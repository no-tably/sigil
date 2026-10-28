"""rules.trace: the shape that keeps a check's memory small (patch-0.6.9 M1).

An exploration keeps each run compact: its RunFacts (deliveries and accesses
with their clocks, the few other facts the rules read), not its event list or
log; the clocks are copied only at the events the rules read; no list of every
run's clocks, deliveries or accesses is cached; repeats are found by a digest
of each run's signature. What the rules find does not change.

Run:  python3 -m unittest tests.test_check_memory
"""
from __future__ import annotations

import sys
import unittest
from functools import cached_property
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_FIXTURES = ROOT / "tests" / "fixtures" / "checks"

from sigil.analyse import check as ck  # noqa: E402
from sigil.analyse.rules import trace as ct  # noqa: E402
from sigil.model import sim  # noqa: E402

# A machine fed by two senders (deliveries), a store written from a fan-out
# (accesses), and an entry started while another runs (overlap runs).
FIXTURES = ("trace-205-flagged.sigil", "trace-204-fanout.sigil", "trace-204-overlap.sigil")


def make_doc(name: str):
    text = (_FIXTURES / name).read_text(encoding="utf-8")
    return ck.Doc(text, "spec", 1, frozenset(ck.CORE_NAMES.values()))


def fresh_events(d, run) -> list:
    return sim.simulate(d.sc, run.scenario, limits=d.limits, keep=False).end["events"]


class TestClocksOnlyWhereRead(unittest.TestCase):
    def test_clocks_are_made_only_at_the_events_the_rules_read(self):
        for name in FIXTURES:
            d = make_doc(name)
            for run in ct.trace_facts(ck, d).runs:
                events = run.events
                at = ct.clocks_at(events, ct.reads_clock)
                read = {i for i, e in enumerate(events)
                        if e["task"] is not None and ct.reads_clock(e)}
                self.assertEqual(set(at), read, (name, run.scenario.name))
                full = ct.vector_clocks(events)
                self.assertEqual(at, {i: full[i] for i in read}, (name, run.scenario.name))

    def test_some_events_need_no_clock(self):
        events = ct.trace_facts(ck, make_doc("trace-204-fanout.sigil")).runs[0].events
        self.assertLess(len(ct.clocks_at(events, ct.reads_clock)), len(events))


class TestCompactRuns(unittest.TestCase):
    def test_an_explored_run_keeps_facts_not_events(self):
        for name in FIXTURES:
            d = make_doc(name)
            runs = ct.trace_facts(ck, d).runs
            self.assertTrue(runs)
            for run in runs:
                self.assertNotIn("events", run.end)
                self.assertNotIn("log", run.end)
                self.assertIsInstance(run.facts, ct.RunFacts)
                events = fresh_events(d, run)
                self.assertEqual(run.events, events)            # replayed on demand
                self.assertEqual(run.facts, ct.run_facts(events))

    def test_trace_facts_cache_no_list_over_every_run(self):
        for attr in ("clocks", "deliveries", "accesses"):
            self.assertNotIsInstance(ct.TraceFacts.__dict__.get(attr), cached_property, attr)
        self.assertNotIn("clocks", ct.TraceFacts.__dict__)

    def test_a_hand_made_run_reads_its_facts_from_its_events(self):
        d = make_doc("trace-204-fanout.sigil")
        t = sim.simulate(d.sc, sim.Scenario("happy"), limits=d.limits, keep=False)
        run = ct.Run(t.scenario, t.end, t.outcome)
        self.assertEqual(ct.facts_of_run(run), ct.run_facts(t.end["events"]))
        self.assertEqual(ct.frames_of(run), ct.frames_of(ct.compact_run(run)))


class TestCombinationsKeep(unittest.TestCase):
    def test_record_and_keep_happy(self):
        d = make_doc("trace-205-flagged.sigil")
        plain = sim.combinations(d.sc, 1, limits=d.limits)
        lean = sim.combinations(d.sc, 1, limits=d.limits, keep_happy=False,
                                record=lambda t: (t.scenario.name, len(t.frames)))
        self.assertEqual([n for n, _ in lean.traces], [t.scenario.name for t in plain.traces])
        self.assertEqual([f for _, f in lean.traces], [1] * len(lean.traces))
        self.assertGreater(len(plain.traces[0].frames), 1)
        self.assertEqual((lean.duplicates, lean.left_out), (plain.duplicates, plain.left_out))

    def test_seen_holds_digests(self):
        seen = ct.Seen()
        seen.add(("ok", ("line a", "last b")))
        self.assertIn(("ok", ("line a", "last b")), seen)
        self.assertNotIn(("ok", ("line a", "last bx")), seen)
        self.assertNotIn(("ok", ("line alast b",)), seen)
        self.assertNotIn(("failed", ("line a", "last b")), seen)
        self.assertEqual(len(seen), 1)


if __name__ == "__main__":
    unittest.main()
