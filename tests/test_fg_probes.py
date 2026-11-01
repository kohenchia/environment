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


if __name__ == "__main__":
    unittest.main()
