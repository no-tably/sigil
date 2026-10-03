"""Tests for view.py — the constructs the drawings carry beyond plain flows.

Covers (each in the graph view and the tree + wires view):
  1. control blocks: titled frames (graph) and gutter brackets (tree) for loop /
     parallel / branch / scope / owns, nested blocks nested, a branch's ◇
     decision node and arm chips / arm labels, the `!>` compensation after `}`;
  2. joins: a join bar labelled `&` / `&?` / `/` (graph), join-marked taps (tree);
     a `*>` broadcast's target list is not a join;
  3. the permission graph behind `a` / --access: r / w / b heads and lanes, the
     `1w` / `Nw` writer badge;
  4. arrow kinds told apart without colour: `!>`'s ✖ head, the trigger's ╍╏
     stroke, `?>` beside `->` on one pair, the `<->` lane's ▶;
  5. modifiers behind `m` / --mods: chips on edges (after the payload) and after
     node labels, relocated with the payloads when the drawing must fit;
  6. `--- section ---` dividers and the `#!mode` in the status bar;
  7. alias nodes drawn `[[name]]` in their own theme colour;
  8. Mermaid ids unique per expansion path.
  9. a stream's shadowed box (┒┃┛) and ` ≋` tree mark; a generic role's stacked
     box (╖║╜) and its generics in ‹ › — told apart from `~`'s heavy box.

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


view = _load("sigil_view", "view.py")
render = view.render
COVERAGE = _DIR / "tests" / "fixtures" / "coverage.sigil"


def graph(text: str, **kw) -> str:
    rows, _w = view.compose(render.parse_document(text), kw.pop("depth", 1),
                            kw.pop("payloads", False), **kw)
    return "\n".join(view.ansi(r, False) for r in rows)


def tree(text: str, **kw) -> str:
    rows, _w = view.compose_tree(render.parse_document(text), kw.pop("depth", 1), **kw)
    return "\n".join(view.ansi(r, False) for r in rows)


def line_with(out: str, needle: str) -> str:
    return next(ln for ln in out.splitlines() if needle in ln)


BLOCKS = """#!sketch
loop @while |Q|.nonempty {
  [Worker] -> |Obs|
}
parallel @all {
  [Api] -> [Inventory] : reserve => {Hold}
  [Api] -> [Fraud]
}
       !> [Inventory] : release({Hold})
checkout {
  [Cart] -> [Api]
}
[Handler] @owns |Conn| {
  [Handler] -> |Conn|
}
branch on {Request}.kind {
  read  => [Reader] -> |DB|
  write => [Writer] -> |DB|
  _     => <Rejected>
}
"""


class TestBlocks(unittest.TestCase):
    def test_graph_frames_carry_their_titles(self):
        out = graph(BLOCKS)
        for title in ("╭╌ ↺ loop @while |Q|.nonempty ╌", "╭╌ ∥ parallel @all ╌",
                      "╭╌ □ checkout ╌", "╭╌ □ [Handler] @owns |Conn| ╌",
                      "╭╌ ◇ branch on {Request}.kind ╌"):
            self.assertIn(title, out)
        self.assertEqual(out.count("╭╌"), 5)
        # a member sits inside its frame: the box row is between the frame's sides
        self.assertRegex(line_with(out, "│ [Worker] │"), r"╎\s+│ \[Worker\] │\s+╎")

    def test_block_flows_leave_the_main_layout(self):
        out = graph(BLOCKS)
        self.assertEqual(out.count("[Reader]"), 1)          # only in the branch frame
        self.assertEqual(out.count("[Obs]"), 0)
        self.assertEqual(out.count("|Obs|"), 1)

    def test_branch_decision_node_and_arm_chips(self):
        out = graph(BLOCKS)
        self.assertIn("│ ◇ {Request}.kind │", out)
        self.assertRegex(out, r"╱─+╲")                     # the decision node's top
        for arm in ("┆ read ┆", "┆ write ┆", "┆ _ ┆"):
            self.assertIn(arm, out)
        # the arms are choices: no `=>` chain from one arm into the next
        self.assertNotIn("━", line_with(out, "[Reader]"))

    def test_compensation_hangs_from_the_subject_inside_the_frame(self):
        out = graph(BLOCKS)
        self.assertEqual(out.count("[Inventory]"), 1)       # drawn once, in the frame
        # `!> [Inventory]` after `}`: its own stroke beside the `->`, headed ✖
        self.assertRegex(out, r"╎[^╎]*✖ ▼[^╎]*╎")

    def test_nested_blocks_nest(self):
        doc = "parallel @all {\n  [A] -> [C]\n  loop @times 2 {\n    [A] -> [B]\n  }\n}\n"
        out = graph(doc)
        self.assertRegex(line_with(out, "↺ loop @times 2"), r"^╎ ╭╌ ↺ loop @times 2")
        t = tree(doc)
        self.assertIn("┌─── ∥ parallel @all", t)
        self.assertRegex(line_with(t, "↺ loop @times 2"), r"^│ ├─ ↺ loop @times 2")
        self.assertRegex(line_with(t, "[B]"), r"^└─└─ \[B\]")

    def test_tree_brackets_headers_and_arm_labels(self):
        for out in (tree(BLOCKS), tree(BLOCKS, width=30, payloads=True)):
            for entry, arm in (("[Reader]", "‹read›"), ("[Writer]", "‹write›")):
                self.assertIn(f"{entry} {arm}", out)
        out = tree(BLOCKS)
        self.assertRegex(out, r"┌─+ ↺ loop @while \|Q\|\.nonempty")
        self.assertRegex(line_with(out, "|Obs|"), r"^[│ ]*└─+ \|Obs\|")
        self.assertIn("◇ branch on {Request}.kind", out)
        for entry, arm in (("[Reader]", "‹read›"), ("[Writer]", "‹write›"),
                           ("<Rejected>", "‹_›")):
            self.assertIn(f"{entry} {arm}", out)

    def test_no_blocks_no_gutter(self):
        out = tree("[A] -> [B]\n")
        self.assertTrue(out.startswith("[A]"))


class TestJoins(unittest.TestCase):
    DOC = ("[Api] -> [Stock] & [Tax]\n[Api] -> [PspA] &? [PspB]\n"
           "[Api] => {Resp} / {Err}\n[X] & [Y] -> [Z]\n")

    def test_graph_join_bars_and_labels(self):
        out = graph(self.DOC)
        self.assertRegex(out, r"━[┯┷┿━]+━ &(?!\?)")
        self.assertRegex(out, r"━[┯┷┿━]+━ &\?")
        self.assertRegex(out, r"━[┳┻╋━]+━ /")              # `=>` joins are heavy
        self.assertEqual(len(re.findall(r"━ &(?!\?)", out)), 2)   # the fork and the fan-in

    def test_tree_marks_joined_taps(self):
        out = tree(self.DOC)
        self.assertIn("[Stock] ◀&", out)
        self.assertIn("[Tax] ◀&─", out)
        self.assertIn("[PspA] ◀&?", out)
        self.assertIn("{Resp} ◀/", out)
        self.assertRegex(line_with(out, "[X]"), r"\[X\] ─&")

    def test_broadcast_target_list_is_not_a_join(self):
        doc = "<Go> *> [A] & [B]\n"
        self.assertNotIn(" &", graph(doc))
        self.assertNotIn("◀&", tree(doc))


class TestAccess(unittest.TestCase):
    DOC = ("[Boss]\n[Worker]\n[Helper]\n|Directives| @read(Worker) @write(Boss)\n"
           "|Results| @read(Boss) @write(Worker, Boss)\n[Helper] @borrow(read) |Results|\n")

    def test_off_by_default(self):
        self.assertNotIn("1w", graph(self.DOC))
        self.assertNotIn("1w", tree(self.DOC))

    def test_graph_heads_and_writer_badges(self):
        out = graph(self.DOC, access=True)
        self.assertIn("|Directives| 1w", out)
        self.assertIn("|Results| 2w", out)
        heads = "".join(re.findall(r"(?<=[┆ ])[rwb](?= |$)", out, re.M))
        for letter in "rwb":
            self.assertIn(letter, heads)
        self.assertIn("┆", out)                              # dotted access strokes

    def test_tree_access_lanes(self):
        out = tree(self.DOC, access=True)
        self.assertRegex(line_with(out, "[Boss]"), r"[┄─]w")
        self.assertRegex(line_with(out, "[Helper]"), r"┄b")
        self.assertIn("|Results| 2w ◀", out)

    def test_key_and_flag(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "acc.sigil"
            p.write_text(self.DOC)
            st = view.ViewState(p, do_lint=False)
            st.reload(force=True)
            before = "\n".join(view.ansi(r, False) for r in st._rows)
            self.assertTrue(st.key("a"))
            after = "\n".join(view.ansi(r, False) for r in st._rows)
            self.assertNotIn("2w", before)
            self.assertIn("2w", after)
            keys = "".join(t for t, _ in view.keys_legend(st))
            self.assertIn("a access", keys)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                view.once(p, 1, False, False, access=True)
            self.assertIn("2w", buf.getvalue())


class TestArrowKinds(unittest.TestCase):
    def test_error_has_its_own_head(self):
        out = graph("[A] !> [B]\n")
        self.assertIn("✖", out)
        self.assertNotIn("▼", out)
        self.assertIn("▼", graph("[A] -> [B]\n"))

    def test_trigger_stroke_is_not_the_async_one(self):
        doc = "[Pay] ~> <Paid>\n<Paid> -> {Order}\nstate {Order} {\n  Open -<Paid>-> Done\n}\n"
        out = graph(doc)
        self.assertRegex(out, "[╏╍]")
        t = tree(doc)
        self.assertIn("›", line_with(t, "[Pay]"))        # the emitter's lane
        self.assertIn("{Order} <Paid> ◀", t)             # named where it lands
        self.assertRegex(t, "[╏╍]")
        legend = "".join(t for t, _ in view.graph_legend())
        self.assertIn("╍╍▼ trigger", legend)
        self.assertIn("──✖ error", legend)

    def test_maybe_and_call_on_one_pair_stay_two_strokes(self):
        out = graph("[A] -> [B]\n[A] ?> [B]\n")
        self.assertIn("┆", out)                              # the dotted `?>`
        self.assertEqual(out.count("▼"), 2)                  # two heads into [B]
        self.assertEqual(graph("[A] -> [B]\n").count("▼"), 1)

    def test_bidirectional_lane_marker(self):
        out = tree("[A] <-> [B]\n")
        self.assertIn("▶", line_with(out, "[A]"))
        self.assertNotIn("●", out)
        self.assertIn("◀─▶ both ways", "".join(t for r in view.tree_legend() for t, _ in r))


class TestModifiers(unittest.TestCase):
    DOC = ("[Api] @sla(p99<200ms)\n(User) -> [Api] : {Cart} !\n"
           "[Api] -> [Scorer] : score({Cart}) @timeout(30s) ×3\n[Api] -> [Shard] ×4\n"
           "[Ingest] => *<Raw>^10k@drop\n")

    def test_off_by_default(self):
        for out in (graph(self.DOC, payloads=True), tree(self.DOC, payloads=True)):
            self.assertNotIn("@timeout", out)
            self.assertNotIn("@sla", out)
            self.assertNotIn("×4", out)

    def test_graph_chips_and_node_labels(self):
        out = graph(self.DOC, payloads=True, mods=True)
        self.assertIn("┆ score({Cart}) ┆ @timeout 30s ×3 ┆", out)
        self.assertIn("┆ {Cart} ┆ ! ┆", out)
        self.assertIn("┆ ×4 ┆", out)                         # a modifier-only chip
        self.assertIn("[Api] @sla p99<200ms", out)
        self.assertIn("*<Raw> ^10k drop", out)
        out = graph(self.DOC, mods=True)                     # without payloads
        self.assertIn("┆ @timeout 30s ×3 ┆", out)
        self.assertNotIn("score(", out)

    def test_tree_after_the_payload(self):
        out = tree(self.DOC, payloads=True, mods=True)
        self.assertIn("┆ score({Cart}) ┆ @timeout 30s ×3 ┆", line_with(out, "[Scorer]"))
        self.assertIn("[Api] @sla p99<200ms", out)
        out = tree(self.DOC, payloads=True, mods=True, width=40)    # margins relocated
        self.assertIn("[Api] @sla p99<200ms", out)
        self.assertIn("@timeout 30s ×3", out)

    def test_transition_mods_not_repeated_as_payload(self):
        doc = "state {Order} {\n  Open -<Paid>-> Settled @timeout(1d)\n}\n"
        out = graph(doc, depth=1, payloads=True, mods=True)
        self.assertEqual(out.count("@timeout"), 1)

    def test_relocated_with_payloads_when_fitting(self):
        rows, w = view.compose(render.parse_document(self.DOC), 1, True, mods=True, width=40)
        out = "\n".join(view.ansi(r, False) for r in rows)
        self.assertIn("┆a┆", out)                            # the chip's letter in the panel
        self.assertIn("@timeout 30s ×3", out)                # and its modifiers beside it

    def test_key(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "m.sigil"
            p.write_text(self.DOC)
            st = view.ViewState(p, do_lint=False)
            st.reload(force=True)
            st.key("m")
            self.assertIn("@sla", "\n".join(view.ansi(r, False) for r in st._rows))
            self.assertIn("m mods", "".join(t for t, _ in view.keys_legend(st)))


class TestSections(unittest.TestCase):
    DOC = ("#!craft\n# shop\n--- L1: Shop ---\n[A] -> [B]\n# kept for later\n[Lone]\n"
           "--- L2: Payments ---\n[Solo]\n[P] -> [Q]\n")

    def test_graph_dividers_group_the_flows(self):
        out = graph(self.DOC)
        lines = out.splitlines()
        shop = next(i for i, ln in enumerate(lines) if ln.startswith("── L1 · Shop ─"))
        pay = next(i for i, ln in enumerate(lines) if ln.startswith("── L2 · Payments ─"))
        between = "\n".join(lines[shop:pay])
        self.assertIn("[A]", between)
        self.assertIn("[Lone]", between)
        self.assertNotIn("[P]", between)
        self.assertIn("[P]", "\n".join(lines[pay:]))
        self.assertIn("[Solo]", "\n".join(lines[pay:]))     # declared as L2 opens

    def test_tree_divider_before_the_first_unit(self):
        lines = tree(self.DOC).splitlines()
        k = next(i for i, ln in enumerate(lines) if "── L2 · Payments ──" in ln)
        self.assertTrue(lines[k + 1].startswith("[Solo]"))
        self.assertTrue(lines[0].startswith("── L1 · Shop ──"))

    def test_no_sections_no_divider(self):
        self.assertFalse(any(ln.startswith("── ") for ln in graph("[A] -> [B]\n").splitlines()))
        self.assertFalse(any(ln.startswith("── ") for ln in tree("[A] -> [B]\n").splitlines()))

    def test_mode_in_status_bar_and_summary(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.sigil"
            p.write_text(self.DOC)
            st = view.ViewState(p, do_lint=False)
            st.reload(force=True)
            self.assertIn("#!craft", "".join(t for t, _ in st._bar(120)))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                view.once(p, 1, False, False)
            self.assertIn("· #!craft", buf.getvalue().splitlines()[-1])


class TestAlias(unittest.TestCase):
    DOC = "walk := [Node] -> walk(.children)\n"

    def test_alias_brackets_in_both_views(self):
        self.assertIn("│ [[walk]] ▾ │", graph(self.DOC))
        self.assertIn("[[walk]]", tree(self.DOC))

    def test_alias_colour_is_a_theme_role(self):
        n = render.parse_document(self.DOC).nodes["walk_alias"]
        runs = view.label_runs(n)
        self.assertEqual([t for t, _ in runs], ["[[", "walk", "]]"])
        self.assertEqual(runs[0][1][0].role, "kinds-alias")


class TestThemeRoles(unittest.TestCase):
    def test_new_roles_are_in_the_theme(self):
        text = (_DIR / "themes" / "sigil.yaml").read_text()
        for key in ("alias:", "arm:", "access:", "frame:", "section:", "mode:"):
            self.assertIn("  " + key, text)
        self.assertEqual(view.FRAME_STYLE[0].role, "ui-frame")
        self.assertEqual(view.SECTION_STYLE[0].role, "ui-section")
        self.assertEqual(view.EDGE_COLOR["access"].role, "edges-access")
        self.assertEqual(view.EDGE_COLOR["arm"].role, "edges-arm")


class TestMermaidIds(unittest.TestCase):
    def test_same_name_in_two_graphs_gets_two_ids(self):
        doc = ("[Handler] -> [X]\n[Core] := {\n  [Router] -> [Handler]\n}\n"
               "--- L3: [Handler] ---\n[Handler] := {\n  [In] -> [Out]\n}\n")
        out = render.render(doc, depth=99)
        defined = re.findall(r"^\s*(?:subgraph )?([A-Za-z0-9_]+)[\[\(\{>]", out, re.M)
        self.assertEqual(len(defined), len(set(defined)), defined)
        self.assertIn("Core_service__Handler_service", out)
        self.assertIn("Router_service --> Core_service__Handler_service", out)

    def test_coverage_fixture_ids_unique(self):
        out = render.render(COVERAGE.read_text(), depth=99)
        defined = re.findall(r"^\s*(?:subgraph )?([A-Za-z0-9_]+)[\[\(\{>]", out, re.M)
        self.assertEqual(len(defined), len(set(defined)))

    def test_triggers_follow_renamed_states(self):
        doc = ("[Shop] := {\n  [Pay] ~> <Paid>\n  {Order}\n}\n<Paid> -> {Order}\n"
               "state {Order} {\n  Open -<Paid>-> Done\n}\n")
        out = render.render(doc, depth=99)
        for m in re.finditer(r"(\w+) -\. \"triggers\" \.-> (\w+)", out):
            for nid in m.groups():
                self.assertRegex(out, r"(?m)^\s*(?:subgraph )?" + nid + r"[\[\(\{>]")


class TestStreamsAndRoles(unittest.TestCase):
    DOC = ("[Ingest] => *<Raw>\n*<Raw> -> [Parse]\n~{Session}\n[Worker<N>] -> [Api]\n"
           "[Cache<K,V>]\n|Tasks| @read(Worker)\n")

    @staticmethod
    def box(out: str, label: str) -> list:
        """The three rows of the box drawn around `label`."""
        lines = out.splitlines()
        y = next(i for i, ln in enumerate(lines) if f" {label} " in ln)
        x = lines[y].index(f" {label} ") - 1
        return [ln[x:x + len(label) + 4] for ln in lines[y - 1:y + 2]]

    def test_graph_shadows_a_stream_box(self):
        out = graph(self.DOC)
        self.assertEqual(self.box(out, "*<Raw>"), ["┌────────┒", "│ *<Raw> ┃", "┕━━━━━━━━┛"])
        self.assertEqual(self.box(out, "~{Session}")[1], "┃ ~{Session} ┃")   # `~` stays heavy

    def test_graph_stacks_a_role_box(self):
        out = graph(self.DOC)
        self.assertEqual(self.box(out, "[Worker‹N›]"),
                         ["┌─────────────╖", "│ [Worker‹N›] ║", "└─────────────╜"])
        self.assertEqual(self.box(out, "[Cache<K,V>]")[1], "│ [Cache<K,V>] │")   # a type

    def test_self_call_stub_leaves_a_role_box(self):
        out = graph("[Worker<N>] -> run()\n|Q| @write(Worker)\n", payloads=True)
        self.assertIn("╢", out)

    def test_tree_marks_streams_and_roles(self):
        out = tree(self.DOC)
        self.assertIn("[Parse] *<Raw> ≋", out)       # an event landed on its target row
        self.assertIn("[Worker‹N›]", out)
        out = tree(self.DOC, events="nodes")
        self.assertIn("*<Raw> ≋", out)

    def test_tree_legend_lists_the_marks_drawn(self):
        marks = view.drawn_call_marks(render.parse_document(self.DOC), 1, False)
        text = "".join(t for r in view.tree_legend(calls=marks) for t, _ in r)
        self.assertIn("≋ stream", text)
        self.assertIn("[R‹N›] role: N members", text)
        plain = view.drawn_call_marks(render.parse_document("[A] -> [B]\n"), 1, False)
        text = "".join(t for r in view.tree_legend(calls=plain) for t, _ in r)
        self.assertNotIn("stream", text)


class TestCoverageFixture(unittest.TestCase):
    def test_every_toggle_draws_the_fixture(self):
        g = render.parse_document(COVERAGE.read_text())
        for kw in ({}, {"access": True, "mods": True}, {"width": 80, "mods": True}):
            rows, w = view.compose(g, 99, True, "markers", True, **kw)
            self.assertTrue(rows)
            rows, w = view.compose_tree(g, 99, notes="callouts", payloads=True, **kw)
            self.assertTrue(rows)
            if "width" in kw:
                self.assertLessEqual(w, max(kw["width"], w))


if __name__ == "__main__":
    unittest.main()


class TestArrowheadColour(unittest.TestCase):
    def test_target_head_takes_the_nearest_incoming_lane_colour(self):
        # [App] receives a call from (Rider) and a !> failure path: its ◀ must be
        # the colour of the lane whose stroke runs into it, not the last drawn.
        doc = "(Rider) -> [App]\n[Pay] !> [App]\n[X] -> [Pay]\n"
        rows, _ = view.compose_tree(view.render.parse_document(doc), 1)
        for row in rows:
            if not "".join(t for t, _ in row).startswith("[App]"):
                continue
            cells = [(ch, st) for t, st in row for ch in t]
            x = next(i for i, (ch, _st) in enumerate(cells) if ch == "◀")
            run = next(st for ch, st in cells[x + 1:] if ch in "─━╌┄═")
            self.assertEqual(cells[x][1][0], run[0])
            return
        self.fail("no [App] row")
