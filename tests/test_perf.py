"""The views' hot loops, rewritten for speed, draw exactly as the plain ones did.

Covers:
  - Canvas.rows (only the drawn cells visited) against a cell-by-cell walk, on
    sparse random canvases with gaps, None and Probe styles and off-canvas cells;
    a subclass's own cell() (the flow view's rounded corners) still asked;
  - Canvas.path and Canvas.run (link inlined) against link() one step at a time,
    stroke ranks, `fixed` cells and hops included;
  - view_graph's shared-cell colour rule (_nearest_owners, direction bitmasks,
    distances only where chains share a cell) against the set-based rule;
  - sim.failure_analysis (a worklist now, not every activation checked every
    round): a long chain still runs each activation a bounded number of times.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import random
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


view = _load("sigil_view_perf", "view.py")
kit, vgraph, sim = view.kit, view.vgraph, view.simulator

KINDS = ["->", "=>", "*>", "~>", "?>", "trigger", "access:r"]
STYLES = [None, (1, None, False), (2, None, True), kit.Probe((1, None, False))]


def plain_rows(cv):
    """Canvas.rows as it was: every cell of every row, through cell()."""
    for y in range(cv.h):
        runs = []
        for x in range(cv.w):
            ch, st = cv.cell(x, y)
            if runs and runs[-1][1] == st:
                runs[-1][0] += ch
            else:
                runs.append([ch, st])
        if runs:
            runs[-1][0] = runs[-1][0].rstrip()
        yield [(t, s) for t, s in runs if t]


def stepwise_path(cv, pts, kind, style):
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        dx, dy = (x2 > x1) - (x2 < x1), (y2 > y1) - (y2 < y1)
        x, y = x1, y1
        while (x, y) != (x2, y2):
            cv.link((x, y), (x + dx, y + dy), kind, style)
            x, y = x + dx, y + dy


def stepwise_run(cv, x0, x1, y, kind, style, hops=None, fixed=frozenset()):
    drawn = set()
    for x in range(x0, x1):
        a, b = (x, y), (x + 1, y)
        a_hop, b_hop = hops is not None and hops(x), hops is not None and hops(x + 1)
        if a_hop and b_hop:
            continue
        if b_hop:
            cv.stub(a, kit.R, kind, style)
            drawn.add(a)
        elif a_hop:
            cv.stub(b, kit.L, kind, style)
            drawn.add(b)
        else:
            cv.link(a, b, kind, style, fixed)
            drawn |= {a, b}
    return drawn


def set_owners(traces, lines):
    """_nearest_owners as it was: sets of (dx, dy), every chain's distances."""
    seen = {}
    for tr in traces:
        dist = tr.to_head()
        dirs = {cell: set() for cell in tr.cells}
        for (ax, ay), (bx, by) in zip(tr.cells, tr.cells[1:]):
            if abs(bx - ax) + abs(by - ay) == 1:
                dirs[(ax, ay)].add((bx - ax, by - ay))
                dirs[(bx, by)].add((ax - bx, ay - by))
        for cell, d in dirs.items():
            if cell in lines:
                seen.setdefault(cell, []).append((dist[cell], d, tr.style))
    out = {}
    for cell, chains in seen.items():
        cur = lines[cell][2]
        ref = next((d for _n, d, st in chains if st == cur), chains[0][1])
        _n, st = min([(n, st) for n, d, st in chains if d & ref], key=lambda c: c[0])
        if st != cur:
            out[cell] = st
    return out


def random_pts(rng, n=4, size=30):
    pts = [(rng.randrange(size), rng.randrange(size))]
    for _ in range(n):
        x, y = pts[-1]
        pts.append((rng.randrange(size), y) if rng.random() < .5 else (x, rng.randrange(size)))
    return pts


class RowsMatchCellByCell(unittest.TestCase):
    def test_random_sparse_canvases(self):
        rng = random.Random(7)
        for _ in range(60):
            cv = kit.Canvas()
            for _ in range(rng.randrange(1, 12)):
                if rng.random() < .5:
                    cv.put(rng.randrange(-3, 40), rng.randrange(-2, 20),
                           rng.choice(["ab", " ", "x y", "  ", "▶"]), rng.choice(STYLES))
                else:
                    cv.path(random_pts(rng), rng.choice(KINDS), rng.choice(STYLES))
            self.assertEqual(list(cv.rows()), list(plain_rows(cv)))

    def test_a_subclass_cell_is_asked(self):
        class Rounded(kit.Canvas):
            def cell(self, x, y):
                ch, st = super().cell(x, y)
                return ("╭" if ch == "┌" else ch), st
        cv = Rounded()
        cv.path([(0, 3), (0, 0), (5, 0)], "->", None)
        self.assertEqual(list(cv.rows()), list(plain_rows(cv)))
        self.assertTrue(list(cv.rows())[0][0][0].startswith("╭"))


class LinesMatchStepwise(unittest.TestCase):
    def test_path(self):
        rng = random.Random(11)
        for _ in range(40):
            fast, slow = kit.Canvas(), kit.Canvas()
            for _ in range(rng.randrange(1, 8)):
                pts, kind, st = random_pts(rng), rng.choice(KINDS), rng.choice(STYLES)
                fast.path(pts, kind, st)
                stepwise_path(slow, pts, kind, st)
            self.assertEqual((fast.lines, fast.w, fast.h), (slow.lines, slow.w, slow.h))

    def test_run_with_hops_and_fixed(self):
        rng = random.Random(13)
        for _ in range(40):
            fast, slow = kit.Canvas(), kit.Canvas()
            for _ in range(rng.randrange(1, 8)):
                x0, x1, y = rng.randrange(20), rng.randrange(25), rng.randrange(5)
                holes = {rng.randrange(25) for _ in range(rng.randrange(4))}
                hops = (lambda x, _h=holes: x in _h) if rng.random() < .6 else None
                fixed = frozenset((rng.randrange(25), y) for _ in range(rng.randrange(3)))
                kind, st = rng.choice(KINDS), rng.choice(STYLES)
                self.assertEqual(fast.run(x0, x1, y, kind, st, hops, fixed),
                                 stepwise_run(slow, x0, x1, y, kind, st, hops, fixed))
            self.assertEqual((fast.lines, fast.w, fast.h), (slow.lines, slow.w, slow.h))


class OwnersMatchSetRule(unittest.TestCase):
    def test_random_chains(self):
        rng = random.Random(17)
        for _ in range(60):
            cv, traces = kit.Canvas(), []
            for _ in range(rng.randrange(1, 7)):
                st = rng.choice(STYLES[1:3])
                tr = vgraph._Trace(st, rng.random() < .3, rng.random() < .2)
                for _ in range(rng.randrange(1, 3)):
                    pts = random_pts(rng, 3, 12)
                    if pts[0] != pts[1]:
                        cv.path(pts, "->", st)
                        tr.cells += vgraph._cells(pts)
                if len(tr.cells) > 1:
                    traces.append(tr)
            self.assertEqual(vgraph._nearest_owners(traces, cv.lines),
                             set_owners(traces, cv.lines))


class FailureAnalysisWorklist(unittest.TestCase):
    def prog(self, text):
        return sim.program(sim.canonical(view.render.parse_document(text)))

    def test_a_long_chain_runs_each_activation_a_few_times(self):
        n = 300
        prog = self.prog("--- chain ---\n" + "\n".join(
            f"[N{i}] -> [N{i + 1}] : go ×2" for i in range(n)) + "\n")
        runs, real = [], sim._activation
        def counted(fl, fails, ctx):
            runs.append(ctx)
            return real(fl, fails, ctx)
        sim._activation = counted
        try:
            flow = sim.failure_analysis(prog)
        finally:
            sim._activation = real
        self.assertGreater(len(set(runs)), n)
        self.assertLessEqual(len(runs), 3 * len(set(runs)))
        self.assertTrue(flow.arriving)


if __name__ == "__main__":
    unittest.main()
