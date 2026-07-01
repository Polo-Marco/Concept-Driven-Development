# Parallel Generator Execution (fan-out / fan-in)

Sequential generation is slow when a plan contains several substantial,
**independent** tickets. This rule lets the Generator build them
concurrently — without sacrificing TDD integrity or git safety.

## Who decides what runs in parallel

**The Planner decides, at plan-time. The Generator only executes.**

Deciding "can these tickets run at once?" requires understanding
cross-ticket data and file dependencies — an architectural judgment that
belongs to the Planner, not the mechanical Generator. The Planner
declares parallelism with two ticket fields (see
`.claude/rules/task-ticket-format.md`):

- **`Depends On:`** — ticket IDs that must complete first.
- **`Parallel Group:`** — a label (e.g. `A`); tickets sharing a label
  run concurrently.

If a plan uses no `Parallel Group:` labels, the Generator runs fully
sequentially (default, backward-compatible). Parallelism is opt-in.

## The two hard invariants

A group is only safe to run in parallel if BOTH hold. The Generator
re-verifies them on the main thread before fanning out:

1. **Disjoint Boundaries.** No two tickets in a group share any file or
   directory in their `Boundary`. This is what prevents file-write
   races — each worker owns a private slice of the tree.
2. **No intra-group dependency.** No ticket in the group lists another
   group member in its `Depends On:`, and no member's `Output` is
   another member's `Input`.

If either check fails, the Generator does NOT parallelize that group:
it warns and falls back to sequential execution for those tickets.

Additionally, **only the main thread commits.** Workers write code and
tests; they never `git commit`. This prevents git races.

## Execution: fan-out / fan-in

For a Parallel Group whose `Depends On:` are all satisfied (committed):

### Fan-out
Dispatch one worker per ticket in the group, concurrently
(Claude Code: a subagent via the Task tool; Cursor: a parallel agent).
Each worker receives ONLY:
- its single ticket,
- selective context for that ticket (Architecture Overview + the
  ticket's `Architecture:` sections + `Skills to Load` + `Reference
  Docs` + `docs/DEVIATIONS.md` if applicable + nested `CLAUDE.md` for
  its Boundary).

Each worker:
- runs the TDD loop for its ticket (write failing tests → implement →
  run its `Run Command`, teeing to a per-ticket log
  `logs/run-<phase>-<step>.log` to avoid clobbering);
- stays strictly within its `Boundary`;
- does NOT commit, does NOT mark the ticket `[x]`, does NOT touch core
  files;
- returns: pass/fail, a short summary, the list of files it wrote, and
  its stop reason if it stopped (see Failure handling).

### Fan-in (main thread, after all workers return)
1. Run the **full domain regression suite** once
   (`2>&1 | tee logs/latest.log`).
2. **If green:** commit each ticket in the group separately, in ticket
   order — mark `[x]`, `git commit` with a detailed per-ticket message.
3. **If red:** attribute failures to the responsible ticket(s). Each
   failing ticket enters the standard 3-attempt fix loop
   (`.claude/rules/generator-protocol.md §3c`) **on the main thread**,
   one at a time. Commit tickets that are green; if a ticket still fails
   after 3 attempts, commit it WIP and stop the session.
4. Perform the self-review checks (`generator-protocol.md §3d`) per
   ticket before its commit.

## Failure & halt handling

- **A worker stops** (needs an architectural decision, hits a spec gap,
  or would breach its Boundary — see `phase-authority.md` Generator
  Boundary Rules): the main thread cancels/ignores incomplete siblings'
  results, commits any group tickets that independently completed AND
  keep the suite green, then stops the session, reporting which ticket
  stopped and why. Resolve via a new Planner session or `git reset`.
- **`[Halt here]`** placed on any ticket in a group: finish and commit
  the current group, then stop before the next group.
- **Green State Check** (`mode-modify` / `mode-merge`): runs once on the
  main thread before the first group — never inside workers.

## Subagent authority

A worker is a Generator worker: it inherits Generator authority
(`.claude/rules/phase-authority.md`). It may read the selective context
above and write ONLY within its ticket's `Boundary`. All Generator
prohibitions apply. Workers never modify core files, never commit, and
never spawn further workers.

## Scope guard (anti-over-engineering)

Parallelism costs tokens — each worker reloads context cold. Use it only
when a group has multiple genuinely independent, non-trivial tickets.
Small plans, tightly-coupled tickets, and single-file changes run
sequentially. The Planner sizes this; when in doubt, don't group.
