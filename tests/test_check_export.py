"""Export readiness (check_export.py): SGC401 no-home and SGC402 untyped-boundary,
active only when a check is asked for export readiness (`check.py --export`,
`check(…, export=True)`). Each rule's evidence is a fixture,
tests/fixtures/checks/export-*.sigil, a flagged form and a fixed (or
acknowledged) one, whose `# expect: LINE:RULE` header (`none` for a quiet one)
names the readiness findings it gives. A plain check never runs the rules, and an
acknowledgement of one is neither unknown nor stale there.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]
_FIXTURES = _DIR / "tests" / "fixtures" / "checks"


def _load(key: str, fname: str):
    spec = importlib.util.spec_from_file_location(key, _DIR / fname)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


ck = _load("sigil_check_export_suite_check", "check.py")
cx = _load("sigil_check_export_suite_rules", "check_export.py")

EXPORT_IDS = ("SGC401", "SGC402")
FIXTURES = sorted(_FIXTURES.glob("export-*.sigil"))


def doc(text: str) -> str:
    return textwrap.dedent(text).lstrip("\n")


def expected_of(text: str) -> list:
    """The `# expect: LINE:RULE` lines of a fixture's header."""
    return [(int(m[1]), m[2]) for m in re.finditer(r"^# expect: (\d+):(\w+)$", text, re.M)]


def run(text: str, mode=None, export=True):
    return ck.check(text, mode=mode, overlaps="off", export=export)


def readiness(findings) -> list:
    return [(f.line, f.rule.id) for f in findings if f.rule.id in EXPORT_IDS]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class Registration(unittest.TestCase):
    def test_the_rules_match_the_catalog(self):
        rules = cx.rules(ck)
        self.assertEqual([r.id for r in rules], list(EXPORT_IDS))
        for r in rules:
            with self.subTest(rule=r.id):
                self.assertEqual(r.name, ck.EXPORT_NAMES[r.id])
                self.assertEqual(r.tier, "binding")
                self.assertEqual(r.layer, "export")
                self.assertTrue(r.ask.endswith("?"))
                self.assertTrue(r.why and r.fix)

    def test_only_an_export_check_registers_them(self):
        self.assertFalse(set(EXPORT_IDS) & set(ck.default_registry()))
        self.assertLessEqual(set(EXPORT_IDS), set(ck.default_registry(export=True)))

    def test_the_core_catalog_is_unchanged(self):
        self.assertFalse(set(EXPORT_IDS) & set(ck.CORE_NAMES))
        self.assertEqual(len(ck.registry_lines(ck.default_registry())), len(ck.CORE_NAMES))

    def test_the_listing_names_them(self):
        listing = ck.registry_lines(ck.default_registry(export=True))
        self.assertIn("SGC401  no-home", "\n".join(listing))
        self.assertIn("SGC402  untyped-boundary", "\n".join(listing))

    def test_their_ids_and_names_are_reserved(self):
        rule = lambda rid, name: ck.Rule(rid, name, "binding", "?", "w", "f",
                                         match=lambda d: [])
        with self.assertRaisesRegex(ck.RegistryError, "catalog"):
            ck.build_registry([rule("SGC401", "homeless")])
        with self.assertRaisesRegex(ck.RegistryError, "core name"):
            ck.build_registry([rule("PCK001", "no-home")])
        names = ck.core_names()
        self.assertIn("SGC402", names.rule_ids)
        self.assertIn("untyped-boundary", names.rule_names)


# ---------------------------------------------------------------------------
# The fixtures
# ---------------------------------------------------------------------------

class Fixtures(unittest.TestCase):
    def test_there_is_a_flagged_and_a_fixed_form_of_each_rule(self):
        names = {p.stem for p in FIXTURES}
        for stem in ("no-home", "untyped-boundary"):
            with self.subTest(rule=stem):
                self.assertIn(f"export-{stem}", names)
                self.assertIn(f"export-{stem}-fixed", names)

    def test_each_fixture_gives_its_expected_findings(self):
        self.assertTrue(FIXTURES)
        for path in FIXTURES:
            text = path.read_text(encoding="utf-8")
            with self.subTest(fixture=path.name):
                self.assertRegex(text, r"(?m)^# expect: ")
                self.assertEqual(readiness(run(text).findings), expected_of(text))

    def test_a_plain_check_never_runs_them(self):
        for path in FIXTURES:
            text = path.read_text(encoding="utf-8")
            with self.subTest(fixture=path.name):
                rep = run(text, export=False)
                self.assertEqual(readiness(rep.findings + rep.acknowledged), [])

    def test_the_rest_of_the_report_is_the_plain_one(self):
        for path in FIXTURES:
            text = path.read_text(encoding="utf-8")
            with self.subTest(fixture=path.name):
                plain = ck.format_lines(run(text, export=False), True)
                ready = [ln for ln in ck.format_lines(run(text), True)
                         if not re.match(r"\w+:\d+:SGC40[12]:", ln)]
                self.assertEqual(ready, plain)


# ---------------------------------------------------------------------------
# Severity and wording
# ---------------------------------------------------------------------------

FLAGGED = doc("""
    #!spec
    (User) -> [Shop] : buy({Order})

    [Shop] := {
      [Cart] -> |Db| : save({Order}) => {Ack}
    }

    [Billing] := {
      [Ledger] -> |Db| : record({Order}) => {Ack}
    }
    """)


class Grading(unittest.TestCase):
    def severities(self, mode):
        rep = run(FLAGGED, mode=mode)
        return sorted((f.rule.id, f.severity, f.hidden) for f in rep.findings
                      if f.rule.id in EXPORT_IDS)

    def test_binding_tier(self):
        self.assertEqual(self.severities("spec"), [("SGC401", "error", False),
                                                   ("SGC402", "error", False)])
        self.assertEqual(self.severities("craft"), [("SGC401", "warn", False),
                                                    ("SGC402", "warn", False)])
        self.assertEqual({s[1:] for s in self.severities("sketch")}, {("info", True)})

    def test_no_home_names_the_systems(self):
        hit = next(f for f in run(FLAGGED).findings if f.rule.id == "SGC401")
        self.assertEqual(hit.line, 5)
        self.assertIn("`|Db|` is written in `Shop` and `Billing`", hit.message)
        self.assertIn("exported under `Shop`", hit.message)

    def test_untyped_boundary_says_what_is_missing(self):
        text = doc("""
            #!craft
            (User) -> [Shop] : buy({Order})
            [Shop] ~> [Mailer]
            [Shop] := {
              [Cart] -> |Orders| : save({Order}) => {Ack}
            }
            """)
        got = {f.line: f.message for f in run(text).findings if f.rule.id == "SGC402"}
        self.assertEqual(got[2], "`(User) -> [Shop]` is a call across the boundary of "
                                 "`Shop`. What does it return?")
        self.assertEqual(got[3], "`[Shop] ~> [Mailer]` crosses the boundary of `Shop`. "
                                 "What does it carry?")

    def test_system_list_names_the_top_level_in_words(self):
        self.assertEqual(cx.system_list(("A",), "top"), "`A`")
        self.assertEqual(cx.system_list(("A", "top", "B"), "top"),
                         "`A`, the top level and `B`")

    def test_async_and_returning_calls_pass(self):
        text = doc("""
            #!spec
            (User) -> [Shop] : buy({Order}) => {Receipt}
            [Shop] ~> [Mailer] : notify({Receipt})
            [Shop] *> [Audit] : log({Order})
            [Shop] := {
              [Cart] -> |Orders| : save({Order}) => {Ack}
            }
            """)
        self.assertEqual(readiness(run(text).findings), [])


# ---------------------------------------------------------------------------
# Acknowledgements
# ---------------------------------------------------------------------------

ACKED = doc("""
    #!spec
    (User) -> [Shop] : buy({Order})   # accepts: untyped-boundary — a status code only
    [Shop] := {
      [Cart] -> |Orders| : save({Order}) => {Ack}
    }
    """)


class Acknowledgements(unittest.TestCase):
    def test_an_acknowledgement_covers_the_finding(self):
        rep = run(ACKED)
        self.assertEqual(readiness(rep.findings), [])
        self.assertEqual(readiness(rep.acknowledged), [(2, "SGC402")])

    def test_a_plain_check_knows_the_name_and_judges_it_not_stale(self):
        rep = run(ACKED, export=False)
        self.assertEqual([f.rule.id for f in rep.findings
                          if f.rule.id in ("SGC001", "SGC003")], [])

    def test_a_stale_one_is_stale_in_an_export_check(self):
        text = ACKED.replace("buy({Order})   #", "buy({Order}) => {Receipt}   #")
        rep = run(text)
        self.assertEqual([(f.line, f.rule.id) for f in rep.findings
                          if f.rule.id == "SGC003"], [(2, "SGC003")])
        self.assertEqual([f.rule.id for f in run(text, export=False).findings
                          if f.rule.id == "SGC003"], [])

    def test_a_misspelt_one_is_unknown_with_a_hint(self):
        text = ACKED.replace("untyped-boundary", "untyped-boundry")
        rep = run(text, export=False)
        hits = [f for f in rep.findings if f.rule.id == "SGC001"]
        self.assertEqual(len(hits), 1)
        self.assertIn("untyped-boundary", hits[0].message)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class Cli(unittest.TestCase):
    def cli(self, *args, stdin=None):
        return subprocess.run([sys.executable, str(_DIR / "check.py"), *args],
                              input=stdin, capture_output=True, text=True,
                              encoding="utf-8")

    def test_export_flag(self):
        path = str(_FIXTURES / "export-no-home.sigil")
        ready = self.cli(path, "--export", "--overlaps", "off")
        self.assertEqual(ready.returncode, 2)
        self.assertIn("error:9:SGC401: no-home:", ready.stdout)
        plain = self.cli(path, "--overlaps", "off")
        self.assertEqual(plain.returncode, 0)
        self.assertNotIn("SGC401", plain.stdout)

    def test_export_json(self):
        path = str(_FIXTURES / "export-untyped-boundary.sigil")
        data = json.loads(self.cli(path, "--export", "--overlaps", "off", "--json").stdout)
        self.assertEqual([(f["line"], f["rule"]) for f in data["findings"]
                          if f["rule"] in EXPORT_IDS], [(7, "SGC402"), (8, "SGC402")])

    def test_fixed_spec_passes(self):
        path = str(_FIXTURES / "export-untyped-boundary-fixed.sigil")
        self.assertEqual(self.cli(path, "--export", "--overlaps", "off").returncode, 0)

    def test_rules_lists_them(self):
        out = self.cli("--rules").stdout
        self.assertIn("SGC401  no-home", out)
        self.assertIn("SGC402  untyped-boundary", out)


if __name__ == "__main__":
    unittest.main()
