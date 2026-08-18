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
import datetime
import json
import os
import re
import sys

# What the current call was trying to do, for the denial log. Set by
# main() before any decision is taken.
CALL_SUMMARY = ""


def log_denial(msg: str) -> None:
    """Leave a trace of the denial where the driver and user can find it.

    v8.1.9: `deny()` wrote to the agent's stderr and exited 2, and
    nothing else. A denial was therefore invisible in `events.jsonl`,
    so diagnosing one — a real breach or a hook false positive — meant
    digging through a session transcript. That is what the 2026-08-02
    `2>&1` false positive cost: a killed Evaluator audit and a paid
    re-run before anyone could see why (see
    journal/from-aibench-retro-20260802.md, problem 2a).

    `logs/` is gitignored runtime output and is writable by every role,
    so logging here does not make the hook a writer of anything it
    guards. Best-effort by design: a hook that crashed while logging
    would fail OPEN, which is strictly worse than not logging.
    """
    try:
        root = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
        if not os.path.isdir(root):
            return                     # not a real tree: leave no litter
        d = os.path.join(root, "logs")
        os.makedirs(d, exist_ok=True)
        stamp = datetime.datetime.now().isoformat(timespec="seconds")
        with open(os.path.join(d, "denials.log"), "a") as fh:
            fh.write(f"{stamp}\t{os.environ.get('CDD_ROLE', '-')}\t"
                     f"{msg}\t{CALL_SUMMARY[:300]}\n")
    except Exception:
        pass


def deny(msg: str) -> None:
    log_denial(msg)
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
#
# The gap between `git` and its subcommand excludes every shell
# separator, NEWLINE INCLUDED. Without \n\r the net spans lines: a
# read-only `git log` on one line and a bare `add` on any later line of
# the same multi-line Bash batch matched as one command. That is the
# false-positive class loop-protocol.md section 3 calls a defect rather
# than caution, and it cost loop 6 an escalation at ticket 1 -- nine
# denials, and an Evaluator audit killed before it ran the test suite.
# Verified after the fix: `git commit -m x`, `git add -A`,
# `git  checkout main` and `cd /tmp && git push` are all still denied.
GIT_WRITE = re.compile(
    r"\bgit\b[^|;&\n\r]*\b(commit|add|reset|checkout|push|tag|merge|rebase|"
    r"stash|rm|mv|restore|switch|cherry-pick|revert|clean|worktree)\b"
)

# Read-only invocations whose SUBCOMMAND shares a name with a write.
# Scrubbed out of the command before GIT_WRITE sees it. Each form here
# must end at a shell separator or end-of-string, so an argument that
# turns the listing into a mutation (`git tag v1.0`) does not match and
# stays subject to the net above. `git stash` bare is a WRITE and is
# deliberately absent -- only its `list`/`show` forms are read-only.
GIT_READONLY = re.compile(
    r"\bgit\s+(?:"
    r"tag(?:\s+(?:-n\d*|--sort\s*=\s*\S+"
    r"|(?:-l|--list)(?:\s+(?:'[^']*'|\"[^\"]*\"|[^-\s|;&][^\s|;&]*))?))*"
    r"|stash\s+(?:list|show)"
    r"|worktree\s+list"
    r")"
    # A trailing redirect does not turn a listing into a write. Without
    # this, `git worktree list 2>&1` -- the Evaluator's standard
    # orientation command -- failed the end-of-segment lookahead and
    # fell through to GIT_WRITE. Any file the redirect names is still
    # decided separately by bash_write_targets().
    r"(?:\s*(?:\d*>>?\s*[^\s|;&]+|\d*>&\d+))*"
    r"\s*(?=$|[|;&\n\r])"
)

# Core files by lowercase basename or path fragment.
CORE_FILES = (
    "concept.md", "architecture.md", "readme.md", "plan.md",
    "triage.md", "claude.md",
)
CORE_DIRS = ("skills/", "docs/")


def resolve(path: str) -> tuple:
    """(project root, absolute target) with symlinks RESOLVED, both.

    v8.1.11. Both sides used `abspath`, which normalises `..` but
    follows nothing, so the hook decided the token it was handed rather
    than the file that would actually be written. The Evaluator that
    reviewed the /tmp carve-out on 2026-08-11 filed this itself
    (non-blocking F3): `/tmp/x -> <repo>/goal.json` reads as scratch and
    is permitted, because only the unresolved prefix was ever compared.

    The root is resolved too, and that is not decoration: resolving one
    side only would make `relpath` return `../..` for every project
    living under a symlinked path (`/home/me -> /mnt/home/me`), and a
    target that resolves outside the repo is SKIPPED on the Bash branch.
    A half-resolved pair fails OPEN across the whole matrix -- strictly
    worse than the abspath it replaces.
    """
    root = os.path.realpath(
        os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    return root, os.path.realpath(
        path if os.path.isabs(path) else os.path.join(root, path))


def norm(path: str) -> str:
    root, p = resolve(path)
    rel = os.path.relpath(p, root)
    return rel.replace("\\", "/").lower()


def is_scratch(path: str) -> bool:
    """True for /tmp scratch -- outside the repo, outside the matrix.

    v8.1.9c. The Bash branch already skips any target resolving outside
    the repo ("outside the repo: VM's problem, not ours"), so
    `echo x > /tmp/f` was permitted for every role -- while the
    Write/Edit branch had no such exemption, so the SAME action was
    denied through the tool and allowed through the shell. A rule that
    depends on which tool you reach for is not a rule.

    That inconsistency stopped a provenance audit mid-flight on
    2026-08-11: `.claude/agents/cdd-evaluator.md` REQUIRES
    reconstructing prior states in /tmp to verify claims, and the hook
    denied `Write: /tmp/evaluator_independent_check.py` on the very
    iteration where five criteria first went green -- so the audit that
    earns a green could not be performed, and the Evaluator correctly
    escalated rather than working around it. Denying the auditor its
    scratch space defeats loop-protocol.md section 7.

    Deliberately scoped to /tmp: a ticket Boundary reaching outside the
    repo (the lmms-eval clone) is still enforced exactly as before, so
    a Generator can still write only the clone files its ticket names.

    v8.1.11: decided on the RESOLVED path (see resolve()), so a /tmp
    symlink pointing back into the repo is not scratch -- and a project
    that itself lives under /tmp is not one big carve-out. Scratch means
    outside the repo, which is a two-sided test; the one-sided prefix
    check disabled the entire matrix for any tree rooted in /tmp (a CI
    checkout, `toy_project.sh /tmp/...`), and it disabled it silently.
    """
    root, p = resolve(path)
    if p == root or p.startswith(root + os.sep):
        return False                  # inside the repo: the matrix decides
    tmp = os.path.realpath("/tmp")
    return p == tmp or p.startswith(tmp + os.sep)


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
# v8.1.9b: `(?!=)` — `>=` is a comparison, not a redirect. The sibling
# of the v8.1.7 `->` fix one line up: a read-only Evaluator heredoc
# doing `if s['reward'] >= 1` was denied as a shell write to '=1'
# (2026-08-03, second false-positive escalation in one loop).
REDIRECT = re.compile(r"(?:\d|(?<![-\d]))>>?(?!=)\s*([^\s|;&<>]+)")
# A heredoc body is DATA, not shell. The module docstring has always
# declared heredocs out of scope (fail OPEN); scanning their lines as
# segments made them fail CLOSED instead — the code contradicting its
# own contract. Truncate at the first heredoc operator; anything after
# the terminator is forfeited to the documented blind spot.
HEREDOC = re.compile(r"<<-?\s*['\"]?\w")
# A quoted span is LITERAL in shell — a `>` inside one is never a
# redirect. v8.1.9b third false positive in one loop (2026-08-03):
# `git show --format='%an <%ae>%n...'` denied a read-only Evaluator as
# a shell write to '%n%ad%n%s%n'. Quoted spans containing shell
# metacharacters are blanked before the scan (they cannot be operators);
# spans WITHOUT metacharacters stay, so a quoted write target
# (`tee 'Plan.md'`) is still caught.
QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_META = re.compile(r"[|;&<>]")
LAST_ARG_CMDS = re.compile(r"^\s*(?:sudo\s+)?(sed|mv|cp|install|truncate)\b")
ALL_ARG_CMDS = re.compile(r"^\s*(?:sudo\s+)?(rm|tee|shred)\b")
DD_OF = re.compile(r"\bdd\b[^|;&]*?\bof=([^\s|;&]+)")
# A token that IS redirect syntax (`>`, `>>`, `2>`, `2>&1`, `<`). The
# ALL_ARG_CMDS token scan stops here: redirect TARGETS are REDIRECT's
# job, decided by target one line up. v8.1.9b: `tee logs/latest.log
# > /dev/null` handed the bare `>` token to the role decision as a
# write target named '>', which denied a read-only Evaluator running a
# ticket's mandated Run Command (2026-08-03) — the same
# false-positive-by-syntax class as the `2>&1` co-occurrence denial
# fixed in v8.1.9 (loop-protocol.md #3: denying a command that merely
# NAMES a protected file is a defect, not caution).
REDIR_TOK = re.compile(r"^\d*>>?|^<")
# A redirect operator with NO target glued to it (`>`, `>>`, `2>`, `<`):
# its target is the NEXT token, which must be dropped too. `2>/dev/null`
# carries its own and consumes nothing further.
BARE_REDIR = re.compile(r"\d*>>?|<")


def bash_write_targets(cmd: str) -> list:
    """Best-effort list of paths this command would write. See the
    module docstring for what is intentionally out of scope."""
    out = []
    m = HEREDOC.search(cmd)
    if m:
        cmd = cmd[:m.start()]
    cmd = QUOTED.sub(
        lambda q: "''" if _META.search(q.group(0)) else q.group(0), cmd)
    for seg in SEGMENT.split(cmd):
        if not seg.strip():
            continue
        out += REDIRECT.findall(seg)
        m = DD_OF.search(seg)
        if m:
            out.append(m.group(1))
        # Redirects are not arguments. Strip them before ANY positional
        # reasoning (v8.1.9c). REDIR_TOK guarded only the ALL_ARG branch,
        # so `cp -a a.log /tmp/b.log 2>/dev/null` handed `2>/dev/null` to
        # the trailing-argument rule as its destination -- the third
        # false-positive escalation of this loop, and the second to kill
        # an Evaluator audit. It also LEAKED: in
        # `cp a.txt Architecture.md > /dev/null` the trailing argument is
        # `/dev/null`, which the sink filter below then drops, so the
        # write to a core file was never decided at all.
        toks = []
        drop_next = False
        for t in seg.split():
            if drop_next:                    # `> foo`: foo is the target
                drop_next = False
                continue
            if REDIR_TOK.match(t):
                drop_next = bool(BARE_REDIR.fullmatch(t))
                continue                     # REDIRECT's job either way
            toks.append(t)
        if LAST_ARG_CMDS.match(seg) and len(toks) > 1:
            # sed -i / mv / cp / install / truncate: the destination or
            # edited file is the trailing argument.
            if toks[0] != "sed" or any(t.startswith("-i") for t in toks):
                out.append(toks[-1])
        elif ALL_ARG_CMDS.match(seg):
            for t in toks[1:]:
                if not t.startswith("-"):
                    out.append(t)
    # /dev/null is a sink, writable by definition — never a target worth
    # deciding (v8.1.9b, same incident as REDIR_TOK).
    return [t for t in (t.strip("'\"") for t in out)
            if t and t != "/dev/null"]


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
    global CALL_SUMMARY
    CALL_SUMMARY = (f"{tool}: " + str(tin.get("command")
                                      or tin.get("file_path")
                                      or tin.get("notebook_path") or ""))

    # ---- Bash: block git mutations for every agent role -------------
    if tool == "Bash":
        cmd = tin.get("command", "")
        # Scrub the LISTING forms of subcommands whose names also name a
        # write, then test what is left. `git tag` with no argument
        # lists tags; `git tag v1.0` creates one. GIT_WRITE cannot tell
        # them apart because it matches a keyword anywhere after `git`,
        # so a read-only provenance batch ending `git tag | head` was
        # denied -- the second false positive of this class in one loop,
        # and it again ended an Evaluator audit mid-flight.
        if GIT_WRITE.search(GIT_READONLY.sub(" ", cmd)):
            deny("Git write commands are driver-only in loop mode.")
        # Loose net for the driver/user-owned files, kept alongside the
        # precise scan below for the cases quoting or expansion can hide
        # a target from it (`cp goal.json{,.bak}`).
        #
        # v8.1.9 narrowed it twice, because as written it denied by mere
        # CO-OCCURRENCE anywhere in the command string:
        #   * redirects are gone from the verb list. `>` matched the `>`
        #     of `2>&1`, so `cat goal.json 2>&1` was a denied "write" to
        #     a protected file. It killed a read-only Evaluator audit
        #     mid-loop on 2026-08-02. Nothing is lost: the precise scan
        #     below denies `echo x > goal.json` BY TARGET, and it is
        #     strictly better at it — the only case this net could add is
        #     an expanded path (`> $F`), which does not contain the
        #     filename either, so it never caught that one.
        #   * the test is per shell segment now. Otherwise a legal Run
        #     Command that merely NAMES the goal and tees elsewhere —
        #     `python3 x.py --goal goal.json 2>&1 | tee logs/latest.log`
        #     — was denied for every role, because `goal.json` and `tee`
        #     both appeared somewhere in it.
        # Over-denial is still the safe direction, but it is not free:
        # each false positive costs a whole paid session and reads to
        # the loop as a failure (journal/from-aibench-retro-20260802.md).
        for seg in SEGMENT.split(cmd.lower()):
            if any(p in seg for p in PROTECTED_ALWAYS) and re.search(
                    r"(\btee\b|\bsed\s+-i|\bmv\b|\brm\b|\bcp\b)", seg):
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
        raw = tin.get("file_path", tin.get("notebook_path", ""))
        if is_scratch(raw):
            sys.exit(0)       # /tmp: the Bash branch already allows it
        rel = norm(raw)
        msg = check_write(role, rel, boundary_env())
        if msg:
            deny(msg)
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
