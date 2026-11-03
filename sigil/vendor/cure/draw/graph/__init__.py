"""[Graph]: DAGs and trees laid out and routed onto a canvas.

Kind: system (the expansion of [Graph] in Draw). Depends on Canvas and Text, and through
Draw on Core: [Place], [Route] and [Trees] import Geometry's `Rect`; [Route] Canvas's
`Path` and `WEIGHTS`; [Diagram] Canvas (`Canvas`, `Masks`, `Path`, `draw`, `label`,
`link`, `stroke`, `WEIGHTS`) and Text (`Line`, `width`, `cut`). Nothing else from cure:
a {Charset} arrives as an argument and only its `glyph(token)` is used.

DAGs, trees and maps: laid out as data, drawn onto a canvas. Graph is generic (README
decision 3): construct's DAG view and minimap use it first; sigil's views keep their
own layout algorithms. Everything here is a pure function of plain values: equal
inputs give `==` results, every tie is broken by a stated rule (node order, edge
order, position), and nothing keeps state between calls; the last layout, when a
caller wants a changed dag kept still, is an argument (`previous`).

The layered pipeline, a module per step:

- [Ranks] (`ranks.py`): the input {Dag} (`Node`s with sizes in cells, edges as id
  pairs) and `GraphError`; cycles broken by a depth-first search (`acyclic`), a
  topological order (`topo`), ranks by longest path (or `compact`), long edges split
  into virtual vertices: {Layers}.
- [Order] (`order.py`): barycentre sweeps, the best kept, a transpose step; vertices of
  the last layout keep their relative order: {Order}; `crossings`.
- [Place] (`place.py`): every vertex's `Rect`, laid `"down"` or `"right"`, packed and
  centred on its neighbours, the last layout's vertices pinned where they were:
  {Coords}; `layout(dag)` runs the three.
- [Fold] (`fold.py`): a layout too long for the pane wrapped into bands of layers, with
  a track between bands per edge that crosses: {Bands}.

Beside it, from a {Dag} or a layout:

- [Lanes] (`lanes.py`): the narrow lane view (git log --graph, renderdag), one row per
  node, each column a Canvas direction mask: {Rows}.
- [Trees] (`trees.py`): tidy top-down trees (Reingold-Tilford) and indented trees with
  [Charset]'s guide tokens.
- [Blocks] (`blocks.py`): one cell per node, for a minimap.

Routed and drawn:

- [Route] (`route.py`): orthogonal wires, ports, channels, fan-out trunks, bundles:
  `route({Edges}) => {Paths}` on [Place].
- [Diagram] (`diagram.py`): the entry that lays out, routes and strokes onto a Canvas
  (`paths({Dag}) => {Paths}`, `diagram`, Canvas's `link`), `sized` (a node sized for
  its label), and Graph's boundary op, `lay`.

The boundary: `lay(dag, charset, **options) -> Laid` (`[Views] -> [Graph] : lay({Dag})
=> {Laid}`, and `[DagView] -> [Graph] : lay`; Diagram's, re-exported here). The dag is
laid out once and handed back as a `Laid` ({Laid}, a frozen dataclass, in its own
module `laid.py`, which `diagram.py` imports): `rows`, the drawing as Text `Line`s
({Rows}, what `lay` returned before Q8); `rects`, each real node's drawn `Rect` keyed
by id in node order, in the rows' coordinates; and `width`, `height`, the drawing's
extent (the widest row and the row count, from the Diagram, so a caller's pan and
clamp never scan the rows). So a view that hits nodes (DagView's click targets) takes
them from the same call and never runs Diagram again. A caller that wants only the rows
reads `lay(...).rows` (Diagram's docstring has the full contract and laws; a `Laid` is
not iterable, so a caller left on the old tuple fails loudly). `sized` is on this face
because a {Dag} for `lay` is built from it: a caller needs nothing from `diagram.py`.

Re-exported here: `Dag`, `Node`, `Layers`, `GraphError`, `acyclic`, `topo`, `ranks`
(ranks); `Order`, `order`, `crossings` (order); `Coords`, `DIRECTIONS`, `place`,
`layout` (place); `Band`, `Bands`, `fold` (fold); `Row`, `Lanes`, `lanes` (lanes);
`Tidy`, `Indent`, `tidy`, `indent`, `prefix` (trees); `Blocks`, `grid`, `scaled`
(blocks); `Laid` (laid); `lay`, `sized` (diagram).

Effects: none.

Usage:
    from cure.draw.graph import Dag, Node, layout, fold, lanes
    d = Dag([Node("a", 3), Node("b", 3), Node("c", 3), Node("d", 3), Node("e", 3)],
            [("a", "c"), ("b", "c"), ("a", "d"), ("c", "e"), ("d", "e"), ("a", "e")])
    c = layout(d)
    c.width, c.height, c.order.crossings     # (9, 7, 0)
    fold(c, 4).bands[1].first                # 2: layers 0-1 fit 4 rows; layer 2 sits beside them
    lanes(d).width                           # 7
    from cure.draw.graph import lay, sized
    from cure.draw.theme.charset import ASCII, Charset
    s = Dag([sized("a"), sized("b")], [("a", "b")])
    laid = lay(s, Charset("ascii", ASCII))
    laid.rects["b"], len(laid.rows)          # Rect(0, 5, 3, 3), 8: rows and rects, one layout
"""

from .blocks import Blocks, grid, scaled
from .fold import Band, Bands, fold
from .lanes import Lanes, Row, lanes
from .order import Order, crossings, order
from .place import DIRECTIONS, Coords, layout, place
from .ranks import Dag, GraphError, Layers, Node, acyclic, ranks, topo
from .trees import Indent, Tidy, indent, prefix, tidy
from .laid import Laid
from .diagram import lay, sized
