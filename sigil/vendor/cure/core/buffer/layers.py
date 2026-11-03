"""[Layers]: z-order; backdrop dim, opaque or none.

Kind: service (a data class and a pure function over {Grid}).

What it does: composes a frame from layers: the base, then overlays (menus, dialogs,
toasts) by z, each a grid placed at a position, painted bottom to top (the painter's
algorithm) into a new grid. Before a layer is painted, its backdrop decides what
happens to everything already painted beneath it.

Data (frozen dataclass, checked on construction):
- `Layer(grid, x=0, y=0, z=0, backdrop="none")`: `grid` a {Grid} (the layer's own
  cells, in layer-local coordinates), `x`, `y` where its top-left cell lands on the
  frame (ints, may be negative), `z` its order (int; higher is nearer the viewer),
  `backdrop` one of `BACKDROPS`:
  - `"none"`: nothing beneath changes; the layer covers only its own footprint (its
    cells are opaque there, every one of them, blanks included);
  - `"dim"`: everything painted so far is dimmed first, `shade(frame, dim=True)` (a
    modal's scrim: the screen behind it still reads, faded);
  - `"opaque"`: everything painted so far is cleared first, `fill(frame)` with
    `BLANK` (nothing behind the layer shows).
  A `Layer` holds the grid it is given (not a copy); do not write into that grid
  while composing.

Operation:
- `compose(layers, w, h) -> Grid`: a NEW `w` x `h` grid, starting all `BLANK`; the
  layers are sorted by `z`, stably (equal `z` keep their given order), and for each in
  turn: its backdrop is applied to the frame so far, then
  `blit(frame, layer.grid, layer.x, layer.y)` ([Grid]: clipped to the frame, wide
  pairs at the edges broken, never split). The base is simply the layer with the
  lowest `z` (usually `Layer(base_grid)`). No layer's grid is changed. `compose((), w, h)`
  is a blank grid.

Inputs: `layers`: an iterable of `Layer` ({Layers}); `w`, `h`: ints >= 0.
Outputs: {Grid}, a new grid.
Errors: `Layer(...)`: `TypeError` when `grid` is not a `Grid` or `x` / `y` / `z` is not
  an `int` (a `bool` included); `ValueError` when `backdrop` is not in `BACKDROPS`.
  `compose`: `TypeError` when `layers` is not iterable or an item is not a `Layer`,
  or `w` / `h` is not an `int`; `ValueError` when `w < 0` or `h < 0`.
Effects: none (the result is new; the inputs are only read).

Usage:
    from cure.core.buffer.grid import Grid, put
    from cure.core.buffer.layers import Layer, compose
    base = put(Grid(10, 3), 0, 1, "background")
    box = put(Grid(4, 1), 0, 0, "menu")
    frame = compose([Layer(base), Layer(box, x=3, y=1, z=1, backdrop="dim")], 10, 3)
    # row 1: "bac" dimmed, "menu", "und" dimmed; rows 0 and 2: blanks with Style(dim=True)
"""

from collections.abc import Iterable
from dataclasses import dataclass

from .grid import Grid, blit, fill, shade

BACKDROPS = ("none", "dim", "opaque")


@dataclass(frozen=True)
class Layer:
    """One layer of a frame: a grid at (x, y), its z-order and its backdrop."""

    grid: Grid
    x: int = 0
    y: int = 0
    z: int = 0
    backdrop: str = "none"

    def __post_init__(self) -> None:
        if not isinstance(self.grid, Grid):
            raise TypeError(f"grid must be a Grid, got {type(self.grid).__name__}")
        for name in ("x", "y", "z"):
            _int(getattr(self, name), name)
        if self.backdrop not in BACKDROPS:
            raise ValueError(f"backdrop must be one of {BACKDROPS}, got {self.backdrop!r}")


def compose(layers: "Iterable[Layer]", w: int, h: int) -> Grid:
    """A new w x h grid: the layers painted by z (stable), each after its backdrop."""
    if not isinstance(layers, Iterable):
        raise TypeError(f"layers must be an iterable of Layer, got {type(layers).__name__}")
    layers = list(layers)
    for layer in layers:
        if not isinstance(layer, Layer):
            raise TypeError(f"expected a Layer, got {type(layer).__name__}")
    frame = Grid(w, h)
    for layer in sorted(layers, key=lambda layer: layer.z):
        _backdrop(frame, layer.backdrop)
        blit(frame, layer.grid, layer.x, layer.y)
    return frame


def _backdrop(frame: Grid, backdrop: str) -> None:
    if backdrop == "dim":
        shade(frame, dim=True)
    elif backdrop == "opaque":
        fill(frame)


def _int(value: object, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
