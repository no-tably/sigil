"""Regression tests for the render.py review fixes (one class per finding).

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]


def _load(name: str, fname: str):
    spec = importlib.util.spec_from_file_location(name, _DIR / fname)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


render = _load("sigil_render", "render.py")


def parse(text):
    return render.parse_document(text)


def edges(g):
    return {(e.src, e.dst) for e in g.edges}


class MidLineModifier(unittest.TestCase):           # 1
    def test_modifier_before_arrow_keeps_the_flow(self):
        g = parse("[A] @timeout(5s) -> [B]")
        self.assertEqual(edges(g), {("A_service", "B_service")})

    def test_modifier_between_hops_keeps_the_rest(self):
        g = parse("[A] -> [B] @timeout(5s) -> [C]")
        self.assertEqual(edges(g), {("A_service", "B_service"), ("B_service", "C_service")})

    def test_modifier_target_is_still_stripped(self):
        g = parse("[A] @borrow(read) |tree|\n[B] @owns |Conn|")
        self.assertEqual(set(g.nodes), {"A_service", "B_service"})

    def test_nested_parens_in_argument(self):
        g = parse("[A] @inv(f(x) > 0) -> [B]")
        self.assertEqual(edges(g), {("A_service", "B_service")})


class ExpansionMatchesKind(unittest.TestCase):      # 2
    def test_data_expansion_not_on_same_named_component(self):
        g = parse("[Order] -> |db|\n{Order} := { {Id} -> {Line} }\n{Order} -> [Ship]")
        self.assertIn("Order_data", g.expansions)
        self.assertNotIn("Order_service", g.expansions)

    def test_bare_name_takes_first_node(self):
        g = parse("[Order] -> |db|\nOrder := {\n  [A] -> [B]\n}")
        self.assertIn("Order_service", g.expansions)


class TextBeforeClosingBrace(unittest.TestCase):    # 3
    def test_expansion_last_line(self):
        g = parse("[X] := {\n  [A] -> [B] }")
        self.assertEqual(edges(g.expansions["X_service"]), {("A_service", "B_service")})

    def test_state_last_line(self):
        g = parse("state {Order} {\n Draft -<Pay>-> Paid\n Paid -> Shipped }")
        machine = g.expansions["Order_data"]
        self.assertIn("Order_state_Shipped", machine.nodes)
        self.assertEqual(len(machine.edges), 2)

    def test_expansion_head_line_content(self):
        g = parse("[X] := { [A] -> [B]\n  [B] -> [C]\n}")
        self.assertEqual(edges(g.expansions["X_service"]),
                         {("A_service", "B_service"), ("B_service", "C_service")})


class OneLineState(unittest.TestCase):              # 4
    def test_one_line_machine(self):
        g = parse("state {Order} { Draft -> Paid }")
        self.assertIn("Order_data", g.nodes)
        machine = g.expansions["Order_data"]
        self.assertEqual(machine.role, "state")
        self.assertEqual(edges(machine), {("Order_state_Draft", "Order_state_Paid")})

    def test_unowned_header_still_consumes_its_block(self):
        g = parse("state {\n  (pending) -<go>-> (done)\n}\n")
        self.assertEqual(g.nodes, {})

    def test_generic_owner_owns_its_machine(self):
        # `{Job<T>}` is ONE glyph (generics are part of the name), so it owns it.
        g = parse("state {Job<T>} {\n  (pending) -<go>-> (done)\n}\n")
        self.assertEqual(set(g.nodes), {"Job_T__data"})
        self.assertEqual(g.expansions["Job_T__data"].role, "state")


class AliasToGlyph(unittest.TestCase):              # 5
    # An alias is a node whose expansion is its definition when that draws a flow;
    # `{Summary}` after `:=` is not an expansion block `{ … }`.
    def test_alias_to_data_glyph_is_no_expansion(self):
        g = parse("[Materializer] := {Summary} cache")
        self.assertEqual(g.expansions, {})
        self.assertEqual(set(g.nodes), {"Materializer_service"})   # defined → a node

    def test_alias_to_flow_is_no_expansion(self):
        g = parse("ingress := {Req} => {Ctx}")
        self.assertEqual(g.nodes["ingress_alias"].kind, "alias")
        self.assertEqual(edges(g.expansions["ingress_alias"]), {("Req_data", "Ctx_data")})

    def test_brace_then_space_is_an_expansion(self):
        g = parse("[X] := { [A] -> [B] }")
        self.assertIn("X_service", g.expansions)


class ExpansionOwnsItsLines(unittest.TestCase):     # 6
    def test_section_header_inside_expansion(self):
        g = parse("[X] := {\n  -- L2: inner --\n  [A] -> [B]\n}\n[C] -> [D]")
        self.assertEqual(g.nodes["C_service"].layer, "L1")
        self.assertNotIn("L2", g.layers)
        self.assertEqual(g.expansions["X_service"].nodes["A_service"].layer, "L2")


class TriggerFromOccurrence(unittest.TestCase):     # 7
    def test_trigger_starts_at_the_drawn_occurrence(self):
        out = render.render("[Shop] \\-> <Pay>\nstate {Order} { Draft -<Pay>-> Paid }")
        self.assertIn('Shop_service__Pay_event -. "triggers" .-> Order_state_Paid', out)
        self.assertNotIn('\n    Pay_event -. "triggers"', out)

    def test_trigger_outside_trees_unchanged(self):
        out = render.render("<Pay> -> [Shop]\nstate {Order} { Draft -<Pay>-> Paid }")
        self.assertIn('Pay_event -. "triggers" .-> Order_state_Paid', out)


class HashInsideString(unittest.TestCase):          # 8, 19
    def test_payload_keeps_hash(self):
        g = parse('[A] -> [B] : "issue #5"')
        self.assertEqual(g.edges[0].payload, '"issue #5"')
        self.assertEqual(g.notes, [])

    def test_comment_after_string_still_a_note(self):
        g = parse('[A] -> [B] : "issue #5"  # real note')
        self.assertEqual([n.text for n in g.notes], ["real note"])
        self.assertEqual(g.edges[0].payload, '"issue #5"')

    def test_unclosed_quote_opens_no_string(self):
        self.assertEqual(render.strip_comment('[A] -> [B] : 5" # note'), '[A] -> [B] : 5" ')

    def test_amp_marker_is_stripped_but_no_note(self):
        self.assertEqual(render.strip_comment("[A] #&marker"), "[A] ")
        self.assertEqual(render.collect_comments(["[A] #&marker # real"]), {0: ("real", False)})

    def test_at_sign_inside_string_payload(self):
        g = parse('[A] -> [B] : "mail ops@example.com"')
        self.assertEqual(g.edges[0].payload, '"mail ops@example.com"')


class AliasColonIsNoPayload(unittest.TestCase):     # 9
    def test_colon_equals_is_not_a_payload(self):
        g = parse("[A] -> [B] := x")
        self.assertIsNone(g.edges[0].payload)


class PayloadDropsTrailingModifiers(unittest.TestCase):   # payload ×N / ^N
    def test_cardinality_after_payload(self):
        g = parse("[API] -> [Payment] : charge(total) ×3 @timeout(2s)")
        self.assertEqual(g.edges[0].payload, "charge(total)")

    def test_ascii_cardinality_and_bound(self):
        self.assertEqual(parse("[A] -> [B] : charge x3").edges[0].payload, "charge")
        self.assertEqual(parse("[A] -> [B] : *<Tick>^5@drop").edges[0].payload, "*<Tick>")

    def test_inside_string_or_value_kept(self):
        self.assertEqual(parse('[A] -> [B] : "a ×3"').edges[0].payload, '"a ×3"')
        self.assertEqual(parse("[A] -> [B] : x^2").edges[0].payload, "x^2")

    def test_modifier_only_payload_is_none(self):
        self.assertIsNone(parse("[A] -> [B] : ×3").edges[0].payload)


class Docstring(unittest.TestCase):                 # 10
    def test_documents_current_cli_and_arrows(self):
        doc = render.__doc__
        self.assertIn("--composition", doc)
        self.assertIn('-- "!" -->', doc)
        self.assertIn("stadium", doc)
        self.assertNotIn("ERROR", doc)


class DeadCodeGone(unittest.TestCase):              # 11-15
    def test_no_stale_names(self):
        self.assertFalse(hasattr(render, "CLASS_DEF"))
        self.assertIn("open", render.GLYPH_RE.groupindex)

    def test_kind_classes(self):
        class D:
            NODE_KINDS = {"gem": {"mermaid_class": "gemc"}}
        kinds = render._kind_classes(D)
        self.assertEqual(kinds["service"], "service")
        self.assertEqual(kinds["gem"], "gemc")


class BlockComments(unittest.TestCase):             # 18
    DOC = ("loop {\n"
           "  # inside\n"
           "  [A] -> [B]\n"
           "  branch {\n"
           "    [C] -> [D]\n"
           "  }\n"
           "  [E] -> [F]\n"
           "}\n"
           "# after\n"
           "[G] -> [H]\n")

    def test_comment_inside_loop_attaches_inside(self):
        notes = {n.text: n.node for n in parse(self.DOC).notes}
        self.assertEqual(notes, {"inside": "A_service", "after": "G_service"})

    def test_nested_header_keeps_depth(self):
        g = parse(self.DOC)
        self.assertIn(("E_service", "F_service"), edges(g))
        self.assertIn(("G_service", "H_service"), edges(g))

    def test_one_line_block_does_not_swallow_next_line(self):
        g = parse("loop @each k of ${xs} { [A] -> [B] }\n[C] -> [D]")
        self.assertEqual(edges(g), {("A_service", "B_service"), ("C_service", "D_service")})


class Cli(unittest.TestCase):                       # 21
    def _main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                render.main(list(argv), default_dialect="")
                code = 0
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_bad_depth_is_a_usage_error(self):
        code, _out, err = self._main("-", "--depth", "x")
        self.assertEqual(code, 2)
        self.assertIn("'all'", err)

    def test_depth_all_and_utf8_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".sigil", delete=False,
                                         encoding="utf-8") as f:
            f.write("[A] → [B] : naïve\n")
        try:
            code, out, _err = self._main(f.name, "--depth", "all")
        finally:
            os.unlink(f.name)
        self.assertEqual(code, 0)
        self.assertIn("A_service --> B_service", out)


class LabelEscaping(unittest.TestCase):             # 22, 25
    def test_quote_in_node_label(self):
        out = render.render('[say "hi"] -> [B]')
        self.assertIn('say__hi__service["say &quot;hi&quot;"]', out)

    def test_subgraph_title_escaped(self):
        out = render.render('[a "b"] := {\n  [C] -> [D]\n}\n[a "b"] -> [E]', composition="none")
        self.assertIn('subgraph a__b__service["a &quot;b&quot;"]', out)

    def test_labels_on_every_arrow_kind(self):
        def emit(kind):
            return render.emit_edge(render.Edge("a", "b", kind, label="<x>"), "")
        self.assertEqual(emit("->"), 'a -- "&lt;x&gt;" --> b')
        self.assertEqual(emit("~>"), 'a -.->|"&lt;x&gt;"| b')
        self.assertEqual(emit("=>"), 'a ==>|"&lt;x&gt;"| b')
        self.assertEqual(emit("!>"), 'a -- "! &lt;x&gt;" --> b')


class ClassDefFooter(unittest.TestCase):            # 24
    def test_every_classdef_indented(self):
        out = render.render("[A] -> [B]")
        for ln in out.splitlines():
            if "classDef" in ln:
                self.assertTrue(ln.startswith("    classDef"), ln)


if __name__ == "__main__":
    unittest.main()
