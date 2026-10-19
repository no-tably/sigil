"""The structure reading (sigil.model.structure; `sigil view FILE --structure`):
units with their members and dependencies, cycles and flows into an enclosing
unit, the edge, reach per component, pass-throughs, large units, a name declared
in two units, writers per store — and the command line (text, --json, exit 0)."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sigil.core.parse import parse_document  # noqa: E402
from sigil.model import scene, structure, systems  # noqa: E402
from sigil.present import app  # noqa: E402

SHOP = ROOT / "site" / "examples" / "02-shop.sigil"
DOCS = sorted((ROOT / "site" / "examples").glob("*.sigil")) + [
    ROOT / "tests" / "fixtures" / "executions.sigil",
    ROOT / "tests" / "fixtures" / "coverage.sigil"]


def read(text: str, stem: str = "t", **kw):
    return structure.structure_of(parse_document(text), stem, **kw)


def unit(s, key):
    return next(u for u in s.units if u.key == key)


def reach_of(s, glyph):
    return next(r for r in s.reach if r.component == glyph)


class TestUnits(unittest.TestCase):
    TEXT = ("#!sketch\n"
            "(U) -> [Api] : go({X}) => {Y}\n"
            "[Api] := {\n"
            "  [A] -> [B] : get({X}) => {Y}\n"
            "  [B] -> |Db| : save({X}) => {Ok}\n"
            "}\n")

    def test_units_follow_the_export_model(self):
        s = read(self.TEXT)
        m = systems.model_of(parse_document(self.TEXT), "t")
        self.assertEqual([u.key for u in s.units], list(m.systems))
        for u in s.units:
            sysm = m.systems[u.key]
            self.assertEqual((u.kind, u.parent), (sysm.kind, sysm.parent))
            self.assertEqual(sorted(set(u.calls) | set(u.nests)), list(sysm.depends_on))
        api = unit(s, "Api")
        self.assertEqual(api.members, ("[A]", "[B]", "|Db|"))
        self.assertEqual([f.text for f in api.internal], ["[A] -> [B]", "[B] -> |Db|"])
        self.assertEqual(unit(s, "t").nests, ("Api",))
        self.assertEqual(unit(s, "t").calls, ())          # (U) is an actor: no dependency

    def test_every_example_reads_and_is_deterministic(self):
        for path in DOCS:
            with self.subTest(path.name):
                text = path.read_text()
                a = structure.as_json(read(text, path.stem))
                b = structure.as_json(read(text, path.stem))
                self.assertEqual(a, b)
                self.assertEqual(json.loads(json.dumps(a)), a)

    def test_a_mode_line_changes_nothing(self):
        body = self.TEXT.split("\n", 1)[1]
        readings = {structure.as_json(read(f"#!{mode}\n" + body))["summary"]
                    for mode in ("sketch", "craft", "spec")}
        self.assertEqual(len(readings), 1)


class TestCycles(unittest.TestCase):
    def test_a_round_through_an_enclosing_level_is_no_cycle(self):
        s = read("[Hub]\n[Hub] -> [R] : go({X}) => {Y}\n"
                 "[A] := {\n  [P] -> [Hub] : go({X}) => {Y}\n}\n"
                 "[B] := {\n  [R] -> [P] : go({X}) => {Y}\n}\n")
        # [Hub] is declared at the top only, so it is homed there: A leans on the
        # top (up), the top reaches into B (its own nesting), B on A — no sibling cycle
        self.assertEqual(s.cycles, ())
        self.assertEqual([(k.src, k.dst) for k in s.up], [("A", "t")])

    def test_a_nested_units_flow_is_its_enclosing_siblings(self):
        text = ("[Root]\n  \\-> [A]\n  \\-> [B]\n"
                "[A] := {\n  [N] -> [M] : go({X}) => {Y}\n"
                "  [N] := {\n    [P] -> [B] : go({X}) => {Y}\n  }\n}\n"
                "[B] := {\n  [Q] -> [A] : go({X}) => {Y}\n}\n")
        s = read(text)
        (c,) = s.cycles
        self.assertEqual(c.units, ("A", "B"))
        self.assertEqual({(k.src, k.dst, tuple(f.text for f in k.flows)) for k in c.links},
                         {("A", "B", ("[P] -> [B]",)), ("B", "A", ("[Q] -> [A]",))})
        self.assertEqual(structure.sibling_cycles(
            structure.units_of(parse_document(text), "t")), s.cycles)

    def test_sibling_cycle_with_its_flows(self):
        text = ("[Root]\n  \\-> [A]\n  \\-> [B]\n"
                "[A] := {\n  [P] -> [B] : go({X}) => {Y}\n}\n"
                "[B] := {\n  [Q] -> [A] : go({X}) => {Y}\n}\n")
        s = read(text)
        (c,) = s.cycles
        self.assertEqual(set(c.units), {"A", "B"})
        self.assertEqual({(k.src, k.dst, tuple(f.text for f in k.flows)) for k in c.links},
                         {("A", "B", ("[P] -> [B]",)), ("B", "A", ("[Q] -> [A]",))})
        self.assertEqual(s.up, ())

    def test_no_cycle_in_a_layered_design(self):
        text = ("[Root]\n  \\-> [A]\n  \\-> [B]\n"
                "[A] := {\n  [P] -> [B] : go({X}) => {Y}\n}\n"
                "[B] := {\n  [Q] -> |S| : put({X}) => {Ok}\n}\n")
        self.assertEqual(read(text).cycles, ())

    def test_a_flow_into_an_enclosing_unit_is_up(self):
        s = read("|Log|\n[Api] := {\n  [A] -> |Log| : put({X}) => {Ok}\n}\n"
                 "[Edge] -> |Log| : put({X}) => {Ok}\n[Edge] -> [Api] : go({X}) => {Y}\n")
        (k,) = s.up
        self.assertEqual((k.src, k.dst), ("Api", "t"))
        self.assertEqual([f.text for f in k.flows], ["[A] -> |Log|"])
        self.assertEqual(s.cycles, ())     # top → Api by [Edge] -> [Api]: no sibling cycle

    def test_strongly_connected(self):
        order = ["a", "b", "c", "d"]
        deps = {"a": {"b"}, "b": {"c"}, "c": {"a"}, "d": {"a"}}
        self.assertEqual(structure.strongly_connected(order, deps), [["a", "b", "c"], ["d"]])


class TestEdgeAndReach(unittest.TestCase):
    TEXT = ("#!sketch\n"
            "(U) -> [A] : go({X}) => {Y}\n"
            "[A] -> [B] : go({X}) => {Y}\n"
            "[B] ~> <E>\n"
            "<E> -> [C]\n"
            "[C] -> (Os) : call({X}) => {Y}\n"
            "(Os) -> [D] : back({X})\n"
            "[A] !> [F]\n"
            "[B] => {R}\n"
            "[B] -> {V}\n")

    def test_edge_parts_call_an_actor(self):
        s = read(self.TEXT)
        self.assertEqual([(e.component, e.actors) for e in s.edge], [("[C]", ("(Os)",))])

    def test_reach_is_transitive_over_calls(self):
        s = read(self.TEXT)
        a = reach_of(s, "[A]")
        self.assertEqual(a.out, ("<E>", "[B]", "[C]"))   # no !> [F], no {R}/{V} data
        self.assertEqual(a.out_actors, ("(Os)",))
        self.assertEqual(a.in_actors, ("(U)",))
        c = reach_of(s, "[C]")
        self.assertEqual(c.into, ("<E>", "[A]", "[B]"))
        d = reach_of(s, "[D]")
        self.assertEqual(d.into, ())                     # an actor is never walked through
        self.assertEqual(d.in_actors, ("(Os)",))
        f = reach_of(s, "[F]")
        self.assertEqual((f.out, f.into), ((), ()))
        self.assertNotIn("(U)", [r.component for r in s.reach])
        self.assertEqual(s.reach[0].component, "[A]")     # largest first

    def test_a_call_into_an_owner_drives_its_entries(self):
        s = read("[Api] -> [Shop] : buy({X}) => {Y}\n"
                 "[Shop] := {\n  [Cart] -> [Pay] : pay({X}) => {Y}\n}\n")
        self.assertEqual(reach_of(s, "[Api]").out, ("[Cart]", "[Pay]", "[Shop]"))
        self.assertEqual(reach_of(s, "[Pay]").into, ("[Api]", "[Cart]", "[Shop]"))

    def test_bidirectional_reaches_both_ways(self):
        s = read("[A] <-> [B] : sync({X}) => {Y}\n")
        self.assertEqual(reach_of(s, "[A]").out, ("[B]",))
        self.assertEqual(reach_of(s, "[B]").out, ("[A]",))


class TestShape(unittest.TestCase):
    def test_pass_through(self):
        s = read("[A] -> [B] : go({X}) => {Y}\n[B] -> [C] : go({X}) => {Y}\n"
                 "[C] -> [D] : go({X}) => {Y}\n[E] -> [C] : go({X}) => {Y}\n"
                 "(U) -> [P] : go({X}) => {Y}\n[P] -> [Q] : go({X}) => {Y}\n"
                 "[Q] -> [R] : go({X}) => {Y}\n")
        self.assertEqual([(p.component, p.caller, p.callee) for p in s.pass_throughs],
                         [("[B]", "[A]", "[C]"), ("[Q]", "[P]", "[R]")])

    def test_a_face_is_no_pass_through(self):
        s = read("[A] -> [B] : go({X}) => {Y}\n[B] -> [C] : go({X}) => {Y}\n"
                 "[B] := {\n  [P] -> [Q] : go({X}) => {Y}\n}\n")
        self.assertNotIn("[B]", [p.component for p in s.pass_throughs])

    def test_units_over_nine_members(self):
        body = "".join(f"  [M{i}]\n" for i in range(10))
        s = read(f"[Big] := {{\n{body}}}\n[Small] := {{\n  [P]\n}}\n")
        self.assertEqual([(u.key, len(u.members)) for u in s.large], [("Big", 10)])

    def test_actors_are_no_members(self):
        body = "".join(f"  [M{i}]\n" for i in range(8)) + "  (U) -> [M0] : go({X}) => {Y}\n" \
            + "  [M1] -> (Os) : call({X}) => {Y}\n  {D} -> [M2]\n"
        s = read(f"[Big] := {{\n{body}}}\n")
        big = unit(s, "Big")
        self.assertEqual(big.actors, ("(U)", "(Os)"))
        self.assertEqual(len(big.members), 9)            # 8 parts and {D}: not over 9
        self.assertEqual(s.large, ())
        self.assertEqual(structure.large_units(structure.units_of(
            parse_document(f"[Big] := {{\n{body}  |S|\n}}\n"), "t"))[0].key, "Big")

    def test_header_lines(self):
        s = read("[Root]\n  \\-> [A]\n[A] -> [B] : go({X}) => {Y}\n\n"
                 "[A] := {\n  [P] -> [Q] : go({X}) => {Y}\n}\n")
        self.assertEqual({u.key: u.line for u in s.units}, {"t": None, "Root": 1, "A": 5})

    def test_a_name_declared_in_two_units(self):
        s = read("[A] := {\n  [X]\n  [P] -> [Q] : go({X}) => {Y}\n}\n"
                 "[B] := {\n  [X] @sla(p99 < 5ms)\n}\n")
        self.assertEqual([(r.component, r.units) for r in s.repeated], [("[X]", ("A", "B"))])

    def test_a_header_or_continued_tree_is_no_second_unit(self):
        text = ("[Core] := {\n  [Text]\n  [B] -> [Text] : get({X}) => {Y}\n}\n"
                "[Text] := {\n  [W] -> [V] : go({X}) => {Y}\n}\n"
                "[Ui] := {\n  [Panes]\n    \\-> [Tab]\n  [Tab]\n    \\-> [Pane]\n}\n")
        self.assertEqual(read(text).repeated, ())

    def test_a_name_named_in_two_units_follows_no_home(self):
        # one rule with SGC401 no-home (sigil check --export): a part a second
        # unit only names in a flow has no one home either
        text = ("#!spec\n[A] := {\n  [P] -> [Q] : go({X}) => {Y}\n}\n"
                "[B] := {\n  [R] -> [P] : go({X}) => {Y}\n}\n")
        self.assertEqual([(r.component, r.units) for r in read(text).repeated],
                         [("[P]", ("A", "B"))])
        from sigil.analyse import check
        rep = check.check(text, export=True)
        (f,) = [f for f in rep.findings if f.rule.id == "SGC401"]
        self.assertTrue(f.message.startswith("`[P]` is written in `A` and `B`"), f.message)

    def test_writers_as_check_counts_them(self):
        text = ("[A] -> |S| : save({X})\n"                  # `=> …` back: a read, as check reads it
                "[B] -> |S| : get({X}) => {Row}\n"
                "[C] ~> |S| : append({X})\n"
                "|T| @write(D)\n[D] -> [A] : go({X}) => {Y}\n")
        s = read(text)
        found = {w.store: w.writers for w in s.writers}
        self.assertEqual(found["|S|"], (("[A]", ("flow",)), ("[C]", ("flow",))))
        self.assertEqual(found["|T|"], (("[D]", ("decl",)),))
        self.assertEqual(s.writers[0].store, "|S|")       # most writers first
        dialect = read(text, read_verbs=scene.READ_VERBS + ("append",))
        self.assertEqual({w.store: w.writers for w in dialect.writers}["|S|"],
                         (("[A]", ("flow",)),))


class TestText(unittest.TestCase):
    def test_sections_and_summary(self):
        s = read(TestEdgeAndReach.TEXT)
        lines = app.structure_text(s)
        for title in ("units", "cycles", "up", "edge", "reach", "pass-throughs",
                      "units over 9 members", "a name declared in two units",
                      "writers per store"):
            self.assertTrue(any(ln.startswith(title) for ln in lines), title)
        self.assertEqual(lines[-1], structure.summary(s))
        self.assertIn("  [C] in t → (Os)", lines)
        self.assertIn("  (none)", lines)

    def test_summary_counts(self):
        self.assertEqual(
            structure.summary(read(TestEdgeAndReach.TEXT)),
            "1 unit: 0 cycles, 0 up, 1 edge part, 0 pass-throughs, 0 over 9 members, "
            "0 names in two units, 0 stores with two or more writers")


class TestCommand(unittest.TestCase):
    def run_view(self, *args, stdin=None):
        return subprocess.run([sys.executable, str(ROOT / "bin" / "sigil"), "view", *args],
                              capture_output=True, text=True, input=stdin)

    def test_text(self):
        res = self.run_view(str(SHOP), "--structure")
        self.assertEqual(res.returncode, 0, res.stderr)
        expected = "\n".join(app.structure_text(
            structure.structure_of(parse_document(SHOP.read_text()), SHOP.stem))) + "\n"
        self.assertEqual(res.stdout, expected)
        self.assertTrue(res.stdout.startswith("units\n  02-shop  top"))

    def test_json(self):
        res = self.run_view(str(SHOP), "--structure", "--json")
        self.assertEqual(res.returncode, 0, res.stderr)
        data = json.loads(res.stdout)
        self.assertEqual(data, structure.as_json(
            structure.structure_of(parse_document(SHOP.read_text()), SHOP.stem)))
        self.assertEqual(set(data), {"top", "units", "cycles", "up", "edge", "reach",
                                     "pass_throughs", "large", "repeated", "writers",
                                     "summary"})

    def test_takes_no_run_flags(self):
        for extra in (["--sim", "happy"], ["--run"], ["--sim", "all"]):
            with self.subTest(extra):
                res = self.run_view(str(SHOP), "--structure", *extra)
                self.assertEqual(res.returncode, 2)
                self.assertIn("--structure", res.stderr)

    def test_a_dialect_kind_keeps_its_brackets(self):
        sys.path.insert(0, str(ROOT / "tests"))
        from test_export_dialect import PROBE, SPEC
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "probe.sigil"
            path.write_text(SPEC)
            res = self.run_view(str(path), "--structure", "--json", "--dialect", str(PROBE))
        self.assertEqual(res.returncode, 0, res.stderr)
        top = json.loads(res.stdout)["units"][0]
        self.assertIn("[[Ledger]]", top["members"])

    def test_a_missing_file(self):
        res = self.run_view(str(ROOT / "no-such.sigil"), "--structure")
        self.assertEqual(res.returncode, 2)
        self.assertEqual(res.stdout, "")


if __name__ == "__main__":
    unittest.main()
