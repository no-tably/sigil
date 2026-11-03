"""[Blocks]: one cell per node: a minimap.

Kind: service (a data class and pure functions).

What it does: reduces a laid-out dag to a grid where each real node is ONE CELL, for a
minimap (construct's: one block per component, builders lit, a click opens it). Two
reductions: `grid(order)` keeps only the structure, a node's cell being its place
among the real nodes of its layer and its layer (no scaling: nodes never share a
cell); `scaled(coords, sx, sy)` keeps the geometry, a node's cell being its centre
divided by the scale (several nodes may share one). Virtual vertices are dropped
either way. Drawing the cells (a block glyph from the {Charset}, a colour by status)
and hit-testing them are the caller's: `cells` says which nodes each cell holds.

`grid(order, *, direction="down")`: for layer r of the {Order}, its real nodes in
order (virtual vertices skipped) get i = 0, 1, ...; the node's cell is `(i, r)` laid
down, `(r, i)` laid right.

`scaled(coords, sx=2, sy=1)`: for each real node with rect `R` in the {Coords}, its
centre `(R.x + (R.w - 1) // 2, R.y + (R.h - 1) // 2)`, and its cell `(cx // sx,
cy // sy)`. (The default 2 x 1 halves the width only: a cell is about twice as tall as
it is wide.)

The data, `Blocks` (frozen dataclass; its dicts are not to be mutated):
- `Blocks(cells: dict[tuple[int, int], tuple[str, ...]], at: dict[str, tuple[int,
  int]], width: int, height: int)`: `cells` maps each occupied `(x, y)` to the ids in
  it, in node order (keys in `(y, x)` order); `at` maps each real node to its cell,
  in node order; `width` / `height` are the greatest `x + 1` / `y + 1` over the cells
  (0, 0 when there are none).

Laws:
- every real node is in exactly one cell, and `at[id]` is that cell;
- `grid`: no cell holds two nodes, and every row (down) or column (right) up to the
  layer count holds a node;
- `scaled(c, 1, 1)`: a node's cell is its rect's centre cell, so no two nodes share
  one (rects never overlap);
- `scaled` keeps order: a node left of (above) another in the layout is never in a
  column (row) right of (below) the other's;
- equal inputs give `==` results.

Inputs: `grid`: an {Order}; `direction` `"down"` or `"right"`. `scaled`: a {Coords};
  `sx`, `sy` ints >= 1.
Outputs: `Blocks`.
Errors: `GraphError` for a `direction` not `"down"` or `"right"`, or `sx` / `sy` < 1.
  `TypeError` when `order` / `coords` has the wrong type or a scale is not an int (a
  `bool` included).
Effects: none.

Usage:
    from cure.draw.graph.ranks import Dag, Node
    from cure.draw.graph.place import layout
    from cure.draw.graph.blocks import grid, scaled
    d = Dag([Node("a", 3), Node("b", 3), Node("c", 3), Node("d", 3), Node("e", 3)],
            [("a", "c"), ("b", "c"), ("a", "d"), ("c", "e"), ("d", "e"), ("a", "e")])
    c = layout(d)      # a (1, 0), b (6, 0), d (0, 3), c (6, 3), e (3, 6); each 3 x 1
    g = grid(c.order)
    g.at               # {"a": (0, 0), "b": (1, 0), "c": (1, 1), "d": (0, 1), "e": (0, 2)}
    g.width, g.height  # (2, 3)
    s = scaled(c, 3, 3)
    s.at               # {"a": (0, 0), "b": (2, 0), "c": (2, 1), "d": (0, 1), "e": (1, 2)}
    scaled(c, 8, 8).cells   # {(0, 0): ("a", "b", "c", "d", "e")}
"""

from dataclasses import dataclass

from .order import Order
from .place import Coords
from .ranks import GraphError


@dataclass(frozen=True)
class Blocks:
    """A minimap: each occupied cell's nodes, each node's cell, and the extent."""

    cells: dict
    at: dict
    width: int
    height: int


def _blocks(at: dict, node_order: tuple) -> Blocks:
    """The cells (keys in (y, x) order, ids in node order) of each node's cell."""
    ordered = {id: at[id] for id in node_order if id in at}
    cells = {}
    for id, cell in ordered.items():
        cells.setdefault(cell, []).append(id)
    cells = {cell: tuple(cells[cell]) for cell in sorted(cells, key=lambda c: (c[1], c[0]))}
    width = max((x + 1 for x, _ in cells), default=0)
    height = max((y + 1 for _, y in cells), default=0)
    return Blocks(cells, ordered, width, height)


def grid(order: Order, *, direction: str = "down") -> Blocks:
    """One cell per real node: its place among its layer's real nodes, and its layer."""
    if not isinstance(order, Order):
        raise TypeError(f"expected an Order, got {type(order).__name__}")
    if direction not in ("down", "right"):
        raise GraphError(f"direction must be 'down' or 'right', got {direction!r}")
    at = {}
    for r, layer in enumerate(order.layers):
        reals = [v for v in layer if isinstance(v, str)]
        for i, id in enumerate(reals):
            at[id] = (i, r) if direction == "down" else (r, i)
    return _blocks(at, order.ranks.dag.ids)


def _scale(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if value < 1:
        raise GraphError(f"{name} must be >= 1, got {value}")
    return value


def scaled(coords: Coords, sx: int = 2, sy: int = 1) -> Blocks:
    """One cell per real node: its rect's centre divided by the scale."""
    if not isinstance(coords, Coords):
        raise TypeError(f"expected Coords, got {type(coords).__name__}")
    sx, sy = _scale(sx, "sx"), _scale(sy, "sy")
    at = {}
    for v, r in coords.rects.items():
        if isinstance(v, str):
            at[v] = ((r.x + (r.w - 1) // 2) // sx, (r.y + (r.h - 1) // 2) // sy)
    return _blocks(at, coords.order.ranks.dag.ids)
