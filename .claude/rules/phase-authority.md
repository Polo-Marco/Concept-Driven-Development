# Phase-Based Authority & Boundary Rules

## Core Principle

Authority is determined by the active session type, not the model.
The Planner Session has full authority over core files.
The Generator Session has zero authority over core files.
The Evaluator Session has zero authority over everything except
`Evaluation.md`.
The Discuss and Retro Sessions never touch code (see below).

## File Authority Matrix

| File | Planner | Generator | Evaluator |
|---|---|---|---|
| `Concept.md` | Read / Write | **Read only** | **Read only** |
| `Architecture.md` | Read / Write | **Read only** (selective) | **Read only** |
| `README.md` | Read / Write | **Read only** | **Read only** |
| `Plan.md` / `Triage.md` | Read / Write | **Read only** (mark `[x]`) | **Read only** |
| `./skills/**` | Read / Write / Create | **Read only** | **Read only** |
| `**/CLAUDE.md` (nested) | Read / Write / Create | **Read only** | **Read only** |
| `docs/*.md` (originals) | **Read only** | **Read only** | **Read only** |
| `docs/DEVIATIONS.md` | Read / Append | **Read only** | **Read only** |
| `Evaluation.md` | — | — | Read / Write |
| `journal/*.md` | Append | Append | Append |
| `src/`, `tests/` | — | Read / Write (within Boundary) | **Read only** (may run) |

v8.0 loop additions: `Goal.md`, `goal.json`, `ledger.jsonl`,
`loop-state.json`, `events.jsonl` are **read-only to ALL sessions**
(user- or driver-owned; hook-enforced). `verdict.json` is
Evaluator-writable only. In loop mode, git commits are DRIVER-only —
no session commits, including the Planner.

There is no `CHANGELOG.md` — git history is the changelog.
`docs/` originals are user-maintained; only the user (and the Discuss
Session, with confirmation) edits them.

## Discuss & Retro Session Authority

These two sessions exist to *think*, not to build. Neither touches
`src/`, `tests/`, `Plan.md`, or `Triage.md`.

| File | Discuss | Retro |
|---|---|---|
| `Concept.md` | Read / Write (with user confirmation) | **Read only** |
| `docs/*.md`, `docs/inbox.md` | Read / Write (with user confirmation) | **Read only** |
| `docs/DEVIATIONS.md` | Read / Append | **Read only** |
| `Architecture.md` | **Read only** | **Read only** |
| `README.md`, `skills/`, `**/CLAUDE.md` | **Read only** | **Read only** |
| `journal/*.md` | **Read only** | Read / Write (retro summary) |
| `src/`, `tests/` | **Read only** | **Read only** |

- **Discuss** is the only agent session (besides the user) allowed to
  edit `docs/`. It applies edits only after the user confirms them, and
  it writes NO `Plan.md` and NO code.
- **Retro** reads `journal/` to surface patterns; it may write a retro
  summary into `journal/` but changes nothing else.

## Monitor Session Authority (v8.0)

The Monitor (`.claude/agents/cdd-monitor.md`) is spawned by the driver
while a trial runs. It may READ the trial log, metrics files, and
process/GPU state. It writes NOTHING and kills NOTHING — it returns a
classification JSON and stops. All action on its verdict belongs to
the driver.

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

### Parallel Workers (subagents)

When the Generator fans out a Parallel Group
(`.claude/rules/parallel-execution.md`), each worker is a Generator
worker and inherits Generator authority exactly:

- It may write ONLY within its own ticket's `Boundary` (which is disjoint
  from every sibling's), and read only that ticket's selective context.
- It obeys every Generator Boundary Rule and Prohibition below. If it
  would breach them, it stops and reports — it does not improvise.
- It NEVER commits, NEVER marks tickets `[x]`, NEVER modifies core
  files, and NEVER spawns further workers. Only the main thread commits.

## Generator Prohibitions

During a Generator Session, the agent must NEVER:
- Propose architectural solutions.
- Work around a spec gap.
- Add TODO placeholders as a substitute for stopping.
- Create files outside the Boundary.
- Modify Concept.md, Architecture.md, README.md, Plan.md/Triage.md,
  skills, any `CLAUDE.md` (root or nested), or any file under `docs/`.
- Read Architecture sections beyond Overview + the ticket's
  **Architecture:** field (selective loading is mandatory). Nested
  `CLAUDE.md` files for touched directories ARE loaded as read-only
  context.
- Work around a PreToolUse denial. A denial means STOP and report —
  the hook is the authority matrix, mechanically enforced.

## Evaluator Prohibitions

During an Evaluator Session, the agent must NEVER:
- Modify code, tests, skills, or core files.
- Edit `docs/` (including `DEVIATIONS.md`).
- Commit anything.
- Make architecture decisions — only flag gaps in `Evaluation.md`.
