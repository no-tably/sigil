"""Tests for kit.doc_title / kit.doc_mode: a document's head read through core's
comment reading (lex.comment_start, lex.is_mode_line).

Covers:
  - the title is the first own-line `# comment`, mode lines skipped, a heading's
    extra `#`s dropped; a statement, a trailing comment, a `#&` marker line or a
    bare `#` before it gives "";
  - the mode is the first `#!` line before any statement (comments and `#&`
    lines skipped), its first word only.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sigil.present import kit  # noqa: E402


class TestDocTitle(unittest.TestCase):
    def test_first_comment_after_mode_lines(self):
        self.assertEqual(kit.doc_title("#!spec\n\n  # A shop\n# more\n[A]\n"), "A shop")

    def test_heading_hashes_dropped(self):
        self.assertEqual(kit.doc_title("## Shop ##\n"), "Shop ##")

    def test_no_title(self):
        for text in ("", "[A] -> [B]\n# late\n", "[A]  # trailing\n", "#&decl\n# t\n",
                     "#\n# t\n", '"#x"\n'):
            with self.subTest(text=text):
                self.assertEqual(kit.doc_title(text), "")


class TestDocMode(unittest.TestCase):
    def test_mode_after_comments(self):
        self.assertEqual(kit.doc_mode("# title\n#&x\n\n  #!craft  extra\n[A]\n"), "#!craft")

    def test_no_mode_after_a_statement(self):
        self.assertEqual(kit.doc_mode("[A]\n#!spec\n"), "")
        self.assertEqual(kit.doc_mode("# only a comment\n"), "")


if __name__ == "__main__":
    unittest.main()
