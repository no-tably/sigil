"""[Ink]: a 24-bit value + DECLARED tty256 / tty16 fallbacks, realized at the depth the
{Caps} it is given allow; nearest-colour only on opt-in.

Kind: service (a data class, constants and pure functions).

What it does: holds the colour vocabulary every other Style module stands on (the 16
names in index order, the colour depths, the xterm palette) and realizes an ink at a
terminal's depth. An `Ink` is a palette-declared colour: a name, a 24-bit value and
up to two declared fallbacks, `tty256` (an index 0..255) and `tty16` (one of the 16
names). Declared fallbacks win; nearest-colour matching runs only when the caller
passes `nearest=True` (README decision 1: nearest-of-nine maths once turned a rose
into grey).

Depth. Style reads exactly one attribute of a {Caps}: `caps.depth`, an `int`, one of
`DEPTHS`:

- `NO_COLOUR` (0): no colour at all (NO_COLOR, a dumb terminal);
- `COLOURS_16` (16): the 16 ANSI colours (SGR 30..37, 90..97, 40..47, 100..107);
- `COLOURS_256` (256): the xterm 256-colour palette (`38;5;n`);
- `TRUECOLOUR` (24): 24-bit colour (`38;2;r;g;b`).

Any object with a `depth` attribute serves (a test may pass
`types.SimpleNamespace(depth=256)`); Style never imports Core's `{Caps}` and reads
nothing else from it. `depth_of(caps)` raises `ValueError` when `caps.depth` is not an
`int` among `DEPTHS` (`bool` is refused: `True` is not a depth); an object without
`depth` raises `AttributeError`, as Python does.

Realizing an ink (`realize_ink(ink, caps, nearest=False)`), with D = `depth_of(caps)`.
The result is a *shade*: `None` (no colour: the terminal's default), an `int` index
0..255, or an `(r, g, b)` tuple of ints 0..255.

- D = 0: `None`.
- D = 24: `ink.rgb`.
- D = 256: the first declared fallback the depth can show: `ink.tty256`, else the
  index of `ink.tty16` (`NAMES.index(ink.tty16)`), else `nearest256(ink.rgb)` when
  `nearest`, else `None`.
- D = 16: `NAMES.index(ink.tty16)`, else `ink.tty256` when it is below 16, else
  `nearest16(ink.rgb)` when `nearest`, else `None`.

So with no declared fallback a lower depth gets no colour (`None`, drawn in the
terminal's default) unless the caller opts in to nearest-colour.

The xterm palette (`palette_rgb(index)`, fixed, the same on every run):

- 0..15: `XTERM16[index]` (xterm's defaults; a real terminal's may differ, which is
  why `nearest16` is opt-in).
- 16..231: the 6x6x6 cube: with `n = index - 16`, `r, g, b = n // 36, n // 6 % 6,
  n % 6`, each mapped through the levels `(0, 95, 135, 175, 215, 255)`;
  e.g. 16 -> (0, 0, 0), 196 -> (255, 0, 0), 231 -> (255, 255, 255).
- 232..255: the grey ramp, `v = 8 + 10 * (index - 232)`, `(v, v, v)`;
  232 -> (8, 8, 8), 255 -> (238, 238, 238).

Nearest colour (only ever called on opt-in): the candidate with the least squared
Euclidean distance in RGB, `(r1-r2)**2 + (g1-g2)**2 + (b1-b2)**2`, ties going to the
lowest index. `nearest16(rgb)` chooses among indices 0..15 (`XTERM16`);
`nearest256(rgb)` chooses among 16..255 only (the cube and the greys, whose values do
not vary by terminal). E.g. `nearest16((250, 10, 10)) == 9`,
`nearest256((255, 0, 0)) == 196`, `nearest256((0, 0, 0)) == 16`.

Hex (`parse_hex(text)`): `"#rrggbb"` or `"#rgb"`, hex digits in either case, exactly
that length; `"#rgb"` doubles each digit (`"#abc"` is `"#aabbcc"`). Gives the
`(r, g, b)` tuple, or `None` for any other `str`.

Data (frozen dataclass, checked on construction):
- `Ink(name: str, rgb: tuple[int, int, int], tty256: int | None = None,
  tty16: str | None = None)`. `name` any `str` (the palette's name for it); `rgb` a
  `tuple` of exactly three `int`s, each 0..255; `tty256` `None` or an `int` 0..255;
  `tty16` `None` or one of `NAMES`. `bool` is not accepted where an `int` is.

Inputs: `caps`: any object with `depth`. `ink`: an `Ink`. `rgb`: an `(r, g, b)` tuple
  of ints 0..255. `index`: an int 0..255. `text`: a `str`.
Outputs: `depth_of`: an int in `DEPTHS`. `realize_ink`: a shade (`None`, an int 0..255,
  or an `(r, g, b)` tuple). `nearest16`: an int 0..15. `nearest256`: an int 16..255.
  `palette_rgb`: an `(r, g, b)` tuple. `parse_hex`: an `(r, g, b)` tuple or `None`.
Errors: `Ink(...)`: `TypeError` when a field has the wrong type (`name` not a `str`,
  `rgb` not a tuple, a component / `tty256` not an `int` or a `bool`, `tty16` not a
  `str`); `ValueError` when it is out of range (`rgb` not of length 3, a component or
  `tty256` outside 0..255, `tty16` not one of `NAMES`). `depth_of`: `ValueError` as
  above. `realize_ink`: `TypeError` when `ink` is not an `Ink`; `ValueError` from
  `depth_of`. `nearest16` / `nearest256`: `TypeError` / `ValueError` when `rgb` is not
  a tuple of three ints 0..255. `palette_rgb`: `TypeError` when `index` is not an
  `int` (or is a `bool`), `ValueError` outside 0..255. `parse_hex`: `TypeError` when
  `text` is not a `str`.
Effects: none.

Invariant: declared_wins — at depths 256 and 16 a declared fallback the depth can show
  is used whether or not `nearest` is passed; `nearest` only fills a missing one.

Usage:
    from types import SimpleNamespace as Caps
    from cure.core.style.ink import Ink, realize_ink, parse_hex
    teal = Ink("teal", parse_hex("#2aa198"), tty256=37, tty16="cyan")
    realize_ink(teal, Caps(depth=24))                 # (42, 161, 152)
    realize_ink(teal, Caps(depth=256))                # 37
    realize_ink(teal, Caps(depth=16))                 # 6
    rose = Ink("rose", (232, 90, 120))
    realize_ink(rose, Caps(depth=16))                 # None: no declared fallback
    realize_ink(rose, Caps(depth=16), nearest=True)   # nearest16((232, 90, 120))
"""

from dataclasses import dataclass
from functools import lru_cache

NAMES: tuple[str, ...] = (
    "black", "red", "green", "yellow", "blue", "magenta", "cyan", "white",
    "bright_black", "bright_red", "bright_green", "bright_yellow",
    "bright_blue", "bright_magenta", "bright_cyan", "bright_white",
)
"""The 16 colour names in index order: `NAMES[i]` is ANSI colour i."""

NO_COLOUR = 0
COLOURS_16 = 16
COLOURS_256 = 256
TRUECOLOUR = 24
DEPTHS: tuple[int, ...] = (NO_COLOUR, COLOURS_16, COLOURS_256, TRUECOLOUR)
"""The values `caps.depth` may take."""

XTERM16: tuple[tuple[int, int, int], ...] = (
    (0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0),
    (0, 0, 238), (205, 0, 205), (0, 205, 205), (229, 229, 229),
    (127, 127, 127), (255, 0, 0), (0, 255, 0), (255, 255, 0),
    (92, 92, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255),
)
"""xterm's default RGB for ANSI colours 0..15, the candidates of `nearest16`."""

CUBE_LEVELS: tuple[int, ...] = (0, 95, 135, 175, 215, 255)
"""The six channel levels of the 256-colour cube (indices 16..231)."""


@dataclass(frozen=True)
class Ink:
    """A palette-declared colour: a 24-bit `rgb` and its DECLARED fallbacks
    (`tty256` an index 0..255, `tty16` one of `NAMES`), checked on construction."""

    name: str
    rgb: tuple[int, int, int]
    tty256: "int | None" = None
    tty16: "str | None" = None

    def __post_init__(self) -> None:
        """Check every field (see the module's Errors)."""
        if not isinstance(self.name, str):
            raise TypeError(f"ink name must be a str, got {type(self.name).__name__}")
        _check_rgb(self.rgb)
        if self.tty256 is not None:
            _check_index(self.tty256, "tty256")
        if self.tty16 is not None:
            if not isinstance(self.tty16, str):
                raise TypeError(f"tty16 must be a str, got {type(self.tty16).__name__}")
            if self.tty16 not in NAMES:
                raise ValueError(f"tty16 must be one of the 16 names, got {self.tty16!r}")

    @property
    def hex(self) -> str:
        """`rgb` as `"#rrggbb"`, lower-case."""
        return _hex(self.rgb)


def depth_of(caps: object) -> int:
    """`caps.depth`, checked to be an int among `DEPTHS` (ValueError otherwise)."""
    depth = caps.depth
    if _is_int(depth) and depth in DEPTHS:
        return depth
    raise ValueError(f"caps.depth must be one of {DEPTHS}, got {depth!r}")


def realize_ink(ink: Ink, caps: object, *, nearest: bool = False) -> "int | tuple[int, int, int] | None":
    """The shade `ink` takes at `caps.depth`, by the ladder in the module docstring."""
    if not isinstance(ink, Ink):
        raise TypeError(f"expected an Ink, got {type(ink).__name__}")
    depth = depth_of(caps)
    if depth == TRUECOLOUR:
        return ink.rgb
    if depth == COLOURS_256:
        if ink.tty256 is not None:
            return ink.tty256
        if ink.tty16 is not None:
            return NAMES.index(ink.tty16)
        return nearest256(ink.rgb) if nearest else None
    if depth == COLOURS_16:
        if ink.tty16 is not None:
            return NAMES.index(ink.tty16)
        if ink.tty256 is not None and ink.tty256 < 16:
            return ink.tty256
        return nearest16(ink.rgb) if nearest else None
    return None


def palette_rgb(index: int) -> tuple[int, int, int]:
    """The RGB of xterm palette entry `index` (0..255), as the module docstring gives it."""
    _check_index(index, "index")
    if index < 16:
        return XTERM16[index]
    if index < 232:
        n = index - 16
        return (CUBE_LEVELS[n // 36], CUBE_LEVELS[n // 6 % 6], CUBE_LEVELS[n % 6])
    v = 8 + 10 * (index - 232)
    return (v, v, v)


def nearest16(rgb: tuple[int, int, int]) -> int:
    """The index 0..15 whose `XTERM16` value is nearest `rgb` (ties: lowest index)."""
    _check_rgb(rgb)
    return _nearest16(*rgb)


def nearest256(rgb: tuple[int, int, int]) -> int:
    """The index 16..255 whose `palette_rgb` is nearest `rgb` (ties: lowest index)."""
    _check_rgb(rgb)
    return _nearest256(*rgb)


def parse_hex(text: str) -> "tuple[int, int, int] | None":
    """`"#rrggbb"` / `"#rgb"` (either case) as `(r, g, b)`; `None` for any other str."""
    if not isinstance(text, str):
        raise TypeError(f"expected a str, got {type(text).__name__}")
    digits = text[1:]
    if not text.startswith("#") or len(digits) not in (3, 6) or not all(d in _HEX for d in digits):
        return None
    if len(digits) == 3:
        digits = "".join(d * 2 for d in digits)
    return tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4))


_HEX = frozenset("0123456789abcdefABCDEF")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_index(value: object, what: str) -> None:
    if not _is_int(value):
        raise TypeError(f"{what} must be an int, got {type(value).__name__}")
    if not 0 <= value <= 255:
        raise ValueError(f"{what} must be 0..255, got {value}")


def _check_rgb(rgb: object) -> None:
    if not isinstance(rgb, tuple):
        raise TypeError(f"rgb must be a tuple, got {type(rgb).__name__}")
    if len(rgb) != 3:
        raise ValueError(f"rgb must have three components, got {len(rgb)}")
    for c in rgb:
        _check_index(c, "an rgb component")


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _nearest(rgb: tuple[int, int, int], indices: range) -> int:
    def distance(i: int) -> int:
        return sum((a - b) ** 2 for a, b in zip(rgb, palette_rgb(i)))

    return min(indices, key=distance)


# The memo (hardening-1 F12: a theme's derived fallbacks ask the same few colours per
# role). Keyed on the three ints only after `_check_rgb`, so `(True, 0, 0)` never meets
# `(1, 0, 0)`'s entry and a tuple subclass shares the plain tuple's. Bounded, as the
# full 2^24 key space is not allowed; lru_cache is thread-safe.
_MEMO_SIZE = 4096


@lru_cache(maxsize=_MEMO_SIZE)
def _nearest16(r: int, g: int, b: int) -> int:
    return _nearest((r, g, b), range(16))


@lru_cache(maxsize=_MEMO_SIZE)
def _nearest256(r: int, g: int, b: int) -> int:
    return _nearest((r, g, b), range(16, 256))


nearest16.cache_info, nearest16.cache_clear = _nearest16.cache_info, _nearest16.cache_clear
nearest256.cache_info, nearest256.cache_clear = _nearest256.cache_info, _nearest256.cache_clear
