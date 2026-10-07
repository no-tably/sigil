"""Tests for render.py's graph construction (the model view.py draws from).

Covers the render fixes that landed with the live viewer:
  - `&` / `&?` joins group glyphs into ONE endpoint, so a `*>` fan-out (or any
    arrow) connects to every member (`<E> *> [A] & [B] & |C|` is three edges);
  - every hole `[?]` is its own node (two unknowns never collapse to one);
  - the terminal `: payload` is kept on the flow's final edge(s);
  - an `X := { … }` expansion attaches even when written before X's first use,
    and a defined-but-unreferenced component still appears as a node.

Run:  uv run python -m unittest discover notations/sigil/tests/
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]


def _load(name: str, fname: str):
    spec = importlib.util.spec_from_file_location(name, _DIR / fname)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


render = _load("sigil_render", "render.py")


def edges(g):
    return {(e.src, e.dst, e.kind) for e in g.edges}


class TestJoinFanOut(unittest.TestCase):
    def test_broadcast_reaches_every_joined_target(self):
        g = render.parse_document(
            "[API] ~> <OrderPlaced> *> [Shipping] & [Email] & |Ledger|\n")
        self.assertEqual(edges(g), {
            ("API_service", "OrderPlaced_event", "~>"),
            ("OrderPlaced_event", "Shipping_service", "*>"),
            ("OrderPlaced_event", "Email_service", "*>"),
            ("OrderPlaced_event", "Ledger_store", "*>"),
        })

    def test_joined_sources_all_connect(self):
        g = render.parse_document("[A] & [B] -> [C]\n")
        self.assertEqual(edges(g), {
            ("A_service", "C_service", "->"),
            ("B_service", "C_service", "->"),
        })

    def test_race_join(self):
        g = render.parse_document("[A] -> [B] &? [C]\n")
        self.assertEqual(len(g.edges), 2)

    def test_plain_chain_unchanged(self):
        g = render.parse_document("(User) -> [API] -> |DB|\n")
        self.assertEqual(edges(g), {
            ("User_actor", "API_service", "->"),
            ("API_service", "DB_store", "->"),
        })

    def test_continuation_inherits_subject(self):
        # language.md: a continuation line inherits only the SUBJECT (the first
        # glyph) of the line above — not its last target (pitfall 9).
        g = render.parse_document("[A] -> [B]\n  -> [C] & [D]\n")
        self.assertIn(("A_service", "C_service", "->"), edges(g))
        self.assertIn(("A_service", "D_service", "->"), edges(g))
        self.assertNotIn(("B_service", "C_service", "->"), edges(g))


class TestHoles(unittest.TestCase):
    def test_holes_are_distinct_nodes(self):
        g = render.parse_document("#!sketch\n[?] -> [X]\n[?] -> [Y]\n")
        holes = [n for n in g.nodes.values() if n.is_hole]
        self.assertEqual(len(holes), 2)
        self.assertEqual(len({e.src for e in g.edges}), 2)

    def test_hole_ids_unique_across_expansions(self):
        g = render.parse_document("#!sketch\n[P] -> [?]\n[P] := {\n  [?] -> [Q]\n}\n")
        outer = {n.id for n in g.nodes.values() if n.is_hole}
        inner = {n.id for sub in g.expansions.values()
                 for n in sub.nodes.values() if n.is_hole}
        self.assertTrue(outer and inner)
        self.assertFalse(outer & inner)


class TestPayload(unittest.TestCase):
    def test_payload_kept_on_final_edge(self):
        g = render.parse_document("(User) -> [API] -> [Inv] : reserve => {Hold}\n")
        by_dst = {e.dst: e for e in g.edges}
        self.assertEqual(by_dst["Inv_service"].payload, "reserve => {Hold}")
        self.assertIsNone(by_dst["API_service"].payload)
        self.assertNotIn("Hold_data", g.nodes)   # payload glyphs are not nodes

    def test_payload_not_in_mermaid(self):
        out = render.render('[A] -> [B] : ${x} @state\n')
        self.assertNotIn("${x}", out)


class TestExpansions(unittest.TestCase):
    def test_expansion_before_first_use_attaches(self):
        g = render.parse_document("[API] := {\n  [Auth] -> [H]\n}\n(U) -> [API]\n")
        self.assertIn("API_service", g.expansions)

    def test_unreferenced_definition_is_a_node(self):
        g = render.parse_document("[Core] := {\n  [A] -> [B]\n}\n")
        self.assertIn("Core_service", g.nodes)
        self.assertIn("Core_service", g.expansions)


JOB = """state {Job} {
  +         -<submit>->    Pending
  Pending   -<pick>->      Running
  Running   -<fail>->      Retryable
  Retryable -<retry>->     Pending     ×3
  Running   -<ok>->        $
  _         -<cancel>->    Cancelled
}
"""


class TestStateMachines(unittest.TestCase):
    def test_state_block_hangs_off_entity(self):
        g = render.parse_document(JOB)
        self.assertIn("Job_data", g.nodes)
        machine = g.expansions["Job_data"]
        self.assertEqual(machine.role, "state")
        names = {n.name for n in machine.nodes.values()}
        self.assertTrue({"Pending", "Running", "Retryable", "Cancelled"} <= names)
        pseudo = {n.attrs.get("pseudo") for n in machine.nodes.values()} - {None}
        self.assertEqual(pseudo, {"start", "end", "any"})

    def test_transitions_carry_triggers_and_modifiers(self):
        machine = render.parse_document(JOB).expansions["Job_data"]
        by_label = {e.label: e for e in machine.edges}
        self.assertIn("<retry>", by_label)
        self.assertEqual(by_label["<retry>"].payload, "×3")
        self.assertEqual(len(machine.edges), 6)

    def test_state_ids_unique_per_entity(self):
        doc = JOB + JOB.replace("{Job}", "{Task}")
        g = render.parse_document(doc)
        a = set(g.expansions["Job_data"].nodes)
        b = set(g.expansions["Task_data"].nodes)
        self.assertFalse(a & b)

    def test_mermaid_escapes_trigger_labels(self):
        out = render.render(JOB)
        self.assertIn('-- "&lt;submit&gt;" -->', out)
        self.assertIn("classDef state", out)


EVT = """#!sketch
[Payments] ~> <Paid>
[Checkout] ~> <Placed>
state {Order} {
  +     -<Placed>-> Open
  Open  -<paid>->   Settled
}
state [Checkout] {
  Idle  -<Placed>-> Busy
  Busy  -<Paid>->   Idle
}
"""


class TestStateOwnersAndTriggers(unittest.TestCase):
    def test_any_glyph_owns_a_machine(self):
        g = render.parse_document(EVT)
        self.assertEqual(g.expansions["Checkout_service"].role, "state")
        self.assertEqual(g.expansions["Order_data"].role, "state")

    def test_events_become_triggers_case_insensitively(self):
        g = render.parse_document(EVT)
        got = {(t.event, t.owner, t.dst) for t in g.triggers}
        self.assertEqual(got, {
            ("Placed_event", "Order_data", "Order_state_Open"),
            ("Paid_event", "Order_data", "Order_state_Settled"),
            ("Placed_event", "Checkout_service", "Checkout_state_Busy"),
            ("Paid_event", "Checkout_service", "Checkout_state_Idle"),
        })

    def test_unmatched_trigger_is_not_wired(self):
        g = render.parse_document("state {Job} {\n  + -<submit>-> Pending\n}\n")
        self.assertEqual(g.triggers, [])

    def test_mermaid_trigger_edges_follow_depth(self):
        self.assertIn('Paid_event -. "triggers" .-> Order_state_Settled', render.render(EVT))
        self.assertIn('Paid_event -. "triggers" .-> Order_data', render.render(EVT, depth=0))

    def test_machine_beside_an_expansion(self):
        doc = "[Checkout] := {\n  [Cart] -> [Pay]\n}\nstate [Checkout] {\n  Idle -<go>-> Busy\n}\n"
        g = render.parse_document(doc)
        inner = g.expansions["Checkout_service"]
        self.assertEqual(inner.role, "expansion")
        self.assertEqual(inner.expansions["Checkout_service_machine"].role, "state")


NOTED = """#!sketch
# a title, detached by the blank line below

# routes traffic
# across zones
[Router]
    \\-(3)-> [ZoneA]   # 3:1 while B migrates
[Core] := {
  # inside
  [API] -> |DB|
}
(User) -> [Router]   # every request
"""


class TestNotes(unittest.TestCase):
    def setUp(self):
        self.g = render.parse_document(NOTED)

    def test_own_line_comments_merge_onto_next_statement(self):
        by = {n.node: n.text for n in self.g.notes}
        self.assertEqual(by["Router_service"], "routes traffic across zones")

    def test_title_detached_by_blank_line(self):
        # A header comment that precedes no statement is the document's own note.
        title = [n for n in self.g.notes if "title" in n.text]
        self.assertEqual([(n.node, n.block, n.line) for n in title], [(None, None, 2)])

    def test_trailing_comment_on_branch_and_flow(self):
        by = {n.node: n.text for n in self.g.notes}
        self.assertEqual(by["ZoneA_service"], "3:1 while B migrates")
        self.assertEqual(by["User_actor"], "every request")    # a flow's source

    def test_notes_inside_expansions(self):
        sub = self.g.expansions["Core_service"]
        self.assertEqual([(n.node, n.text) for n in sub.notes], [("API_service", "inside")])

    def test_mode_line_is_not_a_note(self):
        g = render.parse_document("#!spec\n[A] -> [B]\n")
        self.assertEqual(g.notes, [])


class TestExpansionForms(unittest.TestCase):
    def test_nested_expansions(self):
        doc = ("[Shop] := {\n  [Cart] -> [Payments]\n  [Payments] := {\n"
               "    [Gateway] -> [Risk]\n    [Risk] := {\n      [Model] -> |Features|\n"
               "    }\n  }\n}\n")
        g = render.parse_document(doc)
        shop = g.expansions["Shop_service"]
        pay = shop.expansions["Payments_service"]
        self.assertIn("Model_service", pay.expansions["Risk_service"].nodes)
        self.assertNotIn("Payments_service", g.expansions)      # not hoisted to top

    def test_one_line_expansions_do_not_swallow_the_next_line(self):
        g = render.parse_document("[A] := { [x] -> [y] }\n[B] := { [p] -> [q] }\n[A] -> [B]\n")
        self.assertEqual(set(g.expansions), {"A_service", "B_service"})
        self.assertIn(("A_service", "B_service"), {(e.src, e.dst) for e in g.edges})


if __name__ == "__main__":
    unittest.main()
