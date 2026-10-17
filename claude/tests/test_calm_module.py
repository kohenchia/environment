"""The calm module loads in every session, so it must stay render-only (W3-D20)."""

import re
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "plugin/hooks/stella-calm.tsx"


class RenderOnly(unittest.TestCase):
    def test_no_process_network_spawn_or_message_calls(self):
        self.assertEqual(re.findall(r"\$\.(process|http|agent\.spawn|session\.send|prompt\.submit)", MODULE.read_text()), [])

    def test_gated_on_flag_and_stellas_home(self):
        text = MODULE.read_text()
        self.assertIn("CLAUDE_CODE_ENABLE_FUNCTION_HOOKS", text)
        self.assertIn(".local/share/stella", text)


if __name__ == "__main__":
    unittest.main()
