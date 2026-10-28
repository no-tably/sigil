"""SGC003 ack-unused against deeper witnesses (patch-0.6.9 C1).

The rule: an acknowledgement that covered a finding in this check is never
stale, whatever the finding's witness (a cut or a stalled join that needs two
deviations, spec's k = 2, counts as much as a static finding). A check that
explores fewer deviations than spec (craft's k = 1) cannot see such a finding,
so an acknowledgement of a deviation rule (state.DEVIATION_RULES, or a rule
whose findings carry a k) that covers nothing there is a hint that says the k,
not a stale warning: spec judges it.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_FIXTURES = ROOT / "tests" / "fixtures" / "checks"

from sigil.analyse import check as ck  # noqa: E402
from sigil.analyse.rules import state as cs  # noqa: E402


# [B] fails to arrive only when the `?>` is taken and `x.q` fails: SGC206's
# witness needs two deviations (tests/fixtures/checks/trace-206-k2.sigil).
K2_JOIN = """\
#!spec
(User) -> [S] : go()
[S] ?> [P] : p()
[P] -> [A] : a()
[P] -> (Ext) : op x.q() @timeout(1s)
     !> (User) : <Failed>
[P] -> [B] : b()
[A] & [B] -> [C] : c(){ack}
"""
ACK = "   # accepts: stalled-join — C waits for both on purpose"
JOIN_LINE = 8

# The same join, with a timeout: no run stalls it, at any k.
NO_STALL = K2_JOIN.replace("c(){ack}", "c() @timeout(1s){ack}")


def stale(report) -> list:
    """(line, severity, statement) of every SGC003 finding."""
    return [(f.line, f.severity, f.hit.statement) for f in report.findings
            if f.rule.id == "SGC003"]


def probe(name="probe", rid="TST001", lines=(), **hit_kw):
    """A rule flagging the given lines."""
    def match(_doc):
        for n in lines:
            yield ck.Hit(n, f"{name} at {n}", f"{name} at {n}?", anchor=("line", n), **hit_kw)
    return ck.Rule(rid, name, "binding", ask="Probe?", why="a test rule", fix="nothing",
                   match=match)


def run(text, *extra, mode=None, k=None):
    registry = ck.build_registry(ck.core_rules() + cs.rules(ck) + list(extra))
    return ck.check(textwrap.dedent(text).lstrip("\n"), mode=mode, k=k, registry=registry)


class TwoDeviationWitness(unittest.TestCase):
    """The repro: an acknowledged SGC206 whose witness needs k = 2."""

    def test_spec_accepts_it_and_calls_it_used(self):
        rep = ck.check(K2_JOIN.format(ack=ACK))
        self.assertEqual(stale(rep), [])
        (f,) = [f for f in rep.acknowledged if f.rule.id == "SGC206"]
        self.assertEqual((f.line, f.hit.k), (JOIN_LINE, 2))
        self.assertEqual([f for f in rep.findings if f.severity in ("warn", "error")], [])

    def test_craft_at_k2_agrees_with_spec(self):
        rep = ck.check(K2_JOIN.format(ack=ACK), mode="craft", k=2)
        self.assertEqual(stale(rep), [])
        self.assertEqual([f.rule.id for f in rep.acknowledged], ["SGC206"])

    def test_craft_at_k1_says_the_k_and_never_warns(self):
        rep = ck.check(K2_JOIN.format(ack=ACK), mode="craft")
        self.assertEqual(stale(rep), [(
            JOIN_LINE, "info",
            "the acknowledgement covers no `stalled-join` finding on its line at k = 1; "
            "a witness of 2 deviations (spec's k) may need it")])
        (f,) = [f for f in rep.findings if f.rule.id == "SGC003"]
        self.assertIn("--k 2", f.hit.fix)

    def test_without_the_ack_spec_reports_the_k2_join(self):
        rep = ck.check(K2_JOIN.format(ack=""))
        self.assertEqual([(f.line, f.hit.k) for f in rep.findings if f.rule.id == "SGC206"],
                         [(JOIN_LINE, 2)])

    def test_an_ack_nothing_needs_at_k2_is_stale_in_spec(self):
        rep = ck.check(NO_STALL.format(ack=ACK))
        self.assertEqual(stale(rep), [(
            JOIN_LINE, "warn", "the acknowledgement covers no `stalled-join` finding on its line")])

    def test_the_same_ack_is_a_hint_in_craft(self):
        rep = ck.check(NO_STALL.format(ack=ACK), mode="craft")
        self.assertEqual([sev for _, sev, _ in stale(rep)], ["info"])

    def test_spec_at_k1_is_shallow_too(self):
        rep = ck.check(K2_JOIN.format(ack=ACK), k=1)
        self.assertEqual([sev for _, sev, _ in stale(rep)], ["info"])


class CoveredIsNeverStale(unittest.TestCase):
    TEXT = "[A] -> [B] : f()   # accepts: probe — known\n"

    def test_a_k2_witness_counts_in_every_mode(self):
        for mode in ("sketch", "craft", "spec"):
            with self.subTest(mode=mode):
                rep = run(self.TEXT, probe(lines=(1,), trace=True, k=2), mode=mode)
                self.assertEqual(stale(rep), [])
                self.assertEqual([f.line for f in rep.acknowledged], [1])

    def test_a_k3_witness_counts(self):
        rep = run(self.TEXT, probe(lines=(1,), trace=True, k=3), mode="spec", k=3)
        self.assertEqual(stale(rep), [])


class StaticRulesStayStale(unittest.TestCase):
    """A rule no deviation witnesses is judged at any k: craft still warns."""

    def test_a_static_rule_warns_in_craft(self):
        rep = run("#!craft\n[A] -> [B] : f()   # accepts: probe — nothing flags this\n",
                  probe(lines=()))
        self.assertEqual(stale(rep), [(
            2, "warn", "the acknowledgement covers no `probe` finding on its line")])

    def test_a_rule_with_a_witnessed_finding_elsewhere_is_a_deviation_rule(self):
        rep = run("""
            #!craft
            [A] -> [B] : f()   # accepts: probe — the probe may flag this deeper
            [A] -> [C] : g()
            """, probe(lines=(3,), trace=True, k=1))
        self.assertEqual([(line, sev) for line, sev, _ in stale(rep)], [(2, "info")])


class DeviationRules(unittest.TestCase):
    def test_every_witnessed_finding_in_the_fixtures_is_of_a_deviation_rule(self):
        """DEVIATION_RULES names every rule whose findings carry a k (trace_hit)."""
        seen = set()
        for path in sorted(_FIXTURES.glob("*.sigil")):
            rep = ck.check(path.read_text(encoding="utf-8"), mode="spec")
            seen |= {f.rule.id for f in rep.findings + rep.acknowledged + rep.folded
                     if f.hit.k is not None}
        self.assertEqual(seen, cs.DEVIATION_RULES)


class DeclarationBlock(unittest.TestCase):
    """An acknowledgement on the line above a `#& name {` block spans the block;
    a finding with no line of its own (a cut whose entry has none) lands on the
    document's first statement, the `#&` line. A k = 2 one made the
    acknowledgement both accept it and read as stale ("covers no finding in its
    block") — the same cause as above."""
    TEXT = "#!spec\n# accepts: probe — the block\n#& foo {\n  a: b\n}\n\n[A] -> [B] : f()\n"

    def test_a_k2_finding_on_the_declaration_line_uses_the_ack(self):
        rep = run(self.TEXT, probe(lines=(3,), trace=True, k=2))
        self.assertEqual(stale(rep), [])
        self.assertEqual([f.line for f in rep.acknowledged], [3])

    def test_a_finding_outside_the_block_leaves_it_stale(self):
        rep = run(self.TEXT, probe(lines=(7,), trace=True, k=2))
        self.assertEqual([(line, s) for line, _, s in stale(rep)], [
            (2, "the acknowledgement covers no `probe` finding in its block")])


if __name__ == "__main__":
    unittest.main()
