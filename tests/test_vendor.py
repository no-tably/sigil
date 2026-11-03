"""cure, from one store (round 12): pinned by a lock, loaded by cure's own loader.

The repository keeps only sigil/vendor/cure.lock (cure's lock format: commit and
source), sigil/vendor/supply/ (cure's loader and store, copied verbatim) and
sigil/vendor/cure.systems.json (the contracts of the cure systems sigil stands on,
at the lock's commit). The tree comes from an archive's own vendor/cure (build.py
bundles it from the store), else the shared store ($CURE_STORE/<commit>/cure).
These tests hold:
- the pin: the lock reads as cure's lock, names a URL, and is the commit the
  systems file and the loaded tree name; the supply copies are cure's files at that
  commit; the systems file covers every cure system Present imports from; nothing
  under sigil/vendor names this machine; no cure tree is in git;
- the loading: an archive's copy wins over the store, a copy at another commit is
  refused with cure's CureMismatch, no copy anywhere is cure's CureNotFound naming
  the install command; a built archive draws with an empty store;
- build --check: the bundled tree must be the lock's commit and the store's files;
- the direction: cure never imports sigil, and only Present imports cure, at run
  time too (lint, check and export never load it);
- the playground: the cure files it ships import on their own, with no terminal;
- with the cure repository beside this one (skipped otherwise): the store's tree
  is cure's `git archive` at the commit, the supply copies and the systems file are
  what cure has there, and sync_cure.py writes exactly the committed files.
"""

import ast
import importlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import sigil.vendor as vendor  # noqa: E402  (loads cure: the store, at the lock's commit)
from sigil.vendor import sync_cure  # noqa: E402
from sigil.vendor.supply import loader  # noqa: E402

VENDOR = ROOT / "sigil" / "vendor"
PRESENT = ROOT / "sigil" / "present"
EXAMPLE = ROOT / "site" / "examples" / "02-shop.sigil"
TREE = vendor.FOLDER / "cure"                   # the cure this process draws with


def lock() -> loader.Lock:
    return loader.read_lock(sync_cure.LOCK)


def systems() -> dict:
    return json.loads(sync_cure.SYSTEMS_FILE.read_text(encoding="utf-8"))


def load_build():
    spec = importlib.util.spec_from_file_location("sigil_build_vendor", ROOT / "build.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sigil_build_vendor"] = mod
    spec.loader.exec_module(mod)
    return mod


def cure_repo():
    """The cure repository beside this one (a parent folder's `cure/` holding
    cure's supply), or None."""
    for parent in ROOT.parents:
        repo = parent / "cure"
        if (repo / "cure" / "supply" / "store.py").is_file() and (repo / ".git").exists():
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
    """The deepest cure package holding `module` (cure's systems are its
    packages: `cure.draw.paint.frame` -> `cure.draw.paint`)."""
    parts = module.split(".")
    while parts and not (vendor.FOLDER.joinpath(*parts) / "__init__.py").is_file():
        parts.pop()
    return ".".join(parts)


def files_of(top: Path) -> dict:
    return {p.relative_to(top).as_posix(): p.read_bytes() for p in sorted(top.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts}


def package_copy(dest: Path, vendored: str | None = None) -> Path:
    """sigil's package without its layers, in dest: sigil/__init__.py and
    sigil/vendor's own files (enough to `import sigil.vendor`), plus a cure tree at
    sigil/vendor/cure when `vendored` names a VENDORED text (a copy of the loaded
    tree with that note). Returns dest, resolved."""
    for rel in ("sigil/__init__.py", "sigil/vendor/__init__.py", "sigil/vendor/cure.lock",
                *(f"sigil/vendor/supply/{n}" for n in sync_cure.SUPPLY_FILES)):
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, dest / rel)
    if vendored is not None:
        shutil.copytree(TREE, dest / "sigil" / "vendor" / "cure",
                        ignore=shutil.ignore_patterns("__pycache__"))
        (dest / "sigil" / "vendor" / "cure" / "VENDORED").write_text(vendored, encoding="utf-8")
    return dest.resolve()


def run_python(code: str, cwd: Path, store: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "CURE_STORE": str(store)}
    return subprocess.run([sys.executable, "-I", "-c", code], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=120)


LOADED = ("import sys; sys.path.insert(0, '.')\n"
          "import sigil.vendor as v, cure\n"
          "print(v.FOLDER); print(cure.__file__)\n")


class PinTest(unittest.TestCase):
    def test_the_lock_is_cures_format(self):
        """commit and source only (cure's loader reads it), the source a URL."""
        fields = loader.read_fields(sync_cure.LOCK)
        self.assertEqual(sorted(fields), ["commit", "source"])
        self.assertRegex(lock().commit, r"^[0-9a-f]{40}$")
        self.assertRegex(lock().source, r"^https://")
        self.assertEqual(sync_cure.LOCK.read_text(encoding="utf-8"), sync_cure.lock_text(lock()))

    def test_one_commit(self):
        """The lock, the systems file and the tree loaded name one commit."""
        self.assertEqual(systems()["commit"], lock().commit)
        self.assertEqual(loader.read_lock(TREE / "VENDORED").commit, lock().commit)

    def test_supply_is_cures_verbatim(self):
        """sigil/vendor/supply holds cure's supply files at the lock's commit, byte
        for byte (the loaded tree is that commit's, as its VENDORED says)."""
        for name in sync_cure.SUPPLY_FILES:
            self.assertEqual((sync_cure.SUPPLY / name).read_bytes(),
                             (TREE / "supply" / name).read_bytes(), name)
        self.assertEqual(sorted(p.name for p in sync_cure.SUPPLY.glob("*.py")),
                         sorted(sync_cure.SUPPLY_FILES))

    def test_no_cure_tree_in_git(self):
        """Only the lock is committed: the tree comes from the store (or an archive)."""
        run = subprocess.run(["git", "-C", str(ROOT), "ls-files", "sigil/vendor"],
                             capture_output=True, text=True)
        if run.returncode:
            self.skipTest("not a git checkout")
        tracked = run.stdout.split()
        self.assertFalse([t for t in tracked if t.startswith("sigil/vendor/cure/")])
        self.assertIn("sigil/vendor/cure.lock", tracked)
        ignored = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q",
                                  "sigil/vendor/cure/VENDORED"])
        self.assertEqual(ignored.returncode, 0)

    def test_systems_file_lists_the_systems_the_sync_tool_names(self):
        data = systems()
        self.assertEqual(list(sync_cure.SYSTEMS), sorted(sync_cure.SYSTEMS))
        for key in ("paths", "interfaces", "bodies"):
            self.assertEqual(sorted(data[key]), list(sync_cure.SYSTEMS), key)
        for name, path in data["paths"].items():
            folder = vendor.FOLDER.joinpath(*path.split("."))
            self.assertTrue((folder / "__init__.py").is_file() or folder.with_suffix(".py").is_file(),
                            f"{name}: {path}")

    def test_no_machine_paths(self):
        """sigil/vendor ships in every archive: nothing of its own names this
        machine, nor does the VENDORED an archive gets."""
        for path in sorted(VENDOR.rglob("*")):
            rel = path.relative_to(VENDOR).parts
            if path.is_file() and "__pycache__" not in rel and rel[0] != "cure":
                text = path.read_text(encoding="utf-8")
                self.assertNotRegex(text, r"/home/[\w.-]+|/Users/[\w.-]+", path)
        self.assertFalse(loader.read_lock(TREE / "VENDORED").source.startswith("/"))

    def test_present_imports_only_locked_systems(self):
        """Every cure module Present imports from, and every name's defining
        module, sits in a package whose system the systems file covers (else: add
        it to SYSTEMS and re-sync, so a cure change to it shows in the file)."""
        paths = set(systems()["paths"].values())
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
        tree = {"cure": {"path": "cure", "parent": None},
                "Core": {"path": "core", "parent": "cure"},
                "Text": {"path": "text", "parent": "Core"}}
        self.assertEqual(sync_cure.full_paths(tree),
                         {"cure": "cure", "Core": "cure.core", "Text": "cure.core.text"})
        self.assertEqual(package_of("cure.draw.paint.frame"), "cure.draw.paint")
        self.assertEqual(package_of("cure.core.caps"), "cure.core")
        self.assertEqual(package_of("cure.core.text"), "cure.core.text")


class LoadTest(unittest.TestCase):
    def test_the_checkout_loads_the_store(self):
        """With no tree beside the lock, cure comes from the store's folder for
        the lock's commit."""
        if (VENDOR / "cure").exists():
            self.skipTest("a cure tree is left at sigil/vendor/cure")
        import cure
        self.assertEqual(vendor.FOLDER, loader.store_root() / lock().commit)
        self.assertEqual(Path(cure.__file__).parent, TREE)

    def test_an_archive_copy_wins_over_the_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = package_copy(Path(tmp) / "pkg", (TREE / "VENDORED").read_text(encoding="utf-8"))
            run = run_python(LOADED, root, Path(tmp) / "empty-store")
        self.assertEqual(run.returncode, 0, run.stderr)
        folder, init = run.stdout.split()
        self.assertEqual(Path(folder), root / "sigil" / "vendor")
        self.assertEqual(Path(init), root / "sigil" / "vendor" / "cure" / "__init__.py")

    def test_a_copy_at_another_commit_is_refused(self):
        """cure's CureMismatch, naming both commits; the store is not tried."""
        other = "0" * 40
        with tempfile.TemporaryDirectory() as tmp:
            root = package_copy(Path(tmp) / "pkg", f"commit: {other}\nsource: x\n")
            run = run_python(LOADED, root, loader.store_root())
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("CureMismatch", run.stderr)
        self.assertIn(f"is cure at {other}, not the lock's {lock().commit}", run.stderr)

    def test_no_copy_anywhere_names_the_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = package_copy(Path(tmp) / "pkg")
            run = run_python(LOADED, root, Path(tmp) / "empty-store")
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("CureNotFound", run.stderr)
        self.assertIn(f"store.py install {lock().commit} --from {lock().source}", run.stderr)
        self.assertIn(vendor.STORE_TOOL, run.stderr)


class ArchiveTest(unittest.TestCase):
    """One built target: its archive carries cure and draws with an empty store;
    build --check holds the bundle to the lock."""

    @classmethod
    def setUpClass(cls):
        cls.build = load_build()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name).resolve()
        cls.out = cls.tmp / "dist"
        cls.build.build(cls.out, ["claude"])

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def scripts(self, top: Path) -> Path:
        return next(top.rglob("skills/sigil/scripts"))

    def test_the_bundle_is_the_stores_tree(self):
        bundled = self.scripts(self.out / "claude") / "sigil" / "vendor" / "cure"
        self.assertEqual(files_of(bundled), files_of(TREE))
        self.assertEqual(self.build.check(self.out, ["claude"]), [])

    def test_an_archive_draws_with_an_empty_store(self):
        """The marketplace zip, unpacked: `bin/sigil view --once` draws what the
        checkout draws, with CURE_STORE an empty folder."""
        zips = sorted(self.out.glob("sigil-claude-marketplace-*.zip"))
        self.assertEqual(len(zips), 1)
        unpacked = self.tmp / "unpacked"
        with zipfile.ZipFile(zips[0]) as z:
            z.extractall(unpacked)
        command = self.scripts(unpacked) / "bin" / "sigil"
        empty = self.tmp / "empty-store"
        empty.mkdir()
        env = {**os.environ, "CURE_STORE": str(empty)}
        argv = ["view", str(EXAMPLE), "--once", "--width", "100"]
        got = subprocess.run([sys.executable, "-I", str(command), *argv], cwd=self.tmp, env=env,
                             capture_output=True, text=True, timeout=120)
        want = subprocess.run([sys.executable, "-I", str(ROOT / "bin" / "sigil"), *argv],
                              cwd=self.tmp, capture_output=True, text=True, timeout=120)
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertEqual(want.returncode, 0, want.stderr)
        self.assertEqual(got.stdout, want.stdout)
        self.assertEqual(list(empty.iterdir()), [])

    def test_check_refuses_a_bundle_off_the_lock(self):
        copy = self.tmp / "tampered"
        shutil.copytree(self.out, copy, symlinks=True)
        cure = self.scripts(copy / "claude") / "sigil" / "vendor" / "cure"
        (cure / "core" / "__init__.py").write_text("# edited\n", encoding="utf-8")
        errs = self.build.check(copy, ["claude"])
        self.assertTrue([e for e in errs if "core/__init__.py: not the store's cure" in e], errs)
        (cure / "VENDORED").write_text(f"commit: {'0' * 40}\n", encoding="utf-8")
        errs = self.build.check(copy, ["claude"])
        self.assertTrue([e for e in errs if "is not the bundled cure's" in e], errs)


class DirectionTest(unittest.TestCase):
    def test_cure_never_imports_sigil(self):
        bad = [f"{p.relative_to(TREE)}: {m}" for p in sorted(TREE.rglob("*.py"))
               for m, _n in imports_in(p) if m.split(".")[0] == "sigil"]
        self.assertEqual(bad, [])

    def test_only_present_loads_cure_at_run_time(self):
        """lint, check and the Mermaid export never load cure; a drawing does
        (once Present draws with it), from the folder the loader finds."""
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
        self.assertEqual(Path(out["present"]), TREE / "__init__.py")


class PlaygroundTest(unittest.TestCase):
    def test_shipped_cure_imports_alone_without_a_terminal(self):
        """The cure files the playground ships (core and draw, from the store)
        import on their own, every module of them, and pull in no terminal module;
        sigil.vendor loads them as an archive's copy."""
        sys.path.insert(0, str(ROOT / "site"))
        try:
            build_site = importlib.import_module("build_site")
        finally:
            sys.path.remove(str(ROOT / "site"))
        shipped = [rel for rel in build_site.PY_TOOLS if rel.startswith("sigil/vendor/cure/")]
        self.assertIn("sigil/vendor/cure/VENDORED", shipped)
        self.assertIn("sigil/vendor/cure.lock", build_site.PY_TOOLS)
        self.assertIn("sigil/vendor/supply/loader.py", build_site.PY_TOOLS)
        self.assertNotIn("sigil/vendor/supply/store.py", build_site.PY_TOOLS)
        self.assertTrue(any(rel.startswith("sigil/vendor/cure/core/") for rel in shipped))
        self.assertTrue(any(rel.startswith("sigil/vendor/cure/draw/") for rel in shipped))
        for part in ("edge", "interact", "testing", "supply"):
            self.assertFalse([r for r in shipped if r.startswith(f"sigil/vendor/cure/{part}/")], part)
        for rel in shipped:
            self.assertEqual(build_site.SOURCES[rel], TREE / rel[len("sigil/vendor/cure/"):], rel)
        modules = sorted(rel[len("sigil/vendor/"):-len(".py")].replace("/", ".").removesuffix(".__init__")
                         for rel in shipped if rel.endswith(".py"))
        code = ("import importlib, json, sys\n"
                "sys.path.insert(0, '.')\n"
                "import sigil.vendor as v\n"
                "assert v.FOLDER.name == 'vendor', v.FOLDER\n"
                "for m in json.loads(sys.stdin.read()): importlib.import_module(m)\n"
                "print(json.dumps(sorted(m for m in ('termios', 'tty', 'select', 'cure.edge',"
                " 'cure.interact') if m in sys.modules)))\n")
        with tempfile.TemporaryDirectory() as tmp:
            for rel in build_site.PY_TOOLS:
                if rel.startswith("sigil/vendor/") or rel == "sigil/__init__.py":
                    (Path(tmp) / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(build_site.SOURCES[rel], Path(tmp) / rel)
            env = {**os.environ, "CURE_STORE": str(Path(tmp) / "empty-store")}
            run = subprocess.run([sys.executable, "-I", "-c", code], cwd=tmp, input=json.dumps(modules),
                                 env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout), [])


@unittest.skipIf(cure_repo() is None, "no cure repository beside this one")
class AgainstCureTest(unittest.TestCase):
    def test_the_stores_tree_is_cures_at_the_commit(self):
        """The tree sigil loads is `git archive` of the locked commit, plus VENDORED."""
        repo, sha = cure_repo(), lock().commit
        archive = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", sha, "cure"],
                                 capture_output=True, check=True).stdout
        want = {}
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            for member in tar.getmembers():
                if member.isfile():
                    want[member.name[len("cure/"):]] = tar.extractfile(member).read()
        have = files_of(TREE)
        self.assertEqual(sorted(set(have) - {"VENDORED"}), sorted(want))
        self.assertEqual([name for name in want if have.get(name) != want[name]], [])

    def test_supply_and_systems_are_cures_at_the_commit(self):
        repo, sha = cure_repo(), lock().commit
        for name in sync_cure.SUPPLY_FILES:
            blob = subprocess.run(["git", "-C", str(repo), "show", f"{sha}:cure/supply/{name}"],
                                  capture_output=True, check=True).stdout
            self.assertEqual((sync_cure.SUPPLY / name).read_bytes(), blob, name)
        self.assertEqual(sync_cure.systems_of(sha, sync_cure.manifest_at(sha, str(repo), Path("/"))),
                         systems())

    def test_sync_writes_the_committed_files(self):
        """sync_cure.sync from a clone of cure (origin set to the lock's source)
        into a fresh store writes exactly the lock, the systems file and the
        supply copies committed here, and the store's tree is the one loaded."""
        repo, pin = cure_repo(), lock()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            clone = tmp / "cure"
            subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", str(repo), str(clone)],
                           check=True, capture_output=True)
            subprocess.run(["git", "-C", str(clone), "remote", "set-url", "origin", pin.source],
                           check=True, capture_output=True)
            out = tmp / "vendor"
            (out / "supply").mkdir(parents=True)
            saved = (sync_cure.LOCK, sync_cure.SYSTEMS_FILE, sync_cure.SUPPLY)
            sync_cure.LOCK, sync_cure.SYSTEMS_FILE, sync_cure.SUPPLY = (
                out / "cure.lock", out / "cure.systems.json", out / "supply")
            try:
                sync_cure.sync(pin.commit, str(clone), tmp / "store")
            finally:
                sync_cure.LOCK, sync_cure.SYSTEMS_FILE, sync_cure.SUPPLY = saved
            want = {f"supply/{n}": (VENDOR / "supply" / n).read_bytes() for n in sync_cure.SUPPLY_FILES}
            want["cure.lock"] = sync_cure.LOCK.read_bytes()
            want["cure.systems.json"] = sync_cure.SYSTEMS_FILE.read_bytes()
            self.assertEqual(files_of(out), want)
            self.assertEqual(files_of(tmp / "store" / pin.commit / "cure"), files_of(TREE))


if __name__ == "__main__":
    unittest.main()
