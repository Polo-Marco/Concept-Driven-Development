# Concept-Driven Development (CDD) 8.1.21

A session-based AI development pipeline that runs itself. You state a
goal whose success criteria a machine can check, approve one plan, and a
deterministic driver orchestrates fresh Planner / Generator / Evaluator /
Monitor sessions until those criteria are met — or it escalates to you.
Every line of code traces back to a **Concept** and an **Architecture**
agreed before building. Git is the checkpoint system and the changelog.

**Works with Claude Code and Cursor.**

## Why

AI coding agents forget their own decisions, invent architecture, grade
their own work, drift from external contracts, over-engineer, and hand
control back to you at every step. CDD answers this with a strict
pipeline, structured files as external memory, hook-enforced authority
per session role, always-on engineering principles, and — since 8.0 — a
driver in place of your keyboard: success criteria are read off disk by
code rather than judged by a model, and the goal contract is mechanically
frozen so no session can move its own goalposts.

## The Three Commands

| Command | Persona | Purpose |
|---|---|---|
| `[discuss]` | The Thinking Partner | Think. Align direction; edit docs/Concept with confirmation. No code. |
| `[loop] <goal>` | The Goal Setter | Do. Measurable goal in → driver-orchestrated Plan / Generate / Monitor / Evaluate → answer out. |
| `[retro]` | The Coach | Improve. Review journals; tune the framework and your habits. |

Build, modify, migrate and merge are **goal types** inside `[loop]`. The
7.0 mode skills in `skills/` remain directly invocable as an escape hatch
under the same authority rules.

## How the Loop Works

```
[loop] <goal>
  │
  ├─ Ask phase (interactive): interrogate until every success criterion
  │  is metric + comparison + threshold + the file carrying the number
  │  → Goal.md + goal.json, frozen the moment you confirm them
  │
  └─ driver (.claude/driver/loop.py — a state machine, not a model)
       gates: machinery · contract shape · worktree isolation · preflight · evidence
         ↓       nothing is planned and nothing is spent until all pass
       Planner ──→ Evaluator contract review (bounded by rounds, money,
         ↓                                    and a per-loop cap)
       ══ HUMAN GATE ══  approve once — from the terminal or your phone
         ↓                              then: plan(loop): commit
       per ticket:  Generator → driver launches the trial ← Monitor polls
                      → output gate + criteria gate (code, fail-closed)
                      → Evaluator → verdict.json
                    PASS → commit · RETRY ≤3 · REPLAN → back to the gate
                                              · ESCALATE → you
         ↓
       final: every goal.json criterion re-checked, then a provenance audit
         ↓
       loop.py close: journal record, housekeeping, one commit
```

Three human contact points, all event-driven: approve the plan, answer
an escalation, sign off. Budgets (iterations, replans, USD, GPU-hours,
driver runtime) are circuit breakers that bite without you watching.
Each role runs on the model and reasoning effort you name in
`goal.json`; `status` and the journal show each role's model, effort,
session count, minutes and spend. All timestamps are Taipei time.

Full protocol: `.claude/rules/loop-protocol.md`. Authority matrix:
`.claude/rules/phase-authority.md`. Ticket format:
`.claude/rules/task-ticket-format.md`.

## Setup

**Prerequisites:** Claude Code or Cursor with a Claude account; git
with `user.name` / `user.email` set; for `[loop]`, Python 3 (standard
library only), tmux, and git `worktree`.

```bash
mkdir my-project && cd my-project && git init
# Copy CLAUDE.md, .claude/ and skills/ into the project root — all three
printf 'logs/\njournal/traces/\n' >> .gitignore
python3 .claude/driver/test_loop.py      # the driver's own suite, offline
```

`.claude/settings.json` wires two hooks that Claude Code asks you to
approve on first run: `PreToolUse → enforce_authority.py` (the authority
matrix, mechanically enforced — do not remove it) and
`SessionEnd → archive_transcript.py` (optional transcript archive to
`journal/traces/`, Claude Code only).

## Running a Loop

```
You:     [loop] Get the eval harness running against our endpoint and
         report accuracy on the social-science split.
Agent:   [interrogates: which file carries the number, what threshold,
          what must be true before the loop starts, which model and
          effort per role, budgets]
         "I will check `acc` in results/<loop-id>/eval.json is > 0 …
          Nothing else is checked. Correct?"
You:     yes
Agent:   [writes Goal.md + goal.json; runs `loop.py start`: worktree +
          tmux; tells you where to watch]
Driver:  == HUMAN GATE ==  Plan.md ready. Contract review: OK.
You:     [read Plan.md]  python3 .claude/driver/loop.py approve
         …per ticket: generate → run → criteria checked off disk →
          evaluate → commit. Hours pass. You are elsewhere…
Driver:  done — every criterion green, journal written.
You:     [fill the ## Feedback block in journal/; read a sample of diffs]
         python3 .claude/driver/loop.py close
```

Driver commands: `start`, `status`, `approve`, `replan "<reason>"`,
`note "<text>"`, `close`. Keep an interactive session in tmux with
Remote Control on as your control tower and `status` / `approve` from
your phone. Copy `.claude/driver/notify.sh.example` to `notify.sh` for
push notifications; a gate that waits re-announces itself every 4 h.

## File Structure

```
your-project/
├── CLAUDE.md                 ← Router (auto-loaded by Claude Code & Cursor)
├── .claude/
│   ├── settings.json         ← PreToolUse (authority) + SessionEnd (trace) hooks
│   ├── agents/cdd-*.md       ← Planner / Generator / Evaluator / Monitor roles
│   ├── driver/loop.py        ← The deterministic loop driver (+ test_loop.py)
│   ├── hooks/                ← enforce_authority.py, archive_transcript.py
│   └── rules/                ← loop-protocol, principles, governance,
│                                phase-authority, task-ticket-format, …
├── skills/mode-*/SKILL.md    ← loop, discuss, retro, and the goal-type skills
├── Concept.md, Architecture.md, README.md   ← persistent core files
├── docs/                     ← User-maintained reference docs + DEVIATIONS.md
├── journal/                  ← Per-loop records + your Feedback (traces/ gitignored)
├── logs/                     ← latest.log, driver.log, denials.log (gitignored)
└── Goal.md, goal.json, Plan.md, Evaluation.md   ← ephemeral loop artifacts
```

## Improving the Framework (this repo)

The framework repo is itself a CDD project: retros and feedback from
real projects go into `journal/`, `[retro] all` surfaces patterns, and a
Maintainer session applies accepted recommendations, bumps the version
and tags a release. Deployed projects upgrade by diffing tags
(`git diff v8.1.20..v8.1.21 -- CLAUDE.md .claude/ skills/`) and
re-copying — never by patching template files in place. Git history is
the changelog. Playbook: [`MAINTENANCE.md`](MAINTENANCE.md).

## License

Open for personal and commercial use. Attribution appreciated.
