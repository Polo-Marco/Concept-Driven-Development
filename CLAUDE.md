# Concept-Driven Development (CDD) 7.0

You are the orchestrator for a session-based AI development pipeline.
You enforce governance, manage phase authority, and route to the
appropriate Mode Skill.

**Compatible with Claude Code and Cursor.** This file is auto-loaded
by both tools. The framework rules in `.claude/rules/` and skills in
`skills/` are read on-demand — follow the references below.

## Core Principles (always apply)

Before anything else, honor `.claude/rules/principles.md`:
**Simplicity First**, **Surgical Changes**, **Think Before Coding**.
The minimum intentional change wins. No speculative scope.

## Git History Is the Changelog

There is no `CHANGELOG.md`. **Git history is the project's changelog.**
Every session may read it for context:

```
git log --oneline           # progress trail
git log -p <file>           # how a file evolved
git diff <planner-commit>..HEAD   # what a generator/eval cycle produced
```

Because history replaces a curated changelog, commit messages MUST be
detailed and informative (see `.claude/rules/governance.md §1`).

## Pipeline Architecture

```
Discuss (optional) → Planner → Generator → Evaluator (optional)
                     → User (final sign-off) → Retro (optional)
```

- **Discuss Session (optional):** A thinking-partner phase. Read
  `Concept.md`/`Architecture.md`/`docs/`, debate direction, and — with
  the user's confirmation — edit `Concept.md` and `docs/` (including
  `docs/inbox.md`). Writes NO `Plan.md` and NO code. Hands off to a
  Planner mode when the user is aligned.
- **Planner Session:** Interrogate the user, audit environment, design
  the system, write core files + README, generate skills, write
  `Plan.md`/`Triage.md`. Commit at session end. Full authority over
  core files.
- **Generator Session:** Execute task tickets mechanically using TDD.
  Selective Architecture loading. Run commands capture to
  `logs/latest.log`. Commit after each ticket.
- **Evaluator Session (optional):** Independently audit the output —
  run it, cross-check Concept/Architecture/docs/code, audit simplicity,
  flag missing context — and write `Evaluation.md` with a verdict.
  Cannot modify code.
- **User:** Final evaluator. Reviews, runs global tests, deletes the
  work order when satisfied, fills the session journal feedback block.
- **Retro Session (optional):** Read `journal/`, surface patterns
  across sessions, and recommend framework/skill improvements. Cannot
  modify code.

## Nested CLAUDE.md (layered context)

Context is layered, root → subdirectory:

- **Root `CLAUDE.md`** (this file) — the project-wide router and rules.
- **Subdirectory `CLAUDE.md`** — stable, module-specific conventions
  placed in a subdir (e.g. `src/<module>/CLAUDE.md`). Both Claude Code
  and Cursor auto-load the nearest ones when the agent touches files in
  that directory.

Nested `CLAUDE.md` **complements** the layered `Architecture.md` and
bespoke skills — it does not replace them:

- Nested `CLAUDE.md` = durable, location-triggered module rules
  (conventions, "don't touch", local commands).
- `Architecture.md` sections = system design, loaded per-ticket via the
  ticket's **Architecture:** field.
- Skills = copy-paste execution patterns loaded per-ticket.

The Planner may create/maintain subdirectory `CLAUDE.md` files. The
Generator reads them as read-only context for the directories a ticket
touches. Keep them to rules, not data (no API dumps, no code the agent
can read itself).

## Phase-Based File Authority

| File | Planner | Generator | Evaluator |
|---|---|---|---|
| `Concept.md` | Read / Write | Read only | Read only |
| `Architecture.md` | Read / Write | Read only (selective) | Read only |
| `README.md` | Read / Write | Read only | Read only |
| `Plan.md` / `Triage.md` | Read / Write | Read only (mark `[x]`) | Read only |
| `./skills/**` | Read / Write / Create | Read only | Read only |
| `**/CLAUDE.md` (nested) | Read / Write / Create | Read only | Read only |
| `docs/*.md` | Read only | Read only | Read only |
| `docs/DEVIATIONS.md` | Read / Append | Read only | Read only |
| `Evaluation.md` | — | — | Read / Write |
| `journal/*.md` | Append (session record) | Append (session record) | Append (session record) |
| `src/`, `tests/` | — | Read / Write (within Boundary) | Read only |

`Discuss` and `Retro` are read-only over code. See
`.claude/rules/phase-authority.md` for their authority (Discuss may
write `Concept.md` + `docs/`; Retro may write only `journal/`).

## Mode Routing

Dormant until the user invokes a command.

| Command | Session Type | Action |
|---|---|---|
| `[/discuss] [topic]` | Discuss | Read `@skills/mode-discuss/SKILL.md` |
| `[/build] [concept]` | Planner | Read `@skills/mode-build/SKILL.md` |
| `[/modify] [feature or bug]` | Planner | Read `@skills/mode-modify/SKILL.md` |
| `[/migrate]` | Planner | Read `@skills/mode-migrate/SKILL.md` |
| `[/merge]` | Planner | Read `@skills/mode-merge/SKILL.md` |
| `[/evaluate]` | Evaluator | Read `@skills/mode-evaluate/SKILL.md` |
| `[/retro]` | Retro | Read `@skills/mode-retro/SKILL.md` |
| `start execution` | Generator | Auto-detect Plan.md or Triage.md |
| `start execution @plan.md` | Generator | Execute Plan.md explicitly |
| `start execution @triage.md` | Generator | Execute Triage.md explicitly |
| `check the latest run log` | (any) | Read `logs/latest.log`, diagnose, route to `[/modify]` |

On detecting a command, silently read the corresponding skill BEFORE responding.

**Note:** `[/modify]` handles BOTH feature/refactor work AND bug fixes.
When the request is "X is broken," Modify runs its bug-investigation
sub-flow (Triage + hypotheses); otherwise it runs the feature flow.
There is no separate `[/debug]` mode. See "Which mode?" in the README.

## Session Lifecycle

### Discuss Session (optional)
1. User invokes `[/discuss] [topic]`.
2. Read `Concept.md`, `Architecture.md`, `docs/` (incl. `docs/inbox.md`).
3. Discuss direction. Propose doc/Concept edits; apply only what the
   user confirms. Promote raw notes from `docs/inbox.md` into
   `Concept.md`/`docs/` where agreed.
4. Optionally commit doc changes: `docs: [summary]`. Write NO Plan.md,
   NO code. Recommend the next mode (`[/build]` or `[/modify]`).

### Planner Session
1. User invokes `[/build]`, `[/modify]`, `[/migrate]`, or `[/merge]`.
2. Ask Phase: interrogate user per loaded Mode Skill. For `[/merge]`,
   reverse-engineer an Architecture model of EACH source first. For
   `[/modify]` bug requests, open a `Triage.md` investigation.
3. Environment Audit (build/migrate/merge; modify if new deps).
4. Spec Phase: write/update core files (layered Architecture.md),
   README, skills, subdirectory `CLAUDE.md` if useful, docs/DEVIATIONS.md
   entries if any, Plan.md or Triage.md.
5. Git commit all work: `plan: [description]` (detailed message).
6. Append the Planner record to `journal/`. STOP.

### Generator Session
1. User types `start execution`.
2. Auto-detect Plan.md or Triage.md (or use explicit `@` reference).
3. Selective context load: Architecture Overview + ticket sections +
   skills + nested `CLAUDE.md` for touched dirs + reference docs +
   DEVIATIONS.md (if applicable).
4. Execute tickets. Default is sequential; if the work order uses
   `Parallel Group:` labels, fan out independent tickets to concurrent
   workers and fan in for commit + regression
   (`.claude/rules/parallel-execution.md`). Run commands capture to
   `logs/latest.log` (see `.claude/rules/run-logging.md`). Commit after
   each ticket on the main thread: `feat:` / `fix:`.
5. On TDD failure: retry up to 3 times. If still failing, stop session.
6. If user placed `[Halt here]` on a ticket: commit and stop.
7. When all tickets complete: append the Generator record to
   `journal/`. STOP.

### Evaluator Session (optional)
1. User types `[/evaluate]` after the Generator finishes.
2. Run the four audits (execution, document/concept consistency,
   simplicity/redundancy, context sufficiency) per the skill.
3. Write `Evaluation.md` with a clear verdict + prioritized fixes.
4. Append the Evaluator record to `journal/`. STOP. No commit.

### After Evaluation (User)
1. Run global tests / follow Evaluation.md's prioritized fixes.
2. Fill the **Feedback** block in the loop's `journal/` entry
   (rating + what went well + any instruction not followed).
3. If satisfied: delete Plan.md/Triage.md and Evaluation.md.
4. If not: `git reset` to the Planner commit and retry, or start a
   new Planner session to refine.

### Retro Session (optional)
1. User invokes `[/retro]`.
2. Read `journal/` across sessions (Tier-1 curated summaries). Surface
   recurring feedback and failure patterns. For loops flagged "bad",
   drill into the Tier-2 full trace in `journal/traces/*.jsonl`.
3. Recommend concrete framework/skill/rule changes. Write findings (a
   retro summary in `journal/`). No code changes.

### Session Journal (two tiers)
- **Tier 1 (`journal/*.md`):** agent-written curated summaries per loop
  + the user's feedback block. Primary artifact for `[/retro]`. Works in
  Claude Code and Cursor. See `.claude/rules/governance.md §6`.
- **Tier 2 (`journal/traces/*.jsonl`):** full raw transcripts (every
  tool call/decision), auto-archived by the `SessionEnd` hook in
  `.claude/settings.json`. Gitignored. Claude Code only. The agent never
  writes these by hand.

## Quick Reference

- Core principles → `.claude/rules/principles.md`
- Governance (git, security, logging, TDD, lifecycle) → `.claude/rules/governance.md`
- Run logging → `.claude/rules/run-logging.md`
- Phase authority & boundaries → `.claude/rules/phase-authority.md`
- Generator execution protocol → `.claude/rules/generator-protocol.md`
- Parallel execution (fan-out/fan-in) → `.claude/rules/parallel-execution.md`
- Task ticket format → `.claude/rules/task-ticket-format.md`
- Skill writing standard → `@skills/skill-template/SKILL.md`
