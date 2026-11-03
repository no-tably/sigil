"""{HitMap}: rect → id per layer, the smallest rect wins: Paint writes it, Input reads it.

Kind: data (frozen dataclasses with pure methods). A hit map is a value: Paint builds
it as it paints (each interactive node adds its rect and its tag), the frame returns
it beside the buffer, and Input's router asks it what is under the mouse. Nothing
holds one between frames but the app.

Data:
- `Hit(rect: Rect, tag, layer: int = 0)`: one region. `tag` is the id the app or a
  widget gave the region: any hashable value except `None`. `layer` is its z-order
  (an overlay's regions sit on a higher layer than the base's).
- `HitMap(hits: tuple[Hit, ...] = ())`: the regions in the order they were added.
  `HitMap()` is the empty map. Equality is field by field (order included).

Operations (each returns a new value; none changes `self`):
- `add(rect, tag, layer=0) -> HitMap`: `HitMap(hits + (Hit(rect, tag, layer),))`. An
  empty rect may be added; it never hits.
- `stack(x, y) -> tuple[Hit, ...]`: every hit whose rect contains cell (x, y)
  (`Rect.contains`), in precedence order: the highest `layer` first; within a layer
  the smallest `rect.area` first; among equal areas the one added LATER first (it was
  painted on top). `()` when nothing is there. The router walks it to bubble an
  event outwards.
- `at(x, y)`: the tag of `stack(x, y)[0]`, or `None` when the stack is empty. So the
  topmost layer wins, and inside it the smallest rect: a button inside an overlay
  beats the overlay's own region, and a region on a higher layer beats any region
  below it, however small.
- `moved(dx, dy) -> HitMap`: every rect moved by (dx, dy) (`Rect.moved`), tags,
  layers and order kept (a layer-local map placed on screen).
- `merged(other) -> HitMap`: `HitMap(self.hits + other.hits)` (other's regions count as
  added after self's).

Inputs: `rect` a {Rect}; `tag` hashable, not `None`; `layer`, `x`, `y`, `dx`, `dy`
  ints (never `bool`); `other` a `HitMap`.
Outputs: a `HitMap`, a tuple of `Hit`, or a tag (or `None`).
Errors: `TypeError` when `rect` is not a `Rect`, `tag` is unhashable, `layer` or a
  coordinate is not an `int` (a `bool` included), `hits` is not a tuple of `Hit`, or
  `other` is not a `HitMap`; `ValueError` when `tag` is `None`. The same checks run
  when a `Hit` or `HitMap` is constructed directly. Assigning a field raises
  `dataclasses.FrozenInstanceError`.
Effects: none.

Usage:
    from cure.core.geometry.rect import Rect
    from cure.core.geometry.hitmap import HitMap
    hits = (HitMap()
            .add(Rect(0, 0, 80, 24), "screen")
            .add(Rect(10, 5, 20, 6), "dialog", layer=1)
            .add(Rect(12, 9, 4, 1), "ok", layer=1))
    hits.at(13, 9)                  # "ok": smallest on the top layer
    hits.at(11, 6)                  # "dialog"
    hits.at(0, 0)                   # "screen"
    hits.at(90, 0)                  # None
    [h.tag for h in hits.stack(13, 9)]   # ["ok", "dialog", "screen"]
"""

from collections.abc import Hashable
from dataclasses import dataclass

from .rect import Rect


@dataclass(frozen=True)
class Hit:
    """One region of a {HitMap}: a `rect`, its `tag` (hashable, not None) and its `layer`."""

    rect: Rect
    tag: Hashable
    layer: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.rect, Rect):
            raise TypeError(f"rect must be a Rect, got {type(self.rect).__name__}")
        if self.tag is None:
            raise ValueError("tag must not be None")
        try:
            hash(self.tag)
        except TypeError:
            raise TypeError(f"tag must be hashable, got {type(self.tag).__name__}") from None
        _int(self.layer, "layer")


@dataclass(frozen=True)
class HitMap:
    """{HitMap}: regions in the order added; the smallest rect of the top layer wins."""

    hits: "tuple[Hit, ...]" = ()

    def __post_init__(self) -> None:
        if not isinstance(self.hits, tuple) or not all(isinstance(h, Hit) for h in self.hits):
            raise TypeError("hits must be a tuple of Hit")

    def add(self, rect: Rect, tag: Hashable, layer: int = 0) -> "HitMap":
        """A new map with `Hit(rect, tag, layer)` appended."""
        return HitMap(self.hits + (Hit(rect, tag, layer),))

    def stack(self, x: int, y: int) -> "tuple[Hit, ...]":
        """Every hit containing (x, y): highest layer, then smallest area, then latest first."""
        _int(x, "x")
        _int(y, "y")
        found = [(i, h) for i, h in enumerate(self.hits) if h.rect.contains(x, y)]
        found.sort(key=lambda ih: (-ih[1].layer, ih[1].rect.area, -ih[0]))
        return tuple(h for _, h in found)

    def at(self, x: int, y: int) -> "Hashable | None":
        """The tag that wins at (x, y), or None."""
        top = self.stack(x, y)
        return top[0].tag if top else None

    def moved(self, dx: int, dy: int) -> "HitMap":
        """Every rect moved by (dx, dy)."""
        return HitMap(tuple(Hit(h.rect.moved(dx, dy), h.tag, h.layer) for h in self.hits))

    def merged(self, other: "HitMap") -> "HitMap":
        """`self`'s hits, then `other`'s."""
        if not isinstance(other, HitMap):
            raise TypeError(f"expected a HitMap, got {type(other).__name__}")
        return HitMap(self.hits + other.hits)


def _int(value: object, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
