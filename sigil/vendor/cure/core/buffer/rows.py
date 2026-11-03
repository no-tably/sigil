"""[Rows]: rows of (text, style) runs: --once, goldens.

Kind: service (a data class and pure functions between {Rows} and {Grid}).

What it does: holds the authoring and golden format (Rules carried over): a drawing as
rows, each a {Line} of `(text, style)` runs, the styles kept as they are, colours with
their theme roles. Sigil's views author in it, `--once` prints it, goldens store it,
and [Wire] packs it for the hosts. It converts both ways: `cells` lays rows into a
{Grid}, `runs` reads a grid back as rows, and `text` gives a grid's plain text.

Data (frozen dataclass):
- `Rows(lines: tuple[Line, ...] = ())`: one {Line} (Text's) per row, stored as
  given. `Rows.of(rows)` converts: `rows` is an iterable whose items are each a {Line}
  (kept), a `str` (`Line.of(s)`), or an iterable of parts that `Line.of` takes
  (`Span`s and `(text, style)` pairs), giving `Line.of(*parts)` (normal form). A
  `Rows` given to `Rows.of` is returned as is.
  - `runs` -> `tuple[tuple[tuple[str, style], ...], ...]`: each line's `Line.runs`
    (the golden data).
  - `plain` -> `tuple[str, ...]`: each line's plain text.
  - `width` -> int: the widest line in cells (`cure.core.text.width`), 0 for none.

Operations:
- `cells(rows, w=None, h=None) -> Grid`: a new grid, `w` defaulting to `rows.width`
  and `h` to the number of rows, all `BLANK`, then row `y` put at (0, y) with
  [Grid]'s `put` (Text's layout: wide glyphs and their tails, marks riding their
  base, controls as U+FFFD). Rows past `h` are not drawn, columns past `w` are cut
  (by `put`'s rules: a wide glyph that would straddle the edge leaves a blank).
  `rows` is a `Rows` or anything `Rows.of` takes.
- `runs(grid) -> Rows`: each grid row as a {Line} in normal form: the cells' glyphs
  in order (a tail adds nothing, so a wide glyph appears once), adjacent cells with
  `==` styles in one run, each run keeping its first cell's style object. Every row
  is kept whole, trailing blanks included, so for rows whose lines hold no control
  and start with no mark, each line `measure`-ing at most `w`:
  `runs(cells(rows, w, h)).lines[y] == merge(Line(lines[y].spans + (Span(pad),)))`
  with `pad` the `" "` columns up to `w` (style `None`), and blank lines for the rows
  past the given ones.
- `text(grid) -> str`: the plain text for snapshots: each row's glyphs joined (tails
  add nothing) with trailing U+0020 spaces stripped, the `h` rows joined by `"\\n"`
  (no trailing newline; `""` for a grid with no rows).

Inputs: `Rows.of` / `cells`: rows as above; `w`, `h`: ints >= 0 or `None`. `runs` /
  `text`: a {Grid}.
Outputs: `cells`: {Grid} (new). `runs`: {Rows}. `text`: {Text}, a `str`.
Errors: `TypeError` when `rows` (or one row, or a part of one) is none of the accepted
  types, a `str` included as `rows` itself, or when `grid` is not a `Grid`, or `w` /
  `h` is neither `None` nor an `int`; `ValueError` when `w < 0` or `h < 0`.
Effects: none.

Usage:
    from cure.core.buffer.rows import Rows, cells, runs, text
    bold = ...                                   # any Style
    r = Rows.of([[("name ", None), ("中文", bold)], "ok"])
    r.width                                      # 9
    g = cells(r)                                 # a 9 x 2 grid
    runs(g).runs[1]                              # (("ok       ", None),)
    text(g)                                      # "name 中文\\nok"
"""

from collections.abc import Iterable
from dataclasses import dataclass

from cure.core.text import Line, Span, width

from .cells import is_tail
from .grid import Grid, put


@dataclass(frozen=True)
class Rows:
    """{Rows}: one Text {Line} of (text, style) runs per row; `of` converts."""

    lines: "tuple[Line, ...]" = ()

    @classmethod
    def of(cls, rows: object) -> "Rows":
        """Rows from an iterable of Lines, strs, or iterables of Spans / (text, style) pairs."""
        if isinstance(rows, Rows):
            return rows
        if isinstance(rows, (str, bytes)) or not isinstance(rows, Iterable):
            raise TypeError(f"rows must be an iterable of rows, got {type(rows).__name__}")
        return cls(tuple(_line(row) for row in rows))

    @property
    def runs(self) -> "tuple[tuple[tuple[str, object], ...], ...]":
        """Each line's `(text, style)` runs."""
        return tuple(line.runs for line in self.lines)

    @property
    def plain(self) -> "tuple[str, ...]":
        """Each line's plain text."""
        return tuple(line.plain for line in self.lines)

    @property
    def width(self) -> int:
        """The widest line in cells (0 for no lines)."""
        return max((width(line.plain) for line in self.lines), default=0)


def cells(rows: "Rows | Iterable[object]", w: "int | None" = None, h: "int | None" = None) -> Grid:
    """A new grid with the rows put in, one per grid row (see the module)."""
    rows = Rows.of(rows)
    for name, value in (("w", w), ("h", h)):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
            raise TypeError(f"{name} must be None or an int, got {type(value).__name__}")
    grid = Grid(rows.width if w is None else w, len(rows.lines) if h is None else h)
    for y, line in enumerate(rows.lines[:grid.h]):
        put(grid, 0, y, line)
    return grid


def runs(grid: Grid) -> Rows:
    """The grid read back as rows of runs, every row whole (see the module)."""
    _grid(grid)
    return Rows(tuple(_read(grid.row(y)) for y in range(grid.h)))


def text(grid: Grid) -> str:
    """The grid's plain text: rows right-stripped of spaces, joined by newlines."""
    _grid(grid)
    return "\n".join("".join(c.glyph for c in grid.row(y)).rstrip(" ") for y in range(grid.h))


def _line(row: object) -> Line:
    if isinstance(row, Line):
        return row
    if isinstance(row, str):
        return Line.of(row)
    if isinstance(row, bytes) or not isinstance(row, Iterable):
        raise TypeError(f"a row must be a Line, str or iterable of parts, got {type(row).__name__}")
    return Line.of(*row)


def _read(row: tuple) -> Line:
    """One grid row as a Line in normal form; a tail adds nothing."""
    spans: list[Span] = []
    for cell in row:
        if is_tail(cell):
            continue
        if spans and spans[-1].style == cell.style:
            spans[-1] = Span(spans[-1].text + cell.glyph, spans[-1].style)
        else:
            spans.append(Span(cell.glyph, cell.style))
    return Line(tuple(spans))


def _grid(value: object) -> None:
    if not isinstance(value, Grid):
        raise TypeError(f"expected a Grid, got {type(value).__name__}")
