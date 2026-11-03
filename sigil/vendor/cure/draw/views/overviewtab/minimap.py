"""[Minimap]: one block per component, builders lit, a click opens its sub-hierarchy.

Kind: service (pure functions from Board {Component}s and a {Charset} to a Graph {Dag}
and a widget node; see the OverviewTab package for the tab, its key `k ==
("overview",)` and its ids).

What it does: one cell per component, no scaling (construct's spec), through Graph's
Blocks (`[Minimap] -> [Graph] : grid({Order}) => {Blocks}`): the components are laid
out as their composition hierarchy, each level of it a row of blocks; a component a
builder holds is drawn lit (the charset's full block), one built and held by none is
drawn built (its medium block), the others unlit (its light block), so the three read
apart with colour off (M1, construct's ask: a finished board no longer looks unbuilt). Each block is a hit region naming its
component: the app opens its sub-hierarchy (an Inspector tab, or the next level).
The rows are runs of the charset's glyphs in theme roles, shown by a Widgets
`Drawing`; Paint paints them.

The hierarchy (`hierarchy(components) -> Dag`), for `components` a `tuple` of
{Component} (the Board's; keys `"System/Component"`, unique):
- nodes, in `components`' order: `Node(c.key)` (Graph's, one cell: Blocks gives
  each node one cell whatever its size);
- edges: `(p.key, c.key)` for each `p` in order and each `c` in order with `c.key !=
  p.key` and `c`'s system (its key before the `/`) equal to `p`'s component name
  (its key after the `/`): a component that is itself an expanded system (Views's
  `"Draw/Views"`) holds the components of that system (`"Views/OverviewTab"`, ...).
  A name shared by components of two systems gives both the edges; a cycle (two
  systems each naming the other) is broken by Graph ([Ranks]), never refused.
The blocks (`blocks(components) -> Blocks`): `grid(layout(hierarchy(components)).order)`
(Graph's `layout` and `grid`, laid down): row `r` holds the components at depth `r`
of the hierarchy (longest path from a top-level one), in Graph's order within it.

The rows (`rows(components, charset) -> Rows`): with `b = blocks(components)`,
`Rows.of` (Buffer's) of one row per `y` in `0 .. b.height - 1`, each the runs, for
`x` in `0 .. b.width - 1`, of the cell `(x, y)` then one blank `(" ", None)`. The
cell is `(charset.glyph("block.full"), "accent")` when it holds a component whose
`builder` is not `None` (lit), `(charset.glyph("block.medium"), "ok")` when it holds
one whose builder is `None` and whose `status` is `"built"` (built), `(charset.glyph(
"block.light"), "muted")` when it holds any other (unlit), and `(" ", None)` when it
holds none (`grid`
never puts two components in one cell). So component `c` is drawn at column `2 *
x`, row `y`, `(x, y) == b.at[c.key]`.

The pane (`minimap(components, charset, *, scroll=(0, 0)) -> Block`):
- with components: `Block((Drawing(rows(components, charset), x=scroll[0],
  y=scroll[1], regions=regions, id=k + ("minimap", "view")),), title="map", kind="pane",
  id=k + ("minimap",))`, `regions == tuple(Hit(Rect(2 * x, y, 1, 1), k + ("component",
  c.key)) for c in components)` with `(x, y) == b.at[c.key]` (Geometry's `Hit` and
  `Rect`), in `components`' order; Drawing's overflow marks on (a map wider than
  the pane ends in the ellipsis, never cut silently);
- with none: `Block((Paragraph(EMPTY, role="muted"),), title="map", kind="pane",
  id=k + ("minimap",))`, `EMPTY == "no components yet"`.

Laws (each a property a test can loop over component tuples, scrolls, sizes and
contexts):
- pure: equal arguments give equal results (`hierarchy`, `blocks`, `rows`,
  `minimap`).
- once: every component has exactly one block: `set(blocks(cs).at) == {c.key for c
  in cs}`, no cell holds two (Blocks' `grid` law), and the regions are one per
  component, each tag `k + ("component", c.key)`, its rect the block's cell.
- lit: the glyph at a component's cell is `charset.glyph("block.full")` if and
  only if its `builder` is not `None` (a builder is working); else
  `charset.glyph("block.medium")` if and only if its `status` is `"built"` (built);
  else `charset.glyph("block.light")` (unlit: neither). A builder wins over a status.
- hierarchy: a component's row is 0 when no other component's name is its system,
  and greater than every row of the components that hold it.
- ids: the node ids carried are exactly `{k + ("minimap",), k + ("minimap",
  "view")}` with components, `{k + ("minimap",)}` without.
- legible: with colour off (Caps depth 0), lit, built and unlit read apart by their
  glyphs (█, ▒ and ░; ASCII `#`, `%` and `:`), whenever the charset's three block
  glyphs differ, as the builtin bases' do.

Inputs: `components` a `tuple` of Board {Component}; `charset` a {Charset}
  (`glyph(token)`); `scroll` a `tuple` of two ints (any sign, Drawing's offset).
Outputs: a Graph {Dag}; Graph's `Blocks`; Buffer {Rows}; a Widgets `Block` (of a
  `Drawing`, or a `Paragraph`).
Errors: `TypeError` when `components` is not a `tuple`, `charset` has no callable
  `glyph` (`"charset must be a Charset (the frame's ctx.charset), got NoneType"`),
  or `scroll` is not a `tuple` of two ints (a `bool` refused). Graph's own errors
  cannot arise from a valid {Board} (keys are non-empty and unique; no edge is a
  self-loop).
Effects: none.

Usage:
    from cure.draw.theme.charset import ASCII, Charset
    from cure.draw.views.board import Component
    from cure.draw.views.overviewtab import minimap
    cs = (Component("Draw/Views"), Component("Views/OverviewTab", builder="b2"),
          Component("Views/Inspector"), Component("Draw/Graph"))
    minimap.hierarchy(cs).edges     # (("Draw/Views", "Views/OverviewTab"), ("Draw/Views", "Views/Inspector"))
    minimap.blocks(cs).height       # 2
    minimap.blocks(cs).at["Views/OverviewTab"]   # (0, 1)
    [l.plain for l in minimap.rows(cs, Charset("ascii", ASCII)).lines]   # [": : ", "# : "]
    done = (Component("Draw/Views", status="built"),) + cs[1:]
    [l.plain for l in minimap.rows(done, Charset("ascii", ASCII)).lines]  # ["% : ", "# : "]
"""

from cure.core.buffer import Rows
from cure.core.geometry import Hit, Rect
from cure.draw.graph import Blocks, Dag, Node, grid, layout
from cure.draw.widgets import Block, Drawing, Paragraph

KEY = ("overview",)
"""The tab's key (OverviewTab's `k`)."""

EMPTY = "no components yet"
"""What the pane says when the board has no components."""

LIT = ("block.full", "accent")
"""A lit block (a component a builder holds): the charset token and the theme role."""

UNLIT = ("block.light", "muted")
"""An unlit block (neither held nor built): the charset token and the theme role."""

BUILT = ("block.medium", "ok")
"""A built block (status `"built"`, no builder holding it): the charset token and the
theme role (M1)."""


def hierarchy(components: tuple) -> Dag:
    """The components as Graph's {Dag}: an edge from a system's component to its parts."""
    _components(components)
    names = [(c.key.partition("/")[0], c.key.partition("/")[2]) for c in components]
    edges = [(p.key, c.key) for p, (_, name) in zip(components, names)
             for c, (system, _) in zip(components, names)
             if c.key != p.key and system == name]
    return Dag([Node(c.key) for c in components], edges)


def blocks(components: tuple) -> Blocks:
    """One cell per component, no scaling: Graph's `grid` of the hierarchy's order."""
    return grid(layout(hierarchy(components)).order)


def rows(components: tuple, charset: object) -> Rows:
    """The map's rows: a lit, built or unlit block glyph per cell, a blank between cells."""
    _components(components)
    _charset(charset)
    return _rows(components, charset, blocks(components))


def minimap(components: tuple, charset: object, *, scroll: "tuple[int, int]" = (0, 0)) -> Block:
    """The minimap pane: the blocks in a scrolled Drawing, a hit region per component."""
    _components(components)
    _charset(charset)
    if not (isinstance(scroll, tuple) and len(scroll) == 2
            and all(isinstance(v, int) and not isinstance(v, bool) for v in scroll)):
        raise TypeError(f"scroll must be a tuple of two ints, got {type(scroll).__name__}")
    if not components:
        return Block((Paragraph(EMPTY, role="muted"),), title="map", kind="pane",
                     id=KEY + ("minimap",))
    b = blocks(components)
    regions = tuple(Hit(Rect(2 * b.at[c.key][0], b.at[c.key][1], 1, 1),
                        KEY + ("component", c.key)) for c in components)
    view = Drawing(_rows(components, charset, b), x=scroll[0], y=scroll[1], regions=regions,
                   id=KEY + ("minimap", "view"))
    return Block((view,), title="map", kind="pane", id=KEY + ("minimap",))


# --- private ------------------------------------------------------------------------

def _components(components: object) -> None:
    if not isinstance(components, tuple):
        raise TypeError(f"components must be a tuple, got {type(components).__name__}")


def _charset(charset: object) -> None:
    if not callable(getattr(charset, "glyph", None)):
        raise TypeError("charset must be a Charset (the frame's ctx.charset), got "
                        f"{type(charset).__name__}")


def _rows(components: tuple, charset: object, b: Blocks) -> Rows:
    """The rows of `b`'s cells (see `rows`)."""
    full, built, light = ((charset.glyph(t), role) for t, role in (LIT, BUILT, UNLIT))
    cell = {c.key: full if c.builder is not None else built if c.status == "built" else light
            for c in components}
    blank = (" ", None)
    out = []
    for y in range(b.height):
        runs = []
        for x in range(b.width):
            held = b.cells.get((x, y), ())
            runs.append(cell[held[0]] if held else blank)
            runs.append(blank)
        out.append(runs)
    return Rows.of(out)
