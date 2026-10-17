"""Differential test for kc-hook: the new script must behave byte-for-byte like the old one in every
session except Stella's own (cwd ~/.local/share/stella), because kc-hook runs in every Claude session on
the machine the moment it is merged.

The old script is kc-hook as of BASELINE (the commit before Work Env 3.0), or $KC_HOOK_OLD. Run:

    python3 -m unittest discover -s claude/tests
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NEW = REPO / "claude/bin/kc-hook"
HOME = Path.home()
STELLA_HOME = HOME / ".local/share/stella"
BASELINE = "e58bf30"  # kc-hook before Work Env 3.0; pinned so the test still compares after the merge

RULE = "━" * 40
GOOD = f"Done.\n\n{RULE}\n\U0001f7e9 **ALL DONE** — nothing left for you."
NEXT = f"Hi.\n\n{RULE}\n\U0001f7e7 **NEXT FOR YOU** (2)\n1. Decide A.\n2. Decide B."
BAD = "Here is the answer, with no status block."


def old_script(tmp: Path) -> Path:
    if os.environ.get("KC_HOOK_OLD"):
        return Path(os.environ["KC_HOOK_OLD"])
    src = subprocess.run(["git", "-C", str(REPO), "show", f"{BASELINE}:claude/bin/kc-hook"],
                         capture_output=True, text=True, check=True).stdout
    path = tmp / "kc-hook-old"
    path.write_text(src)
    return path


def corpus(cwds: list[Path]) -> list[tuple[str, dict]]:
    cases: list[tuple[str, dict]] = []
    for cwd in cwds:
        c = str(cwd)
        for msg in (GOOD, NEXT, BAD, ""):
            cases.append(("stop", {"cwd": c, "last_assistant_message": msg}))
        cases.append(("stop", {"cwd": c, "last_assistant_message": BAD, "stop_hook_active": True}))
        for text in ("S, review PR 12", "Stella, what is running?", "ask Stella about it", "fix the test",
                     "thanks stella", ""):
            cases.append(("prompt", {"cwd": c, "prompt": text}))
        for cmd in ("git push", "git -C ~/github/environment push", "cd ~/github/environment && git push",
                    "KC_OWNER_SAID_PUSH=1 git push", "ls -la", "git status"):
            cases.append(("pretool", {"cwd": c, "tool_name": "Bash", "tool_input": {"command": cmd}}))
        cases.append(("pretool", {"cwd": c, "tool_name": "Read", "tool_input": {"file_path": "/x"}}))
    cases.append(("stop", {"not": "the expected shape"}))
    return cases


def run(script: Path, handler: str, data: dict, env: dict) -> tuple[int, str, str]:
    p = subprocess.run(["python3", str(script), handler], input=json.dumps(data),
                       capture_output=True, text=True, env=env, timeout=30)
    return p.returncode, p.stdout, p.stderr


class KcHookDifferential(unittest.TestCase):
    def test_identical_outside_stella_home(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            old = old_script(tmp)
            env = dict(os.environ)
            env.pop("CLAUDE_CODE_ENTRYPOINT", None)
            cwds = [HOME / "github", HOME / "github/environment", tmp, HOME]
            diffs = []
            for handler, data in corpus(cwds):
                a = run(old, handler, data, env)
                b = run(NEW, handler, data, env)
                if a != b:
                    diffs.append(f"{handler} {json.dumps(data)[:120]}\n  old={a}\n  new={b}")
            self.assertEqual(diffs, [], "\n".join(diffs))

    def test_corpus_exercises_every_handler(self):
        handlers = {h for h, _ in corpus([HOME])}
        self.assertEqual(handlers, {"stop", "prompt", "pretool"})


class TurnEndGuard(unittest.TestCase):
    """The one behaviour allowed to differ: in Stella's home, crew in flight with no live watcher blocks once."""

    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.home = Path(self.t.name)
        self.sh = self.home / ".local/share/stella"
        (self.sh / "crew/fix").mkdir(parents=True)
        self.env = {"HOME": str(self.home), "PATH": "/usr/bin:/bin"}

    def tearDown(self):
        self.t.cleanup()

    def stop(self, **extra):
        data = {"cwd": str(self.sh), "last_assistant_message": GOOD, **extra}
        return run(NEW, "stop", data, self.env)

    def record(self, **rec):
        (self.sh / "crew/fix/record.json").write_text(json.dumps({"name": "fix", "state": "working", **rec}))

    def test_blocks_when_crew_in_flight_and_no_watcher(self):
        self.record()
        code, out, err = self.stop()
        self.assertEqual(code, 0)
        self.assertIn('"decision": "block"', out)
        self.assertIn("stella-watch is not running", out)

    def test_quiet_with_live_watcher(self):
        import time
        self.record()
        (self.sh / "watch.pid").write_text(json.dumps({"pid": os.getpid(), "beat": time.time()}))
        self.assertEqual(self.stop()[1], "")
        (self.sh / "watch.pid").write_text(json.dumps({"pid": 999999, "beat": time.time()}))
        self.assertIn("stella-watch is not running", self.stop()[1])
        (self.sh / "watch.pid").write_text(json.dumps({"pid": os.getpid(), "beat": time.time()}))
        self.assertEqual(self.stop()[1], "")

    def test_quiet_when_already_blocked_once_or_no_crew_or_adopted(self):
        self.record()
        self.assertEqual(self.stop(stop_hook_active=True)[1], "")
        self.record(adopted=True)
        self.assertEqual(self.stop()[1], "")
        self.record(state="landed")
        self.assertEqual(self.stop()[1], "")

    def test_a_crewmate_cannot_skip_the_push_ask(self):
        import subprocess as sp
        repo = self.home / "github/environment"
        repo.mkdir(parents=True)
        sp.run(["git", "init", "-q", str(repo)], check=True)
        self.record(session="crew-1")
        cmd = f"KC_OWNER_SAID_PUSH=1 git -C {repo} push"
        def pre(sid):
            data = {"cwd": str(repo), "session_id": sid, "tool_name": "Bash", "tool_input": {"command": cmd}}
            return run(NEW, "pretool", data, self.env)[1]
        self.assertIn('"ask"', pre("crew-1"))
        self.assertEqual(pre("kohens-own-session"), "")
        self.record(session="crew-1", adopted=True)
        self.assertEqual(pre("crew-1"), "")

    def test_never_outside_stellas_home(self):
        self.record()
        data = {"cwd": str(self.home), "last_assistant_message": GOOD}
        self.assertEqual(run(NEW, "stop", data, self.env)[1], "")


if __name__ == "__main__":
    unittest.main()
