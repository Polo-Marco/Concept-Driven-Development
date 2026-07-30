#!/usr/bin/env python3
"""Offline self-test for the CDD 8.1 loop driver.

No API key, no network, no `claude` login required. Every model call is
replaced by a stub, so the whole state machine runs in milliseconds.
This is the M1/M2-equivalent gate for the driver's deterministic half —
the half where all of v8.0's known defects lived.

    python3 .claude/driver/test_loop.py          # all suites
    python3 .claude/driver/test_loop.py -v       # verbose

What it covers, and which v8.0 defect each case pins down:

  check_criteria      fail-closed on missing/corrupt source, absent
                      metric, uncomparable types; nested `metrics{}`
  validate_goal       a contract with no machine-checkable criterion,
                      an unknown operator, missing budgets
  preflight           exit-code gating; abort before any model call
  budget_exceeded     max_usd  (8.0: metered, never enforced)
  run_trial           GPU-hours billed from trial start, not last poll
                      (8.0: t0 reset every poll -> cap never tripped);
                      a killed crash-class trial returns False
                      (8.0: returned True -> Evaluator scored a
                      truncated run)
  contract review     missing/corrupt verdict.json -> REVISE, not OK
                      (8.0: defaulted to "OK", fail-open safety gate)
  machinery           refuse to start when parts are missing or the
                      PreToolUse hook is unwired
  state machine       PASS / RETRY->PASS / regression / final gate
  trial exit code     a self-inflicted non-zero exit is not a
                      completed trial (8.1 covered only driver-caused
                      exits, so a crash was graded as output)
  spend accounting    spent_usd survives a phase-level save, so max_usd
                      is a real cap (8.1: claude() saved a private copy
                      that the next save(STATE, st) wiped)
  field()             multi-line ticket fields kept whole (8.1: `(.+)$`
                      dropped every line but the first, silently
                      disarming a multi-line Monitor Profile)
  approve             targets the pending gate and refuses when none is
                      (8.1 touched both flags; an early approve was a
                      silent no-op)
  ticket marking      the driver's own [x] keeps the heading parseable
                      (8.1: a finished ticket vanished from tickets())
  git_commit          a refused or empty commit returns "" instead of
                      the previous sha, and a PASS that did not land in
                      git escalates rather than marking the ticket done
  start               one command makes the worktree, pins
                      CLAUDE_PROJECT_DIR and launches under tmux; refuses
                      to run a second driver for the same goal
  status              renders ticket progress, criteria, budgets vs caps
                      and a pending gate instead of raw JSON
  auth gate           an unauthenticated `claude` CLI aborts gate 1
                      instead of failing as "contract review twice"
  hook                deny/allow matrix per CDD_ROLE, driven by real
                      PreToolUse JSON on stdin — both the Write/Edit
                      branch and (8.1) the Bash write-target scan, plus
                      one test that pins the interpreter-escape gap as
                      knowingly out of scope
"""
import json
import os
import shutil
import contextlib
import io
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
HOOK = HERE.parent / "hooks" / "enforce_authority.py"

import loop  # noqa: E402  (import after sys.path juggling)

# DriverCase stubs require_cli to keep the suite offline; keep a
# handle on the real one so TestAuthGate can exercise it.
REAL_REQUIRE_CLI = loop.require_cli


# ---------- harness ----------------------------------------------------

def use_root(tmp: Path) -> None:
    """Rebind the driver's module-level paths onto a throwaway root."""
    loop.ROOT = tmp
    loop.GOAL = tmp / "goal.json"
    loop.STATE = tmp / "loop-state.json"
    loop.LEDGER = tmp / "ledger.jsonl"
    loop.EVENTS = tmp / "events.jsonl"
    loop.VERDICT = tmp / "verdict.json"
    loop.APPROVALS = tmp / "approvals"
    loop.AGENTS = tmp / ".claude" / "agents"
    loop.SETTINGS = tmp / ".claude" / "settings.json"
    loop.NOTIFY = tmp / ".claude" / "driver" / "notify.sh"


def install_machinery(tmp: Path, wired: bool = True) -> None:
    (tmp / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
    (tmp / ".claude" / "hooks").mkdir(parents=True, exist_ok=True)
    (tmp / ".claude" / "rules").mkdir(parents=True, exist_ok=True)
    for r in loop.ROLES:
        (tmp / ".claude" / "agents" / f"cdd-{r}.md").write_text(f"# {r}")
    (tmp / ".claude" / "hooks" / "enforce_authority.py").write_text("#")
    (tmp / ".claude" / "rules" / "loop-protocol.md").write_text("#")
    hooks = {"hooks": {"PreToolUse": [{"hooks": [{"command":
             "python3 .claude/hooks/enforce_authority.py"}]}]}} \
        if wired else {"hooks": {}}
    (tmp / ".claude" / "settings.json").write_text(json.dumps(hooks))


class FakeClock:
    """Deterministic replacement for the `time` module inside loop.py."""

    def __init__(self, start=1_000_000.0, step=0.0):
        self.t, self.step = start, step

    def time(self):
        return self.t

    def sleep(self, _sec):
        self.t += self.step


class DriverCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cdd-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self._real_time = loop.time
        self.addCleanup(lambda: setattr(loop, "time", self._real_time))
        # v8.1.1: stubs used to leak between tests -- a case that
        # replaced loop.claude left it replaced for every case after it,
        # making the suite order-dependent.
        for _n in ("claude", "git_commit", "subprocess", "sh",
                   "require_cli"):
            self.addCleanup(setattr, loop, _n, getattr(loop, _n))
        # the suite is offline by contract; TestAuthGate exercises
        # the real probe with a stubbed subprocess.
        loop.require_cli = lambda: None
        use_root(self.tmp)
        install_machinery(self.tmp)
        (self.tmp / "logs").mkdir(exist_ok=True)

    def write_goal(self, **over):
        cfg = {"goal": "test goal", "type": "modify",
               "criteria": [{"metric": "acc", "op": ">", "value": 0.0,
                             "source": "results/out.json"}],
               "budgets": {"max_iterations": 8, "max_usd": 10},
               "evaluation_cadence": "per-iteration",
               "monitor": {"interval_min": 1}}
        cfg.update(over)
        loop.GOAL.write_text(json.dumps(cfg))
        return cfg

    def results(self, payload, path="results/out.json"):
        p = self.tmp / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(payload if isinstance(payload, str)
                     else json.dumps(payload))

    def events(self):
        if not loop.EVENTS.exists():
            return []
        return [json.loads(l) for l in
                loop.EVENTS.read_text().splitlines() if l.strip()]

    def ledger(self):
        if not loop.LEDGER.exists():
            return []
        return [json.loads(l) for l in
                loop.LEDGER.read_text().splitlines() if l.strip()]


# ---------- gate 4: check_criteria ------------------------------------

class TestCheckCriteria(DriverCase):

    def test_nested_metrics_pass(self):
        cfg = self.write_goal()
        self.results({"metrics": {"acc": 0.31}})
        ok, res = loop.check_criteria(cfg)
        self.assertTrue(ok)
        self.assertEqual(res[0]["actual"], 0.31)

    def test_flat_metric_pass(self):
        cfg = self.write_goal()
        self.results({"acc": 0.31})
        ok, _ = loop.check_criteria(cfg)
        self.assertTrue(ok)

    def test_threshold_not_met(self):
        cfg = self.write_goal()
        self.results({"metrics": {"acc": 0.0}})     # the MMMU-zero case
        ok, res = loop.check_criteria(cfg)
        self.assertFalse(ok)
        self.assertEqual(res[0]["why"], "threshold not met")

    def test_missing_source_fails_closed(self):
        cfg = self.write_goal()
        ok, res = loop.check_criteria(cfg)
        self.assertFalse(ok)
        self.assertIn("does not exist", res[0]["why"])

    def test_corrupt_source_fails_closed(self):
        cfg = self.write_goal()
        self.results("{not json")
        ok, res = loop.check_criteria(cfg)
        self.assertFalse(ok)
        self.assertIn("not readable JSON", res[0]["why"])

    def test_absent_metric_fails_closed(self):
        cfg = self.write_goal()
        self.results({"metrics": {"other": 1}})
        ok, res = loop.check_criteria(cfg)
        self.assertFalse(ok)
        self.assertIn("not in", res[0]["why"])

    def test_uncomparable_types_fail_closed(self):
        cfg = self.write_goal()
        self.results({"metrics": {"acc": "high"}})
        ok, res = loop.check_criteria(cfg)
        self.assertFalse(ok)
        self.assertIn("cannot compare", res[0]["why"])

    def test_no_criteria_is_not_a_pass(self):
        cfg = self.write_goal(criteria=[])
        ok, res = loop.check_criteria(cfg)
        self.assertFalse(ok, "an empty criteria list must not pass")
        self.assertEqual(res, [])

    def test_all_operators(self):
        for op, val, actual, expect in [(">=", 1, 1, True),
                                        (">", 1, 1, False),
                                        ("<=", 1, 1, True),
                                        ("<", 1, 0, True),
                                        ("==", 1, 1, True),
                                        ("!=", 1, 1, False)]:
            cfg = self.write_goal(criteria=[{"metric": "m", "op": op,
                                             "value": val,
                                             "source": "r.json"}])
            self.results({"metrics": {"m": actual}}, "r.json")
            ok, _ = loop.check_criteria(cfg)
            self.assertEqual(ok, expect, f"{actual} {op} {val}")


# ---------- gate 2: validate_goal -------------------------------------

class TestValidateGoal(DriverCase):

    def assertDies(self, cfg, needle):
        with self.assertRaises(SystemExit):
            with open(os.devnull, "w") as null:
                real, sys.stderr = sys.stderr, null
                try:
                    loop.validate_goal(cfg)
                finally:
                    sys.stderr = real

    def test_rejects_empty_criteria(self):
        self.assertDies({"criteria": [], "budgets": {"max_usd": 1}},
                        "criteria")

    def test_rejects_missing_criteria(self):
        self.assertDies({"budgets": {"max_usd": 1}}, "criteria")

    def test_rejects_unknown_operator(self):
        self.assertDies({"criteria": [{"metric": "a", "op": "~=",
                                       "value": 1, "source": "s"}],
                         "budgets": {"max_usd": 1}}, "op")

    def test_rejects_missing_budgets(self):
        self.assertDies({"criteria": [{"metric": "a", "op": ">",
                                       "value": 1, "source": "s"}]},
                        "budgets")

    def test_rejects_malformed_preflight(self):
        self.assertDies({"criteria": [{"metric": "a", "op": ">",
                                       "value": 1, "source": "s"}],
                         "budgets": {"max_usd": 1},
                         "preflight": [{"run": "true"}]}, "preflight")

    def test_accepts_valid_contract(self):
        loop.validate_goal({"criteria": [{"metric": "a", "op": ">",
                                          "value": 1, "source": "s"}],
                            "budgets": {"max_usd": 1},
                            "preflight": [{"name": "n", "run": "true"}]})


# ---------- gate 3: preflight -----------------------------------------

class TestPreflight(DriverCase):

    def test_all_pass(self):
        loop.preflight({"preflight": [{"name": "yes", "run": "true"}]})
        self.assertEqual([e for e in self.events()
                          if e["event"] == "preflight"][0]["detail"][:2],
                         "ok")

    def test_any_failure_aborts(self):
        with self.assertRaises(SystemExit):
            with open(os.devnull, "w") as null:
                real, sys.stderr = sys.stderr, null
                try:
                    loop.preflight({"preflight": [
                        {"name": "ok one", "run": "true"},
                        {"name": "missing env", "run": "test -f .env"}]})
                finally:
                    sys.stderr = real

    def test_none_declared_is_logged_not_silent(self):
        loop.preflight({})
        self.assertTrue(any(e["event"] == "preflight_none"
                            for e in self.events()))

    def test_output_is_not_logged(self):
        """A check that prints a secret must not leak it into events."""
        loop.preflight({"preflight": [
            {"name": "leaky", "run": "echo sk-SECRET-abc123"}]})
        self.assertNotIn("SECRET", loop.EVENTS.read_text())


# ---------- budgets ---------------------------------------------------

class TestBudgets(DriverCase):

    def test_max_usd_enforced(self):
        """v8.0 metered spent_usd but budget_exceeded never read it."""
        cfg = {"budgets": {"max_usd": 5}}
        self.assertEqual(loop.budget_exceeded({"spent_usd": 4.9}, cfg), "")
        self.assertEqual(loop.budget_exceeded({"spent_usd": 5.0}, cfg),
                         "max_usd")

    def test_gpu_hours_enforced(self):
        cfg = {"budgets": {"max_gpu_hours": 2}}
        self.assertEqual(loop.budget_exceeded({"gpu_hours": 2.1}, cfg),
                         "max_gpu_hours")

    def test_iterations_and_replans(self):
        self.assertEqual(loop.budget_exceeded(
            {"iteration": 8}, {"budgets": {"max_iterations": 8}}),
            "max_iterations")
        self.assertEqual(loop.budget_exceeded(
            {"replans": 4}, {"budgets": {"max_replans": 3}}),
            "max_replans")


# ---------- trials ----------------------------------------------------

class TestRunTrial(DriverCase):

    def test_no_trial_field_is_a_noop(self):
        st = {"iteration": 1}
        self.assertTrue(loop.run_trial("T", "no fields here", st,
                                       self.write_goal()))

    def test_gpu_hours_billed_from_trial_start(self):
        """v8.0 reset t0 on every poll, so only the last interval was
        ever billed and max_gpu_hours could not trip."""
        clock = FakeClock(step=1800.0)          # 30 min per sleep()
        loop.time = clock
        cfg = self.write_goal(monitor={"interval_min": 1})
        st = {"iteration": 1}
        body = "**Trial:** sleep 0.2\n**Monitor Profile:** none"
        loop.claude = lambda *a, **k: '{"status": "HEALTHY"}'
        loop.run_trial("T", body, st, cfg)
        # The fake clock advances well past an hour; billing must reflect
        # elapsed-since-start, not since-last-poll.
        self.assertGreater(st["gpu_hours"], 0.4)

    def test_killed_trial_returns_false(self):
        """v8.0 returned True after a crash-class kill, so the Evaluator
        graded a truncated run."""
        clock = FakeClock(step=600.0)
        loop.time = clock
        cfg = self.write_goal(monitor={"interval_min": 1})
        st = {"iteration": 2}
        body = "**Trial:** sleep 30\n**Monitor Profile:** cuda_oom"
        loop.claude = lambda *a, **k: json.dumps(
            {"status": "INTERVENE", "signature": "cuda_oom"})
        self.assertFalse(loop.run_trial("T", body, st, cfg))
        self.assertTrue(any(e["event"] == "trial_killed"
                            for e in self.events()))
        self.assertGreater(st["gpu_hours"], 0.0,
                           "a killed trial must still be billed")

    def test_kill_escalate_returns_false(self):
        clock = FakeClock(step=600.0)
        loop.time = clock
        cfg = self.write_goal(monitor={"interval_min": 1})
        st = {"iteration": 3}
        body = "**Trial:** sleep 30\n**Monitor Profile:** x"
        loop.claude = lambda *a, **k: json.dumps(
            {"status": "KILL_ESCALATE", "evidence": "disk full"})
        self.assertFalse(loop.run_trial("T", body, st, cfg))


# ---------- contract review (fail-closed) -----------------------------

class TestContractReview(DriverCase):

    def test_missing_verdict_is_revise_not_ok(self):
        """v8.0: load(VERDICT, {}).get("verdict", "OK") — a crashed
        Evaluator silently passed the safety pre-gate."""
        calls = []

        def fake(_st, role, prompt, *a, **k):
            calls.append(role)
            return ""                      # never writes verdict.json
        loop.claude = fake
        st = {}
        with self.assertRaises(SystemExit):
            loop.phase_contract_review(self.write_goal(), st)
        self.assertEqual(calls.count("evaluator"), 2)
        self.assertTrue(any(e["event"] == "contract_review_unreadable"
                            for e in self.events()))

    def test_corrupt_verdict_is_revise(self):
        def fake(_st, role, prompt, *a, **k):
            loop.VERDICT.write_text("{broken")
            return ""
        loop.claude = fake
        with self.assertRaises(SystemExit):
            loop.phase_contract_review(self.write_goal(), {})

    def test_ok_verdict_advances_to_gate(self):
        def fake(_st, role, prompt, *a, **k):
            loop.VERDICT.write_text(json.dumps({"verdict": "OK"}))
            return ""
        loop.claude = fake
        st = {}
        loop.phase_contract_review(self.write_goal(), st)
        self.assertEqual(st["phase"], "gate")


# ---------- gate 1: machinery -----------------------------------------

class TestMachinery(DriverCase):

    def assertDies(self):
        return self.assertRaises(SystemExit)

    def test_missing_agent_aborts(self):
        (self.tmp / ".claude" / "agents" / "cdd-monitor.md").unlink()
        with self.assertDies():
            with open(os.devnull, "w") as null:
                real, sys.stderr = sys.stderr, null
                try:
                    loop.machinery()
                finally:
                    sys.stderr = real

    def test_unwired_hook_aborts(self):
        install_machinery(self.tmp, wired=False)
        with self.assertDies():
            with open(os.devnull, "w") as null:
                real, sys.stderr = sys.stderr, null
                try:
                    loop.machinery()
                finally:
                    sys.stderr = real

    def test_complete_install_passes(self):
        loop.machinery()
        self.assertTrue(any(e["event"] == "machinery_ok"
                            for e in self.events()))


# ---------- the state machine, with a stubbed Claude -----------------

PLAN = """# Plan

### Phase 1, Step 1: First ticket
**Boundary:** src/
**Run Command:** true

### Phase 1, Step 2: Second ticket
**Boundary:** src/other/
**Run Command:** true
"""


class TestStateMachine(DriverCase):

    def setUp(self):
        super().setUp()
        (self.tmp / "Plan.md").write_text(PLAN)
        loop.git_commit = lambda msg: "deadbee"

    def test_pass_path_marks_and_commits_each_ticket(self):
        cfg = self.write_goal()
        self.results({"metrics": {"acc": 0.5}})

        def fake(_st, role, prompt, *a, **k):
            if role == "evaluator":
                loop.VERDICT.write_text(json.dumps(
                    {"verdict": "PASS", "reason": "ok",
                     "evidence": ["pytest: 3 passed"]}))
            return "done"
        loop.claude = fake
        st = {"phase": "iterate", "iteration": 0, "replans": 0,
              "spent_usd": 0.0, "gpu_hours": 0.0, "criteria_green": [],
              "started_epoch": loop.time.time()}
        loop.phase_iterate(cfg, st)
        self.assertEqual(st["phase"], "final_eval")
        self.assertEqual((self.tmp / "Plan.md").read_text().count("[x]"), 2)
        self.assertEqual(len([e for e in self.events()
                              if e["event"] == "ticket_done"]), 2)

    def test_criteria_regression_forces_retry_without_a_model(self):
        """A criterion that was green going red is a RETRY on the
        deterministic evidence alone — no Evaluator opinion involved."""
        cfg = self.write_goal(evaluation_cadence="final-pass")
        self.results({"metrics": {"acc": 0.5}})
        state = {"n": 0}

        def fake(_st, role, prompt, *a, **k):
            if role == "generator":
                state["n"] += 1
                if state["n"] == 1:
                    self.results({"metrics": {"acc": 0.0}})   # breaks it
                else:
                    self.results({"metrics": {"acc": 0.5}})   # fixes it
            return "done"
        loop.claude = fake
        st = {"phase": "iterate", "iteration": 0, "replans": 0,
              "spent_usd": 0.0, "gpu_hours": 0.0,
              "criteria_green": ["acc"],          # was green before
              "started_epoch": loop.time.time()}
        loop.phase_iterate(cfg, st)
        self.assertTrue(any(e["event"] == "regression"
                            for e in self.events()))
        self.assertTrue(any(r["verdict"] == "RETRY"
                            for r in self.ledger()))

    def test_final_pass_cadence_is_no_longer_unchecked(self):
        """v8.0 auto-PASSed with zero checks under final-pass. Now the
        deterministic gate still runs and a failing criterion blocks."""
        cfg = self.write_goal(evaluation_cadence="final-pass")
        self.results({"metrics": {"acc": 0.0}})   # never satisfied
        loop.claude = lambda *a, **k: "done"
        st = {"phase": "iterate", "iteration": 0, "replans": 0,
              "spent_usd": 0.0, "gpu_hours": 0.0, "criteria_green": [],
              "started_epoch": loop.time.time()}
        loop.phase_iterate(cfg, st)
        ledger = self.ledger()
        self.assertTrue(ledger, "the ledger must record the attempt")
        self.assertTrue(all("criteria" in r for r in ledger),
                        "every ledger row carries a criteria snapshot")

    def test_budget_stops_before_next_ticket(self):
        cfg = self.write_goal(budgets={"max_iterations": 1, "max_usd": 10})
        self.results({"metrics": {"acc": 0.5}})
        loop.claude = lambda *a, **k: "done"
        st = {"phase": "iterate", "iteration": 1, "replans": 0,
              "spent_usd": 0.0, "gpu_hours": 0.0, "criteria_green": [],
              "started_epoch": loop.time.time()}
        loop.phase_iterate(cfg, st)
        self.assertTrue(any("budget exhausted" in str(e.get("detail"))
                            for e in self.events()))

    def test_generator_stop_escalates(self):
        cfg = self.write_goal()
        self.results({"metrics": {"acc": 0.5}})
        loop.claude = lambda _st, role, *a, **k: (
            "STATUS: stopped — needs an architectural decision"
            if role == "generator" else "")
        st = {"phase": "iterate", "iteration": 0, "replans": 0,
              "spent_usd": 0.0, "gpu_hours": 0.0, "criteria_green": [],
              "started_epoch": loop.time.time()}
        loop.phase_iterate(cfg, st)
        self.assertTrue(any(e["event"] == "escalate"
                            for e in self.events()))
        self.assertNotIn("[x]", (self.tmp / "Plan.md").read_text())

    def test_final_gate_blocks_before_paying_the_evaluator(self):
        cfg = self.write_goal()
        self.results({"metrics": {"acc": 0.0}})
        calls = []
        loop.claude = lambda _st, role, *a, **k: (calls.append(role)
                                                 or "")
        st = {}
        loop.phase_final(cfg, st)
        self.assertEqual(calls, [], "no Evaluator call on a failed gate")
        self.assertNotEqual(st.get("phase"), "done")

    def test_final_gate_then_provenance_audit(self):
        cfg = self.write_goal()
        self.results({"metrics": {"acc": 0.5}})
        prompts = []

        def fake(_st, role, prompt, *a, **k):
            prompts.append(prompt)
            loop.VERDICT.write_text(json.dumps(
                {"verdict": "PASS", "reason": "provenance corroborated"}))
            return ""
        loop.claude = fake
        st = {}
        loop.phase_final(cfg, st)
        self.assertEqual(st["phase"], "done")
        self.assertIn("PROVENANCE", prompts[0])


# ---------- the PreToolUse hook, driven by real JSON ------------------

class HookCaller:
    """Shared plumbing. Not a TestCase, so nothing here is collected
    twice by the subclasses below."""

    ALLOW, DENY = 0, 2

    def call(self, role, tool, tool_input, boundary=""):
        env = {**os.environ, "CDD_ROLE": role, "CDD_BOUNDARY": boundary,
               "CLAUDE_PROJECT_DIR": "/repo"}
        r = subprocess.run([sys.executable, str(HOOK)], env=env, text=True,
                           input=json.dumps({"tool_name": tool,
                                             "tool_input": tool_input}),
                           capture_output=True)
        return r.returncode


class TestHook(HookCaller, unittest.TestCase):
    """Offline replacement for INSTALL.md's M1: exhaustive rather than
    end-to-end, and it needs no `claude` login."""

    def test_interactive_session_unrestricted(self):
        self.assertEqual(self.call("", "Write",
                                   {"file_path": "/repo/Concept.md"}),
                         self.ALLOW)

    def test_git_writes_denied_for_every_role(self):
        for role in ("planner", "generator", "evaluator", "monitor"):
            for cmd in ("git commit -m x", "git add -A", "git push",
                        "git worktree add ../x", "git reset --hard"):
                self.assertEqual(self.call(role, "Bash", {"command": cmd}),
                                 self.DENY, f"{role}: {cmd}")

    def test_read_only_git_allowed(self):
        for cmd in ("git status", "git log --oneline", "git diff HEAD"):
            self.assertEqual(self.call("generator", "Bash",
                                       {"command": cmd}), self.ALLOW, cmd)

    def test_goal_files_protected_from_all_roles(self):
        for role in ("planner", "generator", "evaluator"):
            for f in ("goal.json", "Goal.md", "ledger.jsonl",
                      "loop-state.json", "events.jsonl"):
                self.assertEqual(self.call(role, "Write",
                                           {"file_path": f"/repo/{f}"}),
                                 self.DENY, f"{role}: {f}")

    def test_generator_denied_core_files(self):
        for f in ("Concept.md", "Architecture.md", "README.md", "Plan.md",
                  "CLAUDE.md", "skills/mode-loop/SKILL.md",
                  "docs/api.md"):
            self.assertEqual(self.call("generator", "Write",
                                       {"file_path": f"/repo/{f}"}),
                             self.DENY, f)

    def test_generator_boundary(self):
        self.assertEqual(self.call("generator", "Write",
                                   {"file_path": "/repo/src/foo/a.py"},
                                   boundary="src/foo/"), self.ALLOW)
        self.assertEqual(self.call("generator", "Write",
                                   {"file_path": "/repo/src/bar/a.py"},
                                   boundary="src/foo/"), self.DENY)

    def test_evaluator_writes_only_its_two_files(self):
        self.assertEqual(self.call("evaluator", "Write",
                                   {"file_path": "/repo/Evaluation.md"}),
                         self.ALLOW)
        self.assertEqual(self.call("evaluator", "Write",
                                   {"file_path": "/repo/verdict.json"}),
                         self.ALLOW)
        self.assertEqual(self.call("evaluator", "Write",
                                   {"file_path": "/repo/src/a.py"}),
                         self.DENY)

    def test_monitor_writes_nothing(self):
        self.assertEqual(self.call("monitor", "Write",
                                   {"file_path": "/repo/logs/x.log"}),
                         self.DENY)

    def test_planner_denied_src_and_docs(self):
        self.assertEqual(self.call("planner", "Write",
                                   {"file_path": "/repo/src/a.py"}),
                         self.DENY)
        self.assertEqual(self.call("planner", "Write",
                                   {"file_path": "/repo/docs/api.md"}),
                         self.DENY)
        self.assertEqual(self.call("planner", "Write",
                                   {"file_path": "/repo/docs/DEVIATIONS.md"}),
                         self.ALLOW)
        self.assertEqual(self.call("planner", "Write",
                                   {"file_path": "/repo/Architecture.md"}),
                         self.ALLOW)


class TestHookBashWrites(HookCaller, unittest.TestCase):
    """The Bash branch (v8.1). Before this, core files and ticket
    Boundaries were unguarded on the shell path: `echo x >
    Architecture.md` was allowed for every role, so the authority matrix
    was enforcement for Write and prose for Bash."""

    def bash(self, role, cmd, boundary=""):
        return self.call(role, "Bash", {"command": cmd}, boundary)

    # ---- core files ---------------------------------------------------

    def test_redirect_to_core_file_denied(self):
        for cmd in ("echo hi > Architecture.md",
                    "echo hi >> Concept.md",
                    "cat x > README.md",
                    "echo x > Plan.md",
                    "echo x > CLAUDE.md",
                    "echo x > skills/mode-loop/SKILL.md"):
            self.assertEqual(self.bash("generator", cmd), self.DENY, cmd)

    def test_sed_inplace_on_core_denied(self):
        self.assertEqual(self.bash("generator",
                                   "sed -i 's/a/b/' Plan.md"), self.DENY)
        self.assertEqual(self.bash("generator",
                                   "sed -i.bak 's/a/b/' Architecture.md"),
                         self.DENY)

    def test_cp_mv_rm_dd_to_core_denied(self):
        for cmd in ("cp template.md README.md",
                    "mv notes.md Concept.md",
                    "rm Concept.md",
                    "rm -f Architecture.md",
                    "dd if=/dev/zero of=Architecture.md",
                    "truncate -s 0 Plan.md",
                    "tee Architecture.md < x"):
            self.assertEqual(self.bash("generator", cmd), self.DENY, cmd)

    def test_reading_core_files_still_allowed(self):
        for cmd in ("cat Architecture.md",
                    "grep -n foo Concept.md",
                    "head -20 Plan.md",
                    "git log --oneline",
                    "git diff HEAD -- Architecture.md"):
            self.assertEqual(self.bash("generator", cmd), self.ALLOW, cmd)

    # ---- ticket boundary ---------------------------------------------

    def test_shell_write_inside_boundary_allowed(self):
        self.assertEqual(self.bash("generator", "echo x > src/foo/a.py",
                                   boundary="src/foo/"), self.ALLOW)
        self.assertEqual(self.bash("generator",
                                   "mv src/foo/a.py src/foo/b.py",
                                   boundary="src/foo/"), self.ALLOW)

    def test_shell_write_outside_boundary_denied(self):
        self.assertEqual(self.bash("generator", "echo x > src/bar/a.py",
                                   boundary="src/foo/"), self.DENY)
        self.assertEqual(self.bash("generator",
                                   "sed -i 's/a/b/' src/bar/a.py",
                                   boundary="src/foo/"), self.DENY)

    # ---- logs/ must stay writable for every role --------------------

    def test_run_command_tee_to_logs_allowed(self):
        """Every ticket's Run Command tees to logs/latest.log, and the
        Evaluator is REQUIRED to execute it. Blocking logs/ would make
        the Evaluator unable to do its job."""
        cmd = "pytest tests/ -v 2>&1 | tee logs/latest.log"
        for role in ("generator", "evaluator", "planner"):
            self.assertEqual(self.bash(role, cmd, boundary="src/foo/"),
                             self.ALLOW, role)

    def test_monitor_still_writes_nothing(self):
        self.assertEqual(self.bash("monitor", "echo x > logs/a.log"),
                         self.DENY)
        self.assertEqual(self.bash("monitor", "echo x > anything.txt"),
                         self.DENY)

    # ---- role parity with the Write branch --------------------------

    def test_evaluator_shell_write_denied(self):
        self.assertEqual(self.bash("evaluator", "echo hello > notes.txt"),
                         self.DENY)
        self.assertEqual(self.bash("evaluator", "echo x > Evaluation.md"),
                         self.ALLOW)

    def test_planner_shell_write_to_src_denied(self):
        self.assertEqual(self.bash("planner", "echo x > src/a.py"),
                         self.DENY)
        self.assertEqual(self.bash("planner", "echo x > docs/api.md"),
                         self.DENY)
        self.assertEqual(self.bash("planner",
                                   "echo x >> docs/DEVIATIONS.md"),
                         self.ALLOW)

    def test_goal_files_denied_on_shell_path(self):
        for role in ("planner", "generator", "evaluator"):
            for cmd in ("echo x > goal.json", "sed -i s/a/b/ Goal.md",
                        "rm ledger.jsonl", "echo x >> events.jsonl"):
                self.assertEqual(self.bash(role, cmd), self.DENY,
                                 f"{role}: {cmd}")

    # ---- outside the repo is the VM's problem ------------------------

    def test_writes_outside_repo_allowed(self):
        """The Evaluator is told to reconstruct prior states in /tmp."""
        for cmd in ("echo x > /tmp/scratch.json",
                    "cat foo > /dev/null",
                    "mkdir -p /tmp/cdd && echo y > /tmp/cdd/a"):
            self.assertEqual(self.bash("evaluator", cmd), self.ALLOW, cmd)

    def test_interactive_session_unaffected(self):
        self.assertEqual(self.bash("", "echo x > Architecture.md"),
                         self.ALLOW)

    # ---- documented gap: this MUST stay allowed knowingly -----------

    def test_interpreter_escape_is_a_known_gap(self):
        """Pinned deliberately. A shell is Turing-complete and a pattern
        matcher is not; adversarial containment is the VM + worktree, not
        this hook (see the hook's module docstring). If someone makes
        this DENY, they have started writing a shell parser — read the
        docstring before changing this test."""
        self.assertEqual(
            self.bash("generator",
                      "python3 -c \"open('Architecture.md','w').write('x')\""),
            self.ALLOW)

# ---------- v8.1.1: fixes traced to the 2026-07-30 retro ---------------

class TestTrialExitCode(DriverCase):
    """8.1 rewrote run_trial to stop grading incomplete trials, but only
    covered the exits the DRIVER causes (budget kill, Monitor kill). A
    trial that died on its own was still reported as completed, so a
    stale artifact on disk could be graded as its output."""

    def setUp(self):
        super().setUp()
        loop.time = FakeClock(step=0.0)     # never reaches a poll
        loop.claude = lambda *a, **k: '{"status": "HEALTHY"}'

    def test_nonzero_exit_is_not_a_completed_trial(self):
        st = {"iteration": 1}
        body = "**Trial:** exit 7\n**Monitor Profile:** none"
        self.assertFalse(loop.run_trial("T", body, st, self.write_goal()))
        ev = [e for e in self.events() if e["event"] == "trial_failed"]
        self.assertEqual(len(ev), 1)
        self.assertIn("exited 7", ev[0]["detail"])

    def test_zero_exit_still_completes(self):
        st = {"iteration": 2}
        body = "**Trial:** true\n**Monitor Profile:** none"
        self.assertTrue(loop.run_trial("T", body, st, self.write_goal()))
        self.assertFalse(any(e["event"] == "trial_failed"
                             for e in self.events()))

    def test_crash_faster_than_one_poll_is_still_caught(self):
        """The loop-1 regression: the trial died at 1m42s against a
        5-minute poll interval, so no Monitor session ever ran and the
        exit code was the only thing left that could notice."""
        calls = []
        loop.claude = lambda *a, **k: (calls.append(1)
                                       or '{"status": "HEALTHY"}')
        cfg = self.write_goal(monitor={"interval_min": 999})
        body = "**Trial:** exit 1\n**Monitor Profile:** none"
        self.assertFalse(loop.run_trial("T", body, {"iteration": 3}, cfg))
        self.assertEqual(calls, [], "no Monitor ran on this path")


class TestSpendAccounting(DriverCase):
    """8.1 enforced max_usd against a number that never accumulated:
    claude() mutated a privately-loaded copy of the state and the next
    phase-level save(STATE, st) wiped it."""

    def stub_session(self, cost):
        real = loop.subprocess
        loop.subprocess = types.SimpleNamespace(
            run=lambda *a, **k: types.SimpleNamespace(
                stdout=json.dumps({"total_cost_usd": cost,
                                   "result": "ok"})),
            Popen=real.Popen, STDOUT=real.STDOUT)
        self.addCleanup(lambda: setattr(loop, "subprocess", real))

    def test_spend_survives_the_phase_boundary(self):
        self.stub_session(10.0)
        cfg = self.write_goal(budgets={"max_usd": 25,
                                       "max_iterations": 99})
        st = {"spent_usd": 0.0, "iteration": 0, "replans": 0,
              "started_epoch": loop.time.time()}
        for _ in range(2):
            loop.claude(st, "planner", "p")
            loop.save(loop.STATE, st)       # what every phase does
        self.assertEqual(st["spent_usd"], 20.0)
        self.assertEqual(loop.load(loop.STATE, {})["spent_usd"], 20.0)
        self.assertEqual(loop.budget_exceeded(st, cfg), "")
        loop.claude(st, "planner", "p")
        self.assertEqual(loop.budget_exceeded(st, cfg), "max_usd")

    def test_unparseable_session_output_costs_nothing(self):
        real = loop.subprocess
        loop.subprocess = types.SimpleNamespace(
            run=lambda *a, **k: types.SimpleNamespace(stdout="not json"),
            Popen=real.Popen, STDOUT=real.STDOUT)
        self.addCleanup(lambda: setattr(loop, "subprocess", real))
        self.write_goal()
        st = {"spent_usd": 1.0}
        self.assertEqual(loop.claude(st, "planner", "p"), "not json")
        self.assertEqual(st["spent_usd"], 1.0)


class TestFieldParsing(DriverCase):
    """8.1's `(.+)$` under re.M took the first physical line and dropped
    the rest, so a multi-line Monitor Profile shipped disarmed."""

    BODY = ("### Phase 1, Step 6: Run harness\n\n"
            "**Input:** configs/eval.yaml\n"
            "**Monitor Profile:** poll every 5 min\n"
            "- cuda_oom: \"CUDA out of memory\"\n"
            "- stall: no new line for 10 min\n"
            "**Boundary:** src/eval/\n"
            "**Run Command:** uv run pytest 2>&1 | tee logs/latest.log\n")

    def test_multiline_field_is_kept_whole(self):
        mp = loop.field(self.BODY, "Monitor Profile")
        self.assertIn("cuda_oom", mp)
        self.assertIn("stall", mp)

    def test_multiline_field_stops_at_the_next_field(self):
        self.assertNotIn("Boundary",
                         loop.field(self.BODY, "Monitor Profile"))

    def test_single_line_fields_unchanged(self):
        self.assertEqual(loop.field(self.BODY, "Input"),
                         "configs/eval.yaml")
        self.assertEqual(loop.field(self.BODY, "Run Command"),
                         "uv run pytest 2>&1 | tee logs/latest.log")

    def test_absent_field_is_empty(self):
        self.assertEqual(loop.field(self.BODY, "Trial"), "")

    def test_field_does_not_bleed_into_the_next_ticket(self):
        two = self.BODY + "\n### Phase 1, Step 7: Next\n\n**Input:** y\n"
        self.assertEqual(loop.field(two, "Run Command"),
                         "uv run pytest 2>&1 | tee logs/latest.log")


class TestApproveGate(DriverCase):
    """8.1 touched BOTH gate flags, and wait_approval() deletes any
    pre-existing flag on entry -- so approving before the driver reached
    the gate silently did nothing."""

    def approve(self, *extra):
        return subprocess.run(
            [sys.executable, str(HERE / "loop.py"), "approve", *extra],
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(self.tmp)},
            capture_output=True, text=True)

    def test_premature_approve_is_refused_loudly(self):
        loop.save(loop.STATE, {"phase": "plan"})
        r = self.approve()
        self.assertEqual(r.returncode, 1)
        self.assertIn("No gate is pending", r.stderr)
        self.assertFalse((self.tmp / "approvals" / "plan.approved")
                         .exists())

    def test_approve_targets_only_the_pending_gate(self):
        loop.save(loop.STATE, {"phase": "gate", "pending_gate": "plan"})
        self.assertEqual(self.approve().returncode, 0)
        self.assertTrue((self.tmp / "approvals" / "plan.approved")
                        .exists())
        self.assertFalse((self.tmp / "approvals" / "replan.approved")
                         .exists())

    def test_explicit_gate_name_is_honoured(self):
        loop.save(loop.STATE, {"phase": "iterate"})
        self.assertEqual(self.approve("replan").returncode, 0)
        self.assertTrue((self.tmp / "approvals" / "replan.approved")
                        .exists())

    def test_pending_gate_is_published_then_cleared(self):
        flag = self.tmp / "approvals" / "plan.approved"
        seen = {}

        class Clock(FakeClock):
            def sleep(self, _sec):
                seen["gate"] = loop.load(loop.STATE, {}).get("pending_gate")
                flag.touch()                # unblock the next check
        loop.time = Clock()
        st = {}
        loop.wait_approval(st, "plan", "review it")
        self.assertEqual(seen["gate"], "plan",
                         "the waiting gate must be visible on disk")
        self.assertIsNone(st["pending_gate"])
        self.assertIsNone(loop.load(loop.STATE, {})["pending_gate"])


class TestHookPlannerNestedClaudeMd(HookCaller, unittest.TestCase):
    """phase-authority.md grants the Planner Read/Write/CREATE on nested
    CLAUDE.md, but the blanket src//tests/ denial made it unreachable --
    the hook contradicting the matrix it exists to enforce."""

    def test_planner_may_create_nested_claude_md(self):
        for f in ("src/eval/adapters/CLAUDE.md", "tests/unit/CLAUDE.md"):
            self.assertEqual(self.call("planner", "Write",
                                       {"file_path": f"/repo/{f}"}),
                             self.ALLOW, f)

    def test_planner_still_denied_real_code(self):
        for f in ("src/eval/adapters/api.py", "tests/unit/test_api.py",
                  "src/notclaude.md"):
            self.assertEqual(self.call("planner", "Write",
                                       {"file_path": f"/repo/{f}"}),
                             self.DENY, f)

    def test_exemption_is_planner_only(self):
        for role in ("generator", "evaluator", "monitor"):
            self.assertEqual(self.call(role, "Write",
                                       {"file_path":
                                        "/repo/src/eval/CLAUDE.md"},
                                       boundary="src/"),
                             self.DENY, role)

    def test_exemption_holds_on_the_bash_path_too(self):
        self.assertEqual(
            self.call("planner", "Bash",
                      {"command": "echo x > src/eval/CLAUDE.md"}),
            self.ALLOW)
        self.assertEqual(
            self.call("planner", "Bash",
                      {"command": "echo x > src/eval/api.py"}),
            self.DENY)


class TestTicketMarking(DriverCase):
    """v8.1: the driver's own `[x]` marker made a finished heading
    unmatchable, so the ticket vanished from tickets() instead of being
    reported done. phase_iterate still terminated -- but only because
    "unparseable" and "done" happened to coincide."""

    def test_marked_ticket_is_parsed_and_flagged_done(self):
        marked = PLAN.replace("### Phase 1, Step 1:",
                              "### Phase 1, Step 1 [x]:")
        got = list(loop.tickets(marked))
        self.assertEqual(len(got), 2)
        self.assertEqual([d for _, _, _, d in got], [True, False])
        self.assertEqual(got[0][0], "Phase 1, Step 1")
        self.assertNotIn("[x]", got[0][1], "the title keeps the marker")

    def test_a_finished_plan_still_lists_every_ticket(self):
        done = PLAN
        for tid in ("Phase 1, Step 1", "Phase 1, Step 2"):
            done = done.replace(f"### {tid}:", f"### {tid} [x]:")
        got = list(loop.tickets(done))
        self.assertEqual(len(got), 2, "a completed plan must still parse")
        self.assertTrue(all(d for _, _, _, d in got))

    def test_round_trips_through_the_driver_s_own_rewrite(self):
        rewritten = PLAN.replace("### Phase 1, Step 1:",
                                 "### Phase 1, Step 1 [x]:", 1)
        todo = [i for i, _, _, d in loop.tickets(rewritten) if not d]
        self.assertEqual(todo, ["Phase 1, Step 2"])

    def test_body_style_marker_still_honoured(self):
        body_marked = PLAN.replace("### Phase 1, Step 1: First ticket",
                                   "### Phase 1, Step 1: First ticket\n"
                                   "- [x] done by hand")
        got = list(loop.tickets(body_marked))
        self.assertEqual([d for _, _, _, d in got], [True, False])


class TestGitCommitIsChecked(DriverCase):
    """v8.1: sh() ignores return codes, so a commit that failed left
    HEAD alone and git_commit returned the PREVIOUS sha -- the driver
    marked the ticket done and reported a loop whose work never entered
    git."""

    def setUp(self):
        super().setUp()
        loop.sh("git init -q .")
        loop.sh("git config user.name t")
        loop.sh("git config user.email t@t")
        (self.tmp / "a.txt").write_text("1")
        loop.sh("git add -A")
        loop.sh("git commit -q -m base")

    def refuse_commits(self):
        h = self.tmp / ".git" / "hooks" / "pre-commit"
        h.parent.mkdir(parents=True, exist_ok=True)
        h.write_text("#!/bin/sh\nexit 1\n")
        h.chmod(0o755)

    def test_successful_commit_returns_a_new_sha(self):
        (self.tmp / "a.txt").write_text("2")
        head = loop.sh("git rev-parse HEAD").stdout.strip()
        sha = loop.git_commit("feat: change")
        self.assertTrue(sha)
        self.assertFalse(head.startswith(sha))
        self.assertNotIn("commit_failed",
                         [e["event"] for e in self.events()])

    def test_refused_commit_returns_empty_and_is_reported(self):
        self.refuse_commits()
        (self.tmp / "a.txt").write_text("3")
        self.assertEqual(loop.git_commit("feat: refused"), "")
        self.assertIn("commit_failed",
                      [e["event"] for e in self.events()])

    def test_nothing_to_commit_is_not_a_sha(self):
        self.assertEqual(loop.git_commit("feat: noop"), "")


class TestPassRequiresACommit(DriverCase):
    """A PASS whose work never reached git is not a PASS."""

    def setUp(self):
        super().setUp()
        (self.tmp / "Plan.md").write_text(PLAN)

    def test_failed_commit_escalates_and_keeps_the_ticket_runnable(self):
        cfg = self.write_goal()
        self.results({"metrics": {"acc": 0.5}})
        loop.git_commit = lambda msg: ""          # commit did not land

        def fake(_st, role, prompt, *a, **k):
            if role == "evaluator":
                loop.VERDICT.write_text(json.dumps(
                    {"verdict": "PASS", "reason": "ok"}))
            return "done"
        loop.claude = fake
        st = {"phase": "iterate", "iteration": 0, "replans": 0,
              "spent_usd": 0.0, "gpu_hours": 0.0, "criteria_green": [],
              "started_epoch": loop.time.time()}
        loop.phase_iterate(cfg, st)
        self.assertNotIn("[x]", (self.tmp / "Plan.md").read_text(),
                         "an uncommitted ticket must stay runnable")
        self.assertTrue(any(e["event"] == "escalate"
                            for e in self.events()))
        self.assertNotEqual(st.get("phase"), "final_eval")


class TestStart(DriverCase):
    """Stage 0: `loop.py start` replaces six manual steps across two
    terminals. It SPAWNS rather than re-execs -- require_isolation()
    refuses to relocate the process that owns every commit, and that
    judgement stands."""

    def setUp(self):
        super().setUp()
        d = self.tmp / ".claude" / "driver"
        d.mkdir(parents=True, exist_ok=True)
        (d / "loop.py").write_text("#")

    def fake_sh(self, has_session=False):
        def sh(cmd, **k):
            rc = 0
            if "has-session" in cmd:
                rc = 0 if has_session else 1
            return types.SimpleNamespace(returncode=rc, stdout="",
                                         stderr="")
        loop.sh = sh

    def capture_tmux(self):
        seen = {}
        real = loop.subprocess

        def run(cmd, **k):
            seen["cmd"] = cmd
            return types.SimpleNamespace(returncode=0, stdout="",
                                         stderr="")
        loop.subprocess = types.SimpleNamespace(
            run=run, Popen=real.Popen, STDOUT=real.STDOUT)
        return seen

    def test_slug_is_branch_safe(self):
        self.assertEqual(loop.slug({"goal": "Run TMMLU+ & write report"}),
                         "run-tmmlu-write-report")
        self.assertEqual(loop.slug({}), "loop")
        self.assertEqual(loop.slug({"goal": "!!!"}), "loop")

    def test_notify_gap_names_the_missing_push(self):
        self.assertIn("notify.sh", loop.notify_gap())
        loop.NOTIFY.parent.mkdir(parents=True, exist_ok=True)
        loop.NOTIFY.write_text("#")
        self.assertEqual(loop.notify_gap(), "")

    def test_launches_tmux_with_the_project_dir_pinned(self):
        self.fake_sh()
        seen = self.capture_tmux()
        with contextlib.redirect_stdout(io.StringIO()):
            loop.phase_start({"goal": "toy goal"}, allow_here=True)
        cmd = seen["cmd"]
        self.assertEqual(cmd[:4], ["tmux", "new-session", "-d", "-s"])
        self.assertEqual(cmd[4], "cdd-toy-goal")
        # An inherited CLAUDE_PROJECT_DIR would point the child at the
        # PRIMARY tree, so it is pinned explicitly rather than inferred.
        self.assertIn(f"CLAUDE_PROJECT_DIR={self.tmp}", cmd[5])
        self.assertIn("tee logs/driver.log", cmd[5])
        self.assertIn("--here", cmd[5])

    def test_refuses_a_second_driver_for_the_same_goal(self):
        self.fake_sh(has_session=True)
        self.capture_tmux()
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stdout(io.StringIO()):
                loop.phase_start({"goal": "toy goal"}, allow_here=True)

    def test_refuses_a_target_without_the_machinery(self):
        (self.tmp / ".claude" / "driver" / "loop.py").unlink()
        self.fake_sh()
        self.capture_tmux()
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stdout(io.StringIO()):
                loop.phase_start({"goal": "toy goal"}, allow_here=True)


class TestStatusView(DriverCase):
    """v8.1 dumped loop-state.json raw, which answers none of the four
    questions a human actually has: where is it, is it stuck, how much
    has it burned, does it need me?"""

    def render(self, cfg):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            loop.phase_status(cfg)
        return buf.getvalue()

    def test_empty_tree_says_so_instead_of_printing_braces(self):
        self.assertIn("Nothing has run", self.render({}))

    def test_shows_progress_criteria_budgets_and_the_pending_gate(self):
        cfg = self.write_goal()
        (self.tmp / "Plan.md").write_text(PLAN.replace(
            "### Phase 1, Step 1:", "### Phase 1, Step 1 [x]:"))
        self.results({"metrics": {"acc": 0.5}})
        loop.save(loop.STATE, {"phase": "iterate", "iteration": 3,
                               "replans": 0, "spent_usd": 4.0,
                               "gpu_hours": 0.0, "pending_gate": "replan",
                               "current_ticket": "Phase 1, Step 2",
                               "started_epoch": loop.time.time(),
                               "started": "2026-07-30T00:00:00+00:00"})
        out = self.render(cfg)
        self.assertIn("1/2 done", out)
        self.assertIn("[x] Phase 1, Step 1", out)
        self.assertIn("[ ] Phase 1, Step 2", out)
        self.assertIn("ok   acc", out)
        self.assertIn("3 / 8", out)              # iterations vs cap
        self.assertIn("$4.00 / $10.00", out)     # spend vs cap
        self.assertIn("WAITING FOR YOU", out)
        self.assertIn("replan", out)

    def test_survives_a_state_with_no_plan_and_no_criteria(self):
        loop.save(loop.STATE, {"phase": "plan"})
        out = self.render({})
        self.assertIn("phase     plan", out)
        self.assertNotIn("WAITING FOR YOU", out)


class TestAuthGate(DriverCase):
    """v8.1: an unauthenticated CLI was invisible. Every session returned
    a normal envelope reading "Not logged in", so the loop burned four
    no-op sessions and escalated with "plan failed contract review
    twice" -- a reason with no relationship to the cause."""

    def setUp(self):
        super().setUp()
        loop.require_cli = REAL_REQUIRE_CLI     # DriverCase stubs it out

    def stub_auth(self, stdout, exc=None):
        real = loop.subprocess

        def run(cmd, **k):
            if exc:
                raise exc
            return types.SimpleNamespace(returncode=0, stdout=stdout,
                                         stderr="")
        loop.subprocess = types.SimpleNamespace(
            run=run, Popen=real.Popen, STDOUT=real.STDOUT,
            DEVNULL=real.DEVNULL, TimeoutExpired=real.TimeoutExpired)
        self.addCleanup(lambda: setattr(loop, "subprocess", real))

    def test_dies_when_not_logged_in(self):
        self.stub_auth('{"loggedIn": false, "authMethod": "none"}')
        with self.assertRaises(SystemExit):
            loop.require_cli()

    def test_passes_when_logged_in(self):
        self.stub_auth('{"loggedIn": true, "authMethod": "oauth"}')
        loop.require_cli()

    def test_dies_when_the_cli_is_missing(self):
        self.stub_auth("", exc=FileNotFoundError())
        with self.assertRaises(SystemExit):
            loop.require_cli()

    def test_unreadable_answer_does_not_block_a_working_loop(self):
        # a future format change must not ground the fleet: the sessions
        # themselves are still the real gate.
        self.stub_auth("some new human-readable output")
        loop.require_cli()


if __name__ == "__main__":
    unittest.main(verbosity=2 if "-v" in sys.argv else 1,
                  argv=[a for a in sys.argv if a != "-v"])
