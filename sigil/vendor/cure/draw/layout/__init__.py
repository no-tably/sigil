"""[Layout]: rects: solver, flex, box model, scaffold, splits, viewport.

Kind: system (the expansion of [Layout] in Draw); pure. Rects first: every node gets
its rect before anything paints. It imports only Core (Geometry's {Rect}), which it
inherits through Draw; never Widgets, Paint or Theme. A node is read by duck typing
(the protocol below), and a natural size reaches it only through the `measure` the
caller passes: Layout never measures text.

The parts: [Solver] (`solve`: a length divided among constraints, largest remainder,
no residue), [Flex] (`row`, `column`, `grid`, `stack`), [BoxModel] (`boxed`: margin,
border, title, padding as insets), [Scaffold] (`regions`: pinned header and footer, a
scrolling body, `↓N more` as the floor), [Anchor] (`place`, `attach`: overlays),
[Whitespace] (`fit`: a panel in a drawing's empty corner), [Splits] (`panes`: split
trees as data, with tabs, stacked panes, floats, zoom and gutters; pure edits;
`to_data` / `from_data`), [Screens] (the screen stack: which screen gets input,
which are drawn under a backdrop), [Viewport] (2-D pan, home / centre, follow a
focus box without fighting the person's panning).

Splits is a separate call, not a node kind: `lay` does not read split trees. The app
(or Paint) calls `panes(tree, area)` first, then lays each visible pane's own node
tree in its rect with `lay`. Screens and Viewport are values the app keeps; `lay`
reads neither.

The boundary: `lay(node, rect, measure=None) -> Rects` (`[Paint] -> [Layout] :
lay({Node}) => {Rects}` and `[Frame] -> [Layout] : lay`).

The node protocol (attributes read with `getattr`, each with its default; W1's
widget nodes satisfy it):
- `children`: a sequence of child nodes (default `()`: a leaf).
- `layout`: how the children are arranged in the node's content rect: one of
  [Flex]'s `Row`, `Column`, `Grid`, `Stack`, or [Scaffold]'s `Scaffold`; `None`
  (the default) arranges them as `Column()`.
- `box`: a [BoxModel] `Box` or `None` (the default: the content rect is the node's
  rect). The node's content rect is `boxed(rect, box).content`.
- `size`: the child's constraint along its parent's main axis in a `Row` or `Column`
  (a [Solver] constraint; default `Fill(1)`). Not read in a `Grid`, `Stack` or
  `Scaffold`, nor for the root.
- `anchor`: an [Anchor] `At` or `None` (the default). A child with an anchor is out
  of the flow: it takes no slot in its parent's arrangement (the other children are
  arranged as if it were absent) and floats over the parent's content rect.

The measure (Paint's, memoised there): `measure(node, axis, room) -> int`, the natural
size of `node` along `axis` ("x": width, "y": height), box included (BoxModel's
`outer`), given `room` cells on the other axis. `lay` calls it only for:
- a flow child whose `size` is `Auto()`: `measure(child, main_axis, content cross
  extent)`;
- a cross size, in a `Row` or `Column` whose `align` is not "stretch":
  `measure(child, cross_axis, the child's main size)`;
- an `Auto` column or row of a `Grid`: the column's natural width is the largest
  `measure(child, "x", content.h)` over its children (0 with none), solved first; a
  row's natural height the largest `measure(child, "y", that child's column width)`;
- the three children of a `Scaffold`: `measure(child, "y", content.w)` each (the
  header's, the body's and the footer's natural heights);
- a floating child: `w = measure(child, "x", content.h)`, then
  `h = measure(child, "y", min(w, content.w))`.

`lay(node, rect, measure)`, recursively from the root (path `()`, rect `rect`, clip
`rect`). For a node at `rect` with clip `clip`, its content rect `c`:
- `Row` / `Column`: the flow children get `row` / `column` of their `size`s in `c`,
  with the layout's `gap`, `justify`, `align`.
- `Grid`: the flow children fill `grid(columns, rows, c, gap_x, gap_y)` row-major
  (`rows=None`: `Fill(1)` rows as needed).
- `Stack`: every flow child gets `c`.
- `Scaffold`: exactly three flow children `(header, body, footer)`;
  `R = regions(c, header_h, content_h, footer_h, offset=..., anchor=...)`. The header
  gets `R.header`, the footer `R.footer`. The body gets its whole content, scrolled,
  when it is taller than the viewport (`content_h > R.body.h`):
  `Rect(R.body.x, R.body.y - R.first, R.body.w, content_h)`; else `R.body` (all of
  its rows). The body's slot is `R.body` (the viewport); the scaffold node's entry
  carries `R`, so Paint draws `R.more`.
- A floating child: `place(w, h, c, at, margin)` with its measured size.
- Every flow child's clip: `child.rect ∩ slot ∩ parent's clip` (`Rect.intersect`),
  where the slot is the region its parent's arrangement gave it: its own rect,
  except a scaffold body's, which is `R.body`, so a scrolled body never paints over
  the indicator or the footer. A floating child's clip: `child.rect ∩ the root rect`
  (an overlay is not clipped by its parent's scroll). A clip may be empty: the node
  is still laid out and listed.

`Rects` (the result): `placed`, a tuple of `Placed(path, node, rect, clip, regions,
floating)`, one per node occurrence in the tree, in pre-order (a parent before its
children, children in `children` order: the paint order, parents first). `path` is
the tuple of child indices from the root (`()` the root, `(0, 2)` the third child of
the first child; a floating child keeps its index in `children`); `regions` is the
`Regions` of a `Scaffold` node, else `None`; `floating` is true for a child with an
anchor. A node object that occurs twice gets two entries.
- `rects[path] -> Placed` (`KeyError` when no node has that path); `rects.of(node)`:
  the first entry whose `node is node` (`KeyError` when none); `len(rects)`,
  `iter(rects)` over `placed`; `rects.moved(dx, dy) -> Rects`: every rect, clip and
  regions moved, the rest kept.

Laws:
- Every node in the tree has exactly one entry per occurrence; `len(lay(...))` is the
  tree's node count. The root's entry is `Placed((), node, rect, rect, ..., False)`.
- Every flow child's clip lies inside its parent's clip and inside its own rect; a
  floating child's inside the root rect and its own rect.
- A flow child of a `Row`, `Column`, `Grid` or `Stack` lies inside its parent's
  content rect; so does every floating child.
- `lay(n, rect.moved(dx, dy), m) == lay(n, rect, m).moved(dx, dy)` (the measure is
  never told a position); with Scaffold's same_at_depth this is what makes a nested
  scaffold behave as the root does.

Errors: `TypeError` when `rect` is not a `Rect`, a `layout`, `box`, `size` or
  `anchor` is not of the types above, `children` is not iterable, or `measure`
  returns a non-int; `ValueError` when `measure` is needed and is `None`, returns a
  negative int, a `Scaffold` node has other than three flow children, a `Grid` with
  given `rows` has more flow children than cells, or a node is its own ancestor (a
  cycle). As the parts' errors otherwise.
Effects: none (beyond calling `measure`).

Re-exported for consumers: `Fixed`, `Min`, `Max`, `Percent`, `Ratio`, `Fill`, `Auto`,
`Constraint`, `solve`, `apportion`, `gaps` (solver); `Row`, `Column`, `Grid`, `Stack`,
`row`, `column`, `grid`, `stack` (flex); `Box`, `BoxRects`, `boxed`, `inset`, `outer`
(boxmodel); `Scaffold`, `Regions`, `regions` (scaffold); `At`, `Attached`, `place`,
`attach` (anchor); `Occupancy`, `fit` (whitespace); `SplitTree`, `Pane`, `Split`,
`Tabs`, `Stacked`, `Float`, `Tiling`, `PaneRect`, `Gutter`, `Bar`, `SplitDataError`,
`panes` (splits; its edits, queries and `to_data` / `from_data` are used through the
module: `from cure.draw.layout import splits`, `splits.close(tree, id)`); `Pushed`,
`Screens` (screens); `Viewport` (viewport).

Usage:
    from types import SimpleNamespace as N
    from cure.core.geometry import Rect
    from cure.draw.layout import lay, Row, Fixed, Fill, Box, Scaffold
    side, main = N(size=Fixed(10)), N()
    root = N(layout=Row(gap=1), children=(side, main))
    rects = lay(root, Rect(0, 0, 40, 10))
    rects[(0,)].rect, rects[(1,)].rect          # Rect(0, 0, 10, 10), Rect(11, 0, 29, 10)
    rects.of(main).clip                         # Rect(11, 0, 29, 10)
    page = N(layout=Scaffold(), box=Box(border=1),
             children=(N(h=1), N(h=50), N(h=1)))
    out = lay(page, Rect(0, 0, 20, 12), lambda node, axis, room: node.h)
    r = out[()].regions                         # in the content Rect(1, 1, 18, 10)
    r.header, r.body, r.more, r.footer
    #   Rect(1, 1, 18, 1), Rect(1, 2, 18, 7), Rect(1, 9, 18, 1), Rect(1, 10, 18, 1)
    r.below                                     # 43: Paint draws "↓43 more"
    out[(1,)].rect, out[(1,)].clip              # Rect(1, 2, 18, 50), Rect(1, 2, 18, 7)
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from functools import cached_property

from cure.core.geometry import Rect

from .anchor import At, Attached, attach, place
from .boxmodel import Box, BoxRects, boxed, inset, outer
from .flex import Column, Grid, Row, Stack, column, grid, row, stack
from .scaffold import Regions, Scaffold, regions
from .solver import Auto, Constraint, Fill, Fixed, Max, Min, Percent, Ratio, apportion, gaps, solve
from .screens import Pushed, Screens
from .splits import (Bar, Float, Gutter, Pane, PaneRect, Split, SplitDataError, SplitTree,
                     Stacked, Tabs, Tiling, add, add_float, close, drag, from_data, ids,
                     move_float, neighbour, node_at, panes, path_of, raise_float, resize,
                     reveal, select, split, swap, to_data, unzoom, zoom)
from .viewport import Viewport
from .whitespace import Occupancy, fit


@dataclass(frozen=True)
class Placed:
    """One node's place: its path, the node, its rect, its clip, its regions, floating."""

    path: tuple
    node: object
    rect: Rect
    clip: Rect
    regions: "Regions | None" = None
    floating: bool = False


@dataclass(frozen=True)
class Rects:
    """Every node's `Placed`, in pre-order (the paint order)."""

    placed: tuple = ()

    def __getitem__(self, path: tuple) -> Placed:
        """The entry at `path` (KeyError when none)."""
        return self._by_path[path]

    def of(self, node: object) -> Placed:
        """The first entry whose node is `node` (identity; KeyError when none)."""
        for entry in self.placed:
            if entry.node is node:
                return entry
        raise KeyError(node)

    def __len__(self) -> int:
        return len(self.placed)

    def __iter__(self) -> Iterator[Placed]:
        return iter(self.placed)

    def moved(self, dx: int, dy: int) -> "Rects":
        """Every rect, clip and regions moved by (`dx`, `dy`)."""
        return Rects(tuple(
            replace(p, rect=p.rect.moved(dx, dy), clip=p.clip.moved(dx, dy),
                    regions=None if p.regions is None else p.regions.moved(dx, dy))
            for p in self.placed))

    @cached_property
    def _by_path(self) -> dict:
        return {p.path: p for p in self.placed}


def lay(node: object, rect: Rect,
        measure: "Callable[[object, str, int], int] | None" = None) -> Rects:
    """Every node of the tree under `node` given its rect in `rect`, by the rules above."""
    if not isinstance(rect, Rect):
        raise TypeError(f"rect must be a Rect, got {type(rect).__name__}")
    out: list = []
    _visit(node, (), rect, rect, False, _Walk(rect, _checked(measure), out), frozenset())
    return Rects(tuple(out))


_LAYOUTS = (Row, Column, Grid, Stack, Scaffold)


@dataclass(frozen=True)
class _Walk:
    """What every level of the walk shares: the root rect, the measure, the entries."""

    root: Rect
    measure: Callable
    out: list


def _checked(measure: "Callable | None") -> Callable:
    """The caller's measure, its answers checked; a ValueError when needed and None."""
    def checked(node: object, axis: str, room: int) -> int:
        if measure is None:
            raise ValueError("a measure is needed (Auto, align, Grid Auto, Scaffold or anchor)")
        value = measure(node, axis, room)
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"measure must return an int, got {type(value).__name__}")
        if value < 0:
            raise ValueError(f"measure must return an int >= 0, got {value}")
        return value
    return checked


def _children(node: object) -> tuple:
    kids = getattr(node, "children", ())
    try:
        return tuple(kids)
    except TypeError:
        raise TypeError(f"children must be iterable, got {type(kids).__name__}") from None


def _layout(node: object) -> object:
    layout = getattr(node, "layout", None)
    if layout is None:
        return Column()
    if not isinstance(layout, _LAYOUTS):
        raise TypeError(f"layout must be a Row, Column, Grid, Stack or Scaffold, got {layout!r}")
    return layout


def _content(node: object, rect: Rect) -> Rect:
    box = getattr(node, "box", None)
    if box is None:
        return rect
    if not isinstance(box, Box):
        raise TypeError(f"box must be a Box or None, got {type(box).__name__}")
    return boxed(rect, box).content


def _anchor(child: object) -> "At | None":
    at = getattr(child, "anchor", None)
    if at is not None and not isinstance(at, At):
        raise TypeError(f"anchor must be an At or None, got {type(at).__name__}")
    return at


def _size(child: object) -> object:
    size = getattr(child, "size", None)
    if size is None:
        return Fill(1)
    if not isinstance(size, Constraint):
        raise TypeError(f"size must be a constraint value, got {size!r}")
    return size


def _visit(node: object, path: tuple, rect: Rect, clip: Rect, floating: bool, walk: _Walk,
           ancestors: frozenset) -> None:
    """Append `node`'s entry, then lay out and visit its children in order."""
    if id(node) in ancestors:
        raise ValueError(f"a node is its own ancestor at path {path}")
    kids = _children(node)
    layout = _layout(node)
    content = _content(node, rect)
    anchors = [_anchor(kid) for kid in kids]
    flow = [kid for kid, at in zip(kids, anchors) if at is None]
    slots, found = _arrange(layout, flow, content, walk.measure)
    walk.out.append(Placed(path, node, rect, clip, found, floating))
    inside = ancestors | {id(node)}
    flowing = iter(slots)
    for i, (kid, at) in enumerate(zip(kids, anchors)):
        if at is None:
            kid_rect, slot = next(flowing)
            kid_clip = kid_rect.intersect(slot).intersect(clip)
        else:
            kid_rect = _floated(kid, at, content, walk.measure)
            kid_clip = kid_rect.intersect(walk.root)
        _visit(kid, path + (i,), kid_rect, kid_clip, at is not None, walk, inside)


def _floated(kid: object, at: At, content: Rect, measure: Callable) -> Rect:
    """A floating child's rect: measured width, then height for that width, then `place`."""
    w = measure(kid, "x", content.h)
    h = measure(kid, "y", min(w, content.w))
    return place(w, h, content, at.at, at.margin)


def _arrange(layout: object, flow: list, c: Rect, measure: Callable
             ) -> "tuple[list, Regions | None]":
    """Each flow child's (rect, slot) in content rect `c`, and a Scaffold's regions."""
    if isinstance(layout, Scaffold):
        return _scaffolded(layout, flow, c, measure)
    if isinstance(layout, Stack):
        rects = stack(len(flow), c)
    elif isinstance(layout, Grid):
        rects = _gridded(layout, flow, c, measure)
    else:
        flex = row if isinstance(layout, Row) else column
        rects = flex([_size(kid) for kid in flow], c, gap=layout.gap, justify=layout.justify,
                     align=layout.align, measure=lambda i, axis, room: measure(flow[i], axis, room))
    return [(r, r) for r in rects], None


def _scaffolded(layout: Scaffold, flow: list, c: Rect, measure: Callable
                ) -> "tuple[list, Regions]":
    """Header, scrolled body and footer of a Scaffold node, and its regions."""
    if len(flow) != 3:
        raise ValueError(f"a Scaffold node needs exactly three flow children, got {len(flow)}")
    head, body, foot = (measure(kid, "y", c.w) for kid in flow)
    R = regions(c, head, body, foot, offset=layout.offset, anchor=layout.anchor)
    body_rect = R.body
    if body > R.body.h:
        body_rect = Rect(R.body.x, R.body.y - R.first, R.body.w, body)
    return [(R.header, R.header), (body_rect, R.body), (R.footer, R.footer)], R


def _gridded(layout: Grid, flow: list, c: Rect, measure: Callable) -> list:
    """The flow children's cells of a Grid, row-major; Auto tracks measured per the rules."""
    columns = layout.columns
    n = len(columns)
    rows = layout.rows
    if rows is None:
        rows = (Fill(1),) * (-(-len(flow) // n))
    elif len(flow) > n * len(rows):
        raise ValueError(f"a Grid of {n * len(rows)} cells has {len(flow)} flow children")
    naturals: dict = {}

    def column_natural(j: int) -> int:
        if j not in naturals:
            naturals[j] = max((measure(flow[k], "x", c.h) for k in range(j, len(flow), n)),
                              default=0)
        return naturals[j]

    def track(i: int, axis: str, room: int) -> int:
        if axis == "x":
            return column_natural(i)
        widths = solve(columns, c.w, gap=layout.gap_x, measure=column_natural)
        return max((measure(flow[k], "y", widths[k % n])
                    for k in range(i * n, min((i + 1) * n, len(flow)))), default=0)

    cells = grid(columns, rows, c, gap_x=layout.gap_x, gap_y=layout.gap_y, measure=track)
    return [cell for line in cells for cell in line][:len(flow)]
