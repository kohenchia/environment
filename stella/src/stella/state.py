"""Fold the ledger into current state: open orders, follow-ups, teams, attention items.

The ledger grows forever; this state is bounded by what is *open*, not by history.
Only renderings of it (the brief, the delta) ever enter a model's context.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from stella import ledger
from stella.config import settings

CLOSED = {"done", "superseded", "cancelled", "expired"}


# SessionEnd reasons Claude Code documents: clear, resume, logout, prompt_input_exit,
# bypass_permissions_disabled, other. Only a typed /exit is a deliberate close.
DELIBERATE_END = "prompt_input_exit"
END_PHRASES = {
    DELIBERATE_END: "was closed by hand",
    "other": "exited unexpectedly",
    "clear": "was cleared by hand",
    "resume": "switched to another session",
    "logout": "was logged out",
    "bypass_permissions_disabled": "stopped because bypassing permissions was disabled",
}


def end_phrase(reason: str | None) -> str:
    """Plain words for why a team's session ended; an unrecognised reason is shown raw."""
    if not reason:
        return END_PHRASES["other"]
    return END_PHRASES.get(reason) or f"ended (reason: {reason})"


@dataclass
class Order:
    seq: int
    ts: dt.datetime
    text: str
    session: str
    session_label: str
    kind: str
    targets: list[str]
    status: str = "open"
    team: str | None = None
    note: str | None = None

    def stale(self, now: dt.datetime) -> bool:
        return self.status == "open" and (now - self.ts).days >= settings().stale_days


@dataclass
class Team:
    name: str
    seq: int
    ts: dt.datetime
    archetype: str
    order: int | None
    directory: str
    window: str | None
    status: str = "running"  # running | needs-you | done | ended
    last_report: str | None = None
    result: str | None = None
    session_id: str | None = None
    acked: bool = False
    end_reason: str | None = None
    asking: bool = False  # its latest report asked the owner something
    touched: dt.datetime | None = None  # the owner (or Stella) last typed to it
    sessions: set[str] = field(default_factory=set)
    texts: list[str] = field(default_factory=list)  # what it reported, for repos named in them

    def ended_text(self) -> str:
        text = f"team {self.name} {end_phrase(self.end_reason)}"
        if self.last_report:
            text += f". Last report: {' '.join(self.last_report.split())[:120]}"
        return text


@dataclass
class Followup:
    """"After teams X and Y are done, do Z": Stella's own reminder, not an order from the owner."""

    seq: int
    ts: dt.datetime
    text: str
    after: list[str]
    status: str = "open"  # open | done | cancelled
    note: str | None = None


@dataclass
class Attention:
    key: str
    seq: int
    ts: dt.datetime
    text: str


@dataclass
class State:
    last_seq: int = 0
    orders: dict[int, Order] = field(default_factory=dict)
    teams: dict[str, Team] = field(default_factory=dict)
    decisions: list[dict] = field(default_factory=list)
    alerts: dict[str, Attention] = field(default_factory=dict)
    acked: set[str] = field(default_factory=set)
    push_questions: list[dict] = field(default_factory=list)
    push_intents: list[dict] = field(default_factory=list)
    followups: dict[int, Followup] = field(default_factory=dict)

    def open_orders(self) -> list[Order]:
        return [o for o in self.orders.values() if o.status == "open" and o.kind == "instruction"]

    def open_followups(self) -> list[Followup]:
        return sorted((f for f in self.followups.values() if f.status == "open"), key=lambda f: f.seq)

    def waiting_on(self, f: Followup) -> list[str]:
        """The teams a follow-up still waits for, each with why ("beta (running)"); empty means READY.
        Only `stella done` counts as finished: a team that exited without it has not done its part."""
        out = []
        for name in f.after:
            t = self.teams.get(name)
            if not t:
                out.append(f"{name} (not launched)")
            elif t.status != "done":
                out.append(f"{name} ({t.status})")
        return out

    def ready_followups(self) -> list[Followup]:
        return [f for f in self.open_followups() if not self.waiting_on(f)]

    def attention(self, now: dt.datetime | None = None) -> list[Attention]:
        now = now or ledger.now()
        items: list[Attention] = []
        for t in self.teams.values():
            key = f"team:{t.name}:{t.status}"
            if key in self.acked:
                continue
            if t.status == "done":
                items.append(Attention(key, t.seq, t.ts, f"team {t.name} finished: {t.result or ''}".strip()))
            elif t.status == "needs-you":
                items.append(Attention(key, t.seq, t.ts, f"team {t.name} needs you: {t.last_report or ''}"))
            elif t.status == "ended":
                if t.end_reason == DELIBERATE_END:
                    o = self.orders.get(t.order or -1)
                    if not o or o.status != "open":
                        continue
                    items.append(Attention(key, t.seq, t.ts, t.ended_text() + " with its order still open"))
                else:
                    items.append(Attention(key, t.seq, t.ts, t.ended_text()))
        for o in self.open_orders():
            key = f"stale:{o.seq}"
            if o.stale(now) and key not in self.acked:
                items.append(Attention(key, o.seq, o.ts, f"order #{o.seq} is {(now - o.ts).days} days old, still open: {o.text[:90]}"))
        for k, a in self.alerts.items():
            if k not in self.acked:
                items.append(a)
        return sorted(items, key=lambda a: a.seq, reverse=True)


def fold(since_events=None) -> State:
    st = State()
    for ev in since_events if since_events is not None else ledger.events():
        st.last_seq = max(st.last_seq, ev["seq"])
        t = ev["type"]
        ts = ledger.parse_ts(ev)
        if t == "order":
            st.orders[ev["seq"]] = Order(
                seq=ev["seq"],
                ts=ts,
                text=ev.get("text", ""),
                session=ev.get("session", ""),
                session_label=ev.get("session_label", ev.get("session", "")[:8]),
                kind=ev.get("kind", "instruction"),
                targets=ev.get("targets", []),
            )
        elif t == "close":
            o = st.orders.get(ev.get("order", -1))
            if o:
                o.status = ev.get("status", "done")
                o.note = ev.get("note")
        elif t == "decision":
            st.decisions.append(ev)
            for s in ev.get("supersedes", []) or []:
                if s in st.orders:
                    st.orders[s].status = "superseded"
        elif t == "launch":
            name = ev["team"]
            st.teams[name] = Team(
                name=name,
                seq=ev["seq"],
                ts=ts,
                archetype=ev.get("archetype", "adhoc"),
                order=ev.get("order"),
                directory=ev.get("dir", ""),
                window=ev.get("window"),
            )
            st.acked = {k for k in st.acked if not k.startswith(f"team:{name}:")}
            o = st.orders.get(ev.get("order", -1))
            if o:
                o.team = name
        elif t == "reaped":
            team = st.teams.get(ev.get("team", ""))
            if team:
                team.acked = True
        elif t in {"direct", "tell"}:
            team = st.teams.get(ev.get("team", ""))
            if team:
                team.touched = ts
        elif t in {"report", "done", "ended", "started", "respawned"}:
            team = st.teams.get(ev.get("team", ""))
            if not team:
                continue
            if t == "started":
                team.session_id = ev.get("session")
                if ev.get("session"):
                    team.sessions.add(ev["session"])
                if team.status == "ended":  # a resumed session is alive again
                    team.status = "running"
            elif t == "report":
                team.last_report = ev.get("text")
                team.asking = bool(ev.get("needs_you"))
                team.texts = (team.texts + [ev.get("text") or ""])[-50:]
                team.status = "needs-you" if ev.get("needs_you") else "running"
                team.seq, team.ts = ev["seq"], ts
            elif t == "done":
                team.status, team.result = "done", ev.get("text")
                team.asking = False
                team.texts = (team.texts + [ev.get("text") or ""])[-50:]
                team.seq, team.ts = ev["seq"], ts
                o = st.orders.get(team.order or -1)
                if o and o.status == "open":
                    o.status = "done"
            elif t == "respawned" and team.status == "ended":
                team.status = "running"  # needs-you stays: the question is still open
            elif t == "ended" and team.status not in {"done"}:
                team.status = "ended"
                team.end_reason = ev.get("reason")
                team.seq, team.ts = ev["seq"], ts
        elif t == "alert":
            st.alerts[ev.get("key", f"alert:{ev['seq']}")] = Attention(
                ev.get("key", f"alert:{ev['seq']}"), ev["seq"], ts, ev.get("text", "")
            )
        elif t == "ack":
            st.acked.add(ev.get("key", ""))
        elif t == "clear_alert":
            st.alerts.pop(ev.get("key", ""), None)
        elif t == "push_question":
            st.push_questions.append(ev)
        elif t == "push_intent":
            st.push_intents.append(ev)
        elif t == "followup":
            st.followups[ev["seq"]] = Followup(
                seq=ev["seq"], ts=ts, text=ev.get("text", ""), after=list(ev.get("after", []))
            )
        elif t == "followup_close":
            f = st.followups.get(ev.get("followup", -1))
            if f:
                f.status = ev.get("status", "done")
                f.note = ev.get("note")
    return st


def conflicts(st: State, order_seq: int) -> list[Order]:
    new = st.orders.get(order_seq)
    if not new or not new.targets:
        return []
    tg = set(new.targets)
    return [
        o
        for o in st.open_orders()
        if o.seq != order_seq and tg & set(o.targets)
    ]
