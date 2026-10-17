"""
The readers outside core read the text the way core does: the half-typed
document's open blocks (present/frames.autoclose), a composition branch's line
(rules/flow.branch_line), the code lines `@inv` is found on (rules/inv), an
acknowledgement's text in the export model (model/systems) and a glyph's kind
in the payload colours (present/kit).
"""

from __future__ import annotations

import sys
import textwrap
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sigil.analyse import check as ck  # noqa: E402
from sigil.analyse.rules import flow as cf  # noqa: E402
from sigil.analyse.rules import inv as ci  # noqa: E402
from sigil.core.lex import CLOSER, OPEN_TO_KIND  # noqa: E402
from sigil.present import frames, kit  # noqa: E402
from sigil.publish import systems as em  # noqa: E402


def slashes() -> types.ModuleType:
    """A dialect whose comments also start with `//`."""
    mod = types.ModuleType("slash_dialect")
    mod.NAME = "slash"
    mod.COMMENT_MARKERS = [r"//"]
    return mod


def doc_of(text: str, dialect=None) -> ck.Doc:
    return ck.Doc(textwrap.dedent(text).lstrip("\n"), "spec", 1, frozenset(), dialect=dialect)


def closes(lines: list) -> int:
    """How many `}` autoclose adds."""
    return frames.autoclose(lines).count("\n") - len(lines)


class Autoclose(unittest.TestCase):
    """autoclose adds the `}` core's walk needs: no more (a stray one would be
    SGL122 in the drawn prefix), no fewer."""

    def test_a_brace_in_a_string_or_comment_opens_nothing(self):
        self.assertEqual(closes(['[A] := { : "{ # {"   # {']), 1)

    def test_a_string_still_being_typed_opens_nothing(self):
        for line in ['[A] : "half {', '[A] -> [B] : "x {', '[A] -> [B] : "a \\" {"',
                     '[A] -> [B] : """ {', '""" {']:
            with self.subTest(line=line):
                self.assertEqual(closes([line]), 0)

    def test_a_block_strings_body_opens_nothing(self):
        self.assertEqual(closes(["[A] := {", '"""', "{", '"""']), 1)
        self.assertEqual(closes(["[A] := {", '  """', "  {", '  """']), 1)

    def test_no_close_lands_in_an_unterminated_block_string(self):
        self.assertEqual(closes(["[A] := {", '"""', "{"]), 0)

    def test_closes_until_the_walk_has_none_open(self):
        # The body's `{"` after `\"` is counted as the definition reads it: one
        # `}` closes that, the next the definition.
        self.assertEqual(closes(["[X] := {", '"x \\" {"']), 2)
        self.assertEqual(closes(["[A] := {", "  [B] := {", "    [C] -> [D]"]), 2)

    def test_a_mode_line_has_no_code(self):
        self.assertEqual(closes(["#!spec {", "[A] := {"]), 1)

    def test_a_line_led_by_a_stray_close_opens_nothing(self):
        # The walk reads `} [A] := {` as a flow, so a `}` after it would be stray.
        self.assertEqual(closes(["} [A] := {"]), 0)

    def test_an_unclosed_glyph_opens_nothing(self):
        self.assertEqual(closes(["[A] -> {B"]), 0)

    def test_every_prefix_closed_draws_no_stray_close(self):
        for lines in (["[A] := {", "  state X {"], ['[A] -> [B] : "x {'],
                      ['[A] : "half {'], ["[A] := {", '"""', "{", '"""'], ["[A] -> {B"]):
            with self.subTest(lines=lines):
                rules = [d.rule for d in kit.run_lint(frames.autoclose(lines))]
                self.assertNotIn("SGL122", rules)


class BranchLine(unittest.TestCase):
    """The first statement led by a branch marker that names the node — the
    SGC167 / SGC166 anchor ebd30f9 gave."""

    def test_an_inline_branch_is_not_led_by_a_marker(self):
        facts = cf.flow_facts(doc_of("[Log] -> [B]\n[Log] \\-& {Rows}\n"))
        self.assertEqual(cf.branch_line(facts, "Rows_data"), 0)

    def test_a_bare_branch_counts(self):
        facts = cf.flow_facts(doc_of("[Ship]\n    *-> [Bullet]\n"))
        self.assertEqual(cf.branch_line(facts, "Bullet_service"), 2)

    def test_a_marker_in_a_payload_is_text(self):
        facts = cf.flow_facts(doc_of('[A] -> [B] : "\\-> [C]"\n[A]\n    \\-> [C]\n'))
        self.assertEqual(cf.branch_line(facts, "C_service"), 3)

    def test_a_glyph_of_another_kind_by_the_same_name_counts(self):
        facts = cf.flow_facts(doc_of("[Pool]\n  \\-> {Worker}\n  \\-* [Worker]\n"))
        self.assertEqual(cf.branch_line(facts, "Worker_service"), 2)

    def test_a_glyph_in_a_branch_payload_counts(self):
        facts = cf.flow_facts(doc_of("[Pool]\n  \\-> [A] : f({Worker})\n  \\-* [Worker]\n"))
        self.assertEqual(cf.branch_line(facts, "Worker_service"), 2)

    def test_a_malformed_marker_still_leads(self):
        facts = cf.flow_facts(doc_of("[Pool]\n  \\-x [Worker]\n  \\-* [Worker]\n"))
        self.assertEqual(cf.branch_line(facts, "Worker_service"), 2)

    def test_a_bare_lead_without_a_relation_still_leads(self):
        for lead in ("(2)-", "*-", "{c}-"):
            with self.subTest(lead=lead):
                facts = cf.flow_facts(doc_of(f"[Pool]\n  {lead} [Worker]\n  \\-* [Worker]\n"))
                self.assertEqual(cf.branch_line(facts, "Worker_service"), 2)

    def test_a_block_strings_body_is_no_branch(self):
        facts = cf.flow_facts(doc_of('[A] : """\n\\-> [C]\n"""\n[A]\n  \\-> [C]\n'))
        self.assertEqual(cf.branch_line(facts, "C_service"), 5)

    def test_unbounded_spawn_anchors(self):
        # SGC167's line as at ebd30f9: an inline branch falls back to the node's
        # first line; a same-named data branch above takes the anchor.
        inline = "#!spec\n[Pool] -> [Worker] : run()\n[Pool] \\-* [Worker]\n"
        stacked = ("#!spec\n[Pool]\n  \\-> {Worker}\n  \\-* [Worker]\n"
                   "[Pool] -> [Worker] : run()\n")
        for text, want in ((inline, 2), (stacked, 3)):
            with self.subTest(text=text):
                report = ck.check(text)
                lines = [f.hit.line for f in report.shown if f.rule.id == "SGC167"]
                self.assertEqual(lines, [want])


class InvCode(unittest.TestCase):
    def test_code_is_the_walks(self):
        doc = doc_of('[A] -> [B] : "x # y"  # note\n')
        self.assertEqual(ci.Facts(ck, doc).code, ['[A] -> [B] : "x # y"  '])

    def test_a_dialect_comment_marker_cuts_the_code(self):
        doc = doc_of("[A] @inv idempotent(k)  // @inv atomic(|S|)\n", dialect=slashes())
        self.assertEqual(ci.Facts(ck, doc).code, ["[A] @inv idempotent(k)  "])
        self.assertEqual([i.arg for i in ci.Facts(ck, doc).invs], ["idempotent(k)"])


class AckText(unittest.TestCase):
    def test_an_acknowledgement_under_a_dialect_marker(self):
        text = ("#!spec\n[Api] -> [Pay] : charge(x) => {R} ×3 @timeout(2s)"
                "   // accepts: retry-without-idempotency — upsert on id\n")
        api = em.build_model(text, "t", dialect=slashes()).components["Api_service"]
        self.assertEqual(api.accepts, ("accepts: retry-without-idempotency — upsert on id",))


class GlyphKind(unittest.TestCase):
    def test_a_payload_glyph_takes_its_kinds_colour(self):
        for opener, kind in OPEN_TO_KIND.items():
            with self.subTest(kind=kind):
                tok = f"{opener}X{CLOSER[opener]}"
                (first, *_rest) = kit.payload_runs(f"f({tok})")[2:]
                self.assertEqual(first, (opener, (kit.kind_color(kind), None, False)))


if __name__ == "__main__":
    unittest.main()
