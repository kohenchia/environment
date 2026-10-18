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


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


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
        if not (self.bin / "herdr").exists():
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
               "STELLA_FOLLOW_WAIT": "3", "STELLA_NO_FOLLOWER": "1", **self.extra_env}
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

    def test_there_is_no_cap_on_the_number_of_busy_crewmates(self):
        rows = [{"id": "aaaaaaaa", "name": "stella", "kind": "background", "state": "working",
                 "sessionId": "aaaaaaaa-0000-0000-0000-000000000000"}]
        for i in range(10):
            sid = f"{i:08x}"
            self.crew(f"busy-{i}", id=sid, session=sid + "-x", state="working")
            rows.append({"id": sid, "name": f"busy-{i}", "kind": "background", "state": "working",
                         "sessionId": sid + "-x"})
        self.set_agents(rows)
        self.crew("eleventh")
        p = self.run_stella("launch", "eleventh")
        self.assertEqual(p.returncode, 0, p.stderr)  # ten are busy and it still starts: only Opus weight, throttle and budget gate
        self.assertEqual(self.rec("eleventh")["state"], "working")

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
        # a priority naming a crewmate that is not among the ones sorted still ranks its project
        (mod.STELLA_HOME / "priorities.md").write_text("1. one\n   Crew: gone-one.\n")
        live = [{"name": "a", "project": "alpha"}, {"name": "k", "project": "keep"}]
        every = live + [{"name": "gone-one", "project": "keep"}]
        self.assertEqual([r["name"] for r in mod.crew_sort(live, every)], ["k", "a"])

    def with_window(self, name="built", sid="00000001", ws="w10", **rec):
        """A live crewmate with a window in the workspace of the earlier layout (the reporter reads either)."""
        self.with_herdr()
        self.live(name)
        self.crew(name, id=sid, crew_ws=ws, attach=2, **rec)
        self.herdr_tabs.write_text(json.dumps({f"{ws}:t1": f"fm-{name}"}))
        Path(str(self.herdr_tabs) + ".ws").write_text(json.dumps({ws: f"└ {name}"}))

    def test_follow_copies_claudes_awaiting_input_onto_the_pane_and_the_space(self):
        self.with_window(project="mlc")
        self.job("00000001", state="blocked", needs="pick the base branch")
        self.assertEqual(self.run_stella("crew", "follow", "--once").returncode, 0)
        rep = self.herdr_calls("pane", "report-agent")
        self.assertEqual(len(rep), 1)
        self.assertEqual(rep[0][2], "w10:t1:p1")
        self.assertEqual(rep[0][rep[0].index("--state") + 1], "blocked")
        self.assertEqual(rep[0][rep[0].index("--message") + 1], "pick the base branch")
        meta = self.herdr_calls("pane", "report-metadata")[0]
        self.assertIn("blocked=needs you", meta)
        self.assertEqual(meta[meta.index("--title") + 1], "pick the base branch")
        ws = self.herdr_calls("workspace", "report-metadata")
        self.assertEqual([c for c in ws if c[2] == "w10"][0][3:], ["--source", "stella", "--token", "need=1 waiting"])

    def test_follow_maps_working_to_working_and_everything_else_to_idle(self):
        for claude_state, herdr_state in (("working", "working"), ("done", "idle"), ("stopped", "idle"),
                                          ("blocked", "blocked")):
            with self.subTest(claude_state):
                self.herdr_log.unlink(missing_ok=True)
                self.with_window()
                self.job("00000001", state=claude_state)
                self.run_stella("crew", "follow", "--once")
                rep = self.herdr_calls("pane", "report-agent")[0]
                self.assertEqual(rep[rep.index("--state") + 1], herdr_state)

    def test_follow_reports_a_change_once_and_a_steady_state_not_again(self):
        self.with_window()
        self.job("00000001", state="working")
        env = dict(os.environ, HOME=str(self.home), STELLA_PATH=f"{self.bin}:/usr/bin:/bin",
                   FAKE_CLAUDE_LOG=str(self.log), FAKE_CLAUDE_AGENTS=str(self.agents),
                   FAKE_HERDR_LOG=str(self.herdr_log), FAKE_HERDR_TABS=str(self.herdr_tabs),
                   STELLA_FOLLOW_EVERY="0.3", STELLA_FOLLOW_CYCLES="8", STELLA_NO_FOLLOWER="1")
        p = subprocess.Popen(["python3", str(STELLA), "crew", "follow"], cwd=self.sh, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(100):  # the first report is out: now the state changes
            if self.herdr_calls("pane", "report-agent"):
                break
            time.sleep(0.1)
        self.job("00000001", state="blocked", needs="ship it?")
        p.communicate(timeout=20)
        states = [c[c.index("--state") + 1] for c in self.herdr_calls("pane", "report-agent")]
        self.assertEqual(states, ["working", "blocked"])  # six cycles, two reports
        need = [c for c in self.herdr_calls("workspace", "report-metadata") if "--token" in c]
        self.assertEqual(len(need), 1)

    def test_follow_clears_the_space_count_when_nothing_waits_any_more(self):
        self.with_window()
        self.job("00000001", state="done")
        self.run_stella("crew", "follow", "--once")
        self.assertEqual(self.herdr_calls("workspace", "report-metadata")[0][3:],
                         ["--source", "stella", "--clear-token", "need"])

    def test_follow_gives_a_session_without_a_job_file_no_dot(self):
        self.with_window()
        self.run_stella("crew", "follow", "--once")
        self.assertEqual(self.herdr_calls("pane", "report-agent"), [])

    def test_follow_ensure_starts_one_detached_reporter_and_a_second_call_starts_none(self):
        self.with_window()
        self.extra_env = {"STELLA_FOLLOW_EVERY": "0.1", "STELLA_NO_FOLLOWER": ""}
        first = self.run_stella("crew", "follow", "--ensure")
        pid = int(first.stdout.split("(")[1].split(")")[0])
        self.addCleanup(lambda: os.kill(pid, 15) if _alive(pid) else None)
        self.assertTrue(_alive(pid), first.stdout + first.stderr)
        self.assertIn(f"({pid})", self.run_stella("crew", "follow", "--ensure").stdout)
        self.assertEqual(int((self.sh / "follow.pid").read_text()), pid)

    def test_follow_ensure_replaces_a_stale_pidfile(self):
        self.with_window()
        self.extra_env = {"STELLA_FOLLOW_EVERY": "0.1", "STELLA_NO_FOLLOWER": ""}
        (self.sh / "follow.pid").write_text("999999\n")
        pid = int(self.run_stella("crew", "follow", "--ensure").stdout.split("(")[1].split(")")[0])
        self.addCleanup(lambda: os.kill(pid, 15) if _alive(pid) else None)
        self.assertNotEqual(pid, 999999)

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
        self.crew("q", state="queued", queued_because="Opus weight cap")
        self.crew("gone", state="landed")
        out = self.run_stella("crew").stdout
        self.assertRegex(out, r"w +working")
        self.assertRegex(out, r"b +blocked: rate limit")
        self.assertRegex(out, r"d +done")
        self.assertRegex(out, r"n +needs you: a decision on X")
        self.assertRegex(out, r"q +queued: Opus weight cap")
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

    # -------------------------------------------------------------- the layout: a space per project

    def herdr_start(self, spaces=None, tabs=None):
        """Stella's space with her one window, as `tw` builds it, plus whatever else the test lays out."""
        self.with_herdr()
        self.herdr_tabs.write_text(json.dumps({"w1:t1": "stella", **(tabs or {})}))
        Path(str(self.herdr_tabs) + ".ws").write_text(json.dumps({"w1": "stella", **(spaces or {})}))

    def space_tabs(self):
        """{space label: [window labels]} of every space fake-herdr holds."""
        return {label: [n for t, n in self.tabs().items() if t.startswith(w + ":")]
                for w, label in self.workspaces().items()}

    def test_sync_builds_a_space_per_project_with_a_shell_window_first_then_one_window_per_session(self):
        self.herdr_start()
        self.live("built", "also-built", "loose", "other")
        self.crew("built", id="00000001", project="mlc")
        self.crew("also-built", id="00000002", project="mlc")
        self.crew("other", id="00000004", project="beta")
        self.crew("loose", id="00000003")  # a crewmate with no project
        self.assertEqual(self.run_stella("crew", "sync").returncode, 0)
        self.assertEqual(self.space_tabs(), {"stella": ["stella", "loose"], "mlc": ["mlc", "also-built", "built"],
                                             "beta": ["beta", "other"]})
        self.assertFalse([l for l in self.workspaces().values() if l.startswith("└")])
        rec = self.rec("built")
        self.assertEqual(self.workspaces()[rec["space"]], "mlc")
        self.assertEqual(self.tabs()[rec["tab"]], "built")
        creates = self.herdr_calls("workspace", "create")
        self.assertEqual(len(creates), 2)
        self.assertIn("--no-focus", creates[0])
        loops = sorted(r[3].split("claude attach ")[1].split(";")[0] for r in self.herdr_calls("pane", "run"))
        self.assertEqual(loops, ["00000001", "00000002", "00000003", "00000004"])
        self.run_stella("crew", "sync")  # a second run opens nothing new
        self.assertEqual(len(self.herdr_calls("workspace", "create")), 2)
        self.assertEqual(len(self.herdr_calls("tab", "create")), 4)

    def test_a_crew_window_runs_claude_attach_itself_in_a_loop_while_the_session_is_listed(self):
        self.herdr_start()
        self.live("built")
        self.crew("built", id="00000001")
        self.run_stella("crew", "sync")
        cmd = self.herdr_calls("pane", "run")[0][3]
        self.assertRegex(cmd, r"^while .*/stella listed 00000001; do claude attach 00000001; sleep 2; done$")
        self.assertEqual(self.run_stella("listed", "00000001").returncode, 0)
        self.assertEqual(self.run_stella("listed", "000000ff").returncode, 1)

    def test_a_session_nobody_adopted_gets_a_window_in_stellas_space(self):
        self.herdr_start()
        self.live("kohens-own")
        self.run_stella("crew", "sync")
        self.assertEqual(self.space_tabs()["stella"], ["stella", "kohens-own"])
        w = json.loads((self.sh / "windows.json").read_text())["00000001"]
        self.assertEqual((w["name"], self.tabs()[w["tab"]]), ("kohens-own", "kohens-own"))
        self.run_stella("crew", "sync")
        self.assertEqual(len(self.herdr_calls("tab", "create")), 1)

    def test_sync_lists_every_session_claude_lists_completed_ones_too(self):
        self.herdr_start()
        self.set_agents([{"id": "aaaaaaaa", "name": "stella", "kind": "background", "state": "working",
                          "sessionId": "aaaaaaaa-0000-0000-0000-000000000000"},
                         {"id": "00000001", "name": "finished", "kind": "background", "state": "done", "sessionId": "x1"},
                         {"id": "00000002", "name": "old-stella", "kind": "background", "state": "stopped", "sessionId": "x2"},
                         {"id": "00000003", "name": "term", "kind": "interactive", "state": "working", "sessionId": "x3"}])
        self.run_stella("crew", "sync")
        # an interactive session has nothing to attach, and a stopped one gets no window (attaching may resume it)
        self.assertEqual(self.space_tabs()["stella"], ["stella", "finished"])

    def test_sync_moves_the_live_pane_of_an_earlier_layout_into_its_project_and_restarts_nothing(self):
        self.herdr_start(spaces={"w10": "└ mlc · built"}, tabs={"w10:t1": "fm-built"})
        self.live("built")
        self.crew("built", id="00000001", project="mlc", crew_ws="w10", attach=2)
        self.assertEqual(self.run_stella("crew", "sync").returncode, 0)
        self.assertEqual(self.space_tabs(), {"stella": ["stella"], "mlc": ["mlc", "built"]})
        self.assertNotIn("crew_ws", self.rec("built"))
        self.assertEqual(self.herdr_calls("pane", "move")[0][2:4], ["w10:t1:p1", "--new-tab"])
        self.assertEqual(self.herdr_calls("pane", "run"), [])  # the same process: no new attach loop was typed
        self.assertEqual(self.herdr_calls("pane", "send-keys"), [])
        self.assertEqual([c for c in self.calls() if c[:1] != ["agents"]], [])  # no session was started, stopped or touched
        self.run_stella("crew", "sync")  # idempotent
        self.assertEqual(len(self.herdr_calls("pane", "move")), 1)
        self.assertEqual(self.space_tabs(), {"stella": ["stella"], "mlc": ["mlc", "built"]})

    def test_migration_falls_back_to_a_new_window_when_the_pane_cannot_move_and_still_closes_the_old_space(self):
        self.herdr_start(spaces={"w10": "└ built"}, tabs={"w10:t1": "fm-built"})
        self.live("built")
        self.crew("built", id="00000001", crew_ws="w10", attach=2)
        self.extra_env = {"FAKE_HERDR_MOVE_FAIL": "1"}
        self.run_stella("crew", "sync")
        self.assertEqual(self.space_tabs(), {"stella": ["stella", "built"]})
        self.assertIn("claude attach 00000001", self.herdr_calls("pane", "run")[0][3])
        self.assertEqual([c for c in self.calls() if c[:1] != ["agents"]], [])

    def test_a_project_change_moves_the_window_to_the_new_space_without_a_restart(self):
        self.herdr_start()
        self.live("built")
        self.crew("built", id="00000001", project="mlc")
        self.run_stella("crew", "sync")
        self.run_stella("assign", "built", "beta")
        self.run_stella("crew", "sync")
        self.assertEqual(self.space_tabs()["beta"], ["beta", "built"])
        self.assertEqual(self.space_tabs()["mlc"], ["mlc"])
        self.assertEqual(len(self.herdr_calls("pane", "run")), 1)  # attached once, then moved

    def test_a_window_kohen_renamed_keeps_his_name(self):
        self.herdr_start()
        self.live("built")
        self.crew("built", id="00000001")
        self.run_stella("crew", "sync")
        tab = self.rec("built")["tab"]
        t = self.tabs()
        t[tab] = "my-name"
        self.herdr_tabs.write_text(json.dumps(t))
        self.run_stella("crew", "sync")
        self.assertEqual(self.tabs()[tab], "my-name")

    def test_sync_closes_the_window_of_a_session_that_is_gone_or_landed(self):
        self.herdr_start()
        self.live("alive", "done-one")
        self.crew("alive", id="00000001")
        self.crew("done-one", id="00000002")
        self.crew("gone", id="000000f1")
        self.run_stella("crew", "sync")
        self.assertEqual(self.space_tabs()["stella"], ["stella", "alive", "done-one"])
        d = self.rec("done-one")
        (self.sh / "crew/done-one/record.json").write_text(json.dumps({**d, "state": "landed"}))
        self.run_stella("crew", "sync")
        self.assertEqual(self.space_tabs()["stella"], ["stella", "alive"])
        self.assertNotIn("tab", self.rec("done-one"))

    def test_a_window_kohen_closed_stays_closed_until_the_session_awaits_input(self):
        self.herdr_start()
        self.live("built")
        self.crew("built", id="00000001")
        self.job("00000001", state="working")
        self.run_stella("crew", "sync")
        t = self.tabs()
        del t[self.rec("built")["tab"]]
        self.herdr_tabs.write_text(json.dumps(t))
        self.run_stella("crew", "sync")
        self.assertEqual(self.space_tabs()["stella"], ["stella"])
        self.assertEqual(self.rec("built")["closed"], "ok")
        self.run_stella("crew", "sync")  # still working: stays closed
        self.assertEqual(len(self.herdr_calls("tab", "create")), 1)
        self.job("00000001", state="blocked", needs="x")
        self.run_stella("crew", "sync")
        self.assertEqual(self.space_tabs()["stella"], ["stella", "built"])
        self.assertNotIn("closed", self.rec("built"))

    def test_a_space_kohen_closed_stays_closed_until_a_session_in_it_awaits_input_or_one_joins(self):
        self.herdr_start()
        self.live("built", "joiner")
        self.crew("built", id="00000001", project="mlc")
        self.job("00000001", state="working")
        self.run_stella("crew", "sync")
        ws = [w for w, n in self.workspaces().items() if n == "mlc"][0]
        Path(str(self.herdr_tabs) + ".ws").write_text(json.dumps({w: n for w, n in self.workspaces().items() if w != ws}))
        self.herdr_tabs.write_text(json.dumps({t: n for t, n in self.tabs().items() if not t.startswith(ws + ":")}))
        self.run_stella("crew", "sync")
        self.assertNotIn("mlc", self.workspaces().values())
        self.run_stella("crew", "sync")
        self.assertNotIn("mlc", self.workspaces().values())
        self.crew("joiner", id="00000002", project="mlc")  # a new crewmate joins the project: it comes back
        self.run_stella("crew", "sync")
        self.assertIn("mlc", self.workspaces().values())

    def test_sync_without_a_herdr_server_says_so_and_opens_nothing(self):
        self.herdr_start()
        self.live("built")
        self.crew("built", id="00000001")
        self.extra_env = {"FAKE_HERDR_DOWN": "1"}
        r = self.run_stella("crew", "sync")
        self.assertEqual(r.returncode, 0)
        self.assertIn("not running", r.stdout)
        self.assertEqual(self.herdr_calls("tab", "create"), [])
        self.assertEqual(self.herdr_calls("workspace", "create"), [])

    def test_sync_renames_the_work_workspace_to_stella(self):
        self.with_herdr()
        self.herdr_tabs.write_text(json.dumps({"w1:t1": "stella"}))
        Path(str(self.herdr_tabs) + ".ws").write_text(json.dumps({"w1": "work"}))
        self.run_stella("crew", "sync")
        self.assertEqual(self.workspaces(), {"w1": "stella"})

    def test_sync_attaches_again_in_a_window_that_shows_session_exited(self):
        self.herdr_start()
        self.live("exited-one", "fine-one")
        self.crew("exited-one", id="00000001")
        self.crew("fine-one", id="00000002")
        self.run_stella("crew", "sync")
        n = len(self.herdr_calls("pane", "run"))
        tab = self.rec("exited-one")["tab"]
        self.extra_env = {"FAKE_HERDR_SCREEN": json.dumps({tab + ":p1": "...\nSession 00000001 has exited.\n❯\n"})}
        self.run_stella("crew", "sync")
        runs = self.herdr_calls("pane", "run")[n:]
        self.assertEqual([r[2] for r in runs], [tab + ":p1"])
        self.assertIn("claude attach 00000001; sleep 2; done", runs[0][3])

    def test_rm_closes_the_window_of_the_crewmate(self):
        self.herdr_start()
        self.live("done-one")
        self.crew("done-one", id="00000001", mode="scout", report=str(self.home / "r.md"), project="mlc")
        (self.home / "r.md").write_text("findings")
        self.run_stella("crew", "sync")
        self.assertEqual(self.space_tabs()["mlc"], ["mlc", "done-one"])
        self.assertEqual(self.run_stella("rm", "done-one").returncode, 0)
        self.assertEqual(self.space_tabs()["mlc"], ["mlc"])
        self.assertNotIn("tab", self.rec("done-one"))

    def test_launch_and_adopt_open_the_window_in_the_project_space(self):
        self.herdr_start()
        self.crew("fix-flake", project="mlc")
        self.assertEqual(self.run_stella("launch", "fix-flake").returncode, 0)
        self.assertEqual(self.space_tabs()["mlc"], ["mlc", "fix-flake"])
        self.assertEqual(self.herdr_calls("tab", "create", "--workspace", "w1"), [])  # nothing in the work window
        rows = json.loads(self.agents.read_text()) + [{"id": "0000abcd", "name": "theirs", "kind": "background",
                                                       "state": "working", "sessionId": "0000abcd-s"}]
        self.set_agents(rows)
        self.assertEqual(self.run_stella("adopt", "theirs", "--project", "beta").returncode, 0)
        self.assertEqual(self.space_tabs()["beta"], ["beta", "theirs"])

    def test_view_focuses_the_window_of_a_session_even_one_that_was_closed(self):
        self.herdr_start()
        self.live("built")
        self.crew("built", id="00000001", project="mlc")
        self.run_stella("crew", "sync")
        tab = self.rec("built")["tab"]
        self.run_stella("view", "built")
        self.assertEqual(self.herdr_calls("tab", "focus")[-1][2], tab)
        t = self.tabs()
        del t[tab]
        self.herdr_tabs.write_text(json.dumps(t))
        self.run_stella("crew", "sync")
        self.assertEqual(self.rec("built")["closed"], "ok")
        self.run_stella("view", "built")
        self.assertEqual(self.space_tabs()["mlc"], ["mlc", "built"])
        self.assertNotIn("closed", self.rec("built"))

    def test_renaming_a_projects_first_window_renames_the_project_everywhere(self):
        self.herdr_start()
        (self.sh / "projects.md").write_text("# Projects\n\n## mlc — The model work\n- status: going\n\n## beta — B\n")
        self.live("built")
        self.crew("built", id="00000001", project="mlc")
        self.run_stella("crew", "sync")
        ws = [w for w, n in self.workspaces().items() if n == "mlc"][0]
        first = json.loads((self.sh / "view.json").read_text())["firsts"]["mlc"]
        t = self.tabs()
        t[first] = "Mlc Core!"
        self.herdr_tabs.write_text(json.dumps(t))
        self.job("00000001", state="working")
        self.run_stella("crew", "follow", "--once")
        self.assertEqual(self.rec("built")["project"], "mlc-core")
        self.assertEqual(self.workspaces()[ws], "mlc-core")
        self.assertEqual(self.tabs()[first], "mlc-core")
        self.assertIn("## mlc-core — The model work", (self.sh / "projects.md").read_text())
        self.assertIn("## beta — B", (self.sh / "projects.md").read_text())
        ev = [json.loads(l) for l in (self.sh / "renames.jsonl").read_text().splitlines()]
        self.assertEqual([(e["old"], e["new"]) for e in ev], [("mlc", "mlc-core")])
        self.run_stella("crew", "follow", "--once")  # nothing more to rename
        self.assertEqual(len((self.sh / "renames.jsonl").read_text().splitlines()), 1)

    def test_a_first_window_renamed_to_a_name_that_is_taken_is_put_back(self):
        self.herdr_start()
        self.live("built", "other")
        self.crew("built", id="00000001", project="mlc")
        self.crew("other", id="00000002", project="beta")
        self.run_stella("crew", "sync")
        first = json.loads((self.sh / "view.json").read_text())["firsts"]["mlc"]
        t = self.tabs()
        t[first] = "beta"
        self.herdr_tabs.write_text(json.dumps(t))
        self.job("00000001", state="working")
        self.run_stella("crew", "follow", "--once")
        self.assertEqual(self.tabs()[first], "mlc")
        self.assertEqual(self.rec("built")["project"], "mlc")

    def test_doctor_prints_the_parity_line_and_is_green_when_herdr_matches_claude(self):
        self.herdr_start()
        self.live("waits", "works", "finished")
        self.crew("waits", id="00000001", project="mlc")
        self.crew("works", id="00000002", project="mlc")
        self.crew("finished", id="00000003", project="mlc")
        self.job("00000001", state="blocked", needs="pick")
        self.job("00000002", state="working")
        self.job("00000003", state="done")
        self.job("aaaaaaaa", state="working")
        self.run_stella("crew", "sync")
        panes = {n: self.rec(n)["tab"] + ":p1" for n in ("waits", "works", "finished")}
        (self.sh / "view-applied.json").write_text(json.dumps({"at": time.time()}))
        (self.sh / "follow.pid").write_text(f"{os.getpid()}\n")
        self.extra_env = {"FAKE_HERDR_STATUS": json.dumps({panes["waits"]: "blocked", panes["works"]: "working",
                                                           panes["finished"]: "done", "w1:t1:p1": "working"})}
        r = self.run_stella("crew", "doctor")
        self.assertNotIn("BAD", r.stdout, r.stdout)
        self.assertIn("Claude 1 awaiting · 2 working · 1 completed = herdr 1 yellow · 2 blue · 1 green/hollow", r.stdout)
        # a dot that disagrees with Claude is BAD, and the parity line shows it
        self.extra_env["FAKE_HERDR_STATUS"] = json.dumps({panes["waits"]: "idle", panes["works"]: "working",
                                                          panes["finished"]: "done", "w1:t1:p1": "working"})
        r = self.run_stella("crew", "doctor")
        self.assertIn("BAD", r.stdout)
        self.assertIn("0 yellow", r.stdout)
        self.assertEqual(self.herdr_calls("workspace", "close"), [])  # doctor changes nothing

    def test_doctor_is_bad_for_a_left_over_child_space_a_missing_reporter_and_a_stale_agent_view(self):
        self.herdr_start(spaces={"w10": "└ old"})
        d = json.loads(self.run_stella("crew", "doctor", "--json").stdout)
        bad = {c["check"] for c in d["checks"] if not c["ok"] and "check" in c}
        self.assertIn("no `└` space is left", bad)
        self.assertIn("the reporter (`stella crew follow`) runs", bad)
        self.assertIn("the agent view is set (by the reporter, recently)", bad)
        self.assertIn("workspaces", d["raw"])

    # -------------------------------------------------------------- the verbs behind the chords

    def test_project_new_registers_the_project_and_opens_its_space_with_a_first_window(self):
        self.herdr_start()
        r = self.run_stella("project", "new", "WS4 Test")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("using the name ws4-test", r.stdout)
        self.assertEqual(self.space_tabs()["ws4-test"], ["ws4-test"])
        self.assertIn("## ws4-test\n- status: new", (self.sh / "projects.md").read_text())
        self.assertEqual(self.herdr_calls("workspace", "focus")[-1][2], [w for w, n in self.workspaces().items() if n == "ws4-test"][0])
        self.assertNotEqual(self.run_stella("project", "new", "ws4-test").returncode, 0)  # already there
        self.assertEqual(len(self.herdr_calls("workspace", "create")), 1)

    def test_project_new_ask_reads_the_name_from_the_popup(self):
        self.herdr_start()
        env = {"HOME": str(self.home), "STELLA_PATH": f"{self.bin}:/usr/bin:/bin", "FAKE_HERDR_LOG": str(self.herdr_log),
               "FAKE_HERDR_TABS": str(self.herdr_tabs), "FAKE_CLAUDE_AGENTS": str(self.agents), "STELLA_NO_FOLLOWER": "1"}
        p = subprocess.run(["python3", str(STELLA), "project", "new", "--ask"], cwd=self.sh, env=env, input="Chord Test\n",
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("chord-test", self.space_tabs())

    def test_project_rename_close_and_the_old_assign_spelling(self):
        self.herdr_start()
        self.live("built")
        self.crew("built", id="00000001", project="mlc")
        (self.sh / "projects.md").write_text("## mlc — M\n")
        self.run_stella("crew", "sync")
        self.assertEqual(self.run_stella("project", "rename", "mlc", "core").returncode, 0)
        self.assertEqual(self.rec("built")["project"], "core")
        self.assertEqual(self.space_tabs()["core"], ["core", "built"])
        self.assertEqual(self.run_stella("project", "rename", "core", "core").returncode, 0)
        self.assertNotEqual(self.run_stella("project", "rename", "core", "!!!").returncode, 0)
        r = self.run_stella("project", "built", "--none")  # the old spelling still works, with a pointer
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("stella assign", r.stderr)
        self.assertNotIn("project", self.rec("built"))
        self.assertEqual(self.space_tabs()["stella"], ["stella", "built"])
        self.assertEqual(self.run_stella("project", "close", "core").returncode, 0)
        self.assertNotIn("core", self.workspaces().values())
        self.run_stella("crew", "sync")
        self.assertNotIn("core", self.workspaces().values())  # stays closed, the session keeps running
        self.assertEqual([c for c in self.calls() if c[:1] not in (["agents"],)], [])

    def test_window_verbs_open_rename_and_close_windows_and_a_sessions_stays_alive(self):
        self.herdr_start()
        self.live("built")
        self.crew("built", id="00000001", project="mlc")
        self.run_stella("crew", "sync")
        self.assertEqual(self.run_stella("window", "new", "mlc", "Scratch Pad").returncode, 0)
        self.assertEqual(self.space_tabs()["mlc"], ["mlc", "built", "scratch-pad"])
        self.assertEqual(self.run_stella("window", "rename", "mlc", "scratch-pad", "notes").returncode, 0)
        self.assertEqual(self.space_tabs()["mlc"], ["mlc", "built", "notes"])
        self.assertNotEqual(self.run_stella("window", "close", "mlc", "mlc").returncode, 0)  # the first window
        self.assertEqual(self.run_stella("window", "close", "mlc", "notes").returncode, 0)
        self.assertEqual(self.run_stella("window", "close", "mlc", "built").returncode, 0)
        self.assertEqual(self.space_tabs()["mlc"], ["mlc"])
        self.assertEqual(self.rec("built")["closed"], "ok")
        self.run_stella("crew", "sync")
        self.assertEqual(self.space_tabs()["mlc"], ["mlc"])  # sync does not bring it back
        self.assertEqual([c for c in self.calls() if c[:1] != ["agents"]], [])
        self.assertNotEqual(self.run_stella("window", "new", "nope", "x").returncode, 0)

    def test_pane_rename_names_one_pane_of_a_window(self):
        self.herdr_start()
        self.live("built")
        self.crew("built", id="00000001", project="mlc")
        self.run_stella("crew", "sync")
        self.assertEqual(self.run_stella("pane", "rename", "mlc", "built", "1", "the", "agent").returncode, 0)
        self.assertEqual(self.herdr_calls("pane", "rename")[0][3:], ["the agent"])
        self.assertNotEqual(self.run_stella("pane", "rename", "mlc", "built", "2", "x").returncode, 0)

    def test_sync_puts_stellas_space_first_and_the_projects_after_it_over_the_control_socket(self):
        import socket
        import threading
        self.herdr_start(spaces={"w3": "scratch"}, tabs={"w3:t1": "own"})
        Path(str(self.herdr_tabs) + ".ws").write_text(json.dumps({"w3": "scratch", "w1": "stella"}))
        self.live("built")
        self.crew("built", id="00000001", project="mlc")
        got = []
        sock_path = str(self.home / "h.sock")
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
                c.sendall((json.dumps({"id": req["id"], "result": {"type": "ok"}}) + "\n").encode())
                c.close()

        threading.Thread(target=serve, daemon=True).start()
        self.extra_env = {"FAKE_HERDR_SOCKET": sock_path}
        try:
            self.run_stella("crew", "sync")
        finally:
            srv.close()
        mlc = [w for w, n in self.workspaces().items() if n == "mlc"][0]
        self.assertEqual([(g["workspace_id"], g["insert_index"]) for g in got], [("w1", 0), (mlc, 1)])

    # -------------------------------------------------------------- the preferences loop

    def pref_lines(self, *rows):
        (self.sh / "preferences.md").write_text("# Preferences\n\n" + "\n".join(
            f"- {d} | {who} | kind: {kind} | answer: {ans} | Q: {q} | A: {a}" for d, who, kind, ans, q, a in rows) + "\n")

    def test_prefs_propose_drafts_a_principle_from_three_matching_answers_and_only_then(self):
        three = [("2026-10-01", "a-1", "squash-merge", "yes", "squash?", "yes, always"),
                 ("2026-10-05", "b-2", "squash-merge", "yes", "squash this one?", "yes"),
                 ("2026-10-09", "c-3", "squash-merge", "yes", "squash or merge?", "squash")]
        self.pref_lines(*three)
        out = self.run_stella("prefs", "propose").stdout
        self.assertIn("J-NN (proposed): squash-merge", out)
        self.assertIn("3 times, none against", out)
        self.assertIn("- 2026-10-05 b-2: squash this one? → \"yes\"", out)  # each date with his words
        self.assertEqual(out.count("(proposed)"), 1)
        self.pref_lines(*three[:2])  # two answers are an accident
        self.assertIn("no pattern yet: squash-merge (2)", self.run_stella("prefs", "propose").stdout)
        self.assertNotIn("(proposed)", self.run_stella("prefs", "propose").stdout)
        self.pref_lines(*three, ("2026-10-12", "d-4", "squash-merge", "no", "squash?", "no, merge it"))  # one against
        out = self.run_stella("prefs", "propose").stdout
        self.assertNotIn("(proposed)", out)
        self.assertIn("mixed", out)

    def test_prefs_propose_with_nothing_recorded_says_so(self):
        self.assertIn("no answers recorded", self.run_stella("prefs", "propose").stdout)

    def test_prefs_scan_pairs_a_next_for_you_with_the_message_that_followed(self):
        self.crew("built", id="00000001", session="s-built")
        d = self.home / ".claude/projects/p"
        d.mkdir(parents=True)
        rule = "━" * 40
        ev = [{"type": "user", "timestamp": "2026-10-01T10:00:00Z", "message": {"content": "go"}},
              {"type": "assistant", "timestamp": "2026-10-01T10:05:00Z", "message": {"content": [
                  {"type": "text", "text": f"done\n{rule}\n🟧 **NEXT FOR YOU** (1)\n1. Squash it?"}]}},
              {"type": "user", "timestamp": "2026-10-02T09:00:00Z", "message": {"content": [{"type": "tool_result", "content": "x"}]}},
              {"type": "user", "timestamp": "2026-10-02T09:01:00Z", "message": {"content": "yes, squash"}},
              {"type": "assistant", "timestamp": "2026-10-02T09:02:00Z", "message": {"content": [{"type": "text", "text": "ok"}]}},
              {"type": "user", "timestamp": "2026-10-02T09:03:00Z", "message": {"content": "thanks"}}]
        (d / "s-built.jsonl").write_text("\n".join(json.dumps(e) for e in ev) + "\n")
        rows = [json.loads(l) for l in self.run_stella("prefs", "scan").stdout.splitlines()]
        self.assertEqual(rows, [{"date": "2026-10-02", "crewmate": "built", "question": rows[0]["question"], "answer": "yes, squash"}])
        self.assertIn("Squash it?", rows[0]["question"])
        self.assertEqual(self.run_stella("prefs", "scan", "2026-10-03").stdout, "")

    def test_follow_scopes_the_agents_panel_to_the_active_space_over_the_socket(self):
        import socket
        import threading
        self.herdr_start()
        got = []
        sock_path = str(self.home / "v.sock")
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
                got.append(req)
                c.sendall((json.dumps({"id": req["id"], "result": {"type": "ok"}}) + "\n").encode())
                c.close()

        threading.Thread(target=serve, daemon=True).start()
        self.extra_env = {"FAKE_HERDR_SOCKET": sock_path}
        try:
            self.run_stella("crew", "follow", "--once")
        finally:
            srv.close()
        view = [g for g in got if g["method"] == "agent.view.set"][0]["params"]
        self.assertEqual(view["filter"], {"op": "eq", "field": "workspace_id", "value": {"context": "current_workspace_id"}})
        self.assertEqual([s["field"] for s in view["sort"]], ["attention", "tab_order"])
        self.assertEqual(view["source"], "stella")
        self.assertTrue((self.sh / "view-applied.json").exists())  # doctor reads it

    def test_a_finished_session_gets_a_dormant_window_that_holds_no_host_process(self):
        self.herdr_start()
        self.live("finished-one", "busy-one")
        self.crew("finished-one", id="00000001", project="mlc")
        self.crew("busy-one", id="00000002", project="mlc")
        self.job("00000001", state="done")
        self.job("00000002", state="working")
        self.run_stella("crew", "sync")
        runs = [r[3] for r in self.herdr_calls("pane", "run")]
        cmds = {sid: next(c for c in runs if f"listed {sid}" in c) for sid in ("00000001", "00000002")}
        self.assertIn("claude logs 00000001", cmds["00000001"])
        self.assertIn("dormant 00000001", cmds["00000001"])
        self.assertTrue(self.rec("finished-one")["dormant"])
        self.assertTrue(cmds["00000002"].startswith("while "))  # a live session is attached at once
        self.assertNotIn("dormant", self.rec("busy-one"))
        self.assertEqual(self.run_stella("dormant", "00000001").returncode, 0)
        self.assertEqual(self.run_stella("dormant", "00000002").returncode, 1)

    def test_an_attached_window_of_a_session_that_finished_is_swapped_once(self):
        self.herdr_start()
        self.live("built")
        self.crew("built", id="00000001", project="mlc")
        self.job("00000001", state="working")
        self.run_stella("crew", "sync")
        self.job("00000001", state="done")
        self.run_stella("crew", "sync")
        self.assertEqual(len(self.herdr_calls("pane", "send-keys")), 1)
        self.assertIn("claude logs 00000001", self.herdr_calls("pane", "run")[-1][3])
        self.run_stella("crew", "sync")
        self.assertEqual(len(self.herdr_calls("pane", "send-keys")), 1)  # once only

    def test_a_session_named_like_its_project_has_its_own_window_and_the_verbs_mean_that_one(self):
        self.herdr_start()
        self.live("phase-10")
        self.crew("phase-10", id="00000001", project="phase-10")
        self.job("00000001", state="working")
        self.run_stella("crew", "sync")
        self.assertEqual(self.space_tabs()["phase-10"], ["phase-10", "phase-10"])
        self.assertEqual(self.run_stella("window", "rename", "phase-10", "phase-10", "agent").returncode, 0)
        self.assertEqual(self.space_tabs()["phase-10"], ["phase-10", "agent"])  # the session's window, not the first
        self.assertNotEqual(self.run_stella("window", "close", "phase-10", "phase-10").returncode, 0)  # the first window
        d = json.loads(self.run_stella("crew", "doctor", "--json").stdout)
        self.assertTrue(next(c for c in d["checks"] if c.get("check") == "space phase-10")["ok"])

    def test_unknown_subcommand(self):
        self.assertEqual(self.run_stella("launch").returncode, 2)
        self.assertEqual(self.run_stella("frobnicate").returncode, 2)


if __name__ == "__main__":
    unittest.main()
