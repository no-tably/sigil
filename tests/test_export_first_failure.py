"""A first export that fails part way removes exactly what it wrote, so the next
export into the same --out is not refused as a folder it did not make."""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_DIR))

from sigil.publish import exporter as export  # noqa: E402

from tests.test_export import READY, Tmp  # noqa: E402


def failing_after(n: int):
    """A write_text that writes `n` files, then fails like a full disk."""
    real = export.write_text
    calls = {"n": 0}

    def write(path, content):
        calls["n"] += 1
        if calls["n"] > n:
            raise OSError(28, "No space left on device")
        real(path, content)
    return write


class FailedFirstExport(Tmp):
    def fail_then_retry(self, out: Path, n: int) -> None:
        with mock.patch.object(export, "write_text", failing_after(n)):
            code, _, err = self.export(READY, out=out.name)
        self.assertEqual(code, 1, err)
        self.assertIn("cannot write", err)
        code, _, err = self.export(READY, out=out.name)
        self.assertEqual(code, 0, err)
        self.assertTrue((out / export.MANIFEST).is_file())

    def test_a_missing_folder_is_gone_again(self):
        out = self.tmp / "out"
        for n in (0, 1, 3):
            with self.subTest(n=n):
                with mock.patch.object(export, "write_text", failing_after(n)):
                    code, _, err = self.export(READY, out="out")
                self.assertEqual(code, 1, err)
                self.assertFalse(out.exists(), sorted(out.rglob("*")) if out.exists() else ())

    def test_missing_parents_are_gone_again(self):
        with mock.patch.object(export, "write_text", failing_after(2)):
            code, _, err = self.export(READY, out="a/b/out")
        self.assertEqual(code, 1, err)
        self.assertFalse((self.tmp / "a").exists())

    def test_an_empty_folder_stays_and_is_empty(self):
        out = self.tmp / "out"
        out.mkdir()
        with mock.patch.object(export, "write_text", failing_after(2)):
            code, _, err = self.export(READY, out="out")
        self.assertEqual(code, 1, err)
        self.assertTrue(out.is_dir())
        self.assertEqual(list(out.iterdir()), [])

    def test_the_next_export_goes_through(self):
        self.fail_then_retry(self.tmp / "out", 2)

    def test_a_failing_manifest_leaves_nothing(self):
        out = self.tmp / "out"
        with mock.patch.object(export, "replace_text", side_effect=OSError("disk")):
            code, _, err = self.export(READY, out="out")
        self.assertEqual(code, 1, err)
        self.assertFalse(out.exists())

    def test_a_failed_re_export_keeps_the_earlier_one(self):
        out = self.tmp / "out"
        self.assertEqual(self.export(READY, out="out")[0], 0)
        manifest = (out / export.MANIFEST).read_text(encoding="utf-8")
        edited = READY.replace("buy({Order})", "buy({Order}, {Coupon})")
        with mock.patch.object(export, "write_text", failing_after(1)):
            code, _, err = self.export(edited, out="out")
        self.assertEqual(code, 1, err)
        self.assertEqual((out / export.MANIFEST).read_text(encoding="utf-8"), manifest)

    def test_a_refused_export_writes_nothing(self):
        code, _, _ = self.export(READY.replace("#!spec", "#!craft"), out="out")
        self.assertEqual(code, 2)
        self.assertFalse((self.tmp / "out").exists())


if __name__ == "__main__":
    unittest.main()
