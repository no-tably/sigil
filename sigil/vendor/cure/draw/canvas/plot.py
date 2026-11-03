"""[Plot]: braille / half-block / sextant sub-cell plots.

Kind: service (a mutable dot-grid class, contract tables and pure functions).

What it does: plots in dots finer than a cell. A `Dots` grid holds the dots of a
plot `w` x `h` cells in one MODE; `fold` turns it into one glyph per cell, `plot`
puts those glyphs on a canvas (into the texts layer, as [Labels] would, skipping
cells with no dot so the strokes under them still show), and `bar` / `spark` give
the eighth-block bars of gauges and sparklines. The {Charset} decides which modes a
terminal may use (`charset.plots`, finest first); the code points of braille,
sextants, quadrants and half blocks are computed here, as [Charset] states.

Modes (`CELL`, the dots per cell as `(across, down)`; the names are [Charset]'s
`PLOTS`):
`"braille"` (2, 4), `"sextant"` (2, 3), `"quadrant"` (2, 2), `"half"` (1, 2),
`"block"` (1, 1), `"ascii"` (1, 1).

A cell's dots are BITS, dot `(dx, dy)` within the cell (`dx` across, `dy` down from
its top-left) being:
- braille: `(0,0) 0x01, (0,1) 0x02, (0,2) 0x04, (1,0) 0x08, (1,1) 0x10, (1,2) 0x20,
  (0,3) 0x40, (1,3) 0x80` (Unicode's dot numbering);
- sextant and quadrant: `1 << (dy * 2 + dx)`;
- half: `1 << dy` (top 1, bottom 2);
- block and ascii: `1`.

`cell_glyph(mode, bits, charset) -> str`, the glyph of a cell's bits (`""` for 0,
which draws nothing):
- braille: `chr(0x2800 + bits)`;
- sextant: `"█"` for 63, `"▌"` for 21 (the left column), `"▐"` for 42 (the right
  column), else `chr(0x1FB00 + bits - 1 - (bits > 21) - (bits > 42))` (Unicode's
  sextants U+1FB00..U+1FB3B, which leave out those two);
- quadrant: `QUADRANTS[bits]`, `QUADRANTS = " ▘▝▀▖▌▞▛▗▚▐▜▄▙▟█"`;
- half: `"▀"` (1), `"▄"` (2), `"█"` (3);
- block: `charset.glyph("block.full")`;
- ascii: `"#"`.

`Dots` (a mutable class): `Dots(mode, w, h)`, `w` x `h` cells (ints >= 0), no dot set.
- `mode`, `w`, `h` (read-only); `size -> (w * across, h * down)`, the dot grid's size.
- `set(px, py, on=True) -> bool`: dot `(px, py)` set (or cleared, `on=False`); `True`
  when it lies inside `size`, `False` (and nothing changes) when it does not: a plot
  is clipped to its grid, dot by dot.
- `get(px, py) -> bool`: whether the dot is set (`False` outside).
- `line(x0, y0, x1, y1) -> None`: the dots of the integer Bresenham line from
  `(x0, y0)` to `(x1, y1)`, both ends included, each `set` (those outside dropped):
      dx = abs(x1 - x0); sx = 1 if x0 < x1 else -1
      dy = -abs(y1 - y0); sy = 1 if y0 < y1 else -1
      err = dx + dy
      loop: set(x0, y0); stop when (x0, y0) == (x1, y1); e2 = 2 * err
            if e2 >= dy: err += dy; x0 += sx
            if e2 <= dx: err += dx; y0 += sy
- `bits(cx, cy) -> int`: cell `(cx, cy)`'s bits (`0` outside the grid).
Coordinates may be any ints (negative ones lie outside).

Operations:
- `fold(dots, charset) -> tuple[tuple[str, ...], ...]`: `h` rows of `w` glyphs,
  `cell_glyph(dots.mode, dots.bits(cx, cy), charset)` each (`""` for an empty cell).
- `plot(canvas, x, y, dots, charset, style=None, *, tag=None) -> int`: for each cell
  `(cx, cy)` whose glyph `g` is not `""`, the text at `(x + cx, y + cy)` becomes
  `Cell(g, 1, style)` (a narrow glyph, written as [Labels] writes one: no_orphan_half,
  the tag, the extent: each through [Strokes]' public `place(canvas, x + cx, y + cy,
  (Cell(g, 1, style),), tag=tag)`, Q9b, never the Canvas's private `_place`). Cells
  with no dot are not written. Returns the number of
  cells written.
- `mode(charset, want=None) -> str`: the mode to plot in: `want` when it is in
  `charset.plots`; else `charset.plots[0]` (the finest the charset allows); else,
  when `charset.plots` is empty, `"ascii"`.
- `bar(eighths, charset, *, axis="h") -> str`: a bar `eighths` eighths of a cell
  long, from the token `f"block.eighths.{axis}"` (9 code points, index `i` = `i`
  eighths filled): `eighths // 8` times its last code point, then its code point
  `eighths % 8` when that is not 0. `axis` `"h"` reads left to right; `"v"` gives the
  cells from the bottom up (one per row). `bar(0, cs) == ""`.
- `spark(levels, charset) -> str`: one cell per level (each an int 0..8), the code
  point `level` of `"block.eighths.v"`: a sparkline.

Inputs: `Dots`: a mode in `CELL`, ints. `fold`: a `Dots`, a charset. `plot`: a
  {Canvas}, ints >= 0, a `Dots`, a charset, a style, a tag. `mode`: a charset, a mode
  or `None`. `bar`: an int >= 0, a charset, `"h"` or `"v"`. `spark`: an iterable of
  ints. The charset: any object with `glyph(token: str) -> str` and `plots` (a tuple
  of mode names), [Charset]'s {Charset}.
Outputs: as stated.
Errors: `TypeError` for a coordinate, size, bits value, eighths or level that is not
  an `int` (a `bool` included), a `dots` that is not a `Dots`, or a `canvas` that is
  not a `Canvas`; `ValueError` for a mode not in `CELL` (`want` included), a negative
  `w`, `h`, `x`, `y` or `eighths`, bits outside the mode's range (0..255 braille,
  0..63 sextant, 0..15 quadrant, 0..3 half, 0..1 block and ascii), an `axis` other
  than `"h"` / `"v"`, a level outside 0..8, or an eighths token whose glyph is not
  exactly 9 code points.
Effects: `Dots.set` / `line` change that grid; `plot` writes into the canvas
  argument as stated; the rest none.

Usage:
    from cure.draw.canvas import Canvas, Dots, fold, plot, bar, spark, mode
    from cure.draw.theme.charset import Charset
    cs = Charset()
    d = Dots("braille", 2, 1)
    d.line(0, 0, 3, 3)
    fold(d, cs)                              # (("⠑", "⢄"),)
    c = Canvas()
    plot(c, 0, 0, d, cs)                     # 2
    bar(11, cs), spark([0, 4, 8], cs)        # ("█▍", " ▄█")
    mode(cs), mode(cs, "half")               # ("braille", "half")
"""

from cure.core.text import Cell

from .junctions import _check_int
from .strokes import Canvas, _check_canvas, place

CELL: dict = {
    "braille": (2, 4), "sextant": (2, 3), "quadrant": (2, 2),
    "half": (1, 2), "block": (1, 1), "ascii": (1, 1),
}
"""Dots per cell, (across, down), per plot mode."""

BRAILLE: dict = {
    (0, 0): 0x01, (0, 1): 0x02, (0, 2): 0x04, (1, 0): 0x08,
    (1, 1): 0x10, (1, 2): 0x20, (0, 3): 0x40, (1, 3): 0x80,
}
"""Braille: dot (dx, dy) -> its bit."""

QUADRANTS: str = " ▘▝▀▖▌▞▛▗▚▐▜▄▙▟█"
"""Quadrant glyphs by bits (TL 1, TR 2, BL 4, BR 8)."""

_TOP = {"braille": 255, "sextant": 63, "quadrant": 15, "half": 3, "block": 1, "ascii": 1}


class Dots:
    """A grid of dots `w` x `h` cells in one plot mode (mutable)."""

    def __init__(self, mode: str, w: int, h: int) -> None:
        _check_mode(mode)
        _check_int(w, "w")
        _check_int(h, "h")
        if w < 0 or h < 0:
            raise ValueError(f"a plot's size must be >= 0, got {w} x {h}")
        self._mode, self._w, self._h = mode, w, h
        self._on: set = set()

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def w(self) -> int:
        return self._w

    @property
    def h(self) -> int:
        return self._h

    @property
    def size(self) -> "tuple[int, int]":
        """The dot grid's size, (w * across, h * down)."""
        across, down = CELL[self._mode]
        return self._w * across, self._h * down

    def set(self, px: int, py: int, on: bool = True) -> bool:
        """Set (or clear) a dot; False, changing nothing, when it lies outside."""
        if not self._inside(px, py):
            return False
        if on:
            self._on.add((px, py))
        else:
            self._on.discard((px, py))
        return True

    def get(self, px: int, py: int) -> bool:
        """Whether a dot is set (False outside)."""
        _check_int(px)
        _check_int(py)
        return (px, py) in self._on

    def line(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """Set the dots of the Bresenham line between two dots, both ends included."""
        for v in (x0, y0, x1, y1):
            _check_int(v)
        dx, sx = abs(x1 - x0), 1 if x0 < x1 else -1
        dy, sy = -abs(y1 - y0), 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.set(x0, y0)
            if (x0, y0) == (x1, y1):
                return
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def bits(self, cx: int, cy: int) -> int:
        """Cell (cx, cy)'s dot bits in this mode's numbering (0 outside)."""
        _check_int(cx)
        _check_int(cy)
        across, down = CELL[self._mode]
        out = 0
        for dy in range(down):
            for dx in range(across):
                if (cx * across + dx, cy * down + dy) in self._on:
                    out |= _bit(self._mode, dx, dy)
        return out

    def _inside(self, px: int, py: int) -> bool:
        _check_int(px)
        _check_int(py)
        w, h = self.size
        return 0 <= px < w and 0 <= py < h


def cell_glyph(mode: str, bits: int, charset: object) -> str:
    """The glyph of a cell's dot bits in `mode`, "" for none (see the module)."""
    _check_mode(mode)
    _check_int(bits, "bits")
    if not 0 <= bits <= _TOP[mode]:
        raise ValueError(f"{mode} bits must be in 0..{_TOP[mode]}, got {bits}")
    if bits == 0:
        return ""
    if mode == "braille":
        return chr(0x2800 + bits)
    if mode == "sextant":
        special = {63: "█", 21: "▌", 42: "▐"}
        return special.get(bits) or chr(0x1FB00 + bits - 1 - (bits > 21) - (bits > 42))
    if mode == "quadrant":
        return QUADRANTS[bits]
    if mode == "half":
        return " ▀▄█"[bits]
    if mode == "block":
        return charset.glyph("block.full")
    return "#"


def fold(dots: Dots, charset: object) -> "tuple[tuple[str, ...], ...]":
    """One glyph per cell of the dot grid, "" for an empty cell."""
    _check_dots(dots)
    return tuple(tuple(cell_glyph(dots.mode, dots.bits(cx, cy), charset) for cx in range(dots.w))
                 for cy in range(dots.h))


def plot(canvas: Canvas, x: int, y: int, dots: Dots, charset: object, style: object = None,
         *, tag: object = None) -> int:
    """Put the folded glyphs on the canvas at (x, y), skipping empty cells; returns the count."""
    _check_canvas(canvas)
    _check_int(x)
    _check_int(y)
    if x < 0 or y < 0:
        raise ValueError(f"coordinates must be >= 0, got {(x, y)}")
    _check_dots(dots)
    count = 0
    for cy, row in enumerate(fold(dots, charset)):
        for cx, g in enumerate(row):
            if g:
                place(canvas, x + cx, y + cy, (Cell(g, 1, style),), tag=tag)
                count += 1
    return count


def mode(charset: object, want: "str | None" = None) -> str:
    """`want` when the charset allows it, else its finest plot mode, else "ascii"."""
    if want is not None:
        _check_mode(want)
    plots = tuple(charset.plots)
    if want in plots:
        return want
    return plots[0] if plots else "ascii"


def bar(eighths: int, charset: object, *, axis: str = "h") -> str:
    """An eighth-block bar `eighths` eighths long (see the module)."""
    _check_int(eighths, "eighths")
    if eighths < 0:
        raise ValueError(f"eighths must be >= 0, got {eighths}")
    if axis not in ("h", "v"):
        raise ValueError(f"axis must be 'h' or 'v', got {axis!r}")
    points = _eighths(charset, axis)
    whole, part = divmod(eighths, 8)
    return points[8] * whole + (points[part] if part else "")


def spark(levels: "object", charset: object) -> str:
    """A sparkline: one eighth-block cell per level 0..8."""
    levels = tuple(levels)
    for level in levels:
        _check_int(level, "level")
        if not 0 <= level <= 8:
            raise ValueError(f"a level must be in 0..8, got {level}")
    points = _eighths(charset, "v")
    return "".join(points[level] for level in levels)


def _bit(mode: str, dx: int, dy: int) -> int:
    if mode == "braille":
        return BRAILLE[(dx, dy)]
    if mode in ("sextant", "quadrant"):
        return 1 << (dy * 2 + dx)
    if mode == "half":
        return 1 << dy
    return 1


def _eighths(charset: object, axis: str) -> str:
    points = charset.glyph(f"block.eighths.{axis}")
    if len(points) != 9:
        raise ValueError(f"block.eighths.{axis} must be 9 code points, got {points!r}")
    return points


def _check_mode(mode: object) -> None:
    if mode not in CELL:
        raise ValueError(f"mode must be one of {tuple(CELL)}, got {mode!r}")


def _check_dots(dots: object) -> None:
    if not isinstance(dots, Dots):
        raise TypeError(f"expected a Dots, got {type(dots).__name__}")
