"""A temporary HOME with a fake Claude daemon and a fake herdr (see fake_daemon.py), for tests of the session tools.

    with World() as w:
        w.job("backlog", state="working", running=True)
        w.pane("w1", "t1", attach="aaaa0001")
        p = w.run("kc-sessions", "respawn", "backlog")
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

FAKE = Path(__file__).resolve().parent / "fake_daemon.py"
ENV_BIN = Path(__file__).resolve().parents[1] / "bin"


class World:
    def __init__(self, wrapper: str | None = None, extra_env: dict | None = None):
        self._t = tempfile.TemporaryDirectory()
        self.home = Path(self._t.name)
        self.bin = self.home / "bin"
        self.bin.mkdir()
        self.dir = self.home / "fake"
        self.dir.mkdir()
        self.world_file = self.dir / "world.json"
        self.world = {"pid": 20000, "next": 0, "jobs": {}, "workers": {}, "workspaces": {}, "tabs": {}, "panes": {}, "late_exit": 0.3}
        self.wrapper = wrapper
        self.extra_env = extra_env or {}
        for name in ("claude", "herdr"):
            (self.bin / name).write_text(f'#!/bin/sh\nexec python3 "{FAKE}" {name} "$@"\n')
            (self.bin / name).chmod(0o755)
        self.save()
        (self.home / "github").mkdir()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._t.cleanup()

    # ── building the world ───────────────────────────────────────────────────────────────────────────────────
    def env(self, **more) -> dict:
        env = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin:/usr/local/bin",
               "FAKE_WORLD": str(self.world_file), "KC_SESSIONS_POLL": "0.02", "KC_SESSIONS_TIMEOUT_SCALE": "0.25",
               "KC_SESSIONS_STATE": str(self.home / "kcs")}
        if self.wrapper:
            env["FAKE_WRAPPER"] = self.wrapper
        env.update(self.extra_env)
        env.update(more)
        return env

    def save(self):
        self.world_file.write_text(json.dumps(self.world))
        self.ctl("noop")

    def ctl(self, *args) -> None:
        subprocess.run(["python3", str(FAKE), "ctl", *args], env=self.env(), check=True, capture_output=True)

    def load(self) -> dict:
        return json.loads(self.world_file.read_text())

    def _fresh(self) -> dict:
        """The world as the fake tools left it (they change it while a test runs)."""
        self.world = self.load()
        return self.world

    def job(self, name: str, *, state: str = "done", running: bool = False, flags: list | None = None, jid: str | None = None,
            cwd: str | None = None, tempo: str = "idle", created: str | None = None, in_flight: dict | None = None) -> str:
        w = self._fresh()
        w["next"] += 1
        jid = jid or f"{w['next']:08x}"
        sid = f"{jid}-0000-4000-8000-000000000000"
        cwd = cwd or str(self.home / "github")
        Path(cwd).mkdir(parents=True, exist_ok=True)
        transcript = self.home / ".claude/projects/p" / f"{sid}.jsonl"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text('{"message":{"model":"claude-opus-5-5"}}\n')
        w["jobs"][jid] = {"sessionId": sid, "name": name, "state": state, "tempo": tempo, "cwd": cwd,
                          "flags": flags if flags is not None else ["--dangerously-skip-permissions"],
                          "createdAt": created or time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(1_790_000_000 + w["next"])),
                          "transcript": str(transcript), "template": "bg",
                          **({"inFlight": in_flight} if in_flight else {})}
        if running:
            w["pid"] += 2
            w["workers"][jid] = {"pid": w["pid"], "replPid": w["pid"] + 1, "procStart": "Tue Oct 20 21:00:00 2026"}
        self.save()
        return jid

    def pane(self, pane: str, tab: str | None = None, *, attach: str | None = None, ws: str = "w1", ws_label: str = "work",
             tab_label: str | None = None, fg: str | None = None, screen: list | None = None) -> str:
        w = self._fresh()
        tab = tab or f"{ws}:t{len(w['tabs']) + 1}"
        w["workspaces"].setdefault(ws, {"label": ws_label})
        w["tabs"].setdefault(tab, {"ws": ws, "label": tab_label or pane})
        w["pid"] += 1
        w["panes"][pane] = {"tab": tab, "cwd": str(self.home / "github"), "attach_pid": w["pid"],
                            "fg": fg or (f"attach:{attach}" if attach else "shell"),
                            "screen": screen or (["claude attach " + attach] if attach else ["kohen@mac ~ %"])}
        self.save()
        return pane

    def opt(self, key: str, value) -> None:
        self._fresh()[key] = value
        self.save()

    # ── running tools ────────────────────────────────────────────────────────────────────────────────────────
    def run(self, *cmd: str, env: dict | None = None, timeout: float = 120, stdin: str | None = None) -> subprocess.CompletedProcess:
        script = Path(cmd[0])
        if not script.is_absolute():
            script = ENV_BIN / cmd[0]
        full = [str(script), *cmd[1:]]
        if script.read_text().startswith("#!/usr/bin/env python3"):
            full = ["python3", *full]
        return subprocess.run(full, env={**self.env(), **(env or {})}, capture_output=True, text=True, timeout=timeout, input=stdin)

    def calls(self) -> list[str]:
        f = self.dir / "calls.log"
        return f.read_text().splitlines() if f.exists() else []

    def claude_calls(self) -> list[str]:
        return [c[len("claude "):] for c in self.calls() if c.startswith("claude ") and not c.startswith("claude agents")]

    def typed(self) -> list[str]:
        return [c for c in self.calls() if c.startswith("TYPED ")]

    def snapshot(self) -> dict:
        """The things a restart must not change: jobs (id, name, flags, cwd, transcript), windows and what they attach."""
        w = self.load()
        return {
            "jobs": {j: {k: v[k] for k in ("sessionId", "name", "flags", "cwd", "transcript", "template")} for j, v in w["jobs"].items()},
            "workers": sorted(w["workers"]),
            "herdr": {"workspaces": w["workspaces"], "tabs": w["tabs"],
                      "panes": {p: {"tab": v["tab"], "cwd": v["cwd"], "fg": v["fg"]} for p, v in w["panes"].items()}},
        }
