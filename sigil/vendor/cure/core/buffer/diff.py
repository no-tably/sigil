"""[Diff]: front against back: changed runs, coalesced.

Kind: service (data classes and a pure function over two {Grid}s).

What it does: compares the front buffer (what the terminal shows) with the back
buffer (the new frame) and returns the cells to send, as runs: stretches of one row,
left to right, each to be drawn from its first column on. [Display] turns them into
bytes.

Data (frozen dataclasses, stored as given):
- `Change(x: int, y: int, cells: tuple[Cell, ...])`: the back buffer's cells
  `back.get(x, y) ... back.get(x + len(cells) - 1, y)`.
- `Changes(items: tuple[Change, ...] = (), full: bool = False)`: the runs, sorted by
  `y` then `x`, never overlapping; `full` is true when the whole back buffer is sent
  (below). `bool(changes) == bool(items)`, `len(changes) == len(items)`, and
  iterating it iterates `items`.

The rules (`diff(front, back, *, gap=GAP)`):

1. Full. When `front` is `None` (nothing shown yet) or its size differs from `back`'s
   (a resize), the result is `full=True` with one `Change(0, y, back.row(y))` per row
   `y` of `back`, every row, in order (none when `back` has no columns or no rows).
2. Otherwise `full=False`, and on each row:
   a. A column `c` is changed when `front.get(c, y) != back.get(c, y)` (Cell `==`:
      glyph, width and style).
   b. Pairs are whole: when column `c` is changed and `back`'s cell there is a tail,
      `c - 1` is included too; when it is a head, `c + 1` is included too. So no run
      starts on a tail or ends on a head, and a wide glyph is always resent with its
      tail.
   c. Coalescing: the included columns are grouped into runs; two neighbouring groups
      separated by at most `gap` unincluded columns are joined into one run, those
      unchanged columns included (resending a few cells costs fewer bytes than a
      cursor move). With `gap=0` only adjacent columns join.
   d. Each run becomes `Change(first column, y, back's cells over the run)`.
   An identical pair of grids gives `Changes((), False)`: nothing to send.

So, for any front and back of one size, writing each change's cells into a copy of
`front` at (x, y) gives a grid `==` back.

Constants: `GAP = 4`, the default coalescing gap (a cursor move is at least six bytes;
four narrow cells in an unchanged style are four).

Inputs: `front`: a {Grid} or `None`; `back`: a {Grid} ({Pair}); `gap`: an int >= 0.
Outputs: {Changes}.
Errors: `TypeError` when `back` is not a `Grid`, `front` is neither a `Grid` nor
  `None`, or `gap` is not an `int` (a `bool` included); `ValueError` when `gap < 0`.
Effects: none (both grids are only read).

Usage:
    from cure.core.buffer.grid import Grid, put
    from cure.core.buffer.diff import diff
    a = put(Grid(10, 1), 0, 0, "hello")
    b = put(a.copy(), 0, 0, "J")
    diff(a, b).items             # (Change(0, 0, (Cell("J", 1, None),)),)
    put(b, 6, 0, "x")            # columns 0 and 6 differ, 5 unchanged columns between
    diff(a, b).items             # (Change(0, 0, (J,)), Change(6, 0, (x,))): 5 > GAP
    diff(a, b, gap=5).items      # (Change(0, 0, <b's cells 0..6>),): joined
    diff(None, a).full           # True: one Change per row, whole rows
"""

from dataclasses import dataclass

from cure.core.text import Cell

from .grid import Grid

GAP = 4


@dataclass(frozen=True)
class Change:
    """One run to send: the back buffer's `cells` from column `x` of row `y`."""

    x: int
    y: int
    cells: "tuple[Cell, ...]"


@dataclass(frozen=True)
class Changes:
    """{Changes}: the runs, by row then column; `full` for a whole-screen repaint."""

    items: "tuple[Change, ...]" = ()
    full: bool = False

    def __bool__(self) -> bool:
        return bool(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)


def diff(front: "Grid | None", back: Grid, *, gap: int = GAP) -> Changes:
    """The runs that turn `front` into `back`, by the rules above."""
    if not isinstance(back, Grid):
        raise TypeError(f"back must be a Grid, got {type(back).__name__}")
    if front is not None and not isinstance(front, Grid):
        raise TypeError(f"front must be a Grid or None, got {type(front).__name__}")
    if not isinstance(gap, int) or isinstance(gap, bool):
        raise TypeError(f"gap must be an int, got {type(gap).__name__}")
    if gap < 0:
        raise ValueError(f"gap must be >= 0, got {gap}")
    if front is None or front.size != back.size:
        rows = () if back.w == 0 else tuple(Change(0, y, back.row(y)) for y in range(back.h))
        return Changes(rows, True)
    items = []
    seen: dict = {}
    for y, (was, now) in enumerate(zip(front._rows, back._rows)):
        if _same(was, now, seen):
            continue                  # Speed: an equal row adds no Change; no column walk
        new = tuple(now)
        cols = _included(tuple(was), new)
        items.extend(Change(a, y, new[a:b]) for a, b in _runs(cols, gap))
    return Changes(tuple(items), False)


def _same(old: "list[Cell]", new: "list[Cell]", seen: dict) -> bool:
    """`old == new` (Cell `==`), rows of one length; `seen` keeps each pair of distinct
    style objects' `==` for the call, so a row's few styles are compared once each."""
    for was, now in zip(old, new):
        if was is now:
            continue
        if (was.__class__ is not Cell or now.__class__ is not Cell
                or was.glyph != now.glyph or was.width != now.width):
            if was != now:
                return False
            continue
        a, b = was.style, now.style
        if a is b:
            continue
        key = (id(a), id(b))          # both grids hold the styles: ids stay valid
        eq = seen.get(key)
        if eq is None:
            eq = seen[key] = a == b
        if not eq:
            return False
    return True


def _included(old: "tuple[Cell, ...]", new: "tuple[Cell, ...]") -> "list[int]":
    """The changed columns, each wide pair taken whole, in order."""
    cols = set()
    for c, (was, now) in enumerate(zip(old, new)):
        if was != now:
            cols.add(c)
            if now.width == 0:
                cols.add(c - 1)
            elif now.width == 2:
                cols.add(c + 1)
    return sorted(cols)


def _runs(cols: "list[int]", gap: int) -> "list[tuple[int, int]]":
    """Columns grouped into [start, end) runs, joined across at most `gap` others."""
    runs: list[tuple[int, int]] = []
    for c in cols:
        if runs and c - runs[-1][1] <= gap:
            runs[-1] = (runs[-1][0], c + 1)
        else:
            runs.append((c, c + 1))
    return runs
