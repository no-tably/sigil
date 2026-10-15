"""The export example: site/examples/07-export.sigil is a ready spec that exports
clean into five systems, and tests/fixtures/export-edit.sigil (the same spec with
one payload and one description changed) re-exports with the delta it should:
which systems rebuild, which only need a recheck, which stay as they were.

The example's export itself is a golden (tools/golden.py, `export/07-export/`)."""

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_DIR))

import check  # noqa: E402
import export  # noqa: E402
import lint  # noqa: E402

EXAMPLE = _DIR / "site" / "examples" / "07-export.sigil"
EDITED = _DIR / "tests" / "fixtures" / "export-edit.sigil"
TOP = EXAMPLE.stem              # the top system is named after the spec file's stem

# The edit, line by line: (example line, edited line).
EDIT = [("[Stock] -> |Prices| : reprice({Sku}) => {Ack}",
         "[Stock] -> |Prices| : reprice({Sku}, {Count}) => {Ack}"),
        ("  # picks and packs one order at a time",
         "  # picks and packs one order at a time, oldest first")]


def run(argv) -> tuple:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = export.main(argv)
    return code, out.getvalue(), err.getvalue()


def changed_lines(old: str, new: str) -> list:
    """The (old, new) line pairs that differ, for two texts of as many lines."""
    a, b = old.splitlines(), new.splitlines()
    if len(a) != len(b):
        raise ValueError(f"{len(a)} lines against {len(b)}")
    return [(x, y) for x, y in zip(a, b) if x != y]


class TestExampleIsReady(unittest.TestCase):
    def test_spec_mode_and_lint_clean(self):
        text = EXAMPLE.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("#!spec\n"))
        self.assertEqual(lint.lint(text).diagnostics, [])

    def test_gate_lets_both_through(self):
        for path in (EXAMPLE, EDITED):
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertEqual(export.gate(text, None, lint, check), ())

    def test_systems_of_every_kind(self):
        model = export._model().build_model(EXAMPLE.read_text(encoding="utf-8"), TOP)
        kinds = {key: s.kind for key, s in model.systems.items()}
        self.assertEqual(kinds, {TOP: "top", "Catalog": "tree", "Warehouse": "tree",
                                 "Checkout": "expansion", "Fulfilment": "expansion"})

    def test_edit_is_one_payload_and_one_description(self):
        self.assertEqual(changed_lines(EXAMPLE.read_text(encoding="utf-8"),
                                       EDITED.read_text(encoding="utf-8")), EDIT)


class TestEditDelta(unittest.TestCase):
    """Export the example, then the edited spec under the same file name."""

    EXPECTED = {"added": [], "removed": [],
                "rebuild": ["Catalog", "Fulfilment", "Warehouse"],
                "recheck": [TOP], "unchanged": ["Checkout"]}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sigil-export-example-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = self.tmp / "out"
        self.spec = self.tmp / EXAMPLE.name
        shutil.copyfile(EXAMPLE, self.spec)
        code, _, err = run([str(self.spec), "--out", str(self.out)])
        self.assertEqual(code, 0, err)
        self.first = json.loads((self.out / export.MANIFEST).read_text(encoding="utf-8"))
        shutil.copyfile(EDITED, self.spec)

    def lists(self, change: dict) -> dict:
        return {status: sorted(change[status]) for status in export.STATUSES}

    def test_dry_run_delta(self):
        code, out, err = run([str(self.spec), "--out", str(self.out), "--dry-run", "--json"])
        self.assertEqual(code, 0, err)
        change = json.loads(out)
        self.assertEqual(self.lists(change), self.EXPECTED)
        self.assertEqual(change["from"], self.first["spec_hash"])
        self.assertNotEqual(change["to"], change["from"])
        self.assertFalse((self.out / export.DELTA).exists())

    def test_recheck_names_the_changed_interfaces(self):
        _, out, _ = run([str(self.spec), "--out", str(self.out), "--dry-run", "--json"])
        top = json.loads(out)["systems"][TOP]
        self.assertEqual(top["status"], "recheck")
        self.assertEqual(top["because"], ["Catalog", "Warehouse"])
        self.assertEqual(top["old"]["body"], top["new"]["body"])

    def test_payload_moves_interfaces_description_only_the_body(self):
        _, out, _ = run([str(self.spec), "--out", str(self.out), "--dry-run", "--json"])
        systems = json.loads(out)["systems"]
        for key in ("Catalog", "Warehouse"):          # the reprice payload crosses both
            with self.subTest(system=key):
                self.assertNotEqual(systems[key]["old"]["interface"],
                                    systems[key]["new"]["interface"])
        fulfilment = systems["Fulfilment"]           # the picker's description
        self.assertEqual(fulfilment["old"]["interface"], fulfilment["new"]["interface"])
        self.assertNotEqual(fulfilment["old"]["body"], fulfilment["new"]["body"])

    def test_re_export_writes_the_delta(self):
        code, out, err = run([str(self.spec), "--out", str(self.out), "--json"])
        self.assertEqual(code, 0, err)
        written = json.loads((self.out / export.DELTA).read_text(encoding="utf-8"))
        self.assertEqual(written, json.loads(out))
        self.assertEqual(self.lists(written), self.EXPECTED)

    def test_delta_of_the_manifests(self):
        run([str(self.spec), "--out", str(self.out)])
        second = json.loads((self.out / export.MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual(self.lists(export.delta(self.first, second)), self.EXPECTED)


if __name__ == "__main__":
    unittest.main()
