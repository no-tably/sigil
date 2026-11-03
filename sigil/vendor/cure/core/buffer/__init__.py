"""[Buffer]: cells, layers, diff, display, rows, the wire format.

Kind: system (the expansion of [Buffer] in Core); pure: no I/O, no process-wide state.
Depends on Text (cell widths, clusters, the {Cell} model, spans) and Style (the {Style}
a cell carries, and the one SGR seam); nothing else in cure. Rects arrive as plain
`(x, y, w, h)` tuples or any object with those attributes (a Geometry {Rect}); a
{Caps} arrives as an argument and is read by its attributes.

The cell substrate every frame lands on (rects, then cells, then strings):
[Cells] fixes the cell model (glyph, width, style; a wide glyph is a head and its
tail; marks ride their base). [Grid] holds a frame's cells and writes into them (put,
write, fill, blit, clip, shade) without ever leaving half a wide glyph. [Layers]
composes a frame from layers by z, each with its backdrop. [Diff] compares the front
buffer with the new frame as coalesced runs. [Display] holds one front buffer per
terminal or client and returns the bytes that bring it up to date; the idle frame is
silent. [Rows] converts to and from rows of `(text, style)` runs, the authoring and
golden format. [Wire] packs rows for the TS hosts (one code point per cell, plus per
row a side table of the clusters longer than one code point), versioned.

The boundary (the ops other systems call), defined in the modules and re-exported here:

- `cells(rows, w=None, h=None) -> Grid` ({Rows} => {Grid}, for (Sigil)): rows of
  runs laid into a new grid; see [Rows] (`rows.cells`).
- `put(grid, x, y, spans, style=None, *, within=None) -> Grid` ({Spans} => {Grid},
  for Paint's [Painter]): spans laid into a grid in place; see [Grid] (`grid.put`).
- `compose(layers, w, h) -> Grid` ({Layers} => {Grid}, for Paint's [Frame]): see
  [Layers] (`layers.compose`).
- `show(display, grid, *, cursor=None) -> bytes` ({Grid} => {Bytes}, for Remote's
  [Remote] and [Attach], and Edge's [Term]): see [Display] (`display.show`).
- `text(grid) -> str` ({Grid} => {Text}, for Testing's [Snapshot]): see [Rows]
  (`rows.text`).
- `packed(source, *, colours="role") -> Packed` ({Rows} => {Packed}, for (Host)): see
  [Wire] (`wire.packed`).

Re-exported for consumers: `Cell`, `BLANK`, `blank`, `tail`, `check` (cells); `Grid`,
`write`, `fill`, `blit`, `clip`, `shade` (grid); `Layer`, `BACKDROPS` (layers);
`diff`, `Change`, `Changes`, `GAP` (diff); `Display` (display); `Rows`, `runs`
(rows); `pack`, `Packed`, `WIRE` (wire).

Note: the functions `cells` and `diff` shadow the submodules of the same names as
package attributes. Reach a submodule's own names with a from-import of the dotted
module path (`from cure.core.buffer.cells import line`), never through the attribute.

Speed (F1). Writing, blitting and composing cells whose glyphs are printable ASCII
skip the grapheme and width re-checks (Text's fast path, and [Cells]' `check`); nothing
public changes. Law fast_equal: every boundary op above and every re-exported function
gives the general path's result and error (as of commit 26d0853; `==`, the same types,
the same error class and message), and `show` emits the same bytes for the same
sequence of grids, cursors and caps (it reads only the cells, which are `==`).

F2. A grid's rows are always well formed: `Grid(fill=)` and `fill` take a narrow cell
by [Cells]' rule (one cluster of width 1), not by its width alone, so `blit` and
`clip` of a `Grid` need not check its rows again. The one change to the law above:
a malformed fill cell (a width `True` or `1.0`, or a glyph that is not one cluster of
width 1) is now a `ValueError` at `Grid(...)` / `fill`, where it was stored before and
raised (if ever) at `blit` / `clip`; every other input gives the result and error of
commit fd3bc4b (see [Grid]'s Speed (F2)).

The budget, as testable numbers. `U`, the calibration unit, is measured in the same
process as the benchmark, so a budget moves with the machine and its load: for each of
the 40 rows of B3 (below), a tuple of one instance per character of a frozen dataclass
the test defines itself (fields `glyph`, `width`, `style`; not Text's `Cell`, so `U`
does not move with cure), then the list of those tuples compared `==` with a copy.
Method: one warm-up call each, then 7 rounds, each timing `U` best of 5 and every
benchmark best of 2 (`time.perf_counter`), interleaved; a budget is `min(bench) <= k *
min(U)` over all rounds (the minimum, since load only adds). The test skips under a
tracer (`sys.gettrace()` is not `None`: coverage, a debugger). Measured on the dev
machine under load, `U` was 2.5-3.5 ms and the ratios moved by about 10% across runs.
- B3, Buffer's: `put(g, 0, y, rows[y])` for `y` in 0..39 into a fresh `Grid(116, 40)`,
  `rows[y] = "".join(WORDS[(y + i) % 12] + " " for i in range(20))[:116]`, `WORDS =
  ("lorem", "ipsum", "dolor", "sit", "amet", "consectetur", "adipiscing", "elit",
  "sed", "do", "eiusmod", "tempor")`: 116 printable-ASCII characters each.
  Baseline (26d0853): 29-33 U (48-110 ms by load). Budget: `k = 6`
  (5 times faster; a prototype of the fast path measured 3.4-3.6 U).
Paint's budgets (B1, B2, B4) use the same `U` and method (see Paint's [Frame]).

Inputs, outputs and errors: as each module states. Effects: none, apart from the
in-place writes [Grid]'s functions make to the grid they are given and the state a
`Display` keeps for its own terminal.

Usage:
    from cure.core.caps import Caps
    from cure.core.buffer import Display, Grid, Layer, compose, put, show, text
    base = put(Grid(20, 3), 0, 0, "hello")
    frame = compose([Layer(base)], 20, 3)
    d = Display(Caps(depth=256))
    data = show(d, frame)          # bytes for the terminal; the caller writes them
    show(d, frame)                 # b"": the idle frame is silent
    text(frame)                    # "hello\\n\\n"
"""

from .cells import BLANK, Cell, blank, check, tail
from .diff import GAP, Change, Changes, diff
from .display import Display, show
from .grid import Grid, blit, clip, fill, put, shade, write
from .layers import BACKDROPS, Layer, compose
from .rows import Rows, cells, runs, text
from .wire import WIRE, Packed, pack, packed
