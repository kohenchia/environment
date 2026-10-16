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

from stella import daily, ledger, passenv, safety, scheduler, tmuxctl
from stella.config import BIN, settings, store_dir

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


def resumable(session_id: str | None) -> bool:
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


def _argv(fresh: bool, note: str | None = None, sid: str | None = None) -> list[str]:
    s = settings()
    argv = [s.claude_bin, "--name", WINDOW, "--agent", "stella:stella", "--permission-mode", s.permission_mode]
    sid = None if fresh else (sid or _load().get("session_id"))
    if resumable(sid):
        argv += ["--resume", sid] + ([note] if note else [])
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
    env = passenv.apply({**os.environ, ENV: "1"})
    try:
        p = subprocess.Popen(argv, cwd=os.path.expanduser("~"), env=env)
        _update(pid=p.pid, window=None, pane=pane or None,
                socket=srv.socket if srv and os.environ.get("TMUX") else None)  # where the wake line types
        try:
            return p.wait()
        except KeyboardInterrupt:
            return p.wait()
    finally:
        _update(pid=None)
        if old_name and old_name != WINDOW:
            srv.run("rename-window", *target, old_name, check=False)


def run(fresh: bool = False, pass_env: str | None = None) -> str | int:
    store_dir().mkdir(parents=True, exist_ok=True)
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    srv = tmuxctl.find_server()
    current = running()
    if current and not fresh:
        if pass_env:
            passenv.set_mode(pass_env, by="run")
            return (f"Stella is already running; pass_env is now {pass_env} for new sessions. To move her and"
                    " running teams onto it: `stella pass-env --respawn`.")
        sched = scheduler.ensure_daemon()
        where = current.get("window") or current.get("pane")
        if interactive and srv and where:
            srv.run("select-window", "-t", where, check=False)
        return f"Stella is already running (pid {current['pid']}{', ' + where if where else ''}). {sched}"
    if current and fresh:
        stop(keep_scheduler=True)
    switched = _set_pass_env(pass_env)  # before the daemon starts: it would record the default first
    sched = scheduler.ensure_daemon()
    argv = _argv(fresh)
    if interactive:
        print(sched)
        if switched:
            print(switched)
        return _run_here(argv, srv)
    if not srv:
        return tmuxctl.last_error or "No tmux server is running: run `stella run` in a terminal."
    creds = passenv.resolve()
    w = tmuxctl.new_window(srv, WINDOW, os.path.expanduser("~"), _command(argv, creds),
                           env={k: v for k, v in creds.items() if v is not None})
    pid = srv.run("display-message", "-p", "-t", w, "#{pane_pid}", check=False).stdout.strip()
    _update(pid=int(pid) if pid.isdigit() else None, window=w, pane=None, socket=srv.socket)
    return f"Opened Stella in window {w}. {sched}" + (f" {switched}" if switched else "")


def _set_pass_env(explicit: str | None) -> str | None:
    """Only an explicit --pass-env changes the switch; a plain `stella run` reads it. Returns
    a line to show when the switch changed or was read for the first time."""
    names = settings().pass_env
    if not names:
        return None
    before = passenv.mode()
    if explicit:
        passenv.set_mode(explicit, by="run")
        return None if before == explicit else f"pass_env is now {explicit.upper()} ({', '.join(names)})."
    if before is None:
        passenv.effective()
        return ("pass_env was never set: it is OFF, so Stella, her teams and the scheduler use your own credentials."
                " `stella pass-env on` switches them to the project ones.")
    return None


def _command(argv: list[str], creds: dict[str, str | None]) -> str:
    # Stella's own session is never a team, whatever the tmux server's environment says.
    unset = "".join(f"unset {k}; " for k in ["STELLA_TEAM", "STELLA_ORDER"] + [k for k, v in creds.items() if v is None])
    return f"export {ENV}=1; {unset}cd ~ && exec " + " ".join(shlex.quote(a) for a in argv)


# ---------------------------------------------------------------- stop


def stop(keep_scheduler: bool = False) -> str:
    """Stop Stella's session (and, unless asked not to, the scheduler). Teams she
    launched keep running in their own tabs; `stella reap` closes finished ones."""
    out = []
    current = running()
    if current:
        try:
            safety.kill(current["pid"], signal.SIGTERM)
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
