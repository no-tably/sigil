"""A1: the live view stands on cure — Term (modes, signals), Input (keys, mouse,
paste), Clock (the run's Playback), Layout (the Viewport) and Files (the watch).

What it pins:
- key_names: cure's Input events read as sigil's keys, as the old byte parser
  read them (named keys only unmodified, Alt+a character is the character, a
  shifted letter its capital, q quits, a paste read as the keys it holds), and
  mouse reports as SGR codes (button, modifiers, motion, 1-based cells);
- the playground's path (a player only told a frame, --once) never imports
  cure's terminal side (edge, interact);
- the follow is cure's: the least move, none while the span is already shown;
- the watch sees an atomic save that keeps the mtime and size (a new inode);
- SimPlayer's Playback only while playing, restored with its due time (due_at=);
- tui on a headless cure Term: the modes it sets and undoes, a drawn frame, q;
  its colours as the env says (24-bit, the nearest of 256, none under NO_COLOR);
- the real thing in a pty: q leaves with the terminal restored, exit 0; SIGTERM
  leaves with 143, restored too.
"""

import os
import pty
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sigil.present import app  # noqa: E402

DOC = "[Web] -> [Api] : get({Req}) => {Res}\n[Api] -> |Db| : read({Q}) => {Row}\n"


def keys(data: bytes) -> list:
    from cure.interact.input import decode
    return list(app.key_names(decode(data)))


class TestKeyNames(unittest.TestCase):
    def test_named_keys(self):
        self.assertEqual(keys(b"\x1b[A\x1bOB\x1b[C\x1b[D\x1b[5~\x1b[6~\x1b[H\x1b[1~ "),
                         ["up", "down", "right", "left", "pgup", "pgdn", "home", "home", " "])

    def test_modified_named_keys_and_controls_give_nothing(self):
        self.assertEqual(keys(b"\x1b[1;5A\x1b[1;2B\t\r\x7f\x01\x1b[F\x1b[3~"), [])

    def test_characters(self):
        self.assertEqual(keys(b"jLQq=+-<>[],."), ["j", "L", "Q", "quit", "=", "+", "-",
                                                  "<", ">", "[", "]", ",", "."])

    def test_alt_character_is_the_character(self):
        self.assertEqual(keys(b"\x1bx\x1bL"), ["x", "L"])

    def test_lone_escape_gives_nothing(self):
        self.assertEqual(keys(b"j\x1b"), ["j"])

    def test_paste_is_read_as_keys(self):
        self.assertEqual(keys(b"\x1b[200~jz\x1b[201~k"), ["j", "z", "k"])

    def test_mouse_reports(self):
        M = app.Mouse
        self.assertEqual(keys(b"\x1b[<0;10;5M\x1b[<32;12;7M\x1b[<0;12;7m"),
                         [M(0, 10, 5, False), M(32, 12, 7, False), M(0, 12, 7, True)])
        self.assertEqual(keys(b"\x1b[<64;1;1M\x1b[<65;1;1M\x1b[<66;1;1M\x1b[<67;1;1M"),
                         [M(c, 1, 1, False) for c in (64, 65, 66, 67)])
        self.assertEqual(keys(b"\x1b[<68;2;3M\x1b[<35;3;3M\x1b[<34;3;3M\x1b[<16;1;1M"),
                         [M(68, 2, 3, False), M(35, 3, 3, False), M(34, 3, 3, False),
                          M(16, 1, 1, False)])


class TestPlaygroundPath(unittest.TestCase):
    def test_a_told_player_never_imports_the_terminal_side(self):
        code = ("import sys; sys.path.insert(0, sys.argv[1])\n"
                "from pathlib import Path\n"
                "from sigil.core.parse import parse_document\n"
                "from sigil.present import app, frames\n"
                "p = app.SimPlayer(parse_document(Path(sys.argv[2]).read_text()))\n"
                "p.at = p.last; p.step(-1); p.step_event(-1); p.choose(1)\n"
                "print(sorted(m for m in sys.modules if m.startswith(('cure.edge', 'cure.interact'))))\n")
        out = subprocess.run([sys.executable, "-c", code, str(ROOT),
                              str(ROOT / "site/examples/02-shop.sigil")],
                             capture_output=True, text=True, check=True).stdout
        self.assertEqual(out.strip(), "[]")


class TestPlayerClock(unittest.TestCase):
    """SimPlayer's Playback exists only while the run plays; a change of speed,
    frame or document restores it (Playback(..., due_at=)) with its due time."""

    def setUp(self):
        from sigil.core.parse import parse_document
        self.graph = parse_document((ROOT / "site/examples/02-shop.sigil").read_text(
            encoding="utf-8"))
        self.p = app.SimPlayer(self.graph)

    def test_no_clock_until_it_plays_and_none_after_a_pause(self):
        p = self.p
        self.assertIsNone(p._clock)
        p.at = 3
        p.step(1)
        self.assertIsNone(p._clock)
        p.toggle(100.0)
        self.assertTrue(p.playing)
        self.assertIsNotNone(p._clock)
        p.toggle(100.1)
        self.assertFalse(p.playing)
        self.assertIsNone(p._clock)
        self.assertEqual(p.at, 4)

    def test_restored_with_its_due_time(self):
        p = self.p
        p.start(2, True, 50.0)
        due = p.due
        self.assertEqual(due, 50.0 + p.interval)
        p.at = 5
        self.assertEqual((p.at, p.due, p.playing), (5, due, True))
        p.speed = p.speed + 1
        self.assertEqual(p.due, due)
        q = p.rebuilt(self.graph)
        self.assertEqual((q.at, q.due, q.speed), (5, due, p.speed))
        p.at = p.last                                  # the last frame: paused there
        self.assertEqual((p.at, p.playing, p._clock), (p.last, False, None))

    def test_the_last_frame_pauses_and_drops_the_clock(self):
        p = self.p
        p.start(p.last - 1, True, 0.0)
        self.assertTrue(p.advance(p.due))
        self.assertEqual((p.at, p.playing, p._clock), (p.last, False, None))
        self.assertTrue(p.toggle(1.0))                 # from the end: over from 0
        self.assertEqual((p.at, p.playing), (0, True))


class TestFollow(unittest.TestCase):
    def test_a_shown_span_does_not_move(self):
        # 17 cells and two margins don't fit a 20-cell view: the old rule moved to
        # lo - 1 every time; cure's leaves a span already shown where it is
        self.assertEqual(app.follow_origin(10, 12, 17, 20), 10)
        self.assertEqual(app.follow_origin(0, 12, 17, 20), 10)       # not shown: the least move

    def test_a_wide_span_keeps_a_view_inside_it(self):
        self.assertEqual(app.follow_origin(35, 30, 40, 20), 35)
        self.assertEqual(app.follow_origin(0, 30, 40, 20), 30)

    def test_negative_origins(self):
        self.assertEqual(app.follow_origin(-5, 0, 3, 20), -5)
        self.assertEqual(app.follow_origin(-50, 0, 3, 20), -15)


class TestWatch(unittest.TestCase):
    def test_atomic_save_with_the_same_mtime_and_size(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "a.sigil"
            path.write_text("[A] -> [B]\n")
            st = app.ViewState(path, do_lint=False, view="graph")
            self.assertTrue(st.reload(force=True))
            self.assertFalse(st.reload())
            mtime = path.stat().st_mtime_ns
            tmp = Path(d) / "a.tmp"
            tmp.write_text("[A] -> [C]\n")
            os.utime(tmp, ns=(mtime, mtime))
            os.replace(tmp, path)
            self.assertTrue(st.reload())
            self.assertIn("C", {n.name for n in st.graph.nodes.values()})

    def test_missing_keeps_the_last_view(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "a.sigil"
            st = app.ViewState(path, do_lint=False)
            self.assertFalse(st.reload(force=True))
            path.write_text("[A] -> [B]\n")
            self.assertTrue(st.reload())
            path.unlink()
            self.assertFalse(st.reload())
            self.assertFalse(st.reload(force=True))
            self.assertIsNotNone(st.graph)


class TestHeadlessTerm(unittest.TestCase):
    def test_modes_frame_and_quit(self):
        from cure.edge.term import Term, Writer
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "doc.sigil"
            path.write_text(DOC)
            buf = bytearray()
            term = Term(None, Writer(sink=buf), env={"TERM": "xterm-256color",
                                                     "COLORTERM": "truecolor"},
                        size=(80, 24), tty=True)
            term.reader.type(b"jq")
            st = app.ViewState(path, view="graph")
            app.tui(st, term)
            out = bytes(buf)
            self.assertTrue(out.startswith(b"\x1b[?1049h\x1b[?25l\x1b[?1002h\x1b[?1006h"))
            self.assertTrue(out.endswith(b"\x1b[0m\x1b[?1006l\x1b[?1002l\x1b[?25h\x1b[?1049l"))
            self.assertIn(b"doc.sigil", out)
            self.assertIn(b"\x1b[38;2;", out)                 # truecolour, as the env says
            self.assertFalse(term.opened)

    def _drawn(self, env: dict) -> bytes:
        """The bytes tui writes for DOC on a headless Term whose env is `env`."""
        from cure.edge.term import Term, Writer
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "doc.sigil"
            path.write_text(DOC)
            buf = bytearray()
            term = Term(None, Writer(sink=buf), env=env, size=(80, 24), tty=True)
            term.reader.type(b"q")
            app.tui(app.ViewState(path, view="graph"), term)
            return bytes(buf)

    def test_colours_are_what_the_env_says(self):
        """24-bit when the env says so; the nearest of 256 colours when it says
        only TERM=xterm-256color (cure's Display), never an rgb colour dropped."""
        self.assertIn(b"\x1b[38;2;", self._drawn({"TERM": "xterm-256color",
                                                   "COLORTERM": "truecolor"}))
        out = self._drawn({"TERM": "xterm-256color"})
        self.assertNotIn(b"\x1b[38;2;", out)
        self.assertIn(b"38;5;", out)

    def test_no_color_draws_without_colour(self):
        out = self._drawn({"TERM": "xterm-256color", "COLORTERM": "truecolor",
                           "NO_COLOR": "1"})
        self.assertIn(b"doc.sigil", out)
        self.assertNotRegex(out, rb"[34]8;[25];")
        self.assertIn(b"\x1b[38;2;", self._drawn({"TERM": "xterm-256color",
                                                    "COLORTERM": "truecolor",
                                                    "NO_COLOR": ""}))   # empty: unset

    def test_screen_grid_matches_the_once_text(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "doc.sigil"
            path.write_text(DOC)
            st = app.ViewState(path, view="graph")
            st.reload(force=True)
            rows = st.frame(80, 24)
            from cure.core.buffer.rows import text
            got = text(app.screen_grid(rows, 80, 24)).split("\n")
            self.assertEqual(got, ["".join(t for t, _ in r).rstrip(" ") for r in rows])


@unittest.skipUnless(hasattr(os, "fork") and sys.platform != "win32", "a pty")
class TestPty(unittest.TestCase):
    def _run(self, finish):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "doc.sigil"
            path.write_text(DOC)
            master, slave = pty.openpty()
            os.set_blocking(master, False)
            env = {**os.environ, "TERM": "xterm-256color", "COLUMNS": "", "LINES": ""}
            proc = subprocess.Popen([str(ROOT / "bin/sigil"), "view", str(path)],
                                    stdin=slave, stdout=slave, stderr=slave, env=env,
                                    start_new_session=True)
            os.close(slave)
            out = bytearray()

            def pump(until, limit=20.0):
                end = time.monotonic() + limit
                while time.monotonic() < end and not until():
                    r, _, _ = select.select([master], [], [], 0.1)
                    if r:
                        try:
                            out.extend(os.read(master, 65536))
                        except OSError:
                            break
            try:
                pump(lambda: b"doc.sigil" in out)
                self.assertIn(b"doc.sigil", out)
                finish(proc, master)
                pump(lambda: proc.poll() is not None)
                pump(lambda: False, 0.3)
                code = proc.wait(timeout=10)
            finally:
                if proc.poll() is None:
                    proc.kill()
                os.close(master)
            return code, bytes(out)

    def test_q_restores_the_terminal(self):
        code, out = self._run(lambda proc, fd: os.write(fd, b"jq"))
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith(b"\x1b[?1049h\x1b[?25l\x1b[?1002h\x1b[?1006h"))
        self.assertIn(b"\x1b[0m\x1b[?1006l\x1b[?1002l\x1b[?25h\x1b[?1049l", out)

    def test_sigterm_leaves_with_143_restored(self):
        code, out = self._run(lambda proc, fd: proc.send_signal(signal.SIGTERM))
        self.assertEqual(code, 128 + signal.SIGTERM)
        self.assertIn(b"\x1b[0m\x1b[?1006l\x1b[?1002l\x1b[?25h\x1b[?1049l", out)


if __name__ == "__main__":
    unittest.main()
