"""pane.py draw keeps one frame memo per draw: a run's window is drawn as view.py
draws each frame alone (the memo only saves work), and a view.py without
kit.FrameMemo still draws."""

from __future__ import annotations

import importlib.util
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PANE = ROOT / "plugin" / "claude" / "scripts" / "pane.py"
DOC = ROOT / "site" / "examples" / "00-shortener.sigil"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pane = _load("sigil_pane_memo_t", PANE)


class FrameMemoKeyword(unittest.TestCase):
    def test_fresh_memo_from_a_view_that_has_one(self):
        kind = type("FrameMemo", (), {})
        view = types.SimpleNamespace(kit=types.SimpleNamespace(FrameMemo=kind))
        first, second = pane.frame_memo(view), pane.frame_memo(view)
        self.assertIsInstance(first["memo"], kind)
        self.assertIsNot(first["memo"], second["memo"])

    def test_nothing_from_an_older_view(self):
        self.assertEqual(pane.frame_memo(types.SimpleNamespace()), {})
        self.assertEqual(pane.frame_memo(types.SimpleNamespace(kit=object())), {})


class RunWindowWithMemo(unittest.TestCase):
    def test_each_frame_as_drawn_alone(self):
        for view_name in ("flow", "graph", "tree", "run"):
            with self.subTest(view=view_name):
                held = pane.draw(DOC, view_name, width=90, scenario="happy", count=12)
                self.assertNotIn("error", held)
                for i in (0, 5, 11):
                    alone = pane.draw(DOC, view_name, width=90, scenario="happy",
                                      start=held["first"] + i, count=1)
                    self.assertEqual(_looks(held, i), _looks(alone, 0))


def _looks(out: dict, i: int) -> list:
    """frame i of a draw with each style id as the style it names (ids are per draw)."""
    return [[(text, out["styles"][sid]) for text, sid in row] for row in out["frames"][i]]


if __name__ == "__main__":
    unittest.main()
