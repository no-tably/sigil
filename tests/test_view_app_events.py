"""The events toggle in the app (view.py): `v` and `--events land|nodes`.

Each view keeps its own events mode (defaults: tree land, graph nodes); `v` flips
only the active view's; `--events` starts both views in the given mode; the keys
row names the active view's mode.
"""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import view  # noqa: E402

DOC = "[Shop] -> <Paid>\n<Paid> -> [Mailer]\n"


def text(rows):
    return "\n".join(view.ansi(r, False) for r in rows)


def keys(st):
    return "".join(t for t, _ in view.keys_legend(st))


class TestEventsToggle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ev.sigil"
        self.path.write_text(DOC)

    def tearDown(self):
        self.tmp.cleanup()

    def state(self, **kw):
        st = view.ViewState(self.path, do_lint=False, **kw)
        st.reload(force=True)
        return st

    def test_defaults_per_view(self):
        st = self.state()
        self.assertEqual(st.events, {"tree": "land", "graph": "nodes"})
        self.assertEqual(st.events_mode, "nodes")
        self.assertEqual(self.state(tree=True).events_mode, "land")

    def test_flag_sets_both_views(self):
        st = self.state(events="land")
        self.assertEqual(st.events, {"tree": "land", "graph": "land"})

    def test_v_flips_only_the_active_view(self):
        st = self.state()
        before = text(st._rows)
        self.assertTrue(st.key("v"))
        self.assertEqual(st.events, {"tree": "land", "graph": "land"})
        self.assertNotEqual(before, text(st._rows))
        st.key("t")                                  # the tree keeps its own mode
        self.assertEqual(st.events_mode, "land")
        st.key("v")
        self.assertEqual(st.events, {"tree": "nodes", "graph": "land"})
        st.key("t")
        st.key("v")
        self.assertEqual(st.events, {"tree": "nodes", "graph": "nodes"})

    def test_mode_reaches_the_drawing(self):
        for tree in (False, True):
            drawn = {m: text(self.state(tree=tree, events=m)._rows) for m in view.EVENT_MODES}
            self.assertNotEqual(drawn["land"], drawn["nodes"], f"tree={tree}")

    def test_keys_row_names_the_mode(self):
        st = self.state()
        self.assertIn("v events:nodes", keys(st))
        st.key("v")
        self.assertIn("v events:land", keys(st))
        st.key("t")
        self.assertIn("v events:land", keys(st))

    def test_frame_stays_terminal_sized(self):
        st = self.state()
        st.key("v")
        frame = st.frame(60, 20)
        self.assertEqual(len(frame), 20)
        self.assertTrue(all(view.row_len(r) <= 60 for r in frame))

    def test_once_default_and_flag(self):
        def once(**kw):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                view.once(self.path, 1, False, False, **kw)
            return buf.getvalue()
        self.assertEqual(once(), once(events="nodes"))                 # graph default
        self.assertEqual(once(tree=True), once(tree=True, events="land"))
        self.assertNotEqual(once(), once(events="land"))
        self.assertNotEqual(once(tree=True), once(tree=True, events="nodes"))

    def test_once_tree_legend_follows_the_mode(self):
        def legend(events):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                view.once(self.path, 1, False, False, tree=True, events=events)
            return buf.getvalue()
        self.assertIn("›─ emits", legend("land"))
        self.assertNotIn("›─", legend("nodes"))
        self.assertNotIn("emits", legend("nodes"))

    def test_live_legends_follow_the_mode(self):
        def footer(st):
            return text(st._footer_rows(200))
        st = self.state()                            # graph, nodes
        self.assertNotIn("emits", footer(st))
        st.key("v")                                  # graph, land
        self.assertIn("<E> emits", footer(st))
        st.key("t")                                  # tree, land
        self.assertIn("›─ emits", footer(st))
        st.key("v")                                  # tree, nodes
        self.assertNotIn("emits", footer(st))


if __name__ == "__main__":
    unittest.main()
