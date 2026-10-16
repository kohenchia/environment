"""The scheduler: runs the daily log at the configured time, then the nightly jobs.

It runs as a detached background process started by `stella run` from the owner's
terminal, not as a system service: a service manager may launch it without the file
permissions the owner's terminal has, while a process started from that terminal
inherits them. If it isn't running when a run is due (machine asleep, process gone),
the next Claude session that starts runs one catch-up pass. A day missed is caught
up for at most three days back.

One lock (`scheduler.lock`) is held by whichever scheduler is working, so the daemon
and a catch-up pass can never run the same jobs twice.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import signal
import subprocess
import time

from stella import daily, ledger
from stella.config import BIN, settings, store_dir

CATCH_UP_EVERY = 30 * 60  # seconds between catch-up attempts from sessions


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


def tick(now: dt.datetime | None = None, claude: str | None = None) -> list[str]:
    now = now or ledger.now()
    st = _load()
    did = []
    for d in due(now, st.get("last_done")):
        daily.run_daily(d, claude=claude)
        daily.run_nightly(d, claude=claude)
        st["last_done"] = d.isoformat()
        _save(st)
        did.append(d.isoformat())
    return did


# ---------------------------------------------------------------- locking


def _lock_file():
    store_dir().mkdir(parents=True, exist_ok=True)
    return (store_dir() / "scheduler.lock").open("a+")


def _try_lock():
    f = _lock_file()
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        return None
    return f


def running_pid() -> int | None:
    f = _try_lock()
    if f:
        f.close()  # nobody holds it
        return None
    try:
        return int((store_dir() / "scheduler.pid").read_text())
    except (FileNotFoundError, ValueError):
        return -1


# ---------------------------------------------------------------- entry points


def run_forever(interval: int = 60) -> int:
    lock = _try_lock()
    if not lock:
        print("another stella scheduler is already running")
        return 1
    (store_dir() / "scheduler.pid").write_text(str(os.getpid()))
    print(f"{ledger.now():%Y-%m-%d %H:%M} stella scheduler: daily log at {settings().daily_time}; checking every {interval}s", flush=True)
    while True:
        try:
            did = tick()
            if did:
                print(f"{ledger.now():%Y-%m-%d %H:%M} ran daily+nightly for {', '.join(did)}", flush=True)
        except Exception as e:  # noqa: BLE001 - keep the loop alive, but say so
            ledger.append("alert", by="scheduler", key="scheduler:error", text=f"scheduler error: {type(e).__name__}: {e}")
            print(f"error: {e}", flush=True)
        time.sleep(interval)


def run_once(in_session: bool = False) -> list[str]:
    """Run what is due, if no other scheduler is working. Inside a Claude session the
    shell is sandboxed, so headless runs use the query binary, which works there."""
    lock = _try_lock()
    if not lock:
        return []
    try:
        (store_dir() / "scheduler.pid").write_text(str(os.getpid()))
        did = tick(claude=settings().query_bin if in_session else None)
        if did and in_session:
            ledger.append("note", by="scheduler", text=f"catch-up from a session ran {', '.join(did)}; the background scheduler was not running (`stella run` restarts it)")
        return did
    finally:
        lock.close()


def ensure_daemon() -> str:
    pid = running_pid()
    if pid:
        return f"Scheduler running (pid {pid})."
    log = store_dir() / "runs" / "scheduler.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as out:
        p = subprocess.Popen([str(BIN), "scheduler"], stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                             cwd=str(store_dir()), start_new_session=True)
    for _ in range(30):
        time.sleep(0.1)
        if running_pid():
            return f"Started the scheduler in the background (pid {p.pid}); log: {log}."
    return f"Started the scheduler (pid {p.pid}) but it has not taken its lock yet; see {log}."


def stop_daemon() -> str:
    pid = running_pid()
    if not pid or pid < 0:
        return "Scheduler not running."
    os.kill(pid, signal.SIGTERM)
    return f"Stopped the scheduler (pid {pid})."


def catch_up_if_needed() -> None:
    """Called from the SessionStart hook: if no scheduler is running and a run is
    overdue, start one catch-up pass in the background. Never blocks the session."""
    if os.environ.get("STELLA_NO_CATCHUP") == "1":
        return
    try:
        if running_pid() or not due(ledger.now(), _load().get("last_done")):
            return
        stamp = store_dir() / "catch-up.stamp"
        if stamp.exists() and time.time() - stamp.stat().st_mtime < CATCH_UP_EVERY:
            return
        stamp.touch()
        log = store_dir() / "runs" / "catch-up.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as out:
            subprocess.Popen([str(BIN), "scheduler", "--once", "--in-session"], stdin=subprocess.DEVNULL, stdout=out,
                             stderr=subprocess.STDOUT, start_new_session=True,
                             env={**os.environ, "STELLA_HEADLESS": "1"})
    except OSError:
        pass
