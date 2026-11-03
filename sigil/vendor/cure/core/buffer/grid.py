"""[Grid]: put, fill, blit, clip, shade.

Kind: service (a mutable data class and the functions that write into it).

What it does: holds a frame's cells, `w` columns by `h` rows, and writes into it. A
`Grid` is the one mutable value in Buffer: the painters put into it in place, cell by
cell, because rebuilding a whole frame per write would be too slow. Its state is
exactly its size and its cells; it has no cursor, no clip stack and no history.
Everything that must not see later writes takes a copy ([Display] keeps
`grid.copy()` as its front buffer).

Coordinates are 0-based: column `x` (0 at the left), row `y` (0 at the top).

A *region* is a rectangle of cells given as a 4-tuple of ints `(x, y, w, h)` or as
any object with int attributes `x`, `y`, `w`, `h` (a Geometry {Rect} serves; Buffer
does not import Geometry). It may lie partly or wholly outside the grid; only its
part inside the grid counts. `w < 0` or `h < 0` is a `ValueError`.

Invariant: no_orphan_half — a grid's rows are always well formed (see [Cells]): every
  cell is one [Cells]' `check` accepts in its column, so every head (width 2) stands
  at a column <= w - 2 and is followed by its tail with the same style, and every tail
  follows a head. Every writer checks what it brings in: `Grid(...)` and `fill` take
  only a narrow cell (below), `write` / `put` check their row with `check`, `blit` /
  `clip` copy rows of a `Grid` (well formed by this invariant), and `shade` changes
  only styles, a pair's two columns alike. No op below can break the pairs either:
  (1) when an op overwrites one column of a wide pair and not the other, the column
  it did not write becomes `blank(s)`, `s` the pair's style; (2) when an op would
  place a head whose tail falls outside the area it may write (past the grid, or
  outside `within` or the region), or a tail whose head falls outside it, it places
  `blank(s)` (in that cell's style) in the column it may write instead. A glyph is
  never split and never shifts what follows it.
  Law rows_well_formed: for every grid `g` that any sequence of the public ops below
  (`Grid(...)`, `copy`, `write`, `put`, `fill`, `blit`, `clip`, `shade`, and the ops of
  other modules built on them) can produce, and every `y` in `0..g.h - 1`,
  `check(g.row(y)) == g.row(y)` (it raises nothing); a proof drives random sequences
  of those ops, malformed arguments included (each refused one leaves the grid
  unchanged), and checks every row after each step.

A *narrow cell* (what `Grid(fill=)` and `fill` take) is a cell [Cells] calls narrow,
by [Cells]' rule, not by its width alone: exactly the `Cell`s for which
`check((cell,))` succeeds and `cell.width == 1`. That is: a `Cell` (or a subclass,
as `check` takes); its `width` an `int` equal to 1 and not a `bool` (`True` and `1.0`
are refused; an `int` subclass equal to 1 passes, as in `check`); its `glyph` a `str`
(as `check` takes it, `isinstance`) that is exactly one grapheme cluster
(`cure.core.text.cluster`) whose `cure.core.text.width` is 1. So `Cell("ab", 1)`,
`Cell("中", 1)`, `Cell("", 1)`, `Cell("\u0301", 1)` (a mark with no base) and
`Cell(b"a", 1)` are refused; `Cell("e\u0301", 1)` and a control glyph built by hand
(`Cell("\x01", 1)` or a lone surrogate `Cell("\\ud800", 1)`, which `check` passes and
[Display] draws as U+FFFD) are taken.
The checks run in this order, the first that fails raising: the type (`TypeError`
`expected a Cell, got <type name>`), then the width (`ValueError` `expected a narrow
cell (width 1), got width <repr>`), then the glyph (`ValueError` `expected a narrow
cell, got glyph <repr>: not one cluster of width 1`). The cell is checked whatever
the grid's size and the region: `Grid(0, 0, fill=c)` and `fill(g, (0, 0, 0, 0), c)`
refuse a malformed `c` as well.
The narrow check goes through [Cells]' public names only (`Cell`, `check`): the type,
then the width (an `int`, not a `bool`, equal to 1), then `check((cell,))` for the
glyph (its `ValueError` re-raised as the glyph message above). Grid imports nothing
private from `cells` (not `_narrow`): `check` already takes [Cells]' fast path for a
one-code-point glyph, and the narrow check runs once per `Grid(...)` / `fill` call,
never per cell, so the answers, the errors and their order are unchanged.

Data:
- `Grid(w, h, fill=BLANK)`: a `w` x `h` grid of `fill` (`w`, `h` ints >= 0; zero is
  allowed; `fill` a narrow cell, above). Checks in order: `w`'s type, `h`'s type,
  `w` / `h` >= 0, then `fill` (type, width, glyph).
  - `w`, `h` (read-only ints); `size == (w, h)`.
  - `get(x, y) -> Cell`: the cell at column `x`, row `y`.
  - `row(y) -> tuple[Cell, ...]`: row `y`, `w` cells.
  - `copy() -> Grid`: an independent grid with the same cells (cells are immutable,
    so no deeper copy is needed).
  - `==`: same size and every cell `==`. A `Grid` is unhashable (it is mutable).
  There is no setter: the module functions below are the only writers.

Operations (each writes into `grid` in place and returns that same grid, `is`, except
`clip`, which returns a new one):
- `write(grid, x, y, row, *, within=None) -> Grid`: lay a row of cells (any iterable;
  checked with [Cells]' `check`) on row `y` starting at column `x`, cell `i` at column
  `x + i`. Writes only columns inside the grid (and inside `within`, a region, when
  given) and nothing at all when row `y` is outside them. Pairs at the edges follow
  no_orphan_half (2); old pairs half overwritten follow (1).
- `put(grid, x, y, spans, style=None, *, within=None) -> Grid`:
  `write(grid, x, y, cells.line(spans, style), within=within)`: a `str` (one span in
  `style`), a {Line} or an iterable of `Span`, laid out by Text's rules. Columns that
  fall off the grid are cut, never wrapped (Painters fit text before they put it;
  overflow is their concern, [Cut] and the `↓N more` rule).
- `fill(grid, region=None, cell=BLANK) -> Grid`: every cell of the region (the whole
  grid when `None`) becomes `cell`, a narrow cell (above); pairs straddling the
  region's edges follow (1). Checks in order: `grid`'s type, the region (its type,
  then `w` / `h` >= 0), then `cell` (type, width, glyph); all before anything is
  written, so on an error the grid is unchanged.
- `blit(grid, src, x, y, *, within=None) -> Grid`: copy the `Grid` `src` with its
  top-left cell at (x, y): for each row `r` of `src`,
  `write(grid, x, y + r, src.row(r), within=within)`. `src` may be `grid` itself only
  as a copy (`blit(g, g.copy(), ...)`); `src is grid` is a `ValueError`.
- `clip(grid, region) -> Grid`: a NEW grid of the region's size holding the grid's
  cells under it, cells outside the grid `BLANK`, pairs cut by the region's edges
  broken by (2): exactly `blit(Grid(region.w, region.h), grid, -region.x, -region.y)`.
  `grid` is not changed.
- `shade(grid, region=None, *, bg=None, dim=False) -> Grid`: fold a ground or a dim
  under what is already drawn, over the region (whole grid when `None`), a wide pair
  with either column inside it shaded whole. With `bg` (a Style `Colour`): a cell
  whose style is `None` gets `Style(bg=bg)`, one whose style has `bg is None` gets
  `dataclasses.replace(style, bg=bg)`, and one that already has a background keeps
  it (the first writer wins: a ground never covers a highlight). With `dim=True`
  every cell's style gets `dim=True` (`None` becomes `Style(dim=True)`); this is
  [Layers]' dim backdrop. `bg=None, dim=False` changes nothing. Glyphs never change.

Inputs: `w`, `h`, `x`, `y`: ints (never `bool`); `row`: an iterable of {Cell};
  `spans`: as [Cells]' `line`; `style`: a style or `None`; `region` / `within`: a
  region; `cell`: a narrow {Cell} (by [Cells]' rule, above); `src`: a `Grid`; `bg`:
  a `Colour` or `None`; `dim`: a `bool`.
Outputs: {Grid}.
Errors: `Grid(...)`: `TypeError` when `w` / `h` is not an `int` (a `bool` included)
  or `fill` is not a `Cell`; `ValueError` when `w < 0`, `h < 0` or `fill` is not a
  narrow cell (its width, then its glyph; the messages above). `get` / `row`:
  `TypeError` for a non-int, `IndexError` outside the grid (no negative indexing).
  `write` / `put` / `fill` / `blit` / `clip` / `shade`: `TypeError` when `grid` or
  `src` is not a `Grid`, a coordinate is not an `int`, a region is neither a 4-tuple
  of ints nor an object with int `x`, `y`, `w`, `h`, `bg` is neither `None` nor a
  `Colour`, `dim` is not a `bool`, or (`shade`, when it has something to do) a cell's
  style is neither `None` nor a `Style`; `ValueError` for a region with `w < 0` or
  `h < 0`, a `cell` that is not a narrow cell (as `Grid`'s `fill`), `src is grid`,
  and as [Cells]' `check` / `line` for a malformed row (`write`) or a style given
  with spans (`put`). On an error the grid is unchanged.
Effects: only the stated in-place writes to the `grid` argument. No I/O.

Speed: `put` of printable-ASCII text and `write` / `blit` / `clip` of rows of
printable-ASCII or one-code-point glyphs take Text's and [Cells]' fast paths; every
row `write` / `put` is given is still checked in full before anything is written (so
on an error the grid is unchanged, and the error is the general path's; `blit` /
`clip` need not check a `Grid`'s rows at all, see Speed (F2)). `shade` may reuse one
shaded style for every cell whose style is `==` within one call (styles are compared
with `==`; which style object a cell holds is not part of the contract). Law
fast_equal: every operation above leaves the same grid (`==`), returns the same value
(`is` the grid, or for `clip` an `==` grid) and raises the same error class and
message as the general path (as of commit 26d0853), over random grids and rows mixing
ASCII, wide, marks, controls and malformed cells, and random regions and `within`s
partly or wholly off the grid. The budget is B3 (see [Buffer]).

Speed (F2): by rows_well_formed, every row of a `Grid` `src` already passes `check`
(and `check` of a well-formed row is that row as a tuple), so `blit` and `clip` may
lay `src`'s rows without checking them again: the check moved to the writers that
bring cells in (`write`, `put`, `fill`, `Grid(...)`). Law f2_equal: for every input
that involves no malformed fill cell, every operation above leaves the same grid
(`==`), returns the same value (`is` the grid, or for `clip` an `==` grid) and raises
the same error class and message as at commit fd3bc4b (a proof compares with a copy
of the module as of that commit, over the random grids, rows and regions of
fast_equal). The only inputs it accepted that are now refused are malformed fill
cells: `Grid(w, h, fill=c)` and `fill(grid, region, c)` with a `Cell` `c` whose width
is `== 1` but not narrow by [Cells]' rule (a width `True` or `1.0`; a width 1 with a
glyph that is not a `str`, is empty, holds more than one cluster, or is one cluster
of another width, such as `"ab"`, `"中"` or a lone mark), now a `ValueError` (the
messages above) at construction or fill time, the grid unchanged. Before, such a cell
was stored, and the error (`check`'s, naming a column) came only when a `blit` or
`clip` of that grid reached it, or never (a grid with no cells, an empty region, a
grid never blitted); that error at blit time can no longer happen.

Usage:
    from cure.core.text import Cell
    from cure.core.buffer.grid import Grid, put, fill, blit, clip, shade
    g = Grid(6, 2)
    put(g, 0, 0, "ab中")             # row 0: a b 中 <tail> ' ' ' '
    put(g, 3, 0, "x")               # overwrites the tail: column 2 becomes " "
    put(g, 5, 1, "中")               # no room for the tail: column 5 becomes " "
    fill(g, (0, 1, 2, 1), Cell("·", 1, None))
    clip(g, (1, 0, 2, 1)).row(0)     # (Cell("b", 1, None), Cell(" ", 1, None))
"""

import dataclasses
from collections.abc import Iterable, Sequence
from itertools import chain

from cure.core.style import Colour, Style
from cure.core.text import Cell, Line, Span

from .cells import BLANK, blank, check, line


class Grid:
    """{Grid}: `w` x `h` cells, mutable; written only by this module's functions."""

    __hash__ = None  # mutable: unhashable

    def __init__(self, w: int, h: int, fill: Cell = BLANK) -> None:
        _int(w, "w")
        _int(h, "h")
        if w < 0 or h < 0:
            raise ValueError(f"w and h must be >= 0, got {w}, {h}")
        _narrow(fill)
        self._w, self._h = w, h
        self._rows = [[fill] * w for _ in range(h)]

    @property
    def w(self) -> int:
        """Columns."""
        return self._w

    @property
    def h(self) -> int:
        """Rows."""
        return self._h

    @property
    def size(self) -> "tuple[int, int]":
        """`(w, h)`."""
        return (self._w, self._h)

    def get(self, x: int, y: int) -> Cell:
        """The cell at column `x`, row `y` (IndexError outside)."""
        _int(x, "x")
        _int(y, "y")
        if not (0 <= x < self._w and 0 <= y < self._h):
            raise IndexError(f"({x}, {y}) is outside a {self._w} x {self._h} grid")
        return self._rows[y][x]

    def row(self, y: int) -> "tuple[Cell, ...]":
        """Row `y` as a tuple of `w` cells (IndexError outside)."""
        _int(y, "y")
        if not 0 <= y < self._h:
            raise IndexError(f"row {y} is outside a grid of {self._h} rows")
        return tuple(self._rows[y])

    def copy(self) -> "Grid":
        """An independent grid with the same cells."""
        new = Grid(0, 0)
        new._w, new._h = self._w, self._h
        new._rows = [list(r) for r in self._rows]
        return new

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Grid):
            return NotImplemented
        return self.size == other.size and self._rows == other._rows

    def __repr__(self) -> str:
        return f"Grid({self._w}, {self._h})"


def write(grid: Grid, x: int, y: int, row: "Iterable[Cell]", *, within: object = None) -> Grid:
    """Lay a well-formed row of cells at (x, y), clipped, pairs kept whole (see the module)."""
    _grid(grid)
    _int(x, "x")
    _int(y, "y")
    area = _area(grid, within)
    cells = check(row)
    _lay(grid, x, y, cells, area)
    return grid


def _lay(grid: Grid, x: int, y: int, cells: "tuple[Cell, ...]",
         area: "tuple[int, int, int, int]") -> None:
    """`write`'s step after its checks: the checked `cells` at (x, y) inside `area`."""
    lo, hi, top, bottom = area
    if not (top <= y < bottom) or lo >= hi:
        return
    # The columns written are one run, a..b; only its first cell can be a cut tail and
    # only its last a cut head.
    a, b = max(lo, x), min(hi, x + len(cells))
    if a >= b:
        return
    run = cells[a - x:b - x]
    if run[0].width == 0 or run[-1].width == 2:
        run = list(run)
        if run[0].width == 0:
            run[0] = blank(run[0].style)
        if run[-1].width == 2:
            run[-1] = blank(run[-1].style)
    _place_run(grid._rows[y], a, run)


def put(grid: Grid, x: int, y: int, spans: "str | Line | Iterable[Span]", style: object = None,
        *, within: object = None) -> Grid:
    """Lay spans at (x, y): `write(grid, x, y, cells.line(spans, style), within=within)`."""
    _grid(grid)
    return write(grid, x, y, line(spans, style), within=within)


def fill(grid: Grid, region: object = None, cell: Cell = BLANK) -> Grid:
    """Every cell of `region` (the whole grid for None) becomes the narrow `cell`."""
    _grid(grid)
    lo, hi, top, bottom = _area(grid, region)
    _narrow(cell)
    if lo < hi:
        for y in range(top, bottom):
            _place_run(grid._rows[y], lo, [cell] * (hi - lo))
    return grid


def blit(grid: Grid, src: Grid, x: int, y: int, *, within: object = None) -> Grid:
    """Copy `src` in with its top-left at (x, y), row by row through `write`."""
    _grid(grid)
    _grid(src)
    if src is grid:
        raise ValueError("blit a copy of the grid into itself, not the grid")
    _int(x, "x")
    _int(y, "y")
    area = _area(grid, within)
    # Speed (F2): `src`'s rows are well formed (rows_well_formed), so each is laid as
    # `write` would lay it after its check, without the check.
    for r, row in enumerate(src._rows):
        _lay(grid, x, y + r, tuple(row), area)
    return grid


def clip(grid: Grid, region: object) -> Grid:
    """A new grid of the region: `blit(Grid(region.w, region.h), grid, -region.x, -region.y)`."""
    _grid(grid)
    x, y, w, h = _region(region)
    return blit(Grid(w, h), grid, -x, -y)


def shade(grid: Grid, region: object = None, *, bg: object = None, dim: bool = False) -> Grid:
    """Fold a ground (`bg`, first writer wins) and/or `dim` under the region's cells."""
    _grid(grid)
    lo, hi, top, bottom = _area(grid, region)
    if bg is not None and not isinstance(bg, Colour):
        raise TypeError(f"bg must be None or a Colour, got {type(bg).__name__}")
    if not isinstance(dim, bool):
        raise TypeError(f"dim must be a bool, got {type(dim).__name__}")
    if bg is None and not dim:
        return grid
    # Speed: one shaded style per `==` Style (or None), and one shaded cell per cell
    # object, within this call (`runs` keeps every cell and style referenced).
    styles: dict = {}                # a Style (or None) -> its shaded style
    by_id: dict = {}                 # id(style) -> its shaded style (styles stay referenced)
    made: dict = {}                  # id(cell) -> its shaded cell
    alike: dict = {}                 # (glyph, width, id(style)) -> its shaded cell

    def shaded(cell: Cell) -> None:
        style = cell.style
        key = None
        if cell.glyph.__class__ is str and cell.width.__class__ is int:
            key = (cell.glyph, cell.width, id(style))
            if key in alike:
                made[id(cell)] = alike[key]
                return
        if style is None or style.__class__ is Style:
            new = by_id.get(id(style))
            if new is None:
                new = styles.get(style)
                if new is None:
                    new = styles[style] = _shaded(style, bg, dim)
                by_id[id(style)] = new
        else:
            new = _shaded(style, bg, dim)
        made[id(cell)] = Cell(cell.glyph, cell.width, new)
        if key is not None:
            alike[key] = made[id(cell)]

    runs = []                        # (row, a, b, its cells a..b), every row read first
    if lo < hi:
        for y in range(top, bottom):
            row = grid._rows[y]
            a = lo - 1 if row[lo].width == 0 else lo       # a pair at either edge whole
            b = hi + 1 if row[hi - 1].width == 2 else hi
            runs.append((row, a, b, row[a:b]))
    every = list(chain.from_iterable(run[3] for run in runs))
    for cell in dict(zip(map(id, every), every)).values():   # each object once, in order
        shaded(cell)
    for row, a, b, cells in runs:
        row[a:b] = map(made.__getitem__, map(id, cells))
    return grid


def _shaded(style: object, bg: "Colour | None", dim: bool) -> Style:
    if style is None:
        style = Style()
    elif not isinstance(style, Style):
        raise TypeError(f"a cell's style must be None or a Style, got {type(style).__name__}")
    if bg is not None and style.bg is None:
        style = dataclasses.replace(style, bg=bg)
    if dim and not style.dim:
        style = dataclasses.replace(style, dim=True)
    return style


def _place_run(row: "list[Cell]", a: int, run: "Sequence[Cell]") -> None:
    """Write a run of cells into a row from column `a`; a pair half overwritten leaves a
    blank in its style. Only the run's ends can break a pair: a head at its last column
    loses its tail after the run, a tail at its first column its head before it."""
    b = a + len(run)
    first, last = row[a], row[b - 1]
    row[a:b] = run
    if last.width == 2:
        row[b] = blank(last.style)
    if first.width == 0:
        row[a - 1] = blank(first.style)


def _area(grid: Grid, region: object) -> "tuple[int, int, int, int]":
    """The columns lo..hi and rows top..bottom of `region` inside `grid` (all of it for None)."""
    gw, gh = grid._w, grid._h
    if region is None:
        return 0, gw, 0, gh
    x, y, w, h = _region(region)
    r, b = x + w, y + h
    return (x if x > 0 else 0), (r if r < gw else gw), (y if y > 0 else 0), (b if b < gh else gh)


def _region(region: object) -> "tuple[int, int, int, int]":
    if isinstance(region, tuple):
        if len(region) != 4:
            raise TypeError(f"a region tuple has 4 ints, got {len(region)} items")
        parts = region
    else:
        try:
            parts = (region.x, region.y, region.w, region.h)
        except AttributeError:
            raise TypeError(f"a region is (x, y, w, h) or has x, y, w, h, got {type(region).__name__}") from None
    x, y, w, h = parts
    # Speed: the error names are built only when a part is not exactly an int.
    if not (x.__class__ is int and y.__class__ is int and w.__class__ is int
            and h.__class__ is int):
        for name, value in zip("xywh", parts):
            _int(value, f"region {name}")
    if parts[2] < 0 or parts[3] < 0:
        raise ValueError(f"a region's w and h must be >= 0, got {parts[2]}, {parts[3]}")
    return parts


def _grid(value: object) -> None:
    if value.__class__ is Grid:
        return
    if not isinstance(value, Grid):
        raise TypeError(f"expected a Grid, got {type(value).__name__}")


def _narrow(cell: object) -> None:
    """A narrow cell by [Cells]' rule (`check((cell,))` passes and its width is 1), in
    the module's order: the type, then the width, then the glyph. Contract (Q9a): no
    `_narrow_cell` fast path; the glyph is checked by Cells' public `check` alone (see
    the module)."""
    if not isinstance(cell, Cell):
        raise TypeError(f"expected a Cell, got {type(cell).__name__}")
    w = cell.width
    if not isinstance(w, int) or isinstance(w, bool) or w != 1:
        raise ValueError(f"expected a narrow cell (width 1), got width {w!r}")
    try:
        check((cell,))
    except ValueError:
        raise ValueError(f"expected a narrow cell, got glyph {cell.glyph!r}: "
                         "not one cluster of width 1") from None


def _int(value: object, name: str) -> None:
    if value.__class__ is int:
        return
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
