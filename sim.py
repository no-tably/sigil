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
  runs them: on `~>` forked unawaited.
  A failure stops the activation it reaches, fires its routes (those guarded
  by the failed block or call first, else its unguarded ones), ends it failed and
  unwinds the sync stack.

  Resilience: a failing call makes attempts() tries, then `@fallback(x)` returns
  x and the caller goes on as ok; `!` critical ends the run. A self-call is a
  one-tick pulse; recursion stops at Limits.depth (the base case). An external
  op's far node is opaque. Blocks: `loop` repeats its region (`@times N`, capped
  by Limits.iterations), `parallel` forks it (@all waits, @any races, @none
  doesn't wait), `branch` runs the chosen arm only; a block repeats or forks only
  on its outermost entry on a task. State machines start in `+` (or the source of
  their first written transition); an event delivers its triggers, then runs its
  body. An expansion is a closer reading of the same node: its entries run first,
  then the node's body minus its summary wires. An alias runs when called by name.
  Composition children are instances: static ones once per parent (×N
  multiplies), dynamic ones Limits.spawn per parent, a `=>` into one spawns
  another. Declarations (`@read`, `@inv`, `@sla`, notes, …) do not affect a run.

SCENARIOS

scenarios(scene) lists `happy` (every default) and then one scenario per
non-default option of each reachable choice point (call outcomes, node
outcomes, `?>`, `/`, `&?`, `parallel @any`, branch arms, `\\-_` siblings,
ambiguous machine transitions), ordered by source line. scenario(scene,
"a+b") combines deviations. Scenario(name, choices, label, entries): choices a
tuple of (choice id, option).

THE TRACE

Trace(scenario, frames, outcome, end, scene)
  outcome   "ok" | "failed" | "cut"
  end       {"machines", "routes", "stalled", "cut", "visited", "log"}
  scene     the Scene its frames name (the canonical one, or project()'s)

Frame — a full, immutable snapshot (a view draws frame i alone)
  tick, episode, entry, tokens (Token, task order), lit, held, taken, failed,
  nodes {id: active|waiting|visited|failed|cancelled|opaque}, depth,
  machines {owner: state node id}, changed, instances, loops, blocks,
  held_resources, log (lines added this frame, each led by `t` and the tick, zero-padded), done

Token(wire, at, dir, task, state, carries, reach, attempt)
  dir "out" | "back"; state "moving" | "failed" | "cancelled" | "fallback"
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
    recursion limit (each activation nests a few generator frames)."""
    hop: int = 4               # ticks per hop
    iterations: int = 2        # loop repetitions
    depth: int = 3             # recursion depth / re-entry on one task's stack
    spawn: int = 2             # instances per dynamic child per parent; symbolic ×N
    spawns: int = 8            # instances per node in total
    visits: int = 3            # task-root activations of one node per episode (async cycles)
    activations: int = 500     # activations per trace
    stack: int = 64            # activations on one task's stack (nested sync work)
    frames: int = 2000         # frames per trace
    scenarios: int = 64        # scenarios listed


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
    order: dict                # id(wire) → position in Scene.wires


def canonical(graph):
    """The scene every run uses: every unit, events as nodes, triggers to states."""
    return scene_mod.build_scene(graph, events="nodes", triggers=True, access=False,
                                 depth=kit.ALL_DEPTH)


def program(sc) -> Program:
    """The static program of a canonical Scene (see Program's fields)."""
    units = sc.units
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
                   tree=[(i, k, t) for i, u in enumerate(units)
                         for k, t in enumerate(getattr(u.graph, "tree", None) or [])],
                   order={id(w): k for k, w in enumerate(sc.wires)})
    for i, u in enumerate(units):
        if u.graph.role == "state":
            continue
        mine = [w for w in flows if wire_unit[id(w)] == i]
        _fill_unit(prog, i, u, mine)
    for i, u in enumerate(units):
        if u.graph.role != "state":
            prog.entries[i] = _unit_entries(prog, i, [w for w in flows if wire_unit[id(w)] == i])
    prog.triggers = _trigger_refs(sc, prog.machines)
    return prog


def _fill_unit(prog: Program, ui: int, u, wires: list) -> None:
    """Bodies, arm bodies, routes, returns and branch headers of one unit."""
    blocks = getattr(u.graph, "blocks", None) or []
    arm_of = _arm_membership(blocks, wires)
    work = [w for w in wires if w.kind != "!>" and w.returns_of is None and id(w) not in arm_of]
    joins = getattr(u.graph, "joins", None) or []
    for src in dict.fromkeys(w.src for w in work):
        prog.bodies[(ui, src)] = _items(ui, [w for w in work if w.src == src], blocks, joins, None)
    returns = {}
    for w in wires:
        if w.kind == "!>":
            prog.routes[(ui, w.src)] = (prog.routes.get((ui, w.src), ())
                                        + ((w, _route_guard(w, blocks, wires)),))
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
            if b.refs:
                prog.branches[(ui, b.refs[0])] = prog.branches.get((ui, b.refs[0]), ()) + (bi,)
            else:
                prog.decisions[scene_mod.decision_id(u.owner, bi)] = (ui, bi)


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


def _route_guard(w, blocks: list, wires: list) -> Optional[tuple]:
    """("block", index) for a `!>` continuing a block's `}` (Block.after); ("calls",
    frozenset of ("call", ident)) for one continuing a flow line (Edge.cont): the
    subject's work wires written on that line; else None (the node's own route)."""
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


def _pseudo(units: list, nid: str) -> Optional[str]:
    for u in units:
        n = u.graph.nodes.get(nid)
        if n is not None:
            return n.attrs.get("pseudo")
    return None


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
    """The argument of a wire's first modifier `name`, or None; "" for a bare one."""
    for n, arg in (w.mods or []):
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


@dataclass
class _Act:
    node: str
    ui: int
    cause: Optional[tuple]


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


_BUSY = {"active": 5, "waiting": 4, "failed": 3, "visited": 2, "opaque": 1, "cancelled": 0}


class _Run:
    """One simulation: tasks, activations, machines, instances; tick() makes Frames."""

    def __init__(self, prog: Program, sc: Scenario, limits: Limits):
        self.prog, self.limits = prog, limits
        self.choices = dict(sc.choices)
        self.entries = list(_resolve_entries(prog, sc.entries))
        self.t, self.episode, self.entry = 0, 0, None
        self.tasks: list = []
        self.status: dict = {}
        self.taken, self.failed_w, self.routes = set(), set(), []
        self.machines = {o: m.initial for o, m in prog.machines.items()}
        self.changed, self.lit_now, self.ghosts = set(), set(), []
        self.counts = _setup_instances(prog, limits)
        self.loops, self.blocks, self.held = {}, Counter(), Counter()
        self.visits, self.activations = Counter(), 0
        self.gates: dict = {}
        self.one_of = _one_of_groups(prog)
        self.lines, self.log_all = [], []
        self.failed_episode = self.aborted = False
        self.cut: list = []
        self.start_next = bool(self.entries)
        self.done = False

    # ---- scheduler -------------------------------------------------------

    def tick(self) -> Frame:
        t = self.t
        if t == 0:
            self._log(CONVENTIONS)
            self._log_setup()
        if self.start_next:
            self._begin_episode()
        k = 0
        while k < len(self.tasks) and not self.done:
            task = self.tasks[k]
            k += 1
            if not task.ended and task.resume == t:
                self._advance(task)
        self._wake()
        pending = any(not x.ended and x.resume is not None for x in self.tasks)
        if not self.done and not pending:
            if self.entries:
                self.start_next = True
            else:
                self.done = True
        if not self.done and t + 1 >= self.limits.frames:
            self._cut("frames")
        if self.done:
            self._log(f"done: {self.outcome()}")
        frame = self._snapshot()
        self.t += 1
        self.changed, self.lit_now, self.ghosts, self.lines = set(), set(), [], []
        return frame

    def _begin_episode(self) -> None:
        self.start_next = False
        ui, nid = self.entries.pop(0)
        self.episode += 1
        self.entry = nid
        self.visits = Counter()
        self._log(f"episode {self.episode}: {self._name(nid)}")
        self._fork(lambda task: self._entry_gen(task, ui, nid), entry=True)

    def _fork(self, factory, parent: Optional[_Task] = None, entry: bool = False) -> _Task:
        """A new task running factory(task); it starts inside the control blocks its
        parent runs at the fork (a region it re-enters there is a plain scope)."""
        task = _Task(len(self.tasks) + 1, resume=self.t, entry=entry)
        if parent is not None:
            task.scopes = Counter(+parent.scopes)
        task.gen = factory(task)
        self.tasks.append(task)
        return task

    def _advance(self, task: _Task) -> None:
        try:
            req = next(task.gen)
        except StopIteration:
            self._end(task, failed=False)
        except _Fail:
            self._end(task, failed=True)
            if task.entry:
                self.failed_episode = True
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

    def _wake(self) -> None:
        for task in self.tasks:
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
        task.gen.close()
        task.ended, task.resume, task.wait = True, None, None

    def _abort(self) -> None:
        self._log("critical call failed: the run ends")
        self.aborted = True
        for task in self.tasks:
            self._cancel(task)
        self.done = True

    # ---- frames ----------------------------------------------------------

    def _token(self, task: _Task, fl: _Flight, state: Optional[str] = None) -> Token:
        frac = (self.t - fl.start) / fl.dur if fl.dur else 1.0
        at = 1.0 - frac if fl.back else frac
        return Token(fl.wire, round(at, 4), "back" if fl.back else "out", task.id,
                     state or fl.state, fl.carries, fl.reach, fl.attempt)

    def _snapshot(self) -> Frame:
        tokens, in_flight = [], set()
        for task in self.tasks:
            fl = task.flight
            if not task.ended and fl is not None and fl.start <= self.t <= fl.start + fl.dur:
                tokens.append(self._token(task, fl))
                in_flight.add(fl.wire)
        tokens += self.ghosts
        open_ = {w for task in self.tasks if not task.ended for w in task.open}
        depth = {}
        for task in self.tasks:
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
        stalled = [x.stack[-1].node for x in self.tasks
                   if not x.ended and x.wait is not None and x.stack]
        return {"machines": dict(self.machines), "routes": list(self.routes),
                "stalled": list(dict.fromkeys(stalled)), "cut": list(self.cut),
                "visited": list(self.status), "log": list(self.log_all)}

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

    def _choice(self, cid: tuple, default):
        return self.choices.get(cid, default)

    def _ui(self, w) -> int:
        return self.prog.wire_unit.get(id(w), 0)

    def _hop(self, task: _Task, w, *, dur: Optional[int] = None, back: bool = False,
             state: str = "moving", carries=None, reach: int = 1, attempt=None):
        """Move a token along w; returns its flight at the arrival tick."""
        fl = _Flight(w.ident, back, dur or self.limits.hop, state, carries, reach, attempt)
        yield ("hop", fl)
        if not back and state != "failed":
            self.taken.add(w.ident)
        return fl

    def _push(self, task: _Task, ui: int, nid: str, cause) -> _Act:
        self.activations += 1
        if self.activations > self.limits.activations:
            raise _Cut("activations")
        if len(task.stack) >= self.limits.stack:
            raise _Cut("stack")
        if task.stack:
            self.status[task.stack[-1].node] = "waiting"
        act = _Act(nid, ui, cause)
        task.stack.append(act)
        self.status[nid] = "active"
        return act

    def _pop(self, task: _Task, act: _Act, status: str) -> None:
        if task.stack and task.stack[-1] is act:
            task.stack.pop()
        self.status[act.node] = status

    def _resume_caller(self, task: _Task) -> None:
        if task.stack:
            self.status[task.stack[-1].node] = "active"

    def _depth_capped(self, task: _Task, nid: str) -> bool:
        n = sum(1 for a in task.stack if a.node == nid)
        if n >= self.limits.depth:
            self._log(f"base case: {self._name(nid)} at depth {n}")
            return True
        return False

    def _reach_of(self, w) -> int:
        """How many instances a flow into w.dst reaches (1 when it has none)."""
        if not any(t.node == w.dst for _ui, _k, t in self.prog.tree):
            return 1
        ui = self._ui(w)
        path = w.paths[1] if w.paths else None
        total = 0
        for (tui, k, t), n in zip(self.prog.tree, self.counts):
            if t.node != w.dst:
                continue
            if path and tui == ui:
                g = self.prog.units[tui].graph
                occ = kit.render.occurrences(g)
                if occ[k][0] not in kit.render.matching_occurrences(g, occ, w.dst, path):
                    continue
            total += n
        return min(total, self.limits.spawns)

    def _spawn(self, w) -> None:
        """A `=>` into a dynamic or `\\-?` child: one more instance (capped)."""
        for idx, (_ui, _k, t) in enumerate(self.prog.tree):
            if t.node == w.dst and (t.spawn or t.rel in ("$", "?")):
                if sum(n for (_u, _kk, x), n in zip(self.prog.tree, self.counts)
                       if x.node == w.dst) >= self.limits.spawns:
                    self._log("spawn cap reached")
                    return
                self.counts[idx] += 1
                self._log(f"spawn {self._name(w.dst)} ({self.counts[idx]})")
                return

    def _inactive_sibling(self, nid: str) -> bool:
        """A `\\-_` sibling not chosen (the first of its group is the default)."""
        for key, members in self.one_of.items():
            if nid in members:
                return self._choice(("oneof", key), members[0]) != nid
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
            if self._choice(("node", act.node), "ok") == "fails":
                self._log(f"{self._name(act.node)} fails")
                raise _Fail(None)
            if node is not None and node.kind == "event":
                self._deliver(act)
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
        guarded by what failed, else the unguarded ones. A route target's own
        failure ends that route only; the remaining routes still fire."""
        routes = self.prog.routes.get((act.ui, act.node), ())
        chosen = [w for w, g in routes if _guards(g, f.guard)]
        chosen = chosen or [w for w, g in routes if g is None]
        for w in chosen:
            self.failed_w.add(w.ident)
            self.routes.append(w.ident)
            self._log(f"{self._name(act.node)} failed → {self._name(w.dst)}")
            task.open.append(w.ident)
            try:
                yield from self._hop(task, w, state="failed", carries=carried(w))
                yield from self._land(task, w, None)
            except _Fail:
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
            self._fork(lambda t, w=w: self._async(t, w, arm), task)
            return
        if w.kind == "?>" and self._choice(("cond", w.ident), "skip") != "take":
            return
        gate = self._gate_of(w)
        if gate is not None:
            yield from self._gate(task, w, gate, arm)
            return
        yield from self._call(task, w, arm)

    def _async(self, task: _Task, w, arm):
        """A `~>` send in its own task: hop, then the receiver's work."""
        if self._inactive_sibling(w.dst):
            return
        self._log(f"send {self._wire_text(w)}")
        yield from self._hop(task, w, carries=carried(w), reach=self._reach_of(w))
        try:
            yield from self._land(task, w, arm)
        except _Fail:
            self._log(f"{self._name(w.dst)} failed (not awaited)")

    # ---- calls -------------------------------------------------------------

    def _call(self, task: _Task, w, arm):
        """A sync call along w: attempts, the callee's work, the return."""
        if w.src == w.dst or (w.call is not None and w.call.self_call):
            yield from self._self_call(task, w)
            return
        if self._inactive_sibling(w.dst):
            self._log(f"not taken: {self._name(w.dst)} is not the active one")
            return
        if self._choice(("call", w.ident), "ok") == "fails":
            yield from self._failing(task, w, self.limits.hop)
            yield from self._call_failed(task, w)
            return
        a = attempts(w, self.limits) if resilient(w) else 0
        self._log(self._wire_text(w) + (f" attempt 1/{a}" if a > 1 else ""))
        task.open.append(w.ident)
        yield from self._hop(task, w, carries=carried(w), reach=self._reach_of(w),
                             attempt=(1, a) if a > 1 else None)
        try:
            yield from self._land(task, w, arm)
        except _Fail:
            task.open.remove(w.ident)
            yield from self._call_failed(task, w)
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
            self._spawn(w)
        if self._reach_of(w) == 0:
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
                self._log(f"visit limit: {self._name(dst)}")
                yield ("turn",)
                return
        alias = self._alias_of(w)
        if self._depth_capped(task, dst) or (alias and self._depth_capped(task, alias[1])):
            yield ("turn",)
            return
        yield from self._activate(task, self._ui(w), dst, w.ident, arm, alias)

    def _alias_of(self, w) -> Optional[tuple]:
        """(ui, alias node) of the alias w's op verb names, else None."""
        if w.call is None or not w.call.op:
            return None
        return self.prog.aliases.get(scene_mod.op_verb(w.call.op))

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
            self._log(f"attempt {k}/{a} failed")
            yield ("turn",)

    def _call_failed(self, task: _Task, w):
        """A call has finally failed: its fallback comes back, or the failure travels."""
        fb = mod(w, "fallback")
        if fb is not None:
            self._log(f"{self._name(w.src)} falls back to {fb}")
            yield from self._hop(task, w, back=True, state="fallback", carries=fb)
            self._resume_caller(task)
            yield ("turn",)
            return
        self.failed_w.add(w.ident)
        what = carried(w) or self._name(w.dst)
        a = attempts(w, self.limits)
        tries = f" failed after {a} attempt{'s' if a > 1 else ''}" if resilient(w) else ""
        self._log(f"{self._name(w.src)} failed: {what}{tries}")
        if mod(w, "!") is not None:
            raise _Abort()
        raise _Fail(("call", w.ident))

    def _self_call(self, task: _Task, w):
        """A self-call: a one-tick pulse; an alias body or a
        recursion runs as its work; a target op's `=>` wires are its return."""
        call = w.call
        alias = self._alias_of(w)
        glyph = w.edge is None or not w.edge.target_op     # `[D] -> [D]`: the node recurses
        target = alias[1] if alias else (w.src if glyph else None)
        if target is not None and self._depth_capped(task, target):
            return
        if self._choice(("call", w.ident), "ok") == "fails":
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
                yield from self._call_failed(task, w)
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
        kept, winner = self._group_members(g)
        if not kept:
            return
        if kept[0].kind == "~>":
            for w in ([winner] if g.kind == "race" else kept):
                self._fork(lambda t, w=w: self._async(t, w, arm), task)
            return
        if g.kind == "alt":
            yield from self._step(task, winner, arm)
            return
        if g.kind == "race":
            members = [self._fork(lambda t, w=w: (self._call(t, w, arm) if w is winner
                                                  else self._lose(t, w)), task)
                       for w in kept]
            task.members = members
            won = [m for m, w in zip(members, kept) if w is winner]
            yield from self._await(task, members, need=won, failing=won, guard=None)
            return
        members = [self._fork(lambda t, w=w: self._call(t, w, arm), task) for w in kept]
        task.members = members
        yield from self._await(task, members, need=members, failing=members, guard=None)

    def _group_members(self, g: Group) -> tuple:
        """(kept wires, the chosen one): the members whose `?>` the scenario takes
        (an unconditional member always), and among them the alternative / race
        winner the scenario picks — the first kept when it picks none of them."""
        kept = [w for w in g.wires
                if w.kind != "?>" or self._choice(("cond", w.ident), "skip") == "take"]
        if not kept or g.kind == "all":
            return kept, None
        pick = self._choice((g.kind, g.key), kept[0].dst)
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
        `guard`; the others' failures are theirs alone."""
        yield ("wait", lambda: all(m.ended for m in need) or any(m.failed for m in failing))
        failed = any(m.failed for m in failing)
        for m in members:
            if not m.ended:
                self._log(f"cancelled: task {m.id}")
                self._cancel(m)
        task.members = []
        self._resume_caller(task)
        if failed:
            raise _Fail(guard)

    def _gate_of(self, w) -> Optional[tuple]:
        """(unit, join index, kind) of a `&` / `&?` source join w leaves, else None."""
        if w.edge is None or w.edge.src_join is None:
            return None
        ui = self._ui(w)
        joins = getattr(self.prog.units[ui].graph, "joins", None) or []
        j = w.edge.src_join
        if not 0 <= j < len(joins) or joins[j].kind == "/":
            return None
        return (ui, j, joins[j].kind)

    def _gate(self, task: _Task, w, gate: tuple, arm):
        """A source join: members block at the gate; `&` runs the target once when
        the last arrives, `&?` when the first does (later arrivals are dropped)."""
        ui, j, kind = gate
        members = self.prog.units[ui].graph.joins[j].members
        state = self.gates.setdefault((ui, j, w.dst), {"arrived": [], "round": 0, "fired": False})
        self._log(self._wire_text(w))
        task.open.append(w.ident)
        yield from self._hop(task, w, carries=carried(w))
        state["arrived"].append(w.src)
        everyone = all(m in state["arrived"] for m in members)
        if kind == "&?" and state["fired"]:
            self._log(f"race lost: {self._wire_text(w)}")
            if everyone:
                state.update(arrived=[], fired=False)
            task.open.remove(w.ident)
            yield ("turn",)
            return
        if kind == "&" and not everyone:
            my_round = state["round"]
            yield ("wait", lambda: state["round"] > my_round)
            task.open.remove(w.ident)
            self._resume_caller(task)
            return
        state["fired"] = True
        try:
            yield from self._land(task, w, arm)
        finally:
            state["round"] += 1
            if kind == "&" or everyone:
                state.update(arrived=[], fired=False)
        task.open.remove(w.ident)
        self._resume_caller(task)

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
                n = _loop_count(b, self.limits)
                for k in range(1, n + 1):
                    self.loops[key] = k
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
            win = self._choice(("any", (r.ui, r.index)), heads[0].dst)
            k = next((j for j, h in enumerate(heads) if h.dst == win), 0)
            members = [self._fork(lambda t, it=it, h=h, j=j: (
                self._items(t, (it,), arm) if j == k else self._lose(t, h)), task)
                for j, (it, h) in enumerate(zip(r.items, heads))]
            task.members = members
            yield from self._await(task, members, need=[members[k]], failing=[members[k]],
                                   guard=guard)
            return
        members = [self._fork(lambda t, it=it: self._items(t, (it,), arm), task)
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
        label = self._choice(("branch", (ui, bi)), arms[0][0])
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

    def _deliver(self, act: _Act) -> None:
        """An event's triggers: a task per machine with a matching transition."""
        refs = self.prog.triggers.get(act.node, ())
        for owner in dict.fromkeys(r.trigger.owner for r in refs):
            mine = [r for r in refs if r.trigger.owner == owner]
            state = self.machines.get(owner)
            if state is None or _pseudo(self.prog.units, state) == "end":
                continue
            match = [r for r in mine if r.trigger.src == state
                     or _pseudo(self.prog.units, r.trigger.src) == "any"]
            if not match:
                self._log(f"ignored: {mine[0].trigger.label} — {self._name(owner)} in "
                          f"{self._state_name(state)}")
                continue
            pick = match[0]
            if len(match) > 1:
                dst = self._choice(("machine", (owner, state, pick.trigger.label)),
                                   pick.trigger.dst)
                pick = next((r for r in match if r.trigger.dst == dst), pick)
            self._fork(lambda t, r=pick: self._trigger(t, r))

    def _trigger(self, task: _Task, ref: TriggerRef):
        t = ref.trigger
        yield from self._hop(task, ref.wire, carries=t.label)
        state = self.machines.get(t.owner)
        ok = (state is not None and _pseudo(self.prog.units, state) != "end"
              and (t.src == state or _pseudo(self.prog.units, t.src) == "any"))
        if ok:
            self.machines[t.owner] = t.dst
            self.changed.add(t.owner)
            if ref.transition is not None:
                self.lit_now.add(ref.transition)
            self._log(f"{self._name(t.owner)} {self._state_name(state)} -{t.label}-> "
                      f"{self._state_name(t.dst)}")
        else:
            self._log(f"ignored: {t.label} — {self._name(t.owner)} in {self._state_name(state)}")
        yield ("turn",)

    def _state_name(self, nid: Optional[str]) -> str:
        for u in self.prog.units:
            n = u.graph.nodes.get(nid)
            if n is not None:
                return {"start": "+", "end": "$", "any": "_"}.get(n.attrs.get("pseudo"), n.name)
        return str(nid)


def _loop_count(b, limits: Limits) -> int:
    """How often a loop runs: `@times N` capped by the limit, else the limit."""
    times = next((a for n, a in b.modifiers if n == "times"), None)
    if times and times.strip().isdigit():
        return min(int(times), limits.iterations)
    return limits.iterations


def _setup_instances(prog: Program, limits: Limits) -> list:
    """Instance count per composition entry (prog.tree order): static children once per
    parent occurrence (×N multiplies), dynamic ones Limits.spawn, `\\-?` ones 0."""
    counts = []
    for idx, (ui, k, t) in enumerate(prog.tree):
        if t.parent is None:
            counts.append(1)
            continue
        base = counts[idx - k + t.parent]     # a unit's entries are consecutive
        if t.rel == "?":
            n = 0
        elif t.spawn or t.rel == "$":
            n = base * limits.spawn
        else:
            node = prog.units[ui].graph.nodes.get(t.node)
            times = next((a for nm, a in (node.mods if node else []) if nm == "×"), None)
            mult = (int(times) if times and times.isdigit() else limits.spawn) if times else 1
            n = base * mult
        counts.append(min(n, limits.spawns))
    return counts


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

def simulate(sc, scenario: Scenario, *, limits: Limits = Limits()) -> Trace:
    """Run a scenario over a Scene (any Scene of the document: the run uses the
    canonical one) and return its Trace. Raises KeyError for an unknown entry."""
    canon = canonical(sc.graph)
    run = _Run(program(canon), scenario, limits)
    frames = []
    while True:
        frame = run.tick()
        frames.append(frame)
        if frame.done:
            break
    return Trace(scenario, tuple(frames), run.outcome(), run.end(), canon)


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


def _reachable(prog: Program):
    """(wires, (ui, node) pairs, events, (ui, block index) of regions and
    branches) reachable from the default entries — over bodies, routes, self-call
    returns, triggers, arms, expansion and alias descents."""
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


def choice_points(prog: Program, limits: Limits = Limits()) -> list:
    """The reachable choice points, ordered by line, then wire order."""
    wires, nodes, regions = _reachable(prog)
    order = prog.order
    name = lambda nid: _part(prog.scene.nodes[nid].node.name) if nid in prog.scene.nodes else nid
    points = []
    work = {id(w) for items in prog.bodies.values() for w in _flat(items)}
    work |= {id(w) for body in prog.arm_bodies.values() for items in body.values()
             for w in _flat(items)}
    called = set()
    guarded = {c for routes in prog.routes.values() for _w, g in routes
               if g is not None and g[0] == "calls" for c in g[1]}
    for w in wires:
        if id(w) not in work:
            continue
        if (w.call is not None and w.call.external) or resilient(w) \
                or ("call", w.ident) in guarded:
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
    for ui, nid in nodes:
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
    out = []
    for m in prog.machines.values():
        groups = {}
        for src, dst, label, _ident in m.transitions:
            if label:
                groups.setdefault((src, label), []).append(dst)
        for (src, label), dsts in groups.items():
            driven = any(r.trigger.owner == m.owner and r.trigger.label == label
                         for ev in events for r in prog.triggers.get(ev, ()))
            if len(dsts) < 2 or not driven:
                continue
            state = _state_label(prog, src)
            names = ("",) + tuple(f"{name(m.owner)}.{_part(state)}-{_part(label)}->"
                                  f"{_part(_state_label(prog, d))}" for d in dsts[1:])
            out.append(ChoicePoint(("machine", (m.owner, src, label)), 0, -1, tuple(dsts),
                                   names, ("",) + tuple(f"{n}" for n in names[1:])))
    return out


def _state_label(prog: Program, nid: str) -> str:
    for u in prog.units:
        n = u.graph.nodes.get(nid)
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
    prog = program(canonical(sc.graph))
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
