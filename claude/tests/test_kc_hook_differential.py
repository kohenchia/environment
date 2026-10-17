"""Differential test for kc-hook: the new script must behave byte-for-byte like the old one in every
session except Stella's own (cwd ~/.local/share/stella), because kc-hook runs in every Claude session on
the machine the moment it is merged.

The old script is `origin/main:claude/bin/kc-hook` of this repo, or $KC_HOOK_OLD. Run:

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

RULE = "━" * 40
GOOD = f"Done.\n\n{RULE}\n\U0001f7e9 **ALL DONE** — nothing left for you."
NEXT = f"Hi.\n\n{RULE}\n\U0001f7e7 **NEXT FOR YOU** (2)\n1. Decide A.\n2. Decide B."
BAD = "Here is the answer, with no status block."


def old_script(tmp: Path) -> Path:
    if os.environ.get("KC_HOOK_OLD"):
        return Path(os.environ["KC_HOOK_OLD"])
    src = subprocess.run(["git", "-C", str(REPO), "show", "origin/main:claude/bin/kc-hook"],
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


if __name__ == "__main__":
    unittest.main()
