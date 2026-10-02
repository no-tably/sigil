"""
view_graph.py — the graph view of view.py: a Sigil document drawn as boxes and
edges.

Not a command: view.py loads it. The layered layout (cycle breaking,
longest-path layering, barycenter ordering, block-merged x placement, one track
per fan-out) and its drawing, chips on edges, control-block frames, `:=`
expansions and `--- section ---`s as stacked sections, triggers, notes and the
graph legend. compose() returns the rows view.py prints. What is wired to what,
in which colour, and where an event is drawn comes from the Scene (scene.py);
this module only lays it out. Drawing primitives and styles come from
viewkit.py (read as kit.NAME, so a theme change reaches them).
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional


_HERE = Path(__file__).resolve().parent


def _sibling(name: str, fname: str):
    """The module fname beside this file, loaded by path once per directory and then
    shared: the view modules of one directory read the one viewkit, so a theme
    applied through any of them (apply_theme rebinds viewkit's style globals)
    reaches them all, while a view.py loaded from another directory (a packaged
    copy) gets modules, theme and dialect state of its own. The cache key names
    the directory, never the bare name. view.py, view_graph.py, view_tree.py and
    scene.py each carry a copy of this function: keep the copies identical."""
    key = f"{name}@{_HERE}"
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, _HERE / fname)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod   # dataclasses resolve string annotations via sys.modules
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            del sys.modules[key]
            raise
    return sys.modules[key]


kit = _sibling("sigil_viewkit", "viewkit.py")
scene = _sibling("sigil_scene", "scene.py")


# ---------------------------------------------------------------------------
# Layout — layered, top-down: _prepare → _layer → _order → _place_x → _ports →
# _route → _draw, each phase filling in more of a _Layout.
# ---------------------------------------------------------------------------

BOX_H = 3
NODE_GAP = 3
ISOLATED_WRAP = 100   # wrap width for the unconnected-node grid
ORDER_SWEEPS = 6      # barycenter ordering: down + up sweeps
PLACE_SWEEPS = 8      # x placement: alternating down / up sweeps


@dataclass
class _V:
    id: str
    w: int
    dummy: bool = False
    layer: int = 0
    x: int = 0
    ins: list = field(default_factory=list)
    outs: list = field(default_factory=list)
    pw: int = 0                                     # a join bar: its width (its ports' span)


@dataclass
class _Layout:
    """A graph part-way through layout."""
    g: object
    labels: dict                                    # node id → box label
    edges: list                                     # distinct, non-self edges
    ids: list                                       # linked node ids, document order
    isolated: list                                  # unconnected node ids
    V: dict = field(default_factory=dict)           # vertex id → _V (dummies too)
    chains: list = field(default_factory=list)      # (edge, reversed, [vertex ids top → bottom])
    layers: list = field(default_factory=list)      # per layer: vertex ids, left → right
    out_port: dict = field(default_factory=dict)    # u → {w: x where u → w leaves u}
    in_port: dict = field(default_factory=dict)     # w → {u: x where u → w enters w}
    tracks: list = field(default_factory=list)      # per gap: ({(u, w): track}, n tracks)
    top: list = field(default_factory=list)         # per layer: its y
    tags: dict = field(default_factory=dict)        # node id / (src, dst, kind) → tag runs
    styles: dict = field(default_factory=dict)      # (src, dst, kind) → its wire's style
    # Parallel edges between one pair (`?>` beside `->`): (chain, segment) → its
    # rank k >= 1 among them, and the channel track it jogs on (its own).
    dup: dict = field(default_factory=dict)
    dup_track: dict = field(default_factory=dict)

    def centre(self, vid):
        v = self.V[vid]
        return v.x + (v.pw or v.w) // 2

    def kind(self, vid) -> str:
        return "" if self.V[vid].dummy else self.g.nodes[vid].kind


@dataclass
class _Block:
    """Row nodes merged to sit side by side, centred on their mean wanted x."""
    first: int                                      # the row index of its first node
    width: int
    want: float                                     # Σ (wanted left x − offset in block)
    count: int
    offsets: list                                   # each node's x offset in the block

    def left(self) -> int:
        return round(self.want / self.count)


def _break_cycles(ids, succ):
    """DFS in document order; return the set of back edges (reversed for layering)."""
    state, back = {}, set()
    for root in ids:
        if root in state:
            continue
        stack = [(root, iter(succ[root]))]
        state[root] = 1
        while stack:
            v, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                state[v] = 2
                stack.pop()
            elif state.get(nxt) == 1:
                back.add((v, nxt))
            elif nxt not in state:
                state[nxt] = 1
                stack.append((nxt, iter(succ[nxt])))
    return back


def layout(g, expanded: set, collapsed: set, tags: dict | None = None,
           styles: dict | None = None) -> kit.Canvas:
    """g drawn as boxes and edges. `tags`: runs after a box's label (node id) or
    beside an edge's head (its wire key); `styles`: each wire key's stroke style
    (_wire_styles), an edge without one drawn in its arrow's style."""
    lay = _prepare(g, expanded, collapsed, tags, styles)
    _layer(lay)
    _order(lay)
    _place_x(lay)
    _ports(lay)
    _route(lay)
    return _draw(lay)


def _prepare(g, expanded, collapsed, tags, styles) -> _Layout:
    """Box labels (with #N tags, ▾ / ▸ and ↺ marks), the distinct edges, and the
    nodes no edge touches."""
    labels = {}
    for nid in g.nodes:
        lab = kit.node_label(g.nodes[nid])
        if tags and nid in tags:
            lab += "".join(text for text, _style in tags[nid])
        if nid in expanded:
            lab += " ▾"
        elif nid in collapsed:
            lab += " ▸"
        labels[nid] = lab

    # Distinct, non-self edges (a self-loop is marked on the node instead).
    seen, edges = set(), []
    for e in g.edges:
        if e.src == e.dst:
            labels[e.src] = labels[e.src] + " ↺"
            continue
        key = (e.src, e.dst, e.kind)
        if key not in seen and e.src in g.nodes and e.dst in g.nodes:
            seen.add(key)
            edges.append(e)

    # Unconnected nodes skip layering (they would all pile into one very wide top
    # row) and are drawn as a wrapped grid under the graph.
    linked = {e.src for e in edges} | {e.dst for e in edges}
    return _Layout(g, labels, edges, ids=[i for i in g.nodes if i in linked],
                   isolated=[i for i in g.nodes if i not in linked], tags=tags or {},
                   styles=styles or {})


def _layer(lay: _Layout) -> None:
    """Break cycles, assign longest-path layers, and split long edges with 1-wide
    dummies so every segment spans one layer gap."""
    ids, V = lay.ids, lay.V
    succ = {i: [] for i in ids}
    for e in lay.edges:
        succ[e.src].append(e.dst)
    back = _break_cycles(ids, succ)

    # DAG orientation: each edge as (top, bottom, edge, reversed?)
    dag = []
    for e in lay.edges:
        if (e.src, e.dst) in back:
            dag.append((e.dst, e.src, e, True))
        else:
            dag.append((e.src, e.dst, e, False))

    # Longest-path layering (Kahn order). A join bar is as wide as its ports need,
    # its label beside it.
    deg_in, deg_out = {i: 0 for i in ids}, {i: 0 for i in ids}
    for e in lay.edges:
        deg_out[e.src] += 1
        deg_in[e.dst] += 1
    for i in ids:
        if lay.g.nodes[i].kind == kit.JOIN:
            pw = max(2 * max(deg_in[i], deg_out[i]) + 1, 5)
            V[i] = _V(i, pw + 1 + len(lay.labels[i]), pw=pw)
        else:
            V[i] = _V(i, len(lay.labels[i]) + 4)
    indeg = {i: 0 for i in ids}
    down = {i: [] for i in ids}
    for a, b, _, _ in dag:
        down[a].append(b)
        indeg[b] += 1
    queue = [i for i in ids if indeg[i] == 0]
    while queue:
        v = queue.pop(0)
        for b in down[v]:
            V[b].layer = max(V[b].layer, V[v].layer + 1)
            indeg[b] -= 1
            if indeg[b] == 0:
                queue.append(b)

    n_dummy = 0
    for a, b, e, rev in dag:
        chain = [a]
        for layer in range(V[a].layer + 1, V[b].layer):
            n_dummy += 1
            did = f"\0d{n_dummy}"
            V[did] = _V(did, 1, dummy=True, layer=layer)
            chain.append(did)
        chain.append(b)
        for u, w in zip(chain, chain[1:]):
            V[u].outs.append(w)
            V[w].ins.append(u)
        lay.chains.append((e, rev, chain))

    # Edges of different kinds between one pair keep a stroke each: every one
    # after the first is offset (its own ports and track) instead of drawn over it.
    seen = {}
    for ci, (_e, rev, chain) in enumerate(lay.chains):
        for si, (u, w) in enumerate(zip(chain, chain[1:])):
            k = seen.get((u, w, rev), 0)
            if k:
                lay.dup[(ci, si)] = k
            seen[(u, w, rev)] = k + 1

    nlayers = max((v.layer for v in V.values()), default=0) + 1
    lay.layers = [[] for _ in range(nlayers)]
    for vid, v in V.items():          # document order, dummies after
        lay.layers[v.layer].append(vid)


def _order(lay: _Layout) -> None:
    """Barycenter ordering sweeps: down orders each layer by its parents, up by
    its children."""
    V, layers = lay.V, lay.layers
    nlayers = len(layers)
    pos = {vid: i for row in layers for i, vid in enumerate(row)}

    def barycenter(vid, ref):
        nb = getattr(V[vid], ref)
        return sum(pos[n] for n in nb) / len(nb) if nb else pos[vid]

    sweep = [(i, "ins") for i in range(1, nlayers)] + \
            [(i, "outs") for i in range(nlayers - 2, -1, -1)]
    for _ in range(ORDER_SWEEPS):
        for i, ref in sweep:
            row = layers[i]
            row.sort(key=lambda vid, _ref=ref: barycenter(vid, _ref))
            pos.update((vid, k) for k, vid in enumerate(row))   # only this row moved


def _place_x(lay: _Layout) -> None:
    """Pack each layer, then pull each node toward the mean of its neighbours'
    centres (never overlapping its left neighbour), a few sweeps each way."""
    V, layers = lay.V, lay.layers
    for row in layers:
        x = 0
        for vid in row:
            V[vid].x = x
            x += V[vid].w + NODE_GAP

    for sweep in range(PLACE_SWEEPS):
        order = range(len(layers)) if sweep % 2 == 0 else range(len(layers) - 1, -1, -1)
        for i in order:
            row = layers[i]
            want = []
            for vid in row:
                nb = V[vid].ins + V[vid].outs
                want.append(sum(lay.centre(n) for n in nb) / len(nb) - V[vid].w // 2
                            if nb else V[vid].x)
            _place(V, row, want)
    minx = min((v.x for v in V.values()), default=0)
    for v in V.values():
        v.x -= minx


def _place(V, row, want):
    """Put each node as near its wanted left x as spacing allows: overlapping
    neighbours merge into a block centred on their mean want (so siblings
    spread evenly under a shared parent instead of drifting right)."""
    blocks = []
    for k, vid in enumerate(row):
        blocks.append(_Block(k, V[vid].w, want[k], 1, [0]))
        while len(blocks) > 1:
            b, c = blocks[-2], blocks[-1]
            if b.left() + b.width + NODE_GAP <= c.left():
                break
            shift = b.width + NODE_GAP
            b.offsets += [o + shift for o in c.offsets]
            b.want += c.want - shift * c.count
            b.count += c.count
            b.width += NODE_GAP + c.width
            blocks.pop()
    for b in blocks:
        left = b.left()
        for j, off in enumerate(b.offsets):
            V[row[b.first + j]].x = left + off


def _ports(lay: _Layout) -> None:
    """Where each segment leaves its upper vertex and enters its lower one."""
    V, centre = lay.V, lay.centre

    # Incoming edges spread across the box width so each arrowhead is distinct.
    def spread(vid, nbrs):
        v = V[vid]
        if v.dummy or len(nbrs) <= 1:
            return {n: centre(vid) for n in nbrs}
        inner = max((v.pw or v.w) - 2, 1)
        srt = sorted(nbrs, key=centre)
        return {n: v.x + 1 + (k * (inner - 1)) // max(len(srt) - 1, 1)
                for k, n in enumerate(srt)}

    def in_ports(vid):
        return spread(vid, V[vid].ins)

    # Outgoing edges leave from the box centre (a fan-out draws as one ┬ tree); a
    # back edge (drawn upward) gets its own out-port right of centre, so it never
    # merges into the node's forward fan-out tree.
    back_seg = {(ch[0], ch[1]) for _, rev, ch in lay.chains if rev}

    def out_ports(vid):
        outs = V[vid].outs
        if lay.kind(vid) == kit.JOIN:                 # a fork: each branch leaves the bar
            return spread(vid, outs)
        fwd = [n for n in outs if (vid, n) not in back_seg]
        bk = sorted((n for n in outs if (vid, n) in back_seg), key=centre)
        res = {n: centre(vid) for n in fwd}
        if bk and not V[vid].dummy:
            right = V[vid].x + V[vid].w - 2
            for k, n in enumerate(bk):
                res[n] = min(centre(vid) + (0 if not fwd and k == 0 else 2 * (k + 1)), right)
        else:
            res.update({n: centre(vid) for n in bk})
        return res

    out_port = lay.out_port = {vid: out_ports(vid) for vid in V}
    in_port = lay.in_port = {vid: in_ports(vid) for vid in V}

    # Straighten: a lone edge whose far port lies within this box's width drops
    # straight down instead of jogging a column or two sideways.
    def inside(vid, x):
        v = V[vid]
        return not v.dummy and v.x + 1 <= x <= v.x + (v.pw or v.w) - 2

    for u in V:
        for w in V[u].outs:
            sx, dx = out_port[u][w], in_port[w][u]
            if sx == dx:
                continue
            if len(V[u].outs) == 1 and inside(u, dx):
                out_port[u][w] = dx
            elif len(V[w].ins) == 1 and inside(w, sx):
                in_port[w][u] = sx


def _route(lay: _Layout) -> None:
    """Channel between layer i and i+1: one track per source port with a jog;
    then each layer's y."""
    V, layers = lay.V, lay.layers
    for i in range(len(layers) - 1):
        groups = {}
        for u in layers[i]:
            for w in V[u].outs:
                sx, dx = lay.out_port[u][w], lay.in_port[w][u]
                if sx != dx:
                    groups.setdefault(sx, []).append((u, w, min(sx, dx), max(sx, dx)))
        spans = sorted(((min(s[2] for s in segs), max(s[3] for s in segs), segs)
                        for segs in groups.values()), key=lambda t: t[0])
        cols, assign = [], {}
        for lo, hi, segs in spans:
            t = kit._first_fit(cols, lo, hi)
            for u, w, _, _ in segs:
                assign[(u, w)] = t
        extra = 0
        for (ci, si) in sorted(lay.dup):          # an offset parallel edge: its own track
            if V[lay.chains[ci][2][si]].layer == i:
                lay.dup_track[(ci, si)] = len(cols) + extra
                extra += 1
        lay.tracks.append((assign, len(cols) + extra))

    y = 0
    for i in range(len(layers)):
        lay.top.append(y)
        y += BOX_H
        if i < len(layers) - 1:
            y += lay.tracks[i][1] + 2


def _head(kind: str, up: bool = False) -> str:
    """An arrowhead: ✖ for `!>` (an error reads without colour), a permission
    edge's access letter (r / w / b), else ▼ / ▲."""
    if kind == "!>":
        return "✖"
    if kind.startswith("access:"):
        return kind[-1]
    return "▲" if up else "▼"


def _free_port(v, x: int, k: int, used: set) -> int:
    """A port near x on vertex v for the k-th parallel edge: off the ports in use."""
    lo, hi = v.x + 1, v.x + (v.pw or v.w) - 2
    for d in (2 * k, -2 * k, 2 * k + 1, -2 * k - 1, k, -k):
        if lo <= x + d <= hi and x + d not in used:
            return x + d
    return min(max(x + k, lo), hi)


def _draw(lay: _Layout) -> kit.Canvas:
    """Edges, then boxes over them, then edge labels where they fit, then the
    grid of unconnected nodes."""
    V, top, g = lay.V, lay.top, lay.g
    cv = kit.Canvas()

    def is_join(vid):
        return lay.kind(vid) == kit.JOIN

    # Edges first (boxes overwrite line cells they touch).
    heads = []
    edge_labels = []   # (x, y, runs) beside an arrowhead
    bar_style = {}     # join bar → the style of the edges it joins
    traces = []        # per chain: _Trace, for the shared-cell colour rule
    for ci, (e, rev, chain) in enumerate(lay.chains):
        key = _wire_key(g, e)
        style = lay.styles.get(key) or kit.edge_style(e.kind)
        trace = _Trace(style, rev, e.kind == "<->")
        traces.append(trace)

        def path(pts):
            cv.path(pts, e.kind, style)
            trace.cells += _cells(pts)

        for k, (u, w) in enumerate(zip(chain, chain[1:])):
            i = V[u].layer
            assign, _n = lay.tracks[i]
            sx, dx = lay.out_port[u][w], lay.in_port[w][u]
            ty = top[i] + BOX_H + 1 + assign.get((u, w), 0)
            if (ci, k) in lay.dup:                  # a parallel edge: offset ports, own track
                n = lay.dup[(ci, k)]
                if not V[u].dummy:
                    sx = _free_port(V[u], sx, n, set(lay.out_port[u].values()))
                if not V[w].dummy:
                    dx = _free_port(V[w], dx, n, set(lay.in_port[w].values()))
                ty = top[i] + BOX_H + 1 + lay.dup_track[(ci, k)]
            y0 = top[i] + BOX_H if not V[u].dummy else top[i]
            y1 = top[i + 1] - 1 if not V[w].dummy else top[i + 1]
            if is_join(u):                          # lines meet a join bar on its middle row
                y0 = top[i] + 1
                bar_style.setdefault(u, (style, e.kind))
            if is_join(w):
                y1 = top[i + 1] + 1
                bar_style.setdefault(w, (style, e.kind))
            if V[u].dummy:
                path([(sx, top[i]), (sx, top[i] + BOX_H)])
                y0 = top[i] + BOX_H
            pts = [(sx, y0), (sx, ty), (dx, ty), (dx, y1)] if sx != dx else [(sx, y0), (dx, y1)]
            path(pts)
            if V[w].dummy:
                path([(dx, top[i + 1]), (dx, top[i + 1] + BOX_H - 1)])
            last = k == len(chain) - 2
            first = k == 0
            # Arrowheads at the LOGICAL destination (and both ends for <->).
            if e.label and ((last and not rev) or (first and rev)):
                edge_labels.append((dx, y1, [(e.label, kit.LABEL_STYLE)]) if not rev
                                   else (sx, y0, [(e.label, kit.LABEL_STYLE)]))
            # The tag of this flow's wire (an inline note, a landed event's name)
            # sits beside its head: a chip remembers the wire it splits, so the
            # tag follows into the chip half.
            runs = lay.tags.get(key)
            if runs and last and not rev and e.dst == key[1]:
                edge_labels.append((dx, y1, runs))
            elif runs and first and rev and e.src == key[0]:
                edge_labels.append((sx, y0, runs))
            into_chip = g.nodes[chain[-1]].kind in (kit.CHIP, kit.JOIN) if not rev else False
            if last and not rev and not into_chip:
                heads.append((dx, y1, _head(e.kind), style))
            if first and rev and g.nodes[chain[0]].kind != kit.JOIN:
                heads.append((sx, y0, _head(e.kind, up=True), style))
            if e.kind == "<->":
                if first and not rev:
                    heads.append((sx, y0, "▲", style))
                if last and rev:
                    heads.append((dx, y1, "▼", style))
    for cell, st in _nearest_owners(traces, cv.lines).items():
        cv.lines[cell][2] = st
    for x, y, ch, st in heads:
        cv.put(x, y, ch, st)

    for vid, v in V.items():
        if v.dummy:
            continue
        if is_join(vid):
            _draw_join(cv, v, top[v.layer], lay.labels[vid], set(lay.in_port[vid].values()),
                       set(lay.out_port[vid].values()), *bar_style.get(vid, (None, "->")))
            continue
        _draw_box(cv, v.x, top[v.layer], v.w, lay.labels[vid], g.nodes[vid])
        _colour_tags(cv, v.x, top[v.layer], g.nodes[vid], lay.tags.get(vid))

    # Edge labels (e.g. state-machine triggers) beside their arrowhead, right side
    # first, then left; skipped where they would overwrite anything.
    def free(x0, y, n):
        return x0 >= 0 and all((x, y) not in cv.text and (x, y) not in cv.lines
                               for x in range(x0 - 1, x0 + n + 1))

    for x, y, runs in edge_labels:
        n = kit.row_len(runs)
        for x0 in (x + 2, x - 1 - n):
            if free(x0, y, n):
                kit._put_runs(cv, x0, y, runs)
                break

    if lay.isolated:
        wrap = max(cv.w, ISOLATED_WRAP)
        x, y = 0, cv.h + 1 if cv.h else 0
        for vid in lay.isolated:
            w = len(lay.labels[vid]) + 4
            if x and x + w > wrap:
                x, y = 0, y + BOX_H
            _draw_box(cv, x, y, w, lay.labels[vid], g.nodes[vid])
            x += w + 1
    return cv


@dataclass
class _Trace:
    """The cells one drawn chain passes through, in drawing order, with its
    style, whether it is drawn reversed (its head at the start) and whether it
    is a `<->` (a head at both ends)."""
    style: object
    rev: bool
    both: bool
    cells: list = field(default_factory=list)

    def to_head(self, cell) -> int:
        """How many cells from `cell` (its first pass) to this chain's nearest head."""
        i = self.cells.index(cell)
        ahead, behind = len(self.cells) - 1 - i, i
        if self.both:
            return min(ahead, behind)
        return behind if self.rev else ahead

    def runs(self) -> dict:
        """{cell: the set of directions (dx, dy) the chain leaves it by}."""
        out = {cell: set() for cell in self.cells}
        for (ax, ay), (bx, by) in zip(self.cells, self.cells[1:]):
            if abs(bx - ax) + abs(by - ay) == 1:
                out[(ax, ay)].add((bx - ax, by - ay))
                out[(bx, by)].add((ax - bx, ay - by))
        return out


def _cells(pts) -> list:
    """The cells a polyline through pts passes, in order, each once."""
    out = [pts[0]]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        dx, dy = (x2 > x1) - (x2 < x1), (y2 > y1) - (y2 < y1)
        x, y = x1, y1
        while (x, y) != (x2, y2):
            x, y = x + dx, y + dy
            out.append((x, y))
    return out


def _nearest_owners(traces: list, lines: dict) -> dict:
    """{cell: style} for the line cells whose style changes under the colour
    policy's shared-cell rule: of the chains that share a run through a cell
    (leave it the same way as the chain whose style it has; a chain merely
    crossing it does not), the one nearest its own head owns it — on a tie the
    earlier chain. Style only: the cell's stroke (its glyph) stays."""
    seen = {}                                   # cell → [(distance, dirs, style)]
    for tr in traces:
        for cell, dirs in tr.runs().items():
            if cell in lines:
                seen.setdefault(cell, []).append((tr.to_head(cell), dirs, tr.style))
    out = {}
    for cell, chains in seen.items():
        cur = lines[cell][2]
        ref = next((dirs for _d, dirs, st in chains if st == cur), chains[0][1])
        sharing = [(d, st) for d, dirs, st in chains if dirs & ref]
        _d, st = min(sharing, key=lambda c: c[0])
        if st != cur:
            out[cell] = st
    return out


def _wire_key(g, e) -> tuple:
    """The key (src, dst, kind) of the wire a drawn edge belongs to: a chip, join
    bar or branch decision standing in for an end names the end it stands for
    (its attrs["key"], the key of the first wire through it)."""
    def end(nid, side):
        n = g.nodes.get(nid)
        stands = (n.attrs.get("key") if n is not None
                  and n.kind in (kit.CHIP, kit.JOIN, kit.DECISION) else None)
        return stands[side] if stands and stands[side] is not None else nid
    return (end(e.src, 0), end(e.dst, 1), e.kind)


def _draw_join(cv: kit.Canvas, v, y, label, ins: set, outs: set, style, kind):
    """A join bar on its middle row: ━ with a junction where each joined edge
    meets it (┷ in, ┯ out, ┿ both; ┻ ┳ ╋ for heavy `=>` edges), its label after."""
    heavy = kit._stroke(kind) == "heavy"
    marks = {(True, True): "╋" if heavy else "┿", (True, False): "┻" if heavy else "┷",
             (False, True): "┳" if heavy else "┯", (False, False): "━"}
    bar = "".join(marks[(x in ins, x in outs)] for x in range(v.x, v.x + v.pw))
    cv.put(v.x, y + 1, bar, style)
    cv.put(v.x + v.pw + 1, y + 1, label, kit.LABEL_STYLE)


def _colour_tags(cv: kit.Canvas, x, y, n, runs):
    """Re-colour a box's #N note tags (drawn in the label's colour) by note kind."""
    if not runs:
        return
    tx = x + 2 + len(kit.node_label(n))
    for text, style in runs:
        if style:
            cv.put(tx, y + 1, text, style)
        tx += len(text)


def _draw_box(cv: kit.Canvas, x, y, w, label, n):
    if n.kind == kit.DECISION:                      # a branch's choice: ╱──╲ ◇ … ╲──╱
        tl, tr, bl, br, h, s = "╱", "╲", "╲", "╱", "─", "│"
    elif n.kind == kit.CHIP:
        tl, tr, bl, br, h, s = "╭", "╮", "╰", "╯", "┄", "┆"
    elif n.is_hole:
        tl, tr, bl, br, h, s = "┌", "┐", "└", "┘", "┄", "┆"
    elif n.is_mutable:
        tl, tr, bl, br, h, s = "┏", "┓", "┗", "┛", "━", "┃"
    elif kit.KINDS.get(n.kind, {}).get("border") == "double":
        tl, tr, bl, br, h, s = "╔", "╗", "╚", "╝", "═", "║"
    elif kit.KINDS.get(n.kind, {}).get("border") == "round":
        tl, tr, bl, br, h, s = "╭", "╮", "╰", "╯", "─", "│"
    else:
        tl, tr, bl, br, h, s = "┌", "┐", "└", "┘", "─", "│"
    border, text = kit.node_styles(n)
    cv.put(x, y, tl + h * (w - 2) + tr, border)
    cv.put(x, y + 1, s + " ", border)
    cv.put(x + 2, y + 1, label.ljust(w - 4), text)
    if n.kind == kit.CHIP:                          # a payload reads as the code it is
        kit._put_runs(cv, x + 2, y + 1, kit.chip_runs(n))
    else:                                       # brackets in colour, name off-white
        kit._put_runs(cv, x + 2, y + 1, kit.label_runs(n, bg=text[1]))
    cv.put(x + w - 2, y + 1, " " + s, border)
    cv.put(x, y + 2, bl + h * (w - 2) + br, border)


def with_chips(g, payloads: bool = False, scn=None, marks: list | None = None,
               mods: bool = False):
    """The graph as the graph view draws it: each `: payload` as a chip splitting
    its edge (src → chip → dst), then — with `scn`, the document's Scene — what
    drives a machine here as an edge ⇢ its owner (scene.trigger_edges; not in a
    state machine, whose drivers scene.with_trigger_sources wires to the states
    they enter) and the permission edges
    principal → store (scene.access_edges) of g.access (graph_parts gives each
    part its own). Returns g itself when there is nothing to add. With `marks`
    (a list), each chip shows only a marker letter and the payload is appended
    to marks as (letter, payload) — for a panel beside the drawing. Joined
    endpoints (`&` `&?` `/`) fork from / meet at a join bar; `mods` adds an
    edge's modifiers to its chip. A chip or join bar names the wire it stands
    in for (attrs["key"], see _wire_key)."""
    extra = []
    if scn is not None:
        own = {(a.principal, a.store, kit.access_kind(a)) for a in getattr(g, "access", None) or []}
        drives = scene.trigger_edges(scn, g.nodes) if g.role != "state" else []
        extra = (drives + [e for e in scene.access_edges(scn, g.nodes) if (e.src, e.dst, e.kind) in own])
    chips = [any(kit.chip_parts(e, payloads, mods)) for e in g.edges]
    joined = any(kit.drawn_join(g, e, "src") is not None or kit.drawn_join(g, e, "dst") is not None
                 for e in g.edges)
    if not extra and not joined and not any(chips):
        return g
    nodes, edges = dict(g.nodes), []
    finals = set()                              # a final segment shared through a join

    def join_node(idx, e):
        jid = f"\0j{idx}"
        if jid not in nodes:
            nodes[jid] = kit.render.Node(id=jid, name=g.joins[idx].kind, kind=kit.JOIN,
                                         attrs={"key": e.key})
        return jid

    for k, e in enumerate(g.edges):
        src = e.src
        sj, dj = kit.drawn_join(g, e, "src"), kit.drawn_join(g, e, "dst")
        if sj is not None:
            jid = join_node(sj, e)
            edges.append(replace(e, dst=jid, label=None, payload=None, mods=[]))
            src = jid
        if dj is not None:
            jid = join_node(dj, e)
            edges.append(replace(e, src=src, dst=jid, label=None, payload=None, mods=[]))
            src = jid
        if src != e.src and (src, e.dst, e.kind) in finals:
            continue                            # this joined segment is drawn already
        if src != e.src:
            finals.add((src, e.dst, e.kind))
        payload, mtext = kit.chip_parts(e, payloads, mods)
        if (payload or mtext) and e.src != e.dst:
            cid = f"\0p{k}"
            name = kit.chip_text(payload, mtext)
            attrs = {"key": e.key, "payload": payload, "mods": mtext}
            if marks is not None:
                letter = kit._letter(len(marks))
                marks.append((letter, name))
                name, attrs = letter, {"key": e.key}
            nodes[cid] = kit.render.Node(id=cid, name=name, kind=kit.CHIP, attrs=attrs)
            edges += [replace(e, src=src, dst=cid, label=None, payload=None),
                      replace(e, src=cid, payload=None)]
        else:
            edges.append(replace(e, src=src) if src != e.src else e)
    return replace(g, nodes=nodes, edges=edges + extra)


@dataclass
class _Part:
    """One drawing part of a graph: its title, the sub-graph of its free flows
    (and unconnected nodes), and the control blocks drawn as frames under it."""
    title: str
    graph: object
    blocks: list


def graph_parts(g, top: bool = True, drivers: dict | None = None,
                access: bool = False) -> list:
    """The graph split for drawing. Flows inside a control block are drawn in
    that block's frame, not in the main layout. A top-level graph with `---`
    sections is split by them: each flow goes to the section its line is in,
    each node to every section that draws it (an unconnected node: the section
    it is first written in), each block to the section of its header.
    `drivers` ({machine id: [node id]}, _drivers): what drives a machine joins
    each part its machine is in; `access`: each of g's permissions goes, with
    its principal and store, to the part of its line (the part graph's access)."""
    eb = kit.edge_blocks(g)
    blocks = getattr(g, "blocks", None) or []
    secs = (getattr(g, "sections", None) or []) if top else []
    est = kit.node_lines(g) if secs else {}
    in_block = set()
    for k, bi in eb.items():
        in_block |= {g.edges[k].src, g.edges[k].dst}
    for b in blocks:
        in_block |= set(b.members) | set(b.refs)
    free = [k for k in range(len(g.edges)) if k not in eb]
    linked = {g.edges[k].src for k in free} | {g.edges[k].dst for k in free}
    groups = {}                                 # section index → [edges, nodes, blocks, access]

    def grp(i):
        return groups.setdefault(i, [[], set(), [], []])

    for k in free:
        e = g.edges[k]
        i = kit.section_of(secs, e.line or est.get(e.src, 0))
        grp(i)[0].append(e)
        grp(i)[1] |= {e.src, e.dst}
    for nid in g.nodes:
        if nid not in linked and nid not in in_block:
            grp(kit.section_of(secs, est.get(nid, 0)))[1].add(nid)
    for bi, b in enumerate(blocks):
        if b.parent is None:
            grp(kit.section_of(secs, b.lines[0]))[2].append(bi)
    for a in (getattr(g, "access", None) or []) if access else ():
        if a.principal in g.nodes and a.store in g.nodes:
            i = kit.section_of(secs, a.line or est.get(a.store, 0))
            grp(i)[1] |= {a.principal, a.store}
            grp(i)[3].append(a)
    parts = []
    for i in sorted(groups):
        edges, nodes, bis, acc = groups[i]
        nodes |= {src for m, srcs in (drivers or {}).items() if m in nodes
                  for src in srcs if src in g.nodes}
        sub = replace(g, nodes={nid: n for nid, n in g.nodes.items() if nid in nodes},
                      edges=edges, access=acc)
        title = kit.Rule(kit.section_name(secs[i])) if i >= 0 else ""
        parts.append(_Part(title, sub, bis))
    if not parts:
        parts.append(_Part("", replace(g, nodes={}, edges=[], access=[]), []))
    return parts


def _frame_content(g, bi: int, eb: dict, draw) -> "kit.Canvas":
    """What a block's frame holds: its own flows laid out (a branch: a ◇ decision
    node with each arm's label chip on the way to the arm's entry), then its
    nested blocks' frames."""
    b = g.blocks[bi]
    kids = [ci for ci, c in enumerate(g.blocks) if c.parent == bi]
    nested = set()
    for ci in kids:
        nested |= set(g.blocks[ci].members)
    own = [g.edges[k] for k, owner in eb.items() if owner == bi]
    keep = {e.src for e in own} | {e.dst for e in own}
    keep |= set(b.members) - nested
    nodes = {nid: n for nid, n in g.nodes.items() if nid in keep}
    edges = list(own)
    if b.kind == "branch":
        dec = f"\0b{bi}"
        name = b.header if b.header else "branch"
        stands = {"key": (b.refs[0], None)} if b.refs else {}
        nodes = {dec: kit.render.Node(id=dec, name=name, kind=kit.DECISION, attrs=stands),
                 **nodes}
        refs = set(b.refs)
        edges = [replace(e, src=dec) if e.src in refs and e.key in b.after else e
                 for e in edges]
        for ai, (label, ids) in enumerate(b.arm_nodes):
            if not ids or ids[0] not in nodes:
                continue
            cid = f"\0a{bi}.{ai}"
            nodes[cid] = kit.render.Node(id=cid, name=label, kind=kit.CHIP, attrs={"arm": True})
            edges += [kit.render.Edge(src=dec, dst=cid, kind="arm"),
                      kit.render.Edge(src=cid, dst=ids[0], kind="arm")]
    sub = replace(g, nodes=nodes, edges=edges, blocks=[], access=[])
    own_cv = draw(sub) if nodes else kit.Canvas()
    frames = [_framed(_frame_content(g, ci, eb, draw), kit.block_title_runs(g.blocks[ci]))
              for ci in kids]
    return _stack(own_cv, frames)


def _framed(content: "kit.Canvas", title_runs: list) -> "kit.Canvas":
    """A titled frame around a drawing: ╭╌ title ╌╌╮ / ╎ … ╎ / ╰╌╌╌╯ (light dashed)."""
    tw = kit.row_len(title_runs)
    inner = max(content.w, tw + 2)
    w = inner + 4
    cv = kit.Canvas()
    cv.put(0, 0, "╭╌ ", kit.FRAME_STYLE)
    x = kit._put_runs(cv, 3, 0, title_runs)
    cv.put(x, 0, " " + "╌" * (w - 2 - x) + "╮", kit.FRAME_STYLE)
    for y in range(1, content.h + 1):
        cv.put(0, y, "╎", kit.FRAME_STYLE)
        cv.put(w - 1, y, "╎", kit.FRAME_STYLE)
    cv.blit(content, 2 + (inner - content.w) // 2, 1)
    cv.put(0, content.h + 1, "╰" + "╌" * (w - 2) + "╯", kit.FRAME_STYLE)
    return cv


FRAME_GAP = 2                                   # columns between frames in a row


def _stack(main: "kit.Canvas", frames: list) -> "kit.Canvas":
    """main, with the frames in rows under it (left to right, wrapped at the
    wider of main and ISOLATED_WRAP); main is centred over a wider frame row."""
    if not frames:
        return main
    wrap = max(main.w, ISOLATED_WRAP)
    placed, x, y, row_h, width = [], 0, 0, 0, 0
    for f in frames:
        if x and x + f.w > wrap:
            x, y, row_h = 0, y + row_h + 1, 0
        placed.append((f, x, y))
        width = max(width, x + f.w)
        x += f.w + FRAME_GAP
        row_h = max(row_h, f.h)
    out = kit.Canvas()
    out.blit(main, max(width - main.w, 0) // 2, 0)
    top = main.h + 1 if main.h else 0
    for f, fx, fy in placed:
        out.blit(f, fx, top + fy)
    return out


def sections(g, depth: int, title: str = "", level: int = 0, tags: dict | None = None,
             payloads: bool = False, scn=None, fit: int | None = None,
             marks: list | None = None, mods: bool = False, _secs=None, _level=None,
             _owner: Optional[str] = None):
    """Yield (title, graph, canvas) for the graph and its expansions up to depth.
    `scn`: the document's Scene (scene.build_scene; None: built without triggers
    or permissions) — what drives each machine draws as a dashed edge into it,
    the permission graph as dotted edges, an event it lands draws as edges
    emitter → destination, every edge in its wire's colour. `payloads` draws
    each flow's payload as a chip on its edge. With `fit` (columns) and `marks`
    (a list), a section wider than `fit` that has chips is laid out again with
    marker-letter chips — kept (and its payloads appended to marks) when that
    fits, or is at least a fifth narrower.

    A top-level graph with `--- sections ---` yields one part per section (its
    title a Rule); control blocks are drawn as titled frames under their part's
    flows. `mods` puts modifiers on chips (edges) and after labels (nodes)."""
    if scn is None:
        scn = scene.build_scene(g, triggers=False, depth=depth)
    g = _landed(g, scn, _owner)
    show = set(g.expansions) if level < depth else set()
    collapsed = set(g.expansions) - show
    eb = kit.edge_blocks(g)
    secs = (getattr(g, "sections", None) or []) if level == 0 else (_secs or [])
    chipped = (payloads or mods) and any(any(kit.chip_parts(e, payloads, mods)) and e.src != e.dst
                                         for e in g.edges)
    drivers = _drivers(scn) if g.role != "state" else None    # a machine has its own
    styles = _wire_styles(scn)

    def draw_all(part, chip_marks):
        def draw(sub):
            return layout(with_chips(sub, payloads, scn, chip_marks, mods),
                          show, collapsed, tags, styles)
        main = draw(part.graph) if part.graph.nodes else kit.Canvas()
        frames = [_framed(_frame_content(g, bi, eb, draw), kit.block_title_runs(g.blocks[bi]))
                  for bi in part.blocks]
        return _stack(main, frames)

    for part in graph_parts(g, level == 0, drivers, scn.options.access):
        cv = draw_all(part, None)
        if fit is not None and marks is not None and cv.w > fit and chipped:
            trial = list(marks)
            marked = draw_all(part, trial)
            # Worth it when that fits, or saves at least a fifth of the width.
            if marked.w < cv.w and (marked.w <= fit or marked.w * 5 <= cv.w * 4):
                cv, marks[:] = marked, trial
        yield part.title or title, part.graph, cv
    for nid in g.expansions:
        if nid in show:
            sub = g.expansions[nid]
            what = "state machine" if getattr(sub, "role", "") == "state" else ":= { … }"
            sub_title = f"{kit.node_label(g.nodes[nid])} {what}"
            lines = [e.line for cur in kit._walk(sub) for e in cur.edges if e.line]
            k = kit.section_of(secs, min(lines)) if lines else -1
            zoom = secs[k].level if k >= 0 and secs[k].level != "L1" else None
            if zoom and zoom != _level:         # the zoom level it is written at
                sub_title = f"{zoom} · {sub_title}"
            if title and not isinstance(title, kit.Rule):
                sub_title = f"{title}  ›  {sub_title}"
            if getattr(sub, "role", "") == "state":
                sub = scene.with_trigger_sources(scn, sub, nid)
            yield from sections(sub, depth, sub_title, level + 1, tags, payloads, scn,
                                fit, marks, mods, secs, zoom or _level, nid)


def _drivers(scn) -> dict:
    """{machine id: [node id]}: what drives each machine (scene.driver_wires) —
    the event of each trigger wire, the emitter of each landed event a trigger
    delivers — in wire order, each once."""
    out = {}
    for w in scene.driver_wires(scn):
        out.setdefault(w.machine, {})[w.src] = None
    return {m: list(srcs) for m, srcs in out.items()}


def _landed(g, scn, owner: Optional[str]):
    """g (the graph of the unit `owner`) as drawn with the events the Scene lands:
    their boxes and edges gone; an edge emitter → destination for each of the
    unit's emit wires a flow delivers (one per key, its legs' payloads and
    modifiers on it). What drives a machine is added by
    scene.with_trigger_sources. No landed events: g itself."""
    if not scn.collapsed:
        return g
    gone = scn.collapsed
    nodes = {nid: n for nid, n in g.nodes.items() if nid not in gone}
    edges = [e for e in g.edges if e.src not in gone and e.dst not in gone]
    flows = {w.key: w for w in scn.wires
             if w.role == "emit" and w.owner == owner and w.legs[1].role == "flow"}
    for w in flows.values():
        payload = " · ".join(leg.payload for leg in w.legs if leg.payload) or None
        edges.append(kit.render.Edge(src=w.src, dst=w.dst, kind=w.kind, payload=payload,
                                     src_path=w.paths[0], dst_path=w.paths[1],
                                     mods=[m for leg in w.legs for m in leg.mods], line=w.line))
    return replace(g, nodes=nodes, edges=edges)


def _wire_styles(scn) -> dict:
    """{wire key: stroke style} per the colour policy (scene.wire_style), the
    first wire of a key winning."""
    out = {}
    for w in scn.wires:
        out.setdefault(w.key, scene.wire_style(w))
    return out


def _landed_tags(scn) -> dict:
    """{key: runs}: each landed event's name beside the head of the edges that
    carry it, in the event colour — keyed by the emit wire, and by emitter ⇢
    machine for a trigger-delivered one (the overview's edge)."""
    names = {}
    for w in scn.wires:
        if w.role != "emit":
            continue
        keys = [w.key]
        if w.machine is not None:
            keys.append((w.src, w.machine, "trigger"))
        for key in keys:
            names.setdefault(key, {})[w.via] = None
    style = (scene.colour_of("kinds-event"), None, False)
    return {key: [(" · ".join(kit.node_label(scn.nodes[ev].node) for ev in evs), style)]
            for key, evs in names.items()}


def trigger_lines(g):
    """`<Paid> ⇢ {Order}: Open → Settled` for each event wired to a transition."""
    nodes = {}
    for cur in kit._walk(g):
        nodes.update(cur.nodes)

    def lab(nid):
        return kit.node_label(nodes[nid]) if nid in nodes else nid

    return [f"  {lab(t.event)} ⇢ {lab(t.owner)}: {lab(t.src)} → {lab(t.dst)}"
            for t in getattr(g, "triggers", [])]


def payload_lines(g):
    return [f"  {kit.edge_text(g, e)} : {e.payload}" for e in g.edges if e.payload]


def all_payload_lines(g):
    return [line for cur in kit._walk(g) for line in payload_lines(cur)]


def compose(g, depth: int, payloads: bool, notes: str = "off", triggers: bool = True,
            width: int | None = None, access: bool = False, mods: bool = False,
            events: str = "nodes"):
    """The whole drawing as rows of (text, style) runs, plus its width. Each
    section's canvas is centred within the widest section. `payloads` draws each
    flow's payload as a chip on its edge; `triggers` wires each event to the owner
    of the state machine it drives (and lists the transitions below). Notes (any
    mode but "off") tag commented boxes `#N` and list the notes below.

    `width`: the columns to fit (None: draw at the natural width). When the
    drawing is wider, it is rearranged — never squashed: block notes move to a
    panel at the top-left, inline notes to one at the bottom-right, and a
    section still too wide because of its payload chips draws each chip as a
    marker letter (┆ a ┆) with the payload beside its letter in that panel.
    Panels go into empty corners of the drawing when one is big enough.

    `--- sections ---` split the drawing into parts under divider rules; control
    blocks are titled frames under their part's flows; joined endpoints fork
    from / meet at a join bar. `access`: the permission graph (dotted edges
    principal → store headed r / w / b, a store badged `1w` / `Nw` writers).
    `mods`: modifier chips on edges (with the payload) and after node labels.
    `events`: "nodes" draws an event as a box; "land" draws a pass-through
    event where it lands — no box, each emitter → destination edge in the event
    colour with the event's name beside its head (scene.land_events). Every
    edge takes its wire's colour (the Scene's colour policy)."""
    scn = scene.build_scene(g, events=events, triggers=triggers, access=access, depth=depth)
    idx = scn.notes if notes != "off" else {}
    tags = _tags(scn, notes != "off", mods)
    parts = list(sections(g, depth, tags=tags, payloads=payloads, scn=scn, mods=mods))
    rows, drawing_w = _section_rows(parts)
    natural = rows + ([[], kit.section_rule("notes"), []] + kit.note_rows(idx) if idx else [])
    natural_w = max([drawing_w] + [kit.row_len(r) for r in natural])
    if width is None or natural_w <= width:
        return kit.stretch_rules(natural, natural_w), natural_w

    marks = []
    if (payloads or mods) and drawing_w > width:
        parts = list(sections(g, depth, tags=tags, payloads=payloads, scn=scn,
                              fit=width, marks=marks, mods=mods))
        rows, _w = _section_rows(parts)
    listed = sorted(e for entries in idx.values() for e in entries)
    block = [([(f"#{num}", kit.NOTE_STYLE[kind])], [(text, kind)])
             for num, text, kind, _e in listed if kind == "block"]
    side = ([(kit._chip_marker(letter), [(text, "code")]) for letter, text in marks]
            + [([(f"#{num}", kit.NOTE_STYLE[kind])], [(text, kind)])
               for num, text, kind, _e in listed if kind != "block"])
    if block:
        rows = kit._fit_panel(rows, lambda tw: kit._panel_rows(block, tw), width, "tl", kit.CALLOUT_MAX)
    if side:
        rows = kit._fit_panel(rows, lambda tw: kit._panel_rows(side, tw), width, "br", kit.CALLOUT_MAX)
    w = max([0] + [kit.row_len(r) for r in rows if not isinstance(r, kit.RuleRow)])
    return kit.stretch_rules(rows, w), max([w] + [kit.row_len(r) for r in rows])


def _tags(scn, notes: bool, mods: bool) -> dict:
    """The runs after a box's label (node id) and beside an edge's head (wire
    key): #N note tags (notes), then a node's modifiers (mods) and a store's
    writer badges (the Scene's, with the access option); a landed event's name,
    then the #N of the inline notes about its edge's line."""
    tags = {}
    note_runs = {}
    if notes:
        for nid, sn in scn.nodes.items():
            if kit.node_notes(sn.notes):
                tags[nid] = kit.note_tag_runs(kit.node_notes(sn.notes))
        for key, notes_ in scene.wire_notes(scn).items():
            if isinstance(key, tuple):               # an inline note rides its flow's edge
                note_runs[key] = [(" ".join(f"#{num}" for num, _t in notes_),
                                   kit.NOTE_STYLE["inline"])]
    for nid, text in (_node_mods(scn.graph) if mods else {}).items():
        tags[nid] = tags.get(nid, []) + [(" ", None)] + kit.mod_runs(text)
    for nid, sn in scn.nodes.items():
        if sn.badges:
            tags[nid] = tags.get(nid, []) + [(" " + badge, (kit.EDGE_COLOR["access"], None, True))
                                             for badge in sn.badges]
    names = _landed_tags(scn)
    for key in names.keys() | note_runs.keys():
        both = names.get(key, []) + ([(" ", None)] if key in names and key in note_runs else [])
        tags[key] = both + note_runs.get(key, [])
    return tags


def _node_mods(g) -> dict:
    """{node id: modifiers text} from the first place each node is written with
    modifiers, over g and its expansions."""
    out = {}
    for cur in kit._walk(g):
        for nid, n in cur.nodes.items():
            text = kit.mods_text(n.mods)
            if text:
                out.setdefault(nid, text)
    return out


def _section_rows(parts):
    """The sections' canvases as rows, each centred within the widest, under
    their titles; and that width. A Rule title (a `--- section ---`) is a
    divider across the drawing: `── L2 · Payments ─────`."""
    width = max([cv.w for _, _, cv in parts] + [len(t) + 6 for t, _, _ in parts if t] + [0])
    rows = []
    for title, _sg, cv in parts:
        if isinstance(title, kit.Rule):
            rows += ([[]] if rows else []) + [kit.section_rule(title, width), []]
        elif title:
            rows += [[], kit.section_rule(title, width), []]
        pad = (width - cv.w) // 2
        for row in cv.rows():
            rows.append(([(" " * pad, None)] if pad and row else []) + row)
    return rows, width


def graph_legend(triggers: bool = True, payloads: bool = False, access: bool = False,
                 mods: bool = False, events: str = "nodes"):
    """Legend row for the graph view: the stroke and head of each arrow type,
    then the trigger edge, an event drawn where it lands (events "land": the
    event-coloured edge emitter → destination, its name beside the head),
    structure marks (block frames, joins, branch arms), the permission edges,
    payload and modifier chips when they are shown."""
    dim, mid = (kit.GREY["dim"], None, False), (kit.GREY["mid"], None, False)
    row = [("arrows ", dim)]
    for kind, word in kit.ARROW_LEGEND:
        colour = kit.EDGE_COLOR.get(kind, kit.EDGE_DEFAULT)
        sample = ("▲" + kit._stroke_sample(kind) + "▼" if kind == "<->"
                  else kit._stroke_sample(kind) * 2 + _head(kind))
        row += [(sample, (colour, None, False)), (f" {word}  ", mid)]
    if triggers:
        row += [(kit._stroke_sample("trigger") * 2 + "▼", kit.edge_style("trigger")),
                (" trigger  ", mid)]
    if events == "land":
        ev = (scene.colour_of("kinds-event"), None, False)
        row += [(kit._stroke_sample("->") * 2 + _head("->") + " <E>", ev),
                (" emits  ", mid)]
    row += [("╭╌ ↺ ∥ ◇ □", kit.FRAME_STYLE), (" block frame  ", mid),
            ("┄‹arm›┄", (kit.EDGE_COLOR["arm"], None, False)), (" branch arm  ", mid),
            ("━┷━ &", kit.LABEL_STYLE), (" join: all  ", mid), ("&?", kit.LABEL_STYLE),
            (" race  ", mid), ("/", kit.LABEL_STYLE), (" one of  ", mid)]
    if access:
        acc = (kit.EDGE_COLOR["access"], None, False)
        row += [("┄┄r", acc), (" read  ", mid), ("┄┄w", acc), (" write  ", mid),
                ("┄┄b", acc), (" borrow  ", mid),
                ("1w", (kit.EDGE_COLOR["access"], None, True)), (" writers  ", mid)]
    if payloads:
        row += [("╭┄{…}┄╯", dim), (" payload", mid)]       # the chip's corners, on one row
    if mods:
        row += [("┆@… ×N┆", (kit.SYNTAX["modifier"][0], None, False)), (" modifiers", mid)]
    return row
