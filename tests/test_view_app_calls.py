"""The call marks the app hands the tree legend (view.drawn_call_marks).

Only the marks a drawing actually shows are listed: an ordinary payload op
(`: charge(total)`) is no call mark; `↺` / `↻` / `⇱` follow the call wires and
external targets; `↩` needs a returning call and payloads on.

Run:  python3 -m unittest discover tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import view  # noqa: E402


def marks(text: str, payloads: bool = False, depth: int = 1) -> frozenset:
    return view.drawn_call_marks(view.render.parse_document(text), depth, payloads)


class TestDrawnCallMarks(unittest.TestCase):
    def test_no_graph_has_no_marks(self):
        self.assertEqual(view.drawn_call_marks(None, 1, True), frozenset())

    def test_payload_op_is_no_call_mark(self):
        self.assertEqual(marks("[Shop] -> [Pay] : charge(total)\n", payloads=True),
                         frozenset())

    def test_self_call(self):
        self.assertEqual(marks("[Planner] -> plan({Seed})\n"), {"↺"})

    def test_recursion(self):
        self.assertEqual(marks("[Walker] -> [Walker]\n"), {"↻"})

    def test_external_op(self):
        self.assertEqual(marks("[Crawler] -> (Web) : op http.get(${url})\n"), {"⇱"})

    def test_return_only_with_payloads(self):
        doc = "[S] -> plan({Seed}) => {Plan}\n"
        self.assertNotIn("↩", marks(doc))
        self.assertIn("↩", marks(doc, payloads=True))


if __name__ == "__main__":
    unittest.main()
