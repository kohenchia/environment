"""The wake line: tell Stella's own session that a team finished, needs the owner, or exited.

Her session only takes a turn when something is typed into it, so a team that finishes while she is
idle would sit unnoticed. When a team reports done, reports `--needs-you`, or exits unexpectedly, a
short line starting `[Stella] ` is typed into her window. The prompt hook treats that line as a
system note, never as an order from the owner, but only when the prompt is exactly, on one line, a
line this module typed (`take_system_note`): the owner's words queued behind it, or typed by him
starting `[Stella]`, are recorded as orders as usual. The `[Stella-restart]` note a respawn gives
her is recognised the same way.

Not woken by: plain progress reports, and team windows the owner closed by hand (a typed /exit, a
/clear or a logout, or a window that was already gone when the lead's session ended).

What is pending comes from the ledger, not from a queue of its own: every waking event after
`covered_seq` (in `wake.json`) is pending, as is any READY follow-up she has not been woken for.
Typing a line, or one of her turns carrying the pending events in its context, moves `covered_seq`
past them. A helper that dies loses nothing: her next turn, or the scheduler's backstop, picks the
events up. A store without `wake.json` (the first run after upgrading) starts past everything older
than SEED_GRACE, so old news is not replayed.

Timing: events within `wake_merge_seconds` (20) of the oldest pending one share a line, and lines
are at least `wake_gap_seconds` (60) apart. The command that recorded the event starts a detached
helper (`stella wake`) that waits out both, then types the line once she is idle; it gives up after
HELPER_PATIENCE and leaves the rest to her next turn and the backstop. A lead whose shell is
sandboxed may not reach tmux at all; its helper then stops ("blocked"), and the scheduler's backstop,
which runs from the owner's terminal, types the line within `wake_check_minutes`.

Where it types: the one tmux window named `stella` (never a team's window) in the server her
session recorded when it started, and no other server; in it, the pane whose process is her session
or an ancestor of it. No recorded or live server, no such window, several, or no pane running her:
nothing is typed and an alert is raised. Stella not running: nothing is typed; her next session
starts with the brief, which has it all. Every tmux call has a short timeout, so a hung tmux can't
hold the lock the prompt hook also takes.

Idle is read off her screen (`capture-pane`), because Claude Code has no other signal for it:
Claude Code's input box is visible (a prompt line, `❯` or `>`, between two rules of `─`), it holds
no draft (any character that is neither dim nor reverse-video counts as typed text: the placeholder
hint is dim and the cursor is reverse video), and in the LOOK_ABOVE lines above the box there is no
spinner (`✢ Pontificating…`, `✶ Compacting conversation… (3s)`), no running hook (`⎿  Running …
hooks…`) and no "esc to interrupt". A permission prompt or a menu replaces the box, so it reads as
busy. Getting this wrong is mild: Claude Code queues a line typed during a turn.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import json
import os
import re
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

from stella import ledger, run, state, tmuxctl
from stella.config import BIN, CALL, settings, store_dir

PREFIX = "[Stella] "
RESTART_PREFIX = "[Stella-restart] "
ALERT_KEY = "wake:window"
HELPER_PATIENCE = 15 * 60  # seconds a helper waits for her to become idle
MAX_AGE = dt.timedelta(hours=12)  # older events are left to the brief, not woken for
SEED_GRACE = dt.timedelta(minutes=10)
NOTE_TTL = dt.timedelta(days=1)  # how long a line typed (or a restart note given) is recognised
TMUX_TIMEOUT = 3  # seconds per tmux call while wake.lock is held, so a hung tmux can't stall a prompt
# SessionEnd reasons that mean the owner closed the window himself (see state.END_PHRASES).
BY_HAND = {state.DELIBERATE_END, "clear", "resume", "logout"}


def phrase(ev: dict) -> str | None:
    """How a ledger event reads in a wake line, or None when it must not wake her."""
    t = ev["type"]
    if t == "done":
        return "finished"
    if t == "report" and ev.get("needs_you"):
        return "needs you"
    if t == "ended" and ev.get("reason") not in BY_HAND and not ev.get("window_closed"):
        return state.end_phrase(ev.get("reason"))
    return None


# ---------------------------------------------------------------- state


def _path():
    return store_dir() / "wake.json"


def _seed() -> int:
    """Where a store without wake.json (a first run after upgrading) starts: past every event older
    than SEED_GRACE, so old news is not replayed, while the event that caused this first look (a
    `stella done` a moment ago) still wakes her."""
    cutoff = ledger.now() - SEED_GRACE
    return max((e["seq"] for e in ledger.events() if ledger.parse_ts(e) < cutoff), default=0)


@contextlib.contextmanager
def _locked() -> Iterator[dict]:
    """wake.json, read and written under one lock, so a helper and a hook never both type."""
    store_dir().mkdir(parents=True, exist_ok=True)
    with (store_dir() / "wake.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            try:
                w = json.loads(_path().read_text())
            except (FileNotFoundError, json.JSONDecodeError):
                w = {"covered_seq": _seed()}
            before = json.dumps(w, sort_keys=True)
            yield w
            if json.dumps(w, sort_keys=True) != before:
                tmp = _path().with_suffix(".tmp")
                tmp.write_text(json.dumps(w))
                tmp.replace(_path())
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


@dataclass
class Pending:
    events: list[dict] = field(default_factory=list)
    followups: list[state.Followup] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.events or self.followups)


def _pending(w: dict, st: state.State, now: dt.datetime) -> Pending:
    evs = [e for e in ledger.events(w.get("covered_seq", 0))
           if phrase(e) and now - ledger.parse_ts(e) < MAX_AGE]
    seen = set(w.get("followups_seen", []))
    return Pending(evs, [f for f in st.ready_followups() if f.seq not in seen])


def _cover(w: dict, p: Pending, st: state.State) -> None:
    if p.events:
        w["covered_seq"] = max(w.get("covered_seq", 0), max(e["seq"] for e in p.events))
    w["followups_seen"] = sorted(set(w.get("followups_seen", [])) | {f.seq for f in st.ready_followups()})


def summary(p: Pending) -> str:
    """'team alpha finished; team beta needs you; follow-up #12 is READY'."""
    latest: dict[str, str] = {}
    for e in p.events:  # oldest first; a team's latest news wins
        latest.pop(e.get("team", "?"), None)
        latest[e.get("team", "?")] = phrase(e) or ""
    parts = [f"team {name} {what}" for name, what in latest.items()]
    if len(parts) > 4:
        parts = parts[:3] + [f"{len(parts) - 3} more teams have news"]
    fu = [f"#{f.seq}" for f in p.followups]
    if fu:
        parts.append(f"follow-up{'s' if len(fu) > 1 else ''} {', '.join(fu)} {'are' if len(fu) > 1 else 'is'} READY")
    text = "; ".join(parts)
    return text[:1].upper() + text[1:]


def instruction() -> str:
    return (f"Review your open follow-ups and the fleet (`{CALL} brief`, `{CALL} fleet`), act on what is"
            f" unblocked, and tell {settings().owner} briefly. The wrap-up sweep closes clean finished teams by"
            f" itself; you handle only the exceptions the brief lists under \"Finished, not wrapped up\".")


def line(p: Pending) -> str:
    return f"{PREFIX}{summary(p)}. {instruction()}"


def _norm(text: str) -> str:
    return " ".join(text.split())


def _expect(w: dict, text: str, now: dt.datetime) -> None:
    keep = [x for x in w.get("expected", []) if now - dt.datetime.fromisoformat(x["at"]) < NOTE_TTL]
    w["expected"] = keep[-9:] + [{"text": _norm(text), "at": now.isoformat(timespec="seconds")}]


def expect(text: str) -> None:
    """Stella's tooling is about to give her session this exact line (a restart note)."""
    with _locked() as w:
        _expect(w, text, ledger.now())


def take_system_note(text: str) -> bool:
    """True when this prompt is, exactly and on one line, a line Stella's tooling typed or gave her
    (and it is then forgotten, so it counts once). Anything else, including a wake line with the
    owner's own words queued behind it, or a message he types starting `[Stella]`, is not one."""
    if "\n" in text.strip() or not text.lstrip().startswith((PREFIX, RESTART_PREFIX)):
        return False
    now, t = ledger.now(), _norm(text)
    with _locked() as w:
        exp = w.get("expected", [])
        hit = next((x for x in exp if x["text"] == t and now - dt.datetime.fromisoformat(x["at"]) < NOTE_TTL), None)
        if hit:
            exp.remove(hit)
        return hit is not None


def window_gone(t: state.Team) -> bool:
    """True when the team's tmux window no longer exists: the owner closed it (a crashed lead's window
    stays open, waiting for a key). False whenever that can't be told."""
    if not t.window:
        return False
    sock = None
    for e in ledger.events():
        if e["type"] == "launch" and e.get("team") == t.name:
            sock = e.get("socket")
    srv = tmuxctl.server_for_socket(sock) if sock else None
    if not srv or srv.socket != sock:  # window ids belong to one server; another can't say
        return False
    return not tmuxctl.window_exists(srv, t.window)


# ---------------------------------------------------------------- her window


@dataclass
class Target:
    srv: tmuxctl.Server
    pane: str
    window: str


def _her_server(sock: str | None) -> tmuxctl.Server | str:
    """The tmux server her session was started in, and no other: not the caller's, not the default.
    Checked with `list-sessions`, which never starts a server."""
    if not sock:
        return ("her session recorded no tmux server (started outside tmux, or before wake lines existed:"
                " restart her with `stella run` inside tmux)")
    try:
        r = subprocess.run(["tmux", "-S", sock, "list-sessions"], capture_output=True, text=True, timeout=TMUX_TIMEOUT)
    except FileNotFoundError:
        return "tmux is not installed"
    if r.returncode != 0 and "not permitted" in r.stderr:
        tmuxctl.last_error = tmuxctl.SANDBOXED
        return tmuxctl.SANDBOXED
    if r.returncode != 0:
        return f"her tmux server ({sock}) is not running"
    return tmuxctl.Server(["tmux", "-S", sock], sock, "recorded")


def _lineage(pid: int) -> set[int]:
    """pid and its ancestors: a pane is hers when the process it started is one of them (her Claude
    itself when an agent opened her window; the shell that ran `stella run` when she runs in a terminal)."""
    out = {pid}
    for _ in range(32):
        try:
            r = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True, timeout=TMUX_TIMEOUT)
            pid = int(r.stdout.strip() or 0)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            break
        if pid <= 1 or pid in out:
            break
        out.add(pid)
    return out


def target() -> Target | str:
    """The pane to type into, or why there is none. Lists panes only: never starts a server."""
    rec = run._load()
    srv = _her_server(rec.get("socket"))
    if isinstance(srv, str):
        return srv
    r = srv.run("list-panes", "-a", "-F", "#{pane_id}\t#{window_id}\t#{window_name}\t#{pane_dead}\t#{pane_pid}",
                check=False, timeout=TMUX_TIMEOUT)
    teams = {t.window for t in state.fold().teams.values() if t.window}
    panes = [ln.split("\t") for ln in r.stdout.splitlines() if ln.count("\t") == 4]
    mine = [(p, w, ppid) for p, w, name, dead, ppid in panes if name == run.WINDOW and dead != "1" and w not in teams]
    windows = sorted({w for _, w, _ in mine})
    if len(windows) != 1:
        return (f"{len(windows)} tmux windows named {run.WINDOW!r} ({', '.join(windows) or 'none'}) in {srv.socket};"
                " one must be hers")
    lineage = _lineage(int(rec.get("pid") or 0))
    hers = [p for p, _, ppid in mine if ppid.isdigit() and int(ppid) in lineage]
    if len(hers) != 1:
        return f"window {windows[0]} has no pane running her session (pid {rec.get('pid')})"
    return Target(srv, hers[0], windows[0])


_SGR = re.compile(r"\x1b\[([0-9;:]*)m")
_OTHER_ESC = re.compile(r"\x1b(?:\[[0-9;:?]*[A-Za-z]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[()][A-Za-z0-9])")
_RULE = re.compile(r"─{20,}")
_PROMPT = re.compile(r"^[\s│]*[❯>](?:\s|$)")
# A spinner: a glyph (not the prompt, the reply bullet or box drawing), then a word and an ellipsis,
# as in "✢ Pontificating…" or "✶ Compacting conversation… (3s)". A finished turn says "✻ Crunched for 2s".
_SPINNER = re.compile(r"^\s*[^\w\s│─❯>⏺⎿]\s+\S+(?:\s\S+)?(?:…|\.\.\.)")
_BUSY = re.compile(r"esc to interrupt|^\s*⎿\s+Running .*…|Compacting conversation", re.IGNORECASE)
LOOK_ABOVE = 25  # lines above the box searched for a spinner (a todo list can sit between them)


def _plain(s: str) -> str:
    return _OTHER_ESC.sub("", _SGR.sub("", s))


def _typed(s: str) -> str:
    """The characters of a captured line shown neither dim nor in reverse video."""
    out, dim, rev, pos = [], False, False, 0
    for m in _SGR.finditer(s):
        if not (dim or rev):
            out.append(s[pos:m.start()])
        ps = (m.group(1) or "0").replace(":", ";").split(";")
        i = 0
        while i < len(ps):
            p = ps[i] or "0"
            if p in {"38", "48", "58"}:  # a colour: skip its arguments
                i += 3 if ps[i + 1:i + 2] == ["5"] else 5
                continue
            if p == "0":
                dim = rev = False
            elif p == "2":
                dim = True
            elif p == "22":
                dim = False
            elif p == "7":
                rev = True
            elif p == "27":
                rev = False
            i += 1
        pos = m.end()
    if not (dim or rev):
        out.append(s[pos:])
    return _OTHER_ESC.sub("", "".join(out))


def idle(screen: str) -> bool:
    """Is this Claude Code screen (`capture-pane -p -e`) waiting, empty, for input? See the module doc."""
    raw = screen.splitlines()
    plain = [_plain(x) for x in raw]
    if any("esc to interrupt" in x.lower() for x in plain):
        return False
    box = next((i for i in range(len(plain) - 2, 0, -1)
                if _PROMPT.match(plain[i]) and _RULE.search(plain[i - 1]) and _RULE.search(plain[i + 1])), None)
    if box is None:
        return False
    above = plain[max(0, box - 1 - LOOK_ABOVE):box - 1]
    if any(_SPINNER.match(x) or _BUSY.search(x) for x in above):
        return False
    draft = _PROMPT.sub("", _typed(raw[box]), count=1)
    return not draft.replace("│", "").strip()


def screen(t: Target) -> str:
    return t.srv.run("capture-pane", "-p", "-e", "-t", t.pane, check=False, timeout=TMUX_TIMEOUT).stdout


# ---------------------------------------------------------------- delivery


@dataclass
class Result:
    status: str  # nothing | not-running | wait | busy | blocked | no-window | sent
    detail: str = ""
    wait: float = 0.0


def _alert(st: state.State, why: str) -> None:
    text = f"wake line not typed: {why}"
    if ALERT_KEY not in st.alerts or st.alerts[ALERT_KEY].text != text:  # once per problem, not per attempt
        ledger.append("alert", by="wake", key=ALERT_KEY, text=text)


def deliver(now: dt.datetime | None = None) -> Result:
    """One attempt to type the wake line. Never waits: says how long to wait instead."""
    now = now or ledger.now()
    s = settings()
    with _locked() as w:
        st = state.fold()
        p = _pending(w, st, now)
        if not p:
            return Result("nothing")
        if not run.running():
            return Result("not-running")
        waits = []
        if p.events:
            waits.append((min(ledger.parse_ts(e) for e in p.events) + dt.timedelta(seconds=s.wake_merge_seconds) - now))
        if w.get("last_sent"):
            waits.append(dt.datetime.fromisoformat(w["last_sent"]) + dt.timedelta(seconds=s.wake_gap_seconds) - now)
        wait = max([x.total_seconds() for x in waits] + [0.0])
        if wait > 0:
            return Result("wait", wait=wait)
        try:
            t = target()
            if isinstance(t, str):
                if t == tmuxctl.SANDBOXED:  # this shell may not reach tmux; the scheduler's backstop can
                    return Result("blocked", t)
                _alert(st, t)
                return Result("no-window", t)
            if not idle(screen(t)):
                return Result("busy", t.pane)
            text = line(p)
            _expect(w, text, now)  # the prompt hook knows this exact line as hers, not the owner's
            tmuxctl.send_text(t.srv, t.pane, text, timeout=TMUX_TIMEOUT)
        except subprocess.TimeoutExpired as e:
            return Result("blocked", f"tmux did not answer in {e.timeout}s")
        _cover(w, p, st)
        w["last_sent"] = now.isoformat(timespec="seconds")
        ledger.append("wake", by="wake", text=text, teams=sorted({e.get("team") for e in p.events}) or None,
                      followups=[f.seq for f in p.followups] or None, pane=t.pane)
        if ALERT_KEY in st.alerts:
            ledger.append("clear_alert", by="wake", key=ALERT_KEY)
        return Result("sent", text)


def drain() -> str | None:
    """For the prompt hook in her own session: whatever is pending, as context for this turn, and
    marked delivered. None when nothing is pending."""
    with _locked() as w:
        st = state.fold()
        p = _pending(w, st, ledger.now())
        if not p:
            return None
        _cover(w, p, st)
        return f"Since your last turn: {summary(p)}. {instruction()}"


def cover_all() -> None:
    """Her session (re)started: the brief she is given shows everything, so nothing is pending."""
    with _locked() as w:
        st = state.fold()
        w["covered_seq"] = st.last_seq
        _cover(w, Pending(), st)


def seen(followup: int) -> None:
    """She just recorded a follow-up that is READY already; there is no need to wake her for it."""
    with _locked() as w:
        w["followups_seen"] = sorted(set(w.get("followups_seen", [])) | {followup})


# ---------------------------------------------------------------- helper and backstop


def kick() -> None:
    """Start a helper to type the wake line, when there may be one to type. Never blocks the caller."""
    if os.environ.get("STELLA_NO_WAKE") == "1" or not run.running():
        return
    log = store_dir() / "runs" / "wake.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as out:
            subprocess.Popen([str(BIN), "wake"], stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                             cwd=str(store_dir()), start_new_session=True)
    except OSError:
        pass


def _helper_lock():
    f = (store_dir() / "wake-helper.lock").open("a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        return None
    return f


def helper(patience: float = HELPER_PATIENCE, sleep=time.sleep, clock=time.monotonic) -> list[str]:
    """Wait out the merge window and the gap, then type the line once she is idle. One helper at a
    time; one that finds another running leaves the work to it. Returns what happened, for the log."""
    log: list[str] = []
    give_up = clock() + patience
    while True:
        lock = _helper_lock()
        if not lock:
            return log
        try:
            while True:
                r = deliver()
                log.append(f"{ledger.now():%H:%M:%S} {r.status} {r.detail}".rstrip())
                if r.status == "sent":
                    continue
                if r.status not in {"wait", "busy"} or clock() > give_up:
                    break
                sleep(min(max(r.wait, 0.5), 5.0) if r.status == "wait" else 3.0)
        finally:
            lock.close()
        # An event recorded while the lock was being let go started a helper that found it held and
        # left; pick its work up. Anything else that stopped this one stops it for good.
        if r.status != "nothing" or not _pending_now():
            return log


def _pending_now() -> bool:
    with _locked() as w:
        return bool(_pending(w, state.fold(), ledger.now()))


def backstop(now: dt.datetime | None = None) -> Result:
    """The scheduler's check for a wake line that never arrived. Reads the ledger and, only if
    something is pending, her screen: it spends no tokens and touches nothing when all is quiet."""
    return deliver(now)


def main() -> int:
    for entry in helper():
        print(entry, flush=True)
    return 0
