"""Tests for view_graph.py: a simulation frame drawn over the graph (sim.md §7).

Covers:
  1. wire_state and sim_look: a key takes its busiest wire's state; strokes in
     scene.wire_style (active bold, untouched muted, a failure route edges-fail);
  2. tokens: ● out on the wire's cells (the head cell at 1, the tail at 0), ○ a
     return in the produces role (fallback muted), a token on a chipped edge travels through its chip, a self-call's
     token on its stub's source mark (or its box's self mark);
  3. boxes: never-touched boxes muted, a failed one `✕` in edges-fail, waiting
     `…`, instances `×n`, recursion `↻k`;
  4. machines: `◉` before a drawn machine's current state, `◉ State` after its
     owner at a depth that hides it;
  5. badge_slots: the layout holds still from frame to frame; it visits only
     the nodes a frame names and is worked out once per trace;
  6. sim_focus: the cells of the frame's tokens and active boxes;
  7. no frame: compose draws exactly as before (the goldens cover the rest);
  8. a wrapped fan-out's shared trunk takes the look of its busiest member
     (one long-edge member failed: its whole path from the hub reads failed),
     and a FrameMemo repaint draws the trunk as a fresh drawing does.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


view = _load("sigil_view", ROOT / "view.py")
vgraph, kit = view.vgraph, view.kit
scene = vgraph.scene
sim = vgraph._sibling("sigil_sim", "sim.py")

EXAMPLES = ROOT / "site" / "examples"
CHECKOUT = (EXAMPLES / "01-checkout.sigil").read_text()
ARENA = (EXAMPLES / "03-arena.sigil").read_text()
ORDERS = (EXAMPLES / "04-orders.sigil").read_text()
EXECUTIONS = (ROOT / "tests" / "fixtures" / "executions.sigil").read_text()

PAY = ("API_service", "Payments_service", "->")
SHOP = ("Shopper_actor", "API_service", "->")
ROUTE = ("API_service", "PaymentFailed_event", "!>")


class Run:
    """One scenario of a document, projected onto the Scene a graph drawn with
    these options builds, and its frames drawn."""

    def __init__(self, text: str, name: str = "happy", *, depth: int = kit.ALL_DEPTH,
                 events: str = "nodes", payloads: bool = False):
        self.g = kit.render.parse_document(text)
        canon = sim.canonical(self.g)
        self.scn = scene.build_scene(self.g, events=events, triggers=True, depth=depth)
        self.trace = sim.project(sim.simulate(canon, sim.scenario(canon, name)), self.scn)
        self.slots = vgraph.badge_slots(self.trace)
        self.depth, self.events, self.payloads = depth, events, payloads

    def frame(self, i: int):
        return self.trace.frames[i]

    def first(self, pred) -> int:
        """The index of the first frame pred holds for."""
        return next(i for i, f in enumerate(self.trace.frames) if pred(f))

    def args(self) -> tuple:
        """compose's (and sim_focus's) positional arguments for this run."""
        return (self.g, self.depth, self.payloads, "off", True, None, False, False, self.events)

    def rows(self, i: int):
        rows, _w = vgraph.compose(*self.args(), trace=self.trace, tick=i)
        return rows

    def text(self, i: int) -> list:
        return [kit.ansi(r, False) for r in self.rows(i)]

    def look(self, i: int):
        return vgraph.sim_look(self.scn, self.frame(i), self.slots)


def _cells(rows, ch: str) -> list:
    """[(x, y, style)] of every cell drawing ch."""
    out = []
    for y, row in enumerate(rows):
        x = 0
        for text, style in row:
            for k, c in enumerate(text):
                if c == ch:
                    out.append((x + k, y, style))
            x += len(text)
    return out


def _cell_style(rows, needle: str):
    """The style of the first run containing needle."""
    return next(style for row in rows for text, style in row if needle in text)


class WireStates(unittest.TestCase):
    def test_state_precedence(self):
        f = sim.Frame(0, 1, None, (), frozenset({("a",), ("b",)}), frozenset(),
                      frozenset({("b",), ("c",)}), frozenset({("a",)}), {}, {}, {},
                      frozenset(), {}, {}, frozenset(), frozenset(), (), False)
        self.assertEqual([vgraph.wire_state(f, (k,)) for k in "abcd"],
                         ["failed", "active", "trail", "inactive"])

    def test_styles_follow_the_frame(self):
        run = Run(CHECKOUT)
        i = run.first(lambda f: any(t.wire[:3] == SHOP for t in f.tokens))
        look = run.look(i)
        self.assertEqual(look.states[SHOP], "active")
        self.assertEqual(look.states[PAY], "inactive")
        fg, _bg, bold = look.styles[SHOP]
        self.assertTrue(bold)
        self.assertEqual(look.styles[PAY], scene.wire_style(
            next(w for w in run.scn.wires if w.key == PAY), "inactive"))

    def test_a_failure_route_turns_fail(self):
        run = Run(CHECKOUT, "API.charge:fails")
        look = run.look(len(run.trace.frames) - 1)
        self.assertEqual(look.states[ROUTE], "failed")
        self.assertEqual(look.styles[ROUTE][0], scene.colour_of("edges-fail"))


class Tokens(unittest.TestCase):
    def test_out_token_travels_its_edge(self):
        run = Run(CHECKOUT)
        ticks = [i for i, f in enumerate(run.trace.frames)
                 if any(t.wire[:3] == SHOP and t.dir == "out" for t in f.tokens)]
        ys = []
        for i in ticks:
            rows = run.rows(i)
            [(x, y, style)] = _cells(rows, "●")
            ys.append(y)
            self.assertTrue(style[2], "a moving token is bold")
        self.assertEqual(ys, sorted(ys), "the token moves down toward [API]")
        self.assertGreater(ys[-1], ys[0])
        # at 1.0 it sits on the head cell: no ▼ left between (Shopper) and [API]
        last = run.text(ticks[-1])
        top = next(y for y, ln in enumerate(last) if "(Shopper)" in ln)
        api = next(y for y, ln in enumerate(last) if "[API]" in ln)
        if run.frame(ticks[-1]).tokens[0].at == 1.0:
            self.assertNotIn("▼", "".join(last[top + 1:api - 1]))

    def test_return_token(self):
        run = Run(CHECKOUT)
        i = run.first(lambda f: any(t.dir == "back" for t in f.tokens))
        [(_x, _y, style)] = _cells(run.rows(i), "○")
        self.assertEqual(style, (kit.edge_style("=>")[0], None, True),
                         "a return is in the produces role, as in the tree")

    def test_token_styles_follow_the_shared_rules(self):
        run = Run(CHECKOUT)
        w = next(w for w in run.scn.wires if w.key == SHOP)
        produces = kit.edge_style("=>")[0]
        self.assertNotEqual(scene.colour_of(w.colour), produces, "the test needs a coloured wire")

        def drawn(**kw):
            t = vgraph._token(sim.Token(w.ident, 0.5, kw.pop("dir", "out"), 0, **kw), w)
            return t.mark, t.style

        self.assertEqual(drawn(), ("●", scene.wire_style(w, "active")))
        self.assertEqual(drawn(dir="back"), ("○", (produces, None, True)))
        self.assertEqual(drawn(dir="back", state="fallback"),
                         ("○", (kit.muted(produces), None, False)))
        self.assertEqual(drawn(state="failed"), ("✕", scene.wire_style(w, "failed")))
        self.assertEqual(drawn(state="cancelled"), ("⊘", scene.wire_style(w, "inactive")))

    def test_token_marks_match_the_tree(self):
        """Both views play one Trace: every token state gets the same mark and
        style in the graph as in the tree, so it survives --color never alike."""
        w = next(w for w in Run(CHECKOUT).scn.wires if w.key == SHOP)
        for kw in ({}, {"dir": "back"}, {"dir": "back", "state": "fallback"},
                   {"state": "failed"}, {"state": "cancelled"}):
            tok = sim.Token(w.ident, 0.5, kw.get("dir", "out"), 0,
                            **{k: v for k, v in kw.items() if k != "dir"})
            t = vgraph._token(tok, w)
            with self.subTest(**kw):
                self.assertEqual((t.mark, t.style), view.vtree._token_glyph(tok, w))

    def test_token_through_a_chip(self):
        run = Run(CHECKOUT, payloads=True)
        ticks = [i for i, f in enumerate(run.trace.frames)
                 if any(t.wire[:3] == SHOP for t in f.tokens)]
        ys = [_cells(run.rows(i), "●")[0][1] for i in ticks]
        rows = run.text(ticks[0])
        chip = next(y for y, ln in enumerate(rows) if "{Cart}" in ln)
        self.assertLess(min(ys), chip)
        self.assertGreater(max(ys), chip, "the token crosses the {Cart} chip")

    def test_route_cells_skip_other_wires(self):
        R = vgraph._Route
        routes = [R("a", "\0p1", "->", [(0, 1)]), R("\0p1", "c", "->", [(0, 2)]),
                  R("a", "\0p2", "->", [(5, 1)]), R("\0p2", "b", "->", [(5, 2)])]
        self.assertEqual(vgraph._route_cells(routes, ("a", "b", "->")), [(5, 1), (5, 2)])
        self.assertEqual(vgraph._route_cells(routes, ("a", "b", "~>")), [])

    def test_self_call_token_on_its_mark(self):
        run = Run(EXECUTIONS)
        key = ("Scheduler_service", "Scheduler_service", "->")
        i = run.first(lambda f: any(t.wire[:3] == key for t in f.tokens))
        line = next(ln for ln in run.text(i) if "[Scheduler]" in ln)
        self.assertNotIn("↺", line)
        self.assertIn("●", line)
        stubbed = Run(EXECUTIONS, payloads=True)
        rows = stubbed.rows(i)
        [(x, y, style)] = [c for c in _cells(rows, "●") if c[2][2]]
        self.assertIn("└─", kit.ansi(rows[y], False)[x - 2:x])


class Boxes(unittest.TestCase):
    def test_untouched_boxes_are_muted(self):
        run = Run(CHECKOUT)
        rows = run.rows(0)
        email = _cell_style(rows, "[Email]")
        colour = kit.kind_color("service")
        self.assertEqual(email, (kit.muted(colour), None, False))
        self.assertEqual(run.look(0).looks["Email_service"], "muted")

    def test_waiting_and_failed_badges(self):
        run = Run(CHECKOUT, "API.charge:fails")
        i = run.first(lambda f: f.nodes.get("Shopper_actor") == "waiting")
        self.assertIn("(Shopper) …", "\n".join(run.text(i)))
        last = run.text(len(run.trace.frames) - 1)
        self.assertIn("[Payments] ✕", "\n".join(last))
        rows = run.rows(len(run.trace.frames) - 1)
        self.assertEqual(_cell_style(rows, "[Payments]")[0], scene.colour_of("edges-fail"))

    def test_instances_and_recursion(self):
        arena = Run(ARENA)
        n = arena.frame(0).instances["Bullet_service"]
        self.assertNotEqual(n, 1)
        self.assertIn(f"[Bullet] ×{n}", "\n".join(arena.text(0)))
        run = Run(EXECUTIONS)
        i = run.first(lambda f: f.depth.get("Builder_service", 0) > 1)
        k = run.frame(i).depth["Builder_service"]
        self.assertIn(f"[Builder] ↻{k}", "\n".join(run.text(i)))


class Machines(unittest.TestCase):
    def test_current_state_is_led_by_a_mark(self):
        run = Run(ORDERS)
        text = "\n".join(run.text(len(run.trace.frames) - 1))
        self.assertIn("◉ Settled", text)
        self.assertIn("◉ Idle", text)
        self.assertIn("│   Open │", text, "another state keeps a blank slot")

    def test_owner_shows_the_state_when_the_machine_is_hidden(self):
        run = Run(ORDERS, depth=0)
        text = "\n".join(run.text(len(run.trace.frames) - 1))
        self.assertIn("{Order} ◉ Settled", text)
        self.assertIn("[Checkout] ◉ Idle", text)


class Stability(unittest.TestCase):
    def test_slots_keep_the_layout_still(self):
        for text in (CHECKOUT, ORDERS, EXECUTIONS):
            run = Run(text)
            shapes = {(len(rows), max(map(len, rows)))
                      for rows in (run.text(i) for i in range(0, len(run.trace.frames), 3))}
            self.assertEqual(len(shapes), 1, shapes)

    def test_slots_match_a_scan_of_every_node(self):
        run = Run(EXECUTIONS)
        stage = vgraph._stage(run.trace.scene)
        full = {}
        for f in run.trace.frames:
            for nid in run.trace.scene.nodes:
                n = kit.row_len(vgraph._badge_runs(f, nid, stage))
                if n > full.get(nid, 0):
                    full[nid] = n
        self.assertEqual(run.slots, full)

    def test_slots_are_worked_out_once_per_trace(self):
        run = Run(CHECKOUT)
        self.assertIs(vgraph._trace_slots(run.trace), vgraph._trace_slots(run.trace))
        self.assertEqual(vgraph._trace_slots(run.trace), run.slots)
        other = Run(CHECKOUT).trace
        self.assertIsNot(vgraph._trace_slots(other), vgraph._trace_slots(run.trace))

    def test_without_a_frame_nothing_changes(self):
        g = kit.render.parse_document(CHECKOUT)
        plain = vgraph.compose(g, kit.ALL_DEPTH, False)
        self.assertEqual(plain, vgraph.compose(g, kit.ALL_DEPTH, False, trace=None))
        self.assertNotIn("●", "".join(kit.ansi(r, False) for r in plain[0]))


class Focus(unittest.TestCase):
    def test_box_holds_the_token(self):
        run = Run(CHECKOUT)
        i = run.first(lambda f: any(t.wire[:3] == SHOP and t.dir == "out" for t in f.tokens))
        x, y, w, h = vgraph.sim_focus(*run.args(), trace=run.trace, tick=i)
        [(tx, ty, _st)] = _cells(run.rows(i), "●")
        self.assertTrue(x <= tx < x + w and y <= ty < y + h)

    def test_box_holds_the_active_boxes(self):
        run = Run(CHECKOUT)
        i = run.first(lambda f: "active" in f.nodes.values())
        x, y, w, h = vgraph.sim_focus(*run.args(), trace=run.trace, tick=i)
        text = run.text(i)
        for nid, status in run.frame(i).nodes.items():
            if status != "active" or nid not in run.g.nodes:
                continue
            label = kit.node_label(run.g.nodes[nid])
            ly = next(k for k, ln in enumerate(text) if label in ln)
            lx = text[ly].index(label)
            self.assertTrue(x <= lx and lx + len(label) <= x + w and y <= ly < y + h, nid)

    def test_probe_draws_like_the_frame(self):
        run = Run(ORDERS)
        i = len(run.trace.frames) // 2
        probe, _w = vgraph._compose(*run.args(), run.trace, i, probe=True)
        def cells(rows):     # every cell's character and plain style
            return [[(c, tuple(st) if st else None) for text, st in row for c in text]
                    for row in rows]

        self.assertEqual(cells(probe), cells(run.rows(i)))

    def test_follows_the_fit_width(self):
        run = Run(ORDERS)
        i = len(run.trace.frames) // 2
        args = run.args()[:5] + (60,) + run.args()[6:]
        box = vgraph.sim_focus(*args, trace=run.trace, tick=i)
        rows, _w = vgraph.compose(*args, trace=run.trace, tick=i)
        self.assertIsNotNone(box)
        self.assertLessEqual(box[1] + box[3], len(rows))

    def test_no_trace_no_focus(self):
        g = kit.render.parse_document(CHECKOUT)
        self.assertIsNone(vgraph.sim_focus(g, kit.ALL_DEPTH, False))

    def test_a_probe_style_never_merges_with_a_plain_one(self):
        st = (kit.GREY["light"], None, True)
        self.assertNotEqual(vgraph._Probe(st), st)
        self.assertNotEqual(st, vgraph._Probe(st))
        self.assertEqual(vgraph._Probe(st), vgraph._Probe(st))
        self.assertEqual(vgraph._probed_box([[("ab", None), ("●", vgraph._Probe(st))],
                                             [("  ", None), ("x", vgraph._Probe(st))]]),
                         (2, 0, 1, 2))


FAN = "\n".join(
    [f"[Hub] -> [{n}]" for n in ("Alpha", "Beta", "Gamma", "Delta", "Eps", "Zeta", "Eta", "Theta")]
    + ["[Delta] -> |Db| : put => {R}", "  !> <Oops>"]) + "\n"
LINE_CHARS = set("│─┼┬┴┐┌└┘├┤▼")


def _grid(rows) -> dict:
    """{(x, y): (char, style)} of the drawn cells."""
    out = {}
    for y, row in enumerate(rows):
        x = 0
        for text, style in row:
            for k, c in enumerate(text):
                out[(x + k, y)] = (c, style)
            x += len(text)
    return out


class WrappedTrunk(unittest.TestCase):
    """8. a wrapped fan-out's trunk under a run."""
    WIDTH = 50

    def compose(self, run: Run, i: int, memo=None):
        args = list(run.args())
        args[5] = self.WIDTH
        rows, _w = vgraph.compose(*args, trace=run.trace, tick=i, memo=memo)
        return rows

    def test_failed_member_lights_the_trunk(self):
        """[Hub] → [Delta] passes the wrapped trunk: with Delta's call failing,
        the failed stroke is one connected path from under [Hub] to the head
        over [Delta], not only its last row."""
        run = Run(FAN, "Delta->Db:fails")
        rows = self.compose(run, len(run.trace.frames) - 1)
        text = [kit.ansi(r, False) for r in rows]
        hub_y = next(y for y, t in enumerate(text) if "[Hub]" in t) + 1    # its bottom border
        delta_y = next(y for y, t in enumerate(text) if "[Delta]" in t)
        self.assertGreater(delta_y - hub_y, 6, "the fixture must wrap the fan-out")
        grid, fail = _grid(rows), scene.colour_of("edges-fail")

        def failed(cell):
            got = grid.get(cell)
            return got is not None and got[0] in LINE_CHARS and got[1] and got[1][0] == fail

        start = [c for c in grid if c[1] == delta_y - 2 and grid[c][0] == "▼" and failed(c)]
        self.assertEqual(len(start), 1)
        seen, todo = set(start), list(start)
        while todo:
            x, y = todo.pop()
            for nb in ((x + 1, y), (x - 1, y), (x, y - 1), (x, y + 1)):
                if nb not in seen and failed(nb):
                    seen.add(nb)
                    todo.append(nb)
        self.assertTrue(any(y == hub_y + 1 for _x, y in seen),
                        "the failed path is cut before it reaches [Hub]")

    def test_untouched_members_keep_their_look(self):
        """Only the trunk cells the failed member shares take its look: a branch
        to a member the run never took stays untouched."""
        run = Run(FAN, "Delta->Db:fails")
        rows = self.compose(run, len(run.trace.frames) - 1)
        theta = run.look(len(run.trace.frames) - 1).styles[("Hub_service", "Theta_service", "->")]
        grid = _grid(rows)
        text = [kit.ansi(r, False) for r in rows]
        y = next(y for y, t in enumerate(text) if "[Theta]" in t) - 2
        heads = [st for (x, yy), (c, st) in grid.items() if yy == y and c == "▼"]
        self.assertIn(theta, heads)

    def test_memo_repaints_the_trunk(self):
        """Drawn frame after frame with a FrameMemo (forward, then back), each
        frame is the frame drawn afresh: the trunk's rows are repainted when the
        member it takes its look from changes."""
        for name in ("Delta->Db:fails", "happy"):
            run = Run(FAN, name)
            memo = kit.FrameMemo()
            last = len(run.trace.frames) - 1
            for i in list(range(last + 1)) + [0, last, 1]:
                self.assertEqual(self.compose(run, i, memo), self.compose(run, i), (name, i))


if __name__ == "__main__":
    unittest.main()
