"""`~/.local/bin/stella context`: everything Stella needs at the start of a turn or session.

Core persona and procedures live in the `stella` skill. This adds what only the
machine knows: the owner's name, each extension's persona, knowledge map and
playbook, the team list, and the state brief.
"""

from __future__ import annotations

from stella import brief, extensions, registry, state
from stella.config import settings


def _ext_section(key: str, title: str) -> list[str]:
    out = []
    for ext in extensions.load():
        f = ext.file(key)
        if f and f.exists():
            out += ["", f"## {title} ({ext.name})", f.read_text().strip()]
    return out


def render(mode: str = "turn", include_brief: bool = True) -> str:
    s = settings()
    lines = [f"# Stella context (owner: {s.owner})"]
    if mode == "self":
        lines.append(
            f"This is your own session, Stella (`stella run`). Every message here is from {s.owner} to you."
        )
    elif mode == "turn":
        lines.append(
            f"This turn is addressed to you, Stella. Follow the `stella` skill (load it with the Skill tool"
            f" if you have not this session). After this turn, {s.owner} is talking to the session again,"
            " not to you, unless addressed again."
        )
    elif mode == "team":
        lines.append("You are a team lead launched by Stella. These are the knowledge sources and rules you share with her.")
    lines += _ext_section("persona", "Persona addenda")
    lines += _ext_section("knowledge", "Knowledge map")
    lines += _ext_section("playbook", "Engineering playbook addenda")
    if mode != "team":
        teams, errors = registry.load()
        lines += ["", "## Teams (full interface: `~/.local/bin/stella team <name>`)"] + registry.summary_lines(teams)
        if errors:
            lines += [f"- REGISTRY ERROR: {e}" for e in errors]
    if include_brief and mode != "team":
        lines += ["", brief.render(state.fold())]
    return "\n".join(lines)
