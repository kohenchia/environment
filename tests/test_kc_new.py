"""kc-new: validates a request, starts the session, puts a window in the space."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin/kc-new"


class KcNew(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.home = Path(self.t.name)
        (self.home / "bin").mkdir()
        (self.home / "github/proj").mkdir(parents=True)
        (self.home / ".claude/jobs/aaaa1111/tmp").mkdir(parents=True)
        self.log = self.home / "calls.log"
        (self.home / "agents.json").write_text("[]")
        self.tool("claude", f'''case "$1" in
  agents) cat {self.home}/agents.json ;;
  stop) echo "claude $*" >> {self.log}; [ -f {self.home}/stop-fails ] && exit 1 ;;
  --bg) echo "claude $*" >> {self.log}
        n=""; while [ $# -gt 0 ]; do if [ "$1" = -n ]; then n="$2"; fi; shift; done
        echo "[{{\\"kind\\":\\"background\\",\\"id\\":\\"bbbb2222\\",\\"name\\":\\"$n\\"}}]" > {self.home}/agents.json ;;
esac''')
        self.herdr_fail = ""
        self.write_herdr()

    def tearDown(self):
        self.t.cleanup()

    def tool(self, name, body):
        (self.home / "bin" / name).write_text(f"#!/bin/sh\n{body}\n")
        (self.home / "bin" / name).chmod(0o755)

    def write_herdr(self, fail=False):
        body = "echo 'Error: Operation not permitted' >&2; exit 1" if fail else f'''case "$1 $2" in
"workspace list") echo '{{"result":{{"workspaces":[{{"workspace_id":"w9","label":"existing"}}]}}}}' ;;
"workspace create") echo "herdr $*" >> {self.log}; echo '{{"result":{{"workspace":{{"workspace_id":"w10"}},"tab":{{"tab_id":"t10"}},"root_pane":{{"pane_id":"p10"}}}}}}' ;;
"tab create") echo "herdr $*" >> {self.log}; echo '{{"result":{{"tab":{{"tab_id":"t2"}},"root_pane":{{"pane_id":"p2"}}}}}}' ;;
"tab rename"|"pane run") echo "herdr $*" >> {self.log} ;;
esac'''
        self.tool("herdr", body)

    def request(self, **kw):
        req = {"space": "new-work", "dir": str(self.home / "github/proj"), "prompt": "do the thing", **kw}
        (self.home / ".claude/jobs/aaaa1111/tmp/kc-new.json").write_text(json.dumps(req))

    def run_helper(self, *args):
        return subprocess.run(["python3", str(BIN), *args], env={"HOME": str(self.home), "PATH": f"{self.home / 'bin'}:/usr/bin:/bin"},
                              capture_output=True, text=True, timeout=60)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def result(self):
        return json.loads((self.home / ".claude/jobs/aaaa1111/tmp/kc-new.result.json").read_text())

    def test_a_new_space_gets_its_first_window_running_the_attach(self):
        self.request()
        p = self.run_helper()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("started session new-work (bbbb2222) in space new-work", p.stdout)
        self.assertTrue(self.calls()[0].startswith("claude --bg -n new-work --dangerously-skip-permissions -- do the thing"))
        proj = (self.home / "github/proj").resolve()  # the helper resolves symlinks before it checks the path
        self.assertIn(f"herdr workspace create --label new-work --cwd {proj} --no-focus", self.calls())
        self.assertIn("herdr tab rename t10 new-work", self.calls())
        self.assertIn("herdr pane run p10 claude attach bbbb2222", self.calls())
        self.assertEqual(self.result(), {"ok": True, "id": "bbbb2222", "name": "new-work", "space": "new-work"})

    def test_a_model_is_passed_to_the_session(self):
        self.request(model="opus")
        p = self.run_helper()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(self.calls()[0].startswith("claude --bg -n new-work --model opus --dangerously-skip-permissions -- do the thing"))

    def test_an_effort_is_passed_to_the_session(self):
        self.request(model="opus", effort="high")
        p = self.run_helper()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(self.calls()[0].startswith("claude --bg -n new-work --model opus --effort high --dangerously-skip-permissions -- do the thing"))

    def test_an_unknown_effort_is_refused(self):
        self.request(effort="ultra")
        self.assertNotEqual(self.run_helper().returncode, 0)

    def test_an_unknown_model_is_refused(self):
        self.request(model="gpt")
        p = self.run_helper()
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(self.calls(), [])

    def job(self, jid, name, flags, state="done"):
        d = self.home / ".claude/jobs" / jid
        d.mkdir(parents=True, exist_ok=True)
        (self.home / "github/proj").mkdir(parents=True, exist_ok=True)
        (d / "state.json").write_text(json.dumps({"name": name, "state": state, "sessionId": "sess-" + jid,
                                                  "cwd": str(self.home / "github/proj"), "respawnFlags": json.dumps(flags)}))

    def restart(self, **kw):
        (self.home / ".claude/jobs/aaaa1111/tmp/kc-new.json").write_text(json.dumps(kw))
        return self.run_helper()

    def test_restart_moves_a_session_into_bypass_mode(self):
        self.job("cccc3333", "slow-one", ["--permission-mode", "auto"])
        p = self.restart(restart="slow-one")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.calls()[0], "claude stop cccc3333")
        self.assertTrue(self.calls()[1].startswith("claude --bg --resume sess-cccc3333 -n slow-one --dangerously-skip-permissions --"))
        self.assertIn("restarted slow-one (bbbb2222) in bypass-permissions mode (was auto)", p.stdout)

    def test_restart_of_a_finished_session_survives_a_failing_stop_but_a_blocked_one_does_not(self):
        (self.home / "stop-fails").write_text("")
        self.job("aaaa9999", "done-one", ["--permission-mode", "auto"], state="done")
        p = self.restart(restart="done-one")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.job("bbbb9999", "waiting-one", ["--permission-mode", "auto"], state="blocked")
        p = self.restart(restart="waiting-one")
        self.assertNotEqual(p.returncode, 0)

    def test_restart_refuses_a_bypass_session_a_working_one_and_stella(self):
        self.job("dddd4444", "fine", ["--dangerously-skip-permissions"])
        self.job("eeee5555", "busy", ["--permission-mode", "auto"], state="working")
        self.job("ffff6666", "stella", ["--permission-mode", "auto"])
        for name in ("fine", "busy", "stella", "nobody"):
            p = self.restart(restart=name)
            self.assertNotEqual(p.returncode, 0, name)
        self.assertEqual(self.calls(), [])

    def test_an_existing_space_gets_a_window(self):
        self.request(space="existing", name="second-task")
        p = self.run_helper()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(any(c.startswith("herdr tab create --workspace w9 --label second-task") for c in self.calls()))
        self.assertIn("herdr pane run p2 claude attach bbbb2222", self.calls())
        self.assertFalse(any("workspace create" in c for c in self.calls()))

    def test_the_request_is_consumed_even_when_it_is_refused(self):
        self.request(dir="/tmp")
        p = self.run_helper()
        self.assertEqual(p.returncode, 1)
        self.assertIn("dir must be an existing directory under", p.stdout)
        self.assertFalse((self.home / ".claude/jobs/aaaa1111/tmp/kc-new.json").exists())
        self.assertEqual(self.calls(), [])  # nothing was started
        self.assertFalse(self.result()["ok"])

    def test_every_field_is_checked_before_anything_starts(self):
        for bad in ({"space": "x; rm -rf ~"}, {"space": "../x"}, {"name": "Bad Name"}, {"prompt": "  "},
                    {"dir": str(self.home / "github/nope")}, {"dir": str(self.home / "github/../etc")}):
            self.request(**bad)
            p = self.run_helper()
            self.assertEqual(p.returncode, 1, bad)
            self.assertEqual(self.calls(), [], bad)

    def test_extra_roots_come_from_the_machines_file(self):
        (self.home / "notes").mkdir()
        self.request(dir=str(self.home / "notes"))
        self.assertEqual(self.run_helper().returncode, 1)  # not a root yet
        (self.home / ".config/kc-new").mkdir(parents=True)
        (self.home / ".config/kc-new/roots").write_text(f"# extra roots\n{self.home / 'notes'}\n")
        self.request(dir=str(self.home / "notes"))
        p = self.run_helper()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_arguments_are_refused(self):
        self.request()
        p = self.run_helper("--prompt", "x")
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_no_request_is_an_error(self):
        p = self.run_helper()
        self.assertEqual(p.returncode, 1)
        self.assertIn("no request found", p.stderr)

    def test_a_session_that_started_but_got_no_window_says_how_to_attach(self):
        self.request()
        self.write_herdr(fail=True)
        p = self.run_helper()
        self.assertEqual(p.returncode, 1)
        self.assertIn("started, but no window", p.stdout)
        self.assertIn("claude attach bbbb2222", p.stdout)
        self.assertEqual(self.result()["id"], "bbbb2222")


if __name__ == "__main__":
    unittest.main()
