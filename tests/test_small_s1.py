"""patch-0.6.12 S1: small leftovers of the 0.6.11 hardening.

- (a) the site's theme reader (site.js) keeps themes.py's limits: maps nested
      more than MAX_DEPTH deep, an `extends` chain of more than MAX_EXTENDS
      themes, a file over MAX_BYTES or not UTF-8 are errors; a colour that is
      not #rrggbb / #rgb, a fraction outside 0..1, an unknown section or role
      sets no CSS variable (the page keeps sigil's own value), as
      themes.problems reads a theme;
- (b) a `highlight --stream` request line over MAX_REQUEST_CHARS is an error
      answer and the session goes on;
- (c) Mermaid draws a body-less shape (`{Doc} := { }`, or one of fields only)
      as a node, not as an empty subgraph;
- (e) the site's skill cards name `sigil highlight`.

Run:  python3 -m unittest tests.test_small_s1
"""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigil.present import highlight, themes  # noqa: E402
from sigil.publish import mermaid  # noqa: E402

SITE = ROOT / "site"
NODE = shutil.which("node")


def _js_section(start: str, end: str) -> str:
    src = (SITE / "site.js").read_text(encoding="utf-8")
    return src[src.index(start):src.index(end)]


YAML_THEMES_JS = ("  // ------------------------------------------------------------------ YAML subset",
                  "  // ------------------------------------------------------------------ logo")


def nested(levels: int) -> str:
    """A theme of `levels` maps, each two spaces deeper than the last."""
    return "".join(f"{'  ' * k}k{k}:\n" for k in range(levels)) + f"{'  ' * levels}v: x\n"


@unittest.skipUnless(NODE, "node not installed")
class SiteThemeLimits(unittest.TestCase):
    """(a)"""

    def node(self, body: str):
        """Run `body` after site.js's YAML and themes sections, with a fetch that
        serves FILES (name -> text) under themes/; its stdout as JSON."""
        prelude = "const document = { documentElement: { style: {}, dataset: {} } };\n"
        code = prelude + _js_section(*YAML_THEMES_JS) + "\n" + body
        res = subprocess.run([NODE, "-"], input=code, capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(res.stdout)

    def fetching(self, files: dict, expr: str):
        """`expr` (an async expression) with fetch serving `files`: {"ok": value} or
        {"error": message}."""
        body = (f"const FILES = {json.dumps(files)};\n"
                "globalThis.fetch = async (url) => {\n"
                "  const name = decodeURIComponent(url.replace(/^themes\\//, ''));\n"
                "  const text = FILES[name];\n"
                "  return text === undefined ? { ok: false, status: 404 } : {\n"
                "    ok: true, status: 200,\n"
                "    text: async () => text,\n"
                "    arrayBuffer: async () => new TextEncoder().encode(text).buffer };\n"
                "};\n"
                f"(async () => {{ try {{ process.stdout.write(JSON.stringify({{ ok: await ({expr}) }})); }}\n"
                "  catch (e) { process.stdout.write(JSON.stringify({ error: String(e.message) })); } })();")
        return self.node(body)

    def test_depth_limit_matches_python(self):
        for levels in (themes.MAX_DEPTH, themes.MAX_DEPTH + 1):
            text = nested(levels)
            try:
                want = themes.parse(text, "fixture")
            except themes.ThemeError as exc:
                want = {"error": str(exc).split(": ", 1)[1]}
            got = self.node(f"try {{ process.stdout.write(JSON.stringify(parseYaml({json.dumps(text)}, 'fixture'))); }}"
                            " catch (e) { process.stdout.write(JSON.stringify({ error: e.message.split(': ').slice(1).join(': ') })); }")
            with self.subTest(levels=levels):
                self.assertEqual(got, want)
        self.assertIn("nested more than 16 deep", got["error"])

    def test_extends_chain_is_capped(self):
        def chain(n):
            files = {f"link{k}.yaml": f"name: link{k}\nextends: link{k + 1}\n" for k in range(n - 1)}
            files[f"link{n - 1}.yaml"] = f"name: link{n - 1}\n"
            return files
        ok = self.fetching(chain(themes.MAX_EXTENDS), "loadThemeRaw('link0')")
        self.assertEqual(ok, {"ok": {"name": "link0"}})
        bad = self.fetching(chain(themes.MAX_EXTENDS + 1), "loadThemeRaw('link0')")
        self.assertIn(f"an extends chain longer than {themes.MAX_EXTENDS} themes", bad["error"])

    def test_a_large_theme_is_refused(self):
        big = "name: big\n" + "# " + "x" * themes.MAX_BYTES + "\n"
        bad = self.fetching({"big.yaml": big}, "loadThemeRaw('big')")
        self.assertIn(f"larger than {themes.MAX_BYTES} bytes", bad["error"])

    def test_extends_map_is_an_error(self):
        bad = self.fetching({"m.yaml": "extends:\n  a: b\n"}, "loadThemeRaw('m')")
        self.assertIn("extends must be a theme name", bad["error"])

    def test_palette_errors_match_python(self):
        for text, words in (("palette:\n  a: $b\n  b: $a\n", "palette cycle"),
                            ("palette:\n  a: '#fff'\nui:\n  text: $nope\n", "unknown palette colour"),
                            ("palette: x\n", "palette must be a map")):
            with self.subTest(text=text):
                with self.assertRaises(themes.ThemeError) as py:
                    themes.resolve(themes.parse(text))
                self.assertIn(words, str(py.exception))
                got = self.node(f"try {{ resolveTheme(parseYaml({json.dumps(text)}), 't'); process.stdout.write('{{}}'); }}"
                                " catch (e) { process.stdout.write(JSON.stringify({ error: e.message })); }")
                self.assertIn(words, got.get("error", ""))

    def test_only_what_sigil_reads_becomes_a_variable(self):
        sigil = (ROOT / "themes" / "sigil.yaml").read_text(encoding="utf-8")
        theme = ("name: odd\nextends: sigil\n"
                 "palette:\n  fg: red\n  new: '#123456'\n  'bad name': '#123456'\n"
                 "ui:\n  text: $new\n  fill: '2'\n  sim_trail: '0.5'\n  nonsense: '#ffffff'\n"
                 "syntax:\n  operator: '#12345'\n  keyword: $fg\n"
                 "kinds:\n  widget: '#abcdef'\n"
                 "site:\n  scene_blur: 'x; color: red'\n"
                 "extra:\n  a: '#ffffff'\n")
        got = self.fetching({"sigil.yaml": sigil, "odd.yaml": theme},
                            "(async () => { const ref = resolveTheme(await loadThemeRaw('sigil'), 'sigil');"
                            " const t = await loadThemeRaw('odd');"
                            " return Object.fromEntries(themeVars(t, ref, 'odd')); })()")["ok"]
        self.assertEqual(got["--palette-new"], "#123456")
        self.assertEqual(got["--ui-text"], "var(--palette-new)")
        self.assertEqual(got["--ui-sim-trail"], "0.5")
        self.assertEqual(got["--kinds-widget"], "#abcdef")
        for gone in ("--palette-fg", "--palette-bad name", "--ui-fill", "--ui-nonsense",
                     "--syntax-operator", "--syntax-keyword", "--site-scene-blur", "--extra-a"):
            with self.subTest(prop=gone):
                self.assertNotIn(gone, got)
        # the problems Python names are the entries left out
        probs = themes.problems(themes.resolve(themes.parse(theme.replace("extends: sigil\n", ""))))
        for word in ("palette.fg", "ui.fill", "ui.nonsense", "syntax.operator",
                     "syntax.keyword", "unknown section 'extra'"):
            self.assertTrue(any(word in p for p in probs), (word, probs))

    def test_sigil_theme_sets_every_entry_theme_css_sets(self):
        sigil = (ROOT / "themes" / "sigil.yaml").read_text(encoding="utf-8")
        got = self.fetching({"sigil.yaml": sigil},
                            "(async () => { const t = await loadThemeRaw('sigil');"
                            " return themeVars(t, resolveTheme(t, 'sigil'), 'sigil').length; })()")["ok"]
        raw = themes.load_raw("sigil")
        want = sum(1 for v in raw.values() if isinstance(v, dict)
                   for x in v.values() if isinstance(x, str))
        self.assertEqual(got, want)


class StreamLineCap(unittest.TestCase):
    """(b)"""

    def session(self):
        theme, name = highlight.theme_for(None, None)
        return highlight.StreamSession(theme, name, highlight.CORE)

    def test_a_long_request_line_is_an_error_and_the_session_goes_on(self):
        good = json.dumps({"id": 2, "lines": ["[A] -> [B]"]})
        long = json.dumps({"id": 1, "lines": ["x" * 500]})
        out = io.StringIO()
        with mock.patch.object(highlight, "MAX_REQUEST_CHARS", 100):
            code = highlight.stream(self.session(), io.StringIO(long + "\n" + good + "\n"), out)
        self.assertEqual(code, 0)
        first, second = [json.loads(ln) for ln in out.getvalue().splitlines()]
        self.assertEqual(first["id"], None)
        self.assertIn("longer than 100 characters", first["error"])
        self.assertEqual(second["id"], 2)
        self.assertNotIn("error", second)

    def test_a_line_at_the_cap_is_served(self):
        req = json.dumps({"id": 3, "lines": ["[A]"]})
        out = io.StringIO()
        with mock.patch.object(highlight, "MAX_REQUEST_CHARS", len(req)):
            highlight.stream(self.session(), io.StringIO(req + "\n"), out)
        self.assertEqual(json.loads(out.getvalue())["id"], 3)

    def test_a_long_last_line_without_a_line_end(self):
        out = io.StringIO()
        with mock.patch.object(highlight, "MAX_REQUEST_CHARS", 10):
            self.assertEqual(highlight.stream(self.session(), io.StringIO("y" * 50), out), 0)
        self.assertIn("error", json.loads(out.getvalue()))

    def test_the_cap_holds_any_document_under_the_size_cap(self):
        from sigil.core.lex import MAX_SOURCE_BYTES
        self.assertGreaterEqual(highlight.MAX_REQUEST_CHARS, MAX_SOURCE_BYTES)


class MermaidShapes(unittest.TestCase):
    """(c)"""

    def test_a_body_less_shape_is_a_node(self):
        text = "#!sketch\n[A] -> [B] : {Doc}\n{Doc} := { }\n{Row} := { path, note? }\n"
        out = mermaid.render(text)
        self.assertNotIn("subgraph", out)
        self.assertIn('Doc_data{{"Doc"}}', out)
        self.assertIn('Row_data{{"Row"}}', out)

    def test_a_block_with_a_body_is_still_a_subgraph(self):
        out = mermaid.render("#!sketch\n[A] -> [B]\n[B] := {\n  [C] -> [D]\n}\n")
        self.assertIn('subgraph B_service["B"]', out)


class SkillCards(unittest.TestCase):
    """(e)"""

    def test_cards_name_highlight(self):
        page = (SITE / "index.html").read_text(encoding="utf-8")
        start = page.index('<section id="skill"')
        section = page[start:page.index("</section>", start)]
        self.assertIn("sigil highlight", section)


if __name__ == "__main__":
    unittest.main()
