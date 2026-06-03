# Plan.md Task Ticket Format

Each execution step in Plan.md or Triage.md MUST follow this format.
The Generator executes these tickets mechanically.

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
**Boundary:** [Exact directories/files the Generator may touch]
**Run Command:** [Exact command to run tests for this step]
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

**Boundary:** Every file the Generator may touch. Anything outside
triggers a session stop. If a directory in the Boundary has a
subdirectory `CLAUDE.md`, its conventions bind the ticket.

**Run Command:** Exact shell command. Copy-pasteable.

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

Every gap becomes a potential Generator hallucination.

## `[Halt here]` Flags

The Planner does NOT place `[Halt here]` flags. These are placed
by the user after reviewing Plan.md. When the Generator encounters
a ticket with `[Halt here]`, it commits current work and stops.
