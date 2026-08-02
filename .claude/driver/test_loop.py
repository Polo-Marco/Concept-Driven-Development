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
  find_loop           status/approve resolve the worktree that holds
                      the loop, so they work from the primary tree too
  observability       one heartbeat event per model session, a ticket
                      count after planning, and a driver-alive line in
                      status (8.1: loop_start to human gate was silent)
  Boundary parsing    a Boundary written as markdown (the form the
                      Planner actually emits) still matches real paths,
                      and the tolerance is not a pass-all (8.1: every
                      entry kept its backticks, so a non-empty Boundary
                      matched nothing — a silent global write ban that
                      escalated the first real loop on ticket 1)
  Trial quoting       a backticked Trial reaches Popen as a bare
                      command, not as command substitution
  plan parsing        a ticket heading at any level parses, the done
                      marker keeps that level, and a field stops at the
                      next heading (8.1.3: pinned to `###`, so a `##`
                      plan parsed as zero tickets)
  unparseable plan    "cannot read" is not "finished" — it escalates
                      from phase_plan before a contract review is paid
                      for, and again in phase_iterate, instead of
                      reporting all_tickets_done with nothing built
  human-facing output the gate prints the absolute path to Plan.md, and
                      an escalate reason prints in full instead of a
                      54-character window starting mid-word
  retry feedback      attempt 2 carries the verdict that rejected
                      attempt 1 (8.1.5: the dispatch was the ticket body
                      and nothing else, so a retry could only help a
                      nondeterministic fault)
  no-op session       a Generator that changed nothing, twice, escalates
                      instead of buying a third identical session — but
                      a relaunch after a dead trial still may write
                      nothing
  first green         under `final-pass`, the iteration where a criterion
                      FIRST reads green buys an audit (8.1.5: forged
                      evidence sat green for five committed tickets)
  evidence ownership  at most one ticket's Boundary may admit a
                      criterion's source file, and it must name the file
                      rather than its tree
  budget reload       a raised cap is picked up mid-loop; criteria stay
                      frozen
  journal record      the driver writes one on EVERY terminal exit,
                      including an escalation, and never overwrites the
                      user's Feedback block
  close               refuses an unfinished loop, then records, commits
                      and removes the ephemerals — and leaves the merge
                      to the user
  hook                deny/allow matrix per CDD_ROLE, driven by real
                      PreToolUse JSON on stdin — both the Write/Edit
                      branch and (8.1) the Bash write-target scan, plus
                      one test that pins the interpreter-escape gap as
                      knowingly out of scope
"""
import json
import os
import re
import shutil
import contextlib
import importlib.util
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


def load_hook():
    """Import the hook as a module so its parser can be unit-tested.

    v8.1.3: the hook lives outside any package and is named for its
    executable role, so it cannot be `import`ed. Until now it was only
    ever exercised end-to-end through subprocess, which proved the
    verdicts but never the parsing beneath them -- and the 8.1.3 defect
    lived in the parsing (see TestBoundaryParsing). Loading it here is
    cheaper than moving or duplicating the file; `main()` stays inert
    because the module name is not "__main__".
    """
    spec = importlib.util.spec_from_file_location("cdd_hook", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hook = load_hook()

# DriverCase stubs require_cli to keep the suite offline; keep a
# handle on the real one so TestAuthGate can exercise it.
REAL_REQUIRE_CLI = loop.require_cli
REAL_SH = loop.sh


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
        # .resolve() restores the invariant loop.py:44 gives ROOT in
        # production. git reports worktree paths as realpaths, so an
        # unresolved root makes find_loop() compare /var/... against
        # /private/var/... on macOS -- a harness bug that reads as a
        # driver bug. Resolving in find_loop() instead would still need
        # the test to resolve, so it is two changes for none of the gain.
        self.tmp = Path(tempfile.mkdtemp(prefix="cdd-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self._real_time = loop.time
        self.addCleanup(lambda: setattr(loop, "time", self._real_time))
        # v8.1.1: stubs used to leak between tests -- a case that
        # replaced loop.claude left it replaced for every case after it,
        # making the suite order-dependent.
        # wait_approval joined the list in v8.1.7: TestObservability
        # stubs it, and unittest runs classes in name order, so every
        # later suite silently inherited a gate that never blocks and
        # never emits -- the same leak this loop was written for.
        for _n in ("claude", "git_commit", "subprocess", "sh",
                   "require_cli", "wait_approval", "flush_pregate"):
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


class TestSeedGoalFiles(DriverCase):
    """v8.1.9. `start` re-copied the primary tree's goal.json over the
    worktree's on every resume, and the worktree's is the copy the
    running driver reads. A user-approved budget raise (15 -> 18
    iterations) was silently reverted twice in one loop on 2026-08-02,
    and because a restart itself costs an iteration, each repair round
    paid for the failure it was repairing."""

    def dirs(self):
        primary, wt = self.tmp / "primary", self.tmp / "wt"
        primary.mkdir(), wt.mkdir()
        return primary, wt

    def test_seeds_a_fresh_worktree(self):
        primary, wt = self.dirs()
        (primary / "goal.json").write_text('{"budgets": {"a": 1}}')
        (primary / "Goal.md").write_text("# Goal")
        loop.seed_goal_files(primary, wt)
        self.assertEqual((wt / "goal.json").read_text(),
                         '{"budgets": {"a": 1}}')
        self.assertEqual((wt / "Goal.md").read_text(), "# Goal")

    def test_never_overwrites_the_loops_own_copy(self):
        primary, wt = self.dirs()
        (primary / "goal.json").write_text('{"max_iterations": 15}')
        (wt / "goal.json").write_text('{"max_iterations": 18}')
        with contextlib.redirect_stdout(io.StringIO()) as out:
            loop.seed_goal_files(primary, wt)
        self.assertEqual((wt / "goal.json").read_text(),
                         '{"max_iterations": 18}')
        self.assertIn("WINS", out.getvalue())

    def test_identical_copies_say_nothing(self):
        primary, wt = self.dirs()
        (primary / "goal.json").write_text("same")
        (wt / "goal.json").write_text("same")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            loop.seed_goal_files(primary, wt)
        self.assertEqual(out.getvalue(), "")


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
        # v8.1.4: reviews = revisions + 1, so an always-unreadable
        # verdict is three fail-closed reviews, not two.
        self.assertEqual(calls.count("evaluator"), loop.MAX_REVISIONS + 1)
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

    # ---- v8.1.4: every revision gets reviewed ------------------------

    def test_the_last_revision_is_reviewed_not_discarded(self):
        """2026-07-30 toy run 3: the driver bought a Planner revision
        after its final review, escalated without looking at it, and the
        discarded revision had fixed the very defect the review flagged.
        The escalation named a plan that was no longer on disk."""
        calls = []

        def fake(_st, role, prompt, *a, **k):
            calls.append(role)
            # REVISE, REVISE, then the second revision is good.
            loop.VERDICT.write_text(json.dumps(
                {"verdict": "OK" if calls.count("evaluator") == 3
                 else "REVISE"}))
            return ""
        loop.claude = fake
        st = {}
        loop.phase_contract_review(self.write_goal(), st)
        self.assertEqual(st["phase"], "gate")
        self.assertEqual(calls, ["evaluator", "planner",
                                 "evaluator", "planner", "evaluator"])

    def test_no_revision_is_bought_that_nothing_will_review(self):
        calls = []

        def fake(_st, role, prompt, *a, **k):
            calls.append(role)
            loop.VERDICT.write_text(json.dumps({"verdict": "REVISE"}))
            return ""
        loop.claude = fake
        with self.assertRaises(SystemExit):
            loop.phase_contract_review(self.write_goal(), {})
        self.assertEqual(calls[-1], "evaluator",
                         "the last thing paid for must be a review, so "
                         "Evaluation.md describes the plan on disk")
        self.assertEqual(calls.count("planner"), loop.MAX_REVISIONS)
        self.assertEqual(calls.count("evaluator"), loop.MAX_REVISIONS + 1)


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

    # ---- v8.1.9: reading a protected file is not writing it ----------

    def test_reading_a_goal_file_with_stderr_redirect_allowed(self):
        """The loose net matched `>` ANYWHERE in a command that merely
        NAMED a protected file, so the `>` of `2>&1` read as a write to
        goal.json. On 2026-08-02 that killed a read-only Evaluator audit
        mid-loop; the loop paid for a whole extra session to re-run it
        (journal/from-aibench-retro-20260802.md)."""
        for cmd in ("cat goal.json 2>&1",
                    "python3 -c 'import json' 2>&1 | head",
                    "jq . goal.json 2>&1 | tail -5",
                    "grep -c x ledger.jsonl 2>&1"):
            for role in ("planner", "generator", "evaluator"):
                self.assertEqual(self.bash(role, cmd), self.ALLOW,
                                 f"{role}: {cmd}")

    def test_naming_a_goal_file_while_teeing_elsewhere_allowed(self):
        """Co-occurrence is not a target. A perfectly legal Run Command
        that passes the goal as an argument and tees to logs/ was denied
        for every role, because `goal.json` and `tee` both appeared
        somewhere in the string. The test is per shell segment now."""
        cmd = ("python3 scripts/run.py --goal goal.json 2>&1 "
               "| tee logs/latest.log")
        for role in ("generator", "evaluator", "planner"):
            self.assertEqual(self.bash(role, cmd, boundary="src/foo/"),
                             self.ALLOW, role)

    def test_narrowing_did_not_open_the_write_paths(self):
        """The reason the above is safe: the precise scan denies by
        TARGET, and it is strictly better at it than co-occurrence was."""
        for cmd in ("echo x > goal.json", "echo x >> goal.json",
                    "tee goal.json < a", "cp a goal.json",
                    "mv a Goal.md", "rm -f loop-state.json",
                    "sed -i s/a/b/ ledger.jsonl",
                    "cp goal.json{,.bak}"):   # expansion: the loose net
            self.assertEqual(self.bash("generator", cmd), self.DENY, cmd)

    def test_denial_is_logged_where_the_driver_can_see_it(self):
        """v8.1.9: a denial used to exist only on the agent's stderr, so
        a false positive cost a transcript dig to find. One line per
        denial in logs/denials.log; the driver turns the count into an
        event."""
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "CDD_ROLE": "generator",
                   "CDD_BOUNDARY": "", "CLAUDE_PROJECT_DIR": d}
            r = subprocess.run(
                [sys.executable, str(HOOK)], env=env, text=True,
                input=json.dumps({"tool_name": "Bash",
                                  "tool_input":
                                  {"command": "echo x > Architecture.md"}}),
                capture_output=True)
            self.assertEqual(r.returncode, self.DENY)
            logged = (Path(d) / "logs" / "denials.log").read_text()
            self.assertIn("generator", logged)
            self.assertIn("architecture.md", logged.lower())
            self.assertIn("echo x > Architecture.md", logged)

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


# ---------- v8.1.3: a markdown Boundary must match real paths ---------

class TestBoundaryParsing(unittest.TestCase):
    """The 2026-07-30 toy loop escalated on its first ticket: every
    Write the Generator attempted was denied as a Boundary breach,
    including the files its own ticket named.

    The Planner writes the field as markdown -- ``**Boundary:**
    `src/wordfreq/counter.py`, ...`` -- and loop.py passes it through
    verbatim as CDD_BOUNDARY, so every entry arrived backticked and none
    of the comparisons in in_boundary() could ever match. A non-empty
    Boundary that matches nothing is a silent global write ban that
    reports itself as a breach. 112 green tests missed it because no
    case ever fed a Boundary that looked like what a Planner writes.
    """

    def parse(self, value: str) -> list:
        prev = os.environ.get("CDD_BOUNDARY", "")
        os.environ["CDD_BOUNDARY"] = value
        self.addCleanup(os.environ.__setitem__, "CDD_BOUNDARY", prev)
        return hook.boundary_env()

    def test_backticked_entries_parse_to_bare_paths(self):
        self.assertEqual(
            self.parse("`src/wordfreq/counter.py`, `tests/test_cli.py`"),
            ["src/wordfreq/counter.py", "tests/test_cli.py"])

    def test_quoted_entries_parse_to_bare_paths(self):
        self.assertEqual(self.parse("\"src/a.py\", 'tests/b.py'"),
                         ["src/a.py", "tests/b.py"])

    def test_padding_inside_and_outside_the_markup(self):
        self.assertEqual(self.parse("  ` src/a.py ` ,\n`tests/`  "),
                         ["src/a.py", "tests/"])

    def test_plain_entries_are_unchanged(self):
        self.assertEqual(self.parse("src/a.py, tests/"),
                         ["src/a.py", "tests/"])

    def test_a_backticked_boundary_admits_its_own_files(self):
        b = self.parse("`src/wordfreq/counter.py`, `tests/test_cli.py`")
        for f in ("src/wordfreq/counter.py", "tests/test_cli.py"):
            self.assertIsNone(hook.check_write("generator", f, b), f)

    def test_tolerance_is_not_a_pass_all(self):
        """The failure mode of a sloppy fix: strip the markup so widely
        that the Boundary stops constraining anything."""
        b = self.parse("`src/wordfreq/counter.py`")
        self.assertIsNotNone(
            hook.check_write("generator", "src/other/thing.py", b))
        self.assertIsNotNone(hook.check_write("generator", "src", b))

    def test_core_files_stay_denied_inside_a_wide_boundary(self):
        b = self.parse("`src/`, `Architecture.md`")
        self.assertIsNotNone(
            hook.check_write("generator", "architecture.md", b))
        self.assertIsNone(hook.check_write("generator", "src/a.py", b))


class TestHookMarkdownBoundaryEndToEnd(HookCaller, unittest.TestCase):
    """The same three verdicts through the real process, on the exact
    call that escalated the toy loop."""

    MD = "`src/wordfreq/counter.py`, `tests/test_cli.py`"

    def test_the_escalating_write_is_allowed(self):
        self.assertEqual(
            self.call("generator", "Write",
                      {"file_path": "src/wordfreq/counter.py"},
                      boundary=self.MD), self.ALLOW)

    def test_a_breach_is_still_denied(self):
        self.assertEqual(
            self.call("generator", "Write",
                      {"file_path": "src/other/thing.py"},
                      boundary=self.MD), self.DENY)

    def test_shell_writes_share_the_parse(self):
        """bash_write_targets() and Write/Edit both route through
        check_write, so the fix must reach the shell path too."""
        self.assertEqual(
            self.call("generator", "Bash",
                      {"command": "echo x > src/wordfreq/counter.py"},
                      boundary=self.MD), self.ALLOW)
        self.assertEqual(
            self.call("generator", "Bash",
                      {"command": "echo x > src/other/thing.py"},
                      boundary=self.MD), self.DENY)


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


class TestTrialCommandQuoting(DriverCase):
    """v8.1.3, same seam as TestBoundaryParsing, worse consequence.

    A Planner with the markdown habit writes ``**Trial:** `python3
    train.py` ``. run_trial hands that to Popen(shell=True), where
    backticks are command substitution: the inner command runs, then its
    stdout is executed as a command. It never fired in the toy run only
    because build tickets have no Trial field."""

    def setUp(self):
        super().setUp()
        loop.time = FakeClock(step=0.0)     # never reaches a poll
        loop.claude = lambda *a, **k: '{"status": "HEALTHY"}'

    def test_backticked_trial_reaches_popen_bare(self):
        seen = []
        real = loop.subprocess

        class FakeProc:
            returncode = 0

            def poll(self):
                return 0

        loop.subprocess = types.SimpleNamespace(
            Popen=lambda cmd, **kw: (seen.append(cmd) or FakeProc()),
            STDOUT=real.STDOUT)
        body = ("**Trial:** `python3 train.py --lr 0.1`\n"
                "**Monitor Profile:** none")
        self.assertTrue(loop.run_trial("T", body, {"iteration": 1},
                                       self.write_goal()))
        self.assertEqual(seen, ["python3 train.py --lr 0.1"])

    def test_the_inner_command_output_is_not_executed(self):
        """The consequence, through a real shell. Unstripped, the
        substitution runs `echo` and the outer shell then executes what
        it printed, creating the file. Stripped, the trial merely prints
        it."""
        body = ("**Trial:** `echo touch pwned`\n"
                "**Monitor Profile:** none")
        loop.run_trial("T", body, {"iteration": 2}, self.write_goal())
        self.assertFalse((self.tmp / "pwned").exists(),
                         "the Trial field was evaluated as a command, "
                         "not run as one")


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


# ---------- v8.1.4: the second toy run -------------------------------

PLAN_H2 = PLAN.replace("### ", "## ")     # what the Planner actually wrote


class TestPlanHeadingLevels(DriverCase):
    """The 2026-07-30 re-test: the Planner wrote its tickets as
    `## Phase 1, Step 1: ...` and TICKET was pinned to exactly `### `, so
    the driver parsed ZERO tickets out of a 179-line three-ticket plan --
    and then read "no tickets" as "all tickets done" (TestUnparseablePlan
    below). Same class as the 8.1.3 Boundary defect: a model writes
    markdown in a shape the parser will not accept."""

    def setUp(self):
        super().setUp()
        loop.git_commit = lambda msg: "deadbee"

    def test_h2_and_h4_headings_parse(self):
        for text in (PLAN_H2, PLAN.replace("### ", "#### ")):
            self.assertEqual([i for i, _, _, _ in loop.tickets(text)],
                             ["Phase 1, Step 1", "Phase 1, Step 2"])

    def test_a_heading_that_is_not_a_ticket_stays_ignored(self):
        self.assertEqual(
            list(loop.tickets("# Plan\n\n## Planner Self-Check\ntext\n")),
            [])

    def test_the_marker_preserves_the_heading_level(self):
        """The trap in a naive tolerance fix: the driver marked a done
        ticket with a hardcoded `### `, so a parsed `##` ticket could
        never be marked, and phase_iterate would re-run it until the
        iteration cap."""
        (self.tmp / "Plan.md").write_text(PLAN_H2)
        cfg = self.write_goal()
        self.results({"metrics": {"acc": 0.5}})

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
        text = (self.tmp / "Plan.md").read_text()
        self.assertIn("## Phase 1, Step 1 [x]:", text)
        self.assertNotIn("### ", text, "the level must not be rewritten")
        self.assertEqual(st["phase"], "final_eval")
        self.assertTrue(all(d for _, _, _, d in loop.tickets(text)))

    def test_a_field_stops_at_the_next_heading_of_any_level(self):
        """field()'s lookahead knew only `###`, so the last field of the
        last ticket swallowed whatever prose followed the plan. On a
        **Trial:** field that is a command handed to Popen(shell=True)."""
        body = ("## Phase 1, Step 1: t\n"
                "**Trial:** python3 train.py\n\n"
                "## Planner Self-Check (completed)\n"
                "- everything verified\n")
        self.assertEqual(loop.field(body, "Trial"), "python3 train.py")


class TestUnparseablePlan(DriverCase):
    """The load-bearing half. phase_iterate computed `todo` from
    tickets() and could not tell "finished" from "unreadable", so a plan
    the driver could not parse produced `all_tickets_done` with nothing
    built -- $2.24 of planning, zero Generator sessions, and only the
    criteria gate standing between that and a reported success."""

    NO_TICKETS = "# Plan\n\nJust prose. No tickets the driver can see.\n"

    def test_iterate_escalates_instead_of_claiming_all_done(self):
        (self.tmp / "Plan.md").write_text(self.NO_TICKETS)
        cfg = self.write_goal()
        calls = []
        loop.claude = lambda _st, role, *a, **k: (calls.append(role) or "")
        st = {"phase": "iterate", "iteration": 0, "replans": 0,
              "spent_usd": 0.0, "gpu_hours": 0.0, "criteria_green": [],
              "started_epoch": loop.time.time()}
        loop.phase_iterate(cfg, st)
        kinds = [e["event"] for e in self.events()]
        self.assertIn("escalate", kinds)
        self.assertNotIn("all_tickets_done", kinds)
        self.assertNotEqual(st["phase"], "final_eval",
                            "an unreadable plan must not reach the "
                            "final gate as if the work were done")
        self.assertEqual(calls, [], "nothing may be spent on this path")

    def test_a_genuinely_finished_plan_is_still_all_done(self):
        """The guard must not break the real terminating case."""
        done = PLAN
        for tid in ("Phase 1, Step 1", "Phase 1, Step 2"):
            done = done.replace(f"### {tid}:", f"### {tid} [x]:")
        (self.tmp / "Plan.md").write_text(done)
        st = {"phase": "iterate", "iteration": 0, "replans": 0,
              "spent_usd": 0.0, "gpu_hours": 0.0, "criteria_green": [],
              "started_epoch": loop.time.time()}
        loop.phase_iterate(self.write_goal(), st)
        self.assertIn("all_tickets_done",
                      [e["event"] for e in self.events()])
        self.assertEqual(st["phase"], "final_eval")

    def test_planning_stops_before_paying_for_a_contract_review(self):
        """The cheapest place to catch it: the Planner has just run, the
        Evaluator has not. Reaching the human gate with an unreadable
        plan wasted a review AND the human's time."""
        cfg = self.write_goal()
        loop.claude = lambda _st, role, *a, **k: (
            (self.tmp / "Plan.md").write_text(self.NO_TICKETS) or "")
        st = {"phase": "plan", "iteration": 0, "spent_usd": 0.0}
        with self.assertRaises(SystemExit):
            loop.phase_plan(cfg, st)
        self.assertNotEqual(st.get("phase"), "contract_review")
        self.assertTrue(any(e["event"] == "escalate"
                            for e in self.events()))

    def test_a_missing_plan_escalates_too(self):
        cfg = self.write_goal()
        loop.claude = lambda *a, **k: ""
        with self.assertRaises(SystemExit):
            loop.phase_plan(cfg, {"phase": "plan", "spent_usd": 0.0})
        self.assertTrue(any(e["event"] == "escalate"
                            for e in self.events()))


class TestHumanFacingOutput(DriverCase):
    """journal/feedback-inbox.md 2026-07-30, items 4 and 5: a message
    that exists to make a human act was formatted as a log line."""

    def test_the_gate_prints_where_the_plan_is(self):
        """The loop runs in a worktree, so Plan.md is NOT in the tree
        where the user typed `start`. The banner said "Review it, then
        approve" and never said where."""
        (self.tmp / "Plan.md").write_text(PLAN)
        flag = self.tmp / "approvals" / "plan.approved"
        flag.parent.mkdir(exist_ok=True)
        loop.time = types.SimpleNamespace(
            sleep=lambda _s: flag.touch(), time=lambda: 1_000_000.0)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            loop.wait_approval({}, "plan", "Plan.md ready.")
        self.assertIn(str(self.tmp / "Plan.md"), buf.getvalue(),
                      "print the absolute path -- a relative one is "
                      "wrong from the tree the human is standing in")

    def test_an_escalation_is_not_truncated_in_status(self):
        long = ("generator stopped: " + "x" * 300 + " END")
        loop.save(loop.STATE, {"phase": "iterate", "iteration": 1,
                               "started_epoch": loop.time.time()})
        loop.event("escalate", detail=long)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            loop.phase_status({})
        out = buf.getvalue()
        self.assertIn("END", out, "the reason ends mid-word otherwise")
        self.assertIn("generator stopped", out)

    def test_a_stop_report_is_cut_at_a_word_boundary(self):
        """Printing the detail in full exposed where it was cut: the
        driver stores rep[-400:], which opened mid-word."""
        (self.tmp / "Plan.md").write_text(PLAN)
        report = ("prologue " * 80) + "boundary denial explained. " \
                 "STATUS: stopped"
        loop.claude = lambda *a, **k: report
        st = {"phase": "iterate", "iteration": 0, "replans": 0,
              "spent_usd": 0.0, "gpu_hours": 0.0, "criteria_green": [],
              "started_epoch": loop.time.time()}
        loop.phase_iterate(self.write_goal(), st)
        esc = [e for e in self.events() if e["event"] == "escalate"][0]
        said = esc["detail"].split("generator stopped: ", 1)[1]
        self.assertTrue(said.startswith("prologue"),
                        f"starts mid-word: {said[:30]!r}")
        self.assertIn("boundary denial explained", said)

    def test_a_short_report_is_not_clipped_at_all(self):
        (self.tmp / "Plan.md").write_text(PLAN)
        loop.claude = lambda *a, **k: "needs a decision. STATUS: stopped"
        st = {"phase": "iterate", "iteration": 0, "replans": 0,
              "spent_usd": 0.0, "gpu_hours": 0.0, "criteria_green": [],
              "started_epoch": loop.time.time()}
        loop.phase_iterate(self.write_goal(), st)
        esc = [e for e in self.events() if e["event"] == "escalate"][0]
        self.assertIn("needs a decision.", esc["detail"])

    def test_routine_events_stay_one_line(self):
        loop.save(loop.STATE, {"phase": "iterate", "iteration": 1,
                               "started_epoch": loop.time.time()})
        loop.event("criterion", detail="ok   " + "y" * 300)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            loop.phase_status({})
        self.assertNotIn("y" * 100, buf.getvalue(),
                         "a scannable log line stays truncated")


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
        loop.time = FakeClock()                 # skip the liveness wait

    def fake_sh(self, has_session=False, survives=True):
        seen = {"n": 0}

        def sh(cmd, **k):
            if "tmux" not in cmd:
                return REAL_SH(cmd, **k)        # preflight etc: for real
            rc = 0
            if "has-session" in cmd:
                seen["n"] += 1
                if seen["n"] == 1:              # pre-launch: free slot?
                    rc = 0 if has_session else 1
                else:                           # post-launch: alive?
                    rc = 0 if survives else 1
            return types.SimpleNamespace(returncode=rc, stdout="",
                                         stderr="")
        loop.sh = sh

    def capture_tmux(self):
        seen = {}
        real = loop.subprocess

        def run(cmd, **k):
            # intercept ONLY the tmux launch; sh() goes through
            # subprocess.run too, and preflight must really run.
            if isinstance(cmd, list) and cmd[:1] == ["tmux"]:
                seen["cmd"] = cmd
                return types.SimpleNamespace(returncode=0, stdout="",
                                             stderr="")
            return real.run(cmd, **k)
        loop.subprocess = types.SimpleNamespace(
            run=run, Popen=real.Popen, STDOUT=real.STDOUT,
            DEVNULL=real.DEVNULL, TimeoutExpired=real.TimeoutExpired)
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

    def test_preflight_runs_before_anything_is_created(self):
        """`check` failing and `start` succeeding is a contradiction."""
        self.fake_sh()
        seen = self.capture_tmux()
        cfg = {"goal": "toy goal",
               "preflight": [{"name": "impossible", "run": "exit 1"}]}
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stdout(io.StringIO()):
                loop.phase_start(cfg, allow_here=True)
        self.assertNotIn("cmd", seen, "tmux must not be reached")

    def test_a_driver_that_dies_immediately_is_reported(self):
        self.fake_sh(survives=False)
        self.capture_tmux()
        (self.tmp / "logs").mkdir(exist_ok=True)
        (self.tmp / "logs" / "driver.log").write_text(
            "!! LOOP NOT STARTED\nPreflight failed.\n")
        buf = io.StringIO()
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stdout(buf):
                loop.phase_start({"goal": "toy goal"}, allow_here=True)

    def test_session_name_has_no_trailing_hyphen(self):
        self.fake_sh()
        seen = self.capture_tmux()
        with contextlib.redirect_stdout(io.StringIO()):
            loop.phase_start(
                {"goal": "wordfreq CLI with tests, end to end"},
                allow_here=True)
        self.assertEqual(seen["cmd"][4], "cdd-wordfreq-cli-with-tests")

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


class TestFindLoop(DriverCase):
    """`start` runs in the primary tree, the loop runs in a worktree.
    status/approve typed where you ran start must still find it."""

    def setUp(self):
        super().setUp()
        loop.sh("git init -q .")
        loop.sh("git config user.name t")
        loop.sh("git config user.email t@t")
        (self.tmp / "a.txt").write_text("1")
        loop.sh("git add -A")
        loop.sh("git commit -q -m base")
        self.wt = self.tmp.parent / (self.tmp.name + "-loop")
        self.addCleanup(shutil.rmtree, self.wt, ignore_errors=True)

    def add_worktree(self, with_state=True):
        loop.sh(f"git worktree add -q {self.wt} -b loop/x")
        if with_state:
            (self.wt / "loop-state.json").write_text('{"phase": "gate"}')

    def test_uses_this_tree_when_it_has_the_state(self):
        loop.save(loop.STATE, {"phase": "iterate"})
        self.assertEqual(loop.find_loop(), self.tmp)

    def test_finds_the_loop_in_a_sibling_worktree(self):
        self.add_worktree()
        self.assertEqual(loop.find_loop(), self.wt)

    def test_falls_back_to_here_when_no_loop_exists_anywhere(self):
        self.add_worktree(with_state=False)
        self.assertEqual(loop.find_loop(), self.tmp)

    def test_rebind_moves_every_path(self):
        loop.rebind(self.wt)
        self.addCleanup(use_root, self.tmp)
        self.assertEqual(loop.STATE, self.wt / "loop-state.json")
        self.assertEqual(loop.APPROVALS, self.wt / "approvals")
        self.assertEqual(loop.GOAL, self.wt / "goal.json")


class TestObservability(DriverCase):
    """A silent phase and a dead driver used to render identically."""

    def test_every_session_leaves_a_heartbeat(self):
        self.write_goal()
        real = loop.subprocess
        loop.subprocess = types.SimpleNamespace(
            run=lambda *a, **k: types.SimpleNamespace(
                stdout=json.dumps({"total_cost_usd": 0.5,
                                   "result": "ok"})),
            Popen=real.Popen, STDOUT=real.STDOUT)
        self.addCleanup(lambda: setattr(loop, "subprocess", real))
        loop.claude({}, "planner", "p")
        starts = [e for e in self.events() if e["event"] == "session"]
        self.assertEqual(len(starts), 1)
        self.assertIn("planner", starts[0]["detail"])

    def test_planner_reports_how_many_tickets_it_wrote(self):
        cfg = self.write_goal()
        loop.claude = lambda *a, **k: (
            (self.tmp / "Plan.md").write_text(PLAN) or "")
        loop.phase_plan(cfg, {})
        planned = [e for e in self.events() if e["event"] == "planned"]
        self.assertEqual(planned[0]["detail"], "2 tickets")

    def test_a_planner_that_wrote_nothing_says_so(self):
        # v8.1.4: it still SAYS so, and now it also stops -- there is
        # nothing downstream that can do anything useful with no plan.
        cfg = self.write_goal()
        loop.claude = lambda *a, **k: ""
        with self.assertRaises(SystemExit):
            loop.phase_plan(cfg, {})
        planned = [e for e in self.events() if e["event"] == "planned"]
        self.assertIn("NO Plan.md", planned[0]["detail"])

    def test_status_reports_a_dead_driver(self):
        cfg = self.write_goal()
        loop.sh = lambda cmd, **k: types.SimpleNamespace(
            returncode=1, stdout="", stderr="")     # no tmux session
        loop.save(loop.STATE, {"phase": "contract_review"})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            loop.phase_status(cfg)
        self.assertIn("no tmux session", buf.getvalue())

    def test_status_reports_a_live_driver_and_its_idle_time(self):
        cfg = self.write_goal()
        loop.sh = lambda cmd, **k: types.SimpleNamespace(
            returncode=0, stdout="", stderr="")     # session is up
        loop.save(loop.STATE, {"phase": "iterate"})
        loop.event("loop_start", detail="x")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            loop.phase_status(cfg)
        out = buf.getvalue()
        self.assertIn("running (tmux cdd-test-goal)", out)
        self.assertIn("last event 0m ago", out)


class TestDriverArtifactsStayOutOfCommits(DriverCase):
    """v8.1.5: every `feat(loop):` commit carried the driver's own
    bookkeeping.

    Toy run 4 (2026-07-30, ~/cdd-toy4-loop): commit adb77cf "feat(loop):
    Phase 1, Step 2 CLI" staged events.jsonl, loop-state.json and two
    journal/traces/*.jsonl alongside src/wordfreq/cli.py. governance.md
    section 5 lists all three as ephemeral and GITIGNORED, but nothing
    ever ensured the entries existed -- run-logging.md section 1 makes
    the Planner ensure `logs/`, and these had no owner at all.
    """

    def setUp(self):
        super().setUp()
        loop.sh("git init -q .")
        loop.sh("git config user.name t")
        loop.sh("git config user.email t@t")

    def test_entries_are_created_when_there_is_no_gitignore(self):
        loop.ensure_gitignore()
        body = (self.tmp / ".gitignore").read_text()
        for p in loop.DRIVER_IGNORED:
            self.assertIn(p, body)

    def test_existing_entries_are_kept_and_never_duplicated(self):
        (self.tmp / ".gitignore").write_text("logs/\nevents.jsonl\n")
        loop.ensure_gitignore()
        lines = [l.strip() for l in
                 (self.tmp / ".gitignore").read_text().splitlines()]
        self.assertIn("logs/", lines)
        self.assertEqual(lines.count("events.jsonl"), 1)
        self.assertIn("loop-state.json", lines)

    def test_it_is_idempotent(self):
        loop.ensure_gitignore()
        first = (self.tmp / ".gitignore").read_text()
        loop.ensure_gitignore()
        self.assertEqual(first, (self.tmp / ".gitignore").read_text())

    def test_a_feature_commit_does_not_carry_loop_bookkeeping(self):
        """The defect as observed, end to end."""
        loop.ensure_gitignore()
        loop.save(loop.STATE, {"phase": "iterate"})
        loop.event("iteration", detail="Phase 1, Step 2")
        trace = self.tmp / "journal" / "traces" / "s.jsonl"
        trace.parent.mkdir(parents=True)
        trace.write_text('{"raw": "transcript"}\n')
        src = self.tmp / "src" / "cli.py"
        src.parent.mkdir(parents=True)
        src.write_text("print('hi')\n")

        self.assertTrue(loop.git_commit("feat(loop): Phase 1, Step 2"))
        staged = loop.sh("git show --stat --name-only HEAD").stdout
        self.assertIn("src/cli.py", staged)
        for p in ("events.jsonl", "loop-state.json", "journal/traces"):
            self.assertNotIn(p, staged)


class TestTrialLogPerAttempt(DriverCase):
    """v8.1.5: a RETRY destroyed the evidence that caused it.

    Observed live, first experiment toy run (2026-07-30). The trial log
    was named `logs/trial-<iteration>.log` and opened "w", but run_trial
    is called once per ATTEMPT, not per iteration. Attempt 1 died on a
    `nan_loss` the Monitor classified INTERVENE; attempt 2 relaunched
    and truncated the log to 9 lines. The only surviving record of why
    the loop retried was the ledger's one-line reason -- the log tail
    the Monitor actually judged was gone.

    Appending would be worse, not better: the Monitor reads the tail,
    so a relaunch would inherit the previous attempt's failure lines and
    could classify a healthy run as crashing. One file per attempt.
    """

    def setUp(self):
        super().setUp()
        loop.time = FakeClock(step=0.0)     # never reaches a poll
        loop.claude = lambda *a, **k: '{"status": "HEALTHY"}'

    def test_each_attempt_writes_its_own_log(self):
        cfg = self.write_goal()
        st = {"iteration": 1}
        loop.run_trial("T", "**Trial:** echo first attempt\n"
                            "**Monitor Profile:** none", st, cfg, 1)
        loop.run_trial("T", "**Trial:** echo second attempt\n"
                            "**Monitor Profile:** none", st, cfg, 2)
        logs = sorted(p.name for p in (self.tmp / "logs").glob("trial-*"))
        self.assertEqual(logs, ["trial-1-1.log", "trial-1-2.log"])
        self.assertIn("first attempt",
                      (self.tmp / "logs" / "trial-1-1.log").read_text())

    def test_the_generator_is_not_handed_a_path_the_driver_truncates(self):
        """The latent half: phase_iterate told the Generator to tee its
        ticket output to the same `logs/trial-<iteration>.log` the trial
        then reopened "w"."""
        cfg = self.write_goal()
        (self.tmp / "Plan.md").write_text(PLAN)
        self.results({"metrics": {"acc": 0.5}})
        prompts = []

        def fake(_st, role, prompt, *a, **k):
            prompts.append((role, prompt))
            if role == "evaluator":
                loop.VERDICT.write_text(json.dumps(
                    {"verdict": "PASS", "reason": "ok"}))
            return "done"
        loop.claude = fake
        loop.git_commit = lambda msg: "abc1234"
        st = {"phase": "iterate", "iteration": 0, "replans": 0,
              "spent_usd": 0.0, "gpu_hours": 0.0, "criteria_green": [],
              "started_epoch": loop.time.time()}
        loop.phase_iterate(cfg, st)
        gen = [p for r, p in prompts if r == "generator"]
        self.assertTrue(gen)
        for p in gen:
            self.assertNotIn("logs/trial-", p,
                             "the driver handed the Generator a log "
                             "path it truncates for the trial")


class TestReplanIsAnEvent(DriverCase):
    """v8.1.5: a REPLAN left no trace in the event feed.

    First experiment toy run (2026-07-30). The loop replanned once, and
    `events.jsonl` recorded a second `approval_request` whose gate string
    happened to read "replan" -- nothing else. `retry`, `trial_killed`,
    `regression`, `ticket_done`, `escalate` and `goal_reached` all emit;
    the single most expensive transition the driver makes, throwing away
    a plan and buying a whole fresh Planner plus a second contract
    review, did not. `phase_status()` renders events, so a user watching
    the feed could not see that a replan had happened at all.
    """

    def test_a_replan_emits_an_event_naming_its_reason(self):
        cfg = self.write_goal()
        (self.tmp / "Plan.md").write_text(PLAN)
        (self.tmp / "Evaluation.md").write_text("# findings")
        self.results({"metrics": {"acc": 0.5}})
        loop.git_commit = lambda msg: "abc1234"
        loop.wait_approval = lambda st, name, detail: None
        seen = [0]

        def fake(_st, role, prompt, *a, **k):
            if role == "evaluator":
                if "contract review" in prompt:
                    v = "OK"                  # the replan's re-gate
                else:
                    seen[0] += 1
                    v = "REPLAN" if seen[0] == 1 else "PASS"
                loop.VERDICT.write_text(json.dumps(
                    {"verdict": v,
                     "reason": "approach exhausted: lr=0.5 ruled out"}))
            return "done"
        loop.claude = fake
        st = {"phase": "iterate", "iteration": 0, "replans": 0,
              "spent_usd": 0.0, "gpu_hours": 0.0, "criteria_green": [],
              "started_epoch": loop.time.time()}
        loop.phase_iterate(cfg, st)

        replans = [e for e in self.events() if e["event"] == "replan"]
        self.assertTrue(replans, "a REPLAN must be visible in the feed")
        self.assertIn("exhausted", replans[0]["detail"])
        self.assertEqual(replans[0].get("n"), 1)


class TestKillReachesTheTrial(DriverCase):
    """v8.1.5: `trial_killed` was a claim the driver could not back up.

    First experiment toy run (2026-07-30), reconstructed from the event
    timestamps. The trial started ~15:03:59; the Monitor classified
    INTERVENE and the driver logged `trial_killed` at 15:05:10. The
    trial log then went on to gain `step 20/40` and `FATAL: loss
    diverged to nan` -- lines the harness prints at trial_start+100s,
    i.e. ~15:05:39, twenty-nine seconds AFTER the driver said it had
    killed the run.

    Cause: `Popen(cmd, shell=True)` makes the shell the direct child,
    and the Planner's Trial field is `train.py && report.py`, which no
    shell can optimise into an exec. `proc.kill()` therefore reaped the
    shell and orphaned the trainer. In the toy that was harmless -- the
    injected fault aborted it 30s later. On a real experiment goal the
    driver would report a kill, launch the RETRY's trial, and leave two
    trials on one GPU with the "dead" one still holding its memory.

    Same family as the trial exit code and the unchecked git_commit:
    assuming an external process did what we asked because nobody
    looked.
    """

    def test_intervene_kills_the_process_behind_the_shell(self):
        import time as real_time

        class Clock(FakeClock):
            def sleep(self, _sec):
                real_time.sleep(0.8)      # let the child really start
                self.t += self.step

        loop.time = Clock(step=60)        # first sleep reaches the poll
        loop.claude = lambda *a, **k: json.dumps(
            {"status": "INTERVENE", "signature": "nan_loss",
             "evidence": "loss=nan"})
        pid_file = self.tmp / "child.pid"
        # `true &&` forces a real shell: a bare single command is exec'd
        # by sh, which would hide the defect entirely.
        body = ("**Trial:** true && python3 -c \""
                "import os, time, pathlib; "
                f"pathlib.Path(r'{pid_file}').write_text(str(os.getpid()));"
                " time.sleep(30)\"\n**Monitor Profile:** none")
        cfg = self.write_goal(monitor={"interval_min": 1})

        self.assertFalse(loop.run_trial("T", body, {"iteration": 1}, cfg))
        self.assertTrue(pid_file.exists(), "the child never started -- "
                        "the test proves nothing")
        pid = int(pid_file.read_text())
        real_time.sleep(0.3)
        with self.assertRaises(
                OSError,
                msg=f"pid {pid} survived the kill: the driver reaped the "
                    f"shell and orphaned the trial"):
            os.kill(pid, 0)


# ---------- v8.1.6: the 2026-07-31 live-run defects --------------------

TRIAL_PLAN = """# Plan

### Phase 1, Step 1: Only ticket
**Boundary:** src/
**Trial:** exit 1
**Run Command:** true
"""


class LiveRunCase(DriverCase):
    """Shared setUp for the six defects the first live run exposed
    (journal/from-tmmluplus-eval-retro-20260731.md). A real git repo,
    because tree_fingerprint() is the evidence for two of them."""

    def setUp(self):
        super().setUp()
        (self.tmp / "Plan.md").write_text(PLAN)
        loop.time = FakeClock(step=0.0)     # trials never reach a poll
        loop.sh("git init -q .")
        loop.sh("git config user.name t")
        loop.sh("git config user.email t@t")
        loop.sh("git add -A")
        loop.sh("git commit -q -m base")
        loop.git_commit = lambda msg: "deadbee"

    def fresh_state(self, **over):
        st = {"phase": "iterate", "iteration": 0, "replans": 0,
              "spent_usd": 0.0, "gpu_hours": 0.0, "criteria_green": [],
              "started": "2026-07-31T02:26:06+00:00",
              "started_epoch": loop.time.time()}
        st.update(over)
        return st


class TestRetryCarriesTheVerdict(LiveRunCase):
    """Problem 3: the retry dispatch was the ticket body and nothing
    else, so attempt 2 was byte-for-byte the prompt that just failed.
    Three sessions, zero bytes changed, then ESCALATE."""

    def run_with(self, verdicts):
        prompts = []
        seq = list(verdicts)

        def fake(_st, role, prompt, *a, **k):
            if role == "generator":
                prompts.append(prompt)
                (self.tmp / f"gen{len(prompts)}.txt").write_text("x")
            if role == "evaluator":
                loop.VERDICT.write_text(json.dumps(seq.pop(0)))
            return "done"
        loop.claude = fake
        self.results({"metrics": {"acc": 0.5}})
        loop.phase_iterate(self.write_goal(), self.fresh_state())
        return prompts

    def test_the_second_attempt_is_told_why_the_first_failed(self):
        p = self.run_with([
            {"verdict": "RETRY", "reason": "aggregate-check.json is stale",
             "evidence": ["rows=2, expected 1"]},
            {"verdict": "PASS", "reason": "ok"},
            {"verdict": "PASS", "reason": "ok"}])
        self.assertNotIn("attempt", p[0].split("Ticket log")[0].lower(),
                         "attempt 1 has no prior verdict to carry")
        self.assertIn("attempt 2", p[1])
        self.assertIn("aggregate-check.json is stale", p[1])
        self.assertIn("rows=2, expected 1", p[1])

    def test_a_retry_with_no_evidence_still_dispatches(self):
        p = self.run_with([{"verdict": "RETRY", "reason": "just no"},
                           {"verdict": "PASS", "reason": "ok"},
                           {"verdict": "PASS", "reason": "ok"}])
        self.assertIn("just no", p[1])
        self.assertIn("(none)", p[1])


class TestNoOpSessionIsNotRetryable(LiveRunCase):
    """Problem 4: nothing compared the tree before and after a dispatch,
    so a session that could not possibly succeed still spent attempts 2
    and 3 -- and the Evaluator audit each one bought."""

    def drive(self, writes: bool, plan=None, verdict=None):
        (self.tmp / "Plan.md").write_text(plan or PLAN)
        calls = []

        def fake(_st, role, prompt, *a, **k):
            calls.append(role)
            if role == "generator" and writes:
                (self.tmp / f"gen{len(calls)}.txt").write_text("x")
            if role == "evaluator":
                loop.VERDICT.write_text(json.dumps(
                    verdict or {"verdict": "RETRY", "reason": "stale"}))
            return "done"
        loop.claude = fake
        self.results({"metrics": {"acc": 0.5}})
        loop.phase_iterate(self.write_goal(), self.fresh_state())
        return calls

    def test_a_second_no_op_escalates_instead_of_buying_a_third(self):
        calls = self.drive(writes=False)
        self.assertEqual(calls.count("generator"), 2,
                         "attempt 3 was dispatched after two no-ops")
        self.assertTrue(any(e["event"] == "no_op_session"
                            for e in self.events()))
        self.assertEqual(self.ledger()[-1]["verdict"], "ESCALATE")

    def test_the_first_no_op_is_forgiven_because_attempt_2_is_new(self):
        """Attempt 2 carries the verdict attempt 1 never saw, so it has
        genuinely new input -- escalating at the first no-op would throw
        away the fix v8.1.6 just bought."""
        calls = self.drive(writes=False)
        self.assertGreaterEqual(calls.count("generator"), 2)
        self.assertNotIn("no_op_session",
                         [e["event"] for e in self.events()[:3]])

    def test_a_session_that_wrote_something_keeps_all_three_attempts(self):
        calls = self.drive(writes=True)
        self.assertEqual(calls.count("generator"), 3)
        self.assertFalse(any(e["event"] == "no_op_session"
                             for e in self.events()))

    def test_a_failed_trial_is_not_a_no_op_failure(self):
        """The RETRY a dead trial buys is a RELAUNCH of an unchanged
        config -- exactly the case where the Generator should write
        nothing (loop-protocol.md section 5)."""
        calls = self.drive(writes=False, plan=TRIAL_PLAN)
        self.assertEqual(calls.count("generator"), 3)
        self.assertFalse(any(e["event"] == "no_op_session"
                             for e in self.events()))


class TestFirstGreenIsAudited(LiveRunCase):
    """Problem 2: under `final-pass`, six of seven tickets were PASSed on
    the deterministic gate alone. Three criteria went green at iteration
    3 on a unit-test fixture and nothing with provenance judgement looked
    at them until iteration 8."""

    def drive(self, st, make_green: bool):
        roles, prompts = [], []

        def fake(_st, role, prompt, *a, **k):
            roles.append(role)
            prompts.append(prompt)
            if role == "generator" and make_green:
                self.results({"metrics": {"acc": 0.5}})
            if role == "evaluator":
                loop.VERDICT.write_text(json.dumps(
                    {"verdict": "PASS", "reason": "audited"}))
            return "done"
        loop.claude = fake
        loop.phase_iterate(self.write_goal(
            evaluation_cadence="final-pass"), st)
        return roles, prompts

    def test_a_criterion_going_green_buys_an_audit(self):
        roles, prompts = self.drive(self.fresh_state(), make_green=True)
        self.assertIn("evaluator", roles,
                      "a criterion first went green and nothing audited it")
        self.assertTrue(any(e["event"] == "first_green"
                            for e in self.events()))
        audit = [p for p, r in zip(prompts, roles) if r == "evaluator"][0]
        self.assertIn("FIRST", audit)
        self.assertIn("acc", audit)

    def test_an_unchanged_green_still_defers(self):
        """The saving that `final-pass` exists for is intact: only the
        LAST ticket buys an audit when nothing changed colour."""
        self.results({"metrics": {"acc": 0.5}})
        roles, _ = self.drive(self.fresh_state(criteria_green=["acc"]),
                              make_green=False)
        self.assertEqual(roles, ["generator", "generator", "evaluator"])
        self.assertIn("deferred", str(self.ledger()[0]["reason"]))
        self.assertFalse(any(e["event"] == "first_green"
                             for e in self.events()))


class TestPlanEvidenceOwnership(DriverCase):
    """Problem 1: `results/` was a whole-directory Boundary entry on four
    tickets. A schema-module ticket therefore had write access to the
    file its criteria are read from, and its test fixture wrote one."""

    TWO_OWNERS = """# Plan

### Phase 1, Step 1: Schema module
**Boundary:** src/schema.py, results/
**Run Command:** pytest

### Phase 1, Step 2: The harness
**Boundary:** src/run.py, results/out.json
**Run Command:** python3 src/run.py
"""
    TREE_ONLY = """# Plan

### Phase 1, Step 1: The harness
**Boundary:** src/run.py, results/
**Run Command:** python3 src/run.py
"""
    NAMED = """# Plan

### Phase 1, Step 1: The harness
**Boundary:** `src/run.py`, `results/out.json`
**Run Command:** python3 src/run.py
"""
    NO_OWNER = """# Plan

### Phase 1, Step 1: The reporter
**Boundary:** bench/report.py
**Trial:** python3 bench/train.py && python3 bench/report.py
"""

    def test_two_tickets_that_can_write_the_evidence_are_rejected(self):
        p = loop.plan_problems(self.write_goal(), self.TWO_OWNERS)
        self.assertEqual(len(p), 1)
        self.assertIn("2 tickets", p[0])
        self.assertIn("Phase 1, Step 1", p[0])
        self.assertIn("Phase 1, Step 2", p[0])

    def test_a_tree_entry_is_rejected_in_favour_of_the_file(self):
        p = loop.plan_problems(self.write_goal(), self.TREE_ONLY)
        self.assertEqual(len(p), 1)
        self.assertIn("Name the file, not the tree", p[0])

    def test_one_ticket_naming_the_file_is_accepted(self):
        self.assertEqual(loop.plan_problems(self.write_goal(),
                                            self.NAMED), [])

    def test_no_owner_is_legal(self):
        """On an experiment goal the DRIVER launches the trial, so the
        metrics file is written by no session and belongs in no
        Boundary. Requiring an owner would fail every correct plan."""
        self.assertEqual(loop.plan_problems(self.write_goal(),
                                            self.NO_OWNER), [])

    def test_a_bulleted_boundary_is_still_read(self):
        plan = ("# Plan\n\n### Phase 1, Step 1: T\n**Boundary:**\n"
                "- src/a.py\n- results/\n**Run Command:** true\n")
        self.assertTrue(loop.plan_problems(self.write_goal(), plan))

    def test_the_gate_runs_before_the_evaluator_is_paid(self):
        (self.tmp / "Plan.md").write_text(self.TWO_OWNERS)
        calls = []

        def fake(_st, role, prompt, *a, **k):
            calls.append(role)
            if role == "planner":                  # "fixes" the plan
                (self.tmp / "Plan.md").write_text(self.NAMED)
            if role == "evaluator":
                loop.VERDICT.write_text(json.dumps({"verdict": "OK"}))
            return ""
        loop.claude = fake
        st = {}
        loop.phase_contract_review(self.write_goal(), st)
        self.assertEqual(calls, ["planner", "evaluator"],
                         "the rejected plan was reviewed anyway")
        self.assertEqual(st["phase"], "gate")
        self.assertTrue(any(e["event"] == "plan_rejected"
                            for e in self.events()))

    def test_a_plan_that_never_gets_fixed_escalates(self):
        (self.tmp / "Plan.md").write_text(self.TWO_OWNERS)
        calls = []
        loop.claude = lambda _st, role, *a, **k: (calls.append(role) or "")
        with self.assertRaises(SystemExit):
            loop.phase_contract_review(self.write_goal(), {})
        self.assertNotIn("evaluator", calls,
                         "never pay to review a plan a gate rejected")
        esc = [e for e in self.events() if e["event"] == "escalate"][-1]
        self.assertIn("evidence", esc["detail"])


class TestBudgetHotReload(DriverCase):
    """Problem 8 / habits: cfg was read once at startup, so raising a cap
    meant killing tmux -- and a restart costs an iteration."""

    def test_a_raised_cap_is_picked_up_mid_loop(self):
        cfg = {"budgets": {"max_usd": 25}, "criteria": []}
        self.write_goal(budgets={"max_usd": 50})
        loop.reload_budgets(cfg)
        self.assertEqual(cfg["budgets"]["max_usd"], 50)
        self.assertTrue(any(e["event"] == "budgets_updated"
                            for e in self.events()))

    def test_the_contract_itself_is_not_reloaded(self):
        """Budgets are the user's dial; criteria are frozen
        (loop-protocol.md section 4)."""
        cfg = {"budgets": {"max_usd": 25},
               "criteria": [{"metric": "acc", "op": ">", "value": 0.9,
                             "source": "results/out.json"}]}
        self.write_goal(budgets={"max_usd": 50},
                        criteria=[{"metric": "acc", "op": ">", "value": 0.0,
                                   "source": "results/out.json"}])
        loop.reload_budgets(cfg)
        self.assertEqual(cfg["criteria"][0]["value"], 0.9)

    def test_a_corrupt_goal_file_keeps_the_caps(self):
        cfg = {"budgets": {"max_usd": 25}}
        loop.GOAL.write_text("{not json")
        loop.reload_budgets(cfg)
        self.assertEqual(cfg["budgets"]["max_usd"], 25)

    def test_an_unchanged_file_is_not_an_event(self):
        cfg = {"budgets": {"max_usd": 50}}
        self.write_goal(budgets={"max_usd": 50})
        loop.reload_budgets(cfg)
        self.assertFalse(any(e["event"] == "budgets_updated"
                             for e in self.events()))


class TestJournalRecord(DriverCase):
    """Problem 6: CLAUDE.md and governance.md both said the driver
    appends a loop record. `grep -n journal loop.py` returned comments
    and one reminder string."""

    def setUp(self):
        super().setUp()
        (self.tmp / "Plan.md").write_text(PLAN)
        loop.LEDGER.write_text(json.dumps(
            {"ts": "t", "iteration": 1, "ticket": "Phase 1, Step 1",
             "attempt": 1, "verdict": "PASS", "reason": "clean",
             "evidence": [], "criteria": []}) + "\n")

    def state(self, **over):
        st = {"phase": "done", "iteration": 3, "replans": 1,
              "spent_usd": 32.85, "started": "2026-07-31T10:22:18+00:00",
              "started_epoch": loop.time.time()}
        st.update(over)
        return st

    def test_the_record_names_the_loop_and_its_numbers(self):
        cfg = self.write_goal(type="build", goal="prove the pipeline")
        p = loop.write_journal(cfg, self.state())
        self.assertEqual(p.name, "20260731-102218-build.md")
        text = p.read_text()
        for needle in ("prove the pipeline", "32.85", "Phase 1, Step 1",
                       "## Feedback", "## Criteria"):
            self.assertIn(needle, text)

    def test_the_record_separates_human_latency_from_runtime(self):
        """v8.1.9: "too many human interruptions" was the 2026-08-02
        retro's headline complaint and the record carried no number for
        it -- 0.9h of driver runtime says nothing about the seven times
        a person had to be fetched. calendar - runtime is that number."""
        cfg = self.write_goal()
        loop.event("escalate", detail="needs a human")
        st = self.state(run_hours=0.5,
                        started_epoch=loop.time.time() - 4 * 3600)
        text = loop.write_journal(cfg, st).read_text()
        self.assertIn("driver runtime: 0.5h", text)
        self.assertRegex(text, r"elapsed: 4\.0h calendar — 3\.5h")

    def test_an_escalation_is_recorded_too(self):
        """The loops that most need a record are the ones that do not
        finish -- writing only on `done` would have missed the run this
        whole release comes from."""
        cfg = self.write_goal()
        loop.event("escalate", detail="forged evidence at Step 7")
        p = loop.write_journal(cfg, self.state(phase="iterate"))
        self.assertIn("forged evidence at Step 7", p.read_text())

    def test_the_users_feedback_survives_a_rewrite(self):
        cfg = self.write_goal()
        p = loop.write_journal(cfg, self.state())
        p.write_text(p.read_text().replace(
            "- Rating: [good | ok | bad]", "- Rating: bad"))
        loop.write_journal(cfg, self.state(iteration=9))
        self.assertIn("- Rating: bad", p.read_text())
        self.assertIn("iterations: 9", p.read_text())

    def test_the_driver_writes_one_even_when_a_phase_dies(self):
        cfg = self.write_goal(type="build")
        loop.claude = lambda *a, **k: ""
        self.addCleanup(setattr, loop, "phase_plan", loop.phase_plan)
        loop.phase_plan = lambda *a, **k: sys.exit(1)
        argv, sys.argv = sys.argv, ["loop.py", "--here"]
        self.addCleanup(setattr, sys, "argv", argv)

        class Quiet(io.StringIO):
            def reconfigure(self, **_kw):     # main() line-buffers stdout
                pass
        with contextlib.redirect_stdout(Quiet()):
            with self.assertRaises(SystemExit):
                loop.main()
        self.assertTrue(list((self.tmp / "journal").glob("*-build.md")),
                        "a driver that died left no record at all")


class TestCloseTheLoop(DriverCase):
    """Four consecutive retros flagged unclosed loops, with the
    housekeeping reminder already in place. The missing part was never
    the reminder."""

    def setUp(self):
        super().setUp()
        (self.tmp / "Plan.md").write_text(PLAN)
        loop.sh("git init -q .")
        loop.sh("git config user.name t")
        loop.sh("git config user.email t@t")
        loop.sh("git add -A")
        loop.sh("git commit -q -m base")
        loop.LEDGER.write_text("")
        loop.EVENTS.write_text("")

    def close(self, st, force=False):
        cfg = self.write_goal(type="build")
        loop.save(loop.STATE, st)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            loop.phase_close(cfg, st, force)
        return out.getvalue()

    def test_refuses_a_loop_that_is_not_finished(self):
        with open(os.devnull, "w") as null:
            real, sys.stderr = sys.stderr, null
            try:
                with self.assertRaises(SystemExit):
                    self.close({"phase": "iterate", "iteration": 2})
            finally:
                sys.stderr = real
        self.assertTrue((self.tmp / "Plan.md").exists(),
                        "a refused close must delete nothing")

    def test_force_closes_an_escalated_loop(self):
        self.close({"phase": "iterate", "iteration": 2}, force=True)
        self.assertFalse((self.tmp / "Plan.md").exists())

    def test_it_removes_every_ephemeral_and_keeps_the_record(self):
        out = self.close({"phase": "done", "iteration": 3,
                          "started": "2026-07-31T10:22:18+00:00"})
        for f in ("Plan.md", "goal.json", "ledger.jsonl",
                  "loop-state.json", "events.jsonl"):
            self.assertFalse((self.tmp / f).exists(), f)
        self.assertTrue((self.tmp / "journal" /
                         "20260731-102218-build.md").exists())
        self.assertIn("Feedback block is still the template", out)

    def test_the_record_is_committed_and_the_branch_is_left_alone(self):
        head = loop.sh("git rev-parse HEAD").stdout.strip()
        out = self.close({"phase": "done", "iteration": 1,
                          "started": "2026-07-31T10:22:18+00:00"})
        self.assertNotEqual(loop.sh("git rev-parse HEAD").stdout.strip(),
                            head, "the journal record was never committed")
        self.assertIn("journal record", loop.sh(
            "git log -1 --pretty=%B").stdout)
        self.assertIn("merge", out, "closing must not merge for the user")


class TestLoopModeHasNoAskPhase(unittest.TestCase):
    """v8.1.8: the mode skills are 7.0-era and open with an INTERACTIVE
    Ask phase ending in "STOP. Loop until the user says 'proceed to
    spec'" -- an instruction a headless loop Planner cannot follow and
    cannot safely ignore. Nobody knew what it did when it read one,
    because the only harness that could find out (the toy) copied no
    skills/ at all (journal/retro-20260731-toy-816.md, problem 5).

    The rule lives in cdd-planner.md, which the loop Planner always
    reads; every skill that still tells someone to halt must point at
    it, or a model reading the skill top-down hits the contradiction
    with nothing to resolve it."""

    REPO = HERE.parent.parent
    RULE = "In loop mode there is no Ask phase and no halt"

    @staticmethod
    def flat(path):
        """One line, single-spaced -- these files wrap at 72 columns, so
        a cross-reference is routinely split across two lines."""
        return " ".join(path.read_text().split())

    def test_the_planner_states_the_rule(self):
        self.assertIn(self.RULE,
                      self.flat(self.REPO / ".claude" / "agents"
                                / "cdd-planner.md"))

    def test_every_halting_skill_points_at_it(self):
        for skill in sorted((self.REPO / "skills").glob("mode-*/SKILL.md")):
            text = self.flat(skill)
            if not re.search(r"\*\*(?:Step \d+: )?Halt", text):
                continue                    # nothing to halt for
            self.assertIn(self.RULE, text,
                          f"{skill.parent.name} tells the Planner to "
                          f"halt and never says what loop mode does "
                          f"instead")

    def test_the_scaffolders_deploy_what_the_readme_promises(self):
        """A smoke test that copies less than a deployment proves the
        driver, not the framework."""
        for sh_name in ("toy_project.sh", "toy_experiment.sh"):
            src = (HERE / sh_name).read_text()
            for part in ('"$FW/.claude"', '"$FW/skills"', '"$FW/CLAUDE.md"'):
                self.assertIn(part, src, f"{sh_name} does not copy {part}")


class TestPlannerGoalTypeMapping(unittest.TestCase):
    """v8.1.5: `phase_plan()` prompts the Planner with a goal TYPE --
    "the mode skill for goal type 'experiment'" -- and cdd-planner.md
    told it to load `skills/mode-*/SKILL.md`. Only `mode-loop/SKILL.md`
    knows that `experiment` maps to `mode-modify`, and that file is the
    interactive Ask-phase skill, which a headless Planner never reads.

    Observed 2026-07-30, first experiment toy run: the Planner ran
    `find . -iname "*mode-experiment*"`, got nothing, and compensated by
    reading loop.py and enforce_authority.py in full to re-derive the
    driver's contract from source. The mapping is now stated where the
    Planner actually reads it, and these two cases keep it honest: every
    goal type the loop accepts is mapped, and every skill the mapping
    names exists on disk.
    """

    REPO = HERE.parent.parent
    PLANNER = REPO / ".claude" / "agents" / "cdd-planner.md"
    # the goal types [/loop] accepts, per CLAUDE.md and mode-loop/SKILL.md
    GOAL_TYPES = ("build", "modify", "experiment", "migrate", "merge")

    def mapping(self):
        rows = re.findall(r"^\| `([a-z]+)` \| (.+?) \|$",
                          self.PLANNER.read_text(), re.M)
        return dict(rows)

    def test_every_goal_type_the_loop_accepts_is_mapped(self):
        table = self.mapping()
        for t in self.GOAL_TYPES:
            self.assertIn(t, table,
                          f"cdd-planner.md maps no mode skill for goal "
                          f"type {t!r}; the driver names the type and "
                          f"nothing else tells the Planner what to load")

    def test_every_skill_the_mapping_names_exists(self):
        named = set(re.findall(r"skills/(mode-[a-z]+)/SKILL\.md",
                               self.PLANNER.read_text()))
        self.assertTrue(named, "the mapping names no skill at all")
        for s in sorted(named):
            self.assertTrue((self.REPO / "skills" / s / "SKILL.md").exists(),
                            f"cdd-planner.md points the Planner at "
                            f"skills/{s}/SKILL.md, which does not exist")


class TestRuntimeClock(DriverCase):
    """v8.1.7: max_wall_hours meters DRIVER RUNTIME, not the calendar.

    2026-07-31 toy loop: 3.6h at the plan gate with the driver process
    dead; the approval landed and the next budget check escalated
    `budget exhausted: max_wall_hours` before one ticket ran, $0 spent
    since resume. The gate is pitched as approve-from-your-phone, so an
    overnight approval was guaranteed to escalate on resume.
    """

    def test_hours_spent_at_a_gate_are_not_billed(self):
        flag = self.tmp / "approvals" / "plan.approved"

        class Clock(FakeClock):
            def sleep(self, _sec):
                self.t += 4 * 3600          # the human slept on it
                flag.touch()
        loop.time = Clock()
        st = {}
        loop.clock_start(st)
        loop.wait_approval(st, "plan", "review it")
        self.assertLess(loop.wall_hours(st), 0.01)
        self.assertEqual(
            loop.budget_exceeded(st, {"budgets": {"max_wall_hours": 2}}),
            "", "a four-hour approval must not exhaust a two-hour cap")

    def test_hours_spent_working_are_billed(self):
        loop.time = FakeClock()
        st = {}
        loop.clock_start(st)
        loop.time.t += 3 * 3600
        self.assertAlmostEqual(loop.wall_hours(st), 3.0, places=3)
        self.assertEqual(
            loop.budget_exceeded(st, {"budgets": {"max_wall_hours": 2}}),
            "max_wall_hours")

    def test_time_between_runs_is_not_billed(self):
        """The driver was not running; nothing accrued."""
        loop.time = FakeClock(start=1_000_000.0 + 30 * 3600)
        st = {"run_hours": 0.4, "run_epoch": None,
              "started_epoch": 1_000_000.0}
        self.assertAlmostEqual(loop.wall_hours(st), 0.4, places=3)
        self.assertEqual(
            loop.budget_exceeded(st, {"budgets": {"max_wall_hours": 2}}),
            "")

    def test_a_crashed_run_is_closed_at_its_last_event(self):
        """A run that died left run_epoch open. Credit it only up to the
        last moment the driver can be PROVEN to have been alive --
        crediting the crash gap would restore the bug."""
        t0 = 1_000_000.0
        loop.EVENTS.write_text("")
        os.utime(loop.EVENTS, (t0 + 1800, t0 + 1800))
        loop.time = FakeClock(start=t0 + 10 * 3600)   # found 10h later
        st = {"run_epoch": t0, "run_hours": 0.0}
        loop.clock_start(st)
        self.assertAlmostEqual(st["run_hours"], 0.5, places=2)

    def test_a_finished_loop_does_not_keep_billing_itself(self):
        """Found by the 8.1.7 shakedown run: the driver exited with
        run_epoch still open, so every later `status` on a loop that had
        already reported `done` billed it for the calendar time since --
        the reading this whole mechanism exists to remove."""
        t0 = 1_000_000.0
        loop.EVENTS.write_text("")
        os.utime(loop.EVENTS, (t0 + 1800, t0 + 1800))   # died at +30min
        st = {"run_epoch": t0, "run_hours": 0.0}
        loop.time = FakeClock(start=t0 + 20 * 3600)     # read 20h later
        self.assertAlmostEqual(loop.wall_hours(st, live=False), 0.5,
                               places=2)
        self.assertAlmostEqual(loop.wall_hours(st), 20.0, places=1,
                               msg="a LIVE driver is billed to now")
        loop.clock_stop(st)
        self.assertIsNone(st["run_epoch"])

    def test_status_separates_calendar_age_from_metered_runtime(self):
        loop.time = FakeClock(start=1_000_000.0 + 30 * 3600)
        loop.save(loop.STATE, {"phase": "gate", "iteration": 1,
                               "started": "2026-07-31T05:04:00+00:00",
                               "started_epoch": 1_000_000.0,
                               "run_hours": 0.4, "run_epoch": None})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            loop.phase_status(self.write_goal(
                budgets={"max_iterations": 8, "max_usd": 10,
                         "max_wall_hours": 2}))
        out = buf.getvalue()
        self.assertIn("30.0h ago", out)          # calendar, informational
        self.assertIn("runtime     0.4h / 2.0h", out)   # what is metered

    def test_the_approval_event_names_its_gate(self):
        """It rendered as a bare "approved:" -- the one event confirming
        a human acted named nothing."""
        flag = self.tmp / "approvals" / "plan.approved"

        class Clock(FakeClock):
            def sleep(self, _sec):
                flag.touch()
        loop.time = Clock()
        loop.wait_approval({}, "plan", "review it")
        approved = [e for e in self.events() if e["event"] == "approved"]
        self.assertEqual(len(approved), 1)
        self.assertIn("plan", approved[0].get("detail", ""))


class TestPregateBudgetCeiling(DriverCase):
    """v8.1.7: contract review is bounded by MONEY as well as rounds.

    MAX_REVISIONS was the only bound and budget_exceeded() was never
    consulted between rounds, so a review could eat an arbitrary share
    of max_usd before the human gate -- the one place the user can still
    intervene cheaply. 2026-07-31: $5.48, 59% of the loop's spend, six
    sessions, zero tickets dispatched.
    """

    def spender(self, calls, verdict="REVISE", usd=3.0):
        def fake(st, role, prompt, *a, **k):
            calls.append(role)
            st["spent_usd"] = st.get("spent_usd", 0.0) + usd
            loop.VERDICT.write_text(json.dumps({"verdict": verdict}))
            return ""
        return fake

    def test_rounds_stop_once_the_pregate_share_is_gone(self):
        calls = []
        loop.claude = self.spender(calls)
        st = {}
        loop.phase_contract_review(self.write_goal(), st)   # cap $10
        self.assertEqual(st["phase"], "gate",
                         "the plan goes to the human, who reviews free")
        self.assertEqual(calls, ["evaluator", "planner"],
                         "a third round costs money nobody budgeted")
        self.assertIn("contract_review_halted",
                      [e["event"] for e in self.events()])

    def test_the_first_review_is_always_bought(self):
        """Skipping it would not bound a cost -- it would delete the
        safety gate and hand an unreviewed plan to a human who is being
        asked to approve, not to audit."""
        calls = []
        loop.claude = self.spender(calls, verdict="OK")
        st = {"spent_usd": 9.5}                      # already over half
        loop.phase_contract_review(self.write_goal(), st)
        self.assertEqual(calls.count("evaluator"), 1)
        self.assertEqual(st["phase"], "gate")

    def test_a_hard_breach_escalates_rather_than_gating(self):
        calls = []
        loop.claude = self.spender(calls)
        with self.assertRaises(SystemExit):
            loop.phase_contract_review(self.write_goal(),
                                       {"spent_usd": 10.0})
        self.assertEqual(calls, [], "nothing is bought past the cap")
        self.assertTrue(any(e["event"] == "escalate" and
                            "contract review" in e.get("detail", "")
                            for e in self.events()))

    def test_the_gate_banner_reports_the_review_state(self):
        """A gate that misreports what it hands you is worse than no
        gate: the banner used to assert "contract-reviewed" always."""
        calls = []
        loop.claude = self.spender(calls, verdict="OK", usd=0.5)
        st = {}
        loop.phase_contract_review(self.write_goal(), st)
        self.assertIn("OK", st["contract"])
        calls.clear()
        loop.claude = self.spender(calls)
        st2 = {}
        loop.phase_contract_review(self.write_goal(), st2)
        self.assertIn("NOT completed", st2["contract"])


class TestPregateFlush(DriverCase):
    """v8.1.7: the plan phase's artifacts are committed at the gate.

    The driver commits `git add -A` and nothing flushed between the
    Planner and the first ticket, so 2026-07-31's
    `feat(loop): Phase 1, Step 1 Environment Setup` also carried
    Plan.md, Evaluation.md, verdict.json, Architecture.md, the user's
    goal.json edit and the journal record. Three authors, one commit,
    titled after one ticket -- and it made the Evaluator's per-ticket
    Boundary audit unpassable as stated.
    """

    def setUp(self):
        super().setUp()
        loop.sh("git init -q .")
        loop.sh("git config user.name t")
        loop.sh("git config user.email t@t")
        loop.ensure_gitignore()      # as main() does, before any commit
        (self.tmp / "a.txt").write_text("1")
        loop.sh("git add -A")
        loop.sh("git commit -q -m base")

    def test_pregate_artifacts_get_their_own_commit(self):
        (self.tmp / "Plan.md").write_text("### Phase 1, Step 1: X\n")
        (self.tmp / "Evaluation.md").write_text("audit\n")
        sha = loop.flush_pregate("plan approved")
        self.assertTrue(sha)
        msg = loop.sh("git log -1 --pretty=%B").stdout
        self.assertTrue(msg.startswith("plan(loop): plan approved"))
        self.assertIn("Plan.md", msg)
        self.assertIn("plan_committed",
                      [e["event"] for e in self.events()])

    def test_the_next_ticket_commit_carries_only_its_ticket(self):
        (self.tmp / "Plan.md").write_text("### Phase 1, Step 1: X\n")
        loop.flush_pregate("plan approved")
        (self.tmp / "src.py").write_text("x = 1\n")
        loop.git_commit("feat(loop): Phase 1, Step 1")
        touched = loop.sh(
            "git show --stat --name-only --pretty= HEAD").stdout.split()
        self.assertEqual(touched, ["src.py"])

    def test_a_clean_tree_is_not_committed(self):
        head = loop.sh("git rev-parse HEAD").stdout.strip()
        self.assertEqual(loop.flush_pregate("plan approved"), "")
        self.assertEqual(loop.sh("git rev-parse HEAD").stdout.strip(),
                         head)


class TestHookArrowIsNotARedirect(HookCaller, unittest.TestCase):
    """v8.1.7: the shell-write scanner read the `>` of a Python return
    annotation as a redirect, denying `def f(x: str) -> int:` and naming
    `int:` as the write target. Failing CLOSED on legal work is strictly
    worse than the documented heredoc blind spot, which only fails open
    -- and it is what pushed the 2026-07-31 Evaluator into editing its
    repro copies instead of stopping."""

    def test_return_annotations_are_not_write_targets(self):
        hook = load_hook()
        for cmd in ("def f(x: str) -> int:",
                    "    def run_tests(self) -> dict:",
                    "python3 -c 'lambda a -> b'"):
            self.assertEqual(hook.bash_write_targets(cmd), [], cmd)

    def test_real_redirects_still_resolve(self):
        hook = load_hook()
        self.assertEqual(hook.bash_write_targets("echo x > Plan.md"),
                         ["Plan.md"])
        self.assertEqual(hook.bash_write_targets("cat a >> b.txt"),
                         ["b.txt"])
        self.assertEqual(hook.bash_write_targets("pytest -q 2> err.txt"),
                         ["err.txt"])
        self.assertEqual(
            hook.bash_write_targets("pytest 2>&1 | tee logs/run.log"),
            ["logs/run.log"])


if __name__ == "__main__":
    unittest.main(verbosity=2 if "-v" in sys.argv else 1,
                  argv=[a for a in sys.argv if a != "-v"])
