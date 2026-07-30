# Inbox — Raw Idea Capture

Scraps, paper links, aha moments about where the framework should go.
No structure required — one line is fine. Promoted into `Concept.md` /
`docs/` during a `[/discuss]` session, then deleted from here.

---

## 2026-07-30 — The human interface: entry point, roadmap layer, supervising session

Discussion session (Cowork), after the retro fixes landed (`6e04bf3`,
`1ba8760`). Not yet promoted into `Concept.md` — capture only.

### The complaint that started it

"前置作業太複雜、loop driver 不直觀、還需要手動開啟手動 approve。我希望有
一個 orchestrator 可以 monitor 整個 looping process，然後幫我回應一些內容，
若有必要詢問的再 raise questions。"

Roughly half the retro's findings turned out to be interface failures
rather than logic errors: `driver.log` empty, the human-gate banner
invisible, `approve` a silent no-op, the gate carrying no information
for 83% of the loop. The state was correct throughout; nobody could see
it. **v8.1 removed the human from the middle of the loop, which made
every remaining contact point load-bearing — but none of them were
designed as such.**

### Observed cost of entry, measured

An end-to-end rehearsal (stub `claude`, throwaway project) required
eight manual steps:

1. create the worktree by hand (the driver prints the command, then
   refuses to proceed)
2. configure a git identity (nothing checks; a failed commit was silent
   until `1ba8760`)
3. start tmux and the `| tee logs/driver.log` pipeline
4. notice that the gate had opened
5. run `approve` **in a second shell**
6. wait up to 15s for the poll (now 2s)
7. nothing announces completion except the tmux pane
8. delete 11 leftover files

### What the user actually wants as the entry point

> 手動開啟一個 session，跟 Claude 說 `[/loop]`，Claude 就開始執行 loop。
> 不需要我開啟 driver，也不需要手動 `python run approve`。

**This is not a new component — it is the control tower promoted from
optional extra to default interface.** `loop-protocol.md` already
describes it: one interactive session in tmux with Remote Control on,
reading `events.jsonl` / `loop-state.json` to answer `status` and
writing the approval flag on your `approve`. It has never once been run
(confirmed with the user). Two of its failure causes — an invisible gate
banner and a silent `approve` — were only fixed on 2026-07-30.

**Naming collision to resolve before writing any of this down.** CDD
already has a `Monitor` role: the haiku session that classifies a trial
log tail and writes nothing. The thing described here is a different
animal at a different layer. Keep "Monitor" for the trial classifier and
"control tower" (or a new name) for the supervising session; do not let
the two share a word.

**Two candidate homes for the plumbing, and they are not exclusive:**

- **A — `loop.py start`:** a CLI subcommand that creates the worktree,
  launches under tmux, tees the log, and prints one line. Session
  independent, unit-testable, works headless and in CI.
- **B — the `[/loop]` skill:** the session does it conversationally.
  No new CLI surface, but only works while a session is alive.

Recommendation: **A, with B calling it.** Orchestration logic belongs in
code that can be tested, not in a prompt; the session should be a thin
conversational wrapper. This also keeps unattended operation possible.

**The hard 10%.** An interactive session only acts when messaged — it
cannot autonomously notice that a gate opened. So the wake-up mechanism
must remain driver-side push (`notify.sh`, today optional and unset).
The realistic loop is: driver pushes to the phone → user messages the
session → session reads the feed, summarises, and writes the flag on
instruction. The session is where you *respond*, not what wakes you.

**Honesty note on enforcement.** A supervising session must be
interactive to talk to you, and the PreToolUse hook deliberately exempts
interactive sessions (`if not role: sys.exit(0)`). So a session that can
write approval flags is, by construction, unrestricted. "May do
everything except decide" is therefore honour-system, enforced by the
skill's prompt, not by the hook. Mitigation worth considering: have
`approve` record in `events.jsonl` what was shown to the human before
the flag was written — auditable rather than enforced.

### The structural gap: there is no milestone layer

```
Concept.md      project vision — prose, for humans and the Planner
   │
   │   ← nothing lives here
   ▼
goal.json       one loop's contract — frozen, user-owned, machine-read
   │
   ▼
Plan.md         tickets
```

Nothing knows that a loop is milestone 3 of 7, or that milestone 4
depends on 3's output. **Continuity between loops is currently carried
in the user's head.** `ledger.jsonl` remembers within a loop, `journal/`
remembers process, but "why this milestone, what's next, did this result
make the next one impossible" has no home.

Note that `loop-protocol.md`'s scope guard already names the concept:
"Batch = sequential queue of goals; one loop at a time in v8.0." So this
is not a new layer — it is making batch persistent.

### Decisions reached

- **A milestone IS a goal.** One loop per milestone. Example: "run
  tmmluplus and write the report" is one milestone.
- **`roadmap.json` entries are thin:** id, one-line intent, depends-on,
  status. **Not** a pre-written goal contract — writing criteria for
  milestone 5 today is guessing, and earlier milestones change what
  should be measured. `[/loop]`'s Ask phase expands the one-liner into
  `goal.json` when the milestone is actually about to run.
- **The driver writes milestone status** (consistent with it owning
  `loop-state.json` and `ledger.jsonl`). Agents stay read-only on
  `roadmap.json`, same discipline as `goal.json`.
- **The supervising layer never starts the next loop.** The user checks
  each milestone's output before proceeding, specifically to avoid
  accumulating tech debt. Consequence: it takes no irreversible action
  at all, so **its authority profile is identical to the Monitor's** —
  reads everything, writes nothing, returns a report. The hook already
  implements and enforces that shape.
- **The close-out record does not block the next loop.** Nice to have,
  not a gate.
- **Cost is not a concern yet — just record token counts.** Do not build
  price-card conversion.

### The two reframes that did the most work

**1. It is not a monitor; it is a responder to three events.** Problems
and solutions only surface at loop end, REPLAN, and ESCALATE. During a
healthy loop every decision is local and already handled. So it wakes
1–5 times per loop, not continuously — an order of magnitude cheaper,
and nothing is lost. Two of those three events are already blocking
human gates, so it slots naturally into "prepare the gate" rather than
"replace the gate".

**2. Ask for a delta, never a verdict.** Do not ask "is this still on
track?" — it will answer yes, and a supervisor that gradually
rationalises drift will never report drift. Ask it to produce: *the
milestone said X, the loop delivered Y, here is what still does not
exist.* Deltas are checkable; verdicts are not. Same principle as
`check_criteria()` reading numbers instead of asking the Evaluator
whether the goal was met.

### Sharpest technical finding for the divergence check

"Did milestone 3 make milestone 4 harder" is almost always an
**architectural** question — a non-general interface, logic welded into
one adapter, a data format that cannot extend. Those live in
`Architecture.md`.

Note the correction: checking *code vs `Architecture.md`* is weak,
because the Planner writes `Architecture.md` inside the loop, so by loop
end it already describes what was built. The check that matters is
**diffing `Architecture.md` across loops** — where did the design move,
and does it still support the remaining milestones? Tech debt does not
accumulate because someone built something undocumented; it accumulates
because someone documented a decision that forecloses the future.

### On discipline that depends on remembering

The user intends to inspect every milestone before proceeding. The
evidence says otherwise: the five committed diffs went unread, the
journal Feedback block was left empty, and the framework has now flagged
unclosed loops four times.

The conclusion is **not** "be more disciplined" — it is that a ritual
which starts empty stays empty. If the close-out record is *auto-drafted*
from artifacts the driver already has (criteria results, commit range,
architecture delta, flagged uncertainties), the default state becomes
"written but unsigned" rather than "never written". The information is
captured even if nobody signs. That also dissolves the block/don't-block
question entirely — what matters is **who writes the first draft**, not
who enforces it.

This suggests the supervising layer's most valuable single output is not
a divergence alert but **a drafted milestone close-out for the user to
correct in one line.**

### Staging

- **Stage 0 — plumbing only, no new components.** `loop.py start`,
  human-readable `status`, `notify.sh` on by default, and actually run
  the control tower through one loop. The deliverable is *evidence*, not
  features.
- **Stage 1 — `Roadmap.md` + `roadmap.json`.** Files only, no new agent.
  Continuity moves from the user's head to disk.
- **Stage 2 — the supervising role**, event-driven, output is a delta
  plus a drafted close-out, never an action.

**Standing risk:** every one of these sits on a base the user has never
fully exercised. The control tower has never run, `notify.sh` has never
been configured, and the driver could not print to a log until
2026-07-30. If stage 0 removes 80% of the pain, stage 2's spec will look
very different from what we can imagine today.

### Still open

- Does `roadmap.json` need a status richer than done/not-done? Loop 1
  ended at "milestone 1, 5 of 6 tickets, resumable" — a boolean cannot
  express that, and that state is exactly what got lost.
- What wakes the supervising session when the user is not at a keyboard,
  beyond `notify.sh` push?

---

## 2026-07-30 — Loop-engineering literature review → v8.1 design

Sources: HuaShu/Osmani *Loop Engineering* (IEEE-format working note,
2026-06); `github.com/hardness1020/awesome-agent-architecture` (§11
error recovery, §20 observability); Youssef Hosni, "How to Create Loops
with Claude" (loop-readiness check + permission ladder).

**Where CDD stands against the paper's five moves.** It scores
verification, persistence and handoff strongly; discovery and
scheduling are absent. Decision: **keep them absent.** The paper
describes a *maintenance* loop (perpetual, discovery-driven, cron-fired,
no terminal state); `[/loop]` is a *goal* loop (finite contract,
terminates when criteria are met). The paper itself distinguishes these
— "one should not confuse /goal with /loop, which merely reruns on an
interval." Discovery is the Ask phase, deliberately human-held because
that is where judgment lives; the stop condition is goal satisfaction,
not a timer. Bolting cron onto `[/loop]` would be cargo-culting. Record
this so a future `[/retro]` does not "find the gap" and fix it.

**What did transfer (all shipped in v8.1):**

1. *Anything rule-bound never goes to a probabilistic model* (Stripe
   Minions). `goal.json` criteria were already metric+op+value+source —
   and `loop.py` never read them. Now `check_criteria()` does.
2. *The evaluator must act, not read* (Rajasekaran). The driver used to
   hand the Evaluator a `git diff`; it now requires executed evidence,
   and the agent def defaults to assume-broken.
3. *Cap before you ship.* Caps are circuit breakers, not accounting.
4. *Read a sample, always* — the only defence against comprehension rot,
   and it has no technical fix. Now in the driver's closing reminder.

**The contradiction this resolved.** feedback-inbox 2026-07-17 item #5
wanted `final-pass` cadence to cut tokens; the paper says verification
is the move least affordable to skip. v8.0's `final-pass` literally
auto-PASSed with zero checks — the Nodding Loop, config-enabled. v8.1
splits the two: deterministic gate every ticket (free), LLM audit at
final (expensive, rare). Both sources satisfied.

**Held back deliberately** (Simplicity First): connectors, discovery
skills, cloud scheduling, parallelism expansion, and the permission
ladder — the plan gate plus replan/escalate gates already are the
paper's "one door open", and grading autonomy into six levels is a
config surface with no current goal behind it.

**Open for a later `[/discuss]`:** the paper's structural fix for
prompt-cache thrash (feedback-inbox item #6) is moving the driver from
`claude -p` to the Agent SDK. Still an optimisation, not correctness —
but it is also the only way to get real per-call cost data feeding the
USD cap, so it is worth more than "annoyance" now that the cap is live.
