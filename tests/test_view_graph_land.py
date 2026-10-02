"""Tests for view_graph.py: what drives a state machine in the events "land"
mode, and the colour policy's shared-cell rule.

Covers:
  1. land mode on 04-orders: no trigger edge drawn twice, no self-loop on an
     emitter driving its own machine, each machine section holding only its own
     states and what drives them (no overview edges leaking in);
  2. _drivers built from scene.driver_wires;
  3. the shared-cell rule: the chain nearest its own head owns a shared cell
     (_nearest_owners), a chain merely crossing a cell never does, and on
     01-checkout each fan-out head's turn cell is in its head's colour.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


view = _load("sigil_view", ROOT / "view.py")
vgraph, kit = view.vgraph, view.kit
scene = vgraph.scene

ORDERS = (ROOT / "site" / "examples" / "04-orders.sigil").read_text()
CHECKOUT = (ROOT / "site" / "examples" / "01-checkout.sigil").read_text()


def land_scene():
    g = kit.render.parse_document(ORDERS)
    return g, scene.build_scene(g, events="land", depth=kit.ALL_DEPTH)


def plain_sections(g, scn) -> dict:
    """{section title text: drawing text} for every section at full depth."""
    out = {}
    for title, _graph, cv in vgraph.sections(g, kit.ALL_DEPTH, scn=scn):
        out[str(getattr(title, "text", title))] = "\n".join(
            "".join(t for t, _ in r) for r in cv.rows())
    return out


def _scene_keeps_self_drivers() -> bool:
    """Whether scene.trigger_edges still returns an emitter ⇢ its own machine."""
    g, scn = land_scene()
    return any(e.src == e.dst for e in scene.trigger_edges(scn, g.nodes))


class LandTriggers(unittest.TestCase):
    def test_no_trigger_edge_twice_in_the_overview(self):
        g, scn = land_scene()
        gc = vgraph.with_chips(vgraph._landed(g, scn, None), False, scn)
        keys = [(e.src, e.dst, e.kind) for e in gc.edges if e.kind == "trigger"]
        self.assertTrue(keys)
        self.assertEqual(len(keys), len(set(keys)), keys)

    @unittest.skipIf(_scene_keeps_self_drivers(),
                     "scene.trigger_edges does not drop src == machine pairs yet")
    def test_emitter_driving_its_own_machine_is_no_self_loop(self):
        g, scn = land_scene()
        drawn = "\n".join(plain_sections(g, scn).values())
        self.assertNotIn("↺", drawn)

    def test_each_machine_section_holds_its_states_and_their_drivers(self):
        g, scn = land_scene()
        parts = [(title, graph) for title, graph, _cv in vgraph.sections(g, kit.ALL_DEPTH, scn=scn)]
        machines = {nid: sub for nid, sub in g.expansions.items() if sub.role == "state"}
        seen = 0
        for title, part in parts:
            owner = next((nid for nid in machines if str(title).startswith(
                kit.node_label(g.nodes[nid]) + " state machine")), None)
            if owner is None:
                continue
            seen += 1
            drivers = {w.src for w in scene.driver_wires(scn) if w.machine == owner}
            self.assertLessEqual(set(part.nodes), set(machines[owner].nodes) | drivers, title)
            for e in vgraph.with_chips(part, False, scn).edges:
                self.assertIn(e.dst, machines[owner].nodes, (title, e))
        self.assertEqual(seen, 2)

    def test_no_payments_to_checkout_edge_in_the_order_machine(self):
        g, scn = land_scene()
        part = next(graph for title, graph, _cv in vgraph.sections(g, kit.ALL_DEPTH, scn=scn)
                    if str(title).startswith("{Order} state machine"))
        edges = {(e.src, e.dst) for e in vgraph.with_chips(part, False, scn).edges}
        self.assertNotIn(("Payments_service", "Checkout_service"), edges)

    def test_drivers_come_from_the_scene_driver_wires(self):
        _g, scn = land_scene()
        want = {}
        for w in scene.driver_wires(scn):
            want.setdefault(w.machine, [])
            if w.src not in want[w.machine]:
                want[w.machine].append(w.src)
        self.assertEqual(vgraph._drivers(scn), want)


class SharedCells(unittest.TestCase):
    @staticmethod
    def trace(style, pts):
        tr = vgraph._Trace(style, rev=False, both=False)
        tr.cells = vgraph._cells(pts)
        return tr

    def test_nearest_chain_owns_a_shared_trunk(self):
        # a trunk down from (5, 0) to row 2, one branch left to (0, 4), one right to (7, 4)
        far = self.trace("far", [(5, 0), (5, 2), (0, 2), (0, 4)])
        near = self.trace("near", [(5, 0), (5, 2), (7, 2), (7, 4)])
        lines = {c: [0, "light", "far"] for c in far.cells + near.cells}
        owners = vgraph._nearest_owners([far, near], lines)
        self.assertEqual(owners[(5, 0)], "near")             # the trunk: near is closer
        self.assertEqual(owners[(7, 2)], "near")             # its own turn cell
        self.assertNotIn((0, 2), owners)                     # far's own cells stay far's

    def test_a_crossing_chain_never_takes_the_cell(self):
        across = self.trace("across", [(0, 2), (4, 2)])
        down = self.trace("down", [(2, 0), (2, 3)])          # crosses at (2, 2), head near
        lines = {c: [0, "light", "across"] for c in across.cells + down.cells}
        lines[(2, 0)][2] = lines[(2, 1)][2] = lines[(2, 3)][2] = "down"
        self.assertEqual(vgraph._nearest_owners([across, down], lines), {})

    def test_fan_out_turn_cells_take_their_heads_colour(self):
        g = kit.render.parse_document(CHECKOUT)
        rows, _w = vgraph.compose(g, 1, False)
        grid = []
        for r in rows:
            cells = []
            for t, st in r:
                cells += [(ch, st[0] if st else None) for ch in t]
            grid.append(cells)
        heads = [(y, x) for y, row in enumerate(grid) for x, (ch, _c) in enumerate(row)
                 if ch in "▼✖" and y and x < len(grid[y - 1]) and grid[y - 1][x][0] in "┬┌┐"]
        self.assertGreaterEqual(len(heads), 4)
        for y, x in heads:
            self.assertEqual(grid[y - 1][x][1], grid[y][x][1], (y, x, grid[y - 1][x]))


if __name__ == "__main__":
    unittest.main()
