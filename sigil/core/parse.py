"""
parse — a Sigil document read into the model (sigil.core.graph's records):
parse_document(text, dialect=…, walk=…) → Graph, parse_glyph. The document is
read once, by the statement walk (sigil.core.statements: sections, definitions,
`state` machines, control blocks, branch arms, each statement's tokens); this
module builds the model from that reading — nodes, edges, joins and modifiers
from each statement's tokens, composition trees from its branch marker,
expansions, machines, blocks, comments attached as notes, triggers wired to
transitions. What the model means is described under THE MODEL in
sigil.core.graph; the Mermaid export (sigil.publish.mermaid) and every other
reader take the Graph from here.
"""

import dataclasses
import re
from functools import lru_cache
from typing import NamedTuple, Optional

from sigil.core.lex import (  # noqa: F401  (also read as parse.<name> by the model's readers)
    ALIAS_REF, BLOCK_SENTINEL, BRANCH_RE, GLYPH_BRACKETS, GLYPH_RE, OP_TARGET_RE,
    OPEN_TO_KIND, strip_comment)
from sigil.core.graph import (  # noqa: F401  (also read as parse.<name>)
    Access, Block, Declared, Dropped, Edge, Graph, Join, Node, Note, Section, TreeEntry, Trigger,
    mk_id, walk_depth)
from sigil.core.statements import (
    BlockClose, BlockMods, BlockOpen, Blank, Declaration, Definition, Doc, Flow,
    Note as NoteItem, SectionHead, StateEnd, StateHead, Walk, read_document)
from sigil.core.tokens import lexicon, mod_pair, scan_mods

# ---------------------------------------------------------------------------
# Glyph parsing (the lexical tables are sigil.core.lex's)
# ---------------------------------------------------------------------------

def parse_glyph(text: str, layer: str = "L1", dialect=None) -> Optional[Node]:
    """The node a glyph's text names (a dialect's glyph first), or None."""
    text = text.strip()

    # Dialect glyph syntax first (its tokenizers see the glyph at position 0).
    for tok in lexicon(dialect).tokenizers:
        r = tok(text, 0, False, layer, Node)
        if r:
            for kind, node in r[0]:
                if kind == "glyph":
                    return node

    return _core_node(text, layer)


def _core_node(text: str, layer: str) -> Optional[Node]:
    """A fresh node for a core glyph's (stripped) text, or None."""
    fields = _core_glyph(text)
    if fields is None:
        return None
    gid, name, kind, is_hole, is_mutable, is_stream, params = fields
    return Node(id=gid, name=name, kind=kind, is_hole=is_hole, is_mutable=is_mutable,
                is_stream=is_stream, layer=layer, params=params)


@lru_cache(maxsize=4096)
def _core_glyph(text: str) -> Optional[tuple]:
    """A core glyph's node fields (id, name, kind, is_hole, is_mutable, is_stream,
    params), or None when the text is no glyph. Pure: a glyph is read once."""
    m = GLYPH_RE.match(text)
    if not m:
        return None
    name = m.group("name").replace("\x00", "").strip()
    kind = OPEN_TO_KIND[m.group("open")]
    return (mk_id(name + "_" + kind), name, kind, name == "?", m.group("mut") == "~",
            m.group("stream") == "*", generic_params(name))


def generic_params(name: str) -> tuple:
    """The top-level generic parameters of a glyph name: `Cache<K,V>` → ("K", "V"),
    `List<Map<K,V>>` → ("Map<K,V>",), `Api` → ()."""
    at = name.find("<")
    if at < 0 or not name.endswith(">"):
        return ()
    return tuple(p.strip() for p in _split_top(name[at + 1:-1], ",") if p.strip())


def _split_top(text: str, sep: str) -> list:
    """Split on `sep` outside any `<…>` / `(…)` / `[…]` / `{…}` nesting."""
    out, depth, cur = [], 0, ""
    for ch in text:
        if ch in "<([{":
            depth += 1
        elif ch in ">)]}":
            depth -= 1
        if ch == sep and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


# Modifiers that are always a declaration about the entity they follow: they go
# on the node even when they trail a flow (see "Modifiers" in the model notes).
_NODE_MODS = {"loc", "read", "write", "borrow", "owns", "grants", "requires", "^"}

# Modifier names that are no `@name` (signs, cardinality, a stream bound).
_SIGN_MODS = {"×", "!", "?", ".", "^"}

class Subject(NamedTuple):
    """The first endpoint of a flow statement — what a continuation line takes."""
    nodes: tuple              # node ids
    join: Optional[int] = None  # index into Graph.joins when the endpoint is joined
    paths: tuple = ()         # qualifying path per node (`[Bullet]/{Transform}`), or None
    line: int = 0             # the most recent flow line under this subject (Edge.cont)


# The token kinds that place a modifier of the statement (scan_mods' pairs): a
# `@name`, a bound, a count; a mark only when it is `!` (`?` marks a glyph).
def _is_modifier(t) -> bool:
    return t.pair is not None and (t.kind in ("mod", "bound", "card")
                                   or (t.kind == "mark" and t.text == "!"))


def _header_text(it: BlockOpen) -> str:
    """A control-block header less its keyword (`loop`, `parallel`, `branch`,
    `branch on`), from its tokens; a scope's header is all of it."""
    if it.kind == "scope":
        return it.head
    toks = it.toks[1:]                      # the keyword word
    if it.kind == "branch" and toks and toks[0].kind == "word" and toks[0].text == "on":
        toks = toks[1:]
    return it.code.raw[toks[0].col:].strip() if toks else ""


def _header_mods(raw: str, toks) -> list:
    """A control-block header's modifiers, in token order: each `@name` token
    read with the header text up to the next one — a header modifier's free
    argument runs to the next modifier (`loop @while |Q|.nonempty`). A string
    is string text: its `@` starts no modifier."""
    mods = [t for t in toks if t.kind == "mod"]
    ends = [t.col for t in mods[1:]] + [len(raw)]
    return [mod_pair(raw[t.col:end]) for t, end in zip(mods, ends)]


def _add_mod(mods: list, pair: tuple):
    if pair not in mods:
        mods.append(pair)


def extract_flows(toks: list, graph: Graph, layer: str, last_src=None,
                  dialect=None, first: Optional[list] = None, line_no: int = 0,
                  out: Optional[dict] = None, lead: int = 0):
    """Build one flow statement (its tokens, sigil.core.tokens; `lead` the column
    of its first character): add its nodes, edges, joins, modifiers and access
    declarations to `graph`. Returns the statement's Subject (its first endpoint;
    for a continuation line — one starting with an arrow — the inherited
    `last_src` Subject), or `last_src` unchanged when the line draws nothing.
    `last_src` may also be a bare Node (taken as a one-node subject).
    If `first` is a list, the line's first glyph node is appended to it. If `out`
    is a dict it receives "nodes" (ids placed), "edges" (the new Edge objects) and
    "head" (the id of the glyph the statement starts with, or None)."""
    if isinstance(last_src, Node):
        last_src = Subject((last_src.id,))
    tokens, mods, payload, payload_span, event_args, glued = _model_tokens(toks, layer)
    head = _head(tokens, lead)
    tokens, paths = _fold_paths(tokens)
    glyphs = [t[1] for t in tokens if t[0] == "glyph"]
    if not glyphs:
        return last_src

    # Every hole is its own node: `[?] -> [X]` and `[?] -> [Y]` are two unknowns.
    for tok in glyphs:
        if tok.is_hole:
            graph.hole_seq[0] += 1
            tok.id = f"{tok.id}{graph.hole_seq[0]}"

    if first is not None:
        first.append(glyphs[0])

    groups, links, link_cols = _group_endpoints(tokens, graph, last_src)
    placed = _place_groups(groups, graph, paths, event_args, line_no)
    new_edges, final, op_edges, link_edges = _fan_out(groups, links, line_no)
    if payload:
        for e in final:
            e.payload = f"{e.target_op} : {payload}" if e.target_op else payload
        new_edges += _return_emits(graph, final, payload, layer, line_no)
    graph.edges.extend(new_edges)
    if mods:
        _attach_mods(mods, tokens, graph, final=final, op_edges=op_edges,
                     link_edges=link_edges, link_cols=link_cols, glued=glued,
                     payload=payload, payload_span=payload_span, layer=layer,
                     line_no=line_no)

    if out is not None:
        out["nodes"] = list(dict.fromkeys(placed))
        out["edges"] = new_edges
        out["head"] = head.id if head is not None else None
    subject = groups[0]
    if subject.get("inherited"):
        for e in new_edges:
            e.cont = last_src.line
        if any(e.kind != "!>" for e in new_edges):
            return last_src._replace(line=line_no)
        return last_src
    return Subject(tuple(n.id for n in subject["nodes"]), subject["join_idx"],
                   tuple(subject.get("paths") or ()), line_no)


def _head(tokens: list, lead: int) -> Optional[Node]:
    """The glyph a statement starts with: its first token, when that is a glyph
    written at the statement's first column (`lead`); else None."""
    if tokens and tokens[0][0] == "glyph" and tokens[0][2] == lead:
        return tokens[0][1]
    return None


def _model_tokens(toks: list, layer: str) -> tuple:
    """A statement's tokens as the model reads them: (endpoints and operators as
    (kind, value, column) — a glyph's value its Node, a broken glyph a "void"
    endpoint —, [(column, (name, arg))] every modifier, the payload text or None,
    its (start, end) span or (-1, -1), {id(event node): its `(…)` argument},
    columns of `×N` glued to a glyph)."""
    tokens, mods, event_args, glued = [], [], {}, set()
    payload, payload_span = None, (-1, -1)
    for t in toks:
        if t.pair is not None:
            mods.append((t.col, t.pair))
            if t.flag == "glued":
                glued.add(t.col)
        kind = t.kind
        if kind == "payload":
            payload, payload_span = t.text or None, (t.col, t.end)
        elif kind == "glyph":
            node = _token_node(t, layer)
            tokens.append(("glyph", node, t.col) if node is not None else ("void", None, t.col))
        elif kind == "evarg":
            prev = tokens[-1] if tokens else None
            if prev is not None and prev[0] == "glyph" and prev[1].kind == "event" \
                    and t.text.endswith(")") and _close_paren(t.text) == len(t.text) - 1:
                event_args[id(prev[1])] = t.text[1:-1].strip() or None
        elif kind == "arrow":
            tokens.append(("arrow", t.text, t.col))
        elif kind in ("join", "slash") and t.flag != "dead":
            tokens.append((t.flag if t.flag in ("join", "slash") else kind, t.text, t.col))
        elif kind == "op" and t.flag != "dead":
            tokens.append(("op", t.text, t.col))
    return tokens, mods, payload, payload_span, event_args, glued


def _token_node(t, layer: str) -> Optional[Node]:
    """A fresh node for a glyph token (a dialect's, in this layer), or None for a
    broken glyph (a void endpoint: it places nothing, its links draw nothing)."""
    if t.node is not None:
        return dataclasses.replace(t.node, layer=layer, attrs=dict(t.node.attrs),
                                   mods=list(t.node.mods))
    if t.flag == "void":
        return None
    return _core_node(t.text.strip(), layer)     # a dialect's glyph carries its node


def _close_paren(text: str) -> int:
    depth = 0
    for i, ch in enumerate(text):
        depth += (ch == "(") - (ch == ")")
        if depth == 0:
            return i
    return -1


def _fold_paths(tokens: list) -> tuple:
    """Fold `a/b/c` into one reference to `c`, remembering its qualifying path.
    Returns (the tokens without slashes, {id(node token): (name, …, name)})."""
    if "slash" not in [t[0] for t in tokens]:
        return tokens, {}
    paths = {}                                  # id(node token) -> (name, …, name)
    folded = []
    for tok in tokens:
        kind, val = tok[0], tok[1]
        if (kind == "glyph" and len(folded) > 1 and folded[-1][0] == "slash"
                and folded[-2][0] == "glyph"):
            folded.pop()
            prev = folded.pop()[1]
            paths[id(val)] = paths.pop(id(prev), (prev.name,)) + (val.name,)
        folded.append(tok)
    tokens = [t for t in folded if t[0] != "slash"]
    return tokens, paths


def _group_endpoints(tokens: list, graph: Graph, last_src) -> tuple:
    """Group the line into endpoints separated by arrows. A `&` / `&?` / `/` join
    extends the current endpoint; two glyphs with no operator between them are
    separate endpoints with no edge (None). A continuation line (leading arrow) takes
    the inherited subject as its first endpoint. An op-call target is an endpoint
    standing for the endpoint before it (the caller runs the op).
    Returns (groups, links, link_cols)."""
    groups: list = []         # {"nodes": [Node], "join": kind, "join_idx", "op"}
    links: list = []          # links[k] joins groups[k] -> groups[k+1]
    link_cols: list = []      # the column of links[k]'s arrow (None: no arrow)
    cur = None
    pending = None            # the arrow awaiting a destination
    pending_col = None
    joining = None
    if tokens[0][0] == "arrow" and last_src is not None and last_src.nodes:
        cur = {"nodes": [graph.nodes[n] for n in last_src.nodes if n in graph.nodes],
               "join": None, "join_idx": last_src.join, "op": None, "inherited": True,
               "paths": list(last_src.paths) if len(last_src.paths) == len(last_src.nodes)
               else None}
        if not cur["nodes"]:
            cur = None
    for kind, tok, _c in tokens:
        if kind == "arrow":
            if cur is not None:
                groups.append(cur)
                cur = None
                pending, pending_col = tok, _c
            joining = None
        elif kind == "join":
            joining = tok
        elif kind == "op":
            if cur is not None:
                groups.append(cur)
                pending = None
            if groups:
                links.append(pending)
                link_cols.append(pending_col if pending else None)
                prev = groups[-1]
                cur = {"nodes": prev["nodes"], "join": None, "join_idx": prev["join_idx"],
                       "op": tok, "col": _c}
            pending = None
            joining = None
        elif kind in ("glyph", "void"):     # a void endpoint (a broken glyph) has no node
            if cur is not None and joining and not cur.get("op"):
                if tok is not None:
                    cur["nodes"].append(tok)
                cur["join"] = cur["join"] or joining
            else:
                if cur is not None:        # adjacent glyphs, no operator
                    groups.append(cur)
                    pending = None
                if groups:
                    links.append(pending)
                    link_cols.append(pending_col if pending else None)
                cur = {"nodes": [tok] if tok is not None else [], "join": None,
                       "join_idx": None, "op": None}
                pending = None
            joining = None
    if cur is not None:
        groups.append(cur)
    return groups, links, link_cols


def _place_groups(groups: list, graph: Graph, paths: dict, event_args: dict,
                  line_no: int) -> list:
    """Put each written endpoint's nodes in the graph (the graph's node of an id
    replaces the written token) and record a multi-node endpoint as a Join.
    Returns the ids placed, in order."""
    placed = []
    for group in groups:
        if group.get("op") or group.get("inherited"):
            continue
        # Qualifying paths belong to the written token, before it is swapped for
        # the graph's node of that id.
        group["paths"] = [paths.get(id(n)) for n in group["nodes"]]
        group["args"] = [event_args.get(id(n)) for n in group["nodes"]]
        for k, n in enumerate(group["nodes"]):
            if n.id not in graph.nodes:
                graph.nodes[n.id] = n
            group["nodes"][k] = graph.nodes[n.id]
            placed.append(n.id)
        if len(group["nodes"]) > 1 and group["join_idx"] is None:
            graph.joins.append(Join(group["join"] or "&", [n.id for n in group["nodes"]],
                                    line_no))
            group["join_idx"] = len(graph.joins) - 1
    return placed


def _fan_out(groups: list, links: list, line_no: int) -> tuple:
    """Fan every arrow out across both endpoints (`[A] & [B] -> [C] & [D]` is 4 edges).
    Returns (every new edge, the final link's edges, {op-call target column: its
    self-edges}, {link index: its edges})."""
    new_edges = []
    final = []
    op_edges = {}             # an op-call target's column → the self-edges it made
    link_edges = {}           # link index → the edges it made
    for k, arrow in enumerate(links):
        if arrow is None:
            continue
        src, dst = groups[k], groups[k + 1]
        made = []
        spaths = src.get("paths") or [None] * len(src["nodes"])
        if dst.get("op"):
            for s, sp in zip(src["nodes"], spaths):
                made.append(Edge(src=s.id, dst=s.id, kind=arrow, payload=dst["op"],
                                 src_path=sp, dst_path=sp,
                                 src_join=src["join_idx"], target_op=dst["op"],
                                 line=line_no))
            op_edges[dst["col"]] = made
        else:
            dpaths = dst.get("paths") or [None] * len(dst["nodes"])
            dargs = dst.get("args") or [None] * len(dst["nodes"])
            for s, sp in zip(src["nodes"], spaths):
                for d, dp, da in zip(dst["nodes"], dpaths, dargs):
                    made.append(Edge(src=s.id, dst=d.id, kind=arrow, payload=da,
                                     src_path=sp, dst_path=dp,
                                     src_join=src["join_idx"], dst_join=dst["join_idx"],
                                     line=line_no))
        link_edges[k] = made
        new_edges += made
        if k == len(groups) - 2:
            final = made
    return new_edges, final, op_edges, link_edges


def _attach_mods(mods: list, tokens: list, graph: Graph, *, final: list, op_edges: dict,
                 link_edges: dict, link_cols: list, glued: set, payload: Optional[str],
                 payload_span: tuple, layer: str, line_no: int):
    """Modifiers: between a glyph and the next arrow → that glyph's node; between an
    op-call target and the next arrow → that self-call's edges; trailing the statement
    → the final link's edges (or the last glyph without one); entity declarations
    (_NODE_MODS) always on the node."""
    glyph_at = [(c, graph.nodes[t.id]) for kind, t, c in tokens
                if kind == "glyph" and t.id in graph.nodes]
    arrow_cols = [c for kind, _t, c in tokens if kind == "arrow"]
    for col, pair in sorted(mods, key=lambda m: m[0]):
        before = [(c, n) for c, n in glyph_at if c < col]
        after = [n for c, n in glyph_at if c > col]
        owner = before[-1][1] if before else (after[0] if after else None)
        if after and before and any(before[-1][0] < a < col for a in arrow_cols):
            owner = after[0]                    # between an arrow and its target
        trailing = not any(a > col for a in arrow_cols)
        op_col = _op_before(tokens, col)
        into = [e for e in final if owner is not None and e.dst == owner.id]
        if payload_span[0] <= col < payload_span[1] and final:
            for e in final:                     # a bound on the payload's stream
                _add_mod(e.mods, pair)
        elif op_col in op_edges and pair[0] not in _NODE_MODS:
            for e in op_edges[op_col]:          # `-> plan() @deadline(2s) => {P}`
                _add_mod(e.mods, pair)
        elif (pair[0] == "×" and trailing and into
              and (col in glued or payload is None)):
            for e in into:                      # `-> [App]×N`: cardinality, no retry
                e.card = pair[1]
        elif pair[0] in _NODE_MODS or not trailing or not final:
            if owner is not None:
                _add_mod(owner.mods, pair)
                _access(graph, owner, pair, line_no, layer)
                if pair[0] not in _NODE_MODS and pair[0] not in _SIGN_MODS:
                    for e in _leaving(owner, col, arrow_cols, link_cols, link_edges):
                        _add_mod(e.src_mods, pair)
        else:
            for e in final:
                _add_mod(e.mods, pair)


def _op_before(tokens: list, col: int) -> Optional[int]:
    """The column of the op-call target a modifier at `col` follows (no glyph or
    arrow between them), or None."""
    before = [(c, kind) for kind, _t, c in tokens
              if c < col and kind in ("glyph", "op", "arrow")]
    return before[-1][0] if before and before[-1][1] == "op" else None


def _leaving(owner: Node, col: int, arrow_cols: list, link_cols: list,
             link_edges: dict) -> list:
    """The edges from `owner` drawn by the arrow next after column `col`: the
    calls a modifier written between a glyph and its arrow governs."""
    nxt = min((a for a in arrow_cols if a > col), default=None)
    if nxt is None or nxt not in link_cols:
        return []
    return [e for e in link_edges.get(link_cols.index(nxt), []) if e.src == owner.id]


def _return_emits(graph: Graph, final: list, payload: str, layer: str,
                  line_no: int) -> list:
    """`[J] -> [S] : score() => <rated>`: a call that returns an event makes its
    callee emit it — one implied `=>` edge per callee (none for an op-call
    target, whose `=>` edges are drawn)."""
    if "=>" not in payload or not final or final[0].target_op:
        return []
    ret = payload.rsplit("=>", 1)[1].strip()
    ev = parse_glyph(ret, layer) if GLYPH_RE.fullmatch(ret) else None
    if ev is None or ev.kind != "event" or ev.is_hole:
        return []
    graph.nodes.setdefault(ev.id, ev)
    return [Edge(src=callee, dst=ev.id, kind="=>", line=line_no, implied="return")
            for callee in dict.fromkeys(e.dst for e in final)]


def _access(graph: Graph, owner: Node, pair: tuple, line_no: int, layer: str):
    """Record a permission-graph declaration: `|S| @read(A, B)` / `@write(…)` on
    the store `owner`; `[P] @borrow(read)? |S|` lent to the principal `owner`."""
    name, arg = pair
    if name in ("read", "write") and arg:
        for who in _split_top(arg, ","):
            if who.strip():
                graph.access.append(Access(None, owner.id, name, line_no, who.strip()))
    elif name == "borrow" and arg:
        m = re.match(r"\(\s*(\w+)\s*\)\s*(.*)$", arg)
        narrow, rest = (m.group(1), m.group(2)) if m else (None, arg)
        gm = GLYPH_RE.search(rest)
        # The borrowed store is resolved to its node once the document is read (a
        # modifier's argument is not itself a node — see _resolve_access).
        graph.access.append(Access(owner.id, None, "borrow", line_no, owner.name, narrow,
                                   gm.group(0) if gm else rest.strip()))


PSEUDO_STATES = {"+": "start", "$": "end", "_": "any"}

# Core glyph kinds (lex.GLYPH_BRACKETS); any other kind is a dialect's.
_CORE_KINDS = set(GLYPH_BRACKETS)


def _layer_num(layer) -> int:
    m = re.match(r"L(\d+)$", layer or "")
    return int(m.group(1)) if m else 1


def _find_node(g: Graph, name: str, kind) -> Optional[str]:
    """The node of that name AND kind (`[Order] := …` is not `{Order}`); a
    dialect-kind node of the name also qualifies (its tokenizer may own the glyph).
    A bare `name :=` (kind None) takes the first node of the name."""
    target = mk_id(name + "_" + kind) if kind is not None else None
    if target in g.nodes:
        return target
    return next((nid for nid, n in g.nodes.items()
                 if n.name == name and (kind is None or n.kind == kind
                                        or n.kind not in _CORE_KINDS)), None)


def _resolve_access(g: Graph, top: Graph):
    """Fill the node ids of Access entries once the document is read: a
    principal by name (in `g`, else the top-level graph `top`); a borrowed store
    when the glyph is a node there."""
    for a in g.access:
        for where in (g, top):
            if a.principal is None and a.name:
                a.principal = _resolve_principal(where, a.name)
            if a.store is None and a.store_name:
                n = parse_glyph(a.store_name)
                if n is not None and n.id in where.nodes:
                    a.store = n.id


def _place_borrowed(top: Graph):
    """A borrowed store named by glyph that is no node where the borrow is
    written, nor at the top level (`[Helper] @borrow(read) |Feed|`, |Feed| in no
    flow, or a node only in a sibling expansion) becomes a node of the graph the
    borrow is written in, so its access edge has an end to draw to — as a flow
    naming it there would."""
    for g, _o, _l in walk_depth(top):
        for a in g.access:
            if a.mode != "borrow" or a.store is not None or not a.store_name:
                continue
            who = g.nodes.get(a.principal)  # the store sits in its borrower's layer
            n = parse_glyph(a.store_name, who.layer if who else "L1")
            if n is None or n.is_hole:
                continue
            g.nodes.setdefault(n.id, n)
            a.store = n.id


def _mark_roles(top: Graph):
    """Mark each generic glyph whose base name some access list names as a
    principal (`[Worker<N>]` with `@read(Worker)` anywhere in the document) a
    role (Node.is_role) — also when an exact `[Worker]` takes the access edge."""
    graphs = [g for g, _o, _l in walk_depth(top)]
    names = {a.name for g in graphs for a in g.access if a.name and a.mode != "borrow"}
    for g in graphs:
        for n in g.nodes.values():
            n.is_role = bool(n.params) and n.base_name in names


def _resolve_principal(g: Graph, name: str) -> Optional[str]:
    """A principal name → node id: an exact name first, then a generic role's
    base name (`Worker` → `[Worker<N>]`)."""
    for test in (lambda n: n.name == name, lambda n: n.base_name == name):
        hit = next((nid for nid, n in g.nodes.items() if not n.is_hole and test(n)), None)
        if hit:
            return hit
    return None


class _Frame:
    """An open control block while its body is built (`idx` into Graph.blocks;
    None for a dialect keyword's block, which the model does not draw)."""
    def __init__(self, idx: Optional[int]):
        self.idx = idx
        self.arm = None           # branch: index of the arm being read
        self.subjects = []        # subjects of the body's own statements


class _Builder:
    """Builds one document level — the whole text, or a definition's body — from
    the walk's items (sigil.core.statements). `run()` is a generator: it yields
    each body Doc it needs built and is sent that body's Graph back, so nesting
    grows a stack (_build), not the Python call stack."""

    def __init__(self, walk: Walk, doc: Doc, dialect, hole_seq: Optional[list] = None):
        self.walk, self.doc, self.dialect = walk, doc, dialect
        self.graph = Graph()
        if hole_seq is not None:
            self.graph.hole_seq = hole_seq
        self.top = hole_seq is None
        self.layer = "L1"
        # The Subject a continuation line takes: the first endpoint of the last
        # statement that was not itself a continuation (or a closed block's subject).
        self.last_src = None
        # `X := { … }` / `X := expr` definitions and `state` machines, resolved once
        # the whole document is read so one written BEFORE its node's first use
        # still attaches: (name, kind, sub_graph|None, layer, mods, line, the id
        # notes and heads were given, a dialect glyph's node or None) and (owner
        # Node, state graph, `} @mods` pairs).
        self.pending_expansions = []
        self.pending_states = []
        self.state_owner = None
        # Open control blocks, innermost last; and the block whose subject
        # continuation lines after it take.
        self.frames: list = []
        self.after_block = None
        # Composition tree state: open branches as (column, tree index), and the last
        # plain glyph line a branch could hang under: [column, node id, tree index|None,
        # line].
        self.tree_stack: list = []
        self.tree_root: Optional[list] = None
        # Notes: the node the current line is "about", and own-line comments waiting
        # for the statement below.
        self.anchor = None
        self.above: list = []
        # No statement, declaration or section read yet: comments detached
        # above here are the document's header (top level only).
        self.seen = False

    def ln(self, k: int) -> int:
        """The source line of line index k."""
        return k + 1

    def comment(self, k: int) -> Optional[tuple]:
        """Line k's comment (text, own_line): none on a line read from a piece of a
        source line (a definition's body that starts after its `{`)."""
        if k in self.doc.texts:
            return None
        return (self.walk.comments if self.doc.top else self.walk.inner).get(k)

    def frame(self) -> Optional[_Frame]:
        """The innermost open control block the model draws."""
        if not self.frames:
            return None
        return next((f for f in reversed(self.frames) if f.idx is not None), None)

    # -- driver ---------------------------------------------------------------

    def run(self):
        for it in self.doc.items:
            if isinstance(it, Flow):            # the most common item first
                self._flow_line(it.line, it.statement, it.arm)
            elif isinstance(it, NoteItem):
                self.above.append((it.text, self.ln(it.line)))
            elif isinstance(it, Blank):          # a blank line detaches waiting comments
                self._detach()
            elif isinstance(it, Declaration):
                self.last_src = None
                self.seen = True
                if it.name is not None:
                    self.graph.declarations.append(
                        Declared(it.name, it.body, self.ln(it.line)))
            elif isinstance(it, SectionHead):
                self._section(it)
            elif isinstance(it, Definition):
                head = self._definition(it)
                sub = (yield it.body) if it.closed else None
                self._defined(it, head, sub)
            elif isinstance(it, StateHead):
                self._state_head(it)
            elif isinstance(it, StateEnd):
                self._state_end(it)
            elif isinstance(it, BlockOpen):
                self._block_open(it)
            elif isinstance(it, BlockClose):
                self._block_close(it.line)
            elif isinstance(it, BlockMods):
                self._block_mods(it)
        return self._end(self.doc.end)

    def _end(self, n: int) -> Graph:
        """The document (n lines) is read: drop what was left open, then finish."""
        if self.doc.unclosed is not None:   # a body, `state` or declaration never closed
            for k in range(self.doc.unclosed, n):
                self._drop(k, "unclosed")
        while self.frames:                  # a block left open at the end of the text
            if self.frames[-1].idx is None:
                self.frames.pop()
            else:
                self._close_block(n - 1)
        self._detach()
        return self.finish()

    def finish(self) -> Graph:
        graph = self.graph
        by_level: dict = {}               # level → expansion graphs written at it
        order = sorted(range(len(self.pending_expansions)),
                       key=lambda i: _layer_num(self.pending_expansions[i][3]))
        for i in order:
            name, kind, sub_graph, layer, mods, line, provisional, glyph = \
                self.pending_expansions[i]
            level = _layer_num(layer)
            home, target_id = graph, None
            # Zoom: an expansion written in `--- Lk ---` (k >= 3) details a node of
            # the level k-1 expansions — `--- L3: [Handler] ---` nests under the
            # `[Handler]` inside `[Core] := { … }` (L2), not a top-level namesake.
            if level >= 3:
                for cand in by_level.get(level - 1, []):
                    for g2, _o, _l in walk_depth(cand):
                        tid = _find_node(g2, name, kind)
                        if tid and tid not in g2.expansions:
                            home, target_id = g2, tid
                            break
                    if target_id:
                        break
            if target_id is None:
                target_id = _find_node(graph, name, kind)
            if target_id is None and glyph is not None:
                # A dialect glyph defined but never in a flow: its own node.
                target_id = glyph.id
                graph.nodes[target_id] = glyph
            elif target_id is None:
                # Defined but never referenced in a flow — still a node of the design.
                # A bare-word definition (`walk := …`) is an `alias` node.
                target_id = mk_id(name + "_" + (kind or "alias"))
                graph.nodes[target_id] = Node(id=target_id, name=name,
                                              kind=kind or "alias", layer=layer)
            node = home.nodes[target_id]
            for pair in mods:
                _add_mod(node.mods, pair)
            if provisional != target_id:     # notes and heads recorded before resolution
                for note in self.graph.notes:
                    if note.node == provisional and note.line == line:
                        note.node = target_id
                self.graph.heads = [(ln, target_id if (ln, nid) == (line, provisional) else nid)
                                    for ln, nid in self.graph.heads]
            if sub_graph is not None:
                home.expansions[target_id] = sub_graph
                by_level.setdefault(level, []).append(sub_graph)

        for owner, machine in self.pending_states:
            node = graph.nodes.setdefault(owner.id, owner)
            for pair in machine.mods:
                _add_mod(node.mods, pair)
            home = graph.expansions.get(owner.id)
            if home is None:
                graph.expansions[owner.id] = machine
            else:
                # The owner also has a `:=` expansion: the machine hangs inside it.
                mid = owner.id + "_machine"
                home.nodes.setdefault(mid, Node(id=mid, name="states", kind="state"))
                home.expansions[mid] = machine

        _resolve_access(graph, graph)
        for b in graph.blocks:              # `[X] @owns |R| {`: R when it is a node
            b.refs += [r for r in getattr(b, "_owned", ()) if r in graph.nodes
                       and r not in b.refs]
        if self.top:                        # top level: wire events to transitions
            for g2, _o, _l in walk_depth(graph):  # access lists inside expansions may
                _resolve_access(g2, graph)   # name a top-level principal / store
            _place_borrowed(graph)
            _mark_roles(graph)
            graph.triggers, graph.narrowed = find_triggers(graph)
            _expand_alias_refs(graph)
        graph.dropped.sort(key=lambda d: d.line)
        return graph

    # -- helpers --------------------------------------------------------------

    def _detach(self):
        """The waiting comments precede no statement: before the document's first
        one (top level) they are its header — a document note — else dropped."""
        if self.above and self.top and not self.seen:
            self.graph.notes.append(Note(None, " ".join(t for t, _ln in self.above),
                                         self.above[0][1], "block"))
        self.above.clear()

    def attach_block(self, bi: int, k: int, body: str):
        """A glyph-less block header (graph.blocks[bi]) read at line index k: the
        comments above are about the block, and so is a trailing one when no
        body statement shares the header's line (that statement takes it)."""
        self.seen = True
        if self.above:
            self.graph.notes.append(Note(None, " ".join(t for t, _ln in self.above),
                                         self.above[0][1], "block", block=bi))
        trailing = self.comment(k)
        if trailing and not trailing[1] and not body.strip():
            self.graph.notes.append(Note(None, trailing[0], self.ln(k), "inline", block=bi))
        self.above.clear()

    def attach(self, node_id, k: int, edges: tuple = ()):
        self.seen = True
        if node_id and self.above:
            self.graph.notes.append(Note(node_id, " ".join(t for t, _ln in self.above),
                                         self.above[0][1], "block"))
        trailing = self.comment(k)
        if node_id and trailing and not trailing[1]:
            self.graph.notes.append(Note(node_id, trailing[0], self.ln(k), "inline", edges))
        self.above.clear()

    def _drop(self, k: int, reason: str):
        """Record line index k as read and discarded (a blank or comment-only line
        is not recorded)."""
        lines = self.walk.lines
        text = self.doc.texts.get(k, lines[k] if 0 <= k < len(lines) else "").strip()
        if strip_comment(text).strip():
            self.graph.dropped.append(Dropped(self.ln(k), reason, text))

    def _adopt(self, sub: Graph) -> Graph:
        """A body's graph, its dropped lines also listed as this graph's."""
        self.graph.dropped.extend(sub.dropped)
        return sub

    def add_entry(self, node_id, parent, line: int, rel=None, spawn=False, cond=None,
                  weight=None):
        depth = self.graph.tree[parent].depth + 1 if parent is not None else 0
        self.graph.tree.append(TreeEntry(node_id, parent, rel, spawn, cond, depth, weight, line))
        return len(self.graph.tree) - 1

    # -- sections, definitions, machines ---------------------------------------

    def _section(self, it: SectionHead):
        self._detach()
        self.seen = True
        if it.level:
            self.layer = it.level
        if self.layer not in self.graph.layers:
            self.graph.layers.append(self.layer)
        self.graph.sections.append(Section(it.level, it.title, self.ln(it.line)))
        self.last_src = None
        self.after_block = None

    def _definition(self, it: Definition) -> tuple:
        """Definitions — `name := expr`, `[name] := expr`, `X := { … }`, a dialect
        glyph `[[x]] := { … }` — are not flows: each names a node (a bare-word name
        is an `alias` node) whose expansion is its definition — a `{ … }` body, or a
        one-line flow. Returns (kind, the id notes and heads are given, a dialect
        glyph's node or None)."""
        glyph = parse_glyph(it.glyph, self.layer, self.dialect) if it.glyph else None
        kind = glyph.kind if glyph is not None else it.kind
        nid = glyph.id if glyph is not None else mk_id(it.name + "_" + (kind or "alias"))
        self.attach(nid, it.line)
        self.graph.heads.append((self.ln(it.line), nid))
        self.last_src = None
        self.after_block = None
        return kind, nid, glyph

    def _defined(self, it: Definition, head: tuple, sub: Optional[Graph]):
        """The definition's body is built (`sub`; None when it never closed). A
        one-line definition is an expansion when it draws a flow (`walk := [Node]
        -> walk(.children)`); a prose or modifier-only one (`[Cache] := {Summary}
        store`, `retry := @after(…)`) only names the node — its modifiers become
        the node's."""
        if sub is None:
            return
        kind, nid, glyph = head
        sub = self._adopt(sub)
        if it.form == "inline":
            flow = bool(sub.edges)
            self.pending_expansions.append((it.name, kind, sub if flow else None, self.layer,
                                            [] if flow else scan_mods(it.rhs),
                                            self.ln(it.line), nid, glyph))
        else:
            self.pending_expansions.append((it.name, kind, sub, self.layer, scan_mods(it.tail),
                                            self.ln(it.line), nid, glyph))

    def _state_head(self, it: StateHead):
        """`state {X} { … }` — a state machine of entity X, built into its own graph
        that hangs off the {X} node (like an expansion)."""
        owner = parse_glyph(it.owner, self.layer, self.dialect) if it.owner else None
        self.state_owner = owner
        self.attach(owner.id if owner else None, it.line)

    def _state_end(self, it: StateEnd):
        owner = self.state_owner
        if owner is None:                   # no owner glyph: the block is consumed
            for k in range(it.head, it.line + 1):
                self._drop(k, "no-owner")
            return
        if it.line == it.head and not it.lines:
            return                          # `state {X} { }`: nothing
        machine = self._adopt(parse_state_block(it.lines, owner.name))
        # Modifiers after the `}` (`} @inv ordered(id)`): the machine's, and the owner's.
        machine.mods = scan_mods(it.tail)
        self.pending_states.append((owner, machine))

    # -- control blocks -----------------------------------------------------------

    def _block_open(self, it: BlockOpen):
        """A control-block header — `loop …`, `parallel …`, `branch on X`, a scoped
        `name {`, an `[X] @owns |R| {` — opens a Block whose body statements are
        ordinary flows (recorded as the block's members / edges / arms). A dialect
        keyword's block is no Block: its statements are read as if it were not
        there."""
        if it.kind == "keyword":
            self.frames.append(_Frame(None))
            return
        k = it.line
        refs, mods, owned = [], [], []
        if it.kind == "owns":
            # The header is itself a statement: the owner node (+ its @owns modifier).
            out = {}
            self._flow_line(k, it.header, None, out=out, in_header=True)
            header = it.head
            mods = [t.pair for t in it.header.toks if _is_modifier(t)]
            refs = list(out.get("nodes", []))
            owned = [parse_glyph(gm.group(0), self.layer).id
                     for p in mods if p[0] == "owns" and p[1]
                     for gm in GLYPH_RE.finditer(p[1])]
        else:
            header = _header_text(it)
            mods = _header_mods(it.code.raw, it.toks)
            # The glyphs the header names (not those inside a modifier's argument).
            for t in it.toks:
                n = _token_node(t, self.layer) if t.kind == "glyph" else None
                if n is None:
                    continue
                if n.is_hole:
                    self.graph.hole_seq[0] += 1
                    n.id = f"{n.id}{self.graph.hole_seq[0]}"
                self.graph.nodes.setdefault(n.id, n)
                refs.append(n.id)
        fr = self.frame()
        block = Block(it.kind, header, mods, parent=fr.idx if fr else None,
                      lines=(self.ln(k), self.ln(k)), refs=list(dict.fromkeys(refs)))
        if it.kind == "owns":
            block._owned = owned            # resolved in finish()
        self.graph.blocks.append(block)
        self.frames.append(_Frame(len(self.graph.blocks) - 1))
        self.last_src = None
        self.after_block = None
        if it.kind != "owns":               # the owns header attached to its owner
            self.attach_block(len(self.graph.blocks) - 1, k, it.rest)

    def _block_close(self, k: int):
        if self.frames and self.frames[-1].idx is None:
            self.frames.pop()
            return
        self._close_block(k)

    def _close_block(self, k: int):
        fr = self.frames.pop()
        b = self.graph.blocks[fr.idx]
        b.lines = (b.lines[0], self.ln(k))
        if b.kind == "owns":
            b.subject = b.refs[:1]
        elif b.kind == "branch":
            b.subject = list(b.refs)
        else:
            b.subject = list(dict.fromkeys(fr.subjects))
        if self.frames:                     # a nested block is a statement of its parent
            self.frames[-1].subjects.extend(b.subject)
        self.last_src = Subject(tuple(b.subject)) if b.subject else None
        self.after_block = fr.idx

    def _block_mods(self, it: BlockMods):
        """`} @inv …` after a block's `}`: the block's own modifiers."""
        if self.after_block is None:
            return
        b = self.graph.blocks[self.after_block]
        for p in scan_mods(it.text.strip()):
            _add_mod(b.modifiers, p)

    # -- flows ----------------------------------------------------------------

    def _flow_line(self, k: int, st, arm: Optional[str], out: Optional[dict] = None,
                   in_header: bool = False):
        """Build the flow statement `st` (read at line index k), record it in the
        open blocks, and attach the waiting comments to the node it is about.
        `arm`: the label of the branch arm it is the body of."""
        self.anchor = None
        fr = self.frame()
        block = self.graph.blocks[fr.idx] if fr else None
        is_arm = False
        if arm is not None and block is not None and block.kind == "branch" and not in_header:
            # A branch arm: its flow starts afresh (it is not a continuation).
            block.arms.append((arm, []))
            block.arm_nodes.append((arm, []))
            fr.arm = len(block.arms) - 1
            is_arm = True
            self.last_src = None
            if st is None:
                self.attach(None, k)
                return
        continuation = st.cont
        col = st.col - st.shift
        acc = {"nodes": [], "edges": []}
        subject = self._flow(st, col, self.last_src, k, acc, heads=not is_arm)
        if not continuation:
            self.last_src = subject
        elif (isinstance(subject, Subject) and isinstance(self.last_src, Subject)
              and subject.nodes == self.last_src.nodes):
            self.last_src = subject             # the same subject, its latest flow line
        edges = acc["edges"]
        # The edge keys the open blocks record (none to record outside them).
        keys = (list(dict.fromkeys([e.key for e in edges]))
                if self.frames or self.after_block is not None else [])
        for f in self.frames:
            if f.idx is None:
                continue
            b = self.graph.blocks[f.idx]
            b.members.extend(n for n in acc["nodes"] if n not in b.members)
            b.edges.extend(e for e in keys if e not in b.edges)
        if block is not None and block.kind == "branch" and fr.arm is not None:
            block.arms[fr.arm][1].extend(e for e in keys if e not in block.arms[fr.arm][1])
            nodes = block.arm_nodes[fr.arm][1]
            nodes.extend(n for n in acc["nodes"] if n not in nodes)
        if continuation:
            if self.after_block is not None:
                after = self.graph.blocks[self.after_block].after
                after.extend(e for e in keys if e not in after)
        else:
            self.after_block = None
            if fr is not None and subject is not None and acc["nodes"]:
                fr.subjects.extend(subject.nodes)
        if out is not None:
            out["nodes"], out["edges"] = acc["nodes"], edges
        drawn = tuple(dict.fromkeys([e.key for e in edges if e.src != e.dst]))
        self.attach(self.anchor, k, drawn)

    def _flow(self, st, col: int, last, k: int, acc: dict, heads: bool = True):
        """One flow statement; a composition branch (`\\-<rel>`) becomes a tree
        entry. `heads`: whether the glyph it starts with heads a statement
        (Graph.heads); a branch arm's body (`x => [A]`) heads none, its line
        starts with the label."""
        graph = self.graph
        text = st.code.text
        line_no = self.ln(k)

        def first_col(at: int) -> int:
            return at + len(text[at:]) - len(text[at:].lstrip())

        def flows(toks, lead, last, cap):
            out = {}
            res = extract_flows(toks, graph, self.layer, last, self.dialect, first=cap,
                                line_no=line_no, out=out, lead=lead)
            nodes = acc["nodes"]
            if nodes:
                nodes.extend(n for n in out.get("nodes", ()) if n not in nodes)
            else:                               # out["nodes"] holds each id once
                nodes.extend(out.get("nodes", ()))
            acc["edges"].extend(out.get("edges", ()))
            if heads and out.get("head"):
                graph.heads.append((line_no, out["head"]))
            return res

        lead = first_col(0)
        if st.branch < 0:
            cap: list = []
            last = flows(st.toks, lead, last, cap)
            if cap:
                self.tree_stack = [t for t in self.tree_stack if t[0] < col]
                self.tree_root = [col, cap[0].id, None, self.ln(k)]
                self.anchor = cap[0].id
            return last
        btok = st.toks[st.branch]
        m = BRANCH_RE.match(btok.text)
        bcol = col + btok.col - lead
        if btok.col > lead:                  # inline: `[parent] \\-& [child]`
            cap = []
            last = flows(st.toks[:st.branch], lead, last, cap)
            self.tree_stack = [t for t in self.tree_stack if t[0] < col]
            if cap:
                self.tree_root = [col, cap[0].id, None, self.ln(k)]
        stack = self.tree_stack
        while stack and stack[-1][0] >= bcol:
            stack.pop()
        parent = stack[-1][1] if stack else None
        root = self.tree_root
        if parent is None and root is not None and root[0] < bcol:
            if root[2] is None:
                root[2] = self.add_entry(root[1], None, root[3])
            parent = root[2]
            stack.append((root[0], parent))
        cap = []
        last = flows(st.toks[st.branch + 1:], first_col(btok.col + len(btok.text)), last, cap)
        if cap:
            spawn = bool(m.group("spawn") or m.group("bare_spawn"))
            rel = m.group("rel") or ("*" if m.group("bare_spawn") else None)
            weight = int(m.group("weight")) if m.group("weight") else None
            idx = self.add_entry(cap[0].id, parent, self.ln(k), rel, spawn, m.group("cond"),
                                 weight)
            stack.append((bcol, idx))
            self.anchor = cap[0].id
            if rel == "!" and parent is not None:
                acc["edges"].extend(self._alert(parent, cap[0], m.group("cond"), k))
        return last

    def _alert(self, parent: int, child: Node, cond: Optional[str], k: int) -> list:
        """`|R|` `\\-{lagging}-! <LagAlarm>`: the parent emits the alarm event while
        the condition holds — an implied `?>` edge (labelled with the condition)."""
        if child.kind != "event" or child.is_hole:
            return []
        e = Edge(src=self.graph.tree[parent].node, dst=child.id, kind="?>", label=cond,
                 line=self.ln(k), implied="alert")
        self.graph.edges.append(e)
        return [e]


def _build(walk: Walk, dialect) -> Graph:
    """Build the model of a walked document: one _Builder per document level, a
    body's built when its parent's run() asks for it."""
    builders = [_Builder(walk, walk.doc, dialect)]
    runs = [builders[0].run()]
    value = None
    while True:
        try:
            doc = runs[-1].send(value)
        except StopIteration as stop:
            runs.pop()
            builders.pop()
            if not runs:
                return stop.value
            value = stop.value
            continue
        value = None
        child = _Builder(walk, doc, dialect, builders[-1].graph.hole_seq)
        builders.append(child)
        runs.append(child.run())


def parse_document(text: str, dialect=None, walk: Optional[Walk] = None) -> Graph:
    """Parse a Sigil document into a Graph structure (see "THE MODEL" in
    sigil.core.graph). `dialect` is a loaded dialect (dialects.load) or None for
    core Sigil. `walk`: the document's reading when the caller already has it
    (sigil.core.statements.read_document — lint reads a document once)."""
    if walk is None:
        walk = read_document(text, dialect)
    graph = _build(walk, dialect)
    if walk.bodies:
        _attach_block_strings(graph, {k + 1: body for k, body in walk.bodies.items()})
    return graph


def _attach_block_strings(graph: Graph, bodies: dict):
    """Give each edge whose payload holds a block-string its text: bodies is
    {source line: text}, the line its block opens on (the flow's own line)."""
    for g, _owner, _level in walk_depth(graph):
        for e in g.edges:
            if e.payload and BLOCK_SENTINEL in e.payload and e.line in bodies:
                e.block_string = bodies[e.line]


def _expand_alias_refs(graph: Graph):
    """Each ("alias", name) edge modifier (`: charge ×3 Retry`) becomes the
    modifiers of the modifier-only alias of that name (`Retry := @after(…)`), in
    place; a name no such alias defines stays an ("alias", name) modifier."""
    defs = {}
    for g, _o, _l in walk_depth(graph):
        for nid, n in g.nodes.items():
            if n.kind == "alias" and nid not in g.expansions and n.mods:
                defs.setdefault(n.name, n.mods)
    for g, _o, _l in walk_depth(graph):
        for e in g.edges:
            if any(name == ALIAS_REF for name, _a in e.mods):
                expanded = []
                for pair in e.mods:
                    for p in (defs.get(pair[1], [pair]) if pair[0] == ALIAS_REF else [pair]):
                        _add_mod(expanded, p)
                e.mods = expanded


def find_triggers(graph: Graph) -> tuple:
    """An event glyph whose name matches a transition's trigger (`-<Paid>->`,
    case-insensitive) IS that trigger: one Trigger per (event, transition).
    Returns (live, narrowed): the pairs that drive their machine, and the pairs
    narrowing took away (see below) — Graph.triggers and Graph.narrowed."""
    events = {}
    for g, _o, _l in walk_depth(graph):
        for n in g.nodes.values():
            if n.kind == "event" and not n.is_hole:
                events.setdefault(n.name.lower(), n.id)
                events.setdefault(n.base_name.lower(), n.id)   # `<Msg<T>>` drives `-<Msg>->`
    # Narrowing: an event with explicit flows into state-machine owners drives only
    # those owners' machines; without such flows it drives every matching machine.
    owners = {owner for g, owner, _l in walk_depth(graph) if g.role == "state"}
    aimed = {}
    for g, _o, _l in walk_depth(graph):
        for e in g.edges:
            if e.dst in owners:
                aimed.setdefault(e.src, set()).add(e.dst)
    live, narrowed = [], []
    for g, owner, level in walk_depth(graph):
        if g.role != "state":
            continue
        for e in g.edges:
            key = (e.label or "")[1:-1].lower()
            if key in events:
                ev = events[key]
                kept = ev not in aimed or owner in aimed[ev]
                (live if kept else narrowed).append(
                    Trigger(ev, owner, e.src, e.dst, e.label, level))
    return live, narrowed


def parse_state_block(lines, entity: str = "") -> Graph:
    """The body of a `state {X} { … }` block (its lines as the walk read them:
    statements.Transition records) as a graph of `state` nodes whose edges carry
    the trigger as their label. `+` / `$` / `_` become start / end / any
    pseudo-state nodes (attrs["pseudo"]); a line that is no transition is
    dropped ("not-a-transition")."""
    g = Graph(role="state")

    def node(name):
        pseudo = PSEUDO_STATES.get(name)
        nid = f"{mk_id(entity)}_state_" + (pseudo if pseudo else mk_id(name))
        if nid not in g.nodes:
            g.nodes[nid] = Node(id=nid, name=name, kind="state",
                                attrs={"pseudo": pseudo} if pseudo else {})
        return g.nodes[nid]

    for t in lines:
        if t.src is None:
            if t.raw:
                g.dropped.append(Dropped(t.line, "not-a-transition", t.raw))
            continue
        a, b = node(t.src), node(t.dst)
        label = f"<{t.trigger}>" if t.trigger else None
        g.edges.append(Edge(src=a.id, dst=b.id, kind="->", label=label,
                            payload=t.rest or None, mods=scan_mods(t.rest), line=t.line))
    return g
