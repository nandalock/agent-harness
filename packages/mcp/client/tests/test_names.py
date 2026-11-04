import unittest

from agent_platform_mcp_client import public_tool_name


class NameTests(unittest.TestCase):
    def test_clean_names_are_preserved(self):
        self.assertEqual(public_tool_name("", "search_papers"), "search_papers")
        self.assertEqual(public_tool_name("mcp__demo__", "read_file"), "mcp__demo__read_file")

    def test_invalid_characters_are_normalized_with_a_stable_hash(self):
        first = public_tool_name("", "tool.with.dot")
        second = public_tool_name("", "tool.with.dot")
        self.assertEqual(first, second)
        self.assertNotEqual(first, "tool_with_dot")
        self.assertLessEqual(len(first), 64)
        self.assertRegex(first, r"^[A-Za-z0-9_-]+$")

    def test_long_names_are_truncated_without_collisions(self):
        a = public_tool_name("", "x" * 80)
        b = public_tool_name("", "x" * 79 + "y")
        self.assertLessEqual(len(a), 64)
        self.assertLessEqual(len(b), 64)
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
