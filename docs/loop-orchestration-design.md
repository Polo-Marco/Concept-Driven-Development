# Loop Orchestration — v8.0 Design

> Status: **draft for the v8.0 Maintainer session**. Written 2026-07-14
> in a Discuss session; revised same day against current external
> guidance (see §14). Not yet implemented.
>
> Motivating evidence (per MAINTENANCE.md, changes must cite feedback):
> - `journal/feedback-inbox.md` entry 2026-07-14 (five items:
>   multi-planning, worktree isolation, planner→generator control,
>   long-run execution jobs, orchestration).
> - `journal/from-tcocrai-retro-20260713-2.md` (the delegated-loop
>   pilot: sound output, five control-structure defects).
> - External review (§14): Anthropic's long-running-harness posts
>   (2025-11, 2026-03), Cognition's context-engineering principles,
>   2026 orchestration surveys.

## 1. Goal

Let the user state a goal (e.g. *"check whether SFT gate 1 passes"*),
approve one plan, and walk away. The pipeline plans, executes,
monitors, evaluates, and replans by itself until it produces an answer
— or escalates. Human moves from *in* the loop to *on* the loop.

## 2. Design principles

1. **The orchestrator is dumb.** A deterministic driver (small script,
   state machine) controls the loop. LLM intelligence lives *inside*
   phase sessions; control flow is auditable code. This is the direct
   fix for tcocrai retro defect #1 (role fusion): the driver calls all
   phases; **the Planner calls nobody**.
2. **Sessions stay separate and short.** Each phase runs as a fresh
   headless session (`claude -p`) with selective context. Process
   boundaries = session boundaries. Long-running jobs belong to the
   driver, never to a live session.
3. **`Goal.md` is agent-immutable.** No session type may edit the goal
   or its success criteria — only the user. A loop that can move its
   own goalposts is a Goodhart machine.
4. **Trial provenance is sacred.** A launched trial's config is
   immutable. Any parameter change = kill + new trial ID via REPLAN,
   recorded in the trial ledger. Crash-recovery with identical config
   is the only same-trial relaunch.
5. **Authority is enforced, not prose.** Restricted agent definitions +
   a `PreToolUse` hook make violations impossible, not discouraged
   (retro defect #2).
6. **Simplicity First still binds.** The driver is ~150 lines plus
   config. File-based state (`Plan.md`, `Evaluation.md`, `journal/`)
   is already the message bus; v8.0 adds no databases, no daemons
   beyond the driver, no new subsystems.

## 3. User surface: three modes

| Command | Role | What it does |
|---|---|---|
| `[/discuss]` | Think | Unchanged from 7.0. |
| `[/loop] <goal>` | Do | Ask phase → writes `Goal.md` → Planner writes `Plan.md` → **user approves once** → driver runs Generate → Monitor → Evaluate → (Replan) until `PASS` / `ESCALATE` / budget exhaustion. |
| `[/retro]` | Improve | Unchanged from 7.0. |

### Where the 7.0 modes go

- `[/build]`, `[/modify]`, `[/migrate]`, `[/merge]` → **goal types** in
  `Goal.md` (`build | modify | experiment | migrate | merge`). The
  Planner skill branches on type; merge keeps reverse-engineer-first,
  modify keeps the Triage sub-flow. The `mode-*` skills become an
  internal library.
- `start execution` → issued by the driver after plan approval; no
  longer a user command.
- `[/evaluate]` → the Evaluator agent, dispatched by the driver each
  iteration. Skill remains manually invocable as an escape hatch.
- `check the latest run log` → absorbed by the Monitor step.

Manual 7.0-style operation remains possible: the driver calls the same
skills a user would. Zero new concepts on the fallback path.

**Hold the line:** no `[/monitor]`, no `[/batch]` commands. Monitoring
is a driver duty; batch is `[/loop]` over a queue of goals. A fourth
command must be demanded by a retro, not anticipated.

## 4. The loop

```
Goal.md  (user-owned: success criteria, budgets, escalation rules)
   ↓
driver spawns Planner (fresh session) → Plan.md (tickets, typed by goal)
   ↓
driver spawns Evaluator (contract review, §4a)
   → satisfiable? testable? boundaries sane? → OK | REVISE (back to Planner)
   ↓
────── HUMAN GATE: user approves Plan.md + budgets, once ──────
   ↓
loop:
   driver spawns Generator     → bearings + smoke test (§4b),
                                 implements / launches trial, exits
   driver polls job; every N min spawns Monitor (cheap model)
        Monitor → HEALTHY | INTERVENE | KILL+ESCALATE
   driver spawns Evaluator     → metrics vs Goal.md → verdict.json
   branch:
     PASS      → journal, housekeeping, notify user with the answer
     RETRY     → re-dispatch same ticket (max 3, as 7.0)
     REPLAN    → fresh Planner + Evaluation.md + trial ledger (max N)
     ESCALATE  → stop, notify user
   budget check each iteration (iterations, GPU-hours, wall-clock, $)
```

### 4a. Contract review (new, pre-gate)

Before the human gate, the driver spawns the Evaluator once to review
`Plan.md` against `Goal.md`: is every Spec step executable with only
the inputs available at that point (satisfiability)? Are the
success/metric contracts testable? Are Boundaries sane and disjoint
where grouped? On `REVISE`, the Planner gets the findings and
re-plans (max 2 rounds, then ESCALATE to the user). This upgrades the
tcocrai satisfiability fix from a Planner *self*-check to an
independent check, catches impossible specs before GPU spend, and
mirrors the "sprint contract negotiation" that Anthropic's harness
found load-bearing (§14). Cost: one cheap Evaluator call.

### 4b. Bearings + smoke test (every Generator session)

Each Generator session starts with a scripted get-bearings routine:
read git log + trial ledger, run the environment's smoke test
(`init.sh` / Run Command) — fix an inherited broken state *before*
starting new work. This extends 7.0's once-per-loop Green State Check
to every iteration, per Anthropic's harness findings (§14).

Verdict routing rule: **metric-based failures → RETRY/REPLAN; protocol
failures → ESCALATE immediately.** Protocol failures include: Boundary
breach attempt, worker stop (spec gap / unsatisfiable step), missing
deliverable (silent worker death), missing artifacts. Retrying an
impossible spec burns GPU budget on a defect no trial can fix.

## 5. `Goal.md` schema (user-owned, agent-immutable)

```markdown
# Goal: [one line]

**Type:** build | modify | experiment | migrate | merge

## Success Criteria            ← measurable, machine-checkable

Predictable shape so the markdown → JSON translation is mechanical
rather than interpretive. Each states metric, comparison, threshold,
the file carrying the number, and why it matters (v8.1):

1. **[Name]** — `[metric]` in `[path/to/file.json]` is `[op] [value]`.
   [Why this is the right bar; what a failure would mean. This prose is
   what the Evaluator's contract review compares the JSON against.]

## Preflight — what must be true before the loop starts   (v8.1)

The driver runs these before spawning the Planner; any failure aborts
without spending a model call. One check type: a shell command whose
exit code decides. A check must print no secrets — the driver discards
its output and logs only name + exit code (governance §2).

1. **[Name]** — [what it establishes].
   `check: [shell command, exit 0 = pass]`

**Budgets:**
- Max iterations: [N]
- Max replans: [N]
- Max GPU-hours: [N]        ← experiment goals
- Max wall-clock: [hours]

**Escalation rules:**
- [conditions beyond protocol failures that must page the user]

**Evaluation cadence:** per-iteration | final-pass
   ← per-iteration for experiments and frontier tasks; final-pass for
     routine builds well within model capability (§14, revision 4)

**Environment:** [VM / GPU / paths — what the Planner's env audit checks]
```

**Machine mirror (`goal.json`).** The `[/loop]` Ask phase writes the
success criteria, preflight checks, budgets, and cadence into a
`goal.json` the driver parses and the PreToolUse hook write-protects.
Rationale: models are measurably less likely to inappropriately edit
JSON than Markdown (Anthropic feature-list finding, §14) — and the hook
makes it impossible regardless.

**Direction of authority (v8.1).** `Goal.md` is the SOURCE OF TRUTH and
`goal.json` is a DERIVED translation of it. Humans read and edit the
markdown; the Ask phase translates; the driver reads only the JSON. If
the two disagree, the markdown is right and the JSON is a bug.

This introduces one new failure mode — **derivation drift**. The prose
says "≥ 0.85 on the full set" and the JSON records
`{"value": 0.85, "source": "results/gate1.json"}`, with the full-set
qualifier surviving only in the prose. Because `check_criteria()` gates
on the JSON, a lossy translation silently redefines "done", and with no
mid-loop human checkpoint (v8.1 removed `[Halt here]`) nothing catches
it later. Two controls, both cheap:

1. The Ask phase reads the contract back **by the JSON's semantics**,
   closing with "nothing else is checked" — which forces out qualifiers
   that never made it across.
2. The Evaluator's contract review audits the translation
   (**Faithful?**) before the human gate. This is maker–checker applied
   to the translation step: the agent that wrote the JSON is not the
   agent that approves it.

## 6. Experiment tickets (new ticket variant)

For `Type: experiment`, tickets replace the Test Contract with:

```markdown
**Hypothesis:** [what this trial should demonstrate]
**Trial:** [exact launch command, teed to logs/trial-<id>.log]
**Metrics Contract:** [metric names + where they are written]
**Success Threshold:** [metric vs value; maps to Goal.md criteria]
**Monitor Profile:** [poll interval; known failure signatures]
```

All other ticket fields (Boundary, Depends On, Architecture, Skills to
Load) are unchanged. The Planner self-check gains one bullet
(satisfiability — see §9), now backstopped by the contract review
(§4a).

**Spec granularity rule (per goal type).** Anthropic found that
granular technical detail specified upfront *cascades errors* into the
implementation when wrong (§14) — and the tcocrai unsatisfiable spec
was exactly such a cascade. Resolution:

- Stay detailed about **outcomes and interfaces**: metrics contracts,
  function signatures at boundaries, error types, Boundary files.
- Go light on **implementation path**, especially for `experiment`
  goals where the path *is* the unknown — specify the hypothesis and
  how success is measured, not the steps to get there.
- 7.0-style full detail remains right for `build`/`modify` tickets
  where the Generator must not improvise on shared surfaces.

## 7. Machine-readable verdict

`Evaluation.md` keeps its prose audits; the Evaluator additionally
writes a sidecar `verdict.json` the driver parses (JSON, not a
Markdown block — same corruption-resistance rationale as `goal.json`):

```json
{
  "verdict": "PASS | RETRY | REPLAN | ESCALATE",
  "reason": "[one line]",
  "evidence": ["metric values", "test counts", "file refs"]
}
```

**Evaluator input hygiene (retro defect #4 / rec #3):** the driver
constructs the Evaluator prompt from the diff, `Plan.md`, `Goal.md`,
and metrics only — never the Planner's or Generator's self-assessment.
The neutral probe replaces the suspicion list: *"Is any part of this
diff not specified by the plan? If so, judge it."*

## 8. Trial ledger (REPLAN memory)

One JSONL record per iteration, appended **by the driver** (not by
agents) to `ledger.jsonl` in the loop's worktree:
`{trial_id, hypothesis, config_hash, metrics, verdict, notes}`.
Every replanning Planner loads the ledger — otherwise iteration 7
re-proposes iteration 2's failed idea. This closes the "no process
memory" gap *inside* a loop, as `journal/` closes it across loops.

Handoff artifacts are load-bearing, not bookkeeping: with fresh
contexts per phase, the ledger + Plan.md + commit messages ARE the
system's memory (Cognition's context-sharing critique, §14). The
Generator's per-session progress notes (commit message + journal
append) carry the implicit decisions the next session needs.

## 9. Enforcement prerequisites (from the tcocrai retro — ship WITH v8.0)

| # | Change | Fixes retro defect |
|---|---|---|
| 1 | `.claude/agents/cdd-generator.md`, `cdd-evaluator.md`, `cdd-monitor.md` with restricted tool lists | #2 (honor-system authority) |
| 2 | `PreToolUse` hook: deny `git commit/add/reset/checkout` to workers; deny writes outside dispatched Boundary; deny `Goal.md` writes to ALL sessions | #2, goalpost immutability |
| 3 | One dispatch per ticket; driver commits between tickets | #3 (checkpoint gate) |
| 4 | Workers write run records to `journal/traces/` (or hook extended to sidechains) | #5 (unverifiable compliance) |
| 5 | Planner never edits `src/` — simplification is a Generator re-dispatch | #1 (role fusion residue) |
| 6 | Planner self-check bullet: *"Can each Spec step be executed with only the inputs available at that point?"* | the unsatisfiable spec |

These are prerequisites, not a parallel backlog: an autonomous loop
with honor-system guardrails is unauditable by construction.

## 10. Worktree isolation

Each loop runs in its own git worktree + branch
(`loop/<goal-slug>-<date>`); master stays clean; a runaway loop cannot
dirty the main tree. Merge-back after the loop closes:

- **v8.0:** driver merges fast-forward/clean merges; ANY conflict →
  ESCALATE to the user. One loop at a time (batch = sequential queue).
- **v8.1 (deferred):** concurrent loops; conflicted merge-back via a
  merge session using `[/merge]`'s reverse-engineer-first discipline.

## 11. Monitor step

Every N minutes (per ticket's Monitor Profile) the driver spawns a
short, cheap session (log tail + latest metrics in, one token-cheap
judgment out):

- `HEALTHY` → keep going.
- `INTERVENE` → crash-class problem (OOM, NaN, dataloader death):
  driver kills, dispatches a Generator fix, relaunches **same trial**
  only if config is identical; else new trial ID.
- `KILL+ESCALATE` → unrecognized failure or repeated intervention:
  stop, page the user.

The Monitor never edits code or configs itself — it classifies; the
driver routes.

## 12. Scope

**v8.0:** 3-mode surface, driver + Goal.md/goal.json + experiment
tickets + contract review (§4a) + verdict.json + trial ledger +
Monitor + worktree-per-loop (sequential queue) + all §9 enforcement
items. Driver housekeeping: archive `Plan.md`/`Evaluation.md` per
iteration, prompt the feedback block at loop end (three retros running
flagged unclosed loops — housekeeping must be automatic, not
remembered).

**Evaluator calibration is expected work, not a defect.** Anthropic
took several tuning rounds (few-shot graded examples, reading
evaluator logs, fixing judgment divergences) before their evaluator
graded acceptably (§14). Budget the same for `cdd-evaluator`; the
`[/retro]` loop is where divergences surface.

**Harness staleness review (new retro item).** Every harness component
encodes an assumption about what the model can't do on its own; those
assumptions go stale as models improve (§14). On each new model
generation, `[/retro]` should ask: which loop components are still
load-bearing? Strip candidates one at a time — never in batches.

**v8.1 (earn it first):** concurrent loops + merge automation;
anything a retro demands.

**Out of scope:** CI enforcement, multi-user, non-git storage
(unchanged from Concept.md).

## 13. Open questions for the Maintainer session

1. Driver language/runtime (Python on the VM is the default guess) and
   where it lives in the template (`.claude/driver/`? `tools/`?).
2. Exact `claude -p` invocation set: per-phase system prompts, model
   tiers (cheap Monitor, mid Generator, strong Planner/Evaluator?).
3. Budget accounting source of truth (driver-side token/$ metering vs
   GPU-hours from the VM).
4. ~~Notification channel for ESCALATE/PASS.~~ **Resolved 2026-07-14
   → §16 (remote control).** Remaining choice: ntfy.sh vs Telegram
   bot as the concrete channel.
5. Does `[/loop]`'s Ask phase run interactively in the user's session
   (likely yes — it needs the user) while everything after approval is
   headless?
6. Driver crash-resume: persist loop state (iteration count, budgets
   spent, current phase) to a `loop-state.json` so a VM restart resumes
   instead of restarting.

## 14. Review against current guidance (2026-07-14)

Sources reviewed:

- Anthropic, *Effective harnesses for long-running agents* (2025-11):
  initializer + coding agent, feature-list JSON, progress files, git
  checkpoints, get-bearings routine, end-to-end testing.
  https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
- Anthropic, *Harness design for long-running application development*
  (2026-03): GAN-inspired generator/evaluator; final architecture is a
  three-agent **planner / generator / evaluator** harness communicating
  via files — independently convergent with CDD's phase split.
  https://www.anthropic.com/engineering/harness-design-long-running-apps
- Cognition, *Don't Build Multi-Agents* (+ later refinement): fresh
  contexts lose implicit decisions; multi-agent works "when writes
  stay single-threaded and the additional agents contribute
  intelligence rather than actions."
  https://cognition.com/blog/dont-build-multi-agents
- 2026 orchestration surveys: hybrid orchestration (deterministic
  skeleton, LLM tactics within bounds) is the emerging standard for
  high-stakes workflows; deterministic routing is cheaper and
  reproducible.

**Validated by the guides:** phase separation with an independent,
deliberately-skeptical Evaluator ("tuning a standalone evaluator to be
skeptical is far more tractable than making a generator critical of
its own work"); fresh sessions over compaction for long work (context
resets cure "context anxiety"); file-based handoffs; incremental
one-ticket progress with git checkpoints; deterministic driver.
The design also satisfies Cognition's refined principle: only the
Generator writes code, only the driver commits; Planner, Evaluator,
and Monitor contribute intelligence, not actions.

**Where this design goes beyond the guides:** the published harnesses
enforce rules with strongly-worded prompts ("It is unacceptable
to...") — the honor system the tcocrai retro condemned. Hook-based
enforcement (§9), budgets, the protocol-vs-metric escalation split,
worktree isolation, and trial provenance appear in none of them.
Their runs cost $124–$200 with no caps — Goal.md budgets are
justified.

**Revisions adopted from the guides** (already folded into the
sections above): contract review pre-gate (§4a); bearings + smoke test
per session (§4b); spec granularity by goal type (§6); JSON for
machine-critical state — goal.json, verdict.json, ledger.jsonl (§5,
§7, §8); configurable evaluation cadence + harness staleness review +
evaluator calibration expectation (§5, §12).

## 15. Proposal: v8.0 build order

Recommendation for the Maintainer session — three milestones, each
independently shippable, ordered so the safety layer exists before any
autonomy does:

**M1 — Enforcement + skeleton (no autonomy yet).**
`.claude/agents/` definitions, PreToolUse hook, goal.json protection,
per-ticket dispatch-and-commit. Prove it by re-running a tcocrai-style
delegated loop and watching the hook actually deny a violation.
Ships as v7.1 if desired — it hardens manual 7.0 use too.

**M2 — The loop, sequential, one goal.**
Driver (spawn/poll/parse/branch/budget/housekeep), Goal.md + goal.json
Ask flow, contract review, verdict.json, trial ledger, Monitor.
First real target: an actual SFT-gate goal on the GPU VM. Expect to
spend most tuning time on the Evaluator (§12). This is v8.0.

**M3 — Worktrees + queue.**
Worktree-per-loop, sequential goal queue, clean-merge-else-escalate.
Concurrency and merge automation stay in v8.1 until M2 retros are
clean.

Rationale for the order: M1 is the afternoon of work the tcocrai retro
already demanded and everything else assumes it; M2 delivers the
actual user value (goal-in, answer-out); M3 is containment and
throughput. Each milestone ends with a `[/retro]` before the next
starts — the framework should be built the way it tells others to
build.

## 16. Remote control (phone)

Two layers, matching the two halves of the pipeline:

**Interactive half — Claude Code Remote Control.** The `[/loop]` Ask
phase runs as an interactive Claude Code session in tmux on the VM
with Remote Control enabled (research preview, 2026-02). The user can
define the goal and approve the plan from the phone. Limits: one
remote connection per instance, terminal stays open, interactive
sessions only — it does NOT attach to the driver's headless
`claude -p` sessions.

**Autonomous half — the driver IS the control surface.** The running
loop is a script, not a session, so remote control = a message channel
to the driver:

- **Out:** per-iteration digests (trial ID, metric, verdict) from
  `ledger.jsonl`/`loop-state.json`, Monitor alerts, ESCALATE, PASS.
- **In:** minimal verbs — `status | approve | halt | abort |
  extend-budget`. The human gate blocks on an approval message
  instead of local input; same state machine.

Channel candidates (Simplicity First order): ntfy.sh pub/sub (~30
lines, no accounts) or a Telegram bot (inline approve/halt buttons,
~60 lines). SSH + tmux from the phone is the zero-build fallback.

Security: allowlist the user's device/chat ID on the command topic —
an open `approve` channel is a remote trigger for autonomous code
execution; keep secrets out of digests (`governance.md §2`). The phone
talks ONLY to the driver, never to Claude sessions — the remote
surface stays as dumb and auditable as the loop.
