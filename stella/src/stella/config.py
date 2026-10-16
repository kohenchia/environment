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
# How agents invoke the CLI. Always this exact spelling, so a sandbox allowlist entry for it matches.
CALL = "~/.local/bin/stella"


def headless_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """The environment for a `claude -p` run Stella starts. STELLA_HEADLESS keeps her hooks quiet.
    CLAUDE_CODE_ENTRYPOINT names the session's origin; its default for `-p`, `sdk-cli`, is one
    Claude Code leaves out of the `--resume` / `/resume` picker, so those sessions could only be
    resumed by id. Any other value lists them."""
    return {**(os.environ if base is None else base), "STELLA_HEADLESS": "1", "CLAUDE_CODE_ENTRYPOINT": "stella"}


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
    permission_mode: str = "default"
    daily_time: str = "20:00"
    stale_days: int = 7
    brief_lines: int = 60
    delta_lines: int = 15
    # The wake line (see wake.py): events this close together share one line, lines are at least this
    # far apart, and the scheduler's backstop looks for a wake line that never arrived this often.
    wake_merge_seconds: int = 20
    wake_gap_seconds: int = 60
    wake_check_minutes: int = 20
    guarded_repos: list[Path] = field(default_factory=list)
    # Environment variables forwarded from the launcher into every team session it opens.
    pass_env: list[str] = field(default_factory=list)
    # Where a pass_env variable's value is read when the caller lacks it: one file per variable.
    pass_env_dir: Path | None = None

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
        "permission_mode",
        "daily_time",
        "stale_days",
        "brief_lines",
        "delta_lines",
        "wake_merge_seconds",
        "wake_gap_seconds",
        "wake_check_minutes",
    ):
        if key in data:
            setattr(s, key, data[key])
    if "pass_env" in data:
        s.pass_env = [str(v) for v in data["pass_env"]]
    if data.get("pass_env_dir"):
        s.pass_env_dir = _expand(data["pass_env_dir"])
    if "repos_dir" in data:
        s.repos_dir = _expand(data["repos_dir"])
    s.claude_bin = os.path.expanduser(s.claude_bin)
    s.claude_query_bin = os.path.expanduser(s.claude_query_bin)
    guarded = [own_repo()] + [_expand(p) for p in data.get("guarded_repos", [])]
    s.guarded_repos = [p for p in dict.fromkeys(guarded) if p is not None]
    return s


@cache
def own_repo() -> Path | None:
    """The git checkout the core lives in. It is always a guarded repo."""
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
