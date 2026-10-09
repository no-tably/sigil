"""Tests for the run at a depth (--depth) and the run ruler's scale spacing.

Covers:
  - sim.folded_hosts: each node inside a folded expansion with the drawn node
    standing for it (none at --depth all);
  - sim.timeline(hosts=…): a folded node's lanes fold into its host's lane —
    its work is the host's (absorbed into the host's span), a hop inside the
    fold is not drawn, a hop across it leaves or reaches the host's lane;
  - sim.narrate / sim.hops (hosts=…): name only the drawn nodes (no hidden
    [Checkout] at --depth 0), leave out what happens wholly inside a fold;
  - view_run.compose_run(depth=…): the lanes drawn, the notes naming hosts;
  - a fold's own task (an emit inside the expansion) on the host's lane: one
    activation, marked folded, not another run of the host (no `runs 3×`,
    no ∥ row);
  - view.py --once: the run folds only when --depth is given (the default draws
    and tells every level, as --json does);
  - the ruler: the scale's labels and ≈ keep two blanks apart (no `100 104`).

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import re
import sys
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]


def _load(name: str, fname: str):
    spec = importlib.util.spec_from_file_location(name, _DIR / fname)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


view = _load("sigil_view_run_depth_tests", "view.py")
vrun, kit, sim = view.vrun, view.kit, view.simulator

SHOP = _DIR / "site" / "examples" / "02-shop.sigil"
EXAMPLES = sorted((_DIR / "site" / "examples").glob("*.sigil"))
EXECUTIONS = _DIR / "tests" / "fixtures" / "executions.sigil"
HIDDEN_AT_0 = ("[Cart]", "[Checkout]", "[Payments]", "[Gateway]", "[Risk]", "[Model]",
               "|Features|", "{Verdict}", "[Picker]", "[Packer]", "(Courier)")


def parse(path: Path):
    return view.render.parse_document(path.read_text())


def run_of(g, name: str = "happy"):
    canon = sim.canonical(g)
    return canon, sim.simulate(canon, sim.scenario(canon, name))


def labels(rows) -> list:
    """The lane labels of the run view's rows (the text before the bars)."""
    out = []
    for r in rows:
        text = "".join(t for t, _ in r) if isinstance(r, list) else ""
        m = re.match(r"^[ ▸]{2}\s*([\[(|{<][^\]\)|}>]*[\])|}>])", text)
        if m:
            out.append(m.group(1))
    return out


class FoldedHostsTest(unittest.TestCase):
    def setUp(self):
        self.canon = sim.canonical(parse(SHOP))

    def test_all_levels_drawn_fold_nothing(self):
        self.assertEqual(sim.folded_hosts(self.canon, kit.ALL_DEPTH), {})

    def test_depth_0_folds_into_the_top_level_node(self):
        hosts = sim.folded_hosts(self.canon, 0)
        self.assertEqual(hosts["Checkout_service"], "Shop_service")
        self.assertEqual(hosts["Model_service"], "Shop_service")
        self.assertEqual(hosts["Courier_actor"], "Fulfilment_service")
        self.assertNotIn("Shop_service", hosts)
        self.assertNotIn("OrderPlaced_event", hosts)

    def test_depth_1_folds_into_the_nearest_drawn_node(self):
        hosts = sim.folded_hosts(self.canon, 1)
        self.assertEqual(hosts["Gateway_service"], "Payments_service")
        self.assertEqual(hosts["Verdict_data"], "Payments_service")
        self.assertNotIn("Checkout_service", hosts)


class FoldedTimelineTest(unittest.TestCase):
    def timeline(self, path: Path, depth: int, name: str = "happy"):
        canon, tr = run_of(parse(path), name)
        return sim.timeline(tr, hosts=sim.folded_hosts(canon, depth))

    def test_no_lane_of_a_folded_node(self):
        tl = self.timeline(SHOP, 0)
        nodes = {ln.node for ln in tl.lanes}
        self.assertEqual(nodes, {"Shopper_actor", "Edge_service", "Shop_service",
                                 "OrderPlaced_event", "Catalog_store", "Fulfilment_service",
                                 "Ledger_store"})

    def test_moves_stay_between_drawn_lanes(self):
        for depth in (0, 1):
            tl = self.timeline(SHOP, depth)
            keys = {ln.key for ln in tl.lanes}
            for m in tl.moves:
                self.assertTrue(set(m.src) <= keys and set(m.dst) <= keys, m)
                self.assertFalse(set(m.src) & set(m.dst), m)

    def test_a_hop_across_the_fold_leaves_the_hosts_lane(self):
        tl = self.timeline(SHOP, 0)
        emit = [m for m in tl.moves if m.kind == "~>"]
        self.assertEqual([m.src for m in emit], [(("Shop_service", None, 1),)])

    def test_the_host_works_while_its_fold_does(self):
        """[Cart] works at its enter tick: folded, [Shop] does instead of waiting."""
        full = self.timeline(SHOP, kit.ALL_DEPTH)
        cart = next(s for s in full.spans if s.node == "Cart_service")
        shop_full = next(s for s in full.spans if s.node == "Shop_service")
        shop = next(s for s in self.timeline(SHOP, 0).spans if s.node == "Shop_service")
        waiting = lambda s: {t for a, b in s.waits for t in range(a, b)}
        self.assertIn(cart.enter, waiting(shop_full))
        self.assertNotIn(cart.enter, waiting(shop))
        self.assertLess(len(waiting(shop)), len(waiting(shop_full)))
        self.assertEqual(len([s for s in self.timeline(SHOP, 0).spans
                              if s.lane == shop.lane]), 1)   # no ∥ sub-row of its own fold

    def test_every_example_and_scenario_folds_consistently(self):
        for path in EXAMPLES:
            g = parse(path)
            canon = sim.canonical(g)
            for sc in sim.scenarios(canon):
                tr = sim.simulate(canon, sc)
                for depth in (0, 1):
                    hosts = sim.folded_hosts(canon, depth)
                    tl = sim.timeline(tr, hosts=hosts)
                    with self.subTest(path=path.name, scenario=sc.name, depth=depth):
                        self.assertFalse({ln.node for ln in tl.lanes} & hosts.keys())
                        keys = {ln.key for ln in tl.lanes}
                        self.assertTrue({s.lane for s in tl.spans} <= keys)
                        for m in tl.moves:
                            self.assertTrue(set(m.src) | set(m.dst) <= keys, m)


class FoldedNarrationTest(unittest.TestCase):
    def setUp(self):
        self.canon, self.trace = run_of(parse(SHOP))

    def test_depth_0_beats_name_only_drawn_nodes(self):
        text = " ".join(b.text for b in sim.narrate(self.trace, sim.folded_hosts(self.canon, 0)))
        for name in HIDDEN_AT_0:
            self.assertNotIn(name, text)
        self.assertIn("[Shop] emits <OrderPlaced>", text)
        self.assertIn("[Edge] calls [Shop] with {Request}", text)

    def test_without_hosts_every_node_is_named(self):
        text = " ".join(b.text for b in sim.narrate(self.trace))
        self.assertIn("[Checkout] emits <OrderPlaced>", text)
        self.assertEqual(sim.narrate(self.trace), sim.narrate(self.trace, {}))

    def test_depth_0_hops_are_between_drawn_nodes(self):
        hosts = sim.folded_hosts(self.canon, 0)
        hs = sim.hops(self.trace, hosts)
        self.assertFalse({h.src for h in hs} & hosts.keys())
        self.assertFalse({h.dst for h in hs} & hosts.keys())
        self.assertIn(("Shop_service", "~>", "OrderPlaced_event"),
                      [(h.src, h.kind, h.dst) for h in hs])
        self.assertLess(len(hs), len(sim.hops(self.trace)))

    def test_depth_1_names_the_expansion_but_not_deeper(self):
        text = " ".join(b.text for b in sim.narrate(self.trace, sim.folded_hosts(self.canon, 1)))
        self.assertIn("[Checkout] calls [Payments]", text)
        self.assertNotIn("[Gateway]", text)
        self.assertNotIn("[Risk]", text)

    def test_folded_failures_name_no_hidden_node(self):
        for sc in sim.scenarios(self.canon):
            tr = sim.simulate(self.canon, sc)
            text = " ".join(b.text for b in sim.narrate(tr, sim.folded_hosts(self.canon, 0)))
            with self.subTest(scenario=sc.name):
                for name in HIDDEN_AT_0:
                    self.assertNotIn(name, text)


class ComposeRunDepthTest(unittest.TestCase):
    def drawn(self, depth=None, **kw):
        g = parse(SHOP)
        args = {} if depth is None else {"depth": depth}
        rows, _w = vrun.compose_run(g, None, None, 140, **args, **kw)
        return rows

    def test_depth_0_draws_the_top_level_lanes(self):
        ls = labels(self.drawn(0))
        self.assertEqual(ls, ["(Shopper)", "[Edge]", "[Shop]", "<OrderPlaced>", "|Catalog|",
                              "[Fulfilment]", "|Ledger|"])

    def test_depth_1_folds_the_second_level(self):
        ls = labels(self.drawn(1))
        self.assertIn("[Payments]", ls)
        self.assertIn("[Checkout]", ls)
        self.assertNotIn("[Gateway]", ls)
        self.assertNotIn("{Verdict}", ls)

    def test_default_draws_every_level(self):
        self.assertIn("[Model]", labels(self.drawn()))

    def test_depth_0_notes_name_the_host(self):
        text = "\n".join("".join(t for t, _ in r) for r in self.drawn(0) if isinstance(r, list))
        shop = next(ln for ln in text.splitlines() if ln.lstrip().startswith("[Shop]"))
        self.assertIn("emits <OrderPlaced>", shop)
        for name in HIDDEN_AT_0:
            self.assertNotIn(name, text)

    def test_json_at_a_depth(self):
        canon, tr = run_of(parse(SHOP))
        data = vrun.timeline_json(tr, depth=0)
        self.assertNotIn("[Cart]", [ln["label"] for ln in data["lanes"]])
        self.assertIn("[Cart]", [ln["label"] for ln in vrun.timeline_json(tr)["lanes"]])


class OnceRunDepthTest(unittest.TestCase):
    """The run (its lanes, narration and path) folds only when --depth is given."""

    def printed(self, *extra) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            view.main([str(SHOP), "--once", "--run", "--sim", "Risk?>Review", "--no-lint",
                       "--color", "never", "--width", "140", *extra])
        return out.getvalue()

    def test_default_draws_and_tells_every_level(self):
        text = self.printed()
        ls = labels([[(ln, None)] for ln in text.splitlines()])
        for name in ("[Gateway]", "[Risk]", "[Model]", "{Verdict}", "[Review]"):
            self.assertIn(name, ls)
        self.assertIn("[Risk] takes the optional path to [Review]", text)

    def test_depth_given_folds(self):
        text = self.printed("--depth", "1")
        ls = labels([[(ln, None)] for ln in text.splitlines()])
        self.assertIn("[Payments]", ls)
        for name in ("[Gateway]", "[Risk]", "[Review]"):
            self.assertNotIn(name, ls)
        self.assertNotIn("[Risk] takes", text)


API = """#!spec
(User) -> [Api]
[Api] -> |Db|
[Api] := {
  [In] -> [Out]
  [Out] ~> <Done> -> [Bg]
  [Bg] -> |Db|
}
"""


class FoldedTaskTest(unittest.TestCase):
    """[Api] called once; its expansion's emit runs [Bg] on a task of its own."""

    def setUp(self):
        self.g = view.render.parse_document(API)
        self.canon, self.tr = run_of(self.g)
        self.tl = sim.timeline(self.tr, hosts=sim.folded_hosts(self.canon, 0))

    def api_spans(self):
        return [s for s in self.tl.spans if s.lane[0] == "Api_service"]

    def test_the_folds_task_is_one_folded_activation(self):
        spans = self.api_spans()
        self.assertEqual([s.folded for s in spans], [False, True])
        self.assertEqual(len({s.lane for s in spans}), 1)       # no ∥ sub-row

    def test_the_folded_activation_works_while_its_fold_does(self):
        folded = self.api_spans()[1]
        bg = next(s for s in sim.timeline(self.tr).spans if s.node == "Bg_service")
        waits = {t for a, b in folded.waits for t in range(a, b)}
        self.assertTrue(set(range(bg.enter, bg.enter + 1)).isdisjoint(waits))

    def test_the_moves_leave_the_hosts_lane(self):
        lanes = {ln.key for ln in self.tl.lanes}
        for m in self.tl.moves:
            self.assertTrue(set(m.src) | set(m.dst) <= lanes)

    def test_the_lane_says_it_ran_once(self):
        rows, _w = vrun.compose_run(self.g, None, None, 140, depth=0)
        text = "\n".join("".join(t for t, _ in r) for r in rows if isinstance(r, list))
        api = next(ln for ln in text.splitlines() if ln.lstrip().startswith("[Api]"))
        self.assertNotIn("runs", api)
        self.assertNotIn("∥", text)

    def test_json_marks_the_folded_activation(self):
        data = vrun.timeline_json(self.tr, depth=0)
        self.assertEqual(sum(1 for s in data["spans"] if s.get("folded")), 1)


class RulerScaleGapTest(unittest.TestCase):
    def mark(self, col, text, scale=True):
        return vrun._Mark(col, text, None, scale=scale)

    def test_scale_labels_keep_two_blanks(self):
        placed = vrun._place([self.mark(0, "100"), self.mark(4, "104")], 0, 20, None)
        self.assertEqual([m.text for m in placed], ["100"])
        placed = vrun._place([self.mark(0, "100"), self.mark(5, "105")], 0, 20, None)
        self.assertEqual([m.text for m in placed], ["100", "105"])

    def test_quiet_mark_keeps_two_blanks_from_a_tick(self):
        placed = vrun._place([self.mark(3, vrun.QUIET), self.mark(5, "50")], 0, 20, None)
        self.assertEqual([m.text for m in placed], [vrun.QUIET])

    def test_tick_0_outranks_a_quiet_mark_crowding_it(self):
        g = parse(_DIR / "site" / "examples" / "01-checkout.sigil")
        limits = sim.limits_from(["hop=12"])
        canon = sim.canonical(g)
        tr = sim.simulate(canon, sim.scenario(canon, "API.charge:fails", limits=limits),
                          limits=limits)
        rows, _w = vrun.compose_run(g, tr, None, 140, limits=limits)
        ruler = next("".join(t for t, _ in r) for r in rows if isinstance(r, list)
                     and "≈" in "".join(t for t, _ in r))
        self.assertTrue(ruler.strip().startswith("0 "))
        self.assertNotRegex(ruler, r"[0-9≈] [0-9≈]")

    def test_other_marks_keep_one_blank(self):
        placed = vrun._place([self.mark(0, "ep2", scale=False), self.mark(4, "40")], 0, 20, None)
        self.assertEqual(len(placed), 2)

    def test_no_scale_label_one_blank_from_another(self):
        g = parse(EXECUTIONS)
        canon = sim.canonical(g)
        for sc in sim.scenarios(canon)[:4]:
            tr = sim.simulate(canon, sc)
            rows, _w = vrun.compose_run(g, tr, None, 140)
            scales = ["".join(t for t, _ in r) for r in rows if isinstance(r, list)]
            scales = [t for t in scales if t.strip() and re.fullmatch(r"[ 0-9≈]+", t)]
            self.assertTrue(scales)
            for text in scales:
                with self.subTest(scenario=sc.name, row=text):
                    self.assertNotRegex(text, r"[0-9≈] [0-9≈]")


if __name__ == "__main__":
    unittest.main()
