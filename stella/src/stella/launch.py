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
from stella.config import BIN, CALL, settings, store_dir

_NAME = re.compile(r"[^a-z0-9-]+")


def slug(text: str, limit: int = 32) -> str:
    s = _NAME.sub("-", text.lower()).strip("-")
    return (s[:limit].rstrip("-")) or "team"


def lead_prompt(name: str, archetype: str, order_seq: int | None, order_text: str, extra: str = "",
                auto_push: bool = False) -> str:
    owner = settings().owner
    stella = CALL
    order_ref = f"order #{order_seq}" if order_seq else "an order"
    if auto_push:
        push = (f"- Push duty: {owner} told you up front to push. When your work is committed in a repo that has a remote, "
                f"push the branch yourself (no prompt will appear), then say what was pushed. Opening a PR or merging still needs his yes.")
    else:
        push = (f"- Push duty: a commit in a repo that has a remote is not finished until you have tried to push it. Run `git push -u origin <branch>` "
                f"yourself, before `{stella} done`: Claude Code then shows {owner} a yes/no prompt, so he never has to remember an outstanding push. "
                f"If he answers no, the push is deferred: say \"not pushed, you declined\" in your final message and name the branch and commit. "
                f"Never write just \"committed locally\". A repo with no remote needs no push. `{stella} done` refuses once while your commits are unpushed.")
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
- Ask {owner} first before anything outward-facing or hard to reverse: posting, writing to external systems, triggering pipelines, deleting. (Pushing is covered by the push duty below.)
{push}
{extra}""".rstrip() + "\n"


LEAD_EXITED = "@stella_lead_exited"  # window option: the lead has ended and the pane now holds the owner's shell


def write_script(script: Path, name: str, directory: str, mode: str, order_seq: int | None, claude_args: list[str],
                 creds: dict[str, str | None], auto_push: bool = False, team: bool = True) -> None:
    """The window's command. pass_env variables that are off are unset here (a tmux server's
    environment may carry them); values that are on come in through tmux -e and never touch disk.

    Claude runs as a child of the script, and when it ends (/quit, a crash) the script becomes the owner's
    login shell in the same directory, so the window outlives the lead: they can run things or resume.
    `stella reap` closes it by killing the window. The end itself is recorded by the SessionEnd hook; a
    crash sends none, so the script feeds the hook the missing event. `team=False` is a reopened
    session that is not one of Stella's teams: no team name in its environment, no hook feed."""
    s = settings()
    prompt_file = store_dir() / "launch" / f"{name}.prompt.md"
    extra = f" --append-system-prompt-file {shlex.quote(str(prompt_file))}" if team or prompt_file.exists() else ""
    script.write_text(
        "#!/bin/sh\n"
        f"cd {shlex.quote(directory)} || exit 1\n"
        + (f"export STELLA_TEAM={shlex.quote(name)}\n" if team else "")
        + (f"export STELLA_ORDER={order_seq}\n" if order_seq else "")
        + ("export STELLA_AUTO_PUSH=1\n" if auto_push else "")
        + "".join(f"unset {k}\n" for k, v in creds.items() if v is None)
        + f'[ -n "$TMUX" ] && tmux set-option -wu -t "$TMUX_PANE" {LEAD_EXITED} >/dev/null 2>&1\n'
        + f"{shlex.quote(s.claude_bin)} --name {shlex.quote(name)} --permission-mode {shlex.quote(mode)}{extra}"
        f" {' '.join(shlex.quote(a) for a in claude_args)}\n"
        "rc=$?\n"
        # Tell Stella the pane is a plain shell now (`tell` must not type a message into it).
        f'[ -n "$TMUX" ] && tmux set-option -w -t "$TMUX_PANE" {LEAD_EXITED} 1 >/dev/null 2>&1\n'
        + (
            # A SessionEnd hook records every exit it sees. A non-zero status with no record (killed, crashed)
            # is fed to the same hook so the lead still counts as ended; one already recorded changes nothing.
            f'if [ "$rc" -ne 0 ]; then printf \'{{"reason":"other"}}\' | {shlex.quote(str(BIN))} hook session-end >/dev/null 2>&1; fi\n'
            if team else ""
        )
        + 'if [ "$rc" -ne 0 ]; then printf "\\n[stella] claude exited with status %s.\\n" "$rc"; fi\n'
        f'printf "\\n[stella] claude ended. This is your shell in %s: run things, or `claude --resume` to go on.\\n" "$PWD"\n'
        'exec "${SHELL:-/bin/sh}" -l\n'
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
    auto_push: bool = False,
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
    directory_arg = directory
    directory = os.path.expanduser(
        (directory or team.dir or os.getcwd()).format(repos_dir=s.repos_dir)
    )
    if directory_arg is None and not team.dir and os.path.realpath(directory) == os.path.realpath(os.path.expanduser("~")):
        raise SystemExit(
            "refusing to start a team in the home directory by default: pass --dir with the folder where the work belongs"
            " (a repo, or its parent for work across repos), or --dir ~ if the task really is system-wide"
        )
    # Every session starts in the owner's configured mode (the `permission_mode` setting) unless the caller
    # names one: a team's own entry no longer overrides it.
    mode = permission_mode or s.permission_mode

    d = store_dir() / "launch"
    d.mkdir(parents=True, exist_ok=True)
    prompt_file = d / f"{name}.prompt.md"
    prompt_file.write_text(lead_prompt(name, archetype, order_seq, order_text, team.raw.get("lead_notes", ""), auto_push))
    first = registry.first_prompt(team, order_text, args=args, name=name)
    creds = passenv.resolve()
    script = d / f"{name}.sh"
    write_script(script, name, directory, mode, order_seq, [first], creds, auto_push)
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
        env = passenv.apply({**os.environ, "STELLA_TEAM": name, **({"STELLA_ORDER": str(order_seq)} if order_seq else {}),
                                  **({"STELLA_AUTO_PUSH": "1"} if auto_push else {})})
        subprocess.Popen(
            [s.claude_bin, "--bg", "--name", name, "--permission-mode", mode,
             "--append-system-prompt-file", str(prompt_file), first],
            cwd=directory, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        via = "background session (no tmux server found); reach it with `claude attach " + name + "`"
    ev = ledger.append(
        "launch", by="cli", team=name, archetype=archetype, order=order_seq, dir=directory,
        window=window, socket=sock, via=via, mode=mode, auto_push=auto_push, pass_env=passenv.effective(), session=os.environ.get("STELLA_SESSION_ID"),
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


def respawn_team(srv, name: str, pane: str, session_id: str, why: str, creds: dict[str, str | None], label: str = "") -> str:
    """Restart a team's lead in its pane, resuming its conversation, with the pass_env variables as
    the switch says now. Its work so far is kept; a tool call in flight is interrupted."""
    t = state.fold().teams.get(name)
    if not t:
        return f"{name}: no such team"
    launch_ev = next((e for e in reversed(list(ledger.events())) if e["type"] == "launch" and e.get("team") == name), {})
    d = store_dir() / "launch"
    script = d / f"{name}.resume.sh"
    directory = launch_ev.get("dir") or t.directory or os.path.expanduser("~")
    write_script(script, name, directory, launch_ev.get("mode") or "default", t.order,
                 ["--resume", session_id, RESPAWN_NOTE.format(why=why)], creds, bool(launch_ev.get("auto_push")))
    _marker(name).write_text(str(_pending(name) + 1))
    err = tmuxctl.respawn(srv, pane, directory, str(script), env={k: v for k, v in creds.items() if v is not None})
    if err:
        respawning(name)  # nothing was killed: take the expectation back
        return f"{name}: tmux could not restart {label or pane} ({err}); not restarted"
    ledger.append("respawned", by="cli", team=name, window=t.window, pass_env=passenv.mode(),
                  session=os.environ.get("STELLA_SESSION_ID"))
    return f"{name}: restarted in {label or pane}, conversation resumed"


def reopen(target: str, directory: str | None = None, dry_run: bool = False) -> str:
    """Open a window that resumes a finished session, named for it, in the directory it started in (the one
    `claude --resume` lists it under). `target` is a team name, a session name or a session id. The session
    is made listable by the resume picker first. A team comes back as the same team."""
    from stella import daily, resume

    st = state.fold()
    t = st.teams.get(target)
    found = resume.lookup(t.session_id if t and t.session_id else target)
    if not found:
        return f"{target}: no transcript with that name or id under {daily.transcripts_dir()}"
    name = t.name if t else (found.title or target)
    directory = os.path.expanduser(directory or (t.directory if t and t.directory else found.cwd) or "~")
    srv = tmuxctl.find_server()
    if srv and tmuxctl.find_window(srv, name):
        return f"{name}: a window of that name is already open; close it first or give it another name"
    if dry_run:
        return f"would reopen {name} (session {found.session_id}) in {directory}"
    note = resume.make_listable(found.path)
    launch_ev = next((e for e in reversed(list(ledger.events())) if e["type"] == "launch" and e.get("team") == name), {})
    d = store_dir() / "launch"
    d.mkdir(parents=True, exist_ok=True)
    script = d / f"{name}.reopen.sh"
    creds = passenv.resolve()
    mode = launch_ev.get("mode") or settings().permission_mode
    write_script(script, name, directory, mode, t.order if t else None, ["--resume", found.session_id], creds,
                 bool(launch_ev.get("auto_push")), team=t is not None)
    if not srv:
        return tmuxctl.last_error or f"{name}: no tmux server is running; run `cd {directory} && claude --resume {found.session_id}`"
    window = tmuxctl.new_window(srv, name, directory, str(script), env={k: v for k, v in creds.items() if v is not None})
    if t:
        ledger.append("launch", by="cli", team=name, archetype=t.archetype, order=t.order, dir=directory, window=window,
                      socket=srv.socket, via=f"tmux ({srv.via} server)", mode=mode, auto_push=launch_ev.get("auto_push"),
                      pass_env=passenv.effective(), reopened=found.session_id, session=os.environ.get("STELLA_SESSION_ID"))
    return f"reopened {name} in window {window}, {directory}" + (f" ({note})" if note else "")
