"""rules.trace: the check walks the state starts (sim.state_starts, `Owner=State`).

In spec the exploration runs, after the deviation combinations and before the
overlap runs, one run per state machine and later state with a way out, on the
default choices: listed runs bounded by --budget (the overlap work cap is the
overlap runs' own). A finding only such a run shows is witnessed by its name.
--overlaps and the system kind leave them on; sketch and craft leave them off.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigil.analyse import check as ck  # noqa: E402
from sigil.analyse.rules import trace as ct  # noqa: E402
from sigil.model import sim  # noqa: E402

REGISTRY = ck.build_registry(ct.extend_rules(ck, ck.core_rules() + ck.module_rules(ck)))
FIXTURES = ROOT / "tests" / "fixtures" / "checks"


def doc(text: str) -> str:
    return textwrap.dedent(text).lstrip("\n")


# {Ticket}: + → Open on <Opened>; Open takes <Nudge> as a self-loop and goes
# to Done on <Closed>; Done reopens on <Reopen>. The happy run opens it and
# nudges it in Open. Begun in Done (`Ticket=Done`), <Nudge> finds no transition
# and is dropped: a finding only that state start shows. <Opened> meeting it
# there is the replay of how it got to Done, not a finding.
TICKET = doc("""
    #!spec
    (User) -> [Desk] : open({Ticket})
    [Desk] ~> <Opened>
    [Desk] ~> <Nudge>
    state {Ticket} {
      +    -<Opened>-> Open
      Open -<Nudge>->  Open
      Open -<Closed>-> Done
      Done -<Reopen>-> Open
    }
    """)


def make_doc(text: str, mode: str = "spec", k: int = 1, **kw):
    return ck.Doc(text, mode, k, frozenset(ck.CORE_NAMES.values()), **kw)


def of(report, rule_id: str) -> list:
    return [f for f in report.shown if f.rule.id == rule_id]


def names(ex) -> list:
    return [r.scenario.name for r in ex.runs]


class StateStartRuns(unittest.TestCase):
    def test_a_finding_only_a_state_start_shows_is_witnessed_by_its_name(self):
        (f,) = of(ck.check(TICKET, registry=REGISTRY), "SGC203")
        self.assertEqual((f.severity, f.hit.witness, f.hit.k), ("error", "Ticket=Done", 0))
        self.assertIn("`<Nudge>` reaches `{Ticket}` while it is `Done` and is dropped in the "
                      "`Ticket=Done` run", f.hit.statement)
        back = sim.scenario(make_doc(TICKET).sc, f.hit.witness)   # reads back by name
        self.assertTrue(back.machines)

    def test_walked_in_spec_only(self):
        for mode in ("sketch", "craft"):
            with self.subTest(mode=mode):
                self.assertFalse(make_doc(TICKET, mode).state_starts)
                self.assertEqual(of(ck.check(TICKET, mode=mode, registry=REGISTRY), "SGC203"),
                                 [])
        self.assertTrue(make_doc(TICKET).state_starts)

    def test_overlaps_off_and_a_deterministic_kind_leave_them_on(self):
        self.assertEqual(len(of(ck.check(TICKET, overlaps="off", registry=REGISTRY),
                                "SGC203")), 1)
        text = TICKET.replace("#!spec\n", "#!spec\n#% job in-process deterministic\n")
        self.assertEqual(len(of(ck.check(text, registry=REGISTRY), "SGC203")), 1)

    def test_they_follow_the_deviations_and_come_before_the_overlap_runs(self):
        text = (FIXTURES / "trace-204-overlap.sigil").read_text(encoding="utf-8") + TICKET
        d = make_doc(text)
        ex = ct.explore(sim, d.sc, 1, ct.BUDGET, d.limits, "all", states=True)
        got = names(ex)
        listed = [s.name for s in sim.state_starts(d.sc)]
        self.assertEqual(listed, ["Ticket=Open", "Ticket=Done"])
        at = got.index(listed[0])
        self.assertEqual(got[at:at + len(listed)], listed)
        self.assertTrue(all(not r.scenario.starts for r in ex.runs[:at + len(listed)]))
        self.assertTrue(all(r.scenario.starts for r in ex.runs[at + len(listed):]))
        for r in ex.runs[at:at + len(listed)]:
            self.assertEqual((r.k, r.scenario.starts), (0, ()))
            self.assertTrue(r.scenario.machines)

    def test_overlap_runs_are_not_multiplied_by_them(self):
        text = (FIXTURES / "trace-204-overlap.sigil").read_text(encoding="utf-8") + TICKET
        d = make_doc(text)
        on = ct.explore(sim, d.sc, 1, ct.BUDGET, d.limits, "all", states=True)
        off = ct.explore(sim, d.sc, 1, ct.BUDGET, d.limits, "all", states=False)
        overlap = lambda ex: [r.scenario.name for r in ex.runs if r.scenario.starts]
        self.assertEqual(overlap(on), overlap(off))
        self.assertFalse(any(r.scenario.machines and r.scenario.starts for r in on.runs))
        self.assertFalse(any(r.scenario.machines and r.k for r in on.runs))
        self.assertEqual((on.work, on.work_cut), (off.work, off.work_cut))   # not the work cap's

    def test_the_budget_bounds_them_and_sgc090_counts_the_unrun(self):
        d = make_doc(TICKET)
        ex = ct.explore(sim, d.sc, 1, 1, d.limits, "off", states=True)
        self.assertEqual((names(ex), ex.states_left_out), (["happy", "Ticket=Open"], 1))
        rep = ck.check(TICKET, budget=1, registry=REGISTRY)
        (f,) = [f for f in of(rep, "SGC090") if "exploration budget" in f.hit.statement]
        self.assertIn("left 1 state start (a machine begun in a later state) unrun",
                      f.hit.statement)
        self.assertIn("1 state starts", f.hit.ask)
        self.assertEqual([f for f in of(ck.check(TICKET, registry=REGISTRY), "SGC090")
                          if "exploration budget" in f.hit.statement], [])

    def test_the_replay_of_the_way_there_is_no_finding(self):
        d = make_doc(TICKET)
        ex = ct.explore(sim, d.sc, 1, ct.BUDGET, d.limits, "off", states=True)
        done = next(r for r in ex.runs if r.scenario.name == "Ticket=Done")
        dropped = [e["label"] for e in done.events if e["kind"] == "ignored"]
        self.assertEqual(sorted(dropped), ["<Nudge>", "<Opened>"])     # both dropped in Done
        (m,) = ct.trace_facts(ck, d).machines.values()
        self.assertEqual(ct.replayed(m, done), frozenset({"<Opened>", "<Closed>", "<Reopen>"}))
        self.assertEqual(ct.replayed(m, ex.runs[0]), frozenset())      # happy: none
        self.assertEqual([f.hit.statement.split(" reaches")[0]
                          for f in of(ck.check(TICKET, registry=REGISTRY), "SGC203")],
                         ["`<Nudge>`"])

    def test_off_by_default_in_explore(self):
        d = make_doc(TICKET)
        self.assertEqual(names(ct.explore(sim, d.sc, 1, ct.BUDGET, d.limits)), ["happy"])


if __name__ == "__main__":
    unittest.main()
