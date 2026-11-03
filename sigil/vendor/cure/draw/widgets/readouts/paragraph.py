"""[Paragraph]: styled text, wrapped and aligned.

Kind: service (a frozen dataclass node kind; see the Widgets package's protocol).

What it does: draws a run of styled text into its rect: each paragraph wrapped to the
rect's width by Text's `wrap` (or kept to one row and cut), each row aligned by
Text's `align`, rows past the rect's height folded into a last `↓N more` row.

Data (frozen dataclass; checked on construction):
- `Paragraph(text, *, align="left", wrap=True, role="text", id=None, size=None,
  anchor=None, scope=None, surface=False)`:
  - `text`: a `str` (`Text.of(text)`: a "\\n" ends a paragraph), a Text {Line} (one
    paragraph) or a Text {Text} (one paragraph per line). Spans' styles: `None` is
    `role`, a `str` a theme role, a Style as given.
  - `align`: `"left"`, `"centre"` (or `"center"`), `"right"` or `"justify"`.
  - `wrap`: `True` wraps each paragraph to the width; `False` keeps each to one row.
  - `role`: the theme role of unstyled text.

The rows at width `w` (`rows(w, ctx)`: Text {Line}s whose spans carry the resolved
Styles, the same rows for measure and paint), for each paragraph `p` in order:
- `wrap=True`: `wrap(p, max(w, 1))` (Text's rules: words, CJK by cell, hyphens; an
  empty paragraph gives one empty row, so blank lines are kept);
- `wrap=False`: `(p,)`, cut to `w` with `ctx.glyph("ellipsis")` when wider.
Each row is then aligned in `w` with Text's `align`: `"justify"` justifies every row
of the node but its last row (which is `"left"`), across `"\n"` breaks too; a row
still wider than `w` (a lone
wide cluster at width 1) is cut to `w`.

Painting (`paint(rect, ctx, grid, clip=None)`), on `rect` `R` with `g =
ctx.ground()`: the clip's ground; the rows of `rows(R.w)` from `R.y` down, at most
`R.h` of them: when there are more than `R.h`, the first `R.h - 1` and then the
overflow row (`↓N more`, N the rows not shown, in role `muted`); `shade(grid, clip,
bg=g.style.bg)`. Hits: `(Hit(clip, id),)` when `id` is not `None` and the clip is
not empty.

Measuring: `"x"`: the widest paragraph unwrapped (Text's `spans.measure` of each), 0
for no text; `"y"`: `len(rows(room))` (at `room` columns; `room == 0` taken as 1).

Exact cells (the builtin theme; every row's text in `ctx.style("text")`):
- `Paragraph("the quick brown fox")` at `Rect(0, 0, 10, 2)`: `"the quick "`,
  `"brown fox "`; `align="right"`: `" the quick"`, `" brown fox"`.
- `Paragraph("a b c\\nd", align="justify")` at `Rect(0, 0, 8, 2)`: `"a   b  c"`,
  `"d       "` (the paragraph's last row stays left).
- `Paragraph("the quick brown fox")` at `Rect(0, 0, 10, 1)`: `"↓2 more   "`.
- `Paragraph("abcdefghij", wrap=False)` at `Rect(0, 0, 6, 1)`: `"abcde…"`.
- `measure("x", 0, ctx) == 19`, `measure("y", 10, ctx) == 2`.

Errors: `TypeError` when `text` is not a `str`, `Line` or `Text`, `wrap` or `surface`
  is not a `bool`, `role` is not a `str`, or `id` is unhashable; `ValueError` when
  `align` is not one of its values. `measure` / `paint`: as the protocol states.
Effects: none, apart from `paint`'s writes into the grid it is given.

The family's toolkit (this module hosts it: the private `_begin`, `_check_*`, `_ground`,
`_put`, `_styled`, `_shade`, ... every Readouts module imports; same-system helpers, not
Paragraph's face). Q9c added the pieces of the entry flow KeyHints and Legend share; round
12 moved the flow itself to KeyHints' module as its `flow` (Legend calls it there, the
drawn `[Legend] -> [KeyHints] : flow`), and these stay here, private to the family:
- `_SEP`: the tag of a separator piece in a flow row (an `object()` compared by `is`).
- `_paint_flow`, taking `rows, prefix, P, R, grid, area`: the prefix {Line} at `(R.x,
  R.y)`, then each piece of row `i` at `(R.x + P + x, R.y + i)`, written only inside
  `area` (rows outside it are skipped). Outputs: `None`. Effects: writes into `grid`
  inside `area` only. Errors: none of its own.
KeyHints and Legend import `_SEP` and `_paint_flow` from here; their cells, measures and
hits are unchanged by the moves.
"""

from collections.abc import Hashable
from dataclasses import KW_ONLY, dataclass

from cure.core.buffer import Grid, fill, put, shade, write
from cure.core.geometry import Hit, Rect
from cure.core.text import Cell, Line, Span, Text, align, cut, width, wrap

ALIGNS = ("left", "centre", "center", "right", "justify")
"""How a Paragraph's rows are aligned."""


def _check_common(node: object) -> None:
    """The protocol's common fields: `id` hashable, `surface` a bool."""
    if not isinstance(node.surface, bool):
        raise TypeError(f"surface must be a bool, got {type(node.surface).__name__}")
    if not isinstance(node.id, Hashable):
        raise TypeError(f"id must be hashable, got {type(node.id).__name__}")
    hash(node.id)


def _check_text(name: str, value: object, kinds: tuple = (str, Line)) -> None:
    """A styled text field: one of `kinds`."""
    if not isinstance(value, kinds):
        names = ", ".join(k.__name__ for k in kinds)
        raise TypeError(f"{name} must be one of {names}, got {type(value).__name__}")


def _check_role(name: str, value: object) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a str (a theme role), got {type(value).__name__}")


# -- the family's private drawing helpers (Readouts may not share Containers' own) --

def _check_measure(axis: object, room: object, content: object) -> None:
    """measure's stated errors: the axis, then `room` and `content` (ints >= 0)."""
    if axis not in ("x", "y"):
        raise ValueError(f"axis must be 'x' or 'y', got {axis!r}")
    for name, value in (("room", room), ("content", content)):
        if not isinstance(value, int) or isinstance(value, bool):
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


def _plain(text: str, style: object) -> Line:
    return Line((Span(text, style),)) if text else Line()


def _join(*lines: Line) -> Line:
    return Line(tuple(span for line in lines for span in line.spans))


def _width(text: "str | Line") -> int:
    return width(text) if isinstance(text, str) else text.width


def _put(grid: Grid, x: int, y: int, line: Line, area: Rect) -> None:
    """`line` at (x, y), only inside `area`."""
    if line.spans and area.y <= y < area.bottom and x < area.right:
        put(grid, x, y, line, within=area)


def _restyle(grid: Grid, x0: int, x1: int, y: int, area: Rect, how) -> None:
    """Row `y`'s cells in columns [x0, x1) inside `area` take `how(style)`."""
    lo, hi = max(x0, area.x), min(x1, area.right)
    if not (area.y <= y < area.bottom) or lo >= hi:
        return
    row = grid.row(y)
    if row[lo].width == 0 and lo > area.x:
        lo -= 1
    if row[hi - 1].width == 2 and hi < area.right:
        hi += 1
    cells = [Cell(c.glyph, c.width, how(c.style)) for c in row[lo:hi]]
    write(grid, lo, y, cells, within=area)


def _hit(r: Rect, clip: Rect, tag: object) -> "Hit | None":
    """`Hit(r ∩ clip, tag)`, or None when that is empty."""
    v = r.intersect(clip)
    return None if v.empty else Hit(v, tag)


def _own(node: object, clip: Rect) -> "list[Hit]":
    """The node's own hit, `Hit(clip, id)`, when it has an id."""
    return [] if node.id is None else [Hit(clip, node.id)]


def _more(ctx: object, n: int, w: int) -> Line:
    """The overflow row `↓N more` in role `muted`, cut to `w` (no ellipsis)."""
    return cut(_plain(ctx.glyph("more.down") + str(n) + " more", ctx.style("muted")), max(0, w))


def _shown(count: int, h: int) -> "tuple[int, int]":
    """Of `count` rows in a rect `h` tall: how many are drawn, and how many the
    overflow row stands for (0: no overflow row)."""
    if count <= h:
        return count, 0
    keep = max(0, h - 1)
    return keep, count - keep


_SEP = object()
"""The tag of a separator piece in a flow row."""


def _paint_flow(rows: list, prefix: Line, P: int, R: Rect, grid: Grid, area: Rect) -> None:
    """Draw a flow's rows from `R.y`, the prefix first on the first row."""
    _put(grid, R.x, R.y, prefix, area)
    for i, row in enumerate(rows):
        y = R.y + i
        if not area.y <= y < area.bottom:
            continue
        for x, line, _, _ in row:
            _put(grid, R.x + P + x, y, line, area)


@dataclass(frozen=True)
class Paragraph:
    """Styled text, wrapped and aligned into its rect (see the module)."""

    text: "str | Line | Text"
    _: KW_ONLY
    align: str = "left"
    wrap: bool = True
    role: str = "text"
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = False

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _check_text("text", self.text, (str, Line, Text))
        if self.align not in ALIGNS:
            raise ValueError(f"align must be one of {ALIGNS}, got {self.align!r}")
        if not isinstance(self.wrap, bool):
            raise TypeError(f"wrap must be a bool, got {type(self.wrap).__name__}")
        _check_role("role", self.role)
        _check_common(self)

    def rows(self, w: int, ctx: object) -> "tuple[Line, ...]":
        """The aligned rows at width `w`, before the height is applied (see the module)."""
        rows = self._wrapped(w, ctx)
        return tuple(self._aligned(row, w, i == len(rows) - 1) for i, row in enumerate(rows))

    def _wrapped(self, w: int, ctx: object) -> "list[Line]":
        """The rows at width `w` before they are aligned."""
        rows: list = []
        for p in self._paragraphs(ctx):
            if self.wrap:
                rows.extend(wrap(p, max(w, 1)))
            else:
                rows.append(cut(p, w, ellipsis=ctx.glyph("ellipsis")) if p.width > w else p)
        return rows

    def _aligned(self, row: Line, w: int, last: bool) -> Line:
        """One row aligned in `w` (justify leaves the last row left), cut to `w`."""
        how = "left" if self.align == "justify" and last else self.align
        row = align(row, w, how)
        if w < 2 or not self.wrap:
            if row.width > w:
                row = cut(row, w)
        return row

    def _paragraphs(self, ctx: object) -> "tuple[Line, ...]":
        """Each paragraph as a Line, its spans' styles resolved."""
        text = self.text
        if isinstance(text, str):
            lines = Text.of(text).lines
        elif isinstance(text, Line):
            lines = (text,)
        else:
            lines = text.lines
        return tuple(_styled(line, ctx, self.role) for line in lines)

    def chrome(self) -> None:
        """None: a leaf has no insets."""
        return None

    def lifts(self, ctx: object) -> bool:
        """Always False."""
        return False

    def measure(self, axis: str, room: int, ctx: object, content: int = 0) -> int:
        """The widest paragraph, or the rows at `room` columns (see the module)."""
        _check_measure(axis, room, content)
        if axis == "x":
            return max((p.width for p in self._paragraphs(ctx)), default=0)
        return len(self._wrapped(max(room, 1), ctx))

    def paint(self, rect: Rect, ctx: object, grid: Grid, clip: "Rect | None" = None
              ) -> "tuple[Hit, ...]":
        """The rows into `grid` inside `clip` (see the module)."""
        begun = _begin(rect, grid, clip)
        if begun is None:
            return ()
        clip, area = begun
        g = ctx.ground()
        _ground(grid, area, g.style)
        R = rect
        if R.h > 0 and R.w > 0 and not area.empty:
            rows = self._wrapped(R.w, ctx)
            keep, more = _shown(len(rows), R.h)
            padded = self.align != "left" or R.w < 2
            for i in range(max(0, area.y - R.y), min(keep, area.bottom - R.y)):
                row = self._aligned(rows[i], R.w, i == len(rows) - 1) if padded else rows[i]
                _put(grid, R.x, R.y + i, row, area)
            if more:
                _put(grid, R.x, R.y + keep, _more(ctx, more, R.w), area)
        _shade(grid, area, g.style)
        return tuple(_own(self, clip))
