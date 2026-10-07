"""
sim.py — the simulation engine: runs a design's pathways over the Scene.

Not a command: the views and the app load it. Sigil has no execution semantics
of its own; this is the simulator's reading of a design — tokens moving along
Scene wires so a reader sees the happy path, each failure route, each branch,
race and alternative. No values are computed, nothing is evaluated, no time
passes except ticks. This docstring is the contract the views rely on; the
construct-by-construct rules are stated here and on the functions that apply them.

    from sim import scenarios, simulate, project
    for sc in scenarios(scene):
        trace = simulate(scene, sc)            # a list of Frames, one per tick
        shown = project(trace, view_scene)     # the same run, named as a view draws it

Pure and deterministic: simulate() is a function of its arguments — no clock,
no randomness, no I/O. Every choice comes from the Scenario; every order is
written order (the Scene's wire order). Every loop, recursion, cycle, spawn and
the trace length are bounded by Limits; hitting a bound is logged. No drawing
code: this module reads scene.py (and through it render.py's model) only.

THE RUN

The simulator always runs on the CANONICAL scene (canonical()): every unit,
every event a node, every trigger wired to the state it enters. Frames name
wires by Wire.ident and nodes by node id; project() maps them onto the Scene a
view draws (events drawn where they land, a shallower depth).

  activation  one run of one node's work in one unit: its body (its outgoing
              work wires in that unit, written order), its `!>` routes on failure
  task        a thread of control: a stack of activations. A sync call pushes
              onto the caller's task; `~>`, a fan-out member, a trigger and a
              parallel member each start a task. Tasks run in id order per tick
  token       travels one wire, `at` 0 → 1 (a return 1 → 0 on the call's wire)
  tick        one Frame. A hop takes Limits.hop ticks (a self-call 1); the
              task's next turn is the tick after the arrival
  episode     one per entry, run one after another: the next starts the tick
              after the last went quiet. Entries: the document's nodes with
              work and no incoming flow (or actors), in written order

  Wires: `->` `→` `<->` sync call (and its return); `~>` fork, don't wait;
  `*>` and a `&` target fork all and wait for all; `&?` the scenario's winner;
  `/` the chosen member; `=>` a produce hop (into a spawned child: one more
  instance); `?>` only when the scenario takes it (a join's `?>` members too);
  `!>` only on failure. A join's members are resolved first, then its arrow
  runs them: on `~>` forked unawaited. A source join (`[A] & [B] -> [C]`) is
  a deposit, never a barrier: each member deposits and goes on, and the last
  arrival runs the target (`&?`: the first; later ones are dropped).
  A failure stops the activation it reaches, fires its routes (those guarded
  by the failed block or call first, else its unguarded ones), ends it failed and
  unwinds the sync stack. An awaited member (`*>`, an `&` target, a race's
  winner) fails its waiter as its own call, so its line's routes fire. A
  failure never crosses an async edge: a `~>` send (whose own failure the
  scenario may choose too), a `=>` produce hop or a flow into a stream stops
  it at the consumer ("not awaited"); the producer goes on.

  Resilience: a failing call makes attempts() tries; a call that arrives and
  whose callee's work fails (a nested call the scenario fails) is not retried —
  it made one attempt, and its failure says so ("failed after 1 attempt (its
  callee failed)"): the scenario names which call fails, so a retry could only
  replay the same failure. On a call's final failure `@fallback(x)` fires the
  caller's routes guarded by that call ("notify, then yield"), returns x and
  the caller goes on as ok; `!` critical ends the run. A self-call is a
  one-tick pulse; recursion stops at Limits.depth (the base case). An external
  op's far node is opaque. Blocks: `loop` repeats its region (`@times N`, capped
  by Limits.iterations), `parallel` forks it (@all waits, @any races, @none
  doesn't wait), `branch` runs the chosen arm only; a block repeats or forks only
  on its outermost entry on a task; a branch on a value's field (`branch on
  {R}.kind`) decides where it is written, as one with no header glyph does. State
  machines start in `+` (or the source of their first written transition); an
  event delivers its triggers (a transition written from the machine's state
  beats a `_` one), then runs its body. An expansion is a closer reading of the same node: its entries run first,
  then the node's body minus its summary wires. An alias runs when called by name.
  Composition children are instances: static ones once per parent (×N
  multiplies), dynamic ones Limits.spawn per parent, a `=>` into one spawns
  another. A flow's destination cardinality (`-> [App]×N`, Edge.card) is how
  many instances it reaches, never a retry: only a `×N` in a call's policy
  (scene.call_policy: Wire.mods, then Edge.src_mods) retries. Declarations (`@read`, `@inv`, `@sla`, notes, …) do not affect a run.

SCENARIOS

scenarios(scene) lists `happy` (every default) and then one scenario per
non-default option of each reachable choice point (call outcomes, node
outcomes, `?>`, `/`, `&?`, `parallel @any`, branch arms, `\\-_` siblings,
ambiguous machine transitions), ordered by source line. A route makes what it
guards a choice point: the calls on its line, and — when nothing in it fails
on its own — the awaited calls of the block whose `}` it follows. scenario(scene,
"a+b") combines deviations. Scenario(name, choices, label, entries): choices a
tuple of (choice id, option).

combinations(scene, k, budget=…) explores up to k deviations at once: a
combination grows only by a deviation its own run meets after its first
deviation took effect; runs that repeat an earlier one are dropped; the budget
caps the runs and says how many it left out (Exploration). deviations(prog)
lists the single ones.

STATIC FACTS (pure, over program(canonical(graph)); no run changes)

  reachable(prog)         what the default entries reach (wires, nodes, regions)
  route_guard / selected_routes   a route's guard; the routes a failure takes
  loop_count(block, limits)       how often the simulator runs a loop
  failure_flow(prog)      {(ui, node): the failure guards that can arrive there};
                          failure_analysis(prog) adds what fallbacks absorbed and
                          the live routes — mirrors the run

THE TRACE

Trace(scenario, frames, outcome, end, scene)
  outcome   "ok" | "failed" | "cut"
  end       {"machines", "routes", "stalled", "deposits", "cut", "visited", "log",
             "events"}
            deposits: the `&` source joins left open — [{"join": (unit, index),
            "target", "arrived", "missing"}] (node ids); a member deposits and goes
            on, so an open join is a deposit no last arrival consumed
            events: the run as data, in order — dicts with "kind", "t" (tick),
            "task" (id, or None for the run) and "episode" (the task's, recorded
            when it was forked), plus by kind:
              fork        parent (task id | None), why (entry | async | fan | join |
                          race | parallel | trigger), wire, node
              end         how (ok | failed | cancelled)
              await       members, need (task ids)   resume  failed (bool)
              gate-arrive key (unit, join, target), round, node, wire
              gate-fire   key, round, node (the target)
              gate-drop   key, round, node (an `&?` arrival after the winner)
              access      store, mode (read | write | rw | unknown), wire, held
                          (stores the task's `owns` blocks hold), outcome (done |
                          unknown: a failed attempt)
              choice      cid, option, default (bool): a choice point consulted
              fail        origin (("call", ident) | ("node", id)), node; for a call
                          fallback, critical (bool), tries (the attempts it made),
                          callee (bool: it arrived and its callee's work failed)
              route       node, wire, guard        transition  owner, label, src, dst
              stop        how (entry | unawaited | fallback | route-failed |
                          abort), node, guard
              limit       name (depth | visits | spawns | iterations | activations
                          | stack | frames), node; a depth limit also act (the
                          capped caller), level (how deep it is) and wire
              enter       act (run-wide activation number, from 1), caller (the
                          act whose hop or fork started it; None for an entry),
                          node, unit (index), level (activations of node on the
                          task's stack, itself included: Frame.depth's count),
                          insts (the instance keys it stands for, its lanes; ()
                          outside the composition tree), wire (the ident that
                          started it; None for an entry or an expansion's entry)
              leave       act, how (ok | failed | cancelled)
              hop         act (the one it sets out from), wire, back (bool), lanes
                          (the instance keys it reaches going out into a
                          composition node; None otherwise)
              spawn       node, inst (the new key), parent (its parent instance's
                          key), wire
              ignored     event, label, owner, state
              quiet       waiting (task ids still waiting when the run went quiet)
            A source join is a deposit, so its arrivers never wait: there is no
            gate resume; a gate's round counts the times it fired.
  scene     the Scene its frames name (the canonical one, or project()'s)

Frame — a full, immutable snapshot (a view draws frame i alone)
  tick, episode, entry, tokens (Token, task order), lit, held, taken, failed,
  nodes {id: active|waiting|visited|failed|cancelled|opaque}, depth,
  machines {owner: state node id}, changed, instances, loops, blocks,
  held_resources, log (lines added this frame, each led by `t` and the tick, zero-padded), done

Token(wire, at, dir, task, state, carries, reach, attempt, act)
  dir "out" | "back"; state "moving" | "failed" | "cancelled" | "fallback";
  act the activation the hop set out from

INSTANCES

instances(prog, limits, potential=False) -> (Instance(key, node, ordinal, parent,
rel, spawn, setup, entry), …): the composition instances at setup, keyed (node
id, ordinal), in composition order (a parent instance, then its children depth
first); a spawn adds one under the parent instance with the fewest of its
entry. A hop into a composition node stands for some of its instances (its
lanes): from a sender standing for instances I, for each i in I the target's
instances under i when there are any, else every instance the wire selects (a
`[A]/` path, Limits.spawns); from a sender standing for none, every one.

THE RUN GRAPH (pure, no drawing; what the run view draws)

  unroll(trace, limits, show)   the structure that exists only when run: a
                  RunNode per (design node, instance, recursion level) — an
                  instance per composition instance, `↻k` levels of a sync
                  recursion as a chain ending in a base stub (where the
                  simulator stopped it) — and a RunEdge per way a hop took
                  between them (lane by lane), own edges (parent instance →
                  child, the tree's relation mark), base edges. Async cycles,
                  loop iterations, repeats and episodes reuse their nodes (a
                  count). Each node and edge is born at the frame it first
                  exists in. Run node keys: `Bullet_service·2`,
                  `Builder_service↻2`, `…┤` a base stub, `Bullet_service·3‥6`
                  and `Transform_data…Bullet_service·3‥6` folds of instances,
                  `Builder_service↻3‥7` a fold of levels
  unroll_static(scene, limits, show)   what could exist up to the limits:
                  every instance (a `\\-?` entry's potential ones too), every
                  flow, trigger and arm wire lane by lane, each recursive
                  self-call unrolled to Limits.depth; no hops
  run_frame(rg, i)  what exists at frame i: nodes (status, count, pending),
                  edges (hops arrived), tokens on run edges (one per lane)
  folds (show, RUN_SHOW 3): a (node, parent instance) group of more than show
                  instances keeps its first show − 1 and every one that failed
                  or was cancelled, the rest one `[…×k more]` (subtrees with
                  it); a chain deeper than show + 1 keeps its first show − 1
                  levels and its deepest; past RUN_NODES nodes, show 1

NARRATION (pure, over a Trace and the scene it names)

  narrate(trace)  (Beat(frame, tick, text), …): the run in plain words, one Beat
                  per frame where something happens ("[API] calls [Payments] with
                  charge(total) — attempt 2 of 4"), read from the frames and the
                  events, never from the log's text
  hops(trace)     (Hop(frame, src, kind, dst, end, outcome), …): every hop set out
                  on, in order, with the frame it ends and how (failed, cancelled)
"""

from __future__ import annotations

import importlib.util
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple, Optional


_HERE = Path(__file__).resolve().parent


def _sibling(name: str, fname: str):
    """The module fname beside this file, loaded by path once per directory and then
    shared: the view modules of one directory read the one viewkit, so a theme
    applied through any of them (apply_theme rebinds viewkit's style globals)
    reaches them all, while a view.py loaded from another directory (a packaged
    copy) gets modules, theme and dialect state of its own. The cache key names
    the directory, never the bare name. view.py, view_graph.py, view_tree.py and
    scene.py each carry a copy of this function: keep the copies identical."""
    key = f"{name}@{_HERE}"
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, _HERE / fname)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod   # dataclasses resolve string annotations via sys.modules
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            del sys.modules[key]
            raise
    return sys.modules[key]


scene_mod = _sibling("sigil_scene", "scene.py")
kit = scene_mod.kit


# ---------------------------------------------------------------------------
# Public data
# ---------------------------------------------------------------------------

class Limits(NamedTuple):
    """The bounds that make every run end. `depth` is checked at every
    arrival (the base case: nothing runs); `activations`, `stack` and `frames` end
    the run with outcome "cut" — `stack` keeps a long sync chain inside Python's
    recursion limit (each activation nests a few generator frames). `activations`
    and `frames` count per episode, so a design with many entries runs each of them
    in full; a run's length is bounded by its entries times `frames`."""
    hop: int = 4               # ticks per hop
    iterations: int = 2        # loop repetitions
    depth: int = 3             # recursion depth / re-entry on one task's stack
    spawn: int = 2             # instances per dynamic child per parent; symbolic ×N
    spawns: int = 8            # instances per node in total
    visits: int = 3            # task-root activations of one node per episode (async cycles)
    activations: int = 500     # activations per episode
    stack: int = 64            # activations on one task's stack (nested sync work)
    frames: int = 2000         # frames per episode
    scenarios: int = 64        # scenarios listed


def limits_from(pairs, base: Limits = Limits()) -> Limits:
    """`base` with each "name=N" of `pairs` set (the tools' --limit). Raises
    ValueError naming a malformed pair, an unknown name or a value below 1."""
    out = base
    for pair in pairs:
        name, sep, value = pair.partition("=")
        name = name.strip()
        if not sep or not value.strip().isdigit():
            raise ValueError(f"--limit {pair!r}: expected NAME=N")
        if name not in base._fields:
            raise ValueError(f"--limit {name!r}: unknown (one of {', '.join(base._fields)})")
        if int(value) < 1:
            raise ValueError(f"--limit {name}: must be at least 1")
        out = out._replace(**{name: int(value)})
    return out


class Scenario(NamedTuple):
    name: str
    choices: tuple = ()        # ((choice id, option), …)
    label: str = ""
    entries: Optional[tuple] = None    # node ids; None: the default entries


class Token(NamedTuple):
    wire: tuple
    at: float
    dir: str
    task: int
    state: str = "moving"
    carries: Optional[str] = None
    reach: int = 1
    attempt: Optional[tuple] = None
    act: Optional[int] = None


class Instance(NamedTuple):
    """One composition instance (instances()): `key` (node id, ordinal), the
    ordinal counting the node's instances in composition order (a parent
    instance, then its children, depth first; a spawned one next in spawn
    order), its parent instance's key (None: a root), the tree entry's relation
    and `*-`, whether it exists at setup (False: one that could exist, the
    potential ones), and its entry's index in Program.tree."""
    key: tuple
    node: str
    ordinal: int
    parent: Optional[tuple]
    rel: Optional[str]
    spawn: bool
    setup: bool
    entry: int


class Frame(NamedTuple):
    tick: int
    episode: int
    entry: Optional[str]
    tokens: tuple
    lit: frozenset
    held: frozenset
    taken: frozenset
    failed: frozenset
    nodes: dict
    depth: dict
    machines: dict
    changed: frozenset
    instances: dict
    loops: dict
    blocks: frozenset
    held_resources: frozenset
    log: tuple
    done: bool


class Trace(NamedTuple):
    scenario: Scenario
    frames: tuple
    outcome: str
    end: dict
    scene: object = None


CONVENTIONS = ("conventions: written order; entries one after another; ?> not taken "
               "by default; the first member wins a race / alternative / branch")


# ---------------------------------------------------------------------------
# The static program — what each node runs, read once from the Scene
# ---------------------------------------------------------------------------

class Step(NamedTuple):
    wire: object               # scene.Wire


class Group(NamedTuple):
    kind: str                  # "all" | "race" | "alt"
    key: tuple                 # the group's choice key
    wires: tuple


class Region(NamedTuple):
    ui: int
    index: int                 # into the unit graph's blocks
    block: object              # render.Block
    items: tuple


class Machine(NamedTuple):
    owner: str
    initial: str
    transitions: tuple         # (src state, dst state, label, transition wire ident)


class TriggerRef(NamedTuple):
    trigger: object            # render.Trigger
    wire: object               # its trigger wire
    transition: Optional[tuple]  # the state unit's transition wire ident


@dataclass
class Program:
    scene: object
    units: list
    wire_unit: dict            # id(wire) → unit index
    bodies: dict               # (ui, node) → (item, …)
    arm_bodies: dict           # (ui, block index, label) → {node: (item, …)}
    arm_wire: dict             # (ui, block index, label) → arm wire
    routes: dict               # (ui, node) → ((wire, guard), …)
    returns: dict              # call wire ident → (item, …): a self-call's `=>` wires,
                               # relative to the call wire's block
    expansions: dict           # (ui, node) → unit index of its body
    aliases: dict              # alias name → (ui, alias node id)
    entries: dict              # ui → (node id | decision id, …)
    decisions: dict            # decision id → (ui, block index)
    branches: dict             # (ui, header node) → (block index, …)
    machines: dict             # owner → Machine
    triggers: dict             # event id → (TriggerRef, …)
    tree: list                 # [(ui, index in its unit's tree, TreeEntry)]
    tree_nodes: frozenset      # the node ids tree places
    unit_nodes: dict           # node id → render.Node, first seen over units
    order: dict                # id(wire) → position in Scene.wires
    access: object             # scene.access_index of the document


def canonical(graph):
    """The scene every run uses: every unit, events as nodes, triggers to states."""
    return scene_mod.build_scene(graph, events="nodes", triggers=True, access=False,
                                 depth=kit.ALL_DEPTH)


def program(sc) -> Program:
    """The static program of a canonical Scene (see Program's fields)."""
    units = sc.units
    tree = [(i, k, t) for i, u in enumerate(units)
            for k, t in enumerate(getattr(u.graph, "tree", None) or [])]
    unit_of_graph = {id(u.graph): i for i, u in enumerate(units)}
    edge_unit = {id(e): i for i, u in enumerate(units) for e in u.graph.edges}
    flows = [w for w in sc.wires if w.role == "flow" and id(w.edge) in edge_unit]
    wire_unit = {id(w): edge_unit[id(w.edge)] for w in flows}
    expansions = {(i, nid): unit_of_graph[id(sub)] for i, u in enumerate(units)
                  for nid, sub in u.graph.expansions.items()
                  if sub.role != "state" and id(sub) in unit_of_graph}
    prog = Program(scene=sc, units=units, wire_unit=wire_unit, bodies={}, arm_bodies={},
                   arm_wire={}, routes={}, returns={}, expansions=expansions,
                   aliases=_aliases(units, expansions), entries={}, decisions={},
                   branches={}, machines=_machines(sc, units), triggers={},
                   tree=tree, tree_nodes=frozenset(t.node for _i, _k, t in tree),
                   unit_nodes=_unit_nodes(units),
                   order={id(w): k for k, w in enumerate(sc.wires)},
                   access=scene_mod.access_index(sc.graph))
    by_unit = {}
    for w in flows:
        by_unit.setdefault(wire_unit[id(w)], []).append(w)
    for i, u in enumerate(units):
        if u.graph.role == "state":
            continue
        _fill_unit(prog, i, u, by_unit.get(i, []))
    for i, u in enumerate(units):
        if u.graph.role != "state":
            prog.entries[i] = _unit_entries(prog, i, by_unit.get(i, []))
    prog.triggers = _trigger_refs(sc, prog.machines)
    return prog


def _fill_unit(prog: Program, ui: int, u, wires: list) -> None:
    """Bodies, arm bodies, routes, returns and branch headers of one unit."""
    blocks = getattr(u.graph, "blocks", None) or []
    arm_of = _arm_membership(blocks, wires)
    work = [w for w in wires if w.kind != "!>" and w.returns_of is None and id(w) not in arm_of]
    joins = getattr(u.graph, "joins", None) or []
    by_src = {}
    for w in work:
        by_src.setdefault(w.src, []).append(w)
    for src, mine in by_src.items():
        prog.bodies[(ui, src)] = _items(ui, mine, blocks, joins, None)
    returns = {}
    for w in wires:
        if w.kind == "!>":
            prog.routes[(ui, w.src)] = (prog.routes.get((ui, w.src), ())
                                        + ((w, route_guard(w, blocks, wires)),))
        if w.returns_of is not None:
            returns.setdefault(w.returns_of.ident, []).append(w)
    prog.returns.update({k: _items(ui, v, blocks, joins, v[0].returns_of.block)
                         for k, v in returns.items()})
    for (bi, label), members in _arm_groups(arm_of, wires).items():
        prog.arm_bodies[(ui, bi, label)] = {
            src: _items(ui, [w for w in members if w.src == src], blocks, joins, bi)
            for src in dict.fromkeys(w.src for w in members)}
    for w in prog.scene.wires:
        if w.role == "arm" and w.owner == u.owner and w.level == u.level:
            prog.arm_wire[(ui, w.block, w.label)] = w
    for bi, b in enumerate(blocks):
        if b.kind == "branch":
            if b.refs and not _field_header(b):
                prog.branches[(ui, b.refs[0])] = prog.branches.get((ui, b.refs[0]), ()) + (bi,)
            else:
                prog.decisions[scene_mod.decision_id(u.owner, bi)] = (ui, bi)


_FIELD_HEADER = re.compile(r"^\s*\{[^{}]*\}\s*\.\s*\w")


def _field_header(b) -> bool:
    """A branch on a field of a value (`branch on {Request}.kind`): it tests the
    value, nothing activates it, so it decides where it is written, as a branch
    with no header glyph does (catalog §6 B4)."""
    return bool(_FIELD_HEADER.match(b.header or ""))


def _arm_membership(blocks: list, wires: list) -> dict:
    """{id(wire): (block index, arm label)} for every wire drawn inside a branch arm."""
    out = {}
    for bi, b in enumerate(blocks):
        if b.kind != "branch":
            continue
        lo, hi = b.lines
        for label, keys in b.arms:
            for w in wires:
                if w.key in keys and lo <= w.line <= hi and id(w) not in out:
                    out[id(w)] = (bi, label)
    return out


def _arm_groups(arm_of: dict, wires: list) -> dict:
    """{(block index, label): [wire, …]} in wire order."""
    out = {}
    for w in wires:
        if id(w) in arm_of:
            out.setdefault(arm_of[id(w)], []).append(w)
    return out


def route_guard(w, blocks: list, wires: list) -> Optional[tuple]:
    """The guard of route w among its unit's flow `wires` (prog.routes stores it
    beside each route): ("block", index) for a `!>` continuing a block's `}`
    (Block.after); ("calls", frozenset of ("call", ident)) for one continuing a flow
    line (Edge.cont): the subject's work wires written on that line; else None (the
    node's own route)."""
    for bi, b in enumerate(blocks):
        if w.key in b.after and w.line >= b.lines[1]:
            return ("block", bi)
    cont = getattr(w.edge, "cont", 0)
    if cont:
        calls = frozenset(("call", x.ident) for x in wires
                          if x.src == w.src and x.line == cont and x.kind != "!>"
                          and x.returns_of is None)
        if calls:
            return ("calls", calls)
    return None


def _guards(g: Optional[tuple], failed) -> bool:
    """Whether route guard `g` covers the failure guard `failed`."""
    if g is None or failed is None:
        return False
    return failed in g[1] if g[0] == "calls" else g == failed


def _chain(bi: Optional[int], blocks: list) -> list:
    """bi and its enclosing blocks, innermost first."""
    out = []
    while bi is not None:
        out.append(bi)
        bi = blocks[bi].parent
    return out


def _child_block(bi: Optional[int], outer: Optional[int], blocks: list) -> Optional[int]:
    """The block directly inside `outer` (None: top level) that holds block bi, or
    None when bi is `outer` itself (or no block)."""
    chain = _chain(bi, blocks)
    if outer in chain:
        chain = chain[:chain.index(outer)]
    elif outer is not None:
        return None
    return chain[-1] if chain else None


def _group_key(w) -> Optional[tuple]:
    if w.edge is not None and w.edge.dst_join is not None:
        return ("join", w.owner, w.level, w.edge.dst_join)
    if w.kind == "*>":
        return ("fan", w.src, w.line)
    return None


def _group_kind(w, joins: list) -> str:
    j = w.edge.dst_join if w.edge is not None else None
    kind = joins[j].kind if j is not None and 0 <= j < len(joins) else "&"
    return {"&?": "race", "/": "alt"}.get(kind, "all")


def _items(ui: int, wires: list, blocks: list, joins: list, outer: Optional[int]) -> tuple:
    """A body as items: control-block regions (loops / parallel / scopes, nested),
    join and fan-out groups, single steps — in written order."""
    out, i = [], 0
    while i < len(wires):
        w = wires[i]
        child = _child_block(w.block, outer, blocks)
        if child is not None:
            j = i
            while j < len(wires) and _child_block(wires[j].block, outer, blocks) == child:
                j += 1
            out.append(Region(ui, child, blocks[child],
                              _items(ui, wires[i:j], blocks, joins, child)))
            i = j
            continue
        key = _group_key(w)
        if key is None:
            out.append(Step(w))
            i += 1
            continue
        j = i
        while (j < len(wires) and _group_key(wires[j]) == key
               and _child_block(wires[j].block, outer, blocks) is None):
            j += 1
        out.append(Group(_group_kind(w, joins), key, tuple(wires[i:j])))
        i = j
    return tuple(out)


def _flat(items) -> list:
    """Every wire of a body's items, in order."""
    out = []
    for it in items:
        if isinstance(it, Step):
            out.append(it.wire)
        elif isinstance(it, Group):
            out += list(it.wires)
        else:
            out += _flat(it.items)
    return out


def _unit_entries(prog: Program, ui: int, wires: list) -> tuple:
    """A unit's entries: nodes with work and either actors or with no
    incoming flow in the unit (self-edges aside), minus arm entries; branches with
    no header glyph at their position — ordered by line."""
    u = prog.units[ui]
    incoming = {w.dst for w in wires if w.src != w.dst}
    arm_entries = {ids[0] for b in (getattr(u.graph, "blocks", None) or [])
                   if b.kind == "branch" for _l, ids in b.arm_nodes if ids}
    cands = []
    for nid, n in u.graph.nodes.items():
        body = _flat(prog.bodies.get((ui, nid), ()))
        if not body or nid in arm_entries:
            continue
        if n.kind == "actor" or nid not in incoming:
            cands.append((body[0].line, prog.order[id(body[0])], nid))
    for did, (dui, bi) in prog.decisions.items():
        if dui == ui:
            cands.append((u.graph.blocks[bi].lines[0], -1, did))
    return tuple(nid for _line, _k, nid in sorted(cands, key=lambda c: (c[0], c[1])))


def _aliases(units: list, expansions: dict) -> dict:
    """{alias name: (ui, alias node id)} of every alias with a body."""
    out = {}
    for i, u in enumerate(units):
        for nid, n in u.graph.nodes.items():
            if n.kind == "alias" and (i, nid) in expansions:
                out.setdefault(n.name, (i, nid))
    return out


def _unit_nodes(units: list) -> dict:
    out = {}
    for u in units:
        for nid, n in u.graph.nodes.items():
            out.setdefault(nid, n)
    return out


def _pseudo(prog: Program, nid: str) -> Optional[str]:
    n = prog.unit_nodes.get(nid)
    return n.attrs.get("pseudo") if n is not None else None


def _machines(sc, units: list) -> dict:
    """{owner: Machine} of every state unit (initial state: `+` when the machine has a creation
    transition, else the source of its first written transition that is not `_`)."""
    out = {}
    idents = {id(w.edge): w.ident for w in sc.wires if w.role == "flow"}
    for u in units:
        g = u.graph
        if g.role != "state" or u.owner in out:
            continue
        trans = tuple((e.src, e.dst, e.label, idents.get(id(e))) for e in g.edges)
        start = next((e.src for e in g.edges if g.nodes[e.src].attrs.get("pseudo") == "start"),
                     None)
        first = next((e.src for e in g.edges if g.nodes[e.src].attrs.get("pseudo") != "any"),
                     None)
        initial = start or first
        if initial is not None:
            out[u.owner] = Machine(u.owner, initial, trans)
    return out


def _trigger_refs(sc, machines: dict) -> dict:
    """{event id: (TriggerRef, …)} in Scene order: graph.triggers paired with the
    canonical trigger wires (both in trigger order)."""
    wires = [w for w in sc.wires if w.role == "trigger"]
    out = {}
    for t, w in zip(getattr(sc.graph, "triggers", None) or [], wires):
        m = machines.get(t.owner)
        trans = next((x[3] for x in (m.transitions if m else ())
                      if x[0] == t.src and x[1] == t.dst and x[2] == t.label), None)
        out[t.event] = out.get(t.event, ()) + (TriggerRef(t, w, trans),)
    return out


# ---------------------------------------------------------------------------
# Modifiers, durations, returns
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(r"\s*(\d+(?:\.\d+)?)\s*(ms|s|min|h|d)?\s*$")
_UNIT_SECONDS = {"ms": 0.001, "s": 1, "min": 60, "h": 3600, "d": 86400, None: 1}


def duration(text: Optional[str]) -> Optional[float]:
    """Seconds of `500ms` / `2s` / `1min` / `1h` / `1d`; None when it isn't one."""
    m = _DURATION_RE.match(text or "")
    return float(m.group(1)) * _UNIT_SECONDS[m.group(2)] if m else None


def mod(w, name: str):
    """The argument of the first modifier `name` in a call's policy, or None; ""
    for a bare one. The policy is scene.call_policy(w) — the wire's own modifiers,
    then its source side's (`[A] @timeout(2s) -> [B]`) — the same reading every
    check uses, so one policy written in either place gives one run."""
    for n, arg in scene_mod.call_policy(w):
        if n == name:
            return "" if arg is None else arg
    return None


_RESILIENCE = ("timeout", "×", "deadline", "fallback", "!")


def resilient(w) -> bool:
    return any(mod(w, n) is not None for n in _RESILIENCE)


def attempts(w, limits: Limits) -> int:
    """How many attempts a failing call makes: 1 + N for `×N` retries (a symbolic N
    counts Limits.spawn), cut to floor(deadline / timeout) when both parse."""
    n = mod(w, "×")
    retries = (int(n) if n and n.isdigit() else limits.spawn) if n is not None else 0
    a = 1 + retries
    dl, to = duration(mod(w, "deadline")), duration(mod(w, "timeout"))
    if dl is not None and to:
        a = min(a, int(dl // to))
    return max(1, a)


def returned(w) -> Optional[str]:
    """What comes back on a call wire: the Call's return, the text
    after ` => ` in a non-op payload, "" for a bare `<->` reply, else None."""
    if w.call is not None and w.call.returns and not w.call.self_call:
        return w.call.returns
    if w.call is None and w.payload and " => " in w.payload:
        return w.payload.split(" => ", 1)[1].strip()
    return "" if w.kind == "<->" else None


def carried(w) -> Optional[str]:
    """What an out-going hop carries (its op, or its payload / label)."""
    if w.call is not None:
        return w.call.op or w.call.carries
    if w.payload:
        return w.payload.split(" => ", 1)[0].strip()
    return w.label


# ---------------------------------------------------------------------------
# The run — the only mutable state, owned by simulate()
# ---------------------------------------------------------------------------

class _Fail(Exception):
    """A failure travelling up a task's sync stack; guard: what failed."""
    def __init__(self, guard=None):
        super().__init__(guard)
        self.guard = guard


class _Abort(Exception):
    """A `!` critical call failed: the whole run ends."""


class _Cut(Exception):
    """A trace limit was hit."""
    def __init__(self, limit: str):
        super().__init__(limit)
        self.limit = limit


@dataclass
class _Flight:
    wire: tuple
    back: bool
    dur: int
    state: str
    carries: Optional[str]
    reach: int
    attempt: Optional[tuple]
    start: int = 0
    act: Optional[int] = None


@dataclass
class _Act:
    node: str
    ui: int
    cause: Optional[tuple]
    id: int = 0                # run-wide activation number (the `enter` event's act)
    insts: tuple = ()          # the instance keys it stands for (its lanes)
    level: int = 1             # activations of node on its task's stack, itself included


@dataclass
class _Task:
    id: int
    gen: object = None
    stack: list = field(default_factory=list)
    open: list = field(default_factory=list)      # call wires in progress
    flight: Optional[_Flight] = None
    resume: Optional[int] = None                  # tick of its next step
    wait: object = None                           # a predicate while blocked
    ended: bool = False
    failed: bool = False
    entry: bool = False
    members: list = field(default_factory=list)   # tasks it waits for (cancelled with it)
    scopes: Counter = field(default_factory=Counter)  # block keys it runs inside
    episode: int = 0                              # the episode it was forked in
    guard: object = None                          # the failure guard it ended with
    origin: Optional[_Act] = None                 # its parent's activation at the fork


_BUSY = {"active": 5, "waiting": 4, "failed": 3, "visited": 2, "opaque": 1, "cancelled": 0}


class _Run:
    """One simulation: tasks, activations, machines, instances; tick() makes Frames."""

    def __init__(self, prog: Program, sc: Scenario, limits: Limits, keep: bool = True):
        self.prog, self.limits, self.keep = prog, limits, keep
        self.choices = dict(sc.choices)
        self.entries = list(_resolve_entries(prog, sc.entries))
        self.t, self.episode, self.entry = 0, 0, None
        self.episode_t = 0             # the tick the current episode began
        self.tasks: list = []          # every task forked (numbers the next id)
        self.alive: list = []          # the tasks not ended yet, in fork order
        self.status: dict = {}
        self.taken, self.failed_w, self.routes = set(), set(), []
        self.machines = {o: m.initial for o, m in prog.machines.items()}
        self.bound: dict = {}          # owner → [state, …]: in-flight triggers' targets, FIFO
        self.changed, self.lit_now, self.ghosts = set(), set(), []
        self.insts = list(instances(prog, limits))     # every instance, spawned ones after
        self.counts = _tally(prog, self.insts)
        self.inst_parent = {i.key: i.parent for i in self.insts}
        self.wires = {w.ident: w for w in prog.scene.wires}
        self.acts = 0                  # activations numbered so far (the run's `act`)
        self.loops, self.blocks, self.held = {}, Counter(), Counter()
        self.loops_most: dict = {}     # (owner, block index) → the most iterations it ran
        self.visits, self.activations = Counter(), 0
        self.gates: dict = {}
        self.one_of = _one_of_groups(prog)
        self.owned = _owned_stores(prog)
        self.modes: dict = {}
        self.events: list = []
        self.lines, self.log_all = [], []
        self.failed_episode = self.aborted = False
        self.cut: list = []
        self.start_next = bool(self.entries)
        self.done = False

    # ---- scheduler -------------------------------------------------------

    def tick(self) -> Optional[Frame]:
        """One tick; its Frame, or None when the run keeps only its last one."""
        t = self.t
        if t == 0:
            self._log(CONVENTIONS)
            self._log_setup()
        if self.start_next:
            self._begin_episode()
        k = 0
        while k < len(self.alive) and not self.done:
            task = self.alive[k]
            k += 1
            if not task.ended and task.resume == t:
                self._advance(task)
        self._wake()
        pending = any(not x.ended and x.resume is not None for x in self.alive)
        if not self.done and not pending:
            self._event("quiet", None, waiting=[x.id for x in self.alive
                                                if not x.ended and x.wait is not None])
            if self.entries:
                self.start_next = True
            else:
                self.done = True
        if not self.done and t + 1 - self.episode_t >= self.limits.frames:
            self._cut("frames")
        if self.done:
            self._log(f"done: {self.outcome()}")
        frame = self._snapshot() if self.keep or self.done else None
        self.t += 1
        self.alive = [x for x in self.alive if not x.ended]
        self.changed, self.lit_now, self.ghosts, self.lines = set(), set(), [], []
        return frame

    def _begin_episode(self) -> None:
        self.start_next = False
        ui, nid = self.entries.pop(0)
        self.episode += 1
        self.entry = nid
        self.episode_t = self.t
        self.visits, self.activations = Counter(), 0
        self._log(f"episode {self.episode}: {self._name(nid)}")
        self._fork(lambda task: self._entry_gen(task, ui, nid), why="entry", node=nid)

    def _fork(self, factory, parent: Optional[_Task] = None, *, why: str,
              wire=None, node: Optional[str] = None) -> _Task:
        """A new task running factory(task); it starts inside the control blocks its
        parent runs at the fork (a region it re-enters there is a plain scope).
        `why` names the fork site (the `fork` event); an "entry" task is an
        episode's root."""
        task = _Task(len(self.tasks) + 1, resume=self.t, entry=why == "entry",
                     episode=self.episode)
        if parent is not None:
            task.scopes = Counter(+parent.scopes)
            task.origin = self._sender(parent)
        self.tasks.append(task)
        self.alive.append(task)
        self._event("fork", task, parent=parent.id if parent is not None else None, why=why,
                    wire=wire, node=node)
        task.gen = factory(task)
        return task

    def _event(self, kind: str, task: Optional[_Task], **fields) -> None:
        """Record one structured event (THE TRACE: events)."""
        ev = {"kind": kind, "t": self.t, "task": task.id if task is not None else None,
              "episode": task.episode if task is not None else self.episode}
        ev.update(fields)
        self.events.append(ev)

    def _advance(self, task: _Task) -> None:
        try:
            req = next(task.gen)
        except StopIteration:
            self._end(task, failed=False)
        except _Fail as f:
            task.guard = f.guard
            self._end(task, failed=True)
            if task.entry:
                self.failed_episode = True
                self._event("stop", task, how="entry", node=self.entry, guard=f.guard)
                self._log(f"episode {self.episode} failed")
        except _Abort:
            self._abort()
        except _Cut as c:
            self._cut(c.limit)
        except RecursionError:          # a backstop: Limits.stack should trip first
            self._cut("stack")
        else:
            self._request(task, req)

    def _cut(self, limit: str) -> None:
        self.cut.append(limit)
        self._event("limit", None, name=limit, node=None)
        self._log(f"cut: {limit} limit")
        self.done = True

    def _request(self, task: _Task, req: tuple) -> None:
        what = req[0]
        if what == "hop":
            fl = req[1]
            fl.start = self.t
            task.flight = fl
            task.resume = self.t + fl.dur
        elif what == "turn":
            task.resume = self.t + 1
        else:
            task.wait, task.resume = req[1], None
            if task.stack:
                self.status[task.stack[-1].node] = "waiting"

    def _end(self, task: _Task, failed: bool) -> None:
        task.ended, task.failed, task.resume = True, failed, None
        self._event("end", task, how="failed" if failed else "ok")

    def _wake(self) -> None:
        for task in self.alive:
            if not task.ended and task.wait is not None and task.wait():
                task.wait, task.resume = None, self.t + 1

    def _cancel(self, task: _Task) -> None:
        if task.ended:
            return
        for m in task.members:
            self._cancel(m)
        fl = task.flight
        if fl is not None and fl.start <= self.t <= fl.start + fl.dur:
            self.ghosts.append(self._token(task, fl, "cancelled"))
        for act in task.stack:
            self.status[act.node] = "cancelled"
            self._event("leave", task, act=act.id, how="cancelled")
        task.gen.close()
        task.ended, task.resume, task.wait = True, None, None
        self._event("end", task, how="cancelled")

    def _abort(self) -> None:
        self._log("critical call failed: the run ends")
        self.aborted = True
        for task in self.alive:
            self._cancel(task)
        self.done = True

    # ---- frames ----------------------------------------------------------

    def _token(self, task: _Task, fl: _Flight, state: Optional[str] = None) -> Token:
        frac = (self.t - fl.start) / fl.dur if fl.dur else 1.0
        at = 1.0 - frac if fl.back else frac
        return Token(fl.wire, round(at, 4), "back" if fl.back else "out", task.id,
                     state or fl.state, fl.carries, fl.reach, fl.attempt, fl.act)

    def _snapshot(self) -> Frame:
        tokens, in_flight = [], set()
        for task in self.alive:
            fl = task.flight
            if not task.ended and fl is not None and fl.start <= self.t <= fl.start + fl.dur:
                tokens.append(self._token(task, fl))
                in_flight.add(fl.wire)
        tokens += self.ghosts
        open_ = {w for task in self.alive if not task.ended for w in task.open}
        depth = {}
        for task in self.alive:
            if not task.ended:
                for nid, n in Counter(a.node for a in task.stack).items():
                    if n > 1:
                        depth[nid] = max(depth.get(nid, 0), n)
        return Frame(
            self.t, self.episode, self.entry, tuple(tokens),
            frozenset(in_flight | open_ | self.lit_now), frozenset(open_ - in_flight),
            frozenset(self.taken), frozenset(self.failed_w), dict(self.status), depth,
            dict(self.machines), frozenset(self.changed), self._instances(),
            dict(self.loops), frozenset(k for k, n in self.blocks.items() if n > 0),
            frozenset(k for k, n in self.held.items() if n > 0), tuple(self.lines), self.done)

    def _instances(self) -> dict:
        out = {}
        for (_ui, _k, t), n in zip(self.prog.tree, self.counts):
            out[t.node] = min(out.get(t.node, 0) + n, self.limits.spawns)
        return out

    def outcome(self) -> str:
        if self.cut:
            return "cut"
        return "failed" if self.failed_episode or self.aborted else "ok"

    def end(self) -> dict:
        stalled = [x.stack[-1].node for x in self.alive
                   if not x.ended and x.wait is not None and x.stack]
        return {"machines": dict(self.machines), "routes": list(self.routes),
                "stalled": list(dict.fromkeys(stalled)), "deposits": self._deposits(),
                "cut": list(self.cut),
                "visited": list(self.status), "loops": dict(self.loops_most),
                "log": list(self.log_all),
                "events": list(self.events)}

    # ---- helpers -----------------------------------------------------------

    def _log(self, text: str) -> None:
        line = f"t{self.t:03} {text}"
        self.lines.append(line)
        self.log_all.append(line)

    def _log_setup(self) -> None:
        inst = self._instances()
        if inst:
            parts = ", ".join(f"{self._name(n)} ×{c}" for n, c in inst.items())
            self._log(f"setup: {parts}")

    def _name(self, nid: str) -> str:
        sn = self.prog.scene.nodes.get(nid)
        if sn is None:
            dec = self.prog.decisions.get(nid)
            if dec is None:
                return nid
            return f"branch@{self.prog.units[dec[0]].graph.blocks[dec[1]].lines[0]}"
        return kit.node_label(sn.node)

    def _wire_text(self, w) -> str:
        text = f"{self._name(w.src)} {w.kind} {self._name(w.dst)}"
        what = carried(w)
        return f"{text} : {what}" if what else text

    def _choice(self, task: Optional[_Task], cid: tuple, default):
        """The scenario's option at choice point cid (default: none chosen); every
        consultation is a `choice` event, so an exploration sees which points a
        run met."""
        option = self.choices.get(cid, default)
        self._event("choice", task, cid=cid, option=option, default=option == default)
        return option

    def _ui(self, w) -> int:
        return self.prog.wire_unit.get(id(w), 0)

    def _hop(self, task: _Task, w, *, dur: Optional[int] = None, back: bool = False,
             state: str = "moving", carries=None, reach: int = 1, attempt=None):
        """Move a token along w; returns its flight at the arrival tick. A `hop`
        event names the activation it sets out from and, going out into a
        composition node, the instances it reaches (its lanes)."""
        sender = self._sender(task)
        fl = _Flight(w.ident, back, dur or self.limits.hop, state, carries, reach, attempt,
                     act=sender.id if sender is not None else None)
        lanes = None if back else self._lanes(w, sender)
        self._event("hop", task, act=fl.act, wire=w.ident, back=back, lanes=lanes)
        yield ("hop", fl)
        if not back and state != "failed":
            self.taken.add(w.ident)
        return fl

    def _push(self, task: _Task, ui: int, nid: str, cause) -> _Act:
        """A new activation of nid on the task (cause: the wire ident that
        started it, None for an entry), numbered run-wide; an `enter` event
        names its caller (the activation whose hop or fork started it; None for
        an episode's entry), its level on the stack and its lanes."""
        self.activations += 1
        if self.activations > self.limits.activations:
            raise _Cut("activations")
        if len(task.stack) >= self.limits.stack:
            raise _Cut("stack")
        caller = self._sender(task)
        if task.stack:
            self.status[task.stack[-1].node] = "waiting"
        self.acts += 1
        level = 1 + sum(1 for a in task.stack if a.node == nid)
        act = _Act(nid, ui, cause, self.acts, self._act_lanes(nid, cause, caller), level)
        task.stack.append(act)
        self.status[nid] = "active"
        self._event("enter", task, act=act.id, caller=caller.id if caller is not None else None,
                    node=nid, unit=ui, level=level, insts=act.insts, wire=cause)
        return act

    def _pop(self, task: _Task, act: _Act, status: str) -> None:
        if task.stack and task.stack[-1] is act:
            task.stack.pop()
        self.status[act.node] = status
        self._event("leave", task, act=act.id, how="failed" if status == "failed" else "ok")

    @staticmethod
    def _sender(task: _Task) -> Optional[_Act]:
        """The activation a task's next hop sets out from: the top of its stack,
        else (a forked task's first hop) its parent's at the fork."""
        return task.stack[-1] if task.stack else task.origin

    def _resume_caller(self, task: _Task) -> None:
        if task.stack:
            self.status[task.stack[-1].node] = "active"

    def _depth_capped(self, task: _Task, nid: str, wire=None) -> bool:
        """Whether nid is Limits.depth deep on the task's stack already: the
        base case (a `limit` event naming the capped caller's act, the level
        reached and the wire that would have gone deeper)."""
        n = sum(1 for a in task.stack if a.node == nid)
        if n >= self.limits.depth:
            top = task.stack[-1].id if task.stack else None
            self._event("limit", task, name="depth", node=nid, act=top, level=n, wire=wire)
            self._log(f"base case: {self._name(nid)} at depth {n}")
            return True
        return False

    def _reach_of(self, w, task: Optional[_Task] = None) -> int:
        """How many instances a flow into w.dst reaches from the task's sender:
        its lanes (_lanes), else the cardinality written on the flow (`->
        [App]×3`, Edge.card; a symbolic N counts Limits.spawn), else 1."""
        lanes = self._lanes(w, self._sender(task) if task is not None else None)
        if lanes is not None:
            return len(lanes)
        card = w.edge.card if w.edge is not None else None
        if not card:
            return 1
        return min(int(card) if card.isdigit() else self.limits.spawn, self.limits.spawns)

    def _picked(self, w) -> tuple:
        """The instance keys of w.dst a flow along w selects (_select)."""
        return _select(self.prog, self.insts, w, self.limits)

    def _lanes(self, w, sender: Optional[_Act]) -> Optional[tuple]:
        """The instances of w.dst a hop along w from `sender` stands for (None:
        w.dst is no composition node): for each instance the sender stands for,
        w.dst's instances under it when there are any, else every one the wire
        selects (_picked); a node calling itself keeps its own lanes."""
        if w.dst not in self.prog.tree_nodes:
            return None
        picked = self._picked(w)
        mine = sender.insts if sender is not None else ()
        if not mine:
            return picked
        if sender.node == w.dst:
            return mine
        out = []
        for i in mine:
            out += _beneath(self.inst_parent, picked, i) or list(picked)
        return tuple(dict.fromkeys(out))

    def _act_lanes(self, nid: str, cause, caller: Optional[_Act]) -> tuple:
        """The lanes of a new activation of nid: none outside the composition
        tree; along its wire, _lanes; else (an entry, an expansion's entry, an
        alias) every instance of nid."""
        if nid not in self.prog.tree_nodes:
            return ()
        w = self.wires.get(cause) if cause is not None else None
        if w is not None and w.dst == nid:
            return self._lanes(w, caller) or ()
        return tuple(i.key for i in self.insts if i.node == nid)[:self.limits.spawns]

    def _access(self, task: _Task, w, outcome: str) -> None:
        """An `access` event when w touches a store (scene.access_mode, the static
        rules' reading): outcome "done", or "unknown" for a failed attempt (RFC 0003 Q13);
        `held` the stores the task's `owns` blocks hold."""
        if w.ident not in self.modes:
            self.modes[w.ident] = scene_mod.access_mode(w, self.prog.scene.graph,
                                                        index=self.prog.access)
        mode = self.modes[w.ident]
        if mode is None:
            return
        store = w.dst if self._kind(w.dst) == "store" else w.src
        held = sorted({n for key, k in task.scopes.items() if k > 0
                       for n in self.owned.get(key, ())})
        self._event("access", task, store=store, mode=mode, wire=w.ident, held=held,
                    outcome=outcome)

    def _spawn(self, task: _Task, w) -> None:
        """A `=>` into a dynamic or `\\-?` child: one more instance (capped),
        under the parent instance with the fewest of that entry (a `spawn`
        event names it, its parent and the wire)."""
        for idx, (_ui, k, t) in enumerate(self.prog.tree):
            if t.node == w.dst and (t.spawn or t.rel in ("$", "?")):
                if sum(n for (_u, _kk, x), n in zip(self.prog.tree, self.counts)
                       if x.node == w.dst) >= self.limits.spawns:
                    self._event("limit", task, name="spawns", node=w.dst)
                    self._log("spawn cap reached")
                    return
                self.counts[idx] += 1
                parent = None
                if t.parent is not None:
                    pidx = idx - k + t.parent
                    mine = Counter(i.parent for i in self.insts if i.entry == idx)
                    parents = [i.key for i in self.insts if i.entry == pidx]
                    parent = min(parents, key=lambda p: mine[p]) if parents else None
                n = 1 + max((i.ordinal for i in self.insts if i.node == w.dst), default=0)
                inst = Instance((w.dst, n), w.dst, n, parent, t.rel, t.spawn, True, idx)
                self.insts.append(inst)
                self.inst_parent[inst.key] = parent
                self._event("spawn", task, node=w.dst, inst=inst.key, parent=parent,
                            wire=w.ident)
                self._log(f"spawn {self._name(w.dst)} ({self.counts[idx]})")
                return

    def _inactive_sibling(self, task: _Task, nid: str) -> bool:
        """A `\\-_` sibling not chosen (the first of its group is the default)."""
        for key, members in self.one_of.items():
            if nid in members:
                return self._choice(task, ("oneof", key), members[0]) != nid
        return False

    # ---- semantics: entries, activations, items ------------------------------

    def _entry_gen(self, task: _Task, ui: int, nid: str):
        if nid in self.prog.decisions:
            dui, bi = self.prog.decisions[nid]
            yield from self._branch(task, dui, bi, None)
            return
        act = self._push(task, ui, nid, None)
        yield from self._run(task, act, None)

    def _activate(self, task: _Task, ui: int, nid: str, cause, arm=None, alias=None):
        """Push nid's activation onto the task, take a turn, run it."""
        act = self._push(task, ui, nid, cause)
        yield ("turn",)
        yield from self._run(task, act, arm, alias)

    def _run(self, task: _Task, act: _Act, arm, alias: Optional[tuple] = None):
        """An activation's work — its own body, or the alias (ui, alias node) a call
        named (an op whose verb names an alias) — then its pop; a failure fires its routes and travels
        on to the caller."""
        node = self.prog.scene.nodes[act.node].node if act.node in self.prog.scene.nodes else None
        try:
            if self._choice(task, ("node", act.node), "ok") == "fails":
                self._log(f"{self._name(act.node)} fails")
                self._event("fail", task, origin=("node", act.node), node=act.node)
                raise _Fail(None)
            if node is not None and node.kind == "event":
                self._deliver(task, act)
            if alias is not None:
                yield from self._activate(task, alias[0], alias[1], act.cause)
            else:
                yield from self._body(task, act, arm)
        except _Fail as f:
            try:
                yield from self._fire_routes(task, act, f)
            finally:
                self._pop(task, act, "failed")
            raise _Fail(("node", act.node)) from None
        self._pop(task, act, "visited")

    def _body(self, task: _Task, act: _Act, arm):
        """A node's own work in its unit: its expansion's entries, its body (or its
        part of a branch arm), then the branches it heads."""
        exp = self.prog.expansions.get((act.ui, act.node))
        if exp is not None and arm is None:
            for e in self.prog.entries.get(exp, ()):
                yield from self._entry_gen(task, exp, e)
        items = (self.prog.arm_bodies.get(arm, {}).get(act.node, ()) if arm
                 else self.prog.bodies.get((act.ui, act.node), ()))
        yield from self._items(task, items, arm)
        if arm is None:
            for bi in self.prog.branches.get((act.ui, act.node), ()):
                yield from self._branch(task, act.ui, bi, act.node)

    def _fire_routes(self, task: _Task, act: _Act, f: _Fail):
        """The failed activation's routes, in written order: those
        guarded by what failed, else the unguarded ones."""
        for w in selected_routes(self.prog.routes.get((act.ui, act.node), ()), f.guard):
            yield from self._route(task, act, w, f.guard)

    def _route(self, task: _Task, act: _Act, w, guard):
        """Take one failure route out of act's node for the failure `guard`. A
        route target's own failure ends that route only; the remaining routes
        still fire."""
        self.failed_w.add(w.ident)
        self.routes.append(w.ident)
        self._event("route", task, node=act.node, wire=w.ident, guard=guard)
        self._log(f"{self._name(act.node)} failed → {self._name(w.dst)}")
        task.open.append(w.ident)
        try:
            yield from self._hop(task, w, state="failed", carries=carried(w))
            yield from self._land(task, w, None)
        except _Fail:
            self._event("stop", task, how="route-failed", node=w.dst, guard=("node", w.dst))
            self._log(f"route failed: {self._name(w.dst)}")
        finally:
            task.open.remove(w.ident)

    def _items(self, task: _Task, items, arm):
        for it in items:
            if isinstance(it, Step):
                yield from self._step(task, it.wire, arm)
            elif isinstance(it, Group):
                yield from self._group(task, it, arm)
            else:
                yield from self._region(task, it, arm)

    def _step(self, task: _Task, w, arm):
        if w.kind == "~>":
            self._fork(lambda t, w=w: self._async(t, w, arm), task, why="async", wire=w.ident)
            return
        if w.kind == "?>" and self._choice(task, ("cond", w.ident), "skip") != "take":
            return
        gate = _gate_of(self.prog, w)
        if gate is not None:
            yield from self._gate(task, w, gate, arm)
            return
        yield from self._call(task, w, arm)

    def _async(self, task: _Task, w, arm):
        """A `~>` send in its own task: hop, then the receiver's work. A send the
        scenario fails makes its attempts and never arrives; neither that nor the
        receiver's failure reaches the sender (catalog §6 B3)."""
        if self._inactive_sibling(task, w.dst):
            return
        if self._choice(task, ("call", w.ident), "ok") == "fails":
            yield from self._failing(task, w, self.limits.hop)
            self.failed_w.add(w.ident)
            self._event("fail", task, origin=("call", w.ident), node=w.src, fallback=False,
                        critical=False, tries=attempts(w, self.limits), callee=False)
            self._log(self._failure_text(w))
            self._unawaited(task, w.dst, ("call", w.ident))
            return
        self._log(f"send {self._wire_text(w)}")
        yield from self._hop(task, w, carries=carried(w), reach=self._reach_of(w, task))
        try:
            yield from self._land(task, w, arm)
        except _Fail as f:
            self._unawaited(task, w.dst, f.guard)

    def _unawaited(self, task: _Task, nid: str, guard) -> None:
        """A failure that stops where nothing awaits it: a `~>` send, or the
        consumer behind a stream or a `=>` hop (catalog §6 B13)."""
        self._event("stop", task, how="unawaited", node=nid, guard=guard)
        self._log(f"{self._name(nid)} failed (not awaited)")

    # ---- calls -------------------------------------------------------------

    def _call(self, task: _Task, w, arm):
        """A sync call along w: attempts, the callee's work, the return."""
        if w.src == w.dst or (w.call is not None and w.call.self_call):
            yield from self._self_call(task, w)
            return
        if self._inactive_sibling(task, w.dst):
            self._log(f"not taken: {self._name(w.dst)} is not the active one")
            return
        if self._choice(task, ("call", w.ident), "ok") == "fails":
            yield from self._failing(task, w, self.limits.hop)
            yield from self._call_failed(task, w)
            return
        a = attempts(w, self.limits) if resilient(w) else 0
        self._log(self._wire_text(w) + (f" attempt 1/{a}" if a > 1 else ""))
        task.open.append(w.ident)
        yield from self._hop(task, w, carries=carried(w), reach=self._reach_of(w, task),
                             attempt=(1, a) if a > 1 else None)
        try:
            yield from self._land(task, w, arm)
        except _Fail as f:
            task.open.remove(w.ident)
            if _detached(self.prog, w):
                self._unawaited(task, w.dst, f.guard)
                self._resume_caller(task)
                return
            yield from self._call_failed(task, w, callee_failed=True)
            return
        yield from self._return(task, w)
        task.open.remove(w.ident)

    def _land(self, task: _Task, w, arm):
        """A token has arrived at w.dst: run what the node does there (the body of
        the alias w's op names, if any) — every arrival that activates a node comes
        through here, so here is the one depth check (a re-entry beyond
        Limits.depth is the base case)."""
        dst = w.dst
        sn = self.prog.scene.nodes.get(dst)
        if w.kind == "=>":
            self._spawn(task, w)
        self._access(task, w, "done")
        if self._reach_of(w, task) == 0:
            self._log(f"no instance of {self._name(dst)}")
            yield ("turn",)
            return
        if sn is not None and (sn.node.is_hole or sn.external
                               or (w.call is not None and w.call.external)):
            self.status[dst] = "opaque"
            yield ("turn",)
            return
        if sn is not None and sn.node.kind == "actor":
            self.status[dst] = "visited"
            yield ("turn",)
            return
        if not task.stack:              # a task's root: what an async cycle repeats
            self.visits[dst] += 1
            if self.visits[dst] > self.limits.visits:
                self._event("limit", task, name="visits", node=dst)
                self._log(f"visit limit: {self._name(dst)}")
                yield ("turn",)
                return
        alias = _alias_of(self.prog, w)
        if (self._depth_capped(task, dst, w.ident)
                or (alias and self._depth_capped(task, alias[1], w.ident))):
            yield ("turn",)
            return
        yield from self._activate(task, self._ui(w), dst, w.ident, arm, alias)

    def _return(self, task: _Task, w):
        back = returned(w)
        if back is None:
            self._resume_caller(task)
            return
        self._log(f"{self._name(w.dst)} ↩ {back}" if back else f"{self._name(w.dst)} replies")
        yield from self._hop(task, w, back=True, carries=back or None)
        self._resume_caller(task)
        yield ("turn",)

    def _failing(self, task: _Task, w, dur: int):
        """Every attempt of a failing call fails on arrival."""
        a = attempts(w, self.limits)
        for k in range(1, a + 1):
            self._log(f"{self._wire_text(w)} attempt {k}/{a}")
            fl = yield from self._hop(task, w, dur=dur, state="moving", carries=carried(w),
                                      attempt=(k, a))
            fl.state = "failed"
            self.status[w.dst] = "failed"
            self._access(task, w, "unknown")
            self._log(f"attempt {k}/{a} failed")
            yield ("turn",)

    def _call_failed(self, task: _Task, w, *, callee_failed: bool = False):
        """A call has finally failed: the routes guarded by this call fire and its
        fallback comes back (the caller goes on: "notify, then yield"), or the
        failure travels. callee_failed: the call arrived and its callee's work
        failed, so it made one attempt (a callee's failure is never retried)."""
        fb = mod(w, "fallback")
        critical = fb is None and mod(w, "!") is not None
        self._event("fail", task, origin=("call", w.ident), node=w.src,
                    fallback=fb is not None, critical=critical,
                    tries=1 if callee_failed else attempts(w, self.limits),
                    callee=callee_failed)
        if fb is not None:
            yield from self._guarded_routes(task, ("call", w.ident))
            self._event("stop", task, how="fallback", node=w.src, guard=("call", w.ident))
            self._log(f"{self._name(w.src)} falls back to {fb}")
            yield from self._hop(task, w, back=True, state="fallback", carries=fb)
            self._resume_caller(task)
            yield ("turn",)
            return
        self.failed_w.add(w.ident)
        self._log(self._failure_text(w, callee_failed=callee_failed))
        if critical:
            self._event("stop", task, how="abort", node=w.src, guard=("call", w.ident))
            raise _Abort()
        raise _Fail(("call", w.ident))

    def _failure_text(self, w, *, callee_failed: bool = False) -> str:
        """The log line of a failed call, naming the attempts it actually made:
        all of attempts() when the call itself failed, one when its callee did."""
        what = carried(w) or self._name(w.dst)
        if not resilient(w):
            tries = ""
        elif callee_failed:
            tries = " failed after 1 attempt (its callee failed)"
        else:
            a = attempts(w, self.limits)
            tries = f" failed after {a} attempt{'s' if a > 1 else ''}"
        return f"{self._name(w.src)} failed: {what}{tries}"

    def _guarded_routes(self, task: _Task, guard: tuple):
        """The caller's routes guarded by `guard` (never its unguarded ones: the
        caller itself has not failed)."""
        if not task.stack:
            return
        act = task.stack[-1]
        for w, g in self.prog.routes.get((act.ui, act.node), ()):
            if _guards(g, guard):
                yield from self._route(task, act, w, guard)

    def _self_call(self, task: _Task, w):
        """A self-call: a one-tick pulse; an alias body or a
        recursion runs as its work; a target op's `=>` wires are its return."""
        call = w.call
        alias = _alias_of(self.prog, w)
        glyph = w.edge is None or not w.edge.target_op     # `[D] -> [D]`: the node recurses
        target = alias[1] if alias else (w.src if glyph else None)
        if target is not None and self._depth_capped(task, target, w.ident):
            return
        if self._choice(task, ("call", w.ident), "ok") == "fails":
            yield from self._failing(task, w, 1)
            yield from self._call_failed(task, w)
            return
        self._log(f"{self._name(w.src)} {scene_mod.call_text(call) if call else '↺'}")
        task.open.append(w.ident)
        yield from self._hop(task, w, dur=1, carries=carried(w))
        if target is not None:
            ui = alias[0] if alias else self._ui(w)
            try:
                yield from self._activate(task, ui, target, w.ident)
            except _Fail:
                task.open.remove(w.ident)
                yield from self._call_failed(task, w, callee_failed=True)
                return
        else:
            yield ("turn",)
        task.open.remove(w.ident)
        self._resume_caller(task)
        yield from self._items(task, self.prog.returns.get(w.ident, ()), None)

    # ---- groups, gates, regions, branches ------------------------------------

    def _group(self, task: _Task, g: Group, arm):
        """A join or fan-out group: first who takes part (_group_members), then how
        the arrow runs them — `~>` forks them unawaited (a race: the winner only),
        an alternative is one step, a race and an `&` / `*>` fork and await."""
        kept, winner = self._group_members(task, g)
        if not kept:
            return
        if kept[0].kind == "~>":
            for w in ([winner] if g.kind == "race" else kept):
                self._fork(lambda t, w=w: self._async(t, w, arm), task, why="async",
                           wire=w.ident)
            return
        if g.kind == "alt":
            yield from self._step(task, winner, arm)
            return
        if g.kind == "race":
            members = [self._fork(lambda t, w=w: (self._call(t, w, arm) if w is winner
                                                  else self._lose(t, w)), task,
                                  why="race", wire=w.ident)
                       for w in kept]
            task.members = members
            won = [m for m, w in zip(members, kept) if w is winner]
            yield from self._await(task, members, need=won, failing=won, guard=None)
            return
        members = [self._fork(lambda t, w=w: self._call(t, w, arm), task,
                              why="fan" if w.kind == "*>" else "join", wire=w.ident)
                   for w in kept]
        task.members = members
        yield from self._await(task, members, need=members, failing=members, guard=None)

    def _group_members(self, task: _Task, g: Group) -> tuple:
        """(kept wires, the chosen one): the members whose `?>` the scenario takes
        (an unconditional member always), and among them the alternative / race
        winner the scenario picks — the first kept when it picks none of them."""
        kept = [w for w in g.wires
                if w.kind != "?>" or self._choice(task, ("cond", w.ident), "skip") == "take"]
        if not kept or g.kind == "all":
            return kept, None
        pick = self._choice(task, (g.kind, g.key), kept[0].dst)
        winner = next((w for w in kept if w.dst == pick), kept[0])
        return ([winner] if g.kind == "alt" else kept), winner

    def _lose(self, task: _Task, w):
        """A race member that loses (a `&?` member, a `parallel @any` member's head
        wire): its token hops and is cancelled when the winner arrives; nothing of
        it runs."""
        fl = yield from self._hop(task, w, carries=carried(w))
        fl.state = "cancelled"
        self.status[w.dst] = "cancelled"
        self._log(f"race lost: {self._wire_text(w)}")

    def _await(self, task: _Task, members: list, *, need: list, failing: list, guard):
        """Block until every task in `need` ended or one in `failing` failed; then
        cancel the rest of `members`. A failure among `failing` (every member of an
        `&` / `*>` / `@all`; the winner of a race / `@any`) fails the waiter with
        `guard` — None: the failed member's own (its call), so the routes of the
        member's line fire (catalog §6 B1); the others' failures are theirs alone."""
        self._event("await", task, members=[m.id for m in members], need=[m.id for m in need])
        yield ("wait", lambda: all(m.ended for m in need) or any(m.failed for m in failing))
        failed = next((m for m in failing if m.failed), None)
        for m in members:
            if not m.ended:
                self._log(f"cancelled: task {m.id}")
                self._cancel(m)
        task.members = []
        self._event("resume", task, failed=failed is not None)
        self._resume_caller(task)
        if failed is not None:
            raise _Fail(guard if guard is not None else failed.guard)

    def _gate(self, task: _Task, w, gate: tuple, arm):
        """A source join: each member deposits at the gate and goes on (never a
        barrier); `&` runs the target once when the last arrives, `&?` when the first
        does (later arrivals are dropped). A deposit is not a call the arriver
        awaits, so it is no failure choice point: a join's `@timeout` bounds the
        target's wait for the missing members (the open deposit), not the arrival
        (RFC 0003 Q3)."""
        ui, j, kind = gate
        members = self.prog.units[ui].graph.joins[j].members
        key = (ui, j, w.dst)
        state = self.gates.setdefault(key, {"arrived": [], "fired": False, "round": 0})
        self._log(self._wire_text(w))
        task.open.append(w.ident)
        yield from self._hop(task, w, carries=carried(w))
        state["arrived"].append(w.src)
        self._event("gate-arrive", task, key=key, round=state["round"], node=w.src,
                    wire=w.ident)
        everyone = all(m in state["arrived"] for m in members)
        if kind == "&?" and state["fired"]:
            self._event("gate-drop", task, key=key, round=state["round"], node=w.src)
            self._log(f"race lost: {self._wire_text(w)}")
            if everyone:
                self._reset_gate(state)
            task.open.remove(w.ident)
            yield ("turn",)
            return
        if kind == "&" and not everyone:
            self._log(f"deposit: {self._name(w.src)} at {self._name(w.dst)}")
            task.open.remove(w.ident)
            self._resume_caller(task)
            return
        state["fired"] = True
        self._event("gate-fire", task, key=key, round=state["round"], node=w.dst)
        try:
            yield from self._land(task, w, arm)
        finally:
            if kind == "&" or everyone:
                self._reset_gate(state)
        task.open.remove(w.ident)
        self._resume_caller(task)

    @staticmethod
    def _reset_gate(state: dict) -> None:
        """A gate's round is over: the next arrivals start the next one."""
        state.update(arrived=[], fired=False, round=state["round"] + 1)

    def _deposits(self) -> list:
        """The `&` joins a run leaves open: deposits no last arrival consumed."""
        out = []
        for (ui, j, dst), state in self.gates.items():
            join = self.prog.units[ui].graph.joins[j]
            if join.kind == "&" and state["arrived"]:
                arrived = list(dict.fromkeys(state["arrived"]))
                out.append({"join": (ui, j), "target": dst, "arrived": arrived,
                            "missing": [m for m in join.members if m not in arrived]})
        return out

    def _region(self, task: _Task, r: Region, arm):
        """A control block's part of a body. Only the outermost entry
        into a block on a task repeats or forks it (and keeps its iteration): a node
        called from inside the block runs its own part of it as a plain scope. A
        failure leaving the block is the block's (guard ("block", index)), so the
        routes after its `}` fire; an enclosing block re-labels it as its own."""
        b = r.block
        key = (self.prog.units[r.ui].owner, r.index)
        if task.scopes[key]:            # already inside it on this task: a plain scope
            try:
                yield from self._items(task, r.items, arm)
            except _Fail:
                raise _Fail(("block", r.index)) from None
            return
        subject = not task.stack or not b.subject or task.stack[-1].node in b.subject
        kind = b.kind if subject else "scope"
        held = [n for n in b.refs if self._kind(n) == "store"] if b.kind == "owns" else []
        self.blocks[key] += 1
        task.scopes[key] += 1
        for n in held:
            self.held[n] += 1
            self._log(f"acquire {self._name(n)}")
        try:
            if kind == "loop":
                n = loop_count(b, self.limits)
                times = _declared_times(b)
                if times is not None and n < times:
                    self._event("limit", task, name="iterations", node=key[0], block=r.index)
                    self._log(f"loop capped: @times {times} runs {n}")
                for k in range(1, n + 1):
                    self.loops[key] = k
                    self.loops_most[key] = max(self.loops_most.get(key, 0), k)
                    self._log(f"iteration {k}/{n}")
                    yield from self._items(task, r.items, arm)
            elif kind == "parallel":
                yield from self._parallel(task, r, arm)
            else:
                yield from self._items(task, r.items, arm)
        except _Fail:
            raise _Fail(("block", r.index)) from None
        finally:
            self.blocks[key] -= 1
            task.scopes[key] -= 1
            self.loops.pop(key, None)
            for n in held:
                self.held[n] -= 1
                self._log(f"release {self._name(n)}")

    def _kind(self, nid: str) -> str:
        sn = self.prog.scene.nodes.get(nid)
        return sn.node.kind if sn else ""

    def _parallel(self, task: _Task, r: Region, arm):
        """`@all` forks every member and awaits all; `@any` runs the scenario's
        winner while each loser only hops (cancelled on the winner's arrival) and
        awaits the winner alone; `@none` forks and goes on."""
        mods = {n for n, _a in r.block.modifiers}
        guard = ("block", r.index)
        if "any" in mods:
            heads = [_flat((it,))[0] for it in r.items]
            win = self._choice(task, ("any", (r.ui, r.index)), heads[0].dst)
            k = next((j for j, h in enumerate(heads) if h.dst == win), 0)
            members = [self._fork(lambda t, it=it, h=h, j=j: (
                self._items(t, (it,), arm) if j == k else self._lose(t, h)), task,
                why="parallel", wire=h.ident)
                for j, (it, h) in enumerate(zip(r.items, heads))]
            task.members = members
            yield from self._await(task, members, need=[members[k]], failing=[members[k]],
                                   guard=guard)
            return
        members = [self._fork(lambda t, it=it: self._items(t, (it,), arm), task,
                              why="parallel", wire=_flat((it,))[0].ident)
                   for it in r.items]
        if "none" in mods:
            return
        task.members = members
        yield from self._await(task, members, need=members, failing=members, guard=guard)

    def _branch(self, task: _Task, ui: int, bi: int, header: Optional[str]):
        """A branch decides at its header: the chosen arm's wire carries a token to
        the arm's entry, which runs only that arm's wires."""
        b = self.prog.units[ui].graph.blocks[bi]
        arms = [(label, ids) for label, ids in b.arm_nodes if ids]
        if not arms:
            return
        label = self._choice(task, ("branch", (ui, bi)), arms[0][0])
        ids = next((i for lab, i in arms if lab == label), arms[0][1])
        w = self.prog.arm_wire.get((ui, bi, label))
        key = (self.prog.units[ui].owner, bi)
        self.blocks[key] += 1
        self._log(f"branch {b.header}: {label}")
        try:
            if w is not None:
                task.open.append(w.ident)
                yield from self._hop(task, w, carries=label)
                task.open.remove(w.ident)
            yield from self._activate(task, ui, ids[0], w.ident if w is not None else None,
                                      (ui, bi, label))
        finally:
            self.blocks[key] -= 1
        self._resume_caller(task)

    # ---- state machines ------------------------------------------------------

    def _deliver(self, task: _Task, act: _Act) -> None:
        """An event's triggers: a task per machine with a matching transition (a
        specific one beats `_`: catalog §6 NG6), forked by the delivering task. A machine
        heading for `$`, or with no transition from its heading state, ignores it."""
        refs = self.prog.triggers.get(act.node, ())
        for owner in dict.fromkeys(r.trigger.owner for r in refs):
            mine = [r for r in refs if r.trigger.owner == owner]
            state = self._heading(owner)
            if state is None:
                continue
            pick = (None if _pseudo(self.prog, state) == "end"
                    else self._pick(task, mine, owner, state))
            if pick is None:
                self._ignored(task, act.node, mine[0].trigger.label, owner, state)
                continue
            self.bound.setdefault(owner, []).append(pick.trigger.dst)
            self._fork(lambda t, r=pick: self._trigger(t, r), task, why="trigger",
                       wire=pick.wire.ident, node=act.node)

    def _heading(self, owner: str) -> Optional[str]:
        """The state a delivery to owner is judged in: where its last in-flight
        trigger takes it (triggers land in send order), else its state now."""
        bound = self.bound.get(owner)
        return bound[-1] if bound else self.machines.get(owner)

    def _pick(self, task: _Task, refs: list, owner: str, state: str) -> Optional[TriggerRef]:
        """The transition the owner's refs take from `state` (None: none leaves
        it). Two from one written source are the scenario's choice, keyed by that
        source — the state, or the `_` the wildcard transitions are written from —
        as _machine_points lists it."""
        match = self._matching(refs, state)
        if not match:
            return None
        pick = match[0]
        if len(match) > 1:
            t = pick.trigger
            dst = self._choice(task, ("machine", (owner, t.src, t.label)), t.dst)
            pick = next((r for r in match if r.trigger.dst == dst), pick)
        return pick

    def _matching(self, refs: list, state: str) -> list:
        """The refs whose transition leaves `state`: those written from it, else
        the `_` ones (a specific transition beats the wildcard: catalog §6 NG6, Q12)."""
        specific = [r for r in refs if r.trigger.src == state]
        return specific or [r for r in refs
                            if _pseudo(self.prog, r.trigger.src) == "any"]

    def _ignored(self, task: _Task, event: str, label: str, owner: str, state) -> None:
        self._event("ignored", task, event=event, label=label, owner=owner, state=state)
        self._log(f"ignored: {label} — {self._name(owner)} in {self._state_name(state)}")

    def _trigger(self, task: _Task, ref: TriggerRef):
        """A trigger's hop, then the transition the machine's state on arrival
        takes (resolved again there: another delivery may have moved it since; a
        specific transition beats `_`: catalog §6 NG6, RFC 0003 Q12) — or none: ignored."""
        t = ref.trigger
        try:
            yield from self._hop(task, ref.wire, carries=t.label)
        finally:
            self.bound[t.owner].pop(0)
        state = self.machines.get(t.owner)
        pick = None
        if state is not None and _pseudo(self.prog, state) != "end":
            mine = [r for r in self.prog.triggers.get(t.event, ()) if r.trigger.owner == t.owner]
            pick = self._pick(task, mine, t.owner, state)
        if pick is None:
            self._ignored(task, t.event, t.label, t.owner, state)
        else:
            self._transition(task, pick, state)
        yield ("turn",)

    def _transition(self, task: _Task, ref: TriggerRef, state: str) -> None:
        """The machine leaves `state` along ref's transition."""
        t = ref.trigger
        self.machines[t.owner] = t.dst
        self.changed.add(t.owner)
        if ref.transition is not None:
            self.lit_now.add(ref.transition)
        self._event("transition", task, owner=t.owner, label=t.label, src=state, dst=t.dst)
        self._log(f"{self._name(t.owner)} {self._state_name(state)} -{t.label}-> "
                  f"{self._state_name(t.dst)}")

    def _state_name(self, nid: Optional[str]) -> str:
        n = self.prog.unit_nodes.get(nid)
        if n is not None:
            return {"start": "+", "end": "$", "any": "_"}.get(n.attrs.get("pseudo"), n.name)
        return str(nid)


def loop_count(b, limits: Limits) -> int:
    """How often a loop runs: `@times N` capped by Limits.iterations, else the limit.
    A pure function of Block.modifiers and the limits (the checks compare it with
    the declared N: a loop the simulator runs fewer times than written)."""
    times = _declared_times(b)
    return limits.iterations if times is None else min(times, limits.iterations)


def _declared_times(b) -> Optional[int]:
    """A loop's numeric `@times N`, else None."""
    times = next((a for n, a in b.modifiers if n == "times"), None)
    return int(times) if times and times.strip().isdigit() else None


# ---------------------------------------------------------------------------
# Failure flow — the run's failure handling, read statically
# ---------------------------------------------------------------------------
#
# A may-fail fixpoint that mirrors _Run: which failure guards can reach each
# activation (where _run fires its routes), and so which routes some failure
# selects. It changes no run. The rules it mirrors, function by function:
#   _run          a node's own outcome choice fails it with guard None; whatever
#                 fails it travels on as ("node", its id)
#   _call         a call's outcome choice, or its callee failing, fails the call;
#   _call_failed  then `@fallback` absorbs it (the caller's routes guarded by the
#                 call still fire, on the caller's own task only), `!` ends the run
#                 (no route fires), else it raises ("call", ident)
#   _self_call    the same over the recursion / alias body; then its `=>` returns
#   _region       relabels any failure leaving it as ("block", index); a loop run 0
#                 times runs nothing; `parallel` forks its members (a member's
#                 fallback fires no route), @all / @any await, @none does not
#   _group        `~>` members are forked unawaited; an alternative is a step; an
#                 `&` / `*>` / race member's failure fails the waiter with the
#                 member's own ("call", ident) (catalog §6 B1)
#   _gate         a source join's target failing raises ("node", target)
#   _async        a `~>` send: its own and the receiver's failure stop there (catalog §6 B3)
#   _detached     a `=>` hop or a flow into a stream: the callee's failure stops
#                 there; only the hop's own outcome fails the call (catalog §6 B13)
#   _branch       an arm entry's failure travels as ("node", arm entry)
#   _fire_routes  routes guarded by the arriving guard, else the unguarded ones
# Every choice may go either way (each is a scenario option); limits that only
# cut a run short (depth, visits, instances) are not modelled, so a route this
# calls live may need a deeper run, or two deviations, to fire.

def _alias_of(prog: Program, w) -> Optional[tuple]:
    """(ui, alias node) of the alias w's op verb names, else None."""
    if w.call is None or not w.call.op:
        return None
    return prog.aliases.get(scene_mod.op_verb(w.call.op))


def _gate_of(prog: Program, w) -> Optional[tuple]:
    """(unit, join index, kind) of a `&` / `&?` source join w leaves, else None."""
    if w.edge is None or w.edge.src_join is None:
        return None
    ui = prog.wire_unit.get(id(w), 0)
    joins = getattr(prog.units[ui].graph, "joins", None) or []
    j = w.edge.src_join
    if not 0 <= j < len(joins) or joins[j].kind == "/":
        return None
    return (ui, j, joins[j].kind)


def _detached(prog: Program, w) -> bool:
    """Whether a failure landing along w stops there instead of failing the
    sender (catalog §6 B13): a `=>` produce hop, or a flow into a stream — the producer
    deposits and goes on, so a failure stops at the consumer."""
    if w.kind == "=>":
        return True
    sn = prog.scene.nodes.get(w.dst)
    return sn is not None and sn.node.is_stream


def _owned_stores(prog: Program) -> dict:
    """{(owner, block index): (store id, …)} of every `owns` block: the stores a
    task inside it holds (the key _region counts in task.scopes)."""
    out = {}
    for u in prog.units:
        for bi, b in enumerate(getattr(u.graph, "blocks", None) or []):
            if b.kind == "owns":
                stores = tuple(n for n in b.refs
                               if (sn := prog.scene.nodes.get(n)) is not None
                               and sn.node.kind == "store")
                out[(u.owner, bi)] = out.get((u.owner, bi), ()) + stores
    return out


class _Ctx(NamedTuple):
    """One kind of activation: a node in a unit, in a branch arm or not, running
    an alias's body or its own, on a task already inside these block keys."""
    ui: int
    node: str
    arm: Optional[tuple]
    alias: Optional[tuple]
    scopes: frozenset


class _Place(NamedTuple):
    """Where a stretch of work runs: the activation on top of the task (None on a
    forked member's own task), its arm, the blocks the task is inside, and
    whether a fallback's guarded routes reach that activation."""
    node: Optional[str]
    arm: Optional[tuple]
    scopes: frozenset
    on_task: bool


class _Effect(NamedTuple):
    raises: frozenset = frozenset()     # guards the work raises to its activation
    absorbed: frozenset = frozenset()   # ("call", ident) a fallback absorbed there
    started: tuple = ()                 # the _Ctx activations it starts


class _Flow(NamedTuple):
    """The fixed inputs of one failure-flow pass."""
    prog: Program
    limits: Limits
    failing_nodes: frozenset            # node ids with a node outcome choice
    failing_calls: frozenset            # wire idents with a call outcome choice


class FailureFlow(NamedTuple):
    """failure_flow's full result. arriving: {(ui, node): frozenset of guards that
    can fail that activation} for every node some entry activates (empty: it cannot
    fail); absorbed: {(ui, node): frozenset of ("call", ident)} a fallback absorbed
    there (its guarded routes fire, the node goes on); live: the idents of the
    routes some failure selects."""
    arriving: dict
    absorbed: dict
    live: frozenset


def _merge(*effects: _Effect) -> _Effect:
    return _Effect(frozenset().union(*(e.raises for e in effects)),
                   frozenset().union(*(e.absorbed for e in effects)),
                   tuple(c for e in effects for c in e.started))


def _relabel(e: _Effect, guard: tuple) -> _Effect:
    return e._replace(raises=frozenset({guard}) if e.raises else frozenset())


def _land_ctx(prog: Program, w, arm, scopes: frozenset) -> Optional[_Ctx]:
    """The activation a token arriving along w starts (_land), or None where
    _land starts none: a hole, an external node or op, an actor."""
    sn = prog.scene.nodes.get(w.dst)
    if sn is not None and (sn.node.is_hole or sn.external
                           or (w.call is not None and w.call.external)):
        return None
    if sn is not None and sn.node.kind == "actor":
        return None
    return _Ctx(prog.wire_unit.get(id(w), 0), w.dst, arm, _alias_of(prog, w), scopes)


def _failed_call(w, at: _Place) -> _Effect:
    """_call_failed: a fallback absorbs, `!` ends the run, else ("call", ident)."""
    if mod(w, "fallback") is not None:
        return _Effect(absorbed=frozenset({("call", w.ident)}) if at.on_task else frozenset())
    if mod(w, "!") is not None:
        return _Effect()
    return _Effect(raises=frozenset({("call", w.ident)}))


def _fails(ctx: Optional[_Ctx], fails: dict) -> bool:
    return ctx is not None and bool(fails.get(ctx))


class _Asked(dict):
    """failure_analysis's fails ({ctx: guards}), noting in `asked` (when set)
    every context an activation reads, so a round re-runs only the activations
    whose reads changed (an activation is a pure function of them)."""
    asked = None

    def get(self, key, default=None):
        if self.asked is not None:
            self.asked.add(key)
        return super().get(key, default)


def _call_effect(fl: _Flow, fails: dict, w, at: _Place) -> _Effect:
    """_call / _self_call."""
    prog = fl.prog
    chosen = w.ident in fl.failing_calls
    if w.src == w.dst or (w.call is not None and w.call.self_call):
        alias = _alias_of(prog, w)
        glyph = w.edge is None or not w.edge.target_op
        target = None
        if alias:
            target = _Ctx(alias[0], alias[1], None, None, at.scopes)
        elif glyph:
            target = _Ctx(prog.wire_unit.get(id(w), 0), w.src, None, None, at.scopes)
        failed = _failed_call(w, at) if chosen or _fails(target, fails) else _Effect()
        returns = _walk(fl, fails, prog.returns.get(w.ident, ()), at._replace(arm=None))
        return _merge(failed, returns, _Effect(started=(target,) if target else ()))
    target = _land_ctx(prog, w, at.arm, at.scopes)
    landed = _fails(target, fails) and not _detached(prog, w)
    failed = _failed_call(w, at) if chosen or landed else _Effect()
    return _merge(failed, _Effect(started=(target,) if target else ()))


def _step_effect(fl: _Flow, fails: dict, w, at: _Place) -> _Effect:
    """_step: `~>` forks (its failure stops there), a source join's target fails
    the arriving member raw (the deposit itself never fails, RFC 0003 Q3), anything else
    is a call."""
    if w.kind == "~>":
        target = _land_ctx(fl.prog, w, at.arm, at.scopes)
        return _Effect(started=(target,) if target else ())
    if _gate_of(fl.prog, w) is not None:
        target = _land_ctx(fl.prog, w, at.arm, at.scopes)
        if target is None:
            return _Effect()
        raises = frozenset({("node", w.dst)}) if _fails(target, fails) else frozenset()
        return _Effect(raises=raises, started=(target,))
    return _call_effect(fl, fails, w, at)


def _group_effect(fl: _Flow, fails: dict, g: Group, at: _Place) -> _Effect:
    """_group: any kept member may be the alternative or the race's winner; an
    awaited member's failure reaches the waiter as its own call's guard (catalog §6 B1)."""
    if g.wires[0].kind == "~>" or g.kind == "alt":
        return _merge(*(_step_effect(fl, fails, w, at) for w in g.wires))
    forked = at._replace(node=None, on_task=False)
    return _merge(*(_call_effect(fl, fails, w, forked) for w in g.wires))


def _region_effect(fl: _Flow, fails: dict, r: Region, at: _Place) -> _Effect:
    """_region: a plain scope on re-entry; else a loop, a parallel fork or a scope."""
    b = r.block
    key = (fl.prog.units[r.ui].owner, r.index)
    guard = ("block", r.index)
    if key in at.scopes:
        return _relabel(_walk(fl, fails, r.items, at), guard)
    subject = at.node is None or not b.subject or at.node in b.subject
    kind = b.kind if subject else "scope"
    inside = at._replace(scopes=at.scopes | {key})
    if kind == "loop" and loop_count(b, fl.limits) == 0:
        return _Effect()
    if kind != "parallel":
        return _relabel(_walk(fl, fails, r.items, inside), guard)
    forked = inside._replace(node=None, on_task=False)
    members = _merge(*(_walk(fl, fails, (it,), forked) for it in r.items))
    if "none" in {n for n, _a in b.modifiers}:
        return _Effect(started=members.started)
    return _relabel(members, guard)


def _walk(fl: _Flow, fails: dict, items, at: _Place) -> _Effect:
    """_items: the effect of a body's items run where `at` says."""
    out = []
    for it in items:
        if isinstance(it, Step):
            out.append(_step_effect(fl, fails, it.wire, at))
        elif isinstance(it, Group):
            out.append(_group_effect(fl, fails, it, at))
        else:
            out.append(_region_effect(fl, fails, it, at))
    return _merge(*out)


def _branch_effect(fl: _Flow, fails: dict, ui: int, bi: int, scopes: frozenset) -> _Effect:
    """_branch: any arm may be chosen; its entry's failure travels as its node."""
    b = fl.prog.units[ui].graph.blocks[bi]
    out = []
    for label, ids in b.arm_nodes:
        if ids:
            ctx = _Ctx(ui, ids[0], (ui, bi, label), None, scopes)
            raises = frozenset({("node", ids[0])}) if _fails(ctx, fails) else frozenset()
            out.append(_Effect(raises=raises, started=(ctx,)))
    return _merge(*out)


def _entry_effect(fl: _Flow, fails: dict, ui: int, nid: str, scopes: frozenset) -> _Effect:
    """_entry_gen: a decision's branch, or the entry node's activation."""
    if nid in fl.prog.decisions:
        dui, bi = fl.prog.decisions[nid]
        return _branch_effect(fl, fails, dui, bi, scopes)
    ctx = _Ctx(ui, nid, None, None, scopes)
    raises = frozenset({("node", nid)}) if _fails(ctx, fails) else frozenset()
    return _Effect(raises=raises, started=(ctx,))


def _activation(fl: _Flow, fails: dict, ctx: _Ctx) -> _Effect:
    """_run over one activation: what arrives at its routes (raises), what a
    fallback absorbed on it, and the activations it starts."""
    prog = fl.prog
    own = _Effect(raises=frozenset({None}) if ctx.node in fl.failing_nodes else frozenset())
    if ctx.alias is not None:
        body = _entry_effect(fl, fails, ctx.alias[0], ctx.alias[1], ctx.scopes)
        return _merge(own, body)
    at = _Place(ctx.node, ctx.arm, ctx.scopes, True)
    parts = [own]
    exp = prog.expansions.get((ctx.ui, ctx.node))
    if exp is not None and ctx.arm is None:
        parts += [_entry_effect(fl, fails, exp, e, ctx.scopes) for e in prog.entries.get(exp, ())]
    items = (prog.arm_bodies.get(ctx.arm, {}).get(ctx.node, ()) if ctx.arm
             else prog.bodies.get((ctx.ui, ctx.node), ()))
    parts.append(_walk(fl, fails, items, at))
    if ctx.arm is None:
        parts += [_branch_effect(fl, fails, ctx.ui, bi, ctx.scopes)
                  for bi in prog.branches.get((ctx.ui, ctx.node), ())]
    return _merge(*parts)


def selected_routes(routes, guard) -> list:
    """The routes (wire, guard) pairs _fire_routes takes for an arriving failure
    guard: those it guards, else the unguarded ones."""
    chosen = [w for w, g in routes if _guards(g, guard)]
    return chosen or [w for w, g in routes if g is None]


def _fired(prog: Program, ctx: _Ctx, e: _Effect) -> list:
    """The routes of ctx's node that its arriving and absorbed guards select."""
    routes = prog.routes.get((ctx.ui, ctx.node), ())
    out = [w for f in e.raises for w in selected_routes(routes, f)]
    out += [w for f in e.absorbed for w, g in routes if _guards(g, f)]
    return list({w.ident: w for w in out}.values())


def _started(prog: Program, ctx: _Ctx, e: _Effect) -> list:
    """The activations ctx starts: its work's, then its fired routes' targets
    (_route lands them outside any arm)."""
    routed = [_land_ctx(prog, w, None, ctx.scopes) for w in _fired(prog, ctx, e)]
    return list(e.started) + [c for c in routed if c is not None]


def failure_analysis(prog: Program, limits: Limits = Limits(), *,
                     route_induced: bool = True) -> FailureFlow:
    """The failure flow of a program (see the section comment): a least fixpoint
    over the activations the default entries start, the routes that fire and the
    activations those routes start. Its failure sources are choice_points(prog,
    limits, route_induced=…): False keeps only what fails on its own, so a route
    never makes its own guard fail. Pure."""
    cids = {p.cid for p in choice_points(prog, limits, route_induced=route_induced)}
    fl = _Flow(prog, limits, frozenset(c[1] for c in cids if c[0] == "node"),
               frozenset(c[1] for c in cids if c[0] == "call"))
    known = {}
    for nid in prog.entries.get(0, ()):
        for ctx in _entry_effect(fl, {}, 0, nid, frozenset()).started:
            known.setdefault(ctx, None)
    fails, effects = _Asked(), {}
    # ctx → the contexts its activation asked about / the step it last ran at /
    # the step its fails last changed at: a round skips an activation none of
    # whose reads changed since it ran (it would give the same effect).
    asked, ran, moved, step = {}, {}, {}, 0
    changed = True
    while changed:
        changed = False
        for ctx in list(known):
            if ctx in ran and all(moved.get(c, -1) < ran[ctx] for c in asked[ctx]):
                continue
            step += 1
            fails.asked = asked[ctx] = set()
            e = _activation(fl, fails, ctx)
            fails.asked, ran[ctx] = None, step
            effects[ctx] = e
            if e.raises != fails.get(ctx, frozenset()):
                fails[ctx] = e.raises
                moved[ctx] = step
                changed = True
            for c in _started(prog, ctx, e):
                if c not in known:
                    known[c] = None
                    changed = True
    arriving, absorbed, live = {}, {}, set()
    for ctx, e in effects.items():
        key = (ctx.ui, ctx.node)
        arriving[key] = arriving.get(key, frozenset()) | e.raises
        absorbed[key] = absorbed.get(key, frozenset()) | e.absorbed
        live |= {w.ident for w in _fired(prog, ctx, e)}
    return FailureFlow(arriving, absorbed, frozenset(live))


def failure_flow(prog: Program, limits: Limits = Limits()) -> dict:
    """{(ui, node): frozenset of the failure guards that can arrive at that
    activation} for every node the default entries activate — None (its own
    outcome), ("call", ident), ("block", index), ("node", id). Empty: it cannot
    fail. A route is live iff selected_routes picks it for some arriving guard, or
    a fallback absorbed a call it guards (failure_analysis(prog).live)."""
    return failure_analysis(prog, limits).arriving


def instances(prog: Program, limits: Limits = Limits(), *, potential: bool = False) -> tuple:
    """(Instance, …): the composition instances at setup, in composition order —
    each root once, then under each parent instance its children entry by entry
    (static ones once, ×N multiplying; dynamic ones Limits.spawn; `\\-?` ones
    none), each child's own subtree right after it; at most Limits.spawns per
    entry. `potential`: a `\\-?` entry's Limits.spawn per parent too, as
    instances that could exist (setup False, with their subtrees). Pure."""
    kids, roots = {}, []
    for idx, (_ui, k, t) in enumerate(prog.tree):
        if t.parent is None:
            roots.append(idx)
        else:
            kids.setdefault(idx - k + t.parent, []).append(idx)   # a unit's entries are consecutive
    made, ordinal, out = Counter(), Counter(), []

    def per_parent(idx: int) -> int:
        ui, _k, t = prog.tree[idx]
        if t.rel == "?":
            return limits.spawn if potential else 0
        if t.spawn or t.rel == "$":
            return limits.spawn
        node = prog.units[ui].graph.nodes.get(t.node)
        times = next((a for nm, a in (node.mods if node else []) if nm == "×"), None)
        return (int(times) if times and times.isdigit() else limits.spawn) if times else 1

    stack = [(idx, None, True) for idx in reversed(roots)]
    while stack:                       # depth first without recursion: deep trees are fine
        idx, parent, setup = stack.pop()
        t = prog.tree[idx][2]
        made[idx] += 1
        ordinal[t.node] += 1
        inst = Instance((t.node, ordinal[t.node]), t.node, ordinal[t.node], parent, t.rel,
                        t.spawn, setup, idx)
        out.append(inst)
        todo = []
        for c in kids.get(idx, []):
            n = min(per_parent(c), limits.spawns - made[c] - sum(1 for x in todo if x[0] == c))
            child_setup = setup and prog.tree[c][2].rel != "?"
            todo += [(c, inst.key, child_setup)] * max(n, 0)
        stack += reversed(todo)
    return tuple(out)


def _select(prog: Program, insts, w, limits: Limits) -> tuple:
    """The instance keys of w.dst (among `insts`, in their order) a flow along
    w selects: every one, or those under its `[A]/` path (in its own unit),
    the first Limits.spawns."""
    ui = prog.wire_unit.get(id(w), 0)
    path = w.paths[1] if w.paths else None
    out, keep = [], {}
    for inst in insts:
        if inst.node != w.dst:
            continue
        tui, k, _t = prog.tree[inst.entry]
        if path and tui == ui:
            if inst.entry not in keep:
                g = prog.units[tui].graph
                occ = kit.render.occurrences(g)
                keep[inst.entry] = occ[k][0] in kit.render.matching_occurrences(g, occ, w.dst,
                                                                                 path)
            if not keep[inst.entry]:
                continue
        out.append(inst.key)
    return tuple(out[:limits.spawns])


def _beneath(parents: dict, keys, anc: tuple) -> list:
    """The keys (instance keys) that descend from instance `anc`; `parents`:
    {key: its parent's key}."""
    out = []
    for key in keys:
        cur, seen = parents.get(key), 0
        while cur is not None and seen <= len(parents):
            if cur == anc:
                out.append(key)
                break
            cur, seen = parents.get(cur), seen + 1
    return out


def _tally(prog: Program, insts) -> list:
    """Instances per composition entry (prog.tree order)."""
    n = Counter(i.entry for i in insts)
    return [n[idx] for idx in range(len(prog.tree))]


def _setup_instances(prog: Program, limits: Limits) -> list:
    """Instance count per composition entry (prog.tree order): the tallies of
    instances() — static children once per parent occurrence (×N multiplies),
    dynamic ones Limits.spawn, `\\-?` ones 0."""
    return _tally(prog, instances(prog, limits))


def _one_of_groups(prog: Program) -> dict:
    """{(ui, parent entry index): [sibling node ids]} of `\\-_` groups."""
    out = {}
    for ui, _k, t in prog.tree:
        if t.rel == "_" and t.parent is not None:
            out.setdefault((ui, t.parent), []).append(t.node)
    return out


def _resolve_entries(prog: Program, names) -> list:
    """[(ui, node id)]: the default entries, or the named ones in the first unit
    (document first) that has them."""
    if names is None:
        return [(0, nid) for nid in prog.entries.get(0, ())]
    out = []
    for nid in names:
        if nid in prog.decisions:
            out.append((prog.decisions[nid][0], nid))
            continue
        ui = next((i for i, u in enumerate(prog.units)
                   if u.graph.role != "state" and nid in u.graph.nodes), None)
        if ui is None:
            raise KeyError(f"no node {nid!r} to enter")
        out.append((ui, nid))
    return out


# ---------------------------------------------------------------------------
# simulate
# ---------------------------------------------------------------------------

def simulate(sc, scenario: Scenario, *, limits: Limits = Limits(), keep: bool = True) -> Trace:
    """Run a scenario over a Scene (any Scene of the document: the run uses the
    canonical one) and return its Trace. keep=False keeps only the final frame (its
    tick + 1 is the run's length; `end` holds the rest). Raises KeyError for an
    unknown entry."""
    return _simulate(_program_of(sc.graph), scenario, limits, keep)


_LAST_PROGRAM: list = [None, None]     # [graph, its Program]: the last one built


def _program_of(graph) -> Program:
    """program(canonical(graph)), built once for a run of calls on one document
    (each scenario of `view.py --sim all`, a scenario list then its runs). A
    Program is never changed once built, so sharing it is safe."""
    if _LAST_PROGRAM[0] is not graph:
        _LAST_PROGRAM[:] = [graph, program(canonical(graph))]
    return _LAST_PROGRAM[1]


def _simulate(prog: Program, scenario: Scenario, limits: Limits, keep: bool = True) -> Trace:
    """simulate over a built Program (a run never changes it). keep=False keeps
    only the last frame (an exploration reads a run's end and outcome)."""
    run = _Run(prog, scenario, limits, keep)
    frames = []
    while True:
        frame = run.tick()
        if frame is None:
            continue
        frames.append(frame)
        if frame.done:
            break
    return Trace(scenario, tuple(frames), run.outcome(), run.end(), prog.scene)


# ---------------------------------------------------------------------------
# Scenarios — the enumerable pathways
# ---------------------------------------------------------------------------

class ChoicePoint(NamedTuple):
    cid: tuple                 # the choice id a Scenario names
    line: int
    order: int                 # wire order within a line
    options: tuple             # default first
    names: tuple               # one name per option (names[0]: the default's)
    labels: tuple              # one label per option


def _part(text: str) -> str:
    """A name part: no spaces, no `+` (the combinator)."""
    return re.sub(r"[\s+]+", "_", text.strip())


def reachable(prog: Program):
    """What the default entries can reach, over bodies, routes, self-call returns,
    arms, expansion and alias descents: (wires, [(ui, node) …], {(ui, block index):
    its Region, or None for a branch}). Every route counts as taken (a may-reach:
    failure_flow says which routes some failure selects). Pure; public for the
    checks (unreachable constructs, loop caps)."""
    seen, wires, regions = {}, {}, {}
    queue = [(0, nid) for nid in prog.entries.get(0, ())]

    def take(ws, ui):
        for w in ws:
            wires[id(w)] = w
            queue.append((prog.wire_unit.get(id(w), ui), w.dst))
            call = w.call
            if call is not None and call.op:
                alias = prog.aliases.get(scene_mod.op_verb(call.op))
                if alias:
                    queue.append(alias)
            for it in prog.returns.get(w.ident, ()):
                take(_flat((it,)), ui)

    def regions_of(items, nid):
        """The regions of nid's body; a block's region is its subject's (a member's
        own part of the block, run as a plain scope, never replaces it)."""
        for it in items:
            if isinstance(it, Region):
                if not it.block.subject or nid in it.block.subject:
                    regions.setdefault((it.ui, it.index), it)
                regions_of(it.items, nid)

    while queue:
        ui, nid = queue.pop(0)
        if (ui, nid) in seen:
            continue
        seen[(ui, nid)] = True
        if nid in prog.decisions:
            dui, bi = prog.decisions[nid]
            regions[(dui, bi)] = None
            _take_branch(prog, dui, bi, take, queue)
            continue
        items = prog.bodies.get((ui, nid), ())
        regions_of(items, nid)
        take(_flat(items), ui)
        take([w for w, _g in prog.routes.get((ui, nid), ())], ui)
        exp = prog.expansions.get((ui, nid))
        if exp is not None:
            queue += [(exp, e) for e in prog.entries.get(exp, ())]
        for bi in prog.branches.get((ui, nid), ()):
            regions[(ui, bi)] = None
            _take_branch(prog, ui, bi, take, queue)
    return list(wires.values()), list(seen), regions


def _take_branch(prog: Program, ui: int, bi: int, take, queue: list) -> None:
    for (aui, abi, _label), body in prog.arm_bodies.items():
        if (aui, abi) == (ui, bi):
            for items in body.values():
                take(_flat(items), ui)
    for (aui, abi, _label), w in prog.arm_wire.items():
        if (aui, abi) == (ui, bi):
            take([w], ui)


def choice_points(prog: Program, limits: Limits = Limits(), *,
                  route_induced: bool = True) -> list:
    """The reachable choice points, ordered by line, then wire order.
    route_induced=False leaves out the points a route alone creates — a call that
    is a point only because a `!>` route guards it, and a node's own outcome
    (which exists only for its unguarded routes) — so what remains fails on its
    own: the checks judge routes against that, not against themselves."""
    wires, nodes, regions = reachable(prog)
    order = prog.order
    name = lambda nid: _part(prog.scene.nodes[nid].node.name) if nid in prog.scene.nodes else nid
    points = []
    work = {id(w) for items in prog.bodies.values() for w in _flat(items)}
    work |= {id(w) for body in prog.arm_bodies.values() for items in body.values()
             for w in _flat(items)}
    called = set()
    guarded = {c for routes in prog.routes.values() for _w, g in routes
               if route_induced and g is not None and g[0] == "calls" for c in g[1]}
    if route_induced:
        guarded |= _block_guarded(prog, limits)
    for w in wires:
        if id(w) not in work:
            continue
        if _gate_of(prog, w) is None and ((w.call is not None and w.call.external)
                                          or resilient(w) or ("call", w.ident) in guarded):
            called.add((prog.wire_unit.get(id(w)), w.src))
            if w.call is not None and w.call.op:
                verb = _part(scene_mod.op_verb(w.call.op))
                base = f"{name(w.src)}.{verb}"
            else:
                base = f"{name(w.src)}{w.kind}{name(w.dst)}"
            fails = "fallback" if mod(w, "fallback") is not None else "fails"
            text = f"{base}:{fails}"
            points.append(ChoicePoint(("call", w.ident), w.line, order[id(w)], ("ok", "fails"),
                                      ("", text), ("", _call_label(w, limits, name))))
        if w.kind == "?>":
            text = f"{name(w.src)}?>{name(w.dst)}"
            points.append(ChoicePoint(("cond", w.ident), w.line, order[id(w)], ("skip", "take"),
                                      ("", text), ("", f"{text}: taken")))
    points += _group_points(prog, wires, name)
    for ui, nid in nodes if route_induced else ():
        routes = [w for w, g in prog.routes.get((ui, nid), ()) if g is None]
        if routes and (ui, nid) not in called:
            text = f"{name(nid)}:fails"
            points.append(ChoicePoint(("node", nid), routes[0].line, order[id(routes[0])],
                                      ("ok", "fails"), ("", text),
                                      ("", f"{name(nid)} fails → "
                                       + ", ".join(name(w.dst) for w in routes))))
    points += _block_points(prog, regions, name)
    points += _oneof_points(prog, wires, name)
    points += _machine_points(prog, nodes, name)
    points = list({p.cid: p for p in points}.values())
    points.sort(key=lambda p: (p.line, p.order))
    return _dedup(points)


def _block_guarded(prog: Program, limits: Limits) -> set:
    """{("call", ident)} of the calls a block's `} !>` route makes choice points
    (catalog §6 B2): a route declares that its block can fail, so when nothing in the block
    fails on its own (no route of the block is live without route-made
    failures), each awaited call in it may — a `parallel @any`'s default winner
    only, nothing under `@none` or in a loop run no time."""
    routes = {}
    for (ui, _n), rs in prog.routes.items():
        for w, g in rs:
            if g is not None and g[0] == "block":
                routes.setdefault((ui, g[1]), []).append(w.ident)
    if not routes:
        return set()
    own = failure_analysis(prog, limits, route_induced=False).live
    blocks = {key for key, idents in routes.items() if not own & set(idents)}
    out = set()
    for items in list(prog.bodies.values()) + [i for body in prog.arm_bodies.values()
                                               for i in body.values()]:
        for r in _regions(items):
            if (r.ui, r.index) in blocks:
                out |= {("call", w.ident) for w in _awaited_calls(prog, r, limits)}
    return out


def _regions(items):
    for it in items:
        if isinstance(it, Region):
            yield it
            yield from _regions(it.items)


def _awaited_calls(prog: Program, r: Region, limits: Limits) -> list:
    """The requests inside region r whose failure leaves it: not `~>` sends,
    untaken `?>`, source-join deposits or flows into a value (data, an event, a
    state: a produced value cannot fail), nor what a `@none` block or a loop run
    no time holds; under `@any` the default winner's only."""
    b = r.block
    mods = {n for n, _a in b.modifiers}
    if (b.kind == "parallel" and "none" in mods) or (b.kind == "loop"
                                                     and loop_count(b, limits) == 0):
        return []
    items = r.items[:1] if b.kind == "parallel" and "any" in mods else r.items
    out = []
    for it in items:
        if isinstance(it, Region):
            out += _awaited_calls(prog, it, limits)
        else:
            out += [w for w in _flat((it,)) if w.kind not in ("~>", "?>")
                    and _gate_of(prog, w) is None and _requests(prog, w)]
    return out


def _requests(prog: Program, w) -> bool:
    """Whether w asks something of its destination (not a value it produces)."""
    sn = prog.scene.nodes.get(w.dst)
    return sn is None or sn.node.kind not in ("data", "event", "state")


def _call_label(w, limits: Limits, name) -> str:
    """A failing call's scenario label: what fails (the op verb, else the callee's
    display name), its attempt count and its fallback."""
    a = attempts(w, limits)
    verb = scene_mod.op_verb(w.call.op) if w.call is not None and w.call.op else name(w.dst)
    fb = mod(w, "fallback")
    tail = f"falls back to {fb}" if fb is not None else "no fallback"
    return f"{verb} fails {a}×, {tail}"


def _group_points(prog: Program, wires: list, name) -> list:
    """Alternatives (`/`) and races (`&?`) among the reachable wires' groups."""
    out, seen = [], set()
    for items in list(prog.bodies.values()) + list(prog.returns.values()):
        for g in _groups(items):
            ws = g.wires
            if g.kind not in ("alt", "race") or g.key in seen or not any(
                    id(w) in {id(x) for x in wires} for w in ws):
                continue
            seen.add(g.key)
            opts = tuple(w.dst for w in ws)
            sep = "&?" if g.kind == "race" else "/"
            names = ("",) + tuple(f"{name(ws[0].src)}{sep}{name(d)}" for d in opts[1:])
            out.append(ChoicePoint((g.kind, g.key), ws[0].line, prog.order[id(ws[0])], opts,
                                   names, ("",) + tuple(f"{n}: wins" for n in names[1:])))
    return out


def _groups(items):
    for it in items:
        if isinstance(it, Group):
            yield it
        elif isinstance(it, Region):
            yield from _groups(it.items)


def _block_points(prog: Program, regions: dict, name) -> list:
    """`parallel @any` winners and branch arms of the reachable blocks."""
    out = []
    for (ui, bi), r in regions.items():
        b = prog.units[ui].graph.blocks[bi]
        if b.kind == "parallel" and r is not None and "any" in {n for n, _a in b.modifiers}:
            heads = tuple(_flat((it,))[0].dst for it in r.items)
            subj = name(b.subject[0]) if b.subject else "parallel"
            names = ("",) + tuple(f"{subj}@any={name(h)}" for h in heads[1:])
            out.append(ChoicePoint(("any", (ui, bi)), b.lines[0], -1, heads, names,
                                   ("",) + tuple(f"{n}: wins" for n in names[1:])))
        if b.kind == "branch":
            labels = tuple(label for label, ids in b.arm_nodes if ids)
            if len(labels) < 2:
                continue
            head = (_part(re.sub(r"[\[\]{}<>()|]", "", b.header)) if b.refs
                    else f"branch@{b.lines[0]}")
            names = ("",) + tuple(f"{head}={_part(lab)}" for lab in labels[1:])
            out.append(ChoicePoint(("branch", (ui, bi)), b.lines[0], -1, labels, names,
                                   ("",) + tuple(f"arm {lab}" for lab in labels[1:])))
    return out


def _oneof_points(prog: Program, wires: list, name) -> list:
    """`\\-_` groups a reachable flow touches."""
    out = []
    for key, members in _one_of_groups(prog).items():
        touch = [w for w in wires if w.dst in members]
        if not touch or len(members) < 2:
            continue
        ui, parent = key
        pname = name(prog.units[ui].graph.tree[parent].node)
        names = ("",) + tuple(f"{pname}={name(m)}" for m in members[1:])
        out.append(ChoicePoint(("oneof", key), touch[0].line, prog.order[id(touch[0])],
                               tuple(members), names,
                               ("",) + tuple(f"{n}: active" for n in names[1:])))
    return out


def _machine_points(prog: Program, nodes: list, name) -> list:
    """Two transitions from one state on one trigger, for reachable events."""
    events = {nid for _ui, nid in nodes}
    driven_by = {(r.trigger.owner, r.trigger.label)
                 for ev in events for r in prog.triggers.get(ev, ())}
    out = []
    for m in prog.machines.values():
        groups = {}
        for src, dst, label, _ident in m.transitions:
            if label:
                groups.setdefault((src, label), []).append(dst)
        for (src, label), dsts in groups.items():
            if len(dsts) < 2 or (m.owner, label) not in driven_by:
                continue
            state = _state_label(prog, src)
            names = ("",) + tuple(f"{name(m.owner)}.{_part(state)}-{_part(label)}->"
                                  f"{_part(_state_label(prog, d))}" for d in dsts[1:])
            out.append(ChoicePoint(("machine", (m.owner, src, label)), 0, -1, tuple(dsts),
                                   names, ("",) + tuple(f"{n}" for n in names[1:])))
    return out


def _state_label(prog: Program, nid: str) -> str:
    n = prog.unit_nodes.get(nid)
    if n is not None:
        return {"start": "+", "end": "$", "any": "_"}.get(n.attrs.get("pseudo"), n.name)
    return nid


def _dedup(points: list) -> list:
    """Unique option names: `@<line>` on every name two choice points share, then
    `.<k>` (1, 2, … in order) on every name still shared (one name twice on a
    line)."""
    flat = [(n, p.line) for p in points for n in p.names[1:]]
    named = _suffix_shared([n for n, _l in flat], lambda k, n: f"{n}@{flat[k][1]}")
    ordinal = Counter()

    def nth(_k, n):
        ordinal[n] += 1
        return f"{n}.{ordinal[n]}"

    named = iter(_suffix_shared(named, nth))
    return [p._replace(names=(p.names[0],) + tuple(next(named) for _n in p.names[1:]))
            for p in points]


def _suffix_shared(names: list, suffix) -> list:
    """names with suffix(index, name) applied to every name that occurs twice."""
    count = Counter(names)
    return [suffix(k, n) if count[n] > 1 else n for k, n in enumerate(names)]


def scenarios(sc, *, limits: Limits = Limits()) -> list:
    """`happy`, then one scenario per non-default option of each reachable choice
    point, in source order; capped at limits.scenarios."""
    prog = _program_of(sc.graph)
    out = [Scenario("happy", (), "every default: the happy path")]
    for p in choice_points(prog, limits):
        for opt, nm, label in zip(p.options[1:], p.names[1:], p.labels[1:]):
            out.append(Scenario(nm, ((p.cid, opt),), label))
    return out[:limits.scenarios]


def scenario(sc, name: str, *, limits: Limits = Limits()) -> Scenario:
    """The scenario of that name; `a+b` combines deviations (later wins on one
    choice point). Raises KeyError listing the names when one is unknown."""
    listed = {s.name: s for s in scenarios(sc, limits=limits._replace(scenarios=10 ** 6))}
    parts = name.split("+")
    missing = [p for p in parts if p not in listed]
    if missing:
        raise KeyError(f"unknown scenario {', '.join(missing)}; known: {', '.join(listed)}")
    if len(parts) == 1:
        return listed[name]
    choices = {}
    for p in parts:
        choices.update(dict(listed[p].choices))
    return Scenario(name, tuple(choices.items()),
                    " + ".join(listed[p].label for p in parts if listed[p].label))


# ---------------------------------------------------------------------------
# Exploration — bounded combinations of deviations (catalog §1 MG10)
# ---------------------------------------------------------------------------

class Deviation(NamedTuple):
    """One non-default option of one choice point: a persistent per-site choice
    ("this call always fails"), applied at every activation that meets it."""
    cid: tuple
    option: object
    name: str
    label: str


class Exploration(NamedTuple):
    """combinations' result. traces: the happy run, then one Trace per kept
    combination — fewest deviations first, then source order; duplicates: the
    combinations whose run repeated an earlier one's (dropped); left_out: the
    combinations the budget left unrun (deeper ones built on them are not
    counted). A combination's Trace keeps only its last frame (its end and
    outcome are what an exploration reads); the happy run keeps them all."""
    traces: tuple
    duplicates: int
    left_out: int


def deviations(prog: Program, limits: Limits = Limits()) -> list:
    """Every Deviation of the reachable choice points, in source order (the
    scenarios() list without `happy` and without its cap)."""
    return [Deviation(p.cid, opt, nm, label) for p in choice_points(prog, limits)
            for opt, nm, label in zip(p.options[1:], p.names[1:], p.labels[1:])]


def combinations(sc, k: int, *, limits: Limits = Limits(), budget: int = 256) -> Exploration:
    """The runs of up to k deviations at once, built from choice ids (never by
    name). Level 1 is every deviation; a combination grows by a deviation its
    own run depends on — one whose choice point the run meets at or after its
    first deviation's tick, in that episode or a later one (it lies on the
    deviated path, or the deviation enabled it: machine state, gates and spawn
    counts outlive an episode). A run whose log and outcome repeat an earlier one's
    is dropped; at most `budget` runs are made (the happy run aside), and what
    the budget cut is counted in left_out. Pure and deterministic."""
    prog = _program_of(sc.graph)
    devs = deviations(prog, limits)
    happy = _simulate(prog, Scenario("happy", (), "every default: the happy path"), limits)
    seen, kept = {_signature(happy)}, [happy]
    level = [(i,) for i in range(len(devs))] if k >= 1 else []
    runs = duplicates = 0
    for depth in range(1, k + 1):
        grown = []
        for n, combo in enumerate(level):
            if runs >= budget:
                return Exploration(tuple(kept), duplicates, len(level) - n)
            runs += 1
            trace = _simulate(prog, _combined(devs, combo), limits, keep=False)
            sig = _signature(trace)
            if sig in seen:
                duplicates += 1
                continue
            seen.add(sig)
            kept.append(trace)
            if depth < k:
                grown += _grown(devs, combo, trace)
        level = list(dict.fromkeys(grown))
    return Exploration(tuple(kept), duplicates, 0)


def _combined(devs: list, combo: tuple) -> Scenario:
    picked = [devs[i] for i in combo]
    return Scenario("+".join(d.name for d in picked),
                    tuple((d.cid, d.option) for d in picked),
                    " + ".join(d.label for d in picked if d.label))


def _signature(trace: Trace) -> tuple:
    return (trace.outcome, tuple(trace.end["log"]))


def _grown(devs: list, combo: tuple, trace: Trace) -> list:
    """combo plus each deviation (of another choice point) its run depends on, as
    sorted index tuples."""
    cids = {devs[i].cid for i in combo}
    met = _met_after_deviation(trace.end["events"], cids)
    return [tuple(sorted(combo + (j,))) for j, d in enumerate(devs)
            if d.cid not in cids and d.cid in met]


def _met_after_deviation(events: list, cids: set) -> set:
    """The choice ids a run consulted at or after the first consultation that
    took one of `cids`' deviations — in that episode or any later one, since what
    a deviation changes (machine state, gates, spawn counts) outlives its
    episode. Ticks run on across episodes, so the tick alone orders them."""
    choices = [e for e in events if e["kind"] == "choice"]
    first = next((e for e in choices if e["cid"] in cids and not e["default"]), None)
    if first is None:
        return set()
    return {e["cid"] for e in choices if e["t"] >= first["t"]}


# ---------------------------------------------------------------------------
# The run graph — the structure that exists only when the design runs: an
# instance per composition instance, a level per recursion depth (sync
# recursion unrolled into a chain, ending in a base stub), every hop between
# them. Read from a trace's events (unroll) or from the design up to the
# limits (unroll_static); pure, no drawing. The run view (view_flow.compose_run)
# draws it with the flow view's layout.
# ---------------------------------------------------------------------------

RUN_SHOW = 3                   # instances per (node, parent) and levels per chain before folding
RUN_NODES = 400                # past this many run nodes, everything folds at show 1


class RunNode(NamedTuple):
    key: str                   # `Bullet_service·2`, `Builder_service↻2`, `…┤` (base), folds
    node: str                  # the design node id (a base stub: its caller's)
    inst: Optional[int]        # the instance ordinal, when the label shows it (`·k`)
    level: int                 # the recursion level (1: bare; `↻k` k ≥ 2)
    role: str = "node"         # "node" | "base" | "fold"
    born: Optional[int] = None     # the frame it appears in (None: the no-run view)
    potential: bool = False    # the no-run view: could exist, not at setup (◌)
    spawned: Optional[int] = None  # a run: the frame its instance comes to exist
    more: int = 0              # a fold of instances: how many it stands for
    span: tuple = ()           # a fold of levels: (lowest, highest)


class RunEdge(NamedTuple):
    key: tuple                 # (src key, dst key, kind)
    src: str
    dst: str
    kind: str                  # the arrow as written; "own" | "base" for those roles
    role: str                  # "flow" | "own" | "base"
    wire: Optional[tuple]      # the design wire's ident (own: None)
    mark: str = ""             # own: the composition relation (scene.rel_mark)
    hops: tuple = ()           # ((start frame, end frame, outcome), …)
    born: Optional[int] = None


class RunGraph(NamedTuple):
    nodes: dict                # key → RunNode, in drawing order
    edges: dict                # key → RunEdge
    folds: dict                # {"show", "instances", "levels"}: what folding left out
    limits: Limits
    trace: Optional[Trace]     # None: the no-run view
    timeline: object = None    # what run_frame reads (acts, hops, arrivals)


class RunFrame(NamedTuple):
    nodes: dict                # key → (status, count, pending): the nodes drawn by now
    edges: dict                # key → hops arrived: the edges drawn by now
    tokens: tuple              # ((edge key, at, dir, state), …)


def _run_key(nid: str, inst: Optional[tuple], level: int) -> str:
    return nid + (f"·{inst[1]}" if inst is not None else "") + (f"↻{level}" if level > 1 else "")


class _Unrolled:
    """A run graph being built: run nodes and edges as dicts, then folded."""

    def __init__(self, prog: Program, insts, limits: Limits):
        self.prog, self.limits = prog, limits
        self.insts = {i.key: i for i in insts}
        self.parents = {i.key: i.parent for i in insts}
        self.nodes: dict = {}          # key → dict
        self.edges: dict = {}          # key → dict
        self.order = {nid: k for k, nid in enumerate(prog.scene.nodes)}

    def node(self, nid: str, inst: Optional[tuple], level: int, born=None, **kw) -> str:
        key = _run_key(nid, inst, level)
        n = self.nodes.get(key)
        if n is None:
            n = self.nodes[key] = dict(node=nid, inst=inst, level=level, role="node",
                                       born=born, potential=False, spawned=None)
        elif born is not None and (n["born"] is None or born < n["born"]):
            n["born"] = born
        n.update(kw)
        return key

    def base(self, src: str, born=None) -> str:
        key = src + "┤"
        if key not in self.nodes:
            s = self.nodes[src]
            self.nodes[key] = dict(node=s["node"], inst=s["inst"], level=s["level"],
                                   role="base", born=born, potential=False, spawned=None)
        elif born is not None:
            self.nodes[key]["born"] = min(self.nodes[key]["born"], born)
        return key

    def edge(self, src: str, dst: str, kind: str, role: str, wire=None, mark: str = "",
             hop=None, born=None) -> tuple:
        key = (src, dst, "own:" + mark if role == "own" else kind)
        e = self.edges.get(key)
        if e is None:
            e = self.edges[key] = dict(src=src, dst=dst, kind=kind, role=role, wire=wire,
                                       mark=mark, hops=[], born=born)
        elif born is not None and (e["born"] is None or born < e["born"]):
            e["born"] = born
        if hop is not None:
            e["hops"].append(hop)
        return key

    def keys_of(self, nid: str, born=None) -> list:
        """[(key, instance key)]: nid's level-1 run nodes — one per instance, or
        the bare node."""
        mine = [i.key for i in self.insts.values() if i.node == nid]
        if not mine:
            return [(self.node(nid, None, 1, born), None)]
        return [(_run_key(nid, k, 1), k) for k in mine]

    def pairs(self, srcs: list, dsts: list) -> list:
        """[(src key, dst key)]: each source lane to the destinations under its
        instance, else to every destination; a node into itself lane by lane."""
        out = []
        for s, si in srcs:
            if si is None:
                out += [(s, d) for d, _di in dsts]
                continue
            same = [d for d, di in dsts if di == si]
            under = _beneath(self.parents, [di for _d, di in dsts if di is not None], si)
            mine = same or [d for d, di in dsts if di in under]
            out += [(s, d) for d in (mine or [d for d, _di in dsts])]
        return list(dict.fromkeys(out))

    def own_edges(self, born_of=None) -> None:
        """An own edge from each parent instance to each child instance (born
        with the child)."""
        for i in self.insts.values():
            if i.parent is None or i.parent not in self.insts:
                continue
            t = self.prog.tree[i.entry][2]
            child = _run_key(i.node, i.key, 1)
            if child not in self.nodes:
                continue
            self.edge(_run_key(self.insts[i.parent].node, i.parent, 1), child, "own", "own",
                      mark=scene_mod.rel_mark(t), born=self.nodes[child]["born"])

    def shows_inst(self) -> set:
        """The design nodes whose instances are labelled `·k`: a dynamic,
        optional or ×N entry, or two instances or more."""
        n = Counter(i.node for i in self.insts.values())
        out = {nid for nid, k in n.items() if k > 1}
        for ui, _k, t in self.prog.tree:
            node = self.prog.units[ui].graph.nodes.get(t.node)
            if t.spawn or t.rel in ("$", "?") or any(m == "×" for m, _a in
                                                      (node.mods if node else [])):
                out.add(t.node)
        return out

    def done(self, show: int, trace, timeline, troubled=frozenset()) -> RunGraph:
        """The run graph, folded (show), its nodes in drawing order."""
        if show is not None:
            remap, folds = _fold(self, show, troubled)
            if len({remap.get(k, k) for k in self.nodes}) > RUN_NODES and show > 1:
                remap, folds = _fold(self, 1, troubled)
        else:
            remap, folds = {}, {"show": None, "instances": 0, "levels": 0}
        labelled = self.shows_inst()
        nodes = {}
        for key in sorted(self.nodes, key=self._rank):
            n = self.nodes[key]
            fold = remap.get(key, key)
            if fold in nodes:
                f = nodes[fold]
                nodes[fold] = f._replace(born=_least(f.born, n["born"]),
                                         potential=f.potential and n["potential"],
                                         spawned=_least(f.spawned, n["spawned"]))
                continue
            kind = folds["nodes"].get(fold) if fold != key else None
            nodes[fold] = RunNode(
                fold, n["node"], n["inst"][1] if n["inst"] and n["node"] in labelled
                and not kind else None, n["level"], "fold" if kind else n["role"], n["born"],
                n["potential"], n["spawned"], kind[0] if kind else 0, kind[1] if kind else ())
        edges = {}
        for key, e in self.edges.items():
            src, dst = remap.get(e["src"], e["src"]), remap.get(e["dst"], e["dst"])
            if src == dst and e["src"] != e["dst"]:
                continue                        # inside one fold
            k = (src, dst, key[2])
            hops = tuple(e["hops"])
            if k in edges:
                old = edges[k]
                edges[k] = old._replace(hops=tuple(sorted(old.hops + hops)),
                                        born=_least(old.born, e["born"]))
            else:
                edges[k] = RunEdge(k, src, dst, e["kind"], e["role"], e["wire"], e["mark"],
                                   hops, e["born"])
        tl = timeline.remapped(remap) if timeline is not None else None
        return RunGraph(nodes, edges, {k: v for k, v in folds.items() if k != "nodes"},
                        self.limits, trace, tl)

    def _rank(self, key: str) -> tuple:
        n = self.nodes[key]
        inst = n["inst"][1] if n["inst"] else 0
        return (self.order.get(n["node"], len(self.order)), inst, n["level"],
                n["role"] == "base")


def _least(a, b):
    return b if a is None else a if b is None else min(a, b)


def _fold(u: _Unrolled, show: int, troubled) -> tuple:
    """({run key: its fold's key}, folds): in each (node, parent instance) group
    of more than `show` instances, all but the first show − 1 and every one
    that failed or was cancelled fold into one `[…×k more]`, their subtrees
    with them; a recursion chain deeper than show + 1 keeps its first show − 1
    levels and its deepest, the rest one `[… ↻a‥↻b]`. folds["nodes"]: {fold
    key: (instances, (lowest, highest) level)}."""
    keep_n = max(show - 1, 1)
    remap, made = {}, {}
    groups = {}
    for key, n in u.nodes.items():
        if n["role"] == "node" and n["inst"] is not None and n["level"] == 1:
            groups.setdefault((n["node"], u.parents.get(n["inst"])), []).append(key)
    folded = {}                                 # instance key → its fold's key
    for (nid, _parent), keys in groups.items():
        if len(keys) <= show:
            continue
        keys.sort(key=lambda k: u.nodes[k]["inst"][1])
        rest = [k for k in keys[keep_n:] if k not in troubled]
        if len(rest) < 2:
            continue
        lo, hi = u.nodes[rest[0]]["inst"][1], u.nodes[rest[-1]]["inst"][1]
        fold = f"{nid}·{lo}‥{hi}"
        made[fold] = (len(rest), ())
        for k in rest:
            folded[u.nodes[k]["inst"]] = fold
    insts_out = len(folded)
    under = {}                                  # (node, fold) → [instance keys]
    for key, n in u.nodes.items():
        inst = n["inst"]
        if inst is None:
            continue
        if inst in folded:
            remap[key] = folded[inst]
            continue
        top = next((folded[a] for a in _ancestors(u.parents, inst) if a in folded), None)
        if top is not None:
            fold = f"{n['node']}…{top}"
            remap[key] = fold
            under.setdefault(fold, set()).add(inst)
    for fold, insts in under.items():
        made[fold] = (len(insts), ())
        insts_out += len(insts)
    levels_out = 0
    chains = {}
    for key, n in u.nodes.items():
        if n["role"] == "node" and key not in remap:
            chains.setdefault((n["node"], n["inst"]), {})[n["level"]] = key
    for (nid, inst), lv in chains.items():
        deep = max(lv)
        if deep <= show + 1:
            continue
        lo, hi = keep_n + 1, deep - 1
        fold = _run_key(nid, inst, 1) + f"↻{lo}‥{hi}"
        made[fold] = (0, (lo, hi))
        for level, key in lv.items():
            if lo <= level <= hi:
                remap[key] = fold
                levels_out += 1
    return remap, {"show": show, "instances": insts_out, "levels": levels_out, "nodes": made}


def _ancestors(parents: dict, key):
    seen = 0
    cur = parents.get(key)
    while cur is not None and seen <= len(parents):
        yield cur
        cur, seen = parents.get(cur), seen + 1


def unroll_static(sc, limits: Limits = Limits(), *, show: Optional[int] = RUN_SHOW) -> RunGraph:
    """What could exist when the design of Scene `sc` runs, up to `limits`: every
    instance at setup and Limits.spawn per parent of each `\\\\-?` entry (potential,
    ◌), an own edge from each parent instance to each child, every flow, trigger
    and arm wire between the instances it reaches (lane by lane), and each
    recursive self-call unrolled to Limits.depth levels and its base stub. No
    hops. `show`: the folding (None: none)."""
    prog = _program_of(sc.graph)
    insts = instances(prog, limits, potential=True)
    u = _Unrolled(prog, insts, limits)
    for i in insts:
        u.node(i.node, i.key, 1, potential=not i.setup)
    u.own_edges()
    for w in prog.scene.wires:
        if w.role not in ("flow", "trigger", "arm"):
            continue
        srcs = u.keys_of(w.src)
        if w.src == w.dst:
            if w.call is not None and w.call.recursive:
                for key, inst in srcs:
                    prev = key
                    for level in range(2, limits.depth + 1):
                        nxt = u.node(w.src, inst, level)
                        u.edge(prev, nxt, w.kind, "flow", w.ident)
                        prev = nxt
                    u.edge(prev, u.base(prev), "base", "base", w.ident)
            continue
        if w.dst in prog.tree_nodes:
            dsts = [(_run_key(w.dst, k, 1), k) for k in _select(prog, insts, w, limits)]
        else:
            dsts = u.keys_of(w.dst)
        for s, d in u.pairs(srcs, dsts):
            u.edge(s, d, w.kind, "flow", w.ident)
    return u.done(show, None, None)


class _Timeline(NamedTuple):
    """What run_frame reads of a run: acts {act: (run keys, task, enter, leave,
    how)}; waits {task: [(from, to)]} (awaiting members); hops [(task, wire,
    start, end, edge keys)] with by_wire {(task, wire): [(start, hop index)]};
    arrivals {run key: [frame]} (hops ending at a node no act enters) and
    spawned {run key: frame}; ticks: each frame's tick."""
    acts: dict
    waits: dict
    hops: list
    by_wire: dict
    arrivals: dict
    ticks: tuple

    def remapped(self, remap: dict) -> "_Timeline":
        r = lambda keys: tuple(dict.fromkeys(remap.get(k, k) for k in keys))
        re = lambda keys: tuple(dict.fromkeys((remap.get(a, a), remap.get(b, b), c)
                                              for a, b, c in keys))
        acts = {a: (r(v[0]),) + v[1:] for a, v in self.acts.items()}
        hops = [h[:4] + (re(h[4]),) for h in self.hops]
        arrivals = {}
        for k, frames in self.arrivals.items():
            arrivals.setdefault(remap.get(k, k), []).extend(frames)
        return self._replace(acts=acts, hops=hops, arrivals=arrivals)


def unroll(trace: Trace, *, limits: Limits = Limits(), show: Optional[int] = RUN_SHOW) -> RunGraph:
    """The run graph of a trace on the canonical scene (simulate's): a run node
    per (design node, instance, recursion level) its activations entered, the
    setup instances and the spawned ones, an edge per hop's way between them
    (lane by lane: a hop standing for several instances fans out, and work done
    for several converges on a single target), own edges, and a base stub where
    the simulator stopped a recursion. Each node and edge is born at the frame
    it first exists in (run_frame draws what exists by a frame). `limits`: the
    run's (its setup instances). `show`: the folding (None: none). Pure."""
    prog = _program_of(trace.scene.graph)
    frames = trace.frames
    ix = {f.tick: i for i, f in enumerate(frames)}
    last = len(frames) - 1
    at = lambda t: ix.get(t, min(last, max(0, t)))
    events = trace.end.get("events", ())
    setup = instances(prog, limits)
    spawned = []
    for ev in events:
        if ev["kind"] == "spawn":
            entry = next(k for k, (_u, _kk, t) in enumerate(prog.tree)
                         if t.node == ev["node"] and (t.spawn or t.rel in ("$", "?")))
            t = prog.tree[entry][2]
            spawned.append((Instance(ev["inst"], ev["node"], ev["inst"][1], ev["parent"], t.rel,
                                     t.spawn, True, entry), at(ev["t"])))
    u = _Unrolled(prog, list(setup) + [i for i, _f in spawned], limits)
    for i in setup:
        u.node(i.node, i.key, 1, born=0)
    for i, f in spawned:
        u.node(i.node, i.key, 1, spawned=f)
    acts, waits, troubled = {}, {}, set()
    hops, by_wire, arrivals = [], {}, {}
    open_hop = {}                               # task → the hop whose landing is pending
    wires = {w.ident: w for w in prog.scene.wires}
    forward = {}                                # (act, wire) → the edge keys of its last hop out

    def act_keys(a):
        return acts[a][0] if a in acts else None

    def lane_keys(nid, insts, level, born):
        if insts:
            return [(u.node(nid, k, level, born), k) for k in insts]
        return [(u.node(nid, None, level, born), None)]

    def src_of(h):
        a = h["act"]
        if a in acts:
            return [(k, u.nodes[k]["inst"]) for k in acts[a][0]]
        w = wires.get(h["wire"])
        return [(u.node(w.src if w else "?", None, 1, h["start"]), None)]

    def settle(h, dsts):
        """Edges for hop h into dsts [(key, inst)] (None: each source's base stub)."""
        w = wires.get(h["wire"])
        if dsts is None:
            keys = [u.edge(s, u.base(s, h["start"]), "base", "base", h["wire"], born=h["start"])
                    for s, _i in src_of(h)]
        else:
            keys = [u.edge(s, d, w.kind if w else "->", "flow", h["wire"], born=h["start"])
                    for s, d in u.pairs(src_of(h), dsts)]
        h["edges"] = keys
        forward[(h["act"], h["wire"])] = keys

    def unresolved(h):
        w = wires.get(h["wire"])
        if w is None:
            h["edges"] = []
            return
        if w.src == w.dst:
            srcs = src_of(h)
            settle(h, srcs)
            return
        dsts = lane_keys(w.dst, h["lanes"] or (), 1, h["start"])
        settle(h, dsts)
        for k in h["edges"]:
            arrivals.setdefault(k[1], []).append(h)

    for ev in events:
        kind, task = ev["kind"], ev["task"]
        if kind == "hop":
            prev = open_hop.pop(task, None)
            if prev is not None:
                unresolved(prev)
            h = dict(task=task, act=ev["act"], wire=ev["wire"], start=at(ev["t"]),
                     lanes=ev["lanes"], back=ev["back"], edges=[])
            hops.append(h)
            if ev["back"]:
                h["edges"] = list(forward.get((ev["act"], ev["wire"]), ()))
            else:
                open_hop[task] = h
        elif kind == "enter":
            f = at(ev["t"])
            keys = lane_keys(ev["node"], ev["insts"], ev["level"], f)
            acts[ev["act"]] = ([k for k, _i in keys], task, f, None, None)
            h = open_hop.get(task)
            if h is not None and h["wire"] == ev["wire"] and h["act"] == ev["caller"]:
                open_hop.pop(task)
                settle(h, keys)
        elif kind == "leave":
            a = acts.get(ev["act"])
            if a is not None:
                acts[ev["act"]] = a[:3] + (at(ev["t"]), ev["how"])
                if ev["how"] != "ok":
                    troubled.update(a[0])
        elif kind == "limit" and ev.get("name") == "depth" and ev.get("act") in acts:
            f = at(ev["t"])
            h = open_hop.get(task)
            if h is not None and h["wire"] == ev.get("wire") and h["act"] == ev["act"]:
                open_hop.pop(task)              # a hop that landed on the base case
                settle(h, None)
            else:                               # a self-call refused before its hop
                for src in acts[ev["act"]][0]:
                    u.edge(src, u.base(src, f), "base", "base", ev.get("wire"),
                           hop=(f, f, ""), born=f)
        elif kind == "await":
            waits.setdefault(task, []).append([at(ev["t"]), None])
        elif kind == "resume" and waits.get(task):
            waits[task][-1][1] = at(ev["t"])
    for h in open_hop.values():
        unresolved(h)
    ends = _hop_ends(frames, hops)
    for h, (end, outcome) in zip(hops, ends):
        if h["back"]:
            continue
        for k in h["edges"]:
            u.edges[k]["hops"].append((h["start"], end, outcome))
            u.nodes[k[1]]["born"] = _least(u.nodes[k[1]]["born"], h["start"])
    for k, hs in list(arrivals.items()):
        arrivals[k] = sorted(ends[hops.index(h)][0] for h in hs)
    u.own_edges()
    for key, n in u.nodes.items():              # never reached, never set up: not drawn
        if n["born"] is None and n["spawned"] is not None:
            n["born"] = n["spawned"]
    tl = _Timeline(acts, {t: [tuple(x) for x in v] for t, v in waits.items()},
                   [(h["task"], h["wire"], h["start"], ends[k][0], tuple(h["edges"]))
                    for k, h in enumerate(hops)], {}, arrivals,
                   tuple(f.tick for f in frames))
    for k, h in enumerate(hops):
        tl.by_wire.setdefault((h["task"], h["wire"]), []).append((h["start"], k))
    return u.done(show, trace, tl, frozenset(troubled))


def _hop_ends(frames, hops: list) -> list:
    """[(end frame, outcome)] per hop: the last frame its token is on the wire
    and how it ended there ("failed": an attempt failing on arrival;
    "cancelled"; "" arrived), from the frames' tokens."""
    by = {}
    for k, h in enumerate(hops):
        by.setdefault((h["task"], h["wire"]), []).append((h["start"], k))
    out = [[h["start"], "", None] for h in hops]
    for i, f in enumerate(frames):
        for tok in f.tokens:
            starts = by.get((tok.task, tok.wire))
            if not starts:
                continue
            k = next((k for s, k in reversed(starts) if s <= i), None)
            if k is None:
                continue
            o = out[k]
            o[0] = max(o[0], i)
            if o[2] is None:
                o[2] = tok.state
            if tok.state == "cancelled":
                o[1] = "cancelled"
            elif tok.state == "failed" and o[2] == "moving" and tok.dir == "out":
                o[1] = "failed"
    return [(o[0], o[1]) for o in out]


_STATUS_RANK = {"active": 5, "waiting": 4, "failed": 3, "visited": 2, "cancelled": 1}


def run_frame(rg: RunGraph, i: int) -> RunFrame:
    """What of a run graph exists at frame i of its run, and how: each node
    born by then — its status (active | waiting | visited | failed | cancelled
    | None: not reached yet), its count (activations entered, hops arrived, a
    base stub's times) and pending (a spawned instance whose spawn hop is still
    in flight: ◌) — each edge born by then with its hops arrived, and the
    frame's tokens on the run edges (one per lane). The no-run view (rg.trace
    None): every node and edge, no status, no tokens."""
    if rg.trace is None:
        return RunFrame({k: (None, 0, n.potential) for k, n in rg.nodes.items()},
                        {k: 0 for k in rg.edges}, ())
    tl = rg.timeline
    status, count = {}, Counter()
    open_by_task = {}
    for a, (keys, task, enter, leave, how) in tl.acts.items():
        if enter > i:
            continue
        for k in keys:
            count[k] += 1
        if leave is None or leave > i:
            open_by_task.setdefault(task, []).append((a, keys))
        else:
            st = {"failed": "failed", "cancelled": "cancelled"}.get(how, "visited")
            for k in keys:
                if _STATUS_RANK[st] > _STATUS_RANK.get(status.get(k), 0):
                    status[k] = st
    for task, opened in open_by_task.items():
        top = max(a for a, _k in opened)
        waiting = any(s <= i and (e is None or e > i) for s, e in tl.waits.get(task, ()))
        for a, keys in opened:
            st = "active" if a == top and not waiting else "waiting"
            for k in keys:
                if _STATUS_RANK[st] > _STATUS_RANK.get(status.get(k), 0):
                    status[k] = st
    for k, ends in tl.arrivals.items():
        n = sum(1 for e in ends if e <= i)
        if n and k not in status:
            status[k] = "visited"
        if n and not count[k]:
            count[k] = n
    nodes = {}
    for k, n in rg.nodes.items():
        if n.born is None or n.born > i:
            continue
        pending = n.spawned is not None and n.spawned > i
        if n.role == "base":
            c = sum(1 for e in rg.edges.values() if e.dst == k
                    for s, _e, _o in e.hops if s <= i)
            nodes[k] = ("visited", c, False)
        else:
            nodes[k] = (status.get(k), count.get(k, 0), pending)
    edges = {k: sum(1 for _s, end, _o in e.hops if end <= i)
             for k, e in rg.edges.items() if e.born is not None and e.born <= i}
    tokens = []
    for tok in rg.trace.frames[i].tokens:
        starts = tl.by_wire.get((tok.task, tok.wire))
        h = next((k for s, k in reversed(starts or ()) if s <= i), None)
        if h is None:
            continue
        for key in tl.hops[h][4]:
            if key in edges:
                tokens.append((key, tok.at, tok.dir, tok.state))
    return RunFrame(nodes, edges, tuple(tokens))


def run_counts(rg: RunGraph) -> dict:
    """What the run view's footer says of a run graph: {"nodes", "spawned",
    "deepest", "instances", "levels", "show"}."""
    deepest = max((n.level for n in rg.nodes.values() if n.role == "node"), default=1)
    deepest = max([deepest] + [n.span[1] for n in rg.nodes.values() if n.span])
    spawned = sum(1 for n in rg.nodes.values() if n.spawned is not None)
    return {"nodes": sum(1 for n in rg.nodes.values() if n.role != "base"),
            "spawned": spawned, "deepest": deepest, **rg.folds}


# ---------------------------------------------------------------------------
# project — one trace, any view options
# ---------------------------------------------------------------------------

def _edge_sigs(sc) -> dict:
    """{id(edge): (key, line, n)}: a flow edge's identity across parses of one
    document — n counts the edges of one key on one line, in wire order."""
    out, seen = {}, Counter()
    flows = [w for w in sc.wires if w.role == "flow"]
    flows += [leg for w in sc.wires if w.role == "emit" for leg in w.legs if leg.role == "flow"]
    for w in flows:
        if w.edge is not None and id(w.edge) not in out:
            base = (w.key, w.line)
            out[id(w.edge)] = base + (seen[base],)
            seen[base] += 1
    return out


def _leg_key(w, sigs: dict):
    return sigs.get(id(w.edge)) if w.edge is not None else (w.src, w.label, w.machine)


def _view_index(view) -> tuple:
    """How a view's wires are found from canonical ones: (by edge signature, by
    trigger, in-legs, out-legs, the view's idents)."""
    sigs = _edge_sigs(view)
    by_edge, by_trig, in_legs, out_legs = {}, {}, {}, {}
    for w in view.wires:
        if w.role == "flow" and w.edge is not None:
            by_edge.setdefault(sigs[id(w.edge)], []).append(w.ident)
        elif w.role == "trigger":
            by_trig.setdefault((w.src, w.label, w.machine), []).append(w.ident)
        elif w.role == "emit":
            a, b = w.legs
            in_legs.setdefault(_leg_key(a, sigs), []).append(w.ident)
            out_legs.setdefault(_leg_key(b, sigs), []).append(w.ident)
    return by_edge, by_trig, in_legs, out_legs, {w.ident for w in view.wires}


def ident_map(canon, view) -> dict:
    """{canonical ident: ((view ident, offset, scale), …)}: a token at `at` on the
    canonical wire sits at offset + scale·at on each view wire."""
    by_edge, by_trig, in_legs, out_legs, idents = _view_index(view)
    sigs = _edge_sigs(canon)
    out = {}
    for w in canon.wires:
        hits = []
        if w.role == "flow" and w.edge is not None:
            sig = sigs[id(w.edge)]
            hits += [(v, 0.0, 1.0) for v in by_edge.get(sig, [])]
            hits += [(v, 0.0, 0.5) for v in in_legs.get(sig, [])]
            hits += [(v, 0.5, 0.5) for v in out_legs.get(sig, [])]
        elif w.role == "trigger":
            hits += [(v, 0.0, 1.0) for v in by_trig.get((w.src, w.label, w.machine), [])]
            hits += [(v, 0.5, 0.5) for v in out_legs.get((w.src, w.label, w.machine), [])]
        elif w.ident in idents:
            hits.append((w.ident, 0.0, 1.0))
        out[w.ident] = tuple(dict.fromkeys(hits))
    return out


def host_map(canon, view) -> dict:
    """{node id: the drawn node standing for it}: itself when the view draws it,
    else the owner of the nearest drawn unit around it; collapsed events none."""
    drawn = {nid for u in view.units for nid in u.graph.nodes} - set(view.collapsed)
    out = {}
    for nid, sn in canon.nodes.items():
        host, seen = nid, set()
        while host is not None and host not in drawn and host not in seen:
            seen.add(host)
            host = canon.nodes[host].unit if host in canon.nodes else None
        if nid in view.collapsed:
            host = None
        out[nid] = host
    return out


def _project_frame(f: Frame, idmap: dict, hosts: dict) -> Frame:
    tokens = tuple(f_tok._replace(wire=v, at=round(off + scale * f_tok.at, 4))
                   for f_tok in f.tokens for v, off, scale in idmap.get(f_tok.wire, ()))
    remap = lambda s: frozenset(v for i in s for v, _o, _s in idmap.get(i, ()))
    nodes = {}
    for nid, st in f.nodes.items():
        h = hosts.get(nid, nid)
        if h is None:
            continue
        if h not in nodes or _BUSY.get(st, 0) > _BUSY.get(nodes[h], 0):
            nodes[h] = st
    depth = {n: k for n, k in f.depth.items() if hosts.get(n) == n}
    return f._replace(tokens=tokens, lit=remap(f.lit), held=remap(f.held),
                      taken=remap(f.taken), failed=remap(f.failed), nodes=nodes, depth=depth)


def project(trace: Trace, view) -> Trace:
    """The same run named as `view` (a Scene of the same document) draws it:
    wires by its idents (land mode: an emit wire's halves), nodes it does not
    draw folded into the drawn owner (busiest status wins). Pure."""
    idmap = ident_map(trace.scene, view)
    hosts = host_map(trace.scene, view)
    frames = tuple(_project_frame(f, idmap, hosts) for f in trace.frames)
    return trace._replace(frames=frames, scene=view)


# ---------------------------------------------------------------------------
# Narration — a run in plain words, one Beat per frame where something happens
# (the views' narration line and recent-events log, the playground, --sim's
# text and JSON). Pure: read from the frames and the structured events, never
# from the log's text.
# ---------------------------------------------------------------------------

class Beat(NamedTuple):
    frame: int                 # index into Trace.frames
    tick: int
    text: str                  # the frame's sentences, joined with "; "


class Hop(NamedTuple):
    frame: int
    src: str                   # node ids, as the trace's scene names them
    kind: str                  # the arrow as written (`->`, `~>`, `!>`, `trigger`, …)
    dst: str
    end: Optional[int] = None  # the last frame its token is on the wire (None: `frame`)
    outcome: str = ""          # how it ended there: "" arrived, "failed", "cancelled"


_PSEUDO_STATE = {"start": "+", "end": "$", "any": "_"}


class _Words:
    """Names as a reader reads them, over the Scene a trace names (a node's label,
    a machine state as a transition writes it)."""

    def __init__(self, scn):
        self.scn = scn
        self.wires = {w.ident: w for w in scn.wires}

    def name(self, nid) -> str:
        sn = self.scn.nodes.get(nid)
        return kit.node_label(sn.node) if sn is not None else str(nid)

    def state(self, nid) -> str:
        sn = self.scn.nodes.get(nid)
        if sn is None:
            return str(nid)
        return _PSEUDO_STATE.get(sn.node.attrs.get("pseudo"), sn.node.name)

    def kind(self, nid) -> str:
        sn = self.scn.nodes.get(nid)
        return sn.node.kind if sn is not None else ""


def _listed(names: list) -> str:
    """`A`, `A and B`, `A, B and C`."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _attempt(tok) -> str:
    k = tok.attempt
    return f" — attempt {k[0]} of {k[1]}" if k and k[1] > 1 else ""


def _self_call_text(wd: _Words, w, tok, frame) -> str:
    src, what = wd.name(w.src), tok.carries or (w.call.op if w.call is not None else "")
    call = w.call
    if call is not None and call.external:
        return f"{src} calls the host: {what}"
    if call is not None and not call.recursive and w.edge is not None and w.edge.target_op:
        return f"{src} runs {what} itself"
    depth = frame.depth.get(w.src, 1) + 1
    return f"{src} calls itself" + (f" with {what}" if what else "") + f" — depth {depth}"


def _departures(wd: _Words, tokens: list, frame) -> list:
    """The sentences of the tokens setting out in a frame: one per wire, a fan-out
    (several wires of one kind out of one source, one payload) as one."""
    groups: dict = {}
    for tok in tokens:
        w = wd.wires[tok.wire]
        groups.setdefault((w.src, w.kind, tok.carries, tok.attempt), []).append((w, tok))
    out = []
    for (src, kind, what, _a), members in groups.items():
        w, tok = members[0]
        dsts = _listed(list(dict.fromkeys(wd.name(m.dst) for m, _t in members)))
        who = wd.name(src)
        with_ = f" with {what}" if what else ""
        if w.role == "trigger":
            owners = _listed(list(dict.fromkeys(wd.name(m.machine or m.dst)
                                                for m, _t in members)))
            out.append(f"{who} drives {owners}")
        elif w.src == w.dst or (w.call is not None and w.call.self_call):
            out.append(_self_call_text(wd, w, tok, frame))
        elif kind == "~>":
            if all(wd.kind(m.dst) == "event" for m, _t in members):
                out.append(f"{who} emits {dsts}")
            else:
                out.append(f"{who} sends {what + ' ' if what else ''}to {dsts} without waiting")
        elif kind == "*>":
            out.append(f"{who} fans out to {dsts}")
        elif kind == "=>":
            out.append(f"{who} produces {dsts}" if all(wd.kind(m.dst) == "data"
                                                      for m, _t in members)
                       else f"{who} produces {what + ' ' if what else ''}into {dsts}")
        elif kind == "?>":
            out.append(f"{who} takes the optional path to {dsts}")
        elif kind in ("->", "→") and all(wd.kind(m.dst) == "data" for m, _t in members):
            out.append(f"{who} produces {dsts}")
        elif kind in ("->", "→", "<->"):
            out.append(f"{who} calls {dsts}{with_}{_attempt(tok)}")
        else:
            out.append(f"{who} {kind} {dsts}{with_}")
    return out


def _token_sentences(wd: _Words, frame) -> list:
    """What a frame's tokens say: hops setting out (a `!>` route is said by its
    route event, a branch arm by its choice), replies and fallbacks setting
    back, attempts failing on arrival, calls cancelled."""
    leaving, out = [], []
    for tok in frame.tokens:
        w = wd.wires.get(tok.wire)
        if w is None or w.kind == "!>" or w.role == "arm":
            continue
        if tok.state == "cancelled":
            out.append(f"the call to {wd.name(w.dst)} is cancelled")
        elif tok.dir == "out" and tok.at == 0.0 and tok.state == "moving":
            leaving.append(tok)
        elif tok.dir == "out" and tok.at == 1.0 and tok.state == "failed":
            if w.src == w.dst or (w.call is not None and w.call.self_call):
                out.append(f"{wd.name(w.src)}'s {tok.carries or 'call'} fails{_attempt(tok)}")
            else:
                out.append(f"{tok.carries or 'the call'} to {wd.name(w.dst)} fails"
                           f"{_attempt(tok)}")
        elif tok.dir == "back" and tok.at == 1.0 and tok.state == "fallback":
            out.append(f"{wd.name(w.src)} falls back to {tok.carries}")
        elif tok.dir == "back" and tok.at == 1.0:
            out.append(f"{wd.name(w.dst)} returns {tok.carries} to {wd.name(w.src)}"
                       if tok.carries else f"{wd.name(w.dst)} replies to {wd.name(w.src)}")
    return _departures(wd, leaving, frame) + out


def _fail_text(wd: _Words, ev: dict) -> str:
    what, at = ev["origin"]
    if what == "node":
        return f"{wd.name(at)} fails"
    w = wd.wires.get(at)
    if w is None:
        return f"{wd.name(ev['node'])}'s call fails"
    tries = ev.get("tries", 1)
    after = (f" after {tries} attempts" if tries > 1
             else " — its callee failed" if ev.get("callee") else "")
    if w.src == w.dst or (w.call is not None and w.call.self_call):
        text = f"{wd.name(w.src)}'s {carried(w) or 'call'} fails{after}"
    else:
        text = f"{wd.name(w.src)}'s call to {wd.name(w.dst)} fails{after}"
    return text + (" (a critical call)" if ev.get("critical") else "")


_LIMIT_TEXT = {"depth": "{n} stops at the base case",
               "visits": "{n} reached its visit limit: it does not run again",
               "spawns": "{n} reached the spawn cap",
               "iterations": "the loop is capped"}
_STOP_TEXT = {"entry": "episode {ep} fails",
              "unawaited": "{n}'s failure stops there: nothing waits for it",
              "route-failed": "the route to {n} fails too",
              "abort": "a critical call failed: the run ends"}


def _event_sentence(wd: _Words, ev: dict, scn) -> Optional[str]:
    kind = ev["kind"]
    n = wd.name(ev.get("node"))
    if kind == "fail":
        return _fail_text(wd, ev)
    if kind == "route":
        w = wd.wires.get(ev["wire"])
        return f"{n} routes the failure to {wd.name(w.dst) if w else '?'}"
    if kind == "transition":
        return (f"{wd.name(ev['owner'])} moves {wd.state(ev['src'])} → "
                f"{wd.state(ev['dst'])} on {ev['label']}")
    if kind == "ignored":
        return (f"{wd.name(ev['owner'])} ignores {ev['label']} in "
                f"{wd.state(ev['state'])}: no transition leaves it")
    if kind == "stop" and ev["how"] in _STOP_TEXT:
        return _STOP_TEXT[ev["how"]].format(n=n, ep=ev["episode"])
    if kind == "limit":
        text = _LIMIT_TEXT.get(ev["name"])
        return text.format(n=n) if text else f"the run is cut: the {ev['name']} limit"
    if kind == "gate-arrive":
        return f"{n} reaches the join into {wd.name(ev['key'][2])}"
    if kind == "gate-fire":
        return f"the join is complete: {n} runs"
    if kind == "gate-drop":
        return f"{n} arrives after the winner at {wd.name(ev['key'][2])}: dropped"
    if kind == "choice" and ev["cid"][0] == "branch":
        ui, bi = ev["cid"][1]
        header = scn.units[ui].graph.blocks[bi].header if ui < len(scn.units) else None
        return f"branch{' ' + header if header else ''} takes ‹{ev['option']}›"
    return None


def _changes(wd: _Words, prev, f) -> list:
    """What changed from the previous frame that no event says: a loop's
    iteration, a store held or let go by an `owns` block, another instance, a
    node cancelled (a race lost, a waiter's other members)."""
    out = []
    for nid, st in f.nodes.items():
        if st == "cancelled" and (prev is None or prev.nodes.get(nid) != st):
            out.append(f"{wd.name(nid)} is cancelled")
    for key, k in f.loops.items():
        if prev is None or prev.loops.get(key) != k:
            where = f" in {wd.name(key[0])}" if key[0] is not None else ""
            out.append(f"loop{where}: iteration {k}")
    if prev is not None:
        for nid in sorted(f.held_resources - prev.held_resources, key=str):
            out.append(f"{wd.name(nid)} is held")
        for nid in sorted(prev.held_resources - f.held_resources, key=str):
            out.append(f"{wd.name(nid)} is released")
        for nid, k in f.instances.items():
            if k > prev.instances.get(nid, k):
                out.append(f"{wd.name(nid)} gets another instance ({k} now)")
    return out


def narrate(trace: Trace) -> tuple:
    """(Beat, …): the run in plain words, a Beat for every frame where something
    happens — an episode beginning, a hop setting out (`[API] calls [Payments]
    with charge(total) — attempt 2 of 4`), a reply or fallback, an attempt
    failing, a call giving up, a route, a transition, a join, a bound, the end.
    Over the scene the trace names (the canonical one, or project()'s). Pure."""
    scn = trace.scene
    wd = _Words(scn)
    by_tick: dict = {}
    for ev in trace.end.get("events", ()):
        by_tick.setdefault(ev["t"], []).append(ev)
    beats, prev, episode = [], None, 0
    for i, f in enumerate(trace.frames):
        said = []
        events = by_tick.get(f.tick, ())
        if f.episode != episode and f.entry is not None:
            episode = f.episode
            said.append(f"episode {f.episode} begins at {wd.name(f.entry)}")
        said += _changes(wd, prev, f)
        said += [s for s in (_event_sentence(wd, ev, scn) for ev in events) if s]
        said += _token_sentences(wd, f)
        if f.done:
            said.append(f"the run ends: {trace.outcome}")
            stalled = trace.end.get("stalled") or []
            if stalled:
                said.append("left waiting: " + _listed([wd.name(n) for n in stalled]))
        said = list(dict.fromkeys(said))
        if said:
            beats.append(Beat(i, f.tick, "; ".join(said)))
        prev = f
    return tuple(beats)


def hops(trace: Trace) -> tuple:
    """(Hop, …): every hop the run sets out on, in order (the frame it leaves in,
    the wire's ends and arrow, the last frame its token is on the wire and how it
    ended there: an attempt failing on arrival "failed", a call cancelled on the
    way or on arrival — a race's loser — "cancelled") — the path a view writes out. A reply going back is no hop;
    a `!>` route is (it travels as a failure, but it is no failed hop)."""
    wires = {w.ident: w for w in trace.scene.wires}
    out, live = [], {}             # live: (task, wire) → [index in out, its token]
    for i, f in enumerate(trace.frames):
        seen = {}
        for tok in f.tokens:
            w = wires.get(tok.wire)
            if w is None or tok.dir != "out":
                continue
            key = (tok.task, tok.wire)
            on = live.get(key)
            if tok.at == 0.0 and tok.state != "cancelled":
                out.append([i, w.src, w.kind, w.dst, i, "", tok.state])
                seen[key] = len(out) - 1
            elif on is not None:
                h = out[on]
                h[4] = i
                if tok.state == "cancelled":
                    h[5] = "cancelled"
                elif tok.state == "failed" and h[6] == "moving":
                    h[5] = "failed"
                seen[key] = on
        for key, on in live.items():   # gone: a race's loser is cancelled on arrival
            h = out[on]
            if (key not in seen and not h[5] and f.nodes.get(h[3]) == "cancelled"
                    and trace.frames[i - 1].nodes.get(h[3]) != "cancelled"):
                h[4], h[5] = i, "cancelled"
        live = seen
    return tuple(Hop(*h[:6]) for h in out)
