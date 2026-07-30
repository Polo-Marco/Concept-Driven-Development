# Session Journal — Maintainer (v8.0 draft) — 2026-07-14

## Request
Resolve the design doc's open questions and draft the full v8.0
framework (loop orchestration).

## Decisions (user-confirmed)
- Driver: Python stdlib, `.claude/driver/loop.py`.
- Remote control: Claude Code Remote Control via a control-tower
  interactive session + flag files; push via optional `notify.sh`
  (ntfy/Telegram) later.
- Model tiers: Opus Planner/Evaluator, Sonnet Generator, Haiku Monitor.
- Scope: full v8.0 file set in one session.
- Assumed (stated, not asked): budgets = iterations + wall-clock hard
  caps, GPU-hours = trial wall-clock, token cost logged best-effort;
  crash-resume via loop-state.json; Ask phase interactive.

## Maintainer record
Drafted to `v8.0-draft/` (session could not write `.claude/` — staged
as `_claude/`, see `v8.0-draft/INSTALL.md`):
- 4 agent defs, enforce_authority.py (PreToolUse), settings.json,
  loop.py driver (+notify.sh.example), loop-protocol.md rule,
  mode-loop skill, CLAUDE.md v8.0, PATCHES.md (task-ticket-format,
  phase-authority, governance, README), INSTALL.md.
- Evidence trail: feedback-inbox 2026-07-14 (5 items) +
  from-tcocrai-retro-20260713-2.md (all 6 recommendations addressed:
  #1 agents+hook, #2 per-ticket dispatch+commit in driver, #3 neutral
  evaluator framing + no self-assessment handoff, #4 partial — driver
  events + session reports, #5 hook denies planner src/ writes,
  #6 satisfiability in self-check + independent contract review) +
  docs/loop-orchestration-design.md (external guidance §14).

## Not done / follow-ups
- PATCHES.md must be applied by hand (protected paths).
- loop.py untested — INSTALL.md has the M1/M2 verification sequence.
- Full README "What's New in 8.0" section at ship time.
- Retro rec #4 (full worker traces) only partially addressed.
- Version tag v8.0 only after verification.

## Feedback (filled by user)
- Rating: [good | ok | bad]
- What went well:
- Instruction(s) not followed:
- Notes:
