"""sigil.core.tokens and sigil.core.statements: one statement walk in core.

The walk finds each statement with its line and column and records the blocks,
headers, sections, transitions and continuation lines it reads; lint's
hardening rules judge that record (they keep no walk of their own). The parser
records the statements a glyph heads (Graph.heads) and each composition entry's
line (TreeEntry.line); the export model reads its component lines from them,
not from the text.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sigil.analyse.lint import hardening  # noqa: E402
from sigil.core import parse, statements, tokens  # noqa: E402
from sigil.model import systems  # noqa: E402


def walk(text: str) -> statements.Walk:
    return statements.walk_statements(text.splitlines())


class CodeColumns(unittest.TestCase):
    def test_a_cut_keeps_its_column_in_the_line(self):
        code = tokens.code_line("loop @times 3 { [A] -> [B] }")
        body = code.cut(code.text.index("{") + 1)
        self.assertEqual(body.col, 15)
        self.assertEqual(body.cut(1, 4).col, 16)
        self.assertEqual(body.cut(1, 4).raw, "[A]")

    def test_a_line_starts_at_column_zero(self):
        self.assertEqual(tokens.code_line("  [A] -> [B]").col, 0)


class StatementWalk(unittest.TestCase):
    def test_statements_keep_line_and_column(self):
        w = walk("#!sketch\n[A] -> [B]\nloop @times 3 { [C] -> [D] }\n    -> [E]\n")
        found = [(s.line, s.col, s.code.raw.strip()) for s in w.statements]
        self.assertEqual(found, [(2, 0, "[A] -> [B]"), (3, 16, "[C] -> [D]"),
                                 (4, 4, "-> [E]")])

    def test_a_one_line_definition_that_draws_is_an_alias_statement(self):
        # A one-line definition's body is read as a statement either way (the model
        # reads it); lint judges only one that draws (the other is `quiet`).
        w = walk("[R] := [A] -> [B]\n[S] := a prose note\n")
        self.assertEqual([(s.line, s.alias, s.quiet) for s in w.statements],
                         [(1, True, False), (2, True, True)])
        self.assertEqual(w.definitions, frozenset({"R", "S"}))

    def test_blocks_closed_as_they_close_then_those_left_open(self):
        w = walk("loop @times 2 {\n  parallel {\n  }\n}\nbranch on {X} {\n")
        self.assertEqual([(b.kind, b.line, b.content, b.closed) for b in w.blocks],
                         [("parallel", 2, False, True), ("loop", 1, True, True),
                          ("branch", 5, False, False)])

    def test_headers_sections_transitions_and_bare_branches(self):
        w = walk("loop {\n  [A] -> [B]\n}\n--- L2: [X] ---\nstate {O} {\n  a -> b\n}\n"
                 "[P]\n  *-> [Q]\n")
        self.assertEqual([(h.kind, h.line, h.head.strip()) for h in w.headers],
                         [("loop", 1, "loop")])
        self.assertEqual(w.sections, ((4, "--- L2: [X] ---"),))
        self.assertEqual(w.transitions, ((6, "a -> b"),))
        self.assertEqual(w.bare_branches, ((9, "*-> [Q]"),))

    def test_continuations_say_whether_a_flow_is_above(self):
        w = walk("-> [A]\n[B] -> [C]\n\n  -> [D]\n")
        self.assertEqual([(c.line, c.subject, c.after_blank) for c in w.continuations],
                         [(1, False, False), (4, True, True)])

    def test_every_line_has_its_code(self):
        w = walk("[A] -> [B]  # note\n\n")
        self.assertEqual([c.raw for c in w.codes], ["[A] -> [B]  ", ""])


class LintReadsTheWalk(unittest.TestCase):
    """The hardening rules judge the walk's record; the walk judges nothing."""

    def rules(self, text: str) -> list:
        return [(f.line, f.rule) for f in hardening.walk_findings(walk(text))]

    def test_block_findings(self):
        self.assertEqual(self.rules("loop @times 2 {\n}\nparallel {\n"),
                         [(1, "SGL162"), (3, "SGL160")])

    def test_header_section_transition_and_continuation_findings(self):
        found = self.rules("loop {\n  [A] -> [B]\n}\n--- L2 [X]\n--- L2: [Y] ---\n"
                           "state {O} {\n  a -> b\n}\n-> [C]\n[P]\n  -& {H}\n")
        self.assertEqual(sorted(found), [(1, "SGL163"), (4, "SGL184"), (5, "SGL184"),
                                         (7, "SGL161"), (9, "SGL130"), (11, "SGL186")])


class StatementHeads(unittest.TestCase):
    def test_heads_are_the_glyphs_statements_start_with(self):
        g = parse.parse_document("[Api] @sla(99)\n[A] -> [B]\n  -> [C]\n"
                                 "[X] := { [D] }\n@after(1s) [E]\n")
        self.assertEqual(g.heads, [(1, "Api_service"), (2, "A_service"), (4, "X_service")])
        self.assertEqual(g.expansions["X_service"].heads, [(4, "D_service")])

    def test_tree_entries_carry_their_lines(self):
        g = parse.parse_document("[Ship]\n    \\-& {Hull}\n    \\-*-> [Bullet]\n"
                                 "        \\-& {Hull}\n")
        self.assertEqual([(t.node, t.line) for t in g.tree],
                         [("Ship_service", 1), ("Hull_data", 2), ("Bullet_service", 3),
                          ("Hull_data", 4)])

    def test_a_branch_arm_heads_no_statement(self):
        g = parse.parse_document("branch on {R}.kind {\n  read => [Reader] -> |DB|\n"
                                 "  admin => [Admin] @cap(admin)\n}\n")
        self.assertEqual(g.heads, [])

    def test_component_lines_come_from_heads_and_entries(self):
        g = parse.parse_document("[Api] @sla(99)\n[Ship]\n    \\-& {Hull}\n"
                                 "[Ship] -> [Api] : find({Hull})\n")
        nodes = systems.component_nodes(g)
        self.assertEqual(systems.head_lines(g, nodes),
                         {"Api_service": {1}, "Ship_service": {2, 4}, "Hull_data": {3}})


if __name__ == "__main__":
    unittest.main()


class ScannerShortcuts(unittest.TestCase):
    """The tokenizer's shortcuts read as its full rules do."""

    def test_a_glyph_scans_the_same_with_or_without_brackets_inside(self):
        cases = {
            "[A]": (3, ""), "[]": (2, "empty"), "[ \x00]": (4, "empty"),
            "{Order}": (7, ""), "|S|": (3, ""), "(User)": (6, ""), "<E>": (3, ""),
            "<A->": (2, "unclosed"), "<AB->": (3, "unclosed"), "<X=>": (2, "unclosed"),
            "<A>->": (3, ""), "[A}": (3, "mismatched"), "[Cache<K,V>]": (12, ""),
            "[A": (2, "unclosed"), "[A -> [B]": (3, "unclosed"), "(a(b))": (2, "unclosed"),
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(tokens._scan_glyph(text, 0), want)

    def test_a_scanner_left_out_for_a_character_reads_nothing_there(self):
        tails = ["", " ", "1", "3 ", "N", "> [B]", "-> [B]", "= 1", ">", "(x)", "()",
                 "[A]", "a(b)", "|", "||", "&", "!", "?", ".f", "{", "@x"]
        befores = [(), (tokens.Tok("arrow", "->", 0),), (tokens.Tok("glyph", "[A]", 0),)]
        for code in range(32, 127):
            ch = chr(code)
            kept = tokens._scanners_for(ch)
            left_out = [s for s in tokens._SCANNERS if s not in kept]
            for lead in ("", "[A]", "[A] "):
                for tail in tails:
                    for toks in befores:
                        line = lead + ch + tail
                        r = tokens._Reader(tokens.Code(line, line), tokens.NO_DIALECT)
                        if r.w[len(lead)] != ch:    # blanked: the scan skips it
                            continue
                        r.toks, r.prev = list(toks), bool(lead)
                        for scanner in left_out:
                            with self.subTest(ch=ch, line=line, scanner=scanner.__name__):
                                self.assertIsNone(scanner(r, len(lead)))

    def test_a_statement_with_no_modifier_or_payload_keeps_its_scan_order(self):
        toks = tokens.tokenize_statement(tokens.code_line("[A] -> [B] & [C] => <D>"))
        self.assertEqual([t.col for t in toks], sorted(t.col for t in toks))
