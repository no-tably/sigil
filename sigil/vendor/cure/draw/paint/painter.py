"""[Painter]: parents fill their rect before the children.

theme scope, alignment zone, surface level: pushed and restored at one recursion point.

Kind: service (pure functions and two frozen dataclasses). Painter provides `paint`
(`[Frame] -> [Painter] : paint({Rects}) => {Grid}`): it paints a laid-out tree, node by
node in Layout's pre-order (a parent before its children), through Widgets' `paint`
(`[Painter] -> [Widgets] : paint({Rect}) => {Cells}`), into grids, one per layer; it
writes the hit map as each node paints, in screen space, and hands back the layers for
[Frame] to compose. It also gives every node its {Context} (`contexts`, through Theme's
`enter`: `[Painter] -> [Theme] : enter({Node}) => {Context}`) and draws a split tree's
chrome (`tiles`: gutters and tab / title bars, with Buffer's `put` / `fill`:
`[Painter] -> [Buffer] : put({Spans}) => {Grid}`).

The one recursion point (`contexts`). Every node's own context is derived from the
context its parent hands down, in one place and in this order, for a node `N` at path
`p` handed the context `P` (the root is handed the app's `ctx`):
1. `own = enter(N, P)` (Theme's: `N.scope`'s theme / charset swaps, then one more
   surface level when `N.surface`; `P` itself when neither). The level is the real
   tree depth counted from the app's base level (README decision 6; Ramp's from_tree),
   clamped by the theme when a ground is read, never here.
2. `contexts[p] = own`: what `N` measures and paints with.
3. The context handed down, `down`, starts as `own`. Lift: when `N` has a callable
   `lifts` and `N.lifts(own)` is true (the node is the focus pane), `down =
   replace(down, lift=True)` (`dataclasses.replace`; skipped when `own.lift` is already
   true). The node itself is not lifted by this (a lifting Block raises its own ground
   through `ground(focused=...)`); its whole subtree is, since `lift` is inherited.
4. Zone: with `K` the children of `N` (`getattr(N, "children", ())`, in order) that have
   a callable `zone` (a PropertyList: `zone(ctx) -> int`, its key zone, at least
   `ctx.zone`), when `K` is not empty: `Z = max(k.zone(enter(k, down)) for k in K)` and
   `down = replace(down, zone=Z)` (skipped when `down.zone == Z`). So sibling lists
   line up at one separator column, and a zone pushed further up is never narrowed
   (each `zone` is at least `down.zone`). With `K` empty, `down.zone` passes through
   unchanged (an enclosing node's zone reaches nested lists and labelled controls).
5. Each child `i` is handled the same way at `p + (i,)`, handed `down`.
Restored: contexts are values, never changed in place, so each sibling is handed the
same `down`, and nothing a subtree derives reaches its siblings or its parent. Nothing
else in Paint derives a context: `paint` reads `contexts[path]` only.

Layers (`paint`). A tree paints on its base layer `z` (the root and its flow
descendants). A node that is not the root and has a `layer` attribute that is not
`None` (an Overlay: `layer` an int >= 1) opens a layer of its own: it and its subtree
paint on layer `z + node.layer` into a scratch grid of their own, which [Frame]
composes over what is beneath it by z with the node's `backdrop`
(`getattr(node, "backdrop", "none")`: Buffer's `"none"`, `"dim"` or `"opaque"`). Its
footprint is the node's clip (its rect cut by the root rect, as Layout clips a
floating child): only those cells of its grid are composed. Any other node paints on
the layer of its nearest ancestor that opened one (or the base): a floating node that
is not an Overlay (a Paragraph with an `anchor`) paints into its parent's layer and is
cut to that layer's footprint.

`paint(rects, contexts, size, *, z=0, area=None, backdrop="none", outside=False) ->
Painted`, with `w, h = size` and `area` defaulting to `Rect(0, 0, w, h)`. Every grid
`paint` makes has an origin `(ox, oy)`: the screen cell its cell `(0, 0)` stands for. A
node paints into its grid in that grid's coordinates (its rect and clip moved by
`(-ox, -oy)`, Widgets' `moved` law), and its hits come back moved by `(ox, oy)`, in
screen space:
1. `root = rects[()]`, `o = root.clip`; when `o` lies inside `Rect(0, 0, w, h)`
   (always, through [Frame]), the base scratch `S = Grid(o.w, o.h)` (blank) with
   origin `(o.x, o.y)`: the tree's base layer is painted only within the root's clip
   (a pane's rect in a `Tiled` frame), never as a frame-sized grid; otherwise (a direct
   call with a root clip past the frame) `S = Grid(w, h)` with origin `(0, 0)`, as
   before F1. `hits = HitMap()`.
2. When `outside` and the root's widget node has an `id` that is not `None`:
   `hits = hits.add(area, (id, "outside"), z)` (a modal screen's capture: a click
   anywhere off it lands on it; recorded before any other hit of the tree).
3. For each entry `e` of `rects` in order (pre-order: parents first), `n =
   e.node.node` (the widget node; `e.node` is the `Adapted`) and `c =
   contexts[e.path]`:
   a. Its layer and grid: when `n` opens a layer (above), a new blank `Grid(w, h)`
      with origin `(0, 0)` on layer `L = z + n.layer` (frame-sized: a floating
      descendant that is not an Overlay may paint past the overlay's footprint, and is
      cut to it in step 4); else its parent's (`e.path[:-1]`) layer and grid. Below,
      `(ox, oy)` is that grid's origin and `m(r) = r.moved(-ox, -oy)`.
   b. When `n` opens a layer, `getattr(n, "modal", False)` is true and its `id` is
      not `None`: `hits = hits.add(area, (n.id, "outside"), L)` (before its own hits).
   c. `for hit in widgets.paint(n, m(e.rect), c, grid, m(e.clip)): hits =
      hits.add(hit.rect.moved(ox, oy), hit.tag, L)` (a widget's hits are on layer 0 in
      its grid's coordinates; they move to screen space and to `L`).
      The node fills its whole clip (the Widgets recipe), so a parent's cells are
      under its children's and each child paints over its parent's ground.
   d. When `e.regions` is not `None` (a Scaffold node) and `e.regions.more.h == 1`:
      `widgets.paint(More(below=r.below + r.footer_cut, above=r.above +
      r.header_cut), m(r.more), c, grid, m(r.more.intersect(e.clip)))` with `r =
      e.regions` (the `↓N more` row: overflow is never silent; a cut pin's rows count
      as hidden on its side). `More` has no `id`: it records no hit.
   e. When `n` has a callable `cursor_at`: `at = n.cursor_at(e.rect, c, e.clip)`
      (screen space, not moved); a non-`None` `at` becomes the cursor (the last one in
      this order wins).
   f. When `getattr(n, "id", None)` is not `None`: `Place(n.id, e.rect, e.clip, L)`
      is appended to the places.
4. The layers: first `Layer(S, o.x, o.y, z, backdrop)` when `S` is rect-sized, else
   `Layer(clip(S, o), o.x, o.y, z, backdrop)` (Buffer's `clip` and `Layer`: the base
   footprint is the root's clip either way), then, for each node that opened a layer,
   in the order they were opened, `Layer(clip(G, e.clip), e.clip.x, e.clip.y, z +
   n.layer, n.backdrop)` with `G` its grid.
Result: `Painted(layers, hits, cursor, places)`.

Law rect_painted: `paint` gives a `Painted` `==` to the frame-sized construction it
replaces (as of commit 26d0853: `S = Grid(w, h)` with origin `(0, 0)`, every node
painted at its own rect and clip, and the base layer `Layer(clip(S, o), o.x, o.y, z,
backdrop)`): the same layers (grids `==`, the same `x`, `y`, `z`, backdrop, in the same
order), the same hits in the same order, the same cursor and places. It holds for every
tree of nodes that keep Widgets' `contained`, `owned` and `moved` laws (every widget
family does): every clip on the base layer lies inside `o` (Layout clips each node, a
floating one by the root rect), so the frame-sized `S` is blank outside `o` and its
`clip` drops those cells, and a wide pair cut at the edge of the rect-sized `S` is the
`blank` Buffer's `clip` leaves (no_orphan_half (2)). Errors are the same class; their
messages are the same except a widget's own message quoting the rect or clip it was
given (a clip outside its rect), which Layout's clips never raise. A proof compares
`paint` with a copy of the 26d0853 `paint` over random trees (`tests/paint`'s
generators), rects inside and partly outside the frame, overlays and floating children
included, and `Tiled` frames over random split trees with floats (see [Frame]).

Speed: a tree's base layer costs its root clip's cells, not the frame's: in a `Tiled`
frame with `n` panes the panes' trees together paint, cut and compose about one frame
of cells, not `n` (the budget B4 of [Frame]).

Split chrome (`tiles(tiling, tree, ctx, size, *, titles=None) -> Painted`), for
Layout's `Tiling` of `tree` (a `SplitTree`) in `Rect(0, 0, w, h)`, everything with
`ctx` (the app's root context; nothing here is entered), `g = ctx.ground()`:
- Groups: the tiled group (layer 0) holds the gutters and bars whose `path` does not
  start with `"float"`; float `j`'s group (layer `j + 1`) those whose path starts
  `("float", j)`. A group's grid is a blank `Grid(w, h)`; the tiled group's footprint
  is the whole area, float `j`'s the bounding box of its panes', gutters' and bars'
  rects (the clamped float rect: Splits tiles it exactly). Each footprint is first
  filled with `Cell(" ", 1, g.style)`.
- A gutter `G` (a `Gutter(path, index, axis, rect)`) is a RUN (R3b, refine round 7;
  Context's run op, R3a: `[Painter]`'s gutters are among the repeated runs that ask
  `ctx.run`, never `glyph * n`), with `t` the glyph it draws today,
  `ctx.glyph("border.light.v")` for `axis == "x"` (a vertical strip between
  side-by-side panes) or `ctx.glyph("border.light.h")` for `"y"` (a horizontal one
  between stacked panes):
  - `"x"`: `cells = ctx.run("frame.gutter.x", G.rect.h, t, style=ctx.border(False))`
    (a vertical run of the gutter's height: every `frame.gutter.x` cluster is one
    cell, checked at load); every column of `G.rect` takes it, cell `i` at row
    `G.rect.y + i`;
  - `"y"`: `cells = ctx.run("frame.gutter.y", G.rect.w, t, style=ctx.border(False))`
    (a horizontal run of the gutter's width; it may hold wide clusters, `""` the tail
    cell of the pair before it, Buffer's cell model); every row of `G.rect` takes it,
    cell `i` at column `G.rect.x + i`;
  (`weight` None: a gutter has no weight, `frame.gutter.<weight>...` is no run;
  `focused` False: a gutter has no focus state.) Each cell is its run glyph in its
  run style (`ctx.border(False)`, today's, or a part's role style), then
  `shade(grid, G.rect, bg=g.style.bg)`: the same cells as a fill of `G.rect` with
  those cells and a shade of it (no pair half inside the rect: a horizontal run is
  exactly `G.rect.w` cells, so its pairs lie inside). With no `frame.gutter.<axis>`
  pattern in `ctx.charset` (and under the ascii base, a non-ASCII one is already
  dropped at load), every cell is `Cell(t, 1, ctx.border(False))` shaded: today's
  gutter, cell for cell (base_unchanged). Hit `Hit(G.rect, ("gutter", G.path,
  G.index), layer)` when `G.rect` is not empty, whatever the pattern.
- A bar `B` (a `Bar(path, kind, index, rect, active)`), with `node =
  splits.node_at(tree, B.path)` and `label(child) = titles.get(i, i)` where `i` is the
  first pane id under `child` in pre-order (the child itself when it is a `Pane`):
  - kind `"tabs"`: Widgets' `Tabs(tuple(Tab(label(ch)) for ch in node.children),
    active=node.active, id=("tabs", B.path))` painted at `B.rect` (clip `B.rect`):
    its strip on the bar's first row; hits `("tabs", path)` and `(("tabs", path),
    "tab", i)` per whole segment, as the Tabs widget records them.
  - kind `"title"`: Widgets' `Disclosure(label(node.children[B.index]),
    open=B.active, id=("title", B.path, B.index))` painted at `B.rect`: `▾` before
    the active child's title, `▸` before the others'; hit `("title", path, index)`.
  Each widget hit is added on the group's layer, in order.
- Order: the tiled group's gutters (Tiling order), then its bars, then float by float
  its gutters and bars. Result: `Painted(layers, hits, None, ())` with `layers` the
  tiled group's `Layer(S0, 0, 0, 0)` and then, per float `j` with any rect,
  `Layer(clip(Sj, Fj), Fj.x, Fj.y, j + 1)` (`Fj` its footprint).
The panes themselves (their `("pane", id)` hits and their trees) are [Frame]'s.

Data (frozen dataclasses):
- `Place(id, rect, clip, layer)`: where a node with an `id` was painted: its rect and
  clip (screen space, Geometry {Rect}s) and its layer. The app reads these to keep its
  own values in step for the next frame (a Viewport's `sized` view, a dropdown's
  `attach` target): Paint never scrolls anything itself.
- `Painted(layers, hits, cursor, places)`: a tuple of Buffer `Layer`; a Geometry
  {HitMap}; `(x, y)` or `None`; a tuple of `Place`.

Constants:
- `LAYERS = 1000`: the layers one screen may use (`z .. z + LAYERS - 1`); an overlay's
  `layer` must be below it ([Frame] stacks screens `LAYERS` apart).

Laws (each a property a test can loop over trees, sizes and contexts):
- one point: `contexts` calls Theme's `enter` exactly once per node occurrence for its
  own context (plus once per zone-bearing child for its zone), and every entry it
  returns is reached from the app's `ctx` only by `enter` and the two `replace`s above.
- level from depth: with no scopes and `lift` off, `contexts(t, ctx)[p].level ==
  ctx.level + (the number of surface nodes on the path from the root to p, p
  included)`.
- restored: siblings are handed the same context: for children `a`, `b` of one node,
  `contexts[pa]` and `contexts[pb]` differ only by what `a` and `b` themselves enter.
- parents first: a node's cells are written before its children's, so a child's cells
  win inside the child's clip and the parent's show elsewhere in its own clip.
- contained: `paint` changes no grid it is given (it makes its own); every hit's rect
  lies inside `area`.
- rect painted: as law rect_painted above (the same `Painted` as the frame-sized base).
- gutters base_unchanged (R3b, 73c003c): with no `frame.gutter.x` / `frame.gutter.y`
  pattern in `ctx.charset`, `tiles(...)` gives exactly commit 73c003c's `Painted`
  (layers cell for cell, hits) for the same tiling, tree, context, size and titles
  (that commit's code loaded through `tests/_gitref.py` at test time, skipped without
  git history); and with one, every gutter cell is its run's cell (glyph, style, the
  ground's bg where it has none), the bars, footprints and hits unchanged.
- pure: the same rects, contexts and size give equal `Painted` values.

Inputs: `node` / `root` a widget tree; `ctx` a {Context} (any dataclass instance with
  Draw's Context fields); `rects` Layout's {Rects} of an `adapt`ed tree; `contexts` a
  mapping from paths to contexts; `size` a pair of ints `>= 0`; `z` an int; `area` a
  {Rect} or `None`; `backdrop` one of Buffer's `BACKDROPS`; `outside` a bool;
  `tiling` a Layout `Tiling`; `tree` a `SplitTree`; `titles` a mapping from pane ids
  to styled text (`str` or a Text {Line}), or `None`.
Outputs: a `dict` from paths to contexts; a `Painted`.
Errors: `contexts`: what Theme's `enter`, `lifts`, `zone` and `dataclasses.replace`
  raise (a `TypeError` when `ctx` is not a dataclass instance, a `ValueError` from
  Context's checks); `ValueError` "a node is its own ancestor at path <path>" for a
  cycle. `paint`: `TypeError` when `size` is not a pair of ints (a `bool` included),
  `z` is not an int, a node's `layer` is not an int, or as Widgets' `paint` (a node
  lacking the protocol, a bad rect); `ValueError` when a size is negative, a node's
  `layer` is `< 1` or `>= LAYERS`, or its `backdrop` is not one of Buffer's;
  `KeyError` when `contexts` lacks a path of `rects`. `tiles`: as `paint` for `size`;
  `KeyError` when a bar's path names no node of `tree`.
Effects: none (the grids it writes are its own new ones).

Usage:
    from cure.core.buffer import text
    from cure.core.geometry import Rect
    from cure.draw.context import Context
    from cure.draw.layout import lay
    from cure.draw.theme import builtin
    from cure.draw.widgets import Block, Item, PropertyList
    from cure.draw.paint.measure import Measure, adapt
    from cure.draw.paint.painter import Place, contexts, paint
    tree = Block((PropertyList((Item("name", "cure"),)),
                  PropertyList((Item("identifier", "42"),))), id="b")
    cx = contexts(tree, Context.of(builtin(), focus="b"))
    cx[()].level, cx[(0,)].level, cx[(0,)].lift   # 1, 1, True: a surface; the focus pane
    cx[(0,)].zone, cx[(1,)].zone                  # 11, 11: 1 + width("identifier")
    a = adapt(tree)
    out = paint(lay(a, Rect(0, 0, 30, 4), Measure(cx)), cx, (30, 4))
    [h.tag for h in out.hits.hits]                # ["b"]
    out.layers[0].z, out.cursor                   # 0, None
    out.places == (Place("b", Rect(0, 0, 30, 4), Rect(0, 0, 30, 4), 0),)   # True
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace

from cure.core.buffer import BACKDROPS, Cell, Grid, Layer, clip, fill, shade, write
from cure.core.geometry import Hit, HitMap, Rect
from cure.core.text import width
from cure.draw import widgets
from cure.draw.layout import splits
from cure.draw.theme import enter
from cure.draw.widgets import Disclosure, More, Tab, Tabs

LAYERS = 1000
"""The layers one screen may use; an overlay's `layer` must be below it."""


@dataclass(frozen=True)
class Place:
    """Where a node with an `id` was painted: rect, clip (screen space) and layer."""

    id: object
    rect: object
    clip: object
    layer: int = 0


@dataclass(frozen=True)
class Painted:
    """A painted tree: its layers to compose, its hits, its cursor, its places."""

    layers: tuple = ()
    hits: object = None
    cursor: "tuple[int, int] | None" = None
    places: tuple = ()


def contexts(root: object, ctx: object) -> dict:
    """Every node's own context by path, from `ctx`, at the one recursion point (see the module)."""
    out: dict = {}
    _derive(root, (), ctx, out, frozenset())
    return out


def _derive(node: object, path: tuple, handed: object, out: dict, ancestors: frozenset) -> None:
    """Steps 1-5 of the one recursion point for `node` at `path`, then its children."""
    if id(node) in ancestors:
        raise ValueError(f"a node is its own ancestor at path {path}")
    own = enter(node, handed)
    out[path] = own
    down = own
    lifts = getattr(node, "lifts", None)
    if callable(lifts) and not own.lift and lifts(own):
        down = replace(down, lift=True)
    kids = tuple(getattr(node, "children", ()))
    zoned = [k for k in kids if callable(getattr(k, "zone", None))]
    if zoned:
        zone = max(k.zone(enter(k, down)) for k in zoned)
        if down.zone != zone:
            down = replace(down, zone=zone)
    inside = ancestors | {id(node)}
    for i, kid in enumerate(kids):
        _derive(kid, path + (i,), down, out, inside)


def paint(rects: object, contexts: Mapping, size: "tuple[int, int]", *, z: int = 0,
          area: object = None, backdrop: str = "none", outside: bool = False) -> Painted:
    """Paint a laid-out tree, parents first, into its layers; its hits in screen space (see the module)."""
    w, h = _pair(size)
    _int(z, "z")
    if area is None:
        area = Rect(0, 0, w, h)
    root = rects[()]
    hits: list = []
    if outside and getattr(root.node.node, "id", None) is not None:
        hits.append(Hit(area, (root.node.node.id, "outside"), z))
    # Step 1: the base grid is the root's clip, with that clip's corner as its origin,
    # when the clip lies inside the frame; else frame-sized at (0, 0), as before F1.
    o = root.clip
    rect_sized = o.x >= 0 and o.y >= 0 and o.x + o.w <= w and o.y + o.h <= h
    if rect_sized:
        base, bx, by = Grid(o.w, o.h), o.x, o.y
    else:
        base, bx, by = Grid(w, h), 0, 0
    on: dict = {}                    # path -> (layer, grid, ox, oy)
    opened: list = []                # (entry, node, layer, grid), in opening order
    cursor = None
    places: list = []
    for e in rects:
        n = e.node.node
        c = contexts[e.path]
        layer = getattr(n, "layer", None) if e.path else None
        if layer is not None:
            L = z + _layer(layer)
            grid, ox, oy = Grid(w, h), 0, 0
            backdrop_n = getattr(n, "backdrop", "none")
            if backdrop_n not in BACKDROPS:
                raise ValueError(f"backdrop must be one of {BACKDROPS}, got {backdrop_n!r}")
            opened.append((e, backdrop_n, L, grid))
            if getattr(n, "modal", False) and getattr(n, "id", None) is not None:
                hits.append(Hit(area, (n.id, "outside"), L))
        elif e.path:
            L, grid, ox, oy = on[e.path[:-1]]
        else:
            L, grid, ox, oy = z, base, bx, by
        on[e.path] = (L, grid, ox, oy)
        if ox or oy:
            # The node paints in its grid's coordinates; its hits come back to the screen's.
            for hit in widgets.paint(n, e.rect.moved(-ox, -oy), c, grid, e.clip.moved(-ox, -oy)):
                hits.append(Hit(hit.rect.moved(ox, oy), hit.tag, L))
        else:
            for hit in widgets.paint(n, e.rect, c, grid, e.clip):
                hits.append(Hit(hit.rect, hit.tag, L))
        r = e.regions
        if r is not None and r.more.h == 1:
            widgets.paint(More(below=r.below + r.footer_cut, above=r.above + r.header_cut),
                          r.more.moved(-ox, -oy), c, grid,
                          r.more.intersect(e.clip).moved(-ox, -oy))
        cursor_at = getattr(n, "cursor_at", None)
        if callable(cursor_at):
            at = cursor_at(e.rect, c, e.clip)
            if at is not None:
                cursor = at
        if getattr(n, "id", None) is not None:
            places.append(Place(n.id, e.rect, e.clip, L))
    # Step 4: a rect-sized base is the layer itself; a frame-sized one is cut to the
    # root's clip.
    if rect_sized:
        layers = [Layer(base, o.x, o.y, z, backdrop)]
    else:
        layers = [Layer(clip(base, o), o.x, o.y, z, backdrop)]
    for e, backdrop_n, L, grid in opened:
        layers.append(Layer(clip(grid, e.clip), e.clip.x, e.clip.y, L, backdrop_n))
    return Painted(tuple(layers), HitMap(tuple(hits)), cursor, tuple(places))


def tiles(tiling: object, tree: object, ctx: object, size: "tuple[int, int]", *,
          titles: "Mapping | None" = None) -> Painted:
    """A split tree's gutters and tab / title bars, on the tiled and the floats' layers (see the module)."""
    w, h = _pair(size)
    g = ctx.ground()
    ground = Cell(" ", 1, g.style)
    titles = {} if titles is None else titles

    def group(path: tuple) -> int:
        return path[1] + 1 if path and path[0] == "float" else 0

    rects: dict = {}                 # group -> the rects in it, for a float's footprint
    for item in (*tiling.panes, *tiling.gutters, *tiling.bars):
        rects.setdefault(group(item.path), []).append(item.rect)
    floats = sorted(j for j in rects if j > 0)
    grids = {0: Grid(w, h)}
    footprints = {0: Rect(0, 0, w, h)}
    for j in floats:
        grids[j] = Grid(w, h)
        footprints[j] = _bounds(rects[j])
    for j, grid in grids.items():
        fill(grid, footprints[j], ground)

    def label(child: object) -> object:
        while not isinstance(child, splits.Pane):
            child = child.children[0]
        return titles.get(child.id, child.id)

    hits: list = []
    shaded: dict = {}                # a run cell -> its cell, filled then shaded
    for j in [0] + floats:
        grid = grids[j]
        for gut in (x for x in tiling.gutters if group(x.path) == j):
            if not gut.rect.empty:
                _gutter(grid, gut, ctx, g.style.bg, shaded)
                hits.append(Hit(gut.rect, ("gutter", gut.path, gut.index), j))
        for bar in (x for x in tiling.bars if group(x.path) == j):
            node = splits.node_at(tree, bar.path)
            if bar.kind == "tabs":
                widget = Tabs(tuple(Tab(label(ch)) for ch in node.children),
                              active=node.active, id=("tabs", bar.path))
            else:
                widget = Disclosure(label(node.children[bar.index]), open=bar.active,
                                    id=("title", bar.path, bar.index))
            for hit in widgets.paint(widget, bar.rect, ctx, grid, bar.rect):
                hits.append(Hit(hit.rect, hit.tag, j))
    layers = [Layer(grids[0], 0, 0, 0)]
    for j in floats:
        f = footprints[j]
        layers.append(Layer(clip(grids[j], f), f.x, f.y, j))
    return Painted(tuple(layers), HitMap(tuple(hits)), None, ())


def _gutter(grid: Grid, gut: object, ctx: object, bg: object, shaded: dict) -> None:
    """A gutter's run across its rect, then shaded (see the module's gutter)."""
    R = gut.rect
    x_axis = gut.axis == "x"
    t = ctx.glyph("border.light.v" if x_axis else "border.light.h")
    cells = ctx.run("frame.gutter.x" if x_axis else "frame.gutter.y", R.h if x_axis else R.w,
                    t, style=ctx.border(False))
    if cells.count(cells[0]) == len(cells) and width(cells[0][0]) == 1:
        # One cell all along (today's gutter, or a one-glyph pattern): shaded once, then
        # filled, the same cells as a fill of the rect and a shade of it.
        if cells[0] not in shaded:
            shaded[cells[0]] = shade(Grid(1, 1, Cell(cells[0][0], 1, cells[0][1])),
                                     bg=bg).get(0, 0)
        fill(grid, R, shaded[cells[0]])
        return
    if x_axis:                       # cell i fills row R.y + i (every cluster one cell)
        for i, (glyph, style) in enumerate(cells):
            fill(grid, Rect(R.x, R.y + i, R.w, 1), Cell(glyph, 1, style))
    else:                            # every row the run, a "" the tail of the pair before
        row = [Cell(glyph, width(glyph), style) if glyph else Cell("", 0, style)
               for glyph, style in cells]
        for y in range(R.y, R.bottom):
            write(grid, R.x, y, row)
    shade(grid, R, bg=bg)


def _bounds(rects: list) -> Rect:
    """The bounding box of the non-empty `rects` (an empty rect when there is none)."""
    full = [r for r in rects if not r.empty]
    if not full:
        return Rect(0, 0, 0, 0)
    x, y = min(r.x for r in full), min(r.y for r in full)
    return Rect(x, y, max(r.right for r in full) - x, max(r.bottom for r in full) - y)


def _layer(layer: object) -> int:
    """An overlay's `layer`, checked: an int in `1 .. LAYERS - 1`."""
    _int(layer, "layer")
    if not 1 <= layer < LAYERS:
        raise ValueError(f"layer must be in 1 .. {LAYERS - 1}, got {layer}")
    return layer


def _pair(size: object) -> "tuple[int, int]":
    """`size` as `(w, h)`: a pair of ints >= 0 (TypeError, ValueError otherwise)."""
    try:
        w, h = size
    except (TypeError, ValueError):
        raise TypeError(f"size must be a pair of ints, got {size!r}") from None
    _int(w, "w")
    _int(h, "h")
    if w < 0 or h < 0:
        raise ValueError(f"size must be >= 0, got {(w, h)}")
    return w, h


def _int(value: object, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
