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
  8.1.16              the two 2026-09-02 retros: cd tracked per shell
                      segment, quoted spans as data on the loose net,
                      escaped quotes, listing forms with options; the
                      output gate before PASS; the retry cap
                      adjudicated once; the Monitor's memory and the
                      driver's overrule; `max_gpu_hours: 0`; .env/venv
                      seeded into a worktree; a remembered contract
                      review; `note`; denials counted as records and
                      shown in the journal
  8.1.17              the 2026-09-18 agentRl retro: the driver decides
                      stall from mtimes and overrules the Monitor;
                      contract review capped per loop; an `is_error`
                      result is a dead session and is redispatched; a
                      gate re-announces itself every 4 h; the journal
                      carries ONE record (the Feedback split landed on
                      the header sentence); close refuses a template
                      Feedback block; effort per role (`--effort`),
                      per-role sessions/minutes/spend in status and the
                      journal, and Taipei time on every stamp
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
    loop.MANIFEST = tmp / ".claude" / "driver" / "manifest.json"


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
                   "require_cli", "wait_approval", "flush_pregate",
                   "SESSION_RETRY_SECONDS", "NETWORK_PROBE_SECONDS",
                   "MAX_NETWORK_WAIT_MIN", "network_up"):
            self.addCleanup(setattr, loop, _n, getattr(loop, _n))
        # v8.1.13: the retry before a re-dispatch is a real 30s pause in
        # production and must be zero here -- set for EVERY case, not
        # only the ones about it, because any stub that returns
        # unparseable output now costs that pause twice.
        loop.SESSION_RETRY_SECONDS = 0
        # v8.1.19: the suite is offline, so the connectivity wait is
        # zero by default (a stubbed 529 would otherwise probe the real
        # network and sleep for two hours); the B3 cases raise the cap
        # through goal.json and fake the clock.
        loop.NETWORK_PROBE_SECONDS = 0
        loop.MAX_NETWORK_WAIT_MIN = 0
        loop.network_up = lambda: False
        # the suite is offline by contract; TestAuthGate exercises
        # the real probe with a stubbed subprocess.
        loop.require_cli = lambda: None
        use_root(self.tmp)
        install_machinery(self.tmp)
        (self.tmp / "logs").mkdir(exist_ok=True)

    def iterate_state(self, **over):
        """A fresh `iterate`-phase loop state, as the driver has it after
        the plan gate. 8.1.21: this dict was pasted 23 times."""
        st = {"phase": "iterate", "iteration": 0, "replans": 0,
              "spent_usd": 0.0, "gpu_hours": 0.0, "criteria_green": [],
              "started_epoch": loop.time.time()}
        st.update(over)
        return st

    def write_goal(self, **over):
        cfg = {"goal": "test goal", "type": "modify",
               "criteria": [{"metric": "acc", "op": ">", "value": 0.0,
                             "source": "results/out.json"}],
               "budgets": {"max_iterations": 8, "max_usd": 10},
               "evaluation_cadence": "per-iteration",
               "monitor": {"interval_min": 1},
               "models": dict(loop.DEFAULT_MODELS)}
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

    VALID = {"criteria": [{"metric": "a", "op": ">", "value": 1,
                           "source": "s"}],
             "budgets": {"max_usd": 1},
             "preflight": [{"name": "n", "run": "true"}],
             "models": {"planner": "claude-fable-5-1",
                        "generator": "claude-sonnet-5",
                        "evaluator": "claude-opus-5",
                        "monitor": "claude-haiku-4-5"}}

    def test_accepts_valid_contract(self):
        loop.validate_goal(self.VALID)

    # v8.1.16: every role names its model by FULL ID, version included.
    def test_rejects_missing_models(self):
        cfg = {k: v for k, v in self.VALID.items() if k != "models"}
        self.assertDies(cfg, "models")

    def test_rejects_a_tier_alias(self):
        for alias in ("opus", "sonnet", "haiku", "claude-opus", "default"):
            cfg = dict(self.VALID, models=dict(self.VALID["models"],
                                               generator=alias))
            self.assertDies(cfg, "models.generator")

    def test_every_role_must_be_named(self):
        models = {r: m for r, m in self.VALID["models"].items()
                  if r != "monitor"}
        self.assertDies(dict(self.VALID, models=models), "models.monitor")


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
        # verdict is three fail-closed reviews, not two. v8.1.19 (B10):
        # each LIVE session that wrote no verdict is asked once more, so
        # every review costs two dispatches here.
        self.assertEqual(calls.count("evaluator"),
                         2 * (loop.MAX_REVISIONS + 1))
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

### Phase 1, Step 2: Second ticket
**Boundary:** src/other/
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
        st = self.iterate_state()
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
              # v8.1.12: keyed `metric@source`, not the bare name
              "criteria_green": ["acc@results/out.json"],
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
        st = self.iterate_state()
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
        st = self.iterate_state()
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
    """Offline coverage of the authority hook: exhaustive rather than
    end-to-end, and it needs no `claude` login. The manual walkthrough it
    replaces lived in a draft INSTALL.md that never shipped."""

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

    def test_a_planner_s_not_done_marker_parses_and_is_not_done(self):
        """v8.1.18 (B1): `### Phase 1, Step 1 [ ]: Title` produced zero
        tickets and an escalation in three deployments."""
        todo = PLAN.replace("### Phase 1, Step 1:", "### Phase 1, Step 1 [ ]:")
        todo = todo.replace("### Phase 1, Step 2:", "### Phase 1, Step 2 [ ]:")
        got = list(loop.tickets(todo))
        self.assertEqual(len(got), 2)
        self.assertEqual([d for _, _, _, d in got], [False, False])
        self.assertEqual(got[0][1], "First ticket")

    def test_marking_done_replaces_the_planner_s_marker(self):
        todo = PLAN.replace("### Phase 1, Step 1:", "### Phase 1, Step 1 [ ]:")
        marked = loop.mark_done(todo, "Phase 1, Step 1")
        self.assertIn("### Phase 1, Step 1 [x]: First ticket", marked)
        self.assertNotIn("[ ]", marked.split("Step 2")[0])
        self.assertEqual([d for _, _, _, d in loop.tickets(marked)],
                         [True, False])
        # and a heading with no marker still gets one
        self.assertIn("### Phase 1, Step 2 [x]:",
                      loop.mark_done(PLAN, "Phase 1, Step 2"))


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
        st = self.iterate_state()
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
        st = self.iterate_state()
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
        st = self.iterate_state()
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
        st = self.iterate_state()
        loop.phase_iterate(self.write_goal(), st)
        esc = [e for e in self.events() if e["event"] == "escalate"][0]
        said = esc["detail"].split("generator stopped: ", 1)[1]
        self.assertTrue(said.startswith("prologue"),
                        f"starts mid-word: {said[:30]!r}")
        self.assertIn("boundary denial explained", said)

    def test_a_short_report_is_not_clipped_at_all(self):
        (self.tmp / "Plan.md").write_text(PLAN)
        loop.claude = lambda *a, **k: "needs a decision. STATUS: stopped"
        st = self.iterate_state()
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
        st = self.iterate_state()
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
        self.assertIn("tee -a logs/driver.log", cmd[5])
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
        st = self.iterate_state()
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
        st = self.iterate_state()
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
                # v8.1.16: the retry cap is adjudicated; this suite is
                # about the no-op backstop, so the adjudicator declines
                # to extend the cap (TestRetryCapIsAdjudicated covers it).
                loop.VERDICT.write_text(json.dumps(
                    {"verdict": "ESCALATE", "reason": "cap"}
                    if "retry-cap" in prompt else
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
        roles, _ = self.drive(
            self.fresh_state(criteria_green=["acc@results/out.json"]),
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

    def close(self, st, force=False, rated=True):
        cfg = self.write_goal(type="build")
        loop.save(loop.STATE, st)
        if rated:                       # v8.1.17: close refuses a template
            rec = loop.write_journal(cfg, st)
            rec.write_text(rec.read_text().replace(
                "- Rating: [good | ok | bad]", "- Rating: ok"))
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

    def test_refuses_a_template_feedback_block(self):
        """v8.1.17: six of 22 loops closed on the untouched template
        while the 8.1.6 warning printed every time
        (journal/from-agentrl-retro-20260918.md, problem 7a)."""
        st = {"phase": "done", "iteration": 3,
              "started": "2026-07-31T10:22:18+00:00"}
        with open(os.devnull, "w") as null:
            real, sys.stderr = sys.stderr, null
            try:
                with self.assertRaises(SystemExit):
                    self.close(st, rated=False)
            finally:
                sys.stderr = real
        self.assertTrue((self.tmp / "Plan.md").exists(),
                        "a refused close must delete nothing")
        self.close(st, force=True, rated=False)       # --force still closes
        self.assertFalse((self.tmp / "Plan.md").exists())

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
    # the goal types [loop] accepts, per CLAUDE.md and mode-loop/SKILL.md
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


# ---------- v8.1.11: the eight aibench hotfixes, brought home ----------

class TestHookFalsePositivesFromAibench(HookCaller, unittest.TestCase):
    """Every case here denied a READ-ONLY action during loops 1-8 of the
    aibench deployment (2026-08-02 .. 2026-08-18). That retro measured
    the class: 8 of 19 escalations, 42% of every reason the loop stopped,
    and most killed an Evaluator mid-audit -- so the loop paid for the
    session twice (journal/from-aibench-retro-20260818.md, failure class
    1; patches in journal/hotfixes/).

    The fixes were written one live loop at a time and NONE of them
    shipped with a test, which is why the class kept recurring after two
    of them had already landed. Each test below pins the false positive
    that was fixed AND the real denial next to it, because every one of
    these fixes narrows a net that is load-bearing.
    """

    def bash(self, role, cmd, boundary=""):
        return self.call(role, "Bash", {"command": cmd}, boundary)

    # ---- 3d2271e: redirect syntax read as a write TARGET -------------

    def test_bare_redirect_token_is_not_a_write_target(self):
        """`tee logs/latest.log > /dev/null` -- a ticket's mandated Run
        Command -- handed the bare `>` to the role decision as a file
        named '>'."""
        for cmd in ("pytest -q | tee logs/latest.log > /dev/null",
                    "echo hi | tee logs/a.log >/dev/null 2>&1"):
            self.assertEqual(self.bash("evaluator", cmd), self.ALLOW, cmd)

    def test_dev_null_is_never_a_target(self):
        self.assertNotIn("/dev/null",
                         hook.bash_write_targets("rm -f x > /dev/null"))

    # ---- 2c51532: `>=` and heredoc bodies ---------------------------

    def test_ge_comparison_is_not_a_redirect(self):
        """A read-only Evaluator heredoc doing `if s['reward'] >= 1` was
        denied as a shell write to '=1'."""
        self.assertEqual(hook.bash_write_targets("if s['reward'] >= 1:"),
                         [])
        self.assertEqual(
            self.bash("evaluator", "awk '$2 >= 1 {print}' logs/a.log"),
            self.ALLOW)

    def test_heredoc_body_is_data_not_shell(self):
        """The docstring has always declared heredocs out of scope --
        fail OPEN. Scanning their lines made them fail CLOSED instead:
        the code contradicting its own contract."""
        cmd = ("python3 - <<'PY'\n"
               "open('Architecture.md').read()\n"
               "x = 1 > 0\n"
               "PY")
        self.assertEqual(hook.bash_write_targets(cmd), [])

    # ---- be7fe1b: a quoted `>` is literal ---------------------------

    def test_quoted_span_holds_no_redirect(self):
        """`git show --format='%an <%ae>%n...'` denied a read-only
        Evaluator as a write to '%n%ad%n%s%n'."""
        self.assertEqual(
            self.bash("evaluator",
                      "git show -s --format='%an <%ae>%n%ad' HEAD"),
            self.ALLOW)

    def test_a_quoted_write_target_is_still_caught(self):
        """The blanking is scoped to spans that CONTAIN shell
        metacharacters, so quoting a target does not launder it."""
        self.assertEqual(self.bash("generator", "tee 'Plan.md' < a"),
                         self.DENY)

    # ---- 975a946: the git net spanned LINES -------------------------

    def test_git_net_does_not_span_lines(self):
        """A read-only `git log` on one line and a bare `add` anywhere
        later in the same multi-line Bash batch matched as one command.
        Nine denials and a killed audit at loop 6, ticket 1."""
        self.assertEqual(
            self.bash("evaluator",
                      "git log --oneline -3\n"
                      "echo 'now add up the rows'\n"
                      "wc -l results/*.json"),
            self.ALLOW)

    def test_git_writes_still_denied_after_the_narrowing(self):
        for cmd in ("git commit -m x", "git add -A", "git  checkout main",
                    "cd /tmp && git push", "git tag v1.0",
                    "git stash", "git worktree add ../x"):
            self.assertEqual(self.bash("evaluator", cmd), self.DENY, cmd)

    # ---- e7cd02b / 8cd5a8b: listing forms, redirect or not ----------

    def test_git_listing_forms_are_reads(self):
        for cmd in ("git tag", "git tag -l", "git tag -l 'v8.*'",
                    "git tag -n1", "git stash list", "git stash show",
                    "git worktree list", "git worktree list 2>&1",
                    "git tag | head -5"):
            self.assertEqual(self.bash("evaluator", cmd), self.ALLOW, cmd)

    # ---- v8.1.14: a quoted span is not a command --------------------

    def test_echo_label_naming_git_is_not_a_git_command(self):
        """The exact command that killed contract review round 3 of
        aibench loop 11 (2026-08-19 06:17). Every part of it is
        read-only; the real `git worktree list` is scrubbed by
        GIT_READONLY and the ECHO LABEL next to it was not."""
        self.assertEqual(
            self.bash("evaluator",
                      'ls && echo "--- results/repro ---" '
                      '&& ls -la results/repro 2>&1 | head '
                      '&& echo "--- git worktree ---" '
                      '&& git worktree list && pwd'),
            self.ALLOW)

    def test_a_quoted_git_write_as_an_argument_is_data(self):
        """Same class, other shapes: grepping a log for a git command,
        and a heading in single quotes."""
        for cmd in ('grep -c "git commit" logs/driver.log',
                    "echo '--- git add ---'",
                    'printf "%s\n" "git push origin main"'):
            self.assertEqual(self.bash("evaluator", cmd), self.ALLOW, cmd)

    def test_a_real_git_write_with_a_quoted_argument_is_still_denied(self):
        """Blanking quoted spans must not blank the command itself."""
        for cmd in ('git commit -m "wip: something"',
                    "git commit -m 'wip'",
                    'git checkout -b "loop/x"'):
            self.assertEqual(self.bash("evaluator", cmd), self.DENY, cmd)

    def test_interpreter_escape_in_quotes_is_knowingly_out_of_scope(self):
        """ASSERTS A HOLE, so it is visible rather than discovered.

        `sh -c "git push"` executes its quoted argument, so blanking
        quoted spans fails OPEN on it. That is an interpreter escape --
        out of scope by the module docstring exactly like `python3 -c`
        -- and adversarial containment is the VM plus the worktree
        (loop-protocol.md #3). If this test ever needs to flip, the fix
        is to confine the process, not to grow a shell parser here."""
        self.assertEqual(self.bash("evaluator", 'sh -c "git push"'),
                         self.ALLOW)

    # ---- 2bac8fd: redirects are not positional arguments ------------

    def test_redirect_is_not_a_copy_destination(self):
        """`cp -a a.log /tmp/b.log 2>/dev/null` handed `2>/dev/null` to
        the trailing-argument rule as its destination."""
        self.assertEqual(
            self.bash("evaluator", "cp -a logs/a.log /tmp/b.log 2>/dev/null"),
            self.ALLOW)

    def test_stripping_redirects_did_not_leak_the_real_target(self):
        """The same bug LEAKED in the other direction: in `cp a.txt
        Architecture.md > /dev/null` the trailing argument was
        `/dev/null`, so the write to a core file was never decided."""
        self.assertEqual(
            self.bash("generator", "cp a.txt Architecture.md > /dev/null"),
            self.DENY)


class TestHookScratchCarveOut(unittest.TestCase):
    """dc16955 (hook hunk): `Write: /tmp/...` was denied while the same
    write through the shell was allowed -- a rule that depends on which
    tool you reach for is not a rule. It stopped a provenance audit on
    the very iteration where five criteria first went green, because
    cdd-evaluator.md REQUIRES reconstructing prior states in /tmp.

    The two v8.1.11 corrections are pinned here: the carve-out is
    decided on the RESOLVED path (the reviewing Evaluator's own
    non-blocking finding F3), and it is two-sided, so a project rooted
    in /tmp is not one big exemption.
    """

    def call(self, role, path, root):
        env = {**os.environ, "CDD_ROLE": role, "CDD_BOUNDARY": "",
               "CLAUDE_PROJECT_DIR": root}
        return subprocess.run(
            [sys.executable, str(HOOK)], env=env, text=True,
            input=json.dumps({"tool_name": "Write",
                              "tool_input": {"file_path": path,
                                             "content": "x"}}),
            capture_output=True).returncode

    def test_tmp_scratch_allowed_for_every_role(self):
        with tempfile.TemporaryDirectory(dir=os.path.expanduser("~")) as d:
            for role in ("evaluator", "generator", "planner"):
                self.assertEqual(
                    self.call(role, "/tmp/evaluator_recheck.py", d), 0, role)

    def test_symlink_out_of_tmp_is_decided_on_the_target(self):
        """F3, filed by the Evaluator that reviewed the carve-out:
        `abspath` follows nothing, so /tmp/x -> <repo>/Architecture.md
        read as scratch and was permitted."""
        with tempfile.TemporaryDirectory(dir=os.path.expanduser("~")) as d:
            (Path(d) / "Architecture.md").write_text("# arch\n")
            link = Path(tempfile.mkdtemp()) / "sneaky"
            link.symlink_to(Path(d) / "Architecture.md")
            self.addCleanup(shutil.rmtree, link.parent, ignore_errors=True)
            self.assertEqual(self.call("generator", str(link), d), 2)

    def test_a_project_rooted_in_tmp_is_not_one_big_carve_out(self):
        """Scratch means outside the REPO. The one-sided prefix check
        exempted every core file of any tree living under /tmp -- a CI
        checkout, or toy_project.sh pointed at /tmp -- and silently."""
        with tempfile.TemporaryDirectory(dir="/tmp") as d:
            self.assertEqual(
                self.call("generator", str(Path(d) / "Architecture.md"), d),
                2)
            self.assertEqual(
                self.call("generator", str(Path(d) / "src" / "a.py"), d), 0)


# ---------- v8.1.12: what a criterion IS, and when it is evidence ------

class TestCriterionIdentity(DriverCase):
    """A criterion was identified by its bare metric name, so two
    measuring the same quantity in different files were one entry in
    `criteria_green`. Live in three loops of the aibench deployment:
    loop 2 carried six criteria under four names, loop 5 thirteen under
    nine (`accuracy` and `n_samples` once per benchmark)
    (journal/from-aibench-retro-20260818.md, failure class 2)."""

    TWO_BENCHMARKS = [
        {"metric": "acc", "op": ">", "value": 0.0,
         "source": "results/a.json"},
        {"metric": "acc", "op": ">", "value": 0.0,
         "source": "results/b.json"},
    ]

    def test_same_metric_in_two_files_is_two_criteria(self):
        self.results({"metrics": {"acc": 0.5}}, "results/a.json")
        self.results({"metrics": {"acc": 0.5}}, "results/b.json")
        _, crit = loop.check_criteria(
            self.write_goal(criteria=self.TWO_BENCHMARKS))
        self.assertEqual({loop.crit_key(r) for r in crit},
                         {"acc@results/a.json", "acc@results/b.json"})

    def test_one_going_red_is_visible_while_the_other_stays_green(self):
        """The damage the collision hid: under bare names the green set
        still contained `acc` from the healthy benchmark, so the
        regression was invisible."""
        (self.tmp / "Plan.md").write_text(PLAN)
        loop.git_commit = lambda msg: "deadbee"
        self.results({"metrics": {"acc": 0.5}}, "results/a.json")
        self.results({"metrics": {"acc": 0.5}}, "results/b.json")

        def fake(_st, role, prompt, *a, **k):
            if role == "generator":                 # breaks ONE of them
                self.results({"metrics": {"acc": 0.0}}, "results/b.json")
            return "done"
        loop.claude = fake
        st = {"phase": "iterate", "iteration": 0, "replans": 0,
              "spent_usd": 0.0, "gpu_hours": 0.0,
              "criteria_green": ["acc@results/a.json",
                                 "acc@results/b.json"],
              "started_epoch": loop.time.time()}
        loop.phase_iterate(self.write_goal(
            criteria=self.TWO_BENCHMARKS,
            evaluation_cadence="final-pass"), st)
        regressions = [e for e in self.events() if e["event"] == "regression"]
        self.assertTrue(regressions)
        self.assertIn("acc@results/b.json", regressions[0]["detail"])
        self.assertNotIn("acc@results/a.json", regressions[0]["detail"])

    def test_pre_8_1_12_state_never_manufactures_a_regression(self):
        """A loop mid-flight over the upgrade has bare names in its
        state file. Dropping them costs at most one extra audit; keeping
        them would read as every criterion regressing at once."""
        self.assertEqual(loop.green_set({"criteria_green": ["acc"]}), set())
        self.assertEqual(
            loop.green_set({"criteria_green": ["acc", "acc@results/a.json"]}),
            {"acc@results/a.json"})


class TestCriteriaDue(DriverCase):
    """Loop 3 iteration 1 went first-green on `passed`/`failed` off loop
    2's committed `results/test-summary.json`, while running a runtime
    probe that writes no test summary. Loop 6 did the same and then paid
    twice: the stale file was cleared, the guard read green->red and
    forced a RETRY, and the Generator stopped to argue that the
    criterion was not its evidence to produce -- on ticket 1 of 9, in
    the loop that cost $70.89 and did not finish."""

    PLAN_LATER_OWNER = """# Plan

### Phase 1, Step 1: Runtime probe
**Boundary:** src/probe.py

### Phase 2, Step 2: Global regression test phase
**Boundary:** results/out.json
**Run Command:** pytest
"""

    def test_a_later_tickets_evidence_is_not_this_tickets_green(self):
        due = loop.criteria_due(self.write_goal(), self.PLAN_LATER_OWNER,
                                "Phase 1, Step 1")
        self.assertEqual(due, [(False, "Phase 2, Step 2")])

    def test_it_is_due_while_its_own_owner_runs(self):
        due = loop.criteria_due(self.write_goal(), self.PLAN_LATER_OWNER,
                                "Phase 2, Step 2")
        self.assertEqual(due, [(True, "Phase 2, Step 2")])

    def test_it_stays_due_once_its_owner_is_committed(self):
        plan = self.PLAN_LATER_OWNER.replace(
            "### Phase 2, Step 2:", "### Phase 2, Step 2 [x]:")
        due = loop.criteria_due(self.write_goal(), plan, "Phase 3, Step 1")
        self.assertEqual(due, [(True, "Phase 2, Step 2")])

    def test_an_unowned_criterion_is_always_due(self):
        """`experiment` goals: the DRIVER launches the trial, so its
        metrics file is in no Boundary. Deferring those would stall
        every correct experiment plan; evidence_gate() covers them."""
        plan = "# Plan\n\n### Phase 1, Step 1: T\n**Boundary:** logs/\n"
        self.assertEqual(loop.criteria_due(self.write_goal(), plan,
                                           "Phase 1, Step 1"),
                         [(True, None)])

    def test_stale_evidence_neither_greens_nor_regresses(self):
        """The whole loop-6 sequence, replayed end to end: a criterion
        owned by a later ticket reads green off a pre-loop file, then
        the file is cleared. Before v8.1.12 that was one false
        `first_green` and one RETRY on a `criteria regression`."""
        (self.tmp / "Plan.md").write_text(self.PLAN_LATER_OWNER)
        loop.git_commit = lambda msg: "deadbee"
        self.results({"metrics": {"acc": 0.9}})     # the stale artifact
        cleared = {"n": 0}

        def fake(_st, role, prompt, *a, **k):
            if role == "generator":
                cleared["n"] += 1
                if cleared["n"] == 1:               # the honest cleanup
                    (self.tmp / "results" / "out.json").unlink()
                else:
                    self.results({"metrics": {"acc": 0.9}})
                    # v8.1.16: the owner's Run Command ran (output gate)
                    (self.tmp / "logs" / "latest.log").write_text("ran")
            if role == "evaluator":
                loop.VERDICT.write_text(json.dumps(
                    {"verdict": "PASS", "reason": "ok"}))
            return "done"
        loop.claude = fake
        st = self.iterate_state()
        loop.phase_iterate(self.write_goal(), st)
        ev = self.events()
        # ticket 1 never claims evidence it does not owe...
        self.assertFalse([e for e in ev if e["event"] == "first_green"
                          and e.get("ticket") in (None, "Phase 1, Step 1")
                          and "acc" in e["detail"]
                          and st["iteration"] == 1])
        # ...and clearing the stale file is not a regression.
        self.assertEqual([e for e in ev if e["event"] == "regression"], [])
        self.assertFalse([r for r in self.ledger()
                          if r["verdict"] == "RETRY"])
        self.assertTrue([e for e in ev if e["event"] == "criterion"
                         and e["detail"].startswith("pend")])


class TestEvidenceGate(DriverCase):
    """Loop 5 sat at its plan gate with four criteria already green off
    loop 4's committed records -- which carried the very harness pin
    that loop existed to replace. The control tower recorded that it
    could not even delete them: under the old bare-name guard that would
    have manufactured a regression and burned an iteration."""

    def test_a_fresh_loop_refuses_evidence_it_did_not_produce(self):
        cfg = self.write_goal()
        self.results({"metrics": {"acc": 0.9}})
        with self.assertRaises(SystemExit):
            loop.evidence_gate(cfg)
        self.assertTrue([e for e in self.events()
                         if e["event"] == "evidence_predates_loop"])

    def test_it_names_every_stale_source_once(self):
        cfg = self.write_goal(criteria=[
            {"metric": "passed", "op": ">=", "value": 1,
             "source": "results/out.json"},
            {"metric": "failed", "op": "==", "value": 0,
             "source": "results/out.json"},
        ])
        self.results({"metrics": {"passed": 3, "failed": 0}})
        with self.assertRaises(SystemExit):
            loop.evidence_gate(cfg)
        detail = [e for e in self.events()
                  if e["event"] == "evidence_predates_loop"][0]["detail"]
        self.assertEqual(detail, "results/out.json")

    def test_a_clean_tree_passes_silently(self):
        loop.evidence_gate(self.write_goal())
        self.assertEqual(self.events(), [])

    def test_a_unique_path_is_the_fix_the_message_asks_for(self):
        """What the gate is FOR: a per-loop path cannot pre-exist, so
        the check is free forever after."""
        self.results({"metrics": {"acc": 0.9}},
                     "results/20260814-run/out.json")
        loop.evidence_gate(self.write_goal(criteria=[
            {"metric": "acc", "op": ">", "value": 0.0,
             "source": "results/20260818-run/out.json"}]))
        self.assertEqual(self.events(), [])


# ---------- v8.1.13: loop 9 and loop 10 -------------------------------

class TestHookResolvesVariables(HookCaller, unittest.TestCase):
    """The false positive that survived 8.1.11 and fired again in loop 10
    (journal/from-aibench-retro-20260819.md), plus the fail-open that a
    mid-loop patch of this same defect shipped -- pinned here because the
    postmortem asks for it to be found by a test and not by a loop."""

    def bash(self, role, cmd, boundary=""):
        return self.call(role, "Bash", {"command": cmd}, boundary)

    # ---- the denial that started it ---------------------------------

    def test_evaluator_tmp_reconstruction_through_a_variable(self):
        """2026-08-19 03:55. The Evaluator's contract REQUIRES rebuilding
        a prior state under /tmp; the scan read `$M` as a repo-relative
        file named '$m'. This denial is what pushed the control tower
        into patching the hook under a running loop."""
        self.assertEqual(
            self.bash("evaluator",
                      'M=/tmp/eval-check; mkdir -p "$M"; cp -r src "$M/"'),
            self.ALLOW)

    def test_unresolvable_expansion_fails_open_as_documented(self):
        """`$(...)` is not something a pattern matcher can follow. The
        module docstring says expansion is out of scope and therefore
        fails OPEN -- the code used to fail CLOSED on it."""
        self.assertEqual(self.bash("evaluator",
                                   "D=$(mktemp -d); echo x > $D/f"),
                         self.ALLOW)

    # ---- the real denials the fix must not lose ---------------------

    def test_a_resolved_core_file_is_still_denied(self):
        for role in ("generator", "evaluator"):
            self.assertEqual(
                self.bash(role, "M=Architecture.md; echo x > $M"),
                self.DENY, role)

    def test_a_resolved_boundary_breach_is_still_denied(self):
        self.assertEqual(
            self.bash("generator", "M=src/other.py; echo x > $M",
                      boundary="src/mine.py"),
            self.DENY)
        self.assertEqual(
            self.bash("generator", "M=src/mine.py; echo x > $M",
                      boundary="src/mine.py"),
            self.ALLOW)

    def test_goal_json_through_a_variable_is_denied(self):
        """Belt and braces: the resolution decides it, and the loose
        co-occurrence net would have caught the name anyway."""
        for role in ("planner", "generator", "evaluator", "monitor"):
            self.assertEqual(self.bash(role, "M=goal.json; echo x > $M"),
                             self.DENY, role)

    # ---- the fail-open the mid-loop patch shipped -------------------

    def test_a_later_reassignment_cannot_re_decide_an_earlier_write(self):
        """THE regression case. The 2026-08-19 patch collected
        assignments with finditer, last-write-wins, so this command --
        which writes Architecture.md at runtime -- was ALLOWED because
        the hook saw the trailing `/tmp/ok`. Resolution is per segment,
        against what precedes it."""
        self.assertEqual(
            self.bash("evaluator",
                      "M=Architecture.md; echo x > $M; M=/tmp/ok"),
            self.DENY)

    def test_reverse_order_is_decided_the_same_way(self):
        """Its mirror: the write really does land in /tmp, and a
        reassignment after it does not make it a core-file write."""
        self.assertEqual(
            self.bash("evaluator",
                      "M=/tmp/ok; echo x > $M; M=Architecture.md"),
            self.ALLOW)

    def test_resolution_is_incremental_not_global(self):
        """Unit-level statement of the same rule, so a rewrite that keeps
        the end-to-end cases green by accident still fails."""
        self.assertEqual(
            hook.bash_write_targets(
                "M=Architecture.md; echo x > $M; M=/tmp/ok"),
            ["Architecture.md"])
        self.assertEqual(
            hook.bash_write_targets("M=/tmp/a; cp x $M; M=/tmp/b; cp y $M"),
            ["/tmp/a", "/tmp/b"])


class TestHookHeredocBodyIsDataOnEveryScan(HookCaller, unittest.TestCase):
    """2026-08-19 03:02: the Planner writing the file it OWNS with
    `cat > Plan.md <<'PLANEOF'` was denied "Git write commands are
    driver-only" -- prose in the plan body put `git` and a subcommand
    word on one line. v8.1.11 truncated heredocs inside
    bash_write_targets() only, so the git net and the loose net still
    read the body as shell."""

    def bash(self, role, cmd, boundary=""):
        return self.call(role, "Bash", {"command": cmd}, boundary)

    PLAN = ("cat > Plan.md <<'PLANEOF'\n"
            "# Plan\n"
            "Check the clone with git status and confirm it is clean.\n"
            "Criteria are read from goal.json by the driver; tee the run\n"
            "to logs/latest.log.\n"
            "PLANEOF")

    def test_planner_writes_its_own_file_through_a_heredoc(self):
        self.assertEqual(self.bash("planner", self.PLAN), self.ALLOW)

    def test_the_body_cannot_manufacture_a_goal_file_denial(self):
        """The loose net reads `goal.json` and `tee` in the body. Denying
        prose is the false positive; a real write is decided by target."""
        self.assertEqual(
            self.bash("planner", self.PLAN.replace("Plan.md", "Triage.md")),
            self.ALLOW)

    def test_a_real_git_write_before_the_heredoc_is_still_denied(self):
        self.assertEqual(
            self.bash("planner", "git add -A && " + self.PLAN), self.DENY)

    def test_a_real_target_before_the_heredoc_is_still_denied(self):
        self.assertEqual(
            self.bash("generator",
                      "echo x > Architecture.md; " + self.PLAN),
            self.DENY)

    def test_the_evaluator_still_cannot_write_a_plan(self):
        """The heredoc body is data; the redirect in front of it is not."""
        self.assertEqual(self.bash("evaluator", self.PLAN), self.DENY)


class TestSessionDeathIsNotAVerdict(DriverCase):
    """2026-08-18 17:10: the provenance Evaluator died on its first token
    with API Error 529 Overloaded and wrote nothing. The driver read the
    absent verdict.json as ESCALATE and stopped a loop whose 2.7h trial
    had already SUCCEEDED -- a human, a hand-made commit and a restart,
    and a restart costs an iteration
    (journal/from-aibench-retro-20260819.md, escalation 2)."""

    def setUp(self):
        super().setUp()
        self.write_goal()

    def stub_runs(self, *stdouts):
        """One dispatch per argument, in order. An empty stdout is a
        session that died: no output, non-zero exit."""
        seen = []
        real = loop.subprocess

        def run(*a, **k):
            out = stdouts[len(seen)] if len(seen) < len(stdouts) else ""
            seen.append(out)
            return types.SimpleNamespace(
                stdout=out, returncode=0 if out else 1,
                stderr="" if out else "API Error 529 Overloaded")
        loop.subprocess = types.SimpleNamespace(
            run=run, Popen=real.Popen, STDOUT=real.STDOUT)
        self.addCleanup(lambda: setattr(loop, "subprocess", real))
        return seen

    def test_a_dead_session_is_redispatched_once(self):
        ok = json.dumps({"total_cost_usd": 2.0, "result": "fine"})
        seen = self.stub_runs("", ok)
        st = {"spent_usd": 0.0}
        self.assertEqual(loop.claude(st, "evaluator", "p"), "fine")
        self.assertEqual(len(seen), 2)
        self.assertEqual(st["spent_usd"], 2.0)          # billed once
        self.assertFalse(st["session_died"])
        died = [e for e in self.events() if e["event"] == "session_died"]
        self.assertEqual(len(died), 1)
        self.assertIn("529", died[0]["detail"])

    def test_two_deaths_are_recorded_as_a_dead_session(self):
        seen = self.stub_runs("", "")
        st = {"spent_usd": 0.0}
        loop.claude(st, "evaluator", "p")
        self.assertEqual(len(seen), 2)                  # and not a third
        self.assertTrue(st["session_died"])
        self.assertEqual(len([e for e in self.events()
                              if e["event"] == "session_died"]), 2)

    def test_a_live_session_is_never_marked_dead(self):
        self.stub_runs(json.dumps({"total_cost_usd": 1.0, "result": "r"}))
        st = {"spent_usd": 0.0}
        loop.claude(st, "evaluator", "p")
        self.assertFalse(st["session_died"])
        self.assertEqual([e for e in self.events()
                          if e["event"] == "session_died"], [])

    def test_the_escalation_says_which_failure_it_was(self):
        """A dead session leaves the ticket's work intact and unjudged; a
        live session that wrote no verdict is a protocol failure. The
        human's next move differs, so the reason must too."""
        (self.tmp / "Plan.md").write_text(PLAN)
        loop.git_commit = lambda msg: "deadbee"
        self.results({"metrics": {"acc": 0.5}})

        def dead(st, role, *a, **k):
            st["session_died"] = role == "evaluator"
            return ""
        loop.claude = dead
        st = self.iterate_state()
        loop.phase_iterate(self.write_goal(), st)
        self.assertTrue(any(e["event"] == "escalate" for e in self.events()))
        reason = self.ledger()[-1]["reason"]
        self.assertIn("died", reason)
        self.assertNotIn("missing verdict.json", reason)


class TestStopAdjudication(DriverCase):
    """v8.1.15. A Generator stop is adjudicated by one Evaluator
    session instead of auto-escalating. REPLAN fired zero times in
    fifteen deployed loops because its only entrance was a Mode-2
    verdict and a stop returned before any Evaluator ran
    (journal/retro-20260824-aibench.md, rec 3)."""

    def setUp(self):
        super().setUp()
        (self.tmp / "Plan.md").write_text(PLAN)
        loop.git_commit = lambda msg: "deadbee"
        loop.wait_approval = lambda st, name, detail: None
        loop.flush_pregate = lambda what: "deadbee"
        self.results({"metrics": {"acc": 0.5}})

    def iterate_state(self):
        return {"phase": "iterate", "iteration": 0, "replans": 0,
                "spent_usd": 0.0, "gpu_hours": 0.0, "criteria_green": [],
                "started_epoch": loop.time.time()}

    def test_adjudicated_replan_reaches_the_replan_path(self):
        """Stop -> Mode 3 REPLAN -> fresh plan, contract review, gate --
        the same route an Evaluator Mode-2 REPLAN has always taken."""
        state = {"stopped_once": False}

        def fake(_st, role, prompt, *a, **k):
            if role == "generator":
                if not state["stopped_once"]:
                    state["stopped_once"] = True
                    return "STATUS: stopped — spec contradicts Goal.md"
                return "done"
            if "Mode 3" in prompt:
                loop.VERDICT.write_text(json.dumps(
                    {"verdict": "REPLAN",
                     "reason": "the plan reads a shape that is not there",
                     "evidence": ["Goal.md:15 vs Plan.md P1S1 Spec"]}))
            elif "Mode 1" in prompt:
                loop.VERDICT.write_text(json.dumps(
                    {"verdict": "OK", "reason": "reviewed"}))
            elif "Mode 2" in prompt:
                loop.VERDICT.write_text(json.dumps(
                    {"verdict": "PASS", "reason": "ok",
                     "evidence": ["pytest: 3 passed"]}))
            return "done"
        loop.claude = fake
        st = self.iterate_state()
        loop.phase_iterate(self.write_goal(), st)
        self.assertEqual(st["replans"], 1)
        self.assertEqual(st["phase"], "final_eval",
                         "the loop continues after the gated replan")
        self.assertTrue(any(e["event"] == "replan" for e in self.events()))
        self.assertTrue(any(e["event"] == "stop_adjudicated"
                            and "REPLAN" in e["detail"]
                            for e in self.events()))
        rows = [r for r in self.ledger() if r.get("stopped")]
        self.assertEqual(len(rows), 1, "the stop is a ledger row")
        self.assertEqual(rows[0]["verdict"], "REPLAN")

    def test_adjudicated_retry_carries_what_was_missed(self):
        """Stop -> Mode 3 RETRY -> the next Generator dispatch carries
        the adjudicator's reason (the v8.1.6 retry-carries-why path)."""
        prompts = []
        state = {"stopped_once": False}

        def fake(_st, role, prompt, *a, **k):
            if role == "generator":
                prompts.append(prompt)
                if not state["stopped_once"]:
                    state["stopped_once"] = True
                    return "STATUS: stopped — thinks the spec is circular"
                return "done"
            if "Mode 3" in prompt:
                loop.VERDICT.write_text(json.dumps(
                    {"verdict": "RETRY",
                     "reason": "step 2's input is written by step 1; "
                               "re-read the Depends On field"}))
            else:
                loop.VERDICT.write_text(json.dumps(
                    {"verdict": "PASS", "reason": "ok", "evidence": []}))
            return "done"
        loop.claude = fake
        st = self.iterate_state()
        loop.phase_iterate(self.write_goal(), st)
        self.assertEqual(st["replans"], 0)
        self.assertIn("re-read the Depends On field", prompts[1],
                      "attempt 2 must carry the adjudicator's reason")
        self.assertEqual(st["phase"], "final_eval")

    def test_adjudicated_escalate_reaches_the_user(self):
        def fake(_st, role, prompt, *a, **k):
            if role == "generator":
                return "STATUS: stopped — goal.json itself is wrong"
            if "Mode 3" in prompt:
                loop.VERDICT.write_text(json.dumps(
                    {"verdict": "ESCALATE",
                     "reason": "the defect implicates the goal contract"}))
            return "done"
        loop.claude = fake
        st = self.iterate_state()
        loop.phase_iterate(self.write_goal(), st)
        self.assertTrue(any(e["event"] == "escalate"
                            and "goal contract" in e["detail"]
                            for e in self.events()))
        self.assertNotIn("[x]", (self.tmp / "Plan.md").read_text())

    def test_dead_or_junk_adjudication_fails_closed(self):
        """An adjudicator that wrote nothing decides nothing: the stop
        escalates exactly as it did before v8.1.15 -- including the
        Generator's own stop report, which is the human's evidence."""
        loop.claude = lambda _st, role, *a, **k: (
            "STATUS: stopped — needs an architectural decision"
            if role == "generator" else "")
        st = self.iterate_state()
        loop.phase_iterate(self.write_goal(), st)
        ev = [e for e in self.events() if e["event"] == "escalate"]
        self.assertTrue(ev)
        self.assertIn("needs an architectural decision", ev[0]["detail"])
        self.assertEqual(st["replans"], 0)


class TestReplanCLI(DriverCase):
    """v8.1.15. `loop.py replan "<reason>"` -- the user-initiated half
    of the REPLAN route. L5 hand-edited loop-state.json for lack of it;
    two retros recommended it before it shipped."""

    def replan(self, *extra):
        return subprocess.run(
            [sys.executable, str(HERE / "loop.py"), "replan", *extra],
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(self.tmp)},
            capture_output=True, text=True)

    def test_queues_a_plan_phase_with_the_reason(self):
        loop.save(loop.STATE, {"phase": "iterate", "replans": 0})
        r = self.replan("hook denied the run command")
        self.assertEqual(r.returncode, 0, r.stderr)
        st = loop.load(loop.STATE, {})
        self.assertEqual(st["phase"], "plan")
        self.assertEqual(st["replans"], 1)
        self.assertEqual(st["replan_reason"],
                         "hook denied the run command")
        self.assertTrue(any(e["event"] == "replan"
                            and "user-initiated" in e["detail"]
                            for e in self.events()))

    def test_empty_reason_is_refused(self):
        loop.save(loop.STATE, {"phase": "iterate"})
        r = self.replan()
        self.assertEqual(r.returncode, 1)
        self.assertIn("usage", r.stderr)
        self.assertEqual(loop.load(loop.STATE, {})["phase"], "iterate")

    def test_no_state_file_is_refused(self):
        r = self.replan("anything")
        self.assertEqual(r.returncode, 1)
        self.assertIn("nothing to replan", r.stderr)

    def test_phase_plan_pops_the_queued_reason(self):
        """main() passes nothing -- the reason rides the state file, and
        an absent Evaluation.md must not crash the prompt build."""
        (self.tmp / "Plan.md").write_text(PLAN)
        prompts = []
        loop.claude = (lambda _st, role, prompt, *a, **k:
                       prompts.append(prompt) or "done")
        cfg = self.write_goal()
        st = {"phase": "plan", "replans": 1,
              "replan_reason": "the smoke bar was wrong"}
        loop.phase_plan(cfg, st)
        self.assertIn("This is a REPLAN", prompts[0])
        self.assertIn("the smoke bar was wrong", prompts[0])
        self.assertIn("(none on disk)", prompts[0])
        self.assertNotIn("replan_reason", st)


# ---------- 8.1.16: the two 2026-09-02 retros ---------------------------

class TestHookRetro20260902(HookCaller, unittest.TestCase):
    """journal/from-agentrl-retro-20260902.md problem 1 and
    journal/from-aibench-retro-20260902.md problem 2: ~110 denials
    across twelve loops, five sessions killed, one plan reshaped to
    route around the net. Two shapes behind nearly all of them -- a
    relative target under a `cd` decided against the repo root, and a
    token inside a quoted span read as a command -- plus the two listing
    forms and the escaped quote found on the way. Each false positive is
    pinned NEXT to the real denial beside it, because every one of these
    fixes narrows a net that is load-bearing."""

    def bash(self, role, cmd, boundary=""):
        return self.call(role, "Bash", {"command": cmd}, boundary)

    # ---- cd is tracked per segment, like assignments -----------------

    def test_cd_into_tmp_makes_relative_targets_scratch(self):
        for cmd in ("cd /tmp && echo x > notes.txt",
                    "cd /tmp && mkdir -p x && cp -r /repo/src x/",
                    "cd /tmp/eval && cd .. && echo hi > eval/x",
                    "M=/tmp/w; mkdir -p $M; cd $M && echo x > out.txt",
                    "(cd /tmp && tee scratch.txt < /dev/null)"):
            self.assertEqual(self.bash("evaluator", cmd), self.ALLOW, cmd)

    def test_position_is_the_rule(self):
        """A cd AFTER the write does not rebase it -- the reverse-order
        case the v8.1.13 assignment fix mandated for its class."""
        self.assertEqual(self.bash("generator",
                                   "echo x > Plan.md; cd /tmp", "src/"),
                         self.DENY)

    def test_cd_inside_the_repo_is_still_decided(self):
        self.assertEqual(self.bash("generator",
                                   "cd src && echo x > Plan.md", "src/"),
                         self.DENY)
        self.assertEqual(self.bash("generator",
                                   "cd tests && echo x > test_a.py",
                                   "tests/"), self.ALLOW)
        self.assertEqual(self.bash("generator",
                                   "cd tests && echo x > test_a.py",
                                   "src/"), self.DENY)

    def test_a_cd_and_a_dotdot_resolve_to_the_real_target(self):
        """The fail-CLOSED direction of the same fix. Before 8.1.16 this
        write to a core file was ALLOWED: `../../Architecture.md` decided
        against the repo root resolved outside the repo."""
        self.assertEqual(self.bash(
            "generator", "cd src/pkg && echo x > ../../Architecture.md",
            "src/"), self.DENY)

    def test_an_unfollowable_cd_fails_open_as_documented(self):
        """Pinned as a known gap: a cd the hook cannot resolve leaves
        every later RELATIVE target undecidable, and the module docstring
        says expansion fails OPEN. An absolute target needs no cwd."""
        self.assertEqual(self.bash("generator",
                                   "cd $UNSET && echo x > Plan.md", "src/"),
                         self.ALLOW)
        self.assertEqual(self.bash("generator",
                                   "cd $UNSET && echo x > /repo/Plan.md",
                                   "src/"), self.DENY)

    # ---- loose net: quoted spans are data ----------------------------

    def test_a_grep_pattern_naming_rm_is_not_a_write(self):
        cmd = 'grep -n "rm -rf\\|shutil\\." src/x.py loop-state.json'
        self.assertEqual(self.bash("evaluator", cmd), self.ALLOW)
        self.assertEqual(self.bash("evaluator", "rm loop-state.json"),
                         self.DENY, "the real rm is still caught")
        self.assertEqual(self.bash("evaluator", 'tee "goal.json" < x'),
                         self.DENY, "a quoted TARGET is still a target")

    # ---- escaped quotes ----------------------------------------------

    def test_an_escaped_quote_does_not_end_the_span(self):
        cmd = 'python3 -c "print(f\\"{x:>5}\\")"'
        self.assertEqual(self.bash("evaluator", cmd), self.ALLOW)
        self.assertEqual(self.bash("evaluator", cmd + " > Plan.md"),
                         self.DENY, "the redirect after it is real")

    # ---- listing forms take options ----------------------------------

    def test_listing_forms_take_options(self):
        for cmd in ("git worktree list --porcelain 2>&1 | head",
                    "git stash show -p", "git stash list --oneline"):
            self.assertEqual(self.bash("evaluator", cmd), self.ALLOW, cmd)
        for cmd in ("git worktree add ../x", "git stash", "git stash pop"):
            self.assertEqual(self.bash("evaluator", cmd), self.DENY, cmd)

    # ---- one denial, one record --------------------------------------

    def test_a_multiline_command_is_one_denial_record(self):
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "CDD_ROLE": "generator",
                   "CDD_BOUNDARY": "", "CLAUDE_PROJECT_DIR": d}
            cmd = "echo a\necho b\necho x > Architecture.md\necho c"
            r = subprocess.run(
                [sys.executable, str(HOOK)], env=env, text=True,
                capture_output=True,
                input=json.dumps({"tool_name": "Bash",
                                  "tool_input": {"command": cmd}}))
            self.assertEqual(r.returncode, self.DENY)
            lines = (Path(d) / "logs" / "denials.log").read_text() \
                .splitlines()
            self.assertEqual(len(lines), 1)
            self.assertIn("\\n", lines[0])


class TestDenialsAreCountedAsRecords(DriverCase):
    """journal/from-agentrl-retro-20260902.md problem 9: a log written by
    an older hook carries a command's newlines; a record starts with its
    timestamp."""

    def test_an_old_multiline_record_counts_once(self):
        (self.tmp / "logs" / "denials.log").write_text(
            "2026-09-01T10:00:00\tgenerator\tmsg\tBash: echo a\necho b\n"
            "2026-09-01T10:00:05\tevaluator\tmsg\tBash: x\n")
        self.assertEqual(loop.denials_seen(), 2)


class TestGpuCapZeroIsNoCap(DriverCase):
    """journal/from-aibench-retro-20260902.md problem 5: `max_gpu_hours:
    0` escalated the OpenRouter smoke during its contract review."""

    def test_zero_is_not_breached_before_the_first_tick(self):
        cfg = {"budgets": {"max_gpu_hours": 0}}
        self.assertEqual(loop.budget_exceeded({"gpu_hours": 0.0}, cfg), "")
        self.assertEqual(loop.budget_exceeded({"gpu_hours": 9.0}, cfg), "")

    def test_a_positive_cap_still_trips(self):
        cfg = {"budgets": {"max_gpu_hours": 1}}
        self.assertEqual(loop.budget_exceeded({"gpu_hours": 1.5}, cfg),
                         "max_gpu_hours")


class TestTrialRunsUnderBash(DriverCase):
    """journal/from-agentrl-retro-20260902.md problem 3: `shell=True` is
    /bin/sh, which is dash on Ubuntu, so a Trial using the framework's
    own `${BASH_SOURCE[0]}` idiom broke the moment a Phase became one."""

    def setUp(self):
        super().setUp()
        loop.time = FakeClock(step=0.0)
        loop.claude = lambda *a, **k: '{"status": "HEALTHY"}'

    def test_a_bash_only_idiom_runs(self):
        body = ("**Trial:** [[ -n ${BASH_VERSION:-} ]] && [[ 1 == 1 ]]\n"
                "**Monitor Profile:** none")
        self.assertTrue(loop.run_trial("T", body, {"iteration": 1},
                                       self.write_goal()))


class TestMonitorMemory(DriverCase):
    """journal/from-aibench-retro-20260902.md problem 1 (five false
    kills, one true), journal/from-agentrl-retro-20260902.md problem 7
    (a kill at 159/160 on a URL the eval prints on every call). The
    Monitor is handed its own last verdicts, and a kill whose quoted
    evidence sat in a window a prior poll judged HEALTHY is overruled by
    the driver."""

    NOISE = "WARN litellm: see https://prices.example/table for pricing"

    def setUp(self):
        super().setUp()
        loop.time = FakeClock(step=600.0)

    def run_with(self, evidence, status="INTERVENE"):
        state = {"seen": 0, "prompts": []}

        def fake(_st, role, prompt, *a, **k):
            state["prompts"].append(prompt)
            if self.NOISE in prompt.split("Trial log tail:")[-1]:
                state["seen"] += 1
                if state["seen"] > 1:
                    return json.dumps({"status": status,
                                       "signature": "context_window",
                                       "evidence": evidence})
            return '{"status": "HEALTHY"}'
        loop.claude = fake
        cfg = self.write_goal(monitor={"interval_min": 1})
        body = (f"**Trial:** echo '{self.NOISE}'; sleep 0.7\n"
                f"**Monitor Profile:** none")
        ok = loop.run_trial("T", body, {"iteration": 1}, cfg)
        self.assertGreater(state["seen"], 1,
                           "the trial ended before a second sighting")
        return ok, state

    def test_a_line_judged_healthy_once_cannot_kill_later(self):
        ok, state = self.run_with(self.NOISE)
        self.assertTrue(ok)
        kinds = [e["event"] for e in self.events()]
        self.assertIn("monitor_overruled", kinds)
        self.assertNotIn("trial_killed", kinds)

    def test_a_new_line_still_kills(self):
        ok, _ = self.run_with("RuntimeError: CUDA error: out of memory")
        self.assertFalse(ok)
        self.assertIn("trial_killed", [e["event"] for e in self.events()])

    def test_a_kill_escalate_on_old_noise_is_overruled_too(self):
        ok, _ = self.run_with(self.NOISE, status="KILL_ESCALATE")
        self.assertTrue(ok)
        self.assertNotIn("escalate", [e["event"] for e in self.events()])

    def test_the_monitor_sees_its_previous_verdicts(self):
        _, state = self.run_with(self.NOISE)
        self.assertIn("none yet", state["prompts"][0])
        later = state["prompts"][-1]
        self.assertIn("previous verdicts", later)
        self.assertIn("HEALTHY", later.split("Trial log tail:")[0])


class TestSeedEnvAndVenv(DriverCase):
    """journal/from-aibench-retro-20260902.md problem 7: three loops
    failed their own preflight on the first `start` because the
    worktree had no `.env` and no virtualenv."""

    def dirs(self):
        primary, wt = self.tmp / "primary", self.tmp / "wt"
        primary.mkdir(), wt.mkdir()
        return primary, wt

    def test_env_is_copied_and_the_venv_is_linked(self):
        primary, wt = self.dirs()
        (primary / ".env").write_text("KEY=secret\n")
        (primary / ".venv" / "bin").mkdir(parents=True)
        loop.seed_goal_files(primary, wt)
        self.assertEqual((wt / ".env").read_text(), "KEY=secret\n")
        self.assertFalse((wt / ".env").is_symlink())
        self.assertTrue((wt / ".venv").is_symlink())
        self.assertTrue((wt / ".venv" / "bin").is_dir())

    def test_the_worktrees_own_copies_are_never_replaced(self):
        primary, wt = self.dirs()
        (primary / ".env").write_text("KEY=primary\n")
        (primary / "venv").mkdir()
        (wt / ".env").write_text("KEY=mine\n")
        (wt / "venv").mkdir()
        loop.seed_goal_files(primary, wt)
        self.assertEqual((wt / ".env").read_text(), "KEY=mine\n")
        self.assertFalse((wt / "venv").is_symlink())

    def test_nothing_to_seed_seeds_nothing(self):
        primary, wt = self.dirs()
        loop.seed_goal_files(primary, wt)
        self.assertEqual(sorted(p.name for p in wt.iterdir()), [])


class TestJournalShowsDenialsAndNotes(DriverCase):
    """journal/from-aibench-retro-20260902.md problem 2: the driver
    emitted `hook_denials` since 8.1.9 and the journal filtered it out,
    so ~90 denials were counted by hand. Plus the user's own `note`
    events, and the record saying what survives a rewrite."""

    def test_the_new_notable_events_reach_the_record(self):
        (self.tmp / "Plan.md").write_text(PLAN)
        loop.event("hook_denials",
                   detail="evaluator: 3 authority denial(s)")
        loop.event("note", detail="swapped SIM_MODEL by hand", by="user")
        loop.event("stop_adjudicated", detail="Phase 1, Step 1: REPLAN")
        loop.event("monitor_overruled", detail="INTERVENE on old noise")
        st = {"phase": "done", "iteration": 1, "replans": 0,
              "spent_usd": 1.0, "started": "2026-09-02T10:00:00+00:00",
              "started_epoch": loop.time.time()}
        text = loop.write_journal(self.write_goal(), st).read_text()
        for needle in ("hook_denials", "3 authority denial",
                       "swapped SIM_MODEL", "stop_adjudicated",
                       "monitor_overruled",
                       "Only the `## Feedback` block survives"):
            self.assertIn(needle, text)


class TestNoteCLI(DriverCase):
    """journal/from-agentrl-retro-20260902.md problem 4: every loop had
    a manual change made under the running driver and none was recorded
    at the moment it happened. `loop.py note "<text>"` is the record."""

    def note(self, *extra):
        return subprocess.run(
            [sys.executable, str(HERE / "loop.py"), "note", *extra],
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(self.tmp)},
            capture_output=True, text=True)

    def test_a_note_is_an_event_the_journal_shows(self):
        loop.save(loop.STATE, {"phase": "iterate"})
        r = self.note("deleted iterations 1-4 checkpoints to free disk")
        self.assertEqual(r.returncode, 0, r.stderr)
        ev = [e for e in self.events() if e["event"] == "note"]
        self.assertEqual(len(ev), 1)
        self.assertIn("checkpoints", ev[0]["detail"])
        self.assertEqual(ev[0].get("by"), "user")

    def test_an_empty_note_is_refused(self):
        loop.save(loop.STATE, {"phase": "iterate"})
        r = self.note()
        self.assertEqual(r.returncode, 1)
        self.assertIn("usage", r.stderr)
        self.assertEqual(self.events(), [])


class TestContractReviewIsRemembered(DriverCase):
    """journal/from-aibench-retro-20260819.md rec 6, owed since;
    journal/from-aibench-retro-20260902.md problem 8. A restart forgot
    every review round already bought: an OK plan was re-reviewed and a
    REVISE'd plan re-reviewed before being revised. The memory is for
    RESUME only -- within a run, reviews = revisions + 1 still holds."""

    def setUp(self):
        super().setUp()
        (self.tmp / "Plan.md").write_text(PLAN)

    def review(self, memo, planner_rewrites=False):
        calls = []

        def fake(_st, role, prompt, *a, **k):
            calls.append(role)
            if role == "evaluator":
                loop.VERDICT.write_text(json.dumps({"verdict": "OK"}))
            if role == "planner" and planner_rewrites:
                (self.tmp / "Plan.md").write_text(PLAN + "\n<!-- v2 -->\n")
            return ""
        loop.claude = fake
        st = {"spent_usd": 0.0, "review": memo}
        loop.phase_contract_review(self.write_goal(), st)
        return calls, st

    def test_an_ok_review_of_an_unchanged_plan_is_not_rebought(self):
        calls, st = self.review({"plan_hash": loop.plan_hash(),
                                 "verdict": "OK", "revision": 0})
        self.assertEqual(calls, [])
        self.assertEqual(st["phase"], "gate")
        self.assertTrue(any(e["event"] == "contract_review_reused"
                            for e in self.events()))

    def test_a_revise_of_an_unchanged_plan_buys_the_revision_not_the_review(self):
        calls, st = self.review({"plan_hash": loop.plan_hash(),
                                 "verdict": "REVISE", "revision": 1},
                                planner_rewrites=True)
        self.assertEqual(calls, ["planner", "evaluator"])
        self.assertEqual(st["phase"], "gate")

    def test_a_changed_plan_is_reviewed_afresh_and_remembered(self):
        calls, st = self.review({"plan_hash": "stale", "verdict": "OK",
                                 "revision": 0})
        self.assertEqual(calls, ["evaluator"])
        self.assertEqual(st["review"]["plan_hash"], loop.plan_hash())
        self.assertEqual(st["review"]["verdict"], "OK")

    def test_the_round_count_resumes_too(self):
        """A REVISE recorded at the last revision leaves nothing to buy:
        the restart escalates instead of granting two more rounds."""
        with self.assertRaises(SystemExit):
            self.review({"plan_hash": loop.plan_hash(), "verdict": "REVISE",
                         "revision": loop.MAX_REVISIONS})


OUTPUT_PLAN = """# Plan

### Phase 1, Step 1: Build the writer
**Output:** src/writer.py, results/out.json (the metrics file; read/write
of v1.0 data)
**Boundary:** src/, results/out.json
**Run Command:** python3 src/writer.py 2>&1 | tee logs/latest.log
"""


class TestOutputGate(DriverCase):
    """journal/from-aibench-retro-20260902.md problem 3 (a ticket PASSed
    having produced nothing, three times in two loops) and
    journal/from-agentrl-retro-20260902.md problems 3 and 9 (an
    abandoned Run Command is the one case an unchanged retry is for)."""

    def setUp(self):
        super().setUp()
        (self.tmp / "Plan.md").write_text(OUTPUT_PLAN)
        loop.git_commit = lambda msg: "deadbee"

    def drive(self, generator):
        calls = []

        def fake(_st, role, prompt, *a, **k):
            calls.append((role, prompt))
            if role == "generator":
                generator()
            if role == "evaluator":
                loop.VERDICT.write_text(json.dumps(
                    {"verdict": "ESCALATE", "reason": "cap"}
                    if "retry-cap" in prompt else
                    {"verdict": "PASS", "reason": "ok", "evidence": []}))
            return "done"
        loop.claude = fake
        st = self.iterate_state()
        loop.phase_iterate(self.write_goal(), st)
        return calls, st

    def ran(self):
        (self.tmp / "logs" / "latest.log").write_text("ran")

    def complete(self):
        (self.tmp / "src").mkdir(exist_ok=True)
        (self.tmp / "src" / "writer.py").write_text("print(1)")
        self.results({"metrics": {"acc": 0.5}})
        self.ran()

    def gates(self):
        return [e for e in self.events() if e["event"] == "output_gate"]

    def test_output_paths_come_from_prose_and_stay_inside_the_boundary(self):
        self.assertEqual(loop.output_paths(OUTPUT_PLAN),
                         ["src/writer.py", "results/out.json"])

    def test_a_missing_output_file_is_a_retry_and_buys_no_audit(self):
        def gen():
            self.results({"metrics": {"acc": 0.5}})
            self.ran()
        calls, st = self.drive(gen)
        self.assertTrue(self.gates())
        self.assertIn("src/writer.py", self.gates()[0]["detail"])
        self.assertEqual([p for r, p in calls
                          if r == "evaluator" and "Mode 2" in p], [])
        self.assertEqual(self.ledger()[0]["verdict"], "RETRY")
        self.assertIn("src/writer.py", self.ledger()[0]["reason"])

    def test_a_run_command_that_left_no_log_is_a_retry(self):
        def gen():
            (self.tmp / "src").mkdir(exist_ok=True)
            (self.tmp / "src" / "writer.py").write_text("x")
            self.results({"metrics": {"acc": 0.5}})
        self.drive(gen)
        self.assertTrue(self.gates())
        self.assertIn("no log", self.gates()[0]["detail"])

    def test_an_owned_criterion_reading_red_blocks_pass(self):
        def gen():
            self.complete()
            self.results({"metrics": {"acc": 0.0}})
        _, st = self.drive(gen)
        self.assertTrue(self.gates())
        self.assertIn("owned criterion", self.gates()[0]["detail"])
        self.assertNotEqual(st.get("phase"), "final_eval")

    def test_a_complete_ticket_passes_through_to_the_audit(self):
        _, st = self.drive(self.complete)
        self.assertEqual(self.gates(), [])
        self.assertEqual(st["phase"], "final_eval")

    def test_the_retry_carries_what_is_missing(self):
        n = {"i": 0}

        def gen():
            n["i"] += 1
            if n["i"] == 2:
                self.complete()
            else:
                self.results({"metrics": {"acc": 0.5}})
                self.ran()
        calls, st = self.drive(gen)
        second = [p for r, p in calls if r == "generator"][1]
        self.assertIn("src/writer.py", second)
        self.assertEqual(st["phase"], "final_eval")

    def test_an_abandoned_run_is_retried_unchanged_not_escalated_as_a_no_op(self):
        calls, _ = self.drive(lambda: None)      # writes nothing, 3x
        self.assertEqual(len([r for r, _ in calls if r == "generator"]), 3)
        self.assertEqual([e for e in self.events()
                          if e["event"] == "no_op_session"], [])
        self.assertTrue([e for e in self.events()
                         if e["event"] == "stop_adjudicated"
                         and "retry cap" in e["detail"]])


class TestRetryCapIsAdjudicated(LiveRunCase):
    """journal/from-aibench-retro-20260902.md problem 4: three attempts,
    three real defects each precisely diagnosed, converging -- stopped by
    the counter; attempt 4 passed an hour later on a human's say-so.
    LiveRunCase, because each attempt here WRITES something -- the no-op
    backstop is a different suite."""

    def setUp(self):
        super().setUp()
        loop.wait_approval = lambda st, name, detail: None
        loop.flush_pregate = lambda what: "deadbee"
        self.results({"metrics": {"acc": 0.5}})

    def drive(self, cap_verdict, pass_on=None):
        calls = []

        def fake(_st, role, prompt, *a, **k):
            calls.append((role, prompt))
            gens = len([r for r, _ in calls if r == "generator"])
            if role == "generator":
                (self.tmp / f"attempt{gens}.txt").write_text("x")
            if role == "evaluator":
                if "retry-cap" in prompt:
                    v = cap_verdict
                elif "Mode 1" in prompt:
                    v = {"verdict": "OK"}
                elif pass_on and gens >= pass_on:
                    v = {"verdict": "PASS", "reason": "ok", "evidence": []}
                else:
                    v = {"verdict": "RETRY", "reason": f"defect {gens}",
                         "evidence": []}
                if v is not None:
                    loop.VERDICT.write_text(json.dumps(v))
            return "done"
        loop.claude = fake
        st = self.iterate_state()
        loop.phase_iterate(self.write_goal(), st)
        return calls, st

    def gens(self, calls):
        return [p for r, p in calls if r == "generator"]

    def test_the_cap_buys_one_adjudication_carrying_the_ledger(self):
        calls, st = self.drive({"verdict": "RETRY", "evidence": [],
                                "reason": "converging: fix the import"},
                               pass_on=4)
        caps = [p for r, p in calls if r == "evaluator" and "retry-cap" in p]
        self.assertEqual(len(caps), 1)
        for needle in ("attempt 1: RETRY -- defect 1",
                       "attempt 3: RETRY -- defect 3"):
            self.assertIn(needle, caps[0])
        self.assertEqual(len(self.gens(calls)), 5,
                         "4 attempts on ticket 1, then ticket 2 once")
        self.assertIn("fix the import", self.gens(calls)[3])
        self.assertIn("attempt 4", self.gens(calls)[3])
        self.assertEqual(st["phase"], "final_eval")
        self.assertTrue([r for r in self.ledger()
                         if r.get("cap_adjudicated")])

    def test_the_extension_is_granted_once(self):
        calls, _ = self.drive({"verdict": "RETRY", "reason": "again",
                               "evidence": []})
        self.assertEqual(len(self.gens(calls)), 4)
        ev = [e for e in self.events() if e["event"] == "escalate"]
        self.assertTrue(ev)
        self.assertIn("defect 4", ev[0]["detail"])

    def test_escalate_from_the_adjudicator_stops_the_loop(self):
        calls, _ = self.drive({"verdict": "ESCALATE", "evidence": [],
                               "reason": "the goal contract is wrong"})
        self.assertEqual(len(self.gens(calls)), 3)
        ev = [e for e in self.events() if e["event"] == "escalate"]
        self.assertIn("goal contract is wrong", ev[0]["detail"])

    def test_replan_from_the_adjudicator_is_gated_like_any_replan(self):
        calls, st = self.drive({"verdict": "REPLAN", "evidence": [],
                                "reason": "ticket 1 is under-specified"},
                               pass_on=4)
        self.assertEqual(st["replans"], 1)
        self.assertTrue([e for e in self.events() if e["event"] == "replan"])
        self.assertEqual(st["phase"], "final_eval")

    def test_a_junk_adjudication_fails_closed(self):
        calls, _ = self.drive(None)
        self.assertEqual(len(self.gens(calls)), 3)
        ev = [e for e in self.events() if e["event"] == "escalate"]
        self.assertIn("no usable verdict", ev[0]["detail"])




# ---------- 8.1.17: the 2026-09-18 agentRl retro -----------------------

class TestJournalNesting(DriverCase):
    """journal/from-agentrl-retro-20260918.md, problem 7c/7d: 22 files
    carried 53 `## Request` sections. The record's header sentence
    names `## Feedback`, and the split landed on it."""

    def state(self):
        return {"phase": "done", "iteration": 1,
                "started": "2026-07-31T10:22:18+00:00",
                "started_epoch": loop.time.time()}

    def test_a_rewrite_keeps_one_request_section(self):
        cfg = self.write_goal(type="build")
        for _ in range(3):
            p = loop.write_journal(cfg, self.state())
        text = p.read_text()
        self.assertEqual(text.count("## Request"), 1)
        self.assertEqual(text.count("## Feedback"), 1 + 1)   # heading + header sentence
        self.assertTrue(text.rstrip().endswith("- Notes:"))

    def test_the_innermost_block_of_a_nested_record_is_the_real_one(self):
        """A record the 8.1.16 driver already nested heals on rewrite:
        the LAST heading is the block the user actually filled."""
        cfg = self.write_goal(type="build")
        p = loop.write_journal(cfg, self.state())
        nested = p.read_text().replace(
            "## Feedback (filled by user)",
            "## Feedback` block survives a rewrite._\n\n## Request\nold\n\n"
            "## Feedback (filled by user)").replace(
            "- Rating: [good | ok | bad]", "- Rating: bad")
        p.write_text(nested)
        text = loop.write_journal(cfg, self.state()).read_text()
        self.assertEqual(text.count("## Request"), 1)
        self.assertIn("- Rating: bad", text)


class TestDriverDecidesStall(DriverCase):
    """journal/from-agentrl-retro-20260918.md, problem 1: five healthy
    trials killed on a Monitor `stall` verdict; the driver was patched
    three times in three days toward one rule -- the driver's clock
    decides, the Monitor only reports."""

    def setUp(self):
        super().setUp()
        # A clock that starts at the real time so mtimes are comparable.
        self.clock = FakeClock(start=self._real_time.time(), step=600.0)
        loop.time = self.clock
        self.cfg = self.write_goal(monitor={"interval_min": 1})

    def monitor(self, **verdict):
        loop.claude = lambda *a, **k: json.dumps(verdict)

    def stamp_log(self, age_seconds):
        """Popen wrapper that sets the trial log's mtime relative to the
        REAL clock. The fake clock drifts +600 s per poll, so a fresh
        file is stamped far in the future; an old one far in the past."""
        real_popen = loop.subprocess.Popen

        def popen(*a, **k):
            proc = real_popen(*a, **k)
            t = self._real_time.time() - age_seconds
            os.utime(k["stdout"].name, (t, t))
            return proc
        loop.subprocess = types.SimpleNamespace(
            run=loop.subprocess.run, Popen=popen,
            STDOUT=loop.subprocess.STDOUT)

    def test_a_stall_verdict_on_a_fresh_log_is_overruled(self):
        self.monitor(status="INTERVENE", signature="stall",
                     evidence="no new output for 2 intervals")
        body = "**Trial:** sleep 3\n**Monitor Profile:** stall_min: 120"
        st = {"iteration": 1}
        # v8.1.18: 10**9, not 10**7. The fake clock advances 600 s per
        # poll while the real `sleep 3` runs, so on a fast machine the
        # loop spun past a +10**7 s stamp in ~16,700 polls and the
        # driver raised a real stall -- the test depended on CPU speed.
        self.stamp_log(-10 ** 9)                    # written "later"
        self.assertTrue(loop.run_trial("T", body, st, self.cfg))
        kinds = [e["event"] for e in self.events()]
        self.assertIn("monitor_overruled", kinds)
        self.assertNotIn("trial_killed", kinds)

    def test_without_stall_min_the_driver_never_kills_on_stall(self):
        self.monitor(status="INTERVENE", signature="silent_stall",
                     evidence="x")
        body = "**Trial:** sleep 3\n**Monitor Profile:** cuda_oom only"
        self.assertTrue(loop.run_trial("T", body, {"iteration": 1},
                                       self.cfg))
        over = [e for e in self.events() if e["event"] == "monitor_overruled"]
        self.assertTrue(over and "not declared" in over[0]["detail"])

    def test_the_driver_raises_a_stall_the_monitor_missed(self):
        """The trial log stopped 3 h ago, stall_min is 30, the Monitor
        says HEALTHY: the driver kills, and names its own clock."""
        self.monitor(status="HEALTHY")
        body = "**Trial:** sleep 3\n**Monitor Profile:** stall_min: 30"
        st = {"iteration": 2}
        self.stamp_log(3 * 3600)
        self.assertFalse(loop.run_trial("T", body, st, self.cfg))
        killed = [e for e in self.events() if e["event"] == "trial_killed"]
        self.assertTrue(killed and "stall" in killed[0]["detail"])

    def test_declared_writes_paths_count_as_progress(self):
        """A checkpoint written a minute ago is progress even when the
        log itself went quiet (v8d: the log was quiet while the store
        was being written)."""
        self.monitor(status="HEALTHY")
        store = self.tmp / "store" / "ckpt"
        store.mkdir(parents=True)
        ckpt = store / "step-12.pt"
        ckpt.write_text("x")
        t = self._real_time.time() + 10 ** 9        # written "later"
        os.utime(ckpt, (t, t))
        body = ("**Trial:** sleep 3\n**Monitor Profile:**\n"
                "- stall_min: 30\n- writes: store/\n- noise: none")
        self.stamp_log(3 * 3600)                    # the log went quiet
        self.assertTrue(loop.run_trial("T", body, {"iteration": 3},
                                       self.cfg))

    def test_stall_profile_parses_both_keys(self):
        self.assertEqual(loop.stall_profile(
            "poll 10 min; stall_min: 45; writes: `results/`, logs/x.log"),
            (45, ["results/", "logs/x.log"]))
        self.assertEqual(loop.stall_profile("cuda_oom, nan_loss"),
                         (None, []))


class TestReviewRoundsPerLoop(DriverCase):
    """journal/from-agentrl-retro-20260918.md, problem 5: 16 review
    rounds across 6 replans, ~$150 before a measurement, and never one
    consolidated question to the user."""

    def setUp(self):
        super().setUp()
        (self.tmp / "Plan.md").write_text(PLAN)
        loop.claude = lambda *a, **k: ""    # never writes a verdict -> REVISE

    def test_the_cap_counts_across_replans(self):
        cfg = self.write_goal(type="build")
        st = {"review_rounds": loop.MAX_REVIEW_ROUNDS, "replans": 1,
              "review_log": ["replan #0 revision 1: REVISE"]}
        with self.assertRaises(SystemExit):
            loop.phase_contract_review(cfg, st)
        esc = [e for e in self.events() if e["event"] == "escalate"]
        self.assertTrue(esc and "max_review_rounds" in esc[0]["detail"],
                        esc)
        # v8.1.19: the escalation lists each paid round (B6)
        self.assertIn("replan #0 revision 1: REVISE", esc[0]["detail"])
        self.assertIn("first review, uncounted", esc[0]["detail"])
        self.assertEqual(st["review_rounds"], loop.MAX_REVIEW_ROUNDS,
                         "no re-review was bought at the cap")

    def test_each_paid_review_counts_and_a_reused_one_does_not(self):
        """v8.1.19 (B6): the FIRST review of a plan phase is the replan's
        own cost and is not counted; only re-reviews after a REVISE are.
        DF M0 hit the cap on six first reviews of environment-fact
        replans that disputed nothing in Goal.md."""
        cfg = self.write_goal(type="build")
        st = {}
        with self.assertRaises(SystemExit):     # MAX_REVISIONS exhausted
            loop.phase_contract_review(cfg, st)
        self.assertEqual(st["review_rounds"], loop.MAX_REVISIONS)
        self.assertEqual(len(st["review_log"]), loop.MAX_REVISIONS + 1)

    def test_a_first_review_at_the_cap_is_still_bought(self):
        """Eight environment-fact replans must each get their one review
        even when earlier REVISE rounds used up the cap."""
        cfg = self.write_goal(type="build")
        calls = []
        loop.claude = lambda _st, role, *a, **k: (calls.append(role) or "")
        st = {"review_rounds": loop.MAX_REVIEW_ROUNDS, "replans": 1}
        with self.assertRaises(SystemExit):
            loop.phase_contract_review(cfg, st)
        # (two dispatches: the live session wrote no verdict, B10)
        self.assertEqual(set(calls), {"evaluator"},
                         "the first review, and no Planner revision")

    def test_the_cap_is_a_budget(self):
        cfg = self.write_goal(type="build",
                              budgets={"max_usd": 10, "max_iterations": 8,
                                       "max_review_rounds": 20})
        st = {"review_rounds": 7}
        with self.assertRaises(SystemExit):
            loop.phase_contract_review(cfg, st)
        self.assertEqual(st["review_rounds"], 9)      # 2 re-reviews


class TestApiErrorIsADeadSession(DriverCase):
    """journal/from-agentrl-retro-20260918.md, problem 8: an API 529
    reached the driver as valid JSON with `is_error`, so the 8.1.13
    retry never fired and the replan was charged."""

    def stub(self, *stdouts):
        seen = []
        real = loop.subprocess

        def run(*a, **k):
            out = stdouts[len(seen)]
            seen.append(out)
            return types.SimpleNamespace(stdout=out, returncode=0,
                                         stderr="")
        loop.subprocess = types.SimpleNamespace(
            run=run, Popen=real.Popen, STDOUT=real.STDOUT)
        self.addCleanup(lambda: setattr(loop, "subprocess", real))
        return seen

    def test_is_error_json_is_redispatched_once_and_billed(self):
        self.write_goal()
        bad = json.dumps({"type": "result", "subtype": "error_during_execution",
                          "is_error": True, "total_cost_usd": 0.5,
                          "result": "API Error: 529 Overloaded"})
        ok = json.dumps({"total_cost_usd": 2.0, "result": "fine"})
        seen = self.stub(bad, ok)
        st = {"spent_usd": 0.0}
        self.assertEqual(loop.claude(st, "planner", "p"), "fine")
        self.assertEqual(len(seen), 2)
        self.assertEqual(st["spent_usd"], 2.5)
        self.assertFalse(st["session_died"])
        died = [e for e in self.events() if e["event"] == "session_died"]
        self.assertEqual(len(died), 1)
        self.assertIn("529", died[0]["detail"])


class TestGateReminder(DriverCase):
    """journal/from-agentrl-retro-20260918.md, problem 8: a plan gate
    outlasted a 24.6 h rental with one push at open."""

    def test_a_long_wait_is_re_announced(self):
        clock = FakeClock(step=3600.0)          # one hour per sleep()
        loop.time = clock
        self.write_goal()
        flag = loop.APPROVALS / "plan.approved"
        real_exists = Path.exists
        # the flag appears after 10 sleeps
        calls = [0]

        def exists(p):
            if p == flag:
                calls[0] += 1
                if calls[0] > 10 and not real_exists(p):
                    p.write_text("")
                return calls[0] > 10
            return real_exists(p)
        loop.Path.exists = exists
        self.addCleanup(setattr, loop.Path, "exists", real_exists)
        loop.wait_approval({}, "plan", "approve the plan")
        waits = [e for e in self.events() if e["event"] == "approval_waiting"]
        self.assertEqual(len(waits), 2)          # at 4h and 8h
        self.assertIn("4.0h", waits[0]["detail"])


class TestEffortAndRoleClocks(DriverCase):
    """2026-09-18 user request: effort per role, passed as --effort;
    each role's sessions, minutes and spend visible in status and the
    journal; every timestamp in Taipei time."""

    def stub(self, stdout):
        seen = []
        real = loop.subprocess

        def run(cmd, **k):
            seen.append(cmd)
            return types.SimpleNamespace(stdout=stdout, returncode=0,
                                         stderr="")
        loop.subprocess = types.SimpleNamespace(
            run=run, Popen=real.Popen, STDOUT=real.STDOUT)
        self.addCleanup(lambda: setattr(loop, "subprocess", real))
        return seen

    def test_effort_is_validated_per_role(self):
        with open(os.devnull, "w") as null:
            real, sys.stderr = sys.stderr, null
            try:
                with self.assertRaises(SystemExit):
                    loop.validate_goal(self.write_goal(
                        effort={"planner": "ultra"}))
                with self.assertRaises(SystemExit):
                    loop.validate_goal(self.write_goal(
                        effort={"driver": "high"}))
            finally:
                sys.stderr = real
        loop.validate_goal(self.write_goal(effort={"planner": "max"}))
        loop.validate_goal(self.write_goal())       # absent = defaults

    def test_effort_reaches_the_cli_and_the_session_event(self):
        self.write_goal(effort={"generator": "xhigh"})
        seen = self.stub(json.dumps({"total_cost_usd": 1.0, "result": "r"}))
        loop.claude({}, "generator", "p")
        cmd = seen[0]
        self.assertEqual(cmd[cmd.index("--effort") + 1], "xhigh")
        loop.claude({}, "planner", "p")
        self.assertEqual(seen[1][seen[1].index("--effort") + 1], "high")
        started = [e for e in self.events() if e["event"] == "session"]
        self.assertIn("effort xhigh", started[0]["detail"])

    def test_each_session_is_timed_and_totalled_per_role(self):
        clock = FakeClock(step=0.0)
        loop.time = clock
        self.write_goal()
        real = loop.subprocess

        def run(cmd, **k):
            clock.t += 20 * 60                      # a 20-minute session
            return types.SimpleNamespace(
                stdout=json.dumps({"total_cost_usd": 3.0, "result": "r"}),
                returncode=0, stderr="")
        loop.subprocess = types.SimpleNamespace(
            run=run, Popen=real.Popen, STDOUT=real.STDOUT)
        self.addCleanup(lambda: setattr(loop, "subprocess", real))
        st = {}
        loop.claude(st, "planner", "p")
        loop.claude(st, "planner", "p")
        self.assertEqual(st["roles"]["planner"],
                         {"sessions": 2, "minutes": 40.0, "usd": 6.0})
        self.assertNotIn("session_running", st)
        done = [e for e in self.events() if e["event"] == "session_done"]
        self.assertEqual(len(done), 2)
        self.assertEqual(done[0]["minutes"], 20.0)
        table = "\n".join(loop.role_table(self.write_goal(), st))
        self.assertRegex(table, r"planner\s+claude-opus-5-5\s+high\s+2\s+40m\s+\$6\.00")

    def test_status_shows_the_running_role_and_its_elapsed_time(self):
        clock = FakeClock(step=0.0)
        loop.time = clock
        cfg = self.write_goal()
        st = {"phase": "plan", "session_running": {
            "role": "planner", "started_epoch": clock.t - 20 * 60}}
        table = "\n".join(loop.role_table(cfg, st))
        self.assertIn("<- running 20m", table)
        loop.save(loop.STATE, st)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            loop.phase_status(cfg)
        self.assertIn("roles", out.getvalue())
        self.assertIn("<- running 20m", out.getvalue())

    def test_the_journal_carries_the_role_table(self):
        cfg = self.write_goal(type="build")
        st = {"phase": "done", "iteration": 1,
              "started": "2026-07-31T10:22:18+08:00",
              "started_epoch": loop.time.time(),
              "roles": {"evaluator": {"sessions": 3, "minutes": 75.5,
                                      "usd": 2.5}}}
        text = loop.write_journal(cfg, st).read_text()
        self.assertRegex(text, r"evaluator\s+claude-opus-5-5\s+high\s+3\s+1h15m\s+\$2\.50")

    def test_timestamps_are_taipei_time(self):
        self.assertTrue(loop.now().endswith("+08:00"), loop.now())
        loop.event("x")
        self.assertTrue(self.events()[-1]["ts"].endswith("+08:00"))
        hook = load_hook()
        self.assertEqual(str(hook.TZ), "Asia/Taipei")

# ---------- v8.1.20: a ticket may defer its own audit (R3) ---------------

class TestAuditDeferredField(DriverCase):
    """STAGES: 19 per-ticket audits of no-code Trial tickets, all PASS,
    nothing found; Evaluator = 40 % of the programme."""

    PLAN_DEFERRED = PLAN.replace(
        "**Boundary:** src/\n",
        "**Boundary:** src/\n**Audit:** deferred\n", 1)

    def drive(self, plan_text, cadence="per-iteration"):
        cfg = self.write_goal(evaluation_cadence=cadence)
        (self.tmp / "Plan.md").write_text(plan_text)
        self.results({"metrics": {"acc": 0.5}})
        loop.git_commit = lambda msg: "abc1234"
        calls = []

        def fake(_st, role, prompt, *a, **k):
            calls.append((role, prompt))
            if role == "evaluator":
                loop.VERDICT.write_text(json.dumps(
                    {"verdict": "PASS", "reason": "ok"}))
            return "STATUS: pass"
        loop.claude = fake
        st = {"phase": "iterate", "iteration": 0, "replans": 0,
              "spent_usd": 0.0, "gpu_hours": 0.0,
              "criteria_green": ["acc@results/out.json"],   # no first green
              "started_epoch": loop.time.time()}
        loop.phase_iterate(cfg, st)
        return calls

    def test_a_deferred_ticket_buys_no_audit_under_per_iteration(self):
        calls = self.drive(self.PLAN_DEFERRED)
        audits = [p for r, p in calls if r == "evaluator"
                  and "Mode 2" in p and "FINAL" not in p]
        # Step 1 deferred, Step 2 (last ticket) audited as always
        self.assertEqual(len(audits), 1)
        self.assertIn("Phase 1, Step 2", audits[0])
        rows = self.ledger()
        self.assertIn("Audit: deferred", rows[0]["reason"])

    def test_without_the_field_per_iteration_audits_every_ticket(self):
        calls = self.drive(PLAN)
        audits = [p for r, p in calls if r == "evaluator"
                  and "Mode 2" in p and "FINAL" not in p]
        self.assertEqual(len(audits), 2)

    def test_a_first_green_is_audited_even_when_deferred(self):
        cfg = self.write_goal()
        (self.tmp / "Plan.md").write_text(self.PLAN_DEFERRED)
        self.results({"metrics": {"acc": 0.5}})
        loop.git_commit = lambda msg: "abc1234"
        calls = []

        def fake(_st, role, prompt, *a, **k):
            calls.append((role, prompt))
            if role == "evaluator":
                loop.VERDICT.write_text(json.dumps(
                    {"verdict": "PASS", "reason": "ok"}))
            return "STATUS: pass"
        loop.claude = fake
        st = self.iterate_state()
        loop.phase_iterate(cfg, st)
        first = [p for r, p in calls if r == "evaluator" and "Mode 2" in p]
        self.assertTrue(first and "FIRST time" in first[0])


# ---------- v8.1.20: the tree says which framework it really is ----------

class TestTemplateDrift(DriverCase):
    """Four deployments hot-patched the same three defects and none of
    the eleven patches came home."""

    def setUp(self):
        super().setUp()
        (self.tmp / "CLAUDE.md").write_text(
            "# Concept-Driven Development (CDD) 8.1.20\n")
        (self.tmp / "skills").mkdir(exist_ok=True)
        (self.tmp / "skills" / "x.md").write_text("skill\n")
        (self.tmp / ".claude" / "settings.local.json").write_text("{}")

    def test_no_manifest_is_reported_as_such(self):
        self.assertIsNone(loop.template_drift())
        self.assertEqual(loop.framework_label(), "8.1.20 (no manifest)")

    def test_a_pristine_tree_reports_the_release(self):
        loop.write_manifest()
        self.assertEqual(loop.framework_label(), "8.1.20")
        self.assertEqual(loop.template_drift(), ("8.1.20", []))
        files = json.loads(loop.MANIFEST.read_text())["files"]
        self.assertIn("CLAUDE.md", files)
        self.assertIn("skills/x.md", files)
        self.assertNotIn(".claude/settings.json", files)
        self.assertNotIn(".claude/settings.local.json", files)
        self.assertNotIn(".claude/driver/manifest.json", files)

    def test_a_hot_patched_tree_names_the_file(self):
        loop.write_manifest()
        hook = self.tmp / ".claude" / "hooks" / "enforce_authority.py"
        hook.write_text(hook.read_text() + "# local fix\n")
        (self.tmp / "skills" / "x.md").unlink()           # missing too
        version, changed = loop.template_drift()
        self.assertEqual(changed, [".claude/hooks/enforce_authority.py",
                                   "skills/x.md"])
        self.assertEqual(loop.framework_label(),
                         "8.1.20+local(2: enforce_authority.py, x.md)")
        loop.machinery()
        drift = [e for e in self.events() if e["event"] == "template_drift"]
        self.assertEqual(len(drift), 1)
        self.assertIn("format-patch", drift[0]["detail"])

    def test_a_pristine_tree_emits_no_drift_event(self):
        loop.write_manifest()
        loop.machinery()
        self.assertNotIn("template_drift",
                         [e["event"] for e in self.events()])

    def test_the_journal_and_status_carry_the_label(self):
        loop.write_manifest()
        (self.tmp / "Plan.md").write_text(PLAN)
        cfg = self.write_goal()
        text = loop.write_journal(cfg, {
            "phase": "done", "iteration": 1, "replans": 0,
            "spent_usd": 0.0, "started": "2026-10-15T10:00:00+08:00",
            "started_epoch": loop.time.time()}).read_text()
        self.assertIn("- framework: 8.1.20", text)


# ---------- v8.1.19: close keeps the machine records; traces go home (C5) -

class TestCloseKeepsTheRecords(DriverCase):
    def test_ledger_and_events_are_kept_beside_the_journal(self):
        loop.sh("git init -q && git -c user.name=t -c user.email=t@t "
                "commit -q --allow-empty -m init")
        cfg = self.write_goal()
        (self.tmp / "Plan.md").write_text(PLAN)
        loop.LEDGER.write_text(json.dumps({"iteration": 1, "verdict": "PASS",
                                           "ticket": "Phase 1, Step 1",
                                           "attempt": 1, "reason": "ok"})
                               + "\n")
        loop.event("goal_reached", detail="all green")
        st = {"phase": "done", "iteration": 1, "replans": 0,
              "spent_usd": 1.0, "started": "2026-10-15T10:00:00+08:00",
              "started_epoch": loop.time.time()}
        rec = loop.write_journal(cfg, st)
        rec.write_text(rec.read_text().replace(
            "- Rating: [good | ok | bad]", "- Rating: good"))
        loop.git_commit = lambda msg: "abc1234"
        with open(os.devnull, "w") as null:
            real, sys.stdout = sys.stdout, null
            try:
                loop.phase_close(cfg, st, force=False)
            finally:
                sys.stdout = real
        raw = self.tmp / "journal" / "raw" / rec.stem
        self.assertTrue((raw / "ledger.jsonl").exists())
        self.assertTrue((raw / "events.jsonl").exists())
        self.assertIn('"goal_reached"', (raw / "events.jsonl").read_text())
        self.assertFalse(loop.LEDGER.exists(), "the ephemeral is still gone")
        self.assertFalse(loop.EVENTS.exists())


class TestTranscriptsGoToThePrimaryTree(unittest.TestCase):
    """EBFT M0-M3b, JEV 1-7, DF M0/M1a: every Tier-2 trace went with its
    worktree."""

    def test_a_worktree_session_archives_into_the_primary_journal(self):
        base = Path(tempfile.mkdtemp(prefix="cdd-tr-")).resolve()
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        primary, wt = base / "primary", base / "wt"
        primary.mkdir()
        run = lambda c, cwd: subprocess.run(c, shell=True, cwd=cwd, text=True,
                                            capture_output=True)
        run("git init -q && git -c user.name=t -c user.email=t@t commit -q "
            "--allow-empty -m init && git worktree add -q ../wt -b loop",
            primary)
        self.assertTrue(wt.is_dir(), "worktree fixture")
        transcript = base / "s.jsonl"
        transcript.write_text('{"type":"x"}\n')
        payload = {"cwd": str(wt), "transcript_path": str(transcript),
                   "session_id": "abc"}
        r = subprocess.run([sys.executable,
                            str(HERE.parent / "hooks" / "archive_transcript.py")],
                           input=json.dumps(payload), text=True,
                           capture_output=True)
        self.assertEqual(r.returncode, 0)
        got = list((primary / "journal" / "traces").glob("*-abc.jsonl"))
        self.assertEqual(len(got), 1, r.stderr)
        self.assertFalse((wt / "journal" / "traces").exists())

    def test_outside_git_it_falls_back_to_cwd(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "archive_transcript",
            HERE.parent / "hooks" / "archive_transcript.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        d = Path(tempfile.mkdtemp(prefix="cdd-nogit-")).resolve()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        self.assertEqual(mod.primary_tree(d), d)


# ---------- v8.1.19: the Outcome block counts what retros counted (C3, C4)

class TestOutcomeBlockCounts(DriverCase):
    def setUp(self):
        super().setUp()
        (self.tmp / "Plan.md").write_text(PLAN)

    def state(self):
        return {"phase": "done", "iteration": 3, "replans": 1,
                "spent_usd": 1.0, "gpu_hours": 2.5,
                "review_rounds": 2,
                "review_log": ["replan #0 revision 0: REVISE -- first "
                               "review, uncounted",
                               "replan #0 revision 1: REVISE",
                               "replan #0 revision 2: OK"],
                "started": "2026-10-15T10:00:00+08:00",
                "started_epoch": loop.time.time()}

    def test_c3_the_template_has_a_filled_by_line_and_close_still_refuses(self):
        self.assertIn("- Filled by: [user | operator under delegation]",
                      loop.FEEDBACK_BLOCK)
        # the close guard keys on the Rating line, which is unchanged
        self.assertEqual(loop.FEEDBACK_BLOCK.splitlines()[1],
                         "- Rating: [good | ok | bad]")

    def test_c4_review_rounds_gpu_hours_monitor_and_trials(self):
        cfg = self.write_goal(budgets={"max_iterations": 8, "max_usd": 10,
                                       "max_gpu_hours": 20})
        for s in ("HEALTHY", "HEALTHY", "INTERVENE", "HEALTHY"):
            loop.event("monitor", detail=s)
        loop.event("monitor_overruled", detail="stall verdict while ...")
        loop.event("trial_done", detail="Phase 1, Step 1 attempt 1: 83 min "
                                        "wall, exit 0, Deadline 20 min",
                   minutes=83.0, exit=0)
        text = loop.write_journal(cfg, self.state()).read_text()
        self.assertIn("- gpu-hours: 2.50 / 20", text)
        self.assertIn("- contract review: 3 round(s) bought, 2 of them "
                      "re-reviews after a REVISE (cap 6)", text)
        self.assertIn("- monitor: 4 poll(s) · 1 non-HEALTHY · 1 overruled "
                      "by the driver", text)
        self.assertIn("## Trials", text)
        self.assertIn("83 min wall, exit 0, Deadline 20 min", text)
        self.assertIn("- Filled by:", text)

    def test_c4_run_trial_records_its_wall_time(self):
        clock = FakeClock(start=self._real_time.time(), step=600.0)
        loop.time = clock
        loop.claude = lambda *a, **k: json.dumps({"status": "HEALTHY"})
        cfg = self.write_goal(monitor={"interval_min": 1})
        body = "**Trial:** sleep 1\n**Monitor Profile:** cuda_oom\n"
        loop.run_trial("Phase 1, Step 1", body, {"iteration": 2}, cfg, 1)
        done = [e for e in self.events() if e["event"] == "trial_done"]
        self.assertEqual(len(done), 1)
        self.assertIn("Phase 1, Step 1 attempt 1:", done[0]["detail"])
        self.assertIn("exit 0", done[0]["detail"])
        self.assertGreater(done[0]["minutes"], 0)


# ---------- v8.1.19: the driver reads Deadline -- to size and to warn -----

class TestDeadlineIsReadNotEnforced(DriverCase):
    """JEVI: a 4x-under Deadline had no effect because nothing read it;
    EBFT M3 polled a 25 h trial 137 times for no decision."""

    BODY = ("**Trial:** sleep 3\n**Monitor Profile:** cuda_oom\n"
            "**Deadline:** 24 × 5.0 min × 1.5 = 180 min "
            "(source: logs/trial-3-1.log)\n")

    def test_the_last_minutes_figure_is_the_deadline(self):
        self.assertEqual(loop.deadline_minutes(self.BODY), 180.0)
        self.assertIsNone(loop.deadline_minutes("**Trial:** x\n"))

    def test_the_poll_interval_grows_with_the_deadline(self):
        cfg = {"monitor": {"interval_min": 10}}
        self.assertEqual(loop.monitor_interval_min(cfg, None), 10)
        self.assertEqual(loop.monitor_interval_min(cfg, 180), 10)
        self.assertEqual(loop.monitor_interval_min(cfg, 1500), 50)
        self.assertEqual(loop.monitor_interval_min({}, 1500), 50)

    def test_overrunning_the_deadline_warns_once_and_never_kills(self):
        clock = FakeClock(start=self._real_time.time(), step=600.0)
        loop.time = clock
        prompts = []

        def monitor(st, role, prompt, *a, **k):
            prompts.append(prompt)
            return json.dumps({"status": "HEALTHY"})
        loop.claude = monitor
        cfg = self.write_goal(monitor={"interval_min": 1})
        body = ("**Trial:** sleep 2\n**Monitor Profile:** cuda_oom\n"
                "**Deadline:** 1 × 2 min × 1.5 = 3 min\n")
        self.assertTrue(loop.run_trial("T", body, {"iteration": 1}, cfg))
        warned = [e for e in self.events() if e["event"] == "deadline_exceeded"]
        self.assertEqual(len(warned), 1, "warn once, not every poll")
        self.assertIn("Not a kill", warned[0]["detail"])
        self.assertNotIn("trial_killed", [e["event"] for e in self.events()])
        self.assertTrue(any("Deadline (Planner's arithmetic): 3 min" in p
                            for p in prompts))

    def test_an_opus_monitor_is_warned_about_not_refused(self):
        cfg = self.write_goal(models={**loop.DEFAULT_MODELS,
                                      "monitor": "claude-opus-5-5"})
        buf = io.StringIO()
        real, sys.stderr = sys.stderr, buf
        try:
            loop.validate_goal(cfg)                  # no SystemExit
        finally:
            sys.stderr = real
        self.assertIn("models.monitor is claude-opus-5-5", buf.getvalue())


# ---------- v8.1.19: a live Evaluator that wrote no verdict (B10) ---------

class TestMissingVerdictIsRedispatchedOnce(DriverCase):
    """STAGES s8 21:15: an Evaluator exited 0 without verdict.json and
    the absence was read straight as ESCALATE."""

    def test_a_live_session_without_a_verdict_is_asked_again(self):
        self.write_goal()
        calls = []

        def fake(st, role, prompt, *a, **k):
            calls.append(prompt)
            st["session_died"] = False
            if len(calls) == 2:                      # second time: writes
                loop.VERDICT.write_text(json.dumps(
                    {"verdict": "PASS", "reason": "ok"}))
            return "forgot"
        loop.claude = fake
        loop.evaluator_verdict({}, "Mode 2 -- evaluation")
        self.assertEqual(len(calls), 2)
        self.assertIn("WITHOUT writing verdict.json", calls[1])
        self.assertTrue(loop.VERDICT.exists())
        self.assertIn("verdict_missing", [e["event"] for e in self.events()])

    def test_a_dead_session_is_not_asked_a_third_time(self):
        self.write_goal()
        calls = []

        def dead(st, role, prompt, *a, **k):
            calls.append(role)
            st["session_died"] = True
            return ""
        loop.claude = dead
        loop.evaluator_verdict({}, "Mode 2 -- evaluation")
        self.assertEqual(calls, ["evaluator"])
        self.assertNotIn("verdict_missing",
                         [e["event"] for e in self.events()])

    def test_a_verdict_on_the_first_try_is_not_re_asked(self):
        self.write_goal()
        calls = []

        def fake(st, role, prompt, *a, **k):
            calls.append(role)
            loop.VERDICT.write_text(json.dumps({"verdict": "OK"}))
            return "ok"
        loop.claude = fake
        loop.evaluator_verdict({}, "Mode 1 -- contract review")
        self.assertEqual(calls, ["evaluator"])


# ---------- v8.1.19: a trial that fails twice identically is adjudicated --

class TestTrialFailingTwiceIsAdjudicated(DriverCase):
    """JEV loop 3: a vLLM OOM was relaunched verbatim (Protocol #5 is for
    nondeterministic deaths) and bought nothing."""

    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, loop, "run_trial", loop.run_trial)
        self.cfg = self.write_goal(type="experiment")
        (self.tmp / "Plan.md").write_text(
            PLAN.replace("**Boundary:** src/\n",
                         "**Boundary:** src/\n**Trial:** false\n", 1))
        loop.git_commit = lambda msg: "abc1234"
        loop.run_trial = lambda *a, **k: False       # every launch dies

    def drive(self, adjudication):
        prompts = []

        def fake(st, role, prompt, *a, **k):
            prompts.append((role, prompt))
            if role == "evaluator" and "trial-failure adjudication" in prompt:
                loop.VERDICT.write_text(json.dumps(adjudication))
            elif role == "evaluator" and "contract review" in prompt:
                loop.VERDICT.write_text(json.dumps({"verdict": "OK"}))
            return "STATUS: pass"
        loop.claude = fake
        st = self.iterate_state()
        loop.phase_iterate(self.cfg, st)
        return st, prompts

    def test_the_second_identical_death_goes_to_adjudication(self):
        st, prompts = self.drive({"verdict": "ESCALATE",
                                  "reason": "the Trial line OOMs by design"})
        adj = [p for r, p in prompts if "trial-failure adjudication" in p]
        self.assertEqual(len(adj), 1)
        self.assertIn("2 consecutive attempts", adj[0])
        verdicts = [r["verdict"] for r in self.ledger()]
        self.assertEqual(verdicts, ["RETRY", "ESCALATE"],
                         "one relaunch, then the adjudicator decides")
        ev = [e for e in self.events() if e["event"] == "stop_adjudicated"]
        self.assertTrue(ev and "(trial)" in ev[0]["detail"])

    def test_an_adjudicated_replan_takes_the_replan_route(self):
        loop.wait_approval = lambda st, name, detail: None
        loop.flush_pregate = lambda what: ""
        launches = []                       # two deaths, then it runs
        loop.run_trial = lambda *a, **k: (launches.append(1) or
                                          len(launches) > 2)
        st, prompts = self.drive({"verdict": "REPLAN",
                                  "reason": "the config needs a smaller "
                                            "batch; a fresh plan fixes it"})
        kinds = [e["event"] for e in self.events()]
        self.assertIn("replan", kinds)
        self.assertEqual(st["replans"], 1)
        self.assertEqual([r["verdict"] for r in self.ledger()][:2],
                         ["RETRY", "REPLAN"])


# ---------- v8.1.19: `pause-after` -- stop at a ticket boundary (B9) ------

class TestPauseAfter(DriverCase):
    """STAGES s6, s9, s18: three loops needed "stop after ticket N"; the
    workaround once deleted the checkpoints the user wanted."""

    def run_cmd(self, *args):
        argv, sys.argv = sys.argv, ["loop.py", *args]
        self.addCleanup(setattr, sys, "argv", argv)
        class Buf(io.StringIO):          # main() reconfigures stdout
            def reconfigure(self, **k):
                pass
        buf = Buf()
        real, sys.stdout = sys.stdout, buf
        try:
            loop.main()
        finally:
            sys.stdout = real
        return buf.getvalue()

    def test_the_command_records_the_flag_and_validates_the_ticket(self):
        (self.tmp / "Plan.md").write_text(PLAN)
        loop.STATE.write_text(json.dumps({"phase": "iterate"}))
        out = self.run_cmd("pause-after", "Phase 1, Step 1")
        self.assertIn("will pause after Phase 1, Step 1", out)
        # 8.1.21: a flag file, not a state key (see pause_requested())
        self.assertEqual(loop.pause_requested(), "Phase 1, Step 1")
        self.assertNotIn("pause_after", json.loads(loop.STATE.read_text()))
        with open(os.devnull, "w") as null:
            real, sys.stderr = sys.stderr, null
            try:
                with self.assertRaises(SystemExit):
                    self.run_cmd("pause-after", "Phase 9, Step 9")
            finally:
                sys.stderr = real

    def test_the_driver_pauses_after_that_ticket_passes(self):
        cfg = self.write_goal(evaluation_cadence="final-pass")
        (self.tmp / "Plan.md").write_text(PLAN)
        self.results({"metrics": {"acc": 0.5}})
        loop.git_commit = lambda msg: "abc1234"
        calls = []

        def fake(_st, role, prompt, *a, **k):
            calls.append(role)
            if role == "evaluator":
                loop.VERDICT.write_text(json.dumps(
                    {"verdict": "PASS", "reason": "ok"}))
            return "STATUS: pass"
        loop.claude = fake
        st = {"phase": "iterate", "iteration": 0, "replans": 0,
              "spent_usd": 0.0, "gpu_hours": 0.0, "criteria_green": [],
              "started_epoch": loop.time.time(),
              "pause_after": "Phase 1, Step 1"}
        loop.phase_iterate(cfg, st)
        kinds = [e["event"] for e in self.events()]
        self.assertIn("paused", kinds)
        self.assertEqual(st["phase"], "iterate", "resumable")
        self.assertNotIn("pause_after", st, "consumed on firing")
        self.assertEqual(calls.count("generator"), 1,
                         "Step 2 was not dispatched")
        todo = [i for i, *_r, d in loop.tickets(
            (self.tmp / "Plan.md").read_text()) if not d]
        self.assertEqual(todo, ["Phase 1, Step 2"])

    def test_without_the_flag_the_loop_runs_on(self):
        cfg = self.write_goal(evaluation_cadence="final-pass")
        (self.tmp / "Plan.md").write_text(PLAN)
        self.results({"metrics": {"acc": 0.5}})
        loop.git_commit = lambda msg: "abc1234"
        calls = []

        def fake(_st, role, prompt, *a, **k):
            calls.append(role)
            if role == "evaluator":
                loop.VERDICT.write_text(json.dumps(
                    {"verdict": "PASS", "reason": "ok"}))
            return "STATUS: pass"
        loop.claude = fake
        st = self.iterate_state()
        loop.phase_iterate(cfg, st)
        self.assertEqual(calls.count("generator"), 2)
        self.assertNotIn("paused", [e["event"] for e in self.events()])


# ---------- v8.1.19: first-start preflight checks (B8) --------------------

class TestFirstStartPreflight(DriverCase):
    """STAGES: ten loops whose "<dir> absent" preflight went false by
    design after ticket 1, so ~16 restarts each needed a hand-edit."""

    CHECKS = [{"name": "env ok", "run": "true"},
              {"name": "results absent", "run": "false",
               "when": "first-start"}]

    def test_a_first_start_runs_every_check(self):
        cfg = self.write_goal(preflight=self.CHECKS)
        with open(os.devnull, "w") as null:
            real, sys.stderr = sys.stderr, null
            try:
                with self.assertRaises(SystemExit):
                    loop.preflight(cfg, resume=False)
            finally:
                sys.stderr = real

    def test_a_resume_skips_first_start_checks_and_says_so(self):
        cfg = self.write_goal(preflight=self.CHECKS)
        loop.preflight(cfg, resume=True)             # does not die
        ev = [e for e in self.events() if e["event"] == "preflight_skipped"]
        self.assertEqual(len(ev), 1)
        self.assertIn("results absent", ev[0]["detail"])
        ran = [e["detail"] for e in self.events()
               if e["event"] == "preflight"]
        self.assertEqual(ran, ["ok   env ok"])

    def test_an_always_check_still_fails_a_resume(self):
        cfg = self.write_goal(preflight=[
            {"name": "endpoint", "run": "false"}])
        with open(os.devnull, "w") as null:
            real, sys.stderr = sys.stderr, null
            try:
                with self.assertRaises(SystemExit):
                    loop.preflight(cfg, resume=True)
            finally:
                sys.stderr = real

    def test_when_is_validated(self):
        with open(os.devnull, "w") as null:
            real, sys.stderr = sys.stderr, null
            try:
                with self.assertRaises(SystemExit):
                    loop.validate_goal(self.write_goal(preflight=[
                        {"name": "x", "run": "true", "when": "sometimes"}]))
            finally:
                sys.stderr = real
        loop.validate_goal(self.write_goal(preflight=self.CHECKS))


# ---------- v8.1.19: criteria re-read when a gate clears (B7) -------------

class TestCriteriaReloadAtTheGate(DriverCase):
    """STAGES: seven gate-time goal.json amendments, six restarts to load
    them, one loop that did not restart and paid three retries."""

    def test_an_amendment_is_loaded_and_recorded(self):
        cfg = self.write_goal()
        self.write_goal(criteria=[
            {"metric": "acc", "op": ">", "value": 0.5,
             "source": "results/out.json"},
            {"metric": "n", "op": ">=", "value": 10,
             "source": "results/out.json"}])
        loop.reload_criteria(cfg)
        self.assertEqual(cfg["criteria"][0]["value"], 0.5)
        self.assertEqual(len(cfg["criteria"]), 2)
        ev = [e for e in self.events() if e["event"] == "criteria_amended"]
        self.assertEqual(len(ev), 1)
        self.assertIn("~ acc@results/out.json: > 0.0 -> > 0.5",
                      ev[0]["detail"])
        self.assertIn("+ n@results/out.json >= 10", ev[0]["detail"])

    def test_an_unchanged_file_is_silent(self):
        cfg = self.write_goal()
        loop.reload_criteria(cfg)
        self.assertEqual(self.events(), [])

    def test_a_malformed_amendment_is_refused_and_the_old_stand(self):
        cfg = self.write_goal()
        self.write_goal(criteria=[{"metric": "acc", "op": "~", "value": 1}])
        loop.reload_criteria(cfg)
        self.assertEqual(cfg["criteria"][0]["value"], 0.0)
        kinds = [e["event"] for e in self.events()]
        self.assertIn("criteria_amendment_refused", kinds)
        self.assertNotIn("criteria_amended", kinds)

    def test_budgets_reload_still_leaves_criteria_frozen(self):
        """Protocol #4 between gates: reload_budgets() must not become
        the back door."""
        cfg = self.write_goal()
        self.write_goal(criteria=[{"metric": "acc", "op": ">",
                                   "value": 0.9,
                                   "source": "results/out.json"}])
        loop.reload_budgets(cfg)
        self.assertEqual(cfg["criteria"][0]["value"], 0.0)


# ---------- v8.1.19: a connectivity death is a wait, not an attempt (B3) -

class TestNetworkWaitIsNotAnAttempt(DriverCase):
    """NVFP4 L2/L5 and DF M0: a 37-minute DNS outage = three burned
    attempts, a dead adjudicator and an escalation."""

    def setUp(self):
        super().setUp()
        self.clock = FakeClock(start=1_000_000.0, step=60.0)
        loop.time = self.clock
        self.addCleanup(setattr, loop, "network_up", loop.network_up)
        self.write_goal(budgets={"max_iterations": 8, "max_usd": 10,
                                 "max_network_wait_min": 3})

    def stub_runs(self, outcomes):
        """Each outcome: 'net' (connectivity error), 'junk' (unparseable),
        or 'ok'. Consumed in order; the last one repeats."""
        real = loop.subprocess
        seen = []

        def run(cmd, **k):
            o = outcomes[min(len(seen), len(outcomes) - 1)]
            seen.append(o)
            if o == "net":
                return types.SimpleNamespace(stdout=json.dumps({
                    "is_error": True, "subtype": "error_api",
                    "result": "API Error: getaddrinfo EAI_AGAIN "
                              "api.anthropic.com", "total_cost_usd": 0}),
                    returncode=0, stderr="")
            if o == "junk":
                return types.SimpleNamespace(stdout="not json",
                                             returncode=1, stderr="boom")
            return types.SimpleNamespace(stdout=json.dumps(
                {"total_cost_usd": 0.5, "result": "done"}),
                returncode=0, stderr="")
        loop.subprocess = types.SimpleNamespace(
            run=run, Popen=real.Popen, STDOUT=real.STDOUT)
        self.addCleanup(lambda: setattr(loop, "subprocess", real))
        return seen

    def test_an_outage_that_ends_is_waited_out_and_redispatched(self):
        seen = self.stub_runs(["net", "net", "ok"])
        probes = iter([False, False, True])
        loop.network_up = lambda: next(probes, True)
        st = {"run_epoch": self.clock.time(), "run_hours": 0.0}
        self.assertEqual(loop.claude(st, "generator", "p"), "done")
        self.assertFalse(st["session_died"])
        self.assertEqual(seen, ["net", "net", "ok"])
        kinds = [e["event"] for e in self.events()]
        self.assertIn("network_wait", kinds)
        self.assertIn("network_restored", kinds)
        self.assertNotIn("network_wait_exhausted", kinds)
        self.assertTrue(st.get("run_epoch"), "the clock restarted")

    def test_the_wait_does_not_meter_driver_runtime(self):
        self.stub_runs(["net", "net", "ok"])
        probes = iter([False, False, False, True])
        loop.network_up = lambda: next(probes, True)
        st = {"run_epoch": self.clock.time(), "run_hours": 0.0}
        loop.claude(st, "generator", "p")
        # 4 probe sleeps of 60 s happened; none of them is runtime
        self.assertLess(loop.wall_hours(st), 4 * 60 / 3600)

    def test_an_outage_that_outlasts_the_cap_is_a_dead_session(self):
        seen = self.stub_runs(["net"])
        loop.network_up = lambda: False
        st = {}
        loop.claude(st, "generator", "p")
        self.assertTrue(st["session_died"])
        self.assertIn("not restored within 3 min", st["session_died_why"])
        kinds = [e["event"] for e in self.events()]
        self.assertIn("network_wait_exhausted", kinds)
        self.assertEqual(seen.count("net"), 2, "no re-dispatch storm")

    def test_a_non_connectivity_death_does_not_wait(self):
        self.stub_runs(["junk"])
        loop.network_up = lambda: (_ for _ in ()).throw(
            AssertionError("probed the network for a non-network death"))
        st = {}
        loop.claude(st, "evaluator", "p")
        self.assertTrue(st["session_died"])
        self.assertNotIn("network_wait",
                         [e["event"] for e in self.events()])

    def test_a_dead_generator_is_not_an_attempt_in_the_iteration(self):
        cfg = self.write_goal()
        (self.tmp / "Plan.md").write_text(PLAN)
        loop.git_commit = lambda msg: "abc1234"

        def dead(st, role, prompt, *a, **k):
            st["session_died"] = True
            st["session_died_why"] = "connectivity not restored"
            return ""
        loop.claude = dead
        st = self.iterate_state()
        loop.phase_iterate(cfg, st)
        rows = self.ledger()
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].get("session_died"))
        self.assertEqual(rows[0]["attempt"], 0, "not an attempt")
        kinds = [e["event"] for e in self.events()]
        self.assertNotIn("output_gate", kinds)
        self.assertNotIn("retry", kinds)
        esc = [e for e in self.events() if e["event"] == "escalate"]
        self.assertTrue(esc and "infrastructure" in esc[0]["detail"])


# ---------- v8.1.18: the record keeps what a retro needs (C1, C2, C8) ----

class TestJournalKeepsWhatARetroNeeds(DriverCase):
    """journal/retro-20261015-cross-project.md, section 2C."""

    def setUp(self):
        super().setUp()
        (self.tmp / "Plan.md").write_text(PLAN)

    def state(self):
        return {"phase": "done", "iteration": 3, "replans": 1,
                "spent_usd": 1.0, "started": "2026-10-15T10:00:00+08:00",
                "started_epoch": loop.time.time()}

    def test_c1_a_long_gate_wait_is_in_the_record(self):
        cfg = self.write_goal()
        loop.event("approval_waiting", gate="plan",
                   detail="plan gate open 4.0h; approve when ready")
        text = loop.write_journal(cfg, self.state()).read_text()
        self.assertIn("**approval_waiting**", text)

    def test_c2_a_streak_of_dead_sessions_is_one_line(self):
        cfg = self.write_goal()
        for _ in range(5):
            loop.event("session_died", detail="generator: EAI_AGAIN")
        loop.event("escalate", detail="no usable verdict")
        loop.event("session_died", detail="evaluator: 529")
        text = loop.write_journal(cfg, self.state()).read_text()
        self.assertEqual(text.count("**session_died**"), 2)
        self.assertIn("×5 **session_died** — generator: EAI_AGAIN", text)
        self.assertIn("**escalate** — no usable verdict", text)
        # order is kept: the streak is flushed before the escalation
        self.assertLess(text.index("×5"), text.index("**escalate**"))

    def test_c2_a_replan_reason_is_not_cut_mid_sentence(self):
        cfg = self.write_goal()
        reason = "plan defect: " + "the Spec contradicts Goal.md " * 12
        loop.LEDGER.write_text(json.dumps(
            {"ts": "t", "iteration": 2, "ticket": "Phase 1, Step 1",
             "attempt": 1, "verdict": "REPLAN", "reason": reason,
             "evidence": [], "criteria": []}) + "\n")
        text = loop.write_journal(cfg, self.state()).read_text()
        self.assertGreater(len(reason), 120)
        self.assertIn(reason, text)

    def test_c8_hook_denials_event_quotes_the_denial(self):
        self.write_goal()
        log = self.tmp / "logs" / "denials.log"
        real = loop.subprocess

        def run(cmd, **k):
            with log.open("a") as fh:          # the hook, mid-session
                fh.write("2026-10-15T10:01:00+08:00\tgenerator\t"
                         "Core files are read-only to the Generator.\t"
                         "Bash: echo x > Plan.md\tnet=target "
                         "token=plan.md\tfull=-\n")
            return types.SimpleNamespace(
                stdout=json.dumps({"total_cost_usd": 0.1, "result": "r"}),
                returncode=0, stderr="")
        loop.subprocess = types.SimpleNamespace(
            run=run, Popen=real.Popen, STDOUT=real.STDOUT)
        self.addCleanup(lambda: setattr(loop, "subprocess", real))
        loop.claude({}, "generator", "p")
        den = [e for e in self.events() if e["event"] == "hook_denials"]
        self.assertEqual(len(den), 1)
        self.assertIn("1 authority denial", den[0]["detail"])
        self.assertIn("Core files are read-only", den[0]["detail"])
        self.assertIn("echo x > Plan.md", den[0]["detail"])
        self.assertIn("net=target token=plan.md", den[0]["detail"])


# ---------- v8.1.18: a user replan flushes the ticket's work first (B5) --

class TestUserReplanCommitsWip(DriverCase):
    """JEV loop 3: `loop.py replan` only wrote state, so the next start's
    flush_pregate() swept attempt-1 Generator files into the
    `plan(loop): replan #1 approved` commit."""

    def run_replan(self, dirty: bool, state: dict):
        loop.STATE.write_text(json.dumps(state))
        commits = []
        loop.git_commit = lambda msg: (commits.append(msg) or "beef123")
        loop.sh = lambda cmd, **k: types.SimpleNamespace(
            stdout=" M src/a.py\n" if dirty else "", stderr="",
            returncode=0)
        argv, sys.argv = sys.argv, ["loop.py", "replan", "wrong premise"]
        self.addCleanup(setattr, sys, "argv", argv)
        with open(os.devnull, "w") as null:
            real, sys.stdout = sys.stdout, null
            try:
                loop.main()
            finally:
                sys.stdout = real
        return commits

    def test_a_dirty_tree_is_committed_as_wip_before_the_queue(self):
        commits = self.run_replan(True, {
            "phase": "iterate", "iteration": 3, "replans": 0,
            "current_ticket": "Phase 1, Step 2"})
        self.assertEqual(len(commits), 1)
        self.assertTrue(commits[0].startswith(
            "wip(loop): Phase 1, Step 2 before user replan #1 -- wrong "
            "premise"), commits[0])
        st = json.loads(loop.STATE.read_text())
        self.assertEqual((st["replans"], st["phase"]), (1, "plan"))
        kinds = [e["event"] for e in self.events()]
        self.assertIn("wip_committed", kinds)
        self.assertIn("replan", kinds)

    def test_a_clean_tree_commits_nothing(self):
        commits = self.run_replan(False, {
            "phase": "iterate", "iteration": 3, "replans": 1,
            "current_ticket": "Phase 1, Step 2"})
        self.assertEqual(commits, [])
        self.assertNotIn("wip_committed",
                         [e["event"] for e in self.events()])
        self.assertEqual(json.loads(loop.STATE.read_text())["replans"], 2)


# ---------- v8.1.18: a cap raised mid-trial applies to that trial (B4) ---

class TestBudgetReloadInsideTrial(DriverCase):
    """JEV loop 5: `status` read 12.2 / 20 GPU-h while run_trial killed
    the third seed against the 12.0 cap captured at dispatch."""

    def test_a_raised_gpu_cap_is_read_while_the_trial_runs(self):
        self.clock = FakeClock(start=self._real_time.time(), step=600.0)
        loop.time = self.clock
        loop.claude = lambda *a, **k: json.dumps({"status": "HEALTHY"})
        # the FILE carries the raised cap ...
        cfg = self.write_goal(monitor={"interval_min": 1},
                              budgets={"max_iterations": 8, "max_usd": 10,
                                       "max_gpu_hours": 1_000_000})
        # ... the dispatch-time dict still carries the old, tiny one
        cfg["budgets"]["max_gpu_hours"] = 0.01
        body = "**Trial:** sleep 1\n**Monitor Profile:** cuda_oom"
        self.assertTrue(loop.run_trial("T", body, {"iteration": 1}, cfg))
        kinds = [e["event"] for e in self.events()]
        self.assertNotIn("escalate", kinds)
        self.assertEqual(cfg["budgets"]["max_gpu_hours"], 1_000_000)

    def test_without_a_raise_the_cap_still_trips_during_the_trial(self):
        self.clock = FakeClock(start=self._real_time.time(), step=600.0)
        loop.time = self.clock
        loop.claude = lambda *a, **k: json.dumps({"status": "HEALTHY"})
        cfg = self.write_goal(monitor={"interval_min": 1},
                              budgets={"max_iterations": 8, "max_usd": 10,
                                       "max_gpu_hours": 0.01})
        body = "**Trial:** sleep 1\n**Monitor Profile:** cuda_oom"
        self.assertFalse(loop.run_trial("T", body, {"iteration": 1}, cfg))
        esc = [e for e in self.events() if e["event"] == "escalate"]
        self.assertTrue(esc and "budget" in esc[0]["detail"])


# ---------- v8.1.18: the prompt travels on stdin (B2) --------------------

class TestPromptOnStdin(DriverCase):
    """A 128 KB+ replan prompt on argv hit E2BIG and crashed the driver
    after the replan counter was incremented, in three deployments."""

    def test_prompt_is_passed_as_input_not_as_an_argument(self):
        seen = []
        real = loop.subprocess

        def run(cmd, **k):
            seen.append((cmd, k))
            return types.SimpleNamespace(
                stdout=json.dumps({"total_cost_usd": 0.1, "result": "r"}),
                returncode=0, stderr="")
        loop.subprocess = types.SimpleNamespace(
            run=run, Popen=real.Popen, STDOUT=real.STDOUT)
        self.addCleanup(lambda: setattr(loop, "subprocess", real))
        self.write_goal()
        big = "ledger " * 40_000                      # ~280 KB
        loop.claude({}, "planner", big)
        cmd, kwargs = seen[0]
        self.assertEqual(kwargs.get("input"), big)
        self.assertNotIn(big, cmd)
        self.assertEqual(cmd[:2], ["claude", "-p"])
        self.assertTrue(all(len(a) < 128_000 for a in cmd),
                        "no argv element may approach the E2BIG limit")


# ---------- v8.1.18: five hook false positives from seven deployments ---

class TestHookFalsePositives20261015(HookCaller, unittest.TestCase):
    """journal/retro-20261015-cross-project.md section 2A. Each case is
    the real command a deployment was denied on, beside the real denial
    the fix must not loosen."""

    def test_a1_trailing_slash_boundary_covers_the_directory_itself(self):
        # EBFT M5b: `rm -rf runs/x` against Boundary `runs/x/` -> stop.
        self.assertEqual(self.call("generator", "Bash",
                                   {"command": "rm -rf runs/x"},
                                   boundary="runs/x/"), self.ALLOW)
        self.assertEqual(self.call("generator", "Bash",
                                   {"command": "rm -rf runs/xy"},
                                   boundary="runs/x/"), self.DENY)

    def test_a2a_merge_base_is_not_a_merge(self):
        # EBFT M3, NVFP4 L9, DF 10-10: killed the final audit each time.
        self.assertEqual(self.call("evaluator", "Bash", {
            "command": "git merge-base HEAD origin/master"}), self.ALLOW)
        self.assertEqual(self.call("evaluator", "Bash", {
            "command": "git merge-tree A B"}), self.ALLOW)
        self.assertEqual(self.call("evaluator", "Bash", {
            "command": "git merge feature"}), self.DENY)

    def test_a2b_git_writes_in_a_tmp_scratch_tree_are_scratch(self):
        # EBFT M5c, DF 10-10: the Evaluator's /tmp reconstruction and a
        # Planner probing a pinned revision, both denied driver-only.
        for cmd in ("cd /tmp/x && git init -q && git add . && "
                    "git commit -q -m snapshot",
                    "git -C /tmp/seta checkout abc123",
                    "D=/tmp/x; git -C $D add ."):
            self.assertEqual(self.call("evaluator", "Bash",
                                       {"command": cmd}), self.ALLOW, cmd)

    def test_a2b_push_and_unresolved_trees_stay_denied(self):
        for cmd in ("git -C /tmp/seta push",
                    "cd /tmp && git push",
                    "cd /tmp && cd - && git add .",      # cd not followed
                    'cd "/tmp/x" && git add .',          # quoted: data
                    'git -C "$D" add .',                 # unresolved $
                    "git commit -m x",
                    "git log --oneline\ngit add -A"):
            self.assertEqual(self.call("planner", "Bash",
                                       {"command": cmd}), self.DENY, cmd)

    def test_a3_shell_grouping_is_not_a_write_target(self):
        # DF 10-10 11:11: the ticket format's Run Command in a subshell.
        self.assertEqual(self.call("generator", "Bash", {
            "command": "( { python3 run.py; pytest -q; } 2>&1 | "
                       "tee logs/latest.log ) | tail -40"},
            boundary="src/"), self.ALLOW)
        self.assertEqual(self.call("generator", "Bash", {
            "command": "{ echo x > src/a.py; }"}, boundary="src/"),
            self.ALLOW)
        self.assertEqual(self.call("generator", "Bash", {
            "command": "( pytest 2>&1 | tee Plan.md )"}, boundary="src/"),
            self.DENY)
        self.assertEqual(self.call("generator", "Bash", {
            "command": "{ echo x > Architecture.md; }"}, boundary="src/"),
            self.DENY)

    def test_a4_a_multiline_sed_script_is_not_the_target(self):
        # JEV loop 6: GNU sed append, read as a write to `1a/`.
        cmd = "sed -i '1a\\\nimport os' src/x.py"
        self.assertEqual(self.call("generator", "Bash", {"command": cmd},
                                   boundary="src/"), self.ALLOW)
        self.assertEqual(self.call("generator", "Bash", {
            "command": "sed -i '1a\\\nimport os' Plan.md"},
            boundary="src/"), self.DENY)

    def test_a5_a_denial_names_its_net_and_keeps_the_whole_command(self):
        with tempfile.TemporaryDirectory(dir=os.path.expanduser("~")) as d:
            env = {**os.environ, "CDD_ROLE": "generator",
                   "CDD_BOUNDARY": "src/", "CLAUDE_PROJECT_DIR": d}
            long_cmd = "echo x > Architecture.md  # " + "y" * 400
            for cmd in (long_cmd, "git commit -m x"):
                subprocess.run([sys.executable, str(HOOK)], env=env,
                               text=True, capture_output=True,
                               input=json.dumps({"tool_name": "Bash",
                                                 "tool_input": {
                                                     "command": cmd}}))
            lines = (Path(d) / "logs" / "denials.log").read_text() \
                .splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn("net=target token=architecture.md", lines[0])
            self.assertIn("net=git token=commit", lines[1])
            self.assertIn("full=-", lines[1])          # short: inline
            full = lines[0].split("full=")[1].strip()
            self.assertNotEqual(full, "-")
            self.assertEqual((Path(d) / full).read_text(),
                             "Bash: " + long_cmd)
            # the driver counts records by their leading timestamp
            self.assertTrue(all(ln[:4].isdigit() for ln in lines))


# ---------- 8.1.21: the opd-pipe retro batch -----------------------------

class TestPauseAfterSurvivesTheDriversSaves(DriverCase):
    run_cmd = TestPauseAfter.run_cmd
    """opd-pipe e007-l2b: `pause-after` was issued while the driver sat
    at the plan gate; the driver's next save(STATE, st) overwrote the
    key and it ran through Phase 2, Step 2."""

    def test_a_running_drivers_save_does_not_erase_the_request(self):
        cfg = self.write_goal(evaluation_cadence="final-pass")
        (self.tmp / "Plan.md").write_text(PLAN)
        loop.STATE.write_text(json.dumps({"phase": "gate"}))
        self.run_cmd("pause-after", "Phase 1, Step 1")
        # the driver, holding its own copy, saves without the key
        st = self.iterate_state()
        loop.save(loop.STATE, st)
        self.results({"metrics": {"acc": 0.5}})
        loop.git_commit = lambda msg: "abc1234"
        calls = []

        def fake(_st, role, prompt, *a, **k):
            calls.append(role)
            if role == "evaluator":
                loop.VERDICT.write_text(json.dumps(
                    {"verdict": "PASS", "reason": "ok"}))
            return "STATUS: pass"
        loop.claude = fake
        loop.phase_iterate(cfg, st)
        self.assertIn("paused", [e["event"] for e in self.events()])
        self.assertEqual(calls.count("generator"), 1)
        self.assertEqual(loop.pause_requested(), "", "consumed on firing")

    def test_close_removes_a_stale_request(self):
        loop.APPROVALS.mkdir(exist_ok=True)
        loop.pause_flag().write_text("Phase 9, Step 9\n")
        loop.sh("git init -q .")
        loop.sh("git config user.name t")
        loop.sh("git config user.email t@t")
        cfg = self.write_goal(type="build")
        st = {"phase": "done", "iteration": 1,
              "started": "2026-07-31T10:22:18+00:00"}
        loop.save(loop.STATE, st)
        rec = loop.write_journal(cfg, st)
        rec.write_text(rec.read_text().replace(
            "- Rating: [good | ok | bad]", "- Rating: ok"))
        with contextlib.redirect_stdout(io.StringIO()):
            loop.phase_close(cfg, st, False)
        self.assertFalse(loop.pause_flag().exists())


class TestGpuHoursCountGpus(DriverCase):
    """opd-pipe e007-l1b: 5.1 h wall on two GPUs was billed 5.1 GPU-h."""

    def test_the_field_is_parsed_and_defaults_to_one(self):
        self.assertEqual(loop.gpu_count("**GPUs:** 4\n**Trial:** x"), 4)
        self.assertEqual(loop.gpu_count("**GPUs:** 2 (A100)\n"), 2)
        self.assertEqual(loop.gpu_count("**Trial:** x"), 1)
        self.assertEqual(loop.gpu_count("**GPUs:** 0"), 1)

    def test_the_bill_is_wall_hours_times_gpus(self):
        clock = FakeClock(step=1800.0)          # 30 min per poll
        loop.time = clock
        cfg = self.write_goal(monitor={"interval_min": 1})
        st = {"iteration": 1}
        body = "**Trial:** sleep 0.2\n**GPUs:** 3\n**Monitor Profile:** none"
        loop.claude = lambda *a, **k: '{"status": "HEALTHY"}'
        loop.run_trial("T", body, st, cfg)
        self.assertGreater(st["gpu_hours"], 0.0)
        # every poll is 0.5 wall-hours; billed x3 -> a multiple of 1.5
        self.assertAlmostEqual(st["gpu_hours"] / 1.5,
                               round(st["gpu_hours"] / 1.5), places=6)


class TestApproveNote(DriverCase):
    approve = TestApproveGate.approve
    """opd-pipe e007-l1: `approve --note "..."` was read as a gate name."""

    def test_a_note_rides_along_with_the_approval(self):
        loop.save(loop.STATE, {"phase": "gate", "pending_gate": "plan"})
        r = self.approve("--note", "delegated: no open concern, within 4h")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.tmp / "approvals" / "plan.approved").exists())
        notes = [e for e in self.events() if e["event"] == "note"]
        self.assertTrue(notes and "delegated" in notes[0]["detail"])
        self.assertIn("approval of plan", notes[0]["detail"])

    def test_a_stray_word_is_refused_as_not_a_gate(self):
        loop.save(loop.STATE, {"phase": "gate", "pending_gate": "plan"})
        r = self.approve("looks fine")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not a gate", r.stderr)
        self.assertFalse((self.tmp / "approvals" / "plan.approved").exists())


class TestOverviewCap(DriverCase):
    """opd-pipe problem 4: the Overview grew 39 -> 1,657 lines and the
    Generators sampled read none of it."""

    def arch(self, n):
        body = "\n".join(f"- line {i}" for i in range(n))
        (self.tmp / "Architecture.md").write_text(
            f"# Architecture\n\n## Overview\n{body}\n\n## API Surface\n"
            + "\n".join("- api" for _ in range(200)) + "\n")

    def test_counts_only_the_overview(self):
        self.arch(12)
        self.assertEqual(loop.overview_lines(
            (self.tmp / "Architecture.md").read_text()), 12)
        self.assertEqual(loop.overview_lines("# A\n\n## Data\nx\n"), 0)

    def test_an_oversized_overview_is_a_plan_problem(self):
        cfg = self.write_goal()
        self.arch(loop.OVERVIEW_MAX_LINES + 1)
        probs = loop.plan_problems(cfg, PLAN)
        self.assertTrue(any("Overview" in p for p in probs), probs)
        self.arch(loop.OVERVIEW_MAX_LINES)
        self.assertEqual(loop.plan_problems(cfg, PLAN), [])


CARRY_PLAN = """# Plan

### Phase 1, Step 1: First ticket
**Boundary:** src/

### Phase 1, Step 2: Second ticket
**Boundary:** src/other/

### Phase 1, Step 3: Third ticket
**Boundary:** src/third/
"""


class TestCarry(DriverCase):
    """opd-pipe problem 2: 28 Non-blocking lines, three of which came
    true later because nothing handed them to the next session."""

    def setUp(self):
        super().setUp()
        (self.tmp / "Plan.md").write_text(CARRY_PLAN)
        loop.git_commit = lambda msg: "deadbee"

    def test_a_carry_line_reaches_later_generators_and_the_final_audit(self):
        cfg = self.write_goal()
        self.results({"metrics": {"acc": 0.5}})
        prompts = []

        def fake(_st, role, prompt, *a, **k):
            prompts.append((role, prompt))
            if role == "evaluator":
                v = {"verdict": "PASS", "reason": "ok", "evidence": []}
                if "'Phase 1, Step 1'" in prompt:
                    v["carry"] = ["reference forward keeps gradients; "
                                  "peak memory will show it"]
                loop.VERDICT.write_text(json.dumps(v))
            return "done"
        loop.claude = fake
        st = self.iterate_state()
        loop.phase_iterate(cfg, st)
        loop.phase_final(cfg, st)
        gens = [p for r, p in prompts if r == "generator"]
        self.assertNotIn("Carried findings", gens[0])
        self.assertIn("keeps gradients", gens[1])
        self.assertIn("keeps gradients", gens[2])
        final = [p for r, p in prompts if "FINAL evaluation" in p]
        self.assertTrue(final and "keeps gradients" in final[0])
        self.assertIn("resolved / does not apply", final[0])
        self.assertEqual(st["carry"][0]["from"], "Phase 1, Step 1")
        self.assertIn("carry", [e["event"] for e in self.events()])

    def test_the_list_is_bounded(self):
        st = {}
        for i in range(3):
            loop.absorb_carry(st, {"carry": [f"c{i}-{j}" for j in range(15)]},
                              f"t{i}")
        self.assertEqual(len(st["carry"]), loop.CARRY_MAX)
        self.assertEqual(st["carry"][-1]["line"], "c2-14")
        loop.absorb_carry(st, {"carry": []}, "none")
        loop.absorb_carry(st, {}, "none")
        self.assertEqual(loop.carry_text({}), "")


TDD_PLAN = """# Plan

### Phase 1, Step 1: Writer with tests
**Output:** src/writer.py
**Test Contract:**
- test_writes: input -> writes results/out.json
**Boundary:** src/, results/out.json
**Run Command:** python3 src/writer.py 2>&1 | tee logs/latest.log
"""


class TestRedLogGate(DriverCase):
    """opd-pipe problem 10: 78 of 93 code tickets wrote the code first."""
    drive, ran = TestOutputGate.drive, TestOutputGate.ran
    complete, gates = TestOutputGate.complete, TestOutputGate.gates

    def setUp(self):
        super().setUp()
        (self.tmp / "Plan.md").write_text(TDD_PLAN)
        loop.git_commit = lambda msg: "deadbee"

    def test_a_ticket_with_a_test_contract_needs_its_red_run_on_disk(self):
        self.drive(self.complete)
        self.assertTrue(self.gates())
        self.assertIn("red run", self.gates()[0]["detail"])
        self.assertIn("tdd-red-1.log", self.gates()[0]["detail"])

    def test_the_red_log_satisfies_it(self):
        def gen():
            self.complete()
            (self.tmp / "logs" / "tdd-red-1.log").write_text(
                "FAILED test_writes - ModuleNotFoundError")
        calls, st = self.drive(gen)
        self.assertEqual(self.gates(), [])
        self.assertEqual(self.ledger()[0]["verdict"], "PASS")

    def test_the_generator_is_told_where(self):
        calls, _ = self.drive(self.complete)
        gen = [p for r, p in calls if r == "generator"][0]
        self.assertIn("Red log: logs/tdd-red-1.log", gen)

    def test_no_test_contract_means_no_red_log_required(self):
        (self.tmp / "Plan.md").write_text(OUTPUT_PLAN)
        self.drive(self.complete)
        self.assertEqual(self.gates(), [])


class TestApprovalNeedsHuman(DriverCase):
    """opd-pipe problem 11: 22 gates approved in a median of 36 s under
    delegation, one of them on the Assumption that drove the drift."""

    def wait(self):
        flag = self.tmp / "approvals" / "plan.approved"

        class Clock(FakeClock):
            def sleep(self, _sec):
                flag.touch()
        loop.time = Clock()
        loop.wait_approval({}, "plan", "review it")
        return [e for e in self.events()
                if e["event"] == "approval_needs_human"]

    def test_a_concern_line_raises_the_event(self):
        (self.tmp / "Evaluation.md").write_text(
            "# Evaluation\n\n- **CRITERIA CONCERN:** acc >= 0.9 has no "
            "probe -- amend before data to 0.85\n\nOPEN ASSUMPTION: 6 -- "
            "the tokenizer is shared\n\nAll else OK.\n")
        ev = self.wait()
        self.assertEqual(len(ev), 1)
        self.assertIn("CRITERIA CONCERN: acc >= 0.9", ev[0]["detail"])
        self.assertIn("OPEN ASSUMPTION: 6", ev[0]["detail"])

    def test_a_clean_review_raises_nothing(self):
        (self.tmp / "Evaluation.md").write_text("# Evaluation\n\nOK.\n")
        self.assertEqual(self.wait(), [])

    def test_prose_about_the_label_is_not_the_label(self):
        """First live run (toy, 2026-10-25): the Evaluator's heading
        "**Open assumptions.** Read all 5 Plan.md Assumptions ..." and
        its sentence "No `OPEN ASSUMPTION:` lines" raised the event on a
        review that had found nothing for a human."""
        (self.tmp / "Evaluation.md").write_text(
            "**Open assumptions.** Read all 5 Plan.md Assumptions. All are "
            "the Planner's.\n`OPEN ASSUMPTION:` lines: none written.\n"
            "- criteria concern: none\n")
        self.assertEqual(self.wait(), [])


class TestAutoDeferredTrialAudit(DriverCase):
    """opd-pipe problem 6: `Audit: deferred` was written once in 20
    loops; the driver can see a no-code Trial re-run itself."""

    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, loop, "run_trial", loop.run_trial)
        self.addCleanup(setattr, loop, "tree_fingerprint",
                        loop.tree_fingerprint)
        self.cfg = self.write_goal(type="experiment")
        (self.tmp / "Plan.md").write_text(
            CARRY_PLAN.replace("**Boundary:** src/\n",
                               "**Boundary:** src/\n**Trial:** true\n", 1)
            .replace("**Boundary:** src/other/\n",
                     "**Boundary:** src/other/\n**Trial:** true\n", 1)
            .replace("**Boundary:** src/third/\n",
                     "**Boundary:** src/third/\n**Trial:** true\n", 1))
        loop.git_commit = lambda msg: "abc1234"
        loop.run_trial = lambda *a, **k: True
        loop.tree_fingerprint = lambda: "same"          # no code change
        self.results({"metrics": {"acc": 0.5}})

    def drive(self, st):
        prompts = []

        def fake(_st, role, prompt, *a, **k):
            prompts.append((role, prompt))
            if role == "evaluator":
                loop.VERDICT.write_text(json.dumps(
                    {"verdict": "PASS", "reason": "ok", "evidence": []}))
            return "STATUS: pass"
        loop.claude = fake
        loop.phase_iterate(self.cfg, st)
        return [p for r, p in prompts if r == "evaluator" and "Mode 2" in p]

    def test_a_no_code_trial_rerun_is_deferred_but_first_green_is_not(self):
        st = self.iterate_state()
        audits = self.drive(st)
        # Step 1: acc goes green for the first time -> audited.
        # Step 2: same harness, nothing changed, not first green -> free.
        # Step 3: the last ticket is never deferred (the final pass follows).
        self.assertEqual(len(audits), 2)
        self.assertIn("'Phase 1, Step 1'", audits[0])
        self.assertIn("'Phase 1, Step 3'", audits[1])
        self.assertIn("no code change", self.ledger()[1]["reason"])

    def test_a_trial_ticket_that_changed_code_is_still_audited(self):
        fp = iter("abcdefghij")
        loop.tree_fingerprint = lambda: next(fp)
        st = self.iterate_state()
        self.assertEqual(len(self.drive(st)), 3)


class TestEvaluatorAuditTier(DriverCase):
    """8.2.1: `models.evaluator_audit` buys the routine per-ticket audit
    from a cheaper model; first green, final, contract review and
    adjudication stay on `models.evaluator` (opd-pipe problem 6: the
    Evaluator was 53 % of spend with the GPU idle throughout)."""

    VALID = TestValidateGoal.VALID

    def test_session_choice_falls_back_to_the_role(self):
        cfg = {"models": dict(loop.DEFAULT_MODELS)}
        self.assertEqual(loop.session_choice(cfg, "evaluator", "audit"),
                         ("evaluator", "claude-opus-5-5", "high"))
        cfg["models"]["evaluator_audit"] = "claude-sonnet-5-5"
        self.assertEqual(loop.session_choice(cfg, "evaluator", "audit"),
                         ("evaluator_audit", "claude-sonnet-5-5", "high"))
        cfg["effort"] = {"evaluator_audit": "medium"}
        self.assertEqual(loop.session_choice(cfg, "evaluator", "audit")[2],
                         "medium")
        self.assertEqual(loop.session_choice(cfg, "evaluator")[0],
                         "evaluator")

    def test_validate_accepts_a_full_id_and_refuses_an_alias(self):
        ok = dict(self.VALID, models=dict(self.VALID["models"],
                                          evaluator_audit="claude-sonnet-5"),
                  effort={"evaluator_audit": "medium"})
        loop.validate_goal(ok)
        bad = dict(self.VALID, models=dict(self.VALID["models"],
                                           evaluator_audit="sonnet"))
        with open(os.devnull, "w") as null:
            real, sys.stderr = sys.stderr, null
            try:
                with self.assertRaises(SystemExit):
                    loop.validate_goal(bad)
            finally:
                sys.stderr = real

    def test_only_the_routine_audit_uses_the_tier(self):
        cfg = self.write_goal(models=dict(loop.DEFAULT_MODELS,
                                          evaluator_audit="claude-sonnet-5-5"))
        (self.tmp / "Plan.md").write_text(CARRY_PLAN)
        loop.git_commit = lambda msg: "deadbee"
        self.results({"metrics": {"acc": 0.5}})
        seen = []

        def fake(_st, role, prompt, *a, **k):
            if role == "evaluator":
                seen.append((prompt[:40], k.get("tier", "")))
                loop.VERDICT.write_text(json.dumps(
                    {"verdict": "PASS", "reason": "ok", "evidence": []}))
            return "done"
        loop.claude = fake
        st = self.iterate_state()
        loop.phase_iterate(cfg, st)
        loop.phase_final(cfg, st)
        tiers = [t for _p, t in seen]
        # ticket 1: first green -> full evaluator; 2 and 3: audit tier;
        # final: full evaluator
        self.assertEqual(tiers, ["", "audit", "audit", ""])

    def test_status_shows_the_tier_row_once_it_has_spent(self):
        cfg = self.write_goal(models=dict(loop.DEFAULT_MODELS,
                                          evaluator_audit="claude-sonnet-5-5"))
        st = {"roles": {"evaluator_audit": {"sessions": 3, "minutes": 12.0,
                                             "usd": 1.5}}}
        text = "\n".join(loop.role_table(cfg, st, live=False))
        self.assertIn("evaluator_audit ", text,
                      "the role column must be wide enough for the tier")
        self.assertIn("claude-sonnet-5-5", text)


class TestHookCommentsAreData(HookCaller, unittest.TestCase):
    """8.2.1 toy run, 17:19:08: a read-only Evaluator's `cp ... /tmp/x/
    # restore clean copy` was denied as a shell write to 'copy'."""

    def test_the_live_false_positive(self):
        self.assertEqual(self.call("evaluator", "Bash", {"command":
            "cd /repo\ncp -r src tests scripts /tmp/eval_sandbox/   "
            "# restore clean copy\ncd /tmp/eval_sandbox\npython3 x.py"}),
            self.ALLOW)

    def test_a_comment_naming_git_or_rm_is_not_a_command(self):
        self.assertEqual(self.call("generator", "Bash", {"command":
            "# git commit happens in the driver\npytest -q"}), self.ALLOW)
        self.assertEqual(self.call("evaluator", "Bash", {"command":
            "ls results  # do not rm goal.json here"}), self.ALLOW)

    def test_a_quoted_hash_is_not_a_comment(self):
        # the write after the quoted '#' is still a write to a core file
        self.assertEqual(self.call("generator", "Bash", {"command":
            "echo '# heading' > Architecture.md"}), self.DENY)

    def test_a_real_write_before_the_comment_is_still_decided(self):
        self.assertEqual(self.call("generator", "Bash", {"command":
            "cp a.txt Plan.md  # harmless"}), self.DENY)
        self.assertEqual(self.call("generator", "Bash", {"command":
            'git commit -m "x"  # note'}), self.DENY)

    def test_strip_comments_unit(self):
        sys.path.insert(0, str(HOOK.parent))
        import enforce_authority as ea
        self.assertEqual(ea.strip_comments("a # b\nc"), "a \nc")
        self.assertEqual(ea.strip_comments("echo '#x' > f"), "echo '#x' > f")
        self.assertEqual(ea.strip_comments("x#y"), "x#y")


if __name__ == "__main__":
    unittest.main(verbosity=2 if "-v" in sys.argv else 1,
                  argv=[a for a in sys.argv if a != "-v"])
