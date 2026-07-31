#!/usr/bin/env bash
# Set up a throwaway CDD project for a real end-to-end [/loop] test of
# the EXPERIMENT path -- the half `toy_project.sh` never touches.
#
#   ./toy_experiment.sh [framework-repo] [target-dir]
#
# Defaults: framework = ~/Documents/Claude/Projects/Concept-Driven-Development
#           target    = ~/cdd-toy-exp
#
# `toy_project.sh` is a `build` goal: no Trial field, so run_trial()
# returns immediately, the Monitor is never spawned, and RETRY / REPLAN
# / the ledger-as-replan-memory are never exercised. Four green build
# runs proved none of them. This one is shaped to force all of them:
#
#   trial 1, launch 1  baseline lr=0.5 emits `loss=nan` at step 8 and
#                      dies at step 20 -> the Monitor sees a known
#                      signature (INTERVENE, driver kills) or, if it
#                      does not, the non-zero exit catches it. Either
#                      way: RETRY.
#   trial 1, launch 2  baseline runs clean, final_loss ~1.06, misses the
#                      <= 0.25 threshold. The config is immutable
#                      (loop-protocol.md section 5), so the only legal
#                      move is a new plan -> REPLAN -> second human gate.
#   trial 2            a smaller lr from the shipped grid clears the
#                      threshold -> PASS -> goal_reached.
#
# The schedule is deterministic and lives entirely in bench/train.py: a
# launch counter on disk, a synthetic loss curve, no randomness. A smoke
# test whose outcome depends on a seed is not a test. It is documented
# in Architecture.md too, so the Evaluator's provenance audit reads a
# declared fault-injection stub rather than a rigged harness.
#
# Monitor timing is load-bearing. run_trial() sleeps min(interval, 60)
# and skips the poll unless `interval` has elapsed, so a trial shorter
# than monitor.interval_min gets ZERO Monitor sessions. goal.json pins
# interval_min: 1 and a clean trial runs 40 steps x 5s = 200s, which is
# three polls. Do not shorten either without shortening the other.
#
# Cost, MEASURED 2026-07-30 at the tiers pinned below, not estimated:
# $7.66 and 32 minutes wall clock for the whole run -- 2 iterations, 3
# Generator sessions, 1 REPLAN (fresh Planner + second contract review),
# 2 contract reviews, 3 per-iteration Evaluator audits, 1 final
# provenance audit, and 7 Monitor sessions (haiku, pennies). Trials burn
# 10 minutes of wall clock and no tokens at all.
#
# The cap below is 15, roughly 2x measured: `max_replans: 2` permits one
# more replan than this run needed, and a replan costs ~$2.50, so the
# worst case the budgets themselves allow is ~$11. The first estimate
# here was $25, which is a cap that can never bite and therefore is not
# a circuit breaker. Do not raise a cap mid-run -- that is the user's
# call, not the driver's and not the maintainer's.
set -euo pipefail

FW="${1:-$HOME/Documents/Claude/Projects/Concept-Driven-Development}"
DIR="${2:-$HOME/cdd-toy-exp}"

[ -d "$FW/.claude/driver" ] || { echo "no .claude/driver in $FW"; exit 1; }
[ -e "$DIR" ] && { echo "$DIR already exists -- remove it first"; exit 1; }
git config --get user.email >/dev/null 2>&1 || {
  echo "git has no user.email configured -- the driver is the only"
  echo "committer in a loop, and a commit it cannot make is a loop"
  echo "that reports success with nothing in git. Set it first:"
  echo "  git config --global user.email you@example.com"
  echo "  git config --global user.name  'Your Name'"
  exit 1; }

mkdir -p "$DIR"
cp -r "$FW/.claude" "$DIR/.claude"
cd "$DIR"
mkdir -p bench configs logs results

cat > bench/train.py <<'EOF'
#!/usr/bin/env python3
"""toybench 1.0 -- a deterministic stand-in for a training harness.

This is NOT a trainer and does not pretend to be one. It exists so the
CDD loop can be exercised end to end with no GPU and no network: it
burns wall-clock, prints a progress stream a Monitor can classify, and
writes a metrics file the driver can check off disk.

Everything it does is deterministic and lives in this file ON PURPOSE.
Two behaviours are deliberately injected, and both are declared here and
in Architecture.md so an auditor reads a documented stub rather than a
rigged result:

  1. `loss` is a synthetic curve, not a measurement. It decays toward a
     floor that rises with `lr`, so smaller learning rates finish lower.
  2. The shipped baseline learning rate emits `loss=nan` from step 8 on
     its FIRST launch only, and aborts at step 20. Every later launch of
     the same value runs clean. This is fault injection: it exercises
     the Monitor's crash-class classification and the driver's RETRY.

One config per launch, by design: a launched trial's configuration is
immutable (.claude/rules/loop-protocol.md section 5).

    python3 bench/train.py --config configs/<name>.json
"""
import argparse
import json
import math
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"

STEPS = 40                 # x SECONDS_PER_STEP = 200s, three 1-min polls
SECONDS_PER_STEP = 5.0
COLD_START_LR = 0.5        # the shipped baseline, and only it
NAN_FROM_STEP = 8          # ~40s in: inside the first monitor interval
NAN_ABORTS_AT_STEP = 20    # ~100s in: dies even if nobody kills it


def loss_at(lr: float, step: int) -> float:
    """Synthetic. Not a measurement. Monotone in lr."""
    return round(0.06 + 2.0 * lr + 1.4 * math.exp(-step / 6.0), 4)


def launch_number(lr: float) -> int:
    """How many times this lr has been launched, counted on disk so the
    injected schedule is deterministic across processes."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    f = RESULTS / ".launches.json"
    try:
        counts = json.loads(f.read_text())
    except Exception:
        counts = {}
    key = "lr=%g" % lr
    counts[key] = counts.get(key, 0) + 1
    f.write_text(json.dumps(counts, indent=2, sort_keys=True) + "\n")
    return counts[key]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = json.loads(Path(args.config).read_text())
    lr = float(cfg["lr"])
    launch = launch_number(lr)
    cold = abs(lr - COLD_START_LR) < 1e-12 and launch == 1
    print("toybench 1.0 | config=%s lr=%g steps=%d launch=%d"
          % (args.config, lr, STEPS, launch), flush=True)

    for step in range(1, STEPS + 1):
        time.sleep(SECONDS_PER_STEP)
        if cold and step >= NAN_FROM_STEP:
            print("step %d/%d loss=nan grad_norm=nan" % (step, STEPS),
                  flush=True)
            if step >= NAN_ABORTS_AT_STEP:
                print("FATAL: loss diverged to nan -- aborting",
                      flush=True)
                return 1
            continue
        print("step %d/%d loss=%.4f" % (step, STEPS, loss_at(lr, step)),
              flush=True)

    final = loss_at(lr, STEPS)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "trial.json").write_text(json.dumps({
        "harness": "toybench 1.0",
        "config_path": args.config,
        "config": cfg,
        "launch": launch,
        "steps_done": STEPS,
        "final_loss": final,
        "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                      time.gmtime()),
    }, indent=2, sort_keys=True) + "\n")
    print("done: final_loss=%.4f -> results/trial.json" % final,
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
EOF
chmod +x bench/train.py

cat > configs/baseline.json <<'EOF'
{
  "name": "baseline",
  "lr": 0.5,
  "note": "shipped baseline -- immutable, trial 1 must run it unchanged"
}
EOF

cat > Concept.md <<'EOF'
# Concept: toybench lr search

A throwaway project whose only purpose is to exercise the CDD loop's
EXPERIMENT path end to end with real model sessions.

## Why This Exists
`toy_project.sh` proved the `build` path. It has no trials, so it never
spawns a Monitor and never reaches RETRY or REPLAN. This project asks an
empirical question instead, so the driver has to launch a trial, poll it,
score it, and replan when a configuration is ruled out.

## Scope
Find a learning rate for the shipped `bench/train.py` harness that gets
`final_loss` to 0.25 or below. Nothing else. No packaging, no library
API, no second harness.

## Honesty
`bench/train.py` is a stub, not a trainer, and says so in its own
docstring: the loss curve is synthetic and one failure is deliberately
injected. The experiment is real as a *process*; the science is not the
point, the plumbing is.
EOF

cat > Architecture.md <<'EOF'
# Architecture

## Overview
One shipped harness plus the small amount of code a trial needs around
it. `bench/train.py` is FIXED third-party-equivalent code: it is not
modified by any ticket and must never appear in a ticket Boundary. A
trial is one launch of it against exactly one config file in `configs/`.
`bench/report.py` (to be written) turns the harness's raw
`results/trial.json` into the flat `results/metrics.json` the loop's
success criteria are checked against. Tests live in `tests/` and run
under `python3 -m unittest discover -s tests` -- stdlib only, so this
project needs nothing installed.

## Components
- `bench/train.py` — SHIPPED, IMMUTABLE. `--config <path>`, one config
  per launch. Runs 40 steps at 5s each (~200s), prints one progress
  line per step, writes `results/trial.json` on success.
- `configs/*.json` — one file per trial: `{"name", "lr", ...}`.
  `configs/baseline.json` (lr=0.5) is shipped and immutable.
- `bench/report.py` — TO BE WRITTEN. Reads `results/trial.json`, writes
  `results/metrics.json`. Must fail loudly if the trial file is absent
  rather than emitting a stale or invented number.

## The harness's declared behaviour
Documented so nobody has to reverse-engineer it, and so a provenance
audit can tell a declared stub from a rigged result:

- `loss` is SYNTHETIC — computed from `lr` and the step number, not
  measured. It decays toward a floor that RISES with `lr`: smaller
  learning rates finish lower. The coefficients are deliberately not
  documented; finding a value that clears the threshold is the
  experiment.
- FAULT INJECTION: the baseline lr emits `loss=nan` from step 8 on its
  FIRST launch only and aborts at step 20 with a non-zero exit. Every
  later launch of the same value runs clean. Known signature:
  `nan_loss`. Remedy: relaunch unchanged — this is a cold-start fault,
  not a property of the config.

## Data
`results/trial.json` — raw harness output: `harness`, `config`,
`launch`, `steps_done`, `final_loss`, `finished_utc`.
`results/metrics.json` — flat, and the ONLY thing the loop's criteria
read: `{"final_loss": <float>, "steps_done": <int>}`.
EOF

cat > Goal.md <<'EOF'
# Goal — toybench: find a learning rate that clears the loss threshold

## Intent
Answer one empirical question about the shipped `bench/train.py`: is
there a learning rate in the candidate grid below that gets
`final_loss` to 0.25 or lower in a completed 40-step run? Record the
answer where a machine can check it.

## Preflight
- `python3` is on PATH
- `bench/train.py` exists (the shipped harness)

Nothing else. Standard library only, deliberately, so a smoke test of
the pipeline cannot fail on someone else's packaging.

## Protocol (binding — the plan is audited against this)
1. **Trial 1 MUST be `configs/baseline.json` unchanged.** The question
   is asked relative to the shipped baseline; a plan that skips it has
   not established what it is comparing against.
2. **One trial ticket per plan.** The next configuration is chosen from
   the previous trial's result, so it cannot be pre-planned. A plan
   containing two trial tickets is guessing at the second one.
3. **A launched trial's config is immutable**
   (`.claude/rules/loop-protocol.md` section 5). A config that has run
   and missed the threshold is RULED OUT and is never relaunched.
   Obtaining a different config is a REPLAN, not an edit.
4. **Never modify `bench/train.py` or `configs/baseline.json`**, and
   never put either in a ticket Boundary.
5. The driver launches trials, not the Generator. A trial ticket's
   **Trial:** field is the exact command; the Generator writes the
   config and the reporting code and stops.

## Candidate grid
`lr` ∈ {0.5 (shipped baseline), 0.05, 0.01}. One trial per value.

## Success criteria
- `final_loss <= 0.25` in `results/metrics.json`
- `steps_done >= 40` in `results/metrics.json`

Both are written by `bench/report.py`, which runs as the second half of
every trial command (`... && python3 bench/report.py`). A trial that is
killed or aborts never reaches it, so neither number can survive an
incomplete run. Nothing else is checked.

## Budgets
10 iterations, 2 replans, 3 hours of driver runtime, $15.

`goal.json` is the contract the driver reads; this line is a summary of
it. Raise a cap there (it is re-read every iteration) and this prose may
lag — that is fine, the JSON wins. Wall hours meter driver runtime, so
time spent waiting at the plan gate costs nothing.

## Notes
This is a smoke test of the pipeline's experiment path, not research.
`bench/train.py` is a declared stub with a synthetic loss curve and one
deliberately injected cold-start fault (see Architecture.md). Planner,
Generator and Evaluator are pinned to sonnet and the Monitor to haiku to
keep the run cheap; delete the `models` block in goal.json to use the
v8.1 defaults.
EOF

cat > goal.json <<'EOF'
{
  "goal": "toybench lr search: final_loss <= 0.25",
  "type": "experiment",
  "criteria": [
    {"metric": "final_loss", "op": "<=", "value": 0.25,
     "source": "results/metrics.json"},
    {"metric": "steps_done", "op": ">=", "value": 40,
     "source": "results/metrics.json"}
  ],
  "budgets": {
    "max_iterations": 10,
    "max_replans": 2,
    "max_wall_hours": 3,
    "max_usd": 15
  },
  "preflight": [
    {"name": "python3 on PATH", "run": "python3 -V"},
    {"name": "toybench harness present", "run": "test -f bench/train.py"}
  ],
  "models": {"planner": "sonnet", "generator": "sonnet",
             "evaluator": "sonnet", "monitor": "haiku"},
  "monitor": {"interval_min": 1},
  "evaluation_cadence": "per-iteration"
}
EOF

# loop-state.json, events.jsonl and journal/traces/ are the DRIVER's own
# ephemeral files (governance.md §5) -- ensure_gitignore() adds them at
# startup, so this list deliberately does not, and the run tests that.
printf 'logs/\napprovals/\n__pycache__/\n*.pyc\n.venv/\n' > .gitignore

git init -q .
git add -A
git commit -qm "toy experiment: concept, architecture, shipped harness, machinery"

echo
echo "Toy experiment ready at $DIR"
echo
echo "  1. verify the gates without spending anything:"
echo "       cd $DIR && python3 .claude/driver/loop.py check"
echo
echo "  2. start the loop (creates ../$(basename "$DIR")-loop, runs in tmux):"
echo "       python3 .claude/driver/loop.py start"
echo
echo "  3. when it reaches the human gate:"
echo "       python3 .claude/driver/loop.py status"
echo "       # read the worktree's Plan.md, then:"
echo "       python3 .claude/driver/loop.py approve"
echo "     Expect TWO gates: the plan, then the replan after the"
echo "     baseline config is ruled out."
echo
echo "  Push (optional, so a gate reaches your phone):"
echo "       cp .claude/driver/notify.sh.example .claude/driver/notify.sh"
echo "       chmod +x .claude/driver/notify.sh && export CDD_NTFY_TOPIC=..."
echo
echo "  Tear down:  git worktree remove --force ../$(basename "$DIR")-loop; rm -rf $DIR"
