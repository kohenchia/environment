"""Wrap-up readiness, and the optional sweep that closes finished teams that have nothing left for the owner.

The owner decides when a session is wrapped up: `gg` typed in it, `/stella:wrap-up` / `stella wrap` from inside it,
or `stella wrapup <team>` from outside. All of them go through `wrap_session` / `wrap_team` below: the same checks
(nothing unpushed, uncommitted, deferred or waiting on the owner), then the same closing. This module
says which finished teams are ready and why the others are not (`stella wrapup --dry-run`, the brief). With
`wrapup_auto = true` the scheduler also closes the ready ones about once a minute; that is off by default.
A team whose window and process are both gone (killed by a tmux restart, or closed by hand without `stella
done`) is treated as ended, whatever the ledger still says. It has no session to close, so the sweep records it as wrapped up when nothing is
left on it, even with `wrapup_auto` off; otherwise it stays in the list with its reason. A team Stella
launched is ready when ALL of these hold:

* its status is done (or ended, when it was closed by hand with its order closed) and it was not reaped yet
* its archetype does not set `keep_open` in teams.toml (the owner keeps talking to such a session)
* nothing was asked of the owner that is still open
* it has stayed done for the grace period (`wrapup_grace_minutes`), counted from the later of its `done`
  and the last time the owner typed to it
* its session is idle at its prompt, not working
* every repo it worked in (its directory, and repos named in its reports) has nothing unpushed (when the
  repo has a remote) and no uncommitted changes
* no open follow-up waits on it, and no push the owner deferred is still outstanding

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
from stella.config import BIN, settings, store_dir

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
    gone: bool = False  # no window and no process any more


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
    """A push the owner declined (recorded by the Stop hook) is outstanding until its commit is on a remote."""
    mine = t.sessions | ({t.session_id} if t.session_id else set())
    for q in st.push_deferred:
        if q.get("team") == t.name or (q.get("session") in mine and q.get("session")):
            path, sha = q.get("path"), q.get("sha")
            if path and sha and not _git(Path(path), "branch", "-r", "--contains", sha):
                return f"push of {q.get('repo')} {q.get('branch', '')} {str(sha)[:7]} was deferred".replace("  ", " ")
    return None


def _ago(d: dt.timedelta) -> str:
    m = int(d.total_seconds() // 60)
    return f"{m}m" if m < 60 else f"{m // 60}h"


def is_gone(t: state.Team, live: set[str] | None) -> bool:
    """A team Stella opened in tmux that is not finished (running, needs-you, or ended) and whose lead is no longer alive in any pane. `live` is None when that
    cannot be told (tmux unreachable): then nothing is gone."""
    return live is not None and bool(t.window) and t.status in {"running", "needs-you", "ended"} and t.name not in live


def evaluate_team(st: state.State, t: state.Team, keep_open: set[str], now: dt.datetime, gone: bool = False) -> Verdict:
    v = Verdict(t.name, "gone" if gone else t.status, False, gone=gone)

    def no(reason: str) -> Verdict:
        v.reason = reason
        return v

    grace = dt.timedelta(minutes=settings().wrapup_grace_minutes)
    if t.archetype in keep_open and not gone:
        return no("keep_open: its session stays open for you to talk to")
    if t.asking:
        return no(f"needs-you: {' '.join((t.last_report or '').split())[:80]}")
    if t.status == "needs-you" and not gone:
        return no("needs-you")
    if t.status == "running" and not gone:
        return no("still running")
    if gone:
        pass  # treated as ended: nothing is running, and a gone window cannot be closed or asked
    elif t.status == "ended":
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
    if t.window and not gone:
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
        f"status {v.status}" + (f" (the ledger still says {t.status})" if gone else ""),
        "no open question",
        f"stayed {v.status} {_ago(now - v.since)} (grace {settings().wrapup_grace_minutes}m)",
        "window and process gone" if gone else "session idle" if window else "no open window",
        f"repos clean and pushed: {', '.join(Path(p).name for p in v.repos) or 'none touched'}",
        "no follow-up waits on it",
        "no deferred push",
    ]
    return v


def _keep_open() -> set[str]:
    from stella import registry

    teams, _ = registry.load()
    return {n for n, t in teams.items() if t.keep_open}


def gone_teams(st: state.State) -> set[str]:
    """Names of the teams that are running or needs-you in the ledger but whose window and process are gone."""
    from stella import windows

    maybe = [t for t in st.teams.values() if t.window and t.status in {"running", "needs-you", "ended"} and not t.acked]
    if not maybe:
        return set()
    live = windows.live_teams()
    return {t.name for t in maybe if is_gone(t, live)}


def evaluate(st: state.State | None = None, now: dt.datetime | None = None, all_teams: bool = False,
             gone_only: bool = False) -> list[Verdict]:
    """A verdict per team not yet closed out. With all_teams, running teams are listed too; a team whose
    window and process are gone is always listed (as ended). With gone_only, only those."""
    st = st or state.fold()
    now = now or ledger.now()
    keep = _keep_open()
    gone = gone_teams(st)
    wanted = FINISHED | ({"running", "needs-you"} if all_teams else set())
    return [evaluate_team(st, t, keep, now, gone=t.name in gone) for t in st.teams.values()
            if not t.acked and (t.name in gone or (t.status in wanted and not gone_only))]


def pending_lines(st: state.State, now: dt.datetime | None = None) -> list[str]:
    """For the brief and the per-turn hook: each finished team still open, with its one reason."""
    now = now or ledger.now()
    try:
        vs = [v for v in evaluate(st, now) if not (v.ok and settings().wrapup_auto)]
    except Exception:  # noqa: BLE001 - a broken check must not break the brief
        return []
    return [f"- {v.team} ({v.status}{', ' + _ago(now - v.since) + ' ago' if v.since else ''}): {v.reason or ('clean, no window or process left: the sweep records it' if v.gone else 'clean, ready to wrap up when the owner says so')}" for v in vs]


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


def sweep(dry_run: bool = False, now: dt.datetime | None = None, gone_only: bool = False) -> tuple[list[Verdict], list[Verdict]]:
    """Returns (wrapped up, kept open). With dry_run nothing is changed or recorded. With gone_only, only
    teams whose window and process are gone are looked at (what the scheduler does when `wrapup_auto` is off)."""
    st = state.fold()
    verdicts = evaluate(st, now, all_teams=dry_run and not gone_only, gone_only=gone_only)
    wrapped, kept = [], []
    for v in verdicts:
        if not v.ok:
            kept.append(v)
        elif dry_run:
            wrapped.append(v)
        elif v.gone:  # nothing to close: record it. Its order stays as it is (the work was not finished).
            t = st.teams[v.team]
            ledger.append("ack", by="wrapup", key=f"team:{t.name}:{t.status}")
            ledger.append("reaped", by="wrapup", team=t.name)
            ledger.append("wrapped_up", by="wrapup", team=t.name, checked=v.checked, repos=v.repos or None)
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


@dataclass
class Wrap:
    closed: bool
    message: str  # one line for the owner
    blockers: list = field(default_factory=list)  # status.Blocker: why it did not close

    @property
    def push_blocks(self) -> bool:
        return any(b.kind == "push" for b in self.blockers)


def _blocked(bl: list, what: str = "gg") -> str:
    return f"{what}: not closing, " + "; ".join(b.text for b in bl)


def in_stella_server(sock: str) -> bool:
    """Whether this tmux socket is the server Stella works in: hers, a launch's, or tmux's default."""
    from stella import run

    known = {run._load().get("socket")} | {e.get("socket") for e in ledger.events() if e["type"] == "launch"}
    default = Path(os.environ.get("TMUX_TMPDIR") or "/tmp") / f"tmux-{os.getuid()}" / "default"
    known.add(str(default))
    return sock in known


def finish_wrap(st: state.State, t: state.Team, who: str, checked: list[str], record_reap: bool = True) -> None:
    """The ledger side of a wrap-up: the team is acknowledged and reaped, its open orders closed, `wrapped_up` written."""
    if record_reap:
        ledger.append("ack", by=who, key=f"team:{t.name}:{t.status}")
        ledger.append("reaped", by=who, team=t.name)
    carried = [o.seq for o in st.orders.values() if o.team == t.name and o.status == "open"]
    for seq in carried:
        ledger.append("close", by=who, order=seq, status="done", note=f"team {t.name} wrapped up")
    ledger.append("wrapped_up", by=who, team=t.name, checked=checked, orders=carried or None)


def wrap_session(sid: str, cwd: str, delay: float = 3, dry_run: bool = False) -> Wrap:
    """Wrap up the session this runs in (the owner typed `gg`, or ran `stella wrap`): check that nothing is unpushed,
    uncommitted, deferred or waiting on the owner; if so, do not close. Otherwise record the team (if it is one) as
    wrapped up with its orders closed, and close the tmux window `delay` seconds later (so the hook or reply that
    ran this can finish), verifying that it is gone. A session that is not a team just loses its window."""
    from stella import run, status

    if run.is_self():
        return Wrap(False, "gg: Stella's own session is never wrapped up.")
    pane = os.environ.get("TMUX_PANE")
    tm = os.environ.get("TMUX", "")
    if not pane or not tm:
        return Wrap(False, "not inside tmux: nothing to close; type /exit to end this session.")
    sock = tm.split(",", 1)[0]
    if not in_stella_server(sock):
        return Wrap(False, "gg: this tmux server is not Stella's; nothing closed. Type /exit to end this session.")
    srv = tmuxctl.Server(["tmux", "-S", sock], sock, "caller")
    window = srv.run("display-message", "-p", "-t", pane, "#{window_id}", check=False).stdout.strip()
    if not window:
        return Wrap(False, "could not find this session's tmux window (is tmux blocked by the command sandbox?)")
    st = state.fold()
    t = st.teams.get(os.environ.get("STELLA_TEAM") or "")
    bl = status.blockers(st, sid, cwd, own=False, t=t)
    if bl:
        return Wrap(False, _blocked(bl), bl)
    if dry_run:
        return Wrap(False, f"would close window {window}" + (f" and record team {t.name} as wrapped up" if t else ""))
    if t:
        finish_wrap(st, t, "owner", ["the owner typed gg", "nothing unpushed, uncommitted, deferred or open for the owner"])
    subprocess.Popen([str(BIN), "wrapup", "--close-window", f"{sock}|{window}", "--delay", f"{delay:g}"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return Wrap(True, f"wrapped up: window {window} closes in {delay:g}s" + (f"; team {t.name} recorded as wrapped up" if t else ""))


def wrap_team(name: str, dry_run: bool = False) -> Wrap:
    """`stella wrapup <team>`: the same checks and closing for one team from outside its window. The kill is
    immediate and verified (a window still open is reported, not recorded as closed)."""
    from stella import status

    st = state.fold()
    t = st.teams.get(name)
    if not t:
        return Wrap(False, f"no team {name}")
    if t.acked:
        return Wrap(False, f"{name} is already wrapped up")
    bl = status.blockers(st, "", t.directory or "", own=False, t=t)
    if bl:
        return Wrap(False, _blocked(bl, f"{name}"), bl)
    if dry_run:
        return Wrap(False, f"would wrap up {name}")
    closed, msg = close_team(st, t, force_record=False)
    if not closed:
        return Wrap(False, msg)
    finish_wrap(st, t, "owner", ["the owner asked", "nothing unpushed, uncommitted, deferred or open for the owner"], record_reap=False)
    return Wrap(True, f"wrapped up {name}: {msg}")


def wrap_current(delay: float = 3, dry_run: bool = False) -> str:
    """`stella wrap`, from inside the session (what `/stella:wrap-up` runs): the same path as `gg`."""
    return wrap_session(os.environ.get("STELLA_SESSION_ID", ""), os.getcwd(), delay, dry_run).message


def close_window(spec: str, delay: float) -> None:
    """Detached helper of `wrap_session`: close the window after `delay`, verify it is gone, and raise an alert if not."""
    import time

    sock, _, window = spec.partition("|")
    time.sleep(delay)
    srv = tmuxctl.Server(["tmux", "-S", sock], sock, "recorded")
    srv.run("kill-window", "-t", window, check=False)
    time.sleep(0.5)
    if tmuxctl.window_exists(srv, window):
        ledger.append("alert", by="wrapup", key=f"window-open:{window}", text=f"gg: window {window} did not close")
