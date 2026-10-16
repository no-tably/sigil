"""The core glyph kinds' brackets are kept once (sigil.core.lex.GLYPH_BRACKETS):
the parser's bracket → kind, the tokenizer's closer, lint's name patterns, the
model's label brackets and the export's glyph text all read that one table."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sigil.core import graph, lex  # noqa: E402
from sigil.model import systems  # noqa: E402
from sigil.core.graph import Node  # noqa: E402


class OneBracketTable(unittest.TestCase):
    def test_views_follow_the_table(self):
        for kind, (open_, close) in lex.GLYPH_BRACKETS.items():
            with self.subTest(kind=kind):
                self.assertEqual(lex.OPEN_TO_KIND[open_], kind)
                self.assertEqual(lex.CLOSER[open_], close)
                self.assertEqual(graph.GLYPH_KINDS[kind], {"open": open_, "close": close})
        self.assertEqual(set(lex.OPEN_TO_KIND.values()), set(lex.GLYPH_BRACKETS))

    def test_name_patterns_read_one_glyph(self):
        line = "[A] -> (b) ~{x} <E> |S| (a(b))"
        found = {kind: [m.group(1) for m in pat.finditer(line)]
                 for kind, pat in lex.GLYPH_PATTERNS.items()}
        self.assertEqual(found, {"service": ["A"], "data": ["x"], "event": ["E"],
                                 "actor": ["b", "b"], "store": ["S"]})

    def test_export_glyph_text(self):
        for kind, (open_, close) in lex.GLYPH_BRACKETS.items():
            node = Node(id="n", name="N", kind=kind)
            self.assertEqual(systems.glyph([node]), f"{open_}N{close}")


if __name__ == "__main__":
    unittest.main()
