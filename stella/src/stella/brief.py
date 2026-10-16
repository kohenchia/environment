"""Render bounded views of the ledger for a model's context.

* the **brief**: current state, hard-capped (default 60 lines)
* the **delta**: what other sessions recorded since this session last looked,
  capped (default 15 lines), newest first

Neither ever reads out the raw ledger; when a cap is hit the rendering says how
many items it left out and which command shows them.
"""

from __future__ import annotations

import datetime as dt

from stella import ledger
from stella.config import settings
from stella.state import State, conflicts, end_phrase


def _age(ts: dt.datetime, now: dt.datetime) -> str:
    s = int((now - ts).total_seconds())
    if s < 3600:
        return f"{max(s // 60, 0)}m"
    if s < 86400:
        return f"{s // 3600}h"
    return f"{s // 86400}d"


def _clip(text: str, n: int = 110) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def describe(ev: dict) -> str:
    t = ev["type"]
    who = ev.get("session_label") or (ev.get("session") or "")[:8]
    if t == "order":
        tag = "asked" if ev.get("kind") == "question" else "order"
        return f"#{ev['seq']} {tag} in {who}: {_clip(ev.get('text', ''))}"
    if t == "decision":
        sup = f" (supersedes {', '.join('#' + str(s) for s in ev['supersedes'])})" if ev.get("supersedes") else ""
        return f"#{ev['seq']} decision: {_clip(ev.get('text', ''))}{sup}"
    if t == "launch":
        return f"#{ev['seq']} launched team {ev['team']} ({ev.get('archetype', 'adhoc')}) for order #{ev.get('order', '?')}"
    if t == "tell":
        return f"#{ev['seq']} told {ev.get('team')}: {_clip(ev.get('text', ''))}"
    if t == "direct":
        return f"#{ev['seq']} owner typed to team {ev.get('team')}: {_clip(ev.get('text', ''))}"
    if t == "report":
        flag = " NEEDS YOU" if ev.get("needs_you") else ""
        return f"#{ev['seq']} {ev.get('team')} reported{flag}: {_clip(ev.get('text', ''))}"
    if t == "done":
        return f"#{ev['seq']} {ev.get('team')} finished: {_clip(ev.get('text', ''))}"
    if t == "ended":
        return f"#{ev['seq']} {ev.get('team')} {end_phrase(ev.get('reason'))}"
    if t == "close":
        return f"#{ev['seq']} closed order #{ev.get('order')} as {ev.get('status')}"
    if t == "note":
        return f"#{ev['seq']} note: {_clip(ev.get('text', ''))}"
    if t == "list_shown":
        return f"#{ev['seq']} showed the owner a list of {len(ev.get('items') or [])}: {_clip('; '.join(ev.get('items') or []))}"
    if t == "correction":
        return f"#{ev['seq']} correction: {_clip(ev.get('text', ''))}"
    if t == "push_deferred":
        return f"#{ev['seq']} {ev.get('text', 'not pushed, deferred')}"
    if t == "push":
        return f"#{ev['seq']} pushed {ev.get('repo')} {ev.get('sha', '')[:7]} to {ev.get('ref')}"
    if t == "pass_env":
        return f"#{ev['seq']} {ev.get('text', 'pass_env ' + str(ev.get('mode')))}, set by {ev.get('by')}"
    if t == "respawned":
        return f"#{ev['seq']} restarted {ev.get('team')} (pass_env {ev.get('pass_env') or 'not set'}), conversation resumed"
    if t == "alert":
        return f"#{ev['seq']} alert: {_clip(ev.get('text', ''))}"
    if t == "followup":
        return f"#{ev['seq']} follow-up after {', '.join(ev.get('after', []))}: {_clip(ev.get('text', ''))}"
    if t == "followup_close":
        return f"#{ev['seq']} closed follow-up #{ev.get('followup')} as {ev.get('status')}"
    if t == "wrapped_up":
        return f"#{ev['seq']} wrapped up {ev.get('team')}"
    if t == "wake":
        return f"#{ev['seq']} woke Stella: {_clip(ev.get('text', ''))}"
    return f"#{ev['seq']} {t}"


QUIET = {"list_shown", "ack", "started", "clear_alert", "reaped", "wake", "wrapped_up"}


def delta(session_id: str, since: int, st: State | None = None) -> list[str]:
    cap = settings().delta_lines
    evs = [
        e
        for e in ledger.events(since)
        if e.get("session") != session_id and e["type"] not in QUIET
    ]
    lines = [describe(e) for e in reversed(evs)]
    if len(lines) > cap:
        extra = len(lines) - (cap - 1)
        lines = lines[: cap - 1] + [f"+{extra} earlier events: `~/.local/bin/stella log --since {since}`"]
    return lines


def conflict_lines(st: State, order_seq: int) -> list[str]:
    out = []
    now = ledger.now()
    for o in conflicts(st, order_seq):
        out.append(
            f"#{o.seq} ({_age(o.ts, now)} ago, in {o.session_label}): {_clip(o.text)}"
            f" [shares {', '.join(sorted(set(o.targets) & set(st.orders[order_seq].targets)))}]"
        )
    return out


def followup_lines(st: State, now: dt.datetime | None = None) -> list[str]:
    """Each open follow-up, READY when every team it waits for has finished, else naming the rest."""
    now = now or ledger.now()
    out = []
    for f in st.open_followups():
        waiting = st.waiting_on(f)
        tag = f"READY ({', '.join(f.after)} finished)" if not waiting else f"waiting on {', '.join(waiting)}"
        out.append(f"- #{f.seq} {tag}, {_age(f.ts, now)} ago: {_clip(f.text)}")
    return out


def render(st: State) -> str:
    cap = settings().brief_lines
    now = ledger.now()
    sections: list[tuple[str, list[str], int]] = []  # (title, lines, drop priority: higher drops first)

    from stella import finish

    finish.clear_pushed(st)
    from stella import provenance

    att = provenance.attention(st, now)
    sections.append(("Needs you", [f"- {_clip(a.text, 130)}" for a in att], 1))
    sections.append((f"Last list shown (#{st.last_list_seq}; a bare number from the owner means one of these)",
                     [f"{n}. {_clip(x, 110)}" for n, x in enumerate(st.last_list, 1)], 1))
    sections.append(("Follow-ups", followup_lines(st, now), 1))
    from stella import wrapup

    sections.append(("Finished, not wrapped up", wrapup.pending_lines(st, now), 1))

    oo = sorted(st.open_orders(), key=lambda o: o.seq, reverse=True)
    order_lines = []
    for o in oo:
        stale = " (STALE, confirm?)" if o.stale(now) else ""
        team = f" → team {o.team}" if o.team else ""
        order_lines.append(f"- #{o.seq} {_age(o.ts, now)} ago in {o.session_label}{team}{stale}: {_clip(o.text)}")
    sections.append(("Open orders", order_lines, 0))

    running = [t for t in st.teams.values() if t.status in {"running", "needs-you"}]
    team_lines = [
        f"- {t.name} ({t.archetype}, {_age(t.ts, now)}, {t.status}){': ' + _clip(t.last_report, 80) if t.last_report else ''}"
        for t in sorted(running, key=lambda t: t.seq, reverse=True)
    ]
    sections.append(("Running teams", team_lines, 2))

    recent = [d for d in st.decisions if (now - ledger.parse_ts(d)).days < 7]
    dec_lines = [f"- #{d['seq']} {_clip(d.get('text', ''))}" for d in reversed(recent)]
    sections.append(("Recent decisions (7 days)", dec_lines, 3))

    header = [f"Stella state brief (ledger at #{st.last_seq}, {now:%Y-%m-%d %H:%M})"]
    budget = cap - len(header)

    def size(secs):
        return sum(1 + len(ls) for _, ls, _ in secs if ls)

    # Drop the lowest-value lines first until it fits (one line is kept free for
    # the "+N more" footer): decisions, then team detail, then attention, and
    # open orders last.
    trimmed = [(t, list(ls), p) for t, ls, p in sections]
    omitted: dict[str, int] = {}
    for prio in (3, 2, 1, 0):
        for t, ls, p in trimmed:
            while p == prio and ls and size(trimmed) + 1 > budget:
                ls.pop()
                omitted[t] = omitted.get(t, 0) + 1
    out = list(header)
    for t, ls, _ in trimmed:
        if ls:
            out.append(f"{t}:")
            out.extend(ls)
    if omitted:
        out.append(
            "+" + ", ".join(f"{n} more in {t.lower()}" for t, n in omitted.items())
            + ": `~/.local/bin/stella orders`, `… attention`, `… followup list`, `… fleet`"
        )
    if len(out) == 1:
        out.append("Nothing open.")
    return "\n".join(out[:cap])
