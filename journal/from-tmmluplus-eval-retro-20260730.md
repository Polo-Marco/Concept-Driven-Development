# Imported Retro — tmmluplus eval-pipeline project — 2026-07-30

Covers loop 1 of that project (`journal/20260730-154429-build.md` in the
project repo). Imported into the framework repo per `MAINTENANCE.md`
step 1 (Capture).

**Status: partially applied.** Six of the eight recommendations shipped
as `6e04bf3` (`fix(driver): close six loop defects found by the
2026-07-30 retro`) — see "Disposition" at the bottom for what was
deferred and why.

---

## Scope and limits

This project has run exactly **one** loop. There are no cross-loop
trends yet, so nothing below is a "pattern across N loops" except where
it recurs *within* this loop or matches a defect class already recorded
in the framework repo. Every finding was re-verified against
`.claude/driver/loop.py`, `.claude/hooks/enforce_authority.py`,
`events.jsonl`, `ledger.jsonl`, `logs/` and the traces — not taken from
the journal on trust.

The build journal's `## Feedback` block is **empty**. The user's rating
and "instruction not followed" line are the highest-signal input a retro
has, and this retro ran without them.

## What worked

- **Contract review paid for itself.** Round 1 returned REVISE with 4
  blockers; all 4 were real and all 4 were fixed without resequencing a
  ticket. R4 (order `.gitignore` before `uv sync`) is measurable: `.venv`
  reached 5.2 GB during ticket 1.1 and the driver commits with
  `git add -A`. Without R4 this loop would have put 5.2 GB into history.
- **The Evaluator executed rather than read.** Probe repos in
  `/tmp/cddprobe2` / `/tmp/cddprobe4` reproduced the `uv run pytest`
  collection failure and confirmed the fix; the driver's own
  `tickets()` + `field()` was run over `Plan.md` to prove the Monitor
  Profile grew from 47 chars to 947. That is `loop-protocol.md` §7
  working as written.
- **Front-loaded facts bought a clean generation run.** The Planner
  verified lm-eval's loglikelihood incompatibility, the `ikala/tmmluplus`
  config shape and the `0.4.9.1` pin at plan time. Result: tickets
  1.1–1.5 committed in **7m29s, 0 retries, 0 boundary breaches, 0 stops**
  (`0a9b3e3`…`5d1332d`).
- **Fail-closed held under real failure.** `reports/verify.json` records
  `schema_valid: 0`, `num_concurrent: 0`, `tests_passed: 43` — it
  reported the absent record instead of guessing 128. No fabricated
  number anywhere in the artifacts.

## Recurring problems (with evidence)

Ranked by severity. Items 1–2 are new findings from this retro; 3–8
are the build journal's, each confirmed or corrected at the source.

1. **`run_trial()` never checks the trial's exit code** — NEW, and it
   fired this loop. `loop.py:404` loops on `proc.poll() is None`, then
   `loop.py:448-449` runs `bill(); return True` unconditionally. Any
   process exit is reported to `phase_iterate` as "the trial FINISHED",
   which is the exact claim the v8.1 comment above the function says it
   was rewritten to stop making. Evidence: `logs/trial-6.log` starts
   16:42:08 and ends 16:43:50 with `stage=harness_done rc=1` and
   `lm_eval exited 1`. The driver would have scored that as a completed
   trial. It fails closed *here* only by luck — the thresholds happened
   to be unmet. A stale-but-passing artifact left by an earlier command
   would have been graded as trial output, which is precisely the
   provenance hole `loop-protocol.md` §7 warns about.
2. **Both trial guards were blind at once** — NEW. The Monitor's first
   poll is at `interval_min` (`goal.json`: 5 min); the trial died after
   **1m42s**, so no Monitor session ever ran. With finding 1, a trial
   that crashes faster than one poll interval is invisible to *both*
   guards. Compounding it, the real cause (endpoint gone) never surfaced
   as a clean signature: lm-eval's own retry path raised
   `UnboundLocalError: cannot access local variable 'outputs'`
   (`api_models.py:504`), which none of the ticket's five Monitor
   signatures match. The lesson is not "add more signatures" — it is that
   a non-zero exit code is a *rule*, and `loop-protocol.md` §6 says rules
   are decided by code, not by a model.
3. **`max_usd` is decorative** (journal #1) — CONFIRMED. `claude()`
   re-loads state, adds cost, saves (`loop.py:306-309`); every phase
   function then calls `save(STATE, st)` from the dict `main()` loaded at
   startup, overwriting it. `budget_exceeded()` (`loop.py:350`) reads
   that same stale in-memory dict, so the cap is compared against a value
   reset toward zero at every phase boundary. `iteration`, `replans` and
   wall-clock are unaffected — the phase functions own those fields.
   Since v8.1 removed the mid-loop human checkpoint, this is the cap
   `loop-protocol.md` explicitly calls load-bearing.
   **Correction to the journal:** true spend is *not* unrecoverable. The
   traces carry per-turn `message.usage`. The driver's 4 Opus sessions
   total ~1.39M cache-creation + 20.1M cache-read + 426k output tokens;
   the 6 Sonnet Generator sessions ~865k + 10.4M + 87k. Converting that
   to dollars needs the price card, but the volume is large enough that
   "was the $25 cap actually breached?" is a question worth answering
   rather than assuming — and the driver could not have answered it.
4. **Driver stdout is never flushed** (journal #2) — CONFIRMED. No
   `flush`, no `sys.stdout.reconfigure`, no `-u` anywhere in
   `loop.py`. `logs/driver.log` has mtime 15:45:23 and size **0** after a
   54-minute run: through `tee`, stdout is block-buffered at 8 KB and
   SIGTERM discarded the buffer. The `== HUMAN GATE ==` banner prints the
   same way, so the documented way to follow a loop cannot announce the
   one thing that needs a human. Only `events.jsonl`'s
   `approval_request` made the gate visible.
5. **The authority hook blocks Planner work the matrix grants**
   (journal #3) — CONFIRMED, two distinct causes:
   - `check_write()` denies the Planner *all* of `src/`, including
     `src/**/CLAUDE.md`, which `phase-authority.md` lists as Planner
     Read/Write/**Create**. The planned
     `src/eval_pipeline/adapters/CLAUDE.md` was unreachable; its
     conventions had to be smuggled into a skill file.
   - `norm()` resolves relative paths against `CLAUDE_PROJECT_DIR`, and
     the hook cannot see the Bash call's `cwd`. A throwaway probe in
     `/tmp/cddprobe3` referencing `tests/test_probe.py` was judged as
     repo-relative and denied. The existing `rel.startswith("..")`
     escape at `enforce_authority.py:187` already handles this — but only
     for *absolute* paths. Cost: the nested-import case shipped as an
     assumption instead of a tested fact.
6. **`field()` silently truncates multi-line ticket fields**
   (journal #4) — CONFIRMED (`loop.py:331-333`, `(.+)$` with `re.M`).
   Caught by the Evaluator as R3 and worked around by rewriting the
   Monitor Profile onto one 947-char physical line. The parser is still
   lossy; a plan whose Evaluator does not happen to run the parser ships
   a disarmed Monitor.
7. **`approve` is coarser than the three-gate model** (journal #5) —
   CONFIRMED. `loop.py:666-669` touches *both* `plan` and `replan` flags;
   `wait_approval()` unlinks any pre-existing flag on entry
   (`loop.py:359-361`), so a pre-emptive approve silently does nothing.
   Harmless this loop, but the failure mode is invisible.
8. **`[/loop]` collides with Claude Code's built-in recurring-`/loop`
   skill** (journal #6) — CONFIRMED at the harness layer: `loop` is a
   listed built-in ("Run a prompt or slash command on a recurring
   interval"). This is the only defect that fires on **every single
   invocation**. It is also the second instance of a class already on
   record: `skills/mode-loop/SKILL.md` step 0 exists because of
   `journal/from-ccd-ai-bench-retro-20260715.md`, where a project
   silently degraded to the wrong execution path. Same failure, one layer
   up — step 0 guards the machinery but nothing guards step 0 being
   reached.

## Plan-shape finding (not a defect)

Six of seven criteria are first satisfiable at ticket 1.6, so the
deterministic gate emitted **35 identical `FAIL … source file does not
exist` lines across 5 iterations** (`events.jsonl`) and every PASS for
tickets 1.1–1.5 rested solely on the Generator's own TDD. The loop's
headline free guard was inert for 83% of the loop. This is inherent to a
build goal that culminates in one integration run, and the Planner chose
it deliberately — but it was chosen silently, and the user could not have
known the gate was carrying no information.

## Recommendations

Smallest change, at the right layer. 1–3 are the ones that change
outcomes.

1. **Check the trial's exit code** → `.claude/driver/loop.py:448`:
   `if proc.returncode != 0: event(...); return False`. Two lines. Turns
   a crashed trial into a RETRY deterministically, covers every failure
   signature nobody thought to write, and closes the "graded a stale
   artifact" hole. Also makes finding 2 a non-issue without adding poll
   machinery.
2. **Stop clobbering out-of-band state** → `.claude/driver/loop.py`: add
   `def save_state(st)` that merges `spent_usd`/`gpu_hours` from disk
   (take the max — spend is monotonic) before saving, and replace the
   ~14 `save(STATE, st)` call sites with it. Restores `max_usd` and the
   GPU-hour cap to actually being caps.
3. **One line of line-buffering** → `.claude/driver/loop.py`, top of
   `main()`: `sys.stdout.reconfigure(line_buffering=True)`. Makes
   `logs/driver.log` and the human-gate banner work as documented.
4. **Rename the command** → framework `CLAUDE.md` + `skills/mode-loop/`:
   `[/loop]` → `[/cdd-loop]` (or similar). The collision is
   harness-owned and permanent; a rename is the only fix that does not
   depend on the user noticing. Highest frequency of any defect here.
5. **Two-line hook fix** → `.claude/hooks/enforce_authority.py`:
   in the `planner` branch of `check_write()`, exempt basename
   `claude.md` from the `src/`/`tests/` denial (the matrix already grants
   it). For the cwd blindness, do **not** grow the hook — add one line to
   `.claude/agents/cdd-planner.md` / `cdd-evaluator.md`: *out-of-repo
   scratch work must use absolute paths*, which makes the existing `..`
   escape do its job. `loop-protocol.md` §3 is explicit that the hook
   must not become a shell parser.
6. **Make `field()` multi-line** → `.claude/driver/loop.py:331`:
   `(.*?)(?=^\*\*[A-Z]|\Z)` with `re.M | re.S`. Then drop the "one
   physical line" workaround note from ticket 1.6's Monitor Profile
   convention in `.claude/rules/task-ticket-format.md`.
7. **Scope `approve`** → `.claude/driver/loop.py:666`: accept an optional
   gate name, default to the gate implied by `loop-state.json`'s phase,
   and print a warning when no gate is pending.
8. **One Ask-phase self-check** → `skills/mode-loop/SKILL.md`: map each
   criterion to the ticket that first makes it satisfiable; if they all
   map to the last ticket, say so to the user — "the per-iteration gate
   will report FAIL throughout and the Generator's TDD is your only
   guard until ticket N." No new machinery, just stop hiding it.

## For the user (habits)

- **Killing the driver when vLLM went down was the right call** — but
  note *you* were the detector, not the loop. Until recommendation 1
  ships, the loop cannot tell a dead endpoint from a slow one, and the
  Monitor → `KILL_ESCALATE` → driver path remains **unexercised**. The
  guard is present but unproven; don't yet trust it unattended.
- **Fill the Feedback block.** It is the one input only you can provide,
  and this retro had to run without it. Two lines is enough — a rating
  and any instruction that wasn't followed.
- **Close the loop.** `Plan.md`, `Evaluation.md`, `verdict.json`,
  `goal.json`, `Goal.md`, `ledger.jsonl`, `loop-state.json`,
  `events.jsonl` are all still on disk, plus uncommitted WIP
  (`reports/`, `scripts/verify.py`, `tests/test_verify.py`). State is
  `iterate 6/8, replans 0/2, 54m of 6h` — resumable. Decide explicitly:
  restart vLLM and resume ticket 1.6, or close out. Three retros in a row
  flagged unclosed loops in the framework's own history
  (`loop-protocol.md` § Housekeeping); this would be the fourth.
- **Read the five committed diffs.** `0a9b3e3`…`5d1332d` went in with no
  human checkpoint by design. Loop mode has no `[Halt here]` anymore;
  skimming the diffs is the only remaining guard, and it is on you.

---

## Disposition (added at import, 2026-07-30)

**Applied in `6e04bf3`** — recommendations 1, 2, 3, 5, 6, 7. All six are
provable code defects; n=1 is sufficient evidence for a bug. Pinned by
18 new cases in `.claude/driver/test_loop.py` (62 → 80), of which 10
fail against the pre-fix code.

Recommendation 2 was applied **differently than proposed**. The retro's
`save_state()` merge-with-max would give `spent_usd`/`gpu_hours` an
implicit "monotonic" semantics that nothing records and a future
non-monotonic field would silently violate. Root cause is not two
writers to *disk* but two different *in-memory dicts*, so `claude()` now
takes the caller's `st` and bills onto it — one dict, one writer,
`save(STATE, st)` consistent from anywhere. Same for `wait_approval()`,
which needed to publish `pending_gate` for recommendation 7.

**Deferred** — recommendations 4 and 8. Both are design judgements
rather than defects, and this retro is explicitly n=1:

- **4 (rename `[/loop]`):** the rename is probably right, but the retro
  stops at the instance when it already identified the *class* — a CDD
  command colliding with a harness built-in. `/discuss` and `/retro` are
  equally generic English verbs and equally exposed. The fix worth
  making is a namespace convention (`/cdd-*` for all three), not one
  rename; and the blast radius (CLAUDE.md, skills/, docs, existing
  journal references) argues for doing it once, deliberately.
  Also unresolved: the retro reports the collision fires on every
  invocation but never states what harm it did in loop 1. Highest
  frequency is not highest severity.
- **8 (Ask-phase disclosure):** disclosure is honest but does not fix
  anything. If the deterministic gate carries no information for 83% of
  a build loop, the question is whether the Ask phase should require
  each ticket to contribute at least one machine-checkable criterion, so
  the gate is live from iteration 1. That is a Concept-level change and
  belongs in `[/discuss]`, not a self-check bullet.

**Not covered by this retro, worth carrying forward:**

- **A meta-pattern the retro walked past.** `journal/feedback-inbox.md`
  (2026-07-17, item 2) already reported "spend metered but never
  enforced". v8.1 added the `budget_exceeded()` check and stopped —
  nobody asked whether the value being checked was trustworthy. Finding
  1 is the same shape: v8.1 rewrote `run_trial()` for driver-caused
  exits and missed process-caused ones. Twice now, a fix has addressed
  the reported instance rather than the mechanism that produced it.
  Candidate `[/retro]` rule: every recommendation states whether it
  fixes an instance or a mechanism.
- **Cost has no conclusion.** Token volumes were computed but never
  converted. ~20M cache-read tokens across 4 Opus sessions for a
  five-ticket build is the number that decides whether fresh-session /
  cold-context-reload scales; it should be answered, not left open.
- **The contract review has a second reading.** "4 blockers, all real"
  can mean the review is load-bearing, or that Planner quality is the
  actual gap and the review is compensating for it. Only the flattering
  reading was recorded.
