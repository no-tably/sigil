"""[Collections]: virtualised rows from an app-owned source: List, Table, Tree.

Kind: system (the expansion of [Collections] in Widgets); pure. It imports Core only
(Text, Style, Buffer, Geometry, which it inherits through Draw): never Containers,
Readouts, Controls, Surfaces, the Widgets package, Layout, Theme, Input, Paint or
Draw's `context.py`. A {Context} arrives as an argument and is read by attribute.
Inside the family, `table.py` and `tree.py` use `list.py`'s `window`, `GUTTER` and
its row painter (`fetch`, `RowPainter`: List's module states them; package-internal, not
re-exported), plus the family's private toolkit in `list.py`, which List uses too.

The parts, every one a leaf (no children, `chrome()` is `None`, `lifts(ctx)` is
`False`, `surface` defaults to `False`): [List] (`List`, `ListRow`, and the window
arithmetic `window`, `Window`, `reveal`), [Table] (`Table`, `TableColumn`,
`TableRow`, and the width rule `fit`), [Tree] (`Tree`, `TreeNode`).

The node protocol, as the Widgets package states it in full (`cure/draw/widgets`):
each kind is a frozen dataclass, its content fields first, then keyword-only fields
ending in `id`, `size`, `anchor`, `scope`, `surface`; `measure(axis, room, ctx,
content=0) -> int` (`content` ignored), `paint(rect, ctx, grid, clip=None) ->
tuple[Hit, ...]`. Painting follows the protocol's recipe (the clip's ground
`ctx.ground()`, the content, `shade(grid, clip, bg=g.style.bg)`). What every
collection shares is stated once here; each module states its own rows.

The source (List and Table). The rows are the app's and are never copied: `rows` is
either a sequence (any object with `__len__` and `__getitem__` that is not a `str`
or `bytes`: a tuple, a list the app appends to, its own lazy view), whose length is
the row count, or a callable `rows(i) -> row` for `i` in `range(count)`, with `count`
(an `int >= 0`) given beside it. A collection is virtualised: `paint` fetches only
the rows it draws (`rows[i]` / `rows(i)` for `i` in `first .. first + shown - 1` of
its window, each at most once per call, in ascending order; Table's auto column
widths read those same rows and no others). `measure` fetches every row (it is
`O(count)`: give a long collection a `size` other than `Auto()` so Layout never asks
it, see Layout's Solver). A row is checked when it is fetched, not at construction
(the source may be a callable): a row of the wrong shape is a `TypeError` from
`paint` or `measure`, and whatever the source itself raises propagates. This is the
one place a collection's `paint` may fail on content; every field of the node is
still checked at construction.

One row per item, one cell row per row: rows never wrap (a virtualised view needs a
fixed row height). Text cut on the right ends in `ctx.glyph("ellipsis")`, measured
(Text's `cut(..., ellipsis=...)`: an ASCII `...` takes three cells).

The gutter. Every row of a collection (and every header row) starts with
`GUTTER = 2` reserved cells, the row's two mark cells, so that a row's place and its
state both show with colour off, and a focused row that is also selected shows both:
- cell 0, the cursor cell: the mark of focused (`›`) when the row is focused, else
  the mark of hover when it is hovered (the builtin charset has no `mark.hover`:
  `""`), else a blank;
- cell 1, the state cell: the mark of selected (`•`) when the row is selected, else
  the mark of the row's own `state` when it has one (`pressed` ●, `active` ●,
  `emphasised` ✦, `muted` ·; `disabled` has none), else a blank.
A mark cell takes the row's style there (the ground, with the row's row-extent
treatments applied, below). A header row's gutter is blank ground.

A row's states, for row `i` of a collection `c` (the item `it`, its `state` and
`id` as each kind names them), with `f` the collection's focus (`c.focused` when it
is not `None`, else `ctx.is_focused(c.id)`):
- focused: `(i == c.cursor and f) or ctx.is_focused(it.id)` (the cursor row shows
  only while the collection is focused; an item may also be focused by its own id);
- selected: `i in c.selected` (Tree: `it.id in c.selected`) or `it.state ==
  "selected"`;
- hover: `ctx.is_hovered(it.id)`, or `ctx.is_hovered((c.id, "row", i))` when
  `c.id` is not `None` (the tag a row without an id is hit by);
- the row's own `state` (one of Theme's states, `None` for none).
They are applied additively, `ctx.apply(<cell style>, state)`, in the order: the
row's own state, selected, hover, focused (a state already applied is not applied
twice: a row whose `state` is "selected" and that is in `selected` is selected
once), each over its treatment's extent (`ctx.treat(state).extent`): `"row"`
(focused, selected, hover, pressed) over every cell of the row inside the clip, the
gutter and the trailing ground included; `"text"` (active, emphasised, muted,
disabled) over the row's text cells only (List: the text; Table: each cell's text;
Tree: the label, never the guides or the twisty). A focused collection with no
`cursor` (and no focused item) shows its focus only through its pane (the enclosing
Block's border).

Legible (the protocol's law, per state, with colour off): focused, through the
cursor cell's `›`; selected, through the state cell's `•`, on the focused row too;
pressed, active, emphasised, muted, through the state cell's mark (pressed and
active also bold, emphasised bold, muted dim); hover, through its floor flag
(underline) over the row; disabled, through its floor flag (dim) over the text.

The window (`list.window`, the same for all three kinds). With `n` rows and `H`
cell rows for them: when `n <= H` every row shows; when `n > H` the LAST cell row is
the indicator and at most `H - 1` rows show. `follow=True` (a log's tail-follow)
shows the last rows, whatever `offset` says. The indicator is `More`'s text (see
Containers' Scrollbar): `up + str(above) + " " + down + str(below) + " more"` when
both counts are `> 0`, `down + str(below) + " more"` or `up + str(above) + " more"`
when only one is, with `down = ctx.glyph("more.down")` (↓), `up =
ctx.glyph("more.up")` (↑), in role `muted`, from the row's first cell (the gutter
too), cut to the row with no ellipsis, the rest ground. Overflow is never silent.
`reveal(cursor, offset, count, height)` is the offset that brings a cursor into view
with the least move; the app keeps the offset (it is view state, the app's).

Hits, in order: `Hit(clip, id)` when the collection's `id` is not `None`; then each
kind's header and row hits (each `Hit(r ∩ clip, tag)`, only when not empty): a row
drawn at cell row `y` gives `Hit(Rect(R.x, y, R.w, 1) ∩ clip, tag)` with `tag =
it.id` when that is not `None`, else `(id, "row", i)` when `id` is not `None` (`i`
the row's index in the source, or in Tree's `flat()`), else none; then the indicator
row, `Hit(<its row> ∩ clip, (id, "more"))` when `id` is not `None`. The app's router
turns a row hit into its own action (rove, commit and fire stay three steps: a click
names a row, it does not move the cursor by itself).

Every law listed in the Widgets package (contained, owned, pure, hits, moved,
legible, fits) holds for every kind here; and one more:
- virtual: with a callable source that records its calls, `paint` asks exactly for
  the indices `first .. first + shown - 1` of `window(...)` (Tree: it reads only the
  nodes `flat()` walks), whatever `count` is.

Re-exported for consumers: `List`, `ListRow`, `Window`, `window`, `reveal`,
`GUTTER` (list); `Table`, `TableColumn`, `TableRow`, `fit` (table); `Tree`,
`TreeNode` (tree).

Effects: none, apart from `paint`'s writes into the grid it is given.

Usage:
    from cure.core.buffer import Grid, text
    from cure.core.geometry import Rect
    from cure.draw.context import Context
    from cure.draw.theme import builtin
    from cure.draw.widgets.collections import List, window
    ctx = Context.of(builtin(), focus="l")
    g = Grid(8, 3)
    List(("alpha", "beta", "gamma"), cursor=2, selected={2}, id="l").paint(Rect(0, 0, 8, 3), ctx, g)
    text(g)                      # "  alpha\\n  beta\\n›•gamma"
    window(0, 10, 4)             # Window(first=0, shown=3, above=0, below=7)
"""

from .list import GUTTER, List, ListRow, Window, reveal, window
from .table import Table, TableColumn, TableRow, fit
from .tree import Tree, TreeNode
