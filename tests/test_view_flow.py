"""Tests for view_flow.py: the flow view, a call graph read left to right.

Covers:
  - the shape: bare labels (no boxes), columns by call depth, a callee on its
    caller's row, a fan-out's shared trunk (┬ ├ ╰), rounded bends, each arrow's
    stroke and head (✖ for `!>`), a source moved up to just before what it feeds;
  - a wire back to an earlier column along a return row under the drawing;
  - a target fed by several kinds of arrow: stacked heads bundled (▶┐ ✖┘);
  - tracks: a group leaving from a row another enters on goes left of it, and a
    wire only crossing another hops it;
  - chips on wires (one per call, never merged), self-call stubs, notes, a
    transition's label, expansions as parts, the --width fallback to letters;
  - wrapping to a width: chips hung under their sender with a letter in the
    wire, then bands with numbered plugs (fewest bands, then plugs), back plugs
    (↑), a plug skipping a band, the tree-view hint when a band can't fit,
    and a sim run that never reflows, its tokens crossing the plugs;
  - the overlays: a sim frame's tokens and label looks, the checks' numbers;
  - the app: VIEWS and the keys (t steps graph → tree → flow, 1 2 3 select),
    the status bar and legends, --flow on the CLI with --once / --sim / --json;
  - a long chain lays out without deep recursion.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
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


view = _load("sigil_view_flow_tests", "view.py")
vflow, kit = view.vflow, view.kit

CHECKOUT = (_DIR / "site" / "examples" / "01-checkout.sigil").read_text()
EXECUTIONS = (_DIR / "site" / "examples" / "05-executions.sigil").read_text()


def flow(text: str, **kw):
    g = view.render.parse_document(text)
    return vflow.compose_flow(g, kw.pop("depth", 1), kw.pop("payloads", False), **kw)[0]


def plain(rows) -> list:
    return ["".join(t for t, _ in r) for r in rows]


def drawn(text: str, **kw) -> str:
    return "\n".join(plain(flow(text, **kw)))


def line(rows, part: str) -> str:
    """The first row's text containing `part`."""
    return next(ln for ln in plain(rows) if part in ln)


def style_of(rows, part: str, ch: str):
    """The style of the first run containing ch in the first row containing part."""
    r = next(r for r in rows if part in "".join(t for t, _ in r))
    return next(st for t, st in r if ch in t)


class TestShape(unittest.TestCase):
    def setUp(self):
        self.rows = flow(CHECKOUT)
        self.text = "\n".join(plain(self.rows))

    def test_calls_read_left_to_right(self):
        self.assertIn("(Shopper) ──▶ [API] ─┬─▶ [Payments]", self.text)
        api = line(self.rows, "[API]")
        self.assertLess(api.index("(Shopper)"), api.index("[API]"))
        self.assertLess(api.index("[API]"), api.index("[Payments]"))

    def test_bare_labels_no_boxes(self):
        for corner in ("┌", "┐", "└", "┘", "│ [", "╭───"):
            self.assertNotIn(corner, self.text)

    def test_labels_keep_their_stream_and_mutable_leads(self):
        text = drawn("[Src] -> ~*<Raw>\n~*<Raw> -> [Sink]\n[Src] -> *<Plain>\n")
        self.assertIn("~*<Raw> ───▶ [Sink]", text)       # no box to shape: the label says it
        self.assertIn("─▶ *<Plain>", text)

    def test_fan_out_shares_a_trunk(self):
        x = line(self.rows, "[Payments]").index("┬")
        self.assertEqual(line(self.rows, "<PaymentFailed>")[x], "├")
        self.assertEqual(line(self.rows, "<OrderPlaced>")[x], "╰")
        col = line(self.rows, "[Payments]").index("[Payments]")
        for name in ("<PaymentFailed>", "|Orders|", "<OrderPlaced>"):
            self.assertEqual(line(self.rows, name).index(name), col, name)   # one column

    def test_strokes_and_heads_per_arrow(self):
        self.assertIn("─✖ <PaymentFailed>", self.text)          # !> reads without colour
        self.assertIn("╌▶ <OrderPlaced>", self.text)            # ~> dashed
        self.assertIn("═╦═▶ [Email]", self.text)                # *> double
        self.assertIn("╚═▶ |Ledger|", self.text)

    def test_wire_colours_follow_the_scene(self):
        self.assertEqual(style_of(self.rows, "(Shopper)", "─")[0], kit.kind_color("actor"))
        self.assertEqual(style_of(self.rows, "<PaymentFailed>", "✖")[0], kit.EDGE_COLOR["!>"])

    def test_a_source_sits_just_before_what_it_feeds(self):
        rows = flow("[A] -> [B]\n[B] -> [C]\n[D] -> [C]\n")
        self.assertEqual(line(rows, "[D]").index("[D]"), line(rows, "[B]").index("[B]"))
        self.assertIn("[D] ─", line(rows, "[D]"))

    def test_rounded_bends(self):
        text = drawn("[A] -> [B]\n[A] -> [C]\n")
        self.assertIn("╰", text)
        self.assertNotIn("└", text)


class TestWiresBack(unittest.TestCase):
    def test_a_cycle_returns_under_the_drawing(self):
        rows = flow("[A] -> [B]\n[B] -> [A]\n")
        text = plain(rows)
        self.assertTrue(text[0].startswith("╭─▶ [A] ──▶ [B] ─╮"), text)
        self.assertEqual(text[-1].strip()[0], "╰")              # the return row, last
        self.assertTrue(text[-1].rstrip().endswith("╯"))


class TestStackedHeads(unittest.TestCase):
    def test_two_kinds_into_one_target(self):
        rows = flow("[A] -> [C]\n[B] !> [C]\n")
        self.assertIn("▶┐[C]", line(rows, "[C]"))
        self.assertIn("✖┘", line(rows, "[B]"))

    def test_one_kind_shares_the_last_run(self):
        text = plain(flow("[A] -> [C]\n[B] -> [C]\n"))
        self.assertEqual(text[0].count("▶"), 1)
        self.assertIn("╯", text[1])


class TestTracks(unittest.TestCase):
    def test_leaving_row_goes_left_of_the_group_entering_it(self):
        enters = vflow._Group("enters", 0, frozenset({2}), False)
        leaves = vflow._Group("leaves", 2, frozenset({3}), False)
        tracks = vflow._tracks([enters, leaves])
        order = [gr.gid for track in tracks for gr in track]
        self.assertLess(order.index("leaves"), order.index("enters"))

    def test_straight_groups_need_no_track(self):
        self.assertEqual(vflow._tracks([vflow._Group("s", 1, frozenset({1}), False)]), [])

    def test_crossing_hops(self):
        text = drawn("[A] -> [X]\n[A] -> [Y]\n[A] -> [Z]\n[B] -> [Q]\n[B] -> [Z]\n")
        self.assertNotIn("┼", text)


class TestAnnotations(unittest.TestCase):
    def test_payload_chip_on_its_wire(self):
        self.assertIn("(Shopper) ────┆{Cart}┆───▶ [API]",
                      drawn(CHECKOUT, payloads=True, width=200))

    def test_two_calls_keep_two_chips(self):
        text = drawn("[A] -> |S| : get()\n[A] -> |S| : put()\n", payloads=True)
        self.assertIn("┆get()┆", text)
        self.assertIn("┆put()┆", text)

    def test_self_call_stub(self):
        text = drawn(EXECUTIONS, payloads=True, width=300)
        self.assertIn("[Scheduler] ↺", text)
        self.assertIn("╰─● ┆ ↺ plan({Seed}) ↩ {Plan} ┆", text)
        self.assertIn("[Crawler.follow] ↻", text)
        self.assertIn("(Web) ⇱", text)

    def test_notes(self):
        rows = flow(CHECKOUT, notes="markers", width=200)
        self.assertIn("(Shopper) #1", line(rows, "(Shopper)"))
        self.assertIn("#2 retried, idempotent", "\n".join(plain(rows)))

    def test_qualified_paths_ride_the_wire(self):
        text = drawn("[Ship]\n    \\-*-> [Bullet]\n        \\-& {Transform}\n"
                     "[Homing] -> [Bullet]/{Transform}\n[Bullet]/{Transform} -> [Render]\n")
        self.assertRegex(text, r"\[Homing\] ─+ \[Bullet\]/ ─+▶ \{Transform\}")
        self.assertRegex(text, r"─ from \[Bullet\]/ ─+▶ \[Render\]")

    def test_transition_label_and_expansion_parts(self):
        text = drawn("[Svc]\nstate [Svc] {\n  Idle -<go>-> Busy\n}\n")
        self.assertIn("[Svc] ▾", text)
        self.assertIn("── [Svc] state machine", text)
        self.assertIn("Idle ──── <go> ───▶ Busy", text)
        self.assertIn("[Svc] ▸", drawn("[Svc]\nstate [Svc] {\n  Idle -<go>-> Busy\n}\n",
                                       depth=0))

    def test_narrow_width_letters_the_chips(self):
        rows = flow(CHECKOUT, payloads=True, mods=True, width=75)
        text = "\n".join(plain(rows))
        self.assertIn("┆a┆", line(rows, "[API]"))
        self.assertIn("┆b┆ charge(total)", text)


ORDERS = (_DIR / "site" / "examples" / "04-orders.sigil").read_text()
SHORTENER = (_DIR / "site" / "examples" / "00-shortener.sigil").read_text()
RICH = dict(payloads=True, mods=True, notes="markers")


def widest(rows) -> int:
    """The widest drawing row (title rules are stretched to the width)."""
    return max(len(ln) for ln in plain(rows) if not ln.startswith("── "))


class TestWrap(unittest.TestCase):
    def test_hung_chips_under_their_sender(self):
        text = drawn(CHECKOUT, width=80, **RICH)
        self.assertIn("(Shopper) ─a▶ [API] ───", text)
        self.assertIn("#1            #3", text)
        self.assertIn("a┆{Cart}      b┆charge(total)", text)
        self.assertIn("               ┆×3 @timeout 2s #2", text)
        self.assertIn("              c┆insert => {Order}", text)
        self.assertNotIn("┆a┆", text)                  # no key panel at (b)
        self.assertLessEqual(widest(flow(CHECKOUT, width=80, **RICH)), 80)

    def test_letter_on_its_wire(self):
        text = drawn(CHECKOUT, width=80, **RICH)
        self.assertIn("┬b▶ [Payments]", text)            # a branch off a trunk
        self.assertIn("├c▶ |Orders|", text)
        rows = plain(flow(SHORTENER, width=50, **RICH))
        at = next(i for i, ln in enumerate(rows) if "b┬─▶ |Links|" in ln)
        self.assertEqual(rows[at + 1][rows[at].index("┬")], "d")    # a fan-in: on its vertical
        self.assertTrue(any(ln.startswith("③──┬e✖┐(Visitor)") for ln in rows))   # a back path
        self.assertIn("   ╰f▶┘", rows)

    def test_wrap_seams(self):
        def rows(text, budget=18):
            return ["".join(t for t, _ in r) for r in vflow._wrap_runs([(text, None)], budget)]
        self.assertEqual(rows("charge(total) ┆ ×3 @timeout 2s #2"),
                         ["charge(total)", "×3 @timeout 2s #2"])
        self.assertEqual(rows("shorten({Url}) ↩ {Code}"), ["shorten({Url})", "↩ {Code}"])
        self.assertEqual(rows("save({Code}, {Url})"), ["save({Code},", "{Url})"])
        self.assertEqual(rows("@inv immutable @inv content-addressed…"),
                         ["@inv immutable", "@inv content-addressed…"])   # a modifier whole
        self.assertEqual(rows("averyveryverylongwordindeed x"),
                         ["averyveryverylongwordindeed", "x"])

    def test_nothing_to_hang_cuts_at_once(self):
        text = drawn(CHECKOUT, width=50)
        self.assertIn("(Shopper) ──▶ [API] ───▶①", text)
        self.assertIn("①──┬─▶ [Payments]", text)
        self.assertNotIn("┆", text)

    def test_a_fan_out_is_cut_before_its_trunk(self):
        rows = flow(CHECKOUT, width=50, **RICH)
        text = "\n".join(plain(rows))
        self.assertIn("[API] ─────────────────▶①", text)
        self.assertIn("①──┬b▶ [Payments]", text)
        self.assertIn("   ╰╌▶ <OrderPlaced> ═══╦═▶ [Email]", text)
        self.assertLessEqual(widest(rows), 50)

    def test_fewest_plugs_not_greedy(self):
        text = drawn(ORDERS, width=80, **RICH)
        doc = text.split("── [Checkout] state machine")[0]
        self.assertIn("[Payments] ───▶①", doc)
        self.assertEqual([ch for ch in doc if "①" <= ch <= "⑳"], ["①", "①"])
        self.assertIn("①──┬╌▶ <Paid>", doc)
        self.assertIn("Idle ───────▶┐Busy", text)               # the machines stay whole

    def test_numbers_in_reading_order_and_back_plugs(self):
        rows = plain(flow(ORDERS, width=50, **RICH))
        ends = [ln[-2:] if ln.endswith("↑") else ln[-1] for ln in rows
                if ln and ("①" <= ln.rstrip("↑")[-1] <= "⑳")]
        self.assertEqual(ends, ["①", "②", "③", "④", "⑤↑"])
        self.assertTrue(any(ln.startswith("⑤╍") for ln in rows))

    def test_a_plug_skips_the_band_it_only_passes(self):
        text = "\n".join(["[Alpha] -> [Bravo]", "[Bravo] -> [Charlie]",
                          "[Charlie] -> [Delta]", "[Alpha] -> [Delta]"])
        rows = plain(flow(text, width=22))
        bands = "\n".join(rows).split("\n\n")
        holder = [b for b in bands if "[Delta]" in b][0]
        self.assertEqual(len(bands), 4)
        alpha = [b for b in bands if "[Alpha]" in b][0]
        num = [ch for ch in alpha if "①" <= ch <= "⑳"]
        self.assertEqual(len(num), 2)                              # to [Bravo], to [Delta]
        far = next(n for n in num if n in holder)
        self.assertEqual(["\n".join(bands).count(far)], [2])         # its cut end, its resume
        self.assertTrue(all(far not in b for b in bands if b not in (alpha, holder)))

    def test_plug_labels(self):
        self.assertEqual([vflow.plug_label(n) for n in (1, 2, 20, 21)], ["①", "②", "⑳", "«21»"])

    def test_tree_hint_when_a_band_cannot_fit(self):
        rows = flow(CHECKOUT, width=30, **RICH)
        text = plain(rows)
        at = text.index("flow: a band is 31 wide, 30")
        self.assertIn("tree view", " ".join(text[at:at + 3]))
        self.assertTrue(all(len(ln) <= 30 for ln in text[at:at + 3]))
        self.assertNotIn("tree view", drawn(CHECKOUT, width=50, **RICH))

    def test_fits_draws_as_before(self):
        self.assertEqual(flow(CHECKOUT, width=100), flow(CHECKOUT))
        self.assertEqual(flow(SHORTENER, width=75, **RICH)[:3],     # (a) fits: unchanged
                         flow(SHORTENER, width=75, **RICH)[:3])
        self.assertIn("┆a┆", drawn(SHORTENER, width=75, **RICH))

    def test_a_run_never_reflows_and_crosses_plugs(self):
        g = view.render.parse_document(CHECKOUT)
        player = view.SimPlayer(g, None)
        trace = player.shown(view.scene.SceneOptions("nodes", True, False, 1))
        frames = [plain(vflow.compose_flow(g, 1, True, "markers", width=50, mods=True,
                                           trace=trace, tick=t)[0])
                  for t in range(len(trace.frames))]
        self.assertEqual(len({tuple(len(ln) for ln in f) for f in frames}), 1)
        self.assertTrue(any("●①" in ln for f in frames for ln in f))    # at the cut end
        self.assertTrue(any(ln.startswith("①●") for f in frames for ln in f))   # resumed


class TestOverlays(unittest.TestCase):
    def frames(self, text, scenario="happy"):
        g = view.render.parse_document(text)
        player = view.SimPlayer(g, scenario)
        return g, player, player.shown(view.scene.SceneOptions("nodes", True, False, 1))

    def test_tokens_travel_the_wires(self):
        g, player, trace = self.frames(CHECKOUT)
        moving = next(i for i, f in enumerate(trace.frames) if f.tokens)
        rows = vflow.compose_flow(g, 1, False, trace=trace, tick=moving)[0]
        self.assertIn("●", "\n".join(plain(rows)))

    def test_final_frame_marks_the_failure(self):
        g, player, trace = self.frames(CHECKOUT, "API.charge:fails")
        rows = vflow.compose_flow(g, 1, False, trace=trace, tick=player.last)[0]
        self.assertIn("[API] ✕", line(rows, "[API]"))
        untouched = style_of(rows, "|Ledger|", "Ledger")
        self.assertEqual(untouched[0], kit.muted(kit.kind_color("store")))

    def test_checks_numbers_on_labels(self):
        text = "#!craft\n[LB] -> [App]×N\n[App] -> [Data]\n"
        g = view.render.parse_document(text)
        overlay = view.ChecksOverlay(g, view.run_checks(text), "")
        marks = overlay.marks(view.scene.SceneOptions("nodes", True, False, 1))
        rows = vflow.compose_flow(g, 1, False, checks=marks)[0]
        self.assertTrue(marks.nodes)
        self.assertIn("[Data] △1", line(rows, "[Data]"))
        self.assertEqual(style_of(rows, "[Data]", "△1"), kit.check_mark_style(
            kit.CheckMark(1, "info")))


class TestApp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "doc.sigil"
        self.path.write_text(CHECKOUT)

    def tearDown(self):
        self.tmp.cleanup()

    def state(self, **kw):
        st = view.ViewState(self.path, do_lint=False, **kw)
        st.reload(force=True)
        return st

    def test_views_and_names(self):
        self.assertEqual(view.VIEWS, ("graph", "tree", "flow", "run"))
        self.assertEqual(view.view_name(True), "tree")
        self.assertEqual(view.view_name(False), "graph")
        self.assertEqual(view.view_name("flow"), "flow")
        with self.assertRaises(ValueError):
            view.view_name("boxes")

    def test_flow_is_the_default_view(self):
        self.assertEqual(view.DEFAULT_VIEW, "flow")
        self.assertEqual(view.start_view(None), "flow")
        self.assertEqual(view.start_view(None, tree=True), "tree")
        self.assertEqual(view.start_view("graph", tree=True), "graph")
        st = self.state()
        self.assertEqual(st.view, "flow")
        text = "\n".join(plain(st.frame(200, 40)))
        self.assertIn("· flow ·", text)
        # the keys row brightens a view other than the default, as any toggle
        on = lambda st: next(r for r in view.keys_legend(st) if r[0].startswith(" view:"))[1][2]
        self.assertFalse(on(st))
        st.key("1")
        self.assertTrue(on(st))

    def test_cli_starts_in_flow_and_graph_picks_the_graph(self):
        for flags, want in (((), "─▶ [API]"), (("--graph",), "┌──")):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                view.main([str(self.path), "--once", "--no-lint", "--width", "200", *flags])
            self.assertIn(want, buf.getvalue(), flags)

    def test_t_steps_through_the_views_digits_select(self):
        st = self.state()
        seen = [st.view]
        for _ in view.VIEWS:
            st.key("t")
            seen.append(st.view)
        self.assertEqual(seen, ["flow", "run", "graph", "tree", "flow"])
        self.assertTrue(st.key("1"))
        self.assertEqual(st.view, "graph")
        self.assertFalse(st.key("1"))                  # already there
        self.assertTrue(st.key("2"))
        self.assertTrue(st.tree)
        self.assertFalse(st.key(str(len(view.VIEWS) + 1)))

    def test_bar_legend_and_keys(self):
        st = self.state(view="flow")
        text = "\n".join(plain(st.frame(200, 40)))
        self.assertIn("· flow ·", text)
        self.assertIn("flow   ──▶ call", text)
        self.assertIn("1 2 3 4 view:flow", text)
        self.assertIn("t next", text)
        self.assertIn("(Shopper) ──▶ [API]", text)

    def test_once_flow(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            status = view.once(self.path, 1, False, True, view="flow")
        self.assertEqual(status, 0)
        self.assertIn("(Shopper) ──▶ [API]", buf.getvalue())
        self.assertIn("lint: OK", buf.getvalue())

    def run_view(self, *args):
        return subprocess.run([sys.executable, str(VIEW), str(self.path), *args],
                              capture_output=True, text=True, timeout=60)

    def test_cli(self):
        p = self.run_view("--once", "--flow", "--no-lint")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("(Shopper) ──▶ [API]", p.stdout)
        p = self.run_view("--once", "--flow", "--sim", "API.charge:fails", "--no-lint")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("[API] ✕", p.stdout)
        self.assertIn("sim API.charge:fails", p.stdout)
        p = self.run_view("--once", "--flow", "--sim", "list", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('"name": "happy"', p.stdout)
        p = self.run_view("--once", "--flow", "--tree")
        self.assertEqual(p.returncode, 2)
        self.assertIn("not allowed with", p.stderr)


class TestScale(unittest.TestCase):
    def test_long_chain_without_deep_recursion(self):
        doc = "".join(f"[N{i}] -> [N{i + 1}]\n" for i in range(1500))
        rows = flow(doc)
        self.assertIn("[N1500]", plain(rows)[0])


if __name__ == "__main__":
    unittest.main()
