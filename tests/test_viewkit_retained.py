"""Tests for viewkit's Retained and same_look: looks compare by role too.

Covers:
  - same_look: equal looks of the same roles alike; one hex in two theme roles
    not alike (a Colour's role, nested in a style, a list of runs, a dict);
  - Retained.repaint: a colour of another role sharing the old one's hex
    repaints its rows, so the kept drawing carries the new role;
  - a look unchanged, role and all, repaints nothing.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("sigil_viewkit_retained_tests", _DIR / "viewkit.py")
kit = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = kit
_spec.loader.exec_module(kit)

MAYBE = (kit.Colour("#6e7681", "edges-maybe"), None, False)
SPLIT = (kit.Colour("#6e7681", "edges-split"), None, False)


def drawing(style):
    cv = kit.Canvas()
    cv.put(0, 0, "[a]", style)
    cv.put(0, 2, "[b]", None)
    return cv


class TestSameLook(unittest.TestCase):

    def test_roles(self):
        self.assertEqual(MAYBE, SPLIT)                      # one hex: equal values
        self.assertFalse(kit.same_look(MAYBE, SPLIT))
        self.assertTrue(kit.same_look(MAYBE, (kit.Colour("#6e7681", "edges-maybe"), None, False)))
        self.assertTrue(kit.same_look(None, None))
        self.assertFalse(kit.same_look(MAYBE, None))
        self.assertFalse(kit.same_look([("x", MAYBE)], [("x", SPLIT)]))
        self.assertFalse(kit.same_look({1: [MAYBE]}, {1: [SPLIT]}))
        self.assertFalse(kit.same_look(("#6e7681", None, False), MAYBE))   # no role vs a role

    def test_probe_stays_apart(self):
        self.assertFalse(kit.same_look(kit.Probe(MAYBE), MAYBE))
        self.assertTrue(kit.same_look(kit.Probe(MAYBE), kit.Probe(MAYBE)))


class TestRetainedRoles(unittest.TestCase):

    def test_repaints_a_role_change(self):
        painted = []

        def paint(style):
            def draw(rows):
                painted.append(set(rows))
                return drawing(style)
            return draw

        kept = kit.Retained(drawing(MAYBE), {"a": ((0,), MAYBE), "b": ((2,), None)})
        cv = kept.repaint({"a": ((0,), SPLIT), "b": ((2,), None)}, paint(SPLIT))
        self.assertEqual(painted, [{0}])
        self.assertEqual(list(cv.rows())[0][0][1][0].role, "edges-split")
        kept.repaint({"a": ((0,), SPLIT), "b": ((2,), None)}, paint(SPLIT))
        self.assertEqual(painted, [{0}])                    # unchanged: nothing painted


if __name__ == "__main__":
    unittest.main()
