"""The vendored cure (round 11): pinned, untouched, Present's alone.

cure sits under sigil/vendor/cure at the commit its VENDORED file and
sigil/vendor/cure.lock name, written by cure's sync tool (sigil/vendor/sync_cure.py
runs it). These tests hold:
- the pin: VENDORED and the lock name one commit; the lock covers every cure
  system Present imports from; nothing in the vendored tree names this machine;
- the direction: cure never imports sigil, and only Present imports cure, at run
  time too (lint, check and export never load it);
- the playground: the cure files it ships import on their own, with no terminal;
- with the cure repository beside this one (skipped otherwise): the vendored tree
  is cure's tree at the commit, byte for byte, and the lock is what the sync
  tool derives from cure's export there.
"""

import ast
import importlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigil.vendor import sync_cure  # noqa: E402

VENDOR = ROOT / "sigil" / "vendor"
CURE = VENDOR / "cure"
PRESENT = ROOT / "sigil" / "present"
EXAMPLE = ROOT / "site" / "examples" / "02-shop.sigil"


def lock() -> dict:
    return json.loads(sync_cure.LOCK.read_text(encoding="utf-8"))


def vendored_note() -> dict:
    lines = (CURE / "VENDORED").read_text(encoding="utf-8").splitlines()
    return dict(ln.split(": ", 1) for ln in lines if ": " in ln)


def cure_repo():
    """The cure repository beside this one (a parent folder's `cure/` with cure's
    sync tool), or None."""
    for parent in ROOT.parents:
        repo = parent / "cure"
        if (repo / "tools" / "sync.py").is_file() and (repo / ".git").exists():
            return repo
    return None


def imports_in(path: Path) -> list:
    """(module, names) for each import in a file; names is () for `import X`."""
    out = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out += [(a.name, ()) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            out.append((node.module, tuple(a.name for a in node.names)))
    return out


def package_of(module: str) -> str:
    """The deepest vendored package holding `module` (cure's systems are its
    packages: `cure.draw.paint.frame` -> `cure.draw.paint`)."""
    parts = module.split(".")
    while parts and not (VENDOR.joinpath(*parts) / "__init__.py").is_file():
        parts.pop()
    return ".".join(parts)


class PinTest(unittest.TestCase):
    def test_one_commit(self):
        self.assertEqual(vendored_note()["commit"], lock()["commit"])
        self.assertRegex(lock()["commit"], r"^[0-9a-f]{40}$")

    def test_lock_lists_the_systems_the_sync_tool_names(self):
        data = lock()
        self.assertEqual(data["repo"], "cure")
        self.assertEqual(list(sync_cure.SYSTEMS), sorted(sync_cure.SYSTEMS))
        for key in ("paths", "interfaces", "bodies"):
            self.assertEqual(sorted(data[key]), list(sync_cure.SYSTEMS), key)
        for name, path in data["paths"].items():
            folder = VENDOR.joinpath(*path.split("."))
            self.assertTrue((folder / "__init__.py").is_file() or folder.with_suffix(".py").is_file(),
                            f"{name}: {path}")

    def test_no_machine_paths(self):
        """The folder ships in every archive: VENDORED's source is portable."""
        self.assertFalse(vendored_note()["source"].startswith("/"))
        for path in sorted(VENDOR.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                text = path.read_text(encoding="utf-8")
                self.assertNotRegex(text, r"/home/[\w.-]+|/Users/[\w.-]+", path)

    def test_present_imports_only_locked_systems(self):
        """Every cure module Present imports from, and every name's defining
        module, sits in a package whose system the lock covers (else: add it to
        SYSTEMS and re-sync, so a cure change to it shows in the lock)."""
        paths = set(lock()["paths"].values())
        missing = []
        for path in sorted(PRESENT.rglob("*.py")):
            for module, names in imports_in(path):
                if module.split(".")[0] != "cure":
                    continue
                where = [module]
                mod = importlib.import_module(module)
                for name in names:
                    obj = getattr(mod, name, None)
                    sub = getattr(obj, "__name__", None) if isinstance(obj, type(mod)) else None
                    where.append(sub or getattr(obj, "__module__", None) or module)
                for m in where:
                    if m.split(".")[0] == "cure" and package_of(m) not in paths | {"cure"}:
                        missing.append(f"{path.relative_to(ROOT)}: {m}")
        self.assertEqual(missing, [], "add their systems to sync_cure.SYSTEMS and re-sync")

    def test_full_paths_follow_parents(self):
        systems = {"cure": {"path": "cure", "parent": None},
                   "Core": {"path": "core", "parent": "cure"},
                   "Text": {"path": "text", "parent": "Core"}}
        self.assertEqual(sync_cure.full_paths(systems),
                         {"cure": "cure", "Core": "cure.core", "Text": "cure.core.text"})
        self.assertEqual(package_of("cure.draw.paint.frame"), "cure.draw.paint")
        self.assertEqual(package_of("cure.core.caps"), "cure.core")
        self.assertEqual(package_of("cure.core.text"), "cure.core.text")

    def test_portable_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            note = Path(tmp) / "VENDORED"
            note.write_text("commit: abc\ndate: d\nsource: /somewhere/cure\n", encoding="utf-8")
            sync_cure.portable_note(note, "cure")
            self.assertEqual(note.read_text(encoding="utf-8"), "commit: abc\ndate: d\nsource: cure\n")


class DirectionTest(unittest.TestCase):
    def test_cure_never_imports_sigil(self):
        bad = [f"{p.relative_to(ROOT)}: {m}" for p in sorted(CURE.rglob("*.py"))
               for m, _n in imports_in(p) if m.split(".")[0] == "sigil"]
        self.assertEqual(bad, [])

    def test_only_present_loads_cure_at_run_time(self):
        """lint, check and the Mermaid export never load cure; a drawing does
        (once Present draws with it), from the vendored folder."""
        code = ("import sys, io, contextlib\n"
                "from sigil import cli\n"
                "out = {}\n"
                "for argv in (['lint', P], ['check', P], ['export', '--mermaid', P]):\n"
                "    with contextlib.redirect_stdout(io.StringIO()):\n"
                "        try: cli.main(argv)\n"
                "        except SystemExit: pass\n"
                "    out[argv[0]] = sorted(m for m in sys.modules if m.split('.')[0] in ('cure', 'sigil')\n"
                "                          and (m.startswith('cure') or m.startswith('sigil.vendor')))\n"
                "import sigil.present, cure\n"
                "out['present'] = cure.__file__\n"
                "print(__import__('json').dumps(out))\n")
        head = f"import sys; sys.path.insert(0, {str(ROOT)!r}); P = {str(EXAMPLE)!r}\n"
        run = subprocess.run([sys.executable, "-I", "-c", head + code],
                             cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stderr)
        out = json.loads(run.stdout)
        for cmd in ("lint", "check", "export"):
            self.assertEqual(out[cmd], [], cmd)
        self.assertEqual(Path(out["present"]), CURE / "__init__.py")


class PlaygroundTest(unittest.TestCase):
    def test_shipped_cure_imports_alone_without_a_terminal(self):
        """The cure files the playground ships (core and draw) import on their
        own, every module of them, and pull in no terminal module."""
        sys.path.insert(0, str(ROOT / "site"))
        try:
            build_site = importlib.import_module("build_site")
        finally:
            sys.path.remove(str(ROOT / "site"))
        shipped = [rel for rel in build_site.PY_TOOLS if rel.startswith("sigil/vendor/cure/")]
        self.assertTrue(any(rel.startswith("sigil/vendor/cure/core/") for rel in shipped))
        self.assertTrue(any(rel.startswith("sigil/vendor/cure/draw/") for rel in shipped))
        for part in ("edge", "interact", "testing"):
            self.assertFalse([r for r in shipped if r.startswith(f"sigil/vendor/cure/{part}/")], part)
        modules = sorted(rel[len("sigil/vendor/"):-len(".py")].replace("/", ".").removesuffix(".__init__")
                         for rel in shipped if rel.endswith(".py"))
        code = ("import importlib, json, sys\n"
                "sys.path.insert(0, 'sigil/vendor')\n"
                "for m in json.loads(sys.stdin.read()): importlib.import_module(m)\n"
                "print(json.dumps(sorted(m for m in ('termios', 'tty', 'select', 'cure.edge',"
                " 'cure.interact') if m in sys.modules)))\n")
        with tempfile.TemporaryDirectory() as tmp:
            for rel in shipped:
                (Path(tmp) / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / rel, Path(tmp) / rel)
            run = subprocess.run([sys.executable, "-I", "-c", code], cwd=tmp, input=json.dumps(modules),
                                 capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout), [])


@unittest.skipIf(cure_repo() is None, "no cure repository beside this one")
class AgainstCureTest(unittest.TestCase):
    def test_vendored_tree_is_cures_at_the_commit(self):
        """Nothing under sigil/vendor/cure was edited: it is `git archive` of the
        locked commit, plus VENDORED."""
        repo, sha = cure_repo(), lock()["commit"]
        archive = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", sha, "cure"],
                                 capture_output=True, check=True).stdout
        want = {}
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            for member in tar.getmembers():
                if member.isfile():
                    want[member.name] = tar.extractfile(member).read()
        have = {p.relative_to(VENDOR).as_posix(): p.read_bytes() for p in sorted(CURE.rglob("*"))
                if p.is_file() and "__pycache__" not in p.parts}
        self.assertEqual(sorted(set(have) - {"cure/VENDORED"}), sorted(want))
        changed = [name for name in want if have.get(name) != want[name]]
        self.assertEqual(changed, [])

    def test_lock_is_the_sync_tools(self):
        repo, sha = cure_repo(), lock()["commit"]
        manifest = json.loads(subprocess.run(
            ["git", "-C", str(repo), "show", f"{sha}:{sync_cure.MANIFEST}"],
            capture_output=True, check=True, text=True).stdout)
        self.assertEqual(sync_cure.lock_of(sha, manifest), lock())


if __name__ == "__main__":
    unittest.main()
