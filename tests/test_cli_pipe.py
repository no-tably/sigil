"""A reader that closes stdout early (`sigil highlight FILE | less`, quit at once).

Covers: every command leaves quietly through one place in cli.main — no
BrokenPipeError traceback, no "Exception ignored" note at shutdown, exit 1 (as
Python's docs advise for SIGPIPE) — for highlight, highlight --stream, lint and
export --mermaid, each run as a subprocess whose reader takes one line and closes
the pipe; and in-process, a stdout with no file descriptor still gives exit 1.
The outputs are far larger than a pipe's buffer, so the write really fails.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigil import cli  # noqa: E402

SIGIL = ROOT / "bin" / "sigil"
ROWS = 4000          # ~1.3 MB highlighted, ~400 KB of lint issues: well past 64 KiB


def big_doc() -> str:
    """A long, clean sketch (every row a flow with a payload and a comment)."""
    rows = (f"[A{i}] -> [B{i}] : {{D{i}}}  # note {i}" for i in range(ROWS))
    return "#!sketch\n" + "\n".join(rows) + "\n"


def bad_doc() -> str:
    """A long sketch whose every row is a lint error (a flow with no target)."""
    return "#!sketch\n" + "".join(f"[A{i}] -> \n" for i in range(ROWS)) + "\n"


def read_one_line_then_close(argv: list, stdin=subprocess.DEVNULL):
    """Run bin/sigil, read one stdout line, close the pipe: (line, exit code, stderr)."""
    env = {k: v for k, v in os.environ.items() if k != "NO_COLOR"}   # colour on
    proc = subprocess.Popen([sys.executable, str(SIGIL), *argv], stdin=stdin,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    line = proc.stdout.readline()
    proc.stdout.close()
    err = proc.stderr.read().decode("utf-8", "replace")
    proc.stderr.close()
    return line, proc.wait(timeout=120), err


class ReaderGoneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.big = Path(cls.tmp.name) / "big.sigil"
        cls.big.write_text(big_doc(), encoding="utf-8")
        cls.bad = Path(cls.tmp.name) / "bad.sigil"
        cls.bad.write_text(bad_doc(), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def assertQuiet(self, argv, stdin=subprocess.DEVNULL):
        line, code, err = read_one_line_then_close(argv, stdin)
        self.assertTrue(line, "the command printed nothing")
        self.assertEqual(err, "", f"stderr of {argv}")
        self.assertEqual(code, 1, f"exit code of {argv}")

    def test_highlight(self):
        self.assertQuiet(["highlight", str(self.big)])

    def test_lint(self):
        self.assertQuiet(["lint", str(self.bad)])

    def test_export_mermaid(self):
        self.assertQuiet(["export", str(self.big), "--mermaid"])

    def test_highlight_stream(self):
        request = json.dumps({"id": 1, "lines": ["[A] -> [B] : {D}"] * 50}) + "\n"
        requests = Path(self.tmp.name) / "requests.jsonl"
        requests.write_text(request * 2000, encoding="utf-8")
        with open(requests, "rb") as stdin:
            self.assertQuiet(["highlight", "--stream"], stdin=stdin)

    def test_open_pipe_reads_whole_output(self):
        """With the reader staying, the output is unchanged and the exit 0."""
        piped = subprocess.run([sys.executable, str(SIGIL), "export", str(self.big),
                                "--mermaid"], capture_output=True, timeout=120)
        self.assertEqual(piped.returncode, 0)
        self.assertEqual(piped.stderr, b"")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["export", str(self.big), "--mermaid"]), 0)
        self.assertEqual(piped.stdout.decode("utf-8"), out.getvalue())


class InProcessTest(unittest.TestCase):
    def test_stdout_without_fileno(self):
        """A stand-in stdout (no file descriptor) that raises still gives exit 1."""
        class Gone(io.StringIO):
            def write(self, s):
                raise BrokenPipeError(32, "Broken pipe")

        err = io.StringIO()
        with contextlib.redirect_stdout(Gone()), contextlib.redirect_stderr(err):
            self.assertEqual(cli.main(["themes"]), 1)
        self.assertEqual(err.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
