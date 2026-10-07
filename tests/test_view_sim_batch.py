"""Every scenario at once (view.py --sim list / --sim all): the facts of one run
(sim_facts), the table an agent reads and diffs (sim_table, sim_list,
sim_summary), and the command line (no drawing, exit 0, --json).
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import view  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CHECKOUT = ROOT / "site" / "examples" / "01-checkout.sigil"
ORDERS = ROOT / "site" / "examples" / "04-orders.sigil"
EXECUTIONS = ROOT / "tests" / "fixtures" / "executions.sigil"
DOCS = sorted((ROOT / "site" / "examples").glob("*.sigil")) + [
    EXECUTIONS, ROOT / "tests" / "fixtures" / "coverage.sigil"]


def parse(path: Path):
    return view.kit.render.parse_document(path.read_text())


def facts(path: Path) -> list:
    return [view.sim_facts(t) for t in view.run_all(parse(path))]


def fact(name="happy", label="", outcome="ok", frames=3, **kw) -> dict:
    out = {"name": name, "label": label, "outcome": outcome, "frames": frames}
    out.update({k: kw.get(k, []) for k in view.SIM_FACTS})
    return out


class TestFacts(unittest.TestCase):
    def test_orders_machines_failures_and_routes(self):
        happy, fails = facts(ORDERS)
        self.assertEqual((happy["name"], happy["outcome"]), ("happy", "ok"))
        self.assertEqual(happy["states"], ["[Checkout] Idle", "{Order} Settled"])
        self.assertEqual(happy["failed"], [])
        self.assertEqual((fails["name"], fails["outcome"]), ("Payments:fails", "failed"))
        self.assertEqual(fails["states"], ["[Checkout] Idle", "{Order} Cancelled"])
        self.assertEqual(fails["failed"], ["[Payments]"])
        self.assertEqual(fails["routes"], ["[Payments] !> <Declined>"])

    def test_a_failing_call_names_its_wire_and_its_fallback(self):
        by = {f["name"]: f for f in facts(EXECUTIONS)}
        self.assertEqual(by["Crawler.fetch:fallback"]["failed"],
                         ["[Crawler] -> [Fetcher] ↩ fallback"])
        self.assertEqual(by["Crawler.fetch:fallback"]["outcome"], "ok")

    def test_bounds_hit_base_case_and_a_loop_at_the_cap(self):
        bounds = facts(EXECUTIONS)[0]["bounds"]
        self.assertIn("base case at [Doc.walk]", bounds)
        self.assertTrue(any(b.startswith("loop at line ") and "(the cap, no @times)" in b
                            for b in bounds), bounds)

    def test_facts_are_listed_once_in_order(self):
        for path in DOCS:
            for f in facts(path):
                for k in view.SIM_FACTS:
                    self.assertEqual(len(f[k]), len(set(f[k])), (path.name, f["name"], k))

    def test_runs_are_deterministic(self):
        self.assertEqual(facts(EXECUTIONS), facts(EXECUTIONS))


class TestTable(unittest.TestCase):
    def test_one_line_per_run_then_its_facts_then_the_summary(self):
        rows = view.sim_table(facts(ORDERS))
        self.assertTrue(rows[0].startswith("happy "))
        self.assertIn(" ok ", rows[0])
        self.assertTrue(rows[0].endswith("32 frames  every default: the happy path"))
        self.assertEqual(rows[1], "  states: [Checkout] Idle · {Order} Settled")
        self.assertIn("  failed: [Payments]", rows)
        self.assertIn("  routes: [Payments] !> <Declined>", rows)
        self.assertEqual(rows[-1], "2 scenarios: 1 ok, 1 failed, 0 cut")

    def test_lines_fit_100_columns(self):
        for path in DOCS:
            for row in view.sim_table(facts(path)):
                self.assertLessEqual(len(row), view.SIM_WIDTH, (path.name, row))

    def test_a_long_label_moves_to_its_own_line(self):
        rows = view.sim_table([fact("x", "y" * 90)], width=60)
        self.assertEqual(rows[0], "x" + " " * (view.SIM_NAME - 1) + " ok        3 frames")
        self.assertEqual(rows[1], "    " + "y" * 90)

    def test_facts_wrap_between_items_never_inside_one(self):
        rows = view.sim_table([fact(bounds=["a" * 30, "b" * 30, "c" * 30])], width=70)
        self.assertEqual(rows[1:3], [f"  bounds: {'a' * 30}", f"      {'b' * 30} · {'c' * 30}"])

    def test_a_changed_run_changes_only_its_own_lines(self):
        before = view.sim_table([fact("happy"), fact("a:fails", outcome="failed")])
        after = view.sim_table([fact("happy"), fact("a:fails", outcome="failed"),
                                fact("a.much_longer_name:fails")])
        self.assertEqual(after[:2], before[:2])

    def test_summary_counts(self):
        self.assertEqual(view.sim_summary([fact()]), "1 scenario: 1 ok, 0 failed, 0 cut")
        self.assertEqual(view.sim_summary([fact(), fact(outcome="cut")]),
                         "2 scenarios: 1 ok, 0 failed, 1 cut")

    def test_list_names_and_labels(self):
        rows = view.sim_list(view.simulator.scenarios(view.simulator.canonical(parse(CHECKOUT))))
        self.assertEqual(rows, ["happy             every default: the happy path",
                                "API.charge:fails  charge fails 4×, no fallback"])

    def test_no_scenario_is_named_list_or_all(self):
        for path in DOCS:
            names = {sc.name for sc in
                     view.simulator.scenarios(view.simulator.canonical(parse(path)))}
            self.assertFalse(names & set(view.SIM_BATCH), path.name)


class TestCommandLine(unittest.TestCase):
    def run_view(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "view.py"), *map(str, args)],
                              capture_output=True, text=True)

    def test_all_prints_the_table_and_no_drawing(self):
        res = self.run_view(ORDERS, "--once", "--sim", "all")
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout.splitlines(), view.sim_table(facts(ORDERS)))

    def test_a_failing_run_still_exits_0(self):
        res = self.run_view(CHECKOUT, "--once", "--sim", "all")
        self.assertEqual(res.returncode, 0)
        self.assertIn("1 failed", res.stdout)

    def test_list(self):
        res = self.run_view(CHECKOUT, "--once", "--sim", "list")
        self.assertEqual(res.returncode, 0)
        self.assertEqual([ln.split()[0] for ln in res.stdout.splitlines()],
                         ["happy", "API.charge:fails"])

    def test_json(self):
        res = self.run_view(ORDERS, "--once", "--sim", "all", "--json")
        data = json.loads(res.stdout)
        self.assertEqual(data["scenarios"], facts(ORDERS))
        self.assertEqual(data["summary"], "2 scenarios: 1 ok, 1 failed, 0 cut")
        res = self.run_view(ORDERS, "--once", "--sim", "list", "--json")
        self.assertEqual([s["name"] for s in json.loads(res.stdout)], ["happy", "Payments:fails"])

    def test_json_needs_sim(self):
        res = self.run_view(ORDERS, "--once", "--json")
        self.assertEqual(res.returncode, 2)
        self.assertIn("--json needs --sim", res.stderr)

    def test_json_of_one_run(self):
        """--sim NAME --json: the run's facts, its steps in plain words, its log."""
        res = self.run_view(ORDERS, "--sim", "Payments:fails", "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        data = json.loads(res.stdout)
        self.assertEqual(data["name"], "Payments:fails")
        self.assertEqual(data["outcome"], "failed")
        self.assertEqual(data["routes"], ["[Payments] !> <Declined>"])
        texts = [s["text"] for s in data["steps"]]
        self.assertTrue(texts[0].startswith("episode 1 begins at (Shopper)"))
        self.assertIn("[Payments] routes the failure to <Declined>", " ".join(texts))
        self.assertTrue(texts[-1].endswith("the run ends: failed"))
        self.assertEqual(sorted(data["steps"][0]), ["frame", "text", "tick"])
        self.assertTrue(data["log"][-1].endswith("done: failed"))

    def test_json_of_an_unknown_run_exits_2(self):
        res = self.run_view(ORDERS, "--sim", "nope", "--json")
        self.assertEqual(res.returncode, 2)
        self.assertIn("unknown scenario nope", res.stderr)


    def test_limit_raises_a_bound(self):
        res = self.run_view(EXECUTIONS, "--sim", "all", "--limit", "iterations=3")
        self.assertEqual(res.returncode, 0)
        self.assertIn("ran 3/3 (the cap, no @times)", res.stdout)
        self.assertNotIn("ran 2/2", res.stdout)

    def test_limit_rejects_an_unknown_bound(self):
        res = self.run_view(ORDERS, "--sim", "all", "--limit", "bogus=3")
        self.assertEqual(res.returncode, 2)
        self.assertIn("--limit 'bogus': unknown", res.stderr)


if __name__ == "__main__":
    unittest.main()
