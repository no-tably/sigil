"""
check_flow.py — Sigil composition checks over calls, delivery, sagas, load and
failure handling (RFC 0003, rfcs/0003-catalog.md §2 families 10x-12x and 16x,
§3 the static halves of SGC201 and SGC202).

Not a command: check.py loads it (RULE_MODULES) and calls `rules(ck)` with
itself as `ck`, so this module never imports check.py. Every rule reads one
`Facts` record per document (flow_facts): the simulator's canonical scene and
program, the work wires outside state machines, node modifiers over every unit,
the call graph, and the failure flow. A rule never asks for a shape; each hit
names a risk and the declaration that would state how it is handled.

    SGC101 unguarded-call            external call with no time bound
    SGC102 retry-amplification       two or more retry layers multiply
    SGC103 timeout-budget-inverted   a timeout shorter than the chain below it
    SGC104 retry-without-backoff     an external call retried at once
    SGC111 retry-without-idempotency a retried call that changes state
    SGC112 duplicate-delivery        at-least-once delivery into a stateful consumer
    SGC113 dual-write                two durable effects in one activation
    SGC114 poison-message            a message-fed call that can fail, unrouted
    SGC121 saga-uncompensated        a step that can fail after earlier effects
    SGC122 fragile-compensation      a compensating route that may itself fail
    SGC123 race-loser-effects        a race member with effects
    SGC161 unbounded-buffer          a stream, accumulator or dead-letter store unbounded
    SGC162 unbounded-result          a store read returning every row
    SGC163 capacity-mismatch         many callers into one fixed callee
    SGC165 fanout-tail               a strict join member that can fail, unbounded
    SGC166 single-point-of-failure   a critical node with no redundancy stated
    SGC167 unbounded-spawn           dynamic children with no ceiling
    SGC201 unhandled-failure         a failure unwinding to a task's root unrouted
    SGC202 dead-failure-route        a `!>` route no failure reaches

Failure facts. sim.failure_analysis mirrors the simulator's failure handling
over the document's own program: a call fails when it is a choice point (an
external or resilient call, or one a `!>` route guards: the route states that it
can fail) or when its callee's activation can; `absorbed` holds the calls a
`@fallback` absorbed, and `live` the routes some failure selects (Q2: a route
under a fallback still fires). SGC201, SGC114, SGC121 and SGC165 read that. SGC202
reads the same analysis without route-made failures (route_induced=False), so a
route never makes its own guard fail; a route is then live when that analysis
selects it, when it guards a request (or a `=> {X}` continuing one), or when it
guards a `!` call that can fail. A `!` call ends the run when it fails
(sim._call_failed raises nothing), so its failure is reported at its root unless
a route guards it (`!` is not a satisfier).

Not covered yet (catalog clauses this module leaves out): SGC102's crossing into
retrying stream consumers and fan-out widths other than a destination's `×N`;
SGC121's choreography across `~>`; SGC166's dominator clause (b); SGC202 does not
judge the routes of an activation that only route-made failures reach (a route's
target that fires only because another route declared its failure), and its
routes on `*>` / `&` lines are held back until the simulator fixes B1
(GROUP_ROUTES_GATED), and block routes over requests until it fixes B2
(BLOCK_ROUTES_GATED).

Standard library only. Deterministic: written and wire order, never set order.
"""

from __future__ import annotations

import re
import weakref
from dataclasses import dataclass, field, replace
from typing import Callable, NamedTuple, Optional


SYNC_KINDS = ("->", "→", "<->", "*>", "?>")      # the caller waits
CALL_KINDS = ("->", "→")                         # a plain request (SGC163)
NOT_CALLEES = ("actor", "event", "data", "store", "state")
AMPLIFICATION = 9                # SGC102: attempts at the bottom worth asking about
GROUP_ROUTES_GATED = True        # routes on `*>` / `&` lines wait for B1
BLOCK_ROUTES_GATED = True        # SGC202: block routes over requests wait for B2
_VALUE_RE = re.compile(r'^\s*(?:\$\{[^}]*\}|"[^"]*"|-?\d+(?:\.\d+)?|[A-Za-z_]\w*)\s*$')
_VERB_RE = re.compile(r"\s*(?:op\s+)?(?:[A-Za-z_]\w*\.)*([A-Za-z_]\w*)")
_BRANCH_RE = re.compile(r"^\s*(?:\\-|\*-|\{[^}]*\}-|\(\d+\)-)")


# ---------------------------------------------------------------------------
# Facts: what every rule reads, built once per document
# ---------------------------------------------------------------------------

@dataclass
class Facts:
    """The flow facts of one document (flow_facts). `effects` and `failures` are
    the mutable part: memos filled the first time a rule asks (effect_of,
    failures_of)."""
    sim: object                      # sim.py
    scene: object                    # scene.py
    prog: object                     # sim.Program of the canonical scene
    graph: object                    # render.Graph of the document
    nodes: dict                      # id → render.Node, first seen over every unit
    mods: dict                       # id → [(name, arg)] over every occurrence
    flows: tuple                     # flow wires outside state machines, scene order
    unit: dict                       # id(wire) → unit index
    lines: dict                      # node id → the first line naming it
    access: Callable                 # wire → access mode (Doc.access_mode)
    read_verbs: tuple
    label: Callable                  # node id → glyph text
    text: tuple                      # the document's lines
    effects: dict = field(default_factory=dict)
    failures: Optional["Failures"] = None

    def kind(self, nid: str) -> str:
        n = self.nodes.get(nid)
        return n.kind if n is not None else ""

    def name(self, nid: str) -> str:
        return f"`{self.label(nid)}`"


_FACTS = weakref.WeakKeyDictionary()


def flow_facts(doc) -> Facts:
    """The Facts of a check.Doc, built on first use and kept with the doc."""
    if doc not in _FACTS:
        _FACTS[doc] = build_facts(doc)
    return _FACTS[doc]


def build_facts(doc) -> Facts:
    kit = doc.scene.kit
    prog = doc.prog
    graphs = [g for g, _owner, _level in doc.graphs]
    nodes = {}
    for g in graphs:
        for nid, n in g.nodes.items():
            nodes.setdefault(nid, n)
    return Facts(
        sim=doc.sim, scene=doc.scene, prog=prog, graph=doc.graph, nodes=nodes,
        mods=node_mods(graphs), flows=work_flows(prog), unit=dict(prog.wire_unit),
        lines=first_lines(graphs, kit.node_lines), access=doc.access_mode,
        read_verbs=tuple(doc.read_verbs),
        label=lambda nid: kit.node_label(nodes[nid]) if nid in nodes else nid,
        text=tuple(doc.lines))


_INV_HEAD_RE = re.compile(r"\s*([A-Za-z_][\w-]*)")


def inv_head(arg: Optional[str]) -> str:
    """The head of an `@inv` argument: `idempotent(order_id)` → "idempotent"."""
    m = _INV_HEAD_RE.match(arg or "")
    return m.group(1) if m else ""


def node_mods(graphs: list) -> dict:
    """{node id: [(name, arg)]}: every modifier written on a node, over every
    graph that holds it (each Node object read once)."""
    out, seen = {}, set()
    for g in graphs:
        for nid, n in g.nodes.items():
            if id(n) in seen:
                continue
            seen.add(id(n))
            mine = out.setdefault(nid, [])
            mine += [p for p in n.mods if p not in mine]
    return out


def first_lines(graphs: list, node_lines: Callable) -> dict:
    out = {}
    for g in graphs:
        for nid, line in node_lines(g, notes=False).items():
            if line and (nid not in out or line < out[nid]):
                out[nid] = line
    return out


def work_flows(prog) -> tuple:
    """The flow wires of every unit that is not a state machine, in scene order
    (routes included; a machine's transitions are never calls)."""
    out = []
    for w in prog.scene.wires:
        ui = prog.wire_unit.get(id(w))
        if w.role == "flow" and ui is not None and prog.units[ui].graph.role != "state":
            out.append(w)
    return tuple(out)


def heads(facts: Facts, pairs) -> frozenset:
    """The recognised-or-not heads of the `@inv` modifiers among (name, arg) pairs."""
    return frozenset(inv_head(arg) for name, arg in pairs if name == "inv")


def has_mod(pairs, name: str) -> bool:
    return any(n == name for n, _a in pairs)


def mod_arg(pairs, name: str) -> Optional[str]:
    return next(("" if a is None else a for n, a in pairs if n == name), None)


def block_mods(facts: Facts, w) -> list:
    """The modifiers of every block enclosing w (innermost first)."""
    ui = facts.unit.get(id(w))
    if ui is None or w.block is None:
        return []
    blocks = getattr(facts.prog.units[ui].graph, "blocks", None) or []
    out, bi = [], w.block
    while bi is not None and 0 <= bi < len(blocks):
        out += list(blocks[bi].modifiers)
        bi = blocks[bi].parent
    return out


def block_chain(facts: Facts, w) -> tuple:
    """The indices of the blocks enclosing w, innermost first."""
    ui = facts.unit.get(id(w))
    if ui is None or w.block is None:
        return ()
    blocks = getattr(facts.prog.units[ui].graph, "blocks", None) or []
    out, bi = [], w.block
    while bi is not None and 0 <= bi < len(blocks):
        out.append(bi)
        bi = blocks[bi].parent
    return tuple(out)


def declared_on(facts: Facts, head: str, w, *nids: str) -> bool:
    """`@inv head(…)` on w's call policy, on any of the nodes, or on a block
    enclosing w."""
    pairs = list(facts.scene.call_policy(w)) + block_mods(facts, w)
    for nid in nids:
        pairs += facts.mods.get(nid, [])
    return head in heads(facts, pairs)


# ---------------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------------

def is_sync(w) -> bool:
    return w.kind in SYNC_KINDS and w.src != w.dst


def is_route(w) -> bool:
    return w.kind == "!>"


def has_payload(w) -> bool:
    return bool(w.payload or (w.edge is not None and w.edge.target_op))


def is_external(facts: Facts, w) -> bool:
    """An external call (catalog §1.4): an `op ns.verb(…)`, or a call to an actor
    that returns. A plain notification to an actor is not one."""
    if w.call is not None and w.call.external:
        return True
    return (facts.kind(w.dst) == "actor" and not is_route(w)
            and facts.sim.returned(w) is not None)


def is_op_call(w) -> bool:
    return w.call is not None and w.call.external


def retry_arg(facts: Facts, w) -> Optional[str]:
    """The N of a retry `×N`: a `×` trailing a call payload (call_policy never
    holds a node's cardinality). None when the call is not retried."""
    if not has_payload(w):
        return None
    return mod_arg(facts.scene.call_policy(w), "×")


def attempts_of(arg: Optional[str]) -> Optional[int]:
    """1 + N for a numeric `×N`, 1 for no retry, None for a symbolic N."""
    if arg is None:
        return 1
    return 1 + int(arg) if arg.strip().isdigit() else None


def verb_of(facts: Facts, w) -> str:
    """The op verb a flow names: its Call's op, else its payload's first word."""
    if w.call is not None and w.call.op:
        return facts.scene.op_verb(w.call.op).rsplit(".", 1)[-1]
    if w.edge is not None and w.edge.target_op:
        return facts.scene.op_verb(w.edge.target_op).rsplit(".", 1)[-1]
    m = _VERB_RE.match(w.payload or "")
    return m.group(1) if m else ""


def call_name(facts: Facts, w) -> str:
    """What a call does, as a message names it: its op, else the callee."""
    if w.call is not None and w.call.op:
        return f"`{facts.scene.op_verb(w.call.op)}`"
    verb = verb_of(facts, w)
    return f"`{verb}`" if verb else facts.name(w.dst)


def callee_wires(facts: Facts, ui: int, nid: str) -> list:
    """The work a node does when called in unit ui: its body and its expansion's
    bodies, flat, in written order."""
    sim, prog = facts.sim, facts.prog
    out = list(sim._flat(prog.bodies.get((ui, nid), ())))
    exp = prog.expansions.get((ui, nid))
    if exp is not None:
        for (bui, _n), items in prog.bodies.items():
            if bui == exp:
                out += sim._flat(items)
    return out


def callee_key(facts: Facts, w) -> tuple:
    return (facts.unit.get(id(w), 0), w.dst)


def sync_calls(facts: Facts) -> dict:
    """{caller: [sync call wire]} over the work wires."""
    out = {}
    for w in facts.flows:
        if is_sync(w):
            out.setdefault(w.src, []).append(w)
    return out


def instances(facts: Facts, nid: str) -> bool:
    """Whether a node has instances: a `×N` on it or on a flow into it (Edge.card),
    a generic role (`Worker<N>`), or a dynamic composition child."""
    if has_mod(facts.mods.get(nid, []), "×"):
        return True
    n = facts.nodes.get(nid)
    if n is not None and n.params:
        return True
    if any(w.dst == nid and w.edge is not None and w.edge.card for w in facts.flows):
        return True
    for g in _graphs(facts):
        if any(t.node == nid and (t.spawn or t.rel == "*") for t in g.tree):
            return True
    return False


def _graphs(facts: Facts) -> list:
    return [u.graph for u in facts.prog.units]


# ---------------------------------------------------------------------------
# Effects (catalog §1.4 effectful)
# ---------------------------------------------------------------------------

class Effect(NamedTuple):
    what: str                        # "writes `|DB|`", for a message
    guess: str = ""                  # what was guessed ("" exact)
    store: str = ""                  # the store written, when the effect is a write


def effect_owners(w, eff: Effect) -> tuple:
    """The nodes whose `@inv` speaks for w's effect: the callee, and the store
    the effect writes when it reaches one (through a callee or directly)."""
    return (w.dst, eff.store) if eff.store and eff.store != w.dst else (w.dst,)


def effect_of(facts: Facts, w) -> Optional[Effect]:
    """What durable effect a work wire may have: a store write, an external call,
    an emit, or a callee whose body has one (transitively). A callee with no body
    and a non-read verb may change state (a guess). None: no effect."""
    return _effect_memo(facts, w, frozenset())[0]


def _effect_memo(facts: Facts, w, seen: frozenset) -> tuple:
    """(effect, cut): cut when the walk skipped a wire already on the path (a
    cycle), so the effect is partial and is not kept in facts.effects (the
    answer must not depend on which wire of a cycle was asked first)."""
    key = id(w)
    if key in facts.effects:
        return facts.effects[key], False
    out, cut = _effect(facts, w, seen | {key})
    if not cut or not seen:
        facts.effects[key] = out
    return out, cut


def _effect(facts: Facts, w, seen: frozenset) -> tuple:
    kind = facts.kind(w.dst)
    if kind == "store":
        return store_effect(facts, w), False
    if is_op_call(w):
        if verb_of(facts, w).lower() in facts.read_verbs:
            return None, False
        return Effect(f"calls {call_name(facts, w)}, which leaves the system"), False
    if kind == "event":
        return Effect(f"emits {facts.name(w.dst)}"), False
    if kind in ("actor", "data", "state") or w.src == w.dst:
        return None, False
    body = callee_wires(facts, facts.unit.get(id(w), 0), w.dst)
    if body:
        cut = False
        for x in body:
            if is_route(x) or x.kind in ("~>", "=>"):
                continue
            if id(x) in seen:
                cut = True
                continue
            inner, inner_cut = _effect_memo(facts, x, seen)
            cut = cut or inner_cut
            if inner is not None:
                return Effect(f"calls {facts.name(w.dst)}, which {inner.what}",
                              inner.guess, inner.store), cut
        return None, cut
    verb = verb_of(facts, w)
    if verb and verb.lower() not in facts.read_verbs:
        return Effect(f"may change {facts.name(w.dst)}",
                      f"{facts.name(w.dst)} has no body, and `{verb}` reads as a change"), False
    return None, False


def store_effect(facts: Facts, w) -> Optional[Effect]:
    """A flow into a store that writes it. Only a declared `@write` / `@read` is
    exact; a `<->` (read and write, catalog §1.4 access_mode step 5) and a verb's
    reading are guesses, and so is a non-read verb whose flow returns a value
    (access_mode reads a produced value as a read)."""
    mode = facts.access(w)
    store = facts.name(w.dst)
    exact = bool(facts.scene.declared_access(facts.graph, w.src, w.dst))
    verb = verb_of(facts, w)
    if mode in ("write", "rw"):
        if exact:
            return Effect(f"writes {store}", store=w.dst)
        if w.kind == "<->":
            return Effect(f"writes {store}", "`<->` reads as read-and-write", w.dst)
        return Effect(f"writes {store}", f"`{verb}` reads as a write", w.dst)
    if mode == "read" and not exact and verb and verb.lower() not in facts.read_verbs:
        return Effect(f"writes {store}", f"`{verb}` returns a value but reads as a write",
                      w.dst)
    return None


def is_value_assignment(facts: Facts, w) -> bool:
    """`~|S| : true` / `: ${x}`: a plain value into a scalar store, idempotent by
    construction."""
    n = facts.nodes.get(w.dst)
    return (n is not None and n.kind == "store" and n.is_mutable
            and bool(_VALUE_RE.match(w.payload or "")))


# ---------------------------------------------------------------------------
# Joins: the strict ones (SGC101's context, SGC165), races (SGC123)
# ---------------------------------------------------------------------------

class Member(NamedTuple):
    wire: object
    join: str                        # "a strict join" | "parallel @all" | …
    bounded: bool                    # the join itself carries a @deadline


def join_members(facts: Facts, strict: bool) -> list:
    """The members of every join a caller waits on: strict (`&` / `*>` groups,
    `parallel @all`) when `strict`, else races (`&?`, `parallel @any`)."""
    sim, out = facts.sim, []
    for items in facts.prog.bodies.values():
        out += _members(sim, items, strict)
    seen, uniq = set(), []
    for m in out:
        if id(m.wire) not in seen:
            seen.add(id(m.wire))
            uniq.append(m)
    return uniq


def _members(sim, items, strict: bool) -> list:
    out = []
    for it in items:
        if isinstance(it, sim.Group):
            if it.wires and it.wires[0].kind != "~>":
                if strict and it.kind == "all":
                    label = "a fan-out" if it.wires[0].kind == "*>" else "a strict join"
                    out += [Member(w, label, False) for w in it.wires]
                elif not strict and it.kind == "race":
                    out += [Member(w, "a race", False) for w in it.wires]
        elif isinstance(it, sim.Region):
            out += _region_members(sim, it, strict)
            out += _members(sim, it.items, strict)
    return out


def _region_members(sim, r, strict: bool) -> list:
    if r.block.kind != "parallel":
        return []
    mods = {n for n, _a in r.block.modifiers}
    if strict and not mods & {"any", "none"}:
        bounded = "deadline" in mods
        return [Member(w, "parallel @all", bounded) for it in r.items
                for w in sim._flat((it,)) if is_sync(w)]
    if not strict and "any" in mods:
        return [Member(sim._flat((it,))[0], "parallel @any", False) for it in r.items
                if sim._flat((it,))]
    return []


# ---------------------------------------------------------------------------
# Failure flow (catalog §1.5 CG7), judged against the program's real routes
# ---------------------------------------------------------------------------

class Failures(NamedTuple):
    """Two readings of the failure flow. The first counts a route as stating that
    what it guards can fail (sim.failure_analysis's default, as the simulator
    lists its choices): SGC201, SGC114, SGC121 and SGC165 read it, so a routed
    request counts as handled. The `own_` pair leaves those route-made failures out
    (route_induced=False): SGC202 judges each route against it, never against
    itself."""
    arriving: dict                   # (ui, node) → frozenset of guards
    absorbed: dict                   # (ui, node) → frozenset of ("call", ident)
    sources: frozenset               # idents of the calls that fail on their own
    routes: dict                     # (ui, node) → ((wire, guard), …)
    live: frozenset                  # idents of the routes some failure selects
    own_arriving: dict               # as arriving, without route-made failures
    own_live: frozenset              # as live, without route-made failures


def failures_of(facts: Facts) -> Failures:
    if facts.failures is None:
        sim, prog = facts.sim, b1_program(facts)
        flow = sim.failure_analysis(prog)
        own = sim.failure_analysis(prog, route_induced=False)
        sources = frozenset(p.cid[1] for p in sim.choice_points(prog) if p.cid[0] == "call")
        facts.failures = Failures(flow.arriving, flow.absorbed, sources, facts.prog.routes,
                                  flow.live, own.arriving, own.live)
    return facts.failures


def b1_program(facts: Facts):
    """The program the failure facts read: while B1 stands, without the routes on
    `*>` / `&` lines. Such a route makes its members fail, and the simulator then
    drops the guard at the join (B1), so the failure the author routed would
    escape as unrouted; the route itself never fires either way."""
    if not GROUP_ROUTES_GATED:
        return facts.prog
    routes = {k: tuple((w, g) for w, g in rs if not on_group_line(facts, g))
              for k, rs in facts.prog.routes.items()}
    return replace(facts.prog, routes={k: v for k, v in routes.items() if v})


def guarded_by(g, guard) -> bool:
    """Whether route guard g names the failure guard (never an unguarded route)."""
    if g is None or guard is None:
        return False
    return guard in g[1] if g[0] == "calls" else g == guard


def fails_itself(facts: Facts, fl: Failures, w) -> bool:
    """A call fails on its own (an external or resilient call, or one a route
    guards) or because its callee's activation can."""
    if w.ident in fl.sources:
        return True
    return activates(facts, w) and bool(fl.arriving.get(callee_key(facts, w)))


def activates(facts: Facts, w) -> bool:
    """A flow whose arrival runs its destination's work (sim._land): not an
    actor, a hole, an external node or an external op."""
    sn = facts.prog.scene.nodes.get(w.dst)
    if sn is None:
        return False
    return not (sn.node.is_hole or sn.external or sn.node.kind == "actor" or is_op_call(w))


def call_like(facts: Facts, w) -> bool:
    """A request that can fail when a route says so: a sync flow into anything
    but a data glyph, an event or a state (a produced value cannot fail), or a
    call of the node's own operation (`[Worker] -> run({Job})`)."""
    if w.call is not None and w.call.self_call:
        return True
    return is_sync(w) and facts.kind(w.dst) not in ("data", "event", "state")


def guarded_wires(facts: Facts, key: tuple, g) -> list:
    """The wires a route guard names: a block's own wires for a `} !>` route;
    for a continuation the wires of the line it continues, plus, when that line
    only produces (`=> {X}`), the flow it continues in turn (pitfall 4: the route
    is about the statement, `[Auth] -> |UserDB|` then `=> {Session}` then `!>`).
    An unguarded route names none."""
    if g is None:
        return []
    ui, nid = key
    if g[0] == "block":
        return [w for w in facts.flows if w.src == nid and facts.unit.get(id(w)) == ui
                and g[1] in block_chain(facts, w) and not is_route(w)]
    named = {ident for _c, ident in g[1]}
    out = [w for w in facts.flows if w.ident in named]
    conts = {w.edge.cont for w in out if w.edge is not None and w.edge.cont}
    out += [w for w in facts.flows if w.src == nid and facts.unit.get(id(w)) == ui
            and w.line in conts and w.ident not in named and not is_route(w)]
    return out


class Escape(NamedTuple):
    """A failure that leaves a task's root activation with no route chosen on its
    way: `root` the (ui, node) activation, `origin` the call where it starts (None:
    `node` itself fails, its own outcome or a join member's)."""
    root: tuple
    origin: object
    node: str


def escapes(facts: Facts, fl: Failures) -> list:
    """Every failure that unwinds to a task's root (an entry, or an activation a
    `~>`, a `=>` or a stream starts) with no route chosen anywhere on its way, one
    per origin (the first root it reaches, in written order)."""
    raw = RawFailures(facts, fl)
    roots = task_roots(facts, fl)
    found = [Escape(key, wire, node) for key in roots
             for guard in sorted(raw.unrouted(key), key=_guard_order(facts))
             for wire, node in raw.origins(key, guard)]
    found += halting_escapes(facts, fl, raw, roots)
    out, seen = [], set()
    for esc in found:
        at = esc.origin.ident if esc.origin is not None else esc.node
        if at not in seen:
            seen.add(at)
            out.append(esc)
    return out


def is_halting(facts: Facts, w) -> bool:
    """A call marked `!` with no `@fallback`, on either side of the arrow
    (scene.call_policy): when it fails the run ends there (sim._call_failed), so
    its failure raises nothing to a caller or a route."""
    pol = dict(facts.scene.call_policy(w))
    return not is_route(w) and "!" in pol and "fallback" not in pol


def fails_alone(facts: Facts, fl: Failures, w) -> bool:
    """A call that fails on its own for a reason other than its `!` mark (the
    simulator lists a `!` call as a choice, but `!` says must-not-fail, not can
    fail): an external op, or a `@timeout`, `×N` or `@deadline` on it."""
    pol = {n for n, _a in facts.scene.call_policy(w)}
    return w.ident in fl.sources and (is_op_call(w) or bool({"timeout", "×", "deadline"} & pol))


def halting_fails(facts: Facts, fl: Failures, w) -> bool:
    """A `!` call that can fail: on its own, or because its callee can."""
    return fails_alone(facts, fl, w) or (
        activates(facts, w) and bool(fl.arriving.get(callee_key(facts, w))))


def halting_origins(facts: Facts, fl: Failures, raw: "RawFailures", w) -> list:
    """(call wire, node) where the failure that ends the run at a `!` call w
    starts: w itself when it fails on its own, else the unrouted failures of its
    callee. [] when w cannot fail."""
    if fails_alone(facts, fl, w):
        return [(w, w.src)]
    if not activates(facts, w):
        return []
    callee = callee_key(facts, w)
    return [o for g in sorted(raw.unrouted(callee), key=_guard_order(facts))
            for o in raw.origins(callee, g)]


def halting_escapes(facts: Facts, fl: Failures, raw: "RawFailures", roots: list) -> list:
    """The failures a `!` call ends the run on, with no route guarding the call
    (catalog SGC201: `!` is not a satisfier). Each is charged to the first task
    root whose sync chain reaches the call, else to the call's own activation."""
    out = []
    for w in facts.flows:
        key = (facts.unit.get(id(w), 0), w.src)
        if not is_halting(facts, w) or key not in fl.arriving or guarding_routes(facts, key, w):
            continue
        root = next((r for r in roots if key in sync_reach(facts, r)), key)
        out += [Escape(root, wire, node) for wire, node in halting_origins(facts, fl, raw, w)]
    return out


def sync_reach(facts: Facts, start: tuple) -> frozenset:
    """The activations a task started at `start` runs on its sync chain."""
    seen, stack = set(), [start]
    while stack:
        key = stack.pop()
        if key in seen:
            continue
        seen.add(key)
        stack += [callee_key(facts, x) for x in callee_wires(facts, *key)
                  if is_sync(x) and activates(facts, x)]
    return frozenset(seen)


def _guard_order(facts: Facts):
    order = facts.prog.order
    wires = {w.ident: w for w in facts.flows}

    def key(g):
        if g is not None and g[0] == "call" and g[1] in wires:
            return (1, order.get(id(wires[g[1]]), 0), str(g))
        return (0, 0, str(g))
    return key


def task_roots(facts: Facts, fl: Failures) -> list:
    """The activations that start a task: the document's entries and the targets
    of `~>`, `=>` and stream flows that some entry reaches."""
    prog, out = facts.prog, []
    for nid in prog.entries.get(0, ()):
        out.append((0, nid))
    for w in facts.flows:
        fed = w.kind in ("~>", "=>") or (facts.nodes.get(w.src) is not None
                                        and facts.nodes[w.src].is_stream and is_sync(w))
        key = callee_key(facts, w) if w.kind in ("~>", "=>") else None
        if fed and key is not None and key in fl.arriving and key not in out:
            out.append(key)
    return [k for k in out if k in fl.arriving]


class RawFailures:
    """Which arriving failures no route has chosen yet (memoised over the call
    graph; a cycle counts as handled, SGC151's question)."""

    def __init__(self, facts: Facts, fl: Failures):
        self.facts, self.fl = facts, fl
        self.wires = {w.ident: w for w in facts.flows}
        self.memo, self.busy = {}, set()

    def unrouted(self, key: tuple) -> list:
        """The raw guards arriving at `key` that select no route there."""
        if key in self.memo:
            return self.memo[key]
        if key in self.busy:
            return []
        self.busy.add(key)
        routes = self.fl.routes.get(key, ())
        sim = self.facts.sim
        out = [g for g in sorted(self.fl.arriving.get(key, ()), key=str)
               if self.raw(key, g) and not sim.selected_routes(routes, g)]
        self.busy.discard(key)
        self.memo[key] = out
        return out

    def raw(self, key: tuple, guard) -> bool:
        if guard is None:
            return True
        kind, what = guard
        if kind == "call":
            w = self.wires.get(what)
            return w is None or w.ident in self.fl.sources or (
                activates(self.facts, w) and bool(self.unrouted(callee_key(self.facts, w))))
        if kind == "node":
            return any(self.unrouted(k) for k in self.fl.arriving if k[1] == what)
        return any(self.raw(key, ("call", w.ident)) for w in self._in_block(key, what))

    def _in_block(self, key: tuple, bi: int) -> list:
        ui, nid = key
        return [w for w in self.facts.flows if self.facts.unit.get(id(w)) == ui
                and w.src == nid and bi in block_chain(self.facts, w) and not is_route(w)]

    def origins(self, key: tuple, guard, seen: frozenset = frozenset()) -> list:
        """(call wire or None, node) where a raw failure arriving at `key` with
        `guard` starts, following callees down to the calls that fail first."""
        if (key, guard) in seen:
            return []
        seen = seen | {(key, guard)}
        if guard is None:
            return [(None, key[1])]
        kind, what = guard
        if kind == "node":
            return [o for k in self.fl.arriving if k[1] == what
                    for g in self.unrouted(k) for o in self.origins(k, g, seen)]
        if kind == "block":
            return [o for w in self._in_block(key, what) if self.raw(key, ("call", w.ident))
                    for o in self.origins(key, ("call", w.ident), seen)]
        w = self.wires.get(what)
        if w is None:
            return []
        below = self.unrouted(callee_key(self.facts, w)) if activates(self.facts, w) else []
        if not below:
            return [(w, w.src)]
        callee = callee_key(self.facts, w)
        found = [o for g in below for o in self.origins(callee, g, seen)]
        return found or [(w, w.src)]            # a recursion: it starts here


def message_fed(facts: Facts, esc: Escape) -> bool:
    """Whether an escaping failure is a consumer's: its root is a stream (the call
    consumes a message) or a `~>` / `=>` delivers to it."""
    root = esc.root[1]
    n = facts.nodes.get(root)
    if n is not None and n.is_stream:
        return True
    return any(w.dst == root and w.kind in ("~>", "=>") for w in facts.flows)


# ---------------------------------------------------------------------------
# Hit helpers
# ---------------------------------------------------------------------------

def wire_anchor(w) -> tuple:
    return ("wire", w.ident)


def fmt_seconds(s: float) -> str:
    if s < 1:
        return f"{s * 1000:g}ms"
    return f"{s:g}s"


def first_line(facts: Facts, nid: str) -> int:
    return facts.lines.get(nid, 0)


# ---------------------------------------------------------------------------
# SGC101 unguarded-call
# ---------------------------------------------------------------------------

UNCOVERED = None                 # covered_callers: a delivery no deadline crosses


def covered_callers(facts: Facts) -> frozenset:
    """The nodes every sync call into which carries `@deadline` or comes from a
    covered caller (a greatest fixpoint; a node no sync call reaches is an entry,
    uncovered). An expansion's entries are called by its owner. Coverage stops at
    `~>`, `=>`, stream and spawn deliveries: an async task does not inherit its
    sender's deadline, so each counts as an UNCOVERED caller, whatever the sender's
    own coverage."""
    incoming = {}
    for nid, src, dl in deliveries(facts):
        incoming.setdefault(nid, []).append((src, dl))
    covered = set(incoming)
    changed = True
    while changed:
        changed = False
        for n in sorted(covered):
            if not all(dl or (src is not UNCOVERED and src in covered)
                       for src, dl in incoming[n]):
                covered.discard(n)
                changed = True
    return frozenset(covered)


def deliveries(facts: Facts) -> list:
    """(node, caller or UNCOVERED, carries @deadline) for every way work arrives at
    a node: sync calls from their caller; `~>`, `=>` and stream-fed flows (whose
    own `@deadline` still bounds what they start) and
    dynamic children (`\\-*`, `*-`) from UNCOVERED; an expansion's entries from
    its owner."""
    out = []
    for w in facts.flows:
        if is_route(w) or w.src == w.dst:
            continue
        src = facts.nodes.get(w.src)
        dl = has_mod(facts.scene.call_policy(w), "deadline")
        if w.kind in ("~>", "=>") or (src is not None and src.is_stream):
            out.append((w.dst, UNCOVERED, dl))
        elif is_sync(w):
            out.append((w.dst, w.src, dl))
    for g in _graphs(facts):
        out += [(t.node, UNCOVERED, False) for t in g.tree
                if (t.spawn or t.rel == "*") and t.parent is not None]
    prog = facts.prog
    for (_ui, owner), exp in sorted(prog.expansions.items(), key=str):
        out += [(e, owner, False) for e in prog.entries.get(exp, ())]
    return out


def unguarded_calls(facts: Facts) -> list:
    covered = covered_callers(facts)
    out = []
    for w in facts.flows:
        if not (is_sync(w) or (w.call is not None and w.call.self_call)):
            continue
        if not is_external(facts, w) or is_route(w):
            continue
        pol = facts.scene.call_policy(w)
        if has_mod(pol, "timeout") or has_mod(pol, "deadline") or w.src in covered:
            continue
        if has_mod(block_mods(facts, w), "deadline"):
            continue
        out.append(w)
    return out


def match_unguarded_call(ck, doc):
    facts = flow_facts(doc)
    joined = {id(m.wire): m.join for m in join_members(facts, strict=True)}
    for w in unguarded_calls(facts):
        yield unguarded_hit(ck, facts, w, joined.get(id(w)))


def unguarded_hit(ck, facts: Facts, w, join: Optional[str]):
    who = facts.name(w.src)
    where = f" inside {join}" if join else ""
    fix = (f"write `@timeout(t)` or `@deadline(t)` on the call, `}} @deadline(t)` on "
           f"a block around it, or a `@deadline` on every path into {who}")
    if is_op_call(w):
        what = call_name(facts, w)
        return ck.Hit(w.line, f"{who} calls {what} with no time bound{where}",
                      f"How long may {who} wait on {what}{where}?",
                      anchor=wire_anchor(w), fix=fix, scopes=(("call", w.ident),))
    dst = facts.name(w.dst)
    return ck.Hit(w.line, f"{who} waits on {dst} with no time bound{where}",
                  f"Is an unbounded wait on {dst} intended?", anchor=wire_anchor(w),
                  fix=fix, tier="advisory", scopes=(("call", w.ident),))


def unguarded_call_rule(ck):
    return ck.Rule(
        "SGC101", "unguarded-call", "binding",
        ask="How long may the caller wait on this external call?",
        why="An external call with no time bound can hang, and its caller hangs "
            "with it (Release It!, Timeouts).",
        fix="write `@timeout(t)` or `@deadline(t)` on the call",
        match=lambda doc: match_unguarded_call(ck, doc), family="10",
        satisfiers=(("call", "@timeout"), ("call", "@deadline"), ("owner", "@deadline"),
                    ("block", "@deadline")),
        implies=(("fanout-tail", "call"), ("held-across-call", "call")))


# ---------------------------------------------------------------------------
# SGC102 retry-amplification
# ---------------------------------------------------------------------------

class Amp(NamedTuple):
    product: int                     # attempts at the bottom of the worst path
    layers: int                      # retrying calls on it
    retries: int                     # the retry factor
    width: int                       # the fan-out factor
    bottom: object = None            # the last call on it


ONE = Amp(1, 0, 1, 1)


def amplification(facts: Facts, calls: dict, nid: str, memo: dict,
                  busy: frozenset = frozenset()) -> Optional[Amp]:
    """The worst attempts product below a node over the sync chain: None when a
    path is unknown (a symbolic N, a cycle); unknown paths are skipped."""
    if nid in memo:
        return memo[nid]
    if nid in busy:
        return None
    best = ONE
    for w in calls.get(nid, ()):
        a = call_amp(facts, calls, w, memo, busy | {nid})
        if a is not None and (a.product, a.layers) > (best.product, best.layers):
            best = a
    memo[nid] = best
    return best


def call_amp(facts: Facts, calls: dict, w, memo: dict, busy: frozenset) -> Optional[Amp]:
    arg = retry_arg(facts, w)
    tries = attempts_of(arg)
    card = w.edge.card if w.edge is not None else None
    width = int(card) if card and card.isdigit() else (1 if not card else None)
    if tries is None or width is None:
        return None
    below = amplification(facts, calls, w.dst, memo, busy)
    if below is None:
        return None
    return Amp(tries * width * below.product, below.layers + (arg is not None),
               tries * below.retries, width * below.width, below.bottom or w)


def amplified_calls(facts: Facts) -> list:
    """(call, Amp) for each outermost retrying call whose chain has two or more
    retry layers multiplying to at least AMPLIFICATION attempts."""
    calls = sync_calls(facts)
    retrying = [w for w in facts.flows if is_sync(w) and retry_arg(facts, w) is not None]
    below = reached_from(calls, [w.dst for w in retrying])
    memo, out = {}, []
    for w in retrying:
        if w.src in below:
            continue
        a = call_amp(facts, calls, w, memo, frozenset({w.src}))
        if a is not None and a.layers >= 2 and a.product >= AMPLIFICATION:
            out.append((w, a))
    return out


def reached_from(calls: dict, starts: list) -> frozenset:
    seen, stack = set(), list(starts)
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack += [w.dst for w in calls.get(n, ())]
    return frozenset(seen)


def match_retry_amplification(ck, doc):
    facts = flow_facts(doc)
    for w, a in amplified_calls(facts):
        if declared_on(facts, "retry-budget", w, w.src):
            continue
        bottom = call_name(facts, a.bottom)
        yield ck.Hit(
            w.line,
            f"{a.layers} layers retry: one call may become {a.product} attempts at "
            f"{bottom} (×{a.retries} retries, ×{a.width} width)",
            f"{a.layers} layers retry (×{a.product} attempts at {bottom}, ×{a.width} "
            f"width). Is there a retry budget?",
            anchor=wire_anchor(w),
            fix="declare `@inv retry-budget(p)` on this call (a `@deadline` limits "
                "time, not attempts)")


def retry_amplification_rule(ck):
    return ck.Rule(
        "SGC102", "retry-amplification", "advisory",
        ask="Several layers retry. Is there a retry budget?",
        why="Retries at several layers multiply during the very outage that "
            "caused them (SRE book ch. 22).",
        fix="declare `@inv retry-budget(p)` on the outermost retrying call",
        match=lambda doc: match_retry_amplification(ck, doc), family="10",
        satisfiers=(("call", "retry-budget"), ("owner", "retry-budget")))


# ---------------------------------------------------------------------------
# SGC103 timeout-budget-inverted
# ---------------------------------------------------------------------------

def total(values) -> Optional[float]:
    values = list(values)
    return None if any(v is None for v in values) else sum(values)


def worst(values) -> Optional[float]:
    values = list(values)
    if any(v is None for v in values):
        return None
    return max(values, default=0.0)


class Durations:
    """The worst-case duration of a node's work (catalog SGC103's algebra):
    sequence sums, joins and races take the max, a loop multiplies by `@times`;
    `~>`, `=>` and routes add nothing. None: unknown (an unbounded external call,
    a symbolic `×N`, a cycle, an unparsed duration)."""

    def __init__(self, facts: Facts):
        self.facts = facts
        self.memo, self.busy = {}, set()

    def node(self, ui: int, nid: str) -> Optional[float]:
        key = (ui, nid)
        if key in self.memo:
            return self.memo[key]
        if key in self.busy:
            return None
        self.busy.add(key)
        prog = self.facts.prog
        parts = [self.items(prog.bodies.get(key, ()))]
        exp = prog.expansions.get(key)
        if exp is not None:
            parts += [self.node(exp, e) for e in prog.entries.get(exp, ())]
        self.busy.discard(key)
        self.memo[key] = total(parts)
        return self.memo[key]

    def items(self, items) -> Optional[float]:
        return total(self.item(it) for it in items)

    def item(self, it) -> Optional[float]:
        sim = self.facts.sim
        if isinstance(it, sim.Step):
            return self.step(it.wire)
        if isinstance(it, sim.Group):
            if it.wires[0].kind == "~>":
                return 0.0
            return worst(self.step(w) for w in it.wires)
        return self.region(it)

    def region(self, r) -> Optional[float]:
        """The block's body, cut to the block's own `} @deadline(t)` (a deadline
        over every member, language.md)."""
        mods = dict((n, a) for n, a in r.block.modifiers)
        body = self.body(r, mods)
        cap = self.facts.sim.duration(mods["deadline"]) if "deadline" in mods else None
        if cap is None:
            return body
        return cap if body is None else min(body, cap)

    def body(self, r, mods: dict) -> Optional[float]:
        if r.block.kind == "loop":
            times = (mods.get("times") or "").strip()
            body = self.items(r.items)
            return None if not times.isdigit() or body is None else int(times) * body
        if r.block.kind == "parallel":
            return 0.0 if "none" in mods else worst(self.item(it) for it in r.items)
        return self.items(r.items)

    def step(self, w) -> Optional[float]:
        if w.kind in ("~>", "=>") or is_route(w):
            return 0.0
        return self.call(w)

    def call(self, w) -> Optional[float]:
        """attempts × (the timeout, else the callee's work) + the waits between
        attempts, cut to the deadline."""
        facts, sim = self.facts, self.facts.sim
        pol = facts.scene.call_policy(w)
        tries = attempts_of(retry_arg(facts, w))
        timeout, deadline = mod_arg(pol, "timeout"), mod_arg(pol, "deadline")
        if tries is None or (timeout is not None and sim.duration(timeout) is None):
            return None
        per = sim.duration(timeout) if timeout is not None else self.callee(w)
        after = sim.duration(mod_arg(pol, "after")) or 0.0
        spent = None if per is None else tries * per + (tries - 1) * after
        cap = sim.duration(deadline) if deadline is not None else None
        if cap is None:
            return spent
        return cap if spent is None else min(spent, cap)

    def callee(self, w) -> Optional[float]:
        facts = self.facts
        if is_external(facts, w) or facts.kind(w.dst) == "actor":
            return None
        if w.src == w.dst:
            return 0.0
        return self.node(*callee_key(facts, w))


def inverted_budgets(facts: Facts) -> list:
    """(call, its bound in seconds, the callee's worst case) where the callee may
    take longer than the call waits."""
    durations, sim, out = Durations(facts), facts.sim, []
    for w in facts.flows:
        if not is_sync(w) or is_external(facts, w) or facts.kind(w.dst) in NOT_CALLEES:
            continue
        pol = facts.scene.call_policy(w)
        bound = sim.duration(mod_arg(pol, "timeout")) or sim.duration(mod_arg(pol, "deadline"))
        if not bound:
            continue
        inner = durations.node(*callee_key(facts, w))
        if inner is not None and inner > bound:
            out.append((w, bound, inner))
    return out


def match_timeout_budget(ck, doc):
    facts = flow_facts(doc)
    for w, bound, inner in inverted_budgets(facts):
        who, dst = facts.name(w.src), facts.name(w.dst)
        b, i = fmt_seconds(bound), fmt_seconds(inner)
        yield ck.Hit(w.line, f"{who} waits {b} on {dst}, whose work may take {i}",
                     f"{who} waits {b} but {dst} may take {i}. Which bound wins?",
                     anchor=wire_anchor(w),
                     fix=f"make the numbers agree, or put a `@deadline` of at most {b} "
                         f"on the calls below {dst}")


def timeout_budget_rule(ck):
    return ck.Rule(
        "SGC103", "timeout-budget-inverted", "binding",
        ask="The caller gives up before the work below it can finish. Which bound wins?",
        why="An outer timeout shorter than the inner chain's worst case leaves work "
            "running after its caller gave up (deadline propagation).",
        fix="consistent numbers, or an inner `@deadline` within the outer budget",
        match=lambda doc: match_timeout_budget(ck, doc), family="10",
        satisfiers=(("call", "@deadline"), ("call", "@timeout")))


# ---------------------------------------------------------------------------
# SGC104 retry-without-backoff
# ---------------------------------------------------------------------------

def match_retry_without_backoff(ck, doc):
    facts = flow_facts(doc)
    for w in facts.flows:
        if is_route(w) or not is_external(facts, w):
            continue
        arg = retry_arg(facts, w)
        if arg is None or has_mod(facts.scene.call_policy(w), "after"):
            continue
        what = call_name(facts, w)
        yield ck.Hit(w.line, f"{what} is retried ×{arg} with no backoff",
                     f"{what} retries ×{arg} at once. What schedule?",
                     anchor=wire_anchor(w),
                     fix="write `@after(…)` (`@after(0)` for a deliberate immediate retry)")


def retry_without_backoff_rule(ck):
    return ck.Rule(
        "SGC104", "retry-without-backoff", "advisory",
        ask="This external call retries at once. What schedule?",
        why="Immediate retries synchronise clients into a thundering herd against a "
            "recovering dependency (backoff with jitter).",
        fix="write `@after(…)` on the call", family="10",
        match=lambda doc: match_retry_without_backoff(ck, doc),
        satisfiers=(("call", "@after"),))


# ---------------------------------------------------------------------------
# SGC111 retry-without-idempotency
# ---------------------------------------------------------------------------

def match_retry_without_idempotency(ck, doc):
    facts = flow_facts(doc)
    for w in facts.flows:
        if is_route(w) or not is_sync(w) and not (w.call and w.call.self_call):
            continue
        arg = retry_arg(facts, w)
        if arg is None or is_value_assignment(facts, w):
            continue
        eff = effect_of(facts, w)
        if eff is None or declared_on(facts, "idempotent", w, *effect_owners(w, eff)):
            continue
        what = call_name(facts, w)
        yield ck.Hit(w.line, f"{what} is retried ×{arg} and {eff.what}",
                     f"{what} is retried ×{arg}. Is it idempotent, and on what key?",
                     anchor=wire_anchor(w), guess=eff.guess,
                     fix="declare `@inv idempotent(key)` on the call, the callee or "
                         "the store")


def retry_without_idempotency_rule(ck):
    return ck.Rule(
        "SGC111", "retry-without-idempotency", "binding",
        ask="This call is retried and changes state. Is it idempotent, and on what key?",
        why="A retried write whose first attempt succeeded (and whose reply was "
            "lost) is applied twice (Helland, idempotence).",
        fix="declare `@inv idempotent(key)`", family="11",
        match=lambda doc: match_retry_without_idempotency(ck, doc),
        satisfiers=(("call", "idempotent"), ("callee", "idempotent"),
                    ("store", "idempotent"), ("block", "idempotent")),
        guess=("access-verb", "no-body"))


# ---------------------------------------------------------------------------
# SGC112 duplicate-delivery
# ---------------------------------------------------------------------------

def is_message(n) -> bool:
    return n is not None and (n.kind == "event" or (n.kind == "data" and n.is_stream))


def loc(facts: Facts, nid: str) -> Optional[str]:
    return mod_arg(facts.mods.get(nid, []), "loc")


def crosses_boundary(facts: Facts, event: str, w) -> bool:
    """A stream; emitter and consumer at different `@loc`; or a consumer with
    instances."""
    if facts.nodes[event].is_stream:
        return True
    there = loc(facts, w.dst)
    emitters = [x.src for x in facts.flows if x.dst == event]
    if there and any(loc(facts, e) and loc(facts, e) != there for e in emitters):
        return True
    return instances(facts, w.dst) or bool(w.edge is not None and w.edge.card)


def consumer_effect(facts: Facts, w) -> Optional[Effect]:
    """The first state change in the consumer's own body: a store write or an
    external call. None when it makes none, or is only a stage re-emitting into
    another stream."""
    body = [x for x in callee_wires(facts, facts.unit.get(id(w), 0), w.dst)
            if not is_route(x)]
    if body and all(facts.nodes.get(x.dst) is not None and facts.nodes[x.dst].is_stream
                    and facts.kind(x.dst) != "store" for x in body):
        return None
    for x in body:
        eff = store_effect(facts, x) if facts.kind(x.dst) == "store" else None
        if eff is None and is_op_call(x):
            eff = Effect(f"calls {call_name(facts, x)}, which leaves the system")
        if eff is not None:
            return eff
    return None


class Delivery(NamedTuple):
    event: str                       # the message node id
    wire: object                     # the delivering wire
    guess: str                       # what the consumer's state change was guessed on


def duplicate_deliveries(facts: Facts) -> list:
    """The Delivery of each boundary-crossing message whose consumer changes state
    and declares no dedup."""
    out = []
    for w in facts.flows:
        n = facts.nodes.get(w.src)
        if not is_message(n) or is_route(w) or facts.kind(w.dst) in NOT_CALLEES:
            continue
        if not crosses_boundary(facts, w.src, w):
            continue
        eff = consumer_effect(facts, w)
        if eff is None:
            continue
        if ("idempotent" in heads(facts, facts.mods.get(w.dst, []))
                or "dedup" in heads(facts, facts.mods.get(w.src, []))):
            continue
        out.append(Delivery(w.src, w, eff.guess))
    return out


def bare_self_loop(facts: Facts, t, tw) -> bool:
    """`S -<T>-> S` with nothing on it: it changes no state, so it is how a design
    says a duplicate is ignored on purpose (NG7)."""
    if t.src != t.dst or tw is None:
        return False
    return not (facts.scene.call_policy(tw) or tw.payload)


def refiring_machines(facts: Facts) -> list:
    """(event id, owner, line) where a boundary-crossing event drives a machine
    that re-fires on a duplicate: a `_` transition on it, or a self-loop that
    carries modifiers or an effect (a bare self-loop is the NG7 ignore)."""
    out = []
    wires = {w.ident: w for w in facts.prog.scene.wires}
    for event, refs in facts.prog.triggers.items():
        n = facts.nodes.get(event)
        if n is None or not n.is_stream or "dedup" in heads(facts, facts.mods.get(event, [])):
            continue
        for ref in refs:
            t = ref.trigger
            src = facts.nodes.get(t.src)
            wildcard = src is not None and src.attrs.get("pseudo") == "any"
            tw = wires.get(ref.transition)
            refires = wildcard or (t.src == t.dst and not bare_self_loop(facts, t, tw))
            if refires and "idempotent" not in heads(facts, facts.mods.get(t.owner, [])):
                out.append((event, t.owner, tw.line if tw else first_line(facts, t.owner)))
    return out


def match_duplicate_delivery(ck, doc):
    facts = flow_facts(doc)
    fix = "declare `@inv idempotent(key)` on the consumer or `@inv dedup(key)` on the event"
    for d in duplicate_deliveries(facts):
        w = d.wire
        ev, who = facts.name(d.event), facts.name(w.dst)
        yield ck.Hit(w.line, f"{ev} may arrive twice and {who} changes state on it",
                     f"{ev} may arrive twice. Does {who} dedupe?",
                     anchor=wire_anchor(w), fix=fix, guess=d.guess)
    for event, owner, line in refiring_machines(facts):
        ev, who = facts.name(event), facts.name(owner)
        yield ck.Hit(line, f"{ev} may arrive twice and re-fires a transition of {who}",
                     f"{ev} may arrive twice. Should {who} take it again?",
                     anchor=("machine", owner), fix=fix)


def duplicate_delivery_rule(ck):
    return ck.Rule(
        "SGC112", "duplicate-delivery", "advisory",
        ask="This message may arrive twice. Does its consumer dedupe?",
        why="Async delivery is at-least-once, so a stateful consumer sees duplicates "
            "(exactly-once = at-least-once + idempotence).",
        fix="declare `@inv idempotent(key)` or `@inv dedup(key)`", family="11",
        match=lambda doc: match_duplicate_delivery(ck, doc),
        satisfiers=(("callee", "idempotent"), ("callee", "dedup")),
        guess=("access-verb",))


# ---------------------------------------------------------------------------
# SGC113 dual-write
# ---------------------------------------------------------------------------

def known_write(facts: Facts, w) -> bool:
    return facts.kind(w.dst) == "store" and facts.access(w) in ("write", "rw")


def durable_write(facts: Facts, w) -> bool:
    """A known write to a store that is not a mutable slot (`~|S|` holds
    in-process state, not a durable record)."""
    n = facts.nodes.get(w.dst)
    return known_write(facts, w) and n is not None and not n.is_mutable


def consequential_emit(facts: Facts, w) -> bool:
    """An emit whose event drives a machine or reaches another store write."""
    if facts.kind(w.dst) != "event" or is_route(w):
        return False
    if w.dst in facts.prog.triggers:
        return True
    for x in facts.flows:
        if x.src != w.dst or is_route(x):
            continue
        if durable_write(facts, x):
            return True
        body = callee_wires(facts, facts.unit.get(id(x), 0), x.dst)
        if any(durable_write(facts, y) for y in body):
            return True
    return False


class DualWrite(NamedTuple):
    key: tuple                       # (ui, node) of the activation
    effects: list                    # its effect wires, in written order
    guess: str                       # the first write's guessed access ("" exact)


def dual_writes(facts: Facts) -> list:
    """The DualWrite of each activation whose own body makes two durable effects
    with no atomicity stated."""
    out = []
    for key, items in facts.prog.bodies.items():
        body = facts.sim._flat(items)
        writes = [w for w in body if durable_write(facts, w)]
        emits = [w for w in body if consequential_emit(facts, w)]
        stores = list(dict.fromkeys(w.dst for w in writes))
        if len(stores) < 2 and not (writes and emits):
            continue
        effects = writes + emits
        if any(declared_on(facts, "atomic", w, key[1]) for w in effects):
            continue
        if compensated(facts, key, {w.dst for w in effects}):
            continue
        ordered = sorted(effects, key=lambda w: facts.prog.order[id(w)])
        out.append(DualWrite(key, ordered, write_guess(facts, ordered)))
    return out


def write_guess(facts: Facts, effects: list) -> str:
    """The first guess among the store writes' access (access_mode steps 4–5)."""
    for w in effects:
        eff = store_effect(facts, w) if facts.kind(w.dst) == "store" else None
        if eff is not None and eff.guess:
            return eff.guess
    return ""


def compensated(facts: Facts, key: tuple, targets: set) -> bool:
    """A live route of the activation names one of the effects' targets (a route
    no failure reaches compensates nothing: SGC202 would report it)."""
    fl = failures_of(facts)
    return any(r.dst in targets and route_live(facts, fl, key, r, g)
               for r, g in facts.prog.routes.get(key, ()))


def match_dual_write(ck, doc):
    facts = flow_facts(doc)
    for dw in dual_writes(facts):
        nid, effects = dw.key[1], dw.effects
        who = facts.name(nid)
        names = " and ".join(dict.fromkeys(
            ("writes " if facts.kind(w.dst) == "store" else "emits ") + facts.name(w.dst)
            for w in effects))
        yield ck.Hit(effects[0].line, f"{who} {names} without atomicity",
                     f"{who} {names}. What happens if it stops in between?",
                     anchor=("node", nid), fix=dual_write_fix(facts, nid, effects),
                     guess=dw.guess)


def dual_write_fix(facts: Facts, nid: str, effects: list) -> str:
    """Declarations only (the rule never asks for a rewiring). Two stores:
    atomicity or a compensating `!>` under the second write (a request, so the
    route is live). A write and an emit: an emit cannot fail, so a route under it
    is dead; atomicity alone."""
    who = facts.name(nid)
    targets = list(dict.fromkeys(facts.label(w.dst) for w in effects))
    atomic = f"declare `@inv atomic({', '.join(targets)})` on {who}"
    if all(facts.kind(w.dst) == "store" for w in effects):
        return f"{atomic}, or a compensating `!>` under the second write"
    return atomic


def dual_write_rule(ck):
    return ck.Rule(
        "SGC113", "dual-write", "advisory",
        ask="One activation makes two durable effects. What if it stops in between?",
        why="Two effects without atomicity disagree for good after a crash between "
            "them (transactional messaging, change data capture).",
        fix="declare `@inv atomic(…)`, or (two stores) a compensating `!>`",
        family="11", match=lambda doc: match_dual_write(ck, doc),
        satisfiers=(("callee", "atomic"), ("block", "atomic"), ("call", "!>")),
        guess=("access-verb",))


# ---------------------------------------------------------------------------
# SGC114 poison-message and SGC201 unhandled-failure
# ---------------------------------------------------------------------------

def escape_hit(ck, facts: Facts, esc: Escape, **extra):
    """The Hit both SGC114 and SGC201 report for one escaping failure, anchored on
    the call where it starts (else the failing node), so one folds the other."""
    root = facts.name(esc.root[1])
    if esc.origin is not None:
        what, at = call_name(facts, esc.origin), facts.name(esc.origin.src)
        line, anchor = esc.origin.line, wire_anchor(esc.origin)
    else:
        what = at = facts.name(esc.node)
        line, anchor = first_line(facts, esc.node), ("node", esc.node)
    return ck.Hit(line, f"if {what} fails, nothing on the way to {root} says what happens",
                  f"If {what} fails, what does {at} do?", anchor=anchor, **extra)


def match_unhandled_failure(ck, doc):
    facts = flow_facts(doc)
    fl = failures_of(facts)
    for esc in escapes(facts, fl):
        if message_fed(facts, esc) and overflow_stated(facts, esc):
            continue                    # SGC114's, and its overflow policy says
        yield escape_hit(ck, facts, esc,
                         fix="route the failure with `!>` somewhere on the chain (one "
                             "`!> (Caller) : <Failed>` at the entry covers it), or "
                             "declare `@fallback`")


def unhandled_failure_rule(ck):
    return ck.Rule(
        "SGC201", "unhandled-failure", "binding",
        ask="If this fails, what happens?",
        why="A failure that unwinds to an entry with no route reaches the user as a "
            "raw error (fail fast under a supervisor: the route).",
        fix="a `!>` on the chain, or `@fallback`", family="20",
        match=lambda doc: match_unhandled_failure(ck, doc),
        satisfiers=(("call", "!>"), ("call", "@fallback")))


def match_poison_message(ck, doc):
    facts = flow_facts(doc)
    fl = failures_of(facts)
    for esc in escapes(facts, fl):
        if not message_fed(facts, esc) or overflow_stated(facts, esc):
            continue
        retried = any(retry_arg(facts, w) is not None
                      for w in [esc.origin] + feeding_wires(facts, esc) if w is not None)
        yield escape_hit(ck, facts, esc, tier="" if retried else "advisory",
                         fix="route it: `!> |DLQ|`, a `@fallback`, or an overflow "
                             "policy upstream (`^N@drop`, `^N@err`)")


def feeding_wires(facts: Facts, esc: Escape) -> list:
    """The deliveries that hand an escaping failure's root its message: the flows
    out of the root when it is a stream, else the stream, `~>` and `=>` flows
    into it."""
    root = esc.root[1]
    n = facts.nodes.get(root)
    if n is not None and n.is_stream:
        return [w for w in facts.flows if w.src == root and not is_route(w)]
    return [w for w in facts.flows if w.dst == root and not is_route(w) and (
        w.kind in ("~>", "=>") or (facts.nodes.get(w.src) is not None
                                   and facts.nodes[w.src].is_stream))]


def overflow_stated(facts: Facts, esc: Escape) -> bool:
    """A stream feeding the escape's root carries an overflow policy (`^N@drop`,
    `^N@latest`, `^N@err`, on any occurrence): catalog SGC114 counts it as the
    stated handling."""
    streams = {w.src for w in feeding_wires(facts, esc)}
    if facts.nodes.get(esc.root[1]) is not None and facts.nodes[esc.root[1]].is_stream:
        streams.add(esc.root[1])
    return any("@" in (mod_arg(facts.mods.get(s, []), "^") or "") for s in streams)


def poison_message_rule(ck):
    return ck.Rule(
        "SGC114", "poison-message", "binding",
        ask="What happens to a message that always fails?",
        why="A consumer that fails on one message retries it forever and blocks the "
            "queue behind it (dead letter channel).",
        fix="`!> |DLQ|`, a `@fallback`, or an overflow policy", family="11",
        match=lambda doc: match_poison_message(ck, doc),
        satisfiers=(("call", "!>"), ("call", "@fallback"), ("store", "^")),
        implies=(("unhandled-failure", "wire"), ("unhandled-failure", "node")))


# ---------------------------------------------------------------------------
# SGC121 saga-uncompensated
# ---------------------------------------------------------------------------

def guarding_routes(facts: Facts, key: tuple, w) -> list:
    """The routes of activation `key` that a failure of w may take: guarded by
    w's call or an enclosing block, or the node's unguarded ones."""
    chain = block_chain(facts, w)
    out = []
    for r, g in facts.prog.routes.get(key, ()):
        if g is None or guarded_by(g, ("call", w.ident)) or (
                g[0] == "block" and g[1] in chain):
            out.append(r)
    return out


def durable(facts: Facts, nid: str) -> bool:
    n = facts.nodes.get(nid)
    return n is not None and n.is_stream


def forward_recovery(facts: Facts, key: tuple, w) -> bool:
    """The failing step is driven to success: a `@fallback`, a durable retry route,
    or a retry declared idempotent."""
    pol = facts.scene.call_policy(w)
    if has_mod(pol, "fallback"):
        return True
    if any(durable(facts, r.dst) for r in guarding_routes(facts, key, w)):
        return True
    return retry_arg(facts, w) is not None and declared_on(facts, "idempotent", w, w.dst)


def is_pivot(facts: Facts, key: tuple, w) -> bool:
    """An external op call no route compensates: nothing after it can be undone."""
    return is_op_call(w) and not any(
        r.dst == w.dst for r in guarding_routes(facts, key, w))


class SagaStep(NamedTuple):
    wire: object
    effect: Effect


def saga_gaps(facts: Facts) -> list:
    """(failing step, [earlier effectful steps left], after a pivot) for each step
    that can fail after effects that nothing undoes or drives forward."""
    fl, out = failures_of(facts), []
    for key, items in facts.prog.bodies.items():
        steps = [SagaStep(w, e) for w in facts.sim._flat(items)
                 if is_sync(w) and not is_route(w)
                 for e in [effect_of(facts, w)] if e is not None]
        siblings = concurrent_members(facts, items)
        for j, w in enumerate(facts.sim._flat(items)):
            if not is_sync(w) or is_route(w) or not fails_itself(facts, fl, w):
                continue
            earlier = [s for s in steps if s.wire is not w and (
                facts.prog.order[id(s.wire)] < facts.prog.order[id(w)]
                or id(s.wire) in siblings.get(id(w), ()))]
            gap = saga_gap(facts, key, w, earlier)
            if gap is not None:
                out.append(gap)
    return out


def concurrent_members(facts: Facts, items) -> dict:
    """{id(member wire): ids of its sibling members} for the strict joins of a body."""
    out = {}
    groups = [[m.wire for m in _members(facts.sim, (it,), True)] for it in items]
    for ws in groups:
        for w in ws:
            out[id(w)] = frozenset(id(x) for x in ws if x is not w)
    return out


def saga_gap(facts: Facts, key: tuple, w, earlier: list):
    if not earlier or forward_recovery(facts, key, w):
        return None
    if declared_on(facts, "atomic", w, key[1]):
        return None
    pivot = any(is_pivot(facts, key, s.wire) for s in earlier)
    if pivot:
        return (w, earlier, True)
    named = {r.dst for r in guarding_routes(facts, key, w)}
    left = [s for s in earlier if s.wire.dst not in named]
    return (w, left, False) if left else None


def match_saga_uncompensated(ck, doc):
    facts = flow_facts(doc)
    for w, left, pivot in saga_gaps(facts):
        what = call_name(facts, w)
        done = " and ".join(dict.fromkeys(call_name(facts, s.wire) for s in left))
        guess = next((s.effect.guess for s in left if s.effect.guess), "")
        if pivot:
            stmt = (f"{what} can fail after a step that cannot be undone, and nothing "
                    f"drives it to success")
            ask = f"If {what} fails after {done}, what drives {what} to success?"
            fix = "`×N` with `@inv idempotent(key)`, a durable `!> *|Retry|`, or `@fallback`"
        else:
            stmt = f"{what} can fail after {done}, and nothing undoes {done}"
            ask = f"If {what} fails, what undoes {done}, or what drives {what} to success?"
            fix = (f"a `!>` naming {', '.join(facts.name(s.wire.dst) for s in left)}, a "
                   f"`@fallback` or durable retry route, or `@inv atomic(…)`")
        yield ck.Hit(w.line, stmt, ask, anchor=wire_anchor(w), guess=guess, fix=fix)


def saga_uncompensated_rule(ck):
    return ck.Rule(
        "SGC121", "saga-uncompensated", "advisory",
        ask="If this step fails, what undoes the earlier ones, or what drives it to "
            "success?",
        why="A committed step stays when a later step fails: leaked holds, drift "
            "(sagas: compensate backward or recover forward).",
        fix="a `!>` naming the earlier target, `@fallback`, or `@inv atomic(…)`",
        family="12", match=lambda doc: match_saga_uncompensated(ck, doc),
        satisfiers=(("call", "!>"), ("call", "@fallback"), ("callee", "atomic"),
                    ("block", "atomic")),
        guess=("access-verb", "no-body"))


# ---------------------------------------------------------------------------
# SGC122 fragile-compensation
# ---------------------------------------------------------------------------

def fragile_routes(facts: Facts) -> list:
    """Route wires that call an effectful target with no retry, no idempotency
    and no durable destination."""
    out = []
    for w in facts.flows:
        if not is_route(w) or facts.kind(w.dst) in ("event", "actor", "data"):
            continue
        eff = effect_of(facts, w) if has_payload(w) else None
        if eff is None:
            continue
        if (retry_arg(facts, w) is not None or durable(facts, w.dst)
                or declared_on(facts, "idempotent", w, *effect_owners(w, eff))):
            continue
        out.append(w)
    return out


def match_fragile_compensation(ck, doc):
    facts = flow_facts(doc)
    for w in fragile_routes(facts):
        what = call_name(facts, w)
        yield ck.Hit(w.line, f"the compensation {what} is never retried if it fails",
                     f"What if {what} itself fails?", anchor=wire_anchor(w),
                     fix="`×N` (then SGC111 asks for idempotency), "
                         "`@inv idempotent(key)`, or a durable `!> *|Retry|`")


def fragile_compensation_rule(ck):
    return ck.Rule(
        "SGC122", "fragile-compensation", "advisory",
        ask="What if the compensation itself fails?",
        why="A compensation that fails once leaves the saga half-undone; it must "
            "eventually succeed (retryable and idempotent).",
        fix="`×N`, `@inv idempotent(key)`, or a durable route", family="12",
        match=lambda doc: match_fragile_compensation(ck, doc),
        satisfiers=(("call", "×"), ("call", "idempotent"), ("callee", "idempotent")))


# ---------------------------------------------------------------------------
# SGC123 race-loser-effects
# ---------------------------------------------------------------------------

def match_race_loser_effects(ck, doc):
    facts = flow_facts(doc)
    for m in join_members(facts, strict=False):
        w = m.wire
        eff = effect_of(facts, w)
        if eff is None or declared_on(facts, "idempotent", w, *effect_owners(w, eff)):
            continue
        key = (facts.unit.get(id(w), 0), w.src)
        if any(r.dst == w.dst for r, _g in facts.prog.routes.get(key, ())):
            continue
        what, dst = call_name(facts, w), facts.name(w.dst)
        yield ck.Hit(w.line, f"{what} on {dst} is in {m.join}, and a losing {dst} "
                             f"may already have acted ({eff.what})",
                     f"{what} races {dst}. What undoes the loser's effect?",
                     anchor=wire_anchor(w), guess=eff.guess,
                     fix=f"declare `@inv idempotent(key)` on {dst}, or a route that "
                         f"compensates it")


def race_loser_effects_rule(ck):
    return ck.Rule(
        "SGC123", "race-loser-effects", "binding",
        ask="A race cancels its losers. What undoes a loser's effect?",
        why="Cancelling a hedged request does not undo what the loser already did "
            "(The Tail at Scale).",
        fix="idempotent or read-only members, or a compensation route", family="12",
        match=lambda doc: match_race_loser_effects(ck, doc),
        satisfiers=(("callee", "idempotent"), ("call", "!>")),
        guess=("access-verb", "no-body"))


# ---------------------------------------------------------------------------
# SGC161 unbounded-buffer
# ---------------------------------------------------------------------------

def bounded(facts: Facts, nid: str) -> bool:
    return has_mod(facts.mods.get(nid, []), "^")


def has_reader(facts: Facts, store: str) -> bool:
    """A flow out of the store, a read into it, or a declared `@read`."""
    for w in facts.prog.scene.wires:
        if w.role != "flow":
            continue
        if w.src == store and not is_route(w):
            return True
        if w.dst == store and facts.access(w) in ("read", "rw"):
            return True
    return any(a.store == store and a.mode == "read"
               for g in _graphs(facts) for a in getattr(g, "access", None) or [])


def unbounded_streams(facts: Facts) -> list:
    return [nid for nid, n in facts.nodes.items()
            if n.is_stream and n.kind in ("event", "data") and not bounded(facts, nid)]


def unbounded_stores(facts: Facts) -> list:
    """Accumulators and dead-letter stores (route targets) with no reader and no
    `@inv retention(…)`."""
    targets = {w.dst for w in facts.flows if is_route(w)}
    out = []
    for nid, n in facts.nodes.items():
        if n.kind != "store" or not (n.is_stream or nid in targets):
            continue
        if "retention" in heads(facts, facts.mods.get(nid, [])) or has_reader(facts, nid):
            continue
        out.append(nid)
    return out


def implicit_queues(facts: Facts) -> list:
    """`~>` sends into a consumer that retries, calls out or has instances, with
    no stream between and no `@sla` on the consumer."""
    out = []
    for w in facts.flows:
        if w.kind != "~>" or facts.kind(w.dst) in NOT_CALLEES:
            continue
        if has_mod(facts.mods.get(w.dst, []), "sla"):
            continue
        body = callee_wires(facts, facts.unit.get(id(w), 0), w.dst)
        busy = any(retry_arg(facts, x) is not None or is_op_call(x) for x in body)
        if busy or instances(facts, w.dst) or (w.edge is not None and w.edge.card):
            out.append(w)
    return out


def match_unbounded_buffer(ck, doc):
    facts = flow_facts(doc)
    for nid in unbounded_streams(facts):
        s = facts.name(nid)
        yield ck.Hit(first_line(facts, nid), f"{s} is unbounded",
                     f"{s} is unbounded. Is that intended, and what drains it?",
                     anchor=("node", nid), scopes=(("store", nid),),
                     fix=f"bound it: `{facts.label(nid)}^N@policy` on any occurrence")
    for nid in unbounded_stores(facts):
        s = facts.name(nid)
        yield ck.Hit(first_line(facts, nid), f"{s} only grows: nothing reads it and no "
                                             f"retention is stated",
                     f"What reads {s}, and how long is it kept?",
                     anchor=("node", nid), scopes=(("store", nid),),
                     fix="declare `@inv retention(t)` on it, or a reader")
    for w in implicit_queues(facts):
        dst = facts.name(w.dst)
        yield ck.Hit(w.line, f"messages to {dst} queue up with no bound",
                     f"How many messages may wait for {dst}?", anchor=wire_anchor(w),
                     tier="hint", fix=f"a bounded stream before {dst}, or `@sla` on it")


def unbounded_buffer_rule(ck):
    return ck.Rule(
        "SGC161", "unbounded-buffer", "advisory",
        ask="This grows without a stated bound. Is that intended?",
        why="An unbounded queue or store grows until memory runs out, and latency "
            "with it (back-pressure; Little's law).",
        fix="`^N@policy`, `@inv retention(t)`, a reader, or a bounded stream",
        family="16", match=lambda doc: match_unbounded_buffer(ck, doc),
        satisfiers=(("store", "^"), ("store", "retention"), ("callee", "@sla")),
        implies=(("unreached", "store"),))


# ---------------------------------------------------------------------------
# SGC162 unbounded-result
# ---------------------------------------------------------------------------

def collection(text: Optional[str]) -> bool:
    t = (text or "").strip()
    return "List<" in t or t.startswith("*{")


def unbounded_results(facts: Facts) -> list:
    """Store reads whose value is a collection, with no `@inv limit(N)` (or `^N`
    on a stream result)."""
    out = []
    for w in facts.flows:
        if facts.kind(w.dst) != "store" or facts.access(w) != "read":
            continue
        result = facts.sim.returned(w) or ""
        if not collection(result) or declared_on(facts, "limit", w, w.dst):
            continue
        if result.strip().startswith("*{") and "^" in result:
            continue
        out.append((w, result.strip()))
    return out


def match_unbounded_result(ck, doc):
    facts = flow_facts(doc)
    for w, result in unbounded_results(facts):
        what = call_name(facts, w)
        yield ck.Hit(w.line, f"{what} returns `{result}` with no bound",
                     f"{what} returns every row. How many rows can come back?",
                     anchor=wire_anchor(w),
                     fix="declare `@inv limit(N)` (a page size counts)")


def unbounded_result_rule(ck):
    return ck.Rule(
        "SGC162", "unbounded-result", "advisory",
        ask="This read returns every row. How many can come back?",
        why="A query that returns every row works in tests and falls over in "
            "production (Unbounded Result Sets).",
        fix="declare `@inv limit(N)`", family="16",
        match=lambda doc: match_unbounded_result(ck, doc),
        satisfiers=(("call", "limit"),))


# ---------------------------------------------------------------------------
# SGC163 capacity-mismatch
# ---------------------------------------------------------------------------

def fronted(facts: Facts, nid: str) -> bool:
    """`@sla` on it, or a bounded stream in front of it."""
    if has_mod(facts.mods.get(nid, []), "sla"):
        return True
    return any(w.dst == nid and facts.nodes.get(w.src) is not None
               and facts.nodes[w.src].is_stream for w in facts.flows)


def capacity_mismatches(facts: Facts) -> list:
    """(callee, the first call into it from many callers) per fixed callee."""
    out, seen = [], set()
    for w in facts.flows:
        if w.kind not in CALL_KINDS or w.src == w.dst or w.dst in seen:
            continue
        if facts.kind(w.dst) in NOT_CALLEES or instances(facts, w.dst):
            continue
        many = facts.kind(w.src) == "actor" or instances(facts, w.src)
        if not many or fronted(facts, w.dst):
            continue
        seen.add(w.dst)
        out.append((w.dst, w))
    return out


def match_capacity_mismatch(ck, doc):
    facts = flow_facts(doc)
    for nid, w in capacity_mismatches(facts):
        src, dst = facts.name(w.src), facts.name(w.dst)
        many = ("requests from" if facts.kind(w.src) == "actor"
                else "every instance of")
        yield ck.Hit(w.line, f"{many} {src} reach one {dst}, whose capacity is not stated",
                     f"{src} may send many requests to one {dst}. What load can {dst} "
                     f"take?", anchor=("node", nid),
                     fix=f"declare `@sla(…)` on {dst}, or a bounded stream before it")


def capacity_mismatch_rule(ck):
    return ck.Rule(
        "SGC163", "capacity-mismatch", "hint",
        ask="Many callers reach one fixed callee. What load can it take?",
        why="A scaled-out tier or the open front door overwhelms a fixed tier "
            "during spikes (Unbalanced Capacities).",
        fix="`@sla(…)` on the callee, or a bounded stream", family="16",
        match=lambda doc: match_capacity_mismatch(ck, doc),
        satisfiers=(("callee", "@sla"), ("callee", "^")))


# ---------------------------------------------------------------------------
# SGC165 fanout-tail
# ---------------------------------------------------------------------------

def tail_members(facts: Facts) -> list:
    """Strict join members that can fail (or retry) and have no time bound, in a
    join with no `@deadline` of its own."""
    fl, out = failures_of(facts), []
    for m in join_members(facts, strict=True):
        w = m.wire
        pol = facts.scene.call_policy(w)
        if m.bounded or has_mod(pol, "timeout") or has_mod(pol, "deadline"):
            continue
        if retry_arg(facts, w) is not None or fails_itself(facts, fl, w):
            out.append(m)
    return out


def match_fanout_tail(ck, doc):
    facts = flow_facts(doc)
    for m in tail_members(facts):
        w = m.wire
        what = call_name(facts, w)
        yield ck.Hit(w.line, f"{what} can fail but has no timeout inside {m.join}",
                     f"{what} can fail but has no timeout inside {m.join}. How long "
                     f"can the join wait?", anchor=wire_anchor(w),
                     scopes=(("call", w.ident),),
                     fix="a `@timeout` / `@deadline` on the member, or `} @deadline(t)` "
                         "on the block")


def fanout_tail_rule(ck):
    return ck.Rule(
        "SGC165", "fanout-tail", "advisory",
        ask="A strict join waits for its slowest member. How long can it wait?",
        why="A strict join is only as fast as its slowest member (The Tail at Scale).",
        fix="per-member `@timeout`, or a block-level `@deadline`", family="16",
        match=lambda doc: match_fanout_tail(ck, doc),
        satisfiers=(("call", "@timeout"), ("call", "@deadline"), ("block", "@deadline")))


# ---------------------------------------------------------------------------
# SGC166 single-point-of-failure
# ---------------------------------------------------------------------------

def standby_groups(facts: Facts) -> list:
    """[(tree entry node ids)] of each parent's `\\-_` one-of children, in order."""
    out = []
    for g in _graphs(facts):
        groups = {}
        for t in g.tree:
            if t.rel == "_" and t.parent is not None:
                groups.setdefault(t.parent, []).append(t.node)
        out += [tuple(v) for _k, v in sorted(groups.items())]
    return list(dict.fromkeys(out))


def reached(facts: Facts, nid: str) -> bool:
    """A flow or route into it, or a `@fallback` naming it."""
    name = facts.nodes[nid].name if nid in facts.nodes else nid
    for w in facts.flows:
        if w.dst == nid:
            return True
        fb = mod_arg(facts.scene.call_policy(w), "fallback")
        if fb and name in fb:
            return True
    return False


def has_standby(facts: Facts, nid: str, groups: list) -> bool:
    return any(nid in grp and any(o != nid and reached(facts, o) for o in grp)
               for grp in groups)


def critical_nodes(facts: Facts) -> list:
    """(node id, line) of each node marked `!` or reached by a flow marked `!`."""
    out = {}
    for nid, mods in facts.mods.items():
        if has_mod(mods, "!") and facts.kind(nid) not in ("event", "data", "state"):
            out.setdefault(nid, first_line(facts, nid))
    for w in facts.flows:
        if has_mod(facts.scene.call_policy(w), "!") and not is_route(w):
            out.setdefault(w.dst, w.line)
    return sorted(out.items(), key=lambda kv: (kv[1], kv[0]))


def match_single_point(ck, doc):
    facts = flow_facts(doc)
    groups = standby_groups(facts)
    for nid, line in critical_nodes(facts):
        sla = mod_arg(facts.mods.get(nid, []), "sla") or ""
        if sla.strip().startswith("avail") or instances(facts, nid) or has_standby(
                facts, nid, groups):
            continue
        n = facts.name(nid)
        yield ck.Hit(line, f"{n} is critical, with no redundancy and no stated "
                           f"availability",
                     f"What availability is accepted for {n}?", anchor=("node", nid),
                     fix=f"declare `@sla(avail>…)` on {n}, or `×N` / a reachable standby")
    for grp in groups:
        for nid in grp[1:]:
            if not reached(facts, nid):
                n = facts.name(nid)
                yield ck.Hit(first_line(facts, nid) or branch_line(facts, nid),
                             f"the standby {n} is never switched to",
                             f"What switches to the standby {n}?", anchor=("node", nid),
                             tier="hint",
                             fix=f"a route, `@fallback` or transition that reaches {n}")


def single_point_rule(ck):
    return ck.Rule(
        "SGC166", "single-point-of-failure", "advisory",
        ask="This component's failure takes the system down. What availability is "
            "accepted?",
        why="A critical component with no redundancy and no stated availability is "
            "a single point of failure (SRE book).",
        fix="`@sla(avail>…)`, `×N`, or a reachable standby", family="16",
        match=lambda doc: match_single_point(ck, doc),
        satisfiers=(("callee", "@sla"), ("callee", "×")))


# ---------------------------------------------------------------------------
# SGC167 unbounded-spawn
# ---------------------------------------------------------------------------

def branch_line(facts: Facts, nid: str) -> int:
    """The first `\\-` branch line naming the node (tree entries carry no line)."""
    name = facts.nodes[nid].name if nid in facts.nodes else nid
    for n, raw in enumerate(facts.text, start=1):
        if _BRANCH_RE.match(raw) and re.search(rf"[\[({{|<]{re.escape(name)}[\])}}|>]", raw):
            return n
    return 0


class Spawn(NamedTuple):
    parent: str
    child: str
    line: int
    how: str                         # "a dynamic child" | "a spawn flow" | …


def spawns(facts: Facts) -> list:
    """Every place a node starts a task per message or item: a `\\-*` / `*-`
    dynamic child, a spawn flow `=> [X]`, a `*>` over a collection."""
    out = []
    for g in _graphs(facts):
        for t in g.tree:
            if (t.spawn or t.rel == "*") and t.parent is not None:
                parent = g.tree[t.parent].node
                line = branch_line(facts, t.node) or first_line(facts, t.node)
                out.append(Spawn(parent, t.node, line, "a dynamic child"))
    for w in facts.flows:
        if w.kind == "=>" and w.src != w.dst and facts.kind(w.dst) not in NOT_CALLEES:
            out.append(Spawn(w.src, w.dst, w.line, "a spawned task"))
        elif w.kind == "*>" and collection(w.payload):
            out.append(Spawn(w.src, w.dst, w.line, "a fan-out over a collection"))
    return list(dict.fromkeys(out))


def ceiling(facts: Facts, sp: Spawn) -> bool:
    """`×N` on the child, `@inv concurrency` on the spawner or the child, or a
    bounded stream (`^N`) feeding the spawner or a node above it on its sync
    chain (catalog SGC167: at most N messages start the spawning work)."""
    if has_mod(facts.mods.get(sp.child, []), "×"):
        return True
    if any("concurrency" in heads(facts, facts.mods.get(n, []))
           for n in (sp.parent, sp.child)):
        return True
    return any(facts.nodes[n].is_stream and bounded(facts, n)
               for n in callers_of(facts, sp.parent) if n in facts.nodes)


def callers_of(facts: Facts, nid: str) -> frozenset:
    """The node and every node above it on the sync chain."""
    above = {}
    for w in facts.flows:
        if is_sync(w):
            above.setdefault(w.dst, []).append(w.src)
    return reach(above, nid)


def spawn_edges(facts: Facts) -> dict:
    """{node: [node]} over flows (routes aside) and dynamic-child edges."""
    edges = {}
    for w in facts.flows:
        if not is_route(w):
            edges.setdefault(w.src, []).append(w.dst)
    for sp in spawns(facts):
        edges.setdefault(sp.parent, []).append(sp.child)
    return edges


def reach(edges: dict, start: str) -> frozenset:
    seen, stack = set(), [start]
    while stack:
        n = stack.pop()
        if n not in seen:
            seen.add(n)
            stack += edges.get(n, [])
    return frozenset(seen)


def spawn_cycle(edges: dict, sp: Spawn) -> frozenset:
    """The nodes on the cycles back from the child to its parent (empty: the
    spawn does not recurse). A spawned child that spawns its parent's work again
    is one recursive spawn, however many spawn edges the cycle has."""
    below = reach(edges, sp.child)
    if sp.parent not in below:
        return frozenset()
    return frozenset(n for n in below if sp.parent in reach(edges, n))


def match_unbounded_spawn(ck, doc):
    facts = flow_facts(doc)
    edges, reported = spawn_edges(facts), set()
    for sp in spawns(facts):
        if ceiling(facts, sp):
            continue
        cycle = spawn_cycle(edges, sp)
        if cycle and cycle in reported:
            continue
        reported.add(cycle)
        parent, child = facts.name(sp.parent), facts.name(sp.child)
        more = ", and the spawned work spawns again" if cycle else ""
        yield ck.Hit(sp.line, f"{parent} starts {child} as {sp.how} with no ceiling{more}",
                     f"How many {child} can {parent} spawn at once?",
                     anchor=("node", sp.child), tier="binding" if cycle else "",
                     fix=f"`×N` on {child} (a ceiling), a bounded stream (`^N`) "
                         f"feeding {parent}, or `@inv concurrency <= N`")


def unbounded_spawn_rule(ck):
    return ck.Rule(
        "SGC167", "unbounded-spawn", "advisory",
        ask="How many of these can run at once?",
        why="One task per message or item with no cap is a fork bomb or an "
            "exhausted pool (bounded concurrency).",
        fix="`×N` on the child, `^N` upstream, or `@inv concurrency <= N`",
        family="16", match=lambda doc: match_unbounded_spawn(ck, doc),
        satisfiers=(("callee", "×"), ("callee", "concurrency"), ("owner", "concurrency"),
                    ("owner", "^")))


# ---------------------------------------------------------------------------
# SGC202 dead-failure-route
# ---------------------------------------------------------------------------

def on_group_line(facts: Facts, g) -> bool:
    """A route continuing a `*>` / `&` line (gated until B1)."""
    if g is None or g[0] != "calls":
        return False
    wires = {w.ident: w for w in facts.flows}
    for _c, ident in g[1]:
        w = wires.get(ident)
        if w is not None and (w.kind == "*>" or (w.edge is not None and (
                w.edge.dst_join is not None or w.edge.src_join is not None))):
            return True
    return False


def held_back(facts: Facts, key: tuple, g) -> bool:
    """A route the simulator's known defects keep dead: one on a `*>` / `&` line
    (B1), or a block route over requests (B2: block members get no failure
    choice, so a route under `parallel @all { … }` never fires)."""
    if GROUP_ROUTES_GATED and on_group_line(facts, g):
        return True
    return BLOCK_ROUTES_GATED and g is not None and g[0] == "block" and any(
        call_like(facts, w) for w in guarded_wires(facts, key, g))


def declares_failure(facts: Facts, key: tuple, g) -> bool:
    """A route under a request states, by being there, that the request can fail
    (catalog SGC202): it guards a call_like flow, or a `=> {X}` continuing one
    (guarded_wires). A node's own route states that the node's unwritten work can
    fail when the node waits on nothing written (`[Payments] ~> <Paid>` then
    `[Payments] !> <Declined>`); once the node's sync work is written, the route
    guards that work (`[A] -> {Report}` then `[A] !> …` is dead). A block route
    over requests is held_back's (B2)."""
    if g is None:
        return not any(is_sync(w) or call_like(facts, w)
                       for w in callee_wires(facts, *key) if not is_route(w))
    return g[0] == "calls" and any(
        call_like(facts, w) for w in guarded_wires(facts, key, g))


def guards_halting(facts: Facts, fl: Failures, key: tuple, g) -> bool:
    """The route guards a `!` call that can fail. The run ends there before the
    route fires, so it is not dead for want of a failure: SGC201 counts the
    route as the call's handling."""
    if g is None:
        scope = [w for w in facts.flows if (facts.unit.get(id(w), 0), w.src) == key]
    else:
        scope = guarded_wires(facts, key, g)
    return any(is_halting(facts, w) and halting_fails(facts, fl, w) for w in scope)


def route_live(facts: Facts, fl: Failures, key: tuple, r, g) -> bool:
    """SGC202's liveness: the failures that exist without any route select r
    (Failures.own_live), r declares its guard's failure, it guards a `!` call that
    can fail, or a known simulator defect holds it back. A route of an activation
    only route-made failures reach is not judged (live)."""
    return (r.ident in fl.own_live or key not in fl.own_arriving
            or declares_failure(facts, key, g) or guards_halting(facts, fl, key, g)
            or held_back(facts, key, g))


def dead_routes(facts: Facts) -> list:
    """The routes of activated nodes that are not route_live, in scene order."""
    fl, out = failures_of(facts), []
    for key, routes in facts.prog.routes.items():
        if key in fl.arriving:
            out += [r for r, g in routes if not route_live(facts, fl, key, r, g)]
    return sorted(out, key=lambda r: facts.prog.order[id(r)])


def match_dead_failure_route(ck, doc):
    facts = flow_facts(doc)
    for r in dead_routes(facts):
        dst = facts.name(r.dst)
        scopes = (("event", r.dst),) if facts.kind(r.dst) == "event" else ()
        yield ck.Hit(r.line, f"nothing this `!>` guards can fail, so the route to {dst} "
                             f"never fires",
                     f"Nothing above this `!>` can fail, so it never fires. Which flow "
                     f"did you mean it to guard?", anchor=wire_anchor(r), scopes=scopes,
                     fix="say how the guarded flow fails (an `op` call, `@timeout`), "
                         "place the route under the flow it means, or delete it")


def dead_failure_route_rule(ck):
    return ck.Rule(
        "SGC202", "dead-failure-route", "binding",
        ask="Nothing above this `!>` can fail. Which flow should it guard?",
        why="A route no failure reaches makes the author believe a failure is "
            "handled when it is not.",
        fix="state how the guarded flow fails, move the route, or delete it",
        family="20", match=lambda doc: match_dead_failure_route(ck, doc),
        implies=(("orphan-event", "event"),))


# ---------------------------------------------------------------------------
# The module's rules
# ---------------------------------------------------------------------------

RULES = (unguarded_call_rule, retry_amplification_rule, timeout_budget_rule,
         retry_without_backoff_rule, retry_without_idempotency_rule,
         duplicate_delivery_rule, dual_write_rule, poison_message_rule,
         saga_uncompensated_rule, fragile_compensation_rule, race_loser_effects_rule,
         unbounded_buffer_rule, unbounded_result_rule, capacity_mismatch_rule,
         fanout_tail_rule, single_point_rule, unbounded_spawn_rule,
         unhandled_failure_rule, dead_failure_route_rule)


def rules(ck) -> list:
    return [make(ck) for make in RULES]
