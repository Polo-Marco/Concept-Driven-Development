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
        # crude protection against shell-side edits of protected files
        low = cmd.lower()
        if any(p in low for p in PROTECTED_ALWAYS) and re.search(
                r"(>|>>|\btee\b|\bsed\s+-i|\bmv\b|\brm\b|\bcp\b)", low):
            deny("Goal/ledger/state files are user- or driver-owned.")
        sys.exit(0)

    # ---- Write/Edit family -------------------------------------------
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        rel = norm(tin.get("file_path", tin.get("notebook_path", "")))

        if is_protected_always(rel):
            deny("Goal/ledger/state files are user- or driver-owned.")

        if role == "monitor":
            deny("Monitor never writes files — classify and stop.")

        if role == "evaluator":
            base = rel.rsplit("/", 1)[-1]
            if base not in ("evaluation.md", "verdict.json"):
                deny("Evaluator writes only Evaluation.md/verdict.json.")
            sys.exit(0)

        if role == "generator":
            if is_core(rel):
                deny("Core files are read-only to the Generator.")
            boundary = [b.strip().replace("\\", "/").lower()
                        for b in os.environ.get(
                            "CDD_BOUNDARY", "").split(",") if b.strip()]
            if boundary and not in_boundary(rel, boundary):
                deny(f"'{rel}' is outside your ticket Boundary.")
            sys.exit(0)

        if role == "planner":
            if rel.startswith(("src/", "tests/")):
                deny("Planner never edits src/ or tests/ — re-dispatch "
                     "a Generator instead.")
            if rel.startswith("docs/") and not rel.endswith(
                    "deviations.md"):
                deny("docs/ originals are user-maintained "
                     "(DEVIATIONS.md append is the exception).")
            sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
