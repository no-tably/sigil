"""Tests for the run facts of sim.py — what the run view (view.py --run) unrolls.

Covers:
  1. instances(): keys, ordinals and composition order, the potential ones;
  2. lanes: which instances a hop reaches from its sender;
  3. the run's structured facts: enter / leave / hop / spawn events, a depth
     limit's act and level, Token.act.

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


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# The run graph: unroll / unroll_static / run_frame / folds
# ---------------------------------------------------------------------------

def keys(rg, role: str | None = None) -> list:
    return [k for k, n in rg.nodes.items() if role is None or n.role == role]


class TestUnrollStatic(unittest.TestCase):
    def setUp(self):
        self.rg = sim.unroll_static(canon(ARENA))

    def test_every_instance_and_the_potential_ones(self):
        ks = keys(self.rg)
        self.assertIn("Transform_data·4", ks)
        self.assertTrue(self.rg.nodes["Shard_service·2"].potential)
        self.assertFalse(self.rg.nodes["Bullet_service·1"].potential)
        self.assertIsNone(self.rg.trace)

    def test_labels_show_instances_only_where_they_vary(self):
        n = self.rg.nodes
        self.assertEqual(n["Bullet_service·2"].inst, 2)
        self.assertEqual(n["Shard_service·1"].inst, 1)       # optional: always numbered
        self.assertIsNone(n["Health_data·1"].inst)           # one, static: bare
        self.assertIsNone(n["Ship_service·1"].inst)

    def test_own_edges_carry_the_tree_marks(self):
        own = {(e.src, e.dst): e.mark for e in self.rg.edges.values() if e.role == "own"}
        self.assertEqual(own[("Ship_service·1", "Bullet_service·2")], "*")
        self.assertEqual(own[("Bullet_service·2", "Damage_data·2")], "&")
        self.assertEqual(own[("Asteroid_service·1", "Shard_service·1")], "?")

    def test_lanes(self):
        into = lambda src: sorted(e.dst for e in self.rg.edges.values() if e.src == src)
        self.assertEqual(into("Homing_service"), ["Transform_data·2", "Transform_data·3"])
        self.assertEqual(len(into("Physics_service")), 4)

    def test_recursion_unrolls_to_the_depth_then_the_base(self):
        rg = sim.unroll_static(canon(EXECUTIONS))
        chain = [k for k in keys(rg) if k.startswith("Builder_service")]
        self.assertEqual(chain, ["Builder_service", "Builder_service↻2", "Builder_service↻3",
                                 "Builder_service↻3┤"])
        self.assertEqual(len(keys(rg, "base")), 3)            # Doc.walk, Builder, follow()
        self.assertEqual(sim.unroll_static(canon(EXECUTIONS), sim.Limits(depth=2))
                         .nodes["Builder_service↻2┤"].role, "base")


class TestUnroll(unittest.TestCase):
    def setUp(self):
        self.sc = canon(ARENA)
        self.tr = run(self.sc)
        self.rg = sim.unroll(self.tr)

    def test_only_what_ran_or_was_set_up(self):
        ks = keys(self.rg)
        self.assertIn("Shard_service·1", ks)
        self.assertNotIn("Shard_service·2", ks)
        self.assertIn("Ship_service·1", ks)

    def test_a_spawned_instance_is_pending_while_its_hop_flies(self):
        n = self.rg.nodes["Shard_service·1"]
        self.assertLess(n.born, n.spawned)
        self.assertNotIn("Shard_service·1", sim.run_frame(self.rg, n.born - 1).nodes)
        self.assertTrue(sim.run_frame(self.rg, n.born).nodes["Shard_service·1"][2])
        self.assertFalse(sim.run_frame(self.rg, n.spawned).nodes["Shard_service·1"][2])

    def test_tokens_one_per_lane(self):
        e = next(e for e in self.rg.edges.values() if e.src == "Homing_service")
        fr = sim.run_frame(self.rg, e.born)
        on = sorted(k[1] for k, _at, _d, _s in fr.tokens)
        self.assertEqual(on, ["Transform_data·2", "Transform_data·3"])

    def test_edges_appear_with_their_first_hop(self):
        e = self.rg.edges[("Combat_service", "Health_data·1", "->")]
        self.assertNotIn(e.key, sim.run_frame(self.rg, e.born - 1).edges)
        self.assertIn(e.key, sim.run_frame(self.rg, e.born).edges)

    def test_the_run_is_within_what_could_exist(self):
        for path in sorted((_DIR / "site" / "examples").glob("*.sigil")) + [EXECUTIONS]:
            sc = canon(path)
            static = sim.unroll_static(sc, show=None)
            for sc_ in sim.scenarios(sc)[:6]:
                ran = sim.unroll(sim.simulate(sc, sc_), show=None)
                extra = set(ran.nodes) - set(static.nodes)
                self.assertFalse(extra, f"{path.name} {sc_.name}: {sorted(extra)}")

    def test_counts_and_statuses(self):
        rg = sim.unroll(run(canon(EXECUTIONS)))
        last = sim.run_frame(rg, len(rg.trace.frames) - 1)
        self.assertEqual(last.nodes["Parser_service"][1], 3)
        self.assertEqual(last.nodes["Builder_service↻3┤"][1], 3)
        self.assertEqual(len(keys(rg, "base")), 2)
        self.assertTrue(all(st == "visited" for st, _c, _p in last.nodes.values()))

    def test_a_failure_stays_marked(self):
        sc = canon(EXECUTIONS)
        rg = sim.unroll(run(sc, "Fetcher.http.get:fails"))
        last = sim.run_frame(rg, len(rg.trace.frames) - 1)
        self.assertEqual(last.nodes["Fetcher_service"][0], "failed")
        web = rg.edges[("Fetcher_service", "Web_actor", "->")]
        self.assertEqual(web.hops[0][2], "failed")

    def test_waiting_while_a_callee_runs(self):
        rg = sim.unroll(run(canon(EXECUTIONS)))
        e = rg.edges[("Builder_service↻2", "Builder_service↻3", "->")]
        fr = sim.run_frame(rg, e.born)
        self.assertEqual(fr.nodes["Builder_service"][0], "waiting")
        self.assertEqual(fr.nodes["Builder_service↻2"][0], "active")


class TestFolds(unittest.TestCase):
    def test_instances_fold_with_their_subtrees(self):
        L = sim.Limits(spawn=6)
        rg = sim.unroll(run(canon(ARENA), limits=L), limits=L)
        fold = rg.nodes["Bullet_service·3‥6"]
        self.assertEqual((fold.role, fold.more), ("fold", 4))
        self.assertEqual(rg.nodes["Transform_data…Bullet_service·3‥6"].more, 4)
        self.assertEqual(rg.folds["instances"], 12)
        self.assertNotIn("Bullet_service·4", rg.nodes)
        none = sim.unroll(run(canon(ARENA), limits=L), limits=L, show=None)
        self.assertIn("Bullet_service·4", none.nodes)

    def test_a_troubled_instance_stays(self):
        L = sim.Limits(spawn=6)
        prog = sim.program(canon(ARENA))
        u = sim._Unrolled(prog, sim.instances(prog, L), L)
        for i in sim.instances(prog, L):
            u.node(i.node, i.key, 1)
        remap, _folds = sim._fold(u, 3, frozenset({"Bullet_service·5"}))
        self.assertNotIn("Bullet_service·5", remap)
        self.assertEqual(remap["Bullet_service·4"], "Bullet_service·3‥6")

    def test_levels_fold_and_keep_the_base(self):
        L = sim.Limits(depth=8)
        rg = sim.unroll_static(canon(EXECUTIONS), L)
        chain = [k for k in keys(rg) if k.startswith("Builder_service")]
        self.assertEqual(chain, ["Builder_service", "Builder_service↻2", "Builder_service↻3‥7",
                                 "Builder_service↻8", "Builder_service↻8┤"])
        self.assertEqual(rg.nodes["Builder_service↻3‥7"].span, (3, 7))
        edges = {(e.src, e.dst) for e in rg.edges.values()}
        self.assertIn(("Builder_service↻2", "Builder_service↻3‥7"), edges)
        self.assertIn(("Builder_service↻3‥7", "Builder_service↻8"), edges)

    def test_counts_for_the_footer(self):
        L = sim.Limits(depth=8)
        c = sim.run_counts(sim.unroll(run(canon(EXECUTIONS), limits=L), limits=L))
        self.assertEqual((c["deepest"], c["spawned"], c["show"]), (8, 0, 3))
        self.assertGreater(c["levels"], 0)
