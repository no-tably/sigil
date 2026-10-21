"""The `#%` system kind: read by core (sigil.core.kinds), judged by lint (SGL093
to SGL095), and turning rule groups off in check — named in the summary, never
silent, and run anyway with all_rules."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigil.analyse import check as ck  # noqa: E402
from sigil.analyse.lint import lint  # noqa: E402
from sigil.core import kinds  # noqa: E402
from sigil.core.statements import collect_comments  # noqa: E402
from sigil.present import kit  # noqa: E402


def rules(text: str) -> list:
    return [(d.line, d.rule) for d in lint(text).diagnostics]


def ids(report) -> list:
    return sorted({f.rule.id for f in report.findings + report.acknowledged})


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


class ReadKind(unittest.TestCase):
    def test_no_line_is_the_defaults_and_turns_nothing_off(self):
        k = kinds.read_kind(["#!spec", "[A] -> [B]"])
        self.assertEqual((k.shape, k.reach, k.concurrency, k.off, k.line),
                         ("service", "networked", "concurrent", (), None))

    def test_words_pick_one_value_per_choice_and_name_their_groups(self):
        k = kinds.read_kind(["#!spec", "#% library in-process deterministic  # the TUI kit"])
        self.assertEqual((k.shape, k.reach, k.concurrency), ("library", "in-process", "deterministic"))
        self.assertEqual(k.off, ("network", "concurrency", "traffic", "entry"))

    def test_a_line_after_a_statement_is_not_read(self):
        self.assertEqual(kinds.read_kind(["#!spec", "[A] -> [B]", "#% daemon"]).shape, "service")

    def test_comments_between_mode_and_kind_are_fine(self):
        self.assertEqual(kinds.read_kind(["#!spec", "# the shop", "", "#% job"]).shape, "job")

    def test_the_kind_line_is_no_comment_and_no_title(self):
        text = "#!sketch\n#% daemon\n# Shop front\n\n[A] -> [B]\n"
        self.assertEqual(list(collect_comments(text.splitlines(), None)), [2])
        self.assertEqual(kit.doc_title(text), "Shop front")


class LintKind(unittest.TestCase):
    def test_unknown_and_doubled_words(self):
        self.assertEqual(rules("#!sketch\n#% libary job daemon\n[A] -> [B]\n"),
                         [(2, "SGL093"), (2, "SGL093")])

    def test_an_unread_line(self):
        self.assertEqual(rules("#!sketch\n[A] -> [B]\n#% job\n"), [(3, "SGL094")])

    def test_deterministic_beside_a_race(self):
        self.assertEqual(rules("#!sketch\n#% deterministic\n[A] -> [B] &? [C]\n"), [(3, "SGL095")])

    def test_a_good_line_is_quiet(self):
        self.assertEqual(rules("#!sketch\n#% daemon networked\n[A] -> [B]\n"), [])


class CheckKind(unittest.TestCase):
    def test_every_rule_has_a_known_group(self):
        self.assertTrue(set(ck.RULE_GROUPS.values()) <= set(kinds.GROUPS))
        self.assertTrue(set(ck.RULE_GROUPS) <= set(ck.CATALOG))
        self.assertTrue(all(g in kinds.GROUPS for ws in kinds.OFF.values() for g in ws))

    def test_daemon_turns_ending_off_and_says_so(self):
        plain = ck.check(CYCLE % "")
        daemon = ck.check(CYCLE % "#% daemon")
        self.assertIn("SGC144", ids(plain))
        self.assertNotIn("SGC144", ids(daemon))
        self.assertEqual(daemon.off, ("SGC144", "SGC147", "SGC152", "SGC153"))
        self.assertIn("4 rule(s) off for `#% daemon`", ck.summary(daemon))
        self.assertEqual(daemon.to_dict()["kind"], {"words": "daemon", "off": list(daemon.off)})
        self.assertNotIn("kind", plain.to_dict())

    def test_all_rules_runs_them_anyway(self):
        report = ck.check(CYCLE % "#% daemon", all_rules=True)
        self.assertIn("SGC144", ids(report))
        self.assertEqual(report.off, ())

    def test_an_acknowledgement_of_an_off_rule_is_unused(self):
        text = (CYCLE % "#% daemon").replace(
            "state {Order} {", "# accepts: no-exit — an order may reopen\nstate {Order} {")
        unused = [f for f in ck.check(text).findings if f.rule.id == "SGC003"]
        self.assertEqual(len(unused), 1)
        self.assertIn("`#% daemon` turns off", unused[0].line_text())

    def test_deterministic_makes_no_overlap_runs(self):
        self.assertEqual(ck.check(CYCLE % "").limits["overlap_runs"], "all")
        self.assertEqual(ck.check(CYCLE % "#% deterministic").limits["overlap_runs"], "off")


if __name__ == "__main__":
    unittest.main()
