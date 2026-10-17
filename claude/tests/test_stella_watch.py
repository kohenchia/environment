"""Tests for stella-watch, with fixture records, job files and transcripts in a temporary HOME.

    python3 -m unittest discover -s claude/tests
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WATCH = REPO / "claude/bin/stella-watch"
RULE = "━" * 40


def block(kind: str) -> str:
    return {"NEXT": f"x\n\n{RULE}\n\U0001f7e7 **NEXT FOR YOU** (1)\n1. Decide.",
            "DONE": f"x\n\n{RULE}\n\U0001f7e9 **ALL DONE** — nothing left for you.",
            "WORKING": f"x\n\n{RULE}\n\U0001f7e6 **WORKING** — tests running"}[kind]


class Watch(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.home = Path(self.t.name)
        self.sh = self.home / ".local/share/stella"
        (self.sh / "crew").mkdir(parents=True)
        (self.home / ".claude/projects/p").mkdir(parents=True)
        (self.home / ".claude/jobs").mkdir(parents=True)

    def tearDown(self):
        self.t.cleanup()

    def crew(self, name, sid, **rec):
        d = self.sh / "crew" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "record.json").write_text(json.dumps({"name": name, "id": sid, "session": sid + "-s",
                                                   "state": "working", **rec}))

    def say(self, sid, kind, extra=()):
        lines = [json.dumps({"type": "user", "message": {"content": "/kc-dev do it"}})]
        lines += [json.dumps(e) for e in extra]
        lines.append(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": block(kind)}]}}))
        (self.home / f".claude/projects/p/{sid}-s.jsonl").write_text("\n".join(lines) + "\n")

    def job(self, sid, state, needs=None):
        (self.home / f".claude/jobs/{sid}").mkdir(exist_ok=True)
        (self.home / f".claude/jobs/{sid}/state.json").write_text(json.dumps({"state": state, "needs": needs}))

    def once(self):
        p = subprocess.run(["python3", str(WATCH), "--once"], capture_output=True, text=True, timeout=30,
                           env={"HOME": str(self.home), "PATH": "/usr/bin:/bin"})
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def test_working_is_quiet_done_and_next_wake(self):
        self.crew("fix-flake", "a1")
        self.say("a1", "WORKING")
        self.assertEqual(self.once().strip(), "nothing to report")
        self.say("a1", "DONE")
        self.assertIn("fix-flake: ALL DONE", self.once())
        self.assertEqual(self.once().strip(), "nothing to report")  # reported once
        self.say("a1", "NEXT")
        self.assertIn("fix-flake: NEXT FOR YOU", self.once())

    def test_blocked_with_needs(self):
        self.crew("merge-it", "b1")
        self.say("b1", "WORKING")
        self.job("b1", "blocked", "an approving review")
        self.assertIn("merge-it: blocked, needs: an approving review", self.once())

    def test_team_completions_are_held_until_all_done(self):
        for i, sid in enumerate(("t1", "t2")):
            self.crew(f"migrate-{i}", sid, team="migrate")
            self.say(sid, "WORKING")
        self.once()
        self.say("t1", "DONE")
        self.assertEqual(self.once().strip(), "nothing to report")
        self.say("t2", "DONE")
        self.assertIn("team migrate complete", self.once())

    def test_team_member_needing_a_decision_wakes_at_once(self):
        for i, sid in enumerate(("u1", "u2")):
            self.crew(f"m-{i}", sid, team="t")
            self.say(sid, "WORKING")
        self.once()
        self.say("u1", "NEXT")
        self.assertIn("m-0: NEXT FOR YOU", self.once())

    def test_throttle_writes_pause(self):
        self.crew("review", "c1")
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        err = {"type": "system", "subtype": "api_error", "timestamp": now,
               "error": {"message": "429 account rate limit exceeded for quota 'x': 160 requests in 4m0s"}}
        self.say("c1", "WORKING", extra=[err])
        self.once()
        until = json.loads((self.sh / "throttle-until").read_text())["until"]
        self.assertGreater(until, time.time() + 200)

    def test_old_throttle_does_not_pause(self):
        self.crew("review", "c2")
        err = {"type": "system", "subtype": "api_error", "timestamp": "2026-01-01T10:00:00Z",
               "error": {"message": "429 account rate limit exceeded for quota 'x': 160 requests in 4m0s"}}
        self.say("c2", "WORKING", extra=[err])
        self.once()
        self.assertFalse((self.sh / "throttle-until").exists())

    def test_blocked_detail_when_job_has_no_needs(self):
        self.crew("merge-it", "b2")
        self.say("b2", "WORKING")
        (self.home / ".claude/jobs/b2").mkdir()
        (self.home / ".claude/jobs/b2/state.json").write_text(json.dumps({"state": "blocked", "detail": "awaiting approval"}))
        self.assertIn("merge-it: blocked, needs: awaiting approval", self.once())

    def test_relaunch_under_the_same_name_reports_again(self):
        self.crew("pr-12", "h1")
        self.say("h1", "DONE")
        self.assertIn("pr-12: ALL DONE", self.once())
        self.crew("pr-12", "h2")
        self.say("h2", "DONE")
        self.assertIn("pr-12: ALL DONE", self.once())

    def test_held_team_completion_rides_along_with_another_wake(self):
        for i, sid in enumerate(("k1", "k2")):
            self.crew(f"mig-{i}", sid, team="mig")
            self.say(sid, "WORKING")
        self.crew("other", "k3")
        self.say("k3", "WORKING")
        self.once()
        self.say("k1", "DONE")
        self.assertEqual(self.once().strip(), "nothing to report")
        self.say("k3", "NEXT")
        out = self.once()
        self.assertIn("other: NEXT FOR YOU", out)
        self.assertIn("mig-0: ALL DONE", out)

    def test_failing_watch_reports_once_and_does_not_crash(self):
        self.crew("train", "w1", watches=[{"name": "job", "command": ["/nonexistent/px", "bolt"]}])
        self.say("w1", "WORKING")
        self.assertIn("watch failed", self.once())
        self.assertEqual(self.once().strip(), "nothing to report")

    def test_undelivered_steer(self):
        self.crew("fix", "d1", steers=[{"at": time.time() - 700, "text": "also cover the timeout case"}])
        self.say("d1", "WORKING")
        self.assertIn("steer not delivered", self.once())

    def test_delivered_steer_is_quiet(self):
        self.crew("fix", "e1", steers=[{"at": time.time() - 700, "text": "also cover the timeout case"}])
        self.say("e1", "WORKING", extra=[{"type": "user", "message": {"content": "also cover the timeout case"}}])
        self.assertEqual(self.once().strip(), "nothing to report")

    def test_steer_beyond_the_tail_window_is_still_delivered(self):
        self.crew("fix", "f1", steers=[{"at": time.time() - 700, "text": "Kohen's order: queue what's approved"}])
        filler = [{"type": "assistant", "message": {"content": "x" * 5000}}] * 120  # ~600 KB after the steer
        steer = {"type": "user", "message": {"content": "Another Claude session sent a message:\nKohen's order: queue what's approved"}}
        self.say("f1", "WORKING", extra=[steer] + filler)
        self.assertEqual(self.once().strip(), "nothing to report")

    def test_file_watch_from_extension(self):
        note = self.home / "plan.md"
        note.write_text("v1")
        (self.home / ".claude/kc-extensions").mkdir(parents=True)
        (self.home / ".claude/kc-extensions/stella.json").write_text(
            json.dumps({"watches": [{"name": "plan-comments", "file": str(note)}]}))
        self.assertEqual(self.once().strip(), "nothing to report")
        time.sleep(0.01)
        note.write_text("v2 ==**KC:** change this==")
        import os
        os.utime(note, (time.time() + 5, time.time() + 5))
        self.assertIn("plan-comments", self.once())

    def test_pr_merged_and_failing_check(self):
        bindir = self.home / "bin"
        bindir.mkdir()
        state = self.home / "pr.json"
        (bindir / "gh").write_text(f"#!/bin/sh\ncat {state}\n")
        (bindir / "gh").chmod(0o755)
        self.crew("fix", "f1", pr="https://example/pr/1")
        self.say("f1", "WORKING")
        pr = {"state": "OPEN", "reviewDecision": "", "reviews": [], "statusCheckRollup": [{"name": "lint", "conclusion": "SUCCESS"}]}
        env = {"HOME": str(self.home), "PATH": f"{bindir}:/usr/bin:/bin"}
        run = lambda: subprocess.run(["python3", str(WATCH), "--once"], capture_output=True, text=True, env=env).stdout
        state.write_text(json.dumps(pr))
        self.assertEqual(run().strip(), "nothing to report")
        pr["statusCheckRollup"][0]["conclusion"] = "FAILURE"
        state.write_text(json.dumps(pr))
        self.assertIn("PR check failing: lint", run())
        pr["state"] = "MERGED"
        state.write_text(json.dumps(pr))
        self.assertIn("PR merged", run())

    def test_track_record_wakes_with_the_same_words_as_a_crewmate_pr(self):
        bindir = self.home / "bin"
        bindir.mkdir()
        state = self.home / "pr.json"
        (bindir / "gh").write_text(f"#!/bin/sh\ncat {state}\n")
        (bindir / "gh").chmod(0o755)
        url = "https://h/acme/widgets/pull/2428"
        d = self.sh / "crew/track-2428"
        d.mkdir()
        (d / "record.json").write_text(json.dumps({
            "name": "track-2428", "mode": "track", "state": "watching", "pr": url,
            "watches": [{"name": "widgets#2428", "command": ["gh", "pr", "view", url]}]}))
        env = {"HOME": str(self.home), "PATH": f"{bindir}:/usr/bin:/bin"}
        run = lambda: subprocess.run(["python3", str(WATCH), "--once"], capture_output=True, text=True, env=env).stdout
        pr = {"state": "OPEN", "reviewDecision": "", "reviews": [],
              "statusCheckRollup": [{"name": "lint", "conclusion": "SUCCESS"}]}
        state.write_text(json.dumps(pr))
        self.assertEqual(run().strip(), "nothing to report")
        pr["reviews"] = [{}]
        state.write_text(json.dumps(pr))
        self.assertEqual(run().strip(), f"track-2428: new review on {url}")  # once, not also as a watch change
        pr["reviewDecision"], pr["statusCheckRollup"][0]["conclusion"] = "CHANGES_REQUESTED", "FAILURE"
        state.write_text(json.dumps(pr))
        out = run()
        self.assertIn(f"track-2428: changes requested on {url}", out)
        self.assertIn(f"track-2428: PR check failing: lint {url}", out)
        pr["state"] = "MERGED"
        state.write_text(json.dumps(pr))
        self.assertIn(f"track-2428: PR merged {url}", run())
        (d / "record.json").write_text(json.dumps({"name": "track-2428", "mode": "track", "state": "landed",
                                                    "pr": url}))
        pr["state"] = "OPEN"
        pr["reviews"] = [{}, {}]
        state.write_text(json.dumps(pr))
        self.assertEqual(run().strip(), "nothing to report")

    def test_record_command_watch(self):
        out = self.home / "job.txt"
        out.write_text("RUNNING")
        self.crew("train", "g1", watches=[{"name": "job 7", "command": ["cat", str(out)]}])
        self.say("g1", "WORKING")
        self.assertEqual(self.once().strip(), "nothing to report")
        out.write_text("FINISHED")
        self.assertIn("train: job 7: changed", self.once())

    def test_writes_wake_and_clears_its_pidfile_on_exit(self):
        self.once()
        self.assertFalse((self.sh / "watch.pid").exists())
        self.assertIn("events", json.loads((self.sh / "wake.json").read_text()))


if __name__ == "__main__":
    unittest.main()
