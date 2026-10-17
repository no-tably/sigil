"""Every command speaks as `sigil <command>`: its stderr prefix, its argparse
usage line, and `sigil themes` (what `python3 -m sigil.present.themes` does)."""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigil import cli                    # noqa: E402
from sigil.present import themes        # noqa: E402
from sigil.publish import exporter       # noqa: E402

MISSING = str(ROOT / "no-such-file.sigil")


def run(main, argv: list) -> tuple:
    """(exit status, stdout, stderr) of `main(argv)` run in-process; argparse's
    exits count as a status."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class PrefixTest(unittest.TestCase):
    def test_an_unreadable_file_is_said_by_its_command(self):
        cases = {"sigil lint: ": ["lint", MISSING],
                 "sigil check: ": ["check", MISSING],
                 "sigil view: ": ["view", MISSING, "--once"],
                 "sigil export: ": ["export", MISSING, "--mermaid"]}
        for prefix, argv in cases.items():
            with self.subTest(argv=argv):
                code, _out, err = run(cli.main, argv)
                self.assertEqual(code, 2)
                self.assertTrue(err.startswith(prefix), err)

    def test_export_folder_says_sigil_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _out, err = run(cli.main, ["export", MISSING, "--out", tmp])
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("sigil export: "), err)

    def test_export_folder_refuses_stdin(self):
        # The top system is named after the spec file's stem: stdin has none (as 0.5).
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = run(cli.main, ["export", "-", "--out", tmp])
            self.assertEqual(list(Path(tmp).iterdir()), [])
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(err, "sigil export: SPEC must be a file: its stem names "
                              "the top system\n")

    def test_usage_lines_name_the_subcommand(self):
        for cmd in ("lint", "check", "view", "export", "frames"):
            with self.subTest(cmd=cmd):
                code, out, _err = run(cli.main, [cmd, "--help"])
                self.assertEqual(code, 0)
                self.assertTrue(out.startswith(f"usage: sigil {cmd} "), out[:80])
        code, out, _err = run(cli.main, ["export", "x.sigil", "--mermaid", "--help"])
        self.assertTrue(out.startswith("usage: sigil export "), out[:80])

    def test_export_usage_shows_both_forms(self):
        forms = ("sigil export SPEC --out DIR", "sigil export FILE --mermaid")
        for argv, stream in ((["export", "--help"], 1), (["export", "--bogus"], 2),
                             (["export", "x.sigil", "--mermaid", "--help"], 1),
                             (["export", "x.sigil", "--mermaid", "--bogus"], 2)):
            with self.subTest(argv=argv):
                said = run(cli.main, argv)[stream]
                for form in forms:
                    self.assertIn(form, said)

    def test_no_old_script_names_in_help(self):
        for cmd in ("lint", "check", "view", "export"):
            with self.subTest(cmd=cmd):
                _code, out, _err = run(cli.main, [cmd, "--help"])
                for old in ("lint.py", "check.py", "render.py", "view.py", "export.py"):
                    self.assertNotIn(old, out)


class ExportWordsTest(unittest.TestCase):
    def test_a_foreign_folder_is_refused_by_sigil_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "mine.txt").write_text("x", encoding="utf-8")
            problem = exporter.out_problem(Path(tmp))
        self.assertIn("sigil export writes only into", problem)

    def test_index_readme_says_by_sigil_export(self):
        manifest = {"spec_hash": "0" * 16, "systems": {}}
        text = exporter.index_md("doc.sigil", manifest, {})
        self.assertIn("(spec hash `0000000000000000`) by sigil export.", text)
        self.assertNotIn("export.py", text)


class ThemesCommandTest(unittest.TestCase):
    def test_list_and_a_name_match_the_module(self):
        for argv in (["--list"], ["sigil"], []):
            with self.subTest(argv=argv):
                self.assertEqual(run(cli.main, ["themes", *argv]), run(themes.main, argv))

    def test_bad_input_says_sigil_themes(self):
        code, _out, err = run(cli.main, ["themes", "--bogus"])
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("usage: sigil themes "), err)
        code, _out, err = run(cli.main, ["themes", str(ROOT / "no-such.yaml")])
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("sigil themes: "), err)

    def test_usage_lists_themes(self):
        code, out, _err = run(cli.main, ["--help"])
        self.assertEqual(code, 0)
        self.assertIn("sigil themes [NAME|PATH] [--list]", out)


if __name__ == "__main__":
    unittest.main()
