"""Find the right tmux server and open windows in it.

No socket name is ever hard-coded. The server is, in order: the caller's own
(`$TMUX`), else tmux's default socket. Stella never starts a server: one spawned
from an agent would inherit the wrong application's file permissions.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from stella.config import settings


@dataclass
class Server:
    args: list[str]  # e.g. ["tmux", "-S", "/path"] or ["tmux"]
    socket: str
    via: str  # "caller" | "default"

    def run(self, *a: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run([*self.args, *a], capture_output=True, text=True, check=check)


SANDBOXED = (
    "This shell may not connect to tmux (\"Operation not permitted\"): the session's command sandbox"
    " blocks it. Ask the owner to allow the `stella` command in their sandbox's tool allowlist; until"
    " then, the owner can run `~/.local/bin/stella launch …` or `stella run` in a terminal."
)
last_error: str | None = None


def _alive(args: list[str]) -> bool:
    global last_error
    try:
        r = subprocess.run([*args, "list-sessions"], capture_output=True, text=True)
    except FileNotFoundError:
        return False
    if r.returncode != 0 and "not permitted" in r.stderr:
        last_error = SANDBOXED
    return r.returncode == 0


def find_server() -> Server | None:
    tm = os.environ.get("TMUX", "")
    if tm:
        sock = tm.split(",", 1)[0]
        args = ["tmux", "-S", sock]
        if _alive(args):
            return Server(args, sock, "caller")
    if _alive(["tmux"]):
        sock = subprocess.run(["tmux", "display-message", "-p", "#{socket_path}"], capture_output=True, text=True).stdout.strip()
        return Server(["tmux"], sock, "default")
    return None


def server_for_socket(sock: str | None) -> Server | None:
    if sock and _alive(["tmux", "-S", sock]):
        return Server(["tmux", "-S", sock], sock, "recorded")
    return find_server()


def ensure_session(srv: Server, name: str | None = None) -> str:
    name = name or settings().tmux_session
    if srv.run("has-session", "-t", f"={name}", check=False).returncode != 0:
        srv.run("new-session", "-d", "-s", name)
    return name


def new_window(srv: Server, name: str, directory: str, command: str, env: dict[str, str] | None = None) -> str:
    """Open a background window; returns its window id (e.g. '@12').

    `env` is set in the window's environment only (tmux -e), never written to disk.
    """
    session = ensure_session(srv)
    env_args = [a for k, v in (env or {}).items() for a in ("-e", f"{k}={v}")]
    out = srv.run(
        "new-window", "-d", "-P", "-F", "#{window_id}", "-t", f"={session}:", "-n", name, "-c", directory,
        *env_args, command,
    ).stdout.strip()
    srv.run("set-option", "-w", "-t", out, "remain-on-exit", "on", check=False)
    return out


def window_exists(srv: Server, window: str) -> bool:
    r = srv.run("list-windows", "-a", "-F", "#{window_id} #{window_name}", check=False)
    return any(line.split(" ", 1)[0] == window or line.split(" ", 1)[-1] == window for line in r.stdout.splitlines())


def find_window(srv: Server, name: str) -> str | None:
    r = srv.run("list-windows", "-a", "-F", "#{window_id}\t#{window_name}\t#{pane_dead}", check=False)
    for line in r.stdout.splitlines():
        wid, wname, _ = (line.split("\t") + ["", ""])[:3]
        if wname == name:
            return wid
    return None


def window_dead(srv: Server, window: str) -> bool:
    r = srv.run("list-panes", "-t", window, "-F", "#{pane_dead}", check=False)
    return r.returncode != 0 or r.stdout.strip().startswith("1")


def send_text(srv: Server, window: str, text: str) -> None:
    text = " ".join(text.split())
    srv.run("send-keys", "-t", window, "-l", text)
    srv.run("send-keys", "-t", window, "Enter")


def server_app(srv: Server) -> str:
    r = srv.run("show-environment", "-g", "__CFBundleIdentifier", check=False)
    return r.stdout.strip().partition("=")[2]
