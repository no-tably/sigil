"""[Splits]: splits with weights and min sizes, tabs, stacks, floating, zoom; gutters to drag.

Kind: service (pure functions over a plain-data tree; every node, the tree and the
results are frozen dataclasses, checked on construction). Splits provides `panes` on
top of [Solver]: a split's sizes are one `solve` call. The tree is data: sent, saved
and restored (`to_data` / `from_data`), and every edit is a pure function returning a
new tree. Splits knows nothing of what a pane shows: a pane is an id the app owns
(construct: a builder's terminal; sigil: a drawing).

`panes` is a separate call, not a node kind `lay` reads: the app (or Paint) calls
`panes(tree, area)` first, then lays each visible pane's own widget tree in its rect
with `lay(node, pane.rect, measure)`. `lay`'s contract is unchanged.

The tree (all frozen; a `list` given for a tuple field is stored as a tuple):
- `Pane(id)`: a leaf, `id` a non-empty `str`. Ids are unique in a tree.
- `Split(axis, children, weights=(), mins=())`: `axis` "x" (children side by side,
  left to right) or "y" (stacked, top to bottom); `children` a tuple of 2 or more
  nodes; `weights` ints >= 1 and `mins` ints >= 0, one per child, each a child's
  share and its least size along `axis` in cells. `weights=()` is stored as
  `(1,) * n` and `mins=()` as `(0,) * n` (so equality and `to_data` see the explicit
  tuples); any other length than `n` is a `ValueError`.
- `Tabs(children, active=0, bar=1)`: one child shown at a time under a tab bar of
  `bar` rows (an int >= 0; the bar's labels are the Tabs widget's); `children` a
  tuple of 1 or more nodes; `0 <= active < len(children)`.
- `Stacked(children, active=0)`: zellij's stacked panes: every child keeps a one-row
  title bar, the active one is expanded under its own title; 1 or more children,
  `0 <= active < len(children)`.
- `Float(node, rect)`: a node floating above the tiled layer at `rect`, a {Rect}
  relative to the area's top-left cell.
- `SplitTree(root=None, floating=(), zoomed=None)`: `root` a node or `None` (no
  tiled panes: every one was closed); `floating` a tuple of `Float`, in z order
  (the last on top); `zoomed` `None` or the id of a tiled pane (one in `root`).
  Construction checks that every pane id is unique across `root` and `floating`.
`Node` is the tuple `(Pane, Split, Tabs, Stacked)` (for `isinstance`).

Paths. A node is addressed by its path: the tuple of child indices from `root`
(`()` is the root, `(1, 0)` the first child of the root's second child). A node in a
float is addressed by `("float", i) + the child indices inside that float's node`
(`("float", 0)` is the first float's node).

`panes(tree, area) -> Tiling` (the flow's {Rects}). Every node is laid out, hidden
or not, from the root at `area`; for a node at rect `r`:
- `Pane`: gets `r`.
- `Split`: with `L` = `r.w` ("x") or `r.h` ("y"), `n` children, the gutters
  `gaps(n, 1, L)` (one cell between neighbours, fewer when `L < n - 1`) and
  `avail = L - sum(gutters)`. The sizes:
  - when `sum(mins) >= avail` (the mins do not fit, or exactly fit):
    `solve([Min(m) for m in mins], L, gap=1)`: every child shrinks in proportion to
    its min (a child may get fewer cells than its min, or 0). Never an error.
  - else, water-filling: start with every child free; repeat: share
    `avail - (sum of the frozen children's mins)` among the free children by weight
    (exact rationals); freeze, at its min, every free child whose share is below its
    min; until no child is newly frozen. Then the sizes are exactly
    `solve([Fixed(m_i) if i is frozen else Fill(w_i)], L, gap=1)` (largest
    remainder; a free child's exact share is >= its min, so rounding keeps it).
  The children lie in order along `axis` with the gutters between them, each child
  spanning `r`'s full extent on the other axis.
- `Tabs`: the bar is `Rect(r.x, r.y, r.w, b)` with `b = min(bar, r.h)`; the slot
  `Rect(r.x, r.y + b, r.w, r.h - b)`. Every child is laid out in the slot.
- `Stacked`: with `n` children, `k = active` and `s = max(r.h - n, 0)` slot rows:
  child i's title row is `Rect(r.x, r.y + i, r.w, 1)` for `i <= k` and
  `Rect(r.x, r.y + i + s, r.w, 1)` for `i > k`, each `.intersect(r)` (so a row
  outside `r` is empty); the slot is `Rect(r.x, r.y + k + 1, r.w, s)` intersected
  with `r`. Every child is laid out in the slot.
- A `Float(node, rect)`: clamped into `area` as [Anchor]'s attach clamps:
  `w = min(rect.w, area.w)`, `h = min(rect.h, area.h)`,
  `x = max(area.x, min(area.x + rect.x, area.right - w))`, the same on y; its node is
  laid out there.
Visibility: the root, the children of a `Split`, and the active child of a `Tabs` or
`Stacked` are visible when their parent is; the other children of a `Tabs` or
`Stacked` are hidden, with all their descendants (so a hidden pane keeps the rect it
gets when selected: a hidden terminal keeps its size). Every float's node is visible.
Zoom: when `zoomed` names a pane, it is visible with `rect == area`; every other
tiled pane is hidden (its rect as laid out); no tiled gutter or bar is listed; the
floats are unchanged (still visible, above it).

`Tiling(area, panes, gutters, bars)`:
- `panes`: one `PaneRect(id, path, rect, visible, floating)` per pane in the tree:
  the tiled ones in pre-order (children in order), then each float's, float by float
  in z order. `floating` is true for a pane inside a float.
- `gutters`: one `Gutter(path, index, axis, rect)` per gutter of a visible `Split`
  (between its children `index` and `index + 1`; `rect` the one-cell strip, `w` 1
  for "x" and `h` 1 for "y", spanning the split's other extent; it may be empty when
  `L < n - 1`), in pre-order of the splits, then by `index`.
- `bars`: one `Bar(path, kind, index, rect, active)` per bar of a visible `Tabs`
  (`kind` "tabs", `index` its active index, `active` True) or `Stacked` (`kind`
  "title", one per child: `index` the child's index, `active` `index == active`), in
  pre-order of the nodes, then by `index`.
- `tiling[id] -> PaneRect` (`KeyError` when no pane has that id); `iter(tiling)` and
  `len(tiling)` over `panes`; `tiling.visible`: the visible `PaneRect`s, in order;
  `tiling.moved(dx, dy) -> Tiling`: every rect (the area included) moved.
- `tiling.hit(x, y) -> PaneRect | Gutter | Bar | None`: the topmost visible thing
  covering the cell: the floats from the top (last) down, within one its gutters,
  then its bars, then its visible panes; then the tiled gutters, bars, visible
  panes; `None` when nothing covers it. Each list searched in order, the first
  whose rect `contains(x, y)` wins.

Edits (pure: each returns a new `SplitTree`, never changes its argument; the result
is valid, so it constructs). An edit that rewrites a split's weights divides them by
their gcd. A `Split` left with one child is replaced by that child (taking its slot,
weight and min in the parent); a `Tabs` or `Stacked` left with none is removed from
its parent as a closed pane is; a float whose node is removed is removed.
- `split(tree, id, new_id, axis="x", *, after=True)`: a new `Pane(new_id)` next to
  pane `id` (after it: right or below; else before it). When `id`'s parent is a
  `Split` of the same `axis`: the new pane is inserted beside `id` in that split
  with min 0; `id` and the new pane each get `id`'s weight and every other child
  twice its weight (so the two halve `id`'s share), then the gcd rule. Otherwise
  `id`'s place gets `Split(axis, (id, new) or (new, id), (1, 1), (0, 0))`.
- `close(tree, id)`: pane `id` removed. In a `Split` the child, its weight and its
  min go: the siblings absorb its space by weight. In a `Tabs` or `Stacked` with the
  removed index `r` (of `n`): `active - 1` when `r < active`, `min(active, n - 2)`
  when `r == active`, else unchanged. The root pane closed gives `root=None`.
  `zoomed == id` becomes `None`.
- `add(tree, path, node, index=None, *, weight=1, min=0)`: `node` inserted as child
  `index` (`None`: last) of the `Split`, `Tabs` or `Stacked` at `path`; in a `Split`
  with `weight` and `min`; in a `Tabs` or `Stacked` the same child stays active
  (`active + 1` when `index <= active`). `node`'s pane ids must be new.
- `drag(tree, area, path, index, delta)`: gutter `index` of the `Split` at `path`
  moved by `delta` cells (> 0: right / down). With `s` the split's child sizes as
  `panes(tree, area)` lays them out (hidden or not) and each child's floor
  `f_i = max(mins_i, 1)`: `room_i = max(s_i - f_i, 0)`,
  `d = max(-room_index, min(delta, room_(index+1)))`. `d == 0` returns `tree`
  unchanged. Else child `index` gets `s_index + d`, child `index + 1` gets
  `s_(index+1) - d`, the others keep theirs, and the split's weights become
  `max(size, 1)` per child, then the gcd rule; mins are kept. So a drag never pushes
  a child below its min, nor below one cell.
- `resize(tree, area, id, direction, cells)`: pane `id`'s edge on `direction` (one
  of `DIRECTIONS`: "left", "right", "up", "down") moved outward by `cells` (< 0:
  inward), keyboard-style (tmux's resize-pane): from `id` up through its ancestors,
  the first `Split` whose axis is "x" (for left / right) or "y" (up / down) in which
  the branch holding `id`, child `k`, has a sibling on that side; then
  `drag(tree, area, that split's path, k, cells)` for right / down, or
  `drag(..., k - 1, -cells)` for left / up. No such split: `tree` unchanged.
- `swap(tree, a, b)`: the panes `a` and `b` exchange places (each slot keeps its
  weight and min; `zoomed` stays with its id). `a == b`: unchanged.
- `zoom(tree, id)`: `zoomed = id` (a tiled pane). `unzoom(tree)`: `zoomed = None`.
- `select(tree, path, index)`: the `Tabs` or `Stacked` at `path` gets
  `active = index`.
- `reveal(tree, id)`: every `Tabs` and `Stacked` above pane `id` made to show the
  branch holding it (after which `id` is visible, unless another pane is zoomed).
- `add_float(tree, node, rect)`: `Float(node, rect)` added on top (last).
  `move_float(tree, i, rect)`: float `i` given `rect`. `raise_float(tree, i)`: float
  `i` moved to the top (last), the others' order kept.

Queries:
- `neighbour(tree, area, id, direction) -> str | None`: spatial focus. With the
  visible tiled panes of `panes(tree, area)`, `cur` the rect of `id`, the candidates
  are the other visible tiled panes with a non-empty rect wholly beyond `cur`'s edge
  (for "right" `c.x >= cur.right`; "left" `c.right <= cur.x`; "down"
  `c.y >= cur.bottom`; "up" `c.bottom <= cur.y`) and a positive overlap with it on
  the other axis. The pick is the least by `(distance, -overlap, cross start,
  tree order)`: the distance is the gap to `cur`'s edge (`c.x - cur.right` for
  right), the overlap is in cells, the cross start is `c.y` (left / right) or `c.x`
  (up / down). `None` when there is no candidate, `id` is floating or hidden, or the
  tree is zoomed. No wrap-around.
- `ids(tree) -> tuple[str, ...]`: every pane id in `panes`' order.
  `path_of(tree, id) -> tuple`: its path. `node_at(tree, path) -> node`.

Serialisation (JSON-ready: dicts, lists, `str`, `int`, `None` only):
- `to_data(tree) -> dict`: `{"version": VERSION, "root": N or None, "floating":
  [{"node": N, "rect": [x, y, w, h]}, ...], "zoomed": id or None}` with each node N
  `{"kind": "pane", "id": id}`, `{"kind": "split", "axis": a, "children": [N, ...],
  "weights": [...], "mins": [...]}`, `{"kind": "tabs", "children": [...], "active":
  i, "bar": b}` or `{"kind": "stacked", "children": [...], "active": i}`. Every key
  is always present. `VERSION` is 1.
- `from_data(data) -> SplitTree`: the inverse. Strict: `data` and each node must be
  dicts with exactly the keys above (none missing, none extra), `version ==
  VERSION`, a known `kind`, lists (or tuples) where lists are shown, ints that are
  not `bool`; and the tree they make must be valid (unique ids, lengths, ranges).
  Anything else raises `SplitDataError` (a `ValueError`), whose message names the
  offending place as a path of keys and indices (e.g. `root.children[1].weights`).

Laws (each true for every valid input; a test can loop over them):
- tiles: with `root` not `None` and no zoom, the visible tiled panes' rects, the
  gutters' rects and the bars' rects lie inside `area`, are pairwise disjoint, and
  their areas sum to `area.area`.
- Each pane id appears in `panes` exactly once; `ids(tree)` lists them in order.
- mins: when a split's `sum(mins) + n - 1 <= L`, each child gets at least its min.
- weights: with all mins 0, a split's sizes are `solve([Fill(w) ...], L, gap=1)`.
- hidden keeps size: `panes(select(t, p, i), a)[id].rect == panes(t, a)[id].rect`
  for every pane `id` (only `visible` changes), except that under a `Stacked` at `p`
  the slot moves with `active`, so its descendants keep their size (`w`, `h`) and
  their `y` follows the slot; likewise `zoom` changes only the zoomed pane's rect.
- `panes(t, area.moved(dx, dy)) == panes(t, area).moved(dx, dy)`.
- round trip: `from_data(to_data(t)) == t`; `to_data(from_data(d)) == d` for any
  valid `d` written with lists; `json.loads(json.dumps(to_data(t))) == to_data(t)`.
- Every edit's result is a valid `SplitTree` (it constructs, and round-trips).
- drag: when no clamp applied (`d == delta`) and every child had a size >= 1,
  `panes` of the result gives the dragged sizes exactly; dragging back by `-delta`
  restores the sizes.
- `close(split(t, id, new, axis), new) == t` when `id`'s parent is not a `Split`
  of `axis` (the wrapping split collapses back). In a same-axis parent the split
  doubled the other weights, so closing it again leaves `id` half its old share.
- `neighbour` never returns `id`, a hidden pane or a floating one.

Inputs: `tree` a `SplitTree`; `area`, `rect` {Rect}s; `id`, `new_id`, `a`, `b`
  non-empty `str`s; `axis` "x" or "y"; `path` a tuple as above; `index`, `delta`,
  `cells`, `weight`, `min`, `i` ints (never `bool`); `direction` one of
  `DIRECTIONS`; `node` a node; `data` any value.
Outputs: a `Tiling`; a new `SplitTree`; an id or `None`; a dict.
Errors: `TypeError` when an argument or field is of the wrong type (a `bool` for an
  int included; a child that is not a node); `ValueError` when a field is out of
  range (as listed), a `Split` has fewer than 2 children or a `Tabs` / `Stacked`
  none, an id is repeated, `zoomed` names no tiled pane, `new_id` (or an id in
  `node`) is already in the tree, `axis` or `direction` is unknown, the node at
  `path` is not of the kind the edit needs (a `Split` for `drag`; a `Split`, `Tabs`
  or `Stacked` for `add`; a `Tabs` or `Stacked` for `select`), `index` is out of
  range there, `zoom` is given a floating pane, or `weight` < 1 / `min` < 0;
  `KeyError` when an id names no pane, a path no node, or `i` no float;
  `SplitDataError` (a `ValueError`) from `from_data` as above. Assigning a field
  raises `dataclasses.FrozenInstanceError`.
Effects: none.

Usage:
    from cure.core.geometry import Rect
    from cure.draw.layout import splits
    from cure.draw.layout.splits import SplitTree, Pane, Split, Tabs, Stacked, Float, panes
    tree = SplitTree(Split("x", (Pane("a"), Split("y", (Pane("b"), Pane("c"))))))
    area = Rect(0, 0, 81, 24)
    t = panes(tree, area)
    t["a"].rect, t["b"].rect, t["c"].rect
    #   Rect(0, 0, 40, 24), Rect(41, 0, 40, 12), Rect(41, 13, 40, 11)
    [(g.path, g.index, g.rect) for g in t.gutters]
    #   [((), 0, Rect(40, 0, 1, 24)), ((1,), 0, Rect(41, 12, 40, 1))]
    t.hit(40, 5)                                  # Gutter((), 0, "x", Rect(40, 0, 1, 24))
    panes(SplitTree(Split("x", (Pane("a"), Pane("b")), (3, 1), (0, 30))),
          Rect(0, 0, 41, 5))["a"].rect            # Rect(0, 0, 10, 5): b frozen at 30
    panes(SplitTree(Split("x", (Pane("a"), Pane("b")), mins=(15, 15))),
          Rect(0, 0, 21, 5))["b"].rect            # Rect(11, 0, 10, 5): mins shrink
    splits.drag(tree, area, (), 0, 5).root.weights          # (9, 7): sizes 45, 35
    splits.resize(tree, area, "c", "up", 2).root.children[1].weights   # (10, 13)
    splits.split(tree, "a", "d", "x").root
    #   Split("x", (Pane("a"), Pane("d"), Split("y", ...)), (1, 1, 2), (0, 0, 0))
    splits.split(tree, "a", "d", "y").root.children[0]
    #   Split("y", (Pane("a"), Pane("d")), (1, 1), (0, 0))
    splits.close(tree, "b").root                  # Split("x", (Pane("a"), Pane("c")), (1, 1), (0, 0))
    z = panes(splits.zoom(tree, "b"), area)
    z["b"].rect, z["a"].visible, z.gutters        # Rect(0, 0, 81, 24), False, ()
    splits.neighbour(tree, area, "a", "right")    # "b": more overlap than c
    splits.neighbour(tree, area, "b", "down"), splits.neighbour(tree, area, "a", "left")
    #   ("c", None)
    tabs = panes(SplitTree(Tabs((Pane("p"), Pane("q")), active=1)), Rect(0, 0, 20, 10))
    tabs["p"].rect, tabs["p"].visible, tabs.bars[0].rect
    #   Rect(0, 1, 20, 9), False, Rect(0, 0, 20, 1)
    st = panes(SplitTree(Stacked((Pane("p"), Pane("q"), Pane("r")), active=1)),
               Rect(0, 0, 20, 10))
    st["q"].rect, [b.rect.y for b in st.bars]     # Rect(0, 2, 20, 7), [0, 1, 9]
    fl = SplitTree(Pane("a"), floating=(Float(Pane("f"), Rect(60, 20, 30, 10)),))
    panes(fl, area)["f"].rect                     # Rect(51, 14, 30, 10): clamped
    splits.to_data(SplitTree(Pane("a")))
    #   {"version": 1, "root": {"kind": "pane", "id": "a"}, "floating": [], "zoomed": None}
    # a mouse drag: hit the gutter on press, then on each motion
    # drag(tree_at_press, area, g.path, g.index, x - x_at_press)  (no clamp piles up)
"""

import math
from collections.abc import Iterator
from dataclasses import dataclass, replace
from fractions import Fraction
from functools import lru_cache

from cure.core.geometry import Rect

from .solver import Fill, Fixed, Min, gaps, solve

VERSION = 1
AXES = ("x", "y")
DIRECTIONS = ("left", "right", "up", "down")
BAR_KINDS = ("tabs", "title")


class SplitDataError(ValueError):
    """Bad data given to `from_data`; the message names the place (e.g. `root.children[1]`)."""


def _int(value: object, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")


def _at_least(value: object, low: int, name: str) -> None:
    _int(value, name)
    if value < low:
        raise ValueError(f"{name} must be >= {low}, got {value}")


def _tuple(obj: object, name: str) -> tuple:
    """A tuple field: a list or tuple stored as a tuple."""
    value = getattr(obj, name)
    if not isinstance(value, (tuple, list)):
        raise TypeError(f"{name} must be a tuple or list, got {type(value).__name__}")
    value = tuple(value)
    object.__setattr__(obj, name, value)
    return value


def _children(obj: object, least: int) -> tuple:
    kids = _tuple(obj, "children")
    for kid in kids:
        if not isinstance(kid, Node):
            raise TypeError(f"a child must be a Pane, Split, Tabs or Stacked, got {type(kid).__name__}")
    if len(kids) < least:
        raise ValueError(f"{type(obj).__name__} needs at least {least} children, got {len(kids)}")
    return kids


def _active(obj: object, n: int) -> None:
    _int(obj.active, "active")
    if not 0 <= obj.active < n:
        raise ValueError(f"active must be in 0..{n - 1}, got {obj.active}")


def _pane_ids(node: object) -> list:
    if isinstance(node, Pane):
        return [node.id]
    return [i for kid in node.children for i in _pane_ids(kid)]


@dataclass(frozen=True)
class Pane:
    """A leaf: a pane's id (a non-empty str)."""

    id: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, str):
            raise TypeError(f"id must be a str, got {type(self.id).__name__}")
        if not self.id:
            raise ValueError("id must be a non-empty str")


@dataclass(frozen=True)
class Split:
    """Children along `axis` ("x" or "y"), shared by `weights` (>= 1), each at least `mins`."""

    axis: str
    children: tuple
    weights: tuple = ()
    mins: tuple = ()

    def __post_init__(self) -> None:
        if not isinstance(self.axis, str):
            raise TypeError(f"axis must be a str, got {type(self.axis).__name__}")
        if self.axis not in AXES:
            raise ValueError(f"axis must be 'x' or 'y', got {self.axis!r}")
        n = len(_children(self, 2))
        for name, low, default in (("weights", 1, 1), ("mins", 0, 0)):
            values = _tuple(self, name)
            if not values:
                values = (default,) * n
                object.__setattr__(self, name, values)
            if len(values) != n:
                raise ValueError(f"{name} must have {n} items, got {len(values)}")
            for v in values:
                _at_least(v, low, name[:-1])


@dataclass(frozen=True)
class Tabs:
    """One child shown at a time, the `active` one, under a `bar`-row tab bar."""

    children: tuple
    active: int = 0
    bar: int = 1

    def __post_init__(self) -> None:
        _active(self, len(_children(self, 1)))
        _at_least(self.bar, 0, "bar")


@dataclass(frozen=True)
class Stacked:
    """Stacked panes: a title row per child, the `active` one expanded."""

    children: tuple
    active: int = 0

    def __post_init__(self) -> None:
        _active(self, len(_children(self, 1)))


Node = (Pane, Split, Tabs, Stacked)


@dataclass(frozen=True)
class Float:
    """A node floating above the tiled layer at `rect` (relative to the area)."""

    node: object
    rect: Rect

    def __post_init__(self) -> None:
        if not isinstance(self.node, Node):
            raise TypeError(f"node must be a Pane, Split, Tabs or Stacked, got {type(self.node).__name__}")
        if not isinstance(self.rect, Rect):
            raise TypeError(f"rect must be a Rect, got {type(self.rect).__name__}")


@dataclass(frozen=True)
class SplitTree:
    """{SplitTree}: the tiled root (or None), the floats in z order, the zoomed pane id."""

    root: object = None
    floating: tuple = ()
    zoomed: "str | None" = None

    def __post_init__(self) -> None:
        if self.root is not None and not isinstance(self.root, Node):
            raise TypeError(f"root must be a node or None, got {type(self.root).__name__}")
        floats = _tuple(self, "floating")
        for f in floats:
            if not isinstance(f, Float):
                raise TypeError(f"floating must hold Floats, got {type(f).__name__}")
        tiled = [] if self.root is None else _pane_ids(self.root)
        every = tiled + [i for f in floats for i in _pane_ids(f.node)]
        if len(set(every)) != len(every):
            twice = sorted({i for i in every if every.count(i) > 1})
            raise ValueError(f"pane ids must be unique, repeated: {twice}")
        if self.zoomed is not None:
            if not isinstance(self.zoomed, str):
                raise TypeError(f"zoomed must be a str or None, got {type(self.zoomed).__name__}")
            if self.zoomed not in tiled:
                raise ValueError(f"zoomed must name a tiled pane, got {self.zoomed!r}")


@dataclass(frozen=True)
class PaneRect:
    """One pane's place: its id, path, rect, whether it is visible, whether it floats."""

    id: str
    path: tuple
    rect: Rect
    visible: bool = True
    floating: bool = False


@dataclass(frozen=True)
class Gutter:
    """The one-cell strip between children `index` and `index + 1` of the split at `path`."""

    path: tuple
    index: int
    axis: str
    rect: Rect


@dataclass(frozen=True)
class Bar:
    """A tab bar ("tabs") or a stacked child's title row ("title") at `path`."""

    path: tuple
    kind: str
    index: int
    rect: Rect
    active: bool = True


@dataclass(frozen=True)
class Tiling:
    """The {Rects} of `panes`: every pane's PaneRect, the visible gutters and bars."""

    area: Rect
    panes: tuple = ()
    gutters: tuple = ()
    bars: tuple = ()

    def __getitem__(self, id: str) -> PaneRect:
        """The PaneRect of pane `id` (KeyError when none)."""
        for p in self.panes:
            if p.id == id:
                return p
        raise KeyError(id)

    def __len__(self) -> int:
        return len(self.panes)

    def __iter__(self) -> Iterator[PaneRect]:
        return iter(self.panes)

    @property
    def visible(self) -> tuple:
        """The visible PaneRects, in order."""
        return tuple(p for p in self.panes if p.visible)

    def hit(self, x: int, y: int) -> "PaneRect | Gutter | Bar | None":
        """The topmost visible pane, gutter or bar covering cell (x, y), or None."""
        def layer(floating: bool, index: "int | None"):
            def mine(path: tuple) -> bool:
                if not floating:
                    return not path or path[0] != "float"
                return len(path) >= 2 and path[0] == "float" and path[1] == index
            yield from (g for g in self.gutters if mine(g.path))
            yield from (b for b in self.bars if mine(b.path))
            yield from (p for p in self.panes if p.visible and mine(p.path))
        floats = sorted({p.path[1] for p in self.panes if p.floating}, reverse=True)
        for found in [layer(True, i) for i in floats] + [layer(False, None)]:
            for item in found:
                if item.rect.contains(x, y):
                    return item
        return None

    def moved(self, dx: int, dy: int) -> "Tiling":
        """Every rect, the area included, moved by (dx, dy)."""
        return Tiling(self.area.moved(dx, dy),
                      tuple(replace(p, rect=p.rect.moved(dx, dy)) for p in self.panes),
                      tuple(replace(g, rect=g.rect.moved(dx, dy)) for g in self.gutters),
                      tuple(replace(b, rect=b.rect.moved(dx, dy)) for b in self.bars))


def panes(tree: SplitTree, area: Rect) -> Tiling:
    """Every pane's rect and visibility, and the visible gutters and bars, in `area`."""
    _tree(tree)
    _rect(area, "area")
    return _tiling(tree, area)


@lru_cache(maxsize=64)
def _tiling(tree: SplitTree, area: Rect) -> Tiling:
    """`panes`, its arguments checked (memoised: the tree and the result are frozen)."""
    laid = _Laid()
    if tree.root is not None:
        _lay(tree.root, (), area, True, laid)
    tiled = (list(laid.panes), list(laid.gutters), list(laid.bars))
    for i, f in enumerate(tree.floating):
        _lay(f.node, ("float", i), _clamped(f.rect, area), True, laid)
    if tree.zoomed is not None:
        n_panes, n_gutters, n_bars = (len(part) for part in tiled)
        zoomed = [replace(p, rect=area, visible=True) if p.id == tree.zoomed
                  else replace(p, visible=False) for p in laid.panes[:n_panes]]
        laid.panes[:n_panes] = zoomed
        del laid.gutters[:n_gutters]
        del laid.bars[:n_bars]
    return Tiling(area, tuple(laid.panes), tuple(laid.gutters), tuple(laid.bars))


def split(tree: SplitTree, id: str, new_id: str, axis: str = "x", *,
          after: bool = True) -> SplitTree:
    """A new Pane(new_id) beside pane `id` along `axis`, halving its share."""
    _tree(tree)
    _id(id, "id")
    _id(new_id, "new_id")
    _axis(axis)
    path = path_of(tree, id)
    if new_id in ids(tree):
        raise ValueError(f"new_id {new_id!r} is already in the tree")
    new = Pane(new_id)
    parent_path, k = path[:-1], (path[-1] if path else None)
    parent = node_at(tree, parent_path) if _has_parent(path) else None
    if isinstance(parent, Split) and parent.axis == axis:
        at = k + 1 if after else k
        w = parent.weights[k]
        weights = [2 * v for v in parent.weights]
        weights[k] = w
        weights.insert(at, w)
        mins = list(parent.mins)
        mins.insert(at, 0)
        kids = list(parent.children)
        kids.insert(at, new)
        return _set(tree, parent_path, Split(axis, tuple(kids), _reduced(weights), tuple(mins)))
    pair = (Pane(id), new) if after else (new, Pane(id))
    return _set(tree, path, Split(axis, pair, (1, 1), (0, 0)))


def close(tree: SplitTree, id: str) -> SplitTree:
    """Pane `id` removed; its siblings absorb its space by weight."""
    _tree(tree)
    _id(id, "id")
    path = path_of(tree, id)
    zoomed = None if tree.zoomed == id else tree.zoomed
    if path[:1] == ("float",):
        i = path[1]
        node = _removed(tree.floating[i].node, path[2:])
        floats = list(tree.floating)
        if node is None:
            del floats[i]
        else:
            floats[i] = Float(node, floats[i].rect)
        return SplitTree(tree.root, tuple(floats), zoomed)
    return SplitTree(_removed(tree.root, path), tree.floating, zoomed)


def add(tree: SplitTree, path: tuple, node: object, index: "int | None" = None, *,
        weight: int = 1, min: int = 0) -> SplitTree:
    """`node` inserted as child `index` (None: last) of the Split, Tabs or Stacked at `path`."""
    _tree(tree)
    if not isinstance(node, Node):
        raise TypeError(f"node must be a Pane, Split, Tabs or Stacked, got {type(node).__name__}")
    _at_least(weight, 1, "weight")
    _at_least(min, 0, "min")
    if index is not None:
        _int(index, "index")
    parent = node_at(tree, path)
    if not isinstance(parent, (Split, Tabs, Stacked)):
        raise ValueError(f"the node at {path} must be a Split, Tabs or Stacked, got a Pane")
    n = len(parent.children)
    at = n if index is None else index
    if not 0 <= at <= n:
        raise ValueError(f"index must be in 0..{n}, got {index}")
    clash = set(_pane_ids(node)) & set(ids(tree))
    if clash:
        raise ValueError(f"the node's pane ids are already in the tree: {sorted(clash)}")
    kids = parent.children[:at] + (node,) + parent.children[at:]
    if isinstance(parent, Split):
        new = Split(parent.axis, kids, _inserted(parent.weights, at, weight),
                    _inserted(parent.mins, at, min))
    else:
        new = replace(parent, children=kids,
                      active=parent.active + 1 if at <= parent.active else parent.active)
    return _set(tree, path, new)


def drag(tree: SplitTree, area: Rect, path: tuple, index: int, delta: int) -> SplitTree:
    """Gutter `index` of the split at `path` moved `delta` cells, respecting mins; cells → weights."""
    _tree(tree)
    _rect(area, "area")
    _int(index, "index")
    _int(delta, "delta")
    node = node_at(tree, path)
    if not isinstance(node, Split):
        raise ValueError(f"the node at {path} must be a Split, got a {type(node).__name__}")
    if not 0 <= index < len(node.children) - 1:
        raise ValueError(f"index must be in 0..{len(node.children) - 2}, got {index}")
    laid = _Laid()
    if path[:1] == ("float",):
        i = path[1]
        _lay(tree.floating[i].node, ("float", i), _clamped(tree.floating[i].rect, area), True, laid)
    else:
        _lay(tree.root, (), area, True, laid)
    rect = laid.rects[path]
    sizes = list(_sizes(node, rect.w if node.axis == "x" else rect.h))
    room = [max(s - max(m, 1), 0) for s, m in zip(sizes, node.mins)]
    d = max(-room[index], min(delta, room[index + 1]))
    if d == 0:
        return tree
    sizes[index] += d
    sizes[index + 1] -= d
    weights = _reduced([max(s, 1) for s in sizes])
    return _set(tree, path, Split(node.axis, node.children, weights, node.mins))


def resize(tree: SplitTree, area: Rect, id: str, direction: str, cells: int) -> SplitTree:
    """Pane `id`'s edge on `direction` moved outward `cells` cells, by the nearest fitting split."""
    _tree(tree)
    _rect(area, "area")
    _id(id, "id")
    _direction(direction)
    _int(cells, "cells")
    path = path_of(tree, id)
    axis = "x" if direction in ("left", "right") else "y"
    forward = direction in ("right", "down")
    low = 2 if path[:1] == ("float",) else 0
    for cut in range(len(path) - 1, low - 1, -1):
        parent_path, k = path[:cut], path[cut]
        parent = node_at(tree, parent_path)
        if not isinstance(parent, Split) or parent.axis != axis:
            continue
        if forward and k < len(parent.children) - 1:
            return drag(tree, area, parent_path, k, cells)
        if not forward and k > 0:
            return drag(tree, area, parent_path, k - 1, -cells)
    return tree


def swap(tree: SplitTree, a: str, b: str) -> SplitTree:
    """Panes `a` and `b` exchange places."""
    _tree(tree)
    _id(a, "a")
    _id(b, "b")
    path_of(tree, a)
    path_of(tree, b)
    if a == b:
        return tree
    names = {a: b, b: a}
    root = None if tree.root is None else _renamed(tree.root, names)
    floats = tuple(Float(_renamed(f.node, names), f.rect) for f in tree.floating)
    zoomed = tree.zoomed
    if zoomed is not None and (root is None or zoomed not in _pane_ids(root)):
        zoomed = None
    return SplitTree(root, floats, zoomed)


def zoom(tree: SplitTree, id: str) -> SplitTree:
    """Tiled pane `id` fills the area; the tree is kept."""
    _tree(tree)
    _id(id, "id")
    if path_of(tree, id)[:1] == ("float",):
        raise ValueError(f"zoom needs a tiled pane, {id!r} is floating")
    return replace(tree, zoomed=id)


def unzoom(tree: SplitTree) -> SplitTree:
    """No pane zoomed."""
    _tree(tree)
    return replace(tree, zoomed=None)


def select(tree: SplitTree, path: tuple, index: int) -> SplitTree:
    """The Tabs or Stacked at `path` shows child `index`."""
    _tree(tree)
    _int(index, "index")
    node = node_at(tree, path)
    if not isinstance(node, (Tabs, Stacked)):
        raise ValueError(f"the node at {path} must be a Tabs or Stacked, got a {type(node).__name__}")
    if not 0 <= index < len(node.children):
        raise ValueError(f"index must be in 0..{len(node.children) - 1}, got {index}")
    return _set(tree, path, replace(node, active=index))


def reveal(tree: SplitTree, id: str) -> SplitTree:
    """Every Tabs and Stacked above pane `id` shows the branch holding it."""
    _tree(tree)
    _id(id, "id")
    path = path_of(tree, id)
    low = 2 if path[:1] == ("float",) else 0
    for cut in range(len(path) - 1, low - 1, -1):
        node = node_at(tree, path[:cut])
        if isinstance(node, (Tabs, Stacked)) and node.active != path[cut]:
            tree = _set(tree, path[:cut], replace(node, active=path[cut]))
    return tree


def add_float(tree: SplitTree, node: object, rect: Rect) -> SplitTree:
    """Float(node, rect) added on top."""
    _tree(tree)
    f = Float(node, rect)
    clash = set(_pane_ids(node)) & set(ids(tree))
    if clash:
        raise ValueError(f"the node's pane ids are already in the tree: {sorted(clash)}")
    return replace(tree, floating=tree.floating + (f,))


def move_float(tree: SplitTree, i: int, rect: Rect) -> SplitTree:
    """Float `i` given `rect`."""
    _tree(tree)
    _float_index(tree, i)
    floats = list(tree.floating)
    floats[i] = Float(floats[i].node, rect)
    return replace(tree, floating=tuple(floats))


def raise_float(tree: SplitTree, i: int) -> SplitTree:
    """Float `i` moved to the top, the others' order kept."""
    _tree(tree)
    _float_index(tree, i)
    floats = list(tree.floating)
    top = floats.pop(i)
    return replace(tree, floating=tuple(floats) + (top,))


def neighbour(tree: SplitTree, area: Rect, id: str, direction: str) -> "str | None":
    """The visible tiled pane next to `id` on `direction`, by the spatial rule; or None."""
    _tree(tree)
    _rect(area, "area")
    _id(id, "id")
    _direction(direction)
    path = path_of(tree, id)
    if tree.zoomed is not None or path[:1] == ("float",):
        return None
    tiling = panes(tree, area)
    me = tiling[id]
    if not me.visible:
        return None
    cur = me.rect
    best, pick = None, None
    for order, p in enumerate(tiling.panes):
        c = p.rect
        if p.id == id or p.floating or not p.visible or c.empty:
            continue
        if direction in ("left", "right"):
            gap = c.x - cur.right if direction == "right" else cur.x - c.right
            overlap = min(c.bottom, cur.bottom) - max(c.y, cur.y)
            start = c.y
        else:
            gap = c.y - cur.bottom if direction == "down" else cur.y - c.bottom
            overlap = min(c.right, cur.right) - max(c.x, cur.x)
            start = c.x
        if gap < 0 or overlap <= 0:
            continue
        key = (gap, -overlap, start, order)
        if best is None or key < best:
            best, pick = key, p.id
    return pick


def ids(tree: SplitTree) -> tuple:
    """Every pane id, tiled in pre-order then floating in z order."""
    _tree(tree)
    tiled = [] if tree.root is None else _pane_ids(tree.root)
    return tuple(tiled + [i for f in tree.floating for i in _pane_ids(f.node)])


def path_of(tree: SplitTree, id: str) -> tuple:
    """The path of pane `id` (KeyError when none)."""
    _tree(tree)
    _id(id, "id")
    if tree.root is not None:
        found = _find(tree.root, id, ())
        if found is not None:
            return found
    for i, f in enumerate(tree.floating):
        found = _find(f.node, id, ("float", i))
        if found is not None:
            return found
    raise KeyError(id)


def node_at(tree: SplitTree, path: tuple) -> object:
    """The node at `path` (KeyError when none)."""
    _tree(tree)
    node, rest = _base(tree, path)
    for k in rest:
        if not _is_int(k) or isinstance(node, Pane) or not 0 <= k < len(node.children):
            raise KeyError(path)
        node = node.children[k]
    return node


def to_data(tree: SplitTree) -> dict:
    """The tree as JSON-ready data with a version."""
    _tree(tree)
    return {"version": VERSION,
            "root": None if tree.root is None else _node_data(tree.root),
            "floating": [{"node": _node_data(f.node),
                          "rect": [f.rect.x, f.rect.y, f.rect.w, f.rect.h]}
                         for f in tree.floating],
            "zoomed": tree.zoomed}


def from_data(data: object) -> SplitTree:
    """The tree `to_data` gave; SplitDataError for anything else."""
    _keys(data, ("version", "root", "floating", "zoomed"), "data")
    version = data["version"]
    if not _is_int(version) or version != VERSION:
        raise SplitDataError(f"version: must be {VERSION}, got {version!r}")
    root = None if data["root"] is None else _node_from(data["root"], "root")
    floats = []
    for i, item in enumerate(_seq(data["floating"], "floating")):
        place = f"floating[{i}]"
        _keys(item, ("node", "rect"), place)
        node = _node_from(item["node"], place + ".node")
        rect = _ints(item["rect"], place + ".rect")
        if len(rect) != 4:
            raise SplitDataError(f"{place}.rect: must hold 4 ints, got {len(rect)}")
        floats.append(_built(lambda: Float(node, Rect(*rect)), place + ".rect"))
    zoomed = data["zoomed"]
    if zoomed is not None and not isinstance(zoomed, str):
        raise SplitDataError(f"zoomed: must be a str or None, got {type(zoomed).__name__}")
    return _built(lambda: SplitTree(root, tuple(floats), zoomed), "data")


# -- private helpers

_KINDS = {"pane": ("kind", "id"), "split": ("kind", "axis", "children", "weights", "mins"),
          "tabs": ("kind", "children", "active", "bar"), "stacked": ("kind", "children", "active")}


class _Laid:
    """What a layout walk collects: pane rects, gutters, bars, and every node's rect by path."""

    def __init__(self) -> None:
        self.panes: list = []
        self.gutters: list = []
        self.bars: list = []
        self.rects: dict = {}


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _tree(tree: object) -> None:
    if not isinstance(tree, SplitTree):
        raise TypeError(f"tree must be a SplitTree, got {type(tree).__name__}")


def _rect(value: object, name: str) -> None:
    if not isinstance(value, Rect):
        raise TypeError(f"{name} must be a Rect, got {type(value).__name__}")


def _id(value: object, name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a str, got {type(value).__name__}")
    if not value:
        raise ValueError(f"{name} must be a non-empty str")


def _axis(axis: object) -> None:
    if not isinstance(axis, str):
        raise TypeError(f"axis must be a str, got {type(axis).__name__}")
    if axis not in AXES:
        raise ValueError(f"axis must be 'x' or 'y', got {axis!r}")


def _direction(direction: object) -> None:
    if not isinstance(direction, str):
        raise TypeError(f"direction must be a str, got {type(direction).__name__}")
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {DIRECTIONS}, got {direction!r}")


def _float_index(tree: SplitTree, i: object) -> None:
    _int(i, "i")
    if not 0 <= i < len(tree.floating):
        raise KeyError(i)


def _clamped(rect: Rect, area: Rect) -> Rect:
    """A float's rect (relative to the area) clamped into `area`, as attach clamps."""
    w, h = min(rect.w, area.w), min(rect.h, area.h)
    x = max(area.x, min(area.x + rect.x, area.right - w))
    y = max(area.y, min(area.y + rect.y, area.bottom - h))
    return Rect(x, y, w, h)


def _sizes(node: Split, L: int) -> tuple:
    """A split's child sizes along its axis in `L` cells: the min rule or water-filling."""
    return _shares(node.weights, node.mins, L)


@lru_cache(maxsize=4096)
def _shares(weights: tuple, mins: tuple, L: int) -> tuple:
    """`_sizes` by the weights and mins alone (memoised: a pure function of its arguments)."""
    n = len(weights)
    avail = max(L, 0) - sum(gaps(n, 1, L))
    if sum(mins) >= avail:
        return solve([Min(m) for m in mins], L, gap=1)
    frozen: set = set()
    while True:
        free = [i for i in range(n) if i not in frozen]
        room = avail - sum(mins[i] for i in frozen)
        total = sum(weights[i] for i in free)
        newly = {i for i in free if Fraction(room * weights[i], total) < mins[i]}
        if not newly:
            break
        frozen |= newly
    return solve([Fixed(mins[i]) if i in frozen else Fill(weights[i]) for i in range(n)],
                 L, gap=1)


def _lay(node: object, path: tuple, r: Rect, visible: bool, laid: _Laid) -> None:
    """Lay `node` out at `r`, collecting its panes, and its gutters and bars when visible."""
    laid.rects[path] = r
    if isinstance(node, Pane):
        laid.panes.append(PaneRect(node.id, path, r, visible, path[:1] == ("float",)))
        return
    if isinstance(node, Split):
        horizontal = node.axis == "x"
        start, L = (r.x, r.w) if horizontal else (r.y, r.h)
        n = len(node.children)
        cuts = gaps(n, 1, L)
        at, kid_rects = start, []
        for i, size in enumerate(_sizes(node, L)):
            kid_rects.append(Rect(at, r.y, size, r.h) if horizontal else Rect(r.x, at, r.w, size))
            at += size
            if i < n - 1:
                g = cuts[i]
                if visible:
                    strip = Rect(at, r.y, g, r.h) if horizontal else Rect(r.x, at, r.w, g)
                    laid.gutters.append(Gutter(path, i, node.axis, strip))
                at += g
        for i, (kid, kid_rect) in enumerate(zip(node.children, kid_rects)):
            _lay(kid, path + (i,), kid_rect, visible, laid)
        return
    if isinstance(node, Tabs):
        b = min(node.bar, r.h)
        if visible:
            laid.bars.append(Bar(path, "tabs", node.active, Rect(r.x, r.y, r.w, b), True))
        slot = Rect(r.x, r.y + b, r.w, r.h - b)
    else:
        n, k = len(node.children), node.active
        s = max(r.h - n, 0)
        if visible:
            for i in range(n):
                row = Rect(r.x, r.y + i + (s if i > k else 0), r.w, 1).intersect(r)
                laid.bars.append(Bar(path, "title", i, row, i == k))
        slot = Rect(r.x, r.y + k + 1, r.w, s).intersect(r)
    for i, kid in enumerate(node.children):
        _lay(kid, path + (i,), slot, visible and i == node.active, laid)


def _find(node: object, id: str, path: tuple) -> "tuple | None":
    if isinstance(node, Pane):
        return path if node.id == id else None
    for i, kid in enumerate(node.children):
        found = _find(kid, id, path + (i,))
        if found is not None:
            return found
    return None


def _base(tree: SplitTree, path: object) -> "tuple[object, tuple]":
    """The node a path starts from (the root, or a float's node) and the indices after it."""
    if not isinstance(path, tuple):
        raise TypeError(f"path must be a tuple, got {type(path).__name__}")
    if path[:1] == ("float",):
        if len(path) < 2 or not _is_int(path[1]) or not 0 <= path[1] < len(tree.floating):
            raise KeyError(path)
        return tree.floating[path[1]].node, path[2:]
    if tree.root is None:
        raise KeyError(path)
    return tree.root, path


def _has_parent(path: tuple) -> bool:
    return len(path) > (2 if path[:1] == ("float",) else 0)


def _set(tree: SplitTree, path: tuple, new: object) -> SplitTree:
    """The tree with the node at `path` replaced by `new`."""
    node, rest = _base(tree, path)
    built = _put(node, rest, new)
    if path[:1] == ("float",):
        floats = list(tree.floating)
        floats[path[1]] = Float(built, floats[path[1]].rect)
        return replace(tree, floating=tuple(floats))
    return replace(tree, root=built)


def _put(node: object, rest: tuple, new: object) -> object:
    if not rest:
        return new
    k = rest[0]
    kids = list(node.children)
    kids[k] = _put(kids[k], rest[1:], new)
    return replace(node, children=tuple(kids))


def _removed(node: object, rest: tuple) -> object:
    """`node` with the pane at `rest` removed (None when nothing is left), by close's rules."""
    if not rest:
        return None
    r = rest[0]
    kid = _removed(node.children[r], rest[1:])
    kids = list(node.children)
    if kid is not None:
        kids[r] = kid
        return replace(node, children=tuple(kids))
    del kids[r]
    if isinstance(node, Split):
        if len(kids) == 1:
            return kids[0]
        weights, mins = list(node.weights), list(node.mins)
        del weights[r], mins[r]
        return Split(node.axis, tuple(kids), tuple(weights), tuple(mins))
    if not kids:
        return None
    n, active = len(node.children), node.active
    if r < active:
        active -= 1
    elif r == active:
        active = min(active, n - 2)
    return replace(node, children=tuple(kids), active=active)


def _renamed(node: object, names: dict) -> object:
    if isinstance(node, Pane):
        return Pane(names.get(node.id, node.id))
    return replace(node, children=tuple(_renamed(kid, names) for kid in node.children))


def _reduced(weights: list) -> tuple:
    """Weights divided by their gcd."""
    g = math.gcd(*weights)
    return tuple(w // g for w in weights)


def _inserted(values: tuple, at: int, value: int) -> tuple:
    return values[:at] + (value,) + values[at:]


def _node_data(node: object) -> dict:
    if isinstance(node, Pane):
        return {"kind": "pane", "id": node.id}
    kids = [_node_data(kid) for kid in node.children]
    if isinstance(node, Split):
        return {"kind": "split", "axis": node.axis, "children": kids,
                "weights": list(node.weights), "mins": list(node.mins)}
    if isinstance(node, Tabs):
        return {"kind": "tabs", "children": kids, "active": node.active, "bar": node.bar}
    return {"kind": "stacked", "children": kids, "active": node.active}


def _keys(data: object, keys: tuple, place: str) -> None:
    if not isinstance(data, dict):
        raise SplitDataError(f"{place}: must be a dict, got {type(data).__name__}")
    missing = [k for k in keys if k not in data]
    extra = [k for k in data if k not in keys]
    if missing or extra:
        raise SplitDataError(f"{place}: keys must be {list(keys)}; missing {missing}, extra {extra!r}")


def _seq(value: object, place: str) -> tuple:
    if not isinstance(value, (list, tuple)):
        raise SplitDataError(f"{place}: must be a list, got {type(value).__name__}")
    return tuple(value)


def _ints(value: object, place: str) -> tuple:
    items = _seq(value, place)
    for i, v in enumerate(items):
        if not _is_int(v):
            raise SplitDataError(f"{place}[{i}]: must be an int, got {type(v).__name__}")
    return items


def _int_at(value: object, place: str) -> int:
    if not _is_int(value):
        raise SplitDataError(f"{place}: must be an int, got {type(value).__name__}")
    return value


def _built(make, place: str) -> object:
    """`make()`, its TypeError or ValueError raised as a SplitDataError naming `place`."""
    try:
        return make()
    except SplitDataError:
        raise
    except (TypeError, ValueError) as error:
        raise SplitDataError(f"{place}: {error}") from None


def _node_from(data: object, place: str) -> object:
    if not isinstance(data, dict):
        raise SplitDataError(f"{place}: must be a dict, got {type(data).__name__}")
    kind = data.get("kind")
    if not isinstance(kind, str) or kind not in _KINDS:
        raise SplitDataError(f"{place}.kind: must be one of {sorted(_KINDS)}, got {kind!r}")
    _keys(data, _KINDS[kind], place)
    if kind == "pane":
        if not isinstance(data["id"], str):
            raise SplitDataError(f"{place}.id: must be a str, got {type(data['id']).__name__}")
        return _built(lambda: Pane(data["id"]), place + ".id")
    kids = tuple(_node_from(kid, f"{place}.children[{i}]")
                 for i, kid in enumerate(_seq(data["children"], place + ".children")))
    if kind == "split":
        axis = data["axis"]
        if not isinstance(axis, str):
            raise SplitDataError(f"{place}.axis: must be a str, got {type(axis).__name__}")
        weights = _ints(data["weights"], place + ".weights")
        mins = _ints(data["mins"], place + ".mins")
        return _built(lambda: Split(axis, kids, weights, mins), place)
    active = _int_at(data["active"], place + ".active")
    if kind == "tabs":
        bar = _int_at(data["bar"], place + ".bar")
        return _built(lambda: Tabs(kids, active, bar), place)
    return _built(lambda: Stacked(kids, active), place)
