"""Tests for view_run.py: the run view, one simulated run drawn as a timeline.

Covers:
  - the timeline: a lane per participant in first-acted order, a ruler, bars
    (█ working, ░ waiting, ◆ an event landing, ✕ failed), calls drawn at their
    send tick (╰──▶ into the callee's first cell), retries as repeated segments
    (╰───✖), a route's ✖ head, a reply on the callee's lane (───↩), async (╮ ╎),
    fan-out sharing one vertical (├══▶ ╰══▶), a race's loser (⊘);
  - recursion levels as ↻k sub-rows ending ┤, self-calls ↺, host ops ⇱;
  - spawned lanes (◌ while the spawn hop flies) and folds (`{…×4 more}`);
  - the playhead: nothing right of the tick, lanes appear when born, ▼ on the
    ruler, ┊ down the blank cells, tokens on the transits, ▸ running;
  - notes: plain words per lane, shrunk to fit (the outcome last), below the
    drawing when narrow; bands when wider than the width; quiet ticks folded;
  - without a run: the happy run, said so; mono (--color never) cues only;
  - the app: VIEWS and key 4, t, n and u in the run view, --run on the CLI with
    --once / --sim / --json / --unroll, the legend, sim_focus.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
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


view = _load("sigil_view_run_tests", "view.py")
vrun, kit, sim = view.vrun, view.kit, view.simulator

CHECKOUT = _DIR / "site" / "examples" / "01-checkout.sigil"
ARENA = _DIR / "site" / "examples" / "03-arena.sigil"
EXECUTIONS = _DIR / "tests" / "fixtures" / "executions.sigil"
RACE = """(User) -> [Api]
parallel @all {
  [Api] -> [Inventory] : reserve => {Hold}
  [Api] -> [Fraud] : score
}
       !> [Inventory] : release({Hold})
parallel @any {
  [Api] -> [MirrorA]
  [Api] -> [MirrorB]
}
"""


def parse(path_or_text):
    text = path_or_text.read_text() if isinstance(path_or_text, Path) else path_or_text
    return view.render.parse_document(text)


def trace_of(g, name: str = "happy", limits=None):
    limits = limits or sim.Limits()
    canon = sim.canonical(g)
    return sim.simulate(canon, sim.scenario(canon, name, limits=limits), limits=limits)


def plain(rows) -> list:
    return ["".join(t for t, _ in r) for r in rows]


def drawn(path_or_text, name: str | None = None, tick=None, width=None, limits=None, **kw):
    g = parse(path_or_text)
    tr = trace_of(g, name, limits) if name else None
    rows, _w = vrun.compose_run(g, tr, tick, width, limits=limits, **kw)
    return plain(rows)


def row(lines: list, label: str) -> str:
    return next(ln for ln in lines if ln.lstrip(" ▸").startswith(label))


def cells(lines: list, label: str) -> str:
    """A lane's cells: its row from the timeline's first column."""
    ruler = next(ln for ln in lines if ln.strip().startswith("0"))
    x0 = ruler.index("0")
    return row(lines, label)[x0:]


class TestTimeline(unittest.TestCase):
    def test_retries_route_and_failure(self):
        lines = drawn(CHECKOUT, "API.charge:fails", width=140)
        self.assertEqual(lines[0].split(" ─")[0], "── run · API.charge:fails — charge fails 4×, "
                                                   "no fallback")
        self.assertTrue(cells(lines, "(Shopper)").startswith("█░░░"))
        self.assertTrue(cells(lines, "(Shopper)").rstrip().split("   ")[0].endswith("░✕"))
        self.assertTrue(cells(lines, "[API]").startswith("╰──▶██░░░░█░░░░█░░░░█░░░░█░░░░✕"))
        self.assertIn("╰───✖╰───✖╰───✖╰───✖", cells(lines, "[Payments]"))
        self.assertNotIn("█", cells(lines, "[Payments]"))      # it never ran
        self.assertIn("╰──✖◆", cells(lines, "<PaymentFailed>"))
        self.assertIn("4 attempts, each fails", row(lines, "[Payments]"))
        self.assertTrue(row(lines, "[API]").endswith("fails"))

    def test_lanes_in_first_acted_order(self):
        lines = drawn(CHECKOUT, "happy", width=140)
        order = [ln.split()[0] for ln in lines[3:11]]
        self.assertEqual(order, ["(Shopper)", "[API]", "[Payments]", "|Orders|",
                                 "<OrderPlaced>", "[Email]", "[Shipping]", "|Ledger|"])

    def test_reply_async_and_fan_out(self):
        lines = drawn(CHECKOUT, "happy", width=140)
        self.assertIn("╰──▶█───↩", cells(lines, "|Orders|"))      # on the callee's lane
        self.assertIn("░╮", cells(lines, "[API]"))                 # its bar ends as it emits
        self.assertIn("╰╌╌▶◆█░░░░░", cells(lines, "<OrderPlaced>"))
        self.assertIn("├══▶█", cells(lines, "[Email]"))
        self.assertIn("╰══▶█", cells(lines, "|Ledger|"))
        self.assertIn("fans out to 3, waits for all", row(lines, "<OrderPlaced>"))

    def test_a_race_loser_is_cancelled_on_the_way(self):
        lines = drawn(RACE, "happy", width=100)
        self.assertIn("╰───⊘", cells(lines, "[MirrorB]"))
        self.assertIn("cancelled on the way: lost", row(lines, "[MirrorB]"))

    def test_recursion_levels_self_calls_and_host_ops(self):
        lines = drawn(EXECUTIONS, "happy", width=300)
        k = next(i for i, ln in enumerate(lines) if ln.strip().startswith("[Builder]"))
        self.assertEqual(lines[k + 1].split()[0], "↻2")
        self.assertEqual(lines[k + 2].split()[0], "↻3")
        self.assertIn("╰──▶██░░░───↩", cells(lines, "[Builder]"))
        self.assertIn("╰█┤", lines[k + 2])
        self.assertIn("█↺██", cells(lines, "[Scheduler]"))
        self.assertIn("╰──▶⇱", cells(lines, "(Web)"))
        self.assertIn("⇱█", cells(lines, "[Notifier]"))
        self.assertIn("recurses to depth 3 each time", row(lines, "[Builder]"))

    def test_an_expansion_sits_under_its_node(self):
        lines = drawn(EXECUTIONS, "happy", width=300)
        self.assertTrue(row(lines, "[Lexer]").startswith("    [Lexer]"))
        self.assertTrue(row(lines, "[Parser]").startswith("  [Parser]"))


class TestPlayhead(unittest.TestCase):
    def test_nothing_right_of_the_tick(self):
        lines = drawn(CHECKOUT, "API.charge:fails", tick=17, width=140, notes="off")
        ruler = next(ln for ln in lines if "▼17" in ln)
        x = ruler.index("▼")
        for ln in lines[3:]:
            if ln.strip():
                self.assertLessEqual(len(ln), x + 1)
        self.assertFalse(any("<PaymentFailed>" in ln for ln in lines))   # not born yet
        self.assertTrue(cells(lines, "[Payments]").endswith("╰─●"))     # attempt 3 flies

    def test_the_playhead_column_and_running(self):
        lines = drawn(CHECKOUT, "happy", tick=10, width=140, notes="off")
        self.assertTrue(any(ln.startswith("▸ [API]") for ln in lines))   # it sends now
        lines = drawn(CHECKOUT, "happy", tick=12, width=140, notes="off")
        self.assertTrue(cells(lines, "[Payments]").endswith("│ ┊"))     # the blank cells
        self.assertFalse(any(ln.startswith("▸") for ln in lines))       # all wait

    def test_a_spawned_lane_is_pending_while_its_hop_flies(self):
        lines = drawn(ARENA, "happy", tick=34, width=140, notes="off")
        self.assertIn("[Shard·1] ◌", row(lines, "[Shard·1]"))
        self.assertTrue(cells(lines, "[Shard·1]").rstrip().endswith("╰━●"))
        done = drawn(ARENA, "happy", width=140)
        self.assertNotIn("◌", row(done, "[Shard·1]"))
        self.assertIn("spawned by [Spawner] for [Asteroid]", row(done, "[Shard·1]"))

    def test_the_label_column_holds_still_as_lanes_appear(self):
        def x0(lines):
            ruler = next(ln for ln in lines if ln.strip().startswith("0"))
            return ruler.index("0")
        early = drawn(CHECKOUT, "happy", tick=10, width=140, notes="off")
        self.assertFalse(any("<OrderPlaced>" in ln for ln in early))   # the widest, not born
        self.assertEqual(x0(early), x0(drawn(CHECKOUT, "happy", width=140, notes="off")))

    def test_notes_say_so_far(self):
        lines = drawn(CHECKOUT, "API.charge:fails", tick=17, width=140)
        self.assertIn("3 attempts so far, each fails", row(lines, "[Payments]"))


class TestWithoutARun(unittest.TestCase):
    def test_the_happy_run_said_so(self):
        lines = drawn(CHECKOUT, width=140)
        self.assertIn("── run · happy — no scenario chosen: the happy run", lines[0])
        self.assertTrue(any(ln.startswith("happy run (every default) · ok · 32 frames")
                            and "x plays it" in ln for ln in lines))

    def test_mono_every_cue_is_a_glyph(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            view.once(CHECKOUT, 1, False, False, view="run", sim="API.charge:fails",
                      width=100, colour=False)
        text = buf.getvalue()
        self.assertNotIn("\x1b[", text)
        for glyph in ("█", "░", "◆", "✕", "✖", "▶", "╰"):
            self.assertIn(glyph, text)
        self.assertIn("run    █ working  ░ waiting", text)


class TestWidth(unittest.TestCase):
    def test_notes_shrink_then_move_below(self):
        wide = drawn(CHECKOUT, width=140)
        self.assertIn("calls [Payments], then |Orders|", row(wide, "[API]"))
        narrow = drawn(CHECKOUT, width=80)
        self.assertNotIn("calls [Payments], then", row(narrow, "[API]"))
        self.assertIn("fans out to 3", row(narrow, "<OrderPlaced>"))  # the role outlasts "lands"
        tight = drawn(CHECKOUT, width=56)                 # no room beside: below
        below = [ln for ln in tight if ln.startswith("  <OrderPlaced>") and "◆" not in ln]
        self.assertTrue(below)

    def test_fit_note_keeps_the_outcome(self):
        C = vrun.Clause
        cl = [C("episode 1's entry", vrun.ENTRY), C("calls [API]", vrun.MINOR),
              C("fails", vrun.OUTCOME)]
        self.assertEqual(vrun._fit_note(cl, 100), "episode 1's entry; calls [API]; fails")
        self.assertEqual(vrun._fit_note(cl, 26), "episode 1's entry; fails")
        self.assertEqual(vrun._fit_note(cl, 6), "fails")
        short = [C("produces into [Shard]: a new instance", vrun.ROLE, "produces into [Shard]")]
        self.assertEqual(vrun._fit_note(short, 24), "produces into [Shard]")

    def test_bands(self):
        lines = drawn(EXECUTIONS, width=100)
        rulers = [ln for ln in lines if ln.strip()[:1].isdigit() or ln.strip().startswith("ep")]
        self.assertGreaterEqual(len(rulers), 2)
        second = lines.index(rulers[1])
        band2 = lines[second:next(i for i in range(second + 1, len(lines)) if not lines[i])]
        self.assertFalse(any(ln.strip().startswith("[Metrics]") for ln in band2))
        self.assertTrue(any(ln.strip().startswith("[Indexer]") for ln in band2))
        self.assertTrue(all(len(ln) <= 100 for ln in lines))

    def test_quiet_stretches_fold(self):
        limits = sim.limits_from(["hop=12"])
        lines = drawn(CHECKOUT, "API.charge:fails", width=140, limits=limits)
        ruler = next(ln for ln in lines if ln.strip().startswith("0"))
        self.assertIn("≈", ruler)
        self.assertTrue(ruler.rstrip().endswith("78"))
        self.assertLess(len(cells(lines, "[API]").split("   ")[0]), 79)

    def test_instances_fold(self):
        limits = sim.limits_from(["spawn=6"])
        lines = drawn(ARENA, width=160, limits=limits)
        folds = [ln for ln in lines if "{…×4 more}" in ln]
        self.assertEqual(len(folds), 2)
        self.assertIn("[Bullet·3‥6]'s, alike", folds[0])
        unfolded = drawn(ARENA, width=160, limits=limits, show=0)
        self.assertFalse(any("more}" in ln for ln in unfolded))


class TestApp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "doc.sigil"
        self.path.write_text(CHECKOUT.read_text())

    def tearDown(self):
        self.tmp.cleanup()

    def state(self, **kw):
        st = view.ViewState(self.path, do_lint=False, **kw)
        st.reload(force=True)
        return st

    def test_key_4_and_t(self):
        st = self.state()
        self.assertTrue(st.key("4"))
        self.assertEqual(st.view, "run")
        st.key("t")
        self.assertEqual(st.view, "graph")
        text = "\n".join(plain(self.state(view="run").frame(160, 40)))
        self.assertIn("· run ·", text)
        self.assertIn("1 2 3 4 view:run", text)
        self.assertIn("no scenario chosen", text)
        self.assertIn("run    █ working", text)

    def test_n_and_u_in_the_run_view(self):
        st = self.state(view="run")
        self.assertEqual(st.run_notes, "run")
        st.key("n")
        self.assertEqual(st.run_notes, "design")
        self.assertEqual(st.notes, "off")                # the other views' notes stay
        st.key("n")
        self.assertEqual(st.run_notes, "off")
        st.key("u")
        self.assertEqual(st.unroll, 8)
        st.key("u")
        self.assertEqual(st.unroll, 0)
        self.assertFalse(st.key("v"))                    # no events mode here

    def test_x_plays_the_run_in_it(self):
        st = self.state(view="run")
        st.key("x")
        for _ in range(6):
            st.key(".")
        text = "\n".join(plain(st.frame(160, 40)))
        self.assertIn("── run · happy — every default", text)
        self.assertIn("▼6", text)
        box = view.sim_focus(st.graph, "run", depth=1, payloads=False, notes="off",
                             triggers=True, spaced=True, width=160, access=False, mods=False,
                             events="nodes", trace=st.sim_trace(), tick=st.player.at)
        self.assertIsNotNone(box)

    def test_cli_once_json_and_unroll(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            view.main([str(CHECKOUT), "--run", "--once", "--no-lint", "--color", "never",
                       "--width", "120", "--sim", "API.charge:fails"])
        self.assertIn("╰───✖╰───✖╰───✖╰───✖", out.getvalue())
        self.assertIn("sim API.charge:fails", out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            view.main([str(CHECKOUT), "--run", "--json"])
        data = json.loads(out.getvalue())
        self.assertEqual(data["scenario"], "happy")
        self.assertEqual([ln["label"] for ln in data["lanes"]][:2], ["(Shopper)", "[API]"])
        self.assertTrue(data["moves"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            view.main([str(ARENA), "--run", "--once", "--no-lint", "--color", "never",
                       "--limit", "spawn=6", "--unroll", "all"])
        self.assertNotIn("more}", out.getvalue())


if __name__ == "__main__":
    unittest.main()
