"""Tests for every view wrapping in x and growing in y.

Covers:
  - graph view: a layer wider than the width wraps onto the layers below it (a
    node only moves down), the edges passing a layer take its room, each row
    and the frames of control blocks keep inside the width; a layout that fits
    is untouched; a box wider than the width leaves a hint;
  - tree view: lanes past the gutter columns that fit fold into numbered plugs
    (`●①` on a source row, `◀───①` on a target row), packed in a run per row; a
    token on a folded lane sits on its plugs; a tree that fits is untouched;
  - info lines (summary, lint) wrap at the width, ` · ` kept with the word after
    it, in --once and in the live footer.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]


def _load(name: str, fname: str):
    spec = importlib.util.spec_from_file_location(name, _DIR / fname)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


view = _load("sigil_view_wrap", "view.py")
vgraph, vtree, kit = view.vgraph, view.vtree, view.kit


def text_rows(rows):
    return ["".join(t for t, _ in r) for r in rows]


def parse(text):
    return view.render.parse_document(text)


# One service fanning out to eight: a single layer ~130 columns wide.
FAN = "".join(f"[Hub] -> [Worker{k}]\n" for k in range(8))
# Four long lanes beside short labels: the gutter is what makes it wide.
LANES = """\
[A] -> [B]
[A] -> [C]
[A] -> [D]
[A] -> [E]
[B] -> [E]
[C] -> [D]
"""


class TestGraphWraps(unittest.TestCase):
    def draw(self, text, width, **kw):
        rows, w = vgraph.compose(parse(text), 1, kw.pop("payloads", False), width=width, **kw)
        return text_rows(rows), w

    def test_a_wide_layer_wraps_onto_the_rows_below(self):
        natural, nat_w = self.draw(FAN, None)
        self.assertGreater(nat_w, 100)
        one_row = [r for r in natural if r.count("[Worker") == 8]
        self.assertEqual(len(one_row), 1)                 # naturally: one layer
        rows, w = self.draw(FAN, 60)
        self.assertLessEqual(w, 60)
        self.assertTrue(all(len(r) <= 60 for r in rows), rows)
        for k in range(8):
            self.assertEqual(sum(f"[Worker{k}]" in r for r in rows), 1)
        hub = next(i for i, r in enumerate(rows) if "[Hub]" in r)
        workers = [i for i, r in enumerate(rows) if "[Worker" in r]
        self.assertGreater(min(workers), hub)              # a node only moves down
        self.assertGreater(len(set(workers)), 1)           # on more than one row
        self.assertGreater(len(rows), len(natural))        # it grows down

    def test_passing_edges_take_room(self):
        # [Hub]'s edges to the second row of workers pass the first row: their
        # dummies are counted, so that row still fits
        rows, w = self.draw(FAN + "[Hub] -> [Worker0]\n[Worker0] -> [Tail]\n[Hub] -> [Tail]\n", 50)
        self.assertTrue(all(len(r) <= 50 for r in rows), "\n".join(rows))

    def test_a_layout_that_fits_is_untouched(self):
        for path in sorted((_DIR / "site" / "examples").glob("*.sigil")):
            g = parse(path.read_text())
            natural, w = vgraph.compose(g, 1, False)
            self.assertEqual(vgraph.compose(g, 1, False, width=w)[0], natural, path.name)

    def test_a_box_wider_than_the_width_says_so(self):
        rows, _w = self.draw("[ThisServiceHasAVeryLongName] -> [Short]\n", 20)
        self.assertIn("graph: a row is 33 wide, 20", " ".join(rows))

    def test_frames_keep_inside(self):
        doc = "loop @while |Q|.nonempty {\n" + FAN + "}\n"
        rows, w = self.draw(doc, 70)
        self.assertTrue(all(len(r) <= 70 for r in rows), "\n".join(rows))
        self.assertTrue(any("loop" in r for r in rows))

    def test_inside_keeps_order_and_gaps(self):
        V = {k: vgraph._V(k, 10, x=x) for k, x in (("a", 0), ("b", 40), ("c", 45))}
        vgraph._inside(V, ["a", "b", "c"], 40)
        self.assertEqual([V[k].x for k in "abc"], [0, 17, 30])
        vgraph._inside(V, ["a", "b", "c"], 20)              # can't fit: from 0, apart
        self.assertEqual([V[k].x for k in "abc"], [0, 13, 26])


class TestTreeFolds(unittest.TestCase):
    def draw(self, text, width, **kw):
        rows, w = vtree.compose_tree(parse(text), 1, width=width, **kw)
        return text_rows(rows), w

    def test_lanes_past_the_width_fold_into_plugs(self):
        natural, nat_w = self.draw(LANES, None)
        self.assertNotIn("①", "\n".join(natural))
        rows, w = self.draw(LANES, nat_w - 2)
        self.assertLessEqual(w, nat_w - 2)
        text = "\n".join(rows)
        self.assertIn("①", text)
        src = next(r for r in rows if r.startswith("[A]"))
        self.assertIn("●①", src)                           # a source row: mark + number
        dst = [r for r in rows if "①" in r and not r.startswith("[A]")]
        self.assertTrue(dst and all("◀" in r for r in dst), dst)

    def test_a_tree_that_fits_is_untouched(self):
        natural, w = self.draw(LANES, None)
        self.assertEqual(self.draw(LANES, w)[0], natural)

    def test_fold_keeps_the_kept_lanes_and_numbers_in_reading_order(self):
        lane = vtree._Lane
        lanes = [lane(0, 2, None, [0], [2], x=10), lane(1, 4, None, [1], [4], x=12),
                 lane(0, 3, None, [3], [0], x=14)]
        out = vtree._fold_lanes(lanes, 10, 1)
        self.assertEqual(out[0], lanes[0])
        # numbered by their first row: the lane over rows 0 and 3 before rows 1 and 4
        self.assertEqual([(ln.sy, ln.plug, ln.x) for ln in out[1:]], [([3], "①", 12), ([1], "②", 12)])
        self.assertEqual(vtree._token_row(out[1], 0.2), 3)  # a folded lane: its plugs
        self.assertEqual(vtree._token_row(out[1], 0.8), 0)


class TestInfoLines(unittest.TestCase):
    def test_middot_stays_with_the_word_after_it(self):
        self.assertEqual(view.info_lines("doc.sigil: 7 nodes, 8 edges, 0 expansions · #!sketch", 50),
                         ["doc.sigil: 7 nodes, 8 edges, 0 expansions", "  · #!sketch"])
        self.assertEqual(view.info_lines("short · line", 50), ["short · line"])
        self.assertEqual(view.info_lines("an-unbreakable-file-name.sigil", 10),
                         ["an-unbreakable-file-name.sigil"])

    def test_once_wraps_summary_and_lint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "d.sigil"
            path.write_text("#!sketch\n[?] -> <?> -> [?]\n")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                view.once(path, 1, False, True, width=40)
        tail = buf.getvalue().split("\n\n")[-1].splitlines()
        self.assertTrue(all(len(ln) <= 40 for ln in tail), tail)
        self.assertTrue(any(ln.startswith("info:") for ln in tail), tail)
        self.assertTrue(any(ln.startswith("  ") for ln in tail), tail)   # a continuation

    def test_the_live_footer_wraps_lint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "d.sigil"
            path.write_text("#!sketch\n[?] -> <?> -> [?]\n")
            st = view.ViewState(path)
            st.reload(force=True)
            rows = text_rows(st._footer_rows(40))
        at = next(i for i, r in enumerate(rows) if r.startswith("info:"))
        self.assertTrue(rows[at + 1].startswith("  "))      # its message carries on below
        self.assertTrue(all(len(r) <= 40 for r in rows))


if __name__ == "__main__":
    unittest.main()
