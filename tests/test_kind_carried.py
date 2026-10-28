"""The `#%` kind is read once, by Core's walk, and carried: Walk.kind and
Graph.kind hold it, with every `#%` line as written (placed or not), and lint
(SGL093-095) and check (the rule groups it turns off) read that record, not the
text (design/sigil.sigil round 8, move (a))."""

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigil.analyse import check as ck  # noqa: E402
from sigil.analyse.lint import lint  # noqa: E402
from sigil.analyse.lint.lines import lint_kind_line  # noqa: E402
from sigil.core import kinds  # noqa: E402
from sigil.core.kinds import Kind, KindLine  # noqa: E402
from sigil.core.parse import parse_document  # noqa: E402
from sigil.core.statements import read_document  # noqa: E402
from sigil.core.vocab import LintResult  # noqa: E402

CYCLE = """#!spec
%s
(User) -> [Shop] : go() @sla(1s)
[Shop] ~> <Placed>
       ~> <Paid>
{Order} @inv ordered(id)
state {Order} {
  +       -<Placed>-> Open
  Open    -<Paid>->   Settled
  Settled -<Placed>-> Open
}
"""


class Carried(unittest.TestCase):
    TEXT = ("#!spec\n# a job\n#% job in-process  # one shot\n"
            "[A] -> [B]\n[A] := {\n  [C] -> [D]\n}\n#% daemon\n")

    def test_the_walk_and_the_graph_carry_one_kind(self):
        walk = read_document(self.TEXT)
        self.assertEqual((walk.kind.shape, walk.kind.reach, walk.kind.line),
                         ("job", "in-process", 2))
        self.assertEqual(walk.kind, kinds.read_kind(self.TEXT.splitlines()))
        g = parse_document(self.TEXT, walk=walk)
        self.assertIs(g.kind, walk.kind)
        self.assertEqual(parse_document(self.TEXT).kind, walk.kind)

    def test_an_expansion_graph_keeps_the_defaults(self):
        g = parse_document(self.TEXT)
        self.assertTrue(g.expansions)
        for sub in g.expansions.values():
            self.assertEqual(sub.kind, Kind())

    def test_every_kind_line_is_kept_with_its_placement(self):
        k = read_document(self.TEXT).kind
        self.assertEqual(k.written, (KindLine(2, ("job", "in-process"), True),
                                     KindLine(7, ("daemon",), False)))
        self.assertEqual(k.read, k.written[0])
        self.assertEqual(k.ignored, (k.written[1],))

    def test_a_second_placed_line_is_kept_but_not_read(self):
        k = read_document("#!spec\n#% job\n#% daemon\n[A] -> [B]\n").kind
        self.assertEqual([(w.line, w.placed) for w in k.written], [(1, True), (2, True)])
        self.assertEqual((k.shape, k.line), ("job", 1))
        self.assertEqual([w.line for w in k.ignored], [2])

    def test_no_line_is_the_defaults_with_nothing_written(self):
        k = read_document("#!spec\n[A] -> [B]\n").kind
        self.assertEqual(k, Kind())
        self.assertIsNone(k.read)

    def test_a_kind_line_inside_a_block_string_is_not_one(self):
        k = read_document('#!spec\n#% job\n[A] -> [B] : """\n#% daemon\n"""\n').kind
        self.assertEqual([w.line for w in k.written], [1])

    def test_the_words_are_kept_as_written_in_order(self):
        # every word stays in `words` (a later reading, such as a `name=N` pair,
        # reads them there); the choices take only the words they know
        k = read_document("#!spec\n#% daemon frames=300000 deterministic\n[A] -> [B]\n").kind
        self.assertEqual(k.words, ("daemon", "frames=300000", "deterministic"))
        self.assertEqual((k.shape, k.concurrency), ("daemon", "deterministic"))
        self.assertEqual(k.text, "daemon frames=300000 deterministic")


class LintReadsTheRecord(unittest.TestCase):
    def test_lint_kind_line_reports_from_the_record_alone(self):
        # no `#%` in the lines: everything lint says comes from the Kind given
        lines = ["#!sketch", "[A] -> [B]", "", ""]
        written = (KindLine(2, ("libary",), True), KindLine(3, ("job",), False))
        result = LintResult()
        lint_kind_line(kinds.kind_of(written[0], written), lines, result)
        self.assertEqual([(d.line, d.rule) for d in result.diagnostics],
                         [(3, "SGL093"), (4, "SGL094")])

    def test_lint_reads_the_kind_once(self):
        text = "#!sketch\n#% daemon networked\n[A] -> [B]\n#% job\n"
        with mock.patch("sigil.core.statements.read_kind", wraps=kinds.read_kind) as spy:
            got = [(d.line, d.rule) for d in lint(text).diagnostics]
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(got, [(4, "SGL094")])

    def test_messages_are_unchanged(self):
        text = "#!sketch\n#%\n#% job\n[A] -> [B] &? [C]\n#% deterministic\n"
        got = [(d.line, d.rule, d.severity, d.message) for d in lint(text).diagnostics]
        self.assertIn((2, "SGL093", "error", "`#%` names no kind. Expected words from: "
                       "service | library | daemon | job; networked | in-process; "
                       "concurrent | deterministic."), got)
        self.assertIn((3, "SGL094", "warn", "a `#%` kind line is read only once, after the "
                       "mode line and before the first statement; this one is ignored."), got)
        self.assertIn((5, "SGL094", "warn", "a `#%` kind line is read only once, after the "
                       "mode line and before the first statement; this one is ignored."), got)
        self.assertNotIn("SGL095", [r for _l, r, _s, _m in got])


class CheckReadsTheRecord(unittest.TestCase):
    def test_check_reads_the_given_walks_kind_not_the_text(self):
        text = CYCLE % ""
        walk = read_document(text)
        daemon = kinds.kind_of(KindLine(1, ("daemon",), True), ())
        report = ck.check(text, walk=walk._replace(kind=daemon))
        self.assertEqual(report.off, ("SGC144", "SGC147", "SGC152", "SGC153"))
        self.assertIn("4 rule(s) off for `#% daemon`", ck.summary(report))

    def test_check_reads_the_document_once(self):
        text = CYCLE % "#% daemon"
        with mock.patch("sigil.core.statements.read_kind", wraps=kinds.read_kind) as spy:
            report = ck.check(text)
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(report.to_dict()["kind"],
                         {"words": "daemon", "off": ["SGC144", "SGC147", "SGC152", "SGC153"]})

    def test_deterministic_from_the_record_makes_no_overlap_runs(self):
        text = CYCLE % ""
        walk = read_document(text)
        det = kinds.kind_of(KindLine(1, ("deterministic",), True), ())
        self.assertEqual(ck.check(text, walk=walk._replace(kind=det)).limits["overlap_runs"],
                         "off")


if __name__ == "__main__":
    unittest.main()
