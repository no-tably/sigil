"""check.py core (RFC 0003, P1): the rule registry, the finding record, tiers ×
modes (with the guess downgrade and the deviation cap), acknowledgements and their
anchoring (catalog §10.1), folding (§1.7), deterministic output, the CLI, and the
meta rules SGC001 ack-unknown-rule, SGC002 ack-without-reason and SGC004
policy-in-prose (over scene.call_policy), the SGC090 cause hook, and the dialect
rule pack (rules, read verbs, policy words).

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]


def _load_check():
    key = "sigil_check_under_test"
    spec = importlib.util.spec_from_file_location(key, _DIR / "check.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


ck = _load_check()


def doc(text: str) -> str:
    return textwrap.dedent(text).lstrip("\n")


def probe_rule(rid="TST001", name="probe", tier="binding", lines=None, **hit_kw):
    """A rule that flags every statement line (or the given lines)."""
    def match(d):
        for n in sorted(d.layout.statements if lines is None else lines):
            yield ck.Hit(n, f"probe at {n}", f"Probe at {n}?", anchor=("line", n), **hit_kw)
    return ck.Rule(rid, name, tier, ask="Probe?", why="a test rule", fix="nothing",
                   match=match)


def with_rules(*extra):
    return ck.build_registry(ck.core_rules() + list(extra))


def run(text, *extra, mode=None, k=None):
    return ck.check(doc(text), mode=mode, k=k, registry=with_rules(*extra))


def lines_of(findings, name=None):
    return sorted(f.line for f in findings if name is None or f.rule.name == name)


# ---------------------------------------------------------------------------
# Acknowledgement grammar
# ---------------------------------------------------------------------------

class AckGrammar(unittest.TestCase):
    known = frozenset({"retry-without-idempotency", "unguarded-call"})

    def test_separators(self):
        for text in ("accepts: unguarded-call — the db is local",
                     "accepts: unguarded-call -- the db is local",
                     "accepts: unguarded-call - the db is local",
                     "accepts: unguarded-call—the db is local"):
            with self.subTest(text=text):
                self.assertEqual(ck.parse_ack(text, self.known),
                                 (("unguarded-call",), "the db is local"))

    def test_several_names(self):
        self.assertEqual(
            ck.parse_ack("accepts: unguarded-call, retry-without-idempotency — r", self.known),
            (("unguarded-call", "retry-without-idempotency"), "r"))

    def test_prose_is_not_an_ack(self):
        for text in ("accepts: any JSON body", "accepts: Everything", "accepts:",
                     "this accepts: unguarded-call — r", "accepts: everything",
                     "= unguarded-call — reserved marker, acknowledges nothing yet"):
            with self.subTest(text=text):
                self.assertIsNone(ck.parse_ack(text, self.known))

    def test_missing_reason(self):
        for text in ("accepts: retry-without-idempotency",
                     "accepts: retry-without-idempotency —",
                     "accepts: retry-without-idempoten",     # a kebab compound: an attempt
                     "accepts: unguarded-call --   "):
            with self.subTest(text=text):
                self.assertEqual(ck.parse_ack(text, self.known)[1], "")


# ---------------------------------------------------------------------------
# Anchoring (catalog §10.1): each row a case
# ---------------------------------------------------------------------------

ANCHORING = [
    ("trailing on a line", """
        #!spec
        [A] -> [B] : f()
        [A] -> [C] : g()   # accepts: probe — trailing
        [A] -> [D] : h()
        """, [3]),
    ("own line directly above a statement", """
        #!spec
        [A] -> [B] : f()
        # accepts: probe — above
        [A] -> [C] : g()
        [A] -> [D] : h()
        """, [4]),
    ("two own lines above a statement", """
        #!spec
        [A] -> [B] : f()
        # some prose about the call
        # accepts: probe — above, after prose
        [A] -> [C] : g()
        """, [5]),
    ("own line above a block header", """
        #!spec
        [A] -> [B] : f()
        # accepts: probe — the whole block
        parallel @all {
          [A] -> [C] : g()
          [A] -> [D] : h()
        }
        [A] -> [E] : k()
        """, [4, 5, 6, 7]),
    ("trailing on a block header", """
        #!spec
        [A] -> [B] : f()
        loop @times 3 {   # accepts: probe — the whole loop
          [A] -> [C] : g()
        }
        [A] -> [E] : k()
        """, [3, 4, 5]),
    ("trailing on a closing brace", """
        #!spec
        [A] -> [B] : f()
        parallel @all {
          [A] -> [C] : g()
        }   # accepts: probe — the whole block
        [A] -> [E] : k()
        """, [3, 4, 5]),
    ("nested block: the outer header covers the inner block", """
        #!spec
        # accepts: probe — outer
        parallel @all {
          loop @times 2 {
            [A] -> [C] : g()
          }
        }
        [A] -> [E] : k()
        """, [3, 4, 5, 6, 7]),
    ("inside a state body, per line", """
        #!spec
        [A] -> [B] : f()
        state {Order} {
          + -<Go>-> Open   # accepts: probe — this transition
          Open -<Done>-> $
        }
        """, [4]),
    ("above a state block", """
        #!spec
        [A] -> [B] : f()
        # accepts: probe — the machine
        state {Order} {
          + -<Go>-> Open
          Open -<Done>-> $
        }
        """, [4, 5, 6, 7]),
    ("inside an expansion, per line", """
        #!spec
        [A] -> [B] : f()
        Pay := {
          [P] -> [Q] : charge()
          [Q] -> [R] : settle()   # accepts: probe — settle
        }
        """, [5]),
    ("document scope", """
        #!spec
        # accepts: probe — the whole design

        [A] -> [B] : f()
        parallel @all {
          [A] -> [C] : g()
        }
        """, [4, 5, 6, 7]),
    ("directly above the first statement is not document scope", """
        #!spec
        # accepts: probe — only the first line
        [A] -> [B] : f()
        [A] -> [C] : g()
        """, [3]),
    ("own line followed by a blank line mid-document covers nothing", """
        #!spec
        [A] -> [B] : f()
        # accepts: probe — floating

        [A] -> [C] : g()
        """, []),
]


class Anchoring(unittest.TestCase):
    def test_table(self):
        for label, text, covered in ANCHORING:
            with self.subTest(label):
                rep = run(text, probe_rule())
                self.assertEqual(lines_of(rep.acknowledged, "probe"), covered)
                self.assertFalse(set(lines_of(rep.findings, "probe")) & set(covered))
                self.assertEqual(lines_of(rep.findings, "ack-without-reason"), [])
                self.assertEqual(lines_of(rep.findings, "ack-unknown-rule"), [])

    def test_document_scope_is_tagged(self):
        rep = run(ANCHORING[10][1], probe_rule())
        self.assertTrue(all(f.ack.document for f in rep.acknowledged))
        self.assertIn("(document-wide)", ck.format_lines(rep)[-1])

    def test_ack_names_its_rule_only(self):
        rep = run("""
            #!spec
            [A] -> [B] : f()   # accepts: probe — only the probe
            """, probe_rule(), probe_rule("TST002", "other-probe"))
        self.assertEqual(lines_of(rep.acknowledged), [2])
        self.assertEqual([f.rule.name for f in rep.findings], ["other-probe"])

    def test_acknowledged_line_carries_the_reason(self):
        rep = run("""
            #!craft
            [A] -> [B] : f()   # accepts: probe — charge is an upsert
            """, probe_rule())
        self.assertEqual(ck.format_lines(rep),
                         ["accepted:2:TST001: probe: charge is an upsert"])
        self.assertEqual(rep.exit_code(), 0)


# ---------------------------------------------------------------------------
# Meta rules
# ---------------------------------------------------------------------------

class MetaRules(unittest.TestCase):
    def test_prose_accepts_is_not_an_ack(self):
        rep = run("""
            #!spec
            [API] -> [Svc] : post({Body})   # accepts: any JSON body
            """)
        self.assertEqual(rep.findings, [])
        self.assertEqual(rep.acknowledged, [])

    def test_typo_gives_sgc001_with_suggestion(self):
        # the catalog's flagged example
        rep = run("""
            #!spec
            [API] -> [Payments] : charge(total) ×3 @timeout(2s)   # accepts: retry-without-idempotence — charge is an upsert on order_id
            """)
        (f,) = rep.findings
        self.assertEqual((f.rule.id, f.severity, f.line), ("SGC001", "error", 2))
        self.assertIn("Did you mean `retry-without-idempotency`?", f.message)

    def test_declared_twin_is_clean(self):
        rep = run("""
            #!spec
            [API] -> [Payments] : charge(total) ×3 @timeout(2s)   # accepts: retry-without-idempotency — charge is an upsert on order_id
            """)
        self.assertEqual(rep.findings, [])

    def test_sgc001_warns_even_in_sketch(self):
        rep = run("""
            [API] -> [Payments] : charge(total)   # accepts: retry-without-idempotence — r
            """)
        self.assertEqual(rep.mode, "sketch")
        self.assertEqual([(f.rule.id, f.severity, f.hidden) for f in rep.findings],
                         [("SGC001", "warn", False)])

    def test_sgc001_asks_in_craft(self):
        rep = run("""
            #!craft
            [A] -> [B] : f()   # accepts: retry-without-idempotence — r
            """)
        self.assertEqual(rep.findings[0].message,
                         "No rule is named `retry-without-idempotence`. "
                         "Did you mean `retry-without-idempotency`?")

    def test_unknown_name_far_from_any(self):
        rep = run("""
            #!spec
            [A] -> [B] : f()   # accepts: zzzz-qqqq-wwww — r
            """)
        self.assertNotIn("Did you mean", rep.findings[0].message)

    def test_names_a_rule_not_yet_implemented(self):
        rep = run("""
            #!spec
            [A] -> [B] : f()   # accepts: race — two writers by design
            """)
        self.assertEqual(rep.findings, [])

    def test_meta_rules_cannot_be_acknowledged(self):
        rep = run("""
            #!spec
            [Checkout] -> [Payments] : charge(total)   # accepts: ack-without-reason — because
            """)
        self.assertEqual([(f.rule.id, f.line) for f in rep.findings], [("SGC001", 2)])
        self.assertIn("cannot be acknowledged", rep.findings[0].message)

    def test_policy_in_prose_cannot_be_acknowledged(self):
        # writing the modifier is the fix (catalog §5): the ack is an SGC001 and
        # the SGC004 hint stands
        rep = run("""
            #!spec
            # accepts: policy-in-prose — prose on purpose
            [Checkout] -> [Payments] : charge(total)   # 3 retries
            """)
        self.assertEqual(sorted((f.rule.id, f.line) for f in rep.findings),
                         [("SGC001", 2), ("SGC004", 3)])
        sgc001 = next(f for f in rep.findings if f.rule.id == "SGC001")
        self.assertIn("`policy-in-prose` cannot be acknowledged", sgc001.message)
        self.assertEqual(rep.acknowledged, [])

    def test_no_reason_voids_the_ack(self):
        # the catalog's flagged example: the finding stands
        rep = run("""
            #!spec
            [API] -> [Payments] : charge(total) ×3 @timeout(2s)   # accepts: probe
            """, probe_rule())
        self.assertEqual([(f.rule.id, f.line) for f in rep.findings],
                         [("SGC002", 2), ("TST001", 2)])
        self.assertEqual(rep.acknowledged, [])
        self.assertEqual(rep.findings[0].severity, "error")

    def test_sgc002_asks_why(self):
        rep = run("""
            #!craft
            [A] -> [B] : f()   # accepts: retry-without-idempotency
            """)
        self.assertEqual(rep.findings[0].message,
                         "Why is `retry-without-idempotency` accepted here?")

    def test_policy_in_prose_catalog_example(self):
        rep = run("""
            #!craft
            [Checkout] -> [Payments] : charge(total)   # 3 retries, idempotent key
            """)
        (f,) = rep.findings
        self.assertEqual((f.rule.id, f.severity), ("SGC004", "info"))
        self.assertIn("`×3 @inv idempotent(key)`", f.message)
        self.assertTrue(f.message.endswith("?"))

    def test_policy_in_prose_declared_twin(self):
        rep = run("""
            #!craft
            [Checkout] -> [Payments] : charge(total) ×3 @inv idempotent(order_id)   # 3 retries, idempotent key
            """)
        self.assertEqual(rep.findings, [])

    def test_policy_in_prose_partly_declared(self):
        rep = run("""
            #!spec
            [A] -> [B] : f() @timeout(2s)   # timeout 2s, retried twice
            """)
        (f,) = rep.findings
        self.assertIn("retries", f.message)
        self.assertNotIn("timeout", f.message.split("—")[0])

    def test_policy_in_prose_needs_a_call_line_and_a_trailing_comment(self):
        rep = run("""
            #!spec
            # the payments call retries 3 times
            [Checkout] -> [Payments] : charge(total)
            [Checkout] -> [Payments]   # retries
            """)
        self.assertEqual(rep.findings, [])

    def test_policy_in_prose_hint_is_not_emitted_in_sketch(self):
        rep = run("""
            [Checkout] -> [Payments] : charge(total)   # 3 retries
            """)
        self.assertEqual(rep.findings, [])

    def test_policy_ruled_out_or_delegated_is_not_asked_for(self):
        # the comment declines the policy: asking for it would change the design
        for comment in ("no retries: charge is not idempotent",
                        "retried by the caller, no timeout needed",
                        "never retried",
                        "don't retry; idempotency not needed",
                        "timeouts handled upstream",
                        "retries: none",
                        "without backoff"):
            with self.subTest(comment):
                rep = run(f"#!spec\n[A] -> [B] : charge(total) @timeout(2s)   # {comment}\n")
                self.assertEqual(rep.findings, [])

    def test_a_declined_word_beside_a_stated_one(self):
        rep = run("""
            #!craft
            [A] -> [B] : charge(total)   # 3 retries, not idempotent
            """)
        (f,) = rep.findings
        self.assertIn("`×3`", f.message)
        self.assertNotIn("idempoten", f.message.split("?")[0].split("“")[0])

    def test_breaker_is_no_core_policy_word(self):
        # `breaker` is no recognised @inv head; a dialect pack may add the word
        self.assertNotIn("breaker", {h for w in ck.POLICY_WORDS for h in w.heads})
        rep = run("""
            #!craft
            [A] -> [B] : charge(total) ×2 @inv idempotent(k)   # a breaker trips after 5
            """)
        self.assertEqual(rep.findings, [])

    def test_ack_reason_is_not_prose_policy(self):
        rep = run("""
            #!spec
            [A] -> [B] : put(x) ×3   # accepts: probe — writes are idempotent upserts
            """, probe_rule())
        self.assertEqual(rep.findings, [])


# ---------------------------------------------------------------------------
# Tiers × modes, the guess downgrade, the deviation cap
# ---------------------------------------------------------------------------

TABLE = {   # tier → mode → (severity, hidden) or None
    "binding": {"sketch": ("info", True), "craft": ("warn", False), "spec": ("error", False)},
    "advisory": {"sketch": ("info", True), "craft": ("warn", False), "spec": ("warn", False)},
    "hint": {"sketch": None, "craft": ("info", False), "spec": ("info", False)},
}


class Severity(unittest.TestCase):
    text = "[A] -> [B] : f()\n"

    def grade(self, mode, **kw):
        rep = ck.check(self.text, mode=mode, registry=with_rules(probe_rule(lines=[1], **kw)))
        return [(f.severity, f.hidden) for f in rep.findings]

    def test_table(self):
        for tier, row in TABLE.items():
            for mode, cell in row.items():
                with self.subTest(tier=tier, mode=mode):
                    self.assertEqual(self.grade(mode, tier=tier), [cell] if cell else [])

    def test_guess_drops_one_tier(self):
        self.assertEqual(self.grade("spec", guess="this flow looks like a write"),
                         [("warn", False)])
        rep = ck.check(self.text, mode="spec", registry=with_rules(
            probe_rule(lines=[1], guess="this flow looks like a write")))
        self.assertEqual(rep.findings[0].tier, "advisory")
        self.assertIn("(guessed: this flow looks like a write)", rep.findings[0].message)
        self.assertTrue(rep.to_dict()["findings"][0]["guess"])

    def test_guess_never_drops_below_hint(self):
        rep = ck.check(self.text, mode="spec", registry=with_rules(
            probe_rule(tier="hint", lines=[1], guess="a name match")))
        self.assertEqual([(f.severity, f.tier) for f in rep.findings], [("info", "hint")])

    def test_hit_tier_override(self):
        self.assertEqual(self.grade("spec", tier="advisory"), [("warn", False)])

    def test_two_deviation_witness_caps_at_warn(self):
        self.assertEqual(self.grade("spec", k=2, witness="A:fails+B:fails"),
                         [("warn", False)])
        self.assertEqual(self.grade("spec", k=1, witness="A:fails"), [("error", False)])

    def test_trace_findings_warn_only_until_lifted(self):
        self.assertEqual(self.grade("spec", trace=True, k=1), [("warn", False)])
        lifted = ck.Rule("TST001", "probe", "binding", "?", "w", "f",
                         match=lambda d: [ck.Hit(1, "s", "a?", trace=True, k=1)],
                         trace_warn_only=False)
        rep = ck.check(self.text, mode="spec", registry=with_rules(lifted))
        self.assertEqual(rep.findings[0].severity, "error")

    def test_mode_reading(self):
        for first, mode in (("#!spec\n", "spec"), ("#!craft\n", "craft"),
                            ("#!sketch\n", "sketch"), ("", "sketch"),
                            ("# a title comment\n#!spec\n", "spec")):
            with self.subTest(first=first):
                self.assertEqual(ck.check(first + self.text, registry=with_rules()).mode, mode)
        self.assertEqual(ck.check("#!spec\n" + self.text, mode="craft",
                                  registry=with_rules()).mode, "craft")

    def test_default_k_by_mode(self):
        self.assertEqual([ck.check(self.text, mode=m, registry=with_rules()).k
                          for m in ck.MODES], [1, 1, 2])
        self.assertEqual(ck.check(self.text, mode="spec", k=3, registry=with_rules()).k, 3)
        self.assertEqual(ck.check(self.text, mode="spec", k=3,
                                  registry=with_rules()).limits["k"], 3)

    def test_craft_asks_spec_states(self):
        craft = run("#!craft\n" + self.text, probe_rule(lines=[2]))
        spec = run("#!spec\n" + self.text, probe_rule(lines=[2]))
        self.assertEqual(craft.findings[0].message, "Probe at 2?")
        self.assertEqual(spec.findings[0].message, "probe at 2 — nothing")

    def test_exit_codes(self):
        self.assertEqual(run("#!spec\n" + self.text, probe_rule()).exit_code(), 2)
        self.assertEqual(run("#!craft\n" + self.text, probe_rule()).exit_code(), 1)
        self.assertEqual(run("#!sketch\n" + self.text, probe_rule()).exit_code(), 0)
        self.assertEqual(run("#!spec\n" + self.text, probe_rule(tier="hint")).exit_code(), 0)


# ---------------------------------------------------------------------------
# Folding (§1.7) and the registry end to end
# ---------------------------------------------------------------------------

def scoped_rule(rid, name, tier="binding", implies=(), scopes=(), line=2):
    def match(_d):
        yield ck.Hit(line, f"{name} here", f"{name} here?", anchor=("store", "DB"),
                     scopes=scopes)
    return ck.Rule(rid, name, tier, "?", "w", "f", match=match, implies=implies)


class Folding(unittest.TestCase):
    text = "#!spec\n[A] -> |DB| : put(x)\n[B] -> |DB| : put(y)\n"

    def test_implied_finding_is_folded(self):
        cause = scoped_rule("TST010", "shared-probe", implies=(("race-probe", "store"),))
        implied = scoped_rule("TST011", "race-probe", line=3)
        rep = ck.check(self.text, registry=with_rules(cause, implied))
        self.assertEqual([f.rule.name for f in rep.findings], ["shared-probe"])
        self.assertEqual([f.rule.name for f in rep.folded], ["race-probe"])
        self.assertIn("(also: race-probe)", rep.findings[0].message)
        self.assertEqual(rep.to_dict()["findings"][0]["also"][0]["name"], "race-probe")

    def test_other_scope_value_is_not_folded(self):
        cause = scoped_rule("TST010", "shared-probe", implies=(("race-probe", "store"),))

        def match(_d):
            yield ck.Hit(3, "elsewhere", "elsewhere?", anchor=("store", "Other"))
        implied = ck.Rule("TST011", "race-probe", "binding", "?", "w", "f", match=match)
        rep = ck.check(self.text, registry=with_rules(cause, implied))
        self.assertEqual(len(rep.findings), 2)

    def test_folding_is_transitive_to_the_root(self):
        a = scoped_rule("TST010", "a-probe", implies=(("b-probe", "store"),))
        b = scoped_rule("TST011", "b-probe", implies=(("c-probe", "store"),))
        c = scoped_rule("TST012", "c-probe")
        rep = ck.check(self.text, registry=with_rules(a, b, c))
        self.assertEqual([f.rule.name for f in rep.findings], ["a-probe"])
        self.assertEqual(sorted(f.rule.name for f in rep.findings[0].also),
                         ["b-probe", "c-probe"])

    def test_acknowledging_the_cause_covers_folded(self):
        cause = scoped_rule("TST010", "shared-probe", implies=(("race-probe", "store"),))
        implied = scoped_rule("TST011", "race-probe", line=3)
        text = "#!spec\n[A] -> |DB| : put(x)   # accepts: shared-probe — one writer at a time\n" \
               "[B] -> |DB| : put(y)\n"
        rep = ck.check(text, registry=with_rules(cause, implied))
        self.assertEqual(rep.findings, [])
        self.assertEqual([f.rule.name for f in rep.acknowledged], ["shared-probe"])
        self.assertEqual(rep.exit_code(), 0)

    def test_after_acks_rules_see_usage(self):
        seen = {}

        def stale(d):
            seen["used"] = d.ack_used
            seen["names"] = sorted(f.rule.name for f in d.findings)
            for a in d.acks:
                if a.reason and a.line not in d.ack_used:
                    yield ck.Hit(a.line, "stale", "stale?", anchor=("comment", a.line))
        later = ck.Rule("TST020", "stale-probe", "advisory", "?", "w", "f", match=stale,
                        after_acks=True, acknowledgeable=False)
        text = doc("""
            #!spec
            [A] -> [B] : f()   # accepts: probe — fine
            [A] -> [C] : g()   # accepts: other-probe — nothing to cover
            """)
        rep = ck.check(text, registry=with_rules(probe_rule(), later,
                                                 probe_rule("TST002", "other-probe",
                                                            lines=[])))
        self.assertEqual(seen["used"], frozenset({2}))
        self.assertEqual([(f.rule.name, f.line) for f in rep.findings],
                         [("probe", 3), ("stale-probe", 3)])


class Registry(unittest.TestCase):
    def rule(self, rid, name, tier="binding"):
        return ck.Rule(rid, name, tier, "?", "w", "f", match=lambda d: [])

    def test_core_rules_match_the_catalog(self):
        reg = ck.default_registry()
        for rid in ("SGC001", "SGC002", "SGC004"):
            self.assertEqual(reg[rid].name, ck.CORE_NAMES[rid])
        self.assertEqual(len(ck.CORE_NAMES), 55)
        self.assertFalse(ck.RETIRED_IDS & set(ck.CORE_NAMES))
        self.assertEqual(reg["SGC001"].layer, "meta")

    def test_refusals(self):
        cases = [
            ([self.rule("SGC105", "unbroken-dependency")], "retired"),
            ([self.rule("SGC101", "unguarded-calls")], "catalog"),
            ([self.rule("SGC999", "new-rule")], "not in the catalog"),
            ([self.rule("PCK001", "race")], "core name"),
            ([self.rule("PCK001", "a-rule"), self.rule("PCK001", "b-rule")], "twice"),
            ([self.rule("PCK001", "a-rule"), self.rule("PCK002", "a-rule")], "twice"),
            ([self.rule("PCK001", "a-rule", tier="fatal")], "tier"),
        ]
        for rules, why in cases:
            with self.subTest(why=why):
                with self.assertRaisesRegex(ck.RegistryError, why):
                    ck.build_registry(rules)

    def test_pack_names_are_acknowledgeable(self):
        rep = run("""
            #!spec
            [A] -> [B] : f()   # accepts: pack-probe — a pack rule
            """, probe_rule("PCK001", "pack-probe"))
        self.assertEqual(rep.findings, [])
        self.assertEqual(lines_of(rep.acknowledged), [2])

    def test_rule_modules_are_loaded_with_the_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "check_flow.py").write_text(textwrap.dedent("""
                def rules(ck):
                    return [ck.Rule("SGC101", "unguarded-call", "binding", "?", "w", "f",
                                    match=lambda d: [ck.Hit(1, "s", "a?")])]
                """))
            rules = ck.module_rules(ck, here=Path(tmp))
        self.assertEqual([r.id for r in rules], ["SGC101"])
        self.assertIsInstance(rules[0], ck.Rule)

    def test_rules_listing(self):
        listing = ck.registry_lines(ck.default_registry())
        self.assertEqual(len(listing), 55)
        self.assertTrue(listing[0].startswith("SGC001  ack-unknown-rule"))


# ---------------------------------------------------------------------------
# CLI and determinism
# ---------------------------------------------------------------------------

SAMPLE = doc("""
    #!craft
    # accepts: retry-without-idempotence — upsert

    [Checkout] -> [Payments] : charge(total)   # 3 retries, idempotent key
    [API] -> [Payments] : charge(total) ×3 @timeout(2s)   # accepts: retry-without-idempotency
    state {Order} {   # accepts: unguarded-calls — typo
      + -<Go>-> Open   # accepts: ack-unsued — typo
    }
    """)


class Cli(unittest.TestCase):
    def cli(self, *args, seed="0", stdin=SAMPLE):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        env.pop("SIGIL_DIALECT", None)
        return subprocess.run([sys.executable, str(_DIR / "check.py"), *args],
                              input=stdin, capture_output=True, text=True, env=env)

    def test_byte_identical_across_hash_seeds(self):
        for args in (["-"], ["-", "--json"], ["-", "--mode", "spec", "--all"]):
            with self.subTest(args=args):
                outs = {self.cli(*args, seed=s).stdout for s in ("0", "1", "4242")}
                self.assertEqual(len(outs), 1)
                self.assertTrue(next(iter(outs)))

    def test_lines_are_lint_compatible_and_sorted(self):
        p = self.cli("-")
        self.assertEqual(p.returncode, 1)
        out = p.stdout.splitlines()
        # The rule modules add their own findings to SAMPLE; pin only the core's
        # (SGC0xx), and the line order of everything.
        self.assertEqual([ln.split(":")[2] for ln in out if ln.split(":")[2] < "SGC100"],
                         ["SGC001", "SGC004", "SGC002", "SGC001", "SGC001"])
        lines = [int(ln.split(":")[1]) for ln in out]
        self.assertEqual(lines, sorted(lines))
        for ln in out:
            sev, line, rid, rest = ln.split(":", 3)
            self.assertIn(sev, ("error", "warn", "info"))
            self.assertTrue(line.isdigit())
            self.assertRegex(rest, r"^ [a-z0-9-]+: ")
        self.assertIn("sigil check (craft, k=1)", p.stderr)

    def test_json_fields(self):
        data = json.loads(self.cli("-", "--json", "--mode", "spec").stdout)
        self.assertEqual((data["mode"], data["k"], data["limits"]["k"]), ("spec", 2, 2))
        self.assertIn("depth", data["limits"])
        f = data["findings"][0]
        for key in ("severity", "line", "rule", "message", "name", "tier", "mode",
                    "anchor", "why", "fix", "guess", "k", "witness", "acknowledged",
                    "also"):
            self.assertIn(key, f)
        self.assertEqual(data["acknowledged"], [])

    def test_clean_document(self):
        p = self.cli("-", stdin="#!spec\n[A] -> [B] : f() @timeout(2s) @fallback(x)\n")
        self.assertEqual((p.returncode, p.stdout.strip()), (0, "sigil check: OK (no findings)"))

    def test_rules_flag(self):
        p = self.cli("--rules", stdin="")
        self.assertEqual(p.returncode, 0)
        self.assertIn("SGC004  policy-in-prose", p.stdout)

    def test_bad_input(self):
        p = self.cli(str(_DIR / "no-such-file.sigil"), stdin="")
        self.assertEqual(p.returncode, 2)
        self.assertIn("check.py:", p.stderr)

    def test_hidden_findings_need_all(self):
        text = "[A] -> [B] : f()   # accepts: unguarded-call\n"   # SGC002: binding → hidden in sketch
        self.assertEqual(self.cli("-", stdin=text).stdout.strip(),
                         "sigil check: OK (no findings)")
        self.assertIn("info:1:SGC002", self.cli("-", "--all", stdin=text).stdout)


# ---------------------------------------------------------------------------
# The model's facts (call policy, access), exploration causes, the dialect pack
# ---------------------------------------------------------------------------

LOOP = doc("""
    #!spec
    (User) -> [Batch] : run()
    loop @times 5 {
      [Batch] -> |Q| : push({Item})
    }
    """)


def loop_cap(d):
    n = next(i for i, text in enumerate(d.lines, 1) if text.startswith("loop"))
    yield ck.Hit(n, "the loop ran 2 of its 5 times", "Are 2 runs enough?",
                 anchor=("block", n), acknowledgeable=True)


def budget(d):
    yield ck.Hit(2, "the budget left 4 combinations out", "Is that enough?")


def explore(text, *causes, mode=None):
    return ck.check(text, mode=mode,
                    registry=ck.build_registry(ck.core_rules()
                                               + [ck.exploration_rule(list(causes))]))


class ModelFacts(unittest.TestCase):
    def test_node_cardinality_is_no_retry(self):
        rep = run("""
            #!craft
            [A]×3 -> [B] : f()   # 3 retries
            [C] -> [B] : f() ×3   # 3 retries
            """)
        self.assertEqual(lines_of(rep.findings, "policy-in-prose"), [2])

    def test_source_side_modifiers_declare(self):
        rep = run("""
            #!craft
            [A] @timeout(2s) -> [B] : f()   # timeout 2s
            [W] -> run() @deadline(1s)   # times out after 1s
            """)
        self.assertEqual(rep.findings, [])

    def test_inv_head_must_match(self):
        rep = run("""
            #!craft
            [A] -> [B] : f() @inv ordered(k)   # idempotent
            [A] -> [C] : g() @inv dedup(k)   # deduplicated
            """)
        self.assertEqual(lines_of(rep.findings, "policy-in-prose"), [2])
        self.assertEqual(ck.inv_head(" idempotent(order_id)"), "idempotent")

    def test_access_mode_reads_the_dialect_verbs(self):
        text = "[S] -> |DB| : peek(${id})\n"
        plain = ck.Doc(text, "spec", 1, frozenset())
        extended = ck.Doc(text, "spec", 1, frozenset(), read_verbs={"peek"})
        (w,) = [w for w in plain.sc.wires if w.role == "flow"]
        self.assertEqual(plain.access_mode(w), "write")
        self.assertEqual(extended.access_mode(w), "read")
        self.assertEqual(extended.read_verbs[:len(plain.read_verbs)], plain.read_verbs)


class Unacknowledgeable(unittest.TestCase):
    def test_meta_names_override_any_flag(self):
        stale = probe_rule("SGC003", "ack-unused", tier="advisory", lines=[2],
                           acknowledgeable=True)
        rep = run("""
            #!spec
            [A] -> [B] : f()   # accepts: ack-unused — keep it
            """, stale)
        self.assertEqual(rep.acknowledged, [])
        self.assertEqual(sorted(f.rule.id for f in rep.findings), ["SGC001", "SGC003"])

    def test_every_meta_rule_is_refused(self):
        for name in sorted(ck.NOT_ACKNOWLEDGEABLE):
            with self.subTest(name):
                rep = run(f"#!spec\n[A] -> [B] : f()   # accepts: {name} — because\n")
                self.assertEqual([f.rule.id for f in rep.findings], ["SGC001"])


class Packaging(unittest.TestCase):
    def test_every_rule_module_is_packaged_and_scanned(self):
        # check.py loads the rule modules beside it, so a module missing from the
        # archive would silently run fewer rules there than here
        def load(name):
            spec = importlib.util.spec_from_file_location(f"pkg_{name}", _DIR / f"{name}.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
        build, core = load("build"), load("tests/test_core")
        present = {m for m in ck.RULE_MODULES if (_DIR / m).exists()}
        self.assertLessEqual(present, build.REQUIRED_TOOLS)
        self.assertLessEqual(present, set(build.TOOLS))
        self.assertLessEqual(present, set(core._CORE_FILES))


class Exploration(unittest.TestCase):
    def test_causes_fold_into_one_rule(self):
        rep = explore(LOOP, loop_cap, budget)
        self.assertEqual([(f.rule.id, f.line) for f in rep.findings],
                         [("SGC090", 2), ("SGC090", 3)])
        self.assertEqual({f.severity for f in rep.findings}, {"info"})

    def test_loop_cap_acknowledged_on_the_loop_line(self):
        text = LOOP.replace("loop @times 5 {",
                            "loop @times 5 {   # accepts: exploration-incomplete — enough")
        rep = explore(text, loop_cap)
        self.assertEqual(lines_of(rep.acknowledged), [3])
        self.assertEqual(rep.findings, [])

    def test_loop_cap_not_acknowledged_document_wide(self):
        text = LOOP.replace("#!spec\n", "#!spec\n# accepts: exploration-incomplete — "
                                        "small runs suffice\n\n")
        rep = explore(text, loop_cap)
        self.assertEqual(rep.acknowledged, [])
        self.assertEqual(lines_of(rep.findings), [5])

    def test_run_causes_are_never_acknowledged(self):
        text = LOOP.replace("(User) -> [Batch] : run()",
                            "(User) -> [Batch] : run()   # accepts: exploration-incomplete "
                            "— fine")
        rep = explore(text, budget)
        self.assertEqual(rep.acknowledged, [])
        self.assertEqual(lines_of(rep.findings), [2])

    def test_module_causes_build_sgc090(self):
        with tempfile.TemporaryDirectory() as tmp:
            for stem, cause in (("check_state", "loop"), ("check_trace", "budget")):
                Path(tmp, f"{stem}.py").write_text(textwrap.dedent(f"""
                    def exploration_causes(ck):
                        return [lambda d: [ck.Hit(1, "{cause}", "{cause}?")]]
                    """))
            rules = ck.module_rules(ck, here=Path(tmp))
        (rule,) = rules
        self.assertEqual((rule.id, rule.name), ck.EXPLORATION)
        self.assertEqual([h.statement for h in rule.match(None)], ["loop", "budget"])
        self.assertFalse(rule.acknowledgeable or rule.ack_document)

    def test_no_causes_no_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ck.module_rules(ck, here=Path(tmp)), [])


def quota_dialect():
    """A dialect module with a rule, a read verb and a policy word."""
    d = types.ModuleType("quota_dialect")
    d.NAME = "quota"
    d.READ_VERBS = {"peek"}

    def check_rules(api):
        return [api.Rule("QTA001", "quota-probe", "hint", "?", "w", "f",
                         match=lambda doc: [api.Hit(1, "probe", "probe?")])]

    def policy_words(api):
        return [api.PolicyWord("a quota", r"\bquota\b", ("quota",), (),
                               lambda _t: "@quota(…)")]
    d.check_rules, d.policy_words = check_rules, policy_words
    return d


class DialectPack(unittest.TestCase):
    TEXT = "#!craft\n[A] -> [B] : f()   # under a quota\n"

    def test_pack_joins_the_registry_and_the_doc(self):
        rep = ck.check(self.TEXT, dialect=quota_dialect())
        self.assertEqual([(f.rule.id, f.line) for f in rep.findings],
                         [("QTA001", 1), ("SGC004", 2)])
        self.assertIn("`@quota(…)`", rep.findings[1].message)

    def test_no_dialect_no_pack(self):
        self.assertEqual(ck.check(self.TEXT).findings, [])
        self.assertEqual(ck.dialect_pack(None).rules, ())

    def test_clashing_pack_is_refused(self):
        d = quota_dialect()
        d.INV_HEADS = {"idempotent"}
        with self.assertRaisesRegex(ValueError, "core head"):
            ck.dialect_pack(d)


class Corpus(unittest.TestCase):
    """The P1 rules over the repository's own documents: no crash, and the only
    findings are SGC004 hints (prose policy on call lines)."""

    def test_fixtures_and_examples(self):
        texts = [p.read_text(encoding="utf-8")
                 for p in sorted((_DIR / "tests" / "fixtures").glob("*.sigil"))]
        for md in ("examples.md", "language.md"):
            src = (_DIR / md).read_text(encoding="utf-8")
            texts += [b for b in src.split("```")[1::2] if b.lstrip().startswith("#!")]
        reg = with_rules()
        for n, text in enumerate(texts):
            with self.subTest(n=n):
                rep = ck.check(text, registry=reg)
                self.assertEqual({f.rule.id for f in rep.findings} - {"SGC004"}, set())


if __name__ == "__main__":
    unittest.main()
