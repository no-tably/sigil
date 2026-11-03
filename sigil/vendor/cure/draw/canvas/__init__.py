"""[Canvas]: free drawing: strokes, junctions, plots, sprites.

Kind: system (the expansion of [Canvas] in Draw). Depends on Text only: no module of
this package imports another cure package. A {Charset} ([Theme]'s) arrives as an
argument and is used by duck typing; styles are opaque values, compared with `==`
only (Style's Colours compare with their roles, so runs of two roles never merge);
the {Rows} it gives are Text `Line`s, which Buffer's `Rows` takes as they are.

Free 2D drawing for what a box tree can't say (wires, maps, plots), on a sparse,
growing {Canvas} ([Strokes]): strokes as direction masks that join into the charset's
box-drawing glyphs ([Junctions]), straight runs hopping over crossings, text over
strokes ([Labels]), sub-cell plots ([Plot]), one-frame overlays on a kept canvas
([Sprites]), and the one public way to read a drawing back ([Query]).

The charset: any object with `glyph(token: str) -> str` and `plots` (a tuple of plot
mode names, finest first). These are the only two things this package uses on it,
and [Charset]'s {Charset} has both. Tokens asked for: `border.<weight>.<part>` for
the weights `light`, `heavy`, `double`, `dashed`, `dotted`, `heavy-dashed` (and
`rounded` corners) and [Charset]'s `PARTS`, falling back to `border.light.<part>`
when the charset has no glyph for the token ([Junctions]: with [Charset]'s tables
dashed draws ╌ ╎, dotted ┄ ┆, heavy-dashed ╍ ╏ on straight runs and ends, and at
corners, tees and crosses dashed and dotted draw light, heavy-dashed heavy); `block.full`, `block.eighths.h`, `block.eighths.v` ([Plot]).

The boundary (the ops other systems call), defined or re-exported here:

- `draw(source, charset=None, *, rounded=False)`, two flows by its argument's type:
  - a `Canvas` (a `Kept` included), the {Strokes} drawn into it (`(Sigil) -> [Canvas]
    : draw({Strokes}) => {Rows}`): `source.rows(charset, rounded=rounded)`, a
    `tuple[Line, ...]` ({Rows}). `charset` is required here: `None` is a
    `TypeError`.
  - any other iterable, of [Junctions]' `Path` ({Paths}, from Graph's [Route]:
    `[Graph] -> [Canvas] : draw({Paths}) => {Canvas}`): a new `Canvas` with each path
    `stroke`d in order (the hop rule on, [Strokes]). `charset` and `rounded` are not
    used. An empty iterable gives an empty canvas.
  Errors: `TypeError` for a `str`, a lone `Path`, a non-iterable, or an item that is
  not a `Path`; as `rows` / `stroke` otherwise. Effects: none on `source`.
- `keep(canvas) -> Kept` ({Canvas} => {Kept}, for Memo): [Strokes]' `keep`.
- `link(path, hops=frozenset()) -> Masks` ({Path} => {Masks}, for Graph's
  [Diagram]): [Junctions]' `link`.

Re-exported for consumers: `Canvas`, `Kept`, `stroke`, `stub`, `blit` (strokes);
`Path`, `Masks`, `Joint`, `join`, `N`, `E`, `S`, `W`, `WEIGHTS`, `RANK` (junctions);
`label` (labels); `Dots`, `fold`, `plot`, `mode`, `bar`, `spark`, `CELL` (plot);
`overlay`, `undo`, `Undo` (sprites); `Occupied`, `at`, `occupied`, `mask`, `tag`,
`drawn`, `box`, `restyle` (query).

Effects: none outside the canvases the caller passes in.

Usage:
    from cure.draw.canvas import Canvas, Path, draw, keep, link, label
    from cure.draw.theme.charset import Charset
    cs = Charset()
    c = draw([Path([(0, 0), (3, 0)]), Path([(3, 0), (3, 1)], "heavy")])
    label(c, 0, 1, "ok")
    [l.plain for l in draw(c, cs)]           # ["───┓", "ok ┃"]
    link(Path([(0, 0), (0, 1)])).cells       # (((0, 0), 4), ((0, 1), 1))
    keep(c) == c                             # True
"""

from collections.abc import Iterable

from cure.core.text import Line

from .junctions import E, N, RANK, S, W, WEIGHTS, Joint, Masks, Path, join, link
from .labels import label
from .plot import CELL, Dots, bar, fold, mode, plot, spark
from .query import Occupied, at, box, drawn, mask, occupied, restyle, tag
from .sprites import Undo, overlay, undo
from .strokes import Canvas, Kept, blit, keep, stroke, stub


def draw(source: "Canvas | Iterable[Path]", charset: object = None, *, rounded: bool = False) -> "tuple[Line, ...] | Canvas":
    """A canvas's rows ({Strokes} => {Rows}), or paths stroked onto a new canvas ({Paths} => {Canvas})."""
    if isinstance(source, Canvas):
        if charset is None:
            raise TypeError("drawing a canvas needs a charset")
        return source.rows(charset, rounded=rounded)
    if isinstance(source, (str, Path)) or not isinstance(source, Iterable):
        raise TypeError(f"expected a Canvas or an iterable of Path, got {type(source).__name__}")
    paths = tuple(source)
    for path in paths:
        if not isinstance(path, Path):
            raise TypeError(f"expected a Path, got {type(path).__name__}")
    canvas = Canvas()
    for path in paths:
        stroke(canvas, path)
    return canvas
