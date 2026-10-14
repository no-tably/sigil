"""Tests for view_run.py: a run whose episodes overlap, drawn as a timeline.

Covers:
  - an episode beginning while another runs: its start mark (`ep2`) on the
    ruler at its start tick and no ┆ boundary; one beginning after the run
    went quiet keeps its boundary, as before;
  - a lane busy in two episodes at once on its ∥k sub-row;
  - the episodes' legend under the drawing (only when episodes overlap): each
    begun episode with its entry and start tick, ▸ on the running ones while
    the run plays, wrapped to the width;
  - each entry's note names its own episode, also two begun at one tick;
  - overlaps(): the episodes running when each began; `--run --json` names
    them as an episode's "with".

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


view = _load("sigil_view_run_overlap_tests", "view.py")
vrun, kit, sim = view.vrun, view.kit, view.simulator

SHARED = """#!spec
(Builder) -> [Api] : build
[Api] -> [Worker]
[Worker] -> |Db|
(Author) -> [Api] : export
"""
AUTHOR = "Author_actor"


def _graph(src: str = SHARED):
    return kit._call(kit.render.parse_document, src, None)


def _run(g, starts: tuple):
    canon = sim.canonical(g)
    name = "+".join(f"{n}@{t}" for n, t in starts) or "happy"
    return sim.simulate(canon, sim.Scenario(name, starts=starts))


def _text(g, trace, tick=None, width=None) -> list:
    rows, _w = vrun.compose_run(g, trace, tick, width)
    return ["" if isinstance(r, kit.RuleRow) else "".join(t for t, _s in r) for r in rows]


def _lane(lines: list, label: str) -> str:
    return next(ln for ln in lines if ln[2:].startswith(label))


class OverlapDrawn(unittest.TestCase):
    def setUp(self):
        self.g = _graph()
        self.trace = _run(self.g, ((AUTHOR, 3),))
        self.lines = _text(self.g, self.trace)

    def test_start_mark_on_the_ruler_and_no_boundary(self):
        ruler = next(ln for ln in self.lines if "ep2" in ln)
        author = _lane(self.lines, "(Author)")
        self.assertEqual(ruler.index("ep2"), author.index("█"))   # its start tick's column
        self.assertFalse(any(vrun.EPISODE in ln for ln in self.lines))

    def test_a_lane_busy_in_both_takes_a_sub_row(self):
        at = self.lines.index(_lane(self.lines, "[Api]"))
        self.assertTrue(self.lines[at + 1].strip().startswith(f"{vrun.PAR}2"))

    def test_each_entry_names_its_episode(self):
        self.assertIn("episode 1's entry", _lane(self.lines, "(Builder)"))
        self.assertIn("episode 2's entry", _lane(self.lines, "(Author)"))

    def test_the_legend_names_the_episodes(self):
        self.assertEqual(self.lines[-1],
                         "episodes  ep1 (Builder)@0   ep2 (Author)@3")

    def test_the_legend_marks_the_running_ones(self):
        i = next(i for i, f in enumerate(self.trace.frames) if len(f.episodes) > 1)
        self.assertIn(f"{vrun.RUNNING}ep1 (Builder)", _text(self.g, self.trace, i)[-1])
        self.assertIn(f"{vrun.RUNNING}ep2 (Author)", _text(self.g, self.trace, i)[-1])
        first = _text(self.g, self.trace, 0)[-1]           # before episode 2 begins
        self.assertEqual(first, f"episodes {vrun.RUNNING}ep1 (Builder)@0")

    def test_the_legend_wraps_to_the_width(self):
        lines = _text(self.g, self.trace, width=40)
        self.assertEqual(lines[-2:], ["episodes  ep1 (Builder)@0",
                                      "          ep2 (Author)@3"])

    def test_two_begun_at_one_tick_each_name_their_own(self):
        trace = _run(self.g, ((AUTHOR, 0),))
        lines = _text(self.g, trace)
        k = {e["entry"]: e["episode"] for e in trace.end["episodes"]}
        self.assertEqual(sorted(k.values()), [1, 2])
        self.assertIn(f"episode {k['Builder_actor']}'s entry", _lane(lines, "(Builder)"))
        self.assertIn(f"episode {k[AUTHOR]}'s entry", _lane(lines, "(Author)"))


class OverlapColoured(unittest.TestCase):
    """The run view colours an overlapping episode as the other views colour
    its tokens: kit.episode_colour(k)."""

    def setUp(self):
        self.g = _graph()
        self.trace = _run(self.g, ((AUTHOR, 3),))

    def _runs(self, tick=None) -> list:
        rows, _w = vrun.compose_run(self.g, self.trace, tick, None)
        return [run for r in rows if not isinstance(r, kit.RuleRow) for run in r]

    def test_the_start_mark_takes_its_episode_colour(self):
        mark = next(st for t, st in self._runs() if t == "ep2")
        self.assertEqual(mark[0], kit.episode_colour(2))

    def test_a_start_after_the_run_went_quiet_keeps_the_section_look(self):
        happy = _run(self.g, ())
        rows, _w = vrun.compose_run(self.g, happy, None, None)
        mark = next(st for r in rows if not isinstance(r, kit.RuleRow)
                    for t, st in r if t == "ep2")
        self.assertEqual(mark, kit.SECTION_STYLE)

    def test_legend_items_take_their_episode_colour_bold_while_running(self):
        i = next(i for i, f in enumerate(self.trace.frames) if len(f.episodes) > 1)
        items = {t.lstrip(vrun.RUNNING + " ")[:3]: st for t, st in self._runs(i)
                 if t.lstrip(vrun.RUNNING + " ").startswith("ep") and "@" in t}
        self.assertEqual(items["ep1"], (kit.episode_colour(1), None, True))
        self.assertEqual(items["ep2"], (kit.episode_colour(2), None, True))
        ended = {t.strip()[:3]: st for t, st in self._runs() if "@" in t}
        self.assertEqual(ended["ep2"], (kit.episode_colour(2), None, False))

    def test_past_nine_the_label_names_the_token_mark(self):
        self.assertEqual(vrun._episode_label(2), "ep2")
        self.assertEqual(vrun._episode_label(10), f"ep10={kit.episode_mark(10)}")


class OneAtATime(unittest.TestCase):
    def setUp(self):
        self.g = _graph()

    def test_the_happy_run_keeps_its_boundary_and_no_legend(self):
        lines = _text(self.g, _run(self.g, ()))
        self.assertTrue(any(vrun.EPISODE in ln for ln in lines))
        self.assertFalse(any(ln.startswith("episodes") for ln in lines))

    def test_a_start_after_the_run_went_quiet_keeps_its_boundary(self):
        happy = _run(self.g, ())
        late = _run(self.g, ((AUTHOR, happy.end["episodes"][1]["start"] + 2),))
        self.assertEqual(vrun.overlaps(late), {1: (), 2: ()})
        lines = _text(self.g, late)
        self.assertTrue(any(vrun.EPISODE in ln for ln in lines))
        self.assertFalse(any(ln.startswith("episodes") for ln in lines))


class Overlaps(unittest.TestCase):
    def setUp(self):
        self.g = _graph()

    def test_who_runs_when_each_begins(self):
        self.assertEqual(vrun.overlaps(_run(self.g, ((AUTHOR, 3),))), {1: (), 2: (1,)})
        self.assertEqual(vrun.overlaps(_run(self.g, ())), {1: (), 2: ()})

    def test_json_names_who_an_episode_began_with(self):
        eps = vrun.timeline_json(_run(self.g, ((AUTHOR, 3),)))["episodes"]
        self.assertEqual(eps, [{"episode": 1, "tick": 0, "entry": "(Builder)"},
                               {"episode": 2, "tick": 3, "entry": "(Author)", "with": [1]}])
        happy = vrun.timeline_json(_run(self.g, ()))["episodes"]
        self.assertFalse(any("with" in e for e in happy))


if __name__ == "__main__":
    unittest.main()
