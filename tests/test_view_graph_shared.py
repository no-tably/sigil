"""Tests for view_graph.py's fan-outs: the cells their wires share, and a
wrapped fan-out's join bar.

Covers:
  1. one look rule for a fan-out's shared cells, wrapped or not, with or
     without a run — the most severe member wins (share_rank): with no run an
     error wire (`!>`) reads in its colour from under its source, not only
     near its head, while each member's own head keeps its colour; under a
     run the failed member's look takes the stem of a natural (unwrapped)
     fan-out; a FrameMemo repaint draws it as a fresh drawing does;
  2. share_rank: run state first, then an error wire over the rest;
  3. a wrapped joined fan-out's bar takes a port per branch on its first row
     and one for the trunk to the rows below, not one per branch;
  4. no run and no `!>`: the rule leaves the drawing alone — a fan-out's
     shared stem crossing another wire's channel does not take the crossing
     cell (the coverage fixture's <OrderPlaced> broadcast over the produce
     wires).

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


view = _load("sigil_view_graph_shared", ROOT / "view.py")
vgraph, kit = view.vgraph, view.kit
scene = vgraph.scene
sim = vgraph._sibling("sigil_sim", "sim.py")

# [Api]'s `!>` runs two layers down, its siblings one: without the rule the
# stem under [Api] belongs to a sibling (nearest its head) and the error wire
# reads red only from the channel on.
ERROR_FAN = "\n".join(["#!spec", "[Api] -> [Store]", "[Store] -> [Disk]",
                       "[Api] !> [Alarm]", "[Disk] -> [Alarm]", "[Api] -> [Cache]"]) + "\n"
# The run fails [Gamma]'s call: the failed path runs [Hub] → [Alpha] →
# [Gamma]; nearest its head, [Beta] (or the long [Hub] → [Gamma]) would own
# the stem under [Hub].
RUN_FAN = "\n".join(["[Hub] -> [Alpha]", "[Alpha] -> [Gamma]", "[Hub] -> [Gamma]",
                     "[Hub] -> [Beta]", "[Gamma] -> |Db| : put => {R}",
                     "  !> <Oops>"]) + "\n"
# <Tick>'s fan-out stem (shared by its two wires) crosses [Cfg]'s fan-out
# channel (┼): every member is as severe as the next, so the crossing keeps
# the channel's look, as the coverage fixture's <OrderPlaced> broadcast does
# over the produce wires.
CROSSED_FAN = "\n".join(["[Gateway] -> [Api]", "[Api] <-> [Cache]", "<Stop> -> ~|Counter|",
                          "[Cfg] -> ~|Opts|", "[Cfg] -> ~|Limits|", "[Cfg] -> ~|Ratio|",
                          "[Cfg] -> ~|Last|", "<Tick> -> ~|History|", "<Tick> -> ~|Total|",
                          "[Api] -> [Shard]", "[Api] -> [Replica]"]) + "\n"
TARGETS = [f"[Service{k:02d}]" for k in range(14)]
JOINED = "[Hub] -> " + " & ".join(TARGETS) + "\n"


def _grid(rows) -> dict:
    """{(x, y): (char, style)} of the drawn cells (one column each: ASCII names)."""
    out = {}
    for y, row in enumerate(rows):
        x = 0
        for text, style in row:
            for k, c in enumerate(text):
                out[(x + k, y)] = (c, style)
            x += len(text)
    return out


def _row_of(rows, needle: str) -> int:
    return next(y for y, r in enumerate(rows) if needle in kit.ansi(r, False))


def _stem(rows) -> tuple:
    """The (char, style) of the cell under the top box's bottom border, on its
    centre column."""
    grid = _grid(rows)
    y = next(y for y, r in enumerate(rows) if "└" in kit.ansi(r, False))
    xs = [x for (x, yy) in grid if yy == y + 1 and grid[(x, yy)][0] != " "]
    return grid[(xs[0], y + 1)]


class ErrorWireNoRun(unittest.TestCase):
    """1. no run: the error wire reads red from under its source."""

    def setUp(self):
        self.rows, _w = vgraph.compose(kit.render.parse_document(ERROR_FAN), 1, False)
        self.fail = scene.colour_of("edges-fail")

    def test_stem_takes_the_error_colour(self):
        ch, style = _stem(self.rows)
        self.assertEqual(ch, "│")
        self.assertEqual(style[0], self.fail)

    def test_siblings_heads_keep_their_colour(self):
        grid, y = _grid(self.rows), _row_of(self.rows, "[Store]") - 2
        heads = [st for (x, yy), (c, st) in grid.items() if yy == y and c == "▼"]
        self.assertEqual(len(heads), 2)
        self.assertTrue(all(st[0] != self.fail for st in heads), heads)

    def test_same_kind_fan_out_is_untouched(self):
        """Members as severe as each other keep the nearest-owner look."""
        text = "[Api] -> [Store]\n[Store] -> [Disk]\n[Api] -> [Disk]\n[Api] -> [Cache]\n"
        rows, _w = vgraph.compose(kit.render.parse_document(text), 1, False)
        styles = {st for _c, st in _grid(rows).values() if st and _c in "│─┼┬┴┐┌└┘▼"}
        self.assertNotIn(scene.colour_of("edges-fail"), {st[0] for st in styles})


class RunNatural(unittest.TestCase):
    """1. under a run, an unwrapped fan-out's stem takes its most severe member."""

    def setUp(self):
        self.g = kit.render.parse_document(RUN_FAN)
        canon = sim.canonical(self.g)
        scn = scene.build_scene(self.g, events="nodes", triggers=True, depth=kit.ALL_DEPTH)
        self.trace = sim.project(sim.simulate(canon, sim.scenario(canon, "Gamma->Db:fails")), scn)
        self.args = (self.g, kit.ALL_DEPTH, False, "off", True, None, False, False, "nodes")

    def compose(self, i, memo=None):
        rows, _w = vgraph.compose(*self.args, trace=self.trace, tick=i, memo=memo)
        return rows

    def test_failed_member_takes_the_stem(self):
        rows = self.compose(len(self.trace.frames) - 1)
        _ch, style = _stem(rows)
        self.assertEqual(style[0], scene.colour_of("edges-fail"))

    def test_memo_repaints_the_stem(self):
        memo, last = kit.FrameMemo(), len(self.trace.frames) - 1
        for i in list(range(last + 1)) + [0, last, 1]:
            self.assertEqual(self.compose(i, memo), self.compose(i), i)


class ShareRank(unittest.TestCase):
    """2. the order members are weighed in."""

    def test_order(self):
        r = vgraph.share_rank
        self.assertGreater(r("!>"), r("->"))
        self.assertEqual(r("->"), r("~>"))
        self.assertGreater(r("->", "active"), r("!>", "trail"))
        self.assertGreater(r("->", "failed"), r("!>", "active"))
        self.assertGreater(r("!>", "inactive"), r("->", "inactive"))
        self.assertGreater(r("->", "inactive"), r("!>"))


class WrappedJoinBar(unittest.TestCase):
    """3. a wrapped joined fan-out's bar spans its first row's branches and the trunk."""

    def test_bar_ports(self):
        rows, w = vgraph.compose(kit.render.parse_document(JOINED), 1, False, width=80)
        text = [kit.ansi(r, False) for r in rows]
        bar = next(t for t in text if "━" in t)
        first = next(t for t in text if any(s in t for s in TARGETS))
        branches = sum(s in first for s in TARGETS)
        self.assertLess(branches, len(TARGETS), "the fixture must wrap")
        ports = sum(bar.count(c) for c in "┯┿")
        self.assertEqual(ports, branches + 1, "\n".join(text))
        span = bar.strip().split(" ")[0]
        self.assertEqual(len(span), 2 * ports + 1, bar)

    def test_natural_bar_keeps_a_port_per_branch(self):
        rows, _w = vgraph.compose(kit.render.parse_document(JOINED), 1, False)
        bar = next(kit.ansi(r, False) for r in rows if "━" in kit.ansi(r, False))
        self.assertEqual(len(bar.strip().split(" ")[0]), 2 * len(TARGETS) + 1)


class CrossedFanNoRun(unittest.TestCase):
    """4. no run, no `!>`: a crossing in a fan-out's channel keeps its owner."""

    def compose(self):
        rows, _w = vgraph.compose(kit.render.parse_document(CROSSED_FAN), 1, False,
                                  width=100)
        return rows

    def test_crossing_keeps_the_channel_look(self):
        grid = _grid(self.compose())
        crossings = [(x, y) for (x, y), (c, _st) in grid.items() if c == "┼"
                     and grid.get((x - 1, y), ("",))[0] == "─"
                     and grid.get((x, y - 1), ("",))[0] == "│"
                     and grid[(x - 1, y)][1] != grid[(x, y - 1)][1]]
        self.assertTrue(crossings, "the fixture must cross two wires of different looks")
        for x, y in crossings:
            self.assertEqual(grid[(x, y)][1], grid[(x - 1, y)][1], (x, y))

    def test_rule_changes_nothing(self):
        real = vgraph._fan_out_looks
        try:
            vgraph._fan_out_looks = lambda *a: {}
            plain = self.compose()
        finally:
            vgraph._fan_out_looks = real
        self.assertEqual(_grid(self.compose()), _grid(plain))


if __name__ == "__main__":
    unittest.main()
