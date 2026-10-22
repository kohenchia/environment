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

    def run(self, *args, timeout=30):
        env = {"HOME": str(self.home), "PATH": "/usr/bin:/bin", "STELLA_CHECK_POLL": "1"}
        return subprocess.run(["python3", str(BIN), *args], env=env, capture_output=True, text=True, timeout=timeout)

    def once(self):
        p = self.run()
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
            w.job("e1", "tracker", state="working", age=2 * 60, detail="API Error: 500")
            self.assertEqual(w.once(), [])
            w.job("e1", "tracker", state="working", age=6 * 60, detail="API Error: 500")
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


class Watch(unittest.TestCase):
    def test_watch_exits_2_with_the_finding(self):
        with World() as w:
            w.job("a1", "phase-10", age=20 * 60, needs="?")
            p = w.run("--watch")
            self.assertEqual(p.returncode, 2, p.stderr)
            self.assertIn("blocked", p.stdout)

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
