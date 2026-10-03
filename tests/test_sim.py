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
     loop_count).

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
        self.assertEqual(names(load("01-checkout.sigil")), ["happy", "API.charge:fails"])
        self.assertEqual(names(load("02-shop.sigil")), ["happy", "Risk?>Review"])
        self.assertEqual(names(load("03-arena.sigil")), ["happy"])
        self.assertEqual(names(load("04-orders.sigil")), ["happy", "Payments:fails"])

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

    # Dead in both today, each for a listed simulator defect (RFC 0003 catalog §6):
    # a `*>` / `&` member's failure reaches its line's route as None (B1); a
    # `parallel @all` member gets no failure scenario of its own (B2).
    KNOWN_DEAD = {("coverage", 72): "B1", ("examples-04", 7): "B1",
                  (worked_example("Example 4:"), 5): "B1", ("coverage", 141): "B2"}

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

    def test_known_dead_routes_exist(self):
        docs = dict(corpus())
        for (name, line), _defect in self.KNOWN_DEAD.items():
            with self.subTest(doc=name, line=line):
                prog = sim.program(sim.canonical(build(docs[name]).graph))
                dead = [w for i, w in routes_of(prog).items()
                        if i not in sim.failure_analysis(prog).live]
                self.assertIn(line, [w.line for w in dead])

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
                "(U) -> [A]\nparallel @none {\n  [A] -> [B] : f() ×2\n} !> <Failed>\n",
                # a race member's failure reaches the line's route as None (B1)
                "(U) -> [A]\n[A] -> [B] &? [C] : f() ×2\n     !> <Failed>\n"]:
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


if __name__ == "__main__":
    unittest.main()
