"""Adopting a session the owner started by hand in the Stella tmux server.

A Claude session in that server that is not in the ledger (opened or resumed by hand, such as a review window) is
registered under its window name as a team of archetype `adopted`, so `stella tell`, `stella fleet`, `stella pass-env
--respawn`, `gg` and `stella wrapup <team>` treat it like a launched one. An adopted team is never closed by the
automatic sweep (`stella sweep`); only `gg` or the owner's explicit word closes it.

The prompt hook asks for the adoption on a session's first prompt. A hook runs in the session's command sandbox, which
cannot reach tmux, so the window and name are read from the session's own file (`direct`); only if that fails is the request
queued for the scheduler (`process_requests`), the explicit last resort.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from stella import ledger, state, tmuxctl
from stella.config import store_dir

ARCHETYPE = "adopted"
STALE = 300  # seconds a queued request stays valid
_NAME = re.compile(r"[^a-z0-9-]+")


def _queue_dir() -> Path:
    return store_dir() / "adopt"


def known(st: state.State, sid: str) -> state.Team | None:
    return state.team_for_session(st, sid)


def register(st: state.State, sid: str, cwd: str, sock: str, window: str, wname: str) -> str:
    """Write the ledger events that make the session in `window` a team. Returns the team's name."""
    base = _NAME.sub("-", (wname or "").lower()).strip("-")[:32].rstrip("-") or "session"
    if base == "stella":
        base = "stella-session"
    same = st.teams.get(base)
    if same and same.window == window and not same.acked:  # resumed in the window it already had: a new session id
        ledger.append("started", by="hook", team=base, session=sid)
        return base
    name, n = base, 2
    while name in st.teams and st.teams[name].status in {"running", "needs-you"} and not st.teams[name].acked:
        name, n = f"{base}-{n}", n + 1
    ledger.append("launch", by="adopt", team=name, archetype=ARCHETYPE, order=None, dir=cwd, window=window, socket=sock,
                  via="adopted: started by hand")
    ledger.append("started", by="hook", team=name, session=sid)
    return name


def adopt(sid: str, cwd: str, sock: str, pane: str, claude_pid: int | None) -> str | None:
    """Register the calling session, now: through tmux if it can be reached from here, else from its session file; queued for the scheduler only as a last resort."""
    st = state.fold()
    if not sid or known(st, sid):
        return None
    srv = tmuxctl.Server(["tmux", "-S", sock], sock, "caller")
    out = srv.run("display-message", "-p", "-t", pane, "#{window_id}\t#{window_name}", check=False).stdout.strip()
    if "\t" in out:
        wid, wname = out.split("\t", 1)
        return register(st, sid, cwd, sock, wid, wname)
    from stella import direct

    me = direct.of_pid(claude_pid, sid)  # a hook's sandbox: the session file names the window and the session
    if not isinstance(me, str) and me.window and me.name:
        return register(st, sid, cwd, sock, me.window, me.name)
    d = _queue_dir()  # last resort: the scheduler registers it
    d.mkdir(parents=True, exist_ok=True)
    (d / (re.sub(r"[^A-Za-z0-9]", "_", sock + pane) + ".json")).write_text(json.dumps(
        {"sock": sock, "pane": pane, "sid": sid, "cwd": cwd, "claude_pid": claude_pid, "ts": time.time()}))
    return None


def process_requests() -> list[str]:
    """Scheduler side: register each queued session, after checking that the pane still holds that very session."""
    from stella import wrapup

    out = []
    for f in sorted(_queue_dir().glob("*.json")):
        try:
            req = json.loads(f.read_text())
        except (OSError, ValueError):
            req = None
        f.unlink(missing_ok=True)
        if not req or time.time() - req.get("ts", 0) > STALE:
            continue
        srv = tmuxctl.Server(["tmux", "-S", req["sock"]], req["sock"], "recorded")
        ident = wrapup.verify_pane(srv, req)
        if isinstance(ident, str):
            continue  # not that session any more: adopt nothing
        pane = ident
        wname = srv.run("display-message", "-p", "-t", pane["pane_id"], "#{window_name}", check=False).stdout.strip()
        st = state.fold()
        if known(st, req["sid"]):
            continue
        out.append(register(st, req["sid"], req["cwd"], req["sock"], pane["window_id"], wname))
    return out
