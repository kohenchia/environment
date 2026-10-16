"""The ledger: one append-only record of orders, decisions, launches and results.

Every session reads and writes the same files, so this is what makes Stella
consistent across sessions. Events are JSON objects, one per line, in one file per
month (`ledger/YYYY-MM.jsonl`). Appends happen under an exclusive lock, which also
hands out the sequence number, so the ledger is totally ordered.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import json
import os
from collections.abc import Iterator
from pathlib import Path

from stella.config import store_dir

# Event types only the prompt hook may write. `stella log` refuses them, so an
# instruction or a push approval can't be invented by a model calling the CLI.
HOOK_ONLY = frozenset({"order", "push_deferred", "direct"})


def ledger_dir() -> Path:
    return store_dir() / "ledger"


def now() -> dt.datetime:
    return dt.datetime.now().astimezone()


@contextlib.contextmanager
def _locked() -> Iterator[Path]:
    d = ledger_dir()
    d.mkdir(parents=True, exist_ok=True)
    with (d / ".lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield d
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _read_seq(d: Path) -> int:
    try:
        return int((d / "seq").read_text().strip() or 0)
    except FileNotFoundError:
        return 0


def append(type_: str, **fields) -> dict:
    """Append one event and return it (with its `seq` and `ts`)."""
    with _locked() as d:
        seq = _read_seq(d) + 1
        ts = now()
        event = {"seq": seq, "ts": ts.isoformat(timespec="seconds"), "type": type_}
        event.update({k: v for k, v in fields.items() if v is not None})
        line = json.dumps(event, ensure_ascii=False) + "\n"
        path = d / f"{ts:%Y-%m}.jsonl"
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode())
        finally:
            os.close(fd)
        tmp = d / "seq.tmp"
        tmp.write_text(str(seq))
        tmp.replace(d / "seq")
        return event


def last_seq() -> int:
    return _read_seq(ledger_dir())


def events(since: int = 0) -> Iterator[dict]:
    """All events with seq > since, oldest first. Malformed lines are skipped."""
    d = ledger_dir()
    if not d.exists():
        return
    for path in sorted(d.glob("*.jsonl")):
        with path.open() as f:
            for line in f:
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(ev, dict) and ev.get("seq", 0) > since:
                    yield ev


def parse_ts(ev: dict) -> dt.datetime:
    return dt.datetime.fromisoformat(ev["ts"])
