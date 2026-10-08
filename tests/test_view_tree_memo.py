"""Tests for the tree view's frame memo (compose_tree's `memo`, kit.FrameMemo).

Covers:
  - the wrap ladder's step and the outline follow the frames' layout: a run
    whose frames lay out unlike each other (badges not padded to one width)
    draws with the memo what it draws without it, frame by frame, at widths
    where the ladder takes different steps;
  - a width change during a run (the same memo, widths taken in turn) draws
    each frame as it is drawn afresh;
  - _extent: what of a frame the layout depends on — equal for two frames of
    a run (the layout holds still), unequal when a badge's width differs.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

_DIR = Path(__file__).resolve().parents[1]


def _load(name: str, fname: str):
    spec = importlib.util.spec_from_file_location(name, _DIR / fname)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


vtree = _load("sigil_view_tree_memo_tests", "view_tree.py")
sim = _load("sigil_sim_view_tree_memo_tests", "sim.py")
kit, scene = vtree.kit, vtree.scene

EXECUTIONS = (_DIR / "tests" / "fixtures" / "executions.sigil").read_text()
OPTIONS = dict(depth=1, triggers=True, spaced=True, notes="markers", payloads=True,
               access=False, mods=True, events="land")


def run(text: str, name: str = "happy"):
    """(graph, trace) — the trace named as the tree draws it (OPTIONS)."""
    g = kit.render.parse_document(text)
    scn = scene.build_scene(g, events=OPTIONS["events"], triggers=OPTIONS["triggers"],
                            access=OPTIONS["access"], depth=OPTIONS["depth"])
    return g, sim.project(sim.simulate(scn, sim.scenario(scn, name)), scn)


def draw(g, trace, tick: int, width, memo=None):
    return vtree.compose_tree(g, width=width, trace=trace, tick=tick, memo=memo, **OPTIONS)


def unpadded(runs, _width):
    """_padded that pads nothing: each frame's badges as wide as they are."""
    return runs


class TestLayoutFollowed(unittest.TestCase):

    def setUp(self):
        self.g, self.trace = run(EXECUTIONS)
        last = len(self.trace.frames) - 1
        self.ticks = list(range(0, last, 6)) + [last, 3]      # forward, then back

    def widths(self) -> list:
        """The natural width, and widths that take each step of the ladder."""
        natural = draw(self.g, self.trace, 0, None)[1]
        return [None, natural - 4, 60, 24]

    def test_frames_that_lay_out_unlike(self):
        with mock.patch.object(vtree, "_padded", unpadded):
            for width in self.widths():
                memo = kit.FrameMemo()
                for t in self.ticks:
                    with self.subTest(width=width, tick=t):
                        self.assertEqual(draw(self.g, self.trace, t, width, memo),
                                         draw(self.g, self.trace, t, width))

    def test_frames_differ_in_layout(self):
        """(The case above is one: some frame's extent differs from the first's.)"""
        with mock.patch.object(vtree, "_padded", unpadded):
            looks = [vtree._extent(self.look(t)) for t in self.ticks]
        self.assertGreater(len(set(looks)), 1)

    def test_extent_holds_still(self):
        looks = {vtree._extent(self.look(t)) for t in self.ticks}
        self.assertEqual(len(looks), 1)

    def test_width_changes_during_a_run(self):
        memo = kit.FrameMemo()
        widths = self.widths()
        for t in self.ticks:
            width = widths[t % len(widths)]
            with self.subTest(width=width, tick=t):
                self.assertEqual(draw(self.g, self.trace, t, width, memo),
                                 draw(self.g, self.trace, t, width))

    def look(self, tick: int):
        """compose_tree's _TreeLook of frame `tick` (as it builds it)."""
        setup = vtree._tree_setup(self.g, OPTIONS["depth"], OPTIONS["triggers"],
                                  OPTIONS["spaced"], OPTIONS["notes"], OPTIONS["payloads"],
                                  OPTIONS["access"], OPTIONS["mods"], OPTIONS["events"], None)
        frame = self.trace.frames[tick]
        return vtree._TreeLook(
            frame, False, vtree._call_marks(setup.scn, setup.rows, setup.calls, frame),
            vtree._sim_rows(vtree._sim_stage(setup.scn, setup.rows, self.trace),
                            setup.rows, frame),
            vtree._self_call_chips(setup.calls, True, True, frame))


if __name__ == "__main__":
    unittest.main()
