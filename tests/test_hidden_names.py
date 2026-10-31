"""Names holding control or format characters (N1, hardening finding #16).

Lint refuses a name holding a control character (Unicode Cc: ESC, BEL, a tab
inside brackets …) or a format character (Cf: bidi overrides, zero-width space
and joiners, BOM, an emoji's ZWJ too): SGL195, an error. Whatever prints a name
prints it through one helper (sigil.core.lex.visible), so a document lint refuses
still never writes a raw control character to a terminal and never draws two
look-alike names: every view, highlight, export --mermaid (and --spine), lint and
check messages, the --sim narration.

Run:  python3 -m unittest discover tests
"""
import glob
import os
import subprocess
import sys
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_DIR))

from sigil.analyse import lint  # noqa: E402
from sigil.core import lex  # noqa: E402

SIGIL = str(_DIR / "bin" / "sigil")
ESC_DOC = "#!sketch\n(U) -> [Evil\x1bc\x07\x08\x08Good] : go({R}) => {S}\n"
ZW_DOC = "#!sketch\n[A] -> [A​]\n[A​] -> |S|\n"
CHECK_DOC = ("#!spec\n(U) -> [Ev\x1bil] : go({R}) => {S}\n[Ev\x1bil] -> |St\x1bore| : put({R})\n"
             "[Other] -> |St\x1bore| : put({R})\n(U) -> [Other]\n")


def sgl195(text: str) -> list:
    return [(d.severity, d.line) for d in lint.lint(text).diagnostics if d.rule == "SGL195"]


def leaks(out: str, colour: bool = False) -> list:
    """The control and format characters `out` prints raw (line ends kept; with
    `colour`, ESC kept only as the start of an SGR `ESC[`)."""
    bad = []
    for k, ch in enumerate(out):
        if ch in "\n" or not lex.is_hidden(ch):
            continue
        if colour and ch == "\x1b" and out[k + 1:k + 2] == "[":
            continue
        bad.append(hex(ord(ch)))
    return bad


def run(args, doc: str, tmp: Path, plain: bool = False) -> str:
    path = tmp / "doc.sigil"
    path.write_text(doc, encoding="utf-8")
    env = dict(os.environ, NO_COLOR="1") if plain else None
    p = subprocess.run([SIGIL, *args, str(path)], capture_output=True, text=True,
                       encoding="utf-8", timeout=120, cwd=str(tmp), env=env)
    return p.stdout + p.stderr


class Helper(unittest.TestCase):
    def test_visible_escapes_controls_and_format_characters(self):
        self.assertEqual(lex.visible("Evil\x1bc\x07Good"), "Evil\\x1bc\\x07Good")
        self.assertEqual(lex.visible("A​"), "A\\u200b")
        self.assertEqual(lex.visible("‮A⁦"), "\\u202eA\\u2066")
        self.assertEqual(lex.visible("x\U000e0041"), "x\\U000e0041")
        self.assertEqual(lex.visible("a\tb"), "a\\x09b")
        self.assertEqual(lex.visible("a\tb", keep="\t"), "a\tb")

    def test_visible_leaves_printable_text_and_free_text_joiners(self):
        for text in ("[Api]", "Café", "界面", "a b", "❤️", "é"):
            self.assertEqual(lex.visible(text), text)
        emoji = "\U0001f469‍\U0001f4bb"
        self.assertEqual(lex.visible(emoji, controls_only=True), emoji)
        self.assertEqual(lex.visible("a\x1b" + emoji, controls_only=True), "a\\x1b" + emoji)


class Rule(unittest.TestCase):
    def test_the_repro_names_are_errors(self):
        self.assertEqual(sgl195(ESC_DOC), [("error", 2)])
        self.assertEqual(sgl195(ZW_DOC), [("error", 2), ("error", 3)])

    def test_every_kind_of_hidden_character_in_a_name(self):
        for ch in ("\x1b", "\x07", "\x7f", "\x9b", "\t", "\x0c", "​", "‌",
                   "‍", "⁠", "﻿", "­", "‮", "⁦", "\U000e0041"):
            for line in (f"[A{ch}B] -> [C]", f"(U) -> {{D{ch}x}}", f"[C] -> <E{ch}x>"):
                with self.subTest(ch=hex(ord(ch)), line=line):
                    self.assertEqual(sgl195(f"#!sketch\n{line}\n"), [("error", 2)])

    def test_whitespace_around_a_name_is_no_part_of_it(self):
        self.assertEqual(sgl195("#!sketch\n[A\t] -> { B\x0c}\n"), [])

    def test_an_emoji_joined_by_zwj_in_a_name_is_flagged(self):
        # Kept simple: a format character anywhere in a name, a ZWJ in an emoji too.
        self.assertEqual(sgl195("#!sketch\n[\U0001f469‍\U0001f4bb] -> [B]\n"),
                         [("error", 2)])

    def test_words_outside_glyphs_are_names_too(self):
        doc = "#!sketch\nstate [Job] {\n  + -<go>-> Run​\n  Run​ -<end>-> $\n}\n"
        self.assertEqual([line for _s, line in sgl195(doc)], [3, 4])
        self.assertEqual(sgl195("#!sketch\n-- Bi‮ll\n[A] -> [B]\n"), [("error", 2)])

    def test_no_name_no_finding(self):
        for doc in ("#!sketch\n\t[A] -> [B]\n",                       # tab indent
                    "#!sketch\n[A] ->\t[B]\n",                        # tab between
                    "#!sketch\n[A] -> [B]\x0c[B] -> [C]\n",           # form feed between
                    "#!sketch\n[A] -> [B]  # a note \U0001f469‍\U0001f4bb ‏\n",
                    '#!sketch\n[A] -> [B] : say("hi ‍ there")\n',
                    "#!sketch\n[Café] -> [界面] -> [❤️]\n"):
            with self.subTest(doc=doc):
                self.assertEqual(sgl195(doc), [])

    def test_the_message_shows_the_name_escaped(self):
        d = [d for d in lint.lint(ESC_DOC).diagnostics if d.rule == "SGL195"][0]
        self.assertIn("`[Evil\\x1bc\\x07\\x08\\x08Good]`", d.message)
        self.assertIn("\\x1b, \\x07, \\x08", d.message)
        self.assertEqual(leaks(d.format()), [])

    def test_no_existing_document_holds_one(self):
        paths = [p for pat in ("tests/fixtures/**/*.sigil", "site/examples/*.sigil",
                               "design/*.sigil")
                 for p in glob.glob(str(_DIR / pat), recursive=True)]
        paths = [p for p in paths if not Path(p).name.startswith("SGL195.")]   # its own
        self.assertTrue(paths)
        for path in sorted(paths):
            with self.subTest(path=path):
                text = Path(path).read_text(encoding="utf-8")
                self.assertEqual(sgl195(text), [])


class Printed(unittest.TestCase):
    """Every printed name escapes its hidden characters (the doc lints with SGL195)."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def assert_clean(self, args, doc=ESC_DOC, colour=False, shown="Evil\\x1bc"):
        out = run(args, doc, self.tmp, plain=not colour)
        self.assertEqual(leaks(out, colour), [], (args, out))
        if shown:
            self.assertIn(shown, out, args)

    def test_every_view(self):
        for view in ("--graph", "--tree", "--flow", "--run"):
            for extra in ([], ["--payloads"], ["--sim", "happy"]):
                with self.subTest(view=view, extra=extra):
                    self.assert_clean(["view", "--once", view, "--color", "never", *extra])
        self.assert_clean(["view", "--once", "--graph", "--color", "always"], colour=True)

    def test_zero_width_names_differ_when_drawn(self):
        out = run(["view", "--once", "--graph", "--color", "never"], ZW_DOC, self.tmp)
        self.assertEqual(leaks(out), [], out)
        self.assertIn("[A\\u200b]", out)

    def test_sim_narration(self):
        self.assert_clean(["view", "--once", "--sim", "happy", "--run"])
        out = run(["view", "--sim", "happy", "--json"], ESC_DOC, self.tmp)
        self.assertNotIn("​", run(["view", "--sim", "happy", "--json"], ZW_DOC, self.tmp))
        self.assertIn("Evil\\\\x1bc", out)

    def test_highlight(self):
        self.assert_clean(["highlight"], colour=True)
        self.assert_clean(["highlight"])
        self.assert_clean(["highlight"], doc=ZW_DOC, shown="[A\\u200b]")

    def test_highlight_keeps_spaces_between_names(self):
        out = run(["highlight"], "#!sketch\n[A]\x0c[B]\t-> [C]\n", self.tmp, plain=True)
        self.assertEqual(out, "#!sketch\n[A]\x0c[B]\t-> [C]\n")

    def test_highlight_keeps_free_text_joiners(self):
        emoji = "\U0001f469‍\U0001f4bb"
        out = run(["highlight"], f"#!sketch\n[A] -> [B]  # {emoji}\x1b\n", self.tmp,
                  plain=True)
        self.assertIn(emoji, out)
        self.assertIn("\\x1b", out)

    def test_mermaid(self):
        self.assert_clean(["export", "--mermaid"])
        self.assert_clean(["export", "--mermaid", "--spine"])
        self.assert_clean(["export", "--mermaid"], doc=ZW_DOC, shown="A\\u200b")

    def test_lint_and_check_messages(self):
        self.assert_clean(["lint"])
        self.assert_clean(["check"], doc=CHECK_DOC, shown="Ev\\x1bil")
        self.assert_clean(["lint", "--deep"], doc=CHECK_DOC, shown="Ev\\x1bil")

    def test_export_folder_is_refused(self):
        out = run(["export", "--out", str(self.tmp / "out")], "#!spec\n" + CHECK_DOC[7:],
                  self.tmp)
        self.assertIn("SGL195", out)
        self.assertFalse((self.tmp / "out" / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
