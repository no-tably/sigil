"""`sigil frames draw` keeps one frame memo per draw: a run's window is drawn as
the viewer draws each frame alone (the memo only saves work)."""

from __future__ import annotations

import unittest
from pathlib import Path

from sigil.present import frames

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "site" / "examples" / "00-shortener.sigil"


class RunWindowWithMemo(unittest.TestCase):
    def test_each_frame_as_drawn_alone(self):
        for view_name in ("flow", "graph", "tree", "run"):
            with self.subTest(view=view_name):
                held = frames.draw(DOC, view_name, width=90, scenario="happy", count=12)
                self.assertNotIn("error", held)
                for i in (0, 5, 11):
                    alone = frames.draw(DOC, view_name, width=90, scenario="happy",
                                        start=held["first"] + i, count=1)
                    self.assertEqual(_looks(held, i), _looks(alone, 0))


def _looks(out: dict, i: int) -> list:
    """frame i of a draw with each style id as the style it names (ids are per draw)."""
    return [[(text, out["styles"][sid]) for text, sid in row] for row in out["frames"][i]]


if __name__ == "__main__":
    unittest.main()
