"""Tests for the calls ("glyph executions") in view_tree.py.

Covers (design note: executions.md, E1–E12):
  - a self-call's mark on its subject's row, after the label: `↺` a self-call,
    `↻` recursion (a glyph self-edge, or an op naming its own alias), `⇱` a
    host op as the target — per unit, so a node drawn in two units shows each
    unit's own; the mark never collides with the row's `◀`;
  - `⇱` after the far node of an external op call;
  - with payloads, a self-call's chip on its row (no `── payloads ──` footer
    entry), returns as `↩ X`, never ` => ` or the `op ` keyword;
  - several calls into one target: one chip each, in written order, each in
    its wire's stroke (the `!>` one in the failure colour), never merged —
    not even two calls with equal text — also in the relocated panel at a
    narrow width;
  - the legend's call entries.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import re
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


vtree = _load("sigil_view_tree_calls_tests", "view_tree.py")
kit, scene = vtree.kit, vtree.scene

FIXTURE = (_DIR / "tests" / "fixtures" / "executions.sigil").read_text()

INDEX = ("[Indexer] -> |Index| : reserve(${shard}) => {Lease}\n"
         "[Indexer] -> |Index| : write({Doc}, {Lease})\n"
         "          !> |Index| : release({Lease})\n")


def tree(text: str, **kw):
    return vtree.compose_tree(kit.render.parse_document(text), kw.pop("depth", 1), **kw)[0]


def plain(rows) -> list:
    return ["".join(t for t, _ in r) for r in rows]


def line(rows, start: str) -> str:
    """The text of the first row that starts with `start` once its rails are off."""
    return next(ln for ln in plain(rows) if re.sub(r"^[│┆├└┌─┄ ]*", "", ln).startswith(start))


def chips(text: str) -> list:
    return re.findall(r"┆ (.+?) ┆", text)


class TestMarks(unittest.TestCase):
    def setUp(self):
        self.rows = tree(FIXTURE)

    def test_self_call_mark_before_the_target_head(self):
        self.assertRegex(line(self.rows, "[Scheduler]"), r"^\s*\[Scheduler\] ↺ ◀")

    def test_recursion_marks(self):
        for label in ("[Doc.walk]", "[Builder]"):
            self.assertIn(label + " ↻", line(self.rows, label))

    def test_each_unit_shows_its_own_self_calls(self):
        crawler = [ln for ln in plain(self.rows) if "[Crawler] " in ln and "◀" in ln]
        self.assertEqual(len(crawler), 2)
        self.assertIn("[Crawler] ↺", crawler[0])        # throttle, in the document
        self.assertIn("[Crawler] ↻", crawler[1])        # follow(.links), in `follow`

    def test_external_marks(self):
        self.assertIn("[Notifier] ⇱", line(self.rows, "[Notifier]"))
        self.assertIn("(Web) ⇱", line(self.rows, "(Web)"))

    def test_marks_without_colour_and_without_payloads(self):
        self.assertNotIn("┆", line(self.rows, "[Scheduler]"))

    def test_external_mark_takes_its_call_stroke(self):
        rows = tree("[Fetcher] ~> (Web) : op http.get(${url})\n")
        web = next(r for r in rows if plain([r])[0].startswith("(Web)"))
        style = next(st for t, st in web if vtree.EXTERNAL_MARK in t)
        self.assertEqual(style[0], kit.EDGE_COLOR["~>"])

    def test_state_self_transition_is_no_call(self):
        rows = tree("state [M] {\n  idle -> idle : <Tick>\n}\n", depth=1)
        text = "\n".join(plain(rows))
        self.assertIn("idle", text)
        self.assertNotIn("↻", text)


class TestChips(unittest.TestCase):
    def setUp(self):
        self.rows = tree(FIXTURE, payloads=True)
        self.text = "\n".join(plain(self.rows))

    def test_self_call_chip_on_its_row(self):
        self.assertEqual(chips(line(self.rows, "[Scheduler]"))[0], "↺ plan({Seed}) ↩ {Plan}")
        self.assertIn("↻ child", chips(line(self.rows, "[Doc.walk]")))
        self.assertIn("⇱ mail.send(${report})", chips(line(self.rows, "[Notifier]")))

    def test_no_footer_for_drawable_calls(self):
        self.assertNotIn("── payloads ──", self.text)

    def test_returns_and_external_ops_as_marks(self):
        every = chips(self.text)
        self.assertTrue(every)
        self.assertFalse([c for c in every if " => " in c or c.startswith("op ")])
        self.assertIn("crawl({Plan}) ↩ {Site}", every)
        self.assertIn("⇱ http.get(${url})", every)

    def test_several_calls_into_one_target_stay_apart(self):
        rows = tree(INDEX, payloads=True)
        self.assertEqual(chips(line(rows, "|Index|")),
                         ["reserve(${shard}) ↩ {Lease}", "write({Doc}, {Lease})",
                          "✖ release({Lease})"])            # the `!>`: led by ✖

    def test_equal_calls_are_two_chips(self):
        # Two calls with the same text are two calls: two chips, as in the graph.
        rows = tree("[P] -> [Q] : ping()\n[P] -> [Q] : ping()\n", payloads=True)
        self.assertEqual(chips(line(rows, "[Q]")), ["ping()", "ping()"])

    def test_each_chip_in_its_wire_stroke(self):
        rows = tree(INDEX, payloads=True)
        index = next(r for r in rows if plain([r])[0].startswith("|Index|"))
        borders = [st for t, st in index if t == " ┆"]
        self.assertEqual(len(borders), 3)
        self.assertEqual(borders[2][0], kit.EDGE_COLOR["!>"])
        self.assertEqual(borders[0][0], kit.kind_color("service"))

    def test_panel_keeps_chips_apart(self):
        rows = tree(INDEX, payloads=True, width=40)
        text = plain(rows)
        for call in ("reserve(${shard}) ↩ {Lease}", "write({Doc}, {Lease})", "release({Lease})"):
            self.assertTrue(any(ln.rstrip().endswith(call) for ln in text), call)

    def test_mods_only_show_a_self_calls_modifiers(self):
        rows = tree(FIXTURE, mods=True)
        self.assertIn("@deadline 2s", chips(line(rows, "[Crawler]")))


class TestLegend(unittest.TestCase):
    @staticmethod
    def wires_text(**kw) -> str:
        return "".join(t for t, _ in vtree.tree_legend(**kw)[1])

    ALL = frozenset({"↺", "↻", "⇱", "↩"})

    def test_no_call_entries_by_default(self):
        text = self.wires_text(payloads=True)
        for mark in self.ALL:
            self.assertNotIn(mark, text)

    def test_lists_only_the_marks_drawn(self):
        # examples 15-walk draws only `⇱` (a host op, no return)
        text = self.wires_text(calls=frozenset({"⇱"}), payloads=True)
        self.assertIn("⇱ host-provided", text)
        for entry in ("self-call", "recursion", "returns"):
            self.assertNotIn(entry, text)

    def test_each_mark_its_own_entry(self):
        for mark, word in (("↺", "self-call"), ("↻", "recursion"),
                           ("⇱", "host-provided"), ("↩", "returns")):
            text = self.wires_text(calls=frozenset({mark}))
            self.assertIn(f"{mark} {word}", text)
            for other in self.ALL - {mark}:
                self.assertNotIn(other, text)

    def test_all_marks(self):
        text = self.wires_text(calls=self.ALL, payloads=True)
        for entry in ("↺ self-call", "↻ recursion", "⇱ host-provided", "↩ returns"):
            self.assertIn(entry, text)

    def test_entries_pair_marker_and_word(self):
        wires = vtree.tree_legend(calls=self.ALL, payloads=True, mods=True)[1]
        self.assertEqual(len(wires) % 2, 1)             # the label, then pairs

if __name__ == "__main__":
    unittest.main()
