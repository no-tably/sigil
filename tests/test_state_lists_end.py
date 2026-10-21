"""State blocks: a trigger list `S -<a, b>-> T` reads as one transition per
trigger, and `$` takes only its own self-loops (ignored on purpose) and the `+`
transitions (a new record begins) — in the parser, lint, the simulator and the
checks alike."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigil.analyse.check import check  # noqa: E402
from sigil.analyse.lint import lint  # noqa: E402
from sigil.core import parse as render  # noqa: E402
from sigil.model import scene, sim  # noqa: E402


def machine_edges(text: str) -> list:
    g = render.parse_document(text)
    state = next(sub for sub in g.expansions.values() if sub.role == "state")
    return [(state.nodes[e.src].name, e.label, state.nodes[e.dst].name, e.line)
            for e in state.edges]


def rules(text: str) -> list:
    return [(d.line, d.rule) for d in lint(text).diagnostics]


def end_state(text: str) -> tuple:
    sc = scene.build_scene(render.parse_document(text))
    tr = sim.simulate(sc, sim.scenario(sc, "happy"))
    ignored = [e for e in tr.end["events"] if e.get("kind") == "ignored"]
    return tr.end["machines"], ignored


def findings(text: str) -> list:
    return [f.rule.id for f in check(text).findings]


ORDER = """#!sketch
[Shop] ~> <Placed>
       ~> <Paid>
       ~> <Paid>
       ~> <Placed>
state {Order} {
  +     -<Placed>->         Open
  Open  -<Paid>->           $
%s
}
"""


class TriggerLists(unittest.TestCase):
    def test_a_list_is_one_edge_per_trigger_on_its_line(self):
        text = "#!sketch\nstate {Order} {\n  Open -<cancel, expire>-> Cancelled\n}\n"
        self.assertEqual(machine_edges(text), [("Open", "<cancel>", "Cancelled", 3),
                                               ("Open", "<expire>", "Cancelled", 3)])

    def test_a_list_runs_as_the_lines_it_stands_for(self):
        listed = "#!sketch\n[A] ~> <x>\n    ~> <y>\nstate {R} {\n  + -<x>-> On\n  On -<y, z>-> Off\n}\n"
        written = listed.replace("  On -<y, z>-> Off", "  On -<y>-> Off\n  On -<z>-> Off")
        self.assertEqual(end_state(listed), end_state(written))

    def test_lint_reports_an_empty_or_repeated_item(self):
        text = "#!sketch\nstate {Order} {\n  + -<place, >-> Open\n  Open -<pay, pay>-> Paid\n}\n"
        self.assertEqual(rules(text), [(3, "SGL090"), (4, "SGL090")])


class EndState(unittest.TestCase):
    def test_a_late_event_at_end_is_dropped_and_flagged(self):
        machines, ignored = end_state(ORDER % "")
        self.assertEqual([e["label"] for e in ignored], ["<Paid>"])
        self.assertIn("SGC203", findings("#!spec\n(U) -> [Shop] : go() @sla(1s)\n"
                                         + (ORDER % "").replace("#!sketch\n", "")))

    def test_an_end_self_loop_ignores_it_on_purpose(self):
        machines, ignored = end_state(ORDER % "  $     -<Paid>->           $")
        self.assertEqual(ignored, [])
        self.assertNotIn("SGC203", findings("#!spec\n(U) -> [Shop] : go() @sla(1s)\n"
                                            + (ORDER % "  $ -<Paid>-> $").replace("#!sketch\n", "")))

    def test_a_start_event_at_end_begins_a_new_record(self):
        machines, _ignored = end_state(ORDER % "  $     -<Paid>->           $")
        self.assertEqual(machines, {"Order_data": "Order_state_Open"})

    def test_a_wildcard_does_not_reach_end(self):
        text = ORDER % "  _     -<Paid>->           Open"
        _machines, ignored = end_state(text)
        self.assertEqual([e["label"] for e in ignored], ["<Paid>"])

    def test_lint_refuses_a_way_out_of_end(self):
        self.assertEqual(rules(ORDER % "  $     -<Paid>->           Open"), [(9, "SGL092")])


if __name__ == "__main__":
    unittest.main()
