"""`sigil export` hardening (patch-0.6.11 R2, from the 2026-10-30 robustness probe):
a bare `loop {` block (#2), a manifest nested too deep (#5), symbolic links in
--out (#12), folders that stay put across exports (#13), slug length and Windows
device names (#14), deletes only within a system's own listed files (#15)."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_DIR))

from sigil import cli  # noqa: E402
from sigil.analyse import check  # noqa: E402
from sigil.model.systems import SLUG_MAX, slug  # noqa: E402
from sigil.publish import delta as dl  # noqa: E402
from sigil.publish import systems as em  # noqa: E402

EXAMPLE = _DIR / "site" / "examples" / "07-export.sigil"

BARE_LOOP = "#!spec\nloop {\n  [A] -> [B]\n}\n"

SHOP = ("#!spec\n(User) -> [Shop] : go({Req}) => {Res}\n"
        "[Shop] := {\n  [A] -> |S| : put({Req}) => {Ack}\n}\n")
SHOP_AND_BANG = ("#!spec\n(User) -> [Shop] : go({Req}) => {Res}\n"
                 "(User) -> [SHOP!] : go({Req}) => {Res}\n"
                 "[Shop] := {\n  [A] -> |S| : put({Req}) => {Ack}\n}\n"
                 "[SHOP!] := {\n  [Z] -> |Q| : put({Req}) => {Ack}\n}\n")

LONG = "漢" * 50
LONG_SPEC = (f"#!spec\n(User) -> [{LONG}] : go({{Req}}) => {{Res}}\n"
             f"[{LONG}] := {{\n  [{'A' * 300}] -> |S| : put({{Req}}) => {{Ack}}\n}}\n")


def run(*argv) -> tuple:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(["export", *argv])
    return code, out.getvalue(), err.getvalue()


def read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


class Tmp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def export(self, text: str, out: str = "out", name: str = "s.sigil", *flags) -> tuple:
        spec = self.tmp / name
        spec.write_text(text, encoding="utf-8")
        return run(str(spec), "--out", str(self.tmp / out), *flags)


class BareLoop(Tmp):
    """#2: `loop {` with no header exports, and SGC153 names it once."""

    def test_exports(self):
        code, _out, err = self.export(BARE_LOOP)
        self.assertEqual(code, 0, err)
        readme = (self.tmp / "out" / "s" / "README.md").read_text(encoding="utf-8")
        self.assertIn("## Control blocks\n\n- loop\n", readme)

    def test_sgc153_says_loop_once(self):
        report = check.check(BARE_LOOP, mode="spec")
        texts = [f.line_text() for f in report.shown if f.rule.id == "SGC153"]
        self.assertEqual(len(texts), 1)
        self.assertIn("ends `loop`", texts[0])
        self.assertNotIn("loop loop", texts[0])


class DeepManifest(Tmp):
    """#5: a manifest.json nested past the JSON reader's depth is refused cleanly."""

    def test_refused(self):
        out = self.tmp / "out"
        out.mkdir()
        (out / "manifest.json").write_text("[" * 200000, encoding="utf-8")
        code, _out, err = self.export(BARE_LOOP)
        self.assertEqual(code, 2)
        self.assertIn("nested too deep", err)
        self.assertNotIn("Traceback", err)


@unittest.skipUnless(hasattr(os, "symlink"), "no symbolic links here")
class Links(Tmp):
    """#12: never write, compare or delete through a symbolic link inside --out."""

    def setUp(self):
        super().setUp()
        self.text = EXAMPLE.read_text(encoding="utf-8")
        code, _out, err = self.export(self.text)
        self.assertEqual(code, 0, err)
        self.out = self.tmp / "out"
        self.outside = self.tmp / "outside"
        self.outside.mkdir()

    def edited(self) -> str:
        return (self.text.replace("[Stock]", "[Stocks]")
                .replace("one price per sku", "one price per SKU"))

    def test_a_linked_file_is_refused(self):
        victim = self.outside / "victim.txt"
        victim.write_text("SECRET\n", encoding="utf-8")
        readme = self.out / "catalog" / "README.md"
        readme.unlink()
        readme.symlink_to(victim)
        for flags in ((), ("--dry-run",)):
            with self.subTest(flags=flags):
                code, _out, err = self.export(self.edited(), "out", "s.sigil", *flags)
                self.assertEqual(code, 2)
                self.assertIn("symbolic link", err)
                self.assertEqual(victim.read_text(encoding="utf-8"), "SECRET\n")

    def test_a_linked_folder_is_refused(self):
        moved = self.outside / "wh"
        (self.out / "warehouse").rename(moved)
        (self.out / "warehouse").symlink_to(moved)
        before = sorted(p.name for p in moved.iterdir())
        code, _out, err = self.export(self.edited())
        self.assertEqual(code, 2)
        self.assertIn("symbolic link", err)
        self.assertEqual(sorted(p.name for p in moved.iterdir()), before)

    def test_a_linked_root_file_is_refused(self):
        target = self.outside / "index.md"
        target.write_text("mine\n", encoding="utf-8")
        (self.out / "README.md").unlink()
        (self.out / "README.md").symlink_to(target)
        code, _out, err = self.export(self.edited())
        self.assertEqual(code, 2)
        self.assertEqual(target.read_text(encoding="utf-8"), "mine\n")

    def test_out_itself_may_be_a_link(self):
        link = self.tmp / "via"
        link.symlink_to(self.out)
        spec = self.tmp / "s.sigil"
        spec.write_text(self.edited(), encoding="utf-8")
        code, _out, err = run(str(spec), "--out", str(link))
        self.assertEqual(code, 0, err)


class StableFolders(Tmp):
    """#13: a system keeps its folder; a new clashing one takes the next free suffix."""

    def test_a_new_clashing_system_never_takes_an_existing_folder(self):
        self.assertEqual(self.export(SHOP)[0], 0)
        out = self.tmp / "out"
        (out / "shop" / "impl.py").write_text("builder code for Shop\n", encoding="utf-8")
        code, _out, err = self.export(SHOP_AND_BANG)
        self.assertEqual(code, 0, err)
        systems = read_json(out / "manifest.json")["systems"]
        self.assertEqual(systems["Shop"]["path"], "shop")
        self.assertEqual(systems["SHOP!"]["path"], "shop-2")
        self.assertEqual(read_json(out / "shop" / "system.json")["name"], "Shop")
        d = read_json(out / "delta.json")
        self.assertEqual(d["added"], ["SHOP!"])
        self.assertNotIn("moved", d["systems"]["Shop"])

    def test_a_removed_systems_folder_is_not_handed_on(self):
        self.assertEqual(self.export(SHOP)[0], 0)
        out = self.tmp / "out"
        (out / "shop" / "impl.py").write_text("builder code for Shop\n", encoding="utf-8")
        only_bang = ("#!spec\n(User) -> [SHOP!] : go({Req}) => {Res}\n"
                     "[SHOP!] := {\n  [Z] -> |Q| : put({Req}) => {Ack}\n}\n")
        code, _out, err = self.export(only_bang)
        self.assertEqual(code, 0, err)
        # Shop is gone, its folder stays for the builder's file: SHOP! goes elsewhere
        systems = read_json(out / "manifest.json")["systems"]
        self.assertEqual(systems["SHOP!"]["path"], "shop-2")
        self.assertEqual(sorted(p.name for p in (out / "shop").iterdir()), ["impl.py"])

    def test_a_first_export_is_unchanged(self):
        keys = ["s", "Shop", "SHOP!", "shop"]
        from sigil.publish.exporter import folder_names
        self.assertEqual(folder_names(keys, None, "s"), em.slugs(keys))

    def test_a_renamed_top_moves_and_the_delta_says_so(self):
        self.assertEqual(self.export(SHOP, name="old.sigil")[0], 0)
        code, printed, err = self.export(SHOP, name="new.sigil")
        self.assertEqual(code, 0, err)
        d = read_json(self.tmp / "out" / "delta.json")
        self.assertEqual(d["renamed"], {"from": "old", "to": "new"})
        self.assertEqual(d["systems"]["new"]["moved"], {"from": "old", "to": "new"})
        self.assertIn("moved      new: old/ → new/", printed)
        self.assertFalse((self.tmp / "out" / "old").exists())

    def test_a_shared_folder_in_a_manifest_is_refused(self):
        obj = {"sigil_export": 1, "systems": {
            k: {"path": "shop", "interface": "i", "body": "b", "components": [],
                "depends_on": []} for k in ("A", "B")}}
        self.assertIn("share folder", dl.manifest_problem(obj))


class Slugs(Tmp):
    """#14: at most SLUG_MAX bytes (a hash keeps long names apart); no device names."""

    def test_bounded_and_distinct(self):
        a, b = slug("漢" * 60 + "a"), slug("漢" * 60 + "b")
        self.assertLessEqual(len(a.encode()), SLUG_MAX)
        self.assertNotEqual(a, b)
        self.assertEqual(slug("Shop"), "shop")           # short ones as before
        self.assertEqual(slug("Café"), "caf-e9")

    def test_windows_device_names(self):
        for name in ("Con", "NUL", "aux", "com1", "LPT9", "prn"):
            with self.subTest(name=name):
                self.assertEqual(slug(name), name.lower() + "-x")
        self.assertEqual(slug("console"), "console")
        self.assertEqual(slug("com10"), "com10")

    def test_a_long_name_exports(self):
        code, _out, err = self.export(LONG_SPEC)
        self.assertEqual(code, 0, err)
        out = self.tmp / "out"
        self.assertTrue((out / "manifest.json").is_file())
        for p in out.rglob("*"):
            self.assertLessEqual(len(p.name.encode()), SLUG_MAX + 8, p.name)

    def test_device_named_files(self):
        code, _out, err = self.export(
            "#!spec\n(User) -> [Con] : go({Req}) => {Res}\n"
            "[Con] := {\n  [Nul] -> |Aux| : put({Req}) => {Ack}\n}\n")
        self.assertEqual(code, 0, err)
        names = {p.name for p in (self.tmp / "out" / "con-x").iterdir()}
        self.assertTrue({"nul-x.md", "aux-x.md"} <= names, names)


class LineEnds(unittest.TestCase):
    """Export reads lines as the walk does (lex.split_lines): a U+2028 inside a
    block string stays in its line."""

    def test_block_string_keeps_a_line_separator(self):
        from sigil.publish import exporter
        flow = {"arrow": "->", "mode": "sync", "text": "one\u2028still one\ntwo"}
        item = exporter.flow_item("[A]", "[B]", flow)
        self.assertIn("  one\u2028still one", item)
        self.assertIn("  two", item)


if __name__ == "__main__":
    unittest.main()
