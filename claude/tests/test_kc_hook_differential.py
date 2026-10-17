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
import sys
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
        for cmd in ("ls -la", "git status"):  # pushes are covered by PushGate: they now differ on purpose
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

    def test_never_outside_stellas_home(self):
        self.record()
        data = {"cwd": str(self.home), "last_assistant_message": GOOD}
        self.assertEqual(run(NEW, "stop", data, self.env)[1], "")


class PushGate(unittest.TestCase):
    """Publishing to the public repo is gated by what it publishes; other pushes by the session's granted activities."""

    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.home = Path(self.t.name)
        self.env = {"HOME": str(self.home), "PATH": os.environ["PATH"]}
        (self.home / ".local/share/stella/crew/mate").mkdir(parents=True)
        (self.home / ".claude/kc-extensions").mkdir(parents=True)
        self.repo = self.home / "github/environment"
        self.repo.mkdir(parents=True)
        self.g("init", "-q", "-b", "main")
        self.g("config", "user.email", "t@example.com")
        self.g("config", "user.name", "t")
        self.commit("a.txt", "fine\n", "first")
        self.g("update-ref", "refs/remotes/origin/main", "HEAD")
        # a stand-in push check with the real contract: `<cmd> --repo DIR --range SPEC`, exit 1 and hit lines
        self.check = self.home / "check"
        self.check.write_text(
            "import subprocess, sys\n"
            "repo, spec = sys.argv[sys.argv.index('--repo') + 1], sys.argv[sys.argv.index('--range') + 1]\n"
            "log = subprocess.run(['git', '-C', repo, 'log', '-p', '--format=%B', *spec.split()],\n"
            "                     capture_output=True, text=True).stdout\n"
            "bad = [f'diff:{n}: zebrafish' for n, l in enumerate(log.splitlines(), 1) if 'zebrafish' in l]\n"
            "print('\\n'.join(bad)); sys.exit(1 if bad else 0)\n")
        self.configure(True)

    def tearDown(self):
        self.t.cleanup()

    def g(self, *a):
        subprocess.run(["git", "-C", str(self.repo), *a], check=True, capture_output=True)

    def commit(self, name, text, msg):
        (self.repo / name).write_text(text)
        self.g("add", name)
        self.g("commit", "-q", "-m", msg)

    def configure(self, on):
        ext = self.home / ".claude/kc-extensions/stella.json"
        ext.write_text(json.dumps({"push_check": ["python3", str(self.check)]} if on else {}))

    def grant(self, *activities):
        (self.home / ".local/share/stella/crew/mate/record.json").write_text(
            json.dumps({"name": "mate", "session": "mate-1", "allow": list(activities)}))

    def pre(self, cmd="git push", sid="mate-1", cwd=None):
        data = {"cwd": str(cwd or self.repo), "session_id": sid, "tool_name": "Bash", "tool_input": {"command": cmd}}
        out = run(NEW, "pretool", data, self.env)[1]
        return json.loads(out)["hookSpecificOutput"] if out.strip() else None

    def test_a_clean_push_is_allowed_silently(self):
        self.commit("b.txt", "also fine\n", "second")
        self.assertEqual(self.pre()["permissionDecision"], "allow")

    def test_a_leaking_push_is_denied_with_the_hit_whoever_pushes(self):
        self.commit("b.txt", "see zebrafish\n", "second")
        self.grant("push")
        for sid in ("mate-1", "kohens-own-session"):
            out = self.pre(sid=sid)
            self.assertEqual(out["permissionDecision"], "deny")
            self.assertIn("zebrafish", out["permissionDecisionReason"])
            self.assertIn("push again", out["permissionDecisionReason"])

    def test_a_leak_in_a_commit_message_is_denied(self):
        self.commit("b.txt", "fine\n", "about zebrafish")
        self.assertEqual(self.pre()["permissionDecision"], "deny")

    def test_only_what_the_push_adds_is_checked(self):
        self.commit("b.txt", "zebrafish\n", "second")
        self.g("update-ref", "refs/remotes/origin/main", "HEAD")  # already published
        self.assertEqual(self.pre()["permissionDecision"], "allow")

    def test_no_configured_check_falls_back_to_ask_unless_push_is_granted(self):
        self.configure(False)
        self.assertEqual(self.pre()["permissionDecision"], "ask")
        self.grant("security-boundary")
        self.assertEqual(self.pre()["permissionDecision"], "ask")
        self.grant("push")
        self.assertIsNone(self.pre())

    def test_a_check_that_cannot_run_asks(self):
        self.check.write_text("import sys; sys.exit(2)\n")
        self.assertEqual(self.pre()["permissionDecision"], "ask")

    def test_the_range_follows_the_refspec_and_remote(self):
        sys.path.insert(0, str(NEW.parent))
        from importlib.machinery import SourceFileLoader
        mod = SourceFileLoader("kc_hook", str(NEW)).load_module()
        self.assertEqual(mod.push_spec("git push", self.repo), "HEAD --not --remotes=origin")
        self.assertEqual(mod.push_spec("git push -f origin main", self.repo), "main --not --remotes=origin")
        self.assertEqual(mod.push_spec("git push origin +topic:other", self.repo), "topic --not --remotes=origin")
        self.assertEqual(mod.push_spec("git push upstream --all", self.repo), "--branches --not --remotes=upstream")
        self.assertEqual(mod.push_spec("cd x && git push -u origin HEAD", self.repo), "HEAD --not --remotes=origin")

    def test_a_push_elsewhere_is_allowed_only_for_a_session_granted_push(self):
        other = self.home / "github/other"
        other.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(other)], check=True)
        self.assertIsNone(self.pre(cwd=other))
        self.grant("push")
        self.assertEqual(self.pre(cwd=other)["permissionDecision"], "allow")
        self.assertIsNone(self.pre("git push && rm -rf x", cwd=other))  # a chained command is never auto-allowed
        self.assertIsNone(self.pre(sid="kohens-own-session", cwd=other))

    def test_the_old_bypass_variable_does_nothing(self):
        self.commit("b.txt", "zebrafish\n", "second")
        self.assertEqual(self.pre("KC_OWNER_SAID_PUSH=1 git push")["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()
