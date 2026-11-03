"""[BoxModel]: margin, border, padding, title inset: a Rect inset.

Kind: service (pure functions; `Box` and `BoxRects` are frozen dataclasses). A box is
three insets taken in order from the outside in, plus a title row: each layer is a
{Rect} inset, so a box never builds geometry of its own after the fact (rects, then
cells, then strings). Which glyphs a border uses, and whether a border too small to
close is drawn at all, is the painting widget's call ([Block]); this module only says
where things are.

Edges. `margin`, `border` and `padding` each take an int or a tuple of 1 to 4 ints in
CSS order (one: all four sides; two: top/bottom, left/right; three: top, left/right,
bottom; four: top, right, bottom, left), every int >= 0. `Box` stores each as the
normalized 4-tuple `(top, right, bottom, left)`, so `Box(margin=1) ==
Box(margin=(1, 1, 1, 1))`. A border's sides are cell counts (1 for a line border; 0
for none).

The clamped inset. `inset(rect, *sides)` is `Rect.inset` (same CSS order, margins
>= 0) clamped so the result never leaves `rect`: with margins `t, r, b, l`,
`Rect(min(x + l, right), min(y + t, bottom), max(0, w - l - r), max(0, h - t - b))`.
So a rect too small for its insets gives an empty rect at (or inside) its far edge:
never a negative size and never a position outside the rect it came from.

Operations:
- `boxed(rect, box) -> BoxRects`, every rect by the clamped `inset`:
  - `outer`: `rect`.
  - `border`: `inset(outer, *box.margin)`: where the border is drawn (its outer edge).
  - `title`: `None` when `box.title` is false. When `box.border` has a top side
    (>= 1), the title sits on the border's top row:
    `Rect(min(b.x + bl + ti, b.right), b.y, max(0, b.w - bl - br - 2 * ti), min(1, b.h))`
    (`b` the border rect, `bl`, `br` the border's left and right, `ti` the
    `title_inset`, the cells kept between a corner and the title). With no top
    border it is the first row inside the border, the same horizontal inset:
    `Rect(min(i.x + ti, i.right), i.y, max(0, i.w - 2 * ti), min(1, i.h))` with
    `i = inset(border, *box.border)`.
  - `content`: `inset(inset(border, *box.border), *box.padding)`, and when the title
    has a row of its own (a title, no top border) the inset's top grows by 1: the
    padding sits below the title row.
  The rects nest: `content` lies inside `border`, `border` inside `outer`; the title
  lies inside `border`.
- `outer(w, h, box) -> tuple[int, int]`: the outer size a content of `w` x `h` needs:
  `w` plus the left and right of margin, border and padding; `h` plus their tops and
  bottoms, plus 1 for a title with no top border. Paint's measure uses it to give a
  boxed node's natural size. `boxed(Rect(0, 0, *outer(w, h, box)), box).content` has
  size `w` x `h` for every `w, h >= 0`.

Inputs: `rect` a {Rect}; `box` a `Box`; `sides`, `w`, `h`: ints >= 0.
  `Box(margin=0, border=0, padding=0, title=False, title_inset=1)`: `title` a bool,
  `title_inset` an int >= 0.
Outputs: `BoxRects(outer, border, title, content)` (`title` a `Rect` or `None`); a
  `Rect`; a pair of ints.
Errors: `TypeError` when `rect` is not a `Rect`, `box` not a `Box`, a side, `w`, `h`
  or `title_inset` is not an int (a `bool` included), `title` is not a bool, or an
  edge is neither an int nor a tuple; `ValueError` when a side, `w`, `h` or
  `title_inset` is negative, or an edge tuple (or `inset`) has 0 or more than 4
  sides. Assigning a field raises `dataclasses.FrozenInstanceError`.
Effects: none.

Usage:
    from cure.core.geometry import Rect
    from cure.draw.layout.boxmodel import Box, boxed, inset, outer
    box = Box(margin=1, border=1, padding=(0, 1), title=True)
    b = boxed(Rect(0, 0, 20, 10), box)
    b.border                                    # Rect(1, 1, 18, 8)
    b.title                                     # Rect(3, 1, 14, 1): on the top border
    b.content                                   # Rect(3, 2, 14, 6)
    outer(14, 6, box)                           # (20, 10)
    boxed(Rect(0, 0, 10, 4), Box(title=True)).title     # Rect(1, 0, 8, 1)
    boxed(Rect(0, 0, 10, 4), Box(title=True)).content   # Rect(0, 1, 10, 3)
    boxed(Rect(0, 0, 3, 2), Box(border=1, padding=1)).content   # Rect(2, 1, 0, 0)
    inset(Rect(0, 0, 1, 5), 0, 3)               # Rect(1, 0, 0, 5): clamped, not Rect(3, ...)
"""

from dataclasses import dataclass

from cure.core.geometry import Rect


def _edges(value: object, name: str) -> "tuple[int, int, int, int]":
    sides = (value,) if isinstance(value, int) and not isinstance(value, bool) else value
    if not isinstance(sides, tuple):
        raise TypeError(f"{name} must be an int or a tuple of ints, got {type(value).__name__}")
    for side in sides:
        if not isinstance(side, int) or isinstance(side, bool):
            raise TypeError(f"{name} sides must be ints, got {type(side).__name__}")
        if side < 0:
            raise ValueError(f"{name} sides must be >= 0, got {side}")
    if len(sides) == 1:
        return sides * 4
    if len(sides) == 2:
        return sides[0], sides[1], sides[0], sides[1]
    if len(sides) == 3:
        return sides[0], sides[1], sides[2], sides[1]
    if len(sides) == 4:
        return sides
    raise ValueError(f"{name} takes 1 to 4 sides, got {len(sides)}")


@dataclass(frozen=True)
class Box:
    """Margin, border, padding (each normalized to (top, right, bottom, left)), title."""

    margin: "int | tuple[int, ...]" = 0
    border: "int | tuple[int, ...]" = 0
    padding: "int | tuple[int, ...]" = 0
    title: bool = False
    title_inset: int = 1

    def __post_init__(self) -> None:
        for name in ("margin", "border", "padding"):
            object.__setattr__(self, name, _edges(getattr(self, name), name))
        if not isinstance(self.title, bool):
            raise TypeError(f"title must be a bool, got {type(self.title).__name__}")
        if not isinstance(self.title_inset, int) or isinstance(self.title_inset, bool):
            raise TypeError(f"title_inset must be an int, got {type(self.title_inset).__name__}")
        if self.title_inset < 0:
            raise ValueError(f"title_inset must be >= 0, got {self.title_inset}")


@dataclass(frozen=True)
class BoxRects:
    """Where a box's parts are: outer, border, title (or None), content."""

    outer: Rect
    border: Rect
    title: "Rect | None"
    content: Rect


def inset(rect: Rect, *sides: int) -> Rect:
    """`rect` shrunk by 1 to 4 margins (CSS order), clamped never to leave `rect`."""
    _rect(rect)
    t, r, b, l = _edges(sides, "inset")
    return Rect(min(rect.x + l, rect.right), min(rect.y + t, rect.bottom),
                max(0, rect.w - l - r), max(0, rect.h - t - b))


def boxed(rect: Rect, box: Box) -> BoxRects:
    """The rects of `box` laid in `rect`: margin, border, title row, padding, content."""
    _rect(rect)
    _box(box)
    border = inset(rect, *box.margin)
    bt, br, bb, bl = box.border
    inner = inset(border, *box.border)
    ti = box.title_inset
    title = None
    own_row = box.title and bt == 0
    if box.title and bt >= 1:
        title = Rect(min(border.x + bl + ti, border.right), border.y,
                     max(0, border.w - bl - br - 2 * ti), min(1, border.h))
    elif own_row:
        title = Rect(min(inner.x + ti, inner.right), inner.y, max(0, inner.w - 2 * ti),
                     min(1, inner.h))
    pt, pr, pb, pl = box.padding
    content = inset(inner, pt + (1 if own_row else 0), pr, pb, pl)
    return BoxRects(rect, border, title, content)


def outer(w: int, h: int, box: Box) -> tuple[int, int]:
    """The outer size a `w` x `h` content needs inside `box`."""
    for value, name in ((w, "w"), (h, "h")):
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{name} must be an int, got {type(value).__name__}")
        if value < 0:
            raise ValueError(f"{name} must be >= 0, got {value}")
    _box(box)
    layers = (box.margin, box.border, box.padding)
    title_row = 1 if box.title and box.border[0] == 0 else 0
    return (w + sum(e[1] + e[3] for e in layers),
            h + sum(e[0] + e[2] for e in layers) + title_row)


def _rect(rect: object) -> None:
    if not isinstance(rect, Rect):
        raise TypeError(f"rect must be a Rect, got {type(rect).__name__}")


def _box(box: object) -> None:
    if not isinstance(box, Box):
        raise TypeError(f"box must be a Box, got {type(box).__name__}")
