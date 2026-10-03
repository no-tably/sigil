"""`lint.py --deep`: lint, then the composition checks (check.py), one merged report.

The CLI is run as a subprocess (the way agents and the packaged skill run it);
`deep_lines` is also tested directly for the merge order.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(modname: str, filename: str):
    mod = sys.modules.get(modname)
    if mod is None:
        spec = importlib.util.spec_from_file_location(modname, ROOT / filename)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[modname] = mod
        spec.loader.exec_module(mod)
    return mod


lint = _load("sigil_lint_for_deep_tests", "lint.py")

CLEAN = "#!sketch\n\n--- T ---\n(User) -> [API] -> |DB|\n"

# Line 4 gets a check finding (capacity), line 5 one (two writers), line 7 a lint
# note (an invented modifier): the merged list interleaves them by line.
MIXED = ("#!spec\n\n--- Shop ---\n"
         "(User) -> [Api] : go()\n"
         "[Api] -> |Doc| : put({Doc})\n"
         "[Job] -> |Doc| : put({Doc})\n"
         "[Api] @fast\n")

ACKED = ("#!spec\n\n--- Shop ---\n"
         "(User) -> [Api] : go()   # accepts: capacity-mismatch — one user\n"
         "[Api] -> |Doc| : put({Doc})   # accepts: shared-writable-store — last write wins\n"
         "[Job] -> |Doc| : put({Doc})\n")


def run_lint(text: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "lint.py"), "-", *args],
                          input=text, capture_output=True, text=True, encoding="utf-8")


def codes(stdout: str) -> list:
    """(line, code) per output row, in printed order."""
    return [(int(row.split(":")[1]), row.split(":")[2]) for row in stdout.splitlines()]


class DeepCli(unittest.TestCase):
    def test_without_deep_no_check_runs(self):
        r = run_lint(MIXED)
        self.assertNotIn("SGC", r.stdout)
        self.assertNotIn("sigil check", r.stderr)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_clean_document(self):
        r = run_lint(CLEAN, "--deep")
        self.assertEqual(r.stdout.strip(), "sigil: OK (no issues, no findings)")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_reports_are_merged_by_line(self):
        r = run_lint(MIXED, "--deep")
        rows = codes(r.stdout)
        self.assertEqual([c for _l, c in rows], ["SGC163", "SGC131", "SGL040"], r.stdout)
        self.assertEqual([l for l, _c in rows], sorted(l for l, _c in rows))
        self.assertIn("sigil: 1 issue(s)", r.stderr)
        self.assertIn("sigil check (spec, k=2)", r.stderr)

    def test_exit_code_is_the_worse_of_the_two(self):
        # lint alone is clean (exit 0); the checker's warn (two declared writers,
        # no resolution) makes it 1
        writers = ("#!spec\n\n--- T ---\n(User) -> [Api] : go()\n"
                   "[Api] -> |Doc| : put({Doc})\n[Job] -> |Doc| : put({Doc})\n"
                   "|Doc| @write(Api, Job)\n")
        self.assertEqual(run_lint(writers).returncode, 0)
        r = run_lint(writers, "--deep")
        self.assertIn("warn:5:SGC131", r.stdout)
        self.assertEqual(r.returncode, 1, r.stdout)
        broken = "#!spec\n\n--- T ---\n[Broken -> \n"
        self.assertEqual(run_lint(broken, "--deep").returncode, 2)

    def test_acknowledged_findings_listed_last_and_never_counted(self):
        r = run_lint(ACKED, "--deep")
        self.assertEqual(r.stdout.splitlines(), [
            "accepted:4:SGC163: capacity-mismatch: one user",
            "accepted:5:SGC131: shared-writable-store: last write wins"])
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_the_document_mode_sets_the_phrasing(self):
        r = run_lint(MIXED.replace("#!spec", "#!craft"), "--deep")
        self.assertIn("sigil check (craft, k=1)", r.stderr)
        self.assertRegex(r.stdout, r"SGC131: shared-writable-store: .*\?")


    def test_the_dialect_rule_pack_joins_the_check(self):
        pack = ROOT / "tests" / "fixtures" / "dialect_pack_resilience.py"
        doc = ("#!craft\n"
               "[Api] -> (Pay) : op pay.charge(${amt}) @timeout(2s) ×3\n"
               "[Api] -> (Mail) : op mail.send(${to}) @timeout(1s)\n")
        self.assertNotIn("RSL", run_lint(doc, "--deep").stdout)
        r = run_lint(doc, "--deep", "--dialect", str(pack))
        self.assertIn(":RSL105: unbroken-dependency:", r.stdout)
        self.assertIn(":RSL164: shared-pool:", r.stdout)


class DeepLines(unittest.TestCase):
    def test_lint_first_on_a_shared_line(self):
        check = _load("sigil_check_for_deep_tests", "check.py")
        report = check.check(MIXED)
        result = lint.LintResult()
        result.add("warn", 5, "SGL999", "a lint row on the finding's line")
        rows = codes("\n".join(lint.deep_lines(result, report)))
        self.assertEqual(rows, [(4, "SGC163"), (5, "SGL999"), (5, "SGC131")])

    def test_exit_code(self):
        self.assertEqual(lint.exit_code([]), 0)
        self.assertEqual(lint.exit_code(["info", "warn"]), 1)
        self.assertEqual(lint.exit_code(["warn", "error"]), 2)


if __name__ == "__main__":
    unittest.main()
