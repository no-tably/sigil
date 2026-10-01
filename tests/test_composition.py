"""Tests for composition trees (language.md "Composition trees"; rfcs/0001).

Covers:
  - parsing `\\-<rel>` branches into Graph.tree (parents by indentation, inline
    `[parent] \\-& [child]`, spawn `*-`, `{cond}-`, a component placed under
    several parents);
  - branch markers inside prose / payloads are not branches;
  - lint: SGL110 (malformed / unknown relation), SGL111 (no parent), masking so
    other rules do not misread branch lines; a dialect can extend or disable it;
  - the tree + wires view: outline rows, one lane per flow tapping every
    occurrence, hops over crossed lanes.

Run:  uv run python -m unittest discover notations/sigil/tests/
"""
from __future__ import annotations

import importlib.util
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


render = _load("sigil_render", "render.py")
lint = _load("sigil_lint", "lint.py")
view = _load("sigil_view", "view.py")

ECS = """#!sketch
[Ship]
    \\-& {Transform}
    \\-& {Health}
    \\-*-> [Bullet]
        \\-& {Transform}
        \\-& {Damage}
[Asteroid]
    \\-{shattered}-? [Shard]
[Physics] -> {Transform}
{Damage} -> [Combat] -> {Health}
"""


def rules(text, dialect=None):
    return [d.rule for d in lint.lint(text, dialect=dialect).diagnostics]


class TestParse(unittest.TestCase):
    def setUp(self):
        self.g = render.parse_document(ECS)
        self.t = self.g.tree

    def test_roots_and_depths(self):
        shape = [(self.g.nodes[e.node].name, e.depth, e.rel) for e in self.t]
        self.assertEqual(shape, [
            ("Ship", 0, None), ("Transform", 1, "&"), ("Health", 1, "&"),
            ("Bullet", 1, ">"), ("Transform", 2, "&"), ("Damage", 2, "&"),
            ("Asteroid", 0, None), ("Shard", 1, "?"),
        ])

    def test_parents(self):
        names = [self.g.nodes[e.node].name for e in self.t]
        bullet = names.index("Bullet")
        self.assertEqual(self.t[bullet].parent, 0)
        self.assertEqual(self.t[bullet + 1].parent, bullet)
        self.assertTrue(self.t[bullet].spawn)

    def test_condition(self):
        shard = next(e for e in self.t if self.g.nodes[e.node].name == "Shard")
        self.assertEqual(shard.cond, "shattered")

    def test_component_under_two_parents_is_one_node(self):
        ids = [e.node for e in self.t if self.g.nodes[e.node].name == "Transform"]
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 1)

    def test_branches_add_no_flow_edges(self):
        self.assertEqual({(e.src, e.dst) for e in self.g.edges}, {
            ("Physics_service", "Transform_data"),
            ("Damage_data", "Combat_service"),
            ("Combat_service", "Health_data"),
        })

    def test_inline_branch(self):
        g = render.parse_document("[Log] \\-& {Scrollable}\n")
        self.assertEqual([(g.nodes[e.node].name, e.parent) for e in g.tree],
                         [("Log", None), ("Scrollable", 0)])

    def test_marker_in_payload_is_not_a_branch(self):
        g = render.parse_document("[A] -> [B] : note `\\-& [C]` here\n")
        self.assertEqual(g.tree, [])
        self.assertNotIn("C_service", g.nodes)

    def test_expansion_contents_have_their_own_tree(self):
        g = render.parse_document("[Game] := {\n  [World]\n      \\-& [Physics]\n}\n")
        sub = g.expansions["Game_service"]
        self.assertEqual(len(sub.tree), 2)


class TestLint(unittest.TestCase):
    def test_ecs_lints_clean(self):
        self.assertEqual(rules(ECS), [])

    def test_unknown_relation(self):
        self.assertIn("SGL110", rules("#!sketch\n[A]\n    \\-% [B]\n"))

    def test_layout_relation_is_not_core(self):
        self.assertIn("SGL110", rules("#!sketch\n[A]\n    \\-+ [B]\n"))

    def test_orphan_branch(self):
        self.assertIn("SGL111", rules("#!sketch\n    \\-& {Orphan}\n"))

    def test_branch_lines_not_misread(self):
        # `\\->` must not trip the reverse-arrow / prose rules once masked.
        self.assertEqual(rules("#!sketch\n[A]\n    \\-> [B]\n    \\-$ |Items|\n"), [])

    def test_dialect_extends_relations(self):
        class Plus:
            COMPOSITION_RELATIONS = "+"
        self.assertNotIn("SGL110", rules("#!sketch\n[A]\n    \\-+ [B]\n", Plus))

    def test_dialect_can_take_over(self):
        class Own:
            COMPOSITION_LINT = False
        self.assertNotIn("SGL110", rules("#!sketch\n[A]\n    \\-% [B]\n", Own))


class TestTreeView(unittest.TestCase):
    def draw(self, text):
        rows, _w = view.compose_tree(render.parse_document(text), 1)
        return [view.ansi(r, False) for r in rows]

    def test_outline(self):
        out = self.draw(ECS)
        self.assertEqual(out[0].split()[0], "[Ship]")
        self.assertTrue(out[1].startswith("├─& {Transform}"))
        self.assertTrue(any(ln.startswith("└─* [Bullet]") for ln in out))
        self.assertTrue(any("{shattered}? [Shard]" in ln for ln in out))

    def test_query_taps_every_occurrence(self):
        out = self.draw(ECS)
        transforms = [ln for ln in out if "{Transform}" in ln]
        self.assertEqual(len(transforms), 2)
        self.assertTrue(all("◀" in ln for ln in transforms))

    def test_one_source_marker_per_flow_source(self):
        out = "\n".join(self.draw(ECS))
        self.assertEqual(out.count("●"), 3)       # Physics, Damage, Combat

    def test_crossings_hop(self):
        out = self.draw("[A] -> [D]\n[B]\n[C] -> [E]\n[D]\n[E]\n")
        self.assertFalse(any("┼" in ln for ln in out))

    def test_expansions_nest(self):
        out = self.draw("[Game] := {\n  [World] -> [Render]\n}\n")
        self.assertTrue(out[0].startswith("[Game]"))
        self.assertTrue(any(ln.startswith("├── [World]") or ln.startswith("└── [World]")
                            for ln in out))

    def test_legend_in_live_view_and_once(self):
        import contextlib, io, tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "ecs.sigil"
            p.write_text(ECS)
            st = view.ViewState(p, do_lint=False, tree=True)
            st.reload(force=True)
            text = "\n".join("".join(t for t, _ in r) for r in st.frame(140, 40))
            self.assertIn("& has", text)
            self.assertIn("◀ target", text)
            self.assertIn("keys", text)
            st.key("t")                                    # graph mode: arrows legend instead
            text = "\n".join("".join(t for t, _ in r) for r in st.frame(140, 40))
            self.assertNotIn("◀ target", text)
            self.assertIn("arrows", text)
            self.assertIn("t tree/graph", text)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                view.once(p, 1, False, False, tree=True)
            self.assertIn("◀ target", buf.getvalue())

    def test_trigger_lanes_and_state_labels(self):
        doc = ("#!sketch\n[Payments] ~> <Paid>\n"
               "state [Checkout] {\n  Idle -<Paid>-> Busy\n}\n")
        out = self.draw(doc)
        busy = next(ln for ln in out if "Busy" in ln)
        self.assertIn("<Paid>", busy)            # trigger listed beside the state
        self.assertIn("◀", busy)                 # and a lane arrives there
        paid = next(ln for ln in out if ln.startswith("<Paid>"))
        self.assertIn("◎", paid)                 # the event is a trigger lane's source

    def test_graph_mode_lists_triggers(self):
        doc = ("#!sketch\n[Payments] ~> <Paid>\n"
               "state [Checkout] {\n  Idle -<Paid>-> Busy\n}\n")
        rows, _ = view.compose(render.parse_document(doc), 1, False)
        text = "\n".join(view.ansi(r, False) for r in rows)
        self.assertIn("<Paid> ⇢ [Checkout]: Idle → Busy", text)

    def test_path_taps_only_matching_occurrence(self):
        out = self.draw(ECS + "[Homing] => [Bullet]/{Transform}\n")
        homing_lane_rows = [ln for ln in out if "{Transform}" in ln]
        self.assertEqual(len(homing_lane_rows), 2)
        text = "\n".join(out)
        self.assertEqual(text.count("◆"), 1)            # one `=>` source marker

    def test_arrow_markers(self):
        out = "\n".join(self.draw("[A] ~> [B]\n[A] *> [C]\n[A] !> <E>\n"))
        for mark in ("○", "✱", "✖"):
            self.assertIn(mark, out)
        self.assertIn("═", out)                           # broadcast is double

    def test_spacing_and_toggles(self):
        import tempfile
        doc = "[A]\n    \\-& {X}\n[B]\n[C] -> {X}\n[D] ~> <Go>\nstate [A] {\n  Idle -<Go>-> On\n}\n"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.sigil"
            p.write_text(doc)
            st = view.ViewState(p, do_lint=False, tree=True)
            st.reload(force=True)
            spaced = len(st._rows)
            st.key("s")
            self.assertLess(len(st._rows), spaced)          # compact drops blank rows
            with_trig = "\n".join(view.ansi(r, False) for r in st._rows)
            st.key("e")
            without = "\n".join(view.ansi(r, False) for r in st._rows)
            self.assertIn("◎", with_trig)
            self.assertNotIn("◎", without)

    NOTED = ("#!sketch\n# routes traffic\n[Router]\n    \\-(3)-> [ZoneA]   # 3:1 while B migrates\n"
             "(User) -> [Router] : {Query}\n")

    def test_notes_markers_and_list(self):
        rows, _ = view.compose_tree(render.parse_document(self.NOTED), 1, notes="markers")
        out = "\n".join(view.ansi(r, False) for r in rows)
        lines = out.splitlines()
        self.assertIn("[Router] #1", out)                # a block note: on its component
        zone = next(ln for ln in lines if "[ZoneA]" in ln)
        self.assertNotIn("[ZoneA] #2", zone)              # an inline note trails its line…
        self.assertTrue(zone.rstrip().endswith("#2"))     # …in the right margin
        self.assertIn("#1 routes traffic", out)
        self.assertIn("#2 3:1 while B migrates", out)

    def test_notes_callouts_in_left_margin(self):
        rows, _ = view.compose_tree(render.parse_document(self.NOTED), 1, notes="callouts")
        out = [view.ansi(r, False) for r in rows]
        router = next(ln for ln in out if "[Router] #1" in ln)
        self.assertTrue(router.index("routes") < router.index("[Router]"))  # box is left
        self.assertNotIn("── notes ──", "\n".join(out))                   # no list needed

    def test_graph_mode_tags_boxes(self):
        rows, _ = view.compose(render.parse_document(self.NOTED), 1, False, notes="markers")
        out = "\n".join(view.ansi(r, False) for r in rows)
        self.assertIn("[ZoneA] #2", out)
        self.assertIn("── notes ──", out)

    def test_notes_off_by_default_and_n_cycles(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "n.sigil"
            p.write_text(self.NOTED)
            st = view.ViewState(p, do_lint=False, tree=True)
            st.reload(force=True)
            text = lambda: "\n".join(view.ansi(r, False) for r in st._rows)
            self.assertNotIn("#1", text())
            st.key("n")
            self.assertEqual(st.notes, "markers")
            self.assertIn("#1", text())
            st.key("n")
            self.assertEqual(st.notes, "callouts")
            st.key("n")
            self.assertEqual(st.notes, "off")

    def test_payloads_in_tree_view(self):
        rows, _ = view.compose_tree(render.parse_document(self.NOTED), 1, payloads=True)
        out = [view.ansi(r, False) for r in rows]
        router = next(ln for ln in out if ln.startswith("[Router]"))
        self.assertTrue(router.rstrip().endswith("┆ {Query} ┆"))    # a chip on its target row
        self.assertNotIn("── payloads ──", "\n".join(out))          # drawn, so not listed

    def test_block_and_inline_notes_drawn_differently(self):
        doc = "#!sketch\n# above\n[A]   # beside\n[A] -> [B]   # about the flow\n"
        g = render.parse_document(doc)
        self.assertEqual([(n.text, n.kind, n.edges) for n in g.notes],
                         [("above", "block", ()), ("beside", "inline", ()),
                          ("about the flow", "inline", (("A_service", "B_service", "->"),))])
        idx = view.note_index(g)
        rows, _ = view.compose_tree(g, 1, notes="callouts")
        out = [view.ansi(r, False) for r in rows]
        a_row = next(ln for ln in out if "[A] #1" in ln)
        self.assertIn("│ #1 above", a_row)                  # block: framed, on the left
        self.assertTrue(a_row.rstrip().endswith("# beside"))  # inline: trails its own line
        b_row = next(ln for ln in out if ln.lstrip().startswith("[B]") or "[B] ◀" in ln)
        self.assertTrue(b_row.rstrip().endswith("# about the flow"))   # on the flow's row
        styles = {t: st[0].role for r in rows for t, st in r if st and t.strip()}
        self.assertEqual(styles["#1"], "ui-note-block")     # colour tells the kinds apart
        self.assertEqual(styles["# beside"], "ui-note-inline")
        self.assertEqual(sorted(view.edge_notes(idx)), [("A_service", "B_service", "->")])

    def test_inline_flow_note_rides_its_edge_in_graph_view(self):
        g = render.parse_document("#!sketch\n[A] -> [B]   # about the flow\n")
        rows, _ = view.compose(g, 1, False, notes="markers")
        out = "\n".join(view.ansi(r, False) for r in rows)
        self.assertIn("▼ #1", out)                           # beside the arrowhead
        self.assertNotIn("[A] #1", out)                      # not on the source box

    def test_payload_chips_are_colour_coded(self):
        runs = view.payload_runs("quote(route) => {Fare} ×3")
        roles = {t: st[0].role for t, st in runs if t.strip()}
        self.assertEqual(roles["{Fare}"], "kinds-data")
        self.assertEqual(roles["=>"], "syntax-operator")
        self.assertEqual(roles["×3"], "syntax-cardinality")

    def test_live_toggle(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "ecs.sigil"
            p.write_text(ECS)
            st = view.ViewState(p, do_lint=False)
            st.reload(force=True)
            st.key("t")
            text = "\n".join("".join(t for t, _ in r) for r in st.frame(120, 40))
            self.assertIn("├─& {Transform}", text)
            self.assertIn("· tree ·", text)


if __name__ == "__main__":
    unittest.main()
