"""[BuilderGrid]: every builder, a self-scaling grid of live panes.

Kind: service (pure functions from Board {Builder}s, the tab's area and its kept split
tree to a widget node; see the OverviewTab package for the tab, its key `k ==
("overview",)` and its ids).

What it does: one live terminal per builder, side by side: a Widgets `Block` whose
children, one titled Block per builder (a `Pane` over its screen, or a placeholder
before its first frame, under its phase as a Progress beside the phase word when it
has one, as BuilderTab's info pane shows it), are laid in a Layout `Grid` of equal
`Fill` columns and rows, so the grid fills whatever rect the pane gets. How many
columns and rows it has is chosen from the builders' count and the room the pane
has: BuilderGrid finds its own tile through Layout's Splits (`[BuilderGrid] ->
[Layout] : panes({SplitTree}) => {Rects}`: `panes(kept, area)`, the tree the app
draws, in the area it draws it in) and picks the shape that gives each terminal the
most room at a terminal's aspect. It paints nothing itself; the screens are
construct's (Embed and Vt, on its side), held, never copied.

The shape (`shape(n, room=None) -> (columns, rows)`), for `n` builders (an int `>=
0`) and `room` `None` or `(w, h)`, ints `>= 0`:
- `n == 0`: `(0, 0)`.
- `room is None`: `c = ceil(sqrt(n))` (`math.isqrt(n - 1) + 1`), `r = ceil(n / c)`:
  the squarest grid.
- otherwise: of every `c` in `1 .. n`, with `r = ceil(n / c)`, `cw = w // c`, `ch =
  h // r`, the one with the greatest `score = min(cw * ASPECT[1], ch * ASPECT[0])`
  (the size an `ASPECT == (80, 24)` terminal would be drawn at in one cell, in
  integers), ties going to the fewest empty cells (`c * r - n`), then the fewest
  columns; that `c` and its `r`.
So every shape has `c * r >= n` and no empty row (`c * (r - 1) < n`), and the cells
fill row-major in the builders' order.

The room (`room(size=None, kept=None) -> (w, h) | None`): `None` when `size` or `kept`
is `None`, or `"builders"` is not a visible pane of `T = panes(kept, Rect(0, 0, w,
h))` (`(w, h) == size`; not in the tree, or hidden behind another tab or a zoom);
else, with `R = T["builders"].rect` (Layout's `Tiling`), `(max(0, R.w - 2), max(0,
R.h - 2))`: the tile less the pane Block's border, the room its cells share.

A builder's cell (`cell(builder) -> Block`): `Block((child,), title=T, kind="pane",
id=k + ("builder", builder.id))` when `progress(builder) is None`, else `Block((p,
child), title=T, kind="pane", id=k + ("builder", builder.id))` with `p ==
progress(builder)` (one row over the terminal, which takes the rest of the Block's
default Column: its `size` is `None`), every other Block field its default, where
`T` is
`f"{id}: {task}, {s}"` (`"b2: X3, working (proofs)"`), or `f"{id}, {s}"` when
`builder.task is None`, `s` being `builder.status`, or `f"{status} ({phase})"`
when the phase is not `""`; and `child`:
- with a screen: `Pane(builder.screen, cursor=builder.cursor, id=k + ("screen",
  builder.id))` (the app focuses that id to send the builder's terminal keys);
- with `screen is None`: `Paragraph(PLACEHOLDER, role="muted")` (no id),
  `PLACEHOLDER == "no screen yet"` (BuilderTab's, restated: no tab imports another).

A builder's phase widget (`progress(builder) -> Gauge | Spinner | None`; BuilderTab's,
restated), the first that applies (Widgets' Progress kinds, every field not named its
default, no id):
- `builder.progress == (s, t)`: `Gauge(s / t, label=L, size=Fixed(1))`, `L ==
  f"{builder.phase} {s}/{t}"`, or `f"{s}/{t}"` when the phase is `""` (the phase
  word beside the bar; Gauge adds the percentage after it);
- else `builder.status == "working"`: `Spinner("dots", label=builder.phase or
  "working", size=Fixed(1))` (its frame is Paint's, from `ctx.now` alone: the tab
  reads no clock);
- else `None`.

The pane (`buildergrid(builders, *, size=None, kept=None) -> Block`), for `builders`
a `tuple` of {Builder} (the Board's, in its order):
- with builders: `Block(tuple(cell(b) for b in builders), title="builders",
  kind="pane", layout=Grid((Fill(1),) * c, (Fill(1),) * r), id=k + ("builders",))`
  (Layout's `Grid` and `Fill`), `(c, r) == shape(len(builders), room(size, kept))`;
- with none: `Block((Paragraph(EMPTY, role="muted"),), title="builders",
  kind="pane", id=k + ("builders",))`, `EMPTY == "no builders yet"`.
OverviewTab passes `kept` as the app's kept tree, or its own default `tree()` when
the app gives none.
Kinds (R2): the pane Block and every cell are of kind `"pane"`. A cell is nested in
the pane, yet it is a pane in its own right: a live terminal, framed and titled,
the focus pane while its screen has the keys, drawn as BuilderTab's `"terminal"`
pane is, so a theme's pane patterns (R3) frame each terminal alike wherever it is
shown. Inert until R3 (Block's `kind-inert`).

Laws (each a property a test can loop over builder tuples, sizes, trees and
contexts):
- pure: equal arguments give equal results (`shape`, `room`, `progress`, `cell`,
  `buildergrid`).
- once: every builder has exactly one cell, in the board's order: the pane's
  children are `cell(b)` for `b` in `builders`, ids `k + ("builder", b.id)` each
  once.
- fits: `c * r >= n` and `c * (r - 1) < n` for every `shape(n, room)` with `n >=
  1`; `shape(n, room)` is never wider than `n` columns.
- shaped: `shape(n, room)` is exactly the rule above (a test can compare it with a
  brute-force search over `c`); `room(size, kept)` follows the tile, so a kept tree
  that gives the builders a wider tile is scored on that tile.
- ids: the node ids carried are exactly `{k + ("builders",)} | {k + ("builder",
  b.id) for b} | {k + ("screen", b.id) for b with a screen}` (the phase widgets
  carry none).
- screen: each Pane holds the very `Grid` object its builder holds (not a copy).
- legible: with colour off (Caps depth 0), each builder's status is a word of its
  cell's title, drawn whenever the title fits its border; its phase widget reads
  whenever its row is drawn whole: a gauge by its glyphs (`block.full`, the eighths
  and `block.light` differ in glyph, not only in colour) and its label word (`L`), a
  spinner by its frame glyph and its word (the phase, or `"working"`).
- unchanged: a builder with `progress is None` and a status other than `"working"`
  gives a `cell` equal to the commit before X5's (the code at 62d91e8, a git oracle
  loaded with `git archive` at test time), `kind` aside (R2: left out of the
  comparison, the old Block having none), so a board of only such builders gives
  frames equal to it cell for cell, at every size and context of OverviewTab's
  frames law.
- stable: a frame at a fixed `ctx.now` is the same every time it is drawn (the
  spinner's frame is `ctx.now`'s alone).
- frames: OverviewTab's frames law (never raises at `1..120 x 1..40`) holds for
  builders with and without progress, in every status.

Inputs: `builders` a `tuple` of Board {Builder}, `builder` one (read by attribute);
  `size` `None` or a `tuple` of two ints `>= 0`, the tab's area; `kept` `None` or a
  Layout `SplitTree`; `n` an int `>= 0`; `room` `None` or a `tuple` of two ints
  `>= 0`.
Outputs: a `(columns, rows)` pair of ints; a `(w, h)` pair or `None`; Widgets `Block`s
  (of `Pane`s or `Paragraph`s, a cell's under a `Gauge` or a `Spinner`); a `Gauge`,
  a `Spinner` or `None` (`progress`).
Errors: `TypeError` when `builders` is not a `tuple`, `size` or `room` is neither
  `None` nor a `tuple` of two ints (a `bool` refused), `kept` is neither `None` nor
  a `SplitTree`, or `n` is not an int; `ValueError` when a size, a room value or `n`
  is negative. Layout's `panes` cannot fail on a valid tree and area.
Effects: none.

Usage:
    from cure.core.buffer import Grid
    from cure.draw.views.board import Builder
    from cure.draw.views.overviewtab import buildergrid
    buildergrid.shape(4)                  # (2, 2)
    buildergrid.shape(4, (118, 38))       # (2, 2): 59 x 19 each
    buildergrid.shape(3, (200, 30))       # (3, 1)
    bs = (Builder("b1", task="X2", status="working", screen=Grid(80, 24)), Builder("b2"))
    buildergrid.cell(bs[0]).title         # "b1: X2, working"
    buildergrid.cell(bs[0]).children[0]   # Spinner("dots", label="working", size=Fixed(1))
    len(buildergrid.cell(bs[1]).children) # 1: starting, no progress: the cell as before X5
    buildergrid.progress(Builder("b3", phase="proofs", progress=(1, 4)))
                                          # Gauge(0.25, label="proofs 1/4", size=Fixed(1))
    buildergrid.buildergrid(bs).layout    # Grid(columns=(Fill(weight=1), Fill(weight=1)), rows=(Fill(weight=1),), gap_x=0, gap_y=0)
"""

import math

from cure.core.geometry import Rect
from cure.draw.layout import Fill, Fixed, Grid, SplitTree, panes
from cure.draw.widgets import Block, Gauge, Pane, Paragraph, Spinner

KEY = ("overview",)
"""The tab's key (OverviewTab's `k`)."""

PLACEHOLDER = "no screen yet"
"""What a builder's cell says before its first frame."""

EMPTY = "no builders yet"
"""What the pane says when the board has no builders."""

ASPECT = (80, 24)
"""The terminal shape a cell is scored against: (columns, rows)."""


def shape(n: int, room: "tuple[int, int] | None" = None) -> "tuple[int, int]":
    """The grid's (columns, rows) for `n` builders in `room` (see the module)."""
    if not _is_int(n):
        raise TypeError(f"n must be an int, got {type(n).__name__}")
    _pair(room, "room")
    if n < 0:
        raise ValueError(f"n must be >= 0, got {n}")
    _nonneg(room, "room")
    if n == 0:
        return (0, 0)
    if room is None:
        c = math.isqrt(n - 1) + 1
        return (c, -(-n // c))
    w, h = room
    best = None
    for c in range(1, n + 1):
        r = -(-n // c)
        score = min((w // c) * ASPECT[1], (h // r) * ASPECT[0])
        rank = (-score, c * r - n, c)
        if best is None or rank < best[0]:
            best = (rank, c, r)
    return (best[1], best[2])


def room(size: "tuple[int, int] | None" = None, kept: "SplitTree | None" = None
         ) -> "tuple[int, int] | None":
    """The builders tile's inner size, through Layout's `panes(kept, area)`, or None."""
    _pair(size, "size")
    _kept(kept)
    _nonneg(size, "size")
    if size is None or kept is None:
        return None
    tiling = panes(kept, Rect(0, 0, size[0], size[1]))
    tile = next((p for p in tiling.visible if p.id == "builders"), None)
    if tile is None:
        return None
    return (max(0, tile.rect.w - 2), max(0, tile.rect.h - 2))


def cell(builder: object) -> Block:
    """One builder's cell: a titled Block around a Pane over its screen, or the placeholder."""
    s = f"{builder.status} ({builder.phase})" if builder.phase else builder.status
    title = f"{builder.id}, {s}" if builder.task is None else f"{builder.id}: {builder.task}, {s}"
    if builder.screen is None:
        child = Paragraph(PLACEHOLDER, role="muted")
    else:
        child = Pane(builder.screen, cursor=builder.cursor, id=KEY + ("screen", builder.id))
    p = progress(builder)
    phase = () if p is None else (p,)  # one row over the terminal, when there is one
    return Block((*phase, child), title=title, kind="pane", id=KEY + ("builder", builder.id))


def progress(builder: object) -> "object | None":
    """A builder's phase widget: a Gauge with progress, a Spinner while working, or None."""
    if builder.progress is not None:
        s, t = builder.progress
        label = f"{s}/{t}" if builder.phase == "" else f"{builder.phase} {s}/{t}"
        return Gauge(s / t, label=label, size=Fixed(1))
    if builder.status == "working":
        return Spinner("dots", label=builder.phase or "working", size=Fixed(1))
    return None


def buildergrid(builders: tuple, *, size: "tuple[int, int] | None" = None,
                kept: "SplitTree | None" = None) -> Block:
    """The builders pane: every builder's cell in a Grid of `shape(n, room(size, kept))`."""
    if not isinstance(builders, tuple):
        raise TypeError(f"builders must be a tuple, got {type(builders).__name__}")
    r = room(size, kept)
    if not builders:
        return Block((Paragraph(EMPTY, role="muted"),), title="builders", kind="pane",
                     id=KEY + ("builders",))
    c, rs = shape(len(builders), r)
    return Block(tuple(cell(b) for b in builders), title="builders", kind="pane",
                 layout=Grid((Fill(1),) * c, (Fill(1),) * rs), id=KEY + ("builders",))


# --- private ------------------------------------------------------------------------

def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _pair(value: object, name: str) -> None:
    """TypeError unless `value` is None or a tuple of two ints."""
    if value is not None and not (isinstance(value, tuple) and len(value) == 2
                                  and all(_is_int(v) for v in value)):
        raise TypeError(f"{name} must be None or a tuple of two ints, got {type(value).__name__}")


def _nonneg(value: "tuple | None", name: str) -> None:
    if value is not None and min(value) < 0:
        raise ValueError(f"{name} values must be >= 0, got {value}")


def _kept(kept: object) -> None:
    if kept is not None and not isinstance(kept, SplitTree):
        raise TypeError(f"kept must be None or a SplitTree, got {type(kept).__name__}")
