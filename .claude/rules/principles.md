# Core Engineering Principles

These principles apply at ALL times, across every mode and session
type. They bias the framework toward minimal, intentional change —
the opposite of speculative over-engineering. When a principle and a
ticket spec genuinely conflict, follow the spec and surface the
conflict; never silently expand scope.

## 1. Simplicity First (Planner + Generator)

Write the minimum code that satisfies the requirement. Nothing
speculative.

- No features beyond what the ticket asks for.
- No abstractions for single-use code.
- No "flexibility" or configurability that wasn't requested.
- No error handling for impossible scenarios.
- If the implementation could be half the size, rewrite it.

Test: "Would a senior engineer call this overcomplicated?" If yes,
simplify before committing.

This principle is what the Evaluator audits for redundancy, and what
the Planner enforces when sizing tickets.

## 2. Surgical Changes (Generator-weighted)

Touch only what the ticket requires. Clean up only your own mess.

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match the existing style, even if you'd do it differently.
- Remove imports/variables/functions that YOUR change orphaned.
- If you notice pre-existing dead code, flag it — do NOT delete it
  unless a ticket says to.

Test: every changed line should trace directly to the ticket. This
sharpens the Generator's **Boundary** discipline — Boundary says
*which files*; this says *how little* within them.

## 3. Think Before Coding (Planner-weighted)

State assumptions explicitly. Don't hide confusion. Surface
trade-offs before building.

- If multiple interpretations exist, present them — don't pick one
  silently.
- If a simpler approach exists, say so during the Ask phase.
- If something is unclear, stop and name what's confusing.

This is the "Concept-driven" half of the pipeline: the Planner aligns
on intent before the Generator writes a line. It reinforces — does not
replace — the per-mode Ask phase.
