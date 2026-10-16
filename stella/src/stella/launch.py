"""Launch a team: one interactive Claude session (the lead) in its own tmux window.

The owner can switch to that window and type to the lead directly. The lead may
run its own subagents; Stella only ever talks to the lead.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from stella import ledger, passenv, registry, state, tmuxctl
from stella.config import CALL, settings, store_dir

_NAME = re.compile(r"[^a-z0-9-]+")


def slug(text: str, limit: int = 32) -> str:
    s = _NAME.sub("-", text.lower()).strip("-")
    return (s[:limit].rstrip("-")) or "team"


def lead_prompt(name: str, archetype: str, order_seq: int | None, order_text: str, extra: str = "") -> str:
    owner = settings().owner
    stella = CALL
    order_ref = f"order #{order_seq}" if order_seq else "an order"
    return f"""You are the lead of the team "{name}", launched by Stella, {owner}'s chief of staff, to carry out {order_ref}.

The order, verbatim:
> {order_text}

Archetype: {archetype}.

How this team works:
- Start by running `{stella} context --team` once. It holds the knowledge map and rules you share with Stella; follow them.
- {owner} may type to you directly in this window at any time. Treat that as the highest-priority instruction, above this prompt.
- Messages that start with "[Stella]" come from Stella. Treat them as {owner}'s instructions relayed.
- You may run your own subagents. You are responsible for their work.
- Report milestones: `{stella} report {name} "<one line>"`.
- Work as if you were working with {owner} directly: he reads this window, not the ledger. `{stella} report` only rings a bell and records a line for Stella. It is not how {owner} learns what you need.
- If you need {owner}'s decision or input to continue: run `{stella} report {name} --needs-you "<the question>"`, then END YOUR TURN WITH A MESSAGE THAT STATES THE REQUEST IN FULL, as the last thing in the window: the question, the options with what each costs, your recommendation, and what you will do meanwhile. Never write "I have asked", "I reported it" or "see the report". When {owner} opens the window, that last message alone must tell him what you need from him and why.
- The same holds when you finish: after `{stella} done`, your last message says what was done, where the outputs are, and what is left for {owner}, in full.
- When you launch a subagent, brief it the same way: its final report is read by a person who has not seen its work, so it states its result, its open questions and its recommendation in full, self-contained, with no "as discussed" and no references to context only you hold.
- When the order is complete (or cannot be completed): `{stella} done {name} "<what was done, where the outputs are, anything left open>"`. Do this before you stop.
- Ask {owner} first before anything outward-facing or hard to reverse: posting, pushing, writing to external systems, triggering pipelines, deleting.
{extra}""".rstrip() + "\n"


def write_script(script: Path, name: str, directory: str, mode: str, order_seq: int | None, claude_args: list[str],
                 creds: dict[str, str | None]) -> None:
    """The window's command. pass_env variables that are off are unset here (a tmux server's
    environment may carry them); values that are on come in through tmux -e and never touch disk."""
    s = settings()
    prompt_file = store_dir() / "launch" / f"{name}.prompt.md"
    script.write_text(
        "#!/bin/sh\n"
        f"cd {shlex.quote(directory)} || exit 1\n"
        f"export STELLA_TEAM={shlex.quote(name)}\n"
        + (f"export STELLA_ORDER={order_seq}\n" if order_seq else "")
        + "".join(f"unset {k}\n" for k, v in creds.items() if v is None)
        + f"exec {shlex.quote(s.claude_bin)} --name {shlex.quote(name)} --permission-mode {shlex.quote(mode)}"
        f" --append-system-prompt-file {shlex.quote(str(prompt_file))} {' '.join(shlex.quote(a) for a in claude_args)}\n"
    )
    script.chmod(0o755)


@dataclass
class Launched:
    name: str
    window: str | None
    via: str
    directory: str
    script: Path
    event: dict


def _unique_name(base: str) -> str:
    st = state.fold()
    name, n = base, 2
    reserved = {"stella"}  # Stella's own window
    while name in reserved or (name in st.teams and st.teams[name].status in {"running", "needs-you"}):
        name, n = f"{base}-{n}", n + 1
    return name


def launch(
    archetype: str,
    order_seq: int | None = None,
    text: str | None = None,
    name: str | None = None,
    directory: str | None = None,
    args: str = "",
    permission_mode: str | None = None,
    dry_run: bool = False,
) -> Launched:
    st = state.fold()
    order_text = text or ""
    if order_seq is not None:
        o = st.orders.get(order_seq)
        if not o:
            raise SystemExit(f"no order #{order_seq} in the ledger")
        order_text = text or o.text
    if not order_text:
        raise SystemExit("nothing to do: give --order or a task text")

    teams, _ = registry.load()
    if archetype == "adhoc":
        team = registry.Team(name="adhoc", source="core", base=Path("."), summary="one-off team")
    elif archetype in teams:
        team = teams[archetype]
    else:
        raise SystemExit(f"unknown team {archetype!r}; known: {', '.join(teams)} or 'adhoc'")

    name = _unique_name(slug(name or f"{archetype}-{order_text}"))
    s = settings()
    directory = os.path.expanduser(
        (directory or team.dir or os.getcwd()).format(repos_dir=s.repos_dir)
    )
    mode = permission_mode or team.permission_mode or "default"

    d = store_dir() / "launch"
    d.mkdir(parents=True, exist_ok=True)
    prompt_file = d / f"{name}.prompt.md"
    prompt_file.write_text(lead_prompt(name, archetype, order_seq, order_text, team.raw.get("lead_notes", "")))
    first = registry.first_prompt(team, order_text, args=args, name=name)
    creds = passenv.resolve()
    script = d / f"{name}.sh"
    write_script(script, name, directory, mode, order_seq, [first], creds)
    if dry_run:
        return Launched(name, None, "dry-run", directory, script, {})

    srv = tmuxctl.find_server()
    if not srv and tmuxctl.last_error:
        raise SystemExit(tmuxctl.last_error)
    window = sock = None
    if srv:
        passed = {k: v for k, v in creds.items() if v is not None}
        window = tmuxctl.new_window(srv, name, directory, str(script), env=passed)
        sock, via = srv.socket, f"tmux ({srv.via} server)"
    else:
        env = passenv.apply({**os.environ, "STELLA_TEAM": name, **({"STELLA_ORDER": str(order_seq)} if order_seq else {})})
        subprocess.Popen(
            [s.claude_bin, "--bg", "--name", name, "--permission-mode", mode,
             "--append-system-prompt-file", str(prompt_file), first],
            cwd=directory, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        via = "background session (no tmux server found); reach it with `claude attach " + name + "`"
    ev = ledger.append(
        "launch", by="cli", team=name, archetype=archetype, order=order_seq, dir=directory,
        window=window, socket=sock, via=via, mode=mode, session=os.environ.get("STELLA_SESSION_ID"),
    )
    return Launched(name, window, via, directory, script, ev)


RESPAWN_NOTE = "[Stella] {why} Your conversation was resumed in a fresh process; carry on where you left off."
RESPAWN_GRACE = 120  # seconds the old process's SessionEnd is ignored after a respawn


def _marker(name: str) -> Path:
    return store_dir() / "launch" / f"{name}.respawning"


def _pending(name: str) -> int:
    """How many killed processes of this team have not yet sent their SessionEnd."""
    import time

    p = _marker(name)
    try:
        if time.time() - p.stat().st_mtime >= RESPAWN_GRACE:
            return 0
        return int(p.read_text() or 0)
    except (FileNotFoundError, ValueError):
        return 0


def respawning(name: str) -> bool:
    """True when this SessionEnd comes from a process `respawn` killed on purpose. Each respawn
    expects one such SessionEnd; a later one is a real exit."""
    n = _pending(name)
    if n <= 0:
        _marker(name).unlink(missing_ok=True)
        return False
    if n == 1:
        _marker(name).unlink(missing_ok=True)
    else:
        _marker(name).write_text(str(n - 1))
    return True


def respawn(name: str, why: str) -> str:
    """Restart a running team's lead in its own window, resuming its conversation, with the
    pass_env variables as the switch says now. Its work so far is kept; a tool call in
    flight is interrupted."""
    from stella import run

    st = state.fold()
    t = st.teams.get(name)
    if not t:
        return f"{name}: no such team"
    launch_ev = next((e for e in reversed(list(ledger.events())) if e["type"] == "launch" and e.get("team") == name), {})
    srv = tmuxctl.server_for_socket(launch_ev.get("socket"))
    if not srv or not t.window or not tmuxctl.window_exists(srv, t.window):
        return f"{name}: no open window; not restarted"
    if not run.resumable(t.session_id):
        return f"{name}: no conversation recorded to resume; not restarted"
    creds = passenv.resolve()
    d = store_dir() / "launch"
    script = d / f"{name}.resume.sh"
    directory = launch_ev.get("dir") or t.directory or os.path.expanduser("~")
    write_script(script, name, directory, launch_ev.get("mode") or "default", t.order,
                 ["--resume", t.session_id or "", RESPAWN_NOTE.format(why=why)], creds)
    _marker(name).write_text(str(_pending(name) + 1))
    err = tmuxctl.respawn(srv, t.window, directory, str(script), env={k: v for k, v in creds.items() if v is not None})
    if err:
        respawning(name)  # nothing was killed: take the expectation back
        return f"{name}: tmux could not restart {t.window} ({err}); not restarted"
    ledger.append("respawned", by="cli", team=name, window=t.window, pass_env=passenv.mode(),
                  session=os.environ.get("STELLA_SESSION_ID"))
    return f"{name}: restarted in {t.window}, conversation resumed"


def respawn_all(why: str) -> list[str]:
    st = state.fold()
    return [respawn(t.name, why) for t in st.teams.values() if t.status in {"running", "needs-you"} and t.window]


def background_teams() -> list[str]:
    """Running teams started without tmux: they have no window, so they can't be restarted in place."""
    st = state.fold()
    return [t.name for t in st.teams.values() if t.status in {"running", "needs-you"} and not t.window]
