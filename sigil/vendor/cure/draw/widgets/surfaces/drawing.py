"""[Drawing]: rows of runs (a canvas's, a graph's, sigil's) through a viewport.

Kind: service (a frozen dataclass node kind, `Drawing`; see the Widgets package's
protocol and the Surfaces package's shared rules: the offset, the states).

What it does: shows rows of styled runs, already drawn (Canvas's, Graph's, sigil's
views', a golden), through the rect at the app's offset, the viewport's `x`, `y`.
Only the rows and columns in view are laid into the grid. Content past the view is
marked (`marks=True`, the default: a row running off the right ends in the
ellipsis, rows hidden above or below fold into the indicator row), or not
(`marks=False`, for an app that shows the view's place otherwise: Scrollbars, a
status). Hit regions the drawing carries (a graph's boxes) are recorded where they
show, so a click names a box.

Data (frozen dataclass; checked on construction):
- `Drawing(rows=(), *, x=0, y=0, regions=(), marks=True, role="text", extent=None,
  id=None, size=None, anchor=None, scope=None, surface=False)`:
  - `rows`: a tuple of styled text (`str` or Text {Line}), or a Buffer {Rows}
    (its `lines` are the rows). Span styles: `None` is `role`, a `str` a theme role
    (`ctx.style(name)`, so colours keep their role), a Style as given.
  - `x`, `y`: ints (any sign): the content cell shown at the rect's top-left.
  - `regions`: a tuple of Geometry `Hit`, in content cells (each `Hit(r, tag)`; its
    `layer` is not used).
  - `marks`: a `bool`, whether overflow is marked (above).
  - `role`: a `str`, the role of unstyled text.
  - `extent`: the content extent, public for the app's pan and clamp: `None` (the
    default) or a tuple of two ints `>= 0`, `(width, height)`. Given (the caller's
    when it knows it, as DagView does from Graph's `lay`), it is stored as a Surfaces
    {Extent} as given, not re-checked against the rows; `None` is counted once on
    construction, `Extent(widest row, row count)` (a `Rows` value: its own width and
    height), so `drawing.extent` is always an {Extent} after construction. Paint and
    measure never read it: every frame is the same whatever it holds.

The view, on `rect` `R`, with `n = len(rows)`, `H = R.h`:
- Rows. `a = min(max(y, 0), n)` (rows above the view); at full height the rows
  below are `bf = n - min(n, max(a, y + H))`. With `marks`, `H >= 1` and `a > 0 or bf
  > 0`, the last cell row is the indicator and content rows `cy` in `[y, y + H - 1)`
  are drawn, `below = n - min(n, max(a, y + H - 1))`; else the rows in `[y, y + H)`.
  Only `0 <= cy < n` exist; cell rows with none stay ground. Row `cy` is drawn on
  cell row `R.y + cy - y`.
- Columns. With `lead = max(0, -x)` (blank columns before the content), row `cy`
  is `cut(row, max(0, R.w - lead), start=max(0, x), ellipsis=e)` drawn from `R.x +
  lead`, `e = ctx.glyph("ellipsis")` with `marks`, else `""` (Text's cut: a row
  wider than `x + R.w` ends in the ellipsis; a wide glyph straddling the left edge
  leaves blanks, never half a glyph). The rest of the row is ground.
- The indicator: `More`'s text (Containers' Scrollbar), `above = a`, `below`, in
  role `muted`, from `R.x`, cut to `R.w` with no ellipsis.

Painting (`paint(rect, ctx, grid, clip=None)`), `g = ctx.ground()`: the clip's
ground, the rows, the indicator, `shade(grid, clip, bg=g.style.bg)`.

Hits, in order: `Hit(clip, id)` when `id` is not `None`; then each region `h`, in
order, as `Hit(h.rect.moved(R.x - x, R.y - y) ∩ body ∩ clip, h.tag)` when not empty,
`body` the rect less the indicator row when one is drawn (a region's own tag is
recorded as itself, whatever the Drawing's `id`).

Measuring: `"x"`: the widest row (`0` with none); `"y"`: `n`. (At its measured size
with `x == y == 0` everything shows: no mark is drawn.)

Exact cells (the builtin theme, `ctx = Context.of(builtin())`; text in
`ctx.style("text")`), with `rows = ("abcdef", "ghijkl", "mnopqr")`:
- `Drawing(rows, x=2, y=1, marks=False)` at `Rect(0, 0, 4, 2)`: `"ijkl"`, `"opqr"`;
  with `x=-1` instead: `" ghi"`, `" mno"`; with `y=-1` instead: `"    "` (ground)
  then `"cdef"`.
- `Drawing(rows)` at `Rect(0, 0, 4, 2)`: `"abc…"`, `"↓2 m"` (the indicator `↓2
  more` cut to 4); `x=2, y=1`: `"ijkl"`, `"↑1 ↓"` (`↑1 ↓1 more` cut).
- `Drawing(rows)` at `Rect(0, 0, 6, 3)`: the three rows whole, no mark.
- `Drawing(rows, regions=(Hit(Rect(1, 1, 2, 1), "box"),), id="d")` at `Rect(0, 0,
  6, 3)`: hits `Hit(Rect(0, 0, 6, 3), "d")`, `Hit(Rect(1, 1, 2, 1), "box")`; with
  `x=2`: the region at `Rect(-1, 1, 2, 1) ∩ clip == Rect(0, 1, 1, 1)`.
- `measure("x", 0, ctx) == 6`, `measure("y", 0, ctx) == 3`; `Drawing(rows).extent ==
  Extent(6, 3)`; `Drawing(rows, extent=(9, 9)).extent == Extent(9, 9)`.

Errors: construction: `TypeError` when `rows` is neither a tuple of `str` / `Line`
  nor a `Rows`, `x` / `y` is not an int (a `bool` included), `regions` is not a
  tuple of `Hit`, `marks` / `surface` is not a `bool`, `role` is not a `str`, or
  `id` is unhashable; `extent`: `TypeError("extent must be None or a pair of ints >= 0,
  got list")` when it is not a tuple of two ints (a `bool` refused; the message names
  the type), `ValueError("extent must be None or a pair of ints >= 0, got (-1, 2)")`
  when one is negative (the message names the pair). `measure` / `paint`: as the protocol states.
Effects: none, apart from `paint`'s writes into the grid it is given.

Usage:
    from cure.core.buffer import Grid, text
    from cure.core.geometry import Rect
    from cure.draw.context import Context
    from cure.draw.theme import builtin
    from cure.draw.widgets.surfaces import Drawing
    g = Grid(4, 2)
    Drawing(("abcdef", "ghijkl", "mnopqr")).paint(Rect(0, 0, 4, 2), Context.of(builtin()), g)
    text(g)                      # "abc…\\n↓2 m"
"""

from collections.abc import Hashable
from dataclasses import KW_ONLY, dataclass

from cure.core.buffer import Grid, Rows, fill, put, shade
from cure.core.geometry import Hit, Rect
from cure.core.text import Cell, Line, Span, cut, width

from .extent import Extent


# -- the family's private helpers (Surfaces may not share another family's own) --

def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_ints(node: object, *names: str) -> None:
    for name in names:
        value = getattr(node, name)
        if not _is_int(value):
            raise TypeError(f"{name} must be an int, got {type(value).__name__}")


def _check_common(node: object) -> None:
    """The protocol's common fields: `id` hashable, `surface` a bool."""
    if not isinstance(node.surface, bool):
        raise TypeError(f"surface must be a bool, got {type(node.surface).__name__}")
    if not isinstance(node.id, Hashable):
        raise TypeError(f"id must be hashable, got {type(node.id).__name__}")
    hash(node.id)


def _check_measure(axis: object, room: object, content: object) -> None:
    """measure's stated errors: the axis, then `room` and `content` (ints >= 0)."""
    if axis not in ("x", "y"):
        raise ValueError(f"axis must be 'x' or 'y', got {axis!r}")
    for name, value in (("room", room), ("content", content)):
        if not _is_int(value):
            raise TypeError(f"{name} must be an int, got {type(value).__name__}")
        if value < 0:
            raise ValueError(f"{name} must be >= 0, got {value}")


def _begin(rect: object, grid: object, clip: object) -> "tuple[Rect, Rect] | None":
    """paint's stated errors; `(clip, area)` (area: the clip inside the grid), or None
    for an empty clip (nothing is written)."""
    if not isinstance(rect, Rect):
        raise TypeError(f"rect must be a Rect, got {type(rect).__name__}")
    if not isinstance(grid, Grid):
        raise TypeError(f"grid must be a Grid, got {type(grid).__name__}")
    if clip is None:
        clip = rect
    elif not isinstance(clip, Rect):
        raise TypeError(f"clip must be a Rect or None, got {type(clip).__name__}")
    if clip.empty:
        return None
    if clip.intersect(rect) != clip:
        raise ValueError(f"clip {clip} does not lie inside rect {rect}")
    return clip, clip.intersect(Rect(0, 0, grid.w, grid.h))


def _ground(grid: Grid, area: Rect, style: object) -> None:
    """Every cell of `area` becomes a blank in `style` (the recipe's step 1)."""
    if not area.empty:
        fill(grid, area, Cell(" ", 1, style))


def _shade(grid: Grid, area: Rect, style: object) -> None:
    """The recipe's last step: the ground's bg under every written cell without one."""
    bg = getattr(style, "bg", None)
    if bg is not None and not area.empty:
        shade(grid, area, bg=bg)


def _styled(text: "str | Line", ctx: object, role: str) -> Line:
    """Styled text with its spans' styles resolved: None is `role`, a str a theme role,
    a Style as given."""
    if isinstance(text, str):
        return Line((Span(text, ctx.style(role)),)) if text else Line()
    spans = []
    for span in text.spans:
        s = span.style
        if s is None:
            s = ctx.style(role)
        elif isinstance(s, str):
            s = ctx.style(s)
        spans.append(Span(span.text, s))
    return Line(tuple(spans))


def _put(grid: Grid, x: int, y: int, line: Line, area: Rect) -> None:
    """`line` at (x, y), only inside `area`."""
    if line.spans and area.y <= y < area.bottom and x < area.right:
        put(grid, x, y, line, within=area)


def _hit(r: Rect, clip: Rect, tag: object) -> "Hit | None":
    """`Hit(r ∩ clip, tag)`, or None when that is empty."""
    v = r.intersect(clip)
    return None if v.empty else Hit(v, tag)


def _more_text(ctx: object, above: int, below: int) -> str:
    """`More`'s text: `↑A ↓B more`, `↓B more` or `↑A more`."""
    up, down = ctx.glyph("more.up"), ctx.glyph("more.down")
    if above > 0 and below > 0:
        return f"{up}{above} {down}{below} more"
    if below > 0:
        return f"{down}{below} more"
    if above > 0:
        return f"{up}{above} more"
    return ""


def _focus(node: object, ctx: object) -> bool:
    """A surface's focus: its `focused` field, else the context's."""
    return node.focused if node.focused is not None else ctx.is_focused(node.id)


def _check_rect(name: str, value: object, none: bool = False) -> None:
    if none and value is None:
        return
    if not isinstance(value, Rect):
        raise TypeError(f"{name} must be a Rect, got {type(value).__name__}")


def _width(line: "str | Line") -> int:
    return width(line) if isinstance(line, str) else line.width


_EXTENT = "extent must be None or a pair of ints >= 0, got "


def _extent(value: object, lines: tuple) -> Extent:
    """The given pair checked and held as an Extent; None counted from the rows."""
    if value is None:
        return Extent(max((_width(r) for r in lines), default=0), len(lines))
    if not (isinstance(value, tuple) and len(value) == 2 and all(_is_int(v) for v in value)):
        raise TypeError(_EXTENT + type(value).__name__)
    if value[0] < 0 or value[1] < 0:
        raise ValueError(_EXTENT + repr(tuple(value)))
    return Extent(*value)


@dataclass(frozen=True)
class Drawing:
    """Rows of styled runs shown through the rect at an offset (see the module)."""

    rows: "tuple | Rows" = ()
    _: KW_ONLY
    x: int = 0
    y: int = 0
    regions: tuple = ()
    marks: bool = True
    role: str = "text"
    extent: "tuple[int, int] | None" = None
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = False

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        if isinstance(self.rows, Rows):
            if not all(isinstance(r, Line) for r in self.rows.lines):
                raise TypeError("rows must be a tuple of str / Line or a Rows")
        elif not isinstance(self.rows, tuple) or not all(
                isinstance(r, (str, Line)) for r in self.rows):
            raise TypeError("rows must be a tuple of str / Line or a Rows")
        _check_ints(self, "x", "y")
        if not isinstance(self.regions, tuple) or not all(isinstance(h, Hit) for h in self.regions):
            raise TypeError("regions must be a tuple of Hit")
        if not isinstance(self.marks, bool):
            raise TypeError(f"marks must be a bool, got {type(self.marks).__name__}")
        if not isinstance(self.role, str):
            raise TypeError(f"role must be a str, got {type(self.role).__name__}")
        _check_common(self)
        object.__setattr__(self, "extent", _extent(self.extent, self._lines()))

    def _lines(self) -> tuple:
        return self.rows.lines if isinstance(self.rows, Rows) else self.rows

    def chrome(self) -> None:
        """None: no insets."""
        return None

    def lifts(self, ctx: object) -> bool:
        """Always False."""
        return False

    def measure(self, axis: str, room: int, ctx: object, content: int = 0) -> int:
        """The widest row; the number of rows (see the module)."""
        _check_measure(axis, room, content)
        lines = self._lines()
        if axis == "y":
            return len(lines)
        return max((_width(r) for r in lines), default=0)

    def paint(self, rect: Rect, ctx: object, grid: Grid, clip: "Rect | None" = None
              ) -> "tuple[Hit, ...]":
        """The rows in view, their marks, the regions as hits (see the module)."""
        begun = _begin(rect, grid, clip)
        if begun is None:
            return ()
        clip, area = begun
        g = ctx.ground()
        _ground(grid, area, g.style)
        R, lines = rect, self._lines()
        n, H, x, y = len(lines), R.h, self.x, self.y
        a = min(max(y, 0), n)
        after = n - min(n, max(a, y + H))
        marked = self.marks and H >= 1 and (a > 0 or after > 0)
        last = y + H - 1 if marked else y + H
        lead = max(0, -x)
        e = ctx.glyph("ellipsis") if self.marks else ""
        lo = max(y, 0, y + area.y - R.y)
        hi = min(last, n, y + area.bottom - R.y)
        for cy in range(lo, hi):
            line = cut(_styled(lines[cy], ctx, self.role), max(0, R.w - lead), start=max(0, x),
                       ellipsis=e)
            _put(grid, R.x + lead, R.y + cy - y, line, area)
        if marked:
            below = n - min(n, max(a, y + H - 1))
            text = _more_text(ctx, a, below)
            line = cut(Line((Span(text, ctx.style("muted")),)), max(0, R.w))
            _put(grid, R.x, R.y + H - 1, line, area)
        _shade(grid, area, g.style)
        hits = [] if self.id is None else [Hit(clip, self.id)]
        body = Rect(R.x, R.y, R.w, H - 1 if marked else H)
        for h in self.regions:
            hit = _hit(h.rect.moved(R.x - x, R.y - y).intersect(body), clip, h.tag)
            if hit is not None:
                hits.append(hit)
        return tuple(hits)
