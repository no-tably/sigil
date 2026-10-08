"""Wide (CJK) characters in the plugins: pane.py draws every character one column
wide, a wide one as `??` and a combining mark as nothing, so a packed row is as
many characters as view.py's row is columns; logic.ts measures plain text by
viewkit.char_cells's rule (a wide character 2, a combining mark 0)."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import unicodedata
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PANE = ROOT / "plugin" / "claude" / "scripts" / "pane.py"
LOGIC = ROOT / "plugin" / "claude" / "hooks" / "logic.ts"
CJK = ROOT / "tests" / "fixtures" / "cjk.sigil"
NODE = shutil.which("node")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pane = _load("sigil_pane_cells_t", PANE)
view = _load("sigil_view_cells_t", ROOT / "view.py")
kit = view.kit


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


def _assigned() -> list[int]:
    """Every assigned code point that is a mark to Python's Unicode version
    exactly when it is one to node's (unassigned ones and a mark whose category
    changed between the two versions, such as U+1171E, may differ)."""
    codes = [c for c in range(0x110000) if unicodedata.category(chr(c)) not in ("Cn", "Cs")]
    marks = _node(
        "import { readFileSync } from 'node:fs'\n"
        "const codes = JSON.parse(readFileSync(0, 'utf8'))\n"
        "process.stdout.write(codes.map(c => /^[\\p{Mn}\\p{Me}]$/u.test(String.fromCodePoint(c)) ? 1 : 0).join(''))\n",
        json.dumps(codes))
    return [c for c, m in zip(codes, marks)
            if (m == "1") == (unicodedata.category(chr(c)) in ("Mn", "Me"))]


class PaneCells(unittest.TestCase):
    def test_each_character_as_many_one_column_characters_as_its_columns(self):
        for ch in ["a", "─", "界", "ア", "́", "​", "😀", "\U0001d400", "\x07"]:
            with self.subTest(ch=hex(ord(ch))):
                drawn = pane.cells(ch)
                self.assertEqual(len(drawn), kit.char_cells(ch))
                for c in drawn:
                    self.assertTrue(" " <= c and ord(c) <= 0xFFFF)
                    self.assertNotIn(unicodedata.east_asian_width(c), ("W", "F"))

    def test_a_cjk_design_keeps_view_pys_columns_in_every_view(self):
        g = view.render.parse_document(CJK.read_text(encoding="utf-8"))
        for name in view.VIEWS:
            with self.subTest(view=name):
                rows, _ = view.compose_view(
                    g, name, depth=1, payloads=False, notes="off", triggers=True,
                    spaced=True, width=None, access=False, mods=False, events="nodes")
                for row in rows:
                    text = "".join(t for t, _ in row)
                    self.assertEqual(len(pane.cells(text)), kit.cell_width(text), text)


@unittest.skipUnless(_strips_types(), "node with TypeScript type stripping not on PATH")
class LogicCells(unittest.TestCase):
    def test_char_cells_is_viewkits_over_every_assigned_character(self):
        codes = _assigned()
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
            " cutCells('a界b', 3), cutCells('café!', 4)]))\n"))
        self.assertEqual(out, [4, "a", "a界", "café"])


if __name__ == "__main__":
    unittest.main()
