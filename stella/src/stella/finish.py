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
from stella.config import settings, store_dir


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


def remember_commits(sid: str, command: str, cwd: str) -> None:
    """PostToolUse: a `git commit` ran, so its repo is one this session worked in."""
    dirs = gate.commit_dirs(command, cwd)
    if not (sid and dirs):
        return
    sess = sessions.load(sid)
    seen = sess.setdefault("committed", [])
    for d in dirs:
        root = gate.guarded_root(d) or gate._remote_root(d)
        if root and str(root) not in seen:
            seen.append(str(root))
    sessions.save(sid, sess)


def remember_asked(sid: str, keys: tuple[str, ...]) -> None:
    """PreToolUse: the owner was shown the prompt for these heads. If no approval follows, he said no."""
    if not (sid and keys):
        return
    sess = sessions.load(sid)
    asked = sess.setdefault("asked", [])
    asked.extend(k for k in keys if k not in asked)
    sessions.save(sid, sess)


def _worked(sess: dict, cwd: str, own: bool) -> dict[Path, Path]:
    out: dict[Path, Path] = {}
    places = [Path(p) for p in sess.get("committed", [])]
    if cwd and not own:
        places.append(Path(cwd))
    for p in places:
        if p.exists():
            root = gate.guarded_root(p) or gate._remote_root(p)
            if root:
                out.setdefault(root, p)
    return out


def _ahead(where: Path) -> int:
    n = gate._git_out(where, "rev-list", "--count", "HEAD", "--not", "--remotes")
    return int(n) if n.isdigit() else 0


def _push_command(root: Path, where: Path) -> str:
    branch = gate._git_out(where, "rev-parse", "--abbrev-ref", "HEAD")
    if branch in {"", "HEAD"}:
        return (f"HEAD in {root} is on no branch: put the commits on one (`git -C {root} switch -c <name>`), "
                f"then run `git -C {root} push -u origin <name>`")
    return f"run `git -C {root} push -u origin {branch}`"


def check(sid: str, cwd: str, own: bool = False, may_block: bool = True) -> Result:
    res = Result()
    owner = settings().owner
    sess = sessions.load(sid)
    reminded = sess.setdefault("reminded", [])
    lines: list[str] = []
    for root, where in _worked(sess, cwd, own).items():
        n = _ahead(where)
        head = gate._head(where)
        key = f"{root}@{head}"
        if not n or not head or gate.is_approved(root, where):
            continue
        branch = gate._git_out(where, "rev-parse", "--abbrev-ref", "HEAD")
        what = f"{root.name} {branch if branch != 'HEAD' else head[:7]} {head[:7]}"
        if is_deferred(key):
            continue
        if key in sess.get("asked", []):  # the prompt appeared and the push did not happen: the owner said no
            _record_deferred(key)
            ledger.append("push_deferred", by="hook", repo=root.name, path=str(root), sha=head, branch=branch,
                          session=sid, text=f"not pushed, deferred: {what}")
            res.deferred.append(f"not pushed, deferred: {what} ({n} commit{'s' if n != 1 else ''})")
            continue
        if key in reminded or not may_block:
            res.outstanding.append(what)
            continue
        reminded.append(key)
        lines.append(f"- {root.name}: {n} unpushed commit{'s' if n != 1 else ''} at {head[:7]}; "
                     + _push_command(root, where))
    sessions.save(sid, sess)
    if lines:
        res.block = (
            "You have unpushed commits in repos you worked in. Push now, as the last step of your work: the tool hook "
            f"makes Claude Code show {owner} the push prompt (Yes, No to defer, or view the diff), so they never have "
            "to remember a push. Do not ask in chat and do not tell them to run anything.\n" + "\n".join(lines)
            + "\nIf they answer no, it is deferred: say \"not pushed, deferred\" with the repo, branch and commit, and finish."
        )
    return res


def for_done(cwd: str) -> Result | None:
    """`stella done`: the same check for the calling session, if this is a Claude session."""
    sid = os.environ.get("STELLA_SESSION_ID", "")
    return check(sid, cwd) if sid else None
