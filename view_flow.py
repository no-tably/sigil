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
the graph view's sections. A control block's flows are drawn in its frame under
its part, as the graph view frames them (`╭╌ ↺ loop @while … ╌╮`, nested blocks
nested; a branch's arms are dotted wires labelled ‹arm›). A joined endpoint's
wire carries its join just before its head (`─&▶`, `─&?▶`, `─/▶`, as the tree's
`◀&`): each target of `-> [A] & [B]`, the target of `[A] & [B] ->`.

Given a width it wraps (compose_flow): chips to letters with a key, then hung
under their senders (`─a▶` over `a┆{Cart}`), then each part too wide cut between
its columns into bands joined by numbered plugs (`─▶①` … `①──┬─▶`).

compose_flow() returns the rows view.py prints, the same shape as
view_graph.compose(). Drawing primitives and styles come from viewkit.py (read
as kit.NAME, so a theme change reaches them).
"""

from __future__ import annotations

import bisect
import importlib.util
import itertools
import re
import sys
from collections import Counter
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
    view_flow.py, view_run.py and scene.py each carry a copy of this function: keep
    the copies identical."""
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
    base: object = None         # a band (_band_part): the part it is cut from
    blocks: list = field(default_factory=list)  # its control blocks' parts, framed under it
    block: object = None        # a block's part: its render.Block (the frame's title)


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
        strokes, blocks = _block_parts(u, nodes, strokes)
        if u.level == 0:
            parts += _split_sections(scn, u, nodes, strokes, blocks)
            continue
        what = "state machine" if getattr(u.graph, "role", "") == "state" else ":= { … }"
        title = f"{kit.node_label(scn.nodes[u.owner].node)} {what}"
        parent = scn.nodes[u.owner].unit
        if parent is not None and parent in titles:
            title = f"{titles[parent]}{kit.TITLE_STEP}{title}"
        titles[u.owner] = title
        parts.append(_Part(title, u.owner, u.graph, nodes, strokes, blocks=blocks))
    return parts


def _block_parts(u, nodes: dict, strokes: list):
    """(the unit's free strokes, its top-level control blocks' parts): a stroke
    inside a block (its wire's innermost, scene's Wire.block) is drawn in that
    block's part, not with the unit's — as the graph view frames it. A block's
    part holds its own strokes' ends and its members outside its nested blocks,
    whose parts it holds in turn. A node only blocks draw leaves `nodes`."""
    blocks = getattr(u.graph, "blocks", None) or []
    if not blocks:
        return strokes, []
    held, free = {}, []
    for st in strokes:
        w = st.wires[0] if st.wires else None
        if w is not None and w.owner == u.owner and w.block is not None \
                and 0 <= w.block < len(blocks):
            held.setdefault(w.block, []).append(st)
        else:
            free.append(st)
    linked = {st.src for st in free} | {st.dst for st in free}

    def part(bi):
        b = blocks[bi]
        kids = [ci for ci, c in enumerate(blocks) if c.parent == bi]
        nested = {m for ci in kids for m in blocks[ci].members}
        own = held.get(bi, [])
        keep = {st.src for st in own} | {st.dst for st in own} | (set(b.members) - nested)
        return _Part("", u.owner, u.graph, {nid: n for nid, n in nodes.items() if nid in keep},
                     own, blocks=[part(ci) for ci in kids], block=b)

    inside = {nid for sts in held.values() for st in sts for nid in (st.src, st.dst)}
    inside |= {m for b in blocks for m in list(b.members) + list(b.refs)}
    tops = [part(bi) for bi, b in enumerate(blocks) if b.parent is None]
    for nid in inside - linked:
        nodes.pop(nid, None)
    return free, tops


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


def _split_sections(scn, u, nodes: dict, strokes: list, blocks: list) -> list:
    """The document's part, or one per `--- section ---` (titled by a Rule): a
    stroke goes to the section its line is in, a node to every section a
    stroke of it is in (else the one it is written in), a block's part to the
    section of its header."""
    secs = scn.sections
    if not secs:
        return [_Part("", None, u.graph, nodes, strokes, blocks=blocks)]
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
    framed = {}
    for bp in blocks:
        framed.setdefault(kit.section_of(secs, bp.block.lines[0]), []).append(bp)
    out = []
    for i in sorted(set(groups) | set(framed)
                    | {_node_section(scn, nid) for nid in nodes if nid not in linked}):
        here = {nid: n for nid, n in nodes.items()
                if i in linked.get(nid, ()) or (nid not in linked and _node_section(scn, nid) == i)}
        title = kit.Rule(kit.section_name(secs[i])) if i >= 0 else ""
        out.append(_Part(title, None, u.graph, here, groups.get(i, []), blocks=framed.get(i, [])))
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

    CORNERS = ROUND


@dataclass
class _Vx:
    """A vertex: a node (its label), a chip on a wire, a dummy a wire runs
    straight through in a column it skips, or a band's plug (a cut wire's
    numbered end, glued to its stroke: `─▶①` / `①─`)."""
    id: str
    what: str                   # "node" | "chip" | "dummy" | "plug"
    runs: list = field(default_factory=list)
    col: int = 0
    row: int = 0
    heads: list = field(default_factory=list)   # a node's in-ports: one per arrow kind, stacked
    stubs: list = field(default_factory=list)   # a node's self-call stubs (view_graph._Stub)
    ins: list = field(default_factory=list)     # (vertex id, segment) in
    outs: list = field(default_factory=list)    # (vertex id, segment) out
    mark: int = -1              # column of its self-call mark in its runs (-1: none)
    floor: int = 0              # the highest row it may take (moved down to untangle)
    hung: list = field(default_factory=list)    # its hung rows (runs each): see _hang

    @property
    def width(self) -> int:
        w = kit.row_len(self.runs)
        return max([w] + [st.width() for st in self.stubs] + [kit.row_len(r) for r in self.hung])

    @property
    def label_w(self) -> int:
        return kit.row_len(self.runs)

    @property
    def hung_at(self) -> int:
        """The row (from its label's) its hung rows start on: under its stacked
        heads and its self-call stubs."""
        return max(len(self.heads), 1 + len(self.stubs), 1)

    @property
    def height(self) -> int:
        return self.hung_at + len(self.hung)

    @property
    def solid(self) -> bool:
        """A wire ends at it (a node or a plug), not runs on through it."""
        return self.what in ("node", "plug")


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
    letter: Optional[str] = None    # a hung chip's letter (_Hung), drawn in its wire
    ret: int = 0                # a back path: its return row
    tin: int = 0                # a back path: the x of its track into the target
    tout: int = 0               # … and out of the source
    chip_at: tuple = (0, 0)     # a back path's chip: its first cell (_return_chips)
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
    isolated_at: dict = field(default_factory=dict)  # unconnected node id → its cell (_draw)


def _head(kind: str) -> str:
    """A wire's head: ✖ for `!>`, a permission's access letter, else ▶."""
    if kind == "!>":
        return "✖"
    if kind.startswith("access:"):
        return kind[-1]
    return "▶"


def _join_mark(p: "_Path") -> str:
    """The join a path's wire enters (`-> [A] & [B]`) or leaves (`[A] & [B] ->`),
    drawn just before its head (`─&▶`, `─&?▶`, `─/▶`, as the tree's `◀&`); ""
    when none, or when the path ends at a band's cut end (its target draws it)."""
    for w in p.stroke.wires:
        mark = w.join.get("dst") or w.join.get("src")
        if mark:
            return mark
    return ""


def _wire_chips(part: _Part, ctx: "_Ctx") -> dict:
    """{stroke key: its chips (ctx.chips)} of a part's wires between two nodes,
    in stroke order: the order the chips' letters are handed out in."""
    return {st.key: ctx.chips(part, st) for st in part.strokes if st.src != st.dst}


def _build(part: _Part, ctx: "_Ctx", band: "_BandSpec | None" = None,
           place: bool = True, selfs: dict | None = None,
           chips: dict | None = None) -> _Layout:
    """A part's vertices and paths, columns, rows and channels. `band`: the part
    is one band of a wrapped part (_band_part): its columns are fixed, and its
    plugs are vertices of their own. `place`: False — the vertices and their
    columns only, no rows or channels (a part a run's frame cuts into bands as
    the first frame did: _banded reads its columns, never its rows). `selfs`,
    `chips`: the part's ctx.selfs_of and _wire_chips when this frame worked
    them out already (each hands out letters, once a frame)."""
    lay = _Layout(part)
    ids = list(part.nodes)
    selfs = ctx.selfs_of(part) if selfs is None else selfs
    for nid in ids:
        lay.V[nid] = _Vx(nid, "node", ctx.label(part, nid, selfs), stubs=list(
            selfs[nid].stubs if nid in selfs else ()))
        lay.V[nid].mark = ctx.mark_at.get((id(part), nid), -1)
    for pl in band.plugs if band is not None else ():
        lay.V[pl.vid] = _Vx(pl.vid, "plug", [(pl.label, pl.style)])
    strokes = [st for st in part.strokes if st.src != st.dst]
    linked = {st.src for st in strokes} | {st.dst for st in strokes}
    lay.isolated = [nid for nid in ids if nid not in linked]
    col = (band.col if band is not None
           else _columns([nid for nid in ids if nid in linked], strokes))
    chips = _wire_chips(part, ctx) if chips is None else chips
    if ctx.hang:
        _hang(lay, part, ctx, strokes, col, chips)
    # A column of chips after a node column when a flow from it carries one.
    chipped = {col[st.src] for st in strokes if col[st.dst] > col[st.src]
               and any(not isinstance(c, _Hung) for c in chips[st.key])}
    at = {c: c + sum(1 for k in chipped if k < c) for c in set(col.values())}
    k = 0
    for st in strokes:
        style = ctx.style(st)
        for item in chips[st.key] or [None]:
            runs = None if isinstance(item, _Hung) else item
            a, b = col[st.src], col[st.dst]
            p = _Path(st, style, runs, [st.src], back=b <= a, head=_head(st.kind))
            if isinstance(item, _Hung):
                p.letter = item.letter
            if band is not None and st.dst in band.outs:
                p.head = "▶"                    # a cut end's head: the real one is at its target
            for c in range(at[a] + 1, at[b]) if not p.back else ():
                k += 1
                is_chip = runs is not None and c == at[a] + 1
                vid = f"\0{'c' if is_chip else 'd'}{k}"
                lay.V[vid] = _Vx(vid, "chip" if is_chip else "dummy",
                                 list(runs) if is_chip else [], col=c)
                p.via.append(vid)
            p.via.append(st.dst)
            lay.paths.append(p)
    for vid, c in col.items():
        lay.V[vid].col = at[c]
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
    if not place:
        return lay
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
    else:
        if band is not None and _crossed(lay):  # no row parts them: the rows as walked
            for v in lay.V.values():
                v.floor = 0
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
    if not v.solid or vid != p.via[-1]:
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
            if not V[w].solid and end in seen:          # a wire on to a placed node:
                chain = [c for c in path.via if not V[c].solid]
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
    while not lay.V[vid].solid and lay.V[vid].ins:
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
    lead = _back_bundles(paths)
    ins = {}                                    # a bundle's lead → the rows it turns into
    for pi, li in lead.items():
        ins.setdefault(li, set()).add(_in_row(lay, paths[pi], paths[pi].via[-1]))
    for li, rows in ins.items():
        dst = V[paths[li].via[-1]]
        groups.setdefault(dst.col - 1, []).append(_Group(("in", li), None, frozenset(rows), True))
    for gs in groups.values():
        for gr in gs:
            lay.groups[gr.gid] = gr
    widths = [max((V[vid].width for vid in column), default=0) for column in lay.cols]
    room = {}                                   # column → the cells its join marks take
    for p in paths:
        dst = V[p.via[-1]]
        if dst.what == "node":
            room[dst.col] = max(room.get(dst.col, 0), len(_join_mark(p)))
    first = min(groups, default=0)
    x = 0
    if first < 0:                               # the left margin's tracks
        tracks = _tracks(groups[-1])
        x = _place_tracks(lay, tracks, -1) + 4
    for c, column in enumerate(lay.cols):
        x += room.get(c, 0)
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
            p.tin = lay.track[("in", lead[pi])]
    y = lay.bottom
    rets = {}                                   # group id → the return rows it turns into
    order = sorted(ins, key=lambda li: (paths[li].tout - paths[li].tin, paths[li].tin))
    for k, li in enumerate(order):
        bundle = [paths[pi] for pi, l in lead.items() if l == li]
        for p in bundle:                        # the shorter ones higher, a bundle on one row
            p.ret = y
        lead_p = paths[li]
        chipped = [p for p in bundle if p.chip is not None]
        # the bundles still to come return lower: their ways down and up cross these rows
        later = {x for lj in order[k + 1:] for x in (paths[lj].tin, paths[lj].tout)}
        spots = _return_chips([kit.row_len(p.chip) for p in chipped],
                              lead_p.tin + 2, lead_p.tout - 3, later)
        for p, (x, dy) in zip(chipped, spots):
            p.chip_at = (x, y + dy)
        y += 1 + max((dy for _x, dy in spots), default=0)
        rets.setdefault(("out", lead_p.via[0]), set()).add(lead_p.ret)
        rets.setdefault(("in", li), set()).add(lead_p.ret)
    for gid, gr in lay.groups.items():          # the cells a vertical only passes
        if gr.straight or gid not in lay.track:
            continue
        turns = set(gr.dsts) | ({gr.src} if gr.src is not None else set()) | rets.get(gid, set())
        for yy in range(gr.lo, max(turns) + 1):
            if yy not in turns:
                lay.passes[(lay.track[gid], yy)] = gid


def _back_bundles(paths: list) -> dict:
    """{back path index: the index of its bundle's first path}: the wires back
    from one source to one target share one return row and one way up, splitting
    only into their stacked heads (`╭─✖┐` over `├─▶┘`); their chips share the
    return row too (_return_chips)."""
    lead, first = {}, {}
    for pi, p in enumerate(paths):
        if p.back:
            lead[pi] = first.setdefault((p.via[0], p.via[-1]), pi)
    return lead


def _bundle_looks(paths: list, ctx: "_Ctx") -> dict:
    """{cell: style} for the cells a back bundle's wires share (their way down,
    return row and way up): the look of its most severe member (_share_rank:
    the graph view's rule for a fan-out's shared cells) — so a bundled wire the
    run took reads as taken, and an error wire reads as one, along its whole
    way, not only at its head. A bundle whose top rank two members hold keeps
    the nearest-owner rule."""
    bundles = {}                                # lead index → [_Path]
    for pi, li in _back_bundles(paths).items():
        bundles.setdefault(li, []).append(paths[pi])
    out = {}
    for bundle in bundles.values():
        if len(bundle) < 2:
            continue
        ranks = [_share_rank(ctx, p) for p in bundle]
        top = max(ranks)
        if ranks.count(top) > 1:
            continue
        best = bundle[ranks.index(top)]
        count = {}
        for p in bundle:
            for cell in set(p.cells[:-1]):      # its head stays its own
                count[cell] = count.get(cell, 0) + 1
        out.update({cell: best.style for cell, n in count.items() if n > 1})
    return out


def _share_rank(ctx: "_Ctx", p: _Path) -> tuple:
    """view_graph.share_rank of a path's wire, in its run state when there is
    a run: the one rule both views share for cells several wires run along."""
    return vgraph.share_rank(p.stroke.kind, ctx.state(p.stroke))


def _return_chips(widths: list, lo: int, hi: int, blocked: set) -> list:
    """[(x, dy)]: where the chips of one back bundle's chipped wires go
    (`widths`, in order): side by side, one stroke apart, when they fit in the
    return row's cells lo..hi; else stacked a row each, from the return row
    when the first fits there, else from the row under it. Each chip keeps a
    cell clear of every vertical in `blocked` (the xs of other bundles' ways
    down and up through these rows), starting after one it would cover."""
    row, at = [], lo
    for w in widths:
        x = _clear_of(at, w, blocked)
        row.append((x, 0))
        at = x + w + 1
    if not widths or at - 2 <= hi:
        return row
    first = int(_clear_of(lo, widths[0], blocked) + widths[0] - 1 > hi)
    return [(_clear_of(lo, w, blocked), first + k) for k, w in enumerate(widths)]


def _clear_of(x: int, w: int, blocked: set) -> int:
    """The first x from `x` where a chip `w` cells wide keeps a cell clear of
    every vertical in `blocked` on either side."""
    while True:
        hit = [b for b in blocked if x - 1 <= b <= x + w]
        if not hit:
            return x
        x = max(hit) + 2


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
    chip or a plug's number, at the column's start for a dummy (its wire runs
    straight through)."""
    v = lay.V[vid]
    x = lay.colx[v.col]
    if v.what == "node":
        return x + v.label_w + 1
    return x + v.label_w if v.what in ("chip", "plug") else x - 1


def _in_x(lay: _Layout, vid: str) -> int:
    """Where a wire ends at a vertex: a node's head cell (a blank before its
    label), the cell before a chip, a dummy or a plug's number (its head glued
    to it: `─▶①`)."""
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


def _draw(lay: _Layout, ctx: "_Ctx", isolated: bool = True) -> _Canvas:
    """A layout on a canvas; `isolated`: its unconnected nodes too, in rows under
    it (a wrapped part draws them once, under its bands; where each went is
    kept in lay.isolated_at)."""
    cv = _Canvas()
    _paint(cv, lay, ctx, lay.paths, [vid for vid, v in lay.V.items()
                                     if vid not in lay.isolated and v.what != "dummy"])
    if isolated and lay.isolated:
        y = (max(cv.h, lay.bottom) + 1) if (cv.h or lay.bottom) else 0
        lay.isolated_at = _draw_isolated(cv, lay, ctx, y, lay.spots, lay.marks)
    return cv


def _paint(cv: _Canvas, lay: _Layout, ctx: "_Ctx", paths: list, vids: list) -> None:
    """Some of a layout's paths (in lay.paths order) and placed vertices drawn on
    cv as _draw draws them all: the paths' lines, their shared cells' styles,
    heads, join marks and letters, then the vertices, then the back paths'
    chips. A cell one of them shares with a path or vertex left out comes out
    as that one's absence draws it (_Kept paints sets that share none)."""
    traces = []
    for p in paths:
        p.cells = _draw_path(cv, lay, p)
        tr = vgraph._Trace(p.style, False, p.stroke.kind == "<->", edge=None)
        tr.cells = list(p.cells)
        traces.append(tr)
    for cell, st in vgraph._nearest_owners(traces, cv.lines).items():
        cv.lines[cell][2] = st
    for cell, st in _bundle_looks(paths, ctx).items():
        if cell in cv.lines:
            cv.lines[cell][2] = st
    for p in paths:                             # heads, and a `<->`'s source end
        dst = lay.V[p.via[-1]]
        if dst.solid and p.cells:
            cv.put(*p.cells[-1], p.head, p.style)
            if dst.what == "node":
                _put_join(cv, paths, p)
        if p.stroke.kind == "<->" and len(p.cells) > 1:  # its own first cell, else by its head
            shared = sum(q.via[0] == p.via[0] for q in lay.paths) > 1
            at = p.cells[-2] if shared and len(p.cells) > 2 else p.cells[0]
            cv.put(*at, "◀", p.style)
    _put_letters(cv, lay, paths)
    for vid in vids:
        _put_vertex(cv, lay, ctx, vid)
    for p in paths:                             # a back path's chip on its return row
        if p.back and p.chip is not None:
            kit._put_runs(cv, *p.chip_at, p.chip)


def _put_vertex(cv: _Canvas, lay: _Layout, ctx: "_Ctx", vid) -> None:
    """A placed vertex at its column and row: its runs, a node's stacked in-port
    marks, self-call stubs (their ● cells into lay.spots, its mark's into
    lay.marks) and hung rows."""
    v = lay.V[vid]
    x, y = lay.colx[v.col], v.row
    kit._put_runs(cv, x, y, v.runs)
    if v.what != "node":
        return
    if len(v.heads) > 1:
        last = len(v.heads) - 1
        for j in range(last + 1):
            mark = BUNDLE[0] if j == 0 else BUNDLE[2] if j == last else BUNDLE[1]
            cv.put(x - 1, y + j, mark, kit.FRAME_STYLE)
    lay.spots.update(_draw_stubs(cv, x, y, v.stubs, ctx.styles))
    if v.mark >= 0:
        lay.marks[v.id] = (x + v.mark, y)
    for k, row in enumerate(v.hung):
        kit._put_runs(cv, x, y + v.hung_at + k, row)


def _draw_isolated(cv: _Canvas, lay: _Layout, ctx: "_Ctx", y: int, spots: dict,
                   marks: dict) -> dict:
    """A layout's unconnected nodes from row y, wrapped at the drawing's width
    (at most ISOLATED_WRAP, or the width fitted to when that is narrower); the
    cells of their stubs' ● and self-call marks into spots / marks. Returns
    {node id: the cell it was drawn from}."""
    x, row_h, at = 0, 1, {}
    wrap = max(cv.w, min(ISOLATED_WRAP, ctx.width or ISOLATED_WRAP))
    for nid in lay.isolated:
        v = lay.V[nid]
        if x and x + v.width > wrap:
            x, y, row_h = 0, y + row_h, 1
        at[nid] = (x, y)
        _put_isolated(cv, v, ctx, x, y, spots, marks)
        row_h = max(row_h, v.height)
        x += v.width + ISOLATED_GAP
    return at


def _put_isolated(cv: _Canvas, v: _Vx, ctx: "_Ctx", x: int, y: int, spots: dict,
                  marks: dict) -> None:
    """An unconnected node at (x, y): its runs and self-call stubs."""
    kit._put_runs(cv, x, y, v.runs)
    spots.update(_draw_stubs(cv, x, y, v.stubs, ctx.styles))
    if v.mark >= 0:
        marks[v.id] = (x + v.mark, y)


_STRAIGHT = (kit.L | kit.R, kit.U | kit.D)


def _put_join(cv: _Canvas, paths: list, p: _Path) -> None:
    """A path's join mark (_join_mark) in the cells before its head, in the room
    _channels left there; not where a wire with another mark (or none) shares
    those cells: the mark would read as that wire's too."""
    mark = _join_mark(p)
    n = len(mark)
    if not mark or len(p.cells) < n + 2:
        return
    cells = p.cells[-1 - n:-1]
    y = p.cells[-1][1]
    if any(c[1] != y for c in cells) or any(
            c in q.cells and _join_mark(q) != mark for q in paths if q is not p
            for c in cells):
        return
    cv.put(cells[0][0], y, mark, kit.LABEL_STYLE)


def _put_letters(cv: _Canvas, lay: _Layout, paths: list) -> None:
    """Each hung chip's letter in its wire, on the wire's last own straight cell
    (one no other wire draws or crosses: before a shared last run's junction,
    after a trunk's branch), so the wire keeps its length: `─b▶`, `├c▶`,
    `──b┬`. An access head is a letter itself: one stroke stays between them."""
    used = Counter(c for p in paths for c in set(p.cells))
    for p in paths:
        if p.letter is None or len(p.cells) < 2:
            continue
        end = len(p.cells) - (1 if p.head in ("▶", "✖") else 2)
        if lay.V[p.via[-1]].what == "node":     # before its join mark
            end -= len(_join_mark(p))
        way = p.cells[:max(end, 1)]
        own = [c for c in way if used[c] == 1]
        straight = {c for c in own if c in cv.lines and cv.lines[c][0] in _STRAIGHT}
        n = len(p.letter)                       # aa …: as many cells along its row
        fits = [(x, y) for x, y in own if all((x - i, y) in straight
                                              and cv.lines[(x - i, y)][0] == kit.L | kit.R
                                              for i in range(n))]
        pick = [c for c in own if c in straight] if n == 1 else fits
        x, y = (pick or own or way)[-1]
        cv.put(x - n + 1, y, p.letter, kit.PAYLOAD_STYLE)


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
    labels are made, the column of each label's self-call mark (mark_at).
    `hang`: what is written on a wire, and a label's notes and modifiers, hang
    under the node (see _hang); `width`: the columns fitted to (None: natural)."""

    def __init__(self, scn, depth: int, payloads: bool, mods: bool, notes: bool,
                 look=None, checks=None, marks: list | None = None, hang: bool = False,
                 width: int | None = None, tags: dict | None = None):
        """`tags`: vgraph._tags(scn, notes, mods) when worked out already."""
        self.scn, self.depth, self.payloads, self.mods = scn, depth, payloads, mods
        self.look, self.checks, self.letters = look, checks, marks
        self.hang, self.width = hang, width
        self._selfs = {}                        # (graph, owner) → its self-calls (hung)
        self.tags = dict(tags if tags is not None else vgraph._tags(scn, notes, mods))
        self.hung_tags = {}                     # node id → its label's tags that hang
        if hang:
            plain = vgraph._tags(scn, False, False)
            node_mods = vgraph._node_mods(scn.graph) if mods else {}
            for nid, sn in scn.nodes.items():
                runs = kit.note_tag_runs(kit.node_notes(sn.notes)) if notes else []
                if nid in node_mods:
                    runs += [(" ", None)] + kit.mod_runs(node_mods[nid])
                if _strip(runs):
                    self.hung_tags[nid] = _strip(runs)
                if nid in plain:
                    self.tags[nid] = plain[nid]
                else:
                    self.tags.pop(nid, None)
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
        self.hung = {}                          # (id(base part), wire key) → [_Hung]
        self.hung_rows = {}                     # (id(base part), node id) → its hung rows
        self.hung_letters = {}                  # id(base part) → its strokes lettered so far

    def style(self, st: _Stroke) -> tuple:
        """A stroke's style: its key's (a driver ⇢ owner edge: the driver wire's),
        else its arrow's, muted under a sim frame."""
        for key in (st.key,) + st.rides:
            if key in self.styles:
                return self.styles[key]
        return vgraph._unkeyed_style(st.kind, self.look is not None)

    def state(self, st: _Stroke) -> Optional[str]:
        """A stroke's run state ("active", "trail", "inactive", "failed"; see
        style for the key it reads), None with no run or no keyed wire."""
        states = self.look.states if self.look is not None else {}
        for key in (st.key,) + st.rides:
            if key in self.styles:
                return states.get(key)
        return None

    def selfs_of(self, part: _Part) -> dict:
        """{node id: view_graph._Selfs} of the part's nodes that call themselves."""
        key = (id(part.graph), part.owner)
        if self.hang and key in self._selfs:    # a band: its part's, worked out once
            out = dict(self._selfs[key])
        else:
            calls = scene.self_calls(self.scn, part.owner)
            out = vgraph._self_calls(part.graph, calls, self.payloads, self.mods,
                                     None if self.hang else self.letters)
            if self.hang:                       # no letters handed out: the same every time
                self._selfs[key] = dict(out)
        for st in part.strokes:                 # a self-edge that is no call (a machine's)
            if st.src == st.dst and st.src in part.nodes and st.src not in out:
                out[st.src] = vgraph._Selfs("↺", [])
        return {nid: s for nid, s in out.items() if nid in part.nodes}

    def label_key(self, nid: str) -> tuple:
        """What label() reads of a node that a sim frame changes — its lead,
        look, probe and tags (a frame's badges among them): within one plan
        (the same Scene, options and overlay) equal keys, equal labels."""
        tags = self.tags.get(nid)
        if self.look is None:
            return (tags,)
        return (self.look.lead.get(nid), self.look.looks.get(nid), nid in self.look.probe, tags)

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
        view_graph._tags's runs) as bare text on the first; [] when none. Hung
        (self.hang): [_Hung] instead, the same text, each lettered once per
        part, from a (a band's stroke takes the letters of its part's)."""
        key = (id(part.base or part), st.key)
        if self.hang and key in self.hung:
            return self.hung[key]
        if part.owner not in self.chip_lists:
            self.chip_lists[part.owner] = (scene.chip_lists(self.scn, self.payloads, self.mods,
                                                            unit=part.owner)
                                           if self.payloads or self.mods else {})
        texts = self.chip_lists[part.owner].get(st.key, []) if st.role in ("flow", "emit") else []
        dim = (kit.GREY["dim"], None, False)
        bare = self._bare(part, st)
        if self.hang:                           # one wire, one letter: its calls listed
            calls = [vgraph._chip_runs(text, kit.chip_parts(st.wires[0], self.payloads,
                                                            self.mods)[1]) for text in texts]
            self.hung[key] = []
            if calls or bare:
                k = self.hung_letters.get(key[0], 0)
                self.hung[key].append(_Hung(kit._letter(k), calls, bare))
                self.hung_letters[key[0]] = k + 1
            return self.hung[key]
        out = []
        for text in texts:
            if self.letters is not None:
                letter = kit._letter(len(self.letters))
                self.letters.append((letter, text))
                out.append([("┆", dim), (letter, kit.PAYLOAD_STYLE), ("┆", dim)])
            else:
                mtext = kit.chip_parts(st.wires[0], self.payloads, self.mods)[1]
                out.append([("┆", dim)] + vgraph._chip_runs(text, mtext) + [("┆", dim)])
        if bare:
            bare = [(" ", None)] + bare + [(" ", None)]
            if out:
                out[0] = out[0] + bare
            else:
                out.append(bare)
        return out

    def _bare(self, part: _Part, st: _Stroke) -> list:
        """What the graph view writes beside a stroke's head (a transition's or an
        arm's label, view_graph._tags's runs: `↩`, a landed event's name, a
        path's `[A]/`, #N), led by a qualified source path's `from [A]/`, as
        runs with no blank at either end."""
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
        return bare


# ---------------------------------------------------------------------------
# Hanging — (b) of the wrap ladder: what is written on a wire, and a label's
# notes and modifiers, hang under the node in a rail; the wire keeps a letter
#
#     (Shopper) ─a▶ [API] ───────────────┬b▶ [Payments]
#     #1            #3                   ├─✖ <PaymentFailed>
#     a┆{Cart}      b┆charge(total)      ├c▶ |Orders|
#                    ┆×3 @timeout 2s #2  ╰╌▶ <OrderPlaced>
# ---------------------------------------------------------------------------

HANG = 18                       # the text cells a hung block wraps at, at least


class _Hung(NamedTuple):
    """What a stroke has written on it, hung under its sender: its letter, the
    chip of each call it carries (runs each; two calls on one stroke draw as
    one wire here, as nothing sits between them to part them), and its bare
    text."""
    letter: str
    calls: list
    bare: list


def _hang(lay: _Layout, part: _Part, ctx: "_Ctx", strokes: list, col: dict,
          chips: dict) -> None:
    """Each node's hung rows: its label's #N notes and modifiers, then a block
    per out-stroke with something written on it (written order, a wire back to
    an earlier column last), each `b┆text` with ` ┆` continuing it (a call per
    row at least), wrapped at its label's width or HANG. A band takes the rows
    its part's nodes were given."""
    dim = (kit.GREY["dim"], None, False)
    base = part.base or part
    by_src = {}
    for st in strokes:
        by_src.setdefault(st.src, []).append(st)
    for nid in part.nodes:
        key = (id(base), nid)
        if key not in ctx.hung_rows:
            v = lay.V[nid]
            budget = max(v.label_w, HANG)
            rows = _wrap_runs(ctx.hung_tags[nid], budget) if nid in ctx.hung_tags else []
            outs = sorted(by_src.get(nid, ()), key=lambda st: col[st.dst] <= col[st.src])
            for item in (it for st in outs for it in chips[st.key] if isinstance(it, _Hung)):
                body = [row for runs in item.calls for row in _wrap_runs(runs, budget)]
                if item.bare and body and (kit.row_len(body[-1]) + 1
                                           + kit.row_len(item.bare) <= budget):
                    body[-1] = body[-1] + [(" ", None)] + item.bare
                elif item.bare:
                    body += _wrap_runs(item.bare, budget)
                for k, row in enumerate(body):
                    lead = item.letter if k == 0 else " " * kit.cell_width(item.letter)
                    rows.append([(lead, kit.PAYLOAD_STYLE if k == 0 else None),
                                 ("┆", dim)] + row)
            ctx.hung_rows[key] = rows
        lay.V[nid].hung = ctx.hung_rows[key]


_BREAKS = ((" ┆ ", 3), (" ↩ ", 1), (" => ", 1), (" @", 1), (" ", 1))   # (seam, cells it takes)
_MOD = re.compile(r"@.*?(?= @| #| ┆ |$)")    # a modifier with its arguments: never broken


def _wrap_runs(runs: list, budget: int) -> list:
    """[runs]: runs in rows of at most `budget` cells, broken at a ` ┆ ` seam
    first, then before a ` ↩ ` / ` => `, then before a modifier, then at a space
    (the break's blanks and seam dropped); a modifier (`@timeout 2s`) or a word
    longer than the budget stays whole."""
    cells = [(ch, st) for text, st in runs for ch in text]
    rows = []
    while kit.cell_width("".join(ch for ch, _st in cells)) > budget:
        cut = _wrap_at("".join(ch for ch, _st in cells), budget)
        if cut is None:
            break
        rows.append(cells[:cut[0]])
        cells = cells[cut[1]:]
    rows.append(cells)
    out = []
    for row in rows:
        merged = []
        for ch, st in row:
            if merged and merged[-1][1] == st:
                merged[-1][0] += ch
            else:
                merged.append([ch, st])
        out.append(_strip([(t, st) for t, st in merged]))
    return out


def _wrap_at(text: str, budget: int):
    """(end of this row, start of the next) for _wrap_runs, or None: no break.
    Indexes are characters; the budget is columns."""
    inside = {i for m in _MOD.finditer(text) for i in range(m.start() + 1, m.end())}
    found = [(level, i, size) for level, (seam, size) in enumerate(_BREAKS)
             for i in range(1, len(text)) if text.startswith(seam, i) and i not in inside]
    near = [f for f in found if kit.cell_width(text[:f[1]]) <= budget]
    if near:
        level = min(f[0] for f in near)
        _lv, i, size = max(f for f in near if f[0] == level)
        return i, i + size
    if found:
        _lv, i, size = min(found, key=lambda f: (f[1], f[0]))
        return i, i + size
    return None


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
# Whole parts kept — a part drawn whole (not cut into bands) during a run is
# laid out once and kept; each frame paints again only the units (wires and
# vertices whose cells meet) of which something looks different
# ---------------------------------------------------------------------------

class _Unit(NamedTuple):
    """Elements of a layout painted apart from the rest (_units): no cell of
    theirs is drawn by anything outside them."""
    paths: list                 # indices into lay.paths, in order
    vids: list                  # placed vertices
    lone: list                  # unconnected node ids (lay.isolated_at)
    cells: frozenset


def _whole(part: _Part, ctx: "_Ctx", keep: dict | None, lay: _Layout | None = None) -> "_Drawn":
    """part drawn whole, from `lay` when this frame laid it out already. `keep`
    (a plan slot's dict: {} on a run's first frame): the drawing kept from
    frame to frame — laid out once (its strokes and self-calls are the plan's
    Scene's), and while every label a frame changes keeps its width only the
    units whose look changed are painted again (_repaint); the canvas is the
    kept one, a frame's tokens go over it as overlays (_Drawn.kept)."""
    if keep is None:
        lay = lay or _build(part, ctx)
        cv = _draw(lay, ctx)
        return _Drawn(cv, lay.spots, lay.marks, _routes(lay))
    selfs = chips = None
    if lay is None:                             # what _build reads that a frame changes
        selfs = ctx.selfs_of(part)              # (each hands out letters once a frame)
        chips = _wire_chips(part, ctx) if ctx.letters is not None else None
    if lay is None and "lay" in keep:
        kept = keep["lay"]
        keys = {nid: ctx.label_key(nid) for nid in part.nodes}
        fresh = {nid: ctx.label(part, nid, selfs) for nid, k in keys.items()
                 if k != keep["keys"][nid]}
        if all(kit.row_len(r) == kit.row_len(kept.V[nid].runs) for nid, r in fresh.items()):
            for nid, r in fresh.items():
                kept.V[nid].runs = r
            for p in kept.paths:
                p.style = ctx.style(p.stroke)
            keep["keys"] = keys
            keep["looks"] = _repaint(keep["cv"], kept, ctx, keep["units"], keep["owner"],
                                     keep["looks"])
            return _Drawn(keep["cv"], kept.spots, kept.marks, keep["routes"], kept=True)
    lay = lay or _build(part, ctx, selfs=selfs, chips=chips)
    cv = _draw(lay, ctx).keep_rows()            # its paths' cells, then its units
    units = _units(lay, ctx)
    keep.update(lay=lay, cv=cv, routes=_routes(lay), units=units, looks=_looks(lay, ctx),
                keys={nid: ctx.label_key(nid) for nid in part.nodes},
                owner={e: k for k, u in enumerate(units) for e in _elements(u)})
    return _Drawn(cv, lay.spots, lay.marks, keep["routes"], kept=True)


def _elements(u: _Unit):
    """A unit's elements as _looks names them."""
    yield from (("p", pi) for pi in u.paths)
    yield from (("v", vid) for vid in u.vids + u.lone)


def _looks(lay: _Layout, ctx: "_Ctx") -> dict:
    """{element: its look}: what a frame changes of each path (its style, its
    run state: a back bundle's look) and vertex (its runs, its stubs' strokes)."""
    out = {("p", pi): (p.style, ctx.state(p.stroke)) for pi, p in enumerate(lay.paths)}
    for vid, v in lay.V.items():
        if v.what != "dummy":
            out[("v", vid)] = (v.runs, tuple(ctx.styles.get(sb.wire.key) for sb in v.stubs))
    return out


def _units(lay: _Layout, ctx: "_Ctx") -> list:
    """[_Unit] of a drawn layout (_draw): paths and vertices whose cells meet,
    and the wires of one back bundle (their look is their busiest's), in one
    unit; each unit's cells are what its elements draw (a path: its line,
    head, join mark, letters, chip; a vertex: what _put_vertex puts)."""
    elems, parent, lone = {}, {}, set(lay.isolated)

    def find(e):
        while parent[e] != e:
            parent[e] = parent[parent[e]]
            e = parent[e]
        return e

    def add(e, cells):
        elems[e] = cells
        parent[e] = e

    for pi, p in enumerate(lay.paths):
        cells = set(p.cells)
        if p.letter:                            # somewhere along its own cells' rows
            cells |= {(x - k, y) for x, y in p.cells for k in range(len(p.letter))}
        if p.back and p.chip is not None:
            x, y = p.chip_at
            cells |= {(x + k, y) for k in range(kit.row_len(p.chip))}
        add(("p", pi), cells)
    for vid, v in lay.V.items():
        if v.what == "dummy":
            continue
        cv = _Canvas()
        if vid in lone:
            _put_isolated(cv, v, ctx, *lay.isolated_at[vid], {}, {})
        else:
            _put_vertex(cv, lay, ctx, vid)
        add(("v", vid), cv.text.keys() | cv.lines.keys())
    owner = {}
    for e, cells in elems.items():
        for cell in cells:
            other = owner.setdefault(cell, e)
            if other != e:
                parent[find(e)] = find(other)
    for pi, li in _back_bundles(lay.paths).items():
        parent[find(("p", pi))] = find(("p", li))
    groups = {}
    for e in elems:
        groups.setdefault(find(e), []).append(e)
    units = []
    for members in groups.values():
        vids = [vid for kind, vid in members if kind == "v"]
        units.append(_Unit(sorted(pi for kind, pi in members if kind == "p"),
                           [vid for vid in vids if vid not in lone],
                           [vid for vid in vids if vid in lone],
                           frozenset().union(*(elems[e] for e in members))))
    return units


def _repaint(cv: _Canvas, lay: _Layout, ctx: "_Ctx", units: list, owner: dict,
             looks: dict) -> dict:
    """A kept canvas brought to the frame `lay` and `ctx` now draw: the last
    frame's overlays cleared, then the units with an element whose look
    differs from `looks` painted afresh (together: no two share a cell) and
    their cells patched in. Returns the looks now."""
    cv.clear_overlay()
    now = _looks(lay, ctx)
    dirty = [units[k] for k in sorted({owner[e] for e, look in now.items()
                                       if looks.get(e) != look})]
    if dirty:
        vids = {vid for u in dirty for vid in u.vids}
        fresh = _Canvas()
        paths = sorted(pi for u in dirty for pi in u.paths)
        _paint(fresh, lay, ctx, [lay.paths[pi] for pi in paths],
               [vid for vid in lay.V if vid in vids])
        for u in dirty:
            for nid in u.lone:
                _put_isolated(fresh, lay.V[nid], ctx, *lay.isolated_at[nid], lay.spots,
                              lay.marks)
        cv.patch(fresh, frozenset().union(*(u.cells for u in dirty)))
    return now


# ---------------------------------------------------------------------------
# Bands — (c) of the wrap ladder: a part too wide for the width is cut between
# its call-depth columns into bands stacked down the page; a wire cut at a
# band's right edge ends in a numbered plug and resumes at the start of the
# band it lands in
#
#     (Shopper) ─a▶ [API] ─────────────────▶①
#     a┆{Cart}      b┆charge(total)
#
#     ①──┬b▶ [Payments]
#        ╰╌▶ <OrderPlaced> ═══╦═▶ [Email]
# ---------------------------------------------------------------------------

BAND_SEARCH = 12                # columns up to which every cut set is tried (else greedy)


@dataclass
class _Plug:
    vid: str
    label: str                  # `①`, `①↑` (a cut end resuming in a band above)
    style: tuple


@dataclass
class _BandSpec:
    """One band's columns (node or plug id → column) and plugs; `outs`: the ids
    of its cut ends."""
    col: dict
    plugs: list
    outs: set


class _Drawn(NamedTuple):
    """A part drawn: its canvas, the cells a token may sit on (self-call stubs'
    ● and marks), and its wires' routes (_routes)."""
    cv: object
    spots: dict
    marks: dict
    routes: dict
    kept: bool = False          # cv is kept from frame to frame (_whole): tokens overlay it


plug_label = kit.plug_label                     # ① … ⑳, «21» … (the tree's folded lanes too)


def _cut_groups(strokes: list, col: dict, starts: tuple) -> dict:
    """{(source, band it lands in): [strokes]}: the strokes a cut set cuts
    (`starts`: the first column of each band after the first), by plug."""
    def band(c):
        return bisect.bisect_right(starts, c)
    out = {}
    for st in strokes:
        k, j = band(col[st.src]), band(col[st.dst])
        if k != j:
            out.setdefault((st.src, j), []).append(st)
    return out


class _BandIndex(NamedTuple):
    """A part's nodes and strokes by column, so a band is cut from what it
    touches alone (a long part cut into many bands stays linear)."""
    by_col: dict                # column → [node id]
    touching: dict              # node id → [index into part.strokes]
    pos: dict                   # node id → its place in part.nodes

    def here(self, lo: int, hi: int) -> set:
        return {nid for c in range(lo, hi) for nid in self.by_col.get(c, ())}

    def strokes(self, part: _Part, here: set) -> list:
        """part's strokes with an end in `here`, in part order."""
        return [part.strokes[i] for i in sorted({i for nid in here
                                                 for i in self.touching.get(nid, ())})]


def _band_index(part: _Part, col: dict) -> _BandIndex:
    by_col, touching = {}, {}
    for nid, c in col.items():
        by_col.setdefault(c, []).append(nid)
    for i, st in enumerate(part.strokes):
        for nid in dict.fromkeys((st.src, st.dst)):
            touching.setdefault(nid, []).append(i)
    return _BandIndex(by_col, touching, {nid: k for k, nid in enumerate(part.nodes)})


def _band_part(part: _Part, ctx: "_Ctx", col: dict, lo: int, hi: int, groups: dict,
               band_of, labels: dict, index: _BandIndex):
    """(_Part, _BandSpec): the band of `part` over columns lo … hi-1: its nodes,
    the strokes between them, a cut end per group leaving it (in a column of its
    own on the right) and a plug-in per group landing in it (on the left), each
    group's strokes resuming from there. `labels`: {group: its number}."""
    here = index.here(lo, hi)
    me = band_of(lo)
    ins = [g for g in groups if g[1] == me]
    off = 1 if ins else 0
    bcol = {nid: col[nid] - lo + off for nid in here}
    plugs, outs, bstrokes, done = [], set(), [], set()

    def vid(g, side):
        return f"\0p{side}{g[1]}\0{g[0]}"

    for st in index.strokes(part, here):
        if st.src == st.dst:
            if st.src in here:
                bstrokes.append(st)
            continue
        if st.src in here and st.dst in here:
            bstrokes.append(st)
            continue
        g = (st.src, band_of(col[st.dst]))
        if st.src in here and g not in done:   # one cut end for the group
            done.add(g)
            sts = groups[g]
            kinds = {s.kind for s in sts}
            kind = kinds.pop() if len(kinds) == 1 else "->"
            rides = tuple(dict.fromkeys(k for s in sts for k in (s.key,) + s.rides))
            plug = _Plug(vid(g, "o"), labels[g] + ("↑" if g[1] < me else ""), ctx.style(sts[0]))
            plugs.append(plug)
            outs.add(plug.vid)
            bcol[plug.vid] = hi - lo + off
            bstrokes.append(_Stroke(("\0plug",) + g, kind, st.src, plug.vid, (), rides,
                                    sts[0].role))
        elif st.dst in here:                    # resumes from its group's plug-in
            pin = vid(g, "i")
            if pin not in bcol:
                plugs.append(_Plug(pin, labels[g], ctx.style(groups[g][0])))
                bcol[pin] = 0
            bstrokes.append(st._replace(src=pin))
    nodes = {nid: part.nodes[nid] for nid in sorted(here & part.nodes.keys(), key=index.pos.get)}
    return (_Part("", part.owner, part.graph, nodes, bstrokes, base=part),
            _BandSpec(bcol, plugs, outs))


def _banded(part: _Part, lay: _Layout, ctx: "_Ctx", width: int, cut: tuple | None = None,
            kept: dict | None = None):
    """(_Drawn, its widest band, the cut) of a part cut into bands to fit
    `width`: the cut set with the fewest bands, then the fewest plugs, then the
    narrowest widest band, then the earliest cuts — every cut set when the part
    has up to BAND_SEARCH columns, else bands filled column by column. When
    none fits, the one whose widest band is narrowest (fewer bands, then plugs,
    first). None when the part has a single column. `cut`: (cut set, plug
    labels) as a frame before chose them (_stack), every frame of a run cut
    alike, its bands kept in `kept` (_stack's); None: choose."""
    n = len(lay.cols)
    if n < 2:
        return None
    strokes = [st for st in part.strokes if st.src != st.dst]
    col = {vid: v.col for vid, v in lay.V.items() if v.what == "node" and vid not in lay.isolated}
    index = _band_index(part, col)
    if cut is not None:
        return _stack(part, lay, ctx, col, cut[0], strokes, index, cut[1], kept)
    cache = {}

    def band_w(groups, lo, hi, band_of):
        sig = (lo, hi, band_of(lo),
               tuple(sorted((g, tuple(st.key for st in sts)) for g, sts in groups.items()
                            if lo <= col[g[0]] < hi or band_of(lo) == g[1])))
        if sig not in cache:
            labels = {g: plug_label(1) for g in groups}
            bpart, spec = _band_part(part, ctx, col, lo, hi, groups, band_of, labels, index)
            cache[sig] = _draw(_build(bpart, ctx, spec), ctx, isolated=False).w
        return cache[sig]

    def widths(starts, only: int | None = None):
        """[each band's width], the plugs: a cut set drawn; `only`: just that
        band's width (greedy cutting asks for the last band alone)."""
        bounds = (0,) + starts + (n,)
        spans = list(zip(bounds, bounds[1:]))

        def band_of(c):
            return bisect.bisect_right(starts, c)
        if only is not None:                    # its groups: the cut strokes it touches
            lo, hi = spans[only]
            near = [st for st in index.strokes(part, index.here(lo, hi)) if st.src != st.dst]
            return band_w(_cut_groups(near, col, starts), lo, hi, band_of)
        groups = _cut_groups(strokes, col, starts)
        return [band_w(groups, lo, hi, band_of) for lo, hi in spans], len(groups)

    if n <= BAND_SEARCH:
        tries = (cuts for b in range(1, n) for cuts in itertools.combinations(range(1, n), b))
    else:
        tries = iter([_greedy(n, widths, width)])
    best, narrow = None, None
    for cuts in tries:
        if best is not None and len(cuts) > len(best[2]):
            break
        ws, plugs = widths(cuts)
        widest = max(ws)
        if widest <= width:
            cand = (plugs, widest, cuts)
            best = cand if best is None or cand < best else best
        cand = (widest, len(cuts), plugs, cuts)
        narrow = cand if narrow is None or cand < narrow else narrow
    starts = best[2] if best is not None else narrow[3]
    return _stack(part, lay, ctx, col, starts, strokes, index)


def _greedy(n: int, widths, width: int) -> tuple:
    """Cuts for a part of many columns: each band takes the next column while it
    still fits (`widths(starts, k)`: band k's width under a cut set)."""
    starts = ()
    for c in range(1, n):
        trial = starts + (c + 1,) if c + 1 < n else starts
        if widths(trial, len(starts)) > width:
            starts += (c,)
    return starts


def _stack(part: _Part, lay: _Layout, ctx: "_Ctx", col: dict, starts: tuple, strokes: list,
           index: _BandIndex, labels: dict | None = None, kept: dict | None = None):
    """(_Drawn, widest band, (starts, the plug labels)): the bands of a cut set
    laid out, their cut ends numbered in reading order (band by band, top to
    bottom; `labels`: {group: its number} as numbered before), drawn one under
    the other with a blank row between, and the part's unconnected nodes under
    them; a cut wire's route runs from its source to its cut end, then on from
    its plug-in. `kept` ({band: (its look, layout, canvas)}, filled here): the
    bands a frame before drew, each drawn again only when it looks different
    (_band_look) — a band of a long run's chain is lit a few frames out of
    many."""
    bounds = (0,) + starts + (len(lay.cols),)
    groups = _cut_groups(strokes, col, starts)

    def band_of(c):
        return bisect.bisect_right(starts, c)

    def build(labels):
        out = []
        for lo, hi in zip(bounds, bounds[1:]):
            bpart, spec = _band_part(part, ctx, col, lo, hi, groups, band_of, labels, index)
            out.append((_build(bpart, ctx, spec), spec))
        return out

    def drawn(labels):
        """[(band layout, its canvas)], each band kept in `kept` while it looks alike."""
        out = []
        for k, (lo, hi) in enumerate(zip(bounds, bounds[1:])):
            bpart, spec = _band_part(part, ctx, col, lo, hi, groups, band_of, labels, index)
            look = _band_look(bpart, spec, ctx) if kept is not None else None
            if kept is not None and k in kept and kept[k][0] == look:
                out.append(kept[k][1:])
                continue
            blay = _build(bpart, ctx, spec)
            band = (blay, _draw(blay, ctx, isolated=False))
            if kept is not None:
                kept[k] = (look,) + band
            out.append(band)
        return out

    if labels is None:
        bands = build({g: plug_label(1) for g in groups})
        order = []                              # the groups, their cut ends in reading order
        for blay, _spec in bands:
            ends = [p for p in blay.paths if p.stroke.key[0] == "\0plug"]
            order += [p.stroke.key[1:] for p in sorted(ends, key=lambda p: blay.V[p.via[-1]].row)]
        labels = {g: plug_label(k + 1) for k, g in enumerate(order)}
    cv, spots, marks, y, widest = _Canvas(), {}, {}, 0, 0
    cut, resumed = {}, []                       # group → its cut end's cells; resumes
    for blay, bcv in drawn(labels):
        widest = max(widest, bcv.w)
        cv.blit(bcv, 0, y)
        spots.update({k: (x, yy + y) for k, (x, yy) in blay.spots.items()})
        marks.update({k: (x, yy + y) for k, (x, yy) in blay.marks.items()})
        for p in blay.paths:
            cells = [(x, yy + y) for x, yy in p.cells]
            if p.stroke.key[0] == "\0plug":
                cut[p.stroke.key[1:]] = cells
            else:
                resumed.append((p, cells))
        y += bcv.h + 1
    routes, group_of = {}, {}                   # group_of: stroke key → its (first) group
    for gr, sts in groups.items():
        for st in sts:
            group_of.setdefault(st.key, gr)
    for p, cells in resumed:
        if p.via[0].startswith("\0pi"):
            cells = cut.get(group_of[p.stroke.key], []) + cells
        for key in dict.fromkeys((p.stroke.key,) + p.stroke.rides):
            routes.setdefault(key, []).append(cells)
    if lay.isolated:
        _draw_isolated(cv, lay, ctx, cv.h + 1, spots, marks)
    return _Drawn(cv, spots, marks, routes), widest, (starts, labels)


def _band_look(bpart: _Part, spec: "_BandSpec", ctx: "_Ctx") -> tuple:
    """What of a band a sim frame changes, as _build and _draw read it: each
    label's runs (ctx.label: lead, status, badges, probe), each stroke's style,
    each plug's, each self-call stub's stroke."""
    selfs = ctx.selfs_of(bpart)
    return (tuple(tuple(ctx.label(bpart, nid, selfs)) for nid in bpart.nodes),
            tuple(ctx.style(st) for st in bpart.strokes),
            tuple(pl.style for pl in spec.plugs),
            tuple(ctx.styles.get(sb.wire.key) for s in selfs.values() for sb in s.stubs))


# ---------------------------------------------------------------------------
# compose_flow
# ---------------------------------------------------------------------------

def compose_flow(g, depth: int, payloads: bool, notes: str = "off", triggers: bool = True,
                 width: int | None = None, access: bool = False, mods: bool = False,
                 events: str = "nodes", trace=None, tick: int = 0, checks=None,
                 probe: bool = False, memo=None):
    """The flow view as rows of (text, style) runs, plus its width — the same
    arguments and return as view_graph.compose(). Each part (the document or a
    section of it, then each drawn expansion and machine) is a call graph read
    left to right under its title. `payloads` / `mods`: each flow's chip on its
    wire between the columns; notes (any mode but "off"): #N tags and the notes
    listed below; `triggers`, `access`, `events`: what the Scene wires (see
    scene.build_scene). `width`: the columns to fit; a drawing wider than that
    wraps by a ladder, each step taken only when the one before still doesn't
    fit: (a) each chip a marker letter (┆a┆), the chips listed in a panel at
    the bottom-right (view_graph's way); (b) what is written on a wire, and a
    label's notes and modifiers, hung under the node that sends it, the wire
    keeping its letter (_hang); (c) each part still too wide cut into bands
    (_banded); (d) when a band is still too wide, a hint under the drawing that
    the tree view reads narrow panes best (it never switches by itself). The
    notes list wraps at the width. `trace`,
    `tick`: a simulation frame over the drawing, the trace named as this
    drawing's Scene names it (sim.project), as view_graph.compose takes it;
    `checks` (kit.CheckMarks named the same way): the checks overlay. `probe`:
    the frame's tokens and active labels drawn in kit.Probe styles (sim_focus).
    The step and the cuts are chosen on the frame's drawing, whose badge slots
    are the run's (view_graph._trace_slots): every frame of a run wraps alike —
    so with a `memo` (kit.FrameMemo, kept by a caller drawing a run frame
    after frame) they are chosen on the first frame and kept, and so is each
    part's drawing, painted again only where a frame changes how it looks
    (the drawing is the same as without it)."""
    plan = (memo.plan(("flow", depth, payloads, notes, triggers, width, access, mods, events,
                       probe), (g, trace, checks)) if memo is not None else None)
    scn = kit.held(plan, "scene", lambda: scene.build_scene(g, events=events, triggers=triggers,
                                                            access=access, depth=depth))
    idx = scn.notes if notes != "off" else {}
    look = (vgraph.sim_look(scn, trace.frames[tick], vgraph._trace_slots(trace), probe)
            if trace is not None else None)
    note_w = kit.NOTE_WIDTH if width is None else min(kit.NOTE_WIDTH, width)
    tail = [[], kit.section_rule("notes"), []] + kit.note_rows(idx, note_w) if idx else []

    def done(rows, least: int = 0):
        w = max([least] + [kit.row_len(r) for r in rows + tail])
        return kit.stretch_rules(rows + tail, w), w

    args = (scn, depth, payloads, mods, notes != "off", look, checks)
    # A run's frames start down the ladder at the step its first frame took.
    start = LADDER.index(plan.held.get("step", LADDER[0]) if plan is not None else LADDER[0])
    if start <= 0:
        rows, _w, drawing_w, _over = _part_rows(*args, None, width=width,
                                                plan=_step(plan, "natural"))
        if width is None or drawing_w <= width:
            return done(rows)
    if (payloads or mods) and start <= 1:                         # (a)
        marks = []
        fitted, fitted_w, _dw, _over = _part_rows(*args, marks, width=width,
                                                  plan=_step(plan, "letters"))
        if marks:
            side = [(kit._chip_marker(letter), [(text, "code")]) for letter, text in marks]
            fitted = kit.stretch_rules(fitted, max(fitted_w, width))   # a title row is taken
            fitted = kit._fit_panel(fitted, lambda tw, most=None: kit._panel_rows(side, tw, most), width, "br",
                                    kit.CALLOUT_MAX)
            if max(kit.row_len(r) for r in fitted if not isinstance(r, kit.RuleRow)) <= width:
                return done(fitted)
    hung, _w, _dw, over = _part_rows(*args, None, hang=True, width=width,   # (b), (c)
                                     plan=_step(plan, "hung"))
    if over:                                    # (d)
        hung += [[]] + kit.wide_hint("flow", "a band", over, width)
    return done(hung, width)


LADDER = ("natural", "letters", "hung")     # compose_flow's wrap ladder, its steps in order


def _step(plan, name: str):
    """The plan of the wrap ladder's step `name` (kit.Plan.sub), the step the
    plan's frames take from now on (each frame of a run takes the step the
    first one took); None without a plan."""
    if plan is None:
        return None
    plan.held["step"] = name
    return plan.sub(name)


def _part_rows(scn, depth, payloads, mods, notes, look, checks, marks, hang: bool = False,
               width: int | None = None, plan=None):
    """Every part drawn, under its title, each centred within the widest; the
    tokens of a sim frame over them. Returns (rows, their width, the widest
    part's drawing, the widest band still wider than `width` or 0). `hang`:
    chips hung (_hang), and each part wider than `width` cut into bands.
    `plan` (kit.Plan): the parts and tags worked out once, each part's cut
    kept in a slot, chosen on the first frame of a run only, and its drawing
    with it (a part drawn whole: _whole; its bands: _stack)."""
    ctx = _Ctx(scn, depth, payloads, mods, notes, look, checks, marks, hang, width,
               kit.held(plan, "tags", lambda: vgraph._tags(scn, notes, mods)))
    drawn, every, over = [], [], 0

    def draw(part, fit):
        """part's _Drawn (None: no nodes), banded to fit; its blocks' after it."""
        nonlocal over
        d, kept = None, kit.slot(plan)
        if part.nodes:
            cut = kept.get("cut") if kept is not None else None    # False: not cut
            whole = kept.setdefault("whole", {}) if kept is not None else None
            if cut is False:                    # drawn whole on the frames before
                d = _whole(part, ctx, whole)
                widest = d.cv.w
            else:
                lay = _build(part, ctx, place=not cut)
            if cut:
                d, widest, cut = _banded(part, lay, ctx, fit, cut, kept.setdefault("bands", {}))
            elif cut is None:                   # the first frame: kept unless it may band
                may_band = hang and fit is not None
                d = _whole(part, ctx, None if may_band else whole, lay)
                widest = d.cv.w
                if may_band and widest > fit:
                    banded = _banded(part, lay, ctx, fit)
                    if banded is not None:
                        d, widest, cut = banded
            if kept is not None:
                kept["cut"] = cut or False
            if hang and fit is not None and widest > fit:
                over = max(over, widest + (width - fit))
            every.append(d)
        inner = None if fit is None else max(fit - vgraph.FRAME_PAD, 1)
        return d, [draw(bp, inner) for bp in part.blocks]

    for part in kit.held(plan, "parts", lambda: flow_parts(scn, depth)):
        if part.nodes or part.blocks:
            drawn.append((part, draw(part, width)))
    if look is not None:                        # in task order: a later token wins a cell
        for tok in look.tokens:
            for d in every:
                cell = _token_cell(tok, d, d.routes)
                if cell is not None:
                    (d.cv.overlay if d.kept else d.cv.put)(cell[0], cell[1], tok.mark, tok.style)
                    break

    def framed(part, tree, fit):
        """part's canvas with its blocks' frames under it (view_graph's _stack)."""
        d, kids = tree
        inner = None if fit is None else max(fit - vgraph.FRAME_PAD, 1)
        frames = [vgraph._framed(framed(bp, kid, inner), _frame_title(ctx, bp.block), _Canvas, fit)
                  for bp, kid in zip(part.blocks, kids)]
        return vgraph._stack(d.cv if d is not None else _Canvas(), frames, fit, _Canvas)

    parts = [(part.title, None, framed(part, tree, width)) for part, tree in drawn]
    rows, w = vgraph._section_rows(parts, width) if parts else ([], 0)
    return rows, w, max([0] + [cv.w for _t, _n, cv in parts]), over


def _frame_title(ctx: "_Ctx", b) -> list:
    """A block frame's title runs (kit.block_title_runs), then the #N of a
    comment above its header — as the graph view titles it."""
    return vgraph._title(kit.block_title_runs(b), ctx.tags.get(kit.block_note_key(b), []))


# ---------------------------------------------------------------------------
# Legend
# ---------------------------------------------------------------------------

def flow_legend(triggers: bool = True, payloads: bool = False, access: bool = False,
                mods: bool = False, events: str = "nodes"):
    """Legend row for the flow view: each arrow's stroke and head, the trigger
    wire, an event drawn where it lands, the wire shapes (a shared trunk, a hop,
    stacked heads, a wire back along the return row), a block's frame, a
    branch's arm, the join marks, the call marks, the
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
            ("╭╌ ↺ ∥ ◇ □", kit.FRAME_STYLE), (" block frame  ", mid),
            ("┄‹arm›┄", (kit.EDGE_COLOR["arm"], None, False)), (" branch arm  ", mid),
            ("&▶", kit.LABEL_STYLE), (" join: all  ", mid), ("&?▶", kit.LABEL_STYLE),
            (" race  ", mid), ("/▶", kit.LABEL_STYLE), (" one of  ", mid)]
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
