"""
The export model: a spec read as systems of components, each with one home, an
interface, requirements and a lifecycle. Pure functions: a parsed Graph in, a
Model out; nothing here reads or writes a file.

Check's export rules read its facts (SGC401, SGC402); sigil.publish.systems
adds the per-system interface and body hashes, the normalised JSON and the
folder slugs that export writes (its model_of / build_model fill the hashes; a
Model from here leaves them "").

    model = model_of(graph, lines, stem="shop", acks=acks)
    model.shared, model.untyped

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

  A system's KEY is its name; systems sharing a name (or the stem) get a
  ` (kind)` suffix by a stable rule — their face's node kind (a service keeps
  the plain name before a store, actor, event, data or a dialect's kind), then
  its id — never by which comes first in the source.

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
                verbatim (a line it is on: an edge, access list, join or block
                header naming it, or a statement it heads — a declaration, a
                tree root, a `\\-` branch; never a glyph inside a payload or
                an op's arguments)
  lifecycle     its state machine (states, initial, terminal, transitions)

BOUNDARIES AND DEPENDENCIES

  A node is IN a system when it is homed there or is its face. A flow crosses a
  system's boundary when exactly one end is in it; the system's interface is
  those flows. System A depends on B when a flow leaves a node in A for a node
  in B (`<->` both ways), and on every system nested in it. A boundary flow
  with no payload (neither end a data or event glyph either) or a synchronous
  call with no `=> return` is listed in Model.untyped (SGC402).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Iterable, NamedTuple, Optional

from sigil.core.graph import walk_depth
from sigil.core.lex import BLOCK_SENTINEL, comment_start


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

GLYPH_BRACKETS = {"service": "[]", "data": "{}", "event": "<>", "actor": "()", "store": "||"}
NOT_COMPONENTS = frozenset({"state", "alias"})
TYPED_KINDS = frozenset({"data", "event"})          # a glyph that is its own payload
ARROW_MODE = {"->": "sync", "→": "sync", "<->": "sync", "~>": "async", "*>": "async",
              "=>": "return", "!>": "failure", "?>": "optional"}


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
                                        # (picks the home; also_in lists them sorted)
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


def model_of(graph, lines: list, stem: str, acks: Iterable = ()) -> Model:
    """The model of a parsed document. `lines` are its source lines; `acks` its
    acknowledgements (objects with `line`, `span` and `document`, as check.Ack)."""
    layout = lay_out(graph, stem)
    homes, shared_at = resolve_homes(layout)
    nodes = component_nodes(graph)
    flows = collect_flows(graph, nodes)
    facts = Facts(graph, layout, homes, flows,
                  {nid: glyph([n]) for g in walk(graph) for nid, n in g.nodes.items()},
                  tuple((a, ack_text(lines, a.line)) for a in acks))
    appears = merged(graph_lines(graph, nodes), head_lines(graph, nodes))
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
    graph: object                       # sigil.core.graph.Graph
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
    face_kinds: dict = field(default_factory=dict)   # face node id → its node kind


def lay_out(graph, stem: str) -> Layout:
    """The layout of a document: systems keyed first by their face's node id, then
    renamed to their names (see named_keys), so no key depends on source order."""
    lay = Layout(stem, {stem: (stem, "top", None, None)}, {}, {}, {}, {})
    _lay_graph(graph, stem, lay)
    return renamed(lay, named_keys(lay))


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
    key = FACE_KEY + node.id            # provisional: unique, renamed by lay_out
    lay.systems[key] = (node.name, kind, node.id, parent)
    lay.by_face[node.id] = key
    lay.face_kinds[node.id] = node.kind
    return key


FACE_KEY = "\0"                         # prefix of a provisional system key
KEY_KINDS = ("service", "store", "actor", "event", "data")   # who keeps a shared name


def named_keys(lay: Layout) -> dict:
    """{provisional key: system key}: a system is keyed by its name; systems that
    share a name (or the top's) are told apart by a stable rule — by their face's
    node kind (KEY_KINDS order, a dialect's kinds after), then its node id —
    never by which comes first in the source."""
    names, taken = {lay.top: lay.top}, {lay.top}

    def rank(k):
        name, _kind, face, _parent = lay.systems[k]
        kind = lay.face_kinds[face]
        return (name, KEY_KINDS.index(kind) if kind in KEY_KINDS else len(KEY_KINDS),
                kind, face)

    faced = sorted((k for k in lay.systems if k != lay.top), key=rank)
    for k in faced:
        name, face = lay.systems[k][0], lay.systems[k][2]
        names[k] = unique_key(name, lay.face_kinds[face], taken)
        taken.add(names[k])
    return names


def renamed(lay: Layout, names: dict) -> Layout:
    """lay with every system key mapped through `names` (order kept)."""
    return replace(
        lay,
        systems={names[k]: (n, kd, f, names.get(p) if p is not None else None)
                 for k, (n, kd, f, p) in lay.systems.items()},
        by_face={f: names[k] for f, k in lay.by_face.items()},
        candidates={nid: [names[k] for k in ks] for nid, ks in lay.candidates.items()},
        graph_system={g: names[k] for g, k in lay.graph_system.items()})


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
    for g, _owner, _level in walk_depth(graph):
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


def graph_lines(graph, nodes: dict) -> dict:
    """{node id: lines it is written on}, as the graphs tell: the lines of the
    edges, access lists, joins and block headers naming it and the statements a
    trailing comment of its sits on. (viewkit.node_lines also guesses a line for
    a node nothing names, from its neighbours; a guessed line would hand it their
    acknowledgements, so head_lines adds the statements it heads instead.)"""
    out = {nid: set() for nid in nodes}

    def at(nid, line):
        if nid in out and line:
            out[nid].add(line)

    for g in walk(graph):
        for e in g.edges:
            at(e.src, e.line)
            at(e.dst, e.line)
        for a in g.access:
            at(a.principal, a.line)
            at(a.store, a.line)
        for j in g.joins:
            for m in j.members:
                at(m, j.line)
        for b in g.blocks:
            for m in b.refs:
                at(m, b.lines[0])
        for n in g.notes:
            if n.kind == "inline":
                at(n.node, n.line)
    return out


def head_lines(graph, nodes: dict) -> dict:
    """{node id: lines of the statements it heads}, as the parser recorded them
    (Graph.heads, TreeEntry.line): a declaration (`[Api] @sla(…)`), a tree root,
    a `\\-` branch's child, a definition. A glyph inside a payload or an op's
    arguments (`find(User)`) heads nothing."""
    out = {nid: set() for nid in nodes}
    for g in walk(graph):
        for line, nid in g.heads:
            if nid in out:
                out[nid].add(line)
        for t in g.tree:
            if t.node in out:
                out[t.node].add(t.line)
    return out


def merged(*found: dict) -> dict:
    """{node id: sorted lines} of several {node id: set of lines} maps."""
    out = {}
    for f in found:
        for nid, v in f.items():
            out.setdefault(nid, set()).update(v)
    return {nid: tuple(sorted(v)) for nid, v in out.items()}


def ack_text(lines: list, line: int) -> str:
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
    from sigil.model import scene
    call = scene.edge_call(e)
    payload = tight(e.payload) if e.payload else None
    text = None
    if e.block_string is not None:
        text = "\n".join(ln.rstrip() for ln in e.block_string.strip("\n").splitlines())
        payload = payload.replace(BLOCK_SENTINEL, '"""…"""') if payload else None
    return Flow(
        src=e.src, dst=e.dst, arrow=e.kind, line=e.line, payload=payload, text=text,
        op=tight(call.op) if call and call.op else None,
        returns=tight(call.returns) if call and call.returns else None,
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
    if f.is_call and not f.returns and ARROW_MODE.get(f.arrow) == "sync":
        return "return"
    return None


# ---------------------------------------------------------------------------
# Systems, assembled
# ---------------------------------------------------------------------------

def make_systems(facts: Facts, components: dict, inside: dict) -> dict:
    """Every system with its members, boundary, flows, blocks and dependencies
    (no hashes: sigil.publish.systems adds them); the top one also holds the
    document-wide acknowledgements."""
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
    return out


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
    return tuple(sorted({(b.kind, tight(b.header),
                          tuple(sorted({norm_mod(m) for m in b.modifiers}, key=_mod_key)))
                         for g in walk(graph) if lay.graph_system.get(id(g)) == key
                         for b in g.blocks}, key=repr))


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def ws(text: str) -> str:
    """Whitespace runs as one space, ends trimmed."""
    return " ".join(text.split())


_QUOTED = re.compile(r'"(?:[^"\\]|\\.)*"')        # a quoted string, kept as written
_TIGHT = re.compile(r"\s*([()\[\]{}<>|,:])\s*")   # whitespace beside these goes


def tight(text: str) -> str:
    """Token-level form of a payload, op, return, block header or modifier
    argument: whitespace runs as one space, none beside ( ) { } [ ] < > | , :
    and one each side of `=>`; quoted strings kept as written.
    `save( {Order} )=>{Ack}` → `save({Order}) => {Ack}`."""
    parts, at = [], 0
    for q in _QUOTED.finditer(text):
        parts += [_tight_bare(text[at:q.start()]), q.group()]
        at = q.end()
    parts.append(_tight_bare(text[at:]))
    return "".join(parts).strip()


def _tight_bare(text: str) -> str:
    """tight() for text holding no quoted string (a space at its ends, next to a
    quote, is kept as one)."""
    pieces = (_TIGHT.sub(r"\1", re.sub(r"\s+", " ", p)) for p in text.split("=>"))
    return re.sub(r" ?=> ?", " => ", "=>".join(pieces))


def norm_mod(m: tuple) -> tuple:
    name, arg = m
    return (name, tight(arg) if isinstance(arg, str) else arg)


def _mod_key(m: tuple) -> tuple:
    return (m[0], m[1] or "")


def _dedup(items) -> tuple:
    return tuple(dict.fromkeys(i for i in items if i))


