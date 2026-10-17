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

    def with_herdr(self):
        (self.bin / "herdr").symlink_to(FAKE_HERDR)

    def tabs(self):
        return json.loads(self.herdr_tabs.read_text()) if self.herdr_tabs.exists() else {}

    def pr_is(self, state):
        self.gh_state.write_text(json.dumps({"state": state, "url": PR}))

    def tearDown(self):
        self.t.cleanup()

    def set_agents(self, rows):
        self.agents.write_text(json.dumps(rows))

    def run_stella(self, *args, cwd=None):
        env = {"HOME": str(self.home), "STELLA_PATH": f"{self.bin}:/usr/bin:/bin", "FAKE_CLAUDE_LOG": str(self.log),
               "FAKE_CLAUDE_AGENTS": str(self.agents), "FAKE_HERDR_LOG": str(self.herdr_log),
               "FAKE_HERDR_TABS": str(self.herdr_tabs)}
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

    def test_view_all_opens_a_tab_for_each_live_session_without_one_adopted_included(self):
        self.with_herdr()
        self.live("built", "adopted-one")
        self.crew("built", id="00000001")
        self.crew("adopted-one", id="00000002", adopted=True)
        self.herdr_tabs.write_text(json.dumps({"w1:t1": "stella"}))
        self.assertEqual(self.run_stella("view", "--all").returncode, 0)
        self.assertEqual(sorted(self.tabs().values()), ["adopted-one", "built", "stella"])
        self.assertEqual(self.rec("built")["tab"], [t for t, n in self.tabs().items() if n == "built"][0])
        self.run_stella("view", "--all")  # a second run opens nothing new
        self.assertEqual(len(self.tabs()), 3)

    def test_rm_closes_the_tab_it_opened(self):
        self.with_herdr()
        self.live("done-one")
        self.crew("done-one", id="00000001", mode="scout", report=str(self.home / "r.md"))
        (self.home / "r.md").write_text("findings")
        self.run_stella("view", "done-one")
        self.assertEqual(list(self.tabs().values()), ["done-one"])
        self.assertEqual(self.run_stella("rm", "done-one").returncode, 0)
        self.assertEqual(self.tabs(), {})
        self.assertNotIn("tab", self.rec("done-one"))

    def test_rm_finds_a_tab_by_its_label_when_the_record_has_no_id_of_it(self):
        self.with_herdr()
        self.herdr_tabs.write_text(json.dumps({"w1:t7": "old-one", "w1:t8": "keep"}))
        self.crew("old-one", id="00000001", mode="scout", report=str(self.home / "r.md"))
        (self.home / "r.md").write_text("findings")
        self.assertEqual(self.run_stella("rm", "old-one").returncode, 0)
        self.assertEqual(self.tabs(), {"w1:t8": "keep"})

    def test_view_all_closes_tabs_of_sessions_that_exited_for_good(self):
        self.with_herdr()
        self.live("alive")  # `gone` is not listed at all; `landed-one` is listed but its record is landed
        self.crew("alive", id="00000001")
        self.crew("gone", id="000000f1")
        self.crew("landed-one", id="00000002", state="landed")
        self.herdr_tabs.write_text(json.dumps({"w1:t1": "alive", "w1:t2": "gone", "w1:t3": "landed-one"}))
        self.run_stella("view", "--all")
        self.assertEqual(sorted(self.tabs().values()), ["alive"])

    def test_unknown_subcommand(self):
        self.assertEqual(self.run_stella("launch").returncode, 2)
        self.assertEqual(self.run_stella("frobnicate").returncode, 2)


if __name__ == "__main__":
    unittest.main()
