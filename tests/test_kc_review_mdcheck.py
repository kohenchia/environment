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


class SlackBlock(unittest.TestCase):
    BLOCK = "## Slack context\n\n<dataSource:slack>\n- a said b\n</dataSource:slack>\n\n<dataPolicy:slack>\npolicy\n</dataPolicy:slack>\n"

    def test_text_after_the_slack_block_is_flagged(self):
        r, _ = check(self.BLOCK + "\n## Evidence and coverage\n\nlost to the renderer\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn(":10: text after </dataPolicy:slack>", r.stdout)

    def test_a_fenced_slack_block_is_code_and_may_have_text_after_it(self):
        r, _ = check("## Slack\n\n```\n" + self.BLOCK + "```\n\nmore text\n")
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_an_unclosed_slack_block_is_flagged(self):
        r, _ = check("# note\n\n<dataSource:slack>\n<dataPolicy:slack>\np\n")
        self.assertEqual(r.returncode, 1)

    def test_the_slack_block_last_passes(self):
        r, _ = check("## Evidence\n\nfine\n\n" + self.BLOCK)
        self.assertEqual((r.returncode, r.stdout), (0, ""))


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


class TablesInLists(unittest.TestCase):
    THREE = (
        "5. **Where it goes wrong**\n"
        "\n"
        "   | You run | Result |\n"
        "   |---|---|\n"
        "   | `a` | one |\n"
        "6. next\n"
    )

    def test_a_table_indented_3_under_a_numbered_item_is_flagged_at_its_header(self):
        r, _ = check(self.THREE)
        self.assertEqual(r.returncode, 1)
        self.assertIn(":3: table inside a list item is indented 3 spaces", r.stdout)

    def test_a_table_indented_2_under_a_bullet_is_flagged(self):
        r, _ = check("- item\n\n  | a | b |\n  |---|---|\n  | 1 | 2 |\n")
        self.assertIn(":3: table inside a list item is indented 2 spaces", r.stdout)

    def test_4_spaces_or_a_tab_after_a_blank_line_passes(self):
        r, _ = check("5. item\n\n    | a | b |\n    |---|---|\n    | 1 | 2 |\n\n- bullet\n\n\t| a | b |\n\t|---|---|\n")
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_no_blank_line_before_a_table_in_a_list_item_is_flagged(self):
        r, _ = check("5. item\n    | a | b |\n    |---|---|\n    | 1 | 2 |\n")
        self.assertIn(":2: no blank line before the table", r.stdout)

    def test_a_table_after_the_list_or_outside_one_is_not_flagged(self):
        r, _ = check("1. item\n2. item\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nText\n\n  | a | b |\n  |---|---|\n")
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_a_table_in_a_fence_is_not_read(self):
        r, _ = check("1. item\n\n   ```\n   | a | b |\n   |---|---|\n   ```\n")
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_fix_reindents_every_row_to_4_and_adds_the_blank_line_and_nothing_else(self):
        before = "5. item\n   | a | b |\n   |---|---|\n   | `x` | y |\n6. next\n\n| top | t |\n|---|---|\n"
        r, after = check(before, "--fix")
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertEqual(after, "5. item\n\n    | a | b |\n    |---|---|\n    | `x` | y |\n6. next\n\n| top | t |\n|---|---|\n")

    def test_fix_leaves_a_correct_file_untouched(self):
        text = "5. item\n\n    | a | b |\n    |---|---|\n    | 1 | 2 |\n"
        r, after = check(text, "--fix")
        self.assertEqual(after, text)

    def test_the_cell_count_is_still_checked_for_a_nested_table(self):
        r, _ = check("5. item\n\n    | a | b |\n    |---|---|\n    | `x|y` | z |\n")
        self.assertIn(":5: table row has 3 cells", r.stdout)


if __name__ == "__main__":
    unittest.main()


class Frontmatter(unittest.TestCase):
    def test_an_unquoted_value_with_a_colon_is_flagged_at_its_line(self):
        r, _ = check("""\
            ---
            pr: org/repo#41
            updated: 2026-11-03 (Kohen's replies: ask 3 dropped)
            ---
            # report
            """)
        self.assertEqual(r.returncode, 1)
        self.assertIn(":3: unquoted frontmatter value holds ': '", r.stdout)

    def test_quoted_plain_and_list_values_pass(self):
        r, _ = check("""\
            ---
            verdict: "✅ merge with fixes · 1 blocks merge: one test"
            note: 'it: works'
            url: https://example.com/a:b
            reviewed: 2026-10-29 05:36
            tags: [review, notes]
            items:
              - plain item
            body: |
              any: text here
            ---
            # report
            """)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_an_indicator_an_open_quote_and_a_comment_are_flagged(self):
        r, _ = check("""\
            ---
            a: @mention
            b: "never closed
            c: issue #42
            ---
            """)
        self.assertEqual(r.returncode, 1)
        self.assertIn(":2: unquoted frontmatter value starts with '@'", r.stdout)
        self.assertIn(":3: frontmatter value opens a \" quote it never closes", r.stdout)
        self.assertIn(":4: unquoted frontmatter value holds ' #'", r.stdout)

    def test_an_unclosed_frontmatter_is_flagged(self):
        r, _ = check("""\
            ---
            pr: x
            # report
            """)
        self.assertIn(":1: frontmatter opens with --- and never closes", r.stdout)

    def test_a_colon_in_the_body_is_not_frontmatter(self):
        r, _ = check("""\
            # report
            updated: 2026-11-03 (replies: ask 3)
            """)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_fix_double_quotes_the_value_and_changes_nothing_else(self):
        r, text = check("""\
            ---
            pr: org/repo#41
            updated: 2026-11-03 (Kohen's replies: ask "3" dropped)
            ---
            # report
            """, "--fix")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(text, textwrap.dedent("""\
            ---
            pr: org/repo#41
            updated: "2026-11-03 (Kohen's replies: ask \\"3\\" dropped)"
            ---
            # report
            """))
