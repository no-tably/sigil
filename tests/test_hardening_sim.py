"""patch-0.6.11 R3: the simulator and check stay bounded on hostile inputs
(hardening-1 probe findings #3, #7, #8, #11).

- #3  a long chain of expansions and deep `:= {` nesting check without a
      RecursionError (the program's summaries and the rules' unit walk iterate);
- #7  a `#%` line cannot set a limit past its ceiling (sim.DOC_MAX): a run
      clamps it and lint warns (SGL096); --limit still goes past it;
- #8  `[B] -> [B]` written many times: base cases count against the
      activations limit, so the work of a run stays linear in the document;
- #11 check.fold pairs findings with their causes through an index, linearly.

Run:  python3 -m unittest tests.test_hardening_sim
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigil.analyse import check as ck  # noqa: E402
from sigil.analyse.lint import lint  # noqa: E402
from sigil.analyse.rules.state import Facts  # noqa: E402
from sigil.model import sim  # noqa: E402


def make_doc(text: str):
    return ck.Doc(text, "sketch", 1, frozenset(ck.CORE_NAMES.values()))


def happy(text: str):
    """The happy run of `text` at its own limits, its last frame only."""
    d = make_doc(text)
    return sim.simulate(d.sc, sim.Scenario("happy"), limits=d.limits, keep=False)


def chain(n: int) -> str:
    """n expansions, each holding the next: [A0] := { [A1] -> [X0] } …"""
    return "".join(f"[A{i}] := {{ [A{i + 1}] -> [X{i}] }}\n" for i in range(n))


def nested(n: int) -> str:
    """n `:= {` blocks, each inside the one before."""
    return ("".join(f"[A{i}] := {{\n" for i in range(n)) + "[Z] -> [Y]\n" + "}\n" * n)


def self_loops(n: int) -> str:
    """`[A] -> [B]`, then `[B] -> [B]` written n times, then `[B] -> [C]`."""
    return "[A] -> [B]\n" + "[B] -> [B]\n" * n + "[B] -> [C]\n"


class DeepNesting(unittest.TestCase):
    """#3: depth beyond Python's recursion limit is no crash. The limit is
    lowered while each test runs, so a modest depth stands for a deep one."""

    N = 300
    LIMIT = 250                  # below N: a walk that recursed per level fails

    def setUp(self):
        self.was = sys.getrecursionlimit()
        sys.setrecursionlimit(self.LIMIT)

    def tearDown(self):
        sys.setrecursionlimit(self.was)

    def test_chain_of_expansions_checks(self):
        report = ck.check(chain(self.N), mode="sketch")
        self.assertIsNotNone(report)

    def test_chain_of_expansions_runs(self):
        self.assertIn(happy(chain(self.N)).outcome, ("ok", "cut"))

    def test_nested_blocks_check(self):
        report = ck.check(nested(self.N), mode="sketch")
        self.assertIsNotNone(report)

    def test_unit_walk_keeps_written_order(self):
        text = ("[P] := {\n  [Q] -> [R]\n  [Q] := { [S] -> [T] }\n  [R] := {\n"
                "    [U] := { [V] -> [W] }\n  }\n}\n[K] := { [L] -> [M] }\n")
        d = make_doc(text)
        want = []

        def walk(g, owner, level, top):         # the recursive walk it replaced
            want.append((owner, level, top))
            for nid, sub in g.expansions.items():
                walk(sub, nid, level + 1, top if top is not None else nid)
        walk(d.graph, None, 0, None)
        got = [(owner, level, top) for _g, owner, level, top in Facts(d).units]
        self.assertEqual(got, want)
        self.assertGreaterEqual(max(level for _o, level, _t in got), 3)


class DocumentCeiling(unittest.TestCase):
    """#7: the `#%` line's limits stop at DOC_MAX; a flag does not."""

    def test_clamped(self):
        got = sim.limits_for(("frames=1000000000", "iterations=100000000", "depth=5"))
        self.assertEqual(got.frames, sim.DOC_MAX["frames"])
        self.assertEqual(got.iterations, sim.DOC_MAX["iterations"])
        self.assertEqual(got.depth, 5)

    def test_within_unchanged(self):
        self.assertEqual(sim.usable_limits(("frames=300000", "activations=80000")),
                         ("frames=300000", "activations=80000"))

    def test_flag_goes_past(self):
        got = sim.limits_for(("frames=1000000000",), ("frames=5000000",))
        self.assertEqual(got.frames, 5000000)

    def test_lint_warns(self):
        text = "#!sketch\n#% iterations=100000000 frames=300000\n[A] -> [B]\n"
        found = [d for d in lint(text).diagnostics if d.rule == "SGL096"]
        self.assertEqual(len(found), 1, found)
        self.assertEqual(found[0].severity, "warn")
        self.assertIn("iterations", found[0].message)

    def test_huge_document_limits_run_bounded(self):
        text = ("#!sketch\n#% iterations=100000000 frames=1000000000 visits=100000000 "
                "activations=1000000000\n(U) -> [A]\nloop @times 100000000 {\n"
                "  [A] -> [B]\n  [B] -> [C]\n}\n")
        self.assertLessEqual(make_doc(text).limits.iterations, sim.DOC_MAX["iterations"])
        self.assertEqual(happy(text).outcome, "ok")


class SelfLoops(unittest.TestCase):
    """#8: base cases are bounded, so a run's events grow linearly."""

    def events(self, n: int) -> int:
        return len(happy(self_loops(n)).end["events"])

    def test_linear(self):
        small, big = self.events(40), self.events(320)
        self.assertLess(big, small * 8 * 3, (small, big))   # 8× the text: not ~64×

    def test_check_finishes(self):
        start = time.monotonic()
        ck.check(self_loops(400), mode="sketch")
        self.assertLess(time.monotonic() - start, 60)


class FoldIndex(unittest.TestCase):
    """#11: fold is linear in the findings and pairs as the pairwise rule did."""

    @staticmethod
    def finding(name: str, implies=(), scopes=()):
        rule = SimpleNamespace(name=name, implies=tuple(implies))
        hit = SimpleNamespace(scopes=tuple(scopes), anchor=("node", "X"))
        return SimpleNamespace(rule=rule, hit=hit, folded_into=None, also=[])

    def test_same_pairs_as_pairwise(self):
        f = self.finding
        found = [f("B", scopes=[("store", "S")]), f("A", [("B", "store")], [("store", "S")]),
                 f("A", [("B", "store")], [("store", "S")]), f("C", [("A", "store")],
                                                              [("store", "S")]),
                 f("B", scopes=[("store", "T")]), f("D", [("B", "missing")]),
                 f("B", scopes=[("missing", None)])]
        scopes = [ck.scopes_of(x.hit) for x in found]
        self.assertEqual(ck._causes(found, scopes), ck._causes_pairwise(found, scopes))

    def test_many_findings(self):
        n = 20000
        found = [self.finding("SGC003", scopes=[("rule", f"R{i}")]) for i in range(n)]
        found.append(self.finding("SGC001", [("SGC003", "rule")], [("rule", "R7")]))
        start = time.monotonic()
        ck.fold(found)
        self.assertLess(time.monotonic() - start, 5)
        self.assertIs(found[7].folded_into, found[-1])


if __name__ == "__main__":
    unittest.main()
