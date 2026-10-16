"""Claude Code hook handlers. `stella hook <event>` reads the hook JSON on stdin.

* UserPromptSubmit: decide whether the message is addressed to Stella (in
  Stella's own session, always). If it is: record it verbatim in the ledger *before the model runs*,
  then inject the persona, what other sessions recorded since this session last
  looked, and possible conflicts. If it isn't: hand the turn back to the session.
  In Stella's own session, a prompt that is exactly a wake line or restart note her
  tooling typed (wake.take_system_note) is a system note, never an order.
* SessionStart: in Stella's own session, inject the full context and brief (also
  after /compact). In a team window, record which session is the lead. Anywhere,
  if the scheduler is down and a run is overdue, start a catch-up pass.
* SessionEnd: a team lead that exits without `stella done` raises an attention item,
  and unless the owner closed it by hand, wakes Stella.
* PreToolUse: the push prompt (a push from a repo with a remote asks the owner first) and the leak guard.
* PostToolUse: remembers an approved push's head so it is not asked twice, and the repos a session committed in.
* Stop: a session that ends its turn with unpushed commits in repos it worked in is told once to push now, so the
  push prompt appears (`finish`); a push the owner declined is recorded as deferred and not asked again.
"""

from __future__ import annotations

import json
import os
import re
import sys
import traceback

from stella import address, brief, context, finish, gate, leak, ledger, notify, run, scheduler, sessions, state, status, targets, wake, wrapup

HANDBACK = (
    "This message is not addressed to Stella. Answer as this session, continuing its own task;"
    " do not act as Stella or relay to teams."
)
UNAVAILABLE = "STELLA LEDGER UNAVAILABLE ({err}). Tell the owner; do not act on orders until it is fixed."
SYSTEM_NOTE = (
    "This message was typed into your window by Stella's own tooling (a wake line or a restart note), not by"
    " {owner}. It is not an order: nothing was recorded for it, and it neither opens nor closes any order."
    " If it is a wake line: review your open follow-ups and the fleet, act on what is unblocked (READY follow-ups;"
    " close each with `~/.local/bin/stella followup close N` once done), then tell {owner} in a line or two what"
    " happened and what you did. If nothing is unblocked, say so in one line. Finished teams are wrapped up only when the owner"
    " decides; never close one yourself. The brief lists them under \"Finished, not wrapped up\"."
)


def _emit(event: str, text: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}))


def _decide(decision: str, reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": decision, "permissionDecisionReason": reason}}))


def _deny(reason: str) -> None:
    _decide("deny", reason)


def _ask(reason: str) -> None:
    """Claude Code shows the owner its own yes/no prompt for this tool call."""
    _decide("ask", reason)


def _label(data: dict) -> str:
    team = os.environ.get("STELLA_TEAM")
    if run.is_self():
        return "stella"
    if team:
        return f"team {team}"
    cwd = data.get("cwd") or ""
    return f"{os.path.basename(cwd) or '?'}:{(data.get('session_id') or '')[:6]}"


def prompt(data: dict) -> None:
    if os.environ.get("STELLA_HEADLESS") == "1":
        return
    text = data.get("prompt") or ""
    sid = data.get("session_id") or "unknown"
    own = run.is_self()
    team = os.environ.get("STELLA_TEAM")
    if status.is_gg(text):
        return _gg(data)
    addressed = own or address.is_addressed(text)
    sess = sessions.load(sid)

    if own and wake.take_system_note(text):
        return _system_note(sid, sess)

    if not addressed:
        if team and sess.get("seen_first") and not text.startswith("[Stella]"):
            try:
                ledger.append("direct", by="hook", team=team, text=text, session=sid, session_label=_label(data))
            except OSError:
                pass
        if team and not sess.get("seen_first"):
            sess["seen_first"] = True
            sessions.save(sid, sess)
        parts = []
        if sess.get("last_addressed"):
            sess["last_addressed"] = False
            sessions.save(sid, sess)
            parts.append(HANDBACK)
        if team or _in_stella_tmux():
            parts.append(status.turn_rule(False))
        if parts:
            _emit("UserPromptSubmit", "\n\n".join(parts))
        return

    try:
        team_names = set(state.fold().teams)
        kind = address.kind(text)
        order = ledger.append(
            "order", by="hook", text=text, kind=kind, session=sid, session_label=_label(data),
            cwd=data.get("cwd"), targets=targets.extract(text, team_names),
        )
        st = state.fold()
        delta = brief.delta(sid, sess.get("cursor", 0))
        conflicts = brief.conflict_lines(st, order["seq"]) if kind == "instruction" else []
        woke = wake.drain() if own else None  # news that came while she was busy, not yet typed to her
        followups = brief.followup_lines(st) if own else []
        unwrapped = wrapup.pending_lines(st) if own or sess.get("context_loaded") else []
    except Exception as e:  # noqa: BLE001 - the model must hear about any failure
        _emit("UserPromptSubmit", UNAVAILABLE.format(err=f"{type(e).__name__}: {e}"))
        return

    parts: list[str] = []
    if not own and not sess.get("context_loaded"):
        parts.append(context.render("turn", include_brief=True))
        sess["context_loaded"] = True
    elif not own:
        parts.append("This turn is addressed to you, Stella (follow the `stella` skill). After it, the owner is talking to the session again.")
    parts.append(f"Recorded as ledger #{order['seq']} ({kind}).")
    parts.append(status.turn_rule(own))
    if delta:
        parts.append("Since this session last looked, other sessions recorded:\n" + "\n".join(f"- {d}" for d in delta))
    if conflicts:
        parts.append(
            "POSSIBLE CONFLICT with open orders (same target). Decide whether the new order contradicts them;"
            " if it does, ask the owner before acting, then record the outcome with"
            " `~/.local/bin/stella decide \"...\" --supersedes N`:\n" + "\n".join(f"- {c}" for c in conflicts)
        )
    if woke:
        parts.append(woke)
    if followups:
        parts.append(FOLLOWUPS + "\n".join(followups))
    if unwrapped:
        parts.append(wrapup.HEADER + "\n".join(unwrapped))
    sess["cursor"] = st.last_seq
    sess["last_addressed"] = True
    sessions.save(sid, sess)
    _emit("UserPromptSubmit", "\n\n".join(parts))


def _in_stella_tmux() -> bool:
    sock = os.environ.get("TMUX", "").split(",", 1)[0]
    return bool(sock and os.environ.get("TMUX_PANE") and wrapup.in_stella_server(sock))


def _block_prompt(reason: str) -> None:
    """The prompt never reaches the model; the owner sees the reason."""
    print(json.dumps({"decision": "block", "reason": reason}))


def _gg(data: dict) -> None:
    """The owner typed `gg`: wrap this session up (the same code path as `stella wrap` and `stella wrapup <team>`)."""
    sid, cwd = data.get("session_id") or "", data.get("cwd") or os.getcwd()
    try:
        w = wrapup.wrap_session(sid, cwd, delay=float(os.environ.get("STELLA_GG_DELAY") or 2))
    except Exception as e:  # noqa: BLE001
        return _block_prompt(f"gg failed ({type(e).__name__}: {e}); nothing closed.")
    if w.closed or not w.push_blocks:
        return _block_prompt(w.message)
    # An unpushed commit blocks the close: the model runs the push, so Claude Code's own prompt appears.
    res = finish.check(sid, cwd, own=False, may_block=True)
    how = res.block or "Run the push for the unpushed commits again (`git push -u origin <branch>`), so the push prompt appears."
    _emit("UserPromptSubmit",
          f"The owner typed `gg` to wrap this session up, and it did not close: {w.message}. Do not ask in chat and tell"
          f" them nothing to run. {how}\nThen say in one line what still blocks the close, if anything, and end with the"
          " status line (NEXT FOR YOU: … while something is open; ALL DONE: ready to wrap up. Type gg. if nothing is).")


FOLLOWUPS = "Your open follow-ups (act on READY ones; `~/.local/bin/stella followup close N` when done):\n"


def _system_note(sid: str, sess: dict) -> None:
    """A wake line (or restart note) in Stella's own session: context for her turn, and no order."""
    from stella.config import settings

    try:
        newer = wake.drain()  # news since the line was typed: told now, not typed again
        st = state.fold()
        delta = brief.delta(sid, sess.get("cursor", 0))
        followups = brief.followup_lines(st)
        unwrapped = wrapup.pending_lines(st)
    except Exception as e:  # noqa: BLE001
        _emit("UserPromptSubmit", UNAVAILABLE.format(err=f"{type(e).__name__}: {e}"))
        return
    parts = [SYSTEM_NOTE.format(owner=settings().owner), status.turn_rule(True)]
    if newer:
        parts.append(newer)
    if followups:
        parts.append(FOLLOWUPS + "\n".join(followups))
    if unwrapped:
        parts.append(wrapup.HEADER + "\n".join(unwrapped))
    if delta:
        parts.append("Since this session last looked, other sessions recorded:\n" + "\n".join(f"- {d}" for d in delta))
    sess["cursor"] = st.last_seq
    sessions.save(sid, sess)
    _emit("UserPromptSubmit", "\n\n".join(parts))


def session_start(data: dict) -> None:
    if os.environ.get("STELLA_HEADLESS") == "1":
        return
    sid = data.get("session_id") or "unknown"
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if env_file:
        # Lets `stella` commands run by the model tag ledger events with this session.
        try:
            with open(env_file, "a") as f:
                f.write(f"export STELLA_SESSION_ID={sid}\n")
        except OSError:
            pass
    source = data.get("source")
    team = os.environ.get("STELLA_TEAM")
    scheduler.catch_up_if_needed()
    if run.is_self():
        try:
            text = context.render("self", include_brief=True)
            st = state.fold()
            sess = sessions.load(sid)
            sess.update(cursor=st.last_seq, context_loaded=True, own=True)
            sessions.save(sid, sess)
            run.remember_session(sid)
            wake.cover_all()  # the brief below has it all; nothing is left to wake her for
        except Exception as e:  # noqa: BLE001
            text = UNAVAILABLE.format(err=f"{type(e).__name__}: {e}")
        _emit("SessionStart", text)
        return
    if team:
        known = state.fold().teams.get(team) if source == "resume" else None
        if source == "startup" or (known and known.session_id != sid):  # a resume may get a new id
            ledger.append("started", by="hook", team=team, session=sid)
        elif source == "compact":
            from stella.config import store_dir

            p = store_dir() / "launch" / f"{team}.prompt.md"
            if p.exists():
                _emit("SessionStart", "Reminder after compaction, your standing instructions:\n" + p.read_text())


def session_end(data: dict) -> None:
    team = os.environ.get("STELLA_TEAM")
    if not team or os.environ.get("STELLA_HEADLESS") == "1":
        return
    from stella import launch

    if launch.respawning(team):  # killed on purpose by `stella respawn`; a new process has taken over
        return
    st = state.fold()
    t = st.teams.get(team)
    if t and t.status not in {"done", "ended"}:
        ledger.append("ended", by="hook", team=team, session=data.get("session_id"), reason=data.get("reason"),
                      window_closed=wake.window_gone(t) or None)
        t.end_reason = data.get("reason")
        if t.end_reason != state.DELIBERATE_END:
            notify.notify("Stella", "T" + t.ended_text()[1:])
        wake.kick()


_WRITEY = re.compile(r"(>|\btee\b|\bsed\s+-i|\bperl\s+-[pi]|<<|\bcp\b|\bmv\b|\bgit\s+commit\b|\bpython3?\b|\bcat\b.*>|\bprintf\b|\becho\b)")


def pretool(data: dict) -> None:
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    cwd = data.get("cwd") or os.getcwd()
    if tool == "Bash":
        cmd = ti.get("command", "")
        g = leak.guard()
        if g.configured and _WRITEY.search(cmd):
            root = leak.protected_root(cwd, g) or next((r for r in g.protect if str(r) in cmd or str(r).replace(os.path.expanduser("~"), "~") in cmd), None)
            if root:
                hit = _leak_hit(cmd, "command", g)
                if hit:
                    return _deny(hit)
        v = gate.check_bash(cmd, cwd)
        if v.decision == "ask":
            finish.remember_asked(data.get("session_id") or "", v.asked)
            return _ask(v.reason)
        return
    if tool in {"Write", "Edit", "MultiEdit", "NotebookEdit"}:
        path = ti.get("file_path") or ti.get("notebook_path") or ""
        g = leak.guard()
        if g.configured and leak.protected_root(path, g):
            content = "\n".join(
                [ti.get("content", ""), ti.get("new_string", ""), ti.get("new_source", "")]
                + [e.get("new_string", "") for e in ti.get("edits", []) or []]
            )
            hit = _leak_hit(content + "\n" + path, path, g)
            if hit:
                return _deny(hit)


def _leak_hit(text: str, where: str, g: leak.Guard) -> str | None:
    try:
        rules = leak.load_rules(g)
    except leak.DenylistMissing as e:
        return f"STELLA LEAK GUARD: the denylist is missing ({e}); refusing to write to a protected repo."
    hits = leak.scan_text(text, where, rules)
    if not hits:
        return None
    terms = sorted({h.term for h in hits})
    return (
        "STELLA LEAK GUARD: this repo must stay free of extension-private information, and the content contains: "
        + ", ".join(repr(t) for t in terms[:10])
        + ". Rewrite it generically (a fictional example, or no example)."
    )


def posttool(data: dict) -> None:
    """A push command ran, so the owner approved it (or the session was told to push): remember the head."""
    if data.get("tool_name") == "Bash":
        cmd, cwd = (data.get("tool_input") or {}).get("command", ""), data.get("cwd") or os.getcwd()
        gate.record_approval(cmd, cwd)
        finish.remember_commits(data.get("session_id") or "", cmd, cwd)


def stop(data: dict) -> None:
    """The session ends its turn: with unpushed commits in repos it worked in, make it push so the prompt appears."""
    if os.environ.get("STELLA_HEADLESS") == "1" or not data.get("session_id"):
        return
    own = run.is_self()
    team = os.environ.get("STELLA_TEAM")
    res = finish.check(data["session_id"], data.get("cwd") or os.getcwd(), own=own,
                       may_block=not data.get("stop_hook_active"))
    out: dict = {}
    reason = res.block
    if own or team or _in_stella_tmux():
        try:
            t = state.fold().teams.get(team or "")
            line = status.stop_reason(data, data["session_id"], own, t, push_block=bool(res.block))
        except Exception:  # noqa: BLE001 - a broken check must not trap the session
            line = None
        if line:
            reason = f"{res.block}\n\n{line}" if res.block else line
    if reason:
        out.update(decision="block", reason=reason)
    if res.deferred:
        out["systemMessage"] = "; ".join(res.deferred)
    if out:
        print(json.dumps(out))


HANDLERS = {"prompt": prompt, "session-start": session_start, "session-end": session_end, "pretool": pretool,
            "posttool": posttool, "stop": stop}


def main(event: str) -> int:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        data = {}
    try:
        HANDLERS[event](data)
    except Exception:  # noqa: BLE001
        traceback.print_exc(file=sys.stderr)
        return 1
    return 0
