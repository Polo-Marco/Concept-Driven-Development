# Loop Protocol (v8.1)

The `[/loop]` pipeline: a deterministic driver orchestrates fresh
Planner / Generator / Evaluator / Monitor sessions until the goal's
success criteria are verifiably met — or the loop escalates to the
user. Full rationale: `docs/loop-orchestration-design.md` (framework
repo) and the tcocrai retro it cites.

## Control principles

1. **The driver is dumb.** `.claude/driver/loop.py` — a deterministic
   state machine. It spawns sessions, parses JSON artifacts, branches
   on verdicts, enforces budgets, owns long-running processes, and is
   the ONLY thing that commits during a loop. The Planner calls nobody.
2. **Sessions are fresh and short.** Each phase runs headless
   (`claude -p`) with selective context and a role-specific agent
   definition (`.claude/agents/cdd-*.md`). Process boundary = session
   boundary.
3. **Authority is enforced.** The PreToolUse hook
   (`.claude/hooks/enforce_authority.py`) denies git writes, boundary
   breaches, and protected-file edits per role (`CDD_ROLE` /
   `CDD_BOUNDARY` env). An agent that hits a denial STOPS and reports;
   working around it is a protocol violation. Verified 2026-07-30:
   `--dangerously-skip-permissions` skips permission *prompts*, not
   hooks, so the driver's enforcement layer is intact.

   The hook decides `Write`/`Edit` exactly (they carry a `file_path`) and
   scans `Bash` for the write targets a model reaches for by accident —
   redirects, `tee`, `sed -i`, `mv`/`cp`, `rm`, `dd` — applying the same
   role decision to each (v8.1; before this, core files and Boundaries
   were unguarded on the shell path). `logs/` stays writable for the
   roles that execute a Run Command, and the Monitor writes nothing at
   all. Interpreter escapes (`python3 -c`, heredocs, expansion) are
   **knowingly out of scope**: a shell is Turing-complete, a pattern
   matcher is not. Adversarial containment is the VM plus the worktree —
   if a role needs real confinement, confine the process, do not grow
   the hook into a shell parser.

   **A denial is visible, and over-denial is not free** (v8.1.9). The
   hook appends one line per denial to `logs/denials.log` and the driver
   turns the count into a `hook_denials` event, because a denial used to
   exist only on the agent's stderr — so a hook FALSE POSITIVE cost a
   transcript dig to diagnose. It costs more than that to have: on
   2026-08-02 the shell net matched the `>` of `2>&1` as a write to
   `goal.json` and killed a read-only Evaluator audit mid-loop, which
   the loop then paid to re-run. The net tests per shell segment now and
   leaves redirects to the precise target scan, which decides them
   exactly. Denying a command that merely NAMES a protected file is a
   defect, not caution.

   **Decide on the resolved target, never on the token** (v8.1.11). The
   same class recurred eight times across the aibench deployment's first
   eight loops — 42% of every reason a loop stopped — because the net
   kept judging syntax it had mistaken for a path: a bare `>`, a `>=`
   comparison, a `>` inside a quoted `--format` string, a heredoc body,
   a `git log` and a later bare `add` on another line of the same batch,
   the listing forms of `tag`/`stash`/`worktree`, a redirect handed to
   `cp`'s trailing-argument rule. Two rules follow from it: git is
   decided by SUBCOMMAND, not by verb; and a redirect's own syntax is
   never a target. Both directions matter — the same `cp` bug that
   denied a read-only copy also LEAKED a write to `Architecture.md`,
   because the trailing argument it decided was `/dev/null`.

   **`/tmp` is scratch, and scratch is outside the matrix.** Every role
   may write there through `Write` and through the shell alike; the
   Evaluator's contract requires it, since reconstructing a prior state
   is how a claim gets checked independently. Scratch is a TWO-sided
   test on the resolved path: outside the repo AND under `/tmp`. A
   symlink from `/tmp` back into the tree is decided as the file it
   points at, and a project that itself lives under `/tmp` is not one
   big carve-out.
4. **Goal immutability.** `Goal.md` + `goal.json` are user-owned. No
   agent session may edit them — a loop that can move its own
   goalposts optimizes the wrong thing. Change of goal = user edits +
   fresh loop.
5. **Trial provenance.** A launched trial's config is immutable.
   Crash-recovery with an identical config may reuse the trial ID; ANY
   parameter change = new trial ID via REPLAN, recorded in the ledger.
6. **Anything rule-bound is decided by code, not by a model.** (v8.1)
   The driver owns five deterministic gates and runs them before it
   spends anything: `machinery()` (the loop's own parts are installed
   and the hook is wired), `validate_goal()` (the contract is
   well-formed and has at least one machine-checkable criterion),
   `require_isolation()` (not the primary working tree), `preflight()`
   (the environment preconditions declared in `Goal.md`), and
   `evidence_gate()` (nothing already exists at a path a criterion
   reads its number from — v8.1.12). Once a plan exists,
   `plan_problems()` checks that at most one ticket can write each
   criterion's `source` file and that it names the file rather than its
   tree (v8.1.6) — a plan that fails goes back to the Planner before a
   contract review is paid for. `check_criteria()` then reads every
   criterion straight off disk. All fail CLOSED — a
   missing source file, an unparseable artifact or an absent metric is a
   failure, never a pass. Rationale: the Ask phase already forces every
   criterion into metric + op + value + source, so handing the
   comparison to a probabilistic model adds cost and removes certainty.
7. **Deterministic is necessary, not sufficient.** `check_criteria()`
   proves a number met its threshold; it cannot prove the number was
   earned. Provenance stays with the Evaluator, which must EXECUTE
   rather than read. Keep both checks — the cheap one being free is not
   a reason to delete the expensive one.

   **A criterion recorded green by `check_criteria()` alone has met a
   threshold, not earned one** (v8.1.6), and the regression guard
   inherits that uncertainty: it will defend an unearned green as
   readily as a real one, so deleting forged evidence reads to it as a
   regression. This is why the iteration where a criterion FIRST reads
   green always buys an Evaluator audit, even under `final-pass`
   cadence — provenance is worth paying for at the moment the colour
   changes, not five committed tickets later.

   **A criterion is identified by `metric@source`, and is evidence only
   once its owner has run** (v8.1.12). Two rules, one failure class:

   - The green set was keyed on the bare metric name, so two criteria
     measuring the same quantity in different files were one entry —
     six criteria under four names in one loop, thirteen under nine in
     another. A regression in one of a colliding pair was invisible
     while the other stayed green, and `first_green` fired once for the
     pair, so the second criterion's first green bought no audit.
   - `criteria_due()` defers a criterion whose `source` a LATER ticket
     owns. Until that ticket runs, the file at that path is not this
     loop's result; it is whatever was there before. Such a criterion
     is neither green NOR red — out of the green set and out of the
     regression comparison — so clearing stale evidence costs nothing.
     Everything is due by the final gate, which still requires all of
     it green.

   Prefer to make the class impossible rather than detected: give each
   criterion a `source` path only THIS loop can write. A stable pointer
   (`results/<bench>/latest.json`) is the shape that fails — it is what
   made one loop start with four criteria already green off the
   previous loop's records, carrying the very harness pin that loop
   existed to replace. `evidence_gate()` refuses such a start.

## The loop

```
goal.json → [gates: machinery, contract shape, isolation, preflight, evidence]
          → Planner → Evaluator contract review (OK|REVISE, ≤2 rounds
                      AND ≤ half of max_usd)
          → HUMAN GATE (approve once; also after each REPLAN)
          → `plan(loop):` commit of everything the plan phase produced
          → per ticket: Generator (bearings + smoke test → TDD/impl)
                        → driver launches Trial, Monitor polls
                        → check_criteria() + regression guard (free)
                        → Evaluator → verdict.json  (cadence-dependent)
          → final: check_criteria() hard gate, THEN Evaluator provenance
          → PASS: driver marks [x], commits, next ticket
            RETRY: same ticket, ≤3 attempts, each carrying the verdict
                   that rejected the last one
            REPLAN: fresh Planner + ledger + Evaluation.md, ≤ budget
            ESCALATE: stop, notify user
          → final evaluation of ALL Goal.md criteria → done
          → loop.py close: journal record, housekeeping
```

**A retry carries WHY** (v8.1.6). The Generator dispatch on attempt 2+
includes the previous verdict's `reason` and `evidence`; retrying a
ticket verbatim can only help a nondeterministic fault. And a Generator
session that changed **nothing** twice is a protocol failure, not a
retryable one — the driver fingerprints the tree around each dispatch
and escalates rather than buying a third identical session. The
exception is a RETRY caused by a trial that did not complete:
relaunching an unchanged config is exactly what that retry is for
(Protocol #5).

**Contract review is bounded by money, not only by rounds** (v8.1.7).
`MAX_REVISIONS` was the sole bound and no budget was consulted between
rounds, so a review could eat an arbitrary share of `max_usd` before
the one gate where the user can still intervene cheaply — two
consecutive `build` loops spent their pre-gate budget this way
(2026-07-31: $5.48, 59% of the run, six sessions, zero tickets). Once
the pre-gate phases have spent half of `max_usd` the driver stops
buying rounds and hands the plan to the human gate, which is free. The
FIRST review is always bought: skipping it would not bound a cost, it
would delete the safety gate. The gate banner then states what it is
handing you — reviewed OK, or review cut short — because a gate that
misreports itself is worse than no gate.

**The plan phase commits at its gate** (v8.1.7). The driver commits
`git add -A`, so with nothing flushed between the Planner and ticket 1,
the first `feat(loop):` commit carried Plan.md, Evaluation.md,
verdict.json, Architecture.md, a user budget edit and the journal
record under one ticket's title — three authors in one commit, and a
per-ticket Boundary audit read off `git log` cannot work that way. A
`plan(loop):` commit now lands the moment the gate clears (and after
each replan gate), so `feat(loop):` carries exactly one ticket
(governance.md §1).

**Verdict routing:** metric-based failures → RETRY/REPLAN. Protocol
failures (boundary breach, worker stop/death, unsatisfiable spec,
missing artifact, doc contradiction) → ESCALATE immediately. Never
burn trial budget on a defect no trial can fix.

## Machine-readable artifacts (JSON — agents corrupt JSON less than MD)

| File | Writer | Reader |
|---|---|---|
| `goal.json` | `[/loop]` Ask phase (user-confirmed), then frozen | driver, all agents (read-only) |
| `verdict.json` | Evaluator | driver |
| `ledger.jsonl` | driver only | Planner (REPLAN memory), Retro |
| `loop-state.json` | driver only | driver (crash resume), status |
| `events.jsonl` | driver only | control tower, user |

The trial ledger is the loop's memory: a replanning Planner MUST read
every record and never re-propose a failed hypothesis/config.

## Monitor

While a trial runs, the driver spawns `cdd-monitor` (cheap model)
every N minutes with the log tail + Monitor Profile. It classifies —
`HEALTHY | INTERVENE | KILL_ESCALATE` — and the DRIVER acts: kill +
RETRY-with-fix for crash-class signatures (max 2 interventions),
escalate otherwise. The Monitor never edits, never kills, never
retunes parameters.

## Human gates & remote control

Gates: plan approval (once), every replan, and every ESCALATE — three,
all event-driven. The driver blocks on `approvals/<gate>.approved` flag
files.

**No mid-loop `[Halt here]`** (v8.1). The driver never implemented it,
and asking for it required guessing which ticket would need inspection
before any output existed. What replaces it: environment preconditions
are declared up front in `Goal.md`'s `Preflight` section and verified
deterministically, and the loop stops by event — failed criterion,
regression, exhausted budget, escalation. Because there is no scheduled
human checkpoint left, the budget caps and the criteria gate are
load-bearing, not advisory. Read a sample of the loop's diffs after
every loop; it is the only remaining guard against a codebase you no
longer understand.

**Control tower (recommended):** one interactive Claude Code session
in tmux on the VM with Remote Control enabled. From the phone, message
it: it reads `events.jsonl` / `loop-state.json` / `ledger.jsonl` to
answer `status`, and writes the approval flag on your `approve`. When
it surfaces a decision to you, Remote Control pushes to your phone.
The tower session is interactive (no `CDD_ROLE`), so the hook does not
restrict it — it acts only on your instruction.

**Push (optional):** `.claude/driver/notify.sh` — see
`notify.sh.example` (ntfy/Telegram). Allowlist your device on any
command topic; keep secrets out of digests (governance.md §2).

## Housekeeping (driver responsibility, not memory)

**The driver writes the loop's `journal/` record** (v8.1.6) — goal,
outcome, tickets, criteria, every ledger row and the notable events —
on EVERY terminal exit, including an escalation and a crash, not only
on `done`. It never overwrites the `## Feedback` block, which is yours.

**Closing is a command, not a memory exercise:**

```bash
python3 .claude/driver/loop.py close      # add --force if not `done`
```

It writes the record, prints the criteria one last time, deletes
`Plan.md`, `Evaluation.md`, `verdict.json`, `goal.json`, `Goal.md`,
`ledger.jsonl`, `loop-state.json`, `events.jsonl` and the approval
flags, and commits. It deliberately does NOT merge or delete the
branch, and does not touch the tree you started from — those are
irreversible and yours; it prints the commands. Four retros in a row
flagged unclosed loops while the reminder was already in place, so the
missing part was never the reminder.

**Budgets are hot-reloadable** (v8.1.6): the driver re-reads the
`budgets` block of `goal.json` at every iteration, so raising a cap
mid-loop no longer needs a restart. Criteria stay frozen (Protocol #4).

**Edit the WORKTREE's `goal.json`** — that is the copy the running
driver reads, and editing it needs no restart, so it costs no
iteration. `start` seeds `Goal.md`/`goal.json` into a fresh worktree
ONCE and never overwrites them again (v8.1.9); it used to re-copy the
primary tree's version on every resume, which reverted an approved
budget raise twice in one loop and — since a restart itself consumes an
iteration — made each repair round pay for the failure it was
repairing: three `budget exhausted: max_iterations` escalations for a
loop that had finished its work. If the two copies differ, `start`
prints which one wins.

**`max_wall_hours` meters DRIVER RUNTIME, not the calendar** (v8.1.7).
The clock runs only while the driver process is working: it stops at
every human gate and does not run between runs. It used to be
`now - started_epoch`, which billed the loop for time it was not alive
— a loop that sat 3.6h at the plan gate escalated `budget exhausted:
max_wall_hours` the instant the approval landed, before one ticket ran,
with $0 spent since resume. That contradicted this file's own pitch of
approving from your phone, i.e. with no SLA. A run that crashed is
credited only up to its last recorded event, which is the last moment
the driver can be proven alive. `status` shows both clocks: calendar
age next to the start time, metered runtime under `budgets`.

**Every driver restart consumes an iteration** — `iteration` counts
dispatches, and a resume re-dispatches the ticket it was on. Size
`max_iterations` with headroom for interruptions; do not expect the
counter to forgive them, because a cap a restart can reset is a cap a
crash loop can defeat.

## Scope guards

- Batch = sequential queue of goals; one loop at a time in v8.0.
- Worktree-per-loop is recommended for experiment goals (runaway
  containment); merge conflicts always escalate — no auto-resolution.
- No `[/monitor]` or `[/batch]` commands. A fourth user command must
  be demanded by a retro, not anticipated.
- On each new model generation, `[/retro]` stress-tests which loop
  components are still load-bearing (every component encodes an
  assumption about what the model can't do; assumptions go stale).
