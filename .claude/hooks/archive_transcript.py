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
import sys
from datetime import datetime
from pathlib import Path


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
    dest_dir = project / "journal" / "traces"
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        session = payload.get("session_id", "session")
        shutil.copy(src, dest_dir / f"{ts}-{session}.jsonl")
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
