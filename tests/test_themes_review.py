"""Regression tests for the review of themes.py and dialects.py.

Covers:
  - themes.parse: escaped double quotes, '' in single-quoted keys and values,
    line splitting on "\\n" only, a leading BOM, non-space indentation, the
    top-level indentation message, unterminated single quotes;
  - themes.resolve: malformed palettes raise ThemeError, never a crash;
  - themes extends: path values relative to the theme's folder, map values
    rejected, a BOM-prefixed `extends`;
  - themes CLI: --help, extra arguments, unreadable files; names() skipping
    index.yaml and non-YAML suffixes; find() treating "a/b" as a path;
  - dialects: modules registered in sys.modules (dataclasses work, a failed
    load leaves nothing behind), one module per file across separate copies of
    dialects.py, "sigil-" prefixed names, path-like names rejected, distinct
    modules for names that differ only in punctuation, the CLI exit code.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
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


themes = _load("sigil_themes_review", "themes.py")
dialects = _load("sigil_dialects_review", "dialects.py")


def _run(main, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class _EnvCase(unittest.TestCase):
    """A temp dir, with chosen env vars restored afterwards."""
    ENV: tuple[str, ...] = ()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.saved = {k: os.environ.get(k) for k in self.ENV}

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()


# ---------------------------------------------------------------------------
# themes.parse
# ---------------------------------------------------------------------------

class TestParseQuotes(unittest.TestCase):
    def test_escaped_double_quote_does_not_end_the_string(self):      # item 10
        self.assertEqual(themes.parse('a: "x\\" # y"\n'), {"a": 'x" # y'})
        self.assertEqual(themes.parse('a: "x\\\\" # c\n'), {"a": "x\\"})

    def test_doubled_single_quote_then_hash(self):                     # item 11
        self.assertEqual(themes.parse("a: 'it''s # here'\n"), {"a": "it's # here"})
        self.assertEqual(themes.parse("a: 'it''s' # c\n"), {"a": "it's"})

    def test_doubled_single_quote_in_a_key(self):                      # item 11
        self.assertEqual(themes.parse("'a'': b': v\n"), {"a': b": "v"})

    def test_single_quotes_must_close_cleanly(self):
        for doc in ("a: 'abc''\n", "a: 'abc\n", "a: 'x' y'\n", "a: \"x\n"):
            with self.subTest(doc=doc), self.assertRaises(themes.ThemeError):
                themes.parse(doc)

    def test_empty_key(self):
        with self.assertRaises(themes.ThemeError):
            themes.parse("'': v\n")


class TestParseLines(unittest.TestCase):
    def test_only_newline_splits_lines(self):                          # item 14
        for sep in ("\x0c", "\x0b", "\x85", "\u2028", "\u2029", "\x1e"):
            with self.subTest(sep=repr(sep)):
                self.assertEqual(themes.parse(f"a: x{sep}y\n"), {"a": f"x{sep}y"})

    def test_crlf_is_a_newline(self):
        self.assertEqual(themes.parse("a:\r\n  b: 1\r\nc: 2\r\n"),
                         {"a": {"b": "1"}, "c": "2"})

    def test_leading_bom_is_ignored(self):                             # item 15
        self.assertEqual(themes.parse("\ufeffextends: x\n"), {"extends": "x"})

    def test_non_space_indentation_is_an_error(self):                  # item 21
        for doc in ("a:\n\u00a0 b: 1\n", "a:\n \u00a0b: 1\n", "a:\n \tb: 1\n",
                    "a:\n\x0cb: 1\n"):
            with self.subTest(doc=repr(doc)), self.assertRaises(themes.ThemeError) as cm:
                themes.parse(doc)
            self.assertIn("spaces", str(cm.exception))

    def test_blank_and_comment_lines_with_tabs_are_skipped(self):
        self.assertEqual(themes.parse("a: 1\n\t\n\t# note\nb: 2\n"), {"a": "1", "b": "2"})

    def test_indentation_messages(self):                               # item 20
        with self.assertRaisesRegex(themes.ThemeError, "column 0"):
            themes.parse("  a: 1\n")
        with self.assertRaisesRegex(themes.ThemeError, "inconsistent"):
            themes.parse("a:\n    b: 1\n  c: 2\n")
        with self.assertRaisesRegex(themes.ThemeError, "inconsistent"):
            themes.parse("a:\n  b: 1\n    c: 2\n")

    def test_key_without_children_is_empty(self):                      # item 19
        self.assertEqual(themes.parse("a:\nb:\n  c: 1\nd:\n"),
                         {"a": "", "b": {"c": "1"}, "d": ""})


# ---------------------------------------------------------------------------
# themes.resolve / extends / CLI
# ---------------------------------------------------------------------------

class TestResolveMalformed(unittest.TestCase):                         # item 16
    def test_palette_entry_that_is_a_map(self):
        doc = "palette:\n  x:\n    y: '#000000'\nui:\n  a: $x\n"
        with self.assertRaises(themes.ThemeError):
            themes.resolve(themes.parse(doc))

    def test_palette_that_is_a_string(self):
        with self.assertRaises(themes.ThemeError):
            themes.resolve(themes.parse("palette: abc\nui:\n  a: $b\n"))

    def test_unreferenced_nested_palette_is_fine(self):
        doc = "palette:\n  x:\n    y: '#000000'\nui:\n  a: plain\n"
        self.assertEqual(themes.resolve(themes.parse(doc))["ui"]["a"], "plain")


class TestExtends(_EnvCase):                                           # item 18
    ENV = ("SIGIL_THEME_PATH",)

    def test_path_is_relative_to_the_theme_folder(self):
        sub = self.dir / "sub"
        sub.mkdir()
        (sub / "base.yaml").write_text("palette:\n  a: '#111111'\nui:\n  x: $a\n")
        (self.dir / "child.yaml").write_text("extends: sub/base.yaml\nui:\n  y: $a\n")
        old = os.getcwd()
        try:
            os.chdir(tempfile.gettempdir())
            t = themes.load(str(self.dir / "child.yaml"))
        finally:
            os.chdir(old)
        self.assertEqual(t["ui"], {"x": "#111111", "y": "#111111"})

    def test_sibling_file_by_plain_filename(self):
        (self.dir / "base.yaml").write_text("palette:\n  a: '#222222'\n")
        (self.dir / "child.yaml").write_text("extends: base.yaml\n")
        self.assertEqual(themes.load(str(self.dir / "child.yaml"))["palette"]["a"], "#222222")

    def test_extends_as_a_map_is_an_error(self):
        (self.dir / "child.yaml").write_text("extends:\n  name: sigil\n")
        with self.assertRaises(themes.ThemeError):
            themes.load(str(self.dir / "child.yaml"))

    def test_bom_file_still_extends(self):                             # item 15
        (self.dir / "base.yaml").write_text("palette:\n  a: '#333333'\n")
        (self.dir / "child.yaml").write_text("\ufeffextends: base.yaml\n", encoding="utf-8")
        self.assertEqual(themes.load(str(self.dir / "child.yaml"))["palette"]["a"], "#333333")

    def test_extends_cycle(self):
        (self.dir / "a.yaml").write_text("extends: b.yaml\n")
        (self.dir / "b.yaml").write_text("extends: ./a.yaml\n")
        with self.assertRaisesRegex(themes.ThemeError, "cycle"):
            themes.load(str(self.dir / "a.yaml"))


class TestLookupAndCli(_EnvCase):
    ENV = ("SIGIL_THEME_PATH", "SIGIL_THEME")

    def setUp(self):
        super().setUp()
        os.environ["SIGIL_THEME_PATH"] = str(self.dir)
        os.environ.pop("SIGIL_THEME", None)

    def test_names_skip_index_and_odd_suffixes(self):                 # item 24
        for f in ("index.yaml", "odd.yxml", "alpha.yml", "beta.yaml"):
            (self.dir / f).write_text("a: 1\n")
        found = themes.names()
        self.assertIn("alpha", found)
        self.assertIn("beta", found)
        self.assertNotIn("index", found)
        self.assertNotIn("odd", found)

    def test_slash_means_a_path(self):                                 # item 25
        with self.assertRaisesRegex(themes.ThemeError, "not found"):
            themes.find("nowhere/thing")

    def test_help_and_extra_args(self):                                # item 23
        code, out, _ = _run(themes.main, ["--help"])
        self.assertEqual(code, 0)
        self.assertIn("--list", out)
        code, _, err = _run(themes.main, ["sigil", "extra"])
        self.assertEqual(code, 2)
        self.assertIn("usage", err)
        code, _, err = _run(themes.main, ["--bogus"])
        self.assertEqual(code, 2)

    def test_unreadable_files_are_reported(self):                     # item 23
        bad = self.dir / "bad.yaml"
        bad.write_bytes(b"a: \xff\xfe\n")
        code, _, err = _run(themes.main, [str(bad)])
        self.assertEqual(code, 2)
        self.assertIn("themes.py:", err)
        with self.assertRaises(themes.ThemeError):
            themes.load(str(bad))

    def test_list_still_works(self):
        (self.dir / "gamma.yaml").write_text("a: 1\n")
        code, out, _ = _run(themes.main, ["--list"])
        self.assertEqual(code, 0)
        self.assertIn("gamma", out.split())


# ---------------------------------------------------------------------------
# dialects
# ---------------------------------------------------------------------------

_DATACLASS_DIALECT = """\
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class Site:
    line_no: int
    value: str = ""

KNOWN_MODIFIERS = {"@demo"}
"""


class TestDialects(_EnvCase):
    ENV = ("SIGIL_DIALECT_PATH", "SIGIL_DIALECT")

    def _dialect(self, folder: str, body: str = "KNOWN_MODIFIERS = set()\n") -> Path:
        d = self.dir / folder
        d.mkdir(parents=True, exist_ok=True)
        (d / "dialect.py").write_text(body)
        return d

    def test_dataclass_dialect_loads(self):                            # item 1
        d = self._dialect("sigil-dc", _DATACLASS_DIALECT)
        mod = dialects.load(str(d))
        self.assertEqual(mod.Site(3).line_no, 3)
        self.assertEqual(mod.NAME, "dc")
        self.assertIs(sys.modules[mod.__name__], mod)

    def test_failed_load_is_not_left_registered(self):                # item 1
        d = self._dialect("sigil-broken", "raise RuntimeError('boom')\n")
        before = set(sys.modules)
        with self.assertRaises(RuntimeError):
            dialects.load(str(d))
        self.assertEqual({m for m in set(sys.modules) - before
                          if m.startswith("sigil_dialect_")}, set())

    def test_one_module_across_copies_of_dialects(self):              # item 2
        d = self._dialect("sigil-shared")
        other = _load("sigil_dialects_review_copy", "dialects.py")
        self.assertIsNot(other, dialects)
        self.assertIs(dialects.load(str(d)), other.load(str(d / "dialect.py")))

    def test_sigil_prefixed_name(self):                                # item 5
        self._dialect("sigil-demo")
        os.environ["SIGIL_DIALECT_PATH"] = str(self.dir)
        a = dialects.load("sigil-demo")
        b = dialects.load("demo")
        self.assertIs(a, b)
        self.assertEqual(a.NAME, "demo")

    def test_path_like_names_are_rejected(self):                      # item 5
        # <path dir>/../x/dialect.py exists: a name must not reach it.
        (self.dir / "inner").mkdir()
        os.environ["SIGIL_DIALECT_PATH"] = str(self.dir / "inner")
        self._dialect("x")
        for spec in ("../x", "sigil-../x", "a/b", ".."):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                dialects.load(spec)

    def test_names_differing_in_punctuation_stay_distinct(self):      # item 9
        a = self._dialect("sigil-a-b", "WHICH = 'dash'\n")
        b = self._dialect("sigil-a_b", "WHICH = 'underscore'\n")
        ma, mb = dialects.load(str(a)), dialects.load(str(b))
        self.assertIsNot(ma, mb)
        self.assertEqual((ma.WHICH, mb.WHICH), ("dash", "underscore"))

    def test_cli_unknown_dialect_exits_2(self):                        # item 6
        os.environ["SIGIL_DIALECT_PATH"] = str(self.dir)
        code, _, err = _run(dialects.main, ["no-such-dialect-here"])
        self.assertEqual(code, 2)
        self.assertIn("unknown sigil dialect", err)
        os.environ.pop("SIGIL_DIALECT", None)
        code, out, _ = _run(dialects.main, [])
        self.assertEqual(code, 0)
        self.assertIn("no dialect", out)

    def test_hook_helper_is_gone(self):                                # item 4
        self.assertFalse(hasattr(dialects, "hook"))


if __name__ == "__main__":
    unittest.main()
