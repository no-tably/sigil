"""Tests for view_graph.py wrapping a wide fan-out to the width.

Covers:
  - one node fanning out to more nodes than a row holds: its targets fill each
    row the width allows (as a wide layer's do), the edges to the later rows
    passing the earlier ones as one trunk, not a line per target;
  - each target drawn once, the hub above them all, every row inside the width;
  - a broadcast (`*>`) and a joined fan-out (`-> [A] & [B] …`) wrap the same way;
  - the natural layout (no width) keeps the fan-out on one row.

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


view = _load("sigil_view_graph_wrap", "view.py")
vgraph = view.vgraph

N = 14
TARGETS = [f"[Service{k:02d}]" for k in range(N)]
FAN = "".join(f"[Hub] -> {t}\n" for t in TARGETS)
BROADCAST = "[Hub] *> " + " & ".join(TARGETS) + "\n"
JOINED = "[Hub] -> " + " & ".join(TARGETS) + "\n"


def draw(text: str, width):
    rows, w = vgraph.compose(view.render.parse_document(text), 1, False, width=width)
    return ["".join(t for t, _ in r) for r in rows], w


def label_rows(rows) -> list:
    """The rows carrying target labels, as the number of targets on each."""
    return [sum(t in r for t in TARGETS) for r in rows if any(t in r for t in TARGETS)]


class TestFanOutWraps(unittest.TestCase):
    def test_targets_fill_each_row(self):
        rows, w = draw(FAN, 80)
        self.assertLessEqual(w, 80)
        self.assertTrue(all(len(r) <= 80 for r in rows), "\n".join(rows))
        per_row = label_rows(rows)
        self.assertEqual(sum(per_row), N)                  # each target once
        # 15-wide boxes, 3 apart, beside one trunk: four to a row (before, the
        # edges passing a row took a column each and the rows held 1 to 4)
        self.assertEqual(per_row, [4, 4, 4, 2], "\n".join(rows))

    def test_the_hub_is_above_its_targets(self):
        rows, _w = draw(FAN, 80)
        hub = next(i for i, r in enumerate(rows) if "[Hub]" in r)
        first = next(i for i, r in enumerate(rows) if any(t in r for t in TARGETS))
        self.assertLess(hub, first)

    def test_one_trunk_passes_a_row(self):
        # beside a full row's boxes, a single line runs on down to the next rows
        rows, _w = draw(FAN, 80)
        row = next(r for r in rows if sum(t in r for t in TARGETS) == 4)
        outside = "".join(ch for k, ch in enumerate(row)
                          if not any(row.find(t) - 2 <= k < row.find(t) + len(t) + 2
                                     for t in TARGETS if t in row))
        self.assertEqual(outside.count("│"), 1, row)

    def test_broadcast_and_joined_fan_outs_wrap_too(self):
        for text in (BROADCAST, JOINED):
            rows, w = draw(text, 80)
            self.assertLessEqual(w, 80)
            self.assertEqual(sum(label_rows(rows)), N)
            self.assertLessEqual(len(label_rows(rows)), 4, "\n".join(rows))

    def test_the_natural_layout_keeps_one_row(self):
        rows, w = draw(FAN, None)
        self.assertEqual(label_rows(rows), [N])
        self.assertGreater(w, 80)


if __name__ == "__main__":
    unittest.main()
