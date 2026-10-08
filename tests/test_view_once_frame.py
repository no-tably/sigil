"""view.py --once --sim X --frame N|last: the printout draws frame N of the run
(not its final frame) in every view, the run view with its playhead there, and
the text under it names the frame drawn."""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scene  # noqa: E402
import view  # noqa: E402

SHORTENER = ROOT / "site" / "examples" / "00-shortener.sigil"
WIDTH = 100
FRAME = 12


def printed(**kw) -> str:
    """What view.once prints for the shortener's happy run (no lint, no colour)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        view.once(SHORTENER, 1, False, False, width=WIDTH, sim="happy", **kw)
    return out.getvalue()


def drawn_at(view_name: str, frame: int) -> list[str]:
    """The drawing compose_view makes of the happy run at `frame` in a view, as
    plain text rows — what the live view shows paused there."""
    g = view.kit.render.parse_document(SHORTENER.read_text())
    player = view.SimPlayer(g, "happy")
    events = view.DEFAULT_EVENTS[view_name]
    shown = player.shown(scene.SceneOptions(events, True, False, 1))
    rows, _w = view.compose_view(g, view_name, depth=1, payloads=False, notes="off",
                                 triggers=True, spaced=True, width=WIDTH, access=False,
                                 mods=False, events=events, trace=shown, tick=frame)
    return [view.kit.ansi(r, False) for r in rows]


def last_frame() -> int:
    """The index of the happy run's final frame."""
    return view.SimPlayer(view.kit.render.parse_document(SHORTENER.read_text()), "happy").last


class TestFrameIndex(unittest.TestCase):
    def test_n_last_past_the_end_and_none(self):
        self.assertEqual(view.frame_index(3, 10), 3)
        self.assertEqual(view.frame_index(0, 10), 0)
        self.assertEqual(view.frame_index(-1, 10), 10)
        self.assertEqual(view.frame_index(11, 10), 10)
        self.assertEqual(view.frame_index(None, 10), 0)
        self.assertEqual(view.frame_index(None, 10, default=10), 10)


class TestOnceFrame(unittest.TestCase):
    def test_every_view_draws_the_frame_asked_for(self):
        for name in view.VIEWS:
            with self.subTest(view=name):
                rows = drawn_at(name, FRAME)
                self.assertNotEqual(rows, drawn_at(name, last_frame()))
                text = printed(view=name, frame=FRAME).splitlines()
                self.assertEqual(text[:len(rows)], rows)

    def test_the_run_view_puts_its_playhead_there(self):
        text = printed(view="run", frame=FRAME)
        self.assertIn(f"▼{FRAME}", text)

    def test_last_and_past_the_end_print_as_without_frame(self):
        for name in view.VIEWS:
            with self.subTest(view=name):
                plain = printed(view=name)
                self.assertEqual(printed(view=name, frame=-1), plain)
                self.assertEqual(printed(view=name, frame=10 ** 6), plain)

    def test_the_text_names_a_frame_before_the_last(self):
        self.assertIn(f"· drawn at frame {FRAME} (t{FRAME:03d})", printed(frame=FRAME))
        self.assertNotIn("drawn at frame", printed(frame=-1))

    def test_the_path_is_the_path_so_far(self):
        early = [ln for ln in printed(frame=FRAME).splitlines() if ln.startswith("path ")]
        final = [ln for ln in printed().splitlines() if ln.startswith("path ")]
        self.assertNotIn("(Visitor)", early[-1])     # episode 2 hasn't begun at frame 12
        self.assertIn("(Visitor)", final[-1])


class TestCli(unittest.TestCase):
    def run_view(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "view.py"), *args],
                              capture_output=True, text=True)

    def test_the_flag_reaches_once(self):
        res = self.run_view(str(SHORTENER), "--once", "--sim", "happy", "--frame", str(FRAME),
                            "--run", "--color", "never", "--no-lint")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(f"▼{FRAME}", res.stdout)
        self.assertIn(f"drawn at frame {FRAME}", res.stdout)

    def test_help_says_once_draws_the_frame(self):
        res = self.run_view("--help")
        flat = " ".join(res.stdout.split())
        self.assertIn("--once draws that frame in any view", flat)
        self.assertIn("--once draws that frame instead of the final one",
                      " ".join(view.__doc__.split()))


if __name__ == "__main__":
    unittest.main()
