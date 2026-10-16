"""Lint's rules over the parsed document (sigil.analyse.lint.graph) report the
line the parser read the flow or transition from, not the first line whose
text looks alike."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sigil.analyse.lint.graph import lint_graph  # noqa: E402
from sigil.core.vocab import LintResult  # noqa: E402


def found(text: str) -> list:
    result = LintResult()
    lint_graph(text, result)
    return [(d.line, d.rule) for d in result.diagnostics]


class GraphRuleLines(unittest.TestCase):
    def test_unmatched_path_at_each_flow_line(self):
        text = "\n".join([
            "#!sketch",
            "# an early mention: [X]/{Gone}",
            "[Ship]",
            "    \\-& {Transform}",
            "[A] -> [Ship]/{Gone}",
            "[B] -> [Ship]/{Gone}",
        ])
        self.assertEqual(found(text), [(5, "SGL112"), (6, "SGL112")])

    def test_unmatched_path_inside_an_expansion(self):
        text = "\n".join([
            "#!sketch",
            "[Core] := {",
            "  [Ship]",
            "      \\-& {Transform}",
            "  [A] -> [Ship]/{Nope}",
            "}",
            "[Core] -> [B]",
        ])
        self.assertEqual(found(text), [(5, "SGL112")])

    def test_trigger_typo_at_its_transition_not_a_comment(self):
        text = "\n".join([
            "#!sketch",
            "[A] -> <Paid>",
            "state {Bill} {",
            "  # -<Pai>-> in a comment",
            "  z -<Pai>-> y",
            "}",
        ])
        self.assertEqual(found(text), [(5, "SGL091")])


if __name__ == "__main__":
    unittest.main()
