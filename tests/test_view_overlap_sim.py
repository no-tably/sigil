"""Tests for the graph, tree and flow views drawing a run whose episodes overlap.

While more than one episode runs (sim.Frame.episodes), each token moving or
returning is drawn as its episode's number, one cell, in that episode's colour
from the run palette (theme section `run`); a failed or cancelled token keeps
its ✕ / ⊘. With one episode running nothing changes (the goldens hold every
existing drawing).

Covers:
  1. kit.episode_glyph / episode_mark / episode_colour: the rule, the marks past
     9, the palette taken in turn, its colours' theme roles (run-episode-k), the
     sigil theme naming each of them;
  2. graph (sim_look), tree and flow: an overlap frame's tokens drawn as 1 and 2
     in their episodes' colours, on the cells the frame drew ● on with one
     episode running — no other cell differs;
  3. a frame where one episode runs (before the second starts, after the first
     ends) draws its tokens as ever;
  4. kit.FrameMemo: every frame of an overlap run drawn with a memo is the frame
     drawn without one, in each view, stepping into and out of the overlap.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


from sigil.present import app as view, kit, themes  # noqa: E402
from sigil.present.views import graph as vgraph  # noqa: E402
from sigil.model import scene, sim  # noqa: E402
from sigil.core.parse import parse_document  # noqa: E402

DOC = "[A] -> [S] : a()\n[S] -> [T] : t()\n[B] -> [S] : b()\n"
VIEWS = ("graph", "tree", "flow")


def kwargs(v: str, width=None) -> dict:
    return dict(depth=1, payloads=False, notes="off", triggers=True, spaced=True, width=width,
                access=False, mods=False, events=view.DEFAULT_EVENTS[v])


def overlap_run(g, kw: dict, start: int = 2):
    """B started at tick `start` while A's episode runs, named as a view drawn
    with kw names things."""
    canon = sim.canonical(g)
    trace = sim.simulate(canon, sim.Scenario(f"B@{start}", starts=(("B_service", start),)))
    opts = scene.SceneOptions(kw["events"], kw["triggers"], kw["access"], kw["depth"])
    return sim.project(trace, scene.build_scene(g, **opts._asdict()))


def squashed(trace, i: int):
    """trace with frame i told that only its latest episode runs."""
    frames = list(trace.frames)
    frames[i] = frames[i]._replace(episodes=frozenset({frames[i].episode}))
    return trace._replace(frames=tuple(frames))


def cells(rows) -> dict:
    """{(x, y): (char, style)} of every non-blank cell."""
    out = {}
    for y, row in enumerate(rows):
        x = 0
        for text, style in row:
            for ch in text:
                if ch != " ":
                    out[x, y] = (ch, style)
                x += 1
    return out


class EpisodeGlyph(unittest.TestCase):
    """1. the rule, the marks and the palette."""

    def tok(self, state="moving", episode=2):
        return sim.Token(("a", "b", "->"), 0.5, "out", 1, state, episode=episode)

    def test_one_episode_leaves_the_token_as_it_is(self):
        style = ("#123456", None, True)
        self.assertEqual(kit.episode_glyph(self.tok(), "●", style, False), ("●", style))

    def test_overlap_numbers_the_token_in_its_episode_colour(self):
        mark, (fg, bg, bold) = kit.episode_glyph(self.tok(), "●", ("#123456", None, True), True)
        self.assertEqual((mark, bg, bold), ("2", None, True))
        self.assertEqual(fg, kit.episode_colour(2))
        self.assertEqual(fg.role, "run-episode-2")
        _m, (_fg, _bg, bold) = kit.episode_glyph(self.tok("fallback"), "○",
                                                 ("#123456", None, False), True)
        self.assertFalse(bold)                  # bold as it was

    def test_failed_and_cancelled_keep_their_marks(self):
        style = ("#ff0000", None, True)
        for state, mark in (("failed", "✕"), ("cancelled", "⊘")):
            self.assertEqual(kit.episode_glyph(self.tok(state), mark, style, True), (mark, style))

    def test_marks_are_one_cell(self):
        self.assertEqual([kit.episode_mark(k) for k in (1, 9, 10, 35, 36)],
                         ["1", "9", "a", "z", "+"])
        for k in range(1, 40):
            self.assertEqual(kit.cell_width(kit.episode_mark(k)), 1)

    def test_palette_in_turn_from_the_theme(self):
        n = len(kit.EPISODE_COLORS)
        self.assertEqual(kit.episode_colour(1), kit.episode_colour(n + 1))
        self.assertEqual(len({kit.episode_colour(k) for k in range(1, n + 1)}), n)
        run = themes.load("sigil")["run"]
        self.assertEqual(set(run), set(kit._BUILTIN_THEME["run"]))
        for k in range(1, n + 1):
            self.assertEqual(kit.episode_colour(k), run[f"episode_{k}"])


class OverlapTokens(unittest.TestCase):
    """2, 3. the views number an overlap frame's tokens, and only those cells."""

    def setUp(self):
        self.g = parse_document(DOC)

    def overlap_frame(self, trace) -> int:
        return next(i for i, f in enumerate(trace.frames)
                    if len(f.episodes) > 1 and {t.episode for t in f.tokens} == {1, 2})

    def test_graph_sim_look(self):
        kw = kwargs("graph")
        trace = overlap_run(self.g, kw)
        scn = trace.scene
        i = self.overlap_frame(trace)
        look = vgraph.sim_look(scn, trace.frames[i])
        by_task = {t.task: t.episode for t in trace.frames[i].tokens}
        self.assertEqual(sorted(t.mark for t in look.tokens), sorted(str(e) for e in by_task.values()))
        for t in look.tokens:
            self.assertEqual(t.style[0].role, f"run-episode-{t.mark}")
        one = vgraph.sim_look(scn, squashed(trace, i).frames[i])
        self.assertEqual({t.mark for t in one.tokens}, {"●"})

    def test_each_view_numbers_only_the_token_cells(self):
        for v in VIEWS:
            with self.subTest(view=v):
                kw = kwargs(v)
                trace = overlap_run(self.g, kw)
                i = self.overlap_frame(trace)
                two, _w = view.compose_view(self.g, v, trace=trace, tick=i, **kw)
                one, _w = view.compose_view(self.g, v, trace=squashed(trace, i), tick=i, **kw)
                a, b = cells(two), cells(one)
                self.assertEqual(a.keys(), b.keys())
                diff = {xy for xy in a if a[xy] != b[xy]}
                self.assertEqual(sorted(a[xy][0] for xy in diff), ["1", "2"])
                for xy in diff:
                    self.assertEqual(b[xy][0], "●")
                    self.assertEqual(a[xy][1][0].role, f"run-episode-{a[xy][0]}")

    def test_one_episode_running_draws_tokens_as_ever(self):
        for v in VIEWS:
            kw = kwargs(v)
            trace = overlap_run(self.g, kw)
            for i, f in enumerate(trace.frames):
                if len(f.episodes) == 1 and f.tokens:
                    with self.subTest(view=v, tick=i):
                        rows, _w = view.compose_view(self.g, v, trace=trace, tick=i, **kw)
                        marks = {ch for ch, _s in cells(rows).values()}
                        self.assertFalse(marks & {"1", "2"})


class OverlapMemo(unittest.TestCase):
    """4. FrameMemo: an overlap run drawn with a memo is the run drawn without."""

    def test_every_frame_with_and_without(self):
        g = parse_document(DOC)
        for v in VIEWS:
            for width in (None, 24):
                kw = kwargs(v, width)
                trace = overlap_run(g, kw)
                memo = kit.FrameMemo()
                last = len(trace.frames) - 1
                for t in list(range(last + 1)) + list(range(last, -1, -2)):
                    with self.subTest(view=v, width=width, tick=t):
                        self.assertEqual(
                            view.compose_view(g, v, trace=trace, tick=t, memo=memo, **kw),
                            view.compose_view(g, v, trace=trace, tick=t, **kw))
                        self.assertEqual(
                            view.sim_focus(g, v, trace=trace, tick=t, memo=memo, **kw),
                            view.sim_focus(g, v, trace=trace, tick=t, **kw))


if __name__ == "__main__":
    unittest.main()
