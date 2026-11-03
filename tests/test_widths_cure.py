"""The kit measures by cure's Text (round 12): one width rule, cure's grapheme
clusters, for every drawing — char_cells / cell_width / cut_cells / wrap_cells /
clip and the Canvas text layer — so the live view's screen (app.screen_grid,
laid by cure), the --once text and the frames hosts' packed rows agree column
for column, a cluster (an emoji ZWJ sequence, a flag, VS16, a letter and its
mark, Hangul L V T jamo) drawn whole."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sigil.present import app, frames, kit

import sigil.vendor  # noqa: F401  (cure on the path)
from cure.core.text import width as cure_width

FAMILY = "\U0001f468‍\U0001f469‍\U0001f467"
FLAG = "\U0001f1fa\U0001f1f8"
HEART = "❤️"
THUMB = "\U0001f44d\U0001f3fd"
JAMO = "각"
CLUSTERS = [FAMILY, FLAG, HEART, THUMB, JAMO, "é"]

DOC = (f"#!craft\n# {FAMILY} family {HEART} and {FLAG}, {JAMO}\n"
       f"[Café] -> [가각] : say({THUMB})\n[가각] ~> |Store{HEART}| : put({FLAG})\n")


class KitWidths(unittest.TestCase):
    def test_widths_are_cures(self):
        for c in CLUSTERS + ["a", "中", "​", "\x1b"]:
            with self.subTest(c=c):
                self.assertEqual(kit.char_cells(c), cure_width(c))
                self.assertEqual(kit.cell_width(f"ab{c}cd"), 4 + cure_width(c))
        self.assertEqual([kit.char_cells(c) for c in CLUSTERS], [2, 2, 2, 2, 2, 1])
        self.assertEqual(kit.clusters(f"a{FAMILY}b"), ("a", FAMILY, "b"))

    def test_cut_and_clip_never_split_a_cluster(self):
        self.assertEqual(kit.cut_cells(f"a{FAMILY}b", 2), "a")
        self.assertEqual(kit.cut_cells(f"a{FAMILY}b", 3), f"a{FAMILY}")
        self.assertEqual(kit.cut_cells(f"aéb", 2), "aé")
        row = [(f"a{FLAG}b", None)]
        self.assertEqual(kit.clip(row, 0, 2), [("a ", None)])     # a cluster cut at the edge: a blank
        self.assertEqual(kit.clip(row, 2, 2), [(" b", None)])
        self.assertEqual(kit.clip(row, 1, 2), [(FLAG, None)])

    def test_wrap_measures_clusters(self):
        lines = kit.wrap_cells(f"{FAMILY} {FAMILY} {FAMILY}", 5)
        self.assertEqual(lines, [f"{FAMILY} {FAMILY}", FAMILY])
        self.assertEqual(kit.wrap_cells("a b\nc", 80), ["a b c"])    # one paragraph, as textwrap
        self.assertEqual(kit.wrap_cells("中文字符串", 4), ["中文", "字符", "串"])

    def test_canvas_lays_clusters(self):
        cv = kit.Canvas()
        cv.put(0, 0, f"[{FAMILY}{JAMO}]")
        self.assertEqual([cv.text[(x, 0)][0] for x in range(6)],
                         ["[", FAMILY, kit.WIDE_TAIL, JAMO, kit.WIDE_TAIL, "]"])
        self.assertEqual(cv.w, 6)
        cv.put(1, 0, "x")                                     # half of a wide cluster overwritten
        rows = list(cv.rows())
        self.assertEqual(kit.row_len(rows[0]), 6)
        self.assertEqual("".join(t for t, _ in rows[0]), f"[x {JAMO}]")


class ScreenOnceAndFrames(unittest.TestCase):
    def test_every_view_agrees_column_for_column(self):
        from cure.core.buffer.rows import text
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "doc.sigil"
            path.write_text(DOC, encoding="utf-8")
            for view in app.VIEWS:
                with self.subTest(view=view):
                    st = app.ViewState(path, view=view)
                    st.reload(force=True)
                    rows = st.frame(100, 40)
                    grid = app.screen_grid(rows, 100, 40)
                    got = text(grid).split("\n")
                    want = ["".join(t for t, _ in r).rstrip(" ") for r in rows]
                    self.assertEqual(got[:len(want)], want)
                    for y, r in enumerate(rows):
                        self.assertLessEqual(kit.row_len(r), 100)
                    tables: list = []
                    packed = frames.packed(rows, frames.HexStyles(), tables)
                    for y, prow in enumerate(packed):
                        cells = "".join(t for t, _ in prow)
                        self.assertEqual(len(cells), kit.cell_width(want[y]), want[y])
                        whole = dict(tables[y])
                        self.assertEqual("".join(whole.get(x, c) for x, c in enumerate(cells)
                                                 if c != frames.WIDE_TAIL), want[y])


if __name__ == "__main__":
    unittest.main()
