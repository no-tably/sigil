"""[Whitespace]: fit a panel into a drawing's empty corner (occupancy sums).

Kind: service (a pure search over an `Occupancy`, a frozen dataclass of 2-D prefix
sums). Ported from sigil's viewer (`kit._occupancy`, `kit._empty_spot`), generalised
to the four corners and to any occupancy source: where a side panel (a legend, a
callout) can sit over a drawing without covering anything drawn. What counts as drawn
is the caller's: Whitespace sees only an occupancy grid, never text (so a wide
character's two columns are the caller's to mark).

Occupancy. The grid's cells, row by row: `Occupancy.of(rows)` takes an iterable of
rows, each an iterable of cells, a cell occupied when `bool(cell)` is true; the grid
is `height = len(rows)` rows by `width = ` the longest row's length, a short row's
missing cells empty. A `str` row is a `TypeError` (pass `[c != " " for c in line]`:
one cell per column is the caller's call). `Occupancy.scan(occupied, width, height)`
calls `occupied(x, y)` once for every cell, row by row (y outer, x inner, both
ascending), a cell occupied when the result is truthy. Either way the grid's
coordinates start at (0, 0); `sums` holds the `(height + 1) x (width + 1)` prefix sums,
`sums[y][x]` the occupied cells in `Rect(0, 0, x, y)`.
- `count(rect) -> int`: the occupied cells in `rect`, clipped to the grid (cells
  outside it are empty), in O(1).
- `empty(rect) -> bool`: `count(rect) == 0`.

`fit(w, h, occupancy, *, corner="top-left", clearance=(1, 2)) -> Rect | None`: where a
`w` x `h` panel fits in the corner's quarter of the grid with a blank clearance all
round. `None` when `w > width` or `h > height`, or when no position qualifies.
- A position (x, y) qualifies when `count(Rect(x - cx, y - cy, w + 2 * cx, h + 2 *
  cy)) == 0` with `(cy, cx) = clearance` (rows, columns): the panel and its clearance,
  clipped to the grid, cover nothing drawn. The grid's edge needs no clearance.
- The corner's quarter: with `X = width - w` and `Y = height - h`, a top corner tries
  y from 0 up to `Y // 2`, a bottom corner y from `Y` down to `(Y + 1) // 2`; a left
  corner x from 0 up to `X // 2`, a right corner x from `X` down to `(X + 1) // 2`.
- The order, the tie-break: rows first (y in the corner's order, outer loop), then x
  in the corner's order: the position nearest the corner's row wins, then the one
  nearest its column. So "top-left" is topmost, then leftmost; "bottom-right"
  bottommost, then rightmost (sigil's "tl" and "br").
`CORNERS` are "top-left", "top-right", "bottom-left", "bottom-right".

Inputs: `rows` an iterable of iterables; `occupied` a callable `(x, y) -> truthy`;
  `width`, `height`: ints >= 0; `w`, `h`: ints >= 1; `rect` a {Rect}; `corner` one of
  `CORNERS`; `clearance` a pair of ints >= 0.
Outputs: an `Occupancy`; an int; a bool; a `Rect` in grid coordinates (the caller
  moves it onto the screen) or `None`.
Errors: `TypeError` when a row is a `str` or not iterable, `rect` is not a `Rect`,
  `occupied` is not callable, or a size or clearance is not an int (a `bool`
  included); `ValueError` when `w` or `h` is below 1, `width`, `height` or a clearance
  is negative, `clearance` is not a pair, or `corner` is unknown. Assigning a field
  raises `dataclasses.FrozenInstanceError`.
Effects: none (beyond calling `occupied`).

Usage:
    from cure.core.geometry import Rect
    from cure.draw.layout.whitespace import Occupancy, fit
    occ = Occupancy.of([[1, 1, 0, 0, 0, 0, 0, 0],
                        [1, 1, 0, 0, 0, 0, 0, 0],
                        [0] * 8,
                        [0] * 8])
    occ.width, occ.height                       # 8, 4
    occ.count(Rect(0, 0, 2, 2))                 # 4
    occ.count(Rect(-5, -5, 100, 100))           # 4: clipped to the grid
    fit(2, 1, occ, corner="top-right")          # Rect(6, 0, 2, 1)
    fit(2, 1, occ, corner="top-left")           # None: the drawing is in the way
    fit(2, 1, occ, corner="top-left", clearance=(0, 0))   # Rect(2, 0, 2, 1)
    fit(9, 1, occ)                              # None: wider than the grid
    Occupancy.scan(lambda x, y: x == y, 3, 3).count(Rect(0, 0, 3, 3))   # 3
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from cure.core.geometry import Rect

CORNERS = ("top-left", "top-right", "bottom-left", "bottom-right")


@dataclass(frozen=True)
class Occupancy:
    """A grid's occupied cells as 2-D prefix sums: `sums[y][x]` counts Rect(0, 0, x, y)."""

    width: int
    height: int
    sums: tuple

    @classmethod
    def of(cls, rows: Iterable) -> "Occupancy":
        """The occupancy of rows of cells (a cell occupied when truthy)."""
        grid = []
        for line in rows:
            if isinstance(line, str):
                raise TypeError("a row must be an iterable of cells, not a str")
            try:
                grid.append([bool(cell) for cell in line])
            except TypeError:
                raise TypeError(f"a row must be iterable, got {type(line).__name__}") from None
        width = max((len(line) for line in grid), default=0)
        return cls(width, len(grid), _prefix(grid, width))

    @classmethod
    def scan(cls, occupied: "Callable[[int, int], object]", width: int, height: int
             ) -> "Occupancy":
        """The occupancy of a `width` x `height` grid, asking `occupied(x, y)` per cell."""
        if not callable(occupied):
            raise TypeError(f"occupied must be callable, got {type(occupied).__name__}")
        _size(width, 0, "width")
        _size(height, 0, "height")
        grid = [[bool(occupied(x, y)) for x in range(width)] for y in range(height)]
        return cls(width, height, _prefix(grid, width))

    def count(self, rect: Rect) -> int:
        """The occupied cells in `rect`, clipped to the grid."""
        if not isinstance(rect, Rect):
            raise TypeError(f"rect must be a Rect, got {type(rect).__name__}")
        x0, x1 = max(rect.x, 0), min(rect.right, self.width)
        y0, y1 = max(rect.y, 0), min(rect.bottom, self.height)
        if x1 <= x0 or y1 <= y0:
            return 0
        s = self.sums
        return s[y1][x1] - s[y0][x1] - s[y1][x0] + s[y0][x0]

    def empty(self, rect: Rect) -> bool:
        """True when nothing in `rect` is occupied."""
        return self.count(rect) == 0


def fit(w: int, h: int, occupancy: Occupancy, *, corner: str = "top-left",
        clearance: "tuple[int, int]" = (1, 2)) -> "Rect | None":
    """Where a `w` x `h` panel fits blank in `corner`'s quarter, or None."""
    _size(w, 1, "w")
    _size(h, 1, "h")
    if corner not in CORNERS:
        raise ValueError(f"corner must be one of {CORNERS}, got {corner!r}")
    if not isinstance(clearance, tuple) or len(clearance) != 2:
        raise ValueError(f"clearance must be a pair of ints, got {clearance!r}")
    cy, cx = clearance
    _size(cy, 0, "clearance")
    _size(cx, 0, "clearance")
    if w > occupancy.width or h > occupancy.height:
        return None
    span_x, span_y = occupancy.width - w, occupancy.height - h
    ys = range(span_y // 2 + 1) if corner.startswith("top") else range(span_y, (span_y + 1) // 2 - 1, -1)
    xs = range(span_x // 2 + 1) if corner.endswith("left") else range(span_x, (span_x + 1) // 2 - 1, -1)
    for y in ys:
        for x in xs:
            if occupancy.empty(Rect(x - cx, y - cy, w + 2 * cx, h + 2 * cy)):
                return Rect(x, y, w, h)
    return None


def _size(value: object, low: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if value < low:
        raise ValueError(f"{name} must be >= {low}, got {value}")


def _prefix(grid: list, width: int) -> tuple:
    """The `(height + 1) x (width + 1)` prefix sums of a grid of bools (short rows empty)."""
    sums = [(0,) * (width + 1)]
    for line in grid:
        run, above, out = 0, sums[-1], [0]
        for x in range(width):
            run += 1 if x < len(line) and line[x] else 0
            out.append(above[x + 1] + run)
        sums.append(tuple(out))
    return tuple(sums)
