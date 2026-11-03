"""[Frame]: the base, then overlays by z.

Kind: service (pure functions and two frozen dataclasses: the `{Frame}` result and
the `Tiled` view). Frame provides `frame` (the boundary op `frame({Node}) =>
{Frame}`, re-exported by the Paint package) and `sizes` (`[Sweep] -> [Paint] :
sizes({Node}) => {Frames}`). It runs one frame, a pure function: the same view, size
and context give the same frame. For one node tree it calls [Measure] (`natural`,
through `adapt` and a `Measure` memo), Layout's `lay` (`[Frame] -> [Layout] :
lay({Node}) => {Rects}`), [Painter]'s `contexts` and `paint` (`[Frame] -> [Painter] :
paint({Rects}) => {Grid}`), and Buffer's `compose` (`[Frame] -> [Buffer] :
compose({Layers}) => {Grid}`): the base, then overlays by z. Nothing is kept between
frames: offsets, scroll positions, the focus, the hover and the clock are the app's,
given in the nodes and the context.

The main loop's call (README): `frame = paint.frame(view(state), term.size, ctx)`;
`frame.hits` goes to Input's router, `frame.layer` as its `layer`, `frame.buffer` to
the terminal, `frame.cursor` to the terminal's cursor.

One tree (`_tree`, the step every view below is made of), for a widget tree `node`
laid out in a rect `R`, painted on base layer `z`, in a frame of `size = (w, h)` with
area `A = Rect(0, 0, w, h)`:
1. `a = adapt(node)` ([Measure]: the protocol checked on every node, cycles refused).
2. `cx = contexts(node, ctx)` ([Painter]: scope, zone, lift and level, at its one
   recursion point).
3. `m = Measure(cx)`: the memo of this tree in this frame.
4. `rects = lay(a, R, m)` (Layout).
5. `paint(rects, cx, size, z=z, area=..., backdrop=..., outside=...)` ([Painter])
   gives the tree's layers, hits, cursor and places. `area` is the tree's root rect
   `R` (Overlay's "the root rect": a modal overlay in a pane captures inside that
   pane), except a modal screen's (`k >= 1` below), which is `A`.

The views `frame` takes:
- A widget node: one tree in `R = A`, `z = 0`, backdrop `"none"`. The root's own
  `anchor`, `layer`, `backdrop` and `modal` are not read (the root is the base).
- A Layout `Screens` stack whose screens are views: `drawn = stack.drawn` (Screens'
  modal rule: from the topmost "full" screen up, bottom first). Drawn screen `k` (from
  0) is painted on base layer `z = k * LAYERS`:
  - `k == 0`: as its own view (a widget node, or a `Tiled`), in `A`.
  - `k >= 1` (a modal over the screens beneath): a widget node only; it floats, sized
    and placed as Layout places a floating child: `w0 = natural(a, "x", A.h)`,
    `h0 = natural(a, "y", min(w0, A.w))` (with this tree's `Measure`), `R =
    place(w0, h0, A, at.at, at.margin)` (Layout's Anchor) with `at` the root's
    `anchor` when it is an `At`, else `At()` (centred); painted with backdrop
    `"dim"` (every screen under the top one is drawn under a backdrop: Screens'
    `backdrop` flag) and `outside=True` (its root's `(id, "outside")` hit on layer
    `z` over the whole area, before its own hits, when the root has an `id`).
  `layer` (the router's floor) is `(len(drawn) - 1) * LAYERS`: the input screen's
  base layer (`0` for an empty stack, which gives a blank frame with no hits).
- A `Tiled(tree, views, titles)`: a split tree of panes, each showing its own widget
  tree (Splits is a separate call, not a node kind `lay` reads):
  1. `tiling = panes(tree, A)` (Layout's Splits).
  2. `tiles(tiling, tree, ctx, size, titles=titles)` ([Painter]): the ground, the
     gutters and the tab / title bars, on layer 0 (tiled) and `j + 1` (float `j`).
  3. For each pane of `tiling.visible`, in order: its layer `pz` is `0` for a tiled
     pane and `j + 1` for a pane in float `j` (its path starts `("float", j)`); its
     hits begin with `Hit(pane.rect, ("pane", pane.id), pz)` (when the rect is not
     empty), then its tree `views[pane.id]`, one tree in `R = pane.rect`, `z = pz`
     (so an overlay in it paints on `pz + layer`). Hidden panes are neither laid out
     nor painted (a hidden terminal keeps its size in the Tiling).
  `frame.tiling` is the `Tiling`; `frame.panes[id]` the {HitMap} of pane `id`'s own
  hits (its `("pane", id)` hit and its tree's), for every visible pane; `frame.hits`
  the chrome's hits then every pane's, in that order. A `Tiled` may be a `Screens`
  stack's bottom drawn screen; above it, it is a `TypeError`.

Composing: `buffer = compose(layers, w, h)` (Buffer's: a new grid, the layers sorted by
`z`, stably, each after its backdrop), with `layers` every tree's layers in the order
the trees were painted (screens bottom first; the chrome, then the panes in Tiling
order). Equal `z` keep that order: a later tree's layer covers an earlier one's.
`hits` is every tree's hits merged in that order (`HitMap.merged`). `cursor`: the last
non-`None` cursor of the input screen's trees (the top drawn screen; for a node or a
`Tiled` view, its own trees), else `None`: a cursor under a modal is not shown.
`places`: every tree's places, in paint order.

Data (frozen dataclasses):
- `Frame(buffer, hits, cursor, size, layer=0, places=(), tiling=None, panes={})`:
  - `buffer`: the composed Buffer {Grid}, `w` x `h`;
  - `hits`: the frame's Geometry {HitMap}, in screen space: every widget's hits on
    its layer (an overlay's on its `layer`, a modal's `outside` hit beneath its own),
    for Input's router;
  - `cursor`: the screen cell `(x, y)` of the text cursor (a focused TextInput's or
    Pane's `cursor_at`), or `None` (the app hides the terminal cursor);
  - `size`: `(w, h)`;
  - `layer`: the input screen's base hit layer, the router's `layer` floor;
  - `places`: a tuple of [Painter]'s `Place(id, rect, clip, layer)`, one per painted
    node occurrence with an `id`, in paint order;
  - `tiling`: the Layout `Tiling` of a `Tiled` view (the bottom one under Screens), or
    `None`;
  - `panes`: a `dict` from pane id to its {HitMap} (empty without a `Tiled` view);
    not to be mutated.
  - `where(id) -> Place`: the first place whose `id == id`; `KeyError` when none.
- `Tiled(tree, views, titles=None)`: `tree` a Layout `SplitTree`; `views` a mapping
  from pane id to the widget tree that pane shows (every visible pane must have one);
  `titles` a mapping from pane id to the styled text of its tab or title bar, or
  `None` (the pane id is the title). Checked on construction (`__post_init__`).

Operations:
- `frame(view, size, ctx) -> Frame`: the frame of `view` (a widget node, a `Screens`,
  a `Tiled`), as above. `size` is any pair of ints `(w, h)` (a tuple, or
  `os.terminal_size`); `ctx` the app's root {Context}: its `level` is the app's base
  level (decision 6), its `focus`, `hover` and `now` the app's.
- `sizes(view, widths, heights, ctx) -> tuple[Frame, ...]`: `frame(view, (w, h), ctx)`
  for every `w` of `widths` and, inside it, every `h` of `heights` (widths outer), in
  that order: Testing's Sweep checks them for jumps.

Speed. Within one frame every natural size is memoised per node occurrence: the key is
`(path, axis, room)` in the tree's `Measure` (so nested `Auto` containers cost one
`measure` per node per room, never one per ancestor). Nothing is memoised across
frames: a frame is a pure function of its arguments and Paint holds no state. F1 made
a frame cheaper without changing it: Core's printable-ASCII fast path (Text's `put`,
Buffer's `check` on every write, blit and compose) and [Painter]'s base layer painted
only within the tree's root clip, so each pane of a `Tiled` view paints, cuts and is
composed within its own rect, never as a frame-sized layer. What is left of a large
node (a 2,000-word Paragraph's wrap of all its text for `↓N more`, and Buffer's
`shade`) is a later task's (a cache the app passes in, or the widget's own work
bounded to its rect).

Budgets, with Buffer's calibration unit `U` and method (`cure.core.buffer`: measured
in the same run, interleaved, minima; `k` the budget, baselines at 26d0853 and the
prototype F1 was sized by, on the dev machine under load). The benchmarks are fixed,
built in the test from cure's public names (no `examples/` import), with `ctx =
Context.of(builtin(), focus="shell")` and `WORDS` Buffer's B3 word list:
- B1, a console-shaped frame: `frame(Tiled(tree, views, {p: p for p in ("shell",
  "dag", "minimap")}), (100, 30), ctx)` with `tree = SplitTree(Split("x",
  (Pane("shell"), Split("y", (Pane("dag"), Pane("minimap")), (3, 1))), (3, 2)),
  floating=(Float(Pane("hints"), Rect(0, 29, 100, 1)),))` (Layout's names) and the
  views: `"shell"`, `Block((Pane(screen, cursor=(0, 0), focused=True, id=...),),
  title="shell", focused=True, id=...)` (Widgets' Pane) over a `Grid(80, 40)` with
  row `y` put as `(L * 3)[y % 11:y % 11 + 76]`, `L = "$ ls -la
  /usr/lib/python3.12/site-packages | grep cure && echo done; "` (one space where the
  line breaks here); `"dag"`, a `Block` of a `Drawing` of `Rows.of` 30 rows, row `y`
  `"".join(f"│ K{(y + i) % 100:02d} │──▶" for i in range(6))`; `"minimap"`, a
  `Block` of a `Drawing` of `Rows.of` 6 rows, each `[("█", "accent"), (" ", None),
  ("░", "muted"), (" ", None)] * 8`; `"hints"`, `KeyHints((Hint("ctrl+g", "prefix"),
  Hint("tab", "next pane"), Hint("z", "zoom"), Hint("q", "quit")))`.
  Baseline: 97-124 U (`examples/console.py`'s own frame at 100 x 30, a quiet run:
  ~170 ms). Budget: `k = 30` (about 3.5 times faster; prototype 21-24 U).
- B2, a long Paragraph: `frame(Block((Paragraph(text),), title="p"), (120, 40), ctx)`,
  `text = " ".join(WORDS[(i * 7) % 12] for i in range(2000))`. Baseline:
  117-137 U (~200 ms quiet). Budget: `k = 50` (about 2.5 times faster; prototype
  38-41 U; the rest is wrap and shade, above).
- B4, many panes: `frame(Tiled(SplitTree(Split("x", (Split("y", (Pane(f"p{i}{j}") for
  j in 0..3)) for i in 0..3))), {id: Block((Paragraph(f"pane {id}"),), title=id,
  id=id)}), (120, 40), ctx)`: 16 panes. Baseline: 292-302 U. Budget: `k = 22`
  (prototype 17-18 U; with the fast path but frame-sized pane layers it measured 27
  U), and, independent of `U`, `min(B4) <= 4 * min(B5)` with B5 the same frame with
  one pane (`Tiled(SplitTree(Pane("p00")), {"p00": <its Block>})`): pane layers cost
  their rects, so 16 panes cost about their chrome more than one (prototype 2.2;
  baseline 7.8; F1 measured 3.0-3.2, the rest per-pane layout and chrome, so the bound
  is 4, well below frame-sized pane layers).

Laws (each a property a test can loop over views, sizes and contexts):
- pure: `frame(v, s, c) == frame(v, s, c)`; the view and the context are unchanged.
- a leaf: for a leaf node `n`, `frame(n, (w, h), c).buffer == g` and its `hits` are
  `HitMap(widgets.paint(n, Rect(0, 0, w, h), enter(n, c), g))` where `g = Grid(w, h)`
  is painted that way.
- inside: every hit's rect lies inside `Rect(0, 0, w, h)`, and so does `cursor`.
- footprint: an Overlay with backdrop `"none"` changes no cell outside its clip: the
  frame with it equals the frame without it there; with `"dim"`, those cells are the
  same glyphs with `dim=True` added.
- layers: every hit of an Overlay's subtree is on layer `overlay.layer` (plus the
  screen's base); a click inside an overlay's rect is won by the overlay (`hits.at`).
- modal: with a modal Overlay (or a Screens modal) that has an `id`, `hits.at(x, y)`
  is never a base-layer tag.
- tiles: with a `Tiled` view and no floats, every visible pane's hits lie in its rect,
  and `frame.panes` has exactly the visible pane ids.
- tiled same (F1): for every view (a node, a `Screens`, a `Tiled` with floats, zoom,
  tabs, hidden and empty panes), size and context, `frame` gives a `Frame` `==` to the
  frame-sized construction of 26d0853 (each tree's base painted into a `Grid(w, h)`
  and cut to its root clip; [Painter]'s law rect_painted): the same buffer cell for
  cell, the same hits in the same order, the same cursor, layer, places, tiling and
  panes; and the same error class for the same bad input. A proof compares with that
  construction kept as a reference (a copy of 26d0853's `paint` passed in its place)
  over random views and sizes, and over the fixed benchmarks above.
- sizes: `len(sizes(v, ws, hs, c)) == len(ws) * len(hs)`, and frame `i` has size
  `(ws[i // len(hs)], hs[i % len(hs)])`.

Inputs: as above.
Outputs: a `Frame`; a tuple of `Frame` ({Frames}).
Errors: `TypeError` when `size` is not a pair of ints (a `bool` included), `widths` /
  `heights` is not an iterable of such ints, `view` is a `Tiled` above a Screens'
  bottom drawn screen or a `Screens` inside a `Screens`, or as the parts raise (a node lacking the protocol: "node lacks
  '<name>'"); `ValueError` when a size is negative, an overlay's `layer` is outside
  `1 .. LAYERS - 1`, or as the parts raise (a cycle, a Scaffold without three
  children); `KeyError` when a visible pane has no view. `Tiled(...)`: `TypeError` when
  `tree` is not a `SplitTree`, `views` is not a mapping, or `titles` is neither
  `None` nor a mapping.
Effects: none.

Usage:
    from cure.core.buffer import text
    from cure.core.geometry import Hit, HitMap, Rect
    from cure.draw.context import Context
    from cure.draw.layout import At, Pane, Split, SplitTree
    from cure.draw.theme import builtin
    from cure.draw.widgets import Block, Overlay
    from cure.draw.paint import Tiled, frame
    ctx = Context.of(builtin())
    f = frame(Block(title="Title", id="b"), (11, 3), ctx)
    text(f.buffer)     # "╭─ Title ─╮\\n│         │\\n╰─────────╯"
    f.hits, f.cursor, f.layer   # HitMap((Hit(Rect(0, 0, 11, 3), "b"),)), None, 0
    f = frame(Block((Overlay(anchor=At(), title="Help", id="o"),), border=None, id="root"),
              (20, 6), ctx)
    f.hits.at(6, 2), f.hits.at(0, 0)    # "o" (layer 1), "root" (layer 0)
    text(f.buffer).split("\\n")[2]       # "     ╭─ Help ─╮     ": centred, 10 x 2
    t = frame(Tiled(SplitTree(Split("x", (Pane("a"), Pane("b")))),
                    {"a": Block(id="A"), "b": Block(id="B")}), (21, 5), ctx)
    t.hits.at(10, 2), t.hits.at(5, 2)   # ("gutter", (), 0), "A"
    sorted(t.panes)                     # ["a", "b"]
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from cure.core.buffer import compose
from cure.core.geometry import Hit, HitMap, Rect
from cure.draw.layout import At, Screens, SplitTree, lay, panes, place

from .measure import Measure, adapt, natural
from .painter import LAYERS, Painted, Place, _int, _pair, contexts, paint, tiles


@dataclass(frozen=True)
class Frame:
    """{Frame}: the composed grid, the hit map, the cursor, and what the app keeps in step (see the module)."""

    buffer: object
    hits: object
    cursor: "tuple[int, int] | None"
    size: "tuple[int, int]"
    layer: int = 0
    places: tuple = ()
    tiling: object = None
    panes: dict = field(default_factory=dict)

    def where(self, id: object) -> Place:
        """The first place of the node whose `id` is `id` (KeyError when none)."""
        for p in self.places:
            if p.id == id:
                return p
        raise KeyError(id)


@dataclass(frozen=True)
class Tiled:
    """A split tree of panes, each showing its own widget tree (see the module)."""

    tree: object
    views: Mapping
    titles: "Mapping | None" = None

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        if not isinstance(self.tree, SplitTree):
            raise TypeError(f"tree must be a SplitTree, got {type(self.tree).__name__}")
        if not isinstance(self.views, Mapping):
            raise TypeError(f"views must be a mapping, got {type(self.views).__name__}")
        if self.titles is not None and not isinstance(self.titles, Mapping):
            raise TypeError(f"titles must be a mapping or None, got {type(self.titles).__name__}")


def frame(view: object, size: "tuple[int, int]", ctx: object) -> Frame:
    """One frame of `view` (a node, a Screens stack or a Tiled) at `size`: pure (see the module)."""
    w, h = _pair(size)
    area = Rect(0, 0, w, h)
    painted: list = []               # every tree's Painted, in paint order
    tiling, owned, layer = None, {}, 0
    top: list = painted              # the input screen's trees, for the cursor
    if isinstance(view, Screens):
        drawn = view.drawn
        for k, (screen, _) in enumerate(drawn):
            z = k * LAYERS
            top = []
            if isinstance(screen, Screens):
                raise TypeError("a Screens cannot be a screen of a Screens")
            if k == 0 and isinstance(screen, Tiled):
                tiling, owned = _tiled(screen, (w, h), ctx, top)
            elif isinstance(screen, Tiled):
                raise TypeError("a Tiled can only be a Screens' bottom drawn screen")
            elif k == 0:
                top.append(_tree(screen, area, 0, (w, h), ctx))
            else:
                top.append(_tree(screen, None, z, (w, h), ctx, backdrop="dim", outside=True))
            painted.extend(top)
        layer = (len(drawn) - 1) * LAYERS if drawn else 0
    elif isinstance(view, Tiled):
        tiling, owned = _tiled(view, (w, h), ctx, painted)
    else:
        painted.append(_tree(view, area, 0, (w, h), ctx))
    hits = HitMap(tuple(hit for p in painted for hit in p.hits.hits))
    cursor = next((p.cursor for p in reversed(top) if p.cursor is not None), None)
    return Frame(compose([x for p in painted for x in p.layers], w, h), hits, cursor, (w, h),
                 layer, tuple(x for p in painted for x in p.places), tiling, owned)


def _tree(node: object, R: "Rect | None", z: int, size: "tuple[int, int]", ctx: object, *,
          backdrop: str = "none", outside: bool = False) -> Painted:
    """One tree: adapt, contexts, a Measure, lay, paint. `R=None`: a modal screen, placed
    as a floating child in the whole area, which is its capture area."""
    a = adapt(node)
    cx = contexts(node, ctx)
    m = Measure(cx)
    whole = Rect(0, 0, *size)
    if R is None:
        w0 = natural(a, "x", whole.h, cx, memo=m.memo)
        h0 = natural(a, "y", min(w0, whole.w), cx, memo=m.memo)
        at = a.anchor if isinstance(a.anchor, At) else At()
        R, capture = place(w0, h0, whole, at.at, at.margin), whole
    else:
        capture = R
    return paint(lay(a, R, m), cx, size, z=z, area=capture, backdrop=backdrop, outside=outside)


def _tiled(view: Tiled, size: "tuple[int, int]", ctx: object, out: list) -> tuple:
    """A Tiled view's chrome and visible panes, appended to `out` in paint order; its
    `Tiling` and each visible pane's own HitMap."""
    tiling = panes(view.tree, Rect(0, 0, *size))
    out.append(tiles(tiling, view.tree, ctx, size, titles=view.titles))
    owned: dict = {}
    for pane in tiling.visible:
        pz = pane.path[1] + 1 if pane.path and pane.path[0] == "float" else 0
        own = () if pane.rect.empty else (Hit(pane.rect, ("pane", pane.id), pz),)
        tree = _tree(view.views[pane.id], pane.rect, pz, size, ctx)
        out.append(Painted(tree.layers, HitMap(own + tree.hits.hits), tree.cursor, tree.places))
        owned[pane.id] = out[-1].hits
    return tiling, owned


def sizes(view: object, widths: Iterable, heights: Iterable, ctx: object) -> tuple:
    """`frame(view, (w, h), ctx)` for every width, then every height (see the module)."""
    ws, hs = _ints(widths, "widths"), _ints(heights, "heights")
    return tuple(frame(view, (w, h), ctx) for w in ws for h in hs)


def _ints(values: object, name: str) -> tuple:
    """`values` as a tuple of ints (TypeError when not an iterable of ints)."""
    if not isinstance(values, Iterable):
        raise TypeError(f"{name} must be an iterable of ints, got {type(values).__name__}")
    values = tuple(values)
    for v in values:
        _int(v, name[:-1])
    return values
