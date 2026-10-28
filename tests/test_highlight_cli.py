"""`sigil highlight` — the command over sigil.present.highlight.

Covers: argv (the two forms, refused mixes, a bad theme or dialect, an
unreadable file → exit 2); the ANSI output with its escape codes stripped is the
source byte for byte (design/sigil.sigil), coloured from the default theme, plain
under NO_COLOR; stdin `-`; the --json shape (runs joined give each line, colours
resolved from the theme, the carry serialised); --stream driven as one
subprocess: several requests, an error that keeps the loop going, a theme
switch, and an editor's incremental session whose lines equal a whole --json
run after each edit. The theme, the output and the session are
sigil.present.highlight's (design/sigil.sigil: [Highlight] -> [Themes]); the
command keeps argv, stdin/stdout and the exit codes (HostEndTest).
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigil import cli  # noqa: E402
from sigil.present import highlight as hl  # noqa: E402
from sigil.present import themes  # noqa: E402

CORPUS = ROOT / "design" / "sigil.sigil"
SGR = re.compile(r"\x1b\[[0-9;]*m")


def run(argv, stdin: str | None = None, env: dict | None = None):
    """cli.main in-process: (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    patches = [contextlib.redirect_stdout(out), contextlib.redirect_stderr(err),
               mock.patch.dict(os.environ, env or {})]
    if stdin is not None:
        patches.append(mock.patch.object(sys, "stdin", io.StringIO(stdin)))
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        try:
            code = cli.main(argv)
        except SystemExit as exc:          # argparse refusals
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def plain_env() -> dict:
    """An environment with NO_COLOR and SIGIL_THEME unset (for subprocesses)."""
    env = {k: v for k, v in os.environ.items() if k not in ("NO_COLOR", "SIGIL_THEME")}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


class ArgvTest(unittest.TestCase):
    def test_help_lists_both_forms(self):
        code, out, _err = run(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("sigil highlight FILE|- [--theme NAME|PATH] [--dialect D] [--json]", out)
        self.assertIn("sigil highlight --stream", out)
        code, out, _err = run(["highlight", "--help"])
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("usage: sigil highlight "), out[:80])
        for word in ("--stream", '"sigil_highlight": 1', "[quote, decl, decl_raw, state]"):
            self.assertIn(word, out)

    def test_refused_mixes_exit_2(self):
        for argv in (["highlight"], ["highlight", "--stream", str(CORPUS)],
                     ["highlight", "--stream", "--json"], ["highlight", "--bogus", "x"]):
            with self.subTest(argv=argv):
                code, out, err = run(argv)
                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith("usage: sigil highlight "), err)

    def test_unreadable_file_bad_theme_bad_dialect_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.sigil"
            bad.write_bytes(b"[A] -> \xff\n")
            cases = ((["highlight", str(Path(tmp) / "missing.sigil")], "cannot read"),
                     (["highlight", tmp], "cannot read"),
                     (["highlight", str(bad)], "not UTF-8"),
                     (["highlight", str(CORPUS), "--theme", "no-such-theme"], ""),
                     (["highlight", str(CORPUS), "--dialect", "no-such-dialect"], ""))
            for argv, said in cases:
                with self.subTest(argv=argv):
                    code, out, err = run(argv)
                    self.assertEqual((code, out), (2, ""))
                    self.assertTrue(err.startswith("sigil highlight: "), err)
                    self.assertIn(said, err)


class AnsiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = CORPUS.read_text(encoding="utf-8")
        cls.code, cls.out, cls.err = run(["highlight", str(CORPUS)], env={"NO_COLOR": ""})

    def test_stripped_output_is_the_source(self):
        self.assertEqual((self.code, self.err), (0, ""))
        self.assertIn("\x1b[38;2;", self.out)
        self.assertEqual(SGR.sub("", self.out), self.text)

    def test_colours_come_from_the_default_theme(self):
        mode = hl.colour("ui.mode", themes.load("sigil"))
        r, g, b = (int(mode[k:k + 2], 16) for k in (1, 3, 5))
        first = self.out.splitlines()[0]
        self.assertEqual(first, f"\x1b[38;2;{r};{g};{b}m#!sketch\x1b[0m")

    def test_line_endings_kept(self):
        text = "#!sketch\r\n[A] -> [B]\n\n# no newline at the end"
        code, out, _err = run(["highlight", "-"], stdin=text)
        self.assertEqual(code, 0)
        self.assertEqual(SGR.sub("", out), text)

    def test_no_color_prints_plain(self):
        code, out, _err = run(["highlight", str(CORPUS)], env={"NO_COLOR": "1"})
        self.assertEqual((code, out), (0, self.text))

    def test_stdin(self):
        code, out, _err = run(["highlight", "-"], stdin=self.text, env={"NO_COLOR": ""})
        self.assertEqual((code, out), (0, self.out))


class JsonTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = CORPUS.read_text(encoding="utf-8")
        code, out, _err = run(["highlight", str(CORPUS), "--json", "--theme", "sigil"])
        assert code == 0
        cls.doc = json.loads(out)

    def test_shape(self):
        self.assertEqual(sorted(self.doc), ["carry", "lines", "sigil_highlight", "theme"])
        self.assertEqual((self.doc["sigil_highlight"], self.doc["theme"]), (1, "sigil"))
        raws = self.text.splitlines()
        self.assertEqual(len(self.doc["lines"]), len(raws))
        self.assertEqual(len(self.doc["carry"]), len(raws))
        for raw, runs in zip(raws, self.doc["lines"]):
            self.assertEqual("".join(text for text, _role, _hex in runs), raw)
            for run_ in runs:
                self.assertEqual(len(run_), 3)
                self.assertTrue(run_[0])

    def test_colours_resolve_from_the_theme(self):
        theme = themes.load("sigil")
        roles = set()
        for runs in self.doc["lines"]:
            for _text, role, hexa in runs:
                self.assertEqual(hexa, hl.colour(role, theme))
                roles.add(role)
        self.assertIn("kinds.service", roles)
        self.assertIn(None, roles)

    def test_carry_matches_the_module(self):
        ends = [hl.carry_json(line.end) for line in hl.lines(self.text)]
        self.assertEqual(self.doc["carry"], ends)
        for end in ends:
            self.assertEqual(hl.carry_json(hl.carry_from_json(end)), end)
        self.assertEqual(hl.carry_json(hl.PLAIN), [0, 0, 1, 0])
        self.assertEqual(hl.carry_from_json(None), hl.PLAIN)
        for bad in ([0, 0, 1], [2, 0, 1, 0], [0, -1, 1, 0], [0, 0, 1, True], "x", {}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                hl.carry_from_json(bad)


def whole(text: str) -> dict:
    """A whole --json run of `text` (in-process, through a temporary file)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "doc.sigil"
        path.write_text(text, encoding="utf-8")
        code, out, _err = run(["highlight", str(path), "--json"], env={"SIGIL_THEME": ""})
    assert code == 0
    return json.loads(out)


class Editor:
    """An editor holding a document's lines, runs and end carries, driving one
    `sigil highlight --stream` the incremental way."""

    def __init__(self, proc, raws: list):
        self.proc, self.raws, self.ids = proc, list(raws), 0
        got = self.ask({"lines": self.raws, "start": 0, "carry": None})
        self.runs, self.ends = got["lines"], got["carry"]
        self.sent = len(self.raws)

    def ask(self, req: dict) -> dict:
        self.ids += 1
        req = {"id": self.ids, **req}
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        got = json.loads(self.proc.stdout.readline())
        assert got["id"] == self.ids, got
        return got

    def replace(self, a: int, b: int, new: list) -> None:
        """Lines [a, b) become `new`: send them with the carry of the line before,
        then each following line until its end carry is the one held."""
        # The last new line hands the next line a carry: the one the last old line did.
        held = [None] * len(new)
        if new and b > a:
            held[-1] = self.ends[b - 1]
        old_ends = self.ends[:a] + held + self.ends[b:]
        self.raws[a:b] = new
        self.runs[a:b] = [None] * len(new)
        self.ends = old_ends
        carry = self.ends[a - 1] if a else None
        j, count = a, max(len(new), 1)
        self.sent = 0
        while j < len(self.raws):
            chunk = self.raws[j:j + count]
            got = self.ask({"lines": chunk, "start": j, "carry": carry})
            self.assertions(got, j, len(chunk))
            stop = None
            for k, (runs, end) in enumerate(zip(got["lines"], got["carry"])):
                held = self.ends[j + k]
                self.runs[j + k], self.ends[j + k] = runs, end
                if j + k >= a + len(new) - 1 and held == end:
                    stop = j + k + 1
                    break
            self.sent += len(chunk) if stop is None else stop - j
            if stop is not None:
                return
            carry, j, count = got["carry"][-1], j + len(chunk), 1

    @staticmethod
    def assertions(got: dict, start: int, n: int) -> None:
        assert "error" not in got, got
        assert got["start"] == start and len(got["lines"]) == n == len(got["carry"]), got


class StreamTest(unittest.TestCase):
    def test_a_session(self):
        text = CORPUS.read_text(encoding="utf-8")
        proc = subprocess.Popen([sys.executable, str(ROOT / "bin" / "sigil"), "highlight",
                                 "--stream"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                env=plain_env())
        try:
            self._requests(proc)
            self._incremental(proc, text)
            proc.stdin.close()
            self.assertEqual(proc.wait(timeout=30), 0)
            self.assertEqual(proc.stderr.read(), "")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            for pipe in (proc.stdout, proc.stderr):
                pipe.close()

    def _requests(self, proc):
        def ask(line: str) -> dict:
            proc.stdin.write(line + "\n")
            proc.stdin.flush()
            return json.loads(proc.stdout.readline())

        got = ask(json.dumps({"id": "a", "lines": ["[A] -> [B]", ""], "start": 7}))
        self.assertEqual(sorted(got), ["carry", "id", "lines", "start"])
        self.assertEqual((got["id"], got["start"]), ("a", 7))
        self.assertEqual(got["carry"], [[0, 0, 1, 0], [0, 0, 1, 0]])
        self.assertEqual(got["lines"][1], [])
        self.assertEqual("".join(r[0] for r in got["lines"][0]), "[A] -> [B]")
        self.assertIn(["->", "syntax.operator",
                       hl.colour("syntax.operator", themes.load("sigil"))], got["lines"][0])
        # A block string opened on one line: the carry says so, the next line is string.
        got = ask(json.dumps({"id": 2, "lines": ['[A] -> [B] : """'], "carry": None}))
        self.assertEqual(got["carry"], [[1, 0, 1, 0]])
        got = ask(json.dumps({"id": 3, "lines": ["still text"], "carry": [1, 0, 1, 0]}))
        self.assertEqual([r[1] for r in got["lines"][0]], ["syntax.string"])
        # Errors answer and the loop goes on.
        for line, rid in (("{not json", None), ("[1, 2]", None),
                          (json.dumps({"id": 4, "lines": "x"}), 4),
                          (json.dumps({"id": 5, "lines": ["a\nb"]}), 5),
                          (json.dumps({"id": 6, "lines": [], "carry": [9]}), 6),
                          (json.dumps({"id": 7, "lines": [], "start": -1}), 7),
                          (json.dumps({"id": 8}), 8),
                          (json.dumps({"id": 9, "theme": "no-such-theme"}), 9)):
            with self.subTest(line=line):
                got = ask(line)
                self.assertEqual(sorted(got), ["error", "id"])
                self.assertEqual(got["id"], rid)
        proc.stdin.write("\n")                           # a blank line: no answer
        # A theme switch (by path: the same theme read from its file).
        path = str(ROOT / "themes" / "sigil.yaml")
        self.assertEqual(ask(json.dumps({"id": 10, "theme": path})),
                         {"id": 10, "theme": "sigil"})
        got = ask(json.dumps({"id": 11, "theme": "sigil", "lines": ["#!spec"]}))
        self.assertEqual((got["theme"], got["lines"][0][0][1]), ("sigil", "ui.mode"))

    def _incremental(self, proc, text):
        raws = text.splitlines()
        ed = Editor(proc, raws)
        self.assertEqual(ed.runs, whole(text)["lines"])
        mid = len(raws) // 2
        edits = (
            (mid, mid + 1, [raws[mid] + " # an edited comment"]),    # one line, same carry
            (mid, mid, ['[X] -> [Y] : """']),                        # opens a block string
            (mid + 3, mid + 3, ['"""']),                             # closes it
            (mid, mid + 1, []),                                      # the opener goes
            (5, 5, ["state {Doc} {", "  + -> Open", "}", ""]),        # a state block
        )
        sent = []
        for a, b, new in edits:
            with self.subTest(edit=(a, b, new)):
                ed.replace(a, b, new)
                sent.append(ed.sent)
                doc = whole("\n".join(ed.raws))
                self.assertEqual(ed.runs, doc["lines"])
                self.assertEqual(ed.ends, doc["carry"])
        self.assertEqual(sent[0], 1)                     # a keystroke costs a line
        self.assertGreater(sent[1], 3)                   # an open string runs on


class HostEndTest(unittest.TestCase):
    """highlight's hosts' end, in-process: what the command calls."""

    def test_the_command_holds_no_session(self):
        for name in ("StreamSession", "stream", "carry_json", "runs_json", "ansi_line",
                     "highlight_text", "highlight_json", "theme_name", "HIGHLIGHT_PROTOCOL"):
            self.assertNotIn(name, vars(cli), name)

    def test_serve_answers_each_request(self):
        theme, name = hl.theme_for("sigil", None)
        inp = io.StringIO('{"id": 1, "lines": ["[A] -> [B]"]}\n\n[1]\n'
                          '{"id": 2, "theme": "sigil"}\n')
        out = io.StringIO()
        self.assertEqual(hl.serve(inp, out, theme, name, hl.CORE), 0)
        got = [json.loads(s) for s in out.getvalue().splitlines()]
        self.assertEqual([g["id"] for g in got], [1, None, 2])
        self.assertEqual(got[0]["lines"], [hl.runs_json(hl.line("[A] -> [B]")[0], theme,
                                                        hl.CORE)])
        self.assertEqual(got[1]["error"], "a request is a JSON object")
        self.assertEqual(got[2]["theme"], name)

    def test_write_text_is_the_command_output(self):
        text = CORPUS.read_text(encoding="utf-8")
        theme, name = hl.theme_for("sigil", None)
        for as_json, colour in ((False, True), (False, False), (True, True)):
            out = io.StringIO()
            hl.write_text(text, out, theme, name, hl.CORE, as_json=as_json, colour=colour)
            argv = ["highlight", str(CORPUS), "--theme", "sigil"] + (["--json"] if as_json
                                                                      else [])
            env = {"NO_COLOR": "" if colour else "1"}
            code, printed, _err = run(argv, env=env)
            self.assertEqual((code, out.getvalue()), (0, printed))


if __name__ == "__main__":
    unittest.main()
