"""Extensions: directories of teams, knowledge and checks loaded beside the core.

The core never names an extension. `~/.config/stella/extensions.toml` lists them:

    [[extension]]
    path = "/path/to/some/extension"

Each extension directory holds `stella-extension.toml`:

    name = "..."
    contract = 1
    teams = "teams.toml"            # optional
    knowledge = "knowledge.md"      # optional, appended to `stella context`
    persona = "persona.md"          # optional
    playbook = "playbook.md"        # optional
    daily = "daily.md"              # optional: prompt template for the daily log
    checks = "checks.toml"          # optional: extra `stella doctor` checks
    nightly = "nightly.toml"        # optional: [[job]] name, cmd, timeout; run at the nightly, last line to ledger + digest
    [settings]                      # optional: merged into the machine settings
    [leak_guard]                    # optional
    protect = ["~/some/repo"]
    denylist = "denylist/built.txt"
    rebuild = "bin/build-denylist"
    required = true
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONTRACT = 1


@dataclass
class Extension:
    name: str
    root: Path
    manifest: dict
    errors: list[str] = field(default_factory=list)

    def file(self, key: str) -> Path | None:
        rel = self.manifest.get(key)
        if not rel:
            return None
        return (self.root / rel).resolve()

    @property
    def settings(self) -> dict:
        return dict(self.manifest.get("settings", {}))

    @property
    def leak_guard(self) -> dict:
        return dict(self.manifest.get("leak_guard", {}))


def registry_file() -> Path:
    from stella.config import config_dir

    return config_dir() / "extensions.toml"


def load() -> list[Extension]:
    reg = registry_file()
    if not reg.exists():
        return []
    try:
        entries = tomllib.loads(reg.read_text()).get("extension", [])
    except tomllib.TOMLDecodeError:
        return []
    out: list[Extension] = []
    for entry in entries:
        root = Path(str(entry.get("path", ""))).expanduser()
        mf = root / "stella-extension.toml"
        if not mf.exists():
            out.append(Extension(root.name, root, {}, [f"missing manifest {mf}"]))
            continue
        try:
            manifest = tomllib.loads(mf.read_text())
        except tomllib.TOMLDecodeError as e:
            out.append(Extension(root.name, root, {}, [f"bad manifest: {e}"]))
            continue
        ext = Extension(manifest.get("name", root.name), root, manifest)
        if manifest.get("contract") != CONTRACT:
            ext.errors.append(f"contract {manifest.get('contract')!r}, core expects {CONTRACT}")
        out.append(ext)
    return out


def register(path: Path) -> bool:
    """Add an extension directory to the registry. Returns False if already there."""
    reg = registry_file()
    reg.parent.mkdir(parents=True, exist_ok=True)
    path = path.expanduser().resolve()
    existing = []
    if reg.exists():
        existing = tomllib.loads(reg.read_text()).get("extension", [])
    if any(Path(e.get("path", "")).expanduser().resolve() == path for e in existing):
        return False
    with reg.open("a") as f:
        f.write(f'\n[[extension]]\npath = "{path}"\n')
    return True


def unregister(path: Path) -> bool:
    reg = registry_file()
    if not reg.exists():
        return False
    path = path.expanduser().resolve()
    entries = tomllib.loads(reg.read_text()).get("extension", [])
    keep = [e for e in entries if Path(e.get("path", "")).expanduser().resolve() != path]
    if len(keep) == len(entries):
        return False
    reg.write_text("".join(f'[[extension]]\npath = "{e["path"]}"\n\n' for e in keep))
    return True
