"""
view_flow.py — the flow view of view.py: a Sigil document drawn as a call graph
read left to right.

Not a command: view.py loads it. It looks like the page's background toy graphs:
bare glyph labels, no boxes, one column per call depth, wires bending between them.

    (Shopper) ──▶ [API] ─┬─▶ [Payments]
                         ├─✖ <PaymentFailed>
                         ├─▶ |Orders|
                         ╰╌▶ <OrderPlaced> ═══╦═▶ [Email]
                                              ╠═▶ [Shipping]
                                              ╚═▶ |Ledger|

A node sits in the column of its call depth (the longest chain of flows that
leads to it; a source with nothing before it moves along to just before what it
calls), its first callee on its own row and the rest below, so a tree of calls
reads straight across. A flow that skips columns runs straight through them; a
flow back to an earlier column (a cycle) leaves its source down to a return row
under the drawing, runs back left along it and comes up into its target. Wires
from one source share a trunk (┬ ├ ╰); wires into one target that end in the
same head share its last run (┴ ┤); a target with several kinds of head takes
them stacked, bundled by a bracket (`▶┐` / `✖┘`). A wire that only crosses
another hops it (─│─), never joins it.

What is drawn comes from the Scene (scene.py), as in the other two views: every
wire in its arrow's stroke and head (`!>` ✖, a permission's r / w / b) and its
colour (the colour policy), each flow's chip (`┆payload ┆ mods┆`, p / m) on its
wire between the two columns, a self-call's chip on a stub under its subject
(`╰─● ┆ ↺ plan({Seed}) ↩ {Plan} ┆`), the marks after a label (#N notes, ▾ / ▸
expansions, `↺` `↻` `⇱` calls, writer badges), what is written beside a wire's
head in the graph view (`↩`, a landed event's name, a path's `[A]/`, an inline
note's #N), led by a qualified source path's `from [A]/`, as bare text on its
wire, triggers (e), the checks overlay (c: a marked wire's stroke and a marked
label's brackets in the finding's style, its number after the label or on the
wire) and a simulation frame (view_graph's
sim_look: lit and muted wires, tokens on their cells, labels by status, badges).
`:=` expansions and state machines are drawn as parts under the document's, like
the graph view's sections; control blocks are not framed (their flows are drawn
with the rest; a branch's arms are dotted wires labelled ‹arm›), joins are not
drawn as bars.

compose_flow() returns the rows view.py prints, the same shape as
view_graph.compose(). Drawing primitives and styles come from viewkit.py (read
as kit.NAME, so a theme change reaches them).
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple, Optional


_HERE = Path(__file__).resolve().parent


def _sibling(name: str, fname: str):
    """The module fname beside this file, loaded by path once per directory and then
    shared: the view modules of one directory read the one viewkit, so a theme
    applied through any of them (apply_theme rebinds viewkit's style globals)
    reaches them all, while a view.py loaded from another directory (a packaged
    copy) gets modules, theme and dialect state of its own. The cache key names
    the directory, never the bare name. view.py, view_graph.py, view_tree.py,
    view_flow.py and scene.py each carry a copy of this function: keep the copies
    identical."""
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
vgraph = _sibling("sigil_view_graph", "view_graph.py")


# ---------------------------------------------------------------------------
# Parts — what one drawing holds: the Scene's wires of one unit (or one
# `--- section ---` of the document), as strokes between its nodes.
# ---------------------------------------------------------------------------

DRAWN_ROLES = ("flow", "emit", "trigger", "access", "arm")    # composition (`\\-`) is not


class _Stroke(NamedTuple):
    """One drawn wire between two nodes of a part: every Scene wire of one key."""
    key: tuple                  # the wire key it is styled and tagged by
    kind: str
    src: str
    dst: str
    wires: tuple                # the Scene wires it draws (their idents carry tokens)
    rides: tuple                # the wire keys whose tokens travel it (key, or a driver's)
    role: str


@dataclass
class _Part:
    title: str                  # "" | an expansion's title | a kit.Rule (a section)
    owner: Optional[str]        # the unit it draws (None: the document)
    graph: object               # that unit's render.Graph
    nodes: dict                 # id → render.Node, drawing order
    strokes: list = field(default_factory=list)


def flow_parts(scn, depth: int) -> list:
    """[_Part]: the document (split by its `--- sections ---`), then each drawn
    expansion and state machine, in the Scene's unit order. A part draws the
    wires of its unit between its nodes; a machine's part also draws what drives
    it (the event, or the emitter of an event drawn where it lands) into the
    state it enters, and the owner's part an edge from that driver into the
    owner (as view_graph does)."""
    parts, titles = [], {}
    for u in scn.units:
        gone = scn.collapsed if u.level == 0 else frozenset()
        nodes = {nid: n for nid, n in u.graph.nodes.items() if nid not in gone}
        strokes = _unit_strokes(scn, u, nodes)
        if u.level == 0:
            parts += _split_sections(scn, u, nodes, strokes)
            continue
        what = "state machine" if getattr(u.graph, "role", "") == "state" else ":= { … }"
        title = f"{kit.node_label(scn.nodes[u.owner].node)} {what}"
        parent = scn.nodes[u.owner].unit
        if parent is not None and parent in titles:
            title = f"{titles[parent]}  ›  {title}"
        titles[u.owner] = title
        parts.append(_Part(title, u.owner, u.graph, nodes, strokes))
    return parts


def _unit_strokes(scn, u, nodes: dict) -> list:
    """The strokes of one unit, in wire order: its own wires between its nodes
    (a branch's arm from a header with no glyph starts at a ◇ decision node,
    added to `nodes`), the drivers of its machine (their sources added to
    `nodes`), and driver ⇢ owner for a machine of one of its nodes drawn
    elsewhere. `nodes` is filled in place."""
    by_key, order = {}, []

    def add(key, kind, src, dst, w, ride, role):
        if key not in by_key:
            by_key[key] = [kind, src, dst, [], [], role]
            order.append(key)
        entry = by_key[key]
        entry[3].append(w)
        if ride not in entry[4]:
            entry[4].append(ride)

    for w in scn.wires:
        if w.role not in DRAWN_ROLES:
            continue
        if w.owner == u.owner and w.role == "arm" and w.src not in scn.nodes:
            nodes.setdefault(w.src, _decision(u.graph, w))
        if w.owner == u.owner and w.src in nodes and w.dst in nodes:
            add(w.key, w.kind, w.src, w.dst, w, w.key, w.role)
        elif w.machine is not None and w.machine == u.owner and w.dst in nodes:
            if w.src in scn.nodes:                  # what drives this machine
                nodes.setdefault(w.src, scn.nodes[w.src].node)
                add(w.key, w.kind, w.src, w.dst, w, w.key, w.role)
        elif (w.machine is not None and w.machine in nodes and w.src in nodes
              and w.src != w.machine and w.dst not in nodes and w.role in ("trigger", "emit")):
            add((w.src, w.machine, "trigger"), "trigger", w.src, w.machine, w, w.key, "trigger")
    return [_Stroke(key, e[0], e[1], e[2], tuple(e[3]), tuple(e[4]), e[5])
            for key in order for e in [by_key[key]]]


def _decision(g, w):
    """The ◇ node an arm starts at when its branch's header names no glyph."""
    blocks = getattr(g, "blocks", None) or []
    b = blocks[w.block] if w.block is not None and 0 <= w.block < len(blocks) else None
    name = (b.header if b is not None and b.header else "branch")
    return kit.render.Node(id=w.src, name=name, kind=kit.DECISION)


def _split_sections(scn, u, nodes: dict, strokes: list) -> list:
    """The document's part, or one per `--- section ---` (titled by a Rule): a
    stroke goes to the section its line is in, a node to every section a
    stroke of it is in (else the one it is written in)."""
    secs = scn.sections
    if not secs:
        return [_Part("", None, u.graph, nodes, strokes)]
    est = kit.node_lines(u.graph)
    groups = {}
    for st in strokes:
        line = next((w.line for w in st.wires if w.line), 0) or est.get(st.src, 0)
        groups.setdefault(kit.section_of(secs, line), []).append(st)
    linked = {}
    for i, sts in groups.items():
        for st in sts:
            linked.setdefault(st.src, set()).add(i)
            linked.setdefault(st.dst, set()).add(i)
    out = []
    for i in sorted(set(groups) | {_node_section(scn, nid) for nid in nodes if nid not in linked}):
        here = {nid: n for nid, n in nodes.items()
                if i in linked.get(nid, ()) or (nid not in linked and _node_section(scn, nid) == i)}
        title = kit.Rule(kit.section_name(secs[i])) if i >= 0 else ""
        out.append(_Part(title, None, u.graph, here, groups.get(i, [])))
    return out


def _node_section(scn, nid) -> int:
    sn = scn.nodes.get(nid)
    return sn.section if sn is not None else -1


# ---------------------------------------------------------------------------
# Layout — columns by call depth, rows by a tree walk, then each channel's
# tracks (between two columns) and the return rows of the wires that go back.
# ---------------------------------------------------------------------------

ROUND = {"┌": "╭", "┐": "╮", "└": "╰", "┘": "╯"}   # light corners drawn rounded
UNTANGLE = 8                    # row passes to untangle two wires that swap rows
ISOLATED_GAP = 3                # columns between unconnected nodes
ISOLATED_WRAP = 100
BUNDLE = ("┐", "┤", "┘")        # the bracket bundling a target's stacked heads


class _Canvas(kit.Canvas):
    """A Canvas whose light corners are rounded (╭ ╮ ╰ ╯), like the page's
    toy graphs; heavy and double corners stay square."""

    def cell(self, x, y):
        ch, style = super().cell(x, y)
        return (ch, style) if (x, y) in self.text else (ROUND.get(ch, ch), style)


@dataclass
class _Vx:
    """A vertex: a node (its label), a chip on a wire, or a dummy a wire runs
    straight through in a column it skips."""
    id: str
    what: str                   # "node" | "chip" | "dummy"
    runs: list = field(default_factory=list)
    col: int = 0
    row: int = 0
    heads: list = field(default_factory=list)   # a node's in-ports: one per arrow kind, stacked
    stubs: list = field(default_factory=list)   # a node's self-call stubs (view_graph._Stub)
    ins: list = field(default_factory=list)     # (vertex id, segment) in
    outs: list = field(default_factory=list)    # (vertex id, segment) out
    mark: int = -1              # column of its self-call mark in its runs (-1: none)
    floor: int = 0              # the highest row it may take (moved down to untangle)

    @property
    def width(self) -> int:
        w = kit.row_len(self.runs)
        return max([w] + [st.width() for st in self.stubs])

    @property
    def label_w(self) -> int:
        return kit.row_len(self.runs)

    @property
    def height(self) -> int:
        return max(len(self.heads), 1 + len(self.stubs), 1)


@dataclass
class _Path:
    """One stroke's way from its source to its target: the vertices it passes
    (source, a chip, dummies, target), or a back path (target in an earlier
    column) routed under the drawing."""
    stroke: _Stroke
    style: tuple
    chip: Optional[list]        # the chip's runs (None: no chip)
    via: list                   # vertex ids, source → target (a back path: both ends)
    back: bool = False
    head: str = "▶"
    ret: int = 0                # a back path: its return row
    tin: int = 0                # a back path: the x of its track into the target
    tout: int = 0               # … and out of the source
    cells: list = field(default_factory=list)


class _Group(NamedTuple):
    """The wires sharing one vertical in a channel: a source's segments to the
    next column (and its back paths' way down), or a back path's way up."""
    gid: object
    src: Optional[int]          # the row it leaves from (None: comes up from below)
    dsts: frozenset             # the rows it turns into
    down: bool                  # it runs on down to the return rows

    @property
    def lo(self) -> int:
        rows = set(self.dsts) | ({self.src} if self.src is not None else set())
        return min(rows)

    @property
    def hi(self) -> float:
        return float("inf") if self.down or self.src is None else max(set(self.dsts) | {self.src})

    @property
    def straight(self) -> bool:
        return not self.down and self.src is not None and self.dsts == {self.src}


@dataclass
class _Layout:
    part: _Part
    spots: dict = field(default_factory=dict)   # self-call wire ident → its stub's ● cell
    marks: dict = field(default_factory=dict)   # node id → the cell of its self-call mark
    V: dict = field(default_factory=dict)       # vertex id → _Vx
    paths: list = field(default_factory=list)
    cols: list = field(default_factory=list)    # per column: vertex ids, top → bottom
    isolated: list = field(default_factory=list)
    colx: dict = field(default_factory=dict)    # column → x of its labels
    track: dict = field(default_factory=dict)   # group id → its x
    groups: dict = field(default_factory=dict)  # group id → _Group
    passes: dict = field(default_factory=dict)  # (x, y) → group id: a vertical passing through
    bottom: int = 0                             # the first row under every vertex


def _head(kind: str) -> str:
    """A wire's head: ✖ for `!>`, a permission's access letter, else ▶."""
    if kind == "!>":
        return "✖"
    if kind.startswith("access:"):
        return kind[-1]
    return "▶"


def _build(part: _Part, ctx: "_Ctx") -> _Layout:
    """A part's vertices and paths, columns, rows and channels."""
    lay = _Layout(part)
    ids = list(part.nodes)
    selfs = ctx.selfs_of(part)
    for nid in ids:
        lay.V[nid] = _Vx(nid, "node", ctx.label(part, nid, selfs), stubs=list(
            selfs[nid].stubs if nid in selfs else ()))
        lay.V[nid].mark = ctx.mark_at.get((id(part), nid), -1)
    strokes = [st for st in part.strokes if st.src != st.dst]
    linked = {st.src for st in strokes} | {st.dst for st in strokes}
    lay.isolated = [nid for nid in ids if nid not in linked]
    col = _columns([nid for nid in ids if nid in linked], strokes)
    chips = {st.key: ctx.chips(part, st) for st in strokes}
    # A column of chips after a node column when a flow from it carries one.
    chipped = {col[st.src] for st in strokes if chips[st.key] and col[st.dst] > col[st.src]}
    at = {c: c + sum(1 for k in chipped if k < c) for c in set(col.values())}
    k = 0
    for st in strokes:
        style = ctx.style(st)
        for runs in chips[st.key] or [None]:
            a, b = col[st.src], col[st.dst]
            p = _Path(st, style, runs, [st.src], back=b <= a, head=_head(st.kind))
            for c in range(at[a] + 1, at[b]) if not p.back else ():
                k += 1
                is_chip = runs is not None and c == at[a] + 1
                vid = f"\0{'c' if is_chip else 'd'}{k}"
                lay.V[vid] = _Vx(vid, "chip" if is_chip else "dummy",
                                 list(runs) if is_chip else [], col=c)
                p.via.append(vid)
            p.via.append(st.dst)
            lay.paths.append(p)
    for nid in ids:
        if nid in linked:
            lay.V[nid].col = at[col[nid]]
    for pi, p in enumerate(lay.paths):
        if p.back:
            continue
        for si, (u, w) in enumerate(zip(p.via, p.via[1:])):
            lay.V[u].outs.append((w, (pi, si)))
            lay.V[w].ins.append((u, (pi, si)))
    for p in lay.paths:                         # a node's in-ports: one per arrow kind
        dst = lay.V[p.via[-1]]
        if p.stroke.kind not in dst.heads:
            dst.heads.append(p.stroke.kind)
    for v in lay.V.values():                    # flows first, then triggers, then access
        v.heads.sort(key=lambda kind: (kind == "trigger", kind.startswith("access:")))
    ncols = max((v.col for v in lay.V.values() if v.id not in lay.isolated), default=-1) + 1
    lay.cols = [[] for _ in range(ncols)]
    for vid, v in lay.V.items():
        if vid not in lay.isolated:
            lay.cols[v.col].append(vid)
    _rows(lay)
    if _sort_heads(lay):                        # stacked heads in their sources' order
        _rows(lay)
    for _ in range(UNTANGLE):
        pushed = _crossed(lay)
        if not pushed:
            break
        for vid in pushed:
            lay.V[vid].floor = lay.V[vid].row + 1
        _rows(lay)
    _channels(lay)
    return lay


def _sort_heads(lay: _Layout) -> bool:
    """Order each node's stacked in-ports by the rows their wires come from (a
    wire back from a later column: from below), so two wires into one node
    don't cross on their way in. Returns whether any order changed."""
    changed = False
    into = {}
    for p in lay.paths:
        into.setdefault(p.via[-1], []).append(p)
    for v in lay.V.values():
        if len(v.heads) < 2:
            continue
        came = {}
        for p in into.get(v.id, ()):
            row = float("inf") if p.back else lay.V[p.via[-2]].row
            came[p.stroke.kind] = min(came.get(p.stroke.kind, row), row)
        order = sorted(v.heads, key=lambda kind: (came.get(kind, float("inf")),
                                                  v.heads.index(kind)))
        changed |= order != v.heads
        v.heads = order
    return changed


def _columns(ids: list, strokes: list) -> dict:
    """{node id: column}: the longest chain of flows into it once each cycle is
    broken (view_graph's DFS in document order), then each source moved along to
    just before the nearest node it feeds."""
    succ = {i: [] for i in ids}
    for st in strokes:
        succ[st.src].append(st.dst)
    back = vgraph._break_cycles(ids, succ)
    down = {i: [] for i in ids}
    indeg = {i: 0 for i in ids}
    for st in strokes:
        a, b = (st.dst, st.src) if (st.src, st.dst) in back else (st.src, st.dst)
        if b not in down[a]:
            down[a].append(b)
            indeg[b] += 1
    col = {i: 0 for i in ids}
    queue, topo = [i for i in ids if indeg[i] == 0], []
    while queue:
        v = queue.pop(0)
        topo.append(v)
        for b in down[v]:
            col[b] = max(col[b], col[v] + 1)
            indeg[b] -= 1
            if indeg[b] == 0:
                queue.append(b)
    has_in = {b for a in ids for b in down[a]}
    for v in reversed(topo):
        if v not in has_in and down[v]:
            col[v] = max(col[v], min(col[b] for b in down[v]) - 1)
    return col


def _in_row(lay: _Layout, p: _Path, vid: str) -> int:
    """The row a path enters vertex vid on: a node's in-port of its arrow kind."""
    v = lay.V[vid]
    if v.what != "node" or vid != p.via[-1]:
        return v.row
    return v.row + v.heads.index(p.stroke.kind)


def _rows(lay: _Layout) -> None:
    """Every vertex's row, by a walk of the calls from each source in turn: a
    callee on its caller's row when its column is free there (its in-port of
    that kind on the row), a later callee below the earlier ones' whole subtrees
    (so a tree of calls draws without a crossing), a source with no caller
    beside the first node it feeds. A vertex never rises above its floor."""
    V = lay.V
    free = {}                                   # column → its first free row
    reach = _reach(lay)
    seen = set()

    def block(vid) -> int:
        """The first row free in every column a vertex's subtree may reach."""
        v = V[vid]
        return max(free.get(c, 0) for c in range(v.col, reach[vid] + 1))

    def place(vid, want: int):
        """Place a vertex, then yield (vertex, wanted row) for each one to place
        next — the walk below (a generator, so a long chain of calls needs no
        deep recursion: walk() drives it); each is asked for once the ones
        before it are placed."""
        v = V[vid]
        seen.add(vid)
        v.row = max(want, free.get(v.col, 0), v.floor)
        free[v.col] = v.row + v.height
        for u, seg in v.ins:                    # a source feeding it: beside it
            origin = _origin(lay, u)
            if origin not in seen and not V[origin].ins:
                yield origin, _in_row(lay, lay.paths[seg[0]], vid)
        for k, (w, seg) in enumerate(v.outs):
            if w in seen:
                continue
            path = lay.paths[seg[0]]
            end = path.via[-1]
            if V[w].what != "node" and end in seen:     # a wire on to a placed node:
                chain = [c for c in path.via if V[c].what != "node"]
                chain = chain[chain.index(w):]          # one row, its in-port's if free
                want = max([_in_row(lay, path, end)] + [free.get(V[c].col, 0) for c in chain])
            else:
                want = v.row - (_in_row(lay, path, w) - V[w].row)
                if k:                           # below the earlier callees' subtrees
                    want = max(want, block(w))
            yield w, want

    def walk(vid, want: int) -> None:
        stack = [place(vid, want)]
        while stack:
            nxt = next(stack[-1], None)
            if nxt is None:
                stack.pop()
            elif nxt[0] not in seen:
                stack.append(place(*nxt))

    # The walk starts from the unit's own sources in document order, then its other
    # nodes; a node brought in from elsewhere (what drives a machine) is placed
    # beside what it feeds.
    order = [vid for vid in V if vid not in lay.isolated]
    own = [vid for vid in order if vid in lay.part.graph.nodes]
    for vid in [vid for vid in own if not V[vid].ins] + own + order:
        if vid not in seen:
            walk(vid, block(vid))
    for column in lay.cols:
        column.sort(key=lambda vid: V[vid].row)


def _origin(lay: _Layout, vid: str) -> str:
    """The node a chip or dummy vertex's wire comes from (a node: itself)."""
    while lay.V[vid].what != "node" and lay.V[vid].ins:
        vid = lay.V[vid].ins[0][0]
    return vid


def _reach(lay: _Layout) -> dict:
    """{vertex id: the furthest column its forward wires lead to}."""
    out = {}
    for column in reversed(lay.cols):
        for vid in column:
            v = lay.V[vid]
            out[vid] = max([v.col] + [out.get(w, lay.V[w].col) for w, _seg in v.outs])
    return out


def _crossed(lay: _Layout) -> set:
    """The vertices to move a row down so that no two wires between one pair of
    columns swap rows (one leaving from the row the other enters on, and the other
    way round: no order of their tracks can draw both): of each such pair, the
    lower vertex entered."""
    out = set()
    for column in lay.cols:
        leaving = {}                            # row → [(entered row, vertex)]
        for vid in column:
            v = lay.V[vid]
            for w, seg in v.outs:
                leaving.setdefault(v.row, []).append((_in_row(lay, lay.paths[seg[0]], w), w))
        for r1, outs1 in leaving.items():
            for r2, w1 in outs1:
                if r2 <= r1 or r2 not in leaving:
                    continue
                if any(r == r1 for r, _w in leaving[r2]):
                    out.add(w1)
    return out


def _channels(lay: _Layout) -> None:
    """The x of every column and of each channel's tracks, and each back path's
    return row; channel k runs between column k and k + 1 (-1: left of the first
    column, for back paths into it)."""
    V, paths = lay.V, lay.paths
    groups = {}                                 # channel → [_Group]
    backs = {p.via[0] for p in paths if p.back}
    for vid, v in V.items():
        if vid in lay.isolated:
            continue
        dsts = {_in_row(lay, paths[seg[0]], w) for w, seg in v.outs}
        down = vid in backs
        if dsts or down:
            groups.setdefault(v.col, []).append(_Group(("out", vid), v.row, frozenset(dsts), down))
    for pi, p in enumerate(paths):
        if p.back:
            dst = V[p.via[-1]]
            groups.setdefault(dst.col - 1, []).append(
                _Group(("in", pi), None, frozenset({_in_row(lay, p, p.via[-1])}), True))
    for gs in groups.values():
        for gr in gs:
            lay.groups[gr.gid] = gr
    widths = [max((V[vid].width for vid in column), default=0) for column in lay.cols]
    first = min(groups, default=0)
    x = 0
    if first < 0:                               # the left margin's tracks
        tracks = _tracks(groups[-1])
        x = _place_tracks(lay, tracks, -1) + 4
    for c, column in enumerate(lay.cols):
        lay.colx[c] = x
        start = x + widths[c] + 1               # one blank after the widest label
        tracks = _tracks(groups.get(c, []))
        last = _place_tracks(lay, tracks, start)
        x = (last if last is not None else start) + 4
    lay.bottom = max((v.row + v.height for vid, v in V.items() if vid not in lay.isolated),
                     default=0)
    for pi, p in enumerate(paths):
        if p.back:
            p.tout = lay.track[("out", p.via[0])]
            p.tin = lay.track[("in", pi)]
    y = lay.bottom
    rets = {}                                   # group id → the return rows it turns into
    back = sorted((pi for pi, p in enumerate(paths) if p.back),
                  key=lambda pi: (paths[pi].tout - paths[pi].tin, paths[pi].tin))
    for pi in back:                             # the shorter ones higher
        p = paths[pi]
        p.ret = y
        y += 1 + (not _chip_fits(p))
        rets.setdefault(("out", p.via[0]), set()).add(p.ret)
        rets.setdefault(("in", pi), set()).add(p.ret)
    for gid, gr in lay.groups.items():          # the cells a vertical only passes
        if gr.straight or gid not in lay.track:
            continue
        turns = set(gr.dsts) | ({gr.src} if gr.src is not None else set()) | rets.get(gid, set())
        for yy in range(gr.lo, max(turns) + 1):
            if yy not in turns:
                lay.passes[(lay.track[gid], yy)] = gid


def _chip_fits(p: _Path) -> bool:
    """Whether a back path's chip fits on its return row (else it takes the row
    under it)."""
    return p.chip is None or kit.row_len(p.chip) + 4 <= p.tout - p.tin


def _tracks(gs: list) -> list:
    """[[_Group]]: the groups that need a vertical, packed into tracks left to
    right — two share a track when their rows don't meet; a group whose source
    row is another's target row goes left of it (its run must not cover the
    other's). A cycle of such constraints is broken at its first group."""
    todo = sorted((gr for gr in gs if not gr.straight), key=lambda gr: (gr.lo, gr.hi))
    before = {gr.gid: {o.gid for o in todo if o is not gr and o.src is not None
                       and o.src in gr.dsts} for gr in todo}
    placed, tracks = set(), []
    while todo:
        track, hi = [], -1
        for gr in todo:
            if gr.lo > hi and before[gr.gid] <= placed:
                track.append(gr)
                hi = gr.hi
        if not track:
            track = [todo[0]]
        placed |= {gr.gid for gr in track}
        tracks.append(track)
        todo = [gr for gr in todo if gr.gid not in placed]
    return tracks


def _place_tracks(lay: _Layout, tracks: list, start: int):
    """Each track's x (a blank column between two tracks); the last one's x, or
    None when there are none."""
    x = None
    for i, track in enumerate(tracks):
        x = start + 1 + 2 * i
        for gr in track:
            lay.track[gr.gid] = x
    return x


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _out_x(lay: _Layout, vid: str) -> int:
    """Where a vertex's wires leave it: a blank after a node's label, right after a
    chip, at the column's start for a dummy (its wire runs straight through)."""
    v = lay.V[vid]
    x = lay.colx[v.col]
    if v.what == "node":
        return x + v.label_w + 1
    return x + v.label_w if v.what == "chip" else x - 1


def _in_x(lay: _Layout, vid: str) -> int:
    """Where a wire ends at a vertex: a node's head cell (a blank before its
    label), the cell before a chip or a dummy."""
    v = lay.V[vid]
    return lay.colx[v.col] - (2 if v.what == "node" else 1)


def _points(lay: _Layout, p: _Path) -> list:
    """The corners of a path's line, source → target."""
    V = lay.V
    if p.back:
        u, w = p.via[0], p.via[-1]
        yin = _in_row(lay, p, w)
        return [(_out_x(lay, u), V[u].row), (p.tout, V[u].row), (p.tout, p.ret),
                (p.tin, p.ret), (p.tin, yin), (_in_x(lay, w), yin)]
    pts = []
    for u, w in zip(p.via, p.via[1:]):
        x0, y0 = _out_x(lay, u), V[u].row
        x1, y1 = _in_x(lay, w), _in_row(lay, p, w)
        tx = lay.track.get(("out", u))
        if pts and pts[-1] != (x0, y0):
            pts.append(None)                    # a chip's text: the line resumes after it
        if tx is None:                          # a straight group: no track
            pts += [(x0, y0), (x1, y1)]
        else:
            pts += [(x0, y0), (tx, y0), (tx, y1), (x1, y1)]
    return pts


def _draw_path(cv: _Canvas, lay: _Layout, p: _Path) -> list:
    """Draw a path's line (hopping every vertical it only crosses); returns its
    cells in order, source → target."""
    pts = _points(lay, p)
    cells = []
    for a, b in zip(pts, pts[1:]):
        if a is None or b is None or a == b:
            continue
        (x0, y0), (x1, y1) = a, b
        if y0 == y1:
            lo, hi = min(x0, x1), max(x0, x1)
            cv.run(lo, hi, y0, p.stroke.kind, p.style,
                   hops=lambda x, _y=y0: (x, _y) in lay.passes and x not in (lo, hi))
        else:
            cv.path([a, b], p.stroke.kind, p.style)
        run = vgraph._cells([a, b])
        cells += run[1:] if cells and cells[-1] == run[0] else run
    return cells


def _draw(lay: _Layout, ctx: "_Ctx") -> _Canvas:
    cv = _Canvas()
    traces = []
    for p in lay.paths:
        p.cells = _draw_path(cv, lay, p)
        tr = vgraph._Trace(p.style, False, p.stroke.kind == "<->", edge=None)
        tr.cells = list(p.cells)
        traces.append(tr)
    for cell, st in vgraph._nearest_owners(traces, cv.lines).items():
        cv.lines[cell][2] = st
    for p in lay.paths:                         # heads, and a `<->`'s source end
        dst = lay.V[p.via[-1]]
        if dst.what == "node" and p.cells:
            cv.put(*p.cells[-1], p.head, p.style)
        if p.stroke.kind == "<->" and len(p.cells) > 1:  # its own first cell, else by its head
            shared = sum(q.via[0] == p.via[0] for q in lay.paths) > 1
            at = p.cells[-2] if shared and len(p.cells) > 2 else p.cells[0]
            cv.put(*at, "◀", p.style)
    for vid, v in lay.V.items():
        if vid in lay.isolated or v.what == "dummy":
            continue
        x, y = lay.colx[v.col], v.row
        kit._put_runs(cv, x, y, v.runs)
        if v.what == "node":
            if len(v.heads) > 1:
                last = len(v.heads) - 1
                for j in range(last + 1):
                    mark = BUNDLE[0] if j == 0 else BUNDLE[2] if j == last else BUNDLE[1]
                    cv.put(x - 1, y + j, mark, kit.FRAME_STYLE)
            lay.spots.update(_draw_stubs(cv, x, y, v.stubs, ctx.styles))
            if v.mark >= 0:
                lay.marks[v.id] = (x + v.mark, y)
    for p in lay.paths:                         # a back path's chip on its return row
        if p.back and p.chip is not None:
            yy = p.ret if _chip_fits(p) else p.ret + 1
            kit._put_runs(cv, p.tin + 2, yy, p.chip)
    if lay.isolated:
        x, y = 0, (max(cv.h, lay.bottom) + 1) if (cv.h or lay.bottom) else 0
        wrap = max(cv.w, ISOLATED_WRAP)
        row_h = 1
        for nid in lay.isolated:
            v = lay.V[nid]
            if x and x + v.width > wrap:
                x, y, row_h = 0, y + row_h, 1
            kit._put_runs(cv, x, y, v.runs)
            lay.spots.update(_draw_stubs(cv, x, y, v.stubs, ctx.styles))
            if v.mark >= 0:
                lay.marks[nid] = (x + v.mark, y)
            row_h = max(row_h, v.height)
            x += v.width + ISOLATED_GAP
    return cv


def _draw_stubs(cv: _Canvas, x: int, y: int, stubs, styles: dict) -> dict:
    """A node's self-call stubs, a row each under its label: `├─●` / `╰─●` then
    the chip, in the self-edge's stroke style. Returns {wire ident: the cell of
    its ● (a token sits there)}."""
    spots = {}
    dim = (kit.GREY["dim"], None, False)
    for k, st in enumerate(stubs):
        e = st.wire
        style = styles.get(e.key) or kit.edge_style(e.kind)
        bend = "╰" if k == len(stubs) - 1 else "├"
        sy = y + 1 + k
        cv.put(x, sy, bend + "─" + kit.SOURCE_MARK.get(e.kind, "●"), style)
        spots[e.ident] = (x + 2, sy)
        cx = kit._put_runs(cv, x + 4, sy, [("┆ ", dim)] + st.runs)
        cv.put(cx, sy, " ┆", dim)
    return spots


# ---------------------------------------------------------------------------
# What a part's labels, chips and strokes show — the Scene's annotations, the
# checks overlay and a sim frame, read once per drawing (_Ctx)
# ---------------------------------------------------------------------------

class _Ctx:
    """One drawing's options and annotations: wire styles (the colour policy, a
    sim frame's, the checks' over them), tags (view_graph._tags: after a label,
    by node id; beside a head, by wire key), chips, the sim look; and, filled as
    labels are made, the column of each label's self-call mark (mark_at)."""

    def __init__(self, scn, depth: int, payloads: bool, mods: bool, notes: bool,
                 look=None, checks=None, marks: list | None = None):
        self.scn, self.depth, self.payloads, self.mods = scn, depth, payloads, mods
        self.look, self.checks, self.letters = look, checks, marks
        self.tags = vgraph._tags(scn, notes, mods)
        for nid, runs in (look.badges if look else {}).items():
            self.tags[nid] = self.tags.get(nid, []) + runs
        for at, runs in (vgraph.check_tags(checks) if checks is not None else {}).items():
            self.tags[at] = self.tags.get(at, []) + runs
        self.styles = look.styles if look is not None else vgraph._wire_styles(scn)
        self.marked = {}
        if checks is not None:
            self.styles = {**self.styles, **{key: kit.check_mark_style(kit.check_worst(ms))
                                             for key, ms in checks.by_key().items()}}
            self.marked = {nid: kit.check_mark_style(kit.check_worst(ms))
                           for nid, ms in checks.nodes.items()}
        self.chip_lists = {}
        self.mark_at = {}                       # (id(part), node id) → its mark's column

    def style(self, st: _Stroke) -> tuple:
        """A stroke's style: its key's (a driver ⇢ owner edge: the driver wire's),
        else its arrow's, muted under a sim frame."""
        for key in (st.key,) + st.rides:
            if key in self.styles:
                return self.styles[key]
        return vgraph._unkeyed_style(st.kind, self.look is not None)

    def selfs_of(self, part: _Part) -> dict:
        """{node id: view_graph._Selfs} of the part's nodes that call themselves."""
        calls = scene.self_calls(self.scn, part.owner)
        out = vgraph._self_calls(part.graph, calls, self.payloads, self.mods, self.letters)
        for st in part.strokes:                 # a self-edge that is no call (a machine's)
            if st.src == st.dst and st.src in part.nodes and st.src not in out:
                out[st.src] = vgraph._Selfs("↺", [])
        return {nid: s for nid, s in out.items() if nid in part.nodes}

    def label(self, part: _Part, nid: str, selfs: dict) -> list:
        """A node's runs: a sim lead (a machine's ◉ slot), its label as the frame
        shows it, its tags, ▾ / ▸ for an expansion drawn below / not, then its
        self-call mark (whose column is kept for a token)."""
        n = part.nodes[nid]
        runs = list(self.look.lead.get(nid, ())) if self.look else []
        label = _label_runs(n, self.look.looks.get(nid, "muted") if self.look else None)
        if nid in self.marked and len(label) == 3:      # a finding's style on the brackets
            label = [(label[0][0], self.marked[nid]), label[1], (label[2][0], self.marked[nid])]
        if self.look is not None and nid in self.look.probe:
            label = kit.probed(label)
        runs += label + self.tags.get(nid, [])
        if nid in part.graph.expansions:
            shown = scene_level(self.scn, part.owner) < self.depth
            runs.append((" ▾" if shown else " ▸", (kit.GREY["mid"], None, False)))
        if nid in selfs:
            runs.append((" ", None))
            self.mark_at[(id(part), nid)] = kit.row_len(runs)
            runs.append((selfs[nid].mark, kit.SYNTAX["operator"]))
        return runs

    def chips(self, part: _Part, st: _Stroke) -> list:
        """[runs]: the chips a stroke carries between its columns — one per call
        written on it (scene.chip_lists, never merged), each `┆…┆`, then what the
        graph view writes beside its head (a transition's or an arm's label,
        view_graph._tags's runs) as bare text on the first; [] when none."""
        if part.owner not in self.chip_lists:
            self.chip_lists[part.owner] = (scene.chip_lists(self.scn, self.payloads, self.mods,
                                                            unit=part.owner)
                                           if self.payloads or self.mods else {})
        texts = self.chip_lists[part.owner].get(st.key, []) if st.role in ("flow", "emit") else []
        dim = (kit.GREY["dim"], None, False)
        out = []
        for text in texts:
            if self.letters is not None:
                letter = kit._letter(len(self.letters))
                self.letters.append((letter, text))
                out.append([("┆", dim), (letter, kit.PAYLOAD_STYLE), ("┆", dim)])
            else:
                mtext = kit.chip_parts(st.wires[0], self.payloads, self.mods)[1]
                out.append([("┆", dim)] + vgraph._chip_runs(text, mtext) + [("┆", dim)])
        bare = []
        label = next((w.label for w in st.wires if w.label), None)
        if st.role == "arm" and label:
            bare.append((f"‹{label}›", (kit.EDGE_COLOR["arm"], None, True)))
        elif label and st.role == "flow" and not _driven(part, label):
            bare.append((label, kit.LABEL_STYLE))
        tag = self.tags.get(st.key, [])
        tail = self.tags.get(vgraph.tail_key(st.key), []) if st.role == "flow" else []
        if tail:                                # a qualified source path's `from [A]/` first
            tag = tail + [(" ", None)] + tag if tag else tail
        if tag:
            bare += [(" ", None)] + tag
        bare = _strip(bare)
        if bare and bare[0][0].startswith(" "):
            bare[0] = (bare[0][0].lstrip(), bare[0][1])
        if bare:
            bare = [(" ", None)] + bare + [(" ", None)]
            if out:
                out[0] = out[0] + bare
            else:
                out.append(bare)
        return out


def scene_level(scn, owner) -> int:
    """The level of the unit `owner` draws (0: the document)."""
    return next((u.level for u in scn.units if u.owner == owner), 0)


def _driven(part: _Part, label: str) -> bool:
    """Whether a transition's label is an event this part draws driving it."""
    return any(st.role in ("trigger", "emit") and any(w.label == label for w in st.wires)
               for st in part.strokes)


def _strip(runs: list) -> list:
    """runs without blank runs at either end."""
    while runs and not runs[0][0].strip():
        runs = runs[1:]
    while runs and not runs[-1][0].strip():
        runs = runs[:-1]
    return runs


def _label_runs(n, look: Optional[str]) -> list:
    """A node's label runs under a sim look (None: no frame): active as drawn,
    plain not bold, failed in edges.fail, muted (untouched) muted."""
    if look in (None, "active"):
        return kit.label_runs(n)
    if look == "plain":
        return kit.label_runs(n, bold=False)
    if look == "failed":
        return [(kit.node_label(n), (scene.colour_of("edges-fail"), None, True))]
    colour = kit.HOLE_COLOR if n.is_hole else kit.kind_color(n.kind)
    return [(kit.node_label(n), (kit.muted(colour), None, False))]


# ---------------------------------------------------------------------------
# Tokens — a sim frame's tokens on the cells of the paths that draw their wires
# ---------------------------------------------------------------------------

def _routes(lay: _Layout) -> dict:
    """{wire key: [cells]}: every path of a layout drawing a key (or carrying a
    driver key), in drawing order."""
    out = {}
    for p in lay.paths:
        for key in dict.fromkeys((p.stroke.key,) + p.stroke.rides):
            out.setdefault(key, []).append(p.cells)
    return out


def _token_cell(tok, lay: _Layout, routes: dict):
    """The cell of a layout a token sits on: a self-call's on its stub's ● (else
    its subject's mark); any other at the cell `at` of the way along its key's
    path (the wire's ordinal picks among the paths of one key); None when this
    layout does not draw it."""
    if tok.ident in lay.spots:
        return lay.spots[tok.ident]
    src, dst = tok.ident[:2]
    if src == dst:
        return lay.marks.get(src)
    ways = [c for c in routes.get(tuple(tok.ident[:3]), []) if c]
    if not ways:
        return None
    cells = ways[min(tok.ident[3] if len(tok.ident) > 3 else 0, len(ways) - 1)]
    return cells[round(tok.at * (len(cells) - 1))]


# ---------------------------------------------------------------------------
# compose_flow
# ---------------------------------------------------------------------------

def compose_flow(g, depth: int, payloads: bool, notes: str = "off", triggers: bool = True,
                 width: int | None = None, access: bool = False, mods: bool = False,
                 events: str = "nodes", trace=None, tick: int = 0, checks=None,
                 probe: bool = False):
    """The flow view as rows of (text, style) runs, plus its width — the same
    arguments and return as view_graph.compose(). Each part (the document or a
    section of it, then each drawn expansion and machine) is a call graph read
    left to right under its title. `payloads` / `mods`: each flow's chip on its
    wire between the columns; notes (any mode but "off"): #N tags and the notes
    listed below; `triggers`, `access`, `events`: what the Scene wires (see
    scene.build_scene). `width`: the columns to fit; a drawing wider than that
    with chips is drawn again with each chip a marker letter (┆a┆) and the
    chips listed in a panel at the bottom-right (view_graph's way). `trace`,
    `tick`: a simulation frame over the drawing, the trace named as this
    drawing's Scene names things (sim.project), as view_graph.compose takes it;
    `checks` (kit.CheckMarks named the same way): the checks overlay. `probe`:
    the frame's tokens and active labels drawn in kit.Probe styles (sim_focus)."""
    scn = scene.build_scene(g, events=events, triggers=triggers, access=access, depth=depth)
    idx = scn.notes if notes != "off" else {}
    look = (vgraph.sim_look(scn, trace.frames[tick], vgraph._trace_slots(trace), probe)
            if trace is not None else None)
    rows, drawing_w = _part_rows(scn, depth, payloads, mods, notes != "off", look, checks, None)
    tail = [[], kit.section_rule("notes"), []] + kit.note_rows(idx) if idx else []
    natural_w = max([drawing_w] + [kit.row_len(r) for r in tail])
    if width is None or natural_w <= width or not (payloads or mods):
        return kit.stretch_rules(rows + tail, natural_w), natural_w
    marks = []
    fitted, fitted_w = _part_rows(scn, depth, payloads, mods, notes != "off", look, checks, marks)
    if not marks or fitted_w >= drawing_w:
        return kit.stretch_rules(rows + tail, natural_w), natural_w
    side = [(kit._chip_marker(letter), [(text, "code")]) for letter, text in marks]
    fitted = kit.stretch_rules(fitted, max(fitted_w, width))   # a title row is taken
    fitted = kit._fit_panel(fitted, lambda tw: kit._panel_rows(side, tw), width, "br",
                            kit.CALLOUT_MAX)
    w = max([0] + [kit.row_len(r) for r in fitted + tail])
    return kit.stretch_rules(fitted + tail, w), w


def _part_rows(scn, depth, payloads, mods, notes, look, checks, marks):
    """Every part drawn, under its title, each centred within the widest; the
    tokens of a sim frame over them."""
    ctx = _Ctx(scn, depth, payloads, mods, notes, look, checks, marks)
    drawn = []
    for part in flow_parts(scn, depth):
        if not part.nodes:
            continue
        lay = _build(part, ctx)
        drawn.append((part, lay, _draw(lay, ctx)))
    if look is not None:                        # in task order: a later token wins a cell
        routes = [_routes(lay) for _p, lay, _cv in drawn]
        for tok in look.tokens:
            for (_p, lay, cv), rt in zip(drawn, routes):
                cell = _token_cell(tok, lay, rt)
                if cell is not None:
                    cv.put(cell[0], cell[1], tok.mark, tok.style)
                    break
    parts = [(part.title, None, cv) for part, _lay, cv in drawn]
    return vgraph._section_rows(parts) if parts else ([], 0)


# ---------------------------------------------------------------------------
# Legend
# ---------------------------------------------------------------------------

def flow_legend(triggers: bool = True, payloads: bool = False, access: bool = False,
                mods: bool = False, events: str = "nodes"):
    """Legend row for the flow view: each arrow's stroke and head, the trigger
    wire, an event drawn where it lands, the wire shapes (a shared trunk, a hop,
    stacked heads, a wire back along the return row), the call marks, the
    expansion marks, and the permission wires and chips when they are shown."""
    dim, mid = (kit.GREY["dim"], None, False), (kit.GREY["mid"], None, False)
    row = [("flow   ", dim)]
    for kind, word in kit.ARROW_LEGEND:
        own = scene.arrow_colour(kind)
        colour = scene.colour_of(own) if own else kit.EDGE_DEFAULT
        sample = ("◀" + kit._stroke_sample(kind) + "▶" if kind == "<->"
                  else kit._stroke_sample(kind) * 2 + _head(kind))
        row += [(sample, (colour, None, False)), (f" {word}  ", mid)]
    if triggers:
        row += [(kit._stroke_sample("trigger") * 2 + "▶", kit.edge_style("trigger")),
                (" trigger  ", mid)]
    if events == "land":
        row += [("─ <E> ─▶", (scene.colour_of("kinds-event"), None, False)), (" emits  ", mid)]
    wire = (kit.EDGE_DEFAULT, None, False)
    row += [("─┬─", wire), (" one source  ", mid), ("─┴─", wire), (" one target  ", mid),
            ("─│─", wire), (" crossing  ", mid), ("▶┐", wire), (" stacked heads  ", mid),
            ("╰──╯", wire), (" back to an earlier column  ", mid),
            ("┄‹arm›┄", (kit.EDGE_COLOR["arm"], None, False)), (" branch arm  ", mid)]
    op = kit.SYNTAX["operator"]
    row += [("↺", op), (" self-call  ", mid), ("↻", op), (" recursion  ", mid),
            ("⇱", op), (" host op  ", mid), ("▾ ▸", mid), (" expansion below / not  ", mid)]
    if access:
        acc = (kit.EDGE_COLOR["access"], None, False)
        row += [("┄┄r", acc), (" read  ", mid), ("┄┄w", acc), (" write  ", mid),
                ("┄┄b", acc), (" borrow  ", mid), ("┄┄ƀ", acc), (" borrow(read)  ", mid),
                ("1w", (kit.EDGE_COLOR["access"], None, True)), (" writers  ", mid)]
    if payloads:
        row += [("─┆{…}┆─", dim), (" payload  ", mid), ("↩", op), (" returns  ", mid)]
    if mods:
        row += [("┆@… ×N┆", (kit.SYNTAX["modifier"][0], None, False)), (" modifiers", mid)]
    return row
