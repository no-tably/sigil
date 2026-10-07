"""Tests for view.py fitting a drawing to its window.

Covers:
  - callout text width adapts to the room, between CALLOUT_MIN and CALLOUT_MAX
    (narrower boxes wrap to more lines; a cut-off callout widens when it can);
  - tree view at a narrow width: block callouts relocate to a top-left panel
    (entity keeps `#N`, the box is headed `#N`); payloads and inline comments to
    a bottom-right panel (row keeps `┆a┆`, the panel repeats it);
  - graph view at a narrow width: payload chips shrink to marker letters with a
    bottom-right payload panel, block notes move to a top-left panel;
  - when everything fits, the output is the natural one, byte for byte, for
    every site example in every mode (and --once --width at that width);
  - live frames are exactly cols x rows, and use the fitted drawing;
  - --width on the command line, and 100 columns when stdout is not a tty.

Run:  python3 -m unittest discover tests
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


view = _load("sigil_view_fit", "view.py")
EXAMPLES = sorted((_DIR / "site" / "examples").glob("*.sigil"))


def text_rows(rows):
    return ["".join(t for t, _ in r) for r in rows]


def parse(text):
    return view.render.parse_document(text)


# A small document with one block note, inline notes and payloads, wide enough
# in callouts mode (≈ 90 columns) to need fitting at 60 and below.
DOC = """\
# the front door: every request passes through here first, authenticated
(Visitor) -> [Gateway] : {Request}
[Gateway] -> [Backend] : fetch(record, options) => {Record}   # cached for a minute
[Backend] -> |Records| : read(key)
[Backend] ~> <Fetched> *> [Audit] & [Metrics]   # sampled at one in ten
"""

# Graph view: payloads long enough that their chips make the graph wide.
WIDE_CHIPS = """\
# where it starts
[Source] -> [Left] : transform(alpha, beta, gamma) => {Intermediate}
[Source] -> [Right] : enrich(delta, epsilon, zeta) => {Enriched}
[Source] -> [Middle] : summarise(eta, theta, iota) => {Summary}
"""


def box_text_widths(lines):
    """The text width of each framed callout box line (`╭ … ╮`) in lines."""
    out = []
    for ln in lines:
        for m in re.finditer(r"╭ (.*?) ╮", ln):
            out.append(len(m.group(1)))
    return out


class TestCalloutWidth(unittest.TestCase):
    def test_limits_are_healthy(self):
        self.assertEqual((view.CALLOUT_MIN, view.CALLOUT_TEXT, view.CALLOUT_MAX), (16, 24, 40))

    def test_narrower_box_wraps_to_more_lines_without_losing_words(self):
        text = "the front door: every request passes through here first, authenticated"
        wide = view._callout_lines(text, "block", 24)
        narrow = view._callout_lines(text, "block", 16)
        self.assertGreater(len(narrow), len(wide))
        self.assertTrue(all(len(ln) <= 16 for ln in narrow))
        self.assertEqual(" ".join(narrow), text)          # nothing cut at the minimum

    def test_shrinks_within_limits_to_fit(self):
        g = parse(DOC)
        natural, nat_w = view.compose_tree(g, 1, notes="callouts")
        self.assertEqual(box_text_widths(text_rows(natural)), [view.CALLOUT_TEXT])
        # A little narrower than natural: the box narrows, nothing relocates.
        rows, w = view.compose_tree(g, 1, notes="callouts", width=nat_w - 4)
        lines = text_rows(rows)
        self.assertLessEqual(w, nat_w - 4)
        (tw,) = box_text_widths(lines)
        self.assertTrue(view.CALLOUT_MIN <= tw < view.CALLOUT_TEXT, tw)
        self.assertTrue(any("#>" in ln for ln in lines))   # still a margin callout

    def test_cut_off_callout_widens_when_there_is_room(self):
        long = " ".join(["word"] * 20)                     # 99 chars: cut at 24
        g = parse(f"# {long}\n[A] -> [B]\n")
        natural = "\n".join(text_rows(view.compose_tree(g, 1, notes="callouts")[0]))
        self.assertIn("…", natural)
        roomy = text_rows(view.compose_tree(g, 1, notes="callouts", width=200)[0])
        self.assertNotIn("…", "\n".join(roomy))
        (tw,) = box_text_widths(roomy)
        self.assertTrue(view.CALLOUT_TEXT < tw <= view.CALLOUT_MAX, tw)

    def test_panel_text_never_below_min_or_above_max(self):
        entries = [(1, "a fairly long note about the thing it sits on", "block")]
        for width in (5, 30, 60, 300):
            rows = view._fit_panel([[("x" * 10, None)]],
                                   lambda t, _most=None: view._callout_panel(entries, t), width, "tl", 24)
            (tw,) = box_text_widths(text_rows(rows))
            self.assertTrue(view.CALLOUT_MIN <= tw <= view.CALLOUT_MAX, (width, tw))


class TestTreeRelocation(unittest.TestCase):
    def setUp(self):
        self.g = parse(DOC)
        self.natural, self.nat_w = view.compose_tree(self.g, 1, notes="callouts", payloads=True)

    def test_narrow_relocates_both_margins(self):
        rows, w = view.compose_tree(self.g, 1, notes="callouts", payloads=True, width=40)
        lines = text_rows(rows)
        self.assertLessEqual(w, 40)
        self.assertGreater(self.nat_w, 40)
        # Top-left: the callout box, headed by its number, before the tree.
        top = lines.index(next(ln for ln in lines if ln.startswith("#1 ╭")))
        tree_row = next(i for i, ln in enumerate(lines) if ln.startswith("(Visitor)"))
        self.assertLess(top, tree_row)
        self.assertIn("(Visitor) #1", lines[tree_row])       # the entity keeps its tag
        self.assertNotIn("#>", "\n".join(lines))            # no margin leaders left
        # Bottom-right: payloads and inline comments beside their markers.
        gateway = next(ln for ln in lines if ln.startswith("[Gateway]"))
        backend = next(ln for ln in lines if ln.startswith("[Backend]"))
        mark_g = re.search(r"┆([a-z]+)┆$", gateway).group(1)
        mark_b = re.search(r"┆([a-z]+)┆$", backend).group(1)
        self.assertNotEqual(mark_g, mark_b)
        panel = lines[max(i for i, ln in enumerate(lines) if ln.startswith("[") or
                          ln.startswith("<") or ln.startswith("|")) + 1:]
        joined = "\n".join(panel)
        self.assertRegex(joined, rf"┆{mark_g}┆ \{{Request\}}")
        self.assertRegex(joined, rf"┆{mark_b}┆ fetch\(record,")
        self.assertIn("# cached for a minute", joined)
        # Every relocated payload / comment is shown, none dropped.
        for text in ("read(key)", "# sampled at one in ten"):
            self.assertIn(text, joined)
        # The panel ends at the drawing's right edge, or past it (bottom-right).
        tree_w = max(len(ln) for ln in lines[:len(lines) - len(panel)])
        self.assertGreaterEqual(max(len(ln) for ln in panel), tree_w)

    def test_markers_stay_once_per_content(self):
        rows, _w = view.compose_tree(self.g, 1, notes="callouts", payloads=True, width=40)
        lines = text_rows(rows)
        # the comment trailing the `*>` line rides two target rows: one letter
        marks = [m for ln in lines for m in re.findall(r"┆([a-z]+)┆$", ln)]
        panel_marks = [m for ln in lines for m in re.findall(r"^\s*┆([a-z]+)┆ ", ln)]
        self.assertEqual(sorted(set(marks)), sorted(panel_marks))
        self.assertEqual(len(panel_marks), len(set(panel_marks)))

    def test_narrowing_comes_first_and_never_cuts_sooner(self):
        # At 62 the right margin moves and the callout narrows (more lines),
        # still whole — it is cut at 24 only because 3 lines can't hold it.
        rows, w = view.compose_tree(self.g, 1, notes="callouts", payloads=True, width=62)
        lines = text_rows(rows)
        self.assertLessEqual(w, 62)
        (tw,) = box_text_widths(lines)
        self.assertTrue(view.CALLOUT_MIN <= tw < view.CALLOUT_TEXT, tw)
        self.assertNotIn("…", "\n".join(lines))
        self.assertTrue(any("#>" in ln for ln in lines))

    def test_moderate_width_only_moves_the_right_margin(self):
        rows, w = view.compose_tree(self.g, 1, notes="callouts", payloads=True,
                                    width=self.nat_w - 30)
        lines = text_rows(rows)
        self.assertLessEqual(w, self.nat_w - 30)
        self.assertTrue(any("#>" in ln for ln in lines))   # callouts still in the margin
        self.assertTrue(any(re.search(r"┆[a-z]┆$", ln) for ln in lines))

    def test_markers_mode_keeps_note_numbers_on_rows(self):
        g = self.g
        natural, nat_w = view.compose_tree(g, 1, notes="markers", payloads=True)
        rows, _w = view.compose_tree(g, 1, notes="markers", payloads=True, width=45)
        lines = text_rows(rows)
        backend = next(ln for ln in lines if ln.startswith("[Backend]"))
        self.assertRegex(backend, r"┆[a-z]┆ #2$")           # payload moved, #2 stays
        self.assertTrue(all(len(ln) <= 45 for ln in lines))  # notes list rewraps too

    def test_too_narrow_for_the_tree_still_relocates(self):
        rows, w = view.compose_tree(self.g, 1, notes="callouts", payloads=True, width=12)
        lines = text_rows(rows)
        self.assertTrue(any(ln.startswith("#1 ╭") for ln in lines))
        self.assertGreater(w, 12)                           # the outline is never squashed
        self.assertTrue(any(ln.startswith("(Visitor) #1") for ln in lines))


class TestGraphRelocation(unittest.TestCase):
    def test_wide_chips_become_markers_with_a_panel(self):
        g = parse(WIDE_CHIPS)
        natural, nat_w = view.compose(g, 1, True, notes="markers")
        self.assertIn("transform(alpha, beta, gamma) ↩ {Intermediate}",
                      "\n".join(text_rows(natural)))
        rows, w = view.compose(g, 1, True, notes="markers", width=60)
        lines = text_rows(rows)
        self.assertLessEqual(w, 60)
        chips = re.findall(r"┆ ([a-z]) ┆", "\n".join(lines))
        self.assertEqual(sorted(chips), ["a", "b", "c"])
        joined = "\n".join(lines)
        for letter in chips:
            self.assertRegex(joined, rf"┆{letter}┆ \S")
        self.assertIn("transform(alpha, beta, gamma)", joined)
        # the block note moved to the top-left, no list header below
        self.assertNotIn("── notes ──", joined)
        note = next(i for i, ln in enumerate(lines) if "#1 where it starts" in ln)
        first_box = next(i for i, ln in enumerate(lines) if "[Source]" in ln)
        self.assertLess(note, first_box)
        self.assertLess(lines[note].index("#1"), 60 // 2)
        panel = [i for i, ln in enumerate(lines) if re.search(r"┆[a-z]┆ ", ln)]
        self.assertGreaterEqual(min(panel), len(lines) // 2)   # payloads bottom-right

    def test_chips_stay_when_they_fit(self):
        # Too wide only because of the notes list: the chip stays in the graph.
        note = "about B: " + " ".join(["more"] * 14)
        g = parse(f"[A] -> [B] : {{Req}}\n# {note}\n[B] -> [C]\n")
        natural, nat_w = view.compose(g, 1, True, notes="markers")
        rows, w = view.compose(g, 1, True, notes="markers", width=40)
        joined = "\n".join(text_rows(rows))
        self.assertGreater(nat_w, 40)
        self.assertLessEqual(w, 40)
        self.assertIn("┆ {Req} ┆", joined)                  # still a chip in the graph
        self.assertNotIn("── notes ──", joined)
        self.assertIn("#1 about B:", joined)

    def test_notes_panel_prefers_an_empty_corner(self):
        g = parse("# where it all begins\n[Root] -> [Hub]\n"
                  "[Hub] -> [Alpha] & [Beta] & [Gamma] & [Delta] & [Epsilon]\n")
        natural, nat_w = view.compose(g, 1, False, notes="markers")
        rows, _w = view.compose(g, 1, False, notes="markers", width=nat_w - 1)
        lines = text_rows(rows)
        note = next(i for i, ln in enumerate(lines) if "#1 where it all begins" in ln)
        alpha = next(i for i, ln in enumerate(lines) if "[Alpha]" in ln)
        self.assertLess(note, alpha)                        # beside the graph's upper boxes
        self.assertTrue(lines[note].startswith("#1"))       # at the left
        self.assertNotIn("── notes", "\n".join(lines))      # no list rows added
        # the fan-out row was a column too wide: it wraps (view_graph's ladder, b)
        self.assertTrue(all(len(ln) <= nat_w - 1 for ln in lines))


class TestFitsUnchanged(unittest.TestCase):
    """When the drawing fits, fitting changes nothing: the natural output, byte for
    byte (styles included), for every site example in every mode."""

    MODES = [dict(notes=n, payloads=p, depth=d)
             for n in view.NOTE_MODES for p in (False, True) for d in (0, 1, view.ALL_DEPTH)]

    def test_examples_tree_and_graph(self):
        self.assertTrue(EXAMPLES)
        for path in EXAMPLES:
            g = parse(path.read_text())
            for m in self.MODES:
                with self.subTest(file=path.name, **m):
                    tree = view.compose_tree(g, m["depth"], notes=m["notes"],
                                             payloads=m["payloads"])
                    graph = view.compose(g, m["depth"], m["payloads"], m["notes"])
                    for width in (tree[1], tree[1] + 1, 400):
                        self.assertEqual(
                            view.compose_tree(g, m["depth"], notes=m["notes"],
                                              payloads=m["payloads"], width=width), tree)
                    for width in (graph[1], 400):
                        self.assertEqual(
                            view.compose(g, m["depth"], m["payloads"], m["notes"],
                                         width=width), graph)

    def test_once_at_the_natural_width(self):
        for path in EXAMPLES:
            for tree in (False, True):
                with self.subTest(file=path.name, tree=tree):
                    plain = io.StringIO()
                    with contextlib.redirect_stdout(plain):
                        view.once(path, view.ALL_DEPTH, True, False, colour=True,
                                  tree=tree, notes="callouts")
                    width = max(len(re.sub(r"\x1b\[[0-9;]*m", "", ln))
                                for ln in plain.getvalue().splitlines())
                    fitted = io.StringIO()
                    with contextlib.redirect_stdout(fitted):
                        view.once(path, view.ALL_DEPTH, True, False, colour=True,
                                  tree=tree, notes="callouts", width=max(width, 100))
                    self.assertEqual(fitted.getvalue(), plain.getvalue())


class TestLiveFit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "doc.sigil"
        self.path.write_text(DOC)

    def tearDown(self):
        self.tmp.cleanup()

    def test_frames_exact_and_fitted(self):
        st = view.ViewState(self.path, tree=True, notes="callouts", payloads=True,
                            do_lint=False)
        st.reload(force=True)
        for cols, rows in ((40, 12), (50, 40), (64, 30), (120, 50), (200, 60)):
            frame = st.frame(cols, rows)
            self.assertEqual(len(frame), rows)
            self.assertTrue(all(view.row_len(r) <= cols for r in frame), (cols, rows))
        lines = [ln.strip() for ln in text_rows(st.frame(40, 60))]
        self.assertTrue(any(ln.startswith("#1 ╭") for ln in lines))
        self.assertTrue(any(re.search(r"┆[a-z]┆ \{Request\}", ln) for ln in lines))
        wide = text_rows(st.frame(200, 60))
        self.assertTrue(any("#>" in ln for ln in wide))       # natural layout again
        self.assertEqual(text_rows(st._rows), text_rows(view.compose_tree(
            st.graph, st.depth, notes="callouts", payloads=True)[0]))

    def test_graph_view_frame(self):
        self.path.write_text(WIDE_CHIPS)
        st = view.ViewState(self.path, payloads=True, notes="markers", do_lint=False,
                            view="graph")
        st.reload(force=True)
        frame = st.frame(60, 50)
        self.assertEqual(len(frame), 50)
        self.assertTrue(all(view.row_len(r) <= 60 for r in frame))
        self.assertIn("┆ a ┆", "\n".join(text_rows(frame)))


class TestCli(unittest.TestCase):
    def _run(self, text, *args):
        with tempfile.NamedTemporaryFile("w", suffix=".sigil", delete=False) as f:
            f.write(text)
        buf = io.StringIO()
        argv = sys.argv
        sys.argv = ["view.py", f.name, "--once", "--no-lint", *args]
        try:
            with contextlib.redirect_stdout(buf):
                status = view.main()
        finally:
            sys.argv = argv
            Path(f.name).unlink()
        return status, buf.getvalue().splitlines()

    def test_width_option(self):
        _s, lines = self._run(DOC, "--tree", "--payloads", "--notes", "callouts",
                              "--width", "40")
        self.assertTrue(any(ln.startswith("#1 ╭") for ln in lines))
        self.assertTrue(all(len(ln) <= 40 for ln in lines[:-1]), lines)

    def test_not_a_tty_defaults_to_100_columns(self):
        args = ", ".join(f"field{i}" for i in range(14))
        doc = f"# a note\n[A] -> [B] : merge({args})\n"
        _s, lines = self._run(doc, "--tree", "--payloads", "--notes", "callouts")
        self.assertTrue(all(len(ln) <= 100 for ln in lines), max(map(len, lines)))
        _s, wide = self._run(doc, "--tree", "--payloads", "--notes", "callouts",
                             "--width", "300")
        self.assertTrue(any("#>" in ln for ln in wide))

    def test_bad_width_is_a_usage_error(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self._run(DOC, "--width", "0")


if __name__ == "__main__":
    unittest.main()
