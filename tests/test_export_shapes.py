"""Interfaces cover data shapes (design/refine-1.md round 7, proposal 3).

A component's interface hash covers its flows plus the shapes of the data they
carry (nested shapes too); a system's covers its boundary flows plus the shapes
of the data crossing its boundary and the data its face's tree holds (`\\-&` data
children, by name even with no shape written). Fields count by name, sorted, so
their order moves no hash; comments stay body only. system.json lists the shapes.
A field added to {X} rechecks every system that sends, takes or holds {X}
(through the interface-changed path of the delta). Also lint SGL193: a data
shape's line that is neither fields nor a flow."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_DIR))

from sigil import cli  # noqa: E402
from sigil.analyse.lint import lint  # noqa: E402
from sigil.publish import systems as em  # noqa: E402

EMPTY = em.digest([])           # 4f53cda18c2baa0c: an interface with nothing in it

EDITOR = """\
#!spec
# an editor and the document it shows

(User) -> [Ui] : open({Path}) => {View}
[Ui] -> [Core] : read({Path}) => {Doc}
[Ui] -> [Log] : note({Path}) => {Ack}
[Ui] -> [Shell] : frame({Path}) => {Ack}
[Log] -> [Core] : ping({Path}) => {Ack}
[Shell] -> [Panel] : show({Path}) => {Ack}
{Doc} := { path, text }

[Core] := {
  [Store] -> |Db| : get({Path}) => {Doc}
}

[Log] := {
  [Writer] -> |Journal| : add({Path}) => {Ack}
}

[Panel]
    \\-& {Doc}
    \\-& {Mark}
    \\-> [Tab]

[Shell] := {
  [Frame] -> |Layout| : place({Path}) => {Ack}
}
"""
NOTE = EDITOR.replace("{ path, text }", "{ path, text, note? }")


def model(text: str, stem: str = "editor"):
    return em.build_model(text, stem)


def iface(text: str) -> dict:
    """{system key: interface hash} and {component id: interface hash}."""
    m = model(text)
    return ({k: s.interface_hash for k, s in m.systems.items()},
            {k: c.interface_hash for k, c in m.components.items()})


def shapes(text: str, key: str) -> list:
    m = model(text)
    return em.system_json(m.systems[key], m.components).get("shapes", [])


class InterfaceCoversShapes(unittest.TestCase):

    def test_a_field_added_moves_the_interfaces_that_carry_or_hold_it(self):
        (sys_a, comp_a), (sys_b, comp_b) = iface(EDITOR), iface(NOTE)
        moved = {k for k in sys_a if sys_a[k] != sys_b[k]}
        # Core: [Ui] -> [Core] carries {Doc} over its boundary; Panel holds {Doc}
        self.assertEqual(moved, {"Core", "Panel"})
        parts = {k for k in comp_a if comp_a[k] != comp_b[k]}
        self.assertEqual(parts, {"Ui_service", "Core_service", "Store_service", "Db_store",
                                 "Doc_data", "Panel_service"})

    def test_field_order_moves_no_hash(self):
        swapped = EDITOR.replace("{ path, text }", "{ text, path }")
        a, b = model(EDITOR), model(swapped)
        for k in a.systems:
            self.assertEqual((a.systems[k].interface_hash, a.systems[k].body_hash),
                             (b.systems[k].interface_hash, b.systems[k].body_hash), k)
        for k in a.components:
            self.assertEqual((a.components[k].interface_hash, a.components[k].body_hash),
                             (b.components[k].interface_hash, b.components[k].body_hash), k)

    def test_a_field_written_on_its_own_line_reads_the_same(self):
        lines = EDITOR.replace("{Doc} := { path, text }", "{Doc} := {\n  text\n  path\n}")
        self.assertEqual(iface(EDITOR), iface(lines))

    def test_optional_counts(self):
        optional = EDITOR.replace("{ path, text }", "{ path, text? }")
        self.assertNotEqual(iface(EDITOR)[0]["Core"], iface(optional)[0]["Core"])

    def test_a_comment_is_body_only(self):
        noted = EDITOR.replace("{Doc} := { path, text }",
                               "{Doc} := { path, text }   # the text as saved")
        a, b = model(EDITOR), model(noted)
        self.assertEqual(iface(EDITOR), iface(noted))
        self.assertNotEqual(a.components["Doc_data"].body_hash,
                            b.components["Doc_data"].body_hash)

    def test_a_tree_described_system_has_an_interface(self):
        # held data counts by name with no shape written: {Mark} has none
        bare = EDITOR.replace("[Shell] -> [Panel] : show({Path}) => {Ack}\n", "") \
                     .replace("[Ui] -> [Shell] : frame({Path}) => {Ack}\n", "")
        self.assertNotEqual(model(bare).systems["Panel"].interface_hash, EMPTY)
        self.assertEqual(shapes(EDITOR, "Panel"), [
            {"glyph": "{Doc}", "fields": [{"name": "path"}, {"name": "text"}], "held": True},
            {"glyph": "{Mark}", "held": True}])
        unshaped = bare.replace("{Doc} := { path, text }\n", "")
        self.assertEqual(shapes(unshaped, "Panel"),
                         [{"glyph": "{Doc}", "held": True}, {"glyph": "{Mark}", "held": True}])
        self.assertNotEqual(model(unshaped).systems["Panel"].interface_hash, EMPTY)

    def test_held_data_counts_at_any_depth_of_the_face_tree(self):
        deep = EDITOR.replace("    \\-> [Tab]\n", "    \\-> [Tab]\n        \\-& {Cursor}\n")
        self.assertIn({"glyph": "{Cursor}", "held": True}, shapes(deep, "Panel"))
        tab = em.component_json(model(deep).components["Tab_service"], model(deep).components)
        self.assertEqual(tab["shapes"], [{"glyph": "{Cursor}", "held": True}])

    def test_carried_data_with_no_shape_changes_nothing(self):
        # no shape and no tree data: every interface hash is its flows' alone
        plain = EDITOR.replace("{Doc} := { path, text }\n", "").split("[Panel]")[0]
        m = model(plain)
        for k, s in m.systems.items():
            flows = em.hash_form(em.system_json(s, m.components), m.top).get("interface", [])
            self.assertEqual(s.interface_hash, em.digest(flows), k)
            self.assertNotIn("shapes", em.system_json(s, m.components))

    def test_nested_shapes_count_and_a_cycle_ends(self):
        nested = EDITOR.replace("{Doc} := { path, text }",
                                "{Doc} := { path, rows: {Row}? }\n{Row} := { cells, {Doc}? }")
        got = shapes(nested, "Core")
        self.assertEqual(got, [
            {"glyph": "{Doc}", "fields": [{"name": "path"},
                                          {"name": "rows", "optional": True, "shape": "{Row}"}]},
            {"glyph": "{Row}", "fields": [{"name": "Doc", "optional": True, "shape": "{Doc}"},
                                          {"name": "cells"}]}])
        deeper = nested.replace("{ cells, {Doc}? }", "{ cells, width, {Doc}? }")
        self.assertNotEqual(iface(nested)[0]["Core"], iface(deeper)[0]["Core"])
        self.assertNotEqual(iface(nested)[1]["Store_service"], iface(deeper)[1]["Store_service"])

    def test_a_nested_glyph_alone_reads_the_same_inline_or_on_its_own_line(self):
        # a field is no node in either form (K1): the same components, homes and hashes
        inline = EDITOR.replace("{ path, text }", "{ path, text, {Meta} }")
        lines = EDITOR.replace("{ path, text }", "{\n  path\n  text\n  {Meta}\n}")
        a, b = model(inline), model(lines)
        self.assertNotIn("Meta_data", a.components)
        self.assertEqual(sorted(a.systems), sorted(b.systems))
        for k in a.systems:
            self.assertEqual((a.systems[k].interface_hash, a.systems[k].body_hash),
                             (b.systems[k].interface_hash, b.systems[k].body_hash), k)
        self.assertEqual({k: (c.home, c.interface_hash, c.body_hash)
                          for k, c in a.components.items()},
                         {k: (c.home, c.interface_hash, c.body_hash)
                          for k, c in b.components.items()})
        self.assertIn({"glyph": "{Doc}", "fields": [{"name": "Meta", "shape": "{Meta}"},
                                                    {"name": "path"}, {"name": "text"}]},
                      shapes(inline, "Core"))

    def test_a_field_s_glyph_is_named_as_written(self):
        odd = EDITOR.replace("{ path, text }", "{ path, rows: {Méta}, {Page<T>} }")
        got = shapes(odd, "Core")[0]["fields"]
        self.assertEqual([f.get("shape") for f in got], ["{Page<T>}", None, "{Méta}"])

    def test_an_empty_shape_differs_from_none(self):
        empty = EDITOR.replace("{ path, text }", "{ }")
        self.assertIn({"glyph": "{Doc}", "fields": [], "held": True}, shapes(empty, "Panel"))
        none = EDITOR.replace("{Doc} := { path, text }\n", "")
        self.assertNotEqual(iface(empty)[0]["Panel"], iface(none)[0]["Panel"])

    def test_a_shape_is_written_whole_in_system_json(self):
        self.assertEqual(shapes(EDITOR, "Core"),
                         [{"glyph": "{Doc}", "fields": [{"name": "path"}, {"name": "text"}]}])
        self.assertEqual(shapes(EDITOR, "Log"), [])


def run(argv) -> tuple:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(["export", *argv])
    return code, out.getvalue(), err.getvalue()


class FieldAddedDelta(unittest.TestCase):
    """Export, add a field, re-export: delta.json names every system that sends,
    takes or holds {Doc} (rebuild: its own interface, so its body, moved) and those
    depending on one of them (recheck, through the interface-changed path)."""

    def test_re_export_rechecks_the_systems_reaching_the_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec, out = Path(tmp) / "editor.sigil", Path(tmp) / "out"
            spec.write_text(EDITOR, encoding="utf-8")
            self.assertEqual(run([str(spec), "--out", str(out)])[0], 0)
            before = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            spec.write_text(NOTE, encoding="utf-8")
            self.assertEqual(run([str(spec), "--out", str(out)])[0], 0)
            d = json.loads((out / "delta.json").read_text(encoding="utf-8"))
            after = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            panel = json.loads((out / "panel" / "system.json").read_text(encoding="utf-8"))
        self.assertEqual(d["rebuild"], ["editor", "Core", "Panel"])
        self.assertEqual(d["recheck"], ["Log", "Shell"])
        self.assertEqual(d["systems"]["Log"]["because"], ["Core"])
        self.assertEqual(d["systems"]["Shell"]["because"], ["Panel"])
        self.assertEqual(d["unchanged"], [])
        for key in ("Core", "Panel"):
            self.assertNotEqual(before["systems"][key]["interface"],
                                after["systems"][key]["interface"], key)
        for key in ("Log", "Shell"):
            self.assertEqual(before["systems"][key]["interface"],
                             after["systems"][key]["interface"], key)
        self.assertIn({"name": "note", "optional": True}, panel["shapes"][0]["fields"])


class LintStrayShapeLine(unittest.TestCase):
    """SGL193: a data shape's line that is neither fields nor a flow is dropped."""

    @staticmethod
    def rules(text: str) -> list:
        return [(d.line, d.rule, d.severity) for d in lint(text).diagnostics
                if d.rule == "SGL193"]

    def test_stray_lines_warn(self):
        text = "#!spec\n{Doc} := {\n  a b\n  x: y\n  1abc\n  {Meta} extra\n  path\n}\n"
        self.assertEqual(self.rules(text), [(3, "SGL193", "warn"), (4, "SGL193", "warn"),
                                            (5, "SGL193", "warn"), (6, "SGL193", "warn")])

    def test_fields_flows_and_declarations_stay_quiet(self):
        text = ("#!spec\n{Doc} := {\n  path, note?\n  rows: {Row}, {Meta}?\n"
                "  [Part]\n  {Doc} -> |Log| : add({Doc})\n}\n")
        self.assertEqual(self.rules(text), [])

    def test_only_a_data_shape(self):
        # a service's expansion reads bare names through SGL191, not SGL193
        text = "#!spec\n[Api] := {\n  a b\n  [Api] -> |Db| : save({Doc})\n}\n"
        self.assertEqual(self.rules(text), [])


if __name__ == "__main__":
    unittest.main()
