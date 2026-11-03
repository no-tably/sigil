"""[Place]: cell x / y per node, compact, aligned; given the last coords, a changed DAG
keeps its nodes still.

Kind: service (a data class and pure functions).

What it does: `place(order)` ({Order} => {Coords}, on [Order]) gives every vertex a rect
of cells: layers stacked along the LAYER AXIS (rows top to bottom when laid `"down"`,
columns left to right when laid `"right"`), each layer's vertices in their order along
the ACROSS AXIS, packed as tightly as the gaps allow and pulled toward the centres of
their neighbours (a priority-free 1-D placement, below, in place of Brandes-Koepf).
Given the last layout (`previous`), every vertex it placed is pinned to its old across
coordinate wherever the order leaves room, so a changed dag keeps its nodes still.
`layout(dag)` runs [Ranks], [Order] and `place` in one call, `previous` threaded
through both. [Fold] (`fold({Width}) => {Bands}`) and Graph's [Route] (G2,
`route({Edges}) => {Paths}`) take the result.

Sizes: a real node's size is its `Node`'s `width` x `height`; a virtual vertex is
1 x 1 (a lane cell). With `direction="down"` a vertex's ACROSS size is its width and its
ALONG size its height; with `"right"`, the other way round.

The layer axis: layer r's thickness `layer_size[r]` is the greatest along size of its
vertices; `layer_at[0] = 0` and `layer_at[r + 1] = layer_at[r] + layer_size[r] +
rank_gap`. Every vertex of layer r starts at `layer_at[r]` on that axis (top-aligned
when down, left-aligned when right).

The across axis, one layer at a time. For layer r with vertices `v_0 .. v_{m-1}` in
order, with across sizes `a_i`, the separation before `v_i` is `s_i = gap` when `v_{i-1}`
and `v_i` are both real, else `lane_gap`; the packed offsets are `o_0 = 0`, `o_i =
o_{i-1} + a_{i-1} + s_i`. PUTTING the layer with a target `t_i` (an int) and a weight
`w_i` for each vertex:
1. `z_i = t_i - o_i`.
2. Pool adjacent violators: blocks, each a run of consecutive vertices with a value.
   For i = 0 .. m-1: push the block `[i]` with value `z_i`; then, while there are two
   or more blocks and the last-but-one's value is GREATER than the last's, merge those
   two, the merged value being the weighted lower median of the members' `z`: the
   members sorted by `z`, the first `z` at which the running weight `c` has
   `2 * c >= ` the block's total weight.
3. `x_i = max(0, the value of v_i's block) + o_i`.
So the order is kept, every separation is met, and no coordinate is negative.

PINNED vertices: those whose vertex is a key of `previous` (a {Coords}: its `across()`;
or a mapping vertex -> int). A pinned vertex's target is always `previous[v]`, with
weight m (the layer's vertex count); every other vertex has weight 1 and the target
below.

The passes:
1. Start: every layer is PUT with targets `t_i = o_i` for the free vertices (packed to
   the left) and `previous[v]` for the pinned.
2. `passes` times: a down pass, layers r = 1 .. H - 1, each PUT against layer r - 1;
   then an up pass, layers r = H - 2 .. 0, each PUT against layer r + 1. Against a
   reference layer, a free vertex v's target is
   `sum(centre(n) for n in N) // len(N) - (a_v - 1) // 2` (Python's floor division)
   over N, the other ends of its segments to the reference layer (each occurrence
   counted; [Ranks]' `segments`), where `centre(n) = across(n) + (a_n - 1) // 2` in the
   reference layer's current coordinates; with no neighbour there, its own current
   across coordinate.
3. With no `previous` (`None`, or an empty mapping), every across coordinate is
   shifted by the same amount so that the least is 0. With one, nothing is shifted
   (the pins stay where they were).

The data, {Coords} (frozen dataclass; its dicts are not to be mutated):
- `Coords(order: Order, direction: str, rects: dict[Vertex, Rect],
  layer_at: tuple[int, ...], layer_size: tuple[int, ...], width: int, height: int)`:
  - `rects`: every vertex's Geometry `Rect` (x, y, w, h), keyed in layer order, each
    layer left to right (the order's order). Down: `Rect(across, layer_at[r], width,
    height)`; right: `Rect(layer_at[r], across, width, height)`.
  - `layer_at`, `layer_size`: as above, one per layer.
  - `width`, `height`: the greatest `x + w` and `y + h` over the rects (0, 0 for an
    empty dag).
- `Coords.across() -> dict[Vertex, int]`: each vertex's across coordinate (`x` when
  down, `y` when right): what `previous` reads.

Laws:
- no two rects overlap (`a.intersect(b).empty` for any two vertices);
- within a layer, the order's order is the across order: `v_{i}` starts at or after
  `v_{i-1}`'s end plus `s_i`;
- every vertex starts at its layer's `layer_at` on the layer axis, so every oriented
  edge goes down (or right) at least one layer;
- with no `previous`, the least across coordinate is 0 (when there is a vertex);
- still: `place(o, ..., previous=place(o, ...))` `==` `place(o, ...)` for the same
  order and options; and `layout(d, ..., previous=layout(d, ...)) == layout(d, ...)`;
- pinned: in a layer whose pinned vertices `p_1, p_2, ...` (in order) have
  `previous[p_j] - o(p_j)` non-decreasing in j and `previous[p_1] >= o(p_1)` (the
  order leaves room for them, `o` being that layer's packed offsets), every pinned
  vertex's across coordinate is exactly `previous[v]`;
- equal inputs give `==` results.

Inputs: `place`: an {Order}; `direction` `"down"` or `"right"`; `gap`, `lane_gap` ints
  >= 0; `rank_gap` an int >= 0; `passes` an int >= 0; `previous` `None`, a {Coords} or
  a mapping vertex -> int. `layout`: a {Dag}, the options of [Ranks]' `ranks`
  (`compact`), [Order]'s `order` (`sweeps`, `transpose`) and `place`, `previous` `None`
  or a {Coords}.
Outputs: {Coords}.
Errors: `GraphError` for a `direction` not `"down"` or `"right"`, a negative gap,
  rank_gap or passes, a `previous` {Coords} laid in the other direction, or a negative
  pinned value. `TypeError` when `order` is not an {Order}, an option is not an int (a
  `bool` included), or `previous` is neither `None`, a {Coords} nor a mapping of ints.
  `layout` raises what `ranks`, `order` and `place` raise.
Effects: none.

Usage:
    from cure.draw.graph.ranks import Dag, Node
    from cure.draw.graph.place import layout
    d = Dag([Node("a", 3), Node("b", 3), Node("c", 3), Node("d", 3), Node("e", 3)],
            [("a", "c"), ("b", "c"), ("a", "d"), ("c", "e"), ("d", "e"), ("a", "e")])
    c = layout(d)              # order (("a", "b"), ("d", ("a", "e", 1), "c"), ("e",))
    c.rects["a"], c.rects["b"]                 # Rect(1, 0, 3, 1), Rect(6, 0, 3, 1)
    c.rects["d"], c.rects[("a", "e", 1)], c.rects["c"]
                                               # Rect(0, 3, 3, 1), Rect(4, 3, 1, 1), Rect(6, 3, 3, 1)
    c.rects["e"]                               # Rect(3, 6, 3, 1)
    c.layer_at, c.layer_size, c.width, c.height   # (0, 3, 6), (1, 1, 1), 9, 7
    # drawn (a vertex's first cell its name, '.' a virtual vertex):
    #  " a    b"  /  ""  /  ""  /  "d   . c"  /  ""  /  ""  /  "   e"
    d2 = Dag(d.nodes + (Node("f", 3),), d.edges + (("b", "f"),))
    s = layout(d2, previous=c)                 # every old vertex keeps its rect
    all(s.rects[v] == c.rects[v] for v in c.rects), s.rects["f"]   # True, Rect(11, 3, 3, 1)
    layout(d2).rects["a"]                      # Rect(3, 0, 3, 1): laid fresh, a moves
    r = layout(d, direction="right")
    r.rects["a"], r.rects["e"], r.width, r.height   # Rect(0, 1, 3, 1), Rect(10, 2, 3, 1), 13, 5
"""

from collections.abc import Mapping
from dataclasses import dataclass

from cure.core.geometry.rect import Rect

from .order import Order, order
from .ranks import Dag, GraphError, ranks

DIRECTIONS: tuple[str, ...] = ("down", "right")
"""The layer axis: layers as rows top to bottom, or as columns left to right."""


@dataclass(frozen=True)
class Coords:
    """{Coords}: every vertex's rect, the layers' positions, the extent."""

    order: Order
    direction: str
    rects: dict
    layer_at: tuple
    layer_size: tuple
    width: int
    height: int

    def across(self) -> dict:
        """Each vertex's across coordinate (x when down, y when right)."""
        if self.direction == "down":
            return {v: r.x for v, r in self.rects.items()}
        return {v: r.y for v, r in self.rects.items()}


def _option(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if value < 0:
        raise GraphError(f"{name} must be >= 0, got {value}")
    return value


def _previous(direction: str, previous: object) -> dict:
    """`previous` as a checked mapping vertex -> int ({} for None)."""
    if previous is None:
        return {}
    if isinstance(previous, Coords):
        if previous.direction != direction:
            raise GraphError(f"previous was laid {previous.direction!r}, not {direction!r}")
        previous = previous.across()
    elif not isinstance(previous, Mapping):
        raise TypeError(f"previous must be None, a Coords or a mapping, got {type(previous).__name__}")
    for v, value in previous.items():
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"previous[{v!r}] must be an int, got {type(value).__name__}")
    return previous


def _pins(order: Order, previous: dict) -> dict:
    """The pinned vertices (keys of `previous` that are vertices) and their old across coordinates."""
    vertices = {v for layer in order.layers for v in layer}
    pins = {}
    for v, value in previous.items():
        if v in vertices:
            if value < 0:
                raise GraphError(f"previous[{v!r}] must be >= 0, got {value}")
            pins[v] = value
    return pins


def _sizes(order: Order, direction: str) -> dict:
    """Each vertex's (across, along) size."""
    nodes = {n.id: n for n in order.ranks.dag.nodes}
    sizes = {}
    for layer in order.layers:
        for v in layer:
            if isinstance(v, str):
                n = nodes[v]
                w, h = n.width, n.height
            else:
                w, h = 1, 1
            sizes[v] = (w, h) if direction == "down" else (h, w)
    return sizes


def _offsets(layer: tuple, across: dict, gap: int, lane_gap: int) -> list:
    """The packed offsets o_i of one layer."""
    offsets = []
    for i, v in enumerate(layer):
        if i == 0:
            offsets.append(0)
            continue
        u = layer[i - 1]
        sep = gap if isinstance(u, str) and isinstance(v, str) else lane_gap
        offsets.append(offsets[-1] + across[u] + sep)
    return offsets


def _lower_median(ordered: list, total: int) -> int:
    """The weighted lower median of (z, weight) pairs sorted by z, their weights summing
    to `total`."""
    running = 0
    for z, w in ordered:
        running += w
        if 2 * running >= total:
            return z
    raise AssertionError("unreachable: a block has members")


def _put(offsets: list, targets: list, weights: list) -> list:
    """PUT: pool adjacent violators over z = t - o, then x = max(0, value) + o."""
    # Speed: a block keeps its members sorted and its total weight; two pooled blocks'
    # sorted members are merged (`sort` of two sorted runs, which Timsort merges in one
    # pass, the same list a full sort gives), so the median needs no re-sort and no re-sum.
    blocks = []  # [value, members as (z, weight) sorted, count, total weight]
    for o, t, w in zip(offsets, targets, weights):
        blocks.append([t - o, [(t - o, w)], 1, w])
        while len(blocks) >= 2 and blocks[-2][0] > blocks[-1][0]:
            last = blocks.pop()
            prior = blocks[-1]
            members = prior[1]
            members.extend(last[1])
            members.sort()
            prior[2] += last[2]
            prior[3] += last[3]
            prior[0] = _lower_median(members, prior[3])
    xs = []
    for value, _, count, _ in blocks:
        xs.extend([max(0, value)] * count)
    return [x + o for x, o in zip(xs, offsets)]


def _targets(layer: tuple, at: dict, across: dict, ends: dict, pins: dict) -> list:
    """Each vertex's target against a reference layer (its pin, or its neighbours' centre)."""
    targets = []
    for v in layer:
        if v in pins:
            targets.append(pins[v])
            continue
        ns = ends.get(v)
        if not ns:
            targets.append(at[v])
            continue
        centre = sum(at[n] + (across[n] - 1) // 2 for n in ns) // len(ns)
        targets.append(centre - (across[v] - 1) // 2)
    return targets


def _neighbours(order: Order) -> tuple:
    up, down = {}, {}
    for upper, lower in order.ranks.segments():
        down.setdefault(upper, []).append(lower)
        up.setdefault(lower, []).append(upper)
    return up, down


def _across(order: Order, across: dict, pins: dict, gap: int, lane_gap: int, passes: int,
            shift: bool) -> dict:
    """The across coordinate of every vertex: start, then the passes, then the shift."""
    layers = order.layers
    offsets = [_offsets(layer, across, gap, lane_gap) for layer in layers]
    weights = [[len(layer) if v in pins else 1 for v in layer] for layer in layers]
    at = {}

    def put(r: int, targets: list) -> None:
        for v, x in zip(layers[r], _put(offsets[r], targets, weights[r])):
            at[v] = x

    for r, layer in enumerate(layers):
        put(r, [pins.get(v, o) for v, o in zip(layer, offsets[r])])
    up, down = _neighbours(order)
    height = len(layers)
    for _ in range(passes):
        for r in range(1, height):
            put(r, _targets(layers[r], at, across, up, pins))
        for r in range(height - 2, -1, -1):
            put(r, _targets(layers[r], at, across, down, pins))
    if shift and at:
        least = min(at.values())
        at = {v: x - least for v, x in at.items()}
    return at


def place(order: Order, *, direction: str = "down", gap: int = 2, lane_gap: int = 1,
          rank_gap: int = 2, passes: int = 4,
          previous: "Coords | Mapping[object, int] | None" = None) -> Coords:
    """Every vertex's rect: layers along one axis, each layer packed and centred on its neighbours, pins kept."""
    if not isinstance(order, Order):
        raise TypeError(f"expected an Order, got {type(order).__name__}")
    if direction not in DIRECTIONS:
        raise GraphError(f"direction must be one of {DIRECTIONS}, got {direction!r}")
    gap = _option(gap, "gap")
    lane_gap = _option(lane_gap, "lane_gap")
    rank_gap = _option(rank_gap, "rank_gap")
    passes = _option(passes, "passes")
    given = _previous(direction, previous)
    pins = _pins(order, given)
    sizes = _sizes(order, direction)
    across_size = {v: a for v, (a, _) in sizes.items()}
    layer_size = tuple(max(sizes[v][1] for v in layer) for layer in order.layers)
    layer_at = []
    for r, size in enumerate(layer_size):
        layer_at.append(0 if r == 0 else layer_at[-1] + layer_size[r - 1] + rank_gap)
    at = _across(order, across_size, pins, gap, lane_gap, passes, shift=not given)
    rects = {}
    for r, layer in enumerate(order.layers):
        for v in layer:
            a, b = sizes[v]
            if direction == "down":
                rects[v] = Rect(at[v], layer_at[r], a, b)
            else:
                rects[v] = Rect(layer_at[r], at[v], b, a)
    width = max((rect.right for rect in rects.values()), default=0)
    height = max((rect.bottom for rect in rects.values()), default=0)
    return Coords(order, direction, rects, tuple(layer_at), layer_size, width, height)


def layout(dag: Dag, *, compact: bool = False, sweeps: int = 4, transpose: bool = True,
           direction: str = "down", gap: int = 2, lane_gap: int = 1, rank_gap: int = 2,
           passes: int = 4, previous: "Coords | None" = None) -> Coords:
    """`place(order(ranks(dag)))`, with `previous.across()` given to both `order` and `place`."""
    if previous is not None and not isinstance(previous, Coords):
        raise TypeError(f"previous must be None or a Coords, got {type(previous).__name__}")
    kept = previous.across() if previous is not None else None
    o = order(ranks(dag, compact=compact), sweeps=sweeps, transpose=transpose, previous=kept)
    return place(o, direction=direction, gap=gap, lane_gap=lane_gap, rank_gap=rank_gap,
                 passes=passes, previous=previous)
