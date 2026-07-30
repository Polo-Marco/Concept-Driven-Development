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

## 2026-07-30 — first end-to-end toy loop (`.claude/driver/toy_project.sh`, build goal, $1.55)

The loop's first real run. It reached the Generator and escalated on
ticket 1. Everything *around* the failure worked — the hook denied, the
Generator stopped and reported rather than improvising, the driver
escalated instead of burning retries. Three code defects (all fixed in
8.1.3) and two interface defects (NOT fixed — logged for a decision).

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

4. **The human gate does not say where `Plan.md` is.** (NOT fixed)
   - What happened: `== HUMAN GATE [plan] ==` says "Review it, then
     approve". The loop runs in a worktree, so `Plan.md` is not in the tree
     where the user typed `start`. Only `toy_project.sh`'s echo prints the
     path, and real projects never see that echo.
   - Framework angle: `loop.py` `wait_approval()`.
   - Severity: recurring

5. **`phase_status()` truncates the one event that requires action.** (NOT fixed)
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
