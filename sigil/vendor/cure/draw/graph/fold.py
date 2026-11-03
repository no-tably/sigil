"""[Fold]: too wide: wrap layers into bands.

Kind: service (data classes and a pure function).

What it does: `fold(coords, limit)` ({Width} => {Bands}, on [Place]) wraps a layout that
is too long along its layer axis, as text wraps into lines: runs of consecutive layers
become BANDS, each at most `limit` cells long, and the bands are stacked across. A
layout laid `"right"` (layers as columns) that is wider than the pane gives bands
stacked top to bottom, each at most `limit` columns wide; one laid `"down"` (layers as
rows) that is taller than `limit` rows gives bands set side by side, left to right.
Nothing inside a band moves relative to the rest of its band.

What crosses a band boundary: only the segments from the last layer of a band to the
first layer of the next (no segment joins two layers that are not adjacent, and no two
bands share a layer). For each boundary Fold lists the edges whose chains cross it and
leaves one track (a row when bands stack down, a column when they sit side by side)
per such edge between the two bands, plus `gap`; Graph's [Route] (G2) runs those wires
out of the band's far side, along their tracks and into the next band's near side.

The rule, on a {Coords} `c` with H layers (its `layer_at`, `layer_size`):
1. Bands, greedy: a band starts at layer s (the first: s = 0) and takes layers
   s .. e for the greatest e with `layer_at[e] + layer_size[e] - layer_at[s] <=
   limit`; when even layer s alone is longer than `limit`, the band is that one layer
   and is OVER (`over=True`: wider than asked; never silently cut). The next band
   starts at e + 1.
2. Each band's across extent: `lo`, the least across coordinate of its vertices, and
   `size`, the greatest across end (`across + across size`) minus `lo`.
3. Its crossing edges: the indices into `dag.edges` (ascending) of the edges whose
   chain has a segment from layer `last` of this band to layer `last + 1`; `()` for
   the last band.
4. Placing: band 0 is `at = 0`; band k + 1 is at `at_k + size_k + gap +
   len(crossing_k)`. Every vertex of band k moves by `-layer_at[first]` along the layer
   axis and by `at_k - lo_k` across. That is `(dx, dy)`: right-laid,
   `dx = -layer_at[first]`, `dy = at - lo`; down-laid, `dx = at - lo`,
   `dy = -layer_at[first]`.

The data (frozen dataclasses; the dict is not to be mutated):
- `Band(first: int, last: int, at: int, size: int, dx: int, dy: int,
  crossing: tuple[int, ...], over: bool)`: layers `first .. last` (inclusive), its
  across start and extent after folding, the move every vertex of it took, the edges
  crossing to the next band, and whether it is longer than the limit.
- `Bands(coords: Coords, bands: tuple[Band, ...], rects: dict[Vertex, Rect], width:
  int, height: int)`: the layout folded, `rects` every vertex's rect moved by its band
  (keyed as `coords.rects`), `width` / `height` the greatest `x + w` / `y + h` over
  them (0, 0 when empty). An empty layout gives no bands.

Laws:
- the bands cover the layers 0 .. H - 1 in order, each once;
- a band that is not `over` is at most `limit` long on the layer axis
  (`layer_at[last] + layer_size[last] - layer_at[first] <= limit`); an `over` band is
  one layer;
- no two folded rects overlap, and each band lies across in `at .. at + size - 1`;
- a layout that fits (its layer-axis extent <= `limit`) is one band; when its least
  across coordinate is 0 (every layout laid without `previous`), `rects ==
  coords.rects`;
- equal inputs give `==` results.

Inputs: a {Coords}; `limit` an int >= 1 (columns for a right-laid layout, rows for a
  down-laid one); `gap` an int >= 0.
Outputs: {Bands}.
Errors: `GraphError` when `limit < 1` or `gap < 0`. `TypeError` when `coords` is not
  a {Coords} or `limit` / `gap` is not an int (a `bool` included).
Effects: none.

Usage:
    from cure.draw.graph.ranks import Dag, Node
    from cure.draw.graph.place import layout
    from cure.draw.graph.fold import fold
    ch = Dag([Node(n, 3) for n in "abcde"],
             [("a", "b"), ("b", "c"), ("c", "d"), ("d", "e"), ("a", "c")])
    c = layout(ch, direction="right")      # layers at x 0, 5, 10, 15, 20; 23 x 3
    f = fold(c, 12)
    [(b.first, b.last, b.at, b.size, b.crossing) for b in f.bands]
        # [(0, 1, 0, 3, (1, 4)), (2, 3, 6, 1, (3,)), (4, 4, 9, 1, ())]
    f.bands[1].dx, f.bands[1].dy           # (-10, 5)
    f.rects["c"], f.rects["d"], f.rects["e"]   # Rect(0, 6, 3, 1), Rect(5, 6, 3, 1), Rect(0, 9, 3, 1)
    f.width, f.height                      # (8, 10)
    fold(c, 23).rects == c.rects           # True: it fits
    [b.over for b in fold(c, 2).bands]     # [True, True, True, True, True]
"""

from dataclasses import dataclass

from .place import Coords
from .ranks import GraphError


@dataclass(frozen=True)
class Band:
    """A run of consecutive layers, placed across, and the edges crossing to the next band."""

    first: int
    last: int
    at: int
    size: int
    dx: int
    dy: int
    crossing: tuple
    over: bool


@dataclass(frozen=True)
class Bands:
    """{Bands}: a layout folded into bands: every vertex's rect after folding, and the extent."""

    coords: Coords
    bands: tuple
    rects: dict
    width: int
    height: int


def _int_option(value: object, name: str, least: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if value < least:
        raise GraphError(f"{name} must be >= {least}, got {value}")
    return value


def _runs(layer_at: tuple, layer_size: tuple, limit: int) -> list:
    """Step 1: the greedy runs of layers, (first, last, over)."""
    runs, s, count = [], 0, len(layer_at)
    while s < count:
        e = s
        while e + 1 < count and layer_at[e + 1] + layer_size[e + 1] - layer_at[s] <= limit:
            e += 1
        over = layer_size[s] > limit
        runs.append((s, e, over))
        s = e + 1
    return runs


def _layer_of(coords: Coords) -> dict:
    return {v: r for r, layer in enumerate(coords.order.layers) for v in layer}


def _extent(coords: Coords, vertices: list) -> tuple:
    """Step 2: a band's least across coordinate and its across extent."""
    down = coords.direction == "down"
    starts, ends = [], []
    for v in vertices:
        rect = coords.rects[v]
        start, size = (rect.x, rect.w) if down else (rect.y, rect.h)
        starts.append(start)
        ends.append(start + size)
    lo = min(starts)
    return lo, max(ends) - lo


def _crossings(coords: Coords, layer_of: dict) -> dict:
    """Step 3, for every layer r: the edges (ascending) whose chain steps from r to r + 1."""
    found = {}
    for k, chain in enumerate(coords.order.ranks.chains):
        for upper, lower in zip(chain, chain[1:]):
            r = layer_of[upper]
            if layer_of[lower] == r + 1:
                found.setdefault(r, []).append(k)
    return {r: tuple(ks) for r, ks in found.items()}


def fold(coords: Coords, limit: int, *, gap: int = 1) -> Bands:
    """The layout's layers wrapped into bands at most `limit` long, stacked across with tracks between."""
    if not isinstance(coords, Coords):
        raise TypeError(f"expected Coords, got {type(coords).__name__}")
    limit = _int_option(limit, "limit", 1)
    gap = _int_option(gap, "gap", 0)
    layers = coords.order.layers
    layer_of = _layer_of(coords)
    runs = _runs(coords.layer_at, coords.layer_size, limit)
    steps = _crossings(coords, layer_of)
    down = coords.direction == "down"
    bands, move, at = [], {}, 0
    for n, (first, last, over) in enumerate(runs):
        vertices = [v for r in range(first, last + 1) for v in layers[r]]
        lo, size = _extent(coords, vertices)
        crossing = steps.get(last, ()) if n + 1 < len(runs) else ()
        along, across = -coords.layer_at[first], at - lo
        dx, dy = (across, along) if down else (along, across)
        bands.append(Band(first, last, at, size, dx, dy, crossing, over))
        for r in range(first, last + 1):
            move[r] = (dx, dy)
        at += size + gap + len(crossing)
    rects = {v: rect.moved(*move[layer_of[v]]) for v, rect in coords.rects.items()}
    width = max((rect.right for rect in rects.values()), default=0)
    height = max((rect.bottom for rect in rects.values()), default=0)
    return Bands(coords, tuple(bands), rects, width, height)
