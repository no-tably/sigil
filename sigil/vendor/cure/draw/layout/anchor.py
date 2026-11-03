"""[Anchor]: overlays: centre, edges, or to a rect with flip + clamp.

Kind: service (pure functions from sizes and {Rect}s to a `Rect`; `At` and `Attached`
are frozen dataclasses). Where an overlay (a popover, modal, menu, tooltip, toast)
goes. Anchor only says where; the layer and its z-order are Paint's, and the overlay's
own size comes from the caller (measured; Layout never measures). An overlay is never
bigger than the rect it is placed in, and never placed outside it.

Operations:
- `place(w, h, within, at="centre", margin=0) -> Rect`: inside `area =
  inset(within, margin)` ([BoxModel]'s clamped inset), at one of `PLACES`:
  "centre" (or "center"), the edges "top", "bottom", "left", "right", and the corners
  "top-left", "top-right", "bottom-left", "bottom-right". The size is clamped first:
  `w' = min(w, area.w)`, `h' = min(h, area.h)`. Then x is `area.x` for a place naming
  "left", `area.right - w'` for one naming "right", otherwise `area.x + (area.w - w')
  // 2`; y is `area.y` for "top…", `area.bottom - h'` for "bottom…", otherwise
  `area.y + (area.h - h') // 2`. So an edge place is centred along its edge, and an
  odd leftover puts the extra cell after (right of, or below) the overlay.
- `attach(w, h, target, screen, side="below", align="start", gap=0) -> Attached`: next
  to `target` (a menu under its button, a tooltip by its cell), flipped and clamped
  into `screen`:
  1. Clamp the size: `w' = min(w, screen.w)`, `h' = min(h, screen.h)`.
  2. The room on each side, `gap` cells away from the target: below
     `screen.bottom - (target.bottom + gap)`, above `target.y - gap - screen.y`,
     right `screen.right - (target.right + gap)`, left `target.x - gap - screen.x`.
  3. The side: `side` when the overlay's size along it (`h'` for below / above, `w'`
     for right / left) fits its room; else the opposite side when it fits there
     (`flipped = True`); else `side` (it fits nowhere whole, and the clamp in step 5
     moves it, over the target if it must).
  4. The position: below `y = target.bottom + gap`, above `y = target.y - gap - h'`,
     right `x = target.right + gap`, left `x = target.x - gap - w'`. On the cross axis
     `align` (one of `ALIGNS`): "start" lines up the leading edges (`x = target.x` for
     below / above, `y = target.y` for right / left), "end" the trailing edges
     (`target.right - w'`, `target.bottom - h'`), "centre" (or "center") centres it
     (`target.x + (target.w - w') // 2`, likewise on y).
  5. Clamp into the screen: `x = max(screen.x, min(x, screen.right - w'))`, the same
     on y. No flip on the cross axis: there it only slides.
  The result's `rect` lies inside `screen`; `side` is the side it ended on.

Data:
- `At(at="centre", margin=0)`: the value `lay` reads from a child's `anchor`
  attribute. Such a child is out of the flow (it takes no slot in its parent's
  arrangement) and is placed by `place` in its parent's content rect, at the size the
  caller's measure gives it (see `lay`). `margin` an int >= 0.
- `Attached(rect, side, flipped)`: the placed `Rect`, the side it ended on (one of
  `SIDES`) and whether that is the opposite of the side asked for.

Inputs: `w`, `h`, `margin`, `gap`: ints >= 0; `within`, `target`, `screen`: {Rect}s;
  `at` one of `PLACES`; `side` one of `SIDES` ("below", "above", "right", "left");
  `align` one of `ALIGNS` ("start", "centre", "center", "end").
Outputs: a `Rect`; an `Attached`.
Errors: `TypeError` when a size, `margin` or `gap` is not an int (a `bool` included)
  or a rect argument is not a `Rect`; `ValueError` when a size, `margin` or `gap` is
  negative, or `at`, `side` or `align` is unknown. Assigning a field raises
  `dataclasses.FrozenInstanceError`.
Effects: none.

Usage:
    from cure.core.geometry import Rect
    from cure.draw.layout.anchor import place, attach
    screen = Rect(0, 0, 80, 24)
    place(20, 5, screen)                                # Rect(30, 9, 20, 5)
    place(20, 5, screen, "bottom-right", margin=1)      # Rect(59, 18, 20, 5)
    place(100, 5, screen, "top")                        # Rect(0, 0, 80, 5): clamped
    attach(20, 5, Rect(10, 20, 6, 1), screen)
    #   Attached(Rect(10, 15, 20, 5), "above", True): no room below, flipped
    attach(20, 5, Rect(70, 2, 6, 1), screen)
    #   Attached(Rect(60, 3, 20, 5), "below", False): slid left into the screen
    attach(8, 1, Rect(10, 5, 4, 1), screen, side="right", gap=1).rect   # Rect(15, 5, 8, 1)
"""

from dataclasses import dataclass

from cure.core.geometry import Rect

from .boxmodel import inset

PLACES = ("centre", "center", "top", "bottom", "left", "right",
          "top-left", "top-right", "bottom-left", "bottom-right")
SIDES = ("below", "above", "right", "left")
ALIGNS = ("start", "centre", "center", "end")


@dataclass(frozen=True)
class At:
    """An out-of-flow child placed by `place` in its parent's content rect."""

    at: str = "centre"
    margin: int = 0

    def __post_init__(self) -> None:
        if self.at not in PLACES:
            raise ValueError(f"at must be one of {PLACES}, got {self.at!r}")
        if not isinstance(self.margin, int) or isinstance(self.margin, bool):
            raise TypeError(f"margin must be an int, got {type(self.margin).__name__}")
        if self.margin < 0:
            raise ValueError(f"margin must be >= 0, got {self.margin}")


@dataclass(frozen=True)
class Attached:
    """Where `attach` put an overlay: its rect, the side it ended on, flipped or not."""

    rect: Rect
    side: str
    flipped: bool


def place(w: int, h: int, within: Rect, at: str = "centre", margin: int = 0) -> Rect:
    """A `w` x `h` overlay at `at` inside `within` less `margin`, clamped to fit."""
    _sizes(w=w, h=h, margin=margin)
    _rects(within=within)
    if at not in PLACES:
        raise ValueError(f"at must be one of {PLACES}, got {at!r}")
    area = inset(within, margin)
    w, h = min(w, area.w), min(h, area.h)
    if "left" in at:
        x = area.x
    elif "right" in at:
        x = area.right - w
    else:
        x = area.x + (area.w - w) // 2
    if at.startswith("top"):
        y = area.y
    elif at.startswith("bottom"):
        y = area.bottom - h
    else:
        y = area.y + (area.h - h) // 2
    return Rect(x, y, w, h)


def attach(w: int, h: int, target: Rect, screen: Rect, side: str = "below",
           align: str = "start", gap: int = 0) -> Attached:
    """A `w` x `h` overlay beside `target`, flipped and clamped into `screen`."""
    _sizes(w=w, h=h, gap=gap)
    _rects(target=target, screen=screen)
    if side not in SIDES:
        raise ValueError(f"side must be one of {SIDES}, got {side!r}")
    if align not in ALIGNS:
        raise ValueError(f"align must be one of {ALIGNS}, got {align!r}")
    w, h = min(w, screen.w), min(h, screen.h)
    room = {"below": screen.bottom - (target.bottom + gap), "above": target.y - gap - screen.y,
            "right": screen.right - (target.right + gap), "left": target.x - gap - screen.x}
    need = {"below": h, "above": h, "right": w, "left": w}
    ended, flipped = side, False
    if need[side] > room[side] and need[side] <= room[_OPPOSITE[side]]:
        ended, flipped = _OPPOSITE[side], True
    x, y = _beside(w, h, target, ended, align, gap)
    x = max(screen.x, min(x, screen.right - w))
    y = max(screen.y, min(y, screen.bottom - h))
    return Attached(Rect(x, y, w, h), ended, flipped)


_OPPOSITE = {"below": "above", "above": "below", "right": "left", "left": "right"}


def _sizes(**values: object) -> None:
    for name, value in values.items():
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{name} must be an int, got {type(value).__name__}")
        if value < 0:
            raise ValueError(f"{name} must be >= 0, got {value}")


def _rects(**values: object) -> None:
    for name, value in values.items():
        if not isinstance(value, Rect):
            raise TypeError(f"{name} must be a Rect, got {type(value).__name__}")


def _lined(start: int, length: int, size: int, align: str) -> int:
    """The cross-axis start of `size` cells against a target span, by `align`."""
    if align == "end":
        return start + length - size
    if align in ("centre", "center"):
        return start + (length - size) // 2
    return start


def _beside(w: int, h: int, target: Rect, side: str, align: str, gap: int) -> "tuple[int, int]":
    """Step 4: the position on `side` of `target`, `gap` away, lined up by `align`."""
    if side == "below":
        return _lined(target.x, target.w, w, align), target.bottom + gap
    if side == "above":
        return _lined(target.x, target.w, w, align), target.y - gap - h
    if side == "right":
        return target.right + gap, _lined(target.y, target.h, h, align)
    return target.x - gap - w, _lined(target.y, target.h, h, align)
