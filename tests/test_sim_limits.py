"""The simulator's limits reach every scenario list and every run check makes.

A document whose happy run needs more frames than the default (generated here):
at the default limits the run is cut, so no later entry's episode starts and no
overlap scenario is listed; `--limit frames=N` (view and check alike) lets the
run end, and the overlap scenarios built from it appear in `sigil view --sim
list` and in check's own runs. The choice points (failure scenarios) are read
off the program, so they are listed either way. SGC090's cut hint names the
flag that raises the limit.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigil.analyse import check as ck  # noqa: E402
from sigil.analyse.rules import trace as ct  # noqa: E402
from sigil.core import parse  # noqa: E402
from sigil.model import sim  # noqa: E402

CALLS = 300                    # sequential calls: about 3000 ticks, past frames=2000
RAISED = ("frames=20000",)


def long_document(calls: int = CALLS) -> str:
    """(Alice) makes `calls` sync calls in turn, then writes |Db|, which (Bob)
    reads; one `?>` is the document's failure-side choice point."""
    lines = ["#!spec", "(Alice) -> [Hub]"]
    lines += [f"[Hub] -> [S{i}] : ask({{Q}}) => {{A}}" for i in range(calls)]
    lines += ["[Hub] -> |Db| : write({Row})", "[Hub] ?> [Audit]", "(Bob) -> |Db| : read({Row})"]
    return "\n".join(lines) + "\n"


TEXT = long_document()


def canon(text: str = TEXT):
    return sim.canonical(parse.parse_document(text))


def names(scenarios) -> list:
    return [s.name for s in scenarios]


def overlap_names(found: list) -> list:
    return [n for n in found if n.startswith("Bob@")]


def raised() -> sim.Limits:
    return sim.limits_from(RAISED)


def sigil(*args) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "SIGIL_DIALECT"}
    return subprocess.run([sys.executable, str(ROOT / "bin" / "sigil"), *args],
                          capture_output=True, text=True, env=env)


class TheDocument(unittest.TestCase):
    def test_its_happy_run_needs_more_than_the_default_frames(self):
        sc = canon()
        happy = sim.scenario(sc, "happy")
        self.assertEqual(sim.simulate(sc, happy, keep=False).outcome, "cut")
        self.assertEqual(sim.simulate(sc, happy, limits=raised(), keep=False).outcome, "ok")


class ScenarioList(unittest.TestCase):
    """sim.scenarios(…, limits=) — what view --sim list / all and check list."""

    def test_the_default_limits_list_no_overlap(self):
        found = names(sim.scenarios(canon()))
        self.assertEqual(overlap_names(found), [])
        self.assertIn("Hub?>Audit", found)

    def test_raised_limits_list_the_overlaps_their_run_reaches(self):
        found = names(sim.scenarios(canon(), limits=raised()))
        self.assertTrue(overlap_names(found), found)
        self.assertIn("Hub?>Audit", found)

    def test_the_choice_points_do_not_depend_on_the_run(self):
        prog = sim._program_of(canon().graph)
        self.assertEqual(sim.deviations(prog), sim.deviations(prog, raised()))


class ViewCli(unittest.TestCase):
    def setUp(self):
        fd, name = tempfile.mkstemp(suffix=".sigil")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(TEXT)
        self.path = name
        self.addCleanup(os.unlink, name)

    def listed(self, *args) -> list:
        p = sigil("view", self.path, "--sim", "list", *args)
        self.assertEqual(p.returncode, 0, p.stderr)
        return [ln.split()[0] for ln in p.stdout.splitlines() if ln.strip()]

    def test_sim_list_follows_limit(self):
        self.assertEqual(overlap_names(self.listed()), [])
        listed = self.listed("--limit", RAISED[0])
        self.assertTrue(overlap_names(listed), listed)
        self.assertIn("Hub?>Audit", listed)

    def test_check_limit_reaches_its_runs(self):
        cut = sigil("check", self.path, "--all", "--overlaps", "listed")
        self.assertIn("cut a run at its frames limit", cut.stdout)
        self.assertIn("--limit frames=N", cut.stdout)
        full = sigil("check", self.path, "--all", "--overlaps", "listed", "--limit", RAISED[0])
        self.assertNotIn("SGC090", full.stdout)


class CheckRuns(unittest.TestCase):
    """check's own scenario set: the exploration under the document's limits."""

    def explored(self, limits) -> list:
        ex = ct.explore(sim, canon(), 1, ct.BUDGET, limits, overlaps="listed")
        return names(r.scenario for r in ex.runs)

    def test_raised_limits_add_the_overlap_runs(self):
        self.assertEqual(overlap_names(self.explored(sim.Limits())), [])
        self.assertTrue(overlap_names(self.explored(raised())))

    def test_the_check_reports_the_limits_it_ran_under(self):
        rep = ck.check(TEXT, limits=raised(), overlaps="listed")
        self.assertEqual(rep.limits["frames"], 20000)
        self.assertEqual([f for f in rep.findings if f.rule.id == "SGC090"], [])


class CutHint(unittest.TestCase):
    def test_the_hint_names_the_flag(self):
        self.assertEqual(ct.limit_fix("frames"), "run with a larger frames limit "
                                                 "(--limit frames=N)")
        rep = ck.check(TEXT, overlaps="off")
        (f,) = [f for f in rep.findings if f.rule.id == "SGC090"]
        self.assertIn("--limit frames=N", f.fix)


if __name__ == "__main__":
    unittest.main()
