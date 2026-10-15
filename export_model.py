"""
export_model.py — the export model: a spec read as systems of components, each
with one home, an interface, requirements and a lifecycle, and per-system
interface and body hashes. Pure functions: text (or a parsed Graph) in, a Model
out; nothing here reads or writes a file.

Not a command: export.py writes the folder from it, check_export.py reads its
facts (SGC401, SGC402).

    model = build_model(text, stem="shop")
    model.systems["shop"].interface_hash, model.systems["shop"].body_hash
    to_json(model)          # the normalised, JSON-able form

SYSTEMS (inferred, no syntax of their own)

  top        the document, named after the given stem
  expansion  every `X := { … }` (or `[X] := expr`) expansion: a system named X
             holding the nodes of its body. A nested expansion is a system of
             its own; its parent depends on it. An alias body (`name := …`) is
             no system: its nodes belong to the system it is written in. A
             `state` machine is no system: it is its owner's lifecycle.
  tree       every composition-tree root (a glyph with `\\-` branches) is a
             system holding every node of its tree below it.

  A system's FACE is the node it is named after (the expansion's owner, the
  tree's root). The face is no member of its own system: it lives where it is
  written, and stands for the system there (a flow into [Shop] at the top
  level is a flow into the Shop system).

HOMES

  A node's candidate systems are the systems it is written in (in a tree, the
  tree's system; elsewhere the system of the graph). Its HOME is the candidate
  that encloses all the others (a node written in the top level and in an
  expansion is shared at the top level). When no candidate encloses the rest
  (a member of two sibling expansions, of two trees) the node has no one home:
  it is listed in Model.shared (SGC401) and lives in its first candidate.

COMPONENTS

  One per node that is a service, store, event, actor or data glyph (or a kind
  a dialect adds); holes, aliases and states are none. Each has:
  description   its `#` comments (render's notes about it), acknowledgements aside
  interface     every flow in or out of it (Flow), with the peer, arrow, mode
                (sync, async, return, failure, optional), payload, op, return,
                the call's modifiers (its policy: retries, timeouts, fallbacks)
  requirements  modifiers written on it (`@inv` `@owns` `@read` `×N` `^N` …),
                the access it is granted (`|S| @read(P)` → P reads |S|), and
                every `# accepts:` acknowledgement covering a line it is on,
                verbatim
  lifecycle     its state machine (states, initial, terminal, transitions)

BOUNDARIES AND DEPENDENCIES

  A node is IN a system when it is homed there or is its face. A flow crosses a
  system's boundary when exactly one end is in it; the system's interface is
  those flows. System A depends on B when a flow leaves a node in A for a node
  in B (`<->` both ways), and on every system nested in it. A boundary flow
  with no payload (neither end a data or event glyph either) or a synchronous
  call with no `=> return` is listed in Model.untyped (SGC402).

HASHES

  sha256 of canonical JSON (sorted keys, compact separators), first 16 hex.
  interface_hash covers the system's boundary flows; body_hash everything in it
  (interface, members, internal flows, control blocks, descriptions). No line
  numbers, whitespace or order from the source enter either.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, NamedTuple, Optional


_HERE = Path(__file__).resolve().parent


def _sibling(name: str, fname: str):
    """The module fname beside this file, loaded by path once per directory and then
    shared (the same loader check.py, scene.py and the views use, so a Graph built
    by any of them is one this module reads)."""
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


def _render():
    return _sibling("sigil_viewkit", "viewkit.py").render


def _scene():
    return _sibling("sigil_scene", "scene.py")


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

GLYPH_BRACKETS = {"service": "[]", "data": "{}", "event": "<>", "actor": "()", "store": "||"}
NOT_COMPONENTS = frozenset({"state", "alias"})
TYPED_KINDS = frozenset({"data", "event"})          # a glyph that is its own payload
ASYNC_ARROWS = frozenset({"~>", "*>"})
ARROW_MODE = {"->": "sync", "→": "sync", "<->": "sync", "~>": "async", "*>": "async",
              "=>": "return", "!>": "failure", "?>": "optional"}
HASH_LEN = 16


@dataclass(frozen=True)
class Flow:
    """One flow between two components, as written (node ids at both ends)."""
    src: str
    dst: str
    arrow: str
    line: int
    payload: Optional[str] = None
    text: Optional[str] = None          # a `\"\"\"…\"\"\"` payload's body
    op: Optional[str] = None
    returns: Optional[str] = None
    external: bool = False
    mods: tuple = ()                    # the call's policy, (name, arg) pairs
    card: Optional[str] = None
    implied: Optional[str] = None
    paths: tuple = (None, None)

    @property
    def is_call(self) -> bool:
        return self.op is not None and self.src != self.dst


@dataclass(frozen=True)
class Lifecycle:
    states: tuple
    initial: tuple
    terminal: tuple
    transitions: tuple                  # (from, to, on, mods)


@dataclass(frozen=True)
class Component:
    id: str
    name: str
    kind: str
    glyph: str                          # as the spec writes it: `[Api]`, `~{Session}`
    home: str                           # system key
    systems: tuple                      # every candidate system, first seen first
    description: tuple
    flows: tuple                        # Flows touching it
    modifiers: tuple                    # (name, arg), sorted
    access: tuple                       # (mode, store glyph), sorted
    accepts: tuple                      # `accepts: …` comment texts, verbatim
    lifecycle: Optional[Lifecycle]
    lines: tuple                        # the lines it is written on


@dataclass(frozen=True)
class System:
    key: str                            # unique name: the face's name or the stem
    name: str
    kind: str                           # "top" | "expansion" | "tree"
    face: Optional[str]                 # node id it is named after (None: top)
    parent: Optional[str]
    members: tuple                      # component ids homed here
    description: tuple
    interface: tuple                    # boundary Flows
    internal: tuple                     # Flows with both ends in it
    blocks: tuple                       # (kind, header, mods) of its control blocks
    depends_on: tuple
    accepts: tuple = ()                 # document-wide acknowledgements (top only)
    interface_hash: str = ""
    body_hash: str = ""


@dataclass(frozen=True)
class Shared:
    """A component written in systems none of which encloses the rest (SGC401)."""
    component: str
    glyph: str
    systems: tuple
    home: str
    lines: tuple


@dataclass(frozen=True)
class Untyped:
    """A boundary flow that states no payload, or a call no return (SGC402)."""
    line: int
    src: str                            # glyphs
    dst: str
    arrow: str
    missing: str                        # "payload" | "return"
    systems: tuple                      # the systems whose boundary it crosses


@dataclass(frozen=True)
class Model:
    stem: str
    top: str
    systems: dict                       # key → System, top first
    components: dict                    # node id → Component
    shared: tuple
    untyped: tuple


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def build_model(text: str, stem: str, dialect=None) -> Model:
    """The model of a document: parsed with render, its acknowledgements read as
    check.py reads them."""
    render = _render()
    check = _sibling("sigil_check", "check.py")
    lines = text.splitlines()
    graph = render.parse_document(text, dialect=dialect)
    comments = {k + 1: v for k, v in render.collect_comments(lines, dialect).items()}
    acks = check.read_acks(comments, check.layout_of(lines, render.strip_comment),
                           frozenset(check.CORE_NAMES.values()))
    return model_of(graph, lines, stem, acks)


def model_of(graph, lines: list, stem: str, acks: Iterable = ()) -> Model:
    """The model of a parsed document. `lines` are its source lines; `acks` its
    acknowledgements (objects with `line`, `span` and `document`, as check.Ack)."""
    render = _render()
    layout = lay_out(graph, stem)
    homes, shared_at = resolve_homes(layout)
    nodes = component_nodes(graph)
    flows = collect_flows(graph, nodes)
    facts = Facts(graph, layout, homes, flows,
                  {nid: glyph([n]) for g in walk(graph) for nid, n in g.nodes.items()},
                  tuple((a, ack_text(lines, a.line, render.comment_start)) for a in acks))
    appears = appearance_lines(lines, nodes, flows, render.strip_comment)
    components = {nid: make_component(nid, insts, appears[nid], facts)
                  for nid, insts in nodes.items()}
    inside = in_systems(components, layout)
    systems = make_systems(facts, components, inside)
    shared = tuple(Shared(nid, components[nid].glyph, cands, homes[nid],
                          components[nid].lines) for nid, cands in shared_at.items())
    untyped = untyped_flows(flows, components, inside)
    return Model(stem, layout.top, systems, components, shared, untyped)


class Facts(NamedTuple):
    """What the components and systems are made from, gathered once."""
    graph: object                       # render.Graph
    lay: "Layout"
    homes: dict                         # node id → system key
    flows: list                         # Flows, document order
    glyphs: dict                        # node id → glyph, every node
    acks: tuple                         # (acknowledgement, its comment text)


# ---------------------------------------------------------------------------
# Systems and homes
# ---------------------------------------------------------------------------

@dataclass
class Layout:
    """What walking the graphs finds: the systems (key → (name, kind, face,
    parent)), each node's candidate systems, the system of each graph and the
    state machines by owner."""
    top: str
    systems: dict
    by_face: dict
    candidates: dict
    graph_system: dict                  # id(graph) → system key
    machines: dict                      # owner node id → state Graph


def lay_out(graph, stem: str) -> Layout:
    lay = Layout(stem, {stem: (stem, "top", None, None)}, {}, {}, {}, {})
    _lay_graph(graph, stem, lay)
    return lay


def _lay_graph(g, key: str, lay: Layout):
    """Record g (written in system `key`): its trees, its nodes' candidates, and
    then its expansions, depth first."""
    lay.graph_system[id(g)] = key
    roots = tree_roots(g.tree)
    member = {}
    for i, entry in enumerate(g.tree):
        if roots[i] != i:
            root = g.nodes[g.tree[roots[i]].node]
            member.setdefault(entry.node, []).append(root)
    local = {}                          # node id → the system it is written in here
    for nid in g.nodes:
        if nid not in member:
            local[nid] = key
            _add(lay.candidates, nid, key)
            _tree_face(g, nid, key, roots, lay)
    for nid, root_nodes in member.items():
        keys = [_system_for(lay, root, "tree", None) for root in root_nodes]
        for k in keys:
            _add(lay.candidates, nid, k)
        local[nid] = keys[0]
        _tree_face(g, nid, keys[0], roots, lay)
    for owner, sub in g.expansions.items():
        node = g.nodes.get(owner)
        if sub.role == "state":
            lay.machines.setdefault(owner, sub)
        elif node is None or node.kind == "alias":
            _lay_graph(sub, key, lay)
        else:
            parent = local.get(owner, key)
            _lay_graph(sub, _system_for(lay, node, "expansion", parent), lay)


def _tree_face(g, nid: str, parent: str, roots: list, lay: Layout):
    """A tree root with branches in g is the face of a tree system."""
    if any(roots[i] == i and _has_children(g.tree, i)
           for i, e in enumerate(g.tree) if e.node == nid):
        _system_for(lay, g.nodes[nid], "tree", parent)


def tree_roots(tree: list) -> list:
    """For each entry, the index of the root of its tree."""
    out = []
    for e in tree:
        out.append(len(out) if e.parent is None else out[e.parent])
    return out


def _has_children(tree: list, i: int) -> bool:
    return any(e.parent == i for e in tree)


def _system_for(lay: Layout, node, kind: str, parent: Optional[str]) -> str:
    """The key of the system `node` is the face of, made on first ask. A system
    first met through its members gets its parent when its face is laid out."""
    key = lay.by_face.get(node.id)
    if key is not None:
        name, k, face, old = lay.systems[key]
        if old is None and parent is not None and parent != key:
            lay.systems[key] = (name, k, face, parent)
        return key
    key = unique_key(node.name, node.kind, lay.systems)
    lay.systems[key] = (node.name, kind, node.id, parent)
    lay.by_face[node.id] = key
    return key


def unique_key(name: str, kind: str, taken) -> str:
    key, n = name, 1
    if key in taken:
        key = f"{name} ({kind})"
    while key in taken:
        n += 1
        key = f"{name} ({kind} {n})"
    return key


def _add(index: dict, k, value):
    vals = index.setdefault(k, [])
    if value not in vals:
        vals.append(value)


def ancestors(key: str, systems: dict) -> list:
    """key, its parent, … up to the top (a cycle stops the walk)."""
    out = []
    while key is not None and key not in out:
        out.append(key)
        key = systems[key][3]
    return out


def resolve_homes(lay: Layout) -> tuple:
    """({node id: home}, {node id: candidates} for the nodes with no one home)."""
    homes, shared = {}, {}
    for nid, cands in lay.candidates.items():
        home = next((c for c in cands
                     if all(c in ancestors(o, lay.systems) for o in cands)), None)
        if home is None:
            shared[nid] = tuple(cands)
            home = cands[0]
        homes[nid] = home
    return homes, shared


def in_systems(components: dict, lay: Layout) -> dict:
    """{node id: frozenset of the systems it is in}: its home and the system it
    is the face of."""
    return {nid: frozenset({c.home} | ({lay.by_face[nid]} if nid in lay.by_face else set()))
            for nid, c in components.items()}


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------

def walk(graph):
    """Every graph of the document that is no state machine, depth first."""
    for g, _owner, _level in _render()._walk(graph):
        if g.role != "state":
            yield g


def component_nodes(graph) -> dict:
    """{node id: [Node instances]} of every component, first seen first."""
    out = {}
    for g in walk(graph):
        for nid, n in g.nodes.items():
            if n.kind not in NOT_COMPONENTS and not n.is_hole:
                out.setdefault(nid, []).append(n)
    return out


def glyph(insts: list) -> str:
    n = insts[0]
    lead = ("~" if any(i.is_mutable for i in insts) else "") + \
           ("*" if any(i.is_stream for i in insts) else "")
    br = GLYPH_BRACKETS.get(n.kind)
    return f"{lead}{br[0]}{n.name}{br[1]}" if br else f"{lead}{n.name}"


def make_component(nid: str, insts: list, lines: tuple, facts: Facts) -> Component:
    """The component of node `nid` (its Node instances, one per graph it is in;
    `lines`: the lines it is written on)."""
    n, lay = insts[0], facts.lay
    return Component(
        id=nid, name=n.name, kind=n.kind, glyph=glyph(insts),
        home=facts.homes.get(nid, lay.top),
        systems=tuple(lay.candidates.get(nid, (lay.top,))),
        description=description(facts.graph, nid),
        flows=tuple(f for f in facts.flows if nid in (f.src, f.dst)),
        modifiers=tuple(sorted({norm_mod(m) for i in insts for m in i.mods},
                               key=_mod_key)),
        access=granted_access(facts.graph, nid, facts.glyphs),
        accepts=tuple(t for a, t in facts.acks
                      if not a.document and set(lines) & set(a.span)),
        lifecycle=lifecycle(lay.machines.get(nid)),
        lines=lines)


def description(graph, nid: str) -> tuple:
    """The texts of the notes about a node, in line order, acknowledgements aside."""
    notes = sorted((n for g in walk(graph) for n in g.notes if n.node == nid),
                   key=lambda n: n.line)
    return _dedup(ws(n.text) for n in notes if not is_ack_text(n.text))


def is_ack_text(text: str) -> bool:
    return text.strip().startswith("accepts:")


def granted_access(graph, nid: str, glyphs: dict) -> tuple:
    """(mode, store glyph) for every access a store grants this principal."""
    out = set()
    for g in walk(graph):
        for a in g.access:
            if a.principal == nid:
                store = glyphs.get(a.store) if a.store else ws(a.store_name)
                mode = f"{a.mode}({a.narrow})" if a.narrow else a.mode
                out.add((mode, store or ""))
    return tuple(sorted(out))


def lifecycle(machine) -> Optional[Lifecycle]:
    if machine is None:
        return None
    name = {nid: n.name for nid, n in machine.nodes.items()}
    pseudo = {nid: n.attrs.get("pseudo") for nid, n in machine.nodes.items()}
    trans = tuple(sorted({(name[e.src], name[e.dst], e.label or "",
                           tuple(sorted({norm_mod(m) for m in e.mods}, key=_mod_key)))
                          for e in machine.edges}, key=repr))
    return Lifecycle(
        states=tuple(sorted(v for k, v in name.items() if not pseudo[k])),
        initial=tuple(sorted({name[e.dst] for e in machine.edges
                              if pseudo[e.src] == "start"})),
        terminal=tuple(sorted({name[e.src] for e in machine.edges
                               if pseudo[e.dst] == "end"})),
        transitions=trans)


def appearance_lines(lines: list, nodes: dict, flows: list, strip_comment) -> dict:
    """{node id: sorted lines it is written on}: its flows' lines and every line
    whose code holds its glyph."""
    out = {nid: set() for nid in nodes}
    for f in flows:
        for nid in (f.src, f.dst):
            if f.line:
                out[nid].add(f.line)
    marks = {nid: glyph([insts[0]]).lstrip("~*") for nid, insts in nodes.items()}
    for k, raw in enumerate(lines, start=1):
        code = strip_comment(raw)
        for nid, mark in marks.items():
            if mark in code:
                out[nid].add(k)
    return {nid: tuple(sorted(v)) for nid, v in out.items()}


def ack_text(lines: list, line: int, comment_start) -> str:
    """The acknowledgement comment on a 1-based line, verbatim (no `#`)."""
    raw = lines[line - 1] if 0 < line <= len(lines) else ""
    m = comment_start(raw, notes_only=True)
    return (raw[m.end():] if m else raw).strip()


# ---------------------------------------------------------------------------
# Flows
# ---------------------------------------------------------------------------

def collect_flows(graph, nodes: dict) -> list:
    """Every flow between two components, in document order."""
    out = []
    for g in walk(graph):
        for e in g.edges:
            if e.src in nodes and e.dst in nodes:
                out.append(flow_of(e))
    return sorted(out, key=lambda f: f.line)


def flow_of(e) -> Flow:
    scene, render = _scene(), _render()
    call = scene.edge_call(e)
    payload = ws(e.payload) if e.payload else None
    text = None
    if e.block_string is not None:
        text = "\n".join(ln.rstrip() for ln in e.block_string.strip("\n").splitlines())
        payload = payload.replace(render.BLOCK_SENTINEL, '"""…"""') if payload else None
    return Flow(
        src=e.src, dst=e.dst, arrow=e.kind, line=e.line, payload=payload, text=text,
        op=ws(call.op) if call and call.op else None,
        returns=ws(call.returns) if call and call.returns else None,
        external=bool(call and call.external),
        mods=tuple(sorted({norm_mod(m) for m in [*e.mods, *e.src_mods]}, key=_mod_key)),
        card=e.card, implied=e.implied,
        paths=(_path(e.src_path), _path(e.dst_path)))


def _path(p) -> Optional[str]:
    return "/".join(p) if p else None


def crossing(f: Flow, inside: dict) -> bool:
    return f.src != f.dst and inside[f.src] != inside[f.dst]


def untyped_flows(flows: list, components: dict, inside: dict) -> tuple:
    """The boundary flows that state no payload, and the synchronous calls across
    a boundary that state no return."""
    out = []
    for f in flows:
        if f.implied or not crossing(f, inside):
            continue
        missing = untyped(f, components[f.src].kind, components[f.dst].kind)
        if missing:
            out.append(Untyped(f.line, components[f.src].glyph, components[f.dst].glyph,
                               f.arrow, missing,
                               tuple(sorted(inside[f.src] ^ inside[f.dst]))))
    return tuple(out)


def untyped(f: Flow, src_kind: str, dst_kind: str) -> Optional[str]:
    """"payload", "return" or None for one boundary flow."""
    if not f.payload and src_kind not in TYPED_KINDS and dst_kind not in TYPED_KINDS:
        return "payload"
    if f.is_call and not f.returns and f.arrow not in ASYNC_ARROWS and f.arrow != "=>":
        return "return"
    return None


# ---------------------------------------------------------------------------
# Systems, assembled
# ---------------------------------------------------------------------------

def make_systems(facts: Facts, components: dict, inside: dict) -> dict:
    """Every system with its members, boundary, flows, blocks, dependencies and
    hashes; the top one also holds the document-wide acknowledgements."""
    lay, flows, graph = facts.lay, facts.flows, facts.graph
    doc_accepts = tuple(t for a, t in facts.acks if a.document)
    deps = dependencies(lay, flows, inside)
    out = {}
    for key, (name, kind, face, parent) in lay.systems.items():
        sysm = System(
            key=key, name=name, kind=kind, face=face, parent=parent,
            members=tuple(nid for nid, c in components.items() if c.home == key),
            description=system_description(graph, lay, key, face),
            interface=tuple(f for f in flows
                            if crossing(f, inside)
                            and (key in inside[f.src]) != (key in inside[f.dst])),
            internal=tuple(f for f in flows
                           if key in inside[f.src] and key in inside[f.dst]),
            blocks=system_blocks(graph, lay, key),
            depends_on=tuple(sorted(deps.get(key, ()))),
            accepts=doc_accepts if kind == "top" else ())
        out[key] = sysm
    return {k: with_hashes(s, components) for k, s in out.items()}


def dependencies(lay: Layout, flows: list, inside: dict) -> dict:
    """{system: {systems it depends on}}: the systems its flows reach, and the
    systems nested in it."""
    deps = {}
    for key, (_n, _k, _f, parent) in lay.systems.items():
        if parent is not None and parent != key:
            _add(deps, parent, key)
    for f in flows:
        pairs = [(f.src, f.dst)] + ([(f.dst, f.src)] if f.arrow == "<->" else [])
        for a, b in pairs:
            for sa in inside[a]:
                for sb in inside[b]:
                    if sa != sb:
                        _add(deps, sa, sb)
    return deps


def system_description(graph, lay: Layout, key: str, face: Optional[str]) -> tuple:
    """The top level's document header; an expansion's body header notes; and
    the face's own description."""
    texts = [n.text for g in walk(graph) if lay.graph_system.get(id(g)) == key
             and (g is graph or lay.systems[key][1] == "expansion")
             for n in g.notes if n.node is None and n.block is None]
    if face is not None:
        texts += description(graph, face)
    return _dedup(ws(t) for t in texts if not is_ack_text(t))


def system_blocks(graph, lay: Layout, key: str) -> tuple:
    return tuple(sorted({(b.kind, ws(b.header),
                          tuple(sorted({norm_mod(m) for m in b.modifiers}, key=_mod_key)))
                         for g in walk(graph) if lay.graph_system.get(id(g)) == key
                         for b in g.blocks}, key=repr))


# ---------------------------------------------------------------------------
# The normalised form and the hashes
# ---------------------------------------------------------------------------

def flow_json(f: Flow, components: dict, side: Optional[str] = None) -> dict:
    """A flow as JSON: `from` / `to` glyphs, or seen from component `side`:
    `dir` (out, in, self) and `peer`."""
    if side is None:
        ends = {"from": components[f.src].glyph, "to": components[f.dst].glyph}
    else:
        d = "self" if f.src == f.dst else "out" if f.src == side else "in"
        ends = {"dir": d, "peer": components[f.dst if d == "out" else f.src].glyph}
    return _compact({
        **ends, "arrow": f.arrow, "mode": ARROW_MODE.get(f.arrow, "flow"),
        "payload": f.payload, "text": f.text, "op": f.op, "returns": f.returns,
        "external": f.external, "mods": [list(m) for m in f.mods], "card": f.card,
        "implied": f.implied, "from_path": f.paths[0], "to_path": f.paths[1]})


def component_json(c: Component, components: dict) -> dict:
    lc = c.lifecycle
    return _compact({
        "name": c.name, "kind": c.kind, "glyph": c.glyph, "home": c.home,
        "also_in": [s for s in c.systems if s != c.home],
        "description": list(c.description),
        "interface": _sorted([flow_json(f, components, c.id) for f in c.flows]),
        "requirements": _compact({
            "modifiers": [list(m) for m in c.modifiers],
            "access": [list(a) for a in c.access],
            "accepts": sorted(c.accepts)}) or None,
        "lifecycle": None if lc is None else {
            "states": list(lc.states), "initial": list(lc.initial),
            "terminal": list(lc.terminal),
            "transitions": [_compact({"from": a, "to": b, "on": on,
                                      "mods": [list(m) for m in mods]})
                            for a, b, on, mods in lc.transitions]}})


def system_json(s: System, components: dict) -> dict:
    """One system in its normalised, JSON-able form (what system.json holds)."""
    return _compact({
        "name": s.name, "kind": s.kind,
        "face": components[s.face].glyph if s.face in components else None,
        "parent": s.parent, "depends_on": list(s.depends_on),
        "description": list(s.description),
        "interface": _sorted([flow_json(f, components) for f in s.interface]),
        "flows": _sorted([flow_json(f, components) for f in s.internal]),
        "blocks": [_compact({"kind": k, "header": h, "mods": [list(m) for m in mods]})
                   for k, h, mods in s.blocks],
        "components": sorted((component_json(components[m], components) for m in s.members),
                             key=lambda c: (c["glyph"], c["kind"])),
        "accepts": sorted(s.accepts),
        "hashes": {"interface": s.interface_hash, "body": s.body_hash}
        if s.body_hash else None})


def with_hashes(s: System, components: dict) -> System:
    body = system_json(s, components)
    iface = body.get("interface", [])
    for k in ("parent", "depends_on"):
        body.pop(k, None)
    return replace(s, interface_hash=digest(iface), body_hash=digest(hash_form(body)))


def hash_form(obj):
    """obj with every `description` list sorted, so moving a commented statement
    changes no hash (the descriptions' order is the source's)."""
    if isinstance(obj, dict):
        return {k: sorted(v) if k == "description" and isinstance(v, list)
                else hash_form(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [hash_form(v) for v in obj]
    return obj


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(obj) -> str:
    """sha256 of obj's canonical JSON, first 16 hex digits."""
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()[:HASH_LEN]


def to_json(model: Model) -> dict:
    """The whole model, normalised: systems by key, the readiness facts."""
    return {
        "spec": model.stem, "top": model.top,
        "systems": {k: system_json(s, model.components) for k, s in model.systems.items()},
        "shared": [{"component": s.glyph, "systems": list(s.systems), "home": s.home}
                   for s in model.shared],
        "untyped": [{"line": u.line, "from": u.src, "to": u.dst, "arrow": u.arrow,
                     "missing": u.missing, "systems": list(u.systems)}
                    for u in model.untyped]}


# ---------------------------------------------------------------------------
# Names on disk
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug(name: str) -> str:
    """An ASCII-safe file name for a name: lower-case letters, digits and `-`;
    any other character by its code point (`Café` → `caf-e9`)."""
    out = []
    for ch in name.lower():
        out.append(ch if ch.isascii() else f"-{ord(ch):x}-")
    s = _SLUG_RE.sub("-", "".join(out)).strip("-")
    return s or "x"


def slugs(names: Iterable) -> dict:
    """{name: slug}, collision-free (a later name that would clash, case aside,
    gets `-2`, `-3` …), in the order given."""
    out, taken = {}, set()
    for name in names:
        base = s = slug(name)
        n = 1
        while s in taken:
            n += 1
            s = f"{base}-{n}"
        taken.add(s)
        out[name] = s
    return out


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def ws(text: str) -> str:
    """Whitespace runs as one space, ends trimmed."""
    return " ".join(text.split())


def norm_mod(m: tuple) -> tuple:
    name, arg = m
    return (name, ws(arg) if isinstance(arg, str) else arg)


def _mod_key(m: tuple) -> tuple:
    return (m[0], m[1] or "")


def _dedup(items) -> tuple:
    return tuple(dict.fromkeys(i for i in items if i))


def _sorted(items: list) -> list:
    return sorted(items, key=canonical)


def _compact(d: dict) -> dict:
    """d without its None, False and empty values."""
    return {k: v for k, v in d.items()
            if v is not None and v is not False and v not in ("", [], {}, ())}
