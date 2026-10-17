"""`#&` dialect declarations (language.md "Dialects"): core's one reading of a
line-leading `#& name …`.

Covers:
  - lex.declaration_name: the spaced form `#& name`, the unspaced `#&name` (the
    same name), the name ending at a space, `~`, `{` or the end; a `#&` after code
    or no `#&` at all is no declaration;
  - the walk: a declaration is a statement that draws nothing — no note, no flow,
    no node — and the `{ … }` block it opens (`{` or `~{`, one line or many, a
    brace inside a string is string text) is its body, consumed; with or without a
    dialect, and the same when a dialect's DECLARATION_BLOCKS matches it too; no
    per-line rule reads a declaration's lines; a `#&` after code is still erased
    like a comment and makes no note;
  - SGL189: with no dialect, every `#&` declaration is warned about; a dialect
    that lists DECLARATIONS is warned about only for a name it does not list; a
    dialect without that hook hears nothing.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import re
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sigil.analyse import lint  # noqa: E402
from sigil.core import lex, parse  # noqa: E402
from sigil.core.statements import Declaration, Flow, Note, read_document  # noqa: E402


def _dialect(**hooks) -> types.ModuleType:
    mod = types.ModuleType("probe_dialect")
    mod.NAME = "probe"
    for k, v in hooks.items():
        setattr(mod, k, v)
    return mod


def items(text: str, dialect=None) -> list:
    return list(read_document(text, dialect).doc.items)


def said(text: str, dialect=None, rule: str = "SGL189") -> list:
    return [(d.line, d.severity) for d in lint.lint(text, dialect=dialect).diagnostics
            if d.rule == rule]


MULTI = '#!sketch\n#& header {\n  address: a/b\n  note: "}"\n  [Ghost] -> [Gone]\n}\n[A] -> [B]\n'


class DeclarationName(unittest.TestCase):
    def test_spaced_and_unspaced_read_the_same(self):
        for line in ("#& header", "#&header", "#&  header x", "  #& header {",
                     "#&header~{ a: b }", "#& header ~{"):
            with self.subTest(line=line):
                self.assertEqual(lex.declaration_name(line), "header")

    def test_the_name_may_be_empty(self):
        for line in ("#&", "#& ", "#&{", "#& ~{"):
            with self.subTest(line=line):
                self.assertEqual(lex.declaration_name(line), "")

    def test_no_declaration(self):
        for line in ("[A] #&x", "# c", "#!spec", "", '"#&x"', "#= x"):
            with self.subTest(line=line):
                self.assertIsNone(lex.declaration_name(line))


class TheWalk(unittest.TestCase):
    def test_a_declaration_is_no_note_and_no_flow(self):
        for text in ("#& header\n[A] -> [B]\n", "#&header\n[A] -> [B]\n"):
            with self.subTest(text=text):
                got = items(text)
                self.assertEqual([i for i in got if isinstance(i, Declaration)],
                                 [Declaration(0, "header")])
                self.assertFalse([i for i in got if isinstance(i, Note)])
                self.assertEqual([i.line for i in got if isinstance(i, Flow)], [1])

    def test_a_one_line_block_is_its_body(self):
        for text in ("#& header { address: [X] -> [Y] }\n[A] -> [B]\n",
                     "#&header~{ address: [X] -> [Y] }\n[A] -> [B]\n"):
            with self.subTest(text=text):
                g = parse.parse_document(text)
                self.assertEqual(sorted(n.name for n in g.nodes.values()), ["A", "B"])
                self.assertEqual(g.notes, [])

    def test_a_many_line_block_is_consumed_to_its_balancing_brace(self):
        walk = read_document(MULTI)
        self.assertEqual([s.line for s in walk.statements], [7])
        self.assertIn((2, 6), walk.spans)
        g = parse.parse_document(MULTI)
        self.assertEqual(sorted(n.name for n in g.nodes.values()), ["A", "B"])

    def test_tilde_brace_opens_the_block_too(self):
        text = "#&header~{\n  [Ghost] -> [Gone]\n}\n[A] -> [B]\n"
        self.assertEqual([s.line for s in read_document(text).statements], [4])

    def test_inside_a_definition_body(self):
        text = "[S] := {\n  #& header {\n    [Ghost]\n  }\n  [A] -> [B]\n}\n"
        g = parse.parse_document(text)
        self.assertNotIn("Ghost", {n.name for n in g.nodes.values()})
        self.assertIn("A", {n.name for n in g.nodes.values()})

    def test_the_same_with_a_dialect_that_opens_it_too(self):
        opener = _dialect(DECLARATION_BLOCKS=[(re.compile(r"^#&header~?\s*\{"), True)])
        for text in (MULTI, MULTI.replace("#& header {", "#&header~{")):
            with self.subTest(text=text):
                core, both = read_document(text), read_document(text, opener)
                self.assertEqual(core.doc.items, both.doc.items)
                self.assertEqual(core.statements, both.statements)
                self.assertEqual(core.spans, both.spans)

    def test_no_line_rule_reads_a_body(self):
        text = "#!spec\n#& header {\n  a: ?\n  [X] excludes [Y] ; @foo\n}\n[A] -> [B]\n"
        meta = _dialect(DECLARATION_BLOCKS=[(re.compile(r"^meta\s*\{"), False)])
        for doc, d in ((text, None), (text.replace("#& header", "meta"), meta)):
            with self.subTest(dialect=d is not None):
                rules = {x.rule for x in lint.lint(doc, dialect=d).diagnostics}
                self.assertFalse(rules & {"SGL010", "SGL020", "SGL030", "SGL040", "SGL050"}, rules)

    def test_a_mark_after_code_is_erased_but_no_note(self):
        self.assertEqual(lex.strip_comment("[A] #& header"), "[A] ")
        self.assertEqual(read_document("[A] #& header # real").comments, {0: ("real", False)})
        self.assertFalse([i for i in items("[A] #& header\n") if isinstance(i, Declaration)])


class SGL189(unittest.TestCase):
    TEXT = "#!sketch\n#& header { a: b }\n#&other\n[A] -> [B]\n"

    def test_no_dialect_warns_on_each(self):
        self.assertEqual(said(self.TEXT), [(2, "warn"), (3, "warn")])
        msg = [d.message for d in lint.lint(self.TEXT).diagnostics if d.rule == "SGL189"][0]
        self.assertIn("`#& header`", msg)
        self.assertIn("--dialect NAME", msg)

    def test_a_declaring_dialect_warns_on_what_it_does_not_declare(self):
        d = _dialect(DECLARATIONS={"header"})
        self.assertEqual(said(self.TEXT, d), [(3, "warn")])
        msg = [x.message for x in lint.lint(self.TEXT, dialect=d).diagnostics
               if x.rule == "SGL189"][0]
        self.assertIn("`#& other`", msg)
        self.assertIn("`#& header`", msg)

    def test_a_dialect_without_declarations_is_silent(self):
        self.assertEqual(said(self.TEXT, _dialect()), [])

    def test_a_dialect_opener_not_led_by_the_mark_is_not_judged(self):
        d = _dialect(DECLARATIONS=set(), DECLARATION_BLOCKS=[(re.compile(r"^meta\s*\{"), False)])
        self.assertEqual(said("#!sketch\nmeta {\n  a: b\n}\n[A] -> [B]\n", d), [])

    def test_a_document_without_one_is_quiet(self):
        self.assertEqual(said("#!sketch\n# a note\n[A] -> [B]  # #&x\n"), [])


if __name__ == "__main__":
    unittest.main()
