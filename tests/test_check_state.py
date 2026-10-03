"""check_state.py (RFC 0003, P2): the shared-state, state-machine, termination and
structure rules (SGC131–136, 141–148, 151–153, 171–174), the static halves of
SGC204 race and SGC205 ordering-unstated, SGC090's loop-cap cause, SGC003
ack-unused, and the calibration gate over the spec's own examples.

Each rule's evidence is a fixture: tests/fixtures/checks/state-*.sigil, a flagged
design and its declared twin (the catalog's Example), with the expected findings
in a `# expect: LINE:RULE` header. The fixtures run with the core rules and this
module's only, so another module's findings never move them.

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
_CALIBRATION = _FIXTURES / "calibration.md"


def _load(key: str, fname: str):
    spec = importlib.util.spec_from_file_location(key, _DIR / fname)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


ck = _load("sigil_check_state_suite_check", "check.py")
cs = _load("sigil_check_state_suite_state", "check_state.py")


def state_registry(*extra) -> dict:
    """The core rules, this module's, and SGC090 from this module's cause."""
    return ck.build_registry(ck.core_rules() + cs.rules(ck)
                             + [ck.exploration_rule(cs.exploration_causes(ck))] + list(extra))


def probe(name="probe", rid="TST001", tier="binding", lines=(), implies=(), **hit_kw):
    """A rule flagging the given lines."""
    def match(_doc):
        for n in lines:
            yield ck.Hit(n, f"{name} at {n}", f"{name} at {n}?", anchor=("line", n),
                         **hit_kw)
    return ck.Rule(rid, name, tier, ask="Probe?", why="a test rule", fix="nothing",
                   match=match, implies=implies)


def run(text, *extra, mode=None):
    registry = ck.build_registry(ck.core_rules() + cs.rules(ck) + list(extra))
    return ck.check(textwrap.dedent(text).lstrip("\n"), mode=mode, registry=registry)


def check_state(text, mode=None):
    return ck.check(textwrap.dedent(text).lstrip("\n"), mode=mode, registry=state_registry())


def found(report, rule=None) -> list:
    """(line, rule id) of the report's findings (hidden ones too)."""
    return [(f.line, f.rule.id) for f in report.findings
            if rule is None or f.rule.id == rule or f.rule.name == rule]


def stale(report) -> list:
    """(line, message) of every SGC003 finding, hidden ones included."""
    return [(f.line, f.hit.statement) for f in report.findings if f.rule.id == "SGC003"]


def expected_of(path: Path) -> list:
    """The `# expect: LINE:RULE` lines of a fixture's header."""
    text = path.read_text(encoding="utf-8")
    return [(int(m[1]), m[2]) for m in re.finditer(r"^# expect: (\d+):(\w+)$", text, re.M)]


def reported(report) -> list:
    """The rule ids of a report's findings and of those folded into them."""
    return [f.rule.id for f in report.findings] + [a.rule.id for f in report.findings
                                                   for a in f.also]


def fixture(stem: str):
    path = _FIXTURES / f"state-{stem}.sigil"
    return path, ck.check(path.read_text(encoding="utf-8"), registry=state_registry())


# ---------------------------------------------------------------------------
# SGC003 ack-unused
# ---------------------------------------------------------------------------

class Registration(unittest.TestCase):
    TIERS = {
        "SGC003": "advisory", "SGC131": "advisory", "SGC132": "binding",
        "SGC133": "advisory", "SGC134": "advisory", "SGC135": "advisory",
        "SGC136": "hint", "SGC141": "binding", "SGC142": "hint", "SGC143": "binding",
        "SGC144": "advisory", "SGC145": "hint", "SGC146": "hint", "SGC147": "advisory",
        "SGC148": "advisory", "SGC151": "advisory", "SGC152": "advisory",
        "SGC153": "hint", "SGC171": "advisory", "SGC172": "advisory",
        "SGC173": "binding", "SGC174": "hint", "SGC204": "binding", "SGC205": "advisory"}

    def test_rule_ids_names_and_tiers_follow_the_catalog(self):
        rules = {r.id: r for r in cs.rules(ck)}
        self.assertEqual({rid: r.tier for rid, r in rules.items()}, self.TIERS)
        for rid, r in rules.items():
            self.assertEqual(r.name, ck.CORE_NAMES[rid])

    def test_ack_unused_shape(self):
        rule = next(r for r in cs.rules(ck) if r.id == "SGC003")
        self.assertTrue(rule.after_acks)
        self.assertFalse(rule.acknowledgeable)

    def test_join_the_default_registry_with_the_loop_cause(self):
        registry = ck.default_registry()
        self.assertLessEqual(set(self.TIERS), set(registry))
        self.assertIn("SGC090", registry)

    def test_suppression_table_is_data(self):
        rules = {r.id: r for r in cs.rules(ck)}
        self.assertIn(("race", "store"), rules["SGC131"].implies)
        self.assertIn(("lost-update", "store"), rules["SGC131"].implies)
        self.assertIn(("lost-update", "node_store"), rules["SGC204"].implies)
        self.assertEqual({n for n, _s in rules["SGC146"].implies},
                         {"event-ignored", "ordering-unstated", "wait-without-timeout"})


class Stale(unittest.TestCase):
    def test_covering_nothing_is_stale(self):
        rep = run("""
            #!craft
            [A] -> [B] : f()   # accepts: probe — nothing flags this
            [A] -> [C] : g()
            """, probe(lines=(3,)))
        self.assertEqual(stale(rep), [
            (2, "the acknowledgement covers no `probe` finding on its line")])
        self.assertEqual(rep.findings[0].severity, "warn")

    def test_covering_a_finding_is_used(self):
        rep = run("""
            #!spec
            [A] -> [B] : f()   # accepts: probe — the probe flags this
            """, probe(lines=(2,)))
        self.assertEqual(stale(rep), [])
        self.assertEqual([f.line for f in rep.acknowledged], [2])

    def test_each_stale_name_is_reported(self):
        rep = run("""
            #!craft
            [A] -> [B] : f()   # accepts: probe, other — only the probe flags this
            """, probe(lines=(2,)), probe("other", "TST002"))
        self.assertEqual(stale(rep), [
            (2, "the acknowledgement covers no `other` finding on its line")])

    def test_a_redundant_document_acknowledgement_is_stale(self):
        rep = run("""
            #!craft
            # accepts: probe — every probe finding

            [A] -> [B] : f()   # accepts: probe — this one in particular
            """, probe(lines=(4,)))
        self.assertEqual(stale(rep), [
            (2, "the acknowledgement covers no `probe` finding in the document")])

    def test_a_block_acknowledgement_names_its_block(self):
        rep = run("""
            #!craft
            [A] {   # accepts: probe — nothing in here
              [A] -> [B] : f()
            }
            """, probe())
        self.assertEqual([m for _, m in stale(rep)],
                         ["the acknowledgement covers no `probe` finding in its block"])

    def test_the_finding_is_anchored_on_the_comment(self):
        rep = run("#!craft\n[A] -> [B] : f()   # accepts: probe — none\n", probe())
        (f,) = rep.findings
        self.assertEqual(f.hit.anchor, ("comment", 2))


class LeftToOtherRules(unittest.TestCase):
    def test_a_void_acknowledgement_is_sgc002_only(self):
        rep = run("#!craft\n[A] -> [B] : f()   # accepts: probe\n", probe())
        self.assertEqual([f.rule.id for f in rep.findings], ["SGC002"])

    def test_an_unknown_name_is_sgc001_only(self):
        rep = run("#!craft\n[A] -> [B] : f()   # accepts: prbe — typo\n", probe())
        self.assertEqual([f.rule.id for f in rep.findings], ["SGC001"])

    def test_a_meta_name_is_sgc001_only(self):
        rep = run("#!craft\n[A] -> [B] : f()   # accepts: ack-unused — keep\n")
        self.assertEqual([f.rule.id for f in rep.findings], ["SGC001"])

    def test_sgc003_itself_is_never_acknowledged(self):
        rep = run("""
            #!craft
            # accepts: probe — stale on purpose

            [A] -> [B] : f()
            """, probe())
        self.assertEqual([f.rule.id for f in rep.findings], ["SGC003"])
        self.assertEqual(rep.acknowledged, [])


class NeverFlipsOnModeOrK(unittest.TestCase):
    TEXT = "[A] -> [B] : f()   # accepts: probe — known\n"

    def test_a_hidden_sketch_finding_counts(self):
        rep = run(self.TEXT, probe(lines=(1,)), mode="sketch")
        self.assertEqual(stale(rep), [])
        self.assertEqual([f.line for f in rep.acknowledged], [1])

    def test_an_unemitted_hint_counts(self):
        rep = run(self.TEXT, probe(tier="hint", lines=(1,)), mode="sketch")
        self.assertEqual(stale(rep), [])

    def test_a_folded_finding_counts(self):
        cause = probe("cause", "TST002", lines=(1,), implies=(("probe", "line"),))
        rep = run(self.TEXT, cause, probe(lines=(1,)), mode="craft")
        self.assertEqual(stale(rep), [])

    def test_a_k1_trace_witness_counts(self):
        rep = run(self.TEXT, probe(lines=(1,), trace=True, k=1), mode="craft")
        self.assertEqual(stale(rep), [])

    def test_a_k2_only_witness_is_judged_the_same_in_every_mode(self):
        for mode in ("craft", "spec"):
            with self.subTest(mode=mode):
                rep = run(self.TEXT, probe(lines=(1,), trace=True, k=2), mode=mode)
                self.assertEqual([line for line, _ in stale(rep)], [1])

    def test_a_stale_acknowledgement_is_hidden_in_sketch(self):
        rep = run(self.TEXT, probe(), mode="sketch")
        (f,) = rep.findings
        self.assertEqual((f.rule.id, f.severity, f.hidden), ("SGC003", "info", True))


class AckUnusedFixtures(unittest.TestCase):
    PROBES = (probe(lines=(10,)), probe("other-probe", "TST002"))

    def check_fixture(self, fname: str, probes: tuple):
        path = _FIXTURES / fname
        rep = ck.check(path.read_text(encoding="utf-8"),
                       registry=ck.build_registry(ck.core_rules() + cs.rules(ck)
                                                  + list(probes)))
        self.assertEqual([(f.line, f.rule.id) for f in rep.findings], expected_of(path))

    def test_flagged(self):
        self.check_fixture("state-ack-unused.sigil", self.PROBES)

    def test_declared(self):
        self.check_fixture("state-ack-unused-declared.sigil", (probe(lines=(6,)),))


# ---------------------------------------------------------------------------
# The rules' fixtures: each probe flagged, each declared twin clean of it
# ---------------------------------------------------------------------------

RULE_FIXTURES = sorted(p for p in _FIXTURES.glob("state-*.sigil")
                       if not p.name.startswith("state-ack-unused"))


class Fixtures(unittest.TestCase):
    def test_every_fixture_gives_its_expected_findings(self):
        self.assertTrue(RULE_FIXTURES)
        for path in RULE_FIXTURES:
            with self.subTest(fixture=path.name):
                rep = ck.check(path.read_text(encoding="utf-8"), registry=state_registry())
                self.assertEqual(found(rep), expected_of(path))

    def test_every_rule_has_a_flagged_probe_and_a_declared_twin(self):
        names = {r.name: r.id for r in cs.rules(ck)} | {"exploration-incomplete": "SGC090"}
        del names["ack-unused"]
        for name, rid in sorted(names.items()):
            with self.subTest(rule=name):
                flagged, ok = fixture(name)[1], fixture(f"{name}-declared")[1]
                self.assertIn(rid, reported(flagged))
                self.assertNotIn(rid, reported(ok))

    def test_a_clean_twin_is_quiet_for_its_rule(self):
        quiet = {"race-one-caller": "SGC204", "unreachable-state-no-start": "SGC141",
                 "ambiguous-transition-wildcard-last": "SGC143",
                 "ambiguous-transition-invs": "SGC143", "no-exit-self-loop": "SGC144",
                 "no-exit-retention": "SGC144", "async-cycle-scheduled": "SGC152",
                 "shared-data-order-chained": "SGC136", "unbounded-loop-pop": "SGC153",
                 "unbounded-recursion-exit": "SGC151",
                 "shared-writable-store-unknown-declared": "SGC131",
                 "race-from-data": "SGC204", "expansion-escape-outer-bound": "SGC172",
                 "expansion-escape-outer-mod": "SGC171"}
        for stem, rid in quiet.items():
            with self.subTest(fixture=stem):
                self.assertNotIn(rid, [r for _l, r in found(fixture(stem)[1])])

    def test_the_fixtures_lint_clean(self):
        lint = ck._kit().lint
        for path in RULE_FIXTURES:
            with self.subTest(fixture=path.name):
                errors = [d.format() for d in lint.lint(path.read_text(encoding="utf-8"))
                          .diagnostics if d.severity == "error"]
                self.assertEqual(errors, [])


def with_flow(text, mode=None):
    """This module's rules beside check_flow's, so cross-module folds run."""
    cf = _load("sigil_check_state_suite_flow", "check_flow.py")
    registry = state_registry(*cf.rules(ck))
    return ck.check(textwrap.dedent(text).lstrip("\n"), mode=mode, registry=registry)


def folded(report, rid: str) -> list:
    """The rule ids folded into the report's `rid` findings."""
    return sorted(a.rule.id for f in report.findings if f.rule.id == rid for a in f.also)


class Suppression(unittest.TestCase):
    """Catalog §1.7: one defect, one finding."""

    def test_131_folds_race_and_lost_update_on_its_store(self):
        rep = fixture("shared-writable-store-folds")[1]
        self.assertEqual(found(rep, "SGC131"), [(7, "SGC131")])
        self.assertEqual(sorted(set(folded(rep, "SGC131"))), ["SGC133", "SGC204"])
        self.assertEqual(found(rep, "SGC204") + found(rep, "SGC133"), [])

    def test_204_folds_lost_update_on_its_node_and_store(self):
        rep = fixture("race-folds")[1]
        self.assertEqual(folded(rep, "SGC204"), ["SGC133"])

    def test_146_case_2_folds_ordering_and_waits_on_its_machine(self):
        rep = fixture("undriven-transition-folds")[1]
        self.assertEqual(sorted(set(folded(rep, "SGC146"))), ["SGC147", "SGC205"])
        self.assertEqual(found(rep, "SGC147") + found(rep, "SGC205"), [])

    def test_a_per_transition_146_folds_the_wait_on_its_source_state_only(self):
        rep = check_state("""
            #!craft
            (Bank) ~> <Paid>
            state {Order} {
              +    -<Placed>-> Open
              Open -<Paid>->   Settled
              Open -<Void>->   Gone
            }
            (Shop) ~> <Placed>
            """)
        self.assertEqual(found(rep, "SGC147"), [])
        self.assertEqual(folded(rep, "SGC146"), ["SGC147"])

    def test_134_hits_carry_their_call_scope_for_101(self):
        rep = fixture("held-across-call")[1]
        hits = [f.hit for f in rep.findings if f.rule.id == "SGC134"]
        self.assertEqual([dict(h.scopes).get("call") for h in hits],
                         [h.anchor[1] for h in hits])
        self.assertEqual(len(hits), 1)

    def test_an_unbounded_call_in_an_owns_region_is_101_only(self):
        rep = with_flow("""
            #!craft
            [H] @owns |Conn| {
              [H] -> (Bank) : op bank.check() ×3
            }
            """)
        self.assertEqual(found(rep, "SGC134"), [])
        self.assertEqual(found(rep, "SGC101"), [(3, "SGC101")])

    def test_a_route_rule_at_the_event_scope_folds_the_orphan_event(self):
        # SGC202 implies ("orphan-event", "event") and scopes its Hit by the route's
        # target event; a probe with that contract stands in for check_flow here.
        route = probe("dead-route", "TST202", lines=(3,), implies=(("orphan-event", "event"),),
                      scopes=(("event", "Failed_event"),))
        rep = run("""
            #!craft
            [A] -> {Report}
                 !> <Failed>
            """, route)
        self.assertEqual(found(rep, "SGC145"), [])
        self.assertEqual(folded(rep, "TST202"), ["SGC145"])

    def test_acknowledging_the_cause_covers_what_it_folds(self):
        rep = check_state("""
            #!spec
            [A] -> |Doc| : put({Doc})   # accepts: shared-writable-store — a test
            [B] -> |Doc| : put({Doc})
            """)
        self.assertEqual(rep.findings, [])
        self.assertEqual([f.rule.id for f in rep.acknowledged], ["SGC131"])


class Severity(unittest.TestCase):
    def test_146_case_2_is_advisory_and_the_base_case_a_hint(self):
        case2 = check_state("#!spec\nstate {Job} {\n  + -<submit>-> Open\n}\n")
        base = check_state("#!spec\nstate {Job} {\n  Open -<done>-> Closed\n}\n")
        self.assertEqual([f.severity for f in case2.findings], ["warn"])
        self.assertEqual([f.severity for f in base.findings], ["info"])

    def test_205_static_is_a_guess_one_tier_down(self):
        rep = fixture("ordering-unstated")[1]
        (f,) = [f for f in rep.findings if f.rule.id == "SGC205"]
        self.assertEqual((f.tier, f.hit.guess != ""), ("hint", True))

    def test_binding_rules_are_errors_in_spec(self):
        for stem, rid in (("unreachable-state", "SGC141"), ("lock-order-cycle", "SGC173"),
                          ("ambiguous-transition", "SGC143")):
            with self.subTest(rule=rid):
                path = _FIXTURES / f"state-{stem}.sigil"
                rep = ck.check(path.read_text(encoding="utf-8"), mode="spec",
                               registry=state_registry())
                self.assertEqual({f.severity for f in rep.findings if f.rule.id == rid},
                                 {"error"})

    def test_a_guessed_write_drops_a_binding_race_to_advisory(self):
        rep = fixture("race-read")[1]
        (f,) = [f for f in rep.findings if f.rule.id == "SGC204"]
        self.assertEqual(f.tier, "advisory")

    def test_an_undeclared_rw_wire_is_a_guessed_write(self):
        """Catalog §1.4 steps 4–5: an undeclared `<->` reads as read-and-write by
        guess, so its race drops a tier."""
        text = """
            #!spec
            (Alice) -> [Handler] : get()
            (Bob)×N -> [Handler] : get()
            [Handler] <-> |Cache|
            """
        (f,) = [f for f in check_state(text).findings if f.rule.id == "SGC204"]
        self.assertEqual((f.tier, f.hit.guess != ""), ("advisory", True))

    def test_a_declaration_inside_an_expansion_declares_the_node(self):
        """Every occurrence of a node declares it (the same fact as
        check_flow.node_mods): `@inv` and `×N` written inside `:= { … }`."""
        doc = ck.Doc(textwrap.dedent("""
            [Parser] -> [Walk] : run(d)
            [Parser] := {
              [Walk]×3 @inv depth <= 32
            }
            """).lstrip("\n"), "craft", 1, frozenset())
        facts = cs.Facts(doc)
        self.assertIn("depth", facts.heads("Walk_service"))
        self.assertTrue(facts.counted("Walk_service"))

    def test_a_declared_write_keeps_the_race_binding(self):
        rep = check_state("""
            #!spec
            (Alice) -> [Editor] : save()
            (Bob) -> [Viewer] : show()
            |Doc| @write(Editor) @read(Viewer)
            [Editor] -> |Doc| : put({Doc})
            [Viewer] -> |Doc| : get() => {Doc}
            """)
        self.assertEqual([(f.rule.id, f.severity) for f in rep.findings], [])
        shared = check_state("""
            #!spec
            (Alice) -> [Editor] : save()
            (Bob)×N -> [Viewer] : show()
            |Doc| @write(Editor, Viewer)
            [Editor] -> |Doc| : put({Doc})
            [Viewer] -> |Doc| : put({Doc})
            """)
        self.assertEqual([(f.rule.id, f.severity) for f in shared.findings],
                         [("SGC131", "warn")])
        self.assertEqual(sorted(set(folded(shared, "SGC131"))), ["SGC204"])
        self.assertTrue(all(a.severity == "error" for f in shared.findings for a in f.also))


class LoopCap(unittest.TestCase):
    """SGC090's static cause: a reachable loop capped below its `@times N`."""

    def test_acknowledged_on_the_loop_line_only(self):
        rep = fixture("exploration-incomplete-declared")[1]
        self.assertEqual([f.rule.id for f in rep.acknowledged], ["SGC090"])
        whole = check_state("""
            #!craft
            # accepts: exploration-incomplete — the document says so

            (User) -> [Batch] : run()
            loop @times 5 {
              [Batch] -> |Q| : push({Item})
            }
            """)
        self.assertEqual(found(whole, "SGC090"), [(5, "SGC090")])

    def test_the_message_prints_the_limit(self):
        rep = fixture("exploration-incomplete")[1]
        (f,) = rep.findings
        self.assertIn("iterations=2", f.message)

    def test_a_loop_within_the_limit_is_quiet(self):
        rep = check_state("#!craft\n(U) -> [B] : run()\nloop @times 2 {\n  [B] -> |Q| : "
                          "push({I})\n}\n")
        self.assertEqual(found(rep, "SGC090"), [])


# ---------------------------------------------------------------------------
# The corpus: the catalog's evidence lines
# ---------------------------------------------------------------------------

def md_blocks(path: Path):
    """(first content line, block text) of every Sigil block in a markdown file."""
    text = path.read_text(encoding="utf-8")
    for m in re.finditer(r"^```([a-z]*)\n(.*?)^```", text, re.S | re.M):
        if m.group(1) != "text":
            yield text[:m.start()].count("\n") + 2, m.group(2)


def worked_examples():
    """language.md's worked examples: the blocks of its "Worked examples" section."""
    text = (_DIR / "language.md").read_text(encoding="utf-8")
    lo = text[:text.index("## Worked examples")].count("\n")
    hi = text[:text.index("## Common pitfalls")].count("\n")
    return [(n, b) for n, b in md_blocks(_DIR / "language.md") if lo < n < hi]


def block_at(path: Path, line: int) -> str:
    """The markdown block holding `line`."""
    for start, block in md_blocks(path):
        if start <= line < start + len(block.splitlines()):
            return block
    raise LookupError(f"{path.name}:{line} is in no block")


def corpus_findings(path: Path, line: int, registry=None) -> list:
    """(absolute line, rule name) of a corpus block checked as `#!spec`."""
    for start, block in md_blocks(path):
        if start <= line < start + len(block.splitlines()):
            rep = ck.check(block, mode="spec", registry=registry or state_registry())
            return [(start + f.line - 1, f.rule.name) for f in rep.findings]
    raise LookupError(line)


class Corpus(unittest.TestCase):
    EX = _DIR / "examples.md"

    def test_permission_examples_stay_clean_of_undeclared_access(self):
        for start, block in md_blocks(self.EX):
            if 805 <= start <= 875:
                with self.subTest(block=start):
                    rep = ck.check(block, mode="spec", registry=state_registry())
                    self.assertEqual(found(rep, "SGC132"), [])

    def test_shared_with_a_writer_list_states_no_resolution(self):
        names = [n for _l, n in corpus_findings(self.EX, self._line("|Shared|"))]
        self.assertIn("shared-writable-store", names)

    def test_example_5_asks_what_drives_the_job_and_about_late_cancels(self):
        (_n, block), = [b for b in worked_examples() if "state {Job}" in b[1]]
        rep = ck.check(block, mode="spec", registry=state_registry())
        names = [f.rule.name for f in rep.findings]
        self.assertIn("undriven-transition", names)
        self.assertIn("wildcard-leaves-terminal", names)
        self.assertNotIn("dead-end-state", names)
        (driver,) = [f for f in rep.findings if f.rule.name == "undriven-transition"]
        self.assertEqual(driver.severity, "warn")

    def test_example_2_unauthorized_has_no_receiver(self):
        (_n, block), = [b for b in worked_examples() if "<Unauthorized>" in b[1]]
        rep = ck.check(block, mode="spec", registry=state_registry())
        self.assertEqual([(f.rule.name, f.severity) for f in rep.findings],
                         [("orphan-event", "warn")])

    def test_example_6_states_the_zoom_dependency(self):
        (_n, block), = [b for b in worked_examples() if "[Core] := {" in b[1]]
        rep = ck.check(block, mode="spec", registry=state_registry())
        self.assertNotIn("expansion-escape", [f.rule.name for f in rep.findings])

    def _line(self, needle: str) -> int:
        for n, text in enumerate(self.EX.read_text(encoding="utf-8").splitlines(), 1):
            if needle in text:
                return n
        raise LookupError(needle)


class Determinism(unittest.TestCase):
    def test_byte_identical_across_hash_seeds(self):
        path = _DIR / "tests" / "fixtures" / "coverage.sigil"
        outs = set()
        for seed in ("0", "1", "4242"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            env.pop("SIGIL_DIALECT", None)
            p = subprocess.run([sys.executable, str(_DIR / "check.py"), str(path),
                                "--mode", "spec", "--json"],
                               capture_output=True, text=True, env=env)
            outs.add(p.stdout)
        self.assertEqual(len(outs), 1)


# ---------------------------------------------------------------------------
# The calibration gate (catalog §12): the spec's own examples under `#!spec`
# ---------------------------------------------------------------------------

_ENTRY_RE = re.compile(r"^- (?P<file>\S+) · (?P<rule>[a-z-]+) · (?P<sev>error|warn|info) · "
                       r"`(?P<text>.*)`$")
_DISP_RE = re.compile(r"^  (?P<disp>accepted|noted|open) — (?P<reason>\S.*)$")


def calibration_entries() -> list:
    """(file, rule name, severity, source line, disposition, reason) recorded in
    calibration.md."""
    lines = _CALIBRATION.read_text(encoding="utf-8").splitlines()
    out = []
    for i, line in enumerate(lines):
        m = _ENTRY_RE.match(line)
        if not m:
            continue
        d = _DISP_RE.match(lines[i + 1]) if i + 1 < len(lines) else None
        out.append((m["file"], m["rule"], m["sev"], m["text"],
                    d["disp"] if d else "", d["reason"] if d else ""))
    return out


def calibration_corpus():
    """(file name, block) of every block the gate runs."""
    for _n, block in worked_examples():
        yield "language.md", block
    for _n, block in md_blocks(_DIR / "examples.md"):
        yield "examples.md", block


def calibration_run() -> list:
    """(file, rule name, severity, source line) of every finding the default
    registry (every rule module present) gives on the corpus as `#!spec`."""
    out = []
    for fname, block in calibration_corpus():
        lines = block.splitlines()
        for f in ck.check(block, mode="spec").findings:
            out.append((fname, f.rule.name, f.severity, lines[f.line - 1].strip()))
    return out


class Calibration(unittest.TestCase):
    def test_the_record_matches_the_run(self):
        recorded = sorted(e[:4] for e in calibration_entries())
        self.assertEqual(sorted(calibration_run()), recorded,
                         "a finding on the spec's examples changed: review it and update "
                         "tests/fixtures/checks/calibration.md")

    def test_every_entry_has_its_disposition(self):
        for entry in calibration_entries():
            fname, rule, sev, text, disp, _reason = entry
            with self.subTest(entry=entry[:4]):
                want = {"error": ("open",), "warn": ("accepted", "open"),
                        "info": ("noted", "accepted")}[sev]
                self.assertIn(disp, want)

    def test_no_binding_finding_from_this_module(self):
        mine = {r.name for r in cs.rules(ck)}
        self.assertEqual([e for e in calibration_run() if e[2] == "error" and e[1] in mine],
                         [])


if __name__ == "__main__":
    unittest.main()
