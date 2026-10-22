"""`stella restart` keeps her job id and her window; it never leaves two sessions called stella."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakeworld import World  # noqa: E402

STELLA_FLAGS = ["--agent", "stella", "--dangerously-skip-permissions", "--model", "sonnet"]


class StellaRestart(unittest.TestCase):
    def test_restart_keeps_the_job_the_flags_and_the_window(self):
        with World() as w:
            job = w.job("stella", state="blocked", running=True, flags=STELLA_FLAGS)
            w.pane("p1", attach=job, tab_label="Stella")
            before = w.snapshot()
            p = w.run("stella", "restart", env={"PATH": f"{w.bin}:/usr/bin:/bin"})
            # the last step execs `claude attach`, which the fake does not provide: that is the only failure allowed
            self.assertIn("restarted in place", p.stdout, p.stdout + p.stderr)
            self.assertEqual(before, w.snapshot())
            self.assertEqual(w.load()["panes"]["p1"]["fg"], f"attach:{job}")
            self.assertEqual(sum(1 for j in w.load()["jobs"].values() if j["name"] == "stella"), 1)
            calls = w.claude_calls()
            self.assertEqual(calls[0], f"stop {job}")
            self.assertTrue(calls[1].startswith(f"--bg --resume {job}-0000-4000-8000-000000000000 -- Session start"), calls)

    def test_waiting_for_a_wake_is_not_busy(self):
        with World() as w:  # state working, tempo idle, one session cron: Stella between her routines
            job = w.job("stella", state="working", running=True, flags=STELLA_FLAGS,
                        in_flight={"tasks": 1, "queued": 0, "kinds": ["session_cron"], "wake": {"at": 1}})
            p = w.run("stella", "restart")
            self.assertIn("restarted in place", p.stdout, p.stdout + p.stderr)
            self.assertEqual(w.claude_calls()[0], f"stop {job}")

    def test_a_daemon_fork_without_a_note_is_followed_not_duplicated(self):
        with World() as w:
            job = w.job("stella", state="blocked", running=True, flags=STELLA_FLAGS)
            w.pane("p1", attach=job)
            w.opt("always_fork", True)  # the daemon forks even a bare resume
            w.opt("no_note", True)  # and does not say so
            p = w.run("stella", "restart")
            self.assertIn("a fork", p.stdout, p.stdout + p.stderr)
            new = [j for j, v in w.load()["jobs"].items() if v["name"] == "stella" and j != job]
            self.assertEqual(len(new), 1)
            self.assertEqual(w.load()["panes"]["p1"]["fg"], f"attach:{new[0]}")

    def test_a_copy_the_daemon_announces_is_undone_and_the_job_restarts_in_place(self):
        with World() as w:
            job = w.job("stella", state="blocked", running=True, flags=STELLA_FLAGS)
            w.pane("p1", attach=job)
            w.opt("always_fork", True)  # the daemon starts a copy and says so
            p = w.run("stella", "restart")
            self.assertIn("instead of continuing it", p.stdout, p.stdout + p.stderr)
            stellas = [j for j, v in w.load()["jobs"].items() if v["name"] == "stella"]
            self.assertEqual(stellas, [job])  # the copy is gone, the job is the same
            self.assertIn(job, w.load()["workers"])
            self.assertEqual(w.load()["panes"]["p1"]["fg"], f"attach:{job}")
            self.assertTrue(any(c.startswith(f"respawn {job}") for c in w.claude_calls()), w.claude_calls())


if __name__ == "__main__":
    unittest.main()
