"""`sigil export --mermaid` (today's chart, any mode) and `--mermaid --spine`
(the chart grouped by the export's systems), plus the export rough edges folded
in with them: a flow into a face depends on the face's system alone, the
SGC204 hint names the store's own line, and the plain check's idle-rule filter
matches SGC003 by rule id.

The spine goldens live in tests/golden/spine/<example>.mmd (outside
tools/golden.py's suffixes). After an intended change, rewrite them with
`bin/sigil export site/examples/<example>.sigil --mermaid --spine`.
"""

import contextlib
import io
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigil import cli                               # noqa: E402
from sigil.analyse import check as ck               # noqa: E402
from sigil.publish import mermaid, spine            # noqa: E402
from sigil.publish import systems as export_systems  # noqa: E402

EXAMPLES = ROOT / "site" / "examples"
SPINE_GOLDEN = ROOT / "tests" / "golden" / "spine"
SPINE_INPUTS = ("02-shop", "07-export")


def doc(text: str) -> str:
    return textwrap.dedent(text).lstrip("\n")


def run_cli(argv: list) -> tuple:
    """(exit status, stdout) of `sigil …` run in-process."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = cli.main(argv)
    return code, out.getvalue()


class MermaidExportTest(unittest.TestCase):
    def test_prints_the_render_chart_in_every_mode(self):
        body = "[Api] -> |Db| : put({Row}) => {Ack}\n"
        for mode in ("#!sketch", "#!craft", "#!spec"):
            with self.subTest(mode=mode):
                text = f"{mode}\n{body}"
                path = self.write(text)
                code, out = run_cli(["export", str(path), "--mermaid", "--depth", "2"])
                self.assertEqual(code, 0)
                self.assertEqual(out, mermaid.render(text, depth=2) + "\n")

    def write(self, text: str) -> Path:
        d = Path(tempfile.mkdtemp(prefix="sigil-mermaid-"))
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        p = d / "doc.sigil"
        p.write_text(text, encoding="utf-8")
        return p


class SpineTest(unittest.TestCase):
    def test_goldens(self):
        for name in SPINE_INPUTS:
            with self.subTest(example=name):
                code, out = run_cli(["export", str(EXAMPLES / f"{name}.sigil"),
                                     "--mermaid", "--spine"])
                self.assertEqual(code, 0)
                self.assertEqual(out, (SPINE_GOLDEN / f"{name}.mmd").read_text(encoding="utf-8"))

    def test_one_subgraph_per_system_but_the_top(self):
        text = (EXAMPLES / "07-export.sigil").read_text(encoding="utf-8")
        model = export_systems.build_model(text, "07-export")
        chart = spine.spine(text, "07-export")
        heads = [ln.strip() for ln in chart.splitlines() if ln.strip().startswith("subgraph ")]
        self.assertEqual(len(heads), len(model.systems) - 1)
        for key in model.systems:
            self.assertEqual(f'["{key}"]' in chart, key != model.top)

    def test_nested_systems_nest(self):
        chart = spine.spine(doc("""
            [Shop] := {
              [Cart] -> [Pay] : pay({Total}) => {Receipt}
              [Pay] := {
                [Psp] -> |Ledger| : post({Entry}) => {Ack}
              }
            }
        """), "doc")
        lines = chart.splitlines()
        shop = lines.index('    subgraph system__shop["Shop"]')
        pay = lines.index('        subgraph system__pay["Pay"]')
        self.assertLess(shop, pay)
        self.assertIn('            Psp_service["Psp"]', lines)

    def test_a_subgraph_id_never_takes_a_node_id(self):
        chart = spine.spine(doc("""
            [system__x] -> [x_service] : go({X}) => {Y}
            [x_service] := {
              [W] -> |S| : put({X}) => {Ack}
            }
        """), "doc")
        self.assertIn('    system__x_service["system__x"]', chart)
        self.assertIn('subgraph system__x_service_2["x_service"]', chart)

    def test_draws_without_the_export_gate(self):
        code, out = run_cli(["export", str(ROOT / "tests" / "fixtures" / "overlap.sigil"),
                             "--mermaid", "--spine"])
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("flowchart TD\n"))


class FaceDependencyTest(unittest.TestCase):
    TEXT = doc("""
        #!spec
        [A] -> [B] : go({X}) => {Y}
        [A] := {
          [W] -> [B] : go({X}) => {Y}
        }
        [B] := {
          [V] -> |S| : put({X}) => {Ack}
        }
    """)

    def test_a_flow_into_a_face_depends_on_its_system_alone(self):
        model = export_systems.build_model(self.TEXT, "doc")
        self.assertEqual(model.systems["A"].depends_on, ("B",))
        self.assertEqual(model.systems["doc"].depends_on, ("A", "B"))

    def test_a_member_at_the_top_is_still_a_dependency(self):
        model = export_systems.build_model(doc("""
            [A] := {
              [W] -> |Db| : put({X}) => {Ack}
            }
            |Db| -> [A] : load({X}) => {Y}
        """), "doc")
        self.assertEqual(model.systems["A"].depends_on, ("doc",))


class CheckEdgesTest(unittest.TestCase):
    def test_the_race_hint_names_the_store_line(self):
        rep = ck.check((ROOT / "tests" / "fixtures" / "checks"
                        / "state-race-many-callers.sigil").read_text(encoding="utf-8"),
                       mode="spec")
        (f,) = [f for f in rep.findings if f.rule.id == "SGC204"]
        self.assertIn("`@inv serialised(|S|)` on the store's own line", f.fix)

    def test_an_ack_of_an_idle_readiness_rule_is_not_stale_in_a_plain_check(self):
        text = doc("""
            #!spec
            # accepts: no-home — the shared cache is homed by hand
            [Api] -> |Db| : put({Row}) => {Ack}
        """)
        plain = [f.rule.id for f in ck.check(text).findings + ck.check(text).acknowledged]
        self.assertNotIn("SGC003", plain)
        export = [f.rule.id for f in ck.check(text, export=True).findings]
        self.assertIn("SGC003", export)

    def test_the_idle_filter_reads_the_rule_id(self):
        rule = ck.Rule("SGC003", "ack-unused", "advisory", ask="", why="", fix="",
                       match=lambda doc: iter(()))
        about = ck.Finding(rule, ck.Hit(1, "", "", about="SGC401"), "info", False, "", "spec")
        other = ck.Finding(rule, ck.Hit(1, "", "", about="SGC131"), "info", False, "", "spec")
        idle = ck.idle_ids(ck.default_registry())
        self.assertEqual(idle, frozenset(ck.EXPORT_NAMES))
        self.assertTrue(ck.about_idle_rule(about, idle))
        self.assertFalse(ck.about_idle_rule(other, idle))
        self.assertEqual(ck.idle_ids(ck.default_registry(export=True)), frozenset())


if __name__ == "__main__":
    unittest.main()
