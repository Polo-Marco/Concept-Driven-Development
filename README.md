# Concept-Driven Development (CDD) 8.1

A structured AI development framework built on a session-based pipeline.
You align. The Planner designs. The Generator builds. The Evaluator
(optional) audits. You sign off. The Coach (optional) helps you improve.
Git is the checkpoint system **and the changelog**.

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

CDD 7.0 addresses all of these with a strict pipeline, structured files
as external memory, layered Architecture and nested `CLAUDE.md`,
always-on engineering **principles**, an environment audit, `docs/` +
`DEVIATIONS.md` for tracked drift, **run-log capture**, a **discuss
mode** for direction, **Planner-maintained README**, and a **session
journal + retro** for improving how you build.

## How It Works

### The Session-Based Pipeline

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
task tickets literally, captures each run to `logs/latest.log`, and
commits per ticket. When the Planner has marked independent tickets with
a **Parallel Group**, the Generator builds them concurrently
(fan-out/fan-in) instead of one at a time.

**Evaluator Session** is optional and independent. It runs the output,
cross-checks Concept/Architecture/docs/**README**/code, audits for
redundancy and missing context, and writes `Evaluation.md`.

**You are the final Evaluator.** You sign off, and you fill the
**Feedback** block in the session journal.

**Retro Session (optional)** is your coach. It reads `journal/` across
loops, finds patterns in what worked and what didn't, and recommends
concrete framework/skill/habit changes.

### Git Is the Changelog

There is **no `CHANGELOG.md`** in 7.0. Git history *is* the changelog —
every session can read it, and commit messages carry the weight, so
they must be detailed:

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

### The Three Commands (v8.0)

| Command | Persona | Purpose |
|---|---|---|
| `[/discuss]` | The Thinking Partner | Think. Align direction; edit docs/Concept. No code. |
| `[/loop]` | The Goal Setter | Do. Measurable goal in → driver-orchestrated Plan/Generate/Monitor/Evaluate → answer out. |
| `[/retro]` | The Coach | Improve. Review journals; tune framework + habits. |

Build/modify/migrate/merge are now **goal types** inside `[/loop]`;
`[/evaluate]` is the loop's Evaluator agent; `start execution` is
issued by the driver. The 7.0 mode skills remain in `skills/` and can
still be invoked manually as an escape hatch — the driver calls the
same skills you would.

### Which Mode? (decision guide)

```
Nothing exists yet (no Concept.md)? .................... [/build]
Existing non-CDD code to adopt? ....................... [/migrate]
Combining two+ existing projects? ..................... [/merge]
Want to think / redirect before changing anything? ... [/discuss]
Adding a feature or refactoring? ..................... [/modify]  (feature flow)
Something is broken / wrong output / a stack trace? .. [/modify]  (bug sub-flow)
Generator finished; want an independent audit? ....... [/evaluate]
Want to improve how you build, from logged facts? .... [/retro]
```

**Your typical life:** one `[/build]` to go 0→1, then repeated
`[/modify]` as you keep building features and fixing bugs on top. Reach
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

| File | Planner | Generator | Evaluator |
|---|---|---|---|
| Concept.md | Read / Write | Read only | Read only |
| Architecture.md | Read / Write | Read only (selective) | Read only |
| README.md | Read / Write | Read only | Read only |
| Plan.md / Triage.md | Read / Write | Read only (mark `[x]`) | Read only |
| skills/ | Read / Write / Create | Read only | Read only |
| `**/CLAUDE.md` (nested) | Read / Write / Create | Read only | Read only |
| docs/*.md | Read only | Read only | Read only |
| docs/DEVIATIONS.md | Read / Append | Read only | Read only |
| Evaluation.md | — | — | Read / Write |
| journal/*.md | Append | Append | Append |
| src/, tests/ | — | Read / Write (within Boundary) | Read only |

**Discuss** may edit `Concept.md` + `docs/` (with your confirmation),
nothing else. **Retro** may write only `journal/`. Full matrix in
`.claude/rules/phase-authority.md`.

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

Git history replaces `CHANGELOG.md`.

## What's New in 7.0

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
tickets. In 7.0 the **Planner decides** what can run in parallel — at
plan-time, not the Generator at runtime — because judging cross-ticket
dependencies is an architectural call. It declares this with two ticket
fields:

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

### Carried over
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
│   ├── settings.json               ← SessionEnd hook: archive full trace (new in 7.0)
│   ├── agents/                     ← cdd-planner/generator/evaluator/monitor (new in 8.0)
│   ├── driver/loop.py              ← deterministic loop driver (new in 8.0)
│   ├── hooks/archive_transcript.py ← Copies transcript → journal/traces/ (new in 7.0)
│   ├── hooks/enforce_authority.py  ← PreToolUse authority enforcement (new in 8.0)
│   └── rules/
│       ├── loop-protocol.md        ← the [/loop] pipeline (new in 8.0)
│       ├── principles.md           ← Simplicity, Surgical change, Think-first
│       ├── governance.md           ← Git-as-changelog, security, logging, TDD, journal
│       ├── run-logging.md          ← logs/latest.log capture (new in 7.0)
│       ├── phase-authority.md      ← Authority matrix (Planner/Gen/Eval/Discuss/Retro)
│       ├── generator-protocol.md   ← Selective context load, retry, halt
│       ├── parallel-execution.md   ← Fan-out/fan-in parallel Generator (new in 7.0)
│       └── task-ticket-format.md   ← Ticket format (+ Depends On / Parallel Group)
├── skills/
│   ├── skill-template/SKILL.md     ← How to write skills
│   ├── mode-discuss/SKILL.md       ← The Thinking Partner (new in 7.0)
│   ├── mode-build/SKILL.md         ← The Architect
│   ├── mode-modify/SKILL.md        ← Refactoring Engineer (+ bug sub-flow)
│   ├── mode-migrate/SKILL.md       ← Migration Specialist
│   ├── mode-merge/SKILL.md         ← Integration Architect
│   ├── mode-evaluate/SKILL.md      ← The Auditor
│   └── mode-retro/SKILL.md         ← The Coach (new in 7.0)
├── src/
│   └── <module>/CLAUDE.md          ← Optional nested module rules
├── docs/                           ← User-maintained reference docs
│   ├── api-contract.md
│   ├── inbox.md
│   └── DEVIATIONS.md
├── journal/                        ← Session records + feedback (new in 7.0)
│   ├── 20260701-142230-modify.md   ← Tier 1: curated summary (in git)
│   └── traces/                     ← Tier 2: full raw transcripts (gitignored)
├── logs/                           ← Run output (gitignored, new in 7.0)
│   └── latest.log
├── Concept.md                      ← Vision (persistent)
├── Architecture.md                 ← Layered design (persistent)
├── README.md                       ← User-facing usage (Planner-maintained)
├── Plan.md                         ← Work order (ephemeral)
└── Evaluation.md                   ← Auditor output (ephemeral)
```

## Setup

### Prerequisites
- **Claude Code** or **Cursor** (or both)
- Claude Pro, Max, Teams, or Enterprise account
- Git initialized in your project

### Install (both tools, same files)

```bash
# Claude Code — macOS / Linux
curl -fsSL https://claude.ai/install.sh | bash
# Windows (PowerShell): irm https://claude.ai/install.ps1 | iex

mkdir my-project && cd my-project && git init
# Copy: CLAUDE.md, .claude/, skills/ into project root
printf 'logs/\njournal/traces/\n' >> .gitignore
```

Copying `.claude/` brings the optional `SessionEnd` hook
(`.claude/settings.json` + `.claude/hooks/archive_transcript.py`) that
archives full session transcripts to `journal/traces/` — Claude Code
will ask you to approve the hook on first run. Delete
`.claude/settings.json` if you don't want it (e.g. Cursor-only).

`CLAUDE.md` is the single entry point — the router for both Claude Code
and Cursor. Rule files in `.claude/rules/` are read on-demand. Nested
`CLAUDE.md` files auto-load when the agent works in their directory.
Switch tools mid-project freely; git keeps everything in sync.

## Usage

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

### Building a new project

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

### Modifying — features AND bugs

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

### Evaluating, signing off, and improving

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

### Generator Retry Logic
1. Attempt to fix (try 1). 2. Try again (try 2). 3. Final attempt (try
3). 4. Still failing → commit progress with a WIP message and stop.

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
- **Layer 2 — Manual Verification.** Each ticket lists what to inspect.
- **Layer 3 — Auditor (optional, `[/evaluate]`).** Independent run +
  consistency + simplicity + context/README audits, with a verdict.
- **Layer 4 — You.** Sign off, then log feedback in `journal/`.

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
(`git diff v7.0..v7.1 -- CLAUDE.md .claude/ skills/`) and re-copying.
Full playbook: [`MAINTENANCE.md`](MAINTENANCE.md).

## Roadmap (planned, not yet in 7.0)

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
| **8.1** | **Deterministic gates: `check_criteria()` reads `goal.json` criteria straight off disk (fail-closed) as the per-ticket regression guard and the final stop condition; `preflight()` verifies environment preconditions declared in `Goal.md` before any model call; `machinery()` refuses to start when the loop's own parts are missing instead of degrading to a manual relay; `validate_goal()` rejects a contract with no machine-checkable criteria. USD budget enforced; GPU-hours billed against trial start (was reset every Monitor poll); a killed trial no longer gets evaluated; contract review fails closed. Evaluator must execute rather than read, and audits provenance. `Goal.md` is the source of truth with `goal.json` a derived mirror, audited by contract review (Faithful?/Sourced?). Driver refuses the primary working tree. `[Halt here]` removed from loop mode. Motivated by journal/feedback-inbox.md 2026-07-17 + from-ccd-ai-bench-retro-20260715.md.** |
| **8.0** | **Loop orchestration: 3-command surface (`[/discuss]`/`[/loop]`/`[/retro]`); deterministic driver (`.claude/driver/loop.py`); hook-ENFORCED phase authority (PreToolUse deny); Goal.md/goal.json contracts; experiment tickets + trial ledger + Monitor agent; Evaluator contract review pre-gate; JSON machine state; control-tower remote control (phone). Design: docs/loop-orchestration-design.md.** |

## Tips

- **Discuss before big pivots.** A `[/discuss]` that prevents a bad
  build is cheaper than the build.
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
