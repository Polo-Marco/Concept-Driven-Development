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
