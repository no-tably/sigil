"""check_flow.py (RFC 0003, P2 structural rules): calls, delivery, sagas, load and
the static halves of the failure rules — SGC101-104, 111-114, 121-123, 161-163,
165-167, 201 and 202.

Each rule's evidence is a fixture: tests/fixtures/checks/flow-*.sigil, a flagged
design (the catalog's Example) and its declared twin, with every finding the core
and flow rules give in a `# expect: LINE:RULE` header (`none` for a quiet one).
The corpus lines the catalog cites as satisfied stay clean; the suppression cases
(101 folds 165 and 134, 114 folds 201) fold.

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import os
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


ck = _load("sigil_check_flow_suite_check", "check.py")
cf = _load("sigil_check_flow_suite_flow", "check_flow.py")

FLOW_IDS = ("SGC101", "SGC102", "SGC103", "SGC104", "SGC111", "SGC112", "SGC113",
            "SGC114", "SGC121", "SGC122", "SGC123", "SGC161", "SGC162", "SGC163",
            "SGC165", "SGC166", "SGC167", "SGC201", "SGC202")


def registry(*extra):
    return ck.build_registry(ck.core_rules() + cf.rules(ck) + list(extra))


def run(text: str, *extra, mode=None):
    return ck.check(textwrap.dedent(text).lstrip("\n"), mode=mode, registry=registry(*extra))


def found(report) -> list:
    """(line, rule id) of every finding, hidden ones included."""
    return [(f.line, f.rule.id) for f in report.findings]


def ids(report) -> list:
    return [f.rule.id for f in report.findings]


def expected_of(text: str) -> list:
    """The `# expect: LINE:RULE` lines of a fixture's header."""
    return [(int(m[1]), m[2]) for m in re.finditer(r"^# expect: (\d+):(\w+)$", text, re.M)]


def fixture(stem: str):
    text = (_FIXTURES / f"flow-{stem}.sigil").read_text(encoding="utf-8")
    return text, ck.check(text, registry=registry())


def rule_of(text: str) -> str:
    """The rule a fixture is about: the id its title line names."""
    return re.search(r"^# (SGC\d{3}) ", text, re.M).group(1)


def block_at(path: Path, line: int) -> str:
    """The fenced code block of a markdown file that holds `line` (1-based)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    opens = [i for i, ln in enumerate(lines) if ln.startswith("```")]
    for a, b in zip(opens[::2], opens[1::2]):
        if a < line - 1 < b:
            return "\n".join(lines[a + 1:b]) + "\n"
    raise AssertionError(f"{path.name}:{line} is in no code block")


def probe(name: str, rid: str, line: int, scopes=()):
    """A stand-in rule flagging one line (for a cause another module owns)."""
    def match(_doc):
        yield ck.Hit(line, f"{name} at {line}", f"{name}?", anchor=("line", line),
                     scopes=scopes)
    return ck.Rule(rid, name, "advisory", ask="?", why="a test rule", fix="", match=match)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class Registration(unittest.TestCase):
    def test_the_rules_match_the_catalog(self):
        rules = cf.rules(ck)
        self.assertEqual([r.id for r in rules], list(FLOW_IDS))
        for r in rules:
            with self.subTest(rule=r.id):
                self.assertEqual(r.name, ck.CORE_NAMES[r.id])
                self.assertIn(r.tier, ck.TIERS)
                self.assertTrue(r.ask.endswith("?"))
                self.assertTrue(r.why and r.fix)

    def test_tiers(self):
        tiers = {r.id: r.tier for r in cf.rules(ck)}
        self.assertEqual(
            [rid for rid in FLOW_IDS if tiers[rid] == "binding"],
            ["SGC101", "SGC103", "SGC111", "SGC114", "SGC123", "SGC201", "SGC202"])
        self.assertEqual([rid for rid in FLOW_IDS if tiers[rid] == "hint"], ["SGC163"])

    def test_joins_the_default_registry(self):
        reg = ck.default_registry()
        for rid in FLOW_IDS:
            self.assertIn(rid, reg)

    def test_suppression_is_registry_data(self):
        rules = {r.id: r for r in cf.rules(ck)}
        self.assertIn(("fanout-tail", "call"), rules["SGC101"].implies)
        self.assertIn(("held-across-call", "call"), rules["SGC101"].implies)
        self.assertIn(("unhandled-failure", "wire"), rules["SGC114"].implies)
        self.assertIn(("orphan-event", "event"), rules["SGC202"].implies)
        self.assertIn(("unreached", "store"), rules["SGC161"].implies)


# ---------------------------------------------------------------------------
# The fixtures: each probe flagged, each declared twin clean of it
# ---------------------------------------------------------------------------

class Fixtures(unittest.TestCase):
    def paths(self):
        paths = sorted(_FIXTURES.glob("flow-*.sigil"))
        self.assertTrue(paths)
        return paths

    def test_every_fixture_gives_its_expected_findings(self):
        for path in self.paths():
            with self.subTest(fixture=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertRegex(text, r"(?m)^# expect: ")
                rep = ck.check(text, registry=registry())
                self.assertEqual(found(rep), expected_of(text))

    def test_every_probe_is_flagged_and_its_twin_is_not(self):
        twins = [p for p in self.paths() if p.stem.endswith("-declared")]
        self.assertGreaterEqual(len(twins), 19)
        for twin in twins:
            stem = twin.stem[len("flow-"):-len("-declared")]
            with self.subTest(probe=stem):
                text, rep = fixture(stem)
                rid = rule_of(text)
                self.assertIn(rid, ids(rep))
                self.assertNotIn(rid, ids(fixture(f"{stem}-declared")[1]))

    def test_every_rule_has_a_flagged_fixture(self):
        flagged = {rule_of(p.read_text(encoding="utf-8")) for p in self.paths()
                   if not p.stem.endswith("-declared")}
        self.assertEqual(sorted(flagged), list(FLOW_IDS))

    def test_quiet_variants(self):
        for stem, rid in (("unguarded-call-covered", "SGC101"),
                          ("unguarded-call-notify", "SGC101"),
                          ("retry-without-idempotency-read", "SGC111"),
                          ("duplicate-delivery-stage", "SGC112"),
                          ("fanout-tail-block", "SGC165"),
                          ("unhandled-failure-fallback", "SGC201"),
                          ("dead-failure-route-request", "SGC202"),
                          ("dead-failure-route-fallback", "SGC202"),
                          ("unhandled-failure-critical-declared", "SGC202"),
                          ("dead-failure-route-group", "SGC202"),
                          ("unguarded-call-block", "SGC101"),
                          ("unguarded-call-loop", "SGC101"),
                          ("retry-without-idempotency-store", "SGC111"),
                          ("duplicate-delivery-ignored", "SGC112")):
            with self.subTest(fixture=stem):
                self.assertNotIn(rid, ids(fixture(stem)[1]))

    def test_the_fixtures_lint_clean(self):
        lint = _load("sigil_check_flow_suite_lint", "lint.py")
        for path in self.paths():
            with self.subTest(fixture=path.name):
                res = lint.lint(path.read_text(encoding="utf-8"))
                self.assertEqual([d.format() for d in res.diagnostics
                                  if d.severity in ("error", "warn")], [])


# ---------------------------------------------------------------------------
# Tiers inside one rule
# ---------------------------------------------------------------------------

def severities(report, rid: str) -> list:
    return [f.severity for f in report.findings if f.rule.id == rid]


class Tiers(unittest.TestCase):
    def test_an_op_reach_is_binding_an_actor_advisory(self):
        self.assertEqual(severities(run(fixture("unguarded-call")[0], mode="spec"),
                                    "SGC101"), ["error"])
        self.assertEqual(severities(run(fixture("unguarded-call-actor")[0], mode="spec"),
                                    "SGC101"), ["warn"])

    def test_a_guessed_write_drops_a_tier(self):
        guessed = run(fixture("retry-without-idempotency")[0], mode="spec")
        exact = run(fixture("retry-without-idempotency-exact")[0], mode="spec")
        self.assertEqual(severities(guessed, "SGC111"), ["warn"])
        self.assertIn("guessed:", guessed.findings[0].message)
        self.assertEqual(severities(exact, "SGC111"), ["error"])

    def test_a_retrying_consumer_is_binding(self):
        rep = run(fixture("poison-message")[0], mode="spec")
        self.assertEqual(severities(rep, "SGC114"), ["error"])
        rep = run("*<Raw>^1k -> [Parse] : op p.parse() @timeout(1s)\n", mode="spec")
        self.assertEqual(severities(rep, "SGC114"), ["warn"])

    def test_a_consumer_retrying_on_its_feeding_wire_is_binding(self):
        rep = run(fixture("poison-message-overflow")[0], mode="spec")
        self.assertEqual(severities(rep, "SGC114"), ["error"])

    def test_a_read_write_store_flow_drops_a_tier(self):
        rep = run(fixture("retry-without-idempotency-rw")[0], mode="spec")
        self.assertEqual(severities(rep, "SGC111"), ["warn"])
        self.assertIn("guessed: `<->` reads as read-and-write", rep.findings[0].message)

    def test_a_recursive_spawn_is_binding(self):
        self.assertEqual(severities(run(fixture("unbounded-spawn")[0], mode="spec"),
                                    "SGC167"), ["warn"])
        self.assertEqual(severities(run(fixture("unbounded-spawn-recursive")[0],
                                        mode="spec"), "SGC167"), ["error"])

    def test_a_guessed_dual_write_drops_a_tier(self):
        for stem in ("dual-write-stores", "dual-write"):
            with self.subTest(fixture=stem):
                rep = run(fixture(stem)[0], mode="spec")
                self.assertEqual(severities(rep, "SGC113"), ["info"])
                self.assertIn("guessed: `", rep.findings[0].message)
        exact = run("[S] -> |A| : put(x)\n[S] -> |B| : put(x)\n"
                    "|A| @write(S)\n|B| @write(S)\n", mode="spec")
        self.assertEqual(severities(exact, "SGC113"), ["warn"])

    def test_a_guessed_consumer_write_drops_a_tier(self):
        rep = run("[Shop] => *<Order>^1k\n*<Order> -> [Billing]\n"
                  "[Billing] -> *|Ledger| : put({Order})\n", mode="spec")
        hits = [f for f in rep.findings if f.rule.id == "SGC112"]
        self.assertEqual([f.severity for f in hits], ["info"])
        self.assertIn("guessed: `put` reads as a write", hits[0].message)

    def test_a_verbless_store_write_names_its_value(self):
        """A value payload has no verb: the guess names the value, never "``"."""
        rep = run("[Shop] => *<Order>^1k\n*<Order> -> [Billing]\n"
                  "[Billing] -> ~|Count| : ${state.Count} + 1\n", mode="spec")
        hits = [f for f in rep.findings if f.rule.id == "SGC112"]
        self.assertEqual(len(hits), 1)
        self.assertIn("guessed: the value `${state.Count} + 1` reads as a write",
                      hits[0].message)

    def test_no_message_quotes_an_empty_name(self):
        """Every checks fixture and examples.md Example Q (the flagship): no finding
        message carries an empty code span."""
        texts = {p.name: p.read_text(encoding="utf-8")
                 for p in sorted(_FIXTURES.glob("*.sigil"))}
        texts["examples.md:971"] = block_at(_DIR / "examples.md", 971)
        for name, text in texts.items():
            for mode in ("sketch", "spec", "craft"):
                with self.subTest(source=name, mode=mode):
                    rep = ck.check(text, mode=mode, registry=registry())
                    self.assertEqual([f.message for f in rep.findings if "``" in f.message],
                                     [])

    def test_an_implicit_queue_is_a_hint(self):
        rep = run(fixture("unhandled-failure-async")[0], mode="spec")
        self.assertEqual(severities(rep, "SGC161"), ["info"])

    def test_capacity_mismatch_is_never_shown_in_sketch(self):
        rep = run(fixture("capacity-mismatch")[0], mode="sketch")
        self.assertEqual(found(rep), [])


# ---------------------------------------------------------------------------
# Suppression (catalog §1.7): one defect, one finding
# ---------------------------------------------------------------------------

class Suppression(unittest.TestCase):
    def test_unguarded_call_folds_fanout_tail(self):
        rep = fixture("unguarded-call-folds")[1]
        cause = next(f for f in rep.findings if f.rule.id == "SGC101")
        self.assertEqual([f.rule.id for f in cause.also], ["SGC165"])
        self.assertIn("(also: fanout-tail)", cause.message)
        self.assertNotIn("SGC165", ids(rep))

    def test_unguarded_call_folds_held_across_call(self):
        text = "[Judge] -> |Scores| : op db.insert(${out.score})\n"
        w = ("Judge_service", "Scores_store", "->", 0)
        held = probe("held-across-call", "SGC134", 1, scopes=(("call", w),))
        rep = run(text, held)
        cause = next(f for f in rep.findings if f.rule.id == "SGC101")
        self.assertEqual([f.rule.id for f in cause.also], ["SGC134"])
        self.assertNotIn("SGC134", ids(rep))

    def test_a_dual_write_fix_never_asks_for_a_dead_route(self):
        rep = fixture("dual-write")[1]
        (hit,) = [f for f in rep.findings if f.rule.id == "SGC113"]
        self.assertNotIn("`!>`", hit.hit.fix)
        self.assertIn("@inv atomic(|DB|, <OrderPlaced>)", hit.hit.fix)

    def test_poison_message_folds_unhandled_failure(self):
        rep = fixture("poison-message")[1]
        cause = next(f for f in rep.findings if f.rule.id == "SGC114")
        self.assertEqual([f.rule.id for f in cause.also], ["SGC201"])
        self.assertNotIn("SGC201", ids(rep))

    def test_acknowledging_the_cause_covers_the_folded(self):
        text = fixture("unguarded-call-folds")[0].replace(
            "op bank.charge(total)",
            "op bank.charge(total)   # accepts: unguarded-call — the bank answers in 1s")
        rep = ck.check(text, registry=registry())
        self.assertNotIn("SGC101", ids(rep))
        self.assertNotIn("SGC165", ids(rep))
        self.assertIn("SGC101", [f.rule.id for f in rep.acknowledged])

    def test_a_dead_route_carries_its_event_for_orphan_event(self):
        rep = fixture("dead-failure-route")[1]
        dead = next(f for f in rep.findings if f.rule.id == "SGC202")
        self.assertIn(("event", "Failed_event"), dead.hit.scopes)


# ---------------------------------------------------------------------------
# The corpus (catalog Evidence)
# ---------------------------------------------------------------------------

def corpus(path: str) -> str:
    return (_DIR / path).read_text(encoding="utf-8")


def on(report, rid: str) -> list:
    return [f.line for f in report.findings if f.rule.id == rid]


class Corpus(unittest.TestCase):
    def test_examples_md_external_reaches_are_bounded(self):
        """examples.md:552-553 now state `@timeout` and `@fallback` (the catalog's
        former corpus hits for SGC101 and SGC201)."""
        block = block_at(_DIR / "examples.md", 552)
        rep = ck.check(block, mode="spec", registry=registry())
        self.assertIn("op db.insert(${out.score})  @timeout(2s)", block)
        self.assertEqual(on(rep, "SGC101"), [])
        self.assertEqual(on(rep, "SGC201"), [])

    def test_executions_failure_handling(self):
        rep = ck.check(corpus("tests/fixtures/executions.sigil"), registry=registry())
        self.assertEqual(on(rep, "SGC201"), [14, 41])       # E4, E12
        self.assertEqual(on(rep, "SGC101"), [])             # 16, 18, 41 are bounded
        self.assertEqual(on(rep, "SGC122"), [35])           # E11's release
        self.assertEqual(on(rep, "SGC202"), [])
        self.assertEqual(severities(ck.check(corpus("tests/fixtures/executions.sigil"),
                                             mode="spec", registry=registry()),
                                    "SGC111"), ["warn"])     # 16 reaches a `<->`

    def test_coverage_satisfied_lines(self):
        rep = ck.check(corpus("tests/fixtures/coverage.sigil"), mode="spec",
                       registry=registry())
        self.assertNotIn(38, on(rep, "SGC101"))
        self.assertNotIn(39, on(rep, "SGC101"))
        self.assertIn(23, on(rep, "SGC166"))               # `{Cart} !`
        self.assertNotIn(72, on(rep, "SGC114"))             # `!> |DLQ|`
        self.assertEqual(on(rep, "SGC202"), [])             # 141: a block route (B2)

    def test_site_executions_route_under_a_fallback_is_live(self):
        rep = ck.check(corpus("site/examples/05-executions.sigil"), mode="spec",
                       registry=registry())
        self.assertEqual(on(rep, "SGC202"), [])             # Q2: notify, then yield
        self.assertEqual(on(rep, "SGC101"), [])
        self.assertEqual(on(rep, "SGC104"), [11])

    def test_site_checkout_retries_without_idempotency(self):
        rep = ck.check(corpus("site/examples/01-checkout.sigil"), mode="spec",
                       registry=registry())
        self.assertEqual(on(rep, "SGC111"), [8])

    def test_language_examples_give_no_binding_finding(self):
        """Examples 3 and 4 (the catalog §12 calibration rows this module owns)."""
        for line, expected in ((102, {"SGC111", "SGC121", "SGC122", "SGC163", "SGC165"}),
                               (168, {"SGC161", "SGC165"})):
            with self.subTest(example_at=line):
                rep = ck.check(block_at(_DIR / "examples.md", line), mode="spec",
                               registry=registry())
                self.assertEqual([f for f in rep.findings if f.severity == "error"], [])
                self.assertEqual({f.rule.id for f in rep.findings} & set(FLOW_IDS),
                                 expected)


# ---------------------------------------------------------------------------
# The facts
# ---------------------------------------------------------------------------

def facts_of(text: str):
    doc = ck.Doc(textwrap.dedent(text).lstrip("\n"), "craft", 1, frozenset())
    return cf.flow_facts(doc)


class Facts(unittest.TestCase):
    def test_attempts(self):
        self.assertEqual(cf.attempts_of(None), 1)
        self.assertEqual(cf.attempts_of("3"), 4)
        self.assertIsNone(cf.attempts_of("N"))

    def test_a_node_times_n_is_never_a_retry(self):
        facts = facts_of("[A] ×3 -> [B] : write(x)\n")
        (w,) = [w for w in facts.flows if w.src == "A_service"]
        self.assertIsNone(cf.retry_arg(facts, w))

    def test_coverage_is_a_greatest_fixpoint(self):
        facts = facts_of("""
            (U) -> [A] : a() @deadline(2s)
            [A] -> [B] : b()
            [B] -> [C] : c()
            [X] -> [C] : c()
            """)
        covered = cf.covered_callers(facts)
        self.assertIn("A_service", covered)
        self.assertIn("B_service", covered)
        self.assertNotIn("C_service", covered)      # [X] is an uncovered entry

    def test_durations_take_the_worst_member(self):
        facts = facts_of("""
            [A] -> [B] : b() @timeout(5s)
            parallel @all {
              [B] -> [C] : c() @timeout(1s) ×1
              [B] -> [D] : d() @timeout(3s)
            }
            """)
        self.assertEqual(cf.Durations(facts).node(0, "B_service"), 3.0)

    def test_a_route_over_data_is_judged_without_its_own_failure(self):
        """The route makes its guard fail for SGC201 (it counts as handled), but
        SGC202 judges it on what fails without routes: a produced value cannot."""
        facts = facts_of("[A] -> {Report}\n     !> <Failed>\n")
        fl = cf.failures_of(facts)
        self.assertEqual(fl.arriving.get((0, "A_service")),
                         {("call", ("A_service", "Report_data", "->", 0))})
        self.assertEqual(fl.own_arriving.get((0, "A_service")), frozenset())
        self.assertEqual([r.line for r in cf.dead_routes(facts)], [2])

    def test_a_node_route_needs_a_failure_of_its_own(self):
        facts = facts_of("[A] -> {Report}\n[A] !> <Failed>\n")
        self.assertEqual([r.line for r in cf.dead_routes(facts)], [2])
        facts = facts_of("[A] -> (Ext) : op x.get() @timeout(1s)\n[A] !> <Failed>\n")
        self.assertEqual(cf.dead_routes(facts), [])

    def test_a_node_route_on_unwritten_work_declares_it(self):
        """site 04: `[Payments]` writes only its emits, so its own route states
        that its (unwritten) work can fail."""
        facts = facts_of("[Payments] ~> <Paid>\n[Payments] !> <Declined>\n")
        self.assertEqual(cf.dead_routes(facts), [])

    def test_a_route_under_a_self_call_declares_it(self):
        facts = facts_of("[Worker] -> run({Job}) => <ok> !> <fail>\n")
        self.assertEqual(cf.dead_routes(facts), [])

    def test_a_route_under_a_critical_call_is_live(self):
        facts = facts_of("""
            (U) -> [J] : judge()
            [J] -> (Ext) : op x.pay() @timeout(1s) !
                 !> (U) : <Failed>
            """)
        self.assertEqual(cf.dead_routes(facts), [])

    def test_a_critical_call_that_can_fail_escapes(self):
        facts = facts_of("""
            (U) -> [J] : judge()
            [J] -> (Ext) : op x.pay() @timeout(1s) !
            """)
        (esc,) = cf.escapes(facts, cf.failures_of(facts))
        self.assertEqual((esc.root, esc.origin.line), ((0, "U_actor"), 2))

    def test_a_critical_mark_alone_is_no_failure(self):
        facts = facts_of("(U) -> [Api] : {Cart} !\n")
        self.assertEqual(cf.escapes(facts, cf.failures_of(facts)), [])

    def test_coverage_stops_at_an_async_delivery(self):
        facts = facts_of("""
            (U) -> [A] : a() @deadline(2s)
            [A] -> [B] : b()
            [C] ~> [B] : tick()
            *<J> -> [D]
            [A] -> [D] : d()
            """)
        covered = cf.covered_callers(facts)
        self.assertIn("A_service", covered)
        self.assertNotIn("B_service", covered)      # a `~>` task starts there
        self.assertNotIn("D_service", covered)      # so does a stream message

    def test_effects_do_not_depend_on_which_cycle_wire_is_asked_first(self):
        text = "[A] -> [B] : f()\n[B] -> [A] : g()\n[B] -> |S| : put(x)\n"
        for first in (0, 1):
            with self.subTest(first=first):
                facts = facts_of(text)
                calls = [w for w in facts.flows if w.dst in ("A_service", "B_service")]
                order = [calls[first], calls[1 - first]]
                self.assertTrue(all(cf.effect_of(facts, w) is not None for w in order))

    def test_a_read_write_flow_is_a_guessed_write(self):
        facts = facts_of("[F] <-> |Robots| : allowed(${u})\n")
        (w,) = facts.flows
        eff = cf.store_effect(facts, w)
        self.assertEqual(eff.guess, "`<->` reads as read-and-write")

    def test_a_write_through_a_callee_names_its_store(self):
        facts = facts_of("[API] -> [Pay] : charge(t)\n[Pay] -> |Ledger| : insert({Tx})\n")
        w = next(x for x in facts.flows if x.dst == "Pay_service")
        eff = cf.effect_of(facts, w)
        self.assertEqual(eff.store, "Ledger_store")
        self.assertEqual(cf.effect_owners(w, eff), ("Pay_service", "Ledger_store"))

    def test_a_block_deadline_caps_the_block(self):
        facts = facts_of("parallel @all {\n  [A] -> [B] : get(x) @timeout(3s)\n"
                         "} @deadline(1s)\n")
        self.assertEqual(cf.Durations(facts).node(0, "A_service"), 1.0)

    def test_a_block_deadline_bounds_an_unbounded_body(self):
        facts = facts_of("loop @while {Q}.size > 0 {\n  [A] -> (E) : op e.get()\n"
                         "} @deadline(2s)\n")
        self.assertEqual(cf.Durations(facts).node(0, "A_service"), 2.0)
        self.assertEqual(cf.unguarded_calls(facts), [])

    def test_a_policy_reads_the_same_in_either_place(self):
        """MG3: a `!` and its `@timeout` on either side of the arrow halt alike."""
        trailing = "(U) -> [A] : go()\n[A] -> [B] : pay() @timeout(1s) !\n"
        source = "(U) -> [A] : go()\n[A] @timeout(1s) -> [B] : pay() !\n"
        self.assertIn((2, "SGC201"), found(run(trailing)))
        self.assertEqual(found(run(source)), found(run(trailing)))
        facts = facts_of(source)
        w = next(x for x in facts.flows if x.dst == "B_service")
        self.assertTrue(cf.is_halting(facts, w))
        self.assertTrue(cf.fails_alone(facts, cf.failures_of(facts), w))

    def test_dual_write_fixes_only_declare(self):
        for stem in ("dual-write", "dual-write-stores"):
            with self.subTest(fixture=stem):
                (f,) = [f for f in fixture(stem)[1].findings if f.rule.id == "SGC113"]
                self.assertIn("@inv atomic(", f.fix)
                self.assertNotIn("relay", f.fix)
        rule = next(r for r in cf.rules(ck) if r.id == "SGC113")
        self.assertNotIn("relay", rule.fix)

    def test_a_bounded_stream_above_the_spawner_is_a_ceiling(self):
        facts = facts_of("*<Url>^10 -> [Gate] : g()\n[Gate] -> [Crawler] : c()\n"
                         "[Crawler]\n    \\-* [Fetch]\n")
        (sp,) = cf.spawns(facts)
        self.assertTrue(cf.ceiling(facts, sp))

    def test_a_block_route_over_values_is_dead(self):
        facts = facts_of("loop @times 2 {\n  [A] -> {Report}\n}\n     !> <Failed>\n")
        self.assertEqual([r.line for r in cf.dead_routes(facts)], [4])

    def test_a_block_route_over_requests_declares_their_failure(self):
        facts = facts_of("parallel @all {\n  [A] -> [B] : b()\n}\n     !> <Failed>\n")
        self.assertTrue(cf.declares_failure(facts, (0, "A_service"), ("block", 0)))
        self.assertEqual(cf.dead_routes(facts), [])

    def test_a_route_on_a_group_line_is_live(self):
        for text in ("*<E>^1 *> |A| & |B|\n     !> |DLQ|\n",
                     "(U) -> [A] : go()\n[A] *> [B] & [C] : f() ×2\n     !> <Failed>\n"):
            with self.subTest(text=text):
                facts = facts_of(text)
                self.assertEqual(cf.dead_routes(facts), [])


class Determinism(unittest.TestCase):
    def test_byte_identical_across_hash_seeds(self):
        outs = set()
        for seed in ("0", "1", "4242"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            env.pop("SIGIL_DIALECT", None)
            p = subprocess.run([sys.executable, str(_DIR / "check.py"),
                                str(_DIR / "tests" / "fixtures" / "coverage.sigil"),
                                "--mode", "spec", "--json"],
                               capture_output=True, text=True, env=env)
            outs.add(p.stdout)
        self.assertEqual(len(outs), 1)
        self.assertIn("SGC1", next(iter(outs)))


if __name__ == "__main__":
    unittest.main()
