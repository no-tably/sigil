"""render.py and lint.py read an op verb by the same rule.

lint.py is a standalone tool, so it keeps its own copy of render's verb rule
(`_is_mark`, `_marks_follow_letters`, `_VerbPattern`). One corpus drives both
copies here: every case must read the same verb (or no op-call) in each.
"""
import sys
import unicodedata
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lint    # noqa: E402
import render  # noqa: E402

# (verb as written, the verb an op-call reads, or None when it is no op-call)
CORPUS = [
    ("run", "run"),
    ("_walk", "_walk"),
    ("短縮", "短縮"),
    ("ガス", "ガス"),                 # ガス, composed
    ("ガス", "ガス"),     # カ + U+3099 (Mn) + ス
    ("कि", "कि"),                 # क + U+093F (Mc)
    ("a⃝b", "a⃝b"),                         # a + U+20DD (Me) + b
    ("a⃝", "a⃝"),                           # an enclosing mark ends the verb
    ("é⃝", "é⃝"),               # Me after another mark
    ("x9", "x9"),
    ("9x", None),                                     # a digit never starts a verb
    ("́x", None),                                # a mark first (Mn)
    ("⃝x", None),                                # a mark first (Me)
    ("a→b", None),                               # a symbol (Sm)
    ("a©b", None),                               # a symbol (So)
    ("a　b", None),                               # an ideographic space
]

# Each case dotted after a namespace, as `op ns.verb(…)`.
# (A segment after the dot starting with a digit is left out: see
# test_a_dotted_digit_segment_is_lint_strictness.)
DOTTED = [(f"ns.{v}", f"ns.{want}" if want else None) for v, want in CORPUS
          if not v[0].isdigit()]
# A mark after the dot joins no letter.
DOTTED += [("ns.́b", None), ("ns.⃝b", None), ("x.́", None)]


def verb(rx, text):
    m = rx.match(text)
    return m.group("verb") if m else None


class VerbRulesAgree(unittest.TestCase):
    def test_is_mark_agrees_on_every_code_point(self):
        for cp in range(0x110000):
            ch = chr(cp)
            if render._is_mark(ch) != lint._is_mark(ch):
                self.fail(f"U+{cp:04X} {unicodedata.category(ch)}")

    def test_enclosing_marks_are_marks(self):
        for ch in ("⃝", "⃞", "҈"):
            self.assertEqual(unicodedata.category(ch), "Me")
            self.assertTrue(render._is_mark(ch))
            self.assertTrue(lint._is_mark(ch))

    def test_a_flow_target_reads_one_verb_in_both(self):
        for written, want in CORPUS + DOTTED:
            with self.subTest(verb=written):
                self.assertEqual(verb(render.OP_TARGET_RE, f"{written}()"), want)
                self.assertEqual(verb(lint._OP_HEAD_RE, f"{written}("), want)

    def test_an_op_payload_reads_one_verb_in_both(self):
        for written, want in CORPUS:
            with self.subTest(verb=written):
                self.assertEqual(verb(render.OP_TARGET_RE, f"{written}({{X}})"), want)
                self.assertEqual(verb(lint._INT_OP_RE, f"{written}({{X}})"), want)
        for written, want in DOTTED:
            with self.subTest(verb=written):
                self.assertEqual(verb(render.OP_TARGET_RE, f"op {written}({{X}})"), want)
                self.assertEqual(verb(lint._EXT_OP_RE, f"op {written}({{X}})"), want)

    def test_marks_follow_letters_agrees(self):
        for written, _ in CORPUS + DOTTED:
            with self.subTest(verb=written):
                self.assertEqual(render._marks_follow_letters(written),
                                 lint._marks_follow_letters(written))

    def test_a_dotted_digit_segment_is_lint_strictness(self):
        # Both read `ns.9x(` as a flow target's head; only lint's payload rule
        # asks every dotted segment to start with a letter (and reports it).
        self.assertEqual(verb(render.OP_TARGET_RE, "ns.9x()"), "ns.9x")
        self.assertEqual(verb(lint._OP_HEAD_RE, "ns.9x("), "ns.9x")
        self.assertIsNone(verb(lint._EXT_OP_RE, "op ns.9x({X})"))


class EnclosingMarkVerbs(unittest.TestCase):
    VERB = "a⃝b"

    def test_render_draws_one_op_call(self):
        g = render.parse_document(f"[Api] -> {self.VERB}({{Job}})\n")
        self.assertEqual([e.payload for e in g.edges], [f"{self.VERB}({{Job}})"])

    def test_lint_classifies_it_as_an_op_call(self):
        self.assertEqual(lint._classify_payload(f"{self.VERB}({{X}})")[0], "int-op")
        self.assertEqual(lint._classify_payload(f"op ns.{self.VERB}({{X}})")[0], "ext-op")
        self.assertEqual(lint._classify_payload("op ns.⃝b({X})")[0], "ext-op-bad")


if __name__ == "__main__":
    unittest.main()
