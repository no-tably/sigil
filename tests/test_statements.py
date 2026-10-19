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
        self.assertEqual([(t.line, t.raw, t.kind) for t in w.transitions],
                         [(6, "a -> b", "untriggered")])
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


def _mods(line: str) -> list:
    return [t.pair for t in tokens.tokenize_statement(tokens.code_line(line)) if t.pair]


class FreeArgumentModifier(unittest.TestCase):
    """A free-argument modifier (`@owns`, `@inv`, …) ends where the next header
    token starts: a stream bound, an access list, `×N`, `!`, a block `{`. Its
    argument never carries the blanks of another capture, and what follows it
    reads as it would without it."""

    def test_a_bound_and_a_mark_after_a_parenthesised_argument(self):
        self.assertEqual(_mods("[Y] @owns(|S|) ^4 ! {"),
                         [("owns", "|S|"), ("^", "4"), ("!", None)])
        self.assertEqual(_mods("[Y] @owns(|S|) ^4 ! {")[1:], _mods("[Y] ^4 ! {"))

    def test_a_bound_and_a_mark_after_a_free_argument(self):
        self.assertEqual(_mods("[Y] @owns |S| ^4 ! {"),
                         [("owns", "|S|"), ("^", "4"), ("!", None)])
        self.assertEqual(_mods("[Y] @owns |S| ×3 !"),
                         [("owns", "|S|"), ("×", "3"), ("!", None)])

    def test_a_block_brace_ends_the_argument(self):
        self.assertEqual(_mods("[Y] @owns(|S|) ×3 ! {"),
                         [("owns", "|S|"), ("×", "3"), ("!", None)])

    def test_a_brace_inside_the_argument_is_kept(self):
        self.assertEqual(_mods("[A] -> [B] @inv status in { open, closed }"),
                         [("inv", "status in { open, closed }")])
        self.assertEqual(_mods("[C] @inv one-of { x, y }"), [("inv", "one-of { x, y }")])
        self.assertEqual(_mods("[C] @inv x in { a, b } {"), [("inv", "x in { a, b }")])

    def test_a_brace_inside_the_argument_lints_clean(self):
        from sigil.analyse.lint import lint
        doc = "#!craft\n[A] -> [B] @inv status in { open, closed }\n[C] @inv one-of { x, y }\n"
        self.assertEqual(lint(doc).diagnostics, [])

    def test_no_argument_carries_a_blank(self):
        for line in ("[Y] @owns(|S|) ^4@drop {", "[Y] @inv x > 0 ^4 -> [Z]",
                     "[Y] @owns |S| @read(A) {"):
            for _name, arg in _mods(line):
                self.assertNotIn("\x00", arg or "", line)

    def test_an_argument_with_marks_inside_keeps_them(self):
        self.assertEqual(_mods("[Y] @inv a != b"), [("inv", "a != b")])
        self.assertEqual(_mods("[Y] @owns(|S|) |T|"), [("owns", "(|S|) |T|")])

    def test_the_owner_of_an_owns_block_reads_the_same(self):
        g = parse.parse_document("[Y] @owns(|S|) ^4 ! {\n  [Y] -> |S|\n}\n")
        self.assertEqual(g.nodes["Y_service"].mods, [("owns", "|S|"), ("^", "4"), ("!", None)])
        self.assertEqual(g.blocks[0].modifiers, [("owns", "|S|"), ("^", "4"), ("!", None)])


class ContinuedTrailingComment(unittest.TestCase):
    """A comment-only line whose `#` sits at the column of the trailing comment
    above it continues that comment: it is about the line above, not the next."""

    DOC = ("#!sketch\n"
           "(U) -> [A] : go({X}) => {Y}    # first part of the note\n"
           "                               # second part, aligned\n"
           "[C] -> [D] : run({X}) => {Y}\n")

    def notes(self, text):
        from sigil.core.comments import note_index
        g = parse.parse_document(text)
        return {k: [e[1] for e in v] for k, v in note_index(g).items()}

    def acks(self, text):
        from sigil.core.comments import read_acks, walk_layout
        w = walk(text)
        comments = {k + 1: v for k, v in w.comments.items()}
        return read_acks(comments, walk_layout(w), frozenset({"retry-unbounded"}))

    def test_the_walk_joins_it_to_the_trailing_comment(self):
        w = walk(self.DOC)
        self.assertEqual(w.comments, {1: ("first part of the note second part, aligned", False)})

    def test_the_note_belongs_to_the_line_above(self):
        self.assertEqual(self.notes(self.DOC),
                         {"U_actor": ["first part of the note second part, aligned"]})

    def test_a_chain_of_lines_continues_it(self):
        text = self.DOC.replace("[C]", "                               # third\n[C]", 1)
        self.assertEqual(self.notes(text)["U_actor"],
                         ["first part of the note second part, aligned third"])
        self.assertNotIn("C_service", self.notes(text))

    def test_another_column_is_a_note_on_the_next_statement(self):
        text = self.DOC.replace("                               # second", "  # second")
        self.assertEqual(self.notes(text)["C_service"], ["second part, aligned"])

    def test_a_blank_line_ends_the_continuation(self):
        text = self.DOC.replace("    # first part of the note\n",
                                "    # first part of the note\n\n")
        self.assertEqual(self.notes(text)["C_service"], ["second part, aligned"])

    def test_below_an_own_line_comment_nothing_continues(self):
        text = ("#!sketch\n[A] -> [B]\n# about C\n# still about C\n[C] -> [D]\n")
        self.assertEqual(self.notes(text)["C_service"], ["about C still about C"])

    def test_inside_a_definition_body(self):
        text = ("#!sketch\n[S] := {\n  [A] -> [B]   # first\n               # second\n"
                "  [C] -> [D]\n}\n")
        notes = self.notes(text)
        self.assertEqual(notes["A_service"], ["first second"])
        self.assertNotIn("C_service", notes)

    def test_an_acknowledgement_is_never_a_continuation(self):
        text = self.DOC.replace("# second part, aligned",
                                "# accepts: retry-unbounded — the queue drains")
        (ack,) = self.acks(text)
        self.assertEqual((ack.line, ack.names, ack.span), (3, ("retry-unbounded",),
                                                          frozenset({4})))
        self.assertEqual(self.notes(text)["U_actor"], ["first part of the note"])

    def test_the_export_describes_the_line_above(self):
        from sigil.publish import systems as em
        m = em.build_model(self.DOC, "doc")
        desc = {nid: list(c.description) for nid, c in m.components.items()}
        self.assertEqual(desc["C_service"], [])
        self.assertEqual(desc["U_actor"], ["first part of the note second part, aligned"])
