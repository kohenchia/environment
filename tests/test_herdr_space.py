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


class Grouping(unittest.TestCase):
    def test_number_in_the_name_groups_sessions(self):
        for name in ("2398-rebase", "pr-2398-kohen", "2398-dev-priority-all"):
            self.assertEqual(hs.project_of({"name": name, "cwd": str(HOME / "github/dashboard")}), "2398")

    def test_worktree_counts_as_its_repo(self):
        a = {"name": "fix-flake", "cwd": str(HOME / "github/dashboard-wt/fix/flake")}
        self.assertEqual(hs.project_of(a), "dashboard")

    def test_stella_has_her_own_space(self):
        self.assertEqual(hs.project_of({"name": "stella", "cwd": str(HOME)}), "stella")

    def test_outside_github_uses_the_directory_name(self):
        self.assertEqual(hs.project_of({"name": "scratch", "cwd": "/tmp/notes"}), "notes")


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
