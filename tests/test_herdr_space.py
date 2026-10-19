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
    SPACES = [{"workspace_id": i, "label": i} for i in "abcd"]

    def fake(self, focused):
        sent = []
        ws = [dict(w, focused=(w["workspace_id"] == focused)) for w in self.SPACES]

        def rpc(method, params):
            sent.append((method, params))
            return {"workspaces": ws} if method == "workspace.list" else {}

        hs.rpc = rpc
        return sent

    def moved(self, sent):
        return [p for m, p in sent if m == "workspace.move_block"]

    def test_down_goes_before_the_space_after_the_next_one(self):
        sent = self.fake("b")  # a b c d  ->  a c b d: b goes before d
        hs.move("down")
        self.assertEqual(self.moved(sent), [{"workspace_ids": ["b"], "before_workspace_id": "d"}])

    def test_down_past_the_last_but_one_goes_to_the_end(self):
        sent = self.fake("c")  # a b c d  ->  a b d c: c goes to the end
        hs.move("down")
        self.assertEqual(self.moved(sent), [{"workspace_ids": ["c"], "before_workspace_id": None}])

    def test_up_goes_before_the_previous_space(self):
        sent = self.fake("c")  # a b c d  ->  a c b d: c goes before b
        hs.move("up")
        self.assertEqual(self.moved(sent), [{"workspace_ids": ["c"], "before_workspace_id": "b"}])

    def test_the_first_space_cannot_move_up_and_the_last_cannot_move_down(self):
        first = self.fake("a")
        hs.move("up")
        last = self.fake("d")
        hs.move("down")
        self.assertEqual((first, last), ([("workspace.list", {})], [("workspace.list", {})]))


if __name__ == "__main__":
    unittest.main()
