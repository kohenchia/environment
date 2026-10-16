"""The team registry: which archetypes exist and how to drive each one.

Teams come from the core's `teams.toml` and from each extension's teams file. An
entry points at the team's own interface (its skill file and CLI commands) rather
than copying it, so a team edited in its own repo never drifts from what Stella
knows. A name defined twice is an error, not an override.
"""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from stella import extensions
from stella.config import CORE_ROOT


@dataclass
class Team:
    name: str
    source: str
    base: Path
    summary: str = ""
    when: str = ""
    launch: str = "{order}"
    skill_file: str = ""
    commands: list[str] = field(default_factory=list)
    status: str = ""
    correct: str = ""
    dir: str = ""
    permission_mode: str = "default"
    read_only: bool = False
    raw: dict = field(default_factory=dict)

    @property
    def skill_path(self) -> Path | None:
        if not self.skill_file:
            return None
        return (self.base / Path(self.skill_file).expanduser()).resolve()

    def skill_frontmatter(self) -> dict[str, str]:
        p = self.skill_path
        if not p or not p.exists():
            return {}
        return parse_frontmatter(p.read_text())


def parse_frontmatter(text: str) -> dict[str, str]:
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t")):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _load_file(path: Path, source: str) -> tuple[list[Team], list[str]]:
    errors: list[str] = []
    try:
        data = tomllib.loads(path.read_text())
    except (FileNotFoundError, tomllib.TOMLDecodeError) as e:
        return [], [f"{path}: {e}"]
    teams = []
    for name, entry in (data.get("team") or {}).items():
        known = {f for f in Team.__dataclass_fields__} - {"name", "source", "base", "raw"}
        kwargs = {k: v for k, v in entry.items() if k in known}
        teams.append(Team(name=name, source=source, base=path.parent, raw=entry, **kwargs))
    return teams, errors


def load() -> tuple[dict[str, Team], list[str]]:
    teams: dict[str, Team] = {}
    errors: list[str] = []
    sources = [(CORE_ROOT / "teams.toml", "core")]
    for ext in extensions.load():
        f = ext.file("teams")
        if f:
            sources.append((f, ext.name))
    for path, source in sources:
        found, errs = _load_file(path, source)
        errors += errs
        for t in found:
            if t.name in teams:
                errors.append(f"team {t.name!r} defined by both {teams[t.name].source} and {source}")
                continue
            teams[t.name] = t
    return teams, errors


def summary_lines(teams: dict[str, Team]) -> list[str]:
    return [f"- {t.name} ({t.source}): {t.summary} Use when: {t.when}" for t in teams.values()]


def interface(t: Team, run_help: bool = True) -> str:
    fm = t.skill_frontmatter()
    out = [f"# Team {t.name} ({t.source})", "", t.summary, "", f"Use when: {t.when}", ""]
    out.append(f"Launch (first prompt to the lead): {t.launch}")
    if fm:
        if fm.get("argument-hint"):
            out.append(f"Arguments (from the skill's argument-hint): {fm['argument-hint']}")
        if fm.get("description"):
            out.append(f"Skill description: {fm['description']}")
    elif t.skill_file:
        out.append(f"WARNING: skill file {t.skill_path} is missing or has no frontmatter")
    out.append(f"Working directory: {t.dir or '(caller decides)'}")
    out.append(f"Permission mode: {t.permission_mode}{' (read-only work)' if t.read_only else ''}")
    if t.status:
        out.append(f"Status command: {t.status}")
    if t.correct:
        out.append(f"How to correct this team: {t.correct}")
    for cmd in t.commands:
        out += ["", f"## `{cmd}`"]
        if not run_help:
            continue
        try:
            r = subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=30)
            text = (r.stdout or r.stderr).strip().splitlines()
            out += text[:40] + (["…"] if len(text) > 40 else [])
        except (OSError, subprocess.TimeoutExpired) as e:
            out.append(f"(could not run: {e})")
    return "\n".join(out)


def check(t: Team) -> list[str]:
    """Problems with a team's interface, for `stella doctor`."""
    problems = []
    if t.skill_file:
        p = t.skill_path
        if not p or not p.exists():
            problems.append(f"skill file missing: {p}")
        elif not t.skill_frontmatter():
            problems.append(f"skill file has no frontmatter: {p}")
    for cmd in t.commands + ([t.status] if t.status else []):
        exe = shlex.split(cmd)[0]
        if not (shutil.which(exe) or Path(exe).expanduser().exists()):
            problems.append(f"command not found: {exe}")
    return problems


def first_prompt(t: Team, order_text: str, args: str = "", name: str = "") -> str:
    return t.launch.format(order=order_text, args=args or order_text, name=name).strip()
