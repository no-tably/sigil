"""Tests for view.py — the live terminal graph view.

Covers:
  - layout invariants: every node label drawn once, one arrowhead per edge,
    back edges (cycles) and self-loops drawn without crashing;
  - unconnected nodes wrap into a grid instead of one very wide row;
  - every code block in language.md / examples.md lays out;
  - `--once` output + exit status (1 on a lint error);
  - the live view (ViewState, no terminal needed): reload on change, last good
    graph kept, exact frame size, centring, scroll clamping, keys, lint panel,
    colour-coded boxes.

Run:  uv run python -m unittest discover notations/sigil/tests/
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import re
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


view = _load("sigil_view", "view.py")


def draw(text: str, depth: int = 1) -> str:
    g = view.render.parse_document(text)
    out = []
    for _title, _g, cv in view.sections(g, depth):
        out.extend("".join(t for t, _ in row) for row in cv.rows())
    return "\n".join(out)


class TestLayout(unittest.TestCase):
    def test_every_label_once_and_one_head_per_edge(self):
        text = ("(User) -> [API] -> |DB|\n"
                "[API] ~> <Placed> *> [Ship] & [Mail]\n")
        out = draw(text)
        for label in ("(User)", "[API]", "|DB|", "<Placed>", "[Ship]", "[Mail]"):
            self.assertEqual(out.count(label), 1, label)
        self.assertEqual(out.count("▼"), 5)

    def test_cycle_draws_upward_head(self):
        out = draw("[A] -> [B] -> [C]\n[C] !> [A]\n")
        self.assertEqual(out.count("▼"), 2)
        self.assertEqual(out.count("✖"), 1)              # `!>`'s own head, at its target
        out = draw("[A] -> [B] -> [C]\n[C] -> [A]\n")
        self.assertEqual(out.count("▲"), 1)

    def test_bidirectional_has_both_heads(self):
        out = draw("[A] <-> [B]\n")
        self.assertEqual((out.count("▼"), out.count("▲")), (1, 1))

    def test_self_loop_marked_on_node(self):
        out = draw("[A] -> [A]\n[A] -> [B]\n")
        self.assertIn("[A] ↻", out)

    def test_holes_drawn_dashed_and_separate(self):
        out = draw("#!sketch\n[?] -> [X]\n[?] -> [Y]\n")
        self.assertEqual(out.count("[?]"), 2)
        self.assertIn("┆", out)

    def test_isolated_nodes_wrap(self):
        text = "\n".join(f"[Component{i}]" for i in range(40)) + "\n"
        g = view.render.parse_document(text)
        (_t, _g, cv), = list(view.sections(g, 1))
        self.assertLessEqual(cv.w, view.ISOLATED_WRAP)

    def test_state_machine_section_with_trigger_labels(self):
        text = "state {Job} {\n  + -<submit>-> Pending\n  Pending -<done>-> $\n}\n"
        rows, _w = view.compose(view.render.parse_document(text), 1, False)
        out = "\n".join("".join(t for t, _ in r) for r in rows)
        self.assertIn("{Job} state machine", out)
        self.assertIn("●", out)
        self.assertIn("◉", out)
        self.assertIn("<submit>", out)

    def test_payload_chip_splits_its_edge(self):
        g = view.render.parse_document("[A] -> [B] : {Req}\n[A] -> [C]\n")
        gc = view.with_chips(g, payloads=True)
        chip = next(n for n in gc.nodes.values() if n.kind == view.CHIP)
        self.assertEqual(chip.name, "{Req}")
        self.assertEqual({(e.src, e.dst) for e in gc.edges},
                         {("A_service", chip.id), (chip.id, "B_service"), ("A_service", "C_service")})
        out = draw("[A] -> [B] : {Req}\n")
        self.assertEqual(out.count("▼"), 1)           # one head, on [B], none into the chip
        self.assertIs(view.with_chips(g), g)          # nothing to add: the same graph

    def test_triggers_wire_event_to_owner_in_graph_view(self):
        text = "[P] ~> <Paid>\nstate {Order} {\n  Open -<Paid>-> Settled\n}\n"
        rows, _ = view.compose(view.render.parse_document(text), 0, False, triggers=True)
        out = "\n".join("".join(t for t, _ in r) for r in rows)
        self.assertEqual(out.count("▼"), 2)           # [P] → <Paid>, <Paid> ⇢ {Order}
        rows, _ = view.compose(view.render.parse_document(text), 0, False, triggers=False)
        self.assertEqual("\n".join("".join(t for t, _ in r) for r in rows).count("▼"), 1)

    def test_expansion_section(self):
        text = "(U) -> [API]\n[API] := {\n  [Auth] -> [H]\n}\n"
        self.assertIn("[API] ▸", draw(text, depth=0))
        out = draw(text, depth=1)
        self.assertIn("[API] ▾", out)
        self.assertIn("[Auth]", out)

    def test_all_doc_blocks_lay_out(self):
        for fname in ("examples.md", "language.md"):
            blocks = re.findall(r"```([a-z]*)\n(.*?)```", (_DIR / fname).read_text(), re.S)
            for info, b in blocks:
                if info == "text":              # a drawing, not Sigil
                    continue
                with self.subTest(fname=fname, block=b[:60]):
                    draw(b, depth=99)


class TestOnce(unittest.TestCase):
    def _run(self, text, *args):
        with tempfile.NamedTemporaryFile("w", suffix=".sigil", delete=False) as f:
            f.write(text)
        buf = io.StringIO()
        argv = sys.argv
        sys.argv = ["view.py", f.name, "--once", *args]
        try:
            with contextlib.redirect_stdout(buf):
                status = view.main()
        finally:
            sys.argv = argv
            Path(f.name).unlink()
        return status, buf.getvalue()

    def test_once_ok(self):
        status, out = self._run("#!spec\n[A] -> [B] : {Req}\n", "--payloads")
        self.assertEqual(status, 0)
        self.assertIn("┆ {Req} ┆", out)                     # a chip on the edge
        self.assertIn("lint: OK", out)
        self.assertIn("2 nodes, 1 edges", out)

    def test_once_lint_error_exit_status(self):
        # A hole in #!spec mode is a lint error.
        status, out = self._run("#!spec\n[?] -> [B]\n")
        self.assertEqual(status, 1)
        self.assertIn("error:", out)


def plain(frame):
    return ["".join(t for t, _ in row) for row in frame]


class TestLiveView(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "doc.sigil"
        self.path.write_text("[Alpha] -> [Beta]\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_reloads_on_change_and_keeps_last_good(self):
        st = view.ViewState(self.path)
        self.assertTrue(st.reload(force=True))
        self.assertIn("[Alpha]", "\n".join(plain(st.frame(100, 30))))
        self.assertFalse(st.reload())                       # unchanged file
        self.path.write_text("[Alpha] -> [Gamma] -> [Delta]\n")
        self.assertTrue(st.reload())
        self.assertIn("[Gamma]", "\n".join(plain(st.frame(100, 30))))
        self.path.unlink()                                  # mid-save
        self.assertFalse(st.reload())
        self.assertIn("[Gamma]", "\n".join(plain(st.frame(100, 30))))

    def test_frame_is_exactly_terminal_sized(self):
        st = view.ViewState(self.path)
        st.reload(force=True)
        for cols, rows in ((80, 24), (40, 10), (200, 60)):
            frame = st.frame(cols, rows)
            self.assertEqual(len(frame), rows)
            self.assertTrue(all(view.row_len(r) <= cols for r in frame))

    def test_small_graph_is_centred_both_ways(self):
        st = view.ViewState(self.path, do_lint=False)
        st.reload(force=True)
        frame = plain(st.frame(100, 41))
        rule = next(i for i, ln in enumerate(frame) if ln.startswith("── ■"))
        lines = frame[1:rule]                     # the viewport: bar and legends dropped
        hit = [i for i, ln in enumerate(lines) if "[Alpha]" in ln or "[Beta]" in ln]
        first_row = next(i for i, ln in enumerate(lines) if ln.strip())
        last_row = max(i for i, ln in enumerate(lines) if ln.strip())
        self.assertAlmostEqual(first_row, len(lines) - 1 - last_row, delta=1)
        left = min(len(ln) - len(ln.lstrip()) for ln in lines if ln.strip())
        right = max(len(ln.rstrip()) for ln in lines if ln.strip())
        self.assertAlmostEqual(left, 100 - right, delta=2)
        self.assertTrue(hit)

    def test_large_graph_scrolls_and_clamps(self):
        self.path.write_text("".join(f"[N{i}] -> [N{i + 1}]\n" for i in range(30)))
        st = view.ViewState(self.path, do_lint=False)
        st.reload(force=True)
        top = plain(st.frame(60, 20))
        self.assertIn("[N0]", "\n".join(top))              # starts at the top
        for _ in range(500):
            st.key("down")
        bottom = "\n".join(plain(st.frame(60, 20)))
        self.assertIn("[N30]", bottom)                      # clamped at the end
        st.key("g")
        self.assertIn("[N0]", "\n".join(plain(st.frame(60, 20))))

    def test_keys(self):
        st = view.ViewState(self.path)
        st.reload(force=True)
        st.key("d")
        self.assertEqual(st.depth, 99)
        st.key("p")
        self.assertTrue(st.payloads)
        st.key("l")
        self.assertFalse(st.show_lint)
        self.assertFalse(st.key("?"))
        self.assertEqual(list(view.parse_keys("\x1b[Ajq\x1b[6~")), ["up", "j", "quit", "pgdn"])

    def test_lint_panel_and_error_count(self):
        self.path.write_text("#!spec\n[?] -> [B]\n")
        st = view.ViewState(self.path)
        st.reload(force=True)
        frame = plain(st.frame(120, 30))
        self.assertTrue(any(ln.startswith("error:") for ln in frame))
        self.assertIn("1E", frame[0])

    def test_boxes_colour_coded_by_kind(self):
        self.path.write_text("(User) -> [API] -> |DB|\n")
        st = view.ViewState(self.path, do_lint=False)
        st.reload(force=True)
        styles = {}                     # run text → style, for the label runs
        for row in st.frame(100, 30)[1:]:
            for t, sty in row:
                if t in ("(", "[", "|", "User", "API", "DB"):
                    styles.setdefault(t, sty)
        # brackets in the kind's colour, the name off-white, all on the tinted fill
        self.assertEqual(styles["("][0], view.CORE_KINDS["actor"]["color"])
        self.assertEqual(styles["["][0], view.CORE_KINDS["service"]["color"])
        self.assertEqual(styles["|"][0], view.CORE_KINDS["store"]["color"])
        for name in ("User", "API", "DB"):
            self.assertTrue(styles[name][0].role.startswith("muted:kinds-"))
        self.assertTrue(all(s[1] for s in styles.values()))   # tinted fill

    def test_dialect_node_kinds_are_drawn(self):
        class Fake:
            NODE_KINDS = {"widget": {"open": "<<", "close": ">>", "color": "#123456",
                                     "border": "double", "legend": "widget"}}
        try:
            view.use_dialect(Fake)
            n = view.render.Node(id="w", name="W", kind="widget")
            self.assertEqual(view.node_label(n), "<<W>>")
            self.assertEqual(view.node_styles(n)[0][0], "#123456")
            st = view.ViewState(self.path, dialect=None)
            self.assertNotIn("widget", "".join(t for t, _ in st._legend_rule(200)))
            view.use_dialect(Fake)
            self.assertIn("widget", "".join(t for t, _ in st._legend_rule(200)))
        finally:
            view.use_dialect(None)

    def test_core_has_no_dialect_kinds(self):
        view.use_dialect(None)
        self.assertEqual(set(view.KINDS),
                         {"service", "data", "event", "actor", "store", "state", "alias"})

    def test_once_colour_emits_truecolor(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            view.once(self.path, 1, False, False, colour=True)
        self.assertIn("\x1b[38;2;", buf.getvalue())
        self.assertIn("48;2;", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
