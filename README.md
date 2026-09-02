# Concept-Driven Development (CDD) 8.1.16

A structured AI development framework built on a session-based pipeline.
You align. The Planner designs. The Generator builds. The Evaluator
audits. You sign off. The Coach helps you improve. Git is the checkpoint
system **and the changelog**.

Since 8.0 the pipeline runs itself. You state a goal whose success
criteria a machine can check, approve one plan, and a deterministic
driver orchestrates the sessions until those criteria are met — or it
escalates to you. You move from *in* the loop to *on* it.

The name says the method: every line of code traces back to an explicit
**Concept** and **Architecture** agreed *before* building — not invented
mid-stream by the agent.

**Works with Claude Code and Cursor.** *(Formerly "Vibe Coding Framework.")*

## The Problem

AI coding agents fail in predictable ways:

1. **Context collapse.** The agent forgets its own decisions mid-session.
2. **Architectural hallucination.** Without planning, the agent invents your architecture.
3. **Poor self-evaluation.** Agents approve their own mediocre work.
4. **Context bloat.** Reading every file every turn burns tokens on
   irrelevant material.
5. **Environment surprises.** The Generator wastes retries on missing
   tools, missing `.env`, missing package managers.
6. **Spec drift.** Implementations slowly diverge from external
   contracts (API specs, design systems) without anyone noticing.
7. **Over-engineering.** The agent adds speculative features,
   abstractions, and config nobody asked for.
8. **Blind merges.** Asked to combine two codebases, the agent plans
   before it understands either version — and produces a mess.
9. **Expensive debugging.** When a slow pipeline (OCR, long agentic
   chains) fails, reproducing the failure to debug it is costly.
10. **Copy-paste debugging.** You paste terminal walls of text into the
    agent just to give it the error it should be able to read itself.
11. **No room to think.** There's no phase to *stop and discuss*
    direction against the docs before committing to a build.
12. **Stale usage docs.** No one maintains a README, so testing and
    using the project correctly is guesswork.
13. **No process memory.** You can't tell whether your development
    process is improving except by feel.
14. **Slow sequential builds.** Independent tickets are generated one at
    a time even when they could be built concurrently.
15. **You are in the loop of every ticket.** Each phase hands back to you
    to type the next command, so progress stops whenever you do.
16. **"Done" is a feeling.** With no machine-checkable success criterion,
    the agent grades its own homework and you audit prose.
17. **Goalpost drift.** An agent that can edit the goal will eventually
    optimize the goal instead of meeting it.

CDD answers 1–14 with a strict pipeline, structured files as external
memory, layered Architecture and nested `CLAUDE.md`, always-on
engineering **principles**, an environment audit, `docs/` +
`DEVIATIONS.md` for tracked drift, **run-log capture**, a **discuss
mode** for direction, **Planner-maintained README**, and a **session
journal + retro** for improving how you build.

It answers 15–17 with the 8.0 loop: a deterministic driver in place of
your keyboard, success criteria read off disk by code rather than judged
by a model, and a goal contract every agent session is mechanically
forbidden to edit.

## How It Works

### The Loop (the default path since 8.0)

`[/loop]` turns a goal into a contract, then hands it to
`.claude/driver/loop.py` — a state machine, not a model — which spawns a
fresh, short, headless session per phase:

```
[/loop] <goal>
  │
  ├─ Ask phase (interactive): interrogate until every success criterion
  │  is metric + comparison + threshold + the file carrying the number
  │  → Goal.md + goal.json, frozen the moment you confirm them
  │
  └─ driver (deterministic; one fresh session per phase)
       gates: machinery · contract shape · worktree isolation · preflight · evidence
         ↓       nothing is planned and nothing is spent until all pass
       Planner ──→ Evaluator contract review (≤2 rounds, ≤½ of max_usd)
         ↓
       ══ HUMAN GATE ══  approve once — from the terminal or your phone
         ↓                              then: plan(loop): commit
       per ticket:  Generator → driver launches the trial ← Monitor polls
                      → criteria gate (code, fail-closed) + regression
                      → Evaluator → verdict.json
                    PASS → commit · RETRY ≤3 · REPLAN → back to the gate
                                              · ESCALATE → you
         ↓
       final: every goal.json criterion re-checked, then a provenance
              audit — a number that met a threshold is not yet a number
              that earned one
         ↓
       loop.py close: journal record, housekeeping, one commit
```

**Three human contact points, all event-driven:** approve the plan,
answer an escalation, sign off. There is nothing to schedule in advance
— the loop stops when something actually happens (a failed criterion, a
regression, an exhausted budget), not where you guessed it might.

What that buys you, concretely: the goal files are hook-protected, so no
session can move its own goalposts; criteria are compared by
`check_criteria()` reading the source file off disk, so "done" is not a
model's opinion; and budgets (iterations, replans, USD, GPU-hours,
driver runtime) are circuit breakers that bite without you watching.

### The Sessions Inside It

Inside a loop the driver issues these transitions itself; `[/discuss]`
and `[/retro]` stay yours to call. Typed by hand — the 7.0 escape hatch,
still fully supported — the same pipeline looks like this:

```
Discuss (opt)      Planner            Generator          Evaluator (opt)    Retro (opt)
──────────────     ───────────        ─────────────      ───────────────    ──────────
[/discuss]         [/build]/[/modify] start execution    [/evaluate]        [/retro]
                   [/migrate]/[/merge]

Align on docs      Ask: interrogate   Read Overview      Independently       Read journal/
Edit Concept/docs  Env audit          Load ticket        audit: run code,    Find patterns
(with your OK)     Spec: core files   sections only      check docs,         Recommend
No plan, no code   + README, skills   TDD loop/ticket    simplicity, README  framework fixes
                   Plan/Triage        Runs → logs/       Write Evaluation    Write retro
                   Commit + journal   Commit + journal    + journal          summary
STOP               STOP               STOP               STOP (no commit)    (no code)

  ↓                    ↓                   ↓                  ↓                  ↓
Docs aligned      Review plan        Run tests          Act on verdict     Improve the
                  Place [Halt here]  Run [/evaluate]    Fill journal         framework
                                                        feedback
```

**Discuss Session (optional)** is a thinking partner. It reads the
docs, debates direction with you, and — only with your confirmation —
edits `Concept.md` and `docs/`. It writes no plan and no code.

**Planner Session** has full authority over core files. It designs,
plans, audits the environment, writes/updates the **README**, and
produces everything the Generator needs.

**Generator Session** has zero authority over core files. It executes
task tickets literally, strictly inside each ticket's **Boundary**, and
captures each run to `logs/latest.log`. When the Planner has marked
independent tickets with a **Parallel Group**, the Generator builds them
concurrently (fan-out/fan-in) instead of one at a time. It commits per
ticket in manual mode; inside a loop it never commits at all — the
driver is the only committer.

**Evaluator Session** is independent and skeptical (optional in manual
mode, built into the loop). It has two duties: *contract review* before
execution — does `Plan.md` actually produce the evidence every criterion
is read from? — and *evaluation* after, where it **executes** the code
rather than reading it, checks that results were earned rather than
merely present, cross-checks Concept/Architecture/docs/**README**/code
for redundancy and missing context, and writes `Evaluation.md` (plus
`verdict.json` in a loop).

**Monitor Session** (loop only) watches a long-running trial from
outside. Every N minutes it reads the log tail against the ticket's
Monitor Profile and returns one word — `HEALTHY`, `INTERVENE`, or
`KILL_ESCALATE`. It writes nothing and kills nothing; the driver acts on
the classification.

**You are the final Evaluator.** You sign off, and you fill the
**Feedback** block in the session journal.

**Retro Session (optional)** is your coach. It reads `journal/` across
loops, finds patterns in what worked and what didn't, and recommends
concrete framework/skill/habit changes.

### Git Is the Changelog

There is **no `CHANGELOG.md`**. Git history *is* the changelog — every
session can read it, and commit messages carry the weight, so they must
be detailed:

```
git log --oneline                 # progress trail
git log -p <file>                 # how a file evolved
git diff <planner-commit>..HEAD   # what a cycle produced
```

### Recovery via Git

Git commits at each ticket give you clean recovery points:

- **Generator fails?** `git reset` to the Planner commit, switch model,
  `start execution` again.
- **Plan was wrong?** `git reset` to the Planner commit, start a new
  Planner session, refine.
- **Partial success?** Keep what worked, plan the rest anew.

In loop mode the driver does the first two for you — a failing ticket is
RETRIED up to three times (each retry carrying the verdict that rejected
the last attempt), a plan that cannot work is REPLANNED and re-gated —
and the whole loop runs in its own git worktree, so the tree you started
from is never at risk. The `plan(loop):` commit at the human gate is
your reset point; each `feat(loop):` commit after it carries exactly one
ticket.

### The Three Commands

| Command | Persona | Purpose |
|---|---|---|
| `[/discuss]` | The Thinking Partner | Think. Align direction; edit docs/Concept. No code. |
| `[/loop]` | The Goal Setter | Do. Measurable goal in → driver-orchestrated Plan/Generate/Monitor/Evaluate → answer out. |
| `[/retro]` | The Coach | Improve. Review journals; tune framework + habits. |

Everything else is internal machinery. Build/modify/migrate/merge are
**goal types** inside `[/loop]`; `[/evaluate]` is the loop's Evaluator
agent; `start execution` is issued by the driver. The 7.0 mode skills
remain in `skills/` and stay directly invocable as an escape hatch —
the driver calls the same files you would, under the same authority
rules.

### Which goal type? (decision guide)

The Ask phase classifies your goal; the Planner then loads the matching
mode skill.

```
Nothing exists yet (no Concept.md)? ................... build
Existing non-CDD code to adopt? ....................... migrate
Combining two+ existing projects? ..................... merge
Adding a feature, refactoring, or fixing a bug? ....... modify
Answering an empirical question with trials
  (SFT gates, ablations, probes)? ..................... experiment
```

And the two commands that are not `[/loop]`:

```
Want to think / redirect before changing anything? ... [/discuss]
Want to improve how you build, from logged facts? .... [/retro]
```

**Your typical life:** one `[/loop]` with a `build` goal to go 0→1, then
repeated `modify` loops as you add features and fix bugs on top. Reach
for `[/discuss]` when a new paper or idea makes you want to redirect,
and `[/retro]` every few loops to tune the process.

### Always-On Principles

Three engineering principles apply in every session
(`.claude/rules/principles.md`):

- **Simplicity First** — minimum code that satisfies the ticket.
- **Surgical Changes** — touch only what the ticket requires.
- **Think Before Coding** — state assumptions and trade-offs first.

### Phase-Based Authority

Authority binds to the session type, not the model:

| File | Planner | Generator | Evaluator | Monitor |
|---|---|---|---|---|
| Concept.md | Read / Write | Read only | Read only | — |
| Architecture.md | Read / Write | Read only (selective) | Read only | — |
| README.md | Read / Write | Read only | Read only | — |
| Plan.md / Triage.md | Read / Write | Read only (mark `[x]`) | Read only | — |
| skills/ | Read / Write / Create | Read only | Read only | — |
| `**/CLAUDE.md` (nested) | Read / Write / Create | Read only | Read only | — |
| docs/*.md | Read only | Read only | Read only | — |
| docs/DEVIATIONS.md | Read / Append | Read only | Read only | — |
| Goal.md, goal.json | **Read only — every session** (yours) | | | |
| Evaluation.md, verdict.json | — | — | Read / Write | — |
| journal/*.md | Append | Append | Append | — |
| src/, tests/ | — | Read / Write (within Boundary) | Read only (may run) | Read only |
| git write commands | loop: driver only | never | never | never |

**Discuss** may edit `Concept.md` + `docs/` (with your confirmation),
nothing else. **Retro** may write only `journal/`. Full matrix in
`.claude/rules/phase-authority.md`.

**In loop mode this is mechanically enforced**, not merely documented. A
`PreToolUse` hook (`.claude/hooks/enforce_authority.py`) reads the
session's role and Boundary from the environment and denies the call —
`Write`/`Edit` by exact path, and `Bash` by scanning each shell segment
for redirects, `tee`, `sed -i`, `mv`/`cp`/`rm`. A denied agent must stop
and report; working around a denial is itself a protocol violation.
Every denial is appended to `logs/denials.log` and counted into the
loop's event feed, because a hook false positive costs real money and
needs to be visible — across one deployment's first eight loops that
class was 42% of every reason a loop stopped. The hook decides the
*resolved target*, never the token it was handed: git by subcommand
rather than verb, redirect syntax never a target, and `/tmp` scratch
writable by every role (outside the repo and under `/tmp` — both, on
the resolved path) because independent reconstruction is how an
Evaluator checks a claim. Interpreter escapes (`python3 -c`) are knowingly
out of scope — the containment boundary for anything adversarial is the
worktree and the VM, not a pattern matcher.

## Core Files

| File | Lifecycle | Purpose |
|---|---|---|
| `Concept.md` | Persistent | Vision — why it exists, scope, principles |
| `Architecture.md` | Persistent (layered) | System design source of truth |
| `README.md` | Persistent | User-facing: install, run, test, use |
| `Plan.md` | **Ephemeral** | Task tickets — deleted after the loop |
| `Triage.md` | **Ephemeral** | Bug hypotheses — deleted after the loop |
| `Architecture-<source>.md` / `Merge-Analysis.md` | **Ephemeral** | `[/merge]` per-source models + conflict map |
| `Evaluation.md` | **Ephemeral** | Evaluator verdict — deleted after sign-off |
| `journal/*.md` | Persistent | Per-loop session records + your feedback (Tier 1) |
| `journal/traces/*.jsonl` | Persistent, gitignored | Full raw transcripts (Tier 2, Claude Code hook) |
| `skills/` | Persistent | Execution patterns, rules, conventions |
| `**/CLAUDE.md` (nested) | Persistent | Module-specific conventions (Planner-maintained) |
| `docs/*.md` | User-maintained | External reference docs (immutable to agents) |
| `docs/inbox.md` | Discuss-appendable | Raw idea capture, promoted via `[/discuss]` |
| `docs/DEVIATIONS.md` | Planner-appendable | Tracked departures from reference docs |
| `logs/latest.log` | Ephemeral, gitignored | Most recent run's stdout/stderr |

The loop adds its own contract and state files, all **ephemeral**, all
deleted by `loop.py close`:

| File | Written by | Purpose |
|---|---|---|
| `Goal.md` | you (via the Ask phase) | The goal contract, in prose — the source of truth |
| `goal.json` | the Ask phase, then frozen | Its machine mirror: criteria, preflight, budgets, models |
| `verdict.json` | Evaluator | The machine verdict the driver branches on |
| `ledger.jsonl` | driver | Trial memory — what was tried, what it cost, why it failed |
| `loop-state.json` | driver | Phase, iteration, spend, clocks (crash resume). Gitignored |
| `events.jsonl` | driver | Event feed the control tower and `status` read. Gitignored |
| `logs/denials.log` | the authority hook | Every denied write, with role and reason. Gitignored |
| `approvals/*.approved` | you | Gate flag files. Gitignored |

Git history replaces `CHANGELOG.md`.

## What's New in 8.0

### 1. `[/loop]` — the pipeline runs itself
A deterministic driver (`.claude/driver/loop.py`) spawns a fresh headless
session per phase, parses the JSON each returns, branches on it, enforces
budgets, owns long-running processes, and is the only thing that commits.
It is deliberately dumb: every rule-bound decision belongs to code, and
all model intelligence lives *inside* the phase sessions. The user
surface collapses from eight commands to three.

### 2. A goal contract a machine can check
The Ask phase refuses to accept a success criterion it cannot express as
**metric + comparison + threshold + the file carrying the number**, and
names who writes that file. `Goal.md` holds the prose (why each bar is
the right bar); `goal.json` is its mechanical mirror. Both freeze the
moment you confirm them — the hook denies every agent edit, including
the session that wrote them. A loop that can move its own goalposts
optimizes the wrong thing.

### 3. Deterministic gates, all failing closed
Before a single model call: the machinery is installed and wired, the
contract is well-formed and has at least one checkable criterion, the
loop is in its own worktree, and the environment preconditions declared
in `Goal.md` all exit 0. Once a plan exists, one more: at most one
ticket may be able to write each criterion's evidence file, and it must
name the file rather than its directory — a plan that fails comes back
before a review is paid for. Then `check_criteria()` reads each
criterion straight off disk after every ticket. A missing file, an
unparseable artifact, or an absent metric is a failure, never a pass.

But deterministic is necessary, not sufficient: a number that met a
threshold is not yet a number that *earned* one. The Evaluator still
audits provenance by executing the code, and the iteration where a
criterion first turns green always buys that audit.

### 4. Authority enforced, not merely documented
The phase-authority matrix became a `PreToolUse` hook that denies the
call. See **Phase-Based Authority** above for how it decides and what it
knowingly does not cover.

### 5. Trials, the Monitor, and the ledger
An `experiment` goal replaces the Test Contract with a **Hypothesis**, a
**Trial** command, a **Metrics Contract**, a **Success Threshold**, and a
**Monitor Profile**. The driver — not the Generator — launches the trial
and polls a cheap Monitor session against the log tail. Every trial is
appended to `ledger.jsonl`, which a replanning Planner must read: it is
the loop's memory of what has already failed, and its config is
immutable (any parameter change is a new trial, not an edited one).

### 6. Budgets as circuit breakers
Iterations, replans, USD, GPU-hours and wall-clock are caps that stop the
loop, sized on the assumption that something will eventually spin idle
overnight. Two refinements you feel immediately: `max_wall_hours` meters
**driver runtime**, so the clock stops while a gate waits for you and
taking a night to approve costs nothing; and caps are re-read every
iteration, so raising one mid-loop needs no restart (criteria stay
frozen).

### 7. Drive it from your phone
Keep one interactive session in tmux with Remote Control on as a control
tower: it reads the event feed to answer `status`, and writes the
approval flag when you say `approve`. Optional push
(`.claude/driver/notify.sh`) tells you a gate opened.

## Carried Over from 7.0

### 1. Run-log capture ("check the latest run log")
Every Run Command tees to `logs/latest.log` via
`<cmd> 2>&1 | tee logs/latest.log`. When something breaks, say
**"check the latest run log and fix it"** — the agent reads the log,
finds the error, and routes the fix through `[/modify]`. No more pasting
terminal walls of text. See `.claude/rules/run-logging.md`.

### 2. `[/discuss]` mode — a phase to think
A thinking-partner session that reads `Concept.md`/`Architecture.md`/
`docs/`, debates direction, and (with your confirmation) edits
`Concept.md` and `docs/`. It's the only agent session allowed to edit
`docs/`, and it promotes raw notes from `docs/inbox.md` into durable
docs. Writes no plan, no code.

### 3. Debug folded into Modify
`[/debug]` is removed. `[/modify]` now handles features, refactors, and
bug fixes. When the request is "X is broken," Modify runs a
bug-investigation sub-flow (Triage, 1–3 hypotheses, Tier-1 permanent
tests vs Tier-2 throwaway sandboxes) — debug's machinery, one fewer
mode to reason about.

### 4. Planner-maintained README
`README.md` is now a first-class core file. Build/migrate/merge write
it; modify keeps it accurate when a change affects install/run/test/use;
the Evaluator's context audit checks it. So you can always test and use
the project correctly.

### 5. Session Journal + `[/retro]` coach (two tiers)
Each pipeline loop writes a **Tier-1 curated summary** to `journal/`
(what was planned, built, evaluated) and you fill a **Feedback** block
(rating + what went well + any instruction not followed). `[/retro]`
reads these across loops and recommends concrete improvements — to the
framework and to your own habits — grounded in logged facts.

Optionally, a **Tier-2 full raw trace** (every tool call and decision)
is archived to `journal/traces/*.jsonl` by a Claude Code `SessionEnd`
hook (`.claude/settings.json`). The curated summary is what `[/retro]`
reasons over; the raw trace is the forensic drill-down for loops you
flag "bad". Tier 2 is Claude-Code-only (Cursor has no transcript path);
Tier 1 works in both tools. Traces are gitignored (large + sensitive);
summaries stay in git.

### 6. Git history is the changelog
`CHANGELOG.md` is gone. Git history is the changelog; every session
knows to read it, and commit messages are required to be detailed.

### 7. Parallel Generator (fan-out / fan-in)
Sequential generation is slow when a plan has several independent
tickets. The **Planner decides** what can run in parallel — at plan-time,
not the Generator at runtime — because judging cross-ticket dependencies
is an architectural call. It declares this with two ticket fields:

- **`Depends On:`** — which tickets must finish first.
- **`Parallel Group:`** — a label; tickets sharing it run concurrently.

A group is only valid when its members have **pairwise-disjoint
Boundaries** (no shared files → no write races) and **no member depends
on another**. The Generator then runs **fan-out / fan-in**: it dispatches
one worker per ticket (Claude Code subagent / Cursor parallel agent) to
implement + test in parallel, then on the main thread runs the full
regression suite once and commits each ticket sequentially. Workers
never commit (no git races); regression always runs at the join.

It's **opt-in**: plans with no `Parallel Group:` labels run fully
sequentially, exactly as before. See
`.claude/rules/parallel-execution.md`.

### Older, still load-bearing (6.x)
- Layered `Architecture.md` with selective loading.
- Environment audit baked into the Planner.
- Reference docs in `docs/` with `DEVIATIONS.md` for tracked drift.
- Nested `CLAUDE.md`, always-on principles, `[/merge]` architecture-first,
  the independent Auditor, opt-in process logging for expensive pipelines.

## Layered Architecture.md (selective loading)

`Architecture.md` is a layered document. The Generator always reads
`## Overview` (a self-contained 20–30-line snapshot) and only the
sections each ticket lists in its `**Architecture:**` field:

```markdown
# Architecture
## Overview            <!-- always read -->
## Environment         <!-- audit results -->
## API Surface
## Data Models
## Frontend Components
## Infrastructure
```

Tickets declare what they need: `**Architecture:** Overview, API Surface`.
Use `Full` to load the entire document.

## Reference Docs with Deviation Tracking

A `docs/` directory holds external specs the agents must respect — API
contracts, design systems, SDK manuals. Originals are immutable to
agents (only you, and `[/discuss]` with your confirmation, edit them).

```
docs/
├── api-contract.md
├── design-system.md
├── inbox.md             ← raw idea capture (promoted via [/discuss])
└── DEVIATIONS.md        ← Planner-appendable
```

Tickets opt in: `**Reference Docs:** @docs/api-contract.md (Section: Auth)`.
When a Planner decision conflicts with a reference doc, it appends to
`docs/DEVIATIONS.md` in the same session. The Auditor flags any code
that contradicts a reference doc without a logged deviation.

## File Structure

```
your-project/
├── CLAUDE.md                       ← Router (auto-loaded by Claude Code & Cursor)
├── .claude/
│   ├── settings.json               ← PreToolUse (authority) + SessionEnd (trace) hooks
│   ├── agents/                     ← Role definitions for the loop's headless sessions
│   │   ├── cdd-planner.md          ← Plans; never executes, never calls other agents
│   │   ├── cdd-generator.md        ← One ticket, TDD, inside its Boundary
│   │   ├── cdd-evaluator.md        ← Contract review + provenance audit
│   │   └── cdd-monitor.md          ← Cheap trial health check; writes nothing
│   ├── driver/
│   │   ├── loop.py                 ← The deterministic loop driver (8.0)
│   │   ├── test_loop.py            ← Its test suite — run it after any driver edit
│   │   ├── notify.sh.example       ← Optional push (ntfy / Telegram)
│   │   ├── toy_project.sh          ← Offline end-to-end shakedown, build goal
│   │   └── toy_experiment.sh       ← Offline shakedown with injected trial faults
│   ├── hooks/
│   │   ├── enforce_authority.py    ← PreToolUse: denies out-of-role writes (8.0)
│   │   └── archive_transcript.py   ← SessionEnd: copies transcript → journal/traces/
│   └── rules/
│       ├── loop-protocol.md        ← The [/loop] pipeline, gates, budgets (8.0)
│       ├── principles.md           ← Simplicity, Surgical change, Think-first
│       ├── governance.md           ← Git-as-changelog, security, logging, TDD, journal
│       ├── run-logging.md          ← logs/latest.log capture
│       ├── phase-authority.md      ← Authority matrix (all six session types)
│       ├── generator-protocol.md   ← Selective context load, retry, halt
│       ├── parallel-execution.md   ← Fan-out/fan-in parallel Generator
│       └── task-ticket-format.md   ← Ticket format (+ experiment tickets)
├── skills/
│   ├── skill-template/SKILL.md     ← How to write skills
│   ├── mode-loop/SKILL.md          ← The Goal Setter + loop launcher (8.0)
│   ├── mode-discuss/SKILL.md       ← The Thinking Partner
│   ├── mode-retro/SKILL.md         ← The Coach
│   ├── mode-build/SKILL.md         ← The Architect        ┐
│   ├── mode-modify/SKILL.md        ← Refactoring Engineer  │ goal types;
│   ├── mode-migrate/SKILL.md       ← Migration Specialist  │ loaded by
│   ├── mode-merge/SKILL.md         ← Integration Architect │ the Planner
│   └── mode-evaluate/SKILL.md      ← The Auditor          ┘
├── src/
│   └── <module>/CLAUDE.md          ← Optional nested module rules
├── docs/                           ← User-maintained reference docs
│   ├── api-contract.md
│   ├── inbox.md
│   └── DEVIATIONS.md
├── journal/                        ← Session records + feedback
│   ├── 20260701-142230-modify.md   ← Tier 1: curated summary (in git)
│   └── traces/                     ← Tier 2: full raw transcripts (gitignored)
├── logs/                           ← Run output (gitignored)
│   ├── latest.log                  ← Most recent Run Command
│   ├── driver.log                  ← The loop's own output
│   └── denials.log                 ← Every authority denial, with role + reason
├── approvals/                      ← Gate flag files (gitignored, loop only)
├── Concept.md                      ← Vision (persistent)
├── Architecture.md                 ← Layered design (persistent)
├── README.md                       ← User-facing usage (Planner-maintained)
├── Goal.md + goal.json             ← The loop's frozen contract (ephemeral)
├── Plan.md                         ← Work order (ephemeral)
└── Evaluation.md                   ← Auditor output (ephemeral)
```

## Setup

### Prerequisites
- **Claude Code** or **Cursor** (or both)
- Claude Pro, Max, Teams, or Enterprise account
- Git initialized in your project, with `user.name` / `user.email` set —
  in a loop the driver is the only committer, and a commit that fails
  for want of an identity fails quietly
- For `[/loop]` only: **Python 3** (standard library only — the driver
  has no dependencies), **tmux**, and a git version with `worktree`

### Install (both tools, same files)

```bash
# Claude Code — macOS / Linux
curl -fsSL https://claude.ai/install.sh | bash
# Windows (PowerShell): irm https://claude.ai/install.ps1 | iex

mkdir my-project && cd my-project && git init
# Copy: CLAUDE.md, .claude/, skills/ into project root
printf 'logs/\njournal/traces/\n' >> .gitignore
```

**Copy all three, not just `.claude/`.** `[/loop]` refuses to start when
any of the driver, the four agent definitions, the authority hook,
`loop-protocol.md`, or the `PreToolUse` wiring in `.claude/settings.json`
is missing — and it refuses loudly rather than falling back to a manual
relay, because a loop that silently degrades still records itself as a
loop. A deployment without `skills/` starts, but the Planner then works
from its fallback instead of the mode skill that shapes tickets.

`.claude/settings.json` wires two hooks, and Claude Code asks you to
approve them on first run:

- **`PreToolUse` → `enforce_authority.py`** — the authority matrix,
  mechanically enforced. Deleting it does not just lose a nicety; it
  removes the only thing stopping a Generator from editing the goal it
  is being measured against.
- **`SessionEnd` → `archive_transcript.py`** — optional Tier-2 trace
  archiving to `journal/traces/`. Claude Code only; harmless in Cursor.

The driver adds its own ephemeral files (`loop-state.json`,
`events.jsonl`, `approvals/`, `journal/traces/`) to `.gitignore` itself
on first run — it stages the whole tree when it commits, so its
bookkeeping must not be able to land in a feature commit.

`CLAUDE.md` is the single entry point — the router for both Claude Code
and Cursor. Rule files in `.claude/rules/` are read on-demand. Nested
`CLAUDE.md` files auto-load when the agent works in their directory.
Switch tools mid-project freely; git keeps everything in sync.

### Verify the install

```bash
python3 .claude/driver/test_loop.py     # or: pytest .claude/driver/test_loop.py
```

The driver ships with its own test suite (203 tests, no dependencies);
run it after any edit to `loop.py` or the hook. For a real end-to-end
rehearsal — gates, planner, contract review, human gate, generator,
evaluator, commits, final audit — `.claude/driver/toy_project.sh`
scaffolds a throwaway project that needs no network and no GPU. That one
spends real model budget; the cost is measured, not estimated, and
documented at the top of the script.

## Usage

### Running a loop

```
You:     [/loop] Get the eval harness running against our endpoint and
         report accuracy on the social-science split.

Agent:   [Verifies the loop machinery is installed. Classifies: build.]
         "Three things I can't accept as written:
          - 'report accuracy' — which file carries the number?
          - what threshold counts as passing?
          - what must be true before the loop can start at all?"
You:     [answers]

Agent:   "I will check `acc` in results/latest.json is > 0, and
          `schema_valid` in the same file is == 1. Before starting I run
          three preflight checks: .env has both keys, the endpoint
          answers a 1-token call, the dataset directory exists.
          Nothing else is checked. Budgets: 12 iterations, 3 replans,
          $60, 24h of driver runtime. Correct?"
You:     yes

Agent:   [Writes Goal.md + goal.json — frozen from here on, for it too.
          Runs `loop.py start`: makes the worktree, launches the driver
          under tmux, says where to watch it.]

         …five gates pass · Planner plans · Evaluator reviews the
         contract · driver waits…

Driver:  == HUMAN GATE ==  Plan.md ready. Contract review: OK.
You:     [read Plan.md] approve
Agent:   [runs `loop.py approve`; the plan phase commits]

         …per ticket: generate → run → criteria checked off disk →
         evaluate → commit. Hours pass. You are elsewhere…

Driver:  done — 9/9 tickets, every criterion green, journal written.

You:     [fill the ## Feedback block; read a sample of the diffs]
         python3 .claude/driver/loop.py close
```

Keep that session alive in tmux with Remote Control on and it becomes
your control tower: message it `status` or `approve` from your phone.
Ask it for `status` at any point and it reads the event feed back to
you — phase, iteration, spend, which criteria are green.

### Discussing direction (before you build)

```
You:     [/discuss] A new paper suggests we chunk PDFs semantically
         instead of by page. Does that fit our Concept?

Agent:   [Reads Concept.md, Architecture Overview, docs/. Weighs
          trade-offs against current design, quotes the relevant docs.]
Agent:   "Proposal: add this to Concept.md §Scope and a note in
          docs/extraction.md. Confirm?"

You:     yes

Agent:   [Edits Concept.md + docs, commits `docs: semantic chunking
          direction`. Recommends [/modify] when you're ready to build.]
```

### Driving the phases by hand (the escape hatch)

The three examples below are 7.0-style manual operation: you invoke each
phase yourself and nothing runs unattended. It stays supported — the
driver calls exactly these skills — and it is the right mode when you
want to watch every step, or when a goal genuinely resists being written
as a machine-checkable criterion.

#### Building a new project

```
You:     [/build] A FastAPI app that uploads PDFs, extracts text, and
         summarizes them with an LLM. React frontend.
Agent:   [Writes Concept.md, asks about stack and edge cases]
You:     proceed to spec
Agent:   [Env audit; writes Architecture.md, README.md, skills,
          Plan.md (first ticket "Environment Setup", adds logs/ to
          .gitignore); commits + journals]
Agent:   "Planner session complete. Review the files. Place [Halt here]
          if needed. Type start execution when ready."

You:     start execution
Agent:   [Executes tickets; runs tee to logs/latest.log; commits per
          ticket; journals]
Agent:   "Generator session complete. Ready for your evaluation."
```

#### Modifying — features AND bugs

```
# Feature
You:     [/modify] Add batch upload with concurrent PDF processing
Agent:   "Warning: current pipeline is synchronous. Options: ..."
You:     proceed to spec
Agent:   [Updates Architecture + Overview + README surgically, writes
          fresh Plan.md with regression tests]

# Bug (same mode — bug sub-flow)
You:     [/modify] Extraction returns empty text for scanned PDFs
Agent:   [Creates Triage.md with 1–3 hypotheses, Tier-1/Tier-2 tests,
          Architecture sections per hypothesis]
You:     start execution

# Bug from a failing run
You:     check the latest run log and fix it
Agent:   [Reads logs/latest.log, identifies the error, opens a
          [/modify] bug sub-flow to fix it]
```

#### Evaluating, signing off, and improving

```
You:     [/evaluate]
Agent:   [Runs tests + app, checks Concept/Arch/docs/README consistency,
          simplicity, context; writes Evaluation.md + journal]
Agent:   "Evaluation complete. Verdict: PASS WITH ISSUES."

You:     [act on fixes; delete Plan.md + Evaluation.md; fill the
          Feedback block in journal/]

You:     [/retro]
Agent:   [Reads journal/ across loops] "3 of the last 5 modify loops
          flagged Boundary overreach. Recommend tightening the Boundary
          rule; and you tend to skip [Halt here] on large plans."
```

## Key Concepts

### Task Tickets

```markdown
### Phase 2, Step 3: Build Extraction Pipeline

**Input:** src/models/document.py
**Output:** src/pipeline/extractor.py, tests/test_extractor.py
**Spec:**
- Function `extract_text(doc: Document) -> ExtractedContent`
- Handle: PDF, DOCX, plain text
- On failure: raise `ExtractionError`

**Test Contract:**
- test_extract_pdf_success: valid PDF → ExtractedContent
- test_extract_unsupported: .xlsx → ExtractionError
- test_extract_corrupt: truncated PDF → ExtractionError

**Manual Verification:**
- Upload multi-page PDF; confirm all pages extracted
- Upload scanned PDF; confirm OCR fallback works

**Architecture:** Overview, Data Models
**Skills to Load:** @skills/fastapi-backend/SKILL.md
**Reference Docs:** @docs/api-contract.md (Section: Documents)
**Process Logging:** Expensive
**Depends On:** Phase 1 (Environment Setup)
**Parallel Group:** A
**Boundary:** src/pipeline/, tests/test_extractor.py
**Run Command:** uv run pytest tests/test_extractor.py -v 2>&1 | tee logs/latest.log
```

`Depends On` + `Parallel Group` let the Generator build independent
tickets concurrently. Here, any other Group-A ticket that also depends
only on Phase 1 and has a **disjoint Boundary** (e.g. `src/auth/`) runs
at the same time as this one.

**Experiment tickets** swap the Test Contract for a **Hypothesis**, a
**Trial** (the exact launch command — the *driver* runs it, never the
Generator), a **Metrics Contract** (which file each metric lands in), a
**Success Threshold** mapping 1:1 to a `goal.json` criterion, and a
**Monitor Profile** (poll interval plus known failure signatures like
`cuda_oom`, `nan_loss`, `stall`). They are precise about outcomes and
interfaces and deliberately light on implementation path — granular
technical detail specified upfront cascades errors when it turns out to
be wrong.

### Generator Retry Logic
1. Attempt to fix (try 1). 2. Try again (try 2). 3. Final attempt (try
3). 4. Still failing → commit progress with a WIP message and stop.

In a loop the driver owns the retry, up to three attempts per ticket,
and each retry **carries the verdict that rejected the previous
attempt** — re-sending the ticket body alone can only help a
nondeterministic fault. A Generator session that changed nothing twice
running escalates instead of buying a third identical session.

### `[Halt here]` Flags — manual mode only
The Planner does NOT place halt flags. You place them after reviewing
the work order, wherever you want the Generator to pause.

**This applies only to the manual `start execution` escape hatch.**
Loop mode (`[/loop]`) has no mid-loop halt gate: it would ask you to
guess, before seeing any output, which ticket you will want to inspect.
Loop mode has exactly three gates — plan approval, every replan, every
escalation — all event-driven, plus the deterministic criteria and
budget gates that stop the loop when something is actually wrong.

### The Evaluation Model
- **Layer 1 — TDD (automated).** Tests before code.
- **Layer 2 — The criteria gate (loop, free).** `check_criteria()` reads
  each criterion's metric out of its source file and compares it. Code,
  not a model; fail-closed, so a missing file or an absent metric is a
  failure. It also acts as a regression guard on every ticket.
- **Layer 3 — Manual Verification.** Each ticket lists what to inspect.
- **Layer 4 — Auditor (`[/evaluate]`, the loop's Evaluator).**
  Independent *execution* + consistency + simplicity + context/README
  audits, with a verdict. Layer 2 proves a number met its threshold; only
  this layer can tell you the number was earned. Keep both — the cheap
  one being free is not a reason to delete the expensive one.
- **Layer 5 — You.** Sign off, then log feedback in `journal/`.

## Syncing Your Docs — use git, not Drive sync

Docs that drive development should live **in the repo (e.g. GitLab)**,
not in Google Drive with rsync into a VM. Reasons: versioned and
diffable, one auth (SSH key/token), headless `git pull` on any
machine/VM, docs that change *atomically* with the code they describe,
and the agent reads them natively. Drive sync on headless Linux servers
is exactly the auth/rsync pain to avoid.

Recommended workflow:
- Keep `Concept.md`, `Architecture.md`, `README.md`, and `docs/` in the
  repo. Push to GitLab. On any machine: `git clone` / `git pull`.
- Capture away-from-repo ideas (a new paper, an aha moment) in
  `docs/inbox.md` (or a notes app as scratchpad), then **promote** them
  into `Concept.md`/`docs/` during a `[/discuss]` session.
- Source of truth for anything that touches development = git. Drive/
  Notion at most a scratchpad.

## Improving the Framework (this repo)

The framework repo is itself a CDD project: retro summaries and
personal feedback from real projects are copied into `journal/`,
`[/retro] all` surfaces cross-project patterns, and a Maintainer
session applies accepted recommendations, bumps the version, and tags
a release. Deployed projects upgrade by diffing tags
(`git diff v8.1.15..v8.1.16 -- CLAUDE.md .claude/ skills/`) and
re-copying — never by patching template files in place. When a live loop
forces you to patch anyway, `git format-patch` it into the framework's
`journal/hotfixes/` so the next release doesn't reintroduce the bug.
Full playbook: [`MAINTENANCE.md`](MAINTENANCE.md).

## Roadmap (not built yet)

- **Federated subsystems.** For big projects with loosely-coupled parts
  (annotation, preprocessing), one monorepo where each subsystem has its
  own `Concept.md`/`Architecture.md`/`skills/`, and modes scope to the
  active subsystem (`[/modify] @annotation ...`) so other subsystems'
  docs don't distract the agent.

## Version History

| Version | Key Change |
|---|---|
| 1.0–3.0 | Prompt-in, code-out. Context collapse. |
| 3.5 | Decoupled design from implementation. |
| 4.0 | 3-Phase Pipeline. Git, TDD, CHANGELOG. |
| 4.1–4.2 | Dynamic skills. Programmable `[Halt here]`. |
| 5.0–5.3 | Personas via mode commands. Phase-based authority. |
| 5.5–5.6 | Session-based dev. Git checkpoints. Dual-tool (Claude Code + Cursor). |
| 6.0 | Layered Architecture. Environment audit. `[/evaluate]`. Reference docs + DEVIATIONS. |
| 6.2 | Renamed to Concept-Driven Development. `.claude/rules/`. Always-on principles. Nested `CLAUDE.md`. `[/merge]`. Independent Auditor. Process logging. |
| **7.0** | **Parallel Generator (Planner-declared `Depends On:` / `Parallel Group:`, fan-out/fan-in). Run-log capture (`logs/latest.log`). `[/discuss]` mode. `[/debug]` folded into `[/modify]`. Planner-maintained `README.md`. Two-tier session journal (curated summaries + optional full-trace `SessionEnd` hook) + `[/retro]` coach. Git history replaces `CHANGELOG.md`. Doc-sync guidance (git over Drive).** |
| **8.0** | **Loop orchestration: 3-command surface (`[/discuss]`/`[/loop]`/`[/retro]`); deterministic driver (`.claude/driver/loop.py`); hook-ENFORCED phase authority (PreToolUse deny); Goal.md/goal.json contracts; experiment tickets + trial ledger + Monitor agent; Evaluator contract review pre-gate; JSON machine state; control-tower remote control (phone). Design: docs/loop-orchestration-design.md.** |
| **8.1** | **Deterministic gates: `check_criteria()` reads `goal.json` criteria straight off disk (fail-closed) as the per-ticket regression guard and the final stop condition; `preflight()` verifies environment preconditions declared in `Goal.md` before any model call; `machinery()` refuses to start when the loop's own parts are missing instead of degrading to a manual relay; `validate_goal()` rejects a contract with no machine-checkable criteria. USD budget enforced; GPU-hours billed against trial start (was reset every Monitor poll); a killed trial no longer gets evaluated; contract review fails closed. Evaluator must execute rather than read, and audits provenance. `Goal.md` is the source of truth with `goal.json` a derived mirror, audited by contract review (Faithful?/Sourced?). Driver refuses the primary working tree. `[Halt here]` removed from loop mode. Motivated by journal/feedback-inbox.md 2026-07-17 + from-ccd-ai-bench-retro-20260715.md.** |
| **8.1.1–8.1.3** | **First real loop runs. 8.1.1–8.1.2: trial exit code checked, spend actually accumulated (so `max_usd` bites), multi-line ticket fields kept whole, `approve` targets the pending gate, Planner may write a nested `CLAUDE.md`, a PASS that never reached git escalates; `loop.py start` (worktree + tmux), `status` for humans, unauthenticated-CLI gate, per-session heartbeat events. 8.1.3: a Boundary written as markdown (the form the Planner actually emits) still matches real paths — before this, every entry kept its backticks and matched nothing, so the first end-to-end loop denied every Generator write and escalated on ticket 1; the same field habit on `**Trial:**` was command substitution under `shell=True`. Motivated by journal/from-tmmluplus-eval-retro-20260730.md + journal/feedback-inbox.md 2026-07-30.** |
| **8.1.4** | **The loop's first COMPLETED run. Plan parsing accepts a ticket heading at any level and marks it back at that level (a `##` plan parsed as zero tickets); an unparseable plan escalates instead of reporting `all_tickets_done` with nothing built; contract review reviews every revision it pays for (reviews = revisions + 1) rather than escalating while holding an unreviewed plan; the Planner must check that some ticket's Run Command WRITES each criterion's source file; the human gate prints the absolute path to Plan.md and `status` never truncates an escalation. Toy harness re-budgeted from measurement and its traces gitignored. Four end-to-end runs, journal/feedback-inbox.md 2026-07-30.** |
| **8.1.5** | **The experiment path's first end-to-end run — trials, the Monitor, RETRY, REPLAN and the ledger as replan memory, none of which a `build` goal ever touches. New toy harness `.claude/driver/toy_experiment.sh` (deterministic fault injection, no GPU, no network) that forces all of them. Three defects fixed: the driver now ensures its own ephemeral files (`loop-state.json`, `events.jsonl`, `journal/traces/`) are gitignored, so a `feat(loop):` commit carries the ticket's work and not the loop's bookkeeping; a trial log is named per ATTEMPT, so the relaunch a RETRY buys no longer truncates the log of the failure that bought it; and `cdd-planner.md` now states the goal-type → mode-skill mapping, because the driver names a type and there is no `skills/mode-experiment/` to find. Journal: journal/feedback-inbox.md 2026-07-30 (experiment run).** |
| **8.1.6** | **The first LIVE run (real endpoint, real dataset) and the six defects it exposed. Evidence ownership: at most one ticket's Boundary may admit a criterion's `source` file, and it must name the file rather than its tree — a `results/` entry on four tickets let a schema ticket's test fixture turn three criteria green four iterations before the harness existed, and the driver now rejects such a plan before paying for a contract review. A RETRY carries the verdict that rejected the previous attempt (it used to re-send the ticket body alone, so three sessions changed zero bytes), and a Generator that writes nothing twice escalates instead of buying a third identical session. Under `final-pass` cadence the iteration where a criterion FIRST reads green always buys a provenance audit. The driver writes the loop's journal record on every terminal exit (the docs had promised this for two versions; nothing did it), re-reads budget caps every iteration so raising one no longer needs a restart, and `loop.py close` performs the housekeeping four consecutive retros asked for. Journal: journal/from-tmmluplus-eval-retro-20260731.md.** |
| **8.1.7** | **What the first toy `build` loop on 8.1.6 charged for. `max_wall_hours` meters DRIVER RUNTIME, not the calendar: the clock stops at every human gate and between runs, and a crashed run is credited only to its last recorded event — a loop that sat 3.6h at the plan gate used to escalate `budget exhausted` the instant the approval landed, before one ticket ran, with $0 spent since resume, which contradicted the framework's own approve-from-your-phone gate. Contract review is bounded by MONEY as well as rounds (it stops buying rounds past half of `max_usd`, always buys the first review, and the gate banner says which), and `cdd-evaluator` Mode 1 now has a ceiling: read the plan, do not re-implement it — three passes that each rebuilt a four-ticket plan cost 59% of a loop's spend before ticket 1. The PreToolUse shell scanner no longer reads the `>` of a Python return annotation as a redirect, which was the rare case of it failing CLOSED on legal work. The plan phase commits at its gate (`plan(loop):`), so a `feat(loop):` commit carries exactly one ticket and a per-ticket Boundary audit is a check that can pass. Journal: journal/retro-20260731-toy-816.md.** |
| **8.1.8** | **The toy becomes a faithful deployment, and the contradiction that hid behind it. Both scaffolders now copy `CLAUDE.md` and `skills/` alongside `.claude/` — until now the smoke test copied `.claude/` alone, so the Planner used its documented fallback and the harness never once exercised the mode-skill path, the part that shapes tickets: it proved the driver, not the framework. That exposed a live conflict: the 7.0 mode skills open with an INTERACTIVE Ask phase ending in "STOP. Loop until the user says 'proceed to spec'", which a headless loop Planner cannot follow. `cdd-planner.md` now states the rule (skip the Ask/Halt step; `Goal.md` IS the Ask phase's output; unanswered questions become Assumptions in `Plan.md`; a genuine blocker is stated, never guessed around), and every halting mode skill points at it — with a test that keeps them pointing. `machinery()` reports a thin deployment as an event rather than aborting, because the Planner's fallback is legal and the choice is the user's. Journal: journal/retro-20260731-toy-816.md problem 5.** |
| **8.1.9** | **The cost of a wrong denial and of a reverted budget — the first deployment loop the framework did not itself run. The PreToolUse shell net no longer denies by CO-OCCURRENCE: it matched the `>` of `2>&1` as a write to any protected file the command merely NAMED, killing a read-only Evaluator audit mid-loop, and a legal Run Command that passed `goal.json` as an argument and teed to `logs/` was denied for every role. Redirects are decided by the precise target scan (which already denied `echo x > goal.json`) and the loose net tests per shell segment. Every denial now lands in `logs/denials.log` and a `hook_denials` event, because a false positive used to cost a transcript dig. `start` SEEDS `Goal.md`/`goal.json` into a worktree once and never overwrites: re-copying the primary tree's copy on resume reverted an approved budget raise twice in one loop, and since a restart itself consumes an iteration, each repair round paid for the failure it was repairing (three spurious `max_iterations` escalations for a finished loop). A `Preflight` check must EXERCISE a pinned third-party harness's runtime path, not just install it (three of that loop's seven interruptions were this class, each surfacing alone at tickets 7–8), with a Planner self-check as the second net. A Hard Rule about a pinned tool must cite where it was verified against that version — one such rule shipped as the exact inverse of the harness's behaviour. The journal record separates calendar time from driver runtime, so "too many human interruptions" has a number. MAINTENANCE.md gains a hotfix inbox: both fixes here were live in a deployed project for days with no path home. Journal: journal/from-aibench-retro-20260802.md.** |
| **8.1.10** | **The v8.0 line released as the mainline, and the docs made to match it. The README was still a 7.0 document with 8.x rows bolted onto its version table: it opened on the manual session pipeline, routed users to `[/build]`/`[/modify]` as primary commands, described `[/loop]` nowhere in Usage, and its file tree predated the driver, the agents and the authority hook. Rewritten around the loop — how it works, what the four gates buy, what the hook enforces and what it knowingly does not, the loop's own ephemeral files, an install that names the `[/loop]` prerequisites and a way to verify them, and a walkthrough of a real run. Two dangling pointers to `v8.0-draft/INSTALL.md` — a path that never shipped — removed, including the one in `machinery()`, which is the single message a half-deployed project ever sees. `docs/loop-orchestration-design.md` no longer claims to be an unimplemented draft and names where the shipped loop diverged from it. Version History reordered chronologically. Prompted by the release itself, not by a retro.** |
| **8.1.11** | **Eight PreToolUse hotfixes brought home from a deployed project, plus the two corrections importing them revealed. The aibench deployment ran eight loops on 8.1.9 and patched its own copy of `enforce_authority.py` seven times to keep going; that retro then measured the class it was patching — **8 of 19 escalations, 42% of every reason a loop stopped**, most of them killing an Evaluator mid-audit, so the loop paid for the session twice. Every one denied a read-only or out-of-tree action the agent contract requires: redirect syntax taken as a write target (`tee x.log > /dev/null` read as a file named `>`), `>=` read as a redirect, a `>` inside a quoted `--format` string, heredoc BODIES scanned as shell (the code contradicting its own documented fail-open contract), the git-write net spanning newlines so a read-only `git log` and a later bare `add` matched as one command, the listing forms `git tag -l` / `stash list` / `worktree list` denied on the verb, a redirect handed to `cp`'s trailing-argument rule as its destination — which also LEAKED, since `cp a.txt Architecture.md > /dev/null` then decided `/dev/null` and never the core file — and `Write` to `/tmp` denied while the same write through the shell was allowed, on the one iteration where five criteria first went green, to an Evaluator whose contract REQUIRES /tmp reconstruction. None of the eight shipped with a test, which is why the class kept recurring after two of them had already landed; 14 regression tests now pin each false positive next to the real denial it narrows. Two corrections on import: the scratch carve-out is decided on the RESOLVED path (the reviewing Evaluator's own non-blocking finding F3 — `abspath` follows nothing, so `/tmp/x -> <repo>/goal.json` read as scratch), and it is two-sided, because a one-sided prefix check silently exempted every core file of any tree rooted in `/tmp`. Journal: journal/from-aibench-retro-20260818.md; patches in journal/hotfixes/.** |
| **8.1.12** | **What a criterion IS, and when a number on disk counts as this loop's result. Same retro, failure class 2 — the second-largest reason a loop stopped. Three changes, all deterministic. (1) A criterion is identified by `metric@source`, not by its bare metric name: two criteria measuring the same quantity in different files were ONE entry in the green set — six criteria under four names in one loop, thirteen under nine in another — so a regression in one of a colliding pair was invisible while the other stayed green, and `first_green` fired once for the pair, meaning the second criterion's first green bought no provenance audit under `final-pass`. (2) `criteria_due()`: a criterion whose `source` a LATER ticket owns is neither green nor red until that ticket runs. `plan_problems()` already computed the owner map and threw it away. One loop went first-green on `passed`/`failed` off the previous loop's committed `results/test-summary.json` while running a probe that writes no test summary; another did the same and then paid twice — the stale file was cleared, the guard read green→red and forced a RETRY, and the Generator stopped to argue that the criterion was not its evidence to produce, on ticket 1 of 9 in the loop that cost $70.89 and did not finish. Deferred criteria stay out of the regression comparison, so clearing stale evidence is free. (3) `evidence_gate()`, a fifth pre-Planner gate: a fresh loop whose criteria read files that ALREADY EXIST refuses to start, for $0, and says the fix — give each `source` a path only this loop can write. A loop had sat at its plan gate with four criteria green off the previous loop's records, carrying the very harness pin it existed to replace, and the control tower recorded that it could not even delete them: under the bare-name guard that would have manufactured a regression and burned an iteration. `mode-loop`'s Ask phase now requires a per-loop evidence path and names `latest.json` as the shape that fails. 12 tests. Journal: journal/from-aibench-retro-20260818.md.** |
| **8.1.13** | **The first two 8.1.12 loops, and the four things that stopped them — one escalation per two iterations, up from one per three. Four causes, only one of them in the state machine, so the fix is four small ones. (1) **A dead session is not a verdict.** `claude()` never looked at the exit code, so an Evaluator that died on its first token with API Error 529 and wrote nothing was read as "missing verdict.json" → ESCALATE — stopping a loop whose 2.7h trial had already SUCCEEDED, and costing a human, a hand-made commit and a restart, which costs an iteration. The SESSION is now re-dispatched once (never the ticket: re-running the ticket is what would re-run the trial), and if it dies twice the escalation says so, because "the work is intact and unjudged" and "the auditor refused to write a verdict" need different human moves. (2) **The hook resolves variables, incrementally.** `$M` was decided as a repo-relative file named `$m`, which denied the Evaluator's contractual `/tmp` reconstruction — and that denial is what pushed a control tower into patching this hook under a running loop, where its patch (`finditer`, last-write-wins, no position awareness) opened a fail-open that allowed `M=Architecture.md; echo x > $M; M=/tmp/ok`. Assignments now bind per shell segment, against what precedes them; a target still carrying an unresolved `$` is dropped, which is the fail-OPEN the module docstring always promised for expansion. Both directions pinned by test, including reverse order. (3) **A heredoc body is data on EVERY scan.** 8.1.11 truncated heredocs inside the target scan only, so the git net and the loose net still read the body as shell: a Planner writing the file it OWNS with `cat > Plan.md <<'PLANEOF'` was denied "Git write commands are driver-only" because prose in the plan put `git` and a subcommand word on one line. (4) Two authoring rules for the layer where the other two escalations were born: the contract review gains a **Grounded?** check — does any Spec contradict a fact `Goal.md` declares established? (a plan reused one reader across two data shapes the goal explicitly distinguishes, passed review, and the Generator stopped six minutes after the human gate) — and the Ask phase gains **never point a criterion at the answer**: a loop escalated on `coverage >= 0.90` at 0.8978, three calls short of 1067, on the last ticket, hours after the science was finished. 17 tests. Journal: journal/from-aibench-retro-20260819.md.** |
| **8.1.14** | **What stopped the loop that was launched an hour after 8.1.13 shipped, and the review layer it exposed. (1) **A quoted span is data.** The last place the decide-on-text class was still live: `echo "--- git worktree ---" && git worktree list` was denied on the ECHO LABEL while the real listing beside it was scrubbed correctly, and `grep "git commit" logs/x` was denied for naming what it searched for. `git` is a command only where the shell would execute it, so quoted spans are blanked before the git net — while the TARGET scan keeps the ones without metacharacters, where a quoted span may still BE a target (`tee 'Plan.md'`). Sixth false positive of this class, and the most expensive: it killed contract review round 3, the driver read the silence as REVISE, spent the last revision and escalated a plan nothing had reviewed. Fails OPEN on `sh -c "git push"` — an interpreter escape, out of scope by the module docstring, and now asserted by a test so the hole is visible rather than discovered. (2) **The contract review executes one class of check.** It was a document review by design, and every finding it has ever produced in a real deployment was the same class: the plan reads a field, key or path that does not exist in the thing it reads from — a reader aimed at two data shapes, a `doc_hash` that is one constant value across 900 rows, `sample_outcomes()` reading `repeat["harness"]` and a `domain` the declared record shape does not carry. Minutes of careful reading each, one command each, and one of them was missed outright — it passed review and the Generator stopped six minutes after the human gate. The new **Wired?** check demands a pasted command and its output rather than a conclusion, and the v8.1.7 'do not build it' ceiling gets its line drawn: EXISTENCE is a spot-check and is required, BEHAVIOUR is building and is forbidden. 250 tests. Journal: journal/from-aibench-loop11-contract-review.md.** |
| **8.1.15** | **The route that never fired, and the bar that was never measured — the 2026-08-24 retro over fifteen deployed loops. (1) **A Generator stop is adjudicated, not auto-escalated.** REPLAN — fresh Planner + ledger + human re-gate, built for exactly the "plan is defective" case — fired ZERO times in fifteen loops, because its only entrance was an Evaluator Mode-2 verdict and a stop returned before any Evaluator ran; every plan defect the Generator caught woke a human to do what a Planner session does, and the manual pipeline handled the same event the same week with a Planner revision session whose only human touch was a `git revert`. On `STATUS: stopped` the driver now dispatches one bounded read-only Evaluator session (Mode 3) that routes REPLAN (plan defect — gated and ledgered like every replan) / RETRY (the Generator misread; the retry carries what it missed) / ESCALATE (implicates the goal contract, or anything no replan can fix); fail-CLOSED, so a dead adjudicator escalates with the stop report exactly as before. The human still approves every replan — the touchpoint changes shape from diagnosis to approval. (2) **`loop.py replan "<reason>"`** — the user-initiated half of the same route, recommended by two consecutive retros while the workaround on record was hand-editing `loop-state.json` under a running loop. (3) **A stopping bar names where its number was measured.** A never-measured `>= 0.90` escalated at 0.8978 hours after the science was finished, and the contract review had predicted the band with no lever to move a frozen criterion: the Ask phase now requires provenance for any bar above presence (no measurement → this loop records `>= 0`, the bar graduates to the next loop's goal), and the review gains an **Earnable?** check that puts a labelled `CRITERIA CONCERN:` line where the user will see it at the gate. 258 tests. Journal: journal/retro-20260824-aibench.md.** |
| **8.1.16** | **What two deployments' 2026-09-02 retros charged the framework for — thirteen loops, $1,878, and three classes behind most of the cost. (1) **The hook decides where the shell would write.** A `cd` is tracked per segment exactly as assignments are (v8.1.13), so `cd /tmp && echo x > notes.txt` is scratch and `cd src/pkg && echo x > ../../Architecture.md` is a core-file write — it used to be ALLOWED; the loose net blanks quoted spans before looking for a verb, so a `grep` pattern containing `rm` is not a removal; an escaped `\"` no longer ends a double-quoted span; the listing forms take their options. ~110 denials across twelve loops, five sessions killed, one plan reshaped to route around the net; each fix pinned beside the real denial it must not loosen. (2) **A ticket PASSes only with its outputs on disk.** Before any audit is bought the driver checks every Output path the Boundary covers, that a Run Command left a log under this dispatch, and that no criterion the ticket OWNS reads red — three tickets had PASSed having produced nothing. The same check exempts an abandoned run from the no-op backstop: a Generator's Bash call is capped at 600 s, eight 20–35 minute runs were abandoned in two loops, and no rule mentioned the cap — now three do, and a Trial runs under bash rather than dash. (3) **The Monitor has a memory.** Five of six kills across two campaigns were healthy trials; the Monitor is handed its last three verdicts and the driver overrules a kill whose quoted evidence sat in a window a prior poll judged HEALTHY. Also: the retry cap is adjudicated once (three converging attempts were stopped by the counter; attempt 4 passed), `max_gpu_hours: 0` is no cap, `.env` and the venv are seeded into the worktree, a contract review is remembered with the plan it reviewed, `loop.py note` records a manual change when it is made, denials are counted as records and finally shown in the journal. Ask phase: three questions per criterion (can it fail for its reason; is the metric name emitted; do numerator and denominator come from different objects), every number carries its command, a recorder writes `null`. Planner self-check: grep consumers, `Disk:` per iteration, banked evidence survives until its replacement has measured. `[/modify] @Evaluation.md` fast path. 297 tests. Journals: journal/from-agentrl-retro-20260902.md, journal/from-aibench-retro-20260902.md.** |

## Tips

- **Discuss before big pivots.** A `[/discuss]` that prevents a bad
  build is cheaper than the build.
- **Spend the Ask phase.** Every minute making a criterion checkable
  buys back an hour of auditing prose later. If you can't say which file
  carries the number, the loop can't tell you it's done.
- **Set budgets as if something will spin overnight**, because
  eventually it will. For a first unattended run, put `max_iterations`
  near the ticket count, not at 20.
- **Read a sample of the loop's diffs afterwards** and explain them to
  yourself. With no mid-loop checkpoint, this is the only thing standing
  between you and a codebase you no longer understand.
- **Close the loop** (`loop.py close`). Four consecutive retros flagged
  loops left open with the reminder already in place — so make it the
  command you run, not the thing you remember.
- **Say "check the latest run log."** Let the agent read the error
  instead of pasting it.
- **Fill the journal feedback.** `[/retro]` is only as good as the
  honest ratings you log — especially "instruction not followed."
- **Approve the SessionEnd hook** (Claude Code) if you want full raw
  traces to dissect bad loops; otherwise Tier-1 summaries alone still
  power `[/retro]`.
- **Keep the Architecture Overview tight.** It's the only always-loaded
  section.
- **Keep nested `CLAUDE.md` to rules, not data.**
- **Drop contracts into `docs/` early**, and idea scraps into
  `docs/inbox.md`.
- **Write detailed commits** — they're your changelog now.
- **Switch tools freely.** Files are tool-agnostic.

## License

Open for personal and commercial use. Attribution appreciated.
