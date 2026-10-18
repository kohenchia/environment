"""The pre-push leak gate and the hook that guards it. Run: python3 -m unittest discover tests"""

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "claude/bin/kc-hook"
PRE_PUSH = REPO / "githooks/pre-push"


def git(cwd, *a, env=None):
    return subprocess.run(["git", "-C", str(cwd), *a], capture_output=True, text=True, env=env)


class PrePush(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        (self.home / ".local/bin").mkdir(parents=True)
        self.remote = self.tmp / "remote.git"
        git(self.tmp, "init", "--bare", str(self.remote))
        self.work = self.tmp / "work"
        git(self.tmp, "clone", str(self.remote), str(self.work))
        git(self.work, "config", "user.email", "t@example.com")
        git(self.work, "config", "user.name", "t")
        self.env = {**os.environ, "HOME": str(self.home)}

    def check(self, body):
        p = self.home / ".local/bin/leakcheck"
        p.write_text(f"#!/bin/sh\n{body}\n")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)

    def commit_and_push(self):
        (self.work / "f.txt").write_text("hello\n")
        git(self.work, "add", "f.txt")
        git(self.work, "commit", "-m", "m", env=self.env)
        return git(self.work, "-c", f"core.hooksPath={REPO / 'githooks'}", "push", "origin", "HEAD:main", env=self.env)

    def test_clean_push_goes_through(self):
        self.check("exit 0")
        self.assertEqual(self.commit_and_push().returncode, 0)

    def test_hit_is_refused(self):
        self.check("echo 'f.txt:1 word:secret'; exit 1")
        p = self.commit_and_push()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("word:secret", p.stdout + p.stderr)

    def test_missing_check_fails_closed(self):
        p = self.commit_and_push()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("no leak check", p.stderr)

    def test_range_names_what_the_push_adds(self):
        self.check('echo "$@" > "$HOME/args"; exit 0')
        self.commit_and_push()
        args = (self.home / "args").read_text()
        self.assertIn("--range", args)
        self.assertIn("--not --remotes=origin", args)


class Hook(unittest.TestCase):
    def run_hook(self, cmd, cwd):
        p = subprocess.run(["python3", str(HOOK), "pretool"], input=json.dumps(
            {"tool_input": {"command": cmd}, "cwd": cwd}), capture_output=True, text=True)
        return json.loads(p.stdout) if p.stdout.strip() else None

    def test_no_verify_in_the_public_repo_is_denied(self):
        home = Path.home()
        out = self.run_hook("git push --no-verify", str(home / "github/environment-wt/x"))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_hooks_path_change_is_denied(self):
        home = Path.home()
        out = self.run_hook("git -C ~/github/environment config core.hooksPath /dev/null", "/tmp")
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_plain_push_and_other_repos_pass(self):
        home = Path.home()
        self.assertIsNone(self.run_hook("git push origin HEAD", str(home / "github/environment")))
        self.assertIsNone(self.run_hook("git push --no-verify", str(home / "github/dashboard")))


if __name__ == "__main__":
    unittest.main()
