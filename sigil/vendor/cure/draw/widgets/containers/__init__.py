"""[Containers]: node kinds: each measures, paints into its rect from the {Context} it is
given, and records its hit rects; none calls Canvas, Graph or Theme.

Kind: system (the expansion of [Containers] in Widgets); pure. It imports Core only
(Text, Style, Buffer, Geometry, which it inherits through Draw): never Readouts or
another family, the Widgets package, Layout, Theme, Paint or Draw's `context.py`. A
{Context} arrives as an argument and is read by attribute.

The parts: [Block] (`Block`: a titled box, border set, title placement, surface
level, focus pop, and a `kind`, below), [Tabs] (`Tabs`, `Tab`: a strip and the
active body), [Disclosure] (`Disclosure`: a collapsible panel, header line, open / closed),
[Overlay] (`Overlay`: popover, modal, tooltip: a layer with an anchor), [Scrollbar]
(`Scrollbar`, and the scroll indicator `More`: `↓N more`).

The node protocol, as the Widgets package states it in full (`cure/draw/widgets`):
each kind is a frozen dataclass with its content fields, then keyword-only `id`,
`size`, `anchor`, `scope`, `surface` (and `children`, `layout` where it holds
children); `chrome() -> dict | None` (Layout `Box` keyword arguments, which Paint
turns into the node's box), `measure(axis, room, ctx, content=0) -> int` (chrome
included; `content` the children's natural size, from Paint), `paint(rect, ctx, grid,
clip=None) -> tuple[Hit, ...]` (the node's ground and chrome only, inside `clip`; the
children are Paint's, painted after it), and `lifts(ctx) -> bool` (the focus pane).
A container's `size`, `layout` and `anchor` are Layout values the app builds and the
node holds opaque. Every law listed there (contained, owned, pure, hits, moved,
legible, fits) holds for every kind here.

A box's `kind` (R2). Block and Overlay take a keyword-only `kind`, a free `str`
(`"block"` by default; Views gives `"pane"` and `"dialog"`), one lowercase word
(Block's `KIND`; no dots, so it never clashes with a weight-qualified
token), after `focus_border` in their fields. It
names the box's edge patterns from R3 on (a theme's `frame.<kind>.<edge>`). Not to
be confused with a node's kind (its class) nor with the class attribute `pane`. Laws:
`kind-inert` (for every kind, chrome, measure, lifts and paint equal those with kind
`"block"`, until R3), and the 74f1f6a oracle (with the default, every frame equals
that commit's); equality and hash include it.

Re-exported for consumers: `Block` (block); `Tabs`, `Tab` (tabs); `Disclosure`
(disclosure); `Overlay` (overlay); `Scrollbar`, `More` (scrollbar).

Effects: none, apart from `paint`'s writes into the grid it is given.

Usage:
    from cure.core.buffer import Grid, text
    from cure.core.geometry import Rect
    from cure.draw.context import Context
    from cure.draw.theme import builtin
    from cure.draw.widgets.containers import Block
    ctx = Context.of(builtin(), level=1)
    g = Grid(11, 3)
    Block(title="Title", id="b").paint(Rect(0, 0, 11, 3), ctx, g)   # (Hit(Rect(0, 0, 11, 3), "b"),)
    text(g)            # "╭─ Title ─╮\\n│         │\\n╰─────────╯"
"""

from .block import Block
from .disclosure import Disclosure
from .overlay import Overlay
from .scrollbar import More, Scrollbar
from .tabs import Tab, Tabs
