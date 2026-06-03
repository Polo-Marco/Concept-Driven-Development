# Phase-Based Authority & Boundary Rules

## Core Principle

Authority is determined by the active session type, not the model.
The Planner Session has full authority over core files.
The Generator Session has zero authority over core files.
The Evaluator Session has zero authority over everything except
`Evaluation.md`.

## File Authority Matrix

| File | Planner | Generator | Evaluator |
|---|---|---|---|
| `Concept.md` | Read / Write | **Read only** | **Read only** |
| `Architecture.md` | Read / Write | **Read only** (selective) | **Read only** |
| `Plan.md` / `Triage.md` | Read / Write | **Read only** (mark `[x]`) | **Read only** |
| `CHANGELOG.md` | Read / Write | **Append only** | **Read only** |
| `./skills/**` | Read / Write / Create | **Read only** | **Read only** |
| `**/CLAUDE.md` (nested) | Read / Write / Create | **Read only** | **Read only** |
| `docs/*.md` (originals) | **Read only** | **Read only** | **Read only** |
| `docs/DEVIATIONS.md` | Read / Append | **Read only** | **Read only** |
| `Evaluation.md` | — | — | Read / Write |
| `src/`, `tests/` | — | Read / Write (within Boundary) | **Read only** (may run) |

`docs/` originals are user-maintained. Only the user edits them.

## Generator Boundary Rules

During a Generator Session, the agent MUST stop the session if ANY of
these are true:

1. The task requires creating a file, endpoint, component, or DB table
   not in `Architecture.md`.
2. The task requires modifying a file outside the ticket's **Boundary**.
3. The test contract is ambiguous or missing a case encountered.
4. Two parts of the spec contradict each other.
5. A dependency or tool is needed that is not in the tech stack.
6. The code requires an architectural decision not already documented.
7. A Reference Doc and the spec contradict, with no entry in
   `docs/DEVIATIONS.md` resolving the conflict.

**On stop:** Commit progress so far with a descriptive message explaining
what was completed and what failed. The user can then start a Planner
session to resolve the gap, or `git reset` and retry.

## Generator Prohibitions

During a Generator Session, the agent must NEVER:
- Propose architectural solutions.
- Work around a spec gap.
- Add TODO placeholders as a substitute for stopping.
- Create files outside the Boundary.
- Modify Concept.md, Architecture.md, Plan.md/Triage.md, skills, any
  `CLAUDE.md` (root or nested), or any file under `docs/`.
- Read Architecture sections beyond Overview + the ticket's
  **Architecture:** field (selective loading is mandatory). Nested
  `CLAUDE.md` files for touched directories ARE loaded as read-only
  context.

## Evaluator Prohibitions

During an Evaluator Session, the agent must NEVER:
- Modify code, tests, skills, or core files.
- Edit `docs/` (including `DEVIATIONS.md`).
- Commit anything.
- Make architecture decisions — only flag gaps in `Evaluation.md`.
