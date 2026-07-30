#!/usr/bin/env bash
# Set up a throwaway CDD project for a real end-to-end [/loop] test.
#
#   ./toy-loop.sh [framework-repo] [target-dir]
#
# Defaults: framework = ~/Documents/Claude/Projects/Concept-Driven-Development
#           target    = ~/cdd-toy
#
# Deliberately tiny: two tickets, no network, no GPU, ~$1-2 of model
# spend at the model tiers pinned below. The point is to exercise the
# PLUMBING (gates -> planner -> contract review -> human gate -> generator
# -> evaluator -> commit -> final audit), not to build anything useful.
set -euo pipefail

FW="${1:-$HOME/Documents/Claude/Projects/Concept-Driven-Development}"
DIR="${2:-$HOME/cdd-toy}"

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

cat > Concept.md <<'EOF'
# Concept: wordfreq

A throwaway project whose only purpose is to exercise the CDD loop end
to end with real model sessions.

## Why This Exists
To prove the pipeline works before pointing it at real work.

## Scope
A single command-line tool that counts word frequencies in a text file.
Nothing more. No packaging, no configuration, no library API.
EOF

cat > Architecture.md <<'EOF'
# Architecture

## Overview
One Python package, `src/wordfreq/`, with no third-party dependencies.
`counter.py` holds the pure logic; `cli.py` is a thin argparse wrapper
over it. Tests live in `tests/` and run under `python3 -m unittest
discover -s tests` -- stdlib only, so the toy needs nothing installed.
A small script writes the run's metrics to `results/metrics.json` so the
loop's success criteria can be checked off disk.

## Components
- `src/wordfreq/counter.py` — `count_words(text: str) -> dict[str, int]`
- `src/wordfreq/cli.py` — reads a file path, prints the top N words
- `scripts/report.py` — runs the suite, writes `results/metrics.json`
  (counts passing tests via `unittest`, exercises the CLI once)

## Data
`results/metrics.json` is a flat object:
`{"tests_passed": <int>, "cli_ok": <0|1>}`
EOF

cat > Goal.md <<'EOF'
# Goal — wordfreq, end to end

## Intent
Build a working word-frequency CLI with tests, and have the run report
its own results to a file the loop can check.

## Preflight
- `python3` is on PATH

Nothing else: the toy uses only the standard library, deliberately, so
a smoke test of the pipeline cannot fail on someone else's packaging.

## Success criteria
- `tests_passed >= 3` in `results/metrics.json`
- `cli_ok == 1` in `results/metrics.json`

Nothing else is checked.

## Budgets
6 iterations, 1 replan, 1 wall-clock hour, $5.

## Notes
This is a smoke test of the pipeline, not a product. Planner and
Evaluator are pinned to sonnet to keep the run cheap; delete the
`models` block in goal.json to use the v8.1 defaults (opus).
EOF

cat > goal.json <<'EOF'
{
  "goal": "wordfreq CLI with tests, end to end",
  "type": "build",
  "criteria": [
    {"metric": "tests_passed", "op": ">=", "value": 3,
     "source": "results/metrics.json"},
    {"metric": "cli_ok", "op": "==", "value": 1,
     "source": "results/metrics.json"}
  ],
  "budgets": {
    "max_iterations": 6,
    "max_replans": 1,
    "max_wall_hours": 1,
    "max_usd": 5
  },
  "preflight": [
    {"name": "python3 on PATH", "run": "python3 -V"}
  ],
  "models": {"planner": "sonnet", "generator": "sonnet",
             "evaluator": "sonnet", "monitor": "haiku"},
  "monitor": {"interval_min": 5},
  "evaluation_cadence": "per-iteration"
}
EOF

printf 'logs/\napprovals/\n__pycache__/\n*.pyc\n.venv/\n' > .gitignore
mkdir -p logs results

git init -q .
git add -A
git commit -qm "toy project: concept, architecture, machinery"

echo
echo "Toy project ready at $DIR"
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
echo
echo "  Push (optional, so a gate reaches your phone):"
echo "       cp .claude/driver/notify.sh.example .claude/driver/notify.sh"
echo "       chmod +x .claude/driver/notify.sh && export CDD_NTFY_TOPIC=..."
echo
echo "  Tear down:  git worktree remove --force ../$(basename "$DIR")-loop; rm -rf $DIR"
