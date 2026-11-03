"""K1: the kit's generic parts stand on cure and draw exactly as before.

The stroke glyphs, direction bits and ranks come from cure's junctions and
charset; muted / faded / tints from cure's derive maths; the frame plans and
dirty rows from cure's Memo. These tests hold each against sigil's own tables
and formulas as they were (0.6.12), so a cure re-sync that moves any of them
fails here before a golden does.
"""

import colorsys
import unittest

from sigil.present import kit

U, R, D, L = 1, 2, 4, 8
_LIGHT = {0: " ", U: "│", D: "│", U | D: "│", L: "─", R: "─", L | R: "─",
          D | R: "┌", D | L: "┐", U | R: "└", U | L: "┘",
          U | D | R: "├", U | D | L: "┤", L | R | D: "┬", L | R | U: "┴",
          U | D | L | R: "┼"}
_HEAVY = {0: " ", U: "┃", D: "┃", U | D: "┃", L: "━", R: "━", L | R: "━",
          D | R: "┏", D | L: "┓", U | R: "┗", U | L: "┛",
          U | D | R: "┣", U | D | L: "┫", L | R | D: "┳", L | R | U: "┻",
          U | D | L | R: "╋"}
_DOUBLE = {0: " ", U: "║", D: "║", U | D: "║", L: "═", R: "═", L | R: "═",
           D | R: "╔", D | L: "╗", U | R: "╚", U | L: "╝",
           U | D | R: "╠", U | D | L: "╣", L | R | D: "╦", L | R | U: "╩",
           U | D | L | R: "╬"}
_STRAIGHT = {"dashed": ("╎", "╌"), "dotted": ("┆", "┄"), "hdash": ("╏", "╍")}
_RANK = {"heavy": 4, "double": 3, "light": 2, "hdash": 1, "dashed": 1, "dotted": 0}


def _old_glyph(stroke: str, mask: int) -> str:
    if stroke in _STRAIGHT:
        v, h = _STRAIGHT[stroke]
        if mask in (U, D, U | D):
            return v
        if mask in (L, R, L | R):
            return h
        return _LIGHT[mask]
    return {"heavy": _HEAVY, "double": _DOUBLE}.get(stroke, _LIGHT)[mask]


def _rgb(c):
    return [int(c[i:i + 2], 16) for i in (1, 3, 5)]


class StrokesTest(unittest.TestCase):
    def test_every_stroke_and_mask_draws_as_before(self):
        for stroke in ("light", "heavy", "double", "dashed", "dotted", "hdash", "unknown"):
            for mask in range(16):
                with self.subTest(stroke=stroke, mask=mask):
                    self.assertEqual(kit._stroke_char(stroke, mask), _old_glyph(stroke, mask))

    def test_bits_and_ranks(self):
        self.assertEqual((kit.U, kit.R, kit.D, kit.L), (U, R, D, L))
        self.assertEqual(kit._OPP, {U: D, D: U, L: R, R: L})
        self.assertEqual(kit._STROKE_RANK, _RANK)

    def test_legend_samples(self):
        self.assertEqual([kit._stroke_sample(k) for k in ("->", "=>", "*>", "~>", "?>", "trigger")],
                         ["─", "━", "═", "╌", "┄", "╍"])


class ColourMathsTest(unittest.TestCase):
    def test_muted_faded_tint_as_before(self):
        bg = _rgb(kit.BG)
        for kind, spec in kit.KINDS.items():
            c = spec["color"]
            with self.subTest(kind=kind):
                h, light, s = colorsys.rgb_to_hls(*(v / 255 for v in _rgb(c)))
                want = "#%02x%02x%02x" % tuple(
                    round(v * 255) for v in colorsys.hls_to_rgb(h, light, s * kit.NAME_SATURATION))
                m = kit.muted(c)
                self.assertEqual((str(m), m.role), (want, "muted:" + c.role))
                for k in (0.0, kit.SIM_TRAIL, 1.0):
                    want = "#%02x%02x%02x" % tuple(
                        round(b + (f - b) * k) for f, b in zip(_rgb(c), bg))
                    t = kit.faded(c, k, "trail")
                    self.assertEqual((str(t), t.role), (want, "trail:" + c.role))
                want = "#%02x%02x%02x" % tuple(
                    round(b + (f - b) * kit.FILL) for f, b in zip(_rgb(c), bg))
                self.assertEqual(str(kit._tint(c)), want)

    def test_hex_reading(self):
        self.assertEqual(kit._hex("#ABC"), "#AABBCC")
        self.assertEqual(kit._hex("#a1b2c3"), "#a1b2c3")
        for bad in ("#abcd", "abc", "#ggg", "#abc\n", "", None, 3):
            self.assertIsNone(kit._hex(bad), bad)


class MemoTest(unittest.TestCase):
    def test_frame_memo_is_cures_memo_with_the_style_epoch(self):
        memo = kit.FrameMemo()
        self.assertIsInstance(memo, kit.Memo)
        a = object()
        plan = memo.plan(("graph",), (a,))
        self.assertIsInstance(plan, kit.Plan)
        self.assertIs(memo.plan(("graph",), (a,)), plan)
        kit.use_dialect(None)                       # bumps the style count
        self.assertIsNot(memo.plan(("graph",), (a,)), plan)

    def test_retained_repaints_a_role_change_of_one_hex(self):
        one = kit.Colour("#6e7681", "edges-maybe")
        two = kit.Colour("#6e7681", "edges-split")
        cv = kit.Canvas()
        cv.put(0, 0, "ab", (one, None, False))
        cv.put(0, 1, "cd", (one, None, False))
        kept = kit.Retained(cv, {"x": ((0,), (one, None, False)), "y": ((1,), "same")})
        painted = []

        def paint(rows):
            painted.append(set(rows))
            c = kit.Canvas()
            c.put(0, 0, "ab", (two, None, False))
            c.put(0, 1, "cd", (one, None, False))
            return c

        kept.repaint({"x": ((0,), (two, None, False)), "y": ((1,), "same")}, paint)
        self.assertEqual(painted, [{0}])
        kept.repaint({"x": ((0,), (two, None, False)), "y": ((1,), "same")}, paint)
        self.assertEqual(painted, [{0}])            # nothing changed: nothing painted
        rows = list(kept.canvas.rows())
        self.assertEqual(rows[0][0][1][0].role, "edges-split")


if __name__ == "__main__":
    unittest.main()
