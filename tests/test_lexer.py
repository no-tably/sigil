"""Tests for the core Sigil Pygments lexer (`highlight/lexer.py`).

Covers: token assignment for each core token family (glyphs, holes, prefixes,
arrows, joins, `:=`, modifiers, cardinality, stream caps, mode lines, comments,
section headers, control keywords, state-block anchors + transitions, value
literals, refs, block strings, the external op-call); the module interface
(`lex_to_text`, `sigil_syntax`, `RICH_STYLE`, `SigilStyle`, `_resolve_style`);
and no Error tokens on the sample and on every fenced example in
`language.md` / `examples.md`.

Every path is relative to this file. Requires Pygments (+ Rich for the
interface tests); skipped when they are not installed.

Run:  python3 -m unittest discover tests      (from the sigil directory)
"""
from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path

try:
    from pygments.token import Token, Comment, Punctuation, String, Number, Name, Error
except ImportError:  # pragma: no cover - optional dependency
    Token = None

try:
    import rich  # noqa: F401
    HAVE_RICH = True
except ImportError:  # pragma: no cover
    HAVE_RICH = False

_ROOT = Path(__file__).resolve().parents[1]
_LEXER_PATH = _ROOT / "highlight" / "lexer.py"
_SAMPLE = _ROOT / "highlight" / "sample.sigil"

if Token is not None:
    _spec = importlib.util.spec_from_file_location("sigil_core_lexer", _LEXER_PATH)
    sigil_lexer = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(sigil_lexer)
    SigilLexer = sigil_lexer.SigilLexer
    T = Token.Sigil


def lex(code: str):
    return list(SigilLexer().get_tokens(code))


def has(code: str, token, value) -> bool:
    """True iff `(token, value)` appears in the lex of `code`."""
    return (token, value) in lex(code)


def errors(code: str) -> list[str]:
    return [v for t, v in lex(code) if t is Error]


@unittest.skipIf(Token is None, "Pygments not installed")
class TestGlyphs(unittest.TestCase):

    def test_component_glyph(self):
        self.assertTrue(has("[AuthSvc]", T.Glyph, "["))
        self.assertTrue(has("[AuthSvc]", T.Glyph.Name, "AuthSvc"))
        self.assertTrue(has("[AuthSvc]", T.Glyph, "]"))

    def test_all_five_glyph_kinds(self):
        for code, name in (("[X]", "X"), ("{User}", "User"), ("<Evt>", "Evt"),
                           ("(Cust)", "Cust"), ("|DB|", "DB")):
            with self.subTest(code=code):
                self.assertTrue(has(code, T.Glyph.Name, name))

    def test_hole_glyphs(self):
        for code in ("[?]", "{?}", "<?>", "(?)", "|?|"):
            with self.subTest(code=code):
                self.assertTrue(has(code, T.Glyph.Name, "?"))

    def test_bare_hole_and_wildcard(self):
        self.assertTrue(has("  ? -> [A]", T.Hole, "?"))
        self.assertTrue(has("  _ -<cancel>-> Done", T.Wild, "_"))

    def test_mutability_and_stream_prefixes(self):
        self.assertTrue(has("~{Session}", T.Glyph, "~"))
        self.assertTrue(has("~|Counter|", T.Glyph, "~"))
        self.assertTrue(has("*<Event>", T.Glyph, "*"))
        self.assertTrue(has("*|Log|", T.Glyph, "*"))

    def test_parametric_glyph(self):
        self.assertTrue(has("[Cache<K,V>]", T.Glyph.Name, "Cache<K,V>"))


@unittest.skipIf(Token is None, "Pygments not installed")
class TestOperators(unittest.TestCase):

    def test_closed_arrow_set(self):
        for a in ("->", "~>", "<->", "=>", "!>", "?>", "*>", "→"):
            with self.subTest(arrow=a):
                self.assertTrue(has(f"[A] {a} [B]", T.Arrow, a))

    def test_alias(self):
        self.assertTrue(has("walk := [Node]", T.Arrow, ":="))

    def test_joins(self):
        self.assertTrue(has("[A] -> [B] & [C]", T.Arrow.Join, "&"))
        self.assertTrue(has("[A] -> [B] &? [C]", T.Arrow.Join, "&?"))

    def test_alternative_and_value_operators(self):
        self.assertTrue(has("{Resp} / {Err}", T.Arrow, "/"))
        for op in ("++", "||", "+"):
            with self.subTest(op=op):
                self.assertTrue(has(f": ${{a}} {op} ${{b}}", T.Arrow, op))

    def test_cardinality(self):
        self.assertTrue(has("[App]×3", T.Card, "×3"))
        self.assertTrue(has("[App]×N", T.Card, "×N"))
        self.assertTrue(has("charge x3", T.Card, "x3"))

    def test_stream_cap_and_policy(self):
        code = "[Src] => *<Raw>^10k@drop"
        self.assertTrue(has(code, T.Card, "^10k"))
        self.assertTrue(has(code, T.Mod, "@drop"))

    def test_predicates(self):
        self.assertTrue(has("{User}.age @inv >= 0", Punctuation, ">="))
        self.assertTrue(has("{Order}.status ∈ {pending}", Punctuation, "∈"))


@unittest.skipIf(Token is None, "Pygments not installed")
class TestModifiers(unittest.TestCase):

    CORE = ("@inv", "@sla", "@loc", "@timeout", "@after", "@deadline", "@fallback",
            "@cap", "@grants", "@requires", "@owns", "@borrow", "@read", "@write",
            "@each", "@while", "@until", "@times", "@all", "@any", "@none")

    def test_core_modifiers(self):
        for mod in self.CORE:
            with self.subTest(mod=mod):
                self.assertTrue(has(f"[X] {mod}", T.Mod, mod))

    def test_single_modifier_token(self):
        # Core has one modifier role — no modifier gets a sub-token.
        for t, v in lex("[X] @inv @read(A) @each @sla(p99<1s)"):
            if v.startswith("@"):
                self.assertIs(t, T.Mod, v)

    def test_access_lists_lex_as_names(self):
        code = "|DB| @read(Reader, Auditor) @write(Writer)"
        self.assertTrue(has(code, Name.Tag, "Reader"))
        self.assertTrue(has(code, Name.Tag, "Writer"))
        self.assertEqual(errors(code), [])

    def test_critical_and_optional_suffixes(self):
        self.assertTrue(has("[Payment]! -> {Receipt}", T.Mod, "!"))
        self.assertTrue(has("[A] -> {Profile}?", T.Mod, "?"))

    def test_call_resilience(self):
        code = "[J] -> [S] : score({Draft}) @timeout(30s) ×3 @fallback(0)"
        self.assertTrue(has(code, Number.Integer, "30s"))
        self.assertTrue(has(code, T.Card, "×3"))
        self.assertTrue(has(code, T.Glyph.Name, "Draft"))
        self.assertEqual(errors(code), [])


@unittest.skipIf(Token is None, "Pygments not installed")
class TestDocumentMarkers(unittest.TestCase):

    def test_mode_lines(self):
        for mode in ("#!spec", "#!sketch", "#!craft"):
            with self.subTest(mode=mode):
                self.assertTrue(has(mode, T.Doc.Shebang, mode))

    def test_comment(self):
        self.assertTrue(has("[A] -> [B]  # a note", Comment.Single, "# a note"))

    def test_section_header_split(self):
        line = "--- L1: System ---"
        self.assertTrue(has(line, T.Doc.Section, "---"))
        self.assertTrue(has(line, T.Doc.Section.Level, "L1"))
        self.assertTrue(has(line, T.Doc.Section.Name, "System"))
        self.assertTrue(has("--- judge-loop ---", T.Doc.Section.Name, "judge-loop"))
        self.assertTrue(has("--- L2: [Core] ---", T.Doc.Section.Name, "[Core]"))


@unittest.skipIf(Token is None, "Pygments not installed")
class TestControlFlow(unittest.TestCase):

    def test_control_keywords(self):
        for kw in ("state", "loop", "parallel", "branch", "on", "of", "op"):
            with self.subTest(kw=kw):
                self.assertTrue(has(kw + " ", T.Keyword, kw))

    def test_non_core_words_are_bare_names(self):
        # Words a dialect might reserve are plain names in core.
        for word in ("mode", "resolve", "prompt", "str", "int", "map"):
            with self.subTest(word=word):
                self.assertTrue(has(word + " ", Name.Tag, word))

    def test_state_block(self):
        block = ("state {Job} {\n"
                 "  +       -<submit>->  Pending\n"
                 "  Pending -<done>->    $\n"
                 "  _       -<cancel>->  Cancelled  ×3\n"
                 "}\n")
        self.assertTrue(has(block, T.Keyword, "state"))
        self.assertTrue(has(block, T.Anchor, "+"))
        self.assertTrue(has(block, T.Anchor, "$"))
        self.assertTrue(has(block, T.Wild, "_"))
        self.assertTrue(has(block, T.Arrow, "-"))
        self.assertTrue(has(block, T.Glyph.Name, "submit"))
        self.assertTrue(has(block, T.Arrow, "->"))
        self.assertTrue(has(block, Name.Tag, "Pending"))
        self.assertEqual(errors(block), [])

    def test_loop_parallel_branch(self):
        code = ("loop @each x of {Xs} {\n  [A] -> [B]\n}\n"
                "parallel @all {\n  [A] -> [B]\n}\n"
                "branch on {Req}.kind {\n  read => [Reader]\n  _ => <Rejected>\n}\n")
        for kw in ("loop", "of", "parallel", "branch", "on"):
            self.assertTrue(has(code, T.Keyword, kw), kw)
        self.assertTrue(has(code, T.Mod, "@each"))
        self.assertTrue(has(code, T.Mod, "@all"))
        self.assertEqual(errors(code), [])


@unittest.skipIf(Token is None, "Pygments not installed")
class TestCompositionTree(unittest.TestCase):

    TREE = ("[Ship]\n"
            "    \\-& {Transform}\n"
            "    \\-*-> [Bullet]\n"
            "        \\-> [Trail] -> [Fx]\n"
            "    \\-{shattered}-? [Shard]\n"
            "    \\-*-{hit}-$ [Spark]\n"
            "    \\-@ [Radio]\n"
            "    \\-* [Drone]\n"
            "    \\-(3)-> [ZoneA]\n"
            "    \\-*-(1)-> [ZoneB]\n"
            "    \\-*-= [ShardQuery]\n"
            "    \\-_ [Primary]\n"
            "    \\-{lagging}-! <LagAlarm>\n"
            "[Log] \\-& {Scrollable}\n")

    def test_no_errors(self):
        self.assertEqual(errors(self.TREE), [])

    def test_every_relation_is_part_of_the_marker(self):
        for rel in (">", "&", "?", "$", "@", "!", "=", "_"):
            with self.subTest(rel=rel):
                self.assertTrue(has(self.TREE, T.Branch, rel))

    def test_marker_prefixes(self):
        self.assertTrue(has(self.TREE, T.Branch, "\\-"))
        self.assertTrue(has(self.TREE, T.Branch, "\\-*-"))      # spawn
        self.assertTrue(has(self.TREE, T.Branch, "\\-*"))       # bare spawn
        self.assertTrue(has(self.TREE, T.Branch, "{"))
        self.assertTrue(has(self.TREE, T.Branch, "}-"))
        self.assertTrue(has(self.TREE, T.Branch, "("))           # (N)- weight
        self.assertTrue(has(self.TREE, T.Branch, ")-"))

    def test_weight_is_a_number(self):
        self.assertTrue(has(self.TREE, Number.Integer, "3"))
        self.assertTrue(has(self.TREE, Number.Integer, "1"))

    def test_new_relations_not_read_as_operators(self):
        vals = {v for t, v in lex(self.TREE) if t is T.Branch}
        self.assertIn("!", vals)
        self.assertIn("=", vals)
        self.assertIn("_", vals)
        self.assertFalse(has(self.TREE, T.Wild, "_"))

    def test_weight_and_cond_are_alternatives(self):
        # `(N)-{cond}-` is not a marker: the relation must follow one prefix.
        self.assertNotIn((T.Branch, "{"), lex("    \\-(2)-{x}-> [A]\n"))

    def test_marker_needs_line_start_or_closer(self):
        self.assertNotIn(T.Branch, {t for t, _ in lex("[A] -> x\\-_ [B]\n")})

    def test_cond_name_is_a_glyph_name(self):
        self.assertTrue(has(self.TREE, T.Glyph.Name, "shattered"))
        self.assertTrue(has(self.TREE, T.Glyph.Name, "hit"))

    def test_inline_branch_and_child_flow(self):
        self.assertTrue(has("[Log] \\-& {Scrollable}", T.Branch, "&"))
        self.assertTrue(has(self.TREE, T.Arrow, "->"))           # the child's own flow

    def test_marker_inside_string_or_comment_is_text(self):
        code = '[A] -> [B] : "a \\-> b"  # see \\-& here\n'
        self.assertNotIn(T.Branch, {t for t, _ in lex(code)})

    def test_qualified_path(self):
        code = "[Ship]/[Bullet]/{Transform} -> [Fx]\n"
        self.assertEqual([v for t, v in lex(code) if t is T.Arrow.Path], ["/", "/"])
        self.assertTrue(has(code, T.Glyph.Name, "Bullet"))
        self.assertEqual(errors(code), [])
        self.assertTrue(has("[Cart]/~{Discount}", T.Arrow.Path, "/"))

    def test_spaced_slash_stays_alternative(self):
        code = "[A] -> [B] => {Resp} / {Err}\n"
        self.assertTrue(has(code, T.Arrow, "/"))
        self.assertNotIn(T.Arrow.Path, {t for t, _ in lex(code)})

    def test_path_colour_is_operator(self):
        self.assertEqual(sigil_lexer._resolve_style(T.Arrow.Path), "#e85d9e")

    def test_branch_colour(self):
        self.assertEqual(sigil_lexer.RICH_STYLE[T.Branch], "#5abea0")
        self.assertEqual(sigil_lexer.SigilStyle.styles[T.Branch], "#5abea0")


@unittest.skipIf(Token is None, "Pygments not installed")
class TestValues(unittest.TestCase):

    def test_literals(self):
        self.assertTrue(has(": true", T.Bool.True_, "true"))
        self.assertTrue(has(": false", T.Bool.False_, "false"))
        self.assertTrue(has(": null", T.Null, "null"))
        self.assertTrue(has(': "ok"', String.Double, '"ok"'))
        self.assertTrue(has(": 42", Number.Integer, "42"))
        self.assertTrue(has(": 3.14", Number.Float, "3.14"))
        self.assertTrue(has("avail>99.95%", Number.Float, "99.95%"))

    def test_ref_split(self):
        code = ": ${state.count}"
        self.assertTrue(has(code, T.Ref.Brace, "${"))
        self.assertTrue(has(code, T.Ref, "state.count"))
        self.assertTrue(has(code, T.Ref.Brace, "}"))

    def test_map_literal_body_lexes_as_values(self):
        code = '[Cfg] -> ~|opts| : {retries: 3, mode: "strict"}'
        self.assertTrue(has(code, Name.Tag, "retries"))
        self.assertTrue(has(code, Number.Integer, "3"))
        self.assertTrue(has(code, String.Double, '"strict"'))

    def test_list_literal_body_lexes_as_values(self):
        code = "<t> -> ~|h| : ${state.h} ++ [${out}, 1]"
        self.assertTrue(has(code, T.Ref, "out"))
        self.assertTrue(has(code, Number.Integer, "1"))

    def test_block_string(self):
        code = '~|sys| : """\nline one\n${rubric} stays text\n"""\n[A] -> [B]\n'
        toks = lex(code)
        body = "".join(v for t, v in toks if t is String.Double)
        self.assertEqual(body, '"""\nline one\n${rubric} stays text\n"""')
        self.assertTrue(has(code, T.Glyph.Name, "B"))   # lexing resumes after
        self.assertEqual(errors(code), [])

    def test_external_op_call(self):
        code = "[Svc] -> |Log| : op db.insert(${out.score}, 3)"
        self.assertTrue(has(code, T.Keyword, "op"))
        self.assertTrue(has(code, T.OpName, "db.insert"))
        self.assertTrue(has(code, T.Ref, "out.score"))
        self.assertTrue(has(code, Number.Integer, "3"))
        self.assertEqual(errors(code), [])


@unittest.skipIf(Token is None or not HAVE_RICH, "Pygments / Rich not installed")
class TestInterface(unittest.TestCase):

    def test_symbols_present(self):
        for sym in ("SigilLexer", "SigilStyle", "RICH_STYLE", "lex_to_text",
                    "sigil_syntax", "_resolve_style"):
            self.assertTrue(hasattr(sigil_lexer, sym), sym)

    def test_lex_to_text_roundtrips(self):
        from rich.text import Text
        src = "[A] -> [B] : true"
        out = sigil_lexer.lex_to_text(src)
        self.assertIsInstance(out, Text)
        self.assertEqual(out.plain, src)

    def test_signature_colours(self):
        rs = sigil_lexer._resolve_style
        self.assertEqual(rs(T.Glyph), "#c850e0")
        self.assertEqual(rs(T.Keyword), "bold #c850e0")
        self.assertEqual(rs(T.Glyph.Name), "italic #8aa0ff")
        self.assertEqual(rs(T.Mod), "#ffe0b0")
        self.assertEqual(rs(T.Arrow), "#e85d9e")
        self.assertEqual(rs(T.Arrow.Join), "#e85d9e")
        self.assertEqual(rs(T.Card), "#f59cc4")
        self.assertEqual(rs(T.Doc.Shebang), "bold #e3c000")
        self.assertEqual(rs(T.Ref), "italic #bc8cff")

    def test_style_and_rich_maps_agree(self):
        self.assertEqual(dict(sigil_lexer.SigilStyle.styles).keys() >= sigil_lexer.RICH_STYLE.keys(), True)
        for tok, style in sigil_lexer.RICH_STYLE.items():
            self.assertEqual(sigil_lexer.SigilStyle.styles[tok], style, tok)

    def test_every_emitted_token_has_a_style(self):
        text = _SAMPLE.read_text(encoding="utf-8")
        for t, v in lex(text):
            if v.strip():
                self.assertNotEqual(sigil_lexer._resolve_style(t), "", (t, v))

    def test_sigil_syntax(self):
        from rich.syntax import Syntax
        self.assertIsInstance(sigil_lexer.sigil_syntax("[A] -> [B]"), Syntax)


@unittest.skipIf(Token is None, "Pygments not installed")
class TestCorpus(unittest.TestCase):
    """No Error tokens on the sample or on any fenced example of the spec."""

    def test_sample_has_no_errors(self):
        self.assertEqual(errors(_SAMPLE.read_text(encoding="utf-8")), [])

    def test_sample_covers_every_token_family(self):
        seen = {t for t, _ in lex(_SAMPLE.read_text(encoding="utf-8"))}
        for tok in (T.Glyph, T.Glyph.Name, T.Keyword, T.Arrow, T.Arrow.Join, T.Mod,
                    T.Card, T.Branch, T.Arrow.Path, T.Wild, T.Anchor, T.Doc.Shebang, T.Doc.Section,
                    T.Doc.Section.Level, T.Doc.Section.Name, T.Bool.True_, T.Bool.False_,
                    T.Null, T.Ref, T.Ref.Brace, T.OpName, Comment.Single, String.Double,
                    Number.Integer, Number.Float, Name.Tag):
            self.assertIn(tok, seen, f"sample.sigil never produces {tok}")

    def test_spec_examples_have_no_errors(self):
        for name in ("language.md", "examples.md"):
            text = (_ROOT / name).read_text(encoding="utf-8")
            for m in re.finditer(r"^```([a-z]*)\n(.*?)^```", text, re.S | re.M):
                if m.group(1) == "text":        # a drawing, not Sigil
                    continue
                line = text[:m.start()].count("\n") + 1
                with self.subTest(file=name, line=line):
                    self.assertEqual(errors(m.group(2)), [])


if __name__ == "__main__":
    unittest.main()
