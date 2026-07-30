# Retro — 2026-07-13 (second) — the delegated loop (`20260713-154020-modify`)

Scope: the "loop engineering" run — one Opus **Planner** session that dispatched a
**Sonnet** subagent as Generator and an **Opus 4.8** subagent as Evaluator, all inside a
single session. Question asked: *is the Planner's plan and control of the sub-agents
working correctly, and are there latent errors?*

Grounded in the Tier-2 trace
(`journal/traces/20260713-171112-6501e312-….jsonl` — the loop and this retro share a
session id), `Evaluation.md`, `Plan.md`, and `git log`. Where the journal and the trace
disagree, the trace wins.

**Headline: the output is sound; the control structure is not.** Every artifact this loop
produced holds up — I re-checked the Evaluator's checkable claims and they are true. But
the mechanism that produced them has five defects, one of which already fired, and the
framework's entire safety model turned out to be *prose in a prompt* rather than anything
enforced.

## What worked (keep)

1. **Git authority held.** All three commits (`e2c8048`, `8936dae`, `20e87d8`) were issued
   from the main thread — visible as `git commit` heredocs in the main thread's own bash
   history in the trace. Neither worker ran a git write command. `parallel-execution.md`'s
   "only the main thread commits" survived contact with a real fan-out.
2. **The Sonnet worker was a good Generator.** Boundaries held exactly (`8936dae` →
   `viz.py`/`test_viz.py`; `20e87d8` → `cli.py`/`test_cli_teacher.py`). The diff is net
   **-6 lines in `viz.py` while gaining a capability**; 325 → 330 tests, no stops, no
   retries. Model tier was not the weak link — the *spec* was.
3. **The Opus Evaluator did real auditing, not a rubber stamp.** It reconstructed the
   pre-fix package into `/tmp/oldsrc` and ran the *new* tests against the *old* code to
   prove they were not false-confidence (they fail, and the traceback originates inside
   `_teacher_doc_ids`, not the store check) — that is precisely the proof the previous
   loop's P2 demanded. It also proved the export-gate HTML byte-identical (`cmp` clean,
   68,889 B) rather than assuming it. Neither check was asked for in its prompt.
4. **The Planner disclosed its own error unprompted** — in `8936dae`'s commit message, in
   the journal, and in the Evaluator's brief. This retro is only possible because of that.

## Defects in the control structure (with evidence)

### 1. The three phases collapsed into one context — and that is what let the bad spec through

CDD defines Planner / Generator / Evaluator as **sessions** with different authority.
Here all three ran inside one Opus session that held git. The Planner never `STOP`ped as
the lifecycle requires, and the user never typed `start execution` — the Planner
self-triggered its own Generator. So the human approval gate between plan and execution
(the moment `[Halt here]` exists for) was skipped.

**This is not theoretical; it already fired.** Step 1's spec told the Generator to derive
`doc_ids` from the *post-limit* selection — circular, therefore **unsatisfiable**. The
worker improvised (`rows_with_orient_loaded()`) instead of stopping, which
`phase-authority.md` Boundary Rules 3/4/6 forbid. And then **the same context that wrote
the impossible spec adjudicated the breach and kept the improvisation** — including
editing `src/tcocrai/viz.py` from the main thread to simplify it (trace: `Edit` on
`viz.py`, `MAIN`, between the two commits). A Planner has *zero* authority over `src/`.
An independent Generator session would have stopped and forced a new Planner cycle. Fusing
the roles removed the only party whose job was to refuse.

### 2. The workers had no sandbox — only good manners

Both subagents were dispatched as `subagent_type: "general-purpose"`, which carries the
full toolset (`*`). Every constraint that made this loop safe —
*"NEVER run `git commit`"*, *"NEVER modify core files"*, *"stay inside each ticket's
Boundary"* — existed **only as prose inside the prompt**. A Sonnet worker with Write and
Bash had the raw ability to commit, to rewrite `Architecture.md`, or to `git reset`. It
didn't. Nothing stopped it. The framework's authority matrix is currently an honor system
executed by the least-capable model in the loop.

### 3. The per-ticket commit gate did not actually gate anything

`generator-protocol.md §3e` is: execute ticket → self-review → **commit** → next ticket.
What happened: **one** dispatch executed *both* tickets, and the main thread committed them
afterwards, 20 seconds apart (`8936dae` 15:52:39, `20e87d8` 15:52:59). So Step 2 was
written against un-reviewed, un-committed Step 1 code. Nothing broke — but the 3-attempt
retry loop and `[Halt here]` both assume a committed checkpoint to fall back to, and there
was none. The plan declared no `Parallel Group`, so this ran the fan-in shape without the
plan authorizing it.

### 4. The Evaluator's independence is partly synthetic — the audited party supplied its search space

The prompt opens with "You are an INDEPENDENT auditor… Trust nothing" and then, under
**"Known context you should weigh"**, hands over the Planner's own framing of the
improvisation *and names the suspicion targets*: does `rows_with_orient_loaded()` "smuggle
IO back in / mutate shared state"? and "look hard for an actual behavioral bug (e.g. limit
reached mid-doc, missing GT, malformed `crop_rel`)".

Compare the deliverable: the Evaluator's headline new finding is **P2 — the seam's purity
is nominal because a side-effecting generator mutates the dict it was handed**, and its bug
hunt clears *exactly* limit-mid-doc, missing GT, and malformed `crop_rel`. That is the
prompt's own list, handed back. The work inside the frame is excellent; the frame was drawn
by the party under audit. An auditor told where to look will mostly find things there — and
whatever the Planner did *not* think to flag got a proportionally thinner look.

### 5. The subagents left no trace, so their compliance is unverifiable

`grep -c '"isSidechain":true'` over the archived transcript → **0**. The SessionEnd hook
captured the main thread only; neither worker's transcript exists anywhere. Every claim
about them — *"ran no git commands"*, *"touched no core files"*, *"3 attempts max"* — is
**self-reported by the worker and transcribed by the Planner**. Tier 2 exists precisely so
a bad loop can be dissected; for the delegated 90% of this loop, there is nothing to
dissect. (Corroborating evidence happens to exist here — the commits are all main-thread,
`git status src/` is clean, and `Evaluation.md` is on disk to cross-check the journal
against. I did check: the journal's Evaluator section is faithful, if softer. But the
*structure* has the audited party holding the auditor's pen.)

### 6. A worker died silently and the only fix was a nag

Evaluator attempt #1 "died mid-run without writing anything" — noticed only because the
deliverable file was absent. The retry prompt's remedy was to add *"Work efficiently and
land the deliverable… before you run out of room."* That treats the symptom. The likely
cause is context exhaustion in a single subagent running four audits against real data.

## Recommendations (minimal, at the right layer)

1. **Convert the authority matrix from prose into enforcement.** Define
   `.claude/agents/cdd-generator.md` and `.claude/agents/cdd-evaluator.md` with restricted
   tool lists, and add a `PreToolUse` hook (you already have the hooks dir) that hard-denies
   `git commit|git add|git reset|git checkout` and any write outside the dispatched ticket's
   Boundary. This is the single highest-value change here: it makes defect #2 impossible
   rather than merely unlikely, and it costs one hook script.
2. **One dispatch per ticket, and commit between them.** Restores §3e's checkpoint, the
   retry loop's rollback target, and `[Halt here]`. Cheap: it is a loop around the existing
   dispatch.
3. **Withhold the Planner's self-assessment from the Evaluator.** Give it the diff, the
   plan, and the verdict criteria — not "here is what I think went wrong and where to look."
   If you want the improvisation caught, ask the neutral form: *"Is any part of this diff
   not specified by the plan? If so, judge it."* Let it find the target itself. Keep the
   protocol-level instructions (run the four audits, write `Evaluation.md`); drop the
   §"Known context you should weigh" block.
4. **Capture the workers.** Have each subagent write its own run record (files touched, git
   commands run = none, attempts) to `journal/traces/`, or extend the archive hook to
   sidechains. Until then, treat every worker self-report as unaudited.
5. **Keep the Planner out of `src/`.** If a worker's code needs simplifying, that is a
   Generator self-review step — dispatch it back, or accept it and file it as a finding.
   Do not let the plan's author hand-edit the code that reveals the plan was wrong.
6. **Add a satisfiability check to the Planner self-check** (`task-ticket-format.md`). The
   Evaluator named this itself and it is the right diagnosis: the existing checklist reviews
   tickets for *completeness*, never for *"can this instruction actually be executed?"*.
   One bullet: *"For each Spec step: can it be executed with only the inputs available at
   that point? A circular or unsatisfiable step leaves the Generator no legal move but to
   stop."*

## Still open from this morning's retro (unchanged)

- **`Plan.md` and `Evaluation.md` are still on disk.** The loop closed its *code* debt and
  then failed to close *itself* — the same finding as this morning, one cycle later.
- **The `## Feedback` block is empty for the 5th consecutive loop.** Recommendation #2 of
  the earlier retro (have the Evaluator ask you the three questions in-session) was not
  adopted, and the blank template propagated again.
- **The CDD 7.0 framework upgrade is still uncommitted** (12 days; `CLAUDE.md` last
  committed `1dbf793`, 2026-07-01). Recommendation #3 was not adopted. The rules this loop
  was *judged against* — including `parallel-execution.md`, which is what the delegation was
  modeled on — exist only as untracked files in a dirty tree.
- **The Evaluator's P2 (silent wrong-orient fallback across 25M rows) is a live, open
  finding.** Do not let it become the 07-09 residue of the next retro.

## For the user (habits)

- **You built the right thing and skipped the part that makes it safe.** The delegation
  design is genuinely good — model-tiered, git-centralized, independently audited. But you
  shipped it with the guardrails written as *suggestions to the subagent*. You would never
  accept that in production code; the framework deserves the same standard. Recommendation
  #1 is an afternoon's work.
- **Do not let the Planner grade its own homework.** The two weakest points in this loop —
  the improvisation that was accepted, and the audit that found what it was told to look
  for — are both the same shape: the author of the spec controlling the review of the spec.
  Separation of powers is the whole reason the phase matrix exists.
- **Your loops still do not close.** Third retro finding in a row. The code debt from
  07-09/07-10 is now gone, which is real progress — but this loop's own `Plan.md`,
  `Evaluation.md`, empty feedback block, and open P2 are already forming the next backlog.
