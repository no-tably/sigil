"""[Query]: occupied, mask, tag, restyle: probe where the action is; views stop poking
private dicts.

Kind: service (a data class and functions over a {Canvas}).

What it does: the one public way to read a drawing back and to recolour it in place.
A view asks what a cell holds (`at`, {Cell} => {Occupied}), whether it is free
(`occupied`), which arms a stroke has there (`mask`), what tag it carries (`tag`),
where everything of a tag lies (`box`, which replaces sigil's Probe styles: the
cells a frame's action was drawn in are found by tag, not by a style that compares
unequal), and recolours a cell without redrawing it (`restyle`).

Reading accepts any int coordinates: a cell outside the canvas (negative, or past its
extent) holds nothing.

Through [Strokes]' public readers and writer only (Q11: never the Canvas's private
`_read`, `_write`, `_texts`, `_joints`, `_tags`; see Strokes' "The query readers and
writer"): `at` takes the cell's text and tag from `texts(canvas, y)` and its joint
from `joints(canvas, y)`; `drawn` and `box` read `texts` (and, for `drawn`, `joints`)
for each row `0 .. canvas.height - 1`; `restyle` writes a joint's style with
`repaint(canvas, x, y, style)` and a text's with `place(canvas, h, y, cells)` (each
column of the text re-made in `style`, `tag` left `None` so the tags are kept). Its
own checks (`canvas`, the cell, `layer`) come first, so on an error nothing is
written. It still uses Strokes' check toolkit (`_check_canvas`, `_pair`), which
reads no canvas state.

Data (frozen dataclass):
- `Occupied(cell: tuple[int, int], text: Cell | None, joint: Joint | None, tag:
  object = None)`: what `cell` holds: its text (a Text `Cell`: a head, a tail or a
  narrow glyph), its stroke ([Junctions]' `Joint`) and its tag, each `None` when
  absent.
  - `empty -> bool`: `text is None and joint is None` (a tag alone is not drawn).
  - `mask -> int`: `joint.mask`, `0` without a joint.

Operations:
- `at(canvas, cell) -> Occupied`: `Occupied(cell, text, joint, tag)` at `cell`.
- `occupied(canvas, cell) -> bool`: `not at(canvas, cell).empty` (a tail is
  occupied: a wide glyph takes both its columns).
- `mask(canvas, cell) -> int`: `at(canvas, cell).mask`.
- `tag(canvas, cell) -> object`: `at(canvas, cell).tag`.
- `drawn(canvas) -> frozenset[tuple[int, int]]`: every cell holding a text or a joint.
- `box(canvas, tag) -> tuple[int, int, int, int] | None`: `(x, y, w, h)`, the smallest
  rectangle around every cell whose tag `==` `tag`; `None` when no cell has it.
- `restyle(canvas, cell, style, *, layer="joint") -> bool`: the style of what `cell`
  holds becomes `style`, its glyph, arms and weight unchanged. `layer` `"joint"`:
  the joint's; `"text"`: the text's (both columns of a wide pair, so the pair keeps
  one style); `"both"`: each of them. Returns `True` when something was restyled,
  `False` (nothing changed) when the cell has no such layer. The extent and tags are
  unchanged. On a `Kept` canvas the cell's row is dirty when its drawn style changed.

Inputs: a {Canvas}; a cell, an `(x, y)` pair of ints; `tag`: any value; `style`: any
  style; `layer`: `"joint"`, `"text"` or `"both"`.
Outputs: as stated.
Errors: `TypeError` when `canvas` is not a `Canvas` or a cell is not a pair of `int`s
  (a `bool` included); `ValueError` for a `layer` not listed.
Effects: `restyle` writes into the canvas argument as stated; the rest none.

Usage:
    from cure.draw.canvas import Canvas, Path, stroke, label, at, occupied, mask, box, restyle, N, S
    c = Canvas()
    stroke(c, Path([(1, 0), (1, 2)]), tag="wire")
    label(c, 3, 1, "ok", tag="note")
    mask(c, (1, 1)) == N | S, occupied(c, (0, 1)), occupied(c, (4, 1))   # (True, False, True)
    box(c, "wire"), box(c, "none")           # ((1, 0, 1, 3), None)
    restyle(c, (1, 1), "lit"), at(c, (1, 1)).joint.style                 # (True, "lit")
"""

from collections.abc import Hashable
from dataclasses import dataclass

from cure.core.text import Cell

from .junctions import Joint
from .strokes import Canvas, _check_canvas, _pair, joints, place, repaint, texts

_LAYERS = ("joint", "text", "both")


@dataclass(frozen=True)
class Occupied:
    """{Occupied}: what one cell holds: its text, its joint and its tag."""

    cell: tuple
    text: "Cell | None" = None
    joint: "Joint | None" = None
    tag: object = None

    @property
    def empty(self) -> bool:
        """No text and no joint."""
        return self.text is None and self.joint is None

    @property
    def mask(self) -> int:
        """The joint's mask, 0 without one."""
        return 0 if self.joint is None else self.joint.mask


def at(canvas: Canvas, cell: "tuple[int, int]") -> Occupied:
    """What `cell` holds (empty outside the canvas)."""
    _check_canvas(canvas)
    x, y = _pair(cell)
    text, tag = texts(canvas, y).get(x, (None, None))
    return Occupied((x, y), text, joints(canvas, y).get(x), tag)


def occupied(canvas: Canvas, cell: "tuple[int, int]") -> bool:
    """Whether `cell` holds a text or a joint."""
    return not at(canvas, cell).empty


def mask(canvas: Canvas, cell: "tuple[int, int]") -> int:
    """The arms of the stroke at `cell`, 0 for none."""
    return at(canvas, cell).mask


def tag(canvas: Canvas, cell: "tuple[int, int]") -> object:
    """The tag at `cell`, None for none."""
    return at(canvas, cell).tag


def drawn(canvas: Canvas) -> "frozenset[tuple[int, int]]":
    """Every cell holding a text or a joint."""
    _check_canvas(canvas)
    out = set()
    for y in range(canvas.height):
        out.update((x, y) for x, (text, _) in texts(canvas, y).items() if text is not None)
        out.update((x, y) for x in joints(canvas, y))
    return frozenset(out)


def box(canvas: Canvas, tag: "Hashable") -> "tuple[int, int, int, int] | None":
    """(x, y, w, h) around every cell with this tag, None when none has it."""
    _check_canvas(canvas)
    cells = [(x, y) for y in range(canvas.height)
             for x, (_, t) in texts(canvas, y).items() if t is not None and t == tag]
    if not cells:
        return None
    xs, ys = [x for x, _ in cells], [y for _, y in cells]
    return min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1


def restyle(canvas: Canvas, cell: "tuple[int, int]", style: object, *, layer: str = "joint") -> bool:
    """Recolour what `cell` holds in place; False when it holds no such layer (see the module)."""
    _check_canvas(canvas)
    x, y = _pair(cell)
    if layer not in _LAYERS:
        raise ValueError(f"layer must be one of {_LAYERS}, got {layer!r}")
    done = False
    if layer in ("joint", "both"):
        done = repaint(canvas, x, y, style)
    if layer in ("text", "both"):
        row = texts(canvas, y)
        text = row.get(x, (None, None))[0]
        if text is not None:
            if text.width == 1:
                place(canvas, x, y, (Cell(text.glyph, 1, style),))
            else:
                head = x - 1 if text.width == 0 else x
                place(canvas, head, y, (Cell(row[head][0].glyph, 2, style), Cell("", 0, style)))
            done = True
    return done
