"""The export as a consumer reads it, probed with a dialect
(tests/fixtures/dialect_export_probe.py: DECLARATIONS, VERSION, a tokenizer
that puts Node.attrs on its glyphs).

Covers:
  - per-component hashes: `hashes` on every component in system.json and
    `component_hashes` per system in manifest.json; a flow's modifier moves
    both ends' interface hash, a description only the body hash; a reorder or
    reformat none;
  - `#&` declarations: `declarations: [{name, body, line}]` on the system whose
    scope holds them (top level → top system, an expansion's body → that
    system), the body verbatim (statements.declaration_body), in the body hash
    and not the interface hash; a line move changes no hash;
  - `--name NAME` names the top system (folder and `--mermaid --spine`), the
    stem by default; no hash depends on it; a name like a top-level service's
    expansion makes that expansion the top's face (one system, one folder;
    the model's tests cover the kinds that keep a system and `NAME (top)`);
    an empty name, or one without --spine on --mermaid, is refused;
  - delta.json on every export, a first one listing every system as added; a
    renamed top (--name or the stem) is `renamed`, not added and removed;
  - manifest `dialect`: {name, version} with a dialect (version only when the
    module defines VERSION), absent without one;
  - `lines` (1-based) per component and per flow;
  - a dialect tokenizer's Node.attrs as `attrs` (none on a core component);
    a dialect glyph written in its NODE_KINDS brackets.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_DIR))

from sigil import cli  # noqa: E402
from sigil.core import dialects  # noqa: E402
from sigil.core.statements import declaration_body  # noqa: E402
from sigil.publish import exporter  # noqa: E402
from sigil.publish import systems as em  # noqa: E402

PROBE = _DIR / "tests" / "fixtures" / "dialect_export_probe.py"

SPEC = """#!spec
#& probe {
  name: shop
  root: src/
}

(Shopper) -> [Api] : {Order}
[Api] ~> [[Ledger]] : {Entry} @at(src/api)
# the api's door
[Api] := {
  #& probe inner
  [Front] -> [Back] : {Req}
}
"""


def run(*argv) -> tuple:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class Tmp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def export(self, *flags, text: str = SPEC, stem: str = "shop", out: str = "out"):
        spec = self.tmp / f"{stem}.sigil"
        spec.write_text(text, encoding="utf-8")
        code, printed, err = run("export", str(spec), "--out", str(self.tmp / out),
                                 "--dialect", str(PROBE), *flags)
        self.assertEqual(code, 0, err)
        return self.tmp / out

    def systems(self, out: Path) -> dict:
        """{system key: its system.json}."""
        manifest = read_json(out / "manifest.json")
        return {k: read_json(out / e["path"] / "system.json")
                for k, e in manifest["systems"].items()}

    def components(self, out: Path) -> dict:
        """{glyph: its form in system.json}, every system."""
        return {c["glyph"]: c for s in self.systems(out).values()
                for c in s.get("components", [])}


class ComponentHashes(Tmp):
    def test_every_component_has_hashes_in_system_json_and_manifest(self):
        out = self.export()
        manifest = read_json(out / "manifest.json")
        for key, form in self.systems(out).items():
            entry = manifest["systems"][key]
            with self.subTest(system=key):
                self.assertEqual(list(entry["component_hashes"]), entry["components"])
                for c in form["components"]:
                    self.assertEqual(set(c["hashes"]), {"interface", "body"})
                    self.assertEqual(entry["component_hashes"][c["glyph"]], c["hashes"])

    def test_a_flow_modifier_moves_both_ends_interface(self):
        a = self.components(self.export(out="a"))
        b = self.components(self.export(text=SPEC.replace("@at(src/api)", "@at(src/x)"), out="b"))
        for glyph in ("[Api]", "[[Ledger]]"):
            with self.subTest(glyph=glyph):
                self.assertNotEqual(a[glyph]["hashes"]["interface"],
                                    b[glyph]["hashes"]["interface"])
        self.assertEqual(a["(Shopper)"]["hashes"], b["(Shopper)"]["hashes"])

    def test_a_description_moves_only_the_body(self):
        a = self.components(self.export(out="a"))
        b = self.components(self.export(text=SPEC.replace("the api's door", "the door"), out="b"))
        self.assertEqual(a["[Api]"]["hashes"]["interface"], b["[Api]"]["hashes"]["interface"])
        self.assertNotEqual(a["[Api]"]["hashes"]["body"], b["[Api]"]["hashes"]["body"])

    def test_moving_lines_moves_no_hash(self):
        moved = SPEC.replace("\n(Shopper)", "\n\n\n(Shopper)")
        a, b = self.export(out="a"), self.export(text=moved, out="b")
        self.assertEqual(read_json(a / "manifest.json")["systems"],
                         read_json(b / "manifest.json")["systems"])
        self.assertNotEqual(self.components(a)["[Api]"]["lines"],
                            self.components(b)["[Api]"]["lines"])


class Declarations(Tmp):
    def test_on_the_system_whose_scope_holds_them(self):
        forms = self.systems(self.export())
        self.assertEqual(forms["shop"]["declarations"],
                         [{"name": "probe", "body": "  name: shop\n  root: src/", "line": 2}])
        self.assertEqual(forms["Api"]["declarations"],
                         [{"name": "probe", "body": "inner", "line": 11}])

    def test_in_the_body_hash_not_the_interface(self):
        a = read_json(self.export(out="a") / "manifest.json")["systems"]["shop"]
        b = read_json(self.export(text=SPEC.replace("root: src/", "root: lib/"), out="b")
                      / "manifest.json")["systems"]["shop"]
        self.assertEqual(a["interface"], b["interface"])
        self.assertNotEqual(a["body"], b["body"])
        self.assertEqual(a["component_hashes"], b["component_hashes"])

    def test_body_forms(self):
        cases = [
            (["#& h a  b "], "a  b"),
            (["#& h"], ""),
            (["#& h { a: 1 }"], "a: 1"),
            (["#& h ~{ a", "  b }"], "a\n  b"),
            (["  #& h {", "  x: \"}\"  # c", "}"], '  x: "}"  # c'),
            (["#& h {", "", "  a", "}"], "\n  a"),
        ]
        for lines, body in cases:
            with self.subTest(lines=lines):
                self.assertEqual(declaration_body(lines), body)


class Name(Tmp):
    def test_the_stem_by_default_and_name_when_given(self):
        self.assertIn("shop", self.systems(self.export(out="a")))
        out = self.export("--name", "store", "--json", out="b")
        manifest = read_json(out / "manifest.json")
        self.assertEqual(list(manifest["systems"])[0], "store")
        self.assertEqual(manifest["systems"]["store"]["path"], "store")
        self.assertEqual(manifest["spec"], "shop.sigil")
        self.assertEqual(read_json(out / "store" / "system.json")["name"], "store")

    def test_no_hash_depends_on_it(self):
        def hashes(out):
            return [(e["interface"], e["body"], e["component_hashes"])
                    for e in read_json(out / "manifest.json")["systems"].values()]
        a = self.export(out="a")
        b = self.export("--name", "store", out="b")
        c = self.export(stem="renamed", out="c")
        self.assertEqual(hashes(a), hashes(b))
        self.assertEqual(hashes(a), hashes(c))

    def test_an_empty_name_is_refused(self):
        spec = self.tmp / "shop.sigil"
        spec.write_text(SPEC, encoding="utf-8")
        for form in (["--out", str(self.tmp / "o")], ["--mermaid", "--spine"]):
            err = io.StringIO()
            with self.subTest(form=form), contextlib.redirect_stderr(err), \
                    self.assertRaises(SystemExit) as stop:
                cli.main(["export", str(spec), *form, "--name", " "])
            self.assertEqual(stop.exception.code, 2)
            self.assertIn("--name", err.getvalue())
        self.assertFalse((self.tmp / "o").exists())

    def test_spine_takes_it(self):
        spec = self.tmp / "shop.sigil"
        spec.write_text(SPEC, encoding="utf-8")
        code, out, err = run("export", str(spec), "--mermaid", "--spine",
                             "--dialect", str(PROBE), "--name", "Api")
        self.assertEqual(code, 0, err)
        _code, plain, _err = run("export", str(spec), "--mermaid", "--spine",
                                 "--dialect", str(PROBE))
        # named like [Api], the top is its expansion: no subgraph of its own
        self.assertIn('subgraph system__api["Api"]', plain)
        self.assertNotIn("subgraph", out)
        self.assertIn('Front_service["Front"]', out)


    def test_a_name_like_a_top_level_service_makes_its_expansion_the_top(self):
        out = self.export("--name", "Api", out="b")
        manifest = read_json(out / "manifest.json")
        self.assertEqual(manifest["top"], "Api")
        self.assertEqual(list(manifest["systems"]), ["Api"])
        self.assertEqual(manifest["systems"]["Api"]["path"], "api")
        top = read_json(out / "api" / "system.json")
        self.assertEqual(top["face"], "[Api]")
        self.assertEqual(sorted(c["glyph"] for c in top["components"]),
                         ["(Shopper)", "[Api]", "[Back]", "[Front]", "[[Ledger]]"])
        # the expansion's `#&` declaration is the top's now, beside the document's
        self.assertEqual([d["name"] for d in top["declarations"]], ["probe", "probe"])
        self.assertEqual(top["description"], ["the api's door"])
        self.assertFalse((out / "api-2").exists())

    def test_mermaid_without_spine_refuses_it(self):
        spec = self.tmp / "shop.sigil"
        spec.write_text(SPEC, encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as stop:
            cli.main(["export", str(spec), "--mermaid", "--name", "x"])
        self.assertEqual(stop.exception.code, 2)
        self.assertIn("--spine", err.getvalue())


class Delta(Tmp):
    def test_a_renamed_top_is_the_same_system(self):
        self.export(out="o")
        for flags, stem in ((("--name", "store"), "shop"), ((), "renamed")):
            with self.subTest(flags=flags, stem=stem):
                d = read_json(self.export(*flags, stem=stem, out="o") / "delta.json")
                self.assertEqual(d["renamed"]["to"], flags[1] if flags else stem)
                self.assertEqual(d["added"] + d["removed"] + d["rebuild"] + d["recheck"], [])

    def test_a_first_export_writes_every_system_added(self):
        out = self.export()
        d = read_json(out / "delta.json")
        self.assertIsNone(d["from"])
        self.assertEqual(sorted(d["added"]), ["Api", "shop"])
        for s in ("removed", "rebuild", "recheck", "unchanged"):
            self.assertEqual(d[s], [])


class Dialect(Tmp):
    def test_name_and_version(self):
        manifest = read_json(self.export() / "manifest.json")
        self.assertEqual(manifest["dialect"], {"name": "export-probe", "version": "1.2"})
        self.assertEqual(list(manifest)[:5], ["sigil_export", "spec", "spec_hash", "top", "dialect"])

    def test_no_version_and_no_dialect(self):
        model = em.build_model("#!spec\n[A] -> [B] : {X}\n", "s")
        bare = types.ModuleType("bare")
        bare.NAME = "bare"
        self.assertEqual(exporter.plan_export(model, "s.sigil", "", bare).manifest["dialect"],
                         {"name": "bare"})
        self.assertNotIn("dialect", exporter.plan_export(model, "s.sigil", "").manifest)

    def test_the_dialect_loads_by_path(self):
        self.assertEqual(dialects.load(str(PROBE)).VERSION, "1.2")


class Lines(Tmp):
    def test_per_component_and_flow(self):
        forms = self.systems(self.export())
        comps = self.components(self.export(out="again"))
        self.assertEqual(comps["(Shopper)"]["lines"], [7])
        self.assertEqual(comps["[[Ledger]]"]["lines"], [8])
        self.assertEqual(comps["[Front]"]["lines"], [12])
        flows = {(f["from"], f["to"]): f["lines"] for s in forms.values()
                 for f in s.get("flows", []) + s.get("interface", [])}
        self.assertEqual(flows[("(Shopper)", "[Api]")], [7])
        self.assertEqual(flows[("[Api]", "[[Ledger]]")], [8])
        self.assertEqual(flows[("[Front]", "[Back]")], [12])
        for f in comps["[Api]"]["interface"]:
            self.assertTrue(f["lines"])


class Attrs(Tmp):
    def test_a_dialect_glyph_keeps_its_brackets(self):
        model = em.build_model(SPEC, "shop", dialects.load(str(PROBE)))
        self.assertEqual(model.components["Ledger_ref"].glyph, "[[Ledger]]")

    def test_a_dialect_glyphs_attrs(self):
        comps = self.components(self.export())
        self.assertEqual(comps["[[Ledger]]"]["kind"], "ref")
        self.assertEqual(comps["[[Ledger]]"]["attrs"], {"pinned": True, "tags": ["a", "b"]})
        self.assertNotIn("attrs", comps["[Api]"])

    def test_attrs_are_in_the_body_hash(self):
        model = em.build_model(SPEC, "shop", dialects.load(str(PROBE)))
        c = model.components["Ledger_ref"]
        other = em.component_hashed(
            dataclasses.replace(c, attrs={"pinned": False}), model.components, model.top)
        self.assertEqual(other.interface_hash, c.interface_hash)
        self.assertNotEqual(other.body_hash, c.body_hash)

    def test_an_attr_named_like_an_export_key_moves_the_body_hash(self):
        # `lines` (and `home`) are the dialect's own data inside attrs
        model = em.build_model(SPEC, "shop", dialects.load(str(PROBE)))
        c = model.components["Ledger_ref"]
        one, two = (em.component_hashed(dataclasses.replace(c, attrs=a),
                                        model.components, model.top)
                    for a in ({"lines": [1, 2]}, {"lines": [9]}))
        self.assertNotEqual(one.body_hash, two.body_hash)
        here, there = (em.component_hashed(dataclasses.replace(c, attrs={"home": h}),
                                           model.components, model.top)
                       for h in (model.top, "Elsewhere"))
        self.assertNotEqual(here.body_hash, there.body_hash)

    def test_plain(self):
        self.assertEqual(em.plain({2: {"b", "a"}, "x": (1, None), "o": object}),
                         {"2": ["a", "b"], "o": str(object), "x": [1, None]})


if __name__ == "__main__":
    unittest.main()
