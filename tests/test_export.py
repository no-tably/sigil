"""`sigil export` (sigil.publish.exporter): the gate, the plan, the Markdown and JSON writers, the write order."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_DIR))

from sigil import cli  # noqa: E402
from sigil.analyse import check, lint  # noqa: E402
from sigil.publish import exporter as export  # noqa: E402
from sigil.publish import systems as em  # noqa: E402

SIGIL = _DIR / "bin" / "sigil"
FIXTURES = _DIR / "tests" / "fixtures" / "checks"

READY = """\
#!spec
# a shop and its billing

(User) -> [Shop] : buy({Order}) => {Receipt}
[Shop] -> [Billing] : charge({Order}) => {Receipt} ×3 @after(1s) @timeout(2s) @inv idempotent(key) @fallback("queued")

[Shop] := {
  # keeps the basket
  [Cart] -> |Db| : save({Order}) => {Ack}
}

[Billing] := {   # accepts: unit-cycle — the ledger records into the shop it bills for
  [Ledger] -> [Shop] : record({Order}) => {Ack}
}
"""

# The same spec reformatted and reordered: no system file may change.
REORDERED = """\
#!spec
# a shop and its billing

[Billing] := {   # accepts: unit-cycle — the ledger records into the shop it bills for
  [Ledger]   ->   [Shop] : record({Order}) => {Ack}
}

[Shop] := {
  # keeps the basket
  [Cart] -> |Db| : save({Order}) => {Ack}
}

[Shop] -> [Billing] : charge({Order}) => {Receipt} ×3 @after(1s) @timeout(2s) @inv idempotent(key) @fallback("queued")
(User) -> [Shop] : buy({Order}) => {Receipt}
"""


def run(argv) -> tuple:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(["export", *argv])
    return code, out.getvalue(), err.getvalue()


def unplaced(text: str):
    """A system.json without its `lines` (where things are written)."""
    def drop(obj):
        if isinstance(obj, dict):
            return {k: drop(v) for k, v in obj.items() if k not in ("lines", "line")}
        if isinstance(obj, list):
            return [drop(v) for v in obj]
        return obj
    return drop(json.loads(text))


def tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
            for p in sorted(root.rglob("*")) if p.is_file()}


class Tmp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def spec(self, text: str, name: str = "store.sigil") -> Path:
        p = self.tmp / name
        p.write_text(text, encoding="utf-8")
        return p

    def export(self, text: str, out: str = "out", name: str = "store.sigil") -> tuple:
        return run([str(self.spec(text, name)), "--out", str(self.tmp / out)])


class TestGate(unittest.TestCase):
    def gate(self, text: str) -> tuple:
        return export.gate(text, None, lint, check)

    def test_ready_spec_passes(self):
        self.assertEqual(self.gate(READY), ())

    def test_info_does_not_block(self):
        text = (FIXTURES / "export-no-home-fixed.sigil").read_text(encoding="utf-8")
        report = check.check(text, mode="spec", export=True)
        self.assertTrue(any(f.severity == "info" for f in report.shown))
        self.assertEqual(self.gate(text), ())

    def test_only_spec_mode_exports(self):
        for mode in ("sketch", "craft"):
            with self.subTest(mode=mode):
                lines = self.gate(READY.replace("#!spec", f"#!{mode}"))
                self.assertEqual(len(lines), 1)
                self.assertIn(f"#!{mode}", lines[0])
        self.assertIn("#!sketch", self.gate(READY.replace("#!spec\n", ""))[0])

    def test_lint_error_blocks(self):
        lines = self.gate(READY + "[Shop] := {\n  [Loose] -> [Cart] : {Order}\n")
        self.assertTrue(lines)
        self.assertTrue(all(ln.startswith("error:") and ":SGL" in ln for ln in lines), lines)

    def test_readiness_rules_block(self):
        for name, rule in (("export-no-home.sigil", "SGC401"),
                           ("export-untyped-boundary.sigil", "SGC402")):
            with self.subTest(name=name):
                lines = self.gate((FIXTURES / name).read_text(encoding="utf-8"))
                self.assertTrue(any(f":{rule}:" in ln for ln in lines), lines)

    def test_acknowledged_finding_does_not_block(self):
        text = (FIXTURES / "export-untyped-boundary-declared.sigil").read_text(encoding="utf-8")
        self.assertEqual(self.gate(text), ())

    def test_unacknowledged_warning_blocks(self):
        risky = READY.replace(" @inv idempotent(key)", "")
        lines = self.gate(risky)
        self.assertEqual([ln.split(":")[2] for ln in lines], ["SGC111"], lines)
        self.assertTrue(lines[0].startswith("warn:"))
        accepted = risky.replace('@fallback("queued")', '@fallback("queued")   '
                                 '# accepts: retry-without-idempotency — a keyed upsert')
        self.assertEqual(self.gate(accepted), ())


class TestOutFolder(Tmp):
    def test_missing_or_empty_folder_is_fine(self):
        self.assertIsNone(export.out_problem(self.tmp / "nope"))
        self.assertIsNone(export.out_problem(self.tmp))

    def test_earlier_export_is_fine(self):
        (self.tmp / "README.md").write_text("x")
        (self.tmp / export.MANIFEST).write_text("{}")
        self.assertIsNone(export.out_problem(self.tmp))

    def test_foreign_folder_or_file_is_refused(self):
        (self.tmp / "README.md").write_text("mine")
        self.assertIn("no manifest.json", export.out_problem(self.tmp))
        self.assertIn("not a folder", export.out_problem(self.tmp / "README.md"))


class TestPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = em.build_model(READY, "store")
        cls.plan = export.plan_export(cls.model, "store.sigil", READY)

    def test_manifest_shape(self):
        m = self.plan.manifest
        self.assertEqual(m["sigil_export"], 1)
        self.assertEqual(m["spec"], "store.sigil")
        self.assertEqual(m["spec_hash"], export.spec_hash(READY))
        self.assertEqual(len(m["spec_hash"]), em.HASH_LEN)
        self.assertEqual(list(m["systems"]), export.system_order(self.model))
        self.assertEqual(set(m["systems"]), set(self.model.systems))
        for key, e in m["systems"].items():
            s = self.model.systems[key]
            with self.subTest(system=key):
                self.assertEqual(set(e), {"path", "interface", "body", "components",
                                          "depends_on", "parent", "component_hashes"})
                self.assertEqual(e["parent"], s.parent)
                self.assertEqual(e["interface"], s.interface_hash)
                self.assertEqual(e["body"], s.body_hash)
                self.assertEqual(list(e["component_hashes"]), e["components"])
                for nid in s.members:
                    c = self.model.components[nid]
                    self.assertEqual(e["component_hashes"][c.glyph],
                                     {"interface": c.interface_hash, "body": c.body_hash})
                self.assertEqual(e["depends_on"], list(s.depends_on))
                self.assertEqual(sorted(e["components"]),
                                 sorted(self.model.components[c].glyph for c in s.members))

    def test_top_system_first_and_folders_are_slugs(self):
        self.assertEqual(next(iter(self.plan.systems)), "store")
        self.assertEqual({k: p.path for k, p in self.plan.systems.items()},
                         em.slugs(export.system_order(self.model)))

    def test_system_json_is_the_models_form(self):
        for key, sp in self.plan.systems.items():
            with self.subTest(system=key):
                self.assertEqual(json.loads(sp.files[export.SYSTEM_JSON]),
                                 em.system_json(self.model.systems[key],
                                                self.model.components))

    def test_one_file_per_component(self):
        shop = self.plan.systems["Shop"].files
        self.assertEqual(set(shop), {"README.md", "system.json", "cart.md", "db.md"})

    def test_component_file_names_avoid_readme_and_collisions(self):
        names = export.component_files([{"glyph": "[Readme]"}, {"glyph": "[Order]"},
                                        {"glyph": "{Order}"}])
        self.assertEqual(names, {"[Readme]": "readme-2.md", "[Order]": "order.md",
                                 "{Order}": "order-2.md"})

    def test_plan_is_pure(self):
        again = export.plan_export(em.build_model(READY, "store"), "store.sigil", READY)
        self.assertEqual(again, self.plan)


class TestMarkdown(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        model = em.build_model(READY, "store")
        cls.plan = export.plan_export(model, "store.sigil", READY)

    def test_mod_text_as_written(self):
        cases = {("×", "3"): "×3", ("^", "10k@drop"): "^10k@drop", (".", "age"): ".age",
                 ("!", None): "!", ("inv", "idempotent(key)"): "@inv idempotent(key)",
                 ("timeout", "2s"): "@timeout(2s)", ("owns", None): "@owns"}
        for pair, want in cases.items():
            with self.subTest(pair=pair):
                self.assertEqual(export.mod_text(pair), want)

    def test_flow_text(self):
        f = {"arrow": "->", "payload": "charge({Order}) => {Receipt}",
             "mods": [["timeout", "2s"], ["×", "3"]], "card": "N"}
        self.assertEqual(export.flow_text("[Shop]", "[Billing]", f),
                         "[Shop] -> [Billing]×N : charge({Order}) => {Receipt} "
                         "@timeout(2s) ×3")

    def test_component_md_states_everything_verbatim(self):
        md = self.plan.systems["store"].files["shop.md"]
        self.assertTrue(md.startswith("# [Shop]\n"))
        self.assertIn("Kind: service.", md)
        self.assertIn("`[Shop] -> [Billing] : charge({Order}) => {Receipt} @after(1s) "
                      '@fallback("queued") @inv idempotent(key) @timeout(2s) ×3`', md)
        self.assertIn("`(User) -> [Shop] : buy({Order}) => {Receipt}` — sync call", md)
        cart = self.plan.systems["Shop"].files["cart.md"]
        self.assertIn("## Description\n\nkeeps the basket\n", cart)

    def test_requirements_and_lifecycle(self):
        c = {"glyph": "{Order}", "kind": "data",
             "requirements": {"modifiers": [["inv", "idempotent(key)"], ["×", "4"]],
                              "access": [["read", "|Db|"]],
                              "accepts": ["accepts: race — one writer at a time"]},
             "lifecycle": {"states": ["Open", "Paid"], "initial": ["Open"],
                           "terminal": ["Paid"],
                           "transitions": [{"from": "Open", "to": "Paid", "on": "<Paid>",
                                            "mods": [["after", "1h"]]}]}}
        md = export.component_md(c, "top", "top")
        for want in ("- `@inv idempotent(key)`", "- `×4`",
                     "- read access to `|Db|`", "- accepts: race — one writer at a time",
                     "## Lifecycle", "States: `Open`, `Paid`.", "Initial: `Open`.",
                     "Terminal: `Paid`.", "- `Open` → `Paid` on `<Paid>` `@after(1h)`"):
            with self.subTest(want=want):
                self.assertIn(want, md)

    def test_system_md(self):
        md = self.plan.systems["Shop"].files["README.md"]
        self.assertTrue(md.startswith("# Shop\n"))
        self.assertIn("The expansion of `[Shop]` (inside system `store`).", md)
        self.assertIn("## Boundary", md)
        self.assertIn("- `[Cart]` (service) — [cart.md](cart.md)", md)
        self.assertIn("`Billing` — [billing/](../billing/README.md)", md)
        self.assertIn(self.plan.manifest["systems"]["Shop"]["body"], md)

    def test_index_lists_every_system(self):
        for key, sp in self.plan.systems.items():
            with self.subTest(system=key):
                self.assertIn(f"- `{key}` (", self.plan.index)
                self.assertIn(f"]({sp.path}/README.md)", self.plan.index)


class TestWrite(Tmp):
    def test_export_writes_the_layout(self):
        code, out, err = self.export(READY)
        self.assertEqual(code, 0, err)
        files = tree(self.tmp / "out")
        self.assertEqual(set(files), {
            "manifest.json", "README.md", "delta.json",
            "store/README.md", "store/system.json", "store/user.md", "store/shop.md",
            "store/billing.md",
            "shop/README.md", "shop/system.json", "shop/cart.md", "shop/db.md",
            "billing/README.md", "billing/system.json", "billing/ledger.md"})
        manifest = json.loads(files["manifest.json"])
        self.assertEqual(manifest["systems"]["Shop"]["path"], "shop")
        self.assertIn("3 system(s)", out)
        self.assertFalse([p for p in (self.tmp / "out").iterdir() if p.name.endswith(".tmp")])

    def test_manifest_written_last_through_replace(self):
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
            self.assertEqual(self.export(READY)[0], 0)
        self.assertEqual(order[-1], ("replace", "manifest.json"))
        self.assertEqual(order[-3:-1], ["README.md", "delta.json"])
        self.assertNotIn("manifest.json", order[:-1])

    def test_failed_manifest_leaves_no_temp_and_no_manifest(self):
        with mock.patch.object(export.os, "replace", side_effect=OSError("disk full")):
            code, _out, err = self.export(READY)
        self.assertEqual(code, 1)
        self.assertIn("disk full", err)
        out = self.tmp / "out"
        self.assertFalse((out / "manifest.json").exists())
        self.assertFalse([p for p in out.iterdir() if p.name.endswith(".tmp")])

    def test_blocked_spec_touches_nothing(self):
        code, out, err = self.export(READY.replace("#!spec", "#!sketch"))
        self.assertEqual(code, 2)
        self.assertIn("#!sketch", out)
        self.assertIn("not ready to export", err)
        self.assertFalse((self.tmp / "out").exists())

    def test_blocked_spec_prints_the_check_lines(self):
        text = (FIXTURES / "export-no-home.sigil").read_text(encoding="utf-8")
        code, out, _err = self.export(text)
        self.assertEqual(code, 2)
        self.assertIn(":SGC401:", out)
        self.assertFalse((self.tmp / "out").exists())

    def test_foreign_folder_is_refused_untouched(self):
        out = self.tmp / "out"
        out.mkdir()
        (out / "README.md").write_text("mine", encoding="utf-8")
        code, _out, err = self.export(READY)
        self.assertEqual(code, 2)
        self.assertIn("no manifest.json", err)
        self.assertEqual(tree(out), {"README.md": "mine"})

    def test_bad_input(self):
        code, _out, err = run([str(self.tmp / "missing.sigil"), "--out", str(self.tmp / "o")])
        self.assertEqual(code, 2)
        self.assertIn("sigil export:", err)
        code, _out, err = run([str(self.spec(READY)), "--out", str(self.tmp / "o"),
                               "--dialect", "no-such-dialect"])
        self.assertEqual(code, 2)
        self.assertIn("no-such-dialect", err)

    def test_reexport_drops_a_removed_component_file(self):
        self.assertEqual(self.export(READY)[0], 0)
        self.assertTrue((self.tmp / "out" / "shop" / "db.md").exists())
        less = READY.replace("[Cart] -> |Db| : save({Order}) => {Ack}",
                             "[Cart] -> [Ledger2] : save({Order}) => {Ack}")
        self.assertEqual(self.export(less)[0], 0)
        self.assertFalse((self.tmp / "out" / "shop" / "db.md").exists())
        self.assertTrue((self.tmp / "out" / "shop" / "ledger2.md").exists())

    def test_write_only_some_systems(self):
        plan = export.plan_export(em.build_model(READY, "store"), "store.sigil", READY)
        out = self.tmp / "part"
        export.write_export(out, plan, only=["Billing"])
        self.assertEqual(sorted(p.name for p in out.iterdir()),
                         ["README.md", "billing", "manifest.json"])

    def test_reformatting_changes_no_system_file(self):
        self.assertEqual(self.export(READY, out="a")[0], 0)
        self.assertEqual(self.export(REORDERED, out="b")[0], 0)
        a, b = tree(self.tmp / "a"), tree(self.tmp / "b")
        self.assertEqual(set(a), set(b))
        for name in a:
            if name.endswith("/system.json"):   # only its lines move
                with self.subTest(file=name):
                    self.assertEqual(unplaced(a[name]), unplaced(b[name]))
            elif "/" in name:
                with self.subTest(file=name):
                    self.assertEqual(a[name], b[name])
        ma, mb = json.loads(a["manifest.json"]), json.loads(b["manifest.json"])
        self.assertNotEqual(ma["spec_hash"], mb["spec_hash"])
        self.assertEqual(list(ma["systems"].items()), list(mb["systems"].items()))


class TestCommand(unittest.TestCase):
    def test_help_and_executable(self):
        self.assertTrue(os.access(SIGIL, os.X_OK))
        r = subprocess.run([sys.executable, str(SIGIL), "export", "--help"],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0)
        for word in ("--out", "--dialect", "#!spec"):
            self.assertIn(word, r.stdout)

    def test_out_is_required(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            cli.main(["export", "x.sigil"])
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
