"""Guarded repos: a push from one asks the owner first, and commits to one pass the leak guard.

Guarded repos: the repo the core lives in, plus any listed in settings.

* The push prompt. `check_bash` (run by the PreToolUse hook) spots a Claude
  session's command that pushes from a guarded repo and returns an "ask"
  verdict, so Claude Code shows the owner its own yes/no prompt before the
  command runs. A push the owner types at a terminal is plain git.
* The leak guard's git hooks. `install` puts `pre-commit` and `commit-msg`
  hooks in each guarded repo; `git_hook` runs them against the denylist.

`install` also removes what the old push gate left behind: its `pre-push` hook
and the unusable push URL it set on every remote.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from stella import leak
from stella.config import BIN, settings

# The push URL the old push gate set on every remote. Kept only to recognise and remove it.
BLOCKED_URL = "file:///STELLA-PUSH-GATE/push-with-stella-push"
COMMIT_HOOKS = ("pre-commit", "commit-msg")
_MARK = "Installed by stella."


# ---------------------------------------------------------------- repos


def _common_dir(path: Path) -> Path | None:
    d = path if path.is_dir() else path.parent
    while d != d.parent and not d.exists():
        d = d.parent
    try:
        out = subprocess.run(
            ["git", "-C", str(d), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return Path(out).resolve() if out else None


def guarded_repos() -> list[Path]:
    return [p for p in settings().guarded_repos if p and p.exists()]


def guarded_root(path: str | Path) -> Path | None:
    p = Path(os.path.expanduser(str(path)))
    try:
        p = p.resolve()
    except OSError:
        return None
    for root in guarded_repos():
        if p == root or root in p.parents:
            return root
    common = _common_dir(p)
    if common:
        for root in guarded_repos():
            if common == (root / ".git").resolve():
                return root
    return None


def alias(root: Path) -> str:
    return root.name


def resolve_alias(name: str) -> Path:
    for root in guarded_repos():
        if name in {alias(root), str(root)} or Path(os.path.expanduser(name)).resolve() == root:
            return root
    raise SystemExit(f"{name!r} is not a guarded repo ({', '.join(alias(r) for r in guarded_repos())})")


# ---------------------------------------------------------------- the push prompt

_SPLIT = re.compile(r"\s*(?:&&|\|\||;|\||\n|\$\(|`|\(|\))\s*")
# `git … push`, but not `.git/hooks/pre-push` or `git remote set-url --push`.
_PUSHY = re.compile(r"(?<![\w.-])git\s[^;&|\n]*?(?<![\w./=-])push(?![\w-])"
                    r"|\bgh\s+(pr\s+(create|merge)|repo\s+sync|release\s+create)\b")
_GH_API_WRITE = re.compile(r"\bgh\s+api\b.*(-X|--method)\s*(POST|PUT|PATCH|DELETE)", re.I)


@dataclass
class Verdict:
    decision: str | None = None  # None (no opinion), "ask" or "deny": a PreToolUse permissionDecision
    reason: str = ""


def _segments(cmd: str) -> list[list[str]]:
    segs = []
    for part in _SPLIT.split(cmd):
        part = part.strip()
        if not part:
            continue
        try:
            segs.append(shlex.split(part, posix=True))
        except ValueError:
            segs.append(part.split())
    return segs


def _touched(command: str, cwd: str) -> dict[Path, Path]:
    """Guarded repos the command touches, each mapped to the directory it is touched from."""
    here = Path(os.path.expanduser(cwd or os.getcwd()))
    touched: dict[Path, Path] = {}

    def add(path: Path | str) -> None:
        r = guarded_root(path)
        if r:
            touched.setdefault(r, Path(os.path.expanduser(str(path))))

    add(here)
    for seg in _segments(command):
        if not seg:
            continue
        if seg[0] == "cd" and len(seg) > 1:
            target = Path(os.path.expanduser(seg[1]))
            here = target if target.is_absolute() else here / target
            add(here)
        for i, tok in enumerate(seg):
            if tok in {"-C", "--git-dir", "--work-tree", "-R", "--repo"} and i + 1 < len(seg):
                add(here / os.path.expanduser(seg[i + 1]))
            elif tok.startswith(("/", "~", "./", "../")):
                add(here / os.path.expanduser(tok) if not tok.startswith(("/", "~")) else tok)
    for root in guarded_repos():
        spellings = {str(root)}
        if root.is_relative_to(Path.home()):
            spellings |= {f"~/{root.relative_to(Path.home())}", f"$HOME/{root.relative_to(Path.home())}"}
        if any(sp in command for sp in spellings):
            touched.setdefault(root, root)
    return touched


def _summary(where: Path) -> str:
    """Branch and how far it is ahead of its upstream, as seen from `where`."""
    d = where if where.is_dir() else where.parent

    def git(*args: str) -> str:
        try:
            r = subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return r.stdout.strip() if r.returncode == 0 else ""

    branch = git("rev-parse", "--abbrev-ref", "HEAD") or "?"
    upstream = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if not upstream and git("rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"):
        upstream = f"origin/{branch}"
    if not upstream:
        return f"branch {branch}, not on the remote yet"
    ahead = git("rev-list", "--count", f"{upstream}..HEAD") or "?"
    return f"branch {branch}, {ahead} commit(s) ahead of {upstream}"


def check_bash(command: str, cwd: str) -> Verdict:
    """Ask the owner before a command that pushes from a guarded repo runs."""
    if not guarded_repos() or not (_PUSHY.search(command) or _GH_API_WRITE.search(command)):
        return Verdict()
    touched = _touched(command, cwd)
    if not touched:
        return Verdict()
    names = ", ".join(alias(r) for r in sorted(touched))
    details = "; ".join((f"{alias(r)}: " if len(touched) > 1 else "") + _summary(w) for r, w in sorted(touched.items()))
    shown = " ".join(command.split())
    shown = shown if len(shown) <= 200 else shown[:199] + "…"
    return Verdict("ask", f"Push {names}? {details}. Command: {shown}")


# ---------------------------------------------------------------- git hooks


def _git(repo: Path, *args: str, check: bool = True) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check).stdout.strip()


HOOK_SCRIPT = """#!/bin/sh
# Installed by stella. Do not edit: see `stella gate status`.
exec "{bin}" git-hook {name} "$@"
"""


def _hooks_dir(repo: Path) -> Path:
    return Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "hooks"


def _ours(p: Path) -> bool:
    try:
        return p.is_file() and _MARK in p.read_text()
    except OSError:
        return False


def _blocked_pushurls(repo: Path) -> list[str]:
    """Config keys (remote.<name>.pushurl) still set to the old push gate's unusable URL."""
    out = _git(repo, "config", "--local", "--get-regexp", r"^remote\..*\.pushurl$", check=False)
    return [k for k, _, v in (line.partition(" ") for line in out.splitlines()) if v == BLOCKED_URL]


def install(repo: Path) -> list[str]:
    done = []
    hooks = _hooks_dir(repo)
    hooks.mkdir(exist_ok=True)
    for name in COMMIT_HOOKS:
        p = hooks / name
        body = HOOK_SCRIPT.format(bin=BIN, name=name)
        if p.exists() and p.read_text() != body:
            p.rename(p.with_suffix(".pre-stella"))
            done.append(f"kept the old {name} hook as {name}.pre-stella")
        p.write_text(body)
        p.chmod(0o755)
        done.append(f"installed {name} hook")
    pre_push = hooks / "pre-push"
    if _ours(pre_push):
        backup = hooks / "pre-push.pre-stella"
        if backup.exists():
            backup.replace(pre_push)
            done.append("removed the old push gate's pre-push hook; restored pre-push.pre-stella")
        else:
            pre_push.unlink()
            done.append("removed the old push gate's pre-push hook")
    for key in _blocked_pushurls(repo):
        _git(repo, "config", "--local", "--fixed-value", "--unset-all", key, BLOCKED_URL)
        done.append(f"unset {key} (the old push gate's blocked URL)")
    return done


def status(repo: Path) -> list[str]:
    out = []
    hooks = _hooks_dir(repo)
    hp = _git(repo, "config", "--get", "core.hooksPath", check=False)
    if hp:
        out.append(f"FAIL core.hooksPath is set ({hp}); the leak guard's commit hooks would be skipped")
    for name in COMMIT_HOOKS:
        p = hooks / name
        ok = p.exists() and str(BIN) in p.read_text()
        out.append(f"{'ok  ' if ok else 'FAIL'} {name} hook")
    left = _ours(hooks / "pre-push")
    out.append("FAIL the old push gate's pre-push hook is still installed: run `stella gate install`" if left
               else "ok   no push gate pre-push hook")
    for key in _blocked_pushurls(repo):
        out.append(f"FAIL {key} is still the old push gate's blocked URL: run `stella gate install`")
    return out


def git_hook(name: str, argv: list[str], stdin: str) -> int:
    if name == "pre-push":  # a leftover hook from the old push gate: pushes are not gated any more
        return 0
    repo = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel"))
    g = leak.guard()
    if not (g.configured and leak.protected_root(repo, g)):
        return 0
    try:
        rules = leak.load_rules(g)
    except leak.DenylistMissing as e:
        print(f"STELLA LEAK GUARD: denylist missing ({e}); refusing to commit to a protected repo.", file=sys.stderr)
        return 1
    if name == "pre-commit":
        hits = leak.scan_staged(repo, rules)
    elif name == "commit-msg":
        hits = leak.scan_text(Path(argv[0]).read_text(), "commit message", rules) if argv else []
    else:
        return 0
    if hits:
        print("STELLA LEAK GUARD: refusing to commit; these look private to an extension:", file=sys.stderr)
        for h in hits[:30]:
            print(f"  {h.where}:{h.line}: {h.term!r}: {h.text}", file=sys.stderr)
        return 1
    return 0
