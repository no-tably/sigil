"""
Scenarios: the pathways a run may take — the failure flow read statically
(failure_flow, failure_analysis), the choice points and the scenarios they
give (happy, then one per deviation; scenario() reads a name), the overlap
scenarios (entries that begin while an earlier episode runs) and the bounded
exploration of combined deviations. See the package's docstring (SCENARIOS,
STATIC FACTS).
"""

from __future__ import annotations

import hashlib
import heapq
import re
from collections import Counter
from typing import NamedTuple, Optional

from sigil.model import scene as scene_mod
from sigil.model.sim.program import (
    Decide, Group, Limits, Program, Region, Scenario, Step, Trace, _alias_of, _decides,
    _detached, _flat, _gate_of, _guards, _home, _one_of_groups, _program_of, _pseudo, _running,
    arm_entry, attempts, landing_arm, loop_count,
    mod, resilient, selected_routes)
from sigil.model.sim.engine import _simulate
from sigil.model.sim.narration import _Words


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
#   _region       relabels any failure leaving it as ("block", index), keeping what it
#                 was inside (a route on the call line still fires); a loop run 0
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
#   _fire_routes  routes guarded by the arriving guard (or one it was inside its
#                 blocks), else the unguarded ones
# Every choice may go either way (each is a scenario option); limits that only
# cut a run short (depth, visits, instances) are not modelled, so a route this
# calls live may need a deeper run, or two deviations, to fire.

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
    via: frozenset = frozenset()        # (raised block guard, the guards it was before
                                        # leaving its blocks, innermost first): one per path


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
                   tuple(c for e in effects for c in e.started),
                   frozenset().union(*(e.via for e in effects)))


def _relabel(e: _Effect, guard: tuple) -> _Effect:
    """A failure leaving a block raises the block's guard; each path keeps the
    guards it had inside (_Fail.via), so a route on a call line still fires."""
    if not e.raises:
        return e._replace(raises=frozenset(), via=frozenset())
    via = frozenset((guard, p + (g,)) for g in e.raises for p in _paths(e, g))
    return e._replace(raises=frozenset({guard}), via=via)


def _paths(e: _Effect, guard) -> list:
    """The guards a raised `guard` had inside its blocks, one tuple per path."""
    return [p for o, p in e.via if o == guard] or [()]


def _land_ctx(prog: Program, w, arm, scopes: frozenset) -> Optional[_Ctx]:
    """The activation a token arriving along w starts (_land), or None where
    _land starts none: a hole, an external node or op, an actor."""
    sn = prog.scene.nodes.get(w.dst)
    if sn is not None and (sn.node.is_hole or sn.external
                           or (w.call is not None and w.call.external)):
        return None
    if sn is not None and sn.node.kind == "actor":
        return None
    ui = prog.wire_unit.get(id(w), 0)
    arm = landing_arm(prog, arm, w.dst)
    return _Ctx(ui if arm is not None else _home(prog, ui, w.dst), w.dst, arm,
                _alias_of(prog, w), scopes)


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
        elif isinstance(it, Decide):
            out.append(_branch_effect(fl, fails, it.ui, it.index, at.scopes))
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
    parts = [own]
    if ctx.arm is None or ctx.node != arm_entry(prog, ctx.arm):
        ui = ctx.ui if ctx.arm is None else _home(prog, ctx.ui, ctx.node)
        exp = prog.expansions.get((ui, ctx.node))
        if exp is not None:
            parts += [_entry_effect(fl, fails, exp, e, ctx.scopes)
                      for e in prog.entries.get(exp, ())]
        parts.append(_walk(fl, fails, _running(prog, prog.bodies.get((ui, ctx.node), ())),
                           _Place(ctx.node, None, ctx.scopes, True)))
        parts += [_branch_effect(fl, fails, ui, bi, ctx.scopes)
                  for bi in prog.branches.get((ui, ctx.node), ())]
    if ctx.arm is not None:
        parts.append(_walk(fl, fails, prog.arm_bodies.get(ctx.arm, {}).get(ctx.node, ()),
                           _Place(ctx.node, ctx.arm, ctx.scopes, True)))
    return _merge(*parts)


def _fired(prog: Program, ctx: _Ctx, e: _Effect) -> list:
    """The routes of ctx's node that its arriving and absorbed guards select."""
    routes = prog.routes.get((ctx.ui, ctx.node), ())
    out = [w for f in e.raises for p in _paths(e, f) for w in selected_routes(routes, f, p)]
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
    # Rounds over the known activations in discovery order, each re-running only
    # those whose reads changed since they ran (an activation is a pure function
    # of them): `dirty` holds them by discovery index — a round runs the ones
    # below its start's count in order, one dirtied ahead of the round's place
    # still this round, else the next. readers: ctx → the activations whose
    # last run asked about it.
    order = list(known)
    index = {ctx: i for i, ctx in enumerate(order)}
    asked, readers = {}, {}
    dirty = set(range(len(order)))      # never ran, or a read changed since
    while dirty:
        limit = len(order)
        todo = [i for i in dirty if i < limit]
        heapq.heapify(todo)
        queued = set(todo)
        dirty -= queued
        while todo:
            i = heapq.heappop(todo)
            ctx = order[i]
            for c in asked.get(ctx, ()):
                readers[c].discard(ctx)
            fails.asked = asked[ctx] = set()
            e = _activation(fl, fails, ctx)
            fails.asked = None
            for c in asked[ctx]:
                readers.setdefault(c, set()).add(ctx)
            effects[ctx] = e
            if e.raises != fails.get(ctx, frozenset()):
                fails[ctx] = e.raises
                for r in readers.get(ctx, ()):
                    k = index[r]
                    if i < k < limit:
                        if k not in queued:
                            queued.add(k)
                            heapq.heappush(todo, k)
                    else:
                        dirty.add(k)
            for c in _started(prog, ctx, e):
                if c not in known:
                    known[c] = None
                    index[c] = len(order)
                    dirty.add(len(order))
                    order.append(c)
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
        ui = _home(prog, ui, nid)
        if (ui, nid) in seen:
            continue
        seen[(ui, nid)] = True
        if nid in prog.decisions:
            dui, bi = prog.decisions[nid]
            regions[(dui, bi)] = None
            _take_branch(prog, dui, bi, take, queue)
            continue
        items = _running(prog, prog.bodies.get((ui, nid), ()))
        regions_of(items, nid)
        take(_flat(items), ui)
        for d in _decides(items):
            regions[(d.ui, d.index)] = None
            _take_branch(prog, d.ui, d.index, take, queue)
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
    name = lambda nid: _node_part(prog, nid)
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
    point, in source order, then the overlap scenarios (overlaps()), then the
    state starts (state_starts()); capped at limits.scenarios."""
    prog = _program_of(sc.graph)
    out = [Scenario("happy", (), "every default: the happy path")]
    for p in choice_points(prog, limits):
        for opt, nm, label in zip(p.options[1:], p.names[1:], p.labels[1:]):
            out.append(Scenario(nm, ((p.cid, opt),), label))
    if len(out) < limits.scenarios:
        out += _overlaps(prog, limits)
    if len(out) < limits.scenarios:
        out += _state_starts(prog)
    return out[:limits.scenarios]


def scenario(sc, name: str, *, limits: Limits = Limits()) -> Scenario:
    """The scenario of that name; `a+b` combines its parts (later wins on one
    choice point, one entry's start or one machine's state). A part is a listed
    scenario, `Entry@t` (an entry, named as scenario names write nodes, beginning
    at tick t: any t, listed or not) or `Owner=State` (a state machine's owner,
    named so, beginning in State: any state its block names, not `+`, `$` or `_`;
    no `.` before the `=`, so a field choice `Owner.field=value` is not one).
    Raises KeyError listing the names when one is unknown, and the owner's states
    when the owner is known and the state is not."""
    prog = _program_of(sc.graph)
    listed = {s.name: s for s in scenarios(sc, limits=limits._replace(scenarios=10 ** 6))}
    entries = _entry_parts(prog)
    owners = _machine_parts(prog)
    parts = name.split("+")
    picked = [listed.get(p) or _start_scenario(prog, p, entries)
              or _state_scenario(prog, p, owners) for p in parts]
    missing = [p for p, s in zip(parts, picked) if s is None]
    if missing:
        ways = ([f"an entry start is Entry@tick, one of {', '.join(entries)}"] if entries else []) \
            + ([f"a state start is Owner=State: {_owner_states(prog, owners)}"] if owners else [])
        hint = f" ({'; '.join(ways)})" if ways else ""
        raise KeyError(f"unknown scenario {', '.join(missing)}{hint}; known: {', '.join(listed)}")
    if len(parts) == 1:
        return picked[0]
    choices, starts, machines = {}, {}, {}
    for s in picked:
        choices.update(dict(s.choices))
        starts.update(dict(s.starts))
        machines.update(dict(s.machines))
    return Scenario(name, tuple(choices.items()),
                    " + ".join(s.label for s in picked if s.label), None, tuple(starts.items()),
                    tuple(machines.items()))


# ---------------------------------------------------------------------------
# Overlaps — entries that begin while an earlier one's episode runs
# ---------------------------------------------------------------------------

_START_RE = re.compile(r"^(.+)@(\d+)$")


_TOUCH_RANK = {"store": 0, "machine": 1, "node": 2}   # the likeliest race first


class OverlapWindow(NamedTuple):
    """An earlier entry's episode in the happy run, as a later one may overlap it:
    `first` and `later` entry node ids, `start` and `end` the first and last tick
    the earlier episode is busy (a task of it acts)."""
    first: str
    later: str
    start: int
    end: int


class _Touch(NamedTuple):
    """An episode touching something: at `tick`, `item` (a node id, or a machine's
    owner) as `kind` ("store": an access, `mode` its mode, `by` the node at the
    access wire's other end, the one reading or writing it; "machine": a
    transition; "node": the middle of an activation there)."""
    tick: int
    item: str
    kind: str
    mode: str = ""
    by: str = ""


class _Episode(NamedTuple):
    entry: str
    start: int
    end: int                   # its last busy tick
    touches: tuple             # _Touch, in tick order


def _node_part(prog: Program, nid: str) -> str:
    """A node as scenario names write it."""
    return _part(prog.scene.nodes[nid].node.name) if nid in prog.scene.nodes else nid


def _entry_parts(prog: Program) -> dict:
    """{name as scenario names write it: node id} of the default entries that are
    nodes of the scene (the first entry of a name keeps it)."""
    out = {}
    for nid in prog.entries.get(0, ()):
        if nid in prog.scene.nodes:             # a decision has no name to write
            out.setdefault(_node_part(prog, nid), nid)
    return out


def _start_scenario(prog: Program, part: str, entries: dict) -> Optional[Scenario]:
    """The scenario `Entry@t` names (an entry of `entries` beginning at tick t),
    or None when part is not one."""
    m = _START_RE.match(part)
    if m is None or m.group(1) not in entries:
        return None
    nid, t = entries[m.group(1)], int(m.group(2))
    return Scenario(part, (), f"{_Words(prog.scene).name(nid)} starts at t{t}", None, ((nid, t),))


_STATE_PART_RE = re.compile(r"^([^.=@+]+)=([^=+]+)$")


def _machine_parts(prog: Program) -> dict:
    """{owner as scenario names write it: owner node id} of every state machine
    whose owner is a node of the scene (the first machine of a name keeps it)."""
    out = {}
    for owner in prog.machines:
        if owner in prog.scene.nodes:
            out.setdefault(_node_part(prog, owner), owner)
    return out


def _state_names(prog: Program, owner: str) -> dict:
    """{state as scenario names write it: state node id} of owner's machine, in
    written order (the first state of a name keeps it)."""
    out = {}
    for nid in prog.machines[owner].states:
        out.setdefault(_part(_state_label(prog, nid)), nid)
    return out


def _owner_states(prog: Program, owners: dict) -> str:
    """`Owner in A, B, C; Other in X` over owners ({part: owner id})."""
    return "; ".join(f"{part} in {', '.join(_state_names(prog, owner))}"
                     for part, owner in owners.items())


def _state_start(prog: Program, owner: str, state: str) -> Scenario:
    return Scenario(f"{_node_part(prog, owner)}={_part(_state_label(prog, state))}", (),
                    f"starts with {_Words(prog.scene).name(owner)} in "
                    f"{_state_label(prog, state)}", None, (), ((owner, state),))


def _state_scenario(prog: Program, part: str, owners: dict) -> Optional[Scenario]:
    """The scenario `Owner=State` names (owner's machine beginning in State), or
    None when part is not one. Raises KeyError listing the owner's states when
    the owner is known and its block names no such state (`+`, `$` and `_` are
    no states to begin in)."""
    m = _STATE_PART_RE.match(part)
    if m is None or m.group(1) not in owners:
        return None
    owner = owners[m.group(1)]
    states = _state_names(prog, owner)
    if m.group(2) not in states:
        raise KeyError(f"unknown state {m.group(2)} for {m.group(1)} in scenario {part}; "
                       f"its states: {', '.join(states)}")
    return _state_start(prog, owner, states[m.group(2)])


def _ways_out(prog: Program, m) -> set:
    """The states of machine m some transition leaves for another state: one written
    from it, or a `_` one (taken from any state with no transition of its own on
    that trigger) to a state other than it."""
    out, wild = set(), set()
    for src, dst, _label, _ident in m.transitions:
        if src in m.states and dst != src:
            out.add(src)
        elif _pseudo(prog, src) == "any":
            wild.add(dst)
    return out | {s for s in m.states if wild - {s}}


def _state_starts(prog: Program) -> list:
    """One scenario `Owner=State` per state machine and state other than its initial
    one with a way out (_ways_out), in machine order, then written order."""
    out = []
    for owner, m in prog.machines.items():
        if owner not in prog.scene.nodes:
            continue
        ways = _ways_out(prog, m)
        out += [_state_start(prog, owner, s) for s in m.states if s != m.initial and s in ways]
    return out


def state_starts(sc) -> list:
    """The state starts scenarios() lists after the overlaps: for each state machine
    (its owner a node of the scene) and each state other than its initial one that
    a transition leaves, a scenario `Owner=State` beginning the machine there, so a
    way out of a later state is walked. Named as scenario names write nodes."""
    return _state_starts(_program_of(sc.graph))


def _touches(events: list, wires: dict) -> tuple:
    """The _Touches of one episode's events: each store access (by the other end
    of its wire, `wires` {ident: scene Wire}), each machine transition, and the
    middle tick of each activation (a node the access already names counts as
    the store only)."""
    entered, out = {}, []
    accessed = {e["store"] for e in events if e["kind"] == "access"}
    for e in events:
        if e["kind"] == "access":
            w = wires.get(e["wire"])
            by = "" if w is None else (w.src if w.dst == e["store"] else w.dst)
            out.append(_Touch(e["t"], e["store"], "store", e["mode"], by))
        elif e["kind"] == "transition":
            out.append(_Touch(e["t"], e["owner"], "machine"))
        elif e["kind"] == "enter":
            entered[e["act"]] = (e["t"], e["node"])
        elif e["kind"] == "leave" and e["act"] in entered:
            t, nid = entered.pop(e["act"])
            if nid not in accessed:
                out.append(_Touch((t + e["t"]) // 2, nid, "node"))
    return tuple(sorted(out, key=lambda x: x.tick))


def _episodes(prog: Program, trace: Trace) -> list:
    """[_Episode] of a run of prog, in start order (an episode no task of which
    acted is left out)."""
    events = [e for e in trace.end["events"] if e["task"] is not None]
    wires = {w.ident: w for w in prog.scene.wires}
    out = []
    for ep in trace.end["episodes"]:
        own = [e for e in events if e["episode"] == ep["episode"]]
        if own:
            out.append(_Episode(ep["entry"], ep["start"], max(e["t"] for e in own),
                                _touches(own, wires)))
    return out


def _pairs(prog: Program, limits: Limits) -> list:
    """[(earlier _Episode, later _Episode)] of the happy run, by the later one's
    written order, then the earlier's; [] for a document with one entry."""
    named = set(_entry_parts(prog).values())
    if len(named) < 2:
        return []
    eps = [e for e in _episodes(prog, _simulate(prog, Scenario("happy"), limits, keep=False))
           if e.entry in named]
    return [(a, b) for j, b in enumerate(eps) for a in eps[:j]]


def _touch_clause(who: str, t: _Touch, wd: _Words) -> str:
    """What the earlier entry `who` is doing to the shared item as the later one
    reaches it: "as [A] writes it", "as [A] changes its state", "while [A] is there".
    A store access names the node that makes it, which may be a node the entry's
    episode reaches rather than the entry ("as (Author) writes it" in (Visitor)'s
    episode)."""
    verb = {"read": "reads", "write": "writes", "rw": "reads and writes"}.get(t.mode, "uses")
    if t.kind == "store":
        return f"as {wd.name(t.by) if t.by else who} {verb} it"
    if t.kind == "machine":
        return f"as {who} changes its state"
    return f"while {who} is there"


def _pair_overlaps(prog: Program, a: _Episode, b: _Episode, wd: _Words, cap: int) -> list:
    """Up to `cap` scenarios starting b's entry so it reaches something a's episode
    touches (a's own entry aside: a is busy there throughout) as a touches it,
    in tick order: one per shared item and start tick, those b can reach in time
    first, then stores, machines, nodes, then the earliest. A start that would
    fall before a's episode begins is a's start (b then reaches it later)."""
    reach = {}
    for t in b.touches:
        reach.setdefault(t.item, t.tick - b.start)
    picked, items = {}, set()
    for late, _rank, start, t in sorted(_meetings(a, reach)):
        if start not in picked and t.item not in items and len(picked) < cap:
            picked[start] = (t, late)
            items.add(t.item)
    bname, aname = wd.name(b.entry), wd.name(a.entry)
    out = []
    for start, (t, late) in sorted(picked.items()):
        item = wd.name(t.item)
        label = (f"{bname} starts at t{start} with {aname}, reaching {item} after it does"
                 if late else
                 f"{bname} starts at t{start}, reaching {item} {_touch_clause(aname, t, wd)}")
        out.append(Scenario(f"{_node_part(prog, b.entry)}@{start}", (), label, None,
                            ((b.entry, start),)))
    return out


def _meetings(a: _Episode, reach: dict) -> list:
    """[(late, rank, start, _Touch)] for each touch of a's episode on an item the
    other entry reaches `reach[item]` ticks after it starts: the start that has it
    arrive as a touches it (no earlier than a's start; `late` when it had to be
    moved later) and the touch's rank (_TOUCH_RANK)."""
    out = []
    for t in a.touches:
        if t.item in reach and t.item != a.entry:
            start = t.tick - reach[t.item]
            out.append((start < a.start, _TOUCH_RANK[t.kind], max(start, a.start), t))
    return out


_LAST_OVERLAPS: list = [None, None, None]     # [Program, Limits, its overlap scenarios]


def _overlaps(prog: Program, limits: Limits) -> list:
    """The listed overlap scenarios (overlaps()), built once per program and limits."""
    if _LAST_OVERLAPS[0] is not prog or _LAST_OVERLAPS[1] != limits:
        wd, out = _Words(prog.scene), {}
        for a, b in _pairs(prog, limits):
            for s in _pair_overlaps(prog, a, b, wd, limits.pair_overlaps):
                out.setdefault(s.name, s)
        _LAST_OVERLAPS[:] = [prog, limits, list(out.values())[:limits.overlaps]]
    return list(_LAST_OVERLAPS[2])


def overlaps(sc, *, limits: Limits = Limits()) -> list:
    """The overlap scenarios scenarios() lists after the failure ones: for each
    later entry B and earlier entry A (the happy run's episodes), B started so it
    reaches something A's episode touches — a store A accesses, a machine A
    moves, a node or event A is busy at — as A touches it: the moments a race
    could happen. Named `B@t`; at most limits.pair_overlaps per pair and
    limits.overlaps in all; [] with one entry."""
    return _overlaps(_program_of(sc.graph), limits)


def overlap_windows(sc, *, limits: Limits = Limits()) -> list:
    """[OverlapWindow] for each later entry and earlier one of the happy run, by
    the later one's written order: the ticks the earlier episode is busy."""
    return [OverlapWindow(a.entry, b.entry, a.start, a.end)
            for a, b in _pairs(_program_of(sc.graph), limits)]


def overlap_runs(sc, *, limits: Limits = Limits()) -> list:
    """Every start of a later entry inside an earlier one's window (overlap_windows):
    one scenario `B@t` per tick t from the window's start to its end — at most
    limits.window ticks per window, spread evenly over it when it is longer — in
    window order, then tick order; a start two windows share is listed once.
    What a checker tries beyond the listed overlaps (combine with a deviation by
    `_replace(choices=…)`)."""
    prog = _program_of(sc.graph)
    wd, out = _Words(prog.scene), {}
    for w in overlap_windows(sc, limits=limits):
        bname = _node_part(prog, w.later)
        for t in _spread(w.start, w.end, limits.window):
            label = (f"{wd.name(w.later)} starts at t{t}, during {wd.name(w.first)}'s "
                     f"episode (t{w.start}–t{w.end})")
            out.setdefault(f"{bname}@{t}", Scenario(f"{bname}@{t}", (), label, None,
                                                    ((w.later, t),)))
    return list(out.values())


def _spread(lo: int, hi: int, cap: int) -> list:
    """The ticks lo … hi, or `cap` of them spread evenly (both ends kept) when
    there are more."""
    n = hi - lo + 1
    if n <= cap:
        return list(range(lo, hi + 1))
    if cap == 1:
        return [lo]
    return sorted({lo + round(i * (n - 1) / (cap - 1)) for i in range(cap)})


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
    outcome are what an exploration reads); the happy run keeps them all
    (combinations' `keep_happy`). With combinations' `record`, each kept
    Trace is stored as what record made of it instead."""
    traces: tuple
    duplicates: int
    left_out: int


def deviations(prog: Program, limits: Limits = Limits()) -> list:
    """Every Deviation of the reachable choice points, in source order (the
    scenarios() list without `happy` and without its cap)."""
    return [Deviation(p.cid, opt, nm, label) for p in choice_points(prog, limits)
            for opt, nm, label in zip(p.options[1:], p.names[1:], p.labels[1:])]


def combinations(sc, k: int, *, limits: Limits = Limits(), budget: int = 256,
                 keep_happy: bool = True, record=None) -> Exploration:
    """The runs of up to k deviations at once, built from choice ids (never by
    name). Level 1 is every deviation; a combination grows by a deviation its
    own run depends on — one whose choice point the run meets at or after its
    first deviation's tick, in that episode or a later one (it lies on the
    deviated path, or the deviation enabled it: machine state, gates and spawn
    counts outlive an episode). A run whose log and outcome repeat an earlier one's
    is dropped; at most `budget` runs are made (the happy run aside), and what
    the budget cut is counted in left_out. Pure and deterministic.

    What it keeps, not what it runs: `keep_happy` false keeps only the happy
    run's last frame too; `record(trace)`, when given, is stored for each kept
    run in place of its Trace (once its deeper combinations are read off it),
    so a caller can keep a compact form; repeats are found by a digest of each
    run's signature, not by its whole log."""
    prog = _program_of(sc.graph)
    devs = deviations(prog, limits)
    keep = record or (lambda trace: trace)
    happy = _simulate(prog, Scenario("happy", (), "every default: the happy path"), limits,
                      keep_happy)
    seen, kept = {signature_digest(_signature(happy))}, [keep(happy)]
    level = [(i,) for i in range(len(devs))] if k >= 1 else []
    runs = duplicates = 0
    for depth in range(1, k + 1):
        grown = []
        for n, combo in enumerate(level):
            if runs >= budget:
                return Exploration(tuple(kept), duplicates, len(level) - n)
            runs += 1
            trace = _simulate(prog, _combined(devs, combo), limits, keep=False)
            sig = signature_digest(_signature(trace))
            if sig in seen:
                duplicates += 1
                continue
            seen.add(sig)
            if depth < k:
                grown += _grown(devs, combo, trace)
            kept.append(keep(trace))
        level = list(dict.fromkeys(grown))
    return Exploration(tuple(kept), duplicates, 0)


def _combined(devs: list, combo: tuple) -> Scenario:
    picked = [devs[i] for i in combo]
    return Scenario("+".join(d.name for d in picked),
                    tuple((d.cid, d.option) for d in picked),
                    " + ".join(d.label for d in picked if d.label))


def _signature(trace: Trace) -> tuple:
    return (trace.outcome, tuple(trace.end["log"]))


def signature_digest(sig: tuple) -> bytes:
    """A run signature (outcome, log lines) as a fixed-size digest: two runs
    repeat each other when their digests are equal (each line is length-
    prefixed, so no two signatures run together)."""
    outcome, log = sig
    h = hashlib.blake2b(digest_size=20)
    for part in (outcome, *log):
        b = part.encode("utf-8", "surrogatepass")
        h.update(len(b).to_bytes(8, "little"))
        h.update(b)
    return h.digest()


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
