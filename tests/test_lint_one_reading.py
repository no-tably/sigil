"""`sigil lint` reads a document once: one statement walk, each statement
tokenized once, each line's code read once — the rules and the parser judge that
reading (sigil.analyse.lint.reading), nothing reads the text again."""

import io
import sys
import tempfile
import types
import unittest
from collections import Counter
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sigil.analyse import lint  # noqa: E402
from sigil.analyse.lint import reading  # noqa: E402
from sigil.core import parse, statements  # noqa: E402

DOC = """#!spec
--- Shop ---
(Buyer) -> [Shop] : browse() @timeout(2s)
[Shop] @read(Buyer) -> |Cart| : {items: [], total: 0}
[Shop] := {
  [Cart] -> [Pay] : charge ×3 Retry   # retried
    -> [Ledger]
  loop @each {Item} { [Cart] -> [Stock] }
}
Retry := @after(1s)
state {Order} {
  new -<pay>-> paid
}
[Ship]
    \\-& {Transform}
[A] -> [B] : \"\"\"
a block string
\"\"\"
"""


def counted(stack: ExitStack, counts: Counter, module, name: str):
    """Wrap module.name so each call is counted under `name`."""
    real = getattr(module, name)

    def wrapper(*args, **kwargs):
        counts[name] += 1
        return real(*args, **kwargs)
    stack.enter_context(mock.patch.object(module, name, wrapper))


def reading_calls(run) -> Counter:
    """What `run()` costs in readings: walks, folds, line codes, statement tokens."""
    counts: Counter = Counter()
    with ExitStack() as stack:
        for name in ("read_lines", "fold_block_strings", "code_line", "tokenize_statement"):
            counted(stack, counts, statements, name)
        run()
    return counts


class OneReading(unittest.TestCase):
    def test_lint_walks_the_document_once(self):
        walked = reading_calls(lambda: statements.read_document(DOC))
        linted = reading_calls(lambda: lint.lint(DOC))
        self.assertEqual(linted["read_lines"], 1)
        self.assertEqual(linted["fold_block_strings"], 1)
        self.assertGreater(walked["tokenize_statement"], 5)
        self.assertEqual(linted, walked)

    def test_a_line_view_is_its_code_where_nothing_is_blanked(self):
        walk = statements.read_document(DOC)
        views = reading.line_views(walk, {})
        for k, (view, code) in enumerate(zip(views, walk.codes)):
            self.assertEqual(view.plain, code.text, k)
            if "@read" not in code.raw:
                self.assertEqual(view.bare, code.text, k)

    def test_the_branch_markers_read_past_are_blanked(self):
        walk = statements.read_document("#!sketch\n[Ship]\n    \\-& {T}\n")
        views = reading.line_views(walk, {2: [(4, 7)]})
        self.assertEqual(views[2].plain, "        {T}")

    def test_state_lines_run_from_head_to_close(self):
        walk = statements.read_document(DOC)
        self.assertEqual(reading.state_lines(walk.doc), frozenset({11, 12, 13}))
        walk = statements.read_document("#!sketch\n[X] := {\n  state {J} {\n    a -<go>-> b\n")
        self.assertEqual(reading.state_lines(walk.doc), frozenset({3, 4}))


def rules(text: str) -> list:
    return [(d.line, d.rule) for d in lint.lint(text).diagnostics]


class ReadAsTheWalkReads(unittest.TestCase):
    """The per-line rules judge the walk's reading (one-walk DIVERGENCES.md)."""

    def test_a_string_holds_no_code(self):
        # D1: an arrow, a glyph, an actor or a `;` inside a string is string text.
        doc = ('#!sketch\n[A] -> [B] : "x <- y"\n[A] -> [C] : "[A] then [A]"\n'
               '[A] -> [D] : "(done)"\n[A] -> [E] : "a; b"\n')
        self.assertEqual(rules(doc), [])

    def test_a_principal_named_only_in_a_string_is_not_declared(self):
        doc = '#!sketch\n[A] -> [B] : "(Ghost)"\n|T| @read(Ghost)\n'
        self.assertEqual(rules(doc), [(3, "SGL143")])

    def test_access_lists_are_modifier_tokens_of_flows_and_headers(self):
        doc = ("#!sketch\n[A] -> |S|\n|S| @read(A, A) @borrow(x)\n"
               "loop @times(2) @read(Ghost) {\n  [A] -> |S|\n}\n")
        self.assertEqual(rules(doc), [(3, "SGL141"), (3, "SGL144"), (4, "SGL143")])

    def test_an_access_list_member_is_quoted_as_written(self):
        # A comma inside a string splits no member; the message quotes the string.
        def said(doc):
            return [(d.rule, d.message) for d in lint.lint(doc).diagnostics]
        found = said('#!sketch\n[A] -> |S|\n|S| @read(A, "B, C")\n')
        self.assertEqual([rule for rule, _ in found], ["SGL142"])
        self.assertIn("""list member '"B, C"'""", found[0][1])
        found = said('#!sketch\n[A] -> |S|\nloop @times(2) @write("A", A) {\n'
                     '  [A] -> |S|\n}\n')
        self.assertEqual([rule for rule, _ in found], ["SGL142"])
        self.assertIn("""list member '"A"'""", found[0][1])

    def test_a_borrow_argument_is_quoted_as_written(self):
        found = [(d.rule, d.message) for d in
                 lint.lint('#!sketch\n[A] -> |S|\n|S| @borrow("rw x")\n').diagnostics]
        self.assertEqual([rule for rule, _ in found], ["SGL144"])
        self.assertIn('`@borrow("rw x")`', found[0][1])

    def test_a_state_line_has_one_reading(self):
        # The walk's Transition is what the model builds and what SGL161 / SGL090 judge.
        doc = ("#!sketch\nstate {X} {\n  + -<go>-> A\n  A -> B\n  A -<>-> C\n"
               "  A-<x>->B\n  hello\n  \"a\" -> B\n}\n")
        w = statements.read_document(doc)
        self.assertEqual([t.kind for t in w.transitions],
                         ["triggered", "untriggered", "untriggered", "malformed", "unread",
                          "untriggered"])
        self.assertEqual(sorted(rules(doc)), [(4, "SGL161"), (5, "SGL090"), (5, "SGL161"),
                                      (6, "SGL090"), (7, "SGL161"), (8, "SGL161")])
        said = {d.line: d.message for d in lint.lint(doc).diagnostics if d.rule == "SGL161"}
        self.assertIn('`"a" -> B`', said[8])
        g = parse.parse_document(doc)
        self.assertEqual(sorted(d.line for d in g.dropped), [6, 7])

    def test_an_owner_less_machine_is_reported_once(self):
        doc = "#!sketch\nstate {\n  a -> b\n  c -<x d\n}\n"
        self.assertEqual(statements.read_document(doc).transitions, ())
        self.assertEqual(rules(doc), [(2, "SGL161")])

    def test_a_marker_is_judged_where_a_branch_stands(self):
        # D4: a malformed `\-` at a statement's start is SGL110; in prose or a
        # payload it is text.
        self.assertEqual(rules("#!sketch\n[Ship]\n    \\-% {T}\n"),
                         [(3, "SGL110"), (3, "SGL131")])   # `-` is then no arrow
        self.assertEqual(rules("#!sketch\n[A] -> [B] : note \\-% here\n"), [])

    def test_a_branch_the_model_hangs_under_nothing(self):
        self.assertEqual(rules("#!sketch\n\\-& {Orphan}\n"), [(2, "SGL111")])
        self.assertEqual(rules("#!sketch\n[Ship]\n    \\-& {T}\n"), [])

    def test_state_membership_is_the_walk_s(self):
        # D9: `state Foo {` is a machine with no owner, its lines are no flows.
        doc = "#!sketch\nstate Order {\n  A -<x>-> B\n  (done)\n}\n"
        self.assertEqual(rules(doc), [(2, "SGL161")])
        self.assertEqual(rules("#!sketch\n[A] -> (done)\n"), [(2, "SGL020")])

    def test_a_payload_is_the_statement_s(self):
        # D12: one payload a statement, its call part and each later `: …`; a
        # colon inside a map or a modifier argument starts none.
        self.assertEqual(rules("#!sketch\n[A] -> [B] : {a: 1, b}\n"), [(2, "SGL100")])
        self.assertEqual(rules("#!sketch\n[A] @inv unique:email -> [B] : {X}\n"), [])
        self.assertIn((2, "SGL100"),
                      rules("#!sketch\n[A] -> [B] : f() => [C] : {a: 1, b}\n"))


def _dialect(**hooks):
    d = types.ModuleType("toy_lint_walk_dialect")
    d.NAME = "toy"
    for k, v in hooks.items():
        setattr(d, k, v)
    return d


class TheWalkAlone(unittest.TestCase):
    """What lint reads beside the statements is the walk's record too."""

    def test_a_reserved_marker_is_where_the_walk_cut_the_comment(self):
        self.assertEqual(rules("#!sketch\n[A] -> [B] #= x\n#= alone\n"),
                         [(2, "SGL188"), (3, "SGL188")])
        self.assertEqual(rules('#!sketch\n[A] -> [B] # = x\n[A] -> [C] : "#= x"\n'), [])

    def test_a_dialect_comment_marker_starts_the_comment(self):
        d = _dialect(COMMENT_MARKERS=[r"//"])
        said = lambda doc: [(x.line, x.rule) for x in lint.lint(doc, dialect=d).diagnostics]
        self.assertEqual(said("#!sketch\n[A] -> [B] // see #= x\n"), [])
        self.assertEqual(said("#!sketch\n[A] -> [B] #= x // y\n"), [(2, "SGL188")])

    def test_principals_are_declared_by_what_the_walk_read(self):
        # A state owner, a definition head, a trigger and a layer section's glyph
        # declare a name; an access list's members and a branch condition do not.
        doc = ("#!sketch\nstate {Job} {\n  + -<pay>-> Open\n}\n[Shop] := {\n  [A] -> [B]\n}\n"
               "|S| @read(Job, pay, Shop)\n")
        self.assertEqual(rules(doc), [])
        doc = ("#!sketch\n[Ship]\n    \\-{hot}-? [Cache]\n|S| @read(hot, Ghost)\n"
               "|T| @write(Ghost)\n")
        self.assertEqual(rules(doc), [(4, "SGL143"), (4, "SGL143"), (5, "SGL143")])

    def test_lint_deep_reads_the_document_once(self):
        from sigil import cli
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "doc.sigil"
            path.write_text(DOC, encoding="utf-8")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                counts = reading_calls(lambda: cli.main(["lint", "--deep", str(path)]))
        self.assertEqual(counts["read_lines"], 1)
        self.assertEqual(counts["fold_block_strings"], 1)


if __name__ == "__main__":
    unittest.main()
