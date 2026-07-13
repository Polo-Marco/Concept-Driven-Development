# Feedback Inbox (personal)

Quick capture for framework feedback from daily use. Append entries at
the top. `[/retro] all` reads this file alongside imported project
retros. After an upgrade incorporates an entry, delete it (the retro
summary + commit preserve the history).

Entry format:

```
## YYYY-MM-DD — <project or context>
- What happened: [1–3 lines, factual]
- Framework angle: [which rule/skill/mode it implicates, if known]
- Severity: [annoyance | recurring | blocking]
```

---

## 2026-07-13 — (example, delete me)
- What happened: Generator read the full Architecture.md even though
  the ticket listed only Overview + Data Models.
- Framework angle: generator-protocol.md selective loading may need a
  harder rule or a self-check line in the ticket format.
- Severity: recurring
