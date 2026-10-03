"""Declared invariants (RFC 0003): so far SGC173's declared-order clause, an
`@inv lock-order(|A| < |B|)` checked against the lock-order graph of
check_state.py (catalog SGC173: every acquisition against the declared order is
reported; a cycle already covered by such a report is not reported again).

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import sys
import textwrap
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]


def _load(key: str, fname: str):
    spec = importlib.util.spec_from_file_location(key, _DIR / fname)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


ck = _load("sigil_check_inv_suite_check", "check.py")
cs = _load("sigil_check_inv_suite_state", "check_state.py")


def lock_findings(text: str, mode: str = "spec") -> list:
    """(line, statement) of every SGC173 finding, the core and state rules run."""
    registry = ck.build_registry(ck.core_rules() + cs.rules(ck))
    rep = ck.check(textwrap.dedent(text).lstrip("\n"), mode=mode, registry=registry)
    return [(f.hit.line, f.hit.statement) for f in rep.findings if f.rule.id == "SGC173"]


CYCLE = """
    #!spec
    {decl}
    [P] @owns |A| {{
      [P] -> [Q]
    }}
    [Q] @owns |B| {{
      [Q] -> [P]
    }}
    """


class LockOrderChain(unittest.TestCase):

    def test_reads_resources_in_order(self):
        self.assertEqual(cs.lock_order_chain("lock-order(|A| < |B| < |C|)"),
                         ["|A|", "|B|", "|C|"])

    def test_other_heads_give_nothing(self):
        self.assertEqual(cs.lock_order_chain("serialised(|A|)"), [])

    def test_precedence_is_transitive_across_chains(self):
        order = cs.declared_precedence([["|A|", "|B|"], ["|B|", "|C|"]])
        self.assertEqual(order, {("|A|", "|B|"), ("|B|", "|C|"), ("|A|", "|C|")})


class DeclaredOrder(unittest.TestCase):

    def test_undeclared_cycle_reported_once(self):
        (hit,) = lock_findings(CYCLE.format(decl=""))
        self.assertIn("cycle", hit[1])

    def test_against_order_edge_replaces_the_cycle(self):
        found = lock_findings(CYCLE.format(decl="[P] @inv lock-order(|A| < |B|)"))
        self.assertEqual(found, [(7, "`|B|` is held while `|A|` is acquired, against "
                                     "the declared order (`|A|` before `|B|`)")])

    def test_against_order_is_binding_even_with_a_timeout(self):
        text = CYCLE.format(decl="[P] @inv lock-order(|A| < |B|)").replace(
            "[Q] -> [P]", "[Q] -> [P] @timeout(1s)")
        self.assertEqual([line for line, _s in lock_findings(text)], [7])

    def test_nested_owns_against_order(self):
        found = lock_findings("""
            #!spec
            [P] @inv lock-order(|A| < |B|)
            [P] @owns |B| {
              [P] @owns |A| {
                [P] -> |A| : put({X})
              }
            }
            """)
        self.assertEqual(len(found), 1)
        self.assertIn("`|B|` is held while `|A|`", found[0][1])

    def test_acquisitions_in_declared_order_are_clean(self):
        self.assertEqual(lock_findings("""
            #!spec
            [P] @inv lock-order(|A| < |B|)
            [P] @owns |A| {
              [P] -> [Q]
            }
            [Q] @owns |B| {
              [Q] -> |B| : put({X})
            }
            """), [])

    def test_an_order_over_other_resources_leaves_the_cycle(self):
        (hit,) = lock_findings(CYCLE.format(decl="[P] @inv lock-order(|C| < |D|)"))
        self.assertIn("cycle", hit[1])


if __name__ == "__main__":
    unittest.main()
