"""--depth not given: the run view (drawn, --once, live) shows every level, as
--run --json does, and a run is told naming every node; graph, tree and flow
are drawn to DEFAULT_DEPTH. Given, every view and the telling honour it."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import view  # noqa: E402

SHOP = ROOT / "site" / "examples" / "02-shop.sigil"
ALL = view.kit.ALL_DEPTH
NESTED = "[Risk]"                       # a lane two expansions deep in the shop


def printed(argv: list[str]) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        status = view.main([str(SHOP), *argv])
    assert status == 0, status
    return out.getvalue()


def drawn_lanes(argv: list[str]) -> list[str]:
    """The lane names `--once --run <argv>` draws (each lane row's first word: a
    node, which opens with its glyph's bracket)."""
    text = printed(["--once", "--run", "--no-lint", "--width", "160", *argv])
    rows = text[:text.index("\nrun ")].splitlines()[1:]      # below the title rule
    return [r.split()[0] for r in rows if r.strip() and r.split()[0][0] in "[({<|"]


def json_lanes(argv: list[str]) -> list[str]:
    return [lane["label"] for lane in json.loads(printed(["--run", "--json", *argv]))["lanes"]]


class DrawnDepth(unittest.TestCase):
    def test_given_wins_in_every_view(self):
        for v in view.VIEWS:
            self.assertEqual(view.drawn_depth(v, 0), 0)

    def test_not_given_run_every_level_others_the_default(self):
        self.assertEqual(view.drawn_depth("run", None), ALL)
        for v in ("graph", "tree", "flow"):
            self.assertEqual(view.drawn_depth(v, None), view.DEFAULT_DEPTH)


class OnceRunMatchesJson(unittest.TestCase):
    def test_same_lanes_for_the_same_flags(self):
        for argv in ([], ["--depth", "0"], ["--depth", "1"], ["--depth", "all"],
                     ["--sim", "Risk?>Review"]):
            with self.subTest(argv=argv):
                self.assertEqual(drawn_lanes(argv), json_lanes(argv))

    def test_no_depth_draws_the_nested_lanes(self):
        self.assertIn(NESTED, drawn_lanes([]))
        self.assertNotIn(NESTED, drawn_lanes(["--depth", "1"]))


class OnceTellsEveryNodeByDefault(unittest.TestCase):
    def test_narration_without_depth_names_nested_nodes(self):
        out = printed(["--once", "--sim", "happy", "--width", "160", "--no-lint"])
        self.assertIn(NESTED, out[out.index("sim happy"):])

    def test_graph_still_drawn_to_the_default_depth(self):
        plain = printed(["--once", "--no-lint", "--width", "160"])
        one = printed(["--once", "--no-lint", "--width", "160", "--depth", "1"])
        self.assertEqual(plain, one)


class LiveRunView(unittest.TestCase):
    def state(self, **kw):
        st = view.ViewState(SHOP, do_lint=False, sim="happy", **kw)
        st.reload()
        st._ensure_player()
        return st

    def test_not_given_run_every_level_graph_default_told_every_node(self):
        st = self.state(view="run")
        self.assertEqual(st.drawn_depth, ALL)
        self.assertIsNone(st.player.depth)
        st.key("1")
        self.assertEqual(st.drawn_depth, view.DEFAULT_DEPTH)

    def test_given_depth_draws_the_run_there(self):
        st = self.state(view="run", depth=1)
        self.assertEqual(st.drawn_depth, 1)
        self.assertEqual(st.player.depth, 1)

    def test_d_gives_a_depth_from_the_one_drawn(self):
        st = self.state(view="run")
        st.key("d")                                    # every level → the first
        self.assertEqual((st.drawn_depth, st.player.depth), (0, 0))
        st.key("4")
        self.assertEqual(st.drawn_depth, 0)


if __name__ == "__main__":
    unittest.main()
