"""[StatusBar]: segments by priority, never clipped off the left.

Kind: service (two frozen dataclasses: the `StatusBar` node kind and its `Segment`s;
see the Widgets package's protocol).

What it does: one row of segments (a file name, a mode, counts, a clock the app
formats), some flush left and some flush right, on the bar's own ground. When they do
not all fit, whole segments are dropped, the lowest priority first, so what stays is
always readable from its left edge: nothing is ever clipped off the left (sigil's bar
keeps the name and the run's status before the title for this reason).

Data (frozen dataclasses; checked on construction):
- `Segment(text, priority=0, side="left", *, id=None)`: `text` styled text (`str` or
  {Line}; span style `None` is the bar's role; the caller writes the spaces it wants
  around it), `priority` an int (higher stays longer), `side` `"left"` or `"right"`,
  `id` its own tag.
- `StatusBar(segments=(), *, role="status.bar", id=None, size=None, anchor=None,
  scope=None, surface=False)`: `segments` a tuple of `Segment`, in display order
  within each side; `role` the bar's theme role (its ground: the builtin's
  `status.bar` is `$fg on $surface`).

Fitting, at width `w = R.w`: the left group is the left segments in order, the right
group the right ones in order; `total = width(left) + width(right) + (1 if both
groups are non-empty else 0)` (one cell between the groups at least). While `total >
w` and more than one segment is kept, drop the kept segment with the lowest
`priority`; among equal priorities the one drawn furthest right (the right group's
last, then leftwards; then the left group's last). When one segment is left and is
still wider than `w`, it is cut on the right with `ctx.glyph("ellipsis")` (its left
edge kept) and drawn from `R.x`, whatever its side.

Painting (`paint(rect, ctx, grid, clip=None)`), with `bar = ctx.style(role)` and
`g = ctx.ground()`: every cell of the clip `Cell(" ", 1, bar)`; on row `R.y`, the
left group from `R.x` and the right group ending at `R.right`; then
`shade(grid, clip, bg=bar.bg)` and `shade(grid, clip, bg=g.style.bg)` (a segment's
role without a background sits on the bar's). Rows below the first are the bar's
blanks. Hits, in order: `Hit(clip, id)` when `id` is not `None`; then each drawn
segment with an `id`: `Hit(<its cells> ∩ clip, seg.id)`.

Measuring: `"x"`: `total` with every segment kept (0 with none); `"y"`: `1`.

Exact cells (the builtin theme; unstyled text in `ctx.style("status.bar")`):
- `StatusBar((Segment(" file.sigil ", 9), Segment(" view ", 1),
  Segment(" 3E ", 5, "right")))` at `Rect(0, 0, 30, 1)`:
  `" file.sigil  view " + " " * 8 + " 3E "` (18 + 8 + 4 = 30).
- At width 17: `total = 12 + 6 + 4 + 1 = 23 > 17`, so `" view "` (priority 1) goes:
  `" file.sigil " + " " + " 3E "`.
- At width 8: `" 3E "` goes next (5 < 9), then `" file.sigil "` alone is cut:
  `" file.s…"`.

Errors: `TypeError` when `segments` is not a tuple of `Segment`, `text` is neither a
  `str` nor a `Line`, `priority` is not an int (a `bool` included), `role` is not a
  `str`, or an `id` is unhashable; `ValueError` when `side` is not `"left"` or
  `"right"`. `measure` / `paint`: as the protocol states.
Effects: none, apart from `paint`'s writes into the grid it is given.
"""

from collections.abc import Hashable
from dataclasses import KW_ONLY, dataclass

from cure.core.buffer import Grid, fill
from cure.core.geometry import Hit, Rect
from cure.core.text import Cell, Line, cut

from .paragraph import (_begin, _check_common, _check_measure, _check_role, _check_text, _hit,
                        _own, _put, _shade, _styled, _width)


def _total(segments: "list[Segment]") -> int:
    """The width of the kept segments: both groups and the gap between them."""
    left = sum(_width(s.text) for s in segments if s.side == "left")
    right = sum(_width(s.text) for s in segments if s.side == "right")
    both = any(s.side == "left" for s in segments) and any(s.side == "right" for s in segments)
    return left + right + (1 if both else 0)


@dataclass(frozen=True)
class Segment:
    """One piece of a status bar: its text, priority and side (see the module)."""

    text: "str | Line"
    priority: int = 0
    side: str = "left"
    _: KW_ONLY
    id: Hashable = None

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _check_text("text", self.text)
        if not isinstance(self.priority, int) or isinstance(self.priority, bool):
            raise TypeError(f"priority must be an int, got {type(self.priority).__name__}")
        if self.side not in ("left", "right"):
            raise ValueError(f"side must be 'left' or 'right', got {self.side!r}")
        if not isinstance(self.id, Hashable):
            raise TypeError(f"id must be hashable, got {type(self.id).__name__}")
        hash(self.id)


@dataclass(frozen=True)
class StatusBar:
    """A row of segments, dropped by priority to fit (see the module)."""

    segments: tuple = ()
    _: KW_ONLY
    role: str = "status.bar"
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = False

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        if not isinstance(self.segments, tuple) or not all(isinstance(s, Segment) for s in self.segments):
            raise TypeError("segments must be a tuple of Segment")
        _check_role("role", self.role)
        _check_common(self)

    def kept(self, w: int) -> "tuple[Segment, ...]":
        """The segments that fit in `w` columns, in display order (see Fitting)."""
        kept = ([s for s in self.segments if s.side == "left"]
                + [s for s in self.segments if s.side == "right"])
        while len(kept) > 1 and _total(kept) > w:
            low = min(s.priority for s in kept)
            drop = max(i for i, s in enumerate(kept) if s.priority == low)
            del kept[drop]
        return tuple(kept)

    def chrome(self) -> None:
        """None: a leaf has no insets."""
        return None

    def lifts(self, ctx: object) -> bool:
        """Always False."""
        return False

    def measure(self, axis: str, room: int, ctx: object, content: int = 0) -> int:
        """Every segment's width with the gap; one row (see the module)."""
        _check_measure(axis, room, content)
        return _total(list(self.segments)) if axis == "x" else 1

    def paint(self, rect: Rect, ctx: object, grid: Grid, clip: "Rect | None" = None
              ) -> "tuple[Hit, ...]":
        """The bar into `grid` inside `clip` (see the module)."""
        begun = _begin(rect, grid, clip)
        if begun is None:
            return ()
        clip, area = begun
        bar = ctx.style(self.role)
        g = ctx.ground()
        if not area.empty:
            fill(grid, area, Cell(" ", 1, bar))
        R = rect
        hits = _own(self, clip)
        if R.h >= 1 and self.segments:
            kept = self.kept(R.w)
            placed = []
            if len(kept) == 1 and _total(list(kept)) > R.w:
                line = cut(_styled(kept[0].text, ctx, self.role), R.w,
                           ellipsis=ctx.glyph("ellipsis"))
                placed.append((R.x, line, kept[0]))
            else:
                x = R.x
                for seg in kept:
                    if seg.side == "left":
                        placed.append((x, _styled(seg.text, ctx, self.role), seg))
                        x += _width(seg.text)
                x = R.right - sum(_width(s.text) for s in kept if s.side == "right")
                for seg in kept:
                    if seg.side == "right":
                        placed.append((x, _styled(seg.text, ctx, self.role), seg))
                        x += _width(seg.text)
            for x, line, seg in placed:
                _put(grid, x, R.y, line, area)
                if seg.id is not None and line.width:
                    hit = _hit(Rect(x, R.y, line.width, 1), clip, seg.id)
                    if hit is not None:
                        hits.append(hit)
        _shade(grid, area, bar)
        _shade(grid, area, g.style)
        return tuple(hits)
