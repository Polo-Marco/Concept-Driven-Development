# Imported Retro — CCD-AI-Bench — 2026-07-15

> Copied from the CCD-AI-Bench test project per MAINTENANCE.md §1
> (capture). First attempt at running the v8.0 pipeline in a deployed
> project.

## What the loop produced (it works)

CCD-AI-Bench ran TMMLU+ against local gpt-oss-120b and produced clean,
schema-conforming results with no API key leaked into any file:

- limit=10 → acc 0.513 (670 samples)
- full run → acc 0.520 (20,160 samples), harness 0.4.12, scoring
  loglikelihood

Goal met. The function is sound.

## Who did what — verdict on "8.0"

**It did not run as an 8.0 autonomous loop.** It ran as a manual
7.0-style Planner → Generator flow — because the 8.0 driver was not
present in the deployed project (`.claude/driver/` doesn't exist).
Half the roles the 8.0 diagram promises had no machinery to run in.

| 8.0 role | What actually happened |
|---|---|
| Goal Setter (Ask) | Partial. Ask-phase decisions captured, but folded into the Planner section. No frozen Goal.md / goal.json written. |
| Planner | ✅ Full and clean. Wrote Concept.md, Architecture.md, the benchmark-adapter skill, README.md, and a 5-ticket sequential Plan.md. |
| Evaluator contract-review (≤2 rounds pre-gate) | ❌ Never ran. |
| Human gate | No mechanical gate (`loop.py approve`). User confirmed in chat instead. |
| Generator | ✅ Strong. 4 tickets sequentially, one commit each (9fff110→e6960f1), 17 offline tests green, zero retries, zero boundary stops. |
| Monitor | ❌ Never existed — no trial-launch/polling machinery. |
| Evaluator (verdict) | ❌ Skipped. Journal says [pending]; no verdict.json, no ledger.jsonl. |
| Driver commits | ❌ The agent committed directly (there's no driver to own commits). |

## Three process deviations

1. **Phase-4 fix blended Planner + Generator authority.** When the
   live smoke surfaced 3 real failures (datasets 5.0 script ban,
   loglikelihood-vs-chat, missing tokenizer), the fix was done as an
   in-session modify — commit e8cf640 touched src/, Architecture.md,
   the skill, and README.md together. Exactly the split
   phase-authority is meant to keep separate. Cleaner: a fresh
   [/modify] loop.
2. **Journal stale vs git.** The record says Phase-4 changes were
   "not yet committed" — but git has both e8cf640 and e4af1de
   (--num-concurrent), and the second commit isn't mentioned in the
   journal at all.
3. **Housekeeping.** Plan.md still present (all tickets [x], but it's
   ephemeral and should be deleted on success); Feedback block empty.

## Bottom line

Engineering followed the framework well — surgical tickets, TDD,
per-ticket commits, redacted secrets, empirical resolution of the
deferred scoring decision. Process-wise this was a 7.0 manual run
wearing an 8.0 label, because the driver providing the
gate/Monitor/verdict/ledger guarantees wasn't deployed. The single
real authority slip was the post-smoke fix done in-session rather
than as its own modify loop.

**Top recommendation:** ship `.claude/driver/` — everything else is
minor.

## Maintainer note (added on import, 2026-07-15)

The driver was already drafted (2026-07-14 Maintainer session,
`journal/20260714-maintainer-v8-draft.md`) but only staged in
`v8.0-draft/` — the test project was deployed with the v8.0 CLAUDE.md
and none of the machinery. Root cause is an incomplete install, not a
missing implementation. Install status as of 2026-07-15: root
CLAUDE.md, skills/mode-loop, README patches (PATCHES §4), and
.gitignore entries are already in place; the `.claude/` copy
(driver, agents, hook, settings, 4 patched rules — satisfying
PATCHES §1–3) is user-run per INSTALL.md because `.claude/` is
write-protected to agent sessions. M1/M2 verification per INSTALL.md
still pending before tagging v8.0.
