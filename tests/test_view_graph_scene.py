"""Tests for view_graph.py on the Scene (scene.py) — what the graph view takes
from the shared presentation model rather than deriving itself.

Covers:
  1. the colour policy: a default edge in its source's kind colour, an arrow
     with a colour of its own (`!>`) in that colour, a chip half in its wire's;
  2. _wire_key: a chip / join bar stands in for the end of the wire it splits;
  3. the events "land" mode: the event box gone, emitter → destination edges in
     the event colour with the event's name beside the head, a `!>` emission
     keeping its ✖, a trigger-delivered event drawn from its emitter (overview
     and machine section); "nodes" (the default) keeps the box;
  4. inline notes on a landed edge ride beside the event name;
  5. with_chips' links from the Scene: trigger edges, then permission edges
     scoped to the part graph's own access (a `---` section);
  6. graph_legend's emits entry, in "land" mode only.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


view = _load("sigil_view", ROOT / "view.py")
vgraph, kit = view.vgraph, view.kit


def compose(text: str, depth: int = 1, events: str = "nodes", notes: str = "off",
            payloads: bool = False, access: bool = False):
    g = kit.render.parse_document(text)
    rows, _w = vgraph.compose(g, depth, payloads, notes, True, None, access, False, events)
    return rows


def plain(rows) -> str:
    return "\n".join("".join(t for t, _ in r) for r in rows)


def colours_of(rows, chars: str) -> set:
    """The foreground colours of the runs holding any of chars."""
    return {st[0] for r in rows for t, st in r if st and any(c in t for c in chars)}


class ColourPolicy(unittest.TestCase):
    def test_default_edge_takes_its_source_kind_colour(self):
        rows = compose("[A] -> |DB|\n")
        self.assertEqual(colours_of(rows, "▼"), {kit.kind_color("service")})

    def test_fail_edge_keeps_its_own_colour(self):
        rows = compose("[A] !> [B]\n")
        self.assertEqual(colours_of(rows, "✖"), {kit.EDGE_COLOR["!>"]})

    def test_both_chip_halves_take_their_wire_colour(self):
        rows = compose("(User) -> [A] : {Req}\n", payloads=True)
        self.assertEqual(colours_of(rows, "▼"), {kit.kind_color("actor")})


class WireKey(unittest.TestCase):
    def test_chip_and_join_stand_in_for_their_wire_ends(self):
        g = kit.render.parse_document("[A] & [B] -> [C] : {X}\n")
        gc = vgraph.with_chips(g, payloads=True)
        keys = {vgraph._wire_key(gc, e) for e in gc.edges}
        self.assertTrue(keys <= {("A_service", "C_service", "->"),
                                 ("B_service", "C_service", "->")}, keys)


class LandMode(unittest.TestCase):
    TEXT = "[API] ~> <Placed>\n<Placed> -> [Ship]\n[API] !> <Failed>\n<Failed> -> [Ops]\n"

    def test_nodes_mode_keeps_the_event_box(self):
        out = plain(compose(self.TEXT))
        self.assertIn("│ <Placed> │", out)

    def test_land_mode_drops_the_box_and_names_the_event_at_the_head(self):
        rows = compose(self.TEXT, events="land")
        out = plain(rows)
        self.assertNotIn("│ <Placed> │", out)
        self.assertIn("▼ <Placed>", out)
        self.assertIn("✖ <Failed>", out)                 # a `!>` emission stays a failure
        self.assertIn(kit.kind_color("event"), colours_of(rows, "▼"))
        self.assertEqual(colours_of(rows, "✖"), {kit.EDGE_COLOR["!>"]})

    def test_trigger_delivered_event_drawn_from_its_emitter(self):
        text = "[P] ~> <Paid>\nstate {Order} {\n  Open -<Paid>-> Settled\n}\n"
        out = plain(compose(text, events="land"))
        self.assertNotIn("│ <Paid> │", out)
        self.assertEqual(out.count("▼ <Paid>"), 2)       # [P] ⇢ {Order}, [P] ⇢ Settled
        self.assertEqual(out.count("│ [P] │"), 2)         # the overview and the machine

    def test_inline_note_rides_beside_the_event_name(self):
        out = plain(compose("[API] ~> <Placed>  # sent once\n<Placed> -> [Ship]\n",
                            events="land", notes="markers"))
        self.assertIn("▼ <Placed> #1", out)


    def test_one_stroke_per_landed_key(self):
        text = "[A] ~> <E>\n[A] ~> <E>\n<E> -> [B]\n"
        g = kit.render.parse_document(text)
        scn = vgraph.scene.build_scene(g, events="land")
        landed = vgraph._landed(g, scn, None)
        self.assertEqual([(e.src, e.dst) for e in landed.edges], [("A_service", "B_service")])


class SceneLinks(unittest.TestCase):
    def test_trigger_then_access_links_after_the_chip_edges(self):
        text = "[P] -> <Paid> : {Amount}\nstate {Order} {\n  Open -<Paid>-> Settled\n}\n" \
               "|DB| @write(P)\n"
        g = kit.render.parse_document(text)
        scn = vgraph.scene.build_scene(g, access=True)
        gc = vgraph.with_chips(g, payloads=True, scn=scn)
        kinds = [e.kind for e in gc.edges]
        self.assertEqual(kinds[-2:], ["trigger", "access:w"])
        self.assertEqual((gc.edges[-2].src, gc.edges[-2].dst), ("Paid_event", "Order_data"))
        self.assertIs(vgraph.with_chips(g), g)                   # no Scene: nothing linked

    def test_access_drawn_only_in_the_section_it_is_written_in(self):
        text = ("--- One ---\n[P] -> |DB|\n|DB| @write(P)\n"
                "--- Two ---\n[P] ~> |DB|\n")
        out = plain(compose(text, access=True))
        one, two = out.split("── Two")
        self.assertIn("┆", one)                                  # the dotted w edge
        self.assertNotIn("┆", two)


class Legend(unittest.TestCase):
    def test_emits_entry_only_when_events_land(self):
        text = lambda **kw: "".join(t for t, _ in vgraph.graph_legend(**kw))
        self.assertNotIn("emits", text())
        row = vgraph.graph_legend(events="land")
        entry = next(st for t, st in row if "<E>" in t)
        self.assertEqual(entry[0], kit.kind_color("event"))
        self.assertIn("▼ <E> emits", text(events="land"))


if __name__ == "__main__":
    unittest.main()
