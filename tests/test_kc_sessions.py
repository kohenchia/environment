"""kc-sessions against the fake daemon and herdr: a restart changes nothing but the worker."""

import json
import unittest
from pathlib import Path

from fakeworld import World


def attach_of(w, pane):
    return w.load()["panes"][pane]["fg"]


class Respawn(unittest.TestCase):
    def test_a_respawn_keeps_the_job_and_gives_the_window_its_attach_back(self):
        with World() as w:
            job = w.job("backlog", state="blocked", running=True)
            w.pane("p1", attach=job, tab_label="backlog")
            before = w.snapshot()
            p = w.run("kc-sessions", "respawn", "backlog")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            after = w.snapshot()
            self.assertEqual(before, after)
            self.assertEqual(attach_of(w, "p1"), f"attach:{job}")
            self.assertEqual(w.claude_calls(), [f"respawn {job}"])
            self.assertEqual(w.typed(), [f"TYPED p1 claude attach {job}"])

    def test_an_attach_that_exits_late_is_not_taken_for_the_new_one(self):
        # the real attach client exits 0.3-0.5 s AFTER the new worker is up (daemon log, 21:09): it must be waited for,
        # and the window must end up with a NEW attach, not an empty shell
        with World() as w:
            job = w.job("backlog", state="blocked", running=True)
            w.pane("p1", attach=job)
            w.opt("late_exit", 1.2)
            old_pid = w.load()["panes"]["p1"]["attach_pid"]
            p = w.run("kc-sessions", "respawn", job)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            w.run("kc-sessions", "windows")  # any herdr call lets the fake's clock run
            pane = w.load()["panes"]["p1"]
            self.assertEqual(pane["fg"], f"attach:{job}")
            self.assertNotEqual(pane["attach_pid"], old_pid)
            self.assertEqual(w.run("kc-sessions", "check", "--files-only").returncode, 0)  # nothing left in the ledger
            self.assertFalse([c for c in w.calls() if "TYPED-INTO-PROGRAM" in c])

    def test_each_sessions_windows_come_back_before_the_next_session_is_restarted(self):
        with World() as w:
            a = w.job("a-idle", state="blocked", running=True)
            b = w.job("b-busy", state="working", tempo="active", running=True)
            w.pane("pa", attach=a)
            w.pane("pb", attach=b)
            p = w.run("kc-sessions", "respawn", a, b, "--wait-idle", "1.5")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            calls = w.calls()
            typed_a = next(i for i, c in enumerate(calls) if c.startswith("TYPED pa"))
            respawn_b = next(i for i, c in enumerate(calls) if c == f"claude respawn {b}")
            self.assertLess(typed_a, respawn_b)  # a's window was back while b was still waited for

    def test_a_respawn_that_gives_a_new_id_is_followed_and_the_old_one_is_not_resumed(self):
        with World() as w:
            old = w.job("backlog", state="blocked", running=True)
            w.pane("p1", attach=old)
            w.opt("respawn_forks", True)
            p = w.run("kc-sessions", "respawn", old)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            new = json.loads((w.home / "kcs/lineage.json").read_text())[old]["new"]
            self.assertEqual(w.load()["panes"]["p1"]["fg"], f"attach:{new}")
            self.assertFalse([c for c in w.claude_calls() if c.startswith("--bg")])  # never resumed beside a live worker

    def test_a_window_that_was_a_shell_all_along_is_not_typed_into(self):
        with World() as w:
            job = w.job("backlog", state="blocked", running=True)
            w.pane("mine", attach=None, tab_label="my notes")
            w.pane("p1", attach=job)
            p = w.run("kc-sessions", "respawn", job)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertEqual(w.typed(), [f"TYPED p1 claude attach {job}"])

    def test_someone_typing_in_the_shell_stops_the_tool_from_typing(self):
        with World() as w:
            job = w.job("backlog", state="blocked", running=True)
            w.pane("p1", attach=job)
            w.opt("user_typing", "p1")
            p = w.run("kc-sessions", "respawn", job)
            self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
            self.assertEqual(w.typed(), [])
            self.assertIn("could not give back", p.stdout)
            self.assertIn("p1", json.loads((w.home / "kcs/detached.json").read_text()))
            self.assertEqual(w.run("kc-sessions", "check", "--files-only").returncode, 1)
            w.opt("user_typing", None)
            self.assertEqual(w.run("kc-sessions", "repair").returncode, 0)
            self.assertEqual(attach_of(w, "p1"), f"attach:{job}")

    def test_two_windows_on_one_session_both_get_it_back(self):
        with World() as w:
            job = w.job("backlog", state="blocked", running=True)
            w.pane("p1", attach=job)
            w.pane("p2", attach=job, ws="w2", ws_label="second")
            p = w.run("kc-sessions", "respawn", job)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertEqual({attach_of(w, "p1"), attach_of(w, "p2")}, {f"attach:{job}"})

    def test_a_pane_running_something_else_is_never_typed_into(self):
        with World() as w:
            job = w.job("backlog", state="blocked", running=True)
            w.pane("p1", fg="other:less -R")
            w.pane("p2", attach=job)
            w.run("kc-sessions", "respawn", job)
            self.assertFalse([c for c in w.calls() if "TYPED-INTO-PROGRAM" in c])

    def test_a_busy_session_is_waited_for_then_restarted(self):
        import threading
        with World() as w:
            job = w.job("backlog", state="working", tempo="active", running=True)
            idle = w.job("idle-one", state="blocked", running=True)

            def quiet():
                w.ctl("set", job, "tempo", json.dumps("idle"))

            threading.Timer(3.0, quiet).start()
            p = w.run("kc-sessions", "respawn", job, idle, "--wait-idle", "60")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertEqual(w.claude_calls(), [f"respawn {idle}", f"respawn {job}"])  # idle first, busy after the wait
            self.assertIn("waiting for", p.stdout)

    def test_a_session_that_goes_idle_while_waited_for_is_restarted_early(self):
        with World() as w:
            job = w.job("backlog", state="working", tempo="active", running=True)
            import subprocess, threading, time
            def idle():
                w.ctl("set", job, "state", json.dumps("blocked"))
                w.ctl("set", job, "tempo", json.dumps("idle"))

            threading.Timer(0.3, idle).start()
            t0 = time.time()
            p = w.run("kc-sessions", "respawn", job, "--wait-idle", "60", env={"KC_SESSIONS_POLL": "0.02"})
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertLess(time.time() - t0, 30)

    def test_now_restarts_a_working_session_at_once(self):
        with World() as w:
            job = w.job("backlog", state="working", tempo="active", running=True)
            p = w.run("kc-sessions", "respawn", job)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertEqual(w.claude_calls(), [f"respawn {job}"])

    def test_a_failed_respawn_is_reported_and_the_window_is_still_attached(self):
        with World() as w:
            job = w.job("backlog", state="blocked", running=True)
            w.pane("p1", attach=job)
            w.opt("respawn_fails", job)
            p = w.run("kc-sessions", "respawn", job)
            self.assertEqual(p.returncode, 1)
            self.assertIn("claude respawn failed", p.stdout)
            self.assertEqual(attach_of(w, "p1"), f"attach:{job}")  # never detached: nothing to restore

    def test_herdr_down_still_restarts_and_says_windows_are_not_tracked(self):
        with World() as w:
            job = w.job("backlog", state="blocked", running=True)
            w.opt("herdr_down", True)
            p = w.run("kc-sessions", "respawn", job)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertIn("windows are not tracked", p.stdout)

    def test_a_stopped_session_is_revived_in_place(self):
        with World() as w:
            job = w.job("old", state="stopped")
            p = w.run("kc-sessions", "respawn", job)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertIn(job, w.load()["workers"])
            self.assertEqual(list(w.load()["jobs"]), [job])


class Screen(unittest.TestCase):
    def test_a_json_answer_with_a_moving_revision_still_counts_as_a_quiet_screen(self):
        import importlib.machinery, importlib.util, subprocess, sys, tempfile
        from pathlib import Path as P
        d = P(tempfile.mkdtemp())
        n = d / "n"
        (d / "herdr").write_text(f"#!/bin/sh\nc=$(cat {n} 2>/dev/null || echo 0); echo $((c+1)) > {n}\n"
                                 f"echo '{{\"result\":{{\"text\":\"prompt %\",\"revision\":'$c'}}}}'\n")
        (d / "herdr").chmod(0o755)
        loader = importlib.machinery.SourceFileLoader("ks_screen", str(P(__file__).resolve().parents[1] / "bin/kc-sessions"))
        ks = importlib.util.module_from_spec(importlib.util.spec_from_loader("ks_screen", loader))
        sys.modules["ks_screen"] = ks
        loader.exec_module(ks)
        import os
        old = os.environ["PATH"]
        os.environ["PATH"] = f"{d}:{old}"
        try:
            self.assertTrue(ks.screen_still("p1"))
        finally:
            os.environ["PATH"] = old


class Ledger(unittest.TestCase):
    def write(self, w, entries):
        (w.home / "kcs").mkdir(exist_ok=True)
        (w.home / "kcs/detached.json").write_text(json.dumps(entries))

    def test_an_old_entry_is_forgotten_not_acted_on(self):
        with World() as w:
            job = w.job("a", state="done", running=True)
            w.pane("p1", fg="shell")
            self.write(w, {"p1": {"job": job, "since": "2020-01-01T00:00:00Z", "pid": 1}})
            p = w.run("kc-sessions", "repair")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertIn("forgotten", p.stdout)
            self.assertEqual(w.typed(), [])
            self.assertEqual(json.loads((w.home / "kcs/detached.json").read_text()), {})

    def test_an_entry_for_a_window_that_is_gone_is_dropped(self):
        with World() as w:
            job = w.job("a", state="blocked", running=True)
            w.pane("other", attach=job)
            self.write(w, {"p-gone": {"job": job, "since": "2099-01-01T00:00:00Z", "pid": 1}})
            p = w.run("kc-sessions", "repair")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertIn("the window is gone", p.stdout)

    def test_a_finished_job_is_never_revived_to_fill_a_window(self):
        with World() as w:
            job = w.job("a", state="done")  # no worker
            w.pane("p1", fg="shell")
            self.write(w, {"p1": {"job": job, "since": "2099-01-01T00:00:00Z", "pid": 1}})
            p = w.run("kc-sessions", "repair")
            self.assertIn("not reviving", p.stdout)
            self.assertEqual(w.typed(), [])
            self.assertNotIn(job, w.load()["workers"])


class Model(unittest.TestCase):
    def test_the_fork_takes_the_model_of_the_main_thread_not_of_a_subagent_or_a_tool_result(self):
        with World() as w:
            old = w.job("review", state="blocked", running=True)
            tr = w.load()["jobs"][old]["transcript"]
            lines = [
                json.dumps({"type": "assistant", "message": {"model": "claude-sonnet-5-5", "content": []}}),
                json.dumps({"type": "assistant", "isSidechain": True, "message": {"model": "claude-opus-5-5"}}),
                json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": 'model": "claude-opus-5-5"'}]}}),
            ]
            Path(tr).write_text("\n".join(lines) + "\n")
            p = w.run("kc-sessions", "fork", "review")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            bg = [c for c in w.claude_calls() if c.startswith("--bg")][0]
            self.assertIn("--model sonnet", bg)


class Names(unittest.TestCase):
    def test_a_name_with_one_running_job_resolves_to_it(self):
        with World() as w:
            old = w.job("x", state="stopped")
            new = w.job("x", state="working", running=True)
            p = w.run("kc-sessions", "respawn", "x")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertEqual(w.claude_calls(), [f"respawn {new}"])
            self.assertNotIn(old, "".join(w.claude_calls()))

    def test_two_running_jobs_of_one_name_are_ambiguous(self):
        with World() as w:
            a = w.job("x", state="done", running=True)
            b = w.job("x", state="working", running=True)
            p = w.run("kc-sessions", "respawn", "x")
            self.assertEqual(p.returncode, 2)
            self.assertIn(a, p.stderr)
            self.assertIn(b, p.stderr)
            self.assertEqual(w.claude_calls(), [])

    def test_a_recorded_fork_settles_which_is_current(self):
        with World() as w:
            a = w.job("x", state="done", running=True)
            b = w.job("x", state="working", running=True)
            (w.home / "kcs").mkdir()
            (w.home / "kcs/lineage.json").write_text(json.dumps({a: {"new": b, "at": "t"}}))
            p = w.run("kc-sessions", "respawn", "x")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertEqual(w.claude_calls(), [f"respawn {b}"])

    def test_an_unknown_name_is_an_error(self):
        with World() as w:
            p = w.run("kc-sessions", "respawn", "nope")
            self.assertEqual(p.returncode, 2)
            self.assertIn("no session called nope", p.stderr)


class Fork(unittest.TestCase):
    def test_a_fork_moves_the_window_and_retires_the_old_record(self):
        with World() as w:
            old = w.job("review", state="blocked", running=True, flags=["--dangerously-skip-permissions"], created="2026-10-19T00:00:00.000Z")
            w.job("other", state="blocked", running=True)
            w.pane("p1", attach=old, tab_label="review")
            p = w.run("kc-sessions", "fork", "review")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            world = w.load()
            names = [(j, v["name"]) for j, v in world["jobs"].items() if v["name"] == "review"]
            self.assertEqual(len(names), 1, names)  # one name, one session
            new = names[0][0]
            self.assertNotEqual(new, old)
            self.assertEqual(world["panes"]["p1"]["fg"], f"attach:{new}")
            self.assertIn(new, world["workers"])
            self.assertEqual(json.loads((w.home / "kcs/lineage.json").read_text())[old]["new"], new)
            bg = [c for c in w.claude_calls() if c.startswith("--bg")][0]
            self.assertIn("--dangerously-skip-permissions", bg)
            self.assertIn("--model opus", bg)
            self.assertNotIn("--session-id", bg)
            self.assertNotIn("--settings", bg)

    def test_a_busy_session_is_not_forked(self):
        with World() as w:
            old = w.job("review", state="working", tempo="active", running=True)
            p = w.run("kc-sessions", "fork", "review")
            self.assertEqual(p.returncode, 2)
            self.assertIn("busy", p.stderr)
            self.assertEqual(w.claude_calls(), [])
            self.assertIn(old, w.load()["jobs"])

    def test_the_old_record_is_kept_when_its_transcript_grew_after_the_fork(self):
        with World() as w:
            old = w.job("review", state="blocked", running=True)
            tr = w.load()["jobs"][old]["transcript"]
            # `claude stop` is where the old job could have done more work: make the stop append to the transcript
            real = w.bin / "claude"
            real.write_text(real.read_text().replace('exec python3', f'case "$1" in stop) echo \x27{{"type":"user","message":"more"}}\x27 >> {tr};; esac\nexec python3'))
            p = w.run("kc-sessions", "fork", "review")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertIn(old, w.load()["jobs"])  # not removed
            self.assertIn("grew", p.stdout)
            self.assertEqual(sum(1 for v in w.load()["jobs"].values() if v["name"] == "review"), 2)

    def test_bookkeeping_lines_written_by_the_stop_are_not_work(self):
        with World() as w:
            old = w.job("review", state="blocked", running=True)
            tr = w.load()["jobs"][old]["transcript"]
            real = w.bin / "claude"
            real.write_text(real.read_text().replace('exec python3', f'case "$1" in stop) echo \x27{{"type":"cost-state","totalCostUSD":1}}\x27 >> {tr};; esac\nexec python3'))
            p = w.run("kc-sessions", "fork", "review")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertNotIn(old, w.load()["jobs"])  # removed
            self.assertEqual(sum(1 for v in w.load()["jobs"].values() if v["name"] == "review"), 1)
    def test_a_job_in_a_git_worktree_is_stopped_but_not_removed(self):
        import subprocess
        with World() as w:
            main = w.home / "github/repo"
            main.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(main)], check=True)
            subprocess.run(["git", "-C", str(main), "-c", "user.email=a@b", "-c", "user.name=n", "commit", "-q", "--allow-empty", "-m", "i"], check=True)
            wt = w.home / "github/repo-wt"
            subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", str(wt), "-b", "b"], check=True)
            old = w.job("review", state="blocked", running=True, cwd=str(wt))
            p = w.run("kc-sessions", "fork", "review")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertIn(old, w.load()["jobs"])
            self.assertNotIn(old, w.load()["workers"])
            self.assertIn("git worktree", p.stdout)


class Check(unittest.TestCase):
    def test_a_clean_world_is_ok(self):
        with World() as w:
            job = w.job("a", state="blocked", running=True)
            w.pane("p1", attach=job)
            p = w.run("kc-sessions", "check")
            self.assertEqual(p.returncode, 0, p.stdout)
            self.assertIn("ok", p.stdout)

    def test_duplicates_stale_windows_and_grey_dots_are_reported(self):
        with World() as w:
            old = w.job("x", state="stopped")
            a = w.job("x", state="working", running=True)
            b = w.job("x", state="done", running=True)
            ok = w.job("y", state="blocked", running=True)
            w.pane("p1", attach=old, tab_label="x")
            w.pane("p2", attach=ok)
            w.ctl("dot", "p2", "unknown")
            p = w.run("kc-sessions", "check")
            self.assertEqual(p.returncode, 1)
            self.assertIn("held by", p.stdout)
            self.assertIn(f"attaches {old}", p.stdout)
            self.assertIn("grey dot", p.stdout)
            del a, b

    def test_files_only_needs_no_herdr_and_no_claude(self):
        with World() as w:
            w.job("x", state="done", running=True)
            w.job("x", state="working", running=True)
            w.opt("herdr_down", True)
            p = w.run("kc-sessions", "check", "--files-only", env={"PATH": "/usr/bin:/bin"})
            self.assertEqual(p.returncode, 1)
            self.assertIn("held by", p.stdout)

    def test_non_bypass_sessions_are_listed_as_information_only(self):
        with World() as w:
            w.job("auto-one", state="blocked", running=True, flags=["--permission-mode", "auto"])
            p = w.run("kc-sessions", "check", "--files-only")
            self.assertEqual(p.returncode, 0)
            self.assertIn("auto", p.stdout)

    def test_a_leftover_ledger_entry_is_drift_and_repair_clears_it(self):
        with World() as w:
            job = w.job("a", state="blocked", running=True)
            w.pane("p1", fg="shell")
            (w.home / "kcs").mkdir()
            (w.home / "kcs/detached.json").write_text(json.dumps({"p1": {"job": job, "since": "t"}}))
            self.assertEqual(w.run("kc-sessions", "check", "--files-only").returncode, 1)
            p = w.run("kc-sessions", "repair")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertEqual(attach_of(w, "p1"), f"attach:{job}")
            self.assertEqual(w.run("kc-sessions", "check", "--files-only").returncode, 0)


class Invariant(unittest.TestCase):
    def snap(self, w):
        p = w.run("kc-sessions", "snapshot")
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def diff(self, w, a, b):
        fa, fb = w.home / "a.json", w.home / "b.json"
        fa.write_text(json.dumps(a))
        fb.write_text(json.dumps(b))
        p = w.run("kc-sessions", "diff", str(fa), str(fb))
        return p.returncode, p.stdout

    def test_a_respawn_changes_nothing_the_snapshot_covers(self):
        with World() as w:
            a = w.job("a", state="blocked", running=True)
            w.job("b", state="working", tempo="active", running=True, flags=["--permission-mode", "auto"])
            w.job("c", state="done")  # no worker
            w.pane("p1", attach=a, tab_label="a")
            w.pane("mine", tab_label="notes")
            before = self.snap(w)
            self.assertEqual(w.run("kc-sessions", "respawn", "a", "b").returncode, 0)
            rc, out = self.diff(w, before, self.snap(w))
            self.assertEqual((rc, out), (0, ""))

    def test_focus_new_windows_and_new_jobs_are_not_damage(self):
        with World() as w:
            a = w.job("a", state="blocked", running=True)
            w.pane("p1", attach=a)
            before = self.snap(w)
            w.job("brand-new", state="blocked", running=True)
            w.pane("p2", attach=None, tab_label="opened meanwhile")
            world = w.load()
            world["panes"]["p1"]["focused"] = True
            w.world = world
            w.save()
            self.assertEqual(self.diff(w, before, self.snap(w)), (0, ""))

    def test_the_diff_names_every_kind_of_damage(self):
        with World() as w:
            a = w.job("a", state="blocked", running=True)
            w.pane("p1", attach=a, tab_label="a")
            before = self.snap(w)
            w.ctl("retire", a)  # the worker is gone and the window fell to its shell
            rc, out = self.diff(w, before, self.snap(w))
            self.assertEqual(rc, 1)
            self.assertIn("had a worker and has none now", out)
            self.assertIn("now shows None", out)
            w.ctl("set", a, "name", json.dumps("renamed"))
            self.assertIn("name changed", self.diff(w, before, self.snap(w))[1])

    def test_a_flag_that_was_dropped_is_a_difference(self):
        with World() as w:
            a = w.job("a", state="blocked", running=True, flags=["--dangerously-skip-permissions", "--effort", "high"])
            before = self.snap(w)
            w.ctl("set", a, "flags", json.dumps(["--dangerously-skip-permissions"]))
            self.assertIn("flags changed", self.diff(w, before, self.snap(w))[1])


if __name__ == "__main__":
    unittest.main()
