"""[Pane]: a {Grid} from elsewhere (an embedded terminal's screen), blitted.

Kind: service (a frozen dataclass node kind, `Pane`; see the Widgets package's
protocol and the Surfaces package's shared rules: the offset, the states).

What it does: shows a Buffer {Grid} it is given, such as an embedded terminal's
screen (a Vt screen's grid, kept by Embed), in its rect: the grid's cells are blitted
at the app's offset, cut where they run past the rect (clipped) and the rect's cells
that no source cell covers are ground (padded). The cells keep their own styles
(an embedded program's colours); a cell with no background takes the ground's, so
the program's default background is the pane's ground. It also says where the
embedded program's cursor is on screen (`cursor_at`) so the app can place the
terminal's own cursor there while the pane has the focus.

Data (frozen dataclass; checked on construction):
- `Pane(grid, *, x=0, y=0, cursor=None, focused=None, id=None, size=None,
  anchor=None, scope=None, surface=False)`:
  - `grid`: a Buffer `Grid`, the source. It is held, not copied: the app gives the
    frame's grid (a Grid is mutable; a Pane over a grid that changes later draws
    the later cells, so the pure law holds per grid content).
  - `x`, `y`: ints (any sign), the source cell shown at the rect's top-left (a
    scrollback's offset; `0, 0` for a live screen).
  - `cursor`: `None` or a pair `(col, row)` of ints `>= 0`, the program's cursor in
    source cells (`None`: hidden).
  - `focused`: `None` (ask `ctx.is_focused(id)`), `True` or `False`.

Painting (`paint(rect, ctx, grid, clip=None)`), on `rect` `R` with `g =
ctx.ground()` and `area` the clip inside the target grid: the clip's ground;
`blit(grid, source, R.x - x, R.y - y, within=area)` (Buffer's: wide pairs cut by
the area's edges leave a blank in the column inside, never half a glyph); then
`shade(grid, clip, bg=g.style.bg)`. A Pane draws no overflow marks: an embedded
terminal is sized to its pane by the app (measure gives the source's size), and a
scrolled view shows its place through a Scrollbar beside it. Hits: `(Hit(clip,
id),)` when `id` is not `None` and the clip is not empty, else `()`.

The cursor (`cursor_at(rect, ctx, clip=None) -> tuple[int, int] | None`): with
`(col, row) = cursor`, the screen cell `(R.x + col - x, R.y + row - y)`, when
`cursor` is not `None`, the pane is focused (`focused` if not `None`, else
`ctx.is_focused(id)`), and that cell lies inside `rect` and `clip` (default
`rect`); else `None`. The Pane does not draw the cursor (the terminal's own cursor
shows it; the embedded program's screen may draw its own).

Measuring: `"x"`: `grid.w`; `"y"`: `grid.h`.

Exact cells (the builtin theme, `ctx = Context.of(builtin())`), with `src =
Grid(3, 2)`, `put(src, 0, 0, "ab")`, `put(src, 0, 1, "cd")`:
- `Pane(src, id="p")` at `Rect(0, 0, 5, 3)`: `"ab   "`, `"cd   "`, `"     "`; `a`
  .. `d` and the source's third column in `Style(bg=<the ground's bg>)` (their
  style was `None`), the other cells in `ctx.ground().style`; hits `(Hit(Rect(0,
  0, 5, 3), "p"),)`.
- `x=1`: `"b    "`, `"d    "`; `y=1`: `"cd   "`, then ground.
- At `Rect(1, 1, 2, 1)` in a 5 x 3 grid: only row 1, columns 1-2, become `"ab"`.
- A source row `"中x"` with `x=1`: `" x"` (the wide glyph's tail column is a blank).
- `cursor=(2, 1)`, `ctx.focus == "p"`: `cursor_at(Rect(0, 0, 5, 3), ctx) == (2,
  1)`; unfocused, `None`; with `x=3`, `None` (off the rect).
- `measure("x", 0, ctx) == 3`, `measure("y", 0, ctx) == 2`.

Errors: construction: `TypeError` when `grid` is not a Buffer `Grid`, `x` / `y` is
  not an int (a `bool` included), `cursor` is not `None` or a pair of ints,
  `focused` is not `None` or a `bool`, `surface` is not a `bool`, or `id` is
  unhashable; `ValueError` when a `cursor` value is negative. `measure` / `paint`: as
  the protocol states; `cursor_at`: `TypeError` when `rect` / `clip` is not a Rect.
Effects: none, apart from `paint`'s writes into the grid it is given.

Usage:
    from cure.core.buffer import Grid, put, text
    from cure.core.geometry import Rect
    from cure.draw.context import Context
    from cure.draw.theme import builtin
    from cure.draw.widgets.surfaces import Pane
    src = put(put(Grid(3, 2), 0, 0, "ab"), 0, 1, "cd")
    ctx = Context.of(builtin(), focus="p")
    g = Grid(5, 3)
    p = Pane(src, cursor=(2, 1), id="p")
    p.paint(Rect(0, 0, 5, 3), ctx, g)     # (Hit(Rect(0, 0, 5, 3), "p"),)
    text(g)                               # "ab\\ncd\\n"
    p.cursor_at(Rect(0, 0, 5, 3), ctx)    # (2, 1)
"""

from collections.abc import Hashable
from dataclasses import KW_ONLY, dataclass

from cure.core.buffer import Grid, blit
from cure.core.geometry import Hit, Rect

from .drawing import (_begin, _check_common, _check_ints, _check_measure, _check_rect, _focus,
                      _ground, _is_int, _shade)


@dataclass(frozen=True)
class Pane:
    """A grid from elsewhere, blitted into the rect at an offset (see the module)."""

    grid: Grid
    _: KW_ONLY
    x: int = 0
    y: int = 0
    cursor: "tuple[int, int] | None" = None
    focused: "bool | None" = None
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = False

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        if not isinstance(self.grid, Grid):
            raise TypeError(f"grid must be a Grid, got {type(self.grid).__name__}")
        _check_ints(self, "x", "y")
        if self.cursor is not None:
            c = self.cursor
            if not isinstance(c, (tuple, list)) or len(c) != 2 or not all(_is_int(v) for v in c):
                raise TypeError(f"cursor must be None or a pair of ints, got {c!r}")
        if self.focused is not None and not isinstance(self.focused, bool):
            raise TypeError(f"focused must be None or a bool, got {type(self.focused).__name__}")
        _check_common(self)
        if self.cursor is not None and min(self.cursor) < 0:
            raise ValueError(f"cursor values must be >= 0, got {self.cursor!r}")

    def chrome(self) -> None:
        """None: no insets."""
        return None

    def lifts(self, ctx: object) -> bool:
        """Always False."""
        return False

    def measure(self, axis: str, room: int, ctx: object, content: int = 0) -> int:
        """The source grid's size (see the module)."""
        _check_measure(axis, room, content)
        return self.grid.w if axis == "x" else self.grid.h

    def paint(self, rect: Rect, ctx: object, grid: Grid, clip: "Rect | None" = None
              ) -> "tuple[Hit, ...]":
        """The source blitted at the offset, clipped and padded (see the module)."""
        begun = _begin(rect, grid, clip)
        if begun is None:
            return ()
        clip, area = begun
        g = ctx.ground()
        _ground(grid, area, g.style)
        if not area.empty:
            blit(grid, self.grid, rect.x - self.x, rect.y - self.y, within=area)
        _shade(grid, area, g.style)
        return () if self.id is None else (Hit(clip, self.id),)

    def cursor_at(self, rect: Rect, ctx: object, clip: "Rect | None" = None
                  ) -> "tuple[int, int] | None":
        """The screen cell of the embedded cursor, when focused and in view (see the module)."""
        _check_rect("rect", rect)
        _check_rect("clip", clip, none=True)
        if self.cursor is None or not _focus(self, ctx):
            return None
        col, row = self.cursor
        at = (rect.x + col - self.x, rect.y + row - self.y)
        within = rect if clip is None else clip
        if not rect.contains(*at) or not within.contains(*at):
            return None
        return at
