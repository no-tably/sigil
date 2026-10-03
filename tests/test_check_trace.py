"""check_trace.py (RFC 0003, P3 behavioural layer): SGC206 stalled-join over the
simulator's runs — the deposit half (a `&` deposit no last arrival consumed) and
the waiting half (a task still waiting at an awaited join), the 2026-10-02 probe
quiet, the catalog's example flagged and its declared twin clean.

Fixtures: tests/fixtures/checks/trace-*.sigil, each with its expected finding
lines in `# expect:` header comments (`(none)` for a quiet one).

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


ck = _load("sigil_check_for_trace", "check.py")
ct = _load("sigil_check_trace_under_test", "check_trace.py")


def doc(text: str) -> str:
    return textwrap.dedent(text).lstrip("\n")


def run(text: str, mode=None, k=None):
    registry = ck.build_registry(ct.rules(ck))
    return ck.check(doc(text), mode=mode, k=k, registry=registry)


def finding_keys(report) -> list:
    """severity:line:id for every finding the report shows."""
    return [f"{f.severity}:{f.line}:{f.rule.id}" for f in report.shown]


def expected_of(text: str) -> list:
    """The `# expect:` lines of a fixture's header ((none) for none)."""
    out = []
    for m in re.finditer(r"(?m)^#\s*expect:\s*(.+?)\s*$", text):
        if m.group(1) != "(none)":
            out.append(m.group(1))
    return out


FLAGGED = """
    #!spec
    [S] -> [A] : a()
    [S] ?> [B] : b()
    [A] & [B] -> [C] : go()
    """


class Fixtures(unittest.TestCase):
    def test_every_trace_fixture_gives_its_expected_findings(self):
        paths = sorted(_FIXTURES.glob("trace-*.sigil"))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(fixture=path.name):
                text = path.read_text(encoding="utf-8")
                rep = ck.check(text)                 # the default registry
                got = [k for k in finding_keys(rep) if k.split(":")[2].startswith("SGC2")]
                self.assertEqual(got, expected_of(text))


class StalledJoin(unittest.TestCase):
    def test_the_2026_10_02_probe_is_quiet(self):
        rep = run("""
            #!spec
            [S] -> [A] : a()
            [S] -> [B] : b()
            [A] & [B] -> [C] : go()
            """)
        self.assertEqual(rep.findings, [])

    def test_a_deposit_no_last_arrival_consumes_is_flagged(self):
        rep = run(FLAGGED)
        (f,) = rep.findings
        self.assertEqual((f.line, f.rule.name, f.severity), (4, "stalled-join", "warn"))
        self.assertEqual((f.hit.witness, f.hit.k, f.hit.trace), ("happy", 0, True))
        self.assertEqual(f.hit.anchor, ("node", "C_service"))
        self.assertIn("`[B]`", f.hit.statement)

    def test_craft_asks(self):
        (f,) = run(FLAGGED, mode="craft").findings
        self.assertEqual(f.message,
                         "`[C]` waits for `[B]` in the `happy` run. What if it never arrives?")

    def test_binding_is_capped_at_warn_until_the_sim_fixes(self):
        (f,) = run(FLAGGED).findings
        self.assertEqual((f.tier, f.severity), ("binding", "warn"))

    def test_sketch_hides_it(self):
        rep = run(FLAGGED, mode="sketch")
        self.assertEqual(rep.shown, [])
        self.assertEqual([f.severity for f in rep.findings], ["info"])

    def test_timeout_or_fallback_on_the_join_declares_it(self):
        for mod in ("@timeout(5s)", "@fallback(none)"):
            with self.subTest(mod=mod):
                text = FLAGGED.replace("go()\n", f"go() {mod}\n")
                self.assertEqual(run(text).findings, [])

    def test_another_modifier_does_not(self):
        text = FLAGGED.replace("go()\n", "go() @sla(1s)\n")
        self.assertEqual(len(run(text).findings), 1)

    def test_acknowledged(self):
        text = FLAGGED.replace("go()\n", "go()   # accepts: stalled-join — B always runs\n")
        rep = run(text)
        self.assertEqual(rep.findings, [])
        self.assertEqual([f.line for f in rep.acknowledged], [4])

    def test_one_finding_per_join_across_runs(self):
        rep = run("""
            #!spec
            [S] -> [A] : a()
            [S] ?> [B] : b()
            [S] -> [D] : d()
            [A] & [B] -> [C] : go()
            """)
        self.assertEqual([f.line for f in rep.findings], [5])

    def test_without_a_join_nothing_runs(self):
        g = ck.Doc(doc("[S] -> [A] : a()\n"), "spec", 1, frozenset()).graphs
        self.assertFalse(ct.may_hold_joins(g))
        g = ck.Doc(doc(FLAGGED), "spec", 1, frozenset()).graphs
        self.assertTrue(ct.may_hold_joins(g))


class Queries(unittest.TestCase):
    """open_joins over a run's end record: both halves, and a cut run."""

    def setUp(self):
        self.d = ck.Doc(doc("""
            [S] *> [A] & [B] : x()
            [A] -> [D] : d()
            """), "spec", 1, frozenset())
        self.policy = self.d.scene.call_policy

    def end(self, **kw):
        out = {"deposits": [], "stalled": []}
        out.update(kw)
        return out

    def run_of(self, end, outcome="ok"):
        return ct.Run(self.d.sim.Scenario("happy"), end, outcome)

    def joins(self, end, outcome="ok"):
        return ct.open_joins(self.run_of(end, outcome), self.d.prog.units,
                             self.d.sc.wires, self.policy)

    def test_a_waiting_task_is_an_open_join(self):
        (oj,) = self.joins(self.end(stalled=["S_service"]))
        self.assertEqual((oj.key, oj.line, oj.waiter, oj.missing, oj.bounded),
                         (("waiting", "S_service"), 1, "S_service", (), False))

    def test_a_waiting_task_with_a_bounded_fan_out(self):
        d = ck.Doc(doc("[S] *> [A] & [B] : x() @timeout(2s)\n"), "spec", 1, frozenset())
        (oj,) = ct.open_joins(ct.Run(d.sim.Scenario("happy"), self.end(stalled=["S_service"]),
                                     "ok"), d.prog.units, d.sc.wires, d.scene.call_policy)
        self.assertTrue(oj.bounded)

    def test_a_deposit_is_an_open_join(self):
        d = ck.Doc(doc(FLAGGED), "spec", 1, frozenset())
        deposit = {"join": (0, 0), "target": "C_service", "arrived": ["A_service"],
                   "missing": ["B_service"]}
        (oj,) = ct.open_joins(ct.Run(d.sim.Scenario("happy"), self.end(deposits=[deposit]),
                                     "ok"), d.prog.units, d.sc.wires, d.scene.call_policy)
        self.assertEqual((oj.key, oj.line, oj.missing, oj.bounded),
                         (("deposit", 0, 0, "C_service"), 4, ("B_service",), False))

    def test_both_halves_deposits_first(self):
        d = ck.Doc(doc(FLAGGED), "spec", 1, frozenset())
        deposit = {"join": (0, 0), "target": "C_service", "arrived": ["A_service"],
                   "missing": ["B_service"]}
        end = self.end(deposits=[deposit], stalled=["S_service"])
        got = ct.open_joins(ct.Run(d.sim.Scenario("happy"), end, "ok"), d.prog.units,
                            d.sc.wires, d.scene.call_policy)
        self.assertEqual([oj.key[0] for oj in got], ["deposit", "waiting"])

    def test_a_cut_run_shows_no_stall(self):
        self.assertEqual(self.joins(self.end(stalled=["S_service"]), "cut"), [])

    def test_first_witness_wins(self):
        a, b = ct.Run("a", {}, "ok"), ct.Run("b", {}, "ok")
        oj = ct.OpenJoin(("waiting", "X"), 1, "X", (), False)
        self.assertEqual(ct.first_witnesses([a, b], lambda r: [oj]), [(oj, a)])


if __name__ == "__main__":
    unittest.main()
