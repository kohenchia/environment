"""Make sessions findable by `claude --resume`, and reopen one by name.

Claude Code's picker lists the transcripts of the directory you run it in, by name, but it leaves
out any session whose transcript *begins* with a non-interactive origin: the first `entrypoint`
in the file's first 64 KB (`sdk-cli` for a `claude -p` run) decides, however many interactive
turns were added after it. A review that started as a headless run and was later resumed by hand is
therefore resumable by id only. `make_listable` rewrites that origin to `cli`.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from stella import daily

HEAD = 65536  # how much of the file Claude Code reads to classify it
SDK_ORIGIN = re.compile(rb'"entrypoint":\s*"sdk-(?:cli|ts|py)"')
IDLE = 60  # seconds a transcript must be untouched before it is rewritten: a live session appends to it
TITLE = re.compile(rb'"customTitle":\s*"((?:[^"\\]|\\.)*)"')
CWD = re.compile(rb'"cwd":\s*"((?:[^"\\]|\\.)*)"')
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


@dataclass
class Found:
    session_id: str
    path: Path
    title: str | None
    cwd: str | None


def transcript(session_id: str) -> Path | None:
    return next(iter(daily.transcripts_dir().glob(f"*/{session_id}.jsonl")), None)


def _last(rx: re.Pattern[bytes], data: bytes) -> str | None:
    hits = rx.findall(data)
    return hits[-1].decode(errors="replace") if hits else None


def _first(rx: re.Pattern[bytes], data: bytes) -> str | None:
    m = rx.search(data)
    return m.group(1).decode(errors="replace") if m else None


def describe(path: Path) -> Found:
    size = path.stat().st_size
    with path.open("rb") as f:
        head = f.read(HEAD)
        f.seek(max(0, size - 4 * HEAD))
        tail = f.read()
    # the directory it started in is the one `--resume` must be run from
    return Found(path.stem, path, _last(TITLE, tail) or _last(TITLE, head), _first(CWD, head) or _last(CWD, tail))


def lookup(target: str) -> Found | None:
    """A transcript by session id, or by the name it was given (the newest one with that name)."""
    if UUID.match(target):
        p = transcript(target)
        return describe(p) if p else None
    hits = []
    for p in daily.transcripts_dir().glob("*/*.jsonl"):
        try:
            with p.open("rb") as f:
                f.seek(max(0, p.stat().st_size - 4 * HEAD))
                if _last(TITLE, f.read()) == target:
                    hits.append((p.stat().st_mtime, p))
        except OSError:
            continue
    return describe(max(hits)[1]) if hits else None


def hidden(path: Path) -> bool:
    """True when the picker leaves this transcript out because of how it began."""
    with path.open("rb") as f:
        head = f.read(HEAD)
    m = re.search(rb'"entrypoint":\s*"([^"]*)"', head)
    return bool(m and SDK_ORIGIN.fullmatch(m.group(0)))


def make_listable(path: Path, now: float | None = None) -> str | None:
    """Rewrite a headless origin to `cli` so the picker lists the session. Returns what it did, or None
    when there was nothing to change. A transcript touched in the last IDLE seconds is left alone."""
    if not hidden(path):
        return None
    if (now or time.time()) - path.stat().st_mtime < IDLE:
        return f"{path.stem}: in use, left alone"
    before = path.stat()
    data = path.read_bytes()
    out = SDK_ORIGIN.sub(b'"entrypoint":"cli"', data)
    tmp = path.with_name(path.name + ".stella-tmp")
    tmp.write_bytes(out)
    os.chmod(tmp, before.st_mode & 0o777)
    if path.stat().st_mtime != before.st_mtime:  # appended to while we worked: leave it
        tmp.unlink()
        return f"{path.stem}: in use, left alone"
    tmp.replace(path)
    return f"{path.stem}: now listed by the resume picker"


def heal_known(sessions: set[str]) -> list[str]:
    """make_listable for every transcript of the given session ids."""
    out = []
    for sid in sorted(sessions):
        p = transcript(sid)
        r = make_listable(p) if p else None
        if r:
            out.append(r)
    return out
