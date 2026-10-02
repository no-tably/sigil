"""Tests for the graph view's calls (view_graph.py; design note P2 "executions") —
what a call runs, what comes back, and what leaves the system, drawn from the
Scene's Call (scene.py).

Covers:
  1. a call's chip: its op and `↩` return (never ` => `), `⇱` and no `op `
     keyword for an external op, the far node of an external call marked `⇱`;
  2. self-calls (the `=>` edge a target op returns along marked `↩`): the box mark (↺ self-call, ↻ recursion, ⇱ host op only; once
     per box), and with payloads a stub chip under the box's right side per
     self-call, stacked in written order; none without payloads;
  3. recursion through an alias's body (`follow := [C] -> follow(.links)`);
  4. several calls into one target: a chip each, the `!>` one ending in ✖ and
     the fail colour;
  5. stubs in fit mode become marker letters listed in the panel; modifiers
     follow the op on a stub;
  6. a stub never runs into a neighbouring box; isolated nodes carry theirs;
  7. the fixture and the showcase keep every mark with colour off;
  8. graph_legend's call marks.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import re
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

FIXTURE = ROOT / "tests" / "fixtures" / "executions.sigil"
SHOWCASE = ROOT / "site" / "examples" / "05-executions.sigil"


def compose(text: str, payloads: bool = True, mods: bool = False, depth: int = 1,
            width: int | None = None):
    g = kit.render.parse_document(text)
    rows, _w = vgraph.compose(g, depth, payloads, "off", True, width, False, mods)
    return rows


def plain(rows) -> str:
    return "\n".join("".join(t for t, _ in r) for r in rows)


def line_with(text: str, needle: str) -> str:
    return next(ln for ln in text.splitlines() if needle in ln)


class CallChips(unittest.TestCase):
    def test_a_call_chip_shows_its_return(self):
        out = plain(compose("[S] -> [C] : crawl({Plan}) => {Site}\n"))
        self.assertIn("┆ crawl({Plan}) ↩ {Site} ┆", out)
        self.assertNotIn("=>", out)

    def test_an_external_op_is_marked_on_the_chip_and_the_far_node(self):
        out = plain(compose("[F] -> (Web) : op http.get(${url})\n"))
        self.assertIn("┆ ⇱ http.get(${url}) ┆", out)
        self.assertNotIn("op http", out)
        self.assertIn("(Web) ⇱", out)

    def test_the_far_node_mark_shows_without_payloads(self):
        out = plain(compose("[F] -> (Web) : op http.get(${url})\n", payloads=False))
        self.assertIn("(Web) ⇱", out)
        self.assertNotIn("http.get", out)

    def test_a_plain_payload_stays_as_written(self):
        out = plain(compose("[A] -> [B] : {Order}\n"))
        self.assertIn("┆ {Order} ┆", out)
        self.assertNotIn("↩", out)


class SelfCalls(unittest.TestCase):
    def test_a_target_op_hangs_a_stub_under_its_box(self):
        out = plain(compose("[S] -> plan({Seed}) => {Plan}\n"))
        self.assertIn("[S] ↺", out)
        stub = line_with(out, "└─●")
        self.assertIn("└─● ┆ ↺ plan({Seed}) ↩ {Plan} ┆", stub)
        box_right = line_with(out, "[S] ↺").index("│", line_with(out, "[S] ↺").index("]"))
        self.assertEqual(stub.index("└─●"), box_right)        # under its right side
        self.assertIn("┤", line_with(out, "└──"))             # the corner it leaves from

    def test_the_return_edge_is_marked_beside_its_head(self):
        out = plain(compose("[S] -> plan({Seed}) => {Plan}\n[S] -> [C]\n", payloads=False))
        self.assertEqual(out.count("↩"), 1)
        self.assertIn("▼ ↩", out)                            # on the `=>` edge, not [C]'s
        head = line_with(out, "▼ ↩").index("▼ ↩")
        box = line_with(out, "│ {Plan} │").index("│ {Plan} │")
        self.assertIn(head - box, range(len("│ {Plan} │")))   # the head into {Plan}

    def test_a_written_produce_is_no_return(self):
        out = plain(compose("[S] -> [C]\n[S] => {Plan}\n", payloads=False))
        self.assertNotIn("↩", out)

    def test_without_payloads_only_the_mark(self):
        out = plain(compose("[S] -> plan({Seed}) => {Plan}\n", payloads=False))
        self.assertIn("[S] ↺", out)
        self.assertNotIn("└─●", out)
        self.assertNotIn("plan(", out)

    def test_recursion_is_marked_and_carries_its_payload(self):
        out = plain(compose("[P] -> [Doc.walk] : {Doc}\n[Doc.walk] -> [Doc.walk] : child\n"))
        self.assertIn("[Doc.walk] ↻", out)
        self.assertIn("└─● ┆ ↻ child ┆", out)
        self.assertNotIn("↺", out)

    def test_an_external_target_op_reads_as_a_host_op_not_recursion(self):
        out = plain(compose("[N] -> op mail.send(${report})\n"))
        self.assertIn("[N] ⇱", out)
        self.assertIn("└─● ┆ ⇱ mail.send(${report}) ┆", out)       # isolated: still stubbed
        self.assertNotIn("↺", out)

    def test_several_self_calls_stack_under_one_mark(self):
        out = plain(compose("[W] -> a(x)\n[W] -> b(y)\n[W] -> [V]\n"))
        self.assertEqual(line_with(out, "[W]").count("↺"), 1)
        lines = out.splitlines()
        first = next(i for i, ln in enumerate(lines) if "├─● ┆ ↺ a(x) ┆" in ln)
        self.assertIn("└─● ┆ ↺ b(y) ┆", lines[first + 1])
        self.assertEqual(lines[first].index("├"), lines[first + 1].index("└"))

    def test_modifiers_follow_the_op_on_a_stub(self):
        out = plain(compose("[C] -> throttle(${host}) @deadline(2s)\n", mods=True))
        self.assertIn("┆ ↺ throttle(${host}) ┆ @deadline 2s ┆", out)

    def test_a_state_self_transition_keeps_the_plain_mark(self):
        doc = "state {Order} {\n  Open -<Touch>-> Open\n  Open -<Close>-> Closed\n}\n"
        out = plain(compose(doc, depth=2))
        self.assertIn("↺", out)
        self.assertNotIn("└─●", out)

    def test_a_stub_never_runs_into_its_neighbour(self):
        out = plain(compose("[A] -> plan(alpha, beta, gamma) => {P}\n[X] -> [B]\n[A] -> [B]\n"))
        stub = line_with(out, "└─●")
        self.assertIn("┆ ↺ plan(alpha, beta, gamma) ↩ {P} ┆", stub)
        for ln in out.splitlines():                         # every box still whole
            for m in re.finditer(r"[┌└]─+[┐┘┤]", ln):
                self.assertNotIn("●", m.group())


class AliasRecursion(unittest.TestCase):
    def test_a_target_op_named_after_its_alias_recurses(self):
        out = plain(compose("follow := [C] -> follow(.links)\n"))
        self.assertIn("[C] ↻", out)
        self.assertIn("┆ ↻ follow(.links) ┆", out)


class SeveralCalls(unittest.TestCase):
    DOC = ("[I] -> |Index| : reserve(${shard}) => {Lease}\n"
           "[I] -> |Index| : write({Doc}, {Lease})\n"
           "          !> |Index| : release({Lease})\n")

    def test_each_call_its_own_chip(self):
        out = plain(compose(self.DOC))
        for chip in ("reserve(${shard}) ↩ {Lease}", "write({Doc}, {Lease})", "release({Lease})"):
            self.assertEqual(out.count(f"┆ {chip} ┆"), 1, chip)
        self.assertEqual(out.count("✖"), 1)                 # release's `!>` head

    def test_the_failure_call_ends_in_the_fail_colour(self):
        rows = compose(self.DOC)
        heads = {st[0] for r in rows for t, st in r if st and "✖" in t}
        self.assertEqual(heads, {kit.EDGE_COLOR["!>"]})


class FitMode(unittest.TestCase):
    def test_stubs_become_letters_listed_in_the_panel(self):
        doc = ("[Scheduler] -> plan(alpha, beta, gamma, delta) => {Plan}\n"
               "[Scheduler] -> [Crawler] : crawl(alpha, beta, gamma, delta) => {Site}\n")
        out = plain(compose(doc, width=40))
        self.assertRegex(out, r"└─● ┆ [a-z] ┆")
        panel = " ".join(out.split())                       # the panel wraps its entries
        self.assertIn("↺ plan(alpha, beta, gamma, delta) ↩ {Plan}", panel)
        self.assertIn("crawl(alpha, beta, gamma, delta) ↩ {Site}", panel)


class Fixtures(unittest.TestCase):
    def draw(self, path: Path, depth: int = 99) -> str:
        return plain(compose(path.read_text(), depth=depth))

    def test_executions_fixture_marks(self):
        out = self.draw(FIXTURE)
        for label in ("[Doc.walk] ↻", "[Builder] ↻", "[Scheduler] ↺", "[Crawler] ↺",
                      "[Crawler] ↻", "[Notifier] ⇱", "(Web) ⇱"):
            self.assertIn(label, out)
        self.assertNotIn(" => ", out)
        for op in ("plan({Seed})", "throttle(${host})", "child", "follow(.links)",
                   "mail.send(${report})", "nest({Node})"):
            self.assertRegex(out, r"[├└]─● ┆ . " + re.escape(op))

    def test_showcase_marks(self):
        out = self.draw(SHOWCASE, depth=1)
        for label in ("[Scheduler] ↺", "[Crawler.follow] ↻", "(Web) ⇱"):
            self.assertIn(label, out)
        self.assertIn("┆ ⇱ http.get(${url}) ┆", out)
        self.assertEqual(out.count("┆ reserve(shard) ↩ {Lease} ┆"), 1)
        self.assertEqual(out.count("┆ write({Page}, {Lease}) ┆"), 1)


class Legend(unittest.TestCase):
    def test_call_marks_in_the_legend(self):
        text = "".join(t for t, _ in vgraph.graph_legend())
        for entry in ("↺ self-call", "↻ recursion", "⇱ host op"):
            self.assertIn(entry, text)
        self.assertNotIn("↩", text)
        self.assertIn("↩ returns", "".join(t for t, _ in vgraph.graph_legend(payloads=True)))


if __name__ == "__main__":
    unittest.main()
