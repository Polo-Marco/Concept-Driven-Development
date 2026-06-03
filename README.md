# Concept-Driven Development (CDD) 6.2

A structured AI development framework built on a session-based pipeline.
The Planner designs. The Generator builds. The Evaluator (optional)
audits. You sign off. Git is the checkpoint system.

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

This framework addresses all nine with a strict Planner → Generator →
Evaluator pipeline, structured files as external memory, layered
Architecture and nested `CLAUDE.md` for selective loading, always-on
engineering **principles** (simplicity, surgical change), an
environment audit baked into the Planner, a dedicated `[/merge]` mode
that models each source *before* merging, opt-in process logging for
expensive pipelines, and `docs/` + `DEVIATIONS.md` for tracked spec
drift.

## How It Works

### The Session-Based Pipeline

```
Planner Session              Generator Session            Evaluator Session
────────────────             ─────────────────            ──────────────────
[/build] / [/modify]         start execution              [/evaluate]
[/debug] / [/migrate]
[/merge]

Ask: interrogate user        Read Architecture Overview   Independently audit:
Env audit                    Read ticket → load only       run code/tests,
Spec: write core files        the sections it lists        check Concept/docs,
      write Plan/Triage      TDD loop per ticket           simplicity, context
      log deviations         Commit after each ticket     Write Evaluation.md
Git commit all                                             with a verdict
STOP                         STOP when done               STOP (no commit)

     ↓                            ↓                            ↓
User reviews plan           User runs tests            User acts on verdict
User places [Halt here]     User can run [/evaluate]   User deletes Plan +
  (optional)                                              Evaluation
```

**Planner Session** has full authority over core files. It designs,
plans, audits the environment, and produces everything the Generator
needs.

**Generator Session** has zero authority over core files. It reads
task tickets and executes them literally. Selective context loading
keeps it focused on the sections each ticket actually needs.

**Evaluator Session** is optional and independent. It cannot modify
code — it runs the output, cross-checks it against the Concept,
Architecture, and docs, audits for redundancy and missing context, and
writes `Evaluation.md` with a clear verdict. Useful when working in
unfamiliar domains or after a merge.

**You are the final Evaluator.** You sign off when the work is done.

### Recovery via Git

Git commits at each ticket give you clean recovery points:

- **Generator fails?** `git reset` to the Planner commit, switch
  to a better model, `start execution` again.
- **Plan was wrong?** `git reset` to the Planner commit, start a
  new Planner session, refine the plan.
- **Partial success?** Keep what worked, start a new Planner session
  to address what didn't.

### The Six Modes

| Command | Persona | Purpose |
|---|---|---|
| `[/build]` | The Architect | 0-to-1 creation from scratch |
| `[/modify]` | The Refactoring Engineer | Feature additions, refactoring |
| `[/debug]` | The QA Lead | Root-cause analysis, bug fixing |
| `[/migrate]` | Migration Specialist | Bring an existing codebase under the framework |
| `[/merge]` | Integration Architect | Combine two+ existing projects, Architecture-first |
| `[/evaluate]` | The Auditor | Independently audit a completed Generator session |

Planner modes (`build` / `modify` / `debug` / `merge`) drive the
Planner → Generator pipeline. `[/migrate]` is Planner-only.
`[/evaluate]` runs after the Generator and is optional.

### Always-On Principles

Three engineering principles apply in every session
(`.claude/rules/principles.md`):

- **Simplicity First** — minimum code that satisfies the ticket; no
  speculative features or abstractions.
- **Surgical Changes** — touch only what the ticket requires; match
  existing style; don't refactor what isn't broken.
- **Think Before Coding** — state assumptions and surface trade-offs
  before building (the "concept-driven" half of the pipeline).

### Phase-Based Authority

Authority binds to the session type, not the model:

| File | Planner | Generator | Evaluator |
|---|---|---|---|
| Concept.md | Read / Write | Read only | Read only |
| Architecture.md | Read / Write | Read only (selective) | Read only |
| Plan.md / Triage.md | Read / Write | Read only (mark `[x]`) | Read only |
| CHANGELOG.md | Read / Write | Append only | Read only |
| skills/ | Read / Write / Create | Read only | Read only |
| `**/CLAUDE.md` (nested) | Read / Write / Create | Read only | Read only |
| docs/*.md | Read only | Read only | Read only |
| docs/DEVIATIONS.md | Read / Append | Read only | Read only |
| Evaluation.md | — | — | Read / Write |
| src/, tests/ | — | Read / Write (within Boundary) | Read only |

## Core Files

| File | Lifecycle | Purpose |
|---|---|---|
| `Concept.md` | Persistent | Vision — why it exists, scope, principles |
| `Architecture.md` | Persistent (layered) | System design source of truth |
| `CHANGELOG.md` | Persistent | What changed, when |
| `Plan.md` | **Ephemeral** | Task tickets — deleted after the loop |
| `Triage.md` | **Ephemeral** | Bug hypotheses — deleted after the loop |
| `Architecture-<source>.md` / `Merge-Analysis.md` | **Ephemeral** | `[/merge]` per-source models + conflict map |
| `Evaluation.md` | **Ephemeral** | Evaluator verdict — deleted after sign-off |
| `skills/` | Persistent | Execution patterns, rules, conventions |
| `**/CLAUDE.md` (nested) | Persistent | Module-specific conventions (Planner-maintained) |
| `docs/*.md` | User-maintained | External reference docs (immutable to agents) |
| `docs/DEVIATIONS.md` | Planner-appendable | Tracked departures from reference docs |

## What's New in 6.2

### 1. Renamed: Concept-Driven Development

The framework's method *is* concept-driven — design from an explicit
Concept and Architecture before writing code. The name now matches.
Rules live under the conventional `.claude/rules/` directory (dotted,
matching Claude Code's convention).

### 2. Always-on engineering principles

`.claude/rules/principles.md` adds **Simplicity First** and **Surgical
Changes** (with **Think Before Coding** reinforcing the Planner). These
curb over-engineering and scope creep, and the Generator's self-review
now checks against them.

### 3. Nested `CLAUDE.md` (layered, location-triggered context)

Subdirectory `CLAUDE.md` files (e.g. `src/<module>/CLAUDE.md`) hold
durable, module-specific conventions and auto-load when the agent works
in that directory. They **complement** the layered `Architecture.md`
(loaded per-ticket) and bespoke skills — not replace them. Keep them to
rules, not data.

### 4. `[/merge]` mode — Architecture-first project merging

A dedicated Planner mode for combining two or more existing projects.
It is forbidden from designing the union until it has reverse-engineered
an Architecture model of **every** source and written a
`Merge-Analysis.md` conflict map. This fixes the "blind merge" failure.

### 5. Redefined Evaluator — independent Auditor

`[/evaluate]` is no longer a checklist that restates TDD. The Auditor
runs four independent audits and emits a verdict:
1. **Execution** — actually runs tests (and the app where feasible);
   trusts no prior claim of success.
2. **Document/Concept consistency** — cross-checks Concept ↔
   Architecture ↔ docs ↔ code; flags untracked deviations.
3. **Simplicity / redundancy** — audits against the principles.
4. **Context sufficiency** — flags missing/outdated documentation
   (e.g. a new package with no usage doc).

### 6. Opt-in process logging for expensive pipelines

Tickets can set **Process Logging: Expensive**. The Generator then emits
structured stage logs (stage, input summary, timing, success/failure)
so slow/costly pipelines (OCR, long agentic chains) are debuggable
without expensive re-runs. Logging only — no caching, no bespoke
framework, and never applied to cheap functions.

### Carried over from 6.0

- **Layered Architecture.md** with selective loading.
- **Environment audit** baked into the Planner.
- **Reference docs** in `docs/` with `DEVIATIONS.md` for tracked drift.

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

Tickets declare what they need:

```
**Architecture:** Overview, API Surface, Data Models
```

Use `Full` to load the entire document.

## Reference Docs with Deviation Tracking

A `docs/` directory holds external specs the user wants the agents to
respect — API contracts, design systems, SDK manuals. Originals are
immutable to agents.

```
docs/
├── api-contract.md
├── design-system.md
├── development-manual.md
└── DEVIATIONS.md         ← Planner-appendable
```

Tickets opt in:

```
**Reference Docs:** @docs/api-contract.md (Section: Authentication)
```

When the Planner makes a decision that conflicts with a reference
doc, it appends to `docs/DEVIATIONS.md` in the same session — the
Generator then knows which parts of the spec are current. The
Auditor flags any code that contradicts a reference doc without
a logged deviation.

`DEVIATIONS.md` format:

```markdown
## api-contract.md

### Section: Authentication — JWT lifetime
**Original spec:** 24-hour token TTL
**Current implementation:** 1-hour TTL with refresh token
**Reason:** Security review required short-lived access tokens
**Decided:** 2026-05-03
```

## File Structure

```
your-project/
├── CLAUDE.md                       ← Router (auto-loaded by Claude Code & Cursor)
├── .claude/rules/
│   ├── principles.md               ← Simplicity, Surgical change, Think-first
│   ├── governance.md               ← Git, security, process logging, TDD, lifecycle
│   ├── phase-authority.md          ← Authority matrix, boundary rules
│   ├── generator-protocol.md       ← Selective context load, retry, halt
│   └── task-ticket-format.md       ← Ticket format with Architecture: + Reference Docs:
├── skills/
│   ├── skill-template/SKILL.md     ← How to write skills
│   ├── mode-build/SKILL.md         ← The Architect
│   ├── mode-modify/SKILL.md        ← The Refactoring Engineer
│   ├── mode-debug/SKILL.md         ← The QA Lead
│   ├── mode-migrate/SKILL.md       ← Migration Specialist
│   ├── mode-merge/SKILL.md         ← Integration Architect (new in 6.2)
│   └── mode-evaluate/SKILL.md      ← The Auditor
├── src/
│   └── <module>/CLAUDE.md          ← Optional nested module rules (new in 6.2)
├── docs/                           ← User-maintained reference docs
│   ├── api-contract.md
│   ├── design-system.md
│   └── DEVIATIONS.md
├── Concept.md                      ← Vision (persistent)
├── Architecture.md                 ← Layered design (persistent)
├── Plan.md                         ← Work order (ephemeral)
├── Evaluation.md                   ← Auditor output (ephemeral)
├── CHANGELOG.md                    ← History (persistent)
└── README.md
```

## Setup

### Prerequisites

- **Claude Code** or **Cursor** (or both)
- Claude Pro, Max, Teams, or Enterprise account
- Git initialized in your project

### Option A: Claude Code

Install Claude Code if you haven't:

```bash
# macOS / Linux
curl -fsSL https://claude.ai/install.sh | bash

# Windows (PowerShell)
irm https://claude.ai/install.ps1 | iex
```

Add the framework to your project:

```bash
mkdir my-project && cd my-project && git init
# Copy: CLAUDE.md, .claude/, skills/ into project root
```

Claude Code auto-loads `CLAUDE.md` on startup. Rule files in
`.claude/rules/` are read on-demand via the router. Nested `CLAUDE.md`
files auto-load when the agent works in their directory.

### Option B: Cursor

Cursor auto-loads `CLAUDE.md` as a workspace rule. Copy the same
files into your project:

```bash
mkdir my-project && cd my-project && git init
# Copy: CLAUDE.md, .claude/, skills/ into project root
```

### Both tools, same files

`CLAUDE.md` is the single entry point — the router for both Claude
Code and Cursor. No duplication. Switch tools mid-project freely;
git keeps everything in sync.

## Usage

### Building a New Project

**Planner session:**

```
You:     [/build] A FastAPI app that uploads PDFs, extracts text,
         and summarizes them with an LLM. React frontend.

Agent:   [Writes Concept.md, asks questions about stack and edge cases]

You:     proceed to spec

Agent:   [Runs environment audit: python ✓, uv ✓, node missing]
Agent:   [Writes layered Architecture.md, skills, Plan.md whose
          first ticket is "Environment Setup", CHANGELOG.md]
Agent:   "Planner session complete. Review the files. Place [Halt here]
          if needed. Type start execution when ready."
```

**Generator session:**

```
You:     start execution

Agent:   [Reads Architecture Overview only, then per-ticket sections]
Agent:   [Executes tickets, commits after each]
Agent:   "Generator session complete. Ready for your evaluation."
```

**Optional Evaluator session:**

```
You:     [/evaluate]

Agent:   [Runs the four audits: execution, consistency, simplicity,
          context]
Agent:   [Writes Evaluation.md with a verdict + prioritized fixes]
Agent:   "Evaluation complete. Verdict: PASS WITH ISSUES."
```

**You sign off.** Act on the verdict. If satisfied, delete Plan.md and
Evaluation.md.

### Modifying

```
You:     [/modify] Add batch upload with concurrent PDF processing

Agent:   [Reads Concept.md, Architecture sections, nested CLAUDE.md,
          docs/DEVIATIONS.md]
Agent:   "Warning: Current pipeline is synchronous. Batch processing
          needs async. Options: ..."

You:     proceed to spec

Agent:   [Audits new deps, updates Architecture surgically + Overview,
          writes fresh Plan.md]
```

### Debugging

```
You:     [/debug] Extraction returns empty text for scanned PDFs

Agent:   [Creates Triage.md with hypotheses, lists Architecture sections
          and reference docs each hypothesis touches]

You:     start execution
```

### Migrating an Existing Codebase

```
You:     [/migrate]

Agent:   [Reads codebase, runs environment audit, asks about vision
          and reference docs]

You:     proceed to spec

Agent:   [Writes Concept.md, layered Architecture.md (with Environment
          section), skills matching existing patterns. Sets up empty
          docs/DEVIATIONS.md. No code changes.]
```

### Merging Two Projects

```
You:     [/merge] Combine agent-v1/ and agent-v2/ into one project

Agent:   [Reverse-engineers Architecture-v1.md and Architecture-v2.md
          FIRST, writes Merge-Analysis.md (features, overlaps,
          conflicts), then asks which features/implementations win]

You:     proceed to spec

Agent:   [Writes unified Concept.md + Architecture.md, skills for the
          target conventions, Plan.md sequencing the integration with
          regression coverage]

You:     start execution
```

### Evaluating

```
You:     [/evaluate]

Agent:   [Audit 1: runs the test suite + app. Audit 2: Concept ↔
          Architecture ↔ docs ↔ code consistency. Audit 3: simplicity
          /redundancy. Audit 4: context sufficiency.]
Agent:   [Writes Evaluation.md with a verdict + prioritized fix list.]
Agent:   "Evaluation complete. Verdict: PASS WITH ISSUES."
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
- Upload 0-byte file; confirm clean error, no crash

**Architecture:** Overview, Data Models
**Skills to Load:** @skills/fastapi-backend/SKILL.md
**Reference Docs:** @docs/api-contract.md (Section: Documents)
**Process Logging:** Expensive
**Boundary:** src/pipeline/, tests/test_extractor.py
**Run Command:** uv run pytest tests/test_extractor.py -v
```

### Generator Retry Logic

When a ticket's tests fail after implementation:
1. Attempt to fix (try 1).
2. If still failing, attempt again (try 2).
3. If still failing, final attempt (try 3).
4. If still failing: commit progress with a WIP message and stop.

### `[Halt here]` Flags

The Planner does NOT place halt flags. You place them after reviewing
Plan.md, wherever you want the Generator to pause. The Generator
commits and stops on hitting one.

### Bespoke Skills & Nested CLAUDE.md

Planner-generated, project-specific files with:
- Canonical file structure
- Copy-paste code patterns with your actual types
- DO / DO NOT rules (binary, no judgment)
- Error handling contracts, testing conventions, exact commands

Nested `CLAUDE.md` files complement skills: they hold durable,
module-specific *rules* that auto-load by location (no code, no data).

### The Evaluation Model

**Layer 1 — TDD (automated):** Tests before code. Catches regressions.

**Layer 2 — Manual Verification:** Each ticket lists what to inspect.

**Layer 3 — Auditor (optional, `[/evaluate]`):** Independently runs the
output, cross-checks it against Concept/Architecture/docs, audits
simplicity and context sufficiency, and issues a verdict.

**Layer 4 — You:** Sign off. The full loop isn't done until you say so.

## Claude Code vs Cursor

| Concern | Claude Code | Cursor |
|---|---|---|
| Router loading | `CLAUDE.md` auto-loaded on startup | `CLAUDE.md` auto-loaded as workspace rule |
| Rule files | `.claude/rules/*.md` read on-demand | Read on-demand when referenced |
| Nested CLAUDE.md | Auto-loaded for the active directory | Auto-loaded for the active directory |
| Skill files | Read via `Read` tool when instructed | Read via `Read` tool when instructed |
| `@` references | Plain text (agent resolves) | File references (IDE resolves) |
| Mode commands | Typed in chat | Typed in chat |

## Version History

| Version | Key Change |
|---|---|
| 1.0–3.0 | Prompt-in, code-out. Context collapse. |
| 3.5 | Decoupled design from implementation. |
| 4.0 | 3-Phase Pipeline. Git, TDD, CHANGELOG. |
| 4.1 | Dynamic skill creation. |
| 4.2 | Programmable `[Halt here]` for context-aware chunking. |
| 5.0 | Strategy Pattern: personas via mode commands. |
| 5.1 | Two-Tier Bug Classification. |
| 5.2 | STATE.md, task tickets with Boundary, Blocked protocol. |
| 5.3 | Phase-based authority. Unified Planner/Generator pipeline. User as Evaluator. |
| 5.5 | Session-based development. Git as checkpoint system. Concept.md restored. STATE.md eliminated. Plan/Triage ephemeral. User-placed `[Halt here]` only. `[/migrate]` mode. 3-retry logic. |
| 5.6 | Dual-tool compatibility: Claude Code + Cursor. `CLAUDE.md` as unified router. |
| 6.0 | Layered Architecture.md with selective loading. Environment audit baked into Planner. Evaluator session via `[/evaluate]`. Reference docs in `docs/` with `DEVIATIONS.md`. |
| **6.2** | **Renamed to Concept-Driven Development (formerly Vibe Coding). `.claude/rules/` convention. Always-on principles (Simplicity, Surgical, Think). Nested `CLAUDE.md`. `[/merge]` Architecture-first mode. Evaluator redefined as independent Auditor. Opt-in process logging for expensive pipelines.** |

## Tips

- **Start small.** First project should be buildable in a day.
- **Keep the Architecture Overview tight.** It's the only section
  always loaded — anything that drifts here, drifts everywhere.
- **Keep nested `CLAUDE.md` to rules, not data.** API dumps and code
  the agent can read itself belong elsewhere.
- **Drop your contracts into `docs/` early.** API specs, design
  systems, SDK manuals. Reference them from tickets.
- **Use `[/evaluate]` when you're not the domain expert** or after a
  merge. The Auditor's verdict makes you a better evaluator.
- **Flag expensive pipelines** with `Process Logging: Expensive` so a
  failure leaves a debuggable trail instead of a costly re-run.
- **Review the environment audit.** Catching missing tools at the
  Planner stage saves a Generator stop later.
- **Read git logs.** `git log --oneline` is the progress trail.
- **Switch tools freely.** Planner in Cursor, Generator in Claude
  Code, or vice versa. Files are tool-agnostic.

## License

Open for personal and commercial use. Attribution appreciated.
