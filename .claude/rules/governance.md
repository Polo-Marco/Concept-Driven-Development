# Global Governance & Safety

These rules apply at ALL times, regardless of mode or session type.
They sit alongside the Core Principles in
`.claude/rules/principles.md` (Simplicity First, Surgical Changes,
Think Before Coding), which are equally always-on.

## 1. Version Control (Git)

**Git history is the changelog.** There is no `CHANGELOG.md`. The full
project history lives in git and any session may read it
(`git log --oneline`, `git log -p <file>`,
`git diff <planner-commit>..HEAD`). Because history replaces a curated
changelog, commit messages carry that weight and MUST be detailed.

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
- **Loop mode (v8.0):** the driver is the only committer.
  `plan(loop):` for everything the plan phase produced, committed the
  moment its human gate clears (v8.1.7 — without it the first ticket
  commit carried Plan.md, Evaluation.md, Architecture.md and a user
  budget edit under one ticket's title, breaking "one domain per
  commit" below and making a per-ticket Boundary audit unpassable);
  `feat(loop):` per passed ticket (verdict + evidence in the body),
  `wip(loop):` before a replan or on escalation. Sessions never
  commit inside a loop.
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

**Run Logging is separate.** Capturing the stdout/stderr of executed
commands to `logs/latest.log` (so a failing run can be diagnosed
without pasting a terminal wall of text) is governed by
`.claude/rules/run-logging.md`. It applies to every run, not just
expensive pipelines.

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
| `README.md` | Persistent, evolving | User-facing: install, run, test, use |
| `Plan.md` | **Ephemeral** — deleted after full loop | Task tickets |
| `Triage.md` | **Ephemeral** — deleted after full loop | Bug hypotheses |
| `Architecture-<source>.md` / `Merge-Analysis.md` | **Ephemeral** — `[/merge]` working artifacts, deleted after sign-off | Per-source models + conflict map |
| `Evaluation.md` | **Ephemeral** — deleted after user signs off | Evaluator verdict + audits |
| `Goal.md` + `goal.json` | **Ephemeral** — frozen at loop start, deleted after sign-off | User-owned goal contract (v8.0) |
| `ledger.jsonl` | **Ephemeral** — summarized into `journal/` at loop end, then deleted | Trial memory for REPLANs (driver-written) |
| `loop-state.json` / `events.jsonl` | Ephemeral, gitignored | Driver state (crash resume) + event feed |
| `verdict.json` | **Ephemeral** | Machine verdict (Evaluator → driver) |
| `journal/*.md` | Persistent | Per-loop session records + user feedback (for `[/retro]`) |
| `journal/traces/*.jsonl` | Persistent, gitignored | Full raw session transcripts (Tier 2, Claude Code hook) |
| `skills/` | Persistent, evolving | Execution patterns and rules |
| `**/CLAUDE.md` (nested) | Persistent, evolving | Module-specific conventions (Planner-maintained) |
| `docs/*.md` | Persistent, user-maintained | External reference docs (immutable to agents) |
| `docs/DEVIATIONS.md` | Persistent, planner-appendable | Tracked departures from reference docs |
| `docs/inbox.md` | Persistent, discuss-appendable | Raw idea capture, promoted into Concept/docs via `[/discuss]` |
| `logs/latest.log` | Ephemeral, gitignored | Most recent run's stdout/stderr (see run-logging.md) |
| `logs/denials.log` | Ephemeral, gitignored | Every PreToolUse authority denial (hook-written; the driver counts it into a `hook_denials` event) |

There is no `CHANGELOG.md` — git history is the changelog (see §1).

Only one of Plan.md or Triage.md exists at a time. When the full loop
(Planner + Generator + optional Evaluator + user evaluation) completes
successfully, the user deletes the work order file and any
`Evaluation.md`. They served their purpose.

## 6. Session Journal (development-process tracking)

The `journal/` directory records the *development process itself* — not
the code — so the user can later re-evaluate how a project was built and
improve the framework (via `[/retro]`). It has two tiers:

**Tier 1 — curated summary (`journal/*.md`, primary).**
A short, agent-written record per loop. This is what `[/retro]` reasons
over. It is NOT a full trace — it captures decisions, not every tool
call.

- **One file per pipeline loop:** `journal/YYYYMMDD-HHMMSS-<mode>.md`
  (e.g. `journal/20260701-142230-modify.md`).
- **In loop mode the DRIVER writes it** (v8.1.6), from `ledger.jsonl` +
  `loop-state.json` + `events.jsonl`, on every terminal exit — done,
  escalation or crash — and rewrites it on resume. Sessions inside a
  loop append nothing; they have no state the ledger lacks. The one
  part the driver never touches is the `## Feedback` block.
- **In manual sessions each session appends its own record** to the
  current loop's file: the Planner appends what it planned and why; the
  Generator appends what it built, commits (SHAs), and any
  stops/retries; the Evaluator appends its verdict.
- **The user fills the `## Feedback` block** at loop end: a rating
  (good / ok / bad), what went well, and — critically — any
  *instruction that was not followed*.
- Keep records short and factual. This is a log, not an essay.

**Tier 2 — full raw trace (`journal/traces/*.jsonl`, optional, Claude
Code only).**
The complete session transcript — every tool call, input, output, and
decision — captured automatically by the `SessionEnd` hook in
`.claude/settings.json` (script: `.claude/hooks/archive_transcript.py`).
Use it to dissect a loop you flagged "bad"; `[/retro]` drills into it on
demand. Cursor has no equivalent, so Tier 2 is Claude-Code-only; Tier 1
works in both tools.

- Traces can be large and may contain sensitive context, so
  `journal/traces/` is **gitignored** — the curated `journal/*.md`
  summaries stay in git, the raw traces stay local.
- The agent does NOT write Tier-2 files; the hook does. Never
  hand-reconstruct a trace into `journal/traces/`.

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

## Feedback (filled by user)
- Rating: [good | ok | bad]
- What went well:
- Instruction(s) not followed:
- Notes:

## Full trace
[journal/traces/<timestamp>-<session>.jsonl — auto-archived by the
SessionEnd hook, Claude Code only. "none" if running under Cursor.]
```
