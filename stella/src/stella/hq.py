"""HQ: the persistent session where every message is to Stella."""

from __future__ import annotations

import json
import os
import shlex
import sys

from stella import tmuxctl
from stella.config import BIN, settings, store_dir

WINDOW = "stella"
CRON = "stella-cron"


def _hq_file():
    return store_dir() / "hq.json"


def remember_session(session_id: str) -> None:
    _hq_file().write_text(json.dumps({"session_id": session_id}))


def last_session() -> str | None:
    try:
        return json.loads(_hq_file().read_text()).get("session_id")
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def command(fresh: bool) -> str:
    s = settings()
    parts = [s.claude_bin, "--name", WINDOW, "--agent", "stella:stella", "--permission-mode", s.hq_permission_mode]
    sid = None if fresh else last_session()
    if sid:
        parts += ["--resume", sid]
    return "export STELLA_HQ=1; exec " + " ".join(shlex.quote(p) for p in parts)


def ensure_scheduler(srv) -> str:
    w = tmuxctl.find_window(srv, CRON)
    if w and not tmuxctl.window_dead(srv, w):
        return w
    if w:
        srv.run("kill-window", "-t", w, check=False)
    return tmuxctl.new_window(srv, CRON, str(store_dir()), f"{shlex.quote(str(BIN))} scheduler")


def open_hq(fresh: bool = False, here: bool = False) -> str:
    store_dir().mkdir(parents=True, exist_ok=True)
    cmd = command(fresh)
    if here:
        os.execvp("sh", ["sh", "-c", cmd])
    srv = tmuxctl.find_server()
    if not srv and tmuxctl.last_error:
        return tmuxctl.last_error
    if not srv:
        return "No tmux server is running. Start one from your terminal (your usual tmux entry point), then run `stella hq` inside it, or run `stella hq --here`."
    cron = ensure_scheduler(srv)
    w = tmuxctl.find_window(srv, WINDOW)
    if w and not tmuxctl.window_dead(srv, w) and not fresh:
        msg = f"HQ is already open in window {w}."
    else:
        if w:
            srv.run("kill-window", "-t", w, check=False)
        w = tmuxctl.new_window(srv, WINDOW, os.path.expanduser("~"), cmd)
        msg = f"Opened HQ in window {w}."
    if sys.stdin.isatty():
        srv.run("select-window", "-t", w, check=False)
    return msg + f" Scheduler window: {cron}."
