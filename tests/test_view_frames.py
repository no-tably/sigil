"""A run drawn frame after frame with a kit.FrameMemo is the run drawn without one.

A view lays a drawing out once per plan (its options, width, the document, the
run and the checks overlay) and then repaints only what each frame changes
(view_graph and view_tree: the rows of the boxes, wires and tokens that look
different, kit.Retained; view_flow: the bands that look different, and in a
part drawn whole the cells of the wires and labels that look different, the
wrap ladder's step and cuts chosen once).

Covers:
  1. every few frames of runs of the site examples and the executions fixture,
     stepped forward, then back, then jumped about, in the graph, tree and flow
     views — natural and fitted narrow, with and without payloads, modifiers,
     notes, permissions and every depth: compose_view and sim_focus give the
     same rows, width and focus with a memo as without (the probe drawing has
     a plan of its own); the checks overlay too;
  2. ViewState: a run played with its memo draws the frames a ViewState
     without one draws (follow, wrap and pan);
  3. a 500-flow chain (and, in the flow view, a tall design that fits): a
     frame with the memo is the frame without it, for a fraction of the work
     — natural (as --layout pan draws) and fitted. Work is counted, not
     timed: the function calls (Python and built-in) the frames make, the
     same on every run however busy the machine is. Frames spread over the
     run: the chain in the flow view ≥ 4× fewer calls (counted 5.7-10×),
     tree ≥ 3× (3.8×), graph ≥ 2× (2.5×: each frame still works out the
     run's look, sim_look, and every box's; CPU time drops more, 4.5-7×);
     the tall design's frames as played ≥ 3× (4×), spread ≥ 2× (2.5×: a
     third of its wires and labels look different between frames that far
     apart, and each of those is painted again);
  4. kit.Canvas.keep_rows / splice / patch / overlay: a kept canvas keeps its
     rows, rows spliced or cells patched in from another drawing come out as
     that drawing draws them, a frame's overlay goes when cleared;
  5. kit.Retained: only the rows of an element whose look or rows changed are
     painted again; kit.FrameMemo: plans by key and by the identity of what
     they hold, the newest KEEP of them, all afresh after a theme is applied.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import random
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


view = _load("sigil_view_frames", ROOT / "view.py")
kit, scene, sim = view.kit, view.scene, view.simulator

EXAMPLES = sorted((ROOT / "site" / "examples").glob("*.sigil"))
EXECUTIONS = ROOT / "tests" / "fixtures" / "executions.sigil"
VIEWS = ("graph", "tree", "flow")
OPTIONS = (
    dict(),
    dict(payloads=True, mods=True, notes="markers"),
    dict(access=True, depth=kit.ALL_DEPTH, notes="callouts", events="land"),
)


def chain(n: int) -> str:
    return "".join(f"[N{i}] -> [N{i + 1}]\n" for i in range(n))


def rows_of_chains(n: int) -> str:
    """n chains of three, one under the other: a tall drawing that fits 120."""
    return "".join(f"[A{i}] -> [B{i}]\n[B{i}] -> [C{i}]\n" for i in range(n))


def kwargs(v: str, width, opts: dict) -> dict:
    return dict(depth=opts.get("depth", 1), payloads=opts.get("payloads", False),
                notes=opts.get("notes", "off"), triggers=True, spaced=True, width=width,
                access=opts.get("access", False), mods=opts.get("mods", False),
                events=opts.get("events", view.DEFAULT_EVENTS[v]))


def shown(g, name: str, kw: dict):
    """(player, its trace named as a view drawn with kw names things)."""
    player = view.SimPlayer(g, name)
    return player, player.shown(scene.SceneOptions(kw["events"], kw["triggers"], kw["access"],
                                                   kw["depth"]))


def ticks(last: int, stride: int, seed: int) -> list:
    """Forward every `stride` frames to the last, back a few, then jumps."""
    forward = list(range(0, last + 1, stride)) + [last]
    jumps = random.Random(seed).sample(range(last + 1), min(4, last + 1))
    return forward + forward[::-1][1:4] + jumps


class TestSameFrames(unittest.TestCase):
    """1. compose_view / sim_focus with a memo == without, frame by frame."""

    def assert_run(self, g, v: str, width, opts: dict, name: str, stride: int, checks=None):
        kw = kwargs(v, width, opts)
        player, trace = shown(g, name, kw)
        memo = kit.FrameMemo()
        for t in ticks(player.last, stride, len(opts)):
            plain = view.compose_view(g, v, trace=trace, tick=t, checks=checks, **kw)
            kept = view.compose_view(g, v, trace=trace, tick=t, checks=checks, memo=memo, **kw)
            self.assertEqual(kept, plain, (v, width, opts, name, t))
            self.assertEqual(view.sim_focus(g, v, trace=trace, tick=t, memo=memo, **kw),
                             view.sim_focus(g, v, trace=trace, tick=t, **kw),
                             (v, width, opts, name, t))

    def scenarios(self, g) -> list:
        """happy, and the first scenario after it (a failure path, mostly)."""
        names = [s.name for s in sim.scenarios(scene.build_scene(g))]
        return ["happy"] + [n for n in names if n != "happy"][:1]

    def test_examples_every_view(self):
        """Each input in each view, the option sets, widths and runs taken in
        turn (every combination is a few minutes: tools/ is not, this is)."""
        turn = 0
        for path in EXAMPLES + [EXECUTIONS]:
            g = kit.render.parse_document(path.read_text())
            names = self.scenarios(g)
            for v in VIEWS:
                opts, width = OPTIONS[turn % len(OPTIONS)], (None, 60)[turn % 2]
                name = names[turn % len(names)]
                turn += 1
                with self.subTest(path=path.name, view=v, opts=opts, width=width, run=name):
                    self.assert_run(g, v, width, opts, name, stride=5)

    def test_narrow_bands_and_folds(self):
        """The narrowest fits: flow bands with plugs, tree lanes folded, graph
        layers wrapped and hints under the drawing."""
        g = kit.render.parse_document((EXAMPLES[2]).read_text())
        for v in VIEWS:
            with self.subTest(view=v):
                self.assert_run(g, v, 30, dict(payloads=True), "happy", stride=6)

    def test_checks_overlay(self):
        g = kit.render.parse_document(EXAMPLES[1].read_text())
        report = view.run_checks(EXAMPLES[1].read_text())
        overlay = view.ChecksOverlay(g, report, view.checks_summary(report))
        for v in VIEWS:
            kw = kwargs(v, 80, {})
            opts = scene.SceneOptions(kw["events"], True, False, 1)
            with self.subTest(view=v):
                self.assert_run(g, v, 80, {}, "happy", stride=3, checks=overlay.marks(opts))

    def test_flow_letters_step(self):
        """Frames that fit with the chips lettered: each frame hands out the
        letters the panel lists (a part drawn whole is not laid out again)."""
        for path in EXAMPLES[:3]:
            g = kit.render.parse_document(path.read_text())
            with self.subTest(path=path.name):
                self.assert_run(g, "flow", 100, dict(payloads=True, mods=True), "happy",
                                stride=3)

    def test_chain_long_run(self):
        g = kit.render.parse_document(chain(40))
        for v in VIEWS:
            with self.subTest(view=v):
                self.assert_run(g, v, 50, {}, "happy", stride=11)


class TestViewState(unittest.TestCase):
    """2. a live view playing a run draws what it draws without its memo."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "doc.sigil"
        self.path.write_text(EXAMPLES[2].read_text())

    def tearDown(self):
        self.tmp.cleanup()

    def test_play_with_and_without(self):
        for v in VIEWS:
            for layout in ("wrap", "pan"):
                with self.subTest(view=v, layout=layout):
                    kept = view.ViewState(self.path, view=v, sim="happy", do_lint=False,
                                          layout=layout)
                    plain = view.ViewState(self.path, view=v, sim="happy", do_lint=False,
                                           layout=layout)
                    for st in (kept, plain):
                        st.reload()
                    plain.memo = None
                    for _k in range(min(kept.player.last, 25)):
                        self.assertEqual(kept.frame(70, 30), plain.frame(70, 30))
                        for st in (kept, plain):
                            st.key(".")


def calls_made(fn):
    """(the function calls, Python and built-in, fn() makes; what it returns):
    a count of its work that doesn't change with the machine's load."""
    made = 0

    def count(_frame, event, _arg):
        nonlocal made
        if event in ("call", "c_call"):
            made += 1

    sys.setprofile(count)
    try:
        out = fn()
    finally:
        sys.setprofile(None)
    return made, out


class TestLongChain(unittest.TestCase):
    """3. the 500-flow chain: the same frames, a fraction of the work."""

    def fewer_calls(self, g, v: str, width, played: bool = False) -> float:
        """How many times fewer calls frames take with the memo than without
        (the same frames): four spread over the run, or (`played`) six in a
        row from its middle, as it plays."""
        kw = kwargs(v, width, {})
        player, trace = shown(g, "happy", kw)
        memo = kit.FrameMemo()
        view.compose_view(g, v, trace=trace, tick=0, memo=memo, **kw)
        frames = ([player.last // 2 + k for k in range(6)] if played
                  else [player.last * k // 4 for k in range(1, 5)])

        def draw(m):
            return [view.compose_view(g, v, trace=trace, tick=t, memo=m, **kw) for t in frames]

        slow, plain = calls_made(lambda: draw(None))
        fast, kept = calls_made(lambda: draw(memo))
        self.assertEqual(kept, plain, (v, width))
        return slow / max(fast, 1)

    def test_fewer_calls_and_same(self):
        g = kit.render.parse_document(chain(500))
        least = {"flow": 4, "tree": 3, "graph": 2}
        for v in VIEWS:
            for width in (None, 120):
                with self.subTest(view=v, width=width):
                    self.assertGreater(self.fewer_calls(g, v, width), least[v])

    def test_flow_fits(self):
        """A drawing that fits the width is one part drawn whole, kept too."""
        g = kit.render.parse_document(rows_of_chains(120))
        for width in (None, 120):
            with self.subTest(width=width):
                self.assertGreater(self.fewer_calls(g, "flow", width, played=True), 3)
                self.assertGreater(self.fewer_calls(g, "flow", width), 2)

    def test_calls_made_counts_work(self):
        """The measure itself: twice the work is twice the calls, every time."""
        def step(k):
            return abs(k)

        def work(n):
            return [step(k) for k in range(n)]

        once, out = calls_made(lambda: work(100))
        twice, _ = calls_made(lambda: work(200))
        self.assertEqual(out, list(range(100)))
        self.assertEqual(calls_made(lambda: work(100))[0], once)
        self.assertGreaterEqual(once, 200)                    # step and abs, each k
        self.assertGreater(twice, once * 1.9)


class TestRetained(unittest.TestCase):
    """4, 5. the kit's kept canvas, Retained and FrameMemo."""

    @staticmethod
    def drawing(styles: dict):
        """Three boxes on rows 0, 2 and 4 and a line down column 10."""
        cv = kit.Canvas()
        for y, name in ((0, "a"), (2, "b"), (4, "c")):
            cv.put(0, y, f"[{name}]", styles.get(name))
        cv.path([(10, 0), (10, 4)], "->", styles.get("line"))
        return cv

    def test_kept_rows_and_splice(self):
        cv = self.drawing({}).keep_rows()
        self.assertEqual(list(cv.rows()), list(self.drawing({}).rows()))
        lit = {"b": (kit.Colour("#ff0000", "edges-fail"), None, True)}
        cv.splice(self.drawing(lit), {2})
        self.assertEqual(list(cv.rows()), list(self.drawing(lit).rows()))
        rows = list(cv.rows())
        rows[0].append(("mutated", None))          # rows handed out are copies
        self.assertEqual(list(cv.rows()), list(self.drawing(lit).rows()))

    def test_patch_and_overlay(self):
        def wide(styles):                         # one row wider than a span
            cv = kit.Canvas()
            for k in range(60):
                cv.put(k * 6, 0, f"[n{k:02d}]", styles.get(k))
                cv.path([(k * 6 + 5, 1), (k * 6 + 5, 2)], "->", styles.get(k))
            return cv

        cv = wide({}).keep_rows()
        lit = {7: (kit.Colour("#ff0000", "edges-fail"), None, True), 59: (None, None, True)}
        self.assertEqual(list(cv.rows()), list(wide({}).rows()))
        cells = {(x, y) for k in lit for x in range(k * 6, k * 6 + 6) for y in range(3)}
        cv.patch(wide(lit), cells)
        self.assertEqual(list(cv.rows()), list(wide(lit).rows()))
        cv.overlay(3, 0, "●", (None, None, True))
        cv.overlay(300, 1, "●●", None)
        marked = wide(lit)
        marked.put(3, 0, "●", (None, None, True))
        marked.put(300, 1, "●●", None)
        self.assertEqual(list(cv.rows()), list(marked.rows()))
        cv.clear_overlay()
        self.assertEqual(list(cv.rows()), list(wide(lit).rows()))
        cv.patch(wide({}), cells)
        self.assertEqual(list(cv.rows()), list(wide({}).rows()))

    def test_repaints_changed_rows_only(self):
        painted = []

        def paint(styles):
            def draw(rows):
                painted.append(set(rows))
                return self.drawing(styles)
            return draw

        def now(styles):
            return {name: ((y,), styles.get(name)) for y, name in ((0, "a"), (2, "b"), (4, "c"))}

        kept = kit.Retained(self.drawing({}), now({}))
        lit = {"c": (None, None, True)}
        cv = kept.repaint(now(lit), paint(lit))
        self.assertEqual(painted, [{4}])
        self.assertEqual(list(cv.rows()), list(self.drawing(lit).rows()))
        kept.repaint(now(lit), paint(lit))
        self.assertEqual(painted, [{4}])            # nothing changed: nothing painted
        moved = now(lit)
        moved["c"] = ((3,), lit["c"])
        kept.repaint(moved, paint(lit))
        self.assertEqual(painted[-1], {3, 4})        # moved: its old rows and its new

    def test_memo_plans(self):
        memo = kit.FrameMemo()
        a, b = object(), object()
        plan = memo.plan(("graph", 1), (a,))
        plan.held["x"] = 1
        self.assertIs(memo.plan(("graph", 1), (a,)), plan)
        self.assertIsNot(memo.plan(("graph", 1), (b,)), plan)   # another document
        self.assertIsNot(memo.plan(("graph", 2), (a,)), plan)   # other options
        for k in range(kit.FrameMemo.KEEP):
            memo.plan(("other", k), (a,))
        self.assertIsNot(memo.plan(("graph", 1), (a,)), plan)   # the oldest went
        plan = memo.plan(("graph", 1), (a,))
        kit.use_theme("sigil")                      # a theme applied: drawn afresh
        self.assertIsNot(memo.plan(("graph", 1), (a,)), plan)
        self.assertEqual(kit.held(None, "x", lambda: 2), 2)
        self.assertIsNone(kit.slot(None))
        p = kit.Plan()
        first = p.slot()
        p.begin()
        self.assertIs(p.slot(), first)


if __name__ == "__main__":
    unittest.main()
