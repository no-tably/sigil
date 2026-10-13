"""Tests for viewkit's row runs: neighbours merge only when they draw alike.

Covers:
  - Canvas.rows / _span: two neighbouring cells of one hex but two theme
    roles stay two runs, each keeping its own role (a repaint keyed by role
    stays right); one hex in one role still merges into one run;
  - a style tuple holding such a colour (colour, bold) splits the same way;
  - a kept canvas (keep_rows): its spans joined by _join_runs split at a
    role change across the ROW_SPAN boundary, and merge when the role is
    the same; its runs are the plain canvas's runs;
  - the printed text is unchanged (the runs' text joined is the row).

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


vk = sys.modules.get("viewkit") or _load("viewkit", "viewkit.py")

HEX = "#6e7681"


def _roles(runs) -> list:
    """(text, role) of each run; a tuple style's role is its colour's."""
    def role(st):
        st = st[0] if isinstance(st, tuple) else st
        return getattr(st, "role", None)
    return [(t, role(s)) for t, s in runs]


def _two_roles(x0: int, style=lambda c: c) -> "vk.Canvas":
    """A canvas whose row 0 has "ab" in edges-maybe then "cd" in edges-split
    (one hex) from column x0."""
    c = vk.Canvas()
    c.put(x0, 0, "ab", style(vk.Colour(HEX, "edges-maybe")))
    c.put(x0 + 2, 0, "cd", style(vk.Colour(HEX, "edges-split")))
    return c


class RowRuns(unittest.TestCase):
    def test_one_hex_two_roles_stays_two_runs(self):
        row = list(_two_roles(0).rows())[0]
        self.assertEqual(_roles(row), [("ab", "edges-maybe"), ("cd", "edges-split")])

    def test_one_hex_one_role_merges(self):
        c = vk.Canvas()
        c.put(0, 0, "ab", vk.Colour(HEX, "edges-maybe"))
        c.put(2, 0, "cd", vk.Colour(HEX, "edges-maybe"))
        self.assertEqual(_roles(list(c.rows())[0]), [("abcd", "edges-maybe")])

    def test_tuple_style_splits_by_role(self):
        row = list(_two_roles(0, lambda col: (col, True)).rows())[0]
        self.assertEqual(_roles(row), [("ab", "edges-maybe"), ("cd", "edges-split")])

    def test_plain_styles_still_merge(self):
        c = vk.Canvas()
        c.put(0, 0, "ab", "#112233")
        c.put(2, 0, "cd", "#112233")
        c.put(4, 0, "  ef")
        self.assertEqual(list(c.rows())[0], [("abcd", "#112233"), ("  ef", None)])


class KeptRuns(unittest.TestCase):
    def test_role_change_on_span_boundary_splits(self):
        x0 = vk.ROW_SPAN - 2            # "ab" ends one span, "cd" starts the next
        plain = list(_two_roles(x0).rows())[0]
        kept = list(_two_roles(x0).keep_rows().rows())[0]
        self.assertEqual(_roles(kept)[-2:], [("ab", "edges-maybe"), ("cd", "edges-split")])
        self.assertEqual(_roles(kept), _roles(plain))
        self.assertEqual("".join(t for t, _s in kept), " " * x0 + "abcd")

    def test_same_role_on_span_boundary_merges(self):
        c = vk.Canvas()
        x0 = vk.ROW_SPAN - 2
        c.put(x0, 0, "ab", vk.Colour(HEX, "edges-maybe"))
        c.put(x0 + 2, 0, "cd", vk.Colour(HEX, "edges-maybe"))
        kept = list(c.keep_rows().rows())[0]
        self.assertEqual(_roles(kept)[-1], ("abcd", "edges-maybe"))


if __name__ == "__main__":
    unittest.main()
