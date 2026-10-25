# Plan.md Task Ticket Format

Each execution step in Plan.md or Triage.md MUST follow this format.
The Generator executes these tickets mechanically. Goals of type
`experiment` use the experiment-ticket variant below. Rationale for
every rule here: `docs/loop-orchestration-design.md` §17 (framework
repo) and `git log -p` of this file.

## Template

```markdown
### Phase [N], Step [M]: [Descriptive Title]

**Input:** [Files/schemas the Generator reads from]
**Output:** [Exact files to create or modify]
**Spec:**
- [Concrete behavioral specification]
- [Function signatures with types]
- [Explicit error handling: what to catch, what to raise]
- [Edge cases to handle]

**Test Contract:**
- [test_name]: [input] → [expected output/behavior]
- [test_name]: [input] → [expected error type]
- [test_name]: [edge case] → [expected behavior]

**Manual Verification:**
- [What the user should inspect after tests pass]
- [Expected behavior from the user's perspective]
- [UX or integration checks that TDD cannot cover]

**Architecture:** [Sections of Architecture.md to read, comma-separated]
**Skills to Load:** @skills/[relevant-skill]/SKILL.md
**Reference Docs:** @docs/[file].md (Section: [Name])   ← optional
**Process Logging:** [Expensive | none]   ← optional, default none
**Audit:** [deferred]   ← optional; only a no-code Trial ticket on a proven harness
**Depends On:** [Ticket IDs that must complete first, or "none"]
**Parallel Group:** [Label, e.g. A | omit for sequential]   ← optional
**Boundary:** [Exact directories/files the Generator may touch]
**Run Command:** [Exact command] 2>&1 | tee logs/latest.log
```

## Field Definitions

**Input:** What exists before execution. Source files, schema definitions.

**Output:** Exact files to create or modify. Be specific.

**Spec:** Behavioral requirements. Typed function signatures, explicit
error types, edge cases. No judgment calls for the Generator.

**Test Contract:** Named test cases. Minimum: 1 success + 1 validation
error + 1 edge case.

**Manual Verification:** What the user checks after the full loop.
UX, visual, and integration concerns that TDD cannot catch.

**Architecture:** Which sections of `Architecture.md` the Generator
must load. The Overview is always loaded implicitly — list additional
sections (e.g. `API Surface, Data Models`). `Full` only if the ticket
genuinely needs the entire document.

**Skills to Load:** `@skills/` references for patterns and rules.

**Reference Docs:** Optional. Files in `docs/` that constrain the
implementation. When present, the Generator also reads
`docs/DEVIATIONS.md`.

**Process Logging:** Optional. `Expensive` when the ticket implements a
slow/costly pipeline; the Generator then emits structured stage logs
per `governance.md` §3. Default `none`.

**Audit:** Optional. `deferred` skips this ticket's per-ticket
Evaluator audit under any cadence; the deterministic gate, the
regression guard and the output gate still run, and a criterion's FIRST
green or the final pass is never deferred. The driver applies the same
skip on its own to a Trial ticket whose Generator changed nothing in
the tree. Never write it on a ticket that introduces a mechanism.

**Depends On:** Ticket IDs (Phase/Step) that must be committed before
this one starts; `none` for the first. Everything depends (directly or
transitively) on the Environment Setup ticket.

**Parallel Group:** Optional label. Tickets sharing it run concurrently
(`.claude/rules/parallel-execution.md`). Valid only with
**pairwise-disjoint Boundaries** and **no member depending on another
member**. The Environment Setup ticket is NEVER grouped. Group only
genuinely independent, non-trivial tickets.

**Boundary:** Every file the Generator may touch; anything outside
stops the session. A subdirectory `CLAUDE.md` inside it binds the
ticket.

**Run Command:** Exact shell command piped through
`2>&1 | tee logs/latest.log` (`run-logging.md`). **Under ten minutes,
or it is a `Trial:`** — a Generator's Bash call is capped at 600 s;
anything slower is launched by the driver, or detached (`nohup … &`)
and polled. **Chain the regression sweep with `;`, not `&&`**, so a
failing writer does not short-circuit the sweep.

## Experiment Tickets

For `experiment` goals, tickets REPLACE the Test Contract with:

**Hypothesis:** [what this trial should demonstrate]
**Trial:** [exact launch command; the DRIVER launches it — output goes
to logs/trial-<n>.log]
**Metrics Contract:** [metric names + the exact file each is written
to, e.g. results/<loop>/gate1.json]
**Success Threshold:** [metric vs value; maps 1:1 to goal.json criteria]
**Monitor Profile:** [known failure signatures; the run's known benign
noise listed as non-actionable; `stall_min: N`; `writes: <path>[, …]`]
**Deadline:** [`K × measured min/iteration × 1.5 = N min`, naming the
file the measurement came from]
**GPUs:** [N — the driver bills GPU-hours as wall time × N; default 1]
**Disk:** [bytes written per iteration/step, and what the trial deletes
as it goes]

All other fields are unchanged. Rules:

- **The Monitor Profile is where false kills are prevented.** Enumerate
  the run's own noise (per-call cost lines, a URL printed every call, a
  constant-zero task) as non-actionable, against the run's scar tissue,
  not a generic list.
- **`stall` is the driver's clock.** `stall_min` is sized from the run's
  longest legitimate silence (an eval pass, a checkpoint write), padded;
  `writes:` lists what the trial writes as it progresses. Without
  `stall_min` the driver never kills on stall.
- **`Deadline:` is arithmetic on a measured number, never a round one**;
  per domain when the mix changes the per-iteration time. A first run
  sizes from the smoke and says so. The driver reads it to size the
  poll and to warn, never to kill. The journal's `## Trials` section
  records each launch's actual wall time for the next Deadline.
- **A shared-fate trial writes its infrastructure errors.** When the
  trial pulls from a registry, a hub, a mirror or a gateway, the Metrics
  Contract names `n_infra_error` and `infra_error_rate`, and the Goal
  gates on the rate. A resume never re-summarises a finished job whose
  trials carry infrastructure exceptions.
- **`Disk:` is a contract.** K iterations × the figure < `df` at launch,
  or the trial rotates; show the arithmetic.
- Detailed about OUTCOMES and interfaces, light on implementation
  path. A launched trial's config is immutable; a parameter change is a
  new trial via REPLAN.

## Planner Self-Check

Before ending the Planner session, verify for each ticket:

- Could the Generator execute without asking questions? Every
  signature typed, every error case explicit, Test Contract specific
  enough to write tests from, Manual Verification concrete?
- Does the Boundary list every file that will be touched — including,
  for every symbol the ticket retires, renames or changes, each file
  that imports or calls it (grep the consumers)?
- Does **Architecture:** list every section the ticket needs?
- Is the ticket the minimum change? **Process Logging** set only for
  an expensive pipeline? Reference Docs listed, deviations logged?
- Is **Depends On** complete? Does a ticket that deletes or supersedes
  banked evidence depend on the ticket that PROVES the replacement?
- Can each Spec step be executed with only the inputs available at
  that point?
- Does some ticket's **Run Command** actually WRITE each `goal.json`
  criterion's `source` file? Is each `source` writable by **at most
  one** ticket, whose Boundary names the FILE, not its directory
  (`plan_problems()` enforces this)? Zero owners is legal on an
  `experiment` goal, where the driver launches the trial.
- Is each `source` a path only THIS loop can write (`evidence_gate()`
  refuses a stable pointer or an unversioned file)?
- Does the Environment Setup ticket's Run Command EXERCISE a pinned
  harness's runtime path, not only install it?
- Any Run Command over ~5 minutes is a `Trial:` or launched detached.
- **Every number** a Test Contract, tolerance, routing rule or Spec
  premise depends on names its probe (`probe: <command> → <output>` in
  `Goal.md`, or one you ran). A tolerance states its dtype and comes
  from a measured noise floor; a time bar for a path this loop has not
  run is `smoke × 1.5` at the run's actual concurrency; a buffer or
  tensor the Spec implies is sized (shape × dtype) against the device.
- **Every `*_ok` / `*_exact` / `*_match` flag or ratio names its
  denominator in the Spec and requires it ≥ 1.** A comparison over an
  empty set must read FAIL, never PASS; the Test Contract carries the
  empty-side case.
- Before the first GPU smoke of a new training path: is there a
  GPU-free config-probe ticket that trips every assertion the new argv
  can trip?
- If a replan's cause was an environment fact, does the fix ticket edit
  the environment script or the goal's preflight, not the Trial line?
- What does a stop after this ticket strand? Arm N's intermediates are
  deleted by the ticket that banks their LAST measurement; state the
  disk left behind on PASS and on a stop.
- For every **Parallel Group**: Boundaries pairwise disjoint, no
  intra-group dependency, Environment Setup kept out, grouping worth it?
- For experiment tickets: every Success Threshold maps to a `goal.json`
  criterion; the Metrics Contract names the exact file; `Deadline:` is
  K × MEASURED × 1.5 with its source; `GPUs:` matches the Trial's
  device count; the Profile carries `stall_min` and `writes:`; `Disk:`
  arithmetic fits `df` or the trial rotates.

Every gap becomes a potential Generator hallucination.

## `[Halt here]` Flags (manual mode only)

Placed by the user after reviewing Plan.md, never by the Planner. The
manual Generator (`start execution`) commits current work and stops at
a flagged ticket. **Loop mode ignores these flags**: the driver stops by
event (criteria gate, regression guard, budget caps, ESCALATE,
`pause-after`) and declares preconditions in `Goal.md`'s `Preflight`.
