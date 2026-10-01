"""Tests for themes.py and the viewer's theming.

Covers:
  - the YAML subset: nesting, comments, quoting, and the errors it reports;
  - $palette references, `extends`, lookup by name / path / SIGIL_THEME_PATH;
  - view.py applying a theme: box, edge and chrome colours come from it, each
    tagged with its role; --theme on the command line.

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


themes = _load("sigil_themes_t", "themes.py")
view = _load("sigil_view_t", "view.py")


class TestYamlSubset(unittest.TestCase):
    def test_nested_maps_comments_and_quotes(self):
        doc = ('# a theme\nname: x   # trailing\npalette:\n  bg: "#000000"\n'
               "  fg: '#ffffff'\nui:\n  inner:\n    deep: yes\n  text: $fg\n")
        self.assertEqual(themes.parse(doc), {
            "name": "x",
            "palette": {"bg": "#000000", "fg": "#ffffff"},
            "ui": {"inner": {"deep": "yes"}, "text": "$fg"},
        })

    def test_unquoted_hash_value_is_a_comment(self):
        self.assertEqual(themes.parse("a: #abc\n"), {"a": ""})

    def test_quoted_key(self):
        self.assertEqual(themes.parse('"!>": red\n'), {"!>": "red"})

    def test_errors(self):
        for doc in ("a:\n\tb: 1\n", "a:\n  - 1\n", "a: 1\n  b: 2\n", "a: 1\na: 2\n",
                    "just words\n", "  a: 1\n"):
            with self.subTest(doc=doc), self.assertRaises(themes.ThemeError):
                themes.parse(doc)


class TestResolve(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.env = os.environ.get("SIGIL_THEME_PATH")
        os.environ["SIGIL_THEME_PATH"] = str(self.dir)

    def tearDown(self):
        if self.env is None:
            os.environ.pop("SIGIL_THEME_PATH", None)
        else:
            os.environ["SIGIL_THEME_PATH"] = self.env
        self.tmp.cleanup()

    def test_refs_resolve_through_the_palette(self):
        t = themes.resolve(themes.parse('palette:\n  a: "#111111"\n  b: $a\nui:\n  x: $b\n'))
        self.assertEqual(t["ui"]["x"], "#111111")

    def test_unknown_ref_and_cycle(self):
        with self.assertRaises(themes.ThemeError):
            themes.resolve(themes.parse("ui:\n  x: $nope\n"))
        with self.assertRaises(themes.ThemeError):
            themes.resolve(themes.parse("palette:\n  a: $b\n  b: $a\nui:\n  x: $a\n"))

    def test_extends_overrides_only_what_it_names(self):
        (self.dir / "loud.yaml").write_text('extends: sigil\nname: loud\npalette:\n  magenta: "#ff00ff"\n')
        base, loud = themes.load("sigil"), themes.load("loud")
        self.assertEqual(loud["syntax"]["glyph"], "#ff00ff")          # follows the palette
        self.assertEqual(loud["kinds"], base["kinds"])                 # untouched
        self.assertIn("loud", themes.names())

    def test_load_by_path_and_unknown_name(self):
        p = self.dir / "mine.yaml"
        p.write_text('palette:\n  bg: "#000000"\n')
        self.assertEqual(themes.load(str(p))["palette"]["bg"], "#000000")
        with self.assertRaises(themes.ThemeError):
            themes.load("no-such-theme")

    def test_sigil_theme_covers_every_role(self):
        t = themes.load("sigil")
        for section in ("palette", "kinds", "edges", "syntax", "ui", "site"):
            self.assertIn(section, t)
        for kind in view.CORE_KINDS:
            self.assertTrue(t["kinds"][kind].startswith("#"), kind)


class TestViewTheme(unittest.TestCase):
    def tearDown(self):
        view.use_theme("sigil")
        view.use_dialect(None)

    def test_colours_come_from_the_theme_with_roles(self):
        view.use_theme("sigil")
        t = themes.load("sigil")
        svc = view.CORE_KINDS["service"]["color"]
        self.assertEqual(svc, t["kinds"]["service"])
        self.assertEqual(svc.role, "kinds-service")
        self.assertEqual(view.EDGE_COLOR["!>"].role, "edges-fail")
        self.assertEqual(view.BAR_STYLE[1], t["ui"]["bar_bg"])
        self.assertEqual(view._tint(svc).role, "tint:kinds-service")

    def test_custom_theme_recolours_boxes(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write('extends: sigil\nkinds:\n  service: "#123456"\n')
        try:
            view.use_theme(f.name)
            self.assertEqual(view.CORE_KINDS["service"]["color"], "#123456")
            self.assertEqual(view.node_styles(view.render.Node(id="a", name="A", kind="service"))[0][0],
                             "#123456")
        finally:
            Path(f.name).unlink()

    def test_theme_colours_dialect_kinds_by_name(self):
        class Fake:
            NODE_KINDS = {"widget": {"open": "<<", "close": ">>", "color": "#000001"}}
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write('extends: sigil\nkinds:\n  widget: "#abcdef"\n')
        try:
            view.use_theme(f.name)
            view.use_dialect(Fake)
            self.assertEqual(view.KINDS["widget"]["color"], "#abcdef")
            self.assertEqual(Fake.NODE_KINDS["widget"]["color"], "#000001")   # not mutated
        finally:
            Path(f.name).unlink()

    def _main(self, *args):
        with tempfile.NamedTemporaryFile("w", suffix=".sigil", delete=False) as f:
            f.write("[A] -> [B]\n")
        argv, sys.argv = sys.argv, ["view.py", f.name, "--once", "--no-lint", *args]
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                status = view.main()
        finally:
            sys.argv = argv
            Path(f.name).unlink()
        return status, out.getvalue(), err.getvalue()

    def test_cli_theme_flag(self):
        status, out, _ = self._main("--theme", "sigil", "--color", "always")
        self.assertEqual(status, 0)
        r, g, b = (int(themes.load("sigil")["kinds"]["service"][i:i + 2], 16) for i in (1, 3, 5))
        self.assertIn(f"38;2;{r};{g};{b}", out)
        status, _, err = self._main("--theme", "no-such-theme")
        self.assertEqual(status, 2)
        self.assertIn("unknown theme", err)


if __name__ == "__main__":
    unittest.main()
