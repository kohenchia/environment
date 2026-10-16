"""Which uncommitted changes belong to a session: the one rule `gg`, the Stop hook, `tyfp`, the wrap-up sweep and
`stella wrapup <team>` all use (status.blockers and wrapup.repo_problem call `check`).

A dirty file blocks a session only when the session could have made the change:

  (a) a tracked file that is modified, deleted or staged and is newer than the session's start;
  (b) a file the session itself wrote (its Edit/Write targets, Bash redirects), anything in a worktree it created (`wta`), and
      anything in a repo it ran `git add` / `commit` in. Reading a repo, or starting in it, is not work;
  (c) a path its reports or its order name;
  (d) an untracked file or directory (judged by its newest file) newer than the session's start, in a repo it worked in.

Left alone, and counted in one calm line when `gg` closes: untracked symlinks (what an installer links into a repo's
`.claude/`, which the session did not write itself), anything older than the session, and anything whose most recent writer is another live team's session.
With no start time known, age is not a reason to ignore a file.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from stella import state

WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
_WORD = r"(\"[^\"]+\"|'[^']+'|[^\s;&|)<>]+)"
_GIT_C = re.compile(r"\bgit\s+-C\s+" + _WORD + r"\s+(?:add|commit|rm|mv|stash|reset|checkout|switch|restore|apply|merge|rebase)\b")
_CD_GIT = re.compile(r"(?:^|[;&|(]\s*|&&\s*)cd\s+" + _WORD + r"\s*(?:&&|;)\s*git\s+(?:add|commit|rm|mv|stash|reset|checkout|switch|restore|apply|merge|rebase)\b")
_REDIRECT = re.compile(r">>?\s*" + _WORD + r"|\btee\s+(?:-a\s+)?" + _WORD)
_WTA = re.compile(r"\bwta\s+(\S+)\s+(\S+)")
SHOWN = 5


@dataclass
class Ctx:
    start: float | None = None  # epoch seconds of the session's first event
    mine: dict[str, float] = field(default_factory=dict)  # path -> when this session last wrote it
    others: dict[str, float] = field(default_factory=dict)  # path -> when another live team's session last wrote it
    touched: set[Path] = field(default_factory=set)  # repos it ran git add/commit in, worktrees it created
    named: list[Path] = field(default_factory=list)  # paths its reports and order name


@dataclass
class Result:
    blocking: list[str] = field(default_factory=list)  # file names, relative to the repo
    left: dict[str, int] = field(default_factory=dict)  # "untracked" | "modified" -> how many were left alone

    def message(self, name: str) -> str:
        more = f" and {len(self.blocking) - SHOWN} more" if len(self.blocking) > SHOWN else ""
        return f"uncommitted in {name}: {', '.join(self.blocking[:SHOWN])}{more}"


def _ts(s: str) -> float | None:
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def _top(path: str) -> Path | None:
    from stella import wrapup

    p = Path(os.path.expanduser(path.strip("\"'")))
    if not p.is_absolute():
        return None
    top = wrapup.toplevel(p)
    return top.resolve() if top else None


def scan(sid: str, written: dict[str, float], touched: set[Path] | None = None) -> float | None:
    """Read one session's transcript: its first timestamp; the files it wrote (into `written`, with the time); the repos it
    worked in (into `touched`). Reads are not work: only the write tools, `git -C`, `cd` and `wta` count."""
    from stella import resume

    p = resume.transcript(sid) if sid else None
    first = None
    if not p:
        return None
    try:
        lines = p.read_text(errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        if first is None and '"timestamp"' in line:
            try:
                first = _ts(json.loads(line).get("timestamp", ""))
            except json.JSONDecodeError:
                pass
        if '"tool_use"' not in line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        when = _ts(ev.get("timestamp", "")) or 0.0
        content = (ev.get("message") or {}).get("content")
        for b in content if isinstance(content, list) else []:
            if not isinstance(b, dict) or b.get("type") != "tool_use":
                continue
            inp = b.get("input") or {}
            if b.get("name") in WRITE_TOOLS:
                f = inp.get("file_path") or inp.get("notebook_path")
                if f:
                    f = str(Path(os.path.expanduser(f)).resolve())
                    written[f] = max(written.get(f, 0.0), when)
            elif b.get("name") == "Bash" and touched is not None:
                cmd = inp.get("command") or ""
                for m in (*_GIT_C.finditer(cmd), *_CD_GIT.finditer(cmd)):
                    top = _top(m.group(1))
                    if top:
                        touched.add(top)
                for m in _REDIRECT.finditer(cmd):
                    f = m.group(1) or m.group(2)
                    f = os.path.expanduser(f.strip("\"'"))
                    if os.path.isabs(f) and not f.startswith("/dev/"):
                        written[f] = max(written.get(f, 0.0), when)
                for m in _WTA.finditer(cmd):
                    top = _top(str(Path("~/github").expanduser() / f"{m.group(1)}-wt" / m.group(2)))
                    if top:
                        touched.add(top)
    return first


def context(st: state.State, sid: str, t: state.Team | None) -> Ctx:
    from stella import wrapup

    ctx = Ctx()
    mine = (t.sessions if t else set()) | ({sid} if sid else set()) | ({t.session_id} if t and t.session_id else set())
    starts = [s for s in (scan(m, ctx.mine, ctx.touched) for m in mine) if s]
    if t and t.ts:
        starts.append(t.ts.timestamp())  # a reopened session keeps the team's first launch
    if starts:
        ctx.start = min(starts)
    if t is None:
        return ctx
    o = st.orders.get(t.order or -1)
    for p in wrapup.mentioned_paths([*t.texts, *([o.text] if o else [])]):
        if p.exists():
            ctx.named.append(p.resolve())
    for other in st.teams.values():
        if other.name == t.name or other.acked or other.status not in {"running", "needs-you"}:
            continue
        for s in (other.sessions | ({other.session_id} if other.session_id else set())) - mine:
            scan(s, ctx.others)
    return ctx


def _entries(top: Path, only: set[str] | None) -> list[tuple[str, str]]:
    args = ["git", "--no-optional-locks", "-C", str(top), "status", "--porcelain", "-z", "--untracked-files=normal"]
    if only:
        args += ["--", *sorted(only)]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return []
    out, parts, i = [], r.stdout.split("\0"), 0
    while i < len(parts):
        e = parts[i]
        i += 1
        if len(e) < 4:
            continue
        code, path = e[:2], e[3:]
        if code[0] in "RC":
            i += 1  # the rename's source follows as its own field
        out.append((code, path))
    return out


def _index_mtime(top: Path) -> float:
    try:
        r = subprocess.run(["git", "--no-optional-locks", "-C", str(top), "rev-parse", "--git-path", "index"], capture_output=True,
                           text=True, timeout=10)
        p = Path(r.stdout.strip())
        return (p if p.is_absolute() else top / p).stat().st_mtime
    except (OSError, subprocess.TimeoutExpired):
        return 0.0


def _newest(p: Path) -> float:
    """A file's mtime; a directory's is its newest file's (an untracked directory is judged as one)."""
    try:
        m = p.lstat().st_mtime
    except OSError:
        return 0.0  # deleted
    if p.is_dir() and not p.is_symlink():
        for dp, _, files in os.walk(p):
            for f in files:
                try:
                    m = max(m, os.lstat(os.path.join(dp, f)).st_mtime)
                except OSError:
                    pass
    return m


def check(top: Path, only: set[str] | None, ctx: Ctx) -> Result:
    res = Result()
    root = top.resolve()
    worked_here = root in ctx.touched
    index = None
    for code, rel in _entries(top, only):
        p = root / rel
        untracked = code == "??"
        kind = "untracked" if untracked else "modified"
        if untracked and p.is_symlink():
            res.left[kind] = res.left.get(kind, 0) + 1  # what an installer links into `.claude/`: never this session's work
            continue
        under = [w for w in ctx.mine if w == str(p) or (rel.endswith("/") and w.startswith(str(p) + "/"))]
        theirs = ctx.others.get(str(p))
        if theirs is not None and theirs > ctx.mine.get(str(p), 0.0):
            res.left[kind] = res.left.get(kind, 0) + 1  # its latest writer is another live team's session
            continue
        if under or worked_here or any(n != root and (n == p or n in p.parents) for n in ctx.named):
            res.blocking.append(rel)
            continue
        if untracked and rel.startswith(".claude/"):
            res.left[kind] = res.left.get(kind, 0) + 1  # installed by a setup tool, not written by this session
            continue
        m = _newest(p)
        if not untracked and (code[0] != " " or "D" in code):  # staged or deleted: the index is the evidence
            index = _index_mtime(top) if index is None else index
            m = max(m, index)
        if ctx.start is None or m >= ctx.start:
            res.blocking.append(rel)
        else:
            res.left[kind] = res.left.get(kind, 0) + 1
    return res


def left_line(items: list[tuple[str, Result]]) -> str:
    """'left alone: 3 untracked files in proj, not from this session', or '' when nothing was left alone."""
    parts = []
    for name, r in items:
        bits = [f"{n} {kind} file{'s' if n != 1 else ''}" for kind, n in sorted(r.left.items(), reverse=True) if n]
        if bits:
            parts.append(f"{' and '.join(bits)} in {name}")
    return f"left alone: {'; '.join(parts)}, not from this session" if parts else ""
