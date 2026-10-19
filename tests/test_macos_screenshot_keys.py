"""macos-screenshot-keys: the plain shortcuts copy to the clipboard, the Ctrl ones save a file."""

import importlib.machinery
import importlib.util
import plistlib
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin/macos-screenshot-keys"
loader = importlib.machinery.SourceFileLoader("macos_screenshot_keys", str(BIN))
mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
loader.exec_module(mod)

PLAIN, WITH_CTRL = mod.PLAIN, mod.WITH_CTRL


def entry(ascii_code, key_code, mods, enabled=True):
    return {"enabled": enabled, "value": {"parameters": [ascii_code, key_code, mods], "type": "standard"}}


# What macOS does when nothing was ever changed: no entry, so the shipped defaults (plain = file).
WANTED = {"29": entry(51, 20, PLAIN), "31": entry(52, 21, PLAIN), "28": entry(51, 20, WITH_CTRL),
          "30": entry(52, 21, WITH_CTRL)}


class Drift(unittest.TestCase):
    def test_nothing_written_means_all_four_are_wrong(self):
        self.assertEqual(sorted(mod.drift({})), [28, 29, 30, 31])

    def test_wanted_state_has_no_drift(self):
        self.assertEqual(mod.drift(WANTED), [])

    def test_only_the_wrong_ones_are_reported(self):
        state = dict(WANTED, **{"30": entry(52, 21, PLAIN)})  # the shipped default for "area to a file"
        self.assertEqual(mod.drift(state), [30])

    def test_a_disabled_entry_is_wrong(self):
        state = dict(WANTED, **{"31": entry(52, 21, PLAIN, enabled=False)})
        self.assertEqual(mod.drift(state), [31])

    def test_the_clipboard_pair_is_the_plain_chord(self):
        by_name = {v[0]: v[3] for v in mod.SHORTCUTS.values()}
        self.assertEqual(by_name["selected area to the clipboard"], PLAIN)
        self.assertEqual(by_name["selected area to a file"], WITH_CTRL)
        self.assertEqual(PLAIN, 1048576 + 131072)  # Cmd+Shift
        self.assertEqual(WITH_CTRL, PLAIN + 262144)  # Cmd+Ctrl+Shift

    def test_entry_xml_is_a_valid_plist_value(self):
        for hid in mod.SHORTCUTS:
            value = plistlib.loads(f"<plist>{mod.entry_xml(hid)}</plist>".encode())
            self.assertTrue(value["enabled"])
            self.assertEqual(value["value"]["parameters"], list(mod.SHORTCUTS[hid][1:]))


@unittest.skipUnless(sys.platform == "darwin", "writes macOS hotkeys")
class Cli(unittest.TestCase):
    """The command, with a fake `defaults` that serves a plist and records the writes."""

    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.dir = Path(self.t.name)
        self.log = self.dir / "writes.log"
        self.plist = self.dir / "hotkeys.plist"
        (self.dir / "defaults").write_text(f'''#!/bin/sh
case "$1" in
  export) cat {self.plist} ;;
  write) shift; echo "$*" >> {self.log} ;;
esac
''')
        (self.dir / "defaults").chmod(0o755)
        self.set_state({})

    def tearDown(self):
        self.t.cleanup()

    def set_state(self, hotkeys):
        self.plist.write_bytes(plistlib.dumps({"AppleSymbolicHotKeys": hotkeys}))

    def run_cmd(self, *args):
        return subprocess.run(["python3", str(BIN), *args], capture_output=True, text=True,
                              env={"PATH": f"{self.dir}:/usr/bin:/bin"})

    def writes(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_check_fails_on_a_fresh_machine_and_writes_nothing(self):
        r = self.run_cmd("--check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("selected area to the clipboard", r.stdout)
        self.assertEqual(self.writes(), [])

    def test_apply_writes_the_four_shortcuts(self):
        r = self.run_cmd()
        self.assertEqual(r.returncode, 0, r.stderr)
        w = self.writes()
        self.assertEqual(len(w), 4)
        ids = sorted(int(re.match(rf"{mod.DOMAIN} AppleSymbolicHotKeys -dict-add (\d+) ", line).group(1)) for line in w)
        self.assertEqual(ids, [28, 29, 30, 31])
        area_clip = next(line for line in w if " -dict-add 31 " in line)
        self.assertIn(f"<integer>{PLAIN}</integer>", area_clip)

    def test_apply_is_idempotent(self):
        self.set_state(WANTED)
        r = self.run_cmd()
        self.assertEqual(r.returncode, 0)
        self.assertIn("already set", r.stdout)
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.run_cmd("--check").returncode, 0)

    def test_only_the_drifted_shortcut_is_written(self):
        self.set_state(dict(WANTED, **{"30": entry(52, 21, PLAIN)}))
        self.run_cmd()
        w = self.writes()
        self.assertEqual(len(w), 1)
        self.assertIn(" -dict-add 30 ", w[0])

    def test_unknown_arguments_are_refused(self):
        self.assertEqual(self.run_cmd("--nope").returncode, 2)


if __name__ == "__main__":
    unittest.main()
