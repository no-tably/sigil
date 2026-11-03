"""[Lanes]: a narrow lane view (git log --graph, renderdag): one row per node, for a live
schedule.

Kind: service (data classes and a pure function).

What it does: `lanes(dag)` ({Dag} => {Rows}, on [Ranks]) lays the dag out as ONE ROW PER
NODE, in a topological order, with each edge still to be reached running down a column
(a LANE) from its tail's row to its head's row, the way `git log --graph` and Sapling's
renderdag draw history in a narrow pane. A row says where its node sits and, for every
column of the lane graph, a DIRECTION MASK: the arms a caller strokes there. Glyphs are
never picked here: the masks are Canvas's ([Junctions]' `N = 1`, `E = 2`, `S = 4`,
`W = 8`), drawn with the {Charset} the caller has (`junctions.glyph(mask, weight,
charset)`, or a Canvas `stub` per arm), and the node's own cell is the caller's
marker (a status glyph: ready, held, done). The caller puts the node's label after
the lane columns, which are the same width on every row.

Columns: lane k is column `2 * k`; the odd columns between lanes carry only horizontal
links. Every row has `width = 2 * L - 1` cells, L the most lanes open at any point
(after any appends of the row, before trimming), 0 for an empty dag.

The state between rows is a list `lanes` of lane slots, each `None` (free) or the id of
the node that lane runs to; it starts empty. The edges are [Ranks]' oriented edges
(cycles broken by `acyclic`; a reversed edge runs down from its new tail, and
`Lanes.reversed` names it so a caller may mark it). For each node n in `rows` order:
1. Arriving: `arrive = [k for k, t in enumerate(lanes) if t == n]` (ascending). The
   node's lane `col` is `arrive[0]`; with none arriving, the first free slot, or a new
   slot appended at the end. `below` starts as a copy of `lanes` with every slot of
   `arrive` set free (they all end at n).
2. Leaving: n's children are the heads of its oriented out-edges in edge order, each
   once (a 2-cycle's doubled edge counts once). For each child c, in that order:
   - a slot of `below` already runs to c (a lane from another parent): a JOIN link
     from `col` to that slot (the first such);
   - else, `below[col]` is free: it becomes c (the lane goes straight down);
   - else: a FORK link to the first slot of `below` that is free and not in `arrive`
     (a lane ending on this row is not reused on it), or to a new slot appended; that
     slot becomes c.
   Each slot of `arrive` other than `col` is a MERGE link into `col`.
3. Then trailing free slots of `below` are dropped, and `below` is the next row's
   `lanes`.

The cells of n's row (the OR of every rule that applies; others 0):
- a PASSING lane, a slot k != col that ran to some node other than n before the row:
  `N | S` at column 2k;
- a MERGE from slot k: `N` plus the arm toward col (`W` when k > col, `E` when k < col);
  a FORK to slot k: `S` plus the arm toward col; a JOIN to slot k: the arm toward col
  (added to that lane's `N | S`);
- the node's column 2*col: `N` when a lane arrived in it (col in `arrive`), `S` when
  `below[col]` is not free, `E` when any link's slot is right of col, `W` when any is
  left of it;
- every column strictly between 2*col and a link's column 2k: `E | W`, except the
  column of a passing lane that is no link's slot: it keeps `N | S` only. That is a
  HOP-OVER as Canvas draws one (`─│─`, [Strokes]): the line crossed keeps its cell and
  the cells either side keep their arms toward it, so it never reads as joined.

The data (frozen dataclasses):
- `Row(node: str, lane: int, x: int, cells: tuple[int, ...])`: the node, its lane, its
  column (`x == 2 * lane`) and the masks, `len(cells) == width`.
- `Lanes(dag: Dag, rows: tuple[Row, ...], width: int, reversed: tuple[tuple[str,
  str], ...])`: a row per node in the order laid, the shared width, and [Ranks]'
  `acyclic(dag)`.

`rows`: `None` is [Ranks]' `topo(dag)` (Kahn, least node index first). A caller may
give its own order instead (done tasks first, say): a sequence holding every id once,
each oriented edge's tail before its head; anything else is a GraphError.

Laws:
- one row per node, in `rows` order; every row has `width` cells and `x == 2 * lane`,
  and `cells[x]` is never 0 unless the node has no edge at all;
- a column's arms meet: for consecutive rows i, i + 1 and every column j,
  `cells_i[j] & S` is set exactly when `cells_{i+1}[j] & N` is; and within a row,
  `cells[j] & E` is set exactly when `cells[j + 1] & W` is, except across a hop-over
  (where the passing lane has neither);
- the first row has no `N` arm anywhere and the last no `S`;
- prefix: for a dag without cycles, rows `0 .. i` depend only on the nodes of those
  rows and the edges out of them, in edge order: two such dags that agree on those
  give the same rows `0 .. i`, cell for cell, up to zeros padded on the right (their
  widths may differ). So appending a node a live schedule gained keeps every row
  above the first of its parents;
- equal inputs give `==` results.

Inputs: a {Dag}; `rows` `None` or a sequence of ids.
Outputs: {Lanes} (its `rows`: the {Rows}).
Errors: `GraphError` when `rows` misses an id, repeats one, names an unknown one, or
  puts a head before its tail. `TypeError` when `dag` is not a {Dag} or `rows` is not
  a sequence of `str`.
Effects: none.

Usage:
    from cure.draw.graph.ranks import Dag
    from cure.draw.graph.lanes import lanes
    from cure.draw.canvas.junctions import glyph  # a mask and a weight -> the charset's glyph
    from cure.draw.theme.charset import Charset
    v = lanes(Dag(["a", "b", "c", "d"], [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")]))
    [(r.node, r.lane, r.cells) for r in v.rows]
        # [("a", 0, (6, 10, 12)), ("b", 0, (5, 0, 5)), ("c", 1, (7, 10, 9)), ("d", 0, (1, 0, 0))]
    cs = Charset()
    ["".join("●" if j == r.x else (glyph(m, "light", cs) or " ") for j, m in enumerate(r.cells))
     + " " + r.node for r in v.rows]
        # ["●─┐ a", "● │ b", "├─● c", "●   d"]   (rounded=True gives "●─╮ a")
    d = Dag(["a", "b", "c", "d", "e"],
            [("a", "c"), ("b", "c"), ("a", "d"), ("c", "e"), ("d", "e"), ("a", "e")])
    w = lanes(d)                 # width 7; drawn the same way:
        # ["●─┬─┐   a", "├─│─│─● b", "●─│─┤   c", "  ●─┤   d", "    ●   e"]
        # b joins c's lane, hopping over d's and e's
    lanes(d, ["b", "a", "d", "c", "e"]).width   # 5:
        # ["●     b", "├─●─┐ a", "│ ●─┤ d", "●───┤ c", "    ● e"]
"""

from collections.abc import Sequence
from dataclasses import dataclass

from .ranks import Dag, GraphError, acyclic, topo


@dataclass(frozen=True)
class Row:
    """One node's row of the lane view: its lane, its column, and every column's mask."""

    node: str
    lane: int
    x: int
    cells: tuple


@dataclass(frozen=True)
class Lanes:
    """{Rows}: the lane view, a row per node, the shared width, the edges reversed."""

    dag: Dag
    rows: tuple
    width: int
    reversed: tuple


_N, _E, _S, _W = 1, 2, 4, 8  # Canvas's [Junctions] arms


def _children(dag: Dag, back: tuple) -> dict:
    """Each node's oriented children, in edge order, each once."""
    reversed_ = set(back)
    kids = {id: [] for id in dag.ids}
    for u, v in dag.edges:
        a, b = (v, u) if (u, v) in reversed_ else (u, v)
        if b not in kids[a]:
            kids[a].append(b)
    return kids


def _checked_rows(dag: Dag, rows: object, kids: dict) -> tuple:
    if rows is None:
        return topo(dag)
    if isinstance(rows, str) or not isinstance(rows, Sequence):
        raise TypeError(f"rows must be a sequence of ids, got {type(rows).__name__}")
    for id in rows:
        if not isinstance(id, str):
            raise TypeError(f"rows must hold str ids, got {type(id).__name__}")
    order = tuple(rows)
    known = set(dag.ids)
    for id in order:
        if id not in known:
            raise GraphError(f"rows names an unknown id {id!r}")
    if len(set(order)) != len(order):
        raise GraphError("rows repeats an id")
    if len(order) != len(known):
        raise GraphError("rows misses an id")
    at = {id: k for k, id in enumerate(order)}
    for a, heads in kids.items():
        for b in heads:
            if at[a] > at[b]:
                raise GraphError(f"rows puts {b!r} before its tail {a!r}")
    return order


def _free_slot(below: list, avoid: tuple) -> int:
    """The first free slot not in `avoid`, or a new one appended."""
    for k, t in enumerate(below):
        if t is None and k not in avoid:
            return k
    below.append(None)
    return len(below) - 1


def _toward(k: int, col: int) -> int:
    return _W if k > col else _E


def _row(n: str, lanes_: list, kids: list) -> tuple:
    """One node's row: its lane, the masks, the next row's lanes and the most slots open."""
    arrive = tuple(k for k, t in enumerate(lanes_) if t == n)
    below = list(lanes_)
    if arrive:
        col = arrive[0]
    else:
        col = _free_slot(below, ())
    for k in arrive:
        below[k] = None
    links = []  # (kind, slot)
    for c in kids:
        joined = next((k for k, t in enumerate(below) if t == c), None)
        if joined is not None:
            links.append(("join", joined))
        elif below[col] is None:
            below[col] = c
        else:
            k = _free_slot(below, arrive)
            below[k] = c
            links.append(("fork", k))
    links.extend(("merge", k) for k in arrive if k != col)
    widest = len(below)
    cells = [0] * (2 * widest - 1)
    passing = {k for k, t in enumerate(lanes_) if k != col and t is not None and t != n}
    for k in passing:
        cells[2 * k] |= _N | _S
    slots = {k for _, k in links}
    for kind, k in links:
        arm = _toward(k, col)
        cells[2 * k] |= arm | (_N if kind == "merge" else _S if kind == "fork" else 0)
        lo, hi = sorted((2 * col, 2 * k))
        for j in range(lo + 1, hi):
            if j % 2 == 0 and j // 2 in passing and j // 2 not in slots:
                continue
            cells[j] |= _E | _W
    here = 0
    if col in arrive:
        here |= _N
    if below[col] is not None:
        here |= _S
    if any(k > col for k in slots):
        here |= _E
    if any(k < col for k in slots):
        here |= _W
    cells[2 * col] |= here
    while below and below[-1] is None:
        below.pop()
    return col, cells, below, widest


def lanes(dag: Dag, rows: "Sequence[str] | None" = None) -> Lanes:
    """The dag as one row per node, lanes running down to each edge's head, as Canvas masks."""
    if not isinstance(dag, Dag):
        raise TypeError(f"expected a Dag, got {type(dag).__name__}")
    back = acyclic(dag)
    kids = _children(dag, back)
    order = _checked_rows(dag, rows, kids)
    state, laid, most = [], [], 0
    for n in order:
        col, cells, state, widest = _row(n, state, kids[n])
        laid.append((n, col, cells))
        most = max(most, widest)
    width = 2 * most - 1 if most else 0
    out = tuple(Row(n, col, 2 * col, tuple(cells) + (0,) * (width - len(cells)))
                for n, col, cells in laid)
    return Lanes(dag, out, width, back)
