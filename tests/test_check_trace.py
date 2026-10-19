"""check_trace.py (RFC 0003, P3 behavioural layer): the rules over the
simulator's runs and the trace halves it adds to other modules' rules.

Covers:
  1. every trace fixture gives its `# expect:` findings (tests/fixtures/checks/
     trace-*.sigil, checked with the default registry plus this module's
     extensions);
  2. the regression probes of the simulator fixes in FIXED (one per fix), and
     the trace caps they lift;
  3. happens-before: vector clocks over fork, await/resume and gate events;
  4. SGC203 event-ignored and SGC205 ordering-unstated (diamond check,
     per-sender FIFO, drops in `+`, folding under SGC146);
  5. SGC204 race, trace half (intra-episode, concurrent ownership, Q10);
  6. SGC206 stalled-join; 7. SGC175 unreached; 8. SGC090's run causes;
  9. witnesses for SGC151/152/201/202, extend_rules, determinism and cost.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_FIXTURES = ROOT / "tests" / "fixtures" / "checks"


from sigil.analyse import check as ck  # noqa: E402
from sigil import cli  # noqa: E402
from sigil.analyse.rules import state as cs  # noqa: E402
from sigil.analyse.rules import trace as ct  # noqa: E402
from sigil.model import sim  # noqa: E402

# The default registry with this module's extensions applied (extend_rules is
# idempotent, so this holds whether or not check.py applies it too).
REGISTRY = ck.build_registry(ct.extend_rules(ck, ck.core_rules() + ck.module_rules(ck)))
MINE = re.compile(r"SGC(2\d\d|175|090)$")


def doc(text: str) -> str:
    return textwrap.dedent(text).lstrip("\n")


def check(text: str, mode=None, k=None, registry=None):
    return ck.check(doc(text), mode=mode, k=k, registry=registry or REGISTRY)


def finding_keys(report, ids=MINE) -> list:
    """severity:line:id for every finding the report shows, of the given ids."""
    return [f"{f.severity}:{f.line}:{f.rule.id}" for f in report.shown if ids.match(f.rule.id)]


def of(report, rule_id: str) -> list:
    return [f for f in report.findings if f.rule.id == rule_id]


def expected_of(text: str) -> list:
    """The `# expect:` lines of a fixture's header ((none) for none)."""
    return [m.group(1) for m in re.finditer(r"(?m)^#\s*expect:\s*(.+?)\s*$", text)
            if m.group(1) != "(none)"]


def fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


def make_doc(text: str, mode: str = "spec", k: int = 1):
    return ck.Doc(doc(text), mode, k, frozenset(ck.CORE_NAMES.values()))


def runs_of(text: str, k: int = 1) -> list:
    return list(ct.trace_facts(ck, make_doc(text, k=k)).runs)


def by_name(runs, name: str):
    return next(r for r in runs if r.scenario.name == name)


def events(run, kind: str) -> list:
    return [e for e in run.events if e["kind"] == kind]


# ---------------------------------------------------------------------------
# 1. Fixtures
# ---------------------------------------------------------------------------

class Fixtures(unittest.TestCase):
    def test_every_trace_fixture_gives_its_expected_findings(self):
        paths = sorted(_FIXTURES.glob("trace-*.sigil"))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(fixture=path.name):
                text = path.read_text(encoding="utf-8")
                rep = ck.check(text, registry=REGISTRY)
                self.assertEqual(finding_keys(rep), expected_of(text))


# ---------------------------------------------------------------------------
# 2. Regression probes and trace caps
# ---------------------------------------------------------------------------

def probe_b1(case):
    runs = runs_of(fixture("trace-fix-b1.sigil"))
    deviated = [r for r in runs if r.k == 1]
    case.assertTrue(deviated)
    for r in deviated:
        case.assertEqual([e["guard"][0] for e in events(r, "route")], ["call"], r.scenario.name)


def probe_b2(case):
    runs = runs_of(fixture("trace-fix-b2.sigil"))
    case.assertEqual([r.scenario.name for r in runs],
                     ["happy", "Api.reserve:fails", "Api.score:fails"])
    for r in runs[1:]:
        case.assertEqual(len(events(r, "route")), 1, r.scenario.name)


def probe_b3(case):
    run = by_name(runs_of(fixture("trace-fix-b3.sigil")), "A.send:fails")
    case.assertEqual(run.outcome, "ok")
    case.assertNotIn("C_service", run.end["visited"])
    case.assertEqual([e["how"] for e in events(run, "stop")], ["unawaited"])


def probe_b4(case):
    run = by_name(runs_of(fixture("trace-fix-b4.sigil")), "Request.kind=write")
    case.assertEqual([e["store"] for e in events(run, "access")], ["DB_store"])


def probe_b13(case):
    run = by_name(runs_of(fixture("trace-fix-b13.sigil")), "S.f:fails")
    case.assertEqual(run.outcome, "ok")
    case.assertEqual([e["how"] for e in events(run, "stop")], ["unawaited"])


def probe_ng6(case):
    (run,) = runs_of(fixture("trace-fix-ng6.sigil"))
    case.assertEqual(run.end["machines"], {"X_data": "X_state_Done"})


def probe_q3(case):
    (run,) = runs_of(fixture("trace-206-probe.sigil"))
    case.assertEqual((run.end["stalled"], run.end["deposits"]), ([], []))
    case.assertEqual(len(events(run, "gate-fire")), 1)


PROBES = {"B1": probe_b1, "B2": probe_b2, "B3": probe_b3, "B4": probe_b4,
          "B13": probe_b13, "NG6": probe_ng6, "Q3": probe_q3}


class RegressionProbes(unittest.TestCase):
    def test_every_fix_in_fixed_has_a_passing_probe(self):
        self.assertEqual(set(ct.FIXED), set(PROBES))
        for fix, probe in sorted(PROBES.items()):
            with self.subTest(fix=fix):
                probe(self)

    def test_the_caps_are_lifted_for_every_rule(self):
        for rule_id in ct.NEEDS:
            self.assertFalse(ct.warn_only(rule_id), rule_id)

    def test_a_missing_fix_keeps_the_cap(self):
        self.assertTrue(ct.warn_only("SGC206", fixed=ct.FIXED - {"Q3"}))
        self.assertFalse(ct.warn_only("SGC175", fixed=frozenset()))

    def test_extended_rules_carry_the_lifted_cap(self):
        for rule_id in ("SGC203", "SGC204", "SGC205", "SGC206"):
            self.assertFalse(REGISTRY[rule_id].trace_warn_only, rule_id)


# ---------------------------------------------------------------------------
# 3. Happens-before
# ---------------------------------------------------------------------------

def fork(task, parent=None, why="async", episode=1, wire=None, node=None):
    return {"kind": "fork", "task": task, "parent": parent, "why": why, "episode": episode,
            "wire": wire, "node": node, "t": 0}


def ev(kind, task, **fields):
    return {"kind": kind, "task": task, "episode": 1, "t": 0, **fields}


class HappensBefore(unittest.TestCase):
    def test_siblings_are_concurrent_and_follow_their_parent(self):
        evs = [fork(1, why="entry"), ev("access", 1), fork(2, 1), fork(3, 1),
               ev("access", 2), ev("access", 3)]
        c = ct.vector_clocks(evs)
        self.assertTrue(ct.concurrent(c[4], c[5]))
        self.assertTrue(ct.leq(c[1], c[4]) and ct.leq(c[1], c[5]))

    def test_a_resume_follows_every_member_end(self):
        evs = [fork(1, why="entry"), fork(2, 1, "fan"), fork(3, 1, "fan"),
               ev("await", 1, members=[2, 3], need=[2, 3]), ev("access", 2),
               ev("end", 2), ev("end", 3), ev("resume", 1, failed=False), ev("access", 1)]
        c = ct.vector_clocks(evs)
        self.assertTrue(ct.leq(c[4], c[8]))

    def test_a_gate_fire_follows_every_arrival(self):
        key = (0, 0, "C")
        evs = [fork(1, why="entry"), ev("access", 1), ev("gate-arrive", 1, key=key, round=0),
               fork(2, why="entry", episode=2), ev("gate-arrive", 2, key=key, round=0),
               ev("gate-fire", 2, key=key, round=0), ev("access", 2)]
        c = ct.vector_clocks(evs)
        self.assertTrue(ct.leq(c[1], c[6]))

    def test_episodes_are_independent_roots(self):
        evs = [fork(1, why="entry"), ev("access", 1), fork(2, why="entry", episode=2),
               ev("access", 2)]
        c = ct.vector_clocks(evs)
        self.assertTrue(ct.concurrent(c[1], c[3]))

    def test_run_events_have_no_clock(self):
        self.assertEqual(ct.vector_clocks([{"kind": "quiet", "task": None}]), [None])

    def test_a_send_into_an_event_is_its_parents(self):
        forks = {2: (1, fork(2, 1, wire=("S", "E_event", "~>", 0)))}
        self.assertEqual(ct.sender_of(2, "E_event", forks, 5), (1, 1))
        self.assertEqual(ct.sender_of(2, "F_event", forks, 5), (2, 5))


# ---------------------------------------------------------------------------
# 4. State machines: SGC203, SGC205
# ---------------------------------------------------------------------------

ORDER = """
    #!spec
    [Payments] ~> <Paid>
    [Checkout] ~> <Placed>
    state {Order} {
      +     -<Placed>->  Open
      Open  -<Paid>->    Settled
    }
    """

IGNORED = """
    #!spec
    [Shop] ~> <Paid>
    [Shop] ~> <Paid>
    state {Order} {
      +  -<Paid>->  Settled
    }
    """


class Machines(unittest.TestCase):
    def view(self, text):
        f = cs.facts_of(make_doc(text))
        return f.machines[0]

    def test_step_prefers_the_specific_transition(self):
        m = self.view("state {X} {\n  _ -<Go>-> Weird\n  A -<Go>-> B\n  + -<Start>-> A\n}\n")
        a = next(s for s, n in m.states.items() if n == "A")
        self.assertEqual(m.name(ct.step(m, a, "<Go>")[0]), "B")
        self.assertEqual(ct.step(m, a, "<None>"), (a, True))

    def test_the_diamond_check(self):
        m = self.view("state {X} {\n  + -<A>-> One\n  One -<B>-> Two\n}\n")
        start = next(iter(m.start))
        self.assertTrue(ct.order_matters(m, start, "<A>", "<B>"))
        m = self.view("state {X} {\n  S -<A>-> S\n  S -<B>-> S\n}\n")
        self.assertFalse(ct.order_matters(m, "X_state_S", "<A>", "<B>"))

    def test_event_ignored_message_and_witness(self):
        (f,) = of(check(IGNORED), "SGC203")
        self.assertEqual((f.line, f.severity, f.hit.witness, f.hit.k, f.hit.trace),
                         (5, "error", "happy", 0, True))
        self.assertEqual(f.hit.anchor, ("machine", "Order_data"))
        drop = events(by_name(runs_of(IGNORED), "happy"), "ignored")[0]
        self.assertEqual(f.hit.at, drop["t"])             # the tick the run shows it
        (f,) = of(check(IGNORED, mode="craft"), "SGC203")
        self.assertEqual(f.message, "`<Paid>` reaches `{Order}` while it is `Settled`. "
                                    "Should it be ignored, or is a transition missing?")

    def test_event_ignored_can_be_acknowledged(self):
        text = IGNORED.replace("Settled\n", "Settled   # accepts: event-ignored — a "
                                            "repeat is a no-op\n")
        rep = check(text)
        self.assertEqual(of(rep, "SGC203"), [])
        self.assertEqual([f.rule.id for f in rep.acknowledged], ["SGC203"])

    def test_sketch_hides_it(self):
        rep = check(IGNORED.replace("#!spec", "#!sketch"))
        self.assertEqual([f.severity for f in of(rep, "SGC203")], ["info"])
        self.assertEqual(finding_keys(rep), [])

    def test_ordering_replaces_the_static_guess_and_asks_the_order(self):
        (f,) = of(check(ORDER), "SGC205")
        self.assertEqual((f.line, f.severity, f.hit.trace, f.hit.guess), (5, "warn", True, ""))
        (f,) = of(check(ORDER, mode="craft"), "SGC205")
        self.assertEqual(f.message, "`{Order}` only works if `<Placed>` comes before "
                                    "`<Paid>`. Is that order guaranteed?")

    def test_a_stated_order_declares_it(self):
        rep = check(ORDER.replace("    }\n", "    } @inv ordered(order_id)\n"))
        self.assertEqual(of(rep, "SGC205"), [])

    def test_per_sender_fifo_is_quiet_in_the_runs(self):
        rep = check(fixture("trace-205-fifo.sigil"))
        self.assertEqual([f.hit.trace for f in of(rep, "SGC205")], [False])
        self.assertEqual(of(rep, "SGC203"), [])

    def test_coverage_paid_before_placed_is_an_ordering_question(self):
        text = (ROOT / "tests" / "fixtures" / "coverage.sigil").read_text(encoding="utf-8")
        (f,) = of(ck.check(text, mode="spec", k=1, registry=REGISTRY), "SGC205")
        self.assertTrue(f.hit.trace)
        self.assertIn("`<Paid>`", f.hit.statement)
        self.assertIn("`<Placed>` arrives before `<Paid>`", f.hit.statement)

    def test_the_booking_demo_seed_finding(self):
        (f,) = of(ck.check(fixture("trace-205-booking.sigil"), registry=REGISTRY), "SGC205")
        self.assertEqual(f.hit.witness, "Booking.charge:fails")
        self.assertIn("`<Declined>` reaches `{Trip}` before `<Confirmed>`", f.hit.statement)

    def test_folded_under_an_undriven_machine(self):
        rep = check("""
            #!spec
            [Shop] ~> <Paid>
            state {Order} {
              +     -<Placed>->  Open
              Open  -<Paid>->    Settled
            }
            """)
        (cause,) = of(rep, "SGC146")
        self.assertIn("ordering-unstated", {f.rule.name for f in cause.also})
        self.assertEqual(of(rep, "SGC205"), [])


# ---------------------------------------------------------------------------
# 5. SGC204 race, trace half
# ---------------------------------------------------------------------------

class Races(unittest.TestCase):
    def test_an_intra_episode_race_is_found_and_its_declared_twin_is_clean(self):
        (f,) = of(ck.check(fixture("trace-204-fanout.sigil"), registry=REGISTRY), "SGC204")
        self.assertEqual((f.hit.trace, f.hit.witness, f.hit.anchor[0]), (True, "happy", "wire"))
        self.assertEqual(dict(f.hit.scopes)["node_store"], "W_service|Doc_store")
        rep = ck.check(fixture("trace-204-fanout-declared.sigil"), registry=REGISTRY)
        self.assertEqual(of(rep, "SGC204"), [])

    def test_the_static_half_does_not_see_it(self):
        text = fixture("trace-204-fanout.sigil")
        static = ck.build_registry(cs.rules(ck))     # unextended
        self.assertEqual(of(ck.check(text, registry=static), "SGC204"), [])

    def test_concurrent_ownership_is_reported_never_passed(self):
        (f,) = of(ck.check(fixture("trace-204-owns.sigil"), registry=REGISTRY), "SGC204")
        self.assertEqual((f.severity, f.hit.guess), ("error", ""))
        self.assertIn("holds `@owns |Doc|`", f.hit.statement)

    def test_sequential_calls_are_ordered(self):
        rep = check("""
            #!spec
            (User) -> [Api] : go()
            [Api] -> [A] : run()
            [Api] -> [B] : run()
            [A] -> [W] : save()
            [B] -> [W] : save()
            [W] -> |Doc| : put({Doc})
            """)
        self.assertEqual(of(rep, "SGC204"), [])

    def test_a_kind_resolves_it(self):
        text = fixture("trace-204-fanout.sigil").replace("|Doc|", "~|Doc|")
        self.assertEqual(of(ck.check(text, registry=REGISTRY), "SGC204"), [])

    def test_q10_many_callers_race_with_themselves(self):
        rep = ck.check(fixture("trace-204-users.sigil"), registry=REGISTRY)
        self.assertEqual(len(of(rep, "SGC204")), 1)
        rep = ck.check(fixture("trace-204-user.sigil"), registry=REGISTRY)
        self.assertEqual(of(rep, "SGC204"), [])
        d = make_doc(fixture("trace-204-users.sigil"))
        tf = ct.trace_facts(ck, d)
        self.assertEqual(tf.self_concurrent(tf.runs[0]), frozenset({1}))
        self.assertTrue(list(ct.race_hits(ck, d)))

    def test_examples_md_running_flag_is_quiet(self):
        text = (ROOT / "examples.md").read_text(encoding="utf-8")
        start = text.index("[Loop]  -> ~|running| : true")
        block = text[text.rindex("```\n", 0, start) + 4:text.index("```", start)]
        rep = ck.check(block, mode="spec", registry=REGISTRY)
        self.assertEqual([f for f in rep.findings + rep.folded if f.rule.id == "SGC204"], [])

    def test_a_cross_entry_race_shows_in_an_overlap_run(self):
        (f,) = of(ck.check(fixture("trace-204-overlap.sigil"), registry=REGISTRY), "SGC204")
        self.assertEqual((f.severity, f.hit.trace, f.hit.k), ("error", True, 0))
        self.assertRegex(f.hit.witness, r"^Bob@\d+$")
        self.assertIn("a task of another entry holds it too", f.hit.statement)
        self.assertIn(f"in the `{f.hit.witness}` run", f.hit.statement)
        rep = ck.check(fixture("trace-204-overlap-declared.sigil"), registry=REGISTRY)
        self.assertEqual(of(rep, "SGC204"), [])

    def test_the_witness_replays_by_name(self):
        d = make_doc(fixture("trace-204-overlap.sigil"))
        (h,) = ct.race_hits(ck, d)
        t = sim.simulate(d.sc, sim.scenario(d.sc, h.witness), limits=d.limits, keep=False)
        self.assertEqual(ct.running_together(t.end["events"]), frozenset({frozenset({1, 2})}))

    def test_episodes_one_after_the_other_never_run_together(self):
        runs = runs_of(fixture("trace-204-overlap.sigil"))
        self.assertEqual(ct.running_together(by_name(runs, "happy").events), frozenset())
        spans = ct.busy_spans(by_name(runs, "happy").events)
        self.assertEqual(sorted(spans), [1, 2])
        self.assertLess(spans[1][1], spans[2][0])

    def test_two_episodes_clash_only_while_they_run_together(self):
        a = ct.Access(1, 1, "S", "write", ("w",), frozenset(), {1: 1})
        b = ct.Access(2, 2, "S", "write", ("w",), frozenset(), {2: 1})
        self.assertEqual(ct.clashes([a, b], frozenset()), [])
        self.assertEqual(len(ct.clashes([a, b], frozenset(), frozenset({frozenset({1, 2})}))),
                         1)

    def test_an_unknown_mode_never_clashes(self):
        a = ct.Access(1, 1, "S", "unknown", ("w",), frozenset(), {1: 1})
        b = ct.Access(2, 1, "S", "read", ("w",), frozenset(), {2: 1})
        self.assertIsNone(ct.clash(a._replace(mode="read"), b))
        self.assertTrue(ct.clash(a._replace(mode="write"), b))


# ---------------------------------------------------------------------------
# 6. SGC206 stalled-join
# ---------------------------------------------------------------------------

FLAGGED = """
    #!spec
    [S] -> [A] : a()
    [S] ?> [B] : b()
    [A] & [B] -> [C] : go()
    """


class StalledJoin(unittest.TestCase):
    def test_the_2026_10_02_probe_is_quiet(self):
        rep = check("""
            #!spec
            [S] -> [A] : a()
            [S] -> [B] : b()
            [A] & [B] -> [C] : go()
            """)
        self.assertEqual(of(rep, "SGC206"), [])

    def test_a_deposit_no_last_arrival_consumes_is_flagged(self):
        (f,) = of(check(FLAGGED), "SGC206")
        self.assertEqual((f.line, f.rule.name, f.severity), (4, "stalled-join", "error"))
        self.assertEqual((f.hit.witness, f.hit.k, f.hit.trace), ("happy", 0, True))
        self.assertEqual(f.hit.anchor, ("node", "C_service"))
        self.assertIn("`[B]`", f.hit.statement)

    def test_craft_asks(self):
        (f,) = of(check(FLAGGED, mode="craft"), "SGC206")
        self.assertEqual(f.message,
                         "`[C]` waits for `[B]` in the `happy` run. What if it never arrives?")

    def test_a_two_deviation_witness_caps_at_warn(self):
        (f,) = of(ck.check(fixture("trace-206-k2.sigil"), registry=REGISTRY), "SGC206")
        self.assertEqual((f.tier, f.severity, f.hit.k), ("binding", "warn", 2))

    def test_sketch_hides_it(self):
        rep = check(FLAGGED, mode="sketch")
        self.assertEqual([f.severity for f in of(rep, "SGC206")], ["info"])
        self.assertTrue(all(f.hidden for f in of(rep, "SGC206")))

    def test_timeout_or_fallback_on_the_join_declares_it(self):
        for mod in ("@timeout(5s)", "@fallback(none)"):
            with self.subTest(mod=mod):
                text = FLAGGED.replace("go()\n", f"go() {mod}\n")
                self.assertEqual(of(check(text), "SGC206"), [])

    def test_another_modifier_does_not(self):
        text = FLAGGED.replace("go()\n", "go() @sla(1s)\n")
        self.assertEqual(len(of(check(text), "SGC206")), 1)

    def test_acknowledged(self):
        text = FLAGGED.replace("go()\n", "go()   # accepts: stalled-join — B always runs\n")
        rep = check(text)
        self.assertEqual(of(rep, "SGC206"), [])
        self.assertEqual([f.line for f in rep.acknowledged if f.rule.id == "SGC206"], [4])

    def test_one_finding_per_join_across_runs(self):
        rep = check("""
            #!spec
            [S] -> [A] : a()
            [S] ?> [B] : b()
            [S] -> [D] : d()
            [A] & [B] -> [C] : go()
            """)
        self.assertEqual([f.line for f in of(rep, "SGC206")], [5])

    def test_without_a_join_nothing_can_stall(self):
        self.assertFalse(ct.may_hold_joins(make_doc("[S] -> [A] : a()\n").graphs))
        self.assertTrue(ct.may_hold_joins(make_doc(FLAGGED).graphs))


class OpenJoins(unittest.TestCase):
    """open_joins over a run's end record: both halves, and a cut run."""

    def setUp(self):
        self.d = make_doc("""
            [S] *> [A] & [B] : x()
            [A] -> [D] : d()
            """)
        self.policy = self.d.scene.call_policy

    def end(self, **kw):
        out = {"deposits": [], "stalled": []}
        out.update(kw)
        return out

    def joins(self, d, end, outcome="ok"):
        return ct.open_joins(ct.Run(d.sim.Scenario("happy"), end, outcome), d.prog.units,
                             d.sc.wires, d.scene.call_policy)

    def test_a_waiting_task_is_an_open_join(self):
        (oj,) = self.joins(self.d, self.end(stalled=["S_service"]))
        self.assertEqual((oj.key, oj.line, oj.waiter, oj.missing, oj.bounded),
                         (("waiting", "S_service"), 1, "S_service", (), False))

    def test_a_waiting_task_with_a_bounded_fan_out(self):
        d = make_doc("[S] *> [A] & [B] : x() @timeout(2s)\n")
        (oj,) = self.joins(d, self.end(stalled=["S_service"]))
        self.assertTrue(oj.bounded)

    def test_a_deposit_is_an_open_join_and_deposits_come_first(self):
        d = make_doc(FLAGGED)
        deposit = {"join": (0, 0), "target": "C_service", "arrived": ["A_service"],
                   "missing": ["B_service"]}
        got = self.joins(d, self.end(deposits=[deposit], stalled=["S_service"]))
        self.assertEqual([oj.key[0] for oj in got], ["deposit", "waiting"])
        oj = got[0]
        self.assertEqual((oj.key, oj.line, oj.missing, oj.bounded),
                         (("deposit", 0, 0, "C_service"), 4, ("B_service",), False))

    def test_a_cut_run_shows_no_stall(self):
        self.assertEqual(self.joins(self.d, self.end(stalled=["S_service"]), "cut"), [])

    def test_first_witness_wins(self):
        a, b = ct.Run("a", {}, "ok"), ct.Run("b", {}, "ok")
        oj = ct.OpenJoin(("waiting", "X"), 1, "X", (), False)
        self.assertEqual(ct.first_witnesses([a, b], lambda r: [oj]), [(oj, a)])


# ---------------------------------------------------------------------------
# 7. SGC175 unreached
# ---------------------------------------------------------------------------

class Unreached(unittest.TestCase):
    def test_an_unused_alias(self):
        (f,) = of(ck.check(fixture("trace-175-flagged.sigil"), registry=REGISTRY), "SGC175")
        self.assertEqual((f.severity, f.tier), ("info", "hint"))
        self.assertEqual(f.hit.statement, "nothing invokes `purge`")

    def test_a_rootless_cycle_is_one_finding(self):
        (f,) = of(ck.check(fixture("trace-175-rootless.sigil"), registry=REGISTRY), "SGC175")
        self.assertIn("`[Ping]` and `[Pong]`", f.hit.statement)

    def test_the_corpus_evidence(self):
        text = (ROOT / "tests" / "fixtures" / "coverage.sigil").read_text(encoding="utf-8")
        got = [f.line for f in of(ck.check(text, mode="spec", k=1, registry=REGISTRY),
                                  "SGC175")]
        self.assertEqual(got, [82, 195, 196, 197])
        text = (ROOT / "tests" / "fixtures" / "executions.sigil").read_text(encoding="utf-8")
        got = [f.line for f in of(ck.check(text, mode="spec", k=1, registry=REGISTRY),
                                  "SGC175")]
        self.assertEqual(got, [30])

    def test_quiet_with_no_entry_at_all(self):
        rep = ck.check(fixture("trace-175-entryless.sigil"), mode="spec", registry=REGISTRY)
        self.assertEqual(of(rep, "SGC175"), [])
        self.assertEqual(len(of(rep, "SGC152")), 1)

    def test_a_field_branch_is_reached(self):
        rep = ck.check(fixture("trace-fix-b4.sigil"), mode="spec", registry=REGISTRY)
        self.assertEqual(of(rep, "SGC175"), [])

    def test_groups(self):
        self.assertEqual(ct.groups(["a", "b", "c", "d"], [("b", "d"), ("x", "a")]),
                         [["a"], ["b", "d"], ["c"]])


# ---------------------------------------------------------------------------
# 8. SGC090 exploration-incomplete: the run causes
# ---------------------------------------------------------------------------

COVERAGE = ROOT / "tests" / "fixtures" / "coverage.sigil"


def cause_of(report, words: str) -> list:
    """The SGC090 findings whose statement holds the given words."""
    return [f for f in of(report, "SGC090") if words in f.hit.statement]


class Exploration(unittest.TestCase):
    """The bounds reach the exploration through the public API (check's
    budget= / limits=, --budget / --limit), and --json reports what ran."""

    def test_the_budget_counts_what_it_left_out(self):
        rep = ck.check(fixture("trace-206-k2.sigil"), k=2, budget=1, registry=REGISTRY)
        (f,) = cause_of(rep, "exploration budget")
        self.assertIn("left 1 combination of up to 2 deviations unrun", f.hit.statement)
        self.assertIn("budget=1 runs, k=2", f.hit.statement)
        self.assertEqual(rep.limits["budget"], 1)

    def test_the_budget_on_a_spec(self):
        rep = ck.check(COVERAGE.read_text(encoding="utf-8"), mode="spec", budget=1,
                       registry=REGISTRY)
        (f,) = cause_of(rep, "exploration budget")
        self.assertIn("budget=1 runs", f.hit.statement)

    def test_the_budget_counts_the_overlap_runs_it_left_out(self):
        text = fixture("trace-204-overlap.sigil")
        d = make_doc(text)
        starts = ct.overlap_scenarios(sim, d.sc, (), d.limits)
        rep = ck.check(text, budget=2, registry=REGISTRY)
        (f,) = cause_of(rep, "exploration budget")
        self.assertIn(f"left {len(starts) - 2} overlap runs (an entry started while an "
                      "earlier one runs) unrun (budget=2 runs", f.hit.statement)
        self.assertEqual(cause_of(ck.check(text, registry=REGISTRY), "exploration budget"), [])

    def test_overlap_runs_are_the_spec_checks_and_off_while_drafting(self):
        text = fixture("trace-204-overlap.sigil")
        races = lambda **kw: of(ck.check(text, registry=REGISTRY, **kw), "SGC204")
        self.assertEqual(len(races()), 1)                       # #!spec: every tick
        self.assertEqual(races(mode="craft"), [])               # drafting: none
        self.assertEqual(len(races(mode="craft", overlaps="listed")), 1)
        self.assertEqual(races(overlaps="off"), [])
        rep = ck.check(text, registry=REGISTRY, mode="craft")
        self.assertEqual(rep.limits["overlap_runs"], "off")
        self.assertEqual(rep.limits["overlaps"], sim.Limits().overlaps)

    def test_listed_skips_the_sweep_and_n_caps_the_overlap_runs(self):
        d = make_doc(fixture("trace-204-overlap.sigil"))
        listed = [s.name for s in sim.overlaps(d.sc, limits=d.limits)]
        got = ct.overlap_scenarios(sim, d.sc, (), d.limits, sweep=False)
        self.assertEqual([s.name for s in got], listed)
        ex = ct.explore(sim, d.sc, 1, 500, d.limits, overlaps=1)
        self.assertEqual(sum(1 for r in ex.runs if r.scenario.starts), 1)
        self.assertGreater(ex.overlaps_left_out, 0)
        off = ct.explore(sim, d.sc, 1, 500, d.limits, overlaps="off")
        self.assertEqual((sum(1 for r in off.runs if r.scenario.starts),
                          off.overlaps_left_out), (0, 0))

    def test_the_overlaps_option_reads_a_mode_or_a_number(self):
        self.assertEqual(cli.overlaps_arg("listed"), "listed")
        self.assertEqual(cli.overlaps_arg("7"), 7)
        for bad in ("0", "some", "-1"):
            with self.assertRaises(Exception):
                cli.overlaps_arg(bad)

    def test_the_listed_starts_come_first_then_each_deviation_then_every_tick(self):
        d = make_doc(fixture("trace-204-overlap.sigil"))
        ticks = sim.overlap_runs(d.sc, limits=d.limits)
        (window,) = sim.overlap_windows(d.sc, limits=d.limits)
        self.assertEqual([s.name for s in ticks],
                         [f"Bob@{t}" for t in range(window.start, window.end + 1)])
        deviated = ct.Run(sim.Scenario("X.f:fails", (("cid", "fail"),), "x fails"), {}, "ok")
        got = ct.overlap_scenarios(sim, d.sc, (deviated,), d.limits)
        listed = sim.overlaps(d.sc, limits=d.limits)
        head = [s.name for s in listed] + [f"X.f:fails+{s.name}" for s in listed]
        self.assertEqual([s.name for s in got],
                         head + [s.name for s in ticks if s.name not in head])
        self.assertEqual(got[len(listed)].choices, (("cid", "fail"),))
        self.assertEqual(got[len(listed)].starts, listed[0].starts)

    def test_the_sweep_takes_the_windows_round_robin(self):
        w = [sim.OverlapWindow("A", "B", 0, 9), sim.OverlapWindow("A", "C", 0, 9)]
        start = lambda e, t: sim.Scenario(f"{e}@{t}", starts=((e, t),))
        groups = ct.by_window(w, [start("B", 0), start("B", 1), start("B", 2),
                                  start("C", 5), start("D", 1)])
        self.assertEqual([[s.name for s in g] for g in groups],
                         [["B@0", "B@1", "B@2"], ["C@5"], ["D@1"]])
        self.assertEqual([s.name for s in ct.round_robin(groups)],
                         ["B@0", "C@5", "D@1", "B@1", "B@2"])
        self.assertEqual(ct.round_robin([]), [])

    def test_a_small_budget_runs_every_listed_overlap_before_the_sweep(self):
        text = COVERAGE.read_text(encoding="utf-8")
        d = make_doc(text)
        listed = [s.name for s in sim.overlaps(d.sc, limits=d.limits)]
        self.assertGreater(len(listed), 3)
        made = []

        class Recording:
            def __getattr__(self, name):
                return getattr(sim, name)

            def simulate(self, sc, s, **kw):
                made.append(s)
                return sim.simulate(sc, s, **kw)

        combos = sim.combinations(d.sc, 0, limits=d.limits, budget=10)
        budget = len(combos.traces) - 1 + combos.duplicates + len(listed) + 4
        ex = ct.explore(Recording(), d.sc, 0, budget, d.limits)
        overlap = [s.name for s in made if s.starts]
        self.assertEqual(overlap[:len(listed)], listed)
        swept = {s.starts[0][0] for s in made[len(listed):] if s.starts}
        self.assertGreater(len(swept), 1)
        self.assertGreater(ex.overlaps_left_out, 0)

    def test_a_deviated_overlap_run_reads_back_by_name(self):
        text = fixture("trace-204-overlap.sigil") + "[Sync] -> (Ext) : op x.put() @timeout(1s)\n"
        d = make_doc(text)
        deviated = [r for r in ct.trace_facts(ck, d).runs if r.k and r.scenario.starts]
        self.assertTrue(deviated)
        for r in deviated:
            with self.subTest(run=r.scenario.name):
                self.assertRegex(r.scenario.name, r"^Sync\.x\.put:fails\+Bob@\d+$")
                back = sim.scenario(d.sc, r.scenario.name)
                self.assertEqual((back.choices, back.starts),
                                 (r.scenario.choices, r.scenario.starts))

    def test_run_new_drops_repeats_and_stops_at_the_budget(self):
        logs = {"a": ["x"], "b": ["x"], "c": ["y"], "d": ["z"]}
        made = []

        def simulate(s):
            made.append(s.name)
            return sim.Trace(s, (), "ok", {"log": logs[s.name]})
        scen = [sim.Scenario(n) for n in "abcd"]
        ran = ct.run_new(simulate, scen, 3, {("ok", ())})
        self.assertEqual(([r.scenario.name for r in ran.runs], ran.left), (["a", "c"], 1))
        self.assertFalse(ran.work_cut)
        self.assertEqual(made, ["a", "b", "c"])

    def test_run_new_stops_once_the_runs_frames_reach_the_work_cap(self):
        # each run's frames: its last event's tick plus one (repeats count too)
        ticks = {"a": 5, "b": 5, "c": 3, "d": 1}

        def simulate(s):
            end = {"log": [s.name], "events": [{"kind": "end", "t": ticks[s.name] - 1}]}
            return sim.Trace(s, (), "ok", end)
        scen = [sim.Scenario(n) for n in "abcd"]
        ran = ct.run_new(simulate, scen, 10, set(), work=10)
        self.assertEqual(([r.scenario.name for r in ran.runs], ran.left, ran.work,
                          ran.work_cut), (["a", "b"], 2, 10, True))
        ran = ct.run_new(simulate, scen, 10, set(), work=11)
        self.assertEqual((len(ran.runs), ran.left, ran.work, ran.work_cut), (3, 1, 13, True))
        ran = ct.run_new(simulate, scen, 2, set(), work=10)       # the budget stops it first
        self.assertEqual((ran.left, ran.work_cut), (2, False))
        self.assertEqual(ct.run_new(simulate, scen, 10, set()).left, 0)   # no cap
        self.assertEqual(ct.frames_of(ct.Run(scen[0], {}, "ok")), 0)

    def test_the_work_cap_grows_with_a_larger_budget_only(self):
        floor = ct.WORK_PER_RUN * ct.BUDGET
        self.assertEqual([ct.work_cap(b) for b in (1, ct.BUDGET, 2 * ct.BUDGET)],
                         [floor, floor, 2 * floor])

    def test_the_overlap_sweep_is_bounded_by_its_frames(self):
        from unittest import mock
        text = fixture("trace-204-overlap.sigil")
        d = make_doc(text)
        whole = ct.explore(sim, d.sc, 1, ct.BUDGET, d.limits)
        self.assertEqual((whole.overlaps_left_out, whole.work_cut), (0, False))
        self.assertGreater(whole.work, 0)
        self.assertEqual(cause_of(ck.check(text, registry=REGISTRY), "exploration budget"), [])
        with mock.patch.object(ct, "WORK_PER_RUN", 1):           # a cap of BUDGET frames
            cut = ct.explore(sim, d.sc, 1, ct.BUDGET, d.limits)
            (f,) = cause_of(ck.check(text, registry=REGISTRY), "exploration budget")
        self.assertTrue(cut.work_cut)
        self.assertGreater(cut.overlaps_left_out, 0)
        self.assertGreaterEqual(cut.work, ct.BUDGET)
        self.assertLess(sum(1 for r in cut.runs if r.scenario.starts),
                        sum(1 for r in whole.runs if r.scenario.starts))
        self.assertIn(f"left {cut.overlaps_left_out} overlap runs (an entry started while an "
                      f"earlier one runs; their frames reached the work cap: {cut.work} of "
                      f"{ct.BUDGET}) unrun", f.hit.statement)
        self.assertIn("--budget N; above 256 it raises the work cap", f.hit.fix)
        self.assertIn("--overlaps listed", f.hit.fix)

    def test_the_overlap_runs_follow_the_deviation_runs(self):
        names = [r.scenario.name for r in runs_of(fixture("trace-204-overlap.sigil"))]
        self.assertEqual(names[0], "happy")
        self.assertTrue(all(re.match(r"^Bob@\d+$", n) for n in names[1:]), names)

    def test_a_cut_run(self):
        rep = ck.check(COVERAGE.read_text(encoding="utf-8"), mode="spec", limits=sim.Limits(frames=10),
                       registry=REGISTRY)
        (f,) = cause_of(rep, "cut a run at its frames limit")
        self.assertIn("in the `happy` run", f.hit.statement)
        self.assertIn("frames=10", f.hit.statement)
        self.assertEqual((f.hit.trace, f.hit.k), (True, 0))
        self.assertEqual(rep.limits["frames"], 10)

    def test_a_larger_limit_silences_the_declared_bound(self):
        text = fixture("trace-090-bound.sigil")
        self.assertEqual(len(of(ck.check(text, registry=REGISTRY), "SGC090")), 1)
        rep = ck.check(text, limits=sim.Limits(depth=40), registry=REGISTRY)
        self.assertEqual(of(rep, "SGC090"), [])

    def test_the_cli_passes_its_bounds_on(self):
        def cli(*args) -> str:
            return subprocess.run([sys.executable, str(ROOT / "bin" / "sigil"), "check", *args, "--all"],
                                  capture_output=True, text=True).stdout
        out = cli(str(COVERAGE), "--mode", "spec", "--budget", "1")
        self.assertIn("budget=1 runs", out)
        self.assertNotIn("budget=256", out)
        self.assertIn("frames=10", cli(str(COVERAGE), "--mode", "spec", "--limit", "frames=10"))
        bound = str(ROOT / "tests" / "fixtures" / "checks" / "trace-090-bound.sigil")
        self.assertIn("SGC090", cli(bound))
        self.assertNotIn("SGC090", cli(bound, "--limit", "depth=40"))

    def test_only_a_cut_or_a_loop_cap_is_acknowledgeable(self):
        rule = REGISTRY["SGC090"]
        self.assertEqual((rule.acknowledgeable, rule.ack_document), (False, False))
        (budget,) = cause_of(ck.check(fixture("trace-206-k2.sigil"), k=2, budget=1,
                                      registry=REGISTRY), "exploration budget")
        self.assertFalse(ck.acknowledgeable(budget))
        (cut,) = cause_of(self.cut("spec"), "cut a run")
        self.assertTrue(ck.acknowledgeable(cut))

    # A short spec the simulator cuts at frames=2 (its entry on line 2).
    SHORT = ("#!spec\n(U) -> [A] : go({X}) => {Y}\n[A] -> [B] : step({X}) => {Y}\n"
             "[B] -> [C] : step({X}) => {Y}\n")

    def cut(self, mode: str, text: str = SHORT):
        return ck.check(text, mode=mode, limits=sim.Limits(frames=2), registry=REGISTRY)

    def test_a_cut_run_warns_in_spec_only(self):
        severities = {}
        for mode in ck.MODES:
            rep = self.cut(mode)
            severities[mode] = [f.severity for f in rep.findings
                                if f.rule.id == "SGC090" and "cut a run" in f.hit.statement]
        self.assertEqual(severities, {"sketch": [], "craft": ["info"], "spec": ["warn"]})
        (f,) = cause_of(self.cut("spec"), "cut a run")
        self.assertEqual(f.line, 2)
        self.assertIn("raise --limit frames=N until no run is cut", f.hit.fix)

    def test_the_other_causes_stay_hints_in_spec(self):
        rep = ck.check(COVERAGE.read_text(encoding="utf-8"), mode="spec", budget=1,
                       registry=REGISTRY)
        (f,) = cause_of(rep, "exploration budget")
        self.assertEqual(f.severity, "info")

    def test_a_cut_is_acknowledged_on_its_entry_line(self):
        acked = self.SHORT.replace("=> {Y}\n", "=> {Y}  # accepts: exploration-incomplete "
                                   "— the happy run is long by design\n", 1)
        rep = self.cut("spec", acked)
        self.assertEqual(cause_of(rep, "cut a run"), [])
        self.assertEqual([f.rule.id for f in rep.acknowledged], ["SGC090"])

    def test_a_cut_run_blocks_the_export_gate(self):
        from sigil.analyse import lint
        from sigil.publish import exporter

        blocking = exporter.gate(self.SHORT, None, lint, ck, sim.Limits(frames=2))
        self.assertTrue(any("SGC090" in ln and "cut a run" in ln for ln in blocking), blocking)
        self.assertFalse(any("SGC090" in ln for ln in exporter.gate(self.SHORT, None, lint, ck)))

    def test_export_takes_the_limits_its_gate_checks_under(self):
        import tempfile

        def export(*args):
            return subprocess.run([sys.executable, str(ROOT / "bin" / "sigil"), "export",
                                   str(spec), "--out", str(Path(tmp) / "out"), "--dry-run",
                                   *args], capture_output=True, text=True)
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / "short.sigil"
            spec.write_text(self.SHORT, encoding="utf-8")
            cut = export("--limit", "frames=2")
            self.assertEqual(cut.returncode, 2)
            self.assertIn("cut a run at its frames limit", cut.stdout)
            self.assertIn("frames=2)", cut.stdout)
            self.assertIn("not ready to export", cut.stderr)
            self.assertNotIn("SGC090", export().stdout)
            self.assertNotIn("SGC090", export("--limit", "frames=2", "--limit",
                                              "frames=5000").stdout)
            bad = export("--limit", "frames=none")
            self.assertEqual(bad.returncode, 2)
            self.assertIn("frames=none", bad.stderr)

    # A chain long enough that the default frames and activations limits grow
    # past their floors (sim.sized): 41 nodes and 40 edges.
    LONG = "#!craft\n(U) -> [N0] : go({X}) => {Y}\n" + "".join(
        f"[N{i}] -> [N{i + 1}] : step({{X}}) => {{Y}}\n" for i in range(39))

    def test_the_limits_shown_are_the_ones_the_runs_had(self):
        sized = sim.sized(sim.Limits(), make_doc(self.LONG).sc)
        self.assertEqual((sized.frames, sized.activations),
                         (sim.PER_SIZE["frames"] * 81, sim.PER_SIZE["activations"] * 81))
        rep = ck.check(self.LONG, registry=REGISTRY)
        self.assertEqual((rep.limits["frames"], rep.limits["activations"]),
                         (sized.frames, sized.activations))
        rep = ck.check(self.LONG, limits=sim.Limits(stack=4), registry=REGISTRY)
        (f,) = cause_of(rep, "cut a run at its stack limit")
        self.assertIn(f"(limits: activations={sized.activations}, stack=4, "
                      f"frames={sized.frames})", f.hit.statement)
        self.assertEqual(rep.limits["stack"], 4)
        given = ck.check(self.LONG, limits=sim.limits_from(["frames=3000"]), registry=REGISTRY)
        self.assertEqual((given.limits["frames"], given.limits["activations"]),
                         (3000, sized.activations))
        small = ck.check(self.SHORT, registry=REGISTRY)            # a small one: the floors
        self.assertEqual((small.limits["frames"], small.limits["activations"]), (2000, 500))

    def test_the_loop_cap_reads_the_iterations_limit(self):
        text = "#!craft\n(U) -> [B] : run()\nloop @times 5 {\n  [B] -> |Q| : push({I})\n}\n"
        (f,) = of(ck.check(text, registry=REGISTRY), "SGC090")
        self.assertIn("ran this loop 2 of its 5 times (limits: iterations=2)", f.hit.statement)
        self.assertIn("--limit iterations=N", f.hit.fix)
        (f,) = of(ck.check(text, limits=sim.Limits(iterations=3), registry=REGISTRY), "SGC090")
        self.assertIn("ran this loop 3 of its 5 times (limits: iterations=3)", f.hit.statement)
        self.assertEqual(of(ck.check(text, limits=sim.Limits(iterations=5), registry=REGISTRY),
                            "SGC090"), [])

    def test_a_declared_bound_beyond_the_simulators(self):
        rep = ck.check(fixture("trace-090-bound.sigil"), registry=REGISTRY)
        (f,) = of(rep, "SGC090")
        self.assertIn("bounded by design (depth <= 32) vs the simulator (depth 3)",
                      f.hit.statement)
        text = fixture("trace-090-bound.sigil").replace("<= 32", "<= 2")
        self.assertEqual(of(ck.check(text, registry=REGISTRY), "SGC090"), [])

    def test_the_spawn_ceiling(self):
        (f,) = of(ck.check(fixture("trace-090-spawn.sigil"), registry=REGISTRY), "SGC090")
        self.assertIn("stopped spawning `[W]`", f.hit.statement)
        self.assertIn("spawns=8", f.hit.statement)


# ---------------------------------------------------------------------------
# 9. Witnesses, extend_rules, determinism, cost
# ---------------------------------------------------------------------------

class Witnesses(unittest.TestCase):
    def test_unbounded_recursion(self):
        rep = check("#!spec\n(U) -> [A] : go()\n[A] -> [A] : again()\n")
        (f,) = of(rep, "SGC151")
        self.assertEqual((f.hit.witness, f.hit.k, f.hit.trace), ("happy", None, False))

    def test_async_cycle(self):
        (f,) = of(check("#!spec\n[P] -> [Q]\n[Q] ~> [R]\n[R] ~> [Q]\n"), "SGC152")
        self.assertEqual(f.hit.witness, "happy")

    def test_unhandled_failure(self):
        rep = check("""
            #!spec
            (User) -> [Judge] : judge()
            [Judge] -> |Scores| : op db.insert(${score}) @timeout(2s)
            """)
        (f,) = of(rep, "SGC201")
        self.assertEqual((f.severity, f.hit.witness, f.hit.k), ("error", "Judge.db.insert:fails",
                                                                None))

    def test_dead_failure_route(self):
        rep = check("""
            #!spec
            (U) -> [A] : go()
            [A] ~> [B] : notify()
                 !> <Failed>
            [B] -> (Ext) : op x.put() @timeout(1s)
            """)
        (f,) = of(rep, "SGC202")
        self.assertEqual(f.hit.witness, "A.notify:fails")

    def test_a_route_on_produced_data_has_no_witness(self):
        rep = check("#!spec\n(U) -> [A] : go()\n[A] -> {Report}\n     !> <Failed>\n")
        self.assertEqual([f.hit.witness for f in of(rep, "SGC202")], [None])


class Extending(unittest.TestCase):
    def test_extend_rules_is_idempotent(self):
        rules = ck.core_rules() + ck.module_rules(ck)
        once = ct.extend_rules(ck, rules)
        twice = ct.extend_rules(ck, once)
        self.assertEqual([r.match for r in once], [r.match for r in twice])
        extended = {r.id for r in once if isinstance(r.match, ct.ExtendedMatch)}
        self.assertEqual(extended, {"SGC151", "SGC152", "SGC201", "SGC202", "SGC204",
                                    "SGC205"})

    def test_merged(self):
        static_guess = ck.Hit(1, "s", "a", anchor=("machine", "M"), guess="g")
        static_exact = ck.Hit(1, "s", "a", anchor=("machine", "N"))
        trace = [ck.Hit(1, "t", "a", anchor=("machine", "M"), trace=True),
                 ck.Hit(1, "t", "a", anchor=("machine", "N"), trace=True),
                 ck.Hit(1, "t", "a", anchor=("machine", "O"), trace=True)]
        got = ct.merged([static_guess, static_exact], trace, ct.by_anchor)
        self.assertEqual([(h.anchor[1], h.statement) for h in got],
                         [("M", "t"), ("N", "s"), ("O", "t")])


class Determinism(unittest.TestCase):
    def test_byte_identical_across_hash_seeds(self):
        path = str(ROOT / "tests" / "fixtures" / "coverage.sigil")
        outs = []
        for seed in ("1", "2"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            outs.append(subprocess.run([sys.executable, str(ROOT / "bin" / "sigil"), "check", path, "--json",
                                        "--mode", "spec"], capture_output=True, env=env).stdout)
        self.assertEqual(outs[0], outs[1])
        self.assertTrue(outs[0])

    def test_the_playground_budget_on_coverage(self):
        text = COVERAGE.read_text(encoding="utf-8")
        start = time.perf_counter()
        ck.check(text, mode="craft", k=1, registry=REGISTRY)
        self.assertLess(time.perf_counter() - start, 10.0)


if __name__ == "__main__":
    unittest.main()
