"""check_state.py (RFC 0003): SGC003 ack-unused — an acknowledgement that covers no
finding of a rule it names. Findings the mode hides or does not emit still count as
covered; trace findings count only with a k <= 1 witness (catalog §5).

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import re
import sys
import textwrap
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]
_FIXTURES = _DIR / "tests" / "fixtures" / "checks"


def _load(key: str, fname: str):
    spec = importlib.util.spec_from_file_location(key, _DIR / fname)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


ck = _load("sigil_check_state_suite_check", "check.py")
cs = _load("sigil_check_state_suite_state", "check_state.py")


def probe(name="probe", rid="TST001", tier="binding", lines=(), implies=(), **hit_kw):
    """A rule flagging the given lines."""
    def match(_doc):
        for n in lines:
            yield ck.Hit(n, f"{name} at {n}", f"{name} at {n}?", anchor=("line", n),
                         **hit_kw)
    return ck.Rule(rid, name, tier, ask="Probe?", why="a test rule", fix="nothing",
                   match=match, implies=implies)


def run(text, *extra, mode=None):
    registry = ck.build_registry(ck.core_rules() + cs.rules(ck) + list(extra))
    return ck.check(textwrap.dedent(text).lstrip("\n"), mode=mode, registry=registry)


def stale(report) -> list:
    """(line, message) of every SGC003 finding, hidden ones included."""
    return [(f.line, f.hit.statement) for f in report.findings if f.rule.id == "SGC003"]


def expected_of(path: Path) -> list:
    """The `# expect: LINE:RULE` lines of a fixture's header."""
    text = path.read_text(encoding="utf-8")
    return [(int(m[1]), m[2]) for m in re.finditer(r"^# expect: (\d+):(\w+)$", text, re.M)]


class Registration(unittest.TestCase):
    def test_rule_shape(self):
        (rule,) = cs.rules(ck)
        self.assertEqual((rule.id, rule.name, rule.tier), ("SGC003", "ack-unused", "advisory"))
        self.assertTrue(rule.after_acks)
        self.assertFalse(rule.acknowledgeable)

    def test_joins_the_default_registry(self):
        self.assertIn("SGC003", ck.default_registry())


class Stale(unittest.TestCase):
    def test_covering_nothing_is_stale(self):
        rep = run("""
            #!craft
            [A] -> [B] : f()   # accepts: probe — nothing flags this
            [A] -> [C] : g()
            """, probe(lines=(3,)))
        self.assertEqual(stale(rep), [
            (2, "the acknowledgement covers no `probe` finding on its line")])
        self.assertEqual(rep.findings[0].severity, "warn")

    def test_covering_a_finding_is_used(self):
        rep = run("""
            #!spec
            [A] -> [B] : f()   # accepts: probe — the probe flags this
            """, probe(lines=(2,)))
        self.assertEqual(stale(rep), [])
        self.assertEqual([f.line for f in rep.acknowledged], [2])

    def test_each_stale_name_is_reported(self):
        rep = run("""
            #!craft
            [A] -> [B] : f()   # accepts: probe, other — only the probe flags this
            """, probe(lines=(2,)), probe("other", "TST002"))
        self.assertEqual(stale(rep), [
            (2, "the acknowledgement covers no `other` finding on its line")])

    def test_a_redundant_document_acknowledgement_is_stale(self):
        rep = run("""
            #!craft
            # accepts: probe — every probe finding

            [A] -> [B] : f()   # accepts: probe — this one in particular
            """, probe(lines=(4,)))
        self.assertEqual(stale(rep), [
            (2, "the acknowledgement covers no `probe` finding in the document")])

    def test_a_block_acknowledgement_names_its_block(self):
        rep = run("""
            #!craft
            [A] {   # accepts: probe — nothing in here
              [A] -> [B] : f()
            }
            """, probe())
        self.assertEqual([m for _, m in stale(rep)],
                         ["the acknowledgement covers no `probe` finding in its block"])

    def test_the_finding_is_anchored_on_the_comment(self):
        rep = run("#!craft\n[A] -> [B] : f()   # accepts: probe — none\n", probe())
        (f,) = rep.findings
        self.assertEqual(f.hit.anchor, ("comment", 2))


class LeftToOtherRules(unittest.TestCase):
    def test_a_void_acknowledgement_is_sgc002_only(self):
        rep = run("#!craft\n[A] -> [B] : f()   # accepts: probe\n", probe())
        self.assertEqual([f.rule.id for f in rep.findings], ["SGC002"])

    def test_an_unknown_name_is_sgc001_only(self):
        rep = run("#!craft\n[A] -> [B] : f()   # accepts: prbe — typo\n", probe())
        self.assertEqual([f.rule.id for f in rep.findings], ["SGC001"])

    def test_a_meta_name_is_sgc001_only(self):
        rep = run("#!craft\n[A] -> [B] : f()   # accepts: ack-unused — keep\n")
        self.assertEqual([f.rule.id for f in rep.findings], ["SGC001"])

    def test_sgc003_itself_is_never_acknowledged(self):
        rep = run("""
            #!craft
            # accepts: probe — stale on purpose

            [A] -> [B] : f()
            """, probe())
        self.assertEqual([f.rule.id for f in rep.findings], ["SGC003"])
        self.assertEqual(rep.acknowledged, [])


class NeverFlipsOnModeOrK(unittest.TestCase):
    TEXT = "[A] -> [B] : f()   # accepts: probe — known\n"

    def test_a_hidden_sketch_finding_counts(self):
        rep = run(self.TEXT, probe(lines=(1,)), mode="sketch")
        self.assertEqual(stale(rep), [])
        self.assertEqual([f.line for f in rep.acknowledged], [1])

    def test_an_unemitted_hint_counts(self):
        rep = run(self.TEXT, probe(tier="hint", lines=(1,)), mode="sketch")
        self.assertEqual(stale(rep), [])

    def test_a_folded_finding_counts(self):
        cause = probe("cause", "TST002", lines=(1,), implies=(("probe", "line"),))
        rep = run(self.TEXT, cause, probe(lines=(1,)), mode="craft")
        self.assertEqual(stale(rep), [])

    def test_a_k1_trace_witness_counts(self):
        rep = run(self.TEXT, probe(lines=(1,), trace=True, k=1), mode="craft")
        self.assertEqual(stale(rep), [])

    def test_a_k2_only_witness_is_judged_the_same_in_every_mode(self):
        for mode in ("craft", "spec"):
            with self.subTest(mode=mode):
                rep = run(self.TEXT, probe(lines=(1,), trace=True, k=2), mode=mode)
                self.assertEqual([line for line, _ in stale(rep)], [1])

    def test_a_stale_acknowledgement_is_hidden_in_sketch(self):
        rep = run(self.TEXT, probe(), mode="sketch")
        (f,) = rep.findings
        self.assertEqual((f.rule.id, f.severity, f.hidden), ("SGC003", "info", True))


class Fixtures(unittest.TestCase):
    PROBES = (probe(lines=(10,)), probe("other-probe", "TST002"))

    def check_fixture(self, fname: str, probes: tuple):
        path = _FIXTURES / fname
        rep = ck.check(path.read_text(encoding="utf-8"),
                       registry=ck.build_registry(ck.core_rules() + cs.rules(ck)
                                                  + list(probes)))
        self.assertEqual([(f.line, f.rule.id) for f in rep.findings], expected_of(path))

    def test_flagged(self):
        self.check_fixture("state-ack-unused.sigil", self.PROBES)

    def test_declared(self):
        self.check_fixture("state-ack-unused-declared.sigil", (probe(lines=(6,)),))


if __name__ == "__main__":
    unittest.main()
