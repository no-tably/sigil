"""[Scrollbar]: and scroll indicators.

Kind: service (two frozen dataclass node kinds, `Scrollbar` and `More`; see the
Widgets package's protocol).

What it does: shows where a scrolled view is. `Scrollbar` is a track with a thumb
whose length and place follow the view's share of the content; `More` is the
`↓N more` row (overflow is never silent: Layout's Scaffold reserves the row, its
`Regions.below` and `first` give the counts, and Paint draws a `More` there). Both
take their numbers from the app or Paint; neither scrolls anything.

Data (frozen dataclasses; checked on construction):
- `Scrollbar(total, offset=0, view=None, *, axis="y", id=None, size=None,
  anchor=None, scope=None, surface=False)`: `total` the content's length (rows for
  `axis="y"`, columns for `"x"`), `offset` the first one shown, `view` how many are
  shown (`None`: the track's own length), each an `int >= 0`.
- `More(below=0, above=0, *, id=None, size=None, anchor=None, scope=None,
  surface=False)`: the rows hidden below and above, each an `int >= 0`.

The scrollbar (`paint(rect, ctx, grid, clip=None)`), on `rect` `R`: the track's
length `n` is `R.h` (`axis="y"`) or `R.w` (`"x"`); `v = view if view is not None else
n`. The thumb:
- when `total <= v`: the whole track, `L = n`, `T = 0`;
- else `L = max(1, min(n, n * v // total))`, `top = total - v`,
  `T = (n - L) * min(offset, top) // top`.
The track is a RUN (R3b, refine round 7; Context's run op, R3a): `cells =
ctx.run("run.scrollbar.track", n, t, style=ctx.border(False))` (`weight` None,
`focused` False: a scrollbar has no focus state), `t` the track glyph it draws today,
`ctx.glyph("border.light.v")` (│) for `"y"` or `ctx.glyph("border.light.h")` (─) for
`"x"`. One token for both axes: every `run.` pattern is one cell per cluster (checked
at theme load), so it lays the same along either axis. Cell `i` along the track
(`0 <= i < n`) is the thumb, `ctx.glyph("block.full")` (█) in role `muted`, when `T
<= i < T + L`, exactly as today; otherwise `cells[i]`, its glyph and its style (the
edge style `ctx.border(False)`, or a part's role style). The run is laid over the
WHOLE track and the thumb drawn over it, never laid around the thumb: the pattern
stays where it is as the thumb moves (its start at cell 0, its end at cell `n - 1`,
covered while the thumb is there). A track wider than one cell repeats each cell
across it (`"y"`: row `R.y + i` is `cells[i]`'s glyph `R.w` times in its style; `"x"`:
every row the same row of cells). With no `run.scrollbar.track` pattern in the
context's charset (and under the ascii base, a non-ASCII one is already dropped),
`cells` is `t` `n` times in `ctx.border(False)`: today's track (base_unchanged). Ground first and `shade` last, as the protocol's recipe. Hits, when `id` is not
`None`: `Hit(R ∩ clip, (id, "track"))`, then `Hit(thumb rect ∩ clip, (id,
"thumb"))` (each only when not empty). Measuring: `1` along both axes (it fills what
it is given; give it `size=Fixed(1)` in a `Row`).
- `Scrollbar(100, 45, 10)` at `Rect(0, 0, 1, 10)`: `L = 1`, `T = 4`: rows 0-3 `"│"`,
  row 4 `"█"`, rows 5-9 `"│"`. `offset=0`: the thumb at row 0; `offset=90` (or
  more): row 9. `Scrollbar(5)` at the same rect: all ten rows `"█"`.
- `Scrollbar(40, 10, 20, axis="x")` at `Rect(0, 0, 8, 1)`: `L = 4`, `T = (8 - 4) *
  10 // 20 = 2`: `"──████──"`.

The indicator (`More`): one row, `R.y`: the text
- `up + str(above) + " " + down + str(below) + " more"` when both are > 0,
- `down + str(below) + " more"` when only `below`, `up + str(above) + " more"` when
  only `above`, nothing when neither,
with `down = ctx.glyph("more.down")` (↓), `up = ctx.glyph("more.up")` (↑), in role
`muted`, from `R.x`, cut to `R.w` with no ellipsis (the arrow and the number come
first, so they go last); the rest ground. Hits: `(Hit(Rect(R.x, R.y, R.w, 1) ∩ clip,
id),)` when `id` is not `None`. Measuring: `"x"`: the text's width; `"y"`: `1` when
either count is > 0, else `0`.
- `More(43)` at `Rect(0, 0, 12, 1)`: `"↓43 more    "`. `More(43, 2)`:
  `"↑2 ↓43 more "`. `More(43)` at width 4: `"↓43 "`.

`chrome()` is `None` and `lifts(ctx)` is `False` for both (they hold no children).

Laws (R3b; a test loops over themes with and without a `run.scrollbar.track`
pattern, both ascii modes, both axes, every total, offset, view and rect):
- base_unchanged (73c003c): with no `run.scrollbar.track` pattern in the context's
  charset, every Scrollbar's and More's paint (cells and hits) and measure equal
  commit 73c003c's for the same fields and context (that commit's code loaded
  through `tests/_gitref.py` at test time, skipped without git history).
- track-run: every non-thumb cell along the track holds `cells[i]` (glyph and style,
  the ground's bg added where it has none); every thumb cell is today's; the hits
  and the thumb's `T` and `L` do not depend on the pattern.
- `More` takes no run (a line of text).

Errors: `TypeError` when a count is not an int (a `bool` included), `view` is
  neither `None` nor an int, `axis` is not a `str`, or as the common fields;
  `ValueError` when a count is negative or `axis` is not `"x"` or `"y"`. `measure` /
  `paint`: as the protocol states.
Effects: none, apart from `paint`'s writes into the grid it is given.
"""

from collections.abc import Hashable
from dataclasses import KW_ONLY, dataclass

from cure.core.buffer import Grid
from cure.core.geometry import Hit, Rect
from cure.core.text import cut, width

from .block import _begin, _check_common, _check_measure, _ground, _hit, _join, _plain, _put, _shade


def _count(name: str, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{name} must be >= 0, got {value}")


@dataclass(frozen=True)
class Scrollbar:
    """A track and a thumb showing a view's place in its content (see the module)."""

    total: int
    offset: int = 0
    view: "int | None" = None
    _: KW_ONLY
    axis: str = "y"
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = False

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _count("total", self.total)
        _count("offset", self.offset)
        if self.view is not None:
            _count("view", self.view)
        if not isinstance(self.axis, str):
            raise TypeError(f"axis must be a str, got {type(self.axis).__name__}")
        if self.axis not in ("x", "y"):
            raise ValueError(f"axis must be 'x' or 'y', got {self.axis!r}")
        _check_common(self)

    def chrome(self) -> None:
        """None: no insets."""
        return None

    def lifts(self, ctx: object) -> bool:
        """Always False."""
        return False

    def measure(self, axis: str, room: int, ctx: object, content: int = 0) -> int:
        """1 along both axes (see the module)."""
        _check_measure(axis, room, content)
        return 1

    def paint(self, rect: Rect, ctx: object, grid: Grid, clip: "Rect | None" = None
              ) -> "tuple[Hit, ...]":
        """The track and thumb into `grid` inside `clip` (see the module)."""
        begun = _begin(rect, grid, clip)
        if begun is None:
            return ()
        clip, area = begun
        g = ctx.ground()
        _ground(grid, area, g.style)
        R = rect
        y_axis = self.axis == "y"
        n = R.h if y_axis else R.w
        T, L = self._thumb(n)
        full = ctx.glyph("block.full"), ctx.style("muted")
        t = ctx.glyph("border.light.v" if y_axis else "border.light.h")
        track = ctx.run("run.scrollbar.track", n, t, style=ctx.border(False))
        if y_axis:
            for y in range(max(R.y, area.y), min(R.bottom, area.bottom)):
                glyph, style = full if T <= y - R.y < T + L else track[y - R.y]
                _put(grid, R.x, y, _plain(glyph * R.w, style), area)
        else:
            row = _join(*(_plain(*(full if T <= i < T + L else track[i])) for i in range(n)))
            for y in range(max(R.y, area.y), min(R.bottom, area.bottom)):
                _put(grid, R.x, y, row, area)
        _shade(grid, area, g.style)
        if self.id is None:
            return ()
        thumb = Rect(R.x, R.y + T, R.w, L) if y_axis else Rect(R.x + T, R.y, L, R.h)
        hits = (_hit(R, clip, (self.id, "track")), _hit(thumb, clip, (self.id, "thumb")))
        return tuple(h for h in hits if h is not None)

    def _thumb(self, n: int) -> "tuple[int, int]":
        """The thumb's first cell `T` and length `L` on a track `n` cells long."""
        v = self.view if self.view is not None else n
        if self.total <= v:
            return 0, n
        L = max(1, min(n, n * v // self.total))
        top = self.total - v
        return (n - L) * min(self.offset, top) // top, L


@dataclass(frozen=True)
class More:
    """The `↓N more` row: how many rows are hidden below and above (see the module)."""

    below: int = 0
    above: int = 0
    _: KW_ONLY
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = False

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _count("below", self.below)
        _count("above", self.above)
        _check_common(self)

    def chrome(self) -> None:
        """None: no insets."""
        return None

    def lifts(self, ctx: object) -> bool:
        """Always False."""
        return False

    def measure(self, axis: str, room: int, ctx: object, content: int = 0) -> int:
        """The text's width, one row (see the module)."""
        _check_measure(axis, room, content)
        if axis == "x":
            return width(self._text(ctx))
        return 1 if self.below or self.above else 0

    def paint(self, rect: Rect, ctx: object, grid: Grid, clip: "Rect | None" = None
              ) -> "tuple[Hit, ...]":
        """The indicator row into `grid` inside `clip` (see the module)."""
        begun = _begin(rect, grid, clip)
        if begun is None:
            return ()
        clip, area = begun
        g = ctx.ground()
        _ground(grid, area, g.style)
        R = rect
        if R.h >= 1:
            text = _plain(self._text(ctx), ctx.style("muted"))
            _put(grid, R.x, R.y, cut(text, R.w), area)
        _shade(grid, area, g.style)
        if self.id is None:
            return ()
        hit = _hit(Rect(R.x, R.y, R.w, 1), clip, self.id)
        return () if hit is None else (hit,)

    def _text(self, ctx: object) -> str:
        """The indicator's text (see the module)."""
        down = ctx.glyph("more.down") + str(self.below)
        up = ctx.glyph("more.up") + str(self.above)
        if self.below and self.above:
            return up + " " + down + " more"
        if self.below:
            return down + " more"
        if self.above:
            return up + " more"
        return ""
