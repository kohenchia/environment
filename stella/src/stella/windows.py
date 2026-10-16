"""Every Claude session in the tmux server, found by looking at the panes, and restarted in place.

`stella pass-env on|off --respawn` has to move all ongoing sessions onto the new credentials, not just
the ones the ledger knows. So a session is found the way the owner would find it, from the panes:

    tmux pane  ->  its process tree  ->  a `claude` process  ->  `claude agents --json`: session id, cwd, name

and then told apart by what it is:

    stella   Stella's own session: `--agent stella:stella`, or the pane her state file records
    team     a launched team's lead: its `--name` (or window name) is a team in the ledger
    other    anything else the owner opened or resumed by hand

A window is skipped only with a stated reason (no session id readable, nothing to resume). The
restart is `tmux respawn-pane -k` of that pane running `claude --resume <id>`: the conversation is
kept, a tool call in flight is interrupted. The process that kills the caller's own pane, and Stella's
pane, are restarted last by a detached helper after this command has printed and returned, so `tok`
works from inside Stella's own session.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from stella import fleet, ledger, passenv, run, state, tmuxctl
from stella.config import BIN, settings, store_dir

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_INTERPRETERS = {"sh", "bash", "zsh", "dash", "env", "node", "python", "python3"}
# Flags worth carrying over when an unknown (hand-opened) session is restarted; each takes one value.
_KEEP_WITH_VALUE = ("--name", "--model", "--permission-mode", "--agent", "--append-system-prompt-file")
_KEEP_FLAGS = ("--dangerously-skip-permissions",)
LATE_DELAY = 1.5  # seconds the detached helper waits, so the caller finishes its output first


@dataclass
class Target:
    window_id: str
    window_name: str
    pane_id: str
    pane_pid: int
    cwd: str
    argv: list[str] = field(default_factory=list)
    kind: str = "other"  # stella | team | other
    team: str | None = None
    agent_name: str | None = None
    session_id: str | None = None
    late: bool = False  # restarted by the detached helper, after everything else

    @property
    def label(self) -> str:
        return "Stella" if self.kind == "stella" else self.team or self.agent_name or self.window_name or self.pane_id


# ------------------------------------------------------------ discovery


def _procs() -> dict[int, tuple[int, list[str]]]:
    """pid -> (ppid, argv) for every process."""
    try:
        r = subprocess.run(["ps", "-axo", "pid=,ppid=,command="], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    out = {}
    for line in r.stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            out[int(parts[0])] = (int(parts[1]), parts[2].split())
    return out


def _is_claude(argv: list[str]) -> bool:
    if not argv:
        return False
    exe = os.path.basename(argv[0])
    if exe in _INTERPRETERS and len(argv) > 1:
        exe = os.path.basename(argv[1])  # `sh claude-x ...`: a script standing in for the binary
    return exe == "claude" or exe.startswith("claude-")


def _descendants(root: int, procs) -> list[int]:
    kids: dict[int, list[int]] = {}
    for pid, (ppid, _) in procs.items():
        kids.setdefault(ppid, []).append(pid)
    out, todo = [], [root]
    while todo:
        p = todo.pop(0)
        out.append(p)
        todo += sorted(kids.get(p, []))
    return out


def _flag(argv: list[str], *names: str) -> str | None:
    for i, a in enumerate(argv[:-1]):
        if a in names:
            return argv[i + 1]
        for n in names:
            if a.startswith(n + "="):
                return a.split("=", 1)[1]
    return None


def _panes(srv) -> list[dict]:
    fmt = "\t".join(f"#{{{k}}}" for k in ("window_id", "window_name", "pane_id", "pane_pid", "pane_current_path", "pane_dead", "@sidebar"))
    r = srv.run("list-panes", "-a", "-F", fmt, check=False)
    out = []
    for line in r.stdout.splitlines():
        f = (line.split("\t") + [""] * 7)[:7]
        if f[6] == "1" or f[5] == "1" or not f[3].isdigit():  # the sidebar, a dead pane
            continue
        out.append({"window_id": f[0], "window_name": f[1], "pane_id": f[2], "pane_pid": int(f[3]), "cwd": f[4]})
    return out


def discover(srv, with_agents: bool = True, procs=None) -> list[Target]:
    """Every pane that runs Claude, classified; panes with nothing of Claude in them are left out.
    `with_agents` asks `claude agents` for session ids and cwds (not needed to tell what is alive)."""
    procs = procs if procs is not None else _procs()
    live = fleet.sessions()[0] if with_agents else []
    by_pid = {a["pid"]: a for a in live if a.get("pid")}
    st = state.fold()
    me = run._load()
    caller = os.environ.get("TMUX_PANE", "")
    found = []
    for p in _panes(srv):
        tree = _descendants(p["pane_pid"], procs)
        claudes = [pid for pid in tree if pid in procs and _is_claude(procs[pid][1])]
        if not claudes:
            continue
        argv = procs[claudes[0]][1]
        agent = next((by_pid[pid] for pid in claudes if pid in by_pid), None)
        t = Target(p["window_id"], p["window_name"], p["pane_id"], p["pane_pid"], (agent or {}).get("cwd") or p["cwd"],
                   argv=argv, agent_name=(agent or {}).get("name") or _flag(argv, "--name"))
        sid = (agent or {}).get("sessionId") or _flag(argv, "--resume", "-r", "--session-id")
        t.session_id = sid if sid and _UUID.match(sid) else None
        _classify(t, st, me, srv)
        t.late = t.kind == "stella" or (bool(caller) and caller == t.pane_id)
        found.append(t)
    return found


def _classify(t: Target, st, me: dict, srv) -> None:
    if "stella:stella" in t.argv or (me.get("pane") == t.pane_id and me.get("socket") == srv.socket):
        t.kind, t.team = "stella", None
        t.session_id = t.session_id or me.get("session_id")
        return
    for key in (_flag(t.argv, "--name"), t.agent_name, t.window_name):
        if key and key in st.teams:
            t.kind, t.team = "team", key
            t.session_id = t.session_id or st.teams[key].session_id
            return


def live_teams(srv=None) -> set[str] | None:
    """The names of the teams that still have a lead alive in a tmux pane (by its `--name` or its window's
    name, whatever the window is called) or a window of that name. None when that cannot be told: no tmux server reachable from here, or
    the process list unreadable. Never guesses a team is gone."""
    srv = srv or tmuxctl.find_server() or tmuxctl.server_for_socket(run._load().get("socket"))
    procs = _procs()
    if not srv or not procs:
        return None
    names = {t.team for t in discover(srv, with_agents=False, procs=procs) if t.team}
    # A lead that has ended leaves the owner's shell in its window (see launch.write_script): the window is
    # not gone. Matched by name only: window ids are reused after a tmux restart, so an old id proves nothing.
    return names | {p["window_name"] for p in _panes(srv)}


# ------------------------------------------------------------ restart


def _resume_script(t: Target, why: str, creds: dict[str, str | None]) -> Path:
    from stella import launch

    s = settings()
    keep: list[str] = []
    for i, a in enumerate(t.argv[:-1]):
        if a in _KEEP_WITH_VALUE:
            keep += [a, t.argv[i + 1]]
    keep += [a for a in t.argv if a in _KEEP_FLAGS]
    if "--permission-mode" not in keep:
        keep += ["--permission-mode", s.permission_mode]
    script = store_dir() / "launch" / f"resume-{re.sub(r'[^A-Za-z0-9_.-]', '_', t.label)}.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "#!/bin/sh\n"
        f"cd {shlex.quote(t.cwd)} || exit 1\n"
        + "".join(f"unset {k}\n" for k, v in creds.items() if v is None)
        + f"{shlex.quote(s.claude_bin)} {' '.join(shlex.quote(a) for a in keep)} --resume {shlex.quote(t.session_id or '')} {shlex.quote(launch.RESPAWN_NOTE.format(why=why))}\n"
        'rc=$?\n'
        'if [ "$rc" -ne 0 ]; then printf "\\n[stella] claude exited with status %s.\\n" "$rc"; fi\n'
        'printf "\\n[stella] claude ended. This is your shell in %s: run things, or `claude --resume` to go on.\\n" "$PWD"\n'
        'exec "${SHELL:-/bin/sh}" -l\n'
    )
    script.chmod(0o755)
    return script


def skip_reason(t: Target) -> str | None:
    """Why this target cannot be restarted, or None."""
    if not t.session_id:
        return "no session id could be read from its Claude process"
    if not run.resumable(t.session_id):
        return "its conversation has no transcript yet, so there is nothing to resume"
    return None


def restart(srv, t: Target, why: str) -> str:
    """Restart one target in its pane; returns one line saying what happened."""
    from stella import launch

    if reason := skip_reason(t):
        return f"{t.label} ({t.window_name}): skipped, {reason}"
    creds = passenv.resolve()
    env = {k: v for k, v in creds.items() if v is not None}
    where = f"{t.window_name} {t.pane_id}"
    if t.kind == "stella":
        note = f"[Stella-restart] {why} Your conversation was resumed in a fresh process."
        from stella import wake  # here: wake imports run

        wake.expect(note)  # so her prompt hook knows the note as a system note, not an order
        err = tmuxctl.respawn(srv, t.pane_id, os.path.expanduser("~"), run._command(run._argv(False, note=note, sid=t.session_id), creds), env=env)
        if err:
            ledger.append("alert", by="cli", key="stella:respawn", text=f"could not restart Stella in {where}: {err}")
            return f"Stella: tmux could not restart {where} ({err}); not restarted"
        time.sleep(0.5)
        pid = srv.run("display-message", "-p", "-t", t.pane_id, "#{pane_pid}", check=False).stdout.strip()
        run._update(pid=int(pid) if pid.isdigit() else None, pane=t.pane_id, window=t.window_id, socket=srv.socket)
        ledger.append("respawned", by="cli", team=run.WINDOW, window=t.window_id, pass_env=passenv.mode())
        return f"Stella: restarted in {where}, conversation resumed"
    if t.kind == "team":
        return launch.respawn_team(srv, t.team, t.pane_id, t.session_id, why, creds, label=where)
    err = tmuxctl.respawn(srv, t.pane_id, t.cwd, str(_resume_script(t, why, creds)), env=env)
    if err:
        return f"{t.label} ({t.window_name}): tmux could not restart {t.pane_id} ({err}); not restarted"
    ledger.append("respawned", by="cli", team=None, window=t.window_id, pass_env=passenv.mode(), name=t.label)
    return f"{t.label}: restarted in {where}, conversation resumed"


def restart_all(why: str, only_teams: list[str] | None = None) -> list[str]:
    """Restart every Claude session in the tmux server (or only the named teams). Returns the report lines."""
    st = state.fold()
    lines: list[str] = []
    if only_teams:
        lines = [f"{n}: no such team" for n in only_teams if n not in st.teams]
        only_teams = [n for n in only_teams if n in st.teams]
        if not only_teams:
            return lines
    srv = tmuxctl.find_server() or tmuxctl.server_for_socket(run._load().get("socket"))
    if not srv:
        return lines + [tmuxctl.last_error or "No tmux server found: nothing restarted."]
    passenv.resolve()  # fail here, where it can be seen, not halfway
    targets = discover(srv)
    if only_teams:
        for name in only_teams:
            t = next((x for x in targets if x.team == name), None)
            if not t:
                lines.append(f"{name}: no open window; not restarted")
            else:
                lines.append(restart(srv, t, why))
        return lines
    for t in targets:
        if not t.late:
            lines.append(restart(srv, t, why))
    for name in sorted(n for n, tm in st.teams.items() if tm.status in {"running", "needs-you"} and tm.window):
        if not any(x.team == name for x in targets):
            lines.append(f"{name}: no window or process any more (gone); nothing to restart")
    late = []
    for t in (x for x in targets if x.late):
        if skip_reason(t):
            lines.append(restart(srv, t, why))  # says why, at once
        else:
            late.append(t)
    if late:
        _later(srv, late, why)
        lines += [f"{t.label}: restarting in {t.window_name} {t.pane_id} in a moment, conversation resumed"
                  + (" (last: it is where this command runs)" if t.kind != "stella" else "") for t in late]
    elif not any(t.kind == "stella" for t in targets):
        lines.append("Stella: no session of hers found in any pane; `stella run` will start her on the current setting")
    return lines


def _later(srv, late: list[Target], why: str) -> None:
    """Hand the last restarts to a detached helper: they kill the process that asked (Stella's pane, or the
    caller's own), so they happen after this command has printed and returned. Stella's pane goes last."""
    late = sorted(late, key=lambda t: t.kind == "stella")
    plan = store_dir() / "launch" / "respawn-later.json"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(json.dumps({"socket": srv.socket, "why": why, "targets": [asdict(t) for t in late]}))
    log = store_dir() / "runs" / "respawn-self.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as out:
        subprocess.Popen([str(BIN), "respawn-self", why, "--plan", str(plan)], stdin=subprocess.DEVNULL, stdout=out,
                         stderr=subprocess.STDOUT, start_new_session=True)


def run_plan(plan: Path) -> None:
    """The detached helper: restart what `_later` left, in order."""
    time.sleep(LATE_DELAY)
    d = json.loads(plan.read_text())
    srv = tmuxctl.server_for_socket(d.get("socket"))
    if not srv:
        print(f"{ledger.now():%Y-%m-%d %H:%M} no tmux server at {d.get('socket')}; nothing restarted", flush=True)
        return
    for raw in d["targets"]:
        print(f"{ledger.now():%Y-%m-%d %H:%M} {restart(srv, Target(**raw), d['why'])}", flush=True)


def background_teams() -> list[str]:
    """Running teams started without tmux: they have no window, so they can't be restarted in place."""
    return [t.name for t in state.fold().teams.values() if t.status in {"running", "needs-you"} and not t.window]
