"""Tests for the web page (site/) and its build.

Covers:
  - build_site.py output: pages with every {{placeholder}} filled, themes and
    their menu, theme.css, frames.json;
  - every example lints clean once fully typed, and a half-typed block still draws;
  - the page's colours all come from the theme: every var(--…) the CSS and the
    frames use is defined by theme.css or by site.css itself;
  - the YAML subset: tests/fixtures/yaml_cases.json (the contract written in
    themes.py's docstring) holds for themes.parse and, with node available, for
    site.js parseYaml; both parse every shipped theme identically;
  - with node available: site.js highlights Sigil into the theme's syntax roles.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import html
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]
SITE = _DIR / "site"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


site = _load("sigil_build_site_t", SITE / "build_site.py")
themes = _load("sigil_themes_site_t", _DIR / "themes.py")
YAML_CASES = json.loads((_DIR / "tests" / "fixtures" / "yaml_cases.json").read_text(encoding="utf-8"))
VAR_RE = re.compile(r"var\(--([\w-]+)")


class TestBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "_site"
        site.build(cls.out, "coin")
        cls.frames = json.loads((cls.out / "frames.json").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_outputs(self):
        for name in ("fonts/DepartureMono-Regular.woff2", "fonts/DepartureMono-OFL.txt",
                     "index.html", "site.css", "site.js", "theme.css", "frames.json",
                     "themes/index.yaml", "themes/sigil.yaml", ".nojekyll"):
            self.assertTrue((self.out / name).is_file(), name)

    def test_placeholders_filled_and_logos_embedded(self):
        page = (self.out / "index.html").read_text()
        self.assertNotIn("{{", page)
        for p in (SITE / "logos").glob("*.txt"):
            self.assertIn(f'data-logo="{p.stem}"', page)
        for p in (SITE / "logos").glob("*.mask"):
            self.assertIn(f'data-logo-mask="{p.stem}"', page)
            art = p.with_suffix(".txt").read_text().splitlines()
            mask = p.read_text().splitlines()
            self.assertLessEqual(len(mask), len(art))
            for a, m in zip(art, mask):            # accent cells sit on drawn characters
                self.assertTrue(all(c == " " or (i < len(a) and a[i] != " ")
                                    for i, c in enumerate(m)), p.name)

    def test_theme_menu_lists_sigil(self):
        index = themes.parse((self.out / "themes" / "index.yaml").read_text())
        self.assertEqual(index["themes"]["sigil"], "Sigil")

    def test_examples_lint_clean_when_typed(self):
        self.assertGreaterEqual(len(self.frames["examples"]), 3)
        for ex in self.frames["examples"]:
            with self.subTest(ex=ex["id"]):
                last = ex["steps"][-1]
                self.assertEqual(last["lint"], "OK")
                self.assertEqual(last["line"], len(ex["lines"]) - 1)
                self.assertGreater(last["nodes"], 2)

    def test_half_typed_block_still_draws(self):
        text = site.autoclose(["[Shop] := {", "  [Cart] -> [Pay]"])
        self.assertTrue(text.rstrip().endswith("}"))
        g = site.view.render.parse_document(text)
        self.assertIn("Shop_service", g.expansions)

    def _defined(self) -> set:
        theme = (self.out / "theme.css").read_text()
        own = (SITE / "site.css").read_text()
        decl = re.compile(r"(--[\w-]+)\s*:")
        return {m[2:] for m in decl.findall(theme) + decl.findall(own)}

    def test_css_colours_come_from_globals(self):
        defined = self._defined()
        used = set(VAR_RE.findall((SITE / "site.css").read_text()))
        # Variables set at runtime by site.js (scene state), not by a theme.
        runtime = {"x", "y", "z", "rx", "ry", "d", "focus-k", "delay", "dur"}
        self.assertEqual(used - defined - runtime, set())
        css = (SITE / "site.css").read_text()
        rules = re.sub(r":root\s*\{.*?\}", "", css, count=1, flags=re.S)
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,6}\b", rules), "a literal colour outside :root")

    def test_frame_roles_are_theme_variables(self):
        defined = self._defined()
        for fg, bg, _bold in self.frames["styles"]:
            for c in (fg, bg):
                if c:
                    self.assertIn(c.removeprefix("tint:").removeprefix("shade:"), defined, c)


    def test_symbols_outside_the_font_get_a_fixed_cell(self):
        # Departure Mono 1.500 lacks these viewer symbols (checked with fontTools);
        # site.js must wrap each in a 1ch fallback cell or frame columns drift.
        missing = "↺⇢∗▸▾◀◆◇◉○◎●✖✱"
        js = (SITE / "site.js").read_text()
        pattern = re.search(r"const FALLBACK = /\[(.*?)\]/g", js).group(1)
        for ch in missing:
            self.assertIn(ch, pattern)
        # index.html asks the fallback font for exactly these characters
        page = (SITE / "index.html").read_text(encoding="utf-8")
        url = re.search(r'href="(https://fonts\.googleapis\.com/css2\?[^"]+)"', page).group(1)
        text = urllib.parse.parse_qs(urllib.parse.urlsplit(html.unescape(url)).query)["text"][0]
        self.assertEqual(set(text), set(pattern))


class TestBuildGuards(unittest.TestCase):
    def test_refuses_to_wipe_sources_or_foreign_dirs(self):
        for bad in (_DIR, SITE, _DIR.parent):
            with self.subTest(out=bad), self.assertRaises(site.BuildError):
                site.check_out(bad)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "keep.txt").write_text("mine")
            with self.assertRaises(site.BuildError):
                site.check_out(Path(tmp))
            (Path(tmp) / ".nojekyll").write_text("")      # a previous build: fine
            self.assertEqual(site.check_out(Path(tmp)), Path(tmp).resolve())

    def test_unfilled_placeholder_fails(self):
        with self.assertRaises(site.BuildError):
            site.fill("<p>{{version}} {{nope}}</p>", {"{{version}}": "1"})

    def test_autoclose_counts_braces_structurally(self):
        def opened(lines):
            return site.autoclose(lines).count("\n") - len(lines)
        cases = [
            (["[A] := {"], 1),
            (["state {Order} {"], 1),
            (["[Handler] @owns |Conn| {"], 1),
            (["[A] := { [B] -> [C] }"], 0),
            (["[A] := {", "  state X {", "}}"], 0),
            (["[A] := {", "} @inv write-only-primary"], 0),
            (["[A] := {", "  \\-{shattered}-? [Shard]", "  {Order} -> [B]"], 1),
            (['[A] -> [B] : "{"   # {'], 0),
            (["}"], 0),
        ]
        for lines, want in cases:
            with self.subTest(lines=lines):
                self.assertEqual(opened(lines), want)


class TestYamlSubsetPython(unittest.TestCase):
    """themes.parse against the shared fixtures (site.js runs the same ones)."""

    def test_fixture_cases(self):
        self.assertGreaterEqual(len(YAML_CASES), 25)
        for case in YAML_CASES:
            with self.subTest(case=case["name"]):
                try:
                    got = themes.parse(case["text"], "fixture")
                except themes.ThemeError:
                    got = "error"
                self.assertEqual(got, case["expect"], f"themes.parse: {case['name']}")


class TestBanner(unittest.TestCase):
    def test_banner_is_current(self):
        """assets/banner.svg is what site/banner.py renders now (re-run it after
        changing the logo or the theme)."""
        banner = _load("sigil_banner_t", SITE / "banner.py")
        self.assertEqual(banner.banner("coin", "sigil"),
                         (_DIR / "assets" / "banner.svg").read_text(encoding="utf-8"))

    def test_banner_colours_match_the_page(self):
        banner = _load("sigil_banner_t2", SITE / "banner.py")
        css = (SITE / "site.css").read_text()
        for code in banner.code_colours(themes.load("sigil")):
            self.assertIn(f".logo .k-{code} ", css)


NODE = shutil.which("node")


def _js_section(start: str, end: str) -> str:
    src = (SITE / "site.js").read_text()
    return src[src.index(start):src.index(end)]


@unittest.skipUnless(NODE, "node not installed")
class TestSiteJs(unittest.TestCase):
    def _run(self, body: str) -> str:
        prelude = ('const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", '
                   '">": "&gt;", \'"\': "&quot;" })[c]);\n')
        res = subprocess.run([NODE, "-e", prelude + body], capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)
        return res.stdout

    YAML_JS = ("// ------------------------------------------------------------------ YAML subset",
               "// ------------------------------------------------------------------ themes")

    def _parse_all_js(self, texts: list) -> list:
        """parseYaml over each text: {"ok": result} or {"error": message}."""
        code = _js_section(*self.YAML_JS)
        body = (code + f"\nconst texts = {json.dumps(texts)};\n"
                "process.stdout.write(JSON.stringify(texts.map((t) => {"
                " try { return { ok: parseYaml(t, 'fixture') }; }"
                " catch (e) { return { error: String(e.message) }; } })));")
        return json.loads(self._run(body))

    def test_yaml_parser_fixture_cases(self):
        results = self._parse_all_js([c["text"] for c in YAML_CASES])
        for case, res in zip(YAML_CASES, results):
            with self.subTest(case=case["name"]):
                got = "error" if "error" in res else res["ok"]
                self.assertEqual(got, case["expect"], f"site.js parseYaml: {case['name']}")

    def test_yaml_parser_matches_python_on_themes(self):
        paths = sorted((_DIR / "themes").glob("*.yaml"))
        results = self._parse_all_js([p.read_text(encoding="utf-8") for p in paths])
        for path, res in zip(paths, results):
            with self.subTest(theme=path.name):
                self.assertNotIn("error", res)
                self.assertEqual(res["ok"], themes.parse(path.read_text(encoding="utf-8")))

    def test_highlighter_roles(self):
        code = _js_section("const RULES", "// ------------------------------------------------------------------ frames")
        lines = ["(User) -> [API] : charge(total) ×3 @timeout(2s)   # note",
                 "[Ship]", "    \\-*-> [Bullet]", "  Open  -<Paid>->  Settled", "#!sketch", "--- arena ---"]
        out = json.loads(self._run(code + f"\nprocess.stdout.write(JSON.stringify({json.dumps(lines)}.map(highlight)));"))
        first = out[0]
        for cls in ("t-glyph", "t-name", "t-operator", "t-modifier", "t-cardinality", "t-comment"):
            self.assertIn(cls, first)
        self.assertNotIn('<span class="t-name">total</span>', first)    # op-call args are not a glyph
        self.assertIn('<span class="t-branch">\\-*-&gt;</span>', out[2])
        self.assertIn('<span class="t-name">Paid</span>', out[3])
        self.assertIn("t-shebang", out[4])
        self.assertIn('<span class="t-section">arena</span>', out[5])


if __name__ == "__main__":
    unittest.main()
