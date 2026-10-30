"""`stella restart` keeps her job id and her window; it never leaves two sessions called stella."""

import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakeworld import World  # noqa: E402

STELLA_FLAGS = ["--agent", "stella", "--dangerously-skip-permissions", "--model", "sonnet"]


def link_stella_check(w):
    """`setup.sh` links bin/stella-check into ~/.local/bin; `stella` writes her hooks only once it is there."""
    link = w.home / ".local/bin/stella-check"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.write_text("#!/bin/sh\n")


class StellaRestart(unittest.TestCase):
    """`stella restart` starts an empty conversation (a fork --fresh): a new job id, the same name, flags and window, the old
    job stopped and removed, so there is never a second Stella."""

    def test_restart_starts_an_empty_conversation_keeping_the_name_the_flags_and_the_window(self):
        with World() as w:
            link_stella_check(w)
            job = w.job("stella", state="blocked", running=True, flags=STELLA_FLAGS)
            w.pane("p1", attach=job, tab_label="Stella")
            p = w.run("stella", "restart", env={"PATH": f"{w.bin}:/usr/bin:/bin"})
            # the last step execs `claude attach`, which the fake does not provide: that is the only failure allowed
            self.assertIn("started afresh", p.stdout, p.stdout + p.stderr)
            world = w.load()
            stellas = [j for j, v in world["jobs"].items() if v["name"] == "stella"]
            self.assertEqual(len(stellas), 1)
            self.assertNotEqual(stellas[0], job)  # the id changes; the old record is gone
            self.assertEqual(world["panes"]["p1"]["fg"], f"attach:{stellas[0]}")
            self.assertEqual(sorted(world["jobs"][stellas[0]]["flags"]), sorted(["--dangerously-skip-permissions", "--agent", "stella", "--model", "opus"]))
            calls = w.claude_calls()
            self.assertTrue(calls[0].startswith("--bg -n stella --dangerously-skip-permissions --agent stella"), calls)
            self.assertNotIn("--resume", calls[0])  # an empty conversation, not a continuation
            self.assertIn("Session start (today is", calls[0])
            self.assertEqual(calls[1:3], [f"stop {job}", f"rm {job}"])

    def test_waiting_for_a_wake_is_not_busy(self):
        with World() as w:  # state working, tempo idle, one session cron: Stella between her routines
            link_stella_check(w)
            job = w.job("stella", state="working", running=True, flags=STELLA_FLAGS,
                        in_flight={"tasks": 1, "queued": 0, "kinds": ["session_cron"], "wake": {"at": 1}})
            p = w.run("stella", "restart")
            self.assertIn("started afresh", p.stdout, p.stdout + p.stderr)
            self.assertIn(f"stop {job}", w.claude_calls())

    def test_a_busy_stella_is_not_restarted(self):
        with World() as w:
            link_stella_check(w)
            w.job("stella", state="working", tempo="active", running=True, flags=STELLA_FLAGS)
            p = w.run("stella", "restart")
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("busy", p.stderr + p.stdout)
            self.assertEqual(w.claude_calls(), [])


class StellaSettings(unittest.TestCase):
    """Every run writes her project settings: the watcher hooks, recaps off, the hour cache; the cap only when ready."""

    def linked(self, w):
        link_stella_check(w)

    def test_without_the_stella_check_link_nothing_is_written(self):
        with World() as w:
            w.job("stella", state="blocked", running=True, flags=STELLA_FLAGS)
            p = w.run("stella", "start")
            self.assertIn("setup.sh", p.stderr)
            self.assertFalse((w.home / ".local/share/stella/.claude/settings.json").exists())

    def settings(self, w):
        return json.loads((w.home / ".local/share/stella/.claude/settings.json").read_text())

    def test_start_on_a_running_stella_writes_the_hooks_and_keeps_other_keys(self):
        with World() as w:
            self.linked(w)
            w.job("stella", state="blocked", running=True, flags=STELLA_FLAGS)
            path = w.home / ".local/share/stella/.claude/settings.json"
            path.parent.mkdir(parents=True)
            other = {"hooks": [{"type": "command", "command": "say done"}]}
            path.write_text(json.dumps({"permissions": {"allow": ["Read"]}, "hooks": {"PreToolUse": [], "Stop": [other]}}))
            w.run("stella", "start")
            s = self.settings(w)
            self.assertEqual(s["permissions"], {"allow": ["Read"]})
            self.assertIn("PreToolUse", s["hooks"])
            self.assertEqual(s["hooks"]["Stop"][0], other)  # Kohen's own hook stays, first
            w.run("stella", "start")  # a second run replaces ours, never duplicates them
            s = self.settings(w)
            self.assertEqual(len(s["hooks"]["Stop"]), 2)
            for event in ("SessionStart", "Stop", "StopFailure"):
                hook = [e for e in s["hooks"][event] if "stella-check --watch" in str(e)][0]["hooks"][0]
                self.assertEqual("--fresh" in hook["command"], event == "SessionStart")
                self.assertEqual(hook["rewakeSummary"], "stella-check wake")  # the text her /calm module hides
                self.assertIn("not an error", hook["rewakeMessage"])
                self.assertTrue(hook["asyncRewake"], event)
                self.assertIn("stella-check --watch", hook["command"])
                self.assertGreaterEqual(hook["timeout"], 86400)
            self.assertEqual(s["hooks"]["SessionStart"][-1]["matcher"], "compact")
            self.assertEqual(s["hooks"]["SessionStart"][0]["matcher"], "startup|resume")
            self.assertEqual(s["env"]["CLAUDE_CODE_ENABLE_AWAY_SUMMARY"], "0")
            self.assertEqual(s["promptCacheTtl"], "1h")
            self.assertNotIn("autoCompactWindow", s)

    def test_a_settings_file_that_does_not_parse_is_left_alone(self):
        with World() as w:
            self.linked(w)
            w.job("stella", state="blocked", running=True, flags=STELLA_FLAGS)
            path = w.home / ".local/share/stella/.claude/settings.json"
            path.parent.mkdir(parents=True)
            path.write_text("{ not json")
            p = w.run("stella", "start")
            self.assertIn("does not parse", p.stderr)
            self.assertEqual(path.read_text(), "{ not json")

    def test_a_settings_file_of_the_wrong_shape_is_left_alone(self):
        with World() as w:
            self.linked(w)
            w.job("stella", state="blocked", running=True, flags=STELLA_FLAGS)
            path = w.home / ".local/share/stella/.claude/settings.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"hooks": []}')
            p = w.run("stella", "start")
            self.assertIn("not the shape", p.stderr)
            self.assertEqual(path.read_text(), '{"hooks": []}')

    def test_restart_writes_them_too_and_adds_the_cap_after_a_day_of_pr_lists(self):
        with World() as w:
            self.linked(w)
            w.job("stella", state="blocked", running=True, flags=STELLA_FLAGS)
            store = w.home / ".local/share/stella"
            store.mkdir(parents=True)
            (store / "pr-tasks.json").write_text(json.dumps({"updated": int(time.time()), "since": int(time.time()) - 2 * 86400}))
            w.run("stella", "restart")
            s = self.settings(w)
            self.assertEqual(s["autoCompactWindow"], 200000)
            self.assertTrue(s["hooks"]["Stop"][0]["hooks"][0]["asyncRewake"])


if __name__ == "__main__":
    unittest.main()
