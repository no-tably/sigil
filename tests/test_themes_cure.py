"""sigil's theme grammar beside cure's Theme parser (cure.draw.theme.parse).

0.7.0 keeps sigil's own parser in sigil.present.themes: cure's is a stricter port of
it (KEY-only keys split on dots, control characters refused, `key: #abc` and values
starting with a YAML indicator refused, a tab may follow the colon, no depth limit,
other error texts), and the site's JavaScript parser mirrors sigil's grammar. These
tests pin where the two agree (every shipped theme reads the same tree) and where they
differ, so a later move onto cure's parser sees exactly what it changes.

Run:  python3 -m unittest tests.test_themes_cure
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_DIR))

from sigil.present import themes  # noqa: E402  (imports sigil.vendor first)
from cure.draw.theme.parse import ThemeError as CureThemeError  # noqa: E402
from cure.draw.theme.parse import parse as cure_parse  # noqa: E402


def _nested(raw) -> dict:
    """cure's flat Raw as sigil's nested dicts."""
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


class TestShippedThemesAgree(unittest.TestCase):
    def test_every_shipped_theme_reads_the_same_tree(self):
        files = sorted((_DIR / "themes").glob("*.y*ml"))
        self.assertTrue(files)
        for path in files:
            with self.subTest(theme=path.name):
                ours, theirs = _both(path.read_text(encoding="utf-8"))
                self.assertIsInstance(ours, dict)
                self.assertEqual(ours, theirs)


class TestGrammarsDiffer(unittest.TestCase):
    """Inputs sigil reads one way and cure another (the 0.7.0 CURE QUESTION)."""

    DIFFER = (
        '"!>": red\n',                 # a key outside cure's KEY
        "a.b: c\n",                    # one key in sigil, a path in cure
        "a: x\x0cy\n",                 # a control character in a value
        "a: #abc\n",                   # sigil: an empty value; cure: an error
        "a: @timeout\n",               # a plain value starting with an indicator
        "a:\tb\n",                     # sigil: no separator; cure: a tab after the colon
        "a: 'abc\n",                   # the same error, another text
        "\n".join(" " * (2 * k) + f"k{k}:" for k in range(17)) + "\n" + " " * 34 + "x: 1\n",
    )
    AGREE = (
        'a: "x\\" # y"\n',
        "a: 'it''s # here'\n",
        "a: 1\na: 2\n",
        "a: 1\n\t\n\t# note\nb: 2\n",
        "a:\nb:\n  c: 1\nd:\n",
    )

    def test_known_differences(self):
        for text in self.DIFFER:
            with self.subTest(text=text[:30]):
                ours, theirs = _both(text)
                self.assertNotEqual(ours, theirs)

    def test_known_agreements(self):
        for text in self.AGREE:
            with self.subTest(text=text[:30]):
                ours, theirs = _both(text)
                self.assertEqual(ours, theirs)


if __name__ == "__main__":
    unittest.main()
