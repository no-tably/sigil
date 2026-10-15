"""Readings of a parsed Graph that every layer above shares — no drawing here.

    glyph text      node_label(n) (`[Api]`, `~{Session}`, `●` for a start
                    pseudo-state, a dialect kind's own brackets or label),
                    role_name(n) (`Worker‹N›`); the dialect's node kinds
                    (use_dialect_kinds) that node_label reads
    walks           walk_breadth(g): g, then its expansions, breadth-first
    where things    node_lines (first line a node is written on), section_of,
                    edge_blocks (the control block an edge is drawn in)
    joins, access   drawn_join, access_kind, writer_badges; base_kind of an
                    edge kind (`access:w` → `access`)

ALL_DEPTH is `--depth all`. Pure functions over duck-typed graph records
(sigil.core.parse's Graph, Node, Edge, …); this module imports none of sigil.
"""

# ---------------------------------------------------------------------------
# Glyph text
# ---------------------------------------------------------------------------

# Each core node kind's brackets. A dialect adds kinds through its NODE_KINDS
# mapping ({kind: {"open", "close", optional "label": fn(node) -> str, …}});
# use_dialect_kinds() makes them the ones node_label reads (the viewer's kit
# sets them with the kinds it draws).
GLYPH_KINDS = {
    "service": {"open": "[", "close": "]"},
    "data":    {"open": "{", "close": "}"},
    "event":   {"open": "<", "close": ">"},
    "actor":   {"open": "(", "close": ")"},
    "store":   {"open": "|", "close": "|"},
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
