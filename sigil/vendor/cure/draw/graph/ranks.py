"""[Ranks]: DAGs, trees and maps: laid out as data, drawn onto a canvas. Longest path /
network simplex; cycles broken.

Kind: service (the input data classes, the layering data class, and pure functions).

What it does: holds the input every part of Graph takes, a {Dag} (nodes with ids and
sizes in cells, edges as id pairs), breaks its cycles by reversing a stated set of
edges, gives each node a RANK (its layer: 0 at the top) and splits every edge that
spans more than one layer into VIRTUAL vertices, one per layer it crosses. The result,
{Layers}, is what [Order] takes (`order({Layers}) => {Order}`); [Lanes] uses `topo`.

Network simplex is not used: the ranks are the longest path from the sources (the
default: a schedule's waves, every node as early as its dependencies allow), or with
`compact=True` the longest path pulled down toward the successors (fewer virtual
vertices). Both are exact rules, below, with no tie to break.

The input, {Dag} (frozen dataclass, checked on construction):
- `Node(id: str, width: int = 1, height: int = 1)`: a node and its size in cells (the
  box a caller will draw for it: a label's width, a box's height). `id` a non-empty
  `str`; `width`, `height` ints >= 1.
- `Dag(nodes=(), edges=())`: `nodes` an iterable whose items are `Node`s or `str`s (a
  `str` is `Node(that, 1, 1)`), stored as `tuple[Node, ...]` in the order given;
  `edges` an iterable of `(u, v)` pairs of ids, stored as `tuple[tuple[str, str], ...]`
  in the order given. An edge `(u, v)` means u is drawn above v (u before v: for a
  schedule, a dependency before what needs it). The input order of nodes and of edges
  is the tie-break everywhere in Graph: "node order" and "edge order" below.
  Checked: every id unique; every edge's ends are ids of `nodes`; no self-loop
  `(u, u)`; no edge given twice (`(u, v)` and `(v, u)` are two edges: a 2-cycle, which
  is broken like any cycle). An edge is a `tuple` or `list` of exactly two `str`s.
  Equality is field by field; a `Dag` is hashable.
  Lookups (each raises GraphError for an id not in the dag):
  - `Dag.ids -> tuple[str, ...]`: the ids in node order.
  - `Dag.index(id) -> int`: its position in node order.
  - `Dag.node(id) -> Node`.
  - `Dag.succ(id) -> tuple[str, ...]` / `Dag.pred(id) -> tuple[str, ...]`: the other
    ends of the edges out of / into `id`, in edge order (as given, before any
    reversal).

Breaking cycles (`acyclic(dag) -> tuple[tuple[str, str], ...]`, the edges reversed):
a depth-first search. For each node not yet entered, in node order, a search starts at
it; at a node, its out-edges are taken in edge order: an edge `(u, v)` whose `v` is on
the current search path (entered and not finished, `v` itself the ancestor) is a BACK
edge; an unentered `v` is entered (searched, then finished); a finished `v` is left
alone. The result is the back edges, in edge order. Reversing exactly those edges
leaves no cycle (the orientation below). A dag with no cycle gives `()`. The search
must not hit Python's recursion limit: a chain of 5000 nodes is fine.
The ORIENTED edges: `dag.edges` with each back edge `(u, v)` replaced by `(v, u)`, in
edge order (two may now be equal: the 2-cycle `a -> b`, `b -> a` gives `(a, b)`
twice; both are kept, as two edges).

Topological order (`topo(dag) -> tuple[str, ...]`): Kahn's algorithm over the oriented
edges, the ready node with the least node-order index taken first: every id once, each
oriented edge's tail before its head.

Ranks (`rank`, real nodes only), over the oriented edges:
- `compact=False` (longest path): a node with no oriented in-edge has rank 0; any
  other node's rank is 1 + the greatest rank of its oriented predecessors.
- `compact=True`: first the longest-path ranks; then, taking the nodes in REVERSE
  `topo` order, each node with at least one oriented successor gets rank = (the least
  rank of its successors) - 1; a node with none keeps its longest-path rank. (So a
  source that feeds only a deep node sits just above it.)
Either way every oriented edge `(a, b)` has `rank[a] < rank[b]`, ranks start at 0, and
no rank between 0 and the greatest is empty.

Virtual vertices: an edge whose oriented ends `(a, b)` have `rank[b] - rank[a] = k > 1`
gets `k - 1` virtual vertices, one at each rank `r` with `rank[a] < r < rank[b]`, each
the tuple `(u, v, r)` where `(u, v)` is the edge AS GIVEN in `dag.edges` (not
reversed), so a virtual id is stable from one dag to the next while that edge exists.
A VERTEX is a real node's id (a `str`) or a virtual vertex (a `tuple[str, str, int]`):
`isinstance(v, str)` tells them apart.

The data, {Layers} (frozen dataclass; its dicts are not to be mutated):
- `Layers(dag: Dag, rank: dict[str, int], layers: tuple[tuple[Vertex, ...], ...],
  chains: tuple[tuple[Vertex, ...], ...], reversed: tuple[tuple[str, str], ...])`:
  - `rank`: every real node's rank, keyed by id (inserted in node order).
  - `layers`: one tuple per rank, 0 first, `len(layers) == max(rank) + 1` (`()` for an
    empty dag). Layer r holds every vertex of rank r in the INITIAL ORDER: the real
    nodes in node order, then the virtual vertices in edge order (of the edge they
    belong to).
  - `chains`: one per edge, aligned with `dag.edges`: the vertices the oriented edge
    passes, top to bottom, `(a, (u, v, rank[a] + 1), ..., (u, v, rank[b] - 1), b)`;
    an edge between adjacent layers is `(a, b)`.
  - `reversed`: `acyclic(dag)`.
  Equal inputs give `==` results.
- `Layers.of(vertex) -> int`: a vertex's layer (`rank[id]`, or `r` of `(u, v, r)`);
  GraphError for a vertex not in `layers`.
- `Layers.oriented() -> tuple[tuple[str, str], ...]`: the oriented edges, in edge order.
- `Layers.segments() -> tuple[tuple[Vertex, Vertex], ...]`: every pair of consecutive
  vertices of every chain, chain by chain in edge order, top to bottom within one: the
  pieces between adjacent layers, each `(upper, lower)`. Equal pairs (a 2-cycle's) are
  kept as many times as they occur: [Order] and [Place] count each.

Laws (a property test can loop over random dags):
- every oriented edge goes down at least one layer: `rank[a] < rank[b]`;
- `compact=False`: every node of rank r > 0 has an oriented predecessor of rank r - 1;
- each chain's layers run `rank[a], rank[a] + 1, ..., rank[b]` (one vertex per layer);
- every vertex of `layers` appears exactly once, and every vertex of a chain is in
  `layers` at its own layer;
- a dag with no cycle has `reversed == ()` and `oriented() == dag.edges`.

Inputs: `Node`: a `str` and ints. `Dag`: iterables as above. `acyclic` / `topo`: a
  `Dag`. `ranks`: a `Dag`, `compact` a bool.
Outputs: `acyclic`: the reversed edges. `topo`: the ids. `ranks`: {Layers}.
Errors: `GraphError` (a `ValueError`): a duplicate id, an edge to an unknown id, a
  self-loop, a duplicate edge, an empty id, a width or height < 1, a lookup of an
  unknown id or vertex. `TypeError`: an id that is not a `str`, a size that is not an
  `int` (a `bool` included), a node item neither `Node` nor `str`, an edge that is not
  a pair, `ranks` / `acyclic` / `topo` given something other than a `Dag`.
Effects: none.

Usage:
    from cure.draw.graph.ranks import Dag, Node, acyclic, ranks, topo
    d = Dag([Node("a", 3), Node("b", 3), Node("c", 3), Node("d", 3), Node("e", 3)],
            [("a", "c"), ("b", "c"), ("a", "d"), ("c", "e"), ("d", "e"), ("a", "e")])
    L = ranks(d)
    L.rank                    # {"a": 0, "b": 0, "c": 1, "d": 1, "e": 2}
    L.layers                  # (("a", "b"), ("c", "d", ("a", "e", 1)), ("e",))
    L.chains[5]               # ("a", ("a", "e", 1), "e"): a -> e crosses layer 1
    L.segments()[5:]          # (("a", ("a", "e", 1)), (("a", "e", 1), "e"))
    topo(d)                   # ("a", "b", "c", "d", "e")
    cyc = Dag(["a", "b", "c"], [("a", "b"), ("b", "c"), ("c", "a")])
    acyclic(cyc)              # (("c", "a"),): reversed, it is a -> c
    ranks(cyc).rank           # {"a": 0, "b": 1, "c": 2}
    ranks(cyc).chains[2]      # ("a", ("c", "a", 1), "c")
    s = Dag(["x", "y", "z", "w"], [("x", "y"), ("y", "z"), ("w", "z")])
    ranks(s).rank["w"], ranks(s, compact=True).rank["w"]   # (0, 1)
"""

import heapq
from collections.abc import Iterable
from dataclasses import dataclass

Vertex = "str | tuple[str, str, int]"
"""A real node's id, or a virtual vertex `(u, v, r)`: edge `(u, v)` as given, at rank `r`."""


class GraphError(ValueError):
    """A dag, an order, a layout or a tree that Graph's contracts refuse; the message says which."""


def _size(value: object, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if value < 1:
        raise GraphError(f"{name} must be >= 1, got {value}")


@dataclass(frozen=True)
class Node:
    """A node of a {Dag}: its id and its size in cells."""

    id: str
    width: int = 1
    height: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.id, str):
            raise TypeError(f"a node id must be a str, got {type(self.id).__name__}")
        if not self.id:
            raise GraphError("a node id must not be empty")
        _size(self.width, "width")
        _size(self.height, "height")


@dataclass(frozen=True, init=False)
class Dag:
    """{Dag}: nodes (with sizes) and edges as id pairs, in the order given."""

    nodes: tuple
    edges: tuple

    def __init__(self, nodes: "Iterable[Node | str]" = (), edges: "Iterable[tuple[str, str]]" = ()) -> None:
        if isinstance(nodes, (str, Node)) or not isinstance(nodes, Iterable):
            raise TypeError("nodes must be an iterable of Node or str")
        if isinstance(edges, str) or not isinstance(edges, Iterable):
            raise TypeError("edges must be an iterable of (u, v) pairs")
        ns = []
        for item in nodes:
            if isinstance(item, Node):
                ns.append(item)
            elif isinstance(item, str):
                ns.append(Node(item))
            else:
                raise TypeError(f"a node must be a Node or a str, got {type(item).__name__}")
        index = {}
        for k, n in enumerate(ns):
            if n.id in index:
                raise GraphError(f"duplicate node id {n.id!r}")
            index[n.id] = k
        es, seen = [], set()
        for e in edges:
            if not isinstance(e, (tuple, list)) or len(e) != 2:
                raise TypeError(f"an edge must be a (u, v) pair, got {e!r}")
            u, v = e
            if not isinstance(u, str) or not isinstance(v, str):
                raise TypeError(f"an edge's ends must be str ids, got {e!r}")
            for end in (u, v):
                if end not in index:
                    raise GraphError(f"edge ({u!r}, {v!r}): unknown id {end!r}")
            if u == v:
                raise GraphError(f"self-loop ({u!r}, {v!r})")
            if (u, v) in seen:
                raise GraphError(f"duplicate edge ({u!r}, {v!r})")
            seen.add((u, v))
            es.append((u, v))
        object.__setattr__(self, "nodes", tuple(ns))
        object.__setattr__(self, "edges", tuple(es))

    def _index(self) -> dict:
        return {n.id: k for k, n in enumerate(self.nodes)}

    def _known(self, id: object) -> int:
        k = self._index().get(id) if isinstance(id, str) else None
        if k is None:
            raise GraphError(f"unknown id {id!r}")
        return k

    @property
    def ids(self) -> tuple:
        """The ids in node order."""
        return tuple(n.id for n in self.nodes)

    def index(self, id: str) -> int:
        """The id's position in node order."""
        return self._known(id)

    def node(self, id: str) -> Node:
        """The node with this id."""
        return self.nodes[self._known(id)]

    def succ(self, id: str) -> tuple:
        """Heads of the edges out of `id`, in edge order (as given)."""
        self._known(id)
        return tuple(v for u, v in self.edges if u == id)

    def pred(self, id: str) -> tuple:
        """Tails of the edges into `id`, in edge order (as given)."""
        self._known(id)
        return tuple(u for u, v in self.edges if v == id)


@dataclass(frozen=True)
class Layers:
    """{Layers}: ranks, the layers in initial order, each edge's chain, the reversed edges."""

    dag: Dag
    rank: dict
    layers: tuple
    chains: tuple
    reversed: tuple

    def of(self, vertex: object) -> int:
        """The layer of a vertex."""
        for r, layer in enumerate(self.layers):
            if vertex in layer:
                return r
        raise GraphError(f"vertex {vertex!r} is in no layer")

    def oriented(self) -> tuple:
        """The edges after cycle breaking, in edge order."""
        back = set(self.reversed)
        return tuple((v, u) if (u, v) in back else (u, v) for u, v in self.dag.edges)

    def segments(self) -> tuple:
        """Every (upper, lower) piece of every chain, chain by chain."""
        return tuple(pair for chain in self.chains for pair in zip(chain, chain[1:]))


def _need_dag(dag: object) -> None:
    if not isinstance(dag, Dag):
        raise TypeError(f"expected a Dag, got {type(dag).__name__}")


def _out_edges(dag: Dag) -> dict:
    """Each id's out-edges as (edge index, head), in edge order."""
    out = {id: [] for id in dag.ids}
    for k, (u, v) in enumerate(dag.edges):
        out[u].append((k, v))
    return out


def acyclic(dag: Dag) -> tuple:
    """The back edges of the stated depth-first search: reversed, they leave no cycle."""
    _need_dag(dag)
    out = _out_edges(dag)
    state = {}  # id -> "open" (on the path) or "done"
    back = []
    for start in dag.ids:
        if start in state:
            continue
        state[start] = "open"
        stack = [(start, 0)]
        while stack:
            node, i = stack[-1]
            edges = out[node]
            if i == len(edges):
                stack.pop()
                state[node] = "done"
                continue
            stack[-1] = (node, i + 1)
            k, head = edges[i]
            seen = state.get(head)
            if seen == "open":
                back.append(k)
            elif seen is None:
                state[head] = "open"
                stack.append((head, 0))
    return tuple(dag.edges[k] for k in sorted(back))


def _oriented(dag: Dag, back: tuple) -> tuple:
    reversed_ = set(back)
    return tuple((v, u) if (u, v) in reversed_ else (u, v) for u, v in dag.edges)


def _kahn(dag: Dag, oriented: tuple) -> tuple:
    index = dag._index()
    indegree = {id: 0 for id in dag.ids}
    heads = {id: [] for id in dag.ids}
    for a, b in oriented:
        indegree[b] += 1
        heads[a].append(b)
    ready = [index[id] for id in dag.ids if indegree[id] == 0]
    heapq.heapify(ready)
    ids = dag.ids
    result = []
    while ready:
        node = ids[heapq.heappop(ready)]
        result.append(node)
        for b in heads[node]:
            indegree[b] -= 1
            if indegree[b] == 0:
                heapq.heappush(ready, index[b])
    return tuple(result)


def topo(dag: Dag) -> tuple:
    """Kahn's order over the oriented edges, least node index first."""
    _need_dag(dag)
    return _kahn(dag, _oriented(dag, acyclic(dag)))


def _longest(order: tuple, oriented: tuple) -> dict:
    preds = {id: [] for id in order}
    for a, b in oriented:
        preds[b].append(a)
    rank = {}
    for id in order:
        rank[id] = 1 + max((rank[p] for p in preds[id]), default=-1)
    return rank


def _compacted(order: tuple, oriented: tuple, rank: dict) -> dict:
    succs = {id: [] for id in order}
    for a, b in oriented:
        succs[a].append(b)
    rank = dict(rank)
    for id in reversed(order):
        if succs[id]:
            rank[id] = min(rank[s] for s in succs[id]) - 1
    return rank


def ranks(dag: Dag, *, compact: bool = False) -> Layers:
    """The dag ranked (longest path, or compact), its long edges split into virtual vertices."""
    _need_dag(dag)
    back = acyclic(dag)
    oriented = _oriented(dag, back)
    order = _kahn(dag, oriented)
    by_order = _longest(order, oriented)
    if compact:
        by_order = _compacted(order, oriented, by_order)
    rank = {id: by_order[id] for id in dag.ids}
    chains = tuple(
        (a,) + tuple((u, v, r) for r in range(rank[a] + 1, rank[b])) + (b,)
        for (u, v), (a, b) in zip(dag.edges, oriented)
    )
    height = max(rank.values()) + 1 if rank else 0
    layers = [[] for _ in range(height)]
    for id in dag.ids:
        layers[rank[id]].append(id)
    for chain in chains:
        for vertex in chain[1:-1]:
            layers[vertex[2]].append(vertex)
    return Layers(dag, rank, tuple(tuple(layer) for layer in layers), chains, back)
