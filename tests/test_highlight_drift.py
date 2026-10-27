"""The editor grammars in highlight/ against sigil's own highlighter: one corpus,
every character, one role class each — so the grammars cannot drift from the
token model (design/refine-1.md, round 6, proposal 8).

Four grammars, one check: sigil.tmLanguage.json (VS Code) and
sigil.sublime-syntax (bat, broot, Sublime) through tests/_textmate.py, the
Pygments lexer.py (skipped without Pygments), and syntax/sigil.vim through one
headless vim run over the whole corpus (skipped without vim / nvim).

sigil.present.highlight gives each character a role (a theme path, or None);
each grammar gives it scopes (TextMate / sublime-syntax, read by tests/_textmate.py)
or a token type (the Pygments lexer). Both sides are reduced to a *role class*
(SCOPE_CLASSES, PYGMENTS_CLASSES, sigil_class) and compared character by
character; whitespace is skipped (no visible colour). Every difference must be
one of the EXCEPTIONS below — each named by construct, with the reason and
whether it is by design or still open — and every exception must still be met
somewhere (a stale one fails).

The corpus: the fenced Sigil blocks of language.md and examples.md (the
collector of tests/test_highlight.py) that lint without errors — the formal
grammar block, a mode line with trailing text and a mode line under a heading
are not Sigil to compare — plus site/examples/*.sigil and design/sigil.sigil.

    python3 tests/test_highlight_drift.py     prints each grammar's agreement and
                                              the exceptions it meets
"""
from __future__ import annotations

import collections
import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Callable, NamedTuple, Optional

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "tests"))

import _textmate  # noqa: E402
from sigil.analyse import lint  # noqa: E402
from sigil.present import highlight as hl  # noqa: E402
from test_highlight import _blocks  # noqa: E402

try:
    import yaml  # noqa: F401
except ImportError:  # pragma: no cover - optional dependency
    yaml = None

try:
    from pygments.token import Token
except ImportError:  # pragma: no cover - optional dependency
    Token = None

_HL = _ROOT / "highlight"


def corpus() -> list:
    """(name, text) of every text compared."""
    out = []
    for md in ("language.md", "examples.md"):
        out += [(name, text) for name, text in _blocks(_ROOT / md)
                if not any(d.severity == "error" for d in lint.lint(text).diagnostics)]
    files = sorted((_ROOT / "site" / "examples").glob("*.sigil"))
    files.append(_ROOT / "design" / "sigil.sigil")
    out += [(p.relative_to(_ROOT).as_posix(), p.read_text(encoding="utf-8")) for p in files]
    return out


# ---------------------------------------------------------------------------
# Role classes
# ---------------------------------------------------------------------------

# A TextMate scope → the role class it shows (README "What is highlighted");
# the first prefix that matches the innermost scope wins. "constant" and
# "predicate" are grammar classes sigil has no role for.
SCOPE_CLASSES = (
    ("keyword.other.sigil.shebang", "ui.mode"),
    ("punctuation.definition.sigil.section", "ui.section"),
    ("markup.heading.sigil", "ui.section"),
    ("comment.line.sigil", "ui.note"),
    ("keyword.control.sigil", "syntax.keyword"),       # glyph brackets, prefixes, keywords
    ("storage.type.sigil", "kinds"),                   # a glyph's name
    ("comment.other.meta.sigil.hole", "kinds"),        # `?` (sigil: kinds.hole)
    ("comment.other.meta.sigil", "syntax.punct"),      # state anchors `+ $`, `_`
    ("entity.name.function.sigil", "syntax.call_name"),  # .op (op ns.verb), .call
    ("entity.name.tag.sigil", "syntax.tag"),
    ("keyword.operator.sigil.cardinality", "syntax.cardinality"),
    ("keyword.operator.sigil", "syntax.operator"),     # arrows, :=, joins, branch, /, values
    ("storage.modifier.sigil", "syntax.modifier"),
    ("punctuation.definition.template-expression", "syntax.ref"),
    ("variable.interpolation", "syntax.ref"),
    ("string.quoted.sigil", "syntax.string"),
    ("punctuation.definition.string", "syntax.string"),
    ("constant.character.escape", "syntax.string"),
    ("constant.numeric", "syntax.number"),
    ("constant.language", "constant"),
    ("punctuation.separator.predicate", "predicate"),
    ("punctuation.separator.sigil", "syntax.punct"),
)


def scope_class(scopes: list) -> Optional[str]:
    for scope in reversed(scopes):
        for prefix, cls in SCOPE_CLASSES:
            if scope == prefix or scope.startswith(prefix + "."):
                return cls
    return None


def sigil_class(role: Optional[str]) -> Optional[str]:
    """A sigil role's class: every kinds.<kind> is "kinds" (a grammar knows no
    kinds), a comment's marker and its text are one "ui.note"."""
    if role is None:
        return None
    if role.startswith("kinds."):
        return "kinds"
    return {"ui.note_tag": "ui.note"}.get(role, role)


# The Pygments token types (highlight/lexer.py) → role class, most specific first.
PYGMENTS_CLASSES = (
    ("Sigil.Doc.Shebang", "ui.mode"), ("Sigil.Doc.Section", "ui.section"),
    ("Sigil.Glyph.Name", "kinds"), ("Sigil.Glyph", "syntax.keyword"),
    ("Sigil.Keyword", "syntax.keyword"), ("Sigil.Branch", "syntax.operator"),
    ("Sigil.Arrow", "syntax.operator"), ("Sigil.Card", "syntax.cardinality"),
    ("Sigil.Mod", "syntax.modifier"), ("Sigil.OpName", "syntax.call_name"),
    ("Sigil.CallName", "syntax.call_name"), ("Sigil.Hole", "kinds"),
    ("Sigil.Wild", "syntax.punct"), ("Sigil.Anchor", "syntax.punct"),
    ("Sigil.Bool", "constant"), ("Sigil.Null", "constant"), ("Sigil.Ref", "syntax.ref"),
    ("Comment", "ui.note"), ("Literal.String", "syntax.string"),
    ("Literal.Number", "syntax.number"), ("Punctuation", "syntax.punct"),
    ("Name.Tag", "syntax.tag"),
)


# The vim syntax groups (syntax/sigil.vim) → role class. sigilPunct also holds the
# comparisons, sigilMeta the hole `?`.
VIM_CLASSES = {
    "sigilKeyword": "syntax.keyword", "sigilGlyphDelim": "syntax.keyword",
    "sigilTypeName": "kinds", "sigilGlyph": "kinds", "sigilBranchCond": "kinds",
    "sigilModifier": "syntax.modifier", "sigilOperator": "syntax.operator",
    "sigilBranch": "syntax.operator", "sigilCard": "syntax.cardinality",
    "sigilBranchWeight": "syntax.number", "sigilNumber": "syntax.number",
    "sigilOpName": "syntax.call_name", "sigilCallName": "syntax.call_name",
    "sigilShebang": "ui.mode", "sigilSecName": "ui.section", "sigilSecRail": "ui.section",
    "sigilSecLevel": "ui.section", "sigilRef": "syntax.ref", "sigilRefBrace": "syntax.ref",
    "sigilString": "syntax.string", "sigilConst": "constant", "sigilComment": "ui.note",
    "sigilMeta": "syntax.punct", "sigilPunct": "syntax.punct", "sigilTag": "syntax.tag",
}


def pygments_class(tok) -> Optional[str]:
    name = str(tok).removeprefix("Token.")
    for prefix, cls in PYGMENTS_CLASSES:
        if name == prefix or name.startswith(prefix + "."):
            return cls
    return None


# ---------------------------------------------------------------------------
# Exceptions: the differences that are by design, or open for a decision
# ---------------------------------------------------------------------------

class Diff(NamedTuple):
    grammar: Optional[str]      # the grammar's role class
    role: Optional[str]         # sigil's role (full)
    raw: str                    # the line
    col: int

    @property
    def ch(self) -> str:
        return self.raw[self.col]

    @property
    def sigil(self) -> Optional[str]:
        return sigil_class(self.role)

    def within(self, rx: str) -> bool:
        """Whether a match of `rx` on the line covers this column."""
        return any(m.start() <= self.col < m.end() for m in re.finditer(rx, self.raw))


class Exception_(NamedTuple):
    name: str
    status: str                 # "by design" | "open"
    why: str
    test: Callable


EXCEPTIONS = (
    Exception_(
        "held-words", "by design",
        "A bare word in text a statement holds (a payload, a modifier's or event's "
        "argument, a definition's prose: `: {retries: 3}`, `@inv depth <= 32`): sigil "
        "leaves it plain (lex.PAYLOAD_PIECE_RE has no word class); a word-level grammar "
        "cannot tell held text from names, so every bare word is entity.name.tag. Both "
        "draw it in the foreground colour (theme syntax.tag = $fg).",
        lambda d: d.grammar == "syntax.tag" and d.sigil is None),
    Exception_(
        "held-marks", "by design",
        "Comparisons (`> <= = ∈`), `true false null`, `.` `,` `&` `+` inside held text or "
        "a definition's prose, and the `...` elision: sigil leaves them plain, the grammars "
        "colour them as predicate / constant / punctuation / operator. The theme's syntax "
        "section has no role for a constant or a comparison (none is added for this), so "
        "sigil draws them as the text they are held in.",
        lambda d: d.sigil is None and d.grammar in
        ("predicate", "constant", "syntax.punct", "syntax.operator")),
    Exception_(
        "call-parens", "by design",
        "A call's `( )` (`charge(…)`, `op db.put(…)`): sigil colours them syntax.call; the "
        "grammars give every parenthesis one punctuation scope (the call-args rule "
        "cannot tell a call's from a modifier's).",
        lambda d: d.role == "syntax.call" and d.grammar == "syntax.punct" and d.ch in "()"),
    Exception_(
        "state-names", "open",
        "A state name inside a `state … { }` body: sigil colours it kinds.state; the "
        "grammars have no state-block context and read a bare name. A state-block region "
        "in the four grammars would close this (and the one-line `state {S} { + -<Go>-> "
        "Run }`, which the grammars read as a {data} glyph).",
        lambda d: d.role == "kinds.state" and d.grammar == "syntax.tag"),
    Exception_(
        "on-of-words", "by design",
        "`on` / `of` away from `branch on` / `loop … of` (prose: `subgraph of facts`): sigil "
        "makes them keywords only there; a word-level grammar makes them keywords always.",
        lambda d: d.grammar == "syntax.keyword" and d.sigil == "syntax.tag"
        and d.within(r"\b(?:on|of)\b")),
    Exception_(
        "lists-in-brackets", "open",
        "A comma list inside one bracket pair — a trigger list `-<Paid, Declined>->`, a set "
        "`{superseded, retracted}` in an argument: a grammar's glyph name runs to the "
        "closing bracket, commas included; sigil splits at the commas (a set is no glyph).",
        lambda d: (d.ch == "," and d.grammar == "kinds" and d.sigil == "syntax.punct")
        or (d.grammar in ("kinds", "syntax.keyword") and d.sigil in (None, "syntax.punct")
            and d.within(r"\{[^{}\n]*,[^{}\n]*\}"))),
)


def explain(d: Diff) -> Optional[str]:
    """The name of the first exception the difference is, or None."""
    return next((e.name for e in EXCEPTIONS if e.test(d)), None)


# ---------------------------------------------------------------------------
# Comparing
# ---------------------------------------------------------------------------

class Report(NamedTuple):
    total: int
    agree: int
    met: collections.Counter    # exception name → characters
    unexplained: list           # (where, Diff)

    @property
    def rate(self) -> float:
        return self.agree / self.total if self.total else 1.0


def compare(classes_of: Callable, texts: list) -> Report:
    """`classes_of(text)` → per line, per character the grammar's role class."""
    total = agree = 0
    met, unexplained = collections.Counter(), []
    for name, text in texts:
        ours = hl.lines(text)
        theirs = classes_of(text)
        for k, (raw, line, cells) in enumerate(zip(text.splitlines(), ours, theirs)):
            roles = [role for run, role in line.runs for _ in run]
            for col, ch in enumerate(raw):
                if ch.isspace():
                    continue
                total += 1
                d = Diff(cells[col], roles[col], raw, col)
                if d.grammar == d.sigil:
                    agree += 1
                    continue
                why = explain(d)
                if why:
                    met[why] += 1
                else:
                    unexplained.append((f"{name}+{k + 1}:{col}", d))
    return Report(total, agree, met, unexplained)


def textmate_classes(grammar) -> Callable:
    return lambda text: [[scope_class(c) for c in line] for line in grammar.scopes(text)]


def pygments_classes() -> Callable:
    spec = importlib.util.spec_from_file_location("sigil_core_lexer", _HL / "lexer.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    lexer = mod.SigilLexer(stripnl=False, ensurenl=True)

    def classes(text: str) -> list:
        flat = []
        for tok, val in lexer.get_tokens(text):
            flat += [(ch, pygments_class(tok)) for ch in val]
        lines, cur = [], []
        for ch, cls in flat:
            if ch == "\n":
                lines.append(cur)
                cur = []
            else:
                cur.append(cls)
        return lines
    return classes


_VIM_DUMP = """\
syntax sync fromstart
let out = []
for lnum in range(1, line('$'))
  let line = getline(lnum)
  let row = []
  for col in range(1, len(line))
    call add(row, synIDattr(synID(lnum, col, 1), 'name'))
  endfor
  call add(out, join(row, ' '))
endfor
call writefile(out, '{out}')
"""


def vim_classes(vim: str, texts: list) -> Callable:
    """One headless vim over every text (one file, a blank line between texts):
    the group at each character's first byte, by text."""
    joined = "\n\n".join(text.rstrip("\n") for _name, text in texts) + "\n"
    with tempfile.TemporaryDirectory() as td:
        src, out, script = (Path(td) / n for n in ("corpus.sigil", "dump.txt", "dump.vim"))
        src.write_text(joined, encoding="utf-8")
        script.write_text(_VIM_DUMP.format(out=out), encoding="utf-8")
        proc = subprocess.run([vim, "-Es", "-u", "NONE", "-N", "-i", "NONE",
                               "--cmd", f"set rtp^={_HL}", "--cmd", "syntax on",
                               "-c", f"edit {src}", "-c", f"source {script}", "-c", "qa!"],
                              capture_output=True, text=True, stdin=subprocess.DEVNULL,
                              timeout=120)
        if re.search(r"\bE\d{2,4}:", proc.stderr) or not out.exists():
            raise RuntimeError(f"vim failed:\n{proc.stderr}")
        rows = out.read_text(encoding="utf-8").split("\n")
    by_line = {}
    for raw, row in zip(joined.split("\n"), rows):
        groups = row.split(" ") if row else []
        cells, at = [], 0
        for ch in raw:
            cells.append(VIM_CLASSES.get(groups[at]) if at < len(groups) else None)
            at += len(ch.encode("utf-8"))
        by_line.setdefault(raw, cells)       # one line, one highlight (no carry differs)
    return lambda text: [by_line[raw] for raw in text.splitlines()]


_CORPUS: list = []
_REPORTS: dict = {}


def report(which: str) -> Report:
    if not _CORPUS:
        _CORPUS.extend(corpus())
    if which not in _REPORTS:
        if which == "tmLanguage":
            fn = textmate_classes(_textmate.tmlanguage(_HL / "sigil.tmLanguage.json"))
        elif which == "sublime-syntax":
            fn = textmate_classes(_textmate.sublime(_HL / "sigil.sublime-syntax"))
        elif which == "vim":
            fn = vim_classes(shutil.which("vim") or shutil.which("nvim"), _CORPUS)
        else:
            fn = pygments_classes()
        _REPORTS[which] = compare(fn, _CORPUS)
    return _REPORTS[which]


def _show(rep: Report, limit: int = 15) -> str:
    rows = [f"{where} grammar={d.grammar} sigil={d.role} {d.ch!r} in {d.raw.strip()[:70]!r}"
            for where, d in rep.unexplained[:limit]]
    return f"{len(rep.unexplained)} unexplained differences:\n  " + "\n  ".join(rows)


class TestTextMateReader(unittest.TestCase):
    def test_reads_both_grammars(self):
        tm = _textmate.tmlanguage(_HL / "sigil.tmLanguage.json")
        cells = tm.scopes('[A] -> {B} : "x" # note')[0]
        self.assertEqual(cells[0][-1], "keyword.control.sigil.glyph")
        self.assertEqual(cells[1][-1], "storage.type.sigil")
        self.assertEqual(cells[4][-1], "keyword.operator.sigil.arrow")
        self.assertEqual(cells[14][-1], "string.quoted.sigil.double")
        self.assertEqual(cells[-1][-1], "comment.line.sigil")

    def test_region_spans_lines(self):
        tm = _textmate.tmlanguage(_HL / "sigil.tmLanguage.json")
        lines = tm.scopes('x : """a\nb\n""" [C]')
        self.assertIn("string.quoted.sigil.block", lines[1][0])
        self.assertEqual(lines[2][-2][-1], "storage.type.sigil")

    @unittest.skipIf(yaml is None, "PyYAML not installed")
    def test_grammars_agree(self):
        """The tmLanguage and the sublime-syntax give every corpus character the
        same innermost scope (they share their regexes)."""
        tm = _textmate.tmlanguage(_HL / "sigil.tmLanguage.json")
        sub = _textmate.sublime(_HL / "sigil.sublime-syntax")
        for name, text in corpus():
            with self.subTest(name):
                a = [[c[-1:] for c in line] for line in tm.scopes(text)]
                b = [[c[-1:] for c in line] for line in sub.scopes(text)]
                self.assertEqual(a, b)

    def test_unsupported_construct_is_loud(self):
        with self.assertRaises(_textmate.Unsupported):
            _textmate.compile_rx(r"\h+")


class TestDrift(unittest.TestCase):
    """Every difference between a grammar and sigil's highlighter is a named
    exception; the agreement stays above its floor."""

    FLOOR = 0.93

    def check(self, which: str):
        rep = report(which)
        self.assertGreater(rep.total, 20000)
        self.assertEqual(rep.unexplained, [], _show(rep))
        self.assertGreaterEqual(rep.rate, self.FLOOR)

    def test_tmlanguage(self):
        self.check("tmLanguage")

    @unittest.skipIf(yaml is None, "PyYAML not installed")
    def test_sublime_syntax(self):
        self.check("sublime-syntax")

    @unittest.skipIf(Token is None, "Pygments not installed")
    def test_pygments_lexer(self):
        self.check("pygments")

    @unittest.skipIf(not (shutil.which("vim") or shutil.which("nvim")), "no vim/nvim installed")
    def test_vim(self):
        self.check("vim")

    def test_no_stale_exception(self):
        """Each exception is still met by the tmLanguage (a fixed one is removed)."""
        met = report("tmLanguage").met
        for e in EXCEPTIONS:
            with self.subTest(e.name):
                self.assertGreater(met[e.name], 0, f"exception {e.name!r} is never met")

    def test_exceptions_are_documented(self):
        for e in EXCEPTIONS:
            self.assertIn(e.status, ("by design", "open"))
            self.assertTrue(e.why)


if __name__ == "__main__":
    for which in ("tmLanguage", "sublime-syntax", "pygments", "vim"):
        rep = report(which)
        print(f"{which}: {rep.agree}/{rep.total} agree ({rep.rate:.2%}); "
              f"{len(rep.unexplained)} unexplained")
        for name, n in rep.met.most_common():
            print(f"    {n:5d}  {name}")
        if rep.unexplained:
            print("  " + _show(rep))
