"""lint.py parsing edge cases: block strings, state blocks, inert strings, arrows,
payloads, modifiers, mode lines and the CLI entry point.

Run:  python3 -m unittest discover tests
"""
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]


def _load(name: str, fname: str):
    spec = importlib.util.spec_from_file_location(name, _DIR / fname)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lint = _load("sigil_lint_parsing", "lint.py")


def rules(text: str):
    return [d.rule for d in lint.lint(text).diagnostics]


class BlockStrings(unittest.TestCase):
    def test_block_opening_on_closing_line(self):
        doc = '#!spec\n[A] -> [B] : """\nx\n""" -> [C] : """\ny\n"""\n'
        self.assertNotIn("SGL170", rules(doc))
        folded = lint.collapse_block_strings(doc.splitlines(), lint.LintResult())
        self.assertEqual(len(folded), len(doc.splitlines()))
        self.assertFalse(any('"""' in ln for ln in folded))

    def test_two_single_line_blocks_on_one_line(self):
        folded = lint.collapse_block_strings(
            ['[A] -> [B] : """a""" -> [C] : """b"""'], lint.LintResult())
        self.assertEqual(folded, ['[A] -> [B] : "block-string" -> [C] : "block-string"'])

    def test_unterminated_still_reported(self):
        self.assertIn("SGL170", rules('#!spec\n[A] -> [B] : """\nx\n'))


class StateBlocks(unittest.TestCase):
    def test_generic_owner_is_a_state_block(self):
        self.assertIn("SGL090", rules("#!spec\nstate {Job<T>} {\n  a -<go> b\n}\n"))

    def test_plain_owner_still_checked(self):
        self.assertIn("SGL090", rules("#!spec\nstate {Job} {\n  a -<go> b\n}\n"))

    def test_generic_owner_states_not_actors(self):
        doc = "#!spec\nstate {Job<T>} {\n  (pending) -<go>-> (done)\n}\n"
        self.assertNotIn("SGL020", rules(doc))


class StringsAreInert(unittest.TestCase):
    def test_semicolon_in_string(self):
        self.assertNotIn("SGL050", rules('#!spec\n[A] -> [B] : "a; b"\n'))
        self.assertIn("SGL050", rules("#!spec\n[A] -> [B]; [B] -> [C]\n"))

    def test_at_sign_in_string(self):
        self.assertNotIn("SGL040", rules('#!spec\n[A] -> [B] : "mail ops@example.com"\n'))

    def test_hole_in_string(self):
        self.assertNotIn("SGL010", rules('#!spec\n[A] -> [B] : "is [?] set"\n'))


class ReverseArrow(unittest.TestCase):
    def test_no_invented_match(self):
        self.assertNotIn("SGL060", rules("#!spec\n[A] <<=- [B]\n"))

    def test_real_reverse_arrow(self):
        self.assertIn("SGL060", rules("#!spec\n[A] <- [B]\n"))
        self.assertNotIn("SGL060", rules("#!spec\n[A] <-> [B]\n"))


class Arrows(unittest.TestCase):
    def test_bidirectional_matched_whole(self):
        self.assertEqual(lint.ARROW_RE.search("[A] <-> [B]").group(0), "<->")

    def test_bidirectional_is_not_an_event_glyph(self):
        doc = "#!sketch\n(User) <-> [API] <-> |DB|\n"
        self.assertNotIn("SGL070", rules(doc))
        self.assertIn("SGL070", rules("#!sketch\n[A] -> [B] -> [A]\n"))


class Payloads(unittest.TestCase):
    def test_list_literal(self):
        self.assertEqual(lint._classify_payload("[1, 2]")[0], "value")
        self.assertEqual(lint._classify_payload('["a"]')[0], "value")
        self.assertEqual(lint._classify_payload("[]")[0], "value")
        self.assertEqual(lint._classify_payload("[API]")[0], "entity")
        self.assertEqual(lint._classify_payload("[?]")[0], "entity")

    def test_stream_bound_dropped(self):
        self.assertEqual(lint._split_payload_and_tags("x ^8@drop"), ("x", []))
        self.assertEqual(lint._split_payload_and_tags("x ^10k"), ("x", []))
        self.assertEqual(lint._split_payload_and_tags("x @inv"), ("x", ["@inv"]))


class Modifiers(unittest.TestCase):
    def test_nearest_match_hint(self):
        msgs = [d.message for d in lint.lint("#!spec\n[A] -> [B] @timout(5s)\n").diagnostics
                if d.rule == "SGL040"]
        self.assertEqual(len(msgs), 1)
        self.assertIn("Did you mean @timeout?", msgs[0])

    def test_accessor_after_glyph(self):
        self.assertNotIn("SGL040", rules("#!spec\n[A] -> {Concept}@hash\n"))


class ModeLines(unittest.TestCase):
    def test_duplicate_mode_line(self):
        self.assertIn("SGL080", rules("#!spec\n#!sketch\n[A] -> [B]\n"))

    def test_single_mode_line_ok(self):
        self.assertNotIn("SGL080", rules("# header\n#!spec\n[A] -> [B]\n"))


class Main(unittest.TestCase):
    def test_missing_file(self):
        p = subprocess.run([sys.executable, str(_DIR / "lint.py"), "/nonexistent/x.sigil"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)
        self.assertIn("cannot read", p.stderr)
        self.assertNotIn("Traceback", p.stderr)

    def test_stdin_utf8(self):
        p = subprocess.run([sys.executable, str(_DIR / "lint.py"), "-"],
                           input="#!spec\n[A] → [B]\n".encode("utf-8"),
                           capture_output=True, env={"PYTHONIOENCODING": "ascii"})
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_sibling_loader_caches(self):
        self.assertIs(lint._render_module(), lint._render_module())


if __name__ == "__main__":
    unittest.main()
