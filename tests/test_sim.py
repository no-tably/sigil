"""Tests for sim.py — the simulation engine over the Scene.

Covers:
  1. scenario lists of the examples and fixtures (names, order, combination);
  2. worked traces (01-checkout, 04-orders): frame counts,
     outcomes, the fan-out forking, failure routes, machine states;
  3. calls (executions fixture): recursion bounded and unwound, aliases as
     entries, loops, external ops failing, fallbacks;
  4. composition instances (03-arena), races, alternatives, branches, gates,
     parallel blocks, conditionals, critical calls;
  5. termination and determinism: every scenario of every input ends, cycles
     end by their limits, two runs are equal, frame invariants hold;
  6. project(): one trace named as a view draws it (land mode, a shallow depth);
  7. failure_flow(): the static failure flow agrees with the traces of every
     corpus document, and the public static helpers (reachable, route_guard,
     loop_count);
  8. the simulator defect fixes of RFC 0003 (B1, B2, B3, B4, B13) and NG6;
  9. the structured events of Trace.end["events"] (MG1, MG2, MG5, MG6, MG9, MG11);
 10. combinations(): bounded k-deviation exploration (MG10).

Run:  python3 -m unittest discover tests
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sim = _load("sigil_sim_test", _DIR / "sim.py")
golden = _load("sigil_golden_sim_test", _DIR / "tools" / "golden.py")
scene = sim.scene_mod
render = sim.kit.render

EXAMPLES = sorted((_DIR / "site" / "examples").glob("*.sigil"))
FIXTURES = [_DIR / "tests" / "fixtures" / "executions.sigil",
            _DIR / "tests" / "fixtures" / "coverage.sigil"]


def build(text: str, **options):
    return scene.build_scene(render.parse_document(text), **options)


def load(name: str, **options):
    path = next(p for p in EXAMPLES + FIXTURES if p.name == name)
    return build(path.read_text(), **options)


def names(sc) -> list:
    return [s.name for s in sim.scenarios(sc)]


def run(sc, name: str = "happy", **kw):
    return sim.simulate(sc, sim.scenario(sc, name), **kw)


def wire(sc, src: str, dst: str, kind: str, n: int = 0) -> tuple:
    """The ident of a canonical wire (asserting it exists)."""
    ident = (src, dst, kind, n)
    canon = sim.canonical(sc.graph)
    assert ident in {w.ident for w in canon.wires}, ident
    return ident


def logs(trace, needle: str) -> list:
    return [line for line in trace.end["log"] if needle in line]


# ---------------------------------------------------------------------------
# 1. Scenario lists
# ---------------------------------------------------------------------------

class TestScenarioLists(unittest.TestCase):
    def test_examples(self):
        self.assertEqual(names(load("00-shortener.sigil")), ["happy", "Redirect.lookup:fails"])
        self.assertEqual(names(load("01-checkout.sigil")), ["happy", "API.charge:fails"])
        self.assertEqual(names(load("02-shop.sigil")), ["happy", "Risk?>Review"])
        self.assertEqual(names(load("03-arena.sigil")), ["happy"])
        self.assertEqual(names(load("04-orders.sigil")), ["happy", "Payments:fails"])

    def test_shortener_paths(self):
        # the page's first example: follow redirects and counts the click, or a
        # missing code ends on the !> route with neither
        sc = load("00-shortener.sigil")
        happy, missing = run(sc), run(sc, "Redirect.lookup:fails")
        self.assertEqual(happy.outcome, "ok")
        self.assertTrue(logs(happy, "redirect({Url})") and logs(happy, "<Clicked> -> [Stats]"))
        self.assertEqual(missing.outcome, "failed")
        self.assertTrue(logs(missing, "[Redirect] failed → (Visitor)"))
        self.assertEqual(logs(missing, "redirect({Url})") + logs(missing, "<Clicked>"), [])

    def test_executions_fixture_in_line_order(self):
        self.assertEqual(names(load("executions.sigil")), [
            "happy", "Crawler.throttle:fails", "Crawler.fetch:fallback",
            "Fetcher.http.get:fails", "Indexer.write:fails", "Notifier.mail.send:fails"])

    def test_names_are_unique_and_safe(self):
        for path in EXAMPLES + FIXTURES:
            with self.subTest(path.name):
                listed = names(build(path.read_text()))
                self.assertEqual(len(listed), len(set(listed)))
                self.assertEqual(listed[0], "happy")
                for n in listed:
                    self.assertNotIn("+", n)
                    self.assertNotIn(" ", n)

    def test_names_unique_on_one_line(self):
        # one payload on two join members; an alternative beside its conditionals
        cases = {"(U) -> [A]\n[A] -> [B] & [C] : charge() ×2\n":
                 ["happy", "A.charge:fails@2.1", "A.charge:fails@2.2"],
                 "(U) -> [A]\n[A] ?> [B] / [C]\n": ["happy", "A?>B", "A/C", "A?>C"]}
        for text, want in cases.items():
            with self.subTest(text):
                sc = build(text)
                self.assertEqual(names(sc), want)
                for n in want:
                    self.assertEqual(sim.scenario(sc, n).name, n)
        sc = build("(U) -> [A]\n[A] -> [B] & [C] : charge() ×2\n")
        a, b = (sim.scenario(sc, f"A.charge:fails@2.{k}").choices for k in (1, 2))
        self.assertNotEqual(a, b)

    def test_scenario_carries_choice_and_label(self):
        sc = load("01-checkout.sigil")
        s = sim.scenario(sc, "API.charge:fails")
        self.assertEqual(s.choices, ((("call", wire(sc, "API_service", "Payments_service", "->")),
                                      "fails"),))
        self.assertIn("4×", s.label)
        self.assertIsNone(s.entries)

    def test_call_label_names_the_callee_by_its_display_name(self):
        s = sim.scenario(load("coverage.sigil"), "Customer->Api:fails")
        self.assertIn("Api fails", s.label)
        self.assertNotIn("_service", s.label)

    def test_unknown_name_lists_the_known(self):
        with self.assertRaises(KeyError) as cm:
            sim.scenario(load("01-checkout.sigil"), "nope")
        self.assertIn("API.charge:fails", str(cm.exception))

    def test_combination_applies_both(self):
        sc = load("executions.sigil")
        both = sim.scenario(sc, "Crawler.fetch:fallback+Indexer.write:fails")
        self.assertEqual(len(both.choices), 2)
        tr = sim.simulate(sc, both)
        self.assertEqual(len(logs(tr, "falls back")), 1)
        self.assertEqual(len(logs(tr, "failed → |Index|")), 1)

    def test_continuation_route_guards_only_its_statement(self):
        # R-a: a `!>` continuing a flow line guards that line's calls, not its
        # subject's other calls (Edge.cont).
        sc = build("[A] -> [B] : first() @timeout(1s)\n"
                   "[A] -> [C] : second()\n"
                   "     !> [D] : undo()\n")
        self.assertEqual(names(sc), ["happy", "A.first:fails", "A.second:fails"])
        first = sim.simulate(sc, sim.scenario(sc, "A.first:fails"))
        self.assertEqual(logs(first, "failed → [D]"), [])
        second = sim.simulate(sc, sim.scenario(sc, "A.second:fails"))
        self.assertEqual(len(logs(second, "failed → [D]")), 1)

    def test_route_follows_the_most_recent_flow(self):
        # pitfall 4: an error path attaches to the most recent flow of the chain
        sc = build("[A] -> [B] : first() @timeout(1s)\n"
                   "    -> [C] : second()\n"
                   "    !> [D]\n")
        self.assertEqual(names(sc), ["happy", "A.first:fails", "A.second:fails"])
        first = sim.simulate(sc, sim.scenario(sc, "A.first:fails"))
        self.assertEqual(logs(first, "failed → [D]"), [])
        second = sim.simulate(sc, sim.scenario(sc, "A.second:fails"))
        self.assertEqual(len(logs(second, "failed → [D]")), 1)

    def test_list_is_capped(self):
        sc = load("coverage.sigil")
        self.assertEqual(len(sim.scenarios(sc, limits=sim.Limits(scenarios=3))), 3)

    def test_unreachable_choices_are_left_out(self):
        # follow := … holds a self-call nobody makes: no choice point from it
        sc = build("(U) -> [A]\nhelp := [B] -> [C] : go() @timeout(1s)\n")
        self.assertEqual(names(sc), ["happy"])


# ---------------------------------------------------------------------------
# 2. Worked traces
# ---------------------------------------------------------------------------

class TestCheckout(unittest.TestCase):
    def setUp(self):
        self.sc = load("01-checkout.sigil")
        self.w3 = wire(self.sc, "API_service", "PaymentFailed_event", "!>")

    def test_happy(self):
        tr = run(self.sc)
        self.assertEqual(len(tr.frames), 32)
        self.assertEqual(tr.outcome, "ok")
        self.assertNotIn(self.w3, tr.frames[-1].taken)
        self.assertEqual(tr.end["routes"], [])

    def test_fan_out_forks_three_tokens_in_one_frame(self):
        tr = run(self.sc)
        f = tr.frames[25]
        self.assertEqual([t.wire[2] for t in f.tokens], ["*>"] * 3)
        self.assertEqual(len({t.task for t in f.tokens}), 3)
        self.assertTrue(all(t.at == 0.0 for t in f.tokens))
        self.assertEqual(tr.frames[25].nodes["OrderPlaced_event"], "waiting")

    def test_call_held_while_callee_runs(self):
        tr = run(self.sc)
        w1 = wire(self.sc, "Shopper_actor", "API_service", "->")
        self.assertIn(w1, tr.frames[4].lit)
        self.assertIn(w1, tr.frames[5].held)
        self.assertEqual(tr.frames[4].nodes["Shopper_actor"], "waiting")
        self.assertEqual(tr.frames[4].nodes["API_service"], "active")

    def test_return_token_travels_back(self):
        tr = run(self.sc)
        back = [t for t in tr.frames[17].tokens if t.dir == "back"]
        self.assertEqual(len(back), 1)
        self.assertEqual(back[0].at, 0.5)
        self.assertEqual(back[0].carries, "{Order}")

    def test_failure_route(self):
        tr = run(self.sc, "API.charge:fails")
        self.assertEqual(len(tr.frames), 31)
        self.assertEqual(tr.outcome, "failed")
        self.assertEqual(len(logs(tr, "failed: ")), 2)     # the call, then the caller's
        self.assertEqual(len([ln for ln in tr.end["log"] if "attempt" in ln and "failed" in ln
                              and "after" not in ln]), 4)
        self.assertIn(self.w3, tr.frames[-1].failed)
        self.assertEqual(tr.end["routes"], [self.w3])
        self.assertEqual(tr.frames[25].tokens[0].state, "failed")
        self.assertEqual(tr.frames[9].tokens[0].attempt, (1, 4))
        for gone in ("Orders_store", "OrderPlaced_event", "Email_service"):
            self.assertNotIn(gone, tr.frames[-1].nodes)
        self.assertEqual(tr.frames[-1].nodes["PaymentFailed_event"], "visited")


class TestOrders(unittest.TestCase):
    def setUp(self):
        self.sc = load("04-orders.sigil")

    def test_happy_drives_both_machines(self):
        tr = run(self.sc)
        self.assertEqual(len(tr.frames), 32)
        self.assertEqual(tr.frames[0].machines, {"Order_data": "Order_state_start",
                                                 "Checkout_service": "Checkout_state_Idle"})
        self.assertEqual(tr.end["machines"], {"Order_data": "Order_state_Settled",
                                              "Checkout_service": "Checkout_state_Idle"})
        self.assertEqual(tr.frames[19].changed, {"Order_data", "Checkout_service"})
        self.assertIn(("Order_state_start", "Order_state_Open", "->", 0), tr.frames[19].lit)

    def test_episodes_run_one_after_another(self):
        tr = run(self.sc)
        self.assertEqual([f.episode for f in (tr.frames[20], tr.frames[21])], [1, 2])
        self.assertEqual(tr.frames[21].entry, "Payments_service")

    def test_payments_fail(self):
        tr = run(self.sc, "Payments:fails")
        self.assertEqual(tr.outcome, "failed")
        self.assertEqual(tr.end["machines"], {"Order_data": "Order_state_Cancelled",
                                              "Checkout_service": "Checkout_state_Idle"})
        self.assertEqual(tr.end["routes"],
                         [wire(self.sc, "Payments_service", "Declined_event", "!>")])
        self.assertNotIn("Paid_event", tr.frames[-1].nodes)

    def test_trigger_ignored_when_no_transition_matches(self):
        sc = build("(U) -> [A]\n[A] ~> <Go>\n[A] ~> <Go>\n"
                   "state {X} {\n  Idle -<Go>-> Busy\n}\n<Go> -> {X}\n")
        tr = run(sc)
        self.assertEqual(tr.end["machines"], {"X_data": "X_state_Busy"})
        self.assertTrue(logs(tr, "ignored: <Go>"))


class TestShopLevels(unittest.TestCase):
    """An expansion is a closer reading of the same node (sim.md §3.11, §8.4):
    `[Shop] ~> <OrderPlaced>` summarises `[Checkout] ~> <OrderPlaced>` inside
    `[Shop] := { … }`, so the event lands once, and the detail's emit runs the
    event's home body (`*> [Fulfilment] & |Ledger|`, written at the top level)."""

    def setUp(self):
        self.sc = load("02-shop.sigil")
        self.trace = run(self.sc)
        self.summary = wire(self.sc, "Shop_service", "OrderPlaced_event", "~>")

    def test_the_event_lands_once(self):
        tr = self.trace
        self.assertEqual(tr.outcome, "ok")
        became = [i for i in range(1, len(tr.frames))
                  if tr.frames[i].nodes.get("OrderPlaced_event") == "active"
                  and tr.frames[i - 1].nodes.get("OrderPlaced_event") != "active"]
        self.assertEqual(len(became), 1)
        self.assertEqual(logs(tr, "[Shop] ~>"), [])
        self.assertEqual(len(logs(tr, "<OrderPlaced> *> [Fulfilment]")), 1)

    def test_the_summary_carries_no_token_but_is_taken(self):
        tr = self.trace
        self.assertFalse(any(t.wire == self.summary for f in tr.frames for t in f.tokens))
        self.assertIn(self.summary, tr.frames[-1].taken)
        detail = sim.program(sim.canonical(self.sc.graph)).summaries[self.summary]
        for f in tr.frames:
            self.assertEqual(self.summary in f.lit, not f.lit.isdisjoint(detail))

    def test_the_pathway_runs(self):
        visited = self.trace.end["visited"]
        for nid in ("Fulfilment_service", "Ledger_store", "Picker_service",
                    "Packer_service", "Courier_actor", "Catalog_store"):
            self.assertIn(nid, visited)

    def test_out_wires_the_expansion_never_reaches_still_run(self):
        sc = build("(U) -> [Core]\n[Core] -> |DB| : put()\n[Core] -> |Log| : add()\n"
                   "[Core] := {\n  [H] -> |DB| : put()\n}\n")
        tr = run(sc)
        self.assertEqual(logs(tr, "[Core] -> |DB|"), [])
        self.assertTrue(logs(tr, "[H] -> |DB|"))
        self.assertTrue(logs(tr, "[Core] -> |Log|"))

    def test_a_node_with_no_work_where_reached_runs_its_home_body(self):
        sc = build("(U) -> [A]\n[A] ~> <E>\n<E> -> |Log| : add()\n"
                   "[A] := {\n  [B] ~> <E>\n}\n")
        tr = run(sc)
        self.assertEqual(logs(tr, "send [A] ~> <E>"), [])        # the summary
        self.assertEqual(len(logs(tr, "send [B] ~> <E>")), 1)
        self.assertEqual(len(logs(tr, "<E> -> |Log|")), 1)       # <E>'s top-level body


# ---------------------------------------------------------------------------
# 3. Calls
# ---------------------------------------------------------------------------

class TestExecutions(unittest.TestCase):
    def setUp(self):
        self.sc = load("executions.sigil")

    def test_recursion_reaches_the_depth_and_unwinds(self):
        tr = run(self.sc)
        self.assertEqual(tr.outcome, "ok")
        depths = {}
        for f in tr.frames:
            for nid, k in f.depth.items():
                depths[nid] = max(depths.get(nid, 0), k)
        self.assertEqual(depths, {"Doc_walk_service": 3, "Builder_service": 3})
        self.assertEqual(tr.frames[-1].depth, {})
        self.assertTrue(logs(tr, "base case: [Doc.walk] at depth 3"))

    def test_alias_unreachable_by_default_bounded_as_an_entry(self):
        tr = run(self.sc)
        self.assertNotIn("follow_alias", tr.frames[-1].nodes)
        entry = sim.Scenario("follow", entries=("follow_alias",))
        tr = sim.simulate(self.sc, entry)
        self.assertEqual(tr.outcome, "ok")
        self.assertEqual(max(f.depth.get("follow_alias", 0) for f in tr.frames), 3)
        self.assertTrue(logs(tr, "base case"))

    def test_call_naming_an_alias_runs_its_body(self):
        sc = build("[A] -> [B] : follow(x)\nfollow := [B] -> [C]\n")
        nodes = run(sc).frames[-1].nodes
        self.assertEqual(nodes["C_service"], "visited")
        self.assertEqual(nodes["follow_alias"], "visited")

    def test_choice_inside_a_called_alias_takes_effect(self):
        sc = build("walk := [D] ?> [E]\n(U) -> [D] : walk()\n")
        self.assertEqual(names(sc), ["happy", "D?>E"])
        self.assertNotIn("E_service", run(sc).frames[-1].nodes)
        self.assertEqual(run(sc, "D?>E").frames[-1].nodes["E_service"], "visited")

    def test_loop_runs_bounded_iterations(self):
        tr = run(self.sc)
        seen = {k for f in tr.frames for k in f.loops.values()}
        self.assertEqual(seen, {1, 2})
        self.assertEqual(len(logs(tr, "iteration")), 2)
        self.assertEqual(tr.frames[-1].loops, {})

    def test_external_op_fails_into_its_route(self):
        tr = run(self.sc, "Fetcher.http.get:fails")
        route = wire(self.sc, "Fetcher_service", "FetchFailed_event", "!>")
        self.assertIn(route, tr.frames[-1].failed)
        self.assertEqual(tr.frames[-1].nodes["FetchFailed_event"], "visited")
        # fetch's fallback catches Fetcher's failure: the crawl goes on
        self.assertEqual(tr.outcome, "ok")
        self.assertEqual(tr.frames[-1].nodes["Parser_service"], "visited")

    def test_fallback_returns_and_continues(self):
        tr = run(self.sc, "Crawler.fetch:fallback")
        backs = [t for f in tr.frames for t in f.tokens if t.state == "fallback"]
        self.assertTrue(backs)
        self.assertTrue(all(t.carries == "${cached}" and t.dir == "back" for t in backs))
        self.assertEqual(tr.outcome, "ok")
        self.assertEqual(tr.frames[-1].nodes["Parser_service"], "visited")
        self.assertEqual(tr.frames[-1].nodes["Fetcher_service"], "failed")   # each attempt
        self.assertEqual(len(logs(tr, "attempt")) // 2, 4)

    def test_fallback_fires_the_calls_guarded_route_then_yields(self):
        sc = build("(U) -> [A]\n[A] -> [B] : f() @fallback(x)\n  !> <Degraded>\n"
                   "[A] !> <Down>\n")
        tr = run(sc, "A.f:fallback")
        self.assertEqual(tr.outcome, "ok")
        # the route guarded by f() fires; the node's own route does not (A is fine)
        self.assertEqual(tr.end["routes"], [wire(sc, "A_service", "Degraded_event", "!>")])
        self.assertNotIn("Down_event", tr.frames[-1].nodes)
        log = tr.end["log"]
        fired = next(i for i, ln in enumerate(log) if "failed → <Degraded>" in ln)
        yielded = next(i for i, ln in enumerate(log) if "falls back to x" in ln)
        self.assertLess(fired, yielded)
        self.assertEqual(run(sc).end["routes"], [])

    def test_a_callee_failure_is_one_attempt_never_retried(self):
        # Example Q's declared twin: the charge retries ×3, but the scenario fails
        # the nested card call, so the charge arrives once and is not re-run
        sc = build("(User) -> [Booking] : book({Seat})\n"
                   "[Booking] -> [Payments] : charge({Seat}) ×3\n"
                   "[Payments] -> [Card] : op card.charge(${total})  @timeout(5s)\n")
        tr = run(sc, "Payments.card.charge:fails")
        self.assertEqual(tr.outcome, "failed")
        tries = logs(tr, "charge({Seat}) attempt")
        self.assertEqual(len(tries), 1)
        self.assertTrue(tries[0].endswith("charge({Seat}) attempt 1/4"))
        self.assertTrue(logs(tr, "failed: charge({Seat}) failed after 1 attempt "
                                 "(its callee failed)"))
        self.assertFalse(logs(tr, "after 4 attempts"))
        # the call failing itself still makes every attempt
        own = run(sc, "Booking.charge:fails")
        self.assertTrue(logs(own, "failed: charge({Seat}) failed after 4 attempts"))

    def test_deadline_without_timeout_is_one_attempt(self):
        tr = run(self.sc, "Crawler.throttle:fails")
        self.assertEqual(tr.outcome, "failed")
        self.assertTrue(logs(tr, "throttle(${host}) attempt 1/1"))
        self.assertEqual(tr.frames[-1].nodes["Operator_actor"], "failed")

    def test_external_far_node_is_opaque(self):
        tr = run(self.sc)
        self.assertEqual(tr.frames[-1].nodes["Web_actor"], "opaque")

    def test_self_call_is_a_one_tick_pulse_then_its_return(self):
        tr = run(self.sc)
        call = wire(self.sc, "Scheduler_service", "Scheduler_service", "->")
        ticks = [f.tick for f in tr.frames if any(t.wire == call for t in f.tokens)]
        self.assertEqual(len(ticks), 2)
        ret = wire(self.sc, "Scheduler_service", "Plan_data", "=>")
        self.assertIn(ret, tr.frames[-1].taken)

    def test_writes_into_one_target_are_separate_calls(self):
        tr = run(self.sc)
        idx = [w for w in tr.frames[-1].taken if w[:3] == ("Indexer_service", "Index_store", "->")]
        self.assertEqual(sorted(idx), [("Indexer_service", "Index_store", "->", 0),
                                       ("Indexer_service", "Index_store", "->", 1)])

    def test_request_reply_returns_on_its_wire(self):
        tr = run(self.sc)
        rw = wire(self.sc, "Fetcher_service", "Robots_store", "<->")
        self.assertTrue(any(t.wire == rw and t.dir == "back" for f in tr.frames for t in f.tokens))


# ---------------------------------------------------------------------------
# 4. Instances, joins, blocks
# ---------------------------------------------------------------------------

class TestArena(unittest.TestCase):
    def setUp(self):
        self.sc = load("03-arena.sigil")
        self.tr = run(self.sc)

    def test_setup_instances(self):
        inst = self.tr.frames[0].instances
        self.assertEqual(inst["Bullet_service"], 2)
        self.assertEqual(inst["Transform_data"], 4)
        self.assertEqual(inst["Shard_service"], 0)
        self.assertTrue(logs(self.tr, "setup: "))

    def test_reach_counts_matching_instances(self):
        reach = {t.wire[:2]: t.reach for f in self.tr.frames for t in f.tokens}
        self.assertEqual(reach[("Physics_service", "Transform_data")], 4)
        self.assertEqual(reach[("Homing_service", "Transform_data")], 2)   # [Bullet]/{Transform}

    def test_produce_spawns_one(self):
        self.assertEqual(self.tr.frames[-1].instances["Shard_service"], 1)
        self.assertTrue(logs(self.tr, "spawn [Shard] (1)"))

    def test_flow_into_no_instance_runs_nothing(self):
        sc = build("[P]\n    \\-{hit}-? [Q]\n[S] -> [Q]\n[Q] -> [R]\n")
        tr = run(sc)
        self.assertTrue(logs(tr, "no instance of [Q]"))
        self.assertNotIn("R_service", tr.frames[-1].nodes)


class TestJoinsAndBlocks(unittest.TestCase):
    def test_race_winner_and_loser(self):
        sc = build("(U) -> [Api]\n[Api] -> [A] &? [B]\n")
        self.assertEqual(names(sc), ["happy", "Api&?B"])
        happy = run(sc).frames[-1].nodes
        self.assertEqual((happy["A_service"], happy["B_service"]), ("visited", "cancelled"))
        other = run(sc, "Api&?B").frames[-1].nodes
        self.assertEqual((other["A_service"], other["B_service"]), ("cancelled", "visited"))

    def test_alternatives_take_one(self):
        sc = build("(U) -> [Api]\n[Api] => {Resp} / {Err}\n")
        self.assertEqual(names(sc), ["happy", "Api/Err"])
        self.assertNotIn("Err_data", run(sc).frames[-1].nodes)
        nodes = run(sc, "Api/Err").frames[-1].nodes
        self.assertIn("Err_data", nodes)
        self.assertNotIn("Resp_data", nodes)

    def test_strict_join_waits_for_all_and_member_failure_fails(self):
        sc = build("(U) -> [Api]\n[Api] -> [A] & [B] @timeout(1s)\n")
        tr = run(sc)
        self.assertEqual(tr.outcome, "ok")
        bad = [n for n in names(sc) if n != "happy"]
        self.assertEqual(bad, ["Api->A:fails", "Api->B:fails"])   # on both links
        tr = run(sc, bad[1])
        self.assertEqual(tr.outcome, "failed")
        self.assertEqual(tr.frames[-1].nodes["Api_service"], "failed")

    def test_conditional(self):
        sc = build("(U) -> [Risk]\n[Risk] ?> [Review]\n")
        self.assertEqual(names(sc), ["happy", "Risk?>Review"])
        self.assertNotIn("Review_service", run(sc).frames[-1].nodes)
        self.assertEqual(run(sc, "Risk?>Review").frames[-1].nodes["Review_service"], "visited")

    def test_gate_runs_target_once_when_all_arrived(self):
        sc = build("[A] & [B] -> [C]\n")
        tr = run(sc)
        self.assertEqual([f.episode for f in tr.frames][-1], 2)
        self.assertEqual(sum(1 for ln in tr.end["log"] if "-> [C]" in ln), 2)
        self.assertEqual(tr.frames[-1].nodes["C_service"], "visited")
        self.assertEqual(tr.end["stalled"], [])
        self.assertEqual(tr.end["deposits"], [])
        half = sim.simulate(sc, sim.Scenario("a", entries=("A_service",)))
        self.assertEqual(half.end["stalled"], [])          # a deposit, not a barrier
        self.assertEqual(half.end["deposits"], [{"join": (0, 0), "target": "C_service",
                                                  "arrived": ["A_service"],
                                                  "missing": ["B_service"]}])
        self.assertNotIn("C_service", half.frames[-1].nodes)

    def test_gate_members_deposit_and_go_on(self):
        # both members reached from one caller: the first deposits, the caller goes
        # on to the second, whose arrival fires the target (no stall)
        sc = build("[S] -> [A] : a()\n[S] -> [B] : b()\n[A] & [B] -> [C] : go()\n")
        tr = run(sc)
        self.assertEqual((tr.outcome, tr.end["stalled"], tr.end["deposits"]), ("ok", [], []))
        self.assertEqual(tr.frames[-1].nodes["C_service"], "visited")
        self.assertTrue(logs(tr, "deposit: [A] at [C]"))

    def test_gate_member_on_an_untaken_branch_leaves_its_deposit(self):
        sc = build("[S] -> [A] : a()\n[S] ?> [B] : b()\n[A] & [B] -> [C] : go()\n")
        happy = run(sc)
        self.assertEqual(happy.outcome, "ok")
        self.assertEqual([(d["target"], d["arrived"], d["missing"])
                          for d in happy.end["deposits"]],
                         [("C_service", ["A_service"], ["B_service"])])
        self.assertNotIn("C_service", happy.frames[-1].nodes)
        self.assertEqual(run(sc, "S?>B").end["deposits"], [])

    def test_branch_arms(self):
        sc = build("(U) -> {Req}\nbranch on {Req}.kind {\n"
                   "  read  => [Reader] -> |DB|\n  write => [Writer] -> |DB| -> |WAL|\n}\n")
        self.assertEqual(names(sc), ["happy", "Req.kind=write"])
        happy = run(sc).frames[-1].nodes
        self.assertIn("Reader_service", happy)
        self.assertNotIn("WAL_store", happy)        # DB -> WAL is the write arm's
        write = run(sc, "Req.kind=write").frames[-1].nodes
        self.assertNotIn("Reader_service", write)
        self.assertEqual(write["WAL_store"], "visited")

    def test_parallel_all_failure_takes_the_block_route(self):
        sc = build("(U) -> [Api]\nparallel @all {\n  [Api] -> [Inv] : reserve ×1\n"
                   "  [Api] -> [Fraud] : score\n}\n       !> [Inv] : release\n")
        bad = [n for n in names(sc) if n != "happy"]
        self.assertEqual(bad, ["Api->Inv:fails"])
        self.assertEqual(run(sc).outcome, "ok")
        tr = run(sc, "Api->Inv:fails")
        self.assertEqual(tr.outcome, "failed")
        self.assertEqual(tr.end["routes"], [wire(sc, "Api_service", "Inv_service", "!>")])

    def test_block_failure_takes_the_route_after_a_loop(self):
        sc = build("(U) -> [A]\nloop @times 3 {\n  [A] -> [B] @timeout(1s)\n}\n  !> <LoopFailed>\n")
        tr = run(sc, "A->B:fails")
        self.assertEqual(tr.outcome, "failed")
        self.assertEqual(tr.end["routes"], [wire(sc, "A_service", "LoopFailed_event", "!>")])
        self.assertEqual(tr.frames[-1].nodes["LoopFailed_event"], "visited")

    def test_parallel_any_losers_are_cancelled(self):
        sc = build("(U) -> [A]\nparallel @any {\n  [A] -> [B]\n  [A] -> [C] -> [D]\n}\n")
        nodes = run(sc).frames[-1].nodes
        self.assertEqual(nodes["C_service"], "cancelled")
        self.assertNotIn("D_service", nodes)              # a loser's body never runs
        sc = build("(U) -> [A]\nparallel @any {\n  [A] -> [B]\n  [A] -> [C]\n}\n")
        nodes = run(sc, "A@any=C").frames[-1].nodes
        self.assertEqual((nodes["B_service"], nodes["C_service"]), ("cancelled", "visited"))

    def test_parallel_any_loser_failure_leaves_the_block_ok(self):
        sc = build("(U) -> [A]\nparallel @any {\n  [A] -> [B]\n  [A] -> [C] @timeout(1s)\n}\n"
                   "[B] -> [D] -> [E]\n")
        tr = run(sc, "A->C:fails")
        self.assertEqual(tr.outcome, "ok")
        self.assertEqual(tr.frames[-1].nodes["E_service"], "visited")
        self.assertEqual(run(sc, "A@any=C+A->C:fails").outcome, "failed")

    def test_parallel_any_with_a_chained_member_lists_its_winner(self):
        # C's own part of the block (C -> D) must not replace A's region
        sc = build("(U) -> [A]\nparallel @any {\n  [A] -> [B]\n  [A] -> [C] -> [D]\n}\n")
        self.assertEqual(names(sc), ["happy", "A@any=C"])
        nodes = run(sc, "A@any=C").frames[-1].nodes
        self.assertEqual((nodes["B_service"], nodes["D_service"]), ("cancelled", "visited"))

    def test_parallel_any_winner(self):
        sc = build("(U) -> [Api]\nparallel @any {\n  [Api] -> [MA]\n  [Api] -> [MB]\n}\n")
        self.assertEqual(names(sc), ["happy", "Api@any=MB"])
        nodes = run(sc).frames[-1].nodes
        self.assertEqual(nodes["MA_service"], "visited")
        self.assertEqual(nodes["MB_service"], "cancelled")

    def test_loop_times_capped(self):
        sc = build("(U) -> [P]\nloop @times 5 {\n  [P] -> (Peer)\n}\n")
        tr = run(sc)
        self.assertEqual(len(logs(tr, "iteration")), 2)
        tr = run(sc, limits=sim.Limits(iterations=9))
        self.assertEqual(len(logs(tr, "iteration")), 5)

    def test_nested_loop_member_runs_once_per_iteration(self):
        sc = build("(U) -> [A]\nloop @times 2 {\n  [A] -> [B]\n  [B] -> [C]\n}\n")
        tr = run(sc)
        self.assertEqual(len(logs(tr, "[A] -> [B]")), 2)
        self.assertEqual(len(logs(tr, "[B] -> [C]")), 2)
        self.assertEqual([ln.split(" ", 1)[1] for ln in logs(tr, "iteration")],
                         ["iteration 1/2", "iteration 2/2"])
        loops = [next(iter(f.loops.values())) for f in tr.frames if f.loops]
        self.assertEqual(loops, sorted(loops))       # the outer count never resets
        self.assertEqual(tr.frames[-1].loops, {})

    def test_nested_parallel_member_forks_once(self):
        sc = build("(U) -> [A]\nparallel {\n  [A] -> [B]\n  [B] -> [C]\n}\n")
        tr = run(sc)
        self.assertEqual(tr.outcome, "ok")
        self.assertEqual(len(logs(tr, "[B] -> [C]")), 1)

    def test_self_call_return_runs_once_per_iteration(self):
        text = (_DIR / "language.md").read_text()
        body = text[text.index("### Example 5"):].split("```")[1]
        sc = build(body)
        prog = sim.program(sim.canonical(sc.graph))
        for items in prog.returns.values():
            self.assertTrue(all(isinstance(it, sim.Step) for it in items))
        tr = run(sc)
        self.assertEqual(len(logs(tr, "iteration")), 2)
        self.assertEqual(len(logs(tr, "[Worker] => <ok>")), 2)

    def test_async_alternative_sends_one(self):
        sc = build("(U) -> [A]\n[A] ~> [B] / [C]\n")
        self.assertEqual(names(sc), ["happy", "A/C"])
        happy = run(sc)
        self.assertEqual(len(logs(happy, "send")), 1)
        self.assertIn("B_service", happy.frames[-1].nodes)
        self.assertNotIn("C_service", happy.frames[-1].nodes)
        other = run(sc, "A/C")
        self.assertIn("C_service", other.frames[-1].nodes)
        self.assertNotIn("B_service", other.frames[-1].nodes)

    def test_async_race_sends_the_winner(self):
        sc = build("(U) -> [A]\n[A] ~> [B] &? [C]\n")
        self.assertEqual(names(sc), ["happy", "A&?C"])
        sent = [ln.split(" ", 1)[1] for ln in logs(run(sc, "A&?C"), "send")]
        self.assertEqual(sent, ["send [A] ~> [C]"])

    def test_conditional_join_members_not_taken_by_default(self):
        sc = build("(U) -> [A]\n[A] ?> [B] & [C]\n")
        self.assertEqual(names(sc), ["happy", "A?>B", "A?>C"])
        happy = run(sc).frames[-1].nodes
        self.assertNotIn("B_service", happy)
        self.assertNotIn("C_service", happy)
        nodes = run(sc, "A?>B").frames[-1].nodes
        self.assertEqual(nodes.get("B_service"), "visited")
        self.assertNotIn("C_service", nodes)
        both = run(sc, "A?>B+A?>C").frames[-1].nodes
        self.assertEqual((both["B_service"], both["C_service"]), ("visited", "visited"))

    def test_failing_route_target_is_contained_and_unwound(self):
        sc = build("(U) -> [A]\n[A] -> [B]\n[A] !> [E]\n[A] !> [H]\n"
                   "[E] -> [G]\n[E] !> [F]\n")
        tr = run(sc, "A:fails+E:fails")
        self.assertEqual(tr.outcome, "failed")
        end = tr.frames[-1].nodes
        self.assertFalse({k: v for k, v in end.items() if v in ("waiting", "active")})
        self.assertEqual((end["A_service"], end["E_service"]), ("failed", "failed"))
        self.assertEqual(end["F_service"], "visited")
        self.assertEqual(end["H_service"], "visited")    # the next route still fires
        self.assertEqual(tr.frames[-1].depth, {})

    def test_critical_call_ends_the_run(self):
        sc = build("(U) -> [Api] : {Cart} !\n[Api] -> [Db]\n")
        bad = [n for n in names(sc) if n != "happy"]
        tr = run(sc, bad[0])
        self.assertEqual(tr.outcome, "failed")
        self.assertTrue(tr.frames[-1].done)
        self.assertTrue(logs(tr, "critical"))

    def test_async_failure_never_reaches_the_sender(self):
        sc = build("(U) -> [A]\n[A] ~> [B]\n[B] !> <Oops>\n")
        tr = run(sc, "B:fails")
        self.assertEqual(tr.outcome, "ok")
        self.assertEqual(tr.frames[-1].nodes["A_service"], "visited")
        self.assertEqual(tr.frames[-1].nodes["B_service"], "failed")


# ---------------------------------------------------------------------------
# 5. Termination, determinism, frame invariants
# ---------------------------------------------------------------------------

class TestModelFacts(unittest.TestCase):
    """The P1 model fixes as the simulator reads them: cardinality is no retry
    (CG1) and implied emitters are not entries (B12)."""

    def test_cardinality_is_no_choice_point(self):
        # the phantom `Primary~>Replica:fails` (examples.md L3: [Data])
        sc = build("(Client) -> [Core]\n[Core] := {\n  [LB] -> [App]×N\n}\n"
                   "[Core] -> [Data]\n[Data] := {\n  [Primary] ~> [Replica]×2\n}\n")
        self.assertEqual(names(sc), ["happy"])

    def test_a_retry_still_is(self):
        sc = build("(U) -> [A]\n[A] -> [B] : charge() ×3\n")
        self.assertEqual(names(sc), ["happy", "A.charge:fails"])
        self.assertEqual(len(logs(run(sc, "A.charge:fails"), "attempt ")), 8)

    def test_cardinality_is_the_reach(self):
        sc = build("(U) -> [LB]\n[LB] -> [App]×3\n[LB] -> [Db] ×N\n[LB] -> [One]\n")
        reach = {}
        for f in run(sc).frames:
            for tok in f.tokens:
                reach.setdefault(tok.wire[1], tok.reach)
        self.assertEqual((reach["App_service"], reach["One_service"]), (3, 1))
        self.assertEqual(reach["Db_service"], sim.Limits().spawn)

    def test_implied_emitters_start_no_episode(self):
        sc = build("(U) -> [Judge]\n[Judge] -> [Scorer] : score({Draft}) => <rated>\n"
                   "<rated> -> ~|history| : x\n"
                   "|Replica|\n    \\-{lagging}-! <LagAlarm>\n<LagAlarm> ~> (OnCall)\n"
                   "[Judge] -> |Replica|\n")
        prog = sim.program(sim.canonical(sc.graph))
        self.assertEqual(prog.entries[0], ("U_actor",))
        self.assertEqual(names(sc), ["happy", "Replica?>LagAlarm"])
        self.assertEqual(run(sc).frames[-1].nodes["history_store"], "visited")
        self.assertNotIn("OnCall_actor", run(sc).frames[-1].nodes)
        self.assertEqual(run(sc, "Replica?>LagAlarm").frames[-1].nodes["OnCall_actor"], "visited")


class TestTermination(unittest.TestCase):
    def test_every_scenario_of_every_input_ends(self):
        limits = sim.Limits()
        for path in EXAMPLES + FIXTURES:
            sc = build(path.read_text())
            for s in sim.scenarios(sc):
                with self.subTest(file=path.name, scenario=s.name):
                    tr = sim.simulate(sc, s)
                    self.assertTrue(tr.frames[-1].done)
                    self.assertLessEqual(len(tr.frames), limits.frames)
                    self.assertNotEqual(tr.outcome, "cut")
                    self.assertFalse(any(f.done for f in tr.frames[:-1]))

    def test_async_cycle_ends_by_the_visit_limit(self):
        tr = run(build("(U) -> [A]\n[A] ~> [B]\n[B] ~> [A]\n"))
        self.assertEqual(tr.outcome, "ok")
        self.assertTrue(logs(tr, "visit limit"))

    def test_sync_cycle_ends_by_depth(self):
        tr = run(build("(U) -> [A]\n[A] -> [B]\n[B] -> [A]\n"))
        self.assertEqual(tr.outcome, "ok")
        self.assertTrue(logs(tr, "base case: [A] at depth 3"))

    def test_self_route_cycle_ends_by_depth(self):
        sc = build("(Ops) -> [Worker] : job()\n[Worker] -> |Queue| : pop()\n"
                   "[Worker] !> [Worker] : retry()\n")
        self.assertIn("Worker:fails", names(sc))
        tr = run(sc, "Worker:fails")
        self.assertEqual(tr.outcome, "failed")
        self.assertTrue(logs(tr, "base case: [Worker] at depth 3"))

    def test_two_node_route_cycle_ends_by_depth(self):
        sc = build("(U) -> [A]\n[A] -> [C]\n[A] !> [B]\n[B] -> [C]\n[B] !> [A]\n")
        tr = run(sc, "A:fails+B:fails")
        self.assertEqual(tr.outcome, "failed")
        self.assertTrue(logs(tr, "base case"))
        self.assertTrue(tr.frames[-1].done)

    def test_deep_sync_chain_cuts_by_stack(self):
        text = "(U) -> [N0]\n" + "".join(f"[N{i}] -> [N{i + 1}]\n" for i in range(300))
        tr = run(build(text))
        self.assertEqual((tr.outcome, tr.end["cut"]), ("cut", ["stack"]))
        self.assertTrue(tr.frames[-1].done)
        deep = run(build(text), limits=sim.Limits(stack=400))      # the RecursionError backstop
        self.assertEqual((deep.outcome, deep.end["cut"]), ("cut", ["stack"]))

    def test_frame_cap_cuts(self):
        tr = run(load("01-checkout.sigil"), limits=sim.Limits(frames=10))
        self.assertEqual((len(tr.frames), tr.outcome, tr.end["cut"]), (10, "cut", ["frames"]))

    def test_activation_cap_cuts(self):
        tr = run(load("executions.sigil"), limits=sim.Limits(activations=5))
        self.assertEqual((tr.outcome, tr.end["cut"]), ("cut", ["activations"]))
        self.assertTrue(tr.frames[-1].done)

    def test_frame_and_activation_caps_count_per_episode(self):
        """Many entries each run in full: the caps bound one episode, not the run."""
        one = "(U0) -> [A0] -> [B0] -> [C0]\n"
        many = "".join(f"(U{i}) -> [A{i}] -> [B{i}] -> [C{i}]\n" for i in range(12))
        single = run(build(one))
        caps = sim.Limits(frames=len(single.frames) + 2, activations=4)
        self.assertEqual(run(build(one), limits=caps).outcome, "ok")
        tr = run(build(many), limits=caps)
        self.assertEqual((tr.outcome, tr.end["cut"]), ("ok", []))
        self.assertGreater(len(tr.frames), caps.frames)
        self.assertTrue(logs(tr, "episode 12"))

    def test_keep_false_keeps_the_final_frame(self):
        sc = load("executions.sigil")
        full = sim.simulate(sc, sim.scenarios(sc)[0])
        last = sim.simulate(sc, sim.scenarios(sc)[0], keep=False)
        self.assertEqual(last.frames, full.frames[-1:])
        self.assertEqual((last.outcome, last.end["log"]), (full.outcome, full.end["log"]))
        most = {}
        for f in full.frames:
            for key, k in f.loops.items():
                most[key] = max(most.get(key, 0), k)
        for key, k in most.items():                # end["loops"] sees every iteration
            self.assertGreaterEqual(last.end["loops"][key], k)

    def test_deterministic(self):
        for path in EXAMPLES + FIXTURES:
            sc = build(path.read_text())
            for s in sim.scenarios(sc)[:4]:
                with self.subTest(file=path.name, scenario=s.name):
                    a, b = sim.simulate(sc, s), sim.simulate(build(path.read_text()), s)
                    self.assertEqual(a.frames, b.frames)
                    self.assertEqual(a.end, b.end)

    def test_distinct_scenarios_differ(self):
        sc = load("executions.sigil")
        traces = [sim.simulate(sc, s) for s in sim.scenarios(sc)]
        self.assertEqual(len({tr.end["log"].__repr__() for tr in traces}), len(traces))

    def test_every_scenario_changes_the_run(self):
        # a listed choice point is one the run takes: no scenario equals happy
        for path in EXAMPLES + FIXTURES:
            sc = build(path.read_text())
            listed = sim.scenarios(sc)
            happy = sim.simulate(sc, listed[0]).frames
            for s in listed[1:]:
                with self.subTest(file=path.name, scenario=s.name):
                    self.assertNotEqual(sim.simulate(sc, s).frames, happy)

    def test_frame_invariants(self):
        sc = load("coverage.sigil")
        for s in sim.scenarios(sc)[:5]:
            tr = sim.simulate(sc, s)
            idents = {w.ident for w in tr.scene.wires}
            for i, f in enumerate(tr.frames):
                self.assertEqual(f.tick, i)
                self.assertTrue(f.held <= f.lit)
                for t in f.tokens:
                    self.assertTrue(0.0 <= t.at <= 1.0)
                    self.assertIn(t.wire, idents)
                self.assertEqual([t.task for t in f.tokens if t.state != "cancelled"],
                                 sorted(t.task for t in f.tokens if t.state != "cancelled"))
                for line in f.log:
                    self.assertTrue(line.startswith(f"t{i:03} "), line)
                    self.assertNotIn("\x1b", line)

    def test_conventions_logged_first(self):
        tr = run(load("01-checkout.sigil"))
        self.assertIn("conventions:", tr.frames[0].log[0])
        self.assertTrue(tr.frames[-1].log[-1].endswith("done: ok"))

    def test_any_scene_of_the_document_gives_one_trace(self):
        text = (_DIR / "site" / "examples" / "04-orders.sigil").read_text()
        a = run(build(text))
        b = run(build(text, events="land", depth=0))
        self.assertEqual(a.frames, b.frames)


# ---------------------------------------------------------------------------
# 6. project()
# ---------------------------------------------------------------------------

class TestProject(unittest.TestCase):
    def setUp(self):
        self.text = (_DIR / "site" / "examples" / "04-orders.sigil").read_text()
        self.trace = run(build(self.text))

    def test_identity_on_the_canonical_scene(self):
        same = sim.project(self.trace, sim.canonical(self.trace.scene.graph))
        self.assertEqual(same.frames, self.trace.frames)

    def test_land_mode_one_token_per_emit_wire_per_leg(self):
        land = build(self.text, events="land")
        p = sim.project(self.trace, land)
        emits = {w.ident for w in land.wires if w.role == "emit"}
        in_leg = p.frames[12].tokens         # `[Checkout] ~> <Placed>` at .5
        self.assertEqual(len(in_leg), 2)
        self.assertTrue(all(t.wire in emits and t.at == 0.25 for t in in_leg))
        out_leg = p.frames[17].tokens        # the triggers at .5
        self.assertEqual(sorted(t.at for t in out_leg), [0.75, 0.75])
        self.assertTrue(all(len({t.wire for t in f.tokens}) == len(f.tokens) for f in p.frames))
        self.assertNotIn("Placed_event", p.frames[-1].nodes)
        self.assertEqual(p.scene, land)

    def test_shallow_depth_owners_carry_the_state(self):
        d0 = build(self.text, depth=0)
        p = sim.project(self.trace, d0)
        owners = {w.ident for w in d0.wires if w.role == "trigger"}
        toks = p.frames[19].tokens
        self.assertEqual({t.wire for t in toks},
                         {("Placed_event", "Order_data", "trigger", 0),
                          ("Placed_event", "Checkout_service", "trigger", 0)})
        self.assertTrue({t.wire for t in toks} <= owners)
        self.assertEqual(p.frames[-1].machines, self.trace.frames[-1].machines)

    def test_undrawn_unit_folds_into_its_owner(self):
        text = (_DIR / "site" / "examples" / "02-shop.sigil").read_text()
        tr = run(build(text))
        p = sim.project(tr, build(text, depth=0))
        busy = [f for f in p.frames if f.nodes.get("Shop_service") == "active"]
        inside = [f for f in tr.frames if f.nodes.get("Cart_service") == "active"]
        self.assertTrue(inside)
        self.assertTrue(busy)
        self.assertNotIn("Cart_service", p.frames[-1].nodes)



# ---------------------------------------------------------------------------
# 7. failure_flow() and the public static helpers
# ---------------------------------------------------------------------------

ALL = sim.Limits(scenarios=10 ** 6)


def corpus() -> list:
    """Every golden input plus every language.md block: (name, text)."""
    spec = golden.examples_inputs((_DIR / "language.md").read_text(encoding="utf-8"))
    return ([(i.name, i.text) for i in golden.collect_inputs(_DIR)]
            + [("language-" + i.name, i.text) for i in spec])


def worked_example(title: str) -> str:
    """The corpus name of the first Sigil block under language.md's `### {title}`
    heading, so spec edits that renumber the blocks do not shift a key."""
    text = (_DIR / "language.md").read_text(encoding="utf-8")
    at = text.index(f"### {title}")
    fences = [m for m in golden._FENCE.finditer(text) if m.group(1) != "text"]
    k = next(k for k, m in enumerate(fences) if m.start() > at)
    return "language-" + golden.examples_inputs(text)[k].name


def routes_of(prog) -> dict:
    return {w.ident: w for rs in prog.routes.values() for w, _g in rs}


def fired(sc, picked) -> set:
    return {r for s in picked for r in sim.simulate(sc, s).end["routes"]}


def fired_in_pairs(sc, singles) -> set:
    """The routes some combination of two deviations fires."""
    out = set()
    for i, a in enumerate(singles):
        for b in singles[i + 1:]:
            out |= fired(sc, [sim.scenario(sc, f"{a.name}+{b.name}", limits=ALL)])
    return out


class TestFailureFlow(unittest.TestCase):
    """CG7: a route is live per failure_flow iff some scenario fires it — one
    deviation, or (for a route behind a route or an arm) two."""

    # Dead in both until the simulator defects were fixed (RFC 0003 catalog §6):
    # a `*>` / `&` member's failure reached its line's route as None (B1); a
    # `parallel @all` member got no failure scenario of its own (B2). No corpus
    # route is dead now.
    FIXED = {("coverage", 72): "B1", ("examples-04", 7): "B1",
             (worked_example("Example 4:"), 5): "B1", ("coverage", 141): "B2"}
    KNOWN_DEAD: dict = {}

    def test_live_iff_fired_over_the_corpus(self):
        for name, text in corpus():
            sc = build(text)
            prog = sim.program(sim.canonical(sc.graph))
            live = sim.failure_analysis(prog).live
            singles = sim.scenarios(sc, limits=ALL)[1:]
            got = fired(sc, singles)
            if live - got:
                got |= fired_in_pairs(sc, singles)
            for ident, w in routes_of(prog).items():
                with self.subTest(doc=name, line=w.line, route=ident):
                    self.assertEqual(ident in live, ident in got)
                    if ident not in live:
                        self.assertIn((name, w.line), self.KNOWN_DEAD)

    def test_routes_the_fixes_revived_fire(self):
        docs = dict(corpus())
        for (name, line), defect in self.FIXED.items():
            with self.subTest(doc=name, line=line, defect=defect):
                sc = build(docs[name])
                prog = sim.program(sim.canonical(sc.graph))
                live = sim.failure_analysis(prog).live
                (ident,) = [i for i, w in routes_of(prog).items() if w.line == line]
                self.assertIn(ident, live)
                self.assertIn(ident, fired(sc, sim.scenarios(sc, limits=ALL)[1:]))

    def probe(self, text: str):
        sc = build(text)
        prog = sim.program(sim.canonical(sc.graph))
        ff = sim.failure_analysis(prog)
        singles = sim.scenarios(sc, limits=ALL)[1:]
        got = fired(sc, singles) | fired_in_pairs(sc, singles)
        self.assertEqual({i for i in routes_of(prog) if i in ff.live},
                         {i for i in routes_of(prog) if i in got})
        return ff, {w.dst: w.ident in ff.live for w in routes_of(prog).values()}

    def test_dead_routes(self):
        for text in [
                # a `~>` send never consults its call outcome; its failure stops there
                "(U) -> [A]\n[A] ~> [B] : go() @timeout(1s)\n     !> <Failed>\n",
                # a loop that runs no time
                "(U) -> [A]\nloop @times 0 {\n  [A] -> [B] : x() ×2\n} !> <Failed>\n",
                # a critical call ends the run: no route fires
                "(U) -> [A]\n[A] -> [B] : pay() !\n     !> <Failed>\n",
                # parallel @none forks and does not wait
                "(U) -> [A]\nparallel @none {\n  [A] -> [B] : f() ×2\n} !> <Failed>\n"]:
            with self.subTest(text=text):
                _ff, live = self.probe(text)
                self.assertEqual(live, {"Failed_event": False})

    def test_a_fallback_absorbs_and_its_routes_still_fire(self):
        ff, live = self.probe("(U) -> [A]\n[A] -> (Ext) : op x.get() @timeout(1s) "
                              "@fallback(${c})\n     !> <Failed>\n")
        self.assertEqual(live, {"Failed_event": True})
        self.assertEqual(ff.arriving[(0, "A_service")], frozenset())
        self.assertEqual(ff.absorbed[(0, "A_service")],
                         {("call", wire(build("(U) -> [A]\n[A] -> (Ext) : op x.get() "
                                              "@timeout(1s) @fallback(${c})\n"),
                                        "A_service", "Ext_actor", "->"))})

    def test_route_induced_sources(self):
        """route_induced=False: a route alone makes nothing fail, so a route over a
        plain call (or a node's own outcome) is dead; an external call still fails."""
        text = ("(U) -> [A]\n[A] -> [B] : f()\n     !> <Guarded>\n(U) -> [D]\n[D] !> <Any>\n"
                "(U) -> [C]\n[C] -> (Ext) : op x.get()\n     !> <ExtFailed>\n")
        prog = sim.program(sim.canonical(build(text).graph))
        names = lambda ff: {routes_of(prog)[i].dst for i in ff.live}
        self.assertEqual(names(sim.failure_analysis(prog)),
                         {"Guarded_event", "Any_event", "ExtFailed_event"})
        self.assertEqual(names(sim.failure_analysis(prog, route_induced=False)),
                         {"ExtFailed_event"})
        cids = {p.cid[0] for p in sim.choice_points(prog, route_induced=False)}
        self.assertEqual(cids, {"call"})
        self.assertEqual(len(sim.choice_points(prog, route_induced=False)), 1)

    def test_a_policy_reads_the_same_in_either_place(self):
        """scene.call_policy: `[A] @timeout(2s) -> [B] : f()` and the trailing
        `[A] -> [B] : f() @timeout(2s)` are one policy, so one choice point, one
        failure flow and the same runs."""
        def facts(stmt):
            sc = build(f"(U) -> [A]\n{stmt}\n")
            prog = sim.program(sim.canonical(sc.graph))
            points = [(p.cid, p.options, p.names)
                      for p in sim.choice_points(prog, route_induced=False)]
            outcomes = [(s.name, run(sc, s.name).outcome) for s in sim.scenarios(sc)]
            return points, sim.failure_flow(prog), outcomes
        for policy in ("@timeout(2s)", "@deadline(5s)", "@fallback(none)"):
            with self.subTest(policy=policy):
                before = facts(f"[A] {policy} -> [B] : f()")
                after = facts(f"[A] -> [B] : f() {policy}")
                self.assertTrue(before[0], "a guarded call is a choice point")
                self.assertEqual(before, after)

    def test_guards_name_what_failed(self):
        ff, live = self.probe("(U) -> [A]\nloop @times 3 {\n  [A] -> [B] : x() ×2\n}"
                              " !> <LoopFailed>\n[A] !> <Any>\n")
        self.assertEqual(ff.arriving[(0, "A_service")], {("block", 0)})
        self.assertEqual(live, {"LoopFailed_event": True, "Any_event": False})
        ff, _live = self.probe("(U) -> [A]\n(U) -> [B]\n[A] & [B] -> [C]\n"
                               "[C] -> [D] : f() ×2\n[A] !> <AF>\n")
        self.assertIn(("node", "C_service"), ff.arriving[(0, "A_service")])
        ff, _live = self.probe("(U) -> [A]\n[A] := {\n  [In] -> [Db] : q() ×2\n}\n"
                               "[A] !> <AF>\n")
        self.assertIn(("node", "In_service"), ff.arriving[(0, "A_service")])

    def test_routes_behind_a_route_or_an_arm_need_two_deviations(self):
        for text, target in [
                ("(U) -> [A]\n[A] -> [B] : f() ×2\n     !> [H]\n"
                 "[H] -> [I] : g() ×2\n     !> <HF>\n", "HF_event"),
                ("branch on kind {\n  a => [B] -> [C] : f() ×2\n"
                 "  b => [D] -> [E] : g() ×2\n}\n[B] !> <BF>\n[D] !> <DF>\n", "DF_event")]:
            with self.subTest(target=target):
                _ff, live = self.probe(text)
                self.assertTrue(live[target])

    def test_failure_flow_is_the_arriving_map(self):
        prog = sim.program(sim.canonical(load("executions.sigil").graph))
        self.assertEqual(sim.failure_flow(prog), sim.failure_analysis(prog).arriving)
        self.assertEqual(sim.failure_flow(prog), sim.failure_flow(prog))


# ---------------------------------------------------------------------------
# 8. The simulator defect fixes (RFC 0003 catalog §6) and NG6
# ---------------------------------------------------------------------------

STREAM = ("(U) -> [In]\n[In] => *<Raw>^10k@drop\n*<Raw> -> [Parse] => *<Parsed>^10k\n"
          "*<Parsed> *> |Warehouse| & |Index|\n          !> |DLQ|\n")


SHOP = "(U) -> [Shop]\n[Shop] ~> <Paid>\n[Shop] ~> <Paid>\nstate {Order} {\n"
WILDCARD_ONLY = SHOP + "  + -<Paid>-> A\n  _ -<Paid>-> Weird\n  _ -<Paid>-> Other\n}\n"
JOIN_206 = "[S] -> [A] : a()\n[S] ?> [B] : b()\n[A] & [B] -> [C] : go() @timeout(5s)\n"
# Beyond the golden corpus: a `_`-only machine ambiguity, a source join whose
# members are choice points (Q3), and every checks fixture.
B3_PROBES = ([("wildcard-only", WILDCARD_ONLY), ("join-206", JOIN_206)]
             + [(p.stem, p.read_text()) for p in
                sorted((_DIR / "tests" / "fixtures" / "checks").glob("*.sigil"))])


def _changes_with_another(sc, s, listed) -> bool:
    """Whether s changes the trace of some other single deviation it joins."""
    for o in listed[1:]:
        if o is s:
            continue
        both = sim.scenario(sc, f"{o.name}+{s.name}", limits=ALL)
        if sim.simulate(sc, both).end["log"] != sim.simulate(sc, o).end["log"]:
            return True
    return False


class TestDefectFixes(unittest.TestCase):
    def test_b1_a_fan_out_member_failure_fires_its_lines_route(self):
        sc = build(STREAM)
        dlq = wire(sc, "Parsed_event", "DLQ_store", "!>")
        for name in ("Parsed*>Warehouse:fails", "Parsed*>Index:fails"):
            with self.subTest(name=name):
                tr = run(sc, name)
                self.assertEqual(tr.end["routes"], [dlq])
                (fail,) = [e for e in tr.end["events"] if e["kind"] == "route"]
                self.assertEqual(fail["guard"][0], "call")

    def test_b1_a_join_target_member_failure_fires_its_lines_route(self):
        sc = build("(U) -> [A]\n[A] -> [B] & [C] : f() ×2\n     !> <Failed>\n")
        for s in sim.scenarios(sc)[1:]:
            with self.subTest(scenario=s.name):
                tr = sim.simulate(sc, s)
                self.assertEqual(tr.end["routes"], [wire(sc, "A_service", "Failed_event", "!>")])

    def test_b2_block_members_fail_when_only_the_route_says_so(self):
        sc = build("(U) -> [Api]\nparallel @all {\n  [Api] -> [Inv] : reserve\n"
                   "  [Api] -> [Fraud] : score\n}\n       !> [Inv] : release\n")
        self.assertEqual(names(sc), ["happy", "Api->Inv:fails", "Api->Fraud:fails"])
        route = wire(sc, "Api_service", "Inv_service", "!>")
        for name in names(sc)[1:]:
            with self.subTest(name=name):
                self.assertEqual(run(sc, name).end["routes"], [route])

    def test_b2_values_and_sends_in_a_block_are_no_choice(self):
        sc = build("(U) -> [A]\nparallel @all {\n  [A] -> {Report}\n  [A] ~> [B]\n}\n"
                   "     !> <Failed>\n")
        self.assertEqual(names(sc), ["happy"])

    def test_b3_a_failing_send_never_arrives_and_the_sender_goes_on(self):
        sc = build("(U) -> [A]\n[A] ~> [B] : go() ×2\n[B] -> [C]\n")
        self.assertEqual(names(sc), ["happy", "A.go:fails"])
        tr = run(sc, "A.go:fails")
        self.assertEqual(tr.outcome, "ok")
        self.assertEqual(len(logs(tr, "failed")), 5)        # 3 attempts, the call, the stop
        self.assertNotIn("C_service", tr.frames[-1].nodes)
        self.assertTrue(logs(tr, "[B] failed (not awaited)"))

    def test_b3_every_listed_deviation_changes_the_trace_over_the_corpus(self):
        """A deviation whose choice point the happy run meets changes the trace
        alone; one behind another deviation (a `?>` not taken by default) changes
        it together with some other listed one."""
        for name, text in corpus() + B3_PROBES:
            sc = build(text)
            listed = sim.scenarios(sc, limits=ALL)
            happy = sim.simulate(sc, listed[0])
            met = {e["cid"] for e in events(happy, "choice")}
            for s in listed[1:]:
                with self.subTest(doc=name, scenario=s.name):
                    ((cid, _opt),) = s.choices
                    if cid in met:
                        self.assertNotEqual(sim.simulate(sc, s).end["log"], happy.end["log"])
                    else:
                        self.assertTrue(_changes_with_another(sc, s, listed))

    def test_b4_a_branch_on_a_field_runs(self):
        sc = build("(U) -> [Api] : req({Request})\nbranch on {Request}.kind {\n"
                   "  read  => [Api] -> |Cache|\n  write => [Api] -> |DB|\n}\n")
        self.assertEqual(names(sc), ["happy", "Request.kind=write"])
        self.assertEqual(run(sc).frames[-1].nodes.get("Cache_store"), "visited")
        tr = run(sc, "Request.kind=write")
        self.assertEqual(tr.frames[-1].nodes.get("DB_store"), "visited")
        self.assertNotIn("Cache_store", tr.frames[-1].nodes)

    def test_b13_a_failure_behind_a_stream_stops_at_its_consumer(self):
        sc = build("(U) -> [A]\n[A] => *<S>^4\n*<S> -> [B] : f() ×2\n")
        tr = run(sc, "S.f:fails")
        self.assertEqual(tr.outcome, "ok")
        self.assertEqual(tr.frames[-1].nodes["A_service"], "visited")
        self.assertTrue(logs(tr, "*<S> failed (not awaited)"))
        prog = sim.program(sim.canonical(sc.graph))
        ff = sim.failure_flow(prog)
        self.assertEqual(ff[(0, "A_service")], frozenset())
        self.assertEqual(ff[(0, "S_event")], {("call", wire(sc, "S_event", "B_service", "->"))})

    def test_b13_the_stream_examples_route_fires_and_the_producer_goes_on(self):
        sc = build(STREAM)
        tr = run(sc, "Parsed*>Index:fails")
        self.assertEqual(tr.outcome, "ok")
        self.assertEqual([e["how"] for e in tr.end["events"] if e["kind"] == "stop"],
                         ["unawaited"])

    def test_ng6_a_specific_transition_beats_the_wildcard(self):
        sc = build("(U) -> [A]\n[A] ~> <Paid>\nstate {X} {\n  _ -<Paid>-> Weird\n"
                   "  + -<Paid>-> Done\n  Done -<Paid>-> Done\n}\n")
        self.assertEqual(names(sc), ["happy"])          # no ambiguity left to choose
        self.assertEqual(run(sc).end["machines"], {"X_data": "X_state_Done"})

    def test_ng6_two_deliveries_across_a_state_change_resolve_on_arrival(self):
        """Both `<Paid>` are delivered in the start state; the second arrives after
        the first moved the machine to Open, where Open's own transition takes it
        (no false `ignored`)."""
        sc = build(SHOP + "  + -<Init>-> Idle\n  _ -<Paid>-> Open\n  Open -<Paid>-> Done\n}\n")
        tr = run(sc)
        self.assertEqual(tr.end["machines"], {"Order_data": "Order_state_Done"})
        self.assertEqual([line.split(" ", 1)[1] for line in logs(tr, "-<Paid>->")],
                         ["{Order} + -<Paid>-> Open", "{Order} Open -<Paid>-> Done"])
        self.assertEqual(events(tr, "ignored"), [])

    def test_ng6_a_second_delivery_rematches_in_the_state_the_first_reached(self):
        """`+ -<Paid>-> Settled` then `Settled -<Paid>-> Settled`: the second
        `<Paid>` takes Settled's own transition, never a phantom `ignored`."""
        sc = build(SHOP + "  + -<Paid>-> Settled\n  Settled -<Paid>-> Settled\n}\n")
        tr = run(sc)
        self.assertEqual([line.split(" ", 1)[1] for line in logs(tr, "-<Paid>->")],
                         ["{Order} + -<Paid>-> Settled", "{Order} Settled -<Paid>-> Settled"])
        self.assertEqual(events(tr, "ignored"), [])

    def test_a_delivery_is_judged_after_the_senders_earlier_trigger_lands(self):
        """Per-sender FIFO: `<Placed>` then `<Paid>` from one sender — `<Paid>` is
        judged in Open, where `<Placed>` takes the machine, not dropped in `+`."""
        sc = build("(U) -> [Shop]\n[Shop] ~> <Placed>\n[Shop] ~> <Paid>\nstate {Order} {\n"
                   "  + -<Placed>-> Open\n  Open -<Paid>-> Settled\n}\n")
        tr = run(sc)
        self.assertEqual(tr.end["machines"], {"Order_data": "Order_state_Settled"})
        self.assertEqual(events(tr, "ignored"), [])

    def test_ng6_a_deviation_on_the_state_reached_by_an_earlier_delivery_is_honoured(self):
        sc = build(SHOP + "  + -<Paid>-> Open\n  Open -<Paid>-> Done\n  _ -<Paid>-> Weird\n"
                   "  Open -<Paid>-> Twice\n}\n")
        self.assertEqual(names(sc), ["happy", "Order.Open-<Paid>->Twice"])
        self.assertEqual(run(sc).end["machines"], {"Order_data": "Order_state_Done"})
        self.assertEqual(run(sc, "Order.Open-<Paid>->Twice").end["machines"],
                         {"Order_data": "Order_state_Twice"})

    def test_ng6_a_wildcard_ambiguity_is_chosen_by_its_written_source(self):
        sc = build(WILDCARD_ONLY)
        self.assertEqual(names(sc), ["happy", "Order._-<Paid>->Other"])
        self.assertEqual(run(sc).end["machines"], {"Order_data": "Order_state_Weird"})
        self.assertEqual(run(sc, "Order._-<Paid>->Other").end["machines"],
                         {"Order_data": "Order_state_Other"})

    def test_q3_a_deposit_is_no_failure_choice_point(self):
        # a member deposits and goes on, so it cannot time out: the join's
        # @timeout bounds the target's wait for the missing member (the open
        # deposit), not the arriver's call — the catalog's SGC206 Declared twin
        sc = build(JOIN_206)
        self.assertEqual(names(sc), ["happy", "S?>B"])
        happy = run(sc)
        self.assertEqual(happy.outcome, "ok")
        self.assertEqual(events(happy, "fail"), [])
        self.assertEqual([d["missing"] for d in happy.end["deposits"]], [["B_service"]])
        both = run(sc, "S?>B")
        self.assertEqual([e["node"] for e in events(both, "gate-arrive")],
                         ["A_service", "B_service"])
        self.assertEqual([e["node"] for e in events(both, "gate-fire")], ["C_service"])
        self.assertEqual(both.end["deposits"], [])
        ff = sim.failure_flow(sim.program(sim.canonical(sc.graph)))
        self.assertEqual(ff[(0, "A_service")], frozenset())

    def test_ng6_the_wildcard_still_takes_what_nothing_specific_does(self):
        sc = build("(U) -> [A]\n[A] ~> <Stop>\nstate {X} {\n  + -<Go>-> Run\n"
                   "  _ -<Stop>-> Halted\n}\n")
        self.assertEqual(run(sc).end["machines"], {"X_data": "X_state_Halted"})


# ---------------------------------------------------------------------------
# 9. Structured events (Trace.end["events"])
# ---------------------------------------------------------------------------

def events(trace, kind: str) -> list:
    return [e for e in trace.end["events"] if e["kind"] == kind]


class TestEvents(unittest.TestCase):
    def test_every_event_names_its_kind_tick_task_and_episode(self):
        for path in EXAMPLES + FIXTURES:
            sc = build(path.read_text())
            for s in sim.scenarios(sc)[:4]:
                tr = sim.simulate(sc, s)
                with self.subTest(file=path.name, scenario=s.name):
                    ticks = [e["t"] for e in tr.end["events"]]
                    self.assertEqual(ticks, sorted(ticks))
                    for e in tr.end["events"]:
                        self.assertLessEqual({"kind", "t", "task", "episode"}, set(e))

    def test_forks_name_their_parent_and_why(self):
        sc = build("(U) -> [A]\n[A] ~> [B]\n[A] *> [C] & [D]\n")
        tr = run(sc)
        forks = [(e["task"], e["parent"], e["why"]) for e in events(tr, "fork")]
        self.assertEqual(forks, [(1, None, "entry"), (2, 1, "async"), (3, 1, "fan"),
                                 (4, 1, "fan")])
        (aw,) = events(tr, "await")
        self.assertEqual((aw["task"], aw["members"]), (1, [3, 4]))
        self.assertEqual([e["task"] for e in events(tr, "resume")], [1])
        self.assertEqual({e["task"]: e["how"] for e in events(tr, "end")},
                         {1: "ok", 2: "ok", 3: "ok", 4: "ok"})

    def test_a_trigger_task_is_forked_by_the_delivering_task(self):
        tr = run(load("04-orders.sigil"))
        triggers = events(tr, "fork")
        delivered = [e for e in triggers if e["why"] == "trigger"]
        self.assertTrue(delivered)
        tasks = {e["task"] for e in triggers}
        self.assertTrue(all(e["parent"] in tasks for e in delivered))
        self.assertEqual([(e["owner"], e["dst"]) for e in events(tr, "transition")][:2],
                         [("Order_data", "Order_state_Open"),
                          ("Checkout_service", "Checkout_state_Busy")])

    def test_episode_is_recorded_at_fork(self):
        sc = build("[A] & [B] -> [C]\n")
        tr = run(sc)
        self.assertEqual([(e["task"], e["episode"]) for e in events(tr, "fork")],
                         [(1, 1), (2, 2)])
        arrive = events(tr, "gate-arrive")
        self.assertEqual([(e["task"], e["node"], e["round"]) for e in arrive],
                         [(1, "A_service", 0), (2, "B_service", 0)])
        (fire,) = events(tr, "gate-fire")
        self.assertEqual((fire["task"], fire["node"], fire["key"]), (2, "C_service", (0, 0, "C_service")))

    def test_access_events_carry_mode_and_held_stores(self):
        sc = build("(U) -> [W]\n[W] @owns |S| {\n  [W] -> |S| : put(x)\n}\n"
                   "[W] -> |S| : get() => {Row}\n[W] -> |T| : op db.insert(x) @timeout(1s)\n")
        happy = run(sc)
        got = [(e["store"], e["mode"], e["held"], e["outcome"]) for e in events(happy, "access")]
        self.assertEqual(got, [("S_store", "write", ["S_store"], "done"),
                               ("S_store", "read", [], "done"),
                               ("T_store", "write", [], "done")])
        failed = run(sc, "W.db.insert:fails")
        self.assertEqual([(e["store"], e["outcome"]) for e in events(failed, "access")][-1],
                         ("T_store", "unknown"))

    def test_failures_routes_and_stops(self):
        tr = run(load("04-orders.sigil"), "Payments:fails")
        (fail,) = events(tr, "fail")
        self.assertEqual(fail["origin"], ("node", "Payments_service"))
        (route,) = events(tr, "route")
        self.assertEqual((route["node"], route["guard"]), ("Payments_service", None))
        self.assertEqual([e["how"] for e in events(tr, "stop")], ["entry"])

    def test_a_fallback_stops_its_failure(self):
        sc = build("(U) -> [A]\n[A] -> (Ext) : op x.get() @timeout(1s) @fallback(none)\n")
        tr = run(sc, "A.x.get:fallback")
        (fail,) = events(tr, "fail")
        self.assertTrue(fail["fallback"])
        self.assertEqual([e["how"] for e in events(tr, "stop")], ["fallback"])
        self.assertEqual(tr.outcome, "ok")

    def test_limits(self):
        cases = [("(U) -> [A]\n[A] -> [A] : again()\n", "depth"),
                 ("[P] -> [Q]\n[Q] ~> [R]\n[R] ~> [Q]\n", "visits"),
                 ("(U) -> [A]\nloop @times 5 {\n  [A] -> |Q| : push()\n}\n", "iterations")]
        for text, name in cases:
            with self.subTest(limit=name):
                self.assertIn(name, [e["name"] for e in events(run(build(text)), "limit")])
        tr = run(build("(U) -> [A]\nloop @times 5 {\n  [A] -> |Q| : push()\n}\n"))
        self.assertTrue(logs(tr, "loop capped: @times 5 runs 2"))
        cut = sim.simulate(load("coverage.sigil"), sim.scenarios(load("coverage.sigil"))[0],
                           limits=sim.Limits(frames=10))
        self.assertEqual([e["name"] for e in events(cut, "limit")][-1], "frames")

    def test_ignored_deliveries(self):
        sc = build("(U) -> [A]\n[A] ~> <Go>\n[A] ~> <Go>\n"
                   "state {X} {\n  Idle -<Go>-> Busy\n}\n<Go> -> {X}\n")
        (ign,) = events(run(sc), "ignored")
        self.assertEqual((ign["owner"], ign["state"], ign["label"]),
                         ("X_data", "X_state_Busy", "<Go>"))

    def test_sgc206_probe_is_quiet_and_its_flagged_twin_leaves_a_deposit(self):
        probe = run(build("[S] -> [A] : a()\n[S] -> [B] : b()\n[A] & [B] -> [C] : go()\n"))
        self.assertEqual((probe.end["stalled"], probe.end["deposits"]), ([], []))
        self.assertEqual([e["node"] for e in events(probe, "gate-arrive")],
                         ["A_service", "B_service"])
        self.assertEqual(len(events(probe, "gate-fire")), 1)
        self.assertEqual([e["waiting"] for e in events(probe, "quiet")], [[]])
        flagged = run(build("[S] -> [A] : a()\n[S] ?> [B] : b()\n[A] & [B] -> [C] : go()\n"))
        self.assertEqual([d["missing"] for d in flagged.end["deposits"]], [["B_service"]])
        self.assertEqual(events(flagged, "gate-fire"), [])

    def test_quiet_names_the_tasks_left_waiting(self):
        tr = run(build("(U) -> [A]\n[A] *> [B] & [C]\n"))
        self.assertEqual([e["waiting"] for e in events(tr, "quiet")], [[]])

    def test_choices_record_what_a_run_met(self):
        sc = load("01-checkout.sigil")
        tr = run(sc, "API.charge:fails")
        met = [e for e in events(tr, "choice") if not e["default"]]
        self.assertEqual([e["option"] for e in met], ["fails"])

    def test_events_are_deterministic(self):
        sc = load("coverage.sigil")
        a, b = run(sc), run(load("coverage.sigil"))
        self.assertEqual(a.end["events"], b.end["events"])


# ---------------------------------------------------------------------------
# 10. combinations() — bounded k-deviation exploration (MG10)
# ---------------------------------------------------------------------------

CROSS_EPISODE = ("(A) -> [P]\n[P] -> (Ext) : op x.get() @timeout(1s)\n  !> <Declined>\n"
                 "(B) -> [Q]\n[Q] -> (Ext) : op y.get() @timeout(1s)\n  !> <Voided>\n"
                 "state {Trip} {\n  + -<Declined>-> Cancelled\n  + -<Voided>-> Void\n"
                 "  Void -<Declined>-> Void\n}\n")


class TestCombinations(unittest.TestCase):
    def test_k1_is_happy_and_every_single_deviation(self):
        sc = load("executions.sigil")
        ex = sim.combinations(sc, 1)
        self.assertEqual([t.scenario.name for t in ex.traces], names(sc))
        self.assertEqual((ex.duplicates, ex.left_out), (0, 0))

    def test_k0_is_the_happy_run(self):
        ex = sim.combinations(load("executions.sigil"), 0)
        self.assertEqual([t.scenario.name for t in ex.traces], ["happy"])

    def test_pairs_grow_only_along_a_dependency(self):
        # Push's call is met only when Router?>Push is taken, so alone it repeats
        # the happy run and grows nothing; V's failure, in the last episode, meets
        # no choice point after it. Router?>Push pairs with what its run meets
        # later: Push's call, and V's call in the next episode (state outlives one)
        sc = build("(U) -> [Router]\n[Router] ?> [Push] : notify()\n"
                   "[Push] -> (Ext) : op p.send() @timeout(1s)\n"
                   "(V) -> [Other] : op o.get() @timeout(1s)\n")
        ex = sim.combinations(sc, 2)
        pairs = [t.scenario.name for t in ex.traces if len(t.scenario.choices) == 2]
        self.assertEqual(pairs, ["Router?>Push+Push.p.send:fails", "Router?>Push+V.o.get:fails"])
        both = next(t for t in ex.traces if len(t.scenario.choices) == 2)
        self.assertEqual(both.scenario.choices,
                         sim.scenario(sc, "Router?>Push+Push.p.send:fails").choices)

    def test_a_deviation_pairs_with_one_it_enables_in_a_later_episode(self):
        # P's failure in episode 1 moves {Trip} to Cancelled; only then does Q's
        # failure in episode 2 deliver <Voided> to a state that ignores it
        sc = build(CROSS_EPISODE)
        ex = sim.combinations(sc, 2)
        self.assertEqual([t.scenario.name for t in ex.traces],
                         ["happy", "P.x.get:fails", "Q.y.get:fails",
                          "P.x.get:fails+Q.y.get:fails"])
        self.assertEqual([e["label"] for t in ex.traces for e in events(t, "ignored")],
                         ["<Voided>"])
        self.assertEqual(sim.combinations(sc, 1).traces[-1].scenario.name, "Q.y.get:fails")

    def test_runs_that_repeat_are_dropped(self):
        sc = load("coverage.sigil")
        ex = sim.combinations(sc, 3)
        logs_seen = [tuple(t.end["log"]) for t in ex.traces]
        self.assertEqual(len(logs_seen), len(set(logs_seen)))
        self.assertGreater(ex.duplicates, 0)

    def test_the_budget_counts_what_it_left_out(self):
        sc = load("coverage.sigil")
        full = sim.combinations(sc, 1)
        cut = sim.combinations(sc, 1, budget=3)
        self.assertEqual(len(cut.traces), 4)
        self.assertEqual(cut.left_out, len(full.traces) - 4)
        self.assertEqual([t.scenario for t in cut.traces], [t.scenario for t in full.traces[:4]])

    def test_deterministic(self):
        sc = load("coverage.sigil")
        a, b = sim.combinations(sc, 2), sim.combinations(load("coverage.sigil"), 2)
        self.assertEqual([t.scenario for t in a.traces], [t.scenario for t in b.traces])


class TestStaticHelpers(unittest.TestCase):
    """MG4 and the SGC090 loop cap: the public static helpers."""

    def test_loop_count_caps_the_declared_times(self):
        g = render.parse_document("(U) -> [A]\nloop @times 5 {\n  [A] -> |Q| : push()\n}\n"
                                  "loop {\n  [A] -> |R| : push()\n}\n")
        counts = [sim.loop_count(b, sim.Limits()) for b in g.blocks]
        self.assertEqual(counts, [2, 2])
        self.assertEqual(sim.loop_count(g.blocks[0], sim.Limits(iterations=9)), 5)

    def test_reachable_and_route_guard(self):
        sc = build("(U) -> [A]\n[A] -> [B] : f() ×2\n     !> <F>\n[Z] -> [Y]\n")
        prog = sim.program(sim.canonical(sc.graph))
        _wires, nodes, _regions = sim.reachable(prog)
        self.assertIn((0, "B_service"), nodes)
        (w, guard), = prog.routes[(0, "A_service")]
        unit = [x for x in prog.scene.wires if x.role == "flow"]
        self.assertEqual(sim.route_guard(w, [], unit), guard)
        self.assertEqual(guard[0], "calls")


# ---------------------------------------------------------------------------
# Narration — the run in plain words (narrate) and the hops it takes (hops)
# ---------------------------------------------------------------------------

def told(trace) -> list:
    return [b.text for b in sim.narrate(trace)]


class TestNarration(unittest.TestCase):
    def test_checkout_happy_reads_as_prose(self):
        tr = run(load("01-checkout.sigil"))
        self.assertEqual(told(tr), [
            "episode 1 begins at (Shopper); (Shopper) calls [API] with {Cart}",
            "[API] calls [Payments] with charge(total) — attempt 1 of 4",
            "[API] calls |Orders| with insert",
            "|Orders| returns {Order} to [API]",
            "[API] emits <OrderPlaced>",
            "<OrderPlaced> fans out to [Email], [Shipping] and |Ledger|",
            "the run ends: ok"])

    def test_a_beat_per_frame_where_something_happens(self):
        tr = run(load("01-checkout.sigil"))
        beats = sim.narrate(tr)
        self.assertEqual([b.frame for b in beats], sorted({b.frame for b in beats}))
        for b in beats:
            self.assertEqual(tr.frames[b.frame].tick, b.tick)
        self.assertEqual(beats[-1].frame, len(tr.frames) - 1)

    def test_retries_give_up_and_route(self):
        text = told(run(load("01-checkout.sigil"), "API.charge:fails"))
        self.assertIn("charge(total) to [Payments] fails — attempt 2 of 4", text)
        self.assertIn("[API]'s call to [Payments] fails after 4 attempts; "
                      "[API] routes the failure to <PaymentFailed>", text)
        self.assertEqual(text[-1], "(Shopper)'s call to [API] fails — its callee failed; "
                                   "episode 1 fails; the run ends: failed")

    def test_fail_events_count_the_attempts_made(self):
        tr = run(load("01-checkout.sigil"), "API.charge:fails")
        fails = [(e["tries"], e["callee"]) for e in events(tr, "fail")]
        self.assertEqual(fails, [(4, False), (1, True)])

    def test_machines_triggers_and_transitions(self):
        text = told(run(load("04-orders.sigil")))
        self.assertIn("[Checkout] produces {Order}", text)
        self.assertIn("<Placed> drives {Order} and [Checkout]", text)
        self.assertIn("{Order} moves + → Open on <Placed>; [Checkout] moves Idle → Busy "
                      "on <Placed>", text)

    def test_calls_of_every_shape(self):
        sc = load("executions.sigil")
        joined = "\n".join(told(run(sc)))
        for said in ("[Scheduler] runs plan({Seed}) itself",
                     "[Scheduler] produces {Plan}",
                     "|Robots| replies to [Fetcher]",
                     "[Crawler] sends count(${host}) to [Metrics] without waiting",
                     "[Builder] calls itself with nest({Node}) — depth 2",
                     "[Builder] stops at the base case",
                     "loop: iteration 2",
                     "[Notifier] calls the host: mail.send(${report})"):
            self.assertIn(said, joined)
        self.assertIn("[Crawler] falls back to ${cached}",
                      "\n".join(told(run(sc, "Crawler.fetch:fallback"))))

    def test_races_branches_locks_and_bounds(self):
        joined = "\n".join(told(run(load("coverage.sigil"))))
        for said in ("[PspB] is cancelled", "branch {Request}.kind takes ‹read›",
                     "|Conn| is held", "|Conn| is released",
                     "{Order} ignores <Paid> in +: no transition leaves it",
                     "the loop is capped"):
            self.assertIn(said, joined)

    def test_never_reads_the_log(self):
        """The words come from frames and events: a trace with its log emptied
        narrates the same."""
        tr = run(load("01-checkout.sigil"), "API.charge:fails")
        bare = tr._replace(frames=tuple(f._replace(log=()) for f in tr.frames),
                           end={**tr.end, "log": []})
        self.assertEqual(sim.narrate(bare), sim.narrate(tr))

    def test_every_input_narrates(self):
        for path in EXAMPLES + FIXTURES:
            sc = build(path.read_text())
            for s in sim.scenarios(sc)[:4]:
                with self.subTest(file=path.name, scenario=s.name):
                    tr = sim.simulate(sc, s)
                    beats = sim.narrate(tr)
                    self.assertTrue(beats[-1].text.endswith(f"the run ends: {tr.outcome}"))
                    self.assertNotIn("None", " ".join(b.text for b in beats))
                    self.assertNotIn("\0", " ".join(b.text for b in beats))

    def test_a_branch_entry_is_named_as_drawn(self):
        # an episode starting at a branch: its decision node, never the raw id
        text = "#!sketch\nbranch on {Request}.kind {\n  read  => [Reader] -> |DB|\n}\n"
        self.assertIn("episode 1 begins at ◇ {Request}.kind", told(run(build(text)))[0])
        text = "#!sketch\nbranch on mode {\n  a => [X]\n  b => [Y]\n}\n"
        self.assertIn("episode 1 begins at ◇ mode", told(run(build(text)))[0])

    def test_hops_in_order(self):
        tr = run(load("01-checkout.sigil"), "API.charge:fails")
        hops = [(h.src, h.kind, h.dst) for h in sim.hops(tr)]
        self.assertEqual(hops[0], ("Shopper_actor", "->", "API_service"))
        self.assertEqual(hops.count(("API_service", "->", "Payments_service")), 4)
        self.assertEqual(hops[-1], ("API_service", "!>", "PaymentFailed_event"))
        self.assertEqual([h.frame for h in sim.hops(tr)],
                         sorted(h.frame for h in sim.hops(tr)))

    def test_hops_end_and_outcome(self):
        # each attempt fails on arrival; the call that waited on them and the
        # `!>` route (it travels as a failure) are no failed hops
        tr = run(load("01-checkout.sigil"), "API.charge:fails")
        got = [(h.dst, h.frame, h.end, h.outcome) for h in sim.hops(tr)]
        self.assertEqual(got[0], ("API_service", 0, 4, ""))
        self.assertEqual(got[1:5], [("Payments_service", f, f + 4, "failed")
                                    for f in (5, 10, 15, 20)])
        self.assertEqual(got[-1], ("PaymentFailed_event", 25, 29, ""))
        # a race's loser is cancelled when the winner arrives
        tr = run(build("(U) -> [Api]\n[Api] -> [A] &? [B]\n"))
        got = {h.dst: (h.end, h.outcome) for h in sim.hops(tr)}
        self.assertEqual(got["A_service"], (9, ""))
        self.assertEqual(got["B_service"], (9, "cancelled"))


if __name__ == "__main__":
    unittest.main()
