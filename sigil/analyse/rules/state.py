"""
check_state.py — Sigil composition checks over shared state, state machines,
termination and structure (RFC 0003, rfcs/0003-composition-checks.catalog.md), plus the stale
acknowledgement rule.

A rule module for check.py: `rules(ck)` returns this module's `ck.Rule`s and
`exploration_causes(ck)` its SGC090 cause, where `ck` is check.py itself (passed
in, so this module never imports it). Rules:

    SGC003 ack-unused                an acknowledgement that covers no finding
    SGC131 shared-writable-store     two writers to a plain store, no resolution
    SGC132 undeclared-access         a flow its store's access list does not grant
    SGC133 lost-update               a concurrent read-modify-write
    SGC134 held-across-call          an owned resource held across a long call
    SGC135 stale-read                write the primary, read the async replica
    SGC136 shared-data-order         one data glyph written twice per tick
    SGC141 unreachable-state         nothing enters a state
    SGC142 dead-end-state            a stuck state in a machine that uses `$`
    SGC143 ambiguous-transition      one state, one trigger, two targets
    SGC144 no-exit                   a data lifecycle that can circle forever
    SGC145 orphan-event              an event nothing consumes
    SGC146 undriven-transition       a trigger nothing in the design raises
    SGC147 wait-without-timeout      a state waiting with no deadline
    SGC148 wildcard-leaves-terminal  `_ -<T>->` also leaves a final state
    SGC151 unbounded-recursion       a recursion with no stated bound
    SGC152 async-cycle               a message loop with no stated stop
    SGC153 unbounded-loop            a `loop @while` nothing ends
    SGC171 dependency-cycle          components calling each other
    SGC172 expansion-escape          a zoom level hiding a dependency
    SGC173 lock-order-cycle          resources acquired in opposite orders,
                                     or against a declared `lock-order`
    SGC174 optional-callee           a call to a node that may not exist
    SGC204 race (static half)        concurrent arrivals touching one store
    SGC205 ordering-unstated (static half, a guess)
    SGC090 exploration-incomplete    its loop-cap cause (a reachable loop the
                                     simulator runs fewer times than written)

Every rule names a risk the design leaves undeclared and is satisfied by a
declaration (catalog "Declare"); none asks for a different shape.

Standard library only. Deterministic: no clock, no randomness, no set-order output.
"""

from __future__ import annotations

import re
from dataclasses import replace
from functools import cached_property
from typing import NamedTuple, Optional


# ---------------------------------------------------------------------------
# SGC003 ack-unused (catalog §5)
# ---------------------------------------------------------------------------

def judged(finding) -> bool:
    """Whether a first-pass finding can make an acknowledgement used: a static one
    (no witness) or a trace one with a k <= 1 witness. Craft explores at k = 1 and
    spec at k = 2, so counting a k >= 2-only finding would flip the verdict with
    the mode. Severity is not looked at: a hidden or unemitted finding counts."""
    return finding.hit.k is None or finding.hit.k <= 1


def covered_names(ack, findings) -> frozenset:
    """The rule names whose judged findings `ack` covered (check.acknowledge
    attaches to each finding the acknowledgement that covered it)."""
    return frozenset(f.rule.name for f in findings if f.ack == ack and judged(f))


def judgeable_names(ack, known: frozenset, refused: frozenset) -> tuple:
    """The names of a valid acknowledgement that SGC003 judges, in written order.
    A void one (no reason, SGC002) and names no rule has or that cannot be
    acknowledged (SGC001) are left to those rules."""
    if not ack.reason:
        return ()
    return tuple(n for n in ack.names if n in known and n not in refused)


def stale_names(ack, findings, known: frozenset, refused: frozenset) -> tuple:
    used = covered_names(ack, findings)
    return tuple(n for n in judgeable_names(ack, known, refused) if n not in used)


def ack_scope(ack) -> str:
    """Where an acknowledgement reaches, as the message says it."""
    if ack.document:
        return "in the document"
    if len(ack.span) > 1:
        return "in its block"
    if ack.span:
        return "on its line"
    return "anywhere: it sits above no statement"


def stale_hit(ck, ack, name: str):
    where = ack_scope(ack)
    return ck.Hit(ack.line, f"the acknowledgement covers no `{name}` finding {where}",
                  f"This acknowledgement covers no `{name}` finding {where}. Is it stale?",
                  anchor=("comment", ack.line), scopes=(("rule", name),),
                  fix=f"delete `{name}` from the acknowledgement, or move it to the "
                      "line it is about")


def ack_unused_rule(ck):
    def match(doc):
        for ack in doc.acks:
            for name in stale_names(ack, doc.findings, doc.known, ck.NOT_ACKNOWLEDGEABLE):
                yield stale_hit(ck, ack, name)

    return ck.Rule(
        "SGC003", "ack-unused", "advisory",
        ask="This acknowledgement covers no finding of the rule it names. Is it stale?",
        why="A stale acknowledgement may later silence an unrelated new finding.",
        fix="delete or move the stale acknowledgement", match=match,
        acknowledgeable=False, after_acks=True, family="0")


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------

_HEAD_RE = re.compile(r"\s*([A-Za-z_][\w-]*)")
_STORE_REF_RE = re.compile(r"[~*]?\|([^|]+)\|")
_DATA_ONLY_RE = re.compile(r"^\s*~?\{[^{}:]*\}\s*$")

# Resolutions a plain store may state (catalog SGC131, SGC204): @inv heads.
STORE_RESOLUTIONS = ("serialised", "cas", "atomic", "immutable")
BOUND_HEADS = ("depth", "terminates")            # SGC151, SGC171
HOLD_SECONDS = 1.0                               # SGC134's default hold


def inv_head(arg: Optional[str]) -> str:
    """The head of an `@inv` argument: `depth <= 32` → "depth"."""
    m = _HEAD_RE.match(arg or "")
    return m.group(1) if m else ""


def inv_args(mods) -> list:
    """The `@inv` arguments among (name, arg) modifier pairs."""
    return [arg or "" for name, arg in mods if name == "inv"]


def heads_of(mods) -> frozenset:
    return frozenset(inv_head(a) for a in inv_args(mods))


def has_mod(mods, name: str) -> bool:
    return any(n == name for n, _a in mods)


def mod_arg(mods, name: str) -> Optional[str]:
    return next((a for n, a in mods if n == name), None)


def glyph(node) -> str:
    """A node as the notation writes it: `[A]`, `{D}`, `<E>`, `(U)`, `|S|`, `~|S|`."""
    if node is None:
        return "?"
    name = node.name
    if node.kind == "store":
        prefix = "~" if node.is_mutable else "*" if node.is_stream else ""
        return f"{prefix}|{name}|"
    if node.kind == "event":
        return f"{'*' if node.is_stream else ''}<{name}>"
    wrap = {"service": "[{}]", "data": "{{{}}}", "actor": "({})"}.get(node.kind, "{}")
    return f"{'~' if node.is_mutable and node.kind == 'data' else ''}{wrap.format(name)}"


def listing(items) -> str:
    """`a`, `a and b`, `a, b and c` (items already formatted)."""
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def sccs(nodes: list, edges: dict) -> list:
    """Tarjan's strongly connected components, iterative and deterministic: nodes
    and each adjacency list are visited in the order given. Each component is a
    list in discovery order; the components come in completion order."""
    index, low, on, stack, out = {}, {}, set(), [], []
    counter = 0
    for root in nodes:
        if root in index:
            continue
        work = [(root, iter(edges.get(root, ())))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on.add(root)
        while work:
            v, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(edges.get(w, ()))))
                    advanced = True
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            if advanced:
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
                out.append(comp[::-1])
    return out


def bfs(seeds, step) -> list:
    """Everything reachable from `seeds` by `step(x) -> iterable`, in visit order."""
    seen, queue = dict.fromkeys(seeds), list(seeds)
    while queue:
        x = queue.pop(0)
        for y in step(x):
            if y not in seen:
                seen[y] = None
                queue.append(y)
    return list(seen)


def spawned(t) -> bool:
    """A composition-tree child that is a dynamic instance (catalog §1.4
    concurrent(n)): a `\\-*` spawn or a `*-` child. The same predicate as
    check_flow.instances; `\\-$` (from data) is no spawn."""
    return bool(t.spawn or t.rel == "*")


def wired_ids(g) -> frozenset:
    """The ids that take part in g's own structure: an end of one of its edges,
    a composition-tree node, or an expansion owner. A node named at a level only
    on a declaration line (`[A] @inv depth <= 4`) is not wired there."""
    out = {x for e in g.edges for x in (e.src, e.dst)}
    out |= {t.node for t in getattr(g, "tree", None) or []}
    return frozenset(out | set(g.expansions))


# ---------------------------------------------------------------------------
# State machines as the rules read them
# ---------------------------------------------------------------------------

class Transition(NamedTuple):
    src: str
    dst: str
    label: str
    line: int
    mods: tuple


class MachineView(NamedTuple):
    """One `state X { … }` machine: its owner, whether the owner is a data glyph
    (a record's lifecycle) or a component (modes), its named states and pseudo
    states, and its transitions in written order."""
    owner: str
    owner_glyph: str
    data: bool
    states: dict             # named state id → name
    start: frozenset         # `+` ids
    any: frozenset           # `_` ids
    end: frozenset           # `$` ids
    transitions: tuple

    def outgoing(self, s: str) -> list:
        """Transitions that leave s: its own, then the wildcards (`_`)."""
        return ([t for t in self.transitions if t.src == s]
                + [t for t in self.transitions if t.src in self.any])

    def specific(self, s: str) -> list:
        return [t for t in self.transitions if t.src == s]

    def uses_end(self) -> bool:
        return any(t.dst in self.end for t in self.transitions)

    def name(self, sid: str) -> str:
        if sid in self.start:
            return "+"
        if sid in self.any:
            return "_"
        if sid in self.end:
            return "$"
        return self.states.get(sid, sid)

    def seeds(self) -> Optional[list]:
        """Where the machine starts: every `+` target; with no `+`, every named
        state no transition enters; None when every state is entered (skip)."""
        if self.start:
            return [t.dst for t in self.transitions if t.src in self.start]
        entered = {t.dst for t in self.transitions}
        roots = [s for s in self.states if s not in entered]
        return roots or None

    def reachable(self) -> Optional[list]:
        seeds = self.seeds()
        if seeds is None:
            return None
        return bfs(seeds, lambda s: [t.dst for t in self.outgoing(s)])

    def state_line(self, sid: str) -> int:
        return min((t.line for t in self.transitions if sid in (t.src, t.dst)), default=0)

    def transition_text(self, t: Transition) -> str:
        return f"{self.name(t.src)} -{t.label}-> {self.name(t.dst)}"


def machine_view(owner: str, owner_node, graph) -> MachineView:
    states, pseudo = {}, {"start": set(), "any": set(), "end": set()}
    for nid, n in graph.nodes.items():
        kind = n.attrs.get("pseudo")
        if kind in pseudo:
            pseudo[kind].add(nid)
        elif kind is None:
            states[nid] = n.name
    trans = tuple(Transition(e.src, e.dst, e.label or "", e.line, tuple(e.mods))
                  for e in graph.edges)
    return MachineView(owner, glyph(owner_node), getattr(owner_node, "kind", "") == "data",
                       states, frozenset(pseudo["start"]), frozenset(pseudo["any"]),
                       frozenset(pseudo["end"]), trans)


# ---------------------------------------------------------------------------
# The facts the rules share, computed once per document
# ---------------------------------------------------------------------------

class Facts:
    """What this module's rules read off one document (catalog §1.4): every
    fact is derived from `doc` (check.Doc) on first use."""

    def __init__(self, doc):
        self.doc = doc

    # -- units and nodes -----------------------------------------------------

    @cached_property
    def units(self) -> list:
        """(graph, owner, level, top-level ancestor owner) for every graph."""
        out = []

        def walk(g, owner, level, top):
            out.append((g, owner, level, top))
            for nid, sub in g.expansions.items():
                walk(sub, nid, level + 1, top if top is not None else nid)
        walk(self.doc.graph, None, 0, None)
        return out

    @cached_property
    def nodes(self) -> dict:
        """{id: render.Node} over every graph, first seen."""
        out = {}
        for g, _o, _l, _t in self.units:
            for nid, n in g.nodes.items():
                out.setdefault(nid, n)
        return out

    @cached_property
    def lines(self) -> dict:
        """{node id: the first line naming it} over every graph."""
        node_lines = self.doc.scene.kit.node_lines
        out = {}
        for g, _o, _l, _t in self.units:
            for nid, line in node_lines(g, notes=False).items():
                if line and (nid not in out or line < out[nid]):
                    out[nid] = line
        return out

    @cached_property
    def mods(self) -> dict:
        """{node id: [(name, arg)]}: every modifier written on a node, over every
        occurrence in every graph (an expansion's `[Walk] @inv depth <= 32`
        declares the same node). The same fact as check_flow.node_mods."""
        out, seen = {}, set()
        for g, _o, _l, _t in self.units:
            for nid, n in g.nodes.items():
                if id(n) in seen:
                    continue
                seen.add(id(n))
                mine = out.setdefault(nid, [])
                mine += [p for p in n.mods if p not in mine]
        return out

    def line_of(self, nid: str) -> int:
        return self.lines.get(nid, 0)

    def g(self, nid: str) -> str:
        return glyph(self.nodes.get(nid))

    def kind(self, nid: str) -> str:
        n = self.nodes.get(nid)
        return n.kind if n is not None else ""

    @cached_property
    def machine_edges(self) -> frozenset:
        return frozenset(id(e) for g, _o, _l, _t in self.units if g.role == "state"
                         for e in g.edges)

    @cached_property
    def flows(self) -> list:
        """The canonical scene's flow wires, machine transitions left out."""
        return [w for w in self.doc.sc.wires
                if w.role == "flow" and id(w.edge) not in self.machine_edges]

    @cached_property
    def top_level_ids(self) -> frozenset:
        """The top level's own nodes: a node it only declares (`[A] @sla(…)`)
        while an expansion wires it belongs to that expansion."""
        top = self.doc.graph
        inner = {nid for g, _o, level, _t in self.units if level > 0 for nid in wired_ids(g)}
        wired = wired_ids(top)
        return frozenset(nid for nid in top.nodes if nid in wired or nid not in inner)

    def component(self, nid: str) -> str:
        """The top-level component a node belongs to: its dotted head
        (`Doc.walk` → `Doc`) at the top level; inside an expansion, its top
        ancestor's."""
        if nid not in self.top_level_ids:
            for g, _o, _l, top in self.units:
                if top is not None and nid in g.nodes:
                    nid = top
                    break
        n = self.nodes.get(nid)
        return (n.base_name if n is not None else nid).split(".", 1)[0]

    # -- declarations --------------------------------------------------------

    def heads(self, nid: str) -> frozenset:
        return heads_of(self.mods.get(nid, ()))

    @cached_property
    def all_inv(self) -> list:
        """(where, arg) of every `@inv` in the document: on nodes and on blocks."""
        out = []
        for g, _o, _l, _t in self.units:
            for nid, n in g.nodes.items():
                out += [(nid, a) for a in inv_args(n.mods)]
            for b in getattr(g, "blocks", None) or []:
                out += [(b, a) for a in inv_args(b.modifiers)]
        return out

    def store_heads(self, sid: str) -> frozenset:
        """The @inv heads declared about a store: on it, or naming it anywhere."""
        name = self.nodes[sid].name
        out = set(self.heads(sid))
        for _where, arg in self.all_inv:
            if any(m.group(1).strip() == name for m in _STORE_REF_RE.finditer(arg)):
                out.add(inv_head(arg))
        return frozenset(out)

    # -- stores --------------------------------------------------------------

    @cached_property
    def stores(self) -> list:
        return [nid for nid, n in self.nodes.items() if n.kind == "store"]

    def plain(self, sid: str) -> bool:
        n = self.nodes[sid]
        return not (n.is_mutable or n.is_stream)

    def heuristic(self, w) -> bool:
        """The access mode of w is the verb guess: nothing declares it and it is
        not a produced value. An undeclared `<->` is a guessed read-and-write
        (catalog §1.4 steps 4–5)."""
        store, principal = (w.dst, w.src) if self.kind(w.dst) == "store" else (w.src, w.dst)
        return (not self.doc.declared_access(principal, store)
                and self.doc.access_mode(w) in ("write", "rw"))

    @cached_property
    def store_wires(self) -> list:
        """The wires scene.all_writers reads a store's writers off: the flows and
        every emit's flow legs."""
        legs = [leg for w in self.doc.sc.wires if w.role == "emit"
                for leg in w.legs if leg.role == "flow"]
        return self.flows + legs

    @cached_property
    def all_store_flows(self) -> dict:
        """{store id: [(wire, principal, mode)]} of every store_wires wire touching
        each store, summary wires included (only summarised reads them)."""
        out = {}
        for w in self.store_wires:
            mode = self.doc.access_mode(w)
            if mode is None:
                continue
            store, principal = ((w.dst, w.src) if self.kind(w.dst) == "store"
                                else (w.src, w.dst))
            out.setdefault(store, []).append((w, principal, mode))
        return out

    @cached_property
    def summaries(self) -> frozenset:
        """The idents of the summary wires (sim's Program.summaries): an expanded
        node's out-wire whose detail inside its expansion carries the same
        traffic. A summary and its detail are one access, counted by the detail."""
        return frozenset(self.doc.prog.summaries or ())

    @cached_property
    def store_flows(self) -> dict:
        """{store id: [(wire, principal, mode)]} of the accesses to each store, a
        summary and its detail counted once (by the detail): what every rule scans."""
        out = {}
        for sid, flows in self.all_store_flows.items():
            kept = [wpm for wpm in flows if wpm[0].ident not in self.summaries]
            if kept:
                out[sid] = kept
        return out

    def summarised(self, sid: str, principal: str) -> bool:
        """Whether every wire by which principal writes sid (a flow or an emit's
        leg, as writers counts them) is a summary, so its detail's writer stands
        for it."""
        mine = [w for w, p, m in self.all_store_flows.get(sid, [])
                if p == principal and m in ("write", "rw")]
        return bool(mine) and all(w.ident in self.summaries for w in mine)

    def writers(self, sid: str) -> dict:
        return self.doc.writers(sid)

    def role(self, principal: str) -> str:
        """A principal counted by role: `Worker<N>` is one principal."""
        n = self.nodes.get(principal)
        return n.base_name if n is not None else principal

    def access_entries(self, sid: str, mode: str) -> list:
        return [a for g, _o, _l, _t in self.units for a in getattr(g, "access", None) or []
                if a.store == sid and a.mode == mode]

    def resolution(self, sid: str) -> Optional[str]:
        """How a plain store's concurrent writes are resolved, as written; None."""
        owners = {self.role(p) for p, srcs in self.writers(sid).items() if "owns" in srcs}
        if len(owners) == 1:
            return f"owned by {next(iter(owners))}"
        declared = {a.name or a.principal for a in self.access_entries(sid, "write")}
        if len(declared) == 1:
            return f"written only by {next(iter(declared))}"
        found = sorted(self.store_heads(sid) & set(STORE_RESOLUTIONS))
        return f"@inv {found[0]}" if found else None

    # -- the work graph, arrivals, concurrency -------------------------------

    @cached_property
    def entries(self) -> tuple:
        """The independent arrivals (catalog §1.4): the simulator's entries."""
        return tuple(self.doc.prog.entries.get(0, ()))

    def counted(self, nid: str) -> bool:
        """The node has cardinality: `×N` with N > 1 or symbolic."""
        arg = mod_arg(self.mods.get(nid, ()), "×")
        return arg is not None and not (arg.strip().isdigit() and int(arg) <= 1)

    def many_callers(self, nid: str) -> bool:
        """The node runs concurrently with itself by its own cardinality. An actor
        with cardinality and `@inv ordered(key)` is sequential per key (catalog
        SGC204 Declare): its callers' arrivals are ordered, not concurrent."""
        if not self.counted(nid):
            return False
        return not (self.kind(nid) == "actor" and "ordered" in self.heads(nid))

    @cached_property
    def reach(self) -> dict:
        """{entry: frozenset of (ui, node) pairs and wire ids it reaches}."""
        out = {}
        for e in self.entries:
            prog = replace(self.doc.prog, entries={**self.doc.prog.entries, 0: (e,)})
            wires, nodes, _regions = self.doc.sim.reachable(prog)
            out[e] = (frozenset(nid for _ui, nid in nodes), frozenset(id(w) for w in wires))
        return out

    def entries_reaching(self, nid: str) -> list:
        return [e for e in self.entries if nid in self.reach[e][0]]

    def entries_reaching_wire(self, w) -> list:
        return [e for e in self.entries if id(w) in self.reach[e][1]]

    @cached_property
    def concurrent(self) -> frozenset:
        """The nodes that may run concurrently with themselves (catalog §1.4
        concurrent(n)): cardinality, a spawn, a generic role, a stream feed,
        `(User)×N` entry, or two or more arrivals; propagated down the work
        wires."""
        roots = set()
        for nid, n in self.nodes.items():
            if n.kind in ("store", "state"):
                continue
            if self.many_callers(nid) or n.params:
                roots.add(nid)
        for w in self.flows:
            if getattr(w.edge, "card", None):
                roots.add(w.dst)
            src = self.nodes.get(w.src)
            if src is not None and src.is_stream and src.kind == "event":
                roots.add(w.dst)
        for g, _o, _l, _t in self.units:
            for t in getattr(g, "tree", None) or []:
                if spawned(t):
                    roots.add(t.node)
        for e in self.entries:
            if self.many_callers(e):
                roots |= self.reach[e][0]
        for nid in self.nodes:
            if len(self.entries_reaching(nid)) >= 2:
                roots.add(nid)
        succ = {}
        for w in self.flows:
            if self.kind(w.dst) not in ("store", "data"):
                succ.setdefault(w.src, []).append(w.dst)
        return frozenset(bfs(sorted(roots), lambda x: succ.get(x, ())))

    # -- call graphs ---------------------------------------------------------

    def sync_wire(self, w) -> bool:
        """A sync call between components (catalog §1.4 sync chain): `->`, `<->`,
        `*>` or a join target; never a self-edge that is no recursion, never
        into an actor (a reply), a store, data or an event."""
        if w.kind in ("~>", "!>", "=>", "?>"):
            return False
        if w.src == w.dst:
            return bool(w.call is not None and w.call.recursive)
        work = ("service", "alias")
        return self.kind(w.src) in work and self.kind(w.dst) in work

    @cached_property
    def sync_edges(self) -> dict:
        """{node: [node]} of the sync chain, plus alias calls by name."""
        out = {}
        aliases = self.doc.prog.aliases
        for w in self.flows:
            if self.sync_wire(w):
                out.setdefault(w.src, []).append(w.dst)
            call = w.call
            if call is not None and call.op and not call.external:
                target = aliases.get(self.doc.scene.op_verb(call.op))
                if target is not None:
                    out.setdefault(w.src, []).append(target[1])
        return {k: list(dict.fromkeys(v)) for k, v in out.items()}

    def wires_within(self, members: frozenset, pick) -> list:
        """The flows from a member to a member that pick keeps, in flow order."""
        by_src = self._flows_by_src
        found = sorted(k for n in members for k in by_src.get(n, ()))
        return [w for w in (self.flows[k] for k in found) if w.dst in members and pick(w)]

    @cached_property
    def _flows_by_src(self) -> dict:
        """{source node: [its flows' indices in self.flows]}."""
        out = {}
        for k, w in enumerate(self.flows):
            out.setdefault(w.src, []).append(k)
        return out

    def blocks_of(self, w) -> list:
        """The Blocks enclosing a wire, innermost first."""
        g = self.unit_graph(w)
        blocks = getattr(g, "blocks", None) or []
        out, bi = [], w.block
        while bi is not None and 0 <= bi < len(blocks):
            out.append(blocks[bi])
            bi = blocks[bi].parent
        return out

    def unit_graph(self, w):
        for g, _o, _l, _t in self.units:
            if any(e is w.edge for e in g.edges):
                return g
        return self.doc.graph

    @cached_property
    def machines(self) -> list:
        out = []
        for g, owner, _l, _t in self.units:
            if g.role == "state" and owner is not None:
                out.append(machine_view(owner, self.nodes.get(owner), g))
        return out


def facts_of(doc) -> Facts:
    """The Facts of a document, built once and kept on it."""
    found = doc.__dict__.get("_state_facts")
    if found is None:
        found = doc.__dict__["_state_facts"] = Facts(doc)
    return found


# ---------------------------------------------------------------------------
# Shared state and access (SGC13x) and the static half of SGC204
# ---------------------------------------------------------------------------

def store_scopes(sid: str, nid: Optional[str] = None) -> tuple:
    """Folding scopes (catalog §1.7): the store; the (node, store) pair."""
    out = (("store", sid),)
    return out + ((("node_store", f"{nid}|{sid}"),) if nid else ())


def writer_roles(f: Facts, sid: str) -> dict:
    """{role: guessed} of a store's writers; a writer is a guess when every flow
    that makes it one reads its mode off a verb. A writer only by summary wires
    is not one: its expansion's detail writes in its place."""
    out = {}
    flows = f.store_flows.get(sid, [])
    for principal, srcs in f.writers(sid).items():
        if principal == sid or (srcs == frozenset({"flow"}) and f.summarised(sid, principal)):
            continue
        mine = [w for w, p, m in flows if p == principal and m in ("write", "rw")]
        guessed = srcs == frozenset({"flow"}) and all(f.heuristic(w) for w in mine)
        role = f.role(principal)
        out[role] = out.get(role, True) and guessed
    return out


def find_shared_writable(ck, f: Facts):
    """SGC131 (a): a plain store with two or more writers and no resolution;
    (c): one writer plus flows of unknown mode that could make two (a hint, which
    folds nothing: a hint never hides a race). A summarised outer flow and its
    expansion's detail are one writer (writer_roles)."""
    for sid in f.stores:
        if not f.plain(sid) or f.resolution(sid):
            continue
        roles = writer_roles(f, sid)
        line = f.line_of(sid)
        if len(roles) >= 2:
            names = listing(f"`{r}`" for r in sorted(roles))
            guess = "a writer read off its op verb" if any(roles.values()) else ""
            yield ck.Hit(line, f"`{f.g(sid)}` has {len(roles)} writers ({names}) and no "
                               "stated resolution",
                         f"`{f.g(sid)}` has {len(roles)} writers ({names}). How are their "
                         "writes resolved?",
                         anchor=("node", sid), scopes=store_scopes(sid), guess=guess)
            continue
        unknown = sorted({f.role(p) for w, p, m in f.store_flows.get(sid, [])
                          if m == "unknown" and f.role(p) not in roles})
        if len(roles) == 1 and unknown:
            who = listing(f"`{u}`" for u in unknown)
            yield ck.Hit(line, f"{who} use `{f.g(sid)}` without saying whether they "
                               "write it; it has one known writer",
                         f"Does {who} read or write `{f.g(sid)}`? `@read`/`@write`, or a "
                         "verb, says.", anchor=("node", sid),
                         tier="hint", fix="declare `@read(…)` / `@write(…)` or name a verb")


def granted(f: Facts, entries: list, principal: str) -> bool:
    """Whether an access list names the principal (by id, or by role name)."""
    names = {principal, f.role(principal)}
    n = f.nodes.get(principal)
    if n is not None:
        names.add(n.name)
    return any(a.principal == principal or a.name in names for a in entries)


def borrowed(f: Facts, sid: str, principal: str, need: str) -> bool:
    return any(a.narrow in (None, need) or need == "read"
               for a in f.access_entries(sid, "borrow") if granted(f, [a], principal))


def find_undeclared_access(ck, f: Facts):
    """SGC132: per direction, opt-in: a write on a store with `@write`, a read on
    one with `@read`, by a principal the list does not grant (nor a borrow)."""
    for sid in f.stores:
        writes, reads = f.access_entries(sid, "write"), f.access_entries(sid, "read")
        for w, p, m in f.store_flows.get(sid, []):
            if p == sid or m == "unknown":
                continue
            if writes and m in ("write", "rw") and not granted(f, writes, p) \
                    and not borrowed(f, sid, p, "write"):
                who = listing(sorted({a.name or f.role(a.principal) for a in writes}))
                yield ck.Hit(w.line, f"`{f.g(p)}` writes `{f.g(sid)}`, whose `@write` "
                                     f"grants only {who}",
                             f"`{f.g(p)}` writes `{f.g(sid)}`, which grants write only to "
                             f"{who}. Should it?",
                             anchor=("wire", w.ident), scopes=store_scopes(sid, p),
                             guess="the write is read off its op verb" if f.heuristic(w) else "",
                             fix=f"add {f.role(p)} to `@write(…)`, or borrow write access")
            elif reads and m in ("read", "rw") and not granted(f, reads + writes, p) \
                    and not borrowed(f, sid, p, "read"):
                who = listing(sorted({a.name or f.role(a.principal) for a in reads + writes}))
                yield ck.Hit(w.line, f"`{f.g(p)}` reads `{f.g(sid)}`, whose access list "
                                     f"grants only {who}",
                             f"`{f.g(p)}` reads `{f.g(sid)}`, which grants read only to "
                             f"{who}. Should it?",
                             anchor=("wire", w.ident), scopes=store_scopes(sid, p),
                             fix=f"add {f.role(p)} to `@read(…)`, or borrow read access")


def node_store_flows(f: Facts, nid: str, sid: str) -> list:
    """(wire, mode) of node nid's flows touching store sid, in line order."""
    return sorted(((w, m) for w, p, m in f.store_flows.get(sid, []) if p == nid),
                  key=lambda wm: (wm[0].line, f.doc.prog.order.get(id(wm[0]), 0)))


def read_modify_write(f: Facts, nid: str, sid: str):
    """The write of a read-modify-write by nid on sid: a read then a write, or
    one write whose value reads `${state.…}` (RFC 0003 Q11: not atomic). None."""
    seen_read = False
    for w, m in node_store_flows(f, nid, sid):
        if m in ("write", "rw") and (seen_read or "${state." in (w.payload or "")):
            return w
        if m == "read":
            seen_read = True
    return None


def owns_store(f: Facts, nid: str, sid: str) -> bool:
    return "owns" in f.writers(sid).get(nid, frozenset())


def find_lost_update(ck, f: Facts):
    """SGC133: a read-modify-write by a node that can run concurrently with
    itself, with no atomic / cas, merge kind with appends, or owner."""
    for sid in f.stores:
        store = f.nodes[sid]
        for nid in sorted({p for _w, p, _m in f.store_flows.get(sid, [])}):
            w = read_modify_write(f, nid, sid)
            if w is None or nid not in f.concurrent:
                continue
            if (f.heads(nid) | f.store_heads(sid)) & {"atomic", "cas"}:
                continue
            if store.is_stream and "++" in (w.payload or "") or owns_store(f, nid, sid):
                continue
            yield ck.Hit(w.line, f"`{f.g(nid)}` reads then writes `{f.g(sid)}` and can run "
                                 "concurrently with itself",
                         f"`{f.g(nid)}` reads then writes `{f.g(sid)}`"
                         f"{' (`' + w.payload.strip() + '`)' if w.payload else ''}. Can two "
                         "of these run at once?",
                         anchor=("wire", w.ident), scopes=store_scopes(sid, nid))


def store_accesses(f: Facts, sid: str, entry: str) -> list:
    """(wire, principal, mode) of the known-mode accesses to sid that entry reaches."""
    wires = f.reach[entry][1]
    return [(w, p, m) for w, p, m in f.store_flows.get(sid, [])
            if m != "unknown" and id(w) in wires]


def racing_writers(f: Facts, sid: str) -> dict:
    """{writer node: (other participants, guessed)} of a store's static races
    (catalog SGC204, half 1): two arrivals reach the store and one writes it, or
    one arrival writes it through a node that runs concurrently with itself.
    Arrivals from one plain actor are one entry (RFC 0003 Q10: one sequential caller)."""
    per = {e: store_accesses(f, sid, e) for e in f.entries}
    per = {e: acc for e, acc in per.items() if acc}
    out = {}

    def note(w, p, others):
        prev = out.get(p, (frozenset(), True))
        out[p] = (prev[0] | frozenset(others), prev[1] and f.heuristic(w))

    entries = list(per)
    for i, a in enumerate(entries):
        for b in entries[i + 1:]:
            for mine, theirs in ((per[a], per[b]), (per[b], per[a])):
                for w, p, m in mine:
                    if m in ("write", "rw"):
                        note(w, p, {q for _w, q, _m in theirs})
        for w, p, m in per[a]:
            if m in ("write", "rw") and (f.many_callers(a) or p in f.concurrent):
                note(w, p, {p})
    return out


def find_race_static(ck, f: Facts):
    """SGC204 (static half): concurrent arrivals reach one plain, unresolved store
    and one writes it. One finding per writing node."""
    for sid in f.stores:
        if not f.plain(sid) or f.resolution(sid):
            continue
        for p, (others, guessed) in sorted(racing_writers(f, sid).items()):
            w = next(w for w, q, m in f.store_flows.get(sid, []) if q == p and m in ("write", "rw"))
            peers = sorted(o for o in others if o != p)
            if peers:
                verb = "touches" if len(peers) == 1 else "touch"
                what = f"{listing(f'`{f.g(o)}`' for o in peers)} also {verb} it"
            else:
                what = "it can run concurrently with itself"
            yield ck.Hit(w.line, f"`{f.g(p)}` writes `{f.g(sid)}` and {what}, with nothing "
                                 "ordering them",
                         f"`{f.g(p)}` writes `{f.g(sid)}` and {what}. Which write wins?",
                         anchor=("wire", w.ident), scopes=store_scopes(sid, p),
                         guess="the write is read off its op verb" if guessed else "")


def owns_blocks(f: Facts) -> list:
    """(graph, block index, block, resource) of every `owns` block; the resource
    is its glyph as written (`|Conn|`), whether or not a node names it."""
    out = []
    for g, _o, _l, _t in f.units:
        for bi, b in enumerate(getattr(g, "blocks", None) or []):
            if b.kind == "owns":
                arg = mod_arg(b.modifiers, "owns") or ""
                m = _STORE_REF_RE.search(arg)
                out.append((g, bi, b, f"|{m.group(1).strip()}|" if m else arg.strip()))
    return out


def region_wires(f: Facts, g, bi: int) -> list:
    """The flow wires drawn inside block bi of graph g (nested blocks included)."""
    blocks = getattr(g, "blocks", None) or []

    def inside(w):
        b = w.block
        while b is not None:
            if b == bi:
                return True
            b = blocks[b].parent
        return False
    edges = {id(e) for e in g.edges}
    return [w for w in f.flows if id(w.edge) in edges and inside(w)]


def sync_callee_wires(f: Facts, wires: list) -> list:
    """`wires` and every flow their sync callees run, transitively (stopping at
    `~>`); each with the path of nodes that led to it."""
    out, seen, queue = [], set(), [(w, ()) for w in wires]
    while queue:
        w, path = queue.pop(0)
        if id(w) in seen:
            continue
        seen.add(id(w))
        out.append((w, path))
        if w.kind == "~>" or w.src == w.dst:
            continue
        queue += [(x, path + (w.dst,)) for x in f.flows if x.src == w.dst and x.kind != "~>"]
    return out


def external(f: Facts, w) -> bool:
    """An external call (catalog §1.4): an `op`, or a call into an actor that returns."""
    if w.call is not None and w.call.external:
        return True
    return f.kind(w.dst) == "actor" and f.doc.sim.returned(w) is not None


def hold_text(policy: list) -> str:
    parts = [f"×{a}" for n, a in policy if n == "×"]
    parts += [f"at {a}" for n, a in policy if n == "timeout"]
    return " ".join(parts)


def long_hold(sim, policy: list) -> bool:
    """A bounded call that still holds long: retried, or one try over the hold."""
    if has_mod(policy, "×"):
        return True
    to = sim.duration(mod_arg(policy, "timeout"))
    return to is not None and to > HOLD_SECONDS


def bounded_call(policy: list) -> bool:
    """SGC101 is satisfied on the call itself: a `@timeout` or `@deadline` (catalog
    SGC101: `×N`, `@fallback` and routes do not bound a hang). An unbounded call is
    SGC101's finding, which folds this rule's at the call."""
    return has_mod(policy, "timeout") or has_mod(policy, "deadline")


def find_held_across_call(ck, f: Facts):
    """SGC134: an owns region (with its sync callees) makes a bounded external
    call that still holds long, and no deadline bounds it."""
    for g, bi, b, rid in owns_blocks(f):
        if has_mod(b.modifiers, "deadline"):
            continue
        holder = b.subject[0] if b.subject else (b.refs[0] if b.refs else "")
        res = rid or "the resource"
        for w, path in sync_callee_wires(f, region_wires(f, g, bi)):
            policy = f.doc.scene.call_policy(w)
            if not external(f, w) or not bounded_call(policy):
                continue
            if has_mod(policy, "deadline") or not long_hold(f.doc.sim, policy):
                continue
            op = (w.call.op if w.call is not None and w.call.op else f.g(w.dst))
            via = f" (via {' → '.join(f.g(n) for n in path)})" if path else ""
            yield ck.Hit(w.line, f"`{f.g(holder)}` holds `{res}` across `{op}` "
                                 f"({hold_text(policy)}){via}",
                         f"`{f.g(holder)}` holds `{res}` across `{op}` ({hold_text(policy)})"
                         f"{via}. Is that hold bounded?",
                         anchor=("wire", w.ident),
                         scopes=(("call", w.ident),),
                         fix="`@deadline(t)` on the call, or `} @deadline(t)` on the block")


def async_feeds(f: Facts) -> dict:
    """{store: {stores feeding it asynchronously}}: `|P| ~> |R|`, or through a
    stream / event between them."""
    out = {}
    for w in f.flows:
        if f.kind(w.src) == "store" and f.kind(w.dst) == "store" and w.kind == "~>":
            out.setdefault(w.dst, set()).add(w.src)
    for w in f.flows:
        if f.kind(w.src) == "store" and f.kind(w.dst) == "event":
            for x in f.flows:
                if x.src == w.dst and f.kind(x.dst) == "store":
                    out.setdefault(x.dst, set()).add(w.src)
    return out


def find_stale_read(ck, f: Facts):
    """SGC135: a node writes P and later reads R, fed only asynchronously from P,
    and no `@inv consistent(…)` is on R or the reader."""
    feeds = async_feeds(f)
    sync_into = {(w.src, w.dst) for w in f.flows if w.kind != "~>"}
    for nid in sorted({p for flows in f.store_flows.values() for _w, p, _m in flows}):
        mine = sorted(((w, s, m) for s, flows in f.store_flows.items()
                       for w, p, m in flows if p == nid), key=lambda x: x[0].line)
        written = []
        for w, sid, m in mine:
            if m in ("read", "rw"):
                for p in written:
                    if p in feeds.get(sid, ()) and (p, sid) not in sync_into \
                            and "consistent" not in f.heads(nid) | f.store_heads(sid):
                        yield ck.Hit(w.line, f"`{f.g(nid)}` writes `{f.g(p)}` then reads "
                                             f"`{f.g(sid)}`, which `{f.g(p)}` feeds "
                                             "asynchronously",
                                     f"`{f.g(nid)}` writes `{f.g(p)}` then reads "
                                     f"`{f.g(sid)}`. Must it see its own write?",
                                     anchor=("wire", w.ident),
                                     scopes=store_scopes(sid, nid),
                                     fix=f"`{f.g(sid)} @inv consistent(read-your-writes)` "
                                         "or `consistent(eventual)`")
                        break
            if m in ("write", "rw"):
                written.append(sid)


def fork_blocks(f: Facts) -> list:
    """(graph, block index, block) of every `loop` and `parallel` block."""
    return [(g, bi, b) for g, _o, _l, _t in f.units
            for bi, b in enumerate(getattr(g, "blocks", None) or [])
            if b.kind in ("loop", "parallel")]


def find_shared_data_order(ck, f: Facts):
    """SGC136: one data glyph written by two components inside one loop or
    parallel body, with no `@inv ordered(…)` and no flow between the writers."""
    linked = {(w.src, w.dst) for w in f.flows} | {(w.dst, w.src) for w in f.flows}
    for g, bi, b in fork_blocks(f):
        if "ordered" in heads_of(b.modifiers):
            continue
        written = {}
        for w in region_wires(f, g, bi):
            if f.kind(w.dst) == "data" and f.kind(w.src) not in ("data", "event", "store"):
                written.setdefault(w.dst, {}).setdefault(f.component(w.src), w)
        for did, by in written.items():
            ws = list(by.values())
            if len(ws) < 2 or any((a.src, c.src) in linked for a in ws for c in ws if a is not c):
                continue
            who = listing(f"`{f.g(w.src)}`" for w in ws)
            each = "each tick" if b.kind == "loop" else "in parallel"
            yield ck.Hit(ws[0].line, f"{who} both write `{f.g(did)}` {each} in no stated "
                                     "order",
                         f"{who} both write `{f.g(did)}` {each}. In what order?",
                         anchor=("block", f"{b.lines[0]}"),
                         fix="`@inv ordered(…)` on the block, or a flow between the writers")


# ---------------------------------------------------------------------------
# State machines (SGC14x)
# ---------------------------------------------------------------------------

def machine_scopes(m: MachineView, state: Optional[str] = None) -> tuple:
    """Folding scopes (catalog §1.7): the machine; one of its states."""
    out = (("machine", m.owner),)
    return out + ((("state", f"{m.owner}|{state}"),) if state else ())


def emitters(f: Facts, eid: str) -> list:
    """The wires into an event: emits, flows, routes."""
    return [w for w in f.flows if w.dst == eid and w.src != eid]


def consumers(f: Facts, eid: str) -> list:
    """The wires out of an event, its trigger wires included."""
    return [w for w in f.doc.sc.wires if w.src == eid and w.dst != eid
            and w.role in ("flow", "trigger") and id(w.edge) not in f.machine_edges]


def triggers_of(f: Facts, m: MachineView, t: Transition, pairs: list) -> list:
    return [tr for tr in pairs if tr.owner == m.owner and tr.src == t.src
            and tr.dst == t.dst and tr.label == t.label]


def driven(f: Facts, m: MachineView, t: Transition) -> bool:
    """A transition some event in the design raises: a live trigger whose event
    has an emitter."""
    return any(emitters(f, tr.event)
               for tr in triggers_of(f, m, t, f.doc.graph.triggers))


def find_unreachable_state(ck, f: Facts):
    """SGC141: a named state no path from a start enters."""
    for m in f.machines:
        reach = m.reachable()
        if reach is None:
            continue
        for sid, name in m.states.items():
            if sid not in reach:
                yield ck.Hit(m.state_line(sid), f"nothing enters `{name}` in `{m.owner_glyph}`",
                             f"Nothing enters `{name}` in `{m.owner_glyph}`. Which transition "
                             "leads there?", anchor=("node", sid),
                             scopes=machine_scopes(m, sid))


def find_dead_end_state(ck, f: Facts):
    """SGC142: in a machine that uses `$`, a reached state with a way in and no
    way out (no transition, no wildcard, no `$`)."""
    for m in f.machines:
        if not m.uses_end():
            continue
        for sid in m.reachable() or []:
            if sid not in m.states or m.outgoing(sid):
                continue
            if any(t.dst == sid for t in m.transitions):
                yield ck.Hit(m.state_line(sid), f"`{m.name(sid)}` has no way out, while "
                                                "other end states lead to `$`",
                             f"Is `{m.name(sid)}` terminal? The other end states lead to "
                             "`$`.", anchor=("node", sid), scopes=machine_scopes(m, sid),
                             fix="a triggered transition out (to `$` or elsewhere)")


def ambiguous_groups(m: MachineView) -> list:
    """The transitions of every (state, trigger) written twice with two targets,
    unless each carries its own `@inv`. A specific transition beside a `_` one on
    its trigger is not ambiguous: the specific one wins (catalog §6 NG6), in spec+sim."""
    out, groups = [], {}
    for t in m.transitions:
        groups.setdefault((t.src, t.label), []).append(t)
    for (_src, _label), ts in groups.items():
        if len({t.dst for t in ts}) > 1 and not all(has_mod(t.mods, "inv") for t in ts):
            out.append(ts)
    return out


def find_ambiguous_transition(ck, f: Facts):
    """SGC143: two transitions leave one state on one trigger."""
    for m in f.machines:
        for ts in ambiguous_groups(m):
            last = ts[-1]
            state = m.name(last.src)
            targets = listing(f"`{m.name(t.dst)}`" for t in ts)
            text = f"`{m.owner_glyph}` leaves `{state}` on `{last.label}` for {targets}"
            yield ck.Hit(last.line, text,
                         f"`{m.owner_glyph}` leaves `{state}` on `{last.label}` for "
                         f"{targets}. Which one wins?",
                         anchor=("line", last.line), scopes=machine_scopes(m, last.src),
                         fix="distinct triggers, or a per-transition `@inv` on each")


def closed_cycles(m: MachineView) -> list:
    """The closed SCCs (no transition leaves them) of two or more named states,
    self-loops removed and wildcards expanded to every named state."""
    edges = {}
    for s in m.states:
        edges[s] = [t.dst for t in m.outgoing(s) if t.dst != s]
    out = []
    for comp in sccs(list(m.states), edges):
        members = set(comp)
        if len(comp) >= 2 and all(d in members for s in comp for d in edges[s]):
            out.append(comp)
    return out


def find_no_exit(ck, f: Facts):
    """SGC144: a record's lifecycle (a machine on a data owner) that can circle
    with no way to an end, and no `@inv retention(t)` on the owner."""
    for m in f.machines:
        if not m.data or "retention" in f.heads(m.owner):
            continue
        for comp in closed_cycles(m):
            names = " ↔ ".join(f"`{m.name(s)}`" for s in comp)
            line = min(t.line for t in m.transitions if t.src in comp)
            yield ck.Hit(line, f"`{m.owner_glyph}` can cycle {names} with no way to an end",
                         f"`{m.owner_glyph}` can cycle {names} forever. What ends it, or how "
                         "long are records kept?",
                         anchor=("machine", m.owner), scopes=machine_scopes(m),
                         fix="a `$` path, an exhaustion transition, or "
                             f"`{m.owner_glyph} @inv retention(t)`")


def find_orphan_event(ck, f: Facts):
    """SGC145: an event something emits and nothing consumes (hint); advisory when
    narrowing took its consumer away, or when it is a `!>` route's target."""
    narrowed = {tr.event for tr in f.doc.graph.narrowed}
    for eid, n in f.nodes.items():
        if n.kind != "event":
            continue
        ins = emitters(f, eid)
        if not ins or consumers(f, eid):
            continue
        routed = any(w.kind == "!>" for w in ins)
        escalated = "" if eid not in narrowed and not routed else "advisory"
        why = (" (trigger narrowing aimed it elsewhere)" if eid in narrowed
               else " (it is a failure route's target)" if routed else "")
        yield ck.Hit(min(w.line for w in ins), f"nothing consumes `{glyph(n)}`{why}",
                     f"Nothing consumes `{glyph(n)}`{why}. Who receives it, or is it "
                     "consumed outside this design?",
                     anchor=("node", eid), scopes=(("event", eid),), tier=escalated or "",
                     fix=f"a consumer flow, or `{glyph(n)} -> (Actor)`")


def undriven_events(f: Facts) -> list:
    """Events with a flow out and nothing in: their emitter is hidden (catalog
    SGC146, non-machine part). Trigger-only events are reported per transition."""
    return [eid for eid, n in f.nodes.items() if n.kind == "event"
            and not emitters(f, eid) and any(w.role == "flow" for w in consumers(f, eid))]


def find_undriven(ck, f: Facts):
    """SGC146: a consumed event nothing produces (hint), and per machine each
    transition nothing raises; advisory when narrowing took its trigger away
    (case 1), or when nothing raises any transition out of `+` (case 2: one
    finding for the machine, the per-transition ones folded into it)."""
    for eid in undriven_events(f):
        e = f.g(eid)
        yield ck.Hit(f.line_of(eid), f"nothing in the design emits `{e}`",
                     f"Nothing in the design emits `{e}`. What raises it?",
                     anchor=("node", eid), scopes=(("event", eid),),
                     fix=f"an emitter, e.g. `(Cause) ~> {e}`")
    for m in f.machines:
        undriven = [t for t in m.transitions if not driven(f, m, t)]
        starts = [t for t in m.transitions if t.src in m.start]
        if starts and all(t in undriven for t in starts):
            labels = listing(dict.fromkeys(f"`{t.label}`" for t in starts))
            more = len(undriven) - len(starts)
            also = (f" ({more} more transition{'s are' if more > 1 else ' is'} undriven)"
                    if more > 0 else "")
            yield ck.Hit(starts[0].line, f"nothing in the design emits {labels}, so "
                                         f"`{m.owner_glyph}` never leaves `+`{also}",
                         f"Nothing in the design emits {labels}, so `{m.owner_glyph}` never "
                         f"leaves `+`{also}. What raises it?",
                         anchor=("machine", m.owner), tier="advisory",
                         scopes=(("state", f"{m.owner}|{starts[0].src}"),),
                         fix=f"an emitter, e.g. `(Cause) ~> {starts[0].label}`")
            continue
        for t in undriven:
            narrowed = bool(triggers_of(f, m, t, f.doc.graph.narrowed))
            why = " (an event of that name is aimed at another machine)" if narrowed else ""
            yield ck.Hit(t.line, f"nothing in the design emits `{t.label}`, so "
                                 f"`{m.transition_text(t)}` never fires{why}",
                         f"Nothing in the design emits `{t.label}`, so "
                         f"`{m.transition_text(t)}` never fires{why}. What raises it?",
                         anchor=("line", t.line), tier="advisory" if narrowed else "",
                         scopes=(("state", f"{m.owner}|{t.src}"),),
                         fix=f"an emitter, e.g. `(Cause) ~> {t.label}`; an aim "
                             f"`{t.label} -> {m.owner_glyph}` narrows the event")


def timed(t: Transition) -> bool:
    return has_mod(t.mods, "timeout") or has_mod(t.mods, "after")


def find_wait_without_timeout(ck, f: Facts):
    """SGC147: a reached, non-terminal state whose way out is only events (none of
    them timed) — ignoring transitions nothing raises (SGC146's) — on a machine
    whose owner states no `@inv retention(t)`."""
    for m in f.machines:
        if "retention" in f.heads(m.owner):
            continue
        for sid in m.reachable() or []:
            if sid not in m.states:
                continue
            own = [t for t in m.specific(sid) if t.dst != sid]
            if not own or any(timed(t) for t in m.outgoing(sid)):
                continue
            waits = [t for t in m.outgoing(sid) if t.dst != sid and driven(f, m, t)]
            if not waits:
                continue
            on = listing(dict.fromkeys(f"`{t.label}`" for t in waits))
            yield ck.Hit(min(t.line for t in waits), f"`{m.owner_glyph}` waits in `{m.name(sid)}` "
                                            f"for {on} with no timeout",
                         f"`{m.owner_glyph}` waits in `{m.name(sid)}` for {on}. What if it "
                         "never comes?", anchor=("node", sid), scopes=machine_scopes(m, sid),
                         fix="a timed transition (`… @after(t)`), or "
                             f"`{m.owner_glyph} @inv retention(t)`")


def looks_terminal(m: MachineView, sid: str) -> bool:
    """A state that leads to `$`, or that no transition of its own leaves."""
    own = m.specific(sid)
    return not own or any(t.dst in m.end for t in own)


def find_wildcard_leaves_terminal(ck, f: Facts):
    """SGC148: `_ -<T>-> X` also leaves states that look final, unless such a
    state has its own transition on T (a self-loop says "ignored on purpose")."""
    for m in f.machines:
        for wild in (t for t in m.transitions if t.src in m.any):
            hit = [s for s in m.states if s != wild.dst and looks_terminal(m, s)
                   and not any(t.label == wild.label for t in m.specific(s))]
            if not hit:
                continue
            names = listing(f"`{m.name(s)}`" for s in hit)
            yield ck.Hit(wild.line, f"a late `{wild.label}` also leaves {names}",
                         f"A late `{wild.label}` also leaves {names}. Is that intended?",
                         anchor=("line", wild.line), scopes=machine_scopes(m),
                         fix=f"a self-loop `S -{wild.label}-> S` on each final state")


# ---------------------------------------------------------------------------
# Termination (SGC15x) and dependency cycles (SGC171)
# ---------------------------------------------------------------------------

def reply_hint(f: Facts, wires: list) -> str:
    """A back-edge carrying only data reads as a call; `=>` says it is a reply."""
    for w in wires:
        if w.call is None and _DATA_ONLY_RE.match(w.payload or ""):
            return (f" (if `{f.g(w.src)} -> {f.g(w.dst)} : {w.payload.strip()}` is a reply, "
                    "write it as a `=>` return)")
    return ""


def sync_cycles(f: Facts) -> list:
    """(members, wires) of every cycle of the sync chain: an SCC of two or more
    nodes, or one node with a recursive self-call. Members in discovery order."""
    edges = f.sync_edges
    nodes = list(dict.fromkeys([n for n in edges] + [d for ds in edges.values() for d in ds]))
    out = []
    for comp in sccs(nodes, edges):
        members = frozenset(comp)
        wires = f.wires_within(members, f.sync_wire)
        if len(comp) >= 2 or any(w.src == w.dst for w in wires) or comp[0] in edges.get(comp[0], ()):
            out.append((comp, wires))
    return out


def exits(f: Facts, members: frozenset) -> bool:
    """A `?>` arm or a branch leaves the cycle (a `!>` route does not: it says
    what happens on failure, not when the recursion stops)."""
    if any(w.kind == "?>" and w.src in members and w.dst not in members for w in f.flows):
        return True
    for g, _o, _l, _t in f.units:
        for b in getattr(g, "blocks", None) or []:
            if b.kind == "branch" and set(b.refs or b.subject) & members:
                return True
    return False


def declares_bound(f: Facts, members) -> bool:
    return any(f.heads(n) & set(BOUND_HEADS) for n in members)


def cycle_text(f: Facts, comp: list) -> str:
    if len(comp) == 1:
        return f"`{f.g(comp[0])}` calls itself"
    return " → ".join(f"`{f.g(n)}`" for n in comp + comp[:1])


def cycle_line(f: Facts, comp: list, wires: list) -> int:
    return min((w.line for w in wires if w.line), default=f.line_of(comp[0]))


def find_unbounded_recursion(ck, f: Facts):
    """SGC151: a sync cycle inside one component (or a self-recursion) with no
    `@inv depth <= N` / `@inv terminates` and no `?>` or branch way out."""
    for comp, wires in sync_cycles(f):
        members = frozenset(comp)
        if len({f.component(n) for n in comp}) > 1:
            continue
        if declares_bound(f, comp) or exits(f, members):
            continue
        head = f.g(comp[0])
        yield ck.Hit(cycle_line(f, comp, wires), f"{cycle_text(f, comp)} with no stated "
                                                 f"bound{reply_hint(f, wires)}",
                     f"How deep can {cycle_text(f, comp) if len(comp) > 1 else f'`{head}`'} "
                     f"go?{reply_hint(f, wires)}",
                     anchor=("node", comp[0]), scopes=(("scc", "|".join(sorted(comp))),),
                     fix=f"`{head} @inv depth <= N` or `@inv terminates`, or a `?>` exit")


def find_dependency_cycle(ck, f: Facts):
    """SGC171: a sync cycle spanning two or more top-level components, with no
    timeout or deadline on one of its calls and no stated bound."""
    for comp, wires in sync_cycles(f):
        if len({f.component(n) for n in comp}) < 2 or declares_bound(f, comp):
            continue
        policies = [f.doc.scene.call_policy(w) for w in wires]
        if any(has_mod(p, "timeout") or has_mod(p, "deadline") for p in policies):
            continue
        names = listing(f"`{f.g(n)}`" for n in comp)
        yield ck.Hit(cycle_line(f, comp, wires), f"{names} call each other synchronously "
                                                 f"({cycle_text(f, comp)})"
                                                 f"{reply_hint(f, wires)}",
                     f"{names} call each other. How does the cycle avoid deadlock, or end?"
                     f"{reply_hint(f, wires)}",
                     anchor=("node", comp[0]), scopes=(("scc", "|".join(sorted(comp))),),
                     fix="`@timeout` / `@deadline` on a call of the cycle, or "
                         "`@inv depth <= N` / `@inv terminates`")


def async_wire(f: Facts, w, parallel_none: frozenset) -> bool:
    """An edge the sender does not wait on: `~>`, a produce into a stream or an
    event, a `parallel @none` member."""
    if w.kind == "~>" or id(w) in parallel_none:
        return True
    return w.kind == "=>" and f.kind(w.dst) == "event"


def work_cycles(f: Facts) -> list:
    """(members, wires) of every SCC of the whole work graph (every flow but
    `!>` routes and self-edges, actors left out: a flow into one is a reply)."""
    edges, wires = {}, []
    for w in f.flows:
        if w.kind == "!>" or w.src == w.dst or "actor" in (f.kind(w.src), f.kind(w.dst)):
            continue
        edges.setdefault(w.src, []).append(w.dst)
        wires.append(w)
    nodes = list(dict.fromkeys([n for n in edges] + [d for ds in edges.values() for d in ds]))
    out = []
    for comp in sccs(nodes, edges):
        if len(comp) >= 2:
            members = frozenset(comp)
            out.append((comp, [w for w in wires if w.src in members and w.dst in members]))
    return out


def parallel_none_wires(f: Facts) -> frozenset:
    out = set()
    for g, bi, b in fork_blocks(f):
        if b.kind == "parallel" and has_mod(b.modifiers, "none"):
            out |= {id(w) for w in region_wires(f, g, bi)}
    return frozenset(out)


def in_loop(f: Facts, wires: list) -> bool:
    return bool(wires) and all(any(b.kind == "loop" for b in f.blocks_of(w)) for w in wires)


def blocking_stream(f: Facts, members) -> Optional[str]:
    """A `^N@block` stream on the cycle (it can fill and deadlock)."""
    for n in members:
        arg = mod_arg(f.mods.get(n, ()), "^")
        if arg and "block" in arg:
            return n
    return None


def find_async_cycle(ck, f: Facts):
    """SGC152: a message loop (a work-graph cycle through an edge nobody waits on)
    with no `@after(t)`, `@inv hops <= N`, `?>` or route leaving it, outside any
    loop block. A `^N@block` stream on it asks what drains the stream."""
    pn = parallel_none_wires(f)
    for comp, wires in work_cycles(f):
        if not any(async_wire(f, w, pn) for w in wires):
            continue
        members = frozenset(comp)
        line = cycle_line(f, comp, wires)
        hops = any("hops" in f.heads(n) for n in comp)
        stream = blocking_stream(f, comp)
        if stream and not hops:
            yield ck.Hit(line, f"the loop {cycle_text(f, comp)} runs through "
                               f"`{f.g(stream)}`, which blocks when full",
                         f"What drains `{f.g(stream)}` when it is full?",
                         anchor=("node", stream), scopes=(("scc", "|".join(sorted(comp))),),
                         fix="`@drop` / `@latest` on the stream, or `@inv hops <= N`")
            continue
        if hops or in_loop(f, wires) or any(has_mod(w.mods, "after") for w in wires):
            continue
        if any(w.kind in ("?>", "!>") and w.src in members for w in f.flows):
            continue
        rootless = not any(w.dst in members and w.src not in members for w in f.flows) \
            and not members & set(f.entries)
        note = " (nothing outside enters it)" if rootless else ""
        yield ck.Hit(line, f"{cycle_text(f, comp)} loops with nothing stopping it{note}",
                     f"{cycle_text(f, comp)} loops{note}. What stops it?",
                     anchor=("node", comp[0]), scopes=(("scc", "|".join(sorted(comp))),),
                     fix=f"a `?>` exit, `@after(t)`, or `{f.g(comp[0])} @inv hops <= N`")


_VERB_RE = re.compile(r"\s*(?:op\s+)?(?:[A-Za-z_]\w*\.)*([A-Za-z_]\w*)")


def changes_store(f: Facts, w) -> bool:
    """A flow on a store whose op verb is no read verb changes it, even when it
    also produces a value (`pop => {Job}` drains `|Q|`)."""
    text = (w.call.op if w.call is not None and w.call.op else w.payload) or ""
    m = _VERB_RE.match(text)
    return bool(m) and m.group(1).lower() not in f.doc.read_verbs


def loop_condition_written(f: Facts, b) -> bool:
    """A `@while` / `@until` naming a store something in the design changes: a
    writer of it, or a flow on it with a verb that is no read verb."""
    for nid in b.refs:
        if f.kind(nid) != "store":
            continue
        if any(p != nid for p in f.writers(nid)):
            return True
        if any(changes_store(f, w) for w, _p, _m in f.store_flows.get(nid, [])):
            return True
    return False


def find_unbounded_loop(ck, f: Facts):
    """SGC153: a loop with no `@times` / `@each`, no `} @inv terminates`, and no
    writer of the store its condition names."""
    for g, _o, _l, _t in f.units:
        for b in getattr(g, "blocks", None) or []:
            if b.kind != "loop":
                continue
            if has_mod(b.modifiers, "times") or has_mod(b.modifiers, "each"):
                continue
            if "terminates" in heads_of(b.modifiers) or loop_condition_written(f, b):
                continue
            cond = b.header.strip() or "loop"
            yield ck.Hit(b.lines[0], f"nothing in the design ends `loop {cond}`",
                         f"What changes the condition so that `loop {cond}` ends?",
                         anchor=("block", str(b.lines[0])),
                         fix="`@times N`, `@each`, `} @inv terminates`, or a writer of the "
                             "condition")


# ---------------------------------------------------------------------------
# Structure (SGC172–SGC174)
# ---------------------------------------------------------------------------

def expansion_units(f: Facts) -> list:
    """(graph, owner, ancestor graphs) of every expansion (not a state machine)."""
    out = []

    def walk(g, ancestors):
        for nid, sub in g.expansions.items():
            if sub.role == "state":
                continue
            out.append((sub, nid, ancestors + [g]))
            walk(sub, ancestors + [g])
    walk(f.doc.graph, [])
    return out


def composed_under(g, owner: str, nid: str) -> bool:
    """The composition tree of g places nid somewhere under owner."""
    tree = getattr(g, "tree", None) or []
    for t in tree:
        p = t.parent
        if t.node != nid:
            continue
        while p is not None:
            if tree[p].node == owner:
                return True
            p = tree[p].parent
    return False


def find_expansion_escape(ck, f: Facts):
    """SGC172: a wire inside `[O] := { … }` reaches a node of an outer level other
    than O, and the outer levels never connect O with it."""
    for sub, owner, ancestors in expansion_units(f):
        outer = {nid for g in ancestors for nid in wired_ids(g)}
        connected = {(e.src, e.dst) for g in ancestors for e in g.edges}
        for e in sub.edges:
            d = e.dst
            if d == owner or d not in outer or e.src == d:
                continue
            if f.kind(d) != "service" or f.kind(e.src) != "service":
                continue
            if (owner, d) in connected or (d, owner) in connected:
                continue
            if any(composed_under(g, owner, d) for g in ancestors):
                continue
            yield ck.Hit(e.line, f"`{f.g(e.src)}` inside `{f.g(owner)}` reaches `{f.g(d)}`, "
                                 f"but the outer level never connects `{f.g(owner)}` to it",
                         f"`{f.g(e.src)}` inside `{f.g(owner)}` reaches `{f.g(d)}`, but the "
                         f"outer level never connects `{f.g(owner)}` to `{f.g(d)}`. Should it?",
                         anchor=("line", e.line),
                         fix=f"state `{f.g(owner)} -> {f.g(d)}` at the outer level")


def lock_edges(f: Facts) -> list:
    """(R1, R2, wires, line) of the lock-order graph: an owns block on R2 nested in
    one on R1, or a sync call inside owns R1 whose callee's chain acquires R2.
    `wires` are the calls that wait (empty for plain nesting)."""
    blocks = owns_blocks(f)
    acquires = {}                     # holder node → [(resource, block)]
    for g, bi, b, rid in blocks:
        for holder in (b.subject or b.refs):
            acquires.setdefault(holder, []).append(rid)
    out = []
    for g, bi, b, rid in blocks:
        all_blocks = getattr(g, "blocks", None) or []
        for g2, bj, b2, rid2 in blocks:
            if g2 is g and bj != bi and rid2 != rid and bi in _parents(all_blocks, bj):
                out.append((rid, rid2, [], b2.lines[0]))
        for w, path in sync_callee_wires(f, region_wires(f, g, bi)):
            if w.kind == "~>":
                continue
            for r2 in acquires.get(w.dst, []):
                if r2 != rid and w.dst not in (b.subject or b.refs):
                    out.append((rid, r2, [w], w.line))
    return out


def _parents(blocks: list, bi: int) -> list:
    out, p = [], blocks[bi].parent
    while p is not None:
        out.append(p)
        p = blocks[p].parent
    return out


def lock_order_chain(arg: str) -> list:
    """The resources of one `lock-order(|A| < |B| < …)` argument, in order, written
    `|Name|` as lock_edges writes them; [] for any other head."""
    if inv_head(arg) != "lock-order":
        return []
    return [f"|{m.group(1).strip()}|" for part in arg.split("<")
            for m in [_STORE_REF_RE.search(part)] if m]


def declared_precedence(chains) -> frozenset:
    """(earlier, later) for every pair the declared chains order, closed
    transitively across chains (`A < B` and `B < C` give `A < C`)."""
    pairs = {(a, b) for ch in chains for i, a in enumerate(ch) for b in ch[i + 1:]}
    while True:
        more = {(a, d) for a, b in pairs for c, d in pairs if b == c} - pairs
        if not more:
            return frozenset(pairs)
        pairs |= more


def find_lock_order_cycle(ck, f: Facts):
    """SGC173: with `@inv lock-order(…)` declared, every acquisition that goes
    against the declared order; and resources acquired in opposite orders (a cycle
    in the lock-order graph) with no `@timeout` / `@deadline` on a waiting call of
    the cycle, unless an against-order report already covers the cycle."""
    lock = [(r1, r2, wires, line) for r1, r2, wires, line in lock_edges(f) if r1 and r2]
    order = declared_precedence(lock_order_chain(a) for _w, a in f.all_inv)
    against = sorted({(line, r1, r2) for r1, r2, _w, line in lock if (r2, r1) in order})
    for line, held, wanted in against:
        yield against_order_hit(ck, line, held, wanted)
    yield from cycle_hits(ck, f, lock, {(r1, r2) for _l, r1, r2 in against})


def against_order_hit(ck, line: int, held: str, wanted: str):
    return ck.Hit(line, f"`{held}` is held while `{wanted}` is acquired, against the "
                        f"declared order (`{wanted}` before `{held}`)",
                  f"`{held}` is held while `{wanted}` is acquired, but the declared "
                  f"`lock-order` puts `{wanted}` first. Which order is right?",
                  anchor=("line", line),
                  fix=f"acquire `{wanted}` before `{held}`, or correct the "
                      "`@inv lock-order(…)`")


def cycle_hits(ck, f: Facts, lock: list, reported: set):
    """The undeclared half of SGC173: a cycle of `lock` edges with no time bound
    on a waiting call, skipped when one of its edges is already `reported`."""
    edges, waits = {}, {}
    for r1, r2, wires, line in lock:
        edges.setdefault(r1, []).append(r2)
        waits.setdefault((r1, r2), []).append((wires, line))
    for comp in sccs(list(edges), edges):
        if len(comp) < 2:
            continue
        members = set(comp)
        inner = {k: ws for k, ws in waits.items() if k[0] in members and k[1] in members}
        if reported & set(inner):
            continue
        calls = [w for ws in inner.values() for wires, _l in ws for w in wires]
        if any(has_mod(f.doc.scene.call_policy(w), n) for w in calls
               for n in ("timeout", "deadline")):
            continue
        line = min(l for ws in inner.values() for _w, l in ws)
        order = " → ".join(f"`{r}`" for r in comp + comp[:1])
        yield ck.Hit(line, f"resources are acquired in a cycle ({order}): circular wait",
                     f"{listing(f'`{r}`' for r in comp)} are acquired in opposite "
                     "orders. Which order is right?",
                     anchor=("line", line),
                     fix="one acquisition order, `@timeout` on the inner step, or "
                         "`@inv lock-order(…)`")


def optional_reason(f: Facts, nid: str) -> Optional[str]:
    """Why a node may have no instance: every tree entry of it is conditional
    (`\\-?`, `\\-_`, a `{cond}-`) or spawned; None when one always exists."""
    entries = [t for g, _o, _l, _t in f.units for t in getattr(g, "tree", None) or []
               if t.node == nid and t.parent is not None]
    if not entries:
        return None
    reasons = []
    for t in entries:
        if t.cond:
            reasons.append(f"only while `{t.cond}`")
        elif t.rel == "?":
            reasons.append("only conditionally")
        elif t.rel == "_":
            reasons.append("only as a standby")
        elif t.spawn:
            reasons.append("only once spawned")
        else:
            return None
    return reasons[0]


def find_optional_callee(ck, f: Facts):
    """SGC174: a call to a node that may have no instance, from a caller with no
    route and no `@fallback`."""
    prog = f.doc.prog
    for w in f.flows:
        if w.kind not in ("->", "<->", "→") or w.src == w.dst:
            continue
        why = optional_reason(f, w.dst)
        if why is None or has_mod(f.doc.scene.call_policy(w), "fallback"):
            continue
        if prog.routes.get((prog.wire_unit.get(id(w), 0), w.src)):
            continue
        yield ck.Hit(w.line, f"`{f.g(w.dst)}` exists {why}, and nothing says what "
                             f"`{f.g(w.src)}` does when it is absent",
                     f"`{f.g(w.dst)}` exists {why}. What does `{f.g(w.src)}` do when it's "
                     "absent?", anchor=("wire", w.ident),
                     scopes=(("call", w.ident),),
                     fix="a `!>` route or `@fallback(…)` on the call")


# ---------------------------------------------------------------------------
# SGC205 ordering-unstated, static half (a guess)
# ---------------------------------------------------------------------------

def state_block_invs(f: Facts, m: MachineView) -> list:
    """`} @inv …` written after a machine's closing brace. The parser keeps no
    modifiers there yet, so this reads the closing line's text (a stopgap until
    the model records them on the owner)."""
    lines = f.doc.lines
    end = max((t.line for t in m.transitions), default=0)
    for n in range(end, len(lines)):
        text = lines[n].strip()
        if text.startswith("}"):
            return re.findall(r"@inv\s*\(?\s*([^@#]*?)\s*\)?\s*(?=@|#|$)", text[1:])
    return []


def trigger_sources(f: Facts, m: MachineView) -> dict:
    """{source: [event]} of the events that drive m: an async emit is its own
    source; any other emitter counts as the arrivals that reach it."""
    out = {}
    for tr in f.doc.graph.triggers:
        if tr.owner != m.owner:
            continue
        for w in emitters(f, tr.event):
            keys = ([("emit", str(w.ident))] if w.kind == "~>"
                    else [("entry", e) for e in f.entries_reaching_wire(w)])
            if f.counted(w.src) or f.nodes.get(w.src) is not None and f.nodes[w.src].params:
                keys = [("instances", w.src)]
            for k in keys:
                out.setdefault(k, [])
                if tr.event not in out[k]:
                    out[k].append(tr.event)
    return out


def find_ordering_unstated(ck, f: Facts):
    """SGC205 (static half): a machine driven from two or more independent
    sources, or by `×N` instances, with no `@inv ordered(key)` on it or its
    events. A guess (one tier down): the trace half finds the real orderings."""
    for m in f.machines:
        heads = set(f.heads(m.owner)) | {inv_head(a) for a in state_block_invs(f, m)}
        sources = trigger_sources(f, m)
        events = list(dict.fromkeys(e for evs in sources.values() for e in evs))
        heads |= {h for e in events for h in f.heads(e)}
        if "ordered" in heads:
            continue
        many = any(k[0] == "instances" for k in sources)
        if not many and (len(sources) < 2 or len(events) < 2):
            continue
        names = listing(f"`{f.g(e)}`" for e in events)
        line = min((t.line for t in m.transitions), default=f.line_of(m.owner))
        yield ck.Hit(line, f"`{m.owner_glyph}` is driven by {names} from independent "
                           "sources, and no order is stated",
                     f"`{m.owner_glyph}` is driven by {names} from independent sources. Is "
                     "the order they arrive in guaranteed?",
                     anchor=("machine", m.owner), scopes=machine_scopes(m),
                     guess="independent sources read off the wiring",
                     fix=f"`@inv ordered(key)` on `{m.owner_glyph}` or its events, or "
                         "transitions for both orders")


# ---------------------------------------------------------------------------
# SGC090 exploration-incomplete: the loop-cap cause (static)
# ---------------------------------------------------------------------------

def capped_loops(sim, prog) -> list:
    """(Block, declared, runs) of every reachable loop the simulator runs fewer
    times than its `@times N` (a symbolic N: always)."""
    limits = sim.Limits()
    out = []
    for _key, region in sorted(sim.reachable(prog)[2].items(), key=lambda kv: kv[0]):
        if region is None or region.block.kind != "loop":
            continue
        times = (mod_arg(region.block.modifiers, "times") or "").strip()
        if not times:
            continue
        runs = sim.loop_count(region.block, limits)
        if not times.isdigit() or int(times) > runs:
            out.append((region.block, times, runs))
    return out


def loop_cap_cause(ck):
    def match(doc):
        limits = doc.sim.Limits()
        for b, times, runs in capped_loops(doc.sim, doc.prog):
            yield ck.Hit(b.lines[0], f"the simulator ran this loop {runs} of its {times} "
                                     f"times (limits: iterations={limits.iterations})",
                         f"The simulator ran this loop {runs} of its {times} times "
                         f"(limits: iterations={limits.iterations}). Are {runs} iterations "
                         "enough evidence?",
                         anchor=("block", str(b.lines[0])), acknowledgeable=True,
                         fix="run with a larger iterations limit, or acknowledge on the "
                             "loop's line")
    return match


def exploration_causes(ck) -> list:
    return [loop_cap_cause(ck)]


# ---------------------------------------------------------------------------
# The module's rules (catalog §2, §3, §5)
# ---------------------------------------------------------------------------

class Spec(NamedTuple):
    """One rule's registry data; `find(ck, facts)` yields its Hits."""
    id: str
    name: str
    tier: str
    find: object
    ask: str
    why: str
    fix: str
    satisfiers: tuple = ()
    implies: tuple = ()
    guess: tuple = ()


SPECS = (
    Spec("SGC131", "shared-writable-store", "advisory", find_shared_writable,
         "This store has several writers. How are their writes resolved?",
         "Two writers to one plain store: the last write wins by accident (single "
         "writer principle; DDIA ch. 5, 7).",
         "`@owns |S|`, a single `@write(X)`, `@inv serialised(|S|)` / `cas` / "
         "`atomic` / `immutable`, or the `~|S|` / `*|S|` kind",
         satisfiers=(("owner", "@owns"), ("store", "@write"), ("store", "serialised"),
                     ("store", "cas"), ("store", "atomic"), ("store", "immutable"),
                     ("store", "~|"), ("store", "*|")),
         implies=(("race", "store"), ("lost-update", "store")),
         guess=("access-mode",)),
    Spec("SGC132", "undeclared-access", "binding", find_undeclared_access,
         "This flow touches a store its access list does not grant. Should it?",
         "The design's access claims and its flows disagree (least privilege).",
         "add the principal to the list, or borrow from one that has it",
         satisfiers=(("store", "@write"), ("store", "@read"), ("owner", "@borrow")),
         guess=("access-mode",)),
    Spec("SGC133", "lost-update", "advisory", find_lost_update,
         "Can two of these read-modify-writes run at once?",
         "A concurrent read-modify-write loses updates (DDIA ch. 7).",
         "`@inv atomic(…)` or `@inv cas(version)`, the `*|S|` kind with `++` appends, "
         "or an `@owns |S| { … }` block",
         satisfiers=(("owner", "atomic"), ("owner", "cas"), ("store", "*|"),
                     ("owner", "@owns"))),
    Spec("SGC134", "held-across-call", "advisory", find_held_across_call,
         "This owned resource is held across a long external call. Is that hold bounded?",
         "Holding a resource across a slow call exhausts the pool (Nygard).",
         "`@deadline(t)` on the inner call or `} @deadline(t)` on the block",
         satisfiers=(("call", "@deadline"), ("block", "@deadline"))),
    Spec("SGC135", "stale-read", "advisory", find_stale_read,
         "This request reads a replica fed asynchronously after writing its primary. "
         "Must it see its own write?",
         "Replication lag breaks read-your-writes (DDIA ch. 5).",
         "`@inv consistent(read-your-writes)` or `consistent(eventual)` on the replica "
         "or the reader",
         satisfiers=(("store", "consistent"), ("callee", "consistent"))),
    Spec("SGC136", "shared-data-order", "hint", find_shared_data_order,
         "Several systems write one data glyph in one tick. In what order?",
         "The result depends on the writers' order, which is unstated.",
         "`@inv ordered(…)` on the loop or fork, or a flow between the writers",
         satisfiers=(("block", "ordered"),)),
    Spec("SGC141", "unreachable-state", "binding", find_unreachable_state,
         "Nothing enters this state. Which transition leads there?",
         "A state no start reaches is dead design, or a missing trigger (Harel).",
         "the entering transition"),
    Spec("SGC142", "dead-end-state", "hint", find_dead_end_state,
         "Is this state terminal? The machine's other end states lead to `$`.",
         "A non-terminal state with no way out strands its entities.",
         "a triggered transition out of it (to `$` or elsewhere)"),
    Spec("SGC143", "ambiguous-transition", "binding", find_ambiguous_transition,
         "One state leaves on one trigger for two targets. Which one wins?",
         "Two transitions on one trigger leave the outcome unstated (Harel; SCR).",
         "distinct triggers, or a per-transition `@inv` on each duplicate"),
    Spec("SGC144", "no-exit", "advisory", find_no_exit,
         "This lifecycle can circle forever. What ends it, or how long are records kept?",
         "Everything that accumulates must be purged (Nygard, Steady State).",
         "a `$` path, an exhaustion transition, or `@inv retention(t)` on the owner",
         satisfiers=(("machine", "retention"),)),
    Spec("SGC145", "orphan-event", "hint", find_orphan_event,
         "Nothing consumes this event. Who receives it, or is it consumed outside?",
         "An event nobody consumes is lost work or a stale design (Hohpe and Woolf).",
         "a consumer flow, or `<E> -> (Actor)` to say it is consumed outside"),
    Spec("SGC146", "undriven-transition", "hint", find_undriven,
         "Nothing in the design raises this event. What does?",
         "A trigger with no emitter is a dead transition, or a cause outside the "
         "design left unnamed.",
         "an emitter, preferably an outside actor that names the cause",
         implies=(("event-ignored", "machine"), ("ordering-unstated", "machine"),
                  ("wait-without-timeout", "machine"), ("wait-without-timeout", "state"))),
    Spec("SGC147", "wait-without-timeout", "advisory", find_wait_without_timeout,
         "This state waits on an event that may never come. What if it never comes?",
         "Every wait needs a deadline (Garcia-Molina and Salem; Nygard, Timeouts).",
         "a timed transition (`@after(t)` / `@timeout(t)`) or `@inv retention(t)` on "
         "the owner",
         satisfiers=(("machine", "@after"), ("machine", "@timeout"),
                     ("machine", "retention"))),
    Spec("SGC148", "wildcard-leaves-terminal", "advisory", find_wildcard_leaves_terminal,
         "A wildcard transition also leaves the final states. Is that intended?",
         "Terminal states absorb; a late event should not resurrect a finished entity.",
         "a self-loop `S -<T>-> S` on each final state"),
    Spec("SGC151", "unbounded-recursion", "advisory", find_unbounded_recursion,
         "How deep can this recursion go?",
         "A recursion with no stated bound may overflow or run forever on adversarial "
         "input.",
         "`@inv depth <= N` or `@inv terminates` on a node of the cycle, or a `?>` exit",
         satisfiers=(("callee", "depth"), ("callee", "terminates"), ("call", "?>")),
         implies=(("dependency-cycle", "scc"),)),
    Spec("SGC152", "async-cycle", "advisory", find_async_cycle,
         "These messages loop. What stops them?",
         "A message loop keeps the system busy without progress (livelock).",
         "a `?>` exit, `@after(t)`, `@inv hops <= N`, or `loop @until …`",
         satisfiers=(("call", "?>"), ("call", "@after"), ("callee", "hops"))),
    Spec("SGC153", "unbounded-loop", "hint", find_unbounded_loop,
         "What ends this loop?",
         "A loop whose condition nothing changes runs forever.",
         "`@times N`, `@each`, `} @inv terminates`, or a writer of the condition",
         satisfiers=(("block", "@times"), ("block", "@each"), ("block", "terminates"))),
    Spec("SGC171", "dependency-cycle", "advisory", find_dependency_cycle,
         "These components call each other. How does the cycle avoid deadlock, or end?",
         "Components in a sync cycle cannot be deployed apart and can deadlock (ADP).",
         "`@timeout` / `@deadline` on a call of the cycle, or `@inv depth <= N` / "
         "`@inv terminates`",
         satisfiers=(("call", "@timeout"), ("call", "@deadline"), ("callee", "depth"),
                     ("callee", "terminates"))),
    Spec("SGC172", "expansion-escape", "advisory", find_expansion_escape,
         "An inner node reaches a dependency the outer level never states. Should it?",
         "Zoom levels that hide a dependency mislead (Parnas).",
         "state the dependency at the outer level"),
    Spec("SGC173", "lock-order-cycle", "binding", find_lock_order_cycle,
         "Resources are acquired in opposite orders. Which order is right?",
         "Circular wait (Coffman et al. 1971).",
         "one acquisition order, `@timeout` on the inner step, or `@inv lock-order(…)`",
         satisfiers=(("call", "@timeout"), ("document", "lock-order"))),
    Spec("SGC174", "optional-callee", "hint", find_optional_callee,
         "This callee may not exist. What does the caller do when it's absent?",
         "A missing dependency should fail fast and visibly (Nygard).",
         "a `!>` route or `@fallback` on the call",
         satisfiers=(("call", "!>"), ("call", "@fallback"))),
    Spec("SGC204", "race", "binding", find_race_static,
         "Two tasks touch one store and nothing orders them. Which write wins?",
         "Unordered accesses, one a write: a data race or write skew (Lamport 1978).",
         "a single owner, the `*|S|` / `~|S|` kind, `@inv serialised(|S|)`, "
         "`@inv cas(version)`, `@inv atomic(…)`, or `@inv ordered(key)` on a "
         "`(User)×N` actor",
         satisfiers=(("owner", "@owns"), ("owner", "ordered"), ("store", "@write"), ("store", "serialised"),
                     ("store", "cas"), ("store", "atomic"), ("store", "immutable"),
                     ("store", "~|"), ("store", "*|")),
         implies=(("lost-update", "node_store"),), guess=("access-mode",)),
    Spec("SGC205", "ordering-unstated", "advisory", find_ordering_unstated,
         "This machine only works if its events arrive in order. Is that guaranteed?",
         "Partitions, retries and parallel consumers reorder events (DDIA ch. 9, 11).",
         "`@inv ordered(key)` on the events or the machine owner, or transitions for "
         "both orders",
         satisfiers=(("machine", "ordered"),), guess=("independent-sources",)),
)


def spec_rule(ck, spec: Spec):
    def match(doc):
        yield from spec.find(ck, facts_of(doc))
    return ck.Rule(spec.id, spec.name, spec.tier, ask=spec.ask, why=spec.why, fix=spec.fix,
                   match=match, satisfiers=spec.satisfiers, implies=spec.implies,
                   guess=spec.guess, family=spec.id[3:5])


def rules(ck) -> list:
    return [ack_unused_rule(ck)] + [spec_rule(ck, s) for s in SPECS]
