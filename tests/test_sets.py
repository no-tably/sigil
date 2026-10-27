"""Sets are values (design/refine-1.md, round 7, proposal 1): a glyph name never
holds a comma, so `{a, b}` is a set wherever it stands — in `branch on`, a
`loop @while`, a `?>` guard, an `@inv` argument, a payload, or written as a
flow's end. A set makes no node (so Mermaid draws none), `sigil highlight` reads
it the way the editor grammars do (as held text: punctuation and plain words),
and lint says a set as a flow's end is an error (SGL190) that names the fix.
`{Cache<K,V>}` stays a glyph (its comma is a generic's) and `{A}, {B}` stays two."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigil.analyse.lint import lint  # noqa: E402
from sigil.core import lex  # noqa: E402
from sigil.core import parse as render  # noqa: E402
from sigil.core.tokens import code_line, glyph_spans, tokenize_statement  # noqa: E402
from sigil.present import highlight as hl  # noqa: E402
from sigil.publish import mermaid  # noqa: E402

HEAD = "#!sketch\n[A] -> {Order}\nstate {Order} {\n  + -<Go>-> pending\n  pending -<Go>-> active\n}\n"

# Every place a set may stand as a value; none of them makes a node.
VALUES = {
    "branch": "branch on {Order}.status ∈ {pending, active} {\n  yes => [C]\n  _ => [D]\n}\n",
    "while": "loop @while {Order}.status ∈ {pending, active} {\n  [C] -> [D]\n}\n",
    "guard": "[D] ?> {Order}.status ∈ {pending, active} -> [E]\n",
    "inv": "[F] @inv excludes({Order}.status ∈ {pending, active})\n",
    "payload": "[E] -> [F] : go({Order}, {pending, active})\n",
}


def names(text: str) -> set:
    return {n.name for n in render.parse_document(text).nodes.values()}


def rules(text: str) -> list:
    return [(d.line, d.rule) for d in lint(text).diagnostics]


def kinds(raw: str) -> list:
    return [(t.kind, t.text) for t in tokenize_statement(code_line(raw))]


class Lexicon(unittest.TestCase):
    def test_is_set(self):
        for text in ("{a, b}", "{a,b}", "~{a, b}", "{Open, Closed}"):
            self.assertTrue(lex.is_set(text), text)
        for text in ("{Order}", "{Cache<K,V>}", "[A, B]", "{?}", "<K,V>"):
            self.assertFalse(lex.is_set(text), text)

    def test_glyph_re_reads_no_set(self):
        self.assertIsNone(lex.GLYPH_RE.match("{pending, active}"))
        self.assertIsNone(lex.GLYPH_RE.search("∈ {pending, active}"))
        self.assertEqual(lex.GLYPH_RE.match("{Cache<K,V>}").group("name"), "Cache<K,V>")
        self.assertEqual(lex.GLYPH_RE.match("[Pool<Worker>]").group("name"), "Pool<Worker>")
        self.assertEqual([m.group(0) for m in lex.ANY_GLYPH_RE.finditer("{O}.s ∈ {a, b}")],
                         ["{O}"])

    def test_glyph_spans_skip_sets(self):
        got = [(g.kind, g.name) for g in glyph_spans("{Order}.s ∈ {done, gone}")]
        self.assertEqual(got, [("data", "Order")])
        got = [(g.kind, g.name) for g in glyph_spans("{A}, {B}")]
        self.assertEqual(got, [("data", "A"), ("data", "B")])

    def test_a_set_is_a_set_token(self):
        self.assertIn(("set", "{pending, active}"),
                      kinds("[D] ?> {Order}.status ∈ {pending, active} -> [E]"))
        self.assertEqual([k for k, _t in kinds("{A}, {B} -> [G]")],
                         ["glyph", "glyph", "arrow", "glyph"])
        self.assertEqual(kinds("[H] -> {Cache<K,V>}")[-1], ("glyph", "{Cache<K,V>}"))


class NoNode(unittest.TestCase):
    def test_a_set_as_a_value_makes_no_node(self):
        for where, body in VALUES.items():
            with self.subTest(where=where):
                got = names(HEAD + body)
                self.assertFalse([n for n in got if "," in n], got)
                self.assertNotIn("pending, active", got)

    def test_values_lint_clean(self):
        for where, body in VALUES.items():
            with self.subTest(where=where):
                self.assertEqual(rules(HEAD + body), [])

    def test_a_guard_on_a_set_reads_as_on_a_word(self):
        g = render.parse_document("#!sketch\n[D] ?> {Order}.status ∈ {pending, active} -> [E]\n")
        w = render.parse_document("#!sketch\n[D] ?> {Order}.status ∈ pending -> [E]\n")
        pairs = lambda x: [(x.nodes[e.src].name, e.kind, x.nodes[e.dst].name) for e in x.edges]
        self.assertEqual(pairs(g), pairs(w))
        self.assertEqual(pairs(g), [("D", "?>", "Order"), ("Order", "->", "E")])

    def test_a_set_as_a_flow_end_makes_no_node(self):
        self.assertEqual(names("#!sketch\n[B] -> {B1, C1}\n"), {"B"})

    def test_two_glyphs_and_a_generic_stay_glyphs(self):
        got = names("#!sketch\n{A}, {B} -> [G]\n[H] -> {Cache<K,V>}\n")
        self.assertEqual(got, {"A", "B", "G", "H", "Cache<K,V>"})

    def test_mermaid_draws_no_set(self):
        for where, body in VALUES.items():
            with self.subTest(where=where):
                out = mermaid.mermaid_text(HEAD + body)     # the source rides along
                self.assertNotIn('"pending, active"', out)
                self.assertNotIn("pending__active", out)


class FlowEnd(unittest.TestCase):
    def test_a_set_as_a_flow_end_is_sgl190(self):
        for line in ("[B] -> {B1, C1}", "[B] ~> {B1, C1}", "{B1, C1} -> [B]",
                     "[A] -> {B1, C1} -> [D]"):
            with self.subTest(line=line):
                self.assertEqual(rules(f"#!sketch\n{line}\n"), [(2, "SGL190")])

    def test_after_a_join(self):
        self.assertIn((2, "SGL190"), rules("#!sketch\n[A] -> [X] & {B1, C1}\n"))

    def test_the_message_names_the_fix(self):
        d = next(d for d in lint("#!spec\n[A] -> {B, C}\n").diagnostics if d.rule == "SGL190")
        self.assertEqual(d.severity, "error")
        self.assertIn("a set is a value, not a flow end: write one flow per glyph", d.message)
        self.assertIn("`{B}`, `{C}`", d.message)

    def test_an_error_in_every_mode(self):
        for mode in ("sketch", "craft", "spec"):
            with self.subTest(mode=mode):
                sev = [d.severity for d in lint(f"#!{mode}\n[A] -> {{B, C}}\n").diagnostics
                       if d.rule == "SGL190"]
                self.assertEqual(sev, ["error"])


class Highlight(unittest.TestCase):
    """A set in a statement is painted as the same set held in a payload is."""

    def roles(self, raw: str, piece: str) -> list:
        runs, _ = hl.line(raw)
        at, out = raw.index(piece), []
        pos = 0
        for text, role in runs:
            if at <= pos < at + len(piece) and text.strip():
                out.append((text, role))
            pos += len(text)
        return out

    def test_a_statement_set_reads_as_held_text(self):
        held = self.roles("[Desk] -> [Store] : {Open, Closed}", "{Open, Closed}")
        for raw in ("branch on {Ticket}.state ∈ {Open, Closed} {",
                    "loop @while {Ticket}.state ∈ {Open, Closed} {",
                    "[Desk] ?> {Ticket}.state ∈ {Open, Closed} -> [Store]"):
            with self.subTest(raw=raw):
                got = self.roles(raw, "{Open, Closed}")
                self.assertEqual(got, held)
                self.assertNotIn("kinds.data", [r for _t, r in got])


if __name__ == "__main__":
    unittest.main()
