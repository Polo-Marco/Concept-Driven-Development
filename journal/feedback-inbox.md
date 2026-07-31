# Feedback Inbox (personal)

Quick capture for framework feedback from daily use. Append entries at
the top. `[/retro] all` reads this file alongside imported project
retros. After an upgrade incorporates an entry, delete it (the retro
summary + commit preserve the history).

Entry format:

```
## YYYY-MM-DD — <project or context>
- What happened: [1–3 lines, factual]
- Framework angle: [which rule/skill/mode it implicates, if known]
- Severity: [annoyance | recurring | blocking]
```

---

## 2026-07-31 — cdd-toy-818: the mode-skill path, exercised for the first time

- **What happened:** first toy loop run on a FAITHFUL deployment
  (8.1.8 scaffolders copy `CLAUDE.md` + `skills/`). `goal_reached`,
  5 tickets, 0 retries, 0 replans, **$9.14 of $25**, 0.43h driver
  runtime. The path that had never run before ran clean: the Planner
  followed `mode-build` Spec Step 3 and wrote a 324-line project skill
  (`skills/wordfreq-stdlib/SKILL.md`), every ticket carried
  `Skills to Load: @skills/wordfreq-stdlib/SKILL.md` instead of `none`,
  and the delivered `src/wordfreq/counter.py` is **byte-identical to
  the skill's copy-paste template** — Planner → ticket → Generator,
  end to end. The 8.1.8 no-Ask-phase clause was quoted back almost
  verbatim in the plan's Assumptions block, with five named calls and
  no silent guess.
- **Framework angle:** two observations, neither blocking.
  1. **`max_iterations: 6` is now tight.** With mode skills present the
     Planner produced 5 tickets, not the 3–4 it produced without them,
     so the toy finished at iteration 5/6 — one retry of headroom for
     the whole run. The toy's default was measured before skills
     existed; a single RETRY anywhere would now escalate on
     `max_iterations` with the work nearly done. Same class as the
     `max_wall_hours` and `max_usd` defaults that already had to be
     raised: **a cap measured on a thinner harness.**
  2. **Contract review got CHEAPER as the plan got bigger** — 0
     revisions and $1.93 pre-gate, against 1 revision / $2.58 (8.1.7,
     4 tickets) and 2 revisions / $5.48 (8.1.6, 4 tickets). The plan
     volunteered its own "Evidence ownership (self-check)" section
     before the Evaluator asked. One data point each, so not a trend —
     but if it holds, the mode skill is paying for itself at the gate.
- **Severity:** annoyance (item 1), observation (item 2)

## 2026-07-30 — the EXPERIMENT path, first end to end (2 runs, $16.95)

Four `build` runs had proved the pipeline and left its whole reason for
existing untested: a build goal has no `Trial` field, so `run_trial()`
returns immediately, `cdd-monitor` is never spawned, and no verdict but
PASS or ESCALATE is ever reached. New harness
`.claude/driver/toy_experiment.sh` — a declared fault-injection stub, no
GPU, no network, failure schedule entirely deterministic — forces the
rest. Run A ($7.66, 32 min) reached `goal_reached` and produced the
defects below; run B ($9.29, 37 min, 3 iterations, 1 replan) re-ran the
same harness against the fixed driver and reached `goal_reached` too.
Both under their caps. The schedule reproduced exactly across both runs,
which is the point of putting it in a launch counter rather than a seed.

**What the path proved.** Monitor spawned and classified
(INTERVENE `nan_loss`, then HEALTHY on every clean poll); driver killed
and RETRIED; a clean baseline missed its threshold and the Evaluator
returned REPLAN; a fresh Planner read `ledger.jsonl`, named `lr=0.5` as
ruled out per Protocol #3 and picked a different config; the replan was
re-gated; `check_criteria()` went green on numbers a trial actually
wrote (`final_loss=0.1618`). Every ledger row carried its `criteria`
snapshot. Both contract reviews passed round 1 — the first toy runs to
manage that, which I read as the 8.1.4 Producibility self-check earning
its place.

**Five defects.** Four fixed with regression tests, one reported only.

1. **`proc.kill()` killed the shell, not the trial.** (fixed) The
   driver logged `trial_killed` at 15:05:10; the trial log then gained
   `step 20/40` and `FATAL` — lines the harness prints at
   trial_start+100s, i.e. ~15:05:39. Twenty-nine seconds of output from
   a process reported dead. `shell=True` makes the shell the child, and
   the Planner's `train.py && report.py` is exactly what no shell can
   collapse into an exec. Harmless in the toy; on a real goal the driver
   reports a kill and immediately launches the RETRY's trial, so two
   trials share one GPU and one of them is believed dead. Now
   `start_new_session` + `killpg` + `wait()`. Run B: log frozen at
   step 14 at +12s and +57s, zero surviving processes.
   Severity: blocking (for any real experiment goal).

2. **A RETRY destroyed the evidence that caused it.** (fixed) The trial
   log was `trial-<iteration>.log` opened `"w"`, but `run_trial()` runs
   once per ATTEMPT. Attempt 2 truncated the nan window the Monitor had
   actually judged. Now one log per attempt. Latent twin, same line: the
   driver told the Generator to tee to that same path, so on an
   experiment ticket the trial destroyed the Generator's own output —
   now `ticket-<iteration>.log`. Severity: recurring.

3. **A REPLAN left no trace in the event feed.** (fixed) Every other
   consequential transition emits; the most expensive one the driver
   makes — discard the plan, buy a fresh Planner *and* a second contract
   review, ~$2.50 of a $7.66 run — produced only an `approval_request`
   whose gate string happened to read "replan". `phase_status()` renders
   events, so a replan was invisible to the person paying for it.
   Severity: recurring.

4. **The driver names a goal type; no skill of that name exists.**
   (fixed) `phase_plan()` says "the mode skill for goal type
   'experiment'" and `cdd-planner.md` said `skills/mode-*/SKILL.md`. The
   run-A Planner's first act was `find . -iname "*mode-experiment*"` —
   nothing — after which it read `loop.py` in full twice and
   `enforce_authority.py` in full, re-deriving the driver's contract
   from source. The plan was good; this is cost and confusion, not
   corruption. Honest limit: the toy ships no `skills/` at all, so it
   did NOT reproduce the dangerous shape (siblings present, only this
   one missing, inviting a substitution). Mapping now stated in
   `cdd-planner.md`, with a test that every skill it names exists. Run B
   Planner: "planned from Goal.md + task-ticket-format.md only, per the
   Planner's documented fallback — no other mode's skill was
   substituted." Severity: recurring.

5. **`toy_project.sh`'s `.gitignore` gap, generalised.** (fixed before
   these runs, verified live in both) `loop-state.json`, `events.jsonl`
   and `journal/traces/` are declared gitignored by governance.md §5 and
   nothing ensured it, so run 4 swept them into `feat(loop):` commits.
   The driver now writes those entries itself. Deliberately still
   tracked: Plan.md's `[x]`, Evaluation.md, verdict.json, ledger.jsonl —
   ephemeral, but the evidence a reviewer wants attached to the commit
   they explain.

**Reported, not fixed.** The `results/` directory holding both criteria
sources gets added to `.gitignore` by the Planner, in every run that has
made the choice (build run 4, experiment runs A and B). Defensible —
runtime output — but it means the loop's own evidence never enters git,
and a provenance audit after the fact has only the working tree. Worth a
retro's opinion rather than a unilateral fix.

**Do the two recorded patterns hold up?**

*A value crossing from a model to a stricter parser* — yes, and this
round finally produced the confirmation the 8.1.3 fix had been waiting
for. Run B's Planner wrote ``**Trial:** `python3 bench/train.py --config
configs/baseline.json && python3 bench/report.py` `` — backticked, the
same markdown habit that caused the Boundary defect — and the trial
launched clean (`toybench 1.0 | config=configs/baseline.json ...`).
Unstripped, those backticks are command substitution under
`shell=True`. Five runs to see it in the wild once. Run B also wrote
`##` headings (8.1.4 tolerance) and a backticked Boundary (8.1.3 fix),
both fine. Defect 4 is the same pattern one level up: not a value the
parser rejects, but a NAME the driver hands a model for something that
does not exist.

*The driver failing to distinguish two states and defaulting to the
optimistic one* — yes, and defect 1 is its sharpest instance yet.
"I sent a signal" was recorded as "the process is dead", which is the
same shape as the unchecked trial exit code (8.1.1) and the unchecked
`git_commit` (8.1.2). Three instances now, all: **the driver asked an
external process to do something and wrote down that it had happened,
without asking.** That is worth promoting from "pattern" to a rule the
next reviewer applies deliberately — every `subprocess` call in
`loop.py` should be read with "and who checked?".

**A third pattern, new.** Defects 2 and 3 are both about *the record*,
not the control flow: a log keyed on the wrong unit, and a transition
that emitted nothing. Neither changed a single verdict. Both destroyed
the ability to explain afterwards why the loop did what it did — and the
loop's whole justification is running unattended, which means the record
IS the product. Name it: **the loop is only as trustworthy as what it
can show you afterwards, and nothing tests that.** 149 offline tests
cover verdicts and gates; almost none assert that an event or an
artifact a human will need later actually exists. Both defects were
found by reading the run, not by the suite.

**Economics.** Run A: $7.66, 32 min, 2 iterations, 1 replan, 3 trial
launches, 7 Monitor sessions. Run B: $9.29, 37 min, 3 iterations (its
Planner split reporting and trial into separate tickets), 1 replan, 3
trial launches, 7 Monitor sessions. First cap was $25 — three times
measured, which is a cap that can never bite; now $15, against a ~$11
worst case the other budgets allow and a $9.29 observed high. Same
mistake as run 4's $5 cap, in the opposite direction. Nothing audits the
driver's own economics, still.

**Plan shape varies a lot between runs of the identical goal.** A gave
one ticket doing report + baseline trial; B gave three (report, a
trial-only ticket with an empty Boundary and no Run Command, then the
replan's new config). Both passed contract review round 1 and both
reached the goal. B's trial-only ticket is worth noting: the driver
still spends a full Generator session on a ticket whose declared Output
is "none", and its `Boundary: none — no files are written...` is prose
that `boundary_env()` reads as a non-empty list matching nothing. That
happened to be the intent, but a Boundary that means "no writes" and a
Boundary that is unparseable are the same string to the hook.

## 2026-07-30 — toy loop runs 2–4: the first COMPLETED loop

Four runs in one afternoon, $14.74 total ($1.55 / $2.24 / $2.62 / $8.34). Run 4 finished: `goal_reached`,
three tickets built and committed by the driver, 13 passing tests,
`results/metrics.json = {"tests_passed": 13, "cli_ok": 1}` verified by
hand afterwards. The pipeline works end to end. What the three failed
runs cost us was worth more than the successful one.

**Fixed along the way** (all shipped, all with regression tests):

1. **Markdown Boundary matched nothing** (run 1) — see the entry below.
   Verified live in run 4: three Generator sessions, zero denials.
2. **A `##` ticket heading parsed as zero tickets** (runs 2 and 3). The
   sonnet Planner wrote `## Phase 1, Step 1:` in both runs; `TICKET` was
   pinned to `### `. Tolerance now spans `#{2,4}` — and the done-marker
   had to learn the same, or a parsed ticket could never be marked and
   would re-run to the iteration cap.
3. **"Unparseable" read as "finished"** (run 2). `phase_iterate` computed
   `todo` off `tickets()` and could not tell the two apart, so a plan it
   could not read produced `all_tickets_done` with nothing built. Only
   the deterministic criteria gate stopped that from reading as success.
4. **A revision nobody reviewed** (run 3). Contract review was
   `for _ in range(2): review; revise` — it bought a Planner revision
   after the last review and escalated without looking at it. The
   discarded revision had fixed the flagged defect; the loop was one
   review away from the gate, and the escalation described a plan that
   was no longer on disk. Reviews are now revisions + 1.
5. **Nothing told the Planner to BUILD what the criteria READ** (run 3).
   Both REVISE rounds were spent on this, with the Evaluator
   re-deriving the rule each time by reading `loop.py` line by line.
   Now a Producibility self-check in `cdd-planner.md` +
   `task-ticket-format.md`.
6. **The toy could not finish under its own budget** (run 4). Advertised
   "~$1-2", capped `max_usd` at 5, escalated at $5.69 with one ticket to
   go. Re-budgeted from measurement ($12).
7. **The toy committed 1.2 MB of `journal/traces/`** (run 4), contrary to
   governance.md §6 — its `.gitignore` never excluded them.

**Patterns worth a retro's attention:**

- Items 1, 2 and 5 are one failure mode: **a value crosses from a model
  to a parser, and the parser is stricter than what the model writes.**
  Each was invisible until a real run, and each was silent — the loop
  reported something other than "I could not read this."
- Items 3 and 4 are the other: **the driver could not distinguish two
  states and picked the optimistic one.** Unparseable vs finished;
  reviewed vs merely paid for. Both defaulted toward "proceed".
- Three of the seven were found by the loop's own machinery, not by me:
  the criteria gate caught 3, the contract review caught 5, and run 4's
  final provenance audit caught 7. The Evaluator also detected an
  out-of-band `goal.json` budget edit made between the escalation and
  the resume, verified the criteria block was byte-identical, and
  reasoned from PROTECTED_ALWAYS about who could have made it. The
  expensive checks are earning their cost.
- What no automated check caught: item 4 (I found it by comparing file
  mtimes) and item 6. Both are about the driver's own economics, which
  nothing audits.

**Still unexercised after four runs:** REPLAN, RETRY, the Monitor,
trials, and the `[Halt here]`-free escalation path from a Generator
stop. A `build` goal never touches them. The next smoke test should be
an `experiment` goal.

## 2026-07-30 — first end-to-end toy loop (`.claude/driver/toy_project.sh`, build goal, $1.55)

The loop's first real run. It reached the Generator and escalated on
ticket 1. Everything *around* the failure worked — the hook denied, the
Generator stopped and reported rather than improvising, the driver
escalated instead of burning retries. Three code defects (fixed in 8.1.3) and
two interface defects (fixed in 8.1.4, after run 3 re-confirmed both).

1. **A markdown Boundary matched nothing → silent global write ban.** (fixed)
   - What happened: the Planner wrote ``**Boundary:** `src/wordfreq/counter.py`, ...``
     — markdown, which `task-ticket-format.md` does not forbid. `loop.py`
     passed the field verbatim as `CDD_BOUNDARY`; `boundary_env()`
     normalised whitespace/backslashes/case but not backticks, so every
     entry kept its markup and no comparison in `in_boundary()` could
     match. A non-empty Boundary that matches nothing bans every write and
     reports it as a Boundary breach. Any real loop dies on ticket 1.
   - Framework angle: `.claude/hooks/enforce_authority.py` `boundary_env()`
     — fixed at the parser (sole consumer + the place that matches).
   - Severity: blocking

2. **The same seam on `**Trial:**` is command substitution.** (fixed, was latent)
   - What happened: `loop.py` read the `Trial` field and ran it under
     `Popen(shell=True)`. The same Planner habit — ``**Trial:** `python3
     train.py` `` — makes the shell run the inner command and then execute
     its stdout. Invisible in the toy run only because build tickets have
     no `Trial` field; the first experiment goal would have hit it.
   - Framework angle: `loop.py` `run_trial` — stripped at the launch site,
     deliberately not inside `field()` (Spec/Monitor Profile are prose).
   - Severity: blocking

3. **The offline suite was green on a macOS-incompatible fixture.** (fixed)
   - What happened: `test_loop.py` failed `TestFindLoop`
     `test_finds_the_loop_in_a_sibling_worktree` — `/private/var/...` vs
     `/var/...`. `DriverCase.setUp` injected an unresolved `mkdtemp()`
     path, breaking the `.resolve()`d-ROOT invariant the driver has in
     production.
   - Framework angle: `test_loop.py` fixture, not `find_loop()`.
   - Severity: annoyance (but it made the gate command untrustworthy)

   Cross-cutting lesson for the first three: 112 green tests did not catch
   defects 1 and 2 because **no case ever fed the machinery a value in the
   form the Planner actually emits.** The suite tested the driver against
   its own idea of a ticket. Where a model writes a field that code then
   parses, the test fixture should be copied from real Planner output.

4. **The human gate does not say where `Plan.md` is.** (fixed in 8.1.4)
   - What happened: `== HUMAN GATE [plan] ==` says "Review it, then
     approve". The loop runs in a worktree, so `Plan.md` is not in the tree
     where the user typed `start`. Only `toy_project.sh`'s echo prints the
     path, and real projects never see that echo.
   - Framework angle: `loop.py` `wait_approval()`.
   - Severity: recurring

5. **`phase_status()` truncates the one event that requires action.** (fixed in 8.1.4)
   - What happened: every event detail is cut to 54 characters, including
     `escalate`. The escalation reason is `rep[-400:]` of the Generator's
     report, so the user sees a 54-character window starting mid-word —
     `generator stopped: t those literal bac` — for the event that exists
     to make a human act.
   - Framework angle: `loop.py` `phase_status()`.
   - Severity: recurring

   4 and 5 are one class: **a message whose purpose is to make a human act
   is formatted as a log line.** Log lines get truncated and omit paths
   because their reader is scanning; gate and escalation output has exactly
   one reader who must do exactly one thing, and it should print in full
   with the path to act on. Worth `[/retro]` checking every human-facing
   string in the driver against this, not just these two.

## 2026-07-17 — CDD framework self-audit (v8.0 driver review, Cowork session)

Reviewed `docs/loop-orchestration-design.md` + `v8.0-draft/` against two
goals: (a) make `[/loop]` more hands-off, (b) cut token/$ cost via
caching. Priority 0: **8.0 has never run AS 8.0** — driver undeployed +
untested (see `from-ccd-ai-bench-retro-20260715.md`). Everything below
assumes the M1/M2 install lands first (`v8.0-draft/INSTALL.md`).
Line refs are approximate (against the 2026-07-14 draft of `loop.py`).

Concrete items to action when there's time:

1. **GPU-hours cap is dead code (real bug).**
   - What happened: `run_trial` resets `t0` on every Monitor poll (~L177),
     then computes `gpu_hours` from `t0` after the trial ends (~L205) — so
     it only counts time since the LAST poll, massively undercounting;
     `max_gpu_hours` budget never trips.
   - Framework angle: `.claude/driver/loop.py` — use a separate `trial_start`.
   - Severity: blocking (unattended runs can't be trusted without it)

2. **$ / token budget metered but never enforced.**
   - What happened: `claude()` accumulates `spent_usd` (~L94) but
     `budget_exceeded()` never checks it — design §4 promises a `$` cap.
   - Framework angle: `loop.py` `budget_exceeded()` + `goal.json` schema.
   - Severity: blocking (this is the direct lever for "降低 token 消耗")

3. **INTERVENE evaluates a killed trial.**
   - What happened: `run_trial` returns True after killing a crash-class
     trial (~L204); driver then runs the Evaluator on partial metrics.
     Relies on the Evaluator noticing truncation → fragile; a PASS on
     truncated metrics ships a half-run.
   - Framework angle: `loop.py` `run_trial` / verdict routing.
   - Severity: recurring

4. **Contract-review gate is fail-open.**
   - What happened: `phase_contract_review` defaults a missing/corrupt
     `verdict.json` to `"OK"` (~L231) → the safety pre-gate silently
     passes. A safety gate should fail-closed (REVISE/ESCALATE).
   - Framework angle: `loop.py` `phase_contract_review`.
   - Severity: recurring

5. **Biggest token lever is cadence, not caching.**
   - What happened: `loop.py` defaults `evaluation_cadence` to
     per-iteration (~L278) → one Opus Evaluator per ticket. Flip the
     default to final-pass for `build`/`modify`; keep per-iteration only
     for `experiment`/frontier. Also consider Sonnet for per-ticket eval,
     Opus only for contract-review + final.
   - Framework angle: `loop.py` + `goal.json` cadence default + model tiers.
   - Severity: recurring

6. **Caching is in tension with fresh-session-per-phase (optimization).**
   - What happened: Claude Code cache is per-model + per-directory +
     git-snapshot-bound, so worktree-per-loop silos the cache, and the
     driver's per-ticket commit shifts the recent-commits snapshot →
     breaks cross-ticket system-layer cache. Levers: `ENABLE_PROMPT_CACHING_1H`
     (API key) / auto-1h on a Claude subscription — but subagents stay on
     the 5-min TTL and any trial >1h always misses. Structural fix: move
     the driver from `claude -p` to the Agent SDK (suppress per-machine
     system sections → shared cache across worktrees/machines; explicit
     `cache_control` breakpoints; real cost tracking to feed item 2).
   - Framework angle: `.claude/driver/loop.py` invocation layer.
   - Severity: annoyance (perf/cost, not correctness)

Suggested order: install + verify driver → fix #1/#2 (+ #3/#4) →
flip cadence/tiers (#5) → 1h TTL + SDK migration (#6). Full write-up in
the 2026-07-17 Cowork session; offer stands to turn #1–#5 into a
`loop.py` patch.

## 2026-07-14 — cross-project (v7.0 usage, esp. tcocrai SFT work)

Five items, captured during the v8.0 design discussion. Together they
motivate the loop-orchestration design
(`docs/loop-orchestration-design.md`).

1. **Multi-planning (batch).**
   - What happened: multiple goals queue up but each Planner→Generator→
     Evaluator loop must be run by hand, one at a time.
   - Framework angle: no batch entry point; Mode Routing assumes one
     manual invocation per session.
   - Severity: recurring

2. **Git tracking / worktree isolation.**
   - What happened: want multiple P→G→E loops in one repo concurrently,
     merging afterwards; today all loops share one working tree.
   - Framework angle: parallel-execution.md isolates tickets *within*
     a plan (disjoint Boundaries) but nothing isolates whole loops.
   - Severity: recurring

3. **Planner controlling the Generator.**
   - What happened: wanted hands-off Planner→Generator handoff; when
     tried (tcocrai 2026-07-13 loop), the fused session let a bad spec
     through — spec author adjudicated its own breach.
   - Framework angle: session lifecycle STOPs + phase-authority.md;
     see `journal/from-tcocrai-retro-20260713-2.md` defect #1.
   - Severity: blocking (for autonomy)

5. **Long-run execution jobs.**
   - What happened: SFT probes and similar experiments run for hours;
     need something to monitor logs, react to bugs (OOM/NaN/crash),
     and vary experiment parameters — today that's the user.
   - Framework angle: run-logging.md captures output but nothing
     *watches* it; no monitor role; no experiment ticket shape.
   - Severity: blocking (for experiment workflows)

6. **Planner calling Generator and Evaluator (orchestration).**
   - What happened: want to set a goal (e.g. "check SFT gate 1
     passes") and have the loop research/trial until an answer, no
     manual phase relay.
   - Framework angle: whole pipeline; resolved in v8.0 design by a
     deterministic driver calling all phases — NOT the Planner
     (retro defect #1 forbids that shape).
   - Severity: recurring

(Numbering preserved from the original capture; there is no item 4.)

## 2026-07-13 — (example, delete me)
- What happened: Generator read the full Architecture.md even though
  the ticket listed only Overview + Data Models.
- Framework angle: generator-protocol.md selective loading may need a
  harder rule or a self-check line in the ticket format.
- Severity: recurring
