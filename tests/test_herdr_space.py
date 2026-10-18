"""herdr-space: project grouping and moving a space over a fake herdr socket."""

import importlib.machinery
import importlib.util
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "bin/herdr-space"
loader = importlib.machinery.SourceFileLoader("herdr_space", str(PATH))
hs = importlib.util.module_from_spec(importlib.util.spec_from_loader("herdr_space", loader))
loader.exec_module(hs)
HOME = Path.home()


PROJECTS = hs.parse_projects("""# Projects

## bolt-priority — `mlc --priority` on every Bolt-starting step
- PRs: dashboard#2398 (draft)
- Crew: 2398-rebase (sole writer), pr-2398-kohen (reviewer), stella-cli-retirement (docs branch)

## mlc-docs-drift — Docs drift fixes
- Crew: docs-drift-benchmark, fix-430-comment · Status: waiting on review

## cloud-pro-targets — Cloud Pro targets
- Ticket: T-1 · PR: dashboard#2428 · Crew: 2428-fix-cloud-pro · Status: waiting
""")


class Grouping(unittest.TestCase):
    def of(self, name, cwd="/tmp/x"):
        return hs.project_of({"name": name, "cwd": cwd}, PROJECTS)

    def test_a_listed_session_goes_to_its_project_by_slug(self):
        self.assertEqual(self.of("2398-rebase"), "bolt-priority")
        self.assertEqual(self.of("stella cli retirement"), "bolt-priority")
        self.assertEqual(self.of("fix-430-comment"), "mlc-docs-drift")
        self.assertEqual(self.of("2428-fix-cloud-pro"), "cloud-pro-targets")

    def test_an_unlisted_session_follows_its_number_into_the_project_that_mentions_it(self):
        self.assertEqual(self.of("2398-keep-priority-guide"), "bolt-priority")

    def test_an_unknown_number_is_pr_n_never_a_bare_number(self):
        self.assertEqual(self.of("2777-new-thing"), "pr-2777")

    def test_worktree_counts_as_its_repo(self):
        self.assertEqual(self.of("fix-flake", str(HOME / "github/dashboard-wt/fix/flake")), "dashboard")

    def test_stella_has_her_own_space(self):
        self.assertEqual(self.of("stella", str(HOME)), "stella")

    def test_outside_github_uses_the_directory_name(self):
        self.assertEqual(self.of("scratch", "/tmp/notes"), "notes")

    def test_crew_line_stops_at_status_and_ignores_parentheses(self):
        crew = next(p for p in PROJECTS if p["slug"] == "bolt-priority")["crew"]
        self.assertEqual(crew, {"2398-rebase", "pr-2398-kohen", "stella-cli-retirement"})


class Strays(unittest.TestCase):
    OWNER = {"2398-rebase": "bolt-priority", "stella": "stella", "phase-10": "phase-10"}

    def test_old_layout_windows_in_the_wrong_space_are_closed_and_duplicates_too(self):
        layout = {
            "w16": ("stella", {"t1": "Stella", "t2": "2398-rebase", "t3": "phase-10", "t4": "stella", "t5": "my notes"}),
            "w18": ("bolt-priority", {"t6": "2398-rebase"}),
        }
        got = {(tid, why.split(",")[0]) for tid, _, why in hs.stray_tabs(layout, self.OWNER)}
        self.assertEqual(got, {("t2", "belongs to bolt-priority"), ("t3", "belongs to phase-10"),
                               ("t4", "second window for the same session in stella")})


class Status(unittest.TestCase):
    def transcript(self, *entries):
        import json as j, tempfile as t
        f = t.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        f.write("\n".join(j.dumps(e) for e in entries) + "\n")
        f.close()
        return f.name

    TEXT = {"type": "assistant", "message": {"content": [{"type": "text", "text": "NEXT FOR YOU 1. merge"}]}}
    ASK = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "AskUserQuestion", "input": {}}]}}
    ANSWER = {"type": "user", "message": {"content": [{"type": "tool_result", "content": "yes"}]}}

    def test_working_and_done(self):
        self.assertEqual(hs.session_status({"state": "working"}), "working")
        self.assertEqual(hs.session_status({"state": "done"}), "done")
        self.assertIsNone(hs.session_status({"state": "stopped"}))

    def test_blocked_with_a_question_on_screen_is_a_prompt(self):
        job = {"state": "blocked", "linkScanPath": self.transcript(self.TEXT, self.ASK)}
        self.assertEqual(hs.session_status(job), "prompt")

    def test_blocked_after_a_finished_turn_is_next_steps(self):
        job = {"state": "blocked", "linkScanPath": self.transcript(self.ASK, self.ANSWER, self.TEXT)}
        self.assertEqual(hs.session_status(job), "next")

    def test_blocked_without_a_transcript_is_next_steps(self):
        self.assertEqual(hs.session_status({"state": "blocked"}), "next")

    def test_every_status_has_a_herdr_state(self):
        self.assertEqual(hs.HERDR_STATE, {"prompt": "blocked", "working": "working", "next": "unknown", "done": "idle"})


class Dots(unittest.TestCase):
    def test_a_finished_session_is_new_until_herdr_shows_it_seen(self):
        self.assertEqual(hs.dot_key("done", "done"), "new")
        self.assertEqual(hs.dot_key("done", "idle"), "read")
        self.assertEqual(hs.dot_key("done", None), "read")

    def test_other_statuses_are_their_own_dot(self):
        for status in ("prompt", "next", "working"):
            self.assertEqual(hs.dot_key(status, "idle"), status)

    def test_exactly_the_current_dot_is_set_and_the_rest_cleared(self):
        args = hs.token_args("next")
        self.assertEqual(args.count("--token"), 1)
        self.assertIn("dot_next=\u25cf", args)
        self.assertEqual([args[i + 1] for i, a in enumerate(args) if a == "--clear-token"],
                         ["dot_prompt", "dot_working", "dot_new", "dot_read"])

    def test_read_is_the_hollow_one_and_none_clears_all(self):
        self.assertIn("dot_read=\u25cb", hs.token_args("read"))
        self.assertNotIn("--token", hs.token_args(None))


class Follower(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.old = hs.STATE_DIR
        hs.STATE_DIR = Path(tempfile.mkdtemp())

    def tearDown(self):
        hs.STATE_DIR = self.old

    def test_a_pid_file_without_a_version_is_version_zero(self):
        import os
        (hs.STATE_DIR / "follow.pid").write_text(f"{os.getpid()}\n")
        self.assertEqual(hs.follower(), (os.getpid(), 0))

    def test_a_pid_file_with_a_version_and_a_dead_pid_is_none(self):
        (hs.STATE_DIR / "follow.pid").write_text("999999 2\n")
        self.assertIsNone(hs.follower())

    def test_an_older_reporter_is_replaced_and_a_current_one_is_kept(self):
        import os
        launched, killed = [], []
        real = (hs.subprocess.Popen, hs.os.kill)
        hs.subprocess.Popen = lambda *a, **k: launched.append(a)
        hs.os.kill = lambda pid, sig: killed.append((pid, sig)) if sig else None
        try:
            (hs.STATE_DIR / "follow.pid").write_text(f"{os.getpid()} {hs.FOLLOW_VERSION}\n")
            hs.ensure_follower()
            self.assertEqual((launched, killed), ([], []))
            (hs.STATE_DIR / "follow.pid").write_text(f"{os.getpid()}\n")
            hs.ensure_follower()
            self.assertEqual(len(launched), 1)
            self.assertEqual(killed, [(os.getpid(), hs.signal.SIGTERM)])
        finally:
            hs.subprocess.Popen, hs.os.kill = real


class Move(unittest.TestCase):
    def fake(self, workspaces):
        sent = []

        def rpc(method, params):
            sent.append((method, params))
            return {"workspaces": workspaces} if method == "workspace.list" else {}

        hs.rpc = rpc
        return sent

    def test_down_moves_the_focused_space_one_index(self):
        sent = self.fake([{"workspace_id": "a", "label": "x"}, {"workspace_id": "b", "label": "y", "focused": True},
                          {"workspace_id": "c", "label": "z"}])
        hs.move("down")
        self.assertEqual(sent[1], ("workspace.move", {"workspace_id": "b", "insert_index": 2}))

    def test_top_space_cannot_move_up(self):
        sent = self.fake([{"workspace_id": "a", "label": "x", "focused": True}, {"workspace_id": "b", "label": "y"}])
        hs.move("up")
        self.assertEqual(len(sent), 1)  # only the list


if __name__ == "__main__":
    unittest.main()
