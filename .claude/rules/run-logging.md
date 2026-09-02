# Run Logging (capture what actually ran)

This rule solves a concrete pain: to debug a failing run, you should
not have to copy-paste a terminal wall of text into the agent. Instead,
runs write their output to a file the agent can read on demand.

Run Logging (stdout/stderr capture of executed commands) is **distinct**
from Process Logging (`.claude/rules/governance.md §3`, in-code
structured stage logs for expensive pipelines). Both can apply at once.

## 1. The `logs/` convention

- Runs write to `logs/latest.log` (always the most recent run) and,
  optionally, a timestamped archive `logs/run-YYYYMMDD-HHMMSS.log`.
- `logs/` is gitignored — it is runtime output, not source. The Planner
  ensures `logs/` is in `.gitignore` (Environment Setup ticket).

## 2. How commands capture output

Any command whose output you may need later is piped through `tee`:

```bash
<command> 2>&1 | tee logs/latest.log
```

- The Planner writes Run Commands in this form in every task ticket
  (see `.claude/rules/task-ticket-format.md`).
- For the app/pipeline (not just tests), the Planner documents a launch
  command in the README that tees to `logs/latest.log` the same way.
- `2>&1` is mandatory so errors (stderr) are captured, not just stdout.

Keep it simple (Simplicity First): no bespoke logging harness, no log
rotation service. `tee` to a gitignored file is the whole mechanism.

## 3. The "check the latest run log" trigger

When the user says **"check the latest run log"** (or "check the latest
running log", "read the log and fix it", or similar):

1. Read `logs/latest.log`.
2. Identify the error: the failing stage, stack trace, or assertion.
3. Report the root cause concisely.
4. Route the fix through `[modify]` (its bug-investigation sub-flow) —
   do NOT edit `src/` outside a proper Planner → Generator cycle.

If `logs/latest.log` is missing, tell the user to re-run with the
`2>&1 | tee logs/latest.log` suffix (or via the README launch command).

## 4. Secrets

Never let secrets reach the log. The same rule as `governance.md §2`
applies: if a command would echo credentials, redact or avoid teeing
that command.
