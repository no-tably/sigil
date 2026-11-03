"""[Flex]: rows, columns, grids, stacks; gaps, align.

Kind: service (pure functions from constraints and a {Rect} to {Rects}; the layout
values `Row`, `Column`, `Grid`, `Stack` are frozen dataclasses, checked on
construction, that `lay` reads off a node). Flex provides `row` on top of [Solver]:
the main-axis sizes are always `solve`'s, and Flex only places them.

Terms. A row's main axis is x (children side by side, left to right) and its cross
axis is y; a column's main axis is y (stacked, top to bottom) and its cross axis x.
`main` and `cross` are the rect's extents on those axes (`rect.w`, `rect.h` for a row).

The measure. Every function here that may need a natural size takes
`measure(index, axis, room) -> int`: the natural size of item `index` along `axis`
("x": its width, "y": its height) given `room` cells on the other axis (so text can
answer height-for-width). Flex calls it only when told to: for an `Auto` constraint,
and for a cross size when `align` is not "stretch".

Operations:
- `row(constraints, rect, *, gap=0, justify="start", align="stretch", measure=None)
  -> tuple[Rect, ...]`, one rect per constraint, in order:
  1. Main sizes: `sizes = solve(constraints, main, gap=gap, measure=...)`, an `Auto`
     item i measured as `measure(i, "x", cross)`.
  2. Gaps: `g = gaps(len(constraints), gap, main)`. The leftover is
     `L = main - sum(sizes) - sum(g)` (0 whenever a Fill or Min takes the spare).
  3. `justify` places the leftover along the main axis:
     "start": all of it after the last item; "end": all before the first;
     "centre" (or "center"): `L // 2` before the first, the rest after the last;
     "between": `apportion(L, (1,) * (n - 1))` added to the gaps in order (earlier
     gaps first on a tie; with one item it is "start");
     "evenly": `apportion(L, (1,) * (n + 1))` as n + 1 slots: before the first item,
     between each pair (added to the gap), after the last.
     Item i's main start is `rect.x` + the slots and items before it.
  4. `align` places each item on the cross axis: "stretch": the whole cross extent;
     otherwise its cross size is `c_i = min(cross, measure(i, "y", sizes[i]))`, at
     the cross start ("start"), `cross - c_i` in ("end"), or `(cross - c_i) // 2` in
     ("centre" or "center").
- `column(...)`: the same with the axes swapped (main y, cross x; an `Auto` item
  measured as `measure(i, "y", cross)`, a cross size as `measure(i, "x", sizes[i])`).
- `grid(columns, rows, rect, *, gap_x=0, gap_y=0, measure=None)
  -> tuple[tuple[Rect, ...], ...]`: two 1-D solves: column widths
  `solve(columns, rect.w, gap=gap_x)` (an `Auto` column j measured as
  `measure(j, "x", rect.h)`), row heights `solve(rows, rect.h, gap=gap_y)` (an `Auto`
  row i as `measure(i, "y", rect.w)`); always placed from the top-left ("start"),
  the gaps by `gaps`. The result is row-major: `result[i][j]` is the cell of row i,
  column j. No spans: a spanning cell is the union of its cells, which the caller
  builds from these rects.
- `stack(count, rect) -> tuple[Rect, ...]`: `count` copies of `rect` (children on top
  of each other, later ones drawn above).

Layout values (what `lay` reads from a node's `layout`; each child's own `size`, a
constraint, is its main-axis constraint):
- `Row(gap=0, justify="start", align="stretch")`, `Column(gap=0, justify="start",
  align="stretch")`: the children laid out by `row` / `column` in the content rect.
- `Grid(columns, rows=None, gap_x=0, gap_y=0)`: `columns` a non-empty tuple of
  constraints, `rows` a tuple of constraints or `None` (as many `Fill(1)` rows as the
  children need: `ceil(len(children) / len(columns))`). Children fill the cells
  row-major; the children's own `size` is not used. Iterables are stored as tuples.
- `Stack()`: every child gets the whole content rect.
`JUSTIFY` and `ALIGN` are the accepted names.

Laws:
- Every rect lies inside `rect` (x >= rect.x, right <= rect.right, the same on y).
- Along the main axis the rects are in order and do not overlap; their main sizes are
  exactly `solve`'s; with "start" the gaps between them are exactly `gaps`'s.
- With `align="stretch"` every rect spans the whole cross extent.
- `row(cs, r.moved(dx, dy), ...)` is `row(cs, r, ...)` with every rect moved by
  `(dx, dy)` (the same for `column`, `grid`, `stack`).

Inputs: `constraints`, `columns`, `rows`: iterables of [Solver]'s constraint values;
  `rect` a {Rect}; `gap`, `gap_x`, `gap_y`, `count`: ints >= 0; `justify` one of
  `JUSTIFY`; `align` one of `ALIGN`; `measure` `None` or a callable as above.
Outputs: {Rects}: a tuple of `Rect` (a tuple of tuples for `grid`).
Errors: `TypeError` when `rect` is not a `Rect`, a constraint is not a constraint
  value, a gap or `count` is not an int (a `bool` included), or `measure` returns a
  non-int; `ValueError` when a gap or `count` is negative, `justify` or `align` is
  unknown, `measure` returns a negative int, or `measure` is needed (an `Auto`
  constraint, or `align` other than "stretch") and is `None`; a `Grid` with no
  columns is a `ValueError`. As `solve` otherwise.
Effects: none (beyond calling `measure`).

Usage:
    from cure.core.geometry import Rect
    from cure.draw.layout.solver import Fixed, Fill
    from cure.draw.layout.flex import row, column, grid, stack
    row([Fixed(3), Fill(1)], Rect(0, 0, 10, 2))
    #   (Rect(0, 0, 3, 2), Rect(3, 0, 7, 2))
    row([Fixed(2), Fixed(2)], Rect(0, 0, 10, 1), gap=1, justify="centre")
    #   (Rect(2, 0, 2, 1), Rect(5, 0, 2, 1))
    row([Fixed(2)] * 3, Rect(0, 0, 10, 1), justify="between")
    #   (Rect(0, 0, 2, 1), Rect(4, 0, 2, 1), Rect(8, 0, 2, 1))
    row([Fixed(2)] * 2, Rect(0, 0, 10, 1), justify="evenly")
    #   (Rect(2, 0, 2, 1), Rect(6, 0, 2, 1))
    row([Fixed(4)], Rect(0, 0, 4, 5), align="centre", measure=lambda i, axis, room: 2)
    #   (Rect(0, 1, 4, 2),)
    column([Fixed(1), Fill(1)], Rect(0, 0, 8, 5), gap=1)
    #   (Rect(0, 0, 8, 1), Rect(0, 2, 8, 3))
    grid([Fill(1)] * 2, [Fixed(1)] * 2, Rect(0, 0, 10, 3))
    #   ((Rect(0, 0, 5, 1), Rect(5, 0, 5, 1)), (Rect(0, 1, 5, 1), Rect(5, 1, 5, 1)))
    stack(2, Rect(1, 1, 3, 3))                      # (Rect(1, 1, 3, 3), Rect(1, 1, 3, 3))
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from cure.core.geometry import Rect

from .solver import Constraint, apportion, gaps, solve

JUSTIFY = ("start", "centre", "center", "end", "between", "evenly")
ALIGN = ("stretch", "start", "centre", "center", "end")


def _gap(value: object, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{name} must be >= 0, got {value}")


def _constraints(values: Iterable, name: str) -> tuple:
    out = tuple(values)
    for value in out:
        if not isinstance(value, Constraint):
            raise TypeError(f"{name} must hold constraint values, got {type(value).__name__}")
    return out


def _flow(self) -> None:
    _gap(self.gap, "gap")
    if self.justify not in JUSTIFY:
        raise ValueError(f"justify must be one of {JUSTIFY}, got {self.justify!r}")
    if self.align not in ALIGN:
        raise ValueError(f"align must be one of {ALIGN}, got {self.align!r}")


@dataclass(frozen=True)
class Row:
    """Children side by side, by `row`."""

    gap: int = 0
    justify: str = "start"
    align: str = "stretch"

    def __post_init__(self) -> None:
        _flow(self)


@dataclass(frozen=True)
class Column:
    """Children stacked top to bottom, by `column`."""

    gap: int = 0
    justify: str = "start"
    align: str = "stretch"

    def __post_init__(self) -> None:
        _flow(self)


@dataclass(frozen=True)
class Grid:
    """Children in cells, row-major, by `grid`; `rows=None`: Fill(1) rows as needed."""

    columns: tuple
    rows: "tuple | None" = None
    gap_x: int = 0
    gap_y: int = 0

    def __post_init__(self) -> None:
        columns = _constraints(self.columns, "columns")
        if not columns:
            raise ValueError("a Grid needs at least one column")
        object.__setattr__(self, "columns", columns)
        if self.rows is not None:
            object.__setattr__(self, "rows", _constraints(self.rows, "rows"))
        _gap(self.gap_x, "gap_x")
        _gap(self.gap_y, "gap_y")


@dataclass(frozen=True)
class Stack:
    """Every child gets the whole content rect (later ones drawn above)."""


def row(constraints: Iterable, rect: Rect, *, gap: int = 0, justify: str = "start",
        align: str = "stretch", measure: "Callable[[int, str, int], int] | None" = None
        ) -> tuple[Rect, ...]:
    """The rects of items side by side in `rect` (main axis x), by the rules above."""
    return _flow_rects(constraints, rect, "x", gap, justify, align, measure)


def column(constraints: Iterable, rect: Rect, *, gap: int = 0, justify: str = "start",
           align: str = "stretch", measure: "Callable[[int, str, int], int] | None" = None
           ) -> tuple[Rect, ...]:
    """The rects of items stacked in `rect` (main axis y), by the rules above."""
    return _flow_rects(constraints, rect, "y", gap, justify, align, measure)


def grid(columns: Iterable, rows: Iterable, rect: Rect, *, gap_x: int = 0, gap_y: int = 0,
         measure: "Callable[[int, str, int], int] | None" = None
         ) -> tuple[tuple[Rect, ...], ...]:
    """The cells of a grid in `rect`, row-major (`result[row][column]`)."""
    _rect(rect)
    columns = _constraints(columns, "columns")
    rows = _constraints(rows, "rows")
    _gap(gap_x, "gap_x")
    _gap(gap_y, "gap_y")
    widths = solve(columns, rect.w, gap=gap_x, measure=_along(measure, "x", rect.h))
    heights = solve(rows, rect.h, gap=gap_y, measure=_along(measure, "y", rect.w))
    xs = _starts(rect.x, widths, gaps(len(widths), gap_x, rect.w))
    ys = _starts(rect.y, heights, gaps(len(heights), gap_y, rect.h))
    return tuple(tuple(Rect(x, y, w, h) for x, w in zip(xs, widths))
                 for y, h in zip(ys, heights))


def stack(count: int, rect: Rect) -> tuple[Rect, ...]:
    """`count` copies of `rect`."""
    _gap(count, "count")
    _rect(rect)
    return (rect,) * count


def _rect(rect: object) -> None:
    if not isinstance(rect, Rect):
        raise TypeError(f"rect must be a Rect, got {type(rect).__name__}")


def _measured(measure: "Callable[[int, str, int], int]", i: int, axis: str, room: int) -> int:
    value = measure(i, axis, room)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"measure must return an int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"measure must return an int >= 0, got {value}")
    return value


def _along(measure: "Callable | None", axis: str, room: int) -> "Callable[[int], int] | None":
    """The solver's one-argument measure for `axis` given `room` (None stays None)."""
    if measure is None:
        return None
    return lambda i: measure(i, axis, room)


def _starts(origin: int, sizes: tuple, between: tuple, before: int = 0) -> list:
    """Each item's start along an axis: `origin`, then `before`, items and `between`s."""
    out, at = [], origin + before
    for i, size in enumerate(sizes):
        out.append(at)
        at += size + (between[i] if i < len(between) else 0)
    return out


def _justified(n: int, leftover: int, between: tuple, justify: str) -> "tuple[int, tuple]":
    """The cells before the first item and the widened gaps, by `justify`."""
    if justify == "end":
        return leftover, between
    if justify in ("centre", "center"):
        return leftover // 2, between
    if justify == "between" and n > 1:
        extra = apportion(leftover, (1,) * (n - 1))
        return 0, tuple(g + e for g, e in zip(between, extra))
    if justify == "evenly" and n > 0:
        slots = apportion(leftover, (1,) * (n + 1))
        return slots[0], tuple(g + e for g, e in zip(between, slots[1:n]))
    return 0, between


def _cross(i: int, size: int, cross: int, align: str, cross_axis: str,
           measure: "Callable") -> "tuple[int, int]":
    """Item i's offset into the cross extent and its cross size, by `align`."""
    if align == "stretch":
        return 0, cross
    extent = min(cross, _measured(measure, i, cross_axis, size))
    if align == "end":
        return cross - extent, extent
    if align in ("centre", "center"):
        return (cross - extent) // 2, extent
    return 0, extent


def _flow_rects(constraints: Iterable, rect: Rect, axis: str, gap: int, justify: str,
                align: str, measure: "Callable | None") -> tuple[Rect, ...]:
    """`row` (axis "x") or `column` (axis "y")."""
    _rect(rect)
    items = _constraints(constraints, "constraints")
    _gap(gap, "gap")
    if justify not in JUSTIFY:
        raise ValueError(f"justify must be one of {JUSTIFY}, got {justify!r}")
    if align not in ALIGN:
        raise ValueError(f"align must be one of {ALIGN}, got {align!r}")
    if align != "stretch" and measure is None and items:
        raise ValueError(f"align={align!r} needs a measure")
    cross_axis = "y" if axis == "x" else "x"
    main, cross = (rect.w, rect.h) if axis == "x" else (rect.h, rect.w)
    sizes = solve(items, main, gap=gap, measure=_along(measure, axis, cross))
    between = gaps(len(items), gap, main)
    leftover = main - sum(sizes) - sum(between)
    before, between = _justified(len(items), leftover, between, justify)
    m0, c0 = (rect.x, rect.y) if axis == "x" else (rect.y, rect.x)
    out = []
    for i, (start, size) in enumerate(zip(_starts(m0, sizes, between, before), sizes)):
        offset, extent = _cross(i, size, cross, align, cross_axis, measure)
        if axis == "x":
            out.append(Rect(start, c0 + offset, size, extent))
        else:
            out.append(Rect(c0 + offset, start, extent, size))
    return tuple(out)
