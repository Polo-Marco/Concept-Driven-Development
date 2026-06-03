---
name: skill-template
description: Standard for bespoke execution skills. The Planner reads this during Spec Phase to write skills the Generator can follow mechanically.
author: framework
version: 6.2
---

# Skill Template Standard (v6.2)

## Purpose

Skills are the interface between the Planner's intent and the Generator's
execution. Write every skill as if the reader is competent but literal —
it will follow instructions exactly and improvise dangerously when
instructions are missing.

## 1. Mandatory YAML Frontmatter

```yaml
---
name: [kebab-case-name]
description: [one-line purpose]
author: planner
project: [project name]
stack: [comma-separated tools]
version: [semver or date]
---
```

## 2. Six Mandatory Sections (In Order)

### Section 1: File Structure (Canonical)
Exact directory tree. Generator cannot create files outside it.
Use `←` arrows for annotations.

### Section 2: Patterns (Copy-Paste Templates)
Concrete code using the project's **actual types and names**.
Minimum 3 patterns: create, read/query, test.
Full import blocks. Complete functions. No pseudocode.

### Section 3: Hard Rules (DO / DO NOT)
Binary rules. Minimum 5 DO, 5 DO NOT. Specific and testable.

### Section 4: Error Handling Contract
Per-layer patterns for raising, catching, surfacing errors.
What NOT to catch.

### Section 5: Testing Contract
Framework, naming, minimum coverage, fixture patterns, run commands.

### Section 6: Environment & Commands
Every command the Generator needs. Copy-pasteable.

## 3. Quality Checklist

- [ ] No ambiguity: could a literal agent read any rule two ways?
- [ ] No missing imports: every pattern has full import blocks?
- [ ] Real names: patterns use actual project types?
- [ ] Boundary-safe: File Structure makes placement unambiguous?
- [ ] Error handling explicit: Generator knows what to raise/catch?
- [ ] Commands run verbatim?
- [ ] DO NOT list covers every common mistake?

## 4. Versioning

When the Planner revises a skill:
1. Increment `version` in frontmatter.
2. Add entry under `## Revision Log`.
3. Verify Patterns match updated Architecture.md sections.

Generator must NEVER modify skill files.

## 5. Architecture.md Coupling

Skills reference real types and endpoints from `Architecture.md`.
The document is layered — every skill should declare which sections
of Architecture it depends on, so the Planner knows which skills to
revise when a section changes.

When updating a skill because an Architecture section changed:
1. Update the affected Patterns and Hard Rules.
2. Re-read `Architecture.md ## Overview` and confirm the Overview
   still summarises the system accurately. If a section was added,
   removed, or substantially renamed, **update the Overview** so the
   Generator's first read still sees a faithful snapshot.
3. Bump the skill `version` and log the change in `## Revision Log`.

The Overview is the only Architecture section the Generator always
reads. Letting it drift defeats selective loading.
