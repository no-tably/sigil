"""A branch inside an expansion, and an arm's call, in the simulator (patch-0.6.9 B2).

The rule: a branch on a field (`branch on {X}.f`) runs in written order. Written
between two flows of one source, it decides between them (0.6.4); otherwise it
decides in the body of the source of the last flow written before it that gives
its subject (carries or returns {X}, or flows into {X}) and reaches the branch's
owner (its source or target is an arm's entry), right after that flow, and it
is no entry of its unit then (else it stays one, test_sim.TestFieldBranchInPlace). An arm's entry that has work of its own
written before the branch stays an entry of its unit. An arm's call is a call
like any other: its callee runs its expansion, body and branches in its home
unit, so its failures route, then its own part of the arm.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigil.model import sim  # noqa: E402
from sigil.model import scene  # noqa: E402
from sigil.core import parse as render  # noqa: E402

BUILDERS = ("[Builders] := {\n"
            "  [Phase] -> [Agent] : work({Job}) => {Done}\n"
            "      !> [Phase] : revert()\n"
            "}\n")

# The branch at the top: its subject comes with (User) -> [Orch].
TOP = ("#!spec\n"
       "(User) -> [Orch] : go({Job}) => {Done}\n"
       "branch on {Job}.mode {\n"
       "  run  => [Orch] -> [Builders] : assign({Job}) => {Done}\n"
       "  hold => [Orch] ~> <Waiting>\n"
       "}\n"
       "<Waiting> ~> (User) : told({Job})\n" + BUILDERS)

# Inside an expansion, after the flow that gives its subject; an arm calls Builders.
ARM_CALL = ("#!spec\n"
            "(User) -> [Run] : go({Job}) => {Done}\n"
            "[Run] := {\n"
            "  [Orch] -> [Plan] : next({Job}) => {Job}\n"
            "  branch on {Job}.mode {\n"
            "    run  => [Orch] -> [Builders] : assign({Job}) => {Done}\n"
            "    hold => [Orch] ~> <Waiting>\n"
            "  }\n"
            "  <Waiting> ~> (User) : told({Job})\n"
            "}\n" + BUILDERS)

# The arm emits; the event's flow reaches Builders.
ARM_EVENT = ("#!spec\n"
             "(User) -> [Run] : go({Job}) => {Done}\n"
             "[Run] := {\n"
             "  [Orch] -> [Plan] : next({Job}) => {Job}\n"
             "  branch on {Job}.mode {\n"
             "    run  => [Orch] ~> <Go>\n"
             "    hold => [Orch] ~> <Waiting>\n"
             "  }\n"
             "  <Go> ~> [Builders] : assign({Job})\n"
             "  <Waiting> ~> (User) : told({Job})\n"
             "}\n" + BUILDERS)

# An unconditional call written before a one-arm branch.
CALL_BEFORE = ("#!spec\n"
               "(User) -> [Run] : go({Job}) => {Done}\n"
               "[Run] := {\n"
               "  [Orch] -> [Plan] : next({Job}) => {Job}\n"
               "  [Orch] -> [Builders] : assign({Job}) => {Done}\n"
               "  branch on {Job}.mode {\n"
               "    hold => [Orch] ~> <Waiting>\n"
               "  }\n"
               "  <Waiting> ~> (User) : told({Job})\n"
               "}\n" + BUILDERS)


def build(text: str):
    return scene.build_scene(render.parse_document(text))


def run(sc, name: str = "happy"):
    return sim.simulate(sc, sim.scenario(sc, name))


def log(tr) -> list:
    return list(tr.end["log"])


def order(tr, *needles) -> list:
    """The index of the first log line holding each needle (asserting each is there)."""
    lines = log(tr)
    out = []
    for n in needles:
        hit = next((i for i, line in enumerate(lines) if n in line), None)
        assert hit is not None, (n, lines)
        out.append(hit)
    return out


def names(sc) -> list:
    return [s.name for s in sim.scenarios(sc)]


class TestBranchInPlace(unittest.TestCase):
    def test_top_level_branch_runs_in_its_subjects_episode(self):
        tr = run(build(TOP))
        self.assertEqual(tr.outcome, "ok")
        self.assertEqual([e["entry"] for e in tr.end["episodes"]], ["User_actor"])
        a, b, c = order(tr, "(User) -> [Orch]", "branch {Job}.mode: run", "[Phase] -> [Agent]")
        self.assertTrue(a < b < c)

    def test_branch_in_an_expansion_follows_the_flow_before_it(self):
        sc = build(ARM_CALL)
        tr = run(sc)
        self.assertEqual(tr.outcome, "ok")
        a, b, c, d = order(tr, "[Orch] -> [Plan]", "branch {Job}.mode: run",
                           "[Orch] -> [Builders]", "[Phase] -> [Agent]")
        self.assertTrue(a < b < c < d)

    def test_other_arm(self):
        tr = run(build(ARM_CALL), "Job.mode=hold")
        a, b = order(tr, "[Orch] -> [Plan]", "branch {Job}.mode: hold")
        self.assertLess(a, b)
        self.assertFalse(any("[Builders]" in x for x in log(tr)))

    def test_an_arms_event_reaches_the_callees_expansion(self):
        tr = run(build(ARM_EVENT))
        a, b, c = order(tr, "[Orch] -> [Plan]", "branch {Job}.mode: run", "[Phase] -> [Agent]")
        self.assertTrue(a < b < c)

    def test_a_call_written_before_the_branch_runs(self):
        tr = run(build(CALL_BEFORE))
        a, b, c, d = order(tr, "[Orch] -> [Plan]", "[Orch] -> [Builders]",
                           "[Phase] -> [Agent]", "branch {Job}.mode: hold")
        self.assertTrue(a < b < c < d)


class TestArmCallFaults(unittest.TestCase):
    def test_a_fault_inside_the_arms_callee_is_reached(self):
        for label, text in [("arm call", ARM_CALL), ("arm event", ARM_EVENT),
                            ("call before", CALL_BEFORE), ("top", TOP)]:
            with self.subTest(label):
                sc = build(text)
                self.assertIn("Phase.work:fails", names(sc))
                happy, bad = run(sc), run(sc, "Phase.work:fails")
                self.assertNotEqual(log(bad), log(happy))
                self.assertIn("[Phase] failed → [Phase]", [x[5:] for x in log(bad)])

    def test_failure_flow_reaches_the_route(self):
        prog = sim.program(sim.canonical(build(ARM_CALL).graph))
        self.assertEqual(sim.failure_analysis(prog).live,
                         frozenset({("Phase_service", "Phase_service", "!>", 0)}))

    def test_the_failure_reaches_the_arms_caller(self):
        tr = run(build(ARM_CALL), "Phase.work:fails")
        self.assertEqual(tr.outcome, "failed")
        self.assertIn("[Orch] failed: assign({Job})", [x[5:] for x in log(tr)])


class TestArmChain(unittest.TestCase):
    def test_a_chain_in_an_arm_keeps_its_arm_and_enters_expansions(self):
        sc = build("(U) -> [Api] : req({Req})\n"
                   "branch on {Req}.kind {\n"
                   "  write => [Api] -> [Store] -> |WAL|\n"
                   "  read  => [Api] -> |Cache|\n"
                   "}\n"
                   "[Store] := {\n  [Disk] -> |Block|\n}\n")
        nodes = run(sc).frames[-1].nodes
        self.assertEqual(nodes.get("WAL_store"), "visited")
        self.assertEqual(nodes.get("Block_store"), "visited")
        self.assertNotIn("Cache_store", nodes)


if __name__ == "__main__":
    unittest.main()
