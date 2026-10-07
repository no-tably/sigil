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

import importlib.util
import os
import re
import subprocess
import sys
import textwrap
import time
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


ck = _load("sigil_check_for_trace", "check.py")
ct = ck._rule_module(ck._HERE / "check_trace.py")        # the instance check.py loads
sim = ck._sim()

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
        f = ct.state_module(ck).facts_of(make_doc(text))
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
        text = (_DIR / "tests" / "fixtures" / "coverage.sigil").read_text(encoding="utf-8")
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
        static = ck.build_registry(ct.state_module(ck).rules(ck))     # unextended
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
        text = (_DIR / "examples.md").read_text(encoding="utf-8")
        start = text.index("[Loop]  -> ~|running| : true")
        block = text[text.rindex("```\n", 0, start) + 4:text.index("```", start)]
        rep = ck.check(block, mode="spec", registry=REGISTRY)
        self.assertEqual([f for f in rep.findings + rep.folded if f.rule.id == "SGC204"], [])

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
        text = (_DIR / "tests" / "fixtures" / "coverage.sigil").read_text(encoding="utf-8")
        got = [f.line for f in of(ck.check(text, mode="spec", k=1, registry=REGISTRY),
                                  "SGC175")]
        self.assertEqual(got, [82, 195, 196, 197])
        text = (_DIR / "tests" / "fixtures" / "executions.sigil").read_text(encoding="utf-8")
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

COVERAGE = _DIR / "tests" / "fixtures" / "coverage.sigil"


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
            return subprocess.run([sys.executable, str(_DIR / "check.py"), *args, "--all"],
                                  capture_output=True, text=True).stdout
        out = cli(str(COVERAGE), "--mode", "spec", "--budget", "1")
        self.assertIn("budget=1 runs", out)
        self.assertNotIn("budget=256", out)
        self.assertIn("frames=10", cli(str(COVERAGE), "--mode", "spec", "--limit", "frames=10"))
        bound = str(_DIR / "tests" / "fixtures" / "checks" / "trace-090-bound.sigil")
        self.assertIn("SGC090", cli(bound))
        self.assertNotIn("SGC090", cli(bound, "--limit", "depth=40"))

    def test_a_cut_is_not_acknowledgeable(self):
        rule = REGISTRY["SGC090"]
        self.assertFalse(rule.acknowledgeable)

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
        path = str(_DIR / "tests" / "fixtures" / "coverage.sigil")
        outs = []
        for seed in ("1", "2"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            outs.append(subprocess.run([sys.executable, str(_DIR / "check.py"), path, "--json",
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
