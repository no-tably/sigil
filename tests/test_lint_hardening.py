"""Lint hardening (RFC 0003 catalog §8, SGL120–SGL188): lines the parser would
misread or silently drop.

Each rule has a positive fixture `tests/fixtures/lint/SGLnnn*.sigil` and a negative
twin `SGLnnn*-ok.sigil`; the first line of each names the hardening diagnostics it
must give (`# expect: SGL120@4 …` or `# expect: none`), and the set must match
exactly, so a rule that fires on its neighbours' lines fails too. SGL153 guards a
line the parser now reads (B8), so its positive is stubbed; SGL181 reports a
modifier alias after `×N` that the parser could not resolve (B7).

Run:  python3 -m unittest discover tests
"""
import re
import sys
import types
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]
_FIXTURES = _DIR / "tests" / "fixtures" / "lint"
sys.path.insert(0, str(_DIR))

from sigil.analyse import lint  # noqa: E402
from sigil.analyse.lint import hardening as hl  # noqa: E402
from sigil.core import parse as render  # noqa: E402
from sigil.core import tokens  # noqa: E402
from sigil.core.statements import read_document  # noqa: E402

CODES = set(hl.HARDENING_SEVERITY)
# The parser reads this line since B8; its positive is stubbed below.
STUBBED = {"SGL153"}


def hardening(text: str, dialect=None) -> set:
    return {f"{d.rule}@{d.line}" for d in lint.lint(text, dialect=dialect).diagnostics
            if d.rule in CODES}


def expected(text: str) -> set:
    names = re.match(r"# expect: (.*)", text).group(1).split()
    return set() if names == ["none"] else set(names)


def fixtures():
    return sorted(_FIXTURES.glob("*.sigil"))


class Fixtures(unittest.TestCase):
    def test_each_fixture_gives_exactly_its_expected_findings(self):
        self.assertTrue(fixtures())
        for path in fixtures():
            with self.subTest(fixture=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertEqual(hardening(text), expected(text))

    def test_every_code_has_a_positive_and_a_negative_fixture(self):
        names = [p.stem for p in fixtures()]
        for code in sorted(CODES):
            with self.subTest(code=code):
                self.assertTrue(any(n.startswith(code) and n.endswith("-ok") for n in names))
                if code not in STUBBED:
                    self.assertTrue(any(n.startswith(code) and not n.endswith("-ok")
                                        for n in names))

    def test_positive_fixtures_fire_only_their_own_code(self):
        for path in fixtures():
            if path.stem.endswith("-ok"):
                continue
            code = path.stem.split("-")[0]
            with self.subTest(fixture=path.name):
                rules = {f.split("@")[0] for f in expected(path.read_text(encoding="utf-8"))}
                self.assertEqual(rules, {code})


class Severity(unittest.TestCase):
    CATALOG = {  # RFC 0003 catalog §8 (SGL181 warn since B7: an undefined name)
        "SGL120": "error", "SGL121": "error", "SGL122": "error", "SGL130": "error",
        "SGL131": "error", "SGL132": "error", "SGL150": "warn", "SGL151": "error",
        "SGL152": "warn", "SGL153": "error", "SGL160": "error", "SGL161": "error",
        "SGL162": "warn", "SGL163": "info", "SGL180": "error", "SGL181": "warn",
        "SGL182": "warn", "SGL183": "warn", "SGL184": "warn", "SGL185": "warn",
        "SGL186": "warn", "SGL187": "info", "SGL188": "warn",
        "SGL190": "error",      # a set as a flow's end (design/refine-1.md round 7)
        "SGL191": "warn",       # a bare name outside a data expansion (round 7)
        "SGL192": "error",      # a field written twice in one data shape (round 7)
        "SGL193": "warn",       # a data shape's line that is neither fields nor a flow
        "SGL194": "warn",       # a `{X}.f` naming no field of X's shape (0.6.10)
        "SGL195": "error",      # a name holding a control or format character (0.6.11)
    }

    def test_table_matches_the_catalog(self):
        self.assertEqual(hl.HARDENING_SEVERITY, self.CATALOG)

    def test_reported_severity_follows_the_table(self):
        for path in fixtures():
            for d in lint.lint(path.read_text(encoding="utf-8")).diagnostics:
                if d.rule in CODES:
                    self.assertEqual(d.severity, self.CATALOG[d.rule], (path.name, d.format()))

    def test_silent_drops_are_errors_in_every_mode(self):
        body = "[A] := {\n  [B] -> [C]\n"
        for mode in ("#!spec", "#!sketch", "#!craft"):
            with self.subTest(mode=mode):
                d = [x for x in lint.lint(f"{mode}\n{body}").diagnostics if x.rule == "SGL160"]
                self.assertEqual([(x.severity, x.line) for x in d], [("error", 2)])


class ParserFacts(unittest.TestCase):
    """The rules that ask the parsed model (Graph.dropped, edges by line)."""

    @staticmethod
    def facts(alias_refs=None):
        return hl.ParsedFacts(alias_refs or {})

    def test_an_event_argument_chain_is_read_and_sgl153_is_retired(self):
        # The parser reads `<H>({C})` from the walk's tokens, so the chain cannot
        # break; SGL153 keeps its id (reserved) and its regression fixture.
        lines = ["#!spec", "|P| ~> <H>({C}) -> [R]"]
        self.assertEqual(hardening("\n".join(lines) + "\n"), set())   # the real parser
        self.assertIn("SGL153", hl.HARDENING_SEVERITY)
        g = render.parse_document("\n".join(lines) + "\n")
        self.assertIn(("H_event", "R_service"), {(e.src, e.dst) for e in g.edges})

    def test_an_unresolved_alias_after_a_count_is_flagged(self):
        found = hl.parser_gap_findings(self.facts(alias_refs={2: {"Retry"}}))
        self.assertEqual([(f.line, f.rule) for f in found], [(2, "SGL181")])

    def test_the_parser_resolves_a_defined_alias_and_keeps_an_undefined_one(self):
        g = render.parse_document("#!spec\nRetry := @after(1s)\n"
                                  "[A] -> [B] : charge ×3 Retry\n[A] -> [C] : pay ×2 Nope\n")
        self.assertEqual(hl.parsed_facts(g).alias_refs, {4: {"Nope"}})

    def test_a_transition_without_trigger_is_the_walk_s_one_reading(self):
        # SGL161 for a machine's lines comes from the walk's Transitions (the
        # model's own reading), never from the parsed facts as well.
        text = "#!spec\nstate {X} {\n  + -<a>-> S\n  S -> T\n}\n"
        g = render.parse_document(text)
        self.assertEqual(hl.parser_gap_findings(hl.parsed_facts(g)), [])
        self.assertEqual([(f.line, f.rule) for f in hl.walk_findings(read_document(text))],
                         [(4, "SGL161")])

    def test_every_sgl161_is_the_walk_s(self):
        # One emitter: an owner-less machine at its head, a line of an owned one
        # that is no transition; the parsed facts give none.
        text = ("#!spec\nstate {\n  + -<a>-> S\n}\nstate {X} {\n  hello\n  a -<go b\n}\n"
                "state ~~{Y} {\n}\n")
        g = render.parse_document(text)
        self.assertEqual(hl.parser_gap_findings(hl.parsed_facts(g)), [])
        found = [(f.line, f.rule) for f in hl.walk_findings(read_document(text))]
        self.assertEqual([x for x in found if x[1] == "SGL161"],
                         [(2, "SGL161"), (9, "SGL161"), (6, "SGL161")])
        # The heads it names are the machines the parser drops whole.
        dropped = {d.line for d in g.dropped if d.reason == "no-owner"
                   and d.text.startswith("state")}
        self.assertEqual(set(hl.ownerless_heads(read_document(text).doc)), dropped)

    def test_the_parser_reports_what_it_dropped(self):
        g = render.parse_document("#!spec\n[A] := {\n  [B] -> [C]\n")
        self.assertIn((3, "unclosed", "[B] -> [C]"),
                      {(d.line, d.reason, d.text) for d in g.dropped})

    def test_an_unclosed_block_is_one_finding_at_its_opener(self):
        d = [(x.line, x.rule) for x in lint.lint("#!spec\nstate {X} {\n  + -<a>-> S\n").diagnostics
             if x.rule == "SGL160"]
        self.assertEqual(d, [(2, "SGL160")])

    def test_an_unclosed_block_is_the_walk_s_finding_alone(self):
        # The lines the parser drops in a block never closed say nothing more.
        self.assertEqual(hardening("#!spec\n[A] := {\n  [B] -> [C]\n  [C] -> [D]\n"),
                         {"SGL160@2"})


class Tokens(unittest.TestCase):
    def kinds(self, line):
        return [(t.kind, t.problem) for t in tokens.tokenize_statement(tokens.code_line(line))]

    def test_a_flow_with_payload_and_modifiers(self):
        self.assertEqual(
            self.kinds('[A] -> [B] : charge(total) ×3 @timeout(5s) @fallback("x")'),
            [("glyph", ""), ("arrow", ""), ("glyph", ""), ("payload", ""), ("card", ""),
             ("mod", ""), ("mod", "")])

    def test_problems_are_named(self):
        self.assertEqual(self.kinds("[A -> []"), [("glyph", "unclosed"), ("arrow", ""),
                                                  ("glyph", "empty")])
        self.assertEqual(self.kinds("[A} ) @timeout"), [("glyph", "mismatched"),
                                                        ("bad", "closer"), ("mod", "no-arg")])

    def test_tokenizing_is_pure(self):
        code = tokens.code_line("[A] -> [B] : {X} [C]")
        self.assertEqual(tokens.tokenize_statement(code), tokens.tokenize_statement(code))

    def test_one_finding_per_rule_per_line_in_line_order(self):
        found = hl.hardening_findings(["#!spec", "[A] -> -> -> [B]", "[] -> []"])
        keys = [(f.line, f.rule) for f in found]
        self.assertEqual(keys, sorted(set(keys)))


class NotDrops(unittest.TestCase):
    """Lines the parser reads whole, beside the near neighbours it does not."""

    def check(self, doc: str, want: set):
        self.assertEqual(hardening("#!spec\n" + doc + "\n"), want)

    def test_the_merge_operator_is_no_glyph(self):
        self.check("[A] -> |tree| ||| ${x}", set())
        self.check("[A] -> || [B]", {"SGL121@2"})

    def test_an_empty_map_is_a_store_slot_value(self):
        self.check("~|graph| : {}", set())
        self.check("[A] : {}", {"SGL150@2"})

    def test_a_key_value_modifier_argument_is_no_payload(self):
        self.check("[A] @spawn state:inline", set())
        self.check("[A] -> [B] @embed view:pane @x", set())
        self.check("[A] @spawn state:inline -> [B]", {"SGL150@2"})   # `: inline -> [B]`
        self.check("[A] state:inline", {"SGL150@2"})


class Corpus(unittest.TestCase):
    """The repository's own Sigil gives no hardening errors."""

    def blocks(self, path):
        txt = path.read_text(encoding="utf-8")
        for m in re.finditer(r"^```([a-z]*)\n(.*?)^```", txt, re.S | re.M):
            block = m.group(2)
            first = next((ln.strip() for ln in block.splitlines() if ln.strip()), "")
            if m.group(1) != "text" and first in ("#!spec", "#!sketch", "#!craft"):
                yield txt[:m.start()].count("\n") + 1, block

    def assert_no_errors(self, label, text):
        errs = [d.format() for d in lint.lint(text).diagnostics
                if d.rule in CODES and d.severity == "error"]
        self.assertEqual(errs, [], label)

    def test_spec_and_example_blocks(self):
        for name in ("language.md", "examples.md", "README.md", "skills/sigil/SKILL.md"):
            for line, block in self.blocks(_DIR / name):
                with self.subTest(block=f"{name}:{line}"):
                    self.assert_no_errors(f"{name}:{line}", block)

    def test_sigil_files(self):
        paths = sorted((_DIR / "site" / "examples").glob("*.sigil")) + \
            sorted((_DIR / "tests" / "fixtures").glob("*.sigil")) + \
            [_DIR / "highlight" / "sample.sigil"]
        for path in paths:
            with self.subTest(file=path.name):
                self.assert_no_errors(path.name, path.read_text(encoding="utf-8"))


def _toy_dialect():
    """A dialect with `[[name]]` glyphs (read by its tokenizer), a `meta { … }`
    declaration block and a `using` block keyword."""
    d = types.ModuleType("toy_hardening_dialect")
    d.NAME = "toy"

    def _ref(s, i, prev, layer, Node):
        m = re.compile(r"\[\[([^\[\]]+)\]\]").match(s, i)
        if not m:
            return None
        return [("glyph", Node(id=m.group(1) + "_ref", name=m.group(1), kind="ref",
                               layer=layer))], m.end(), True
    d.tokenizers = lambda: [_ref]
    d.DECLARATION_BLOCKS = [(re.compile(r"^meta\s*\{"), False)]
    d.BLOCK_KEYWORDS = {"using"}
    d.ARROW_TARGET_WORDS = {"resume"}
    return d


class Dialects(unittest.TestCase):
    def test_masked_dialect_glyphs_are_endpoints(self):
        doc = "#!spec\n[[rate]] -> [B]\n[A] -> [[rate]]\n[[a]]>[[b]] -> [C]\n"
        self.assertEqual(hardening(doc, _toy_dialect()), set())

    def test_declaration_blocks_and_keywords_are_not_flows(self):
        doc = ("#!spec\nmeta {\n  address: a/b\n  in: {x: str}\n}\n"
               "using [A] {\n  [A] -> [B]\n}\n")
        self.assertEqual(hardening(doc, _toy_dialect()), set())

    def test_dialect_target_words_are_endpoints(self):
        doc = "#!spec\n<go> -> resume\n<go> -> resumes\n"
        self.assertEqual(hardening(doc, _toy_dialect()), {"SGL130@3"})
        self.assertEqual(hardening(doc), {"SGL130@2", "SGL130@3"})

    def test_a_dialect_without_target_words_keeps_its_bare_targets(self):
        # The core cannot judge a dialect's vocabulary: a dialect that has not said
        # which bare words it reads as targets keeps them all; op calls still check.
        d = _toy_dialect()
        del d.ARROW_TARGET_WORDS
        doc = "#!spec\n<go> -> context\n[W] -> run()\n[A] ->\n"
        self.assertEqual(hardening(doc, d), {"SGL130@4"})
        self.assertEqual(hardening(doc), {"SGL130@2", "SGL130@4"})

    def test_a_dialect_glyph_can_be_expanded(self):
        doc = "#!spec\n[[rate]] := {\n  [A] -> [B]\n}\n[[one]] := { [A] -> [B] }\n"
        self.assertEqual(hardening(doc, _toy_dialect()), set())

    def test_core_rules_still_run_under_a_dialect(self):
        doc = "#!spec\n[[rate]] -> [B\n"
        self.assertEqual(hardening(doc, _toy_dialect()), {"SGL120@2"})


if __name__ == "__main__":
    unittest.main()
