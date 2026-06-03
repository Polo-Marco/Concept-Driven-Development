# Global Governance & Safety

These rules apply at ALL times, regardless of mode or session type.
They sit alongside the Core Principles in
`.claude/rules/principles.md` (Simplicity First, Surgical Changes,
Think Before Coding), which are equally always-on.

## 1. Version Control (Git)

### Commit Conventions
- Semantic prefixes: `plan:`, `feat:`, `fix:`, `refactor:`, `migrate:`.
- **Planner Session:** one commit at session end covering all core files.
- **Generator Session:** one commit per completed ticket.
- **Evaluator Session:** does NOT commit. `Evaluation.md` is ephemeral.
- Commit messages must be detailed and informative — they serve as the
  project's progress log. Include what was built, which files changed,
  and any notable decisions.

### Commit Message Format
```
feat: implement PDF extraction pipeline

- Created src/pipeline/extractor.py with extract_text()
- Handles PDF, DOCX, plain text formats
- Raises ExtractionError on corrupt/unsupported files
- Added tests: test_extractor.py (3 passing)
```

One domain per commit. No unrelated changes bundled.

## 2. Security & Secrets

- **NO HARDCODING.** API keys, URIs, credentials → `.env` (in `.gitignore`).
- Never leak sensitive data into logs or UI traces.

## 3. Process Logging for Expensive Pipelines (opt-in)

Long or expensive operations — OCR, multi-stage agentic pipelines,
batch jobs, anything slow or costly to re-run — are painful to debug
because reproducing a failure burns time and money.

When the Planner flags a ticket as implementing such a pipeline, the
generated code MUST emit **structured stage logs**:

- One log line per pipeline stage: stage name, a short summary of
  inputs (NOT raw payloads / secrets), start/end or duration, and
  success/failure with the error.
- Use the language's standard logging facility (e.g. Python `logging`),
  not `print`. Default level INFO for stage boundaries, ERROR on
  failure.
- Never log secrets or full sensitive payloads (see §2).

Scope guard (anti-over-engineering, per `principles.md`): this is
**logging only** — no checkpointing, no result caching, no bespoke log
framework. Apply it ONLY to pipelines the Planner explicitly flags as
expensive/long-running. Short, cheap functions do not get this
treatment.

## 4. Test-Driven Development

- Write tests before application logic.
- TDD is the automated sanity check. It catches regressions and proves
  basic functionality.
- The user is the final evaluator. TDD does not replace human judgment.
  The optional `[/evaluate]` session produces a checklist; the user
  still signs off.

## 5. Core File Lifecycle

| File | Lifecycle | Purpose |
|---|---|---|
| `Concept.md` | Persistent, evolving | Vision, scope, principles |
| `Architecture.md` | Persistent, evolving (layered) | System design source of truth |
| `CHANGELOG.md` | Persistent, append-only | What changed, when |
| `Plan.md` | **Ephemeral** — deleted after full loop | Task tickets |
| `Triage.md` | **Ephemeral** — deleted after full loop | Bug hypotheses |
| `Architecture-<source>.md` / `Merge-Analysis.md` | **Ephemeral** — `[/merge]` working artifacts, deleted after sign-off | Per-source models + conflict map |
| `Evaluation.md` | **Ephemeral** — deleted after user signs off | Evaluator verdict + audits |
| `skills/` | Persistent, evolving | Execution patterns and rules |
| `**/CLAUDE.md` (nested) | Persistent, evolving | Module-specific conventions (Planner-maintained) |
| `docs/*.md` | Persistent, user-maintained | External reference docs (immutable to agents) |
| `docs/DEVIATIONS.md` | Persistent, planner-appendable | Tracked departures from reference docs |

Only one of Plan.md or Triage.md exists at a time. When the full loop
(Planner + Generator + optional Evaluator + user evaluation) completes
successfully, the user deletes the work order file and any
`Evaluation.md`. They served their purpose.
