"""
Tests for sim's state starts: a scenario part `Owner=State` begins that owner's
machine in State, and scenarios() lists one per state with a way out after the
overlaps.
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


def build(text: str):
    return scene.build_scene(render.parse_document(text))


# [Src] emits <Go> or, as a field choice, <Back>; {Job} walks
# + → Open → Done, and from Done back to Open on <Back>.
DOC = ("[Src] -> [Work] : run({Job})\n"
       "branch on {Job}.change {\n"
       "  go   => [Work] ~> <Go>\n"
       "  back => [Work] ~> <Back>\n"
       "}\n"
       "state {Job} {\n"
       "  +    -<Go>->   Open\n"
       "  Open -<Go>->   Done\n"
       "  Done -<Back>-> Open\n"
       "  Idle -<Go>->   Idle\n"
       "}\n")


def moves(trace) -> list:
    return [(trace.scene.nodes[e["src"]].node.name if e["src"] in trace.scene.nodes else e["src"],
             trace.scene.nodes[e["dst"]].node.name)
            for e in trace.end["events"] if e["kind"] == "transition"]


def machine_ids(sc) -> tuple:
    prog = sim._program_of(sc.graph)
    (m,) = prog.machines.values()
    return m.owner, {sc.nodes[s].node.name: s for s in m.states}


class TestStateStartNames(unittest.TestCase):
    def setUp(self):
        self.sc = build(DOC)
        self.owner, self.states = machine_ids(self.sc)

    def test_a_part_names_the_machine_and_its_state(self):
        s = sim.scenario(self.sc, "Job=Done")
        self.assertEqual(s.machines, ((self.owner, self.states["Done"]),))
        self.assertEqual(s.label, "starts with {Job} in Done")
        self.assertEqual((s.choices, s.starts), ((), ()))

    def test_the_machine_begins_there(self):
        tr = sim.simulate(self.sc, sim.scenario(self.sc, "Job.change=back+Job=Done"))
        self.assertEqual(tr.frames[0].machines[self.owner], self.states["Done"])
        self.assertEqual(moves(tr), [("Done", "Open")])
        self.assertEqual(tr.outcome, "ok")

    def test_without_one_the_machine_begins_in_its_initial_state(self):
        tr = sim.simulate(self.sc, sim.scenario(self.sc, "Job.change=back"))
        self.assertEqual(moves(tr), [])            # + takes no <Back>
        self.assertEqual(tr.frames[0].machines[self.owner],
                         sim._program_of(self.sc.graph).machines[self.owner].initial)

    def test_a_field_choice_is_not_a_state_start(self):
        s = sim.scenario(self.sc, "Job.change=back")
        self.assertEqual(s.machines, ())
        self.assertTrue(s.choices)

    def test_any_state_its_block_names(self):     # listed or not: Idle has no way out
        s = sim.scenario(self.sc, "Job=Idle")
        self.assertEqual(s.machines, ((self.owner, self.states["Idle"]),))

    def test_a_later_part_wins_for_one_owner(self):
        s = sim.scenario(self.sc, "Job=Done+Job=Open")
        self.assertEqual(s.machines, ((self.owner, self.states["Open"]),))

    def test_combines_with_an_entry_start(self):
        sc = build("[A] -> [S] : a()\n[S] ~> <Go>\n[B] -> [T] : t()\n" + DOC.split("\n", 5)[5])
        s = sim.scenario(sc, "B@3+Job=Open")
        self.assertEqual(len(s.starts), 1)
        self.assertEqual(len(s.machines), 1)

    def test_an_unknown_state_lists_the_owner_s_states(self):
        for part in ("Job=Nope", "Job=$", "Job=_"):
            with self.assertRaises(KeyError) as cm:
                sim.scenario(self.sc, part)
            self.assertIn("its states: Open, Done, Idle", str(cm.exception), part)
        with self.assertRaises(KeyError):          # `+` is the combinator: `Job=` is no part
            sim.scenario(self.sc, "Job=+")

    def test_an_unknown_owner_lists_the_machines(self):
        with self.assertRaises(KeyError) as cm:
            sim.scenario(self.sc, "Nobody=Open")
        self.assertIn("a state start is Owner=State: Job in Open, Done, Idle", str(cm.exception))

    def test_the_engine_refuses_a_state_the_machine_lacks(self):
        bad = sim.Scenario("bad", machines=((self.owner, "nowhere"),))
        with self.assertRaises(KeyError):
            sim.simulate(self.sc, bad)
        with self.assertRaises(KeyError):
            sim.simulate(self.sc, sim.Scenario("bad", machines=(("nobody", "x"),)))


class TestListedStateStarts(unittest.TestCase):
    def test_one_per_later_state_with_a_way_out_after_the_rest(self):
        sc = build(DOC)
        names = [s.name for s in sim.scenarios(sc)]
        self.assertEqual(names[-2:], ["Job=Open", "Job=Done"])   # not +, not Idle
        self.assertEqual([s.name for s in sim.state_starts(sc)], ["Job=Open", "Job=Done"])

    def test_a_wildcard_is_a_way_out(self):
        sc = build("[A] ~> <Go>\nstate {M} {\n  + -<Go>-> One\n  One -<Go>-> One\n"
                   "  _ -<Reset>-> Two\n}\n")
        self.assertEqual([s.name for s in sim.state_starts(sc)], ["M=One"])   # Two: the wildcard only leads back to it

    def test_the_initial_state_is_not_listed(self):
        sc = build("[A] ~> <Go>\nstate {M} {\n  One -<Go>-> Two\n  Two -<Go>-> One\n}\n")
        self.assertEqual([s.name for s in sim.state_starts(sc)], ["M=Two"])

    def test_within_the_scenario_limit(self):
        sc = build(DOC)
        n = len(sim.scenarios(sc))
        lim = sim.Limits(scenarios=n - 1)
        self.assertEqual([s.name for s in sim.scenarios(sc, limits=lim)][-1], "Job=Open")

    def test_no_machine_lists_none(self):
        self.assertEqual(sim.state_starts(build("[A] -> [B] : b()\n")), [])

    def test_every_listed_start_runs(self):
        sc = build(DOC)
        for s in sim.state_starts(sc):
            self.assertIn(sim.simulate(sc, s).outcome, ("ok", "failed"), s.name)


class TestCorpus(unittest.TestCase):
    CORPUS = (sorted((ROOT / "site" / "examples").glob("*.sigil"))
              + [ROOT / "tests" / "fixtures" / "executions.sigil",
                 ROOT / "tests" / "fixtures" / "coverage.sigil"])

    def test_the_examples(self):
        sc = build((ROOT / "site" / "examples" / "04-orders.sigil").read_text())
        listed = [s.name for s in sim.scenarios(sc)]
        self.assertEqual(listed[-2:], ["Checkout=Busy", "Order=Open"])   # last, in written order
        sc = build((ROOT / "site" / "examples" / "02-shop.sigil").read_text())
        self.assertEqual(sim.state_starts(sc), [])

    def test_every_listed_start_begins_there_and_reads_back(self):
        for path in self.CORPUS:
            sc = build(path.read_text())
            for s in sim.state_starts(sc):
                with self.subTest(doc=path.name, scenario=s.name):
                    self.assertEqual(sim.scenario(sc, s.name), s)
                    tr = sim.simulate(sc, s)
                    ((owner, state),) = s.machines
                    self.assertEqual(tr.frames[0].machines[owner], state)
                    self.assertTrue(sim.narrate(tr)[0].text.startswith(
                        s.label.replace("starts with ", "").replace(" in ", " starts in ", 1)))


class TestNarration(unittest.TestCase):
    def test_the_first_line_says_where_the_machine_starts(self):
        sc = build(DOC)
        beats = sim.narrate(sim.simulate(sc, sim.scenario(sc, "Job=Done")))
        self.assertTrue(beats[0].text.startswith("{Job} starts in Done; episode 1 begins"))

    def test_the_log_says_it_at_setup(self):
        sc = build(DOC)
        log = sim.simulate(sc, sim.scenario(sc, "Job=Done")).end["log"]
        self.assertTrue(any(line.endswith("starts: {Job} in Done") for line in log[:3]), log[:3])

    def test_no_start_no_line(self):
        sc = build(DOC)
        beats = sim.narrate(sim.simulate(sc, sim.scenario(sc, "happy")))
        self.assertNotIn("starts in", beats[0].text)


if __name__ == "__main__":
    unittest.main()
