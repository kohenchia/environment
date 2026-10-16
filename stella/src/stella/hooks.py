"""Claude Code hook handlers. `stella hook <event>` reads the hook JSON on stdin.

* UserPromptSubmit: decide whether the message is addressed to Stella (in
  Stella's own session, always). If it is: record it verbatim in the ledger *before the model runs*,
  then inject the persona, what other sessions recorded since this session last
  looked, and possible conflicts. If it isn't: hand the turn back to the session.
* SessionStart: in Stella's own session, inject the full context and brief (also
  after /compact). In a team window, record which session is the lead. Anywhere,
  if the scheduler is down and a run is overdue, start a catch-up pass.
* SessionEnd: a team lead that exits without `stella done` raises an attention item.
* PreToolUse: the push gate and the leak guard.
"""

from __future__ import annotations

import json
import os
import re
import sys
import traceback

from stella import address, brief, context, gate, leak, ledger, notify, run, scheduler, sessions, state, targets
from stella.config import settings

HANDBACK = (
    "This message is not addressed to Stella. Answer as this session, continuing its own task;"
    " do not act as Stella or relay to teams."
)
UNAVAILABLE = "STELLA LEDGER UNAVAILABLE ({err}). Tell the owner; do not act on orders until it is fixed."


def _emit(event: str, text: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}))


def _deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}))


def _label(data: dict) -> str:
    team = os.environ.get("STELLA_TEAM")
    if run.is_self():
        return "stella"
    if team:
        return f"team {team}"
    cwd = data.get("cwd") or ""
    return f"{os.path.basename(cwd) or '?'}:{(data.get('session_id') or '')[:6]}"


_NEG = re.compile(r"\b(don'?t|do not|never|not|no|stop|cancel|hold|wait)\b", re.I)


def _push_intent(text: str, data: dict) -> dict | None:
    body = address.strip_address(text)
    if _NEG.search(body):
        return None
    for root in gate.guarded_repos():
        name = re.escape(gate.alias(root))
        if re.match(rf"^(?:(?:please|ok|okay|now|go ahead and)[,\s]+)*push\b[^.?!\n]{{0,40}}\b{name}\b", body, re.I):
            branch = gate.current_branch(root)
            return {"repo": gate.alias(root), "sha": gate.head(root, branch), "branch": branch}
    return None


def _affirmed_question(text: str, session: str, st: state.State) -> dict | None:
    if not address.is_affirmative(text) or not st.push_questions:
        return None
    q = st.push_questions[-1]
    if q.get("session") not in {session, None} and not run.is_self():
        return None
    if (ledger.now() - ledger.parse_ts(q)).total_seconds() > settings().push_intent_minutes * 60:
        return None
    root = gate.resolve_alias(q["repo"])
    if gate.head(root, q["branch"]) != q["sha"]:
        return None
    return {"repo": q["repo"], "sha": q["sha"], "branch": q["branch"], "question": q["seq"]}


def prompt(data: dict) -> None:
    if os.environ.get("STELLA_HEADLESS") == "1":
        return
    text = data.get("prompt") or ""
    sid = data.get("session_id") or "unknown"
    own = run.is_self()
    team = os.environ.get("STELLA_TEAM")
    addressed = own or address.is_addressed(text)
    sess = sessions.load(sid)

    if not addressed:
        if team and sess.get("seen_first") and not text.startswith("[Stella]"):
            try:
                ledger.append("direct", by="hook", team=team, text=text, session=sid, session_label=_label(data))
            except OSError:
                pass
        if team and not sess.get("seen_first"):
            sess["seen_first"] = True
            sessions.save(sid, sess)
        if sess.get("last_addressed"):
            sess["last_addressed"] = False
            sessions.save(sid, sess)
            _emit("UserPromptSubmit", HANDBACK)
        return

    try:
        st_before = state.fold()
        team_names = set(st_before.teams)
        kind = address.kind(text)
        order = ledger.append(
            "order", by="hook", text=text, kind=kind, session=sid, session_label=_label(data),
            cwd=data.get("cwd"), targets=targets.extract(text, team_names),
        )
        intent = _push_intent(text, data) or _affirmed_question(text, sid, st_before)
        if intent:
            ledger.append("push_intent", by="hook", order=order["seq"], session=sid, **intent)
        st = state.fold()
        delta = brief.delta(sid, sess.get("cursor", 0))
        conflicts = brief.conflict_lines(st, order["seq"]) if kind == "instruction" else []
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
    if intent:
        parts.append(f"Recorded as an explicit push approval for {intent['repo']} at {intent['sha'][:7]}: run `~/.local/bin/stella push {intent['repo']}`.")
    if delta:
        parts.append("Since this session last looked, other sessions recorded:\n" + "\n".join(f"- {d}" for d in delta))
    if conflicts:
        parts.append(
            "POSSIBLE CONFLICT with open orders (same target). Decide whether the new order contradicts them;"
            " if it does, ask the owner before acting, then record the outcome with"
            " `~/.local/bin/stella decide \"...\" --supersedes N`:\n" + "\n".join(f"- {c}" for c in conflicts)
        )
    sess["cursor"] = st.last_seq
    sess["last_addressed"] = True
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
        except Exception as e:  # noqa: BLE001
            text = UNAVAILABLE.format(err=f"{type(e).__name__}: {e}")
        _emit("SessionStart", text)
        return
    if team:
        if source == "startup":
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
    st = state.fold()
    t = st.teams.get(team)
    if t and t.status not in {"done", "ended"}:
        ledger.append("ended", by="hook", team=team, session=data.get("session_id"), reason=data.get("reason"))
        notify.notify("Stella", f"Team {team} exited without reporting done")


_WRITEY = re.compile(r"(>|\btee\b|\bsed\s+-i|\bperl\s+-[pi]|<<|\bcp\b|\bmv\b|\bgit\s+commit\b|\bpython3?\b|\bcat\b.*>|\bprintf\b|\becho\b)")


def pretool(data: dict) -> None:
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    cwd = data.get("cwd") or os.getcwd()
    if tool == "Bash":
        cmd = ti.get("command", "")
        for v in (gate.check_bash(cmd, cwd), gate.check_review_window(cmd)):
            if v.deny:
                return _deny(v.reason)
        g = leak.guard()
        if g.configured and _WRITEY.search(cmd):
            root = leak.protected_root(cwd, g) or next((r for r in g.protect if str(r) in cmd or str(r).replace(os.path.expanduser("~"), "~") in cmd), None)
            if root:
                hit = _leak_hit(cmd, "command", g)
                if hit:
                    return _deny(hit)
        return
    if tool in {"Write", "Edit", "MultiEdit", "NotebookEdit"}:
        path = ti.get("file_path") or ti.get("notebook_path") or ""
        v = gate.check_path_write(path)
        if v.deny:
            return _deny(v.reason)
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


HANDLERS = {"prompt": prompt, "session-start": session_start, "session-end": session_end, "pretool": pretool}


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
