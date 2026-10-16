"""Every session on this machine, merged with what Stella launched and why."""

from __future__ import annotations

import datetime as dt
import json
import subprocess

from stella import ledger, passenv, state, tmuxctl
from stella.config import settings


def sessions() -> tuple[list[dict], str | None]:
    try:
        r = subprocess.run([settings().query_bin, "agents", "--json"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return [], str(e)
    if r.returncode != 0:
        return [], (r.stderr or r.stdout).strip()[:300]
    try:
        return json.loads(r.stdout), None
    except json.JSONDecodeError:
        return [], "could not parse `agents --json` output"


def rows() -> tuple[list[dict], str | None]:
    live, err = sessions()
    st = state.fold()
    by_name = {s.get("name"): s for s in live if s.get("name")}
    srv = tmuxctl.find_server()
    out = []
    seen = set()
    now = ledger.now()
    launched = {e.get("team"): e.get("pass_env") for e in ledger.events() if e["type"] in {"launch", "respawned"} and e.get("pass_env")}
    for t in sorted(st.teams.values(), key=lambda t: t.seq, reverse=True):
        if t.status == "done" and t.acked:
            continue
        s = by_name.get(t.name)
        seen.add(t.name)
        win_state = ""
        if srv and t.window:
            win_state = "window closed" if not tmuxctl.window_exists(srv, t.window) else (
                "exited" if tmuxctl.window_dead(srv, t.window) else "open")
        out.append({
            "name": t.name, "launched_by_stella": True, "archetype": t.archetype, "order": t.order,
            "team_status": t.status, "session_status": (s or {}).get("status", "not running"),
            "window": t.window, "window_state": win_state, "cwd": t.directory,
            "age": _age(t.ts, now), "last_report": t.last_report, "pid": (s or {}).get("pid"),
            "credentials": _credentials((s or {}).get("pid"), launched.get(t.name)),
        })
    for s in live:
        if s.get("name") in seen:
            continue
        started = dt.datetime.fromtimestamp(s.get("startedAt", 0) / 1000).astimezone() if s.get("startedAt") else None
        out.append({
            "name": s.get("name") or s.get("sessionId", "")[:8], "launched_by_stella": False,
            "session_status": s.get("status"), "kind": s.get("kind"), "cwd": s.get("cwd"),
            "age": _age(started, now) if started else "", "pid": s.get("pid"),
            "credentials": _credentials(s.get("pid"), None),
        })
    return out, err


def _credentials(pid, launched_with: str | None) -> str:
    """'project' or 'personal', read from the session's own environment (names only, never a value);
    when that can't be read, from how it was launched, marked '(launch)'; else '?'."""
    if not settings().pass_env:
        return ""
    seen = passenv.in_use(pid)
    if seen:
        return seen
    return {"on": "project (launch)", "off": "personal (launch)"}.get(launched_with or "", "?")


def _age(ts, now) -> str:
    s = int((now - ts).total_seconds())
    return f"{s // 60}m" if s < 3600 else f"{s // 3600}h" if s < 86400 else f"{s // 86400}d"


def table(rs: list[dict]) -> str:
    show = any(r.get("credentials") for r in rs)
    lines = [f"{'name':<30} {'by S':<5} {'status':<22} {'age':<5} " + (f"{'token':<18} " if show else "") + "cwd / last report"]
    for r in rs:
        status = r.get("team_status") or ""
        status = f"{status}/{r['session_status']}" if status else str(r.get("session_status"))
        if r.get("window_state"):
            status += f" [{r['window_state']}]"
        tail = r.get("last_report") or r.get("cwd") or ""
        lines.append(f"{r['name'][:30]:<30} {'yes' if r['launched_by_stella'] else '':<5} {status[:22]:<22} {r.get('age', ''):<5} "
                     + (f"{r.get('credentials', ''):<18} " if show else "") + f"{str(tail)[:70]}")
    return "\n".join(lines)
