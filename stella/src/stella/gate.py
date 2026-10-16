"""The push gate: nothing is pushed from a guarded repo without the owner's approval.

Guarded repos: the repo the core lives in, plus any listed in settings. Three
independent layers, because each alone can be skipped:

1. `check_bash` (a PreToolUse hook) refuses agent commands that push from, or
   reconfigure, a guarded repo.
2. The repo's `pre-push` git hook refuses a push without a valid in-flight approval.
3. Each remote's push URL is set to an unusable value, so only `stella push`,
   which pushes to the real URL explicitly, can reach the remote.

Approvals are single-use, bound to one commit, and come from exactly two places:
a typed confirmation at a real terminal (`stella review-push`), or an instruction
captured by the prompt hook (a `push_intent` ledger event).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from stella import ledger, leak, state
from stella.config import BIN, settings, store_dir

BLOCKED_URL = "stella-gate:blocked-use-stella-push"


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


# ---------------------------------------------------------------- bash guard

_SPLIT = re.compile(r"\s*(?:&&|\|\||;|\||\n|\$\(|`|\(|\))\s*")
_PUSHY = re.compile(r"\bgit\b[^;&|\n]*\bpush\b|\bgh\s+(pr\s+(create|merge)|repo\s+sync|release\s+create)\b")
_GH_API_WRITE = re.compile(r"\bgh\s+api\b.*(-X|--method)\s*(POST|PUT|PATCH|DELETE)", re.I)
_CONFIG_KEYS = re.compile(r"(core\.hookspath|remote\.[^\s.]+\.(push)?url|url\..*\.(push)?insteadof|alias\.)", re.I)


@dataclass
class Verdict:
    deny: bool
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


def check_bash(command: str, cwd: str) -> Verdict:
    roots = guarded_repos()
    if not roots:
        return Verdict(False)
    stripped = command.strip()
    if re.match(rf"^({re.escape(str(BIN))}|stella)\s+(push|review-push)\b", stripped):
        return Verdict(False)

    here = Path(os.path.expanduser(cwd or os.getcwd()))
    touched: set[Path] = set()
    r = guarded_root(here)
    if r:
        touched.add(r)
    for seg in _segments(command):
        if not seg:
            continue
        if seg[0] == "cd" and len(seg) > 1:
            target = Path(os.path.expanduser(seg[1]))
            here = target if target.is_absolute() else here / target
            r = guarded_root(here)
            if r:
                touched.add(r)
        for i, tok in enumerate(seg):
            if tok in {"-C", "--git-dir", "--work-tree", "-R", "--repo"} and i + 1 < len(seg):
                r = guarded_root(here / os.path.expanduser(seg[i + 1]))
                if r:
                    touched.add(r)
            elif tok.startswith(("/", "~", "./", "../")):
                r = guarded_root(here / os.path.expanduser(tok)) if not tok.startswith(("/", "~")) else guarded_root(tok)
                if r:
                    touched.add(r)
    for root in roots:
        spellings = {str(root)}
        if root.is_relative_to(Path.home()):
            spellings |= {f"~/{root.relative_to(Path.home())}", f"$HOME/{root.relative_to(Path.home())}"}
        if any(sp in command for sp in spellings):
            touched.add(root)
    if not touched:
        return Verdict(False)
    names = ", ".join(alias(t) for t in sorted(touched))
    how = f"Pushing {names} needs the owner's approval: ask them to run `stella review-push {alias(sorted(touched)[0])}`, or to tell Stella explicitly to push it; then use `stella push {alias(sorted(touched)[0])}`."
    if _PUSHY.search(command) or _GH_API_WRITE.search(command):
        return Verdict(True, f"STELLA PUSH GATE: blocked a push from a guarded repo ({names}). {how}")
    if re.search(r"\bgit\b[^;&|\n]*\b(config)\b", command) and _CONFIG_KEYS.search(command):
        return Verdict(True, f"STELLA PUSH GATE: blocked a change to push or hook configuration of {names}.")
    if re.search(r"\bgit\b[^;&|\n]*\bremote\s+(set-url|add|rename|remove|rm)\b", command):
        return Verdict(True, f"STELLA PUSH GATE: blocked a remote change in {names}.")
    if ".git/hooks" in command or "hooksPath" in command:
        return Verdict(True, f"STELLA PUSH GATE: blocked a command touching git hooks of {names}.")
    return Verdict(False)


def check_path_write(path: str) -> Verdict:
    """Refuse agent writes to guarded repos' git internals and to approval records."""
    try:
        p = Path(os.path.expanduser(path)).resolve()
    except OSError:
        return Verdict(False)
    if (store_dir() / "approvals").resolve() in p.parents:
        return Verdict(True, "STELLA PUSH GATE: approval records are written only by `stella review-push` and the prompt hook.")
    for root in guarded_repos():
        if (root / ".git").resolve() in p.parents or p == (root / ".git").resolve():
            return Verdict(True, f"STELLA PUSH GATE: refusing to write inside {alias(root)}/.git.")
    return Verdict(False)


_SEND_KEYS_REVIEW = re.compile(r"\btmux\b.*\bsend-keys\b.*review-push|\btmux\b.*\bsend-keys\b.*stella-review", re.S)


def check_review_window(command: str) -> Verdict:
    if _SEND_KEYS_REVIEW.search(command):
        return Verdict(True, "STELLA PUSH GATE: only the owner types into a push review.")
    return Verdict(False)


# ---------------------------------------------------------------- approvals


def _approvals() -> Path:
    d = store_dir() / "approvals"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _git(repo: Path, *args: str, check: bool = True) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check).stdout.strip()


def head(repo: Path, branch: str | None = None) -> str:
    return _git(repo, "rev-parse", branch or "HEAD")


def current_branch(repo: Path) -> str:
    b = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if b == "HEAD":
        raise SystemExit("detached HEAD: name the branch with --branch")
    return b


def upstream_base(repo: Path, remote: str, branch: str) -> str | None:
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{branch}"],
                       capture_output=True, text=True)
    return r.stdout.strip() or None


def write_approval(repo: Path, sha: str, branch: str, source: str) -> Path:
    rec = {
        "repo": str(repo), "sha": sha, "branch": branch, "source": source,
        "created": ledger.now().isoformat(timespec="seconds"),
        "expires": (ledger.now() + dt.timedelta(minutes=settings().push_approval_minutes)).isoformat(timespec="seconds"),
        "used": False,
    }
    p = _approvals() / f"{alias(repo)}-{sha[:12]}.json"
    p.write_text(json.dumps(rec))
    return p


def find_approval(repo: Path, sha: str) -> tuple[str, Path | dict] | None:
    p = _approvals() / f"{alias(repo)}-{sha[:12]}.json"
    if p.exists():
        rec = json.loads(p.read_text())
        if rec["sha"] == sha and not rec["used"] and dt.datetime.fromisoformat(rec["expires"]) > ledger.now():
            return ("review", p)
    window = dt.timedelta(minutes=settings().push_intent_minutes)
    st = state.fold()
    used = {e.get("intent") for e in ledger.events() if e["type"] == "push"}
    for ev in reversed(st.push_intents):
        if ev.get("by") != "hook" or ev.get("repo") != alias(repo):
            continue
        if ledger.now() - ledger.parse_ts(ev) > window:
            break
        if ev.get("sha") == sha and ev["seq"] not in used:
            return ("instruction", ev)
    return None


# ---------------------------------------------------------------- push


def model_review(diff: str) -> tuple[bool, str]:
    """Ask a model whether the diff carries context that belongs elsewhere."""
    if not diff.strip():
        return True, "empty diff"
    prompt = (
        "You are a release gate for a personal, public dotfiles repository. Read the diff below. "
        "Does anything in it only make sense with knowledge of the author's employer: internal system or "
        "product names, internal hostnames or URLs, colleague names, ticket numbers, internal project "
        "names, or examples drawn from internal work? Generic technology names (git, tmux, Python, macOS) "
        "are fine. Answer on the first line with exactly CLEAN or LEAK, then one line per finding.\n\n"
        + diff[:150_000]
    )
    try:
        r = subprocess.run([settings().query_bin, "-p", prompt, "--model", "sonnet"], capture_output=True, text=True, timeout=300,
                           env={**os.environ, "STELLA_HEADLESS": "1"})
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"model review could not run: {e}"
    out = r.stdout.strip()
    first = out.splitlines()[0].strip().upper() if out else ""
    return first.startswith("CLEAN"), out[:2000] or r.stderr[:500]


def preflight(repo: Path, branch: str, remote: str = "origin") -> tuple[str, str | None, list[str]]:
    """Return (sha, base, problems) for pushing `branch` to `remote`."""
    sha = head(repo, branch)
    base = upstream_base(repo, remote, branch)
    rng = f"{base}..{sha}" if base else sha
    problems: list[str] = []
    if base:
        if subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", base, sha]).returncode != 0:
            problems.append(f"{branch} is not a fast-forward of {remote}/{branch}; the gate never force-pushes")
    g = leak.guard()
    if g.configured and leak.protected_root(repo, g):
        try:
            rules = leak.load_rules(g)
            hits = leak.scan_range(repo, rng, rules)
            problems += [f"leak: {h.where}: {h.term!r} in: {h.text}" for h in hits]
        except leak.DenylistMissing as e:
            problems.append(f"leak guard required but denylist missing ({e})")
    return sha, base, problems


def push(repo: Path, branch: str, remote: str = "origin", review_text: str | None = None) -> dict:
    sha, base, problems = preflight(repo, branch, remote)
    if problems:
        raise SystemExit("push refused:\n- " + "\n- ".join(problems))
    found = find_approval(repo, sha)
    if not found:
        raise SystemExit(
            f"push refused: no approval for {alias(repo)} {sha[:7]}. The owner must run `stella review-push {alias(repo)}`"
            f" or tell Stella explicitly to push {alias(repo)} (approvals are bound to the exact head commit)."
        )
    g = leak.guard()
    if g.configured and g.review and leak.protected_root(repo, g):
        diff = _git(repo, "diff", f"{base}..{sha}" if base else sha)
        ok, text = model_review(diff) if review_text is None else (True, review_text)
        if not ok:
            raise SystemExit("push refused by the model review:\n" + text)
    url = _git(repo, "remote", "get-url", remote)
    if url == BLOCKED_URL:
        raise SystemExit(f"remote {remote} has no usable fetch URL")
    nonce = secrets.token_hex(16)
    inflight = _approvals() / "inflight.json"
    inflight.write_text(json.dumps({"nonce": nonce, "sha": sha, "ref": f"refs/heads/{branch}", "repo": str(repo)}))
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), "push", url, f"{sha}:refs/heads/{branch}"],
            env={**os.environ, "STELLA_PUSH_NONCE": nonce}, text=True,
        )
    finally:
        inflight.unlink(missing_ok=True)
    if r.returncode != 0:
        raise SystemExit(f"git push failed ({r.returncode}); the approval is still unused")
    kind, rec = found
    if kind == "review":
        data = json.loads(rec.read_text())
        data["used"] = True
        rec.write_text(json.dumps(data))
    subprocess.run(["git", "-C", str(repo), "fetch", "--quiet", remote], capture_output=True)
    return ledger.append("push", by="cli", repo=alias(repo), sha=sha, ref=f"refs/heads/{branch}", approval=kind,
                         intent=rec["seq"] if kind == "instruction" else None)


def review_push(repo: Path, branch: str, remote: str = "origin") -> int:
    try:
        tty = open("/dev/tty", "r+")
    except OSError:
        print("stella review-push needs a real terminal; agents cannot approve pushes.", file=sys.stderr)
        return 2
    sha, base, problems = preflight(repo, branch, remote)
    rng = f"{base}..{sha}" if base else sha

    def say(s: str = "") -> None:
        tty.write(s + "\n")
        tty.flush()

    say(f"Push review: {alias(repo)} {branch} → {remote}   head {sha[:7]}   range {rng}")
    say(_git(repo, "log", "--oneline", "--no-decorate", rng))
    say()
    say(_git(repo, "diff", "--stat", rng if base else f"{sha}~1..{sha}", check=False))
    say()
    if problems:
        say("Checks FAILED:")
        for p in problems:
            say(f"  - {p}")
        say("Fix these first. Nothing was approved.")
        return 1
    say("Leak checks: clean.")
    g = leak.guard()
    review_text = None
    if g.configured and g.review and leak.protected_root(repo, g):
        say("Running the model review…")
        ok, review_text = model_review(_git(repo, "diff", rng))
        say(review_text)
        if not ok:
            say("The model review flagged the diff. Nothing was approved.")
            return 1
    say()
    tty.write("Press Enter to page through the full diff (q quits the pager)… ")
    tty.flush()
    tty.readline()
    subprocess.run(f"git -C {shlex.quote(str(repo))} -c color.ui=always log -p --reverse {shlex.quote(rng)} | less -R",
                   shell=True, stdin=tty, stdout=tty, stderr=tty)
    tty.write(f"Type the first 7 characters of the head commit ({sha[:7]}) to approve and push, anything else to cancel: ")
    tty.flush()
    answer = tty.readline().strip()
    if answer != sha[:7]:
        say("Cancelled. Nothing was approved.")
        return 1
    write_approval(repo, sha, branch, "review")
    ev = push(repo, branch, remote, review_text=review_text or "")
    say(f"Pushed {sha[:7]} to {remote}/{branch} (ledger #{ev['seq']}).")
    return 0


def push_question(repo: Path, branch: str, session: str | None) -> str:
    sha, base, problems = preflight(repo, branch)
    rng = f"{base}..{sha}" if base else sha
    n = len(_git(repo, "rev-list", rng).splitlines())
    ledger.append("push_question", by="cli", repo=alias(repo), sha=sha, branch=branch, session=session)
    text = f"Push {alias(repo)} {branch}: {n} commit(s), {rng}, head {sha[:7]}?"
    if problems:
        text += " Checks currently FAIL: " + "; ".join(problems)
    return text


# ---------------------------------------------------------------- git hooks


HOOK_SCRIPT = """#!/bin/sh
# Installed by stella. Do not edit: see `stella gate status`.
exec "{bin}" git-hook {name} "$@"
"""


def install(repo: Path) -> list[str]:
    done = []
    hooks = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "hooks"
    hooks.mkdir(exist_ok=True)
    for name in ("pre-push", "pre-commit", "commit-msg"):
        p = hooks / name
        body = HOOK_SCRIPT.format(bin=BIN, name=name)
        if p.exists() and p.read_text() != body:
            p.rename(p.with_suffix(".pre-stella"))
            done.append(f"kept the old {name} hook as {name}.pre-stella")
        p.write_text(body)
        p.chmod(0o755)
        done.append(f"installed {name} hook")
    for remote in _git(repo, "remote").split():
        _git(repo, "config", f"remote.{remote}.pushurl", BLOCKED_URL)
        done.append(f"set {remote} push URL to {BLOCKED_URL}")
    return done


def status(repo: Path) -> list[str]:
    out = []
    hooks = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "hooks"
    hp = _git(repo, "config", "--get", "core.hooksPath", check=False)
    if hp:
        out.append(f"FAIL core.hooksPath is set ({hp}); the gate's hooks would be skipped")
    for name in ("pre-push", "pre-commit", "commit-msg"):
        p = hooks / name
        ok = p.exists() and str(BIN) in p.read_text()
        out.append(f"{'ok  ' if ok else 'FAIL'} {name} hook")
    for remote in _git(repo, "remote").split():
        pu = _git(repo, "config", "--get", f"remote.{remote}.pushurl", check=False)
        out.append(f"{'ok  ' if pu == BLOCKED_URL else 'FAIL'} {remote} push URL {'blocked' if pu == BLOCKED_URL else repr(pu)}")
    return out


def git_hook(name: str, argv: list[str], stdin: str) -> int:
    repo = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel"))
    root = guarded_root(repo)
    g = leak.guard()
    protected = g.configured and leak.protected_root(repo, g)
    if name == "pre-push":
        if not root:
            return 0
        nonce = os.environ.get("STELLA_PUSH_NONCE")
        inflight = store_dir() / "approvals" / "inflight.json"
        rec = json.loads(inflight.read_text()) if inflight.exists() else None
        if not nonce or not rec or rec.get("nonce") != nonce:
            print("STELLA PUSH GATE: pushes from this repo go through `stella push` after the owner approves.", file=sys.stderr)
            return 1
        for line in stdin.splitlines():
            parts = line.split()
            if len(parts) != 4:
                continue
            _lref, lsha, rref, _rsha = parts
            if lsha != rec["sha"] or rref != rec["ref"]:
                print(f"STELLA PUSH GATE: approval covers {rec['sha'][:7]} → {rec['ref']} only.", file=sys.stderr)
                return 1
        return 0
    if not protected:
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
