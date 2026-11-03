"""{Rect}: where things are: plain values the packages hand each other.

Kind: data (a frozen dataclass, checked on construction, with pure methods).

What it is: a rectangle of terminal cells. `x`, `y` is its top-left cell (column, row;
0-based, either may be negative: a rect may start off screen), `w`, `h` its width and
height in cells (>= 0). It covers the columns `x <= c < x + w` and the rows
`y <= r < y + h`. A rect with `w == 0` or `h == 0` is empty: it covers no cell, but
keeps its position (an empty rect is still a value, e.g. the result of `intersect`).

Data:
- `Rect(x: int, y: int, w: int, h: int)`. Equality and hashing are field by field
  (so two empty rects at different positions differ).

Properties:
- `right == x + w`, `bottom == y + h` (exclusive edges), `area == w * h`,
  `empty == (w == 0 or h == 0)`.

Operations (each returns a new value; none changes `self`):
- `contains(px, py) -> bool`: `x <= px < right and y <= py < bottom`; never true for
  an empty rect.
- `intersect(other) -> Rect`: the overlap, by exactly this formula:
  `x0 = max(x, o.x)`, `y0 = max(y, o.y)`, `x1 = min(right, o.right)`,
  `y1 = min(bottom, o.bottom)`, result `Rect(x0, y0, max(0, x1 - x0), max(0, y1 - y0))`.
  So rects that do not overlap (or only touch) give an empty rect, and
  `a.intersect(b) == b.intersect(a)`.
- `inset(*sides) -> Rect`: the rect shrunk by the given margins, CSS order: one value
  (all four sides), two (top/bottom, left/right), three (top, left/right, bottom) or
  four (top, right, bottom, left). With the four margins `t, r, b, l`:
  `Rect(x + l, y + t, max(0, w - l - r), max(0, h - t - b))`. Negative margins grow
  the rect (an outset). A border box's content is `rect.inset(1)`.
- `split(at, axis="x") -> tuple[Rect, Rect]`: cut in two. With axis `"x"` the pieces
  sit side by side: `a = at` when `at >= 0`, else `w + at` (counted from the right,
  as a Python slice), then clamped to `0..w`; the result is
  `(Rect(x, y, a, h), Rect(x + a, y, w - a, h))`. With axis `"y"` the pieces are
  stacked, the same rule on `h`: `(Rect(x, y, w, a), Rect(x, y + a, w, h - a))`.
  The two pieces always cover the rect exactly (one may be empty).
- `moved(dx, dy) -> Rect`: `Rect(x + dx, y + dy, w, h)` (a layer-local rect moved
  into screen coordinates).

Inputs: ints (never `bool`) for every coordinate, size, margin, `at`, `dx`, `dy`;
  `other` a `Rect`; `axis` a `str`.
Outputs: a `Rect`, a pair of `Rect`, or a `bool`.
Errors: `TypeError` when a field, margin, coordinate, `at` or delta is not an `int`
  (a `bool` included) or `other` is not a `Rect`; `ValueError` when `w < 0` or
  `h < 0`, when `inset` is given 0 or more than 4 margins, or when `axis` is neither
  `"x"` nor `"y"`. Assigning a field raises `dataclasses.FrozenInstanceError`.
Effects: none.

Usage:
    from cure.core.geometry.rect import Rect
    r = Rect(0, 0, 10, 4)
    r.contains(9, 3), r.contains(10, 3)        # (True, False)
    r.intersect(Rect(5, 2, 10, 10))            # Rect(5, 2, 5, 2)
    r.intersect(Rect(20, 0, 2, 2))             # Rect(20, 0, 0, 2): empty
    r.inset(1)                                 # Rect(1, 1, 8, 2)
    r.inset(0, 2)                              # Rect(2, 0, 6, 4)
    r.split(3)                                 # (Rect(0, 0, 3, 4), Rect(3, 0, 7, 4))
    r.split(-1, "y")                           # (Rect(0, 0, 10, 3), Rect(0, 3, 10, 1))
    r.moved(2, 1)                              # Rect(2, 1, 10, 4)
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    """{Rect}: x, y, w, h in cells; intersect, inset, split, contains (see the module)."""

    x: int
    y: int
    w: int
    h: int

    def __post_init__(self) -> None:
        x, y, w, h = self.x, self.y, self.w, self.h
        if x.__class__ is int and y.__class__ is int and w.__class__ is int and h.__class__ is int:
            if w < 0 or h < 0:      # four exact ints: only the sign is left to check
                raise ValueError(f"w and h must be >= 0, got {w}, {h}")
            return
        for name in ("x", "y", "w", "h"):
            _int(getattr(self, name), name)
        if self.w < 0 or self.h < 0:
            raise ValueError(f"w and h must be >= 0, got {self.w}, {self.h}")

    @property
    def right(self) -> int:
        """`x + w`: the first column past the rect."""
        return self.x + self.w

    @property
    def bottom(self) -> int:
        """`y + h`: the first row past the rect."""
        return self.y + self.h

    @property
    def area(self) -> int:
        """`w * h`: the cells it covers."""
        return self.w * self.h

    @property
    def empty(self) -> bool:
        """True when it covers no cell (`w == 0 or h == 0`)."""
        return self.w == 0 or self.h == 0

    def contains(self, px: int, py: int) -> bool:
        """True when cell (`px`, `py`) is inside (never for an empty rect)."""
        _int(px, "px")
        _int(py, "py")
        return self.x <= px < self.right and self.y <= py < self.bottom

    def intersect(self, other: "Rect") -> "Rect":
        """The overlap with `other`, by the formula in the module docstring."""
        if not isinstance(other, Rect):
            raise TypeError(f"expected a Rect, got {type(other).__name__}")
        x0, y0 = max(self.x, other.x), max(self.y, other.y)
        x1, y1 = min(self.right, other.right), min(self.bottom, other.bottom)
        return Rect(x0, y0, max(0, x1 - x0), max(0, y1 - y0))

    def inset(self, *sides: int) -> "Rect":
        """Shrunk by 1 to 4 margins in CSS order (negative ones grow it)."""
        t, r, b, l = _margins(sides)
        return Rect(self.x + l, self.y + t, max(0, self.w - l - r), max(0, self.h - t - b))

    def split(self, at: int, axis: str = "x") -> "tuple[Rect, Rect]":
        """Cut in two at `at` along `axis` ("x": side by side, "y": stacked)."""
        _int(at, "at")
        if axis not in ("x", "y"):
            raise ValueError(f"axis must be 'x' or 'y', got {axis!r}")
        if axis == "x":
            a = _cut(at, self.w)
            return Rect(self.x, self.y, a, self.h), Rect(self.x + a, self.y, self.w - a, self.h)
        a = _cut(at, self.h)
        return Rect(self.x, self.y, self.w, a), Rect(self.x, self.y + a, self.w, self.h - a)

    def moved(self, dx: int, dy: int) -> "Rect":
        """The same size, moved by (`dx`, `dy`)."""
        _int(dx, "dx")
        _int(dy, "dy")
        return Rect(self.x + dx, self.y + dy, self.w, self.h)


def _int(value: object, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")


def _margins(sides: tuple) -> "tuple[int, int, int, int]":
    for side in sides:
        _int(side, "margin")
    if len(sides) == 1:
        return sides * 4
    if len(sides) == 2:
        return sides[0], sides[1], sides[0], sides[1]
    if len(sides) == 3:
        return sides[0], sides[1], sides[2], sides[1]
    if len(sides) == 4:
        return sides
    raise ValueError(f"inset takes 1 to 4 margins, got {len(sides)}")


def _cut(at: int, size: int) -> int:
    a = at if at >= 0 else size + at
    return min(max(a, 0), size)
