"""
check_trace.py — the behavioural rules: what the simulator's runs show.

Not a command: check.py loads it (RULE_MODULES) and calls `rules(ck)` with
itself as `ck`, so this module never imports check.py. Each rule reads the
runs of the document's scenarios (sim.scenarios over the canonical scene, up
to `doc.k` deviations each) and reports a candidate as a trace Hit: its
witness is the scenario that shows it, `k` the deviations that scenario takes.

Rules (rfcs/0003-catalog.md §3):
  SGC206 stalled-join   a run ends with a join still open — a `&` deposit no
                        last arrival consumed, or a task still waiting at an
                        awaited join (`*>`, a `&` target). Declared by
                        `@timeout` or `@fallback` on the join's wires.

A run the simulator cut (a limit) shows no stall: it did not end, and SGC090
reports it. Standard library only; deterministic (written and scenario order).
"""

from __future__ import annotations

from typing import NamedTuple

# The modifiers that bound a wait on a join (catalog §3 SGC206 "Declare").
BOUNDING_MODS = ("timeout", "fallback")


class OpenJoin(NamedTuple):
    """One join a run leaves open, located in the document. `key` names the join
    across runs; `waiter` is the node left waiting (the target for a deposit)."""
    key: tuple
    line: int
    waiter: str
    missing: tuple           # node ids that never arrived (empty: a waiting task)
    bounded: bool            # every wait it holds carries a bounding modifier


class Run(NamedTuple):
    scenario: object         # sim.Scenario
    end: dict                # Trace.end
    outcome: str


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

def explored_runs(sim, sc, k: int) -> list:
    """The runs of every scenario with at most k deviations, fewest first, then
    in scenario order."""
    picked = [s for s in sim.scenarios(sc) if len(s.choices) <= k]
    picked.sort(key=lambda s: len(s.choices))       # stable: keeps scenario order
    out = []
    for s in picked:
        tr = sim.simulate(sc, s)
        out.append(Run(s, tr.end, tr.outcome))
    return out


def may_hold_joins(graphs) -> bool:
    """Whether any unit has a `&` source join or an awaited fan-out (`*>`): a
    document without one cannot stall, so it needs no run."""
    for g, _owner, _level in graphs:
        if any(j.kind == "&" for j in getattr(g, "joins", None) or []):
            return True
        if any(e.kind == "*>" for e in g.edges):
            return True
    return False


# ---------------------------------------------------------------------------
# SGC206 stalled-join
# ---------------------------------------------------------------------------

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
    wires (`*>`, a `&` target), else its first outgoing one (attribution to the
    exact join needs the simulator's await events)."""
    out = [w for w in wires if w.src == node and w.role == "flow" and w.line]
    awaited = [w for w in out if w.kind == "*>"
               or (w.edge is not None and w.edge.dst_join is not None)]
    held = awaited or out[:1]
    line = min((w.line for w in held), default=0)
    bounded = bool(awaited) and all(bounds_wait(call_policy(w)) for w in awaited)
    return OpenJoin(("waiting", node), line, node, (), bounded)


def open_joins(run: Run, units: list, wires: list, call_policy) -> list:
    """Every join the run ended with open: its deposits, then its waiting tasks.
    A cut run ended at a limit, not by itself: none."""
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
    where = f"in the `{run.scenario.name}` run"
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
    return ck.Hit(oj.line, statement, ask, anchor=("node", oj.waiter),
                  k=len(run.scenario.choices), witness=run.scenario.name, trace=True,
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
    runs = explored_runs(doc.sim, doc.sc, doc.k)
    units, wires = doc.prog.units, doc.sc.wires
    joins_of = lambda run: open_joins(run, units, wires, doc.scene.call_policy)
    label = node_namer(doc.sc, doc.sim.kit.node_label)
    for oj, run in first_witnesses(runs, joins_of):
        if not oj.bounded:
            yield stall_hit(ck, oj, run, label)


# ---------------------------------------------------------------------------
# The registry entry point
# ---------------------------------------------------------------------------

def rules(ck) -> list:
    return [
        ck.Rule("SGC206", "stalled-join", "binding",
                ask="The join waits for every member. What if one never arrives?",
                why="A join whose member neither arrives nor fails holds its target "
                    "(and any caller awaiting it) forever.",
                fix="write `@timeout(…)` or `@fallback(…)` on the join",
                match=lambda doc: stalled_joins(ck, doc), family="2",
                satisfiers=(("call", "@timeout"), ("call", "@fallback"),
                            ("block", "@timeout"))),
    ]
