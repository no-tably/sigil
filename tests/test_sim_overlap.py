"""
Tests for sim.py's overlap scenarios: `Entry@t` names, the listed overlap
family scenarios() adds after the failure scenarios, and the windows and
every-tick runs a checker tries.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


sys.path.insert(0, str(ROOT / "tools"))
from sigil.model import sim  # noqa: E402
from sigil.model.sim.engine import _Entry, _due  # noqa: E402
from sigil.model.sim.narration import _prefixed, _subject_episodes  # noqa: E402
from sigil.model.sim.program import _program_of  # noqa: E402
from sigil.model.sim.scenarios import _spread  # noqa: E402
from sigil.model import scene  # noqa: E402
from sigil.core import parse as render  # noqa: E402
import golden  # noqa: E402

EXAMPLES = sorted((ROOT / "site" / "examples").glob("*.sigil"))
FIXTURES = [ROOT / "tests" / "fixtures" / "executions.sigil",
            ROOT / "tests" / "fixtures" / "coverage.sigil"]


def build(text: str):
    return scene.build_scene(render.parse_document(text))


def at(tick: int) -> str:
    """A tick as labels write it."""
    return f"t{tick}"


def accesses(trace) -> list:
    return [(e["t"], e["episode"], e["mode"]) for e in trace.end["events"]
            if e["kind"] == "access"]


# [A] writes |Db| through [S]; [B] reads it directly: B reaches |Db| 4 ticks
# after it starts, A writes it at tick 9.
SHARED = "[A] -> [S] : a()\n[S] -> |Db| : w()\n[S] -> [T] : t()\n[B] -> |Db| : read()\n"
TWO = "[A] -> [S] : a()\n[S] -> [X] : x()\n[S] !> <Failed>\n[B] -> [U] : u()\n"


class TestStartNames(unittest.TestCase):
    def setUp(self):
        self.sc = build(TWO)

    def test_an_entry_at_a_tick_is_a_start(self):
        s = sim.scenario(self.sc, "B@2")
        self.assertEqual((s.name, s.choices, s.starts), ("B@2", (), (("B_service", 2),)))
        self.assertEqual(s.label, f"[B] starts at {at(2)}")
        plain = sim.Scenario("x", starts=(("B_service", 2),))
        self.assertEqual(sim.simulate(self.sc, s).frames, sim.simulate(self.sc, plain).frames)

    def test_any_tick_is_accepted_listed_or_not(self):
        s = sim.scenario(self.sc, "B@400")
        self.assertEqual(sim.simulate(self.sc, s).end["episodes"][1]["start"], 400)

    def test_combines_with_a_deviation(self):
        s = sim.scenario(self.sc, "S:fails+B@1")
        self.assertEqual(s.choices, (((("node", "S_service")), "fails"),))
        self.assertEqual(s.starts, (("B_service", 1),))
        self.assertIn(f"[B] starts at {at(1)}", s.label)
        tr = sim.simulate(self.sc, s)
        self.assertEqual(tr.outcome, "failed")
        self.assertEqual(tr.end["episodes"][1]["start"], 1)

    def test_a_later_start_of_one_entry_wins(self):
        self.assertEqual(sim.scenario(self.sc, "B@3+B@2").starts, (("B_service", 2),))

    def test_two_entries_given_starts(self):
        s = sim.scenario(self.sc, "B@0+A@5")
        tr = sim.simulate(self.sc, s)
        self.assertEqual([(e["entry"], e["start"]) for e in tr.end["episodes"]],
                         [("B_service", 0), ("A_service", 5)])

    def test_unknown_names_are_refused(self):
        for bad in ("Nope@3", "B@x", "B@-1", "B@", "S@2", "B@1+nope"):
            with self.subTest(name=bad), self.assertRaises(KeyError) as cm:
                sim.scenario(self.sc, bad)
            self.assertIn("Entry@tick", str(cm.exception))

    def test_entries_due_at_one_tick_begin_in_written_order(self):
        tr = sim.simulate(self.sc, sim.scenario(self.sc, "B@0"))
        self.assertEqual([(e["episode"], e["entry"]) for e in tr.end["episodes"]],
                         [(1, "A_service"), (2, "B_service")])

    def test_the_first_entry_at_its_own_opening_tick_runs_as_happy(self):
        tr = sim.simulate(self.sc, sim.scenario(self.sc, "A@0"))
        happy = sim.simulate(self.sc, sim.scenarios(self.sc)[0])
        self.assertEqual(tr.frames, happy.frames)
        self.assertEqual(tr.end["episodes"], happy.end["episodes"])

    def test_an_entry_without_a_start_follows_one_begun_at_the_opening(self):
        tr = sim.simulate(self.sc, sim.scenario(self.sc, "A@0"))
        a, b = tr.end["episodes"]
        self.assertEqual((a["entry"], a["start"]), ("A_service", 0))
        self.assertGreater(b["start"], 0)

    def test_an_entry_without_a_start_opens_the_run_when_none_is_due(self):
        tr = sim.simulate(self.sc, sim.scenario(self.sc, "A@3"))
        self.assertEqual([(e["entry"], e["start"]) for e in tr.end["episodes"]],
                         [("B_service", 0), ("A_service", 3)])

    def test_due_at_the_opening(self):
        E = _Entry
        entries = [E(0, "a", 0), E(0, "b", None), E(0, "c", 5)]
        self.assertEqual(_due(entries, 0, True, opening=True), [0])
        self.assertEqual(_due(entries[1:], 0, True, opening=True), [0])
        self.assertEqual(_due([E(0, "b", None), E(0, "a", 0)], 0, True, opening=True),
                         [0, 1])
        self.assertEqual(_due(entries, 0, True, opening=False), [0, 1])
        self.assertEqual(_due(entries[1:], 5, True, opening=True), [0, 1])

    def test_the_overlap_example_entry_at_zero_runs_as_happy(self):
        sc = build((ROOT / "tests" / "fixtures" / "overlap.sigil").read_text())
        happy = sim.simulate(sc, sim.scenarios(sc)[0])
        tr = sim.simulate(sc, sim.scenario(sc, "Operator@0"))
        self.assertEqual(tr.frames, happy.frames)
        self.assertEqual([e["start"] for e in tr.end["episodes"]],
                         [e["start"] for e in happy.end["episodes"]])


class TestListedOverlaps(unittest.TestCase):
    def test_after_the_failure_scenarios(self):
        sc = build(SHARED + "[S] -> [V] : v() ×2\n")
        listed = sim.scenarios(sc)
        plain = [s for s in listed if not s.starts]
        self.assertEqual(listed[:len(plain)], plain)
        self.assertEqual([s.name for s in listed[len(plain):]], ["B@5"])

    def test_the_later_entry_reaches_the_store_as_the_earlier_writes_it(self):
        sc = build(SHARED)
        (s,) = sim.overlaps(sc)
        self.assertEqual((s.name, s.starts), ("B@5", (("B_service", 5),)))
        self.assertEqual(s.label, f"[B] starts at {at(5)}, reaching |Db| as [A] writes it")
        self.assertEqual(accesses(sim.simulate(sc, s)), [(9, 1, "write"), (9, 2, "read")])
        self.assertEqual(sim.scenario(sc, "B@5"), s)          # by name: the same one

    def test_a_start_before_the_earlier_episode_is_its_start(self):
        sc = build("[A] -> |Db| : w()\n[A] -> [S] : a()\n[B] -> [C] : c()\n[C] -> |Db| : r()\n")
        (s,) = sim.overlaps(sc)
        self.assertEqual(s.name, "B@0")
        self.assertEqual(s.label, f"[B] starts at {at(0)} with [A], reaching |Db| after it does")

    def test_the_example_labels_each_listed_overlap_on_its_name_line(self):
        """`--sim list` keeps a label beside its name when it fits the list's
        width: the example's overlap labels are short enough, and none is empty."""
        from sigil.present import app as view
        sc = build((ROOT / "tests" / "fixtures" / "overlap.sigil").read_text(encoding="utf-8"))
        listed = sim.scenarios(sc)
        self.assertTrue(all(s.label for s in listed if s.starts))
        self.assertEqual(len(view.sim_list(listed)), len(listed))

    def test_a_machine_the_earlier_entry_moves(self):
        sc = build("[A] -> [W] : w()\n[W] ~> <Go>\n[B] ~> <Go>\n"
                   "state {X} {\n  + -<Go>-> Open\n  Open -<Go>-> Done\n}\n")
        (s,) = sim.overlaps(sc)
        self.assertEqual(s.label, f"[B] starts at {at(5)}, reaching {{X}} as [A] changes its state")
        moves = [(e["t"], e["episode"]) for e in sim.simulate(sc, s).end["events"]
                 if e["kind"] == "transition"]
        self.assertEqual(moves, [(14, 1), (14, 2)])

    def test_one_entry_lists_none(self):
        sc = build("[A] -> |Db| : w()\n")
        self.assertEqual(sim.overlaps(sc), [])
        self.assertEqual(sim.overlap_windows(sc), [])
        self.assertEqual(sim.overlap_runs(sc), [])

    def test_nothing_shared_lists_none(self):
        self.assertEqual(sim.overlaps(build("[A] -> [S] : a()\n[B] -> [U] : u()\n")), [])

    def test_a_decision_entry_takes_no_part(self):
        sc = build("(U) -> [Api] : req({Request})\nbranch on {Request}.kind {\n"
                   "  read  => [Api] -> |Cache|\n  write => [Api] -> |DB|\n}\n")
        self.assertEqual([s.name for s in sim.scenarios(sc)], ["happy", "Request.kind=write"])

    def test_the_caps_are_limits(self):
        sc = build("[A] -> [Z] : z()\n[A] -> |Db| : w()\n[A] -> |Log| : l()\n[A] -> |Q| : q()\n"
                   "[B] -> |Q| : r()\n[B] -> |Log| : r()\n[B] -> |Db| : r()\n"
                   "[C] -> |Db| : r()\n")
        full = sim.overlaps(sc)
        self.assertLessEqual(len(full), sim.Limits().overlaps)
        pair = [s for s in full if s.name.startswith("B@")]
        self.assertEqual(len(pair), 3)
        one = sim.overlaps(sc, limits=sim.Limits(pair_overlaps=1))
        self.assertEqual(sum(s.name.startswith("B@") for s in one), 1)
        self.assertEqual(len(sim.overlaps(sc, limits=sim.Limits(overlaps=2))), 2)
        self.assertEqual(len(sim.scenarios(sc, limits=sim.Limits(scenarios=2))), 2)

    def test_listing_twice_gives_equal_lists(self):
        sc = build(SHARED)
        a = sim.overlaps(sc)
        a.clear()
        self.assertEqual(len(sim.overlaps(sc)), 1)

    def test_the_corpus(self):
        """Every listed overlap runs with two episodes at once, and the scenarios
        before them are the deviations, as before."""
        for path in EXAMPLES + FIXTURES:
            sc = build(path.read_text())
            prog = _program_of(sc.graph)
            with self.subTest(doc=path.name):
                listed = sim.scenarios(sc, limits=sim.Limits(scenarios=10 ** 6))
                plain = [s.name for s in listed if not s.starts]
                self.assertEqual(plain, ["happy"] + [d.name for d in sim.deviations(prog)])
                for s in listed[len(plain):]:
                    tr = sim.simulate(sc, s)
                    self.assertTrue(any(len(f.episodes) > 1 for f in tr.frames), s.name)
                    self.assertEqual(sim.scenario(sc, s.name).starts, s.starts)

    def test_every_listed_overlap_changes_the_trace_over_the_corpus(self):
        """The overlap side of the deviation test in test_sim: over every golden
        input and language.md block, a listed `B@t` starts no choice and runs
        differently from the happy run (B begins before the earlier one is quiet)."""
        spec = golden.examples_inputs((ROOT / "language.md").read_text(encoding="utf-8"))
        corpus = ([(i.name, i.text) for i in golden.collect_inputs(ROOT)]
                  + [("language-" + i.name, i.text) for i in spec])
        for name, text in corpus:
            sc = build(text)
            listed = sim.scenarios(sc, limits=sim.Limits(scenarios=10 ** 6))
            happy = sim.simulate(sc, listed[0]).end["log"]
            for s in (s for s in listed if s.starts):
                with self.subTest(doc=name, scenario=s.name):
                    self.assertEqual(s.choices, ())
                    self.assertNotEqual(sim.simulate(sc, s).end["log"], happy)


class TestWindows(unittest.TestCase):
    def test_a_window_is_the_earlier_episode_busy(self):
        sc = build(SHARED)
        (w,) = sim.overlap_windows(sc)
        self.assertEqual(w, sim.OverlapWindow("A_service", "B_service", 0, 15))
        happy = sim.simulate(sc, sim.scenario(sc, "happy"))
        self.assertEqual(happy.end["episodes"][1]["start"], 16)   # the tick after quiet

    def test_every_tick_of_the_window(self):
        sc = build(SHARED)
        runs = sim.overlap_runs(sc)
        self.assertEqual([s.name for s in runs], [f"B@{t}" for t in range(16)])
        self.assertEqual(runs[3].starts, (("B_service", 3),))
        self.assertEqual(runs[3].label,
                         f"[B] starts at {at(3)}, during [A]'s episode ({at(0)}–{at(15)})")
        self.assertIn("B@5", {s.name for s in runs})            # the listed one among them

    def test_the_window_cap_spreads_the_ticks(self):
        runs = sim.overlap_runs(build(SHARED), limits=sim.Limits(window=4))
        self.assertEqual([s.name for s in runs], ["B@0", "B@5", "B@10", "B@15"])

    def test_three_entries_one_start_listed_once(self):
        sc = build("[A] -> [S] : a()\n[B] -> [S] : b()\n[C] -> [S] : c()\n")
        windows = sim.overlap_windows(sc)
        self.assertEqual([(w.first, w.later) for w in windows],
                         [("A_service", "B_service"), ("A_service", "C_service"),
                          ("B_service", "C_service")])
        names = [s.name for s in sim.overlap_runs(sc)]
        self.assertEqual(len(names), len(set(names)))

    def test_spread(self):
        self.assertEqual(_spread(0, 3, 10), [0, 1, 2, 3])
        self.assertEqual(_spread(0, 9, 3), [0, 4, 9])
        self.assertEqual(_spread(5, 9, 1), [5])


class TestNarration(unittest.TestCase):
    """While episodes overlap each sentence is led by its episode."""

    def beats(self, text: str, name: str) -> list:
        sc = build(text)
        return [b.text for b in sim.narrate(sim.simulate(sc, sim.scenario(sc, name)))]

    def test_overlapping_sentences_name_their_episode(self):
        beats = self.beats(SHARED, "B@2")
        self.assertEqual(beats[1], "ep2: episode 2 begins at [B]; ep2: [B] calls |Db| with read()")
        self.assertEqual(beats[2], "ep1: [S] calls |Db| with w()")

    def test_one_episode_at_a_time_says_no_episode(self):
        for text in self.beats(SHARED, "happy") + self.beats(SHARED, "B@2")[3:]:
            self.assertNotIn("ep1:", text)
            self.assertNotIn("ep2:", text)

    def test_episodes_begun_at_one_tick_are_each_said(self):
        first = self.beats(SHARED, "B@0")[0]
        self.assertTrue(first.startswith("ep1: episode 1 begins at [A]; "
                                         "ep2: episode 2 begins at [B]; "), first)

    def test_the_corpus_without_starts_is_never_prefixed(self):
        for path in EXAMPLES + FIXTURES:
            sc = build(path.read_text())
            for s in sim.scenarios(sc):
                if s.starts:
                    continue
                with self.subTest(path=path.name, scenario=s.name):
                    beats = sim.narrate(sim.simulate(sc, s))
                    self.assertFalse([b for b in beats if re.search(r"\bep\d+: ", b.text)])

    def test_a_subject_belongs_to_the_episode_that_acted_on_it_last(self):
        events = [{"task": 1, "episode": 1, "node": "S"},
                  {"task": 2, "episode": 2, "store": "Db", "node": "S"},
                  {"task": None, "episode": 2, "node": "T"}]
        self.assertEqual(_subject_episodes(events, {"T": 1}),
                         {"S": 2, "Db": 2, "T": 1})

    def test_prefixed(self):
        pairs = [(1, "a"), (None, "the run ends: ok"), (2, "b")]
        self.assertEqual(_prefixed(pairs, False), ["a", "the run ends: ok", "b"])
        self.assertEqual(_prefixed(pairs, True), ["ep1: a", "the run ends: ok", "ep2: b"])


if __name__ == "__main__":
    unittest.main()
