"""A drawing command when cure cannot be loaded (round 12: the lock's commit in no
archive copy and no store, or a tree at another commit there).

Covers: `sigil view --once`, `frames draw`, `highlight` and `themes` each print one
line "sigil: <the loader's message>" on stderr and exit 2, never a traceback — for
a store without the commit (CureNotFound, naming the install command) and for one
whose tree names another commit (CureMismatch); a command that never draws (lint)
is untouched. Run as subprocesses with CURE_STORE pointed at a temporary store, so
the person's own store is never read. Skipped when the checkout itself holds an
archive copy (sigil/vendor/cure), which the loader takes before any store.
In-process: cli._vendor_unloadable tells the loader's errors from any other.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigil import cli  # noqa: E402
from sigil.vendor.supply import loader  # noqa: E402  (loads cure: the store has it here)

SIGIL = ROOT / "bin" / "sigil"
DOC = ROOT / "site" / "examples" / "02-shop.sigil"
COMMIT = loader.read_lock(ROOT / "sigil" / "vendor" / "cure.lock").commit
DRAWING = (["view", str(DOC), "--once"], ["frames", "draw", str(DOC)],
           ["highlight", str(DOC)], ["themes"])


@unittest.skipIf((ROOT / "sigil" / "vendor" / "cure").exists(),
                 "the checkout holds an archive copy of cure, taken before any store")
class CureMissing(unittest.TestCase):

    def run_sigil(self, store: Path, argv: list) -> subprocess.CompletedProcess:
        env = {**os.environ, "CURE_STORE": str(store)}
        return subprocess.run([sys.executable, str(SIGIL), *argv], capture_output=True,
                              text=True, env=env, timeout=60)

    def assert_one_line(self, done, *needles):
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertNotIn("Traceback", done.stderr)
        lines = done.stderr.splitlines()
        self.assertEqual(len(lines), 1, done.stderr)
        self.assertTrue(lines[0].startswith("sigil: "), lines[0])
        for needle in needles:
            self.assertIn(needle, lines[0])

    def test_not_in_the_store_is_one_line(self):
        with tempfile.TemporaryDirectory() as store:
            for argv in DRAWING:
                with self.subTest(argv=argv[:2]):
                    done = self.run_sigil(Path(store), argv)
                    self.assert_one_line(done, COMMIT, "not found", "store.py install")
                    self.assertEqual(done.stdout, "")

    def test_another_commit_in_the_store_is_one_line(self):
        other = "0" * 40
        with tempfile.TemporaryDirectory() as store:
            tree = Path(store) / COMMIT / "cure"
            tree.mkdir(parents=True)
            (tree / "VENDORED").write_text(f"commit: {other}\n", encoding="utf-8")
            done = self.run_sigil(Path(store), DRAWING[0])
            self.assert_one_line(done, other, COMMIT)

    def test_lint_never_loads_cure(self):
        with tempfile.TemporaryDirectory() as store:
            done = self.run_sigil(Path(store), ["lint", str(DOC)])
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stderr, "")


class Unloadable(unittest.TestCase):

    def test_tells_the_loaders_errors_from_others(self):
        for exc in (loader.CureNotFound("x"), loader.CureMismatch("x"), loader.LockError("x")):
            self.assertTrue(cli._vendor_unloadable(exc), exc)
        for exc in (ImportError("no module"), ValueError("bad"), ModuleNotFoundError("m")):
            self.assertFalse(cli._vendor_unloadable(exc), exc)


if __name__ == "__main__":
    unittest.main()
