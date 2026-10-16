"""ViewState keeps one depth: `depth` is None until --depth or d gives one, and
whatever sets it is what every view (the run view too) is drawn and told at."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigil.present import app as view, kit  # noqa: E402
SHOP = ROOT / "site" / "examples" / "02-shop.sigil"
ALL = kit.ALL_DEPTH


class OneDepth(unittest.TestCase):
    def state(self, **kw):
        st = view.ViewState(SHOP, do_lint=False, sim="happy", view="run", **kw)
        st.reload()
        st._ensure_player()
        return st

    def test_not_given_is_none(self):
        st = self.state()
        self.assertIsNone(st.depth)
        self.assertFalse(hasattr(st, "depth_given"))
        self.assertEqual(st.drawn_depth, ALL)
        st.key("1")
        self.assertEqual(st.drawn_depth, view.DEFAULT_DEPTH)

    def test_setting_depth_draws_the_run_there(self):
        for d in (0, 1, 2):
            st = self.state()
            st.depth = d
            self.assertEqual(st.drawn_depth, d)
            self.assertEqual(st.player.depth, d)      # told where drawn
            st.key("1")
            self.assertEqual(st.drawn_depth, d)

    def test_setting_depth_back_to_none_is_not_given_again(self):
        st = self.state(depth=0)
        st.depth = None
        self.assertEqual(st.drawn_depth, ALL)
        self.assertIsNone(st.player.depth)

    def test_player_told_at_the_state_depth(self):
        self.assertIsNone(self.state().player.depth)
        st = self.state(depth=0)
        self.assertEqual(st.player.depth, 0)
        st.key("d")
        self.assertEqual((st.depth, st.player.depth), (1, 1))

    def test_drawn_matches_the_module_rule(self):
        for v in view.VIEWS:
            for d in (None, 0, 1, ALL):
                st = self.state(depth=d)
                st.view = v
                self.assertEqual(st.drawn_depth, view.drawn_depth(v, d), (v, d))


if __name__ == "__main__":
    unittest.main()
