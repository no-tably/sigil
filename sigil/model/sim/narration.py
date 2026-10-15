"""
Narration: a finished run read for a reader — the timeline the run view draws
(lanes, spans, moves, marks), the projection of a run onto the Scene a view
draws (folded hosts), and the run in plain words (narrate → Beats, hops). Pure,
no drawing. See the package's docstring (THE TIMELINE, NARRATION).
"""

from __future__ import annotations

import heapq
from collections import Counter
from typing import NamedTuple, Optional

from sigil.core.graph import node_label
from sigil.model import scene as scene_mod
from sigil.model.sim.program import Frame, Limits, Trace, _program_of, carried, instances


# ---------------------------------------------------------------------------
# The timeline — what the run view draws: one run as lanes over ticks (a lane
# per participant, composition instance and recursion level), each activation
# a span on its lanes, each hop a move between them, a self-call's pulse, a
# host op and a base case a mark. Read from a trace's events in one pass;
# pure, no drawing (view_run.py draws it).

RUN_SHOW = 3                   # instances per (node, owner's node) and levels per lane before folding


FOLD = "…"                     # a fold's ordinal in a lane key: (node, "…" + owner's node, level)


class Lane(NamedTuple):
    """One row of the timeline. key (node id, instance ordinal | None, level):
    ordinal None outside the composition tree, a fold's FOLD + its owner's node;
    level 1, or a recursion's depth k (a `↻k` sub-row), or a fold of levels'
    `lo‥hi`."""
    key: tuple
    node: str
    inst: Optional[tuple]      # its instance key (None: outside the tree, or a fold)
    level: int                 # 1, or the recursion depth k (a fold of levels: its lowest)
    parent: Optional[tuple]    # the lane it sits under: the node an expansion reads
                               # closer, a recursion's level-1 lane; None: top level
    born: int                  # the tick it first acts or a hop sets out to it
    owner: Optional[tuple]     # its instance's composition parent (an instance key)
    spawned: Optional[int]     # the tick its instance was spawned (None: set up)
    spawner: Optional[str]     # the node whose `=>` spawned it
    fold: tuple = ()           # a fold of instances: the instance keys it stands for
    levels: tuple = ()         # a fold of levels: (lowest, highest)
    owners: tuple = ()         # a fold of instances: their owners (instance keys), in order
    par: int = 1               # k ≥ 2: a `∥k` sub-row of its parent lane, the activations
                               # that ran while the rows above it were taken (key + (k,))


class Span(NamedTuple):
    """One activation on one lane: [enter, leave) ticks; waits ((from, to), …)
    the ticks of it spent waiting (to exclusive) — on a call it made, a deeper
    activation of its task, the members it awaits — the rest is work. `folded`:
    a folded node's activation moved onto its host's lane (_fold_into_hosts),
    work the host's fold does, not another run of the host."""
    lane: tuple
    act: int
    task: int
    node: str
    enter: int
    leave: Optional[int]       # None: still running when the run ended
    how: str                   # ok | failed | cancelled | "" (still running)
    waits: tuple
    caller: Optional[int]
    wire: Optional[tuple]
    episode: int
    folded: bool = False


class Move(NamedTuple):
    """One hop between lanes: set out at `start`, ended at `end` (the land
    event's tick; None: in flight when the run ended) as `how` (the land
    event's: entered, reached, opaque, failed, cancelled, returned, fallback,
    arrived, none, visits). src: the lanes it leaves (a reply: its callee's, a
    fallback: the call target's); dst: the lanes it arrives on (a reply: its
    caller's)."""
    id: int
    task: int
    act: Optional[int]
    wire: tuple
    kind: str
    back: bool
    start: int
    end: Optional[int]
    how: str
    src: tuple
    dst: tuple
    attempt: Optional[tuple]
    carries: Optional[str]


class Mark(NamedTuple):
    """A one-tick event on a lane: self (a self-call's pulse, ↺), host (a host
    op it calls, ⇱), base (where the depth limit stopped a recursion, ┤)."""
    lane: tuple
    t: int
    what: str
    wire: Optional[tuple] = None
    carries: Optional[str] = None  # a pulse's call (`plan({Seed})`, `mail.send(…)`)


class Iteration(NamedTuple):
    """A loop starting its k-th iteration (of `of`) at tick t: `block` (unit
    owner node id | None, block index), `act` the activation running it (its
    spans say on which lanes; None: none; a folded node's: the one on its
    drawn host's lane standing for it). `inside`: the loop's owner is folded
    too, so the host loops inside its hidden expansion (_hosted_iterations)."""
    t: int
    k: int
    of: int
    block: tuple
    act: Optional[int]
    inside: bool = False


class Timeline(NamedTuple):
    lanes: tuple               # Lane, in drawing order
    spans: tuple               # Span, by enter
    moves: tuple               # Move, by id
    marks: tuple               # Mark, by tick
    episodes: tuple            # ((k, start tick, entry node id), …)
    last: int                  # the run's last tick
    folded: dict               # {"show", "instances", "levels"}: what folding left out
    iterations: tuple = ()     # Iteration, by tick
    hosts: dict = {}           # folded_hosts: the folded nodes, each with its host
    hidden: frozenset = frozenset()  # the ticks something happens inside a fold (change_ticks
                               # of the folded lanes' spans and of the hops left out): the
                               # host is busy on hidden internals then


def timeline(trace: Trace, *, limits: Limits = Limits(),
             show: Optional[int] = RUN_SHOW, hosts: Optional[dict] = None) -> Timeline:
    """The run of `trace` (on the canonical scene, simulate's) as a timeline:
    a lane per participant it touched — every node an activation entered or a
    hop set out to (a failed attempt's target, a race's loser, an actor, a
    host's side too) — one per composition instance (`{Transform·2}`) and per
    recursion level (`↻k`). Lanes are born at the tick they first act or a hop
    sets out towards them and ordered by birth (in one tick the sender before
    the receiver), an expansion's lanes under the node it reads closer, a
    recursion's levels under its lane, the instances of one node together in
    ordinal order, a lane's concurrent activations (on other tasks) on `∥k`
    sub-rows under it (_parallel_lanes). Each activation is a Span per lane it stands for, each hop
    a Move, each self-call pulse, host op and base case a Mark, each loop
    iteration an Iteration. `limits`: the
    run's (its setup instances). `show` (None: no folding): a group of more
    than `show` instances of one node under one kind of owner keeps its first
    show − 1 and every one that failed or was cancelled, the rest one lane
    (FOLD); levels past show + 1 keep ↻2 … ↻(show − 1) and the deepest, the
    middle one lane (lo‥hi). `hosts` (folded_hosts; None: every node drawn):
    a folded node's lanes fold into its host's (_fold_into_hosts), the ticks
    something happens inside a fold kept as `hidden`, a loop run inside one
    said of the host's activation (_hosted_iterations). Pure."""
    prog = _program_of(trace.scene.graph)
    events = trace.end.get("events", ())
    wires = {w.ident: w for w in prog.scene.wires}
    setup = {i.key: i for i in instances(prog, limits)}
    owner_of = {k: i.parent for k, i in setup.items()}
    exp_owner = {exp: node for (_ui, node), exp in prog.expansions.items()}
    last = trace.frames[-1].tick if trace.frames else 0
    acts, lanes, spawns = {}, {}, {}
    hops, lands, enters_by_hop = {}, {}, {}
    marks, awaits, episodes, iterations = [], {}, [], []
    seq, hop_seq = [0], {}

    def keys_of(nid: str, insts, level: int) -> tuple:
        return tuple((nid, k[1], level) for k in insts) if insts else ((nid, None, level),)

    def parent_of(key: tuple, unit: Optional[int], chain: Optional[int]) -> Optional[tuple]:
        nid, ordinal, level = key
        if level > 1:
            return (nid, ordinal, 1)
        owner = exp_owner.get(unit)
        a = chain
        while owner is not None and a is not None:
            info = acts.get(a)
            if info is None:
                break
            if info["node"] == owner:
                return info["lanes"][0] if info["level"] == 1 else (owner, info["lanes"][0][1], 1)
            a = info["caller"]
        return None

    def born(key: tuple, t: int, unit=None, chain=None) -> None:
        seq[0] += 1
        if key not in lanes:
            if key[2] > 1:
                born((key[0], key[1], 1), t)
            lanes[key] = {"born": (t, seq[0]), "parent": parent_of(key, unit, chain)}

    for ev in events:
        kind, t = ev["kind"], ev["t"]
        if kind == "enter":
            ks = keys_of(ev["node"], ev["insts"], ev["level"])
            acts[ev["act"]] = {"node": ev["node"], "task": ev["task"], "enter": t, "leave": None,
                               "how": "", "lanes": ks, "caller": ev["caller"],
                               "wire": ev["wire"], "level": ev["level"],
                               "episode": ev["episode"]}
            for k in ks:
                born(k, t, ev["unit"], ev["caller"])
            if ev.get("hop") is not None:
                enters_by_hop[ev["hop"]] = ev["act"]
        elif kind == "leave":
            a = acts.get(ev["act"])
            if a is not None and a["leave"] is None:
                a["leave"], a["how"] = t, ev["how"]
        elif kind == "hop":
            hops[ev["id"]] = ev
            seq[0] += 1
            hop_seq[ev["id"]] = seq[0]
            w = wires.get(ev["wire"])
            if w is not None and not ev["back"] and w.src != w.dst:
                ks = keys_of(w.dst, ev["lanes"], 1)
                if ev["lanes"] != ():       # a spawn's lane is born with its instance's act
                    for k in ks:
                        born(k, t, prog.wire_unit.get(id(w)), ev["act"])
        elif kind == "land":
            lands[ev["hop"]] = ev
        elif kind == "spawn":
            spawns[ev["inst"]] = (t, ev["wire"][0], ev["parent"])
            owner_of[ev["inst"]] = ev["parent"]
        elif kind == "limit" and ev.get("name") == "depth" and ev.get("act") in acts:
            marks += [Mark(k, t, "base", ev.get("wire")) for k in acts[ev["act"]]["lanes"]]
        elif kind == "await":
            awaits.setdefault(ev["task"], []).append([t, None])
        elif kind == "resume" and awaits.get(ev["task"]):
            awaits[ev["task"]][-1][1] = t
        elif kind == "fork" and ev["why"] == "entry":
            episodes.append((ev["episode"], t, ev["node"]))
        elif kind == "iterate":
            iterations.append(Iteration(t, ev["k"], ev["of"], (ev["owner"], ev["block"]),
                                        ev["act"]))

    moves, last_out, move_acts = [], {}, {}
    for hid, ev in sorted(hops.items()):
        w = wires.get(ev["wire"])
        land = lands.get(hid)
        how = land["how"] if land is not None else ""
        end = land["t"] if land is not None else None
        sender = acts.get(ev["act"])
        src = sender["lanes"] if sender is not None else ()
        if how == "self":
            what = "host" if w is not None and w.call is not None and w.call.external else "self"
            marks += [Mark(k, ev["t"], what, ev["wire"], ev.get("carries")) for k in src]
            continue
        if how == "base" or w is None:
            continue                     # the depth limit's mark says it (limit event)
        if ev["back"]:
            callee = acts.get(ev.get("callee"))
            dst = src
            src = (callee["lanes"] if callee is not None
                   else last_out.get((ev["task"], ev["wire"]), ()))
            move_acts[hid] = (ev.get("callee"), ev["act"])
        elif hid in enters_by_hop:
            dst = acts[enters_by_hop[hid]]["lanes"]
            move_acts[hid] = (ev["act"], enters_by_hop[hid])
        else:
            dst = keys_of(w.dst, ev["lanes"], 1)
            for k in dst:
                born(k, ev["t"], prog.wire_unit.get(id(w)), ev["act"])
        if not ev["back"]:
            last_out[(ev["task"], ev["wire"])] = dst
            for k in dst:                # a lane is born as a hop sets out to it
                if k in lanes:
                    lanes[k]["born"] = min(lanes[k]["born"], (ev["t"], hop_seq[hid] + 0.5))
        if not src or not dst:
            continue
        moves.append(Move(hid, ev["task"], ev["act"], ev["wire"], w.kind, ev["back"], ev["t"],
                          end, how, src, dst, ev.get("attempt"), ev.get("carries")))

    spans = _spans(acts, moves, awaits, last)
    lane_rows = []
    for key, info in lanes.items():
        nid, ordinal, level = key
        inst = (nid, ordinal) if ordinal is not None else None
        sp = spawns.get(inst)
        lane_rows.append(Lane(key, nid, inst, level, info["parent"], info["born"][0],
                              owner_of.get(inst) if inst else None,
                              sp[0] if sp else None, sp[1] if sp else None))
    born_at = {k: v["born"] for k, v in lanes.items()}
    hidden = frozenset()
    if hosts:
        lane_rows, spans, moves, marks, born_at, alias, hidden = _fold_into_hosts(
            lane_rows, spans, moves, marks, born_at, hosts, last)
        move_acts = {h: tuple(alias.get(a, a) for a in ab) for h, ab in move_acts.items()}
        iterations = _hosted_iterations(iterations, alias,
                                        {sp.act for sp in spans if sp.folded}, hosts)
    folded = {"show": show, "instances": 0, "levels": 0}
    if show is not None:
        lane_rows, spans, moves, marks, born_at = _fold_lanes(
            lane_rows, spans, moves, marks, born_at, prog, show, folded)
    lane_rows, spans, moves, marks = _parallel_lanes(lane_rows, spans, moves, marks, born_at,
                                                     move_acts, last)
    return Timeline(_lane_order(lane_rows, born_at), tuple(sorted(spans, key=lambda s: (s.enter, s.act))),
                    tuple(moves), tuple(sorted(marks, key=lambda m: m.t)), tuple(episodes), last,
                    folded, tuple(iterations), dict(hosts or {}), hidden)


def change_ticks(spans, moves) -> set:
    """The ticks something happens: an activation enters or leaves, a hop sets
    out, lands or is about to (its end's tick before)."""
    out = set()
    for s in spans:
        out.add(s.enter)
        if s.leave is not None:
            out.add(s.leave)
    for m in moves:
        out.add(m.start)
        if m.end is not None:
            out |= {m.end, m.end - 1}
    return out


def _hosted_iterations(iterations: list, alias: dict, folded_acts: set, hosts: dict) -> list:
    """Iterations run by a folded node's activation, said of the activation on
    its host's lane: one absorbed into another (alias: {act id absorbed: the
    act id that absorbed it}) by the one that absorbed it, one moved onto the
    host's lane as it is (folded_acts) by itself. Such a loop is `inside` when
    its owner is folded too (hosts), as the narration says `[Host] loops
    (inside)`; a drawn owner's loop stays its own (`loop in [Owner]`). The
    rest as they are."""
    return [it._replace(act=alias.get(it.act, it.act), inside=it.block[0] in hosts)
            if it.act in alias or it.act in folded_acts else it for it in iterations]


def _host_lanes(lanes: list, hosts: dict) -> dict:
    """{folded lane key: its host's lane key}: the nearest lane above it (by
    parent) of a drawn node; with none, the host's level-1 lane outside the
    composition tree."""
    by_key = {ln.key: ln for ln in lanes}
    out = {}
    for ln in lanes:
        if ln.node not in hosts:
            continue
        p, seen = ln.parent, set()
        while p is not None and p in by_key and by_key[p].node in hosts and p not in seen:
            seen.add(p)
            p = by_key[p].parent
        out[ln.key] = p if p in by_key and by_key[p].node not in hosts \
            else (hosts[ln.node], None, 1)
    return out


def _absorbed(host: Span, inner: list, last: int) -> Span:
    """The host's span with the work of the folded spans it runs (its task's,
    within it) taken out of its waits: the fold works while they do. `last`:
    the run's last tick (a span still running then works to it)."""
    work = set()
    for s in inner:
        stop = s.leave if s.leave is not None else last + 1
        busy = set(range(s.enter, max(stop, s.enter + 1)))
        for a, b in s.waits:
            busy -= set(range(a, b))
        work |= busy
    waits = {t for a, b in host.waits for t in range(a, b)} - work
    return host._replace(waits=_ranges(waits))


def _within(s: Span, host: Span) -> bool:
    """Whether span s runs on host's task inside host's activation."""
    return (s.task == host.task and host.enter <= s.enter
            and (host.leave is None or (s.leave is not None and s.leave <= host.leave)))


def _fold_into_hosts(lanes: list, spans: list, moves: list, marks: list, born_at: dict,
                     hosts: dict, last: int) -> tuple:
    """The lanes of folded nodes (hosts) folded into their hosts' (_host_lanes):
    a folded span running inside a host span on its task is absorbed into it
    (_absorbed), any other moves onto the host's lane, marked `folded`, those of
    one task merged into its outermost (_merge_folded); a move between two
    lanes of one fold is left out (the host's own work), any other leaves or
    reaches the host's lane; marks move with their lanes. Also returns {act id
    absorbed: the act id that absorbed it} and the ticks something happens
    inside a fold (change_ticks of the folded lanes' spans and the moves left
    out)."""
    to = _host_lanes(lanes, hosts)
    if not to:
        return lanes, spans, moves, marks, born_at, {}, frozenset()
    r = lambda k: to.get(k, k)
    by_key = {ln.key: ln for ln in lanes}
    out_lanes, out_born = {}, {}
    for ln in lanes:
        key = r(ln.key)
        b = born_at[ln.key]
        if key in out_lanes:
            out_lanes[key] = out_lanes[key]._replace(born=min(out_lanes[key].born, ln.born))
            out_born[key] = min(out_born[key], b)
            continue
        base = by_key.get(key) or Lane(key, key[0], None, 1, None, ln.born, None, None, None)
        out_lanes[key] = base._replace(parent=r(base.parent) if base.parent is not None else None)
        out_born[key] = born_at.get(key, b)
    hosted, inner = [], {}
    for s in spans:
        if s.lane in to:
            inner.setdefault(to[s.lane], []).append(s)
        else:
            hosted.append(s)
    out_spans, taken, alias = [], set(), {}
    for s in hosted:
        mine = [x for x in inner.get(s.lane, ()) if _within(x, s)]
        taken.update(id(x) for x in mine)
        alias.update((x.act, s.act) for x in mine)
        out_spans.append(_absorbed(s, mine, last) if mine else s)
    for lane, ss in inner.items():
        merged, more = _merge_folded([s for s in ss if id(s) not in taken], last)
        out_spans += [s._replace(lane=lane, folded=True) for s in merged]
        alias.update(more)
    out_moves, left_out = [], []
    for m in moves:
        src = tuple(dict.fromkeys(map(r, m.src)))
        dst = tuple(k for k in dict.fromkeys(map(r, m.dst)) if k not in src)
        if (src, dst) == (m.src, m.dst):
            out_moves.append(m)
        elif dst:
            out_moves.append(m._replace(src=src, dst=dst))
        else:
            left_out.append(m)
    out_marks = [mk._replace(lane=r(mk.lane)) for mk in marks]
    hidden = change_ticks([s for ss in inner.values() for s in ss], left_out)
    return (list(out_lanes.values()), out_spans, out_moves, out_marks, out_born, alias,
            frozenset(hidden))


def _merge_folded(spans: list, last: int) -> tuple:
    """Folded spans bound for one host lane, each running inside an earlier
    one on its task (_within) absorbed into that outermost one (_absorbed):
    one activation per stretch of a task's work. Returns (the spans left,
    {act id absorbed: the act id that absorbed it})."""
    outer, inner, alias = [], {}, {}
    for s in sorted(spans, key=lambda x: (x.enter, -(x.leave if x.leave is not None
                                                     else last + 1), x.act)):
        host = next((o for o in outer if _within(s, o)), None)
        if host is None:
            outer.append(s)
        else:
            inner.setdefault(host.act, []).append(s)
            alias[s.act] = host.act
    return [_absorbed(o, inner[o.act], last) if o.act in inner else o for o in outer], alias


def _spans(acts: dict, moves: list, awaits: dict, last: int) -> list:
    """A Span per activation and lane, its waits worked out task by task: an
    activation waits while it is not the top of its task's stack, while a hop
    of its task it sent is out (the send tick is work; a reply's whole flight
    is waiting; the arrival tick of a hop that entered its callee is the
    callee's) and while its task awaits members (the await tick is work, the
    resume tick too)."""
    busy = {}
    for m in moves:
        end = m.end if m.end is not None else last
        lo = m.start if m.back else m.start + 1
        hi = end if m.how == "entered" else end + 1
        busy.setdefault(m.task, set()).update(range(lo, hi))
    for task, spans in awaits.items():
        for a, r in spans:
            busy.setdefault(task, set()).update(range(a + 1, (r if r is not None else last + 1)))
    by_task = {}
    for act, a in acts.items():
        by_task.setdefault(a["task"], []).append(act)
    waiting = {}
    for task, ids in by_task.items():
        enters, leaves = {}, {}
        for act in ids:
            a = acts[act]
            enters.setdefault(a["enter"], []).append(act)
            stop = a["leave"] if a["leave"] is not None else last + 1
            leaves.setdefault(max(stop, a["enter"] + 1), []).append(act)
        lo = min(acts[x]["enter"] for x in ids)
        hi = max(leaves)
        stack, mine = [], busy.get(task, set())
        for t in range(lo, hi):
            for act in leaves.get(t, ()):
                if act in stack:
                    stack.remove(act)
            stack += sorted(enters.get(t, ()))
            for k, act in enumerate(stack):
                if k < len(stack) - 1 or t in mine:
                    waiting.setdefault(act, []).append(t)
    out = []
    for act, a in acts.items():
        ws = _ranges(waiting.get(act, ()))
        for k in a["lanes"]:
            out.append(Span(k, act, a["task"], a["node"], a["enter"], a["leave"], a["how"], ws,
                            a["caller"], a["wire"], a["episode"]))
    return out


def _ranges(ticks) -> tuple:
    """Sorted ticks as ((from, to), …) runs, to exclusive."""
    out = []
    for t in sorted(ticks):
        if out and out[-1][1] == t:
            out[-1][1] = t + 1
        else:
            out.append([t, t + 1])
    return tuple((a, b) for a, b in out)


def _fold_lanes(lanes: list, spans: list, moves: list, marks: list, born_at: dict, prog,
                show: int, folded: dict) -> tuple:
    """The lanes folded (timeline's `show`), and the spans, moves and marks
    moved onto the folds: instances by (node, owner's node), then each lane's
    levels."""
    keep_n = max(show - 1, 1)
    troubled = {s.lane for s in spans if s.how in ("failed", "cancelled")}
    troubled |= {k for m in moves if m.how in ("failed", "cancelled") for k in m.dst}
    owner_node = lambda ln: ln.owner[0] if ln.owner else None
    groups = {}
    for ln in lanes:
        if ln.inst is not None and ln.level == 1:
            groups.setdefault((ln.node, owner_node(ln)), []).append(ln)
    remap, made = {}, {}
    for (nid, onode), group in groups.items():
        if len(group) <= show:
            continue
        group.sort(key=lambda ln: ln.inst[1])
        rest = [ln for ln in group[keep_n:] if ln.key not in troubled]
        if len(rest) < 2:
            continue
        tag = FOLD + (onode or "")
        for ln in rest:
            remap[ln.key] = (nid, tag, 1)
        made[(nid, tag, 1)] = rest
        folded["instances"] += len(rest)
    for ln in lanes:                    # a folded instance's levels go with it
        if ln.level > 1 and (ln.node, ln.key[1], 1) in remap:
            remap[ln.key] = (ln.node, remap[(ln.node, ln.key[1], 1)][1], ln.level)
    deep, inst = {}, dict(remap)        # bases by the instance folds only
    for ln in lanes:
        base = inst.get((ln.node, ln.key[1], 1), (ln.node, ln.key[1], 1))
        deep[base] = max(deep.get(base, 1), ln.level)
    for ln in lanes:
        base = inst.get((ln.node, ln.key[1], 1), (ln.node, ln.key[1], 1))
        top = deep[base]
        if top > show + 1 and show <= ln.level < top:
            remap[ln.key] = (base[0], base[1], f"{show}‥{top - 1}")
            folded["levels"] += 1
    if not remap:
        return lanes, spans, moves, marks, born_at
    r = lambda k: remap.get(k, k)
    out, seen = {}, {}
    for ln in lanes:
        key = r(ln.key)
        parent = r(ln.parent) if ln.parent is not None else None
        b = born_at[ln.key]
        if key in out:
            out[key] = out[key]._replace(born=min(out[key].born, ln.born))
            seen[key] = min(seen[key], b)
            continue
        seen[key] = b
        if key == ln.key:
            out[key] = ln._replace(parent=parent)
        elif isinstance(key[2], str):               # a fold of levels
            lo, hi = (int(x) for x in key[2].split("‥"))
            out[key] = ln._replace(key=key, level=lo, parent=parent, levels=(lo, hi))
        else:                                       # a fold of instances (or its levels)
            group = made.get(key, ())
            out[key] = ln._replace(key=key, inst=None, parent=parent,
                                   fold=tuple(g.inst for g in group),
                                   owners=tuple(dict.fromkeys(g.owner for g in group
                                                              if g.owner is not None)))
    spans = list({(r(s.lane), s.act): s._replace(lane=r(s.lane)) for s in spans}.values())
    moves = [m._replace(src=tuple(dict.fromkeys(map(r, m.src))),
                        dst=tuple(dict.fromkeys(map(r, m.dst)))) for m in moves]
    marks = list(dict.fromkeys(m._replace(lane=r(m.lane)) for m in marks))
    return list(out.values()), spans, moves, marks, seen


def _parallel_lanes(lanes: list, spans: list, moves: list, marks: list, born_at: dict,
                    move_acts: dict, last: int) -> tuple:
    """The lanes with a `∥k` sub-row for each activation that ran while one on
    its lane was still going (a lane's activations on different tasks at
    once), and the spans, moves and marks moved onto them: each activation
    takes the first row of its lane free from its enter (a failed or
    cancelled one keeps the cell after it, for its ✕ / ⊘). A fold stays one
    row. `born_at` gains the sub-rows; `move_acts`: {hop id: (the act it
    leaves, the act it lands in)}."""
    by_lane = {}
    for s in spans:
        by_lane.setdefault(s.lane, []).append(s)
    lane_of = {ln.key: ln for ln in lanes}
    moved, made = {}, {}                    # (lane, act) → its sub-row key; key → [Span]
    for key, ss in by_lane.items():
        ln = lane_of.get(key)
        if ln is None or ln.fold or ln.levels:
            continue
        for s, row in _first_free_rows(ss, last):
            if row:
                sub = key + (row + 1,)
                moved[(key, s.act)] = sub
                made.setdefault(sub, []).append(s)
    if not made:
        return lanes, spans, moves, marks

    def to(key, act):
        return moved.get((key, act), key)

    out_moves = []
    for m in moves:
        a, b = move_acts.get(m.id, (None, None))
        out_moves.append(m._replace(src=tuple(to(k, a) for k in m.src),
                                    dst=tuple(to(k, b) for k in m.dst)))
    ticks = {}                              # lane → the ticks its marks are at
    for mk in marks:
        ticks.setdefault(mk.lane, set()).add(mk.t)
    running = {lane: _running_at(by_lane.get(lane, ()), ts) for lane, ts in ticks.items()}
    out_marks = []
    for mk in marks:                        # on the row of the activation then running
        s = running[mk.lane].get(mk.t)
        out_marks.append(mk._replace(lane=to(mk.lane, s.act)) if s is not None else mk)
    arrive = {}                             # sub-row → the earliest move onto it
    for m in out_moves:
        for k in m.dst:
            if k in made:
                arrive[k] = min(arrive.get(k, m.start), m.start)
    out_lanes = list(lanes)
    for sub, ss in made.items():
        base = lane_of[sub[:-1]]
        first = min([s.enter for s in ss] + ([arrive[sub]] if sub in arrive else []))
        out_lanes.append(base._replace(key=sub, parent=base.key, born=first, par=sub[-1]))
        born_at[sub] = (first, born_at[base.key][1])
    out_spans = [s._replace(lane=to(s.lane, s.act)) for s in spans]
    return out_lanes, out_spans, out_moves, out_marks


def _first_free_rows(spans: list, last: int) -> list:
    """[(span, row)] in (enter, act) order: each activation on the lowest row
    free at its enter, a row free from its activation's leave (a run's end
    + 1 for one still running; a failed or cancelled one a tick later, for
    its ✕ / ⊘). Enters only grow, so a row once free stays free: busy rows wait
    on a heap by the tick they free, free ones on a heap by row."""
    busy, free, rows, out = [], [], 0, []
    for s in sorted(spans, key=lambda s: (s.enter, s.act)):
        while busy and busy[0][0] <= s.enter:
            heapq.heappush(free, heapq.heappop(busy)[1])
        if free:
            row = heapq.heappop(free)
        else:
            row, rows = rows, rows + 1
        stop = max(s.leave if s.leave is not None else last + 1, s.enter + 1)
        heapq.heappush(busy, (stop + (s.how in ("failed", "cancelled")), row))
        out.append((s, row))
    return out


def _running_at(spans, ticks) -> dict:
    """{tick: the span running at it}, for each tick in `ticks` some span of
    `spans` runs at ([enter, max(leave, enter + 1)), open when leave is None):
    the latest in `spans`' order when several do. A sweep over the ticks in
    order: spans join a heap by their place as they enter, and leave it once
    they ended (lazily, when they surface)."""
    order = sorted(range(len(spans)), key=lambda k: spans[k].enter)
    heap, nxt, out = [], 0, {}
    for t in sorted(ticks):
        while nxt < len(order) and spans[order[nxt]].enter <= t:
            k = order[nxt]
            s = spans[k]
            heapq.heappush(heap, (-k, None if s.leave is None else max(s.leave, s.enter + 1)))
            nxt += 1
        while heap and heap[0][1] is not None and heap[0][1] <= t:
            heapq.heappop(heap)
        if heap:
            out[t] = spans[-heap[0][0]]
    return out


def _lane_order(lanes: list, born_at: dict) -> tuple:
    """The lanes in drawing order: by birth, each lane's recursion levels
    right under it (by depth), each row's ∥ sub-rows right under that row,
    then its other children (an expansion's lanes) the same way; the instances of one node among siblings together, in
    ordinal order, where the first of them was born."""
    kids, roots = {}, []
    by_key = {ln.key: ln for ln in lanes}
    for ln in lanes:
        if ln.parent is not None and ln.parent in by_key and ln.parent != ln.key:
            kids.setdefault(ln.parent, []).append(ln)
        else:
            roots.append(ln)

    def ordinal(ln):
        return ln.inst[1] if ln.inst is not None else (ln.fold[0][1] if ln.fold else 0)

    def order(group: list) -> list:
        group = sorted(group, key=lambda ln: born_at[ln.key])
        out, done = [], set()
        for ln in group:
            if ln.node in done:
                continue
            done.add(ln.node)
            same = [x for x in group if x.node == ln.node]
            out += sorted(same, key=lambda x: (x.level, ordinal(x), born_at[x.key]))
        return out

    out, seen = [], set()

    def walk(group: list) -> None:
        for ln in order(group):
            if ln.key in seen:
                continue
            seen.add(ln.key)
            out.append(ln)
            mine = kids.get(ln.key, [])
            levels = sorted((x for x in mine if x.node == ln.node and x.level > 1
                             and x.par == 1), key=lambda x: x.level)
            for x in [ln] + levels:             # each row's ∥ sub-rows right under it
                if x is not ln:
                    seen.add(x.key)
                    out.append(x)
                for y in sorted((y for y in kids.get(x.key, ()) if y.par > 1),
                                key=lambda y: y.par):
                    seen.add(y.key)
                    out.append(y)
            walk([x for x in mine if x not in levels and x.par == 1])

    walk(roots)
    out += [ln for ln in lanes if ln.key not in seen]
    return tuple(out)


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


def _nearest_drawn(canon, nid: str, drawn: set) -> Optional[str]:
    """nid when it is drawn, else the owner of the nearest drawn unit around
    it (None: none)."""
    host, seen = nid, set()
    while host is not None and host not in drawn and host not in seen:
        seen.add(host)
        host = canon.nodes[host].unit if host in canon.nodes else None
    return host


def host_map(canon, view) -> dict:
    """{node id: the drawn node standing for it}: itself when the view draws it,
    else the owner of the nearest drawn unit around it; collapsed events none."""
    drawn = {nid for u in view.units for nid in u.graph.nodes} - set(view.collapsed)
    return {nid: None if nid in view.collapsed else _nearest_drawn(canon, nid, drawn)
            for nid in canon.nodes}


def folded_hosts(canon, depth: int) -> dict:
    """{node id: the drawn node standing for it} for each node of the canonical
    scene inside an expansion a view drawn to `depth` folds (the owner of the
    nearest drawn unit around it, as host_map); a drawn node is absent. The
    hosts timeline(), narrate() and hops() fold a run by. Pure."""
    drawn = {nid for u in scene_mod.drawn_units(canon.graph, depth) for nid in u.graph.nodes}
    out = {}
    for nid in canon.nodes:
        host = _nearest_drawn(canon, nid, drawn)
        if host is not None and host != nid:
            out[nid] = host
    return out


def folded_wire(w, hosts: dict) -> bool:
    """Whether wire w runs wholly inside a fold: an end of it folded and both
    ends standing for the same drawn node (the host's own work)."""
    return ((w.src in hosts or w.dst in hosts)
            and hosts.get(w.src, w.src) == hosts.get(w.dst, w.dst))


def folded_details(summaries: dict, idmap: dict) -> dict:
    """{detail ident: its hits}, for each detail a view does not draw (its
    expansion folded, as at --depth 0): the hits of the innermost summary of it
    the view draws, composed. A summary carries its detail's traffic as the
    folded node's own wire, so its token rides the summary there; where the
    detail is drawn it rides the detail and the summary is only lit.
    `summaries`: Program.summaries; `idmap`: ident_map's."""
    by_detail = {}
    for s, details in summaries.items():
        for d in details:
            by_detail.setdefault(d, []).append(s)
    out = {}
    for d, sums in by_detail.items():
        if idmap.get(d):
            continue
        drawn = [s for s in sums if idmap.get(s)]
        inner = [s for s in drawn if not any(t in summaries[s] for t in drawn if t != s)]
        hits = [(v, o, sc) for s in inner for v, o, sc in idmap[s]]
        if hits:
            out[d] = tuple(dict.fromkeys(hits))
    return out


# How busy a node state is: a folded host shows its busiest member's.
_BUSY = {"active": 5, "waiting": 4, "failed": 3, "visited": 2, "opaque": 1, "cancelled": 0}


def _project_frame(f: Frame, idmap: dict, hosts: dict, tokmap: dict) -> Frame:
    tokens = tuple(f_tok._replace(wire=v, at=round(off + scale * f_tok.at, 4))
                   for f_tok in f.tokens for v, off, scale in tokmap.get(f_tok.wire, ()))
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
    draw folded into the drawn owner (busiest status wins), and a token on a
    detail it does not draw on the summary standing for it (folded_details).
    Pure."""
    idmap = ident_map(trace.scene, view)
    hosts = host_map(trace.scene, view)
    summaries = _program_of(trace.scene.graph).summaries or {}
    tokmap = {**idmap, **folded_details(summaries, idmap)}
    frames = tuple(_project_frame(f, idmap, hosts, tokmap) for f in trace.frames)
    return trace._replace(frames=frames, scene=view)


# ---------------------------------------------------------------------------
# Narration — a run in plain words, one Beat per frame where something happens
# (the views' narration line and recent-events log, the playground, --sim's
# text and JSON). Pure: read from the frames and the structured events, never
# from the log's text.

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
    a machine state as a transition writes it); a folded node (hosts,
    folded_hosts) by its host's."""

    def __init__(self, scn, hosts: Optional[dict] = None):
        self.scn = scn
        self.hosts = hosts or {}
        self.wires = {w.ident: w for w in scn.wires}

    def name(self, nid) -> str:
        sn = self.scn.nodes.get(self.hosts.get(nid, nid))
        if sn is not None:
            return node_label(sn.node)
        return scene_mod.decision_name(self.scn, nid) or str(nid)

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
    """The (episode, sentence) pairs of the tokens setting out in a frame: one per
    wire, a fan-out (several wires of one kind out of one source, one payload,
    one episode) as one."""
    groups: dict = {}
    for tok in tokens:
        w = wd.wires[tok.wire]
        groups.setdefault((w.src, w.kind, tok.carries, tok.attempt, tok.episode),
                          []).append((w, tok))
    out = []
    for (src, kind, what, _a, ep), members in groups.items():
        out.append((ep, _departure(wd, src, kind, what, members, frame)))
    return out


def _departure(wd: _Words, src: str, kind: str, what, members: list, frame) -> str:
    """The sentence of one group of departing tokens (_departures): [(wire, token)]
    out of `src` along `kind` wires, carrying `what`."""
    w, tok = members[0]
    dsts = _listed(list(dict.fromkeys(wd.name(m.dst) for m, _t in members)))
    who = wd.name(src)
    with_ = f" with {what}" if what else ""
    if w.role == "trigger":
        owners = _listed(list(dict.fromkeys(wd.name(m.machine or m.dst) for m, _t in members)))
        return f"{who} drives {owners}"
    if w.src == w.dst or (w.call is not None and w.call.self_call):
        return _self_call_text(wd, w, tok, frame)
    if kind == "~>":
        if all(wd.kind(m.dst) == "event" for m, _t in members):
            return f"{who} emits {dsts}"
        return f"{who} sends {what + ' ' if what else ''}to {dsts} without waiting"
    if kind == "*>":
        return f"{who} fans out to {dsts}"
    if kind == "=>":
        return (f"{who} produces {dsts}" if all(wd.kind(m.dst) == "data" for m, _t in members)
                else f"{who} produces {what + ' ' if what else ''}into {dsts}")
    if kind == "?>":
        return f"{who} takes the optional path to {dsts}"
    if kind in ("->", "→") and all(wd.kind(m.dst) == "data" for m, _t in members):
        return f"{who} produces {dsts}"
    if kind in ("->", "→", "<->"):
        return f"{who} calls {dsts}{with_}{_attempt(tok)}"
    return f"{who} {kind} {dsts}{with_}"


def _token_sentences(wd: _Words, frame) -> list:
    """What a frame's tokens say, as (episode, sentence) pairs: hops setting out
    (a `!>` route is said by its route event, a branch arm by its choice),
    replies and fallbacks setting back, attempts failing on arrival, calls
    cancelled."""
    leaving, out = [], []
    for tok in frame.tokens:
        w = wd.wires.get(tok.wire)
        if w is None or w.kind == "!>" or w.role == "arm" or folded_wire(w, wd.hosts):
            continue
        if tok.dir == "out" and tok.at == 0.0 and tok.state == "moving":
            leaving.append(tok)
            continue
        text = _token_sentence(wd, w, tok)
        if text:
            out.append((tok.episode, text))
    return _departures(wd, leaving, frame) + out


def _token_sentence(wd: _Words, w, tok) -> Optional[str]:
    """What one token on wire `w` says that is not a departure (_token_sentences),
    or None."""
    if tok.state == "cancelled":
        return f"the call to {wd.name(w.dst)} is cancelled"
    if tok.dir == "out" and tok.at == 1.0 and tok.state == "failed":
        if w.src == w.dst or (w.call is not None and w.call.self_call):
            return f"{wd.name(w.src)}'s {tok.carries or 'call'} fails{_attempt(tok)}"
        return f"{tok.carries or 'the call'} to {wd.name(w.dst)} fails{_attempt(tok)}"
    if tok.dir == "back" and tok.at == 1.0 and tok.state == "fallback":
        return f"{wd.name(w.src)} falls back to {tok.carries}"
    if tok.dir == "back" and tok.at == 1.0:
        return (f"{wd.name(w.dst)} returns {tok.carries} to {wd.name(w.src)}"
                if tok.carries else f"{wd.name(w.dst)} replies to {wd.name(w.src)}")
    return None


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


def _inside_fold(wd: _Words, ev: dict) -> bool:
    """Whether an event happens wholly inside a fold (wd.hosts): it is a folded
    node's, a folded machine's, or on a wire running inside the fold."""
    if any(ev.get(k) in wd.hosts for k in ("node", "owner")):
        return True
    w = wd.wires.get(ev.get("wire"))
    return w is not None and folded_wire(w, wd.hosts)


def _event_sentence(wd: _Words, ev: dict, scn) -> Optional[str]:
    if _inside_fold(wd, ev):
        return None
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


def _loop_subject(wd: _Words, owner: Optional[str]) -> str:
    """Who a loop is said of, by the owner of the unit it runs in (None: the
    document): `loop in [Checkout]`; an owner folded into a drawn host
    (wd.hosts) is not drawn, so the host loops inside: `[Shop] loops (inside)`."""
    if owner is None:
        return "loop"
    if owner in wd.hosts:
        return f"{wd.name(owner)} loops (inside)"
    return f"loop in {wd.name(owner)}"


def _changes(wd: _Words, prev, f) -> list:
    """What changed from the previous frame that no event says, as (subject node
    id or None, sentence) pairs: a loop's iteration (its unit's owner), a store
    held or let go by an `owns` block, another instance, a node cancelled (a
    race lost, a waiter's other members)."""
    out = []
    for nid, st in f.nodes.items():
        if (st == "cancelled" and nid not in wd.hosts
                and (prev is None or prev.nodes.get(nid) != st)):
            out.append((nid, f"{wd.name(nid)} is cancelled"))
    for key, k in f.loops.items():
        if prev is None or prev.loops.get(key) != k:
            out.append((key[0], f"{_loop_subject(wd, key[0])}: iteration {k}"))
    if prev is not None:
        for nid in sorted(f.held_resources - prev.held_resources - wd.hosts.keys(), key=str):
            out.append((nid, f"{wd.name(nid)} is held"))
        for nid in sorted(prev.held_resources - f.held_resources - wd.hosts.keys(), key=str):
            out.append((nid, f"{wd.name(nid)} is released"))
        for nid, k in f.instances.items():
            if nid not in wd.hosts and k > prev.instances.get(nid, k):
                out.append((nid, f"{wd.name(nid)} gets another instance ({k} now)"))
    return out


_SUBJECT_KEYS = ("node", "store", "owner")


def _subject_episodes(events, known: dict) -> dict:
    """`known` ({node id: episode}) updated by `events`: each node, store or
    machine owner an event names belongs to the episode of the task that acted
    on it last (events of the run itself, task None, name none)."""
    out = dict(known)
    for ev in events:
        if ev.get("task") is not None:
            for key in _SUBJECT_KEYS:
                if ev.get(key) is not None:
                    out[ev[key]] = ev["episode"]
    return out


def _begun(trace: Trace, f, episode: int) -> list:
    """[(k, entry node id)] of the episodes begun since `episode` by frame f, in
    start order (the frame's own episode and entry when the trace lists none)."""
    listed = [(b["episode"], b["entry"]) for b in trace.end.get("episodes", ())
              if episode < b["episode"] <= f.episode]
    return listed or [(f.episode, f.entry)]


def _prefixed(pairs: list, overlapping: bool) -> list:
    """The sentences of (episode or None, sentence) pairs, each led by `ep{k}: `
    while episodes overlap (one with no episode as it is)."""
    if not overlapping:
        return [text for _k, text in pairs]
    return [f"ep{k}: {text}" if k is not None else text for k, text in pairs]


def narrate(trace: Trace, hosts: Optional[dict] = None) -> tuple:
    """(Beat, …): the run in plain words, a Beat for every frame where something
    happens — an episode beginning, a hop setting out (`[API] calls [Payments]
    with charge(total) — attempt 2 of 4`), a reply or fallback, an attempt
    failing, a call giving up, a route, a transition, a join, a bound, the end.
    Over the scene the trace names (the canonical one, or project()'s). `hosts`
    (folded_hosts; None: every node drawn): a folded node is named by its host
    and what happens wholly inside a fold is not said. While a frame's episodes
    overlap (more than one runs), each sentence is led by its episode, `ep2: `
    (an event's, a token's task's, a change's subject's last acting task's;
    the run's end is not). Pure."""
    scn = trace.scene
    wd = _Words(scn, hosts)
    by_tick: dict = {}
    for ev in trace.end.get("events", ()):
        by_tick.setdefault(ev["t"], []).append(ev)
    ticks = sorted(by_tick)
    beats, prev, episode, subjects, folded = [], None, 0, {}, 0
    for i, f in enumerate(trace.frames):
        pairs = []
        events = by_tick.get(f.tick, ())
        while folded < len(ticks) and ticks[folded] <= f.tick:   # subjects as of f.tick
            subjects = _subject_episodes(by_tick[ticks[folded]], subjects)
            folded += 1
        if f.episode != episode and f.entry is not None:
            pairs += [(k, f"episode {k} begins at {wd.name(nid)}")
                      for k, nid in _begun(trace, f, episode)]
            episode = f.episode
        pairs += [(subjects.get(nid), text) for nid, text in _changes(wd, prev, f)]
        pairs += [(ev["episode"], s) for ev in events
                  for s in (_event_sentence(wd, ev, scn),) if s]
        pairs += _token_sentences(wd, f)
        if f.done:
            pairs.append((None, f"the run ends: {trace.outcome}"))
            stalled = trace.end.get("stalled") or []
            if stalled:
                pairs.append((None, "left waiting: " + _listed([wd.name(n) for n in stalled])))
        said = list(dict.fromkeys(_prefixed(pairs, len(f.episodes) > 1)))
        if said:
            beats.append(Beat(i, f.tick, "; ".join(said)))
        prev = f
    return tuple(beats)


def hops(trace: Trace, hosts: Optional[dict] = None) -> tuple:
    """(Hop, …): every hop the run sets out on, in order (the frame it leaves in,
    the wire's ends and arrow, the last frame its token is on the wire and how it
    ended there: an attempt failing on arrival "failed", a call cancelled on the
    way or on arrival — a race's loser — "cancelled") — the path a view writes out. A reply going back is no hop;
    a `!>` route is (it travels as a failure, but it is no failed hop).
    `hosts` (folded_hosts; None: every node drawn): a hop's folded end is its
    host, and a hop wholly inside a fold is left out."""
    hosts = hosts or {}
    wires = {w.ident: w for w in trace.scene.wires if not folded_wire(w, hosts)}
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
                out.append([i, hosts.get(w.src, w.src), w.kind, hosts.get(w.dst, w.dst), i,
                            "", tok.state, w.dst])
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
            if (key not in seen and not h[5] and f.nodes.get(h[7]) == "cancelled"
                    and trace.frames[i - 1].nodes.get(h[7]) != "cancelled"):
                h[4], h[5] = i, "cancelled"
        live = seen
    return tuple(Hop(*h[:6]) for h in out)
