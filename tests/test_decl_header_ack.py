"""An acknowledgement trailing a `#&` declaration line (patch-0.6.9 A1).

The rule: `#& name {   # accepts: rule — reason` reads as the acknowledgement it
is, the same as one written on the line above the declaration: it covers the
declaration (its whole block when it opens one; the line alone when it opens
none), accepts a finding there, and draws SGC001/002/003 like any other. Nothing
else about the line changes: its text, the acknowledgement included, stays the
declaration's body as written (so no export hash moves), any other comment on it
stays the dialect's (no note), and no comment-only line below continues it.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigil.analyse import check as ck  # noqa: E402
from sigil.analyse.rules import state as cs  # noqa: E402
from sigil.core.parse import parse_document  # noqa: E402
from sigil.core.statements import collect_comments  # noqa: E402


def probe(lines=(), **hit_kw):
    """A rule `probe` flagging the given lines."""
    def match(_doc):
        for n in lines:
            yield ck.Hit(n, f"probe at {n}", f"probe at {n}?", anchor=("line", n), **hit_kw)
    return ck.Rule("TST001", "probe", "binding", ask="Probe?", why="a test rule",
                   fix="nothing", match=match)


def run(text, *extra, mode=None, k=None):
    registry = ck.build_registry(ck.core_rules() + cs.rules(ck) + list(extra))
    return ck.check(textwrap.dedent(text).lstrip("\n"), mode=mode, k=k, registry=registry)


def found(report, rid) -> list:
    return [(f.line, f.hit.statement) for f in report.findings if f.rule.id == rid]


INLINE = "#!spec\n#& foo {   # accepts: probe — the block\n  a: b\n}\n\n[A] -> [B] : f()\n"
ABOVE = "#!spec\n# accepts: probe — the block\n#& foo {\n  a: b\n}\n\n[A] -> [B] : f()\n"


class InlineLikeAbove(unittest.TestCase):
    """The inline form reads as the line-above form does."""

    def test_accepts_a_finding_on_the_header(self):
        rep = run(INLINE, probe(lines=(2,), trace=True, k=2))
        self.assertEqual(found(rep, "SGC003"), [])
        self.assertEqual([f.line for f in rep.acknowledged], [2])

    def test_accepts_a_finding_inside_the_block(self):
        rep = run(INLINE, probe(lines=(3,)))
        self.assertEqual(found(rep, "SGC003"), [])
        self.assertEqual([f.line for f in rep.acknowledged], [3])

    def test_stale_outside_the_block(self):
        rep = run(INLINE, probe(lines=(6,)))
        self.assertEqual(found(rep, "SGC003"), [
            (2, "the acknowledgement covers no `probe` finding in its block")])
        self.assertEqual(found(ck.check(ABOVE.replace("probe", "race")), "SGC003")[0][1],
                         found(ck.check(INLINE.replace("probe", "race")), "SGC003")[0][1])

    def test_unknown_rule_draws_sgc001(self):
        rep = ck.check("#!craft\n#& foo {   # accepts: prbe — typo\n  a b\n}\n[A] -> [B]\n")
        self.assertEqual([f.line for f in rep.findings if f.rule.id == "SGC001"], [2])

    def test_missing_reason_draws_sgc002(self):
        rep = ck.check("#!craft\n#& foo {   # accepts: race\n  a b\n}\n[A] -> [B]\n")
        self.assertEqual([f.line for f in rep.findings if f.rule.id == "SGC002"], [2])

    def test_no_block_covers_its_line(self):
        rep = run("#!spec\n#& bar x y   # accepts: probe — one line\n[A] -> [B] : f()\n",
                  probe(lines=(2,)))
        self.assertEqual(found(rep, "SGC003"), [])
        self.assertEqual([f.line for f in rep.acknowledged], [2])
        rep = run("#!spec\n#& bar x y   # accepts: probe — one line\n[A] -> [B] : f()\n",
                  probe(lines=(3,)))
        self.assertEqual(found(rep, "SGC003"), [
            (2, "the acknowledgement covers no `probe` finding on its line")])

    def test_spaced_and_one_line_forms(self):
        for text in ("#!craft\n#&foo {   # accepts: prbe — typo\n  a b\n}\n[A] -> [B]\n",
                     "#!craft\n  #& foo { a b }   # accepts: prbe — typo\n[A] -> [B]\n"):
            rep = ck.check(text)
            self.assertEqual([f.line for f in rep.findings if f.rule.id == "SGC001"], [2],
                             text)


class OnlyTheAck(unittest.TestCase):
    """What else a `#&` header's comments do stays as it was."""

    def test_other_comment_is_no_comment(self):
        self.assertEqual(collect_comments(["#& foo {   # a note", "  a b", "}"], None), {})

    def test_first_ack_among_the_dialects_text(self):
        line = '#& foo #fff "# accepts: x — in a string" # accepts: race — real'
        self.assertEqual(collect_comments([line], None), {0: ("accepts: race — real", False)})

    def test_nothing_continues_it(self):
        lines = ["#& foo {   # accepts: race — why", "           # body comment", "}"]
        self.assertEqual(collect_comments(lines, None), {
            0: ("accepts: race — why", False), 1: ("body comment", True)})

    def test_no_note_and_body_as_written(self):
        g = parse_document("#& foo {   # accepts: race — why\n  a b\n}\n[A] -> [B]\n")
        self.assertEqual([n.text for n in g.notes], [])
        (d,) = g.declarations
        self.assertEqual(d.body, "# accepts: race — why\n  a b")


if __name__ == "__main__":
    unittest.main()
