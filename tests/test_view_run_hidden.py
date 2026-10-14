"""Tests for a run drawn to a depth where a drawn host is busy on hidden internals.

Covers:
  - sim.timeline(hosts=…).hidden: the ticks something happens inside a fold
    (none when every level is drawn);
  - the ≈ quiet-stretch fold: a host busy on its folded expansion is not quiet —
    the ticks kept unfolded at --depth 0/1 are those kept at every level
    (site/examples/02-shop.sigil: no ≈ while [Shop]'s internals run);
  - sim.narrate: a loop inside a hidden expansion is said as the drawn host's
    loop inside it (`[Shop] loops (inside)`), not as the host's own
    (`loop in [Shop]`); a loop in a drawn owner's expansion keeps its owner's
    name (`loop in [Checkout]`);
  - the lane notes say the same: sim.timeline(hosts=…) says an iteration run
    by a folded activation of the act on its host's lane (`inside` when the
    loop's owner is folded too), so [Shop]'s note at --depth 0 is `loops 2×
    (inside)`, [Checkout]'s at --depth 1 `loops 2×` (--run --json marks it).

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
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


view = _load("sigil_view_run_hidden_tests", "view.py")
vrun, kit, sim = view.vrun, view.kit, view.simulator

SHOP = _DIR / "site" / "examples" / "02-shop.sigil"
EXAMPLES = sorted((_DIR / "site" / "examples").glob("*.sigil")) + [
    _DIR / "tests" / "fixtures" / "executions.sigil"]

LOOP = """#!sketch
(Shopper) -> [Shop] : {Request}
[Shop] -> |Catalog| : lookup(sku) => {Item}

[Shop] := {
  [Cart] -> [Checkout] : {Cart}
  [Checkout] := {
    loop @times 3 {
      [Pricer] -> [Tax] : price(line)
    }
  }
}
"""

TOP_LOOP = """#!sketch
loop @times 2 {
  (User) -> [Api]
}
"""


def run_of(g, name: str = "happy"):
    canon = sim.canonical(g)
    return canon, sim.simulate(canon, sim.scenario(canon, name))


def text_of(rows) -> str:
    return "\n".join("".join(t for t, _ in r) for r in rows if isinstance(r, list))


class HiddenTicksTest(unittest.TestCase):
    def setUp(self):
        self.canon, self.trace = run_of(view.render.parse_document(SHOP.read_text()))

    def test_every_level_drawn_hides_nothing(self):
        self.assertEqual(sim.timeline(self.trace).hidden, frozenset())

    def test_depth_0_keeps_the_folded_internals_ticks(self):
        full = sim.timeline(self.trace)
        cart = next(s for s in full.spans if s.node == "Cart_service")
        model = next(s for s in full.spans if s.node == "Model_service")
        hidden = sim.timeline(self.trace, hosts=sim.folded_hosts(self.canon, 0)).hidden
        self.assertIn(cart.enter, hidden)
        self.assertIn(model.enter, hidden)

    def test_change_ticks(self):
        span = sim.Span(("A", None, 1), 1, 1, "A", 3, 9, "ok", (), None, None, 1)
        move = sim.Move(1, 1, 1, ("w",), "->", False, 4, 7, "entered", (), (), None, None)
        self.assertEqual(sim.change_ticks([span], [move]), {3, 9, 4, 6, 7})
        self.assertEqual(sim.change_ticks([span._replace(leave=None)],
                                          [move._replace(end=None)]), {3, 4})


class QuietFoldTest(unittest.TestCase):
    def test_folding_keeps_the_ticks_every_level_keeps(self):
        for path in EXAMPLES:
            canon, _tr = run_of(view.render.parse_document(path.read_text()))
            for sc in sim.scenarios(canon):
                tr = sim.simulate(canon, sc)
                full = vrun._busy_ticks(sim.timeline(tr))
                for depth in (0, 1):
                    tl = sim.timeline(tr, hosts=sim.folded_hosts(canon, depth))
                    with self.subTest(path=path.name, scenario=sc.name, depth=depth):
                        self.assertEqual(vrun._busy_ticks(tl), full)

    def test_shop_at_depth_0_has_no_quiet_stretch_while_its_internals_run(self):
        g = view.render.parse_document(SHOP.read_text())
        rows, _w = vrun.compose_run(g, None, None, 200, depth=0)
        self.assertNotIn(vrun.QUIET, text_of(rows))

    def test_a_folded_loop_is_drawn_tick_by_tick(self):
        g = view.render.parse_document(LOOP)
        rows, _w = vrun.compose_run(g, None, None, 140, depth=0)
        text = text_of(rows)
        self.assertNotIn(vrun.QUIET, text)
        self.assertIn(vrun.ITERATION + "2", text)


class FoldedLoopNarrationTest(unittest.TestCase):
    def beats(self, src: str, depth: int) -> str:
        canon, tr = run_of(view.render.parse_document(src))
        return " ".join(b.text for b in sim.narrate(tr, sim.folded_hosts(canon, depth)))

    def test_depth_0_says_the_host_loops_inside(self):
        text = self.beats(LOOP, 0)
        self.assertIn("[Shop] loops (inside): iteration 2", text)
        self.assertNotIn("loop in [Shop]", text)
        self.assertNotIn("[Checkout]", text)

    def test_a_drawn_owner_keeps_its_name(self):
        for depth in (1, kit.ALL_DEPTH):
            with self.subTest(depth=depth):
                text = self.beats(LOOP, depth)
                self.assertIn("loop in [Checkout]: iteration 2", text)
                self.assertNotIn("loops (inside)", text)

    def test_a_top_level_loop_names_no_owner(self):
        self.assertIn("loop: iteration 2", self.beats(TOP_LOOP, 0))


class FoldedLoopNotesTest(unittest.TestCase):
    def setUp(self):
        self.canon, self.trace = run_of(view.render.parse_document(LOOP))

    def note_of(self, depth: int, label: str) -> str:
        rows, _w = vrun.compose_run(view.render.parse_document(LOOP), None, None, 200,
                                    depth=depth)
        return next(ln for ln in text_of(rows).splitlines() if ln.strip().startswith(label))

    def test_every_level_keeps_the_running_act(self):
        tl = sim.timeline(self.trace)
        acts = {s.act: s.node for s in tl.spans}
        self.assertTrue(tl.iterations)
        for it in tl.iterations:
            self.assertFalse(it.inside)
            self.assertEqual(acts[it.act], "Pricer_service")

    def test_depth_0_says_it_of_the_hosts_act(self):
        tl = sim.timeline(self.trace, hosts=sim.folded_hosts(self.canon, 0))
        lane_of = {s.act: s.lane for s in tl.spans}
        for it in tl.iterations:
            self.assertTrue(it.inside)
            self.assertEqual(lane_of[it.act][0], "Shop_service")

    def test_hosted_iterations(self):
        its = [sim.Iteration(1, 1, 3, ("Checkout_service", 0), 7),
               sim.Iteration(2, 2, 3, ("Checkout_service", 0), 8),
               sim.Iteration(3, 2, 3, (None, 0), 9)]
        hosts = {"Checkout_service": "Shop_service"}
        out = sim._hosted_iterations(its, {7: 1}, {8}, hosts)
        self.assertEqual([(it.act, it.inside) for it in out], [(1, True), (8, True), (9, False)])
        self.assertEqual([it.inside for it in sim._hosted_iterations(its, {7: 1}, {8}, {})],
                         [False, False, False])

    def test_notes(self):
        self.assertIn("loops 2× (inside)", self.note_of(0, "[Shop]"))
        one = self.note_of(1, "[Checkout]")
        self.assertIn("loops 2×", one)
        self.assertNotIn("(inside)", one)
        self.assertIn("loops 2×", self.note_of(kit.ALL_DEPTH, "[Pricer]"))
        self.assertNotIn("loops", self.note_of(kit.ALL_DEPTH, "[Shop]"))

    def test_loop_clauses(self):
        it = sim.Iteration(1, 2, 3, ("A", 0), 1)
        texts = lambda its, sf="": [c.text for c in vrun._loop_clauses(its, sf)]
        self.assertEqual(texts([it]), ["loops 2×"])
        self.assertEqual(texts([it._replace(inside=True)], " so far"),
                         ["loops 2× (inside) so far"])
        self.assertEqual(texts([it, it._replace(k=3, inside=True)]),
                         ["loops 2×", "loops 3× (inside)"])
        self.assertEqual(texts([it._replace(k=1)]), [])

    def test_json_marks_inside(self):
        data = vrun.timeline_json(self.trace, depth=0)
        self.assertTrue(all(it.get("inside") for it in data["iterations"]))
        span_acts = {s["act"] for s in data["spans"]}
        self.assertTrue(all(it["act"] in span_acts for it in data["iterations"]))
        self.assertFalse(any("inside" in it for it in vrun.timeline_json(self.trace)["iterations"]))


if __name__ == "__main__":
    unittest.main()
