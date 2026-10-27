"""
The readers outside core read the text the way core does: the half-typed
document's open blocks (present/frames.autoclose), a composition branch's line
(rules/flow.branch_line), the code lines `@inv` is found on (rules/inv), an
acknowledgement's text in the export model (model/systems), a glyph's kind
in the payload colours (present/kit), the store / event references of an
argument (rules/state, rules/inv), the actor glyphs SGL020 reads and the access
lists lint blanks (lint/lines, lint/permissions).
"""

from __future__ import annotations

import re
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
from sigil.analyse.rules import state as cs  # noqa: E402
from sigil.analyse.lint import lint  # noqa: E402
from sigil.core import lex  # noqa: E402
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


class BranchLineReadsCore(unittest.TestCase):
    """branch_line reads the lead from lex (BRANCH_LEAD_RE, the pattern flow.py
    held) and the names from core's glyph_spans over the line's code."""

    OLD_LEAD = re.compile(r"^\s*(?:\\-|\*-|\{[^}]*\}-|\(\d+\)-)")

    def test_the_lead_is_the_one_flow_held(self):
        for line in corpus_lines() + ["\\-x [A]", "*-> [A]", "{c d}- [A]", "(12)-", "-& {H}",
                                      "-* [W]", "  \\-> [A]", "[P] \\-* [C]"]:
            with self.subTest(line=line):
                self.assertEqual(bool(lex.BRANCH_LEAD_RE.match(line)),
                                 bool(self.OLD_LEAD.match(line)))

    def test_a_name_in_a_comment_or_string_on_a_branch_line_is_text(self):
        # Named change: the old search ran over the raw line.
        for line in ("  \\-> [A]   # not [Worker]", '  \\-> [A] : "[Worker]"'):
            with self.subTest(line=line):
                facts = cf.flow_facts(doc_of(f"[Pool]\n{line}\n  \\-* [Worker]\n"))
                self.assertEqual(cf.branch_line(facts, "Worker_service"), 3)

    def test_a_branch_holds_its_lines_code_as_written(self):
        facts = cf.flow_facts(doc_of("[Pool]\n  \\-> [A] : f([Worker])\n  \\-* [Worker]\n"))
        self.assertEqual(facts.branches[0], (2, "  \\-> [A] : f([Worker])"))


def corpus_lines() -> list:
    """Every line of the repository's .sigil documents."""
    out = []
    for path in sorted(ROOT.glob("**/*.sigil")):
        if "node_modules" not in path.parts:
            out += path.read_text(encoding="utf-8").splitlines()
    return out


class GlyphRefsReadCore(unittest.TestCase):
    """The store / event reference patterns of rules/state and rules/inv are read
    off lex's tables and match as the literal patterns did."""

    OLD_STORE = re.compile(r"[~*]?\|([^|]+)\|")
    OLD_DATA_ONLY = re.compile(r"^\s*~?\{[^{}:]*\}\s*$")
    OLD_REF = re.compile(r"(?P<pre>[~*]?)(?:\|(?P<store>[^|]+)\||<(?P<event>[^<>]+)>)")
    EXTRA = ["lock-order(|A| < ~|B| < *|C|)", "atomic(|S|, <E>, *<F>)", "{}", " ~{Row} ",
             "{Order: [Item]}", "*{X}", "~*|S|", "|a|b|", "<<E>>", "{ x }"]

    def test_the_patterns_match_as_before(self):
        for text in corpus_lines() + self.EXTRA:
            with self.subTest(text=text):
                for new, old in ((cs._STORE_REF_RE, self.OLD_STORE),
                                 (ci._GLYPH_REF_RE, self.OLD_REF)):
                    self.assertEqual([m.groupdict() or m.groups() for m in new.finditer(text)],
                                     [m.groupdict() or m.groups() for m in old.finditer(text)])
                self.assertEqual(bool(cs._DATA_ONLY_RE.match(text)),
                                 bool(self.OLD_DATA_ONLY.match(text)))

    def test_glyph_patterns_unchanged(self):
        for kind, (open_, close) in lex.GLYPH_BRACKETS.items():
            inside = "".join(map(re.escape, dict.fromkeys(open_ + close)))
            with self.subTest(kind=kind):
                # round 7: a data glyph's name holds no comma (`{a, b}` is a set)
                not_set = r"(?![^{}<]*,)" if kind == "data" else ""
                self.assertEqual(lex.GLYPH_PATTERNS[kind].pattern,
                                 f"{re.escape(open_)}{not_set}([^{inside}]+){re.escape(close)}")


class AccessListsReadCore(unittest.TestCase):
    def test_blanked_as_before(self):
        old = lex.PRINCIPAL_SET_RE
        for text in corpus_lines() + ["|S| @read(a, b) @write( c )", "@read", "x@write(y)z"]:
            with self.subTest(text=text):
                self.assertEqual(lex.blank_access_lists(text),
                                 old.sub(lambda m: " " * len(m.group(0)), text))

    def test_an_actor_as_state_quotes_the_name_as_written(self):
        result = lint("[A] -> ( Pending ) @read(done)\n")
        self.assertEqual([d.message.split(")")[0] for d in result.diagnostics
                          if d.rule == "SGL020"], ["( Pending "])


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
