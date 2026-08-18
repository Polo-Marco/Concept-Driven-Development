# Plan.md Task Ticket Format

Each execution step in Plan.md or Triage.md MUST follow this format.
The Generator executes these tickets mechanically.

Goals of type `experiment` (v8.0 loop) use the experiment-ticket
variant below.

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
must load for this ticket. The Overview section is always loaded
implicitly — list any additional sections needed (e.g.
`Overview, API Surface, Data Models`). Use `Full` only if the ticket
genuinely needs the entire document.

**Skills to Load:** `@skills/` references for patterns and rules.

**Reference Docs:** Optional. Pointers to files in `docs/` that
constrain the implementation (e.g. an API contract or design system).
When this field is present, the Generator also reads
`docs/DEVIATIONS.md` to know which parts of the spec have been
superseded.

**Process Logging:** Optional. Set to `Expensive` when the ticket
implements a slow/costly pipeline (OCR, long agentic chains, batch
jobs). The Generator then emits structured stage logs per
`.claude/rules/governance.md` §3. Default `none` — do NOT set it on
short, cheap functions (over-engineering).

**Depends On:** Ticket IDs (Phase/Step) that must be committed before
this ticket can start. Use `none` for the first ticket. Everything
depends (directly or transitively) on the Environment Setup ticket.
This is the dependency graph the Generator uses to know what is ready.

**Parallel Group:** Optional. A label (e.g. `A`, `B`). Tickets sharing a
label are dispatched concurrently by the Generator
(`.claude/rules/parallel-execution.md`). A group is valid only if its
members have **pairwise-disjoint Boundaries** and **no member depends on
another member**. Omit the field for sequential execution (the default).
The Environment Setup ticket is NEVER grouped — everything depends on
it. Only group genuinely independent, non-trivial tickets (Simplicity
First; grouping costs tokens).

**Boundary:** Every file the Generator may touch. Anything outside
triggers a session stop. If a directory in the Boundary has a
subdirectory `CLAUDE.md`, its conventions bind the ticket. Within a
Parallel Group, Boundaries MUST be pairwise disjoint — this is what
makes concurrent execution race-free.

**Run Command:** Exact shell command, copy-pasteable, piped through
`2>&1 | tee logs/latest.log` so the run's output is captured for
later diagnosis (see `.claude/rules/run-logging.md`). Example:
`uv run pytest tests/test_extractor.py -v 2>&1 | tee logs/latest.log`.

## Experiment Tickets (v8.0)

For `experiment` goals, tickets REPLACE the Test Contract with:

**Hypothesis:** [what this trial should demonstrate]
**Trial:** [exact launch command; the DRIVER launches it, not the
Generator — output goes to logs/trial-<n>.log]
**Metrics Contract:** [metric names + the exact file/path each is
written to, e.g. results/gate1.json]
**Success Threshold:** [metric vs value; must map 1:1 to goal.json
criteria]
**Monitor Profile:** [poll interval; known failure signatures, e.g.
cuda_oom, nan_loss, stall]

All other fields (Boundary, Depends On, Architecture, Skills to Load)
are unchanged. Spec granularity rule: experiment tickets are detailed
about OUTCOMES and interfaces, light on implementation path — granular
technical detail specified upfront cascades errors when wrong.
Provenance: a launched trial's config is immutable; any parameter
change = new trial via REPLAN (see .claude/rules/loop-protocol.md).

## Planner Self-Check

Before ending the Planner session, verify for each ticket:
- Could the Generator execute without asking questions?
- Is every function signature typed?
- Is every error case explicit?
- Does the Boundary list every file that will be touched?
- Is the Test Contract specific enough to write tests from?
- Does Manual Verification tell the user exactly what to check?
- Does the **Architecture:** field list every section the ticket needs?
- Is the ticket scoped to the minimum change (no speculative work)?
- If it's an expensive/long-running pipeline, is **Process Logging**
  set to `Expensive`?
- If a Reference Doc applies, is it listed (and any deviation logged
  in `docs/DEVIATIONS.md`)?
- Is **Depends On** correct — does it list every ticket whose output
  this one consumes?
- Does some ticket's **Run Command** actually WRITE each `goal.json`
  criterion's `source` file? On `build`/`modify` goals the driver runs
  nothing of its own, so a metrics file produced only by a human step —
  or sitting behind an `if __name__ == "__main__"` that no Run Command
  invokes — makes every ticket pass and the final criteria gate
  escalate on numbers that were never written.
- And its converse: is each criterion's `source` file writable by **at
  most one** ticket, and does that ticket's **Boundary** name the FILE
  rather than its parent directory? A whole-tree entry (`results/`) on
  a ticket that does not produce the evidence lets anything running in
  that session — a test fixture, a default output path — write the file
  its own criteria are read from. On 2026-07-31 `results/` sat in four
  tickets' Boundaries; a schema ticket's fixture wrote `acc=0.6` and
  three criteria read green four iterations before the harness existed.
  The driver enforces this before paying for a contract review
  (`plan_problems()`), so a plan that fails it comes straight back.
  Zero owners is legal: on an `experiment` goal the driver launches the
  trial, so its metrics file belongs in no Boundary at all.
- Is each criterion's `source` a path only THIS loop can write? A
  stable pointer (`results/<bench>/latest.json`) or a single unversioned
  file (`results/test-summary.json`) carries the previous loop's number
  into this one, and `check_criteria()` reads the file, not the run.
  The driver refuses such a start (`evidence_gate()`), so a plan that
  assumes one never gets written; the Planner's job here is to make
  every Run Command WRITE the versioned path the criteria name, not a
  convenience alias next to it.
- If the plan pins a third-party harness/framework, does the
  Environment Setup ticket's **Run Command** EXERCISE its runtime path
  (import + one trivial invocation, e.g. registering the expected
  task) rather than only installing it? An install that succeeds
  proves nothing about the runtime dependency graph, and each missing
  link then surfaces alone, in a later ticket, as a Generator stop
  (2026-08-02: three escalations at tickets 7–8 for one under-tested
  Step 1). This is the second net — the first is a `Preflight` check in
  `Goal.md`, which fails before the Planner is paid for at all
  (`skills/mode-loop/SKILL.md` §3).
- For every **Parallel Group**: are the members' Boundaries pairwise
  disjoint, and does no member depend on another member? Is the
  Environment Setup ticket kept out of all groups? Is grouping actually
  worth it (multiple independent, non-trivial tickets)?
- For each Spec step: can it be executed with only the inputs
  available at that point? A circular or unsatisfiable step leaves the
  Generator no legal move but to stop.
- For experiment tickets: does every Success Threshold map to a
  goal.json criterion, and does the Metrics Contract name the exact
  file the driver/Evaluator will read?

Every gap becomes a potential Generator hallucination.

## `[Halt here]` Flags (manual mode only)

The Planner does NOT place `[Halt here]` flags. These are placed
by the user after reviewing Plan.md. When the Generator encounters
a ticket with `[Halt here]`, it commits current work and stops.

**Loop mode ignores these flags** (v8.1). The driver never reads them —
it never did — and `[/loop]` no longer asks you to place them. A
pre-placed pause requires guessing which ticket will need inspection
before any output exists; loop mode replaces that with event-driven
stops (deterministic criteria gate, regression guard, budget caps,
ESCALATE) and declares environment preconditions up front via the
`Preflight` section of `Goal.md`. The flag remains live for the manual
`start execution` escape hatch (`generator-protocol.md` §3f).
