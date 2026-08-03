# Framework Maintenance

**This file applies only in this repo — the CDD framework source.**
Deployed projects never copy it. This repo is two things at once:

1. **The template** — `CLAUDE.md`, `.claude/`, `skills/` are the files
   projects copy.
2. **A CDD project about itself** — the product is the framework, and
   feedback from real projects drives its upgrades.

## The Improvement Loop

```
capture      →   review        →   decide   →   apply           →   version + ship
(journal/)       ([/retro] all)    (user)       (Maintainer          (commit, tag,
                                                 session)             push)
```

### 1. Capture (continuous, zero ceremony)

Three inboxes, by input type:

| Input | Where |
|---|---|
| **Experience** — what worked / failed in real loops | `journal/` |
| **Ideas** — new capabilities, direction changes | `docs/inbox.md` |
| **Hotfixes** — template files patched in place in a deployed project | `journal/hotfixes/` |

- **Personal feedback:** append a dated entry to
  `journal/feedback-inbox.md` (format inside the file).
- **Project retros:** copy retro summaries — or whole loop journals
  with rich Feedback blocks — from any project into `journal/`,
  prefixed with the project name:

  ```bash
  cp ~/dev/ocrapp/journal/retro-20260712.md \
     journal/from-ocrapp-retro-20260712.md
  ```

- **Hotfixes: a live loop cannot wait for this repo.** When a project
  patches its own copy of `.claude/` or `skills/` to get unstuck, that
  fix exists ONLY there — it is code, not a journal entry, so nothing
  above captures it and the next deploy silently reintroduces the bug.
  Report it as a patch plus one line of why:

  ```bash
  cd ~/dev/ocrapp && git format-patch -1 <sha> \
     -o <framework-repo>/journal/hotfixes/
  ```

  Both v8.1.9 fixes were already live in a deployed project days before
  this repo heard about them, and only because a retro happened to
  mention the commit hashes in prose. Patching a project's template
  files is still not the fix (see *Upgrading a Deployed Project*) — it
  is the emergency, and this is how the emergency gets home.

### 2. Review — `[/retro] all`

Run `[/retro] all` in this repo. The Coach reads everything in
`journal/` — imported project retros, `feedback-inbox.md`, and any
patches in `hotfixes/` — looks
for cross-project patterns ("Boundary overreach flagged in 3 of 4
projects"), and writes recommendations to `journal/retro-YYYYMMDD.md`.

### 3–4. Decide + Apply — Maintainer session

When the user asks to apply accepted recommendations (or requests any
direct framework edit), the agent acts as the **Framework Maintainer**:

- Full write authority over ALL template files: `CLAUDE.md`,
  `.claude/rules/`, `skills/`, `README.md`. The project phase-authority
  matrix does NOT restrict maintenance sessions in this repo.
- Core Principles still bind: the smallest change that addresses the
  logged feedback, surgical edits, assumptions stated first.
- Every change must trace to a journal entry, an inbox item, or an
  explicit user request — cite it in the commit message.

### 5. Version + ship

- **Bump the version** everywhere it appears: README title + Version
  History row, `CLAUDE.md` header, and the `version:` frontmatter of
  any skill touched.
  - Patch (8.1.x): rule tightening, skill edits, doc clarifications,
    driver/hook fixes.
  - Major (x.0): new/removed modes, pipeline or file-structure changes.
- **Commit** with a detailed message (git is the changelog), citing the
  motivating feedback.
- **Tag the release:** `git tag v8.1.10` — so projects can diff tags to
  see exactly what to re-copy.
- **Housekeeping:** move processed journal files to `journal/archive/`;
  delete processed entries from `feedback-inbox.md` and
  `docs/inbox.md`.
- Push: `git push --follow-tags` (user runs or confirms).

## Upgrading a Deployed Project

```bash
cd <framework-repo>
git diff v8.1.9..v8.1.10 -- CLAUDE.md .claude/ skills/
# re-copy the changed files into the project, then commit there:
#   docs: upgrade CDD 8.1.9 → 8.1.10
```

Never patch template files inside a project — fix here, re-copy there.

## Meta vs Template Files

| Meta (this repo only, never copied) | Template (copied to projects) |
|---|---|
| `MAINTENANCE.md`, `Concept.md`, `journal/`, `docs/`, `.gitignore` | `CLAUDE.md`, `.claude/`, `skills/` |

`README.md` is both: the framework's public doc and this repo's README.

**`journal/` is gitignored HERE** (v8.1.9). In this repo the journal is
raw *input* to maintenance — imported project retros, personal
feedback, hotfix patches — not something the framework ships, and it
carries other projects' internal detail. It stays on the maintainer's
machine; what leaves this repo is the change it motivated, with the
journal file cited by name in the commit message and in the code
comment that traces to it.

This does NOT change the template rule: in a deployed project
`journal/*.md` is committed and persistent (`governance.md` §6) — it is
that project's own record, and `[/retro]` reads it there.
