#!/usr/bin/env python3
"""CDD 8.1 PreToolUse hook: enforce phase authority mechanically.

Reads the tool call from stdin (Claude Code PreToolUse JSON), decides
allow/deny from the session's CDD role, and exits:
  0 = allow;  2 = DENY (stderr message is shown to the agent).

Role is set by the loop driver via env var CDD_ROLE
(planner | generator | evaluator | monitor). Generator dispatches also
set CDD_BOUNDARY (comma-separated path prefixes, relative to repo
root). Interactive sessions have no CDD_ROLE and are not restricted —
the human is the supervisor there. This hook is defense-in-depth for
AUTONOMOUS sessions, not a sandbox; keep the VM itself contained.

Motivated by journal/from-tcocrai-retro-20260713-2.md defect #2:
"the framework's authority matrix is prose in a prompt."

Bash coverage is DELIBERATELY INCOMPLETE (v8.1)
-----------------------------------------------
`Write`/`Edit` calls carry an explicit file_path, so those are decided
exactly. Shell commands do not, so `bash_write_targets()` extracts the
write targets of the forms a model reaches for by accident — redirects,
tee, sed -i, mv/cp/install, rm, dd, truncate — and runs each through the
same role decision as `Write`.

It does NOT and CANNOT cover interpreter escapes (`python3 -c`,
`perl -e`), heredocs, variable/command expansion, `base64 -d`, or an
`xargs` chain. A shell is Turing-complete; a pattern matcher is not.
The goal is to stop the accidental breach, not the adversarial one —
adversarial containment is the VM plus the worktree
(`.claude/rules/loop-protocol.md`). Do not grow this into a shell
parser; if a role needs real confinement, confine the process.
"""
import json
import os
import re
import sys


def deny(msg: str) -> None:
    print(f"CDD authority: DENIED. {msg} "
          f"(role={os.environ.get('CDD_ROLE')}; see "
          f".claude/rules/phase-authority.md). If this blocks your "
          f"ticket, STOP and report — do not work around it.",
          file=sys.stderr)
    sys.exit(2)


# Files no agent session may ever write (user- or driver-owned).
PROTECTED_ALWAYS = (
    "goal.md", "goal.json", "ledger.jsonl", "loop-state.json",
    "events.jsonl",
)

# Git subcommands that mutate state (only the driver commits).
GIT_WRITE = re.compile(
    r"\bgit\b[^|;&]*\b(commit|add|reset|checkout|push|tag|merge|rebase|"
    r"stash|rm|mv|restore|switch|cherry-pick|revert|clean|worktree)\b"
)

# Core files by lowercase basename or path fragment.
CORE_FILES = (
    "concept.md", "architecture.md", "readme.md", "plan.md",
    "triage.md", "claude.md",
)
CORE_DIRS = ("skills/", "docs/")


def norm(path: str) -> str:
    root = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    p = os.path.abspath(path if os.path.isabs(path)
                        else os.path.join(root, path))
    rel = os.path.relpath(p, root)
    return rel.replace("\\", "/").lower()


def is_protected_always(rel: str) -> bool:
    base = rel.rsplit("/", 1)[-1]
    return base in PROTECTED_ALWAYS


def is_core(rel: str) -> bool:
    base = rel.rsplit("/", 1)[-1]
    return base in CORE_FILES or any(rel.startswith(d) for d in CORE_DIRS)


def in_boundary(rel: str, boundary: list[str]) -> bool:
    if rel.startswith("logs/"):
        return True
    return any(rel == b or rel.startswith(b.rstrip("/") + "/")
               or rel.startswith(b) for b in boundary)


# Write targets a shell command would create/modify. Over-approximates
# (a quoted ">" may be misread) — over-denial is the safe direction, and
# the Generator is told to STOP and report rather than improvise.
SEGMENT = re.compile(r"[|;&\n]+")
# `(?:\d|(?<![-\d]))>` — a redirect is either `N>` or a `>` NOT preceded
# by `-`. v8.1.7: without the lookbehind, the `>` of a Python return
# annotation read as a redirect, so `def f(x: str) -> int:` denied the
# command and named `int:` as the write target. That is the pattern
# failing CLOSED on legal work — strictly worse than the documented
# heredoc blind spot, which only fails open — and it is what pushed the
# 2026-07-31 Evaluator into stripping annotations from its repro copies
# instead of stopping (journal/retro-20260731-toy-816.md, problem 3).
REDIRECT = re.compile(r"(?:\d|(?<![-\d]))>>?\s*([^\s|;&<>]+)")
LAST_ARG_CMDS = re.compile(r"^\s*(?:sudo\s+)?(sed|mv|cp|install|truncate)\b")
ALL_ARG_CMDS = re.compile(r"^\s*(?:sudo\s+)?(rm|tee|shred)\b")
DD_OF = re.compile(r"\bdd\b[^|;&]*?\bof=([^\s|;&]+)")


def bash_write_targets(cmd: str) -> list:
    """Best-effort list of paths this command would write. See the
    module docstring for what is intentionally out of scope."""
    out = []
    for seg in SEGMENT.split(cmd):
        if not seg.strip():
            continue
        out += REDIRECT.findall(seg)
        m = DD_OF.search(seg)
        if m:
            out.append(m.group(1))
        toks = seg.split()
        if LAST_ARG_CMDS.match(seg) and len(toks) > 1:
            # sed -i / mv / cp / install / truncate: the destination or
            # edited file is the trailing argument.
            if toks[0] != "sed" or any(t.startswith("-i") for t in toks):
                out.append(toks[-1])
        elif ALL_ARG_CMDS.match(seg):
            out += [t for t in toks[1:] if not t.startswith("-")]
    return [t.strip("'\"") for t in out if t.strip("'\"")]


def check_write(role: str, rel: str, boundary: list):
    """Role decision for one path. Returns a denial message or None.

    Shared by the Write/Edit branch and the Bash target scan so the two
    can never drift apart.
    """
    if is_protected_always(rel):
        return "Goal/ledger/state files are user- or driver-owned."
    if role == "monitor":
        return "Monitor never writes files — classify and stop."
    if role == "evaluator":
        if rel.rsplit("/", 1)[-1] not in ("evaluation.md", "verdict.json"):
            return "Evaluator writes only Evaluation.md/verdict.json."
        return None
    if role == "generator":
        if is_core(rel):
            return "Core files are read-only to the Generator."
        if boundary and not in_boundary(rel, boundary):
            return f"'{rel}' is outside your ticket Boundary."
        return None
    if role == "planner":
        # v8.1.1: a nested CLAUDE.md is Planner Read/Write/CREATE per
        # phase-authority.md. The blanket src//tests/ denial made the
        # planned module conventions unreachable and forced them into a
        # skill file instead -- the hook contradicting the matrix it
        # exists to enforce.
        if rel.startswith(("src/", "tests/")) and \
                rel.rsplit("/", 1)[-1] != "claude.md":
            return ("Planner never edits src/ or tests/ — re-dispatch "
                    "a Generator instead.")
        if rel.startswith("docs/") and not rel.endswith("deviations.md"):
            return ("docs/ originals are user-maintained "
                    "(DEVIATIONS.md append is the exception).")
        return None
    return None


def boundary_env() -> list:
    """CDD_BOUNDARY as comparable path prefixes.

    v8.1.3: strip markdown/quote wrapping per entry. The Planner writes
    the ticket field as markdown -- ``**Boundary:** `src/a.py`,
    `tests/b.py` `` -- and loop.py passes it through verbatim, so every
    entry used to arrive backticked and none of the comparisons in
    in_boundary() could match. A non-empty Boundary that matches nothing
    is a silent global write ban that reports itself as a Boundary
    breach; the first real loop (2026-07-30) escalated on ticket 1 with
    every Write denied. Tolerance belongs here rather than at the
    dispatch site because this is the sole consumer of the variable and
    the place that does the matching, so a hand-set env var and the
    control tower are covered too.
    """
    return [e for e in (b.strip().strip("`'\"").strip()
                        .replace("\\", "/").lower()
                        for b in os.environ.get("CDD_BOUNDARY",
                                                "").split(","))
            if e]


def main() -> None:
    role = os.environ.get("CDD_ROLE", "").strip().lower()
    if not role:               # interactive session: human supervises
        sys.exit(0)

    try:
        call = json.load(sys.stdin)
    except Exception:
        sys.exit(0)            # malformed input: fail open, log nothing
    tool = call.get("tool_name", "")
    tin = call.get("tool_input", {}) or {}

    # ---- Bash: block git mutations for every agent role -------------
    if tool == "Bash":
        cmd = tin.get("command", "")
        if GIT_WRITE.search(cmd):
            deny("Git write commands are driver-only in loop mode.")
        # Loose net for the driver/user-owned files, kept alongside the
        # precise scan below: these are the ones worth over-denying for.
        low = cmd.lower()
        if any(p in low for p in PROTECTED_ALWAYS) and re.search(
                r"(>|>>|\btee\b|\bsed\s+-i|\bmv\b|\brm\b|\bcp\b)", low):
            deny("Goal/ledger/state files are user- or driver-owned.")
        # v8.1: apply the SAME role decision as Write/Edit to the paths a
        # shell command would write. Previously core files and ticket
        # Boundaries were unguarded on this branch, so `echo x >
        # Architecture.md` sailed through for every role.
        boundary = boundary_env()
        for target in bash_write_targets(cmd):
            rel = norm(target)
            if rel.startswith(".."):
                continue          # outside the repo: VM's problem, not ours
            if role == "monitor":
                # Checked ahead of the logs/ exemption below: the Monitor
                # runs no Run Command, and the observer must not be able
                # to edit the observation it is classifying.
                deny("Monitor never writes files — classify and stop. "
                     f"(shell write to '{rel}')")
            if rel.startswith("logs/") or rel == "logs":
                continue          # gitignored runtime output; the roles
                                  # that execute a Run Command tee here
            msg = check_write(role, rel, boundary)
            if msg:
                deny(f"{msg} (shell write to '{rel}')")
        sys.exit(0)

    # ---- Write/Edit family -------------------------------------------
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        rel = norm(tin.get("file_path", tin.get("notebook_path", "")))
        msg = check_write(role, rel, boundary_env())
        if msg:
            deny(msg)
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
