"""Tests for the stella helper, against fake-claude in a temporary HOME. Nothing real is started or touched.

    python3 -m unittest discover -s claude/tests
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STELLA = REPO / "claude/bin/stella"
FAKE = REPO / "claude/tests/fake-claude"
FAKE_HERDR = REPO / "claude/tests/fake-herdr"
PR = "https://github.example.com/acme/widgets/pull/2428"


class Helper(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.home = Path(self.t.name)
        self.bin = self.home / "bin"
        self.bin.mkdir()
        (self.bin / "claude").symlink_to(FAKE)
        self.sh = self.home / ".local/share/stella"
        (self.sh / "crew").mkdir(parents=True)
        self.tokens = self.home / ".local/state/claude-token/sessions"
        self.tokens.mkdir(parents=True)
        self.log = self.home / "calls.jsonl"
        self.agents = self.home / "agents.json"
        self.set_agents([{"id": "aaaaaaaa", "name": "stella", "kind": "background", "state": "working",
                          "sessionId": "aaaaaaaa-0000-0000-0000-000000000000"}])
        (self.tokens / "aaaaaaaa-0000-0000-0000-000000000000").write_text("personal\n")
        self.work = self.home / "github/demo"
        self.work.mkdir(parents=True)
        self.gh_state = self.home / "gh-state"  # what the fake `gh pr view` prints; absent = no PR
        (self.bin / "gh").write_text(f"#!/bin/sh\ncat {self.gh_state} 2>/dev/null || exit 1\n")
        (self.bin / "gh").chmod(0o755)
        self.herdr_tabs = self.home / "herdr-tabs.json"
        self.herdr_log = self.home / "herdr.jsonl"

    extra_env: dict = {}

    def with_herdr(self):
        (self.bin / "herdr").symlink_to(FAKE_HERDR)

    def tabs(self):
        return json.loads(self.herdr_tabs.read_text()) if self.herdr_tabs.exists() else {}

    def workspaces(self):
        ws = Path(str(self.herdr_tabs) + ".ws")
        return json.loads(ws.read_text()) if ws.exists() else {}

    def sidebar(self):
        """{workspace label: [tab labels]} of the crew workspaces ("└ <name>") fake-herdr holds."""
        return {label: [n for t, n in self.tabs().items() if t.startswith(w + ":")]
                for w, label in self.workspaces().items() if label.startswith("└ ")}

    def herdr_calls(self, *head):
        calls = [json.loads(l) for l in self.herdr_log.read_text().splitlines()] if self.herdr_log.exists() else []
        return [c for c in calls if c[:len(head)] == list(head)]

    def pr_is(self, state):
        self.gh_state.write_text(json.dumps({"state": state, "url": PR}))

    def tearDown(self):
        self.t.cleanup()

    def set_agents(self, rows):
        self.agents.write_text(json.dumps(rows))

    def run_stella(self, *args, cwd=None):
        env = {"HOME": str(self.home), "STELLA_PATH": f"{self.bin}:/usr/bin:/bin", "FAKE_CLAUDE_LOG": str(self.log),
               "FAKE_CLAUDE_AGENTS": str(self.agents), "FAKE_HERDR_LOG": str(self.herdr_log),
               "FAKE_HERDR_TABS": str(self.herdr_tabs), "STELLA_FOLLOW_GRACE": "0.2",
               "STELLA_FOLLOW_WAIT": "3", **self.extra_env}
        return subprocess.run(["python3", str(STELLA), *args], cwd=cwd or self.sh, env=env,
                              capture_output=True, text=True, timeout=30)

    def calls(self):
        return [json.loads(l)["argv"] for l in self.log.read_text().splitlines()] if self.log.exists() else []

    def crew(self, name, **rec):
        d = self.sh / "crew" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "brief.md").write_text("/kc-dev fix the thing\n")
        (d / "record.json").write_text(json.dumps({"name": name, "dir": str(self.work), **rec}))

    def rec(self, name):
        return json.loads((self.sh / "crew" / name / "record.json").read_text())

    # -------------------------------------------------------------- launch

    def test_launch_inherits_stellas_token_and_records_the_session(self):
        self.crew("fix-flake", model="sonnet", weight=0.5)
        p = self.run_stella("launch", "fix-flake")
        self.assertEqual(p.returncode, 0, p.stderr)
        rec = self.rec("fix-flake")
        self.assertEqual(rec["state"], "working")
        self.assertEqual((self.tokens / rec["session"]).read_text(), "personal\n")
        bg = [c for c in self.calls() if "--bg" in c][0]
        # the daemon ignores --session-id: the record holds the session it really started
        self.assertNotEqual(bg[bg.index("--session-id") + 1], rec["session"])
        listed = {a["name"]: a for a in json.loads(self.agents.read_text())}
        self.assertEqual(rec["session"], listed["fix-flake"]["sessionId"])
        self.assertEqual(rec["id"], listed["fix-flake"]["id"])
        self.assertIn("--model", bg)
        self.assertEqual(bg[-2:], ["--", "/kc-dev fix the thing\n"])

    def test_launch_turns_the_security_flag_into_the_security_boundary_activity(self):
        self.crew("fix-flake", security=True, allow=["push"])
        self.assertEqual(self.run_stella("launch", "fix-flake").returncode, 0)
        rec = self.rec("fix-flake")
        self.assertEqual(rec["allow"], ["push", "security-boundary"])
        self.assertNotIn("security", rec)

    def test_allow_sets_and_clears_the_activities_of_a_record(self):
        self.crew("fix-flake")
        self.assertEqual(self.run_stella("allow", "fix-flake", "push").returncode, 0)
        self.assertEqual(self.rec("fix-flake")["allow"], ["push"])
        self.assertNotEqual(self.run_stella("allow", "fix-flake", "rm-rf").returncode, 0)
        self.assertEqual(self.rec("fix-flake")["allow"], ["push"])
        self.assertEqual(self.run_stella("allow", "fix-flake", "--none").returncode, 0)
        self.assertEqual(self.rec("fix-flake")["allow"], [])

    def test_second_launch_of_a_running_crewmate_is_refused(self):
        self.crew("fix-flake")
        self.assertEqual(self.run_stella("launch", "fix-flake").returncode, 0)
        sid = self.rec("fix-flake")["id"]
        self.set_agents([{"id": "aaaaaaaa", "name": "stella", "kind": "background", "state": "working",
                          "sessionId": "aaaaaaaa-0000-0000-0000-000000000000"},
                         {"id": sid, "name": "fix-flake", "kind": "background", "state": "working"}])
        self.assertNotEqual(self.run_stella("launch", "fix-flake").returncode, 0)
        self.assertEqual(len([c for c in self.calls() if "--bg" in c]), 1)

    def test_adopt_by_a_name_with_a_dot_or_spaces(self):
        self.set_agents([{"id": "cccccccc", "name": "workenv-3.0", "kind": "background", "state": "blocked",
                          "sessionId": "cccccccc-1"},
                         {"id": "dddddddd", "name": "stella cli retirement", "kind": "background", "state": "done",
                          "sessionId": "dddddddd-1"}])
        self.assertEqual(self.run_stella("adopt", "workenv-3.0").returncode, 0)
        self.assertEqual(self.run_stella("adopt", "stella cli retirement").returncode, 0)
        self.assertEqual(self.run_stella("adopt", "a;b").returncode, 2)

    def test_adopt_resume_brings_back_an_unlisted_session(self):
        sid = "084c5838-32d1-4d90-a787-d42cbe45cdee"
        proj = self.home / ".claude/projects/-x"
        proj.mkdir(parents=True)
        (proj / f"{sid}.jsonl").write_text(json.dumps({"cwd": str(self.work)}) + "\n")
        p = self.run_stella("adopt", "--resume", sid, "phase-10")
        self.assertEqual(p.returncode, 0, p.stderr)
        rec = self.rec("phase-10")
        self.assertTrue(rec["adopted"])
        self.assertEqual(rec["resumed_from"], sid)
        bg = [c for c in self.calls() if "--resume" in c][0]
        self.assertEqual(bg[bg.index("--resume") + 1], sid)
        self.assertNotEqual(self.run_stella("adopt", "--resume", sid, "phase-10").returncode, 0)
        self.assertNotEqual(self.run_stella("adopt", "--resume", "not-a-uuid", "x").returncode, 0)

    def test_adopt_never_takes_stella_or_a_prefix(self):
        self.assertNotEqual(self.run_stella("adopt", "stella").returncode, 0)
        self.assertNotEqual(self.run_stella("adopt", "aaaaaa").returncode, 0)
        self.assertNotEqual(self.run_stella("adopt", "aaaaaaaa").returncode, 0)

    def test_launch_only_from_stellas_home(self):
        self.crew("fix-flake")
        p = self.run_stella("launch", "fix-flake", cwd=self.work)
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(any("--bg" in c for c in self.calls()))

    def test_launch_rejects_bad_names_and_dirs(self):
        self.assertEqual(self.run_stella("launch", "a;b").returncode, 2)
        self.crew("outside", dir="/etc")
        self.assertEqual(self.run_stella("launch", "outside").returncode, 2)

    def test_slot_cap_queues(self):
        rows = [{"id": "aaaaaaaa", "name": "stella", "kind": "background", "state": "working",
                 "sessionId": "aaaaaaaa-0000-0000-0000-000000000000"}]
        for i in range(6):
            sid = f"{i:08x}"
            self.crew(f"busy-{i}", id=sid, session=sid + "-x", state="working")
            rows.append({"id": sid, "name": f"busy-{i}", "kind": "background", "state": "working",
                         "sessionId": sid + "-x"})
        self.set_agents(rows)
        self.crew("seventh")
        p = self.run_stella("launch", "seventh")
        self.assertEqual(p.returncode, 75, p.stderr)
        self.assertEqual(self.rec("seventh")["state"], "queued")

    def test_opus_weight_cap_and_throttle_and_budget(self):
        rows = [{"id": "aaaaaaaa", "name": "stella", "kind": "background", "state": "working",
                 "sessionId": "aaaaaaaa-0000-0000-0000-000000000000"}]
        for i in range(2):
            sid = f"{i + 10:08x}"
            self.crew(f"review-{i}", id=sid, session=sid + "-x", weight=2)
            rows.append({"id": sid, "name": f"review-{i}", "kind": "background", "state": "working",
                         "sessionId": sid + "-x"})
        self.set_agents(rows)
        self.crew("third-review", weight=2)
        self.assertEqual(self.run_stella("launch", "third-review").returncode, 75)
        self.crew("docs", weight=0)
        self.assertEqual(self.run_stella("launch", "docs").returncode, 0)
        self.set_agents(rows[:1])
        (self.sh / "throttle-until").write_text(json.dumps({"until": time.time() + 200}))
        self.crew("opus-job", weight=1)
        self.assertEqual(self.run_stella("launch", "opus-job").returncode, 75)
        (self.sh / "throttle-until").unlink()
        (self.sh / "quota.json").write_text(json.dumps({"fraction": 0.9}))
        self.crew("any-job", weight=0)
        self.assertEqual(self.run_stella("launch", "any-job").returncode, 75)

    def test_budget_gate_applies_only_to_the_token_it_measures(self):
        (self.sh / "quota.json").write_text(json.dumps({"fraction": 0.96, "token": "personal"}))
        self.crew("on-personal", weight=0)
        self.assertEqual(self.run_stella("launch", "on-personal").returncode, 75)
        (self.tokens / "aaaaaaaa-0000-0000-0000-000000000000").write_text("project\n")
        self.crew("on-project", weight=0)
        self.assertEqual(self.run_stella("launch", "on-project").returncode, 0)

    # -------------------------------------------------------------- adopt / lifecycle

    def test_adopt_is_observation_only(self):
        self.set_agents([{"id": "bbbbbbbb", "name": "pr-2332-include-consistency", "kind": "background",
                          "state": "blocked", "sessionId": "bbbbbbbb-1", "cwd": "/x"}])
        p = self.run_stella("adopt", "pr-2332-include-consistency")
        self.assertEqual(p.returncode, 0, p.stderr)
        rec = self.rec("pr-2332-include-consistency")
        self.assertTrue(rec["adopted"])
        self.assertEqual([c for c in self.calls() if c[:1] != ["agents"]], [])
        for cmd in ("stop", "respawn", "rm"):
            self.assertNotEqual(self.run_stella(cmd, "pr-2332-include-consistency").returncode, 0)
        self.assertEqual([c for c in self.calls() if c[:1] != ["agents"]], [])

    def test_rm_refuses_a_directory_that_is_not_a_checkout(self):
        self.crew("loose", id="eeeeeeee", mode="local")
        p = self.run_stella("rm", "loose")
        self.assertEqual(p.returncode, 1)
        self.assertIn("not a git checkout", p.stderr)

    def test_rm_refuses_unlanded_work(self):
        subprocess.run(["git", "init", "-q", str(self.work)], check=True)
        subprocess.run(["git", "-C", str(self.work), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "--allow-empty", "-m", "x"], check=True)
        self.crew("unpushed", id="cccccccc", mode="local")
        p = self.run_stella("rm", "unpushed")
        self.assertEqual(p.returncode, 1)
        self.assertIn("never pushed", p.stderr)
        self.assertFalse(any(c[:1] == ["rm"] for c in self.calls()))

    def test_scout_rm_needs_report(self):
        self.crew("investigate", id="dddddddd", mode="scout", report=str(self.home / "r.md"))
        self.assertEqual(self.run_stella("rm", "investigate").returncode, 1)
        (self.home / "r.md").write_text("findings")
        self.assertEqual(self.run_stella("rm", "investigate").returncode, 0)
        self.assertIn(["rm", "dddddddd"], self.calls())

    def test_restart_stops_then_resumes_with_the_start_prompt(self):
        self.set_agents([{"id": "aaaaaaaa", "name": "stella", "kind": "background", "state": "working", "pid": 42,
                          "sessionId": "aaaaaaaa-0000-0000-0000-000000000000"}])
        p = self.run_stella("restart")
        self.assertEqual(p.returncode, 0, p.stderr)
        calls = [c for c in self.calls() if c[:1] != ["agents"]]
        self.assertEqual(calls[0], ["stop", "aaaaaaaa"])
        resume = calls[1]
        self.assertEqual(resume[resume.index("--resume") + 1], "aaaaaaaa-0000-0000-0000-000000000000")
        self.assertIn("--agent", resume)
        self.assertEqual(resume[-2], "--")
        self.assertIn("start-of-session", resume[-1])

    def test_restart_of_a_stopped_stella_only_resumes(self):
        self.set_agents([{"id": "aaaaaaaa", "name": "stella", "kind": "background", "state": "done",
                          "sessionId": "aaaaaaaa-0000-0000-0000-000000000000"}])
        self.assertEqual(self.run_stella("restart").returncode, 0)
        calls = [c for c in self.calls() if c[:1] != ["agents"]]
        self.assertFalse(any(c[:1] == ["stop"] for c in calls))
        self.assertTrue(any("--resume" in c for c in calls))

    def test_restart_with_no_stella_starts_her(self):
        self.set_agents([])
        self.run_stella("restart")
        self.assertTrue(any("--bg" in c and "--resume" not in c and "stella" in c for c in self.calls()))

    # -------------------------------------------------------------- A: an open PR keeps the session

    def test_rm_keeps_a_session_whose_pr_is_open(self):
        for mode in ("local", "scout", "ship"):
            self.crew(f"open-{mode}", id="abababab", mode=mode, pr=PR, report=str(self.home / "r.md"))
            (self.home / "r.md").write_text("findings")
            self.pr_is("OPEN")
            p = self.run_stella("rm", f"open-{mode}")
            self.assertEqual(p.returncode, 1, mode)
            self.assertIn("still open", p.stderr)
        self.assertFalse(any(c[:1] == ["rm"] for c in self.calls()))

    def test_rm_looks_up_the_branch_pr_when_the_record_has_none(self):
        self.pr_is("OPEN")
        self.crew("by-branch", id="abababab", mode="scout", report=str(self.home / "r.md"))
        (self.home / "r.md").write_text("findings")
        self.assertIn("still open", self.run_stella("rm", "by-branch").stderr)
        self.pr_is("MERGED")
        self.assertEqual(self.run_stella("rm", "by-branch").returncode, 0)

    # -------------------------------------------------------------- B: pr is a full URL

    def test_launch_refuses_a_short_pr_reference(self):
        for bad in ("acme/widgets#2398", "http://h/o/r/pull/1", "https://h/o/r/pull/x", "https://h/o/r/issues/3"):
            self.crew("short-pr", pr=bad)
            p = self.run_stella("launch", "short-pr")
            self.assertEqual(p.returncode, 2, bad)
            self.assertIn("full URL", p.stderr)
        self.assertFalse(any("--bg" in c for c in self.calls()))
        self.crew("full-pr", pr=PR)
        self.assertEqual(self.run_stella("launch", "full-pr").returncode, 0)

    # -------------------------------------------------------------- C: track-pr

    def test_track_pr_writes_one_shape_of_record(self):
        p = self.run_stella("track-pr", PR)
        self.assertEqual(p.returncode, 0, p.stderr)
        rec = self.rec("track-widgets-2428")
        self.assertEqual((rec["mode"], rec["state"], rec["pr"]), ("track", "watching", PR))
        self.assertNotIn("session", rec)
        self.assertEqual(rec["watches"][0]["command"],
                         ["gh", "pr", "view", PR, "--json", "state,reviewDecision,statusCheckRollup"])
        self.assertEqual(self.run_stella("track-pr", PR).returncode, 2)  # already tracked
        self.assertEqual(self.run_stella("track-pr", "acme/widgets#2428").returncode, 2)
        self.assertEqual(self.run_stella("track-pr", PR, "two").returncode, 0)
        self.assertEqual(self.rec("two")["pr"], PR)

    def test_untrack_and_rm_of_a_track_record(self):
        self.run_stella("track-pr", PR)
        self.pr_is("OPEN")
        p = self.run_stella("rm", "track-widgets-2428")
        self.assertEqual(p.returncode, 1)
        self.assertIn("still OPEN", p.stderr)
        self.pr_is("MERGED")
        self.assertEqual(self.run_stella("rm", "track-widgets-2428").returncode, 0)
        self.assertEqual(self.rec("track-widgets-2428")["state"], "landed")
        self.assertEqual(self.run_stella("track-pr", PR).returncode, 0)  # a landed one can be tracked again
        self.pr_is("OPEN")
        self.assertEqual(self.run_stella("untrack", "track-widgets-2428").returncode, 0)
        self.assertEqual(self.rec("track-widgets-2428")["state"], "landed")
        self.crew("not-a-track")
        self.assertEqual(self.run_stella("untrack", "not-a-track").returncode, 2)

    # -------------------------------------------------------------- D, G: herdr tabs

    def live(self, *names):
        rows = [{"id": "aaaaaaaa", "name": "stella", "kind": "background", "state": "working",
                 "sessionId": "aaaaaaaa-0000-0000-0000-000000000000"}]
        for i, n in enumerate(names):
            rows.append({"id": f"{i + 1:08x}", "name": n, "kind": "background", "state": "working",
                         "sessionId": f"{i + 1:08x}-s"})
        self.set_agents(rows)

    def test_crew_sync_gives_each_live_session_its_own_workspace_adopted_included_and_no_tab_in_the_work_window(self):
        self.with_herdr()
        self.live("built", "adopted-one")
        self.crew("built", id="00000001", project="mlc")
        self.crew("adopted-one", id="00000002", adopted=True)
        self.herdr_tabs.write_text(json.dumps({"w1:t1": "stella"}))
        Path(str(self.herdr_tabs) + ".ws").write_text(json.dumps({"w1": "work"}))
        self.assertEqual(self.run_stella("crew", "sync").returncode, 0)
        self.assertEqual(self.sidebar(), {"└ mlc · built": ["fm-built"], "└ adopted-one": ["fm-adopted-one"]})
        self.assertEqual([t for t in self.tabs() if t.startswith("w1:")], ["w1:t1"])  # the work window gained no tab
        creates = self.herdr_calls("workspace", "create")
        self.assertEqual(len(creates), 2)
        self.assertIn("--no-focus", creates[0])
        self.assertEqual(self.rec("built")["crew_ws"], [w for w, n in self.workspaces().items() if n == "└ mlc · built"][0])
        runs = self.herdr_calls("pane", "run")
        self.assertEqual(sorted(r[3].split("claude attach ")[1].split(";")[0] for r in runs), ["00000001", "00000002"])
        self.run_stella("crew", "sync")  # a second run opens nothing new
        self.assertEqual(len(self.herdr_calls("workspace", "create")), 2)

    def test_crew_sync_moves_a_new_workspace_after_the_work_workspace_and_its_crew(self):
        import socket
        import threading
        self.with_herdr()
        self.live("first", "second")
        self.crew("first", id="00000001")
        self.crew("second", id="00000002")
        self.herdr_tabs.write_text(json.dumps({"w1:t1": "stella", "w2:t1": "scratch"}))
        Path(str(self.herdr_tabs) + ".ws").write_text(json.dumps({"w1": "work", "w2": "scratch"}))
        sock_path = str(self.home / "h.sock")
        got = []
        srv = socket.socket(socket.AF_UNIX)
        try:
            srv.bind(sock_path)
        except PermissionError:
            self.skipTest("the command sandbox forbids binding a Unix socket; run this test outside it")
        srv.listen(4)

        def serve():
            while True:
                try:
                    c, _ = srv.accept()
                except OSError:
                    return
                req = json.loads(c.makefile().readline())
                got.append(req["params"])
                c.sendall((json.dumps({"id": req["id"], "result": {"type": "workspace_list"}}) + "\n").encode())
                c.close()

        threading.Thread(target=serve, daemon=True).start()
        self.extra_env = {"FAKE_HERDR_SOCKET": sock_path}
        try:
            self.run_stella("crew", "sync")
        finally:
            srv.close()
        # the fake lists workspaces in creation order: work, scratch, first, second. `first` goes to index 1,
        # right after work; `second` then goes to 2, ahead of scratch (the fake socket does not really move)
        self.assertEqual([g["insert_index"] for g in got], [1, 2])
        self.assertEqual(got[0]["workspace_id"], [w for w, n in self.workspaces().items() if n == "└ first"][0])

    def test_crew_sync_labels_with_the_project_and_orders_by_priority_then_alphabet_and_is_idempotent(self):
        self.with_herdr()
        (self.home / ".local/share/stella").mkdir(parents=True, exist_ok=True)
        (self.home / ".local/share/stella/priorities.md").write_text(
            "# P\n\n1. **Infer.** Crew: zeta-crew.\n2. **Other.** project beta.\n")
        self.live("zeta-crew", "a-beta", "b-alpha", "loose")
        self.crew("zeta-crew", id="00000001", project="gamma")
        self.crew("a-beta", id="00000002", project="beta")
        self.crew("b-alpha", id="00000003", project="alpha")
        self.crew("loose", id="00000004")
        self.herdr_tabs.write_text(json.dumps({"w1:t1": "stella", "w2:t1": "scratch"}))
        Path(str(self.herdr_tabs) + ".ws").write_text(json.dumps({"w1": "stella", "w2": "scratch"}))
        self.run_stella("crew", "sync")
        labels = sorted(self.workspaces().values())
        self.assertEqual(labels, sorted(["stella", "scratch", "└ gamma · zeta-crew", "└ beta · a-beta",
                                         "└ alpha · b-alpha", "└ loose"]))
        d = json.loads(self.run_stella("crew", "doctor", "--json").stdout)
        by = {c["crewmate"]: c for c in d["checks"] if "crewmate" in c}
        self.assertTrue(all(c["label_ok"] for c in by.values()))
        # a stale label (no project) is renamed once; a second run renames and creates nothing
        ws = [w for w, n in self.workspaces().items() if n == "└ gamma · zeta-crew"][0]
        Path(str(self.herdr_tabs) + ".ws").write_text(json.dumps({**self.workspaces(), ws: "└ zeta-crew"}))
        before = len(self.herdr_calls("workspace", "rename"))
        self.run_stella("crew", "sync")
        self.assertEqual(len(self.herdr_calls("workspace", "rename")), before + 1)
        self.run_stella("crew", "sync")
        self.assertEqual(len(self.herdr_calls("workspace", "rename")), before + 1)
        self.assertEqual(len(self.herdr_calls("workspace", "create")), 4)
        self.assertEqual(self.workspaces()[ws], "└ gamma · zeta-crew")
        self.assertEqual(self.workspaces()["w2"], "scratch")

    def test_crew_sort_puts_prioritised_projects_first_then_alphabetical_and_no_project_last(self):
        import importlib.machinery
        import importlib.util
        loader = importlib.machinery.SourceFileLoader("stella_mod", str(STELLA))
        spec = importlib.util.spec_from_loader("stella_mod", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        (self.home / ".local/share/stella").mkdir(parents=True, exist_ok=True)
        mod.STELLA_HOME = self.home / ".local/share/stella"
        (mod.STELLA_HOME / "priorities.md").write_text("1. one\n2. project zed and crew m2\n")
        recs = [{"name": "n1", "project": "alpha"}, {"name": "m2", "project": "mid"}, {"name": "x"},
                {"name": "m1", "project": "mid"}, {"name": "z", "project": "zed"}, {"name": "b", "project": "beta"}]
        self.assertEqual([r["name"] for r in mod.crew_sort(recs)], ["m1", "m2", "z", "n1", "b", "x"])

    def test_crew_sync_renames_the_work_workspace_to_stella(self):
        self.with_herdr()
        self.live("built")
        self.crew("built", id="00000001")
        self.herdr_tabs.write_text(json.dumps({"w1:t1": "stella"}))
        Path(str(self.herdr_tabs) + ".ws").write_text(json.dumps({"w1": "work"}))
        self.run_stella("crew", "sync")
        self.assertEqual(self.herdr_calls("workspace", "rename"), [["workspace", "rename", "w1", "stella"]])

    def test_crew_sync_works_when_the_socket_is_out_of_reach(self):
        self.with_herdr()
        self.live("built")
        self.crew("built", id="00000001")
        self.herdr_tabs.write_text(json.dumps({"w1:t1": "stella", "w2:t1": "scratch"}))
        Path(str(self.herdr_tabs) + ".ws").write_text(json.dumps({"w1": "work", "w2": "scratch"}))
        self.extra_env = {"FAKE_HERDR_SOCKET": str(self.home / "nothing.sock")}
        self.assertEqual(self.run_stella("crew", "sync").returncode, 0)
        self.assertEqual(self.sidebar(), {"└ built": ["fm-built"]})  # ordering is best effort

    def test_crew_sync_retires_the_workspace_of_the_first_sidebar_version(self):
        self.with_herdr()
        self.live("built")
        self.crew("built", id="00000001")
        self.herdr_tabs.write_text(json.dumps({"w1:t1": "stella", "w10:t1": "built", "w10:t2": "built-too"}))
        Path(str(self.herdr_tabs) + ".ws").write_text(json.dumps({"w1": "work", "w10": "crew"}))
        self.crew("built-too", id="00000009", state="landed")
        self.run_stella("crew", "sync")
        self.assertNotIn("crew", self.workspaces().values())
        self.assertEqual(list(self.sidebar()), ["└ built"])
        # a tab of Kohen's in it keeps it
        self.herdr_tabs.write_text(json.dumps({"w1:t1": "stella", "w11:t1": "kohens-own"}))
        Path(str(self.herdr_tabs) + ".ws").write_text(json.dumps({"w1": "work", "w11": "crew"}))
        self.run_stella("crew", "sync")
        self.assertIn("crew", self.workspaces().values())

    def test_the_crew_pane_runs_claude_attach_itself_in_a_loop_while_the_session_is_listed(self):
        self.with_herdr()
        self.live("built")
        self.crew("built", id="00000001")
        self.run_stella("crew", "sync")
        cmd = self.herdr_calls("pane", "run")[0][3]
        self.assertRegex(cmd, r"^while .*/stella listed 00000001; do claude attach 00000001; sleep 2; done$")
        self.assertEqual(self.run_stella("listed", "00000001").returncode, 0)
        self.assertEqual(self.run_stella("listed", "000000ff").returncode, 1)

    def test_an_undetected_crew_pane_is_registered_as_a_claude_agent_and_released_once_herdr_sees_it(self):
        self.with_herdr()
        self.live("built")
        self.crew("built", id="00000001")
        self.extra_env = {"FAKE_HERDR_AGENTS": "[]"}
        self.run_stella("crew", "sync")  # opens the workspace
        self.run_stella("crew", "sync")  # the pane exists now and herdr lists no agent in it
        rep = self.herdr_calls("pane", "report-agent")
        self.assertEqual(len(rep), 1)
        self.assertEqual(rep[0][2:6], [rep[0][2], "--source", "stella", "--agent"])
        self.assertIn("claude", rep[0])
        self.assertTrue(self.rec("built")["reported"])
        pane = rep[0][2]
        self.extra_env = {"FAKE_HERDR_AGENTS": json.dumps([pane])}
        self.run_stella("crew", "sync")
        self.assertEqual(len(self.herdr_calls("pane", "release-agent")), 1)
        self.assertNotIn("reported", self.rec("built"))

    def test_an_undetected_pane_of_an_earlier_version_is_restarted_once_with_the_new_command(self):
        self.with_herdr()
        self.live("built")
        self.crew("built", id="00000001", crew_ws="w10")
        self.herdr_tabs.write_text(json.dumps({"w10:t1": "fm-built"}))
        Path(str(self.herdr_tabs) + ".ws").write_text(json.dumps({"w10": "└ built"}))
        self.extra_env = {"FAKE_HERDR_AGENTS": "[]"}
        self.run_stella("crew", "sync")
        self.assertEqual(self.herdr_calls("pane", "send-keys"), [["pane", "send-keys", "w10:t1:p1", "ctrl+c"]])
        self.assertIn("claude attach 00000001", self.herdr_calls("pane", "run")[-1][3])
        self.run_stella("crew", "sync")  # once only
        self.assertEqual(len(self.herdr_calls("pane", "send-keys")), 1)

    def test_crew_doctor_fails_a_live_crewmate_whose_pane_is_not_an_agent_and_says_why(self):
        self.with_herdr()
        self.live("built")
        self.crew("built", id="00000001")
        self.herdr_tabs.write_text(json.dumps({"w1:t1": "stella"}))
        Path(str(self.herdr_tabs) + ".ws").write_text(json.dumps({"w1": "stella"}))
        self.run_stella("crew", "sync")
        self.assertNotIn("BAD", self.run_stella("crew", "doctor").stdout)
        self.extra_env = {"FAKE_HERDR_AGENTS": "[]"}
        r = self.run_stella("crew", "doctor")
        self.assertIn("BAD", r.stdout)
        d = json.loads(self.run_stella("crew", "doctor", "--json").stdout)
        check = [c for c in d["checks"] if c.get("crewmate") == "built"][0]
        self.assertFalse(check["agent_listed"])
        self.assertEqual(sorted(next(iter(check["diagnostics"].values()))), ["explain", "get", "process_info", "screen"])

    def test_crew_doctor_reports_workspaces_checks_and_raw_json(self):
        self.with_herdr()
        self.live("built", "stray")
        self.crew("built", id="00000001")
        self.crew("stray", id="00000002")
        self.herdr_tabs.write_text(json.dumps({"w1:t1": "stella"}))
        Path(str(self.herdr_tabs) + ".ws").write_text(json.dumps({"w1": "work"}))
        self.run_stella("crew", "sync")
        r = self.run_stella("crew", "doctor")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("└ built", r.stdout)
        self.assertNotIn("BAD", r.stdout)
        d = json.loads(self.run_stella("crew", "doctor", "--json").stdout)
        self.assertEqual({c["crewmate"] for c in d["checks"] if "crewmate" in c}, {"built", "stray"})
        self.assertIn("workspaces", d["raw"])
        # a live crewmate whose workspace is missing is reported
        Path(str(self.herdr_tabs) + ".ws").write_text(json.dumps({"w1": "work"}))
        self.assertIn("BAD", self.run_stella("crew", "doctor").stdout)
        self.assertEqual(self.herdr_calls("workspace", "close"), [])  # doctor changes nothing



    def test_crew_sync_without_a_herdr_server_says_so_and_opens_nothing(self):
        self.with_herdr()
        self.live("built")
        self.crew("built", id="00000001")
        self.extra_env = {"FAKE_HERDR_DOWN": "1"}
        r = self.run_stella("crew", "sync")
        self.assertEqual(r.returncode, 0)
        self.assertIn("not running", r.stdout)
        self.assertEqual(self.herdr_calls("tab", "create"), [])
        self.assertEqual(self.herdr_calls("workspace", "create"), [])

    def test_rm_takes_the_crewmate_out_of_the_sidebar(self):
        self.with_herdr()
        self.live("done-one")
        self.crew("done-one", id="00000001", mode="scout", report=str(self.home / "r.md"))
        (self.home / "r.md").write_text("findings")
        self.run_stella("view", "done-one")
        self.assertEqual(self.sidebar(), {"└ done-one": ["fm-done-one"]})
        self.assertEqual(self.run_stella("rm", "done-one").returncode, 0)
        self.assertEqual(self.tabs(), {})
        self.assertEqual(self.workspaces(), {})
        self.assertNotIn("crew_ws", self.rec("done-one"))

    def test_rm_finds_a_tab_by_its_label_when_the_record_has_no_id_of_it(self):
        self.with_herdr()
        self.herdr_tabs.write_text(json.dumps({"w1:t7": "old-one", "w1:t8": "keep"}))
        self.crew("old-one", id="00000001", mode="scout", report=str(self.home / "r.md"))
        (self.home / "r.md").write_text("findings")
        self.assertEqual(self.run_stella("rm", "old-one").returncode, 0)
        self.assertEqual(self.tabs(), {"w1:t8": "keep"})

    def test_crew_sync_closes_the_workspace_of_sessions_that_exited_for_good(self):
        self.with_herdr()
        self.live("alive")  # `gone` is not listed at all; `landed-one` is listed but its record is landed
        self.crew("alive", id="00000001")
        self.crew("gone", id="000000f1")
        self.crew("landed-one", id="00000002", state="landed")
        self.herdr_tabs.write_text(json.dumps({"w10:t1": "fm-alive", "w11:t1": "fm-gone", "w12:t1": "fm-landed-one",
                                               "w13:t1": "kohens-own", "w1:t1": "gone"}))
        Path(str(self.herdr_tabs) + ".ws").write_text(json.dumps(
            {"w1": "work", "w10": "└ alive", "w11": "└ gone", "w12": "└ landed-one", "w13": "kohens-own-ws"}))
        self.run_stella("crew", "sync")
        self.assertEqual(sorted(self.workspaces().values()), ["kohens-own-ws", "stella", "└ alive"])
        self.assertEqual(sorted(self.tabs().items()), [("w10:t1", "fm-alive"), ("w13:t1", "kohens-own"), ("w1:t1", "gone")])

    # -------------------------------------------------------------- tabs follow their session

    def running(self, pid=100, **row):
        self.set_agents([{"id": "00000001", "name": "built", "kind": "background", "state": "working",
                          "sessionId": "00000001-s", "pid": pid, "startedAt": 1000, **row}])

    def attaches(self):
        return [c for c in self.calls() if c[:1] == ["attach"]]

    def test_tab_attaches_again_after_the_process_restarts(self):
        self.running()
        self.extra_env = {"FAKE_CLAUDE_ATTACH": json.dumps(["restart", "detach"])}
        p = self.run_stella("tab", "00000001")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.attaches(), [["attach", "00000001"]] * 2)

    def test_tab_survives_several_restarts_in_a_row(self):
        self.running()
        self.extra_env = {"FAKE_CLAUDE_ATTACH": json.dumps(["restart", "restart", "restart"])}
        self.run_stella("tab", "00000001")
        self.assertEqual(len(self.attaches()), 4)

    def test_tab_ends_on_a_detach(self):
        self.running()
        self.assertEqual(self.run_stella("tab", "00000001").returncode, 0)
        self.assertEqual(len(self.attaches()), 1)

    def test_tab_ends_when_the_session_is_gone(self):
        self.running()
        self.extra_env = {"FAKE_CLAUDE_ATTACH": json.dumps(["gone"])}
        p = self.run_stella("tab", "00000001")
        self.assertEqual(p.returncode, 0)
        self.assertIn("gone", p.stdout)
        self.assertEqual(len(self.attaches()), 1)

    def test_tab_does_not_attach_to_a_session_that_is_not_listed(self):
        self.set_agents([])
        self.assertEqual(self.run_stella("tab", "00000001").returncode, 0)
        self.assertEqual(self.attaches(), [])

    def test_tab_rejects_a_bad_id(self):
        self.assertNotEqual(self.run_stella("tab", "../x").returncode, 0)

    def test_tabs_run_the_follow_command(self):
        self.with_herdr()
        self.live("built")
        self.crew("built", id="00000001")
        self.run_stella("view", "built")
        runs = [c for c in map(json.loads, self.herdr_log.read_text().splitlines()) if c[:2] == ["pane", "run"]]
        self.assertEqual(len(runs), 1)
        self.assertTrue("claude attach 00000001; sleep 2; done" in runs[0][3], runs[0])

    def test_crew_sync_attaches_again_in_a_crew_tab_that_shows_session_exited(self):
        self.with_herdr()
        self.live("exited-one", "fine-one")
        self.crew("exited-one", id="00000001")
        self.crew("fine-one", id="00000002")
        self.herdr_tabs.write_text(json.dumps({"w10:t1": "fm-exited-one", "w11:t1": "fm-fine-one"}))
        Path(str(self.herdr_tabs) + ".ws").write_text(json.dumps({"w10": "└ exited-one", "w11": "└ fine-one"}))
        self.extra_env = {"FAKE_HERDR_SCREEN": json.dumps({"w10:t1:p1": "...\nSession 00000001 has exited.\n\n~/github on main\n❯\n", "w11:t1:p1": "working"})}
        self.assertEqual(self.run_stella("crew", "sync").returncode, 0)
        runs = self.herdr_calls("pane", "run")
        self.assertEqual([r[2] for r in runs], ["w10:t1:p1"])
        self.assertTrue("claude attach 00000001; sleep 2; done" in runs[0][3])
        self.assertEqual(len(self.tabs()), 2)  # the tabs and their order are untouched

    def test_view_all_repairs_stellas_own_tab_which_has_no_record(self):
        self.with_herdr()
        self.live()
        self.herdr_tabs.write_text(json.dumps({"w4:t1": "Stella"}))
        self.extra_env = {"FAKE_HERDR_SCREEN": json.dumps({"w4:t1:p1": "Session 3479a9f0 has exited."})}
        self.assertEqual(self.run_stella("view", "--all").returncode, 0)
        runs = [c for c in map(json.loads, self.herdr_log.read_text().splitlines()) if c[:2] == ["pane", "run"]]
        self.assertEqual([r[2] for r in runs], ["w4:t1:p1"])
        self.assertTrue("stella listed aaaaaaaa; do claude attach aaaaaaaa" in runs[0][3])

    # -------------------------------------------------------------- projects, no tabs, the crew list

    def job(self, sid, **state):
        d = self.home / ".claude/jobs" / sid
        d.mkdir(parents=True, exist_ok=True)
        (d / "state.json").write_text(json.dumps(state))

    def transcript(self, session, text):
        d = self.home / ".claude/projects/x"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{session}.jsonl").write_text(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": text}]}}) + "\n")

    def test_launch_lists_the_crewmate_in_the_sidebar_and_opens_no_tab_in_the_work_window(self):
        self.with_herdr()
        self.herdr_tabs.write_text(json.dumps({"w1:t1": "Stella"}))
        Path(str(self.herdr_tabs) + ".ws").write_text(json.dumps({"w1": "work"}))
        self.crew("fix-flake", project="benchmark-poem")
        self.assertEqual(self.run_stella("launch", "fix-flake").returncode, 0)
        self.assertEqual([t for t in self.tabs() if t.startswith("w1:")], ["w1:t1"])
        self.assertEqual(self.sidebar(), {"└ benchmark-poem · fix-flake": ["fm-fix-flake"]})
        self.assertEqual(self.rec("fix-flake")["project"], "benchmark-poem")

    def test_adopt_lists_the_session_in_the_sidebar(self):
        self.with_herdr()
        self.live("mine")
        self.assertEqual(self.run_stella("adopt", "mine").returncode, 0)
        self.assertEqual(self.sidebar(), {"└ mine": ["fm-mine"]})

    def test_launch_still_works_when_herdr_is_missing(self):
        self.crew("fix-flake")
        self.assertEqual(self.run_stella("launch", "fix-flake").returncode, 0)

    def test_launch_refuses_a_bad_project_slug(self):
        self.crew("fix-flake", project="Bad Slug")
        self.assertNotEqual(self.run_stella("launch", "fix-flake").returncode, 0)

    def test_adopt_takes_a_project_and_validates_it(self):
        self.live("mine")
        self.assertEqual(self.run_stella("adopt", "mine", "--project", "mlc", "--team", "t1").returncode, 0)
        self.assertEqual((self.rec("mine")["project"], self.rec("mine")["team"]), ("mlc", "t1"))
        self.live("other")
        self.assertNotEqual(self.run_stella("adopt", "other", "--project", "Bad_Slug").returncode, 0)
        self.assertFalse((self.sh / "crew/other/record.json").exists())

    def test_adopt_resume_takes_a_project(self):
        session = "12345678-1234-1234-1234-123456789abc"
        tr = self.home / ".claude/projects/x"
        tr.mkdir(parents=True)
        (tr / f"{session}.jsonl").write_text(json.dumps({"cwd": str(self.work)}) + "\n")
        p = self.run_stella("adopt", "--resume", session, "old-one", "--project", "mlc")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.rec("old-one")["project"], "mlc")

    def test_project_sets_and_clears_the_project_of_a_record(self):
        self.crew("fix-flake")
        self.assertEqual(self.run_stella("project", "fix-flake", "mlc").returncode, 0)
        self.assertEqual(self.rec("fix-flake")["project"], "mlc")
        self.assertNotEqual(self.run_stella("project", "fix-flake", "No Good").returncode, 0)
        self.assertEqual(self.run_stella("project", "fix-flake", "--none").returncode, 0)
        self.assertNotIn("project", self.rec("fix-flake"))

    def test_projects_lists_each_project_with_its_crew_and_the_decisions_waiting(self):
        (self.sh / "projects.md").write_text(
            "# Projects\n\n## mlc \u2014 Billing revamp\n- status: in review\n\n## empty-one \u2014 Not started\n")
        self.crew("builder", id="00000001", session="s1", project="mlc")
        self.crew("asker", id="00000002", session="s2", project="mlc")
        self.crew("loose", id="00000003", session="s3")
        self.job("00000001", state="working")
        self.job("00000002", state="working")
        self.job("00000003", state="working")
        self.transcript("s2", "text\n" + "\u2501" * 40 + "\n\U0001F7E7 **NEXT FOR YOU** (2)\n1. Pick the schema\n2. Approve the PR")
        p = self.run_stella("projects")
        self.assertEqual(p.returncode, 0, p.stderr)
        out = p.stdout
        self.assertIn("mlc \u2014 Billing revamp", out)
        self.assertIn("status: in review", out)
        self.assertIn("asker", out)
        self.assertIn("needs you: Pick the schema (+1 more)", out)
        self.assertIn("decisions waiting: 1", out)
        self.assertIn("builder", out)
        self.assertIn("working", out)
        self.assertIn("empty-one", out)
        self.assertIn("no crew", out)
        self.assertIn("(no project)", out)
        self.assertLess(out.index("asker"), out.index("builder"))  # the one that needs Kohen first

    def test_crew_states(self):
        for name, i in (("w", 1), ("b", 2), ("d", 3), ("n", 4)):
            self.crew(name, id=f"{i:08x}", session=f"s{i}")
        self.job("00000001", state="working")
        self.job("00000002", state="blocked", detail="rate limit")
        self.job("00000003", state="working")
        self.transcript("s3", "x\n" + "\u2501" * 40 + "\n\U0001F7E9 **ALL DONE** \u2014 nothing left for you.")
        self.job("00000004", state="blocked", needs="a decision on X")
        self.crew("q", state="queued", queued_because="slot cap")
        self.crew("gone", state="landed")
        out = self.run_stella("crew").stdout
        self.assertRegex(out, r"w +working")
        self.assertRegex(out, r"b +blocked: rate limit")
        self.assertRegex(out, r"d +done")
        self.assertRegex(out, r"n +needs you: a decision on X")
        self.assertRegex(out, r"q +queued: slot cap")
        self.assertNotIn("gone", out)

    def test_crew_watch_redraws_the_list_in_frames(self):
        self.crew("w", id="00000001", session="s1")
        self.job("00000001", state="working")
        self.extra_env = {"STELLA_CREW_EVERY": "0.05", "STELLA_CREW_FRAMES": "2"}
        out = self.run_stella("crew", "--watch").stdout
        self.assertEqual(out.count("CREW"), 2)
        self.assertEqual(out.count("\033[H\033[J"), 2)
        self.assertIn("w", out)

    def test_crew_pane_is_gone_and_unpane_closes_only_the_recorded_pane(self):
        self.with_herdr()
        self.assertNotEqual(self.run_stella("crew", "--pane").returncode, 0)
        self.herdr_tabs.write_text(json.dumps({"w1:t1": "Stella"}))
        (self.sh / "crew-pane").write_text("w1:t1:p1\n")
        self.assertEqual(self.run_stella("crew", "--unpane").returncode, 0)
        self.assertEqual(self.herdr_calls("pane", "close"), [["pane", "close", "w1:t1:p1"]])
        self.assertFalse((self.sh / "crew-pane").exists())
        self.assertIn("no crew-list pane", self.run_stella("crew", "--unpane").stdout)
        self.assertEqual(len(self.herdr_calls("pane", "close")), 1)

    def test_hide_closes_only_the_tabs_of_crew_records_and_keeps_the_sessions(self):
        self.with_herdr()
        self.live("built", "adopted-one")
        self.crew("built", id="00000001", tab="w1:t2")
        self.crew("adopted-one", id="00000002", adopted=True)
        self.herdr_tabs.write_text(json.dumps({"w1:t1": "Stella", "w1:t2": "built", "w1:t3": "adopted-one",
                                               "w1:t4": "kohens-own-shell"}))
        self.assertEqual(self.run_stella("hide", "built").returncode, 0)
        self.assertEqual(sorted(self.tabs().values()), ["Stella", "adopted-one", "kohens-own-shell"])
        self.assertNotIn("tab", self.rec("built"))
        self.assertEqual(self.run_stella("hide", "--all").returncode, 0)
        self.assertEqual(sorted(self.tabs().values()), ["Stella", "kohens-own-shell"])
        self.assertFalse([c for c in self.calls() if c[:1] in (["stop"], ["rm"])])  # the sessions are untouched

    def test_hide_never_closes_a_tab_of_a_crew_workspace(self):
        self.with_herdr()
        self.live("built")
        self.crew("built", id="00000001")
        self.herdr_tabs.write_text(json.dumps({"w1:t1": "Stella", "w1:t2": "built"}))
        Path(str(self.herdr_tabs) + ".ws").write_text(json.dumps({"w1": "work"}))
        self.run_stella("crew", "sync")  # its workspace, next to the old tab in the work window
        self.assertEqual(sorted(self.tabs().values()), ["Stella", "built", "fm-built"])
        self.run_stella("hide", "--all")
        self.assertEqual(sorted(self.tabs().values()), ["Stella", "fm-built"])  # the old one went, the sidebar's stays
        self.assertEqual(self.sidebar(), {"└ built": ["fm-built"]})

    def test_view_repair_and_view_all_are_the_old_names_of_crew_sync(self):
        self.with_herdr()
        self.live("built")
        self.crew("built", id="00000001")
        for old in ("--repair", "--all"):
            self.assertEqual(self.run_stella("view", old).returncode, 0)
        self.assertEqual(self.sidebar(), {"└ built": ["fm-built"]})
        self.assertEqual(len(self.herdr_calls("workspace", "create")), 1)

    def test_view_of_one_focuses_its_workspace_and_opens_no_tab_in_the_work_window(self):
        self.with_herdr()
        self.live("built")
        self.crew("built", id="00000001")
        self.herdr_tabs.write_text(json.dumps({"w1:t1": "Stella"}))
        Path(str(self.herdr_tabs) + ".ws").write_text(json.dumps({"w1": "work"}))
        self.assertEqual(self.run_stella("view", "built").returncode, 0)
        self.assertEqual([t for t in self.tabs() if t.startswith("w1:")], ["w1:t1"])
        ws = [w for w, n in self.workspaces().items() if n == "└ built"][0]
        self.assertEqual(self.herdr_calls("workspace", "focus"), [["workspace", "focus", ws]])
        self.assertEqual(self.herdr_calls("tab", "focus"), [])

    def test_unknown_subcommand(self):
        self.assertEqual(self.run_stella("launch").returncode, 2)
        self.assertEqual(self.run_stella("frobnicate").returncode, 2)


if __name__ == "__main__":
    unittest.main()
