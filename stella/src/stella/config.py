"""Where things live, and the machine-local settings.

Nothing in this module names a particular employer, extension or machine. Machine
specifics come from `~/.config/stella/config.toml` and from each registered
extension's manifest (see `extensions.py`).
"""

from __future__ import annotations

import os
import subprocess
import tomllib
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parents[2]  # .../stella (the core project)
PLUGIN_DIR = CORE_ROOT / "plugin"
BIN = CORE_ROOT / "bin" / "stella"


def _expand(p: str | os.PathLike[str]) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(p))))


def config_dir() -> Path:
    return _expand(os.environ.get("STELLA_CONFIG", "~/.config/stella"))


def store_dir() -> Path:
    return _expand(os.environ.get("STELLA_STORE", "~/.local/share/stella"))


@dataclass
class Settings:
    owner: str = "the user"
    tmux_session: str = "work"
    tmux_expected_app: str = ""
    repos_dir: Path = field(default_factory=lambda: _expand("~/github"))
    claude_bin: str = "claude"
    claude_query_bin: str = ""
    daily_time: str = "20:00"
    stale_days: int = 7
    brief_lines: int = 60
    delta_lines: int = 15
    push_approval_minutes: int = 60
    push_intent_minutes: int = 15
    guarded_repos: list[Path] = field(default_factory=list)

    @property
    def query_bin(self) -> str:
        return self.claude_query_bin or self.claude_bin


def _merge(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        elif isinstance(v, list) and isinstance(dst.get(k), list):
            dst[k] = dst[k] + [x for x in v if x not in dst[k]]
        else:
            dst[k] = v


def raw_config() -> dict:
    """Merged settings: extension manifests' [settings], then the machine config."""
    from stella import extensions

    data: dict = {}
    for ext in extensions.load():
        _merge(data, ext.settings)
    path = config_dir() / "config.toml"
    if path.exists():
        _merge(data, tomllib.loads(path.read_text()))
    return data


@cache
def settings() -> Settings:
    data = raw_config()
    s = Settings()
    for key in (
        "owner",
        "tmux_session",
        "tmux_expected_app",
        "claude_bin",
        "claude_query_bin",
        "daily_time",
        "stale_days",
        "brief_lines",
        "delta_lines",
        "push_approval_minutes",
        "push_intent_minutes",
    ):
        if key in data:
            setattr(s, key, data[key])
    if "repos_dir" in data:
        s.repos_dir = _expand(data["repos_dir"])
    s.claude_bin = os.path.expanduser(s.claude_bin)
    s.claude_query_bin = os.path.expanduser(s.claude_query_bin)
    guarded = [own_repo()] + [_expand(p) for p in data.get("guarded_repos", [])]
    s.guarded_repos = [p for p in dict.fromkeys(guarded) if p is not None]
    return s


@cache
def own_repo() -> Path | None:
    """The git checkout the core lives in. The push gate always guards it."""
    try:
        out = subprocess.run(
            ["git", "-C", str(CORE_ROOT), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return Path(out).resolve() if out else None
