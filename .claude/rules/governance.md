# Global Governance & Safety

These rules apply at ALL times, regardless of mode or session type.
They sit alongside the Core Principles in
`.claude/rules/principles.md` (Simplicity First, Surgical Changes,
Think Before Coding), which are equally always-on.

## 1. Version Control (Git)

**Git history is the changelog.** There is no `CHANGELOG.md`. Any
session may read history (`git log --oneline`, `git log -p <file>`,
`git diff <planner-commit>..HEAD`). Because history replaces a curated
changelog, commit messages MUST be detailed.

### Commit Conventions
- Semantic prefixes: `plan:`, `feat:`, `fix:`, `refactor:`, `migrate:`,
  `docs:`.
- **Discuss Session:** optionally one `docs:` commit for confirmed
  doc/Concept edits. No code.
- **Planner Session:** one commit at session end covering all core files.
- **Generator Session:** one commit per completed ticket.
- **Evaluator Session:** does NOT commit. `Evaluation.md` is ephemeral.
- **Retro Session:** does NOT commit code. May commit its `journal/`
  summary.
- **Loop mode:** the driver is the only committer. `plan(loop):` for
  everything the plan phase produced, committed the moment its human
  gate clears; `feat(loop):` per passed ticket (verdict + evidence in
  the body); `wip(loop):` before a replan or on escalation. Sessions
  never commit inside a loop.
- Commit messages must be detailed and informative — they ARE the
  project's changelog. Include what was built, which files changed,
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

When the Planner flags a ticket as implementing a long or expensive
pipeline (OCR, multi-stage agentic chains, batch jobs), the generated
code MUST emit **structured stage logs**:

- One log line per pipeline stage: stage name, a short summary of
  inputs (NOT raw payloads / secrets), start/end or duration, and
  success/failure with the error.
- Use the language's standard logging facility (e.g. Python `logging`),
  not `print`. INFO for stage boundaries, ERROR on failure.
- Never log secrets or full sensitive payloads (see §2).

Scope guard: this is **logging only** — no checkpointing, no result
caching, no bespoke log framework — and only for pipelines the Planner
explicitly flags.

**Run Logging is separate.** Capturing the stdout/stderr of executed
commands to `logs/latest.log` is governed by
`.claude/rules/run-logging.md` and applies to every run.

## 4. Test-Driven Development

- Write tests before application logic. TDD catches regressions and
  proves basic functionality; the user is the final evaluator.
- **No permanent test reads the live loop contract** (`goal.json`,
  `Goal.md`) or any other ephemeral loop artifact. Fixtures carry their
  own copy.
- **No test writes under a criterion's `source` tree** (`results/` or
  whatever the goal names). Every default output path a writer has is
  redirected by an autouse fixture into the test's own tmp dir, and no
  test undoes that redirection.

## 5. Core File Lifecycle

| File | Lifecycle | Purpose |
|---|---|---|
| `Concept.md` | Persistent, evolving | Vision, scope, principles |
| `Architecture.md` | Persistent, evolving (layered) | System design source of truth |
| `README.md` | Persistent, evolving | User-facing: install, run, test, use |
| `Plan.md` | **Ephemeral** — deleted after full loop | Task tickets |
| `Triage.md` | **Ephemeral** — deleted after full loop | Bug hypotheses |
| `Architecture-<source>.md` / `Merge-Analysis.md` | **Ephemeral** — `[merge]` working artifacts | Per-source models + conflict map |
| `Evaluation.md` | **Ephemeral** — deleted after user signs off | Evaluator verdict + audits |
| `Goal.md` + `goal.json` | **Ephemeral** — frozen at loop start, deleted by `close` | User-owned goal contract |
| `ledger.jsonl` | **Ephemeral** — copied to `journal/raw/<record>/` by `close`, then deleted | Trial memory for REPLANs (driver-written) |
| `loop-state.json` / `events.jsonl` | Ephemeral, gitignored | Driver state (crash resume) + event feed |
| `verdict.json` | **Ephemeral** | Machine verdict (Evaluator → driver) |
| `journal/*.md` | Persistent | Per-loop session records + user feedback (for `[retro]`) |
| `journal/traces/*.jsonl` | Persistent, gitignored; written into the PRIMARY tree | Full raw session transcripts (Tier 2, Claude Code hook) |
| `journal/raw/<record>/` | Persistent | `ledger.jsonl` + `events.jsonl` of a closed loop |
| `skills/` | Persistent, evolving | Execution patterns and rules |
| `**/CLAUDE.md` (nested) | Persistent, evolving | Module-specific conventions (Planner-maintained) |
| `docs/*.md` | Persistent, user-maintained | External reference docs (immutable to agents) |
| `docs/DEVIATIONS.md` | Persistent, planner-appendable | Tracked departures from reference docs |
| `docs/inbox.md` | Persistent, discuss-appendable | Raw idea capture, promoted via `[discuss]` |
| `logs/latest.log` | Ephemeral, gitignored | Most recent run's stdout/stderr |
| `logs/denials.log` | Ephemeral, gitignored | Every PreToolUse authority denial |

Only one of Plan.md or Triage.md exists at a time. When the full loop
completes, the user deletes the work order and any `Evaluation.md`.

## 6. Session Journal (development-process tracking)

`journal/` records the *development process itself* — not the code —
so `[retro]` can improve the framework. Two tiers:

**Tier 1 — curated summary (`journal/*.md`, primary).** A short record
per loop: decisions, not every tool call.

- One file per pipeline loop: `journal/YYYYMMDD-HHMMSS-<mode>.md`.
- **In loop mode the DRIVER writes it** from `ledger.jsonl` +
  `loop-state.json` + `events.jsonl`, on every terminal exit, and
  rewrites it on resume. Sessions inside a loop append nothing. The
  driver never touches the `## Feedback` block.
- **In manual sessions each session appends its own record**: the
  Planner what it planned and why; the Generator what it built, commit
  SHAs, stops/retries; the Evaluator its verdict.
- **The `## Feedback` block** is filled at loop end: `Filled by:
  user | operator under delegation`, a rating (good / ok / bad), what
  went well, and any *instruction that was not followed*. `loop.py
  close` refuses a template block. Under delegation the operator fills
  it; one line in the user's own words is still what `[retro]` cannot
  get anywhere else.
- Keep records short and factual.

**Tier 2 — full raw trace (`journal/traces/*.jsonl`, Claude Code
only).** The complete transcript, captured by the `SessionEnd` hook
(`.claude/hooks/archive_transcript.py`) into the PRIMARY tree's
`journal/traces/` even when the session ran in a worktree. Gitignored
(large, possibly sensitive). The agent never writes Tier-2 files.

Suggested per-loop skeleton:

```markdown
# Session Journal — <mode> — <date>

## Request
[What the user asked for]

## Planner
[Key decisions, files written, open questions]

## Generator
[Tickets executed, commits (SHAs), stops/retries, run-log notes]

## Evaluator
[Verdict + top findings, or "skipped"]

## Feedback
- Filled by: [user | operator under delegation]
- Rating: [good | ok | bad]
- What went well:
- Instruction(s) not followed:
- Notes:

## Full trace
[journal/traces/<timestamp>-<session>.jsonl — auto-archived by the
SessionEnd hook, Claude Code only. "none" if running under Cursor.]
```
