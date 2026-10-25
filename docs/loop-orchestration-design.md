# Loop Orchestration — v8.0 Design

> Status: **shipped**. Implemented in 8.0 and hardened through 8.1.9;
> this file is kept as the as-designed record — why the loop is shaped
> the way it is — not as a description of the code. Where the two
> disagree, `.claude/rules/loop-protocol.md` is current and this is
> history. Known divergences: the human gate count settled at three
> (plan, replan, escalate) with mid-loop `[Halt here]` removed in 8.1;
> the deterministic gates, the plan-evidence check and the runtime
> clock were all added after this was written.
>
> Written 2026-07-14 in a Discuss session; revised same day against
> current external guidance (see §14).
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
| `[discuss]` | Think | Unchanged from 7.0. |
| `[loop] <goal>` | Do | Ask phase → writes `Goal.md` → Planner writes `Plan.md` → **user approves once** → driver runs Generate → Monitor → Evaluate → (Replan) until `PASS` / `ESCALATE` / budget exhaustion. |
| `[retro]` | Improve | Unchanged from 7.0. |

### Where the 7.0 modes go

- `[build]`, `[modify]`, `[migrate]`, `[merge]` → **goal types** in
  `Goal.md` (`build | modify | experiment | migrate | merge`). The
  Planner skill branches on type; merge keeps reverse-engineer-first,
  modify keeps the Triage sub-flow. The `mode-*` skills become an
  internal library.
- `start execution` → issued by the driver after plan approval; no
  longer a user command.
- `[evaluate]` → the Evaluator agent, dispatched by the driver each
  iteration. Skill remains manually invocable as an escape hatch.
- `check the latest run log` → absorbed by the Monitor step.

Manual 7.0-style operation remains possible: the driver calls the same
skills a user would. Zero new concepts on the fallback path.

**Hold the line:** no `[monitor]`, no `[batch]` commands. Monitoring
is a driver duty; batch is `[loop]` over a queue of goals. A fourth
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

**Machine mirror (`goal.json`).** The `[loop]` Ask phase writes the
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
  merge session using `[merge]`'s reverse-engineer-first discipline.

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
`[retro]` loop is where divergences surface.

**Harness staleness review (new retro item).** Every harness component
encodes an assumption about what the model can't do on its own; those
assumptions go stale as models improve (§14). On each new model
generation, `[retro]` should ask: which loop components are still
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
5. Does `[loop]`'s Ask phase run interactively in the user's session
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
throughput. Each milestone ends with a `[retro]` before the next
starts — the framework should be built the way it tells others to
build.

## 16. Remote control (phone)

Two layers, matching the two halves of the pipeline:

**Interactive half — Claude Code Remote Control.** The `[loop]` Ask
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

## 17. Rationale register (moved out of the rules in 8.1.21)

Until 8.1.20 every rule in `.claude/rules/` and `.claude/agents/` carried
its own incident narrative, version tag and journal citation inline.
That made the always-loaded set (CLAUDE.md + 8 rule files) ~15,000
words, read by every session including each Monitor poll, and turned
the rules into a second changelog (`journal/from-opd-pipe-retro-20261025.md`,
maintainer observation). The rules now state the rule; this register
keeps the WHY, one entry per rule, pointing at the record. `git log -p`
of each rule file holds the full original prose.

### Hook (loop-protocol.md §3)
- **Shell write-target scan** (v8.1): core files and Boundaries were
  unguarded on the shell path.
- **Denials visible; over-denial not free** (v8.1.9): a `2>&1` matched
  as a write to `goal.json` killed a read-only audit (2026-08-02).
- **Decide on the resolved target, never the token** (v8.1.11): eight
  false positives in aibench's first eight loops, 42 % of all stops —
  bare `>`, `>=`, quoted `--format`, heredoc body, `git log` batch,
  listing forms of `tag`/`stash`/`worktree`, `cp` trailing argument
  (which also LEAKED a write to `Architecture.md`).
- **Expansion is not a path** (v8.1.13): `$M` reached the role
  decision as a file called `$m`; assignments resolved per segment, a
  global last-write-wins fix failed OPEN on
  `M=Architecture.md; echo x > $M; M=/tmp/ok`.
- **Quoted span is data on the git net** (v8.1.14): `echo "--- git
  worktree ---"` and `grep "git commit"` denied; killed contract review
  round 3, driver read silence as REVISE.
- **Heredoc body is data on every scan** (v8.1.13): a Planner writing
  `cat > Plan.md <<'EOF'` denied for prose naming `git`.
- **Relative paths decided where the shell writes; quoted spans data
  on EVERY net** (v8.1.16): ~110 denials across twelve loops in the
  two 2026-09-02 retros; `cd` tracked per segment.
- **`/tmp` is scratch**: two-sided test (outside repo AND under
  `/tmp`), symlinks resolved.

### Gates and criteria (§6–7)
- **`check_criteria` fail-closed; first green buys an audit** (v8.1.6):
  the regression guard defends an unearned green as readily as a real
  one.
- **`metric@source` identity; `criteria_due`** (v8.1.12): six criteria
  under four names in one loop, thirteen under nine in another; a
  stable `latest.json` pointer started a loop with four criteria green
  off the previous loop's records — `evidence_gate()` refuses it.
- **`plan_problems()` single owner, file not tree** (v8.1.6): on
  2026-07-31 `results/` sat in four Boundaries; a schema ticket's
  fixture wrote `acc=0.6` and three criteria read green four
  iterations before the harness existed.

### Review and commits
- **Review bounded by money** (v8.1.7): two consecutive builds spent
  59 % of the run ($5.48, six sessions, zero tickets) before the gate.
- **Review EXECUTES the Wired? class** (v8.1.14): every aibench review
  finding was a read of a non-existent field/key/path; one passed
  review and stopped the Generator six minutes after the gate.
- **Review cap per loop across replans** (v8.1.17): 16 rounds across 6
  replans, ~$150 of $218 before any measurement, four replans were
  GOAL defects (`journal/from-agentrl-retro-20260918.md`, problem 5).
- **First review of each plan phase uncounted; cap checked before a
  revision is bought** (v8.1.19): DF M0 escalated "the contract keeps
  failing" after six first reviews of environment-fact replans.
- **Review remembered with the Plan.md hash** (v8.1.16): a restart
  mid-review re-bought the review of an unchanged plan.
- **`plan(loop):` commit at the gate** (v8.1.7): the first ticket commit
  carried Plan.md, Evaluation.md, Architecture.md and a budget edit —
  three authors in one commit.

### Verdict routing
- **Retry carries WHY; no-op twice escalates** (v8.1.6).
- **Generator stop adjudicated** (v8.1.15): REPLAN fired zero times in
  fifteen loops because its only entrance was a Mode-2 verdict; every
  plan defect woke a human (`journal/retro-20260824-aibench.md`).
- **Output gate** (v8.1.16): three PASSes in two aibench loops with
  nothing on disk, each caught one iteration and one opus audit later.
- **Retry cap adjudicated** (v8.1.16): three converging attempts
  stopped by the counter; attempt 4 passed on a human's say-so an hour
  later (`journal/from-aibench-retro-20260902.md`, problem 4).
- **Trial dying twice identically adjudicated** (v8.1.19): a vLLM OOM
  relaunched verbatim bought nothing (JEV loop 3).
- **Replan of an environment fact fixes the environment** (v8.1.17):
  the vLLM flashinfer `PATH` defect cost identical replans on 09-02 and
  09-08 (`journal/from-agentrl-retro-20260918.md`, problem 4).

### Dead sessions and outages
- **Dead session re-dispatched once** (v8.1.13): an API 529 on the
  first token read as ESCALATE on a loop whose 2.7 h trial had
  succeeded.
- **API error inside a valid result is dead too** (v8.1.17): `is_error:
  true`, exit 0 — the retry never fired for the fault it was written
  for (problem 8).
- **Connectivity death is a wait** (v8.1.19): 11 of 16 escalations and
  8 of 27 iterations in one deployment were a 15–80 min DNS outage
  billed as attempts (`journal/retro-20261015-cross-project.md`, B3).
- **Live Evaluator with no verdict asked once more** (v8.1.19): STAGES
  s8 21:15 woke a human for a forgotten last step.

### Monitor
- **Monitor memory; driver overrules** (v8.1.16): five of six kills
  across two campaigns were healthy trials — a per-call cost line read
  HEALTHY five polls and as a crash on the sixth.
- **Stall is the driver's clock** (v8.1.17): five healthy trials killed
  on a model's stall reading; one deployment patched its driver three
  times in three days toward this rule (problem 1).
- **Deadline sizes the poll, warns, never kills** (v8.1.19): a 25 h
  trial polled every 10 min cost 137 Monitor sessions and 23 % of its
  loop; ~2,600 polls across seven deployments decided nothing (S4, B12,
  B13). A 4× under-estimate on a healthy trial (JEVI) would have been a
  false kill. One loop paid $26 for 68 HEALTHY readings on an opus
  Monitor (v8.1.18).

### Gates, commands, housekeeping
- **Criteria re-read at a gate → `criteria_amended`** (v8.1.19): seven
  loops amended at a gate, six restarted the driver to load it (B7).
- **`approval_waiting` every 4 h; delegation rule** (v8.1.17): a plan
  gate outlasted a 24.6 h GPU rental with the driver silent.
- **`replan` is a command** (v8.1.15): the workaround was a tower
  hand-editing `loop-state.json` under a running loop (L5).
- **`pause-after`** (v8.1.19): lowering `max_iterations` as a pause
  landed 8 s after the next Step and deleted checkpoints (B9).
- **`note`** (v8.1.16): every agentRl loop had a hand in it that
  surfaced later as "the record does not match the run".
- **Driver writes the journal on every exit; Feedback block matched as
  a line** (v8.1.6, v8.1.17): 22 files held 53 `## Request` sections
  after nested rewrites.
- **`Filled by:`** (v8.1.19): seven deployments ran delegated; in 22
  loops the user's voice appeared in one block.
- **`close` refuses a template block** (v8.1.17): six of 22 loops
  closed on the untouched template (problem 7a).
- **`close` copies ledger + events to `journal/raw/`; traces into the
  PRIMARY tree** (v8.1.19): three deployments lost every trace of a
  campaign when the worktree was removed.
- **Budgets hot-reloadable; worktree copy wins; seeded once** (v8.1.6,
  v8.1.9): a resume re-copied the primary tree's goal and reverted an
  approved budget raise twice in one loop.
- **`max_wall_hours` meters runtime** (v8.1.7): a loop that sat 3.6 h
  at the gate escalated the instant the approval landed.
- **Preflight `first-start`** (v8.1.19): ten loops failed every restart
  on a "`<dir>` absent" check and hand-edited `goal.json` (B8).

### Ticket format
- **Under ten minutes or it is a Trial** (v8.1.16): eight abandoned
  runs across six iterations, each killing vLLM mid-flight
  (`journal/from-agentrl-retro-20260902.md`, problem 3).
- **`;` not `&&` for the sweep**: rebuild-v2's standing rule 8.
- **Monitor Profile enumerates noise** (v8.1.16): the one loop that did
  killed nothing healthy (`journal/from-aibench-retro-20260902.md`,
  problem 1).
- **Deadline from a measured number** (v8.1.17): a 540-min cap from a
  mean over a rising series; a 900-min cap assuming ~52 min where the
  airline domain took ~155 (problem 3).
- **Infra errors are metrics** (v8.1.20, R7): three outage-tainted
  files read green at the free gate (DF M0 it 24–25).
- **`Disk:` is a contract** (v8.1.16): 54 GB/iteration filled the
  volume at iteration 7 and killed the driver mid-write (problem 6).
- **Consumers grep** (v8.1.16): three manual sessions in one week
  shipped importers in no Boundary (`journal/from-aibench-retro-20260902.md`,
  problem 6).
- **GPU-free config probe** (v8.1.17): nine of 49 replans were framework
  configuration facts found by a failed GPU smoke (problem 2).
- **Numbers name their probe** (v8.1.20, R1): six replans in one
  deployment, three escalations in another, the sole bad loop of a
  third (`journal/retro-20261015-cross-project.md`, S2).
- **What a stop strands** (v8.1.20, R8): 29 GB and 58 GB left twice,
  three later preflights tripped (STAGES; PB pb13).
- **Never destroy evidence before its replacement exists**: both arms'
  ten repeats discarded before the new protocol ran
  (`journal/from-aibench-retro-20260902.md`, problem 9).
- **Exercise a pinned harness's runtime path** (2026-08-02): three
  escalations at tickets 7–8 for one under-tested Step 1.
- **`Audit: deferred`** (v8.1.20): one deployment bought 19 audits of
  no-code Trial re-runs, all PASS, nothing found.
- **No test reads the live goal; no test writes under a `source` tree**
  (v8.1.16, v8.1.20 R6): rebuild-v2 `tests/CLAUDE.md` rules 1, 2, 7;
  `results/s0-setup/serve_check.json` overwritten twice.

### Evaluator
- **Grounded?** (v8.1.13): 2026-08-18 the plan gave the live probe
  three read paths of the nested shape
  (`journal/from-aibench-retro-20260819.md`).
- **Earnable?** (v8.1.15, v8.1.20): a never-measured `>= 0.90`
  escalated at 0.8978 hours after the science was finished; six of
  seven deployments on 2026-10-15 paid for a recalled number.
- **Wired? one paste per criterion** (v8.1.16): a criterion named a key
  the harness cannot emit; three rounds of reading passed it
  (`journal/from-agentrl-retro-20260902.md`, problem 2).
- **Ceiling** (v8.1.7): three review passes that each rebuilt a
  four-ticket plan cost 59 % of the loop
  (`journal/retro-20260731-toy-816.md`, problem 2).
- **Plant one failure on first green** (v8.1.20, R10): six Generator
  sessions in one loop wrote tests after the implementation.
- **Report carries every amendment** (v8.1.20, R2): a report.json with
  no trace of the 0.95 → 0.94 that made it pass.
- **Write denial ends the session; read denial is a finding** (v8.1.20,
  R9): four audits in three deployments died on a read-only
  `git merge-base`.
- **`python -B`** (v8.1.20, R13): four protected-tree tripwires were
  bytecode a probe wrote.

### Planner / Generator agent files
- **No Ask phase in loop mode** (v8.1.8): the toy copied no `skills/`,
  so nobody knew what a headless Planner did with "STOP. Loop until
  the user says 'proceed to spec'" (`journal/retro-20260731-toy-816.md`,
  problem 5).
- **Goal-type → skill mapping stated in the agent file** (v8.1.5): the
  Planner ran `find . -iname "*mode-experiment*"` and re-derived the
  driver's contract from `loop.py`.
- **Prompt on stdin** (v8.1.18): a 128 KB replan prompt hit E2BIG in
  three deployments (`journal/retro-20261015-cross-project.md`, B2).

### 8.1.21 (journal/from-opd-pipe-retro-20261025.md)
- **Rule / register split, word caps** (maintainer observation): the
  always-loaded set was ~15,000 words × 660 sessions.
- **Denominator rule; empty-side probe** (problem 1): `identity_exact
  = 1` over zero compared items passed the free gate in e010-l1 and the
  same expression sat in four packages after `c537307` fixed one.
- **`carry`** (problem 2): 28 non-blocking lines, three came true
  (e011-l1 OOM → REPLAN; e007-l0 ensurepip → Triton JIT REPLAN;
  e010-l1 `__pycache__` → `cc4c156`).
- **Start once is existence; memory arithmetic** (problem 3): two of
  four REPLANs were runtime facts a single launch or a shape × dtype
  product would have shown at review.
- **Overview cap in `plan_problems()`** (problem 4): 39 → 1,657 lines;
  two sampled Generators skipped it.
- **Concept check in the Ask phase** (problem 5): `Concept.md` still
  described E007 through E011.
- **Auto-deferred Trial re-runs** (problem 6): `Audit: deferred` used
  once in 20 loops.
- **`pause-after` as a flag file** (problem 9): the key was overwritten
  by the running driver's next save (e007-l2b).
- **GPU-hours × `GPUs:`** (problem 9): 5.1 h on two GPUs billed 5.1.
- **`approve --note`** (problem 9): the note text was read as a gate
  name (e007-l1).
- **`__pycache__/` and `*.pyc` in `ensure_gitignore()`** (problem 2):
  five `.pyc` files committed by `git add -A`.
- **Red log in the output gate** (problem 10): 78 of 93 code tickets
  were code-first; the TDD rule had no mechanical check.
- **`approval_needs_human`** (problem 11): 22 gates in a median of
  36 s; Assumption 6 accepted at one of them.

### mode-loop (Ask phase) — moved in 8.1.21
- **Refuse on missing machinery, never degrade** (`journal/from-ccd-ai-bench-retro-20260715.md`):
  a project with the v8.0 CLAUDE.md and no driver ran a manual flow and
  recorded itself as an 8.0 run.
- **Never point a criterion at the answer; a stopping bar names its
  measurement** (v8.1.13, v8.1.15): `>= 0.90` as a tripwire escalated at
  0.8978, three calls short of 1067, eight hours after the science was
  finished; the real tripwire was `< 0.5` and the contract review had
  written it down (`journal/from-aibench-retro-20260819.md`,
  `journal/retro-20260824-aibench.md` gap A/B).
- **Probe lines for every number and fact** (v8.1.20): thirteen of
  thirty goals in one deployment, eleven of twenty-seven replans in
  another, the one loop rated *bad* ($74, zero measurement) — a count,
  a cap, a sha256, a premise, a bf16 tolerance below one ulp, a
  throughput bar from another path (PB pb10), a `.env` value the parser
  stripped (JEV loop 10), a class import as a runtime preflight (JEV
  loop 9) (`journal/retro-20261015-cross-project.md`, S2/R1).
- **Three questions per criterion** (v8.1.16): six criterion defects in
  four agentRl loops, five frozen contracts in nine aibench loops — a
  bar that read 1.0 on its control, a key the harness cannot emit, a
  numerator and denominator from one list.
- **Detectable effect; stop rule before the first read** (v8.1.17):
  three training loops ($251, ~100 GPU-h) ended "within one SE" of the
  same baseline because no Goal said what a 16-task slice could resolve
  (`journal/from-agentrl-retro-20260918.md`, problem 6).
- **`max_replans` by kind** (v8.1.20, R4): first-of-kind loops replanned
  3, 4, 2, 2, 2 times; re-runs 0, 0, 0, 0, 0.
- **Cadence by novelty** (v8.1.20, R3): the Evaluator was 33–62 % of
  spend across seven deployments; every outcome-changing catch was in a
  loop introducing a new mechanism; the two `final-pass` loops lost
  nothing (S3).
- **Full model IDs** (v8.1.16): a bare tier alias resolved differently
  on the day, so no journal could say which model ran a loop.
- **Generator on sonnet by default** (2026-10): JEV 19/19 first-attempt
  passes, STAGES 70 tickets, NVFP4, JEVI — zero Generator-side defects
  at about half the cost.
- **Runtime-path preflight** (`journal/from-aibench-retro-20260802.md`):
  three of seven human interruptions were a missing `[api]` extra, an
  incompatible `datasets`, a missing `transformers`, each at tickets
  7–8.
- **Gate concern dispositions** (v8.1.20, R2): the same concern
  acknowledged at four consecutive gates became a post-result 0.95 →
  0.94 amendment (PB problem 2).
- **Delegated approval answers every gate question first** (v8.1.20,
  R12): one loop approved past an unanswered question escalated on it
  four tickets later (JEV loop 4).
- **`start` does the mechanical steps** (2026-07-30 inbox): eight
  manual steps per loop, the gate banner invisible, `approve` in a
  second shell.
- **Fast path for audit findings** (mode-modify, v8.1.16): four manual
  `[modify]` loops in three hours for a two-line fix, rated *bad*
  (`journal/from-aibench-retro-20260902.md`, problem 6).
- **Harness staleness step; hot-patch inventory** (mode-retro, R11 /
  v8.1.20): three of seven retros noted the step was missing; four
  deployments patched the same three defects and none came home.

### 8.2.1 toy run (2026-10-25, ~/cdd-toy, $4.79, 21 min, 4/4 tickets)
- **`approval_needs_human` label is case-sensitive with a colon**: the
  first live gate matched the review's own heading "**Open
  assumptions.** Read all 5 ..." and raised the event on a review that
  had found nothing.
- **A shell comment is data on every net**: the Evaluator's
  `cp -r src tests scripts /tmp/eval_sandbox/   # restore clean copy`
  was denied as a write to 'copy'. Seventh false positive of the
  "decide on the token" class; the other four denials in the run were
  correct (in-tree `git checkout`, an in-tree Edit, two in-tree
  `rm results/metrics.json`).
- **`status` role column widened to 16** for `evaluator_audit`.
- Observed working: audit tier on haiku for tickets 1–3 and sonnet for
  the first green and final; `carry` written by the contract review,
  handed to every dispatch, marked resolved at the final audit; red
  logs on all four tickets (ticket 1's was a passing run — the gate
  checks presence, the planted failure checks validity); `approve
  --note`; `close` with `journal/raw/`.
