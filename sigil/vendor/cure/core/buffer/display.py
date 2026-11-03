"""[Display]: holds one front buffer: cursor moves, SGR changes, glyphs, synchronized
output, the text cursor last; one per terminal or client.

Kind: service (a class with explicit state, and the function that drives it). Pure in
the sense that matters: no I/O and no process-wide state. `show` RETURNS the bytes
for a frame; the caller (Edge's one Writer, a Remote client's connection) writes
them. Each terminal or client has its own `Display`, at its own size and {Caps};
two Displays never share anything.

State (all of it; held by each `Display`, changed only by `show` and `invalidate`):
- `front`: the last grid shown (a copy taken by `show`), or `None` before the first
  frame and after `invalidate()`;
- the pen: the style the terminal's SGR state is known to hold (a Style {Style} or
  `None`), or unknown;
- the terminal cursor's position `(x, y)`, or unknown;
- whether the text cursor is shown: `True`, `False`, or unknown;
- the text cursor last asked for (`cursor`), `None` for hidden.
A new `Display`, and one after `invalidate()`, knows nothing: no front, pen,
position or cursor visibility.

Data:
- `Display(caps)`: `caps` a {Caps}, any object with `depth` (checked with Style's
  `depth_of`), `sync` (`bool`) and `graphemes` (`bool`) attributes; Buffer does not
  import Core's `Caps`. Read-only attributes: `caps`; `front` (a copy of the front
  buffer, or `None`); `cursor` (the text cursor of the last frame shown).
  `Display.show(grid, *, cursor=None)` is `show(self, grid, cursor=cursor)`.
  `invalidate()` forgets everything (the state above returns to unknown), so the
  next frame is a full repaint: call it when emitted bytes may not have reached the
  terminal (a failed write) or after anything else wrote to it.

The escapes (1-based rows and columns, decimal, no padding):
- cursor move (CUP): `ESC [ {y + 1} ; {x + 1} H`, both numbers always written;
- hide / show the text cursor: `ESC [ ? 25 l` / `ESC [ ? 25 h`;
- synchronized output begin / end: `ESC [ ? 2026 h` / `ESC [ ? 2026 l`;
- SGR: only through Style ([Sgr], the one seam): `sgr(style, caps).escape` when the
  pen is unknown (a full set led by the reset `0`), else
  `codes(style, caps, pen).escape` (only the change; `""` when nothing realized
  changes);
- hyperlinks: Style's `hyperlink(uri)` (OSC 8) to open, `hyperlink(None)` to close.

`show(display, grid, *, cursor=None) -> bytes`. `cursor` is `None` (hide the text
cursor) or `(x, y)` inside the grid. The bytes are built in this order:

1. Changes: `diff(front, grid)` ([Diff], default `GAP`). When it is full (the first
   frame, after `invalidate()`, or a size change: a resize is a full repaint at the
   new size), the pen and the cursor position become unknown first.
2. Hide while drawing: when there are changes and the text cursor is not known to be
   hidden, `ESC[?25l`; it is now hidden.
3. The cells, change by change, cell by cell, left to right. A tail emits nothing
   (its head's glyph covered both columns). Every other cell at column `c`, row `y`:
   a. the move: a CUP to (c, y), unless the cursor is known to be there;
   b. the link: `want` is the cell's `style.link` (for a `Style`; `None` for a `None`
      style); when it differs from the open link, `hyperlink(want)` is emitted and
      becomes the open link (`hyperlink(None)` closes one);
   c. the SGR, as above, then the pen is the cell's style;
   d. the glyph, as UTF-8; a glyph holding any control code point (C0
      U+0000..U+001F, DEL U+007F, C1 U+0080..U+009F), any lone surrogate
      (U+D800..U+DFFF), any bidi formatting character (Text's `BIDI`: U+061C, U+200E,
      U+200F, U+202A..U+202E, U+2066..U+2069), U+2028 or U+2029 (Text's
      `SEPARATORS`), or more than `MAX_CLUSTER` (32) code points, is sent as U+FFFD
      instead (one code point, so step e treats it as any one-code-point glyph), so
      no raw control, bidi override or line break ever reaches a terminal, no cell
      costs more than 32 code points a repaint, and every glyph sent encodes as strict
      UTF-8. Such a glyph is one Buffer's `check` accepts from a cell built by hand
      (`Cell("\\x01", 1, None)`, `Cell("\\ud800", 1, None)`: Text's `width` gives
      each 1, and Text's `cell` / `put` never make one, turning both into U+FFFD), and
      Text's `cell` / `put` make the others (Graphemes keeps a bidi character as an
      extender: `"a\\u202e"` is one cluster); Display, not `check` or Text, is where
      it is made safe. The three constants live in `cure.core.text.width`;
   e. the position is then known as (c + width, y), except: unknown when
      `c + width >= grid.w` (the terminal's pending wrap at the last column), and
      unknown when the glyph sent has more than one code point and
      `caps.graphemes` is false (the terminal may draw it at another width).
4. An open link is closed (`hyperlink(None)`): no link outlives a frame.
5. The text cursor, last: for `cursor=None`, `ESC[?25l` unless it is known hidden; for
   `(x, y)`, a CUP there unless the cursor is known to be there, then `ESC[?25h`
   unless it is known shown.
6. When anything was emitted and `caps.sync` is true, the whole is wrapped in
   `ESC[?2026h` ... `ESC[?2026l`. When nothing was emitted the result is `b""`.

Then `front` is a copy of `grid` (later writes into `grid` do not touch it) and the
other state is as left by the steps. The pen persists from frame to frame. The
state changes only when `show` returns: on an error nothing has changed.

Invariant: idle_is_silent — an unchanged repaint emits zero bytes, and the gate is the
  emitted frame: after `b = show(d, g, cursor=k)`, `show(d, g2, cursor=k)` with
  `g2 == g` returns `b""` (whatever `g2`'s identity, and however its cells were
  written), and so does every repeat. Any frame that differs in a cell or in the
  text cursor emits something.

Invariant: utf8_out — `show` never raises `UnicodeEncodeError`: for every `Display`
  (any {Caps} it takes, any state) and every {Grid} (every row of which Buffer's
  `check` accepts) whose cells' styles are each `None` or a `Style`, and every
  valid `cursor`, `show(d, grid, cursor=cursor).decode("utf-8")` (strict) succeeds.
  The glyphs are made safe by step 3d; a link is safe because Style refuses one
  holding a control or a lone surrogate ([Attrs]), so `hyperlink` never raises for
  it; every escape is ASCII.

Inputs: `display` a `Display`; `grid` a {Grid}; `cursor` `None` or a 2-tuple of ints.
Outputs: {Bytes}: `bytes` (UTF-8 text and escapes), `b""` for an idle frame.
Errors: `Display(...)`: `AttributeError` when `caps` lacks `depth`, `sync` or
  `graphemes`; `ValueError` from `depth_of` when `caps.depth` is not a depth;
  `TypeError` when `sync` or `graphemes` is not a `bool`. `show`: `TypeError` when
  `display` is not a `Display`, `grid` is not a `Grid`, `cursor` is neither `None`
  nor a 2-tuple of ints, or a cell's style is neither `None` nor a `Style` (from
  Style's `codes` / `sgr`); `ValueError` when `cursor` lies outside the grid (a grid
  with no cells has no place for one). Never `UnicodeEncodeError` (utf8_out). On an
  error the state is unchanged.
Effects: only the stated changes to `display`'s own state. No I/O.

Usage (`Caps` is Core's {Caps}; `E` is `"\\x1b"`):
    from cure.core.caps import Caps
    from cure.core.buffer.grid import Grid, put
    from cure.core.buffer.display import Display, show
    d = Display(Caps(depth=16))
    g = put(Grid(3, 1), 0, 0, "ab")
    show(d, g)                    # b"E[?25lE[1;1HE[0mab ": hide, move, full SGR, cells
    show(d, g)                    # b"": idle
    put(g, 1, 0, "x")
    show(d, g)                    # b"E[1;2Hx": the pen is known plain, no SGR
    show(d, g, cursor=(0, 0))     # b"E[1;1HE[?25h": the text cursor, last
    s = Display(Caps(depth=0, sync=True))
    show(s, put(Grid(2, 1), 0, 0, "中"))
    # b"E[?2026hE[?25lE[1;1HE[0m\\xe4\\xb8\\xadE[?2026l": the tail sends nothing
"""

from cure.core.style import Style, codes, depth_of, hyperlink, sgr
from cure.core.text import Cell
from cure.core.text.width import BIDI, MAX_CLUSTER, SEPARATORS

from .diff import GAP, diff
from .grid import Grid

_UNKNOWN = object()
_HIDE = "\x1b[?25l"
_SHOW = "\x1b[?25h"
_SYNC_ON = "\x1b[?2026h"
_SYNC_OFF = "\x1b[?2026l"
_REPLACEMENT = "\ufffd"


class Display:
    """{Display}: one terminal's or client's front buffer and known terminal state."""

    def __init__(self, caps: object) -> None:
        depth_of(caps)
        sync, graphemes = caps.sync, caps.graphemes
        for name, value in (("sync", sync), ("graphemes", graphemes)):
            if not isinstance(value, bool):
                raise TypeError(f"caps.{name} must be a bool, got {type(value).__name__}")
        self._caps = caps
        self._sync = sync
        self._graphemes = graphemes
        self.invalidate()

    @property
    def caps(self) -> object:
        """The {Caps} this display emits for."""
        return self._caps

    @property
    def front(self) -> "Grid | None":
        """A copy of the last grid shown, or None."""
        return self._front

    @property
    def cursor(self) -> "tuple[int, int] | None":
        """The text cursor of the last frame shown (None: hidden, or nothing shown yet)."""
        return self._cursor

    def show(self, grid: Grid, *, cursor: "tuple[int, int] | None" = None) -> bytes:
        """`show(self, grid, cursor=cursor)`."""
        return show(self, grid, cursor=cursor)

    def invalidate(self) -> None:
        """Forget the front buffer, pen, position and cursor visibility: the next frame is full."""
        self._front = None
        self._pen = _UNKNOWN
        self._pos = None
        self._shown = None
        self._cursor = None


def show(display: Display, grid: Grid, *, cursor: "tuple[int, int] | None" = None) -> bytes:
    """The bytes that bring `display`'s terminal from its front buffer to `grid` (see the module)."""
    if not isinstance(display, Display):
        raise TypeError(f"expected a Display, got {type(display).__name__}")
    if not isinstance(grid, Grid):
        raise TypeError(f"expected a Grid, got {type(grid).__name__}")
    _check_cursor(cursor, grid)
    changes = diff(display._front, grid, gap=GAP)
    pen, pos, shown = display._pen, display._pos, display._shown
    if changes.full:
        pen, pos = _UNKNOWN, None
    out: list[str] = []
    if changes and shown is not False:
        out.append(_HIDE)
        shown = False
    link = None
    caps, graphemes, w = display._caps, display._graphemes, grid.w
    # Speed: one escape per distinct (pen, style) pair met in this call; dropped at return.
    escapes: dict = {}
    for change in changes:
        y = change.y
        for c, cell in enumerate(change.cells, change.x):
            width = cell.width
            if width == 0:
                continue
            if pos != (c, y):
                out.append(_cup(c, y))
            style = cell.style
            is_style = isinstance(style, Style)
            want = style.link if is_style else None
            if want != link:
                out.append(hyperlink(want))
                link = want
            if not is_style and style is not None:
                out.append(_sgr(style, caps, pen))    # Style's TypeError, as ever
            # Speed: a style equal to (or the very object of) the known pen changes nothing
            # (`codes` gives no codes).
            elif pen is not style and (pen is _UNKNOWN or not style == pen):
                try:
                    escape = escapes.get((pen, style))
                except TypeError:     # an unhashable style: asked directly
                    escape = _sgr(style, caps, pen)
                if escape is None:
                    escape = escapes[(pen, style)] = _sgr(style, caps, pen)
                out.append(escape)
            pen = style
            glyph = cell.glyph
            if not (glyph.isascii() and glyph.isprintable()):
                glyph = _safe(glyph)  # Speed: printable ASCII is sent as it is
            out.append(glyph)
            # Where the cursor is known to be now (step e), or None. Speed: inline.
            pos = None if c + width >= w or (len(glyph) > 1 and not graphemes) else (c + width, y)
    if link is not None:
        out.append(hyperlink(None))
    if cursor is None:
        if shown is not False:
            out.append(_HIDE)
            shown = False
    else:
        if pos != cursor:
            out.append(_cup(*cursor))
            pos = cursor
        if shown is not True:
            out.append(_SHOW)
            shown = True
    data = "".join(out)
    if data and display._sync:
        data = _SYNC_ON + data + _SYNC_OFF
    display._front = grid.copy()
    display._pen, display._pos, display._shown = pen, pos, shown
    display._cursor = cursor
    return data.encode("utf-8")


def _check_cursor(cursor: object, grid: Grid) -> None:
    if cursor is None:
        return
    if not (isinstance(cursor, tuple) and len(cursor) == 2
            and all(isinstance(v, int) and not isinstance(v, bool) for v in cursor)):
        raise TypeError(f"cursor must be None or a 2-tuple of ints, got {cursor!r}")
    x, y = cursor
    if not (0 <= x < grid.w and 0 <= y < grid.h):
        raise ValueError(f"cursor {cursor} is outside a {grid.w} x {grid.h} grid")


def _cup(x: int, y: int) -> str:
    return f"\x1b[{y + 1};{x + 1}H"


def _sgr(style: object, caps: object, pen: object) -> str:
    if pen is _UNKNOWN:
        return sgr(style, caps).escape
    return codes(style, caps, pen).escape


_REFUSED = BIDI | SEPARATORS


def _safe(glyph: str) -> str:
    """The glyph as sent (step 3d): U+FFFD when it holds any C0, DEL or C1 control, a lone
    surrogate, a bidi formatting character, U+2028 or U+2029, or more than MAX_CLUSTER
    code points."""
    if len(glyph) > MAX_CLUSTER:
        return _REPLACEMENT
    if any(ord(ch) < 0x20 or 0x7F <= ord(ch) <= 0x9F or 0xD800 <= ord(ch) <= 0xDFFF
           or ch in _REFUSED for ch in glyph):
        return _REPLACEMENT
    return glyph

