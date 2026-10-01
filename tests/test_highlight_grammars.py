"""Tests for the core Sigil deploy grammars (`highlight/`).

Validates the per-tool grammars against the token model (`highlight/lexer.py`)
and the shared scope convention:

- **Well-formed:** `sigil.tmLanguage.json` + the VS Code theme + `package.json`
  parse as JSON; `sigil.sublime-syntax` parses as YAML; `sigil.tmTheme` parses
  as a plist; the vim files have the expected structure.
- **Core scope set:** both TextMate-family grammars emit exactly the same core
  scope set (no more, no less), and every role is present.
- **Theme coverage:** each theme colours every role the grammar emits, and has
  no `.sigil` rule for a scope the grammar never emits (no stale rules).
- **Cross-format consistency:** the control keywords agree across the lexer,
  sublime, tmLanguage and vim.
- **Render checks** where a tool is installed (vim / nvim, bat); else skipped.

Every path is relative to this file, so the suite runs from any checkout.

Run:  python3 -m unittest discover tests      (from the sigil directory)
"""
from __future__ import annotations

import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None

_ROOT = Path(__file__).resolve().parents[1]
_HL = _ROOT / "highlight"

SUBLIME    = _HL / "sigil.sublime-syntax"
TMTHEME    = _HL / "sigil.tmTheme"
TMLANG     = _HL / "sigil.tmLanguage.json"
VSTHEME    = _HL / "sigil-color-theme.json"
PACKAGE    = _HL / "package.json"
LANGCONF   = _HL / "language-configuration.json"
LEXER      = _HL / "lexer.py"
SYNTAX_VIM = _HL / "syntax" / "sigil.vim"
FTDET_VIM  = _HL / "ftdetect" / "sigil.vim"
COLORS_VIM = _HL / "after" / "syntax" / "sigil.vim"
SAMPLE     = _HL / "sample.sigil"
LINT       = _ROOT / "lint.py"

# Role → the role-prefix scope. The grammar emits this scope (optionally with a
# `.detail` leaf) and each theme keys a rule on it.
THEMED_ROLES = {
    "keyword":  "keyword.control.sigil",
    "modifier": "storage.modifier.sigil",
    "operator": "keyword.operator.sigil",
    "type":     "storage.type.sigil",
}
UNIVERSAL_ROLES = {
    "ref.brace":   "punctuation.definition.template-expression",
    "ref":         "variable.interpolation",
    "string":      "string.quoted.sigil",
    "number":      "constant.numeric",
    "constant":    "constant.language",
    "comment":     "comment.line.sigil",
    "meta":        "comment.other.meta.sigil",
    "tag":         "entity.name.tag.sigil",
    "punctuation": "punctuation.separator.sigil",
}
ALL_ROLES = {**THEMED_ROLES, **UNIVERSAL_ROLES}

# The complete core scope set — both grammars emit exactly these.
CORE_SCOPES = {
    # doc markers
    "keyword.other.sigil.shebang",
    "punctuation.definition.sigil.section",
    "markup.heading.sigil.level",
    "markup.heading.sigil.name",
    "comment.line.sigil",
    # glyphs + names
    "keyword.control.sigil.glyph",
    "keyword.control.sigil.glyph-prefix",
    "storage.type.sigil",
    "entity.name.tag.sigil",
    # keywords + op-call
    "keyword.control.sigil",
    "entity.name.function.sigil.op",
    # operators
    "keyword.operator.sigil.arrow",
    "keyword.operator.sigil.alias",
    "keyword.operator.sigil.join",
    "keyword.operator.sigil.value",
    "keyword.operator.sigil.cardinality",
    "keyword.operator.sigil.branch",
    "keyword.operator.sigil.path",
    # modifiers
    "storage.modifier.sigil",
    "storage.modifier.sigil.suffix",
    # structural sigils
    "comment.other.meta.sigil.anchor",
    "comment.other.meta.sigil.wildcard",
    "comment.other.meta.sigil.hole",
    # refs
    "punctuation.definition.template-expression.begin.sigil",
    "punctuation.definition.template-expression.end.sigil",
    "variable.interpolation.sigil",
    # values
    "constant.language.boolean.true.sigil",
    "constant.language.boolean.false.sigil",
    "constant.language.null.sigil",
    "constant.numeric.float.sigil",
    "constant.numeric.integer.sigil",
    "string.quoted.sigil.double",
    "string.quoted.sigil.single",
    "string.quoted.sigil.block",
    "punctuation.definition.string.begin.sigil",
    "punctuation.definition.string.end.sigil",
    "constant.character.escape.sigil",
    # punctuation
    "punctuation.separator.sigil",
    "punctuation.separator.predicate.sigil",
}

# The palette: themed hexes + neutral universal hexes. Both full themes carry all.
THEMED_HEXES = {
    "#c850e0",  # glyph / keyword (magenta)
    "#8aa0ff",  # names (periwinkle)
    "#ffe0b0",  # modifiers (less-gold)
    "#e85d9e",  # operators (pink)
    "#f59cc4",  # cardinality (soft pink)
    "#5abea0",  # composition-tree branch marker (teal)
    "#e3c000",  # mode line (gold)
    "#8b7aad", "#d2a8ff", "#e6edf3",  # section rails / level / name
}
UNIVERSAL_HEXES = {
    "#bc8cff", "#a371f7", "#a5d6ff", "#79c0ff",
    "#3fb950", "#f85149", "#6e7681", "#c9d1d9", "#586e75",
}
CORE_KEYWORDS = {"state", "loop", "parallel", "branch", "on", "of", "op"}


def _json_scopes(obj):
    """Yield every `name`/`scope` string anywhere in a parsed JSON grammar."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("name", "scope") and isinstance(v, str):
                yield v
            else:
                yield from _json_scopes(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _json_scopes(v)


def tmlang_scopes() -> set[str]:
    doc = json.loads(TMLANG.read_text(encoding="utf-8"))
    return {s for s in _json_scopes(doc) if s not in ("Sigil",)}


def sublime_scopes() -> set[str]:
    text = SUBLIME.read_text(encoding="utf-8")
    found = set(re.findall(r"^\s*(?:-\s*)?(?:scope|meta_scope):\s*([\w.\-]+)\s*$", text, re.M))
    found |= set(re.findall(r"^\s*\d+:\s*([\w.\-]+)\s*$", text, re.M))
    found.discard("source.sigil")
    return found


def _covered(scope: str, rules) -> bool:
    return any(r == scope or scope.startswith(r + ".") for r in rules)


def tmtheme_rules() -> dict[str, str]:
    doc = plistlib.loads(TMTHEME.read_bytes())
    out = {}
    for rule in doc["settings"]:
        for sc in (rule.get("scope") or "").split(","):
            if sc.strip():
                out[sc.strip()] = rule.get("settings", {}).get("foreground")
    return out


def vstheme_rules() -> dict[str, str]:
    doc = json.loads(VSTHEME.read_text(encoding="utf-8"))
    out = {}
    for tc in doc["tokenColors"]:
        sc = tc.get("scope", [])
        for s in (sc if isinstance(sc, list) else [sc]):
            out[s] = tc.get("settings", {}).get("foreground")
    return out


class TestWellFormed(unittest.TestCase):
    """Every grammar/theme file parses in its own format."""

    def test_all_files_exist(self):
        for p in (SUBLIME, TMTHEME, TMLANG, VSTHEME, PACKAGE, LANGCONF, LEXER,
                  SYNTAX_VIM, FTDET_VIM, COLORS_VIM, SAMPLE):
            self.assertTrue(p.exists(), f"missing highlight file: {p}")

    @unittest.skipIf(yaml is None, "PyYAML not installed")
    def test_sublime_syntax_parses_as_yaml(self):
        doc = yaml.safe_load(SUBLIME.read_text(encoding="utf-8"))
        self.assertEqual(doc["scope"], "source.sigil")
        self.assertIn("sigil", doc["file_extensions"])
        self.assertIn("main", doc["contexts"])
        # Every included / pushed context exists.
        text = SUBLIME.read_text(encoding="utf-8")
        for name in re.findall(r"(?:include|push):\s*([\w-]+)\s*$", text, re.M):
            self.assertIn(name, doc["contexts"], f"undefined context {name!r}")

    def test_tmlanguage_parses_as_json(self):
        doc = json.loads(TMLANG.read_text(encoding="utf-8"))
        self.assertEqual(doc["scopeName"], "source.sigil")
        self.assertIn("sigil", doc["fileTypes"])
        for inc in re.findall(r'"include":\s*"#([\w-]+)"', TMLANG.read_text(encoding="utf-8")):
            self.assertIn(inc, doc["repository"], f"undefined repository key {inc!r}")

    def test_tmlanguage_regexes_compile(self):
        # Python `re` is close enough to Oniguruma for these patterns to be a
        # useful smoke check (no possessive/atomic constructs are used).
        doc = json.loads(TMLANG.read_text(encoding="utf-8"))

        def walk(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k in ("match", "begin", "end") and isinstance(v, str):
                        yield v
                    else:
                        yield from walk(v)
            elif isinstance(o, list):
                for v in o:
                    yield from walk(v)
        for rx in walk(doc):
            with self.subTest(rx=rx):
                re.compile(rx)

    def test_tmtheme_parses_as_plist(self):
        doc = plistlib.loads(TMTHEME.read_bytes())
        self.assertIn("settings", doc)
        self.assertGreater(len(doc["settings"]), 1)

    def test_vscode_theme_parses_as_json(self):
        doc = json.loads(VSTHEME.read_text(encoding="utf-8"))
        self.assertIn("tokenColors", doc)
        self.assertEqual(doc["type"], "dark")

    def test_package_json_contributes(self):
        doc = json.loads(PACKAGE.read_text(encoding="utf-8"))
        c = doc["contributes"]
        self.assertEqual(c["languages"][0]["id"], "sigil")
        self.assertIn(".sigil", c["languages"][0]["extensions"])
        self.assertEqual(c["grammars"][0]["scopeName"], "source.sigil")
        self.assertEqual(c["grammars"][0]["path"], "./sigil.tmLanguage.json")
        self.assertEqual(c["themes"][0]["path"], "./sigil-color-theme.json")

    def test_language_configuration(self):
        doc = json.loads(LANGCONF.read_text(encoding="utf-8"))
        self.assertEqual(doc["comments"]["lineComment"], "#")

    def test_vim_files_structure(self):
        syn = SYNTAX_VIM.read_text(encoding="utf-8")
        self.assertIn("b:current_syntax", syn)
        ft = FTDET_VIM.read_text(encoding="utf-8")
        self.assertIn("*.sigil", ft)
        self.assertIn("filetype=sigil", ft)
        self.assertIn("hi ", COLORS_VIM.read_text(encoding="utf-8"))


class TestCoreScopeSet(unittest.TestCase):
    """Both TextMate-family grammars emit exactly the core scope set."""

    def test_tmlanguage_emits_exactly_core_scopes(self):
        self.assertEqual(tmlang_scopes() - {"source.sigil"}, CORE_SCOPES)

    def test_sublime_emits_exactly_core_scopes(self):
        self.assertEqual(sublime_scopes(), CORE_SCOPES)

    def test_every_role_present(self):
        for label, scopes in (("tmLanguage", tmlang_scopes()),
                              ("sublime-syntax", sublime_scopes())):
            for role, prefix in ALL_ROLES.items():
                with self.subTest(grammar=label, role=role):
                    self.assertTrue(any(s == prefix or s.startswith(prefix + ".")
                                        for s in scopes))


class TestThemes(unittest.TestCase):
    """Each theme colours every emitted scope's role and has no stale rules."""

    def _check_theme(self, rules: dict[str, str], label: str):
        sigil_rules = {r for r in rules if r.endswith(".sigil") or ".sigil." in r
                       or r in UNIVERSAL_ROLES.values()}
        # Every role the grammar emits is covered by some rule.
        emitted = CORE_SCOPES
        for role, prefix in ALL_ROLES.items():
            role_scopes = [s for s in emitted if s == prefix or s.startswith(prefix + ".")]
            with self.subTest(theme=label, role=role):
                self.assertTrue(any(_covered(s, rules) for s in role_scopes),
                                f"{label}: no rule covers role {role!r}")
        # No `.sigil` rule targets a scope the grammar does not emit.
        for r in sigil_rules:
            with self.subTest(theme=label, rule=r):
                self.assertTrue(any(s == r or s.startswith(r + ".") for s in emitted),
                                f"{label}: stale rule {r!r} matches no emitted scope")

    def test_tmtheme(self):
        self._check_theme(tmtheme_rules(), "tmTheme")

    def test_vscode_theme(self):
        self._check_theme(vstheme_rules(), "vscode theme")

    def test_palette_hexes(self):
        tm = TMTHEME.read_text(encoding="utf-8")
        vs = VSTHEME.read_text(encoding="utf-8")
        for hexv in THEMED_HEXES | UNIVERSAL_HEXES:
            self.assertIn(hexv, tm, f"tmTheme missing {hexv}")
            self.assertIn(hexv, vs, f"vscode theme missing {hexv}")

    def test_signature_roles_agree_across_themes(self):
        tm, vs = tmtheme_rules(), vstheme_rules()
        want = {
            "keyword.control.sigil.glyph": "#c850e0",
            "keyword.control.sigil": "#c850e0",
            "storage.type.sigil": "#8aa0ff",
            "entity.name.function.sigil": "#8aa0ff",
            "storage.modifier.sigil": "#ffe0b0",
            "keyword.operator.sigil": "#e85d9e",
            "keyword.operator.sigil.cardinality": "#f59cc4",
            "keyword.operator.sigil.branch": "#5abea0",
            "keyword.other.sigil.shebang": "#e3c000",
            "variable.interpolation": "#bc8cff",
        }
        for scope, hexv in want.items():
            with self.subTest(scope=scope):
                self.assertEqual(tm.get(scope), hexv)
                self.assertEqual(vs.get(scope), hexv)

    def test_one_modifier_colour(self):
        # Core has a single modifier role: no sub-rule recolours a subset of
        # `storage.modifier.sigil` in either theme.
        for label, rules in (("tmTheme", tmtheme_rules()), ("vscode", vstheme_rules())):
            subs = [r for r in rules if r.startswith("storage.modifier.sigil.")]
            self.assertEqual(subs, [], f"{label} splits the modifier role: {subs}")


class TestCrossFormatConsistency(unittest.TestCase):
    """The control keywords agree across all four token sources."""

    def test_keywords_agree(self):
        lexer_src = LEXER.read_text(encoding="utf-8")
        m = re.search(r"_BLOCK_KW\s*=\s*r'\(\?:([^)]*)\)'", lexer_src)
        self.assertIsNotNone(m)
        self.assertEqual(set(m.group(1).split("|")), CORE_KEYWORDS, "lexer")

        m = re.search(r"block_kw:\s*'([^']*)'", SUBLIME.read_text(encoding="utf-8"))
        self.assertEqual(set(m.group(1).split("|")), CORE_KEYWORDS, "sublime")

        doc = json.loads(TMLANG.read_text(encoding="utf-8"))
        rx = doc["repository"]["block-keywords"]["patterns"][0]["match"]
        m = re.search(r"\(\?:([^)]*)\)", rx)
        self.assertEqual(set(m.group(1).split("|")), CORE_KEYWORDS, "tmLanguage")

        m = re.search(r"^syn keyword sigilKeyword (.*)$",
                      SYNTAX_VIM.read_text(encoding="utf-8"), re.M)
        self.assertEqual(set(m.group(1).split()), CORE_KEYWORDS, "vim")

    def test_branch_relation_set_agrees(self):
        rels = "[>&?$@!=_]"
        self.assertIn(rels, LEXER.read_text(encoding="utf-8"))
        self.assertIn(rels, SUBLIME.read_text(encoding="utf-8"))
        self.assertIn(rels, json.loads(TMLANG.read_text(encoding="utf-8"))
                      ["repository"]["branch"]["patterns"][0]["match"])
        self.assertIn(rels, SYNTAX_VIM.read_text(encoding="utf-8"))
        for src in (LEXER, SUBLIME, SYNTAX_VIM):
            with self.subTest(src=src.name):
                self.assertIn("\\d", src.read_text(encoding="utf-8"))   # (N)- weight

    def test_path_separator_agrees(self):
        doc = json.loads(TMLANG.read_text(encoding="utf-8"))
        rx = doc["repository"]["path"]["patterns"][0]["match"]
        self.assertIn(rx, LEXER.read_text(encoding="utf-8"))
        self.assertIn(rx, SUBLIME.read_text(encoding="utf-8"))
        self.assertIn({"include": "#path"}, doc["patterns"])
        self.assertRegex(SYNTAX_VIM.read_text(encoding="utf-8"), r"(?m)^syn match sigilOperator .*/\\ze")

    def test_arrow_set_agrees(self):
        arrows = r"<->|->|~>|=>|!>|\?>|\*>|→"
        self.assertIn(arrows, LEXER.read_text(encoding="utf-8"))
        self.assertIn(arrows, SUBLIME.read_text(encoding="utf-8"))
        self.assertIn(arrows, json.loads(TMLANG.read_text(encoding="utf-8"))
                      ["repository"]["arrows"]["patterns"][0]["match"])


class TestVim(unittest.TestCase):
    """The vim syntax defines, links and colours every group it uses."""

    EXPECTED_GROUPS = {
        "sigilKeyword", "sigilGlyphDelim", "sigilTypeName", "sigilModifier",
        "sigilOperator", "sigilCard", "sigilBranch", "sigilBranchCond", "sigilBranchWeight",
        "sigilOpName", "sigilShebang",
        "sigilSecName", "sigilSecRail", "sigilSecLevel", "sigilRef",
        "sigilRefBrace", "sigilString", "sigilNumber", "sigilConst",
        "sigilComment", "sigilMeta", "sigilPunct", "sigilTag",
    }

    @classmethod
    def setUpClass(cls):
        cls.syn = SYNTAX_VIM.read_text(encoding="utf-8")
        cls.colors = COLORS_VIM.read_text(encoding="utf-8")

    def test_groups_linked_and_coloured(self):
        linked = set(re.findall(r"^hi def link (sigil\w+)", self.syn, re.M))
        coloured = set(re.findall(r"^hi (sigil\w+)", self.colors, re.M))
        self.assertEqual(linked, self.EXPECTED_GROUPS)
        self.assertEqual(coloured, self.EXPECTED_GROUPS)

    def test_every_used_group_is_linked(self):
        used = set(re.findall(r"\b(sigil[A-Z]\w*)", self.syn)) - {"sigilGlyph", "sigilArgs"}
        linked = set(re.findall(r"^hi def link (sigil\w+)", self.syn, re.M))
        self.assertEqual(used - linked, set())

    def test_colours_use_palette(self):
        for hexv in THEMED_HEXES | {"#bc8cff", "#a5d6ff", "#79c0ff", "#3fb950", "#6e7681"}:
            self.assertIn(hexv, self.colors, f"after/syntax missing {hexv}")


class TestRender(unittest.TestCase):
    """Real renders where the tool is installed; skipped otherwise."""

    def test_sample_lints_clean(self):
        proc = subprocess.run([sys.executable, str(LINT), str(SAMPLE)],
                              cwd=_ROOT, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("no issues", proc.stdout)

    def _vim_dump(self, vim: str, source: Path) -> dict[str, str]:
        """Open `source` headless and return {text-run: highlight group}."""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "dump.txt"
            script = Path(td) / "dump.vim"
            script.write_text(
                "let out = [&filetype]\n"
                "for lnum in range(1, line('$'))\n"
                "  let line = getline(lnum)\n"
                "  for col in range(1, len(line))\n"
                "    call add(out, lnum . ' ' . col . ' ' . synIDattr(synID(lnum, col, 1), 'name'))\n"
                "  endfor\n"
                "endfor\n"
                f"call writefile(out, '{out}')\n", encoding="utf-8")
            cmd = [vim, "-Es", "-u", "NONE", "-N", "-i", "NONE",
                   "--cmd", f"set rtp^={_HL}", "--cmd", "syntax on",
                   "-c", f"edit {source}", "-c", f"source {script}", "-c", "qa!"]
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  stdin=subprocess.DEVNULL, timeout=300)
            self.assertNotRegex(proc.stderr, r"\bE\d{2,4}:",
                                f"vim reported an error:\n{proc.stderr}")
            self.assertTrue(out.exists(), "vim produced no dump")
            lines = out.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "sigil", "ftdetect did not set filetype=sigil")
        grid = {}
        for row in lines[1:]:
            parts = row.split(" ")
            grid[(int(parts[0]), int(parts[1]))] = parts[2] if len(parts) > 2 else ""
        return grid

    def test_vim_highlights_core_tokens(self):
        vim = shutil.which("vim") or shutil.which("nvim")
        if not vim:
            self.skipTest("no vim/nvim installed")
        src = ("#!spec\n"
               "--- L1: Core ---\n"
               "[A] -> |DB| : op db.put(${x}) @timeout(5s) ×3\n"
               "state {Job} {\n"
               "  + -<go>-> Run\n"
               "}\n"
               "[Ship]\n"
               "    \\-{hit}-? [Shard]\n"
               "[Log] \\-& {Scroll}\n"
               "[Edge]\n"
               "    \\-(3)-> [ZoneA]\n"
               "    \\-*-= [Shard]\n"
               "    \\-_ [Primary]\n"
               "    \\-{lagging}-! <Lag>\n"
               "[Ship]/[Bullet]/{Transform} -> [Fx]\n"
               "{Resp} / {Err}\n")
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "probe.sigil"
            f.write_text(src, encoding="utf-8")
            grid = self._vim_dump(vim, f)
        line3 = src.splitlines()[2]

        def at(lnum, text, line=None):
            line = line or src.splitlines()[lnum - 1]
            return grid.get((lnum, line.index(text) + 1))
        self.assertEqual(grid.get((1, 1)), "sigilShebang")
        self.assertEqual(at(2, "L1"), "sigilSecLevel")
        self.assertEqual(at(3, "["), "sigilGlyphDelim")
        self.assertEqual(at(3, "A"), "sigilTypeName")
        self.assertEqual(at(3, "->"), "sigilOperator")
        self.assertEqual(at(3, "op "), "sigilKeyword")
        self.assertEqual(at(3, "db.put"), "sigilOpName")
        self.assertEqual(at(3, "${"), "sigilRefBrace")
        self.assertEqual(at(3, "@timeout"), "sigilModifier")
        self.assertEqual(at(3, "×3", line3), "sigilCard")
        self.assertEqual(at(4, "state"), "sigilKeyword")
        self.assertEqual(at(5, "+"), "sigilMeta")
        self.assertEqual(at(8, "\\-"), "sigilBranch")
        self.assertEqual(at(8, "hit"), "sigilBranchCond")
        self.assertEqual(at(8, "-?"), "sigilBranch")
        self.assertEqual(at(9, "\\-&"), "sigilBranch")
        self.assertEqual(at(9, "&"), "sigilBranch")
        self.assertEqual(at(11, "\\-("), "sigilBranch")
        self.assertEqual(at(11, "3"), "sigilBranchWeight")
        self.assertEqual(at(11, ")->"), "sigilBranch")
        self.assertEqual(at(11, ">"), "sigilBranch")
        self.assertEqual(at(12, "="), "sigilBranch")
        self.assertEqual(at(13, "_"), "sigilBranch")
        self.assertEqual(at(14, "lagging"), "sigilBranchCond")
        self.assertEqual(at(14, "!"), "sigilBranch")
        self.assertEqual(at(15, "/"), "sigilOperator")
        self.assertEqual(at(15, "Bullet"), "sigilTypeName")
        self.assertEqual(at(15, "Transform"), "sigilTypeName")
        self.assertEqual(at(16, "/"), "sigilOperator")

    def test_bat_renders_sample_with_theme(self):
        bat = shutil.which("bat") or shutil.which("batcat")
        if not bat:
            self.skipTest("no bat installed")
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "syntaxes").mkdir()
            (Path(td) / "themes").mkdir()
            shutil.copy(SUBLIME, Path(td) / "syntaxes")
            shutil.copy(TMTHEME, Path(td) / "themes")
            build = subprocess.run([bat, "cache", "--build", "--source", td, "--target", td],
                                   capture_output=True, text=True,
                                   stdin=subprocess.DEVNULL, timeout=300)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            env = {k: v for k, v in os.environ.items() if not k.startswith("BAT_")}
            env["BAT_CACHE_PATH"] = td
            env["COLORTERM"] = "truecolor"   # exact hexes, not the 256-colour fallback
            proc = subprocess.run([bat, "--theme=sigil", "--color=always", "--style=plain",
                                   "--paging=never", str(SAMPLE)],
                                  capture_output=True, text=True, env=env,
                                  stdin=subprocess.DEVNULL, timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr.strip(), "")
        out = proc.stdout
        # Magenta glyphs, periwinkle names, gold mode line, pink arrows.
        for rgb in ("200;80;224", "138;160;255", "227;192;0", "232;93;158", "255;224;176",
                    "90;190;160"):
            self.assertIn(f"38;2;{rgb}m", out, f"no {rgb} in bat output")


if __name__ == "__main__":
    unittest.main()
