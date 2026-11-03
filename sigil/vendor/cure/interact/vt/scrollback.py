"""[Scrollback]: logical lines in a ring: reflow on resize.

Kind: service (a mutable ring of {Line}s and the functions that keep and read it).

What it does: keeps the history of a pane, the rows its primary screen scrolled off the
top, as LOGICAL lines (a soft-wrapped run of rows is one line), so reading it back at
any width is a reflow and a resize costs nothing here. It builds on [Screen]
(`[Scrollback] -> [Screen] : keep({Lines}) => {Ring}`): it takes the {Line}s that
`Screen.scrolled()` gives out and reuses [Screen]'s {Line} and `reflow`; [Screen] never
imports it. The app (Embed, a Pane widget) wires them:
`keep(ring, screen.scrolled())` after each `apply`.

## The ring

`Ring(capacity=CAPACITY)`: an empty ring holding at most `capacity` (an int >= 0;
`CAPACITY` is 10000) logical lines. Mutable, unhashable; written only by `keep`.

- `capacity` (read-only int); `len(ring)`: the logical lines held.
- `lines() -> tuple[Line, ...]`: the logical lines, oldest first. Each is a {Line}
  whose `cells` are the whole logical line and whose `wrapped` is True only when the
  line is still open: the rows scrolled so far end on a wrapped row, so its rest is
  still on the screen and the next row kept continues it (or when `MAX_LINE` split it,
  below).
- `==`: same capacity and equal `lines()`.

`keep(ring, lines) -> Ring` (the flow's op): adds the {Line}s (physical rows, oldest
first, as `scrolled()` gives them) in order, in place, and returns the same ring
(`is`). For each line: when the ring's newest line is open (`wrapped`), the line's
cells are appended to it and it takes the line's `wrapped`; otherwise the line is
added as a new logical line. A join that would make a logical line longer than
`MAX_LINE` (65536) cells adds the line as a new logical line instead (the old one
stays `wrapped`, so a reader still sees them as one run). Past `capacity`, the oldest
logical lines are evicted, one by one, so `len(ring) <= capacity` always; with
capacity 0 nothing is kept. `keep(ring, ())` changes nothing.

So, for any rows `r1 .. rn`, `keep` in any number of calls gives the same ring as one
call with all of them, and `reflow(ring.lines(), w)` equals `reflow((r1, .., rn), w)`
whenever nothing was evicted or split.

## Reading it back for a viewport

- `height(ring, w) -> int`: the rows the ring takes at width `w`:
  `len(reflow(ring.lines(), w))` (each logical line wrapped by [Screen]'s `reflow`).
- `view(ring, w, top, h) -> tuple[Line, ...]`: rows `top .. top + h - 1` of
  `reflow(ring.lines(), w)`, row 0 the oldest; fewer (or none) when they run past the
  end. A viewport scrolled `k` rows up from the live screen of height `sh` shows
  `view(ring, w, height(ring, w) - k, min(k, sh))` above the screen's top
  `sh - min(k, sh)` rows. Each row is a {Line} of at most `w` cells; a renderer pads it
  with `BLANK` to the pane's width.

Inputs: `Ring`: `capacity` an int. `keep`: a `Ring` and an iterable of {Line}.
  `height` / `view`: a `Ring`, `w` an int >= 1, `top` an int >= 0, `h` an int >= 0.
Outputs: `keep`: {Ring} (the same object). `height`: an int. `view`: a tuple of {Line}.
Errors: `Ring(...)`: `TypeError` when `capacity` is not an `int` (a `bool` included),
  `ValueError` when it is < 0. `keep`: `TypeError` when `ring` is not a `Ring` or an
  item is not a `Line` (checked before anything is kept: on an error the ring is
  unchanged). `height` / `view`: `TypeError` when `ring` is not a `Ring` or a number is
  not an `int` (a `bool` included); `ValueError` when `w < 1`, `top < 0` or `h < 0`.
Effects: only the stated in-place writes to the `ring` argument. No I/O.

Usage:
    from cure.core.buffer.cells import line
    from cure.interact.vt.screen import Line
    from cure.interact.vt.scrollback import Ring, keep, height, view
    r = keep(Ring(capacity=2), [Line(line("abcd"), True), Line(line("ef"))])
    r.lines()                 # (Line(<"abcdef">, False),)
    height(r, 4), height(r, 2)    # 2, 3
    view(r, 3, 1, 5)          # (Line(<"def">, False),)
    keep(r, [Line(line("g")), Line(line("h"))])
    len(r)                    # 2: "abcdef" evicted; ("g", "h") remain
"""

from collections import deque
from collections.abc import Iterable

from .screen import Line, reflow

CAPACITY = 10_000
"""The logical lines a `Ring()` holds by default."""

MAX_LINE = 65536
"""The longest logical line a ring joins, in cells; a longer run is split (see `keep`)."""


class Ring:
    """{Ring}: at most `capacity` logical lines, oldest first; written only by `keep`."""

    __hash__ = None  # mutable: unhashable

    def __init__(self, capacity: int = CAPACITY) -> None:
        _int(capacity, "capacity")
        if capacity < 0:
            raise ValueError(f"capacity must be >= 0, got {capacity}")
        self._capacity = capacity
        self._lines: deque = deque()  # [cells (a list), wrapped] per logical line

    @property
    def capacity(self) -> int:
        """The most logical lines it holds."""
        return self._capacity

    def __len__(self) -> int:
        return len(self._lines)

    def lines(self) -> "tuple[Line, ...]":
        """The logical lines, oldest first."""
        return tuple(Line(cells, wrapped) for cells, wrapped in self._lines)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Ring):
            return NotImplemented
        return self._capacity == other._capacity and self._lines == other._lines


def keep(ring: Ring, lines: "Iterable[Line]") -> Ring:
    """Add scrolled rows to the ring in place, joining wrapped runs; evict past capacity."""
    if not isinstance(ring, Ring):
        raise TypeError(f"ring must be a Ring, got {type(ring).__name__}")
    items = list(lines)
    for item in items:
        if not isinstance(item, Line):
            raise TypeError(f"expected a Line, got {type(item).__name__}")
    if ring._capacity == 0:
        return ring
    held = ring._lines
    for item in items:
        newest = held[-1] if held else None
        if newest is not None and newest[1] and len(newest[0]) + len(item.cells) <= MAX_LINE:
            newest[0].extend(item.cells)
            newest[1] = item.wrapped
        else:
            held.append([list(item.cells), item.wrapped])
            if len(held) > ring._capacity:
                held.popleft()
    return ring


def height(ring: Ring, w: int) -> int:
    """The rows the ring takes at width `w`."""
    _ring(ring)
    _int(w, "w")
    if w < 1:
        raise ValueError(f"w must be >= 1, got {w}")
    return len(reflow(ring.lines(), w))


def view(ring: Ring, w: int, top: int, h: int) -> "tuple[Line, ...]":
    """Rows `top .. top + h - 1` of the ring reflowed at width `w`."""
    _ring(ring)
    for name, value in (("w", w), ("top", top), ("h", h)):
        _int(value, name)
    if w < 1 or top < 0 or h < 0:
        raise ValueError(f"need w >= 1, top >= 0 and h >= 0, got {w}, {top}, {h}")
    if h == 0:
        return ()
    return reflow(ring.lines(), w)[top:top + h]


def _ring(value: object) -> None:
    if not isinstance(value, Ring):
        raise TypeError(f"ring must be a Ring, got {type(value).__name__}")


def _int(value: object, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
