"""The push prompt for every repo that has a remote, and the leak guard for guarded repos.

Guarded repos: the repo the core lives in, plus any listed in settings.

* The push prompt. `check_bash` (run by the PreToolUse hook) spots a Claude
  session's command that pushes from any git repo with a remote (guarded or
  not) and returns an "ask" verdict, so Claude Code shows the owner its own
  yes/no prompt before the command runs (the reason is plain text; Claude Code shows it all in
  one colour and prints escape codes raw). Sessions ask the owner first through a dropdown (`plan`,
  `answered`): a Push the owner picked there is remembered, so the `stella push` that follows is not asked. A push the owner types at a terminal
  is plain git. A session launched with `--auto-push` (STELLA_AUTO_PUSH=1) was
  told up front to push for the owner, so it is not asked.
* The leak guard's git hooks. `install` puts `pre-commit` and `commit-msg`
  hooks in each guarded repo; `git_hook` runs them against the denylist.

`install` also removes what the old push gate left behind: its `pre-push` hook
and the unusable push URL it set on every remote.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from stella import leak
from stella.config import BIN, settings, store_dir

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


def _remote_root(path: str | Path) -> Path | None:
    """The top of the git checkout `path` is in, if it has a remote to push to."""
    p = Path(os.path.expanduser(str(path)))
    d = p if p.is_dir() else p.parent
    while d != d.parent and not d.exists():
        d = d.parent
    try:
        top = subprocess.run(["git", "-C", str(d), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        if not top:
            return None
        remotes = subprocess.run(["git", "-C", top, "remote"], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return Path(top).resolve() if remotes else None


def alias(root: Path) -> str:
    return root.name


def resolve_alias(name: str) -> Path:
    for root in guarded_repos():
        if name in {alias(root), str(root)} or Path(os.path.expanduser(name)).resolve() == root:
            return root
    raise SystemExit(f"{name!r} is not a guarded repo ({', '.join(alias(r) for r in guarded_repos())})")


# ---------------------------------------------------------------- the push prompt

# What counts as a push is decided from the parsed command, never from its text: a commit message, a
# grep pattern, a heredoc or a quoted argument that says "git push" is not a push.
_HEREDOC = re.compile(r"(<<-?\s*(['\"]?)(\w+)\2[^\n]*\n).*?\n[ \t]*\3[ \t]*(?=\n|$)", re.S)
_OPERATOR = re.compile(r"[;()<>|&\n`]+")
_WRAPPERS = {"env", "command", "sudo", "time", "exec", "nohup", "nice", "builtin"}
_SHELLS = {"bash", "sh", "zsh", "dash"}
_GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix", "--config-env"}
_GH_WRITES = {("pr", "create"), ("pr", "merge"), ("repo", "sync"), ("release", "create")}
_API_WRITE = re.compile(r"^(-X|--method)(=|$)|^-X(POST|PUT|PATCH|DELETE)$", re.I)
_API_METHOD = re.compile(r"POST|PUT|PATCH|DELETE", re.I)


@dataclass
class Verdict:
    decision: str | None = None  # None (no opinion), "ask" or "deny": a PreToolUse permissionDecision
    reason: str = ""
    asked: tuple[str, ...] = ()  # "<repo>@<head>" of every push the owner is being asked about


def _segments(cmd: str) -> list[list[str]]:
    """The command's simple commands, as word lists, split on operators outside quotes."""
    cmd = _HEREDOC.sub(r"\1", cmd)
    lex = shlex.shlex(cmd, posix=True, punctuation_chars=";()<>|&\n`")
    lex.whitespace, lex.whitespace_split, lex.commenters = " \t\r", True, ""
    try:
        tokens = list(lex)
    except ValueError:  # unbalanced quote: fall back to words, still never matching inside text
        tokens = cmd.split()
    segs: list[list[str]] = [[]]
    for tok in tokens:
        if _OPERATOR.fullmatch(tok):
            segs.append([])
        else:
            segs[-1].append(tok)
    return [seg for seg in segs if seg]


def _command(seg: list[str]) -> tuple[str, list[str]] | None:
    """The program and arguments of a simple command, past env assignments and wrappers like `env` or `sudo`."""
    i = 0
    while i < len(seg) and (re.fullmatch(r"\w+=.*", seg[i]) or seg[i] in _WRAPPERS):
        i += 1
        while i < len(seg) and seg[i - 1] in _WRAPPERS and seg[i].startswith("-"):
            i += 1
    return (os.path.basename(seg[i]), seg[i + 1:]) if i < len(seg) else None


def _git_sub(seg: list[str]) -> str | None:
    """The git subcommand of a simple command (`push`, `commit`, …), past git's own options."""
    cmd = _command(seg)
    if not cmd or cmd[0] != "git":
        return None
    args, j = cmd[1], 0
    while j < len(args) and args[j].startswith("-"):
        j += 2 if args[j] in _GIT_VALUE_OPTS else 1
    return args[j] if j < len(args) else None


def _kind(seg: list[str]) -> str | None:
    """"git" or "gh" if this simple command pushes or writes to the remote, else None."""
    cmd = _command(seg)
    if not cmd:
        return None
    word, args = cmd
    if word == "git":
        return "git" if _git_sub(seg) == "push" else None
    if word == "stella":  # `stella push`: the one short command sessions use to push (see `cmd_push`)
        return "stella" if args[:1] == ["push"] else None
    if word == "gh":
        words, j = [], 0
        while j < len(args) and len(words) < 2:
            if args[j] in {"-R", "--repo"}:
                j += 1
            elif not args[j].startswith("-"):
                words.append(args[j])
            j += 1
        if tuple(words) in _GH_WRITES:
            return "gh"
        if words[:1] == ["api"]:
            for k, tok in enumerate(args):
                if _API_WRITE.match(tok):
                    nxt = args[k + 1] if k + 1 < len(args) else ""
                    val = tok.split("=", 1)[1] if "=" in tok else nxt if tok.startswith("--") or len(tok) == 2 else tok[2:]
                    if _API_METHOD.fullmatch(val.strip()):
                        return "gh"
        return None
    if word in _SHELLS:
        for k, tok in enumerate(args):
            if tok.startswith("-") and not tok.startswith("--") and "c" in tok and k + 1 < len(args):
                return "inner"  # resolved by `_walk`
    return None


def _walk(command: str, here: Path, out: list[tuple[list[str], str, Path]]) -> None:
    """Collect (words, kind, cwd) for every simple command that pushes, following `cd` and `sh -c '…'`."""
    for seg in _segments(command):
        if seg[0] == "cd" and len(seg) > 1:
            target = Path(os.path.expandvars(os.path.expanduser(seg[1])))
            here = target if target.is_absolute() else here / target
            continue
        kind = _kind(seg)
        if kind == "inner":
            i = next(k for k, t in enumerate(seg) if os.path.basename(t) in _SHELLS)
            args = seg[i + 1:]
            k = next(k for k, t in enumerate(args) if t.startswith("-") and not t.startswith("--") and "c" in t)
            _walk(args[k + 1], here, out)
        elif kind:
            out.append((seg, kind, here))


def commit_dirs(command: str, cwd: str) -> list[Path]:
    """The directories a `git commit` in this command runs from, following `cd` and `git -C`."""
    here = Path(os.path.expanduser(cwd or os.getcwd()))
    out: list[Path] = []
    for seg in _segments(command):
        if seg[0] == "cd" and len(seg) > 1:
            target = Path(os.path.expandvars(os.path.expanduser(seg[1])))
            here = target if target.is_absolute() else here / target
        elif _git_sub(seg) == "commit":
            where = here
            for i, tok in enumerate(seg[:-1]):
                if tok == "-C":
                    where = here / os.path.expanduser(seg[i + 1])
                    break
            out.append(where)
    return out


def _touched(pushes: list[tuple[list[str], str, Path]], command: str) -> dict[Path, Path]:
    """Repos with a remote that the pushing commands touch, each mapped to the directory it is touched from."""
    touched: dict[Path, Path] = {}

    def add(path: Path | str) -> None:
        r = guarded_root(path) or _remote_root(path)
        if r:
            touched.setdefault(r, Path(os.path.expanduser(str(path))))

    for seg, _, here in pushes:
        if "-C" not in seg:  # `-C <dir>` replaces the directory the command runs from: the session's own repo is not pushed
            add(here)
        for i, tok in enumerate(seg):
            if tok in {"-C", "--git-dir", "--work-tree", "-R", "--repo"} and i + 1 < len(seg):
                add(here / os.path.expanduser(seg[i + 1]))
            elif tok.startswith(("/", "~", "./", "../")):
                add(here / os.path.expanduser(tok) if not tok.startswith(("/", "~")) else tok)
        text = " ".join(seg)
        for root in guarded_repos():
            spellings = {str(root)}
            if root.is_relative_to(Path.home()):
                spellings |= {f"~/{root.relative_to(Path.home())}", f"$HOME/{root.relative_to(Path.home())}"}
            if any(sp in text for sp in spellings):
                touched.setdefault(root, root)
    return touched


def _remote_range(where: Path) -> tuple[str | None, bool]:
    """The revision range of what a push from `where` would send, and whether the branch is already on the
    remote. A branch that is not falls back to the default branch; with neither, the range is None."""
    d = where if where.is_dir() else where.parent
    upstream = _git_out(d, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    branch = _git_out(d, "rev-parse", "--abbrev-ref", "HEAD")
    for i, ref in enumerate((upstream, f"origin/{branch}", "origin/main", "origin/master")):
        if ref and _git_out(d, "rev-parse", "--verify", "--quiet", f"refs/remotes/{ref}"):
            return f"{ref}...HEAD", i < 2
    return None, False


def _facts(where: Path) -> tuple[str, str, list[str], int, bool]:
    """(branch, "N commits", newest subjects, commits not shown, branch already on the remote) of a push from `where`."""
    d = where if where.is_dir() else where.parent
    branch = _git_out(d, "rev-parse", "--abbrev-ref", "HEAD") or "?"
    rng, on_remote = _remote_range(d)
    if rng is None:
        return branch, "", [], 0, False
    ahead = rng.replace("...", "..")
    count = _git_out(d, "rev-list", "--count", ahead) or "?"
    subjects = _git_out(d, "log", "--format=%s", "--max-count=3", ahead).splitlines()
    more = int(count) - len(subjects) if count.isdigit() else 0
    return branch, f"{count} commit{'' if count == '1' else 's'}", [s[:72] for s in subjects], max(more, 0), on_remote


def _summary(root: Path, where: Path, force: bool) -> str:
    """One visual group per repo: where it goes, how much, the newest subjects."""
    branch, what, subjects, more, on_remote = _facts(where)
    lines = [f"▲ PUSH  {alias(root)} → {branch}"]
    notes = [n for n in (what, "" if on_remote else "new branch", "FORCE" if force else "") if n]
    if notes:
        lines.append("  " + " · ".join(notes))
    if subjects:
        lines.append("")
        lines += [f"  · {s}" for s in subjects]
        if more:
            lines.append(f"    … and {more} more")
    return "\n".join(lines)


_FILTERS = {"tail", "head", "wc", "grep", "sort", "uniq", "cat", "tee", "sed", "awk", "cut", "tr", "true", "echo", "sleep"}


def _others(command: str) -> str:
    """The rest of a compound command that pushes, in a few words ("just style, uv run pytest"); empty when it is only the push."""
    names = []
    for seg in _segments(command):
        cmd = _command(seg)
        if not cmd or seg[0] == "cd" or _kind(seg):
            continue
        word, args = cmd
        if word in _FILTERS or word.isdigit():  # `| tail -1`, `2>&1`: not something the command also does
            continue
        if word == "uv" and args[:1] == ["run"]:  # name the program, not the launcher
            rest = [a for a in args[1:] if not a.startswith("-")]
            word, args = (rest[0], rest[1:]) if rest else (word, args)
        names.append(" ".join([word, *[a for a in args[:1] if not a.startswith(("-", "/", "~", "."))]]).strip())
    names = list(dict.fromkeys(names))
    return ", ".join(names[:3]) + (f" (+{len(names) - 3} more)" if len(names) > 3 else "")


# The owner's question as Claude Code's own dropdown (AskUserQuestion): "Push" (its preview pane shows what is sent) or "Defer".
# `plan` builds the question and its preview and remembers it; when the owner picks Push, `answered` (PostToolUse) records the
# approval of that repo head, so the `stella push` that follows is not asked a second time.
PUSH_LABEL, DEFER_LABEL, PREVIEW_LINES = "Push", "Defer", 60


def _plan_dir() -> Path:
    return store_dir() / "pushplan"


def plan(where: Path) -> dict:
    """The AskUserQuestion for a push from `where`: its question, preview text and what was remembered. Empty when nothing is sent."""
    d = where if where.is_dir() else where.parent
    root = guarded_root(d) or _remote_root(d)
    if not root:
        return {}
    head = _head(d)
    if is_approved(root, d):
        return {"approved": True}
    if _nothing_to_send(d):
        return {"nothing": True}
    branch, what, subjects, more, on_remote = _facts(d)
    detail = ", ".join(n for n in (what, "" if on_remote else "new branch", head[:7]) if n)
    question = f"Push {alias(root)} → {branch} ({detail})?"
    rng, _ = _remote_range(d)
    git = ["git", "-C", str(d), "-c", "color.ui=never"]
    cmds = ([git + ["diff", "--stat", rng], git + ["diff", rng]] if rng else [git + ["log", "--stat", "--max-count=5"]])
    lines = [f"· {x}" for x in subjects] + ([f"  … and {more} more"] if more else []) + [""]
    for c in cmds:
        lines += subprocess.run(c, capture_output=True, text=True, timeout=10).stdout.splitlines() + [""]
    if len(lines) > PREVIEW_LINES:
        lines = lines[:PREVIEW_LINES] + [f"… {len(lines) - PREVIEW_LINES} more lines: `stella diff` prints them all"]
    key = hashlib.sha1(question.encode()).hexdigest()[:12]
    _plan_dir().mkdir(parents=True, exist_ok=True)
    (_plan_dir() / f"{key}.json").write_text(json.dumps({"root": str(root), "head": head, "question": question, "ts": time.time()}))
    return {"question": question, "preview": "\n".join(lines).rstrip()}


def _chosen(response, label: str) -> bool:
    """Whether the AskUserQuestion response says the owner picked `label` (its shape is Claude Code's: look for it anywhere,
    ignoring the question list and the options themselves)."""
    def strings(x, skip=False):
        if isinstance(x, str):
            yield x
        elif isinstance(x, dict):
            for k, v in x.items():
                if k not in {"questions", "options"}:
                    yield from strings(v)
        elif isinstance(x, list):
            for v in x:
                yield from strings(v)

    return any(t == label or re.search(r'="%s"' % re.escape(label), t) or t.startswith(f"{label} selected") for t in strings(response))


def answered(tool_input: dict, response) -> str:
    """PostToolUse of AskUserQuestion: if it was one of ours and the owner picked Push, remember the approval. Returns
    "push", "defer" or "" (not ours, or he answered something else)."""
    for q in (tool_input or {}).get("questions") or []:
        text = q.get("question", "") if isinstance(q, dict) else ""
        f = _plan_dir() / f"{hashlib.sha1(text.encode()).hexdigest()[:12]}.json"
        try:
            p = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if _chosen(response, PUSH_LABEL):
            keep = [e for e in _approved() if e != f"{p['root']}@{p['head']}"][-499:] + [f"{p['root']}@{p['head']}"]
            _approvals_file().parent.mkdir(parents=True, exist_ok=True)
            _approvals_file().write_text(json.dumps(keep))
            return "push"
        if _chosen(response, DEFER_LABEL):
            return "defer:" + f"{p['root']}@{p['head']}"
    return ""


def _diff_command(where: Path, color: bool = True) -> str:
    """Shell command that prints the diffstat, then the full diff, of a push from `where`."""
    d = where if where.is_dir() else where.parent
    rng, _ = _remote_range(d)
    git = f"git -C {shlex.quote(str(d))} -c color.ui={'always' if color else 'never'}"
    if rng:
        return f"{git} diff --stat {shlex.quote(rng)}; echo; {git} diff {shlex.quote(rng)}"
    return f"{git} log --stat --max-count=5; echo; {git} log -p --max-count=5"


def _git_out(where: Path, *args: str) -> str:
    d = where if where.is_dir() else where.parent
    try:
        r = subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def _head(where: Path) -> str:
    return _git_out(where, "rev-parse", "HEAD")


_PLAIN_FLAGS = {"-u", "--set-upstream", "--no-verify", "-q", "--quiet", "-v", "--verbose", "--no-progress"}


def _plain(seg: list[str]) -> bool:
    """A push of the current work: no deletion, tags, force or refspec that changes the remote beyond the commits."""
    if (_command(seg) or ("", []))[0] == "stella":
        return True  # `stella push` sends the current branch and nothing else
    args = seg[seg.index("push") + 1:] if "push" in seg else []
    return all(a in _PLAIN_FLAGS or (not a.startswith("-") and ":" not in a and not a.startswith("+")) for a in args)


def _nothing_to_send(where: Path) -> bool:
    """True when the branch has an upstream and no commits ahead of it."""
    upstream = _git_out(where, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if not upstream:
        upstream = f"origin/{_git_out(where, 'rev-parse', '--abbrev-ref', 'HEAD')}"
    return _git_out(where, "rev-list", "--count", f"{upstream}..HEAD") == "0"


# An approval is remembered per repo and head commit, in one file every session and subagent of the owner
# reads, so the same head is never asked about twice. It is recorded after a push command ran, which only
# happens when the owner said yes (or the session was told up front to push).


def _approvals_file() -> Path:
    return store_dir() / "push_approved.json"


def _approved() -> list[str]:
    try:
        return json.loads(_approvals_file().read_text())
    except (OSError, ValueError):
        return []


def is_approved(root: Path, where: Path) -> bool:
    head = _head(where)
    return bool(head) and f"{root}@{head}" in _approved()


def record_approval(command: str, cwd: str) -> list[str]:
    """After a push command ran: remember each touched repo's head as approved."""
    pushes: list[tuple[list[str], str, Path]] = []
    _walk(command, Path(os.path.expanduser(cwd or os.getcwd())), pushes)
    done = []
    for root, where in _touched(pushes, command).items():
        head = _head(where)
        if head:
            done.append(f"{root}@{head}")
    if done:
        keep = [e for e in _approved() if e not in done][-499:] + done
        f = _approvals_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(keep))
    return done


def _unresolved(pushes: list[tuple[list[str], str, Path]]) -> str | None:
    """A directory a push runs from that only the shell could expand (`cd $D/w`, `git -C "$(pwd)"`):
    the hook cannot tell which repo it is, and guessing would describe the wrong one."""
    for seg, _, here in pushes:
        paths = [str(here)] + [seg[i + 1] for i, t in enumerate(seg[:-1]) if t in {"-C", "--git-dir", "--work-tree"}]
        for p in paths:
            if "$" in p or "`" in p:
                return p
    return None


def check_bash(command: str, cwd: str) -> Verdict:
    """Ask the owner before a command that pushes from a repo with a remote runs. Once per repo and head."""
    pushes: list[tuple[list[str], str, Path]] = []
    _walk(command, Path(os.path.expanduser(cwd or os.getcwd())), pushes)
    if not pushes:
        return Verdict()
    kinds = {k for _, k, _ in pushes}
    pushy = kinds <= {"git", "stella"}
    if os.environ.get("STELLA_AUTO_PUSH") == "1" and pushy:
        return Verdict()  # told up front to push; a PR, merge or API write still asks
    unknown = _unresolved(pushes)
    if unknown and pushy:
        return Verdict("ask", f"Push from {unknown}: this hook cannot resolve that path, so it cannot say which repo or how many commits.")
    plain = pushy and all(_plain(seg) for seg, _, _ in pushes)
    touched = {r: w for r, w in _touched(pushes, command).items()
               if not is_approved(r, w) and not (plain and _nothing_to_send(w))}
    if not touched:
        return Verdict()
    groups = "\n\n".join(_summary(r, w, not plain) for r, w in sorted(touched.items()))
    asked = tuple(f"{r}@{_head(w)}" for r, w in sorted(touched.items()))
    also = _others(command)
    tail = (f"⚠ This command also runs {also}. Push only?\n\n" if also else "") + "Yes: push · No: defer"
    return Verdict("ask", f"{groups}\n\n{tail}", asked)


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
