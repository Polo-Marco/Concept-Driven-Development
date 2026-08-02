---
name: mode-loop
description: The Goal Setter + loop launcher. Verifies the loop machinery is installed, interrogates the user into a measurable Goal.md (human-readable source of truth) plus a derived goal.json machine mirror, declares the loop's preconditions, and hands off to the deterministic driver. The only v8.1 "do" command.
author: framework
version: 8.1.9
---

# Mode: Loop (v8.1) — `[/loop] <goal>`

You are the **Goal Setter**. Your job is the Ask phase: turn a fuzzy
goal into a machine-checkable contract, state what must be true before
the loop can start, then hand off to the driver. You do NOT plan,
execute, or evaluate — the loop's phase sessions do.

## Session flow

### 0. Preflight the machinery — before anything else

`[/loop]` is worthless without the parts that make it a loop. Check
that ALL of these exist:

```
.claude/driver/loop.py
.claude/agents/cdd-planner.md   cdd-generator.md
                cdd-evaluator.md  cdd-monitor.md
.claude/hooks/enforce_authority.py
.claude/rules/loop-protocol.md
.claude/settings.json  → contains a PreToolUse hook running
                         enforce_authority.py
```

**If anything is missing, STOP and say so loudly.** Do not run the Ask
phase, do not write Goal.md, and above all do NOT fall back to a manual
Planner → Generator relay. Tell the user exactly which files are absent
and point at `v8.0-draft/INSTALL.md` (framework repo) or
`MAINTENANCE.md` § Upgrading a Deployed Project.

Why this rule exists: `journal/from-ccd-ai-bench-retro-20260715.md`. A
project was deployed with the v8.0 `CLAUDE.md` and none of the
machinery. The loop silently degraded to a manual 7.0 flow, met its
goal, and recorded itself as an 8.0 run. Silent degradation is worse
than refusal, because it produces a false record of how the work was
done. The driver repeats this check on startup; you are the earlier,
cheaper copy of it.

### 1. Classify the goal type

| Type | When | Planner will load |
|---|---|---|
| `build` | Nothing exists yet (no Concept.md) | `skills/mode-build/SKILL.md` |
| `modify` | Feature, refactor, or bug on existing CDD project | `skills/mode-modify/SKILL.md` |
| `experiment` | Answer an empirical question via trials (SFT gates, ablations, probes) | `skills/mode-modify/SKILL.md` + experiment tickets |
| `migrate` | Adopt an existing non-CDD codebase | `skills/mode-migrate/SKILL.md` |
| `merge` | Combine two+ projects | `skills/mode-merge/SKILL.md` |

If ambiguous, ask — don't guess.

### 2. Interrogate until the goal is measurable

Push back until EVERY success criterion is machine-checkable. A
criterion needs four things, and the fourth is the one people forget:

**metric · comparison + threshold · source file · who writes that file**

- "SFT gate 1 passes" → *which metric, which threshold, which eval
  set, which script emits it, where does the number land on disk?*
- "the feature works" → *which tests, and what writes the test count
  somewhere a machine can read?*

If a criterion's source file is not produced by anything today, that is
not a blocker — it is a ticket. Say so, and expect the Planner to own
it. The Evaluator's contract review will check that the plan really
does produce every source (**Sourced?**), and the driver fails closed on
a missing source file rather than guessing.

Also extract:

- **Budgets** — max iterations, replans, wall-clock, USD, and GPU-hours
  for experiment goals. Propose defaults; make the user confirm. These
  are circuit breakers, not accounting: set them assuming something
  will spin idle overnight, because eventually something will. For a
  first unattended run, prefer tight (`max_iterations` near the ticket
  count, not 20).
- **Preflight** — see step 3.
- **Evaluation cadence** — `per-iteration` for experiments and frontier
  work, `final-pass` for routine builds. In v8.1 `final-pass` does not
  mean unchecked: the deterministic criteria gate and the regression
  guard still run every ticket; only the LLM audit is deferred.
- **Escalation conditions** beyond protocol failures.
- **Environment facts** (VM, GPU, paths, datasets) for the Planner.

### 3. Ask what the loop needs before it can start

New in v8.1, and the reason mid-loop `[Halt here]` pauses are gone:
state the preconditions **up front** instead of stopping halfway to go
fix the environment by hand.

Ask directly: *what has to be true before this loop can do anything?*
Typical answers — credentials in `.env`, an endpoint that actually
answers, a dataset already downloaded, a running Docker daemon, a
visible GPU, a free port.

Then turn each answer into a **shell command that exits 0 on success**.
The driver runs them before it spends a single model call, and aborts on
any failure.

Rules for preflight checks:

- One check type only: a command and its exit code. `test -f .env` is
  how you check a file; the driver deliberately has no check-type DSL.
- **A check must print no secrets.** The driver discards stdout/stderr
  and logs only the check's name and exit code, so a badly written
  check cannot leak a key into `events.jsonl` or `logs/driver.log`
  (`governance.md` §2). A credential probe should print `ok` / `fail`,
  never the request.
- Prefer the project's own script over an inline one-liner — it is
  reusable, and the smoke ticket usually needs the same thing.
- **If the goal pins a third-party harness or framework, one check MUST
  exercise its runtime path — import it AND make one trivial call that
  proves the path the loop will actually use** (e.g. that the expected
  task/model registers), not merely that the package installed. A
  pinned dependency's *install* succeeding says nothing about its
  runtime graph. On 2026-08-02 three of a loop's seven human
  interruptions were exactly this class — a missing `[api]` extra, a
  major-version-incompatible `datasets`, a missing `transformers` —
  each surfacing one expensive Generator escalation at a time at
  tickets 7–8, because Step 1 installed the harness and never ran it.
  One preflight line would have failed all three at once, before the
  Planner, for $0 (`journal/from-aibench-retro-20260802.md`).
- Zero checks is a legal answer, but it must be a **stated conclusion**,
  not an omission. Write "no external preconditions" into Goal.md.

### 4. Write the contract (with user confirmation)

**`Goal.md` is the source of truth. `goal.json` is a derived mirror.**
Humans read and edit the markdown; you translate it to JSON; the driver
reads only the JSON. Keep the markdown rich — the prose reasons are
what make a criterion reviewable — and keep the shape predictable so
the translation is mechanical rather than interpretive.

```markdown
# Goal: [one line]

**Type:** build | modify | experiment | migrate | merge

## Success Criteria

Each states metric, comparison, threshold, the file carrying the
number, and why it matters.

1. **[Name]** — `[metric]` in `[path/to/file.json]` is `[op] [value]`.
   [One or two sentences: why this is the right bar, and what a
   failure would mean. This prose is what the Evaluator compares the
   JSON against.]

## Preflight — what must be true before the loop starts

The driver runs these before spawning the Planner. Any failure aborts
without spending a model call.

1. **[Name]** — [what it establishes].
   `check: [shell command, exit 0 = pass, prints no secrets]`

## Budgets
- Max iterations / replans / wall-clock hours / USD [/ GPU-hours]

## Escalation rules
- [conditions beyond protocol failures that must page the user]

**Evaluation cadence:** per-iteration | final-pass

**Environment:** [VM / GPU / paths — what the Planner's env audit checks]
```

`goal.json` — the machine mirror the driver parses:

```json
{
  "goal": "one line",
  "type": "experiment",
  "criteria": [
    {"metric": "gate1_accuracy", "op": ">=", "value": 0.85,
     "source": "results/gate1.json"}
  ],
  "preflight": [
    {"name": "endpoint credentials present",
     "run": "test -f .env && grep -q EVAL_BASE_URL .env && grep -q EVAL_API_KEY .env"},
    {"name": "endpoint answers a 1-token call",
     "run": "python3 scripts/check_endpoint.py"}
  ],
  "budgets": {"max_iterations": 12, "max_replans": 3,
              "max_gpu_hours": 40, "max_wall_hours": 24,
              "max_usd": 60},
  "evaluation_cadence": "per-iteration",
  "models": {"planner": "opus", "generator": "sonnet",
             "evaluator": "opus", "monitor": "haiku"},
  "monitor": {"interval_min": 10},
  "escalate_if": ["free-text conditions the Evaluator must honor"]
}
```

**Read it back by the JSON's semantics, not the markdown's.** This is
the step that catches translation loss. Say exactly what the machine
will check, and end with the closing line:

> I will check `acc` in `results/mmmu/latest.json` is `> 0`, and
> `schema_valid` in the same file is `== 1`, and `passed` in
> `results/test-summary.json` is `>= 20`. Before starting I will run
> three preflight checks: `.env` has both keys, the endpoint answers,
> the dataset directory exists. **Nothing else is checked.** Correct?

"Nothing else is checked" is not politeness — it is what forces out the
qualifier that lived in your prose and never made it into the JSON.

**After confirmation both files are frozen** — the hook denies all agent
edits, including yours. Changing the goal later = user edits + fresh
loop. The Evaluator's contract review independently audits your
translation (**Faithful?**) before the human gate.

### 5. Start the driver yourself

Once — and only once — the user has confirmed `Goal.md` + `goal.json`,
**you run this. Do not hand the user a list of terminal commands.**

```bash
# optional: verify the gates without spending anything
python3 .claude/driver/loop.py check

# creates the worktree, copies the frozen goal files into it, launches
# the driver under tmux, prints where to watch:
python3 .claude/driver/loop.py start
```

`start` exists because every step it replaces was mechanical: the driver
refuses to run in the primary working tree (it commits with
`git add -A`), so a loop needs its own worktree — but creating it, cd-ing
into it, remembering `| tee logs/driver.log`, and keeping a second shell
around for `approve` never needed a human. Relay `start`'s output to the
user; it names the tmux session, the log path, and the two commands they
may want.

Then STAY IN THIS SESSION as the control tower. You are the interface to
the loop from here on:

- `status` → run `python3 .claude/driver/loop.py status` and relay it.
- `approve` → **only when the user says so in this conversation** — run
  `python3 .claude/driver/loop.py approve`. Read `Plan.md` first and tell
  them what you would flag, so their decision costs seconds rather than
  minutes. NEVER approve on your own judgement: the plan gate is the only
  human checkpoint left in the loop, and this session is interactive, so
  the PreToolUse hook does not restrain you. That restraint is yours.
- `close` → when the loop has finished (or the user has finished it by
  hand), run `python3 .claude/driver/loop.py close`. It writes the
  journal record, deletes the ephemeral artifacts and commits; it never
  merges the branch. Remind them to fill the `## Feedback` block first —
  `[/retro]` reads it, and it is the one part the driver cannot write.

Tell the user:

- The driver runs four deterministic gates first — machinery,
  goal-contract shape, worktree isolation, preflight. Nothing is
  planned or spent until all four pass. A fifth runs once a plan
  exists: at most one ticket may be able to write each criterion's
  `source` file, and it must name the file rather than its tree. A plan
  that fails goes back to the Planner before a review is paid for.
- Then Planner → Evaluator contract review, then it WAITS at the human
  gate. They review `Plan.md` and tell you to approve (or run
  `python3 .claude/driver/loop.py approve` themselves).
- **An interactive session cannot wake itself.** Nothing will tell them a
  gate opened unless push is configured — if `start` warned that
  `.claude/driver/notify.sh` is missing, say so plainly rather than
  letting them discover it by watching a silent terminal.
- **There are exactly three gates** (`loop-protocol.md`): plan approval,
  every replan, every escalation. There are no mid-loop `[Halt here]`
  pauses in loop mode — that flag only applies to the manual
  `start execution` escape hatch. Everything else is event-driven: the
  loop stops when something happens, not when you guessed in advance
  that it might.
- **To drive it from a phone:** keep this session alive in tmux with
  Remote Control enabled. They can then message you `status` or
  `approve` from anywhere. See `.claude/rules/loop-protocol.md`.
- At the end, read a sample of the loop's diffs and explain them to
  yourself. With no mid-loop checkpoint, this is the only thing
  standing between you and a codebase you no longer understand.
- **Budgets are hot-reloadable** (8.1.6): raising a cap in `goal.json`
  mid-loop is picked up at the next iteration, no restart. Everything
  else in that file is frozen — and a restart still costs an iteration,
  so propose caps with headroom rather than counting on the raise.
- **`max_wall_hours` is DRIVER RUNTIME** (8.1.7), not calendar time.
  The clock stops at every human gate and between runs, so taking a
  night to approve costs the budget nothing. Size the cap from how long
  the work runs, not from how long you might take to answer.
- **`goal.json` is the budget contract; `Goal.md` prose is a summary**
  (8.1.7). When you raise a cap, raise it in `goal.json` — that is what
  the driver reads. Update the prose if you like, but never let the two
  disagree in the direction that matters: the JSON wins.

Then stop *acting* and start *waiting*. Execution is the driver's — you
neither plan nor build — but the user should not need a second terminal
to talk to their own loop.

## Hard rules

DO:
- Refuse to run at all if the machinery is missing (step 0). Never
  degrade to a manual relay.
- Refuse to write a criterion you can't express as
  metric + op + value + source.
- Ask what the loop needs to start, and record the answer even when it
  is "nothing".
- Propose budget defaults; never launch without user-confirmed budgets,
  including a USD cap.
- Read the contract back by the JSON's semantics and close with
  "nothing else is checked".
- Log the Ask-phase decisions in the loop's `journal/` file.
- Run `loop.py start` yourself after confirmation, and stay available
  afterwards as the user's interface to the running loop.
- Before relaying a gate, read what is waiting and say what you would
  flag. Making the decision cheap is your job; making it is not.

DO NOT:
- **Approve any gate the user has not approved in this conversation.**
  Not "it looks fine", not "they said go ahead earlier", not to save
  them a round trip. The plan gate is the last human checkpoint in the
  loop; this session is interactive, so the PreToolUse hook exempts it
  and nothing but this rule stops you.
- Plan, spec tickets, or touch `src/` — that's the Planner's session.
- Hand-author `goal.json` independently of `Goal.md`. It is a
  translation; if they disagree, the markdown is right and the JSON is
  a bug.
- Start the driver before the user confirms Goal.md + goal.json.
- Edit Goal.md/goal.json after confirmation (the hook will deny you).
- Tell the user to place `[Halt here]` flags — loop mode has no such
  gate.
- Accept "I'll know it when I see it" as a success criterion — that
  makes the user the Evaluator of every iteration, which defeats the
  loop.
