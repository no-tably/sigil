"""
The engine: one run of a scenario over a Program — tasks, flights, failures,
entries and when each episode begins (simulate → Trace). _Run holds the only
mutable state and lives only inside simulate(). The rules it applies are the
package's docstring (sigil.model.sim, THE RUN).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import NamedTuple, Optional

from sigil.core.graph import node_label
from sigil.model import scene as scene_mod
from sigil.model.sim.program import (
    Frame, Group, Instance, Limits, Program, Region, Scenario, Step, Token, Trace, TriggerRef,
    _alias_of, _beneath, _declared_times, _detached, _flat, _gate_of, _guards, _home,
    _one_of_groups, _owned_stores, _program_of, _pseudo, _running, _select, _summed, _tally,
    attempts, carried, instances, loop_count, mod, resilient, returned,
    scaled, selected_routes)


CONVENTIONS = ("conventions: written order; entries one after another; ?> not taken "
               "by default; the first member wins a race / alternative / branch")


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
    id: int = 0                # run-wide hop number (the `hop` event's id)
    land: Optional[dict] = None    # its `land` event, once it has one


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
    popped: Optional[int] = None                  # the act that left its stack last


class _Run:
    """One simulation: tasks, activations, machines, instances; tick() makes Frames."""

    def __init__(self, prog: Program, sc: Scenario, limits: Limits, keep: bool = True):
        limits = scaled(limits, prog)  # the defaults grown to the document's size
        self.prog, self.limits, self.keep = prog, limits, keep
        self.choices = dict(sc.choices)
        self.entries = _scheduled(_resolve_entries(prog, sc.entries), sc.starts)
        self.t, self.episode, self.entry = 0, 0, None
        self.episode_t = 0             # the tick the latest episode began
        self.begun: list = []          # Trace.end["episodes"], in start order
        self.quiet = False             # the run went quiet and no episode began since
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
        self.hop_n = 0                 # hops numbered so far (the `hop` event's id)
        self.loops, self.blocks, self.held = {}, Counter(), Counter()
        self.loops_most: dict = {}     # (owner, block index) → the most iterations it ran
        self.visits = Counter()        # (episode, node) → task-root activations
        self.activations = Counter()   # episode → activations
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
        due = set(_due(self.entries, t, self.start_next, opening=not self.begun))
        begin = [e for i, e in enumerate(self.entries) if i in due]
        self.entries = [e for i, e in enumerate(self.entries) if i not in due]
        for entry in begin:                     # written order
            self._begin_episode(entry)
        self.start_next = False
        k = 0
        while k < len(self.alive) and not self.done:
            task = self.alive[k]
            k += 1
            if not task.ended and task.resume == t:
                self._advance(task)
        self._wake()
        pending = any(not x.ended and x.resume is not None for x in self.alive)
        if not self.done and not pending:
            if not self.quiet:
                self.quiet = True
                self._event("quiet", None, waiting=[x.id for x in self.alive
                                                    if not x.ended and x.wait is not None])
            if any(e.start is None for e in self.entries):
                self.start_next = True
            elif not self.entries:
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

    def _begin_episode(self, entry: _Entry) -> None:
        ui, nid = entry.ui, entry.node
        self.episode += 1
        self.entry = nid
        self.episode_t = self.t
        self.quiet = False
        self.begun.append({"episode": self.episode, "entry": nid, "start": self.t})
        self._log(f"episode {self.episode}: {self._name(nid)}")
        self._fork(lambda task: self._entry_gen(task, ui, nid), why="entry", node=nid)

    def _fork(self, factory, parent: Optional[_Task] = None, *, why: str,
              wire=None, node: Optional[str] = None) -> _Task:
        """A new task running factory(task); it starts inside the control blocks its
        parent runs at the fork (a region it re-enters there is a plain scope).
        `why` names the fork site (the `fork` event); an "entry" task is an
        episode's root (the latest begun), any other is its parent's episode's."""
        task = _Task(len(self.tasks) + 1, resume=self.t, entry=why == "entry",
                     episode=parent.episode if parent is not None else self.episode)
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
                ep = task.episode
                self._event("stop", task, how="entry", node=self.begun[ep - 1]["entry"],
                            guard=f.guard)
                self._log(f"episode {ep} failed")
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
            if fl.land is None:
                self._landed(task, fl, "cancelled")
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
                     state or fl.state, fl.carries, fl.reach, fl.attempt, fl.act, task.episode)

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
        lit = _summed(self.prog, in_flight | open_ | self.lit_now)
        running = {x.episode for x in self.alive if not x.ended and x.wait is None}
        running |= {tok.episode for tok in tokens}
        return Frame(
            self.t, self.episode, self.entry, tuple(tokens),
            lit, frozenset(open_ - in_flight),
            _summed(self.prog, self.taken), _summed(self.prog, self.failed_w),
            dict(self.status), depth,
            dict(self.machines), frozenset(self.changed), self._instances(),
            dict(self.loops), frozenset(k for k, n in self.blocks.items() if n > 0),
            frozenset(k for k, n in self.held.items() if n > 0), tuple(self.lines), self.done,
            frozenset(running))

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
                "events": list(self.events), "episodes": [dict(b) for b in self.begun]}

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
        return node_label(sn.node)

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
             state: str = "moving", carries=None, reach: int = 1, attempt=None,
             lands: Optional[str] = None):
        """Move a token along w; returns its flight at the arrival tick. A `hop`
        event (numbered run-wide: its id) names the activation it sets out from,
        going out into a composition node the instances it reaches (its lanes),
        the attempt and what it carries; a reply also names the callee it leaves
        (the activation that just left the task's stack). On arrival a `land`
        event says how it ended: `lands`, else "returned" / "fallback" for a
        reply, else "arrived" until _land or _push say more."""
        sender = self._sender(task)
        self.hop_n += 1
        fl = _Flight(w.ident, back, dur or self.limits.hop, state, carries, reach, attempt,
                     act=sender.id if sender is not None else None, id=self.hop_n)
        lanes = None if back else self._lanes(w, sender)
        extra = {"callee": task.popped if state != "fallback" else None} if back else {}
        self._event("hop", task, id=fl.id, act=fl.act, wire=w.ident, back=back, lanes=lanes,
                    attempt=attempt, carries=carries, **extra)
        yield ("hop", fl)
        how = lands or (("fallback" if state == "fallback" else "returned") if back
                        else "arrived")
        self._landed(task, fl, how)
        if not back and state != "failed":
            self.taken.add(w.ident)
        return fl

    def _landed(self, task: _Task, fl: _Flight, how: str) -> None:
        """The `land` event of a flight: where it ended (the wire's far end, a
        reply's near one) and how — entered | reached | opaque | base | none |
        visits | arrived (refined by _land / _push) | failed | cancelled |
        returned | fallback | self."""
        w = self.wires.get(fl.wire)
        node = (w.src if fl.back else w.dst) if w is not None else None
        self._event("land", task, hop=fl.id, node=node, how=how)
        fl.land = self.events[-1]

    def _arrival(self, task: _Task, how: str) -> None:
        """Say how the flight that has just landed (the task's) ended at its node."""
        fl = task.flight
        if fl is not None and fl.land is not None and fl.land["t"] == self.t:
            fl.land["how"] = how

    def _push(self, task: _Task, ui: int, nid: str, cause) -> _Act:
        """A new activation of nid on the task (cause: the wire ident that
        started it, None for an entry), numbered run-wide; an `enter` event
        names its caller (the activation whose hop or fork started it; None for
        an episode's entry), its level on the stack and its lanes."""
        self.activations[task.episode] += 1
        if self.activations[task.episode] > self.limits.activations:
            raise _Cut("activations")
        if len(task.stack) >= self.limits.stack:
            raise _Cut("stack")
        caller = self._sender(task)
        if task.stack:
            self.status[task.stack[-1].node] = "waiting"
        self.acts += 1
        level = 1 + sum(1 for a in task.stack if a.node == nid)
        act = _Act(nid, ui, cause, self.acts, self._act_lanes(nid, cause, caller), level)
        fl, hop = task.flight, None
        if (cause is not None and fl is not None and fl.wire == cause and fl.land is not None
                and fl.land["t"] == self.t and not fl.back):
            fl.land["how"], hop = "entered", fl.id
        task.stack.append(act)
        self.status[nid] = "active"
        self._event("enter", task, act=act.id, caller=caller.id if caller is not None else None,
                    node=nid, unit=ui, level=level, insts=act.insts, wire=cause, hop=hop)
        return act

    def _pop(self, task: _Task, act: _Act, status: str) -> None:
        if task.stack and task.stack[-1] is act:
            task.stack.pop()
        task.popped = act.id
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
                 else _running(self.prog, self.prog.bodies.get((act.ui, act.node), ())))
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
        task.popped = None              # a reply names the callee only when one ran
        if w.kind == "=>":
            self._spawn(task, w)
        self._access(task, w, "done")
        if self._reach_of(w, task) == 0:
            self._log(f"no instance of {self._name(dst)}")
            self._arrival(task, "none")
            yield ("turn",)
            return
        if sn is not None and (sn.node.is_hole or sn.external
                               or (w.call is not None and w.call.external)):
            self.status[dst] = "opaque"
            self._arrival(task, "opaque")
            yield ("turn",)
            return
        if sn is not None and sn.node.kind == "actor":
            self.status[dst] = "visited"
            self._arrival(task, "reached")
            yield ("turn",)
            return
        if not task.stack:              # a task's root: what an async cycle repeats
            self.visits[task.episode, dst] += 1
            if self.visits[task.episode, dst] > self.limits.visits:
                self._event("limit", task, name="visits", node=dst)
                self._log(f"visit limit: {self._name(dst)}")
                self._arrival(task, "visits")
                yield ("turn",)
                return
        alias = _alias_of(self.prog, w)
        if (self._depth_capped(task, dst, w.ident)
                or (alias and self._depth_capped(task, alias[1], w.ident))):
            self._arrival(task, "base")
            yield ("turn",)
            return
        ui = self._ui(w) if arm is not None else _home(self.prog, self._ui(w), dst)
        yield from self._activate(task, ui, dst, w.ident, arm, alias)

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
                                      attempt=(k, a), lands="failed")
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
        yield from self._hop(task, w, dur=1, carries=carried(w), lands="self")
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
        fl = yield from self._hop(task, w, carries=carried(w), lands="cancelled")
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
                    self._event("iterate", task, owner=key[0], block=r.index, k=k, of=n,
                                act=task.stack[-1].id if task.stack else None)
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


# ---------------------------------------------------------------------------
# Entries — which entry begins when
# ---------------------------------------------------------------------------

class _Entry(NamedTuple):
    """An entry still to begin: its unit, its node and the tick it begins at (None:
    the tick after the run goes quiet, entries one after another)."""
    ui: int
    node: str
    start: Optional[int]


def _scheduled(entries: list, starts) -> list:
    """[_Entry] in written order: each of `entries` ((ui, node id)) with the start
    tick `starts` ((node id, tick) pairs or a dict) gives it. Raises KeyError for a
    start naming no entry, ValueError for a tick that is not a whole number ≥ 0."""
    ticks = dict(starts or ())
    named = {nid for _ui, nid in entries}
    for nid, t in ticks.items():
        if nid not in named:
            raise KeyError(f"no entry {nid!r} to start")
        if isinstance(t, bool) or not isinstance(t, int) or t < 0:
            raise ValueError(f"start of {nid!r}: {t!r} is not a tick")
    return [_Entry(ui, nid, ticks.get(nid)) for ui, nid in entries]


def _due(entries: list, t: int, quiet: bool, opening: bool = False) -> list:
    """The indices of `entries` (_Entry) that begin at tick t, in written order:
    each whose start tick has come, and — when the run went quiet (`quiet`) — the
    first with none. At the run's opening (`opening`: no episode begun yet) that one
    waits when an entry written before it begins at t: it follows that episode as it
    would follow any other (`Operator@0` runs as the happy run does)."""
    timed = [i for i, e in enumerate(entries) if e.start is not None and e.start <= t]
    free = next((i for i, e in enumerate(entries) if e.start is None), None) if quiet else None
    if free is not None and opening and timed and timed[0] < free:
        free = None
    return sorted(timed + ([free] if free is not None else []))


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
    unknown entry or a start (Scenario.starts) naming no entry, ValueError for a
    start tick that is not a whole number ≥ 0."""
    return _simulate(_program_of(sc.graph), scenario, limits, keep)


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
