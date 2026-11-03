"""[Surfaces]: content drawn elsewhere, shown through a rect: Drawing, Pane.

Kind: system (the expansion of [Surfaces] in Widgets); pure. It imports Core only
(Text, Style, Buffer, Geometry, which it inherits through Draw): never Collections,
Containers, Controls, Readouts, the Widgets package, Layout, Theme, Canvas, Graph,
Vt, Embed, Paint or Draw's `context.py`. A {Context} arrives as an argument and is
read by attribute; a Layout {Viewport}'s offset arrives as plain ints (`x`, `y`),
which the app reads off its viewport (`viewport.x`, `viewport.y`).

The parts, every one a leaf (no children, `chrome()` is `None`, `lifts(ctx)` is
`False`, `surface` defaults to `False`): [Drawing] (`Drawing`: rows of runs, a
canvas's, a graph's or sigil's, through a viewport) and [Pane] (`Pane`: a Buffer
{Grid} from elsewhere, an embedded terminal's screen, blitted, clipped or padded).

Neither makes what it shows: a Drawing's rows are rendered by Canvas, Graph or the
app beforehand (Rules carried over: rows of `(text, style)` runs are the authoring
format); a Pane's grid is a Vt screen's, kept by Embed. Both show it at an offset
the app keeps (Layout's Viewport computes it: pan, follow a focus box), so content
cell `(cx, cy)` is drawn at screen cell `(R.x + cx - x, R.y + cy - y)`; an offset
may be negative (a blank lead-in) or past the content (blank ground).

The node protocol, as the Widgets package states it in full (`cure/draw/widgets`):
each kind is a frozen dataclass, its content fields first, then keyword-only fields
ending in `id`, `size`, `anchor`, `scope`, `surface`; `measure(axis, room, ctx,
content=0) -> int` (the content's own size; `content` ignored), `paint(rect, ctx,
grid, clip=None) -> tuple[Hit, ...]`, following the recipe (the clip's ground
`ctx.ground()`, the content, `shade(grid, clip, bg=g.style.bg)`: content cells with
no background of their own take the ground's).

States: neither has a state of its own to show. A surface is focused as a whole
(keys go to the drawing's app or the embedded program); the focus shows through its
pane (the enclosing Block's border comes up and turns heavy) and, for a Pane, the
terminal cursor the app places at `cursor_at`. So the legible law holds vacuously.

Every law listed in the Widgets package (contained, owned, pure, hits, moved,
legible, fits) holds for every kind here.

The data: {Extent} (`Extent`, `extent.py`): a Drawing's content extent `(width,
height)`, a `NamedTuple`; a Drawing's `extent` is one, the caller's or counted.

Re-exported for consumers: `Drawing` (drawing); `Extent` (extent); `Pane` (pane).

Effects: none, apart from `paint`'s writes into the grid it is given.

Usage:
    from cure.core.buffer import Grid, put, text
    from cure.core.geometry import Rect
    from cure.draw.context import Context
    from cure.draw.theme import builtin
    from cure.draw.widgets.surfaces import Drawing, Pane
    ctx = Context.of(builtin())
    g = Grid(4, 2)
    Drawing(("abcdef", "ghijkl", "mnopqr"), x=2, y=1, marks=False).paint(Rect(0, 0, 4, 2), ctx, g)
    text(g)                      # "ijkl\\nopqr"
    src = put(Grid(3, 1), 0, 0, "ab")
    Pane(src).paint(Rect(0, 0, 4, 2), ctx, g)
    text(g)                      # "ab\\n"
"""

from .drawing import Drawing
from .extent import Extent
from .pane import Pane
