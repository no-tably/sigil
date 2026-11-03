"""[Block]: titled box: border set, title placement, surface level, focus pop.

Kind: service (a frozen dataclass node kind, see the Widgets package's protocol).

What it does: a box around its children: a ground at its own surface level, a border
in one of the charset's weights (its four edges runs a theme may pattern by the
Block's `kind`: The edges, below), an optional title on the top border, padding inside.
It is a surface (`surface=True`: Theme's `enter` gives it and its children the next
ground level) and a pane: when it holds the focus it lifts (its ground and its
subtree's grounds one level up), its border comes up from receded to full and turns
to its `focus_border` weight, so the focus pane reads with colour off.

Data (frozen dataclass; checked on construction):
- `Block(children=(), *, title="", title_at="left", border="rounded",
  focus_border="heavy", kind="block", padding=0, focused=None, layout=None, id=None,
  size=None, anchor=None, scope=None, surface=True)`:
  - `children`: a tuple of child nodes (a list is refused: pass a tuple).
  - `title`: styled text (a `str` or a Text {Line}; span style `None` is the role
    `title`); `""` for none.
  - `title_at`: `"left"`, `"centre"` (or `"center"`) or `"right"`: where the title
    sits in its title rect.
  - `border`: a weight of the charset's borders (`"light"`, `"heavy"`, `"double"`,
    `"rounded"`, `"dashed"`, `"dotted"`, `"heavy-dashed"`, `"ascii"`) or `None` (no
    border).
  - `focus_border`: the weight drawn while the Block is the focus pane, or `None` to
    keep `border`'s. Ignored when `border` is `None`.
  - `kind`: what sort of box this is, the name its edge patterns go by (R3b: the
    runs `frame.<kind>.<edge>`, edges `top`, `bottom`, `left`, `right`, below);
    `"block"` by default, `"pane"` for a tab's tiled pane, `"dialog"` for
    an overlay, or any other the app names. A free `str` of one lowercase
    word: exactly the strings `re.fullmatch(KIND, kind)` accepts, the module
    constant `KIND == "[a-z][a-z0-9_]*"` (ASCII only: no dot, space, hyphen or
    capital, not empty), so it is always one whole token segment between `frame.`
    and `.<edge>` and never clashes with a weight-qualified token
    (`frame.pane.heavy.top`); a later round may widen it, never narrow it. It sits after the two weights, with them the box's look, before
    the spacing and state fields. It is read by the border alone (The edges, below):
    it names the runs the four edges ask the context for, and nothing else (chrome,
    measure, lifts, hits) reads it (the laws `kind-inert` and `layout-unchanged`).
  - `padding`: an int or a tuple of 1 to 4 ints, every one >= 0 (CSS order).
  - `focused`: `None` (ask the context, below), `True` or `False` (the app's own
    word for whether this Block is the focus pane).
  - `layout`: the children's arrangement, a Layout value (opaque).
  - `id`, `size`, `anchor`, `scope`, `surface`: as the protocol states.
- Class attribute `pane = True`: what `lifts` looks for in a subtree. (`pane` is
  a class attribute every Block has, whatever its `kind`; `kind="pane"` is a value
  Views gives its tiled panes. They are not the same thing: a Block of kind
  `"block"` or `"dialog"` is still a focus pane for `lifts`.)
- Equality and hash: the dataclass's own, field by field, `kind` included:
  `Block(kind="pane") != Block()`, and two Blocks equal but for `kind` may hash
  apart. `repr` shows it.

The focus pane (`lifts(ctx) -> bool`): `focused` when it is not `None`; else true
exactly when `ctx.focus` is not `None` and is either this Block's `id` or the `id` of
a node in its subtree (followed through each node's `children`, read with `getattr`,
default `()`) reached without passing through a node whose class has `pane = True`
(a nested Block or Overlay: the focus pane is the NEAREST pane around the focused
node; the nested pane's own `id` counts as inside it). Paint gives a lifting Block's
children `lift=True`.

The geometry (`chrome()`, exactly Layout's BoxModel for that box): with `b = 1` when
`border` is not `None` else `0`, `chrome() == {"border": b, "padding": padding,
"title": title != "", "title_inset": 1}` (an empty Line counts as no title). At `rect`
`R`:
- the border is drawn on `R`'s outer cells when `b == 1` and `R.w >= 2` and
  `R.h >= 2` (a border too small to close is not drawn at all, nor its title);
- the title rect `T`: with a border, `Rect(x0, R.y, max(0, x1 - x0), 1)` with `x0 =
  R.x + max(2, ws + 1)` and `x1 = R.right - max(2, we + 1)`, `ws` and `we` the widths
  of the top run's start and end AS LAID (The edges, below; both 1 with no top
  pattern), so with no pattern `T == Rect(R.x + 2, R.y, max(0, R.w - 4), 1)` exactly
  as before R3b (the top border row, one corner cell and one inset cell kept each
  side), and with a start or end wider than the corner the title moves in past it,
  keeping one inset cell; with none, the first row, `Rect(R.x + 1, R.y, max(0, R.w -
  2), 1)` (when `R.h >= 1`; no run is asked);
- the content rect (where Paint lays the children) is BoxModel's `content`: the
  chrome is the same with and without patterns (vertical edges are one cell per row,
  checked at theme load; the top and bottom edges one row), so a theme's patterns
  never move the inside.

The edges (R3b, refine round 7: every repeated run a widget draws asks `ctx.run`,
never `glyph * n`). When the border is drawn (`b == 1`, `R.w >= 2`, `R.h >= 2`), with
`w` the weight it draws at (`focus_border` when `f` and `focus_border`, else
`border`), `k` the `kind`, `gl(part) = ctx.glyph(f"border.{w}.{part}")`, `bs =
ctx.border(f)` (receded at rest, full on focus: today's border style) and
`run(edge, n, base) = ctx.run(f"frame.{k}.{edge}", n, base, weight=w, style=bs,
focused=f)` (Context's run op, R3a: the weight-qualified run `frame.<k>.<w>.<edge>`
first, else the plain one, else the base; a part with no role, and every base cell, in
`bs`; a part with role `r` in `r.focus` when `f`, else `r`), the four edges OWN these
cells of `R`'s outer ring, which they partition (no cell in two edges, none outside the
ring):
- top: `run("top", R.w, (gl("tl"), gl("h"), gl("tr")))`, cell `i` at `(R.x + i,
  R.y)`: the whole top row, both corners included (the corners are the run's start
  and end: a pattern's start REPLACES the top-left corner);
- bottom: `run("bottom", R.w, (gl("bl"), gl("h"), gl("br")))`, cell `i` at `(R.x + i,
  R.bottom - 1)`: the whole bottom row, corners included (construct's pane foot, `▙`
  `─┴─` `///`, is start, fill and end of this run: `▙` in the bottom-left corner's
  cell);
- left: `run("left", R.h - 2, gl("v"))`, cell `i` at `(R.x, R.y +
  1 + i)`: the rows strictly between the corners (`R.h - 2` cells; none when `R.h ==
  2`), so a vertical pattern's start sits in the cell just under the top-left corner
  and its end just above the bottom-left one; the base is the one glyph `gl("v")`, a run
  with no ends (R1r: `Base(None, v, None)`), so a fill-only side pattern fills every
  row between the corners;
- right: `run("right", R.h - 2, gl("v"))`, cell `i` at
  `(R.right - 1, R.y + 1 + i)`, likewise.
Each run is laid along the whole edge of `rect` (its `n` from `R`, never from the
clip), and only its cells inside `area` (the clip within the grid) are written, so a
Block scrolled or clipped part way shows the same pattern cells where they are (the
protocol's `moved` law). A horizontal run is written as one Line at `(R.x, row)`, its
spans the run's cells in order (a wide cluster's `""` tail adds no text: the head
covers it), through `put(..., within=area)` (Buffer's rule for a pair cut by the area
edge: a blank in the pair's style); a vertical run's cell `i` is one one-cell glyph
put at its row. The degenerate sizes are today's: with `border=None`, or `R.w < 2` or
`R.h < 2`, no run is asked and no edge cell drawn (nor the bordered title). With no
pattern for the kind in the context's charset (and under the ascii base, every
pattern holding a non-ASCII cell is already dropped at theme load), the runs are
`tl + h * (R.w - 2) + tr`, `bl + h * (R.w - 2) + br` and `v` down each side, all in
`bs`: today's border, cell for cell (base_unchanged).

The start and end AS LAID (`ws`, `we`, for the title rect): `ws` is the number of
leading cells of the top run that the run's pattern's START drew, read from
`ctx.parts(f"frame.{k}.top", R.w, (tl, h, tr), weight=w)` (R3a's addendum: the cells
`lay_parts` tags `"start"`, a wide cluster's tail included), or 1 when there are none
(the top-left cell is the base corner: no start given, the ends fell back because
the run is too short, or no pattern); `we` likewise, the trailing cells tagged
`"end"`, or 1. (Block reads `ctx.parts`, never re-derives it.) Equivalently, by [Pattern]'s fits law (rule 1 is the only rule that
lays a start or an end), with `P = ctx.charset.pattern(f"frame.{k}.top", w)`, `sP =
sum(width(c) for c in P.start)` (1 when `P.start == ()`) and `eP` likewise over
`P.end`: `(ws, we) = (sP, eP)` when `sP + eP <= R.w`, else `(1, 1)`. A start given
but one cell wide gives `ws == 1`, so the title rect moves only past a start (or
end) wider than the corner, as round 7 states.

Painting (`paint(rect, ctx, grid, clip=None) -> tuple[Hit, ...]`), with
`f = lifts(ctx)` and `g = ctx.ground(focused=f)`:
1. Every cell of the clip: `Cell(" ", 1, g.style)`.
2. The border, when drawn: the four edge runs (The edges, above), in the order top,
   bottom, left, right, each cell its run's glyph in its run's style.
3. The title, when not empty and `T.w > 0` (and, with a border, the border drawn):
   - with a border, the label is `" " + title + " "` when `T.w >= width(title) + 2`,
     else `" " + cut(title, T.w - 2, ellipsis=ctx.glyph("ellipsis")) + " "` when
     `T.w >= 3`, else nothing is drawn (the top run stays whole). The label is
     aligned in `T` by `title_at` (Text's `align`) and written over the top run's
     cells (its two spaces in `bs`, never a part role; its text the `title` role);
     every top-run cell outside the label keeps the glyph and the style the run gave
     it (the extra cells of `T` included: the pattern runs under and around the
     title). A wide fill cluster the label's edge cuts in half leaves its other half
     a blank in the pair's style (Buffer's no_orphan_half); a start or end cell is
     never cut (law `title-around`);
   - with none, the title (cut to `T.w` with the ellipsis when wider) aligned in `T`
     by `title_at`, in the `title` role, the rest of `T` ground.
4. `shade(grid, clip, bg=g.style.bg)`.
Hits: `(Hit(clip, id),)` when `id` is not `None` and the clip is not empty, else
`()`. Children are not painted here.

Measuring (`measure(axis, room, ctx, content=0) -> int`), with `(pt, pr, pb, pl)` the
padding and `tw = width(title)`:
- `"x"`: `max(content + pl + pr + 2 * b, need)`, `need` being `tw + 6` with a border
  and a title (so the label fits whole), `tw + 2` with a title and no border, else 0.
- `"y"`: `content + pt + pb + 2 * b`, plus 1 for a title with no border.
Measuring reads no pattern (R3b's decision: layout never moves under a theme): with
a top pattern whose laid start or end is wider than one cell, the title rect is
`(ws - 1) + (we - 1)` cells narrower than `need` allows for, so at the natural width
such a title is cut, with the ellipsis (never silently). The protocol's `fits` law
holds for every theme whose top runs' starts and ends are one cell each (the builtin,
`light`, `contrast`); for a wider one it holds for the content and the chrome, the
title's last cells excepted (`wire` since refine round 13: its top start `▛▀` is two
cells, so `Block(title="Title")` at its natural width 11 draws `"▛▀━ Tit… ━┑"`).

Exact cells (the builtin theme, `ctx = Context.of(builtin(), level=1)`, styles named
by role; every style below also carries the ground's `bg` where it has none):
- `Block(title="Title", id="b")` at `Rect(0, 0, 11, 3)`: rows `"╭─ Title ─╮"`,
  `"│         │"`, `"╰─────────╯"`; the corners, lines and the title's two spaces in
  `ctx.border(False)`, `"Title"` in `ctx.style("title")`, the inside blanks in
  `ctx.ground().style`; hits `(Hit(Rect(0, 0, 11, 3), "b"),)`.
- The same with `ctx.focus == "b"` (or `focused=True`): `"┏━ Title ━┓"`,
  `"┃         ┃"`, `"┗━━━━━━━━━┛"` in `ctx.border(True)`, ground
  `ctx.ground(focused=True)` (one level up: `surface.sub`).
- Width 10: `"╭─ Tit… ─╮"`. Width 13, `title_at="right"`: `"╭─── Title ─╮"`.
- With a pattern (a theme giving kind `block` R4's first `wire` glyphs, before refine
  round 13 redrew them: `frame.block.top` start `┏` fill `━` end
  `┓`; `frame.block.bottom` start `▙` fill `─┴─` end `///`, `end.role: accent`;
  `frame.block.left` / `.right` fill `┃`), `Block(title="Title")` at `Rect(0, 0, 13,
  4)`: rows `"┏━ Title ━━━┓"`, `"┃           ┃"`, `"┃           ┃"`,
  `"▙─┴──┴──┴─///"` (`ws == we == 1`: `T` is the pre-R3b rect; the bottom fill `─┴─`
  cut to the 9 cells between `▙` and `///`); `///` in `ctx.style("accent")`, every
  other edge cell in `ctx.border(False)`. A top start `"┏━"` (two one-cell clusters)
  at the same rect gives `ws == 2`, `T == Rect(3, 0, 8, 1)`, top row `"┏━━ Title
  ━━┓"`. At width 3 the bottom run is too short for `▙` + `///` (4 cells): both ends
  fall back to the base corners with the pattern's fill cut to one cell: `"╰─╯"`.
- `Block(border=None, title="Log")` at `Rect(0, 0, 6, 2)`: rows `" Log  "` and
  `"      "`; `chrome()` is `{"border": 0, "padding": 0, "title": True,
  "title_inset": 1}`, so the content starts on row 1.
- At `Rect(0, 0, 1, 3)` a bordered Block draws only its ground.

Laws (R2, as R3b keeps them, and R3b's; a test can loop over kinds, fields, rects,
contexts, clips, themes with and without `frame` patterns, both ascii modes, every
weight and both focus states). "Unpatterned for `q`" means the context's charset
holds no run named `frame.<q>.<edge>` or `frame.<q>.<weight>.<edge>` (no key of
`ctx.charset.patterns` starts `f"frame.{q}."`): true of every kind under a charset
with `patterns == {}` (the builtin, every theme before R3).
- base_unchanged (73c003c): for every Block unpatterned for its kind, every chrome,
  measure, lifts and paint (cells and hits) equals that of commit 73c003c's Block
  built from the same fields (`kind` included), under the same context. The proof
  loads that commit's `cure/draw` (and the Core it imports) through
  `tests/_gitref.py`'s `extract` at test time, never a frozen copy, and is skipped
  without git history.
- kind-inert (R2's, kept where it still applies): for every valid `kind` `q` and every
  other field set `F`, with `a = Block(**F, kind=q)` and `z = Block(**F)` (kind
  `"block"`): `a.chrome() == z.chrome()`, `a.measure(...) == z.measure(...)` and
  `a.lifts(ctx) == z.lifts(ctx)` always; and, when the context is unpatterned for
  both `q` and `"block"`, `a.paint(rect, ctx, g1, clip)` leaves `g1` cell for cell
  equal to `z.paint(rect, ctx, g2, clip)`'s `g2` (from equal grids) with the same
  hits.
- edges-fit: before the title is written (a Block with `title=""`), each edge's
  cells inside `area` are exactly its run's: the cell at the edge's position `i` (The
  edges) holds the run's glyph `i` (a `""` tail as the pair's tail cell) and the
  run's style `i` with the ground's `bg` where it has none (step 4's shade); the top
  and bottom runs have exactly `R.w` cells, the left and right exactly `R.h - 2`; and
  every cell inside the ring is the ground, as with no pattern (the runs write no
  cell outside the ring).
- title-around: with a border and a title drawn, the label lies inside `T`, so the
  top run's start cells `R.x .. R.x + ws - 1`, end cells `R.right - we .. R.right -
  1` and the inset cell next to each are never overwritten; every top-run cell the
  label does not cover keeps its glyph and style. With no top pattern `ws == we == 1`
  and `T` is the pre-R3b rect.
- layout-unchanged: `chrome()`, `measure(axis, room, ctx, content)` and `lifts(ctx)`
  read no pattern: each equals its value under the same context with its charset's
  patterns removed (`replace(ctx, charset=replace(cs, patterns={},
  part_roles={}))`), so Layout gives the content, and so every child, the same rect
  with and without a theme's patterns.
- ascii (carried from Theme's ascii_drop): under an ascii charset every edge glyph is
  ASCII or one of the weight's own border glyphs.

Errors: construction: `TypeError` when `children` is not a tuple, `title` is neither
  a `str` nor a `Line`, `border` / `focus_border` is neither `None` nor a `str`,
  `kind` is not a `str` (`"kind must be a str, got int"`), `padding` is not an int
  or a tuple of ints (a `bool` refused), `focused` is not `None` or a `bool`,
  `surface` is not a `bool`, or `id` is unhashable; `ValueError` when `border` /
  `focus_border` is not one of the weights, `title_at` is not one of its values,
  `kind` does not match `KIND` (`"kind must be one lowercase word, like
  'pane' or 'dialog', got 'Pane'"`; `""` included), or `padding` has a
  negative side or other than 1 to 4 sides. The checks run in field order (the
  box's shared check: `title`, `title_at`, `border`, `focus_border`, then `kind`,
  each its TypeError before its ValueError, then `padding`, `focused`; then
  `surface` and `id` as before), so the first bad field's error is the one raised; the
  kind's check sits in the shared box check, so an Overlay raises the same.
  `measure` and `paint`: as the protocol states.
Effects: none, apart from `paint`'s writes into the grid it is given.
"""

import re
from collections.abc import Hashable
from dataclasses import KW_ONLY, dataclass
from itertools import groupby
from operator import itemgetter
from typing import ClassVar

from cure.core.buffer import Grid, fill, put, shade, write
from cure.core.geometry import Hit, Rect
from cure.core.text import Cell, Line, Span, cut, width

WEIGHTS = ("light", "heavy", "double", "rounded", "dashed", "dotted", "heavy-dashed", "ascii")
"""The border weights a Block may name (the charset's borders)."""

PLACES = ("left", "centre", "center", "right")
"""Where a title sits in its title rect."""

KIND = "[a-z][a-z0-9_]*"
"""The kinds a Block may name: one lowercase word (`re.fullmatch(KIND, kind)`)."""


def _check_common(node: object) -> None:
    """The protocol's common fields: `id` hashable, `surface` a bool."""
    if not isinstance(node.surface, bool):
        raise TypeError(f"surface must be a bool, got {type(node.surface).__name__}")
    if not isinstance(node.id, Hashable):
        raise TypeError(f"id must be hashable, got {type(node.id).__name__}")
    hash(node.id)


def _check_padding(padding: object) -> None:
    """An int or a tuple of 1 to 4 ints, each >= 0."""
    sides = padding if isinstance(padding, tuple) else (padding,)
    for side in sides:
        if not isinstance(side, int) or isinstance(side, bool):
            raise TypeError(f"padding must be an int or a tuple of ints, got {padding!r}")
        if side < 0:
            raise ValueError(f"padding must be >= 0, got {padding!r}")
    if not 1 <= len(sides) <= 4:
        raise ValueError(f"padding takes 1 to 4 sides, got {len(sides)}")


def _check_box(title: object, title_at: str, border: object, focus_border: object,
              kind: object, padding: object, focused: object) -> None:
    """The fields a Block and an Overlay share (see Errors)."""
    if not isinstance(title, (str, Line)):
        raise TypeError(f"title must be a str or a Line, got {type(title).__name__}")
    if title_at not in PLACES:
        raise ValueError(f"title_at must be one of {PLACES}, got {title_at!r}")
    for name, weight in (("border", border), ("focus_border", focus_border)):
        if weight is not None and not isinstance(weight, str):
            raise TypeError(f"{name} must be None or a str, got {type(weight).__name__}")
        if weight is not None and weight not in WEIGHTS:
            raise ValueError(f"{name} must be one of {WEIGHTS}, got {weight!r}")
    if not isinstance(kind, str):
        raise TypeError(f"kind must be a str, got {type(kind).__name__}")
    if re.fullmatch(KIND, kind) is None:
        raise ValueError(f"kind must be one lowercase word, like 'pane' or 'dialog', "
                         f"got {kind!r}")
    _check_padding(padding)
    if focused is not None and not isinstance(focused, bool):
        raise TypeError(f"focused must be None or a bool, got {type(focused).__name__}")


# -- the family's private drawing helpers (Containers may not share Readouts' own) --

def _check_measure(axis: object, room: object, content: object) -> None:
    """measure's stated errors: the axis, then `room` and `content` (ints >= 0)."""
    if axis not in ("x", "y"):
        raise ValueError(f"axis must be 'x' or 'y', got {axis!r}")
    for name, value in (("room", room), ("content", content)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{name} must be an int, got {type(value).__name__}")
        if value < 0:
            raise ValueError(f"{name} must be >= 0, got {value}")


def _begin(rect: object, grid: object, clip: object) -> "tuple[Rect, Rect] | None":
    """paint's stated errors; `(clip, area)` (area: the clip inside the grid), or None
    for an empty clip (nothing is written)."""
    if not isinstance(rect, Rect):
        raise TypeError(f"rect must be a Rect, got {type(rect).__name__}")
    if not isinstance(grid, Grid):
        raise TypeError(f"grid must be a Grid, got {type(grid).__name__}")
    if clip is None:
        clip = rect
    elif not isinstance(clip, Rect):
        raise TypeError(f"clip must be a Rect or None, got {type(clip).__name__}")
    if clip.empty:
        return None
    if clip.intersect(rect) != clip:
        raise ValueError(f"clip {clip} does not lie inside rect {rect}")
    return clip, clip.intersect(Rect(0, 0, grid.w, grid.h))


def _ground(grid: Grid, area: Rect, style: object) -> None:
    """Every cell of `area` becomes a blank in `style` (the recipe's step 1)."""
    if not area.empty:
        fill(grid, area, Cell(" ", 1, style))


def _shade(grid: Grid, area: Rect, style: object) -> None:
    """The recipe's last step: the ground's bg under every written cell without one."""
    bg = getattr(style, "bg", None)
    if bg is not None and not area.empty:
        shade(grid, area, bg=bg)


def _styled(text: "str | Line", ctx: object, role: str) -> Line:
    """Styled text with its spans' styles resolved: None is `role`, a str a theme role,
    a Style as given."""
    if isinstance(text, str):
        return Line((Span(text, ctx.style(role)),)) if text else Line()
    spans = []
    for span in text.spans:
        s = span.style
        if s is None:
            s = ctx.style(role)
        elif isinstance(s, str):
            s = ctx.style(s)
        spans.append(Span(span.text, s))
    return Line(tuple(spans))


def _plain(text: str, style: object) -> Line:
    return Line((Span(text, style),)) if text else Line()


def _join(*lines: Line) -> Line:
    return Line(tuple(span for line in lines for span in line.spans))


def _width(text: "str | Line") -> int:
    return width(text) if isinstance(text, str) else text.width


def _plain_of(text: "str | Line") -> str:
    return text if isinstance(text, str) else text.plain


def _put(grid: Grid, x: int, y: int, line: Line, area: Rect) -> None:
    """`line` at (x, y), only inside `area`."""
    if line.spans and area.y <= y < area.bottom and x < area.right:
        put(grid, x, y, line, within=area)


def _restyle(grid: Grid, x0: int, x1: int, y: int, area: Rect, how) -> None:
    """Row `y`'s cells in columns [x0, x1) inside `area` take `how(style)`."""
    lo, hi = max(x0, area.x), min(x1, area.right)
    if not (area.y <= y < area.bottom) or lo >= hi:
        return
    row = grid.row(y)
    if row[lo].width == 0 and lo > area.x:
        lo -= 1
    if row[hi - 1].width == 2 and hi < area.right:
        hi += 1
    cells = [Cell(c.glyph, c.width, how(c.style)) for c in row[lo:hi]]
    write(grid, lo, y, cells, within=area)


def _hit(r: Rect, clip: Rect, tag: object) -> "Hit | None":
    """`Hit(r ∩ clip, tag)`, or None when that is empty."""
    v = r.intersect(clip)
    return None if v.empty else Hit(v, tag)


def _sides(padding: "int | tuple") -> "tuple[int, int, int, int]":
    """The padding's (top, right, bottom, left), CSS order."""
    p = padding if isinstance(padding, tuple) else (padding,)
    if len(p) == 1:
        return p * 4
    if len(p) == 2:
        return p[0], p[1], p[0], p[1]
    if len(p) == 3:
        return p[0], p[1], p[2], p[1]
    return p


def _offset(extra: int, at: str) -> int:
    """Where a piece `extra` cells narrower than its field starts, by `at`."""
    if extra <= 0 or at == "left":
        return 0
    return extra if at == "right" else extra // 2


def _in_pane(nodes: object, focus: object) -> bool:
    """Whether `focus` is the id of a node under `nodes`, not crossing a nested pane."""
    stack = list(nodes)
    while stack:
        node = stack.pop()
        if getattr(type(node), "pane", False):
            continue
        if getattr(node, "id", None) == focus:
            return True
        stack.extend(getattr(node, "children", ()) or ())
    return False


@dataclass(frozen=True)
class Block:
    """A titled box around its children (see the module)."""

    children: tuple = ()
    _: KW_ONLY
    title: "str | Line" = ""
    title_at: str = "left"
    border: "str | None" = "rounded"
    focus_border: "str | None" = "heavy"
    kind: str = "block"
    padding: "int | tuple" = 0
    focused: "bool | None" = None
    layout: object = None
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = True

    pane: ClassVar[bool] = True

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        if not isinstance(self.children, tuple):
            raise TypeError(f"children must be a tuple, got {type(self.children).__name__}")
        _check_box(self.title, self.title_at, self.border, self.focus_border, self.kind,
                  self.padding, self.focused)
        _check_common(self)

    def chrome(self) -> dict:
        """The Layout `Box` keyword arguments of the border, title and padding."""
        return {"border": 1 if self.border is not None else 0, "padding": self.padding,
                "title": _plain_of(self.title) != "",
                "title_inset": 1}

    def lifts(self, ctx: object) -> bool:
        """Whether this Block is the focus pane (see the module)."""
        if self.focused is not None:
            return self.focused
        focus = ctx.focus
        if focus is None:
            return False
        return self.id == focus or _in_pane(self.children, focus)

    def measure(self, axis: str, room: int, ctx: object, content: int = 0) -> int:
        """The natural size along `axis`, chrome included (see the module)."""
        _check_measure(axis, room, content)
        b = 1 if self.border is not None else 0
        pt, pr, pb, pl = _sides(self.padding)
        titled = self.chrome()["title"]
        tw = _width(self.title)
        if axis == "x":
            need = (tw + 6 if b else tw + 2) if titled else 0
            return max(content + pl + pr + 2 * b, need)
        return content + pt + pb + 2 * b + (1 if titled and not b else 0)

    def paint(self, rect: Rect, ctx: object, grid: Grid, clip: "Rect | None" = None
              ) -> "tuple[Hit, ...]":
        """The ground, border and title into `grid` inside `clip` (see the module)."""
        begun = _begin(rect, grid, clip)
        if begun is None:
            return ()
        clip, area = begun
        f = self.lifts(ctx)
        g = ctx.ground(focused=f)
        _ground(grid, area, g.style)
        R = rect
        if self.border is not None:
            if R.w >= 2 and R.h >= 2:
                self._border(R, ctx, grid, area, f)
        elif R.h >= 1 and self.chrome()["title"]:
            T = Rect(R.x + 1, R.y, max(0, R.w - 2), 1)
            if T.w > 0:
                title = _styled(self.title, ctx, "title")
                if title.width > T.w:
                    title = cut(title, T.w, ellipsis=ctx.glyph("ellipsis"))
                _put(grid, T.x + _offset(T.w - title.width, self.title_at), T.y, title, area)
        _shade(grid, area, g.style)
        return () if self.id is None else (Hit(clip, self.id),)

    def _border(self, R: Rect, ctx: object, grid: Grid, area: Rect, f: bool) -> None:
        """The four edge runs on R's outer cells, then the title on its top row."""
        w = self.focus_border if f and self.focus_border else self.border
        bs = ctx.border(f)
        gl = lambda part: ctx.glyph(f"border.{w}.{part}")
        k = self.kind
        top_base = (gl("tl"), gl("h"), gl("tr"))
        run = lambda edge, n, base: ctx.run(f"frame.{k}.{edge}", n, base, weight=w,
                                            style=bs, focused=f)
        _put(grid, R.x, R.y, _run_line(run("top", R.w, top_base)), area)
        _put(grid, R.x, R.bottom - 1, _run_line(run("bottom", R.w, (gl("bl"), gl("h"),
                                                                    gl("br")))), area)
        v = gl("v")
        for x, cells in ((R.x, run("left", R.h - 2, v)), (R.right - 1, run("right", R.h - 2, v))):
            if not area.x <= x < area.right:
                continue
            rows = range(max(R.y + 1, area.y), min(R.bottom - 1, area.bottom))
            if cells and cells.count(cells[0]) == len(cells):   # one cell all down
                side = _plain(*cells[0])
                for y in rows:
                    _put(grid, x, y, side, area)
            else:
                for y in rows:
                    _put(grid, x, y, _plain(*cells[y - R.y - 1]), area)
        if not self.chrome()["title"]:
            return
        ws, we = _ends(ctx.parts(f"frame.{k}.top", R.w, top_base, weight=w))
        x0, x1 = R.x + max(2, ws + 1), R.right - max(2, we + 1)
        T = Rect(x0, R.y, max(0, x1 - x0), 1)
        if T.w <= 0:
            return
        title = _styled(self.title, ctx, "title")
        space = _plain(" ", bs)
        if T.w >= title.width + 2:
            label = _join(space, title, space)
        elif T.w >= 3:
            label = _join(space, cut(title, T.w - 2, ellipsis=ctx.glyph("ellipsis")), space)
        else:
            return
        _put(grid, T.x + _offset(T.w - label.width, self.title_at), T.y, label, area)


def _run_line(cells: tuple) -> Line:
    """A horizontal run's cells as one Line, a span per stretch of one style (a `""` tail
    adds no text: its head covers it)."""
    return Line(tuple(Span("".join(g for g, _ in group), s)
                      for s, group in groupby(cells, key=itemgetter(1))))


def _ends(parts: tuple) -> "tuple[int, int]":
    """(ws, we): the top run's leading cells tagged "start" and trailing ones tagged
    "end" (The start and end AS LAID), each 1 when there are none."""
    ws = 0
    for _, p in parts:
        if p != "start":
            break
        ws += 1
    we = 0
    for _, p in reversed(parts):
        if p != "end":
            break
        we += 1
    return ws or 1, we or 1
