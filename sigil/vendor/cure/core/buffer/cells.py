"""[Cells]: the cell substrate every frame lands on: glyph, style, width; a wide glyph +
its tail; marks ride their base.

Kind: service (constants and pure functions over Text's `Cell`).

What it does: fixes the cell model every Buffer op shares. A cell is Text's {Cell}
(`cure.core.text.Cell(glyph, width, style)`, re-exported here as `Cell`; the same
class, not a copy), one per terminal column:

- a narrow cell: `width == 1`, `glyph` exactly one grapheme cluster of width 1;
- a wide glyph takes two columns: its head `width == 2` (the cluster) and, in the
  next column, its tail `Cell("", 0, style)`, with the head's own `style` (`==`);
- a tail is the only cell of width 0 or with an empty glyph. Combining marks and
  other zero-width code points are never cells of their own: they ride their base,
  inside the base's glyph (`"e\\u0301"` is one narrow cell); a mark with no base
  before it is dropped (Text's `put` rule).
- `style` is a Style {Style} (`cure.core.style.Style`) or `None` (plain). Buffer
  stores it as given and compares it with `==`; [Display] and [Wire] read it.

So a row of cells is *well formed* when: every cell is a `Cell`; every width is 0, 1
or 2; every narrow or head cell's glyph is exactly one grapheme cluster
(`cure.core.text.cluster`) whose `cure.core.text.width` equals its width; every head
is followed directly by a tail with an `==` style; every tail directly follows a
head. (`check` below tests exactly this.) A glyph may still hold a control code point
or a lone surrogate (U+D800..U+DFFF; Text's `width` gives either 1, and a lone one is
a cluster of its own) when a caller built the cell by hand (`Cell("\\ud800", 1,
None)`); `check` accepts it, as it is well formed by the rules above, and [Display]
never emits one (it draws U+FFFD, so its bytes are always strict UTF-8). Text's
`cell` / `put`, and so `glyph` and `line`, never make one.

Constants and functions:
- `BLANK`: `Cell(" ", 1, None)`, the empty cell a new grid is filled with.
- `blank(style=None) -> Cell`: `Cell(" ", 1, style)`, the cell a broken wide pair
  leaves behind (in the pair's style, so a background stays unbroken).
- `tail(style=None) -> Cell`: `Cell("", 0, style)`.
- `is_tail(cell) -> bool`: `cell.width == 0`. `is_wide(cell) -> bool`:
  `cell.width == 2`.
- `glyph(char, style=None) -> Cell`: one grapheme cluster as a cell, exactly
  `cure.core.text.cell(char, style)` (a control cluster becomes U+FFFD; a wide one is
  a head, which needs its tail after it in a row).
- `line(spans, style=None) -> tuple[Cell, ...]`: a line laid out one cell per column,
  exactly `cure.core.text.put(...)`: `spans` is a `str` (taken as one span in
  `style`), a {Line}, or an iterable of `Span`. The result is always well formed.
- `check(row) -> tuple[Cell, ...]`: `row` (any iterable of cells) as a tuple when it
  is well formed (above); otherwise an error.

Inputs: `glyph`: a `str` of one cluster and an optional style. `line`: a `str`,
  {Line} or iterable of `Span`, and `style`. `check`: an iterable of {Cell}.
Outputs: {Cell}, or a tuple of {Cell} (one per column).
Errors: `glyph`: as `cure.core.text.cell` (`TypeError`, `ValueError`). `line`:
  `TypeError` when `spans` is none of the accepted types; `ValueError` when `style`
  is not `None` and `spans` is not a `str` (a style given for spans that carry their
  own). `check`: `TypeError` when `row` is not iterable or an item is not a `Cell`;
  `ValueError` naming the first column that breaks a rule above (a width outside
  0..2, a glyph that is not one cluster of its width, a head without its tail at the
  end of the row or before a non-tail, a tail whose style differs from its head's,
  an orphan tail).
Effects: none.

Speed: `check` is on every write, blit and compose, so it has a fast path. A cell
whose `width` is an `int` 1 (not a `bool`) and whose glyph is a `str` (exactly) of one
printable-ASCII code point (U+0020..U+007E) is one cluster of width 1, so `check` may
pass its glyph without `cluster` or `width`. It may also check a glyph of one code
point that is not ASCII by its width alone, without `cluster` (one code point is
always one cluster; `cure.core.text.width` of it is 1 for a control and the table's
`point` otherwise, and the glyph passes when that equals the cell's width), which
covers the border and block glyphs of a frame. That width is read through Text's face
alone (`[Buffer] -> [Text] : width`): `cure.core.text.width(g)` of the one code point,
which is by Text's rule 1 for a control and `width.point(g)` otherwise; Cells imports
only `cure.core.text` (`Cell`, `Line`, `Span`, `cell`, `put`, `width`, `cluster`) and
never the `cure.core.text.width` submodule (`control`, `point`), so the memoised
`_point(g)` is exactly `cure.core.text.width(g)` for a one-code-point `str`. Inputs,
outputs and errors of `check` are unchanged by this. Everything else in a row is still
checked: the item types first (over the whole row), then each column in order, the
width and the head / tail rules included, so the first error raised and its message
are the general path's. Every row given to `check` is checked in full whatever its
source; [Grid] simply need not call it on a `Grid`'s own rows: every writer of a grid
checks what it brings in (`Grid(fill=...)` and Grid's `fill` take a narrow cell by
this module's rule, not by its width alone, so a grid never holds a cell `check`
refuses), so `blit` and `clip` of a `Grid` may lay its rows unchecked (see [Grid]'s
rows_well_formed and its Speed (F2)). Law fast_equal (as `cure.core.text`'s): `check`,
`line` and `glyph` give the general path's result, `==` and of the same types, and the
same error class and message for the same row; a proof compares them with a copy of
`check` as of commit 26d0853 over random rows of cells: printable-ASCII, wide heads
and tails, marks riding a base, controls drawn as U+FFFD, and malformed cells (a width
of `True`, `1.0`, `3` or `-1`; a glyph that is empty, two clusters, `b"a"`, a `str`
subclass, or of the wrong width such as `Cell("a", 2)` or `Cell("中", 1)`; a head
without its tail; a tail with another style or no head).

Usage:
    from cure.core.buffer.cells import BLANK, Cell, line, check, blank
    line("a中")          # (Cell("a", 1, None), Cell("中", 2, None), Cell("", 0, None))
    line("e\\u0301")      # (Cell("e\\u0301", 1, None),)
    check([Cell("中", 2, None)])   # ValueError: the head at column 0 has no tail
    blank("s")           # Cell(" ", 1, "s")
"""

from collections.abc import Iterable
from functools import lru_cache

import cure.core.text as _text
from cure.core.text import Cell, Line, Span

BLANK = Cell(" ", 1, None)


def blank(style: object = None) -> Cell:
    """`Cell(" ", 1, style)`: what a broken wide pair leaves behind."""
    return Cell(" ", 1, style)


def tail(style: object = None) -> Cell:
    """`Cell("", 0, style)`: the second column of a wide glyph."""
    return Cell("", 0, style)


def is_tail(cell: Cell) -> bool:
    """True for a tail (width 0)."""
    return cell.width == 0


def is_wide(cell: Cell) -> bool:
    """True for the head of a wide glyph (width 2)."""
    return cell.width == 2


def glyph(char: str, style: object = None) -> Cell:
    """One grapheme cluster as a cell: `cure.core.text.cell(char, style)`."""
    return _text.cell(char, style)


def line(spans: "str | Line | Iterable[Span]", style: object = None) -> "tuple[Cell, ...]":
    """A line as one cell per column (`cure.core.text.put`); a `str` is one span in `style`."""
    if isinstance(spans, str):
        return _text.put(Line((Span(spans, style),)))
    out = _text.put(spans)
    if style is not None:
        raise ValueError("a style is given for spans that carry their own")
    return out


def check(row: "Iterable[Cell]") -> "tuple[Cell, ...]":
    """`row` as a tuple when it is well formed (see the module); ValueError otherwise."""
    if row.__class__ is not tuple and row.__class__ is not list and not isinstance(row, Iterable):
        raise TypeError(f"expected an iterable of Cell, got {type(row).__name__}")
    cells = tuple(row)
    # Speed: each distinct cell object of the row is looked at once (a grid's rows repeat
    # a few objects: its ground, a border glyph).
    distinct = cells if len(cells) < 8 else dict(zip(map(id, cells), cells)).values()
    for cell in distinct:
        if cell.__class__ is not Cell:
            for i, cell in enumerate(cells):
                if not isinstance(cell, Cell):
                    raise TypeError(f"column {i}: expected a Cell, got {type(cell).__name__}")
            break
    for cell in distinct:
        if not _narrow(cell):
            break
    else:
        return cells                 # no head, no tail: every column passes on its own
    prev_w = None
    for i, cell in enumerate(cells):
        if prev_w != 2 and _narrow(cell):
            prev_w = 1
            continue
        _check_cell(cells, i, cell)
        prev_w = cell.width
    return cells


def _narrow(cell: Cell) -> bool:
    """Speed: a cell whose width is an `int` 1 and whose glyph is a `str` of one code point
    of width 1 (printable ASCII is; see the module), checked by that width alone. It
    passes `_check_cell` at any column whose previous cell is not a head. Cells' own:
    no other module imports it ([Grid] asks `check((cell,))`, which takes this path)."""
    w, g = cell.width, cell.glyph
    return (w.__class__ is int and w == 1 and g.__class__ is str and len(g) == 1
            and (" " <= g <= "~" or _point(g) == 1))


@lru_cache(maxsize=4096)
def _point(g: str) -> int:
    """Speed: the width of one code point taken as a cluster: `cure.core.text.width(g)`
    (Text's face; 1 for a control, else the table's `point`; one code point is always
    one cluster; see the module). Memoised: the table is frozen with the release.
    Contract (Q9a): the body calls `_text.width(g)` and nothing of the
    `cure.core.text.width` submodule; the answer is unchanged."""
    return _text.width(g)


def _check_cell(cells: "tuple[Cell, ...]", i: int, cell: Cell) -> None:
    w = cell.width
    if not isinstance(w, int) or isinstance(w, bool) or w not in (0, 1, 2):
        raise ValueError(f"column {i}: width {w!r} is outside 0..2")
    prev = cells[i - 1] if i > 0 else None
    if prev is not None and prev.width == 2 and w != 0:
        raise ValueError(f"column {i - 1}: the head has no tail after it")
    if w == 0:
        if cell.glyph != "":
            raise ValueError(f"column {i}: a tail holds a glyph {cell.glyph!r}")
        if prev is None or prev.width != 2:
            raise ValueError(f"column {i}: an orphan tail")
        if cell.style != prev.style:
            raise ValueError(f"column {i}: the tail's style differs from its head's")
        return
    g = cell.glyph
    if not isinstance(g, str) or len(_text.cluster(g)) != 1 or _text.width(g) != w:
        raise ValueError(f"column {i}: glyph {g!r} is not one cluster of width {w}")
    if w == 2 and i == len(cells) - 1:
        raise ValueError(f"column {i}: the head has no tail at the end of the row")
