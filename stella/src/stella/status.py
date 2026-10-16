"""The status line every turn ends with, and the readiness check `gg` shares with it.

The last line of a session's final message of a turn is exactly one of:

    NEXT FOR YOU: <the one or two things only the owner can do or decide>
    ALL DONE: ready to wrap up. Type gg.
    WORKING: <what is still running>

so the owner never rereads the output to ask whether anything is left for them. The Stop hook enforces it:
`judge` compares the final message with the facts (`blockers`) and, when the line is missing or contradicts
them (ALL DONE while commits are unpushed, a push was deferred, a needs-you flag is open, files are
uncommitted), the hook blocks the stop once with the exact line to write. `stop_hook_active` means that
block was already used this turn, so the hook never loops.

`blockers` is also what `gg` and `stella wrapup <team>` check before closing a session: ALL DONE is only
true when `gg` would succeed. Stella's own session is the exception: she is never wrapped up, so her
blockers are the items from `stella attention` and her "nothing to do" line says so instead of "Type gg".
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from stella import finish, gate, state, wrapup

MARKERS = ("NEXT FOR YOU:", "ALL DONE:", "WORKING:")
ALL_DONE = "ALL DONE: ready to wrap up. Type gg."
ALL_DONE_STELLA = "ALL DONE: nothing needs you."

RULE = (
    "Status line (structural, the Stop hook checks it): the LAST line of your final message of every turn is exactly one of"
    " `NEXT FOR YOU: <the one or two things only the owner can do or decide: a question, a decision, a deferred push,"
    " a review to post>`, `ALL DONE: ready to wrap up. Type gg.` (only when nothing is unpushed, uncommitted, deferred or"
    " open for the owner), or `WORKING: <what is still running>` (only when the turn ends while background work continues)."
    " In plain words, no list after it. (`gg` wraps up just this session; `tyfp` wraps up every session that is done.)"
)


TURN_RULE = (
    "Status line, checked by the Stop hook: the LAST line of your final message ends with exactly one of"
    " `NEXT FOR YOU: <the one or two things only the owner can do or decide>`,"
    " `ALL DONE: ready to wrap up. Type gg.` (only if nothing is unpushed, uncommitted, deferred or open for the owner), or"
    " `WORKING: <what is still running>` (only if background work continues after this turn)."
)
STELLA_TURN_RULE = (
    "Status line, checked by the Stop hook: the LAST line of your final message ends with exactly one of"
    " `NEXT FOR YOU: <the items from `~/.local/bin/stella attention`, or the one decision you need>`,"
    " `ALL DONE: nothing needs you.` (only when `stella attention` is empty and you owe no answer), or"
    " `WORKING: <what is still running>`. You are never wrapped up, so there is no gg line for you."
)


def turn_rule(own: bool) -> str:
    return STELLA_TURN_RULE if own else TURN_RULE


@dataclass
class Blocker:
    kind: str  # push | deferred | dirty | asking | attention
    text: str  # one clause: what is open
    ask: str  # what the owner is asked, for the NEXT FOR YOU line
    command: str = ""  # for a push: the push that raises the prompt


# ---------------------------------------------------------------- facts


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def _worked_roots(sess: dict, cwd: str, own: bool, t: state.Team | None) -> dict[Path, Path]:
    """Every git checkout the session worked in -> a path inside it: its directory, the repos it committed in and,
    for a team, the repos its reports name. Repos without a remote are included (they can be dirty)."""
    out = dict(finish._worked(sess, cwd, own))
    if not own and cwd:
        top = wrapup.toplevel(Path(os.path.expanduser(cwd)))
        if top:
            out.setdefault(top, top)
    if t:
        for top in wrapup.repos_of(t):
            out.setdefault(top, top)
    return out


def blockers(st: state.State, sid: str, cwd: str, own: bool = False, t: state.Team | None = None) -> list[Blocker]:
    """What is still open for the owner on this session. Empty means nothing is left: `gg` may close it."""
    if own:
        finish.clear_pushed(st)
        return [Blocker("attention", i.text, i.text) for i in st.attention()]
    sess = _session(sid)
    out: list[Blocker] = []
    if t and (t.asking or t.status == "needs-you"):
        q = " ".join((t.last_report or "").split())[:100]
        out.append(Blocker("asking", f"an open question: {q}" if q else "an open question",
                           f"answer the open question: {q}" if q else "answer the open question"))
    mine = (t.sessions if t else set()) | ({sid} if sid else set()) | ({t.session_id} if t and t.session_id else set())
    for ev in st.push_deferred:
        if not (ev.get("team") == (t.name if t else None) and t) and ev.get("session") not in mine:
            continue
        key = f"push-deferred:{ev.get('repo')}@{ev.get('sha')}"
        path, sha = ev.get("path"), ev.get("sha")
        if key in st.acked or not (path and sha) or wrapup._git(Path(path), "branch", "-r", "--contains", sha):
            continue  # dropped by the owner, or the commit reached a remote
        what = f"{ev.get('repo')} {ev.get('branch') or str(sha)[:7]} {str(sha)[:7]}"
        out.append(Blocker("deferred", f"push of {what} was deferred",
                           f"push of {what} is deferred: push it or drop it (`stella ack {key}`)"))
    deferred_heads = {f"{e.get('path')}@{e.get('sha')}" for e in st.push_deferred}
    for root, where in _worked_roots(sess, cwd, own, t).items():
        problem = wrapup._git(root, "status", "--porcelain")
        if problem:
            n = len(problem.splitlines())
            out.append(Blocker("dirty", f"uncommitted changes in {root.name} ({_plural(n, 'file')})",
                               f"commit or discard the changes in {root.name}"))
        n = finish._ahead(where) if wrapup._git(root, "remote") else 0
        head = gate._head(where)
        if not n or not head or gate.is_approved(root, where) or f"{root}@{head}" in deferred_heads \
                or finish.is_deferred(f"{root}@{head}"):
            continue  # deferred ones are listed above (or dropped by the owner)
        branch = gate._git_out(where, "rev-parse", "--abbrev-ref", "HEAD")
        out.append(Blocker("push", f"{_plural(n, 'unpushed commit')} in {root.name} ({branch})",
                           f"approve the push of {root.name} {branch} ({_plural(n, 'commit')})",
                           f"git -C {root} push -u origin {branch}"))
    return out


def _session(sid: str) -> dict:
    from stella import sessions

    return sessions.load(sid) if sid else {}


# ---------------------------------------------------------------- the line


def expected(bl: list[Blocker], own: bool = False) -> str:
    """The exact line the facts call for."""
    if bl:
        asks = [b.ask for b in bl]
        shown = "; ".join(asks[:2]) + (f"; and {len(asks) - 2} more" if len(asks) > 2 else "")
        return f"NEXT FOR YOU: {shown}"
    return ALL_DONE_STELLA if own else ALL_DONE


_STRIP = " \t*_`>#-"


def last_line(text: str) -> str:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return lines[-1].strip(_STRIP) if lines else ""


def marker(text: str) -> str | None:
    line = last_line(text)
    return next((m for m in MARKERS if line.startswith(m)), None)


def final_message(data: dict) -> str:
    """The turn's last assistant text: the hook's own field when Claude Code gives one, else the transcript's tail."""
    msg = data.get("last_assistant_message")
    if isinstance(msg, str) and msg.strip():
        return msg
    path = data.get("transcript_path")
    if not path:
        return ""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 400_000))
            raw = f.read().decode("utf-8", "replace")
    except OSError:
        return ""
    for line in reversed(raw.splitlines()):
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") != "assistant":
            continue
        content = (ev.get("message") or {}).get("content")
        if isinstance(content, str):
            text = content
        else:
            text = "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")
        if text.strip():
            return text
    return ""


def judge(text: str, bl: list[Blocker], own: bool = False) -> str | None:
    """None when the final message ends with a status line the facts allow; else why not, with the exact line."""
    m = marker(text)
    want = expected(bl, own)
    if m is None:
        return (f"Your final message does not end with the status line. Write the last line as exactly this one, in plain words,"
                f" as the LAST line of your final message (reply with one or two sentences of context, then the line): {want}")
    if m == "ALL DONE:" and bl:
        return ("Your final message ends with ALL DONE, but not everything is done: " + "; ".join(b.text for b in bl)
                + f". Make the last line exactly: {want}")
    if m == "WORKING:" and any(b.kind in {"asking", "deferred"} for b in bl):
        return ("Your final message ends with WORKING, but the owner has something open: "
                + "; ".join(b.text for b in bl if b.kind in {"asking", "deferred"}) + f". Make the last line exactly: {want}")
    return None


def stop_reason(data: dict, sid: str, own: bool, t: state.Team | None, push_block: bool) -> str | None:
    """The reason to block the stop for a missing or false status line, or None."""
    if data.get("stop_hook_active"):
        return None
    st = state.fold()
    bl = blockers(st, sid, data.get("cwd") or os.getcwd(), own=own, t=t)
    if push_block:
        # The push comes first and its outcome is not known yet: give the rule, not the line.
        return RULE + " After the push: if the owner declined, " + (
            "write the NEXT FOR YOU line naming the deferred push; if it went through and nothing else is open, the ALL DONE line.")
    return judge(final_message(data), bl, own)


_GG = re.compile(r"^gg$", re.I)


def is_gg(prompt: str) -> bool:
    return bool(_GG.match((prompt or "").strip()))
