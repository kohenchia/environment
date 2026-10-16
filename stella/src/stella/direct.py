"""Closing a session's own tmux window without tmux: by signalling the processes the window is made of.

A hook runs in Claude Code's command sandbox. That sandbox denies the tmux socket and the process table (`ps` sees nothing), so a
hook cannot ask tmux to kill a window. It can still read the kernel's process info through libproc, and it may signal processes of
its own user (a hook that signalled its ancestors, the pane's shell and tmux itself included, was allowed). A window closes when its
pane process exits, and the sidebar pane then sees it is alone and exits too (docs/tmux.md). So:

    tmux server
      └─ pane process    the shell the window was started with (or Claude itself, if it was started with `exec`)
           └─ ... └─ claude          <- the hook is its descendant

    close = SIGHUP the pane process, SIGTERM claude, then SIGKILL whichever is still alive

Who to signal is read from the process tree, never from an environment variable or a pane id: the ancestors of the hook ARE the
window it was typed in, so a `gg` can only ever close its own window. For a session that is not the caller (the `tyfp` sweep) the
way in is the session file Claude writes (`~/.claude/sessions/<pid>.json`: pid, session id, its tmux window and pane, idle or busy),
checked against the process (alive, same start time, under a pane process of tmux). A pid is signalled only if it still has the
start time that was recorded, so a reused pid is never hit.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from stella import ledger, safety
from stella.config import BIN

PROC_PIDTBSDINFO = 3


class _BsdInfo(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_uint32), ("status", ctypes.c_uint32), ("xstatus", ctypes.c_uint32), ("pid", ctypes.c_uint32),
                ("ppid", ctypes.c_uint32), ("uid", ctypes.c_uint32), ("gid", ctypes.c_uint32), ("ruid", ctypes.c_uint32),
                ("rgid", ctypes.c_uint32), ("svuid", ctypes.c_uint32), ("svgid", ctypes.c_uint32), ("rfu1", ctypes.c_uint32),
                ("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32), ("nfiles", ctypes.c_uint32), ("pgid", ctypes.c_uint32),
                ("pjobc", ctypes.c_uint32), ("tdev", ctypes.c_uint32), ("tpgid", ctypes.c_uint32), ("nice", ctypes.c_int32),
                ("start_sec", ctypes.c_uint64), ("start_usec", ctypes.c_uint64)]


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    comm: str
    start: int  # seconds; 0 when unknown (the `ps` fallback)


_lib = None


def _libproc():
    global _lib
    if _lib is None:
        name = ctypes.util.find_library("proc")
        try:
            _lib = ctypes.CDLL(name) if name else False
        except OSError:
            _lib = False
    return _lib


def info(pid: int) -> Proc | None:
    """The process `pid`, or None when it does not exist (or cannot be read)."""
    if pid <= 0:
        return None
    lib = _libproc()
    if lib:
        b = _BsdInfo()
        if lib.proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, ctypes.byref(b), ctypes.sizeof(b)) > 0 and b.pid == pid:
            return Proc(pid, b.ppid, b.comm.decode(errors="replace"), int(b.start_sec))
        return None
    try:  # no libproc (not macOS): the process table
        r = subprocess.run(["ps", "-o", "ppid=,comm=", "-p", str(pid)], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    f = r.stdout.split(None, 1)
    return Proc(pid, int(f[0]), os.path.basename(f[1].strip()), 0) if len(f) == 2 and f[0].isdigit() else None


def chain(pid: int) -> list[Proc]:
    """`pid` and its ancestors, nearest first, up to (not including) launchd."""
    out = []
    for _ in range(60):
        p = info(pid)
        if not p:
            break
        out.append(p)
        if p.ppid <= 1:
            break
        pid = p.ppid
    return out


def is_tmux(p: Proc | None) -> bool:
    return bool(p) and p.comm.startswith("tmux")


def pane_process(pid: int) -> Proc | None:
    """The process tmux started for the pane `pid` runs in: `pid` itself or its nearest ancestor whose parent is the tmux server."""
    ch = chain(pid)
    for i, p in enumerate(ch):
        if not is_tmux(p) and i + 1 < len(ch) and is_tmux(ch[i + 1]):
            return p
    return None


def claude_ancestor() -> Proc | None:
    """The Claude process this process runs under, read without `ps`."""
    if "STELLA_CLAUDE_PID" in os.environ:  # set where the process tree must not be walked (tests: never find the real session)
        v = os.environ["STELLA_CLAUDE_PID"]
        return info(int(v)) if v.isdigit() else None
    ch = chain(os.getpid())
    return next((p for p in ch[1:] if p.comm.startswith("claude")), None)


# ---------------------------------------------------------------- sessions Claude knows about


def sessions_dir() -> Path:
    return Path(os.environ.get("STELLA_CLAUDE_SESSIONS") or Path.home() / ".claude" / "sessions")


def session_files() -> list[dict]:
    """What each running Claude wrote about itself: pid, sessionId, name, tmux (`session:@window.%pane`), status (idle/busy)."""
    out = []
    try:
        files = sorted(sessions_dir().glob("*.json"))
    except OSError:
        return out
    for f in files:
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and isinstance(d.get("pid"), int):
            out.append(d)
    return out


def session_window(d: dict) -> str:
    """The tmux window id a session file records (`work:@33.%77` -> `@33`), or ''."""
    return (d.get("tmux") or "").partition(":")[2].partition(".")[0]


@dataclass(frozen=True)
class Target:
    """A Claude session that can be closed: its process and the pane process of its window, with the start times they must still have."""
    claude: Proc
    pane: Proc
    sid: str = ""
    name: str = ""
    window: str = ""
    idle: bool = False


def _alive(p: Proc) -> bool:
    now = info(p.pid)
    return bool(now) and (not p.start or not now.start or now.start == p.start)


def _target(claude: Proc, rec: dict | None, sid: str = "") -> Target | str:
    """The target for a Claude process, or why there is none. Refuses a pane that another live session shares."""
    pane = pane_process(claude.pid)
    if not pane:
        return "this session is not running in a tmux window"
    if rec and sid and rec.get("sessionId") and rec["sessionId"] != sid:
        return "the process asking is not this session"
    for d in session_files():
        if d["pid"] != claude.pid and info(d["pid"]) and (pp := pane_process(d["pid"])) and pp.pid == pane.pid:
            return f"its window also holds another Claude session ({d.get('name') or d['pid']})"
    rec = rec or {}
    return Target(claude, pane, rec.get("sessionId") or sid, rec.get("name") or "", session_window(rec), rec.get("status") == "idle")


def of_pid(pid: int | None, sid: str) -> Target | str:
    """The session whose Claude process is `pid` (as the hook that typed `gg` or `tyfp` read it), or why it cannot be closed."""
    c = info(pid) if pid else None
    if not c:
        return "could not find the Claude process this runs under"
    rec = next((d for d in session_files() if d["pid"] == c.pid), None)
    return _target(c, rec, sid)


def own(sid: str) -> Target | str:
    """The session this process runs under (the hook of the session that typed `gg`), or why it cannot be closed."""
    c = claude_ancestor()
    return of_pid(c.pid if c else None, sid)


def of_team(t) -> Target | str:
    """The live session of a team (its recorded session id, running in the team's window), or why there is none."""
    mine = set(getattr(t, "sessions", ()) or ()) | ({t.session_id} if getattr(t, "session_id", None) else set())
    for d in session_files():
        if d.get("sessionId") not in mine:
            continue
        c = info(d["pid"])
        if not c:
            continue
        if t.window and session_window(d) and session_window(d) != t.window:
            return f"its session now runs in window {session_window(d)}, not {t.window}; left alone"
        return _target(c, d, d.get("sessionId") or "")
    return "no live Claude session of it found"


# ---------------------------------------------------------------- closing


def _signal(p: Proc, sig: int) -> None:
    """Signal `p` only if it is still the process that was recorded (same start time) and is not the tmux server."""
    now = info(p.pid)
    if not now or is_tmux(now) or (p.start and now.start and now.start != p.start) or p.pid <= 1 or p.pid == os.getpid():
        return
    try:
        safety.kill(p.pid, sig)  # under pytest this raises for any pid that is not the test's own (see `safety`)
    except safety.UnsafeSignal:
        if safety.roots() is not None:
            raise
    except OSError:
        pass


def close_now(t: Target, wait: float = 2.0) -> bool:
    """Close the window now: SIGHUP the pane process, SIGTERM Claude, SIGKILL what is left after `wait` seconds. True when both
    are gone. When this runs in a hook of the very session it closes, Claude dies with the window and this does not return."""
    _signal(t.pane, signal.SIGHUP)
    if t.claude.pid != t.pane.pid:
        _signal(t.claude, signal.SIGTERM)
    for sig, secs in ((signal.SIGKILL, wait), (None, 1.0)):
        end = time.monotonic() + secs
        while time.monotonic() < end and (_alive(t.pane) or _alive(t.claude)):
            time.sleep(0.05)
        if sig and (_alive(t.pane) or _alive(t.claude)):
            _signal(t.pane, sig)
            _signal(t.claude, sig)
    return not (_alive(t.pane) or _alive(t.claude))


def close_later(t: Target, delay: float) -> None:
    """The same, `delay` seconds later by a detached helper (so the reply or report that asked can be read first)."""
    spec = ",".join(f"{p.pid}:{p.start}" for p in (t.pane, t.claude))
    subprocess.Popen([str(BIN), "wrapup", "--close-pids", spec, "--delay", f"{delay:g}"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def run_helper(spec: str, delay: float) -> None:
    """Detached helper of `close_later`: `PANE:START,CLAUDE:START`, closed after `delay`, and an alert if it did not close."""
    pane, claude = (Proc(int(a), 0, "", int(b)) for a, b in (x.split(":") for x in spec.split(",")))
    time.sleep(delay)
    if not close_now(Target(claude, pane)):
        ledger.append("alert", by="wrapup", key=f"window-open:{pane.pid}", text=f"gg: the window of session process {claude.pid} did not close")
