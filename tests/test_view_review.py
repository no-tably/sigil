"""Regression tests for view.py review fixes.

Covers:
  - re-centre (z) followed by a scroll key in the same read doesn't crash;
  - a tree row that is both a lane's target and another lane's source keeps the
    incoming lane's stroke between its ◀ and that lane;
  - --depth with a bad value is a usage error (exit 2), not a traceback;
  - a theme's fill and colours are validated (bad values fall back, fill clamps);
  - a 600-node chain lays out quickly (the barycenter sweep is not quadratic);
  - a bad $SIGIL_THEME is reported once, clearly, with exit 2;
  - paging moves by the viewport height; d steps to the next larger depth;
  - the legends: payload chip sample, lane colours.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import os
import resource
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]
VIEW = _DIR / "view.py"


def _load(name: str, fname: str):
    spec = importlib.util.spec_from_file_location(name, _DIR / fname)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


view = _load("sigil_view_review", "view.py")


def plain(rows):
    return ["".join(t for t, _ in r) for r in rows]


def run_view(*args, env=None):
    return subprocess.run([sys.executable, str(VIEW), *args], capture_output=True,
                          text=True, env=env, timeout=60)


class _TempDoc(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "doc.sigil"

    def tearDown(self):
        self.tmp.cleanup()


class TestKeys(_TempDoc):
    def setUp(self):
        super().setUp()
        self.path.write_text("".join(f"[N{i}] -> [N{i + 1}]\n" for i in range(30)))
        self.st = view.ViewState(self.path, do_lint=False)
        self.st.reload(force=True)

    def test_recentre_then_scroll_in_one_read(self):
        self.st.frame(60, 20)
        for k in view.parse_keys("zj"):
            self.st.key(k)
        frame = self.st.frame(60, 20)
        self.assertEqual(len(frame), 20)
        self.assertIsInstance(self.st.sx, int)
        self.assertIsInstance(self.st.sy, int)
        self.assertGreater(self.st.sy, 0)              # centred on the tall drawing

    def test_page_moves_by_the_viewport(self):
        self.st.frame(60, 20)
        vh = self.st._vh
        self.st.key("pgdn")
        self.st.frame(60, 20)
        self.assertEqual(self.st.sy, vh)
        self.st.key(" ")
        self.st.key("pgup")
        self.st.frame(60, 20)
        self.assertEqual(self.st.sy, vh)

    def test_depth_steps_to_the_next_larger(self):
        self.st.depth = 2                              # e.g. --depth 2, not in DEPTHS
        self.st.key("d")
        self.assertEqual(self.st.depth, view.ALL_DEPTH)
        self.st.key("d")
        self.assertEqual(self.st.depth, 0)


class TestLaneStrokes(unittest.TestCase):
    def test_target_and_source_row_keeps_incoming_stroke(self):
        g = view.render.parse_document("[A] ~> [B]\n[B] *> [C]\n")
        rows, _w = view.compose_tree(g, 1)
        b = next(ln for ln in plain(rows) if ln.startswith("[B]"))
        head = b.index("◀")
        self.assertEqual(b[head + 1], "╌")             # the async lane's dashes reach ◀
        self.assertNotIn("╩", b)                       # not taken over by the double run
        self.assertNotIn("◀═", b)
        self.assertIn("✱", b)                          # and B still sources its lane

    def test_lane_colour_is_the_source_kind(self):
        g = view.render.parse_document("(User) -> [API]\n[API] !> <Failed>\n")
        rows, _w = view.compose_tree(g, 1)
        user = next(r for r in rows if plain([r])[0].startswith("(User)"))
        mark = next(st for t, st in user if "●" in t)
        self.assertEqual(mark[0], view.kind_color("actor"))
        api = next(r for r in rows if plain([r])[0].startswith("[API]"))
        fail = next(st for t, st in api if "✖" in t)
        self.assertEqual(fail[0], view.EDGE_COLOR["!>"])


class TestCli(_TempDoc):
    def test_bad_depth_is_a_usage_error(self):
        self.path.write_text("[A] -> [B]\n")
        p = run_view(str(self.path), "--once", "--depth", "abc")
        self.assertEqual(p.returncode, 2)
        self.assertIn("usage", p.stderr)
        self.assertNotIn("Traceback", p.stderr)

    def test_bad_theme_env_reported_once(self):
        self.path.write_text("[A] -> [B]\n")
        env = {**os.environ, "SIGIL_THEME": str(Path(self.tmp.name) / "missing.yaml")}
        p = run_view(str(self.path), "--once", "--no-lint", env=env)
        self.assertEqual(p.returncode, 2)
        lines = p.stderr.strip().splitlines()
        self.assertEqual(len(lines), 1, p.stderr)
        self.assertTrue(lines[0].startswith("view.py: "))
        self.assertNotIn("built-in", p.stderr)

    def test_long_chain_is_fast(self):
        """Layering stays linear-ish: doubling the chain must not quadruple the CPU
        time (the quadratic sweeps did: ~1 s → ~4 s). CPU time of the child, not
        wall-clock, so other load on the machine doesn't count."""
        took = {}
        for n in (600, 1200):
            self.path.write_text("".join(f"[N{i}] -> [N{i + 1}]\n" for i in range(n - 1)))
            before = resource.getrusage(resource.RUSAGE_CHILDREN)
            p = run_view(str(self.path), "--once", "--no-lint")
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            took[n] = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn(f"[N{n - 1}]", p.stdout)
        self.assertLess(took[1200], 3.0 * took[600] + 0.3, took)
        self.assertLess(took[1200], 4.0, took)


class TestThemeValidation(unittest.TestCase):
    def tearDown(self):
        view.use_theme("sigil")

    def test_fill_map_and_out_of_range(self):
        view.apply_theme({"ui": {"fill": {"a": "b"}}})
        self.assertEqual(view.FILL, 0.22)
        view.apply_theme({"ui": {"fill": "3"}})
        self.assertEqual(view.FILL, 1.0)
        tint = view._tint(view.CORE_KINDS["service"]["color"])
        self.assertRegex(tint, r"^#[0-9a-f]{6}$")
        view.apply_theme({"ui": {"fill": "-2"}})
        self.assertEqual(view.FILL, 0.0)
        view.apply_theme({"ui": {"fill": "nan"}})
        self.assertEqual(view.FILL, 0.22)

    def test_malformed_colours_fall_back(self):
        view.apply_theme({"kinds": {"service": "#zzzzzz", "data": "#abc"},
                          "ui": {"key_bg": "#12", "bar_bg": 7}})
        self.assertEqual(view.CORE_KINDS["service"]["color"], "#8aa0ff")
        self.assertEqual(view.CORE_KINDS["data"]["color"], "#aabbcc")
        self.assertEqual(view.KEY_STYLE[1], "#30363d")
        self.assertEqual(view.BAR_STYLE[1], "#161b22")
        view._sgr(view.KEY_STYLE)                      # every colour is SGR-safe

    def test_partial_theme_starts_from_the_builtins(self):
        view.apply_theme({"kinds": {"service": "#123456"}})
        view.apply_theme({"kinds": {"data": "#654321"}})
        self.assertEqual(view.CORE_KINDS["service"]["color"], "#8aa0ff")
        self.assertEqual(view.CORE_KINDS["data"]["color"], "#654321")


class TestLegends(unittest.TestCase):
    def test_payload_sample_is_a_rounded_dotted_chip(self):
        row = view.graph_legend(triggers=False, payloads=True)
        sample = next(t for t, _ in row if "{…}" in t)
        self.assertTrue(sample.startswith("╭┄") and sample.endswith("┄╯"), sample)

    def test_tree_legend_says_lanes_take_the_source_colour(self):
        text = "".join(t for r in view.tree_legend() for t, _ in r)
        self.assertIn("lane: its source's colour", text)
        self.assertNotIn("l-arrow", VIEW.read_text())


if __name__ == "__main__":
    unittest.main()
