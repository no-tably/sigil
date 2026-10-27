"""Data shapes (design/refine-1.md, round 7, proposals 2 and 4): a data
expansion's bare names are its fields — `{Doc} := { path, text, note? }`, `?`
optional, a data glyph `{Rows}` or `rows: {Rows}` a nested shape, comma- or
newline-separated, in written order. The parsed document carries them as
Graph.shapes (data id → (Field, …)). A data expansion is the data's shape, no
export system: it gets no folder, {Doc} stays a component homed as before, and a
nested glyph its shape names lives in the system the shape is written in. Lint:
a bare name outside a data expansion is a warn (SGL191; the parser drops it), a
field written twice in one shape an error (SGL192)."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigil.analyse.lint import lint  # noqa: E402
from sigil.core import parse as render  # noqa: E402
from sigil.core.graph import Field  # noqa: E402
from sigil.core.statements import read_document, read_fields  # noqa: E402
from sigil.model import systems  # noqa: E402
from sigil.model import structure  # noqa: E402


def shapes(text: str) -> dict:
    return render.parse_document(text).shapes


def rules(text: str) -> list:
    return [(d.line, d.rule) for d in lint(text).diagnostics if d.rule in ("SGL191", "SGL192")]


def fields_of(line: str):
    st = read_document("#!sketch\n" + line + "\n").statements[0]
    return read_fields(st)


DOC = "#!spec\n(User) -> [Api] : get() => {Doc}\n[Api] -> |Docs| : read() => {Doc}\n"


class Reading(unittest.TestCase):
    def test_bare_names_are_the_fields_in_written_order(self):
        got = shapes("#!sketch\n{Doc} := { path, text, note? }\n")
        self.assertEqual(got, {"Doc_data": (Field("path"), Field("text"),
                                            Field("note", optional=True))})

    def test_newline_and_comma_separated_fields_read_alike(self):
        one = shapes("#!sketch\n{Doc} := { path, text, note? }\n")
        many = shapes("#!sketch\n{Doc} := {\n  path\n  text, note?\n}\n")
        self.assertEqual(one, many)

    def test_nested_shapes_named_and_alone(self):
        got = shapes("#!sketch\n{Batch} := {\n  id\n  rows: {Row}?\n  {Meta}\n"
                     "  {Page<T>}?\n}\n")["Batch_data"]
        self.assertEqual([(f.name, f.optional, f.shape) for f in got], [
            ("id", False, None), ("rows", True, "Row_data"), ("Meta", False, "Meta_data"),
            ("Page<T>", True, render.parse_glyph("{Page<T>}").id)])

    def test_optional_mark_before_the_colon(self):
        self.assertEqual(fields_of("rows?: {Row}"), (("rows", True, "{Row}"),))

    def test_a_field_is_a_frozen_record(self):
        f = Field("path")
        with self.assertRaises(Exception):
            f.name = "other"            # frozen
        self.assertEqual((f.name, f.optional, f.shape), ("path", False, None))

    def test_lines_that_are_no_fields(self):
        for line in ("[A] -> [B]", "a b", "x: y", "rows: [Row]", "_", "{a, b}",
                     "~{Row}", "[A] @inv x", "kind: \"x\"", "id ×3"):
            with self.subTest(line=line):
                self.assertIsNone(fields_of(line))

    def test_a_flow_in_a_data_expansion_adds_no_field_and_is_still_drawn(self):
        g = render.parse_document("#!sketch\n{Doc} := {\n  path\n  [A] -> [B]\n}\n")
        self.assertEqual(g.shapes["Doc_data"], (Field("path"),))
        self.assertEqual([(e.src, e.dst) for e in g.expansions["Doc_data"].edges],
                         [("A_service", "B_service")])

    def test_fields_inside_a_control_block_are_no_fields(self):
        g = render.parse_document("#!sketch\n{Doc} := {\n  path\n  loop @each x {\n"
                                  "    inner\n  }\n}\n")
        self.assertEqual(g.shapes["Doc_data"], (Field("path"),))

    def test_only_a_data_expansion_has_a_shape(self):
        self.assertEqual(shapes("#!sketch\n[Api] := { token, user }\n"), {})
        self.assertEqual(shapes("#!sketch\nwalk := { a, b }\n"), {})

    def test_an_empty_shape_and_a_shape_with_only_flows(self):
        self.assertEqual(shapes("#!sketch\n{Doc} := {\n  [A] -> [B]\n}\n"), {"Doc_data": ()})

    def test_nested_levels_are_listed_on_the_document(self):
        g = render.parse_document("#!sketch\n[Core] := {\n  [A] -> [B] : f({Doc})\n"
                                  "  {Doc} := { path }\n}\n")
        self.assertEqual(g.shapes, {"Doc_data": (Field("path"),)})
        self.assertEqual(g.expansions["Core_service"].shapes, {"Doc_data": (Field("path"),)})

    def test_the_bare_names_make_no_nodes(self):
        g = render.parse_document("#!sketch\n{Doc} := { path, text, {Meta} }\n")
        self.assertEqual(set(g.expansions["Doc_data"].nodes), {"Meta_data"})


class Export(unittest.TestCase):
    def model(self, text: str, stem: str = "d"):
        return systems.model_of(render.parse_document(text), stem)

    def test_a_data_expansion_is_no_system(self):
        m = self.model(DOC + "{Doc} := { path, text, note?, {Meta} }\n")
        self.assertEqual(list(m.systems), ["d"])
        self.assertIn("Doc_data", m.components)
        self.assertEqual(m.components["Doc_data"].home, "d")
        # the nested glyph lives where the shape is written
        self.assertEqual(m.components["Meta_data"].home, "d")
        self.assertEqual(m.shared, ())

    def test_a_service_expansion_still_is_a_system(self):
        m = self.model(DOC + "[Api] := {\n  [Parse] -> [Load]\n}\n")
        self.assertEqual(sorted(m.systems), ["Api", "d"])

    def test_the_data_keeps_its_home_inside_a_unit(self):
        # {Doc} written only in Core's flows, its shape at the top: homed in Core,
        # as when its expansion was a system nested under its home.
        text = ("#!spec\n(User) -> [Core] : go() => {Ok}\n[Core] := {\n"
                "  [A] -> [B] : put({Doc}) => {Ok}\n  {Doc}\n}\n{Doc} := { path }\n")
        m = self.model(text)
        self.assertEqual(sorted(m.systems), ["Core", "d"])
        self.assertEqual(m.components["Doc_data"].home, "Core")

    def test_a_nested_glyph_written_elsewhere_keeps_that_home(self):
        text = ("#!spec\n(User) -> [Core] : go() => {Ok}\n[Core] := {\n"
                "  [A] -> [B] : put({Meta}) => {Ok}\n  {Meta}\n}\n{Doc} := { path, {Meta} }\n")
        m = self.model(text)
        self.assertEqual(m.components["Meta_data"].home, "Core")

    def test_structure_lists_no_unit_for_a_shape(self):
        g = render.parse_document(DOC + "{Doc} := { path, {Meta} }\n")
        units = structure.structure_of(g, "d").units
        self.assertEqual([u.key for u in units], ["d"])
        self.assertIn("{Meta}", units[0].members)


class Lint(unittest.TestCase):
    def test_a_bare_name_outside_a_data_expansion_is_a_warn(self):
        text = "#!spec\npath\n[Api] := {\n  token\n  rows: {Row}\n  [A] -> [B]\n}\n"
        self.assertEqual(rules(text), [(2, "SGL191"), (4, "SGL191"), (5, "SGL191")])
        d = next(d for d in lint(text).diagnostics if d.rule == "SGL191")
        self.assertEqual(d.severity, "warn")
        self.assertIn("`path`", d.message)

    def test_fields_in_a_data_expansion_lint_clean(self):
        text = ("#!spec\n[A] -> [B] : f({Doc}, {Batch})\n{Doc} := { path, text, note? }\n"
                "{Batch} := {\n  id\n  rows: {Row}, {Meta}?\n}\n")
        self.assertEqual(rules(text), [])
        self.assertEqual(lint(text).diagnostics, [])

    def test_a_glyph_alone_outside_a_shape_is_a_declaration(self):
        self.assertEqual(rules("#!spec\n{Meta}\n[A] -> [B] : f({Meta})\n"), [])

    def test_a_field_written_twice_is_an_error(self):
        text = "#!spec\n{Doc} := { path, path? }\n{Row} := {\n  {Meta}\n  {Meta}\n}\n"
        self.assertEqual(rules(text), [(2, "SGL192"), (5, "SGL192")])
        self.assertTrue(all(d.severity == "error" for d in lint(text).diagnostics
                            if d.rule == "SGL192"))

    def test_the_same_name_in_two_shapes_is_fine(self):
        self.assertEqual(rules("#!spec\n{Doc} := { path }\n{Row} := { path }\n"), [])

    def test_quiet_and_alias_lines_are_not_judged(self):
        self.assertEqual(rules("#!sketch\nretry := @after(1s)\n[Cache] := {Summary} store\n"),
                         [])


if __name__ == "__main__":
    unittest.main()
