# Concept-Driven Development (CDD) 6.2

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

## Pipeline Architecture

```
Planner → Generator → Evaluator (optional) → User (final sign-off)
```

- **Planner Session:** Interrogate the user, audit environment, design
  the system, write core files, generate skills, write Plan.md/Triage.md.
  Commit at session end. Full authority over core files.
- **Generator Session:** Execute task tickets mechanically using TDD.
  Selective Architecture loading. Commit after each ticket.
- **Evaluator Session (optional):** Independently audit the output —
  run it, cross-check Concept/Architecture/docs/code, audit simplicity,
  flag missing context — and write `Evaluation.md` with a verdict.
  Cannot modify code.
- **User:** Final evaluator. Reviews, runs global tests, deletes the
  work order when satisfied.

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
| `Plan.md` / `Triage.md` | Read / Write | Read only (mark `[x]`) | Read only |
| `CHANGELOG.md` | Read / Write | Append only | Read only |
| `./skills/**` | Read / Write / Create | Read only | Read only |
| `**/CLAUDE.md` (nested) | Read / Write / Create | Read only | Read only |
| `docs/*.md` | Read only | Read only | Read only |
| `docs/DEVIATIONS.md` | Read / Append | Read only | Read only |
| `Evaluation.md` | — | — | Read / Write |
| `src/`, `tests/` | — | Read / Write (within Boundary) | Read only |

## Mode Routing

Dormant until the user invokes a command.

| Command | Session Type | Action |
|---|---|---|
| `[/build] [concept]` | Planner | Read `@skills/mode-build/SKILL.md` |
| `[/modify] [feature]` | Planner | Read `@skills/mode-modify/SKILL.md` |
| `[/debug] [issue]` | Planner | Read `@skills/mode-debug/SKILL.md` |
| `[/migrate]` | Planner | Read `@skills/mode-migrate/SKILL.md` |
| `[/merge]` | Planner | Read `@skills/mode-merge/SKILL.md` |
| `[/evaluate]` | Evaluator | Read `@skills/mode-evaluate/SKILL.md` |
| `start execution` | Generator | Auto-detect Plan.md or Triage.md |
| `start execution @plan.md` | Generator | Execute Plan.md explicitly |
| `start execution @triage.md` | Generator | Execute Triage.md explicitly |

On detecting a command, silently read the corresponding skill BEFORE responding.

## Session Lifecycle

### Planner Session
1. User invokes `[/build]`, `[/modify]`, `[/debug]`, `[/migrate]`, or `[/merge]`.
2. Ask Phase: interrogate user per loaded Mode Skill. For `[/merge]`,
   reverse-engineer an Architecture model of EACH source first.
3. Environment Audit (build/migrate/merge; modify if new deps).
4. Spec Phase: write core files (layered Architecture.md), skills,
   subdirectory `CLAUDE.md` if useful, docs/DEVIATIONS.md entries if
   any, Plan.md or Triage.md.
5. Git commit all work: `plan: [description]`.
6. STOP.

### Generator Session
1. User types `start execution`.
2. Auto-detect Plan.md or Triage.md (or use explicit `@` reference).
3. Selective context load: Architecture Overview + ticket sections +
   skills + nested `CLAUDE.md` for touched dirs + reference docs +
   DEVIATIONS.md (if applicable).
4. Execute tickets sequentially. Commit after each: `feat:` / `fix:`.
5. On TDD failure: retry up to 3 times. If still failing, stop session.
6. If user placed `[Halt here]` on a ticket: commit and stop.
7. When all tickets complete: STOP.

### Evaluator Session (optional)
1. User types `[/evaluate]` after the Generator finishes.
2. Run the four audits (execution, document/concept consistency,
   simplicity/redundancy, context sufficiency) per the skill.
3. Write `Evaluation.md` with a clear verdict + prioritized fixes.
4. STOP. No commit.

### After Evaluation (User)
1. Run global tests / follow Evaluation.md's prioritized fixes.
2. If satisfied: delete Plan.md/Triage.md and Evaluation.md.
3. If not: `git reset` to the Planner commit and retry, or start a
   new Planner session to refine.

## Quick Reference

- Core principles → `.claude/rules/principles.md`
- Governance → `.claude/rules/governance.md`
- Phase authority & boundaries → `.claude/rules/phase-authority.md`
- Generator execution protocol → `.claude/rules/generator-protocol.md`
- Task ticket format → `.claude/rules/task-ticket-format.md`
- Skill writing standard → `@skills/skill-template/SKILL.md`
