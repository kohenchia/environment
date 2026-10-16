"""Which uncommitted changes belong to a session: PROVENANCE, not proximity. `gg`, the Stop hook, `tyfp`, the sweep and
`stella wrapup <team>` all ask `check` (through status.blockers); the unowned sweep (provenance.unowned) asks `writer`.

An uncommitted file is a session's business only if that session CAUSED it: it is the session whose Edit/Write tool call, Bash
redirect, `sed -i`, `cp`/`mv`/`rm`... wrote the file LAST, across every session's transcript (subagents' included: a subagent's
writes belong to the lead's session). The index is built from the transcripts and kept incrementally in the store.

For a file in a repo the session worked in:

  * last written by this session (or this team's other sessions, after a resume): blocks it;
  * last written by another session, live or closed: not its business, counted in one calm line when `gg` closes
    (a closed writer's files become an UNOWNED item in Stella's attention list instead: provenance.unowned);
  * no known writer (an installer, a hand edit, an old session whose transcript is gone): not its business either; it is
    UNOWNED, never "blocks the bystander". Untracked symlinks and untracked `.claude/` files are never anyone's work.

There is no "newer than my start", no "repo I worked in", no "path my report names": none of those is evidence that this session
wrote the file.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from stella import state
from stella.config import store_dir

WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SHOWN = 5
HORIZON = 45 * 86400  # transcripts older than this are not read
_RM = {"rm", "unlink"}


@dataclass
class Ctx:
    sessions: set[str] = field(default_factory=set)  # this session, its team's other sessions (a resume gets a new id)
    index: dict[str, tuple[str, float]] = field(default_factory=dict)  # path -> (session that wrote it last, when)

    def mine(self, session: str | None) -> bool:
        return bool(session) and session in self.sessions


@dataclass
class Result:
    blocking: list[str] = field(default_factory=list)  # file names relative to the repo: this session wrote them last
    left: dict[str, int] = field(default_factory=dict)  # "foreign" | "unowned" | "untracked" -> how many were left alone

    def message(self, name: str) -> str:
        more = f" and {len(self.blocking) - SHOWN} more" if len(self.blocking) > SHOWN else ""
        return f"uncommitted in {name}: {', '.join(self.blocking[:SHOWN])}{more}"


def _ts(s: str) -> float | None:
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def real(path: str | Path) -> str:
    return os.path.realpath(os.path.expanduser(str(path)))


# ---------------------------------------------------------------- the writers index


def _cache_file() -> Path:
    return store_dir() / "writers.json"


def transcript_files(since: float = 0.0) -> list[tuple[Path, str]]:
    """(transcript, session id) for every transcript touched after `since`: a session's own, and its subagents' (those belong
    to the lead's session, whose id is the directory they sit in)."""
    from stella import daily

    root = daily.transcripts_dir()
    out: list[tuple[Path, str]] = []
    floor = max(since, time.time() - HORIZON)
    for pat, sess in (("*/*.jsonl", lambda f: f.stem), ("*/*/subagents/*.jsonl", lambda f: f.parent.parent.name)):
        for f in root.glob(pat):
            try:
                if f.stat().st_mtime >= floor:
                    out.append((f, sess(f)))
            except OSError:
                pass
    return out


def _rm_paths(cmd: str, cwd: str) -> list[str]:
    """Files a `rm`, `git rm` or `git mv` removes, when the path is literal."""
    from stella import gate

    here = Path(os.path.expanduser(cwd or "/"))
    out: list[str] = []
    try:
        segs = gate._segments(cmd)
    except Exception:  # noqa: BLE001
        return out
    for seg in segs:
        if seg[0] == "cd" and len(seg) > 1:
            t = Path(os.path.expandvars(os.path.expanduser(seg[1])))
            here = t if t.is_absolute() else here / t
            continue
        c = gate._command(seg)
        if not c:
            continue
        word, args = c
        sub = gate._git_sub(seg) if word == "git" else None
        if word in _RM or sub in {"rm", "mv"}:
            base = here
            for i, tok in enumerate(args[:-1]):
                if tok == "-C":
                    base = here / os.path.expanduser(args[i + 1])
            tail = args[args.index(sub) + 1:] if sub in args else args
            for a in (x for x in tail if not x.startswith("-")):
                if "$" in a or "*" in a:
                    continue
                p = Path(os.path.expanduser(a))
                out.append(real(p if p.is_absolute() else base / p))
    return out


def _event_writes(ev: dict, into: dict[str, float]) -> None:
    from stella import bashwrites

    when = _ts(ev.get("timestamp", "")) or 0.0
    cwd = ev.get("cwd") or ""
    content = (ev.get("message") or {}).get("content")
    for b in content if isinstance(content, list) else []:
        if not isinstance(b, dict) or b.get("type") != "tool_use":
            continue
        inp = b.get("input") or {}
        paths: list[str] = []
        if b.get("name") in WRITE_TOOLS:
            f = inp.get("file_path") or inp.get("notebook_path")
            if f:
                p = Path(os.path.expanduser(f))
                paths.append(real(p if p.is_absolute() else Path(cwd) / p))
        elif b.get("name") == "Bash":
            cmd = inp.get("command") or ""
            try:
                for w in bashwrites.writes(cmd, cwd):
                    for t in w.targets:
                        if not (Path(t) / ".git").exists():  # `git commit` yields its repo: a commit is not a file write
                            paths.append(real(t))
            except Exception:  # noqa: BLE001 - a command the parser chokes on writes nothing we can name
                pass
            if " rm " in f" {cmd} " or "git rm" in cmd or "git mv" in cmd or "unlink" in cmd:
                paths += _rm_paths(cmd, cwd)
        for p in paths:
            into[p] = max(into.get(p, 0.0), when)


def _scan_file(f: Path, entry: dict) -> dict:
    """Read what a transcript gained since last time (it only ever grows) into the cache entry."""
    try:
        size = f.stat().st_size
    except OSError:
        return entry
    if size < entry.get("off", 0):  # rewritten: start over
        entry = {"off": 0, "w": {}}
    start = entry.get("off", 0)
    if size == start:
        return entry
    try:
        with open(f, "rb") as fh:
            fh.seek(start)
            raw = fh.read(size - start)
    except OSError:
        return entry
    end = raw.rfind(b"\n") + 1  # a line still being written is read next time
    w = entry.setdefault("w", {})
    for line in raw[:end].decode("utf-8", "replace").splitlines():
        if '"tool_use"' not in line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        _event_writes(ev, w)
    entry["off"] = start + end
    return entry


def index(since: float = 0.0) -> dict[str, tuple[str, float]]:
    """path -> (session that wrote it last, when), over every transcript touched after `since`."""
    try:
        cache = json.loads(_cache_file().read_text())
    except (OSError, ValueError):
        cache = {}
    changed = False
    out: dict[str, tuple[str, float]] = {}
    for f, sid in transcript_files(since):
        key = str(f)
        before = cache.get(key, {"off": 0, "w": {}})
        after = _scan_file(f, json.loads(json.dumps(before)))
        if after.get("off") != before.get("off"):
            cache[key] = after
            changed = True
        for p, when in cache.get(key, {}).get("w", {}).items():
            if p not in out or when >= out[p][1]:
                out[p] = (sid, when)
    if changed:
        try:
            _cache_file().parent.mkdir(parents=True, exist_ok=True)
            tmp = _cache_file().with_suffix(".tmp")
            tmp.write_text(json.dumps(cache))
            tmp.replace(_cache_file())
        except OSError:
            pass
    return out


def writer(idx: dict[str, tuple[str, float]], p: str, is_dir: bool = False) -> tuple[str, float] | None:
    """Who wrote this path last. A directory (an untracked tree) was written by whoever wrote its newest file."""
    hit = idx.get(p)
    if not is_dir:
        if hit:
            return hit
        d = os.path.dirname(p)  # a file inside a directory some command created (cp -r, mkdir)
        while d and d != "/":
            if d in idx:
                return idx[d]
            d = os.path.dirname(d)
        return None
    best = hit
    pre = p.rstrip("/") + "/"
    for k, v in idx.items():
        if k.startswith(pre) and (best is None or v[1] > best[1]):
            best = v
    return best


# ---------------------------------------------------------------- the check


def context(st: state.State, sid: str, t: state.Team | None, idx: dict | None = None) -> Ctx:
    from stella import provenance

    return Ctx(sessions=provenance.who(st, sid, t).sessions, index=idx if idx is not None else index())


def _repo_top(d: str) -> Path | None:
    """The git checkout a directory is in, found by walking up to the nearest `.git` (a file for a worktree): no process."""
    p = Path(d)
    home = Path(os.path.expanduser("~")).resolve()
    for q in (p, *p.parents):
        if q in {home, Path("/")}:
            return None
        if (q / ".git").exists():
            return None if store_dir() in {q, *q.parents} or q in store_dir().parents else q
    return None


def footprint(ctx: Ctx) -> set[Path]:
    """The git checkouts this session wrote a file in (derived from the index, so a repo only read is never one)."""
    tops: set[Path] = set()
    for d in {os.path.dirname(p) for p, (sid, _) in ctx.index.items() if ctx.mine(sid)}:
        top = _repo_top(d)
        if top:
            tops.add(top.resolve())
    return tops


def newest(p: Path) -> float:
    """A file's mtime; a directory's is its newest file's."""
    try:
        m = p.lstat().st_mtime
    except OSError:
        return 0.0
    if p.is_dir() and not p.is_symlink():
        for dp, _, files in os.walk(p):
            for f in files:
                try:
                    m = max(m, os.lstat(os.path.join(dp, f)).st_mtime)
                except OSError:
                    pass
    return m


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


def classify(top: Path, only: set[str] | None, idx: dict) -> list[tuple[str, str, tuple[str, float] | None]]:
    """(file relative to the repo, "untracked"/"modified"/"never", its last writer) for each dirty path; "never" is a path that
    can be nobody's work (an installer's symlink, an untracked `.claude/` file)."""
    root = top.resolve()
    out = []
    for code, rel in _entries(top, only):
        p = root / rel
        untracked = code == "??"
        if untracked and (p.is_symlink() or rel.startswith(".claude/")):
            out.append((rel, "never", None))
            continue
        out.append((rel, "untracked" if untracked else "modified", writer(idx, real(p), is_dir=rel.endswith("/"))))
    return out


def check(top: Path, only: set[str] | None, ctx: Ctx) -> Result:
    res = Result()
    for rel, kind, w in classify(top, only, ctx.index):
        if kind == "never":
            res.left["untracked"] = res.left.get("untracked", 0) + 1
        elif w and ctx.mine(w[0]):
            res.blocking.append(rel)
        else:
            k = "foreign" if w else "unowned"
            res.left[k] = res.left.get(k, 0) + 1
    return res


def left_line(items: list[tuple[str, Result]]) -> str:
    """'left alone: 3 uncommitted files in proj, not from this session', or '' when nothing was left alone."""
    parts = []
    for name, r in items:
        n = sum(v for k, v in r.left.items() if k != "untracked")
        if n:
            parts.append(f"{n} uncommitted file{'s' if n != 1 else ''} in {name}")
    return f"left alone: {'; '.join(parts)}, not from this session" if parts else ""
