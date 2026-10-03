"""Declared invariants (RFC 0003, catalog §4): check_inv.py's SGC301 inv-unchecked,
SGC302 inv-dangling, SGC303 inv-contradicted, SGC304 layer-inversion and SGC306
timeout-below-sla, and SGC173's declared-order clause, an `@inv lock-order(|A| <
|B|)` checked against the lock-order graph of check_state.py (every acquisition
against the declared order is reported; a cycle already covered by such a report
is not reported again).

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import re
import sys
import textwrap
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]


def _load(key: str, fname: str):
    spec = importlib.util.spec_from_file_location(key, _DIR / fname)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


ck = _load("sigil_check_inv_suite_check", "check.py")
cs = _load("sigil_check_inv_suite_state", "check_state.py")
ci = _load("sigil_check_inv_suite_inv", "check_inv.py")
dialects = _load("sigil_check_inv_suite_dialects", "dialects.py")

INV_RULES = ("SGC301", "SGC302", "SGC303", "SGC304", "SGC306")


def lock_findings(text: str, mode: str = "spec") -> list:
    """(line, statement) of every SGC173 finding, the core and state rules run."""
    registry = ck.build_registry(ck.core_rules() + cs.rules(ck))
    rep = ck.check(textwrap.dedent(text).lstrip("\n"), mode=mode, registry=registry)
    return [(f.hit.line, f.hit.statement) for f in rep.findings if f.rule.id == "SGC173"]


def inv_report(text: str, mode: str = "spec", dialect=None):
    registry = ck.build_registry(ck.core_rules() + ci.rules(ck))
    return ck.check(textwrap.dedent(text).lstrip("\n"), mode=mode, registry=registry,
                    dialect=dialect)


def found(text: str, mode: str = "spec", dialect=None) -> list:
    """(rule id, line, severity) of every finding this module's rules give."""
    rep = inv_report(text, mode, dialect)
    return [(f.rule.id, f.line, f.severity) for f in rep.findings if f.rule.id in INV_RULES]


def messages(text: str, rid: str) -> list:
    return [f.hit.statement for f in inv_report(text).findings if f.rule.id == rid]


# ---------------------------------------------------------------------------
# Reading an argument
# ---------------------------------------------------------------------------

class Reading(unittest.TestCase):

    def test_paren_args_split_at_top_level_commas(self):
        self.assertEqual(ci.paren_args("atomic(|S|, <E>)"), ["|S|", "<E>"])
        self.assertEqual(ci.paren_args("excludes({E}.state ∈ {a, b})"),
                         ["{E}.state ∈ {a, b}"])
        self.assertEqual(ci.paren_args("idempotent"), [])
        self.assertEqual(ci.paren_args("idempotent()"), [])

    def test_glyph_refs(self):
        self.assertEqual([(r.kind, r.name, r.text) for r in ci.glyph_refs("atomic(~|S|, <E>)")],
                         [("store", "S", "~|S|"), ("event", "E", "<E>")])

    def test_bounds(self):
        self.assertTrue(ci.bound_ok("depth <= 32"))
        self.assertTrue(ci.bound_ok("hops ≤ 3"))
        for arg in ("depth <= 0", "depth <= N", "depth", "concurrency <= -1"):
            with self.subTest(arg=arg):
                self.assertFalse(ci.bound_ok(arg))

    def test_value_operator_over_state(self):
        self.assertTrue(ci.value_op_over_state("${state.n} + 1"))
        self.assertTrue(ci.value_op_over_state("${state.log} ++ {Entry}"))
        self.assertFalse(ci.value_op_over_state("${state.n}"))
        self.assertFalse(ci.value_op_over_state("${n} + 1"))
        self.assertFalse(ci.value_op_over_state(None))

    def test_sla_percentiles(self):
        self.assertEqual(ci.sla_percentiles("p50<100ms, p99 < 800ms"),
                         [(50.0, "100ms"), (99.0, "800ms")])

    def test_layer_order_closes_transitively(self):
        chains = [ci.chain("layers(ui > app > data)", ">")]
        self.assertIn(("ui", "data"), ci.closure(chains))


# ---------------------------------------------------------------------------
# SGC301 inv-unchecked
# ---------------------------------------------------------------------------

class InvUnchecked(unittest.TestCase):

    def test_unrecognised_head_is_listed_as_a_hint(self):
        self.assertEqual(found("""
            #!spec
            [Payment] @inv no-double-charge
            """), [("SGC301", 2, "info")])

    def test_glued_to_a_wire_source_is_listed_once(self):
        self.assertEqual(found("""
            #!craft
            [Api] @inv foo -> [B] : f() @timeout(1s)
            """), [("SGC301", 2, "info")])

    def test_recognised_head_is_not_listed(self):
        self.assertEqual(found("""
            #!spec
            [Payment] @inv idempotent(transaction_id)
            """), [])

    def test_never_fails_and_is_silent_in_sketch(self):
        self.assertEqual(found("""
            [Payment] @inv no-double-charge
            """, mode="sketch"), [])

    def test_every_written_place_is_read(self):
        text = """
            #!spec
            {User}.age @inv >= 0
            [A] -> [B] : f() @inv write-only-primary
            loop @while |Q|.nonempty {
              [W] -> |Q| : pop
            } @inv drains
            """
        self.assertEqual([line for _r, line, _s in found(text)], [2, 3, 6])

    def test_corpus_invariants_listed_never_failed(self):
        """examples.md's `@inv` lines (catalog SGC301 evidence) are listed, as
        hints only, by this module."""
        text = (_DIR / "examples.md").read_text(encoding="utf-8")
        blocks = [m.group(2) for m in re.finditer(r"^```([a-z]*)\n(.*?)^```", text, re.S | re.M)
                  if m.group(1) != "text" and "@inv" in m.group(2)]
        self.assertTrue(blocks)
        listed = []
        for block in blocks:
            for rid, line, sev in found(block):
                with self.subTest(line=block.splitlines()[line - 1]):
                    self.assertEqual((rid, sev), ("SGC301", "info"))
                listed.append(block.splitlines()[line - 1].strip())
        self.assertIn("} @inv write-only-primary", listed)
        self.assertIn("[MCP.r]   @inv semantic-surface(no raw graph queries)", listed)
        self.assertNotIn("|PROV|    @inv immutable", listed)

    def test_an_acknowledgement_silences_it(self):
        rep = inv_report("""
            #!spec
            [Payment] @inv no-double-charge   # accepts: inv-unchecked — enforced by the bank
            """)
        self.assertEqual([f.rule.id for f in rep.acknowledged], ["SGC301"])

    def test_a_dialect_head_is_recognised(self):
        pack = dialects.load(str(_DIR / "tests" / "fixtures" / "dialect_pack_resilience.py"))
        text = """
            #!spec
            [Api] @inv breaker(payments)
            """
        self.assertEqual(found(text), [("SGC301", 2, "info")])
        self.assertEqual(found(text, dialect=pack), [])

    def test_the_heads_come_from_the_documents_pack(self):
        # A pack handed to check() directly (no dialect loaded) is the one read.
        pack = dialects.RulePack(inv_heads=frozenset({"breaker"}))
        registry = ck.build_registry(ck.core_rules() + ci.rules(ck))
        rep = ck.check("#!spec\n[Api] @inv breaker(5)\n", mode="spec",
                       registry=registry, pack=pack)
        self.assertEqual([f.rule.id for f in rep.findings if f.rule.id in INV_RULES], [])


class Placement(unittest.TestCase):
    """Each written `@inv` is reported once, on the line that writes it."""

    def test_a_name_inside_another_names_its_own_line(self):
        # `[A]` is not `[AB]`: each node's invariant is on its own line.
        self.assertEqual(found("""
            #!spec
            [AB] @inv no-dup
            [A] @inv no-dup
            """), [("SGC301", 2, "info"), ("SGC301", 3, "info")])

    def test_a_contradiction_on_the_shorter_name_is_on_its_line(self):
        self.assertEqual(found("""
            #!spec
            [AB] @inv idempotent
            [A] @inv idempotent
            [A] -> ~|n| : ${state.n} + 1
            """), [("SGC303", 3, "error")])

    def test_an_acknowledgement_on_the_real_line_matches(self):
        rep = inv_report("""
            #!spec
            [AB] @inv no-dup
            [A] @inv no-dup   # accepts: inv-unchecked — enforced elsewhere
            """)
        self.assertEqual([f.line for f in rep.acknowledged], [3])
        self.assertEqual([f.line for f in rep.findings if f.rule.id in INV_RULES], [2])

    def test_a_block_head_and_close_each_keep_their_line(self):
        self.assertEqual(found("""
            #!spec
            parallel @inv alpha-x {
              [A] -> [B] : f()
            } @inv beta-y
            """), [("SGC301", 2, "info"), ("SGC301", 4, "info")])

    def test_an_owns_header_invariant_is_one_invariant(self):
        # The header's `@inv` is both the node's and the block's: reported once.
        self.assertEqual(found("""
            #!spec
            [A] @owns |S| @inv foo-one {
              [A] -> |S| : put
            } @inv bar-two
            """), [("SGC301", 2, "info"), ("SGC301", 4, "info")])


# ---------------------------------------------------------------------------
# SGC302 inv-dangling
# ---------------------------------------------------------------------------

class InvDangling(unittest.TestCase):

    def test_typo_flagged_with_a_suggestion(self):
        text = """
            #!spec
            [Checkout] -> |Orders| : put({Order})
            [Checkout] ~> <Placed>
            [Checkout] @inv atomic(|Order|, <Placed>)
            """
        self.assertEqual(found(text), [("SGC302", 4, "warn")])
        rep = inv_report(text)
        self.assertEqual(rep.findings[0].fix, "write `|Orders|`")

    def test_declared_twin_clean(self):
        self.assertEqual(found("""
            #!spec
            [Checkout] -> |Orders| : put({Order})
            [Checkout] ~> <Placed>
            [Checkout] @inv atomic(|Orders|, <Placed>)
            """), [])

    def test_atomic_naming_what_another_node_does(self):
        text = """
            #!spec
            [Checkout] -> |Orders| : put({Order})
            [Mailer] ~> <Placed>
            [Checkout] @inv atomic(|Orders|, <Placed>)
            """
        self.assertEqual(found(text), [("SGC302", 4, "warn")])
        self.assertIn("never emits `<Placed>`", messages(text, "SGC302")[0])

    def test_atomic_on_a_block_reads_its_members(self):
        self.assertEqual(found("""
            #!spec
            checkout {
              [Checkout] -> |Orders| : put({Order})
              [Checkout] ~> <Placed>
            } @inv atomic(|Orders|, <Placed>)
            """), [])

    def test_lock_order_naming_an_unowned_resource(self):
        text = """
            #!spec
            [P] @inv lock-order(|A| < |C|)
            [P] @owns |A| {
              [P] -> |A| : put({X})
            }
            |C| -> [P] : get()
            """
        self.assertEqual(found(text), [("SGC302", 2, "warn")])
        self.assertIn("`|C|`", messages(text, "SGC302")[0])

    def test_lock_order_over_owned_only_stores_clean(self):
        self.assertEqual(found(CYCLE.format(decl="[P] @inv lock-order(|A| < |B|)")), [])

    def test_serialised_over_an_owned_only_store_clean(self):
        self.assertEqual(found("""
            #!spec
            [P] @owns |A| {
              [P] -> [Q]
            }
            [P] @inv serialised(|A|)
            """), [])

    def test_layers_tier_no_loc_uses(self):
        text = """
            #!spec
            [Shop] @inv layers(ui > dta)
            [UI] @loc(ui)
            [Repo] @loc(data)
            """
        self.assertEqual(found(text), [("SGC302", 2, "warn")])
        self.assertEqual(inv_report(text).findings[0].fix, "write `data`")

    def test_serialised_on_a_drawn_store_clean(self):
        self.assertEqual(found("""
            #!spec
            [A] -> |S| : put({X})
            [B] -> |S| : put({Y})
            |S| @inv serialised(|S|)
            """), [])


# ---------------------------------------------------------------------------
# SGC303 inv-contradicted
# ---------------------------------------------------------------------------

class InvContradicted(unittest.TestCase):

    def test_keyless_idempotent_counter(self):
        self.assertEqual(found("""
            #!spec
            (User) -> [Counter] : hit()
            [Counter] -> ~|n| : ${state.n} + 1
            [Counter] @inv idempotent
            """), [("SGC303", 4, "error")])

    def test_keyed_idempotent_counter_clean(self):
        self.assertEqual(found("""
            #!spec
            (User) -> [Counter] : hit()
            [Counter] -> ~|n| : ${state.n} + 1
            [Counter] @inv idempotent(request_id)
            """), [])

    def test_keyless_idempotent_with_plain_writes_clean(self):
        self.assertEqual(found("""
            #!spec
            (User) -> [Flag] : set()
            [Flag] -> ~|on| : true
            [Flag] @inv idempotent
            """), [])

    def test_immutable_on_a_mutable_store(self):
        self.assertEqual(found("""
            #!spec
            [A] -> ~|S| : put({X})
            ~|S| @inv immutable
            """), [("SGC303", 3, "error")])

    def test_immutable_store_updated_over_its_state(self):
        text = """
            #!spec
            [A] -> |Log| : ${state.items} ++ {Entry}
            |Log| @inv immutable
            """
        self.assertEqual(found(text), [("SGC303", 3, "error")])

    def test_immutable_plain_store_written_once_clean(self):
        self.assertEqual(found("""
            #!spec
            [A] -> |PROV| : put({Record})
            |PROV| @inv immutable
            """), [])

    def test_bounds_must_be_positive_integers(self):
        text = """
            #!spec
            [Walk] @inv depth <= 0
            [Hop] @inv hops <= N
            [Pool] @inv concurrency <= 8
            [Tree] @inv depth <= 32
            """
        self.assertEqual(found(text), [("SGC303", 2, "error"), ("SGC303", 3, "error")])

    def test_keyless_ordered_with_many_consumers(self):
        self.assertEqual(found("""
            #!spec
            *<Orders> @inv ordered
            *<Orders> -> [Worker]×4 : handle({Order})
            """), [("SGC303", 2, "error")])

    def test_keyed_ordered_with_many_consumers_clean(self):
        self.assertEqual(found("""
            #!spec
            *<Orders> @inv ordered(order_id)
            *<Orders> -> [Worker]×4 : handle({Order})
            """), [])

    def test_keyless_ordered_with_an_owner_or_one_consumer_clean(self):
        self.assertEqual(found("""
            #!spec
            *<Orders> @inv ordered
            *<Orders> -> [Worker]×4 : handle({Order})
            [Worker] @owns |Ledger|
            *<Paid> @inv ordered
            *<Paid> -> [Biller] : bill({Order})
            """), [])


# ---------------------------------------------------------------------------
# SGC304 layer-inversion
# ---------------------------------------------------------------------------

LAYERED = """
    #!spec
    [App] @inv layers(ui > data)
    [UI] @loc(ui)
    [Repo] @loc(data)
    {wire}
    """


class LayerInversion(unittest.TestCase):

    def test_upcall_flagged(self):
        text = LAYERED.format(wire="[Repo] -> [UI] : refresh()")
        self.assertEqual(found(text), [("SGC304", 5, "error")])
        self.assertEqual(messages(text, "SGC304"),
                         ["`[Repo]` (data) calls `[UI]` (ui), a tier above it"])

    def test_event_up_clean(self):
        self.assertEqual(found(LAYERED.format(wire="[Repo] ~> <Changed> -> [UI]")), [])

    def test_downcall_clean(self):
        self.assertEqual(found(LAYERED.format(wire="[UI] -> [Repo] : load()")), [])

    def test_node_without_loc_ignored(self):
        self.assertEqual(found(LAYERED.format(wire="[Repo] -> [Other] : ping()")), [])

    def test_no_declaration_no_rule(self):
        self.assertEqual(found("""
            #!spec
            [UI] @loc(ui)
            [Repo] @loc(data)
            [Repo] -> [UI] : refresh()
            """), [])

    def test_order_is_transitive(self):
        self.assertEqual(found("""
            #!spec
            [App] @inv layers(ui > app > data)
            [UI] @loc(ui)
            [Svc] @loc(app)
            [Repo] @loc(data)
            [Repo] -> [UI] : refresh()
            """), [("SGC304", 6, "error")])


# ---------------------------------------------------------------------------
# SGC306 timeout-below-sla
# ---------------------------------------------------------------------------

class TimeoutBelowSla(unittest.TestCase):

    def test_timeout_below_p99(self):
        text = """
            #!spec
            [Search] @sla(p99<800ms)
            [API] -> [Search] : find(${q}) @timeout(200ms)
            """
        self.assertEqual(found(text), [("SGC306", 3, "warn")])
        self.assertIn("more than 1% of calls", messages(text, "SGC306")[0])

    def test_timeout_above_clean(self):
        self.assertEqual(found("""
            #!spec
            [Search] @sla(p99<800ms)
            [API] -> [Search] : find(${q}) @timeout(1s)
            """), [])

    def test_the_lowest_percentile_above_the_timeout_is_reported(self):
        text = """
            #!spec
            [Search] @sla(p50<100ms, p99<800ms)
            [API] -> [Search] : find(${q}) @timeout(50ms)
            """
        self.assertIn("p50 of 100ms", messages(text, "SGC306")[0])

    def test_fallback_clean(self):
        self.assertEqual(found("""
            #!spec
            [Search] @sla(p99<800ms)
            [API] -> [Search] : find(${q}) @timeout(200ms) @fallback([])
            """), [])

    def test_route_clean(self):
        self.assertEqual(found("""
            #!spec
            [Search] @sla(p99<800ms)
            [API] -> [Search] : find(${q}) @timeout(200ms)
              !> <Degraded>
            """), [])

    def test_race_member_clean(self):
        self.assertEqual(found("""
            #!spec
            [Search] @sla(p99<800ms)
            [API] -> [Search] &? [Cache] : look(${q}) @timeout(200ms)
            """), [])

    def test_parallel_any_member_clean(self):
        self.assertEqual(found("""
            #!spec
            [Search] @sla(p99<800ms)
            parallel @any {
              [API] -> [Search] : scan(${q}) @timeout(200ms)
              [API] -> [Cache] : scan(${q}) @timeout(200ms)
            }
            """), [])

    def test_no_timeout_or_no_sla_quiet(self):
        self.assertEqual(found("""
            #!spec
            [Search] @sla(p99<800ms)
            [API] -> [Search] : find(${q})
            [API] -> [Index] : find(${q}) @timeout(1ms)
            """), [])


# ---------------------------------------------------------------------------
# SGC173: the declared order (check_state.py)
# ---------------------------------------------------------------------------

CYCLE = """
    #!spec
    {decl}
    [P] @owns |A| {{
      [P] -> [Q]
    }}
    [Q] @owns |B| {{
      [Q] -> [P]
    }}
    """


class LockOrderChain(unittest.TestCase):

    def test_reads_resources_in_order(self):
        self.assertEqual(cs.lock_order_chain("lock-order(|A| < |B| < |C|)"),
                         ["|A|", "|B|", "|C|"])

    def test_other_heads_give_nothing(self):
        self.assertEqual(cs.lock_order_chain("serialised(|A|)"), [])

    def test_precedence_is_transitive_across_chains(self):
        order = cs.declared_precedence([["|A|", "|B|"], ["|B|", "|C|"]])
        self.assertEqual(order, {("|A|", "|B|"), ("|B|", "|C|"), ("|A|", "|C|")})


class DeclaredOrder(unittest.TestCase):

    def test_undeclared_cycle_reported_once(self):
        (hit,) = lock_findings(CYCLE.format(decl=""))
        self.assertIn("cycle", hit[1])

    def test_against_order_edge_replaces_the_cycle(self):
        found_ = lock_findings(CYCLE.format(decl="[P] @inv lock-order(|A| < |B|)"))
        self.assertEqual(found_, [(7, "`|B|` is held while `|A|` is acquired, against "
                                      "the declared order (`|A|` before `|B|`)")])

    def test_against_order_is_binding_even_with_a_timeout(self):
        text = CYCLE.format(decl="[P] @inv lock-order(|A| < |B|)").replace(
            "[Q] -> [P]", "[Q] -> [P] @timeout(1s)")
        self.assertEqual([line for line, _s in lock_findings(text)], [7])

    def test_nested_owns_against_order(self):
        found_ = lock_findings("""
            #!spec
            [P] @inv lock-order(|A| < |B|)
            [P] @owns |B| {
              [P] @owns |A| {
                [P] -> |A| : put({X})
              }
            }
            """)
        self.assertEqual(len(found_), 1)
        self.assertIn("`|B|` is held while `|A|`", found_[0][1])

    def test_acquisitions_in_declared_order_are_clean(self):
        self.assertEqual(lock_findings("""
            #!spec
            [P] @inv lock-order(|A| < |B|)
            [P] @owns |A| {
              [P] -> [Q]
            }
            [Q] @owns |B| {
              [Q] -> |B| : put({X})
            }
            """), [])

    def test_an_order_over_other_resources_leaves_the_cycle(self):
        (hit,) = lock_findings(CYCLE.format(decl="[P] @inv lock-order(|C| < |D|)"))
        self.assertIn("cycle", hit[1])


class Registry(unittest.TestCase):

    def test_rules_match_the_catalog(self):
        got = {r.id: (r.name, r.tier) for r in ci.rules(ck)}
        self.assertEqual(got, {
            "SGC301": ("inv-unchecked", "hint"), "SGC302": ("inv-dangling", "advisory"),
            "SGC303": ("inv-contradicted", "binding"),
            "SGC304": ("layer-inversion", "binding"),
            "SGC306": ("timeout-below-sla", "advisory")})

    def test_satisfiers_name_what_clears_never_what_triggers(self):
        sat = {r.id: set(r.satisfiers) for r in ci.rules(ck)}
        self.assertEqual(sat["SGC304"], {("call", "~>")})
        self.assertTrue(sat["SGC306"].isdisjoint({("call", "@timeout"), ("callee", "@sla")}))
        self.assertTrue({("call", "@fallback"), ("call", "!>"), ("call", "&?"),
                         ("block", "@any")} <= sat["SGC306"])
        self.assertTrue(sat["SGC303"].isdisjoint({("call", "idempotent"),
                                                  ("store", "ordered")}))

    def test_deterministic(self):
        text = """
            #!spec
            [B] @inv zeta
            [A] @inv alpha
            [A] @inv depth <= 0
            """
        self.assertEqual(found(text), found(text))
        self.assertEqual([line for _r, line, _s in found(text)], [2, 3, 4])


if __name__ == "__main__":
    unittest.main()
