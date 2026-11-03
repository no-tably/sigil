"""[Tree]: guides, twisties, depth cap.

Kind: service (two frozen dataclasses, the `Tree` node kind and its `TreeNode`
items; see the Widgets package's protocol and the Collections package's shared
rules: the gutter, a row's states, the window, the hits).

What it does: an app-owned tree drawn as rows, one per node reached through open
nodes only (depth first, in order), each row its two gutter cells, its indentation
guides, its twisty (open ▾, closed ▸, a leaf none) and its label. Only the open
nodes are walked (a closed node's children are never read), and only the rows in
the window are drawn. Which nodes are open, the cursor and the selection are the
app's; a click on a twisty hits it, and the app's router toggles that node.

Data (frozen dataclasses; checked on construction):
- `TreeNode(label, children=(), *, open=False, expandable=None, state=None,
  id=None)`:
  - `label`: styled text (span style `None` is the role `text`).
  - `children`: a tuple of `TreeNode` (each checked by its own construction).
  - `open`: whether its children are shown.
  - `expandable`: `None` (`bool(children)`), or `True` / `False`: whether it shows a
    twisty (`True` with no children: a node whose children the app loads when it is
    opened).
  - `state`, `id`: as `ListRow`'s.
- `Tree(roots=(), *, cursor=None, selected=frozenset(), offset=0, cap=None,
  focused=None, id=None, size=None, anchor=None, scope=None, surface=False)`:
  - `roots`: a tuple of `TreeNode`, the top level (depth 0).
  - `cursor`: `None` or an index into `flat()`.
  - `selected`: a container of node ids (`node.id in selected`; a node with no id is
    selected only by its `state`).
  - `offset`: the first row of `flat()` the app wants shown (List's window).
  - `cap`: `None` or an `int >= 1`, the depth cap: the most indentation segments a
    row draws (below).
  - `focused`, `id`, `size`, `anchor`, `scope`, `surface`: as List's.

The rows (`flat() -> tuple[tuple[int, TreeNode], ...]`): `(depth, node)` for each
root and, below every node that is `open`, its children, depth first in order;
roots at depth 0. The app maps the cursor and a row hit's index through it.

A row, for node `p_d` at depth `d` on the path `p_0 (a root), p_1, .., p_d` (cells
from `R.x`):
1. The gutter (2 cells, the marks as the Collections package states).
2. The guides, `d` segments of 2 cells, in `ctx.border(False)` (receded): segment
   `k` (for `k` in `0 .. d - 1`) is about `p_{k+1}`: for `k < d - 1`,
   `ctx.glyph("guide.vert") + " "` (│) when `p_{k+1}` has a next sibling, else two
   blanks; for `k = d - 1` (the node's own), `ctx.glyph("guide.branch") +
   ctx.glyph("guide.stem")` (├─) when `p_d` has a next sibling, else
   `ctx.glyph("guide.last") + ctx.glyph("guide.stem")` (└─). Roots have no
   connector (their siblings are not joined).
3. The depth cap: when `cap` is not `None` and `d > cap`, the row draws `cap`
   segments only: first a fold segment, `ctx.glyph("ellipsis")` cut (or padded with
   a blank) to 2 cells in role `muted` ("… "; ASCII ".."), then the last `cap - 1`
   segments of step 2 (those for `k = d - cap + 1 .. d - 1`). So a row's indent is
   `2 * min(d, cap)` cells (`2 * d` with no cap), and deep trees stop running off.
4. The twisty cell, in role `muted`: `ctx.glyph("twisty.open")` (▾) for an
   expandable open node, `ctx.glyph("twisty.closed")` (▸) for an expandable closed
   one; for a leaf, `ctx.glyph("guide.stem")` (─, continuing its connector) at
   depth `>= 1`, a blank at depth 0.
5. One blank, then the label, cut with the ellipsis to the cells left in the row.
The rest of the row is ground. The label is the row's text (a `"text"` state covers
its cells only).

Painting (`paint(rect, ctx, grid, clip=None)`), with `rows = flat()`, `n =
len(rows)`, `w = window(offset, n, R.h)` (List's; a Tree has no `follow`): the
clip's ground; each row of the window on its cell row; the states; the indicator as
List's when `n > R.h >= 1`; `shade(grid, clip, bg=g.style.bg)`, `g = ctx.ground()`.

Hits, in order: `Hit(clip, id)` when `id` is not `None`; then for each drawn row
`i`: its row hit as the Collections package states (`node.id`, else `(id, "row",
i)`), then, when the node is expandable and `id` is not `None`, `Hit(<the twisty
cell> ∩ clip, (id, "twisty", i)`; then the indicator's `(id, "more")`.

Measuring: `"x"`: the widest row, `GUTTER + indent + 2 + width(label)` over
`flat()` (`0` with no roots); `"y"`: `len(flat())`.

Exact cells (the builtin theme; guides in `ctx.border(False)`, twisties in
`ctx.style("muted")`, labels in `ctx.style("text")`), with `roots =
(TreeNode("src", (TreeNode("a", (TreeNode("x"),)), TreeNode("b")), open=True),
TreeNode("README"))`:
- `Tree(roots, id="tr")` at `Rect(0, 0, 10, 4)`: `"  ▾ src   "`, `"  ├─▸ a   "`,
  `"  └── b   "`, `"    README"`; `flat()` is `((0, src), (1, a), (1, b), (0,
  README))`; hits `Hit(Rect(0, 0, 10, 4), "tr")`, then per row `Hit(Rect(0, i,
  10, 1), ("tr", "row", i))`, with `Hit(Rect(2, 0, 1, 1), ("tr", "twisty", 0))`
  after row 0's and `Hit(Rect(4, 1, 1, 1), ("tr", "twisty", 1))` after row 1's.
- With `a` open: a row `"  │ └── x"` after `a`'s (`x` is `a`'s last child; `a` has
  a next sibling, so its column keeps the `│`).
- A chain `r > p > q > z`, every node open and an only child: rows `"  ▾ r"`,
  `"  └─▾ p"`, `"    └─▾ q"`, `"      └── z"`; with `cap=2` the last is
  `"  … └── z"`.
- `cursor=1` with `ctx.focus == "tr"`: row 1 `"› ├─▸ a   "`, every cell focused.
- `measure("x", 0, ctx) == 10` and `measure("y", 0, ctx) == 4` for the first tree.

Errors: construction: `TypeError` when `roots` or `children` is not a tuple of
  `TreeNode`, `label` is neither a `str` nor a `Line`, `open` is not a `bool`,
  `expandable` / `focused` is not `None` or a `bool`, `cap` is not `None` or an int
  (a `bool` included), or as List's for the shared fields; `ValueError` when `cap <
  1`, `cursor` is outside `range(len(flat()))`, or as List's. `paint` / `measure`:
  as the protocol states.
Through List (Q9c): each drawn row painted and hit through List's public row painter
(`RowPainter(ctx)`, one per `paint` call: its `row` and `hit`), never List's private
`_paint_row`, `_row_hit` or `_Styler`; the window is List's `window`. List's
module states their inputs, outputs and errors.
Effects: none, apart from `paint`'s writes into the grid it is given.

Usage:
    from cure.core.buffer import Grid, text
    from cure.core.geometry import Rect
    from cure.draw.context import Context
    from cure.draw.theme import builtin
    from cure.draw.widgets.collections import Tree, TreeNode
    t = Tree((TreeNode("src", (TreeNode("a", (TreeNode("x"),)), TreeNode("b")), open=True),
              TreeNode("README")))
    g = Grid(10, 4)
    t.paint(Rect(0, 0, 10, 4), Context.of(builtin()), g)
    text(g)                      # "  ▾ src\\n  ├─▸ a\\n  └── b\\n    README"
    [d for d, _ in t.flat()]     # [0, 1, 1, 0]
"""

from collections.abc import Hashable
from dataclasses import KW_ONLY, dataclass

from cure.core.buffer import Grid
from cure.core.geometry import Hit, Rect
from cure.core.text import Line, cut

from .list import GUTTER, window  # noqa: F401  (the shared gutter and window arithmetic)
from .list import RowPainter, row  # List's row painter and its op (see List's module)
from .list import (_begin, _check_common, _check_flag, _check_id, _check_int, _check_measure,
                   _check_state, _check_text, _fitted, _focus, _ground, _hit, _indicator, _is_int,
                   _plain, _put, _shade, _styled, _width)


def _check_nodes(name: str, nodes: object) -> None:
    if not isinstance(nodes, tuple) or not all(isinstance(n, TreeNode) for n in nodes):
        raise TypeError(f"{name} must be a tuple of TreeNode")


def _walk(roots: tuple):
    """`(depth, node, nexts)` for every row, depth first, through open nodes only;
    `nexts[k]` is whether the path's node at depth `k` has a next sibling (a live
    list: copy what is kept)."""
    frames = [[roots, 0]]
    nexts: list = []
    while frames:
        frame = frames[-1]
        kids, i = frame
        if i >= len(kids):
            frames.pop()
            continue
        frame[1] = i + 1
        d = len(frames) - 1
        del nexts[d:]
        nexts.append(i < len(kids) - 1)
        node = kids[i]
        yield d, node, nexts
        if node.open and node.children:
            frames.append([node.children, 0])


def _expandable(node: "TreeNode") -> bool:
    return bool(node.children) if node.expandable is None else node.expandable


@dataclass(frozen=True)
class TreeNode:
    """One node: a label, its children, open or closed (see the module)."""

    label: "str | Line"
    children: tuple = ()
    _: KW_ONLY
    open: bool = False
    expandable: "bool | None" = None
    state: "str | None" = None
    id: Hashable = None

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _check_text("label", self.label)
        _check_nodes("children", self.children)
        _check_flag("open", self.open)
        _check_flag("expandable", self.expandable, none=True)
        _check_state(self.state)
        _check_id("id", self.id)


@dataclass(frozen=True)
class Tree:
    """A tree's open rows, with guides and twisties, virtualised (see the module)."""

    roots: tuple = ()
    _: KW_ONLY
    cursor: "int | None" = None
    selected: object = frozenset()
    offset: int = 0
    cap: "int | None" = None
    focused: "bool | None" = None
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = False

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _check_nodes("roots", self.roots)
        if self.cursor is not None and not _is_int(self.cursor):
            raise TypeError(f"cursor must be None or an int, got {type(self.cursor).__name__}")
        _check_int("offset", self.offset)
        if not hasattr(self.selected, "__contains__"):
            raise TypeError(f"selected must be a container, got {type(self.selected).__name__}")
        if self.cap is not None and not _is_int(self.cap):
            raise TypeError(f"cap must be None or an int, got {type(self.cap).__name__}")
        _check_flag("focused", self.focused, none=True)
        _check_common(self)
        if self.cap is not None and self.cap < 1:
            raise ValueError(f"cap must be >= 1, got {self.cap}")
        if self.cursor is not None:
            n = sum(1 for _ in _walk(self.roots))
            if not 0 <= self.cursor < n:
                raise ValueError(f"cursor {self.cursor} is outside range({n})")

    def flat(self) -> "tuple[tuple[int, TreeNode], ...]":
        """`(depth, node)` for every row: the roots and the open nodes' children (see the module)."""
        return tuple((d, node) for d, node, _ in _walk(self.roots))

    def chrome(self) -> None:
        """None: no insets."""
        return None

    def lifts(self, ctx: object) -> bool:
        """Always False."""
        return False

    def _indent(self, d: int) -> int:
        return 2 * (d if self.cap is None else min(d, self.cap))

    def measure(self, axis: str, room: int, ctx: object, content: int = 0) -> int:
        """The widest row; one cell row per row of `flat()` (see the module)."""
        _check_measure(axis, room, content)
        if axis == "y":
            return sum(1 for _ in _walk(self.roots))
        widest = None
        for d, node, _ in _walk(self.roots):
            w = GUTTER + self._indent(d) + 2 + _width(node.label)
            widest = w if widest is None or w > widest else widest
        return 0 if widest is None else widest

    def paint(self, rect: Rect, ctx: object, grid: Grid, clip: "Rect | None" = None
              ) -> "tuple[Hit, ...]":
        """The rows in view: marks, guides, twisties, labels, the indicator (see the module)."""
        begun = _begin(rect, grid, clip)
        if begun is None:
            return ()
        clip, area = begun
        g = ctx.ground()
        _ground(grid, area, g.style)
        R = rect
        hits = [] if self.id is None else [Hit(clip, self.id)]
        n = sum(1 for _ in _walk(self.roots))
        w = window(self.offset, n, R.h)
        f = _focus(self, ctx)
        painter = RowPainter(ctx)
        look = _Look(ctx)
        end = w.first + w.shown
        if w.shown:
            for i, (d, node, nexts) in enumerate(_walk(self.roots)):
                if i < w.first:
                    continue
                if i >= end:
                    break
                y = R.y + i - w.first
                tx = R.x + GUTTER + self._indent(d)
                if area.y <= y < area.bottom:
                    pieces = self._row(d, node, nexts, R, tx, look, ctx)
                    own = node.state
                    sel = (node.id is not None and node.id in self.selected) or own == "selected"
                    hov = (ctx.is_hovered(node.id) or own == "hover"
                           or (self.id is not None and ctx.is_hovered((self.id, "row", i))))
                    foc = (i == self.cursor and f) or ctx.is_focused(node.id) or own == "focused"
                    row(painter, grid, R, y, area, g.style, own, pieces,
                        selected=sel, hovered=hov, focused=foc)
                hit = painter.hit(R, y, clip, node.id, self.id, "row", i)
                if hit is not None:
                    hits.append(hit)
                if self.id is not None and _expandable(node):
                    hit = _hit(Rect(tx, y, 1, 1), clip, (self.id, "twisty", i))
                    if hit is not None:
                        hits.append(hit)
        if n > R.h >= 1:
            y = R.y + R.h - 1
            _indicator(grid, R, y, area, ctx, w.above, w.below)
            if self.id is not None:
                hit = _hit(Rect(R.x, y, R.w, 1), clip, (self.id, "more"))
                if hit is not None:
                    hits.append(hit)
        _shade(grid, area, g.style)
        return tuple(hits)

    def _row(self, d: int, node: TreeNode, nexts: list, R: Rect, tx: int, look: "_Look",
             ctx: object) -> "list[tuple[int, Line, bool]]":
        """One row's pieces: the guides, the twisty, the label (the row's text)."""
        pieces = []
        x = R.x + GUTTER
        ks = range(d)
        if self.cap is not None and d > self.cap:
            pieces.append((x, look.fold, False))
            x += 2
            ks = range(d - self.cap + 1, d)
        for k in ks:
            pieces.append((x, look.segment(k == d - 1, nexts[k + 1]), False))
            x += 2
        if _expandable(node):
            pieces.append((tx, look.open if node.open else look.closed, False))
        elif d >= 1:
            pieces.append((tx, look.stem, False))
        lx = tx + 2
        label = _fitted(_styled(node.label, ctx, "text"), R.right - lx, ctx)
        if label.spans:
            pieces.append((lx, label, True))
        return pieces


class _Look:
    """A Tree's glyph pieces for one paint call, from the charset and the theme."""

    def __init__(self, ctx: object) -> None:
        guide, muted = ctx.border(False), ctx.style("muted")
        stem = ctx.glyph("guide.stem")
        self.vert = _plain(ctx.glyph("guide.vert") + " ", guide)
        self.blank = _plain("  ", guide)
        self.branch = _plain(ctx.glyph("guide.branch") + stem, guide)
        self.last = _plain(ctx.glyph("guide.last") + stem, guide)
        self.fold = cut(_plain(ctx.glyph("ellipsis"), muted), 2, pad=True, fill_style=muted)
        self.open = _plain(ctx.glyph("twisty.open"), muted)
        self.closed = _plain(ctx.glyph("twisty.closed"), muted)
        self.stem = _plain(stem, muted)

    def segment(self, own: bool, has_next: bool) -> Line:
        if own:
            return self.branch if has_next else self.last
        return self.vert if has_next else self.blank
