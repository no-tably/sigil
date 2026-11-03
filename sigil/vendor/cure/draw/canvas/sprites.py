"""[Sprites]: one-frame overlays on a kept canvas.

Kind: service (a data class and two functions that write into a {Canvas}).

What it does: an animation's moving bits (a run's tokens, a cursor, a pulse) are put
on a kept canvas for one frame and taken off before the next, so the drawing under
them is laid out once ([Strokes]' {Kept}, Memo). `overlay` is [Labels]' `label` that
remembers what it covered and returns it as an {Undo} ({Spans} => {Undo}); `undo`
puts it back.

- `overlay(canvas, x, y, spans, style=None, *, tag=None) -> Undo`: exactly
  `label(canvas, x, y, spans, style, tag=tag)`, returning an `Undo` that records,
  for every cell whose text or tag the label changed (the cells written and any
  half pair blanked beside them by no_orphan_half), the text (a Text `Cell`, or
  `None`) and the tag (or `None`) it held before, and the extent before.
- `undo(canvas, *undos) -> None`: puts the recorded texts, tags and extent back,
  the undos applied last first (`undo(c, a, b)` is `undo(c, b)` then `undo(c, a)`),
  so overlays taken off in any one call come off in the reverse of the order they
  went on. Joints are never touched by either (an overlay is text).

Through [Strokes]' public texts writers only (Q9b: never the Canvas's private
`_write`, `_texts`, `_tags`, `_w`, `_h`): `overlay` reads row `y` with `texts(canvas,
y)` before and after its `label`, and records each column whose `(text, tag)`
differs, with the extent read from `canvas.width` and `canvas.height`; `undo` puts
each record back with `restore(canvas, u.cells, u.extent)`, the undos last first.

Invariant: undo_exact — for any canvas `c` and overlays `u1 .. un` made on it in
  that order with no other write between, `undo(c, u1, ..., un)` leaves `c` `==` to
  what it was before `u1` (texts, tags and extent). On a `Kept` canvas whose `rows`
  were drawn before `u1`, the rows the overlays touched are dirty after them and
  clean again after the undo.

Data (frozen dataclass):
- `Undo(cells: tuple[tuple[tuple[int, int], object, object], ...] = (), extent:
  tuple[int, int] = (0, 0))`: `((x, y), text_before, tag_before)` per changed cell,
  sorted by `(y, x)`, each cell once; `extent` the `(width, height)` before. An
  overlay of an empty line has no cells (and its undo changes nothing).

Inputs: `overlay`: as [Labels]' `label`. `undo`: a {Canvas} and `Undo`s.
Outputs: `overlay`: {Undo}. `undo`: `None`.
Errors: `overlay`: as `label`. `undo`: `TypeError` when `canvas` is not a `Canvas` or
  an undo is not an `Undo`. On an error the canvas is unchanged.
Effects: only the stated writes to the canvas argument.

Usage:
    from cure.draw.canvas import Canvas, Path, stroke, keep, overlay, undo
    from cure.draw.theme.charset import Charset
    cs = Charset()
    c = Canvas()
    stroke(c, Path([(0, 0), (4, 0)]))
    k = keep(c)
    k.rows(cs)[0].plain                      # "─────"
    u = overlay(k, 2, 0, "●", "lit")
    k.rows(cs)[0].plain                      # "──●──"
    undo(k, u)
    k.dirty, k.rows(cs)[0].plain             # (frozenset({0}), "─────")
"""

from collections.abc import Hashable, Iterable
from dataclasses import dataclass

from cure.core.text import Line, Span

from .labels import label
from .strokes import Canvas, _check_canvas, restore, texts


@dataclass(frozen=True)
class Undo:
    """{Undo}: what an overlay covered: ((x, y), text before, tag before) per cell, and the extent before."""

    cells: tuple = ()
    extent: tuple = (0, 0)


def overlay(canvas: Canvas, x: int, y: int, spans: "str | Line | Iterable[Span]", style: object = None,
            *, tag: "Hashable | None" = None) -> Undo:
    """`label` for one frame: returns the Undo that takes it off (see the module)."""
    _check_canvas(canvas)
    extent = (canvas.width, canvas.height)
    before = texts(canvas, y)
    label(canvas, x, y, spans, style, tag=tag)
    after = texts(canvas, y)
    cells = tuple(((cx, y), *before.get(cx, (None, None)))
                  for cx in sorted(set(before) | set(after))
                  if before.get(cx) != after.get(cx))
    return Undo(cells, extent)


def undo(canvas: Canvas, *undos: Undo) -> None:
    """Put back what the overlays covered, the last first (see the module)."""
    _check_canvas(canvas)
    for u in undos:
        if not isinstance(u, Undo):
            raise TypeError(f"expected an Undo, got {type(u).__name__}")
    for u in reversed(undos):
        restore(canvas, u.cells, u.extent)

