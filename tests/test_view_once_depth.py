"""view.py's run view honours --depth: compose_view and sim_focus hand the depth
to view_run.compose_run, so --once --run --depth N (and the live run view, the
pane and pi, which draw through compose_view) fold an expansion's lanes into its
node's lane below depth N."""

from __future__ import annotations

import contextlib
import json
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import view  # noqa: E402
import view_run as vrun  # noqa: E402

SHOP = ROOT / "site" / "examples" / "02-shop.sigil"
WIDTH = 140
ALL = view.kit.ALL_DEPTH


def shop():
    """The shop example's graph (its [Payments] expansion nests [Risk]'s)."""
    return view.kit.render.parse_document(SHOP.read_text())


def run_rows(g, depth: int) -> list[str]:
    """The run view of the happy run that compose_view draws at `depth`, as text."""
    rows, _w = view.compose_view(g, "run", depth=depth, payloads=False, notes="off",
                                 triggers=True, spaced=True, width=WIDTH, access=False,
                                 mods=False, events="land")
    return [view.kit.ansi(r, False) for r in rows]


def lanes_named(rows: list[str], name: str) -> int:
    """How many rows of a run drawing start a lane for `name`."""
    return sum(1 for r in rows if r.strip().startswith(name))


class RunViewDepth(unittest.TestCase):
    def test_compose_view_draws_the_run_at_its_depth(self):
        g = shop()
        for depth in (0, 1, ALL):
            want, _w = vrun.compose_run(g, None, None, WIDTH, "run", chosen=False,
                                        depth=depth)
            self.assertEqual(run_rows(g, depth), [view.kit.ansi(r, False) for r in want],
                             f"depth {depth}")

    def test_a_shallower_depth_folds_nested_lanes(self):
        g = shop()
        deep, one = run_rows(g, ALL), run_rows(g, 1)
        self.assertEqual(lanes_named(deep, "[Risk]"), 1)
        self.assertEqual(lanes_named(one, "[Risk]"), 0)
        self.assertEqual(lanes_named(one, "[Payments]"), 1)
        self.assertLess(len(one), len(deep))

    def test_sim_focus_reads_the_playhead_of_the_run_drawn_at_that_depth(self):
        g = shop()
        player = view.SimPlayer(g, "happy")
        kw = dict(payloads=False, notes="off", triggers=True, spaced=True, width=WIDTH,
                  access=False, mods=False, events="land", trace=player.trace,
                  tick=player.last)
        rows, _w = vrun.compose_run(g, player.trace, player.last, WIDTH, "run",
                                    probe=True, depth=1)
        self.assertEqual(view.sim_focus(g, "run", depth=1, **kw), view.kit.probed_box(rows))

    def test_once_prints_the_folded_run(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            view.once(SHOP, 1, False, False, width=WIDTH, view="run")
        self.assertNotIn("[Risk]", out.getvalue())


def json_lanes(argv: list[str]) -> list[str]:
    """The lane labels `view.py SHOP --run --json <argv>` prints."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        view.main([str(SHOP), "--run", "--json", *argv])
    return [lane["label"] for lane in json.loads(out.getvalue())["lanes"]]


class RunJsonDepth(unittest.TestCase):
    def test_run_json_folds_lanes_at_the_given_depth(self):
        every, zero = json_lanes([]), json_lanes(["--depth", "0"])
        self.assertIn("[Risk]", every)
        self.assertNotIn("[Risk]", zero)
        self.assertNotIn("[Payments]", zero)
        self.assertIn("[Shop]", zero)
        self.assertEqual(json_lanes(["--depth", "all"]), every)


if __name__ == "__main__":
    unittest.main()
