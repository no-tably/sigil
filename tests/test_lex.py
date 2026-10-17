"""sigil.core.lex: the lexical tables the parser and lint both read, kept once.

The op-call verb rule (is_mark, marks_follow_letters, VerbPattern) reads one
corpus the same way wherever a verb stands: a flow's target, an op-call's head,
an op-call payload. The two comment readings and the two block-string folds stay
apart on purpose; a guard checks no reader keeps a table of its own.
"""
import re
import sys
import unicodedata
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sigil.analyse import lint  # noqa: E402
from sigil.analyse.lint import composition, hardening, lines, payloads, permissions, reading  # noqa: E402
from sigil.core import comments, lex, parse, statements, tokens, vocab  # noqa: E402

# (verb as written, the verb an op-call reads, or None when it is no op-call)
CORPUS = [
    ("run", "run"),
    ("_walk", "_walk"),
    ("短縮", "短縮"),
    ("ガス", "ガス"),                 # ガス, composed
    ("ガス", "ガス"),     # カ + U+3099 (Mn) + ス
    ("कि", "कि"),                 # क + U+093F (Mc)
    ("a⃝b", "a⃝b"),                         # a + U+20DD (Me) + b
    ("a⃝", "a⃝"),                           # an enclosing mark ends the verb
    ("é⃝", "é⃝"),               # Me after another mark
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
# test_a_dotted_digit_segment_is_one_malformed_op_call.)
DOTTED = [(f"ns.{v}", f"ns.{want}" if want else None) for v, want in CORPUS
          if not v[0].isdigit()]
# A mark after the dot joins no letter.
DOTTED += [("ns.́b", None), ("ns.⃝b", None), ("x.́", None)]

# Verbs holding a character that is neither a word character nor a mark after a letter.
NOT_MARKS_AFTER_LETTERS = ["́x", "⃝x", "a→b", "a©b", "a　b",
                           "ns.́b", "ns.⃝b", "x.́"]


def verb(rx, text):
    m = rx.match(text)
    return m.group("verb") if m else None


class VerbRule(unittest.TestCase):
    def test_marks_are_the_three_mark_categories(self):
        for cp in range(0x110000):
            ch = chr(cp)
            if lex.is_mark(ch) != (unicodedata.category(ch) in ("Mn", "Mc", "Me")):
                self.fail(f"U+{cp:04X} {unicodedata.category(ch)}")

    def test_enclosing_marks_are_marks(self):
        for ch in ("⃝", "⃞", "҈"):
            self.assertEqual(unicodedata.category(ch), "Me")
            self.assertTrue(lex.is_mark(ch))

    def test_a_flow_target_and_its_head_read_one_verb(self):
        for written, want in CORPUS + DOTTED:
            with self.subTest(verb=written):
                self.assertEqual(verb(lex.OP_TARGET_RE, f"{written}()"), want)
                self.assertEqual(verb(lex.OP_HEAD_RE, f"{written}("), want)

    def test_an_op_payload_reads_the_target_s_verb(self):
        for written, want in CORPUS:
            with self.subTest(verb=written):
                self.assertEqual(verb(lex.OP_TARGET_RE, f"{written}({{X}})"), want)
                self.assertEqual(verb(lex.INT_OP_RE, f"{written}({{X}})"), want)
        for written, want in DOTTED:
            with self.subTest(verb=written):
                self.assertEqual(verb(lex.OP_TARGET_RE, f"op {written}({{X}})"), want)
                self.assertEqual(verb(lex.EXT_OP_RE, f"op {written}({{X}})"), want)

    def test_marks_follow_letters(self):
        for written, want in CORPUS + DOTTED:
            if want is not None:
                self.assertTrue(lex.marks_follow_letters(written), written)
        for written in NOT_MARKS_AFTER_LETTERS:
            self.assertFalse(lex.marks_follow_letters(written), written)

    def test_a_dotted_digit_segment_is_one_malformed_op_call(self):
        # The parser reads `op ns.9x(` as one op-call (and draws it as written);
        # lint reports it as malformed wherever it stands, payload or target.
        self.assertEqual(verb(lex.OP_TARGET_RE, "ns.9x()"), "ns.9x")
        self.assertEqual(verb(lex.OP_HEAD_RE, "ns.9x("), "ns.9x")
        self.assertIsNone(verb(lex.EXT_OP_RE, "op ns.9x({X})"))
        for line in ("[Api] -> op ns.9x({Job})", "[Api] -> [Db] : op ns.9x({Job})"):
            g = parse.parse_document(line + "\n")
            self.assertIn("op ns.9x({Job})", [e.payload for e in g.edges])
            codes = [d.rule for d in lint.lint("#!spec\n" + line + "\n").diagnostics]
            self.assertIn("SGL102", codes, line)

    def test_a_well_formed_op_target_lints_clean(self):
        for line in ("[Api] -> op ns.run({Job})", "[Api] -> op ns.a⃝b()",
                     "[Api] -> op db.query(${sql}) -> [Db]"):
            codes = [d.rule for d in lint.lint("#!spec\n" + line + "\n").diagnostics]
            self.assertNotIn("SGL102", codes, line)


class EnclosingMarkVerbs(unittest.TestCase):
    VERB = "a⃝b"

    def test_the_parser_draws_one_op_call(self):
        g = parse.parse_document(f"[Api] -> {self.VERB}({{Job}})\n")
        self.assertEqual([e.payload for e in g.edges], [f"{self.VERB}({{Job}})"])

    def test_lint_classifies_it_as_an_op_call(self):
        self.assertEqual(payloads._classify_payload(f"{self.VERB}({{X}})")[0], "int-op")
        self.assertEqual(payloads._classify_payload(f"op ns.{self.VERB}({{X}})")[0], "ext-op")
        self.assertEqual(payloads._classify_payload("op ns.⃝b({X})")[0], "ext-op-bad")


class Comments(unittest.TestCase):
    """One comment reading (D1): a `#` inside a `"…"` string is string text, for
    the parser, lint and the dialect API alike."""

    def test_a_hash_inside_a_string_is_string_text(self):
        self.assertEqual(lex.strip_comment('[A] -> [B] : "issue #5" # n'),
                         '[A] -> [B] : "issue #5" ')
        self.assertEqual(lex.comment_col('[A] : "issue #5" # n'), 17)

    def test_the_dialect_api_reads_comments_the_same_way(self):
        self.assertIs(vocab.strip_comment, lex.strip_comment)
        self.assertEqual(vocab.strip_comment('[A] -> [B] : "issue #5"'),
                         '[A] -> [B] : "issue #5"')

    def test_a_mode_line_is_no_comment(self):
        self.assertEqual(lex.strip_comment("#!spec # x"), "#!spec # x")
        self.assertIsNone(lex.comment_col("  #!spec # x"))

    def test_a_dialect_marker_ends_the_code_outside_a_string(self):
        marker = re.compile(r"(?:^|(?<=\s))(?:-//)")
        self.assertEqual(lex.code_end("[A] -> [B] -// note", marker), 11)
        self.assertEqual(lex.code_end('[A] : "a -// b" -// n', marker), 16)
        self.assertEqual(lex.code_end("[A] # x -// y", marker), 4)


class BlockStrings(unittest.TestCase):
    DOC = ['[A] -> [B] : """a""" -> [C] : """b"""', 'x', '[D] -> [E] : """', 'body',
           '""" @inv k']

    def test_a_folded_line_is_read_again_and_its_first_body_kept(self):
        # D3: what follows a closing `"""` may open another block; a payload is
        # terminal, so the line's first body is its flow's.
        bodies = {}
        folded = lex.fold_block_strings(self.DOC, bodies)
        self.assertEqual(folded.lines[0],
                         '[A] -> [B] : "block-string" -> [C] : "block-string"')
        self.assertEqual(folded.lines[2:], ['[D] -> [E] : "block-string" @inv k', "", ""])
        self.assertEqual(bodies, {0: "a", 2: "\nbody\n"})
        self.assertIsNone(folded.unterminated)

    def test_an_unterminated_block_blanks_to_the_end(self):
        folded = lex.fold_block_strings(["a", '[A] -> [B] : """', "x"])
        self.assertEqual(folded, lex.Folded(["a", "", ""], 1, frozenset({2})))

    def test_the_lines_a_body_consumed_are_quoted(self):
        # D16: the Layout's quoted lines come from the fold.
        self.assertEqual(lex.fold_block_strings(self.DOC).quoted, frozenset({3, 4}))

    def test_a_delimiter_after_a_hash_in_a_string(self):
        # D1: the `#` is string text, so the `"""` opens a block (never closed).
        doc = ['[A] : "x #y" """', "z"]
        self.assertEqual(lex.fold_block_strings(doc).unterminated, 0)

    def test_a_delimiter_in_a_comment_is_comment_text(self):
        self.assertIsNone(lex.fold_block_strings(['[A] # see """', "z"]).unterminated)


class Braces(unittest.TestCase):
    """D2: a brace inside a string is string text, never a block's."""

    def test_net_braces_and_close_at_skip_strings(self):
        self.assertEqual(lex.net_braces('[A] -> [B] : "a { b"'), 0)
        self.assertEqual(lex.close_at('[A] : "}" }', 1), 10)


# Modules that read Sigil text; none may compile a pattern lex already holds.
READERS = (parse, statements, tokens, comments, lint, composition, hardening, lines, payloads,
           permissions, reading)


class GlyphTables(unittest.TestCase):
    """The glyph brackets and prefixes are lex's one table; a `state` owner takes
    the prefixes a glyph takes; one predicate says what a mode line is."""

    def test_the_bracket_strings_are_the_table_s(self):
        self.assertEqual(lex.OPENERS, "".join(o for o, _c in lex.GLYPH_BRACKETS.values()))
        self.assertEqual(lex.CLOSERS, "".join(c for _o, c in lex.GLYPH_BRACKETS.values()))
        for o in lex.OPENERS:
            self.assertTrue(re.fullmatch(lex.OPENERS_CLASS, o), o)
        for c in lex.CLOSERS:
            self.assertTrue(re.fullmatch(lex.CLOSERS_CLASS, c), c)

    def test_a_state_owner_is_a_glyph_the_parser_reads(self):
        for head, owner in (("state {X} {", "{X}"), ("state ~{X} {", "~{X}"),
                            ("state ~*{X} {", "~*{X}"), ("state ~~{X} {", None),
                            ("state *~{X} {", None)):
            m = lex.STATE_HEAD_RE.match(head)
            self.assertEqual(m.group(1) if m else None, owner, head)
            glyph = parse.parse_glyph(head[len("state "):-2])
            self.assertEqual(glyph is not None, owner is not None, head)

    def test_an_owner_less_head_has_no_owner_in_the_walk(self):
        doc = statements.read_document("state ~~{X} {\n  A -<a>-> B\n}\n").doc
        heads = [i for i in doc.items if isinstance(i, statements.StateHead)]
        self.assertEqual([h.owner for h in heads], [None])

    def test_a_mode_line_indented_or_not(self):
        self.assertTrue(lex.is_mode_line("#!spec"))
        self.assertTrue(lex.is_mode_line("  #!craft # x"))
        self.assertFalse(lex.is_mode_line("[A] #!x"))
        self.assertFalse(lex.is_mode_line("# !spec"))


class OneSourceOfTruth(unittest.TestCase):
    def test_no_reader_keeps_a_copy_of_a_lex_pattern(self):
        held = {(v.pattern, v.flags): name for name, v in vars(lex).items()
                if isinstance(v, re.Pattern)}
        for mod in READERS:
            for name, v in vars(mod).items():
                key = (v.pattern, v.flags) if isinstance(v, re.Pattern) else None
                if key in held:
                    self.assertIs(v, getattr(lex, held[key]),
                                  f"{mod.__name__}.{name} copies lex.{held[key]}")

    def test_no_reader_defines_the_verb_rule_or_a_hook_reader(self):
        for mod in READERS:
            for name in ("_is_mark", "_marks_follow_letters", "_VerbPattern", "_hook",
                         "_close_at", "_in_string"):
                obj = vars(mod).get(name)
                self.assertFalse(obj is not None and obj.__module__ == mod.__name__,
                                 f"{mod.__name__}.{name}")

    def test_the_parser_s_names_are_lex_s(self):
        for name in ("GLYPH_RE", "OP_TARGET_RE", "BLOCK_SENTINEL", "BRANCH_RE",
                     "ALIAS_REF", "strip_comment"):
            self.assertIs(getattr(parse, name), getattr(lex, name), name)
        for name in ("MODIFIER_RE", "PAYLOAD_RE", "GLUED_MOD_RE", "in_string"):
            self.assertIs(getattr(tokens, name), getattr(lex, name), name)

    def test_the_dialect_api_is_lex_s(self):
        for name in ("ARROWS", "ARROW_RE", "GLYPH_PATTERNS", "ANY_GLYPH_RE", "COMMENT_START_RE"):
            self.assertIs(getattr(vocab, name), getattr(lex, name), name)


if __name__ == "__main__":
    unittest.main()
