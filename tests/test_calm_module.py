"""The /calm module must pass Claude Code's static check, or the module does not load at all, and silently.

Claude Code 2.1.293 reads a hooks module's source before it runs it and refuses (the transcript says "reload failed" only
when a running session reloads it) a module that breaks these rules, which this test encodes from the messages it gave:
  - a function that is handed `$` is declared at the top of the file (not inside `register`);
  - a name that is handed `$` as a function is not also assigned elsewhere (a local variable of the same name is enough);
  - one hook per event unless the hooks are told apart by a matcher.
It is a guard against the two ways the module failed to load on 2026-10-22 and 23; `tsc` against the engine's types is the
other half (docs/claude-code.md says how to run both, and how to load the module in a throwaway session).
"""

import re
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parent.parent / "claude/plugin/hooks/stella-calm.tsx"


def source() -> list[str]:
    return MODULE.read_text().splitlines()


def code(lines: list[str]) -> list[str]:
    """The lines without comments and string/template contents that could hold a stray `(`."""
    out, in_block = [], False
    for line in lines:
        if in_block:
            in_block = "*/" not in line
            out.append("")
            continue
        if line.lstrip().startswith("/*"):
            in_block = "*/" not in line
            out.append("")
            continue
        out.append(re.sub(r"//.*$", "", line))
    return out


class CalmModule(unittest.TestCase):
    def test_helpers_that_take_the_engine_are_declared_at_the_top_of_the_file(self):
        bad = []
        for n, line in enumerate(code(source()), 1):
            m = re.match(r"^(\s+)(?:async\s+)?(?:function\s+(\w+)\s*\(|(?:const|let|var)\s+(\w+)\s*(?::[^=]+)?=\s*(?:async\s*)?\()\s*\$", line)
            if m:
                bad.append(f"line {n}: {line.strip()[:80]}")
        self.assertEqual(bad, [], "declared inside another function; move it to the top level")

    def test_a_function_handed_the_engine_is_never_assigned(self):
        text = "\n".join(code(source()))
        helpers = set(re.findall(r"^(?:async\s+)?function\s+(\w+)\s*\(\s*\$", text, re.M))
        self.assertTrue(helpers, "expected helper functions that take $")
        clashes = [h for h in helpers if re.search(rf"(?:\blet|\bvar|\bconst)\s+{h}\b|\b{h}\s*=(?!=)", text)]
        self.assertEqual(clashes, [], "a local named like a helper makes the engine treat the helper as assigned")

    def test_each_event_has_one_hook_unless_a_matcher_tells_them_apart(self):
        text = "\n".join(code(source()))
        plain = re.findall(r"\bon\(\s*'([\w.]+)'\s*,\s*(?:async\s+)?(?:function|\()", text)
        dupes = sorted({e for e in plain if plain.count(e) > 1})
        self.assertEqual(dupes, [], "the same event registered twice without a matcher")

    def test_the_module_is_the_one_the_plugin_names(self):
        hooks = (MODULE.parent / "hooks.json").read_text()
        self.assertIn('"./stella-calm.tsx"', hooks)


if __name__ == "__main__":
    unittest.main()
