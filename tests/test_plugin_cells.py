"""Wide characters and clusters in the plugins: `sigil frames` (sigil.present.frames)
packs every row through cure's Wire (format 2) by the kit's widths (cure's
grapheme clusters, the package's kit, not a copy) — a wide cluster its first code
point then WIDE_TAIL, its continuation cell, any other cluster its first code
point, and a cluster longer than one code point whole in the row's side table —
so a packed row is as many code points as the viewer's row is columns; logic.ts
measures plain text by the same per-code-point rule (its WIDE and ZERO tables,
written from cure's by tools/wide_table.py)."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from sigil.core.parse import parse_document
from sigil.present import app, kit
from sigil.present import frames as pane

ROOT = Path(__file__).resolve().parent.parent
FRAMES = ROOT / "sigil" / "present" / "frames.py"
LOGIC = ROOT / "plugin" / "claude" / "hooks" / "logic.ts"
CJK = ROOT / "tests" / "fixtures" / "cjk.sigil"
NODE = shutil.which("node")


def _strips_types() -> bool:
    """node runs .ts files itself (type stripping, on by default from 23.6)."""
    if NODE is None:
        return False
    r = subprocess.run([NODE, "-e", "process.exit(process.features.typescript ? 0 : 1)"],
                       capture_output=True, timeout=30)
    return r.returncode == 0


def _node(script: str, stdin: str = "") -> str:
    r = subprocess.run([NODE, "--input-type=module", "-e", script], input=stdin,
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise AssertionError(r.stderr)
    return r.stdout


def packed_text(text: str) -> tuple[str, list]:
    """`text` as one packed row's text and its side table."""
    tables: list = []
    rows = pane.packed([[(text, None)]], pane.HexStyles(), tables)
    return "".join(t for t, _ in rows[0]) if rows else "", tables[0] if tables else []


def drawn(row_text: str, table: list) -> str:
    """A packed row's text as a host draws it: each cell its cluster, tails nothing."""
    whole = dict(table)
    return "".join(whole.get(x, ch) for x, ch in enumerate(row_text) if ch != pane.WIDE_TAIL)


class PaneCells(unittest.TestCase):
    def test_each_cluster_as_many_cells_as_its_columns(self):
        for ch in ["a", "─", "界", "ア", "é", "😀", "\U0001d400", "👍🏽",
                   "❤️", "🇺🇸", "각", "👨‍👩‍👧"]:
            with self.subTest(ch=ch):
                text, table = packed_text(ch)
                self.assertEqual(len(text), kit.char_cells(ch))
                if kit.char_cells(ch) == 2:
                    self.assertEqual(text, ch[0] + pane.WIDE_TAIL)   # its first code point, then its second cell
                self.assertEqual(table, [[0, ch]] if len(ch) > 1 else [])
                self.assertEqual(drawn(text, table), ch)

    def test_a_wide_character_is_itself_not_question_marks(self):
        self.assertEqual(packed_text("a界́─"), ("a界\0─", [[1, "界́"]]))
        self.assertEqual(packed_text("(利用者)"), ("(利\0用\0者\0)", []))
        self.assertEqual(pane.WIDE_TAIL, "\0")    # logic.ts's WIDE_TAIL
        self.assertIn("export const WIDE_TAIL = '\\u0000'", LOGIC.read_text(encoding="utf-8"))

    def test_the_width_rule_is_the_kits(self):
        self.assertIs(pane.kit, kit)
        source = FRAMES.read_text(encoding="utf-8")
        for own in ("east_asian_width", "_ZERO_WIDTH", "unicodedata", "pack_rows", "_JOINS"):
            self.assertNotIn(own, source)

    def test_a_cjk_design_keeps_the_viewers_columns_in_every_view(self):
        g = parse_document(CJK.read_text(encoding="utf-8"))
        for name in app.VIEWS:
            with self.subTest(view=name):
                rows, _ = app.compose_view(
                    g, name, depth=1, payloads=False, notes="off", triggers=True,
                    spaced=True, width=None, access=False, mods=False, events="nodes")
                for row in rows:
                    text = "".join(t for t, _ in row)
                    cells, table = packed_text(text)
                    self.assertEqual(len(cells), kit.cell_width(text.rstrip(" ")), text)
                    self.assertEqual(drawn(cells, table), text.rstrip(" "), text)


@unittest.skipUnless(_strips_types(), "node with TypeScript type stripping not on PATH")
class LogicCells(unittest.TestCase):
    def test_char_cells_is_the_kits_over_every_code_point(self):
        codes = [c for c in range(0x110000) if not 0xD800 <= c <= 0xDFFF]
        out = _node(
            f"import {{ charCells }} from {json.dumps(LOGIC.as_uri())}\n"
            "import { readFileSync } from 'node:fs'\n"
            "const codes = JSON.parse(readFileSync(0, 'utf8'))\n"
            "process.stdout.write(codes.map(c => charCells(String.fromCodePoint(c))).join(''))\n",
            json.dumps(codes))
        wrong = [hex(c) for c, n in zip(codes, out) if int(n) != kit.char_cells(chr(c))]
        self.assertEqual(len(out), len(codes))
        self.assertEqual(wrong, [])

    def test_cell_width_and_cut_cells(self):
        out = json.loads(_node(
            f"import {{ cellWidth, cutCells }} from {json.dumps(LOGIC.as_uri())}\n"
            "console.log(JSON.stringify([cellWidth('a界́b'), cutCells('a界b', 2),"
            " cutCells('a界b', 3), cutCells('café!', 4)]))\n"))
        self.assertEqual(out, [4, "a", "a界", "café"])

    def test_drawn_runs_reads_the_side_table(self):
        out = json.loads(_node(
            f"import {{ drawnRuns }} from {json.dumps(LOGIC.as_uri())}\n"
            "const fam = '\\u{1f468}\\u200d\\u{1f469}\\u200d\\u{1f467}'\n"
            "console.log(JSON.stringify([drawnRuns([['cafe!', 0]], [[3, 'e\\u0301']]),"
            " drawnRuns([['x\\u{1f468}\\u0000y', 1]], [[1, fam]]),"
            " drawnRuns([['x\\u{1f468}\\u0000y', 1]], [[1, fam]], 0, 2)]))\n"))
        fam = "\U0001f468‍\U0001f469‍\U0001f467"
        self.assertEqual(out, [[["café!", 0]], [[f"x{fam}y", 1]], [["x ", 1]]])


if __name__ == "__main__":
    unittest.main()
