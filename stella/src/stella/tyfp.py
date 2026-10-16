"""`tyfp`: the owner's explicit sweep across every session. `gg` wraps up only the session it is typed in; `tyfp` wraps up
every session that is done.

Typed alone (any case, trimmed) in any session in the Stella tmux server, handled by the prompt hook so the prompt never reaches
the model. For every Stella-managed or adopted session it applies the `gg` blockers (unpushed commits, uncommitted changes, a
deferred push, an open question, a follow-up waiting, needs-you) and wraps up each one that is clean and idle. No grace period,
and `keep_open` and adopted sessions count: the word is explicit. It never touches a session that is busy, running, blocked, or
Stella's own. The session it was typed in goes last, if clean, a few seconds after the report is delivered.

The result is ONE report: `wrapped up: <names>`, then `left open: <name>: <reason>` for each. A session whose only blocker is an
unpushed commit also gets its push raised through Claude Code's prompt (the typing session runs the push; never a command for
the owner). The same code serves `stella sweep --now`.

A hook cannot reach tmux (its sandbox), so then it queues the request and the scheduler runs it (`process_requests`), the way it
closes windows for `gg`; the hook waits for the result for a few seconds.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from stella import ledger, state, status, tmuxctl, wrapup
from stella.config import BIN, store_dir

WAIT = 25  # seconds the hook waits for the scheduler's report (the hook's own timeout is 30)
_WORD = re.compile(r"^tyfp$", re.I)


def is_tyfp(prompt: str) -> bool:
    return bool(_WORD.match((prompt or "").strip()))


@dataclass
class Report:
    wrapped: list[str] = field(default_factory=list)
    left: list[tuple[str, str]] = field(default_factory=list)
    pushes: list[str] = field(default_factory=list)  # push commands whose prompt the typing session raises

    def text(self) -> str:
        lines = ["wrapped up: " + (", ".join(self.wrapped) if self.wrapped else "nothing")]
        lines += [f"left open: {n}: {r}" for n, r in self.left]
        return "\n".join(lines)


def _one_line(reason: str) -> str:
    return " ".join(reason.split())[:160]


def run(sock: str | None, typed: dict | None = None, dry_run: bool = False, delay: float = 3) -> Report:
    """Sweep every session now. `typed` identifies the session the word was typed in (pane, claude_pid, sid, cwd, team), or None."""
    st = state.fold()
    now = ledger.now()
    rep = Report()
    srv = tmuxctl.server_for_socket(sock) if sock else tmuxctl.find_server()
    typed_team = None
    if typed:
        typed_team = st.teams.get(typed.get("team") or "") or state.team_for_session(st, typed.get("sid") or "")
    gone = wrapup.gone_teams(st)
    for t in sorted(st.teams.values(), key=lambda t: t.seq):
        if t.acked or t is typed_team:
            continue
        v = wrapup.evaluate_team(st, t, set(), now, gone=t.name in gone, explicit=True)
        if not v.ok:
            rep.left.append((t.name, _one_line(v.reason)))
            if v.push_only:
                rep.pushes += [b.command for b in v.blockers if b.command]
            continue
        if dry_run:
            rep.wrapped.append(t.name)
            continue
        if v.gone or not t.window:  # nothing to close
            ledger.append("ack", by="owner", key=f"team:{t.name}:{t.status}")
            ledger.append("reaped", by="owner", team=t.name)
            wrapup.finish_wrap(st, t, "owner", v.checked, record_reap=False)
            rep.wrapped.append(t.name)
            continue
        window = wrapup.window_of(srv, t) if srv else None
        if not window:
            rep.left.append((t.name, "its window does not look like its own; left alone"))
            continue
        srv.run("kill-window", "-t", window, check=False)
        if tmuxctl.window_exists(srv, window):
            rep.left.append((t.name, f"window {window} did not close"))
            continue
        wrapup.finish_wrap(st, t, "owner", v.checked)
        rep.wrapped.append(t.name)
    _typed_in_last(st, now, srv, typed, typed_team, rep, dry_run, delay)
    return rep


def _typed_in_last(st, now, srv, typed, typed_team, rep: Report, dry_run: bool, delay: float) -> None:
    if not typed or typed.get("own"):
        return  # Stella's own session is never wrapped up
    name = typed_team.name if typed_team else "this session"
    if typed_team:
        v = wrapup.evaluate_team(st, typed_team, set(), now, explicit=True, typed_in=True)
        bl, why = v.blockers, v.reason
        ok = v.ok
    else:
        bl = status.blockers(st, typed.get("sid") or "", typed.get("cwd") or "", own=False, t=None)
        ok, why = not bl, "; ".join(b.text for b in bl)
    if not ok:
        rep.left.append((name, _one_line(why)))
        if bl and all(b.kind == "push" for b in bl):
            rep.pushes += [b.command for b in bl if b.command]
        return
    pane = wrapup.verify_pane(srv, typed) if srv else "tmux is not reachable"
    if isinstance(pane, str):
        rep.left.append((name, _one_line(pane)))
        return
    if dry_run:
        rep.wrapped.append(name)
        return
    if typed_team:
        wrapup.finish_wrap(st, typed_team, "owner", v.checked)
    subprocess.Popen([str(BIN), "wrapup", "--close-window", f"{srv.socket}|{pane['window_id']}", "--delay", f"{delay:g}"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    rep.wrapped.append(name)


# ---------------------------------------------------------------- when the session cannot reach tmux


def _dir() -> Path:
    return store_dir() / "tyfp"


def ask(req: dict) -> dict | None:
    """Queue the request for the scheduler and wait for its report. None when the scheduler does not answer in time."""
    d = _dir()
    d.mkdir(parents=True, exist_ok=True)
    key = re.sub(r"[^A-Za-z0-9]", "_", f"{req['sock']}{req['pane']}{req['sid']}")
    out = d / f"{key}.result"
    out.unlink(missing_ok=True)
    (d / f"{key}.json").write_text(json.dumps({**req, "ts": time.time()}))
    end = time.monotonic() + WAIT
    while time.monotonic() < end:
        if out.exists():
            try:
                res = json.loads(out.read_text())
            except ValueError:
                time.sleep(0.2)
                continue
            out.unlink(missing_ok=True)
            return res
        time.sleep(0.3)
    (d / f"{key}.json").unlink(missing_ok=True)
    return None


def process_requests() -> None:
    """Scheduler side: run each fresh request and leave its report for the waiting hook."""
    for f in sorted(_dir().glob("*.json")):
        try:
            req = json.loads(f.read_text())
        except (OSError, ValueError):
            req = None
        f.unlink(missing_ok=True)
        if not req or time.time() - req.get("ts", 0) > wrapup.REQUEST_STALE:
            continue
        rep = run(req["sock"], req, delay=3)
        f.with_suffix(".result").write_text(json.dumps({"text": rep.text(), "pushes": rep.pushes}))
