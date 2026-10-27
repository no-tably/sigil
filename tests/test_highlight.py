"""sigil.present.highlight — sigil source as coloured runs.

Covers the laws over one corpus (every block of language.md and examples.md,
site/examples, tests/fixtures, design/sigil.sigil):
  - every character of a line is in exactly one run; a line's runs joined give
    the line back; every role is a theme path the module names;
  - nothing raises, on the corpus and on fuzzed text (mutations, truncations,
    unbalanced brackets, half-typed glyphs);
  - incremental == whole: line by line with the carry gives lines(text); after an
    edit, edit() (highlighting from the changed line until the carry matches)
    gives a full highlight;
  - one token model: every glyph and arrow Core's walk reads is coloured as one;
plus the carry states, a dialect (its glyph kind, its `#&` declaration, an
undeclared `#&` name), and colour() through a theme.
"""
from __future__ import annotations

import random
import re
import sys
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_DIR))

from sigil.core import dialects  # noqa: E402
from sigil.core.statements import read_document  # noqa: E402
from sigil.present import highlight as hl  # noqa: E402
from sigil.present import themes  # noqa: E402

PROBE = _DIR / "tests" / "fixtures" / "dialect_export_probe.py"

_SYNTAX = {"operator", "cardinality", "modifier", "keyword", "ref", "string", "number",
           "punct", "tag", "call", "call_name"}
_UI = {"mode", "section", "note", "note_tag", "payload"}


def _blocks(path: Path):
    """The fenced blocks of a Markdown file that are Sigil (not ```text drawings)."""
    txt = path.read_text(encoding="utf-8")
    for m in re.finditer(r"^```([a-z]*)\n(.*?)^```", txt, re.S | re.M):
        if m.group(1) in ("", "sigil"):
            yield f"{path.name}:{txt[:m.start()].count(chr(10)) + 1}", m.group(2)


def corpus() -> list:
    """(name, text) of every corpus text."""
    out = []
    for md in ("language.md", "examples.md"):
        out += list(_blocks(_DIR / md))
    files = sorted((_DIR / "site" / "examples").glob("*.sigil"))
    files += sorted((_DIR / "tests" / "fixtures").rglob("*.sigil"))
    files.append(_DIR / "design" / "sigil.sigil")
    out += [(p.relative_to(_DIR).as_posix(), p.read_text(encoding="utf-8")) for p in files]
    return out


CORPUS = corpus()


def whole(raws: list, lx=hl.CORE) -> list:
    """A full highlight of a list of lines (a last blank line kept, which a
    text's splitlines would drop)."""
    out, carry = [], hl.PLAIN
    for raw in raws:
        runs, nxt = hl.line(raw, carry, lx)
        out.append(hl.Line(runs, carry, nxt))
        carry = nxt
    return out


def role_ok(role) -> bool:
    if role is None:
        return True
    section, _, key = role.partition(".")
    return (section == "syntax" and key in _SYNTAX) or (section == "ui" and key in _UI) \
        or (section == "kinds" and bool(key))


def strict(raw: str, carry, lx=hl.CORE):
    """line() without its safety net: the reading itself must not raise."""
    roles = [None] * len(raw)
    out = hl._line(raw, carry, lx, roles)
    return hl._runs(raw, roles), out


class TestLaws(unittest.TestCase):
    def test_corpus_is_large(self):
        self.assertGreater(len(CORPUS), 250)

    def check_runs(self, raw, runs, where):
        self.assertEqual("".join(t for t, _r in runs), raw, where)
        self.assertTrue(all(t for t, _r in runs), where)             # no empty run
        self.assertTrue(all(a[1] != b[1] for a, b in zip(runs, runs[1:])), where)
        for _t, role in runs:
            self.assertTrue(role_ok(role), f"{where}: {role}")

    def test_every_character_in_one_run(self):
        for name, text in CORPUS:
            with self.subTest(name):
                got = hl.lines(text)
                raws = text.splitlines()
                self.assertEqual(len(got), len(raws))
                for k, (raw, ln) in enumerate(zip(raws, got)):
                    self.check_runs(raw, ln.runs, f"{name}:{k + 1}")

    def test_never_raises_on_corpus(self):
        for name, text in CORPUS:
            carry = hl.PLAIN
            for raw in text.splitlines():
                _runs, carry = strict(raw, carry)

    def test_incremental_equals_whole(self):
        for name, text in CORPUS:
            with self.subTest(name):
                whole = hl.lines(text)
                carry, got = hl.PLAIN, []
                for raw in text.splitlines():
                    runs, nxt = hl.line(raw, carry, hl.CORE)
                    got.append(hl.Line(runs, carry, nxt))
                    carry = nxt
                self.assertEqual(got, whole)

    def test_carry_is_small_and_hashable(self):
        seen = set()
        for _name, text in CORPUS:
            seen.update(ln.end for ln in hl.lines(text))
        self.assertIn(hl.PLAIN, seen)
        self.assertTrue(all(isinstance(c, hl.Carry) and hash(c) is not None for c in seen))


# Edits an author makes, each (new lines for line k of `raws`).
_EDITS = (
    lambda r, k: [r[k] + ' """'],                    # opens a block string
    lambda r, k: ['"""'] + [r[k]],                   # a lone delimiter above
    lambda r, k: [r[k] + " {"],                      # opens a block
    lambda r, k: ["}", r[k]],
    lambda r, k: ["#& probe {", r[k]],               # opens a declaration
    lambda r, k: ["state {X} {", r[k]],              # opens a state block
    lambda r, k: [],                                 # deletes the line
    lambda r, k: [r[k][: len(r[k]) // 2]],           # half typed
    lambda r, k: [r[k], r[k]],                       # duplicated
    lambda r, k: [r[k].replace("]", "")],            # a glyph left open
)


class TestEdit(unittest.TestCase):
    def test_edit_equals_full_highlight(self):
        rng = random.Random(6)
        for name, text in CORPUS:
            raws = text.splitlines()
            if not raws:
                continue
            old = hl.lines(text)
            for _ in range(4):
                k = rng.randrange(len(raws))
                change = rng.choice(_EDITS)(raws, k)
                new = raws[:k] + change + raws[k + 1:]
                with self.subTest(name=name, line=k + 1, change=change):
                    got, stop = hl.edit(old, new, k, k + len(change))
                    self.assertEqual(got, whole(new))
                    self.assertLessEqual(stop, len(new))

    def test_edit_that_keeps_the_carry_costs_one_line(self):
        text = "#!spec\n[A] -> [B]\n[B] -> [C]\n[C] -> [D]\n"
        old = hl.lines(text)
        new = text.splitlines()
        new[1] = "[A] ~> [B] : x"
        got, stop = hl.edit(old, new, 1, 2)
        self.assertEqual(stop, 2)
        self.assertEqual(got, hl.lines("\n".join(new)))

    def test_edit_that_opens_a_string_runs_to_the_end(self):
        text = "#!spec\n[A] -> [B]\n[B] -> [C]\n[C] -> [D]\n"
        new = text.splitlines()
        new[1] = '[A] -> [B] : """'
        got, stop = hl.edit(hl.lines(text), new, 1, 2)
        self.assertEqual(stop, 4)
        self.assertTrue(all(ln.start.quote for ln in got[2:]))


_SYMBOLS = list('[]{}<>()|~*@:="#&!?^×\\-$.,/ ') + ['"""', "->", "~>", "=>", "!>", "#&", "#%",
                                                   "#!", "state {", "\\-&", "op ", "${"]


class TestFuzz(unittest.TestCase):
    def test_mutations_never_raise(self):
        rng = random.Random(1)
        lines = [ln for _n, text in CORPUS for ln in text.splitlines() if ln.strip()]
        for _ in range(4000):
            raw = rng.choice(lines)
            for _step in range(rng.randrange(1, 4)):
                k = rng.randrange(len(raw) + 1)
                op = rng.randrange(3)
                if op == 0:
                    raw = raw[:k]
                elif op == 1:
                    raw = raw[:k] + rng.choice(_SYMBOLS) + raw[k:]
                else:
                    raw = raw[:k] + raw[k + 1:]
            carry = hl.Carry(rng.random() < 0.2, rng.choice((0, 0, 1, 2)),
                             rng.random() < 0.5, rng.choice((0, 0, 1)))
            with self.subTest(raw=raw, carry=carry):
                runs, out = strict(raw, carry)
                self.assertEqual("".join(t for t, _r in runs), raw)
                self.assertIsInstance(out, hl.Carry)

    def test_odd_text(self):
        for raw in ("", " ", "\t", "[", "]", "{", "}", '"', '"""', '""""', "#", "#&", "#&{",
                    "#% ", "#!", "---", "-- x --", "state", "state {", "state {X} {",
                    "[A", "[A] ->", "<->", ":", ": :", "@", "@x(", "×", "^", "\\-", "\x00",
                    " ", "[漢字] -> {データ}", "op", "op x.y(", "${", "a -<", "-<a>->"):
            for carry in (hl.PLAIN, hl.Carry(quote=True), hl.Carry(decl=1),
                          hl.Carry(decl=1, decl_raw=False), hl.Carry(state=1)):
                runs, _out = strict(raw, carry)
                self.assertEqual("".join(t for t, _r in runs), raw)


class TestOneTokenModel(unittest.TestCase):
    def test_walk_glyphs_and_arrows_are_coloured_so(self):
        """Every well-formed glyph the walk reads has its name in a kind's colour and
        its brackets as keywords; every arrow is an operator."""
        for name, text in CORPUS:
            raws = text.splitlines()
            if any('"""' in r for r in raws):
                continue                    # folded lines move columns
            got = hl.lines(text)
            roles = []
            for raw, ln in zip(raws, got):
                row = []
                for t, role in ln.runs:
                    row += [role] * len(t)
                roles.append(row)
            walk = read_document(text)
            for st in walk.statements:
                k = st.line - 1
                for tok in st.toks:
                    col = st.code.col + tok.col
                    if tok.kind == "glyph" and not tok.problem and tok.node is None:
                        lead = len(tok.text) - len(tok.text.lstrip("~*"))
                        with self.subTest(name=name, line=st.line, tok=tok.text):
                            self.assertEqual(roles[k][col + lead], "syntax.keyword")
                            self.assertTrue(str(roles[k][col + lead + 1]).startswith("kinds."))
                    elif tok.kind == "arrow":
                        with self.subTest(name=name, line=st.line, tok=tok.text):
                            self.assertEqual(roles[k][col], "syntax.operator")


def roles_of(raw, carry=hl.PLAIN, lx=hl.CORE):
    runs, out = hl.line(raw, carry, lx)
    return [(t, r) for t, r in runs if t.strip()], out


class TestRoles(unittest.TestCase):
    def test_flow(self):
        runs, out = roles_of('~[A] -> |S| : save({Row}, "x") ×3 @timeout(2s)  # why')
        self.assertEqual(out, hl.PLAIN)
        self.assertEqual(runs[:4], [("~[", "syntax.keyword"), ("A", "kinds.service"),
                                    ("]", "syntax.keyword"), ("->", "syntax.operator")])
        got = dict(runs)
        self.assertEqual(got["S"], "kinds.store")
        self.assertEqual(got["save"], "syntax.call_name")
        self.assertEqual(got["Row"], "kinds.data")
        self.assertEqual(got['"x"'], "syntax.string")
        self.assertEqual(got["×3"], "syntax.cardinality")
        self.assertEqual(got["@timeout"], "syntax.modifier")
        self.assertEqual(got["#"], "ui.note_tag")
        self.assertEqual(got[" why"], "ui.note")

    def test_mode_kind_section(self):
        self.assertEqual(roles_of("#!spec")[0], [("#!spec", "ui.mode")])
        runs, _ = roles_of("#% service networked bogus")
        self.assertEqual(runs[:2], [("#%", "ui.mode"), ("service", "syntax.keyword")])
        self.assertIn((" bogus", None), runs)
        self.assertEqual(roles_of("--- L2: [Core] ---")[0], [("--- L2: [Core] ---", "ui.section")])

    def test_block_string_carry(self):
        doc = hl.lines('[A] -> [B] : """\n  text -> [x]\n""" @inv y\n[C] -> [D]')
        self.assertEqual([ln.end.quote for ln in doc], [True, True, False, False])
        self.assertEqual(doc[1].runs, (("  text -> [x]", "syntax.string"),))
        self.assertIn(("@inv", "syntax.modifier"), doc[2].runs)
        self.assertEqual(doc[3].runs[1], ("C", "kinds.service"))

    def test_one_line_block_string(self):
        runs, out = roles_of('[A] -> [B] : """one""" ×2')
        self.assertEqual(out, hl.PLAIN)
        self.assertIn(('"""one"""', "syntax.string"), runs)
        self.assertIn(("×2", "syntax.cardinality"), runs)

    def test_declaration_carry(self):
        doc = hl.lines("#& anything {\n  [not] -> [read]\n}\n[A] -> [B]")
        self.assertEqual([ln.end.decl for ln in doc], [1, 1, 0, 0])
        self.assertEqual(doc[0].runs[:2], (("#&", "ui.mode"), (" ", None)))
        self.assertEqual(doc[0].runs[2], ("anything", "syntax.keyword"))
        self.assertEqual(doc[1].runs[-1], ("[not] -> [read]", "ui.payload"))
        self.assertEqual(doc[3].end, hl.PLAIN)

    def test_state_carry(self):
        doc = hl.lines("state {Order} {\n  + -> Draft\n  Draft -<Go>-> Done @timeout(1d)\n"
                       "} @inv terminates\n[A] -> [B]")
        self.assertEqual([ln.end.state for ln in doc], [1, 1, 1, 0, 0])
        runs = [r for r in doc[2].runs if r[0].strip()]
        self.assertEqual(runs[:7], [("Draft", "kinds.state"), ("-", "syntax.operator"),
                                    ("<", "syntax.keyword"), ("Go", "kinds.event"),
                                    (">", "syntax.keyword"), ("->", "syntax.operator"),
                                    ("Done", "kinds.state")])
        self.assertIn(("@inv", "syntax.modifier"), doc[3].runs)

    def test_one_line_state(self):
        runs, out = roles_of("state {X} { A -> B }")
        self.assertEqual(out, hl.PLAIN)
        self.assertIn(("A", "kinds.state"), runs)

    def test_keywords_and_branch(self):
        runs, _ = roles_of("branch on {X}.f {")
        self.assertEqual(runs[:2], [("branch", "syntax.keyword"), ("on", "syntax.keyword")])
        runs, _ = roles_of("  \\-& [Child]")
        self.assertEqual(runs[0], ("\\-&", "syntax.operator"))
        runs, _ = roles_of("[A] -> op db.put({R})")
        self.assertIn(("op", "syntax.keyword"), runs)
        self.assertIn(("db.put", "syntax.call_name"), runs)


class TestDialect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = dialects.load(str(PROBE))
        cls.lx = hl.lexicon(cls.d)

    def test_dialect_glyph_in_its_kind(self):
        runs, _ = roles_of("[[Pin]] -> [A] @at(x)", lx=self.lx)
        self.assertEqual(runs[:3], [("[[", "syntax.keyword"), ("Pin", "kinds.ref"),
                                    ("]]", "syntax.keyword")])
        doc = hl.lines("[[Pin]] -> [A]", dialect=self.d)
        self.assertEqual(doc[0].runs[1], ("Pin", "kinds.ref"))

    def test_declared_and_undeclared_names(self):
        for name in ("probe", "nobody-declares-this"):
            doc = hl.lines(f"#& {name} {{\n  x\n}}", dialect=self.d)
            self.assertEqual(doc[0].runs[2], (name, "syntax.keyword"))
            self.assertEqual(doc[1].runs[-1], ("x", "ui.payload"))
            self.assertEqual(doc[-1].end, hl.PLAIN)


class TestColour(unittest.TestCase):
    def test_roles_resolve_through_the_theme(self):
        theme = themes.load("sigil")
        for role in ["syntax." + k for k in _SYNTAX] + ["ui." + k for k in _UI] \
                + ["kinds.service", "kinds.state", "kinds.hole"]:
            with self.subTest(role):
                self.assertRegex(hl.colour(role, theme) or "", r"^#[0-9a-f]{6}$")
        self.assertIsNone(hl.colour(None, theme))
        self.assertIsNone(hl.colour("kinds.nothing-here", theme))
        self.assertEqual(hl.colour("syntax.operator", {"syntax": {"operator": "#ABC"}}),
                         "#aabbcc")
        self.assertIsNone(hl.colour("syntax.operator", {"syntax": {"operator": "pink"}}))

    def test_dialect_kind_colour(self):
        lx = hl.Lexicon(kinds=(("ref", "[[", "]]", "#123456"),))
        self.assertEqual(hl.colour("kinds.ref", {}, lx), "#123456")
        self.assertEqual(hl.colour("kinds.ref", {"kinds": {"ref": "#654321"}}, lx), "#654321")


if __name__ == "__main__":
    unittest.main()
