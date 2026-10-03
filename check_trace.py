"""
check_trace.py — the behavioural rules: what the simulator's runs show.

Not a command: check.py loads it (RULE_MODULES) and calls `rules(ck)`,
`exploration_causes(ck)` and `extend_rules(ck, rules)` with itself as `ck`, so
this module never imports check.py. Every rule here reads the runs of the
document's bounded exploration (sim.combinations over the canonical scene, up
to `doc.k` deviations at once, at most `doc.budget` runs (default BUDGET), each
under `doc.limits`) and reports a candidate as a trace Hit: its witness is the scenario that shows it, `k` the deviations that
scenario takes (rfcs/0003-composition-checks.catalog.md §3).

Rules this module registers:
  SGC203 event-ignored      an event reaches its machine in a state with no
                            transition for it, and it is dropped in every order
  SGC206 stalled-join       a run ends with a join still open
  SGC175 unreached          a construct no entry reaches (static, over
                            sim.reachable; a hint)
  SGC090 exploration-incomplete — its run causes: the budget left combinations
                            out, a run was cut, a spawn ceiling was hit, a declared
                            bound lies beyond the simulator's (catalog §1 CG4)

Rules other modules register, extended here (`extend_rules`):
  SGC204 race (trace half)  vector clocks over the run's fork / await / gate
                            events; two accesses to one store in one episode, one
                            a write, unordered and lockset-disjoint; two tasks
                            holding one `owns` at once (concurrent ownership); a
                            `(User)×N` entry's writes race with their own copies (RFC 0003 Q10)
  SGC205 ordering-unstated (the primary detector) — two unordered deliveries to
                            one machine whose order changes its outcome (a static
                            diamond check), or a drop while the owner is in `+`
  SGC151, SGC152, SGC201, SGC202 — a witness (the run that shows the static
                            finding) on each of their findings

Happens-before. Each task's vector clock starts as its parent's at the fork;
an awaiting task joins the clocks its members ended with; a join's target (run
by the last arrival) joins every arrival's clock. Deliveries from one sender to
one machine arrive in send order (per-sender FIFO): a `~>` send into an event
counts as its sender's. Runs are deterministic and the analysis does not depend
on the scheduler, so no interleaving search is needed.

Trace caps (catalog §1.2): a rule's trace findings cap at warn until every
simulator fix it relies on is in FIXED; a fix joins FIXED only with a passing
regression probe (tests/fixtures/checks/trace-fix-*.sigil, asserted by
tests/test_check_trace.py). A finding whose witness needs k >= 2 deviations
caps at warn whatever its tier (check.grade).

Folding scopes: a trace hit carries its rule's static scopes, so one
acknowledgement and one fold cover both halves (catalog §1.7):
  SGC203, SGC205  ("machine", owner id)        SGC146 case 2 folds them there
  SGC204          ("store", store id) and      SGC131 folds it at the store;
                  ("node_store", "node|store")  it folds SGC133 at node_store

Standard library only; deterministic (written, event and scenario order).
"""

from __future__ import annotations

import weakref
from dataclasses import replace
from functools import cached_property
from typing import Callable, NamedTuple, Optional

# The modifiers that bound a wait on a join (catalog §3 SGC206 "Declare").
BOUNDING_MODS = ("timeout", "fallback")

# Runs one exploration may make, the happy run aside (sim.combinations' budget).
BUDGET = 256

# The simulator fixes (catalog §6 "Prerequisite tool fixes"; the keys are its ids) whose
# regression probes pass, and the fixes each rule's trace evidence relies on. A rule's
# trace findings stay capped at warn while it needs a fix not listed in FIXED.
FIXED = frozenset({"B1", "B2", "B3", "B4", "B13", "NG6", "Q3"})
NEEDS = {
    "SGC203": ("B1", "B2", "B3", "B4", "NG6"),
    "SGC204": ("B1", "B2", "B3", "B4"),
    "SGC205": ("B1", "B2", "B3", "B4", "NG6"),
    "SGC206": ("B1", "B2", "B3", "B4", "Q3"),
}

WRITES = ("write", "rw")


def warn_only(rule_id: str, fixed: frozenset = FIXED) -> bool:
    """Whether a rule's trace findings still cap at warn."""
    return not set(NEEDS.get(rule_id, ())) <= fixed


class Run(NamedTuple):
    scenario: object         # sim.Scenario
    end: dict                # Trace.end
    outcome: str

    @property
    def k(self) -> int:
        return len(self.scenario.choices)

    @property
    def events(self) -> list:
        return self.end.get("events", [])


class Explored(NamedTuple):
    """One bounded exploration: the runs kept (happy first, fewest deviations
    first), what the budget left unrun, and the bounds it ran under."""
    runs: tuple
    left_out: int
    k: int
    budget: int
    limits: object           # sim.Limits


def explore(sim, sc, k: int, budget: int, limits) -> Explored:
    """The runs of up to k deviations at once (sim.combinations), at most
    `budget` of them, each under `limits` (a sim.Limits)."""
    ex = sim.combinations(sc, k, limits=limits, budget=budget)
    runs = tuple(Run(t.scenario, t.end, t.outcome) for t in ex.traces)
    return Explored(runs, ex.left_out, k, budget, limits)


# ---------------------------------------------------------------------------
# Happens-before: vector clocks over a run's events
# ---------------------------------------------------------------------------

def leq(a: dict, b: dict) -> bool:
    """Clock a happens before (or is) clock b."""
    return all(v <= b.get(t, 0) for t, v in a.items())


def concurrent(a: dict, b: dict) -> bool:
    return not leq(a, b) and not leq(b, a)


def _join(into: dict, other: dict) -> None:
    for t, v in other.items():
        if v > into.get(t, 0):
            into[t] = v


def vector_clocks(events: list) -> list:
    """The clock of every event, aligned with `events` (None for an event of the
    run itself). A `fork` event's clock is its parent's at the fork (the send
    point), a root's its own start; any other event's is its task's, after the
    synchronisation it makes (a `resume` joins its members' end clocks, a
    `gate-fire` every arrival's). Each event then ticks its task."""
    clock, ended, gates, awaiting, out = {}, {}, {}, {}, []
    for ev in events:
        task = ev["task"]
        if task is None:
            out.append(None)
            continue
        kind = ev["kind"]
        if kind == "fork":
            parent = ev.get("parent")
            start = dict(clock.get(parent, {})) if parent is not None else {}
            out.append(dict(start) if parent is not None else {task: 1})
            start[task] = 1
            clock[task] = start
            if parent is not None:
                mine = clock.setdefault(parent, {parent: 1})
                mine[parent] = mine.get(parent, 0) + 1
            continue
        mine = clock.setdefault(task, {task: 1})
        if kind == "resume":
            for m in awaiting.pop(task, ()):
                _join(mine, ended.get(m, {}))
        elif kind == "gate-fire":
            _join(mine, gates.get((ev["key"], ev["round"]), {}))
        out.append(dict(mine))
        if kind == "gate-arrive":
            _join(gates.setdefault((ev["key"], ev["round"]), {}), mine)
        elif kind == "end":
            ended[task] = dict(mine)
        elif kind == "await":
            awaiting[task] = list(ev["members"])
        mine[task] = mine.get(task, 0) + 1
    return out


def episode_entries(events: list) -> dict:
    """{episode: the node it entered}."""
    return {e["episode"]: e["node"] for e in events
            if e["kind"] == "fork" and e["why"] == "entry"}


# ---------------------------------------------------------------------------
# State machines: deliveries and the diamond check (SGC203, SGC205)
# ---------------------------------------------------------------------------

class Delivery(NamedTuple):
    """One event delivered to one machine in a run: where it was sent (clock,
    sender task), the state the machine was in when it arrived, and whether a
    transition took it. A drop judged at send time (no trigger task carried
    it) met the state the machine is heading to: its in-flight triggers are
    already counted in `state`."""
    owner: str
    label: str
    clock: dict
    sender: int
    sent: int                # the event index of its send (the sender's fork)
    index: int               # the event index of its transition / drop
    state: str
    accepted: bool
    at_send: bool            # a drop judged at send time, against the heading state


def sender_of(task: int, event: str, forks: dict, at: int) -> tuple:
    """(sender task, send index) of `event` delivered by `task` at event index
    `at`: a `~>` send straight into the event is its parent's, sent at the fork
    (per-sender FIFO); any other task sends its own, where it delivers."""
    index, fork = forks.get(task, (None, None))
    if fork is not None and fork["why"] == "async" and fork["wire"] \
            and fork["wire"][1] == event and fork["parent"] is not None:
        return fork["parent"], index
    return task, at


def deliveries(events: list, clocks: list) -> list:
    """Every delivery of the run, in the order the machines took them. A trigger
    task's delivery was sent at its fork; a drop before any trigger (no
    transition matched) was sent by the delivering task, where it happened."""
    forks = {e["task"]: (i, e) for i, e in enumerate(events) if e["kind"] == "fork"}
    sent, out = {}, []
    for i, ev in enumerate(events):
        kind = ev["kind"]
        if kind == "fork" and ev["why"] == "trigger":
            sent[ev["task"]] = (clocks[i], sender_of(ev["parent"], ev["node"], forks, i))
        elif kind in ("transition", "ignored"):
            task = ev["task"]
            at_send = task not in sent
            if at_send:
                clock, (sender, at) = clocks[i], sender_of(task, ev.get("event"), forks, i)
            else:
                clock, (sender, at) = sent.pop(task)
            accepted = kind == "transition"
            out.append(Delivery(ev["owner"], ev["label"], clock, sender, at, i,
                                ev["src"] if accepted else ev["state"], accepted,
                                at_send and not accepted))
    return out


def unordered(a: Delivery, b: Delivery) -> bool:
    return a.sender != b.sender and concurrent(a.clock, b.clock)


def step(m, state: str, label: str) -> tuple:
    """(next state, dropped) of machine view m taking `label` in `state`: a
    transition written from the state beats a `_` one (catalog §6 NG6); after `$` or with
    no transition the event is dropped."""
    if state in m.end:
        return state, True
    for t in m.specific(state) + [t for t in m.transitions if t.src in m.any]:
        if t.label == label:
            return t.dst, False
    return state, True


def outcome_of(m, state: str, labels: tuple) -> tuple:
    """(end state, the labels dropped) of taking `labels` in order from `state`."""
    dropped = []
    for label in labels:
        state, lost = step(m, state, label)
        if lost:
            dropped.append(label)
    return state, tuple(sorted(dropped))


def order_matters(m, state: str, a: str, b: str) -> bool:
    """The diamond check: from `state`, do `a, b` and `b, a` end differently or
    drop different events?"""
    return outcome_of(m, state, (a, b)) != outcome_of(m, state, (b, a))


class Reorder(NamedTuple):
    """Two unordered deliveries whose order changes the machine's outcome."""
    first: Delivery
    second: Delivery


def reorders(m, ds: list) -> list:
    """The unordered pairs of one machine's deliveries (in taken order) whose
    order matters, judged from the state the first one met."""
    return [Reorder(a, b) for i, a in enumerate(ds) for b in ds[i + 1:]
            if a.label != b.label and unordered(a, b) and order_matters(m, a.state, a.label,
                                                                        b.label)]


def in_flight(d: Delivery, ds: list) -> list:
    """The deliveries its sender sent before d that the machine took after it:
    per-sender FIFO puts them first."""
    return [p for p in ds if p.sender == d.sender and p.sent < d.sent and p.index > d.index]


def machine_drops(m, d: Delivery, ds: list) -> bool:
    """d, dropped in the run, is dropped by the machine itself: its sender's
    earlier sends land first (per-sender FIFO; the run judged d while they were
    still in flight), then d meets no transition (catalog §6 NG6) in the state reached. A
    drop the run judged at send time already met the heading state (the
    in-flight triggers taken), so nothing is replayed. A drop the run made
    against a transition the machine has is not one."""
    if d.accepted:
        return False
    state = d.state
    for p in ([] if d.at_send else in_flight(d, ds)):
        state, _ = step(m, state, p.label)
    return step(m, state, d.label)[1]


class Drops(NamedTuple):
    early: list              # dropped while the owner is in `+` (an ordering question)
    always: list             # dropped in every order (no reordering explains it)


def drops(m, ds: list, pairs: list) -> Drops:
    """The machine's own drops of its deliveries (machine_drops), split. A drop
    that a reordering explains is the reordering's."""
    explained = {id(d) for p in pairs for d in p}
    dropped = [d for d in ds if machine_drops(m, d, ds)]
    return Drops([d for d in dropped if d.state in m.start],
                 [d for d in dropped if d.state not in m.start and id(d) not in explained])


# ---------------------------------------------------------------------------
# Stores: accesses and races (SGC204 trace half)
# ---------------------------------------------------------------------------

class Access(NamedTuple):
    task: int
    episode: int
    store: str
    mode: str
    wire: tuple
    held: frozenset
    clock: dict


def accesses(events: list, clocks: list) -> list:
    """The run's store accesses with a known mode (a rule that needs a write
    never fires on `unknown`), in event order. A failed attempt counts (RFC 0003 Q13)."""
    return [Access(e["task"], e["episode"], e["store"], e["mode"], e["wire"],
                   frozenset(e["held"]), clocks[i])
            for i, e in enumerate(events)
            if e["kind"] == "access" and e["mode"] != "unknown"]


class Clash(NamedTuple):
    """Two accesses to one store, one a write, nothing ordering them. `writer`
    is a writing access; `shared` says both held the store's `owns`."""
    writer: Access
    other: Access
    shared: bool


def clash(a: Access, b: Access) -> Optional[Clash]:
    if a.store != b.store or not (a.mode in WRITES or b.mode in WRITES):
        return None
    writer, other = (a, b) if a.mode in WRITES else (b, a)
    return Clash(writer, other, a.store in a.held and a.store in b.held)


def clashes(acc: list, self_concurrent: frozenset) -> list:
    """The clashes of one run: pairs of accesses in one episode by two tasks with
    concurrent clocks, plus each write of an episode whose entry runs
    concurrently with itself (`(User)×N`, RFC 0003 Q10) against its own copy."""
    out = []
    for i, a in enumerate(acc):
        if a.mode in WRITES and a.episode in self_concurrent:
            out.append(clash(a, a))
        for b in acc[i + 1:]:
            if a.task != b.task and a.episode == b.episode and concurrent(a.clock, b.clock):
                found = clash(a, b)
                if found is not None:
                    out.append(found)
    return out


# ---------------------------------------------------------------------------
# What one document's runs show, computed once
# ---------------------------------------------------------------------------

class TraceFacts:
    """The exploration of one document and the per-run facts the rules share.
    `state` is check_state.Facts (store, machine and arrival facts); `budget`
    and `limits` bound the exploration (the document's: `doc.budget`,
    `doc.limits`, which --json reports)."""

    def __init__(self, doc, state, budget: int, limits):
        self.doc = doc
        self.state = state
        self.budget = budget
        self.limits = limits

    @cached_property
    def explored(self) -> Explored:
        return explore(self.doc.sim, self.doc.sc, self.doc.k, self.budget, self.limits)

    @property
    def runs(self) -> tuple:
        return self.explored.runs

    @cached_property
    def clocks(self) -> list:
        return [vector_clocks(r.events) for r in self.runs]

    @cached_property
    def deliveries(self) -> list:
        return [deliveries(r.events, c) for r, c in zip(self.runs, self.clocks)]

    @cached_property
    def accesses(self) -> list:
        return [accesses(r.events, c) for r, c in zip(self.runs, self.clocks)]

    @cached_property
    def wires(self) -> dict:
        return {w.ident: w for w in self.doc.sc.wires}

    @cached_property
    def machines(self) -> dict:
        return {m.owner: m for m in self.state.machines}

    def self_concurrent(self, run: Run) -> frozenset:
        """The episodes of a run whose entry has concurrent callers (RFC 0003 Q10)."""
        return frozenset(ep for ep, node in episode_entries(run.events).items()
                         if node is not None and self.state.many_callers(node))

    def principal(self, w) -> str:
        return w.src if self.state.kind(w.dst) == "store" else w.dst


# The TraceFacts of each live document; trace_facts is its only reader and writer.
_FACTS: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def trace_facts(ck, doc) -> TraceFacts:
    """The TraceFacts of a document, built once, under the document's own bounds."""
    found = _FACTS.get(doc)
    if found is None:
        found = _FACTS[doc] = TraceFacts(doc, state_module(ck).facts_of(doc),
                                         budget=doc.budget, limits=doc.limits)
    return found


def state_module(ck):
    """check_state.py, the module that holds the shared static facts."""
    return ck._rule_module(ck._HERE / "check_state.py")


def in_run(run: Run) -> str:
    return f"in the `{run.scenario.name}` run"


def trace_hit(ck, run: Run, line: int, statement: str, ask: str, **kw):
    return ck.Hit(line, statement, ask, k=run.k, witness=run.scenario.name, trace=True, **kw)


# ---------------------------------------------------------------------------
# SGC203 event-ignored and SGC205 ordering-unstated (trace half)
# ---------------------------------------------------------------------------

def label_list(labels) -> str:
    return " or ".join(f"`{x}`" for x in dict.fromkeys(labels))


def enablers(m) -> str:
    """The events that take a machine out of `+`."""
    found = [t.label for t in m.transitions if t.src in m.start]
    return label_list(found) if found else "the event that starts it"


def machine_line(m) -> int:
    return min((t.line for t in m.transitions), default=0)


def per_machine(tf: TraceFacts):
    """(machine view, run, its deliveries in taken order, their reorderings) for
    every machine every run delivers to, in run then machine order."""
    for run, ds in zip(tf.runs, tf.deliveries):
        for owner in dict.fromkeys(d.owner for d in ds):
            m = tf.machines.get(owner)
            if m is None:
                continue
            mine = [d for d in ds if d.owner == owner]
            yield m, run, mine, reorders(m, mine)


def ignored_hit(ck, st, m, run: Run, d: Delivery):
    o, s = m.owner_glyph, m.name(d.state)
    return trace_hit(
        ck, run, m.state_line(d.state) or machine_line(m),
        f"`{d.label}` reaches `{o}` while it is `{s}` and is dropped {in_run(run)}",
        f"`{d.label}` reaches `{o}` while it is `{s}`. Should it be ignored, or is a "
        "transition missing?",
        anchor=("machine", m.owner), scopes=st.machine_scopes(m, d.state),
        fix=f"a transition `{s} -{d.label}-> …`, a `_ -{d.label}-> …` wildcard, or the "
            f"self-loop `{s} -{d.label}-> {s}` to ignore it on purpose")


def events_ignored(ck, doc):
    """SGC203: a drop no reordering explains, outside `+`; one per (machine,
    event, state), with its first witness."""
    tf = trace_facts(ck, doc)
    st, seen = state_module(ck), set()
    for m, run, ds, pairs in per_machine(tf):
        for d in drops(m, ds, pairs).always:
            key = (m.owner, d.label, d.state)
            if key not in seen:
                seen.add(key)
                yield ignored_hit(ck, st, m, run, d)


def ordering_declared(st, f, m) -> bool:
    """`@inv ordered(key)` on the machine's owner, after its `}`, or on an event
    that drives it (as SGC205's static half reads it)."""
    heads = set(f.heads(m.owner)) | {st.inv_head(a) for a in st.state_block_invs(f, m)}
    heads |= {h for tr in f.doc.graph.triggers if tr.owner == m.owner
              for h in f.heads(tr.event)}
    return "ordered" in heads


def reorder_text(m, run: Run, p: Reorder) -> tuple:
    """(statement, ask) for two deliveries whose order matters."""
    o, a, b = m.owner_glyph, p.first.label, p.second.label
    end_ab, lost_ab = outcome_of(m, p.first.state, (a, b))
    end_ba, lost_ba = outcome_of(m, p.first.state, (b, a))
    if lost_ab != lost_ba:
        first, then = (a, b) if len(lost_ab) < len(lost_ba) else (b, a)
        lost = label_list(lost_ab + lost_ba)
        return (f"`{o}` drops {lost} unless `{first}` arrives before `{then}`, and nothing "
                f"orders them {in_run(run)}",
                f"`{o}` only works if `{first}` comes before `{then}`. Is that order "
                "guaranteed?")
    x, y = m.name(end_ab), m.name(end_ba)
    return (f"`{o}` ends in `{x}` or `{y}` depending on whether `{a}` or `{b}` "
            f"arrives first, and nothing orders them {in_run(run)}",
            f"`{o}` ends in `{x}` if `{a}` comes before `{b}`, and in `{y}` otherwise. "
            "Is that order guaranteed?")


def early_text(m, run: Run, d: Delivery) -> tuple:
    """(statement, ask) for a drop while the owner is in `+`."""
    o, first = m.owner_glyph, enablers(m)
    return (f"`{d.label}` reaches `{o}` before {first} starts it, and is dropped "
            f"{in_run(run)}",
            f"`{o}` only works if {first} comes before `{d.label}`. Is that order "
            "guaranteed?")


def ordering_hits(ck, doc):
    """SGC205 (trace): per machine with no stated order, its first reordering
    or drop in `+`, with its first witness."""
    tf = trace_facts(ck, doc)
    st, f, seen = state_module(ck), tf.state, set()
    for m, run, ds, pairs in per_machine(tf):
        if m.owner in seen or ordering_declared(st, f, m):
            continue
        early = drops(m, ds, pairs).early
        if not pairs and not early:
            continue
        seen.add(m.owner)
        statement, ask = (reorder_text(m, run, pairs[0]) if pairs
                          else early_text(m, run, early[0]))
        yield trace_hit(ck, run, machine_line(m), statement, ask,
                        anchor=("machine", m.owner), scopes=st.machine_scopes(m),
                        fix=f"`@inv ordered(key)` on `{m.owner_glyph}` or its events, or "
                            "transitions for both orders")


# ---------------------------------------------------------------------------
# SGC204 race (trace half)
# ---------------------------------------------------------------------------

def resolved(st, f, c: Clash) -> bool:
    """The store's kind or declarations resolve the clash: a `~|S|` / `*|S|`
    kind always; a single owner or writer only a race between tasks that do not
    both hold the store (two holders at once is concurrent ownership, never a
    pass)."""
    sid = c.writer.store
    if not f.plain(sid):
        return True
    if f.store_heads(sid) & set(st.STORE_RESOLUTIONS):
        return True
    return not c.shared and f.resolution(sid) is not None


def race_text(f, tf: TraceFacts, run: Run, c: Clash) -> tuple:
    """(statement, ask, fix) of one clash (fix "": the rule's)."""
    sid = c.writer.store
    s = f"`{f.g(sid)}`"
    me = tf.principal(tf.wires[c.writer.wire])
    them = tf.principal(tf.wires[c.other.wire])
    if c.shared:
        return (f"`{f.g(me)}` holds `@owns {f.g(sid)}` while another task holds it too "
                f"{in_run(run)}, and nothing orders them",
                f"Two tasks hold `{f.g(sid)}` at once {in_run(run)}. Which write wins?",
                f"`@inv serialised({f.g(sid)})` (one holder at a time), `@inv cas(version)` "
                "or `@inv atomic(…)`")
    if c.writer is c.other:
        who = f"`{f.g(me)}` writes {s} and its entry has concurrent callers"
    elif me == them:
        who = f"`{f.g(me)}` writes {s} from two tasks"
    else:
        who = f"`{f.g(me)}` writes {s} and `{f.g(them)}` also touches it"
    return (f"{who}, with nothing ordering them {in_run(run)}",
            f"{who} {in_run(run)}. Which write wins?", "")


def race_hits(ck, doc):
    """SGC204 (trace): one hit per writing wire, with its first witness."""
    tf = trace_facts(ck, doc)
    st, f, seen = state_module(ck), tf.state, set()
    for run, acc in zip(tf.runs, tf.accesses):
        for c in clashes(acc, tf.self_concurrent(run)):
            w = tf.wires.get(c.writer.wire)
            if w is None or c.other.wire not in tf.wires or w.ident in seen \
                    or resolved(st, f, c):
                continue
            seen.add(w.ident)
            statement, ask, fix = race_text(f, tf, run, c)
            guessed = any(f.heuristic(tf.wires[a.wire]) for a in (c.writer, c.other)
                          if a.mode in WRITES)
            yield trace_hit(ck, run, w.line, statement, ask, anchor=("wire", w.ident),
                            scopes=st.store_scopes(c.writer.store, tf.principal(w)), fix=fix,
                            guess="the write is read off its op verb" if guessed else "")


# ---------------------------------------------------------------------------
# SGC206 stalled-join
# ---------------------------------------------------------------------------

class OpenJoin(NamedTuple):
    """One join a run leaves open, located in the document. `key` names the join
    across runs; `waiter` is the node left waiting (the target for a deposit)."""
    key: tuple
    line: int
    waiter: str
    missing: tuple           # node ids that never arrived (empty: a waiting task)
    bounded: bool            # every wait it holds carries a bounding modifier


def may_hold_joins(graphs) -> bool:
    """Whether any unit has a `&` source join or an awaited fan-out (`*>`): a
    document without one cannot stall."""
    for g, _owner, _level in graphs:
        if any(j.kind == "&" for j in getattr(g, "joins", None) or []):
            return True
        if any(e.kind == "*>" for e in g.edges):
            return True
    return False


def bounds_wait(policy: list) -> bool:
    """A call policy (scene.call_policy pairs) holds @timeout or @fallback."""
    return any(name in BOUNDING_MODS for name, _arg in policy)


def deposit_join(deposit: dict, units: list, wires: list, call_policy) -> OpenJoin:
    """The open join a run's deposit record (Trace.end["deposits"]) names. Bounded
    when every missing member's wire into the target bounds its wait."""
    ui, j = deposit["join"]
    graph = units[ui].graph
    missing = tuple(deposit["missing"])
    edges = [e for e in graph.edges
             if e.src_join == j and e.dst == deposit["target"] and e.src in missing]
    waits = [w for w in wires if any(w.edge is e for e in edges)]
    bounded = bool(waits) and all(bounds_wait(call_policy(w)) for w in waits)
    return OpenJoin(("deposit", ui, j, deposit["target"]), graph.joins[j].line,
                    deposit["target"], missing, bounded)


def waiting_join(node: str, wires: list, call_policy) -> OpenJoin:
    """The awaited join a task left waiting at `node` holds: the node's awaited
    wires (`*>`, a `&` target), else its first outgoing one."""
    out = [w for w in wires if w.src == node and w.role == "flow" and w.line]
    awaited = [w for w in out if w.kind == "*>"
               or (w.edge is not None and w.edge.dst_join is not None)]
    held = awaited or out[:1]
    line = min((w.line for w in held), default=0)
    bounded = bool(awaited) and all(bounds_wait(call_policy(w)) for w in awaited)
    return OpenJoin(("waiting", node), line, node, (), bounded)


def open_joins(run: Run, units: list, wires: list, call_policy) -> list:
    """Every join the run ended with open: its deposits, then its waiting tasks.
    A cut run ended at a limit, not by itself: none (SGC090 reports it)."""
    if run.outcome == "cut":
        return []
    deposits = [deposit_join(d, units, wires, call_policy) for d in run.end.get("deposits", ())]
    waiting = [waiting_join(n, wires, call_policy) for n in run.end.get("stalled", ())]
    return deposits + waiting


def first_witnesses(runs: list, joins_of) -> list:
    """(OpenJoin, Run) for each distinct join, with the first run that shows it."""
    seen, out = set(), []
    for run in runs:
        for oj in joins_of(run):
            if oj.key not in seen:
                seen.add(oj.key)
                out.append((oj, run))
    return out


def stall_text(oj: OpenJoin, run: Run, label) -> tuple:
    """(statement, ask) for an open join seen in a run."""
    where = in_run(run)
    waiter = label(oj.waiter)
    if oj.missing:
        missing = " and ".join(f"`{label(m)}`" for m in oj.missing)
        one = len(oj.missing) == 1
        verb, pron = ("never arrives", "it") if one else ("never arrive", "they")
        return (f"`{waiter}` waits at a join for {missing}, which {verb} {where}",
                f"`{waiter}` waits for {missing} {where}. What if {pron} never arrive"
                f"{'s' if one else ''}?")
    return (f"`{waiter}` is still waiting at an awaited join when the run ends {where}",
            f"`{waiter}` is still waiting {where}. What if a member never finishes?")


def stall_hit(ck, oj: OpenJoin, run: Run, label):
    statement, ask = stall_text(oj, run, label)
    return trace_hit(ck, run, oj.line, statement, ask, anchor=("node", oj.waiter),
                     scopes=(("join", ":".join(map(str, oj.key))),))


def node_namer(sc, node_label):
    """node id → its drawn glyph (`[C]`), the id itself when the scene lacks it."""
    def label(nid: str) -> str:
        sn = sc.nodes.get(nid)
        return node_label(sn.node) if sn is not None else nid
    return label


def stalled_joins(ck, doc):
    """SGC206: the joins the explored runs leave open, unbounded, one per join."""
    if not may_hold_joins(doc.graphs):
        return
    runs = trace_facts(ck, doc).runs
    units, wires = doc.prog.units, doc.sc.wires
    joins_of = lambda run: open_joins(run, units, wires, doc.scene.call_policy)
    label = node_namer(doc.sc, doc.sim.kit.node_label)
    for oj, run in first_witnesses(runs, joins_of):
        if not oj.bounded:
            yield stall_hit(ck, oj, run, label)


# ---------------------------------------------------------------------------
# SGC175 unreached (static, over sim.reachable)
# ---------------------------------------------------------------------------

def parent_units(prog) -> dict:
    """{unit index: the index of the unit it expands from} (the document: none)."""
    by_graph = {id(u.graph): i for i, u in enumerate(prog.units)}
    out = {}
    for i, u in enumerate(prog.units):
        for sub in u.graph.expansions.values():
            if id(sub) in by_graph:
                out.setdefault(by_graph[id(sub)], i)
    return out


def within(ui: int, units: frozenset, parents: dict) -> bool:
    """Unit ui is one of `units` or nested in one."""
    seen = set()
    while ui is not None and ui not in seen:
        if ui in units:
            return True
        seen.add(ui)
        ui = parents.get(ui)
    return False


class Unreached(NamedTuple):
    what: str                # "alias" | "nodes" | "block"
    ui: int
    ref: object              # alias name | node ids (one group) | block index
    line: int


def groups(items: list, links) -> list:
    """`items` split into the groups `links` ((a, b) pairs) connect, each in
    item order, groups in the order of their first item."""
    root = {x: x for x in items}

    def find(x):
        while root[x] != x:
            root[x] = root[root[x]]
            x = root[x]
        return x
    for a, b in links:
        if a in root and b in root:
            root[find(b)] = find(a)
    out = {}
    for x in items:
        out.setdefault(find(x), []).append(x)
    return list(out.values())


def unreached(prog, reach, line_of, links) -> list:
    """What no default entry reaches: aliases never invoked; the nodes with work
    outside them, one group per set the flows (`links`) connect (a rootless
    cycle is one); blocks outside them. State units are left to the machine
    rules. In written order. A document with no default entry has nothing to
    measure reach from (every part would be listed): none, and its cycles are
    SGC152's ("nothing outside enters it")."""
    if not prog.entries.get(0):
        return []
    _wires, nodes, regions = reach
    reached, parents = set(nodes), parent_units(prog)
    out = [Unreached("alias", ui, name, line_of(nid))
           for name, (ui, nid) in prog.aliases.items() if (ui, nid) not in reached]
    unused = {nid for ui, nid in prog.aliases.values() if (ui, nid) not in reached}
    dead = frozenset(ui for ui, u in enumerate(prog.units) if u.owner in unused)
    idle = [(ui, nid) for (ui, nid), body in prog.bodies.items()
            if body and (ui, nid) not in reached and prog.units[ui].graph.role != "state"
            and not within(ui, dead, parents) and nid not in prog.decisions]
    ids = list(dict.fromkeys(nid for _ui, nid in idle))
    for group in groups(sorted(ids, key=lambda n: (line_of(n), ids.index(n))), links):
        ui = next(u for u, n in idle if n == group[0])
        out.append(Unreached("nodes", ui, tuple(group), line_of(group[0])))
    for ui, u in enumerate(prog.units):
        if u.graph.role == "state" or within(ui, dead, parents):
            continue
        for bi, b in enumerate(getattr(u.graph, "blocks", None) or []):
            if (ui, bi) not in regions and b.lines:
                out.append(Unreached("block", ui, bi, b.lines[0]))
    return sorted(out, key=lambda x: (x.line, x.what))


def unreached_hit(ck, prog, f, listing, x: Unreached):
    if x.what == "alias":
        return ck.Hit(x.line, f"nothing invokes `{x.ref}`",
                      f"Nothing invokes `{x.ref}`. Is it a library fragment, or should "
                      "something call it?",
                      anchor=("node", prog.aliases[x.ref][1]),
                      fix=f"name its caller (`… : {x.ref}()`), or acknowledge it as a "
                          "library fragment")
    if x.what == "nodes":
        names = listing(f"`{f.g(n)}`" for n in x.ref)
        one = len(x.ref) == 1
        verb, pron = ("its", "it") if one else ("their", "them")
        return ck.Hit(x.line, f"no entry reaches {names}, so {verb} work never runs",
                      f"No entry reaches {names}. What starts {pron}?",
                      anchor=("node", x.ref[0]),
                      fix="a flow from an entry, or acknowledge it as a fragment")
    b = prog.units[x.ui].graph.blocks[x.ref]
    return ck.Hit(x.line, f"no entry reaches this `{b.kind}` block",
                  f"No entry reaches this `{b.kind}` block. What runs it?",
                  anchor=("block", str(x.line)),
                  fix="a flow from an entry into its members, or acknowledge it")


def match_unreached(ck, doc):
    """SGC175: the complement of sim.reachable (field branches run: catalog §6 B4)."""
    st = state_module(ck)
    f = st.facts_of(doc)
    links = [(w.src, w.dst) for w in doc.sc.wires if w.role == "flow"]
    for x in unreached(doc.prog, doc.sim.reachable(doc.prog), f.line_of, links):
        yield unreached_hit(ck, doc.prog, f, st.listing, x)


# ---------------------------------------------------------------------------
# SGC090 exploration-incomplete: the run causes
# ---------------------------------------------------------------------------

def limits_text(limits, names: tuple) -> str:
    return "limits: " + ", ".join(f"{n}={getattr(limits, n)}" for n in names)


def first_line(doc) -> int:
    return doc.layout.first or 1


def budget_cause(ck):
    def match(doc):
        ex = trace_facts(ck, doc).explored
        if ex.left_out:
            yield ck.Hit(first_line(doc),
                         f"the exploration budget left {ex.left_out} combination"
                         f"{'s' if ex.left_out != 1 else ''} of up to {ex.k} deviations "
                         f"unrun (budget={ex.budget} runs, k={ex.k})",
                         f"The exploration budget left {ex.left_out} combinations unrun. "
                         "Is what it ran enough evidence?",
                         anchor=("document", "budget"),
                         fix="run with a larger budget, or a smaller --k")
    return match


def episode_entry_at(events: list, index: int) -> Optional[str]:
    """The entry of the episode running at event `index`."""
    node = None
    for e in events[:index + 1]:
        if e["kind"] == "fork" and e["why"] == "entry":
            node = e["node"]
    return node


def cut_cause(ck):
    """A run the simulator cut at a limit: one finding per limit."""
    run_limits = ("activations", "stack", "frames")

    def match(doc):
        tf, seen = trace_facts(ck, doc), set()
        for run in tf.runs:
            if run.outcome != "cut":
                continue
            for i, e in enumerate(run.events):
                if e["kind"] != "limit" or e["name"] not in run_limits or e["name"] in seen:
                    continue
                seen.add(e["name"])
                entry = episode_entry_at(run.events, i)
                line = (tf.state.line_of(entry) if entry else 0) or first_line(doc)
                limits = limits_text(tf.explored.limits, run_limits)
                yield trace_hit(ck, run, line,
                                f"the simulator cut a run at its {e['name']} limit "
                                f"{in_run(run)} ({limits})",
                                f"The simulator stopped {in_run(run)} at its {e['name']} "
                                "limit. Is what it ran enough evidence?",
                                anchor=("limit", e["name"]),
                                fix="run with larger limits")
    return match


def spawn_cause(ck):
    """A spawn ceiling the runs hit (SGC167's witness): one finding per node."""
    def match(doc):
        tf, seen = trace_facts(ck, doc), set()
        for run in tf.runs:
            for e in run.events:
                if e["kind"] == "limit" and e["name"] == "spawns" and e["node"] not in seen:
                    seen.add(e["node"])
                    g = tf.state.g(e["node"])
                    limits = limits_text(tf.explored.limits, ("spawn", "spawns"))
                    yield trace_hit(ck, run, tf.state.line_of(e["node"]) or first_line(doc),
                                    f"the simulator stopped spawning `{g}` at its ceiling "
                                    f"{in_run(run)} ({limits})",
                                    f"The simulator stopped spawning `{g}` at its ceiling. "
                                    "Are that many instances enough evidence?",
                                    anchor=("node", e["node"]),
                                    fix="run with a larger spawns limit")
    return match


# Declared bounds (`@inv depth <= N`, `@inv hops <= N`) and the simulator limit
# that stands in for each (catalog §1 CG4: declarations never change a run).
BOUND_LIMITS = (("depth", "depth", "depth"), ("hops", "visits", "visits"))


def declared_bound(f, nid: str, head: str) -> Optional[int]:
    """N of a node's `@inv <head> <= N`, when it is a number."""
    for name, arg in f.mods.get(nid, ()):
        text = (arg or "").replace(" ", "")
        if name == "inv" and text.startswith(head + "<="):
            n = text[len(head) + 2:]
            return int(n) if n.isdigit() else None
    return None


def bound_cause(ck):
    """A declared bound beyond the limit the simulator stopped the node at:
    "bounded by design (N) vs simulator (depth 3)" (catalog §1 CG4)."""
    def match(doc):
        tf, seen = trace_facts(ck, doc), set()
        for run in tf.runs:
            for e in run.events:
                if e["kind"] != "limit" or not e.get("node"):
                    continue
                for head, limit, event in BOUND_LIMITS:
                    n = declared_bound(tf.state, e["node"], head)
                    sim_n = getattr(tf.explored.limits, limit)
                    key = (e["node"], head)
                    if e["name"] != event or n is None or n <= sim_n or key in seen:
                        continue
                    seen.add(key)
                    g = tf.state.g(e["node"])
                    yield trace_hit(ck, run, tf.state.line_of(e["node"]) or first_line(doc),
                                    f"`{g}` is bounded by design ({head} <= {n}) vs the "
                                    f"simulator ({limit} {sim_n}), so the runs stop it "
                                    f"early ({limits_text(tf.explored.limits, (limit,))})",
                                    f"The simulator ran `{g}` to {limit} {sim_n} of its "
                                    f"declared {n}. Is that enough evidence?",
                                    anchor=("node", e["node"]),
                                    fix=f"run with a larger {limit} limit")
    return match


def exploration_causes(ck) -> list:
    return [budget_cause(ck), cut_cause(ck), spawn_cause(ck), bound_cause(ck)]


# ---------------------------------------------------------------------------
# Witnesses for the static rules (SGC151, SGC152, SGC201, SGC202)
# ---------------------------------------------------------------------------

def witnessed(hits: list, runs, shows_hit: Callable) -> list:
    """The hits with the first run that shows each (`shows_hit(hit)` builds the
    run predicate; None: no run can). A static finding stays static: it gets a
    witness name, never a deviation count or a trace cap."""
    out = []
    for h in hits:
        shows = None if h.witness else shows_hit(h)
        run = next((r for r in runs if shows(r)), None) if shows else None
        out.append(replace(h, witness=run.scenario.name) if run else h)
    return out


def limit_at_cycle(name: str) -> Callable:
    """SGC151 / SGC152: a run that hits `name` (depth / visits) at a node of the
    finding's cycle (its "scc" scope)."""
    def shows_hit(h):
        members = set(dict(h.scopes).get("scc", "").split("|")) - {""}
        if not members:
            return None
        return lambda run: any(e["kind"] == "limit" and e["name"] == name
                               and e.get("node") in members for e in run.events)
    return shows_hit


def origin_of(anchor: tuple) -> Optional[tuple]:
    """The failure origin a call or node anchor names (sim `fail` events)."""
    kind, ident = anchor
    return ("call", ident) if kind == "wire" else ("node", ident) if kind == "node" else None


def failure_escapes(h):
    """SGC201: a run where the anchored call or node fails and the failure stops
    a task's root unrouted (its episode, or an unawaited task)."""
    origin = origin_of(h.anchor)
    if origin is None:
        return None

    def shows(run):
        evs = run.events
        failed = [i for i, e in enumerate(evs) if e["kind"] == "fail" and e["origin"] == origin]
        return bool(failed) and any(e["kind"] == "stop" and e["how"] in ("entry", "unawaited")
                                    for e in evs[failed[0]:])
    return shows


def route_guards(prog) -> dict:
    """{route wire ident: its guard} over every activation's routes."""
    return {w.ident: g for routes in prog.routes.values() for w, g in routes}


def route_stays_quiet(guards: dict):
    """SGC202: a run where a call the route guards fails and the route does not
    fire (a `~>` send's failure, for one)."""
    def shows_hit(h):
        g = guards.get(h.anchor[1]) if h.anchor[0] == "wire" else None
        if not g or g[0] != "calls":
            return None
        origins = {("call", ident) for _c, ident in g[1]}
        ident = h.anchor[1]
        return lambda run: (any(e["kind"] == "fail" and e["origin"] in origins
                                for e in run.events)
                            and not any(e["kind"] == "route" and e["wire"] == ident
                                        for e in run.events))
    return shows_hit


# ---------------------------------------------------------------------------
# Extending the rules other modules register
# ---------------------------------------------------------------------------

class Extension(NamedTuple):
    """What this module adds to a rule another module registers: `extend(doc,
    hits)` returns that rule's hits with a trace half merged in or witnesses
    attached; `trace_warn_only` replaces the rule's flag."""
    rule_id: str
    extend: Callable
    trace_warn_only: bool


class ExtendedMatch:
    """A rule's match followed by an Extension (applying one twice is a no-op)."""

    def __init__(self, base: Callable, extension: Extension):
        self.base = base
        self.extension = extension

    def __call__(self, doc):
        return self.extension.extend(doc, list(self.base(doc)))


def merged(static: list, trace: list, key: Callable) -> list:
    """The static hits, plus each trace hit whose key no static hit has; a trace
    hit replaces a static guess at the same key when it is exact."""
    out = list(static)
    at = {}
    for i, h in enumerate(out):
        at.setdefault(key(h), i)
    for h in trace:
        k = key(h)
        if k not in at:
            at[k] = len(out)
            out.append(h)
        elif out[at[k]].guess and not out[at[k]].trace and not h.guess:
            out[at[k]] = h
    return out


def by_node_store(h) -> tuple:
    scopes = dict(h.scopes)
    return ("node_store", scopes["node_store"]) if "node_store" in scopes else h.anchor


def by_anchor(h) -> tuple:
    return h.anchor


def extensions(ck) -> list:
    """The trace halves and witnesses this module adds, by rule id."""
    runs = lambda doc: trace_facts(ck, doc).runs
    return [
        Extension("SGC151", lambda doc, hits: witnessed(hits, runs(doc),
                                                        limit_at_cycle("depth")),
                  warn_only("SGC151")),
        Extension("SGC152", lambda doc, hits: witnessed(hits, runs(doc),
                                                        limit_at_cycle("visits")),
                  warn_only("SGC152")),
        Extension("SGC201", lambda doc, hits: witnessed(hits, runs(doc), failure_escapes),
                  warn_only("SGC201")),
        Extension("SGC202", lambda doc, hits: witnessed(
            hits, runs(doc), route_stays_quiet(route_guards(doc.prog))), warn_only("SGC202")),
        Extension("SGC204", lambda doc, hits: merged(hits, list(race_hits(ck, doc)),
                                                     by_node_store), warn_only("SGC204")),
        Extension("SGC205", lambda doc, hits: merged(hits, list(ordering_hits(ck, doc)),
                                                     by_anchor), warn_only("SGC205")),
    ]


def extend_rules(ck, rules: list) -> list:
    """`rules` with this module's Extensions applied to the rules they name: the
    match runs the rule's own, then the extension; the trace cap follows FIXED.
    Rules already extended are left as they are."""
    exts = {e.rule_id: e for e in extensions(ck)}
    out = []
    for rule in rules:
        ext = exts.get(rule.id)
        if ext is None or isinstance(rule.match, ExtendedMatch):
            out.append(rule)
        else:
            out.append(replace(rule, match=ExtendedMatch(rule.match, ext),
                               trace_warn_only=ext.trace_warn_only))
    return out


# ---------------------------------------------------------------------------
# The registry entry point
# ---------------------------------------------------------------------------

def rules(ck) -> list:
    return [
        ck.Rule("SGC175", "unreached", "hint",
                ask="Nothing reaches this. Is it a library fragment, or should something "
                    "call it?",
                why="A construct no entry reaches is dead design, or a caller left out.",
                fix="name its caller, or acknowledge it as a fragment",
                match=lambda doc: match_unreached(ck, doc), family="17"),
        ck.Rule("SGC203", "event-ignored", "binding",
                ask="This event reaches its machine in a state with no transition for it. "
                    "Should it be ignored, or is a transition missing?",
                why="An event a machine cannot take is silently dropped (Harel; SCR "
                    "completeness).",
                fix="a transition for the event, a `_ -<T>-> …` wildcard, or the self-loop "
                    "`S -<T>-> S`",
                match=lambda doc: events_ignored(ck, doc), family="20",
                satisfiers=(("machine", "-<T>->"),),
                trace_warn_only=warn_only("SGC203")),
        ck.Rule("SGC206", "stalled-join", "binding",
                ask="The join waits for every member. What if one never arrives?",
                why="A join whose member neither arrives nor fails holds its target "
                    "(and any caller awaiting it) forever.",
                fix="write `@timeout(…)` or `@fallback(…)` on the join",
                match=lambda doc: stalled_joins(ck, doc), family="20",
                satisfiers=(("call", "@timeout"), ("call", "@fallback"),
                            ("block", "@timeout")),
                trace_warn_only=warn_only("SGC206")),
    ]
