"""[Route]: orthogonal wires, ports, channels, fan-out trunks, bundles.

Kind: service (two data classes and pure functions).

What it does: `route(layout)` ({Edges} => {Paths}, on [Place]) turns a laid-out dag into
one orthogonal wire per edge, as Canvas {Path}s ([Junctions]' `Path`): out of a PORT on
the source node's far side, down a CHANNEL (the gap between two layers) on a TRACK,
through the virtual vertices of a long edge (their lane cells), into a port on the
target's near side. Every edge leaving one node shares one out-port and its trunk (a
FAN-OUT TRUNK: the edges of one source in a channel run together on one track, a bus);
edges arriving at one node get ports of their own where its side has room. Channels
are made as tall as their tracks need, so Route moves layers along the layer axis
(never across: a layout kept still by [Place] stays still across). Given a layout
[Fold] wrapped into bands, the edges crossing from one band to the next run out of
the band's far side, along their track between the two bands, and into the next
band's near side. Glyphs are never picked here: [Diagram] strokes the paths onto a
Canvas (`[Graph] -> [Canvas] : draw({Paths}) => {Canvas}`), where they join into the
charset's box-drawing glyphs and a straight run crossing another hops over it.

AXES. Everything below is stated on two axes, as [Place] does: the LAYER axis (along:
rows when the layout is laid `"down"`, columns when `"right"`) and the ACROSS axis
(columns when down, rows when right). A rect's across start / size and along start /
size are `x, w, y, h` when down and `y, h, x, w` when right; a point stated as
(across p, along q) is the cell `(x, y) = (p, q)` when down and `(q, p)` when right.
"Above" / "top" mean toward along 0; "left" means toward across 0.

The input is [Place]'s {Coords} `c` (its `order.ranks` the {Layers}: chains, reversed
edges) or [Fold]'s {Bands} of a ROUTED layout (below). H is the number of layers;
CHANNEL r (0 <= r < H - 1) is the gap between layer r and layer r + 1. Its SEGMENTS
are the pieces `(upper, lower)` of the chains with `upper` in layer r ([Ranks]'
`segments`, each chain's pieces in edge order); a segment that occurs twice (a
2-cycle's two edges, oriented alike) is one segment there: such edges are a BUNDLE
and share every cell of their wire.

1. Ports (across coordinates; `inset` an int >= 0, [Diagram] gives 1 when it draws
   boxes, so a port is never a box corner):
   - A vertex's TOP PIN in channel r (r its layer): a real node's OUT-PORT, its across
     centre `a + (s - 1) // 2` (a, s its rect's across start and size), shared by all
     its edges; a virtual vertex's own across coordinate.
   - A vertex's BOTTOM PINS in channel r - 1 (r its layer): a virtual vertex has one
     segment arriving, and its pin is its across coordinate. A real node `t` with
     across start a and size s: its port span is `lo = a + inset`, `hi = a + s - 1 -
     inset`, or `lo = hi = a + (s - 1) // 2` when that is empty (`lo > hi`); `L = hi -
     lo + 1`. The NETS arriving at t (step 2) are sorted by their top pin, ascending:
     n_0 .. n_{k-1}. Each gets an IN-PORT p_i:
     - `k <= L` (distinct ports): forward, `p_0 = clamp(top(n_0))`, `p_i =
       max(clamp(top(n_i)), p_{i-1} + 1)`, `clamp(v) = min(max(v, lo), hi)`; then,
       when `p_{k-1} > hi`, backward: `p_{k-1} = hi` and `p_i = min(p_i, p_{i+1} - 1)`
       for i = k - 2 .. 0. (So one arriving net takes the column of its source when
       t spans it, and the wire is straight.)
     - `k > L` (SHARED ports, the node's side too narrow): `p_i = lo + (i * L) // k`.
2. Nets. In channel r, the segments with the same `upper` vertex form one NET: its
   `top` pin, and its `bottoms`, one `(lower, column)` per distinct lower vertex (the
   lower's pin for this net), sorted by column. Its SPAN is `(min, max)` over its top
   and bottom columns. A net whose span has one column (every bottom straight below
   its top) is STRAIGHT and takes no track; any other takes one track: its wire runs
   down from its top pin to the track, along the track over its whole span, and down
   from the track into each bottom pin. The nets of a channel are ordered by `top`
   (top pins are distinct: rects in a layer never overlap).
3. Vertical constraints, between the nets of channel r that take a track: P must be
   ABOVE N (P's track nearer the top than N's), when P != N and
   - P's top column is one of N's bottom columns (P runs down that column from the
     top to its track, N runs down it from its track to the bottom: in the other order
     they would overlap), its column being P's top; or else
   - P has two or more bottoms, N exactly one, and both have the same `(lower,
     column)` bottom (a shared in-port: the bus turns into the column above the single
     wire, so the single wire is never read as joining the bus), its column being that
     shared one.
4. Tracks, a constrained left-edge packing. The SCAN ORDER is the nets that take a
   track, sorted by `(span left, span right, top)`. Track t = 0, 1, ... in turn: going
   through the unplaced nets in scan order, a net N is put on track t when every net
   it must be below (a constraint not dropped) is already on a track `< t`, and N's
   span keeps clear of every span already on track t (`N.left >= M.right + 2` or
   `N.right <= M.left - 2`: one blank cell between two wires on one track). When a
   pass puts no net on track t while nets remain, every one of them waits on another:
   a CYCLE. Then the first unplaced net N in scan order that lies on a cycle among the
   unplaced nets (following its constraints to unplaced nets leads back to N) has
   every constraint from an unplaced net dropped, and the pass over track t is run
   again. Otherwise t goes on to t + 1. `tracks[r]`, the channel's TRACK COUNT, is the
   number of tracks used (0 when no net takes one).
5. Channels made room for (the RESTACK): channel r's given size is `g_r = layer_at[r +
   1] - layer_at[r] - layer_size[r]`; its new size is `max(g_r, tracks[r] + 1)` when
   `tracks[r] > 0`, else `g_r`. New `layer_at[0]` is the given one; `layer_at[r + 1] =
   layer_at[r] + layer_size[r] + size of channel r`. Every vertex moves along by its
   layer's change; across nothing moves. The ROUTED layout is that {Coords} (same
   `order`, `direction` and `layer_size`; `width`, `height` the rects' extent).
   Track t of channel r is at along `layer_at[r] + layer_size[r] + 1 + t` (one row,
   or column, between the layer and track 0; the last track touches the next layer).
6. Wires. Edge k's chain `v_0 .. v_m` (oriented: [Ranks]' `chains[k]`), as a list of
   (across, along) points:
   - start: `(top pin of v_0, along end of v_0's rect - 1)`: the out-port cell, the
     last cell of the source's rect on its far side;
   - for each segment `(v_i, v_{i+1})` in channel r, its net n and its bottom column b
     for `v_{i+1}`: when `n.top != b`, `(n.top, row)` and `(b, row)`, `row` n's track;
     (a virtual vertex's wire runs straight through its layer, so no point is needed
     there: its top pin is its bottom pin);
   - end: `(bottom column for v_m, along start of v_m's rect)`: the in-port cell, the
     first cell of the target's rect on its near side.
   Then the list is made CANONICAL: a point equal to the one before it is dropped, and
   a point in line with both its neighbours (the same across, or the same along, as
   both) is dropped, until neither applies. Every path has at least two points.
7. Weights, by the edge's kind: `back` for an edge [Ranks] reversed to break a cycle
   (in `layers.reversed`: it is drawn from its head down to its tail), `weight` for any
   other. Every `Path` has style `None` ([Diagram] restyles).

Folded layouts. A {Bands} `f` is routed only when its `coords` are a ROUTED layout:
`route(f.coords, inset=inset).coords == f.coords`, with the `inset` given to this call
(fold after routing with the same inset: `fold(route(c, inset=inset).coords, limit)`;
[Diagram] does so); otherwise GraphError. Then steps 1-7 run on `f.coords`
unchanged, and the result is moved and the band boundaries rewired:
- Band k's vertices, wires and tracks move by its `(dx, dy)` (across by `dA`, along
  by `dL`: `(dx, dy)` down, `(dy, dx)` right), and every along coordinate by `M` more.
- A segment from band k's last layer to band k + 1's first is a BOUNDARY segment. Its
  source pin `s` (the net's top, moved by band k's `dA`) and target pin `g` (its bottom
  column, moved by band k + 1's `dA`) make a PAIR; boundary k's distinct pairs, sorted
  by `(-s, -g)`, are j = 0, 1, ... (a bundle's edges, equal pairs, share one). N is the
  greatest number of pairs at any boundary, and `M = N + 1` when N > 0, else 0.
- `E` is the greatest along end (`along start + along size`) over the moved rects.
  The wire of boundary k's pair j: from s down to EXIT lane `E + 1 + j`, across to
  TRACK `at_k + size_k + (gap_k + 1) // 2 + j` (in the gap between the bands, `gap_k
  = at_{k+1} - at_k - size_k - len(crossing_k)`: Fold's gap), back up to ENTRY lane
  `j` (along), across to g, and down into band k + 1: the points `(s, E + 1 + j)`,
  `(T, E + 1 + j)`, `(T, j)`, `(g, j)` in place of the segment's own, then canonical.
  So a boundary's wires nest: the one whose source is furthest across takes the
  nearest track and the innermost exit and entry lanes, and they cross only where
  sources and targets are in different orders.
- One band (a layout that fits) has no boundary: M = 0 and the wires are those of the
  routed layout, moved by the band.

The data (frozen dataclasses; the dicts are not to be mutated):
- `Net(channel: int, source: Vertex, top: int, bottoms: tuple[tuple[Vertex, int],
  ...], track: int | None)`: one net of step 2, in the routed layout's coordinates
  (never moved by folding). `track` is None for a straight net. `Net.span ->
  tuple[int, int]`: `(min, max)` of `top` and the bottom columns.
- `Paths(coords: Coords, bands: Bands | None, nets: tuple[Net, ...], tracks:
  tuple[int, ...], paths: tuple[Path, ...], rects: dict[Vertex, Rect], joins:
  tuple[tuple[int, int], ...], width: int, height: int)`:
  - `coords`: the routed layout (for a {Bands}, its `coords`); `bands`: the {Bands}
    routed, or None;
  - `nets`: every channel's nets, by `(channel, top)`; `tracks`: each channel's track
    count, `len == max(H - 1, 0)`;
  - `paths`: one Canvas `Path` per edge, aligned with `dag.edges`, each from its
    oriented tail's out-port to its oriented head's in-port;
  - `rects`: every vertex's final rect (routed; folded and moved by M when banded),
    keyed as `coords.rects`;
  - `joins`: the cells `(x, y)`, sorted by `(y, x)`, each once, where a dropped
    constraint (step 4) left two wires running along one column: for each dropped
    "P above N" in column c whose tracks ended up `track(P) >= track(N)`, the cell at
    (across c, along N's track), moved with its band. `()` whenever no channel had a
    cycle; a channel of a band boundary contributes nothing (its wires are rewired);
  - `width`, `height`: the greatest `x + 1` / `y + 1` over every rect's cells and
    every path point (0, 0 for an empty dag).

Guarantees (laws a property test can loop over random dags and both directions):
- every edge drawn: `len(paths) == len(dag.edges)`; path k's first point lies in its
  oriented tail's rect and its last in its oriented head's rect;
- no wire through a box: every cell of `link(paths[k])` ([Junctions]) other than its
  first and last lies outside every real node's rect in `rects`, and its first and
  last lie in no real node's rect but their own;
- orthogonal and canonical: consecutive points differ, share an x or a y, and no
  three consecutive points are in line;
- still across: `route(c).coords.across() == c.across()`; the layer order is kept,
  and no channel shrinks;
- idempotent: `route(route(c).coords) == route(c)` (the same paths, nets, rects);
- tracks: every net with a track t in channel r has `0 <= t < tracks[r]`; two nets on
  one track have spans at least 2 apart; every constraint of step 3 holds
  (`track(P) < track(N)`) except those `joins` reports;
- ports: a real node whose k arriving nets in a channel fit its port span (`k <= L`)
  has k distinct in-ports in `lo .. hi`, in the order of their top pins;
- wires meet only where they connect: when `joins == ()` and no in-port is shared
  (`k <= L` at every node), for any two edges i != j that share neither their
  oriented tail nor their oriented head, every cell in both `link(paths[i])` and
  `link(paths[j])` that lies in no real node's rect has masks `E | W` in one and `N |
  S` in the other: a crossing, which Canvas draws as a hop-over;
- banded: every band's vertices keep their relative positions; with one band
  `route(f).paths == route(f.coords).paths` when `f.rects == f.coords.rects`;
- equal inputs give `==` results.

Where wires may read as joined (stated, not hidden): a shared in-port (`k > L`) merges
the arriving wires into one column (a FAN-IN: each tees into the next, all flowing
into the node); two buses into one shared port, or a bus sharing a port with a
straight net, meet there. A constraint cycle (step 4) is broken, and the cells are
reported in `joins`.

Inputs: `route`: a {Coords} or a {Bands} of a routed layout; `inset` an int >= 0;
  `weight`, `back`: weights of Canvas's `WEIGHTS`. `nets`: a {Coords}, `inset`.
Outputs: `route`: {Paths}. `nets`: the `Net`s of steps 1-4, by `(channel, top)`, the
  same as `route(coords, inset=inset).nets` (they depend on across coordinates only).
Errors: `GraphError` when `inset < 0`, `weight` / `back` is not in `WEIGHTS`, or a
  {Bands}' coords are not routed. `TypeError` when `layout` is neither a {Coords} nor
  a {Bands} (`nets`: not a {Coords}), or `inset` is not an int (a `bool` included).
Effects: none.

Usage:
    from cure.draw.graph.ranks import Dag, Node, ranks
    from cure.draw.graph.order import order
    from cure.draw.graph.place import layout, place
    from cure.draw.graph.fold import fold
    from cure.draw.graph.route import route
    from cure.draw.canvas import draw            # Paths => Canvas, the hop rule on
    from cure.draw.theme.charset import Charset
    cs = Charset()
    rows = lambda paths: [l.plain for l in draw(paths).rows(cs)]
    d = Dag([Node("a", 3), Node("b", 3), Node("c", 3), Node("d", 3), Node("e", 3)],
            [("a", "c"), ("b", "c"), ("a", "d"), ("c", "e"), ("d", "e"), ("a", "e")])
    p = route(layout(d))     # a (1, 0) b (6, 0) / d (0, 3) virtual (4, 3) c (6, 3) / e (3, 6)
    p.nets[0]                # Net(0, "a", 2, (("d", 2), (("a", "e", 1), 4), ("c", 6)), 0)
    p.nets[1]                # Net(0, "b", 7, (("c", 7),), None): straight down
    p.tracks, p.coords.layer_at, (p.width, p.height)   # (1, 1), (0, 3, 6), (9, 7)
    [q.points for q in p.paths]
        # [((2, 0), (2, 2), (6, 2), (6, 3)),   a -> c: a's trunk, its bus on track 0
        #  ((7, 0), (7, 3)),                   b -> c: straight
        #  ((2, 0), (2, 3)),                   a -> d
        #  ((7, 3), (7, 5), (5, 5), (5, 6)),   c -> e: e's third in-port
        #  ((1, 3), (1, 5), (3, 5), (3, 6)),   d -> e: e's first
        #  ((2, 0), (2, 2), (4, 2), (4, 6))]   a -> e: down the virtual lane at x 4
    rows(p.paths)            # the wires alone (a node's own cells show its port arms):
        # ["  │    │",
        #  "  │    │",
        #  "  ├─┬─┐│",
        #  " ││ │ ││",
        #  " │  │  │",
        #  " └─┐│┌─┘",
        #  "   │││"]
    cy = Dag([Node(n, 3) for n in "abc"], [("a", "b"), ("b", "c"), ("c", "a")])
    b = route(layout(cy))    # c -> a reversed: drawn from a down to c, dashed
    [q.weight for q in b.paths], b.paths[2].points
        # ["light", "light", "dashed"], ((2, 0), (2, 2), (4, 2), (4, 5), (3, 5), (3, 6))
    rows(b.paths)            # ["  │", "  │", "  ├╌┐", " ││ ╎", " │  ╎", " │ ┌┘", " │ ╎"]
    x = Dag(["u1", "u2", "l1", "l2"], [("u1", "l2"), ("u2", "l1")])
    c = place(order(ranks(x), sweeps=0, transpose=False), passes=0)
        # u1 (0, 0) u2 (3, 0) / l1 (0, 3) l2 (3, 3): each net's top is the other's bottom
    k = route(c)
    [(n.source, n.track) for n in k.nets], k.tracks, k.joins
        # [("u1", 0), ("u2", 1)], (2,), ((3, 2),): a cycle, broken; reported
    rows(k.paths)            # ["│  │", "│  │", "└──┤", "┌──┤", "│  │"]: they meet at (3, 2)
    ch = Dag([Node(n, 3) for n in "abcde"],
             [("a", "b"), ("b", "c"), ("c", "d"), ("d", "e"), ("a", "c")])
    r = route(layout(ch, direction="right"))
    r.tracks, r.coords.layer_at, r.rects["c"]    # (1, 2, 0, 0), (0, 5, 11, 16, 21), Rect(11, 1, 3, 1)
    f = route(fold(r.coords, 12))                # bands: layers 0-1, 2-3, 4
    f.width, f.height, f.rects["c"]              # 14, 10, Rect(3, 6, 3, 1)
    f.paths[4].points        # a -> c: through its virtual, out the right, along track
        # y 4, in from entry column 0:
        # ((5, 1), (7, 1), (7, 2), (12, 2), (12, 4), (0, 4), (0, 6), (3, 6))
    rows(f.paths)
        # ["       ┌─ ───┐",
        #  "     ──┤     │",
        #  "       └────┐│",
        #  "            ││",
        #  "┌───────────┘│",
        #  "│┌───────────┘",
        #  "└┴── ──── ──┐",
        #  "            │",
        #  "┌───────────┘",
        #  "└───"]
    route(fold(layout(ch, direction="right"), 12))   # GraphError: fold the routed layout
"""

from dataclasses import dataclass

from cure.core.geometry.rect import Rect
from cure.draw.canvas.junctions import WEIGHTS, Path

from .fold import Bands
from .place import Coords
from .ranks import GraphError

WEIGHT: str = "light"
"""The default weight of an edge's wire."""

BACK: str = "dashed"
"""The default weight of an edge [Ranks] reversed to break a cycle (drawn against its direction)."""

@dataclass(frozen=True)
class Net:
    """One source's wiring in one channel: its top pin, its bottom pins, its track (None: straight)."""

    channel: int
    source: object
    top: int
    bottoms: tuple
    track: object

    @property
    def span(self) -> tuple:
        """`(min, max)` of `top` and the bottom columns."""
        cols = [self.top] + [b for _, b in self.bottoms]
        return min(cols), max(cols)


@dataclass(frozen=True)
class Paths:
    """{Paths}: one orthogonal Canvas Path per edge, the routed layout, its nets and tracks, the final rects."""

    coords: Coords
    bands: object
    nets: tuple
    tracks: tuple
    paths: tuple
    rects: dict
    joins: tuple
    width: int
    height: int


def nets(coords: Coords, *, inset: int = 0) -> tuple:
    """Every channel's nets (steps 1-4): pins, bottoms and tracks, by (channel, top)."""
    if not isinstance(coords, Coords):
        raise TypeError(f"expected Coords, got {type(coords).__name__}")
    inset = _inset(inset)
    return _steps(coords, inset)[0]


def route(layout: "Coords | Bands", *, inset: int = 0, weight: str = WEIGHT,
          back: str = BACK) -> Paths:
    """Every edge as an orthogonal wire: ports, channel tracks, restacked layers; band boundaries rewired."""
    if isinstance(layout, Bands):
        bands, coords = layout, layout.coords
    elif isinstance(layout, Coords):
        bands, coords = None, layout
    else:
        raise TypeError(f"expected Coords or Bands, got {type(layout).__name__}")
    inset = _inset(inset)
    _weight(weight, "weight")
    _weight(back, "back")
    found, tracks, violated = _steps(coords, inset)
    routed = _restack(coords, tracks)
    if bands is not None and routed != coords:
        raise GraphError("the bands' coords are not routed: fold route(coords).coords")
    ax = _Axes(routed)
    net = {(n.channel, n.source): n for n in found}
    if bands is None:
        wires = _wires(routed, ax, net, _Plain())
        rects = routed.rects
        joins = {ax.cell(col, ax.track(r, t)) for r, col, t in violated}
    else:
        fb = _Folded(routed, ax, bands, net)
        wires = _wires(routed, ax, net, fb)
        rects = {v: fb.rect(rect) for v, rect in bands.rects.items()}
        joins = {ax.cell(*fb.moved(r, col, ax.track(r, t)))
                 for r, col, t in violated if r not in fb.last}
    weights = _weights(coords, weight, back)
    paths = tuple(Path(pts, w) for pts, w in zip(wires, weights))
    width = max([rect.right for rect in rects.values()]
                + [x + 1 for q in paths for x, _ in q.points], default=0)
    height = max([rect.bottom for rect in rects.values()]
                 + [y + 1 for q in paths for _, y in q.points], default=0)
    return Paths(routed, bands, found, tracks, paths, rects,
                 tuple(sorted(joins, key=lambda xy: (xy[1], xy[0]))), width, height)


# --- checks ---------------------------------------------------------------------------

def _inset(inset: object) -> int:
    if not isinstance(inset, int) or isinstance(inset, bool):
        raise TypeError(f"inset must be an int, got {type(inset).__name__}")
    if inset < 0:
        raise GraphError(f"inset must be >= 0, got {inset}")
    return inset


def _weight(value: object, name: str) -> None:
    if not isinstance(value, str) or value not in WEIGHTS:
        raise GraphError(f"{name} must be one of {WEIGHTS}, got {value!r}")


def _weights(coords: Coords, weight: str, back: str) -> list:
    """Step 7: each edge's weight."""
    rev = set(coords.order.ranks.reversed)
    return [back if e in rev else weight for e in coords.order.ranks.dag.edges]


# --- axes -----------------------------------------------------------------------------

class _Axes:
    """The AXES paragraph on one layout: a rect's across / along, a point's cell."""

    def __init__(self, coords: Coords) -> None:
        self.down = coords.direction == "down"
        self.coords = coords

    def across(self, rect: Rect) -> tuple:
        return (rect.x, rect.w) if self.down else (rect.y, rect.h)

    def along(self, rect: Rect) -> tuple:
        return (rect.y, rect.h) if self.down else (rect.x, rect.w)

    def cell(self, p: int, q: int) -> tuple:
        return (p, q) if self.down else (q, p)

    def track(self, r: int, t: int) -> int:
        """Step 5: the along coordinate of track t of channel r."""
        c = self.coords
        return c.layer_at[r] + c.layer_size[r] + 1 + t


def _layer_of(coords: Coords) -> dict:
    return {v: r for r, layer in enumerate(coords.order.layers) for v in layer}


# --- steps 1-4 ------------------------------------------------------------------------

def _steps(coords: Coords, inset: int) -> tuple:
    """Steps 1-4: (nets by (channel, top), track counts, violated constraints as
    (channel, column, N's track))."""
    ax = _Axes(coords)
    layer_of = _layer_of(coords)
    H = len(coords.order.layers)
    lowers = [dict() for _ in range(max(H - 1, 0))]   # channel -> upper -> {lower: None}
    for u, w in coords.order.ranks.segments():
        lowers[layer_of[u]].setdefault(u, {})[w] = None
    found, tracks, violated = [], [], []
    for r, uppers in enumerate(lowers):
        cn = _channel(ax, r, uppers, inset)
        placed, bad = _pack(cn)
        count = 0
        for source, top, bottoms in cn:
            t = placed.get(source)
            found.append(Net(r, source, top, bottoms, t))
            if t is not None:
                count = max(count, t + 1)
        tracks.append(count)
        violated.extend((r, col, placed[n]) for p, n, col in bad)
    return tuple(found), tuple(tracks), violated


def _top(ax: _Axes, v: object) -> int:
    """Step 1: a vertex's top pin."""
    a, s = ax.across(ax.coords.rects[v])
    return a + (s - 1) // 2 if isinstance(v, str) else a


def _in_ports(ax: _Axes, t: str, tops: list, inset: int) -> list:
    """Step 1: the in-ports of real node t for arriving nets with these top pins (ascending)."""
    a, s = ax.across(ax.coords.rects[t])
    lo, hi = a + inset, a + s - 1 - inset
    if lo > hi:
        lo = hi = a + (s - 1) // 2
    L, k = hi - lo + 1, len(tops)
    if k > L:
        return [lo + (i * L) // k for i in range(k)]
    clamp = lambda v: min(max(v, lo), hi)
    ports = []
    for top in tops:
        p = clamp(top)
        ports.append(p if not ports else max(p, ports[-1] + 1))
    if ports[-1] > hi:
        ports[-1] = hi
        for i in range(k - 2, -1, -1):
            ports[i] = min(ports[i], ports[i + 1] - 1)
    return ports


def _channel(ax: _Axes, r: int, uppers: dict, inset: int) -> list:
    """Steps 1-2 for channel r: its nets as (source, top, bottoms), by top."""
    tops = {u: _top(ax, u) for u in uppers}
    arriving = {}
    for u, ws in uppers.items():
        for w in ws:
            if isinstance(w, str):
                arriving.setdefault(w, []).append(u)
    col = {}
    for w, us in arriving.items():
        us.sort(key=tops.__getitem__)
        for u, p in zip(us, _in_ports(ax, w, [tops[u] for u in us], inset)):
            col[(u, w)] = p
    out = []
    for u in sorted(uppers, key=tops.__getitem__):
        bottoms = [(w, col[(u, w)] if isinstance(w, str) else _top(ax, w)) for w in uppers[u]]
        bottoms.sort(key=lambda b: b[1])
        out.append((u, tops[u], tuple(bottoms)))
    return out


def _constraints(tk: list) -> dict:
    """Step 3: {(P, N): column} over the nets taking a track (indices into tk)."""
    by_col, by_bottom = {}, {}
    for j, (_, _, bottoms) in enumerate(tk):
        for b in {c for _, c in bottoms}:
            by_col.setdefault(b, []).append(j)
        if len(bottoms) == 1:
            by_bottom.setdefault(bottoms[0], []).append(j)
    out = {}
    for i, (_, top, bottoms) in enumerate(tk):
        for j in by_col.get(top, ()):
            if j != i:
                out[(i, j)] = top
        if len(bottoms) >= 2:
            for b in bottoms:
                for j in by_bottom.get(b, ()):
                    if j != i and (i, j) not in out:
                        out[(i, j)] = b[1]
    return out


def _pack(cn: list) -> tuple:
    """Step 4: ({source: track}, violated constraints (P, N, column) as sources)."""
    tk = [n for n in cn if any(c != n[1] for _, c in n[2])]
    spans = []
    for _, top, bottoms in tk:
        cols = [top] + [c for _, c in bottoms]
        spans.append((min(cols), max(cols)))
    cons = _constraints(tk)
    preds = [set() for _ in tk]
    for i, j in cons:
        preds[j].add(i)
    scan = sorted(range(len(tk)), key=lambda i: (spans[i][0], spans[i][1], tk[i][1]))
    placed, t, left = {}, 0, list(scan)
    while left:
        on = []
        rest = []
        for j in left:
            lj, rj = spans[j]
            if all(placed.get(p, t) < t for p in preds[j]) and all(
                    lj >= spans[m][1] + 2 or rj <= spans[m][0] - 2 for m in on):
                placed[j] = t
                on.append(j)
            else:
                rest.append(j)
        left = rest
        if on:
            t += 1
            continue
        for j in left:
            if _on_cycle(j, preds, placed):
                preds[j] = {p for p in preds[j] if p in placed}
                break
    bad = [(tk[i][0], tk[j][0], col) for (i, j), col in cons.items() if placed[i] >= placed[j]]
    return {tk[j][0]: placed[j] for j in placed}, bad


def _on_cycle(s: int, preds: list, placed: dict) -> bool:
    """Following s's constraints to unplaced nets leads back to s."""
    seen, stack = set(), [s]
    while stack:
        for p in preds[stack.pop()]:
            if p == s:
                return True
            if p not in placed and p not in seen:
                seen.add(p)
                stack.append(p)
    return False


# --- step 5 ---------------------------------------------------------------------------

def _restack(coords: Coords, tracks: tuple) -> Coords:
    """Step 5: channels made as tall as their tracks need; vertices moved along."""
    old = coords.layer_at
    if not old:
        return Coords(coords.order, coords.direction, dict(coords.rects), old,
                      coords.layer_size, 0, 0)
    at = [old[0]]
    for r in range(len(old) - 1):
        g = old[r + 1] - old[r] - coords.layer_size[r]
        size = max(g, tracks[r] + 1) if tracks[r] > 0 else g
        at.append(at[r] + coords.layer_size[r] + size)
    layer_of = _layer_of(coords)
    down = coords.direction == "down"
    rects = {}
    for v, rect in coords.rects.items():
        d = at[layer_of[v]] - old[layer_of[v]]
        rects[v] = rect if d == 0 else (rect.moved(0, d) if down else rect.moved(d, 0))
    width = max((rect.right for rect in rects.values()), default=0)
    height = max((rect.bottom for rect in rects.values()), default=0)
    return Coords(coords.order, coords.direction, rects, tuple(at), coords.layer_size,
                  width, height)


# --- step 6 and the folded rewiring ---------------------------------------------------

class _Plain:
    """No folding: nothing moves, no boundary."""

    last: dict = {}

    def moved(self, r: int, p: int, q: int) -> tuple:
        return p, q


class _Folded:
    """A {Bands}' moves, margin M, exit base E and boundary pairs."""

    def __init__(self, coords: Coords, ax: _Axes, bands: Bands, net: dict) -> None:
        bs = bands.bands
        self.ax = ax
        self.dA = [b.dx if ax.down else b.dy for b in bs]
        self.dL = [b.dy if ax.down else b.dx for b in bs]
        self.band_of = {r: k for k, b in enumerate(bs) for r in range(b.first, b.last + 1)}
        self.last = {b.last: k for k, b in enumerate(bs) if k + 1 < len(bs)}
        self.track_at = []
        pairs = [set() for _ in bs]
        layer_of = _layer_of(coords)
        for u, w in coords.order.ranks.segments():
            r = layer_of[u]
            k = self.last.get(r)
            if k is not None:
                n = net[(r, u)]
                pairs[k].add((n.top + self.dA[k], dict(n.bottoms)[w] + self.dA[k + 1]))
        self.pairs = [{pair: j for j, pair in enumerate(sorted(s, key=lambda x: (-x[0], -x[1])))}
                      for s in pairs]
        most = max((len(s) for s in pairs), default=0)
        self.M = most + 1 if most else 0
        for k, b in enumerate(bs[:-1]):
            b1 = bs[k + 1]
            gap = b1.at - b.at - b.size - len(b.crossing)
            self.track_at.append(b.at + b.size + (gap + 1) // 2)
        self.E = max((sum(ax.along(rect)) + self.M for rect in bands.rects.values()), default=0)

    def moved(self, r: int, p: int, q: int) -> tuple:
        k = self.band_of[r]
        return p + self.dA[k], q + self.dL[k] + self.M

    def rect(self, rect: Rect) -> Rect:
        return rect.moved(0, self.M) if self.ax.down else rect.moved(self.M, 0)

    def boundary(self, r: int, top: int, b: int) -> list:
        k = self.last[r]
        s, g = top + self.dA[k], b + self.dA[k + 1]
        j = self.pairs[k][(s, g)]
        T, X = self.track_at[k] + j, self.E + 1 + j
        return [(s, X), (T, X), (T, j), (g, j)]


def _wires(coords: Coords, ax: _Axes, net: dict, fb: object) -> list:
    """Step 6: each edge's points as cells, canonical (folded: moved and rewired)."""
    layer_of = _layer_of(coords)
    out = []
    for chain in coords.order.ranks.chains:
        v0, vm = chain[0], chain[-1]
        q, s = ax.along(coords.rects[v0])
        r0 = layer_of[v0]
        pts = [fb.moved(r0, _top(ax, v0), q + s - 1)]
        b = None
        for u, w in zip(chain, chain[1:]):
            r = layer_of[u]
            n = net[(r, u)]
            b = _bottom(n, w)
            if r in fb.last:
                pts += fb.boundary(r, n.top, b)
            elif n.top != b:
                row = ax.track(r, n.track)
                pts += [fb.moved(r, n.top, row), fb.moved(r, b, row)]
        pts.append(fb.moved(layer_of[vm], b, ax.along(coords.rects[vm])[0]))
        out.append(tuple(ax.cell(p, q) for p, q in _canonical(pts)))
    return out


def _bottom(n: Net, w: object) -> int:
    for lower, col in n.bottoms:
        if lower == w:
            return col
    raise GraphError(f"no bottom for {w!r} in {n!r}")


def _canonical(points: list) -> list:
    """Step 6: equal neighbours and in-line middle points dropped until neither applies."""
    pts = list(points)
    changed = True
    while changed:
        changed = False
        out = []
        for p in pts:
            if out and out[-1] == p:
                changed = True
                continue
            out.append(p)
        pts = out
        for i in range(1, len(pts) - 1):
            a, b, d = pts[i - 1], pts[i], pts[i + 1]
            if a[0] == b[0] == d[0] or a[1] == b[1] == d[1]:
                del pts[i]
                changed = True
                break
    return pts
