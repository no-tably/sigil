"""
parse — a Sigil document read into the model (sigil.core.graph's records):
parse_document(text, dialect=…) → Graph, parse_glyph, the flow tokenizer, the
statement walk (_DocParser: sections, aliases, expansions, `state` machines,
control blocks, composition trees, declarations), comments attached as notes
and triggers wired to transitions. What the model means is described under
THE MODEL in sigil.core.graph; the Mermaid export (sigil.publish.mermaid) and
every other reader take the Graph from here.
"""

import re
from bisect import bisect_left
from typing import NamedTuple, Optional

from sigil.core.dialects import _hook
from sigil.core.lex import (  # noqa: F401  (also read as parse.<name> by the model's readers)
    ALIAS_RE, ALIAS_REF, ALIAS_REF_RE, ARG_MODIFIERS, ARM_RE, ARROW_RE, BLOCK_DELIM,
    BLOCK_OPEN_RE, BLOCK_SENTINEL, BRANCH_RE, EXPANSION_OPEN_RE, GLUED_MOD_RE, GLYPH_RE,
    JOIN_RE, LOOP_HEAD_RE, MODIFIER_RE, OP_TARGET_RE, OPEN_TO_KIND, PAYLOAD_RE,
    PAYLOAD_TAIL_RE, PRINCIPAL_SET_RE, SCOPE_HEAD_RE, SECTION_RE, STATE_HEAD_RE,
    STATE_OPEN_RE, STREAM_BOUND_RE, TAIL_MOD_RE, TAIL_ONLY_RE, close_at, comment_col,
    comment_start, fold_block_strings, in_string, strip_comment)
from sigil.core.graph import (
    Access, Block, Dropped, Edge, Graph, Join, Node, Note, Section, TreeEntry, Trigger,
    mk_id, walk_depth)

# ---------------------------------------------------------------------------
# Glyph parsing (the lexical tables are sigil.core.lex's)
# ---------------------------------------------------------------------------

def parse_glyph(text: str, layer: str = "L1", dialect=None) -> Optional[Node]:
    text = text.strip()

    # Dialect glyph syntax first (its tokenizers see the glyph at position 0).
    for tok in _hook(dialect, "render_tokenizers"):
        r = tok(text, 0, False, layer, Node)
        if r:
            for kind, node in r[0]:
                if kind == "glyph":
                    return node

    m = GLYPH_RE.match(text)
    if not m:
        return None
    name = m.group("name").replace(_GAP, "").strip()
    kind = OPEN_TO_KIND[m.group("open")]
    is_hole = name == "?"
    return Node(
        id=mk_id(name + "_" + kind),
        name=name,
        kind=kind,
        is_hole=is_hole,
        is_mutable=m.group("mut") == "~",
        is_stream=m.group("stream") == "*",
        layer=layer,
        params=generic_params(name),
    )


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

def _mod_spans(rx, text: str) -> list:
    """(start, end) of each modifier `rx` finds outside `"…"` strings. A
    modifier's trailing text that is only `×N` / `xN` / `!` is left out of its
    span (those are modifiers of their own)."""
    spans = []
    for m in rx.finditer(text):
        if in_string(text, m.start()):
            continue
        start, end = m.start(), m.end()
        tok = m.group(0)
        pm = re.match(r"@[A-Za-z][\w-]*\s*\(", tok)
        if pm:
            close = _close_paren(tok[pm.end() - 1:])
            if close >= 0:
                cut = pm.end() + close
                if cut < len(tok) and TAIL_ONLY_RE.match(tok[cut:]):
                    end = start + cut
        spans.append((start, end))
    return spans


# Masking. A captured modifier / payload is blanked in place, so every other
# column stays put: with one space where the old text-deleting strip put one (a
# modifier with an argument, a payload) and _GAP elsewhere — a filler the
# tokenizer skips and parse_glyph drops, so text around a removed modifier still
# reads as adjacent (as it did when the modifier was deleted).
_GAP = "\x00"


def _blank(n: int, spaced: bool = True) -> str:
    return (" " + _GAP * (n - 1)) if spaced and n else _GAP * n


def mod_pair(text: str) -> tuple:
    """`@timeout(30s)` → ("timeout", "30s"); `@inv >= 0` → ("inv", ">= 0");
    `@all` → ("all", None). A lone `( … )` argument loses its parens."""
    m = re.match(r"@([A-Za-z][\w-]*)\s*", text)
    if not m:
        return (text.strip(), None)
    rest = text[m.end():].strip()
    if rest.startswith("(") and _close_paren(rest) == len(rest) - 1:
        rest = rest[1:-1].strip()
    return (m.group(1), rest or None)


def _close_paren(text: str) -> int:
    depth = 0
    for i, ch in enumerate(text):
        depth += (ch == "(") - (ch == ")")
        if depth == 0:
            return i
    return -1


def scan_mods(text: str) -> list:
    """Every modifier in a statement-free text (a block header tail, an alias
    body, a transition's tail) as (name, arg) pairs, in written order."""
    out = []
    masked = text
    for rx in (STREAM_BOUND_RE, PRINCIPAL_SET_RE, MODIFIER_RE):
        for start, end in _mod_spans(rx, masked):
            tok = masked[start:end]
            out.append((start, ("^", tok[1:]) if tok.startswith("^") else mod_pair(tok)))
            masked = masked[:start] + " " * (end - start) + masked[end:]
    for m in TAIL_MOD_RE.finditer(masked):
        if in_string(masked, m.start()):
            continue
        card = m.group(1) or m.group(2)
        out.append((m.start(), ("×", card) if card else ("^", m.group(3)) if m.group(3)
                    else ("!", None)))
    return [p for _pos, p in sorted(out, key=lambda x: x[0])]


class Subject(NamedTuple):
    """The first endpoint of a flow statement — what a continuation line takes."""
    nodes: tuple              # node ids
    join: Optional[int] = None  # index into Graph.joins when the endpoint is joined
    paths: tuple = ()         # qualifying path per node (`[Bullet]/{Transform}`), or None
    line: int = 0             # the most recent flow line under this subject (Edge.cont)


def _add_mod(mods: list, pair: tuple):
    if pair not in mods:
        mods.append(pair)


def extract_flows(line: str, graph: Graph, layer: str, last_src=None,
                  dialect=None, first: Optional[list] = None, line_no: int = 0,
                  out: Optional[dict] = None):
    """Parse one flow statement: add its nodes, edges, joins, modifiers and access
    declarations to `graph`. Returns the statement's Subject (its first endpoint;
    for a continuation line — one starting with an arrow — the inherited
    `last_src` Subject), or `last_src` unchanged when the line draws nothing.
    `last_src` may also be a bare Node (taken as a one-node subject).
    If `first` is a list, the line's first glyph node is appended to it. If `out`
    is a dict it receives "nodes" (ids placed), "edges" (the new Edge objects) and
    "head" (the id of the glyph the statement starts with, or None)."""
    if isinstance(last_src, Node):
        last_src = Subject((last_src.id,))
    stripped = line
    # Dialect line strips first (dialect-only syntax that must not leak as glyphs).
    for strip in _hook(dialect, "render_line_strips"):
        stripped = strip(stripped)
    lead = len(stripped) - len(stripped.lstrip())
    stripped, mods = _capture_mods(stripped)        # mods: [(column, (name, arg))]
    stripped, payload, payload_span = _take_payload(stripped, mods)
    tokens, event_args, glued = _tokenize_flow(stripped, layer, dialect, mods)
    head = _head(tokens, lead)
    tokens, paths = _fold_paths(tokens)
    if not any(t[0] == "glyph" for t in tokens):
        return last_src

    # Every hole is its own node: `[?] -> [X]` and `[?] -> [Y]` are two unknowns.
    for kind, tok, _c in tokens:
        if kind == "glyph" and tok.is_hole:
            graph.hole_seq[0] += 1
            tok.id = f"{tok.id}{graph.hole_seq[0]}"

    if first is not None:
        first.append(next(t[1] for t in tokens if t[0] == "glyph"))

    groups, links, link_cols = _group_endpoints(tokens, graph, last_src)
    placed = _place_groups(groups, graph, paths, event_args, line_no)
    new_edges, final, op_edges, link_edges = _fan_out(groups, links, line_no)
    if payload:
        for e in final:
            e.payload = f"{e.target_op} : {payload}" if e.target_op else payload
        new_edges += _return_emits(graph, final, payload, layer, line_no)
    graph.edges.extend(new_edges)
    _attach_mods(mods, tokens, graph, final=final, op_edges=op_edges, link_edges=link_edges,
                 link_cols=link_cols, glued=glued, payload=payload,
                 payload_span=payload_span, layer=layer, line_no=line_no)

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


def _capture_mods(stripped: str) -> tuple:
    """Capture a line's modifiers with their column and blank them (length-preserving,
    so the columns of everything else stay put). Stream bounds first (their `@policy` is not
    a modifier of its own); then the permission-graph access lists `@read(…)` /
    `@write(…)` — principal NAMES, which must not read as actor glyphs; then every
    other modifier with its argument — not an `@` inside a `"…"` string (`:
    "ops@example.com"` is payload text).
    Returns (the blanked line, [(column, (name, arg))])."""
    mods = []

    def capture(rx, s, pair):
        for start, end in _mod_spans(rx, s):
            tok = s[start:end]
            mods.append((start, pair(tok)))
            spaced = rx is PRINCIPAL_SET_RE or (rx is MODIFIER_RE and mod_pair(tok)[0]
                                                  in ARG_MODIFIERS)
            s = s[:start] + _blank(end - start, spaced) + s[end:]
        return s

    stripped = capture(STREAM_BOUND_RE, stripped, lambda tok: ("^", tok[1:]))
    stripped = capture(PRINCIPAL_SET_RE, stripped, mod_pair)
    stripped = capture(MODIFIER_RE, stripped, mod_pair)
    return stripped, mods


def _take_payload(stripped: str, mods: list) -> tuple:
    """Take the terminal `: payload` (not a `:=` alias), kept as text for the edge
    less its trailing cardinality / stream-bound / `!` modifiers and alias
    references, which join `mods`. Returns (the line with the payload
    blanked, the payload text or None, its (start, end) span or (-1, -1))."""
    payload = None
    payload_span = (-1, -1)
    pm = PAYLOAD_RE.search(stripped)
    if pm:
        payload_span = (pm.start(), pm.end())
        raw = pm.group(1)
        refs = ALIAS_REF_RE.search(raw.replace(_GAP, " "))
        if refs:
            at = pm.start(1) + refs.start("names")
            mods += [(at, (ALIAS_REF, name)) for name in refs.group("names").split()]
            raw = raw[:refs.start("names")]
        tail = PAYLOAD_TAIL_RE.search(raw.replace(_GAP, " "))   # same length
        if tail and tail.start() < len(raw):
            at = pm.start(1) + tail.start()
            for t in TAIL_MOD_RE.finditer(tail.group(0)):
                card = t.group(1) or t.group(2)
                mods.append((at + t.start(), ("×", card) if card
                             else ("^", t.group(3)) if t.group(3) else ("!", None)))
            raw = raw[:tail.start()]
        payload = raw.replace(_GAP, "").strip() or None
        stripped = stripped[:pm.start()] + _blank(pm.end() - pm.start()) + stripped[pm.end():]
        stripped = PAYLOAD_RE.sub(lambda m: _blank(len(m.group(0))), stripped)
    return stripped, payload, payload_span


def _tokenize_flow(stripped: str, layer: str, dialect, mods: list) -> tuple:
    """Tokenize a blanked flow line into glyphs, arrows, joins, op-call targets
    and glued modifiers (those join `mods`). Returns (tokens as (kind, value,
    column), {id(event token): its `(…)` argument}, columns of `×N` glued to a
    glyph)."""
    tokenizers = list(_hook(dialect, "render_tokenizers"))
    tokens = []                                 # (kind, value, column)
    event_args = {}                             # id(event token) -> its `(…)` argument
    glued = set()                               # columns of `×N` glued to a glyph
    i = 0
    prev_was_glyph = False
    while i < len(stripped):
        ch = stripped[i]
        if ch.isspace() or ch == _GAP:
            i += 1
            continue
        # Dialect tokenizers first (extra glyph / operator syntax).
        hit = None
        for tok in tokenizers:
            hit = tok(stripped, i, prev_was_glyph, layer, Node)
            if hit:
                break
        if hit:
            new_tokens, end, prev_was_glyph = hit
            tokens.extend((k, v, i) for k, v in new_tokens)
            i = end
            continue
        am = ARROW_RE.match(stripped, i)
        if am:
            tokens.append(("arrow", am.group(0), i))
            i = am.end()
            prev_was_glyph = False
            continue
        # Strict join `&` / race `&?` between glyphs (language.md "a & b") groups
        # them into ONE endpoint: `<E> *> [A] & [B]` fans out to both A and B.
        jm = JOIN_RE.match(stripped, i)
        if jm and prev_was_glyph:
            tokens.append(("join", jm.group(0), i))
            i = jm.end()
            prev_was_glyph = False
            continue
        gm = GLYPH_RE.match(stripped, i)
        if gm:
            node = parse_glyph(gm.group(0), layer)
            end = gm.end()
            if node:
                tokens.append(("glyph", node, i))
                arg = _event_arg(stripped, end) if node.kind == "event" else None
                if arg is not None:             # `<H>({C})`: one glyph, its argument
                    event_args[id(node)] = arg[0]
                    end = arg[1]
            i = end
            prev_was_glyph = True
            continue
        if ch == "/" and prev_was_glyph:
            nxt = stripped[i + 1] if i + 1 < len(stripped) else " "
            if nxt in "[{<(|~*" and not stripped[i - 1].isspace():
                # Qualified path `[Bullet]/{Transform}`: a `/` glued between glyphs.
                tokens.append(("slash", "/", i))
            else:
                # Alternative `a / b` (language.md "Structure"): one-of endpoint.
                tokens.append(("join", "/", i))
            i += 1
            prev_was_glyph = False
            continue
        if tokens and tokens[-1][0] == "arrow":
            om = OP_TARGET_RE.match(stripped, i)
            if om:
                tokens.append(("op", om.group(0), i))
                i = om.end()
                prev_was_glyph = False
                continue
        mm = GLUED_MOD_RE.match(stripped, i)
        if mm and (prev_was_glyph or mm.group("bang") or mm.group("card")
                   or mm.group("card2") or mm.group("card3")) and (
                not (mm.group("opt") or mm.group("field"))
                or stripped[:i].rstrip(_GAP)[-1:] in tuple("]}>)|")):
            card = mm.group("card") or mm.group("card2") or mm.group("card3")
            pair = (("×", card) if card else ("!", None) if mm.group("bang")
                    else ("?", None) if mm.group("opt") else (".", mm.group("field")))
            mods.append((i, pair))
            if card and stripped[:i].rstrip(_GAP)[-1:] in tuple("]}>)|"):
                glued.add(i)
            i = mm.end()
            continue                            # prev_was_glyph unchanged
        i += 1  # skip unrecognized chars
        prev_was_glyph = False
    return tokens, event_args, glued


def _fold_paths(tokens: list) -> tuple:
    """Fold `a/b/c` into one reference to `c`, remembering its qualifying path.
    Returns (the tokens without slashes, {id(node token): (name, …, name)})."""
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
        elif kind == "glyph":
            if cur is not None and joining and not cur.get("op"):
                cur["nodes"].append(tok)
                cur["join"] = cur["join"] or joining
            else:
                if cur is not None:        # adjacent glyphs, no operator
                    groups.append(cur)
                    pending = None
                if groups:
                    links.append(pending)
                    link_cols.append(pending_col if pending else None)
                cur = {"nodes": [tok], "join": None, "join_idx": None, "op": None}
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


def _event_arg(text: str, at: int) -> Optional[tuple]:
    """(argument, end column) of a `( … )` glued to an event glyph ending at `at`
    (`<H>({C})` → ("{C}", …)); None when no balanced `(` follows."""
    if not text.startswith("(", at):
        return None
    close = _close_paren(text[at:])
    if close < 0:
        return None
    return text[at + 1:at + close].replace(_GAP, "").strip() or None, at + close + 1


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


# A transition inside a `state` block: `Src -<trigger>-> Dst` or `Src -> Dst`,
# optionally followed by per-transition modifiers (`×3`, `@timeout(…)`, …).
TRANSITION_RE = re.compile(r"^(\S+)\s+(?:-<([^<>]*)>->|->)\s+(\S+)\s*(.*)$")
PSEUDO_STATES = {"+": "start", "$": "end", "_": "any"}

# What may precede an inline branch (`[parent] \\-& [child]`): glyphs only — no
# payload colon, no prose.
_BRANCH_PARENT_RE = re.compile(r"^\s*[~*]?[\[{<(|][^:]*[\]}>)|]\s*$")

# Core glyph kinds (OPEN_TO_KIND); any other kind is a dialect's.
_CORE_KINDS = set(OPEN_TO_KIND.values())


def _close_head(stripped: str, before: int) -> tuple:
    """The line that closes an expansion open `before` deep: the text before its
    `}` (the body's last line) and the modifiers after it (`} @inv x` — the
    node's)."""
    cut = close_at(stripped, before)
    if cut is None:
        return stripped, []
    return stripped[:cut], scan_mods(stripped[cut + 1:])


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
    """An open control block while its body is read."""
    def __init__(self, idx: int):
        self.idx = idx            # index into Graph.blocks
        self.depth = 1            # braces open since the header's `{`
        self.arm = None           # branch: index of the arm being read
        self.subjects = []        # subjects of the body's own statements


class _BodyLines:
    """The lines of an expansion body read in one pass (see _DocParser._stream):
    the document's own lines from `base` on, except those the body reads rewritten
    (a header's text after its `{`, a closing line's text before its `}`)."""
    def __init__(self, shared: list, base: int):
        self.shared, self.base = shared, base
        self.over: dict = {}                # body index → rewritten line
        self.n = 0                          # lines read so far

    def __getitem__(self, k: int) -> str:
        return self.over[k] if k in self.over else self.shared[self.base + k]

    def __len__(self) -> int:
        return self.n


class _DocParser:
    """parse_document's line-by-line state — one instance per document (and per
    `:= { … }` sub-document). Handlers named `_on_*` take a line and return True
    when it was theirs; `_in_*` continue a block being collected."""

    def __init__(self, hole_seq: Optional[list], dialect, line0: int = 0):
        self.graph = Graph()
        if hole_seq is not None:
            self.graph.hole_seq = hole_seq
        self.top = hole_seq is None
        self.dialect = dialect
        self.line0 = line0              # source line of this (sub-)document's first line, - 1
        self.layer = "L1"
        # The Subject a continuation line takes: the first endpoint of the last
        # statement that was not itself a continuation (or a closed block's subject).
        self.last_src = None
        # `X := { … }` / `X := expr` definitions and `state` machines, resolved once
        # the whole document is read so one written BEFORE its node's first use
        # still attaches.
        self.pending_expansions = []   # (name, kind, sub_graph|None, layer, mods, line)
        self.pending_states = []       # (owner Node, state graph, `} @mods` pairs)
        # Blocks being collected. Expansion: [target_name, target_kind, raw lines
        # (read in one pass: only the header's text after its `{`), brace depth,
        # first line, layer, header line]; state: [owner Node | None,
        # lines, brace depth, header index]; declaration: [(regex, on_raw), depth,
        # header index].
        self.expansion = None
        self.state = None
        self.decl = None
        self.decl_blocks = list(_hook(dialect, "DECLARATION_BLOCKS"))
        self.prepasses = list(_hook(dialect, "render_prepasses"))
        # Open control blocks (loop / parallel / branch / scope / owns), innermost
        # last; and the block whose subject continuation lines after it take.
        self.frames: list = []
        self.after_block = None
        # Composition tree state: open branches as (column, tree index), and the last
        # plain glyph line a branch could hang under: [column, node id, tree index|None,
        # line].
        self.tree_stack: list = []
        self.tree_root: Optional[list] = None
        # Notes: the node the current line is "about", the document's comments, and
        # own-line comments waiting for the statement below.
        self.anchor = None
        self.comments: dict = {}
        self.marker = _comment_marker(dialect)
        self.above: list = []
        # No statement, declaration or section read yet: comments detached
        # above here are the document's header (top level only).
        self.seen = False
        # The lines being read (block-strings folded): the text of a dropped line.
        self.lines: list = []

    def ln(self, k: int) -> int:
        """The source line of this document's line index k."""
        return self.line0 + k + 1

    # -- driver ---------------------------------------------------------------

    def parse(self, text: str) -> Graph:
        # Pre-pass: fold multiline `"""…"""` block-strings to masked single-line STRs
        # so the block body never emits phantom nodes (block-aware for this token).
        # Then any dialect pre-passes (line-count preserving).
        bodies: dict = {}
        lines = fold_block_strings(text.splitlines(), comment_col, rescan=False,
                                   bodies=bodies).lines
        self.comments = collect_comments(lines, self.dialect)   # before dialect pre-passes
        for prepass in self.prepasses:
            lines = prepass(lines)
        self.lines = lines
        # A `"""` the pre-pass left (in a comment, a second block-string on a line)
        # would be folded again inside a body, which reading bodies in one pass
        # cannot see ahead to: such a document collects each body and parses it
        # on its own, as a sub-document.
        if any(BLOCK_DELIM in raw for raw in lines):
            for k, raw in enumerate(lines):
                self.line(k, raw)
        else:
            self._stream(lines)
        graph = self._end(len(lines))
        if bodies:
            _attach_block_strings(graph, {self.ln(k): body for k, body in bodies.items()})
        return graph

    def _end(self, n: int) -> Graph:
        """The text (of n lines) is read: drop what was left open, then finish."""
        self._drop_unclosed(n)
        while self.frames:                  # a block left open at the end of the text
            self._close_block(n - 1)
        self._detach()
        return self.finish()

    def _stream(self, lines: list):
        """Read the lines once each. An expansion body is read as it arrives by a
        child parser — the stack's innermost — and adopted when its closing `}`
        does; nesting grows the stack, not the Python call stack.

        Every open body counts the same braces on a line it does not close, so one
        running sum `acc` stands for all: body i's depth is offs[i] + acc. The
        bodies a line closes are those whose depth it takes to 0 or below; the
        outermost is found by bisecting the running minimum of offs. Inside it,
        each deeper body reads that line's text before its `}` as a sub-document
        would, and is adopted if its own parent closed on the line, else discarded
        with the hole numbers it took (a sub-document never parses a body it
        leaves unclosed)."""
        stack = [self]                      # each parser but the last has an open body
        offs: list = []                     # offs[i]: depth of stack[i]'s body, less acc
        lows: list = []                     # lows[i]: -min(offs[:i + 1]) (ascending)
        acc = 0
        hole_seq = self.graph.hole_seq
        for t, raw in enumerate(lines):
            stripped = strip_comment(raw).rstrip()
            line = stripped.strip()
            delta = (self._delta(raw.strip(), line)
                     if offs and line and not line.startswith("#!") else 0)
            j = bisect_left(lows, acc + delta)
            if j == len(lows):              # closes no body: the innermost reads it
                acc += delta
                self._read(stack, offs, lows, acc, t, raw, False)
                continue
            # Body j closes; the text before its `}` goes on down the open bodies.
            head, mods = _close_head(stripped, offs[j] + acc)
            closed = {j: mods}              # body index → modifiers after its `}`
            fed = set()                     # bodies that read the line's text
            text = head if head.strip() else None
            i = j + 1
            while text is not None and i < len(stack):
                if i == len(stack) - 1:
                    fed.add(i)
                    self._read(stack, offs, lows, acc, t, text, True)
                    break
                p = stack[i]
                fed.add(i)
                text = p._body_line(t, text)
                t_stripped = strip_comment(text).rstrip()
                t_line = t_stripped.strip()
                if t_line and not t_line.startswith("#!"):
                    before = offs[i] + acc
                    if before + self._delta(text.strip(), t_line) <= 0:
                        head, closed[i] = _close_head(t_stripped, before)
                        text = head if head.strip() else None
                i += 1
            while len(stack) > j + 1:
                child = stack.pop()
                offs.pop()
                lows.pop()
                parent = len(stack) - 1
                if parent in closed:
                    home = stack[parent]
                    sub = child._end(child._body_len(t, parent + 1 in fed))
                    home._close_expansion(home._adopt(sub), closed[parent])
                else:
                    hole_seq[0] = child.hole0   # its holes were never numbered
            acc += delta
        while len(stack) > 1:               # bodies left open at the end of the text
            hole_seq[0] = stack.pop().hole0

    def _read(self, stack: list, offs: list, lows: list, acc: int, t: int, text: str,
              rewritten: bool):
        """The innermost parser reads document line t (`text`, rewritten when it is
        not the document's own line); a body it opens is pushed and reads the
        header's text after the `{`."""
        p = stack[-1]
        if p is self:
            self.line(t, text)
        else:
            p._read_body_line(t, text, rewritten)
        while p.expansion is not None:
            exp = p.expansion
            child = _DocParser(self.graph.hole_seq, self.dialect, exp[4])
            child.base = exp[4] - self.line0     # document index of its line 0
            child.lines = _BodyLines(self.lines, child.base)
            child.hole0 = self.graph.hole_seq[0]
            off = exp[3] - acc
            offs.append(off)
            lows.append(max(lows[-1], -off) if lows else -off)
            stack.append(child)
            if not exp[2]:
                break
            child._read_body_line(t, exp[2].pop(), True)
            p = child

    def _body_line(self, t: int, text: str) -> str:
        """A body's rewritten line arrives (document line t): this body's dialect
        pre-passes run on it, as on a sub-document's lines. Returns it as read."""
        k = t - self.base
        for prepass in self.prepasses:
            text = prepass([text])[0]
        self.lines.over[k] = text
        return text

    def _read_body_line(self, t: int, text: str, rewritten: bool):
        """A body reads its line at document index t. Its comments are those of the
        line it was given (before its own pre-passes), as a sub-document's are."""
        k = t - self.base
        src = text
        if rewritten:
            text = self._body_line(t, text)
        self.lines.n = k + 1
        c = _comment_of(src, self.marker)
        if c:
            self.comments[k] = c
        self.line(k, text)

    def _body_len(self, t: int, fed: bool) -> int:
        """How many lines this body has when document line t closes it (`fed`: the
        closing line's head is its last line). A sub-document's text was its lines
        joined with newlines and split again, which loses one trailing blank line."""
        n = t - self.base + (1 if fed else 0)
        if not fed and n > 0 and (n - 1) not in self.lines.over and self.lines[n - 1] == "":
            n -= 1
        self.lines.n = n
        return n

    def _close_expansion(self, sub: Graph, mods: list):
        """The open expansion's body is read: `sub` is its graph."""
        exp = self.expansion
        self.pending_expansions.append((exp[0], exp[1], sub, exp[5], mods, exp[6]))
        self.expansion = None

    def line(self, k: int, raw: str):
        raw_lead = raw.strip()
        stripped = strip_comment(raw).rstrip()
        line = stripped.strip()
        # Inside an expansion block (checked first: everything up to its closing `}`
        # — section headers, declarations, a nested `X := {` — belongs to it).
        if self.expansion is not None:
            self._in_expansion(raw, raw_lead, stripped, line)
            return
        if self.state is None and self.decl is None:
            c = self.comments.get(k)
            if c and c[1]:                  # a comment on its own line
                self.above.append((c[0], self.ln(k)))
                return
            if not line:                    # a blank line detaches waiting comments
                self._detach()
        if self._on_declaration(k, raw_lead, line) or self._on_section(k, line):
            return
        if line.startswith("#!") or not line:
            return
        if self.state is not None:
            self._in_state(k, line)
        else:
            self._statement(k, stripped, 0)

    def _statement(self, k: int, text: str, offset: int):
        """One statement (`text` found at column `offset`): a definition, a block
        header, a line inside / closing an open block, or a flow."""
        line = text.strip()
        if not line:
            return
        if (self._on_alias(k, line) or self._on_state_head(k, line)
                or self._on_block_head(k, text, offset)):
            return
        if self.frames:
            fr = self.frames[-1]
            before = fr.depth
            fr.depth += line.count("{") - line.count("}")
            if fr.depth <= 0:               # the line closes the innermost block
                cut = close_at(text, before)
                head = text[:cut] if cut is not None else text
                if head.strip():
                    self._flow_line(k, head, offset)
                self._close_block(k)
                rest = text[cut + 1:] if cut is not None else ""
                if rest.strip():            # `} !> [X]`, `} }`, `} @inv …`
                    self._after_close(k, rest, offset + cut + 1)
                return
        self._flow_line(k, text, offset)

    def finish(self) -> Graph:
        graph = self.graph
        by_level: dict = {}               # level → expansion graphs written at it
        order = sorted(range(len(self.pending_expansions)),
                       key=lambda i: _layer_num(self.pending_expansions[i][3]))
        for i in order:
            name, kind, sub_graph, layer, mods, line = self.pending_expansions[i]
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
            if target_id is None:
                # Defined but never referenced in a flow — still a node of the design.
                # A bare-word definition (`walk := …`) is an `alias` node.
                target_id = mk_id(name + "_" + (kind or "alias"))
                graph.nodes[target_id] = Node(id=target_id, name=name,
                                              kind=kind or "alias", layer=layer)
            node = home.nodes[target_id]
            for pair in mods:
                _add_mod(node.mods, pair)
            provisional = mk_id(name + "_" + (kind or "alias"))
            if provisional != target_id:     # notes and heads recorded before resolution
                for note in self.graph.notes:
                    if note.node == provisional and note.line == line:
                        note.node = target_id
                self.graph.heads = [(ln, target_id if (ln, nid) == (line, provisional) else nid)
                                    for ln, nid in self.graph.heads]
            if sub_graph is not None:
                home.expansions[target_id] = sub_graph
                by_level.setdefault(level, []).append(sub_graph)

        for owner, machine, tail in self.pending_states:
            node = graph.nodes.setdefault(owner.id, owner)
            for pair in tail:
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

    def _sub_parse(self, text: str, line0: int) -> Graph:
        return self._adopt(parse_document(text, self.graph.hole_seq, self.dialect,
                                          _line0=line0))

    def _delta(self, raw_lead: str, line: str) -> int:
        """Net braces a line opens. A raw-matched declaration opener (a `#…` marker,
        erased by comment stripping) counts on the raw line, as _on_declaration does."""
        if any(on_raw and rx.match(raw_lead) for rx, on_raw in self.decl_blocks):
            line = raw_lead
        return line.count("{") - line.count("}")

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
        trailing = self.comments.get(k)
        if trailing and not trailing[1] and not body.strip():
            self.graph.notes.append(Note(None, trailing[0], self.ln(k), "inline", block=bi))
        self.above.clear()

    def attach(self, node_id, k: int, edges: tuple = ()):
        self.seen = True
        if node_id and self.above:
            self.graph.notes.append(Note(node_id, " ".join(t for t, _ln in self.above),
                                         self.above[0][1], "block"))
        trailing = self.comments.get(k)
        if node_id and trailing and not trailing[1]:
            self.graph.notes.append(Note(node_id, trailing[0], self.ln(k), "inline", edges))
        self.above.clear()

    def _drop(self, k: int, reason: str):
        """Record line index k as read and discarded (a blank or comment-only line
        is not recorded)."""
        text = self.lines[k].strip() if 0 <= k < len(self.lines) else ""
        if strip_comment(text).strip():
            self.graph.dropped.append(Dropped(self.ln(k), reason, text))

    def _drop_unclosed(self, n: int):
        """At the end of the text: a block still being collected (an expansion,
        a `state` machine, a declaration) was never closed — its header and every
        line after it are lost."""
        heads = []
        if self.expansion is not None:
            heads.append(self.expansion[6] - self.line0 - 1)
        if self.state is not None:
            heads.append(self.state[3])
        if self.decl is not None:
            heads.append(self.decl[2])
        for k in range(min(heads), n) if heads else ():
            self._drop(k, "unclosed")

    def _adopt(self, sub: Graph) -> Graph:
        """A sub-document's graph, its dropped lines also listed as this graph's."""
        self.graph.dropped.extend(sub.dropped)
        return sub

    def add_entry(self, node_id, parent, line: int, rel=None, spawn=False, cond=None,
                  weight=None):
        depth = self.graph.tree[parent].depth + 1 if parent is not None else 0
        self.graph.tree.append(TreeEntry(node_id, parent, rel, spawn, cond, depth, weight, line))
        return len(self.graph.tree) - 1

    # -- blocks ---------------------------------------------------------------

    def _in_expansion(self, raw: str, raw_lead: str, stripped: str, line: str):
        exp = self.expansion
        if not line or line.startswith("#!"):
            exp[2].append(raw)              # keep comments/blank lines for the sub-parse
            return
        before = exp[3]
        exp[3] += self._delta(raw_lead, line)
        if exp[3] > 0:
            exp[2].append(raw)
            return
        # End of expansion — keep what precedes its closing `}`, then parse the
        # body as a sub-document.
        last, mods = _close_head(stripped, before)
        if last.strip():
            exp[2].append(last)
        self._close_expansion(self._sub_parse("\n".join(exp[2]), exp[4]), mods)

    def _on_declaration(self, k: int, raw_lead: str, line: str) -> bool:
        """Dialect DECLARATION blocks (`name { … }` whose body declares, not flows)
        render nothing. Raw-matched openers track depth on the raw line (a `#…`
        marker would be erased by comment stripping), others on the stripped one."""
        if self.decl is not None:
            txt = raw_lead if self.decl[0][1] else line
            self.decl[1] += txt.count("{") - txt.count("}")
            if self.decl[1] <= 0:
                self.decl = None
            return True
        for opener, on_raw in self.decl_blocks:
            txt = raw_lead if on_raw else line
            if opener.match(txt):
                depth = txt.count("{") - txt.count("}")
                self.decl = [(opener, on_raw), depth, k] if depth > 0 else None
                self.last_src = None
                self.seen = True
                return True
        return False

    def _on_section(self, k: int, line: str) -> bool:
        sec = SECTION_RE.match(line)
        if not sec:
            return False
        self._detach()
        self.seen = True
        if sec.group(1):
            self.layer = sec.group(1)
        if self.layer not in self.graph.layers:
            self.graph.layers.append(self.layer)
        self.graph.sections.append(Section(sec.group(1), sec.group(2), self.ln(k)))
        self.last_src = None
        self.after_block = None
        return True

    def _on_alias(self, k: int, line: str) -> bool:
        """Definitions — `name := expr`, `[name] := expr`, `X := { … }` — are not
        flows: each names a node (a bare-word name is an `alias` node) whose
        expansion is its definition — a `{ … }` body, or a one-line flow — parsed
        recursively. A definition that draws no flow (prose, `retry := @after(…)`)
        gives the node its modifiers and no expansion."""
        am = ALIAS_RE.match(line)
        if not am:
            return False
        name = am.group("svc") or am.group("data") or am.group("word")
        kind = ("service" if am.group("svc") is not None
                else "data" if am.group("data") is not None else None)
        rhs = am.group("rhs").strip()
        nid = mk_id(name + "_" + (kind or "alias"))
        self.attach(nid, k)
        self.graph.heads.append((self.ln(k), nid))
        self.last_src = None
        self.after_block = None
        if EXPANSION_OPEN_RE.match(rhs):
            body = rhs[1:]
        elif rhs.endswith("{"):
            body = ""
        else:
            # A one-line definition is an expansion when it draws a flow
            # (`walk := [Node] -> walk(.children)`); a prose or modifier-only
            # definition (`[Cache] := {Summary} store`, `retry := @after(…)`) only
            # names the node — its modifiers become the node's.
            sub = self._sub_parse(rhs, self.ln(k) - 1)
            flow = bool(sub.edges)
            self.pending_expansions.append((name, kind, sub if flow else None, self.layer,
                                            [] if flow else scan_mods(rhs), self.ln(k)))
            return True
        cut = close_at(body, 1)
        if cut is not None:
            # One-line expansion `[X] := { … }`: its body is right here.
            self.pending_expansions.append((name, kind,
                                            self._sub_parse(body[:cut], self.ln(k) - 1),
                                            self.layer, scan_mods(body[cut + 1:]),
                                            self.ln(k)))
        else:
            self.expansion = [name, kind, [body] if body.strip() else [],
                              1 + body.count("{") - body.count("}"),
                              self.ln(k) - 1 if body.strip() else self.ln(k), self.layer,
                              self.ln(k)]
        return True

    def _on_state_head(self, k: int, line: str) -> bool:
        """`state {X} { … }` — a state machine of entity X: collected, then parsed
        into its own graph that hangs off the {X} node (like an expansion)."""
        sm = STATE_HEAD_RE.match(line)
        if not sm:
            if not STATE_OPEN_RE.match(line):
                return False
            # No owner glyph: the block is consumed, nothing drawn.
            self.attach(None, k)
            depth = line.count("{") - line.count("}")
            self.state = [None, [], depth, k] if depth > 0 else None
            if depth <= 0:
                self._drop(k, "no-owner")
            return True
        owner = parse_glyph(sm.group(1), self.layer, self.dialect)
        self.attach(owner.id if owner else None, k)
        body = line[sm.end():]
        cut = close_at(body, 1)
        if cut is not None:
            # One-line `state {X} { A -> B }`.
            if owner and body[:cut].strip():
                self.pending_states.append((owner, self._adopt(
                    parse_state_block([(body[:cut], self.ln(k))], owner.name)),
                    scan_mods(body[cut + 1:])))
            elif not owner:
                self._drop(k, "no-owner")
        else:
            self.state = [owner, [(body.strip(), self.ln(k))] if body.strip() else [],
                          1 + body.count("{") - body.count("}"), k]
        return True

    def _in_state(self, k: int, line: str):
        st = self.state
        before = st[2]
        st[2] += line.count("{") - line.count("}")
        if st[2] > 0:
            st[1].append((line, self.ln(k)))
            return
        cut = close_at(line, before)
        if cut is not None and line[:cut].strip():
            st[1].append((line[:cut].strip(), self.ln(k)))   # a last transition before the `}`
        if st[0]:
            # Modifiers after the `}` (`} @inv ordered(id)`) are the owner's.
            tail = scan_mods(line[cut + 1:]) if cut is not None else []
            self.pending_states.append((st[0], self._adopt(parse_state_block(st[1],
                                                                             st[0].name)),
                                        tail))
        else:
            for kk in range(st[3], k + 1):
                self._drop(kk, "no-owner")
        self.state = None

    def _on_block_head(self, k: int, text: str, offset: int) -> bool:
        """A control-block header — `loop …`, `parallel …`, `branch on X`, a scoped
        `name {`, an `[X] @owns |R| {` — opens a Block whose body statements are
        ordinary flows (recorded as the block's members / edges / arms)."""
        line = text.strip()
        hm = LOOP_HEAD_RE.match(line)
        om = BLOCK_OPEN_RE.search(text)
        if hm:
            kind = hm.group(1)
        elif om and SCOPE_HEAD_RE.match(line):
            kind = "scope"
        elif om and "@owns" in text[:om.start()] and GLYPH_RE.search(text[:om.start()]):
            kind = "owns"
        else:
            return False
        if om is None:                      # a header with no body: nothing to read
            return True
        head = text[:om.start()].strip()
        refs, mods = [], []
        if kind == "owns":
            # The header is itself a statement: the owner node (+ its @owns modifier).
            out = {}
            self._flow_line(k, text[:om.start()], offset, out=out, in_header=True)
            header = head
            mods = scan_mods(head)
            refs = list(out.get("nodes", []))
            owned = [parse_glyph(gm.group(0), self.layer).id
                     for p in mods if p[0] == "owns" and p[1]
                     for gm in GLYPH_RE.finditer(p[1])]
        else:
            header = re.sub(r"^(?:loop|parallel|branch(?:\s+on\b)?)\s*", "", head) \
                if kind != "scope" else head
            parts = [p for p in re.split(r"(?:^|\s+)(?=@[A-Za-z])", header) if p.strip()]
            mods = [mod_pair(p) for p in parts if p.startswith("@")]
            for gm in GLYPH_RE.finditer(header):
                n = parse_glyph(gm.group(0), self.layer)
                if n is None:
                    continue
                if n.is_hole:
                    self.graph.hole_seq[0] += 1
                    n.id = f"{n.id}{self.graph.hole_seq[0]}"
                self.graph.nodes.setdefault(n.id, n)
                refs.append(n.id)
        parent = self.frames[-1].idx if self.frames else None
        block = Block(kind, header, mods, parent=parent, lines=(self.ln(k), self.ln(k)),
                      refs=list(dict.fromkeys(refs)))
        if kind == "owns":
            block._owned = owned            # resolved in finish()
        self.graph.blocks.append(block)
        self.frames.append(_Frame(len(self.graph.blocks) - 1))
        self.last_src = None
        self.after_block = None
        body = text[om.start() + 1:]
        if kind != "owns":                  # the owns header attached to its owner
            self.attach_block(len(self.graph.blocks) - 1, k, body)
        if body.strip():                    # statements after the header's `{`
            self._statement(k, body, offset + om.start() + 1)
        return True

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

    def _after_close(self, k: int, rest: str, offset: int):
        """Text after a block's closing `}` on the same line."""
        line = rest.strip()
        if line.startswith("@"):            # `} @inv …`: the block's own modifiers
            b = self.graph.blocks[self.after_block]
            for p in scan_mods(line):
                _add_mod(b.modifiers, p)
            return
        self._statement(k, rest, offset)

    # -- flows ----------------------------------------------------------------

    def _flow_line(self, k: int, text: str, offset: int, out: Optional[dict] = None,
                   in_header: bool = False):
        """Flow the statement `text` (found at column `offset`), record it in the
        open blocks, and attach the waiting comments to the node it is about."""
        self.anchor = None
        body = text.strip()
        fr = self.frames[-1] if self.frames else None
        block = self.graph.blocks[fr.idx] if fr else None
        arm = False
        if block is not None and block.kind == "branch" and not in_header:
            am = ARM_RE.match(body)
            if am and not ARROW_RE.match(body):
                # A branch arm: its flow starts afresh (it is not a continuation).
                block.arms.append((am.group("label"), []))
                block.arm_nodes.append((am.group("label"), []))
                fr.arm = len(block.arms) - 1
                offset += text.find(am.group("body")) if am.group("body") else len(text)
                text = body = am.group("body")
                arm = True
                self.last_src = None
                if not body.strip():
                    self.attach(None, k)
                    return
        continuation = bool(ARROW_RE.match(body))
        col = offset + len(text) - len(text.lstrip())
        acc = {"nodes": [], "edges": []}
        subject = self._flow(body, col, self.last_src, k, acc, heads=not arm)
        if not continuation:
            self.last_src = subject
        elif (isinstance(subject, Subject) and isinstance(self.last_src, Subject)
              and subject.nodes == self.last_src.nodes):
            self.last_src = subject             # the same subject, its latest flow line
        edges = acc["edges"]
        keys = list(dict.fromkeys(e.key for e in edges))
        for f in self.frames:
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
        drawn = tuple(dict.fromkeys(e.key for e in edges if e.src != e.dst))
        self.attach(self.anchor, k, drawn)

    def _flow(self, text: str, col: int, last, k: int, acc: dict, heads: bool = True):
        """One flow line; composition branches (`\\-<rel>`) become tree entries.
        `heads`: whether the glyph it starts with heads a statement (Graph.heads);
        a branch arm's body (`x => [A]`) heads none, its line starts with the label."""
        graph, dialect = self.graph, self.dialect

        def flows(t, last, cap):
            out = {}
            res = extract_flows(t, graph, self.layer, last, dialect, first=cap,
                                line_no=self.ln(k), out=out)
            acc["nodes"].extend(n for n in out.get("nodes", ()) if n not in acc["nodes"])
            acc["edges"].extend(out.get("edges", ()))
            if heads and out.get("head"):
                graph.heads.append((self.ln(k), out["head"]))
            return res

        m = BRANCH_RE.search(text)
        if m is not None and m.start() > 0 and not _BRANCH_PARENT_RE.match(text[:m.start()]):
            m = None                         # a marker inside prose / a payload, not a branch
        if m is None:
            cap: list = []
            last = flows(text, last, cap)
            if cap:
                self.tree_stack = [t for t in self.tree_stack if t[0] < col]
                self.tree_root = [col, cap[0].id, None, self.ln(k)]
                self.anchor = cap[0].id
            return last
        left, rest = text[:m.start()], BRANCH_RE.sub(" ", text[m.end():])
        bcol = m.start() + col
        if left.strip():                     # inline: `[parent] \\-& [child]`
            cap = []
            last = flows(left, last, cap)
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
        last = flows(rest, last, cap)
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


def parse_document(text: str, _hole_seq: Optional[list] = None, dialect=None,
                   _line0: int = 0) -> Graph:
    """Parse a Sigil document into a Graph structure (see "THE MODEL" above).
    `dialect` is a loaded dialect (dialects.load) or None for core Sigil.
    `_hole_seq` / `_line0` are internal: a sub-document (an expansion body) shares
    its parent's hole counter, and its line numbers are offset to the source's."""
    return _DocParser(_hole_seq, dialect, _line0).parse(text)


def _attach_block_strings(graph: Graph, bodies: dict):
    """Give each edge whose payload holds a block-string its text: bodies is
    {source line: text}, the line its block opens on (the flow's own line)."""
    for g, _owner, _level in walk_depth(graph):
        for e in g.edges:
            if e.payload and BLOCK_SENTINEL in e.payload and e.line in bodies:
                e.block_string = bodies[e.line]


def collect_comments(lines: list, dialect=None) -> dict:
    """{line index: (text, own_line)} for every comment. Core comments start with
    `#` (not the `#!` mode line, nor a `#&` marker — see lex.COMMENT_START_RE); a
    dialect may add markers (COMMENT_MARKERS, regex sources matched at line start
    or after whitespace). A marker inside a `"…"` string starts no comment."""
    marker = _comment_marker(dialect)
    out = {}
    for k, line in enumerate(lines):
        c = _comment_of(line, marker)
        if c:
            out[k] = c
    return out


def _comment_marker(dialect=None):
    """The dialect's extra comment markers as one regex, or None."""
    extra = list(_hook(dialect, "COMMENT_MARKERS"))
    return re.compile(r"(?:^|(?<=\s))(?:" + "|".join(extra) + ")") if extra else None


def _comment_of(line: str, marker) -> Optional[tuple]:
    """collect_comments for one line: (text, own_line), or None."""
    if line.lstrip().startswith(("#!", "#&")):
        return None
    hits = [comment_start(line, notes_only=True)]
    if marker:
        hits.append(next((h for h in marker.finditer(line)
                          if not in_string(line, h.start())), None))
    hits = [h for h in hits if h]
    if not hits:
        return None
    m = min(hits, key=lambda h: h.start())
    text = line[m.end():].strip()
    return (text, not line[:m.start()].strip()) if text else None


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


def parse_state_block(lines: list, entity: str = "") -> Graph:
    """The body of a `state {X} { … }` block as a graph of `state` nodes whose
    edges carry the trigger as their label. `+` / `$` / `_` become start / end /
    any pseudo-state nodes (attrs["pseudo"])."""
    g = Graph(role="state")

    def node(name):
        pseudo = PSEUDO_STATES.get(name)
        nid = f"{mk_id(entity)}_state_" + (pseudo if pseudo else mk_id(name))
        if nid not in g.nodes:
            g.nodes[nid] = Node(id=nid, name=name, kind="state",
                                attrs={"pseudo": pseudo} if pseudo else {})
        return g.nodes[nid]

    for line in lines:
        line, line_no = line if isinstance(line, tuple) else (line, 0)
        m = TRANSITION_RE.match(line.strip())
        if not m:
            if strip_comment(line).strip():
                g.dropped.append(Dropped(line_no, "not-a-transition", line.strip()))
            continue
        src, trigger, dst, rest = m.groups()
        a, b = node(src), node(dst)
        label = f"<{trigger}>" if trigger else None
        rest = rest.strip()
        g.edges.append(Edge(src=a.id, dst=b.id, kind="->", label=label,
                            payload=rest or None, mods=scan_mods(rest), line=line_no))
    return g
