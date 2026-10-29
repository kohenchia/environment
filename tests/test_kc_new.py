"""kc-new: validates a request, starts the session, puts a window in the space."""

import json
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fakeworld import World  # noqa: E402

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

    def test_the_machines_after_start_hook_gets_the_new_job_and_the_caller(self):
        hooks = self.home / ".config/kc-new"
        hooks.mkdir(parents=True)
        hook = hooks / "after-start"
        hook.write_text(f'#!/bin/sh\necho "hook $1 $KC_CALLER_JOB" >> {self.log}\n')
        hook.chmod(0o755)
        self.request(name="child")
        p = self.run_helper()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("hook bbbb2222 aaaa1111", self.calls())

    def test_a_failing_after_start_hook_leaves_the_session_and_says_so(self):
        hooks = self.home / ".config/kc-new"
        hooks.mkdir(parents=True)
        hook = hooks / "after-start"
        hook.write_text("#!/bin/sh\necho boom >&2; exit 1\n")
        hook.chmod(0o755)
        self.request(name="child")
        p = self.run_helper()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("started session child", p.stdout)
        self.assertIn("WARNING: the after-start hook failed: boom", p.stdout)
        self.assertTrue(any(c.startswith("herdr") for c in self.calls()))

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


class RestartAndDoctor(unittest.TestCase):
    """The restart and doctor requests, against the fake daemon (tests/fakeworld.py)."""

    def request(self, w, caller, **kw):
        d = w.home / ".claude/jobs" / caller / "tmp"
        d.mkdir(parents=True, exist_ok=True)
        (d / "kc-new.json").write_text(json.dumps(kw))
        return d

    def result(self, d):
        return json.loads((d / "kc-new.result.json").read_text())

    def test_restart_continues_a_non_bypass_session_in_bypass_and_moves_its_window(self):
        with World() as w:
            caller = w.job("caller", state="blocked", running=True)
            old = w.job("slow-one", state="blocked", running=True, flags=["--permission-mode", "auto"])
            w.pane("p1", attach=old, tab_label="slow-one")
            d = self.request(w, caller, restart="slow-one")
            p = w.run("kc-new")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            world = w.load()
            slow = [j for j, v in world["jobs"].items() if v["name"] == "slow-one"]
            self.assertEqual(len(slow), 1)  # the old record is gone
            self.assertNotEqual(slow[0], old)
            self.assertEqual(world["panes"]["p1"]["fg"], f"attach:{slow[0]}")
            self.assertIn("in bypass-permissions mode (was auto)", p.stdout)
            self.assertEqual(self.result(d)["id"], slow[0])

    def test_force_restarts_a_bypass_session_in_place_keeping_its_id_and_window(self):
        with World() as w:
            caller = w.job("caller", state="blocked", running=True)
            job = w.job("reload-me", state="blocked", running=True)
            w.pane("p1", attach=job)
            d = self.request(w, caller, restart="reload-me")
            self.assertNotEqual(w.run("kc-new").returncode, 0)  # already bypass: refused without force
            self.assertEqual(w.claude_calls(), [])
            self.request(w, caller, restart="reload-me", force=True)
            p = w.run("kc-new")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertEqual(w.claude_calls(), [f"respawn {job}"])
            self.assertEqual(w.load()["panes"]["p1"]["fg"], f"attach:{job}")
            self.assertEqual(self.result(d)["id"], job)

    def test_restart_refuses_a_busy_session_stella_and_an_ambiguous_name(self):
        with World() as w:
            caller = w.job("caller", state="blocked", running=True)
            w.job("busy", state="working", tempo="active", running=True, flags=["--permission-mode", "auto"])
            w.job("stella", state="blocked", running=True, flags=["--permission-mode", "auto"])
            w.job("twin", state="done", running=True, flags=["--permission-mode", "auto"])
            w.job("twin", state="working", running=True, flags=["--permission-mode", "auto"])
            for name in ("busy", "stella", "twin", "nobody"):
                d = self.request(w, caller, restart=name)
                p = w.run("kc-new")
                self.assertNotEqual(p.returncode, 0, name)
                self.assertFalse(self.result(d)["ok"], name)
            self.assertEqual(w.claude_calls(), [])

    def test_a_new_session_may_not_take_a_live_name(self):
        with World() as w:
            caller = w.job("caller", state="blocked", running=True)
            w.job("taken", state="blocked", running=True)
            (w.home / "github/proj").mkdir()
            d = self.request(w, caller, space="s", dir=str(w.home / "github/proj"), name="taken", prompt="x")
            p = w.run("kc-new")
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("already exists", self.result(d)["error"])
            self.assertEqual(w.claude_calls(), [])

    def test_doctor_report_works_for_any_session_and_repair_only_for_stella_once_in_ten_minutes(self):
        with World() as w:
            caller = w.job("somebody", state="blocked", running=True)
            d = self.request(w, caller, doctor="report")
            p = w.run("kc-new")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertIn("ok: nothing to fix", self.result(d)["report"])
            self.request(w, caller, doctor="repair")
            self.assertNotEqual(w.run("kc-new").returncode, 0)
            self.assertIn("only run for Stella", self.result(d)["error"])
        with World() as w:
            stella = w.job("stella", state="blocked", running=True)
            sj = w.load()["jobs"][stella]
            w.ctl("set", stella, "template", json.dumps("stella"))
            d = self.request(w, stella, doctor="repair")
            self.assertEqual(w.run("kc-new").returncode, 0)
            self.request(w, stella, doctor="repair")
            self.assertNotEqual(w.run("kc-new").returncode, 0)
            self.assertIn("10 minutes", self.result(d)["error"])
            del sj

    def test_doctor_takes_no_other_fields_and_uses_the_machines_hooks(self):
        with World() as w:
            caller = w.job("somebody", state="blocked", running=True)
            d = self.request(w, caller, doctor="report", force=True)
            self.assertNotEqual(w.run("kc-new").returncode, 0)
            hook = w.home / ".config/kc-sessions/doctor"
            hook.parent.mkdir(parents=True)
            hook.write_text('#!/bin/sh\necho "hook ran for $KC_CALLER_JOB"; echo drift: token; exit 1\n')
            hook.chmod(0o755)
            self.request(w, caller, doctor="report")
            p = w.run("kc-new")
            self.assertEqual(p.returncode, 1)
            self.assertEqual(self.result(d)["report"], [f"hook ran for {caller}", "drift: token"])

class MoveAndRename(unittest.TestCase):
    """The move and rename requests, against the fake daemon and the fake herdr (tests/fakeworld.py)."""

    request = RestartAndDoctor.request
    result = RestartAndDoctor.result

    def where(self, w, job):
        """(space label, tab label) of the window that attaches the job."""
        world = w.load()
        pane = next(p for p in world["panes"].values() if p["fg"] == f"attach:{job}")
        tab = world["tabs"][pane["tab"]]
        return world["workspaces"][tab["ws"]]["label"], tab["label"]

    def moves(self, w):
        return [c for c in w.calls() if c.startswith("herdr pane move")]

    def test_move_puts_the_window_in_an_existing_space_without_restarting_the_session(self):
        with World() as w:
            caller = w.job("caller", state="blocked", running=True)
            job = w.job("reports-docs", state="blocked", running=True)
            w.pane("p1", "w1:t1", attach=job, ws="w1", ws_label="work", tab_label="reports-docs")
            w.pane("p2", "w2:t2", ws="w2", ws_label="reports")
            d = self.request(w, caller, move="reports-docs", space="reports")
            p = w.run("kc-new")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertEqual(self.where(w, job), ("reports", "reports-docs"))
            self.assertEqual(w.claude_calls(), [])  # not restarted
            self.assertIn(job, w.load()["workers"])
            r = self.result(d)
            self.assertEqual((r["ok"], r["moved"], r["id"], r["was"], r["created_space"]), (True, "reports-docs", job, "work/reports-docs", False))
            self.assertIn("--new-tab --workspace w2 --label reports-docs --no-focus", self.moves(w)[0])
            self.assertEqual(w.typed(), [])  # nothing typed into any pane

    def test_move_makes_the_space_when_none_has_the_name(self):
        with World() as w:
            caller = w.job("caller", state="blocked", running=True)
            job = w.job("reports-docs", state="blocked", running=True)
            w.pane("p1", attach=job, tab_label="reports-docs")
            d = self.request(w, caller, move="reports-docs", space="brand new")
            p = w.run("kc-new")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertEqual(self.where(w, job), ("brand new", "reports-docs"))
            self.assertTrue(self.result(d)["created_space"])
            self.assertIn("--new-workspace --label brand new --tab-label reports-docs --no-focus", self.moves(w)[0])

    def test_move_to_the_space_it_is_already_in_does_nothing(self):
        with World() as w:
            caller = w.job("caller", state="blocked", running=True)
            job = w.job("reports-docs", state="blocked", running=True)
            w.pane("p1", attach=job, ws_label="work")
            d = self.request(w, caller, move="reports-docs", space="work")
            self.assertEqual(w.run("kc-new").returncode, 0)
            self.assertTrue(self.result(d)["unchanged"])
            self.assertEqual(self.moves(w), [])

    def test_move_refuses_what_it_cannot_do_and_moves_nothing(self):
        with World() as w:
            caller = w.job("caller", state="blocked", running=True)
            job = w.job("has-window", state="blocked", running=True)
            w.job("no-window", state="blocked", running=True)
            two = w.job("two-windows", state="blocked", running=True)
            w.job("twin", state="done", running=True)
            w.job("twin", state="working", running=True)
            w.pane("p1", attach=job)
            w.pane("p2", attach=two)
            w.pane("p3", attach=two)
            for req in ({"move": "no-window", "space": "s"}, {"move": "two-windows", "space": "s"}, {"move": "twin", "space": "s"},
                        {"move": "nobody", "space": "s"}, {"move": "has-window", "space": "x; rm -rf ~"}, {"move": "has-window"},
                        {"move": "has-window", "space": "s", "force": True}, {"move": "has-window", "rename": "x", "space": "s"}):
                d = self.request(w, caller, **req)
                p = w.run("kc-new")
                self.assertNotEqual(p.returncode, 0, req)
                self.assertFalse(self.result(d)["ok"], req)
            self.assertEqual(self.moves(w), [])
            self.assertIn("more than one session", self.request_error(w, caller, move="twin", space="s"))

    def request_error(self, w, caller, **req):
        d = self.request(w, caller, **req)
        w.run("kc-new")
        return self.result(d)["error"]

    def test_rename_changes_the_name_and_the_window_title_without_restarting(self):
        with World() as w:
            caller = w.job("caller", state="blocked", running=True)
            job = w.job("2332-include-consistency", state="blocked", running=True)
            w.pane("p1", attach=job, tab_label="2332-include-consistency")
            w.pane("p2", "w1:t2", tab_label="2332-include-consistency")  # a shell window with the same title: not the session's
            d = self.request(w, caller, rename="2332-include-consistency", to="include-consistency")
            p = w.run("kc-new")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            state = json.loads((w.home / ".claude/jobs" / job / "state.json").read_text())
            self.assertEqual((state["name"], state["nameSource"]), ("include-consistency", "user"))
            self.assertEqual(self.where(w, job), ("work", "include-consistency"))
            self.assertEqual(w.load()["tabs"]["w1:t2"]["label"], "2332-include-consistency")
            self.assertEqual(w.claude_calls(), [])  # not restarted
            self.assertIn(job, w.load()["workers"])
            self.assertEqual(self.result(d), {"ok": True, "renamed": "2332-include-consistency", "to": "include-consistency", "id": job, "windows": ["w1:t1"]})
            # the new name resolves, the old one is gone, and the name survives the daemon's next write
            w.ctl("noop")
            self.request(w, caller, rename="include-consistency", to="again-2")
            self.assertEqual(w.run("kc-new").returncode, 0)

    def test_rename_leaves_a_window_title_that_is_not_the_name(self):
        with World() as w:
            caller = w.job("caller", state="blocked", running=True)
            job = w.job("old-name", state="blocked", running=True)
            w.pane("p1", attach=job, tab_label="my own title")
            d = self.request(w, caller, rename="old-name", to="new-name")
            self.assertEqual(w.run("kc-new").returncode, 0)
            self.assertEqual(self.where(w, job), ("work", "my own title"))
            self.assertEqual(self.result(d)["windows"], [])

    def test_rename_without_herdr_still_renames_and_says_the_title_is_not(self):
        with World() as w:
            caller = w.job("caller", state="blocked", running=True)
            job = w.job("old-name", state="blocked", running=True)
            w.pane("p1", attach=job, tab_label="old-name")
            w.opt("herdr_down", True)
            d = self.request(w, caller, rename="old-name", to="new-name")
            p = w.run("kc-new")
            self.assertEqual(p.returncode, 1)
            self.assertIn("WARNING: the session is renamed, but its window title is not", p.stdout)
            self.assertEqual(json.loads((w.home / ".claude/jobs" / job / "state.json").read_text())["name"], "new-name")
            self.assertFalse(self.result(d)["ok"])

    def test_rename_refuses_stella_a_busy_session_a_live_name_and_a_bad_name(self):
        with World() as w:
            caller = w.job("caller", state="blocked", running=True)
            w.job("stella", state="blocked", running=True)
            busy = w.job("busy", state="working", tempo="active", running=True)
            w.job("taken", state="blocked", running=True)
            ok = w.job("quiet", state="blocked", running=True)
            w.job("twin", state="done", running=True)
            w.job("twin", state="working", running=True)
            cases = [({"rename": "stella", "to": "helper"}, "stella is not renamed"),
                     ({"rename": "quiet", "to": "stella"}, "stella is not renamed"),
                     ({"rename": "busy", "to": "free-name"}, "busy; retry when it is idle"),
                     ({"rename": "quiet", "to": "taken"}, "already exists"),
                     ({"rename": "twin", "to": "free-name"}, "more than one session"),
                     ({"rename": "nobody", "to": "free-name"}, "no session called nobody"),
                     ({"rename": "quiet", "to": "Bad Name"}, "lower-case letters"),
                     ({"rename": "quiet", "to": "-dash"}, "lower-case letters"),
                     ({"rename": "quiet"}, "lower-case letters"),
                     ({"rename": "quiet", "to": "quiet"}, "already called"),
                     ({"rename": "quiet", "to": "free-name", "force": True}, "only"),
                     ({"rename": "quiet", "to": "free-name", "move": "quiet", "space": "s"}, "one of restart")]
            for req, why in cases:
                d = self.request(w, caller, **req)
                p = w.run("kc-new")
                self.assertNotEqual(p.returncode, 0, req)
                self.assertIn(why, self.result(d)["error"], req)
            names = sorted(v["name"] for v in w.load()["jobs"].values())
            self.assertEqual(names, sorted(["caller", "stella", "busy", "taken", "quiet", "twin", "twin"]))
            self.assertEqual(w.claude_calls(), [])
            del busy, ok

    def test_rename_may_take_the_name_of_a_stopped_session(self):
        with World() as w:
            caller = w.job("caller", state="blocked", running=True)
            w.job("retired", state="stopped")
            job = w.job("quiet", state="blocked", running=True)
            self.request(w, caller, rename="quiet", to="retired")
            self.assertEqual(w.run("kc-new").returncode, 0)
            self.assertEqual(json.loads((w.home / ".claude/jobs" / job / "state.json").read_text())["name"], "retired")


if __name__ == "__main__":
    unittest.main()
