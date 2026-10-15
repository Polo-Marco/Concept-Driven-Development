#!/usr/bin/env python3
"""Archive the Claude Code session transcript into journal/traces/.

Fired by the SessionEnd hook (see .claude/settings.json). Reads the hook
JSON payload from stdin and copies the FULL session transcript — every
tool call, input, output, and decision — next to the project's curated
journal summaries, as journal/traces/<timestamp>-<session>.jsonl.

This is Tier 2 of the session journal (see .claude/rules/governance.md
§6): the curated `journal/*.md` summary is the primary artifact for
`[retro]`; this raw trace is the forensic drill-down for loops you flag
"bad". Claude Code only — Cursor has no equivalent transcript path.

Never blocks session end: any error exits 0 silently.
"""
import json
import shutil
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

TZ = ZoneInfo("Asia/Taipei")  # v8.1.17: one clock everywhere


def primary_tree(cwd: Path) -> Path:
    """The main repository's working tree for `cwd`: from a linked
    worktree that is the tree the worktree was made from; from the
    primary tree, or outside git, `cwd` itself."""
    try:
        r = subprocess.run(["git", "rev-parse", "--git-common-dir"],
                           cwd=cwd, text=True, capture_output=True,
                           timeout=10)
        common = r.stdout.strip()
        if r.returncode == 0 and common:
            p = Path(common)
            if not p.is_absolute():
                p = cwd / p
            return p.resolve().parent
    except (OSError, subprocess.SubprocessError):
        pass
    return cwd


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # never block session end

    transcript = payload.get("transcript_path")
    if not transcript:
        return 0
    src = Path(transcript).expanduser()
    if not src.is_file():
        return 0

    project = Path(payload.get("cwd") or ".")
    # v8.1.19 (C5): write into the PRIMARY tree's journal/traces/. Loop
    # sessions run in a per-loop worktree, and the worktree is removed
    # at close -- so the Tier-2 traces of three deployments' first
    # campaigns no longer exist (EBFT M0-M3b, JEV loops 1-7, DF M0/M1a;
    # journal/retro-20261015-cross-project.md, C5). `git rev-parse
    # --git-common-dir` names the main repository's .git from any
    # worktree; its parent is the primary tree. Falls back to cwd when
    # not in a git tree, and never blocks session end.
    dest_dir = primary_tree(project) / "journal" / "traces"
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(TZ).strftime("%Y%m%d-%H%M%S")
        session = payload.get("session_id", "session")
        shutil.copy(src, dest_dir / f"{ts}-{session}.jsonl")
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
