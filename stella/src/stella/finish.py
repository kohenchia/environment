"""Finishing with unpushed work: the session pushes, so the push prompt appears. It is the prompt, or nothing.

When a session ends its turn (the Stop hook) or a team reports done (`stella done`) while commits sit unpushed in
a repo with a remote that the session worked in, `check` refuses once and tells the session to run the push now.
The push goes through the PreToolUse prompt (`gate.check_bash`): the owner answers yes, no (defer) or asks for the
diff. Nothing here pushes, approves or asks the owner to run anything.

* Repos the session worked in: the one it runs in (not for Stella's own session, which runs from anywhere) and
  every repo a `git commit` of this session ran in (recorded by the PostToolUse hook).
* One reminder per repo head per session, so the hook cannot loop; a head the session already asked about, whose
  push was then not approved, is a deferral: recorded once, reported as "not pushed, deferred", never asked again.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from stella import gate, ledger, sessions
from stella.config import CALL, settings, store_dir


@dataclass
class Result:
    block: str = ""  # non-empty: refuse to finish and tell the session this
    deferred: list[str] = field(default_factory=list)  # "not pushed, deferred: …" lines to show the owner
    outstanding: list[str] = field(default_factory=list)  # reminded already and still unpushed, not deferred


def _deferred_file() -> Path:
    return store_dir() / "push_deferred.json"


def _deferred() -> list[str]:
    try:
        return json.loads(_deferred_file().read_text())
    except (OSError, ValueError):
        return []


def is_deferred(key: str) -> bool:
    return key in _deferred()


def _record_deferred(key: str) -> None:
    keep = [k for k in _deferred() if k != key][-499:] + [key]
    f = _deferred_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(keep))


def remember_asked(sid: str, keys: tuple[str, ...]) -> None:
    """PreToolUse: the owner was shown the prompt for these heads. If no approval follows, he said no."""
    if not (sid and keys):
        return
    sess = sessions.load(sid)
    asked = sess.setdefault("asked", [])
    asked.extend(k for k in keys if k not in asked)
    sessions.save(sid, sess)


def _team_of(st, sid: str):
    from stella import state

    return st.teams.get(os.environ.get("STELLA_TEAM") or "") or state.team_for_session(st, sid)


def check(sid: str, cwd: str, own: bool = False, may_block: bool = True) -> Result:
    """Ask a session to push only the commits THAT SESSION made (see `provenance`): never another session's or effort's,
    never one a remote branch has, never one the owner approved or deferred. A bystander in the same repo is never asked."""
    from stella import provenance, state

    res = Result()
    owner = settings().owner
    st = state.fold()
    w = provenance.who(st, sid, _team_of(st, sid))
    sess = sessions.load(sid)
    reminded = sess.setdefault("reminded", [])
    lines: list[str] = []
    for p in provenance.owned_pushes(st, w, skip_known=False):
        br = p.branch
        if br.tip in provenance._approved_shas() or br.tip in {k.rsplit("@", 1)[-1] for k in _deferred()}:
            continue
        root = (br.where or br.repo).resolve()
        key = f"{root}@{br.tip}"
        what = f"{root.name} {br.name} {br.tip[:7]}"
        n = p.n
        if key in sess.get("asked", []):  # the prompt appeared and the push did not happen: the owner said no
            _record_deferred(key)
            tip = provenance.recs().get(br.tip)
            ledger.append("push_deferred", by="hook", repo=root.name, path=str(root), sha=br.tip, branch=br.name,
                          session=sid, made_by=(tip.session if tip else None), made_by_team=(tip.team if tip else None),
                          text=f"not pushed, deferred: {what}")
            ledger.append("alert", by="hook", key=f"push-deferred:{root.name}@{br.tip}", path=str(root), sha=br.tip,
                          text=f"deferred push: {root.name} {br.name} ({n} commit{'s' if n != 1 else ''})")
            res.deferred.append(f"not pushed, deferred: {what} ({n} commit{'s' if n != 1 else ''})")
            continue
        if key in reminded or not may_block:
            res.outstanding.append(what)
            continue
        reminded.append(key)
        if br.name == "HEAD":
            lines.append(f"- {root.name}: {n} unpushed commit{'s' if n != 1 else ''} you made on no branch: put them on one "
                         f"(`git -C {root} switch -c <name>`), then run `{CALL} push --plan -C {root}` and follow it")
        elif br.where:
            lines.append(f"- {root.name}: {n} unpushed commit{'s' if n != 1 else ''} you made, at {br.tip[:7]}; run `{CALL} push --plan -C {root}` and follow it")
        else:
            lines.append(f"- {root.name}: {n} unpushed commit{'s' if n != 1 else ''} you made on {br.name}, which is checked out nowhere: "
                         f"check it out in a worktree (`wta`), then run `{CALL} push --plan -C <that directory>`")
    sessions.save(sid, sess)
    if lines:
        res.block = (
            "You have unpushed commits that you made. Push now, as the last step of your work. Each line below gives "
            f"`{CALL} push --plan -C <repo>`: it prints {owner}'s question (Claude Code's own dropdown: Push, with what is sent in "
            "its preview pane, or Defer). Ask it with AskUserQuestion exactly as it says; if they pick Push, run "
            f"`{CALL} push -C <repo>` as that one command and nothing else in it (no second prompt appears). Do not ask in chat "
            "and do not tell them to run anything.\n" + "\n".join(lines)
            + "\nIf they pick Defer (or answer anything else without Push), it is deferred: say \"not pushed, deferred\" with the repo, branch and commit, and finish."
        )
    return res


def clear_pushed(st) -> list[str]:
    """A deferred push stays on the owner's list until its commit is on a remote; then the item clears itself."""
    cleared = []
    for ev in st.push_deferred:
        key = f"push-deferred:{ev.get('repo')}@{ev.get('sha')}"
        path, sha = ev.get("path"), ev.get("sha")
        gone = bool(path and sha and not gate._git_out(Path(path), "cat-file", "-t", sha))  # amended or squashed away
        if key in st.alerts and path and sha and (gone or gate._git_out(Path(path), "branch", "-r", "--contains", sha)):
            ledger.append("clear_alert", by="hook", key=key)
            st.alerts.pop(key, None)
            cleared.append(key)
    return cleared


def for_done(cwd: str) -> Result | None:
    """`stella done`: the same check for the calling session, if this is a Claude session."""
    sid = os.environ.get("STELLA_SESSION_ID", "")
    return check(sid, cwd) if sid else None
