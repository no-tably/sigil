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
    def test_a_brace_in_a_string_or_comment_opens_nothing(self):
        self.assertEqual(closes(['[A] := { : "{ # {"   # {']), 1)

    def test_strings_follow_the_notations_rule(self):
        # `"…"` has no escapes and an unclosed quote opens no string (lex.STRING_RE).
        self.assertEqual(closes(['[A] := { : "a\\"{"']), 2)
        self.assertEqual(closes(['[A] -> [B] : "x {']), 1)

    def test_a_mode_line_has_no_code(self):
        self.assertEqual(closes(["#!spec {", "[A] := {"]), 1)

    def test_a_stray_close_is_read_and_the_line_goes_on(self):
        self.assertEqual(closes(["} [A] := {"]), 1)


class BranchLine(unittest.TestCase):
    def test_a_branch_after_its_parent_on_one_line(self):
        facts = cf.flow_facts(doc_of("[Log] -> [B]\n[Log] \\-& {Rows}\n"))
        self.assertEqual(cf.branch_line(facts, "Rows_data"), 2)

    def test_a_continuation_is_no_branch(self):
        facts = cf.flow_facts(doc_of("[Ship]\n    *-> [Bullet]\n"))
        self.assertEqual(cf.branch_line(facts, "Bullet_service"), 0)

    def test_a_marker_in_a_payload_is_text(self):
        facts = cf.flow_facts(doc_of('[A] -> [B] : "\\-> [C]"\n[A]\n    \\-> [C]\n'))
        self.assertEqual(cf.branch_line(facts, "C_service"), 3)


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
