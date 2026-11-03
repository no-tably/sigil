"""[Chart]: sparkline, bars, lines in braille.

Kind: service (four frozen dataclasses: the node kinds `Sparkline`, `Bars`, `Lines`
and the `Series` a `Lines` plots; see the Widgets package's protocol).

What it does: small charts of numbers in cells. A `Sparkline` is one column per
value in vertical eighths, newest at the right; `Bars` one row per labelled value in
horizontal eighths; `Lines` one or more series plotted as dots joined by vertical
runs, in braille (2 x 4 dots a cell) when the charset allows it. Block glyphs come
from the charset (`block.eighths.v` " ▁▂▃▄▅▆▇█" from the bottom, `block.eighths.h`
from the left, `block.full`); braille is a plot mode, not a glyph table: when
`"braille"` is in `ctx.charset.plots` the cell's code point is computed, as
Canvas's plots do, `chr(0x2800 | bits)`; otherwise `Lines` falls back to one dot a
cell drawn as `block.full`. Every sample shows (a value at the floor still draws one
eighth): a chart never hides a point.

Values: ints or floats, finite (a `bool` refused). The scale `lo`, `hi`: `low` /
`high` when given, else `lo = min(0, min(values))` and `hi = max(values)` (for
`Lines`, over every series). A value outside is clamped into `[lo, hi]`.

Data (frozen dataclasses; checked on construction; each node kind ends with the
common keyword-only fields `id`, `size`, `anchor`, `scope`, `surface=False`):
- `Sparkline(values, *, low=None, high=None, role="accent")`: `values` a tuple.
- `Bars(items, *, high=None, span=20, role="accent")`: `items` a tuple of
  `(label, value)` pairs, `label` a `str`, `value` >= 0; `span` the natural bar
  width (`measure("x")`), an `int >= 1`. The scale is `0 .. (high or max(values))`.
- `Series(values, role="accent")`: one line's values (a tuple) and its role.
- `Lines(series, *, low=None, high=None, rows=4)`: `series` a tuple of `Series`;
  `rows` the natural height (`measure("y")`), an `int >= 1`.

Sparkline (`paint`), at `rect` `R` (`n = R.w` columns, `h = R.h` rows): the last
`n` values, right-aligned (value `i` of `k` shown in column `R.x + n - k + i`). A
value `v`'s height in eighths: `e = int((v - lo) * 8 * h / (hi - lo))` when `hi > lo`,
else `0`; then `e = max(1, e)`. Its cell in the row `r` from the bottom (`r = 0` the
last row): `k = min(8, max(0, e - 8 * r))`, the glyph `ctx.glyph("block.eighths.v")[k]`
when `k > 0`, else ground; all in `role`.
- `Sparkline((0, 1, 2, 3, 4, 5, 6, 7, 8))` at `Rect(0, 0, 9, 1)`: `"▁▁▂▃▄▅▆▇█"`
  (the 0 still draws one eighth). At `Rect(0, 0, 9, 2)`: `e = 2v`, floored at 1,
  `(1, 2, 4, 6, 8, 10, 12, 14, 16)`: the top row `"     ▂▄▆█"`, the bottom row
  `"▁▂▄▆█████"`.

Bars (`paint`): `z` the widest label; each item a row from `R.y`: the label
left-aligned in `z` cells (role `muted`), one ground cell, the bar over `b = R.w - z -
1` cells: `e = int(v * 8 * b / top)` eighths (`top = high or max(values)`, `e = 0`
when `top == 0`), `e // 8` cells of `block.full` and, when `e % 8 > 0`,
`block.eighths.h[e % 8]`, in `role`; the rest ground. Rows past `R.h`: the first
`R.h - 1` and the overflow row (`↓N more`).
- `Bars((("a", 1), ("bb", 2)))` at `Rect(0, 0, 7, 2)`: `"a  ██  "`, `"bb ████"`.

Lines (`paint`), braille: a dot grid `W = 2 * R.w` wide and `H = 4 * R.h` tall. Each
series' last `W` values, right-aligned: value `i` of `k` at dot column `X_i = W - k +
i`, dot row from the bottom `Y_i = int((v - lo) * (H - 1) / (hi - lo))` when `hi > lo`,
else `0`. Its dots: `(X_i, Y_i)`, and for `i >= 1` the dots of column `X_i` strictly
between `Y_{i-1}` and `Y_i` (a vertical run joining the two). A dot `(X, Y)` falls in
cell `(R.x + X // 2, R.y + (H - 1 - Y) // 4)`, at column `c = X % 2` and row `q =
(H - 1 - Y) % 4` inside it, the bit `((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20,
0x80))[c][q]`; a cell's glyph is `chr(0x2800 | <the OR of its bits over every
series>)`, in the role of the last series (in order) with a dot there; a cell with
no dot is ground. Without braille: `W = R.w`, `H = R.h`, one dot a cell, each dot cell
`ctx.glyph("block.full")` in its series' role.
- `Lines((Series((0, 1, 2, 3)),))` at `Rect(0, 0, 2, 1)`: `Y = (0, 1, 2, 3)`; cell 0
  holds `(0, 0)` (bit 0x40) and `(1, 1)` (0x20): `"⡠"`; cell 1 `(2, 2)` (0x02) and
  `(3, 3)` (0x08): `"⠊"`: `"⡠⠊"`.
- The same with an ascii charset at `Rect(0, 0, 4, 4)`: `Y = (0, 1, 2, 3)`: a
  diagonal of `#` from the bottom-left to the top-right.

Painting, every kind: the protocol's recipe (the clip's ground, the cells, `shade`).
Hits: `(Hit(clip, id),)` when `id` is not `None`.

Measuring: `Sparkline`: `"x"` `len(values)`, `"y"` `1`. `Bars`: `"x"` `z + 1 + span`,
`"y"` `len(items)`. `Lines`: `"x"` `ceil(max(len(s.values)) / 2)` (braille) or
`max(len(s.values))` (without; `0` with no series), `"y"` `rows`.

Errors: `TypeError` when `values` / `items` / `series` is not a tuple of the stated
  items, a value is not an int or float (a `bool` included), a label or role is not a
  `str`, `low` / `high` is neither `None` nor a number, `span` / `rows` is not an int,
  or as the common fields; `ValueError` when a value, `low` or `high` is not finite,
  `low > high`, a `Bars` value or `high` is negative, or `span` / `rows` is < 1.
  `measure` / `paint`: as the protocol states.
Effects: none, apart from `paint`'s writes into the grid it is given.
"""

import math
from collections.abc import Hashable
from dataclasses import KW_ONLY, dataclass

from cure.core.buffer import Grid
from cure.core.geometry import Hit, Rect
from cure.core.text import width

from .paragraph import (_begin, _check_common, _check_measure, _check_role, _ground, _join, _more,
                        _own, _plain, _put, _shade, _shown)

BRAILLE_BITS = ((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80))
"""The braille dot bits by column (0, 1) and row from the top (0 to 3) in a cell."""


def _check_number(name: str, value: object) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int or a float, got {type(value).__name__}")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")


def _check_values(values: object) -> None:
    if not isinstance(values, tuple):
        raise TypeError(f"values must be a tuple, got {type(values).__name__}")
    for v in values:
        _check_number("a value", v)


def _check_scale(low: object, high: object) -> None:
    for name, v in (("low", low), ("high", high)):
        if v is not None:
            _check_number(name, v)
    if low is not None and high is not None and low > high:
        raise ValueError(f"low must be <= high, got {low!r} > {high!r}")


def _check_positive(name: str, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if value < 1:
        raise ValueError(f"{name} must be >= 1, got {value}")


class _Leaf:
    """The leaf methods every chart kind shares (stubs: see the module)."""

    def chrome(self) -> None:
        """None: a leaf has no insets."""
        return None

    def lifts(self, ctx: object) -> bool:
        """Always False."""
        return False

    def measure(self, axis: str, room: int, ctx: object, content: int = 0) -> int:
        """The kind's natural size (see the module)."""
        _check_measure(axis, room, content)
        return self._natural(axis, ctx)

    def paint(self, rect: Rect, ctx: object, grid: Grid, clip: "Rect | None" = None
              ) -> "tuple[Hit, ...]":
        """The chart into `grid` inside `clip` (see the module)."""
        begun = _begin(rect, grid, clip)
        if begun is None:
            return ()
        clip, area = begun
        g = ctx.ground()
        _ground(grid, area, g.style)
        if not rect.empty:
            self._draw(rect, ctx, grid, area, g.style)
        _shade(grid, area, g.style)
        return tuple(_own(self, clip))


def _scale(values: "list[float]", low: "float | None", high: "float | None"
           ) -> "tuple[float, float]":
    """`lo`, `hi`: `low` / `high` when given, else `min(0, min(values))`, `max(values)`."""
    lo = low if low is not None else min(0, min(values))
    hi = high if high is not None else max(values)
    return lo, hi


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v)) if lo <= hi else lo


@dataclass(frozen=True)
class Sparkline(_Leaf):
    """One column per value in vertical eighths, newest at the right (see the module)."""

    values: tuple = ()
    _: KW_ONLY
    low: "float | None" = None
    high: "float | None" = None
    role: str = "accent"
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = False

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _check_values(self.values)
        _check_scale(self.low, self.high)
        _check_role("role", self.role)
        _check_common(self)

    def _natural(self, axis: str, ctx: object) -> int:
        return len(self.values) if axis == "x" else 1

    def _draw(self, R: Rect, ctx: object, grid: Grid, area: Rect, gs: object) -> None:
        if not self.values:
            return
        lo, hi = _scale(self.values, self.low, self.high)
        shown = self.values[-R.w:]
        h = R.h
        heights = []
        for v in shown:
            v = _clamp(v, lo, hi)
            e = int((v - lo) * 8 * h / (hi - lo)) if hi > lo else 0
            heights.append(max(1, e))
        eighths = ctx.glyph("block.eighths.v")
        style = ctx.style(self.role)
        x0 = R.x + R.w - len(shown)
        for y in range(max(R.y, area.y), min(R.bottom, area.bottom)):
            r = R.bottom - 1 - y
            spans = []
            for e in heights:
                k = min(8, max(0, e - 8 * r))
                spans.append(_plain(eighths[k], style) if k > 0 else _plain(" ", gs))
            _put(grid, x0, y, _join(*spans), area)


@dataclass(frozen=True)
class Bars(_Leaf):
    """One row per labelled value in horizontal eighths (see the module)."""

    items: tuple = ()
    _: KW_ONLY
    high: "float | None" = None
    span: int = 20
    role: str = "accent"
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = False

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        if not isinstance(self.items, tuple):
            raise TypeError(f"items must be a tuple, got {type(self.items).__name__}")
        for item in self.items:
            if not (isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str)):
                raise TypeError(f"an item must be a (label, value) pair, got {item!r}")
            _check_number("a value", item[1])
            if item[1] < 0:
                raise ValueError(f"a Bars value must be >= 0, got {item[1]!r}")
        _check_scale(None, self.high)
        if self.high is not None and self.high < 0:
            raise ValueError(f"high must be >= 0, got {self.high!r}")
        _check_positive("span", self.span)
        _check_role("role", self.role)
        _check_common(self)

    def _natural(self, axis: str, ctx: object) -> int:
        if axis == "y":
            return len(self.items)
        return max((width(label) for label, _ in self.items), default=0) + 1 + self.span

    def _draw(self, R: Rect, ctx: object, grid: Grid, area: Rect, gs: object) -> None:
        if not self.items:
            return
        z = max(width(label) for label, _ in self.items)
        b = R.w - z - 1
        top = self.high or max(v for _, v in self.items)
        keep, more = _shown(len(self.items), R.h)
        full, eighths = ctx.glyph("block.full"), ctx.glyph("block.eighths.h")
        muted, style = ctx.style("muted"), ctx.style(self.role)
        for i in range(keep):
            y = R.y + i
            if not area.y <= y < area.bottom:
                continue
            label, v = self.items[i]
            _put(grid, R.x, y, _plain(label, muted), area)
            if b < 1:
                continue
            e = min(int(v * 8 * b / top), 8 * b) if top else 0
            cells = full * (e // 8) + (eighths[e % 8] if e % 8 else "")
            _put(grid, R.x + z + 1, y, _plain(cells, style), area)
        if more:
            _put(grid, R.x, R.y + keep, _more(ctx, more, R.w), area)


@dataclass(frozen=True)
class Series:
    """One line of a `Lines` chart: its values and its role."""

    values: tuple = ()
    role: str = "accent"

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _check_values(self.values)
        _check_role("role", self.role)


@dataclass(frozen=True)
class Lines(_Leaf):
    """Series plotted as joined dots, in braille when the charset allows (see the module)."""

    series: tuple = ()
    _: KW_ONLY
    low: "float | None" = None
    high: "float | None" = None
    rows: int = 4
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = False

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        if not isinstance(self.series, tuple) or not all(isinstance(s, Series) for s in self.series):
            raise TypeError("series must be a tuple of Series")
        _check_scale(self.low, self.high)
        _check_positive("rows", self.rows)
        _check_common(self)

    def _natural(self, axis: str, ctx: object) -> int:
        if axis == "y":
            return self.rows
        longest = max((len(s.values) for s in self.series), default=0)
        return math.ceil(longest / 2) if "braille" in ctx.charset.plots else longest

    def _draw(self, R: Rect, ctx: object, grid: Grid, area: Rect, gs: object) -> None:
        values = [v for s in self.series for v in s.values]
        if not values:
            return
        lo, hi = _scale(values, self.low, self.high)
        braille = "braille" in ctx.charset.plots
        W, H = (2 * R.w, 4 * R.h) if braille else (R.w, R.h)
        cells: dict = {}
        for series in self.series:
            shown = series.values[-W:]
            k = len(shown)
            prev = None
            for i, v in enumerate(shown):
                v = _clamp(v, lo, hi)
                X = W - k + i
                Y = int((v - lo) * (H - 1) / (hi - lo)) if hi > lo else 0
                dots = [Y]
                if prev is not None:
                    a, b = sorted((prev, Y))
                    dots.extend(range(a + 1, b))
                prev = Y
                for y in dots:
                    q = H - 1 - y
                    if braille:
                        key = (X // 2, q // 4)
                        bit = BRAILLE_BITS[X % 2][q % 4]
                    else:
                        key, bit = (X, q), 0
                    bits = cells.get(key, (0, None))[0]
                    cells[key] = (bits | bit, series.role)
        full = ctx.glyph("block.full")
        for (cx, cy), (bits, role) in cells.items():
            glyph = chr(0x2800 | bits) if braille else full
            _put(grid, R.x + cx, R.y + cy, _plain(glyph, ctx.style(role)), area)
