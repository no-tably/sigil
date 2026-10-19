"""
The structure reading: a design read as units and the reach of its parts, for a
designer refining it (`sigil view FILE --structure [--json]`). Pure functions: a
parsed Graph in, a Structure out; nothing here reads a file or draws. Built on
the export model (sigil.model.systems): its systems are the units, its homes
and depends_on are the units' members and dependencies, so this reading and an
export never disagree. It runs in any mode (no gate) and is deterministic.

    s = structure_of(graph, stem="shop")
    s.units, s.cycles, s.up, s.edge, s.reach, s.pass_throughs, s.large, s.repeated, s.writers
    as_json(s)                         # the same as plain data

UNITS        every system of the model (top, expansions, trees), in the model's
             order: kind, parent, members (the components homed there), its
             internal flows, and depends_on split into `calls` (units its flows
             reach) and `nests` (the units nested in it); calls ∪ nests is the
             model's depends_on. A flow to or from an actor makes no dependency.
CYCLES       each set of units whose flows depend on one another round (a
             strongly connected set of `calls`), with every link inside it and
             the flows that make it.
UP           a unit whose flows reach a unit enclosing it (its parent, …, the
             top): with the nesting that unit's depends_on holds, that too is a
             cycle of the export's depends_on — a part of an enclosing level
             (a store, a component first written there) the unit leans on.
EDGE         the components that call an actor: the parts that touch the
             outside world, with the actors each calls.
REACH        per component: what it can drive (out) and what can drive it (in),
             transitively over calls — sync, async and optional flows (`->` `→`
             `~>` `*>` `?>`, `<->` both ways); never a failure (`!>`) or return
             (`=>`). A call into an expansion's owner drives the expansion's
             entries (its nodes with a call out and none in from inside it, as
             the simulator enters a unit). An actor ends a path: it is listed
             (out: the actors it can reach; in: the actors that can drive it),
             never walked through. Data glyphs carry a path but are not counted.
             Largest first: most reached, then most reaching, then by glyph.
PASS-THROUGHS a component (no data, event, store or actor, no unit's face) with
             exactly one caller and one callee, neither an actor, touching no
             actor: a layer that may isolate nothing.
LARGE        the units with more than LARGE members (a unit past it does not
             scan at a glance), largest first.
REPEATED     a component (no actor) declared as a member of two or more units:
             one name is one entity, so the two merge silently. Declared in a
             unit: a statement of the unit's own level it heads that is no flow
             of its and no tree's root (`[Text]`, `[Api] @sla(…)`; its own
             `[X] := {` header aside),
             or a `\\-` branch's child (in the tree's unit). Naming a part of
             another unit in a flow is a reference, not a declaration.
WRITERS      per store, who writes it, as `sigil check` counts it
             (scene.all_writers over the simulator's canonical scene): a flow
             into it with a write-like reading (`->` / `~>` whose verb is no read
             verb), `@write(P)` on it, `@owns` on the writer; `read_verbs` adds a
             dialect's. Most writers first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from sigil.core.graph import walk_depth
from sigil.model import systems

LARGE = 9                                    # members past which a unit is large
CALL_MODES = frozenset({"sync", "async", "optional"})   # systems.ARROW_MODE values
NOT_COUNTED = frozenset({"data"})            # carried through, never counted in reach
NOT_PASS = frozenset({"data", "event", "store", "actor"})


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FlowRef:
    """One flow as the reading names it: glyphs at both ends, its arrow and line."""
    src: str
    arrow: str
    dst: str
    line: int

    @property
    def text(self) -> str:
        return f"{self.src} {self.arrow} {self.dst}"


@dataclass(frozen=True)
class Unit:
    key: str
    name: str
    kind: str                    # "top" | "expansion" | "tree"
    parent: Optional[str]
    members: tuple               # glyphs of the components homed here, written order
    internal: tuple              # FlowRefs with both ends in the unit
    calls: tuple                 # unit keys its flows depend on, sorted
    nests: tuple                 # unit keys nested in it, sorted
    depends_on: tuple            # the model's: calls ∪ nests, sorted


@dataclass(frozen=True)
class Link:
    """One flow dependency: unit `src` depends on unit `dst` by the flows listed."""
    src: str
    dst: str
    flows: tuple                 # FlowRefs


@dataclass(frozen=True)
class Cycle:
    units: tuple                 # unit keys, in the model's order
    links: tuple                 # Links


@dataclass(frozen=True)
class EdgePart:
    component: str               # glyph
    unit: str
    actors: tuple                # actor glyphs it calls, sorted


@dataclass(frozen=True)
class Reach:
    component: str
    unit: str
    out: tuple                   # glyphs it can drive (no actors, no data), sorted
    out_actors: tuple
    into: tuple                  # glyphs that can drive it
    in_actors: tuple


@dataclass(frozen=True)
class PassThrough:
    component: str
    unit: str
    caller: str
    callee: str


@dataclass(frozen=True)
class Repeated:
    component: str
    units: tuple                 # the units it is written in, written order


@dataclass(frozen=True)
class Writers:
    store: str
    unit: str
    writers: tuple               # (principal glyph or name, (how, …)), sorted


@dataclass(frozen=True)
class Structure:
    stem: str
    top: str
    units: tuple
    cycles: tuple
    up: tuple                    # Links into an enclosing unit
    edge: tuple
    reach: tuple
    pass_throughs: tuple
    large: tuple                 # Units over LARGE members, largest first
    repeated: tuple
    writers: tuple


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def structure_of(graph, stem: str, kinds: Mapping = {},
                 read_verbs: Optional[tuple] = None) -> Structure:
    """The structure reading of a parsed document. `stem`: the top unit's name;
    `kinds`: the dialect's NODE_KINDS (its glyphs' brackets); `read_verbs`: the
    verbs whose flows into a store read it (None: the core's, scene.READ_VERBS)."""
    model = systems.model_of(graph, stem, kinds=kinds)
    comps = model.components
    flows = systems.collect_flows(graph, comps)
    actors = frozenset(nid for nid, c in comps.items() if c.kind == "actor")
    g = {nid: c.glyph for nid, c in comps.items()}
    faces = {s.face: key for key, s in model.systems.items() if s.face is not None}
    links = flow_links(flows, comps, faces, actors)
    children: dict = {}
    for key, sysm in model.systems.items():
        if sysm.parent is not None and sysm.parent != key:
            children.setdefault(sysm.parent, set()).add(key)
    units = tuple(make_unit(s, comps, links, children) for s in model.systems.values())
    calls = call_edges(flows)
    return Structure(
        stem=model.stem, top=model.top, units=units,
        cycles=cycles(units, links, g),
        up=up_links(units, links, g),
        edge=edge_parts(comps, calls, actors),
        reach=reach(comps, calls, expansion_entries(graph, comps), actors),
        pass_throughs=pass_throughs(comps, calls, flows, faces, actors),
        large=tuple(sorted((u for u in units if len(u.members) > LARGE),
                           key=lambda u: (-len(u.members), u.key))),
        repeated=repeated(graph, model, actors),
        writers=store_writers(graph, comps, read_verbs))


# ---------------------------------------------------------------------------
# Units and their dependencies
# ---------------------------------------------------------------------------

def inside(c, faces: dict) -> frozenset:
    """The units a component is in: its home, and the unit it is the face of."""
    return frozenset({c.home} | ({faces[c.id]} if c.id in faces else set()))


def flow_links(flows: list, comps: dict, faces: dict, actors: frozenset) -> dict:
    """{(unit, unit it depends on): [Flow]}: the dependencies flows make, as the
    export model's depends_on reads them (systems.dependencies): a flow from a node
    in A to a node in B (`<->` both ways), a flow into a face standing for its unit
    alone; a flow to or from an actor makes none."""
    ins = {nid: inside(c, faces) for nid, c in comps.items()}
    out: dict = {}
    for f in flows:
        if f.src in actors or f.dst in actors:
            continue
        pairs = [(f.src, f.dst)] + ([(f.dst, f.src)] if f.arrow == "<->" else [])
        for a, b in pairs:
            for sa in ins[a]:
                for sb in ({faces[b]} if b in faces else ins[b]):
                    if sa != sb:
                        out.setdefault((sa, sb), []).append(f)
    return out


def make_unit(s, comps: dict, links: dict, children: dict) -> Unit:
    """A system of the model as a unit: `links` the flow dependencies
    (flow_links), `children` {unit: the units whose parent it is}."""
    return Unit(key=s.key, name=s.name, kind=s.kind, parent=s.parent,
                members=tuple(comps[nid].glyph for nid in s.members),
                internal=tuple(ref(f, comps) for f in s.internal),
                calls=tuple(sorted({b for (a, b) in links if a == s.key})),
                nests=tuple(sorted(children.get(s.key, ()))),
                depends_on=tuple(s.depends_on))


def ref(f, comps: dict) -> FlowRef:
    return FlowRef(comps[f.src].glyph, f.arrow, comps[f.dst].glyph, f.line)


def cycles(units: tuple, links: dict, glyphs: dict) -> tuple:
    """Each strongly connected set of two or more units over their flow
    dependencies (`calls`), with the links inside it."""
    order = [u.key for u in units]
    deps = {u.key: set(u.calls) for u in units}
    out = []
    for comp in strongly_connected(order, deps):
        if len(comp) < 2:
            continue
        members = set(comp)
        found = []
        for a in comp:
            for b in sorted(deps[a] & members, key=order.index):
                found.append(link(a, b, links, glyphs))
        out.append(Cycle(tuple(comp), tuple(found)))
    return tuple(out)


def link(a: str, b: str, links: dict, glyphs: dict) -> Link:
    return Link(a, b, tuple(FlowRef(glyphs[f.src], f.arrow, glyphs[f.dst], f.line)
                            for f in links.get((a, b), ())))


def up_links(units: tuple, links: dict, glyphs: dict) -> tuple:
    """The flow dependencies of a unit on a unit enclosing it, in unit order."""
    parent = {u.key: u.parent for u in units}
    out = []
    for u in units:
        above, k = [], parent[u.key]
        while k is not None and k not in above and k != u.key:
            above.append(k)
            k = parent[k]
        out += [link(u.key, b, links, glyphs) for b in u.calls if b in above]
    return tuple(out)


def strongly_connected(order: list, deps: dict) -> list:
    """The strongly connected sets of `deps` ({key: keys it points to}), each in
    `order`, the sets ordered by their first key (Tarjan's, iterative)."""
    index, low, on, stack, out = {}, {}, set(), [], []
    counter = 0
    for root in order:
        if root in index:
            continue
        work = [(root, iter(sorted(deps.get(root, ()), key=order.index)))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on.add(root)
        while work:
            v, it = work[-1]
            w = next(it, None)
            if w is not None:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(sorted(deps.get(w, ()), key=order.index))))
                elif w in on:
                    low[v] = min(low[v], index[w])
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                out.append(sorted(comp, key=order.index))
    return sorted(out, key=lambda c: order.index(c[0]))


# ---------------------------------------------------------------------------
# Calls: the edge, reach, pass-throughs
# ---------------------------------------------------------------------------

def is_call(f) -> bool:
    return systems.ARROW_MODE.get(f.arrow) in CALL_MODES and f.src != f.dst


def call_edges(flows: list) -> list:
    """(caller id, callee id) of every call (`<->` both ways), document order."""
    out = []
    for f in flows:
        if is_call(f):
            out.append((f.src, f.dst))
            if f.arrow == "<->":
                out.append((f.dst, f.src))
    return out


def edge_parts(comps: dict, calls: list, actors: frozenset) -> tuple:
    found: dict = {}
    for a, b in calls:
        if a not in actors and b in actors:
            found.setdefault(a, set()).add(comps[b].glyph)
    return tuple(EdgePart(comps[nid].glyph, comps[nid].home, tuple(sorted(acts)))
                 for nid, acts in sorted(found.items(), key=lambda kv: comps[kv[0]].glyph))


def expansion_entries(graph, comps: dict) -> dict:
    """{owner id: entry ids}: for each expansion `X := { … }` (no alias body, no
    state machine), the nodes of its body with a call out and none in from
    another node of the body, as the simulator enters a unit (no actor); a body
    whose callers all have callers (a cycle) enters at every caller."""
    out: dict = {}
    for g, _owner, _level in walk_depth(graph):
        for nid, sub in g.expansions.items():
            node = g.nodes.get(nid)
            if sub.role == "state" or node is None or node.kind == "alias" or nid not in comps:
                continue
            edges = [(e.src, e.dst) for e in sub.edges
                     if systems.ARROW_MODE.get(e.kind) in CALL_MODES and e.src != e.dst
                     and e.src in comps and e.dst in comps]
            edges += [(d, s) for e in sub.edges if e.kind == "<->"
                      for s, d in [(e.src, e.dst)] if s != d and s in comps and d in comps]
            callers = [s for s, _d in edges if comps[s].kind != "actor"]
            called = {d for _s, d in edges}
            entries = [s for s in callers if s not in called] or callers
            out.setdefault(nid, [])
            out[nid] += [e for e in dict.fromkeys(entries) if e not in out[nid]]
    return out


def reach(comps: dict, calls: list, entries: dict, actors: frozenset) -> tuple:
    """Reach per component (no actor), the largest first."""
    fwd: dict = {}
    for a, b in calls:
        fwd.setdefault(a, set()).add(b)
    for owner, ids in entries.items():
        fwd.setdefault(owner, set()).update(i for i in ids if i != owner)
    back: dict = {}
    for a, bs in fwd.items():
        for b in bs:
            back.setdefault(b, set()).add(a)
    out = []
    for nid, c in comps.items():
        if nid in actors:
            continue
        down, up = walked(nid, fwd, actors), walked(nid, back, actors)
        out.append(Reach(
            c.glyph, c.home,
            out=counted(down, comps, actors), out_actors=glyphs_of(down & actors, comps),
            into=counted(up, comps, actors), in_actors=glyphs_of(up & actors, comps)))
    return tuple(sorted(out, key=lambda r: (-len(r.out), -len(r.into), r.component)))


def walked(start: str, adj: dict, actors: frozenset) -> set:
    """Every node reachable from start over adj (start aside); an actor is
    reached but never walked through."""
    seen, todo = set(), [start]
    while todo:
        v = todo.pop()
        for w in adj.get(v, ()):
            if w in seen or w == start:
                continue
            seen.add(w)
            if w not in actors:
                todo.append(w)
    return seen


def counted(ids: set, comps: dict, actors: frozenset) -> tuple:
    return glyphs_of({i for i in ids if i not in actors and comps[i].kind not in NOT_COUNTED},
                     comps)


def glyphs_of(ids, comps: dict) -> tuple:
    return tuple(sorted(comps[i].glyph for i in ids))


def pass_throughs(comps: dict, calls: list, flows: list, faces: dict,
                  actors: frozenset) -> tuple:
    callers, callees = {}, {}
    for a, b in calls:
        callees.setdefault(a, set()).add(b)
        callers.setdefault(b, set()).add(a)
    touches = {n for f in flows if f.src in actors or f.dst in actors for n in (f.src, f.dst)}
    out = []
    for nid, c in comps.items():
        if c.kind in NOT_PASS or nid in faces or nid in touches:
            continue
        ins, outs = callers.get(nid, set()), callees.get(nid, set())
        if len(ins) == 1 and len(outs) == 1 and ins != outs:
            (a,), (b,) = ins, outs
            out.append(PassThrough(c.glyph, c.home, comps[a].glyph, comps[b].glyph))
    return tuple(sorted(out, key=lambda p: (p.unit, p.component)))


# ---------------------------------------------------------------------------
# Names and stores
# ---------------------------------------------------------------------------

def repeated(graph, model, actors: frozenset) -> tuple:
    comps = model.components
    found = declared_in(graph, model.stem)
    return tuple(sorted((Repeated(comps[nid].glyph, tuple(units))
                         for nid, units in found.items()
                         if nid in comps and nid not in actors and len(units) > 1),
                        key=lambda r: r.component))


def declared_in(graph, stem: str) -> dict:
    """{node id: [unit keys it is declared a member of]}, first declared first:
    a statement of a unit's level the node heads that is no flow from it, no
    branch and no tree's root (a tree's face, or the tree continued where its
    root was a branch; one
    head of a node expanded at that level is its `X := {` header, so it needs a
    second), and a `\\-` branch's child, in its tree's unit."""
    lay = systems.lay_out(graph, stem)
    out: dict = {}
    for g in systems.walk(graph):
        key = lay.graph_system.get(id(g))
        if key is None:
            continue
        flows = {(e.line, e.src) for e in g.edges}
        parents = {t.parent for t in g.tree}
        flows |= {(t.line, t.node) for i, t in enumerate(g.tree)
                  if t.parent is not None or i in parents}
        heads: dict = {}
        for line, nid in g.heads:
            if (line, nid) not in flows:
                heads[nid] = heads.get(nid, 0) + 1
        for nid, n in heads.items():
            sub = g.expansions.get(nid)
            defined = sub is not None and sub.role != "state"
            if n > (1 if defined else 0):
                _add(out, nid, key)
        roots = systems.tree_roots(g.tree)
        for i, t in enumerate(g.tree):
            if t.parent is not None:
                root = g.tree[roots[i]].node
                _add(out, t.node, lay.by_face.get(root, key))
    return out


def _add(index: dict, k, value):
    vals = index.setdefault(k, [])
    if value not in vals:
        vals.append(value)


def store_writers(graph, comps: dict, read_verbs: Optional[tuple]) -> tuple:
    """Who writes each store, as `sigil check` reads it (scene.all_writers over the
    canonical scene, with the read verbs given)."""
    from sigil.model import scene, sim
    verbs = scene.READ_VERBS if read_verbs is None else read_verbs
    found = scene.all_writers(sim.canonical(graph), verbs)
    out = []
    for nid, c in comps.items():
        if c.kind != "store":
            continue
        who = found.get(nid, {})
        ws = tuple(sorted((comps[p].glyph if p in comps else str(p), tuple(sorted(how)))
                          for p, how in who.items()))
        out.append(Writers(c.glyph, c.home, ws))
    return tuple(sorted(out, key=lambda w: (-len(w.writers), w.store)))


# ---------------------------------------------------------------------------
# As data
# ---------------------------------------------------------------------------

def flow_json(f: FlowRef) -> dict:
    return {"src": f.src, "arrow": f.arrow, "dst": f.dst, "line": f.line}


def link_json(k: Link) -> dict:
    return {"from": k.src, "to": k.dst, "flows": [flow_json(f) for f in k.flows]}


def as_json(s: Structure) -> dict:
    """The reading as plain data (`sigil view --structure --json`), with a summary."""
    return {
        "top": s.top,
        "units": [{"key": u.key, "name": u.name, "kind": u.kind, "parent": u.parent,
                   "members": list(u.members),
                   "internal": [flow_json(f) for f in u.internal],
                   "calls": list(u.calls), "nests": list(u.nests),
                   "depends_on": list(u.depends_on)} for u in s.units],
        "cycles": [{"units": list(c.units),
                    "links": [link_json(k) for k in c.links]} for c in s.cycles],
        "up": [link_json(k) for k in s.up],
        "edge": [{"component": e.component, "unit": e.unit, "actors": list(e.actors)}
                 for e in s.edge],
        "reach": [{"component": r.component, "unit": r.unit, "out": list(r.out),
                   "out_actors": list(r.out_actors), "in": list(r.into),
                   "in_actors": list(r.in_actors)} for r in s.reach],
        "pass_throughs": [{"component": p.component, "unit": p.unit, "caller": p.caller,
                           "callee": p.callee} for p in s.pass_throughs],
        "large": [{"unit": u.key, "members": len(u.members)} for u in s.large],
        "repeated": [{"component": r.component, "units": list(r.units)} for r in s.repeated],
        "writers": [{"store": w.store, "unit": w.unit,
                     "writers": [{"principal": p, "how": list(how)} for p, how in w.writers]}
                    for w in s.writers],
        "summary": summary(s),
    }


def summary(s: Structure) -> str:
    """`N units: c cycles, u up, e edge parts, p pass-throughs, l over 9 members, r
    names in two units, w stores with two or more writers`."""
    shared = sum(1 for w in s.writers if len(w.writers) > 1)
    return (f"{count(len(s.units), 'unit')}: {count(len(s.cycles), 'cycle')}, "
            f"{len(s.up)} up, {count(len(s.edge), 'edge part')}, "
            f"{count(len(s.pass_throughs), 'pass-through')}, "
            f"{len(s.large)} over {LARGE} members, "
            f"{count(len(s.repeated), 'name')} in two units, "
            f"{count(shared, 'store')} with two or more writers")


def count(n: int, noun: str) -> str:
    """`1 unit`, `2 units`."""
    return f"{n} {noun}{'' if n == 1 else 's'}"
