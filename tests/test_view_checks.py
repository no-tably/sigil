"""The checks overlay (view.py `c`, --checks): check.py's findings mapped onto the
Scene each view draws, marked in both views in the theme's ui.error / ui.warn
roles only (acknowledged findings dimmed), the panel with each finding's
question, the legend and keys rows, and `--once --checks`.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import view  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# Four findings in spec: capacity-mismatch (info, on [API]), retry-without-
# idempotency (warn, on the charge wire), orphan-event (warn, on the event) and
# an acknowledged shared-writable-store (info, a guess, on |Orders|).
DOC = """#!spec
(User) -> [API] : order()
[API] -> [Payments] : charge(total) ×3 @timeout(2s)
       !> <PaymentFailed>
[API] -> |Orders| : write(order)   # accepts: shared-writable-store — upserts on order id
[Worker] -> |Orders| : write(job)
"""

# The roles an overlay may colour with (its own runs and the strokes it restyles).
CHECK_ROLES = {"ui-error", "ui-warn", "muted:ui-error", "muted:ui-warn"}


def plain(rows):
    return ["".join(t for t, _ in r) for r in rows]


def roles(rows) -> set:
    """The theme roles of every run's foreground colour."""
    return {getattr(st[0], "role", "") for r in rows for _t, st in r if st and st[0]}


def runs_with(rows, text: str) -> list:
    return [(t, st) for r in rows for t, st in r if text in t]


class _Doc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = view.kit.render.parse_document(DOC)
        cls.report = view.run_checks(DOC)
        cls.overlay = view.ChecksOverlay(cls.graph, cls.report, view.checks_summary(cls.report))

    def draw(self, tree: bool, checks: bool, events: str | None = None):
        events = events or view.DEFAULT_EVENTS[view.view_name(tree)]
        options = view.scene.SceneOptions(events, True, False, 1)
        rows, _w = view.compose_view(self.graph, tree, depth=1, payloads=False, notes="off",
                                     triggers=True, spaced=True, width=None, access=False,
                                     mods=False, events=events,
                                     checks=self.overlay.marks(options) if checks else None)
        return rows


class TestEntries(_Doc):
    def test_numbered_shown_then_acknowledged(self):
        marks = [e.mark for e in self.overlay.entries]
        self.assertEqual([m.number for m in marks], [1, 2, 3, 4])
        self.assertEqual([(m.severity, m.acked) for m in marks],
                         [("info", False), ("warn", False), ("warn", False), ("info", True)])
        names = [e.finding.rule.name for e in self.overlay.entries]
        self.assertEqual(names, ["capacity-mismatch", "retry-without-idempotency",
                                 "orphan-event", "shared-writable-store"])

    def test_marks_land_on_nodes_and_wires(self):
        for tree in (False, True):
            events = view.DEFAULT_EVENTS[view.view_name(tree)]
            m = self.overlay.marks(view.scene.SceneOptions(events, True, False, 1))
            self.assertEqual({nid: [k.number for k in ms] for nid, ms in m.nodes.items()},
                             {"API_service": [1], "PaymentFailed_event": [3],
                              "Orders_store": [4]})
            self.assertEqual({key: [k.number for k in ms] for key, ms in m.by_key().items()},
                             {("API_service", "Payments_service", "->"): [2]})

    def test_anchors_with_nothing_drawn_are_listed_only(self):
        view_scene = view.scene.build_scene(self.graph, events="nodes")
        for anchor in (("block", "3"), ("document", "budget"), ("limit", "depth")):
            self.assertEqual(view.finding_targets(anchor, view_scene, {}, {}), (set(), set()))

    def test_a_line_anchor_marks_the_wires_written_there(self):
        view_scene = view.scene.build_scene(self.graph, events="nodes")
        _nodes, wires = view.finding_targets(("line", 6), view_scene, {}, {})
        self.assertEqual({w[:3] for w in wires}, {("Worker_service", "Orders_store", "->")})


class TestOverlayRows(_Doc):
    def test_off_is_the_plain_drawing(self):
        for tree in (False, True):
            off = self.draw(tree, checks=False)
            self.assertFalse(any(g in "".join(plain(off)) for g in ("▲", "△", "◆", "✓")))

    def test_on_marks_each_finding_in_both_views(self):
        for tree in (False, True):
            with self.subTest(tree=tree):
                on = "\n".join(plain(self.draw(tree, checks=True)))
                for mark in ("[API] △1", "<PaymentFailed> ▲3", "|Orders| ✓4", "▲2"):
                    self.assertIn(mark, on)

    def test_overlay_colours_are_theme_check_roles_only(self):
        for tree in (False, True):
            with self.subTest(tree=tree):
                off, on = self.draw(tree, False), self.draw(tree, True)
                added = roles(on) - roles(off)
                self.assertTrue(added)
                self.assertLessEqual(added, CHECK_ROLES)
                for glyph in ("△1", "▲2", "▲3", "✓4"):
                    for _t, st in runs_with(on, glyph):
                        self.assertIn(st[0].role, CHECK_ROLES)

    def test_the_marked_wire_and_box_take_the_warn_role(self):
        on = self.draw(False, True)
        warn = [st for r in on for t, st in r if st and getattr(st[0], "role", "") == "ui-warn"
                and set(t) & set("─│┌┐└┘▼")]
        self.assertTrue(warn)                       # the charge stroke, the event's border

    def test_acknowledged_is_dimmed(self):
        for tree in (False, True):
            ((_t, st),) = runs_with(self.draw(tree, True), "✓4")
            self.assertTrue(st[0].role.startswith("muted:"))
            self.assertFalse(st[2])
            ((_t, st),) = runs_with(self.draw(tree, True), "▲3")
            self.assertEqual((st[0].role, st[2]), ("ui-warn", True))

    def test_another_theme_recolours_the_overlay(self):
        try:
            view.kit.apply_theme({"ui": {"warn": "#123456"}})
            ((_t, st),) = runs_with(self.draw(False, True), "▲3")
            self.assertEqual((str(st[0]), st[0].role), ("#123456", "ui-warn"))
        finally:
            view.kit.apply_theme(view.kit.themes.load(None) if view.kit.themes else {})


class TestPanel(_Doc):
    def test_each_finding_asks_its_question(self):
        text = "\n".join(plain(self.overlay.panel(200)))
        self.assertIn("sigil check (spec, k=2)", text)
        self.assertIn("▲2 3:retry-without-idempotency `charge` is retried ×3. Is it idempotent", text)
        self.assertIn("✓4 5:shared-writable-store accepted: upserts on order id", text)

    def test_wraps_and_limits(self):
        rows = self.overlay.panel(40)
        self.assertTrue(all(view.kit.row_len(r) <= 40 for r in rows[1:]))
        short = self.overlay.panel(40, limit=4)
        self.assertLessEqual(len(short), 4)
        self.assertTrue(plain(short)[-1].startswith("… "))
        self.assertTrue(plain(short)[-1].endswith("more (check.py)"))

    def test_acknowledged_text_is_dimmed(self):
        rows = self.overlay.panel(200)
        row = next(r for r in rows if r and r[0][0] == "✓4")
        self.assertEqual(row[1][1][0], view.kit.GREY["dim"])

    def test_legend_lists_the_marks_in_check_roles(self):
        legend = view.checks_legend()
        text = "".join(t for t, _ in legend)
        for word in ("◆N error", "▲N warning", "△N info", "✓N acknowledged"):
            self.assertIn(word, text)
        marks = [st for t, st in legend if t[:1] in "◆▲△✓"]
        self.assertTrue(marks)
        self.assertTrue(all(st[0].role in CHECK_ROLES for st in marks))


class TestLiveView(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "doc.sigil"
        self.path.write_text(DOC)
        self.st = view.ViewState(self.path, do_lint=False)
        self.st.reload(force=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_c_toggles_the_overlay_legend_and_panel(self):
        before = "\n".join(plain(self.st.frame(100, 60)))
        self.assertNotIn("checks ◆N", before)
        self.assertTrue(self.st.key("c"))
        on = "\n".join(plain(self.st.frame(100, 60)))
        self.assertIn("checks ◆N error", on)
        self.assertIn("[API] △1", on)
        self.assertIn("2:capacity-mismatch", on)
        self.st.key("2")                                 # the tree view marks it too
        self.assertIn("[API] △1", "\n".join(plain(self.st.frame(100, 60))))
        self.st.key("3")                                 # and the flow view
        self.assertIn("[API] △1", "\n".join(plain(self.st.frame(100, 60))))
        self.st.key("c")
        self.assertNotIn("△1", "\n".join(plain(self.st.frame(100, 60))))

    def test_keys_row_shows_checks_and_z_centres(self):
        row = "".join(t for t, _ in view.keys_legend(self.st))
        self.assertIn("c checks", row)
        self.assertIn("z centre", row)
        self.st.key("c")
        on = view.keys_legend(self.st)
        i = next(i for i, (t, _s) in enumerate(on) if t == "c")
        self.assertTrue(on[i + 1][1][2])                 # bright while on
        self.st.key("z")
        self.assertEqual(self.st._place, "centre")

    def test_reload_rechecks(self):
        self.st.key("c")
        self.st.frame(100, 60)
        self.path.write_text(DOC.replace("   # accepts: shared-writable-store — upserts on order id",
                                         ""))
        self.st.reload(force=True)
        text = "\n".join(plain(self.st.frame(100, 60)))
        self.assertNotIn("✓4", text)
        self.assertIn("shared-writable-store", text)

    def test_a_checker_failure_is_a_footer_row(self):
        original = view.run_checks

        def broken(_text, _dialect=None):
            raise view.ChecksUnavailable("no checker here")

        view.run_checks = broken
        try:
            self.st.key("c")
            text = "\n".join(plain(self.st.frame(100, 40)))
        finally:
            view.run_checks = original
        self.assertIn("checks failed: ChecksUnavailable: no checker here", text)
        self.assertEqual(len(self.st.frame(100, 40)), 40)

    def test_frames_stay_terminal_sized(self):
        self.st.key("c")
        for tree in (False, True):
            self.st.tree = tree
            self.st._recompose()
            for cols, rows in ((40, 10), (80, 24), (30, 5)):
                frame = self.st.frame(cols, rows)
                self.assertEqual(len(frame), rows)
                self.assertTrue(all(view.row_len(r) <= cols for r in frame))


class TestOnce(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "doc.sigil"
        self.path.write_text(DOC)

    def tearDown(self):
        self.tmp.cleanup()

    def run_view(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "view.py"), str(self.path), "--once",
                               *args], capture_output=True, text=True)

    def test_checks_flag_marks_lists_and_keeps_lints_status(self):
        for extra in ((), ("--tree",)):
            r = self.run_view("--checks", *extra)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("[API] △1", r.stdout)
            self.assertIn("checks ◆N error", r.stdout)
            self.assertIn("sigil check (spec, k=2): 3 finding(s)", r.stdout)
            self.assertIn("✓4 5:shared-writable-store accepted: upserts on order id", r.stdout)

    def test_without_the_flag_nothing_changes(self):
        r = self.run_view()
        self.assertNotIn("△1", r.stdout)
        self.assertNotIn("sigil check", r.stdout)


if __name__ == "__main__":
    unittest.main()
