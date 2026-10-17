"""Tests for kit.doc_title / kit.doc_mode: a document's head read through core's
comment reading (lex.comment_start, lex.is_mode_line).

Covers:
  - the title is the first own-line `# comment`, blank and mode lines skipped, a
    heading's extra `#`s dropped; `#&` declarations are stepped over with the
    `{ … }` block one opens (one line or many, spaced or not); a dialect's
    comment markers read as comments; a statement, a trailing comment or a bare
    `#` before it gives "";
  - the mode is the first `#!` line before any statement (comments and `#&`
    lines skipped), its first word only.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sigil.present import kit  # noqa: E402


class TestDocTitle(unittest.TestCase):
    def test_first_comment_after_mode_lines(self):
        self.assertEqual(kit.doc_title("#!spec\n\n  # A shop\n# more\n[A]\n"), "A shop")

    def test_heading_hashes_dropped(self):
        self.assertEqual(kit.doc_title("## Shop ##\n"), "Shop ##")

    def test_declarations_stepped_over(self):
        for text in ("#&decl\n# t\n", "#!spec\n#& header { a: b }\n\n# t\n",
                     "#!spec\n#&header~{ a: b }\n# t\n",
                     "#!spec\n#& header {\n  a: {b}\n  c: \"}\"\n}\n# t\n[A]\n",
                     "#& one\n#& two ~{\n}\n# t\n"):
            with self.subTest(text=text):
                self.assertEqual(kit.doc_title(text), "t")

    def test_a_dialect_s_comment_markers(self):
        d = types.ModuleType("probe_dialect")
        d.COMMENT_MARKERS = [r"//"]
        text = "#!spec\n#& header { a: b }\n\n// TITLE — more\n// on\n[A]\n"
        self.assertEqual(kit.doc_title(text, d), "TITLE — more")
        self.assertEqual(kit.doc_title(text), "")

    def test_no_title(self):
        for text in ("", "[A] -> [B]\n# late\n", "[A]  # trailing\n",
                     "#\n# t\n", '"#x"\n', "#& header {\n# inside\n", "--- S ---\n# t\n"):
            with self.subTest(text=text):
                self.assertEqual(kit.doc_title(text), "")


class TestDocMode(unittest.TestCase):
    def test_mode_after_comments(self):
        self.assertEqual(kit.doc_mode("# title\n#\n\n  #!craft  extra\n[A]\n"), "#!craft")

    def test_no_mode_after_a_declaration(self):
        self.assertEqual(kit.doc_mode("#& header\n#!craft\n[A]\n"), "")

    def test_no_mode_after_a_statement(self):
        self.assertEqual(kit.doc_mode("[A]\n#!spec\n"), "")
        self.assertEqual(kit.doc_mode("# only a comment\n"), "")


if __name__ == "__main__":
    unittest.main()
