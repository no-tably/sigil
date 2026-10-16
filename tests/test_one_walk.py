"""One reading of a document (campaign one-walk W1): sigil.core.statements reads
it once — lines, statement walk, each statement's tokens — and both the parser
(sigil.core.parse builds the model from that reading) and lint (its rules judge
it) take it from there. The divergences between the parser's and lint's old
readings are settled by the parser's reading, as one-walk/DIVERGENCES.md
decides (ids D1–D17 below).
"""
import json
import re
import sys
import types
import unittest
from dataclasses import fields, is_dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sigil.analyse import lint  # noqa: E402
from sigil.analyse.lint import hardening  # noqa: E402
from sigil.core import dialects, parse, statements, tokens  # noqa: E402


def _dump(obj):
    """A graph as plain data (dict order kept), for comparing two parses."""
    if is_dataclass(obj):
        return {f.name: _dump(getattr(obj, f.name)) for f in fields(obj)
                if f.name != "hole_seq"}
    if isinstance(obj, dict):
        return [[_dump(k), _dump(v)] for k, v in obj.items()]
    if isinstance(obj, (list, tuple)):
        return [_dump(x) for x in obj]
    return obj


def _corpus():
    paths = sorted((ROOT / "tests" / "fixtures").rglob("*.sigil")) + \
        sorted((ROOT / "site" / "examples").glob("*.sigil"))
    return [(p.relative_to(ROOT).as_posix(), p.read_text(encoding="utf-8")) for p in paths]


class ReadOnce(unittest.TestCase):
    def test_lint_reads_a_document_once(self):
        calls = []
        read = statements.read_lines

        def counted(*a, **k):
            calls.append(1)
            return read(*a, **k)
        statements.read_lines = counted
        try:
            for name, text in _corpus():
                calls.clear()
                lint.lint(text)
                self.assertEqual(len(calls), 1, name)
        finally:
            statements.read_lines = read

    def test_the_model_from_lint_s_reading_is_the_parser_s(self):
        for name, text in _corpus():
            walk = statements.read_document(text)
            self.assertEqual(json.dumps(_dump(parse.parse_document(text, walk=walk))),
                             json.dumps(_dump(parse.parse_document(text))), name)

    def test_a_walk_can_be_built_twice(self):
        # The builder makes fresh nodes: a reading is not changed by building it.
        walk = statements.read_document("[?] -> [B] : x @timeout(1s)\n<E> -> [?]\n")
        first = _dump(parse.parse_document("", walk=walk))
        self.assertEqual(_dump(parse.parse_document("", walk=walk)), first)


class Readings(unittest.TestCase):
    """The parser's reading, as each divergence settles it."""

    def test_d1_a_hash_in_a_string_is_payload_text(self):
        g = parse.parse_document('[A] -> [B] : "issue #5"   # real note\n')
        self.assertEqual(g.edges[0].payload, '"issue #5"')
        self.assertEqual([n.text for n in g.notes], ["real note"])

    def test_d2_a_brace_in_a_string_is_no_block_brace(self):
        g = parse.parse_document('loop @each x {\n  [A] -> [B] : "a { b"\n}\n[C] -> [D]\n')
        self.assertEqual(g.blocks[0].lines, (1, 3))
        self.assertEqual(g.blocks[0].edges, [("A_service", "B_service", "->")])
        g = parse.parse_document('state {Job} {\n  A -<x>-> B : "}"\n  B -<y>-> C\n}\n')
        self.assertEqual(len(g.expansions["Job_data"].edges), 2)

    def test_d3_a_closing_block_string_may_open_another(self):
        g = parse.parse_document('[A] -> [B] : """one\ntwo""" -> [C] : """three\nfour"""\n'
                                 '[D] -> [E]\n')
        self.assertIn(("D_service", "E_service", "->"), [e.key for e in g.edges])

    def test_d6_a_stray_brace_then_an_arrow_continues_the_flow_above(self):
        w = statements.read_document("[A] -> [B]\n} -> [D]\n")
        self.assertEqual([(c.line, c.subject) for c in w.continuations], [(2, True)])
        g = parse.parse_document("[A] -> [B]\n} -> [D]\n")
        self.assertIn(("A_service", "D_service", "->"), [e.key for e in g.edges])

    def test_d9_a_state_head_with_no_owner_glyph_is_consumed(self):
        g = parse.parse_document("state Order {\n  A -<x>-> B\n  (done)\n}\n[A] -> [B]\n")
        self.assertNotIn("x_event", g.nodes)
        self.assertNotIn("done_actor", g.nodes)
        self.assertEqual([(d.line, d.reason) for d in g.dropped][:1], [(1, "no-owner")])
        found = {(d.line, d.rule) for d in lint.lint("#!sketch\nstate Order {\n  A -<x>-> B\n}\n")
                 .diagnostics}
        self.assertIn((2, "SGL161"), found)

    def test_d10_a_broken_glyph_is_a_void_endpoint(self):
        g = parse.parse_document("[A] -> <B -> [C]\n")
        self.assertEqual(g.edges, [])
        self.assertEqual(list(g.nodes), ["A_service", "C_service"])
        g = parse.parse_document("[A] -> [Z]\n<> -> [B]\n")
        self.assertEqual([e.key for e in g.edges], [("A_service", "Z_service", "->")])
        g = parse.parse_document("[A} -> [B]\n")           # mismatched: the opener's kind
        self.assertEqual([e.key for e in g.edges], [("A_service", "B_service", "->")])

    def test_d11_a_header_names_no_glyph_inside_a_modifier_argument(self):
        g = parse.parse_document("loop @times(2) {\n  [A] -> [B]\n}\n"
                                 "branch on {Req}.kind {\n  x => [A]\n}\n")
        self.assertNotIn("n2_actor", g.nodes)
        self.assertEqual([b.refs for b in g.blocks], [[], ["Req_data"]])

    def test_d12_one_payload_to_the_line_end_less_its_modifiers(self):
        g = parse.parse_document("[A] -> [B] : claim({S}) @timeout(1h) => {L}\n")
        self.assertEqual(g.edges[0].payload, "claim({S})   => {L}")
        self.assertEqual(g.edges[0].mods, [("timeout", "1h")])

    def test_d13_a_count_with_no_number_is_reported_and_placed_nowhere(self):
        g = parse.parse_document("[A] -> [B] ×\n")
        self.assertEqual((g.edges[0].mods, g.edges[0].card), ([], None))
        found = [d.rule for d in lint.lint("#!spec\n[A] -> [B] ×\n").diagnostics]
        self.assertIn("SGL180", found)


def _toy(**hooks):
    d = types.ModuleType("toy_one_walk_dialect")
    d.NAME = "toy"
    for k, v in hooks.items():
        setattr(d, k, v)
    return d


def _ref_tokenizer(s, i, prev, layer, Node):
    m = re.compile(r"\[\[([^\[\]]+)\]\]").match(s, i)
    if not m:
        return None
    return [("glyph", Node(id=m.group(1) + "_ref", name=m.group(1), kind="ref",
                           layer=layer))], m.end(), True


class OneHookSet(unittest.TestCase):
    def test_a_retired_hook_is_refused_by_name(self):
        d = _toy(render_tokenizers=lambda: [])
        with self.assertRaises(dialects.DialectError) as err:
            tokens.lexicon(d)
        self.assertIn("define `tokenizers`", str(err.exception))
        self.assertEqual(sorted(dialects.RETIRED_HOOKS),
                         ["lint_glyph_masks", "lint_prepasses", "lint_principal_scanners",
                          "render_line_strips", "render_prepasses", "render_tokenizers"])

    def test_load_refuses_a_dialect_with_a_retired_hook(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sigil-old" / "dialect.py"
            path.parent.mkdir()
            path.write_text("NAME = 'old'\ndef lint_glyph_masks():\n    return []\n")
            with self.assertRaises(dialects.DialectError) as err:
                dialects.load(str(path))
        self.assertIn("lint_glyph_masks", str(err.exception))

    def test_tokenizers_serve_the_model_lint_and_definitions(self):
        d = _toy(tokenizers=lambda: [_ref_tokenizer])
        g = parse.parse_document("[[rate]] -> [B]\n[[rate]] := {\n  [X] -> [Y]\n}\n",
                                 dialect=d)
        self.assertEqual(g.nodes["rate_ref"].kind, "ref")
        self.assertIn("rate_ref", g.expansions)            # D5: a dialect glyph head
        self.assertEqual(hardening.hardening_findings(
            statements.read_document("#!spec\n[[a]]>[[b]] -> [C]\n", d)), [])

    def test_prepasses_run_once_before_the_walk(self):
        seen = []

        def prepass(lines, result):
            seen.append(len(lines))
            return [ln.replace(" ;; ", " # ") for ln in lines]
        d = _toy(prepasses=lambda: [prepass])
        g = parse.parse_document("[A] -> [B] ;; a note\n[X] := {\n  [C] -> [D]\n}\n",
                                 dialect=d)
        self.assertEqual(seen, [4])
        self.assertEqual([e.key for e in g.edges], [("A_service", "B_service", "->")])

    def test_strips_blank_a_flow_statement_and_keep_its_length(self):
        d = _toy(strips=lambda: [lambda line: re.sub(r"^on <\w+> ", lambda m: " " * len(
            m.group(0)), line)])
        g = parse.parse_document("on <go> |S| -> [V]\n", dialect=d)
        self.assertEqual([e.key for e in g.edges], [("S_store", "V_service", "->")])
        self.assertEqual(g.heads, [(1, "S_store")])
        bad = _toy(strips=lambda: [lambda line: line.replace("on ", "")])
        with self.assertRaises(ValueError):
            parse.parse_document("on <go> |S| -> [V]\n", dialect=bad)


class Nesting(unittest.TestCase):
    def test_a_line_closing_bodies_ends_them_inside_out(self):
        g = parse.parse_document("[A] := {\n  [B] := {\n    [X] -> [Y] } @inv b\n} @inv a\n")
        self.assertIn(("inv", "a"), g.nodes["A_service"].mods)
        inner = g.expansions["A_service"]
        self.assertIn(("inv", "b"), inner.nodes["B_service"].mods)
        self.assertEqual([e.key for e in inner.expansions["B_service"].edges],
                         [("X_service", "Y_service", "->")])

    def test_a_body_never_closed_drops_every_line_from_its_head(self):
        g = parse.parse_document("[A] := {\n  [B] := {\n    [X] -> [Y]\n}\n[C] -> [D]\n")
        self.assertEqual([(d.line, d.reason) for d in g.dropped],
                         [(n, "unclosed") for n in range(1, 6)])
        self.assertEqual(g.edges, [])


if __name__ == "__main__":
    unittest.main()
