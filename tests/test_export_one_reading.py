"""`sigil export` reads a document once: the gate's reading (lint's walk and
parsed model, the ones check judges) is the one the export's model is built
from, in every form — a first export, a re-export, --json, --dry-run — and
`--mermaid` (with or without --spine) reads it once too."""

import io
import shutil
import sys
import tempfile
import unittest
from collections import Counter
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigil import cli  # noqa: E402
from sigil.core import parse, statements  # noqa: E402

EXAMPLE = ROOT / "site" / "examples" / "07-export.sigil"
NO_HOME = ROOT / "tests" / "fixtures" / "checks" / "export-no-home.sigil"


def counted(stack: ExitStack, counts: Counter, module, name: str):
    """Wrap module.name so each call is counted under `name`."""
    real = getattr(module, name)

    def wrapper(*args, **kwargs):
        counts[name] += 1
        return real(*args, **kwargs)
    stack.enter_context(mock.patch.object(module, name, wrapper))


def reading_calls(argv: list) -> tuple:
    """(exit code, {walks, folds, parses}) of one `sigil` command."""
    counts: Counter = Counter()
    with ExitStack() as stack:
        counted(stack, counts, statements, "read_lines")
        counted(stack, counts, statements, "fold_block_strings")
        counted(stack, counts, parse, "_build")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = cli.main(argv)
    return code, counts


class ExportReadsOnce(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.spec = self.tmp / EXAMPLE.name
        shutil.copyfile(EXAMPLE, self.spec)
        self.out = self.tmp / "out"

    def assertOnce(self, argv: list):
        code, counts = reading_calls(argv)
        self.assertEqual(code, 0, argv)
        self.assertEqual(counts["read_lines"], 1, argv)
        self.assertEqual(counts["fold_block_strings"], 1, argv)
        self.assertEqual(counts["_build"], 1, argv)

    def test_the_folder_form_reads_the_spec_once(self):
        folder = ["export", str(self.spec), "--out", str(self.out)]
        self.assertOnce(folder)                         # a first export
        self.assertTrue((self.out / "manifest.json").is_file())
        self.assertOnce(folder)                         # a re-export (a delta)
        self.assertOnce(folder + ["--json"])

    def test_a_dry_run_reads_the_spec_once(self):
        folder = ["export", str(self.spec), "--out", str(self.out)]
        self.assertOnce(folder + ["--dry-run"])         # nothing exported yet
        self.assertOnce(folder)
        self.assertOnce(folder + ["--dry-run", "--json"])

    def test_the_mermaid_form_reads_the_document_once(self):
        self.assertOnce(["export", str(self.spec), "--mermaid"])
        self.assertOnce(["export", str(self.spec), "--mermaid", "--spine"])

    def test_a_blocked_spec_is_read_once_and_nothing_is_written(self):
        code, counts = reading_calls(["export", str(NO_HOME), "--out", str(self.out)])
        self.assertEqual(code, 2)
        self.assertEqual(counts["read_lines"], 1)
        self.assertEqual(counts["_build"], 1)
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
