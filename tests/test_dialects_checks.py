"""The rule-pack hook in dialects.py (RFC 0003 MG16): a dialect's rules join the
check registry and can be acknowledged, a pack reusing a core name or the reserved
`#=` marker is refused, and the core runs without any dialect."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]
_PACK = _DIR / "tests" / "fixtures" / "dialect_pack_resilience.py"


def _load(stem: str):
    key = f"sigil_{stem}_dialect_checks_test"
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, _DIR / f"{stem}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod
        spec.loader.exec_module(mod)
    return sys.modules[key]


dialects = _load("dialects")
ck = _load("check")
lint = _load("lint")

CORE = dialects.CoreNames(
    lint_codes=frozenset(lint.HARDENING_SEVERITY),
    rule_ids=frozenset(ck.CORE_NAMES),
    rule_names=frozenset(ck.CORE_NAMES.values()),
    inv_heads=frozenset({"idempotent", "dedup", "ordered", "lock-order"}))

DOC = textwrap.dedent("""\
    #!craft
    [Api] -> [Pay]: charge() @timeout(2s) ×3
    [Api] -> [Mail]: send() @timeout(1s)
    """)


def _dialect(**hooks) -> types.ModuleType:
    mod = types.ModuleType("probe_dialect")
    mod.NAME = "probe"
    for k, v in hooks.items():
        setattr(mod, k, v)
    return mod


def _rule(rid: str, name: str):
    return ck.Rule(rid, name, "hint", ask="?", why=".", fix=".", match=lambda doc: ())


def _check(text: str, pack_dialect):
    pack = dialects.checked_pack(pack_dialect, ck, CORE)
    registry = ck.default_registry(extra=pack.rules)
    return ck.check(text, dialect=pack_dialect, registry=registry)


class TestPackRuns(unittest.TestCase):
    def setUp(self):
        self.pack = dialects.load(str(_PACK))

    def test_pack_reads_every_hook(self):
        pack = dialects.rule_pack(self.pack, ck)
        self.assertEqual([r.id for r in pack.rules], ["RSL105", "RSL164"])
        self.assertEqual(pack.inv_heads, {"breaker", "bulkhead"})
        self.assertEqual(pack.read_verbs, {"peek"})
        self.assertEqual(pack.policy_words, ())

    def test_rules_join_the_registry_and_fire(self):
        report = _check(DOC, self.pack)
        names = sorted(f.rule.name for f in report.findings)
        self.assertEqual(names, ["shared-pool", "unbroken-dependency"])
        self.assertTrue(all(f.severity == "info" for f in report.findings))
        self.assertTrue(all(f.rule.layer == "dialect" for f in report.findings))

    def test_declared_handling_satisfies(self):
        doc = DOC.replace("[Api] -> [Pay]", "[Api] @inv breaker(5) @inv bulkhead(2) -> [Pay]")
        names = [f.rule.name for f in _check(doc, self.pack).findings]
        self.assertNotIn("unbroken-dependency", names)

    def test_craft_only(self):
        report = _check(DOC.replace("#!craft", "#!spec"), self.pack)
        self.assertEqual([f for f in report.findings if f.rule.id.startswith("RSL")], [])

    def test_pack_rule_can_be_acknowledged(self):
        doc = DOC.replace("[Api] -> [Pay]: charge() @timeout(2s) ×3",
                          "# accepts: unbroken-dependency, shared-pool — the callee sheds load\n"
                          "[Api] -> [Pay]: charge() @timeout(2s) ×3")
        report = _check(doc, self.pack)
        self.assertEqual([f.rule.name for f in report.findings], [])
        self.assertEqual(sorted(f.rule.name for f in report.acknowledged),
                         ["shared-pool", "unbroken-dependency"])

    def test_pack_name_is_unknown_without_the_pack(self):
        doc = "#!craft\n# accepts: shared-pool — local\n[Api] -> [Pay]: charge()\n"
        report = ck.check(doc)
        self.assertIn("ack-unknown-rule", [f.rule.name for f in report.findings])


class TestNamesRefused(unittest.TestCase):
    def _problems(self, **hooks):
        return dialects.name_problems(dialects.rule_pack(_dialect(**hooks), ck), CORE)

    def test_core_lint_code_refused(self):
        self.assertEqual(self._problems(LINT_CODES={"SGL120", "XYZ001"}),
                         ["lint code SGL120 is a core code"])

    def test_core_check_id_as_lint_code_refused(self):
        self.assertEqual(self._problems(LINT_CODES={"SGC101"}),
                         ["lint code SGC101 is a core code"])

    def test_rule_reusing_core_name_or_id_refused(self):
        rules = lambda api: [_rule("RSL001", "unguarded-call"), _rule("SGL150", "own-name")]
        self.assertEqual(self._problems(check_rules=rules),
                         ["rule RSL001: `unguarded-call` is a core rule name",
                          "rule id SGL150 is a core id"])

    def test_core_inv_head_refused(self):
        self.assertEqual(self._problems(INV_HEADS={"idempotent", "breaker"}),
                         ["@inv head `idempotent` is a core head"])

    def test_checked_pack_raises_with_every_problem(self):
        d = _dialect(LINT_CODES={"SGL188"}, COMMENT_MARKERS=[r"#="])
        with self.assertRaises(dialects.DialectError) as cm:
            dialects.checked_pack(d, ck, CORE)
        self.assertIn("SGL188", str(cm.exception))
        self.assertIn("#=", str(cm.exception))

    def test_example_pack_is_clean(self):
        self.assertEqual(dialects.name_problems(
            dialects.rule_pack(dialects.load(str(_PACK)), ck), CORE), [])


class TestReservedMarker(unittest.TestCase):
    def test_markers_claiming_it(self):
        for src in (r"#=", r"#[=+]", r"#.", r"#=\s*", r"(?:#=|//)"):
            with self.subTest(src=src):
                self.assertIsNotNone(dialects.marker_problem(src))

    def test_markers_not_claiming_it(self):
        for src in (r"-//", r"\\-//", r"#&", r"//", r"#(?!=)"):
            with self.subTest(src=src):
                self.assertIsNone(dialects.marker_problem(src))

    def test_invalid_regex_reported(self):
        self.assertIn("not a valid regex", dialects.marker_problem("(#"))

    def test_load_refuses_and_forgets(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sigil-claims" / "dialect.py"
            path.parent.mkdir()
            path.write_text('COMMENT_MARKERS = [r"#="]\n', encoding="utf-8")
            with self.assertRaises(dialects.DialectError):
                dialects.load(str(path))
            self.assertNotIn(dialects._module_name(path.resolve()), sys.modules)
            with self.assertRaises(ValueError):       # still refused on a second load
                dialects.load(str(path))


class TestCoreWithoutDialect(unittest.TestCase):
    def test_empty_pack(self):
        self.assertEqual(dialects.checked_pack(None, ck, CORE), dialects.RulePack())

    def test_core_registry_unchanged(self):
        self.assertEqual(sorted(ck.default_registry(extra=dialects.RulePack().rules)),
                         sorted(ck.default_registry()))
        self.assertFalse(any(r.layer == "dialect" for r in ck.default_registry().values()))


if __name__ == "__main__":
    unittest.main()
