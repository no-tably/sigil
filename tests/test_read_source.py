"""R1 (patch-0.6.11): how a document is read, the same in every command.

- bytes that are not UTF-8: "cannot read F: not UTF-8 …", exit 2, no traceback,
  in every command (and the live view keeps its last good drawing);
- a leading UTF-8 byte-order mark is dropped (it hid `#!spec`);
- lines end only at \\n, \\r\\n and \\r (as editors count them), never at a form
  feed, NEL, U+2028/2029 or the other breaks str.splitlines knows;
- every read is UTF-8, never the locale's encoding;
- a document larger than lex.MAX_SOURCE_BYTES is refused with a clear message.
"""

import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigil import cli                      # noqa: E402
from sigil.core import lex, statements    # noqa: E402
from sigil.analyse import lint            # noqa: E402

BAD = b"[A] -> [B]\n\xff\xfe\n"
GOOD = "#!sketch\n[A] -> [B]\n"


def run(argv: list, stdin: bytes | None = None) -> tuple:
    """(exit status, stdout, stderr) of `sigil argv` in-process; `stdin`: the
    bytes standard input holds."""
    out, err = io.StringIO(), io.StringIO()
    fake = None
    if stdin is not None:
        fake = io.TextIOWrapper(io.BytesIO(stdin), encoding="latin-1")
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
            mock.patch.object(sys, "stdin", fake or sys.stdin):
        try:
            code = cli.main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class NotUtf8Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bad = Path(self.tmp.name) / "bad.sigil"
        self.bad.write_bytes(BAD)

    def test_every_command_says_not_utf8(self):
        f = str(self.bad)
        out_dir = str(Path(self.tmp.name) / "out")
        cases = {
            "lint": ["lint", f], "lint --deep": ["lint", f, "--deep"],
            "check": ["check", f],
            "view --once": ["view", f, "--once"],
            "view --graph": ["view", f, "--once", "--graph"],
            "view --tree": ["view", f, "--once", "--tree"],
            "view --run": ["view", f, "--once", "--run"],
            "view --sim list": ["view", f, "--sim", "list"],
            "view --sim all": ["view", f, "--sim", "all"],
            "view --sim happy --json": ["view", f, "--sim", "happy", "--json"],
            "view --run --json": ["view", f, "--run", "--json"],
            "view --structure": ["view", f, "--structure"],
            "export --mermaid": ["export", f, "--mermaid"],
            "export --mermaid --spine": ["export", f, "--mermaid", "--spine"],
            "export --out": ["export", f, "--out", out_dir],
            "highlight": ["highlight", f],
        }
        for what, argv in cases.items():
            with self.subTest(what):
                code, _out, err = run(argv)
                self.assertEqual(code, 2, err)
                self.assertRegex(err, r"^sigil \w+: cannot read .*bad\.sigil: not UTF-8 "
                                      r"\(line 2: ")
                self.assertNotIn("Traceback", err)
                self.assertEqual(err.count("\n"), 1, err)

    def test_stdin_says_not_utf8(self):
        for cmd in ("lint", "check", "highlight"):
            with self.subTest(cmd):
                code, _out, err = run([cmd, "-"], stdin=BAD)
                self.assertEqual(code, 2, err)
                self.assertRegex(err, r"^sigil \w+: cannot read -: not UTF-8 \(line 2: ")

    def test_frames_draw_answers_an_error(self):
        code, out, _err = run(["frames", "draw", str(self.bad)])
        self.assertEqual(code, 0)
        self.assertIn("not UTF-8", json.loads(out)["error"])

    def test_live_view_keeps_its_last_drawing(self):
        from sigil.present import app
        path = Path(self.tmp.name) / "live.sigil"
        path.write_text(GOOD, encoding="utf-8")
        st = app.ViewState(path, do_lint=False)
        self.assertTrue(st.reload(force=True))
        graph = st.graph
        self.assertIsNotNone(graph)
        path.write_bytes(BAD)
        self.assertTrue(st.reload(force=True))       # the change shows (the reason why)
        self.assertIs(st.graph, graph)                # the last good drawing stays
        self.assertIn("not UTF-8", st.error)
        path.write_text(GOOD + "[B] -> [C]\n", encoding="utf-8")
        self.assertTrue(st.reload(force=True))
        self.assertIsNone(st.error)


class ByteOrderMarkTest(unittest.TestCase):
    def test_decode_drops_a_leading_bom(self):
        self.assertEqual(lex.decode_source(b"\xef\xbb\xbf#!spec\n"), "#!spec\n")
        self.assertEqual(lex.decode_source("a﻿b".encode()), "a﻿b")

    def test_bom_saved_spec_keeps_its_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "bom.sigil"
            f.write_bytes(b"\xef\xbb\xbf#!spec\n(U) -> [A]: go({R}) => {S}\n")
            code, out, err = run(["lint", str(f)])
            self.assertNotIn("SGL002", out + err)
            code, out, _err = run(["check", str(f), "--json"])
            self.assertEqual(json.loads(out)["mode"], "spec")

    def test_walk_drops_a_leading_bom(self):
        w = statements.read_document("﻿#!spec\n[A] -> [B]\n")
        self.assertEqual(w.lines[0], "#!spec")


class LineBreakTest(unittest.TestCase):
    def test_split_lines_only_at_lf_crlf_cr(self):
        text = "a\x0cb\x0bc\x85d e f\x1cg\x1dh\x1ei\r\nj\rk\nl"
        self.assertEqual(lex.split_lines(text),
                         ["a\x0cb\x0bc\x85d e f\x1cg\x1dh\x1ei", "j", "k", "l"])
        self.assertEqual(lex.split_lines(""), [])
        self.assertEqual(lex.split_lines("a\n"), ["a"])
        self.assertEqual(lex.split_lines("a\n\n"), ["a", ""])
        self.assertEqual(lex.split_lines("a\r\n\r\n"), ["a", ""])

    def test_walk_counts_lines_as_editors_do(self):
        text = "[A] -> [B] [B] -> [C]\n[C] -> [D]\n"
        w = statements.read_document(text)
        self.assertEqual(len(w.lines), 2)
        res = lint.lint("[A] -> [B]\x0c[B]\n[C] ->\n")
        lines = {d.line for d in res.diagnostics if d.severity == "error"}
        self.assertTrue(lines and lines <= {2}, res.diagnostics)


class Utf8EverywhereTest(unittest.TestCase):
    def test_no_read_in_the_locale_encoding(self):
        # read_text()/open(…) with no encoding read in the locale's (cp1252 on Windows).
        bare = re.compile(r"\.read_text\(\s*\)|\bopen\((?![^)]*(encoding|\"[rwa]?b|'[rwa]?b))")
        found = []
        for py in sorted((ROOT / "sigil").rglob("*.py")):
            for n, line in enumerate(py.read_text(encoding="utf-8").split("\n"), 1):
                if bare.search(line) and "os.open(" not in line and "fdopen" not in line:
                    found.append(f"{py.relative_to(ROOT)}:{n}: {line.strip()}")
        self.assertEqual(found, [])


class SizeCapTest(unittest.TestCase):
    def test_a_document_over_the_cap_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "big.sigil"
            f.write_text("[A] -> [B]\n" * 10, encoding="utf-8")
            with mock.patch.object(lex, "MAX_SOURCE_BYTES", 64):
                for argv in (["lint", str(f)], ["view", str(f), "--once"],
                             ["export", str(f), "--mermaid"]):
                    with self.subTest(argv[0]):
                        code, _out, err = run(argv)
                        self.assertEqual(code, 2, err)
                        self.assertIn("larger than", err)
                code, _out, err = run(["lint", "-"], stdin=b"[A]\n" * 40)
                self.assertEqual(code, 2, err)
                self.assertIn("cannot read -: larger than", err)

    def test_dev_zero_is_refused(self):
        if not Path("/dev/zero").exists():
            self.skipTest("no /dev/zero")
        with mock.patch.object(lex, "MAX_SOURCE_BYTES", 1 << 16):
            code, _out, err = run(["lint", "/dev/zero"])
        self.assertEqual(code, 2, err)
        self.assertIn("larger than", err)

    def test_the_cap_is_64_mib(self):
        self.assertEqual(lex.MAX_SOURCE_BYTES, 64 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
