"""[Junctions]: a mask and a weight → the charset's box-drawing glyph.

Kind: service (data classes, contract tables and pure functions).

What it does: a stroke cell is a DIRECTION MASK, four bits for the arms it has, and
one WEIGHT. `link(path)` gives the masks a {Path} lays down ({Path} => {Masks}, for
[Strokes] and, through the package, Graph's [Diagram]); `join` is the rule by which a
cell already holding a stroke takes another; `part` / `token` / `glyph` turn a mask
and a weight into the {Charset}'s box-drawing glyph. Glyphs are never picked here:
they come from the charset given, by token.

Directions (module constants, part of this contract): `N = 1`, `E = 2`, `S = 4`,
`W = 8` (an arm up, right, down, left). A mask is an `int` 0..15, the OR of its arms;
`OPPOSITE = {N: S, S: N, E: W, W: E}`.

Weights (`WEIGHTS`, in this order): `"light"`, `"heavy"`, `"double"`, `"dashed"`,
`"dotted"`, `"heavy-dashed"` (six, sigil's kit, README decision 5; the last is exactly
the string `"heavy-dashed"`). `RANK = {"heavy": 4, "double": 3, "light": 2,
"dashed": 1, "heavy-dashed": 1, "dotted": 0}` (the kit's ranks: heavy-dashed ranks
with dashed, below light): where strokes of two weights meet, the cell takes the
higher-ranked one; where the two ranks are equal (the same weight, or `dashed` and
`heavy-dashed`) the stroke already in the cell keeps it (`join`, below). So a
heavy-dashed line joined into a light one draws light (`┼`), and of a dashed and a
heavy-dashed line joined, the first drawn decides (`┼` or `╋`).

Each weight's glyphs (what `glyph` gives with [Charset]'s `UNICODE`, by part; every
weight's token is its own, `border.<weight>.<part>`, and the glyphs are the charset's
rows, never picked here):

    weight         h  v  corners tl tr bl br   tees l r t b   cross
    light          ─  │  ┌ ┐ └ ┘ (rounded: ╭ ╮ ╰ ╯)  ├ ┤ ┬ ┴   ┼
    heavy          ━  ┃  ┏ ┓ ┗ ┛                  ┣ ┫ ┳ ┻   ╋
    double         ═  ║  ╔ ╗ ╚ ╝                  ╠ ╣ ╦ ╩   ╬
    dashed         ╌  ╎  ┌ ┐ └ ┘                  ├ ┤ ┬ ┴   ┼
    dotted         ┄  ┆  ┌ ┐ └ ┘                  ├ ┤ ┬ ┴   ┼
    heavy-dashed   ╍  ╏  ┏ ┓ ┗ ┛                  ┣ ┫ ┳ ┻   ╋

That is the kit's rule, held in [Charset]'s data: a dashed weight's own glyphs are
its straight ones (`h`, `v`: a straight run and an end cell, mask `N`, `S`, `N|S`,
`E`, `W` or `E|W`, draw `╌ ╎` / `┄ ┆` / `╍ ╏`); box drawing has no dashed corners,
tees or crosses, so at any other mask `dashed` and `dotted` draw the light glyphs and
`heavy-dashed` the heavy ones (the charset's `border.dashed.tl` is `┌`,
`border.heavy-dashed.tl` is `┏`; a theme overriding such a token is honoured, since
the token asked for is the weight's own). `rounded` rounds `light` corners only: a
dashed or dotted corner stays `┌` with `rounded=True`. With [Charset]'s `ASCII` base
every weight draws the plain ASCII box (`h` `-`, `v` `|`, `+` at every corner, tee
and cross) but `heavy` and `double`, whose `h` is `=`.

Mask → part (`PART`, the exact table; the part names are [Charset]'s `PARTS`):

    0                 -> None (no arm: draws nothing)
    N, S, N|S         -> "v"        E, W, E|W         -> "h"
    S|E               -> "tl"       S|W               -> "tr"
    N|E               -> "bl"       N|W               -> "br"
    N|S|E             -> "tee_l"    N|S|W             -> "tee_r"
    E|W|S             -> "tee_t"    E|W|N             -> "tee_b"
    N|E|S|W           -> "cross"

Data (frozen dataclasses):
- `Joint(mask: int, weight: str, style: object = None)`: one stroke cell: its arms,
  its weight (one of `WEIGHTS`) and its style (opaque, compared with `==` only).
  Stored as given.
- `Masks(weight: str, style: object, cells: tuple[tuple[tuple[int, int], int], ...])`:
  what one path lays: `cells` holds `((x, y), mask)` for every cell with a non-zero
  mask, sorted by `(y, x)`, each cell once. `Masks.at(cell) -> int`: the mask at
  `cell` (an `(x, y)` pair), `0` when it is not in `cells`.
- `Path(points, weight: str = "light", style: object = None)`: an orthogonal
  polyline through cells. `points` is any non-empty iterable of `(x, y)` pairs; it is
  stored as a `tuple` of `tuple`s of two ints. Checked on construction: every
  coordinate an `int` (not a `bool`) and `>= 0`; each two consecutive points share
  their `x` or their `y` (a segment is horizontal or vertical; equal points are a
  zero-length segment and allowed); `weight` in `WEIGHTS`.

Operations:
- `link(path, hops=frozenset()) -> Masks` ({Path} => {Masks}): for each segment
  `p -> q` and each unit step `a -> b` along it (direction `d` from `a` to `b`), the
  mask of `a` gains `d` and the mask of `b` gains `OPPOSITE[d]`; masks OR together,
  so a path that revisits a cell joins itself there. Then every cell in `hops` is
  left out (its neighbours along the path keep their arm toward it: a hop-over, see
  [Strokes]). The result is `Masks(path.weight, path.style, cells)`. A path of one
  point, or of equal points only, lays nothing (`cells == ()`).
  Example: `link(Path([(0, 0), (2, 0), (2, 1)]))` has cells
  `(((0, 0), E), ((1, 0), E | W), ((2, 0), W | S), ((2, 1), N))`.
- `join(old, mask, weight, style=None, *, fixed=False) -> Joint`: a cell holding
  `old` (a `Joint`, or `None` for no stroke) takes `mask` of `weight` in `style`.
  `old is None`: `Joint(mask, weight, style)`. Otherwise the arms join,
  `old.mask | mask`, and the weight and style are `(weight, style)` when
  `RANK[weight] > RANK[old.weight]` and not `fixed`, else `old`'s (on equal ranks
  the first stroke keeps the cell, `dashed` against `heavy-dashed` included; a `fixed` cell's weight and style are settled and
  a stroke only joins its arms).
- `part(mask) -> str | None`: `PART[mask]`.
- `token(mask, weight, *, rounded=False) -> str | None`: `None` for mask 0; else
  `f"border.{w}.{part(mask)}"`, `w` being `"rounded"` when `rounded` is true,
  `weight == "light"` and the part is a corner (`tl`, `tr`, `bl`, `br`), else
  `weight`.
- `glyph(mask, weight, charset, *, rounded=False) -> str`: `""` for mask 0; else
  `charset.glyph(token(mask, weight, rounded=rounded))`, and when that is `""`
  `charset.glyph(f"border.light.{part(mask)}")` (a weight, or a part of one, the
  charset has no glyph for draws as light: this holds for every weight, so a charset
  lacking `border.heavy-dashed.tl` draws its `border.light.tl`, not the heavy one).
  [Charset]'s {Charset} has a glyph for every weight's every part (the table above;
  its own ascii fallback covers a token its glyphs lack), so with it the fallback
  never fires; it is for other charsets. Still `""` is returned as `""`; [Strokes]
  draws it as a blank.

Mixed weights: a cell has ONE weight (by `join`), so a heavy line crossing a light one
draws `╋` whole, never a mixed glyph such as `╂` ([Charset] has no mixed tokens).

The charset: any object with `glyph(token: str) -> str` ([Charset]'s {Charset}
satisfies it). That method is the only thing called on it here.

Inputs: `link`: a `Path`, `hops` an iterable of `(x, y)` pairs. `join`: a `Joint` or
  `None`, `mask` an int 1..15, `weight` a str, any style, `fixed` a bool. `part`:
  an int 0..15. `token` / `glyph`: an int 0..15, a str weight, a charset.
Outputs: `link`: {Masks}. `join`: a `Joint`. `part` / `token`: a `str` or `None`.
  `glyph`: a `str`.
Errors: `Path(...)`: `TypeError` when `points` is not an iterable of pairs or a
  coordinate is not an `int` (a `bool` included); `ValueError` for no points, a
  negative coordinate, a diagonal segment, or a weight not in `WEIGHTS`. `link`:
  `TypeError` when `path` is not a `Path`. `join`: `TypeError` when `old` is neither
  `None` nor a `Joint`, or `mask` is not an `int`; `ValueError` when `mask` is not in
  1..15 or `weight` not in `WEIGHTS`. `part` / `token` / `glyph`: `TypeError` for a
  non-`int` mask (a `bool` included), `ValueError` for a mask outside 0..15 or (for
  `token` / `glyph`) a weight not in `WEIGHTS`.
Effects: none.

Usage:
    from cure.draw.canvas.junctions import Path, link, join, glyph, Joint, N, E, S, W
    from cure.draw.theme.charset import ASCII, Charset
    cs = Charset()
    link(Path([(0, 0), (2, 0)])).cells       # (((0, 0), 2), ((1, 0), 10), ((2, 0), 8))
    join(Joint(N | S, "light"), E | W, "heavy")   # Joint(15, "heavy", None)
    glyph(S | E, "light", cs), glyph(S | E, "light", cs, rounded=True)   # "┌", "╭"
    glyph(E | W, "dashed", cs), glyph(N | S, "dashed", cs)               # "╌", "╎"
    glyph(E | W, "dotted", cs), glyph(N, "dotted", cs)                   # "┄", "┆"
    glyph(E, "heavy-dashed", cs), glyph(N | S, "heavy-dashed", cs)       # "╍", "╏"
    glyph(S | E, "dashed", cs), glyph(S | E, "dashed", cs, rounded=True) # "┌", "┌"
    glyph(N | S | E, "dotted", cs), glyph(15, "dotted", cs)              # "├", "┼"
    glyph(S | W, "heavy-dashed", cs), glyph(15, "heavy-dashed", cs)      # "┓", "╋"
    join(Joint(E | W, "heavy-dashed"), N | S, "light")   # Joint(15, "light", None)
    join(Joint(E | W, "dashed"), N | S, "heavy-dashed")  # Joint(15, "dashed", None)
    asc = Charset("ascii", ASCII)
    glyph(E | W, "heavy-dashed", asc), glyph(N | S, "dotted", asc), glyph(S | E, "dashed", asc)   # "-", "|", "+"
"""

from collections.abc import Iterable
from dataclasses import dataclass
from operator import itemgetter

N, E, S, W = 1, 2, 4, 8
OPPOSITE: dict = {N: S, S: N, E: W, W: E}

WEIGHTS: tuple[str, ...] = ("light", "heavy", "double", "dashed", "dotted", "heavy-dashed")
RANK: dict = {"heavy": 4, "double": 3, "light": 2, "dashed": 1, "heavy-dashed": 1, "dotted": 0}

PART: dict = {
    0: None,
    N: "v", S: "v", N | S: "v",
    E: "h", W: "h", E | W: "h",
    S | E: "tl", S | W: "tr", N | E: "bl", N | W: "br",
    N | S | E: "tee_l", N | S | W: "tee_r", E | W | S: "tee_t", E | W | N: "tee_b",
    N | E | S | W: "cross",
}

CORNERS: frozenset = frozenset({"tl", "tr", "bl", "br"})


@dataclass(frozen=True)
class Joint:
    """One stroke cell: its arms (a mask 0..15), its weight and its style."""

    mask: int
    weight: str
    style: object = None


@dataclass(frozen=True)
class Masks:
    """{Masks}: the masks one path lays, `((x, y), mask)` sorted by (y, x)."""

    weight: str
    style: object
    cells: tuple = ()

    def at(self, cell: "tuple[int, int]") -> int:
        """The mask at `cell`, 0 when the path lays nothing there."""
        return dict(self.cells).get(tuple(cell), 0)


@dataclass(frozen=True)
class Path:
    """{Path}: an orthogonal polyline through cells, of one weight and style."""

    points: tuple
    weight: str = "light"
    style: object = None

    def __post_init__(self) -> None:
        points = tuple(_point(p) for p in _iterable(self.points))
        if not points:
            raise ValueError("a path needs at least one point")
        if any(v < 0 for p in points for v in p):
            raise ValueError(f"coordinates must be >= 0, got {points}")
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            if x0 != x1 and y0 != y1:
                raise ValueError(f"diagonal segment {(x0, y0)} -> {(x1, y1)}")
        _check_weight(self.weight)
        object.__setattr__(self, "points", points)


def link(path: Path, hops: "Iterable[tuple[int, int]]" = frozenset()) -> Masks:
    """The masks `path` lays, the cells in `hops` left out (see the module)."""
    if not isinstance(path, Path):
        raise TypeError(f"expected a Path, got {type(path).__name__}")
    skip = {tuple(h) for h in hops}
    masks = _masks(path.points)
    order = sorted(masks, key=_YX)   # Speed: sorted by (y, x) and paired in C
    if skip:
        order = [c for c in order if c not in skip]
    return Masks(path.weight, path.style, tuple(zip(order, map(masks.__getitem__, order))))


_YX = itemgetter(1, 0)   # a cell's sort key, (y, x)


def _masks(points: tuple) -> dict:
    """Each cell's mask along `points` (unsorted): `link`'s rule, each unit step `a -> b`
    giving `a` its direction and `b` the opposite. Speed: one pass per segment, its
    direction worked out once, its interior cells (both arms) by `range`."""
    masks: dict = {}
    get = masks.get
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 == x1:
            if y0 == y1:
                continue
            d, o, step = (S, N, 1) if y1 > y0 else (N, S, -1)
            masks[(x0, y0)] = get((x0, y0), 0) | d
            both = d | o
            for y in range(y0 + step, y1, step):
                masks[(x0, y)] = get((x0, y), 0) | both
            masks[(x1, y1)] = get((x1, y1), 0) | o
        else:
            d, o, step = (E, W, 1) if x1 > x0 else (W, E, -1)
            masks[(x0, y0)] = get((x0, y0), 0) | d
            both = d | o
            for x in range(x0 + step, x1, step):
                masks[(x, y0)] = get((x, y0), 0) | both
            masks[(x1, y1)] = get((x1, y1), 0) | o
    return masks


def join(old: "Joint | None", mask: int, weight: str, style: object = None, *, fixed: bool = False) -> Joint:
    """A cell holding `old` takes `mask` of `weight`: arms OR, the higher rank wins (see the module)."""
    if old is not None and not isinstance(old, Joint):
        raise TypeError(f"expected a Joint or None, got {type(old).__name__}")
    _check_mask(mask, low=1)
    _check_weight(weight)
    if old is None:
        return Joint(mask, weight, style)
    if RANK[weight] > RANK[old.weight] and not fixed:
        return Joint(old.mask | mask, weight, style)
    return Joint(old.mask | mask, old.weight, old.style)


def part(mask: int) -> "str | None":
    """`PART[mask]`: the charset part a mask draws as, None for 0."""
    _check_mask(mask)
    return PART[mask]


def token(mask: int, weight: str, *, rounded: bool = False) -> "str | None":
    """The charset token of a mask and a weight, None for 0 (see the module)."""
    _check_mask(mask)
    _check_weight(weight)
    name = PART[mask]
    if name is None:
        return None
    w = "rounded" if rounded and weight == "light" and name in CORNERS else weight
    return f"border.{w}.{name}"


def glyph(mask: int, weight: str, charset: object, *, rounded: bool = False) -> str:
    """The charset's glyph for a mask and a weight, falling back to light (see the module)."""
    t = token(mask, weight, rounded=rounded)
    if t is None:
        return ""
    return charset.glyph(t) or charset.glyph(f"border.light.{PART[mask]}")


def _check_int(value: object, name: str = "coordinate") -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")


def _check_mask(mask: object, low: int = 0) -> None:
    _check_int(mask, "mask")
    if not low <= mask <= 15:
        raise ValueError(f"mask must be in {low}..15, got {mask}")


def _check_weight(weight: object) -> None:
    if weight not in WEIGHTS:
        raise ValueError(f"weight must be one of {WEIGHTS}, got {weight!r}")


def _iterable(points: object) -> Iterable:
    if isinstance(points, (str, bytes)) or not isinstance(points, Iterable):
        raise TypeError(f"points must be an iterable of (x, y) pairs, got {type(points).__name__}")
    return points


def _point(p: object) -> "tuple[int, int]":
    pair = tuple(_iterable(p))
    if len(pair) != 2:
        raise TypeError(f"a point is an (x, y) pair, got {p!r}")
    for v in pair:
        _check_int(v)
    return pair
