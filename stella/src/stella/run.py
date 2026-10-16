"""`stella run` and `stella stop`: Stella's own session, where every message is to her.

Typed in a terminal, `stella run` starts the scheduler in the background, then runs
Stella right there (the tmux tab is called `stella` while she runs and gets its old
name back when she exits), or switches to her tab if she is already running. Called
by an agent, it opens her tab in the background.

"Running" means her Claude process is alive, not that a tab of that name exists: a
tab keeps its name after Claude exits, and a name alone would say she is running
when only a shell is left.
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys

from stella import daily, scheduler, tmuxctl
from stella.config import settings, store_dir

WINDOW = "stella"
ENV = "STELLA_SELF"  # set in Stella's own session; the hooks treat every message there as addressed


def is_self() -> bool:
    return os.environ.get(ENV) == "1"


# ---------------------------------------------------------------- state


def _file():
    return store_dir() / "stella-session.json"


def _load() -> dict:
    for p in (_file(), store_dir() / "hq.json"):  # hq.json: the name before 2026-10-16
        try:
            return json.loads(p.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            continue
    return {}


def _update(**fields) -> None:
    d = _load()
    d.update({k: v for k, v in fields.items()})
    _file().write_text(json.dumps(d))


def remember_session(session_id: str) -> None:
    _update(session_id=session_id)


def _resumable(session_id: str | None) -> bool:
    """Only a conversation that actually started has a transcript to resume. One that
    was abandoned at the folder-trust prompt has an id but nothing to resume."""
    if not session_id:
        return False
    return any(daily.transcripts_dir().glob(f"*/{session_id}.jsonl"))


def _alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def running() -> dict | None:
    d = _load()
    return d if _alive(d.get("pid")) else None


# ---------------------------------------------------------------- run


def _argv(fresh: bool) -> list[str]:
    s = settings()
    argv = [s.claude_bin, "--name", WINDOW, "--agent", "stella:stella", "--permission-mode", s.permission_mode]
    sid = None if fresh else _load().get("session_id")
    if _resumable(sid):
        argv += ["--resume", sid]
    return argv


def _run_here(argv: list[str], srv) -> int:
    """Run Stella in this terminal and wait; restore the tab's name afterwards."""
    pane = os.environ.get("TMUX_PANE", "")
    target = ["-t", pane] if pane else []
    old_name = None
    if srv and os.environ.get("TMUX"):
        r = srv.run("display-message", "-p", *target, "#{window_name}", check=False)
        old_name = r.stdout.strip() or None
        srv.run("rename-window", *target, WINDOW, check=False)
    env = {**os.environ, ENV: "1"}
    try:
        p = subprocess.Popen(argv, cwd=os.path.expanduser("~"), env=env)
        _update(pid=p.pid, window=None, pane=pane or None)
        try:
            return p.wait()
        except KeyboardInterrupt:
            return p.wait()
    finally:
        _update(pid=None)
        if old_name and old_name != WINDOW:
            srv.run("rename-window", *target, old_name, check=False)


def run(fresh: bool = False) -> str | int:
    store_dir().mkdir(parents=True, exist_ok=True)
    sched = scheduler.ensure_daemon()
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    srv = tmuxctl.find_server()
    current = running()
    if current and not fresh:
        where = current.get("window") or current.get("pane")
        if interactive and srv and where:
            srv.run("select-window", "-t", where, check=False)
        return f"Stella is already running (pid {current['pid']}{', ' + where if where else ''}). {sched}"
    if current and fresh:
        stop(keep_scheduler=True)
    argv = _argv(fresh)
    if interactive:
        print(sched)
        return _run_here(argv, srv)
    if not srv:
        return tmuxctl.last_error or "No tmux server is running: run `stella run` in a terminal."
    cmd = f"export {ENV}=1; cd ~ && exec " + " ".join(shlex.quote(a) for a in argv)
    w = tmuxctl.new_window(srv, WINDOW, os.path.expanduser("~"), cmd)
    pid = srv.run("display-message", "-p", "-t", w, "#{pane_pid}", check=False).stdout.strip()
    _update(pid=int(pid) if pid.isdigit() else None, window=w, pane=None)
    return f"Opened Stella in window {w}. {sched}"


# ---------------------------------------------------------------- stop


def stop(keep_scheduler: bool = False) -> str:
    """Stop Stella's session (and, unless asked not to, the scheduler). Teams she
    launched keep running in their own tabs; `stella reap` closes finished ones."""
    out = []
    current = running()
    if current:
        try:
            os.kill(current["pid"], signal.SIGTERM)
            out.append(f"Stopped Stella's session (pid {current['pid']}).")
        except ProcessLookupError:
            out.append("Stella's session had already exited.")
        if current.get("window"):
            srv = tmuxctl.find_server()
            if srv:
                srv.run("kill-window", "-t", current["window"], check=False)
        _update(pid=None, window=None)
    else:
        out.append("Stella's session is not running.")
    if not keep_scheduler:
        out.append(scheduler.stop_daemon())
    return " ".join(out)
