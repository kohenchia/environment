"""kc-shot picks the screenshot you just took."""

import importlib.machinery
import importlib.util
import os
import tempfile
import time
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "bin/kc-shot"
loader = importlib.machinery.SourceFileLoader("kc_shot", str(PATH))
ks = importlib.util.module_from_spec(importlib.util.spec_from_loader("kc_shot", loader))
loader.exec_module(ks)


class Newest(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.now = time.time()

    def shot(self, name, age):
        p = self.d / name
        p.write_bytes(b"png")
        os.utime(p, (self.now - age, self.now - age))
        return p

    def test_the_newest_recent_screenshot_wins(self):
        self.shot("Screenshot 2026-10-18 at 3.15.49 PM.png", 90)
        newest = self.shot("Screenshot 2026-10-18 at 3.45.00 PM.png", 10)
        self.assertEqual(ks.newest_desktop_shot(self.d, self.now), newest)

    def test_an_old_screenshot_is_not_the_one_you_just_took(self):
        self.shot("Screenshot 2026-10-18 at 3.15.49 PM.png", 600)
        self.assertIsNone(ks.newest_desktop_shot(self.d, self.now))

    def test_other_files_are_ignored(self):
        self.shot("notes.png", 5)
        self.shot("Screenshot clip.txt", 5)
        self.assertIsNone(ks.newest_desktop_shot(self.d, self.now))


if __name__ == "__main__":
    unittest.main()
