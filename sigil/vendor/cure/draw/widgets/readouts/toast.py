"""[Toast]: transient notes.

Kind: service (a frozen dataclass node kind; see the Widgets package's protocol).

What it does: a short note (saved, failed, copied) led by its kind's word in the
kind's role, so it reads with colour off. It is transient by the app's doing, not its
own: the app keeps a toast in the tree until its own deadline passes (the clock is an
argument; nothing here reads one) and usually floats it in an Overlay
(`At("bottom-right", margin=1)`) for its frame. It is a surface (`surface=True`):
it takes the next ground level, so it stands off what is beneath it.

Data (frozen dataclass; checked on construction):
- `Toast(text, *, kind="info", id=None, size=None, anchor=None, scope=None,
  surface=True)`: `text` styled text (`str` or {Line}; span style `None` is the role
  `text`); `kind` one of `KINDS` (`"info"`, `"ok"`, `"warn"`, `"error"`).

The cells, at `rect` `R`: the prefix `kind + " "` (the word in the role named `kind`,
which the builtin theme defines: `info`, `ok`, `warn`, `error`; then one ground
cell), `P = width(kind) + 1`; the text wrapped by Text's `wrap` to `max(1, R.w - P)`,
its first row after the prefix and the rest from `R.x + P` (indented under it). Rows
past `R.h`: the first `R.h - 1` and the overflow row (`↓N more`).

Painting (`paint(rect, ctx, grid, clip=None)`), `g = ctx.ground()` (the toast's own
level): the clip's ground, the rows, `shade(grid, clip, bg=g.style.bg)`. Hits:
`(Hit(clip, id),)` when `id` is not `None` (a click to dismiss is the app's).

Measuring: `"x"`: `P + width(text)` (unwrapped); `"y"`: the wrapped rows at
`max(1, room - P)`.

Exact cells (the builtin theme, `ctx` entered at the toast's level):
- `Toast("saved", kind="ok")` at `Rect(0, 0, 10, 1)`: `"ok saved  "`, `ok` in
  `ctx.style("ok")`, `saved` in `ctx.style("text")`, the rest `ctx.ground().style`.
- `Toast("could not write the file", kind="error")` at `Rect(0, 0, 16, 3)`: the
  text wraps at 10 to `"could not"`, `"write the"`, `"file"`: `"error could not "`,
  `"      write the "`, `"      file      "`. At `Rect(0, 0, 16, 2)`: `"error could
  not "` and the overflow row, a whole row from `R.x`: `"↓2 more         "`.

Errors: `TypeError` when `text` is neither a `str` nor a `Line`, `kind` is not a
  `str`, or as the common fields; `ValueError` when `kind` is not in `KINDS`.
  `measure` / `paint`: as the protocol states.
Effects: none, apart from `paint`'s writes into the grid it is given.
"""

from collections.abc import Hashable
from dataclasses import KW_ONLY, dataclass

from cure.core.buffer import Grid
from cure.core.geometry import Hit, Rect
from cure.core.text import Line, width, wrap

from .paragraph import (_begin, _check_common, _check_measure, _check_text, _ground, _join, _more,
                        _own, _plain, _put, _shade, _shown, _styled, _width)

KINDS = ("info", "ok", "warn", "error")
"""A toast's kinds; each is also the theme role its word is drawn in."""


@dataclass(frozen=True)
class Toast:
    """A transient note led by its kind's word (see the module)."""

    text: "str | Line"
    _: KW_ONLY
    kind: str = "info"
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = True

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _check_text("text", self.text)
        if not isinstance(self.kind, str):
            raise TypeError(f"kind must be a str, got {type(self.kind).__name__}")
        if self.kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}, got {self.kind!r}")
        _check_common(self)

    def chrome(self) -> None:
        """None: a leaf has no insets."""
        return None

    def lifts(self, ctx: object) -> bool:
        """Always False."""
        return False

    def measure(self, axis: str, room: int, ctx: object, content: int = 0) -> int:
        """The prefix and the text, unwrapped or wrapped (see the module)."""
        _check_measure(axis, room, content)
        P = width(self.kind) + 1
        if axis == "x":
            return P + _width(self.text)
        return len(self._rows(max(1, room - P), ctx))

    def paint(self, rect: Rect, ctx: object, grid: Grid, clip: "Rect | None" = None
              ) -> "tuple[Hit, ...]":
        """The note into `grid` inside `clip` (see the module)."""
        begun = _begin(rect, grid, clip)
        if begun is None:
            return ()
        clip, area = begun
        g = ctx.ground()
        _ground(grid, area, g.style)
        R = rect
        if R.h >= 1:
            P = width(self.kind) + 1
            rows = self._rows(max(1, R.w - P), ctx)
            keep, more = _shown(len(rows), R.h)
            if keep:
                _put(grid, R.x, R.y, _join(_plain(self.kind, ctx.style(self.kind)),
                                           _plain(" ", g.style)), area)
            for i in range(keep):
                if area.y <= R.y + i < area.bottom:
                    _put(grid, R.x + P, R.y + i, rows[i], area)
            if more:
                _put(grid, R.x, R.y + keep, _more(ctx, more, R.w), area)
        _shade(grid, area, g.style)
        return tuple(_own(self, clip))

    def _rows(self, w: int, ctx: object) -> "tuple[Line, ...]":
        """The text wrapped to `w` columns, its spans' styles resolved."""
        return wrap(_styled(self.text, ctx, "text"), w)
