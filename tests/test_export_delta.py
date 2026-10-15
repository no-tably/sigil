"""export.py re-export: the delta (added / removed / rebuild / recheck / unchanged),
delta.json, --json, --dry-run, and rewriting only what changed."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_DIR))

import export  # noqa: E402

READY = """\
#!spec
# a shop and its billing

(User) -> [Shop] : buy({Order}) => {Receipt}
[Shop] -> [Billing] : charge({Order}) => {Receipt} ×3 @after(1s) @timeout(2s) @inv idempotent(key) @fallback("queued")

[Shop] := {
  # keeps the basket
  [Cart] -> |Db| : save({Order}) => {Ack}
}

[Billing] := {
  [Ledger] -> [Shop] : record({Order}) => {Ack}
}
"""

# Reformatted and reordered: every system unchanged.
REORDERED = """\
#!spec
# a shop and its billing

[Billing] := {
  [Ledger]   ->   [Shop] : record({Order}) => {Ack}
}

[Shop] := {
  # keeps the basket
  [Cart] -> |Db| : save({Order}) => {Ack}
}

[Shop] -> [Billing] : charge({Order}) => {Receipt} ×3 @after(1s) @timeout(2s) @inv idempotent(key) @fallback("queued")
(User) -> [Shop] : buy({Order}) => {Receipt}
"""

# A new flow out of the Shop expansion: Shop's interface (and so its body) and
# the top system's body change; Billing's body does not, but it depends on Shop.
NOTIFY = READY.replace("  [Cart] -> |Db| : save({Order}) => {Ack}\n",
                       "  [Cart] -> |Db| : save({Order}) => {Ack}\n"
                       "  [Cart] ~> (User) : notify({Order})\n")

# The Billing expansion gone: [Billing] stays a component of the top system.
NO_BILLING = READY.split("[Billing] := {")[0]

OLD_MTIME = 1_000_000_000


def run(argv) -> tuple:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = export.main(argv)
    return code, out.getvalue(), err.getvalue()


def entry(path, interface, body, deps=()):
    return {"path": path, "interface": interface, "body": body,
            "components": [], "depends_on": list(deps)}


def manifest(systems: dict, spec_hash: str = "s0") -> dict:
    return {"sigil_export": 1, "spec": "x.sigil", "spec_hash": spec_hash,
            "systems": systems}


class TestDelta(unittest.TestCase):
    OLD = manifest({"x": entry("x", "i1", "b1", ["A", "B"]),
                    "A": entry("a", "ia", "ba"),
                    "B": entry("b", "ib", "bb"),
                    "Gone": entry("gone", "ig", "bg")})

    def test_first_export_lists_everything_as_added(self):
        d = export.delta(None, self.OLD)
        self.assertIsNone(d["from"])
        self.assertEqual(d["to"], "s0")
        self.assertEqual(d["added"], ["x", "A", "B", "Gone"])
        for status in ("removed", "rebuild", "recheck", "unchanged"):
            self.assertEqual(d[status], [])
        self.assertEqual(d["systems"]["A"],
                         {"status": "added", "old": None,
                          "new": {"interface": "ia", "body": "ba"}})

    def test_every_status(self):
        new = manifest({"x": entry("x", "i1", "b1", ["A", "B"]),     # A's interface moved
                        "A": entry("a", "ia2", "ba2"),                 # body changed
                        "B": entry("b", "ib", "bb"),                   # same
                        "New": entry("new", "in", "bn")}, "s1")
        d = export.delta(self.OLD, new)
        self.assertEqual(d["sigil_delta"], 1)
        self.assertEqual((d["from"], d["to"]), ("s0", "s1"))
        self.assertEqual(d["added"], ["New"])
        self.assertEqual(d["removed"], ["Gone"])
        self.assertEqual(d["rebuild"], ["A"])
        self.assertEqual(d["recheck"], ["x"])
        self.assertEqual(d["unchanged"], ["B"])
        self.assertEqual(d["systems"]["x"]["because"], ["A"])
        self.assertEqual(d["systems"]["A"]["old"], {"interface": "ia", "body": "ba"})
        self.assertEqual(d["systems"]["A"]["new"], {"interface": "ia2", "body": "ba2"})
        self.assertEqual(d["systems"]["Gone"],
                         {"status": "removed", "old": {"interface": "ig", "body": "bg"},
                          "new": None})
        self.assertEqual(list(d["systems"]), ["x", "A", "B", "New", "Gone"])

    def test_body_change_wins_over_recheck(self):
        new = manifest({"x": entry("x", "i1", "b2", ["A"]), "A": entry("a", "ia2", "ba")})
        self.assertEqual(export.delta(self.OLD, new)["rebuild"], ["x"])

    def test_a_dependency_new_to_the_export_counts_as_changed(self):
        new = manifest({"x": entry("x", "i1", "b1", ["C"]), "C": entry("c", "ic", "bc")})
        d = export.delta(self.OLD, new)
        self.assertEqual(d["recheck"], ["x"])
        self.assertEqual(d["systems"]["x"]["because"], ["C"])

    def test_body_change_of_a_dependency_alone_is_no_recheck(self):
        new = manifest({"x": entry("x", "i1", "b1", ["A"]), "A": entry("a", "ia", "ba2")})
        self.assertEqual(export.delta(self.OLD, new)["unchanged"], ["x"])

    def test_delta_is_pure(self):
        old, new = json.dumps(self.OLD), json.dumps(manifest({}))
        export.delta(self.OLD, manifest({}))
        self.assertEqual((json.dumps(self.OLD), json.dumps(manifest({}))), (old, new))

    def test_dropped_folders(self):
        new = manifest({"A": entry("gone", "ia", "ba"), "B": entry("b", "ib", "bb")})
        self.assertEqual(export.dropped_folders(self.OLD, new), ["a", "x"])
        self.assertEqual(export.dropped_folders(None, new), [])

    def test_words(self):
        new = manifest({"x": entry("x", "i1", "b1", ["A"]), "A": entry("a", "ia2", "ba2"),
                        "B": entry("b", "ib", "bb"), "C": entry("c", "ic", "bc")}, "s1")
        lines = export.delta_lines(export.delta(self.OLD, new))
        self.assertEqual(lines, [
            "since spec s0: 1 added, 1 removed, 1 rebuild, 1 recheck, 1 unchanged",
            "  added      C",
            "  removed    Gone",
            "  rebuild    A (body ba → ba2)",
            "  recheck    x (interface changed: A)",
            "  unchanged  B"])
        self.assertEqual(export.delta_lines(export.delta(None, new)),
                         ["first export: 4 system(s) added"])


class TestManifestProblem(unittest.TestCase):
    def test_an_export_manifest_is_fine(self):
        self.assertIsNone(export.manifest_problem(TestDelta.OLD))

    def test_refused(self):
        bad_path = manifest({"A": entry("../a", "i", "b")})
        no_body = manifest({"A": {"path": "a", "interface": "i", "depends_on": []}})
        no_components = manifest({"A": {"path": "a", "interface": "i", "body": "b",
                                        "depends_on": [], "components": [1]}})
        for obj, word in ((None, "version"), ({"sigil_export": 2}, "version"),
                          ({"sigil_export": 1, "systems": []}, "systems"),
                          (no_body, "body"), (bad_path, "no slug"),
                          (no_components, "components")):
            with self.subTest(obj=obj):
                self.assertIn(word, export.manifest_problem(obj))


class Tmp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.out = self.tmp / "out"

    def tearDown(self):
        self._tmp.cleanup()

    def export(self, text: str, *flags) -> tuple:
        spec = self.tmp / "shop.sigil"
        spec.write_text(text, encoding="utf-8")
        return run([str(spec), "--out", str(self.out), *flags])

    def exported(self, text: str, *flags) -> str:
        code, out, err = self.export(text, *flags)
        self.assertEqual(code, 0, err)
        return out

    def age(self):
        """Every file in the export made old, so a rewrite shows in its mtime."""
        for p in self.out.rglob("*"):
            if p.is_file():
                os.utime(p, (OLD_MTIME, OLD_MTIME))

    def rewritten(self) -> set:
        return {p.relative_to(self.out).as_posix() for p in self.out.rglob("*")
                if p.is_file() and p.stat().st_mtime != OLD_MTIME}

    def files(self) -> dict:
        return {p.relative_to(self.out).as_posix(): p.read_bytes()
                for p in sorted(self.out.rglob("*")) if p.is_file()}

    def delta_json(self) -> dict:
        return json.loads((self.out / "delta.json").read_text(encoding="utf-8"))


class TestWrittenFiles(unittest.TestCase):
    def test_the_names_an_export_wrote(self):
        old = manifest({"A": dict(entry("a", "i", "b"), components=["[Cart]", "|Db|"])})
        self.assertEqual(export.written_files(old),
                         {"a": frozenset({"README.md", "system.json", "cart.md", "db.md"})})
        self.assertEqual(export.written_files(None), {})

    def test_they_match_the_plan(self):
        import export_model
        plan = export.plan_export(export_model.build_model(READY, "shop"), "shop.sigil", READY)
        written = export.written_files(plan.manifest)
        for sp in plan.systems.values():
            with self.subTest(system=sp.key):
                self.assertEqual(written[sp.path], frozenset(sp.files))


class TestFirstExport(Tmp):
    def test_no_delta_file_but_json_lists_every_system_added(self):
        d = json.loads(self.exported(READY, "--json"))
        self.assertFalse((self.out / "delta.json").exists())
        self.assertTrue((self.out / "manifest.json").exists())
        self.assertIsNone(d["from"])
        self.assertEqual(sorted(d["added"]), ["Billing", "Shop", "shop"])

    def test_plain_output_says_so(self):
        self.assertIn("first export: 3 system(s) added", self.exported(READY))


class TestReexport(Tmp):
    def test_formatting_only_is_all_unchanged_and_rewrites_no_system_file(self):
        self.exported(READY)
        self.age()
        d = json.loads(self.exported(REORDERED, "--json"))
        self.assertEqual(sorted(d["unchanged"]), ["Billing", "Shop", "shop"])
        for status in ("added", "removed", "rebuild", "recheck"):
            self.assertEqual(d[status], [])
        self.assertNotEqual(d["from"], d["to"])
        # the spec hash lives in the index and the manifest; nothing else moves
        self.assertEqual(self.rewritten(), {"README.md", "delta.json", "manifest.json"})
        self.assertEqual(self.delta_json(), d)

    def test_the_same_spec_again_writes_nothing(self):
        self.exported(READY)
        self.exported(READY)            # the delta.json of an all-unchanged run
        self.age()
        d = json.loads(self.exported(READY, "--json"))
        self.assertEqual(d["from"], d["to"])
        self.assertEqual(self.rewritten(), set())

    def test_recheck_and_rebuild(self):
        self.exported(READY)
        self.age()
        out = self.exported(NOTIFY)
        d = self.delta_json()
        self.assertEqual(sorted(d["rebuild"]), ["Shop", "shop"])
        self.assertEqual(d["recheck"], ["Billing"])
        self.assertIn("Shop", d["systems"]["Billing"]["because"])
        self.assertIn("recheck    Billing (interface changed:", out)
        rewritten = self.rewritten()
        self.assertFalse([f for f in rewritten if f.startswith("billing/")])
        self.assertIn("shop-2/system.json", rewritten)
        self.assertIn("shop/system.json", rewritten)
        manifest = json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))
        for key, e in manifest["systems"].items():
            self.assertEqual(d["systems"][key]["new"],
                             {"interface": e["interface"], "body": e["body"]})

    def test_removed_system_folder_is_deleted(self):
        self.exported(READY)
        out = self.exported(NO_BILLING)
        d = self.delta_json()
        self.assertEqual(d["removed"], ["Billing"])
        self.assertIsNone(d["systems"]["Billing"]["new"])
        self.assertFalse((self.out / "billing").exists())
        self.assertIn("removed    Billing", out)
        manifest = json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn("Billing", manifest["systems"])

    def test_removed_folder_holding_other_files_is_kept(self):
        self.exported(READY)
        (self.out / "billing" / "ledger.py").write_text("x = 1\n", encoding="utf-8")
        code, _out, err = self.export(NO_BILLING)
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(p.name for p in (self.out / "billing").iterdir()),
                         ["ledger.py"])
        self.assertIn("kept", err)

    def test_a_folder_edited_by_hand_is_written_again(self):
        self.exported(READY)
        before = self.files()
        (self.out / "billing" / "ledger.md").write_text("edited\n", encoding="utf-8")
        (self.out / "shop-2" / "db.md").unlink()
        d = json.loads(self.exported(READY, "--json"))
        self.assertEqual(d["rebuild"], [])
        after = self.files()
        self.assertTrue(after.pop("delta.json"))
        self.assertEqual(after, before)

    def test_a_builders_files_survive_a_reexport(self):
        self.exported(READY)
        mine = {"billing/NOTES.md": "mine\n", "billing/package.json": "{}\n",
                "shop/NOTES.md": "mine too\n", "shop/package.json": "{}\n"}
        for name, text in mine.items():
            (self.out / name).write_text(text, encoding="utf-8")
        self.age()
        d = json.loads(self.exported(NOTIFY, "--json"))
        self.assertEqual(d["unchanged"], [])
        self.assertIn("shop", d["rebuild"])           # a rebuilt system (folder shop/)
        self.assertEqual(d["recheck"], ["Billing"])   # its files are not rewritten
        self.assertFalse([f for f in self.rewritten() if f.startswith("billing/")])
        self.assertIn("shop/system.json", self.rewritten())
        for name, text in mine.items():
            with self.subTest(file=name):
                self.assertEqual((self.out / name).read_text(encoding="utf-8"), text)

    def test_a_builders_files_survive_an_unchanged_reexport(self):
        self.exported(READY)
        (self.out / "billing" / "NOTES.md").write_text("mine\n", encoding="utf-8")
        self.age()
        d = json.loads(self.exported(REORDERED, "--json"))
        self.assertEqual(sorted(d["unchanged"]), ["Billing", "Shop", "shop"])
        self.assertEqual(self.rewritten(), {"README.md", "delta.json", "manifest.json"})
        self.assertTrue((self.out / "billing" / "NOTES.md").exists())

    def test_a_removed_systems_folder_keeps_a_builders_markdown(self):
        self.exported(READY)
        (self.out / "billing" / "NOTES.md").write_text("mine\n", encoding="utf-8")
        code, _out, err = self.export(NO_BILLING)
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(p.name for p in (self.out / "billing").iterdir()),
                         ["NOTES.md"])
        self.assertIn("kept", err)

    def test_delta_written_before_the_manifest(self):
        self.exported(READY)
        order = []
        real_write, real_replace = export.write_text, os.replace

        def write(path, content):
            order.append(Path(path).name)
            real_write(path, content)

        def replace(src, dst):
            order.append(("replace", Path(dst).name))
            real_replace(src, dst)

        with mock.patch.object(export, "write_text", write), \
                mock.patch.object(export.os, "replace", replace):
            self.exported(NOTIFY)
        self.assertEqual(order[-2:], ["delta.json", ("replace", "manifest.json")])

    def test_dry_run_writes_nothing(self):
        self.exported(READY)
        before = self.files()
        out = self.exported(NOTIFY, "--dry-run")
        self.assertEqual(self.files(), before)
        self.assertIn("dry run", out)
        self.assertIn("recheck    Billing", out)
        d = json.loads(self.exported(NOTIFY, "--dry-run", "--json"))
        self.assertEqual(d["recheck"], ["Billing"])
        self.assertEqual(self.files(), before)

    def test_dry_run_on_a_new_folder_makes_nothing(self):
        d = json.loads(self.exported(READY, "--dry-run", "--json"))
        self.assertEqual(len(d["added"]), 3)
        self.assertFalse(self.out.exists())

    def test_unreadable_manifest_is_refused_untouched(self):
        self.exported(READY)
        for text in ("{not json", json.dumps({"sigil_export": 1, "systems": {
                "A": entry("../../etc", "i", "b")}})):
            with self.subTest(text=text):
                (self.out / "manifest.json").write_text(text, encoding="utf-8")
                before = self.files()
                code, _out, err = self.export(NOTIFY)
                self.assertEqual(code, 2)
                self.assertIn("manifest.json", err)
                self.assertEqual(self.files(), before)


if __name__ == "__main__":
    unittest.main()
