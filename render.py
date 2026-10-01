#!/usr/bin/env python3
"""
render.py — Render a Sigil document as a Mermaid flowchart (TD).

Usage:
    ./render.py <file.sigil> [--depth N|all] [--composition MODE] [--dialect NAME]
    cat doc.sigil | ./render.py - [--depth N|all] [--composition MODE] [--dialect NAME]

Options:
    --depth N          Draw `X := { … }` expansions (and `state` machines) as
                       subgraphs up to N levels deep (default: 1). --depth 0 draws
                       no expansion subgraphs; --depth all draws every level.
    --composition MODE How composition trees (`\\-<rel>` branches) are drawn:
                       `subgraphs` (default — nested subgraphs, one node per
                       occurrence), `edges` (one node per name, dotted relation
                       edges) or `none`. A dialect may change the default.
    --dialect NAME     Load a dialect (name or path to a dialect.py) that extends
                       the glyph syntax / strips. Default: env SIGIL_DIALECT; unset
                       = core Sigil. See dialects.py.

Output:
    Mermaid `flowchart TD` source on stdout, ready to paste into any
    Mermaid-compatible renderer (GitHub, Obsidian, Notion, mermaid.live).

Visual language (NODE_SHAPE):
    [X]  component → rectangle,  blue
    {X}  data      → hexagon,    purple
    <X>  event     → asymmetric, orange
    (X)  actor     → circle,     green
    |X|  store     → cylinder,   yellow
    a state of a `state {X} { … }` machine → stadium, teal

    [?]  hole      → dashed border (every hole is its own node)
    ~X   mutable   → thick border, label prefixed `~`
    *X   stream    → label prefixed `*`

Arrows (ARROW_MAP):
    ->  / →   solid           -->
    ~>        dotted          -.->
    <->       double          <-->
    =>        thick           ==>
    !>        labelled "!"    -- "!" -->
    ?>        dotted "?"      -. "?" .->
    *>        fan-out         one --> per target
"""

import sys
import re
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Glyph parsing
# ---------------------------------------------------------------------------

GLYPH_RE = re.compile(
    r"(?P<mut>~)?(?P<stream>\*)?"
    r"(?P<open>[\[\{<\(\|])"
    r"(?P<name>[^\[\]\{\}<>()|]+)"
    r"(?P<close>[\]\}>\)\|])"
)

# Permission-graph access modifiers `@read(…)` / `@write(…)` (language.md
# "Permission graph"). These carry a `( )` comma-list of principal names — a
# DECLARATION of access edges on a store, not a flow. The modifier + its list are
# stripped before flow extraction so a list like `(boss, worker)` is not rendered
# as a phantom actor-glyph node (mirrors the @inv/@cap modifier strips). The store
# the edge anchors on still renders.
PERMISSION_SET_RE = re.compile(r"@(?:read|write)\s*\([^()]*\)")

OPEN_TO_KIND = {
    "[": "service",
    "{": "data",
    "<": "event",
    "(": "actor",
    "|": "store",
}

ARROW_MAP = {
    "<->": "<-->",
    "->":  "-->",
    "~>":  "-.->",
    "=>":  "==>",
    "!>":  '-- "!" -->',
    "?>":  '-. "?" .->',
    "*>":  "-->",  # broadcast — rendered by fanning out to each target
    "→":   "-->",
}

ARROW_RE = re.compile(r"(<->|->|~>|=>|!>|\?>|\*>|→)")

# Strict join `&` / race `&?` between glyphs (language.md "a & b").
JOIN_RE = re.compile(r"&\??")

# A modifier's `( … )` argument, one level of nested parens allowed (`@inv(f(x) > 0)`).
_PAREN_ARG = r"\((?:[^()]|\([^()]*\))*\)"

# Modifiers whose argument may also (or further) follow without parens (`@owns
# |Conn|`, `@inv unique:order_id`, `@borrow(read) |tree|`): that argument runs to the
# next arrow, `@` or line end. Their contents are semantic, not structural — they
# must not leak as phantom glyphs.
_ARG_MODIFIERS = ("inv", "sla", "cap", "grants", "requires", "owns", "borrow",
                  "loc", "timeout", "after", "deadline", "notify")

# Every modifier (a property, not a flow or a node — it leaves no phantom node): one
# of the above with its argument, or any other `@name` with an optional `( … )`.
# Only the modifier and its argument go: `[A] @timeout(5s) -> [B]` keeps its flow.
MODIFIER_RE = re.compile(
    r"(?P<arg>@(?:" + "|".join(_ARG_MODIFIERS) + r")\b"
    r"(?:\s*" + _PAREN_ARG + r")?[^\n@]*?(?=\s*(?:" + ARROW_RE.pattern + r")|@|$))"
    r"|@[a-z][a-z0-9_-]*(?:" + _PAREN_ARG + r")?"
)

# The terminal `: payload` of a flow (not a `:=` alias), up to any `@` left outside
# a `"…"` string.
PAYLOAD_RE = re.compile(r'\s*:(?!=)\s*((?:"[^"]*"|[^@])*?)(?=@|$)')

# Trailing cardinality (`×3`, ` x3`) and stream-bound (`^5`) tokens after a payload:
# modifiers, not payload text (a `×` inside a string or value is left alone).
_PAYLOAD_TAIL_RE = re.compile(r"(?:\s*×\s*\w+|\s+x(?:\d+|N)\b|(?<=[\s>])\^\w+)+\s*$")

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Node:
    id: str
    name: str
    kind: str  # service|data|event|actor|store (+ kinds a dialect adds)
    is_hole: bool = False
    is_mutable: bool = False
    is_stream: bool = False
    layer: str = "L1"
    # Free-form metadata a dialect attaches to the nodes its tokenizers build
    # (core Sigil leaves it empty). See dialects.py NODE_KINDS.
    attrs: dict = field(default_factory=dict)

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
    # Events wired to state-machine transitions by name (top-level graph only).
    triggers: list = field(default_factory=list)
    # Comments attached to nodes (see collect_comments / parse_document).
    notes: list = field(default_factory=list)


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
    node: str                 # node id the comment belongs to
    text: str
    line: int                 # 1-based line of the (first) comment line
    # "block": own-line `#` comments directly above the statement (merged) —
    # about the component the statement is about;
    # "inline": the `#` comment trailing the statement on its own line — about
    # that line, so `edges` holds the (src, dst, kind) of the flows it drew
    # (empty for a line that only places a node, e.g. a branch).
    kind: str = "block"
    edges: tuple = ()


@dataclass
class TreeEntry:
    node: str                 # node id
    parent: Optional[int]     # index into Graph.tree, None for a root
    rel: Optional[str]        # relation char: > & ? $ @ ! = _ (+ any a dialect adds); None for a root
    spawn: bool = False       # `*-` prefix: instances spawned at runtime
    cond: Optional[str] = None  # `{cond}-` guard / source
    depth: int = 0
    weight: Optional[int] = None  # `(N)-` relative share among siblings


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def mk_id(name: str) -> str:
    """Make a Mermaid-safe ID from a glyph name. Lossy: names differing only in
    punctuation (`[a-b]` / `[a_b]`) share an id, so they draw as one node."""
    # Replace non-alphanumeric with underscore, prefix with 'n' if starts with digit
    safe = re.sub(r"[^A-Za-z0-9_]", "_", name.strip())
    if safe and safe[0].isdigit():
        safe = "n" + safe
    return safe or "anon"


def _hook(dialect, name: str, default=()):
    """Read an optional dialect hook (see dialects.py): a callable hook is called,
    a data hook returned as-is, a missing one (or no dialect) gives `default`."""
    if dialect is None:
        return default
    val = getattr(dialect, name, None)
    if val is None:
        return default
    return val() if callable(val) else val


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
    name = m.group("name").strip()
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
    )


# A comment starts at a `#` at line start or after whitespace — not the `#!` mode
# line, and not inside a `"…"` string (`: "issue #5"` is a payload). A `#&…` marker
# also starts here: it is erased from flows like a comment, but it is dialect
# syntax (e.g. a declaration-block opener), not prose, so collect_comments never
# makes a note of it.
_COMMENT_START_RE = re.compile(r"(?<!\S)#(?!!)")


def _in_string(line: str, pos: int) -> bool:
    """Whether `pos` sits inside a closed `"…"` span (an odd number of quotes
    before it and at least one after; an unclosed quote opens no string)."""
    return line.count('"', 0, pos) % 2 == 1 and '"' in line[pos:]


def comment_start(line: str, notes_only: bool = False):
    """The match of the first comment `#` on the line, or None. `notes_only`
    skips `#&` markers (see _COMMENT_START_RE)."""
    for m in _COMMENT_START_RE.finditer(line):
        if _in_string(line, m.start()):
            continue
        if notes_only and line.startswith("&", m.end()):
            continue
        return m
    return None


def strip_comment(line: str) -> str:
    if line.startswith("#!"):
        return line
    m = comment_start(line)
    if m:
        return line[: m.start()]
    return line


def extract_flows(line: str, graph: Graph, layer: str, last_src: Optional[Node],
                  dialect=None, first: Optional[list] = None) -> Optional[Node]:
    """Parse a flow line, add nodes and edges, return the last node (for continuation).
    If `first` is a list, the line's first glyph node is appended to it."""
    stripped = line
    # Dialect line strips first (dialect-only syntax that must not leak as glyphs).
    for strip in _hook(dialect, "render_line_strips"):
        stripped = strip(stripped)
    # Permission-graph access modifiers `@read(…)` / `@write(…)` carry a `( )`
    # comma-list of principal NAMES — these are declarations on a store, not
    # flows, and their members must NOT render as phantom actor glyphs. Strip the
    # modifier + its list first (before the actor-glyph rule sees `(…)`).
    stripped = PERMISSION_SET_RE.sub(" ", stripped)
    # Strip every other modifier with its argument (MODIFIER_RE) — not an `@`
    # inside a `"…"` string (`: "ops@example.com"` is payload text).
    stripped = MODIFIER_RE.sub(
        lambda m, s=stripped: (m.group(0) if _in_string(s, m.start())
                               else " " if m.group("arg") else ""), stripped)
    # Strip `: payload` (but not `:=` aliases) — keeping its text for the edge, less
    # any trailing cardinality / stream-bound modifiers.
    payload = None
    pm = PAYLOAD_RE.search(stripped)
    if pm:
        payload = _PAYLOAD_TAIL_RE.sub("", pm.group(1)).strip() or None
        stripped = stripped[:pm.start()] + " " + stripped[pm.end():]
        stripped = PAYLOAD_RE.sub(" ", stripped)
    # Strip cardinality markers
    stripped = re.sub(r"×\s*\d+|\*\s*\d+\b", "", stripped)
    # Strip stream bound markers `^N...`
    stripped = re.sub(r"\^[a-z0-9]+(@[a-z]+)?", "", stripped, flags=re.IGNORECASE)

    # Tokenize into glyphs and arrows
    tokenizers = list(_hook(dialect, "render_tokenizers"))
    tokens = []
    i = 0
    prev_was_glyph = False
    while i < len(stripped):
        if stripped[i].isspace():
            i += 1
            continue
        # Dialect tokenizers first (extra glyph / operator syntax).
        hit = None
        for tok in tokenizers:
            hit = tok(stripped, i, prev_was_glyph, layer, Node)
            if hit:
                break
        if hit:
            new_tokens, i, prev_was_glyph = hit
            tokens.extend(new_tokens)
            continue
        # Try arrow first
        am = ARROW_RE.match(stripped, i)
        if am:
            tokens.append(("arrow", am.group(0)))
            i = am.end()
            prev_was_glyph = False
            continue
        # Strict join `&` / race `&?` between glyphs (language.md "a & b") groups
        # them into ONE endpoint: `<E> *> [A] & [B]` fans out to both A and B.
        jm = JOIN_RE.match(stripped, i)
        if jm and prev_was_glyph:
            tokens.append(("join", jm.group(0)))
            i = jm.end()
            prev_was_glyph = False
            continue
        # Try glyph
        gm = GLYPH_RE.match(stripped, i)
        if gm:
            node = parse_glyph(stripped[gm.start():gm.end()], layer)
            if node:
                tokens.append(("glyph", node))
            i = gm.end()
            prev_was_glyph = True
            continue
        # Qualified path `[Bullet]/{Transform}`: a `/` glued between two glyphs.
        if (stripped[i] == "/" and prev_was_glyph and i + 1 < len(stripped)
                and stripped[i + 1] in "[{<(|~*"):
            tokens.append(("slash", "/"))
            i += 1
            prev_was_glyph = False
            continue
        i += 1  # skip unrecognized chars
        prev_was_glyph = False

    # Fold `a/b/c` into one reference to `c`, remembering its qualifying path.
    paths = {}                                  # id(node token) -> (name, …, name)
    folded = []
    for kind, tok in tokens:
        if (kind == "glyph" and len(folded) > 1 and folded[-1][0] == "slash"
                and folded[-2][0] == "glyph"):
            folded.pop()
            _, prev = folded.pop()
            paths[id(tok)] = paths.pop(id(prev), (prev.name,)) + (tok.name,)
        folded.append((kind, tok))
    tokens = [t for t in folded if t[0] != "slash"]

    if not any(t[0] == "glyph" for t in tokens):
        return last_src

    # Every hole is its own node: `[?] -> [X]` and `[?] -> [Y]` are two unknowns.
    for kind, tok in tokens:
        if kind == "glyph" and tok.is_hole:
            graph.hole_seq[0] += 1
            tok.id = f"{tok.id}{graph.hole_seq[0]}"

    # Group the line into endpoints separated by arrows. A `&`/`&?` join extends
    # the current endpoint; two glyphs with no operator between them are separate
    # endpoints with no edge (None). A continuation line (leading arrow) inherits
    # last_src as its first endpoint.
    if first is not None:
        first.append(next(t[1] for t in tokens if t[0] == "glyph"))
    groups: list = []
    links: list = []          # links[k] joins groups[k] -> groups[k+1]
    cur: Optional[list] = None
    pending = None            # the arrow awaiting a destination
    joining = False
    if tokens[0][0] == "arrow" and last_src is not None:
        cur = [last_src]
    for kind, tok in tokens:
        if kind == "arrow":
            if cur is not None:
                groups.append(cur)
                cur = None
                pending = tok
            joining = False
        elif kind == "join":
            joining = True
        else:
            if cur is not None and joining:
                cur.append(tok)
            else:
                if cur is not None:        # adjacent glyphs, no operator
                    groups.append(cur)
                    pending = None
                if groups:
                    links.append(pending)
                cur = [tok]
                pending = None
            joining = False
    if cur is not None:
        groups.append(cur)

    for group in groups:
        for n in group:
            graph.nodes.setdefault(n.id, n)

    # Fan every arrow out across both endpoints (`[A] & [B] -> [C] & [D]` is 4 edges).
    new_edges = []
    for k, arrow in enumerate(links):
        if arrow is None:
            continue
        for s in groups[k]:
            for d in groups[k + 1]:
                new_edges.append(Edge(src=s.id, dst=d.id, kind=arrow,
                                      src_path=paths.get(id(s)), dst_path=paths.get(id(d))))
    if payload:
        for e in new_edges:
            if any(e.dst == n.id for n in groups[-1]):
                e.payload = payload
    graph.edges.extend(new_edges)

    return groups[-1][-1]


# Multiline block-string delimiter — a `str` literal's
# triple-quoted multiline form `"""…"""` (language.md "Multiline block-strings").
BLOCK_DELIM = '"""'


def collapse_block_strings(lines: list) -> list:
    """Fold each `\"\"\"…\"\"\"` multiline block-string into a single masked STR
    (`"block-string"`) on its opening line, blanking the consumed body lines.
    Mirrors lint.py's pre-pass so render is block-aware for this one token: the
    block is a payload VALUE, so the masked `"…"` is removed by the `: payload`
    strip in extract_flows and leaves NO phantom node (the slot/component still
    renders). An unterminated block simply blanks to EOF (lint flags it; render
    renders nothing for it). Line numbering is preserved."""
    out = list(lines)
    n = len(out)
    i = 0
    while i < n:
        raw = out[i]
        if raw.lstrip().startswith("#!"):
            i += 1
            continue
        pos = raw.find(BLOCK_DELIM)
        if pos == -1:
            i += 1
            continue
        cm = comment_start(raw)
        if cm and cm.start() < pos:   # the `"""` is comment text, not a delimiter
            i += 1
            continue
        prefix = raw[:pos]
        after_open = raw[pos + len(BLOCK_DELIM):]
        close_rel = after_open.find(BLOCK_DELIM)
        if close_rel != -1:           # degenerate single-line `"""…"""`
            out[i] = prefix + '"block-string"' + after_open[close_rel + len(BLOCK_DELIM):]
            i += 1
            continue
        j = i + 1
        while j < n and BLOCK_DELIM not in out[j]:
            j += 1
        if j >= n:                    # unterminated — blank from the opener (lint reports it)
            for k in range(i, n):
                out[k] = ""
            break
        suffix = out[j][out[j].find(BLOCK_DELIM) + len(BLOCK_DELIM):]
        out[i] = prefix + '"block-string"' + suffix
        for k in range(i + 1, j + 1):
            out[k] = ""
        i = j + 1
    return out


# Section header `-- L2: Name --` (the layer is optional).
SECTION_RE = re.compile(r"^-{2,}\s*(L\d+)?\s*:?\s*(.+?)\s*-{2,}\s*$")

# `name := expr`, `[name] := expr` or `{name} := expr` — a definition, not a flow.
ALIAS_RE = re.compile(
    r"^(?:\[(?P<svc>[^\]]+)\]|\{(?P<data>[^}]+)\}|(?P<word>[A-Za-z_][\w.]*))"
    r"\s*:=\s*(?P<rhs>.*)$"
)

# An alias right-hand side that opens an expansion block: a bare `{` (`X := {`,
# `X := { [A] -> [B] }`) — not a data glyph (`X := {Summary} cache` is an alias).
EXPANSION_OPEN_RE = re.compile(r"\{(\s|$)")
BLOCK_OPEN_RE = re.compile(r"\{(?=\s|$)")

# A state-machine header: `state <glyph> {` — any glyph owns the machine (`{Order}`
# a record's lifecycle, `[Checkout]` a component's own modes). STATE_OPEN_RE also
# takes a malformed header (no owner glyph), whose block is consumed unparsed.
STATE_HEAD_RE = re.compile(r"^state\s*([~*]*[\[{<(|][^\[\]{}<>()|]+[\]}>)|])\s*\{")
STATE_OPEN_RE = re.compile(r"^state\s*\{")

# A transition inside a `state` block: `Src -<trigger>-> Dst` or `Src -> Dst`,
# optionally followed by per-transition modifiers (`×3`, `@timeout(…)`, …).
TRANSITION_RE = re.compile(r"^(\S+)\s+(?:-<([^<>]*)>->|->)\s+(\S+)\s*(.*)$")
PSEUDO_STATES = {"+": "start", "$": "end", "_": "any"}

# A control block header: its statements are ordinary flows.
LOOP_HEAD_RE = re.compile(r"^(loop|parallel|branch)\b")

# A composition-tree branch marker: `\\-` [`*-` spawn] [`(N)-` weight | `{cond}-`]
# <rel>, or a bare spawn `\\-*`. Core relations are `> & ? $ @ ! = _`; the parser
# accepts the wider punctuation set so a dialect's extra relations still place in
# the tree (lint decides which relations are valid).
BRANCH_RE = re.compile(
    r"\\-(?:(?P<spawn>\*)-)?(?:\((?P<weight>\d+)\)-|\{(?P<cond>[A-Za-z0-9_-]+)\}-)?"
    r"(?P<rel>[>+#_^v$?!&@=])(?=\s|$)"
    r"|\\-(?P<bare_spawn>\*)(?=\s|$)"
)

# What may precede an inline branch (`[parent] \\-& [child]`): glyphs only — no
# payload colon, no prose.
_BRANCH_PARENT_RE = re.compile(r"^\s*[~*]?[\[{<(|][^:]*[\]}>)|]\s*$")

# Core glyph kinds (OPEN_TO_KIND); any other kind is a dialect's.
_CORE_KINDS = set(OPEN_TO_KIND.values())


def _close_at(text: str, depth: int) -> Optional[int]:
    """Index of the `}` in `text` that closes a block open `depth` deep where the
    text starts, or None when the block stays open past it."""
    for i, ch in enumerate(text):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth <= 0:
                return i
    return None


class _DocParser:
    """parse_document's line-by-line state — one instance per document (and per
    `:= { … }` sub-document). Handlers named `_on_*` take a line and return True
    when it was theirs; `_in_*` continue a block being collected."""

    def __init__(self, hole_seq: Optional[list], dialect):
        self.graph = Graph()
        if hole_seq is not None:
            self.graph.hole_seq = hole_seq
        self.top = hole_seq is None
        self.dialect = dialect
        self.layer = "L1"
        self.last_src = None
        # `X := { … }` expansions and `state` machines, resolved once the whole
        # document is read so one written BEFORE its node's first use still attaches.
        self.pending_expansions = []   # (target_name, target_kind, sub_graph)
        self.pending_states = []       # (owner Node, state graph)
        # Blocks being collected. Expansion: [target_name, target_kind, raw lines,
        # brace depth]; state: [owner Node | None, lines, brace depth]; loop: its
        # brace depth (None outside one); declaration: [(regex, on_raw), depth].
        self.expansion = None
        self.state = None
        self.loop_depth = None
        self.decl = None
        self.decl_blocks = list(_hook(dialect, "DECLARATION_BLOCKS"))
        # Composition tree state: open branches as (column, tree index), and the last
        # plain glyph line a branch could hang under: [column, node id, tree index|None].
        self.tree_stack: list = []
        self.tree_root: Optional[list] = None
        # Notes: the node the current line is "about", the document's comments, and
        # own-line comments waiting for the statement below.
        self.anchor = None
        self.comments: dict = {}
        self.above: list = []

    # -- driver ---------------------------------------------------------------

    def parse(self, text: str) -> Graph:
        # Pre-pass: fold multiline `"""…"""` block-strings to masked single-line STRs
        # so the block body never emits phantom nodes (block-aware for this token).
        # Then any dialect pre-passes (line-count preserving).
        lines = collapse_block_strings(text.splitlines())
        self.comments = collect_comments(lines, self.dialect)   # before dialect pre-passes
        for prepass in _hook(self.dialect, "render_prepasses"):
            lines = prepass(lines)
        for k, raw in enumerate(lines):
            self.line(k, raw)
        return self.finish()

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
                self.above.append((c[0], k + 1))
                return
            if not line:                    # a blank line detaches waiting comments
                self.above.clear()
        if self._on_declaration(raw_lead, line) or self._on_section(line):
            return
        if line.startswith("#!") or not line:
            return
        if self.state is not None:
            self._in_state(line)
        elif not (self._on_alias(k, line) or self._on_state_head(k, line)
                  or self._on_loop_head(k, stripped, line)):
            self._on_flow(k, stripped, line)

    def finish(self) -> Graph:
        graph = self.graph
        for name, kind, sub_graph in self.pending_expansions:
            # The node of that name AND kind (`[Order] := …` is not `{Order}`); a
            # dialect-kind node of the name also qualifies (its tokenizer may own
            # the glyph). A bare `name :=` takes the first node of the name.
            target_id = mk_id(name + "_" + kind) if kind is not None else None
            if target_id not in graph.nodes:
                target_id = next((nid for nid, n in graph.nodes.items()
                                  if n.name == name and (kind is None or n.kind == kind
                                                         or n.kind not in _CORE_KINDS)),
                                 None)
            if target_id is None and kind is not None:
                # Defined but never referenced in a flow — still a node of the design.
                target_id = mk_id(name + "_" + kind)
                graph.nodes[target_id] = Node(id=target_id, name=name,
                                              kind=kind, layer=self.layer)
            if target_id:
                graph.expansions[target_id] = sub_graph

        for owner, machine in self.pending_states:
            graph.nodes.setdefault(owner.id, owner)
            home = graph.expansions.get(owner.id)
            if home is None:
                graph.expansions[owner.id] = machine
            else:
                # The owner also has a `:=` expansion: the machine hangs inside it.
                mid = owner.id + "_machine"
                home.nodes.setdefault(mid, Node(id=mid, name="states", kind="state"))
                home.expansions[mid] = machine

        if self.top:                        # top level: wire events to transitions
            graph.triggers = find_triggers(graph)
        return graph

    # -- helpers --------------------------------------------------------------

    def _sub_parse(self, text: str) -> Graph:
        return parse_document(text, self.graph.hole_seq, self.dialect)

    def _delta(self, raw_lead: str, line: str) -> int:
        """Net braces a line opens. A raw-matched declaration opener (a `#…` marker,
        erased by comment stripping) counts on the raw line, as _on_declaration does."""
        if any(on_raw and rx.match(raw_lead) for rx, on_raw in self.decl_blocks):
            line = raw_lead
        return line.count("{") - line.count("}")

    def attach(self, node_id, k: int, edges: tuple = ()):
        if node_id and self.above:
            self.graph.notes.append(Note(node_id, " ".join(t for t, _ln in self.above),
                                         self.above[0][1], "block"))
        trailing = self.comments.get(k)
        if node_id and trailing and not trailing[1]:
            self.graph.notes.append(Note(node_id, trailing[0], k + 1, "inline", edges))
        self.above.clear()

    def add_entry(self, node_id, parent, rel=None, spawn=False, cond=None, weight=None):
        depth = self.graph.tree[parent].depth + 1 if parent is not None else 0
        self.graph.tree.append(TreeEntry(node_id, parent, rel, spawn, cond, depth, weight))
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
        # body recursively.
        cut = _close_at(stripped, before)
        last = stripped[:cut] if cut is not None else stripped
        if last.strip():
            exp[2].append(last)
        self.pending_expansions.append((exp[0], exp[1], self._sub_parse("\n".join(exp[2]))))
        self.expansion = None

    def _on_declaration(self, raw_lead: str, line: str) -> bool:
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
                self.decl = [(opener, on_raw), depth] if depth > 0 else None
                self.last_src = None
                return True
        return False

    def _on_section(self, line: str) -> bool:
        sec = SECTION_RE.match(line)
        if not sec:
            return False
        self.above.clear()
        if sec.group(1):
            self.layer = sec.group(1)
        if self.layer not in self.graph.layers:
            self.graph.layers.append(self.layer)
        self.last_src = None
        return True

    def _on_alias(self, k: int, line: str) -> bool:
        """Aliases — `name := expr` or `[name] := expr` — are definitions, not flows:
        draw nothing. An `X := { … }` expansion is collected for a recursive parse."""
        am = ALIAS_RE.match(line)
        if not am:
            return False
        name = am.group("svc") or am.group("data") or am.group("word")
        kind = ("service" if am.group("svc") is not None
                else "data" if am.group("data") is not None else None)
        rhs = am.group("rhs").strip()
        if EXPANSION_OPEN_RE.match(rhs):
            body = rhs[1:]
        elif rhs.endswith("{"):
            body = ""
        else:
            return True                     # a simple alias — skip for rendering
        if kind:
            self.attach(mk_id(name + "_" + kind), k)
        cut = _close_at(body, 1)
        if cut is not None:
            # One-line expansion `[X] := { … }`: its body is right here.
            self.pending_expansions.append((name, kind, self._sub_parse(body[:cut])))
        else:
            self.expansion = [name, kind, [body] if body.strip() else [],
                              1 + body.count("{") - body.count("}")]
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
            self.state = [None, [], depth] if depth > 0 else None
            return True
        owner = parse_glyph(sm.group(1), self.layer, self.dialect)
        self.attach(owner.id if owner else None, k)
        body = line[sm.end():]
        cut = _close_at(body, 1)
        if cut is not None:
            # One-line `state {X} { A -> B }`.
            if owner and body[:cut].strip():
                self.pending_states.append(
                    (owner, parse_state_block([body[:cut]], owner.name)))
        else:
            self.state = [owner, [body.strip()] if body.strip() else [],
                          1 + body.count("{") - body.count("}")]
        return True

    def _in_state(self, line: str):
        st = self.state
        before = st[2]
        st[2] += line.count("{") - line.count("}")
        if st[2] > 0:
            st[1].append(line)
            return
        cut = _close_at(line, before)
        if cut is not None and line[:cut].strip():
            st[1].append(line[:cut].strip())   # a last transition before the `}`
        if st[0]:
            self.pending_states.append((st[0], parse_state_block(st[1], st[0].name)))
        self.state = None

    def _on_loop_head(self, k: int, stripped: str, line: str) -> bool:
        """`loop` / `parallel` / `branch` headers draw nothing; the statements of the
        block are ordinary flows. A nested header deepens the open block."""
        if not LOOP_HEAD_RE.match(line):
            return False
        delta = line.count("{") - line.count("}")
        nested = self.loop_depth is not None
        self.loop_depth = (self.loop_depth if nested else 0) + delta
        om = BLOCK_OPEN_RE.search(stripped)     # not a `{X}` glyph or `${ref}` in the header
        if om:                              # statements after the header's `{`
            open_at = om.start()
            body = stripped[open_at + 1:]
            cut = _close_at(body, 1)
            if body[:cut].strip():
                self._flow_line(k, body[:cut], open_at + 1)
            if cut is not None and not nested and self.loop_depth <= 0:
                self.loop_depth = None      # a one-line block `loop { … }`
        return True

    def _on_flow(self, k: int, stripped: str, line: str):
        if self.loop_depth is not None:
            before = self.loop_depth
            self.loop_depth += line.count("{") - line.count("}")
            if self.loop_depth <= 0:        # the line closes the block
                self.loop_depth = None
                cut = _close_at(stripped, before)
                if cut is not None:
                    if stripped[:cut].strip():
                        self._flow_line(k, stripped[:cut], 0)
                    return
        self._flow_line(k, stripped, 0)

    # -- flows ----------------------------------------------------------------

    def _flow_line(self, k: int, text: str, offset: int):
        """Flow the statement `text` (found at column `offset`) and attach the
        waiting comments to the node it is about."""
        self.anchor = None
        col = offset + len(text) - len(text.lstrip())
        before = len(self.graph.edges)
        self.last_src = self._flow(text.strip(), col, self.last_src)
        drawn = tuple(dict.fromkeys((e.src, e.dst, e.kind) for e in self.graph.edges[before:]
                                    if e.src != e.dst))
        self.attach(self.anchor, k, drawn)

    def _flow(self, text: str, col: int, last):
        """One flow line; composition branches (`\\-<rel>`) become tree entries."""
        graph, dialect = self.graph, self.dialect
        m = BRANCH_RE.search(text)
        if m is not None and m.start() > 0 and not _BRANCH_PARENT_RE.match(text[:m.start()]):
            m = None                         # a marker inside prose / a payload, not a branch
        if m is None:
            cap: list = []
            last = extract_flows(text, graph, self.layer, last, dialect, first=cap)
            if cap:
                self.tree_stack = [t for t in self.tree_stack if t[0] < col]
                self.tree_root = [col, cap[0].id, None]
                self.anchor = cap[0].id
            return last
        left, rest = text[:m.start()], BRANCH_RE.sub(" ", text[m.end():])
        bcol = m.start() + col
        if left.strip():                     # inline: `[parent] \\-& [child]`
            cap = []
            last = extract_flows(left, graph, self.layer, last, dialect, first=cap)
            self.tree_stack = [t for t in self.tree_stack if t[0] < col]
            if cap:
                self.tree_root = [col, cap[0].id, None]
        stack = self.tree_stack
        while stack and stack[-1][0] >= bcol:
            stack.pop()
        parent = stack[-1][1] if stack else None
        root = self.tree_root
        if parent is None and root is not None and root[0] < bcol:
            if root[2] is None:
                root[2] = self.add_entry(root[1], None)
            parent = root[2]
            stack.append((root[0], parent))
        cap = []
        last = extract_flows(rest, graph, self.layer, last, dialect, first=cap)
        if cap:
            spawn = bool(m.group("spawn") or m.group("bare_spawn"))
            rel = m.group("rel") or ("*" if m.group("bare_spawn") else None)
            weight = int(m.group("weight")) if m.group("weight") else None
            idx = self.add_entry(cap[0].id, parent, rel, spawn, m.group("cond"), weight)
            stack.append((bcol, idx))
            self.anchor = cap[0].id
        return last


def parse_document(text: str, _hole_seq: Optional[list] = None, dialect=None) -> Graph:
    """Parse a Sigil document into a Graph structure. `dialect` is a loaded
    dialect (dialects.load) or None for core Sigil. `_hole_seq` is internal: a
    sub-document (an expansion body) shares its parent's hole counter."""
    return _DocParser(_hole_seq, dialect).parse(text)


def _walk(g, owner=None, level=0):
    """(graph, owning node id, nesting level) for g and every nested graph."""
    yield g, owner, level
    for nid, sub in g.expansions.items():
        yield from _walk(sub, nid, level + 1)


def collect_comments(lines: list, dialect=None) -> dict:
    """{line index: (text, own_line)} for every comment. Core comments start with
    `#` (not the `#!` mode line, nor a `#&` marker — see _COMMENT_START_RE); a
    dialect may add markers (COMMENT_MARKERS, regex sources matched at line start
    or after whitespace). A marker inside a `"…"` string starts no comment."""
    extra = list(_hook(dialect, "COMMENT_MARKERS"))
    marker = (re.compile(r"(?:^|(?<=\s))(?:" + "|".join(extra) + ")") if extra else None)
    out = {}
    for k, line in enumerate(lines):
        if line.lstrip().startswith(("#!", "#&")):
            continue
        hits = [comment_start(line, notes_only=True)]
        if marker:
            hits.append(next((h for h in marker.finditer(line)
                              if not _in_string(line, h.start())), None))
        hits = [h for h in hits if h]
        if not hits:
            continue
        m = min(hits, key=lambda h: h.start())
        text = line[m.end():].strip()
        if text:
            out[k] = (text, not line[:m.start()].strip())
    return out


def find_triggers(graph: Graph) -> list:
    """An event glyph whose name matches a transition's trigger (`-<Paid>->`,
    case-insensitive) IS that trigger: one Trigger per (event, transition)."""
    events = {}
    for g, _o, _l in _walk(graph):
        for n in g.nodes.values():
            if n.kind == "event" and not n.is_hole:
                events.setdefault(n.name.lower(), n.id)
    # Narrowing: an event with explicit flows into state-machine owners drives only
    # those owners' machines; without such flows it drives every matching machine.
    owners = {owner for g, owner, _l in _walk(graph) if g.role == "state"}
    aimed = {}
    for g, _o, _l in _walk(graph):
        for e in g.edges:
            if e.dst in owners:
                aimed.setdefault(e.src, set()).add(e.dst)
    out = []
    for g, owner, level in _walk(graph):
        if g.role != "state":
            continue
        for e in g.edges:
            key = (e.label or "")[1:-1].lower()
            if key in events:
                ev = events[key]
                if ev in aimed and owner not in aimed[ev]:
                    continue
                out.append(Trigger(ev, owner, e.src, e.dst, e.label, level))
    return out


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
        m = TRANSITION_RE.match(line.strip())
        if not m:
            continue
        src, trigger, dst, rest = m.groups()
        a, b = node(src), node(dst)
        label = f"<{trigger}>" if trigger else None
        rest = rest.strip()
        g.edges.append(Edge(src=a.id, dst=b.id, kind="->", label=label,
                            payload=rest or None))
    return g


# ---------------------------------------------------------------------------
# Mermaid emission
# ---------------------------------------------------------------------------

NODE_SHAPE = {
    "service":   ("[", "]"),         # rectangle
    "data":      ("{{", "}}"),       # hexagon
    "event":     (">", "]"),         # asymmetric (flag)
    "actor":     ("((", "))"),       # circle
    "store":     ("[(", ")]"),       # cylinder
    "state":     ("([", "])"),       # stadium — a state of a `state {X}` machine
}

_CORE_CLASSDEFS = [
    "classDef service fill:#E3F2FD,stroke:#1976D2,color:#0D47A1",
    "classDef data    fill:#F3E5F5,stroke:#7B1FA2,color:#4A148C",
    "classDef event   fill:#FFF3E0,stroke:#F57C00,color:#E65100",
    "classDef actor   fill:#E8F5E9,stroke:#388E3C,color:#1B5E20",
    "classDef store   fill:#FFF9C4,stroke:#F9A825,color:#F57F17",
    "classDef state   fill:#E0F2F1,stroke:#00897B,color:#004D40",
]
_STYLE_CLASSDEFS = [
    "classDef hole    stroke-dasharray:5 5,opacity:0.7",
    "classDef mutable stroke-width:3px",
]


def _node_kinds(dialect=None) -> dict:
    return _hook(dialect, "NODE_KINDS", {}) or {}


def _class_def(dialect=None) -> str:
    extra = [f"classDef {k['mermaid_class']} {k['classdef']}"
             for k in _node_kinds(dialect).values()
             if k.get("mermaid_class") and k.get("classdef")]
    return "\n".join("    " + ln for ln in _CORE_CLASSDEFS + extra + _STYLE_CLASSDEFS)


def _kind_classes(dialect=None) -> dict:
    """Node kind → Mermaid class: the core kinds, then each dialect kind's
    `mermaid_class` (default: the kind's own name)."""
    kinds = {k: k for k in NODE_SHAPE}
    for kind, spec in _node_kinds(dialect).items():
        kinds[kind] = spec.get("mermaid_class", kind)
    return kinds


def mermaid_text(text: str) -> str:
    """Text safe inside a Mermaid `"…"` label: `<` / `>` / `"` as HTML entities."""
    return text.replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def node_label(n: Node, dialect=None) -> str:
    """The plain-text label of a node: its name, or what the dialect's NODE_KINDS
    `label` callable makes of it (e.g. appending metadata from `n.attrs`)."""
    spec = _node_kinds(dialect).get(n.kind) or {}
    fn = spec.get("label")
    if fn:
        return fn(n)
    return {"start": "●", "end": "◉", "any": "∗ any"}.get(n.attrs.get("pseudo"), n.name)


def emit_node(n: Node, indent: str = "    ", dialect=None) -> str:
    spec = _node_kinds(dialect).get(n.kind)
    if spec is not None:
        open_shape, close_shape = spec["mermaid_shape"]
    else:
        open_shape, close_shape = NODE_SHAPE[n.kind]
    label = mermaid_text(node_label(n, dialect))
    if n.is_stream:
        label = f"*{label}"
    if n.is_mutable:
        label = f"~{label}"
    return f'{indent}{n.id}{open_shape}"{label}"{close_shape}'


def emit_edge(e: Edge, indent: str = "    ", dialect=None) -> str:
    arrow = ARROW_MAP.get(e.kind) or _hook(dialect, "RENDER_ARROWS", {}).get(e.kind, "-->")
    if e.label:
        arrow = _labelled(arrow, mermaid_text(e.label))
    return f"{indent}{e.src} {arrow} {e.dst}"


def _labelled(arrow: str, label: str) -> str:
    """A Mermaid arrow carrying `label`: joined to the label an arrow already has
    (`-- "!" -->`), written into a `-->` (`-- "x" -->`), else in pipes (`-.->|"x"|`)."""
    m = re.fullmatch(r'(\S+) "([^"]*)" (\S+)', arrow)
    if m:
        return f'{m.group(1)} "{m.group(2)} {label}" {m.group(3)}'
    if "-->" in arrow:
        return arrow.replace("-->", f'-- "{label}" -->', 1)
    return f'{arrow}|"{label}"|'



def emit_classes(graph: Graph, indent: str = "    ", dialect=None) -> list:
    lines = []
    for kind, cls in _kind_classes(dialect).items():
        ids = [n.id for n in graph.nodes.values() if n.kind == kind]
        if ids:
            lines.append(f"{indent}class {','.join(ids)} {cls}")
    holes = [n.id for n in graph.nodes.values() if n.is_hole]
    if holes:
        lines.append(f"{indent}class {','.join(holes)} hole")
    mutables = [n.id for n in graph.nodes.values() if n.is_mutable]
    if mutables:
        lines.append(f"{indent}class {','.join(mutables)} mutable")
    return lines


REL_WORD = {">": "contains", "&": "has", "?": "when", "$": "from data", "@": "attached",
            "!": "alerts", "=": "gathers", "_": "one of"}


def rel_word(t) -> str:
    """A tree entry's relation as words: `spawns`, `has`, `(3) contains`, …"""
    word = REL_WORD.get(t.rel or ">", t.rel or "contains")
    if t.spawn:
        word = "spawns" if word == "contains" else f"spawns, {word}"
    if t.weight is not None:
        word = f"({t.weight}) {word}"
    if t.cond:
        word = f"{{{t.cond}}} {word}"
    return word


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


def emit_graph(graph: Graph, depth: int = 1, indent: str = "    ", depth_so_far: int = 0,
               dialect=None, composition: str = "none") -> str:
    if composition == "subgraphs" and graph.tree:
        return _emit_composed(graph, depth, indent, depth_so_far, dialect)
    body = _emit_flat(graph, depth, indent, depth_so_far, dialect, composition)
    if composition == "edges":
        extra = []
        for t in graph.tree:
            if t.parent is not None:
                extra.append(f'{indent}{graph.tree[t.parent].node} -. "{rel_word(t)}" .-> {t.node}')
        body += ("\n" + "\n".join(dict.fromkeys(extra))) if extra else ""
    return body


def _emit_composed(graph: Graph, depth: int, indent: str, depth_so_far: int, dialect) -> str:
    """Composition as subgraphs: one Mermaid node per occurrence; flows fan out to
    every occurrence of a bare name, or to the path-matching ones."""
    occ = occurrences(graph)
    kids = {}
    for i, t in enumerate(graph.tree):
        kids.setdefault(t.parent, []).append(i)
    in_tree = {t.node for t in graph.tree}
    lines, class_of = [], {}
    shown_internals = set()

    def node_line(oid, n, ind):
        return emit_node(n, ind, dialect).replace(f"{ind}{n.id}", f"{ind}{oid}", 1)

    def emit_occ(i, ind):
        oid, _chain = occ[i]
        n = graph.nodes[graph.tree[i].node]
        expand = (n.id in graph.expansions and depth_so_far < depth
                  and n.id not in shown_internals)
        if kids.get(i) or expand:
            lines.append(f'{ind}subgraph {oid}["{mermaid_text(node_label(n, dialect))}"]')
            lines.append(f"{ind}    direction TB")
            if expand:
                shown_internals.add(n.id)
                lines.append(f'{ind}    subgraph {oid}__internals["internals"]')
                lines.append(emit_graph(graph.expansions[n.id], depth, ind + "        ",
                                        depth_so_far + 1, dialect, "subgraphs"))
                lines.append(f"{ind}    end")
            for c in kids.get(i, []):
                emit_occ(c, ind + "    ")
            lines.append(f"{ind}end")
        else:
            lines.append(node_line(oid, n, ind))
        class_of[oid] = n

    # Nodes outside every tree, then the trees (roots in document order).
    rest = Graph(nodes={k: v for k, v in graph.nodes.items() if k not in in_tree},
                 expansions={k: v for k, v in graph.expansions.items() if k not in in_tree})
    flat = _emit_flat(rest, depth, indent, depth_so_far, dialect, "subgraphs",
                      with_edges=False, with_classes=False)
    if flat:
        lines.append(flat)
    for i in kids.get(None, []):
        emit_occ(i, indent)

    def ends(nid, path):
        return matching_occurrences(graph, occ, nid, path) if nid in in_tree else [nid]

    for e in graph.edges:
        for s in ends(e.src, e.src_path):
            for d in ends(e.dst, e.dst_path):
                lines.append(emit_edge(Edge(src=s, dst=d, kind=e.kind, label=e.label),
                                       indent, dialect))
    # Classes: nodes outside the trees as usual, occurrences by their node's kind.
    lines += emit_classes(rest, indent, dialect)
    by_cls = {}
    kinds = _kind_classes(dialect)
    for oid, n in class_of.items():
        by_cls.setdefault(kinds.get(n.kind, n.kind), []).append(oid)
        if n.is_hole:
            by_cls.setdefault("hole", []).append(oid)
        if n.is_mutable:
            by_cls.setdefault("mutable", []).append(oid)
    for cls, ids in by_cls.items():
        lines.append(f"{indent}class {','.join(ids)} {cls}")
    return "\n".join(lines)


def _emit_flat(graph: Graph, depth: int = 1, indent: str = "    ", depth_so_far: int = 0,
               dialect=None, composition: str = "none", with_edges: bool = True,
               with_classes: bool = True) -> str:
    """Emit Mermaid for a graph, recursively expanding up to `depth` levels.

    When a node has an expansion being rendered, it's emitted as a subgraph
    instead of a flat node — edges automatically route to the subgraph boundary.
    """
    lines = []
    expanded_ids = set()

    # First pass: figure out which nodes are being expanded
    for node in graph.nodes.values():
        if depth_so_far < depth and node.id in graph.expansions:
            expanded_ids.add(node.id)

    # Emit nodes — flat ones first, subgraphs after
    for node in graph.nodes.values():
        if node.id in expanded_ids:
            continue  # will be emitted as subgraph below
        lines.append(emit_node(node, indent, dialect))

    # Emit subgraphs for expanded nodes
    for node in graph.nodes.values():
        if node.id not in expanded_ids:
            continue
        sub = graph.expansions[node.id]
        lines.append(f'{indent}subgraph {node.id}["{mermaid_text(node_label(node, dialect))}"]')
        lines.append(f"{indent}    direction TB")
        # Recurse into sub with incremented depth_so_far (only render() adds the
        # classDef footer, once).
        lines.append(emit_graph(sub, depth, indent + "    ", depth_so_far + 1, dialect,
                                composition))
        lines.append(f"{indent}end")

    # Emit edges at this level
    if with_edges:
        for edge in graph.edges:
            lines.append(emit_edge(edge, indent, dialect))

    # Emit classes at this level
    if with_classes:
        for cls_line in emit_classes(graph, indent, dialect):
            lines.append(cls_line)

    return "\n".join(lines)


def render(text: str, depth: int = 1, dialect=None, composition: Optional[str] = None) -> str:
    """Mermaid for a document. `composition`: "subgraphs" (default — composition
    trees as nested subgraphs, one node per occurrence), "edges" (one node per name,
    dotted relation edges), or "none"; a dialect may change the default
    (MERMAID_COMPOSITION)."""
    if composition is None:
        composition = _hook(dialect, "MERMAID_COMPOSITION", "subgraphs")
    graph = parse_document(text, dialect=dialect)
    body = emit_graph(graph, depth=depth, dialect=dialect, composition=composition)
    in_tree = {t.node for t in graph.tree} if composition == "subgraphs" else set()
    occ = occurrences(graph) if in_tree else []
    wires = []
    for t in graph.triggers:
        # Into the state the transition enters when its machine is drawn, else
        # into the machine's owner (its first occurrence when it sits in a tree);
        # from every drawn occurrence of the event, as flows are.
        dst = t.dst if t.level <= depth else t.owner
        if dst in in_tree:
            dst = matching_occurrences(graph, occ, dst, None)[0]
        srcs = (matching_occurrences(graph, occ, t.event, None) if t.event in in_tree
                else [t.event])
        wires += [f'\n    {src} -. "triggers" .-> {dst}' for src in srcs]
    body += "".join(wires)
    return f"flowchart TD\n{body}\n\n{_class_def(dialect)}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _load_dialect(spec):
    """Load a dialect via the sibling dialects.py (path-loaded; stdlib only)."""
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parent / "dialects.py"
    sp = importlib.util.spec_from_file_location("sigil_dialects", path)
    mod = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(mod)
    return mod.load(spec)


# `--depth all`: deeper than any document nests.
ALL_DEPTH = 99


def _depth_arg(value: str) -> int:
    """argparse type for --depth: a non-negative number, or `all`."""
    import argparse
    if value == "all":
        return ALL_DEPTH
    try:
        depth = int(value)
    except ValueError:
        depth = -1
    if depth < 0:
        raise argparse.ArgumentTypeError(f"expected a number >= 0 or 'all', got {value!r}")
    return depth


def main(argv=None, default_dialect=None):
    import argparse
    ap = argparse.ArgumentParser(prog="render.py",
                                 description="Render a Sigil document as Mermaid.")
    ap.add_argument("file", help="a .sigil file, or - for stdin")
    ap.add_argument("--depth", type=_depth_arg, default=1,
                    help="expansion depth (N or 'all')")
    ap.add_argument("--composition", choices=("subgraphs", "edges", "none"), default=None,
                    help="composition trees as nested subgraphs (default), dotted "
                         "relation edges, or not at all")
    ap.add_argument("--dialect", default=default_dialect,
                    help="dialect name or path (default: $SIGIL_DIALECT)")
    a = ap.parse_args(argv)
    try:
        dialect = _load_dialect(a.dialect)
    except ValueError as exc:
        print(f"render.py: {exc}", file=sys.stderr)
        sys.exit(2)

    if a.file == "-":
        text = sys.stdin.read()
    else:
        with open(a.file, "r", encoding="utf-8") as f:
            text = f.read()

    print(render(text, depth=a.depth, dialect=dialect, composition=a.composition))


if __name__ == "__main__":
    main()
