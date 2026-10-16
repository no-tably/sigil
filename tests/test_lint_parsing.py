"""Lint parsing edge cases: block strings, state blocks, inert strings, arrows,
payloads, modifiers, mode lines and the CLI entry point (`sigil lint`).

Run:  python3 -m unittest discover tests
"""
import subprocess
import sys
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_DIR))

from sigil.analyse import lint  # noqa: E402
from sigil.analyse.lint import graph as lint_graph, hardening, payloads  # noqa: E402
from sigil.core import parse, vocab  # noqa: E402

SIGIL = _DIR / "bin" / "sigil"


def rules(text: str):
    return [d.rule for d in lint.lint(text).diagnostics]


class BlockStrings(unittest.TestCase):
    def test_block_opening_on_closing_line(self):
        doc = '#!spec\n[A] -> [B] : """\nx\n""" -> [C] : """\ny\n"""\n'
        self.assertNotIn("SGL170", rules(doc))
        folded = lint.collapse_block_strings(doc.splitlines(), vocab.LintResult())
        self.assertEqual(len(folded), len(doc.splitlines()))
        self.assertFalse(any('"""' in ln for ln in folded))

    def test_two_single_line_blocks_on_one_line(self):
        folded = lint.collapse_block_strings(
            ['[A] -> [B] : """a""" -> [C] : """b"""'], vocab.LintResult())
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
        self.assertEqual(vocab.ARROW_RE.search("[A] <-> [B]").group(0), "<->")

    def test_bidirectional_is_not_an_event_glyph(self):
        doc = "#!sketch\n(User) <-> [API] <-> |DB|\n"
        self.assertNotIn("SGL070", rules(doc))
        self.assertIn("SGL070", rules("#!sketch\n[A] -> [B] -> [A]\n"))


class Payloads(unittest.TestCase):
    def test_list_literal(self):
        self.assertEqual(payloads._classify_payload("[1, 2]")[0], "value")
        self.assertEqual(payloads._classify_payload('["a"]')[0], "value")
        self.assertEqual(payloads._classify_payload("[]")[0], "value")
        self.assertEqual(payloads._classify_payload("[API]")[0], "entity")
        self.assertEqual(payloads._classify_payload("[?]")[0], "entity")

    def test_stream_bound_dropped(self):
        self.assertEqual(payloads._split_payload_and_tags("x ^8@drop"), ("x", []))
        self.assertEqual(payloads._split_payload_and_tags("x ^10k"), ("x", []))
        self.assertEqual(payloads._split_payload_and_tags("x @inv"), ("x", ["@inv"]))


class Modifiers(unittest.TestCase):
    def test_nearest_match_hint(self):
        msgs = [d.message for d in lint.lint("#!spec\n[A] -> [B] @timout(5s)\n").diagnostics
                if d.rule == "SGL040"]
        self.assertEqual(len(msgs), 1)
        self.assertIn("Did you mean @timeout?", msgs[0])

    def test_accessor_after_glyph(self):
        self.assertNotIn("SGL040", rules("#!spec\n[A] -> {Concept}@hash\n"))


class CombiningMarkVerbs(unittest.TestCase):
    VERB = "\u30ab\u3099\u30b9"      # カ + combining ゛ + ス: a decomposed ガス

    def test_an_op_target_holding_a_mark_lints_as_its_composed_twin(self):
        composed = "\u30ac\u30b9"
        for tmpl in ("#!sketch\n[A] -> {v}({{X}})\n", "#!sketch\n[A] -> op ns.{v}({{X}})\n"):
            self.assertEqual(rules(tmpl.format(v=self.VERB)), rules(tmpl.format(v=composed)))
            self.assertNotIn("SGL120", rules(tmpl.format(v=self.VERB)))

    def test_a_payload_holding_a_mark_is_an_op_call(self):
        self.assertEqual(payloads._classify_payload(f"op ns.{self.VERB}({{X}})")[0], "ext-op")
        self.assertEqual(payloads._classify_payload(f"{self.VERB}({{X}})")[0], "int-op")
        self.assertEqual(payloads._classify_payload("op ns.\u0915\u093f({X})")[0], "ext-op")
        self.assertEqual(payloads._classify_payload("op ns.a\u2192b({X})")[0], "ext-op-bad")
        self.assertEqual(payloads._classify_payload("op ns.\u0301b({X})")[0], "ext-op-bad")


class ModeLines(unittest.TestCase):
    def test_duplicate_mode_line(self):
        self.assertIn("SGL080", rules("#!spec\n#!sketch\n[A] -> [B]\n"))

    def test_single_mode_line_ok(self):
        self.assertNotIn("SGL080", rules("# header\n#!spec\n[A] -> [B]\n"))


class Main(unittest.TestCase):
    def test_missing_file(self):
        p = subprocess.run([sys.executable, str(SIGIL), "lint", "/nonexistent/x.sigil"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)
        self.assertIn("cannot read", p.stderr)
        self.assertNotIn("Traceback", p.stderr)

    def test_stdin_utf8(self):
        p = subprocess.run([sys.executable, str(SIGIL), "lint", "-"],
                           input="#!spec\n[A] → [B]\n".encode("utf-8"),
                           capture_output=True, env={"PYTHONIOENCODING": "ascii"})
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_lint_reads_the_one_parser(self):
        # lint parses with the package's parser, the same instance everywhere
        self.assertIs(lint_graph.render, parse)
        self.assertIs(hardening.render, parse)


if __name__ == "__main__":
    unittest.main()
