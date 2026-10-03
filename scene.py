"""
scene.py — the shared presentation model: what any view draws and the simulator
runs, built from render.py's Graph.

Not a command: the views (view_graph.py, view_tree.py) and the simulator load
it. The Graph says what a design MEANS; the Scene says what is SHOWN at a given
depth and with given options — which graphs are drawn, every wire between their
nodes with its colour, payload, notes and join marks, and where an event is
drawn. A view only decides how a Scene looks (boxes and edges, or an outline
and lanes); it never re-derives wiring or colour on its own.

    scene = build_scene(graph, events="land", triggers=True, access=False, depth=1)

THE SCENE

Scene
  graph       the Graph it was built from (render.parse_document)
  options     SceneOptions(events, triggers, access, depth)
  units       [Unit(owner, level, graph)]: the graphs drawn — the document, then
              each `X := { … }` / `state` expansion up to `depth`, depth-first in
              outline order (a composition tree's order: roots and their `\\-`
              branches, then the nodes no tree places). owner is the node id the
              expansion hangs off (None: the document); level 0 is the document.
  nodes       {id: SceneNode}, first-seen over the units
  wires       [Wire], grouped by role in this order: flows and triggers (unit by
              unit, each unit's flows in document order, then its triggers),
              emits, access, arms, compose. A wire per edge: a flow written twice
              is two wires with one key (a view that draws one stroke per key
              dedups; the simulator may not).
  sections    the document's `--- sections ---` (render.Section)
  blocks      [BlockRef(owner, index, block)]: the control blocks of every unit
  notes       {node id: [(number, text, kind, edges)]}: viewkit.note_index()
  collapsed   the event ids drawn where they land (events="land"): no row or box
              of their own; their emit wires replace them

SceneNode
  node        the render.Node
  unit        the owner of the unit it is first seen in (None: the document)
  section     index into Scene.sections of the section it is written in (-1:
              none, or not a top-level node)
  blocks      indices into its unit graph's blocks of the blocks it is a member of
  notes       its note entries (Scene.notes[id])
  badges      writer badges (`1w` / `Nw`, the access option only)
  arms        branch-arm labels it is the entry of (`‹read›`)
  landed      the event nodes that land on it (events="land")
  external    the far node of an external op call (`-> (Web) : op http.get(…)`):
              host-provided, opaque. A self-call's subject is never marked (its
              Call says the op is external)

Wire
  src, dst    node ids. An arm starting at a branch with no glyph in its header
              starts at decision_id(owner, block index) (no SceneNode).
  kind        the arrow as written (`->`, `~>`, `!>`, …), or "trigger",
              "access:r|w|b", "arm", or `\\-<rel>` for a composition branch
  role        flow     an edge of a unit graph
              emit     emitter → destination through a collapsed event (via)
              trigger  an event → the state it drives (to the machine's owner
                       when the machine is not drawn); machine = that owner
              access   a principal → the store it may read / write / borrow
              arm      a branch → the entry of one arm (label; alt = the branch)
              compose  a composition parent → child (`\\-`), spawn for `*-`
  key         (src, dst, kind): the model's edge key, what a view draws as one
              stroke and what notes / payloads / joins are keyed by. Two calls
              written with one key share it: chip_lists keeps their chips apart
              and ident tells the wires apart
  ident       key + (n,): the wire's own identity, n counting the wires of its
              key in wire order — unique in the Scene and stable across builds
              of one document (what a simulation trace names a wire by)
  colour      a theme role, per the colour policy (wire_colour); resolve it with
              colour_of() or style a stroke with wire_style()
  payload     the `: payload` text (flows); None for the rest
  mods        the edge's modifiers as (name, arg) pairs
  notes       ((number, text), …): the inline notes about the line it came from
  join        {"src" | "dst": "&" | "&?" | "/"}: the drawn joins it leaves / enters
  block       index into its unit graph's blocks of the innermost block drawing it
  paths       (src path, dst path): qualified-path endpoints (`[A]/{B}`) or None
  via         emit: the collapsed event id it carries
  alt         an alternatives group id: wires sharing one fire one of them (a `/`
              join's members, a branch's arms); None otherwise
  line        the source line (0: none)
  owner       the owner of the unit it is drawn in (None: the document)
  level       that unit's level
  label       an edge label (a transition's trigger), a trigger's label (also on
              an emit wire a trigger delivers), an arm's
  machine     trigger, and an emit wire a trigger delivers: the node owning the
              state machine it drives (driver_wires); None for the rest
  legs        emit: (the wire into the event, the wire out of it)
  spawn       compose: `*-` (instances spawned at runtime)
  edge        the render.Edge a flow wire comes from (None for the rest)
  call        flow: the Call it makes (see CALLS); None when it is no call
  returns_of  flow: the `=>` wire of an op-call target's return
              (`[S] -> plan() => {Plan}`): the call wire it returns from

CALLS

A flow wire is a call when its target is an op-call (`[S] -> plan({Seed})`, a
self-call), it is a glyph self-edge (`[Doc.walk] -> [Doc.walk] : child`,
recursion; its payload is what each call carries), or its payload is an
op-call (`: crawl({Plan}) => {Site}`). A state machine's self-transition is no
call. Call (the payload text is parsed here, once — render.py keeps it whole):

  op          the op text without the `op ` keyword and without the return
              ("crawl({Plan})"); None for a glyph self-edge
  carries     what each call carries besides its op: a target op's payload
              (`[W] -> run() : {Job}` → "{Job}"), a glyph self-edge's payload
              ("child"); None
  external    `op …`: a host-provided op (opaque; it may fail)
  returns     what comes back: the payload's `=> X` text, or the glyph(s) of a
              target op's `=>` edge(s) (`{Plan}`, `{A} / {B}`); None
  return_nodes  the node ids of those `=>` edges' glyphs (a target op only)
  self_call   the subject runs the op itself (a self-edge)
  recursive   a glyph self-edge, or a target op naming the alias whose body it
              is in (`follow := [Crawler] -> follow(.links)`)

Marks (call_mark; the chip text, call_text, leads with it): `↻` recursive,
`⇱` external, `↺` any other self-call; `↩ X` the return. What a call carries
follows its op as written: `↺ run() : {Job}`. Each flow line is its
own call (language.md "Calls — who runs an op"): two calls into one target
keep two chips.

STATIC FACTS (what a check reads off the wiring; no view draws them)

  call_policy(w)        a call's modifiers: the wire's, then its source side's
                        (Edge.src_mods); a node's `×N` is cardinality, never here
  access_mode(w, graph) "read" | "write" | "rw" | "unknown" | None: how a flow
                        touches a store (declarations first, then the wiring)
  writers(scene, store) {principal: {"decl", "owns", "flow"}}: who writes it
  all_writers(scene)    {store: writers(scene, store)}, in one pass
  access_index(graph)   what access_mode reads, gathered once for many wires

THE COLOUR POLICY (one rule for every view)

A wire takes its arrow's own colour when it has one — `!>` edges-fail, `?>`
edges-maybe, `~>` edges-async, `]>[` edges-split, arm edges-arm, access
edges-access, trigger the event colour — an emit wire the event colour (a
failure emission stays edges-fail), else its source node's kind colour. A row's
`◀` / an edge's head takes its wire's colour; where wires share cells, the
wire nearest its target owns them. A simulation overlay restyles on top
(wire_style: active = full colour + bold, inactive = muted, failed = edges-fail).

Colours are theme roles named as Colour.role names them ("edges-fail",
"kinds-service"), resolved through viewkit at call time, so a theme applied
later still reaches a built Scene.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import NamedTuple, Optional


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


# ---------------------------------------------------------------------------
# The Scene
# ---------------------------------------------------------------------------

ROLES = ("flow", "emit", "trigger", "access", "arm", "compose")
EVENTS = ("land", "nodes")          # an event drawn where it lands, or as a node
STATES = ("plain", "active", "inactive", "failed")     # wire_style overlays
ANY_UNIT = object()     # a `unit` filter's default: the wires of every unit


class SceneOptions(NamedTuple):
    events: str = "nodes"
    triggers: bool = True
    access: bool = False
    depth: int = kit.ALL_DEPTH


class Unit(NamedTuple):
    owner: Optional[str]            # the node the expansion hangs off; None: the document
    level: int
    graph: object                   # render.Graph


class Call(NamedTuple):
    """What a call wire runs (Wire.call; see CALLS in the module docstring)."""
    op: Optional[str]
    external: bool = False
    returns: Optional[str] = None
    return_nodes: tuple = ()
    self_call: bool = False
    recursive: bool = False
    carries: Optional[str] = None


class BlockRef(NamedTuple):
    owner: Optional[str]
    index: int                      # into the unit graph's blocks
    block: object                   # render.Block


@dataclass
class SceneNode:
    node: object                    # render.Node
    unit: Optional[str] = None
    section: int = -1
    blocks: tuple = ()
    notes: list = field(default_factory=list)
    badges: list = field(default_factory=list)
    arms: list = field(default_factory=list)
    landed: list = field(default_factory=list)
    external: bool = False


@dataclass
class Wire:
    src: str
    dst: str
    kind: str
    role: str
    key: tuple
    colour: str = ""
    payload: Optional[str] = None
    mods: list = field(default_factory=list)
    notes: tuple = ()
    join: dict = field(default_factory=dict)
    block: Optional[int] = None
    paths: tuple = (None, None)
    via: Optional[str] = None
    alt: Optional[str] = None
    line: int = 0
    owner: Optional[str] = None
    level: int = 0
    label: Optional[str] = None
    machine: Optional[str] = None
    legs: tuple = ()
    spawn: bool = False
    edge: object = None
    call: Optional[Call] = None
    returns_of: Optional["Wire"] = None
    ident: tuple = ()


@dataclass
class Scene:
    graph: object
    options: SceneOptions
    units: list
    nodes: dict
    wires: list
    sections: list
    blocks: list
    notes: dict
    collapsed: frozenset = frozenset()


def build_scene(graph, *, events: str = "nodes", triggers: bool = True,
                access: bool = False, depth: int = kit.ALL_DEPTH) -> Scene:
    """The Scene of a Graph drawn to `depth` (0: the document only). `events`:
    "land" draws a pass-through event where it lands (see land_events), "nodes"
    as a node of its own; `triggers`: wire events to the states they drive;
    `access`: the permission graph. Raises ValueError for an unknown events mode."""
    if events not in EVENTS:
        raise ValueError(f"events must be one of {', '.join(EVENTS)}, not {events!r}")
    options = SceneOptions(events, triggers, access, depth)
    units = drawn_units(graph, depth)
    nodes = scene_nodes(graph, units)
    idx = kit.note_index(graph)
    inline = trailing_notes(idx)
    wires = []
    for u in units:
        wires += unit_wires(u, inline, nodes)
        wires += trigger_wires(u, depth, nodes) if triggers else []
    collapsed = frozenset()
    if events == "land":
        wires, collapsed, landed = land_events(graph, wires, nodes)
        for nid, evs in landed.items():
            nodes[nid].landed = evs
    if access:
        wires += access_wires(graph)
        _badge(nodes, graph)
    wires += [w for u in units for w in arm_wires(u)]
    wires += [w for u in units for w in compose_wires(u, nodes)]
    _number(wires)
    _annotate(nodes, graph, units, idx, collapsed)
    for nid in external_targets(wires):
        nodes[nid].external = True
    blocks = [BlockRef(u.owner, bi, b) for u in units
              for bi, b in enumerate(getattr(u.graph, "blocks", None) or [])]
    return Scene(graph, options, units, nodes, wires,
                 list(getattr(graph, "sections", None) or []), blocks, idx, collapsed)


# ---------------------------------------------------------------------------
# Units and nodes
# ---------------------------------------------------------------------------

def outline_ids(g) -> list:
    """g's node ids in outline order: each composition tree's root and its `\\-`
    branches depth-first, a node no tree places where it is first seen. A node
    composed into several parents is listed once, at its first place."""
    tree = getattr(g, "tree", None) or []
    kids = {}
    for i, t in enumerate(tree):
        kids.setdefault(t.parent, []).append(i)
    placed = {t.node for t in tree if t.parent is not None}
    out = []

    def entry(i):
        out.append(tree[i].node)
        for c in kids.get(i, []):
            entry(c)

    roots_of = {}
    for i in kids.get(None, []):
        roots_of.setdefault(tree[i].node, []).append(i)
    for nid in g.nodes:
        roots = roots_of.get(nid, [])
        for i in roots:
            entry(i)
        if not roots and nid not in placed:
            out.append(nid)
    return list(dict.fromkeys(out))


def drawn_units(g, depth: int) -> list:
    """The graphs drawn to `depth`: g, then its expansions (and theirs) depth-first
    in outline order, as Units."""
    out = []

    def visit(graph, owner, level):
        out.append(Unit(owner, level, graph))
        if level < depth:
            for nid in outline_ids(graph):
                if nid in graph.expansions:
                    visit(graph.expansions[nid], nid, level + 1)

    visit(g, None, 0)
    return out


def walked_units(g) -> list:
    """Every graph of the document, drawn or not — g, then its expansions
    breadth-first in document order (viewkit._walk's order) — as Units."""
    out, queue = [], [Unit(None, 0, g)]
    while queue:
        u = queue.pop(0)
        out.append(u)
        queue += [Unit(nid, u.level + 1, sub) for nid, sub in u.graph.expansions.items()]
    return out


def scene_nodes(g, units) -> dict:
    """{id: SceneNode} over the units, first-seen; nodes only an undrawn
    expansion holds are added after them (a wire may still name one)."""
    nodes = {}
    for u in units + walked_units(g):
        for nid, n in u.graph.nodes.items():
            if nid not in nodes:
                nodes[nid] = SceneNode(n, u.owner)
    return nodes


def _annotate(nodes: dict, g, units, idx: dict, collapsed: frozenset) -> None:
    """Fill each SceneNode's section, blocks, notes and branch-arm labels."""
    secs = getattr(g, "sections", None) or []
    est = kit.node_lines(g) if secs else {}
    for nid in g.nodes:
        nodes[nid].section = kit.section_of(secs, est.get(nid, 0)) if secs else -1
    for nid, entries in idx.items():
        if nid in nodes:
            nodes[nid].notes = entries
    for u in units:
        for bi, b in enumerate(getattr(u.graph, "blocks", None) or []):
            for m in dict.fromkeys(b.members):
                if m in nodes and nodes[m].unit == u.owner:
                    nodes[m].blocks += (bi,)
        for entry, label in branch_arms(u, collapsed):
            nodes[entry].arms.append(label)


def branch_arms(u: Unit, collapsed: frozenset = frozenset()) -> list:
    """[(entry node id, arm label)] of the unit's branch blocks with a drawn
    member (a collapsed event of the document is not drawn)."""
    out = []
    for b in getattr(u.graph, "blocks", None) or []:
        gone = collapsed if u.level == 0 else frozenset()
        if b.kind != "branch" or not [m for m in b.members if m not in gone]:
            continue
        out += [(ids[0], label) for label, ids in b.arm_nodes if ids]
    return out


def _badge(nodes: dict, g) -> None:
    """Writer badges (`1w` / `Nw`) on every store, from every graph's access."""
    for u in walked_units(g):
        for sid, badge in kit.writer_badges(u.graph).items():
            if sid in nodes:
                nodes[sid].badges.append(badge)


# ---------------------------------------------------------------------------
# Wires
# ---------------------------------------------------------------------------

def unit_wires(u: Unit, inline: dict, nodes: dict) -> list:
    """A flow wire per edge of the unit graph, in document order, each call with
    its Call (none in a state machine) and an op-call target's return linked."""
    g = u.graph
    eb = kit.edge_blocks(g)
    alias = _alias_of(u, nodes)
    calls = getattr(g, "role", "") != "state"
    out = []
    for k, e in enumerate(g.edges):
        w = Wire(e.src, e.dst, e.kind, "flow", (e.src, e.dst, e.kind),
                 payload=e.payload, mods=list(e.mods), notes=tuple(inline.get(e.key, ())),
                 join=_joins_of(g, e), block=eb.get(k), paths=(e.src_path, e.dst_path),
                 alt=_alt_group(u, e), line=e.line, owner=u.owner, level=u.level,
                 label=e.label, edge=e, call=edge_call(e, alias) if calls else None)
        w.colour = wire_colour(w, _kind_of(nodes, e.src))
        out.append(w)
    _link_returns(out, nodes)
    return out


def _number(wires: list) -> None:
    """Give each wire its ident: its key and its ordinal among the wires of that key."""
    seen = {}
    for w in wires:
        n = seen.get(w.key, 0)
        seen[w.key] = n + 1
        w.ident = w.key + (n,)


def _joins_of(g, e) -> dict:
    """{"src" | "dst": join kind} of the drawn joins an edge leaves / enters."""
    out = {}
    for side in ("src", "dst"):
        idx = kit.drawn_join(g, e, side)
        if idx is not None:
            out[side] = g.joins[idx].kind
    return out


def _alt_group(u: Unit, e) -> Optional[str]:
    """The `/` (one of) join an edge leaves or enters, as an alternatives group id."""
    joins = getattr(u.graph, "joins", None) or []
    for idx in (e.dst_join, e.src_join):
        if idx is not None and 0 <= idx < len(joins) and joins[idx].kind == "/":
            return f"{u.owner or ''}/join{idx}"
    return None


def trigger_wires(u: Unit, depth: int, nodes: dict) -> list:
    """An event → the state it enters, for each trigger of the unit graph; to the
    machine's owner when the machine is drawn below `depth`."""
    out = []
    for t in getattr(u.graph, "triggers", None) or []:
        dst = t.dst if t.level <= depth else t.owner
        w = Wire(t.event, dst, "trigger", "trigger", (t.event, dst, "trigger"),
                 owner=u.owner, level=u.level, label=t.label, machine=t.owner)
        w.colour = wire_colour(w, _kind_of(nodes, t.event))
        out.append(w)
    return out


def access_wires(g) -> list:
    """A permission wire principal → store for every access of every graph
    (drawn or not: a principal's access is about the whole design)."""
    out = []
    for u in walked_units(g):
        for a in getattr(u.graph, "access", None) or []:
            if a.principal and a.store and a.principal != a.store:
                kind = kit.access_kind(a)
                w = Wire(a.principal, a.store, kind, "access", (a.principal, a.store, kind),
                         line=a.line, owner=u.owner, level=u.level, label=a.mode)
                w.colour = wire_colour(w, "")
                out.append(w)
    return out


def decision_id(owner: Optional[str], index: int) -> str:
    """The id an arm wire starts at when its branch names no glyph in its header."""
    return f"\0b{index}" if owner is None else f"\0b{owner}.{index}"


def arm_wires(u: Unit) -> list:
    """A wire from each branch (its header's first glyph) to each arm's entry."""
    out = []
    for bi, b in enumerate(getattr(u.graph, "blocks", None) or []):
        if b.kind != "branch":
            continue
        src = b.refs[0] if b.refs else decision_id(u.owner, bi)
        for label, ids in b.arm_nodes:
            if ids:
                w = Wire(src, ids[0], "arm", "arm", (src, ids[0], "arm"), block=bi,
                         alt=f"{u.owner or ''}/branch{bi}", line=b.lines[0],
                         owner=u.owner, level=u.level, label=label)
                w.colour = wire_colour(w, "")
                out.append(w)
    return out


def compose_wires(u: Unit, nodes: dict) -> list:
    """A wire from each composition parent to each `\\-` branch under it."""
    tree = getattr(u.graph, "tree", None) or []
    out = []
    for t in tree:
        if t.parent is None:
            continue
        src, kind = tree[t.parent].node, "\\-" + (t.rel or ">")
        w = Wire(src, t.node, kind, "compose", (src, t.node, kind), owner=u.owner,
                 level=u.level, label=t.cond, spawn=bool(t.spawn))
        w.colour = wire_colour(w, _kind_of(nodes, src))
        out.append(w)
    return out


def _kind_of(nodes: dict, nid: str) -> str:
    sn = nodes.get(nid)
    return sn.node.kind if sn else ""


# ---------------------------------------------------------------------------
# Calls — what a flow runs, what comes back, what leaves the system
# ---------------------------------------------------------------------------

_RETURN_RE = re.compile(r"\s*=>\s*(\S.*?)\s*")
_EXTERNAL_RE = re.compile(r"op\s+")


def split_op(text: str) -> Optional[tuple]:
    """(op, external, returns) of an op-call text — `verb(args)`, `op ns.verb(args)`,
    either followed by `=> X` — with the `op ` keyword and the return taken off
    the op; None when the text is no op-call (`{Doc}`, `child`, `"hi"`)."""
    text = text.strip()
    m = kit.render.OP_TARGET_RE.match(text)
    if not m:
        return None
    rest = text[m.end():]
    ret = _RETURN_RE.fullmatch(rest)
    if rest.strip() and not ret:
        return None
    ext = _EXTERNAL_RE.match(m.group(0))
    op = m.group(0)[ext.end():] if ext else m.group(0)
    return op, bool(ext), ret.group(1) if ret else None


def op_verb(op: str) -> str:
    """The op's name, without its arguments: `follow(.links)` → `follow`."""
    return op.split("(", 1)[0].strip()


def target_op_payload(target_op: str, payload: Optional[str]) -> Optional[str]:
    """The payload a target-op edge carries besides its op: render writes it
    `target_op : payload` (`run() : {Job}` → "{Job}"); None when there is none."""
    prefix = f"{target_op} : "
    if payload and payload.startswith(prefix):
        return payload[len(prefix):].strip() or None
    return None


def edge_call(e, alias: Optional[str] = None) -> Optional[Call]:
    """The Call a flow edge makes, or None when it makes none (see CALLS).
    `alias`: the name of the alias whose body holds the edge — a target op of
    that name recurses. A target op's return is linked later (_link_returns)."""
    if e.target_op:
        op, external, _ret = split_op(e.target_op)
        return Call(op, external, self_call=True,
                    recursive=not external and op_verb(op) == alias,
                    carries=target_op_payload(e.target_op, e.payload))
    parsed = split_op(e.payload or "")
    if e.src == e.dst:
        if parsed is None:
            return Call(None, self_call=True, recursive=True, carries=e.payload or None)
        op, external, returns = parsed
        return Call(op, external, returns, self_call=True, recursive=True)
    if parsed is None:
        return None
    op, external, returns = parsed
    return Call(op, external, returns)


def _alias_of(u: Unit, nodes: dict) -> Optional[str]:
    """The name of the alias a unit is the body of (`follow := …`), else None."""
    sn = nodes.get(u.owner)
    return sn.node.name if sn and sn.node.kind == "alias" else None


def _link_returns(wires: list, nodes: dict) -> None:
    """Link each op-call target to the `=>` wires after it on its line from its
    subject (`[S] -> plan() => {Plan}`): the call's returns / return_nodes name
    their glyphs (joined ` / ` for alternatives, ` & ` otherwise) and each `=>`
    wire's returns_of is the call wire."""
    open_calls = {}                         # (line, subject) → the call wire
    for w in wires:
        at = (w.line, w.src)
        if w.call is not None and w.edge is not None and w.edge.target_op:
            open_calls[at] = w
        elif w.kind == "=>" and at in open_calls:
            call = open_calls[at]
            glyph = kit.node_label(nodes[w.dst].node)
            sep = " / " if w.alt else " & "
            returns = f"{call.call.returns}{sep}{glyph}" if call.call.returns else glyph
            call.call = call.call._replace(returns=returns,
                                           return_nodes=call.call.return_nodes + (w.dst,))
            w.returns_of = call


def external_targets(wires: list) -> list:
    """The far nodes of the external op calls (not a self-call's subject), in wire
    order, once each."""
    return list(dict.fromkeys(w.dst for w in wires if w.call is not None
                              and w.call.external and not w.call.self_call))


def call_mark(call: Call) -> str:
    """A call's mark: `↻` recursive, `⇱` external, `↺` another self-call, else ""."""
    if call.recursive:
        return "↻"
    if call.external:
        return "⇱"
    return "↺" if call.self_call else ""


def call_text(call: Call) -> str:
    """A call as its chip shows it: mark, op, what it carries (after ` : ` when
    there is an op), `↩` return — `↺ plan({Seed}) ↩ {Plan}`, `⇱ http.get(${url})`,
    `crawl({Plan}) ↩ {Site}`, `↺ run() : {Job}`, `↻ child`."""
    carried = call.carries or ""
    if call.op and carried:
        carried = ": " + carried
    parts = [call_mark(call), call.op or "", carried]
    if call.returns:
        parts += ["↩", call.returns]
    return " ".join(p for p in parts if p)


def self_mark(calls: list) -> str:
    """The mark a node's box / row carries for its self-calls (Calls, any
    order): `↻` when one recurses, `↺` when one runs an internal op, else `⇱`
    (only external ops); "" for none."""
    if any(c.recursive for c in calls):
        return "↻"
    if any(not c.external for c in calls):
        return "↺"
    return "⇱" if calls else ""


def self_calls(scene: "Scene", unit=ANY_UNIT) -> dict:
    """{node id: [call wire]}: each node's self-calls in written order; with
    `unit` (a unit owner, None: the document), only those drawn in that unit."""
    out = {}
    for w in scene.wires:
        if (w.call is not None and w.call.self_call
                and (unit is ANY_UNIT or w.owner == unit)):
            out.setdefault(w.src, []).append(w)
    return out


# ---------------------------------------------------------------------------
# Static facts about calls and stores — what a check reads off the wiring
# ---------------------------------------------------------------------------

# Op verbs that only read a store (`[S] -> |DB| : get(${id})`); a dialect may
# extend the list a caller passes.
READ_VERBS = ("get", "read", "query", "fetch", "load", "find", "list", "scan",
              "lookup", "search", "count")


def call_policy(w: Wire) -> list:
    """The modifiers that govern one call, as (name, arg) pairs: the wire's own
    (trailing the statement) then those written between its source glyph and
    the arrow (Edge.src_mods: `[A] @timeout(3s) -> [B]`). A `×N` on a node is
    cardinality, so it is never among them; a `×N` here is a retry."""
    own = list(w.mods)
    src = getattr(w.edge, "src_mods", None) or []
    return own + [p for p in src if p not in own]


class AccessIndex(NamedTuple):
    """What access_mode reads off the whole document, gathered in one walk
    (access_index): a caller classifying many wires builds it once."""
    nodes: dict                # id → render.Node, first seen over every graph
    declared: dict             # (principal, store) → {"read", "write"} declared
    produced: frozenset        # (src, line) of every `=>` edge
    continued: frozenset       # (src, cont) of every `=>` edge continuing a line
    units: tuple               # per graph, walk order: (access entries, (id, Node) …)


def access_index(graph) -> AccessIndex:
    nodes, declared, produced, continued, units = {}, {}, set(), set(), []
    for u in walked_units(graph):
        access = tuple(getattr(u.graph, "access", None) or [])
        units.append((access, tuple(u.graph.nodes.items())))
        for nid, n in u.graph.nodes.items():
            nodes.setdefault(nid, n)
        for a in access:
            mode = a.narrow if a.mode == "borrow" else a.mode
            if mode in ("read", "write"):
                declared.setdefault((a.principal, a.store), set()).add(mode)
        for e in u.graph.edges:
            if e.kind == "=>":
                produced.add((e.src, e.line))
                continued.add((e.src, e.cont))
    return AccessIndex(nodes, declared, frozenset(produced), frozenset(continued),
                       tuple(units))


def access_mode(w: Wire, graph, read_verbs: tuple = READ_VERBS,
                index: Optional[AccessIndex] = None) -> Optional[str]:
    """How a flow wire touches a store: "read" | "write" | "rw" | "unknown", or
    None when neither end is a store (`|S|`; a data glyph is never one). In order:
    a `@read(P)` / `@write(P)` / `@borrow(read|write)` declared for the wire's
    principal (its end that is not the store) wins; `<->` reads and writes; a
    flow out of a store reads; a flow into one that produces a value (`=> X` on
    its payload or line, or a `=>` continuing it) reads; one with no payload is
    unknown (`[Svc] -> |DB|` says "uses"); else it writes, unless its op verb is
    one of `read_verbs`. The verb reading is a heuristic. `index`: the
    document's access_index, when the caller has one."""
    ix = index or access_index(graph)
    into, out_of = _is_store(ix.nodes.get(w.dst)), _is_store(ix.nodes.get(w.src))
    if w.role != "flow" or w.src == w.dst or not (into or out_of):
        return None
    store, principal = (w.dst, w.src) if into else (w.src, w.dst)
    declared = ix.declared.get((principal, store))
    if declared:
        return "rw" if declared == {"read", "write"} else next(iter(declared))
    if w.kind == "<->":
        return "rw"
    if not into or _produces(w, ix):
        return "read"
    if not w.payload:
        return "unknown"
    return "read" if _verb(w).lower() in read_verbs else "write"


def declared_access(graph, principal: str, store: str,
                    index: Optional[AccessIndex] = None) -> set:
    """The modes ("read", "write") declared for `principal` on `store` anywhere
    in the document: `@read(P)` / `@write(P)` on the store, `@borrow(read|write)`."""
    ix = index or access_index(graph)
    return set(ix.declared.get((principal, store), ()))


def writers(sc: Scene, store: str, read_verbs: tuple = READ_VERBS) -> dict:
    """{principal: frozenset of sources} of everything that writes `store`:
    "decl" (`@write(P)` on it), "owns" (`@owns |S|` on P, a `[P] @owns |S| { … }`
    block included) and "flow" (a flow wire whose access_mode, read with
    `read_verbs`, is write or rw). A principal is a node id, or the name as
    written when a declaration names no node. A flow of unknown mode is no
    writer."""
    return all_writers(sc, read_verbs).get(store, {})


def all_writers(sc: Scene, read_verbs: tuple = READ_VERBS,
                index: Optional[AccessIndex] = None) -> dict:
    """{store: writers(sc, store)} for every store something writes, in one pass."""
    g = sc.graph
    ix = index or access_index(g)
    out = {}
    add = lambda store, principal, how: (
        out.setdefault(store, {}).setdefault(principal, set()).add(how))
    for access, nodes in ix.units:
        for a in access:
            if a.mode == "write":
                add(a.store, a.principal or a.name, "decl")
        for nid, n in nodes:
            for store in _owned(n):
                add(store, nid, "owns")
    legs = [leg for w in sc.wires if w.role == "emit" for leg in w.legs]
    for w in [w for w in sc.wires if w.role == "flow"] + legs:
        if access_mode(w, g, read_verbs, ix) in ("write", "rw"):
            add(w.dst, w.src, "flow")
    return {store: {p: frozenset(srcs) for p, srcs in found.items()}
            for store, found in out.items()}


def _is_store(n) -> bool:
    return n is not None and n.kind == "store"


def _owned(n) -> set:
    """The node ids named by a node's `@owns` modifiers."""
    out = set()
    for name, arg in n.mods:
        if name == "owns" and arg:
            for gm in kit.render.GLYPH_RE.finditer(arg):
                owned = kit.render.parse_glyph(gm.group(0))
                if owned is not None:
                    out.add(owned.id)
    return out


def _produces(w: Wire, ix: AccessIndex) -> bool:
    """Whether a flow returns a value: `=> X` in its payload or Call, or a `=>`
    edge on its line from its target (`-> |DB| => {Row}`) or continuing it from
    its subject (`[Auth] -> |UserDB|` then `=> {Session}`)."""
    if w.call is not None and w.call.returns:
        return True
    if w.payload and "=>" in w.payload:
        return True
    return (w.dst, w.line) in ix.produced or (w.src, w.line) in ix.continued


def _verb(w: Wire) -> str:
    """The op verb a flow names: its Call's op, else its payload's first word."""
    if w.call is not None and w.call.op:
        return op_verb(w.call.op).rsplit(".", 1)[-1]
    m = re.match(r"\s*(?:op\s+)?(?:[A-Za-z_]\w*\.)*([A-Za-z_]\w*)", w.payload or "")
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# The events transform — an event drawn where it lands
# ---------------------------------------------------------------------------

def pass_through_candidates(g) -> list:
    """The document's event nodes that may be drawn where they land: top-level,
    in no composition tree as a branch or a parent, and owning no expansion. An
    expansion may write the event too: that occurrence stays a node of its
    unit, but loses its wires with the rest (a graph view keeps the sub-graph's
    box and edges, see view_graph._landed). In document order."""
    tree = getattr(g, "tree", None) or []
    placed = {t.node for t in tree if t.parent is not None}
    parents = {tree[t.parent].node for t in tree if t.parent is not None}
    owners = {nid for u in walked_units(g) for nid in u.graph.expansions}
    kept = placed | parents | owners
    return [nid for nid, n in g.nodes.items() if n.kind == "event" and nid not in kept]


def land_events(g, wires: list, nodes: dict):
    """Draw a pass-through event where it lands, not as its own row or box: a
    candidate event (pass_through_candidates) that is both emitted (a flow into
    it) and delivered (a flow or trigger out of it) goes; each emitter is wired
    straight to each destination by an emit wire (via the event; a `!>` emission
    stays a `!>` unless it is delivered by a trigger), and the event lands on
    each destination a flow delivers it to. An emit wire per (emission,
    delivery) pair: two events from one emitter to one destination are two
    wires with one key (one stroke; its annotations are the first a leg has).

    Returns (wires without the collapsed events' wires, then the emit wires;
    the collapsed event ids; {destination id: [event nodes landing there]})."""
    emits, landed, gone = [], {}, []
    for ev in pass_through_candidates(g):
        into = [w for w in wires if w.dst == ev and w.kind != "trigger" and w.src != ev]
        onward = [w for w in wires if w.src == ev and w.dst != ev]
        if not into or not onward:
            continue
        gone.append(ev)
        for a in into:
            for b in onward:
                emits.append(emit_wire(a, b, ev, nodes))
                if b.kind != "trigger":
                    events = landed.setdefault(b.dst, [])
                    if nodes[ev].node not in events:
                        events.append(nodes[ev].node)
    kept = [w for w in wires if w.src not in gone and w.dst not in gone]
    return kept + emits, frozenset(gone), landed


def emit_wire(a: Wire, b: Wire, ev: str, nodes: dict) -> Wire:
    """The wire a's emitter → b's destination through the event ev."""
    kind = "!>" if a.kind == "!>" and b.kind != "trigger" else b.kind
    driven = b.role == "trigger"
    w = Wire(a.src, b.dst, kind, "emit", (a.src, b.dst, kind), notes=a.notes + b.notes,
             paths=(a.paths[0], b.paths[1]), via=ev, line=a.line, owner=a.owner,
             level=a.level, label=b.label if driven else None,
             machine=b.machine if driven else None, legs=(a, b))
    w.colour = wire_colour(w, _kind_of(nodes, a.src))
    return w


# ---------------------------------------------------------------------------
# Annotations keyed by a stroke's key — what a view hangs on a drawn wire
# ---------------------------------------------------------------------------

def trailing_notes(idx: dict) -> dict:
    """Inline notes by what their line drew: (src, dst, kind) for a flow line, the
    node id for a line that only placed a node → [(number, text)]."""
    out = {}
    for nid, entries in idx.items():
        for num, text, kind, edges in entries:
            if kind == "inline":
                for key in (edges or (nid,)):
                    out.setdefault(key, []).append((num, text))
    return out


def chip_text(w: Wire, payloads: bool, mods: bool) -> str:
    """The chip a wire carries: its payload (payloads) and modifiers (mods),
    `payload ┆ mods` — a call's payload as call_text shows it; an emit wire's
    legs' chips joined ` · `."""
    if w.role == "emit":
        return " · ".join(t for t in (chip_text(leg, payloads, mods) for leg in w.legs) if t)
    payload, mtext = kit.chip_parts(w, payloads, mods)
    if payload and w.call is not None:
        payload = call_text(w.call)
    return kit.chip_text(payload, mtext)


def _keyed_all(scene: Scene, value, unit=ANY_UNIT) -> dict:
    """{key: [value(wire), …]} over the flow wires (an emit's legs included,
    collapsed or not, each once) then the emit wires, in that order; empty
    values are left out. `unit`: only the wires drawn in that unit."""
    flows = [w for w in scene.wires if w.role == "flow"]
    legs = [leg for w in scene.wires if w.role == "emit" for leg in w.legs
            if leg.role == "flow"]
    flows += list({id(leg): leg for leg in legs}.values())
    out = {}
    for w in flows + [w for w in scene.wires if w.role == "emit"]:
        v = value(w) if unit is ANY_UNIT or w.owner == unit else None
        if v:
            out.setdefault(w.key, []).append(v)
    return out


def _keyed(scene: Scene, value) -> dict:
    """{key: value(wire)}, the first non-empty value of a key (_keyed_all's order)."""
    return {key: vs[0] for key, vs in _keyed_all(scene, value).items()}


def chip_lists(scene: Scene, payloads: bool, mods: bool, unit=ANY_UNIT) -> dict:
    """{key: [chip text, …]} for every flow and emit stroke that carries one:
    every call on the stroke its own chip, in written order — several payloads
    into one target kept apart, never merged. `unit` (a unit owner, None: the
    document): only the strokes drawn in that unit."""
    return _keyed_all(scene, lambda w: chip_text(w, payloads, mods), unit)


def wire_notes(scene: Scene) -> dict:
    """trailing_notes(scene.notes) with each emit stroke carrying its legs' notes."""
    out = trailing_notes(scene.notes)
    for key, notes in _keyed(scene, lambda w: list(w.notes) if w.role == "emit" else None).items():
        out.setdefault(key, notes)
    return out


def join_marks(scene: Scene) -> dict:
    """{key: {"src" | "dst": join}} of the flows that leave or enter a drawn join."""
    return _keyed(scene, lambda w: dict(w.join) if w.role == "flow" else None)


# ---------------------------------------------------------------------------
# Graph-view wiring: what drives a machine, and permissions, as edges
# ---------------------------------------------------------------------------

def driver_wires(scene: Scene) -> list:
    """The wires that drive a state machine, in wire order: each trigger wire (an
    event → the state it enters) and each emit wire a trigger delivers (an
    emitter → that state, through an event drawn where it lands). Their
    `machine` is the machine's owner. A collapsed event drives nothing itself:
    its emitters do."""
    return [w for w in scene.wires if w.machine is not None and w.role in ("trigger", "emit")]


def trigger_edges(scene: Scene, nodes) -> list:
    """An edge driver ⇢ machine owner (kind "trigger") for each driver wire
    (driver_wires) whose source and machine are both in `nodes`, one per pair:
    how an overview shows what drives a machine. A machine's owner driving its
    own machine is no edge (with_trigger_sources draws it into the state)."""
    pairs = dict.fromkeys((w.src, w.machine) for w in driver_wires(scene)
                          if w.src != w.machine)
    return [kit.render.Edge(src=src, dst=m, kind="trigger")
            for src, m in pairs if src in nodes and m in nodes]


def with_trigger_sources(scene: Scene, machine, owner: str):
    """A state machine (the expansion of `owner`) as a graph view draws it: what
    drives it — an event, or the emitter of an event drawn where it lands — is a
    node with a trigger edge (╍) into the state it enters, one per pair. The
    transition labels those edges now show are dropped (an event is drawn once).
    Nothing drives it (or the triggers option is off): the machine itself."""
    ws = [w for w in driver_wires(scene)
          if w.machine == owner and w.dst in machine.nodes and w.src in scene.nodes]
    if not ws:
        return machine
    drawn = {w.label for w in ws}
    new_nodes = dict(machine.nodes)
    edges = [replace(e, label=None) if e.label in drawn else e for e in machine.edges]
    for src, dst in dict.fromkeys((w.src, w.dst) for w in ws):
        new_nodes.setdefault(src, scene.nodes[src].node)
        edges.append(kit.render.Edge(src=src, dst=dst, kind="trigger"))
    return replace(machine, nodes=new_nodes, edges=edges)


def access_edges(scene: Scene, nodes, unit=ANY_UNIT) -> list:
    """An edge principal → store (kind access:r|w|b) for each access wire with
    both ends in `nodes`; with `unit` (a unit owner, None: the document), only
    the wires of that unit's graph — its own permissions."""
    return [kit.render.Edge(src=w.src, dst=w.dst, kind=w.kind, line=w.line)
            for w in scene.wires if w.role == "access"
            and (unit is ANY_UNIT or w.owner == unit)
            and w.src in nodes and w.dst in nodes]


# ---------------------------------------------------------------------------
# The colour policy
# ---------------------------------------------------------------------------

def arrow_colour(kind: str) -> Optional[str]:
    """The theme role of an arrow's own colour, or None when it has none (it
    then takes its source's kind colour)."""
    if kind == "trigger":
        return "kinds-event"
    role = kit.EDGE_ROLE.get(kit._base_kind(kind))
    return f"edges-{role}" if role else None


def wire_colour(w: Wire, src_kind: str) -> str:
    """The colour policy: the theme role a wire is drawn in (see the module
    docstring); src_kind is its source node's kind."""
    if w.kind == "!>":
        return "edges-fail"
    if w.role == "emit":
        return "kinds-event"
    return arrow_colour(w.kind) or (f"kinds-{src_kind}" if src_kind else "edges-default")


def colour_of(role: str):
    """A theme role ("edges-fail", "kinds-service") as the theme's Colour now."""
    section, _, key = role.partition("-")
    if section == "kinds":
        return kit.kind_color(key)
    arrow = next((a for a, r in kit.EDGE_ROLE.items() if r == key), None)
    return kit.EDGE_COLOR[arrow] if arrow else kit.EDGE_DEFAULT


def wire_style(w: Wire, state: str = "plain"):
    """The (fg, bg, bold) style a wire's stroke and head are drawn in. A
    simulation overlay: "active" full colour and bold, "inactive" muted,
    "failed" edges-fail and bold. Raises ValueError for an unknown state."""
    if state not in STATES:
        raise ValueError(f"state must be one of {', '.join(STATES)}, not {state!r}")
    if state == "failed":
        return (colour_of("edges-fail"), None, True)
    colour = colour_of(w.colour)
    if state == "inactive":
        return (kit.muted(colour), None, False)
    return (colour, None, state == "active")
