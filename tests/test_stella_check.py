"""stella-check wakes Stella once per new finding, never for what has not changed, and keeps one watcher."""

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin/stella-check"

HELPER = '''#!/usr/bin/env python3
import json, sys, pathlib
here = pathlib.Path(__file__).resolve().parent
cmd = sys.argv[1] if len(sys.argv) > 1 else "steward"
data = json.loads((here / "fake.json").read_text())
if data.get("fail") == cmd:
    sys.exit("boom")
print(json.dumps(data.get(cmd, {})))
'''


class World:
    def __init__(self):
        self.t = tempfile.TemporaryDirectory()
        self.home = Path(self.t.name)
        self.store = self.home / ".local/share/stella"
        self.store.mkdir(parents=True)

    def job(self, jid, name, state="blocked", age=0, **fields):
        d = self.home / ".claude/jobs" / jid
        d.mkdir(parents=True, exist_ok=True)
        p = d / "state.json"
        p.write_text(json.dumps({"name": name, "state": state, **fields}))
        t = time.time() - age
        os.utime(p, (t, t))

    def helper(self, **outputs):
        h = self.store / "approved-prs"
        h.mkdir(exist_ok=True)
        (h / "approved-prs.py").write_text(HELPER)
        (h / "fake.json").write_text(json.dumps(outputs))

    def env(self):
        return {"HOME": str(self.home), "PATH": "/usr/bin:/bin", "STELLA_CHECK_POLL": "1"}

    def run(self, *args, timeout=30):
        return subprocess.run(["python3", str(BIN), *args], env=self.env(), capture_output=True, text=True, timeout=timeout)

    def once(self):
        p = self.run("--once")
        assert p.returncode == 0, p.stderr
        return json.loads(p.stdout)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.t.cleanup()


class Findings(unittest.TestCase):
    def test_a_session_blocked_for_15_minutes_wakes_once(self):
        with World() as w:
            w.job("a1", "phase-10", age=10 * 60, needs="which branch?")
            self.assertEqual(w.once(), [])  # 10 minutes: not yet
            w.job("a1", "phase-10", age=16 * 60, needs="which branch?")
            new = w.once()
            self.assertEqual([(f["kind"], f["session"]) for f in new], [("blocked", "phase-10")])
            self.assertEqual(w.once(), [])  # still blocked: not news again

    def test_stella_and_old_records_are_ignored(self):
        with World() as w:
            w.job("s1", "stella", age=20 * 60)
            w.job("o1", "ancient", age=5 * 3600)
            self.assertEqual(w.once(), [])

    def test_an_api_error_wakes_after_5_minutes(self):
        with World() as w:
            w.job("e1", "tracker", state="done", age=2 * 60, detail="API Error: 500")
            self.assertEqual(w.once(), [])
            w.job("e1", "tracker", state="done", age=6 * 60, detail="API Error: 500")
            self.assertEqual([f["kind"] for f in w.once()], ["api_error"])

    def test_a_failed_session_is_an_api_error_after_5_minutes(self):
        with World() as w:
            w.job("f1", "tracker", state="failed", age=6 * 60, needs="Retry later")
            self.assertEqual([f["kind"] for f in w.once()], ["api_error"])

    def test_every_pr_bucket_wakes_and_pr_tasks_are_written(self):
        with World() as w:
            w.helper(steward={"act": [{"pr": "o/r#1", "signature": "s1", "reasons": ["conflict"], "owner": {"name": "x"}}],
                              "orphans": [{"pr": "o/r#2", "signature": "s2", "reasons": ["conflict"]}],
                              "unacknowledged": [{"pr": "o/r#3", "told": "y"}], "stuck": [{"pr": "o/r#4", "told": "z", "times": 3}],
                              "held": [{"pr": "o/r#5", "why": "after #4"}], "waiting_review": [{"pr": "o/r#6"}],
                              "wrong_mode_sessions": [{"id": "j9", "name": "rev", "mode": "default"}]},
                     merged={"merged": [{"id": "j8", "session": "fix", "signature": "m1"}]},
                     reminders={"due": [{"key": "o/r#7", "text": "tell Ana"}]})
            kinds = sorted(f["kind"] for f in w.once())
            self.assertEqual(kinds, ["act", "held", "merged", "orphan", "reminders", "stuck", "unacknowledged", "wrong_mode"])
            tasks = json.loads((w.store / "pr-tasks.json").read_text())
            self.assertEqual(tasks["waiting_review"], [{"pr": "o/r#6"}])
            self.assertEqual(w.once(), [])  # nothing changed

    def test_an_item_that_goes_and_comes_back_is_news_again(self):
        with World() as w:
            item = {"pr": "o/r#1", "signature": "s1", "reasons": ["approved and green: queue it"]}
            w.helper(steward={"act": [item]})
            self.assertEqual(len(w.once()), 1)
            w.helper(steward={"act": []})  # Stella marked it; the helper rests it
            self.assertEqual(w.once(), [])
            w.helper(steward={"act": [item]})  # listed again later
            self.assertEqual(len(w.once()), 1)

    def test_a_failing_helper_wakes_once(self):
        with World() as w:
            w.helper(fail="steward")
            self.assertEqual([f["kind"] for f in w.once()], ["helper_error"])
            self.assertEqual(w.once(), [])

    def test_events_log_gets_a_line_per_wake(self):
        with World() as w:
            w.job("a1", "phase-10", age=20 * 60, needs="?")
            w.once()
            w.once()
            lines = (w.store / "events.log").read_text().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertIn("blocked phase-10", lines[0])

    def test_merged_items_keep_the_wake_kind(self):
        with World() as w:
            w.helper(merged={"merged": [{"id": "j8", "session": "fix", "signature": "m1", "kind": "partial"}]})
            new = w.once()
            self.assertEqual([(f["kind"], f["helper_kind"]) for f in new], [("merged", "partial")])

    def test_a_helper_failure_and_recovery_do_not_wake_the_backlog_again(self):
        with World() as w:
            steward = {"held": [{"pr": "o/r#5", "why": "w"}], "stuck": [{"pr": "o/r#4", "told": "z", "times": 3}]}
            w.helper(steward=steward)
            self.assertEqual(len(w.once()), 2)
            w.helper(steward=steward, fail="steward")
            self.assertEqual([f["kind"] for f in w.once()], ["helper_error"])
            w.helper(steward=steward)
            self.assertEqual(w.once(), [])

    def test_an_error_that_lasts_an_hour_wakes_again_as_persisting(self):
        with World() as w:
            w.helper(fail="steward")
            self.assertEqual(len(w.once()), 1)
            state = json.loads((w.store / "check-state.json").read_text())
            state["errors"]["steward"]["first"] -= 2 * 3600
            (w.store / "check-state.json").write_text(json.dumps(state))
            new = w.once()
            self.assertEqual([(f["kind"], f.get("persisting")) for f in new], [("helper_error", True)])

    def test_a_blocked_session_that_mentions_a_rate_limit_is_still_blocked(self):
        with World() as w:
            w.job("b1", "phase-10", age=20 * 60, needs="awaiting your call on the rate limit")
            self.assertEqual([f["kind"] for f in w.once()], ["blocked"])

    def test_a_dry_run_saves_nothing(self):
        with World() as w:
            w.job("a1", "phase-10", age=20 * 60, needs="?")
            w.helper(steward={"waiting_review": [{"pr": "o/r#6"}]})
            p = w.run()
            self.assertEqual([f["kind"] for f in json.loads(p.stdout)], ["blocked"])
            self.assertFalse((w.store / "check-state.json").exists())
            self.assertFalse((w.store / "pr-tasks.json").exists())
            self.assertEqual([f["kind"] for f in w.once()], ["blocked"])

    def test_compact_note_is_a_session_start_answer(self):
        with World() as w:
            out = json.loads(w.run("--compact-note").stdout)
            self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
            self.assertIn("start-of-session", out["hookSpecificOutput"]["additionalContext"])


class Watch(unittest.TestCase):
    def test_watch_exits_2_with_the_finding(self):
        with World() as w:
            w.job("a1", "phase-10", age=20 * 60, needs="?")
            p = w.run("--watch")
            self.assertEqual(p.returncode, 2, p.stderr)
            self.assertIn("blocked", p.stdout)

    def test_a_crash_wakes_once_instead_of_killing_the_watcher(self):
        with World() as w:
            w.helper(steward={})
            (w.store / "pr-tasks.json").mkdir()  # writing the PR lists now fails
            p = w.run("--watch")
            self.assertEqual(p.returncode, 2, p.stderr)
            self.assertIn('"kind": "crash"', p.stdout)

    def test_a_wake_lost_to_a_restart_is_delivered_again_only_by_a_fresh_watcher(self):
        with World() as w:
            w.job("a1", "phase-10", age=20 * 60, needs="?")
            self.assertEqual(w.run("--watch").returncode, 2)
            state = json.loads((w.store / "check-state.json").read_text())
            (w.store / "check-state.json").write_text(json.dumps(state))
            # a Stop-hook watcher in the same process never doubles a wake that may still be queued
            stop = subprocess.Popen(["python3", str(BIN), "--watch"], env=w.env(), stdout=subprocess.PIPE, text=True)
            try:
                time.sleep(2.5)
                self.assertIsNone(stop.poll())
            finally:
                stop.kill()
                stop.wait()
                stop.stdout.close()
            p = w.run("--watch", "--fresh")  # a new session process: the wake was lost, deliver it again
            self.assertEqual(p.returncode, 2)
            self.assertIn("blocked", p.stdout)
            w.run("--ack")
            self.assertNotIn("pending", json.loads((w.store / "check-state.json").read_text()))

    def test_a_fresh_watcher_takes_over_from_one_left_by_the_previous_process(self):
        with World() as w:
            old = subprocess.Popen(["python3", str(BIN), "--watch"], env=w.env(), stdout=subprocess.PIPE, text=True)
            try:
                time.sleep(1.5)
                self.assertIn(f"watcher pid {old.pid}", w.run("--status").stdout)
                new = subprocess.Popen(["python3", str(BIN), "--watch", "--fresh"], env=w.env(),
                                       stdout=subprocess.PIPE, text=True)
                try:
                    old.wait(timeout=10)  # ended by the takeover
                    time.sleep(1.5)
                    self.assertIn(f"watcher pid {new.pid}", w.run("--status").stdout)
                finally:
                    new.kill()
                    new.wait()
                    new.stdout.close()
            finally:
                if old.poll() is None:
                    old.kill()
                old.wait()
                old.stdout.close()

    def test_a_helper_that_fails_every_other_run_wakes_her_once(self):
        with World() as w:
            for fail in ("steward", None, "steward", None, "steward"):
                w.helper(**({"fail": fail} if fail else {"steward": {}}))
                w.once()
            self.assertEqual((w.store / "events.log").read_text().count("helper error"), 1)

    def test_a_stale_pid_in_the_lock_file_is_never_signalled(self):
        with World() as w:
            sleeper = subprocess.Popen(["sleep", "30"])
            try:
                (w.store / "watch.lock").write_text(f"{sleeper.pid} {int(time.time())} {int(time.time())}\n")
                p = subprocess.Popen(["python3", str(BIN), "--watch", "--fresh"], env=w.env(), stdout=subprocess.PIPE, text=True)
                try:
                    time.sleep(2)
                    self.assertIsNone(sleeper.poll(), "take_over killed a process that is not a watcher")
                    self.assertIsNone(p.poll())
                finally:
                    p.kill()
                    p.wait()
                    p.stdout.close()
            finally:
                sleeper.kill()
                sleeper.wait()

    def test_an_ack_during_a_check_is_not_undone(self):
        with World() as w:
            w.helper(steward={})
            (w.store / "approved-prs/approved-prs.py").write_text(HELPER.replace(
                "cmd = sys.argv", "import time; time.sleep(3 if len(sys.argv) < 2 or sys.argv[1] == 'steward' else 0)\ncmd = sys.argv"))
            (w.store / "check-state.json").write_text(json.dumps({"pending": {"at": 1, "findings": []}}))
            check = subprocess.Popen(["python3", str(BIN), "--once"], env=w.env(), stdout=subprocess.PIPE, text=True)
            try:
                time.sleep(1)
                w.run("--ack")
                check.wait(timeout=30)
            finally:
                check.stdout.close()
            self.assertNotIn("pending", json.loads((w.store / "check-state.json").read_text()))

    def test_ending_the_watcher_ends_the_helper_it_is_waiting_for(self):
        with World() as w:
            marker = w.home / "helper.pid"
            (w.store / "approved-prs").mkdir()
            (w.store / "approved-prs/approved-prs.py").write_text(
                f"import os, time\nopen({str(marker)!r}, 'w').write(str(os.getpid()))\ntime.sleep(60)\n")
            p = subprocess.Popen(["python3", str(BIN), "--watch"], env=w.env(), stdout=subprocess.PIPE, text=True)
            try:
                for _ in range(50):
                    if marker.exists() and marker.read_text():
                        break
                    time.sleep(0.2)
                helper_pid = int(marker.read_text())
                p.terminate()
                p.wait(timeout=10)
                time.sleep(0.5)
                with self.assertRaises(ProcessLookupError):
                    os.kill(helper_pid, 0)
            finally:
                if p.poll() is None:
                    p.kill()
                    p.wait()
                p.stdout.close()

    def test_a_second_watcher_exits_at_once(self):
        with World() as w:
            env = {"HOME": str(w.home), "PATH": "/usr/bin:/bin", "STELLA_CHECK_POLL": "1"}
            first = subprocess.Popen(["python3", str(BIN), "--watch"], env=env, stdout=subprocess.PIPE, text=True)
            try:
                time.sleep(1.5)
                started = time.time()
                p = w.run("--watch")
                self.assertEqual(p.returncode, 0)
                self.assertLess(time.time() - started, 5)
                self.assertIn("watcher pid", w.run("--status").stdout)
            finally:
                first.kill()
                first.wait()
                first.stdout.close()
            self.assertIn("NOT running", w.run("--status").stdout)


if __name__ == "__main__":
    unittest.main()
