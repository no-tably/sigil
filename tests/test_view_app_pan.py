"""XY pan in the app (view.py): keys and SGR mouse (drag, wheel), the `f` fit
toggle, clamping, home / centre, input split mid-sequence, exact frame sizes.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import view  # noqa: E402

TALL = "".join(f"[N{i}] -> [N{i + 1}]\n" for i in range(30))
WIDE = """\
[Source] -> [Left] : transform(alpha, beta, gamma) => {Intermediate}
[Source] -> [Right] : enrich(delta, epsilon, zeta) => {Enriched}
[Source] -> [Middle] : summarise(eta, theta, iota) => {Summary}
"""                                            # payload chips make it wide
SMALL = "[Alpha] -> [Beta]\n"


def plain(rows):
    return ["".join(t for t, _ in r) for r in rows]


class _Doc(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "doc.sigil"

    def tearDown(self):
        self.tmp.cleanup()

    def state(self, text, **kw):
        self.path.write_text(text)
        st = view.ViewState(self.path, do_lint=False, **kw)
        st.reload(force=True)
        return st


class TestPlacement(unittest.TestCase):
    def test_home_centres_a_fitting_drawing(self):
        self.assertEqual(view.home_origin(4, 10), -3)
        self.assertEqual(view.home_origin(40, 10), 0)

    def test_centre(self):
        self.assertEqual(view.centre_origin(40, 10), 15)
        self.assertEqual(view.centre_origin(4, 10), -3)

    def test_fit_bounds(self):
        self.assertEqual(view.pan_bounds(4, 10, True), (-3, -3))     # pinned centred
        self.assertEqual(view.pan_bounds(40, 10, True), (0, 30))

    def test_free_bounds_keep_part_on_screen(self):
        self.assertEqual(view.pan_bounds(40, 10, False), (-5, 35))   # half the view
        self.assertEqual(view.pan_bounds(3, 10, False), (-7, 0))     # all of it
        self.assertEqual(view.place(40, 10, 999, False, None), 35)
        self.assertEqual(view.place(40, 10, -999, False, None), -5)
        self.assertEqual(view.place(40, 10, 7, False, "home"), 0)

    def test_wheel_steps(self):
        self.assertEqual(view.wheel_step(64), (0, -view.WHEEL_Y))
        self.assertEqual(view.wheel_step(65), (0, view.WHEEL_Y))
        self.assertEqual(view.wheel_step(66), (-view.SCROLL_X, 0))
        self.assertEqual(view.wheel_step(67), (view.SCROLL_X, 0))
        self.assertEqual(view.wheel_step(64 + 4), (-view.SCROLL_X, 0))  # shift+wheel
        self.assertEqual(view.wheel_step(65 + 4), (view.SCROLL_X, 0))


class TestParseInput(unittest.TestCase):
    def test_sgr_mouse_reports(self):
        self.assertEqual(list(view.parse_keys("\x1b[<0;10;5Mj\x1b[<32;12;7M\x1b[<0;12;7m")),
                         [view.Mouse(0, 10, 5, False), "j", view.Mouse(32, 12, 7, False),
                          view.Mouse(0, 12, 7, True)])
        self.assertEqual(list(view.parse_keys("\x1b[<65;1;1M")), [view.Mouse(65, 1, 1, False)])

    def test_unknown_sequences_are_dropped_whole(self):
        self.assertEqual(list(view.parse_keys("\x1b[200~p\x1b[1;5Am")), ["p", "m"])

    def test_keys_unchanged(self):
        self.assertEqual(list(view.parse_keys("\x1b[Ajq\x1b[6~f")), ["up", "j", "quit", "pgdn", "f"])

    def test_split_mid_sequence_waits_for_the_rest(self):
        data, rest = view.split_input("j\x1b[<0;1")
        self.assertEqual((data, rest), ("j", "\x1b[<0;1"))
        data, rest = view.split_input(rest + "0;5m")
        self.assertEqual(rest, "")
        self.assertEqual(list(view.parse_keys(data)), [view.Mouse(0, 10, 5, True)])
        self.assertEqual(view.split_input("ab"), ("ab", ""))
        self.assertEqual(view.split_input("a\x1b"), ("a", "\x1b"))


class TestFitToggle(_Doc):
    def test_f_toggles_and_the_bar_says_which(self):
        st = self.state(SMALL)
        self.assertTrue(st.fit)
        self.assertIn("· fit ·", plain(st.frame(100, 30))[0])
        self.assertTrue(st.key("f"))
        self.assertFalse(st.fit)
        self.assertIn("· pan ·", plain(st.frame(100, 30))[0])
        self.assertIn("f fit", "".join(t for t, _ in view.keys_legend(st)))

    def test_natural_layout_is_not_rearranged(self):
        st = self.state(WIDE, payloads=True)
        fitted = plain(st.frame(40, 60))
        st.key("f")
        natural = plain(st.frame(40, 60))
        self.assertNotEqual(fitted, natural)
        self.assertGreater(st._width, 40)              # the natural drawing overflows
        self.assertEqual(st.sx, 0)                     # kept at home

    def test_frames_exactly_terminal_sized_in_both_modes(self):
        for text in (SMALL, TALL, WIDE):
            for tree in (False, True):
                st = self.state(text, tree=tree)
                for fit in (True, False):
                    st.fit = fit
                    for k in ("down", "right", "up", "left", "c", "g"):
                        st.key(k)
                        for cols, rows in ((40, 10), (80, 24), (30, 5), (200, 60)):
                            frame = st.frame(cols, rows)
                            self.assertEqual(len(frame), rows)
                            self.assertTrue(all(view.row_len(r) <= cols for r in frame),
                                            (text[:8], tree, fit, k, cols, rows))


class TestPan(_Doc):
    def test_free_pan_moves_both_axes_even_when_it_fits(self):
        st = self.state(SMALL)
        st.key("f")
        st.frame(100, 30)
        x0, y0 = st.sx, st.sy
        st.key("right")
        st.key("down")
        st.frame(100, 30)
        self.assertEqual((st.sx, st.sy), (x0 + view.SCROLL_X, y0 + 1))

    def test_fitted_small_drawing_stays_centred(self):
        st = self.state(SMALL)
        st.frame(100, 30)
        x0, y0 = st.sx, st.sy
        st.key("right")
        st.key("down")
        st.frame(100, 30)
        self.assertEqual((st.sx, st.sy), (x0, y0))

    def test_pan_is_clamped_in_both_modes(self):
        for tree in (False, True):
            st = self.state(TALL, tree=tree)
            st.key("f")
            for _ in range(500):
                st.key("down")
                st.key("right")
            frame = plain(st.frame(60, 20))
            self.assertTrue(any(ln.strip() for ln in frame[1:1 + st._vh]))  # still visible
            for _ in range(1000):
                st.key("up")
                st.key("left")
            frame = plain(st.frame(60, 20))
            self.assertTrue(any(ln.strip() for ln in frame[1:1 + st._vh]))

    def test_home_and_centre(self):
        st = self.state(TALL)
        st.key("f")
        st.frame(60, 20)
        self.assertEqual(st.sy, 0)
        self.assertIn("[N0]", "\n".join(plain(st.frame(60, 20))))
        st.key("c")
        st.frame(60, 20)
        self.assertEqual(st.sy, (len(st._rows) - st._vh) // 2)
        st.key("g")
        st.frame(60, 20)
        self.assertEqual(st.sy, 0)

    def test_view_toggle_goes_home(self):
        st = self.state(TALL)
        for _ in range(10):
            st.key("down")
        st.frame(60, 20)
        st.key("t")
        st.frame(60, 20)
        self.assertEqual(st.sy, 0)


class TestMouse(_Doc):
    def test_drag_pans_with_the_pointer(self):
        st = self.state(TALL)
        st.key("f")
        st.frame(60, 20)
        x0, y0 = st.sx, st.sy
        self.assertFalse(st.mouse(view.Mouse(0, 30, 10, False)))     # press
        self.assertTrue(st.mouse(view.Mouse(32, 26, 4, False)))      # drag up-left
        st.frame(60, 20)
        self.assertEqual((st.sx, st.sy), (x0 + 4, y0 + 6))           # drawing follows
        st.mouse(view.Mouse(0, 26, 4, True))                         # release
        self.assertFalse(st.mouse(view.Mouse(32, 1, 1, False)))      # motion: no drag
        self.assertEqual((st.sx, st.sy), (x0 + 4, y0 + 6))

    def test_other_buttons_do_not_drag(self):
        st = self.state(TALL)
        st.frame(60, 20)
        st.mouse(view.Mouse(2, 30, 10, False))
        self.assertFalse(st.mouse(view.Mouse(34, 20, 1, False)))

    def test_wheel_scrolls(self):
        st = self.state(TALL)
        st.frame(60, 20)
        self.assertTrue(st.mouse(view.Mouse(65, 5, 5, False)))
        st.frame(60, 20)
        self.assertEqual(st.sy, view.WHEEL_Y)
        st.key("f")
        x0 = st.sx
        st.mouse(view.Mouse(67, 5, 5, False))
        st.frame(60, 20)
        self.assertEqual(st.sx, x0 + view.SCROLL_X)


if __name__ == "__main__":
    unittest.main()
