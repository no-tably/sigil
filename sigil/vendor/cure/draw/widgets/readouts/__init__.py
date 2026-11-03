"""[Readouts]: text, values and gauges drawn from data the app gives.

Kind: system (the expansion of [Readouts] in Widgets); pure. Its own `depends_on` is
empty (the export's): it imports Core (Text, Style, Buffer, Geometry), which it
inherits through the root's `[Draw] -> [Core]`: never Containers or another family, the
Widgets package, Layout, Theme, Paint or Draw's `context.py`. A {Context} arrives as
an argument and is read by attribute.

The parts, every one a leaf (no children, `chrome()` is `None`, `lifts(ctx)` is
`False`): [Paragraph] (`Paragraph`: styled text, wrapped and aligned),
[PropertyList] (`PropertyList`, `Item`: key:value rows aligned at the separator),
[StatusBar] (`StatusBar`, `Segment`: segments by priority, never clipped off the
left), [KeyHints] (`KeyHints`, `Hint`: drawn from a bindings table it is given),
[Legend] (`Legend`, `Entry`: marker + word entries that wrap between entries),
[Toast] (`Toast`: transient notes), [Progress] (`Bar`, `Gauge`, `Pulse`, `Spinner`:
phase from the tick; coloured by the widget roles `progress.fill`, `progress.track`,
`progress.label` and `progress.figure`, which the builtin declares over `accent`,
`dim`, `text` and `muted`, so a theme restyles Progress alone; W1: every builtin
frame unchanged but the role tags), [Chart] (`Sparkline`, `Bars`, `Lines`, `Series`: sparkline,
bars, lines in braille).

The boundary: no flow of its own crosses out of Readouts. [PropertyList]'s key zone
is Text's `measure(keys)` (zone = 1 + the widest key), one of Draw's uses of Core's
primitives that the root's `[Draw] -> [Core]` stands for (not drawn one by one).

The node protocol, as the Widgets package states it in full (`cure/draw/widgets`):
each kind is a frozen dataclass, its content fields first, then keyword-only `id`,
`size`, `anchor`, `scope`, `surface` (each kind's default `surface` is `False` but
Toast's, `True`); `measure(axis, room, ctx, content=0) -> int` (`content` ignored),
`paint(rect, ctx, grid, clip=None) -> tuple[Hit, ...]`. Painting follows the
protocol's recipe (the clip's ground, the content, `shade` with the ground's bg),
text is styled text (a span style `None` is the kind's role, a `str` a role name, a
Style as given), overflow shows (`…` on a cut row, `↓N more` as a last row) and
states stack additively with their marks in reserved cells. Every law listed there
(contained, owned, pure, hits, moved, legible, fits) holds for every kind here.

Re-exported for consumers: `Paragraph` (paragraph); `PropertyList`, `Item`
(propertylist); `StatusBar`, `Segment` (statusbar); `KeyHints`, `Hint` (keyhints);
`Legend`, `Entry` (legend); `Toast` (toast); `Bar`, `Gauge`, `Pulse`, `Spinner`
(progress); `Sparkline`, `Bars`, `Lines`, `Series` (chart).

Effects: none, apart from `paint`'s writes into the grid it is given.

Usage:
    from cure.core.buffer import Grid, text
    from cure.core.geometry import Rect
    from cure.draw.context import Context
    from cure.draw.theme import builtin
    from cure.draw.widgets.readouts import PropertyList, Item
    ctx = Context.of(builtin())
    g = Grid(12, 2)
    PropertyList((Item("name", "cure"), Item("id", "42"))).paint(Rect(0, 0, 12, 2), ctx, g)
    text(g)            # "-name: cure\\n---id: 42"
"""

from .chart import Bars, Lines, Series, Sparkline
from .keyhints import Hint, KeyHints
from .legend import Entry, Legend
from .paragraph import Paragraph
from .progress import Bar, Gauge, Pulse, Spinner
from .propertylist import Item, PropertyList
from .statusbar import Segment, StatusBar
from .toast import Toast
