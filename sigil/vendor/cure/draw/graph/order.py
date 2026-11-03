"""[Order]: crossing reduction (barycentre sweeps).

Kind: service (a data class and pure functions).

What it does: `order(layers)` ({Layers} => {Order}, on [Ranks]) chooses the left-to-right
order of the vertices in each layer so that few segments cross: layer-by-layer
barycentre sweeps from [Ranks]' initial order, the best order seen kept, then a
transpose step of adjacent swaps. Given the last layout's positions (`previous`), the
vertices that were there keep their relative order and only the new ones move: what
lets [Place] keep a changed dag still. [Place] takes the result
(`place({Order}) => {Coords}`).

Counting crossings (`crossings(layers, arrangement) -> int`): `arrangement` is one
sequence per layer, each a permutation of that layer of `layers.layers`. With `pos(v)`
the index of `v` in its layer's sequence, two segments `(a, b)` and `(c, d)` of
`layers.segments()` between the same two adjacent layers CROSS when
`(pos(a) - pos(c)) * (pos(b) - pos(d)) < 0`. The count is the number of unordered
pairs of segments (each occurrence a segment of its own) that cross. Segments sharing
an end never cross; two equal segments (a 2-cycle's) never cross each other.

The sweeps (`order(layers, *, sweeps=4, transpose=True, previous=None)`):

KEPT vertices: those that are keys of `previous` (a mapping vertex -> int, the across
coordinate each had in the last layout: x when laid down, y when laid right, as
[Place]'s `Coords.across()` gives). Keys that are not vertices of `layers` are ignored.
With `previous=None` no vertex is kept. Every other vertex is FREE.

1. The initial order: [Ranks]' `layers.layers`, and then in each layer the kept
   vertices are re-sorted among the positions kept vertices hold, by
   `(previous[v], initial index)`; free vertices keep their positions.
2. A STEP places one layer r against a reference layer (r - 1 in a down sweep, r + 1 in
   an up sweep), both in the current order. A vertex's barycentre `b(v)` is the mean
   of `pos(n)` over its neighbours n in the reference layer (the other ends of its
   segments to that layer, each occurrence counted), compared as an exact rational
   (`fractions.Fraction`); a vertex with no neighbour there has `b(v) = pos(v)`, its own
   current index. The free vertices are sorted by `(b(v), pos(v))`; the kept ones stay
   in their current relative order; then the two sequences merge: while both have
   vertices left, the next free `f` goes first when `b(k) > b(f)` for the next kept `k`,
   else `k` goes first; then whatever is left of either, in its order. (No kept
   vertex: the layer is simply sorted by `(b, pos)`.)
3. A SWEEP: a down sweep steps r = 1, 2, ..., H - 1 (each against r - 1, already
   placed), then an up sweep steps r = H - 2, ..., 0 (each against r + 1). `sweeps`
   such down-and-up pairs run.
4. The best order: of the candidates, the initial order and the order after each
   half-sweep (1 + 2 * sweeps of them, in that sequence), the one with the fewest
   crossings; on a tie, the earliest. An implementation may stop as soon as a
   candidate has 0 crossings or a whole sweep changes nothing: the result is the same.
5. Transpose (when `transpose` is true), on the best order: passes over the layers
   r = 0 .. H - 1, and in each layer over its adjacent pairs (i, i + 1), i = 0, 1, ...
   left to right. A pair of which at least one is free is swapped when that strictly
   lowers the crossings (the count over the whole arrangement); a pair of two kept
   vertices never is. The scan goes on from i + 1 either way. Passes repeat until one
   swaps nothing.

The data, {Order} (frozen dataclass):
- `Order(ranks: Layers, layers: tuple[tuple[Vertex, ...], ...])`: the layering it came
  from and each layer's vertices, left to right.
- `Order.position(vertex) -> int`: its index in its layer; GraphError when absent.
- `Order.crossings -> int` (a property): `crossings(self.ranks, self.layers)`.

Laws:
- each layer of the result is a permutation of the same layer of `layers.layers`;
- never worse: `order(L, ...).crossings <= crossings(L, the initial order of step 1)`,
  for every `sweeps`, with or without transpose;
- kept order: in each layer of the result, the kept vertices appear sorted by
  `(previous[v], initial index)`;
- the same `previous` the last result's positions came from, on the same dag,
  reproduces it: with `p` holding every vertex of `o = order(L, ...)` and `p[v]`
  increasing with `o.position(v)` in each layer, `order(L, ..., previous=p).layers ==
  o.layers` (every vertex is kept, so nothing moves);
- equal inputs give `==` results.

Inputs: `crossings`: a {Layers} and one sequence of vertices per layer. `order`: a
  {Layers}; `sweeps` an int >= 0; `transpose` a bool; `previous` `None` or a mapping
  vertex -> int.
Outputs: `crossings`: an int >= 0. `order`: {Order}.
Errors: `GraphError` when `sweeps < 0`, or an arrangement has the wrong number of
  layers or a layer that is not a permutation of `layers`'. `TypeError` when `layers`
  is not a {Layers}, `sweeps` not an int (a `bool` included), `previous` not a mapping,
  or a kept vertex's value not an int.
Effects: none.

Usage:
    from cure.draw.graph.ranks import Dag, Node, ranks
    from cure.draw.graph.order import crossings, order
    d = Dag([Node("a", 3), Node("b", 3), Node("c", 3), Node("d", 3), Node("e", 3)],
            [("a", "c"), ("b", "c"), ("a", "d"), ("c", "e"), ("d", "e"), ("a", "e")])
    L = ranks(d)
    crossings(L, L.layers)                     # 2: b -> c crosses a -> d and a -> e
    o = order(L)
    o.layers                                   # (("a", "b"), ("d", ("a", "e", 1), "c"), ("e",))
    o.crossings                                # 0
    order(L, sweeps=0, transpose=False).layers == L.layers   # True
    order(L, sweeps=0).layers[0]               # ("b", "a"): one transpose swap
    k = order(L, previous={"c": 0, "d": 9})    # c and d kept, c left of d
    k.layers                                   # (("b", "a"), ("c", "d", ("a", "e", 1)), ("e",))
    k.crossings                                # 0: the free a and b moved instead
"""

from bisect import bisect_right, insort
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction

from .ranks import GraphError, Layers


@dataclass(frozen=True)
class Order:
    """{Order}: each layer's vertices, left to right, and the layering they came from."""

    ranks: Layers
    layers: tuple

    def position(self, vertex: object) -> int:
        """The vertex's index in its layer."""
        for layer in self.layers:
            if vertex in layer:
                return layer.index(vertex)
        raise GraphError(f"vertex {vertex!r} is in no layer")

    @property
    def crossings(self) -> int:
        """The number of crossing segment pairs in this order."""
        return crossings(self.ranks, self.layers)


def _positions(arrangement: tuple) -> dict:
    return {v: i for layer in arrangement for i, v in enumerate(layer)}


def _between(layers: Layers) -> list:
    """The segments grouped by their upper layer: one list per pair of adjacent layers."""
    groups = [[] for _ in range(max(len(layers.layers) - 1, 0))]
    for upper, lower in layers.segments():
        groups[layers.rank[upper] if isinstance(upper, str) else upper[2]].append((upper, lower))
    return groups


def _count(groups: list, pos: dict) -> int:
    """The crossing pairs, group by group. Speed: an inversion count, O(s log s) per
    group: the ends sorted by upper position, each batch of equal uppers counted against
    the earlier batches' lowers (those strictly greater), then added; the same integer as
    every pair's `(a - c) * (b - d) < 0`."""
    total = 0
    for segs in groups:
        ends = sorted((pos[a], pos[b]) for a, b in segs)
        lowers: list = []
        n, i = len(ends), 0
        while i < n:
            j, upper = i, ends[i][0]
            while j < n and ends[j][0] == upper:
                total += len(lowers) - bisect_right(lowers, ends[j][1])
                j += 1
            for k in range(i, j):
                insort(lowers, ends[k][1])
            i = j
    return total


def _arranged(layers: Layers, arrangement: object) -> tuple:
    """The arrangement as tuples, checked against the layering."""
    try:
        rows = tuple(tuple(layer) for layer in arrangement)
    except TypeError:
        raise TypeError("an arrangement must be a sequence of sequences of vertices") from None
    if len(rows) != len(layers.layers):
        raise GraphError(f"an arrangement needs {len(layers.layers)} layers, got {len(rows)}")
    for r, (got, want) in enumerate(zip(rows, layers.layers)):
        if len(got) != len(want) or len(set(got)) != len(got) or set(got) != set(want):
            raise GraphError(f"layer {r} of the arrangement is not a permutation of the layering's")
    return rows


def crossings(layers: Layers, arrangement: "Sequence[Sequence[object]]") -> int:
    """How many pairs of segments cross when each layer is in the order given."""
    if not isinstance(layers, Layers):
        raise TypeError(f"expected Layers, got {type(layers).__name__}")
    rows = _arranged(layers, arrangement)
    return _count(_between(layers), _positions(rows))


def _kept(layers: Layers, previous: object) -> dict:
    if previous is None:
        return {}
    if not isinstance(previous, Mapping):
        raise TypeError(f"previous must be a mapping or None, got {type(previous).__name__}")
    vertices = {v for layer in layers.layers for v in layer}
    kept = {}
    for v, value in previous.items():
        if v not in vertices:
            continue
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"previous[{v!r}] must be an int, got {type(value).__name__}")
        kept[v] = value
    return kept


def _initial(layers: Layers, kept: dict) -> list:
    """Step 1: the kept vertices re-sorted among the positions they hold."""
    result = []
    for layer in layers.layers:
        slots = [i for i, v in enumerate(layer) if v in kept]
        ordered = sorted(slots, key=lambda i: (kept[layer[i]], i))
        seq = list(layer)
        for slot, i in zip(slots, ordered):
            seq[slot] = layer[i]
        result.append(seq)
    return result


def _neighbours(layers: Layers) -> tuple:
    """For each vertex, its segment ends one layer up and one layer down (each occurrence)."""
    up, down = {}, {}
    for upper, lower in layers.segments():
        down.setdefault(upper, []).append(lower)
        up.setdefault(lower, []).append(upper)
    return up, down


def _step(layer: list, ends: dict, ref_pos: dict, kept: dict) -> list:
    """Step 2: one layer placed by barycentres against a reference layer."""
    # Speed: the barycentres compared as floats `s / k` when every `k <= 1024`, every
    # `s <= 2**20` and the layer has at most 2**20 vertices: two distinct ones then differ
    # by at least 2**-20 and each float is within 2**-33 of its exact value (equal ones
    # round alike), so every comparison answers as `Fraction`'s and the order is the
    # same; above that bound, `Fraction` (the module's exact rational).
    sums = []
    small = len(layer) <= _FLOAT_LAYER
    for i, v in enumerate(layer):
        ns = ends.get(v)
        if not ns:
            sums.append(None)
            continue
        s, k = sum(ref_pos[n] for n in ns), len(ns)
        if k > _FLOAT_K or s > _FLOAT_SUM:
            small = False
        sums.append((s, k))
    if small:
        scored = [(i if sk is None else sk[0] / sk[1], i, v)
                  for (i, v), sk in zip(enumerate(layer), sums)]
    else:
        scored = [(Fraction(i) if sk is None else Fraction(*sk), i, v)
                  for (i, v), sk in zip(enumerate(layer), sums)]
    free = sorted((t for t in scored if t[2] not in kept), key=lambda t: (t[0], t[1]))
    held = [t for t in scored if t[2] in kept]
    merged, f, k = [], 0, 0
    while f < len(free) and k < len(held):
        if held[k][0] > free[f][0]:
            merged.append(free[f][2])
            f += 1
        else:
            merged.append(held[k][2])
            k += 1
    merged.extend(t[2] for t in free[f:])
    merged.extend(t[2] for t in held[k:])
    return merged


_FLOAT_K = 1024          # _step's float bound: neighbours per vertex,
_FLOAT_SUM = 2 ** 20     # their positions' sum,
_FLOAT_LAYER = 2 ** 20   # vertices in the layer


def _half(current: list, ends: dict, kept: dict, rows: range, delta: int) -> list:
    """A half-sweep: each layer in `rows` stepped against layer r + delta."""
    current = list(current)
    for r in rows:
        ref_pos = {v: i for i, v in enumerate(current[r + delta])}
        current[r] = _step(current[r], ends, ref_pos, kept)
    return current


def _best(current: list, groups: list, up: dict, down: dict, kept: dict, sweeps: int) -> list:
    """Steps 3-4: the candidate with the fewest crossings, the earliest on a tie."""
    height = len(current)

    def count(arr: list) -> int:
        return _count(groups, _positions(arr))

    best, best_count = current, count(current)
    for _ in range(sweeps):
        if best_count == 0:
            break
        start = current
        for rows, ends, delta in ((range(1, height), up, -1), (range(height - 2, -1, -1), down, 1)):
            current = _half(current, ends, kept, rows, delta)
            n = count(current)
            if n < best_count:
                best, best_count = current, n
        if current == start:
            break
    return best


def _pair_crossings(left: object, right: object, ends: dict, pos: dict) -> int:
    """Crossings between left's and right's segments to one adjacent layer, left before right."""
    total = 0
    for a in ends.get(left, ()):
        for b in ends.get(right, ()):
            if pos[a] > pos[b]:
                total += 1
    return total


def _swap_gain(u: object, w: object, up: dict, down: dict, pos: dict) -> int:
    """How many crossings swapping adjacent u (left) and w removes (negative: adds)."""
    before = _pair_crossings(u, w, up, pos) + _pair_crossings(u, w, down, pos)
    after = _pair_crossings(w, u, up, pos) + _pair_crossings(w, u, down, pos)
    return before - after


def _transpose(arr: list, up: dict, down: dict, kept: dict) -> list:
    """Step 5: adjacent swaps that strictly lower the crossings, until a pass swaps nothing."""
    arr = [list(layer) for layer in arr]
    pos = _positions(arr)
    changed = True
    while changed:
        changed = False
        for layer in arr:
            for i in range(len(layer) - 1):
                u, w = layer[i], layer[i + 1]
                if u in kept and w in kept:
                    continue
                if _swap_gain(u, w, up, down, pos) > 0:
                    layer[i], layer[i + 1] = w, u
                    pos[u], pos[w] = i + 1, i
                    changed = True
    return arr


def order(layers: Layers, *, sweeps: int = 4, transpose: bool = True,
          previous: "Mapping[object, int] | None" = None) -> Order:
    """The layers ordered by barycentre sweeps, the best kept, then transposed; kept vertices hold their order."""
    if not isinstance(layers, Layers):
        raise TypeError(f"expected Layers, got {type(layers).__name__}")
    if not isinstance(sweeps, int) or isinstance(sweeps, bool):
        raise TypeError(f"sweeps must be an int, got {type(sweeps).__name__}")
    if sweeps < 0:
        raise GraphError(f"sweeps must be >= 0, got {sweeps}")
    kept = _kept(layers, previous)
    groups = _between(layers)
    up, down = _neighbours(layers)
    arr = _best(_initial(layers, kept), groups, up, down, kept, sweeps)
    if transpose:
        arr = _transpose(arr, up, down, kept)
    return Order(layers, tuple(tuple(layer) for layer in arr))
