"""Core Sigil (no dialect) — the language as it stands alone, plus the dialect
loading mechanism (dialects.py).

Covers:
  - core lint does NOT require a tag on a value payload, and treats modifiers it
    does not know (e.g. `@exec`) as unknown (SGL040 info);
  - multiline block-strings (SGL170, line-count preservation, render);
  - the permission graph with plain glyphs (SGL140/143/144);
  - dialect-only syntax is not specially handled but never crashes;
  - dialects.load: None / "" / env / name via SIGIL_DIALECT_PATH / file path /
    unknown → ValueError; a toy dialect's hooks reach lint and render;
  - every worked example in examples.md (that opens with a mode line) lints
    without errors under core Sigil;
  - the core tools stay standalone (no dialect imports), and the core tools,
    the highlight grammars and these tests carry no dialect vocabulary.

Run:  uv run python -m unittest discover notations/sigil/tests/
"""
from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

_DIR = Path(__file__).resolve().parents[1]


def _load(name: str, fname: str):
    spec = importlib.util.spec_from_file_location(name, _DIR / fname)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lint = _load("sigil_lint", "lint.py")
render = _load("sigil_render", "render.py")
dialects = _load("sigil_dialects", "dialects.py")


def diags(text: str, dialect=None):
    return [(d.severity, d.rule) for d in lint.lint(text, dialect=dialect).diagnostics]


def rules(text: str, dialect=None):
    return {r for _s, r in diags(text, dialect)}


def errors(text: str, dialect=None):
    return [r for s, r in diags(text, dialect) if s == "error"]


# ---------------------------------------------------------------------------
# Payloads & modifiers — the core vocabulary only
# ---------------------------------------------------------------------------

class TestCoreVocabulary(unittest.TestCase):
    def test_untagged_value_payload_is_fine(self):
        doc = "#!spec\n[A] -> |B| : 5\n[A] -> |C| : ${x.y}\n[A] -> |D| : {k: 1}\n"
        self.assertEqual(errors(doc), [])

    def test_ext_op_payload_needs_no_tag(self):
        self.assertEqual(errors("#!spec\n[A] -> [B] : op db.query(${sql})\n"), [])

    def test_ambiguous_map_still_rejected(self):
        self.assertIn("SGL100", rules("#!spec\n[A] -> [B] : {a: 1, b}\n"))

    def test_malformed_ext_op_still_rejected(self):
        self.assertIn("SGL102", rules("#!spec\n[A] -> [B] : op query(x)\n"))

    def test_exec_is_an_unknown_modifier(self):
        d = lint.lint("#!spec\n[A] -> (LLM) : \"rate\" @exec\n").diagnostics
        sgl040 = [x for x in d if x.rule == "SGL040"]
        self.assertEqual(len(sgl040), 1)
        self.assertIn("@exec", sgl040[0].message)
        self.assertNotIn("SGL101", {x.rule for x in d})

    def test_core_modifiers_known(self):
        for mod in ("@inv", "@sla", "@cap", "@owns", "@borrow", "@timeout", "@after",
                    "@deadline", "@fallback", "@grants", "@requires", "@loc",
                    "@read", "@write"):
            self.assertIn(mod, lint.VALID_MODIFIERS)
        for mod in ("@exec", "@state", "@render", "@log", "@spawn", "@tree", "@as"):
            self.assertNotIn(mod, lint.VALID_MODIFIERS)

    def test_loop_each_is_fine(self):
        doc = "#!spec\nloop @each x of {Xs} {\n  [A] -> [B]\n}\n"
        self.assertNotIn("SGL040", rules(doc))

    def test_dialect_syntax_does_not_crash(self):
        # Shapes a dialect might add (a header block, double-bracket refs, a
        # line-leading marker, an event binding, `]>[` chains): core does not
        # understand them, but must neither crash nor invent node kinds.
        doc = ("#!spec\n#&header~{\n  address: a/b\n}\n[[x]] @spawn\n"
               "\\-> [y] -//comment\non <click> |t| -> [v] : ${clicked}\n"
               "[lib]>[book]>[item(x)]\n")
        lint.lint(doc)
        render.render(doc)
        g = render.parse_document(doc)
        core_kinds = {"service", "data", "event", "actor", "store", "state"}
        self.assertLessEqual({n.kind for n in g.nodes.values()}, core_kinds)


# ---------------------------------------------------------------------------
# Multiline block-strings
# ---------------------------------------------------------------------------

BLOCK = '#!spec\n~|sys| : """\nline one ${x}\n[A] excludes [B] ; <- # x\n"""\n[narrator] -> (LLM) : ${sys}\n'


class TestBlockStrings(unittest.TestCase):
    def test_block_lints_clean(self):
        self.assertEqual(errors(BLOCK), [])

    def test_unterminated_is_sgl170_only(self):
        self.assertEqual(errors('#!spec\n~|sys| : """\nnever closed\n'), ["SGL170"])

    def test_collapse_preserves_length(self):
        lines = BLOCK.splitlines()
        self.assertEqual(len(lint.collapse_block_strings(lines, lint.LintResult())), len(lines))

    def test_line_numbers_preserved(self):
        doc = '#!spec\n~|s| : """\na\nb\n"""\n[X] -> [Y] : {a: 1, b}\n'
        d = [x for x in lint.lint(doc).diagnostics if x.rule == "SGL100"]
        self.assertEqual([x.line for x in d], [6])

    def test_render_has_no_phantom_nodes(self):
        g = render.parse_document(BLOCK)
        self.assertEqual({n.name for n in g.nodes.values()}, {"sys", "narrator", "LLM"})


# ---------------------------------------------------------------------------
# Permission graph — plain glyphs
# ---------------------------------------------------------------------------

class TestPermissionGraph(unittest.TestCase):
    def test_well_formed(self):
        doc = "#!spec\n[boss] -> [worker]\n|D| @read(worker) @write(boss)\n"
        self.assertEqual(errors(doc), [])

    def test_undeclared(self):
        self.assertIn("SGL143", rules("#!spec\n[boss] -> |D|\n|D| @write(ghost)\n"))

    def test_empty_list(self):
        self.assertIn("SGL140", rules("#!spec\n[boss] -> |D|\n|D| @write()\n"))

    def test_bad_borrow(self):
        self.assertIn("SGL144", rules("#!spec\n[w] @borrow(execute) |D|\n"))

    def test_list_members_not_rendered(self):
        g = render.parse_document("#!spec\n[boss] -> |D|\n|D| @read(boss, idle)\n")
        self.assertNotIn("actor", {n.kind for n in g.nodes.values()})


# ---------------------------------------------------------------------------
# dialects.load + the hook surface (a toy dialect)
# ---------------------------------------------------------------------------

TOY = textwrap.dedent('''
    import re
    NAME = "toy"
    KNOWN_MODIFIERS = {"@shiny"}
    DEFERRED_MODIFIERS = {"@later"}
    DECLARATION_BLOCKS = [(re.compile(r"^meta\\s*\\{"), False)]

    def _no_bang(lines, result):
        for i, l in enumerate(lines, start=1):
            if "!!" in l:
                result.add("error", i, "TOY1", "no double bang")

    def _tagged(site, result):
        if site.kind == "value" and "@shiny" not in site.tags:
            result.add("error", site.line_no, "TOY2", "values must shine")

    def _tok_star(s, i, prev, layer, Node):
        m = re.match(r"<<(\\w+)>>", s[i:])
        if not m:
            return None
        return [("glyph", Node(id=m.group(1) + "_gem", name=m.group(1), kind="gem",
                               attrs={"facets": 8}))], i + m.end(), True

    lint_passes = lambda: [_no_bang]
    lint_payload_checks = lambda: [_tagged]
    render_tokenizers = lambda: [_tok_star]
    NODE_KINDS = {"gem": {"open": "<<", "close": ">>", "mermaid_shape": ("{{", "}}"),
                          "mermaid_class": "gem", "classdef": "fill:#fff",
                          "color": "#00ffff", "border": "double",
                          "label": lambda n: n.name + "*"}}
''')


class TestDialectLoading(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "sigil-toy").mkdir()
        self.path = root / "sigil-toy" / "dialect.py"
        self.path.write_text(TOY)
        self.root = root

    def tearDown(self):
        self.tmp.cleanup()

    def test_none_and_empty_mean_core(self):
        with mock.patch.dict(os.environ, {"SIGIL_DIALECT": ""}):
            self.assertIsNone(dialects.load(None))
        self.assertIsNone(dialects.load(""))

    def test_load_by_path(self):
        d = dialects.load(str(self.path))
        self.assertEqual(d.NAME, "toy")
        self.assertIs(dialects.load(str(self.path)), d)   # cached

    def test_load_by_name_via_search_path(self):
        with mock.patch.dict(os.environ, {"SIGIL_DIALECT_PATH": str(self.root)}):
            self.assertEqual(dialects.load("toy").NAME, "toy")

    def test_load_from_env(self):
        with mock.patch.dict(os.environ, {"SIGIL_DIALECT": str(self.path)}):
            self.assertEqual(dialects.load(None).NAME, "toy")

    def test_unknown_raises(self):
        with mock.patch.dict(os.environ, {"SIGIL_DIALECT_PATH": ""}):
            with self.assertRaises(ValueError) as cm:
                dialects.load("no-such-dialect-xyz")
        self.assertIn("no-such-dialect-xyz", str(cm.exception))

    def test_hooks_reach_lint(self):
        d = dialects.load(str(self.path))
        doc = "#!spec\n[A] -> [B] @shiny @later\n[A] -> |B| : 5\nmeta {\n  x: {a: 1, b}\n}\n[C] !! [D]\n"
        self.assertIn("SGL040", rules(doc))                 # core: @shiny unknown
        r = rules(doc, d)
        self.assertNotIn("SGL040", r)                       # known + deferred
        self.assertIn("TOY1", r)                            # lint_passes
        self.assertIn("TOY2", r)                            # payload check
        self.assertNotIn("SGL100", r)                       # declaration block skipped

    def test_hooks_reach_render(self):
        d = dialects.load(str(self.path))
        g = render.parse_document("<<ruby>> -> [B]\n", dialect=d)
        self.assertEqual(g.nodes["ruby_gem"].kind, "gem")
        self.assertEqual(g.nodes["ruby_gem"].attrs, {"facets": 8})
        out = render.render("<<ruby>> -> [B]\n", dialect=d)
        self.assertIn('ruby_gem{{"ruby*"}}', out)
        self.assertIn("classDef gem fill:#fff", out)
        self.assertIn("class ruby_gem gem", out)

    def test_cli_unknown_dialect_exits_2(self):
        p = subprocess.run([sys.executable, str(_DIR / "lint.py"), "-", "--dialect",
                            "no-such-dialect-xyz"], input="#!spec\n", text=True,
                           capture_output=True)
        self.assertEqual(p.returncode, 2)
        self.assertIn("unknown sigil dialect", p.stderr)

    def test_cli_dialect_flag(self):
        doc = "#!spec\n[A] -> [B] @shiny\n"
        core = subprocess.run([sys.executable, str(_DIR / "lint.py"), "-"], input=doc,
                              text=True, capture_output=True,
                              env={**os.environ, "SIGIL_DIALECT": ""})
        toy = subprocess.run([sys.executable, str(_DIR / "lint.py"), "-", "--dialect",
                              str(self.path)], input=doc, text=True, capture_output=True)
        self.assertIn("SGL040", core.stdout)
        self.assertEqual(toy.returncode, 0, toy.stdout)


# ---------------------------------------------------------------------------
# Worked examples lint clean under core Sigil
# ---------------------------------------------------------------------------

def _example_blocks(path: Path):
    txt = path.read_text()
    for m in re.finditer(r"^```([a-z]*)\n(.*?)^```", txt, re.S | re.M):
        if m.group(1) == "text":        # a drawing, not Sigil
            continue
        block = m.group(2)
        first = next((l.strip() for l in block.splitlines() if l.strip()), "")
        if first in ("#!spec", "#!sketch", "#!craft"):
            yield txt[:m.start()].count("\n") + 1, block


class TestExamplesLintClean(unittest.TestCase):
    def test_core_examples(self):
        for line, block in _example_blocks(_DIR / "examples.md"):
            with self.subTest(example_at_line=line):
                self.assertEqual(
                    [d.format() for d in lint.lint(block).diagnostics if d.severity == "error"], [])


# ---------------------------------------------------------------------------
# The core tools stand alone
# ---------------------------------------------------------------------------

_CORE_FILES = ("lint.py", "render.py", "dialects.py", "themes.py",
               "view.py", "viewkit.py", "view_graph.py", "view_tree.py", "scene.py",
               "sim.py", "check.py", "check_state.py", "check_trace.py")
# Directories whose every text file must also be free of dialect/host vocabulary.
_SCANNED_DIRS = ("highlight", "tests", "site", "themes")
_WORDLIST_BEGIN = "# vocab-check: word list begin"
_WORDLIST_END = "# vocab-check: word list end"


def _scanned_lines():
    """Yield (relative path, line number, line) for the core tools plus every
    text file under `_SCANNED_DIRS`, skipping this check's own word list (the
    lines between the begin/end markers in this file)."""
    paths = [_DIR / f for f in _CORE_FILES]
    for d in _SCANNED_DIRS:
        paths += sorted(p for p in (_DIR / d).rglob("*")
                        if p.is_file() and "__pycache__" not in p.parts)
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        skipping = False
        for n, ln in enumerate(lines, start=1):
            if ln.strip() == _WORDLIST_BEGIN:
                skipping = True
            elif ln.strip() == _WORDLIST_END:
                skipping = False
            elif not skipping:
                yield path.relative_to(_DIR).as_posix(), n, ln


class TestStandalone(unittest.TestCase):
    # vocab-check: word list begin
    def test_no_dialect_import(self):
        for f in _CORE_FILES:
            src = (_DIR / f).read_text()
            self.assertNotIn("sigil-merlang", src, f)
            self.assertNotRegex(src, r"(?m)^\s*(import|from)\s+\S*merlang", f)

    BANNED = re.compile(
        r"merlang|weaver|\bcure\b|heartstone|WAML|CAML|UAML|triplet|spell(?!check)|keystone"
        r"|harness|elbow|concern"
        r"|\bT\d{1,3}\b|\bO\d{2}\b|subagent|INBOX|OUTBOX|orchestrator", re.I)
    # vocab-check: word list end

    def test_no_dialect_vocabulary(self):
        """Core tools, highlight grammars and tests carry no dialect or host
        vocabulary (so the directory can be exported on its own)."""
        for rel, n, ln in _scanned_lines():
            with self.subTest(file=rel, line=n):
                self.assertIsNone(self.BANNED.search(ln), ln)

    def test_scan_reaches_highlight_and_tests(self):
        scanned = {rel.split("/")[0] for rel, _n, _l in _scanned_lines()}
        self.assertLessEqual({"highlight", "tests"}, scanned)


if __name__ == "__main__":
    unittest.main()
