"""view.py --frame / --play: where a live run starts (the agent plugins' split
passes them so a run asked for at a frame, or playing, starts there)."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import view  # noqa: E402

CHECKOUT = ROOT / "site" / "examples" / "01-checkout.sigil"


class TestStart(unittest.TestCase):
    def setUp(self):
        self.p = view.SimPlayer(view.kit.render.parse_document(CHECKOUT.read_text()))

    def test_a_frame_paused_or_playing(self):
        self.p.start(2, False, now=5.0)
        self.assertEqual((self.p.at, self.p.playing), (2, False))
        self.p.start(1, True, now=5.0)
        self.assertEqual((self.p.at, self.p.playing), (1, True))
        self.assertAlmostEqual(self.p.wait(5.0), self.p.interval)   # the next frame is a frame away

    def test_last_and_past_the_end_are_the_last_and_never_play(self):
        for frame in (-1, 10 ** 6):
            self.p.start(frame, True, now=0.0)
            self.assertEqual((self.p.at, self.p.playing), (self.p.last, False))

    def test_play_alone_plays_from_the_first(self):
        self.p.start(None, True, now=0.0)
        self.assertEqual((self.p.at, self.p.playing), (0, True))


class TestStartingState(unittest.TestCase):
    def test_the_player_starts_where_asked_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "doc.sigil"
            path.write_text(CHECKOUT.read_text())
            st = view.ViewState(path, do_lint=False, sim="happy")
            st.sim_start = (-1, False)
            st.reload(force=True)
            self.assertEqual(st.player.at, st.player.last)
            self.assertIsNone(st.sim_start)          # a later player (x, [ ]) starts as ever
            path.write_text(CHECKOUT.read_text() + "\n")
            st.reload()
            self.assertEqual(st.player.at, st.player.last)   # a reload keeps the position


class TestFlags(unittest.TestCase):
    def run_view(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "view.py"), str(CHECKOUT), *args],
                              capture_output=True, text=True)

    def test_they_need_a_scenario(self):
        for args in (["--frame", "2"], ["--play"], ["--sim", "list", "--play"]):
            with self.subTest(args=args):
                res = self.run_view("--once", *args)
                self.assertEqual(res.returncode, 2)
                self.assertIn("--frame and --play need --sim SCENARIO", res.stderr)

    def test_a_bad_frame_is_named(self):
        res = self.run_view("--sim", "happy", "--frame", "first")
        self.assertEqual(res.returncode, 2)
        self.assertIn("expected a frame number >= 0 or last, got 'first'", res.stderr)


if __name__ == "__main__":
    unittest.main()
