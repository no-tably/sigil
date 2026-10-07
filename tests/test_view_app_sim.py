"""Sim mode in the app (view.py): SimPlayer's controls (step by frame and by
event, play / pause on a clock passed in, speed, scenario choice, rebuild on
reload), the live view's keys (x, space, , . < > [ ] - + w), the status bar,
the narration rows (path, recent events, the narration line), following the
run's focus in every view, one run shared by the views, and `--sim SCENARIO
--once`.
"""

import contextlib
import io
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import view  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CHECKOUT = ROOT / "site" / "examples" / "01-checkout.sigil"
ORDERS = ROOT / "site" / "examples" / "04-orders.sigil"
EXECUTIONS = ROOT / "tests" / "fixtures" / "executions.sigil"
TICKS = re.compile(r"^sim happy ❚❚ 2 frames/s · t(\d+)/(\d+) · ")   # paused, the default speed


def plain(rows):
    return ["".join(t for t, _ in r) for r in rows]


def parse(path: Path):
    return view.kit.render.parse_document(path.read_text())


class TestSimPlayer(unittest.TestCase):
    def setUp(self):
        self.p = view.SimPlayer(parse(CHECKOUT))

    def test_starts_paused_on_happy_at_the_first_frame(self):
        self.assertEqual(self.p.scenario.name, "happy")
        self.assertEqual((self.p.at, self.p.playing), (0, False))
        self.assertGreater(self.p.last, 0)

    def test_step_clamps_and_pauses(self):
        self.p.playing = True
        self.assertFalse(self.p.step(-1))              # already at the start
        self.assertFalse(self.p.playing)
        self.assertTrue(self.p.step(1))
        self.assertEqual(self.p.at, 1)
        self.p.step(10 ** 6)
        self.assertEqual(self.p.at, self.p.last)

    def test_play_advances_on_the_clock_and_pauses_at_the_end(self):
        self.p.toggle(now=10.0)
        self.assertTrue(self.p.playing)
        self.assertFalse(self.p.advance(10.0))         # not due yet
        self.assertAlmostEqual(self.p.wait(10.0), self.p.interval)
        self.assertTrue(self.p.advance(10.0 + self.p.interval))
        self.assertEqual(self.p.at, 1)
        now = 11.0
        while self.p.advance(now):
            now += 1.0
        self.assertEqual(self.p.at, self.p.last)
        self.assertFalse(self.p.playing)
        self.assertIsNone(self.p.wait(now))

    def test_play_from_the_end_starts_over(self):
        self.p.step(10 ** 6)
        self.assertTrue(self.p.toggle(now=0.0))
        self.assertEqual(self.p.at, 0)

    def test_speed_clamps(self):
        for _ in range(20):
            self.p.faster(1)
        self.assertEqual(self.p.interval, 1.0 / view.SIM_SPEEDS[-1])
        for _ in range(20):
            self.p.faster(-1)
        self.assertEqual(self.p.interval, 1.0 / view.SIM_SPEEDS[0])

    def test_choose_wraps_and_restarts(self):
        names = [sc.name for sc in self.p.scenarios]
        self.p.step(3)
        self.p.choose(1)
        self.assertEqual((self.p.scenario.name, self.p.at), (names[1], 0))
        self.p.choose(-2)
        self.assertEqual(self.p.scenario.name, names[-1])

    def test_play_catches_up_when_drawing_falls_behind(self):
        self.p.toggle(now=0.0)
        late = self.p.due + 2.5 * self.p.interval              # 2 frames overdue
        self.assertTrue(self.p.advance(late))
        self.assertEqual(self.p.at, 3)
        self.assertAlmostEqual(self.p.wait(late), self.p.interval)

    def test_choice_names_the_scenario_among_them_all(self):
        n = len(self.p.scenarios)
        self.assertEqual(self.p.choice(), f"scenario 1/{n} · {self.p.scenario.label}")
        self.p.choose(1)
        self.assertTrue(self.p.choice().startswith(f"scenario 2/{n} · "))

    def test_shown_is_one_trace_per_run_and_options(self):
        """Every frame of a run is drawn from the same Trace object, so the graph
        view's per-trace badge slots (view_graph._trace_slots) are worked out once."""
        opts = view.scene.SceneOptions("nodes", True, False, 1)
        shown = self.p.shown(opts)
        self.p.step(1)
        self.assertIs(self.p.shown(opts), shown)
        self.p.choose(1)
        self.assertIsNot(self.p.shown(opts), shown)            # a new run: a new trace

    def test_named_and_combined_scenarios(self):
        g = parse(CHECKOUT)
        name = view.SimPlayer(g).scenarios[1].name
        self.assertEqual(view.SimPlayer(g, name).scenario.name, name)
        combo = view.SimPlayer(g, f"happy+{name}")
        self.assertEqual(combo.scenario.name, f"happy+{name}")
        self.assertIn(combo.scenario, combo.scenarios)
        with self.assertRaises(view.UnknownScenario) as cm:
            view.SimPlayer(g, "nope")
        self.assertIn("happy", str(cm.exception))      # the known names are listed

    def test_rebuilt_keeps_scenario_position_and_play(self):
        self.p.choose(1)
        self.p.step(5)
        self.p.toggle(now=0.0)
        new = self.p.rebuilt(parse(CHECKOUT))
        self.assertEqual((new.scenario.name, new.at, new.playing, new.speed),
                         (self.p.scenario.name, 5, True, self.p.speed))

    def test_status_and_log(self):
        m = TICKS.match(self.p.status())
        self.assertEqual(int(m[1]), 0)
        self.assertEqual(int(m[2]), self.p.trace.frames[-1].tick)
        self.assertIn("episode 1: (Shopper)", self.p.status())
        self.assertNotIn(" · ok", self.p.status())
        self.p.step(10 ** 6)
        self.assertTrue(self.p.status().endswith(" · ok"))
        self.assertTrue(self.p.log_line().endswith("done: ok"))

    def test_shown_is_named_as_the_view_draws_it(self):
        g = parse(ORDERS)
        p = view.SimPlayer(g)
        for events in view.EVENT_MODES:
            opts = view.scene.SceneOptions(events, True, False, 1)
            shown = p.shown(opts)
            drawn = {w.ident for w in view.scene.build_scene(g, **opts._asdict()).wires}
            used = {t.wire for f in shown.frames for t in f.tokens}
            self.assertTrue(used <= drawn, used - drawn)
            self.assertIs(p.shown(opts), shown)                 # cached
            self.assertEqual(len(shown.frames), len(p.trace.frames))


class _Doc(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "doc.sigil"

    def tearDown(self):
        self.tmp.cleanup()

    def state(self, src: Path = CHECKOUT, **kw):
        self.path.write_text(src.read_text())
        kw.setdefault("view", "graph")                 # sim mode is checked on the graph view
        st = view.ViewState(self.path, do_lint=False, **kw)
        st.reload(force=True)
        return st


class TestSimMode(_Doc):
    def test_x_toggles_sim_mode_and_keeps_the_run(self):
        st = self.state()
        self.assertIsNone(st.sim_trace())
        self.assertTrue(st.key("x"))
        self.assertEqual(st.player.scenario.name, "happy")
        st.key(".")
        st.key("x")
        self.assertIsNone(st.sim_trace())
        st.key("x")
        self.assertEqual(st.player.at, 1)                      # resumed where it was

    def test_sim_keys_only_in_sim_mode(self):
        st = self.state()
        st.frame(100, 20)
        st.key(" ", page=3)                                    # off: space pages
        self.assertIsNone(st.player)
        st.key("x")
        sy = st.sy
        st.key(" ", now=5.0)
        self.assertTrue(st.player.playing)
        self.assertEqual(st.sy, sy)                            # not paged
        st.key(".")
        self.assertFalse(st.player.playing)
        self.assertEqual(st.player.at, 1)
        st.key(",")
        self.assertEqual(st.player.at, 0)
        st.key("]")
        self.assertEqual(st.player.index, 1)
        st.key("[")
        self.assertEqual(st.player.index, 0)
        speed = st.player.speed
        st.key("+")
        st.key("=")
        st.key("-")
        self.assertEqual(st.player.speed, speed + 1)

    def test_tick_plays(self):
        st = self.state(sim="happy")
        self.assertFalse(st.tick(1.0))                         # paused
        self.assertIsNone(st.wait(1.0))
        st.key(" ", now=1.0)
        self.assertIsNotNone(st.wait(1.0))
        self.assertTrue(st.tick(1.0 + st.player.interval))
        self.assertEqual(st.player.at, 1)

    def test_x_off_pauses_so_the_run_resumes_where_it_was(self):
        st = self.state(sim="happy")
        st.key(" ", now=1.0)
        st.key("x")
        self.assertFalse(st.player.playing)
        st.key("x")
        self.assertFalse(st.tick(100.0))                       # no stale catch-up
        self.assertEqual(st.player.at, 0)

    def test_fitted_frames_compose_only_the_fitted_drawing(self):
        st = self.state(sim="happy", layout="wrap")
        calls = []
        compose = st._compose
        st._compose = lambda width: calls.append(width) or compose(width)
        st.key(".")
        st.frame(100, 40)
        self.assertEqual(calls, [100])                         # not the natural one too
        st.key("f")
        st.frame(100, 40)
        self.assertEqual(calls, [100, None])

    def test_auto_decides_once_while_a_run_plays(self):
        st = self.state(sim="happy")                  # auto
        calls = []
        compose = st._compose
        st._compose = lambda width: calls.append(width) or compose(width)
        st.frame(30, 40)
        first = list(calls)
        self.assertIn(None, first)                    # the natural drawing, to decide
        for _ in range(3):
            st.key(".")
            st.frame(30, 40)
        self.assertEqual(calls[len(first):].count(None), 0 if st.placing == "wrap" else 3)
        st.key("]")                                   # another run: decided afresh
        st.frame(30, 40)
        self.assertIn(None, calls[len(first) + 3:])

    def test_start_on_a_scenario(self):
        st = self.state(ORDERS, sim="Payments:fails")
        self.assertTrue(st.sim_on)
        self.assertEqual(st.player.scenario.name, "Payments:fails")
        self.assertIsNone(st.sim_error)

    def test_unknown_start_scenario_plays_happy_and_says_so(self):
        st = self.state(sim="nope")
        self.assertEqual(st.player.scenario.name, "happy")
        self.assertIn("unknown scenario nope", st.sim_error)

    def test_reload_keeps_the_scenario(self):
        st = self.state(ORDERS, sim="Payments:fails")
        st.key(".")
        self.path.write_text(ORDERS.read_text() + "\n")
        st.reload(force=True)
        self.assertEqual((st.player.scenario.name, st.player.at), ("Payments:fails", 1))

    def test_both_views_play_the_same_run(self):
        st = self.state(sim="happy")
        st.key(".")
        st.key(".")
        graph_run = st.sim_trace()
        st.key("2")
        tree_run = st.sim_trace()
        self.assertEqual(st.player.at, 2)
        self.assertEqual(graph_run.scenario, tree_run.scenario)
        self.assertEqual([f.tick for f in graph_run.frames], [f.tick for f in tree_run.frames])
        self.assertEqual(tree_run.scene.options.events, st.events_mode)

    def test_keys_rows_and_legend(self):
        st = self.state()
        keys = "".join(t for t, _ in view.keys_legend(st))
        self.assertIn("x sim", keys)
        text = "\n".join(plain(st.frame(160, 40)))
        self.assertNotIn("play/pause", text)
        st.key("x")
        text = "\n".join(plain(st.frame(160, 40)))
        self.assertIn("play/pause", text)
        self.assertIn("[ ] scenario 1/2 · every default", text)
        self.assertIn("● out", text)
        self.assertNotIn("▸ active", text)
        self.assertIn("✕ failed", text)
        for tree in (False, True):                      # token and badge share one entry
            row = "".join(t for t, _ in view.sim_legend(tree=tree))
            self.assertEqual(row.count("✕ failed"), 1, row)
        self.assertIn("⊘ cancelled", text)
        self.assertIn("◉ State its owner's", text)
        st.key("2")                                     # the tree: its own row of marks
        text = "\n".join(plain(st.frame(160, 40)))
        self.assertIn("▸ active", text)


class TestSimLegend(unittest.TestCase):
    def test_one_row_for_both_views_the_tree_adds_only_active(self):
        def text(row):
            return "".join(t for t, _ in row)
        graph, tree = text(view.sim_legend()), text(view.sim_legend(tree=True))
        self.assertIn("⊘ cancelled", graph)
        self.assertNotIn("● cancelled", graph)
        self.assertNotIn("▸ active", graph)
        self.assertEqual(tree.replace("▸ active  ", ""), graph)


class TestSimFrames(_Doc):
    def test_status_bar_and_log_row(self):
        for tree in (False, True):
            with self.subTest(tree=tree):
                st = self.state(sim="happy", tree=tree)
                st.key(".")
                frame = plain(st.frame(200, 40))
                status = frame[0][frame[0].index("sim happy"):]
                self.assertEqual(int(TICKS.match(status)[1]), st.player.trace.frames[1].tick)
                self.assertIn("episode 1: (Shopper)", frame[0])
                # the narration line last: the latest beat, after `›`
                self.assertEqual(frame[-1], ("› " + st.player.narration())[:200])

    def test_frames_stay_exactly_cols_by_rows(self):
        for tree in (False, True):
            st = self.state(ORDERS, sim="Payments:fails", tree=tree)
            for _ in range(st.player.last + 1):
                for cols, rows in ((60, 20), (120, 45)):
                    frame = st.frame(cols, rows)
                    self.assertEqual(len(frame), rows)
                    self.assertTrue(all(view.row_len(r) <= cols for r in frame))
                st.key(".")


class TestOnce(unittest.TestCase):
    def run_once(self, path: Path, **kw) -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            status = view.once(path, 1, False, True, width=100, **kw)
        self.assertEqual(status, 0)
        return buf.getvalue()

    def test_final_frame_outcome_and_log(self):
        for tree in (False, True):
            with self.subTest(tree=tree):
                out = self.run_once(ORDERS, tree=tree, sim="Payments:fails")
                self.assertIn("◉ current state", out)
                # one row of sim marks for both views (view.sim_legend); only
                # the tree's adds an active row's ▸
                self.assertIn("○ return / fallback", out)
                self.assertEqual("▸ active" in out, tree)
                self.assertIn("lint: OK", out)
                tail = out[out.index("sim Payments:fails"):].splitlines()
                self.assertIn(": failed · ", tail[0])
                # the run's path at its final frame, as the live view's row
                self.assertTrue(tail[1].startswith("path   ① [Payments]"), tail[1])
                self.assertTrue(tail[2].endswith(view.simulator.CONVENTIONS))
                self.assertIn("path   the hops taken so far:  ①② its branches", out)
                self.assertIn("episode 2 begins at [Payments]", "\n".join(tail))
                self.assertTrue(tail[-1].endswith("the run ends: failed"))

    def test_without_sim_unchanged(self):
        out = self.run_once(CHECKOUT)
        self.assertNotIn("◉ current state", out)
        self.assertNotIn("sim ", out)

    def test_unknown_scenario_exits_2_listing_the_known(self):
        res = subprocess.run([sys.executable, str(ROOT / "view.py"), str(CHECKOUT), "--once",
                              "--sim", "nope"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)
        self.assertIn("--sim: unknown scenario nope", res.stderr)
        self.assertIn("happy", res.stderr)


class TestReadablePlayback(unittest.TestCase):
    def setUp(self):
        self.p = view.SimPlayer(parse(CHECKOUT), "API.charge:fails")

    def test_speeds_start_slow_and_reach_a_quarter(self):
        self.assertEqual(view.SIM_SPEEDS[:2], (0.25, 0.5))
        self.assertEqual(self.p.fps, 2)
        self.assertEqual([view.speed_text(f) for f in (0.25, 0.5, 1, 2, 32)],
                         ["¼ frame/s", "½ frame/s", "1 frame/s", "2 frames/s", "32 frames/s"])
        self.p.faster(-1)
        self.assertIn("❚❚ 1 frame/s", self.p.status())
        for _ in range(3):
            self.p.faster(-1)
        self.assertEqual(self.p.interval, 4.0)

    def test_step_by_event_stops_on_beats(self):
        frames = [b.frame for b in self.p.beats]
        self.assertTrue(self.p.step_event(1))
        self.assertEqual(self.p.at, frames[1])
        self.p.step(1)                                  # between two beats
        self.assertTrue(self.p.step_event(-1))
        self.assertEqual(self.p.at, frames[1])
        self.p.playing = True
        self.p.step_event(10)
        self.assertFalse(self.p.playing)
        for _ in range(len(frames) + 2):
            self.p.step_event(1)
        self.assertEqual(self.p.at, self.p.last)
        self.assertFalse(self.p.step_event(1))
        for _ in range(len(frames) + 2):
            self.p.step_event(-1)
        self.assertEqual(self.p.at, 0)

    def test_narration_holds_while_a_token_travels(self):
        self.p.step(6)                                  # attempt 1 is on its way
        self.assertEqual(self.p.narration(), f"t{5:03} [API] calls [Payments] with "
                                             "charge(total) — attempt 1 of 4")
        self.p.step(-6)
        self.assertTrue(self.p.narration().endswith("(Shopper) calls [API] with {Cart}"))

    def test_path_writes_the_hops_so_far_by_branch(self):
        self.p.step(12)                                 # attempt 2 on its way
        self.assertEqual(self.p.path(), "① (Shopper) -> [API] ▸-> [Payments] ×2")
        self.assertEqual(self.p.path(mono=False), "① (Shopper) -> [API] -> [Payments] ×2")
        self.p.step(-3)                                 # attempt 1 failing on arrival
        self.assertEqual(self.p.path(), "① (Shopper) -> [API] ▸-> [Payments] ✖")
        self.p.step(10 ** 6)
        self.assertEqual(self.p.path(),
                         "① (Shopper) -> [API] -> [Payments] ✖×4   ② [API] !> <PaymentFailed>")

    def test_path_is_per_episode(self):
        p = view.SimPlayer(parse(ORDERS))
        p.step(10 ** 6)
        self.assertTrue(p.path().startswith("① [Payments] ~> <Paid>"), p.path())

    def test_sim_path_branches(self):
        hop = view.simulator.Hop
        hops = [hop(0, "a", "->", "b"), hop(1, "b", "->", "c", 2, "failed"),
                hop(3, "b", "->", "c", 4, "failed"), hop(5, "x", "~>", "y", 6, "cancelled"),
                hop(7, "e", "trigger", "s", 9)]
        self.assertEqual(view.path_text(view.sim_path(hops, str)),
                         "① a -> b -> c ✖×2   ② x ~> y ⊘   ③ e ⇢ s")
        # at frame 8: the trigger's token is on its wire, and only outcomes reached show
        self.assertEqual(view.path_text(view.sim_path(hops, str, 8)),
                         "① a -> b -> c ✖×2   ② x ~> y ⊘   ③ e ▸⇢ s")
        self.assertEqual(view.path_text(view.sim_path(hops[:3], str, 3)),
                         "① a -> b ▸-> c ×2")
        self.assertEqual(view.path_text(view.sim_path([], str)), "")

    def test_branch_numbers(self):
        self.assertEqual([view.branch_number(n) for n in (1, 2, 20, 21)],
                         ["①", "②", "⑳", "(21)"])

    def test_path_rows_bold_the_hop_now(self):
        self.p.step(12)
        rows = view.path_rows(self.p.path_branches(), 120)
        now = [t for t, st in rows[0] if st and st[2]]
        self.assertEqual(now, ["-> [Payments] ×2"])
        self.assertEqual(plain(view.path_rows(self.p.path_branches(), 120, mono=True))[0],
                         "path   ① (Shopper) -> [API] ▸-> [Payments] ×2")

    def test_path_rows_wrap_then_fold_the_oldest(self):
        hop = view.simulator.Hop
        hops = [hop(k, f"n{k}", "->", f"m{k}") for k in range(6)]
        branches = view.sim_path(hops, str)
        rows = plain(view.path_rows(branches, 200))
        self.assertEqual(rows, ["path   ① n0 -> m0   ② n1 -> m1   ③ n2 -> m2   ④ n3 -> m3   "
                                "⑤ n4 -> m4   ⑥ n5 -> m5"])
        rows = plain(view.path_rows(branches, 50))      # two rows, between branches
        self.assertEqual(rows, ["path   ① n0 -> m0   ② n1 -> m1   ③ n2 -> m2",
                                "       ④ n3 -> m3   ⑤ n4 -> m4   ⑥ n5 -> m5"])
        rows = plain(view.path_rows(branches, 30))      # longer: the oldest fold
        self.assertEqual(rows, ["path   ①–③ …   ④ n3 -> m3",
                                "       ⑤ n4 -> m4   ⑥ n5 -> m5"])
        self.assertTrue(all(len(r) <= 30 for r in rows))
        rows = plain(view.path_rows(branches[:1], 30, hold=True))
        self.assertEqual(rows, ["path   ① n0 -> m0", "  "])

    def test_path_rows_fold_a_long_branch(self):
        hop = view.simulator.Hop
        hops = [hop(k, f"n{k}", "->", f"n{k + 1}") for k in range(12)]
        rows = plain(view.path_rows(view.sim_path(hops, str), 40))
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0].startswith("path   ① …"), rows)
        self.assertTrue(rows[1].endswith("-> n12"), rows)
        self.assertTrue(all(len(r) <= 40 for r in rows))

    def test_story_rows(self):
        rows = [plain([r])[0] for r in view.sim_story_rows(self.p, 120)]
        self.assertEqual(len(rows), view.PATH_ROWS + 1 + view.SIM_LOG_ROWS)
        self.assertTrue(rows[0].startswith("path   ① (Shopper) -> [API]"))
        self.assertEqual(rows[1], "  ")                 # the path's second row, held
        self.assertEqual(rows[2:-1], ["  "] * view.SIM_LOG_ROWS)    # nothing before yet
        self.assertEqual(rows[-1], "› " + self.p.narration())
        self.p.step(10 ** 6)
        rows = [plain([r])[0] for r in view.sim_story_rows(self.p, 40)]
        self.assertTrue(rows[0].startswith("path   ① …   ② [API]"), rows[0])
        self.assertLessEqual(len(rows[0]), 40)
        told = [view.beat_line(b) for b in self.p.told()]
        self.assertEqual([r[2:] for r in rows[2:-1]], told[-view.SIM_LOG_ROWS - 1:-1])

    def test_keys_row_shows_speed_and_follow(self):
        row = "".join(t for t, _ in view.sim_keys_legend(self.p, True))
        for entry in ("< > event", ", . frame", "- + speed 2 frames/s", "w follow:on"):
            self.assertIn(entry, row)
        self.assertIn("w follow:off", "".join(t for t, _ in view.sim_keys_legend(self.p, False)))


class TestFollow(_Doc):
    def test_follow_origin_moves_the_least(self):
        self.assertEqual(view.follow_origin(0, 5, 3, 20), 0)        # already in view
        self.assertEqual(view.follow_origin(0, 30, 3, 20), 15)      # below: just enough
        self.assertEqual(view.follow_origin(40, 30, 3, 20), 28)     # above: margin kept
        self.assertEqual(view.follow_origin(0, 30, 40, 20), 30)     # bigger than the view

    def test_focus_in_every_view(self):
        g = parse(CHECKOUT)
        p = view.SimPlayer(g, "API.charge:fails")
        p.step(6)                                       # a token on [API] -> [Payments]
        for v in view.VIEWS:
            with self.subTest(view=v):
                events = view.DEFAULT_EVENTS[v]
                trace = p.shown(view.scene.SceneOptions(events, True, False, 1))
                kw = dict(depth=1, payloads=False, notes="off", triggers=True, spaced=True,
                          width=None, access=False, mods=False, events=events)
                rows, _w = view.compose_view(g, v, trace=trace, tick=p.at, **kw)
                x, y, w, h = view.sim_focus(g, v, trace=trace, tick=p.at, **kw)
                cells = "".join(plain(rows)[y + k][x:x + w] for k in range(h))
                self.assertIn("●", cells)

    def test_the_view_follows_the_run_down_a_tall_drawing(self):
        st = self.state(EXECUTIONS, sim="happy")
        st.frame(100, 30)
        top = st.sy
        for _ in range(30):
            st.key(">")
        st.frame(100, 30)
        self.assertGreater(st.sy, top)
        box = view.sim_focus(st.graph, st.view, depth=st.depth, payloads=st.payloads,
                             notes=st.notes, triggers=True, spaced=True, width=100,
                             access=False, mods=False, events=st.events_mode,
                             trace=st.sim_trace(), tick=st.player.at)
        self.assertTrue(st.sy <= box[1] < st.sy + st._vh)

    def test_w_turns_following_off(self):
        st = self.state(EXECUTIONS, sim="happy")
        st.frame(100, 30)
        top = st.sy
        st.key("w")
        self.assertFalse(st.follow)
        for _ in range(30):
            st.key(">")
        st.frame(100, 30)
        self.assertEqual(st.sy, top)
        self.assertIn("w follow:off", "\n".join(plain(st.frame(160, 40))))

    def test_panning_holds_between_frames(self):
        st = self.state(EXECUTIONS, sim="happy")
        for _ in range(30):
            st.key(">")
        st.frame(100, 30)
        st.key("up")
        st.key("up")
        held = st.sy
        st.frame(100, 30)                               # the same frame: no follow
        self.assertEqual(st.sy, held)


if __name__ == "__main__":
    unittest.main()
