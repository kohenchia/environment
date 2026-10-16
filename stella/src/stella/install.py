"""`stella install`: set this machine up. Safe to re-run."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from stella import canon, daily, gate
from stella.config import BIN, CORE_ROOT, settings

MARKETPLACE = "stella-local"


def _run(*cmd: str) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def link_bin() -> str:
    target = Path.home() / ".local" / "bin" / "stella"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() and target.resolve() == BIN.resolve():
        return f"{target} already links to {BIN}"
    if target.exists() or target.is_symlink():
        target.rename(target.with_suffix(".bak"))
    target.symlink_to(BIN)
    on_path = shutil.which("stella")
    return f"linked {target} → {BIN}" + ("" if on_path else " (~/.local/bin is not on PATH)")


def install_plugin() -> list[str]:
    claude = settings().query_bin
    out = []
    rc, txt = _run(claude, "plugin", "marketplace", "add", str(CORE_ROOT))
    out.append(f"marketplace {MARKETPLACE}: {'added' if rc == 0 else txt.splitlines()[-1] if txt else rc}")
    rc, txt = _run(claude, "plugin", "install", f"stella@{MARKETPLACE}")
    out.append(f"plugin stella: {'installed' if rc == 0 else txt.splitlines()[-1] if txt else rc}")
    return out


def install(plugin: bool = True, gate_: bool = True) -> list[str]:
    out = []
    venv = CORE_ROOT / ".venv"
    if not venv.exists():
        rc, txt = _run("uv", "sync", "--project", str(CORE_ROOT), "--quiet")
        out.append("created the venv" if rc == 0 else f"uv sync failed: {txt[-300:]}")
    out.append(link_bin())
    made = canon.init_store()
    out.append("store: " + (", ".join(made) if made else "already set up"))
    if gate_:
        for repo in gate.guarded_repos():
            out += [f"gate {repo.name}: {l}" for l in gate.install(repo)]
        daily.record_baseline()
    if plugin:
        out += install_plugin()
    return out
