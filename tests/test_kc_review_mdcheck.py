"""kc-review's Obsidian text check: bare <tags> and table pipes. Run: python3 -m unittest discover tests"""

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "claude/skills/kc-review/mdcheck.py"


def check(text, *args):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "report.md"
        p.write_text(textwrap.dedent(text))
        r = subprocess.run([sys.executable, str(TOOL), *args, str(p)], capture_output=True, text=True, check=False)
        return r, p.read_text()


class BareTags(unittest.TestCase):
    def test_a_placeholder_in_a_heading_is_flagged_with_its_line(self):
        r, _ = check("""\
            ---
            title: x
            ---
            # namespaced settings (--train-<key>, --<step>-<key>)
            """)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.count("bare"), 3)
        self.assertIn(":4: bare '<key>'", r.stdout)

    def test_every_safe_form_passes(self):
        r, _ = check("""\
            # run `<pr>` in the heading
            Inline `<pr>`, entity &lt;pr&gt;, backslash \\<pr>, a<br>break, math 3 < 5 and x<-1 and <0.60.
            A span across
            lines `<date>-<slug>
            .yaml` is code.

            ```
            <feature> in a fence
            ```

            ~~~md
            <feature> in a tilde fence
            ~~~

            | cell | cell |
            |---|---|
            | `<pr>` | one<br>two |

            <!-- from: a.log --> and <https://example.com> and <dataSource:slack>
            """)
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_a_tag_in_a_table_cell_a_list_and_a_callout_is_flagged(self):
        r, _ = check("""\
            | a | b |
            |---|---|
            | x | needs <the inference object id> |

            - item <target> here

            > [!note] Run <pr> now
            """)
        self.assertEqual(r.stdout.count("bare"), 3)

    def test_an_unclosed_angle_that_starts_a_name_is_reported_but_not_fixed(self):
        r, out = check("a <feature and more\n", "--fix")
        self.assertEqual(r.returncode, 1)
        self.assertIn("unclosed", r.stdout)
        self.assertEqual(out, "a <feature and more\n")

    def test_allow_names_an_old_page_s_html(self):
        r, _ = check("<svg><rect/></svg> text\n", "--allow", "svg,rect")
        self.assertEqual(r.returncode, 0)

    def test_a_details_block_is_flagged(self):
        r, _ = check("<details>\n\n**x**\n\n</details>\n")
        self.assertEqual(r.stdout.count("bare"), 2)

    def test_fix_wraps_only_the_tags_and_changes_nothing_else(self):
        before = "# a (--train-<key>, --<step>-<key>) and `<ok>`\n\ncd <worktree> && run `x` <scratch opt.cfg>\n"
        r, after = check(before, "--fix")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(after, "# a (--train-`<key>`, --`<step>`-`<key>`) and `<ok>`\n\ncd `<worktree>` && run `x` `<scratch opt.cfg>`\n")


class TablePipes(unittest.TestCase):
    def test_a_pipe_inside_backticks_or_a_wikilink_alias_splits_the_cell(self):
        r, _ = check("""\
            | a | b |
            |---|---|
            | x | `a|b` |
            | y | [[Note|alias]] |
            | z | `a\\|b` and [[Note\\|alias]] |
            """)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.count("table row has 3 cells"), 2)
        self.assertNotIn(":5:", r.stdout)


if __name__ == "__main__":
    unittest.main()
