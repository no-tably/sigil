"""[Trees]: tidy trees, indented trees with guides.

Kind: service (data classes and pure functions).

What it does: two layouts of a forest given as a {Dag} whose every node has at most one
parent. `tidy(dag)` places it top-down, Reingold-Tilford style: each parent centred
over its first and last child, sibling subtrees packed left to right as close as their
contours allow, the same depth on the same rows. `indent(dag)` gives the indented
outline a tree widget draws (one row per node, depth-first), with the GUIDE TOKENS of
each row's prefix; `prefix` turns those tokens into text with the {Charset} the caller
gives (never a glyph picked here).

The forest: the parent of v is u for the edge `(u, v)`; the ROOTS are the nodes with no
parent, in node order; a node's children are the heads of its out-edges, in edge
order. A node with two parents, or a cycle (nodes no root reaches), is a GraphError
("not a forest").

Tidy (`tidy(dag, *, gap=2, rank_gap=1) -> Tidy`), in cells, widths and heights from the
`Node`s:
1. Rows: depth k's top `y_k`: `y_0 = 0`, `y_{k+1} = y_k + h_k + rank_gap`, `h_k` the
   greatest node height at depth k. Every node at depth k has `y = y_k`.
2. Subtrees, bottom up, each laid in coordinates where its root is at x = 0. A leaf is
   just itself. For a node u with children c_1 .. c_n (subtrees already laid):
   - pack the children's subtrees left to right: c_1's at offset 0; each next c_j at
     the offset `max over relative depths k shared with the subtrees already packed of
     (R(k) + gap - l_j(k))`, where R(k) is the greatest `x + width` at depth k over the
     subtrees already packed (at their offsets) and l_j(k) the least x at depth k in
     c_j's subtree (depth 0 is the children's own level, which all share);
   - u's x: `(centre(c_1) + centre(c_n)) // 2 - (width(u) - 1) // 2`, with
     `centre(v) = x(v) + (width(v) - 1) // 2` and Python's floor division (a single
     child: u centred over it);
   - then the whole subtree shifts so that u is at 0.
   (Classic Reingold-Tilford packing; no Walker spreading of the small subtrees between
   big ones.)
3. The roots' trees are packed left to right as one family of siblings (with no
   parent), then every x shifts by the same amount so the least is 0.

Indent (`indent(dag) -> tuple[Indent, ...]`): the nodes in depth-first pre-order, the
roots in node order, children in edge order. A root's guides are `()`. A child at
depth d >= 1 has d tokens: the first d - 1 copy its parent's guides with
`"guide.branch"` turned into `"guide.vert"` and `"guide.last"` into `None` (a blank: no
line below an ancestor's last child), and the last is `"guide.last"` when it is its
parent's last child, else `"guide.branch"`. The tokens are [Charset]'s.

`prefix(row, charset) -> str`: the row's guides, each three cells: `"guide.branch"` ->
`glyph("guide.branch") + glyph("guide.stem") + " "`, `"guide.last"` ->
`glyph("guide.last") + glyph("guide.stem") + " "`, `"guide.vert"` ->
`glyph("guide.vert") + "  "`, `None` -> `"   "`; `""` for a root. `charset` is any
object with `glyph(token) -> str` ([Charset]'s {Charset}).

The data (frozen dataclasses; the dicts are not to be mutated):
- `Tidy(dag: Dag, rects: dict[str, Rect], depth: dict[str, int], parent: dict[str,
  str | None], width: int, height: int)`: each node's Geometry `Rect` (its own size),
  depth and parent (`None` for a root), all keyed in node order; the extent, the
  greatest `x + w` and `y + h` (0, 0 for an empty dag).
- `Indent(node: str, depth: int, guides: tuple[str | None, ...])`, `len(guides) ==
  depth`.

Laws:
- no two rects overlap; siblings lie left to right in edge order, at least `gap`
  apart;
- every parent is centred over its first and last child by the formula in 2;
- every node at depth k has `y = y_k`, and the least x is 0;
- `indent` lists every node once, each parent before its children, and every subtree
  as a contiguous run of rows;
- equal inputs give `==` results.

Inputs: `tidy`: a {Dag} that is a forest; `gap`, `rank_gap` ints >= 0. `indent`: such a
  {Dag}. `prefix`: an `Indent` and a charset.
Outputs: `tidy`: `Tidy`. `indent`: a tuple of `Indent`. `prefix`: a `str`.
Errors: `GraphError` for a node with two parents or a cycle, a negative `gap` or
  `rank_gap`. `TypeError` when `dag` is not a {Dag}, an option is not an int (a `bool`
  included), or `row` is not an `Indent`.
Effects: none.

Usage:
    from cure.draw.graph.ranks import Dag, Node
    from cure.draw.graph.trees import indent, prefix, tidy
    from cure.draw.theme.charset import Charset
    t = Dag(["r", "a", "b", Node("c", 3), "d", "e"],
            [("r", "a"), ("r", "b"), ("r", "c"), ("a", "d"), ("a", "e")])
    k = tidy(t)
    [(n, k.rects[n].x, k.rects[n].y) for n in t.ids]
        # [("r", 4, 0), ("a", 1, 2), ("b", 4, 2), ("c", 7, 2), ("d", 0, 4), ("e", 3, 4)]
    k.width, k.height                    # (10, 5)
    o = Dag(["r", "a", "b", "x", "y", "z"],
            [("r", "a"), ("a", "x"), ("a", "y"), ("r", "b"), ("b", "z")])
    rows = indent(o)
    [r.guides for r in rows][-1]         # (None, "guide.last")
    [prefix(r, Charset()) + r.node for r in rows]
        # ["r", "├─ a", "│  ├─ x", "│  └─ y", "└─ b", "   └─ z"]
"""

from dataclasses import dataclass

from cure.core.geometry.rect import Rect

from .ranks import Dag, GraphError


@dataclass(frozen=True)
class Tidy:
    """A forest laid out top-down: each node's rect, depth and parent, and the extent."""

    dag: Dag
    rects: dict
    depth: dict
    parent: dict
    width: int
    height: int


@dataclass(frozen=True)
class Indent:
    """One row of an indented tree: its node, depth and guide tokens."""

    node: str
    depth: int
    guides: tuple


def _forest(dag: object) -> tuple:
    """The roots (node order), each node's parent and its children (edge order); GraphError if not a forest."""
    if not isinstance(dag, Dag):
        raise TypeError(f"expected a Dag, got {type(dag).__name__}")
    parent = {id: None for id in dag.ids}
    children = {id: [] for id in dag.ids}
    for u, v in dag.edges:
        if parent[v] is not None:
            raise GraphError(f"not a forest: {v!r} has two parents")
        parent[v] = u
        children[u].append(v)
    roots = [id for id in dag.ids if parent[id] is None]
    reached = len(_preorder(roots, children))
    if reached != len(dag.ids):
        raise GraphError("not a forest: a cycle no root reaches")
    return roots, parent, children


def _preorder(roots: list, children: dict) -> list:
    """Depth-first pre-order, roots in order, children in order."""
    out, stack = [], list(reversed(roots))
    while stack:
        node = stack.pop()
        out.append(node)
        stack.extend(reversed(children[node]))
    return out


def _option(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if value < 0:
        raise GraphError(f"{name} must be >= 0, got {value}")
    return value


class _Contour:
    """A subtree's extent per relative depth: `levels` deepest first, each (lo, hi) stored
    less `delta`, so a whole subtree shifts in O(1) and is merged into a longer one in
    O(the shorter's depth)."""

    __slots__ = ("levels", "delta")

    def __init__(self, levels: list, delta: int) -> None:
        self.levels = levels
        self.delta = delta

    def at(self, k: int) -> tuple:
        """(lo, hi) at relative depth k (0 the subtree's root level)."""
        lo, hi = self.levels[len(self.levels) - 1 - k]
        return lo + self.delta, hi + self.delta

    def absorb(self, other: "_Contour", offset: int) -> "_Contour":
        """This contour merged with `other` moved by `offset`: the longer list is reused."""
        other.delta += offset
        base, extra = (self, other) if len(self.levels) >= len(other.levels) else (other, self)
        for k in range(len(extra.levels)):
            lo, hi = base.at(k)
            elo, ehi = extra.at(k)
            base.levels[len(base.levels) - 1 - k] = (min(lo, elo) - base.delta, max(hi, ehi) - base.delta)
        return base


def _pack(contours: list, gap: int) -> tuple:
    """Siblings' subtrees packed left to right: their offsets and the merged contour."""
    offsets, merged = [], None
    for contour in contours:
        if merged is None:
            offsets.append(0)
            merged = contour
            continue
        shared = min(len(merged.levels), len(contour.levels))
        offset = max(merged.at(k)[1] + gap - contour.at(k)[0] for k in range(shared))
        offsets.append(offset)
        merged = merged.absorb(contour, offset)
    return offsets, merged


def _centre(x: int, width: int) -> int:
    return x + (width - 1) // 2


def _subtrees(order: list, children: dict, width: dict, gap: int) -> tuple:
    """Each subtree's contour and each child's x relative to its parent, laid bottom up."""
    contour, rel = {}, {}
    for u in reversed(order):
        kids = children[u]
        if not kids:
            contour[u] = _Contour([(0, width[u])], 0)
            continue
        offsets, merged = _pack([contour.pop(c) for c in kids], gap)
        first, last = kids[0], kids[-1]
        x = (_centre(offsets[0], width[first]) + _centre(offsets[-1], width[last])) // 2 \
            - (width[u] - 1) // 2
        for c, offset in zip(kids, offsets):
            rel[c] = offset - x
        merged.delta -= x
        merged.levels.append((-merged.delta, width[u] - merged.delta))
        contour[u] = merged
    return contour, rel


def tidy(dag: Dag, *, gap: int = 2, rank_gap: int = 1) -> Tidy:
    """The forest top-down: Reingold-Tilford packing, parents centred over their children."""
    roots, parent, children = _forest(dag)
    gap = _option(gap, "gap")
    rank_gap = _option(rank_gap, "rank_gap")
    order = _preorder(roots, children)
    width = {n.id: n.width for n in dag.nodes}
    depth = {}
    for id in order:
        depth[id] = 0 if parent[id] is None else depth[parent[id]] + 1
    tall = {}
    for n in dag.nodes:
        tall[depth[n.id]] = max(tall.get(depth[n.id], 0), n.height)
    row_y = []
    for k in range(len(tall)):
        row_y.append(0 if k == 0 else row_y[-1] + tall[k - 1] + rank_gap)
    contour, rel = _subtrees(order, children, width, gap)
    root_at, _ = _pack([contour[r] for r in roots], gap)
    x = dict(zip(roots, root_at))
    for id in order:
        if parent[id] is not None:
            x[id] = x[parent[id]] + rel[id]
    least = min(x.values(), default=0)
    rects = {n.id: Rect(x[n.id] - least, row_y[depth[n.id]], n.width, n.height) for n in dag.nodes}
    return Tidy(dag, rects, {id: depth[id] for id in dag.ids}, parent,
                max((r.right for r in rects.values()), default=0),
                max((r.bottom for r in rects.values()), default=0))


_CONTINUED = {"guide.branch": "guide.vert", "guide.last": None, "guide.vert": "guide.vert", None: None}


def indent(dag: Dag) -> tuple:
    """The forest as indented rows in pre-order, each with its guide tokens."""
    roots, parent, children = _forest(dag)
    guides = {}
    rows = []
    for id in _preorder(roots, children):
        up = parent[id]
        if up is None:
            guides[id] = ()
        else:
            last = children[up][-1] == id
            guides[id] = tuple(_CONTINUED[g] for g in guides[up]) + ("guide.last" if last else "guide.branch",)
        rows.append(Indent(id, len(guides[id]), guides[id]))
    return tuple(rows)


def prefix(row: Indent, charset: object) -> str:
    """The row's guides as text, three cells per token, glyphs from `charset`."""
    if not isinstance(row, Indent):
        raise TypeError(f"expected an Indent, got {type(row).__name__}")
    parts = []
    for token in row.guides:
        if token in ("guide.branch", "guide.last"):
            parts.append(charset.glyph(token) + charset.glyph("guide.stem") + " ")
        elif token == "guide.vert":
            parts.append(charset.glyph("guide.vert") + "  ")
        else:
            parts.append("   ")
    return "".join(parts)
