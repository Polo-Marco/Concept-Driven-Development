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
  hook                deny/allow matrix per CDD_ROLE, driven by real
                      PreToolUse JSON on stdin
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
HOOK = HERE.parent / "hooks" / "enforce_authority.py"

import loop  # noqa: E402  (import after sys.path juggling)


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

        def fake(role, prompt, *a, **k):
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
        def fake(role, prompt, *a, **k):
            loop.VERDICT.write_text("{broken")
            return ""
        loop.claude = fake
        with self.assertRaises(SystemExit):
            loop.phase_contract_review(self.write_goal(), {})

    def test_ok_verdict_advances_to_gate(self):
        def fake(role, prompt, *a, **k):
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

        def fake(role, prompt, *a, **k):
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

        def fake(role, prompt, *a, **k):
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
        loop.claude = lambda role, *a, **k: (
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
        loop.claude = lambda role, *a, **k: calls.append(role) or ""
        st = {}
        loop.phase_final(cfg, st)
        self.assertEqual(calls, [], "no Evaluator call on a failed gate")
        self.assertNotEqual(st.get("phase"), "done")

    def test_final_gate_then_provenance_audit(self):
        cfg = self.write_goal()
        self.results({"metrics": {"acc": 0.5}})
        prompts = []

        def fake(role, prompt, *a, **k):
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

class TestHook(unittest.TestCase):
    """Offline replacement for INSTALL.md's M1: exhaustive rather than
    end-to-end, and it needs no `claude` login."""

    def call(self, role, tool, tool_input, boundary=""):
        env = {**os.environ, "CDD_ROLE": role, "CDD_BOUNDARY": boundary,
               "CLAUDE_PROJECT_DIR": "/repo"}
        r = subprocess.run([sys.executable, str(HOOK)], env=env, text=True,
                           input=json.dumps({"tool_name": tool,
                                             "tool_input": tool_input}),
                           capture_output=True)
        return r.returncode

    ALLOW, DENY = 0, 2

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


if __name__ == "__main__":
    unittest.main(verbosity=2 if "-v" in sys.argv else 1,
                  argv=[a for a in sys.argv if a != "-v"])
