"""herdr-space: moving a space, over a fake herdr socket."""

import importlib.machinery
import importlib.util
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "bin/herdr-space"
loader = importlib.machinery.SourceFileLoader("herdr_space", str(PATH))
hs = importlib.util.module_from_spec(importlib.util.spec_from_loader("herdr_space", loader))
loader.exec_module(hs)


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
