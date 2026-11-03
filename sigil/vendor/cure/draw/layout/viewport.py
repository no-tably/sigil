"""[Viewport]: 2D pan, fit, home / centre, follow a focus box without fighting the person's own panning.

Kind: service (a frozen value with pure methods; `Viewport` is a frozen dataclass,
checked on construction). A view of `view_w` x `view_h` cells onto content of
`content_w` x `content_h` cells (a drawing, a pane's scrollback, a log) that may be
larger or smaller. sigil's viewer pans its drawings through it; construct's DAG view
and minimap too. Viewport knows nothing of what the content is: it keeps the offset.
The clock is an argument (`now`: the app's ticks or seconds, any number; `hold` in
the same unit); Viewport never reads one. Ported from sigil's viewer (`pan_bounds`,
`place`, `centre_origin`, `follow_origin`, the drag and `_follow`), with its bugs
fixed: a follow that moved a fully visible box when it was wider than the view with
its margins, and a follow that snapped back over the person's own pan on the next
frame.

The offset. `x`, `y` is the content cell shown at the view's top-left cell: content
cell `(cx, cy)` is drawn at view cell `(cx - x, cy - y)`. An offset may be negative
(a blank lead-in before the content) or past the content's end, within the bounds.

No zoom: in cells there is no scale. Fitting a drawing to the view is the app's
re-layout (sigil's wrap ladder composes a narrower drawing); the app then gives the
new content size (`sized`), and the clamped mode keeps it pinned while it fits.

The bounds, per axis, with `size` the content's extent and `view` the view's:
- clamped (`free=False`, the default; sigil's "fit"): `(0, max(size - view, 0))`:
  the content scrolls within itself, pinned at 0 while it fits.
- free (`free=True`; sigil's "pan"): with `keep = min(size, max(view // 2, 1))`,
  `(keep - view, size - keep)`: anywhere that keeps at least half the view (or all
  of a smaller content) on screen.
`clamp(o) = max(lo, min(o, hi))`. Every operation's result has its offset clamped.

Data:
- `Viewport(content_w, content_h, view_w, view_h, x=0, y=0, free=False,
  last_pan=None, followed=None)`: the sizes ints >= 0; `x`, `y` ints (any; an
  operation clamps them); `free` a bool; `last_pan` `None` or the `now` of the
  person's last own move; `followed` `None` or the last focus box `follow` was given
  (a {Rect} in content cells). The constructor checks types and ranges and does not
  clamp; `clamped()` does.

Operations (each returns a new `Viewport`; none changes `self`). A person's own move
(`pan`, `scroll_to`, `home`, `centre`) given `now` records `last_pan = now`; without
`now` it is the app's move and leaves `last_pan` as it was:
- `bounds -> ((x_lo, x_hi), (y_lo, y_hi))` (a property).
- `clamped()`: the offset clamped to the bounds (after `dataclasses.replace`, e.g. a
  switch of `free`).
- `pan(dx, dy, now=None)`: `x + dx`, `y + dy`, clamped (keys, the wheel).
- `scroll_to(x, y, now=None)`: the offset `(x, y)`, clamped (a mouse drag: on each
  motion `scroll_to(x0 - (px - px0), y0 - (py - py0), now)` from the offset and
  pointer at the press).
- `home(now=None)`: the offset `(0, 0)`, clamped: the content's top-left.
- `centre(box=None, now=None)`: `box` (a {Rect} in content cells; `None`: the whole
  content, `Rect(0, 0, content_w, content_h)`) centred: per axis
  `o = lo - (view - size) // 2` (floor division; `lo`, `size` the box's start and
  extent), clamped.
- `follow(box, now, *, hold, margin=2)`: keep the focus box in view without fighting
  the person. In order:
  1. `box is None`, or `box == followed`: the offset clamped, otherwise unchanged
     (the same focus: a person who panned away from it keeps their view; it is not
     pulled back).
  2. Otherwise `followed = box`. Held, when the person moved recently
     (`last_pan is not None and now - last_pan < hold`): the offset clamped,
     otherwise unchanged.
  3. Not held: per axis, with `o` the offset, `lo`, `size` the box's start and
     extent, `view` the view's extent and `m = min(margin, max(view - size, 0) //
     2)` (the margin shrinks so the box and its margins fit):
     - `size > view`: unchanged when the view lies inside the box (`lo <= o` and
       `o + view <= lo + size`), else `o = lo` (its start);
     - else `o = lo - m` when `lo - m < o`; else `o = lo + size + m - view` when
       `lo + size + m > o + view`; else unchanged (already in view: no move);
     then clamped. `last_pan` is never changed by `follow`.
- `sized(content_w, content_h, view_w, view_h)`: new sizes, the offset clamped, and
  `followed = None` (after a resize, the next `follow` acts on its box anew).
- `visible -> Rect` (a property): `Rect(x, y, view_w, view_h)`: the content cells in
  view (it may reach past the content).
- `shows(box) -> bool`: `box` (a {Rect}) lies wholly in `visible`; an empty box is
  shown when its position is (`visible.x <= box.x <= visible.right`, likewise y).
- `fits -> tuple[bool, bool]` (a property): `(content_w <= view_w, content_h <=
  view_h)`.
- `to_content(vx, vy) -> tuple[int, int]`: the content cell under view cell
  `(vx, vy)`: `(vx + x, vy + y)` (a click).

Laws (each true for every valid input; a test can loop over them):
- Every operation's result lies in its bounds; `v.clamped().clamped() ==
  v.clamped()`.
- pan back: when `v.pan(dx, dy)` is not clamped (both new offsets lie in the
  bounds), `v.clamped().pan(dx, dy).pan(-dx, -dy) == v.clamped()` (with no `now`).
- `home` of a clamped view is `(0, 0)`; `centre()` of content that fits a clamped
  view is `(0, 0)`.
- follow keeps the box visible: when not held, `box` lies inside the content
  (`Rect(0, 0, content_w, content_h)`), `1 <= box.w <= view_w` and
  `1 <= box.h <= view_h`, then `v.follow(box, now, hold=h).shows(box)` (in either mode).
- follow is minimal: on a clamped view, when the box with its margins (`m` per axis,
  as in step 3) lies in `visible`, `follow` leaves the offset unchanged.
- follow never fights: on a clamped view, when held, or when `box == v.followed`,
  the offset is unchanged; `follow(...).follow(box, ...)` with the same box moves
  nothing more.
- `to_content` then drawing at `(cx - x, cy - y)` is the identity.

Inputs: sizes ints >= 0; `x`, `y`, `dx`, `dy`, `vx`, `vy` ints (never `bool`);
  `margin` an int >= 0; `now`, `hold`, `last_pan` ints or floats (never `bool`),
  `hold` >= 0; `box` a {Rect} or `None` (`centre`, `follow`); `free` a bool.
Outputs: a `Viewport`; bounds; a `Rect`; a bool or a pair.
Errors: `TypeError` when a size, offset, delta, `margin`, `now`, `hold` or
  `last_pan` is not of its type (a `bool` included), `free` is not a bool, or `box`
  / `followed` is not a `Rect` (or `None` where allowed); `ValueError` when a size,
  `margin` or `hold` is negative. Assigning a field raises
  `dataclasses.FrozenInstanceError`.
Effects: none.

Usage:
    from cure.core.geometry import Rect
    from cure.draw.layout.viewport import Viewport
    v = Viewport(100, 50, 40, 20)                 # content 100x50, view 40x20, clamped
    v.bounds                                      # ((0, 60), (0, 30))
    v = v.pan(10, 5, now=0)                       # x=10, y=5, last_pan=0
    v.pan(100, 0).x                               # 60: clamped
    f = v.follow(Rect(70, 10, 5, 3), now=10, hold=5)
    f.x, f.y, f.followed                          # 37, 5, Rect(70, 10, 5, 3)
    h = v.follow(Rect(70, 10, 5, 3), now=3, hold=5)
    h.x, h.y, h.followed                          # 10, 5, Rect(70, 10, 5, 3): held
    h.follow(Rect(70, 10, 5, 3), now=10, hold=5).x   # 10: the same box, not pulled back
    Viewport(100, 50, 40, 20).centre()            # x=30, y=15
    Viewport(100, 50, 40, 20, free=True).bounds   # ((-20, 80), (-10, 40))
    s = Viewport(10, 4, 40, 20, free=True).centre()
    s.x, s.y                                      # -15, -8: a small drawing centred
    Viewport(10, 4, 40, 20).centre().x            # 0: clamped, pinned while it fits
    v.visible, v.to_content(3, 2)                 # Rect(10, 5, 40, 20), (13, 7)
"""

from dataclasses import dataclass, replace

from cure.core.geometry import Rect


def _int(value: object, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")


def _number(value: object, name: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int or float, got {type(value).__name__}")


@dataclass(frozen=True)
class Viewport:
    """A view onto larger (or smaller) content: sizes, the offset, the mode, follow state."""

    content_w: int
    content_h: int
    view_w: int
    view_h: int
    x: int = 0
    y: int = 0
    free: bool = False
    last_pan: "int | float | None" = None
    followed: "Rect | None" = None

    def __post_init__(self) -> None:
        for name in ("content_w", "content_h", "view_w", "view_h"):
            value = getattr(self, name)
            _int(value, name)
            if value < 0:
                raise ValueError(f"{name} must be >= 0, got {value}")
        _int(self.x, "x")
        _int(self.y, "y")
        if not isinstance(self.free, bool):
            raise TypeError(f"free must be a bool, got {type(self.free).__name__}")
        if self.last_pan is not None:
            _number(self.last_pan, "last_pan")
        if self.followed is not None and not isinstance(self.followed, Rect):
            raise TypeError(f"followed must be a Rect or None, got {type(self.followed).__name__}")

    @property
    def bounds(self) -> "tuple[tuple[int, int], tuple[int, int]]":
        """((x_lo, x_hi), (y_lo, y_hi)) for the mode."""
        return (_bounds(self.content_w, self.view_w, self.free),
                _bounds(self.content_h, self.view_h, self.free))

    def clamped(self) -> "Viewport":
        """The offset clamped to the bounds."""
        return self._at(self.x, self.y)

    def pan(self, dx: int, dy: int, now: "int | float | None" = None) -> "Viewport":
        """The offset moved by (dx, dy), clamped; `now` records the person's pan."""
        _int(dx, "dx")
        _int(dy, "dy")
        return self._moved(self.x + dx, self.y + dy, now)

    def scroll_to(self, x: int, y: int, now: "int | float | None" = None) -> "Viewport":
        """The offset (x, y), clamped; `now` records the person's pan."""
        _int(x, "x")
        _int(y, "y")
        return self._moved(x, y, now)

    def home(self, now: "int | float | None" = None) -> "Viewport":
        """The offset (0, 0), clamped."""
        return self._moved(0, 0, now)

    def centre(self, box: "Rect | None" = None,
               now: "int | float | None" = None) -> "Viewport":
        """`box` (None: the whole content) centred in the view, clamped."""
        if box is None:
            box = Rect(0, 0, self.content_w, self.content_h)
        _rect(box, "box")
        return self._moved(box.x - (self.view_w - box.w) // 2,
                           box.y - (self.view_h - box.h) // 2, now)

    def follow(self, box: "Rect | None", now: "int | float", *, hold: "int | float",
               margin: int = 2) -> "Viewport":
        """The least move that shows a new focus box, unless the person panned within `hold`."""
        if box is not None:
            _rect(box, "box")
        _number(now, "now")
        _number(hold, "hold")
        if hold < 0:
            raise ValueError(f"hold must be >= 0, got {hold}")
        _int(margin, "margin")
        if margin < 0:
            raise ValueError(f"margin must be >= 0, got {margin}")
        if box is None or box == self.followed:
            return self.clamped()
        v = replace(self, followed=box)
        if self.last_pan is not None and now - self.last_pan < hold:
            return v.clamped()
        return v._at(_follow(self.x, box.x, box.w, self.view_w, margin),
                     _follow(self.y, box.y, box.h, self.view_h, margin))

    def sized(self, content_w: int, content_h: int, view_w: int, view_h: int) -> "Viewport":
        """New sizes, the offset clamped, `followed` cleared."""
        return replace(self, content_w=content_w, content_h=content_h, view_w=view_w,
                       view_h=view_h, followed=None).clamped()

    @property
    def visible(self) -> Rect:
        """Rect(x, y, view_w, view_h): the content cells in view."""
        return Rect(self.x, self.y, self.view_w, self.view_h)

    def shows(self, box: Rect) -> bool:
        """Whether `box` lies wholly in `visible`."""
        _rect(box, "box")
        v = self.visible
        return (v.x <= box.x and box.right <= v.right and v.y <= box.y
                and box.bottom <= v.bottom)

    @property
    def fits(self) -> "tuple[bool, bool]":
        """(content_w <= view_w, content_h <= view_h)."""
        return self.content_w <= self.view_w, self.content_h <= self.view_h

    def to_content(self, vx: int, vy: int) -> "tuple[int, int]":
        """The content cell under view cell (vx, vy)."""
        _int(vx, "vx")
        _int(vy, "vy")
        return vx + self.x, vy + self.y

    def _at(self, x: int, y: int) -> "Viewport":
        """The offset (x, y) clamped to the bounds, the rest kept."""
        (xl, xh), (yl, yh) = self.bounds
        return replace(self, x=max(xl, min(x, xh)), y=max(yl, min(y, yh)))

    def _moved(self, x: int, y: int, now: "int | float | None") -> "Viewport":
        """A move to (x, y), clamped; a person's (recording `now`) when `now` is given."""
        if now is None:
            return self._at(x, y)
        _number(now, "now")
        return replace(self, last_pan=now)._at(x, y)


def _rect(value: object, name: str) -> None:
    if not isinstance(value, Rect):
        raise TypeError(f"{name} must be a Rect, got {type(value).__name__}")


def _bounds(size: int, view: int, free: bool) -> "tuple[int, int]":
    """One axis's offset bounds for the mode."""
    if not free:
        return 0, max(size - view, 0)
    keep = min(size, max(view // 2, 1))
    return keep - view, size - keep


def _follow(o: int, lo: int, size: int, view: int, margin: int) -> int:
    """One axis's offset after follow's step 3 (before the clamp)."""
    if size > view:
        return o if lo <= o and o + view <= lo + size else lo
    m = min(margin, max(view - size, 0) // 2)
    if lo - m < o:
        return lo - m
    if lo + size + m > o + view:
        return lo + size + m - view
    return o
