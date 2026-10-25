# Loop Protocol

The `[loop]` pipeline: a deterministic driver orchestrates fresh
Planner / Generator / Evaluator / Monitor sessions until the goal's
success criteria are verifiably met — or the loop escalates to the
user. This file states the rules. The incident behind each one lives in
`docs/loop-orchestration-design.md` §17 (framework repo) and in
`git log -p` of this file; a session needs neither.

## Control principles

1. **The driver is dumb.** `.claude/driver/loop.py` is a deterministic
   state machine. It spawns sessions, parses JSON artifacts, branches
   on verdicts, enforces budgets, owns long-running processes, and is
   the ONLY thing that commits during a loop. The Planner calls nobody.
2. **Sessions are fresh and short.** Each phase runs headless
   (`claude -p`) with selective context and a role-specific agent
   definition (`.claude/agents/cdd-*.md`). Process boundary = session
   boundary.
3. **Authority is enforced.** The PreToolUse hook
   (`.claude/hooks/enforce_authority.py`) denies git writes, Boundary
   breaches and protected-file edits per role (`CDD_ROLE` /
   `CDD_BOUNDARY`). A denial means STOP and report; working around it
   is a protocol violation. `--dangerously-skip-permissions` skips
   prompts, not hooks.
   - `Write`/`Edit` are decided exactly. `Bash` is scanned for write
     targets (redirects, `tee`, `sed -i`, `mv`/`cp`, `rm`, `dd`) and
     git subcommands, deciding on the RESOLVED target, never on a
     token: a redirect's own syntax, a quoted span, a heredoc body and
     a `grep` pattern are data; `cd` and assignments are tracked per
     shell segment; anything still unresolved (`$VAR`, an interpreter
     escape such as `python3 -c`) fails OPEN by design. Real
     confinement is the VM plus the worktree, not the hook.
   - `/tmp` is scratch for every role: the resolved path must be
     outside the repo AND under `/tmp`; a symlink is decided as its
     target. `logs/` stays writable for roles that execute a Run
     Command; the Monitor writes nothing.
   - Every denial is appended to `logs/denials.log` and surfaces as a
     `hook_denials` event. Denying a command that merely NAMES a
     protected file is a hook defect: report it as a hotfix, do not
     route around it.
4. **Goal immutability.** `Goal.md` + `goal.json` are user-owned; no
   session edits them. Change of goal = user edits + fresh loop. One
   bounded exception: the driver re-reads `criteria` when a plan or
   replan gate clears and records the diff as `criteria_amended`.
   Between gates nothing re-reads the key.
5. **Trial provenance.** A launched trial's config is immutable.
   Crash-recovery with an identical config may reuse the trial ID; any
   parameter change = new trial ID via REPLAN, recorded in the ledger.
6. **Anything rule-bound is decided by code, not by a model.** Five
   gates run before anything is spent: `machinery()`, `validate_goal()`,
   `require_isolation()`, `preflight()`, `evidence_gate()` (nothing may
   already exist at a path a criterion reads). `plan_problems()` sends
   a plan back before a review is paid for when more than one ticket
   can write a criterion's `source`, or a Boundary names its tree
   instead of the file. `check_criteria()` reads every criterion off
   disk. All fail CLOSED.
7. **Deterministic is necessary, not sufficient.** `check_criteria()`
   proves a number met its bar, not that it was earned. Provenance is
   the Evaluator's, which must EXECUTE rather than read. A criterion is
   identified by `metric@source`; it is evidence only once the ticket
   that owns its `source` has run (`criteria_due()`), and the iteration
   where it FIRST reads green always buys an audit, under any cadence.
   Give each criterion a `source` only THIS loop can write — a stable
   pointer such as `results/<bench>/latest.json` is refused at start.

## The loop

```
goal.json → [gates: machinery, contract shape, isolation, preflight, evidence]
          → Planner → Evaluator contract review (OK|REVISE)
          → HUMAN GATE (approve once; also after each REPLAN)
          → `plan(loop):` commit of everything the plan phase produced
          → per ticket: Generator (bearings + smoke test → TDD/impl)
                        → driver launches Trial, Monitor polls
                        → output gate + check_criteria() + regression guard
                        → Evaluator → verdict.json  (cadence-dependent)
          → PASS: driver marks [x], commits `feat(loop):`, next ticket
            RETRY: same ticket, ≤3 attempts, each carrying the last verdict
            REPLAN: `wip(loop):`, fresh Planner + ledger, re-gated
            ESCALATE: stop, notify user
          → final: check_criteria() hard gate, THEN Evaluator provenance
          → loop.py close: journal record, housekeeping
```

## What the driver guarantees

Sessions rely on these; none of them is a session's job.

- **Contract review** is bought at most twice per plan phase and only
  while the pre-gate phases have spent under half of `max_usd`; the
  first review is always bought. Rounds bought because the last said
  REVISE count toward `budgets.max_review_rounds` (default 6) across
  replans; the first review of each plan phase does not. A verdict is
  remembered with the hash of the `Plan.md` it judged. The gate banner
  states whether the plan was reviewed OK or the review was cut short.
- **Commits**: `plan(loop):` the moment a gate clears, `feat(loop):`
  per passed ticket, `wip(loop):` before a replan or escalation.
- **A retry carries WHY**: attempt 2+ receives the verdict that
  rejected the last one. A Generator that changed nothing twice is
  escalated, except when the retry exists to relaunch a trial that did
  not complete.
- **Output gate**: before any audit, every **Output:** path the
  Boundary covers exists, a ticket with a Run Command left a log
  written during this dispatch, a ticket with a Test Contract left its
  first failing test run in `logs/tdd-red-<n>.log`, and no criterion
  the ticket OWNS reads red. A miss is a RETRY naming what is missing;
  no audit is bought.
- **Audit cadence**: a criterion's first green and the final pass are
  always audited. A per-ticket audit is skipped for `Audit: deferred`
  and, automatically, for a Trial ticket whose Generator changed
  nothing in the tree (a harness re-run).
- **Carry**: a verdict's `carry` lines (findings judged non-blocking)
  are kept in `loop-state.json` and handed to every later Generator
  dispatch, every later audit and the final audit, which must mark each
  resolved or not applicable.
- **Verdict routing**: metric failures → RETRY/REPLAN; protocol
  failures (Boundary breach, worker death, missing artifact) →
  ESCALATE. Trial budget is never spent on a defect no trial can fix.
- **Adjudication (Mode 3)** instead of auto-escalation for: a
  Generator `STATUS: stopped`, an exhausted retry cap (RETRY granted
  once more, with what must change), and a trial that dies twice
  identically in one iteration. Routes REPLAN / RETRY / ESCALATE;
  fail-CLOSED — an adjudicator that wrote nothing decides nothing.
- **Dead sessions**: a non-zero exit, or a result carrying
  `is_error: true`, is re-dispatched once. When both dispatches die of
  the connectivity class the driver stops its runtime clock, emits
  `network_wait`, probes every 60 s up to `budgets.max_network_wait_min`
  (default 120) and re-dispatches on `network_restored`; a Generator
  dispatch that dies this way is NOT an attempt and escalates as
  `infrastructure`. A live Evaluator that wrote no verdict is asked
  once more (`verdict_missing`).
- **Monitor**: the driver polls, acts and kills; the Monitor only
  classifies. `stall` is the driver's clock — `now − max(mtime(trial
  log), mtime(Profile writes:))` against `stall_min`; no `stall_min`,
  no stall kill. A kill whose quoted evidence sat in a window a prior
  poll judged HEALTHY is overruled (`monitor_overruled`). `Deadline:`
  sizes the poll to the longer of the Profile's and Deadline/30, is
  reported to every poll, and emits `deadline_exceeded` once at 1.5×;
  it never kills on its own.
- **Preflight** runs on every start; a check with `"when":
  "first-start"` is skipped on resume (`preflight_skipped`).
- **GPU-hours** are a trial's wall time × its ticket's `**GPUs:**`
  (default 1); `max_gpu_hours` bounds that number.
- **Budgets are hot-reloadable** from the WORKTREE's `goal.json` every
  iteration (criteria stay frozen). `start` seeds the goal files into
  a fresh worktree once and never overwrites them. `max_wall_hours`
  meters driver runtime, not the calendar: the clock stops at gates and
  between runs. Every restart consumes an iteration; size
  `max_iterations` with headroom.
- **A replan that fixes an environment fact fixes the environment**:
  when the ledger's reason is a `PATH`, cache, driver or library
  version, the fix ticket edits the project's environment script or
  adds a `Preflight` check — never only the Trial line.

## Monitor

While a trial runs the driver spawns `cdd-monitor` (cheap model) each
poll with the log tail, the Monitor Profile, its last three verdicts
and the driver's stall measurement. It returns
`HEALTHY | INTERVENE | KILL_ESCALATE`; the driver kills and retries
with a fix for crash-class signatures (max 2 interventions) and
escalates otherwise. Profile keys the driver reads — `stall_min`,
`writes:`, benign noise — are the Planner's job
(`task-ticket-format.md`). Never an opus- or fable-class Monitor model.

## Human gates & remote control

Gates: plan approval, every replan, every ESCALATE — all event-driven;
the driver blocks on `approvals/<gate>.approved`. A gate that stays
open emits `approval_waiting` every 4 h. When `Evaluation.md` carries a
`CRITERIA CONCERN:` or `OPEN ASSUMPTION:` line the gate also emits
`approval_needs_human` listing them. Under written delegation an
operator may approve a gate that carries no such event, or one that
has waited longer than the shorter of 4 h or 20 % of a rental, and
notes it (`approve --note "<why>"`).

There is no mid-loop `[Halt here]`: preconditions go in `Goal.md`'s
`Preflight`, and the loop stops by event (failed criterion, regression,
budget, escalation, or `pause-after`). Read a sample of the loop's
diffs after every loop; it is the remaining guard against a codebase
you no longer understand.

**Control tower (recommended):** one interactive Claude Code session in
tmux with Remote Control enabled. It reads `events.jsonl` /
`loop-state.json` / `ledger.jsonl` for `status` and writes the approval
flag on your `approve`; it acts only on your instruction.
**Push (optional):** `.claude/driver/notify.sh` (see the `.example`);
allowlist your device, keep secrets out of digests.

## User commands

```bash
python3 .claude/driver/loop.py start                  # or resume
python3 .claude/driver/loop.py status
python3 .claude/driver/loop.py approve [plan|replan] [--note "<why>"]
python3 .claude/driver/loop.py replan "<reason>"      # stop the driver first
python3 .claude/driver/loop.py pause-after "Phase N, Step M"
python3 .claude/driver/loop.py note "<what you changed and why>"
python3 .claude/driver/loop.py close                  # --force if not done
```

- `replan` queues a fresh plan phase (reason + any `Evaluation.md`
  handed to the Planner, re-reviewed, re-gated); counts against
  `max_replans`.
- `pause-after` writes `approvals/pause-after`; the driver reads it at
  the ticket boundary and stops cleanly after the named ticket PASSES
  and its commit lands (`paused`; phase stays `iterate`, `start`
  resumes). It can be issued while the driver is running or waiting.
- `note` records a manual change under a running loop at the moment it
  is made; it shows under the journal's Notable events. When the loop
  is stopped at an escalation, let the audit finish before touching
  anything it reads.
- `close` writes the journal record, prints the criteria, copies
  `ledger.jsonl` + `events.jsonl` to `journal/raw/<record>/`, deletes
  the ephemeral loop files and approval flags, and commits. It refuses
  a template `## Feedback` block until `Rating:` is filled (`--force`
  overrides). It never merges or deletes the branch; it prints those
  commands.

## Housekeeping (driver responsibility, not memory)

The driver writes the loop's `journal/` record on EVERY terminal exit —
done, escalation, crash — and rewrites it on resume, never touching the
`## Feedback` block, whose `Filled by:` line names its author (user, or
operator under delegation). The Outcome block carries the driver's own
counts (review rounds, Monitor tally, GPU-hours, trial wall times).
Tier-2 traces are archived into the PRIMARY tree's `journal/traces/`
even when the session ran in a worktree.

## Machine-readable artifacts

| File | Writer | Reader |
|---|---|---|
| `goal.json` | `[loop]` Ask phase (user-confirmed), then frozen | driver, all agents (read-only) |
| `verdict.json` | Evaluator | driver |
| `ledger.jsonl` | driver only | Planner (REPLAN memory), Retro |
| `loop-state.json` | driver only | driver (crash resume), status |
| `events.jsonl` | driver only | control tower, user |

The trial ledger is the loop's memory: a replanning Planner MUST read
every record and never re-propose a failed hypothesis/config.

## Scope guards

- Batch = sequential queue of goals; one loop at a time.
- Worktree-per-loop for experiment goals; merge conflicts always
  escalate — no auto-resolution.
- No `[monitor]` or `[batch]` commands. A fourth user command must be
  demanded by a retro, not anticipated.
- On each new model generation, `[retro]` stress-tests which loop
  components are still load-bearing.
