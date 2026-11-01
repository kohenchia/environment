"""cy, cy-follow, cag and the cy-crons hook, on a fake claude and a fake herdr in a throwaway home folder."""

import fcntl
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

ROOT = Path(__file__).resolve().parent.parent
CY = ROOT / "bin" / "cy"
FOLLOW = ROOT / "bin" / "cy-follow"
CAG = ROOT / "bin" / "cag"
HOOK = ROOT / "claude" / "bin" / "cy-crons"

FAKE_CLAUDE = r'''#!/usr/bin/env python3
"""A fake claude: registers like the real one, writes a turn to its transcript, waits for SIGTERM or exits."""
import json, os, signal, sys, time
from pathlib import Path
home = Path(os.environ["HOME"])
argv = sys.argv[1:]
with open(home / "argv.log", "a") as f:
    f.write(json.dumps(argv) + "\n")
def opt(name):
    return argv[argv.index(name) + 1] if name in argv else None
sid = opt("--session-id") if ("--session-id" in argv and ("--fork-session" in argv or "--resume" not in argv)) else opt("--resume")
name = opt("-n")
reg = home / ".claude" / "sessions" / f"{os.getpid()}.json"
reg.parent.mkdir(parents=True, exist_ok=True)
start = time.strftime("%a %b %d %H:%M:%S %Y", time.gmtime(time.time()))
reg.write_text(json.dumps({"pid": os.getpid(), "sessionId": sid, "name": name, "status": "idle", "kind": "interactive",
                           "procStart": start, "cwd": os.getcwd(), "nameSource": "user"}))
tr = home / ".claude" / "projects" / "-fake" / f"{sid}.jsonl"
tr.parent.mkdir(parents=True, exist_ok=True)
prompt = argv[-1] if argv and not argv[-1].startswith("-") and argv[-2:-1] != ["--settings"] else ""
with open(tr, "a") as f:
    f.write(json.dumps({"type": "user", "message": {"content": prompt or "(none)"}, "timestamp": "2026-11-01T10:00:00Z",
                        "permissionMode": opt("--permission-mode")}) + "\n")
    f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": os.environ.get("FAKE_REPLY", "ok")}],
                        "model": "claude-haiku-5-5"}, "timestamp": "2026-11-01T10:00:01Z"}) + "\n")
def bye(*_):
    reg.unlink(missing_ok=True)
    sys.exit(0)
signal.signal(signal.SIGTERM, bye)
code = os.environ.get("FAKE_CLAUDE_EXIT")
if code is not None:
    time.sleep(0.5)
    reg.unlink(missing_ok=True)
    sys.exit(int(code))
while True:
    time.sleep(1)
'''

FAKE_HERDR = r'''#!/bin/bash
echo "$*" >> "$HOME/herdr.log"
case "$1 $2" in
  "workspace list") echo '{"result":{"workspaces":[{"workspace_id":"w1","label":"projects"}]}}' ;;
  "pane get") if [ "$3" = "w1:p9" ]; then echo '{"error":{"code":"pane_not_found"}}'; exit 1; fi
              echo '{"result":{"pane":{"pane_id":"'"$3"'","tab_label":"t","workspace_label":"projects"}}}' ;;
  "tab create") echo '{"result":{"tab":{"tab_id":"w1:t5"},"root_pane":{"pane_id":"w1:p5"}}}' ;;
  *) echo '{"result":{"type":"ok"}}' ;;
esac
'''


class World:
    """A throwaway HOME with a fake claude and herdr first on PATH."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        bindir = self.home / "bin"
        bindir.mkdir()
        for name, body in (("claude", FAKE_CLAUDE), ("herdr", FAKE_HERDR)):
            (bindir / name).write_text(body)
            (bindir / name).chmod(0o755)
        self.env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "HERDR_SOCKET_PATH")}
        self.env.update(HOME=str(self.home), PATH=f"{bindir}:{os.environ['PATH']}", HERDR_PANE_ID="w1:p1",
                        HERDR_TAB_ID="w1:t1", HERDR_WORKSPACE_ID="w1")
        self.state = self.home / ".local" / "state" / "cy"
        return self

    def __exit__(self, *exc):
        for p in self.state.glob("*.loop.json") if self.state.exists() else []:
            pid = json.loads(p.read_text()).get("launched_pid")
            if pid:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        self.tmp.cleanup()

    def module(self, path: Path, name: str):
        old = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)
        try:
            loader = importlib.machinery.SourceFileLoader(name, str(path))
            mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
            loader.exec_module(mod)
        finally:
            os.environ["HOME"] = old
        return mod

    def loops(self) -> list[dict]:
        return [json.loads(p.read_text()) for p in sorted(self.state.glob("*.loop.json"))]

    def argv(self) -> list[list[str]]:
        log = self.home / "argv.log"
        return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []

    def cy(self, *args, env=None, wait=True, stdin=subprocess.DEVNULL):
        e = dict(self.env, **(env or {}))
        p = subprocess.Popen([sys.executable, str(CY), *args], env=e, cwd=self.home, stdin=stdin,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if wait:
            out, err = p.communicate(timeout=60)
            return p.returncode, out, err
        return p


def until(pred, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(0.2)
    return pred()


class Loop(unittest.TestCase):
    def test_a_new_session_gets_its_own_id_bypass_and_the_agent_view_off(self):
        with World() as w:
            code, out, err = w.cy("-n", "probe-one", "hello", env={"FAKE_CLAUDE_EXIT": "0"})
            self.assertEqual(code, 0, err)
            loop = w.loops()[0]
            argv = w.argv()[0]
            self.assertEqual(argv[argv.index("--session-id") + 1], loop["id"])
            self.assertEqual(argv[argv.index("--permission-mode") + 1], "bypassPermissions")
            self.assertEqual(json.loads(argv[argv.index("--settings") + 1]), {"disableAgentView": True})
            self.assertEqual(argv[-1], "hello")
            self.assertEqual((loop["status"], loop["end"]), ("ended", "exit"))
            self.assertIn("ended. ⏎ resumes it here", out)

    def test_a_restart_order_relaunches_the_same_conversation_in_the_same_loop(self):
        with World() as w:
            p = w.cy("-n", "probe-two", env={}, wait=False)
            loop = until(lambda: (w.loops() or [{}])[0].get("launched_pid") and w.loops()[0])
            sid, pid = loop["id"], loop["launched_pid"]
            until(lambda: list((w.home / ".claude" / "sessions").glob("*.json")))
            (w.state / "next").mkdir(exist_ok=True)
            (w.state / "next" / f"{sid}.json").write_text(json.dumps(
                {"for_pid": pid, "conversation": sid, "name": "probe-two", "prompt": "[cy restart] carry on"}))
            os.kill(pid, signal.SIGTERM)
            until(lambda: len(w.argv()) >= 2)
            second = w.argv()[1]
            self.assertEqual(second[second.index("--resume") + 1], sid)
            self.assertEqual(second[-1], "[cy restart] carry on")
            self.assertFalse((w.state / "next" / f"{sid}.json").exists())
            os.kill(until(lambda: w.loops()[0]["launched_pid"] != pid and w.loops()[0]["launched_pid"]), signal.SIGTERM)
            p.communicate(timeout=30)
            self.assertEqual(w.loops()[0]["restarts"], 1)

    def test_a_retire_order_ends_the_session_as_retired(self):
        with World() as w:
            p = w.cy("-n", "probe-three", wait=False)
            loop = until(lambda: (w.loops() or [{}])[0].get("launched_pid") and w.loops()[0])
            until(lambda: list((w.home / ".claude" / "sessions").glob("*.json")))
            (w.state / "next").mkdir(exist_ok=True)
            (w.state / "next" / f"{loop['id']}.json").write_text(json.dumps({"for_pid": loop["launched_pid"],
                                                                              "end": "retired"}))
            os.kill(loop["launched_pid"], signal.SIGTERM)
            p.communicate(timeout=30)
            self.assertEqual(w.loops()[0]["status"], "retired")
            self.assertEqual(len(w.argv()), 1)

    def test_a_stale_order_for_another_process_never_relaunches(self):
        with World() as w:
            p = w.cy("-n", "probe-four", wait=False)
            loop = until(lambda: (w.loops() or [{}])[0].get("launched_pid") and w.loops()[0])
            until(lambda: list((w.home / ".claude" / "sessions").glob("*.json")))
            (w.state / "next").mkdir(exist_ok=True)
            (w.state / "next" / f"{loop['id']}.json").write_text(json.dumps({"for_pid": 1, "conversation": loop["id"]}))
            os.kill(loop["launched_pid"], signal.SIGTERM)
            p.communicate(timeout=30)
            self.assertEqual(len(w.argv()), 1)
            self.assertEqual(w.loops()[0]["end"], "exit")

    def test_a_crash_says_how_to_resume(self):
        with World() as w:
            code, out, err = w.cy("-n", "probe-five", env={"FAKE_CLAUDE_EXIT": "3"})
            self.assertEqual(code, 3)
            self.assertEqual(w.loops()[0]["status"], "crashed")
            self.assertIn("cy -r probe-five", err)

    def test_resume_refuses_a_session_live_in_another_window(self):
        with World() as w:
            p = w.cy("-n", "probe-six", wait=False)
            until(lambda: (w.loops() or [{}])[0].get("launched_pid"))
            code, out, err = w.cy("-r", "probe-six")
            self.assertEqual(code, 1)
            self.assertIn("is live in", err)
            code, out, err = w.cy("-n", "probe-six")
            self.assertEqual(code, 1)
            self.assertIn("already live", err)
            os.kill(w.loops()[0]["launched_pid"], signal.SIGTERM)
            p.communicate(timeout=30)

    def test_resume_by_name_after_exit_keeps_the_key_and_conversation(self):
        with World() as w:
            w.cy("-n", "probe-seven", env={"FAKE_CLAUDE_EXIT": "0"})
            sid = w.loops()[0]["id"]
            code, out, err = w.cy("-r", "probe-seven", env={"FAKE_CLAUDE_EXIT": "0"})
            self.assertEqual(code, 0, err)
            second = w.argv()[1]
            self.assertEqual(second[second.index("--resume") + 1], sid)
            self.assertEqual(len(w.loops()), 1)

    def test_branch_opens_a_copy_under_a_new_key(self):
        with World() as w:
            w.cy("-n", "probe-eight", env={"FAKE_CLAUDE_EXIT": "0"})
            sid = w.loops()[0]["id"]
            code, out, err = w.cy("-r", "probe-eight", "--branch", "probe-eight-alt", env={"FAKE_CLAUDE_EXIT": "0"})
            self.assertEqual(code, 0, err)
            argv = w.argv()[1]
            self.assertIn("--fork-session", argv)
            self.assertEqual(argv[argv.index("--resume") + 1], sid)
            self.assertNotEqual(argv[argv.index("--session-id") + 1], sid)
            self.assertEqual(len(w.loops()), 2)

    def test_unknown_name_and_bad_name_are_refused(self):
        with World() as w:
            self.assertEqual(w.cy("-r", "nobody")[0], 1)
            self.assertEqual(w.cy("-n", "Bad Name")[0], 1)

    def test_refuses_inside_a_claude_session(self):
        with World() as w:
            self.assertEqual(w.cy("-n", "x", env={"CLAUDECODE": "1"})[0], 2)

    def test_the_prompt_file_is_read_and_removed(self):
        with World() as w:
            pf = w.home / "prompt.txt"
            pf.write_text("a long prompt with `backticks` and $DOLLARS")
            w.cy("-n", "probe-nine", "--prompt-file", str(pf), env={"FAKE_CLAUDE_EXIT": "0"})
            self.assertEqual(w.argv()[0][-1], "a long prompt with `backticks` and $DOLLARS")
            self.assertFalse(pf.exists())


class StateRule(unittest.TestCase):
    def setUp(self):
        loader = importlib.machinery.SourceFileLoader("cy_rule", str(CY))
        self.cy = importlib.util.module_from_spec(importlib.util.spec_from_loader("cy_rule", loader))
        loader.exec_module(self.cy)

    def turn(self, prompt, reply, **extra):
        return [{"type": "user", "message": {"content": prompt}},
                dict({"type": "assistant", "message": {"content": [{"type": "text", "text": reply}]}}, **extra)]

    def test_the_rows_in_order(self):
        st = self.cy.state_of
        table = "| Needs you | PRs awaiting a review |\n|---|---|\n| 1. Decide the retry window | |\n"
        self.assertEqual(st({"status": "busy"}, [])["state"], "working")
        self.assertEqual(st({"status": "shell"}, [])["state"], "working (background command)")
        self.assertEqual(st({"status": "waiting", "waitingFor": "permission prompt"}, [])["needs"], "permission prompt")
        self.assertEqual(st({"status": "idle"}, self.turn("go", "API Error: 429", isApiErrorMessage=True))["state"],
                         "stopped: API error")
        self.assertEqual(st({"status": "idle"}, self.turn("go", "✅ Nothing left for you: safe to close."))["state"], "done")
        got = st({"status": "idle"}, self.turn("go", table))
        self.assertEqual((got["state"], got["needs"]), ("waiting on you", "Decide the retry window"))
        nothing = "| Needs you | PRs |\n|---|---|\n| Nothing needed from you | |\n"
        self.assertEqual(st({"status": "idle"}, self.turn("go", nothing))["state"], "idle")
        self.assertEqual(st({"status": "idle"}, self.turn("go", "Which one?"))["waiting_kind"], "question")

    def test_a_restart_prompt_never_hides_the_ask(self):
        table = "| Needs you | PRs |\n|---|---|\n| 1. Send the two DRI messages | |\n"
        recs = self.turn("go", table) + self.turn("[cy restart] Restarted at 00:12.", "Re-armed the loop.")
        self.assertEqual(self.cy.state_of({"status": "idle"}, recs)["needs"], "Send the two DRI messages")


class Follower(unittest.TestCase):
    def setup_session(self, w, status="idle"):
        """A live cy session: its loop file, its lock held by the test, a launched process and its registry row."""
        cy = w.module(CY, "cy_t")
        sid = "11111111-2222-3333-4444-555555555555"
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        cy.write_json(cy.loop_file(sid), {"id": sid, "name": "probe-f", "conversations": [sid], "conversation": sid,
                                          "status": "live", "launched_pid": child.pid,
                                          "launched_start": cy.started_at(child.pid), "pane": "w1:p1", "tab": "w1:t1"})
        lock = open(cy.lock_file(sid), "a")
        fcntl.flock(lock, fcntl.LOCK_EX)
        reg = w.home / ".claude" / "sessions"
        reg.mkdir(parents=True, exist_ok=True)
        (reg / f"{child.pid}.json").write_text(json.dumps({"pid": child.pid, "sessionId": sid, "name": "probe-f",
                                                            "status": status, "kind": "interactive"}))
        return cy, sid, child, lock

    def follower(self, w):
        old = os.environ.copy()
        os.environ.update(HOME=str(w.home), PATH=w.env["PATH"])
        try:
            return w.module(FOLLOW, "cy_follow_t"), old
        except Exception:
            os.environ.clear()
            os.environ.update(old)
            raise

    def test_a_restart_waits_for_three_idle_seconds_then_orders_and_signals(self):
        with World() as w:
            cy, sid, child, lock = self.setup_session(w)
            fm, old = self.follower(w)
            try:
                f = fm.Follower()
                req = fm.cy.submit(sid, "restart", {"token": "project"})
                f.tick()
                self.assertTrue(req.exists())  # not idle for 3 s yet
                f.idle_since[sid] = time.time() - 5
                f.tick()
                order = json.loads(fm.cy.next_file(sid).read_text())
                self.assertEqual((order["for_pid"], order["token"], order["conversation"]), (child.pid, "project", sid))
                self.assertEqual(child.wait(timeout=10), -signal.SIGTERM)
                self.assertEqual(fm.cy.result_of(req)["result"], "done")
                self.assertIn("report-agent --source kc-cy --agent claude --state idle w1:p1 -- cy -r probe-f",
                              (w.home / "herdr.log").read_text())
            finally:
                os.environ.clear()
                os.environ.update(old)
                child.kill()
                child.wait()
                lock.close()

    def test_a_busy_session_is_never_interrupted(self):
        with World() as w:
            cy, sid, child, lock = self.setup_session(w, status="busy")
            fm, old = self.follower(w)
            try:
                f = fm.Follower()
                req = fm.cy.submit(sid, "restart", {})
                f.idle_since[sid] = time.time() - 60
                f.tick()
                self.assertTrue(req.exists())
                self.assertIsNone(child.poll())
            finally:
                os.environ.clear()
                os.environ.update(old)
                child.kill()
                child.wait()
                lock.close()

    def test_a_rename_to_a_live_name_is_refused(self):
        with World() as w:
            cy, sid, child, lock = self.setup_session(w)
            fm, old = self.follower(w)
            try:
                f = fm.Follower()
                req = fm.cy.submit(sid, "rename", {"to": "probe-f"})
                f.tick()
                self.assertEqual(fm.cy.result_of(req)["result"], "refused")
                self.assertIsNone(child.poll())
            finally:
                os.environ.clear()
                os.environ.update(old)
                child.kill()
                child.wait()
                lock.close()

    def test_an_expired_request_is_dropped(self):
        with World() as w:
            cy, sid, child, lock = self.setup_session(w)
            fm, old = self.follower(w)
            try:
                req = fm.cy.submit(sid, "retire", {}, not_after=-1)
                fm.Follower().tick()
                self.assertEqual(fm.cy.result_of(req)["result"], "dropped")
            finally:
                os.environ.clear()
                os.environ.update(old)
                child.kill()
                child.wait()
                lock.close()

    def test_moves_and_closes_from_herdr_events(self):
        with World() as w:
            cy, sid, child, lock = self.setup_session(w)
            fm, old = self.follower(w)
            try:
                f = fm.Follower()
                f.tick()
                f.on_event({"event": "pane.moved", "data": {"previous_pane_id": "w1:p1", "pane_id": "w2:p1",
                                                            "workspace_id": "w2"}})
                self.assertEqual(f.view(sid)["pane"], "w2:p1")
                f.on_event({"event": "pane_closed", "data": {"pane_id": "w2:p1"}})
                self.assertEqual(f.view(sid)["end"], "closed")
            finally:
                os.environ.clear()
                os.environ.update(old)
                child.kill()
                child.wait()
                lock.close()

    def test_after_a_herdr_restart_a_kept_pane_is_interrupted(self):
        with World() as w:
            cy = w.module(CY, "cy_t2")
            for sid, pane in (("aaaaaaaa-0000-0000-0000-000000000001", "w1:p2"),
                              ("aaaaaaaa-0000-0000-0000-000000000002", "w1:p9")):
                cy.write_json(cy.loop_file(sid), {"id": sid, "name": sid[-4:], "status": "live", "pane": pane,
                                                  "launched_pid": 999999, "conversations": [sid]})
            fm, old = self.follower(w)
            try:
                f = fm.Follower()
                f.first_pass()
                self.assertEqual(f.view("aaaaaaaa-0000-0000-0000-000000000001")["status"], "interrupted")
                self.assertEqual(f.view("aaaaaaaa-0000-0000-0000-000000000002")["status"], "ended")
            finally:
                os.environ.clear()
                os.environ.update(old)


class Cag(unittest.TestCase):
    def test_json_rows_cover_cy_sessions_plain_claude_and_dormant_jobs(self):
        with World() as w:
            cy = w.module(CY, "cy_t3")
            sid = "bbbbbbbb-0000-0000-0000-000000000001"
            cy.write_json(cy.loop_file(sid), {"id": sid, "name": "probe-g", "status": "ended", "end": "closed",
                                              "conversations": [sid], "ended_at": time.time(), "pane": "w1:p3"})
            reg = w.home / ".claude" / "sessions"
            reg.mkdir(parents=True)
            (reg / f"{os.getpid()}.json").write_text(json.dumps({"pid": os.getpid(), "sessionId": "plain-1",
                                                                  "name": "tracker", "status": "idle",
                                                                  "kind": "interactive"}))
            job = w.home / ".claude" / "jobs" / "cafe0001"
            job.mkdir(parents=True)
            (job / "state.json").write_text(json.dumps({"name": "support-nelson", "state": "blocked",
                                                         "sessionId": "dorm-1", "cwd": "/x"}))
            p = subprocess.run([sys.executable, str(CAG), "--json"], env=w.env, capture_output=True, text=True)
            rows = {r["name"]: r for r in json.loads(p.stdout)}
            self.assertEqual(rows["probe-g"]["state"], "ended: window closed")
            self.assertEqual(rows["probe-g"]["needs"], "cy -r probe-g")
            self.assertIn("not started by cy", rows["tracker"]["flags"])
            self.assertEqual(rows["support-nelson"]["kind"], "dormant")
            for field in ("waiting_kind", "pinned", "prs", "intent", "last_reply_at", "conversation_ids",
                          "first_conversation_id", "transcript", "pending_requests"):
                self.assertIn(field, rows["probe-g"])

    def test_restart_queues_a_request_for_the_follower(self):
        with World() as w:
            cy = w.module(CY, "cy_t4")
            sid = "cccccccc-0000-0000-0000-000000000001"
            cy.write_json(cy.loop_file(sid), {"id": sid, "name": "probe-h", "status": "live", "conversations": [sid]})
            env = dict(w.env, CLAUDECODE="1")  # inside a session: queue, but start no follower
            p = subprocess.run([sys.executable, str(CAG), "restart", "probe-h", "--now", "--token", "project"],
                               env=env, capture_output=True, text=True, timeout=30)
            self.assertIn("queued restart of probe-h", p.stdout)
            req = next((w.state / "requests" / sid).glob("*-restart.json"))
            self.assertEqual(json.loads(req.read_text())["body"], {"now": True, "token": "project"})


class Hook(unittest.TestCase):
    def run_hook(self, home, data):
        env = dict(os.environ, HOME=str(home))
        subprocess.run([sys.executable, str(HOOK)], input=json.dumps(data), text=True, env=env, check=True)
        return home / ".local" / "state" / "cy" / "crons"

    def test_stop_saves_the_crons_and_a_failure_leaves_them(self):
        with tempfile.TemporaryDirectory() as t:
            crons = [{"id": "d1e4", "schedule": "*/2 * * * *", "prompt": "tick"}]
            out = self.run_hook(Path(t), {"hook_event_name": "Stop", "session_id": "s1", "session_crons": crons})
            self.assertEqual(json.loads((out / "s1.json").read_text())["session_crons"], crons)
            self.run_hook(Path(t), {"hook_event_name": "StopFailure", "session_id": "s1"})
            self.assertEqual(json.loads((out / "s1.json").read_text())["session_crons"], crons)


if __name__ == "__main__":
    unittest.main()
