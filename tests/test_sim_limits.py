"""The simulator's limits reach every scenario list and every run check makes.

A document whose happy run needs more frames than 2000 (generated here): the
default frames and activations limits grow with the document's size
(sim.scaled), so at default limits the run ends and the overlap scenarios built
from it are listed; a given `--limit frames=N` (view and check alike) is used as
given, so a lower one cuts the run, no later entry's episode starts and no
overlap scenario is listed. The choice points (failure scenarios) are read off
the program, so they are listed either way. SGC090's cut hint names the flag
that raises the limit. A small document keeps the 2000 / 500 floors.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import json
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
LOWERED = ("frames=1000",)     # given: used as given, so the run is cut


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


def lowered() -> sim.Limits:
    return sim.limits_from(LOWERED)


def sigil(*args) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "SIGIL_DIALECT"}
    return subprocess.run([sys.executable, str(ROOT / "bin" / "sigil"), *args],
                          capture_output=True, text=True, env=env)


class TheDocument(unittest.TestCase):
    def test_its_happy_run_needs_more_than_the_floor(self):
        sc = canon()
        happy = sim.scenario(sc, "happy")
        tr = sim.simulate(sc, happy, keep=False)
        self.assertEqual(tr.outcome, "ok")
        self.assertGreater(tr.frames[-1].tick + 1, 2000)
        self.assertEqual(sim.simulate(sc, happy, limits=lowered(), keep=False).outcome, "cut")
        self.assertEqual(sim.simulate(sc, happy, limits=raised(), keep=False).outcome, "ok")


class ScenarioList(unittest.TestCase):
    """sim.scenarios(…, limits=) — what view --sim list / all and check list."""

    def test_a_lowered_limit_lists_no_overlap(self):
        found = names(sim.scenarios(canon(), limits=lowered()))
        self.assertEqual(overlap_names(found), [])
        self.assertIn("Hub?>Audit", found)

    def test_the_default_limits_list_the_overlaps(self):
        found = names(sim.scenarios(canon()))
        self.assertTrue(overlap_names(found), found)

    def test_raised_limits_list_the_overlaps_their_run_reaches(self):
        found = names(sim.scenarios(canon(), limits=raised()))
        self.assertTrue(overlap_names(found), found)
        self.assertIn("Hub?>Audit", found)

    def test_the_choice_points_do_not_depend_on_the_run(self):
        prog = sim._program_of(canon().graph)
        self.assertEqual(sim.deviations(prog), sim.deviations(prog, raised()))
        self.assertEqual(sim.deviations(prog), sim.deviations(prog, lowered()))


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
        self.assertEqual(overlap_names(self.listed("--limit", LOWERED[0])), [])
        for given in ((), ("--limit", RAISED[0])):
            listed = self.listed(*given)
            self.assertTrue(overlap_names(listed), listed)
            self.assertIn("Hub?>Audit", listed)

    def test_check_limit_reaches_its_runs(self):
        cut = sigil("check", self.path, "--all", "--overlaps", "listed", "--limit", LOWERED[0])
        self.assertIn("cut a run at its frames limit", cut.stdout)
        self.assertIn("--limit frames=N", cut.stdout)
        for given in ((), ("--limit", RAISED[0])):
            full = sigil("check", self.path, "--all", "--overlaps", "listed", *given)
            self.assertNotIn("SGC090", full.stdout)


class CheckRuns(unittest.TestCase):
    """check's own scenario set: the exploration under the document's limits."""

    def explored(self, limits) -> list:
        ex = ct.explore(sim, canon(), 1, ct.BUDGET, limits, overlaps="listed")
        return names(r.scenario for r in ex.runs)

    def test_limits_that_let_the_run_end_add_the_overlap_runs(self):
        self.assertEqual(overlap_names(self.explored(lowered())), [])
        self.assertTrue(overlap_names(self.explored(sim.Limits())))
        self.assertTrue(overlap_names(self.explored(raised())))

    def test_the_check_reports_the_limits_it_ran_under(self):
        rep = ck.check(TEXT, limits=raised(), overlaps="listed")
        self.assertEqual(rep.limits["frames"], 20000)
        self.assertEqual([f for f in rep.findings if f.rule.id == "SGC090"], [])


class CutHint(unittest.TestCase):
    def test_the_hint_names_the_flag(self):
        self.assertEqual(ct.limit_fix("frames"), "run with a larger frames limit "
                                                 "(`#% frames=N` in the document, "
                                                 "or --limit frames=N)")
        rep = ck.check(TEXT, overlaps="off", limits=lowered())
        (f,) = [f for f in rep.findings if f.rule.id == "SGC090"]
        self.assertIn("--limit frames=N", f.fix)
        self.assertIn("`#% frames=N` in the document", f.fix)


class Scaled(unittest.TestCase):
    """sim.scaled: the default frames / activations grow with the document."""

    def small(self):
        return canon("(U) -> [A] : go({X}) => {Y}\n[A] -> [B]\n")

    def test_size_counts_nodes_and_edges_of_every_unit(self):
        prog = sim._program_of(canon("(U) -> [A]\n[A] := {\n  [P] -> [Q]\n}\n").graph)
        self.assertEqual(sim.doc_size(prog), sum(len(u.graph.nodes) + len(u.graph.edges)
                                                 for u in prog.units))
        self.assertGreater(len(prog.units), 1)

    def test_defaults_grow_with_the_document(self):
        sc = canon()
        size = sim.doc_size(sim._program_of(sc.graph))
        got = sim.sized(sim.Limits(), sc)
        self.assertEqual((got.frames, got.activations),
                         (sim.PER_SIZE["frames"] * size, sim.PER_SIZE["activations"] * size))
        self.assertIs(type(got.frames), int)

    def test_a_small_document_keeps_the_floors(self):
        got = sim.sized(sim.Limits(), self.small())
        self.assertEqual((got.frames, got.activations), (2000, 500))
        self.assertIs(type(got.frames), int)

    def test_a_given_limit_is_used_as_given(self):
        sc = canon()
        self.assertEqual(sim.sized(lowered(), sc).frames, 1000)
        got = sim.sized(sim.Limits(frames=10, activations=7), sc)
        self.assertEqual((got.frames, got.activations), (10, 7))
        given = sim.limits_from(["frames=2000"])
        self.assertEqual(sim.sized(given, sc).frames, 2000)

    def test_a_floor_reads_as_its_value_but_is_not_a_given_one(self):
        default = sim.Limits()
        self.assertEqual((str(default.frames), f"{default.activations}"), ("2000", "500"))
        self.assertEqual(json.loads(json.dumps(default._asdict()))["frames"], 2000)
        self.assertNotEqual(default, sim.Limits(frames=2000, activations=500))
        self.assertEqual(default, sim.Limits())
        self.assertEqual(hash(default), hash(sim.Limits()))

    def test_the_run_is_deterministic(self):
        sc = canon()
        a = sim.simulate(sc, sim.scenario(sc, "happy"), keep=False)
        b = sim.simulate(sc, sim.scenario(sc, "happy"), keep=False)
        self.assertEqual((a.outcome, a.frames[-1].tick, a.end["log"]),
                         (b.outcome, b.frames[-1].tick, b.end["log"]))


class PerEpisode(unittest.TestCase):
    """The frames limit counts from the latest episode's start: a cut says which
    episode ran how many frames from which tick, and the run's length is that
    start plus the limit (the number SGC090's `frames=N` names)."""

    TEXT = "(Bob) -> |Db| : read({Row})\n" + "\n".join(long_document(40).splitlines()[1:]) + "\n"

    def test_a_cut_names_its_episode_and_count(self):
        sc = canon(self.TEXT)
        tr = sim.simulate(sc, sim.scenario(sc, "happy"), limits=sim.Limits(frames=100))
        self.assertEqual(tr.outcome, "cut")
        (ev,) = [e for e in tr.end["events"] if e["kind"] == "limit"]
        (_first, second) = tr.end["episodes"]
        self.assertEqual((ev["name"], ev["episode"], ev["frames"], ev["start"]),
                         ("frames", 2, 100, second["start"]))
        self.assertGreater(ev["start"], 0)
        self.assertEqual(tr.frames[-1].tick + 1, ev["start"] + ev["frames"])
        self.assertTrue([ln for ln in tr.end["log"]
                         if f"100 frames of episode 2, from t{ev['start']}" in ln])
        told = " ".join(b.text for b in sim.narrate(tr))
        self.assertIn(f"episode 2 reached the frames limit, 100 frames from "
                      f"t{ev['start']}", told)


class MetaModel(unittest.TestCase):
    """design/sigil.sigil, the toolchain modelled in sigil: its happy run (two
    episodes, the longer about 80 frames per unit of size) ends at default limits."""

    def test_its_happy_run_ends_at_default_limits(self):
        sc = sim.canonical(parse.parse_document(
            (ROOT / "design" / "sigil.sigil").read_text(encoding="utf-8")))
        tr = sim.simulate(sc, sim.scenario(sc, "happy"), keep=False)
        self.assertEqual(tr.outcome, "ok")


if __name__ == "__main__":
    unittest.main()
