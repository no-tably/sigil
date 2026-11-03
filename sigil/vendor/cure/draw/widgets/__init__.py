"""[Widgets]: the node kinds and their painters.

Kind: system (the expansion of [Widgets] in Draw); pure. Five families, each a package:
[Containers] (Block, Tabs, Disclosure, Overlay, Scrollbar), [Readouts] (Paragraph,
PropertyList, StatusBar, KeyHints, Legend, Toast, Progress, Chart), and W2's
[Collections], [Controls] and [Surfaces]. Each node kind measures, paints into its
rect from the {Context} it is given, and records its hit rects; none calls Canvas,
Graph or Theme, and no family imports another, Layout, Theme, Paint or Draw's
`context.py` (the import rule, `.construct/mapping.md`). So there is no shared base
class: each family defines its own node classes, every one satisfying the protocol
below by duck typing, and the {Context} reaches a widget as an argument read by
attribute.

This module holds the protocol only. W2 adds the families it builds and this
package's boundary op, `paint(node, rect, ctx, grid, clip=None) -> tuple[Hit, ...]`
(`[Paint] -> [Widgets] : paint({Node}) => {Cells}`, `[Painter] -> [Widgets] :
paint({Rect})`): `node.paint(rect, ctx, grid, clip)`, after checking that `node`
satisfies the protocol (a `TypeError` naming the missing attribute otherwise), plus
the re-export of every family's node classes.

The node protocol
-----------------

A node is a frozen dataclass, one class per kind (a family module may define several
kinds, e.g. Progress's `Bar`, `Gauge`, `Pulse`, `Spinner`). Its content fields come
first (positional), then, keyword only (`dataclasses.KW_ONLY`), the common fields
every kind declares itself:

- `id`: any hashable value or `None` (the default): the node's tag in the {HitMap}
  and the value `ctx.focus` / `ctx.hover` name it by. A node with `id=None` records
  no hit of its own and is never focused or hovered through the context.
- `size`: the node's constraint along its parent's main axis, a Layout [Solver]
  value (`Fixed(1)`, `Auto()`, `Fill(2)` ...) or `None` (the default, which Layout
  reads as `Fill(1)`). Held opaque: a widget never looks at it (the app composes the
  tree and imports Layout; a widget may not).
- `anchor`: a Layout [Anchor] `At` or `None` (the default: in the flow). A node with
  an anchor floats over its parent's content rect (Layout places it). Held opaque.
- `scope`: a Theme `Scope` or `None` (the default): read by Theme's `enter`. Opaque.
- `surface`: a `bool`, read by Theme's `enter`: `True` makes the node take the next
  ground level (`ctx.level + 1`) for itself and its children. Each kind states its
  default (Block, Overlay and Toast `True`; every other kind `False`).

A container also has:
- `children`: the child nodes Layout lays out and Paint paints after it, a tuple
  (a field, or a property computed from the node's fields: Tabs gives only its active
  body, Disclosure its body only when open). A leaf has no `children` attribute
  (Layout's default `()`).
- `layout`: how the children are arranged, a Layout `Row`, `Column`, `Grid`, `Stack`
  or `Scaffold`, or `None` (Layout's `Column()`). Opaque. (Only Block has the field;
  the others hold at most one child, which takes the whole content rect.)

The methods:

- `chrome() -> dict | None`: the node's own insets, as the keyword arguments of
  Layout's BoxModel `Box` (`margin`, `border`, `padding`: an int or a tuple of 1 to 4
  ints, CSS order; `title`: a bool; `title_inset`: an int), or `None` for none (every
  leaf). A Block with a border and a title gives `{"border": 1, "padding": 0,
  "title": True, "title_inset": 1}`. A widget cannot build a `Box` (it may not import
  Layout), so Paint does: Layout reads each node's `box` attribute, and Paint lays
  the tree out with `box = Box(**node.chrome())` for every node whose `chrome()` is
  not `None` (no widget node has a `box` attribute of its own). The rects a
  container's `paint` draws its chrome in are exactly the BoxModel's for that box
  (each kind states them), so chrome and children never overlap.
- `measure(axis, room, ctx, content=0) -> int`: the natural size of the node along
  `axis` (`"x"`: width, `"y"`: height), chrome included, given `room` cells on the
  other axis; an `int >= 0`. Paint's measure, memoised there, is
  `lambda node, axis, room: node.measure(axis, room, ctx_of(node), content)`, where for
  a container `content` is the natural size along `axis` of its children as its
  layout arranges them, at `room` less the chrome on the other axis (Paint computes
  it, since only Paint knows Layout; `0` with no children). A leaf ignores
  `content`. It never paints and never reads a grid.
- `paint(rect, ctx, grid, clip=None) -> tuple[Hit, ...]`: draw the node into `grid`,
  a Buffer {Grid}, at `rect` (a Geometry {Rect}: where the node is, which may start
  off the grid or above the viewport when scrolled), writing only the cells of
  `clip` (default `rect`; Layout's clip, which lies inside `rect`) that lie inside
  the grid. `ctx` is the node's own context, already entered (Theme's `enter`: its
  scope and its surface level applied; Paint's `lift` and `zone` set). It returns
  the node's hit regions, each a Geometry `Hit(r, tag)` on layer 0 with `r` a
  non-empty rect inside `clip` (a region cut by the clip is recorded as its visible
  part; one wholly outside it is not recorded), in the order they were drawn. Paint
  adds them to the frame's {HitMap} on the layer the node paints on (an Overlay's
  `layer`, else 0), in screen space. A container paints only its own chrome and
  ground: Paint paints its children afterwards, into their own rects (parents
  before children).
- `lifts(ctx) -> bool` (containers; a node without it is taken as `False`): whether
  the node is the focus pane, whose ground and whose subtree's grounds are lifted
  one level: Paint gives the node's children `replace(child_ctx, lift=True)`.

How a widget paints (the recipe every kind follows, so the laws below hold):

1. Ground. With `g = ctx.ground(focused=...)` (`focused` true only for a node that
   lifts itself: a focused Block), every cell of the clip becomes `Cell(" ", 1,
   g.style)`. A widget owns every cell of its clip: nothing beneath shows through.
2. Content, by the kind's rules: text through Text's `wrap`, `cut` and `align`,
   then Buffer's `put` / `write` with `within=clip`. Glyphs come only from the
   charset (`ctx.glyph(token)`, `ctx.frame(...)`), styles only from theme roles
   (`ctx.style(role)`, `ctx.border(focused)`) and treatments (`ctx.apply(base,
   state)`), so colours keep their theme role. Overflow is never silent: a row cut
   on the right ends in `ctx.glyph("ellipsis")` (…), and rows past the rect become
   a last row `↓N more` (below).
3. Ground under the content: `shade(grid, clip, bg=g.style.bg)`: every written cell
   whose style has no background takes the ground's (a highlight's own background
   is kept: the first writer wins).

Styled text. Where a kind takes text (a title, a value, a paragraph), it is a `str`
or a Text {Line} (a Paragraph also a {Text}); a span's style is `None` (the kind's
own role for that text), a `str` (a theme role name: `ctx.style(name)`, so colours
keep their role) or a Style {Style} (used as given). A `str` is one span of style
`None`.

States. A widget learns its states from the context and its fields, never from what
was drawn:
- focused: `ctx.is_focused(x.id)` for the node or an item of it (an item has its own
  `id`), or the node's own `focused` field where a kind has one (`True` / `False`
  override the context; `None`, the default, asks it);
- hovered: `ctx.is_hovered(x.id)`;
- selected, active, pressed, emphasised, muted, disabled: the node's or the item's
  fields, as each kind states (an item's `state`, Tabs' `active` index ...).
Each state is applied additively, `ctx.apply(base, state)` (Theme [States]: a
highlight changes the background or the text colour, flags only turn on), over the
extent the treatment names: `row` over the item's whole row in the clip (cursor and
selection run the full row), `text` over the item's text cells only (emphasis covers
only its text). Several states stack in the order: the item's own state, hover,
focused. The mark (`ctx.treat(state).mark`) goes in the one cell the kind reserves
for it (a key:value row's last leader cell, a header's or a row's gutter), the first
non-empty one of focused, the item's state, hover; never over text.

Runs (R3b, refine round 7). Every repeated run a widget draws, a line of `n` cells
along one axis of one glyph per part (a frame's edge, a track, a bar's filled cells),
asks the context for its cells, `ctx.run(token, n, base, *, weight=None, style=None,
focused=False)` (Context's run op, R3a: the theme's pattern for `token` laid along
`n` cells, `base` the glyphs the widget would draw without one, `style` the run's
edge style), never `glyph * n` nor a hand-built `tl + h * (n - 2) + tr`. The run is
laid from the widget's `rect` (never from the clip, so `moved` holds) and its cells
written in order, each its own glyph and style; a widget reads `ctx.run` by attribute
(no family imports Theme). With no pattern for the token in the context's charset a
run is exactly `base` drawn as before, in `style` (base_unchanged: every frame of a
theme without patterns is commit 73c003c's). Who takes a run, and its tokens:
- Block and Overlay (Containers): the four edges, `frame.<kind>.top|bottom|left|right`
  at the weight drawn (Block's The edges);
- Scrollbar (Containers): the track, `run.scrollbar.track`, the thumb drawn over it;
- Bar and Gauge (Readouts, Progress): the full cells `run.progress.fill` and the empty
  ones `run.progress.track`, the partial eighth cell between them never a run;
- Paint's split gutters (not a widget, the same rule): `frame.gutter.x|y`.
Who does not (each a cell that carries meaning, a single cell, or a mark in time,
not a run a pattern could restyle):
- Tree's guides (Collections): per-row structure, where branch, last and stem mean
  something;
- Tabs' and KeyHints' separators: single cells;
- Canvas strokes (a Drawing's rows): Junctions own them, and they join at crossings;
- spinners (Progress's Spinner): frames in time, not runs; Pulse, whose block moves
  over a track split around it by the tick;
- PropertyList's and Button's dash leaders and Chart's bars: data-shaped fills (a
  leader's length is a key's slack, a bar's a value), outside round 7's list; they
  keep `glyph * n` until a round names them.
A new widget that draws a frame-like run takes a token under `run.<widget>.<part>`
and asks `ctx.run`; the list above is the whole of it until a refine round adds one.

The overflow row. `↓N more`: `ctx.glyph("more.down") + str(N) + " more"` in role
`muted`, cut to the row (no ellipsis: the arrow and the number go first). A kind that
cannot show all its rows in `rect.h` shows the first `rect.h - 1` and this row last,
N the rows not shown (so `rect.h == 1` shows only `↓N more`).

Laws (each a property a test can loop over nodes, rects, clips and contexts):
- contained: `paint` changes no cell outside `clip ∩ grid`, and writes into no grid
  but the one given.
- owned: after `paint`, every cell of `clip ∩ grid` is the same whatever the grid
  held there before (a widget reads nothing from the grid).
- pure: the same node, rect, clip and context give the same cells and the same hits;
  `measure` likewise. Neither reads a clock or any state of its own.
- hits: every returned hit's rect is non-empty and inside `clip`; its tag is the
  node's `id` or a tuple `(id, part, ...)` the kind names, and none is recorded when
  the node's `id` is `None` (an item's own non-`None` `id` is recorded as itself).
- moved: `paint(rect.moved(dx, dy), ...)` into a grid big enough draws the same cells
  moved by `(dx, dy)` (clip moved too) and the same hits moved.
- legible: with colour off (styles' colours ignored), every state a node or item is
  in still shows: its mark, where the kind reserves a mark cell, or its treatment's
  floor flag (bold, dim, underline) on the cells of its extent.
- fits (a leaf; a container's chrome likewise, with `content` its children's): for
  every `room >= 0`, with `w = measure("x", room, ctx)` and `h =
  measure("y", w, ctx)`, painting at `Rect(0, 0, w, h)` shows all of the node's
  content: no `↓N more` row and no ellipsis that the content itself does not hold
  (one stated exception, R3b: a Block's title under a top pattern whose laid start
  or end is wider than one cell may be cut by those extra cells, since measuring
  reads no pattern; Block's Measuring).
- measure: an `int >= 0`; `ValueError` for an `axis` other than `"x"` / `"y"` or a
  negative `room` or `content`; `TypeError` for a non-int `room` / `content` (a
  `bool` included).
- paint's errors: `TypeError` when `rect` or `clip` is not a Geometry `Rect` or
  `grid` is not a Buffer `Grid`; `ValueError` when a non-empty `clip` does not lie
  inside `rect` (an empty clip, wherever it is, is fine: nothing is written, `()` is
  returned). A node with a field of the wrong type is refused at construction (each
  kind's Errors), so `paint` and `measure` never fail on content.

Effects: none, apart from `paint`'s writes into the grid it is given.
"""

from .collections import List, ListRow, Table, TableColumn, TableRow, Tree, TreeNode
from .containers import Block, Disclosure, More, Overlay, Scrollbar, Tab, Tabs
from .controls import Button, Option, Select, TextInput
from .readouts import (Bar, Bars, Entry, Gauge, Hint, Item, KeyHints, Legend, Lines,
                       Paragraph, PropertyList, Pulse, Segment, Series, Sparkline,
                       Spinner, StatusBar, Toast)
from .surfaces import Drawing, Extent, Pane

PROTOCOL = ("paint", "measure", "chrome", "id", "size", "anchor", "scope", "surface")
"""The attributes `paint` checks a node for, in this order (`lifts` and `children` are
optional: Paint reads them with `getattr`)."""


def paint(node: object, rect: object, ctx: object, grid: object, clip: object = None
          ) -> "tuple":
    """[Widgets]' boundary op (`[Paint] -> [Widgets] : paint({Node}) => {Cells}`,
    `[Painter] -> [Widgets] : paint({Rect})`): paint one node into `grid`.

    Checks that `node` has every attribute of `PROTOCOL` (in that order; a
    `TypeError` naming the first one missing, e.g. "node lacks 'measure'"), then
    returns `node.paint(rect, ctx, grid, clip)` unchanged: the node's hits, a tuple
    of Geometry `Hit`, after its writes into `grid` (a Buffer {Grid}, the {Cells}).
    It adds nothing of its own: no ground, no hit, no clip of its own; the node's
    own errors (a `rect` that is not a `Rect`, a clip outside the rect ...) pass
    through as the protocol states. Any node of any family serves, and any other
    value with the protocol's attributes (duck typed: there is no base class).

    Usage:
        from cure.core.buffer import Grid, text
        from cure.core.geometry import Rect
        from cure.draw.context import Context
        from cure.draw.theme import builtin
        from cure.draw.widgets import Button, paint
        g = Grid(8, 1)
        paint(Button("OK", id="ok"), Rect(0, 0, 8, 1), Context.of(builtin()), g)
        # (Hit(Rect(0, 0, 7, 1), "ok"),); text(g) == " [ OK ]"
        paint(object(), Rect(0, 0, 8, 1), Context.of(builtin()), g)   # TypeError: node lacks 'paint'
    """
    for name in PROTOCOL:
        if not hasattr(node, name):
            raise TypeError(f"node lacks {name!r}")
    return node.paint(rect, ctx, grid, clip)
