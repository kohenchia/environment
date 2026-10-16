"""The scheduler: runs the daily log at the configured time, then the nightly jobs.

It runs as a long-lived process in a tmux window, not as a system service: a
service manager may launch it without the file permissions the owner's terminal
has, while a tmux window inherits them. If a day was missed (machine asleep), it
catches up on the next start, for at most three days back.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import time

from stella import daily, ledger
from stella.config import settings, store_dir


def _state_path():
    return store_dir() / "scheduler.json"


def _load() -> dict:
    try:
        return json.loads(_state_path().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(d: dict) -> None:
    _state_path().write_text(json.dumps(d))


def due(now: dt.datetime, last_done: str | None) -> list[dt.date]:
    hh, mm = (int(x) for x in settings().daily_time.split(":"))
    today = now.date()
    reached = (now.hour, now.minute) >= (hh, mm)
    newest = today if reached else today - dt.timedelta(days=1)
    if last_done:
        start = dt.date.fromisoformat(last_done) + dt.timedelta(days=1)
    else:
        start = newest  # first run: only the most recent day
    start = max(start, newest - dt.timedelta(days=2))
    out, d = [], start
    while d <= newest:
        out.append(d)
        d += dt.timedelta(days=1)
    return out


def tick(now: dt.datetime | None = None) -> list[str]:
    now = now or ledger.now()
    st = _load()
    did = []
    for d in due(now, st.get("last_done")):
        daily.run_daily(d)
        daily.run_nightly(d)
        st["last_done"] = d.isoformat()
        _save(st)
        did.append(d.isoformat())
    return did


def run_forever(interval: int = 60) -> int:
    store_dir().mkdir(parents=True, exist_ok=True)
    lock = (store_dir() / "scheduler.lock").open("a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("another stella scheduler is already running")
        return 1
    (store_dir() / "scheduler.pid").write_text(str(__import__("os").getpid()))
    print(f"stella scheduler: daily log at {settings().daily_time}; checking every {interval}s")
    while True:
        try:
            did = tick()
            if did:
                print(f"{ledger.now():%Y-%m-%d %H:%M} ran daily+nightly for {', '.join(did)}")
        except Exception as e:  # noqa: BLE001 - keep the loop alive, but say so
            ledger.append("alert", by="scheduler", key="scheduler:error", text=f"scheduler error: {type(e).__name__}: {e}")
            print(f"error: {e}")
        time.sleep(interval)
