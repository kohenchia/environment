"""kc-review's use-case helper: capture a case at base and head, pull excerpts, check a page. Run: python3 -m unittest discover tests"""

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "claude/skills/kc-review/usecases.py"
sys.path.insert(0, str(TOOL.parent))
import usecases


def run(*a, cwd=None):
    return subprocess.run([sys.executable, str(TOOL), *a], capture_output=True, text=True, cwd=cwd, check=False)


class Capture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.base, self.head = self.tmp / "base", self.tmp / "head"
        for side, code in ((self.base, 1), (self.head, 0)):
            side.mkdir()
            (side / "tool.sh").write_text(
                f"printf '\\033[1mstep type\\033[0m  BATCH\\n'; echo 'warn: careful' >&2; exit {code}\n")
        self.case = self.tmp / "usecases/A1"

    def test_each_side_gets_its_log_with_ansi_stripped_and_the_exit_code_last(self):
        r = run("capture", str(self.case), "--side", f"base={self.base}", "--side", f"head={self.head}",
                "--shown", "uv run tool --dry-run", "--", "sh", "tool.sh")
        self.assertEqual(r.returncode, 0, r.stderr)
        base = (self.case / "base.log").read_text().splitlines()
        self.assertEqual(base[-1], "EXIT 1")
        self.assertIn("step type  BATCH", base)
        self.assertIn("warn: careful", base)
        self.assertEqual((self.case / "head.log").read_text().splitlines()[-1], "EXIT 0")
        self.assertEqual((self.case / "cmd.txt").read_text().strip(), "uv run tool --dry-run")
        self.assertIn("base EXIT 1", r.stdout)
        self.assertIn("head EXIT 0", r.stdout)

    def test_a_control_side_adds_a_log_and_keeps_the_shown_command(self):
        run("capture", str(self.case), "--side", f"base={self.base}", "--shown", "uv run tool", "--", "sh", "tool.sh")
        run("capture", str(self.case), "--side", f"base-nooption={self.base}", "--", "sh", "tool.sh")
        self.assertTrue((self.case / "base-nooption.log").exists())
        self.assertEqual((self.case / "cmd.txt").read_text().strip(), "uv run tool")

    def test_a_command_that_reads_stdin_does_not_hang(self):
        r = subprocess.run([sys.executable, str(TOOL), "capture", str(self.case), "--side", f"base={self.base}",
                            "--", "cat"], capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.case / "base.log").read_text(), "EXIT 0\n")

    def test_a_side_needs_a_name_and_an_existing_directory(self):
        r = run("capture", str(self.case), "--side", f"base={self.tmp / 'missing'}", "--", "true")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("missing", r.stderr)


class Excerpts(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.log = self.tmp / "head.log"
        self.log.write_text(textwrap.dedent("""\
            tool: warning: a field no object carries
            ── [job] shop:nightly ──
              step type          BATCH
              model              remote,name=v11
              instruction        A = 1
                                 B = 2
              input map          X = Y
                                 Z = W
            ── [check] shop:nightly ──
              step type          BATCH
            tool: refused: the second line
            EXIT 1
            """))

    def test_pull_returns_the_nth_matching_line_verbatim(self):
        self.assertEqual(usecases.pull(self.log, r"refused", prefix="tool:"), "tool: refused: the second line")
        self.assertEqual(usecases.pull(self.log, r"^tool:", nth=1), "tool: refused: the second line")

    def test_pull_stops_loudly_when_nothing_matches(self):
        with self.assertRaises(SystemExit) as e:
            usecases.pull(self.log, r"no such text")
        self.assertIn("no such text", str(e.exception))

    def test_block_keeps_the_chosen_rows_and_their_continuation_lines(self):
        got = usecases.block(self.log, r"── \[job\]", keep=("step type", "input map"))
        self.assertEqual(got.splitlines(), [
            "── [job] shop:nightly ──",
            "  step type          BATCH",
            "  input map          X = Y",
            "                     Z = W",
        ])

    def test_block_without_keep_takes_the_whole_block(self):
        self.assertEqual(len(usecases.block(self.log, r"── \[job\]").splitlines()), 7)

    def test_exit_code_is_the_capture_marker_on_the_last_line(self):
        self.assertEqual(usecases.exit_code(self.log), 1)

    def test_clip_marks_what_it_cut(self):
        self.assertEqual(usecases.clip("abcdefghij", 6), "abcd …")
        self.assertEqual(usecases.clip("abc", 6), "abc")

    def test_fence_names_its_source_for_the_check(self):
        got = usecases.fence("X = Y", source="slice/A1/head.log")
        self.assertEqual(got, "<!-- from: slice/A1/head.log -->\n```text\nX = Y\n```")


class Check(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ev = self.tmp / "usecases"
        (self.ev / "A1").mkdir(parents=True)
        (self.ev / "A2").mkdir()
        (self.ev / "A1/head.log").write_text("tool: refused: no default object of target 12 carries it\n  input map  X = Y\nEXIT 1\n")
        (self.ev / "A2/head.log").write_text("tool: warning: only in A2\nEXIT 0\n")
        self.page = self.tmp / "page.md"

    def check(self, body):
        self.page.write_text(textwrap.dedent(body))
        return run("check", str(self.page), str(self.ev))

    def test_verbatim_excerpts_pass(self):
        r = self.check("""\
            # Use cases
            ```text
            tool: refused: no default object of target 12 carries it
              input map  X = Y
            ```
            """)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("2 lines checked", r.stdout)

    def test_a_retyped_line_fails_with_its_page_line(self):
        r = self.check("""\
            # Use cases

            ```text
            tool: refused: no default object of the target carries it
            ```
            """)
        self.assertEqual(r.returncode, 1)
        self.assertIn("page.md:4", r.stdout)

    def test_an_ellipsis_marks_cut_text_and_the_rest_must_match_in_order(self):
        ok = self.check("```text\ntool: refused: no default … carries it\n```\n")
        self.assertEqual(ok.returncode, 0, ok.stdout)
        bad = self.check("```text\ntool: carries it … refused\n```\n")
        self.assertEqual(bad.returncode, 1)

    def test_a_named_source_restricts_where_a_line_may_come_from(self):
        r = self.check("<!-- from: A1/head.log -->\n```text\ntool: warning: only in A2\n```\n")
        self.assertEqual(r.returncode, 1)
        ok = self.check("<!-- from: A2 -->\n```text\ntool: warning: only in A2\n```\n")
        self.assertEqual(ok.returncode, 0, ok.stdout)

    def test_a_fragment_of_a_line_does_not_pass(self):
        r = self.check("```text\n  input map\nno default object\n```\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("2 not found", r.stdout)

    def test_cut_text_is_anchored_at_the_ends_it_does_not_mark(self):
        self.assertEqual(self.check("```text\ntool: refused: no default …\n```\n").returncode, 0)
        self.assertEqual(self.check("```text\n… carries it\n```\n").returncode, 0)
        self.assertEqual(self.check("```text\nrefused: no default …\n```\n").returncode, 1)
        self.assertEqual(self.check("```text\ntool: refused: … target 12\n```\n").returncode, 1)

    def test_a_config_saved_with_line_numbers_matches_without_them(self):
        (self.ev / "A1/settings.txt").write_text("12:  nightly_job:\n13:    tier: release\n")
        r = self.check("```yaml\n  nightly_job:\n    tier: release\n```\n")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_changed_indentation_fails(self):
        r = self.check("```text\ninput map  X = Y\n```\n")
        self.assertEqual(r.returncode, 1)

    def test_annotations_are_skipped_only_in_config_blocks(self):
        self.assertEqual(self.check("```yaml\n# conf/x/settings.yaml\n```\n").returncode, 0)
        self.assertEqual(self.check("```json\n// conf/x/chain.json\n```\n").returncode, 0)
        r = self.check("```text\n# the job fails on the pod\n```\n")
        self.assertEqual(r.returncode, 1)

    def test_fences_in_lists_and_quotes_are_checked(self):
        r = self.check("- item\n\n  ```text\n  totally invented\n  ```\n")
        self.assertEqual(r.returncode, 1)
        r = self.check("> ```text\n> invented in a quote\n> ```\n")
        self.assertEqual(r.returncode, 1)
        ok = self.check("- item\n\n  ```text\n  tool: warning: only in A2\n  ```\n")
        self.assertEqual(ok.returncode, 0, ok.stdout)

    def test_a_source_outside_the_evidence_folder_is_refused(self):
        r = self.check("<!-- from: ../page.md -->\n```text\n<!-- from: ../page.md -->\n```\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("outside", r.stdout)

    def test_a_longer_fence_holds_a_shorter_one(self):
        r = self.check("````markdown\n```text\ntool: warning: only in A2\n```\n````\n")
        self.assertEqual(r.returncode, 1)  # the inner fence lines are page text, not captures

    def test_scripts_and_notes_are_not_evidence_unless_named(self):
        (self.ev / "gen_doc.py").write_text('add("jobs.<job>.inputs")\n')
        (self.ev / "A1/notes.md").write_text("the pod would fail\n")
        r = self.check("```text\njobs.<job>.inputs\nthe pod would fail\n```\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("2 not found", r.stdout)
        ok = self.check("<!-- from: A1/notes.md -->\n```text\nthe pod would fail\n```\n")
        self.assertEqual(ok.returncode, 0, ok.stdout)

    def test_a_missing_source_fails(self):
        r = self.check("<!-- from: A9/head.log -->\n```text\ntool: warning: only in A2\n```\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("A9/head.log", r.stdout)

    def test_annotation_lines_are_skipped_and_uncaptured_blocks_are_listed(self):
        r = self.check("""\
            ```yaml
            # conf/shop/settings.yaml (same before and after)
            ```
            <!-- not captured: the field name is a template -->
            ```text
            jobs.<job>.inputs
            ```
            """)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("1 block labelled not captured", r.stdout)
        self.assertIn("page.md:5", r.stdout)


if __name__ == "__main__":
    unittest.main()
