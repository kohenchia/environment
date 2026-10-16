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

from stella import ledger, registry, state, tmuxctl
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
- If you need {owner}'s decision or input to continue: `{stella} report {name} --needs-you "<the question>"`, then wait.
- When the order is complete (or cannot be completed): `{stella} done {name} "<what was done, where the outputs are, anything left open>"`. Do this before you stop.
- Ask {owner} first before anything outward-facing or hard to reverse: posting, pushing, writing to external systems, triggering pipelines, deleting.
{extra}""".rstrip() + "\n"


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
    script = d / f"{name}.sh"
    script.write_text(
        "#!/bin/sh\n"
        f"cd {shlex.quote(directory)} || exit 1\n"
        f"export STELLA_TEAM={shlex.quote(name)}\n"
        + (f"export STELLA_ORDER={order_seq}\n" if order_seq else "")
        + f"exec {shlex.quote(s.claude_bin)} --name {shlex.quote(name)} --permission-mode {shlex.quote(mode)}"
        f" --append-system-prompt-file {shlex.quote(str(prompt_file))} {shlex.quote(first)}\n"
    )
    script.chmod(0o755)
    if dry_run:
        return Launched(name, None, "dry-run", directory, script, {})

    srv = tmuxctl.find_server()
    if not srv and tmuxctl.last_error:
        raise SystemExit(tmuxctl.last_error)
    window = sock = None
    if srv:
        window = tmuxctl.new_window(srv, name, directory, str(script))
        sock, via = srv.socket, f"tmux ({srv.via} server)"
    else:
        env = {**os.environ, "STELLA_TEAM": name, **({"STELLA_ORDER": str(order_seq)} if order_seq else {})}
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
