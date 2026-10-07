"""Tests for the run facts of sim.py — what the run view (view.py --run) draws.

Covers:
  1. instances(): keys, ordinals and composition order, the potential ones;
  2. lanes: which instances a hop reaches from its sender;
  3. the run's structured facts: enter / leave / hop / land / spawn events, a
     depth limit's act and level, Token.act;
  4. timeline(): lane order and nesting, work and waits, moves and marks,
     episodes, folds.

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


sim = _load("sigil_sim_run_test", _DIR / "sim.py")
scene = sim.scene_mod
render = sim.kit.render

ARENA = _DIR / "site" / "examples" / "03-arena.sigil"
EXECUTIONS = _DIR / "tests" / "fixtures" / "executions.sigil"


def canon(path_or_text) -> object:
    text = path_or_text.read_text() if isinstance(path_or_text, Path) else path_or_text
    return sim.canonical(render.parse_document(text))


def run(sc, name: str = "happy", **kw):
    return sim.simulate(sc, sim.scenario(sc, name), **kw)


def events(trace, kind: str) -> list:
    return [e for e in trace.end["events"] if e["kind"] == kind]


def short(key) -> str:
    """('Transform_data', 2) → 'Transform·2'."""
    return f"{key[0].rsplit('_', 1)[0]}·{key[1]}"


class TestInstances(unittest.TestCase):
    def setUp(self):
        self.prog = sim.program(canon(ARENA))

    def test_composition_order_and_ordinals(self):
        got = [short(i.key) for i in sim.instances(self.prog)]
        self.assertEqual(got, ["Ship·1", "Transform·1", "Health·1", "Bullet·1", "Transform·2",
                               "Damage·1", "Bullet·2", "Transform·3", "Damage·2", "Asteroid·1",
                               "Transform·4"])

    def test_parents(self):
        by = {short(i.key): i for i in sim.instances(self.prog)}
        self.assertEqual(short(by["Transform·3"].parent), "Bullet·2")
        self.assertIsNone(by["Ship·1"].parent)
        self.assertTrue(by["Bullet·1"].spawn)

    def test_potential_adds_the_optional_ones(self):
        insts = sim.instances(self.prog, potential=True)
        shards = [i for i in insts if i.node == "Shard_service"]
        self.assertEqual([short(i.key) for i in shards], ["Shard·1", "Shard·2"])
        self.assertFalse(any(i.setup for i in shards))
        self.assertTrue(all(i.setup for i in insts if i.node != "Shard_service"))

    def test_counts_are_the_tallies(self):
        self.assertEqual(sim._setup_instances(self.prog, sim.Limits()),
                         [1, 1, 1, 2, 2, 2, 1, 1, 0])

    def test_spawns_caps_an_entry(self):
        insts = sim.instances(self.prog, sim.Limits(spawn=6))
        self.assertEqual(sum(1 for i in insts if i.node == "Bullet_service"), 6)
        self.assertEqual(sum(1 for i in insts if i.node == "Transform_data"), 8)


class TestLanes(unittest.TestCase):
    def setUp(self):
        self.tr = run(canon(ARENA))

    def lanes(self, src: str) -> tuple:
        return next(e["lanes"] for e in events(self.tr, "hop") if e["wire"][0] == src)

    def test_a_path_reaches_the_bullets_transforms_only(self):
        self.assertEqual([short(k) for k in self.lanes("Homing_service")],
                         ["Transform·2", "Transform·3"])

    def test_a_flow_from_outside_reaches_every_instance(self):
        self.assertEqual(len(self.lanes("Physics_service")), 4)

    def test_reach_is_the_lanes(self):
        reach = {t.wire[:2]: t.reach for f in self.tr.frames for t in f.tokens}
        self.assertEqual(reach[("Homing_service", "Transform_data")], 2)

    def test_an_entry_stands_for_every_instance(self):
        damage = next(e for e in events(self.tr, "enter") if e["node"] == "Damage_data")
        self.assertEqual([short(k) for k in damage["insts"]], ["Damage·1", "Damage·2"])
        self.assertIsNone(damage["caller"])

    def test_a_child_of_each_lane(self):
        sc = canon("[Ship]\n    \\-& {Transform}\n    \\-*-> [Bullet]\n"
                   "        \\-& {Transform}\n[Bullet] -> {Transform}\n")
        tr = run(sc)
        bullet = next(e for e in events(tr, "enter") if e["node"] == "Bullet_service")
        hop = next(e for e in events(tr, "hop") if e["wire"][0] == "Bullet_service")
        self.assertEqual([short(k) for k in bullet["insts"]], ["Bullet·1", "Bullet·2"])
        self.assertEqual([short(k) for k in hop["lanes"]], ["Transform·2", "Transform·3"])


class TestRunFacts(unittest.TestCase):
    def test_enter_and_leave_pair_up(self):
        tr = run(canon(ARENA))
        entered = {e["act"] for e in events(tr, "enter")}
        left = {e["act"] for e in events(tr, "leave")}
        self.assertEqual(entered, left)
        self.assertEqual(sorted(entered), list(range(1, len(entered) + 1)))
        self.assertTrue(all(e["how"] == "ok" for e in events(tr, "leave")))

    def test_spawn_names_the_instance_and_its_parent(self):
        tr = run(canon(ARENA))
        (sp,) = events(tr, "spawn")
        self.assertEqual(short(sp["inst"]), "Shard·1")
        self.assertEqual(short(sp["parent"]), "Asteroid·1")
        shard = next(e for e in events(tr, "enter") if e["node"] == "Shard_service")
        self.assertEqual(shard["insts"], (sp["inst"],))

    def test_tokens_carry_their_act(self):
        tr = run(canon(ARENA))
        hops = {(e["task"], e["wire"]): e["act"] for e in events(tr, "hop")}
        toks = [t for f in tr.frames for t in f.tokens]
        self.assertTrue(toks)
        for t in toks:
            self.assertEqual(t.act, hops[(t.task, t.wire)])

    def test_recursion_levels_and_the_base_case(self):
        tr = run(canon(EXECUTIONS))
        builder = [e for e in events(tr, "enter") if e["node"] == "Builder_service"]
        self.assertEqual(sorted({e["level"] for e in builder}), [1, 2, 3])
        acts = {e["act"]: e for e in events(tr, "enter")}
        deep = [e for e in events(tr, "limit") if e["name"] == "depth"
                and e["node"] == "Builder_service"]
        self.assertTrue(deep)
        for e in deep:
            self.assertEqual(e["level"], 3)
            self.assertEqual(acts[e["act"]]["level"], 3)
            self.assertEqual(e["wire"][:2], ("Builder_service", "Builder_service"))
        lvl2 = next(e for e in builder if e["level"] == 2)
        self.assertEqual(acts[lvl2["caller"]]["level"], 1)

    def test_a_failed_activation_leaves_failed(self):
        sc = canon(EXECUTIONS)
        tr = run(sc, "Fetcher.http.get:fails")
        fetcher = {e["act"] for e in events(tr, "enter") if e["node"] == "Fetcher_service"}
        how = {e["how"] for e in events(tr, "leave") if e["act"] in fetcher}
        self.assertIn("failed", how)

    def test_an_async_hop_sets_out_from_the_forking_act(self):
        tr = run(canon(ARENA))
        acts = {e["act"]: e for e in events(tr, "enter")}
        hop = next(e for e in events(tr, "hop") if e["wire"][2] == "~>")
        self.assertEqual(acts[hop["act"]]["node"], "Combat_service")


CHECKOUT = _DIR / "site" / "examples" / "01-checkout.sigil"


class TestLandings(unittest.TestCase):
    """Each hop's id, its `land` event (how it ended) and a reply's callee."""

    def test_every_hop_lands_once(self):
        for path in (ARENA, EXECUTIONS, CHECKOUT):
            tr = run(canon(path))
            ids = [e["id"] for e in events(tr, "hop")]
            self.assertEqual(ids, list(range(1, len(ids) + 1)))
            landed = [e["hop"] for e in events(tr, "land")]
            self.assertEqual(sorted(landed), ids)

    def test_attempts_failing_on_arrival(self):
        tr = run(canon(CHECKOUT), "API.charge:fails")
        pay = [e for e in events(tr, "hop") if e["wire"][1] == "Payments_service"]
        self.assertEqual([e["attempt"] for e in pay], [(k, 4) for k in range(1, 5)])
        how = {e["hop"]: e for e in events(tr, "land")}
        self.assertEqual([how[e["id"]]["how"] for e in pay], ["failed"] * 4)
        self.assertEqual([how[e["id"]]["t"] - e["t"] for e in pay], [4] * 4)

    def test_an_entered_hop_names_its_activation(self):
        tr = run(canon(CHECKOUT))
        how = {e["hop"]: e["how"] for e in events(tr, "land")}
        for e in events(tr, "enter"):
            if e["hop"] is not None:
                self.assertEqual(how[e["hop"]], "entered")

    def test_a_reply_names_its_callee(self):
        tr = run(canon(EXECUTIONS))
        acts = {e["act"]: e for e in events(tr, "enter")}
        back = [e for e in events(tr, "hop") if e["back"]]
        self.assertTrue(back)
        builder = next(e for e in back if e["wire"][1] == "Builder_service")
        self.assertEqual(acts[builder["callee"]]["level"], 1)   # the outermost level replies
        self.assertEqual(builder["carries"], "{Doc}")
        how = {e["hop"]: e["how"] for e in events(tr, "land")}
        self.assertTrue(all(how[e["id"]] == "returned" for e in back))

    def test_reached_opaque_and_self(self):
        tr = run(canon(EXECUTIONS))
        how = {(e["node"], e["how"]) for e in events(tr, "land")}
        self.assertIn(("Web_actor", "opaque"), how)
        self.assertIn(("Scheduler_service", "self"), how)


# ---------------------------------------------------------------------------
# The timeline: lanes, spans, moves, marks, folds
# ---------------------------------------------------------------------------

def timeline(path, name: str = "happy", limits=None, **kw):
    sc = canon(path)
    limits = limits or sim.Limits()
    return sim.timeline(run(sc, name, limits=limits), limits=limits, **kw)


def names(tl) -> list:
    out = []
    for ln in tl.lanes:
        base = ln.node.rsplit("_", 1)[0]
        if ln.fold:
            base += "…"
        elif ln.levels:
            base += f"↻{ln.levels[0]}‥{ln.levels[1]}"
        elif ln.level > 1:
            base += f"↻{ln.level}"
        elif ln.inst is not None:
            base += f"·{ln.inst[1]}"
        out.append(base)
    return out


class TestTimelineLanes(unittest.TestCase):
    def test_first_acted_order_sender_before_receiver(self):
        tl = timeline(CHECKOUT, "API.charge:fails")
        self.assertEqual(names(tl), ["Shopper", "API", "Payments", "PaymentFailed"])
        born = [ln.born for ln in tl.lanes]
        self.assertEqual(born, sorted(born))

    def test_expansions_and_levels_sit_under_their_lane(self):
        tl = timeline(EXECUTIONS)
        got = names(tl)
        k = got.index("Parser")
        self.assertEqual(got[k:k + 5], ["Parser", "Lexer", "Builder", "Builder↻2", "Builder↻3"])
        lanes = {names(tl)[i]: ln for i, ln in enumerate(tl.lanes)}
        self.assertEqual(lanes["Lexer"].parent, lanes["Parser"].key)
        self.assertEqual(lanes["Builder↻3"].parent, lanes["Builder"].key)

    def test_instances_together_in_ordinal_order(self):
        got = names(timeline(ARENA))
        self.assertEqual(got[:5], ["Physics", "Transform·1", "Transform·2", "Transform·3",
                                   "Transform·4"])
        tl = timeline(ARENA)
        owners = [short(ln.owner) for ln in tl.lanes if ln.node == "Transform_data"]
        self.assertEqual(owners, ["Ship·1", "Bullet·1", "Bullet·2", "Asteroid·1"])

    def test_a_spawned_lane_is_born_as_its_spawn_hop_sets_out(self):
        tl = timeline(ARENA)
        shard = next(ln for ln in tl.lanes if ln.node == "Shard_service")
        spawn = next(m for m in tl.moves if m.kind == "=>")
        self.assertEqual(shard.born, spawn.start)
        self.assertEqual(shard.spawned, spawn.end)
        self.assertEqual(shard.spawner, "Spawner_service")
        self.assertEqual(short(shard.owner), "Asteroid·1")


class TestTimelineFacts(unittest.TestCase):
    def test_work_and_waits(self):
        tl = timeline(CHECKOUT, "API.charge:fails")
        api = next(s for s in tl.spans if s.node == "API_service")
        work = [t for t in range(api.enter, api.leave)
                if not any(a <= t < b for a, b in api.waits)]
        self.assertEqual(work, [4, 5, 10, 15, 20, 25])     # arrival, then each send
        self.assertEqual(api.how, "failed")

    def test_retries_fail_on_arrival_and_never_run(self):
        tl = timeline(CHECKOUT, "API.charge:fails")
        pay = [m for m in tl.moves if m.dst[0][0] == "Payments_service"]
        self.assertEqual([(m.start, m.end, m.how) for m in pay],
                         [(5, 9, "failed"), (10, 14, "failed"), (15, 19, "failed"),
                          (20, 24, "failed")])
        self.assertFalse([s for s in tl.spans if s.node == "Payments_service"])
        route = next(m for m in tl.moves if m.kind == "!>")
        self.assertEqual((route.start, route.end, route.how), (25, 29, "entered"))

    def test_a_reply_leaves_the_outermost_level(self):
        tl = timeline(EXECUTIONS)
        back = [m for m in tl.moves if m.back and m.wire[1] == "Builder_service"]
        self.assertEqual(len(back), 3)
        self.assertTrue(all(m.src == (("Builder_service", None, 1),) for m in back))
        self.assertTrue(all(m.how == "returned" for m in back))

    def test_base_case_once_per_recursion(self):
        tl = timeline(EXECUTIONS)
        base = [m for m in tl.marks if m.what == "base" and m.lane[0] == "Builder_service"]
        self.assertEqual(len(base), 3)
        self.assertTrue(all(m.lane[2] == 3 for m in base))

    def test_self_calls_and_host_ops_are_marks(self):
        tl = timeline(EXECUTIONS)
        what = {(m.lane[0], m.what) for m in tl.marks}
        self.assertIn(("Scheduler_service", "self"), what)
        self.assertIn(("Notifier_service", "host"), what)
        self.assertFalse([m for m in tl.moves if m.how == "self"])
        web = next(m for m in tl.moves if m.dst[0][0] == "Web_actor")
        self.assertEqual(web.how, "opaque")

    def test_episodes(self):
        tl = timeline(EXECUTIONS)
        self.assertEqual([(k, t) for k, t, _n in tl.episodes], [(1, 0), (2, 78), (3, 160)])
        self.assertEqual(tl.last, 162)


class TestTimelineFolds(unittest.TestCase):
    def test_instances_fold_by_owner_kind(self):
        limits = sim.limits_from(["spawn=6"])
        tl = timeline(ARENA, limits=limits)
        got = names(tl)
        self.assertIn("Transform…", got)
        bullets = [ln for ln in tl.lanes if ln.node == "Transform_data"
                   and (ln.fold or (ln.owner and ln.owner[0] == "Bullet_service"))]
        self.assertEqual(len(bullets), 3)             # ·2, ·3 and the fold
        fold = bullets[-1]
        self.assertEqual(len(fold.fold), 4)
        self.assertEqual(tl.folded["instances"], 8)   # the Transforms and the Damages
        unfolded = timeline(ARENA, limits=limits, show=None)
        self.assertEqual(sum(1 for ln in unfolded.lanes if ln.node == "Transform_data"), 8)

    def test_a_troubled_instance_stays(self):
        limits = sim.limits_from(["spawn=6"])
        tl = timeline(ARENA, limits=limits, show=None)
        prog = sim.program(canon(ARENA))
        lanes = list(tl.lanes)
        sick = next(ln for ln in lanes if ln.node == "Transform_data" and ln.inst
                    and ln.inst[1] == 6)
        spans = list(tl.spans) + [sim.Span(sick.key, 999, 1, sick.node, 1, 2, "failed", (),
                                           None, None, 1)]
        folded = {"show": 3, "instances": 0, "levels": 0}
        out, *_rest = sim._fold_lanes(lanes, spans, list(tl.moves), list(tl.marks),
                                      {ln.key: (ln.born, 0) for ln in lanes}, prog, 3, folded)
        self.assertIn(sick.key, [ln.key for ln in out])

    def test_levels_fold_and_keep_the_deepest(self):
        limits = sim.limits_from(["depth=6"])
        got = names(timeline(EXECUTIONS, limits=limits))
        k = got.index("Builder")
        self.assertEqual(got[k:k + 4], ["Builder", "Builder↻2", "Builder↻3‥5", "Builder↻6"])


if __name__ == "__main__":
    unittest.main()
