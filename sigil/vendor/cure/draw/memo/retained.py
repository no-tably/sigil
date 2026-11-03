"""[Retained]: dirty rows = elements whose look changed.

Kind: service (a data class, a mutable class and pure-in-arguments functions).

What it does: a drawing kept from frame to frame of an animation. Its frames differ
only in how things LOOK (a wire lit or muted, a label's status, a badge); the layout
holds still (the pattern: reserve widths over the whole animation, every badge
padded to its widest, so nothing moves). So the drawing is laid out once, kept
([Canvas]' {Kept}), and each frame repaints only the rows of the elements whose look
or rows changed ({Looks} => {Rows}).

Data (frozen dataclass; its mapping is not to be mutated):
- `Looks(elements: Mapping[Hashable, tuple[frozenset[int], object]])`: for each
  element drawn (a box, a wire, the tokens …, keyed by any hashable the caller
  names) the rows it takes and the look it is drawn with (any value compared with
  `==`; Style's Colours compare with their roles, so a colour of another role
  repaints though its value is the same, and the drawing keeps every colour's role).
  `Looks.of(mapping)` converts: each value a pair `(rows, look)`, `rows` any iterable
  of ints, stored as a `frozenset`; the result's `elements` is a new `dict`.

Operations:
- `moved(old, new) -> frozenset[int]`: the dirty rows from one frame's looks to the
  next: for each element of `new` not in `old`, its rows; of both, with other rows,
  its old rows and its new; of both, with the same rows and a look not `==`, its
  rows; for each element of `old` not in `new`, its old rows. Nothing else.
- `Retained(canvas, looks)` (mutable): `kept`, the drawing (`canvas` itself when it
  is a `Kept`, else Canvas's `keep(canvas)`), and `looks`, the {Looks} it was drawn
  with (both read-only properties; only `repaint` changes them). A `Line` below is
  Text's {Line}, as Canvas's `rows` gives it (Memo does not import Text).
- `repaint(retained, looks, paint, charset, *, rounded=False) -> tuple[Line, ...]`
  ({Looks} => {Rows}): with `dirty = {y in moved(retained.looks, looks) : 0 <= y <
  retained.kept.height}`: when `dirty` is not empty, `other = paint(dirty)` (called
  once, with that `frozenset`; it returns a {Canvas} whose rows `dirty` are right,
  every element taking any of them drawn; the rest may be left out), then
  `retained.kept.splice(other, dirty)`. When `dirty` is empty, `paint` is not called.
  Then `retained.looks = looks`, and the result is
  `retained.kept.rows(charset, rounded=rounded)` ({Rows}).

Invariant: only_what_moved — `repaint` calls `paint` at most once, with exactly the
  dirty rows (`moved`, clipped to the kept height), never when there are none, and
  leaves every other row of the kept canvas as it was. So when `paint(rows)` draws
  those rows as a whole repaint would, `repaint` returns the rows a whole repaint
  returns (with [Strokes]' kept_same), and an unchanged frame repaints nothing.

Inputs: `Looks.of`: a mapping of hashables to `(rows, look)` pairs. `moved`: two
  `Looks`. `Retained`: a {Canvas} and a `Looks`. `repaint`: a `Retained`, a `Looks`,
  a callable `frozenset[int] -> Canvas`, a charset (as [Canvas]' `rows`), a bool.
Outputs: `moved`: `frozenset[int]`. `repaint`: `tuple[Line, ...]` ({Rows}).
Errors: `TypeError` when `canvas` is not a `Canvas`, a looks is not a `Looks`, a
  value given to `Looks.of` is not a pair or its rows are not ints, `paint` is not
  callable or returns something that is not a `Canvas`; what `paint` raises
  propagates. On an error the retained drawing is unchanged.
Effects: `repaint` changes `retained` (its kept canvas and looks) as stated.

Usage:
    from cure.draw.canvas import Canvas, label
    from cure.draw.memo.retained import Looks, Retained, moved, repaint
    from cure.draw.theme.charset import Charset
    cs = Charset()

    def paint(rows, status="idle"):
        c = Canvas()
        label(c, 0, 0, "title")
        label(c, 0, 1, status)
        return c

    r = Retained(paint(None), Looks.of({"title": ({0}, "plain"), "status": ({1}, "idle")}))
    now = Looks.of({"title": ({0}, "plain"), "status": ({1}, "busy")})
    moved(r.looks, now)                                       # frozenset({1})
    [l.plain for l in repaint(r, now, lambda rows: paint(rows, "busy"), cs)]   # ["title", "busy"]
"""

from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass

from cure.draw.canvas import Canvas, Kept
from cure.draw.canvas import keep as _keep_canvas


@dataclass(frozen=True)
class Looks:
    """{Looks}: element -> (the rows it takes, the look it is drawn with)."""

    elements: Mapping = None

    @classmethod
    def of(cls, mapping: "Mapping[Hashable, tuple[object, object]]") -> "Looks":
        """Looks from a mapping of (rows, look) pairs, rows stored as frozensets."""
        return cls({name: _element(value) for name, value in mapping.items()})


def moved(old: Looks, new: Looks) -> "frozenset[int]":
    """The rows of every element whose look or rows changed, or that came or went."""
    _check_looks(old)
    _check_looks(new)
    out: set = set()
    for name, (rows, look) in new.elements.items():
        if name not in old.elements:
            out |= rows
            continue
        old_rows, old_look = old.elements[name]
        if old_rows != rows:
            out |= old_rows | rows
        elif old_look != look:
            out |= rows
    for name, (rows, _) in old.elements.items():
        if name not in new.elements:
            out |= rows
    return frozenset(out)


class Retained:
    """A drawing kept from frame to frame: its kept canvas and the looks it was drawn with (mutable)."""

    def __init__(self, canvas: Canvas, looks: Looks) -> None:
        if not isinstance(canvas, Canvas):
            raise TypeError(f"expected a Canvas, got {type(canvas).__name__}")
        _check_looks(looks)
        self._kept = canvas if isinstance(canvas, Kept) else _keep_canvas(canvas)
        self._looks = looks

    @property
    def kept(self) -> Kept:
        return self._kept

    @property
    def looks(self) -> Looks:
        return self._looks


def repaint(retained: Retained, looks: Looks, paint: "Callable[[frozenset[int]], Canvas]",
            charset: object, *, rounded: bool = False) -> "tuple[Line, ...]":
    """Splice in only the rows that moved, then the kept canvas's rows (see the module)."""
    if not isinstance(retained, Retained):
        raise TypeError(f"expected a Retained, got {type(retained).__name__}")
    _check_looks(looks)
    if not callable(paint):
        raise TypeError(f"paint must be callable, got {type(paint).__name__}")
    kept = retained.kept
    dirty = frozenset(y for y in moved(retained.looks, looks) if 0 <= y < kept.height)
    if dirty:
        other = paint(dirty)
        if not isinstance(other, Canvas):
            raise TypeError(f"paint must return a Canvas, got {type(other).__name__}")
        kept.splice(other, dirty)
    retained._looks = looks
    return kept.rows(charset, rounded=rounded)


def _element(value: object) -> "tuple[frozenset[int], object]":
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise TypeError(f"each element is a (rows, look) pair, got {value!r}")
    rows, look = value
    rows = frozenset(rows)
    for y in rows:
        if isinstance(y, bool) or not isinstance(y, int):
            raise TypeError(f"rows must be ints, got {y!r}")
    return rows, look


def _check_looks(looks: object) -> None:
    if not isinstance(looks, Looks):
        raise TypeError(f"expected a Looks, got {type(looks).__name__}")
