"""[Diagram]: the graph's entry: lay out, route, stroke.

Kind: service (two data classes and pure functions; the {Canvas} it returns is new and
the caller's).

What it does: one call from a {Dag} to a drawing. `paths(dag)` ({Dag} => {Paths}, on
[Route]) runs the layered pipeline, [Ranks], [Order], [Place] (`layout`), [Route], and
when the drawing is longer than `limit` on its layer axis, [Fold] and [Route] again;
`diagram(dag)` strokes the result onto a new Canvas {Canvas} (Canvas's `draw({Paths})
=> {Canvas}`, the hop rule on), draws each node as a box with its label (or the label
alone), and keeps each wire's cells (Canvas's `link({Path}) => {Masks}`) for hit tests
and highlights, and puts an ARROWHEAD on the cell where each wire meets its target
(README decision 9). `lay(dag, charset)` is Graph's boundary op (`[Views] -> [Graph] :
lay({Dag}) => {Laid}`, and DagView's): a `Laid`, the diagram's rows, Text `Line`s drawn
with the {Charset} given, heads on, and each real node's rect, from the one layout, so
a caller that hits nodes never lays the dag out again. Glyphs are never picked here: the canvas holds direction
masks and weights, and the charset turns them into box-drawing glyphs at `rows` (with
[Charset]'s `ASCII` base every weight draws `+ - |`, heavy and double `=` on
horizontal runs). The heads are the one glyph written at `diagram` time, as text, from
the charset passed as `arrows` (its `arrow.right` / `arrow.left` / `arrow.up` /
`arrow.down` tokens: ▶ ◀ ▲ ▼, ASCII `>` `<` `^` `v`), because a canvas holds no
tokens, only masks and text.

The input, a [Ranks] {Dag}: nodes with sizes in cells (the box a node is drawn in:
`sized` gives one fitting a label), edges `(u, v)` drawn from u (above, or left) to v.
Cycles are broken by [Ranks] (`acyclic`); the edges it reversed are drawn from their
head down to their tail in the `back` weight (dashed by default), every other edge in
`weight` (light). Self-loops are refused by `Dag` itself. Edges carry no labels; an
edge's direction is shown by its head (HEADS, below), on its target's side.

HEADS. Edge k, `e = dag.edges[k] = (u, v)`, has its target v; its wire (`w`, step 2
of `diagram`) runs from its oriented tail's out-port to its oriented head's in-port
([Route]). Its TARGET END is the wire's last point (the in-port of v) for an edge
[Ranks] kept, and its first point (the out-port of v) for one it reversed (in
`layers.reversed`: drawn from v down to u, so it meets v on v's far side). Its NEXT
point is the one beside the target end in `w.points` (the second last, or the
second); the segment between them runs along the layer axis ([Route]'s step 6).
- The HEAD CELL is the cell one step from the target end toward the next point: the
  last wire cell before v's rect (the target end is the port, on v's border when
  boxed, under its label when not). When that
  cell is the wire's other end (the wire is two adjacent cells, `len(masks[k].cells)
  == 2`: the boxes touch, as with `rank_gap=0` and a straight net), the edge has NO
  HEAD: the cell is the source's out-port (or in-port), its border's tee, and a head
  there would break the source's box and read as the source's own; the two tees that
  touch still show the edge. Otherwise, by [Route]'s no-wire-through-a-box law, the
  head cell lies in no real node's rect, in a channel (or on a lane cell, when the
  channel is empty).
- The TOKEN is the way the wire travels into v, from the head cell to the target
  end: `arrow.down` (▼) for a kept edge laid `"down"` (it enters v's top), `arrow.up`
  (▲) for a reversed one laid down (it enters v's bottom), `arrow.right` (▶) for a
  kept edge laid `"right"` (in at v's left), `arrow.left` (◀) for a reversed one laid
  right (in at v's right). No other token occurs: every wire meets its ends along the
  layer axis.
- Drawn with `arrows` given (a charset; None draws none): for each head cell, in
  order of the first edge (in edge order) whose head cell it is, `label(canvas, x, y,
  arrows.glyph(token), styles.get(e))`, `token` and `e` that first edge's. So:
  - a SHARED in-port (a fan-in, [Route]'s `k > L`) takes one head, on the shared
    cell, the first edge's; the others' heads (`heads[j]`) name the same cell;
  - the head is text, so it wins over every stroke at its cell (Canvas's
    text_wins): a corner where a bus turns into the port, a tee of a fan-in, a
    crossing (a hop) or a `joins` cell shows the head, and the strokes on either side
    keep their arms toward it; the joint stays under it (masks, Query and `hit`
    still see the wire);
  - a back edge has its head too, at v's far side, the same glyph (the arrows have
    no weights; `back` and `weights` set the wire's weight only); its style, like
    every head's, is its edge's `styles.get(e)`, as for its wire. When the head cell
    is on a trunk v's other out-edges share, the head is the reversed edge's (they
    have theirs at their own targets);
  - a 2-cycle's two edges (a BUNDLE: one wire, [Route]) take a head at each end: the
    kept one's into its target, the reversed one's into its own target, the other
    end. Two heads of different tokens meet on one cell only across a channel one
    cell long (a ▼ into the node below it and a ▲ into the node above it, as with
    `rank_gap=1`): the first edge's is drawn, as at any shared cell;
  - folded layouts: heads only at targets; the wire's points at a band boundary
    (exit lane, track, entry lane) and a long edge's virtual vertices take none;
  - an empty glyph (`""`) draws no head (the wire shows); a glyph wider than one cell
    (a theme's override) is written as it is, the theme's to answer for ([Charset]).

`sized(id, label=None, *, boxes=True) -> Node`: a node sized for its label (`id` when
`label` is None): `Node(id, w + 2, 3)` with boxes, `Node(id, w, 1)` without, `w = max(1,
width(label))` (Text's `width`, in cells).

`paths(dag, *, direction="down", limit=None, compact=False, sweeps=4, transpose=True,
gap=2, lane_gap=1, rank_gap=2, passes=4, fold_gap=2, inset=0, weight=WEIGHT,
back=BACK, previous=None) -> Paths`:
1. `c = layout(dag, compact=..., sweeps=..., transpose=..., direction=..., gap=...,
   lane_gap=..., rank_gap=..., passes=..., previous=prev)`, `prev` being `previous`
   when it is a {Coords}, `previous.layout` when it is a `Diagram`, else None (the last
   drawing kept still, [Place]);
2. `p = route(c, inset=inset, weight=weight, back=back)`;
3. EXTENT `ext(q)`: `q.height` when laid `"down"`, `q.width` when `"right"` (the layer
   axis). When `limit` is None or `ext(p) <= limit`, the result is `p`. Otherwise, with
   `n = limit`: `q = route(fold(p.coords, n, gap=fold_gap), inset=..., weight=...,
   back=...)`; the result is q when `ext(q) <= limit` or `n == 1`; else `n = max(1, n
   - (ext(q) - limit))` and again. (n falls each time, so it ends; the wires between
   bands and the margins they need are what the fold limit gives up.)
`limit` folds the layer axis only (rows when down, columns when right); a drawing too
wide across is the caller's to scroll (Paint's viewport).

`diagram(dag, *, <every keyword of paths but inset>, boxes=True, box="light",
labels=None, styles=None, weights=None, ellipsis="", arrows=None) -> Diagram`:
1. `p = paths(dag, ..., inset=1 if boxes else 0)` (ports kept off box corners).
2. The wires: for edge k, `e = dag.edges[k]` (as given), `Path(p.paths[k].points,
   weights.get(e, p.paths[k].weight), styles.get(e))`; `canvas = draw(wires)`
   (Canvas's `draw`: each stroked in edge order, a straight run hopping a straight
   line it crosses); `masks = tuple(link(w) for w in wires)` (no hops).
3. The boxes: for each real node in node order, with `r = p.rects[id]`, BOXED when
   `boxes` and `r.w >= 3` and `r.h >= 3`: its outline stroked, `Path([(r.x, r.y),
   (r.right - 1, r.y), (r.right - 1, r.bottom - 1), (r.x, r.bottom - 1), (r.x, r.y)],
   box, styles.get(id))`, after every wire, so a port's wire end joins the border
   into a tee (`┬` on a bottom edge, `┴` on a top one; `├` / `┤` laid right).
4. The labels: for each real node in node order, `text = labels.get(id, id)`, a
   `str` (as `Line.of((text, styles.get(id)))`) or a Text `Line` (as given); its ROOM
   is `r.w - 2` boxed, `r.w` otherwise; it is cut to the room, `cut(line, room,
   ellipsis=ellipsis, pad=True, fill_style=styles.get(id))` (Text's [Cut]: never a
   split glyph; the padding covers the node's row so no port arm shows through), and
   written with Canvas's `label` at `(r.x + 1, r.y + (r.h - 1) // 2)` boxed, `(r.x,
   r.y + (r.h - 1) // 2)` otherwise. Text wins over the strokes under it.
5. The heads (HEADS): with `arrows` not None, each head cell's glyph written, after
   the labels (a head cell is in no rect, so the order never matters); `heads[k]` is
   edge k's `(cell, token)`, or None when it has no head or `arrows` is None.
6. `canvas.extend(p.width, p.height)`.
`labels`, `styles`, `weights`: mappings (None is empty). A key that names no node (a
`str` id) or no edge (a pair as given in `dag.edges`) is ignored, as stale keys from a
live view are. A style is opaque (compared with `==`, as Canvas does).

`lay(dag, charset, *, rounded=False, ellipsis=None, heads=True, <every other keyword
of diagram but arrows>) -> Laid`: with `g = diagram(dag, ..., ellipsis=e,
arrows=charset if heads else None)` (one call: the dag is laid out once), `Laid(rows=
draw(g.canvas, charset, rounded=rounded), rects={n.id: g.paths.rects[n.id] for n in
dag.nodes}, width=g.width, height=g.height)` (Canvas's `draw`, {Strokes} => {Rows}), `e` being `ellipsis` when given,
else `charset.glyph("ellipsis")`. `rounded=True` rounds the light corners, of boxes
and wires alike (╭╮╰╯). Heads are on by default (`heads=False` turns them off), drawn
from the same charset: with [Charset]'s `ASCII` base `>` `<` `^` `v`.

`Laid` ({Laid}, its own module `laid.py`, imported here; a frozen dataclass; its dict
is not to be mutated), `Laid(rows: tuple[Line, ...], rects: dict[str, Rect], width: int
= 0, height: int = 0)`:
- `rows`: the drawing, one Text `Line` per canvas row, exactly what `lay` returned
  before it returned a `Laid` ({Rows}: a Widgets `Drawing` takes them as they are);
- `rects`: each real node's drawn rect (Geometry's `Rect`, the cells its box or label
  is drawn in, the coordinates of `rows`), keyed by node id, in node order; a long
  edge's virtual vertices are not in it (they are [Route]'s, `g.paths.rects` keeps
  them). Folded, the rects are the folded ones, where the boxes are drawn;
- `width`, `height`: the drawing's extent, `g.width` and `g.height`, equal to the
  widest row and the row count (laid-extent), so a caller never scans the rows for
  them.
A caller that wants only the rows reads `.rows`: a `Laid` is not a sequence of rows
(not iterable, not indexable), so a caller left on the old `tuple[Line, ...]` fails
with a `TypeError` at its first use, never draws the wrong thing. `==` compares every
field.

The data, `Diagram` (a frozen dataclass; its canvas is mutable, the caller's to draw
on, and its dicts are not to be mutated):
- `Diagram(dag: Dag, layout: Coords, paths: Paths, canvas: Canvas, masks: tuple[Masks,
  ...], heads: tuple[tuple[tuple[int, int], str] | None, ...], width: int, height:
  int, over: bool)`: `layout` the [Place] layout of step 1 (what `previous` keeps
  still); `paths` the routed {Paths} (its `rects` every node's drawn rect, its `bands`
  the folding or None); `masks` each edge's wire cells, aligned with `dag.edges`;
  `heads` each edge's head as `((x, y), token)`, aligned with `dag.edges`, None for an
  edge with no head and for every edge when `arrows` is None (HEADS: the heads drawn,
  each edge's own token even where a shared cell shows another's); `width`, `height`
  the canvas's extent (`p.width`, `p.height`); `over` true when a `limit` was given and
  `ext(paths) > limit` (folded as far as it goes, still longer: never cut silently).
- `Diagram.hit(x, y) -> str | int | None`: what a click at cell `(x, y)` lands on: the
  id of the first real node, in node order, whose rect in `paths.rects` contains the
  cell; else the index of the first edge, in edge order, whose head is at the cell
  (`heads[k][0] == (x, y)`: a head cell answers the edge whose glyph it shows, even
  on a trunk an earlier edge shares); else the index of the first edge, in edge
  order, whose `masks[k].at((x, y))` is not 0 (a shared trunk cell answers its first
  edge); else None.

Laws:
- every node is drawn: each real node's label cells are in its rect, and a boxed
  node's outline is on its rect's border;
- every edge is drawn, and no wire crosses a box ([Route]'s guarantees, on
  `paths`); `len(masks) == len(dag.edges)`;
- folding: `over` is false whenever `limit` is None; with `limit` given and `over`
  false, `ext(paths) <= limit`; a drawing that fits is never folded (`paths.bands is
  None`);
- heads, with `arrows` given: `heads[k]` is None exactly when `len(masks[k].cells) ==
  2`; otherwise its cell is a cell of `masks[k]` that lies in no real node's rect and
  is next (one step along the layer axis) to a cell of `paths.rects[v]` (v =
  `dag.edges[k][1]`, the edge's own target), and its token names the step from it
  into that rect (`arrow.down` for `(0, 1)`, `arrow.up` `(0, -1)`, `arrow.right` `(1,
  0)`, `arrow.left` `(-1, 0)`): every edge whose wire has a cell in no real node's
  rect has exactly one head, pointing into its own target;
- no head anywhere else: for one-cell glyphs (as [Charset]'s are), the canvas's texts
  outside every real node's rect are exactly the head cells whose glyph is not `""`,
  each holding `arrows.glyph(token)` of the first edge, in edge order, whose head is
  there, in that edge's style; with `arrows` None there are none;
- heads touch only texts: `diagram(dag, ..., arrows=a)` has the same `layout`,
  `paths`, `masks`, extent and canvas joints as `diagram(dag, ...)` (no heads);
- laid once: with `g = diagram(dag, ..., ellipsis=cs.glyph("ellipsis"), arrows=cs if h
  else None)`, `lay(dag, cs, heads=h, ...).rows == g.canvas.rows(cs, rounded=...)` and
  `lay(dag, cs, heads=h, ...).rects == {n.id: g.paths.rects[n.id] for n in dag.nodes}`;
  `list(laid.rects) == list(dag.ids)`; `lay(Dag(), cs) == Laid((), {}, 0, 0)`;
- laid-extent: `lay(...).width == max(r.width for r in rows)` (0 with none) and
  `.height == len(rows)`, cold and warm;
- rects are the layout's alone: `lay(...).rects` does not depend on `charset`,
  `rounded`, `heads`, `ellipsis`, `labels`, `styles` or `weights` (a node's size is
  in the {Dag}; heads and labels touch only texts);
- every node is hit where it is drawn: each real node's label cells (and, boxed, its
  outline) in `rows` lie inside `rects[id]`;
- still: `diagram(d2, previous=diagram(d1))` keeps every node of d1 at its across
  coordinate where [Place]'s pinned law holds (along, layers may move as tracks
  change);
- equal inputs give `==` results.

The memos (Speed: a view lays its DAG again on every build, a selection move
included). Two module-level memos, each an `OrderedDict` of at most `_MEMO_SIZE = 8`
entries, the least recently used dropped when a ninth is stored, a hit refreshing its
entry:
- `_DRAWN`, in `diagram`: a DAG's unlabelled drawing, what steps 1 to 3 work out (the
  layout and routed paths, the wires, the canvas with the wires and boxes stroked, the
  masks, which nodes are boxed), keyed by the {Dag} and every option that reaches that
  work (`direction`, `limit`, `compact`, `sweeps`, `transpose`, `gap`, `lane_gap`,
  `rank_gap`, `passes`, `fold_gap`, `weight`, `back`, `boxes`, `box`, and `weights` as
  a frozen item set); never `styles`, `labels`, `ellipsis`, `arrows` or the charset.
  The kept drawing is stroked with the styles of the call that worked it out, and it
  keeps the OWNER of each joint cell: the source (edge, or boxed node) whose weight
  and style the cell holds, by Canvas's `join` rule (the first stroke laid there of
  the highest `RANK`; `fixed` is never passed). That rule compares weights only, never
  styles, so the owner does not depend on any style, and a style change is not a new
  drawing. A call takes a private copy of the kept canvas (the kept one is never
  written to); on it, each source whose style (`styles.get`) is not the very object
  (`is`) it was stroked with has every cell it owns restyled to that style (Canvas's
  `restyle`, its joints), and such an edge's mask is `Masks(weight, its style,
  cells)`; then it goes on from step 4. So every cell holds the caller's own style
  object, as a fresh call's does.
- `_LAID`, in `lay`: its answers, keyed by everything `lay` takes (the {Dag}, the
  charset, every option, `labels`, `styles` and `weights` as frozen item sets); an entry
  holds the rows, the rects, the width and the height. A hit returns `Laid(rows,
  dict(rects), width, height)`: the rows tuple shared (Lines are immutable), the
  rects a new dict every call. The charset stands in the key by its own hash when it
  hashes; else, a frozen dataclass instance ([Charset]'s {Charset} is one) by its type
  and its fields' values in order, a Mapping value as a frozenset of its items and a
  list or tuple as a tuple (one level deep), a field that is itself an unhashable
  frozen dataclass likewise; the call not kept if that still does not hash. Any other
  charset that does not hash is not kept. Equal charsets share an entry, whatever was
  imported first.
Scalar options stand in the keys with their types (`gap=True` never meets `gap=1`).
Not kept: a call with `previous` not None reads and writes neither memo; a call one of
whose key parts does not hash is worked out fresh, not stored; a call that raises
stores nothing (an entry is stored only once the whole call has succeeded). Argument
checks and their errors come first, as without the memos, before any memo is read.
One module-level lock, `_LOCK` (a `threading.Lock`), guards every read and write of
both memos, so `diagram` and `lay` may be called from any thread; the work runs
outside it (two threads missing one key may both work it out; the answers are equal).
Every answer equals the same call's with both memos cleared. For tests: `_DRAWN` and
`_LAID` may be cleared (`_DRAWN.clear()`, `_LAID.clear()`) to start cold, and
`layout`, `route`, `stroke` and `draw` are reached by their module global names at
call time, so a test may wrap them and count.

Inputs: `sized`: a `str` id, a `str` label or None, a bool. `paths` / `diagram` /
  `lay`: a {Dag}; the options of [Place]'s `layout`; `limit` None or an int >= 1;
  `fold_gap` an int >= 0; `inset` an int >= 0; `weight`, `back`, `box` and each value
  of `weights` one of Canvas's `WEIGHTS`; `previous` None, a {Coords} or a `Diagram`;
  `labels` values `str` or `Line`; `ellipsis` a `str`; `arrows` None or a charset
  (any object with `glyph(token) -> str`, [Charset]'s {Charset}). `lay`: a charset
  (the same kind), `rounded` and `heads` bools.
  `Diagram.hit`: ints.
Outputs: `sized`: a `Node`. `paths`: {Paths}. `diagram`: `Diagram`. `lay`: a `Laid`
  ({Laid}: `rows` a `tuple[Line, ...]`, {Rows}; `rects` a `dict[str, Rect]`; `width`,
  `height` ints). `hit`:
  a `str`, an `int` or None.
Errors: `GraphError` for `limit < 1`, a negative `fold_gap` or `inset`, a weight not
  in `WEIGHTS` (`weight`, `back`, `box`, a `weights` value), and whatever `layout`,
  `route` and `fold` raise. `TypeError` when `dag` is not a {Dag}, `limit` / `fold_gap`
  / `inset` is not an int (a `bool` included), `previous` is none of the accepted
  types, a `labels` value is neither `str` nor `Line`, `ellipsis` is not a `str`, an
  option mapping is not a mapping, or `hit` gets a non-int. `sized`: `TypeError` for
  a non-`str` id or label; `GraphError` for an empty id. `diagram` raises what
  `arrows.glyph` raises (`AttributeError` when it has none), `lay` what
  `charset.glyph` raises.
Effects: none (the canvas is made new for the caller).

Usage:
    from cure.draw.graph.ranks import Dag, Node
    from cure.draw.graph.diagram import diagram, lay, paths, sized
    from cure.draw.theme.charset import ASCII, Charset
    cs = Charset()
    plain = lambda dg: [l.plain for l in dg.canvas.rows(cs)]
    sized("parse"), sized("parse", boxes=False)   # Node("parse", 7, 3), Node("parse", 5, 1)
    s = Dag([sized("a"), sized("b"), sized("c")], [("a", "b"), ("b", "c"), ("a", "c")])
    g = diagram(s, arrows=cs)
    plain(g)                 # a's trunk forks to b and to c's lane; b's wire and the
                             # lane share c's one in-port (c is 3 wide: inset 1 leaves 1),
                             # so c takes one head; b's is where a's bus turns down
        # [" ┌─┐",
        #  " │a│",
        #  " └┬┘",
        #  "  │",
        #  " ▼┴─┐",
        #  "┌┴┐ │",
        #  "│b│ │",
        #  "└┬┘ │",
        #  " │  │",
        #  " └┐ │",
        #  "  ▼─┘",
        #  " ┌┴┐",
        #  " │c│",
        #  " └─┘"]
    g.heads                  # (((1, 4), "arrow.down"), ((2, 10), "arrow.down"),
                             #  ((2, 10), "arrow.down"))
    plain(diagram(s))[4], plain(diagram(s))[10]  # " ┌┴─┐", "  ├─┘": arrows None, no heads
    g.width, g.height, g.over                    # 5, 14, False
    g.paths.paths[2].points  # ((2, 2), (2, 4), (4, 4), (4, 10), (2, 10), (2, 11))
    g.hit(2, 1), g.hit(2, 3), g.hit(4, 7), g.hit(2, 10), g.hit(0, 0)  # "a", 0, 2, 1, None
    laid = lay(s, Charset("ascii", ASCII))
    [l.plain for l in laid.rows][:6]
        # [" +-+", " |a|", " +++", "  |", " v+-+", "+++ |"]
    laid.rects   # {"a": Rect(1, 0, 3, 3), "b": Rect(0, 5, 3, 3), "c": Rect(1, 11, 3, 3)}
    [l.plain for l in lay(s, Charset("ascii", ASCII), heads=False).rows][4]   # " ++-+"
    plain(diagram(s, labels={"a": "alpha"}, ellipsis="…"))[1]   # " │…│": cut to its room
    f = diagram(s, limit=13, arrows=cs)   # 14 rows > 13: folded, one layer per band,
    plain(f), (f.width, f.height, f.over) # side by side; heads at b and c only
        # ["    ┌──────┐ ┌───┐",
        #  "    │┌──┐  │ │┌──┤",
        #  "    ││  ▼  │ ││  ▼",
        #  "┌─┐ ││ ┌┴┐ │ ││ ┌┴┐",
        #  "│a│ ││ │b│ │ ││ │c│",
        #  "└┬┘ ││ └┬┘ │ ││ └─┘",
        #  " │  ││  │  │ ││",
        #  " ├──┘│  │  └─┘│",
        #  " └───┘  └─────┘"], (19, 9, False)
    f.heads                  # (((8, 2), "arrow.down"), ((17, 2), "arrow.down"),
                             #  ((17, 2), "arrow.down"))
    diagram(s, limit=8).over                     # True: 9 rows is as short as it goes
    two = Dag([sized("a"), sized("b")], [("a", "b"), ("b", "a")])
    t = diagram(two, arrows=cs)  # a bundle: (b, a) reversed, one wire, a head at each end
    plain(t), t.heads
        # ["┌─┐", "│a│", "└┬┘", " ▲", " ▼", "┌┴┐", "│b│", "└─┘"],
        # (((1, 4), "arrow.down"), ((1, 3), "arrow.up"))
    t.hit(1, 3), t.hit(1, 4)                     # 1, 0
    cy = Dag([sized(n) for n in "abc"], [("a", "b"), ("b", "c"), ("c", "a")])
    y = diagram(cy, arrows=cs)   # (c, a) reversed: dashed from a down to c, its head
    plain(y)[2:5], plain(y)[10]  # under a, on the trunk a -> b shares
        # [" └┬┘", "  ▲", " ▼┴╌┐"], "  ▼╌┘"
    y.heads[2], y.hit(2, 3)                      # ((2, 3), "arrow.up"), 2
    adj = Dag([sized("a"), sized("b")], [("a", "b")])
    plain(diagram(adj, rank_gap=0, arrows=cs))   # the boxes touch: no cell for a head
        # ["┌─┐", "│a│", "└┬┘", "┌┴┐", "│b│", "└─┘"]; .heads == (None,)
    u = Dag([sized(n, boxes=False) for n in ("lex", "parse", "check", "emit")],
            [("lex", "parse"), ("parse", "check"), ("parse", "emit"), ("check", "emit")])
    plain(diagram(u, boxes=False, direction="right", arrows=cs))
        # ["           ▶check─┐",
        #  "lex─▶parse─┤      └▶emit",
        #  "           └───────┘"]
    plain(diagram(u, boxes=False, direction="right"))[1]   # "lex──parse─┤      └┬emit"
    paths(u, direction="right").tracks           # (0, 1, 2)
"""

import dataclasses
import threading
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass

from cure.core.text import Line, width
from cure.core.text.cut import cut
from cure.draw.canvas import RANK, Canvas, Masks, Path, draw, label, link, restyle, stroke
from cure.draw.canvas.junctions import WEIGHTS

from .fold import fold
from .laid import Laid
from .place import Coords, layout
from .ranks import Dag, GraphError, Node
from .route import BACK, WEIGHT, Paths, route


@dataclass(frozen=True)
class Diagram:
    """A dag drawn: its layout, its routed paths, the canvas, each wire's cells and head, the extent, whether it is over the limit."""

    dag: Dag
    layout: Coords
    paths: Paths
    canvas: Canvas
    masks: tuple
    heads: tuple
    width: int
    height: int
    over: bool

    def hit(self, x: int, y: int) -> "str | int | None":
        """The node id, else the edge whose head is there, else the edge index, at cell (x, y); None for none."""
        for v in (x, y):
            if not isinstance(v, int) or isinstance(v, bool):
                raise TypeError(f"hit takes ints, got {type(v).__name__}")
        rects = self.paths.rects
        for id in self.dag.ids:
            if rects[id].contains(x, y):
                return id
        cell = (x, y)
        for k, h in enumerate(self.heads):
            if h is not None and h[0] == cell:
                return k
        for k, m in enumerate(self.masks):
            if m.at(cell):
                return k
        return None


def sized(id: str, label: "str | None" = None, *, boxes: bool = True) -> Node:
    """A node sized for its label: a 3-row box two cells wider than it, or the label's own width."""
    if not isinstance(id, str):
        raise TypeError(f"a node id must be a str, got {type(id).__name__}")
    if label is None:
        label = id
    elif not isinstance(label, str):
        raise TypeError(f"a label must be a str or None, got {type(label).__name__}")
    w = max(1, width(label))
    return Node(id, w + 2, 3) if boxes else Node(id, w, 1)


def paths(dag: Dag, *, direction: str = "down", limit: "int | None" = None, compact: bool = False,
          sweeps: int = 4, transpose: bool = True, gap: int = 2, lane_gap: int = 1,
          rank_gap: int = 2, passes: int = 4, fold_gap: int = 2, inset: int = 0,
          weight: str = WEIGHT, back: str = BACK,
          previous: "Coords | Diagram | None" = None) -> Paths:
    """The dag laid out and routed, folded to `limit` on its layer axis when longer."""
    return _paths(dag, direction=direction, limit=limit, compact=compact, sweeps=sweeps,
                  transpose=transpose, gap=gap, lane_gap=lane_gap, rank_gap=rank_gap,
                  passes=passes, fold_gap=fold_gap, inset=inset, weight=weight, back=back,
                  previous=previous)[1]


def diagram(dag: Dag, *, direction: str = "down", limit: "int | None" = None, compact: bool = False,
            sweeps: int = 4, transpose: bool = True, gap: int = 2, lane_gap: int = 1,
            rank_gap: int = 2, passes: int = 4, fold_gap: int = 2, weight: str = WEIGHT,
            back: str = BACK, previous: "Coords | Diagram | None" = None, boxes: bool = True,
            box: str = "light", labels: "Mapping | None" = None, styles: "Mapping | None" = None,
            weights: "Mapping | None" = None, ellipsis: str = "", arrows: object = None) -> Diagram:
    """The dag drawn onto a new canvas: wires stroked, then boxes, then labels, then heads (from `arrows`)."""
    labels, styles, weights = _arguments(dag, limit, fold_gap, previous, box, labels, styles,
                                         weights, ellipsis)
    options = dict(direction=direction, limit=limit, compact=compact, sweeps=sweeps,
                   transpose=transpose, gap=gap, lane_gap=lane_gap, rank_gap=rank_gap,
                   passes=passes, fold_gap=fold_gap, weight=weight, back=back)
    key = None if previous is not None else _key(
        dag, _typed(*options.values(), boxes, box), _frozen(weights))
    drawn = None if key is None else _recall(_DRAWN, key)
    hit = drawn is not None
    if drawn is None:
        drawn = _drawn(dag, options, previous, boxes, box, styles, weights)
    c, p, wires, kept, masks, boxed, owned = drawn
    canvas = kept.copy()   # Speed: the kept drawing, never written to; labels go on a copy
    edges = dag.edges
    for source, stroked, cells in owned:   # Speed: a style change restyles its owner's cells
        style = styles.get(source)
        if style is not stroked:
            for cell in cells:
                restyle(canvas, cell, style)
    masks = tuple(m if styles.get(e) is m.style else Masks(m.weight, styles.get(e), m.cells)
                  for e, m in zip(edges, masks))
    rects = p.rects
    for id in dag.ids:
        r, style = rects[id], styles.get(id)
        text = labels.get(id, id)
        line = Line.of((text, style)) if isinstance(text, str) else text
        room = r.w - 2 if boxed[id] else r.w
        line = cut(line, room, ellipsis=ellipsis, pad=True, fill_style=style)
        label(canvas, r.x + 1 if boxed[id] else r.x, r.y + (r.h - 1) // 2, line)
    heads = (None,) * len(edges)
    if arrows is not None:
        rev = set(p.coords.order.ranks.reversed)
        heads = tuple(_head(w, m, e in rev) for e, w, m in zip(edges, wires, masks))
        written = set()
        for e, h in zip(edges, heads):
            if h is None or h[0] in written:
                continue
            written.add(h[0])
            (x, y), token = h
            label(canvas, x, y, arrows.glyph(token), styles.get(e))
    canvas.extend(p.width, p.height)
    over = limit is not None and _ext(p) > limit
    if key is not None and not hit:
        _keep(_DRAWN, key, drawn)
    return Diagram(dag, c, p, canvas, masks, heads, p.width, p.height, over)


def lay(dag: Dag, charset: object, *, rounded: bool = False, ellipsis: "str | None" = None,
        heads: bool = True, direction: str = "down", limit: "int | None" = None, compact: bool = False,
        sweeps: int = 4, transpose: bool = True, gap: int = 2, lane_gap: int = 1,
        rank_gap: int = 2, passes: int = 4, fold_gap: int = 2, weight: str = WEIGHT,
        back: str = BACK, previous: "Coords | Diagram | None" = None, boxes: bool = True,
        box: str = "light", labels: "Mapping | None" = None, styles: "Mapping | None" = None,
        weights: "Mapping | None" = None) -> Laid:
    """{Dag} => {Laid}: the diagram's rows and each node's rect, one layout, heads on unless `heads=False`."""
    _need_dag(dag)
    e = charset.glyph("ellipsis") if ellipsis is None else ellipsis
    labels_, styles_, weights_ = _arguments(dag, limit, fold_gap, previous, box, labels,
                                            styles, weights, e)
    key = None if previous is not None else _key(
        dag, _charset_key(charset),
        _typed(rounded, e, heads, direction, limit, compact, sweeps, transpose, gap, lane_gap,
               rank_gap, passes, fold_gap, weight, back, boxes, box),
        _frozen(labels_), _frozen(styles_), _frozen(weights_))
    laid = None if key is None else _recall(_LAID, key)
    if laid is not None:
        rows, rects, w, h = laid
        return Laid(rows, dict(rects), w, h)   # Speed: the rows shared (Lines are immutable)
    g = diagram(dag, direction=direction, limit=limit, compact=compact, sweeps=sweeps,
                transpose=transpose, gap=gap, lane_gap=lane_gap, rank_gap=rank_gap, passes=passes,
                fold_gap=fold_gap, weight=weight, back=back, previous=previous, boxes=boxes,
                box=box, labels=labels, styles=styles, weights=weights, ellipsis=e,
                arrows=charset if heads else None)
    rows = draw(g.canvas, charset, rounded=rounded)
    rects = {n.id: g.paths.rects[n.id] for n in dag.nodes}
    if key is not None:
        _keep(_LAID, key, (rows, dict(rects), g.width, g.height))
    return Laid(rows, rects, g.width, g.height)


# --- private ------------------------------------------------------------------------

_TOKENS = {(0, 1): "arrow.down", (0, -1): "arrow.up", (1, 0): "arrow.right", (-1, 0): "arrow.left"}

_MEMO_SIZE = 8
_DRAWN: "OrderedDict[tuple, tuple]" = OrderedDict()   # key -> (c, p, wires, canvas, masks, boxed, owned)
_LAID: "OrderedDict[tuple, tuple]" = OrderedDict()    # key -> (rows, rects, width, height)
_LOCK = threading.Lock()


def _recall(memo: OrderedDict, key: tuple) -> "tuple | None":
    """The entry kept under `key`, refreshed; None when there is none."""
    with _LOCK:
        entry = memo.get(key)
        if entry is not None:
            memo.move_to_end(key)
        return entry


def _keep(memo: OrderedDict, key: tuple, entry: tuple) -> None:
    """`entry` stored under `key`, the least recently used dropped past `_MEMO_SIZE`."""
    with _LOCK:
        if key not in memo:   # the least recently used dropped first: never 9, even briefly
            while len(memo) >= _MEMO_SIZE:
                memo.popitem(last=False)
        memo[key] = entry
        memo.move_to_end(key)


_UNHASHABLE = object()   # a mapping with an item that does not hash


def _frozen(mapping: Mapping) -> object:
    """A mapping's items as a `frozenset`; `_UNHASHABLE` when one does not hash."""
    try:
        return frozenset(mapping.items())
    except TypeError:
        return _UNHASHABLE


def _key(*parts: object) -> "tuple | None":
    """The parts as a memo key; None when one does not hash (the call is not kept)."""
    if any(part is _UNHASHABLE for part in parts):
        return None
    try:
        hash(parts)
    except TypeError:
        return None
    return parts


def _typed(*values: object) -> tuple:
    """Each scalar option with its type, so `True` never stands for `1`."""
    return tuple((type(v), v) for v in values)


def _charset_key(charset: object) -> object:
    """The charset itself when it hashes; else a frozen dataclass instance by `_fields`;
    else `_UNHASHABLE` (the call not kept, as when the fields' form does not hash
    either: `_key` finds that out)."""
    try:
        hash(charset)
        return charset
    except TypeError:
        pass
    try:
        return _fields(charset) if _frozen_instance(charset) else _UNHASHABLE
    except TypeError:   # a Mapping item that does not hash
        return _UNHASHABLE


def _frozen_instance(value: object) -> bool:
    """Whether `value` is an instance (not a class) of a frozen dataclass."""
    return (dataclasses.is_dataclass(value) and not isinstance(value, type)
            and type(value).__dataclass_params__.frozen)


def _fields(value: object) -> tuple:
    """A frozen dataclass instance as (its type, its fields' values in order, by `_value`)."""
    return type(value), tuple(_value(getattr(value, f.name)) for f in dataclasses.fields(value))


def _value(v: object) -> object:
    """A field's value for a key: a Mapping as a frozenset of its items, a list or tuple
    as a tuple (one level: what is inside stands as it is), a frozen dataclass instance
    that does not hash by `_fields`; anything else as it is."""
    if isinstance(v, Mapping):
        return frozenset(v.items())
    if isinstance(v, (list, tuple)):
        return tuple(v)
    if _frozen_instance(v):
        try:
            hash(v)
        except TypeError:
            return _fields(v)
    return v


def _arguments(dag: object, limit: object, fold_gap: object, previous: object, box: object,
               labels: object, styles: object, weights: object, ellipsis: object) -> tuple:
    """`diagram`'s argument checks, then `_paths`' own, in their order: (labels, styles,
    weights) as mappings."""
    _need_dag(dag)
    labels = _mapping(labels, "labels")
    styles = _mapping(styles, "styles")
    weights = _mapping(weights, "weights")
    _weight(box, "box")
    for w in weights.values():
        _weight(w, "a weights value")
    for t in labels.values():
        if not isinstance(t, (str, Line)):
            raise TypeError(f"a label must be a str or a Line, got {type(t).__name__}")
    if not isinstance(ellipsis, str):
        raise TypeError(f"ellipsis must be a str, got {type(ellipsis).__name__}")
    if limit is not None:
        _int_option(limit, "limit", 1)
    _int_option(fold_gap, "fold_gap", 0)
    _previous(previous)
    return labels, styles, weights


def _drawn(dag: Dag, options: dict, previous: object, boxes: bool, box: str, styles: Mapping,
           weights: Mapping) -> tuple:
    """`diagram`'s steps 1 to 3, the unlabelled drawing: (layout, paths, wires, canvas,
    masks, boxed, owned). The wires are stroked one by one onto a new Canvas, as
    Canvas's `draw(wires)` does, so each stroke's cells are known; `owned` holds, for
    each source (edge, or boxed node id) that owns a joint cell, `(source, the style it
    was stroked with, its cells)`. A cell's owner is the source whose weight and style
    it holds by Canvas's `join` rule: the first stroke laid there of the highest
    `RANK` (no `fixed` is passed). It never depends on a style."""
    c, p = _paths(dag, inset=1 if boxes else 0, previous=previous, **options)
    wires = tuple(Path(q.points, weights.get(e, q.weight), styles.get(e))
                  for e, q in zip(dag.edges, p.paths))
    canvas = Canvas()
    sources, ranks, owner = [], [], {}

    def put(source: object, path: Path) -> None:
        k, rank = len(sources), RANK[path.weight]
        sources.append((source, path.style))
        ranks.append(rank)
        get = owner.get
        for cell in stroke(canvas, path):
            o = get(cell)
            if o is None or rank > ranks[o]:
                owner[cell] = k

    for e, w in zip(dag.edges, wires):
        put(e, w)
    masks = tuple(link(w) for w in wires)
    rects = p.rects
    boxed = {id: boxes and rects[id].w >= 3 and rects[id].h >= 3 for id in dag.ids}
    for id in dag.ids:
        if boxed[id]:
            r = rects[id]
            put(id, Path([(r.x, r.y), (r.right - 1, r.y), (r.right - 1, r.bottom - 1),
                          (r.x, r.bottom - 1), (r.x, r.y)], box, styles.get(id)))
    cells: dict = {}
    for cell, k in owner.items():
        cells.setdefault(k, []).append(cell)
    owned = tuple((sources[k][0], sources[k][1], tuple(cs)) for k, cs in sorted(cells.items()))
    return c, p, wires, canvas, masks, boxed, owned


def _need_dag(dag: object) -> None:
    if not isinstance(dag, Dag):
        raise TypeError(f"expected a Dag, got {type(dag).__name__}")


def _int_option(value: object, name: str, least: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if value < least:
        raise GraphError(f"{name} must be >= {least}, got {value}")
    return value


def _weight(value: object, name: str) -> None:
    if not isinstance(value, str) or value not in WEIGHTS:
        raise GraphError(f"{name} must be one of {WEIGHTS}, got {value!r}")


def _mapping(value: object, name: str) -> Mapping:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping, got {type(value).__name__}")
    return value


def _previous(previous: object) -> "Coords | None":
    if previous is None or isinstance(previous, Coords):
        return previous
    if isinstance(previous, Diagram):
        return previous.layout
    raise TypeError(f"previous must be None, a Coords or a Diagram, got {type(previous).__name__}")


def _ext(q: Paths) -> int:
    """The extent on the layer axis."""
    return q.height if q.coords.direction == "down" else q.width


def _paths(dag: Dag, *, direction: str, limit: "int | None", compact: bool, sweeps: int,
           transpose: bool, gap: int, lane_gap: int, rank_gap: int, passes: int, fold_gap: int,
           inset: int, weight: str, back: str, previous: object) -> tuple:
    """`paths`' steps: (the [Place] layout of step 1, the routed and folded {Paths})."""
    _need_dag(dag)
    if limit is not None:
        limit = _int_option(limit, "limit", 1)
    fold_gap = _int_option(fold_gap, "fold_gap", 0)
    prev = _previous(previous)
    c = layout(dag, compact=compact, sweeps=sweeps, transpose=transpose, direction=direction,
               gap=gap, lane_gap=lane_gap, rank_gap=rank_gap, passes=passes, previous=prev)
    p = route(c, inset=inset, weight=weight, back=back)
    if limit is None or _ext(p) <= limit:
        return c, p
    n = limit
    while True:
        q = route(fold(p.coords, n, gap=fold_gap), inset=inset, weight=weight, back=back)
        if _ext(q) <= limit or n == 1:
            return c, q
        n = max(1, n - (_ext(q) - limit))


def _head(wire: Path, masks: Masks, reversed: bool) -> "tuple[tuple[int, int], str] | None":
    """HEADS: the cell one step from the wire's target end toward its next point, and the
    token naming the step from it into the target; None for a two-cell wire."""
    if len(masks.cells) == 2:
        return None
    pts = wire.points
    (ex, ey), (nx, ny) = (pts[0], pts[1]) if reversed else (pts[-1], pts[-2])
    sx, sy = (nx > ex) - (nx < ex), (ny > ey) - (ny < ey)
    return (ex + sx, ey + sy), _TOKENS[(-sx, -sy)]
