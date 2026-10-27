"""
The program: the simulator's records (Limits, Scenario, Token, Instance, Frame,
Trace) and the Scene compiled once into what each node runs (canonical,
program → Program: units, steps, groups, regions, machines, trigger refs), with
the static facts the run and the failure flow both read (modifiers, durations,
returns, loop counts, routes, gates, instances). Pure; the bottom of
program ← engine ← scenarios / narration. The contract is the package's
docstring (sigil.model.sim).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import NamedTuple, Optional

from sigil.core.graph import ALL_DEPTH, header_only, matching_occurrences, occurrences
from sigil.model import scene as scene_mod


# ---------------------------------------------------------------------------
# Public data
# ---------------------------------------------------------------------------

PER_SIZE = {"frames": 128, "activations": 20}   # a default limit per unit of document size


class Floor(int):
    """A default per-episode limit that grows with the document (`frames`,
    `activations`): a floor that a run raises to PER_SIZE[name] times the
    document's size (scaled), so a large design's runs finish at default limits.
    A given value (limits_from, Limits(frames=N)) is a plain int and is used as
    given. A Floor prints, formats and serialises as its value, but never equals a
    plain int, so Limits() and Limits(frames=2000) stay apart wherever limits are
    compared or kept as a key."""
    __slots__ = ()

    def __eq__(self, other):
        return type(other) is Floor and int(self) == int(other)

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash((Floor, int(self)))


class Limits(NamedTuple):
    """The bounds that make every run end. `depth` is checked at every
    arrival (the base case: nothing runs); `activations`, `stack` and `frames` end
    the run with outcome "cut" — `stack` keeps a long sync chain inside Python's
    recursion limit (each activation nests a few generator frames). `activations`
    and `frames` count per episode, so a design with many entries runs each of them
    in full; a run's length is bounded by its entries times `frames`. The defaults
    of `frames` and `activations` are Floors: a run gets max(2000, 128 × size)
    frames and max(500, 20 × size) activations per episode, size being the nodes
    and edges of every unit (scaled, PER_SIZE); a given one is used as given."""
    hop: int = 4               # ticks per hop
    iterations: int = 2        # loop repetitions
    depth: int = 3             # recursion depth / re-entry on one task's stack
    spawn: int = 2             # instances per dynamic child per parent; symbolic ×N
    spawns: int = 8            # instances per node in total
    visits: int = 3            # task-root activations of one node per episode (async cycles)
    activations: int = Floor(500)  # activations per episode (default: scaled)
    stack: int = 64            # activations on one task's stack (nested sync work)
    frames: int = Floor(2000)  # frames per episode (default: scaled)
    scenarios: int = 64        # scenarios listed
    overlaps: int = 12         # overlap scenarios listed (scenarios())
    pair_overlaps: int = 3     # overlap scenarios listed per pair of entries
    window: int = 64           # start ticks tried per pair of entries (overlap_runs)


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


def doc_size(prog) -> int:
    """A document's size as the scaled limits read it: the nodes and edges of
    every unit of its Program (every level, each counted where written)."""
    return sum(len(u.graph.nodes) + len(u.graph.edges) for u in prog.units)


def scaled(limits: Limits, prog) -> Limits:
    """The limits a run of `prog` gets, every value a plain int: each default
    (a Floor) of PER_SIZE raised to its factor times doc_size(prog), a given one
    as given. Deterministic: a function of the document and the limits only."""
    grown = {name: max(int(getattr(limits, name)), k * doc_size(prog))
             for name, k in PER_SIZE.items() if type(getattr(limits, name)) is Floor}
    return limits._replace(**grown) if grown else limits


def sized(limits: Limits, sc) -> Limits:
    """scaled() for a Scene's document: the limits its runs get, written out —
    what a tool shows as "frames=N" and what `--limit frames=N` reproduces."""
    return scaled(limits, _program_of(sc.graph))


class Scenario(NamedTuple):
    name: str
    choices: tuple = ()        # ((choice id, option), …)
    label: str = ""
    entries: Optional[tuple] = None    # node ids; None: the default entries
    starts: tuple = ()         # ((entry node id, start tick), …): entries that begin
                               # at their tick, overlapping earlier episodes
    machines: tuple = ()       # ((machine owner id, state node id), …): machines that
                               # begin in that state instead of their initial one


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
    episode: int = 1           # its task's episode


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
    episodes: frozenset = frozenset()  # the running episodes (Frame doc)


class Trace(NamedTuple):
    scenario: Scenario
    frames: tuple
    outcome: str
    end: dict
    scene: object = None


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
    block: object              # core.graph.Block
    items: tuple


class Decide(NamedTuple):
    """A branch with no header glyph (a field's: `branch on {X}.f`, or none) written
    between two flows of one source: it decides there, in that body's order
    (_place_decisions). It holds no wires (`items` is empty, so _flat skips it)."""
    ui: int
    index: int                 # into the unit graph's blocks
    items: tuple = ()


class Machine(NamedTuple):
    owner: str
    initial: str
    transitions: tuple         # (src state, dst state, label, transition wire ident)
    states: tuple = ()         # the state node ids its block names (no `+`, `$`, `_`),
                               # in written order
    start: frozenset = frozenset()   # its `+` ids
    any: frozenset = frozenset()     # its `_` ids
    end: frozenset = frozenset()     # its `$` ids


def replayed(m: Machine, begun: Optional[str]) -> frozenset:
    """The replay rule: the events a state start (`Owner=State`, Scenario.machines)
    replays for machine m begun in `begun` — the triggers of the transitions on a
    way from where m begins (`+`, or its first states) to `begun`. The run plays
    the episode that brought the machine there again, so such an event meeting it
    in that state or later is that replay, not a new arrival (the run marks its
    drop `replayed`; SGC203 counts no such drop). None for begun None (m begins
    where it begins anyway). A way out of a state is its own transitions then the
    `_` ones; out of `$` its own then the `+` ones."""
    if begun is None:
        return frozenset()
    trans = [(src, dst, label) for src, dst, label, _w in m.transitions]

    def reach(seeds, step) -> set:
        seen, queue = dict.fromkeys(seeds), list(seeds)
        while queue:
            x = queue.pop(0)
            for y in step(x):
                if y not in seen:
                    seen[y] = None
                    queue.append(y)
        return set(seen)

    def leaving(s):
        after = m.start if s in m.end else m.any
        return [d for src, d, _l in trans if src == s] + [d for src, d, _l in trans if src in after]

    entered = {d for _s, d, _l in trans}
    firsts = ([d for src, d, _l in trans if src in m.start] if m.start
              else [s for s in m.states if s not in entered])
    into = reach([begun], lambda s: [src for src, d, _l in trans if d == s])
    out_of = reach(list(m.start) + (firsts or list(m.states)), leaving)
    return frozenset(label or "" for src, dst, label in trans if dst in into and dst != src
                     and (src in out_of or src in m.any))


class TriggerRef(NamedTuple):
    trigger: object            # core.graph.Trigger
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
    unit_nodes: dict           # node id → core.graph.Node, first seen over units
    order: dict                # id(wire) → position in Scene.wires
    access: object             # scene.access_index of the document
    summaries: dict = None     # summary wire ident → its detail wire idents (_summaries)
    home: dict = None          # node id → the unit its own work is written in (_homes)


def canonical(graph):
    """The scene every run uses: every unit, events as nodes, triggers to states."""
    return scene_mod.build_scene(graph, events="nodes", triggers=True, access=False,
                                 depth=ALL_DEPTH)


def program(sc) -> Program:
    """The static program of a canonical Scene (see Program's fields)."""
    units = sc.units
    tree = [(i, k, t) for i, u in enumerate(units)
            for k, t in enumerate(getattr(u.graph, "tree", None) or [])]
    unit_of_graph = {id(u.graph): i for i, u in enumerate(units)}
    edge_unit = {id(e): i for i, u in enumerate(units) for e in u.graph.edges}
    flows = [w for w in sc.wires if w.role == "flow" and id(w.edge) in edge_unit]
    wire_unit = {id(w): edge_unit[id(w.edge)] for w in flows}
    expansions = _nested(units, {(i, nid): unit_of_graph[id(sub)] for i, u in enumerate(units)
                                 for nid, sub in u.graph.expansions.items()
                                 if sub.role != "state" and id(sub) in unit_of_graph})
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
    prog.summaries = _summaries(prog, flows)
    prog.home = _homes(prog)
    return prog


def _summaries(prog: Program, flows: list) -> dict:
    """{summary ident: (detail ident, …)}. A work wire out of X whose target X's
    expansion (or one nested in it) already reaches is X's summary of that
    detail: an expansion is a closer reading of the same node, so the detail
    carries the traffic and the summary runs no token of its own
    (`[Shop] ~> <OrderPlaced>` over `[Checkout] ~> <OrderPlaced>` inside
    `[Shop] := { … }`). Only a detail every run takes counts: a route (`!>`)
    or an optional `?>` to the same target may not be taken, so X's own wire
    still runs. Routes are not summaries: a failure reaching X still takes X's
    own routes."""
    by_unit = {}
    for w in flows:
        by_unit.setdefault(prog.wire_unit[id(w)], []).append(w)

    def detail(exp, seen):
        if exp in seen:
            return []
        seen.add(exp)
        out = list(by_unit.get(exp, ()))
        for (ui, _nid), sub in prog.expansions.items():
            if ui == exp:
                out += detail(sub, seen)
        return out

    out = {}
    for (ui, nid), exp in prog.expansions.items():
        inner = [x for x in detail(exp, set()) if x.kind not in ("!>", "?>")]
        for w in _flat(prog.bodies.get((ui, nid), ())):
            if w.src == nid and w.dst != nid:
                hits = tuple(x.ident for x in inner if x.dst == w.dst)
                if hits:
                    out[w.ident] = hits
    return out


def _homes(prog: Program) -> dict:
    """{node id: its home unit}: the shallowest unit (lowest level, then document
    order) where it has work of its own — a body, routes, branches or an
    expansion. A glyph is one entity across levels: reached where it has none,
    it runs its home's (_home)."""
    out = {}
    keys = list(prog.bodies) + list(prog.routes) + list(prog.branches) + list(prog.expansions)
    for ui, nid in sorted(set(keys), key=lambda k: (prog.units[k[0]].level, k[0])):
        out.setdefault(nid, ui)
    return out


def _home(prog: Program, ui: int, nid: str) -> int:
    """The unit nid's activation runs in when reached in unit ui: ui when nid has
    work of its own there, else its home unit (sim.md §1.1)."""
    key = (ui, nid)
    if key in prog.bodies or key in prog.routes or key in prog.branches or key in prog.expansions:
        return ui
    return (prog.home or {}).get(nid, ui)


def _summed(prog: Program, idents) -> frozenset:
    """idents plus every summary one of its details is among: a summary is lit,
    taken or failed exactly while its detail is."""
    out = frozenset(idents)
    extra = [k for k, details in (prog.summaries or {}).items()
             if k not in out and not out.isdisjoint(details)]
    return out.union(extra) if extra else out


def _running(prog: Program, items) -> tuple:
    """A body's items as a run takes them: without its summary wires (a group
    goes when every member is one)."""
    sums = prog.summaries or {}
    if not sums:
        return items
    out = []
    for it in items:
        if isinstance(it, Step) and it.wire.ident in sums:
            continue
        if isinstance(it, Group) and all(w.ident in sums for w in it.wires):
            continue
        out.append(it)
    return tuple(out)


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
            elif not _place_decision(prog, ui, bi, blocks, work):
                prog.decisions[scene_mod.decision_id(u.owner, bi)] = (ui, bi)


_FIELD_HEADER = re.compile(r"^\s*\{[^{}]*\}\s*\.\s*\w")


def _field_header(b) -> bool:
    """A branch on a field of a value (`branch on {Request}.kind`): it tests the
    value, nothing activates it, so it decides where it is written, as a branch
    with no header glyph does (catalog §6 B4)."""
    return bool(_FIELD_HEADER.match(b.header or ""))


def _place_decision(prog: Program, ui: int, bi: int, blocks: list, work: list) -> bool:
    """Put a branch with no header glyph into the body of the source it is written
    between two flows of — the work flows on the lines next before and next after
    the branch, in its own block, share that source — as a Decide item where it is
    written; True when placed. A branch in a `parallel` block, or one with no
    such source around it, stays an entry of its unit (a decision), run in line
    order among the unit's entries."""
    b = blocks[bi]
    if any(blocks[c].kind == "parallel" for c in _chain(b.parent, blocks)):
        return False
    lo, hi = b.lines
    mine = [w for w in work if b.parent is None or b.parent in _chain(w.block, blocks)]
    before = [w for w in mine if w.line < lo]
    after = [w for w in mine if w.line > hi]
    if not before or not after:
        return False
    last, first = max(w.line for w in before), min(w.line for w in after)
    following = {w.src for w in after if w.line == first}
    src = next((w.src for w in before if w.line == last and w.src in following), None)
    if src is None or (ui, src) not in prog.bodies:
        return False
    prog.bodies[(ui, src)] = _with_decide(prog.bodies[(ui, src)], Decide(ui, bi), b, blocks)
    return True


def _with_decide(items: tuple, d: Decide, b, blocks: list) -> tuple:
    """items with d before the first item written after branch b (inside the region
    that holds b, when one does)."""
    chain = _chain(b.parent, blocks)
    out = list(items)
    for k, it in enumerate(out):
        if isinstance(it, Region) and it.index in chain:
            out[k] = it._replace(items=_with_decide(it.items, d, b, blocks))
            return tuple(out)
        wires = _flat((it,))
        if wires and wires[0].line > b.lines[1]:
            out.insert(k, d)
            return tuple(out)
    return tuple(out + [d])


def _decides(items) -> list:
    """Every Decide among items, regions' included, in order."""
    out = []
    for it in items:
        if isinstance(it, Decide):
            out.append(it)
        elif isinstance(it, Region):
            out += _decides(it.items)
    return out


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


def _nested(units: list, expansions: dict) -> dict:
    """expansions with each one whose owner its level writes only on the header
    (core.graph.header_only: `[A] := { … }` at the top for an [A] written inside
    `[Core] := { … }`) moved to the units that write its owner: there it is A's
    inside, run when A is reached as if written in that body (the export model
    nests its system the same way). An owner written nowhere else keeps its
    expansion where the header is."""
    out = dict(expansions)
    for (i, nid), exp in expansions.items():
        if not header_only(units[i].graph, nid):
            continue
        hosts = [j for j, u in enumerate(units)
                 if j not in (i, exp) and u.graph.role != "state" and nid in u.graph.nodes
                 and (j, nid) not in expansions and not header_only(u.graph, nid)]
        if hosts:
            del out[(i, nid)]
            out.update({(j, nid): exp for j in hosts})
    return out


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
            states = tuple(nid for nid, n in g.nodes.items() if not n.attrs.get("pseudo"))
            kinds = {k: frozenset(nid for nid, n in g.nodes.items() if n.attrs.get("pseudo") == k)
                     for k in ("start", "any", "end")}
            out[u.owner] = Machine(u.owner, initial, trans, states, **kinds)
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
# Static facts — what the run and the failure flow both read
# ---------------------------------------------------------------------------

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


def selected_routes(routes, guard, via=()) -> list:
    """The routes (wire, guard) pairs _fire_routes takes for an arriving failure
    guard: those it guards — or that guard one of `via`, the guards the failure
    had before it left its blocks (a `!>` on a call line inside a loop or a
    scope) — else the unguarded ones."""
    chosen = [w for w, g in routes if _guards(g, guard) or any(_guards(g, v) for v in via)]
    return chosen or [w for w, g in routes if g is None]


# ---------------------------------------------------------------------------
# Instances — the composition tree at setup
# ---------------------------------------------------------------------------

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
                occ = occurrences(g)
                keep[inst.entry] = occ[k][0] in matching_occurrences(g, occ, w.dst, path)
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


# ---------------------------------------------------------------------------
# The program of a document, built once
# ---------------------------------------------------------------------------

_LAST_PROGRAM: list = [None, None]     # [graph, its Program]: the last one built


def _program_of(graph) -> Program:
    """program(canonical(graph)), built once for a run of calls on one document
    (each scenario of `sigil view --sim all`, a scenario list then its runs). A
    Program is never changed once built, so sharing it is safe."""
    if _LAST_PROGRAM[0] is not graph:
        _LAST_PROGRAM[:] = [graph, program(canonical(graph))]
    return _LAST_PROGRAM[1]
