"""The structure checks (sigil.analyse.rules.structure): SGC176 unit-cycle (sibling
units whose flows depend on one another round) and SGC177 large-unit (a unit over
nine built members). They read the structure reading's units, so `sigil view
--structure` and `sigil check` never disagree; a flow into an enclosing unit
(`up`) is never a finding, and a part with no one home stays SGC401's."""

from __future__ import annotations

import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigil.analyse import check as ck  # noqa: E402
from sigil.analyse.rules import structure as cs  # noqa: E402
from sigil.core.parse import parse_document  # noqa: E402
from sigil.model import structure  # noqa: E402

EXAMPLES = sorted((ROOT / "site" / "examples").glob("*.sigil"))

CYCLE = """\
[Root]
  \\-> [A]
  \\-> [B]
[A] := {
  [P] -> [B] : go({X}) => {Y} @timeout(1s)
}
[B] := {
  [Q] -> [A] : go({X}) => {Y} @timeout(1s)
}
"""


def doc(text: str) -> str:
    return textwrap.dedent(text)


def run(text: str, mode=None, **kw):
    return ck.check(text, mode=mode, overlaps="off", **kw)


def ours(findings) -> list:
    return [(f.line, f.rule.id, f.severity) for f in findings
            if f.rule.id in ck.STRUCTURE_NAMES]


def big(n: int, extra: str = "") -> str:
    body = "".join(f"  [M{i}] -> [M{i + 1}] : go({{X}}) => {{Y}}\n" for i in range(n - 1))
    return f"[Big] := {{\n{body}{extra}}}\n"


class Registry(unittest.TestCase):
    def test_the_rules_match_the_catalog(self):
        reg = ck.default_registry()
        for rid, name in ck.STRUCTURE_NAMES.items():
            with self.subTest(rid):
                self.assertEqual(reg[rid].name, name)
                self.assertEqual(ck.CORE_NAMES[rid], name)
                self.assertEqual(reg[rid].tier, "advisory")
                self.assertEqual(reg[rid].layer, "structural")
        self.assertFalse(reg["SGC176"].ack_document)

    def test_loaded_with_every_check_not_only_export(self):
        self.assertLessEqual(set(ck.STRUCTURE_NAMES), set(ck.default_registry()))
        self.assertEqual(ck.idle_ids(ck.default_registry()), frozenset(ck.EXPORT_NAMES))


class UnitCycle(unittest.TestCase):
    def test_severity_by_mode(self):
        for mode, severity, hidden in (("sketch", "info", True), ("craft", "info", False),
                                       ("spec", "warn", False)):
            with self.subTest(mode):
                rep = run(CYCLE, mode)
                (f,) = [f for f in rep.findings if f.rule.id == "SGC176"]
                self.assertEqual((f.line, f.severity, f.hidden), (4, severity, hidden))

    def test_names_the_units_and_flows(self):
        (f,) = [f for f in run(CYCLE, "spec").findings if f.rule.id == "SGC176"]
        self.assertIn("`A` and `B` depend on one another in a cycle", f.message)
        self.assertIn("`[P] -> [B]` (line 5)", f.message)
        self.assertIn("`[Q] -> [A]` (line 8)", f.message)
        self.assertEqual(f.hit.anchor, ("unit", "A"))

    def test_acknowledged_on_the_units_header(self):
        text = CYCLE.replace("[A] := {", "[A] := {   # accepts: unit-cycle — one deployable")
        rep = run(text, "spec")
        self.assertEqual([f.rule.id for f in rep.acknowledged], ["SGC176"])
        self.assertEqual(ours(rep.findings), [])
        above = CYCLE.replace("[A] := {", "# accepts: unit-cycle — one deployable\n[A] := {")
        self.assertEqual([f.rule.id for f in run(above, "spec").acknowledged], ["SGC176"])

    def test_acknowledged_on_any_units_header(self):
        text = CYCLE.replace("[B] := {", "[B] := {   # accepts: unit-cycle — one deployable")
        rep = run(text, "spec")
        self.assertEqual([(f.line, f.rule.id) for f in rep.acknowledged], [(7, "SGC176")])
        self.assertEqual([f.rule.id for f in rep.findings
                          if f.rule.id in ("SGC176", "SGC003")], [])

    def test_not_acknowledged_document_wide(self):
        rep = run("# accepts: unit-cycle — everywhere\n" + CYCLE, "spec")
        self.assertEqual(ours(rep.findings), [(5, "SGC176", "warn")])
        self.assertEqual(rep.acknowledged, [])

    def test_a_nested_units_flow_lifts_to_its_enclosing_sibling(self):
        text = doc("""\
            [Root]
              \\-> [A]
              \\-> [B]
            [A] := {
              [N] -> [M] : go({X}) => {Y}
              [N] := {
                [P] -> [B] : go({X}) => {Y}
              }
            }
            [B] := {
              [Q] -> [A] : go({X}) => {Y}
            }
            """)
        self.assertEqual(ours(run(text, "spec").findings), [(4, "SGC176", "warn")])

    def test_a_flow_into_an_enclosing_unit_is_no_finding(self):
        text = doc("""\
            #!spec
            |Log|
            [Api] := {
              [A] -> |Log| : put({X}) => {Ok}
            }
            [Edge] -> |Log| : put({X}) => {Ok}
            [Edge] -> [Api] : go({X}) => {Y}
            """)
        s = structure.structure_of(parse_document(text), "t")
        self.assertTrue(s.up)
        self.assertEqual(ours(run(text).findings), [])

    def test_a_part_with_no_home_is_no_cycle(self):
        # |Db| is written in two siblings: SGC401's (with --export), never a cycle
        text = (ROOT / "tests" / "fixtures" / "checks" / "export-no-home.sigil").read_text()
        self.assertEqual(ours(run(text).findings), [])
        self.assertEqual([f.rule.id for f in run(text, export=True).findings
                          if f.rule.id.startswith("SGC4")], ["SGC401"])


class LargeUnit(unittest.TestCase):
    def test_severity_by_mode(self):
        text = big(10)
        for mode, hidden in (("sketch", True), ("craft", False), ("spec", False)):
            with self.subTest(mode):
                (f,) = [f for f in run(text, mode).findings if f.rule.id == "SGC177"]
                self.assertEqual((f.line, f.severity, f.hidden), (1, "info", hidden))
        (f,) = [f for f in run(text, "spec").findings if f.rule.id == "SGC177"]
        self.assertIn("`Big` has 10 members (over 9)", f.message)

    def test_nine_is_not_large(self):
        self.assertEqual(ours(run(big(9), "spec").findings), [])

    def test_actors_never_count(self):
        text = big(9, "  (U) -> [M0] : go({X}) => {Y}\n  [M8] -> (Os) : call({X}) => {Y}\n")
        self.assertEqual(ours(run(text, "spec").findings), [])

    def test_stores_events_and_data_count(self):
        for extra in ("  [M8] -> |S| : put({X}) => {Ok}\n", "  [M8] ~> <E>\n",
                      "  {D} -> [M0]\n"):
            with self.subTest(extra):
                self.assertEqual(ours(run(big(9, extra), "spec").findings),
                                 [(1, "SGC177", "info")])

    def test_the_top_level_says_it_on_its_first_statement(self):
        text = "#!spec\n\n" + "".join(f"[T{i}] -> [T{i + 1}] : go({{X}}) => {{Y}}\n"
                                      for i in range(10))
        (f,) = [f for f in run(text).findings if f.rule.id == "SGC177"]
        self.assertEqual(f.line, 3)
        self.assertIn("the top level has 11 members", f.message)


class OneReading(unittest.TestCase):
    """The reading and the check say the same: cycles are SGC176's, units over 9 are
    SGC177's, a name in two units is SGC401's."""

    def test_reading_and_check_agree(self):
        paths = EXAMPLES + [ROOT / "tests" / "fixtures" / "coverage.sigil",
                            ROOT / "design" / "sigil.sigil"]
        texts = [(p.name, p.read_text()) for p in paths] + [("cycle", CYCLE),
                                                             ("large", big(10))]
        for name, text in texts:
            with self.subTest(name):
                s = structure.structure_of(parse_document(text), cs.TOP_STEM)
                rep = run(text, "spec")
                found = rep.findings + rep.acknowledged
                self.assertEqual(sorted(f.hit.anchor[1] for f in found
                                        if f.rule.id == "SGC176"),
                                 sorted(c.units[0] for c in s.cycles))
                self.assertEqual(sorted(f.hit.anchor[1] for f in found
                                        if f.rule.id == "SGC177"),
                                 sorted(u.key for u in s.large))

    def test_no_example_has_a_sibling_cycle(self):
        for path in EXAMPLES:
            with self.subTest(path.name):
                self.assertNotIn("SGC176", [f.rule.id for f in run(path.read_text(),
                                                                  "spec").findings])

    def test_units_are_built_once_per_check(self):
        d = ck.Doc(CYCLE, "spec", 2, frozenset(ck.CATALOG.values()))
        self.assertIs(cs.units_of(d), cs.units_of(d))


class Idle(unittest.TestCase):
    def test_a_check_without_the_rules_knows_their_names(self):
        # the playground's check: no structure module, an acknowledgement of one
        # of its rules is neither unknown (SGC001) nor stale (SGC003)
        reg = {rid: r for rid, r in ck.default_registry().items()
               if rid not in ck.STRUCTURE_NAMES}
        self.assertEqual(ck.idle_ids(reg), frozenset(ck.EXPORT_NAMES) | set(ck.STRUCTURE_NAMES))
        text = CYCLE.replace("[A] := {", "[A] := {   # accepts: unit-cycle — one deployable")
        rep = ck.check(text, mode="spec", registry=reg, overlaps="off")
        self.assertEqual([f.rule.id for f in rep.findings
                          if f.rule.id in ("SGC001", "SGC003", "SGC176")], [])


if __name__ == "__main__":
    unittest.main()
