"""patch-0.6.11 R4: themes, highlight, the views, frames and dialect lookup stay
bounded and honest on hostile inputs (hardening-1 probe findings).

- #4  a theme's maps nested deep, a long palette chain, a long `extends` chain:
      a ThemeError, never a RecursionError (in `sigil themes` and in a
      highlight --stream {"theme"} request, which keeps the session);
- #5  a --stream request line nested too deep for the JSON reader: an error
      answer, and the session goes on;
- #6  `frames draw --width 0` is a usage error, and wrap_cells takes any width;
- #9  a fan-in of many wires (`{S} -<Ei>-> {S}` × n) and a long chain of
      expansions: a drawing over kit.MAX_CELLS says so instead of exhausting
      memory, and graph._columns no longer tries every run of sections;
- #10 mk_id is linear in the name's length (and gives the ids it gave);
- #20 `sigil themes` warns about colours that are not #rrggbb / #rgb, unknown
      sections and roles; a FIFO or device theme is "not a regular file";
      a stream carry past any document's depth is refused;
- #21 frames follow never writes CONTROL.alive through a link, and reads the
      control file it checked (by its descriptor);
- a bare dialect name is looked up by name only, never as a path in the
  working directory;
- lines end only at \\n, \\r\\n and \\r in highlight and kit's title/mode readers.

Run:  python3 -m unittest tests.test_hardening_present
"""
from __future__ import annotations

import io
import json
import os
import random
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigil import cli  # noqa: E402
from sigil.core import dialects  # noqa: E402
from sigil.core import graph as core_graph  # noqa: E402
from sigil.core.parse import parse_document  # noqa: E402
from sigil.present import highlight, kit, themes  # noqa: E402
from sigil.present.views import flow as vflow  # noqa: E402
from sigil.present.views import graph as vgraph  # noqa: E402
from sigil.present.views import tree as vtree  # noqa: E402

SIGIL = ROOT / "bin" / "sigil"


def deep_theme(levels: int) -> str:
    """A theme of `levels` maps, each one space deeper than the last."""
    return "".join(f"{' ' * k}k{k}:\n" for k in range(levels)) + f"{' ' * levels}v: x\n"


class DeepThemes(unittest.TestCase):
    """#4"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, name: str, text: str) -> Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_maps_nested_deeper_than_the_limit_are_an_error(self):
        path = self.write("deep.yaml", deep_theme(1100))
        with self.assertRaises(themes.ThemeError) as cm:
            themes.load(str(path))
        self.assertIn(f"nested more than {themes.MAX_DEPTH} deep", str(cm.exception))
        ok = self.write("ok.yaml", deep_theme(themes.MAX_DEPTH))
        self.assertIsInstance(themes.load(str(ok)), dict)

    def test_a_long_palette_chain_resolves_without_recursion(self):
        n = 3000
        lines = ["palette:"] + [f"  p{k}: $p{k + 1}" for k in range(n)] + [f'  p{n}: "#123456"']
        theme = themes.load(str(self.write("chain.yaml", "\n".join(lines) + "\n")))
        self.assertEqual(theme["palette"]["p0"], "#123456")
        cyc = self.write("cyc.yaml", "palette:\n  a: $b\n  b: $a\n")
        with self.assertRaisesRegex(themes.ThemeError, "palette cycle"):
            themes.load(str(cyc))

    def test_a_long_extends_chain_is_an_error(self):
        for k in range(40):
            self.write(f"link-{k}.yaml",
                       f"extends: link-{k + 1}.yaml\n" if k < 39 else "name: x\n")
        with self.assertRaisesRegex(themes.ThemeError, "extends chain longer"):
            themes.load(str(self.dir / "link-0.yaml"))

    def test_sigil_themes_reports_it_cleanly(self):
        path = self.write("deep.yaml", deep_theme(1100))
        p = subprocess.run([sys.executable, str(SIGIL), "themes", str(path)],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 2)
        self.assertIn("nested more than", p.stderr)
        self.assertNotIn("Traceback", p.stderr)

    def test_a_stream_theme_request_keeps_the_session(self):
        path = self.write("deep.yaml", deep_theme(1100))
        theme, name = highlight.theme_for(None, None)
        session = highlight.StreamSession(theme, name, highlight.CORE)
        bad = session.answer(json.dumps({"id": 1, "theme": str(path)}))
        self.assertIn("nested more than", bad["error"])
        good = session.answer(json.dumps({"id": 2, "lines": ["[A] -> [B]"]}))
        self.assertNotIn("error", good)


class StreamBounds(unittest.TestCase):
    """#5, #20 (carry)"""

    def session(self):
        theme, name = highlight.theme_for(None, None)
        return highlight.StreamSession(theme, name, highlight.CORE)

    def test_a_deep_json_line_is_an_error_and_the_session_goes_on(self):
        out = io.StringIO()
        inp = io.StringIO("[" * 200000 + "\n" + json.dumps({"id": 2, "lines": ["[A]"]}) + "\n")
        self.assertEqual(highlight.stream(self.session(), inp, out), 0)
        first, second = [json.loads(ln) for ln in out.getvalue().splitlines()]
        self.assertIn("nested too deep", first["error"])
        self.assertEqual(second["id"], 2)
        self.assertNotIn("error", second)

    def test_a_carry_past_any_documents_depth_is_refused(self):
        s = self.session()
        big = highlight.MAX_CARRY_DEPTH + 1
        for carry in ([0, big, 0, 0], [0, 0, 0, big]):
            said = s.answer(json.dumps({"id": 1, "carry": carry, "lines": ["x"]}))
            self.assertIn("carry must be", said["error"])
        ok = s.answer(json.dumps({"id": 2, "carry": [0, 3, 0, 2], "lines": ["}"]}))
        self.assertNotIn("error", ok)

    def test_a_line_may_hold_a_form_feed_but_no_line_end(self):
        s = self.session()
        self.assertNotIn("error", s.answer(json.dumps({"id": 1, "lines": ["[A]\f [B]"]})))
        for text in ("a\nb", "a\rb"):
            self.assertIn("line end", s.answer(json.dumps({"id": 1, "lines": [text]}))["error"])


class LineEnds(unittest.TestCase):
    """Lines end only at \\n, \\r\\n, \\r (lex.split_lines) in highlight and kit."""

    def test_highlight_lines_and_text(self):
        theme, _name = highlight.theme_for(None, None)
        text = "[A]\f[B] x\r\n[C]\r[D]\n"
        self.assertEqual(len(highlight.lines(text)), 3)
        self.assertEqual(len(highlight.highlight_json(text, theme, "sigil",
                                                      highlight.CORE)["lines"]), 3)
        plain = highlight.highlight_text(text, theme, highlight.CORE, colour=False)
        self.assertEqual(plain, text)
        self.assertEqual(highlight.highlight_text("\n\n", theme, highlight.CORE, False), "\n\n")

    def test_kit_title_and_mode(self):
        self.assertEqual(kit.doc_title("# Title still the title\n[A]\n"),
                         "Title still the title")
        # one comment line (U+2028 ends no line), so no `#!` line follows it
        self.assertEqual(kit.doc_mode("# note\u2028#!spec\n[A]\n"), "")
        self.assertEqual(kit.doc_mode("# note\r#!spec\n[A]\n"), "#!spec")


class FramesWidth(unittest.TestCase):
    """#6"""

    def test_width_under_one_is_a_usage_error(self):
        doc = ROOT / "tests" / "fixtures" / "overlap.sigil"
        for width in ("0", "-3"):
            p = subprocess.run([sys.executable, str(SIGIL), "frames", "draw", str(doc),
                                "--width", width], capture_output=True, text=True, timeout=60)
            self.assertEqual(p.returncode, 2, width)
            self.assertIn("number of columns >= 1", p.stderr)
            self.assertNotIn("Traceback", p.stderr)

    def test_wrap_cells_takes_any_width(self):
        for text in ("hello world", "hello 世界"):
            for width in (0, -4):
                self.assertTrue(kit.wrap_cells(text, width, indent="  "))


def fan_in(n: int) -> str:
    return "#!spec\n" + "".join(f"{{S}} -<E{k}>-> {{S}}\n" for k in range(n))


class TooLargeDrawings(unittest.TestCase):
    """#9: a drawing over kit.MAX_CELLS is not drawn, it says so — in every
    view, before the work that grows with its area."""

    def test_each_view_says_so_over_the_limit(self):
        g = parse_document(fan_in(40))
        with mock.patch.object(kit, "MAX_CELLS", 400):
            for name, rows in (
                    ("graph", vgraph.compose(g, 1, False)[0]),
                    ("flow", vflow.compose_flow(g, 1, False)[0]),
                    ("tree", vtree.compose_tree(g, 1)[0])):
                text = "".join(t for row in rows for t, _s in row)
                self.assertIn(f"{name}: not drawn: the drawing would be", text, name)
        rows, _w = vflow.compose_flow(g, 1, False)              # under the limit: drawn
        self.assertNotIn("not drawn", "".join(t for row in rows for t, _s in row))

    def test_a_canvas_past_the_limit_raises(self):
        cv = kit.Canvas()
        with mock.patch.object(kit, "MAX_CELLS", 100):
            cv.put(0, 0, "x" * 50)
            with self.assertRaises(kit.TooLarge):
                cv.put(0, 2, "y")

    def test_a_large_fan_in_is_refused_quickly(self):
        g = parse_document(fan_in(2000))
        for name, compose in (("graph", lambda: vgraph.compose(g, 1, False)),
                              ("flow", lambda: vflow.compose_flow(g, 1, False)),
                              ("tree", lambda: vtree.compose_tree(g, 1))):
            start = time.monotonic()
            rows, _w = compose()
            self.assertIn("not drawn", "".join(t for row in rows for t, _s in row), name)
            self.assertLess(time.monotonic() - start, 30, name)


def old_columns(sizes, fit):
    """graph._columns as 0.6.10 wrote it: every sum of a run of sections tried."""
    n = len(sizes)
    whole = [(0, n)]
    if fit is None or n < 2:
        return whole
    tops = sorted({sum(h for h, _w in sizes[a:b]) for a in range(n) for b in range(a + 1, n + 1)})
    for top in tops:
        runs, a, h = [], 0, 0
        for i, (hi, _w) in enumerate(sizes):
            if i > a and h + hi > top:
                runs.append((a, i))
                a, h = i, 0
            h += hi
        runs.append((a, n))
        if max(sum(h for h, _w in sizes[s:e]) for s, e in runs) > top:
            continue
        wide = (sum(max(w for _h, w in sizes[s:e]) for s, e in runs)
                + vgraph.COLUMN_GAP * (len(runs) - 1))
        if wide <= fit:
            return runs
    return whole


class Columns(unittest.TestCase):
    """#9 (expansion chains): sections into columns, as before, in O(n) a cap."""

    def test_the_same_columns_as_before(self):
        r = random.Random(11)
        for _ in range(3000):
            sizes = [(r.randint(0, 30), r.randint(1, 60)) for _ in range(r.randint(0, 9))]
            fit = r.choice([None, r.randint(1, 250)])
            self.assertEqual(vgraph._columns(sizes, fit), old_columns(sizes, fit), (sizes, fit))

    def test_many_sections_are_quick(self):
        sizes = [(5 + k % 7, 20 + k % 11) for k in range(3000)]
        start = time.monotonic()
        vgraph._columns(sizes, 120)
        self.assertLess(time.monotonic() - start, 10)


def old_mk_id(name: str) -> str:
    """mk_id as 0.6.10 wrote it (quadratic in the name)."""
    safe = ""
    for ch in reversed(name.strip()):
        lit_u = ch == "u" and core_graph.re.match(r"_*(?:0[0-9a-f]|10)[0-9a-f]{4}", safe)
        safe = ("u_" if lit_u else core_graph._id_char(ch)) + safe
    if safe and safe[0].isdigit():
        safe = "n" + safe
    return safe or "anon"


class MkId(unittest.TestCase):
    """#10"""

    def test_the_same_ids_as_before(self):
        r = random.Random(5)
        alphabet = "u_0123456789abcdef-. 利Āဋ"
        for _ in range(20000):
            name = "".join(r.choice(alphabet) for _ in range(r.randint(0, 14)))
            self.assertEqual(core_graph.mk_id.__wrapped__(name), old_mk_id(name), name)

    def test_a_long_name_is_linear(self):
        start = time.monotonic()
        core_graph.mk_id.__wrapped__("u_" * 200000 + "利" * 100000)
        self.assertLess(time.monotonic() - start, 5)


class ThemeProblems(unittest.TestCase):
    """#20"""

    def test_bad_colours_and_unknown_roles_are_named(self):
        theme = {"palette": {"bg": "#12345", "fg": "red", "ok": "#abc"},
                 "edges": {"default": "#zz", "nope": "#000000"},
                 "ui": {"fill": "lots"}, "colours": {"x": "#000000"}}
        said = "\n".join(themes.problems(theme))
        for part in ("palette.bg: '#12345' is not a colour", "palette.fg: 'red'",
                     "edges.default: '#zz'", "unknown role edges.nope",
                     "ui.fill: 'lots' is not a number", "unknown section 'colours'"):
            self.assertIn(part, said)
        self.assertNotIn("palette.ok", said)
        self.assertEqual(themes.problems(themes.load("sigil")), [])

    def test_sigil_themes_warns_and_still_prints(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "bad.yaml"
            path.write_text('extends: sigil\npalette:\n  fg: "red"\n', encoding="utf-8")
            p = subprocess.run([sys.executable, str(SIGIL), "themes", str(path)],
                               capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0)
        self.assertIn("warning: palette.fg: 'red' is not a colour", p.stderr)
        self.assertEqual(json.loads(p.stdout)["palette"]["fg"], "red")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "fifos")
    def test_a_fifo_theme_is_not_a_regular_file(self):
        with tempfile.TemporaryDirectory() as d:
            fifo = Path(d) / "t.yaml"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(themes.ThemeError, "not a regular file"):
                themes.load(str(fifo))

    def test_a_huge_theme_file_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "big.yaml"
            path.write_text("# x\n" * (themes.MAX_BYTES // 4 + 1), encoding="utf-8")
            with self.assertRaisesRegex(themes.ThemeError, "larger than"):
                themes.load(str(path))


@unittest.skipUnless(hasattr(os, "getuid") and hasattr(os, "O_NOFOLLOW"), "unix")
class FollowFiles(unittest.TestCase):
    """#21"""

    def private(self) -> Path:
        d = Path(tempfile.mkdtemp(prefix="sigil-view-"))
        self.addCleanup(__import__("shutil").rmtree, d, True)
        d.chmod(0o700)
        control = d / "c.json"
        control.write_text(json.dumps({"argv": ["x.sigil"]}))
        control.chmod(0o600)
        return control

    def test_alive_is_never_written_through_a_link(self):
        control = self.private()
        victim = control.parent / "victim.txt"
        victim.write_text("keep")
        alive = control.with_name(control.name + ".alive")
        alive.symlink_to(victim)
        cli._touch_alive(alive)
        self.assertEqual(victim.read_text(), "keep")
        alive.unlink()
        cli._touch_alive(alive)
        self.assertEqual(alive.read_text(), str(os.getpid()))

    def test_the_bytes_read_are_those_of_the_file_checked(self):
        control = self.private()
        data, problem = cli.checked_control(control)
        self.assertIsNone(problem)
        self.assertEqual(cli.read_control(data), ["x.sigil"])
        link = control.with_name("link.json")
        link.symlink_to(control)
        data, problem = cli.checked_control(link)
        self.assertIsNone(data)
        self.assertIn("not a regular file", problem)

    def test_a_fifo_control_is_refused_without_waiting(self):
        control = self.private()
        control.unlink()
        os.mkfifo(control, 0o600)
        data, problem = cli.checked_control(control)
        self.assertIsNone(data)
        self.assertIn("not a regular file", problem)

    def test_bad_control_bytes_ask_for_nothing(self):
        for data in (None, b"\xff", b"[" * 100000, b'{"argv": []}',
                     b"x" * (cli.CONTROL_MAX_BYTES + 1)):
            self.assertIsNone(cli.read_control(data))


class DialectByName(unittest.TestCase):
    """A bare dialect name never loads a folder of that name in the working
    directory (SIGIL_DIALECT=foo in an untrusted checkout holding foo/dialect.py)."""

    def test_a_bare_name_is_not_a_path(self):
        with tempfile.TemporaryDirectory() as d:
            planted = Path(d) / "planted"
            planted.mkdir()
            marker = Path(d) / "ran"
            (planted / "dialect.py").write_text(
                f"open({str(marker)!r}, 'w').close()\nNAME = 'planted'\n")
            here = os.getcwd()
            os.chdir(d)
            try:
                with mock.patch.dict(os.environ, {"SIGIL_DIALECT_PATH": ""}):
                    with self.assertRaisesRegex(ValueError, "unknown sigil dialect"):
                        dialects.load("planted")
                self.assertFalse(marker.exists())
                self.assertEqual(dialects.load("./planted").NAME, "planted")   # a path: loaded
            finally:
                os.chdir(here)

    def test_a_path_that_holds_no_dialect_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "no dialect file at"):
            dialects.load("/no/such/dialect.py")


if __name__ == "__main__":
    unittest.main()
