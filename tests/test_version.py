"""sigil's version: one constant (sigil.__version__) equal to plugin/meta.json's,
printed by `sigil --version`, and written into an export's manifest.json as
`"sigil"`, where no hash reads it (a new sigil marks nothing to rebuild)."""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_DIR))
sys.path.insert(0, str(_DIR / "tools"))

import sigil  # noqa: E402
from sigil import cli  # noqa: E402
from sigil.publish import delta as export_delta  # noqa: E402
import golden  # noqa: E402

READY = """\
#!spec
# a shop and its billing

(User) -> [Shop] : buy({Order}) => {Receipt}
[Shop] -> [Billing] : charge({Order}) => {Receipt}

[Shop] := {
  # keeps the basket
  [Cart] -> |Db| : save({Order}) => {Ack}
}
"""


def run(argv) -> tuple:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class TestConstant(unittest.TestCase):
    def test_equals_plugin_meta(self):
        meta = json.loads((_DIR / "plugin" / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(sigil.__version__, meta["version"])

    def test_looks_like_a_version(self):
        self.assertRegex(sigil.__version__, r"^\d+\.\d+\.\d+$")


class TestFlag(unittest.TestCase):
    def test_prints_sigil_and_the_version(self):
        self.assertEqual(run(["--version"]), (0, f"sigil {sigil.__version__}\n", ""))

    def test_help_lists_it(self):
        code, out, _err = run(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("sigil --version", out)

    def test_both_entry_points(self):
        for argv in ([str(_DIR / "bin" / "sigil")], [sys.executable, "-m", "sigil"]):
            with self.subTest(argv=argv[-1]):
                r = subprocess.run([*argv, "--version"], cwd=_DIR, capture_output=True,
                                   text=True, timeout=60)
                self.assertEqual((r.returncode, r.stdout, r.stderr),
                                 (0, f"sigil {sigil.__version__}\n", ""))


class TestManifest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.spec = self.root / "shop.sigil"
        self.spec.write_text(READY, encoding="utf-8")
        self.out = self.root / "out"

    def export(self) -> dict:
        code, out, err = run(["export", str(self.spec), "--out", str(self.out), "--json"])
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def manifest(self) -> dict:
        return json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))

    def files(self) -> dict:
        return {p.relative_to(self.out).as_posix(): p.read_bytes()
                for p in self.out.rglob("*") if p.is_file() and p.name != "manifest.json"}

    def test_names_the_version_that_wrote_it(self):
        self.export()
        m = self.manifest()
        self.assertEqual(m["sigil"], sigil.__version__)
        self.assertEqual(list(m)[:2], ["sigil_export", "sigil"])

    def test_a_new_version_marks_nothing(self):
        self.export()
        before = self.files()
        with mock.patch.object(sigil, "__version__", "99.0.0"):
            change = self.export()
        self.assertEqual(self.manifest()["sigil"], "99.0.0")
        self.assertEqual((change["added"], change["removed"], change["rebuild"],
                          change["recheck"]), ([], [], [], []))
        self.assertEqual(sorted(change["unchanged"]), sorted(self.manifest()["systems"]))
        after = self.files()
        after.pop("delta.json", None)
        before.pop("delta.json", None)
        self.assertEqual(after, before)      # only the manifest (and delta.json) rewritten

    def test_the_plan_takes_the_version_it_is_given(self):
        from sigil.publish import exporter, systems
        model = systems.build_model(READY, "shop")
        self.assertEqual(exporter.plan_export(model, "s.sigil", READY, version="1.2.3")
                         .manifest["sigil"], "1.2.3")

    def test_the_delta_ignores_the_field(self):
        self.export()
        old = self.manifest()
        new = dict(old, sigil="99.0.0")
        change = export_delta.delta(old, new)
        self.assertEqual(change["unchanged"], list(old["systems"]))
        self.assertNotIn("99.0.0", json.dumps(change))


class TestGolden(unittest.TestCase):
    def test_golden_keeps_the_field_as_a_placeholder(self):
        text = json.dumps({"sigil_export": 1, "sigil": sigil.__version__}, indent=2)
        self.assertIn(golden.VERSION_FIELD, golden.without_version(text))
        self.assertNotIn(sigil.__version__, golden.without_version(text))

    def test_the_export_golden_has_the_placeholder(self):
        text = (_DIR / "tests" / "golden" / "export" / "07-export" / "manifest.json"
                ).read_text(encoding="utf-8")
        self.assertIn(golden.VERSION_FIELD, text)


if __name__ == "__main__":
    unittest.main()
