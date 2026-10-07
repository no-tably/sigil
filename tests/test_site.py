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
  - with node available: site.js highlights Sigil into the theme's syntax roles;
  - the playground: py/ holds the repo's tools byte for byte (the browser runs
    them, never a port) including check.py and every rule module, the manifest
    is complete (playground.py runs from py/ alone, in a fresh interpreter), what
    it draws is what view.py draws, and its findings on every bundled example
    are what check.py finds at k = 1;
  - with node available: the findings panel's list items (findingsHtml).

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
                    self.assertIn(re.sub(r"^(tint|muted|trail|faint):", "", c), defined, c)
        self.assertLessEqual({"ui-sim-trail", "ui-sim-faint", "ui-fill"}, defined)


    def test_playground_ships_the_tools_verbatim(self):
        man = json.loads((self.out / "py" / "manifest.json").read_text())
        self.assertEqual(man["files"], site.PY_TOOLS + site.PY_SITE)
        for name in site.PY_TOOLS:
            self.assertEqual((self.out / "py" / name).read_bytes(), (_DIR / name).read_bytes(), name)
        for name in site.PY_SITE:
            self.assertEqual((self.out / "py" / name).read_bytes(), (SITE / name).read_bytes(), name)
        for t in man["themes"]:
            self.assertTrue((self.out / "themes" / t).is_file(), t)

    def test_playground_ships_every_check_module(self):
        check = _load("sigil_check_site_t", _DIR / "check.py")
        for name in ("check.py", "dialects.py") + check.RULE_MODULES:
            self.assertIn(name, site.PY_TOOLS, name)

    def _manifest_dir(self, tmp: str) -> Path:
        """The browser's file system: py/* and themes/* in one directory, nothing else."""
        man = json.loads((self.out / "py" / "manifest.json").read_text())
        (Path(tmp) / "themes").mkdir()
        for f in man["files"]:
            shutil.copyfile(self.out / "py" / f, Path(tmp) / f)
        for f in man["themes"]:
            shutil.copyfile(self.out / "themes" / f, Path(tmp) / "themes" / f)
        return Path(tmp)

    def test_playground_checks_the_bundled_examples(self):
        examples = sorted((SITE / "examples").glob("*.sigil"))
        modes = [None, "craft", "spec"]
        texts = [p.read_text(encoding="utf-8") for p in examples]
        code = ("import json, sys; sys.path.insert(0, '.'); import playground as p\n"
                "texts, modes = json.loads(sys.stdin.read())\n"
                "print(json.dumps([[json.loads(p.check(json.dumps({'text': t, 'mode': m})))"
                " for m in modes] for t in texts]))")
        with tempfile.TemporaryDirectory() as tmp:
            run = subprocess.run([sys.executable, "-I", "-c", code], cwd=self._manifest_dir(tmp),
                                 input=json.dumps([texts, modes]), capture_output=True,
                                 text=True, timeout=300)
        self.assertEqual(run.returncode, 0, run.stderr)
        got = json.loads(run.stdout)
        check = _load("sigil_check_site_t2", _DIR / "check.py")
        asked = 0
        for path, text, per_mode in zip(examples, texts, got):
            for mode, r in zip(modes, per_mode):
                with self.subTest(example=path.name, mode=mode):
                    self.assertNotIn("error", r)
                    self.assertEqual(r["k"], 1)
                    want = check.check(text, mode=mode, k=1)
                    self.assertEqual(r["mode"], want.mode)
                    self.assertEqual([(f["line"], f["rule"], f["severity"], f["message"])
                                      for f in r["findings"]],
                                     [(f.line, f.rule.id, f.severity, f.message)
                                      for f in want.shown])
                    self.assertEqual(r["hidden"], len(want.findings) - len(want.shown))
                    asked += len(r["findings"])
        self.assertGreater(asked, 0, "no example raised a finding in craft or spec")

    def test_playground_check_reports_a_bad_mode(self):
        pg = _load("sigil_playground_t2", SITE / "playground.py")
        r = json.loads(pg.check(json.dumps({"text": "[A] -> [B]", "mode": "strict"})))
        self.assertIn("unknown mode", r["error"])

    def test_playground_runs_from_the_manifest_alone(self):
        # The browser's file system: py/* and themes/* in one directory, nothing else.
        with tempfile.TemporaryDirectory() as tmp:
            self._manifest_dir(tmp)
            text = (SITE / "examples" / "01-checkout.sigil").read_text()
            code = ("import json, sys; sys.path.insert(0, '.'); import playground as p\n"
                    "t = sys.stdin.read()\n"
                    "d = json.loads(p.draw(json.dumps({'text': t, 'view': 'graph'})))\n"
                    "n = d['scenarios'][-1]['name']\n"
                    "s = json.loads(p.sim(json.dumps({'text': t, 'scenario': n, 'frame': 10**6})))\n"
                    "print(json.dumps([len(d['rows']), n, s['outcome'], sorted(sys.modules)]))")
            run = subprocess.run([sys.executable, "-I", "-c", code], cwd=tmp, input=text,
                                 capture_output=True, text=True, timeout=120)
            self.assertEqual(run.returncode, 0, run.stderr)
            rows, name, outcome, mods = json.loads(run.stdout)
            self.assertGreater(rows, 5)
            self.assertEqual(name, "API.charge:fails")
            self.assertEqual(outcome, "failed")
            self.assertNotIn("termios", mods)          # no terminal in a browser

    def test_playground_draws_what_view_draws(self):
        pg = _load("sigil_playground_t", SITE / "playground.py")
        view = pg.view
        text = (SITE / "examples" / "04-orders.sigil").read_text()
        g = view.render.parse_document(text)
        for tree in (True, False):
            with self.subTest(tree=tree):
                got = json.loads(pg.draw(json.dumps({"text": text,
                                                     "view": "tree" if tree else "graph"})))
                rows, _w = view.compose_view(
                    g, tree, depth=pg.MAX_DEPTH, payloads=True,
                    notes="callouts" if tree else "markers", triggers=True, spaced=True,
                    width=None, access=False, mods=False,
                    events=view.DEFAULT_EVENTS[view.view_name(tree)])
                want = ["".join(t for t, _s in r).rstrip() for r in rows]
                drawn = ["".join(t for t, _s in r).rstrip() for r in got["rows"]]
                while want and not want[-1]:
                    want.pop()
                self.assertEqual(drawn, want)

    def test_playground_sim_narrates_as_the_viewer_does(self):
        """sim() carries the viewer's wording: "say" (the narration line), "story"
        (the beats so far), "beats" (where stepping by event stops), "trail"."""
        pg = _load("sigil_playground_t3", SITE / "playground.py")
        view = pg.view
        text = (SITE / "examples" / "01-checkout.sigil").read_text()
        player = view.SimPlayer(view.render.parse_document(text), "API.charge:fails")
        player.at = 12
        got = json.loads(pg.sim(json.dumps({"text": text, "view": "graph",
                                            "scenario": "API.charge:fails", "frame": 12})))
        self.assertEqual(got["say"], player.narration())
        self.assertIn("attempt 2 of 4", got["say"])
        self.assertEqual(got["story"], [view.beat_line(b) for b in player.told()])
        self.assertEqual(got["beats"], [b.frame for b in player.beats])
        self.assertEqual(got["trail"], "(Shopper) -> [API] -> [Payments] ×2")

    def test_symbols_outside_the_font_get_a_fixed_cell(self):
        # Departure Mono 1.500 lacks these viewer and simulation symbols (fontTools);
        # site.js must wrap each in a 1ch fallback cell or frame columns drift.
        missing = "↺↻⇱↩⇢∗∥⊘▶▸▾◀◆◇◉○◎●✕✖✱"
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

    def test_frame_role_css(self):
        """A frame colour role and the roles derived from it (a box fill, a muted
        name, a run's trail and never-taken wires) as CSS over the theme's variables."""
        code = _js_section("  function roleCss", "  function installFrameStyles")
        roles = ["kinds-service", "tint:kinds-service", "muted:kinds-service",
                 "trail:kinds-service", "faint:kinds-service", "#123456", "bogus:x y"]
        out = json.loads(self._run(code + f"\nprocess.stdout.write(JSON.stringify("
                                   f"{json.dumps(roles)}.map(roleCss)));"))
        self.assertEqual(out[0], "var(--kinds-service)")
        self.assertIn("var(--ui-fill)", out[1])
        self.assertIn("var(--ui-name-saturation)", out[2])
        self.assertIn("var(--ui-sim-trail)", out[3])
        self.assertIn("var(--ui-sim-faint)", out[4])
        self.assertIn("var(--ui-name-saturation)", out[4])     # faint fades the muted colour
        self.assertEqual(out[5], "#123456")
        self.assertIsNone(out[6])

    def test_findings_panel_items(self):
        code = _js_section("  function findingsHtml", "  function initPlayground")
        found = [{"severity": "warn", "line": 11, "rule": "SGC104", "name": "retry-without-backoff",
                  "message": "`f` retries ×3 <at once>?", "why": "a storm"}]
        accepted = [{"severity": "warn", "line": 4, "rule": "SGC101", "name": "call-without-timeout",
                     "message": "unused", "why": "", "acknowledged": "an upsert"}]
        out = self._run(code + f"\nprocess.stdout.write(findingsHtml({json.dumps(found)}, "
                        f"{json.dumps(accepted)}));")
        self.assertIn('<li class="warn"><button type="button" data-line="11">warn:11:SGC104</button>', out)
        self.assertIn("retry-without-backoff: `f` retries ×3 &lt;at once&gt;?", out)
        self.assertIn('<span class="pg-why">a storm</span>', out)
        self.assertIn('<li class="accepted"><button type="button" data-line="4">accepted:4:SGC101'
                      '</button> call-without-timeout: an upsert</li>', out)

    def test_playground_speed_steps(self):
        # the terminal viewer's - / + steps, a readable start, a remembered choice
        code = _js_section("  // Run speeds in frames a second", "  // The findings panel's")
        out = json.loads(self._run(code + "\nprocess.stdout.write(JSON.stringify({"
                                   " speeds: SIM_SPEEDS, start: SIM_SPEEDS[SIM_SPEED],"
                                   " labels: SIM_SPEEDS.map(speedLabel),"
                                   " picks: [null, '0', '7', '8', '-1', '2.5', 'fast', ''].map(speedIndex) }));"))
        view = _load("sigil_view_speeds", _DIR / "view.py")
        self.assertLessEqual(set(view.SIM_SPEEDS), set(out["speeds"]))
        self.assertEqual(out["speeds"], sorted(out["speeds"]))
        self.assertEqual(out["start"], 2)
        self.assertEqual(out["labels"], ["¼/s", "½/s", "1/s", "2/s", "4/s", "8/s", "16/s", "32/s"])
        self.assertEqual(out["picks"], [3, 0, 7, 3, 3, 3, 3, 3])

    def test_playground_speed_control_markup(self):
        page = (SITE / "index.html").read_text(encoding="utf-8")
        self.assertRegex(page, r'<select id="pg-speed" aria-label="[^"]+"')
        for btn in ("pg-back", "pg-play", "pg-fwd"):
            self.assertIn(f'id="{btn}"', page)
        js = (SITE / "site.js").read_text()
        self.assertIn('speed: $("#pg-speed")', js)
        self.assertNotIn("localStorage.setItem(SPEED_KEY", js)   # through the try/catch store


if __name__ == "__main__":
    unittest.main()
