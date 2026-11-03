"""[Virtual]: a virtual terminal: the emitted bytes replayed through Vt; the screen equals
the buffer (the gate is the emitted frame).

Kind: service (a class with explicit state, a frozen dataclass, and pure functions);
no I/O.

What it does: the oracle a frame test asserts against. A frame is checked as the
terminal will see it, not as the buffer says: `show` passes the grid through Buffer's
`show` (the bytes a real terminal would be sent, [Display]'s diff against the front
buffer, SGR from the one seam), then replays those bytes on a Vt `Screen` through Vt's
`apply` (`[Virtual] -> [Vt] : apply({Bytes}) => {Grid}`), the same screen a pane's
program draws on. When every frame of a sequence replays to the screen the buffer
holds, the emitter, the diff and the SGR seam are right for that sequence: a cell left
stale, a pen not reset, a cursor move off by one or a wide glyph sent twice all show
as a cell that differs.

Colours are compared as realized. The bytes carry only what the terminal can show at
`caps.depth`: a colour's theme role never reaches them (replayed colours carry no
role), an ink arrives as its declared fallback, a colour with no shade at the depth
arrives as no colour. So the buffer is compared through `realized(grid, caps)`: the
grid as a terminal at that depth reads it back, which is the form Vt's `Screen` builds
its cells in.

## Realized

`realized_style(style, caps) -> Style | None`: the style a terminal at `caps.depth`
shows for `style`, in the form Vt's [Screen] builds from the SGR it reads. With
`s = style` (`None` taken as `Style()`), `D = depth_of(caps)`, and `shade(c)` Style's
`realize(c, caps)` (no nearest-colour: [Display] sends none), each colour is the
shade written back as a role-less {Colour}: `None` for no shade; an index `i < 16` as
`Colour("name", NAMES[i])` (what SGR 30..37 / 90..97 and 40..47 / 100..107 read back
as); an index `i >= 16` as `Colour("index", i)`; an `(r, g, b)` as
`Colour("rgb", (r, g, b))`. Then the result is
`Style(fg=c(s.fg), bg=c(s.bg), bold=s.bold, dim=s.dim, italic=s.italic,
underline=s.underline, underline_colour=u, strike=s.strike, reverse=s.reverse,
link=s.link)`, where `c(x)` is `None` for a `None` field and the colour of
`shade(x)` otherwise, and `u` is `c(s.underline_colour)` when `D` is 256 or 24 and
`s.underline` is not `None`, else `None` (an underline colour is never sent below
256 colours), except that an underline colour's index is always `Colour("index", i)`,
below 16 too (it is sent as `58;5;i`, which reads back as an index, not a name). When that result `== Style()` the answer is `None` (Vt's plain pen).
So `realized_style(Style(), caps) is None`, a `"default"` colour realizes to no
colour, and two styles that differ only in colour roles realize alike.

`realized(grid, caps) -> Grid`: a NEW grid of `grid`'s size whose cell at every
`(x, y)` is `Cell(g, cell.width, realized_style(cell.style, caps))` for the cell
`cell` of `grid` there, `g` being `cell.glyph`, or `"\\ufffd"` when the cell is not a
tail and its glyph holds a C0 (U+0000..U+001F), DEL (U+007F) or C1 (U+0080..U+009F)
code point or a lone surrogate (U+D800..U+DFFF) ([Display]'s step 3d sends U+FFFD for
such a glyph). `grid` is only read.

## The terminal

`Virtual(caps)`: a fresh virtual terminal for a terminal with the {Caps} `caps` (any
object Buffer's `Display` takes: `depth`, `sync`, `graphemes`). It holds a Buffer
`Display(caps)` (its front buffer, pen and cursor knowledge) and, once a frame has
been shown, a Vt `Screen` of the last frame's size. Read-only attributes: `caps`;
`display` (the `Display`); `screen` (the Vt `Screen`, or `None` before the first
`show`).

- `show(grid, *, cursor=None) -> bytes`: one frame, as the app's loop shows it:
  1. `grid` is checked: a `Grid` with `w >= 1` and `h >= 1` (a terminal has a cell);
  2. `data = show(display, grid, cursor=cursor)` (Buffer's op: the bytes the
     terminal is sent; `b""` for an idle frame);
  3. the screen: before the first frame, `Screen(grid.w, grid.h)`; when the grid's
     size differs from the screen's, `screen.resize(grid.w, grid.h)` (the terminal
     resized; [Display] repaints the whole grid at a new size);
  4. `apply(screen, data)` (Vt's op);
  5. returns `data`.
  On an error in steps 1 or 2 nothing has changed.
- `grid() -> Grid`: what the terminal shows: `screen.grid()` (a new Grid each call).
- `cursor() -> tuple[int, int] | None`: the text cursor the terminal shows: `(c.x,
  c.y)` for `c = screen.cursor()` when `c.visible`, else `None` (hidden).
- `verify(grid, *, cursor=None) -> tuple[Mismatch, ...]`: `show(grid,
  cursor=cursor)`, then every difference between the terminal and the frame: with
  `want = realized(grid, caps)` and `got = self.grid()`, one
  `Mismatch((x, y), want.get(x, y), got.get(x, y))` for every cell where the two
  differ (`!=`), rows top to bottom, cells left to right; then, when `self.cursor()
  != cursor`, `Mismatch("cursor", cursor, self.cursor())`. `()` when the screen
  equals the buffer.
- `assert_shows(grid, *, cursor=None) -> None`: `verify(...)`, raising
  `AssertionError(message)` when it gives any mismatch, `message` being
  `f"the replayed screen differs from the frame in {n} place(s):"` followed by one
  line per mismatch, `"\\n"` before each, the first 20 only (`str(mismatch)`), then,
  when `n > 20`, a line `f"... and {n - 20} more"`.

Data (frozen dataclass, stored as given):
- `Mismatch(at, expected, actual)`: `at` is a cell `(x, y)` (then `expected` is the
  realized frame's {Cell} and `actual` the screen's) or `"cursor"` (then each is the
  cursor, `(x, y)` or `None`). `str(m)`: `f"({x}, {y}): expected {expected!r}, got
  {actual!r}"` for a cell, `f"cursor: expected {expected!r}, got {actual!r}"` for the
  cursor.

Laws (each a property a test can loop over caps, grids and cursors):
- replay (the gate): for every caps and every sequence of grids `g1 .. gn` (each at
  least 1 x 1, sizes free to change between them; cells well formed, as Buffer's
  `check` accepts, with no glyph holding a control code point, and no two
  neighbouring cells whose glyphs Text's `cluster` joins into one cluster when they
  are written one after the other: two lone regional indicators, an emoji then a lone
  skin-tone modifier) and cursors `k1 .. kn` (each `None` or inside its grid), on one
  `Virtual(caps)` `v`: after `v.show(gi, cursor=ki)`, `v.grid() == realized(gi,
  caps)` and `v.cursor() == ki`; so `v.verify(gi, cursor=ki) == ()` for each in turn.
- idle: after `v.show(g, cursor=k)`, `v.show(g2, cursor=k)` with `g2 == g` returns
  `b""` and leaves `v.grid()` unchanged ([Display]'s idle_is_silent, seen from the
  terminal's side).
- contained: after every `show`, `v.screen.take() == ()`: what cure emits for a frame
  asks the terminal nothing and sets no title, clipboard or bell.
- realized: `realized(realized(g, c), c) == realized(g, c)`; `realized(g, c)` has
  `g`'s size; grids that differ only in their colours' roles realize to equal grids;
  at depth 0 no realized cell has a colour.
The neighbouring-cells condition is the terminal's own behaviour (a real terminal
joins them too), so a mismatch there is a true finding about the frame, not about the
emitter.

Inputs: `caps`: a {Caps}; `grid`: a Buffer {Grid}; `cursor`: `None` or `(x, y)`;
  `style`: `None` or a Style {Style}.
Outputs: `show`: {Bytes}, the emitted frame; `grid`, `realized`: a {Grid};
  `cursor`: `(x, y)` or `None`; `verify`: a tuple of `Mismatch`; `realized_style`: a
  {Style} or `None`; `assert_shows`: `None`.
Errors: `Virtual(...)`: as Buffer's `Display(caps)` raises (`AttributeError` for a
  missing attribute, `ValueError` for a depth that is not one, `TypeError` for a
  `sync` / `graphemes` that is not a `bool`). `show`, `verify`, `assert_shows`:
  `TypeError` when `grid` is not a `Grid`; `ValueError` when it has no cell (`w` or
  `h` is 0); and as Buffer's `show` raises (`TypeError` for a bad `cursor` or a cell
  style that is neither `None` nor a `Style`, `ValueError` for a cursor outside the
  grid), with nothing changed. `grid`, `cursor`: `ValueError` before the first
  `show` (there is no screen yet). `realized`: `TypeError` when `grid` is not a
  `Grid`; as `realized_style` raises. `realized_style`: `TypeError` when `style` is
  neither `None` nor a `Style` (a Snapshot `Label` included); `ValueError` from
  `depth_of` when `caps.depth` is not a depth. `assert_shows`: `AssertionError` on a
  mismatch, as above.
Effects: only the stated changes to the `Virtual`'s own `Display` and `Screen`. No I/O.

Usage (`E` is `"\\x1b"`):
    from cure.core import Caps
    from cure.core.buffer import Grid, put, text
    from cure.core.style import Ink, Name, Style, resolve
    from cure.testing.virtual import Virtual, realized, realized_style
    teal = Ink("teal", (42, 161, 152), tty256=37, tty16="cyan")
    s = Style(fg=resolve(Name(teal, "kinds-service")), bold=True)
    g = put(Grid(4, 1), 0, 0, "ok", s)
    v = Virtual(Caps(depth=16))
    v.show(g)                    # b"E[?25lE[1;1HE[0;1;36mokE[0m  "
    v.grid() == realized(g, Caps(depth=16))     # True
    realized_style(s, Caps(depth=16))   # Style(fg=Colour("name", "cyan"), bold=True): no role
    realized_style(s, Caps(depth=256))  # Style(fg=Colour("index", 37), bold=True)
    v.verify(g)                  # (): idle (b"" sent), and the screen still equals
    v.show(g, cursor=(2, 0))     # b"E[1;3HE[?25h"
    v.cursor()                   # (2, 0)
    v.show(put(Grid(5, 2), 0, 1, "中x"))
    # b"E[?25lE[1;1HE[0m     E[2;1H\\xe4\\xb8\\xadx  ": a resize, the cursor hidden
    # while drawing, the whole grid repainted from a reset (the pen unknown)
    text(v.grid()), v.cursor()   # "\\n中x", None
    v.screen.take()              # (): nothing asked of the terminal
    v.assert_shows(put(Grid(5, 2), 0, 1, "中x"))  # None
"""

from dataclasses import dataclass

from cure.core.buffer import Display, Grid, show, write
from cure.core.style import NAMES, Colour, Style, depth_of, realize
from cure.core.text import Cell
from cure.interact.vt import Screen, apply

_SHOWN = 20


@dataclass(frozen=True)
class Mismatch:
    """Where the replayed screen differs from the realized frame: a cell or the cursor (see the module)."""

    at: object
    expected: object
    actual: object

    def __str__(self) -> str:
        """`"(x, y): expected …, got …"` or `"cursor: expected …, got …"` (see the module)."""
        if self.at == "cursor":
            return f"cursor: expected {self.expected!r}, got {self.actual!r}"
        x, y = self.at
        return f"({x}, {y}): expected {self.expected!r}, got {self.actual!r}"


class Virtual:
    """A virtual terminal: a Buffer Display and the Vt Screen its bytes are replayed on (see the module)."""

    def __init__(self, caps: object) -> None:
        """A fresh terminal for `caps`: a new `Display(caps)`, no screen yet."""
        self._caps = caps
        self._display = Display(caps)
        self._screen = None

    @property
    def caps(self) -> object:
        """The {Caps} given."""
        return self._caps

    @property
    def display(self) -> object:
        """The Buffer `Display` the frames are shown through."""
        return self._display

    @property
    def screen(self) -> object:
        """The Vt `Screen` the bytes are replayed on, or `None` before the first `show`."""
        return self._screen

    def _shown(self) -> Screen:
        """The screen, or ValueError before the first `show`."""
        if self._screen is None:
            raise ValueError("no frame has been shown yet: there is no screen")
        return self._screen

    def show(self, grid: Grid, *, cursor: "tuple[int, int] | None" = None) -> bytes:
        """Emit `grid` through Buffer's `show` and replay the bytes on the screen; the bytes."""
        _check_grid(grid)
        data = show(self._display, grid, cursor=cursor)
        if self._screen is None:
            self._screen = Screen(grid.w, grid.h)
        elif self._screen.size != (grid.w, grid.h):
            self._screen.resize(grid.w, grid.h)
        apply(self._screen, data)
        return data

    def grid(self) -> Grid:
        """What the terminal shows: a new Grid of the screen (ValueError before the first `show`)."""
        return self._shown().grid()

    def cursor(self) -> "tuple[int, int] | None":
        """The text cursor the terminal shows, or `None` when hidden (ValueError before the first `show`)."""
        c = self._shown().cursor()
        return (c.x, c.y) if c.visible else None

    def verify(self, grid: Grid, *, cursor: "tuple[int, int] | None" = None) -> "tuple[Mismatch, ...]":
        """Show `grid`, then every cell (and the cursor) where the screen differs from it, realized."""
        self.show(grid, cursor=cursor)
        want, got = realized(grid, self._caps), self.grid()
        out = [Mismatch((x, y), want.get(x, y), got.get(x, y))
               for y in range(grid.h) for x in range(grid.w)
               if want.get(x, y) != got.get(x, y)]
        shown = self.cursor()
        if shown != cursor:
            out.append(Mismatch("cursor", cursor, shown))
        return tuple(out)

    def assert_shows(self, grid: Grid, *, cursor: "tuple[int, int] | None" = None) -> None:
        """`verify(...)`, raising AssertionError listing the mismatches when there are any."""
        found = self.verify(grid, cursor=cursor)
        if found:
            raise AssertionError(_message(
                f"the replayed screen differs from the frame in {len(found)} place(s):", found))


def realized_style(style: object, caps: object) -> object:
    """The style a terminal at `caps.depth` shows for `style`, role-less, as Vt reads it back (see the module)."""
    if style is None:
        style = Style()
    elif not isinstance(style, Style):
        raise TypeError(f"style must be None or a Style, got {type(style).__name__}")
    depth = depth_of(caps)
    s = style

    def c(x: object) -> "Colour | None":
        return None if x is None else _shade(realize(x, caps))

    u = None
    if depth in (256, 24) and s.underline is not None and s.underline_colour is not None:
        u = _shade(realize(s.underline_colour, caps))
        if u is not None and u.form == "name":
            u = Colour("index", NAMES.index(u.value))      # sent as 58;5;i: read back as an index
    r = Style(fg=c(s.fg), bg=c(s.bg), bold=s.bold, dim=s.dim, italic=s.italic,
              underline=s.underline, underline_colour=u, strike=s.strike,
              reverse=s.reverse, link=s.link)
    return None if r == Style() else r


def realized(grid: Grid, caps: object) -> Grid:
    """A new grid: every cell's style realized at `caps.depth`, control and lone-surrogate glyphs as U+FFFD (see the module)."""
    if not isinstance(grid, Grid):
        raise TypeError(f"grid must be a Grid, got {type(grid).__name__}")
    out = Grid(grid.w, grid.h)
    for y in range(grid.h):
        row = []
        for cell in grid.row(y):
            g = cell.glyph
            if cell.width != 0 and any(_control(ch) or 0xD800 <= ord(ch) <= 0xDFFF for ch in g):
                g = "\ufffd"
            row.append(Cell(g, cell.width, realized_style(cell.style, caps)))
        write(out, 0, y, row)
    return out


def _shade(shade: object) -> "Colour | None":
    """A shade (`None`, an index, an `(r, g, b)`) written back as a role-less Colour."""
    if shade is None:
        return None
    if isinstance(shade, int):
        return Colour("name", NAMES[shade]) if shade < 16 else Colour("index", shade)
    return Colour("rgb", tuple(shade))


def _control(ch: str) -> bool:
    """A C0, DEL or C1 code point ([Display] sends U+FFFD for a glyph holding one)."""
    o = ord(ch)
    return o < 0x20 or o == 0x7F or 0x80 <= o <= 0x9F


def _check_grid(grid: object) -> None:
    if not isinstance(grid, Grid):
        raise TypeError(f"grid must be a Grid, got {type(grid).__name__}")
    if grid.w == 0 or grid.h == 0:
        raise ValueError(f"a terminal has a cell: the grid is {grid.w} x {grid.h}")


def _message(title: str, found: tuple) -> str:
    """`title`, then one line per finding (the first 20), then `... and N more`."""
    lines = [title] + [str(f) for f in found[:_SHOWN]]
    if len(found) > _SHOWN:
        lines.append(f"... and {len(found) - _SHOWN} more")
    return "\n".join(lines)
