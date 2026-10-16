"""What an order is about: PRs, repos and team names, for conflict detection.

Two open orders that share a target are shown as a *possible* conflict. Whether
they really contradict is left to judgment; this only makes sure the candidates
are always in front of it.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

from stella.config import settings

_PR_URL = re.compile(r"https?://[^/\s]+/[\w.-]+/([\w.-]+)/pull/(\d+)")
_PR_REF = re.compile(r"\b(?:[\w.-]+/)?([A-Za-z][\w.-]*)#(\d+)\b")
_BARE = re.compile(r"(?<![\w#./:-])#?(\d{3,6})\b(?![:.]\d)")
_WORD = re.compile(r"[A-Za-z][\w.-]{2,}")


@cache
def _repo_names() -> frozenset[str]:
    root: Path = settings().repos_dir
    if not root.is_dir():
        return frozenset()
    return frozenset(p.name.lower() for p in root.iterdir() if (p / ".git").exists())


def extract(text: str, team_names: set[str] | frozenset[str] = frozenset()) -> list[str]:
    found: set[str] = set()
    for repo, num in _PR_URL.findall(text):
        found |= {f"{repo.lower()}#{num}", f"#{num}"}
    for repo, num in _PR_REF.findall(text):
        found |= {f"{repo.lower()}#{num}", f"#{num}"}
    for num in _BARE.findall(text):
        if not (1990 <= int(num) <= 2099):
            found.add(f"#{num}")
    words = {w.lower().rstrip(".-") for w in _WORD.findall(text)}
    repos = _repo_names()
    found |= {f"repo:{w}" for w in words if w in repos}
    teams = {t.lower() for t in team_names}
    found |= {f"team:{w}" for w in words if w in teams}
    return sorted(found)
