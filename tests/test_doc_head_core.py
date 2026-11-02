"""A document's head read once, in core: lex.mode_word (the mode line's word, as
lint, check and the views take it) and statements.title_of (the title: the first
own-line comment before any statement). kit.doc_title and check.read_mode read
the head only through them, with no text reading of their own."""

import inspect
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sigil.analyse import check  # noqa: E402
from sigil.core import lex, statements  # noqa: E402
from sigil.present import kit  # noqa: E402


class ModeWord(unittest.TestCase):
    def test_the_first_content_line_s_first_word(self):
        for lines, word in ((["# t", "", "  #!craft  extra"], "#!craft"),
                            (["#!spec"], "#!spec"), (["#!bogus x"], "#!bogus"),
                            (["[A]", "#!spec"], ""), (["# t"], ""), ([], ""),
                            (["#& header", "#!spec"], "")):
            with self.subTest(lines=lines):
                self.assertEqual(lex.mode_word(lines), word)


class TitleOf(unittest.TestCase):
    def test_as_doc_title_reads_it(self):
        for text, title in (("#!spec\n\n  # A shop\n# more\n[A]\n", "A shop"),
                            ("## Shop ##\n", "Shop ##"), ("#& one\n#& two ~{\n}\n# t\n", "t"),
                            ("#!spec\n#% job\n# t\n", "t"),
                            ("[A]  # trailing\n", ""), ("#\n# t\n", ""), ("", "")):
            with self.subTest(text=text):
                self.assertEqual(statements.title_of(lex.split_lines(text), None), title)


class ReadThroughCore(unittest.TestCase):
    TEXT = re.compile(r"\.(?:split|strip|lstrip|rstrip|startswith)\(|\[\d*:\d*\]")

    def test_no_text_reading_of_their_own(self):
        for fn, uses in ((kit.doc_title, "title_of("), (check.read_mode, "mode_word(")):
            with self.subTest(fn=fn.__name__):
                src = inspect.getsource(fn)
                body = src.split('"""')[-1] if src.count('"""') >= 2 else src
                self.assertIn(uses, body)
                self.assertIsNone(self.TEXT.search(body), body)

    def test_read_mode_unchanged(self):
        for doc, mode in ((["# t", "", "#!craft"], "craft"), (["#!spec x"], "spec"),
                          (["[A]", "#!spec"], "sketch"), (["# t"], "sketch"),
                          (["#!bogus"], "sketch"), ([], "sketch")):
            self.assertEqual(check.read_mode(doc), mode, doc)


if __name__ == "__main__":
    unittest.main()
