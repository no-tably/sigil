"""frames.packed through cure's Wire, format 2 (round 12): every row a view hands
it is cure's packing — cells by cure's grapheme clusters, runs, trailing blanks,
the cluster side table — mapped onto sigil's own style table (roles or hex, in
sigil's order). The reference below is cure's `pack` itself, called on the same
rows with each style as the table entry it stands for; a row with no cluster
longer than one code point, no trailing blank in a run and no empty run packs as it did
before 0.7.0 (the old packing kept here as a second reference)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from sigil.present import app, frames, kit

import sigil.vendor  # noqa: F401  (cure on the path)
from cure.core.buffer.rows import Rows
from cure.core.buffer.wire import pack
from cure.core.style import Colour, Style

ROOT = Path(__file__).resolve().parent.parent


def cure_reference(rows, styles) -> tuple[list, list]:
    """cure's pack of `rows`, each style as a Style whose colours' roles are the
    table's colour text: (rows as [[text, table id]], side tables)."""
    def style(st):
        fg, bg, bold = styles.table[styles.intern(st)]
        if fg is None and bg is None and not bold:
            return None
        return Style(fg=Colour("rgb", (0, 0, 0), fg) if fg else None,
                     bg=Colour("rgb", (0, 0, 0), bg) if bg else None, bold=bold)
    p = pack(Rows.of([[(t, style(st)) for t, st in row] for row in rows]), colours="role")
    keys = [(fg, bg, "b" in attrs) for fg, bg, attrs, _ in p.styles]
    out = [[[t, styles.index[keys[i]]] for t, i in row] for row in p.rows]
    while out and not out[-1]:
        out.pop()
    return out, [[list(c) for c in t] for t in p.clusters[:len(out)]]


def old_reference(rows, styles) -> list:
    """frames.packed before 0.7.0 (code points, trailing blank runs dropped)."""
    out = []
    for row in rows:
        packed: list = []
        for text, st in row:
            text = "".join(ch + "\0" if kit.char_cells(ch) == 2 else ch
                           for ch in text if kit.char_cells(ch))
            sid = styles.intern(st)
            if packed and packed[-1][1] == sid:
                packed[-1][0] += text
            else:
                packed.append([text, sid])
        while packed and not packed[-1][0].strip() and not styles.table[packed[-1][1]][1]:
            packed.pop()
        out.append(packed)
    while out and not out[-1]:
        out.pop()
    return out


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
    [("  ", None), ("中文 名字", A), ("x", B)],
    [("é mark", A), ("​ zero ‍", None), ("\x07ctl\t", B)],
    [("\U0001f600 face", A), ("\U0001f44d\U0001f3fb thumb", B)],
    [("각 jamo", A), ("각", None)],
    [("\U0001f1fa\U0001f1f8 flag ❤️", A)],
    [("tail   ", A)],
    [("x", A), ("   ", A)],
    [("x", A), ("   ", B)],
    [("x", A), ("  ", None)],
    [("x", A), ("  ", BG)],
    [("x", A), ("", BG), ("y", B)],
    [("x", A), ("́", B), ("y", B)],
    [("bold only", BOLD), (" ", None)],
    [],
    [("", None)],
    [("　wide space", A), ("　", None)],
    [("last", B)],
    [("x", (Hue("default"), None, False)), ("y", (Hue("teal"), None, False))],
    [],
    [("  ", None)],
]

PLAIN = [ROWS[0], ROWS[1], ROWS[17], ROWS[18]]   # no long cluster, trailing blank or empty run


class PackedByCure(unittest.TestCase):
    def check(self, rows, kind):
        ref, new = kind(), kind()
        tables: list = []
        got = frames.packed(rows, new, tables)
        want, side = cure_reference(rows, ref)
        self.assertEqual(got, want)
        self.assertEqual(tables, side)
        self.assertEqual(new.table, ref.table)

    def test_every_crafted_row_alone_and_together(self):
        for kind in (frames.HexStyles, frames.Styles):
            for row in ROWS:
                with self.subTest(kind=kind.__name__, row=row):
                    frames._PACKED_ROWS.clear()
                    self.check([row], kind)
            self.check(ROWS, kind)

    def test_rows_without_clusters_pack_as_before(self):
        for kind in (frames.HexStyles, frames.Styles):
            self.assertEqual(frames.packed(PLAIN, kind()), old_reference(PLAIN, kind()))

    def test_side_tables(self):
        tables: list = []
        rows = frames.packed([[("café!", A)], [("ab", None)],
                              [("\U0001f1ef\U0001f1f5 \U0001f468‍\U0001f469‍\U0001f467", B)]],
                             frames.HexStyles(), tables)
        self.assertEqual([t for t, _ in rows[0]], ["cafe!"])
        self.assertEqual([t for t, _ in rows[2]], ["\U0001f1ef\0 \U0001f468\0"])
        self.assertEqual(tables, [[[3, "é"]], [],
                                  [[0, "\U0001f1ef\U0001f1f5"],
                                   [3, "\U0001f468‍\U0001f469‍\U0001f467"]]])
        self.assertEqual(frames.side_tables(tables + [[], []]), tables)
        self.assertEqual(frames.side_tables([[], []]), [])

    def test_table_order_across_draws_and_the_memo(self):
        # one table across several calls (as draw: frames, path rows, legend),
        # the second time from the memo, a fresh table taking sigil's order again
        for _ in range(2):
            ref, new = frames.HexStyles(), frames.HexStyles()
            for rows in (ROWS[5:], ROWS, ROWS[:3], list(reversed(ROWS))):
                tables: list = []
                self.assertEqual((frames.packed(rows, new, tables), tables),
                                 cure_reference(rows, ref))
            self.assertEqual(new.table, ref.table)

    def test_role_tables_tell_roles_apart(self):
        one = [[("x", (Hue("#2aa198", "kinds-service"), None, False))]]
        two = [[("x", (Hue("#2aa198", "kinds-actor"), None, False))]]
        styles = frames.Styles()
        self.assertEqual(frames.packed(one, styles), [[["x", 0]]])
        self.assertEqual(frames.packed(two, styles), [[["x", 1]]])
        self.assertEqual(styles.table, [["kinds-service", None, False],
                                        ["kinds-actor", None, False]])

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

    def test_draw_carries_the_side_tables(self):
        out = frames.draw(ROOT / "tests" / "fixtures" / "cjk.sigil", "flow", width=80)
        json.dumps(out)
        self.assertTrue(all(len(s) == 3 for s in out["styles"]))
        side = out["clusters"]["frames"][0]           # é is e + U+0301 in the fixture
        self.assertLessEqual(len(side), len(out["frames"][0]))
        found = [glyph for table in side for _col, glyph in table]
        self.assertIn("é", found)
        for y, table in enumerate(side):
            text = "".join(t for t, _ in out["frames"][0][y])
            for col, glyph in table:
                self.assertEqual(text[col], glyph[0])
        plain = frames.draw(ROOT / "site" / "examples" / "02-shop.sigil", "flow", width=80)
        self.assertNotIn("clusters", plain)          # none to give: the envelope as before


def _doc(path):
    from sigil.core.parse import parse_document
    return (parse_document(path.read_text(encoding="utf-8")),)


if __name__ == "__main__":
    unittest.main()
