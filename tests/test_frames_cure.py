"""frames.packed through cure's Wire (round 11): the packed rows and style
table are what sigil's own packing gives (the reference below is frames.py's
packing before 0.7.0), byte for byte, for every row a view can hand it — wide
characters, marks, format and control characters, the characters cure joins
to the one before (frames._JOINS), trailing blanks, empty runs, role and hex
tables, the table's order across rows and draws, and the row memo."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from sigil.present import app, frames, kit

import sigil.vendor  # noqa: F401  (cure on the path)
from cure.core.text import Line, put
from cure.core.text.graphemes import cluster

ROOT = Path(__file__).resolve().parent.parent


def reference(rows, styles) -> list:
    """frames.packed as it was before cure packed it."""
    return frames.pack_rows([[(frames.cells(t), st) for t, st in row] for row in rows], styles)


class Hue(str):
    """A view's colour: its hex, with the theme role it came from."""

    def __new__(cls, hexa: str, role: str = ""):
        obj = super().__new__(cls, hexa)
        obj.role = role
        return obj


A = (Hue("#2aa198", "kinds-service"), None, False)
B = (Hue("#AbC123", "kinds-store"), None, True)
BG = (Hue("#111111", "a"), Hue("#222222", "b"), False)
BOLD = (None, None, True)

ROWS = [
    [("plain", None), ("teal", A), (" and ", None), ("bold", B)],
    [("  ", None), ("\u4e2d\u6587 \u540d\u5b57", A), ("x", B)],
    [("e\u0301 mark", A), ("\u200b zero \u200d", None), ("\x07ctl\t", B)],
    [("\U0001f600 face", A), ("\U0001f44d\U0001f3fb thumb", B)],
    [("\u1100\u1161\u11a8 jamo", A), ("\uac00\u11a8", None)],
    [("tail   ", A)],
    [("x", A), ("   ", A)],
    [("x", A), ("   ", B)],
    [("x", A), ("\u00a0\u00a0", None)],
    [("x", A), ("  ", BG)],
    [("x", A), ("", BG), ("y", B)],
    [("x", A), ("\u0301", B), ("y", B)],
    [("bold only", BOLD), (" ", None)],
    [],
    [("", None)],
    [("\u3000wide space", A), ("\u3000", None)],
    [("last", B)],
    [],
    [("  ", None)],
]


class PackedAsBefore(unittest.TestCase):
    def check(self, rows, kind):
        old, new = kind(), kind()
        self.assertEqual(frames.packed(rows, new), reference(rows, old))
        self.assertEqual(new.table, old.table)
        return old, new

    def test_every_crafted_row_alone_and_together(self):
        for kind in (frames.HexStyles, frames.Styles):
            for row in ROWS:
                with self.subTest(kind=kind.__name__, row=row):
                    self.check([row], kind)
            self.check(ROWS, kind)

    def test_ordinary_rows_are_packed_by_cure(self):
        plain = ROWS[:3] + [ROWS[16]]
        kept = frames.pack_rows
        try:
            frames.pack_rows = None             # sigil's own packing is not reached
            frames._PACKED_ROWS.clear()
            got = frames.packed(plain, frames.HexStyles())
        finally:
            frames.pack_rows = kept
        self.assertEqual(got, reference(plain, frames.HexStyles()))

    def test_table_order_across_draws_and_the_memo(self):
        # one table across several calls (as draw: frames, path rows, legend),
        # the second time from the memo, a fresh table taking sigil's order again
        for _ in range(2):
            old, new = frames.HexStyles(), frames.HexStyles()
            for rows in (ROWS[5:], ROWS, ROWS[:3], list(reversed(ROWS))):
                self.assertEqual(frames.packed(rows, new), reference(rows, old))
            self.assertEqual(new.table, old.table)

    def test_role_tables_tell_roles_apart(self):
        one = [[("x", (Hue("#2aa198", "kinds-service"), None, False))]]
        two = [[("x", (Hue("#2aa198", "kinds-actor"), None, False))]]
        styles = frames.Styles()
        self.assertEqual(frames.packed(one, styles), [[["x", 0]]])
        self.assertEqual(frames.packed(two, styles), [[["x", 1]]])
        self.assertEqual(styles.table, [["kinds-service", None, False],
                                        ["kinds-actor", None, False]])

    def test_a_colour_cure_reads_otherwise_keeps_sigils_packing(self):
        rows = [[("x", (Hue("default"), None, False)), ("y", (Hue("teal"), None, False))]]
        for kind in (frames.HexStyles, frames.Styles):
            self.check(rows, kind)

    def test_real_drawings(self):
        f = ROOT / "tests" / "fixtures" / "cjk.sigil"
        for view in ("graph", "tree", "flow", "run"):
            with self.subTest(view=view):
                kit.use_theme(None, None)
                rows, _w = app.compose_view(*_doc(f), view, depth=1, payloads=False,
                                            notes="off", triggers=True, spaced=True,
                                            width=80, access=False, mods=False,
                                            events=app.DEFAULT_EVENTS.get(view, "land"))
                self.check(rows, frames.HexStyles)

    def test_draw_unchanged_in_shape(self):
        out = frames.draw(ROOT / "tests" / "fixtures" / "cjk.sigil", "flow", width=80)
        json.dumps(out)
        self.assertNotIn("clusters", out)       # cure's side table is not in the envelope
        self.assertTrue(all(len(s) == 3 for s in out["styles"]))


def _doc(path):
    from sigil.core.parse import parse_document
    return (parse_document(path.read_text(encoding="utf-8")),)


class CureLaysSigilsCells(unittest.TestCase):
    """Every character frames.cells() keeps is one cell of the same width in
    cure's Text, alone and after another, except frames._JOINS: so a row
    without those is laid by cure as sigil lays it."""

    def test_every_code_point(self):
        bases = ("a", "\uac00", "\u1100")   # a join is the second character's, but Hangul's
        wrong = []
        for cp in range(0x20, sys.maxunicode + 1):
            if 0xD800 <= cp <= 0xDFFF:
                continue
            ch = chr(cp)
            laid = frames.cells(ch).replace(frames.WIDE_TAIL, "")
            if not laid or (laid == "?" and ch != "?"):
                continue                            # cells() drew nothing or `?`
            joins = bool(frames._JOINS.match(ch))
            cut = put(Line.of(ch))
            alone = [c.glyph for c in cut if c.width] == [ch] and len(cut) == kit.char_cells(ch)
            apart = all(len(cluster(b + ch)) == 2 for b in bases) and len(cluster(ch + "a")) == 2
            if (alone and apart) == joins:
                wrong.append(hex(cp))
        self.assertEqual(wrong, [])


if __name__ == "__main__":
    unittest.main()
