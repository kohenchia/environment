"""Leak checks: keep terms an extension marks as private out of protected repos.

The core holds only the mechanism. The terms (the *denylist*) and the protected
repos come from extension manifests' [leak_guard] tables, so the core never
contains the very words it guards against.

Denylist file format, one rule per line (`#` comments):

    word:Term        case-insensitive whole word
    cs:Term          case-sensitive whole word
    re:<regex>       Python regex, case-insensitive
    allow:<regex>    text matching this is removed before checking
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from stella import extensions


@dataclass
class Guard:
    protect: list[Path] = field(default_factory=list)
    denylist: list[Path] = field(default_factory=list)
    rebuild: list[Path] = field(default_factory=list)
    required: bool = False
    review: bool = False

    @property
    def configured(self) -> bool:
        return bool(self.protect)


def guard() -> Guard:
    g = Guard()
    for ext in extensions.load():
        lg = ext.leak_guard
        if not lg:
            continue
        g.protect += [Path(os.path.expanduser(p)).resolve() for p in lg.get("protect", [])]
        if lg.get("denylist"):
            g.denylist.append((ext.root / lg["denylist"]).resolve())
        if lg.get("rebuild"):
            g.rebuild.append((ext.root / lg["rebuild"]).resolve())
        g.required |= bool(lg.get("required"))
        g.review |= bool(lg.get("model_review", True))
    return g


@dataclass
class Rules:
    patterns: list[tuple[str, re.Pattern]]
    allow: list[re.Pattern]


class DenylistMissing(Exception):
    pass


def load_rules(g: Guard | None = None) -> Rules:
    g = g or guard()
    pats: list[tuple[str, re.Pattern]] = []
    allow: list[re.Pattern] = []
    if g.required and not all(p.exists() for p in g.denylist):
        raise DenylistMissing(", ".join(str(p) for p in g.denylist if not p.exists()) or "no denylist configured")
    for path in g.denylist:
        if not path.exists():
            continue
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            kind, _, val = line.partition(":")
            if not val:
                continue
            if kind == "word":
                pats.append((val, re.compile(rf"(?<![\w-]){re.escape(val)}(?![\w])", re.I)))
            elif kind == "cs":
                pats.append((val, re.compile(rf"(?<![\w-]){re.escape(val)}(?![\w])")))
            elif kind == "re":
                pats.append((val, re.compile(val, re.I)))
            elif kind == "allow":
                allow.append(re.compile(val, re.I))
    if g.required and not pats:
        raise DenylistMissing("denylist is empty")
    return Rules(pats, allow)


@dataclass
class Hit:
    where: str
    line: int
    term: str
    text: str


def scan_text(text: str, where: str, rules: Rules) -> list[Hit]:
    hits = []
    for i, line in enumerate(text.splitlines() or [text], 1):
        clean = line
        for a in rules.allow:
            clean = a.sub(" ", clean)
        for term, pat in rules.patterns:
            if pat.search(clean):
                hits.append(Hit(where, i, term, line.strip()[:160]))
    return hits


def protected_root(path: str | os.PathLike, g: Guard | None = None) -> Path | None:
    g = g or guard()
    try:
        p = Path(os.path.expanduser(str(path))).resolve()
    except (OSError, RuntimeError):
        return None
    for root in g.protect:
        if p == root or root in p.parents:
            return root
        # worktrees of a protected repo share its git common dir
    return _worktree_of(p, g)


def _worktree_of(p: Path, g: Guard) -> Path | None:
    d = p if p.is_dir() else p.parent
    while d != d.parent and not d.exists():
        d = d.parent
    try:
        common = subprocess.run(
            ["git", "-C", str(d), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    if not common:
        return None
    common_p = Path(common).resolve()
    for root in g.protect:
        if common_p == (root / ".git").resolve():
            return root
    return None


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def scan_staged(repo: Path, rules: Rules) -> list[Hit]:
    diff = _git(repo, "diff", "--cached", "--no-color", "-U0", "--no-ext-diff")
    return _scan_diff(diff, rules) + _scan_names(_git(repo, "diff", "--cached", "--name-only"), rules)


def scan_range(repo: Path, rng: str, rules: Rules) -> list[Hit]:
    diff = _git(repo, "log", "-p", "--no-color", "-U0", "--format=commit %H%n%B", rng)
    return _scan_diff(diff, rules, include_messages=True)


def _scan_diff(diff: str, rules: Rules, include_messages: bool = False) -> list[Hit]:
    hits: list[Hit] = []
    current = "?"
    in_msg = False
    for line in diff.splitlines():
        if line.startswith("commit ") and include_messages:
            current, in_msg = f"commit {line[7:14]} message", True
            continue
        if line.startswith("diff --git"):
            in_msg = False
            current = line.split(" b/", 1)[-1]
            continue
        if line.startswith("+++ ") or line.startswith("--- "):
            continue
        if line.startswith("+") or (in_msg and include_messages):
            hits += [Hit(current, 0, h.term, h.text) for h in scan_text(line.lstrip("+"), current, rules)]
    return hits


def _scan_names(names: str, rules: Rules) -> list[Hit]:
    return [h for n in names.splitlines() for h in scan_text(n, f"path {n}", rules)]


def scan_tree(root: Path, rules: Rules) -> list[Hit]:
    files = _git(root, "ls-files", "--cached", "--others", "--exclude-standard").splitlines()
    hits: list[Hit] = []
    for rel in files:
        p = root / rel
        hits += _scan_names(rel, rules)
        try:
            text = p.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        hits += scan_text(text, rel, rules)
    return hits


def rebuild() -> list[str]:
    out = []
    for cmd in guard().rebuild:
        r = subprocess.run([str(cmd)], capture_output=True, text=True)
        out.append(f"{cmd}: {'ok' if r.returncode == 0 else 'FAILED ' + r.stderr.strip()[:200]}")
    return out
