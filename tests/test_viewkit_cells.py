"""Tests for viewkit's cells: a drawn width measured in terminal columns.

Covers:
  - cell_width: ASCII is len(), a wide (CJK, east_asian_width W / F) character
    takes 2 columns, a combining mark or a zero-width character 0, the
    drawing kit's own glyphs (box strokes, ◀ ┆ ↩ …) 1;
  - cut_cells, ljust_cells, wrap_cells: textwrap's lines for
    one-column text, a wide word cut by columns, long_words / indent;
  - Canvas: a wide character takes two cells, a combining mark joins the cell
    before, a wide character half overdrawn becomes a blank (the row keeps its
    columns); clip and row_len by columns, probed_box by columns;
  - every view (graph, tree, flow, run) draws tests/fixtures/cjk.sigil exactly
    as it draws its ASCII twin (each wide character written as two letters,
    each combining mark dropped), names put back: wide names never shift a
    column.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import re
import sys
import tempfile
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]


def _load(name: str, fname: str):
    spec = importlib.util.spec_from_file_location(name, _DIR / fname)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


view = _load("sigil_view_cells_tests", "view.py")
kit = view.kit

CJK = _DIR / "tests" / "fixtures" / "cjk.sigil"
ACUTE = "́"


class TestCellWidth(unittest.TestCase):
    def test_ascii_is_len(self):
        for s in ("", "a", "[Shortener] -> |Links|", "  x  "):
            self.assertEqual(kit.cell_width(s), len(s))

    def test_wide_characters_take_two(self):
        self.assertEqual(kit.cell_width("短縮"), 4)
        self.assertEqual(kit.cell_width("[リンク表]"), 10)
        self.assertEqual(kit.cell_width("ＡＢ"), 4)          # fullwidth Latin (F)

    def test_combining_marks_take_none(self):
        self.assertEqual(kit.cell_width("cafe" + ACUTE), 4)
        self.assertEqual(kit.cell_width("a\u200db"), 2)      # zero-width joiner

    def test_drawing_glyphs_take_one(self):
        glyphs = "─│┌┐└┘├┤┬┴┼╭╮╰╯┄┆╌╎━┃═║◀▶▲▼●○◆◇✖✱◎↩↺↻⇱▸▾┊≈░█"
        self.assertEqual(kit.cell_width(glyphs), len(glyphs))


class TestCellText(unittest.TestCase):
    def test_cut_cells(self):
        self.assertEqual(kit.cut_cells("abcdef", 3), "abc")
        self.assertEqual(kit.cut_cells("短縮器", 4), "短縮")
        self.assertEqual(kit.cut_cells("短縮器", 5), "短縮")   # no half a character
        self.assertEqual(kit.cut_cells("cafe" + ACUTE + "s", 4), "cafe" + ACUTE)
        self.assertEqual(kit.cut_cells("短", 0), "")

    def test_justify(self):
        self.assertEqual(kit.ljust_cells("短縮", 6), "短縮  ")
        self.assertEqual(kit.ljust_cells("abc", 5, "─"), "abc──")
        self.assertEqual(kit.ljust_cells("短縮器", 2), "短縮器")   # never cut

    def test_wrap_one_column_text_is_textwraps(self):
        import textwrap
        text = "a call · its payload ↩ {Code} and a-hyphenated-word to wrap here"
        for w in (8, 13, 21):
            self.assertEqual(kit.wrap_cells(text, w), textwrap.wrap(text, w))
            self.assertEqual(kit.wrap_cells(text, w, indent="  ", hyphens=False,
                                            long_words=False),
                             textwrap.wrap(text, w, subsequent_indent="  ",
                                           break_on_hyphens=False, break_long_words=False))

    def test_wrap_wide_text_by_columns(self):
        lines = kit.wrap_cells("短縮サービスは網址を保存する and more words", 10)
        self.assertTrue(all(kit.cell_width(ln) <= 10 for ln in lines))
        self.assertEqual("".join(lines).replace(" ", ""),
                         "短縮サービスは網址を保存するandmorewords")
        self.assertEqual(lines[-2:], ["and more", "words"])   # an ASCII word moves whole

    def test_wrap_indent_and_long_words(self):
        lines = kit.wrap_cells("x 短縮サービスは網址", 8, indent="    ")
        self.assertTrue(all(kit.cell_width(ln) <= 8 for ln in lines))
        self.assertTrue(all(ln.startswith("    ") for ln in lines[1:]))
        # long_words=False keeps an ASCII word whole, still cuts a wide one
        self.assertEqual(kit.wrap_cells("短 abcdefghijkl", 6, long_words=False),
                         ["短", "abcdefghijkl"])
        self.assertTrue(len(kit.wrap_cells("短縮サービス", 6, long_words=False)) > 1)


class TestCanvasCells(unittest.TestCase):
    def rows(self, cv):
        return ["".join(t for t, _ in r) for r in cv.rows()]

    def test_wide_text_takes_two_cells(self):
        cv = kit.Canvas()
        cv.put(0, 0, "[短縮]")
        cv.put(6, 0, "|")
        self.assertEqual((cv.w, self.rows(cv)), (7, ["[短縮]|"]))
        self.assertEqual(kit.row_len(next(iter(cv.rows()))), 7)

    def test_combining_mark_joins_the_cell_before(self):
        cv = kit.Canvas()
        cv.put(0, 0, "cafe" + ACUTE + "|")
        self.assertEqual((cv.w, self.rows(cv)), (5, ["cafe" + ACUTE + "|"]))

    def test_combining_mark_after_a_wide_character_joins_it(self):
        cv = kit.Canvas()
        cv.put(0, 0, "\u304b\u3099x")          # が decomposed: か + U+3099
        self.assertEqual((cv.w, self.rows(cv)), (3, ["\u304b\u3099x"]))
        self.assertEqual(kit.row_len(next(iter(cv.rows()))), 3)

    def test_overdrawn_half_becomes_a_blank(self):
        cv = kit.Canvas()
        cv.put(0, 0, "短縮器")
        cv.put(3, 0, "x")                       # over 縮's second half
        self.assertEqual(self.rows(cv), ["短 x器"])
        cv = kit.Canvas()
        cv.put(0, 0, "短縮器")
        cv.put(2, 0, "y")                       # over 縮's first half
        self.assertEqual(self.rows(cv), ["短y 器"])
        self.assertEqual(kit.row_len(next(iter(cv.rows()))), 6)

    def test_lines_and_blit_keep_columns(self):
        cv = kit.Canvas()
        cv.put(0, 0, "(利用者)")
        cv.link((8, 0), (9, 0), "->", None)
        out = kit.Canvas()
        out.blit(cv, 2, 1)
        rows = self.rows(out)
        self.assertEqual(kit.cell_width(rows[1]), 12)
        self.assertTrue(rows[1].endswith("(利用者)──"))

    def test_clip_by_columns(self):
        row = [("ab", None), ("短縮", None), ("cd", None)]
        self.assertEqual(kit.clip(row, 2, 4), [("短縮", None)])
        self.assertEqual(kit.clip(row, 3, 4), [(" 縮", None), ("c", None)])
        self.assertEqual(kit.clip(row, 0, 3), [("ab", None), (" ", None)])
        self.assertEqual(kit.clip([("ab", None)], 1, 5), [("b", None)])

    def test_probed_box_by_columns(self):
        row = [("短縮", None), ("x", kit.Probe((None, None, False)))]
        self.assertEqual(kit.probed_box([row]), (4, 0, 1, 1))


_WORD = re.compile(r"[^\s()\[\]{}<>|,:;.]+")


def _twin(text: str) -> tuple[str, dict]:
    """(text with each wide character written as two ASCII letters and each
    combining mark dropped, {twin word: its wide word}). The pairs keep
    the characters' order (w… z… sort after the fixture's ASCII names' first
    letters), so a layout that sorts by name sorts the twin the same."""
    wide = sorted({ch for ch in text if kit.char_cells(ch) == 2})
    pair = {ch: chr(ord("w") + k // 26) + chr(ord("a") + k % 26) for k, ch in enumerate(wide)}

    def twin(s):
        return "".join(pair.get(ch, "" if kit.char_cells(ch) == 0 else ch) for ch in s)

    words = {w for w in _WORD.findall(text) if kit.cell_width(w) != len(w)}
    return twin(text), {twin(w): w for w in words}


def _draw(path: Path, args: list) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        view.main(["--once", "--color", "never", *args, str(path)])
    return buf.getvalue()


def _back(drawing: str, back: dict) -> str:
    """A twin's drawing with its twin words put back as the fixture's (whole
    words only, the longest first)."""
    pattern = re.compile(r"(?<![A-Za-z])(" + "|".join(
        re.escape(w) for w in sorted(back, key=len, reverse=True)) + r")(?![A-Za-z])")
    return pattern.sub(lambda m: back[m.group(1)], drawing)


class TestWideNamesInEveryView(unittest.TestCase):
    """The CJK fixture drawn in every view is its ASCII twin's drawing, with the
    names put back — so every column a wide name takes is counted."""

    FLAGS = ([], ["--payloads", "--mods", "--notes", "markers"], ["--depth", "all"],
             ["--width", "60", "--payloads"], ["--sim", "happy", "--frame", "12"],
             ["--notes", "callouts", "--access", "--checks"])
    VIEWS = ("--graph", "--tree", "--flow", "--run")

    @classmethod
    def setUpClass(cls):
        text = CJK.read_text(encoding="utf-8")
        twin, cls.back = _twin(text)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.twin_path = Path(cls.tmp.name) / CJK.name
        cls.twin_path.write_text(twin, encoding="utf-8")
        cls.accented = {"cafe": "cafe" + ACUTE}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_fixture_has_wide_names_and_a_combining_mark(self):
        text = CJK.read_text(encoding="utf-8")
        self.assertIn("[転送するサービス]", text)
        self.assertIn("[cafe" + ACUTE + "]", text)
        self.assertIn("[\u30ab\u3099\u30a4\u30c8\u3099\u4fc2]", text)   # ガイド係 decomposed

    def test_every_view_matches_its_ascii_twin(self):
        for v in self.VIEWS:
            for flags in self.FLAGS:
                with self.subTest(view=v, flags=flags):
                    want = _back(_draw(self.twin_path, [v, *flags]), self.back)
                    got = _draw(CJK, [v, *flags])
                    self.assertEqual(self._names_only(got), self._names_only(want))

    @staticmethod
    def _names_only(drawing: str) -> list:
        """The drawing's rows, the free text of the document's notes (which
        wraps at words of a different width) left out."""
        rows, skip = [], False
        for row in drawing.splitlines():
            if row.lstrip().startswith("¶"):
                skip = True
            elif skip and not row.startswith("  "):
                skip = False
            if not skip:
                rows.append(row.rstrip())
        return rows

    def test_rows_line_up(self):
        """In the graph view a wide name's box closes under its top corners."""
        got = [kit._one_per_column(r) for r in _draw(CJK, ["--graph"]).splitlines()]
        for y, row in enumerate(got):
            if "│ [転転送送" in row:
                x0, x1 = row.index("│ [転"), row.index("│", row.index("[転"))
                self.assertEqual((got[y - 1][x0], got[y - 1][x1]), ("┌", "┐"))
                self.assertEqual((got[y + 1][x0], got[y + 1][x1]), ("└", "┘"))
                return
        self.fail("no box for [転送するサービス]")

if __name__ == "__main__":
    unittest.main()
