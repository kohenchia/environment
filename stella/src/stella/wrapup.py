"""Wrap-up readiness, and the optional sweep that closes finished teams that have nothing left for the owner.

The owner decides when a session is wrapped up (`stella wrap` from inside it, `/stella:wrap-up`). This module
says which finished teams are ready and why the others are not (`stella wrapup --dry-run`, the brief). With
`wrapup_auto = true` the scheduler also closes the ready ones about once a minute; that is off by default.
A team Stella launched is ready when ALL of these hold:

* its status is done (or ended, when it was closed by hand with its order closed) and it was not reaped yet
* its archetype does not set `keep_open` in teams.toml (the owner keeps talking to such a session)
* nothing was asked of the owner that is still open
* it has stayed done for the grace period (`wrapup_grace_minutes`), counted from the later of its `done`
  and the last time the owner typed to it
* its session is idle at its prompt, not working
* every repo it worked in (its directory, and repos named in its reports) has nothing unpushed (when the
  repo has a remote) and no uncommitted changes
* no open follow-up waits on it, and no push question it raised is still unanswered

Then the sweep does what `stella reap` does (kills the window, verifies it is gone), closes the orders the
team carried, records `wrapped_up` naming what it checked, and raises one quiet notification line.
Sessions Stella did not launch are never touched: only teams in the ledger are looked at.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from stella import ledger, notify, state, tmuxctl
from stella.config import settings, store_dir

GIT_TIMEOUT = 10
FINISHED = {"done", "ended"}


@dataclass
class Verdict:
    team: str
    status: str
    ok: bool
    reason: str = ""  # why it stays open (first failing condition)
    checked: list[str] = field(default_factory=list)  # what held, when ok
    repos: list[str] = field(default_factory=list)
    since: dt.datetime | None = None


# ---------------------------------------------------------------- git


def _git(repo: Path | str, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "--no-optional-locks", "-C", str(repo), *args], capture_output=True, text=True,
                           timeout=GIT_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def toplevel(path: Path) -> Path | None:
    d = path
    while not d.is_dir():
        if d.parent == d:
            return None
        d = d.parent
    out = _git(d, "rev-parse", "--show-toplevel")
    if not out:
        return None
    top = Path(out)
    home = Path(os.path.expanduser("~"))
    if top in {home, Path("/")} or store_dir() in {top, *top.parents} or top in store_dir().parents:
        return None
    return top


_PATH = re.compile(r"(?<![\w/.:~-])(~|/)[\w.@+\-]*(?:/[\w.@+\-]+)*")


def mentioned_paths(texts: list[str]) -> list[Path]:
    out: list[Path] = []
    for text in texts:
        for m in _PATH.finditer(text):
            raw = m.group(0).rstrip(".,;)")
            if len(raw) > 1:
                p = Path(os.path.expanduser(raw))
                if p not in out:
                    out.append(p)
    return out


def repos_of(t: state.Team) -> dict[Path, set[str] | None]:
    """The repos a team worked in: its directory (whole repo), and each repo a report names (the named
    path only, unless it is the repo's root, where the whole repo counts)."""
    repos: dict[Path, set[str] | None] = {}
    if t.directory:
        top = toplevel(Path(os.path.expanduser(t.directory)))
        if top:
            repos[top] = None
    for p in mentioned_paths(t.texts):
        if not p.exists():
            continue
        top = toplevel(p)
        if not top:
            continue
        if top == p.resolve() or top == p:
            repos[top] = None
        elif repos.get(top, set()) is not None:
            repos.setdefault(top, set()).add(str(p))  # type: ignore[union-attr]
    return repos


def repo_problem(top: Path, only: set[str] | None) -> str | None:
    name = top.name
    if only is None:
        dirty = _git(top, "status", "--porcelain")
    else:
        dirty = _git(top, "status", "--porcelain", "--", *sorted(only))
    if dirty:
        n = len(dirty.splitlines())
        return f"uncommitted changes in {name} ({n} file{'s' if n != 1 else ''})"
    if _git(top, "remote"):
        up = _git(top, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
        ahead = _git(top, "rev-list", "--count", f"{up}..HEAD") if up else _git(top, "rev-list", "--count", "HEAD", "--not", "--remotes")
        if ahead is None:
            return f"cannot read the git state of {name}"
        if ahead != "0":
            branch = _git(top, "rev-parse", "--abbrev-ref", "HEAD") or "HEAD"
            return f"{ahead} unpushed commit{'s' if ahead != '1' else ''} in {name} ({branch})"
    return None


# ---------------------------------------------------------------- tmux


def _window(st_name: str, t: state.Team):
    """(server, window id) of the team's window; (None, None) when tmux is unreachable; (srv, None) when
    the window is gone."""
    sock = None
    for e in ledger.events():
        if e["type"] == "launch" and e.get("team") == st_name:
            sock = e.get("socket")
    srv = tmuxctl.server_for_socket(sock) or tmuxctl.find_server()
    if srv is None:
        return None, None
    if t.window and tmuxctl.window_exists(srv, t.window):
        return srv, t.window
    return srv, tmuxctl.find_window(srv, st_name)


def session_idle(srv: tmuxctl.Server, window: str) -> bool:
    from stella import wake

    r = srv.run("list-panes", "-t", window, "-f", "#{!=:#{@sidebar},1}", "-F", "#{pane_id}", check=False,
                timeout=wake.TMUX_TIMEOUT)
    pane = r.stdout.split()[0] if r.stdout.split() else None
    if not pane:
        return True
    screen = srv.run("capture-pane", "-p", "-e", "-t", pane, check=False, timeout=wake.TMUX_TIMEOUT).stdout
    return wake.idle(screen)


# ---------------------------------------------------------------- the conditions


def _deferred_push(st: state.State, t: state.Team) -> str | None:
    pushed = [(e.get("repo"), e["seq"]) for e in ledger.events() if e["type"] == "push"]
    mine = t.sessions | ({t.session_id} if t.session_id else set())
    for q in st.push_questions:
        if q.get("team") == t.name or (q.get("session") in mine and q.get("session")):
            if not any(repo == q.get("repo") and seq > q["seq"] for repo, seq in pushed):
                return f"push of {q.get('repo')} {q.get('branch', '')} {str(q.get('sha', ''))[:7]} was asked and not approved".replace("  ", " ")
    return None


def _ago(d: dt.timedelta) -> str:
    m = int(d.total_seconds() // 60)
    return f"{m}m" if m < 60 else f"{m // 60}h"


def evaluate_team(st: state.State, t: state.Team, keep_open: set[str], now: dt.datetime) -> Verdict:
    v = Verdict(t.name, t.status, False)

    def no(reason: str) -> Verdict:
        v.reason = reason
        return v

    grace = dt.timedelta(minutes=settings().wrapup_grace_minutes)
    if t.archetype in keep_open:
        return no("keep_open: its session stays open for you to talk to")
    if t.asking:
        return no(f"needs-you: {' '.join((t.last_report or '').split())[:80]}")
    if t.status == "needs-you":
        return no("needs-you")
    if t.status == "running":
        return no("still running")
    if t.status == "ended":
        o = st.orders.get(t.order or -1)
        if t.end_reason != state.DELIBERATE_END:
            return no(f"{state.end_phrase(t.end_reason)}; decide whether to respawn or reap it")
        if o and o.status == "open":
            return no(f"closed by hand with order #{o.seq} still open")
    v.since = max([x for x in (t.ts, t.touched) if x])
    if now - v.since < grace:
        return no(f"grace period: {_ago(now - v.since)} of {settings().wrapup_grace_minutes}m")
    waiting = [f for f in st.open_followups() if t.name in f.after]
    if waiting:
        return no(f"follow-up #{waiting[0].seq} waits on it")
    deferred = _deferred_push(st, t)
    if deferred:
        return no(f"deferred push: {deferred}")
    srv = window = None
    if t.window:
        srv, window = _window(t.name, t)
        if srv is None:
            return no("tmux is not reachable from here, so its window cannot be checked or closed")
        if window and t.status == "done" and not session_idle(srv, window):
            return no("its session is busy or not at its prompt")
    repos = repos_of(t)
    for top, only in repos.items():
        problem = repo_problem(top, only)
        if problem:
            return no(problem)
    v.repos = [str(p) for p in repos]
    v.ok = True
    v.checked = [
        f"status {t.status}",
        "no open question",
        f"stayed {t.status} {_ago(now - v.since)} (grace {settings().wrapup_grace_minutes}m)",
        "session idle" if window else "no open window",
        f"repos clean and pushed: {', '.join(Path(p).name for p in v.repos) or 'none touched'}",
        "no follow-up waits on it",
        "no deferred push",
    ]
    return v


def _keep_open() -> set[str]:
    from stella import registry

    teams, _ = registry.load()
    return {n for n, t in teams.items() if t.keep_open}


def evaluate(st: state.State | None = None, now: dt.datetime | None = None, all_teams: bool = False) -> list[Verdict]:
    """A verdict per team not yet closed out. With all_teams, running teams are listed too."""
    st = st or state.fold()
    now = now or ledger.now()
    keep = _keep_open()
    wanted = FINISHED | ({"running", "needs-you"} if all_teams else set())
    return [evaluate_team(st, t, keep, now) for t in st.teams.values() if t.status in wanted and not t.acked]


def pending_lines(st: state.State, now: dt.datetime | None = None) -> list[str]:
    """For the brief and the per-turn hook: each finished team still open, with its one reason."""
    now = now or ledger.now()
    try:
        vs = [v for v in evaluate(st, now) if not (v.ok and settings().wrapup_auto)]
    except Exception:  # noqa: BLE001 - a broken check must not break the brief
        return []
    return [f"- {v.team} ({v.status}{', ' + _ago(now - v.since) + ' ago' if v.since else ''}): {v.reason or 'clean, ready to wrap up when the owner says so'}" for v in vs]


HEADER = ("Finished, not wrapped up (the owner decides when a session is wrapped up, with `/stella:wrap-up` in"
          " the session or `stella reap <team>`; never close one on your own. Fix a listed reason when asked,"
          " e.g. push unpushed commits through the push prompt):\n")


# ---------------------------------------------------------------- closing


def close_team(st: state.State, t: state.Team, force_record: bool = True) -> tuple[bool, str]:
    """Kill the team's window and verify it is gone. Records the team as reaped (and its notice as
    acknowledged) when the window is gone, or always when force_record. Returns (closed, message)."""
    name = t.name
    sock = None
    for e in ledger.events():
        if e["type"] == "launch" and e.get("team") == name:
            sock = e.get("socket")
    # The recorded socket can be stale: fall back to whichever server is reachable now, and look the
    # window up by name as well as by id.
    srv = tmuxctl.server_for_socket(sock) or tmuxctl.find_server()
    window = t.window if (srv and t.window and tmuxctl.window_exists(srv, t.window)) else (
        tmuxctl.find_window(srv, name) if srv else None
    )
    if window:
        srv.run("kill-window", "-t", window, check=False)
    still_open = bool(srv and window and tmuxctl.window_exists(srv, window))
    unreachable = srv is None and bool(t.window)
    ok = not still_open and not unreachable
    if ok or force_record:
        ledger.append("ack", by="cli", key=f"team:{name}:{t.status}")
        ledger.append("reaped", by="cli", team=name)
    if unreachable:
        return False, (f"recorded {name} as closed, but tmux is not reachable from here, so its window {t.window} is still open"
                       " (the command sandbox blocks tmux; run `stella reap` where tmux is reachable)")
    if still_open:
        return False, f"recorded {name} as closed, but its window {window} is still open"
    return True, f"closed {name}"


def sweep(dry_run: bool = False, now: dt.datetime | None = None) -> tuple[list[Verdict], list[Verdict]]:
    """Returns (wrapped up, kept open). With dry_run nothing is changed or recorded."""
    st = state.fold()
    verdicts = evaluate(st, now, all_teams=dry_run)
    wrapped, kept = [], []
    for v in verdicts:
        if not v.ok:
            kept.append(v)
        elif dry_run:
            wrapped.append(v)
        else:
            t = st.teams[v.team]
            closed, msg = close_team(st, t, force_record=False)
            if not closed:
                v.ok, v.reason = False, msg
                kept.append(v)
                continue
            carried = [o.seq for o in st.orders.values() if o.team == t.name and o.status == "open"] if t.status == "done" else []
            for seq in carried:
                ledger.append("close", by="wrapup", order=seq, status="done", note=f"team {t.name} wrapped up")
            ledger.append("wrapped_up", by="wrapup", team=t.name, checked=v.checked, repos=v.repos or None,
                          orders=carried or None)
            wrapped.append(v)
    if wrapped and not dry_run:
        notify.notify("Stella", "wrapped up: " + ", ".join(v.team for v in wrapped), quiet=True)
    return wrapped, kept


def report(wrapped: list[Verdict], kept: list[Verdict], dry_run: bool) -> str:
    lines = []
    for v in wrapped:
        lines.append(f"{'would wrap up' if dry_run else 'wrapped up'} {v.team}: " + "; ".join(v.checked))
    for v in kept:
        lines.append(f"kept open {v.team} ({v.status}): {v.reason}")
    return "\n".join(lines) or "no finished teams"


# ---------------------------------------------------------------- the owner wraps up one session


def wrap_current(delay: float = 3, dry_run: bool = False) -> str:
    """The owner's decision: close the session this is called from. Records the team (when it is one) as
    wrapped up, reports anything unpushed or uncommitted (the work stays on disk), and closes the tmux
    window a few seconds later, so the reply that ran this can finish."""
    pane = os.environ.get("TMUX_PANE")
    tm = os.environ.get("TMUX", "")
    if not pane or not tm:
        return "not inside tmux: nothing to close; type /exit to end this session."
    sock = tm.split(",", 1)[0]
    srv = tmuxctl.Server(["tmux", "-S", sock], sock, "caller")
    window = srv.run("display-message", "-p", "-t", pane, "#{window_id}", check=False).stdout.strip()
    if not window:
        return "could not find this session's tmux window (is tmux blocked by the command sandbox?)"
    team = os.environ.get("STELLA_TEAM")
    st = state.fold()
    t = st.teams.get(team or "")
    notes = []
    if t:
        for top, only in repos_of(t).items():
            problem = repo_problem(top, only)
            if problem:
                notes.append(problem)
    if dry_run:
        return f"would close window {window}" + (f" and record team {team} as wrapped up" if t else "") + (
            "; note: " + "; ".join(notes) if notes else "")
    if t:
        ledger.append("ack", by="owner", key=f"team:{t.name}:{t.status}")
        ledger.append("reaped", by="owner", team=t.name)
        ledger.append("wrapped_up", by="owner", team=t.name, checked=["the owner asked"], notes=notes or None)
    subprocess.Popen(["sh", "-c", f"sleep {delay}; tmux -S '{sock}' kill-window -t '{window}'"], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return (f"window {window} closes in {delay:g}s" + (f"; team {t.name} recorded as wrapped up" if t else "")
            + ("; still open in the repos: " + "; ".join(notes) if notes else ""))
