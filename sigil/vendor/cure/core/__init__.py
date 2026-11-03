"""[Core]: Text, Style, Buffer, Geometry.

Kind: system (the expansion of [Core] in cure); pure. What everything stands on: Text
(cell widths, graphemes, styled spans, wrap), Style (colours, inks, attributes, the
one SGR seam), Buffer (cells, layers, diff, display, rows, the wire format), Geometry
(rects and the hit map), and Core's own {Caps} (`cure.core.caps`: what a terminal can
do, which Edge's Term probes). The values the packages share (`Rect`, `HitMap`,
`Caps`, `Grid`) are plain data here, so no package needs another's code to use them.

The boundary (the ops the other packages call), re-exported from Buffer:

- `write(grid, x, y, row, *, within=None) -> Grid` (for [Draw] and [Interact]:
  `[Draw] -> [Core] : write({Cells}) => {Grid}`, `[Interact] -> [Core] : write({Cells})
  => {Grid}`): a well-formed row of cells laid at (x, y), clipped; Buffer's `write`
  ([Grid]), the same object (`cure.core.write is cure.core.buffer.write`); refine
  round 9 (the root flows name the op Paint's Painter and Vt's Screen call).
- `show(display, grid, *, cursor=None) -> bytes` (for [Edge]: {Buffer} => {Bytes}):
  the bytes that bring a terminal's front buffer up to `grid`; Buffer's `show`
  ([Display]).
- `rows(grid) -> Rows` (for [Testing]: {Buffer} => {Rows}): a grid read back as rows of
  runs, the golden format; Buffer's `runs` ([Rows]), under the name the flow gives it.

Re-exported for consumers: `Caps` (caps); `Rect`, `Hit`, `HitMap` (geometry); `Grid`,
`Display`, `Rows` and `cells` (buffer; `cells(rows, w=None, h=None) -> Grid`: rows of
`(text, style)` runs laid into a new Grid, Buffer's `cells` ([Rows]), the op of the
drawn `(Gallery) -> [Core] : cells({Rows}) => {Grid}`: the gallery's panes' screens,
made from text; apps use it too).

Effects: none (importing it imports its children, nothing else).

Usage:
    from cure.core import Caps, Display, cells, rows, show
    g = cells(["hello", "world"])
    rows(g).plain                         # ("hello", "world")
    show(Display(Caps(depth=16)), g)      # the first frame's bytes
"""

from .buffer import Display, Grid, Rows, cells, show, write
from .buffer import runs as rows
from .caps import Caps
from .geometry import Hit, HitMap, Rect
