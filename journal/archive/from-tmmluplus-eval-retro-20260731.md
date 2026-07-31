# Imported Retro — tmmluplus eval-pipeline project — 2026-07-31

Covers loop `20260731-102218-loop` of that project — the **first live
run of v8.1.5 against a real endpoint and a real dataset**. Imported
into the framework repo per `MAINTENANCE.md` step 1 (Capture).
Predecessor: `journal/from-tmmluplus-eval-retro-20260730.md` (same
project, loop 1, four `build` runs against toy targets).

**Status: captured, not yet applied.** Nothing below has been shipped
into the template. Recommendations 1–3 are driver defects
(`.claude/driver/loop.py`); 4–7 are rule/doc changes.

---

Retro — 2026-07-31 — covering loop `20260731-102218-loop` (v8.1.5, first live test)

Scope: one `build` loop, the framework's first run against a real
endpoint and a real dataset. 21 driver-dispatched sessions, 9
iterations of 10, $32.85 of $50, 3 human restarts, 6 of 7 tickets
committed, ESCALATE at ticket 7. Evidence is `journal/20260731-102218-loop.md`,
`ledger.jsonl` (9 records), `events.jsonl` (105 events), `Evaluation.md`,
`git log`, and `.claude/driver/loop.py`.

## What worked

1. **Plan-time probing beat plan-time guessing.** The Planner resolved
   Concept Open Question 1 by running the route twice in `/tmp` against
   the live endpoint before writing a ticket. Four findings that would
   each have cost a replan were measured instead of assumed: the
   `lighteval==0.13.0` hard pin (0.13 rewrote the task API onto
   `inspect_ai`), `--max-samples` applying *per task*, `samples` having
   to come from the details parquet, and
   `lighteval tasks list --custom-tasks` silently reporting zero. **The
   loop finished with 0 replans of a 2-replan budget.**

2. **A security finding landed at plan time, not post-mortem.** lighteval
   writes the raw API key into `config_general.model_config.api_key` of
   its own results JSON — verified by grep against the live key. Caught
   before `results/` (a provenance tree kept on purpose) could carry it,
   and it produced three concrete ticket constraints: redact-on-copy, a
   `0600` model config outside the repo instead of a CLI arg visible to
   `ps`, and a whole-tree key scan in ticket 7. Governance §2 worked as
   a *design input*, which is the only time it is cheap.

3. **The four deterministic gates fail closed, and it showed on the first
   run.** The 02:26:06 start recorded `FAIL endpoint credentials present`
   and `FAIL endpoint answers a 1-token call` and refused to plan
   anything. Fifteen seconds later, with `.env` filled, all four passed.
   Nothing was spent on a run that could not have produced a number.

4. **Contract review earned its cost.** Two `contract_revise` rounds
   before `contract_ok` — 44 minutes and 6 sessions of planning, zero
   Generator tokens burned on a plan that would not have satisfied the
   contract.

5. **The Evaluator did provenance work no deterministic check can do.**
   It recomputed `acc=0.7` from the raw parquet rather than reading
   `latest.json`, and it proved the ticket's assertions non-vacuous by
   mutation — *"moving `unparseable_rate` into `metrics{}` in a /tmp copy
   gives 3 failed, 4 passed"*. That is exactly the "deterministic is
   necessary, not sufficient" clause of `loop-protocol.md` §7 doing its
   job, and it is what found the forged record.

6. **ESCALATE routing was correct.** Faced with six green criteria the
   loop refused to call it done, because one of them was earned by a
   record no harness wrote. A loop that stops rather than banking an
   unearned pass is the behaviour the whole design is for.

7. **Driver resume was sound in all three interruptions** — from the
   human gate ($0, no re-plan, no second contract review), from
   mid-ticket (idempotent re-dispatch), and from an ESCALATE (straight
   back to Step 7). Crash recovery is not theoretical any more.

## Recurring problems (with evidence)

### 1. A ticket could write the evidence for criteria it did not produce — and did

`results/` appears as a whole-directory Boundary entry on tickets 2, 5,
6 and 7 (`Plan.md:172, 453, 516, 589`). Ticket 2's job was a schema
module and its unit tests; its Run Command is plain
`uv run pytest tests/ -v`. It nevertheless had write access to
`results/tmmluplus/`, and during that session `write_result()` was run
against the default results dir, landing
`results/tmmluplus/20260731T033740Z.json` **and** `latest.json` with the
`_make_result()` fixture values (`model='m'`, `endpoint='http://x/v1'`,
`acc=0.6`, `unparseable_rate=0.1`).

Consequence, straight from `ledger.jsonl`: iteration 2's gate was six
FAILs. **Iteration 3 — the very next ticket — reported
`ok samples >= 10 (actual=10)`, `ok acc > 0 (actual=0.6)`,
`ok unparseable_rate <= 0.5 (actual=0.1)`.** Three of six criteria went
green four iterations before any harness existed, and stayed green
through iterations 4 and 5 until the real run at iteration 6 overwrote
`latest.json` with `acc=0.7`. The orphan then survived into
`aggregate-check.json` as `rows=2` and into `summary.csv` as a
fabricated row, contaminating criterion 6 through iterations 7, 8 and 9.

The hook is not at fault — it enforced the Boundary it was given. The
Boundary was wrong. Note that ticket 2 *does* legitimately produce
`results/test-summary.json` via the `conftest.py` hook, so the fix is
not "remove `results/`" but "name the file, not the tree".

### 2. `final-pass` cadence let forged evidence live for five tickets

Cadence was `final-pass`, so `phase_iterate` (`loop.py:854`) took the
`PASS — deterministic gate clean; LLM audit deferred` branch for six of
seven tickets. **Exactly one ticket in this loop received an LLM audit,
and it was the one that failed.** The forged record entered at iteration
3 and was not looked at by anything with provenance judgement until
iteration 8 — five tickets and roughly 30 minutes of committed work
later. Every intervening commit message carries `evidence:` lines quoting
numbers that were never earned (e.g. `4bbdae5`, `3427819`, `ad6d7fa`).

### 3. RETRY dispatches the ticket body and nothing else — so retries cannot converge

`loop.py:811-815` builds the Generator prompt from `body` alone. The
verdict's `reason` and `evidence` are never passed. At Step 7 this
produced three consecutive Generator sessions of **84s, 74s and 80s that
changed zero bytes** — `results/aggregate-check.json` was md5-identical
(`46006ba9…`) before and after, and `git status` showed no change but the
driver's own `verdict.json` unlink. The workers were not lazy; they were
told "execute Step 7", found the suite green and the deliverable
written, and correctly concluded there was nothing to do.

Retrying a ticket verbatim can only help when the fault is
nondeterministic. Here the fault was a stale artifact the ticket never
mentions, so every attempt was byte-identical. **This is a driver defect,
not a worker defect.**

### 4. A zero-diff session still spends an attempt

Nothing in `phase_iterate` compares the tree before and after a
Generator dispatch. Attempts 2 and 3 at Step 7 ran, cost two Sonnet
sessions plus two ~7-minute Opus audits, and could not have succeeded —
the outcome was determined at the 80-second mark of attempt 1. The
restart experiment measured the price of one such cycle at **$0.60**;
the two that ran to completion inside the loop were substantially more.

### 5. The regression guard treats unearned green as a baseline

`st["criteria_green"]` (`loop.py:838-841`) records whatever the gate
reports, with no notion of provenance. Once the fixture record turned
`rows` green at `actual=2`, the correct action — deleting it — takes
`rows` to 1 and, had the driver been running, would have registered as
`criteria regression: rows` and forced a RETRY. **Cleaning up forged
evidence was punishable by the guard meant to protect the loop.** The
manual cleanup only escaped this because it happened outside the driver.

### 6. Documented journal behaviour does not exist

`CLAUDE.md` states "The driver appends loop records (iterations,
verdicts, ledger summary)". `grep -n journal .claude/driver/loop.py`
returns comments and one `housekeeping_reminder` string — no write. The
loop record's `## Generator` and `## Evaluator` sections are still
`_pending_`, and the `## Feedback` block is empty. What saved this retro
is that the control tower hand-wrote 260 lines of record; a loop run
without one would have left only the ledger.

### 7. The loop is not closed

Still present in the worktree: `Plan.md`, `Evaluation.md`, `Goal.md`,
`goal.json`, `ledger.jsonl`, `loop-state.json`, `events.jsonl`. Branch
`loop/build-the-pipeline-skeleton-and-prove-it` is unmerged — `master` is
still at `a4987db`, so none of the six committed tickets exist on the
main line. Stale `Goal.md` and `goal.json` are also sitting untracked in
the primary tree from the mid-loop budget edit.
`loop-protocol.md` already says three retros in a row flagged unclosed
loops; this is the fourth.

### 8. Restarts are charged to the iteration budget

`st["iteration"] += 1` fires on every dispatch (`loop.py:798`), so the
mid-ticket restart at 03:34 made Step 1 consume iterations 1 *and* 2, and
the escalation restart consumed iteration 9. The loop ended at **9/10
iterations with a ticket still open** — not because the work needed nine,
but because three human restarts cost three. Budgets are denominated in
dispatches while the user reasons about them in tickets.

## Recommendations

Ordered by value. 1–3 are the ones that change outcomes.

1. **Pass the verdict into the retry.** `loop.py` `phase_iterate`: on
   `attempt > 1`, append the previous verdict's `reason` and `evidence`
   to the Generator dispatch prompt. → fixes problem 3. Without this,
   `RETRY ≤3` is a budget line item rather than a mechanism.

2. **Treat a zero-diff Generator session as a protocol failure.** Snapshot
   `git status --porcelain` plus tracked-file state before and after each
   dispatch; if nothing changed and the verdict is RETRY, ESCALATE
   immediately instead of spending attempts 2 and 3. → fixes problem 4.
   Pairs with 1: after 1, a no-op means the worker read the feedback and
   still could not act, which is precisely a human's problem.

3. **Audit the first green, not just the last ticket.** In `phase_iterate`,
   when cadence is `final-pass`, also dispatch the Evaluator on any
   iteration where `now_green - prev_green` is non-empty. The moment a
   criterion first goes green is the moment provenance is worth paying
   for. → fixes problem 2, and would have caught the forged record at
   iteration 3 instead of iteration 8, for the price of one extra Opus
   audit.

4. **Name the file, not the tree, in Boundary.** Add to the Planner
   Self-Check in `.claude/rules/task-ticket-format.md`: *for every
   `goal.json` criterion `source`, only a ticket whose Run Command
   actually writes that file may list it in its Boundary — and it lists
   the file, not its parent directory.* Ticket 2's `results/` should have
   read `results/test-summary.json`. → fixes problem 1 at the layer where
   it was introduced. This sits directly beside the existing
   "does some ticket's Run Command actually WRITE each criterion's source
   file?" check; it is that check's missing converse.

5. **Say that green is provisional until audited.** One line in
   `loop-protocol.md` §7: a criterion recorded green by
   `check_criteria()` alone has met a threshold, not earned it, and the
   regression guard inherits that uncertainty. With recommendation 3 the
   window narrows to a single iteration; the caveat should still be
   written down rather than rediscovered.

6. **Fix the journal claim.** Either have the driver append a per-loop
   record at `done` (ledger summary + verdicts — the data already
   exists), or correct `CLAUDE.md` and `governance.md` §6 to say the
   user/control tower writes it. Simplicity First favours the doc fix:
   `ledger.jsonl` already *is* the machine record. What must not stay is a
   promise nothing keeps.

7. **Note the restart cost.** One line in `loop-protocol.md`: every driver
   restart consumes an iteration, so size `max_iterations` with headroom
   for interruptions. Do not change the counter — a dispatch cap that a
   restart can reset is a cap that a crash loop can defeat.

## For the user (habits)

- **Set budgets with headroom at the Ask phase.** Both mid-loop raises
  ($25→$50, 4h→8h) required killing tmux and restarting, because `cfg` is
  loaded once at driver startup (`loop.py:1245`). The first restart was
  free; the second cost an iteration and re-ran a partially-complete
  ticket. You chose tight budgets deliberately, which is the right
  instinct for a first live run — but the cost of being wrong is a
  restart, not an adjustment.

- **Killing the interruption-3 experiment at 80 seconds was the best call
  of the loop.** The answer ("does the driver resume from an ESCALATE?
  yes. Does it then fix anything? no.") was fully determined by the first
  zero-diff session. Letting it run to a third escalation would have cost
  $10–15 of the $17.75 remaining for information you already had. You
  spent $0.60. Keep doing that.

- **Close the loop before starting the next one.** Merge the branch or
  decide not to, fill the Feedback block, and delete the ephemeral
  artifacts. Right now six tickets of genuine, verified work exist only
  on an unmerged branch, and `loop-state.json` still says
  `phase: iterate, current_ticket: Phase 3, Step 7` — a future `loop.py`
  invocation in that tree will try to resume a loop you finished by hand.

- **You left one thing deliberately unfixed and said so** — nothing asserts
  that *every* record under `results/<bench>/` has a matching `raw/`
  provenance directory. That judgement was right: it is a new requirement,
  not a cleanup, and hand-editing it in would have hidden the framework
  defect this retro is built on. It belongs in the next plan.
