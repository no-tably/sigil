"""Tests for scene.py — the shared presentation model both views draw and the
simulator runs.

Covers:
  1. units: the document and its expansions up to a depth, in outline order;
  2. wires: one per flow edge with its key, payload, mods, inline notes, joins,
     block, alternatives group; triggers (to the state, or to the owner when the
     machine isn't drawn); access, arm and compose wires; the role order;
  3. the events transform: a pass-through event drawn where it lands (emit
     wires, landed labels, a `!>` emission kept), events kept as nodes, what is
     never collapsed, a top-level event an expansion also writes;
  4. annotations keyed by stroke: chip texts, notes, joins — an emit stroke
     carrying its legs';
  5. the colour policy and the simulation overlays;
  6. graph-view wiring (trigger / access edges, a machine's trigger sources);
  7. determinism, and a Scene for every golden input.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


scene = _load("sigil_scene_test", _DIR / "scene.py")
kit = scene.kit
render = kit.render


def build(text: str, **options):
    return scene.build_scene(render.parse_document(text), **options)


def keys(sc, role: str) -> list:
    return [w.key for w in sc.wires if w.role == role]


ORDERS = """\
(Shopper) -> [Checkout] -> {Order}
[Checkout] ~> <Placed>
[Payments] ~> <Paid>
[Payments] !> <Declined>   # card refused

state {Order} {
  +     -<Placed>->    Open
  Open  -<Paid>->      Settled
  Open  -<Declined>->  Cancelled
}
"""

RELAY = """\
[Api] -> <Done> : {Receipt}   # emitted
<Done> -> [Mailer] : {Mail}
<Done> -> [Ledger]
[Worker] !> <Crashed>
<Crashed> -> [Pager]
"""


class Units(unittest.TestCase):
    TEXT = """\
[Shop] -> [Cart]
[Cart] := {
  [Line] -> [Price]
  [Price] := {
    [Tax] -> [Sum]
  }
}
"""

    def test_depth_limits_the_units(self):
        g = render.parse_document(self.TEXT)
        self.assertEqual([(u.owner, u.level) for u in scene.drawn_units(g, 0)], [(None, 0)])
        self.assertEqual([(u.owner, u.level) for u in scene.drawn_units(g, 1)],
                         [(None, 0), ("Cart_service", 1)])
        self.assertEqual([u.owner for u in scene.drawn_units(g, kit.ALL_DEPTH)],
                         [None, "Cart_service", "Price_service"])

    def test_wires_only_from_drawn_units(self):
        self.assertEqual(keys(build(self.TEXT, depth=0), "flow"),
                         [("Shop_service", "Cart_service", "->")])
        sc = build(self.TEXT, depth=kit.ALL_DEPTH)
        self.assertEqual([(w.key, w.owner, w.level) for w in sc.wires if w.role == "flow"],
                         [(("Shop_service", "Cart_service", "->"), None, 0),
                          (("Line_service", "Price_service", "->"), "Cart_service", 1),
                          (("Tax_service", "Sum_service", "->"), "Price_service", 2)])

    def test_nodes_first_seen_with_their_unit(self):
        sc = build(self.TEXT, depth=1)
        self.assertIsNone(sc.nodes["Cart_service"].unit)
        self.assertEqual(sc.nodes["Line_service"].unit, "Cart_service")
        self.assertIn("Tax_service", sc.nodes)          # undrawn, still known

    def test_outline_order_follows_the_composition_tree(self):
        g = render.parse_document("[B]\n[A]\n    \\-> [B]\n")
        self.assertEqual(scene.outline_ids(g), ["A_service", "B_service"])


class Wires(unittest.TestCase):
    def test_flow_fields(self):
        sc = build("[A] -> [B] : {Order} @timeout(2s)   # slow\n")
        (w,) = sc.wires
        self.assertEqual((w.role, w.key, w.payload, w.line), ("flow", ("A_service", "B_service", "->"),
                                                              "{Order}", 1))
        self.assertEqual(w.mods, [("timeout", "2s")])
        self.assertEqual(w.notes, ((1, "slow"),))
        self.assertIs(w.edge, sc.graph.edges[0])

    def test_joins_and_alternatives(self):
        sc = build("[Api] -> [PspA] &? [PspB]\n[Api] => {Resp} / {Err}\n")
        flows = [w for w in sc.wires if w.role == "flow"]
        self.assertEqual([w.join for w in flows[:2]], [{"dst": "&?"}, {"dst": "&?"}])
        self.assertEqual([w.alt for w in flows], [None, None, "/join1", "/join1"])

    def test_a_broadcast_list_is_no_join(self):
        sc = build("[Bus] *> [A] & [B]\n")
        self.assertEqual([w.join for w in sc.wires], [{}, {}])

    def test_block_index(self):
        sc = build("[A] -> [B]\nloop @while |Q|.nonempty {\n  [B] -> [C]\n}\n")
        self.assertEqual([w.block for w in sc.wires if w.role == "flow"], [None, 0])
        self.assertEqual(sc.nodes["C_service"].blocks, (0,))
        self.assertEqual([(r.owner, r.index, r.block.kind) for r in sc.blocks], [(None, 0, "loop")])

    def test_triggers_go_to_the_state_or_the_owner(self):
        drawn = build(ORDERS, depth=1)
        self.assertIn(("Paid_event", "Order_state_Settled", "trigger"), keys(drawn, "trigger"))
        hidden = build(ORDERS, depth=0)
        self.assertIn(("Paid_event", "Order_data", "trigger"), keys(hidden, "trigger"))
        self.assertEqual({w.machine for w in hidden.wires if w.role == "trigger"}, {"Order_data"})
        self.assertEqual(keys(build(ORDERS, triggers=False), "trigger"), [])

    def test_access_wires_and_badges(self):
        text = "|Log| @read(Auditor) @write(Api, Worker)\n(Auditor)\n[Api]\n[Worker]\n"
        self.assertEqual(keys(build(text), "access"), [])
        sc = build(text, access=True)
        self.assertEqual(sorted(w.kind for w in sc.wires if w.role == "access"),
                         ["access:r", "access:w", "access:w"])
        self.assertEqual(sc.nodes["Log_store"].badges, ["2w"])

    def test_arm_wires(self):
        sc = build("branch on {Request}.kind {\n  read  => [Reader]\n  write => [Writer]\n}\n")
        arms = [w for w in sc.wires if w.role == "arm"]
        self.assertEqual([(w.src, w.dst, w.label) for w in arms],
                         [("Request_data", "Reader_service", "read"),
                          ("Request_data", "Writer_service", "write")])
        self.assertEqual({w.alt for w in arms}, {"/branch0"})
        self.assertEqual(sc.nodes["Reader_service"].arms, ["read"])

    def test_compose_wires(self):
        sc = build("[Ship]\n    \\-> [Hull]\n    \\-*-> [Bullet]\n")
        self.assertEqual([(w.key, w.spawn) for w in sc.wires if w.role == "compose"],
                         [(("Ship_service", "Hull_service", "\\->"), False),
                          (("Ship_service", "Bullet_service", "\\->"), True)])

    def test_role_order(self):
        text = ("|S| @write(Api)\n[Api] -> [B]\nbranch on {R}.k {\n  a => [X]\n}\n"
                "[Ship]\n    \\-> [Hull]\n")
        roles = [w.role for w in build(text, access=True).wires]
        self.assertEqual(roles, sorted(roles, key=scene.ROLES.index))

    def test_unknown_events_mode(self):
        with self.assertRaises(ValueError):
            build("[A] -> [B]\n", events="boxes")


class Events(unittest.TestCase):
    def test_nodes_mode_keeps_the_event(self):
        sc = build(RELAY, events="nodes")
        self.assertEqual(sc.collapsed, frozenset())
        self.assertEqual(keys(sc, "emit"), [])

    def test_land_wires_emitter_to_destinations(self):
        sc = build(RELAY, events="land")
        self.assertEqual(sc.collapsed, {"Done_event", "Crashed_event"})
        emits = [w for w in sc.wires if w.role == "emit"]
        self.assertEqual([(w.key, w.via) for w in emits],
                         [(("Api_service", "Mailer_service", "->"), "Done_event"),
                          (("Api_service", "Ledger_service", "->"), "Done_event"),
                          (("Worker_service", "Pager_service", "!>"), "Crashed_event")])
        self.assertFalse([w for w in sc.wires if "Done_event" in (w.src, w.dst)
                          and w.role != "emit"])
        self.assertEqual([n.id for n in sc.nodes["Mailer_service"].landed], ["Done_event"])
        self.assertEqual([leg.key for leg in emits[0].legs],
                         [("Api_service", "Done_event", "->"), ("Done_event", "Mailer_service", "->")])

    def test_a_failure_emission_stays_a_failure(self):
        sc = build(RELAY, events="land")
        crash = next(w for w in sc.wires if w.via == "Crashed_event")
        self.assertEqual((crash.kind, crash.colour), ("!>", "edges-fail"))

    def test_delivered_by_a_trigger(self):
        sc = build(ORDERS, events="land", depth=1)
        self.assertIn("Paid_event", sc.collapsed)
        w = next(w for w in sc.wires if w.role == "emit" and w.via == "Paid_event")
        self.assertEqual((w.kind, w.colour), ("trigger", "kinds-event"))
        # a trigger names the event on the state's row already: nothing lands
        self.assertEqual(sc.nodes["Order_state_Settled"].landed, [])
        # `!>` into the event, delivered by a trigger: the trigger's stroke
        dec = next(w for w in sc.wires if w.via == "Declined_event")
        self.assertEqual(dec.kind, "trigger")

    def test_one_stroke_two_events(self):
        text = "[P] ~> <Paid>\n[P] !> <Declined>   # refused\n<Paid> -> [S]\n<Declined> -> [S]\n"
        sc = build(text, events="land")
        self.assertEqual(len(keys(sc, "emit")), 2)
        self.assertEqual(scene.wire_notes(sc)[("P_service", "S_service", "!>")], [(1, "refused")])

    def test_never_collapsed(self):
        cases = {
            "only emitted": "[A] -> <E>\n",
            "only delivered": "<E> -> [B]\n",
            "has parts": "[A] -> <E>\n<E> -> [B]\n<E>\n    \\-> {P}\n",
            "a machine": "[A] -> <E>\n<E> -> [B]\nstate <E> {\n  a -<F>-> b\n}\n",
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.assertNotIn("E_event", build(text, events="land").collapsed)

    def test_a_top_level_event_an_expansion_also_holds_lands(self):
        # the document's row goes; the expansion's occurrence stays in its
        # unit's graph, but every wire touching the event becomes an emit
        text = "[Shop] := { [Cart] ~> <Bought> }\n<Bought> -> [Mailer]\n(User) -> [Shop]\n"
        sc = build(text, events="land", depth=kit.ALL_DEPTH)
        self.assertEqual(sc.collapsed, {"Bought_event"})
        self.assertIn("Bought_event", sc.graph.expansions["Shop_service"].nodes)
        self.assertEqual([(w.key, w.owner, w.via) for w in sc.wires if w.role == "emit"],
                         [(("Cart_service", "Mailer_service", "->"), "Shop_service",
                           "Bought_event")])
        self.assertFalse([w for w in sc.wires if "Bought_event" in (w.src, w.dst)])
        self.assertEqual([n.id for n in sc.nodes["Mailer_service"].landed], ["Bought_event"])

    def test_a_composition_branch_or_parent_never_lands(self):
        for text in ("[A] -> <E>\n<E> -> [B]\n[P]\n    \\-> <E>\n",
                     "[A] -> <E>\n<E> -> [B]\n<E>\n    \\-> [C]\n"):
            with self.subTest(text):
                self.assertNotIn("E_event", build(text, events="land").collapsed)


class Annotations(unittest.TestCase):
    def test_chip_texts(self):
        sc = build("[A] -> [B] : {Order} @timeout(2s)\n")
        key = ("A_service", "B_service", "->")
        self.assertEqual(scene.chip_texts(sc, True, False), {key: "{Order}"})
        self.assertEqual(scene.chip_texts(sc, True, True), {key: "{Order} ┆ @timeout 2s"})
        self.assertEqual(scene.chip_texts(sc, False, False), {})

    def test_an_emit_carries_its_legs(self):
        sc = build(RELAY, events="land")
        chips = scene.chip_texts(sc, True, False)
        self.assertEqual(chips[("Api_service", "Mailer_service", "->")], "{Receipt} · {Mail}")
        self.assertEqual(chips[("Api_service", "Ledger_service", "->")], "{Receipt}")
        notes = scene.wire_notes(sc)
        self.assertEqual(notes[("Api_service", "Ledger_service", "->")], [(1, "emitted")])

    def test_node_keyed_notes(self):
        sc = build("[A]   # alone\n")
        self.assertEqual(scene.wire_notes(sc), {"A_service": [(1, "alone")]})
        self.assertEqual(sc.nodes["A_service"].notes, [(1, "alone", "inline", ())])

    def test_join_marks(self):
        sc = build("[A] & [B] -> [C]\n")
        self.assertEqual(scene.join_marks(sc), {("A_service", "C_service", "->"): {"src": "&"},
                                                ("B_service", "C_service", "->"): {"src": "&"}})

    def test_sections(self):
        sc = build("--- L1: One ---\n[A] -> [B]\n--- L2: Two ---\n[C] -> [D]\n")
        self.assertEqual([s.title for s in sc.sections], ["One", "Two"])
        self.assertEqual((sc.nodes["A_service"].section, sc.nodes["D_service"].section), (0, 1))


class ColourPolicy(unittest.TestCase):
    def colours(self, text, **options):
        return {w.key: w.colour for w in build(text, **options).wires}

    def test_arrow_colour_else_source_kind(self):
        got = self.colours("(U) -> [A]\n[A] -> |S|\n[A] !> [B]\n[A] ?> [C]\n[A] ~> [D]\n"
                           "[A] => {X}\n")
        self.assertEqual(list(got.values()), ["kinds-actor", "kinds-service", "edges-fail",
                                              "edges-maybe", "edges-async", "kinds-service"])

    def test_own_colours(self):
        self.assertEqual(scene.arrow_colour("trigger"), "kinds-event")
        self.assertEqual(scene.arrow_colour("access:w"), "edges-access")
        self.assertEqual(scene.arrow_colour("arm"), "edges-arm")
        self.assertEqual(scene.arrow_colour("]>["), "edges-split")
        self.assertIsNone(scene.arrow_colour("->"))

    def test_emit_takes_the_event_colour(self):
        got = self.colours(RELAY, events="land")
        self.assertEqual(got[("Api_service", "Mailer_service", "->")], "kinds-event")

    def test_roles_resolve_to_theme_colours(self):
        for role in ("edges-fail", "edges-maybe", "edges-async", "edges-split", "edges-arm",
                     "edges-access", "edges-default", "kinds-service", "kinds-event"):
            with self.subTest(role):
                self.assertEqual(scene.colour_of(role).role, role)

    def test_theme_applied_later_reaches_a_built_scene(self):
        sc = build("[A] !> [B]\n")
        try:
            kit.apply_theme({"edges": {"fail": "#123456"}})
            self.assertEqual(scene.wire_style(sc.wires[0]), ("#123456", None, False))
        finally:
            kit.use_theme(None)

    def test_overlays(self):
        w = build("[A] -> [B]\n").wires[0]
        base = scene.colour_of("kinds-service")
        self.assertEqual(scene.wire_style(w), (base, None, False))
        self.assertEqual(scene.wire_style(w, "active"), (base, None, True))
        self.assertEqual(scene.wire_style(w, "inactive"), (kit.muted(base), None, False))
        self.assertEqual(scene.wire_style(w, "failed"), (scene.colour_of("edges-fail"), None, True))
        with self.assertRaises(ValueError):
            scene.wire_style(w, "lit")


class GraphWiring(unittest.TestCase):
    def test_trigger_edges_to_the_owner(self):
        sc = build(ORDERS, depth=1)
        edges = scene.trigger_edges(sc, sc.graph.nodes)
        self.assertEqual([(e.src, e.dst, e.kind) for e in edges],
                         [("Placed_event", "Order_data", "trigger"),
                          ("Paid_event", "Order_data", "trigger"),
                          ("Declined_event", "Order_data", "trigger")])

    def test_machine_trigger_sources(self):
        sc = build(ORDERS, depth=1)
        machine = sc.graph.expansions["Order_data"]
        drawn = scene.with_trigger_sources(sc, machine, "Order_data")
        self.assertIn("Paid_event", drawn.nodes)
        self.assertIn(("Paid_event", "Order_state_Settled", "trigger"), [e.key for e in drawn.edges])
        self.assertFalse([e for e in drawn.edges if e.label == "<Paid>"])
        off = build(ORDERS, depth=1, triggers=False)
        self.assertIs(scene.with_trigger_sources(off, machine, "Order_data"), machine)

    def test_access_edges(self):
        sc = build("|Log| @write(Api)\n[Api]\n", access=True)
        self.assertEqual([(e.src, e.dst, e.kind) for e in scene.access_edges(sc, sc.graph.nodes)],
                         [("Api_service", "Log_store", "access:w")])
        self.assertEqual(scene.access_edges(sc, {"Api_service": None}), [])

    def test_access_edges_of_one_unit(self):
        text = ("|Log| @write(Api)\n[Api]\n"
                "[Svc] := {\n  |Db| @read(Worker)\n  [Worker] -> |Db|\n}\n")
        sc = build(text, access=True)
        every = {**sc.graph.nodes, **sc.graph.expansions["Svc_service"].nodes}
        pairs = lambda unit: [(e.src, e.dst) for e in scene.access_edges(sc, every, unit)]
        self.assertEqual(pairs(None), [("Api_service", "Log_store")])
        self.assertEqual(pairs("Svc_service"), [("Worker_service", "Db_store")])
        self.assertEqual([(e.src, e.dst) for e in scene.access_edges(sc, every)],
                         pairs(None) + pairs("Svc_service"))


class LandedDrivers(unittest.TestCase):
    """What drives a machine when its events are drawn where they land: the
    emitters, never the collapsed events."""

    def setUp(self):
        self.sc = build(ORDERS, depth=1, events="land")
        self.machine = self.sc.graph.expansions["Order_data"]

    def test_driver_wires_are_the_trigger_delivered_emits(self):
        self.assertEqual([(w.role, w.src, w.dst, w.machine, w.label)
                          for w in scene.driver_wires(self.sc)],
                         [("emit", "Checkout_service", "Order_state_Open", "Order_data", "<Placed>"),
                          ("emit", "Payments_service", "Order_state_Settled", "Order_data", "<Paid>"),
                          ("emit", "Payments_service", "Order_state_Cancelled", "Order_data",
                           "<Declined>")])

    def test_driver_wires_with_events_as_nodes(self):
        sc = build(ORDERS, depth=1)
        self.assertEqual({w.role for w in scene.driver_wires(sc)}, {"trigger"})
        self.assertEqual(scene.driver_wires(build(ORDERS, depth=1, triggers=False)), [])

    def test_trigger_edges_from_the_emitters(self):
        self.assertEqual([e.key for e in scene.trigger_edges(self.sc, self.sc.graph.nodes)],
                         [("Checkout_service", "Order_data", "trigger"),
                          ("Payments_service", "Order_data", "trigger")])

    def test_an_owner_driving_its_own_machine_is_no_trigger_edge(self):
        text = "[Svc] ~> <Go>\n<Go> -> [Svc]\nstate [Svc] {\n  idle -<Go>-> busy\n}\n"
        sc = build(text, events="land", depth=1)
        self.assertIn("Svc_service", {w.machine for w in scene.driver_wires(sc)})
        self.assertEqual(scene.trigger_edges(sc, sc.graph.nodes), [])

    def test_machine_sources_are_emitters_not_collapsed_events(self):
        drawn = scene.with_trigger_sources(self.sc, self.machine, "Order_data")
        self.assertFalse(self.sc.collapsed & set(drawn.nodes))
        self.assertIn("Payments_service", drawn.nodes)
        self.assertIn(("Payments_service", "Order_state_Cancelled", "trigger"),
                      [e.key for e in drawn.edges])
        self.assertFalse([e for e in drawn.edges if e.label])

    def test_a_flow_delivered_emit_drives_nothing(self):
        self.assertFalse([w for w in build(RELAY, events="land").wires if w.machine])


class EveryInput(unittest.TestCase):
    """A Scene for every golden input, every way, deterministically."""

    @classmethod
    def setUpClass(cls):
        golden = _load("sigil_golden_scene", _DIR / "tools" / "golden.py")
        cls.inputs = golden.collect_inputs(_DIR)

    def test_builds_and_is_well_formed(self):
        for inp in self.inputs:
            g = render.parse_document(inp.text)
            for events in scene.EVENTS:
                with self.subTest(inp.name, events=events):
                    sc = scene.build_scene(g, events=events, access=True, depth=kit.ALL_DEPTH)
                    for w in sc.wires:
                        self.assertIn(w.role, scene.ROLES)
                        self.assertEqual(w.key, (w.src, w.dst, w.kind))
                        self.assertTrue(w.colour)
                        self.assertNotIn(w.src, sc.collapsed)
                        self.assertNotIn(w.dst, sc.collapsed)

    def test_deterministic(self):
        for inp in self.inputs:
            g = render.parse_document(inp.text)
            with self.subTest(inp.name):
                a = scene.build_scene(g, events="land", access=True)
                b = scene.build_scene(g, events="land", access=True)
                self.assertEqual([(w.key, w.role, w.colour, w.via) for w in a.wires],
                                 [(w.key, w.role, w.colour, w.via) for w in b.wires])


if __name__ == "__main__":
    unittest.main()
