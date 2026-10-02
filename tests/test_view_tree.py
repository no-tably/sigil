"""Tests for view_tree.py on the shared Scene (scene.py).

Covers:
  - events "land" (the default): a pass-through event has no row; its emitters
    are wired straight to its destinations with the `›` emit mark, its label on
    each destination's row; a failure emission keeps its `✖`;
  - events "nodes": the event row comes back, lanes into and out of it;
  - an unknown events mode is an error, not a silent default;
  - the colour policy: lanes take their wire's colour — an arrow's own colour,
    else the source's kind; a permission lane the access colour; an emitted
    event the event colour;
  - the moved annotations still land: payload chips (an emit's from both legs),
    inline notes, join taps, branch-arm labels.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]


def _load(name: str, fname: str):
    spec = importlib.util.spec_from_file_location(name, _DIR / fname)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


view = _load("sigil_view_tree_tests", "view.py")
vtree, kit = view.vtree, view.kit

EMITTED = ("[API] => <Placed>\n[API] !> <Failed>\n"
           "<Placed> *> [Email]\n<Placed> *> [Ship]\n<Failed> -> [Alert]\n")


def tree(text: str, **kw):
    return vtree.compose_tree(view.render.parse_document(text), kw.pop("depth", 1), **kw)[0]


def plain(rows) -> list:
    return ["".join(t for t, _ in r) for r in rows]


def row(rows, start: str):
    """The first row whose text starts with `start`."""
    return next(r for r in rows if plain([r])[0].startswith(start))


def style_of(r, ch: str):
    """The style of the first run in row r containing ch."""
    return next(st for t, st in r if ch in t)


class TestEventsLand(unittest.TestCase):
    def setUp(self):
        self.rows = tree(EMITTED)
        self.text = plain(self.rows)

    def test_default_is_land(self):
        self.assertEqual(self.text, plain(tree(EMITTED, events="land")))

    def test_event_has_no_row(self):
        self.assertFalse([ln for ln in self.text if ln.startswith(("<Placed>", "<Failed>"))])

    def test_event_label_on_its_destinations(self):
        for dst in ("[Email]", "[Ship]"):
            self.assertTrue(plain([row(self.rows, dst)])[0].startswith(dst + " <Placed>"))
        self.assertTrue(plain([row(self.rows, "[Alert]")])[0].startswith("[Alert] <Failed>"))

    def test_emit_marks(self):
        api = plain([row(self.rows, "[API]")])[0]
        self.assertIn(vtree.EMIT_MARK, api)
        self.assertIn("✖", api)                        # a failure emission stays a failure

    def test_emit_lane_takes_the_event_colour(self):
        api = row(self.rows, "[API]")
        self.assertEqual(style_of(api, vtree.EMIT_MARK)[0], kit.kind_color("event"))
        self.assertEqual(style_of(api, "✖")[0], kit.EDGE_COLOR["!>"])


class TestEventsNodes(unittest.TestCase):
    def setUp(self):
        self.rows = tree(EMITTED, events="nodes")
        self.text = plain(self.rows)

    def test_event_rows_come_back(self):
        for ev in ("<Placed>", "<Failed>"):
            self.assertTrue(any(ln.startswith(ev + " ◀") for ln in self.text), ev)

    def test_no_emit_marks_or_landed_labels(self):
        self.assertNotIn(vtree.EMIT_MARK, "\n".join(self.text))
        self.assertTrue(plain([row(self.rows, "[Email]")])[0].startswith("[Email] ◀"))

    def test_lanes_out_of_the_event(self):
        placed = row(self.rows, "<Placed>")
        self.assertEqual(style_of(placed, "✱")[0], kit.kind_color("event"))

    def test_unknown_mode_is_an_error(self):
        with self.assertRaises(ValueError):
            tree(EMITTED, events="hubs")


class TestColourPolicy(unittest.TestCase):
    def test_plain_flow_takes_the_source_kind(self):
        rows = tree("(User) -> [API]\n[API] ~> [Worker]\n")
        self.assertEqual(style_of(row(rows, "(User)"), "●")[0], kit.kind_color("actor"))
        self.assertEqual(style_of(row(rows, "[API]"), "○")[0], kit.EDGE_COLOR["~>"])

    def test_access_lane_takes_the_access_colour(self):
        rows = tree("[Boss]\n|Results| @write(Boss)\n", access=True)
        boss = row(rows, "[Boss]")
        self.assertEqual(style_of(boss, "w")[0], kit.EDGE_COLOR["access"])

    def test_legend_trigger_sample_is_the_event_colour(self):
        wires = vtree.tree_legend(triggers=True)[1]
        sample = next(st for t, st in wires if t.startswith("◎"))
        self.assertEqual(sample[0], kit.kind_color("event"))


class TestLegendEvents(unittest.TestCase):
    @staticmethod
    def wires_text(events: str) -> str:
        return "".join(t for t, _ in vtree.tree_legend(events=events)[1])

    def test_land_shows_the_emit_mark(self):
        self.assertIn(vtree.EMIT_MARK + "─ emits", self.wires_text("land"))

    def test_nodes_drops_the_emit_mark(self):
        self.assertNotIn("emits", self.wires_text("nodes"))

    def test_unknown_mode_is_an_error(self):
        with self.assertRaises(ValueError):
            vtree.tree_legend(events="hubs")


class TestAnnotations(unittest.TestCase):
    def test_emit_chip_joins_both_legs(self):
        rows = tree("[API] => <Placed> : order\n<Placed> -> [Email] : mail\n", payloads=True)
        self.assertIn("order · mail", plain([row(rows, "[Email]")])[0])

    def test_inline_note_trails_its_flow(self):
        rows = tree("[A] -> [B]  # the hand-off\n", notes="callouts")
        self.assertIn("# the hand-off", plain([row(rows, "[B]")])[0])

    def test_join_tap(self):
        rows = tree("[A] -> [B] & [C]\n")
        self.assertIn("◀&", plain([row(rows, "[B]")])[0])

    def test_branch_arm_label(self):
        doc = "branch on {Request}.kind {\n  read  => [Reader]\n  write => [Writer]\n}\n"
        text = "\n".join(plain(tree(doc)))
        self.assertIn("[Reader] ‹read›", text)
        self.assertIn("[Writer] ‹write›", text)


if __name__ == "__main__":
    unittest.main()


class TestMachineRules(unittest.TestCase):
    """A top-level state machine gets its own title rule, as in the graph view."""

    DOC = ("--- shop ---\n(User) -> [Cart] ~> <Placed>\n"
           "state {Order} {\n  + -<Placed>-> Open\n}\n"
           "state [Cart] {\n  Idle -<Placed>-> Busy\n}\n[Ledger] ~> <Placed>\n")

    def titles(self, text, **kw):
        return [ln.strip(" ─") for ln in plain(tree(text, **kw)) if ln.startswith("── ")]

    def test_rule_above_each_machine_and_section_resumes(self):
        # rows of the section after a machine: the section's rule comes back
        self.assertEqual(self.titles(self.DOC), [
            "shop", "[Cart] state machine", "shop", "{Order} state machine"])

    def test_back_to_back_machines_have_no_section_rule_between(self):
        text = (_DIR / "site" / "examples" / "04-orders.sigil").read_text()
        self.assertEqual(self.titles(text), [
            "orders", "[Checkout] state machine", "{Order} state machine", "orders"])

    def test_collapsed_machine_has_no_rule(self):
        self.assertEqual(self.titles(self.DOC, depth=0), ["shop"])
