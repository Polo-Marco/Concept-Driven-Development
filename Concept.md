# Concept: Concept-Driven Development

> Meta note: this is the Concept for the framework itself — this repo
> is a CDD project whose product is CDD. Not part of the template.

## Why This Exists

AI coding agents fail in predictable ways (context collapse,
architectural hallucination, self-approval, spec drift, no process
memory). CDD counters them with a session-based pipeline, phase
authority, structured files as external memory, and git as changelog.

## Who It Serves

Mark — AI engineer, solo-driving multiple projects with Claude Code and
Cursor. The framework must stay operable by one person: low ceremony,
high leverage, no infrastructure beyond git + markdown.

## What It Is

A set of copyable template files (`CLAUDE.md`, `.claude/`, `skills/`)
that turn a coding agent into a disciplined pipeline: Discuss → Plan →
Generate → Evaluate → Retro, with the user as final evaluator. Since 8.0
a deterministic driver (`.claude/driver/loop.py`) can run that pipeline
unattended against a machine-checkable goal contract, so the user
approves one plan instead of typing every transition.

## Design Principles

1. **Simplicity First** — the framework itself must obey its own rule:
   prefer one sharp rule change over a new subsystem.
2. **Evidence over vibes** — upgrades trace to logged feedback
   (`journal/`), not feelings. See `MAINTENANCE.md`.
3. **Tool-agnostic core** — files work in Claude Code and Cursor;
   tool-specific extras (hooks) degrade gracefully.
4. **Authority by phase, not model** — who may write what is defined
   per session type.

## Scope

- In: pipeline modes, rules, ticket format, journal/retro loop,
  template docs, and the loop driver + its authority hook — the parts
  that let the pipeline run without a human in the middle.
- Out (for now): CI enforcement, multi-user workflows, non-git storage.
  Roadmap: federated subsystems for large monorepos (see README).

## Success Criteria

- Retros across projects show *decreasing* repeat findings
  version-over-version.
- A new project goes 0→1 with one `[/loop]` (`build` goal) and no
  framework friction.
- Every framework change cites the feedback that motivated it.
