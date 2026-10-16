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

from stella import daily, ledger, passenv, scheduler, tmuxctl
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


def _argv(fresh: bool, note: str | None = None) -> list[str]:
    s = settings()
    argv = [s.claude_bin, "--name", WINDOW, "--agent", "stella:stella", "--permission-mode", s.permission_mode]
    sid = None if fresh else _load().get("session_id")
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
    sched = scheduler.ensure_daemon()
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    srv = tmuxctl.find_server()
    current = running()
    if current and not fresh:
        if pass_env:
            passenv.set_mode(pass_env, by="run")
            return (f"Stella is already running; pass_env is now {pass_env} for new sessions. To move her and"
                    " running teams onto it: `stella pass-env --respawn`.")
        where = current.get("window") or current.get("pane")
        if interactive and srv and where:
            srv.run("select-window", "-t", where, check=False)
        return f"Stella is already running (pid {current['pid']}{', ' + where if where else ''}). {sched}"
    if current and fresh:
        stop(keep_scheduler=True)
    switched = _set_pass_env(pass_env)
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
    """Started with the shared credentials, everything runs on them; started without, nothing
    does, unless told otherwise. Returns a line to show when that changed the switch."""
    names = settings().pass_env
    if not names:
        return None
    before = passenv.mode()
    m = explicit or passenv.from_environment()
    passenv.set_mode(m, by="run")
    if before == m or explicit:
        return None
    if m == "off":
        return (f"pass_env is now OFF: this terminal has no {', '.join(names)}, so Stella, her teams and the"
                " scheduler use your own credentials. `stella run --pass-env on` keeps them on the shared ones.")
    return f"pass_env is now ON ({', '.join(names)}): Stella, her teams and the scheduler use it."


def _command(argv: list[str], creds: dict[str, str | None]) -> str:
    # Stella's own session is never a team, whatever the tmux server's environment says.
    unset = "".join(f"unset {k}; " for k in ["STELLA_TEAM", "STELLA_ORDER"] + [k for k, v in creds.items() if v is None])
    return f"export {ENV}=1; {unset}cd ~ && exec " + " ".join(shlex.quote(a) for a in argv)


def respawn_self(why: str) -> str:
    """Restart Stella's own session where it runs, resuming her conversation, with the
    pass_env variables as the switch says now. The restart kills everything in her pane,
    including this process when she is the caller, so a detached helper does it a moment
    later, after this command has printed and returned."""
    current = running()
    if not current:
        return "Stella: not running; `stella run` will start her on the current setting."
    where = current.get("window") or current.get("pane")
    srv = tmuxctl.find_server()
    sid = _load().get("session_id")
    if not srv or not where or not resumable(sid):
        return "Stella: can't restart her in place (no tmux pane or conversation recorded); `stella stop`, then `stella run`."
    passenv.resolve()  # fail here, where it can be seen, not in the helper
    log = store_dir() / "runs" / "respawn-self.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as out:
        subprocess.Popen([str(BIN), "respawn-self", why], stdin=subprocess.DEVNULL, stdout=out,
                         stderr=subprocess.STDOUT, start_new_session=True)
    return f"Stella: restarting in {where} in a moment, conversation resumed"


def respawn_self_now(why: str) -> None:
    import time

    time.sleep(1.5)  # let the caller finish its turn's output
    current = running()
    where = current and (current.get("window") or current.get("pane"))
    srv = tmuxctl.find_server()
    if not where or not srv:
        print(f"{ledger.now():%Y-%m-%d %H:%M} Stella not running in a pane; nothing restarted", flush=True)
        return
    creds = passenv.resolve()
    note = f"[Stella-restart] {why} Your conversation was resumed in a fresh process."
    argv = _argv(False, note=note)
    from stella import wake  # here: wake imports this module

    wake.expect(note)  # so her prompt hook knows the note as a system note, not an order
    err = tmuxctl.respawn(srv, where, os.path.expanduser("~"), _command(argv, creds),
                          env={k: v for k, v in creds.items() if v is not None})
    if err:
        ledger.append("alert", by="cli", key="stella:respawn", text=f"could not restart Stella in {where}: {err}")
        return
    time.sleep(0.5)
    pid = srv.run("display-message", "-p", "-t", where, "#{pane_pid}", check=False).stdout.strip()
    _update(pid=int(pid) if pid.isdigit() else None, socket=srv.socket)  # a respawn must keep the wake line's target
    ledger.append("respawned", by="cli", team=WINDOW, window=where, pass_env=passenv.mode())


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
