"""fg-probes: the parts that can be tested without a real claude or herdr server."""

import importlib.machinery
import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "bin/fg-probes"
loader = importlib.machinery.SourceFileLoader("fg_probes", str(PATH))
fp = importlib.util.module_from_spec(importlib.util.spec_from_loader("fg_probes", loader))
loader.exec_module(fp)


def fake_herdr(tmp: Path, body: str) -> dict:
    """A `herdr` on PATH that runs `body` (bash) and logs its arguments and socket."""
    bindir = tmp / "bin"
    bindir.mkdir(exist_ok=True)
    exe = bindir / "herdr"
    exe.write_text("#!/bin/bash\n"
                   f'echo "$HERDR_SOCKET_PATH $*" >> "{tmp}/calls.log"\n' + body + "\n")
    exe.chmod(0o755)
    return dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")


class Transcripts(unittest.TestCase):
    def test_peer_messages_skip_subagent_hand_backs(self):
        recs = [
            {"origin": {"kind": "peer", "name": "fg-probe-b", "fromMode": "bypass", "body": "ping"}},
            {"origin": {"kind": "peer", "name": "general-purpose", "senderTaskId": "a1", "body": "[Subagent hand-back]"}},
            {"origin": {"kind": "human"}},
        ]
        self.assertEqual(fp.peer_messages(recs), [{"from": "fg-probe-b", "mode": "bypass", "body": "ping"}])

    def test_tool_uses_and_text(self):
        recs = [{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "ListAgents"},
                                                              {"type": "text", "text": "3 peers"}]}}]
        self.assertEqual(len(fp.tool_uses(recs, "ListAgents")), 1)
        self.assertEqual(fp.assistant_text(recs), "3 peers")


class Registry(unittest.TestCase):
    def test_a_dead_pid_is_not_a_live_session(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            dead = subprocess.Popen(["true"])
            dead.wait()
            (d / "1.json").write_text(json.dumps({"pid": os.getpid(), "name": "fg-probe-a", "sessionId": "s1"}))
            (d / "2.json").write_text(json.dumps({"pid": dead.pid, "name": "fg-probe-a", "sessionId": "s0"}))
            old, fp.SESSIONS = fp.SESSIONS, d
            try:
                self.assertEqual(fp.find_session(name="fg-probe-a")["sessionId"], "s1")
                self.assertIsNone(fp.find_session(sid="s0"))
            finally:
                fp.SESSIONS = old


class HerdrGuard(unittest.TestCase):
    def test_never_manages_a_server_or_a_session(self):
        with tempfile.TemporaryDirectory() as t:
            h = fp.Herdr(Path(t))
            for args in (("server", "stop"), ("session", "stop", "default"), ("server",)):
                with self.assertRaises(RuntimeError):
                    h.call(*args)

    def test_every_call_goes_to_the_probe_socket(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            env = fake_herdr(tmp, 'echo "{}"')
            h = fp.Herdr(tmp)
            h.sock = "/tmp/probe.sock"
            old = os.environ["PATH"]
            os.environ["PATH"] = env["PATH"]
            os.environ["HERDR_SOCKET_PATH"] = "/tmp/kohens-main.sock"
            try:
                h.call("workspace", "list")
            finally:
                os.environ["PATH"] = old
                del os.environ["HERDR_SOCKET_PATH"]
            self.assertEqual((tmp / "calls.log").read_text().split()[0], "/tmp/probe.sock")


class StandIn(unittest.TestCase):
    """The window loop's end record, as the stand-in makes it on SIGHUP."""

    def hup(self, herdr_body: str) -> dict:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            env = fake_herdr(tmp, herdr_body)
            env.update(FG_PROBES_OUT=str(tmp), HERDR_PANE_ID="w1:p2")
            env.pop("CLAUDECODE", None)
            p = subprocess.Popen([sys.executable, str(PATH), "stand-in", "B"], env=env)
            time.sleep(1.0)
            p.send_signal(signal.SIGHUP)
            p.wait(timeout=10)
            return json.loads((tmp / "hup-B.json").read_text())

    def test_a_stopped_server_answering_at_once_is_interrupted(self):
        rec = self.hup('echo \'{"error":{"code":"server_not_running"}}\'; exit 1')
        self.assertEqual(rec["verdict"], "interrupted")

    def test_pane_gone_and_herdr_answering_is_a_closed_window(self):
        rec = self.hup('echo "pane not found" >&2; exit 1')
        self.assertEqual(rec["verdict"], "closed")

    def test_herdr_not_answering_is_an_interrupted_session(self):
        rec = self.hup("sleep 5")
        self.assertEqual(rec["verdict"], "interrupted")

    def test_pane_still_there(self):
        rec = self.hup('echo \'{"pane_id": "w1:p2"}\'')
        self.assertEqual(rec["verdict"], "pane still there")


class Modes(unittest.TestCase):
    def test_restored_writes_where_the_resume_command_says(self):
        with tempfile.TemporaryDirectory() as t:
            fp.restored("A", t)
            self.assertTrue((Path(t) / "restored-A.json").exists())

    def test_refuses_to_run_inside_a_claude_session(self):
        env = dict(os.environ, CLAUDECODE="1")
        p = subprocess.run([sys.executable, str(PATH), "--only", "P1"], env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)
        self.assertIn("plain terminal", p.stderr)


class Report(unittest.TestCase):
    def test_table_escapes_pipes_and_counts(self):
        with tempfile.TemporaryDirectory() as t:
            r = fp.Results(Path(t))
            r.add("P1", "a | b", True, "x|y")
            r.add("P2", "c", False)
            r.add("P3", "d", None)
            self.assertIn("x\\|y", r.table())
            self.assertEqual(r.save(), {"PASS": 1, "FAIL": 1, "SKIP": 1})
            self.assertTrue((Path(t) / "summary.md").exists())


class Fixes(unittest.TestCase):
    """The review's blocking findings, each pinned by a test."""

    def test_a_stopped_server_is_an_interrupted_session_not_a_closed_window(self):
        said = '{"error":{"code":"server_not_running","message":"herdr server is not running"}}'
        self.assertEqual(fp.hup_verdict(True, 1, said), "interrupted")
        self.assertEqual(fp.hup_verdict(True, 1, "pane not found"), "closed")
        self.assertEqual(fp.hup_verdict(False, None, "timeout"), "interrupted")
        said = '{"error":{"code":"server_unavailable","message":"server is shutting down"}}'
        self.assertEqual(fp.hup_verdict(True, 1, said), "interrupted")  # what herdr 0.9.5 answers on a session stop

    def test_only_probe_made_jobs_are_cleaned_up(self):
        with tempfile.TemporaryDirectory() as t:
            jobs = Path(t)
            for jid, state in (("aaaa1111", {"name": "fg-probe-v-fork"}),
                               ("bbbb2222", {"name": "kohen-real-work", "sessionId": "other"}),
                               ("cccc3333", {"name": "copy", "forkParentSessionId": "probe-sid"})):
                (jobs / jid).mkdir()
                (jobs / jid / "state.json").write_text(json.dumps(state))
            old, fp.JOBS = fp.JOBS, jobs
            try:
                self.assertEqual(sorted(fp.probe_jobs(["aaaa1111", "bbbb2222", "cccc3333"], "probe-sid")),
                                 ["aaaa1111", "cccc3333"])
            finally:
                fp.JOBS = old

    def test_the_subscription_names_pane_moved(self):
        self.assertEqual(fp.SUBSCRIBE, {"subscriptions": [{"type": "pane.moved"}]})

    def test_a_move_event_must_name_the_pane_we_moved(self):
        events = [{"event": "pane.moved", "data": {"previous_pane_id": "w1:p9", "pane_id": "w2:p1"}},
                  {"event": "pane.moved", "data": {"previous_pane_id": "w1:p5", "pane_id": "w3:p1"}}]
        self.assertEqual(fp.moved_event(events, "w1:p5")["data"]["pane_id"], "w3:p1")
        self.assertIsNone(fp.moved_event(events, "w1:p7"))

    def test_agents_are_read_from_the_result(self):
        reply = {"id": "x", "result": {"agents": [{"pane_id": "w1:p2", "agent": "claude"}]}}
        self.assertEqual(fp.agents_in(reply), [{"pane_id": "w1:p2", "agent": "claude"}])

    def test_an_unreadable_session_list_runs_no_herdr_probe(self):
        with tempfile.TemporaryDirectory() as t:
            res = fp.Results(Path(t))
            old_sessions, old_start = fp.Herdr.sessions, fp.Herdr.start
            fp.Herdr.sessions = staticmethod(lambda: None)
            started = []
            fp.Herdr.start = lambda self: started.append(1) or False
            try:
                fp.p3_p4_p6_herdr(res, Path(t), [], {"P3"})
            finally:
                fp.Herdr.sessions, fp.Herdr.start = old_sessions, old_start
            self.assertEqual(started, [])
            self.assertEqual(res.rows[0]["status"], "FAIL")

    def test_the_wrapper_records_the_launcher_pid_and_passes_the_exit_code(self):
        with tempfile.TemporaryDirectory() as t:
            pidfile = Path(t) / "launcher.pid"
            p = subprocess.run([sys.executable, str(PATH), "wrap", "--pidfile", str(pidfile), "--",
                                sys.executable, "-c", "import sys; sys.exit(3)"])
            self.assertEqual(p.returncode, 3)
            self.assertTrue(pidfile.read_text().isdigit())

    def test_the_probes_never_inherit_kohens_herdr_window(self):
        old = dict(os.environ)
        os.environ.update(HERDR_SOCKET_PATH="/tmp/main.sock", HERDR_PANE_ID="w1:p1", TERM_PROGRAM="herdr",
                          CLAUDECODE="1")
        try:
            env = fp.clean_env()
        finally:
            os.environ.clear()
            os.environ.update(old)
        self.assertFalse([k for k in env if k.startswith("HERDR_")])
        self.assertNotIn("CLAUDECODE", env)
        self.assertNotIn("TERM_PROGRAM", env)

    def test_a_recycled_pid_is_never_signalled(self):
        me = os.getpid()
        began = fp.started_at(me)
        self.assertIsNotNone(began)
        self.assertTrue(fp.same_process(me, began))
        self.assertFalse(fp.same_process(me, began - 3600))  # same pid, another process's start time
        self.assertFalse(fp.signal_if_same(me, began - 3600, signal.SIGTERM))  # and we are still here
        utc = time.strftime("%a %b %d %H:%M:%S %Y", time.gmtime(began))
        self.assertTrue(fp.same_process(me, utc))  # a registry procStart string

    def test_refuses_while_probe_sessions_from_an_earlier_run_are_live(self):
        old_reg, old_env = fp.registry, dict(os.environ)
        fp.registry = lambda: [{"pid": os.getpid(), "name": "fg-probe-a", "kind": "interactive"}]
        os.environ.pop("CLAUDECODE", None)
        try:
            self.assertEqual(fp.main(["--only", "P1"]), 2)
        finally:
            fp.registry = old_reg
            os.environ.clear()
            os.environ.update(old_env)


if __name__ == "__main__":
    unittest.main()
