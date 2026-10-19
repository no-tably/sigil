"""`sigil frames draw` keeps one frame memo per draw: a run's window is drawn as
the viewer draws each frame alone (the memo only saves work). It takes --limit
NAME=N as view and check do: the run drawn and the scenarios listed follow it."""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from pathlib import Path

from sigil import cli
from sigil.model import sim
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


class Limits(unittest.TestCase):
    def draw(self, *argv) -> tuple:
        """(exit status, the JSON object or None, stderr) of `sigil frames draw`."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["frames", "draw", str(DOC), *argv])
        return code, (json.loads(out.getvalue()) if out.getvalue() else None), err.getvalue()

    def test_the_scenarios_listed_follow_the_limits(self):
        code, full, _ = self.draw()
        self.assertEqual(code, 0)
        self.assertGreater(len(full["scenarios"]), 1)
        code, capped, _ = self.draw("--limit", "scenarios=1")
        self.assertEqual((code, capped["scenarios"]), (0, ["happy"]))

    def test_the_run_drawn_follows_the_limits(self):
        _, full, _ = self.draw("--scenario", "happy", "--count", "1")
        self.assertEqual(full["outcome"], "ok")
        _, cut, _ = self.draw("--scenario", "happy", "--count", "1", "--limit", "frames=2",
                              "--limit", "scenarios=1")
        self.assertEqual(cut["outcome"], "cut")
        self.assertEqual(cut, frames.draw(DOC, scenario="happy", count=1,
                                          limits=sim.Limits(frames=2, scenarios=1)))

    def test_a_bad_limit_is_refused(self):
        code, out, err = self.draw("--limit", "nope=3")
        self.assertEqual((code, out), (2, None))
        self.assertIn("sigil frames:", err)


def _looks(out: dict, i: int) -> list:
    """frame i of a draw with each style id as the style it names (ids are per draw)."""
    return [[(text, out["styles"][sid]) for text, sid in row] for row in out["frames"][i]]


if __name__ == "__main__":
    unittest.main()
