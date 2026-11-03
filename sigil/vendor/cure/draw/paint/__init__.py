"""[Paint]: one frame: measure, lay out, paint, compose.

Kind: system (the expansion of [Paint] in Draw); pure. One frame is a pure function:
the same node tree, size and context give the same frame. Its parts: [Measure]
(natural sizes without painting, memoised: `adapt`, `natural`, `Measure`), [Painter]
(parents fill their rect before the children; theme scope, alignment zone and surface
level pushed and restored at one recursion point: `contexts`, `paint`, `tiles`) and
[Frame] (the base, then overlays by z: `frame`, `sizes`, the `Frame` result, the
`Tiled` view). Each module states its contract in full.

Imports: Paint depends on Buffer, Geometry, Layout, Theme and Widgets (and, through
Draw, Core); never on Draw's `context.py` (a {Context} arrives as the app's argument
and is rebuilt only by Theme's `enter` and `dataclasses.replace`), Canvas, Graph or
Memo.

How Paint adapts what Widgets may not know (the widget families may not import
Layout, Theme or Paint):
- Boxes: Paint lays out an adapted tree whose nodes carry `Box(**node.chrome())`
  ([Measure]'s `adapt`), so Layout reads each node's box; a widget's chrome rects are
  exactly that box's.
- Measuring: Layout's `measure(node, axis, room)` is [Measure]'s `Measure`, which calls
  the widget's `measure(axis, room, ctx, content)` with the node's own context and its
  children's natural `content`, memoised per `(path, axis, room)` within the frame.
- Contexts: [Painter]'s `contexts` derives every node's context at one recursion point:
  Theme's `enter` (scope; one surface level per surface node, from the app's base),
  then `lift` for a focus pane's subtree, then the `zone` sibling key:value lists
  share.
- Layers: an Overlay paints on its own layer (`layer`, `backdrop`; `modal` records
  `(id, "outside")` over the area beneath its own hits), a Screens modal on the
  screen's layers (`LAYERS` apart), placed by Layout's Anchor; the router's floor is
  `frame.layer`.
- Splits: a `Tiled` view is laid out pane by pane (`panes`, then `lay` per visible
  pane), with gutters and tab / title bars drawn and hits kept per pane.
- Viewports and offsets are taken as given: a List's `offset`, a Drawing's `x` / `y`,
  a Scaffold's `offset` are the app's, in the nodes; Paint reports each node's rect
  (`frame.places`) so the app keeps its Viewport in step for the next frame.

The boundary:
- `frame(view, size, ctx) -> Frame` (`(Sigil)`, `(Construct)`, `(Merlang)`, `[Pilot]
  -> [Paint] : frame({Node}) => {Frame}`; Draw re-exports it for Testing).
- `sizes(view, widths, heights, ctx) -> tuple[Frame, ...]` (`[Sweep] -> [Paint] :
  sizes({Node}) => {Frames}`).
- Paint calls Theme's `enter`, Layout's `lay` (and `panes`, `place`), Widgets' `paint`
  and Buffer's `compose` / `put`.

Re-exported for consumers: `frame`, `sizes`, `Frame`, `Tiled` (frame); `Place`,
`Painted`, `LAYERS`, `contexts`, `tiles` (painter; its `paint` is reached as
`cure.draw.paint.painter.paint`, so `paint.paint` is never mistaken for Widgets'); `Adapted`, `Measure`,
`adapt`, `natural` (measure). Note: the function `frame` shadows the submodule of the
same name as a package attribute; reach the module's own names with a from-import of
its dotted path (`from cure.draw.paint.frame import Frame`).

Effects: none.

Usage:
    from cure.core.buffer import text
    from cure.draw.context import Context
    from cure.draw.theme import builtin
    from cure.draw.widgets import Block, Paragraph
    from cure.draw import paint
    f = paint.frame(Block((Paragraph("hi"),), id="b"), (6, 3), Context.of(builtin()))
    text(f.buffer)                 # "╭────╮\\n│hi  │\\n╰────╯"
    f.hits.at(2, 1), f.size        # "b", (6, 3)
    [g.size for g in (x.buffer for x in paint.sizes(Paragraph("hi"), (2, 3), (1,),
                                                    Context.of(builtin())))]
    #   [(2, 1), (3, 1)]
"""

from .frame import Frame, Tiled, frame, sizes
from .measure import Adapted, Measure, adapt, natural
from .painter import LAYERS, Painted, Place, contexts, tiles
