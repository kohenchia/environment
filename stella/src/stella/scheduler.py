"""The scheduler: runs the daily log and the nightly jobs for the day that just ended (a window
between two local midnights, see `due`), and every
`wake_check_minutes` looks for a wake line to Stella that never arrived (see wake.py).

It runs as a detached background process started by `stella run` from the owner's
terminal, not as a system service: a service manager may launch it without the file
permissions the owner's terminal has, while a process started from that terminal
inherits them. If it isn't running when a run is due (machine asleep, process gone),
the next Claude session that starts runs one catch-up pass. A day missed is caught
up for at most three days back, one run per missed day. The last cutoff is stored in
scheduler.json as a timezone-aware instant with its zone name, so a time-zone change
cannot double-count or drop an hour: consecutive windows tile exactly.

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

from stella import daily, ledger, safety
from stella.config import BIN, headless_env, settings, store_dir

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


def zone_name() -> str:
    """The machine's current time zone, by name (TZ, else the /etc/localtime link, else the abbreviation)."""
    tz = os.environ.get("TZ", "").lstrip(":")
    if tz:
        return tz
    try:
        path = os.path.realpath("/etc/localtime")
    except OSError:
        path = ""
    if "zoneinfo/" in path:
        return path.split("zoneinfo/", 1)[1]
    return time.tzname[0]


MIN_WINDOW = dt.timedelta(hours=1)  # a shorter window is skipped; the next midnight picks it up
MAX_WINDOW = dt.timedelta(hours=36)  # a longer one is split on local midnights
MAX_DAYS_BACK = 3


def _midnight(date: dt.date) -> dt.datetime:
    return daily.local_midnight(date)


def cutoff_record(end: dt.datetime) -> dict:
    """What a completed run stores: the cutoff instant (offset included) and the zone it was local midnight in."""
    return {"at": end.isoformat(), "tz": zone_name()}


def last_cutoff(st: dict) -> dict | None:
    """The stored cutoff. A scheduler.json from before cutoffs (`last_done`, a date whose whole day was logged)
    counts as local midnight at the end of that date."""
    lc = st.get("last_cutoff")
    if lc:
        return lc
    if st.get("last_done"):
        end = _midnight(dt.date.fromisoformat(st["last_done"]) + dt.timedelta(days=1))
        return cutoff_record(end)
    return None


def due(now: dt.datetime, last: dict | None) -> list[daily.Window]:
    """The windows to run now, oldest first; they tile exactly from the stored cutoff to the latest cutoff.

    The cutoff is the latest local midnight (in the current zone) at or before `now`, once `daily_time` of
    the day after it has been reached. No stored cutoff: the previous local calendar day. A window shorter
    than MIN_WINDOW (or inverted, after a zone change) is skipped; one longer than MAX_WINDOW is split on
    local midnights so each day gets its own run; the start is never more than MAX_DAYS_BACK days back.
    """
    now = now.astimezone()
    hh, mm = (int(x) for x in settings().daily_time.split(":"))
    day = now.date() if (now.hour, now.minute) >= (hh, mm) else now.date() - dt.timedelta(days=1)
    end = _midnight(day)
    zone = zone_name()
    if last:
        start = dt.datetime.fromisoformat(last["at"])
    else:
        start = _midnight(day - dt.timedelta(days=1))
    start = max(start, _midnight(day - dt.timedelta(days=MAX_DAYS_BACK)))
    if end - start < MIN_WINDOW:
        return []
    cuts = [start, end]
    if end - start > MAX_WINDOW:
        mids, d = [], start.astimezone().date() + dt.timedelta(days=1)
        while _midnight(d) < end:
            if _midnight(d) > start:
                mids.append(_midnight(d))
            d += dt.timedelta(days=1)
        if mids and mids[0] - start < MIN_WINDOW:  # a sliver at the front joins the next day: still no gap
            mids = mids[1:]
        cuts = [start, *mids, end]
    return [daily.Window(a, b, zone) for a, b in zip(cuts, cuts[1:])]


def tick(now: dt.datetime | None = None, claude: str | None = None) -> list[str]:
    from stella import passenv

    from stella import state

    from stella import finish

    now = now or ledger.now()
    finish.clear_pushed(state.fold())  # a deferred push that has since reached its remote leaves the owner's list
    st = _load()
    wins = due(now, last_cutoff(st))
    if not wins:
        return []
    try:
        passenv.resolve()
    except SystemExit as e:  # don't run on the wrong credentials, and don't mark the day done
        if "scheduler:pass-env" not in state.fold().alerts:  # once, not every minute
            ledger.append("alert", by="scheduler", key="scheduler:pass-env", text=f"scheduler waiting: {e}")
        return []
    prev = last_cutoff(st)
    if prev and prev.get("tz") not in (None, zone_name()):
        ledger.append("note", by="scheduler", text=f"time zone changed since the last cutoff ({prev['tz']} -> {zone_name()}):"
                      f" running {len(wins)} window(s) from {prev['at']}")
    did = []
    for w in wins:
        daily.run_daily(w, claude=claude)
        daily.run_nightly(w, claude=claude)
        st["last_cutoff"] = cutoff_record(w.end)
        st.pop("last_done", None)
        _save(st)
        did.append(f"{w.label.isoformat()} [{w.describe()}]")
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
    every = settings().wake_check_minutes * 60
    print(f"{ledger.now():%Y-%m-%d %H:%M} stella scheduler: daily log for each day that ends (runs from {settings().daily_time} after local midnight); checking every {interval}s;"
          f" wake-line backstop every {every // 60}m", flush=True)
    last_wake_check = 0.0
    while True:
        try:
            did = tick()
            if did:
                print(f"{ledger.now():%Y-%m-%d %H:%M} ran daily+nightly for {', '.join(did)}", flush=True)
            if every > 0 and time.monotonic() - last_wake_check >= every:
                last_wake_check = time.monotonic()
                r = wake_backstop()
                if r:
                    print(f"{ledger.now():%Y-%m-%d %H:%M} wake backstop: {r}", flush=True)
        except Exception as e:  # noqa: BLE001 - keep the loop alive, but say so
            ledger.append("alert", by="scheduler", key="scheduler:error", text=f"scheduler error: {type(e).__name__}: {e}")
            print(f"error: {e}", flush=True)
        sweep_wrapup()
        end = time.monotonic() + interval
        while time.monotonic() < end:  # the last-resort queues (tyfp, adoption) are served here
            time.sleep(min(3, max(0.1, end - time.monotonic())))
            _close_queued()


def _close_queued() -> None:
    from stella import wrapup

    try:
        wrapup.process_requests()
    except Exception as e:  # noqa: BLE001
        print(f"gg error: {type(e).__name__}: {e}", flush=True)


def sweep_wrapup() -> None:
    """Wrap up the finished teams that are clean (see wrapup.py). Plain Python; no model runs. A failure
    is logged and raised once as an alert, never every minute."""
    from stella import state, wrapup

    try:  # with wrapup_auto off only the gone teams (no window, no process) are recorded: nothing is closed
        wrapped, _ = wrapup.sweep(gone_only=not settings().wrapup_auto)
        if wrapped:
            print(f"{ledger.now():%Y-%m-%d %H:%M} wrapped up: {', '.join(v.team for v in wrapped)}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"wrapup error: {type(e).__name__}: {e}", flush=True)
        if "scheduler:wrapup" not in state.fold().alerts:
            ledger.append("alert", by="scheduler", key="scheduler:wrapup", text=f"wrap-up sweep error: {type(e).__name__}: {e}")


def wake_backstop(now: dt.datetime | None = None) -> str | None:
    """A wake line that never arrived (the helper died, or she was busy until it gave up): send it now if
    she is idle. Plain Python over the ledger and her screen; no model runs. None when nothing is pending."""
    from stella import wake

    r = wake.backstop(now)
    return None if r.status == "nothing" else f"{r.status} {r.detail}".rstrip()


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
    safety.kill(pid, signal.SIGTERM)
    return f"Stopped the scheduler (pid {pid})."


def _credentials_match() -> bool:
    """A catch-up pass runs its jobs with the query binary, inside this session's sandbox, which may
    bill this session's own credentials whatever environment it is given. So only a session whose
    pass_env variables agree with the switch may run one; another session (or the daemon) will.
    This only guards who runs the pass; it never changes the switch."""
    from stella import passenv

    names = settings().pass_env
    if not names:
        return True
    has = all(os.environ.get(k) for k in names)
    return has == (passenv.effective() == "on")


def catch_up_if_needed() -> None:
    """Called from the SessionStart hook: if no scheduler is running and a run is
    overdue, start one catch-up pass in the background. Never blocks the session."""
    if os.environ.get("STELLA_NO_CATCHUP") == "1":
        return
    try:
        if running_pid() or not due(ledger.now(), last_cutoff(_load())):
            return
        if not _credentials_match():
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
                             env=headless_env())
    except OSError:
        pass
