# Inbox — Raw Idea Capture

Scraps, paper links, aha moments about where the framework should go.
No structure required — one line is fine. Promoted into `Concept.md` /
`docs/` during a `[/discuss]` session, then deleted from here.

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
