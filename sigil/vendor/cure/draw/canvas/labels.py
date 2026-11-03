"""[Labels]: text wins over strokes.

Kind: service (a pure-in-arguments function that writes into a {Canvas}).

What it does: puts a line of styled text on a canvas, laid out by Text's `put`
({Spans} => {Cells}): one cell per column, a wide glyph as its head and its tail, a
combining mark riding its base, a control as U+FFFD. The text goes into the canvas's
texts layer, over any strokes ([Strokes]' text_wins: the strokes stay under it).

`label(canvas, x, y, spans, style=None, *, tag=None) -> int`:
- the cells are `cure.core.text.put(line)`, `line` being `Line.of((spans, style))`
  when `spans` is a `str`, else `spans` itself (a {Line}, or an iterable of `Span`);
- cell `i` is written at `(x + i, y)`, replacing the text there (a tail included); a
  wide pair that the written columns cover only in part follows no_orphan_half
  ([Strokes]: its other column becomes `Cell(" ", 1, s)`);
- with `tag` not `None` every written cell's tag becomes `tag`; otherwise tags are
  kept;
- the extent grows to cover the written cells;
- returns `x + len(cells)`, the column after the label (so labels chain).
The cells are written through [Strokes]' public `place(canvas, x, y, cells, tag=tag)`
(Q9b: never the Canvas's private `_place`), which does the writing, the tag, the
extent and the mend; `label` checks its own arguments first, as stated below, and
lays the cells out with Text's `put`.
A label is never wrapped, cut or split: the canvas has no right edge, and a glyph is
never split (fitting text to room is the caller's, with Text's [Cut] and [Wrap]). A
space is a text like any other and covers a stroke under it. An empty line writes
nothing and returns `x`.

Inputs: a {Canvas}; `x`, `y`: ints >= 0; `spans`: a `str`, a {Line} or an iterable
  of `Span`; `style`: any style, only with a `str`; `tag`: hashable or `None`.
Outputs: an `int`, the column after the label.
Errors: `TypeError` when `canvas` is not a `Canvas`, a coordinate is not an `int` (a
  `bool` included), or `spans` is none of the accepted types (as Text's `put`);
  `ValueError` for a negative coordinate, or a `style` other than `None` given with a
  {Line} or spans. On an error the canvas is unchanged.
Effects: only the stated writes to the canvas argument.

Usage:
    from cure.draw.canvas import Canvas, Path, stroke, label
    from cure.draw.theme.charset import Charset
    cs = Charset()
    c = Canvas()
    stroke(c, Path([(0, 0), (5, 0)]))
    label(c, 1, 0, "中文")                   # 5
    c.rows(cs)[0].plain                      # "─中文─"
    label(c, 2, 0, "x")                      # 3: over 中's tail, so its head is blanked
    c.rows(cs)[0].plain                      # "─ x文─"
"""

from collections.abc import Hashable, Iterable

from cure.core.text import Line, Span, put

from .junctions import _check_int
from .strokes import Canvas, _check_canvas, place


def label(canvas: Canvas, x: int, y: int, spans: "str | Line | Iterable[Span]", style: object = None,
          *, tag: "Hashable | None" = None) -> int:
    """Put a line of text at (x, y) over any strokes; returns the column after it."""
    _check_canvas(canvas)
    _check_int(x)
    _check_int(y)
    if x < 0 or y < 0:
        raise ValueError(f"coordinates must be >= 0, got {(x, y)}")
    if isinstance(spans, str):
        cells = put(Line.of((spans, style)))
    else:
        cells = put(spans)
        if style is not None:
            raise ValueError("a style is given only with a str; spans carry their own")
    place(canvas, x, y, cells, tag=tag)
    return x + len(cells)
