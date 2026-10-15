"""The spine: each layer of the sigil package imports only the layers above it.

    core  ←  model  ←  analyse  ←  publish / present  ←  cli

A module may import its own layer and any layer to its left; publish and present
never import each other. Every import counts, a lazy one inside a function too,
and so does `importlib.import_module("sigil.…")`. No module loads a sibling by
path (`spec_from_file_location`, `module_from_spec`, a `_sibling` helper, a
`sys.path` edit): the one exception is core/dialects.py, since a dialect is a
file beside the package, not a module of it.

Also here: `sigil lint` loads neither check, the model nor the drawings (the
speed guard), and sigil.core.vocab carries the dialect API.
"""

import ast
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "sigil"
sys.path.insert(0, str(ROOT))

# Layer of each top-level part of the package, by rank: a module may import a
# rank below its own, or its own layer. Same rank, different layer = sideways.
LAYERS = {"core": 0, "model": 1, "analyse": 2, "publish": 3, "present": 3, "cli": 4}
PATH_LOADERS = {"spec_from_file_location", "module_from_spec", "SourceFileLoader",
                "run_path", "_sibling", "_load_sibling"}
MAY_LOAD_BY_PATH = {"sigil.core.dialects"}      # a dialect is a file, not a module


def module_name(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def layer_of(name: str):
    """The layer of a module of the package (`sigil.core.parse` → core); the
    package itself, its __main__ and cli are the command (cli); None outside it."""
    parts = name.split(".")
    if parts[0] != "sigil":
        return None
    if len(parts) == 1 or parts[1] in ("cli", "__main__"):
        return "cli"
    return parts[1] if parts[1] in LAYERS else "cli"


def resolve(importer: str, is_package: bool, node: ast.ImportFrom) -> str:
    """The absolute module an ImportFrom names (relative ones resolved)."""
    if not node.level:
        return node.module or ""
    base = importer.split(".")
    base = base if is_package else base[:-1]
    base = base[:len(base) - (node.level - 1)]
    return ".".join(base + ([node.module] if node.module else []))


def literal_prefix(arg) -> str:
    """The text an import_module argument starts with, when it is a literal
    (or an f-string starting with one)."""
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if isinstance(arg, ast.JoinedStr) and arg.values and isinstance(arg.values[0], ast.Constant):
        return str(arg.values[0].value)
    return ""


def imports_of(path: Path) -> list:
    """(line, imported module) for every import in the file, lazy ones too.
    `from X import Y` counts as X.Y when Y is a module of the package."""
    name, tree = module_name(path), ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(node.lineno, a.name) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = resolve(name, path.name == "__init__.py", node)
            for a in node.names:
                sub = f"{base}.{a.name}"
                is_module = (ROOT / Path(*sub.split("."))).with_suffix(".py").is_file() \
                    or (ROOT / Path(*sub.split("."))).is_dir()
                out.append((node.lineno, sub if is_module else base))
        elif isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) == "import_module":
            target = literal_prefix(node.args[0]) if node.args else ""
            if target:
                out.append((node.lineno, target.rstrip(".")))
    return out


def loaders_in(path: Path) -> list:
    """(line, what) for each path loader the file uses or defines."""
    tree, out = ast.parse(path.read_text(encoding="utf-8")), []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in PATH_LOADERS:
            out.append((node.lineno, f"defines {node.name}"))
        elif isinstance(node, ast.Attribute) and node.attr in PATH_LOADERS:
            out.append((node.lineno, node.attr))
        elif isinstance(node, ast.Name) and node.id in PATH_LOADERS:
            out.append((node.lineno, node.id))
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr in ("insert", "append")
              and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "path"
              and getattr(node.func.value.value, "id", "") == "sys"):
            out.append((node.lineno, "sys.path edit"))
    return out


def violation(importer: str, target: str):
    """Why `importer` may not import `target`, or None when it may."""
    mine, theirs = layer_of(importer), layer_of(target)
    if theirs is None or mine == theirs:
        return None
    if LAYERS[theirs] > LAYERS[mine]:
        return f"{mine} imports {theirs}, a layer below it"
    if LAYERS[theirs] == LAYERS[mine]:
        return f"{mine} imports {theirs}, a layer beside it"
    return None


def modules() -> list:
    return sorted(PACKAGE.rglob("*.py"))


class SpineTest(unittest.TestCase):
    def test_package_has_the_layers(self):
        for layer in ("core", "model", "analyse", "publish", "present"):
            self.assertTrue((PACKAGE / layer / "__init__.py").is_file(), layer)

    def test_layers_import_only_layers_above(self):
        bad = []
        for path in modules():
            name = module_name(path)
            for line, target in imports_of(path):
                why = violation(name, target)
                if why:
                    bad.append(f"{path.relative_to(ROOT)}:{line}: imports {target} ({why})")
        self.assertEqual(bad, [], "\n".join(bad))

    def test_no_path_loaders(self):
        bad = [f"{path.relative_to(ROOT)}:{line}: {what}"
               for path in modules() if module_name(path) not in MAY_LOAD_BY_PATH
               for line, what in loaders_in(path)]
        self.assertEqual(bad, [], "\n".join(bad))


class CheckerTest(unittest.TestCase):
    """The scan itself: it sees what it must."""

    def test_violation(self):
        self.assertIsNone(violation("sigil.model.scene", "sigil.core.parse"))
        self.assertIsNone(violation("sigil.cli", "sigil.present.app"))
        self.assertIsNone(violation("sigil.analyse.lint", "re"))
        self.assertIn("below", violation("sigil.model.scene", "sigil.present.kit"))
        self.assertIn("below", violation("sigil.core.parse", "sigil.analyse.check"))
        self.assertIn("beside", violation("sigil.publish.exporter", "sigil.present.kit"))
        self.assertIn("beside", violation("sigil.present.app", "sigil.publish.systems"))

    def test_imports_seen(self):
        found = {t for _l, t in imports_of(PACKAGE / "analyse" / "rules" / "trace.py")}
        self.assertIn("sigil.analyse.rules.state", found)        # a from-import of a module
        found = {t for _l, t in imports_of(PACKAGE / "analyse" / "check.py")}
        self.assertIn("sigil.analyse.rules", found)               # import_module(f"…{name}")
        self.assertIn("sigil.model.sim", found)                   # a lazy import


class LayersAtRunTimeTest(unittest.TestCase):
    def test_lint_loads_no_check_model_or_drawing(self):
        code = ("import sys, io, contextlib\n"
                "from sigil import cli\n"
                "with contextlib.redirect_stdout(io.StringIO()):\n"
                f"    cli.main(['lint', {str(ROOT / 'site' / 'examples' / '02-shop.sigil')!r}])\n"
                "print(sorted(m for m in sys.modules if m.startswith('sigil.')))")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout
        loaded = ast.literal_eval(out.strip().splitlines()[-1])
        for prefix in ("sigil.analyse.check", "sigil.analyse.rules", "sigil.model",
                       "sigil.publish", "sigil.present"):
            self.assertFalse([m for m in loaded if m.startswith(prefix)], (prefix, loaded))


class DialectApiTest(unittest.TestCase):
    NAMES = ("strip_comment", "ARROW_RE", "GLYPH_PATTERNS", "ANY_GLYPH_RE", "LintResult",
             "Diagnostic", "VALID_MODIFIERS", "CALL_RESILIENCE_MODIFIERS",
             "PERMISSION_MODIFIERS", "VALID_LOOP_MODS")

    def test_vocab_carries_the_dialect_api(self):
        from sigil.core import vocab
        for name in self.NAMES:
            self.assertTrue(hasattr(vocab, name), name)

    def test_vocab_semantics(self):
        from sigil.core import vocab
        self.assertEqual(vocab.strip_comment("[A] -> [B]  # note"), "[A] -> [B]  ")
        self.assertEqual(vocab.strip_comment("#!spec"), "#!spec")
        self.assertEqual(vocab.ARROW_RE.findall("[A] <-> [B] -> [C]"), ["<->", "->"])
        self.assertIsNone(vocab.ANY_GLYPH_RE.search("<->"))
        r = vocab.LintResult()
        r.add("warn", 3, "X001", "m")
        self.assertEqual(r.diagnostics[0].format(), "warn:3:X001: m")

    def test_lint_keeps_the_names(self):
        from sigil.analyse import lint
        from sigil.core import vocab
        for name in self.NAMES:
            self.assertIs(getattr(lint, name), getattr(vocab, name), name)


if __name__ == "__main__":
    unittest.main()
