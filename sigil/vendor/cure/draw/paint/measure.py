"""[Measure]: natural sizes without painting, memoised.

Kind: service (pure functions and two small classes: the `Adapted` node Layout reads,
and `Measure`, the per-frame memo Paint hands Layout as its `measure`). Measure
provides `natural` (`[Frame] -> [Measure] : natural({Node}) => {Size}`): the natural
size of a node of the tree along one axis, its chrome and its children included,
never painting and never reading a grid. One frame is a pure function (the same node
tree, size and context give the same frame), so a natural size is a function of the
node occurrence, the axis, the room and the node's own {Context} alone.

Why an adapter. A widget node may not import Layout (`.construct/mapping.md`), so it
cannot hold a Layout `Box`; it gives its insets as `chrome()` (the Widgets package's
protocol) and its natural size as `node.measure(axis, room, ctx, content)`, where
`content` is its children's natural size, which only Paint can compute (only Paint
knows Layout). Layout's `lay` reads a node's `children`, `layout`, `box`, `size` and
`anchor` with `getattr`, and calls `measure(node, axis, room)`. So Paint lays out an
adapted copy of the tree: `adapt(root)` builds one `Adapted` per node occurrence, each
carrying the widget node, its path and the Layout attributes; Layout's `Rects` then
lists `Adapted` nodes (`placed.node.node` is the widget node), and `Measure` is the
`measure` Layout calls, answering for an `Adapted`.

Data:
- `Adapted(node, path, box, children, layout, size, anchor)` (a frozen dataclass,
  `eq=False`: compared by identity, as Layout's `rects.of` compares nodes):
  - `node`: the widget node (any value with the Widgets protocol's attributes);
  - `path`: its tuple of child indices from the root (`()` the root), as Layout's
    `Placed.path`;
  - `box`: `Box(**node.chrome())` (a Layout BoxModel `Box`) when `node.chrome()` is
    not `None`, else `None`;
  - `children`: a tuple of `Adapted`, one per item of `getattr(node, "children", ())`
    in order, child `i` at `path + (i,)`;
  - `layout`, `size`, `anchor`: `getattr(node, name, None)` each, held as given
    (Layout checks their types when it lays the tree out).
- `Measure(contexts)`: the memo of one tree in one frame. `contexts` maps each path to
  that node's own {Context} (Painter's `contexts`). `Measure` instances are callable as
  Layout's `measure(node, axis, room)`: `m(a, axis, room) == natural(a, axis, room,
  m.contexts, memo=m.memo)`. `m.memo` is a `dict` keyed `(path, axis, room)`, filled as
  sizes are computed; it lives exactly as long as the `Measure` (Paint makes one per
  laid-out tree per frame and drops it with the frame: nothing is kept between frames).

Operations:
- `adapt(node, path=()) -> Adapted`: the adapted tree under `node`, by the rules above,
  in pre-order. Before reading anything else of a node it checks the Widgets protocol:
  every attribute of Widgets' `PROTOCOL` (`paint`, `measure`, `chrome`, `id`, `size`,
  `anchor`, `scope`, `surface`), in that order; the first one missing is a
  `TypeError` "node lacks '<name>'" (the message Widgets' `paint` gives). A node that is
  its own ancestor (a cycle through `children`) is a `ValueError` "a node is its own
  ancestor at path <path>" (Layout's message), raised before any recursion past it; a
  node object occurring twice elsewhere is fine and is adapted twice (two `Adapted`,
  two paths).
- `natural(a, axis, room, contexts, *, memo=None) -> int`: the natural size of the
  adapted node `a` along `axis` (`"x"`: width, `"y"`: height), chrome included, given
  `room` cells on the other axis:
  `a.node.measure(axis, room, contexts[a.path], content(a, axis, room, nat))`, with
  `nat(k, axis, room) = natural(k, axis, room, contexts, memo=memo)` for its children.
  With `memo` (a `dict`), the result for `(a.path, axis, room)` is looked up first and
  stored after: `a.node.measure` is called at most once per `(path, axis, room)` for
  one memo (the law a test counts calls for), whatever Layout and the recursion ask.
- `content(a, axis, room, nat) -> int`: the natural size along `axis` of `a`'s
  children as its layout arranges them, at `room` less the chrome on the other axis
  (`0` when `a` has no flow children, whatever its layout: a Grid's fixed tracks and
  gaps included). The rules:
  - The flow children `F` are `a.children` whose `anchor` is `None` (a floating child
    takes no slot: it is out of the flow, as in Layout), in order; `n = len(F)`.
  - The chrome: `(cw, ch) = outer(0, 0, a.box)` (Layout's BoxModel), `(0, 0)` when
    `a.box` is `None`. The inner room: `inner = max(0, room - cw)` when `axis == "y"`
    (the room is a width), `max(0, room - ch)` when `axis == "x"` (a height).
  - A child's main contribution along the main axis of a Row or Column,
    `main(k, ax, r)`, with `s = k.size`: `s.n` for `Fixed(n)`; `max(s.n, nat(k, ax,
    r))` for `Min(n)`; `min(s.n, nat(k, ax, r))` for `Max(n)`; `nat(k, ax, r)` for any
    other (`Fill`, `Auto`, `Percent`, `Ratio`, `None`). A track's contribution in a
    Grid, `track(c, v)` for constraint `c` and natural `v`, is the same rule (`v` for
    `rows=None`'s implicit `Fill(1)` rows).
  - `Column(gap=g)` (also `layout=None`): `"y"`: `sum(main(k, "y", inner)) + g * (n -
    1)`; `"x"`: `max(nat(k, "x", inner))`.
  - `Row(gap=g)`: `"x"`: `sum(main(k, "x", inner)) + g * (n - 1)`; `"y"`: with the
    children's widths `ws = solve([k.size or Fill(1) for k in F], inner, gap=g,
    measure=lambda i: nat(F[i], "x", 0))` (Layout's Solver; an `Auto` child's width at
    room 0, since the row's height is what is being found), `max(nat(F[i], "y",
    ws[i]))`.
  - `Grid(columns, rows, gap_x, gap_y)`: with `c = len(columns)`, child `i` in column
    `i % c` and row `i // c`, `r` the row count (`len(rows)`, or `ceil(n / c)` when
    `rows` is `None`), `colnat(j, h) = max(nat(F[i], "x", h) for i in column j)`
    (`0` for an empty column): `"x"`: `sum(track(columns[j], colnat(j, inner)) for j)
    + gap_x * (c - 1)`; `"y"`: with `ws = solve(columns, inner, gap=gap_x,
    measure=lambda j: colnat(j, 0))`, `rownat(i) = max(nat(F[k], "y", ws[k % c]) for k
    in row i)` (`0` for an empty row), `sum(track(rows_i, rownat(i)) for i) + gap_y *
    (r - 1)`.
  - `Stack()`: `max(nat(k, axis, inner))`.
  - `Scaffold(...)`: `"y"`: `sum(nat(k, "y", inner))` over the three; `"x"`:
    `max(nat(k, "x", inner))`.
  A `max` over no children is `0`, and `g * (n - 1)` is `0` for `n == 0`.

Laws (each a property a test can loop over trees, axes, rooms and contexts):
- pure: the same adapted tree, axis, room and contexts give the same size, memo or no
  memo (`natural(a, x, r, cx) == natural(a, x, r, cx, memo={})`).
- memoised: with one memo, `node.measure` is called at most once per `(path, axis,
  room)`; `Measure` answers Layout from its memo.
- a leaf: `natural(adapt(leaf), axis, room, cx) == leaf.measure(axis, room,
  cx[()], 0)` (a node with no flow children gets `content == 0`).
- floating children never count: adding a child with an anchor leaves every natural
  size of its parent unchanged.

Inputs: `node` any value with the Widgets protocol; `a`, `k` an `Adapted`; `axis` `"x"`
  or `"y"`; `room` an `int >= 0`; `contexts` a mapping from paths to {Context}s; `memo`
  a `dict` or `None`; `nat` a callable `(Adapted, axis, room) -> int`.
Outputs: an `Adapted`; an `int >= 0` (the {Size} along one axis).
Errors: `adapt`: `TypeError` "node lacks '<name>'" as above, or when `children` is not
  iterable (Layout's message: "children must be iterable, got <type>"); `ValueError`
  for a cycle; what `node.chrome()` and `Box(...)` raise for bad insets passes
  through. `natural` / `content`: `ValueError` when `axis` is not `"x"` / `"y"` or
  `room` is negative; `TypeError` when `room` is not an `int` (a `bool` included) or
  `node.measure` returns a non-int (a `bool` included: "measure must return an int,
  got <type>"); `ValueError` when it returns a negative int ("measure must return an
  int >= 0, got <n>"); `KeyError` when `contexts` has no entry for a path; what
  `node.measure`, `solve` and `outer` raise passes through.
Effects: none (beyond calling each node's `chrome` and `measure`, and filling `memo`).

Usage:
    from cure.draw.context import Context
    from cure.draw.theme import builtin
    from cure.draw.layout import Box
    from cure.draw.widgets import Block, Paragraph
    from cure.draw.paint.measure import Measure, adapt, natural
    from cure.draw.paint.painter import contexts
    tree = Block((Paragraph("hello"),), title="Hi")
    a = adapt(tree)
    a.box == Box(border=1, title=True), a.children[0].path   # True, (0,)
    cx = contexts(tree, Context.of(builtin()))
    natural(a, "x", 10, cx)           # 8: max(5 + 2, width("Hi") + 6)
    natural(a, "y", 10, cx)           # 3: one row of text + 2 border rows
    m = Measure(cx)
    m(a, "y", 10), m.memo[((), "y", 10)]   # 3, 3
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from cure.draw.layout import Box, Column, Fill, Fixed, Max, Min, Row, Scaffold, Stack, outer, solve
from cure.draw.layout import Grid as GridLayout
from cure.draw.widgets import PROTOCOL


@dataclass(frozen=True, eq=False)
class Adapted:
    """One node occurrence as Layout reads it: the widget node, its path, its box (see the module)."""

    node: object
    path: tuple
    box: object
    children: tuple
    layout: object = None
    size: object = None
    anchor: object = None


def adapt(node: object, path: tuple = ()) -> Adapted:
    """The adapted tree under `node`: a `Box` from each `chrome()`, the paths (see the module)."""
    return _adapt(node, path, frozenset())


def _adapt(node: object, path: tuple, ancestors: frozenset) -> Adapted:
    for name in PROTOCOL:
        if not hasattr(node, name):
            raise TypeError(f"node lacks {name!r}")
    if id(node) in ancestors:
        raise ValueError(f"a node is its own ancestor at path {path}")
    chrome = node.chrome()
    box = None if chrome is None else Box(**chrome)
    kids = getattr(node, "children", ())
    try:
        kids = tuple(kids)
    except TypeError:
        raise TypeError(f"children must be iterable, got {type(kids).__name__}") from None
    inside = ancestors | {id(node)}
    children = tuple(_adapt(k, path + (i,), inside) for i, k in enumerate(kids))
    return Adapted(node, path, box, children, getattr(node, "layout", None),
                   getattr(node, "size", None), getattr(node, "anchor", None))


def content(a: Adapted, axis: str, room: int,
            nat: "Callable[[Adapted, str, int], int]") -> int:
    """The natural size of `a`'s flow children as its layout arranges them (see the module)."""
    _check(axis, room)
    flow = [k for k in a.children if k.anchor is None]
    if not flow:
        return 0
    cw, ch = (0, 0) if a.box is None else outer(0, 0, a.box)
    inner = max(0, room - (cw if axis == "y" else ch))
    layout = Column() if a.layout is None else a.layout
    n = len(flow)
    if isinstance(layout, Row):
        if axis == "x":
            return sum(_main(k, "x", inner, nat) for k in flow) + layout.gap * (n - 1)
        ws = solve([Fill(1) if k.size is None else k.size for k in flow], inner,
                   gap=layout.gap, measure=lambda i: nat(flow[i], "x", 0))
        return max(nat(k, "y", w) for k, w in zip(flow, ws))
    if isinstance(layout, Column):
        if axis == "y":
            return sum(_main(k, "y", inner, nat) for k in flow) + layout.gap * (n - 1)
        return max(nat(k, "x", inner) for k in flow)
    if isinstance(layout, GridLayout):
        return _grid(layout, flow, axis, inner, nat)
    if isinstance(layout, Stack):
        return max(nat(k, axis, inner) for k in flow)
    if isinstance(layout, Scaffold):
        if axis == "y":
            return sum(nat(k, "y", inner) for k in flow)
        return max(nat(k, "x", inner) for k in flow)
    raise TypeError(f"layout must be a Row, Column, Grid, Stack or Scaffold, got {layout!r}")


def _main(k: Adapted, axis: str, room: int, nat: Callable) -> int:
    """A flow child's contribution along a Row's or Column's main axis."""
    return _track(k.size, lambda: nat(k, axis, room))


def _track(c: object, v: "Callable[[], int]") -> int:
    """A constraint's contribution given its natural `v()` (asked only when needed)."""
    if isinstance(c, Fixed):
        return c.n
    if isinstance(c, Min):
        return max(c.n, v())
    if isinstance(c, Max):
        return min(c.n, v())
    return v()


def _grid(layout: GridLayout, flow: list, axis: str, inner: int, nat: Callable) -> int:
    """A Grid's natural extent: its tracks' contributions and gaps (see `content`)."""
    columns = layout.columns
    c, n = len(columns), len(flow)
    found: dict = {}

    def colnat(j: int, h: int) -> int:
        if (j, h) not in found:
            found[j, h] = max((nat(flow[i], "x", h) for i in range(j, n, c)), default=0)
        return found[j, h]

    if axis == "x":
        return (sum(_track(columns[j], lambda: colnat(j, inner)) for j in range(c))
                + layout.gap_x * (c - 1))
    rows = layout.rows
    r = -(-n // c) if rows is None else len(rows)
    ws = solve(columns, inner, gap=layout.gap_x, measure=lambda j: colnat(j, 0))

    def rownat(i: int) -> int:
        return max((nat(flow[k], "y", ws[k % c]) for k in range(i * c, min((i + 1) * c, n))),
                   default=0)

    total = sum(_track(Fill(1) if rows is None else rows[i], lambda: rownat(i))
                for i in range(r))
    return total + layout.gap_y * (r - 1)


def natural(a: Adapted, axis: str, room: int, contexts: Mapping, *,
            memo: "dict | None" = None) -> int:
    """`a`'s natural size along `axis` at `room`, chrome and children included (see the module)."""
    _check(axis, room)
    key = (a.path, axis, room)
    if memo is not None and key in memo:
        return memo[key]

    def nat(k: Adapted, ax: str, r: int) -> int:
        return natural(k, ax, r, contexts, memo=memo)

    value = a.node.measure(axis, room, contexts[a.path], content(a, axis, room, nat))
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"measure must return an int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"measure must return an int >= 0, got {value}")
    if memo is not None:
        memo[key] = value
    return value


def _check(axis: object, room: object) -> None:
    if axis not in ("x", "y"):
        raise ValueError(f"axis must be 'x' or 'y', got {axis!r}")
    if not isinstance(room, int) or isinstance(room, bool):
        raise TypeError(f"room must be an int, got {type(room).__name__}")
    if room < 0:
        raise ValueError(f"room must be >= 0, got {room}")


@dataclass(frozen=True, eq=False)
class Measure:
    """The memo of one tree in one frame; callable as Layout's `measure` (see the module)."""

    contexts: Mapping
    memo: dict = field(default_factory=dict)

    def __call__(self, a: Adapted, axis: str, room: int) -> int:
        """`natural(a, axis, room, self.contexts, memo=self.memo)`."""
        return natural(a, axis, room, self.contexts, memo=self.memo)
