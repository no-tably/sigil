"""[Table]: columns with constraints, header, alignment, selection.

Kind: service (three frozen dataclasses, the `Table` node kind, its `TableColumn`
columns and `TableRow` rows, and the pure width rule `fit`; see the Widgets
package's protocol and the Collections package's shared rules: the source, the
gutter, a row's states, the window, the hits).

What it does: a header row of column titles, then one row per record of an
app-owned source (virtualised, from an offset, tail-follow as List's), each row its
two gutter cells then its cells laid in columns. Column widths come from the
columns' own constraints and the cells in view by the rule `fit` below (Layout-free:
Table may not import Layout); a cell wider than its column is cut with the measured
ellipsis; columns that cannot be drawn at all are marked, never silently dropped.

Data (frozen dataclasses; checked on construction):
- `TableColumn(title="", *, width=None, min=1, max=None, grow=0, align="left",
  sort=None, id=None)`:
  - `title`: styled text (span style `None` is the role `title`).
  - `width`: `None` (auto: from the content) or an `int >= 0`, a fixed width that is
    never grown or shrunk.
  - `min`: an `int >= 0`, the narrowest an auto column shrinks to (and the least its
    natural width is raised to).
  - `max`: `None` or an `int >= min`, the widest an auto column's natural width is
    taken as (it may still grow past it by `grow`).
  - `grow`: an `int >= 0`, the column's share of the spare cells.
  - `align`: `"left"`, `"centre"` (or `"center"`) or `"right"`: how its cells and
    its title sit in its width (Text's `align`).
  - `sort`: `None`, `"up"` or `"down"`: the header shows `" " +
    ctx.glyph("more.up")` (↑) or `" " + ctx.glyph("more.down")` (↓) after the title,
    in role `muted` (the app sorts; the arrow only shows it).
  - `id`: the column's own tag for its header hit.
- `TableRow(cells, state=None, *, id=None)`: `cells` a tuple of styled text (`str`
  or `Line`; span style `None` is the role `text`), one per column (missing cells
  are empty, extra cells are not drawn); `state` and `id` as `ListRow`'s. A source
  row may also be a bare tuple of cells: `TableRow(row)`.
- `Table(columns=(), rows=(), *, count=None, header=True, gap=1, cursor=None,
  selected=frozenset(), offset=0, follow=False, focused=None, id=None, size=None,
  anchor=None, scope=None, surface=False)`: `columns` a tuple of `TableColumn`;
  `header` whether the header row is drawn; `gap` an `int >= 0`, the ground cells
  between two columns; `rows`, `count`, `cursor`, `selected`, `offset`, `follow`,
  `focused` as List's.

The header label of column `j`: its title, then the sort arrow when `sort` is set
(`" ↑"` / `" ↓"`). Its natural width `nat_j` (at paint) is the widest of the header
label (when `header`) and the column's cells in the rows drawn (the window's rows
only: auto widths follow what is in view; fix `width` to keep a column still while
scrolling); at measure, of the header label and every row's cell.

The width rule (`fit(columns, naturals, room, gap=1) -> tuple[int, ...]`): the
widths of the columns drawn, from the left (a shorter tuple when columns are
dropped), for `room` cells (at paint, `R.w - GUTTER`, at least 0), with `k =
len(columns)`:
1. `w_j = width_j` when the column is fixed, else `max(min_j, min(naturals[j],
   max_j))` (`max_j` `None`: no cap). `total = sum(w) + gap * (k - 1)` (`0` for no
   columns).
2. `total <= room`: the spare `s = room - total` goes to the growing columns (`grow
   > 0`): with `G` their summed `grow`, column `j` gets `s * grow_j // G` more, then
   the cells still left one each to the growing columns from the left, in turn. With
   no growing column the spare stays as ground after the last column. Done.
3. `total > room`: one cell at a time, the widest auto column whose `w_j > min_j`
   (ties: the rightmost) gives up a cell, until `total <= room` or none can.
4. Still `total > room`: columns are kept from the left while each fits whole (the
   first at 0, each next after `gap` cells); the first that does not fit takes the
   cells left after its gap, when that is at least 1, and every later column is
   dropped.
Examples (`a = TableColumn("a")`, `b = TableColumn("b")`): `fit((a, b), (5, 4), 12)
== (5, 4)`; with `a` `grow=1`: `(7, 4)`; `fit((a, b), (5, 4), 8) == (4, 3)` (5 → 4,
then the tie 4/4 goes to the rightmost); `fit((TableColumn("a", width=6),
TableColumn("b", min=4)), (6, 9), 8) == (6, 1)`; `fit((TableColumn("a", width=4),
TableColumn("b", width=4)), (0, 0), 5) == (4,)`; two growing columns, naturals
`(2, 2)`, room 8: `(4, 3)`.

Painting (`paint(rect, ctx, grid, clip=None)`), on `rect` `R` with `g =
ctx.ground()`:
- the header is drawn on row `R.y` when `header` is true and `R.h >= 2`, or
  `R.h == 1` and there are no rows (one row and some rows: the row is the
  indicator's); `head` is 1 when it is drawn, else 0;
- the window `w = window(offset, n, R.h - head, follow=follow)` (List's), and the
  widths `W = fit(columns, nat, max(R.w - GUTTER, 0), gap)` from the drawn rows;
  column `j` starts at `x_j = R.x + GUTTER + sum(W[:j]) + gap * j`;
- the header row: the gutter blank; each drawn column's header label cut to `W[j]`
  with the ellipsis when wider, aligned in `W[j]` by its `align`, the title in role
  `title` (bold: it reads with colour off), the arrow in `muted`; when columns were
  dropped (`len(W) < k`), the header row's last `E` cells (`E` the ellipsis's
  width) become `ctx.glyph("ellipsis")` in role `muted`; a hovered column header
  (`ctx.is_hovered(column.id)`, or `(id, "column", j)` when `id` is not `None`)
  takes `ctx.apply(.., "hover")` over its `W[j]` cells;
- each row of the window on the cell rows below: the gutter marks, each cell `j`
  cut to `W[j]` with the ellipsis when wider and aligned in it by its column's
  `align`, the gaps and the rest ground; the row's states over their extents (a
  `"text"` state covers each cell's text cells);
- the indicator as List's, on the last row, when `n > R.h - head >= 1`;
- `shade(grid, clip, bg=g.style.bg)`.

Hits, in order: `Hit(clip, id)` when `id` is not `None`; then each drawn header
cell, `Hit(Rect(x_j, R.y, W[j], 1) ∩ clip, tag)` with `tag = column.id` when that is
not `None`, else `(id, "column", j)` when `id` is not `None`; then the rows and the
indicator as the Collections package states.

Measuring: `"x"`: `GUTTER + sum(w_j) + gap * (k - 1)`, the `w_j` of `fit`'s step 1
from every row (`0` with no columns); `"y"`: `(1 if header else 0) + n`.

Exact cells (the builtin theme; titles in `ctx.style("title")`, cells in
`ctx.style("text")`), with `cols = (TableColumn("name"), TableColumn("size",
align="right"))` and `recs = (("cure", "12"), ("sigil", "340"))`:
- `Table(cols, recs, id="t")` at `Rect(0, 0, 14, 3)` (`nat = (5, 4)`, `W = (5,
  4)`): `"  name  size  "`, `"  cure    12  "`, `"  sigil  340  "`; hits
  `Hit(Rect(0, 0, 14, 3), "t")`, `Hit(Rect(2, 0, 5, 1), ("t", "column", 0))`,
  `Hit(Rect(8, 0, 4, 1), ("t", "column", 1))`, `Hit(Rect(0, 1, 14, 1), ("t",
  "row", 0))`, `Hit(Rect(0, 2, 14, 1), ("t", "row", 1))`.
- With `TableColumn("name", grow=1)`: `"  name    size"`, `"  cure      12"`,
  `"  sigil    340"`.
- At width 10 (`W = (4, 3)`): `"  name si…"`, `"  cure  12"`, `"  sig… 340"`.
- `TableColumn("size", align="right", sort="down")`: the header `"  name  size ↓"`
  at width 14 (`nat = (5, 6)`).
- `Table((TableColumn("a", width=4), TableColumn("b", width=4)), (("abcd",
  "efgh"),))` at `Rect(0, 0, 7, 2)` (`W = (4,)`): `"  a   …"`, `"  abcd "`.
- `Table(cols, tuple((f"f{i}", str(i)) for i in range(9)))` at `Rect(0, 0, 10, 4)`:
  the header, rows `f0`, `f1`, then `"↓7 more"`.
- `measure("x", 0, ctx) == 12` and `measure("y", 0, ctx) == 3` for the first table.

Errors: construction: `TypeError` when `columns` is not a tuple of `TableColumn`, a
  `title` or a cell is neither a `str` nor a `Line`, `cells` is not a tuple,
  `width` / `max` is not `None` or an int, `min` / `grow` / `gap` is not an int (a
  `bool` included), `align` / `sort` is not a `str` (`sort` may be `None`), `header`
  is not a `bool`, or as List's for the shared fields; `ValueError` when `width`,
  `min`, `grow` or `gap` is negative, `max < min`, `align` or `sort` is not one of
  its values, or as List's. `fit`: `TypeError` when `columns` is not a tuple of
  `TableColumn` or `naturals` not a tuple of ints, `ValueError` when their lengths
  differ or a value is negative. `paint` / `measure`: as the protocol states, and a
  `TypeError` for a fetched row that is neither a `TableRow` nor a tuple of `str` /
  `Line`.
Through List (Q9c): its rows fetched with List's `fetch`, each drawn row painted and
hit through List's public row painter (`RowPainter(ctx)`, one per `paint` call: its
`row` and `hit`), never List's private `_paint_row`, `_row_hit`, `_Styler` or `_fetch`;
the window is List's `window`. List's module states their inputs, outputs and errors.
Effects: none, apart from `paint`'s writes into the grid it is given.

Usage:
    from cure.core.buffer import Grid, text
    from cure.core.geometry import Rect
    from cure.draw.context import Context
    from cure.draw.theme import builtin
    from cure.draw.widgets.collections import Table, TableColumn, fit
    cols = (TableColumn("name"), TableColumn("size", align="right"))
    g = Grid(14, 3)
    Table(cols, (("cure", "12"), ("sigil", "340"))).paint(Rect(0, 0, 14, 3), Context.of(builtin()), g)
    text(g)                      # "  name  size\\n  cure    12\\n  sigil  340"
    fit(cols, (5, 4), 8)         # (4, 3)
"""

from collections.abc import Hashable
from dataclasses import KW_ONLY, dataclass

from cure.core.buffer import Grid
from cure.core.geometry import Hit, Rect
from cure.core.text import Line, cut

from .list import GUTTER, window  # noqa: F401  (the shared gutter and window arithmetic)
from .list import RowPainter, fetch, row  # List's row painter and its op (see List's module)
from .list import (_begin, _check_collection, _check_flag, _check_id, _check_int, _check_measure,
                   _check_state, _check_text, _count, _fitted, _flags, _focus, _ground,
                   _hit, _indicator, _is_int, _join, _plain, _put, _restyle, _shade, _styled,
                   _width)

ALIGNS = ("left", "centre", "center", "right")
"""How a column's cells and title sit in its width."""

SORTS = ("up", "down")
"""A column's sort arrow, when it has one."""


def _base(column: "TableColumn", natural: int) -> int:
    """`fit`'s step 1 for one column: its fixed width, or its natural one bounded."""
    if column.width is not None:
        return column.width
    cap = natural if column.max is None else min(natural, column.max)
    return max(column.min, cap)


def fit(columns: "tuple[TableColumn, ...]", naturals: "tuple[int, ...]", room: int,
        gap: int = 1) -> "tuple[int, ...]":
    """The widths of the columns drawn in `room` cells (see the module)."""
    if not isinstance(columns, tuple) or not all(isinstance(c, TableColumn) for c in columns):
        raise TypeError("columns must be a tuple of TableColumn")
    if not isinstance(naturals, tuple) or not all(_is_int(v) for v in naturals):
        raise TypeError("naturals must be a tuple of ints")
    if len(naturals) != len(columns):
        raise ValueError(f"{len(columns)} columns but {len(naturals)} naturals")
    if any(v < 0 for v in naturals):
        raise ValueError(f"naturals must be >= 0, got {naturals}")
    _check_int("room", room)
    _check_int("gap", gap)
    k = len(columns)
    if k == 0:
        return ()
    w = [_base(c, n) for c, n in zip(columns, naturals)]
    total = sum(w) + gap * (k - 1)
    if total <= room:
        growers = [j for j, c in enumerate(columns) if c.grow > 0 and c.width is None]
        if growers:
            spare = room - total
            G = sum(columns[j].grow for j in growers)
            given = 0
            for j in growers:
                more = spare * columns[j].grow // G
                w[j] += more
                given += more
            left = spare - given
            while left > 0:
                for j in growers:
                    if left == 0:
                        break
                    w[j] += 1
                    left -= 1
        return tuple(w)
    auto = [j for j, c in enumerate(columns) if c.width is None]
    while total > room:
        best = None
        for j in auto:
            if w[j] > columns[j].min and (best is None or w[j] >= w[best]):
                best = j
        if best is None:
            break
        w[best] -= 1
        total -= 1
    if total <= room:
        return tuple(w)
    kept, pos = [], 0
    for j in range(k):
        start = pos + (gap if j else 0)
        if start + w[j] <= room:
            kept.append(w[j])
            pos = start + w[j]
        else:
            if room - start >= 1:
                kept.append(room - start)
            break
    return tuple(kept)


def _offset(extra: int, at: str) -> int:
    """Where a piece `extra` cells narrower than its field starts, by `at` (Text's
    `align`: the odd cell of a centred piece goes to the right)."""
    if extra <= 0 or at == "left":
        return 0
    return extra if at == "right" else extra // 2


@dataclass(frozen=True)
class TableColumn:
    """One column: title, width constraints, alignment, sort arrow (see the module)."""

    title: "str | Line" = ""
    _: KW_ONLY
    width: "int | None" = None
    min: int = 1
    max: "int | None" = None
    grow: int = 0
    align: str = "left"
    sort: "str | None" = None
    id: Hashable = None

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _check_text("title", self.title)
        for name in ("width", "max"):
            value = getattr(self, name)
            if value is not None and not _is_int(value):
                raise TypeError(f"{name} must be None or an int, got {type(value).__name__}")
        for name in ("min", "grow"):
            value = getattr(self, name)
            if not _is_int(value):
                raise TypeError(f"{name} must be an int, got {type(value).__name__}")
        if not isinstance(self.align, str):
            raise TypeError(f"align must be a str, got {type(self.align).__name__}")
        if self.sort is not None and not isinstance(self.sort, str):
            raise TypeError(f"sort must be None or a str, got {type(self.sort).__name__}")
        _check_id("id", self.id)
        for name in ("width", "min", "grow"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be >= 0, got {value}")
        if self.max is not None and self.max < self.min:
            raise ValueError(f"max {self.max} is less than min {self.min}")
        if self.align not in ALIGNS:
            raise ValueError(f"align must be one of {ALIGNS}, got {self.align!r}")
        if self.sort is not None and self.sort not in SORTS:
            raise ValueError(f"sort must be one of {SORTS}, got {self.sort!r}")


@dataclass(frozen=True)
class TableRow:
    """One record: its cells, a state, an id (see the module)."""

    cells: tuple = ()
    state: "str | None" = None
    _: KW_ONLY
    id: Hashable = None

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        if not isinstance(self.cells, tuple):
            raise TypeError(f"cells must be a tuple, got {type(self.cells).__name__}")
        for cell in self.cells:
            _check_text("a cell", cell)
        _check_state(self.state)
        _check_id("id", self.id)


def _table_row(row: object) -> TableRow:
    """A fetched row as a TableRow (a bare tuple of cells wrapped)."""
    if isinstance(row, TableRow):
        return row
    if isinstance(row, tuple):
        return TableRow(row)
    raise TypeError(f"a Table row must be a TableRow or a tuple of cells, got {type(row).__name__}")


def _label(column: TableColumn, ctx: object) -> Line:
    """The header label: the title in role `title`, then the sort arrow in `muted`."""
    title = _styled(column.title, ctx, "title")
    if column.sort is None:
        return title
    arrow = ctx.glyph("more.up" if column.sort == "up" else "more.down")
    return _join(title, _plain(" " + arrow, ctx.style("muted")))


def _label_width(column: TableColumn, ctx: object) -> int:
    w = _width(column.title)
    if column.sort is not None:
        w += _width(" " + ctx.glyph("more.up" if column.sort == "up" else "more.down"))
    return w


@dataclass(frozen=True)
class Table:
    """A virtualised table: header, columns, rows from an app-owned source (see the module)."""

    columns: tuple = ()
    rows: object = ()
    _: KW_ONLY
    count: "int | None" = None
    header: bool = True
    gap: int = 1
    cursor: "int | None" = None
    selected: object = frozenset()
    offset: int = 0
    follow: bool = False
    focused: "bool | None" = None
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = False

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        if not isinstance(self.columns, tuple) or not all(
                isinstance(c, TableColumn) for c in self.columns):
            raise TypeError("columns must be a tuple of TableColumn")
        _check_flag("header", self.header)
        if not _is_int(self.gap):
            raise TypeError(f"gap must be an int, got {type(self.gap).__name__}")
        if self.gap < 0:
            raise ValueError(f"gap must be >= 0, got {self.gap}")
        _check_collection(self)

    def chrome(self) -> None:
        """None: no insets."""
        return None

    def lifts(self, ctx: object) -> bool:
        """Always False."""
        return False

    def _naturals_of(self, widths: "list[list[int]]", ctx: object) -> "tuple[int, ...]":
        """Each column's natural width over rows of cell widths (and its label, with
        a header)."""
        nat = []
        for j, column in enumerate(self.columns):
            best = _label_width(column, ctx) if self.header else 0
            for row in widths:
                if row[j] > best:
                    best = row[j]
            nat.append(best)
        return tuple(nat)

    def measure(self, axis: str, room: int, ctx: object, content: int = 0) -> int:
        """The gutter, the columns and their gaps; the header and the rows (see the module)."""
        _check_measure(axis, room, content)
        n = _count(self.rows, self.count)
        if axis == "y":
            return (1 if self.header else 0) + n
        items = [_table_row(fetch(self.rows, self.count, i)) for i in range(n)]
        if not self.columns:
            return 0
        k = len(self.columns)
        nat = self._naturals_of([[_width(it.cells[j]) if j < len(it.cells) else 0
                                  for j in range(k)] for it in items], ctx)
        return GUTTER + sum(_base(c, v) for c, v in zip(self.columns, nat)) + self.gap * (k - 1)

    def paint(self, rect: Rect, ctx: object, grid: Grid, clip: "Rect | None" = None
              ) -> "tuple[Hit, ...]":
        """The header, the rows in view, their marks and states, the indicator (see the module)."""
        begun = _begin(rect, grid, clip)
        if begun is None:
            return ()
        clip, area = begun
        g = ctx.ground()
        _ground(grid, area, g.style)
        R = rect
        hits = [] if self.id is None else [Hit(clip, self.id)]
        n = _count(self.rows, self.count)
        head = 1 if self.header and (R.h >= 2 or (R.h == 1 and n == 0)) else 0
        w = window(self.offset, n, R.h - head, follow=self.follow)
        items = [_table_row(fetch(self.rows, self.count, w.first + k)) for k in range(w.shown)]
        k_cols = len(self.columns)
        lines = [[_styled(it.cells[j], ctx, "text") if j < len(it.cells) else Line()
                  for j in range(k_cols)] for it in items]
        widths = [[_width(line) for line in row] for row in lines]
        W = fit(self.columns, self._naturals_of(widths, ctx), max(R.w - GUTTER, 0), self.gap)
        xs, x = [], R.x + GUTTER
        for wj in W:
            xs.append(x)
            x += wj + self.gap
        painter = RowPainter(ctx)
        if head:
            self._header(R, W, xs, ctx, painter, grid, area, clip, hits)
        f = _focus(self, ctx)
        for k, it in enumerate(items):
            i = w.first + k
            y = R.y + head + k
            if area.y <= y < area.bottom:
                pieces = []
                for j, wj in enumerate(W):
                    line, lw = lines[k][j], widths[k][j]
                    if lw > wj:
                        line = _fitted(line, wj, ctx)
                        lw = _width(line)
                    if lw:
                        pieces.append((xs[j] + _offset(wj - lw, self.columns[j].align), line, True))
                sel, hov, foc = _flags(self, ctx, i, it.id, it.state, i in self.selected, f)
                row(painter, grid, R, y, area, g.style, it.state, pieces,
                    selected=sel, hovered=hov, focused=foc)
            hit = painter.hit(R, y, clip, it.id, self.id, "row", i)
            if hit is not None:
                hits.append(hit)
        if n > R.h - head >= 1:
            y = R.y + R.h - 1
            _indicator(grid, R, y, area, ctx, w.above, w.below)
            if self.id is not None:
                hit = _hit(Rect(R.x, y, R.w, 1), clip, (self.id, "more"))
                if hit is not None:
                    hits.append(hit)
        _shade(grid, area, g.style)
        return tuple(hits)

    def _header(self, R: Rect, W: tuple, xs: list, ctx: object, painter: RowPainter,
                grid: Grid, area: Rect, clip: Rect, hits: list) -> None:
        """The header row: the labels, a hovered column's highlight, the dropped-column
        mark, and the header cells' hits."""
        y = R.y
        for j, wj in enumerate(W):
            column = self.columns[j]
            line = _fitted(_label(column, ctx), wj, ctx)
            _put(grid, xs[j] + _offset(wj - line.width, column.align), y, line, area)
            part = (self.id, "column", j) if self.id is not None else None
            if ctx.is_hovered(column.id) or (part is not None and ctx.is_hovered(part)):
                _restyle(grid, xs[j], xs[j] + wj, y, area, painter.apply("hover"))
            tag = column.id if column.id is not None else part
            if tag is not None:
                hit = _hit(Rect(xs[j], y, wj, 1), clip, tag)
                if hit is not None:
                    hits.append(hit)
        if len(W) < len(self.columns) and R.w > 0:
            mark = _plain(ctx.glyph("ellipsis"), ctx.style("muted"))
            mark = cut(mark, R.w) if mark.width > R.w else mark
            _put(grid, R.right - mark.width, y, mark, area)
