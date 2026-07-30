# Retro — 2026-07-14 — tcocrai — Diagnostic Report

> Imported from the tcocrai project per MAINTENANCE.md §1 (capture).
> Canonical source: tcocrai `journal/retro-20260714.md`. Content
> preserved verbatim from the retro report; formatting converted from
> the rendered artifact to markdown.

**Why the last five evaluated loops all closed PASS WITH ISSUES**

- Scope: `journal/*.md`, 2026-07-05 → 2026-07-14
- Loops reviewed: 8 (5 evaluated)
- Authority: read-only over code; writes `journal/` only

## 01 · Finding

Every evaluated loop so far — 5 of 5 — closed PASS WITH ISSUES. None
closed clean. That is not one recurring bug; it's three distinct
failure classes stacked across the same six-loop stretch, plus a
process gap that's kept this pattern invisible until now.

Two of those classes are severe and mechanically related: artifacts
get validated after they're generated at full scale rather than
before, and when the one automated gate built to catch that fired
correctly, it was overridden rather than obeyed. The third is a
documentation-lag pattern that is real but low-stakes and shouldn't be
confused with the other two. Underneath all three sits a quieter
problem: the `## Feedback` block in every one of the 8 journal entries
reviewed is still blank, so this retro had only the Evaluator's side
of the story to work from.

## 02 · The five loops

| Date | Loop | Class |
|---|---|---|
| 07-05 | CC export v2 build | doc-drift |
| 07-07 | Run-readiness + data card | doc-drift |
| 07-08 | Pickle-storm fix + v1 filter run | artifact unfit |
| 07-09 | Filter v2, table-aware + gate override | artifact + process |
| 07-14 | Discard poisoned run | rollback incomplete |
| 07-14 | Short-guard + crop_path fix | pending eval |

Severity marks the loop's top finding, not the verdict — all five
scored loops carry the same PASS WITH ISSUES verdict. The sixth node
(fix for the two P1s below) has no Evaluator record yet, so it isn't
counted in the 5-of-5.

## 03 · Root cause A — validated after scale, not before

Twice in this stretch, a labeling artifact was generated across the
full candidate set before anyone checked it against ground truth on a
sample. Both times the defect was large, mechanical, and would have
been visible in a few hundred rows.

**P1 · 2026-07-08 · agreement filter v1** — The teacher-text loader
excluded MinerU table/equation/image/chart blocks by design — a
decision made once at Ask-phase and never stress-tested against a real
table-heavy page before the candidate run. Run against 27,057,914 v2
crops, the drop list removed 18,473,586 lines (68.3%). 55.6% of drops
had an empty teacher comparison window — no evidence either way — and
81% scored CER = 1.0 by construction. A spot check on doc 455e7530…
p.3 found the dropped cell 西營盤 / 100.00 sitting verbatim in the
teacher's own table block — the teacher had agreed, the filter had
simply never looked.
*(journal/20260708-000000-modify.md · Evaluator)*

**P1 · 2026-07-09 · agreement filter v2** — The v1 gap was fixed —
tables now read, no_evidence=0, park=0 — but the fix's short/numeric
whole-unit guard (len < 4) caught ordinary short CJK words as a side
effect. Of 8,584,328 candidates, 1,608,331 (18.74%) dropped, all
tagged `short_numeric_unsupported`, 76% short CJK text. A 600-line
random sample of that bucket found 98.7% present verbatim inside their
own teacher window — roughly 1.21M verified false drops. Same disease,
new organ: a design assumption locked at Ask-phase, never checked
against non-Latin text before an 8.58M-row run.
*(journal/20260709-000000-modify.md · Evaluator)*

Both are the identical shape: a filter's edge-case assumption was
reasoned about in the abstract, locked into a skill/plan, and only
tested against reality by running the whole corpus through it. A few
hundred rows checked against the teacher, before the full run, would
have caught both at near-zero cost instead of after 8–27 million rows.

## 04 · Root cause A′ — the one gate that caught it got overridden

**P1 · 2026-07-09 · --max-drop-rate gate** — The default abort gate
(0.15) is exactly the safeguard root cause A needed — and it worked.
It fired correctly at the true drop rate, 0.1874, and wrote the run to
`.QUARANTINE` as designed. The threshold was then raised to 0.20 to
let the run ship, before the Evaluator had looked at the output. The
flywheel export at 14:06 consumed the gate-overridden list before
evaluation completed — the quarantined file and the canonical output
ended up byte-identical. This is the single costliest event in the
five loops: it converted a caught, correctable defect into a poisoned
25.4M-crop export that then required an entire dedicated Triage cycle
five days later to unwind.
*(journal/20260709-000000-modify.md → journal/20260714-000000-modify.md)*

This is worth separating from root cause A above: A is a
validation-timing gap; A′ is a working control being turned off under
schedule pressure. Fixing A (sample-check before scale) reduces how
often a gate like this fires late and hard in the first place — but
only not touching the gate, ever, when it does fire is what actually
stops a caught bug from shipping.

## 05 · Root cause B — rollback reversed the marker, not the pointers

**P1 · 2026-07-14 · poisoned-run discard** — The Triage that discarded
the 07-09 export did the hard part correctly — it caught that
`stages_done` is checked for idempotency and rolled it back for all
49,860 affected docs (independently reverified: 0 of 102,505 manifest
rows now carry "flywheel"). But `crop_path` is a write-only field:
`flywheel.py:482` sets it for lines it emits and never clears it for
lines it doesn't. The rollback left ~25.4M dangling `crop_path`
pointers into the now-quarantined export tree. The Triage's own note
called this "expected and self-healing" — it's neither:
`validate.py:106-112` resolves `crop_path` against `data_root`, so
`tcocrdata validate --all`, the README's documented integrity check,
fails on the order of 25.4M times today, and stays broken permanently
for any line a future filter drops, not just this one.
*(journal/20260714-000000-modify.md · Evaluator, finding P1)*

Same shape as root cause A: state was reasoned about locally — one
field, one action — instead of tracing what else that field feeds.
(This is now fixed pending evaluation — see the sixth timeline node —
by making flywheel clear-then-set `crop_path` every run.)

## 06 · Distinct, lower stakes — docs lag correct code

The two earliest loops in this stretch, 07-05 and 07-07, scored PASS
WITH ISSUES on documentation drift alone — zero code defects in
either. 07-05's README omitted three new CLI flags and two export
artifacts the same commit had added. 07-07's data card referenced a
provenance file that does not exist, and its v1→v2 waterfall left
190,411 crops unreconciled against two conflicting v1 baselines. Real,
worth fixing, but a different failure mode entirely from A/A′/B —
flagged here so it doesn't get folded into the more severe pattern
above.

## 07 · Loop-by-loop

| Loop | Verdict | Top finding | Scale | Class |
|---|---|---|---|---|
| 07-05 · CC export v2 | PASS · issues | README omits 3 flags, 2 artifacts | 97/97 tests | doc-drift |
| 07-07 · run-readiness | PASS · issues | waterfall unreconciled, dead path ref | +190,411 crops | doc-drift |
| 07-08 · pickle-storm fix | PASS · issues | table blocks excluded from teacher read | 68.3% dropped | validate-after-scale |
| 07-09 · filter v2 | PASS · issues | short-guard false-drop + gate overridden | 18.74% dropped | validate-after-scale + override |
| 07-14 · discard run | PASS · issues | dangling crop_path, validate broken now | ~25.4M pointers | partial rollback |
| 07-14 · H1+H2 fix | pending | fixes both P1s above | 141/141 tests | — |

## 08 · Recommendations

**1. A firing abort gate is a hard stop — never raise the threshold to
ship.** Treat a gate firing (like `--max-drop-rate`) exactly like a
Generator Boundary violation: it requires a new Planner cycle to fix
the root cause or lower the threshold with logged justification,
before any re-run. Raising the number to force a run through is
prohibited without a `docs/DEVIATIONS.md` entry written before the
override, not after. This is the single highest-leverage fix — it
directly targets the costliest event in these five loops.
*Target: `.claude/rules/phase-authority.md` or `generator-protocol.md`*

**2. Require a sample check before any expensive pipeline's full
run.** For any ticket flagged `Process Logging: Expensive` that
produces an artifact a later stage consumes, the Manual Verification
field must name a concrete sample size and a ground-truth cross-check
that happens before the full-scale run. Would have caught the
table-block gap and the CJK false-drop at hundreds of rows instead of
millions.
*Target: `.claude/rules/task-ticket-format.md` — Manual Verification
field*

**3. Rollback tickets must trace every field a reversed state wrote,
not just the marker.** Add a Planner self-check specific to
Triage/rollback work: enumerate every field the state being reversed
had written to (not only the primary status flag) before declaring the
rollback complete. Targets the `crop_path` class of bug directly.
*Target: `.claude/rules/task-ticket-format.md` — Planner Self-Check*

**4. Fill the Feedback block — even two lines.** 8 of 8 journal
entries reviewed have a blank `## Feedback` block. Retro is currently
reconstructing every pattern above from Evaluator verdicts alone; the
framework's second, distinct signal — your own read on what went well
and what instruction wasn't followed — has never actually fired.
*Target: habit, not a rule file*

## 09 · For the user

**On the gate override** — The 07-09 override reads as a
schedule-pressure call — "critical-path impact" was explicitly one of
the six points raised against that report. It's also the most
expensive decision in this entire stretch: it turned a defect the
system had already caught into a multi-day rollback. If schedule
pressure is a recurring force here, recommendation 2 (sample-check
before scale) is the cheaper lever — it makes the gate rarely fire
late and hard in the first place, rather than counting on not
overriding it in the moment it does.

**What's working** — Every rollback has gone through a proper Triage
cycle rather than a hand-patch outside the framework — that discipline
is exactly why the `stages_done` idempotency trap got caught instead
of silently shipped again. Keep routing data-state fixes through
Triage even when it feels like "just move some files."

---

Retro authority: read-only over Concept/Architecture/skills/docs/src/
tests; writes `journal/` only. No code, rule, or core file was
modified to produce this report.

Sources:
- journal/20260705-000000-modify.md
- journal/20260707-044620-modify.md
- journal/20260708-000000-modify.md
- journal/20260708-033023-modify.md
- journal/20260709-000000-modify.md
- journal/20260714-000000-modify.md
- journal/20260714-120009-modify.md
- Evaluation.md (current — 2026-07-14 discard cycle)
- journal/retro-20260714.md (this retro's canonical journal entry)
