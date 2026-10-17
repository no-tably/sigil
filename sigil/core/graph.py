"""The model — what sigil.core.parse reads a document into — and the readings
of it every layer above shares. No drawing here.

    records         Node, Edge, Graph, Trigger, Note, TreeEntry, Join, Access,
                    Block, Dropped, Section (described under THE MODEL below);
                    mk_id (a node's id from its name)
    glyph text      node_label(n) (`[Api]`, `~{Session}`, `●` for a start
                    pseudo-state, a dialect kind's own brackets or label),
                    role_name(n) (`Worker‹N›`); the dialect's node kinds
                    (use_dialect_kinds) that node_label reads
    walks           walk_depth(g): (graph, owner, level) depth-first;
                    walk_breadth(g): g, then its expansions, breadth-first;
                    occurrences / matching_occurrences of the composition tree
    where things    node_lines (first line a node is written on), section_of,
                    edge_blocks (the control block an edge is drawn in)
    joins, access   drawn_join, access_kind, writer_badges; base_kind of an
                    edge kind (`access:w` → `access`)

ALL_DEPTH is `--depth all` (sigil.cli's depth_arg reads `N|all`). Of sigil this
module imports only the glyph bracket table (sigil.core.lex.GLYPH_BRACKETS).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import NamedTuple, Optional

from sigil.core.lex import GLYPH_BRACKETS


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------
#
# THE MODEL — what parse_document returns, and what every consumer reads.
#
# One Graph per document; one more per `X := { … }` expansion / alias body /
# `state` machine, hung off the node it expands (Graph.expansions). The Graph is
# the single source of truth for every presentation (the Mermaid export, the terminal
# graph and tree views in view.py) and for a future simulation engine that walks
# pathways: viewers decide how to SHOW it, never what it MEANS. Every field below
# is filled by the parser; nothing is inferred later by a viewer.
#
# Identity. A node id is `mk_id(name + "_" + kind)` (`[Api]` → `Api_service`);
# a hole gets a document-unique suffix. An edge has no id: consumers that refer
# to edges (blocks, arms, notes) use the KEY `(src, dst, kind)`, which is what a
# viewer draws as one stroke. Line numbers are 1-based lines of the WHOLE source
# document, also inside expansion bodies.
#
# Graph fields
#   nodes       {id: Node} in first-seen order. Node.name is the glyph's text
#               without brackets, generics included (`[Cache<K,V>]` → name
#               "Cache<K,V>", params ("K", "V"), base_name "Cache"). Kinds:
#               service|data|event|actor|store (the five glyphs), state (a state
#               of a `state` machine), alias (a bare-word `name := …` definition),
#               plus any kind a dialect adds. Node.mods: every modifier written on
#               the node (see "Modifiers"). Node.is_role: a generic glyph whose
#               base name an `@read(…)` / `@write(…)` list names (a generic role).
#   edges       [Edge] in document order: one per (source, target) pair a flow
#               statement draws. `[A] & [B] -> [C]` is two edges; a `*>` fan-out
#               one per target. Edge.kind is the arrow as written (`->`, `→`,
#               `~>`, `<->`, `=>`, `!>`, `?>`, `*>`, or a dialect's). Edge.payload
#               is the terminal `: payload` text (final link only); Edge.mods the
#               statement's trailing modifiers (final link only); Edge.line the
#               source line. A flow whose target is an internal op-call
#               (`[Worker] -> run()`) is a self-edge with Edge.target_op = "run()"
#               (and that op as its payload).
#               Edge.card: the destination's cardinality written on this flow — a
#               `×N` glued to the destination glyph (`[LB] -> [App]×N`), or
#               trailing a flow with no payload (`[Api] -> [Shard] ×4`) — as its
#               text ("N", "4"); None. Edge.mods' `×N` is then only ever a RETRY
#               (one trailing a call's payload: `: charge() ×3`).
#               Edge.src_mods: the `@` modifiers written between this edge's
#               source glyph and its arrow (`[A] @timeout(3s) -> [B]`), which are
#               also the source node's (Node.mods); entity declarations aside.
#               Edge.implied: an edge the notation implies without an arrow —
#               "return" (`[J] -> [S] : score() => <rated>`: the callee S emits
#               `=> <rated>`) or "alert" (`|R|` `\-{lagging}-! <LagAlarm>`: R
#               emits `?> <LagAlarm>`, labelled with the condition); None.
#               An event glued to an argument (`<H>({C})`) is one glyph: the
#               argument is the payload of the edge into it.
#               Continuation lines: a line starting with an arrow takes the
#               SUBJECT (first endpoint) of the statement above it — consecutive
#               continuations keep that subject (language.md pitfall 9).
#   joins       [Join]: every endpoint made of several glyphs — `&` strict join
#               (all must succeed), `&?` race (first wins), `/` alternative (one
#               of). Edges point into it with Edge.src_join / Edge.dst_join (an
#               index into this list): `[Api] => {Resp} / {Err}` is two `=>`
#               edges whose dst_join names one "/" Join — exactly one fires.
#   blocks      [Block]: control blocks — loop | parallel | branch | scope
#               (`name { … }`) | owns (`[X] @owns |R| { … }`). members/edges are
#               what the body draws (nested blocks included); parent indexes this
#               list; arms (branch only) are [(label, [edge keys])] with
#               arm_nodes [(label, [node ids])] — the first node of an arm is its
#               entry. subject: the node ids a continuation after the closing `}`
#               hangs from (a `!>` compensation, per language.md Example 3); the
#               edges it draws are listed in `after`. refs: nodes named in the
#               header (`branch on {Request}.kind` → {Request}). Branch arms draw
#               no edge between arms: the branch is a choice, not a chain.
#   access      [Access]: the permission graph — `|S| @read(P)` / `@write(P)`
#               (one Access per principal, anchored on the store the modifier
#               follows) and `[P] @borrow(read)? |S|` (a borrowed |S| that is a
#               node nowhere else becomes one where the borrow is written — see
#               _place_borrowed). principal is the node id the name resolves to
#               (exact name first, then a generic role's base name —
#               `@read(Worker)` → `[Worker<N>]`), None if it names nothing.
#   sections    [Section(level, title, line)]: `--- L2: [Core] ---` → ("L2",
#               "[Core]", line); a topic header `--- Control ---` has level None.
#   layers      the Lk layers seen, in order (Node.layer is the one in force).
#   expansions  {node id: Graph}: `X := { … }` bodies, `X := expr` alias bodies,
#               `state X { … }` machines (role "state"). An expansion written in a
#               section `--- Lk ---` (k >= 3) attaches to the node of that name in
#               a level k-1 expansion (zoom nests), else to the top-level node.
#   tree        [TreeEntry]: composition trees (`\\-<rel>` branches), document order,
#               each with the line its node is written on.
#   heads       [(line, node id)]: the statements a glyph heads — a flow or
#               declaration whose first token is that glyph (`[Api] @sla(…)`,
#               a tree root, a `\\-` branch's child, an owns header) and a
#               definition (`[X] := …`) — in document order.
#   triggers    [Trigger]: events wired to state-machine transitions (top level).
#   narrowed    [Trigger]: the (event, transition) pairs trigger narrowing took
#               away — the event flows explicitly into other machines' owners
#               only (find_triggers; top level).
#   dropped     [Dropped(line, reason, text)]: source lines the parser read and
#               discarded, by line — reason "unclosed" (an expansion, `state` or
#               declaration block never closed: its body is lost), "no-owner" (a
#               `state {` with no owner glyph), "not-a-transition" (a `state`
#               body line that is no transition). A graph lists its own and its
#               expansions' lines, so the document's graph lists them all.
#   notes       [Note]: `#` comments attached to the node they describe — or to
#               the control block whose glyph-less header they sit above
#               (`branch on …`, `loop …`, `parallel …`, a scoped `name {`), or,
#               for a comment block detached from every statement before the
#               first one (a document header), to the document itself.
#   role        what this graph is when it hangs off a node: "expansion"|"state".
#
# Modifiers (Node.mods / Edge.mods / Block.modifiers) are (name, arg) pairs in
# written order; arg is the text inside the modifier's parens (or after it), or
# None. Names: an `@name` modifier is "name" (`@timeout(30s)` → ("timeout",
# "30s"), `@inv >= 0` → ("inv", ">= 0")); `×N` / `xN` → ("×", "N"); a stream
# bound `^10k@drop` → ("^", "10k@drop"); `!` critical → ("!", None); `?`
# optional → ("?", None); `.field` → (".", "field"); a modifier alias named
# after a retry (`: charge ×3 Retry`) → the modifiers `Retry := @after(…)`
# defines, or ("alias", "Retry") when no modifier-only alias has that name.
# A `×N` never sits on an edge as cardinality (see Edge.card). Placement: a modifier
# written between a glyph and the next arrow is that glyph's node's (after an
# op-call target, that self-call edge's: `-> plan() @deadline(2s) => {P}`); a
# statement's trailing modifiers belong to its final link's edges, or to its last
# glyph when the statement draws no edge. Declarations about an entity always go
# on the node: @loc @read @write @borrow @owns @grants @requires and `^N@policy`.
# Modifiers after the `}` of an `X := { … }` expansion or a `state X { … }` machine
# (`} @inv ordered(id)`) are X's node's.

@dataclass
class Node:
    id: str
    name: str
    kind: str  # service|data|event|actor|store|state|alias (+ kinds a dialect adds)
    is_hole: bool = False
    is_mutable: bool = False
    is_stream: bool = False
    layer: str = "L1"
    # Free-form metadata a dialect attaches to the nodes its tokenizers build
    # (core Sigil leaves it empty). See dialects.py NODE_KINDS.
    attrs: dict = field(default_factory=dict)
    # Every modifier written on this node, as (name, arg) — see "Modifiers" above.
    mods: list = field(default_factory=list)
    # Generic parameters (`[Cache<K,V>]` → ("K", "V")); empty for a plain glyph.
    params: tuple = ()
    # A generic role (`[Worker<N>]` whose base name an access list names as a
    # principal: `@read(Worker)`) — N members, drawn as a role. See _mark_roles.
    is_role: bool = False

    @property
    def base_name(self) -> str:
        """The name without its generics: `Cache<K,V>` → `Cache` (a role's name)."""
        return self.name.split("<", 1)[0].strip()


@dataclass
class Edge:
    src: str
    dst: str
    kind: str  # arrow kind
    label: Optional[str] = None
    # The raw `: payload` text of the flow this edge closes (grammar: the payload is
    # TERMINAL — `src arrow dst (':' payload)?`), kept for viewers. Not emitted into
    # Mermaid (payloads carry `${…}`/quotes/braces that break Mermaid labels).
    payload: Optional[str] = None
    # Qualified-path endpoints (`[Bullet]/{Transform}` → ("Bullet", "Transform")):
    # the flow reaches only the matching occurrences in the composition tree.
    src_path: Optional[tuple] = None
    dst_path: Optional[tuple] = None
    # The statement's trailing modifiers (final link only), as (name, arg).
    mods: list = field(default_factory=list)
    # Index into Graph.joins of the joined endpoint this edge leaves / enters.
    src_join: Optional[int] = None
    dst_join: Optional[int] = None
    # `[Worker] -> run()`: the op-call written as the target (a self-edge).
    target_op: Optional[str] = None
    line: int = 0
    # A continuation line's edge (one starting with an arrow): the line of the flow
    # it continues — the statement's line, or the latest continuation that drew work
    # (pitfall 4: an error path attaches to the most recent flow). 0: not one.
    cont: int = 0
    # The destination's cardinality written on this flow (`[LB] -> [App]×N` → "N").
    card: Optional[str] = None
    # The `@` modifiers written between the source glyph and the arrow.
    src_mods: list = field(default_factory=list)
    # "return" | "alert": an edge the notation implies (see the model notes).
    implied: Optional[str] = None
    # A `"""…"""` block-string payload's text (the payload itself keeps the masked
    # BLOCK_SENTINEL, so what reads the payload sees one STR); None when none.
    block_string: Optional[str] = None

    @property
    def key(self) -> tuple:
        return (self.src, self.dst, self.kind)


@dataclass
class Graph:
    nodes: dict = field(default_factory=dict)  # id → Node
    edges: list = field(default_factory=list)
    expansions: dict = field(default_factory=dict)  # parent_id → Graph
    layers: list = field(default_factory=list)
    # Shared across a document and its `:= { … }` sub-graphs so every hole gets a
    # document-unique id (a hole is "unspecified", never the SAME unspecified thing).
    hole_seq: list = field(default_factory=lambda: [0])
    # What this graph is when it hangs off a node: "expansion" (`X := { … }`) or
    # "state" (a `state {X} { … }` machine). Viewers use it for section titles.
    role: str = "expansion"
    # The composition tree (`\-<rel>` branches under a parent glyph), in document
    # order: TreeEntry per placed node. A node id may occur more than once (the same
    # component composed into several parents).
    tree: list = field(default_factory=list)
    # (line, node id) of each statement a glyph heads (see "heads" above).
    heads: list = field(default_factory=list)
    # Events wired to state-machine transitions by name (top-level graph only).
    triggers: list = field(default_factory=list)
    # Comments attached to nodes (the walk's comments, see parse_document).
    notes: list = field(default_factory=list)
    # Control blocks, joined endpoints, the permission graph, section headers —
    # see the model description above.
    blocks: list = field(default_factory=list)
    joins: list = field(default_factory=list)
    access: list = field(default_factory=list)
    sections: list = field(default_factory=list)
    # Transitions trigger narrowing took away, and the lines the parser discarded.
    narrowed: list = field(default_factory=list)
    dropped: list = field(default_factory=list)


@dataclass
class Trigger:
    event: str                # event node id
    owner: str                # node id owning the state machine
    src: str                  # state node id the transition leaves
    dst: str                  # state node id the transition enters
    label: str                # the trigger as written, `<Paid>`
    level: int                # nesting depth of the machine (for viewers / Mermaid)


@dataclass
class Note:
    # node id the comment belongs to; None when it is about a control block
    # (`block`) or, with no block either, about the whole document.
    node: Optional[str]
    text: str
    line: int                 # 1-based line of the (first) comment line
    # "block": own-line `#` comments directly above the statement (merged) —
    # about the component the statement is about;
    # "inline": the `#` comment trailing the statement on its own line — about
    # that line, so `edges` holds the (src, dst, kind) of the flows it drew
    # (empty for a line that only places a node, e.g. a branch).
    kind: str = "block"
    edges: tuple = ()
    # Index into its graph's blocks when the comment is about that block: own
    # lines above a glyph-less block header, or trailing a header with no body
    # on its line. The header places no node of its own, so a first arm's or
    # member's glyph would be the wrong home.
    block: Optional[int] = None


@dataclass
class TreeEntry:
    node: str                 # node id
    parent: Optional[int]     # index into Graph.tree, None for a root
    rel: Optional[str]        # relation char: > & ? $ @ ! = _ (+ any a dialect adds); None for a root
    spawn: bool = False       # `*-` prefix: instances spawned at runtime
    cond: Optional[str] = None  # `{cond}-` guard / source
    depth: int = 0
    weight: Optional[int] = None  # `(N)-` relative share among siblings
    line: int = 0             # the source line its node is written on


@dataclass
class Join:
    kind: str                 # "&" strict join | "&?" race | "/" alternative (one-of)
    members: list             # node ids, in written order
    line: int


@dataclass
class Access:
    principal: Optional[str]  # node id of the principal (None: names no node)
    store: Optional[str]      # node id of the store (None: a borrowed name that is no glyph)
    mode: str                 # "read" | "write" | "borrow"
    line: int
    name: str = ""            # the principal as written (`Worker`)
    narrow: Optional[str] = None  # `@borrow(read)` → "read"; None = the lender's full access
    store_name: str = ""      # `@borrow`: the store as written (`|Directives|`)


@dataclass
class Block:
    kind: str                 # "loop" | "parallel" | "branch" | "scope" | "owns"
    header: str               # `@while |Q|.nonempty`, `@all`, `{Request}.kind`, `checkout`, `[H] @owns |C|`
    modifiers: list = field(default_factory=list)   # (name, arg): ("while", "|Q|.nonempty"), ("all", None)
    members: list = field(default_factory=list)     # node ids drawn inside the body
    edges: list = field(default_factory=list)       # (src, dst, kind) drawn inside the body
    arms: list = field(default_factory=list)        # branch: [(label, [edge keys])]
    parent: Optional[int] = None                    # index into Graph.blocks
    lines: tuple = (0, 0)                           # (header line, closing line)
    refs: list = field(default_factory=list)        # node ids named in the header
    subject: list = field(default_factory=list)     # where a continuation after `}` hangs
    after: list = field(default_factory=list)       # edge keys of those continuations
    arm_nodes: list = field(default_factory=list)   # branch: [(label, [node ids])]


class Dropped(NamedTuple):
    line: int                 # 1-based source line
    reason: str               # "unclosed" | "no-owner" | "not-a-transition"
    text: str                 # the line as written, stripped


class Section(NamedTuple):
    level: Optional[str]      # "L2" for `--- L2: … ---`, None for a topic header
    title: str
    line: int


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

def _id_char(ch: str) -> str:
    """One character of a node id: ASCII letters, digits and `_` stay; other
    ASCII (punctuation, space) becomes `_`; a non-ASCII character becomes `u` +
    its code point in six hex digits (`利` → `u005229`). The fixed width keeps
    the encoding unambiguous: `Āb` (`u000100b`) and `ဋ` (`u00100b`) differ."""
    if ch.isascii():
        return ch if ch.isalnum() or ch == "_" else "_"
    return f"u{ord(ch):06x}"


# What follows a `u` in an id that would read as an encoded character: a code
# point in six hex digits (`0xxxxx` / `10xxxx`), or `_`s before one (a literal
# `u` there takes one more `_`). Words rarely hold one: `Succeeded` stays.
_CODE_AHEAD_RE = re.compile(r"_*(?:0[0-9a-f]|10)[0-9a-f]{4}")


@lru_cache(maxsize=8192)
def mk_id(name: str) -> str:
    """Make a Mermaid-safe ID ([A-Za-z0-9_], never a digit first) from a glyph
    name. Lossy only for ASCII punctuation: `[a-b]` / `[a_b]` share an id, so
    they draw as one node. A non-ASCII character is `u` + six hex digits, and a
    literal `u` that the rest of the id would make look like one gets one more
    `_` (`[u005229]` → `u_005229`, `[u_00e9ab]` → `u__00e9ab`), so `u` + a code
    point's six hex digits is always an encoded character: two names that
    differ in a non-ASCII character (`[利用者]` / `[転送器]`, `[Āb]` / `[ဋ]`,
    `[u005229]` / `[利]`) never share an id. Every other ASCII name keeps its
    id as written."""
    safe = ""
    for ch in reversed(name.strip()):
        lit_u = ch == "u" and _CODE_AHEAD_RE.match(safe)
        safe = ("u_" if lit_u else _id_char(ch)) + safe
    if safe and safe[0].isdigit():
        safe = "n" + safe
    return safe or "anon"



# ---------------------------------------------------------------------------
# Glyph text
# ---------------------------------------------------------------------------

# Each core node kind's brackets (a glyph kind's from lex.GLYPH_BRACKETS). A
# dialect adds kinds through its NODE_KINDS mapping ({kind: {"open", "close",
# optional "label": fn(node) -> str, …}}); use_dialect_kinds() makes them the
# ones node_label reads (the viewer's kit sets them with the kinds it draws).
GLYPH_KINDS = {
    **{kind: {"open": o, "close": c} for kind, (o, c) in GLYPH_BRACKETS.items()},
    "state":   {"open": "",  "close": ""},
    "alias":   {"open": "[[", "close": "]]"},   # `name := …`
}
DIALECT_KINDS: dict = {}            # the dialect's NODE_KINDS in use


def use_dialect_kinds(dialect) -> None:
    """Make the dialect's node kinds (its NODE_KINDS, if any; none: core only)
    the ones node_label and kind_spec read."""
    DIALECT_KINDS.clear()
    DIALECT_KINDS.update(getattr(dialect, "NODE_KINDS", None) or {})


def kind_spec(kind: str) -> dict:
    """A node kind's spec ("open", "close", maybe "label"): the dialect's when it
    defines the kind, else the core one, else {} (an unknown kind)."""
    if kind in DIALECT_KINDS:
        return DIALECT_KINDS[kind]
    return GLYPH_KINDS.get(kind, {})


PSEUDO_LABEL = {"start": "●", "end": "◉", "any": "∗ any"}


def node_label(n) -> str:
    """A node as the notation writes it: `[Api]`, `~{Session}`, `*<Tick>`, a
    pseudo-state's mark (PSEUDO_LABEL), a dialect kind in its own brackets (or
    its own label)."""
    spec = kind_spec(n.kind)
    if n.attrs.get("pseudo") in PSEUDO_LABEL:
        return PSEUDO_LABEL[n.attrs["pseudo"]]
    name = spec["label"](n) if "label" in spec else role_name(n)
    lead = ("~" if n.is_mutable else "") + ("*" if n.is_stream else "")
    return f"{lead}{spec.get('open', '[')}{name}{spec.get('close', ']')}"


def role_name(n) -> str:
    """A node's name, a generic role's generics in ‹ › (`Worker<N>` → `Worker‹N›`:
    N members of one role, not a parametric type)."""
    if not getattr(n, "is_role", False) or not n.name.endswith(">"):
        return n.name
    base = n.name.split("<", 1)[0]
    return f"{base}‹{n.name[n.name.index('<') + 1:-1]}›"


def base_kind(kind: str) -> str:
    """An edge kind without its qualifier: `access:w` → `access`."""
    return kind.split(":", 1)[0] if kind.startswith("access:") else kind


# ---------------------------------------------------------------------------
# Walks and where things are
# ---------------------------------------------------------------------------

ALL_DEPTH = 99                                  # --depth all


def walk_depth(g, owner=None, level=0):
    """(graph, owning node id, nesting level) for g and every nested graph, depth
    first in document order (a stack, so deep nesting costs no Python stack)."""
    todo = [(g, owner, level)]
    while todo:
        g, owner, level = todo.pop()
        yield g, owner, level
        if g.expansions:
            todo.extend((sub, nid, level + 1) for nid, sub in reversed(g.expansions.items()))


def occurrences(graph: Graph) -> list:
    """Per composition-tree entry: (occurrence id, name chain root→entry)."""
    occ = []
    for t in graph.tree:
        if t.parent is None:
            occ.append((t.node, (graph.nodes[t.node].name,)))
        else:
            pid, chain = occ[t.parent]
            occ.append((f"{pid}__{t.node}", chain + (graph.nodes[t.node].name,)))
    return occ


def matching_occurrences(graph: Graph, occ: list, nid: str, path) -> list:
    """Occurrence ids of node `nid` (all of them, or those whose name chain ends
    with the qualifying path)."""
    out = []
    for (oid, chain), t in zip(occ, graph.tree):
        if t.node == nid and (not path or chain[-len(path):] == tuple(path)):
            out.append(oid)
    return out


def walk_breadth(g):
    """g, then its expansions (and theirs), breadth-first in document order."""
    queue = [g]
    while queue:
        cur = queue.pop(0)
        yield cur
        queue += list(cur.expansions.values())


def node_lines(g, notes: bool = True) -> dict:
    """{node id: line}: where each node is first written, as near as the graph
    tells — the earliest line any edge, note (`notes`: block comments too, the
    line above), access, join, block or its own `:= { … }` names it on; for a node nothing names (a bare declaration),
    the earliest line of any node after it (nodes are kept in first-seen order),
    else the previous named node's."""
    seen = {}

    def at(nid, line):
        if nid and line and (nid not in seen or line < seen[nid]):
            seen[nid] = line

    for e in g.edges:
        at(e.src, e.line)
        at(e.dst, e.line)
    for n in getattr(g, "notes", []) or []:    # a block comment sits just above
        if notes or getattr(n, "kind", "block") == "inline":
            at(n.node, n.line)
    for a in getattr(g, "access", []) or []:
        at(a.principal, a.line)
        at(a.store, a.line)
    for j in getattr(g, "joins", []) or []:
        for m in j.members:
            at(m, j.line)
    for b in getattr(g, "blocks", []) or []:   # a header's refs; a member no flow names
        for m in list(b.refs) + [m for m in b.members if m not in seen]:
            at(m, b.lines[0])
    named = {nid: line for nid, line in seen.items()   # what bounds the nodes before it
             if nid in g.nodes and g.nodes[nid].kind != "alias"}
    for nid, sub in g.expansions.items():      # `X := { … }` names X above its body
        lines = [e.line for cur in walk_breadth(sub) for e in cur.edges if e.line]
        if lines:
            at(nid, min(lines))
    # A node only its own `:= { … }` / `state` body names (an alias, a machine's
    # owner) may be registered out of order: it bounds nothing.
    out, bound = {}, None
    for nid in reversed(list(g.nodes)):         # unnamed: no later than any later node
        if nid in seen:
            out[nid] = seen[nid]
        elif bound is not None:
            out[nid] = bound
        if nid in named:
            bound = named[nid] if bound is None else min(bound, named[nid])
    prev = None
    for nid in g.nodes:                         # nothing after it: the previous one's
        prev = named.get(nid, prev)
        if nid not in out and prev is not None:
            out[nid] = prev
    return out


def section_of(secs, line) -> int:
    """The index of the section a line is in (-1: before the first one)."""
    k = -1
    for i, sec in enumerate(secs or ()):
        if line and sec.line <= line:
            k = i
    return k


def edge_blocks(g) -> dict:
    """{edge index: block index}: the innermost control block each edge is drawn
    in — the block whose body holds its line, or whose `}` it continues (a `!>`
    compensation, Block.after)."""
    out = {}
    blocks = getattr(g, "blocks", None) or []
    holding, after = {}, {}                     # edge key → [block index], in order
    for bi, b in enumerate(blocks):
        for key in dict.fromkeys(b.edges):
            holding.setdefault(key, []).append(bi)
        for key in dict.fromkeys(b.after):
            after.setdefault(key, []).append(bi)
    for k, e in enumerate(g.edges):
        key, best = (e.src, e.dst, e.kind), None
        for bi in holding.get(key, ()):
            lo, hi = blocks[bi].lines
            if lo <= e.line <= hi or not e.line:
                if best is None or hi - lo < blocks[best].lines[1] - blocks[best].lines[0]:
                    best = bi
        if best is None:
            for bi in after.get(key, ()):
                b = blocks[bi]
                if e.line >= b.lines[1]:
                    if best is None or b.lines[1] > blocks[best].lines[1]:
                        best = bi
        if best is not None:
            out[k] = best
    return out


# ---------------------------------------------------------------------------
# Joins and access
# ---------------------------------------------------------------------------

def drawn_join(g, e, side: str):
    """The index into g.joins of the joined endpoint the edge leaves ("src") or
    enters ("dst") when that join is drawn, else None. A `*>` broadcast's target
    list (`*> [A] & [B]`) is not: the double fan-out already says "all of them"."""
    idx = e.src_join if side == "src" else e.dst_join
    joins = getattr(g, "joins", None) or []
    if idx is None or not 0 <= idx < len(joins):
        return None
    if side == "dst" and e.kind == "*>" and joins[idx].kind == "&":
        return None
    return idx


def access_kind(a) -> str:
    """A permission edge's kind: `access:r` read, `access:w` write, `access:b`
    borrow, `access:ƀ` a borrow narrowed to read (`@borrow(read)`). A borrow
    narrowed to write keeps `b`: only the write it lends is left."""
    if a.mode == "borrow" and getattr(a, "narrow", None) == "read":
        return "access:ƀ"
    return "access:" + a.mode[0]


def writer_badges(g) -> dict:
    """{store id: "1w" | "Nw"}: how many principals may write each store (the a
    key) — a single writer owns it, several share it."""
    writers = {}
    for a in getattr(g, "access", None) or []:
        if a.mode == "write" and a.store and a.principal:
            writers.setdefault(a.store, set()).add(a.principal)
    return {sid: f"{len(ps)}w" for sid, ps in writers.items()}
