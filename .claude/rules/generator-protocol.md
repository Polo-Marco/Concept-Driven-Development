# Generator Execution Protocol

When the user types `start execution`, follow this protocol.

## Step 1: Detect Work Order

- If user specified a file (`start execution @plan.md` or
  `start execution @triage.md`), use that file.
- Otherwise, auto-detect:
  - If `Plan.md` exists → execute it.
  - If `Triage.md` exists → execute it.
  - If both exist → ask the user which to execute.
  - If neither exists → tell the user there is nothing to execute.

## Step 2: Load Context (selective)

Load context in this order:

1. Read `Architecture.md` **## Overview section only** → high-level
   project context. Self-contained snapshot of system + components.
2. Read the work order (`Plan.md` or `Triage.md`) → find the first
   unchecked `[ ]` ticket.
3. Read the Architecture.md sections listed in the ticket's
   **Architecture:** field (e.g. `API Surface`, `Data Models`).
   - If the field says `Full`, read the entire document.
   - Never read sections beyond the Overview unless requested.
4. Read the skill files listed in the ticket's **Skills to Load** field.
5. If the ticket has a **Reference Docs:** field, read each referenced
   doc in `docs/` AND read `docs/DEVIATIONS.md` to know which parts
   of the original spec have been superseded.
6. For each directory the ticket's **Boundary** touches, read the
   nearest subdirectory `CLAUDE.md` (if any) as read-only module
   context. Its conventions are binding for files in that directory.

`Concept.md` is NOT loaded by the Generator. The Architecture Overview
provides sufficient project context for execution.

## Step 3: Execute Tickets

Default execution is **sequential** — process tickets in order, one at a
time, per the steps below.

**Parallel groups (opt-in):** If the work order uses `Parallel Group:`
labels, follow `.claude/rules/parallel-execution.md`. In short: when you
reach a group whose `Depends On:` are all committed, re-verify the two
invariants on the main thread (pairwise-disjoint Boundaries; no
intra-group dependency), fan out one worker per ticket, then fan in —
run the full regression suite once and commit each ticket sequentially
on the main thread. Workers never commit. If a plan has no
`Parallel Group:` labels, ignore this and run sequentially.

The per-ticket steps below (3a–3f) apply to both modes — in a group they
run inside each worker (3a–3d) and on the main thread at fan-in
(3c retry, 3d self-review, 3e commit, 3f halt).

For each ticket, in order:

### 3a. Boundary Check
- Read the **Boundary** field. Only touch listed files.
- If you need files outside Boundary → stop session per
  `.claude/rules/phase-authority.md`.

### 3b. TDD Loop
- Write failing tests from the **Test Contract**. Run → confirm fail.
- Write application logic from **Spec** and loaded Skill patterns.
- Run tests → confirm pass.
- Run the **Run Command** for domain-wide test coverage. Run Commands
  capture output to `logs/latest.log` via `2>&1 | tee logs/latest.log`
  (see `.claude/rules/run-logging.md`), so a failure leaves a
  readable trail.

### 3c. Retry on Failure
- If tests fail after implementation, attempt to fix. **3 attempts max.**
- If still failing after 3 attempts: commit what you have with a
  message explaining what worked and what didn't. Stop the session.
  ```
  wip: extraction pipeline — 2/3 tests passing, test_extract_corrupt failing

  - extract_text() handles PDF and DOCX successfully
  - Corrupt file detection not triggering ExtractionError
  - Stopped after 3 fix attempts
  ```

### 3d. Self-Review
- Security: any hardcoded secrets?
- Boundary: any files touched outside Boundary?
- Simplicity & surgery (`.claude/rules/principles.md`): is this the
  minimum code for the ticket? Any speculative feature, single-use
  abstraction, or change to adjacent code that the ticket didn't ask
  for? Did you orphan any imports/symbols?
- Alignment: does code match the loaded Architecture sections and any
  nested `CLAUDE.md` conventions?
- Logging: if the ticket is flagged as an expensive/long-running
  pipeline, does it emit structured stage logs per
  `.claude/rules/governance.md` §3?
- Reference Docs: if a Reference Doc is listed, does the code respect
  it (or follow a logged deviation in `docs/DEVIATIONS.md`)?
- Skill compliance: every DO/DO NOT rule followed?

### 3e. Commit
- Mark ticket `[x]` in the work order.
- Git commit with a detailed, informative message.
- Move to the next ticket.

### 3f. Halt Check
- If the next ticket has `[Halt here]` (placed by the user):
  commit current work and stop the session.

## Step 4: Session Complete

When all tickets are done (or the session stops):

- Append the Generator record to this loop's `journal/` file (tickets
  executed, commit SHAs, any stops/retries, notable run-log findings)
  per `.claude/rules/governance.md §6`.

- If all tickets completed:
  ```
  Generator session complete. All [N] tickets executed.
  [summary of what was built]
  Ready for your evaluation. Run your global tests, then
  delete Plan.md/Triage.md if satisfied.
  ```

- If stopped early (failure or halt):
  ```
  Generator session stopped at Phase [N], Step [M].
  [what completed, what failed, why]
  You can: start a Planner session to refine, or
  git reset to the planner commit and retry.
  ```
