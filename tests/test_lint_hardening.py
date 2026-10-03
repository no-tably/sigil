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
import importlib.util
import re
import types
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]
_FIXTURES = _DIR / "tests" / "fixtures" / "lint"


def _load(name: str, fname: str):
    spec = importlib.util.spec_from_file_location(name, _DIR / fname)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lint = _load("sigil_lint_hardening", "lint.py")
render = _load("sigil_render_hardening", "render.py")

CODES = set(lint.HARDENING_SEVERITY)
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
    }

    def test_table_matches_the_catalog(self):
        self.assertEqual(lint.HARDENING_SEVERITY, self.CATALOG)

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
    def facts(sources=None, alias_refs=None, untriggered=(), dropped=()):
        return lint.ParsedFacts(sources or {}, alias_refs or {}, frozenset(untriggered),
                                tuple(dropped))

    @staticmethod
    def codes(lines):
        return [lint.code_line(ln) for ln in lines]

    def test_event_argument_flagged_while_the_parser_loses_the_chain(self):
        lines = ["#!spec", "|P| ~> <H>({C}) -> [R]"]
        found = lint.parser_gap_findings(self.codes(lines), self.facts())
        self.assertEqual([(f.line, f.rule) for f in found], [(2, "SGL153")])

    def test_event_argument_quiet_once_the_parser_reads_it(self):
        lines = ["#!spec", "|P| ~> <H>({C}) -> [R]"]
        facts = self.facts({2: {("store", "P"), ("event", "H")}})
        self.assertEqual(lint.parser_gap_findings(self.codes(lines), facts), [])
        self.assertEqual(hardening("\n".join(lines) + "\n"), set())   # the real parser

    def test_event_argument_at_the_end_breaks_nothing(self):
        lines = ["#!spec", "|P| ~> <H>({C})"]
        self.assertEqual(lint.parser_gap_findings(self.codes(lines), self.facts()), [])

    def test_an_unresolved_alias_after_a_count_is_flagged(self):
        lines = ["#!spec", "[A] -> [B] : charge ×3 Retry"]
        found = lint.parser_gap_findings(self.codes(lines), self.facts(alias_refs={2: {"Retry"}}))
        self.assertEqual([(f.line, f.rule) for f in found], [(2, "SGL181")])

    def test_the_parser_resolves_a_defined_alias_and_keeps_an_undefined_one(self):
        g = render.parse_document("#!spec\nRetry := @after(1s)\n"
                                  "[A] -> [B] : charge ×3 Retry\n[A] -> [C] : pay ×2 Nope\n")
        self.assertEqual(lint.parsed_facts(g).alias_refs, {4: {"Nope"}})

    def test_a_transition_without_trigger_is_read_from_the_model(self):
        g = render.parse_document("#!spec\nstate {X} {\n  + -<a>-> S\n  S -> T\n}\n")
        facts = lint.parsed_facts(g)
        self.assertEqual(facts.untriggered, frozenset({4}))
        found = lint.parser_gap_findings(self.codes(["", "", "", ""]), facts)
        self.assertEqual([(f.line, f.rule) for f in found], [(4, "SGL161")])

    def test_dropped_lines_map_to_codes(self):
        lines = ["#!spec", "state {", "  + -<a>-> S", "}", "state {X} {", "  hello",
                 "  a -<go b", "}"]
        dropped = [(2, "no-owner", "state {"), (3, "no-owner", "+ -<a>-> S"),
                   (4, "no-owner", "}"), (6, "not-a-transition", "hello"),
                   (7, "not-a-transition", "a -<go b")]
        found = lint.parser_gap_findings(self.codes(lines), self.facts(dropped=dropped))
        # One finding for the owner-less machine; a malformed `-<` line is SGL090's.
        self.assertEqual([(f.line, f.rule) for f in found], [(2, "SGL161"), (6, "SGL161")])

    def test_the_parser_reports_what_it_dropped(self):
        g = render.parse_document("#!spec\n[A] := {\n  [B] -> [C]\n")
        facts = lint.parsed_facts(g)
        self.assertIn((3, "unclosed", "[B] -> [C]"), facts.dropped)

    def test_an_unclosed_block_is_one_finding_at_its_opener(self):
        d = [(x.line, x.rule) for x in lint.lint("#!spec\nstate {X} {\n  + -<a>-> S\n").diagnostics
             if x.rule == "SGL160"]
        self.assertEqual(d, [(2, "SGL160")])

    def test_parser_stand_in_when_the_walker_sees_no_block(self):
        lines = ["#!spec", "[A] -> [B]"]
        found = lint.hardening_findings(lines, facts=self.facts(dropped=[(2, "unclosed", "x"),
                                                                         (3, "unclosed", "y")]))
        self.assertEqual([(f.line, f.rule) for f in found], [(2, "SGL160")])


class Tokens(unittest.TestCase):
    def kinds(self, line):
        return [(t.kind, t.problem) for t in lint.tokenize_statement(lint.code_line(line))]

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
        code = lint.code_line("[A] -> [B] : {X} [C]")
        self.assertEqual(lint.tokenize_statement(code), lint.tokenize_statement(code))

    def test_one_finding_per_rule_per_line_in_line_order(self):
        found = lint.hardening_findings(["#!spec", "[A] -> -> -> [B]", "[] -> []"])
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
    """A dialect with `[[name]]` glyphs (masked for lint), a `meta { … }`
    declaration block and a `using` block keyword."""
    d = types.ModuleType("toy_hardening_dialect")
    d.NAME = "toy"
    d.lint_glyph_masks = lambda: [lambda line: re.sub(r"\[\[[^\[\]]+\]\]",
                                                      lambda m: " " * len(m.group(0)), line)]
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
