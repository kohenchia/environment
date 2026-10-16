"""What `stella pass-env` prints: one line per live tmux window, before and after the switch.

The list is the owner's tmux window list (the Stella server's windows, each joined with the `claude`
process in its pane), never the ledger: a team with no window or process is only counted. Each line
shows the token the process runs on, read from its own environment (names only, never a value).

    SWITCHING TO THE PROJECT TOKEN (was: personal)
      pr-2200-pavan      personal -> PROJECT   restarted
      stella             personal -> PROJECT   restarting last, resuming this conversation
      build              shell                 skipped (not a Claude session)
"""

from __future__ import annotations

import sys
import time

from stella import passenv, windows

WORDS = {"on": "PROJECT", "off": "PERSONAL"}
_COLOUR = {"project": "32", "personal": "33"}  # green, yellow
SETTLE = 1.0  # seconds the restarted processes need before their environment can be read


def _tty() -> bool:
    return sys.stdout.isatty()


def tag(token: str | None, big: bool = False) -> str:
    """A token state as shown: lower case, or capitals (bold and coloured on a terminal) for the after-state."""
    t = token or "?"
    word = t.upper() if big else t
    if not _tty() or t not in _COLOUR:
        return word
    return ("\033[1m" if big else "") + "\033[" + _COLOUR[t] + "m" + word + "\033[0m"


def _cell(token: str | None, big: bool, width: int) -> str:
    """Padded by the plain text's width, so colour codes do not break the columns."""
    plain = (token or "?").upper() if big else (token or "?")
    return tag(token, big) + " " * max(0, width - len(plain))


def switch_line(mode: str | None) -> str:
    return "Switch: " + ("PROJECT token (tok on)" if mode == "on" else "PERSONAL token (tok off)" + ("" if mode else ", never set"))


def header(new: str, prev: str | None) -> str:
    """`prev` is the switch before this command changed it; None when this command did not change it."""
    what = "THE PROJECT TOKEN" if new == "on" else "YOUR PERSONAL TOKEN"
    if prev is None:
        return f"RESTARTING ON {what} (the switch is unchanged)"
    return f"SWITCHING TO {what} (was: {'project' if prev == 'on' else 'personal'})"


def token_of(t: windows.Target) -> str | None:
    return passenv.in_use(t.pid)


def _name(t: windows.Target) -> str:
    return t.window_name or t.pane_id


def line(name: str, before: str | None, after: str | None, note: str, w: int) -> str:
    return f"  {name:<{w}}  {_cell(before, False, 8)} -> {_cell(after, True, 8)} {note}".rstrip()


def width(inv: windows.Inventory) -> int:
    return max([14] + [len(_name(t)) for t in inv.targets] + [len(s) for s in inv.shells])


def result_line(r: windows.Result, before: dict[str, str | None], goal: str, w: int) -> str:
    """One line for a restart result: `name  personal -> PROJECT  restarted`."""
    want = "project" if goal == "on" else "personal"
    b = before.get(r.target.pane_id) if r.target else None
    if r.outcome == "restarted":
        return line(r.name, b, want, "restarted", w)
    if r.outcome == "later":
        who = "stella: restarting last, resuming this conversation" if r.text == "stella" else \
            "restarting after this command (the pane it runs in), conversation resumed"
        return line(r.name, b, want, who, w)
    if r.outcome == "missing":
        return f"  {r.name:<{w}}  {r.text}"
    if r.outcome == "skipped":
        return f"  {r.name:<{w}}  {_cell(b, False, 8)}    {'':<8} skipped, {r.text}"
    return f"  {r.name:<{w}}  {_cell(b, False, 8)}    {'':<8} {r.outcome}: {r.text}"


def extras(inv: windows.Inventory, w: int = 14) -> list[str]:
    out = [f"  {s:<{w}}  shell (not a Claude session, skipped)" for s in inv.shells]
    if inv.dead:
        out.append(f"  {inv.dead} finished session{'s' if inv.dead != 1 else ''} {'have' if inv.dead != 1 else 'has'} no window (skipped)")
    if inv.outside:
        out.append("  outside tmux (not restarted): " + "; ".join(f"pid {p}, {c or '?'}" for p, c in inv.outside))
    return out


def table(inv: windows.Inventory, goal: str | None, title: str, pending: set[str] = frozenset(),
          reasons: dict[str, str] | None = None, with_extras: bool = True) -> list[str]:
    """The state of every live window, re-read from the processes, then one check line."""
    w = width(inv)
    rows, bad = [], []
    for t in inv.targets:
        tok = token_of(t)
        if t.pane_id in pending:
            rows.append(f"  {_name(t):<{w}}  {_cell(tok, False, 8)} restarting in a moment")
            continue
        rows.append(f"  {_name(t):<{w}}  {_cell(tok, True, 8)}".rstrip())
        if goal and tok != ("project" if goal == "on" else "personal"):
            bad.append((_name(t), tok))
    out = [title, *rows, *(extras(inv, w) if with_extras else [])]
    out.append(check(len(inv.targets) - len(pending), bad, goal, len(pending), reasons or {}))
    return out


def check(n: int, bad: list[tuple[str, str | None]], goal: str | None, pending: int = 0, reasons: dict[str, str] | None = None) -> str:
    word = "the project token" if goal == "on" else "the personal token"
    if goal is None:
        return ""
    tail = f"; {pending} still to restart (stella, last)" if pending else ""
    if not bad:
        return f"all {n} session{'' if n == 1 else 's'} now on {word}{tail}"
    why = reasons or {}
    ex = ", ".join(f"{name} ({tok or 'unreadable'}: {why.get(name, 'still on it after the restart')})" for name, tok in bad)
    return f"{n - len(bad)} of {n} session{'' if n == 1 else 's'} now on {word}{tail}; not: {ex}"


def settle() -> None:
    time.sleep(SETTLE)
