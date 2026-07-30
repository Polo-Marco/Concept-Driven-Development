#!/usr/bin/env python3
"""CDD 8.1 loop driver — deterministic orchestrator (reference impl).

Design: docs/loop-orchestration-design.md. The driver is deliberately
dumb: it spawns fresh headless Claude sessions per phase, parses their
JSON artifacts, branches on verdicts, enforces budgets, and owns all
long-running processes and git commits. LLM intelligence lives inside
the sessions; control flow lives here, where it is auditable.

v8.1 adds four deterministic gates, on the principle that anything
rule-bound must never be handed to a probabilistic model:

  * machinery()      -- the loop's own parts are installed and wired
  * validate_goal()  -- the goal contract is well-formed
  * preflight()      -- environment preconditions, before any model call
  * check_criteria() -- goal.json criteria, read straight off disk

Usage:
    python3 .claude/driver/loop.py start      # worktree + tmux + go
    python3 .claude/driver/loop.py status     # what is happening now
    python3 .claude/driver/loop.py approve    # approve the pending gate
    python3 .claude/driver/loop.py check      # run gates only, then exit
    python3 .claude/driver/loop.py            # run in the foreground
    python3 .claude/driver/loop.py --here     # allow the primary worktree

`start` is the entry point: it creates the loop's worktree, launches the
driver under tmux and prints where to watch. Running loop.py bare is the
same driver in the foreground -- what `start` puts inside tmux.

Requires: goal.json (written by the [/loop] Ask phase), Claude Code
CLI on PATH, git. Python 3.9+, stdlib only.
"""
import json
import operator
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()
GOAL = ROOT / "goal.json"
STATE = ROOT / "loop-state.json"
LEDGER = ROOT / "ledger.jsonl"
EVENTS = ROOT / "events.jsonl"
VERDICT = ROOT / "verdict.json"
APPROVALS = ROOT / "approvals"
AGENTS = ROOT / ".claude" / "agents"
SETTINGS = ROOT / ".claude" / "settings.json"
NOTIFY = ROOT / ".claude" / "driver" / "notify.sh"  # optional plug-in

DEFAULT_MODELS = {"planner": "opus", "generator": "sonnet",
                  "evaluator": "opus", "monitor": "haiku"}

ROLES = ("planner", "generator", "evaluator", "monitor")

OPS = {">=": operator.ge, ">": operator.gt, "<=": operator.le,
       "<": operator.lt, "==": operator.eq, "!=": operator.ne}


# ---------- plumbing --------------------------------------------------

def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load(path: Path, default):
    """Read JSON. A corrupt file returns `default` -- callers that gate
    on the result MUST treat `default` as failure (fail-closed)."""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return default


def save(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2))


def event(kind: str, **kw) -> None:
    rec = {"ts": now(), "event": kind, **kw}
    with EVENTS.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    if NOTIFY.exists():                       # pluggable: ntfy/telegram
        subprocess.run(["bash", str(NOTIFY), kind, json.dumps(rec)],
                       check=False)
    print(f"[{rec['ts']}] {kind}: {kw.get('detail', '')}")


def sh(cmd: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, cwd=ROOT, text=True,
                          capture_output=True, **kw)


def git_commit(message: str) -> str:
    """Commit the whole tree. Returns the new short SHA, or "" if
    nothing was committed.

    v8.1.2: the result used to be unchecked. `sh()` captures output and
    ignores the return code, so a commit that FAILED -- no git identity
    configured, a refusing pre-commit hook, a locked index -- left HEAD
    where it was and this function returned the PREVIOUS sha. The driver
    then marked the ticket [x], logged ticket_done with a stale sha and
    moved on, reporting a loop whose work never entered git at all.

    Third instance of the class the trial exit code belongs to: assuming
    an external process succeeded because nobody asked it.
    """
    before = sh("git rev-parse HEAD").stdout.strip()
    sh("git add -A")
    r = sh(f"git commit -m {shlex.quote(message)}")
    after = sh("git rev-parse HEAD").stdout.strip()
    if not after or after == before:
        why = (r.stderr.strip() or r.stdout.strip()
               or "nothing changed").splitlines()[-1]
        event("commit_failed", detail=why[:200])
        return ""
    return sh("git rev-parse --short HEAD").stdout.strip()


def die(msg: str) -> None:
    """Abort loudly. Never degrade to a partial loop silently."""
    print(f"\n!! LOOP NOT STARTED\n{msg}\n", file=sys.stderr)
    sys.exit(1)


# ---------- gate 1: machinery (is the loop actually installed?) -------

def require_cli() -> None:
    """The `claude` CLI must exist AND be logged in.

    v8.1.2: this was the loop's most load-bearing external part and the
    only one nothing checked. An unauthenticated CLI does not error --
    every session returns a normal JSON envelope whose result is "Not
    logged in", so the Planner writes no Plan.md, the Evaluator has
    nothing to review, and the loop escalates with "plan failed contract
    review twice". Observed 2026-07-30: four no-op sessions, $0 spent,
    and the actual diagnosis nowhere in the log.

    `claude auth status` is free, so this costs nothing. It dies only on
    a POSITIVE "not logged in" -- an unparseable answer (a future format
    change) must not block a working loop, because the sessions
    themselves remain the real gate.
    """
    try:
        r = subprocess.run(["claude", "auth", "status"],
                           stdin=subprocess.DEVNULL, text=True,
                           capture_output=True, timeout=60)
    except FileNotFoundError:
        die("The `claude` CLI is not on PATH. The driver spawns every "
            "phase through it.")
    except subprocess.TimeoutExpired:
        return                      # slow, not broken -- do not block
    try:
        auth = json.loads(re.search(r"\{.*\}", r.stdout, re.S).group(0))
    except (AttributeError, TypeError, json.JSONDecodeError):
        return                      # unreadable -- do not block
    if auth.get("loggedIn") is False:
        die("The `claude` CLI is not logged in (`claude auth status` "
            "says loggedIn: false).\n"
            "  Every phase would return \"Not logged in\" and the loop "
            "would escalate with a\n"
            "  misleading reason. Run `claude auth login` first.")


def machinery() -> None:
    """Layer-A preflight: the loop's own parts.

    Motivated by journal/from-ccd-ai-bench-retro-20260715.md -- a project
    deployed with the v8.0 CLAUDE.md but no .claude/driver silently
    degraded to a manual 7.0 flow and reported itself as 8.0. A missing
    part must abort, never degrade.
    """
    required = [AGENTS / f"cdd-{r}.md" for r in ROLES] + [
        ROOT / ".claude" / "hooks" / "enforce_authority.py",
        ROOT / ".claude" / "rules" / "loop-protocol.md"]
    missing = [str(f.relative_to(ROOT)) for f in required
               if not f.exists()]
    if missing:
        die("Loop machinery is incomplete -- see v8.0-draft/INSTALL.md.\n"
            "  missing: " + ", ".join(missing))

    require_cli()

    if "enforce_authority.py" not in json.dumps(load(SETTINGS, {})):
        die("The PreToolUse hook is not wired in .claude/settings.json.\n"
            "  Without it, phase authority is prose, not enforcement --\n"
            "  every guarantee in .claude/rules/phase-authority.md is\n"
            "  honour-system only. Wire it before running unattended.")
    event("machinery_ok", detail=f"{len(ROLES)} agents + hook wired")


# ---------- gate 2: goal contract is well-formed ----------------------

def validate_goal(cfg: dict) -> None:
    """A loop with no machine-checkable criteria cannot know it is done.

    goal.json is a MACHINE MIRROR of Goal.md, written by the [/loop] Ask
    phase and audited by the Evaluator's contract review (Faithful?).
    The driver only checks that it is well-formed -- never what it means.
    """
    problems = []
    crit = cfg.get("criteria")
    if not isinstance(crit, list) or not crit:
        problems.append("criteria: must be a non-empty list -- a loop "
                        "without criteria can only guess when it is done")
    else:
        for i, c in enumerate(crit):
            where = f"criteria[{i}]"
            if not isinstance(c, dict):
                problems.append(f"{where}: must be an object")
                continue
            for k in ("metric", "op", "value", "source"):
                if k not in c:
                    problems.append(f"{where}: missing '{k}'")
            if c.get("op") not in OPS:
                problems.append(f"{where}: op {c.get('op')!r} not in "
                                f"{sorted(OPS)}")
    if not cfg.get("budgets"):
        problems.append("budgets: missing -- caps are circuit breakers, "
                        "not optional. Set them before running "
                        "unattended.")
    for c in cfg.get("preflight", []):
        if not isinstance(c, dict) or "run" not in c or "name" not in c:
            problems.append(f"preflight entry needs 'name' and 'run': {c}")
    if problems:
        die("goal.json is not a usable contract:\n  - "
            + "\n  - ".join(problems))


# ---------- gate 3: preflight (environment preconditions) -------------

def preflight(cfg: dict) -> None:
    """Layer-B preflight: what THIS goal needs before it can start.

    Each check is a shell command; exit 0 = pass. Runs on every driver
    start INCLUDING resume (.env goes stale, endpoints go down, Docker
    daemons die). Fail-closed: any failure aborts before a single model
    call is spent.

    SECRETS: only the check's name and exit code are logged. A check
    must not print credentials; the driver deliberately discards its
    stdout/stderr so a badly written check cannot leak a key into
    events.jsonl or logs/driver.log (governance.md section 2).
    """
    checks = cfg.get("preflight", [])
    if not checks:
        event("preflight_none",
              detail="Goal.md declared no preconditions")
        return
    failed = []
    for c in checks:
        rc = sh(c["run"]).returncode
        event("preflight",
              detail=f"{'ok  ' if rc == 0 else 'FAIL'} {c['name']}")
        if rc != 0:
            failed.append(f"{c['name']} (exit {rc}) -- {c['run']}")
    if failed:
        die("Preflight failed. Nothing was planned and nothing was "
            "spent.\n  - " + "\n  - ".join(failed)
            + "\n\n  Fix the environment, then start the driver again.")


# ---------- gate 4: the success criteria themselves -------------------

def check_criteria(cfg: dict):
    """Read every criterion straight off disk. No model involved.

    Returns (all_ok, results). Fail-closed: a missing source file, an
    unparseable file, or an absent metric is a FAILURE, never a pass.

    This is necessary but NOT sufficient: it proves the number met the
    threshold, not that the number was earned. Provenance (was this
    metric actually produced by the harness, or hand-written?) remains
    the Evaluator's job. Keep both.
    """
    results = []
    for c in cfg.get("criteria", []):
        rec = {"metric": c["metric"], "op": c["op"], "value": c["value"],
               "source": c["source"], "actual": None, "ok": False,
               "why": ""}
        src = ROOT / c["source"]
        if not src.exists():
            rec["why"] = "source file does not exist"
            results.append(rec)
            continue
        data = load(src, None)
        if data is None:
            rec["why"] = "source file is not readable JSON"
            results.append(rec)
            continue
        actual = None
        if isinstance(data, dict):
            actual = data.get("metrics", {}).get(c["metric"]) \
                if isinstance(data.get("metrics"), dict) else None
            if actual is None:
                actual = data.get(c["metric"])
        rec["actual"] = actual
        if actual is None:
            rec["why"] = f"metric '{c['metric']}' not in {c['source']}"
        else:
            try:
                rec["ok"] = bool(OPS[c["op"]](actual, c["value"]))
                if not rec["ok"]:
                    rec["why"] = "threshold not met"
            except TypeError:
                rec["why"] = (f"cannot compare {actual!r} "
                              f"{c['op']} {c['value']!r}")
        results.append(rec)
    return (bool(results) and all(r["ok"] for r in results)), results


def criteria_line(r: dict) -> str:
    return (f"{'ok  ' if r['ok'] else 'FAIL'} {r['metric']} {r['op']} "
            f"{r['value']} (actual={r['actual']}"
            + (f"; {r['why']}" if r["why"] else "") + ")")


def slug(cfg: dict) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", cfg.get("goal", "loop").lower())
    return s[:40].strip("-") or "loop"


def notify_gap() -> str:
    """Empty when push is configured; a warning when it is not."""
    if NOTIFY.exists():
        return ""
    return ("no push configured -- copy .claude/driver/notify.sh.example "
            "to notify.sh, or nothing will tell you a gate opened")


# ---------- isolation --------------------------------------------------

def in_linked_worktree() -> bool:
    """True when this tree is a linked worktree rather than the primary
    checkout. Shared by require_isolation, `start` and `check`."""
    common = sh("git rev-parse --git-common-dir").stdout.strip()
    gitdir = sh("git rev-parse --git-dir").stdout.strip()
    return bool(common and gitdir and common != gitdir)


def require_isolation(cfg: dict, allow_here: bool) -> None:
    """Refuse to drive the primary working tree.

    The driver commits with `git add -A`, so anything loose in the tree
    joins the loop's history. A linked worktree contains that. This
    gate DETECTS rather than creates: an untested re-exec inside the
    process that owns every commit is the wrong place to be clever.
    """
    if allow_here or os.environ.get("CDD_ALLOW_PRIMARY"):
        event("isolation_waived", detail="running in the primary tree")
        return
    if in_linked_worktree():
        event("isolation_ok", detail="linked worktree")
        return
    die(f"Refusing to run in the primary working tree.\n"
        f"  The driver commits with `git add -A`; a loop belongs in its\n"
        f"  own worktree so a runaway cannot touch your main checkout.\n\n"
        f"  python3 .claude/driver/loop.py start\n\n"
        f"  (that creates ../{ROOT.name}-loop on branch "
        f"loop/{slug(cfg)} and starts the driver there)\n\n"
        f"  Override (not recommended): loop.py --here")


# ---------- claude sessions -------------------------------------------

def claude(st: dict, role: str, prompt: str, boundary: str = "",
           timeout: int = 7200) -> str:
    """Spawn one fresh headless session with hook-enforced authority.

    Bills the session onto the CALLER'S state dict.

    v8.1.1: this used to `load(STATE)` a private copy, add the cost and
    save it. Every phase function then saved the dict `main()` loaded at
    startup, wiping that write -- so `spent_usd` was reset toward zero
    at each phase boundary and `max_usd` was compared against a number
    that never accumulated (metered since 8.0, enforced in 8.1, correct
    in neither). The fix is ONE in-memory dict rather than a smarter
    merge: with a single writer, `save(STATE, st)` from anywhere is
    consistent and no field needs special monotonic semantics.
    """
    cfg = load(GOAL, {})
    model = cfg.get("models", {}).get(role, DEFAULT_MODELS[role])
    sys_prompt = (AGENTS / f"cdd-{role}.md").read_text()
    env = {**os.environ, "CDD_ROLE": role, "CDD_BOUNDARY": boundary}
    cmd = ["claude", "-p", prompt, "--model", model,
           "--append-system-prompt", sys_prompt,
           "--output-format", "json",
           "--dangerously-skip-permissions"]  # hook = enforcement layer
    # v8.1.2c: the only thing worse than a slow phase is a phase you
    # cannot see. Nothing was emitted between loop_start and the human
    # gate, so `status` looked identical whether the Planner was
    # thinking or the driver was dead. One line per session is the
    # cheapest heartbeat there is.
    event("session", detail=f"{role} ({model}) started")
    r = subprocess.run(cmd, cwd=ROOT, env=env, text=True,
                       capture_output=True, timeout=timeout)
    try:
        out = json.loads(r.stdout)
    except (json.JSONDecodeError, AttributeError):
        return r.stdout
    st["spent_usd"] = round(st.get("spent_usd", 0.0)
                            + out.get("total_cost_usd", 0.0), 4)
    save(STATE, st)          # safe now: the same dict every caller holds
    return out.get("result", "")


# ---------- plan parsing (dumb, format-bound) --------------------------

TICKET = re.compile(r"^### (Phase \d+, Step \d+)( \[x\])?: (.+)$", re.M)


def tickets(plan_text: str):
    """Yield (id, title, body, done) for each ticket, in order.

    v8.1.2: the driver marks a finished ticket by rewriting its heading
    to `### Phase 1, Step 2 [x]: ...`, which the old pattern could not
    match -- so a completed ticket vanished from this function entirely
    and `done` was never True for one. phase_iterate still terminated,
    because "unparseable" and "done" happen to coincide, but it was
    right by accident: anything that reads a plan for PROGRESS (a status
    view, a close-out summary) saw a truncated list, and on a finished
    plan saw nothing at all. The marker is now part of the grammar.
    """
    heads = list(TICKET.finditer(plan_text))
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(plan_text)
        body = plan_text[m.start():end]
        done = bool(m.group(2)) or bool(re.search(r"^- \[x\]", body, re.M))
        yield m.group(1), m.group(3), body, done


def field(body: str, name: str) -> str:
    """Value of one `**Name:**` ticket field, multi-line included.

    v8.1.1: the old pattern was `(.+)$` under re.M -- it took the first
    physical line and silently dropped the rest, quietly disarming any
    multi-line Monitor Profile. The value now runs to the next
    `**Field:**` or ticket heading.
    """
    m = re.search(rf"^\*\*{name}:\*\*[ \t]*(.*?)(?=^\*\*[A-Z]|^###|\Z)",
                  body, re.M | re.S)
    return m.group(1).strip() if m else ""


# ---------- budgets ----------------------------------------------------

def budget_exceeded(st: dict, cfg: dict) -> str:
    b = cfg.get("budgets", {})
    if st.get("iteration", 0) >= b.get("max_iterations", 20):
        return "max_iterations"
    if st.get("replans", 0) > b.get("max_replans", 3):
        return "max_replans"
    hours = (time.time() - st.get("started_epoch", time.time())) / 3600
    if hours >= b.get("max_wall_hours", 48):
        return "max_wall_hours"
    if st.get("gpu_hours", 0.0) >= b.get("max_gpu_hours", 1e9):
        return "max_gpu_hours"
    # v8.1: spend was metered since 8.0 but never enforced.
    if st.get("spent_usd", 0.0) >= b.get("max_usd", 1e9):
        return "max_usd"
    return ""


# ---------- gates ------------------------------------------------------

def wait_approval(st: dict, name: str, detail: str) -> None:
    """Block until the named gate is approved.

    v8.1.1: publishes WHICH gate is pending, so `approve` can target it
    and a premature `approve` can be told that nothing is waiting.
    """
    APPROVALS.mkdir(exist_ok=True)
    flag = APPROVALS / f"{name}.approved"
    if flag.exists():
        flag.unlink()
    st["pending_gate"] = name
    save(STATE, st)
    event("approval_request", gate=name, detail=detail)
    gap = notify_gap()
    print(f"\n== HUMAN GATE [{name}] ==\n{detail}\n"
          f"Approve via: control-tower session / phone (writes "
          f"{flag.relative_to(ROOT)}), or:\n"
          f"  python3 .claude/driver/loop.py approve\n"
          + (f"!! {gap}\n" if gap else ""))
    while not flag.exists():
        time.sleep(2)          # v8.1.2: 15s made a phone approve feel
                               # broken; this is a stat() call
    flag.unlink()
    st["pending_gate"] = None
    save(STATE, st)
    event("approved", gate=name)


# ---------- trials (experiment goals) ----------------------------------

def run_trial(tid: str, body: str, st: dict, cfg: dict) -> bool:
    """Launch the trial command; poll with Monitor; True if it SUCCEEDED.

    Returns False whenever the trial did not run to completion, so the
    caller never scores partial metrics. (v8.0 returned True after a
    crash-class kill and let the Evaluator grade a truncated run.)

    v8.1.1: ALSO False on a non-zero exit code. v8.1 covered only the
    exits the DRIVER causes -- budget kill, Monitor kill -- and still
    reported any self-inflicted death as completion. Consequences: a
    trial that died faster than one Monitor poll interval was invisible
    to both guards, and whatever stale artifact happened to be on disk
    was graded as its output. A non-zero exit is a RULE, and rules are
    decided here, not by a model (loop-protocol.md section 6).
    """
    trial_cmd = field(body, "Trial")
    if not trial_cmd:
        return True                       # build ticket: no trial phase
    interval = 60 * int(cfg.get("monitor", {}).get("interval_min", 10))
    log = ROOT / "logs" / f"trial-{st['iteration']}.log"
    log.parent.mkdir(exist_ok=True)
    trial_start = time.time()             # v8.1: never reset by polling
    last_poll = trial_start
    billed = [0.0]

    def bill() -> None:
        """Charge elapsed trial wall-clock once, idempotently."""
        elapsed = (time.time() - trial_start) / 3600
        delta = max(0.0, elapsed - billed[0])
        billed[0] = elapsed
        st["gpu_hours"] = round(st.get("gpu_hours", 0.0) + delta, 3)
        save(STATE, st)

    with log.open("w") as lf:
        proc = subprocess.Popen(trial_cmd, shell=True, cwd=ROOT,
                                stdout=lf, stderr=subprocess.STDOUT)
        interventions = 0
        while proc.poll() is None:
            time.sleep(min(interval, 60))
            if time.time() - last_poll < interval:
                continue
            last_poll = time.time()
            # v8.1: bill as we go so a cap can trip DURING a long trial,
            # not only after it ends.
            bill()
            if budget_exceeded(st, cfg) in ("max_gpu_hours",
                                            "max_wall_hours"):
                proc.kill()
                event("escalate", detail="budget exhausted during trial")
                return False
            tail = "\n".join(log.read_text(errors="ignore")
                             .splitlines()[-100:])
            rep = claude(st, "monitor",
                         f"Monitor Profile:\n"
                         f"{field(body, 'Monitor Profile')}\n\n"
                         f"Trial log tail:\n{tail}\n\nClassify per your "
                         f"instructions. Output ONLY the JSON.")
            m = re.search(r"\{.*\}", rep, re.S)
            status = (json.loads(m.group(0)) if m
                      else {"status": "HEALTHY"})
            event("monitor", detail=status.get("status"),
                  signature=status.get("signature"))
            if status["status"] == "KILL_ESCALATE":
                proc.kill()
                bill()
                event("escalate", detail="monitor: "
                      + status.get("evidence", ""))
                return False
            if status["status"] == "INTERVENE":
                interventions += 1
                proc.kill()
                bill()
                st["last_intervention"] = status
                save(STATE, st)
                if interventions > 2:
                    event("escalate", detail="repeated interventions")
                else:
                    event("trial_killed", detail="crash-class: "
                          + str(status.get("signature", "")) + " -- RETRY")
                # v8.1: a killed trial is NOT an evaluable trial.
                return False
    bill()
    if proc.returncode != 0:
        event("trial_failed",
              detail=f"trial exited {proc.returncode} -- see "
                     f"{log.relative_to(ROOT)}")
        return False
    return True


# ---------- phases ------------------------------------------------------

def phase_plan(cfg: dict, st: dict, replan_reason: str = "") -> None:
    ledger = LEDGER.read_text() if LEDGER.exists() else "(empty)"
    ev = (ROOT / "Evaluation.md")
    prompt = (
        f"Read Goal.md and plan per your instructions and the mode "
        f"skill for goal type '{cfg.get('type', 'modify')}'.\n"
        f"Trial ledger so far:\n{ledger}\n"
        + (f"\nThis is a REPLAN. Latest Evaluation.md:\n"
           f"{ev.read_text()}\nReason: {replan_reason}\n" if replan_reason
           else ""))
    claude(st, "planner", prompt)
    plan = ROOT / "Plan.md"
    event("planned", detail=(
        f"{sum(1 for _ in tickets(plan.read_text()))} tickets"
        if plan.exists() else "NO Plan.md was written"))
    st["phase"] = "contract_review"
    save(STATE, st)


def phase_contract_review(cfg: dict, st: dict) -> None:
    for round_ in range(2):
        if VERDICT.exists():
            VERDICT.unlink()          # never read a stale verdict
        claude(st, "evaluator",
               "Mode 1 -- contract review. Read Plan.md, Goal.md, "
               "goal.json, and the Architecture Overview. Audit per "
               "your instructions; write Evaluation.md and verdict.json.")
        # v8.1: fail-CLOSED. A missing or corrupt verdict from a safety
        # pre-gate used to default to "OK", which silently passed the
        # gate whenever the Evaluator crashed or wrote bad JSON.
        v = load(VERDICT, {}).get("verdict")
        if v == "OK":
            event("contract_ok", detail="plan matches the goal contract")
            st["phase"] = "gate"
            save(STATE, st)
            return
        if v is None:
            event("contract_review_unreadable",
                  detail="no usable verdict.json -- treating as REVISE")
        event("contract_revise", detail=f"round {round_ + 1}")
        claude(st, "planner", "Contract review returned REVISE. Read "
               "Evaluation.md and revise Plan.md accordingly.")
    event("escalate", detail="plan failed contract review twice")
    sys.exit(1)


def phase_iterate(cfg: dict, st: dict) -> None:
    while True:
        reason = budget_exceeded(st, cfg)
        if reason:
            event("escalate", detail=f"budget exhausted: {reason}")
            return
        plan = (ROOT / "Plan.md")
        todo = [(i, t, b) for i, t, b, done in tickets(plan.read_text())
                if not done]
        if not todo:
            event("all_tickets_done")
            st["phase"] = "final_eval"
            save(STATE, st)
            return
        tid, title, body = todo[0]
        st["iteration"] += 1
        st["current_ticket"] = tid
        save(STATE, st)
        event("iteration", detail=f"{tid}: {title}", n=st["iteration"])

        verdict, v = "ESCALATE", {"reason": "no attempt completed"}
        for attempt in range(1, 4):                       # RETRY <= 3
            rep = claude(st, "generator",
                         f"Execute this ticket per your instructions:\n\n"
                         f"{body}\n\nTicket log: logs/trial-"
                         f"{st['iteration']}.log", field(body, "Boundary"))
            if "STATUS: stopped" in rep:
                event("escalate", detail=f"{tid} generator stopped: "
                      + rep[-400:])
                return
            trial_ok = run_trial(tid, body, st, cfg)

            # ---- deterministic criteria gate (free; every iteration) --
            _, crit = check_criteria(cfg)
            prev_green = set(st.get("criteria_green", []))
            now_green = {r["metric"] for r in crit if r["ok"]}
            regressed = sorted(prev_green - now_green)
            st["criteria_green"] = sorted(now_green)
            save(STATE, st)
            for r in crit:
                event("criterion", detail=criteria_line(r))

            if not trial_ok:
                v = {"verdict": "RETRY",
                     "reason": "trial did not complete "
                               "(see events.jsonl / monitor)",
                     "evidence": [criteria_line(r) for r in crit]}
            elif regressed:
                # A criterion that was green went red. No model opinion
                # required -- that is a regression, full stop.
                v = {"verdict": "RETRY",
                     "reason": "criteria regression: "
                               + ", ".join(regressed),
                     "evidence": [criteria_line(r) for r in crit
                                  if r["metric"] in regressed]}
                event("regression", detail=", ".join(regressed))
            else:
                cadence = cfg.get("evaluation_cadence", "per-iteration")
                if cadence == "final-pass" and len(todo) > 1:
                    # v8.1: "deferred" no longer means unchecked. The
                    # deterministic gate above ran, the Generator's own
                    # TDD ran, and a regression would have blocked here.
                    v = {"verdict": "PASS",
                         "reason": "deterministic gate clean; LLM audit "
                                   "deferred to final pass",
                         "evidence": [criteria_line(r) for r in crit]}
                else:
                    if VERDICT.exists():
                        VERDICT.unlink()      # no stale verdicts
                    claude(st, "evaluator",
                           "Mode 2 -- evaluation. Audit the latest work "
                           f"for ticket '{tid}' against Plan.md and "
                           "Goal.md per your instructions. The diff is "
                           "`git diff HEAD`. You MUST execute, not just "
                           "read: run the tests and the Run Command and "
                           "paste their real output as evidence. Write "
                           "Evaluation.md and verdict.json.")
                    v = load(VERDICT, {"verdict": "ESCALATE",
                                       "reason": "missing verdict.json"})
            LEDGER.open("a").write(json.dumps(
                {"ts": now(), "iteration": st["iteration"], "ticket": tid,
                 "attempt": attempt, "verdict": v.get("verdict"),
                 "reason": v.get("reason"),
                 "evidence": v.get("evidence", []),
                 "criteria": crit}) + "\n")

            verdict = v.get("verdict")
            if verdict == "RETRY" and attempt < 3:
                event("retry", detail=f"{tid} attempt {attempt}: "
                      + str(v.get("reason", "")))
                continue
            break

        if verdict == "PASS":
            unmarked = plan.read_text()
            plan.write_text(unmarked.replace(
                f"### {tid}:", f"### {tid} [x]:", 1))
            sha = git_commit(
                f"feat(loop): {tid} {title}\n\n"
                f"verdict: PASS -- {v.get('reason', '')}\n"
                f"evidence: {v.get('evidence', [])}\n"
                f"iteration {st['iteration']}; see ledger.jsonl")
            if not sha:
                # v8.1.2: a PASS whose work never reached git is not a
                # PASS. Leave the ticket runnable and stop.
                plan.write_text(unmarked)
                event("escalate", detail=f"{tid} verdict PASS but nothing "
                      "was committed -- see commit_failed")
                return
            event("ticket_done", detail=f"{tid} @ {sha}")
        elif verdict == "REPLAN":
            st["replans"] = st.get("replans", 0) + 1
            git_commit(f"wip(loop): {tid} before replan "
                       f"#{st['replans']} -- {v.get('reason', '')}")
            st["phase"] = "plan"
            save(STATE, st)
            phase_plan(cfg, st, v.get("reason", ""))
            phase_contract_review(cfg, st)
            wait_approval(st, "replan", f"Replan #{st['replans']}: "
                          + str(v.get("reason", "")))
            st["phase"] = "iterate"
            save(STATE, st)
        else:                                             # ESCALATE/fail
            git_commit(f"wip(loop): {tid} stopped -- "
                       f"{v.get('reason', 'failed after 3 attempts')}")
            event("escalate", detail=f"{tid}: {v.get('reason', '')}")
            return


def phase_final(cfg: dict, st: dict) -> None:
    """Deterministic gate first, LLM provenance audit second.

    Order matters: if the numbers are not on disk there is nothing for
    an Evaluator to have an opinion about, and no reason to pay for one.
    """
    ok, crit = check_criteria(cfg)
    for r in crit:
        event("criterion", detail=criteria_line(r))
    if not ok:
        event("escalate", detail="final criteria gate failed: "
              + "; ".join(criteria_line(r) for r in crit if not r["ok"]))
        save(STATE, st)
        return

    if VERDICT.exists():
        VERDICT.unlink()
    claude(st, "evaluator",
           "Mode 2 -- FINAL evaluation of the whole loop. The "
           "deterministic criteria gate already PASSED, so do not "
           "re-check thresholds: audit PROVENANCE instead. Was each "
           "metric actually produced by the harness it claims, or could "
           "it have been hand-written? Do harness versions, sample "
           "counts and configs corroborate it? Any secret leaked into "
           "results or logs? Anything in the history the plan never "
           "asked for? Execute to verify. Write Evaluation.md and "
           "verdict.json.")
    v = load(VERDICT, {})
    if v.get("verdict") == "PASS":
        event("goal_reached", detail=v.get("reason", ""),
              evidence=v.get("evidence", []))
        st["phase"] = "done"
    else:
        event("escalate", detail="final eval: "
              + v.get("reason", "no usable verdict.json"))
    save(STATE, st)


# ---------- where the loop actually lives ------------------------------

def rebind(root: Path) -> None:
    """Point the module's paths at `root`."""
    global ROOT, GOAL, STATE, LEDGER, EVENTS, VERDICT, APPROVALS
    ROOT, GOAL = root, root / "goal.json"
    STATE, LEDGER = root / "loop-state.json", root / "ledger.jsonl"
    EVENTS, VERDICT = root / "events.jsonl", root / "verdict.json"
    APPROVALS = root / "approvals"


def find_loop() -> Path:
    """Resolve which tree holds the running loop, for status/approve.

    v8.1.2c: `start` runs in the PRIMARY tree but the loop runs in a
    worktree, so `status` and `approve` typed where you just ran `start`
    found no state. status said "Nothing has run in this tree yet" while
    a driver was running ten metres away, and approve would have written
    its flag into a tree nobody was watching -- a silent no-op, which is
    the failure mode this release keeps deleting. Resolve it rather than
    expecting the user to track which tree they are in.
    """
    if STATE.exists():
        return ROOT
    lines = sh("git worktree list --porcelain").stdout.splitlines()
    found = [Path(ln.split(" ", 1)[1]) for ln in lines
             if ln.startswith("worktree ")]
    found = [w for w in found
             if w != ROOT and (w / "loop-state.json").exists()]
    if len(found) > 1:
        die("More than one worktree has a loop running:\n  "
            + "\n  ".join(str(w) for w in found)
            + "\n\n  cd into the one you mean.")
    return found[0] if found else ROOT


# ---------- start: worktree + tmux + go --------------------------------

def phase_start(cfg: dict, allow_here: bool) -> None:
    """Create the loop's worktree, launch the driver under tmux, print
    one line saying where it went.

    v8.1.2. Starting a loop used to be six manual steps across two
    terminals -- create the worktree from a command the driver printed
    and then refused to run, cd, start tmux, remember the `| tee`, and
    keep a second shell around for `approve`. Every one of them was
    mechanical, and none of them needed a human.

    Deliberately SPAWNS rather than re-execs. `require_isolation()`
    refuses to relocate the process that owns every commit, and that
    judgement stands: this creates the worktree and starts a SEPARATE
    driver inside it.
    """
    # v8.1.2b: preflight BEFORE creating anything. `start` used to skip
    # it entirely (it is handled ahead of the gates in main()), so a
    # failing environment still got a worktree, a branch and a tmux
    # session, and printed "Loop started" for a driver that was already
    # dying inside tmux where nobody could see it. Observed on the first
    # real run: `check` said FAIL, `start` said started.
    preflight(cfg)

    if allow_here:
        target = ROOT
    else:
        if in_linked_worktree():
            target = ROOT                       # already in a worktree
        else:
            target = ROOT.parent / f"{ROOT.name}-loop"
            branch = f"loop/{slug(cfg)}"
            if not target.exists():
                r = sh(f"git worktree add {shlex.quote(str(target))} "
                       f"-b {shlex.quote(branch)}")
                if r.returncode != 0:
                    die("Could not create the loop worktree:\n  "
                        + (r.stderr.strip() or r.stdout.strip()))
                event("worktree_created", detail=f"{target} on {branch}")
            # Goal.md/goal.json are user-owned and typically uncommitted,
            # so the worktree checkout does not have them yet.
            for f in ("Goal.md", "goal.json"):
                src = ROOT / f
                if src.exists():
                    (target / f).write_text(src.read_text())

    if not (target / ".claude" / "driver" / "loop.py").exists():
        die(f"{target} has no .claude/driver/loop.py -- the branch it "
            f"checked out predates the loop machinery. Commit .claude/ "
            f"first.")
    (target / "logs").mkdir(exist_ok=True)

    name = ("cdd-" + slug(cfg))[:28].rstrip("-")
    if sh(f"tmux has-session -t {shlex.quote(name)}").returncode == 0:
        die(f"tmux session '{name}' already exists -- a driver for this "
            f"goal is already running.\n"
            f"  watch:   tmux attach -t {name}\n"
            f"  status:  python3 .claude/driver/loop.py status")
    if sh("command -v tmux").returncode != 0:
        die("tmux is not installed. Either install it, or run the driver "
            "in the foreground:\n"
            f"  cd {target} && python3 .claude/driver/loop.py "
            "2>&1 | tee logs/driver.log")

    flag = " --here" if allow_here else ""
    inner = (f"cd {shlex.quote(str(target))} && "
             f"CLAUDE_PROJECT_DIR={shlex.quote(str(target))} "
             f"python3 .claude/driver/loop.py{flag} "
             f"2>&1 | tee logs/driver.log")
    r = subprocess.run(["tmux", "new-session", "-d", "-s", name, inner],
                       text=True, capture_output=True)
    if r.returncode != 0:
        die("tmux refused to start the driver:\n  "
            + (r.stderr.strip() or r.stdout.strip()))

    # The driver runs its own gates in the worktree and dies loudly if
    # one fails -- but tmux destroys the session with the process, so
    # the message would vanish. Wait, then report what really happened.
    time.sleep(3)
    if sh(f"tmux has-session -t {shlex.quote(name)}").returncode != 0:
        log = target / "logs" / "driver.log"
        tail = "\n  ".join(log.read_text(errors="ignore").splitlines()[-12:]
                           ) if log.exists() else "(no driver.log)"
        die(f"The driver exited immediately. Its last output:\n\n  {tail}")

    gap = notify_gap()
    print(f"\nLoop started in tmux session '{name}'.\n"
          f"  worktree  {target}\n"
          f"  log       {target}/logs/driver.log\n"
          f"  watch     tmux attach -t {name}   (detach: Ctrl-b d)\n"
          f"  plan      {target}/Plan.md\n"
          f"  status    python3 .claude/driver/loop.py status\n"
          f"  approve   python3 .claude/driver/loop.py approve\n"
          f"            (both work from here or from the worktree)\n"
          + (f"\n  !! {gap}\n" if gap else ""))


# ---------- status: for a human ----------------------------------------

def phase_status(cfg: dict) -> None:
    """What is happening, in the order a human asks it.

    v8.1.2: this used to dump loop-state.json raw, which answers none of
    the four questions you actually have -- where is it, is it stuck, how
    much has it burned, does it need me?
    """
    st = load(STATE, {})
    if not st:
        print("No loop state. Nothing has run in this tree yet.")
        return
    b = cfg.get("budgets", {})
    hours = (time.time() - st.get("started_epoch", time.time())) / 3600
    out = [f"goal      {cfg.get('goal', '(no goal.json here)')}",
           f"phase     {st.get('phase', '?')}"
           + (f"   ticket {st['current_ticket']}"
              if st.get("current_ticket") else ""),
           f"started   {st.get('started', '?')}  (elapsed {hours:.1f}h)"]

    # "is it working, or is it dead" is the first question anyone asks,
    # and until v8.1.2c nothing answered it: a thinking phase and a
    # crashed driver rendered identically.
    name = ("cdd-" + slug(cfg))[:28].rstrip("-") if cfg.get("goal") else ""
    alive = bool(name) and sh(
        f"tmux has-session -t {shlex.quote(name)}").returncode == 0
    idle = ((time.time() - EVENTS.stat().st_mtime) / 60
            if EVENTS.exists() else None)
    out.append(
        "driver    "
        + (f"running (tmux {name})" if alive
           else "no tmux session -- finished, or run in the foreground")
        + (f"  ·  last event {idle:.0f}m ago" if idle is not None else ""))

    plan = ROOT / "Plan.md"
    if plan.exists():
        rows = [f"  [{'x' if d else ' '}] {i}  {t}"
                for i, t, _, d in tickets(plan.read_text())]
        if rows:
            done = sum(1 for r in rows if r.startswith("  [x]"))
            out += ["", f"tickets   {done}/{len(rows)} done"] + rows

    if cfg.get("criteria"):
        _, crit = check_criteria(cfg)
        out += ["", "criteria"] + [f"  {criteria_line(r)}" for r in crit]

    def cap(v, k, fmt="{:.0f}"):
        """`used / limit`, both in the same unit -- the unit lives in
        `fmt` so an absent limit renders as a bare "-"."""
        lim = b.get(k)
        return (fmt.format(v) + " / "
                + (fmt.format(lim) if lim is not None else "-"))
    out += ["", "budgets",
            f"  iterations  {cap(st.get('iteration', 0), 'max_iterations')}",
            f"  replans     {cap(st.get('replans', 0), 'max_replans')}",
            f"  spend       {cap(st.get('spent_usd', 0.0), 'max_usd', '${:.2f}')}",
            f"  wall        {cap(hours, 'max_wall_hours', '{:.1f}h')}",
            f"  gpu         {cap(st.get('gpu_hours', 0.0), 'max_gpu_hours', '{:.1f}h')}"]

    if st.get("pending_gate"):
        out += ["", f">> WAITING FOR YOU: gate '{st['pending_gate']}'",
                "   python3 .claude/driver/loop.py approve"]
        gap = notify_gap()
        if gap:
            out += [f"   !! {gap}"]

    if EVENTS.exists():
        recent = [json.loads(x) for x in
                  EVENTS.read_text().splitlines()[-8:] if x.strip()]
        out += ["", "recent"] + [
            f"  {e['ts'][11:19]}  {e['event']:<20} "
            f"{str(e.get('detail', ''))[:54]}" for e in recent]
    print("\n".join(out))


# ---------- main --------------------------------------------------------

def main() -> None:
    # v8.1.1: through `tee`, stdout is block-buffered at 8 KB. A 54
    # minute run left logs/driver.log at ZERO bytes and the
    # `== HUMAN GATE ==` banner never appeared -- the documented way to
    # follow a loop could not announce the one thing needing a human.
    sys.stdout.reconfigure(line_buffering=True)
    argv = sys.argv[1:]
    allow_here = "--here" in argv
    args = [a for a in argv if not a.startswith("-")]

    if args and args[0] in ("status", "approve"):
        elsewhere = find_loop()
        if elsewhere != ROOT:
            print(f"(the loop is in {elsewhere})")
            rebind(elsewhere)

    if args and args[0] == "status":
        if "--json" in argv:
            print(json.dumps(load(STATE, {}), indent=2))
        else:
            phase_status(load(GOAL, {}) or {})
        return
    if args and args[0] == "approve":
        # v8.1.1: used to touch BOTH gate flags. wait_approval() deletes
        # any pre-existing flag on entry, so approving before the driver
        # reached the gate silently did nothing -- an invisible failure
        # mode. Target the pending gate, and say so when there is none.
        gate = args[1] if len(args) > 1 else \
            load(STATE, {}).get("pending_gate")
        if gate not in ("plan", "replan"):
            print("No gate is pending (loop-state.json has no "
                  "pending_gate). Nothing approved.", file=sys.stderr)
            sys.exit(1)
        APPROVALS.mkdir(exist_ok=True)
        (APPROVALS / f"{gate}.approved").touch()
        print(f"approved: {gate}")
        return

    cfg = load(GOAL, None)
    if cfg is None:
        die("goal.json not found or unreadable -- run the [/loop] Ask "
            "phase first.")

    # Four deterministic gates, cheapest first. Nothing is planned and
    # nothing is spent until all four pass.
    machinery()
    validate_goal(cfg)

    # `start` spawns the real driver elsewhere; isolation and preflight
    # are that process's gates to run, in the tree it will actually use.
    if args and args[0] == "start":
        phase_start(cfg, allow_here)
        return

    # v8.1.2: `check` used to run AFTER require_isolation, so it died in
    # the primary tree -- exactly where you want to run it, before there
    # is a worktree at all. It spawns nothing, so there is nothing to
    # contain; isolation is reported rather than enforced.
    if args and args[0] == "check":
        preflight(cfg)
        print("  isolation: "
              + ("linked worktree" if in_linked_worktree()
                 else "primary tree -- `start` will make a worktree"))
        ok, crit = check_criteria(cfg)
        for r in crit:
            print("  " + criteria_line(r))
        print(f"\ncriteria gate: {'PASS' if ok else 'FAIL'}")
        gap = notify_gap()
        if gap:
            print(f"!! {gap}")
        return

    require_isolation(cfg, allow_here)
    preflight(cfg)

    st = load(STATE, {"phase": "plan", "iteration": 0, "replans": 0,
                      "spent_usd": 0.0, "gpu_hours": 0.0,
                      "criteria_green": [],
                      "started_epoch": time.time(), "started": now()})
    save(STATE, st)
    event("loop_start" if st["iteration"] == 0 else "loop_resume",
          detail=cfg.get("goal", ""))

    if st["phase"] == "plan":
        phase_plan(cfg, st)
    if st["phase"] == "contract_review":
        phase_contract_review(cfg, st)
    if st["phase"] == "gate":
        wait_approval(st, "plan", "Plan.md ready + contract-reviewed. "
                      "Review it, then approve.")
        st["phase"] = "iterate"
        save(STATE, st)
    if st["phase"] == "iterate":
        phase_iterate(cfg, st)
    if st["phase"] == "final_eval":
        phase_final(cfg, st)
    if st["phase"] == "done":
        event("housekeeping_reminder",
              detail="fill journal Feedback block; read a sample of the "
                     "loop's diffs and explain them; delete Plan.md/"
                     "Evaluation.md/goal artifacts when satisfied")


if __name__ == "__main__":
    main()
