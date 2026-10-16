"""The status block every turn ends with, and the readiness check `gg` shares with it.

The last block of a session's final message of a turn (nothing after it) is a rule line of 40 U+2501 characters,
then exactly one of:

    🟧 **NEXT FOR YOU** (3)
    1. approve the push of X
    2. decide Y
    3. post the review of Z

    🟩 **ALL DONE** — ready to wrap up. Type `gg`.

    🟦 **WORKING** — <what is still running>

so the owner never rereads the output to ask whether anything is left for them, and can answer with a number
("do 2"). The Stop hook enforces it: `judge` compares the final message with the facts (`blockers`) and, when the
block is missing, malformed (the (N) count differs from the numbered items, no items) or contradicts the facts
(ALL DONE while commits are unpushed, a push was deferred, a needs-you flag is open, files are uncommitted), the
hook blocks the stop once with the exact block to write. `stop_hook_active` means that block was already used this
turn, so the hook never loops. The retired one-line forms (`NEXT FOR YOU: ...`, `ALL DONE: ...`, `WORKING: ...`
as the last line) are still accepted for one release, but block once with the new block, so a running session
that was taught the old rule is moved over without a loop.

`blockers` is also what `gg` and `stella wrapup <team>` check before closing a session: ALL DONE is only
true when `gg` would succeed. Stella's own session is the exception: she is never wrapped up, so her
blockers are the items from `stella attention` (numbered in the order shown) and her "nothing to do" line says
so instead of "Type gg".
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from stella import finish, gate, related, state, wrapup

RULE_CH = "\u2501"
RULE_LINE = RULE_CH * 40
ALL_DONE = f"{RULE_LINE}\n🟩 **ALL DONE** — ready to wrap up. Type `gg`."
ALL_DONE_STELLA = f"{RULE_LINE}\n🟩 **ALL DONE** — nothing needs you."

# The retired one-line forms, accepted once with a block.
MARKERS = ("NEXT FOR YOU:", "ALL DONE:", "WORKING:")

FORMAT = (
    "the LAST block of your final message, nothing after it, plain markdown (not in a code fence): a line of 40 ━ characters"
    " on its own line, then exactly one of `🟧 **NEXT FOR YOU** (N)` followed by N numbered items `1.` `2.` … (one thing"
    " only the owner can do or decide per item, short and imperative: a question, a decision, a deferred push, a review to"
    " post), `🟩 **ALL DONE** — ready to wrap up. Type `gg`.` (only when nothing is unpushed, uncommitted, deferred or open"
    " for the owner), or `🟦 **WORKING** — <what is still running>` (only when the turn ends while background work"
    " continues)."
)
NUMBERS = (
    "When the owner answers with just a number, or \"do 2\" / \"approve 1 and 3\", he means items of your last NEXT FOR YOU block."
)

RULE = (
    f"Status block (structural, the Stop hook checks it): {FORMAT} {NUMBERS}"
    " (`gg` wraps up just this session; `tyfp` wraps up every session that is done.)"
)

TURN_RULE = f"Status block, checked by the Stop hook: {FORMAT} {NUMBERS}"
STELLA_TURN_RULE = (
    "Status block, checked by the Stop hook: the LAST block of your final message, nothing after it, plain markdown (not in a"
    " code fence): a line of 40 ━ characters on its own line, then `🟧 **NEXT FOR YOU** (N)` with the N items from"
    " `~/.local/bin/stella attention` (or the one decision you need) numbered `1.` `2.` … in the order shown, or"
    " `🟩 **ALL DONE** — nothing needs you.` (only when `stella attention` is empty and you owe no answer), or"
    " `🟦 **WORKING** — <what is still running>`. You are never wrapped up, so there is no gg for you."
    f" When you present a list, record it with `~/.local/bin/stella shown \"<item 1>\" \"<item 2>\" …`. {NUMBERS}"
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
    ctx = related.context(st, sid, t)
    for root, where in _worked_roots(sess, cwd, own, t).items():
        res = related.check(root, None, ctx)
        if res.blocking:
            out.append(Blocker("dirty", res.message(root.name), f"commit or discard the changes in {root.name}"))
        n = finish._ahead(where) if wrapup._git(root, "remote") else 0
        head = gate._head(where)
        if not n or not head or gate.is_approved(root, where) or f"{root}@{head}" in deferred_heads \
                or finish.is_deferred(f"{root}@{head}"):
            continue  # deferred ones are listed above (or dropped by the owner)
        branch = gate._git_out(where, "rev-parse", "--abbrev-ref", "HEAD")
        out.append(Blocker("push", f"{_plural(n, 'unpushed commit')} in {root.name} ({branch})",
                           f"approve the push of {root.name} {branch} ({_plural(n, 'commit')})",
                           f"~/.local/bin/stella push --plan -C {root}"))
    return out


def left_alone(st: state.State, sid: str, cwd: str, t: state.Team | None = None) -> str:
    """The calm info line for what `blockers` ignored as not this session's: 'left alone: 3 untracked files in proj, not from
    this session'. Empty when nothing was."""
    ctx = related.context(st, sid, t)
    return related.left_line([(root.name, related.check(root, None, ctx)) for root in _worked_roots(_session(sid), cwd, False, t)])


def _session(sid: str) -> dict:
    from stella import sessions

    return sessions.load(sid) if sid else {}


# ---------------------------------------------------------------- the line


def _item(text: str, n: int = 150) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def next_block(items: list[str]) -> str:
    """The NEXT FOR YOU block for these items, numbered 1..N in the order given."""
    return "\n".join([RULE_LINE, f"🟧 **NEXT FOR YOU** ({len(items)})"] + [f"{i}. {_item(t)}" for i, t in enumerate(items, 1)])


def working_block(what: str) -> str:
    return f"{RULE_LINE}\n🟦 **WORKING** — {what}"


def expected(bl: list[Blocker], own: bool = False) -> str:
    """The exact block the facts call for: one numbered item per blocker."""
    if bl:
        return next_block([b.ask for b in bl])
    return ALL_DONE_STELLA if own else ALL_DONE


@dataclass
class Block:
    kind: str  # NEXT FOR YOU | ALL DONE | WORKING
    count: int | None  # the (N) in the label line, if any
    items: list[str]
    numbers: list[int]  # the numbers the items carry
    extra: list[str]  # text after the label (or after the items) that is not part of the block


_LABEL = re.compile(r"^(?:[\U0001F7E0-\U0001F7EB]\uFE0F?\s*)?[*_]*\s*(NEXT FOR YOU|ALL DONE|WORKING)\b", re.I)
_ITEM = re.compile(r"^\s*(\d+)[.)]\s+(\S.*)$")


def parse_block(text: str) -> Block | None:
    """The final block: the last rule line (a run of >= 20 U+2501) followed by the label line and, for NEXT FOR YOU, the
    numbered items to the end of the message. None when the message does not end with one."""
    lines = (text or "").splitlines()
    rules = [i for i, ln in enumerate(lines) if re.fullmatch(f"{RULE_CH}{{20,}}", ln.strip().strip("*_ "))]
    if not rules:
        return None
    rest = [ln for ln in lines[rules[-1] + 1:] if ln.strip()]
    m = _LABEL.match(rest[0].strip()) if rest else None
    if not m:
        return None
    kind = m.group(1).upper()
    cm = re.match(r"[*_\s]*\((\d+)\)", rest[0].strip()[m.end():])
    blk = Block(kind, int(cm.group(1)) if cm else None, [], [], [])
    for ln in rest[1:]:
        im = _ITEM.match(ln)
        if kind == "NEXT FOR YOU" and im:
            blk.numbers.append(int(im.group(1)))
            blk.items.append(im.group(2).strip())
        elif kind == "NEXT FOR YOU" and blk.items and ln[:1].isspace():
            blk.items[-1] += " " + ln.strip()  # a wrapped item
        else:
            blk.extra.append(ln.strip())
    return blk


_STRIP = " \t*_`>#-"


def last_line(text: str) -> str:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return lines[-1].strip(_STRIP) if lines else ""


def marker(text: str) -> str | None:
    """The retired one-line form: the last line starts with `NEXT FOR YOU:`, `ALL DONE:` or `WORKING:`."""
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


def _contradiction(kind: str, bl: list[Blocker]) -> str | None:
    if kind == "ALL DONE" and bl:
        return "Your final message ends with ALL DONE, but not everything is done: " + "; ".join(b.text for b in bl) + "."
    if kind == "WORKING" and any(b.kind in {"asking", "deferred"} for b in bl):
        return ("Your final message ends with WORKING, but the owner has something open: "
                + "; ".join(b.text for b in bl if b.kind in {"asking", "deferred"}) + ".")
    return None


def _write(want: str) -> str:
    return f" Make the LAST block of your final message exactly this (plain markdown, nothing after it):\n\n{want}"


def judge(text: str, bl: list[Blocker], own: bool = False) -> str | None:
    """None when the final message ends with a status block the facts allow; else why not, with the exact block."""
    want = expected(bl, own)
    blk = parse_block(text)
    if blk is None:
        old = marker(text)
        if old is None:
            return ("Your final message does not end with the status block. Reply with one or two sentences of context, then the"
                    f" block, as the LAST thing of your final message (plain markdown, nothing after it):\n\n{want}")
        # The retired one-line form: block once, with the block to copy (a question or a wait carries over its text).
        said = last_line(text)[len(old):].strip()
        if not bl and old == "NEXT FOR YOU:":
            want = next_block([s.strip() for s in said.split(";") if s.strip()] or [said or "see the message above"])
        elif not bl and old == "WORKING:":
            want = working_block(said or "background work")
        bad = _contradiction(old[:-1], bl)
        return (bad + " " if bad else "") + ("The one-line status (`" + old + " …`) is retired; the status is now a block." + _write(want))
    bad = _contradiction(blk.kind, bl)
    if bad:
        return bad + _write(want)
    if blk.extra:
        return ("Something follows the status block in your final message; the block must be the last thing, with nothing after it."
                + _write(blk.kind == "NEXT FOR YOU" and next_block(blk.items) or want))
    if blk.kind == "NEXT FOR YOU":
        fixed = want if bl else (next_block(blk.items) if blk.items else None)
        if not blk.items:
            return ("Your NEXT FOR YOU block has no numbered items; list at least one thing only the owner can do or decide"
                    " as `1. …`" + (_write(want) if bl else f", or, if nothing needs the owner, end with the ALL DONE block:\n\n{want}"))
        if blk.count is None or blk.count != len(blk.items) or blk.numbers != list(range(1, len(blk.items) + 1)):
            return (f"Your NEXT FOR YOU block says ({blk.count}) but has {len(blk.items)} numbered item(s)"
                    f" numbered {blk.numbers}; the count must match and the items must be numbered 1..N." + _write(fixed))
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
            "write the NEXT FOR YOU block naming the deferred push; if it went through and nothing else is open, the ALL DONE block.")
    return judge(final_message(data), bl, own)


_GG = re.compile(r"^gg$", re.I)


def is_gg(prompt: str) -> bool:
    return bool(_GG.match((prompt or "").strip()))
