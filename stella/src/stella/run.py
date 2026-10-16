"""`stella run`: Stella's own session, where every message is to her.

Typed in a terminal, it starts the scheduler in the background, then runs Stella
right there (renaming the tmux window to `stella`), or switches to her window if
she is already running. Called by an agent, it opens her window in the background.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys

from stella import scheduler, tmuxctl
from stella.config import settings, store_dir

WINDOW = "stella"
ENV = "STELLA_SELF"  # set in Stella's own session; the hooks treat every message there as addressed


def is_self() -> bool:
    return os.environ.get(ENV) == "1"


def _file():
    return store_dir() / "stella-session.json"


def remember_session(session_id: str) -> None:
    _file().write_text(json.dumps({"session_id": session_id}))


def last_session() -> str | None:
    for p in (_file(), store_dir() / "hq.json"):  # hq.json: the name before 2026-10-16
        try:
            return json.loads(p.read_text()).get("session_id")
        except (FileNotFoundError, json.JSONDecodeError):
            continue
    return None


def _argv(fresh: bool) -> list[str]:
    s = settings()
    argv = [s.claude_bin, "--name", WINDOW, "--agent", "stella:stella", "--permission-mode", s.permission_mode]
    sid = None if fresh else last_session()
    if sid:
        argv += ["--resume", sid]
    return argv


def _exec_here(argv: list[str]) -> None:
    os.environ[ENV] = "1"
    os.chdir(os.path.expanduser("~"))
    os.execvp(argv[0], argv)


def run(fresh: bool = False) -> str:
    store_dir().mkdir(parents=True, exist_ok=True)
    sched = scheduler.ensure_daemon()
    argv = _argv(fresh)
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    srv = tmuxctl.find_server()
    w = tmuxctl.find_window(srv, WINDOW) if srv else None
    alive = bool(w and not tmuxctl.window_dead(srv, w))
    if alive and not fresh:
        if interactive:
            srv.run("select-window", "-t", w, check=False)
        return f"Stella is already running in window {w}. {sched}"
    if w:
        srv.run("kill-window", "-t", w, check=False)
    if interactive:
        print(sched)
        if srv and os.environ.get("TMUX"):
            pane = os.environ.get("TMUX_PANE", "")
            srv.run("rename-window", *(["-t", pane] if pane else []), WINDOW, check=False)
        _exec_here(argv)
    if not srv:
        return tmuxctl.last_error or "No tmux server is running: run `stella run` in a terminal."
    cmd = f"export {ENV}=1; cd ~ && exec " + " ".join(shlex.quote(a) for a in argv)
    w = tmuxctl.new_window(srv, WINDOW, os.path.expanduser("~"), cmd)
    return f"Opened Stella in window {w}. {sched}"
