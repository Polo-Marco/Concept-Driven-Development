# Concept-Driven Development (CDD) 8.1.14

You are part of a session-based AI development pipeline. You enforce
governance, honor phase authority, and route to the appropriate Mode
Skill. In v8.0 the pipeline can run autonomously under a deterministic
driver; your session's role and authority are set per session, and the
PreToolUse hook enforces them mechanically.

**Compatible with Claude Code and Cursor.** This file is auto-loaded
by both tools. Rules in `.claude/rules/` and skills in `skills/` are
read on-demand — follow the references below.

## Framework-Repo Maintenance

If `MAINTENANCE.md` exists at the project root, this repo is the CDD
framework source itself — not a deployed project. Read `MAINTENANCE.md`
before acting: it defines the feedback→upgrade loop and grants
Maintainer authority that supersedes the phase-authority matrix below.

## Core Principles (always apply)

Before anything else, honor `.claude/rules/principles.md`:
**Simplicity First**, **Surgical Changes**, **Think Before Coding**.
The minimum intentional change wins. No speculative scope.

## Git History Is the Changelog

There is no `CHANGELOG.md`. **Git history is the project's changelog.**
Commit messages MUST be detailed (`.claude/rules/governance.md §1`).
In loop mode, only the driver commits.

## Pipeline Architecture (v8.0)

```
                    ┌────────────── [/loop] ───────────────┐
[/discuss]          │  Ask → Goal.md + goal.json (frozen)  │   [/retro]
 think              │  driver: Planner → contract review   │   improve
 (docs only)        │        → HUMAN GATE (approve once)   │   (journal
                    │  per ticket: Generator → Trial ←     │    only)
                    │        Monitor → Evaluator → verdict │
                    │  PASS→commit / RETRY≤3 / REPLAN→gate │
                    │        / ESCALATE→user               │
                    └──────────────────────────────────────┘
```

Three commands. Everything else is internal machinery:

- **`[/discuss]`** — thinking partner. Reads Concept/Architecture/docs,
  debates direction, edits `Concept.md`/`docs/` only with user
  confirmation. No plan, no code.
- **`[/loop] <goal>`** — the Goal Setter (Ask phase) turns the goal
  into `Goal.md` + `goal.json`, then the driver
  (`.claude/driver/loop.py`) orchestrates fresh Planner / Generator /
  Evaluator / Monitor sessions per `.claude/rules/loop-protocol.md`.
  Goal types: `build | modify | experiment | migrate | merge` — the
  Planner loads the matching internal mode skill.
- **`[/retro]`** — the Coach. Reads `journal/` across loops, surfaces
  patterns, recommends framework/skill changes. Includes the harness
  staleness check on new model generations.
- **You (the user)** — approve the plan gate, answer escalations, sign
  off at the end, fill the journal Feedback block.

## Mode Routing

Dormant until the user invokes a command.

| Command | Session | Action |
|---|---|---|
| `[/discuss] [topic]` | Discuss | Read `@skills/mode-discuss/SKILL.md` |
| `[/loop] [goal]` | Goal Setter → driver | Read `@skills/mode-loop/SKILL.md` |
| `[/retro]` | Retro | Read `@skills/mode-retro/SKILL.md` |

### Escape hatch (manual 7.0-style operation)

The internal skills remain directly invocable — the driver calls the
same skills you would. Authority rules apply identically.

| Command | Session | Action |
|---|---|---|
| `[/build]` `[/modify]` `[/migrate]` `[/merge]` | Planner | Read the matching `@skills/mode-*/SKILL.md` |
| `start execution` | Generator | `.claude/rules/generator-protocol.md` |
| `[/evaluate]` | Evaluator | Read `@skills/mode-evaluate/SKILL.md` |
| `check the latest run log` | (any) | Read `logs/latest.log`, diagnose, route to a `modify` goal |

## Phase-Based File Authority (hook-enforced in loop mode)

| File | Planner | Generator | Evaluator | Monitor |
|---|---|---|---|---|
| `Concept.md`, `Architecture.md`, `README.md` | Read / Write | Read only | Read only | — |
| `Plan.md` / `Triage.md` | Read / Write | Read only | Read only | — |
| `./skills/**`, `**/CLAUDE.md` | Read / Write / Create | Read only | Read only | — |
| `docs/*.md` | Read only (`DEVIATIONS.md` append) | Read only | Read only | — |
| `Goal.md`, `goal.json`, `ledger.jsonl`, `loop-state.json` | **Read only — ALL sessions** (user/driver-owned) | | | |
| `Evaluation.md`, `verdict.json` | — | — | Read / Write | — |
| `journal/*.md` | Append | Append | Append | — |
| `src/`, `tests/` | **—** (never) | Read / Write (within Boundary) | Read only (may run) | Read only |
| git write commands | loop: driver only | never | never | never |

Discuss may write `Concept.md` + `docs/` (with confirmation); Retro
writes only `journal/`. Full matrix + Generator Boundary Rules:
`.claude/rules/phase-authority.md`. Enforcement:
`.claude/hooks/enforce_authority.py` — a denial means STOP and report,
never work around.

## Session Lifecycle

### `[/loop]` (the default "do" path)
1. Goal Setter interrogates until every success criterion is
   machine-checkable; writes `Goal.md` + `goal.json`; user confirms;
   files freeze.
2. User starts the driver (tmux):
   `python3 .claude/driver/loop.py 2>&1 | tee logs/driver.log`.
3. Driver: five deterministic gates (machinery / goal-contract
   shape / worktree isolation / preflight / evidence — nothing is
   planned or spent until all five pass; the evidence gate refuses a
   loop whose criteria read files that already exist) → Planner session → Evaluator contract review
   (≤2 rounds) → waits at the human gate. User reviews Plan.md,
   approves (`loop.py approve`, control tower, or phone). There are no
   mid-loop `[Halt here]` pauses in loop mode.
4. Driver iterates tickets: Generator (bearings + smoke test → TDD) →
   trial launch + Monitor polling → Evaluator → `verdict.json` →
   PASS commit / RETRY ≤3 (each retry carries the verdict that
   rejected the last attempt) / REPLAN (re-gated) / ESCALATE. Ledger
   appended every iteration. Budgets checked — and re-read — every
   iteration.
5. Final evaluation verifies ALL `goal.json` criteria → done. The
   driver writes the loop's `journal/` record on every terminal exit;
   the user fills its Feedback block and closes the loop with
   `python3 .claude/driver/loop.py close`.

Remote control: keep an interactive session in tmux with Remote
Control enabled as the control tower — `status` and `approve` from
your phone. See `.claude/rules/loop-protocol.md`.

### Discuss / Retro / manual sessions
Unchanged from 7.0 — see `.claude/rules/phase-authority.md` and the
mode skills. Generator sessions follow
`.claude/rules/generator-protocol.md` (now with bearings + smoke test
at session start); parallel groups follow
`.claude/rules/parallel-execution.md`.

### Session Journal (two tiers)
- **Tier 1 (`journal/*.md`):** curated per-loop summaries + the user's
  Feedback block. In loop mode the driver writes the record (tickets,
  iterations, verdicts, criteria, notable events) on every terminal
  exit and never overwrites the Feedback block; in manual sessions each
  session appends its own. Primary artifact for `[/retro]`.
- **Tier 2 (`journal/traces/*.jsonl`):** full transcripts via the
  `SessionEnd` hook. Gitignored. Claude Code only.

## Quick Reference

- Core principles → `.claude/rules/principles.md`
- Governance (git, security, logging, TDD, lifecycle) → `.claude/rules/governance.md`
- **Loop protocol (v8.0)** → `.claude/rules/loop-protocol.md`
- Run logging → `.claude/rules/run-logging.md`
- Phase authority & boundaries → `.claude/rules/phase-authority.md`
- Generator execution protocol → `.claude/rules/generator-protocol.md`
- Parallel execution → `.claude/rules/parallel-execution.md`
- Task ticket format (+ experiment tickets) → `.claude/rules/task-ticket-format.md`
- Agent roles → `.claude/agents/cdd-*.md`
- Skill writing standard → `@skills/skill-template/SKILL.md`
