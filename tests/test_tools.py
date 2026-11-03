"""The doc and table generators under tools/.

Covers:
  1. tools/wide_table.py: the WIDE and ZERO tables in plugin/claude/hooks/logic.ts
     are current (`--check`); the ranges are sigil.present.kit.char_cells's
     (cure's) wide and zero-width code points exactly; the format packs its ranges
     into lines that fit; only the table's lines are rewritten; `--check` never
     writes, and a file without its table is an error, not a rewrite;
  2. tools/regen_docs.py: `--help` prints usage and draws nothing; `--check`
     never writes, even when a drawing is stale; without it a stale doc is
     rewritten; every README drawing it redraws is found (by `sigil view` or the
     older `view.py` wording), so a reworded command can't skip one silently.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import regen_docs as regen  # noqa: E402  (tools/ is a folder of scripts, not a package)
import wide_table as wide   # noqa: E402


def quiet(fn, *args, **kwargs):
    """fn(...) with its printing kept out of the test output."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


class TestWideTable(unittest.TestCase):
    def test_tables_are_current(self):
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "wide_table.py"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, "run tools/wide_table.py\n" + r.stdout + r.stderr)

    def test_ranges_are_the_wide_characters(self):
        cells = {0x41: 1, 0x42: 2, 0x43: 2, 0x44: 0, 0x45: 2, 0x46: 1, 0x47: 2}
        got = wide.wide_ranges(lambda ch: cells.get(ord(ch), 1), last=0x47)
        self.assertEqual(got, [(0x42, 0x43), (0x45, 0x45), (0x47, 0x47)])   # a mark splits a run
        zero = wide.wide_ranges(lambda ch: cells.get(ord(ch), 1), last=0x47, n=0)
        self.assertEqual(zero, [(0x44, 0x44)])

    def test_format(self):
        ranges = [(0x1100, 0x115f), (0x23f0, 0x23f0), (0x20000, 0x2fffd)]
        self.assertEqual(wide.ts_pair_lines(ranges),
                         ["  0x1100, 0x115f, 0x23f0, 0x23f0, 0x20000, 0x2fffd,"])
        many = [(k * 4, k * 4 + 1) for k in range(0x1000, 0x1100)]
        lines = wide.ts_pair_lines(many, 60)
        self.assertGreater(len(lines), 1)
        self.assertTrue(all(len(ln) <= 60 for ln in lines))
        self.assertEqual(sum(ln.count(",") for ln in lines), 2 * len(many))

    def test_only_the_table_lines_change(self):
        table = wide.TABLES[0]
        text = "before\nconst WIDE: readonly number[] = [\n  0x1, 0x2,\n]\nconst x = [\n]\n"
        got = wide.with_table(text, table, [(0x10, 0x11)])
        self.assertEqual(got, "before\nconst WIDE: readonly number[] = [\n  0x10, 0x11,\n]\n"
                              "const x = [\n]\n")
        with self.assertRaises(wide.TableNotFound):
            wide.with_table("const x = [\n]\n", table, [])
        with self.assertRaises(wide.TableNotFound):
            wide.with_table("const WIDE: readonly number[] = [\n  0x1,\n", table, [])

    @staticmethod
    def cells(ch: str) -> int:
        """A width rule for the copy: U+4E00..U+4E0F wide, U+0300 zero, the rest narrow."""
        return 2 if 0x4E00 <= ord(ch) <= 0x4E0F else 0 if ch == "\u0300" else 1

    def copy_tree(self, tmp: Path, wide_table: str) -> Path:
        """A root holding logic.ts, its WIDE table as given, its ZERO table
        already the one `cells` makes."""
        (tmp / "plugin" / "claude" / "hooks").mkdir(parents=True)
        (tmp / "plugin" / "claude" / "hooks" / "logic.ts").write_text(
            "const WIDE: readonly number[] = [\n" + wide_table + "\n]\n"
            "const ZERO: readonly number[] = [\n  0x300, 0x300,\n]\n", encoding="utf-8")
        return tmp

    def test_check_never_writes_and_update_does(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.copy_tree(Path(d), "  0x1100, 0x1100,")
            logic = root / "plugin" / "claude" / "hooks" / "logic.ts"
            before = logic.read_text(encoding="utf-8")
            self.assertEqual(quiet(wide.main, ["--check"], root=root, cells=self.cells), 1)
            self.assertEqual(logic.read_text(encoding="utf-8"), before)
            self.assertEqual(quiet(wide.main, [], root=root, cells=self.cells), 0)
            self.assertIn("  0x4e00, 0x4e0f,\n", logic.read_text(encoding="utf-8"))
            self.assertEqual(quiet(wide.main, ["--check"], root=root, cells=self.cells), 0)

    def test_missing_table_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.copy_tree(Path(d), "")
            logic = root / "plugin" / "claude" / "hooks" / "logic.ts"
            logic.write_text("no table here\n", encoding="utf-8")
            self.assertEqual(quiet(wide.main, [], root=root, cells=self.cells), 2)
            self.assertEqual(logic.read_text(encoding="utf-8"), "no table here\n")


class TestRegenDocs(unittest.TestCase):
    def test_help(self):
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "regen_docs.py"), "--help"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--check", r.stdout)
        self.assertNotIn("drawing(s)", r.stdout)               # nothing redrawn

    def test_check_never_writes(self):
        """A doc whose drawing is stale: --check reports it and leaves the file;
        without --check it is rewritten."""
        with tempfile.TemporaryDirectory() as d:
            doc = Path(d) / "doc.md"
            doc.write_text("old\n", encoding="utf-8")
            stale = (("doc.md", lambda text: ("new\n", 1)),)
            self.assertEqual(quiet(regen.main, ["--check"], root=Path(d), docs=stale), 1)
            self.assertEqual(doc.read_text(encoding="utf-8"), "old\n")
            self.assertEqual(quiet(regen.main, [], root=Path(d), docs=stale), 0)
            self.assertEqual(doc.read_text(encoding="utf-8"), "new\n")

    def test_readme_anchors_found(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertEqual(regen.missing_anchors(text), [])

    def test_the_command_name(self):
        """The README's commands are `sigil view`; the old `view.py` is no anchor."""
        for cmd, found in (("sigil view", True), ("view.py", False)):
            doc = (f"```sh\n{cmd} orders.sigil --once --sim all\n```\n\n```\nx\n```\n"
                   f"```sh\n{cmd} checkout.sigil --once --run --sim 'A'\n```\n\n```\nx\n```\n")
            missing = regen.missing_anchors(doc)
            self.assertEqual("sim all orders.sigil" not in missing, found, cmd)
            self.assertEqual("run" not in missing, found, cmd)
            self.assertIn("flow", missing, cmd)


if __name__ == "__main__":
    unittest.main()
