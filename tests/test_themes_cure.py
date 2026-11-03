"""sigil's themes read by cure's Theme parser (cure.draw.theme.parse): one grammar.

Since 0.7.0 sigil.present.themes parses every theme file with cure's parser and reads
cure's flat key paths back into nested maps; sigil keeps finding files, `extends` by
name or path (laid with cure's merge) and `$ref` resolution. The site's JavaScript
parser follows the same grammar. These tests pin the agreement:
  - every shipped theme and the dialect probe theme read to cure's tree;
  - inputs sigil once read its own way now read exactly as cure reads them, and an
    error carries cure's text (file and line);
  - sigil's own two nesting errors (too deep; a path both a value and a map);
  - `extends` is cure's merge (a value replaces the map below it);
  - site.js parseYaml gives the same tree or the same error text as themes.parse
    over a corpus of edge cases (node only).

Run:  python3 -m unittest tests.test_themes_cure
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_DIR))

from sigil.present import themes  # noqa: E402  (imports sigil.vendor first)
from cure.draw.theme.parse import ThemeError as CureThemeError  # noqa: E402
from cure.draw.theme.parse import merge as cure_merge  # noqa: E402
from cure.draw.theme.parse import parse as cure_parse  # noqa: E402


def _nested(raw) -> dict:
    """cure's flat Raw as nested dicts (no conflicts in the inputs used here)."""
    out: dict = {}
    for path, value in raw.leaves.items():
        node = out
        for key in path[:-1]:
            node = node.setdefault(key, {})
        node[path[-1]] = value
    return out


def _both(text: str):
    try:
        ours = themes.parse(text, "t")
    except themes.ThemeError as exc:
        ours = ("error", str(exc))
    try:
        theirs = _nested(cure_parse(text, "t"))
    except CureThemeError as exc:
        theirs = ("error", str(exc))
    return ours, theirs


# Inputs sigil read its own way before 0.7.0 (its own parser), now cure's.
ONCE_DIFFERENT = (
    '"!>": red\n',                 # a key outside cure's KEY
    "a.b: c\n",                    # one key once, a path now
    "a: x\x0cy\n",                 # a control character in a value
    "a: #abc\n",                   # once an empty value; now an error
    "a: @timeout\n",               # a plain value starting with an indicator
    "a:\tb\n",                     # once no separator; a tab may follow the colon
    "a: 'abc\n",                   # the same error, cure's text
    'a: "\\q"\n',                  # a malformed double-quoted string, cure's text
)
ALWAYS_AGREED = (
    'a: "x\\" # y"\n',
    "a: 'it''s # here'\n",
    "a: 1\na: 2\n",
    "a: 1\n\t\n\t# note\nb: 2\n",
    "a:\nb:\n  c: 1\nd:\n",
)


class TestShippedThemesAgree(unittest.TestCase):
    def test_every_shipped_theme_reads_cures_tree(self):
        files = sorted((_DIR / "themes").glob("*.y*ml"))
        files.append(_DIR / "tests" / "fixtures" / "theme_dialect" / "probe.yaml")
        self.assertGreater(len(files), 1)
        for path in files:
            with self.subTest(theme=path.name):
                ours, theirs = _both(path.read_text(encoding="utf-8"))
                self.assertIsInstance(ours, dict)
                self.assertEqual(ours, theirs)
                self.assertEqual(list(ours), list(theirs))      # key order too


class TestOneGrammar(unittest.TestCase):
    def test_once_different_now_agree(self):
        for text in ONCE_DIFFERENT + ALWAYS_AGREED:
            with self.subTest(text=text[:30]):
                ours, theirs = _both(text)
                self.assertEqual(ours, theirs)

    def test_errors_are_cures_text(self):
        for text, reason in (("a: #abc\n", "t:1: a value starting with # must be quoted"),
                             ('"!>": red\n', "t:1: bad key"),
                             ("a:\n  - x\n", "t:2: lists and flow collections are not supported"),
                             ("a: 'abc\n", "t:1: unclosed single-quoted string")):
            with self.subTest(text=text), self.assertRaises(themes.ThemeError) as cm:
                themes.parse(text, "t")
            self.assertEqual(str(cm.exception), reason)

    def test_no_parser_of_its_own(self):
        for name in ("_strip_comment", "_skip_quoted", "_scalar", "_single_quoted",
                     "_find_colon", "_key", "_merge"):
            self.assertFalse(hasattr(themes, name), name)


class TestSigilsNesting(unittest.TestCase):
    """cure's Raw is flat; sigil's tree is nested, which adds two errors."""

    def test_a_path_both_a_value_and_a_map(self):
        for text in ("list.item: x\nlist.item.selected: y\n",
                     "list.item.selected: y\nlist.item: x\n"):
            with self.subTest(text=text):
                cure_parse(text, "t")                         # cure reads it
                with self.assertRaisesRegex(themes.ThemeError,
                                            r"^t:2: 'list.item' is both a value and a map$"):
                    themes.parse(text, "t")

    def test_depth_counts_dotted_segments_too(self):
        ok = ".".join(f"k{k}" for k in range(themes.MAX_DEPTH + 1)) + ": x\n"
        self.assertIsInstance(themes.parse(ok), dict)
        deep = ".".join(f"k{k}" for k in range(themes.MAX_DEPTH + 2)) + ": x\n"
        with self.assertRaisesRegex(themes.ThemeError, f"nested more than {themes.MAX_DEPTH} deep"):
            themes.parse(deep)


class TestExtendsIsCuresMerge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, name: str, text: str) -> Path:
        (self.dir / name).write_text(text, encoding="utf-8")
        return self.dir / name

    def test_load_raw_is_cures_merge_read_back(self):
        base = "name: b\nui:\n  a: '1'\n  b:\n    c: '2'\nkinds:\n  x: '3'\n"
        child = "extends: base.yaml\nui:\n  b: flat\n  d: '4'\nnew: '5'\n"
        self.write("base.yaml", base)
        path = self.write("child.yaml", child)
        want = _nested(cure_merge(cure_parse(base, "b"), cure_parse(child.split("\n", 1)[1], "c")))
        got = themes.load_raw(str(path))
        self.assertEqual(got, want)
        self.assertEqual(json.dumps(got), json.dumps(want))   # order too
        self.assertEqual(got["ui"]["b"], "flat")              # a value replaces the map below it
        self.assertEqual(got["name"], "b")                    # a parent's name stays unless set

    def test_a_map_over_a_parents_value_is_both(self):
        self.write("base.yaml", "ui:\n  fill: '0.2'\n")
        path = self.write("child.yaml", "extends: base.yaml\nui:\n  fill:\n    x: '1'\n")
        with self.assertRaisesRegex(themes.ThemeError, "'ui.fill' is both a value and a map"):
            themes.load_raw(str(path))


NODE = shutil.which("node")

# Edge cases site.js and themes.py must read alike (tree, or the same error text).
JS_CORPUS = (
    "a: 1\n", "a.b.c: x\nd: y\n", "a:\n  b.c: x\n  b:\n    d: y\n", "bg: #0d1117\n",
    "a: # none\n", "a: @x\n", "a: '@x'\n", "a: `x\n", "a: |\n", "a:\tb\n", "a: x\x01y\n",
    "a: 1 # \x1b\n", 'a: "x\\ty"\n', 'a: "x\\u0007"\n', "a: x\x85\n", "a:\n\tb: 1\n",
    "a:\n  b: 1\n   c: 2\n", "  a: 1\n", "a: 1\n  b: 2\n", '"a b": 1\n', "'it''s': v\n",
    '"__proto__": x\n', "a: 1\na: 2\n", "a:\n  b: 1\na.b: 2\n", "a: 1\na.b: 2\n",
    "x.y: 1\nx: 2\n", "a: 'x'' y'\n", "a: 'x' y\n", 'a: "x" y\n', ": v\n", "'': v\n",
    "a:b\n", "- x\n", "-\n", "[a]\n", "{a: 1}\n", "a: [1]\n", "a: {b}\n", "a: !tag\n",
    "a: *ref\n", "a: &anchor\n", "a: %x\n", "a: >\n", "a: x # y\n", "a: x#y\n",
    "a:\n\n  # c\n  b: 1\n", chr(0xFEFF) + "a: 1\r\nb: 2\r\n", "a: 1\rb: 2\n", "",
    "a:\n" + chr(0x3000) + "b: 1\n",
    "".join(f"{'  ' * k}k{k}:\n" for k in range(17)) + "  " * 17 + "v: x\n",
)


@unittest.skipUnless(NODE, "node not installed")
class TestSiteJsAgrees(unittest.TestCase):
    def test_parse_yaml_matches_themes_parse(self):
        src = (_DIR / "site" / "site.js").read_text(encoding="utf-8")
        code = src[src.index("  // ------------------------------------------------------------------ YAML subset"):
                   src.index("  // ------------------------------------------------------------------ themes")]
        body = (code + f"\nconst texts = {json.dumps(JS_CORPUS)};\n"
                "process.stdout.write(JSON.stringify(texts.map((t) => {"
                " try { return { ok: parseYaml(t, 'fixture') }; }"
                " catch (e) { return { error: String(e.message) }; } })));")
        res = subprocess.run([NODE, "-e", body], capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)
        for text, got in zip(JS_CORPUS, json.loads(res.stdout)):
            try:
                want = {"ok": themes.parse(text, "fixture")}
            except themes.ThemeError as exc:
                want = {"error": str(exc)}
            with self.subTest(text=text[:40]):
                self.assertEqual(got, want)


if __name__ == "__main__":
    unittest.main()
