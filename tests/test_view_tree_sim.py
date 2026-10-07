"""Tests for the simulation overlay of view_tree.py (sim.md §7: P5b).

Covers:
  - the layout holds still for a whole trace: every frame has the drawing's
    width, its rows, and every `◀` where the first frame has it;
  - without a trace nothing changes (no status slot, no restyling);
  - rows: `▸` before an active node's label (bold, full colour), `…` waiting
    and `✕` failed (edges-fail) after it, an untouched node muted;
  - state machines: `◉` on the current state's row, moving with its triggers;
    at a depth that hides the states, `◉ State` after the owner's label;
  - lanes: lit bold in full colour, never taken muted, a failure route in
    edges-fail;
  - tokens: `●` in the lane's gutter column, on its source row at 0 and its
    target row at 1; a return `○`; a failed attempt `✕`; a cancelled one `⊘`,
    distinct from both without colour; a self-call's token
    on its call mark; tokens on wires the tree does not draw skipped;
  - badges: `↻k` recursion depth, room kept for the widest one in the trace;
    `×n` only when n ≠ 1 (as the graph view's);
  - source marks muted in a simulation, so a token on a source row stands out;
  - badges' room computed only over the nodes that ever carry one;
  - a tick past the trace's end; the legend's sim row, in the graph row's
    words (view.sim_legend) wherever the two views draw alike.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]


def _load(name: str, fname: str):
    spec = importlib.util.spec_from_file_location(name, _DIR / fname)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


vtree = _load("sigil_view_tree_sim_tests", "view_tree.py")
sim = _load("sigil_sim_view_tree_tests", "sim.py")
kit, scene = vtree.kit, vtree.scene

ORDERS = (_DIR / "site" / "examples" / "04-orders.sigil").read_text()
EXECUTIONS = (_DIR / "tests" / "fixtures" / "executions.sigil").read_text()
CHAIN = "(User) -> [API]\n[API] -> |DB|\n[API] !> [Alarm]\n"


def run(text: str, depth: int = 1, events: str = "land", name: str = "happy"):
    """(graph, trace) — the trace named as the tree draws it."""
    g = kit.render.parse_document(text)
    scn = scene.build_scene(g, events=events, triggers=True, access=False, depth=depth)
    return g, sim.project(sim.simulate(scn, sim.scenario(scn, name)), scn)


def draw(g, trace, tick: int, depth: int = 1, **kw):
    return vtree.compose_tree(g, depth, trace=trace, tick=tick, **kw)


def plain(rows) -> list:
    return ["".join(t for t, _ in r) for r in rows]


def find_row(rows, name: str) -> int:
    """The index of the first row whose label (rails, slot and marks off) is name."""
    for y, ln in enumerate(plain(rows)):
        if re.sub(r"^[│┆├└┌─┄·▸◉ ]*", "", ln).startswith(name):
            return y
    raise AssertionError(f"no row {name!r}")


def cell(rows, x: int, y: int):
    """(char, style) at column x of row y."""
    at = 0
    for text, style in rows[y]:
        if at <= x < at + len(text):
            return text[x - at], style
        at += len(text)
    return " ", None


def style_at(rows, y: int, text: str):
    """The style of the run on row y that holds text."""
    for t, style in rows[y]:
        if text in t:
            return style
    raise AssertionError(f"{text!r} not on row {y}: {plain(rows)[y]!r}")


def first_tick(trace, pred) -> int:
    return next(f.tick for f in trace.frames if pred(f))


class LayoutHoldsStill(unittest.TestCase):
    def check(self, text: str, depth: int, name: str = "happy"):
        g, trace = run(text, depth, name=name)
        first = draw(g, trace, 0, depth)
        heads = [[m.start() for m in re.finditer("◀", ln)] for ln in plain(first[0])]
        for f in trace.frames:
            rows, w = draw(g, trace, f.tick, depth)
            self.assertEqual(w, first[1], f.tick)
            self.assertEqual(len(rows), len(first[0]), f.tick)
            self.assertEqual([[m.start() for m in re.finditer("◀", ln)] for ln in plain(rows)],
                             heads, f.tick)

    def test_orders(self):
        self.check(ORDERS, 1)

    def test_orders_machines_hidden(self):
        self.check(ORDERS, 0, "Payments:fails")

    def test_executions_with_recursion(self):
        self.check(EXECUTIONS, 1)


class WithoutATrace(unittest.TestCase):
    def test_no_slot_and_no_restyling(self):
        g = kit.render.parse_document(CHAIN)
        self.assertEqual(vtree.compose_tree(g, 1), vtree.compose_tree(g, 1, trace=None, tick=5))
        self.assertTrue(plain(vtree.compose_tree(g, 1)[0])[0].startswith("(User)"))

    def test_slot_before_every_label(self):
        g, trace = run(CHAIN)
        rows, _w = draw(g, trace, 0)
        for ln in plain(rows):
            self.assertRegex(ln, r"^[▸ ] [(\[|]")


class Rows(unittest.TestCase):
    def setUp(self):
        self.g, self.trace = run(CHAIN)

    def test_active_row(self):
        rows, _w = draw(self.g, self.trace, 0)
        y = find_row(rows, "(User)")
        self.assertTrue(plain(rows)[y].startswith("▸ (User)"))
        fg, _bg, bold = style_at(rows, y, "(User)")
        self.assertEqual(str(fg), str(kit.kind_color("actor")))
        self.assertTrue(bold)

    def test_untouched_row_is_muted(self):
        rows, _w = draw(self.g, self.trace, 0)
        y = find_row(rows, "|DB|")
        self.assertTrue(plain(rows)[y].startswith("  |DB|"))
        fg, _bg, bold = style_at(rows, y, "|DB|")
        self.assertEqual(str(fg), str(kit.muted(kit.kind_color("store"))))
        self.assertFalse(bold)

    def test_waiting_row(self):
        t = first_tick(self.trace, lambda f: f.nodes.get("User_actor") == "waiting")
        rows, _w = draw(self.g, self.trace, t)
        y = find_row(rows, "(User)")
        self.assertTrue(plain(rows)[y].startswith("  (User) …"))
        self.assertEqual(style_at(rows, y, "…")[0], kit.kind_color("actor"))

    def test_failed_row(self):
        g, trace = run(CHAIN, name=next(s.name for s in sim.scenarios(
            scene.build_scene(kit.render.parse_document(CHAIN))) if s.name != "happy"))
        t = first_tick(trace, lambda f: "failed" in f.nodes.values())
        rows, _w = draw(g, trace, t)
        failed = [nid for nid, st in trace.frames[t].nodes.items() if st == "failed"]
        name = kit.node_label(g.nodes[failed[0]])
        y = find_row(rows, name)
        self.assertTrue(plain(rows)[y].startswith(f"  {name} ✕"))
        self.assertEqual(str(style_at(rows, y, name)[0]), str(scene.colour_of("edges-fail")))
        self.assertEqual(style_at(rows, y, "✕"), (scene.colour_of("edges-fail"), None, True))


class Machines(unittest.TestCase):
    def setUp(self):
        self.g, self.trace = run(ORDERS)

    def current_rows(self, tick: int) -> list:
        rows, _w = draw(self.g, self.trace, tick)
        return [re.sub(r"^[│┆├└─┄· ]*◉ ", "", ln).split()[0] for ln in plain(rows)
                if re.match(r"^[│┆├└─┄· ]*◉ ", ln)]

    def test_start_states_then_moved(self):
        self.assertEqual(self.current_rows(0), ["Idle", "●"])
        self.assertEqual(self.current_rows(len(self.trace.frames) - 1), ["Idle", "Settled"])

    def test_one_current_state_per_machine_every_frame(self):
        for f in self.trace.frames:
            self.assertEqual(len(self.current_rows(f.tick)), len(f.machines), f.tick)

    def test_hidden_machine_on_its_owner(self):
        g, trace = run(ORDERS, depth=0)
        rows, _w = draw(g, trace, len(trace.frames) - 1, depth=0)
        self.assertIn("{Order} ▸ ◉ Settled", plain(rows)[find_row(rows, "{Order}")])
        style = style_at(rows, find_row(rows, "{Order}"), "◉ Settled")
        self.assertEqual(style, (kit.kind_color("state"), None, True))


class Lanes(unittest.TestCase):
    def setUp(self):
        self.g, self.trace = run(CHAIN)

    def lane_style(self, tick: int, src: str, dst: str):
        """The style of the `◀` on dst's row (its nearest incoming lane: here the
        only one) — the lane's stroke."""
        rows, _w = draw(self.g, self.trace, tick)
        y = find_row(rows, dst)
        x = plain(rows)[y].index("◀")
        return cell(rows, x, y)[1]

    def test_lit_lane_bold_full_colour(self):
        style = self.lane_style(0, "(User)", "[API]")
        self.assertEqual(style, (kit.kind_color("actor"), None, True))

    def test_never_taken_lane_faint(self):
        self.assertEqual(self.lane_style(0, "[API]", "|DB|"),
                         (kit.faded(kit.kind_color("service"), kit.SIM_FAINT, "faint"),
                          None, False))

    def test_taken_lane_in_the_trail_colour(self):
        last = len(self.trace.frames) - 1
        self.assertEqual(self.lane_style(last, "(User)", "[API]"),
                         (kit.faded(kit.kind_color("actor"), kit.SIM_TRAIL, "trail"),
                          None, False))

    def test_failure_route_in_fail_colour(self):
        name = next(s.name for s in sim.scenarios(scene.build_scene(self.g)) if s.name != "happy")
        g, trace = run(CHAIN, name=name)
        rows, _w = vtree.compose_tree(g, 1, trace=trace, tick=len(trace.frames) - 1)
        y = find_row(rows, "[Alarm]")
        style = cell(rows, plain(rows)[y].index("◀"), y)[1]
        self.assertEqual(style, (scene.colour_of("edges-fail"), None, True))


class Tokens(unittest.TestCase):
    def setUp(self):
        self.g, self.trace = run(CHAIN)
        self.scn = self.trace.scene
        self.wire = next(w for w in self.scn.wires if w.src == "User_actor")

    def at(self, at: float, **kw):
        """The drawing of frame 0 with one token at `at` on User → API."""
        tok = sim.Token(self.wire.ident, at, kw.pop("dir", "out"), 1, kw.pop("state", "moving"))
        frame = self.trace.frames[0]._replace(tokens=(tok,))
        trace = self.trace._replace(frames=(frame,))
        return draw(self.g, trace, 0)[0]

    def lane_x(self, rows) -> int:
        y = find_row(rows, "(User)")
        return len(plain(rows)[y].rstrip()) - 1     # the source tap ends the row

    def test_source_row_at_zero_target_row_at_one(self):
        rows = self.at(0.0)
        x = self.lane_x(rows)
        self.assertEqual(cell(rows, x, find_row(rows, "(User)"))[0], "●")
        rows = self.at(1.0)
        self.assertEqual(cell(rows, x, find_row(rows, "[API]"))[0], "●")
        self.assertEqual(cell(rows, x, find_row(rows, "(User)"))[0], "●")   # the tap itself

    def test_token_style_and_marks(self):
        rows = self.at(1.0)
        x, y = self.lane_x(rows), find_row(rows, "[API]")
        self.assertEqual(cell(rows, x, y)[1], (kit.kind_color("actor"), None, True))
        self.assertEqual(cell(self.at(1.0, dir="back"), x, y)[0], "○")
        failed = self.at(1.0, state="failed")
        self.assertEqual(cell(failed, x, y), ("✕", (scene.colour_of("edges-fail"), None, True)))

    def test_source_marks_muted_so_a_token_stands_out(self):
        rows = self.at(1.0)
        x = self.lane_x(rows)
        mark = cell(rows, x, find_row(rows, "(User)"))
        self.assertEqual(mark, ("●", scene.wire_style(self.wire, "inactive")))
        self.assertNotEqual(mark, cell(rows, x, find_row(rows, "[API]")))  # the token
        bare = vtree.compose_tree(self.g, 1)[0]     # without a trace: the lane's own style
        y = find_row(bare, "(User)")
        self.assertEqual(cell(bare, len(plain(bare)[y].rstrip()) - 1, y)[1],
                         scene.wire_style(self.wire))

    def test_token_on_an_undrawn_wire_is_skipped(self):
        frame = self.trace.frames[0]
        tok = sim.Token(("nowhere", "nothing", "->", 0), 0.5, "out", 1)
        quiet = self.trace._replace(frames=(frame._replace(tokens=()),))
        stray = self.trace._replace(frames=(frame._replace(tokens=(tok,)),))
        self.assertEqual(draw(self.g, stray, 0), draw(self.g, quiet, 0))

    def test_self_call_token_on_its_mark(self):
        g, trace = run(EXECUTIONS)
        selfs = {w.ident for w in trace.scene.wires
                 if w.call is not None and w.call.self_call and not any(w.paths)}
        t = first_tick(trace, lambda f: any(tok.wire in selfs for tok in f.tokens))
        rows, _w = draw(g, trace, t)
        y = find_row(rows, "[Scheduler]")
        self.assertRegex(plain(rows)[y], r"\[Scheduler\] ● +◀")
        quiet = plain(draw(g, trace, 0)[0])[y]
        self.assertRegex(quiet, r"\[Scheduler\] ↺ +◀")


class Badges(unittest.TestCase):
    def test_depth_badge_and_its_room(self):
        g, trace = run(EXECUTIONS)
        t = first_tick(trace, lambda f: f.depth.get("Builder_service", 0) > 1)
        k = trace.frames[t].depth["Builder_service"]
        rows, _w = draw(g, trace, t)
        self.assertIn(f"[Builder] ● ↻{k} ◀", plain(rows)[find_row(rows, "[Builder]")])
        rows, _w = draw(g, trace, 0)
        self.assertIn("[Builder] ↻    ◀", plain(rows)[find_row(rows, "[Builder]")])


class Errors(unittest.TestCase):
    def test_tick_past_the_end(self):
        g, trace = run(CHAIN)
        with self.assertRaises(IndexError):
            draw(g, trace, len(trace.frames))


class Legend(unittest.TestCase):
    def test_sim_row_only_when_asked(self):
        self.assertEqual(len(vtree.tree_legend()), 3)
        rows = vtree.tree_legend(sim=True)
        self.assertEqual(len(rows), 4)
        text = "".join(t for t, _ in rows[-1])
        for mark in ("▸ active", "… waiting", "✕ failed", "⊘ cancelled", "◉ current state",
                     "● out", "○ return / fallback", "×n instances", "↻k recursion",
                     "─ now", "─ taken", "─ untouched"):
            self.assertIn(mark, text)

    def test_words_shared_with_the_graph_views_row(self):
        """Every entry of the app's graph sim row the tree draws alike reads the
        same in the tree's row (the cancelled token aside until the graph view
        draws it `⊘` as well)."""
        def entries(row):
            return {(mark, word.strip()) for (mark, _s), (word, _w) in zip(row[1::2], row[2::2])}

        view = _load("sigil_view_tree_sim_app", "view.py")
        graph = {e for e in entries(view.sim_legend()) if e[1] != "cancelled"}
        self.assertLessEqual(graph, entries(vtree.tree_legend(sim=True)[-1]))


class BadgeWidths(unittest.TestCase):
    def test_widest_over_the_trace_only_for_badged_nodes(self):
        frame = sim.Frame(*([None] * len(sim.Frame._fields)))._replace(
            nodes={}, instances={}, depth={}, machines={})
        frames = (frame._replace(instances={"A": 3, "N": 1}, depth={"B": 1}),
                  frame._replace(instances={"A": 12}, depth={"B": 2}),
                  frame._replace(machines={"M": "S", "N": "T"}))
        trace = sim.Trace(None, frames, "done", {})
        nodes = {nid: kit.render.Node(nid, nid, "service") for nid in "ABMN"}
        self.assertEqual(vtree._badge_widths(trace, nodes, {"M"}, {"S": "Start"}),
                         {"A": len(" ×12"), "B": len(" ↻2"), "M": len(" ◉ Start")})

    def test_one_instance_has_no_badge(self):
        """`×n` only when n ≠ 1, as the graph view's (view_graph._badge_runs)."""
        frame = sim.Frame(*([None] * len(sim.Frame._fields)))._replace(
            nodes={}, instances={"A": 1, "B": 2}, depth={}, machines={})
        one, two = (kit.render.Node(nid, nid, "service") for nid in "AB")
        self.assertEqual(vtree._badge_runs(one, frame, set(), {}), [])
        self.assertEqual(vtree._badge_runs(two, frame, set(), {}),
                         [(" ×2", (kit.kind_color("service"), None, False))])


class CancelledToken(unittest.TestCase):
    def test_mark_survives_without_colour(self):
        """A cancelled token's mark differs from an out `●` and a failed `✕`."""
        g, trace = run(CHAIN)
        wire = trace.scene.wires[0]
        marks = {state: vtree._token_glyph(sim.Token(wire.ident, 0.5, "out", 1, state), wire)[0] for state in ("moving", "failed", "cancelled")}
        self.assertEqual(marks["cancelled"], vtree.CANCELLED_MARK)
        self.assertEqual(len(set(marks.values())), 3)


if __name__ == "__main__":
    unittest.main()
