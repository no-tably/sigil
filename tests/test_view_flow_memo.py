"""Tests for the flow view's frame memo (compose_flow's `memo`, kit.FrameMemo).

Covers:
  - the wrap ladder's step and each part's cut follow the frames' layout: a
    run whose frames lay out unlike each other (badges not padded to one
    width) draws with the memo what it draws without it, frame by frame, at
    widths where the step or the cuts differ between frames;
  - the padded run (as drawn) still draws with the memo what it draws
    without it, and its extent holds still (the plan is kept);
  - a width change during a run (the same memo, widths taken in turn) draws
    each frame as it is drawn afresh;
  - a padded run whose badge slot is blank on one frame and marked on
    another (the same width) takes another step on each — the bottom-right
    chip panel fits only in blank cells — and draws with the memo what it
    draws without it, frame by frame, forward and back;
  - _extent: what of a frame the layout depends on — equal for two frames of
    a run, unequal when a badge's width differs; () without a frame;
    _blanks: equal widths, unequal blank cells;
  - the blank cells are looked at only on a frame whose held step is past
    the first (natural): a run that fits draws each frame without them;
  - a frame whose badges are blank where an earlier frame's were starts at
    the step that frame took (one step painted), and one with blank cells
    not met yet starts past the first step: over every frame of the
    executions fixture's happy run only the first frame of each blank-cell
    pattern paints more than one step (each frame as drawn without the memo).

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


vflow = _load("sigil_view_flow_memo_tests", "view_flow.py")
sim = _load("sigil_sim_view_flow_memo_tests", "sim.py")
kit, scene, vgraph = vflow.kit, vflow.scene, vflow.vgraph

OPTIONS = dict(depth=1, payloads=True, notes="markers", triggers=True, access=False,
               mods=True, events="land")
# (document, scenario, widths, ticks): runs whose unpadded frames take another
# step or cut at these widths than their first frame does.
CASES = (
    ("site/examples/02-shop.sigil", "happy", (37, 44, 93), (0, 56, 64, 1)),
    ("site/examples/00-shortener.sigil", "Redirect.lookup:fails", (44,), (0, 27, 30, 1)),
    ("site/examples/01-checkout.sigil", "happy", (100,), (0, 9, 14, 21, 1)),
)


def run(path: str, name: str):
    """(graph, trace) — the trace named as the flow draws it (OPTIONS)."""
    g = kit.render.parse_document((_DIR / path).read_text())
    scn = scene.build_scene(g, events=OPTIONS["events"], triggers=OPTIONS["triggers"],
                            access=OPTIONS["access"], depth=OPTIONS["depth"])
    return g, sim.project(sim.simulate(scn, sim.scenario(scn, name)), scn)


def draw(g, trace, tick: int, width, memo=None):
    return vflow.compose_flow(g, width=width, trace=trace, tick=tick, memo=memo, **OPTIONS)


def unpadded():
    """Badges as wide as each frame's own (no slots): frames lay out unlike."""
    return mock.patch.object(vgraph, "_trace_slots", lambda trace: {})


def look(g, trace, tick: int):
    scn = scene.build_scene(g, events=OPTIONS["events"], triggers=OPTIONS["triggers"],
                            access=OPTIONS["access"], depth=OPTIONS["depth"])
    return vgraph.sim_look(scn, trace.frames[tick], vgraph._trace_slots(trace))


class TestLayoutFollowed(unittest.TestCase):

    def test_frames_that_lay_out_unlike(self):
        with unpadded():
            for path, name, widths, ticks in CASES:
                g, trace = run(path, name)
                for width in widths:
                    memo = kit.FrameMemo()
                    for t in ticks:
                        with self.subTest(doc=path, width=width, tick=t):
                            self.assertEqual(draw(g, trace, t, width, memo),
                                             draw(g, trace, t, width))

    def test_frames_differ_in_layout(self):
        """(The cases above are such: some frame's extent differs from the first's.)"""
        with unpadded():
            for path, name, _widths, ticks in CASES:
                g, trace = run(path, name)
                with self.subTest(doc=path):
                    self.assertGreater(
                        len({vflow._extent(look(g, trace, t)) for t in ticks}), 1)

    def test_padded_run(self):
        path, name, widths, ticks = CASES[0]
        g, trace = run(path, name)
        self.assertEqual(len({vflow._extent(look(g, trace, t)) for t in ticks}), 1)
        for width in (None,) + widths:
            memo = kit.FrameMemo()
            for t in ticks:
                with self.subTest(width=width, tick=t):
                    self.assertEqual(draw(g, trace, t, width, memo), draw(g, trace, t, width))

    def test_width_changes_during_a_run(self):
        path, name, widths, ticks = CASES[0]
        g, trace = run(path, name)
        memo = kit.FrameMemo()
        with unpadded():
            for i, t in enumerate(ticks + ticks):
                width = (None,) + widths
                width = width[i % len(width)]
                with self.subTest(width=width, tick=t):
                    self.assertEqual(draw(g, trace, t, width, memo), draw(g, trace, t, width))

    def test_extent_without_a_frame(self):
        self.assertEqual(vflow._extent(None), ())
        self.assertEqual(vflow._blanks(None), ())


class TestBlankCellsFollowed(unittest.TestCase):
    """The shortener's failing lookup at 72 columns: frame 1 (|Links| badge
    blank) fits the chips' letters with their panel; frame 25 (|Links| ✕)
    does not and hangs them."""

    def setUp(self):
        self.g, self.trace = run("site/examples/00-shortener.sigil", "Redirect.lookup:fails")

    def test_steps_differ(self):
        self.assertNotEqual(draw(self.g, self.trace, 1, 72)[0],
                            draw(self.g, self.trace, 25, 72)[0])
        one, late = look(self.g, self.trace, 1), look(self.g, self.trace, 25)
        self.assertEqual(vflow._extent(one), vflow._extent(late))
        self.assertNotEqual(vflow._blanks(one), vflow._blanks(late))

    def test_forward_and_back(self):
        memo = kit.FrameMemo()
        for t in (0, 1, 25, 1, 25, 31, 1):
            with self.subTest(tick=t):
                self.assertEqual(draw(self.g, self.trace, t, 72, memo),
                                 draw(self.g, self.trace, t, 72))

    def test_blanks_only_past_the_first_step(self):
        """Frames held at the natural step never work out _blanks; frames
        held at a later step do (the step stands only on the same blanks)."""
        for width, looked in ((None, False), (72, True)):
            memo = kit.FrameMemo()
            draw(self.g, self.trace, 25, width, memo)
            with self.subTest(width=width), \
                    mock.patch.object(vflow, "_blanks", wraps=vflow._blanks) as blanks:
                self.assertEqual(draw(self.g, self.trace, 26, width, memo),
                                 draw(self.g, self.trace, 26, width))
                self.assertEqual(blanks.called, looked)



def painted(g, trace, ticks, width, memo, check=lambda t: True):
    """For each tick, (tick, the wrap steps drawn — _part_rows calls — with
    `memo`, whether the frame is as drawn without one: None when check(tick)
    is false)."""
    real, counts = vflow._part_rows, []

    def counting(*args, **kw):
        counts[-1] += 1
        return real(*args, **kw)

    out = []
    for t in ticks:
        counts.append(0)
        with mock.patch.object(vflow, "_part_rows", counting):
            got = draw(g, trace, t, width, memo)
        out.append((t, counts[-1], got == draw(g, trace, t, width) if check(t) else None))
    return out


class TestStepsKeptByBlankCells(unittest.TestCase):

    def test_shortener_back_and_forth(self):
        """Frames 1 (letters) and 25 (hung) in turn at 72 columns: each paints
        one step once its blank cells were met."""
        g, trace = run("site/examples/00-shortener.sigil", "Redirect.lookup:fails")
        got = painted(g, trace, (1, 25, 1, 25, 1), 72, kit.FrameMemo())
        self.assertTrue(all(same for _t, _n, same in got))
        self.assertEqual([n for _t, n, _same in got[2:]], [1, 1, 1])

    def test_executions_run(self):
        """Every frame of the happy run, narrow (every frame hung) and wide
        (letters on some frames): a frame paints more than one step only on
        the first frame or the first with its blank cells. (Every 8th frame
        checked against its drawing without the memo, to keep the test quick.)"""
        g, trace = run("tests/fixtures/executions.sigil", "happy")
        scn = scene.build_scene(g, events=OPTIONS["events"], triggers=OPTIONS["triggers"],
                                access=OPTIONS["access"], depth=OPTIONS["depth"])
        ticks, slots = range(len(trace.frames)), vgraph._trace_slots(trace)
        for width in (60, 200):
            with self.subTest(width=width):
                got = painted(g, trace, ticks, width, kit.FrameMemo(), lambda t: t % 8 == 0)
                self.assertTrue(all(same is not False for _t, _n, same in got))
                met, firsts = set(), set()
                for t in ticks:
                    blanks = vflow._blanks(vgraph.sim_look(scn, trace.frames[t], slots))
                    if blanks not in met:
                        met.add(blanks)
                        firsts.add(t)
                again = [t for t, n, _same in got if n > 1 and t not in firsts | {0}]
                self.assertEqual(again, [])
                self.assertLess(sum(n > 1 for _t, n, _same in got), len(firsts) + 1)
                self.assertLess(len(firsts), len(ticks) // 4)


if __name__ == "__main__":
    unittest.main()
