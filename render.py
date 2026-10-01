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
    an alias `name := …` (a bare-word definition) → subroutine, grey

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
    branch arm                dotted, labelled with the arm, from the `branch on X`
                              glyph to the arm's first node
    `-> run()`                a self-edge labelled with the op it runs

The parsed model (parse_document → Graph) is described under "THE MODEL" below.
"""

import sys
import re
from dataclasses import dataclass, field, replace
from typing import NamedTuple, Optional

# ---------------------------------------------------------------------------
# Glyph parsing
# ---------------------------------------------------------------------------

# A glyph's name may carry generics (language.md "Parametric"): `[Cache<K,V>]`,
# `{List<T>}`, `<Msg<T>>` — one level of nesting inside the generic list
# (`{List<Map<K,V>>}`). The generic is part of the ONE glyph's name.
_NAME_CHARS = r"[^\[\]\{\}<>()|]"
_GENERIC = (r"<" + _NAME_CHARS + r"*(?:<" + _NAME_CHARS + r"*>" + _NAME_CHARS + r"*)*>")
GLYPH_RE = re.compile(
    r"(?P<mut>~)?(?P<stream>\*)?"
    r"(?P<open>[\[\{<\(\|])"
    r"(?P<name>" + _NAME_CHARS + r"+(?:" + _GENERIC + r")?)"
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
_PAYLOAD_TAIL_RE = re.compile(r"(?:\s*×\s*\w+|\s+x(?:\d+|N)\b|(?<=[\s>])\^\w+|\s+!(?![>=]))+\s*$")

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
#
# THE MODEL — what parse_document returns, and what every consumer reads.
#
# One Graph per document; one more per `X := { … }` expansion / alias body /
# `state` machine, hung off the node it expands (Graph.expansions). The Graph is
# the single source of truth for every presentation (Mermaid here, the terminal
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
#               the node (see "Modifiers").
#   edges       [Edge] in document order: one per (source, target) pair a flow
#               statement draws. `[A] & [B] -> [C]` is two edges; a `*>` fan-out
#               one per target. Edge.kind is the arrow as written (`->`, `→`,
#               `~>`, `<->`, `=>`, `!>`, `?>`, `*>`, or a dialect's). Edge.payload
#               is the terminal `: payload` text (final link only); Edge.mods the
#               statement's trailing modifiers (final link only); Edge.line the
#               source line. A flow whose target is an internal op-call
#               (`[Worker] -> run()`) is a self-edge with Edge.target_op = "run()"
#               (and that op as its payload).
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
#               follows) and `[P] @borrow(read)? |S|`. principal is the node id
#               the name resolves to (exact name first, then a generic role's base
#               name — `@read(Worker)` → `[Worker<N>]`), None if it names nothing.
#   sections    [Section(level, title, line)]: `--- L2: [Core] ---` → ("L2",
#               "[Core]", line); a topic header `--- Control ---` has level None.
#   layers      the Lk layers seen, in order (Node.layer is the one in force).
#   expansions  {node id: Graph}: `X := { … }` bodies, `X := expr` alias bodies,
#               `state X { … }` machines (role "state"). An expansion written in a
#               section `--- Lk ---` (k >= 3) attaches to the node of that name in
#               a level k-1 expansion (zoom nests), else to the top-level node.
#   tree        [TreeEntry]: composition trees (`\\-<rel>` branches), document order.
#   triggers    [Trigger]: events wired to state-machine transitions (top level).
#   notes       [Note]: `#` comments attached to the node they describe.
#   role        what this graph is when it hangs off a node: "expansion"|"state".
#
# Modifiers (Node.mods / Edge.mods / Block.modifiers) are (name, arg) pairs in
# written order; arg is the text inside the modifier's parens (or after it), or
# None. Names: an `@name` modifier is "name" (`@timeout(30s)` → ("timeout",
# "30s"), `@inv >= 0` → ("inv", ">= 0")); `×N` / `xN` → ("×", "N"); a stream
# bound `^10k@drop` → ("^", "10k@drop"); `!` critical → ("!", None); `?`
# optional → ("?", None); `.field` → (".", "field"). Placement: a modifier
# written between a glyph and the next arrow is that glyph's node's; a
# statement's trailing modifiers belong to its final link's edges, or to its last
# glyph when the statement draws no edge. Declarations about an entity always go
# on the node: @loc @read @write @borrow @owns @grants @requires and `^N@policy`.

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
    # Events wired to state-machine transitions by name (top-level graph only).
    triggers: list = field(default_factory=list)
    # Comments attached to nodes (see collect_comments / parse_document).
    notes: list = field(default_factory=list)
    # Control blocks, joined endpoints, the permission graph, section headers —
    # see the model description above.
    blocks: list = field(default_factory=list)
    joins: list = field(default_factory=list)
    access: list = field(default_factory=list)
    sections: list = field(default_factory=list)


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


@dataclass
class Join:
    kind: str                 # "&" strict join | "&?" race | "/" alternative (one-of)
    members: list             # node ids, in written order
    line: int


@dataclass
class Access:
    principal: Optional[str]  # node id of the principal (None: names no node)
    store: Optional[str]      # node id of the store (None: a borrowed store that is no node)
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


class Section(NamedTuple):
    level: Optional[str]      # "L2" for `--- L2: … ---`, None for a topic header
    title: str
    line: int


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


# Modifiers that are always a declaration about the entity they follow: they go
# on the node even when they trail a flow (see "Modifiers" in the model notes).
_NODE_MODS = {"loc", "read", "write", "borrow", "owns", "grants", "requires", "^"}

# A stream bound `^N` / `^N@policy` (language.md "Streams"), glued to a glyph:
# captured before the generic `@name` modifier rule, which would otherwise take
# its `@policy`. (`x^2` in a value is not a bound.)
STREAM_BOUND_RE = re.compile(r"(?<=[\]}>)|\s])\^[A-Za-z0-9]+(?:@[a-z]+)?")

# Modifiers glued to (or right after) a glyph, read by the tokenizer: `×N`, the
# legacy `*N`, ASCII `xN`, `!` critical, `?` optional, `.field`.
_GLUED_MOD_RE = re.compile(
    r"×\s*(?P<card>\w+)"
    r"|\*\s*(?P<card2>\d+)\b"
    r"|(?<![\w.])x(?P<card3>\d+|N)\b(?=\s|$|@)"
    r"|(?P<bang>!)(?![>=])"
    r"|(?P<opt>\?)(?!>)"
    r"|\.(?P<field>[A-Za-z_][\w.]*)"
)

# The modifiers peeled off a payload's tail (`: score ×3`, `: {Cart} !`).
_TAIL_MOD_RE = re.compile(r"×\s*(\w+)|x(\d+|N)\b|\^(\w+(?:@\w+)?)|(!)")

# An internal op-call written as a flow's target: `[Worker] -> run()`,
# `-> run({Job})`, `-> walk(.children)` (no space before the `(`: `-> x (Y)` is
# a word and an actor). An `op ns.verb(…)` external reach is taken too.
OP_TARGET_RE = re.compile(r"(?:op\s+)?[A-Za-z_][\w.]*\((?:[^()]|\([^()]*\))*\)")


# What may follow a modifier's `( … )` argument and still be other modifiers:
# `@timeout(30s) ×3` is two modifiers, not one with the argument "(30s) ×3".
_TAIL_ONLY_RE = re.compile(r"^(?:\s*(?:×\s*\w+|x(?:\d+|N)\b|!(?![>=])))+\s*$")


def _mod_spans(rx, text: str) -> list:
    """(start, end) of each modifier `rx` finds outside `"…"` strings. A
    modifier's trailing text that is only `×N` / `xN` / `!` is left out of its
    span (those are modifiers of their own)."""
    spans = []
    for m in rx.finditer(text):
        if _in_string(text, m.start()):
            continue
        start, end = m.start(), m.end()
        tok = m.group(0)
        pm = re.match(r"@[A-Za-z][\w-]*\s*\(", tok)
        if pm:
            close = _close_paren(tok[pm.end() - 1:])
            if close >= 0:
                cut = pm.end() + close
                if cut < len(tok) and _TAIL_ONLY_RE.match(tok[cut:]):
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
    for rx in (STREAM_BOUND_RE, PERMISSION_SET_RE, MODIFIER_RE):
        for start, end in _mod_spans(rx, masked):
            tok = masked[start:end]
            out.append((start, ("^", tok[1:]) if tok.startswith("^") else mod_pair(tok)))
            masked = masked[:start] + " " * (end - start) + masked[end:]
    for m in _TAIL_MOD_RE.finditer(masked):
        if _in_string(masked, m.start()):
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
    is a dict it receives "nodes" (ids placed) and "edges" (the new Edge objects)."""
    if isinstance(last_src, Node):
        last_src = Subject((last_src.id,))
    stripped = line
    # Dialect line strips first (dialect-only syntax that must not leak as glyphs).
    for strip in _hook(dialect, "render_line_strips"):
        stripped = strip(stripped)

    # Modifiers are captured with their column and blanked (length-preserving, so
    # the columns of everything else stay put). Stream bounds first (their
    # `@policy` is not a modifier of its own); then the permission-graph access
    # lists `@read(…)` / `@write(…)` — principal NAMES, which must not read as
    # actor glyphs; then every other modifier with its argument — not an `@`
    # inside a `"…"` string (`: "ops@example.com"` is payload text).
    mods = []                                   # (column, (name, arg))

    def capture(rx, s, pair):
        for start, end in _mod_spans(rx, s):
            tok = s[start:end]
            mods.append((start, pair(tok)))
            spaced = rx is PERMISSION_SET_RE or (rx is MODIFIER_RE and mod_pair(tok)[0]
                                                  in _ARG_MODIFIERS)
            s = s[:start] + _blank(end - start, spaced) + s[end:]
        return s

    stripped = capture(STREAM_BOUND_RE, stripped, lambda tok: ("^", tok[1:]))
    stripped = capture(PERMISSION_SET_RE, stripped, mod_pair)
    stripped = capture(MODIFIER_RE, stripped, mod_pair)
    # The terminal `: payload` (not a `:=` alias) is kept as text for the edge,
    # less its trailing cardinality / stream-bound / `!` modifiers.
    payload = None
    payload_span = (-1, -1)
    pm = PAYLOAD_RE.search(stripped)
    if pm:
        payload_span = (pm.start(), pm.end())
        raw = pm.group(1)
        tail = _PAYLOAD_TAIL_RE.search(raw.replace(_GAP, " "))   # same length
        if tail and tail.start() < len(raw):
            at = pm.start(1) + tail.start()
            for t in _TAIL_MOD_RE.finditer(tail.group(0)):
                card = t.group(1) or t.group(2)
                mods.append((at + t.start(), ("×", card) if card
                             else ("^", t.group(3)) if t.group(3) else ("!", None)))
            raw = raw[:tail.start()]
        payload = raw.replace(_GAP, "").strip() or None
        stripped = stripped[:pm.start()] + _blank(pm.end() - pm.start()) + stripped[pm.end():]
        stripped = PAYLOAD_RE.sub(lambda m: _blank(len(m.group(0))), stripped)

    # Tokenize into glyphs, arrows, joins, op-call targets and glued modifiers.
    tokenizers = list(_hook(dialect, "render_tokenizers"))
    tokens = []                                 # (kind, value, column)
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
            if node:
                tokens.append(("glyph", node, i))
            i = gm.end()
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
        mm = _GLUED_MOD_RE.match(stripped, i)
        if mm and (prev_was_glyph or mm.group("bang") or mm.group("card")
                   or mm.group("card2") or mm.group("card3")) and (
                not (mm.group("opt") or mm.group("field"))
                or stripped[:i].rstrip(_GAP)[-1:] in tuple("]}>)|")):
            card = mm.group("card") or mm.group("card2") or mm.group("card3")
            pair = (("×", card) if card else ("!", None) if mm.group("bang")
                    else ("?", None) if mm.group("opt") else (".", mm.group("field")))
            mods.append((i, pair))
            i = mm.end()
            continue                            # prev_was_glyph unchanged
        i += 1  # skip unrecognized chars
        prev_was_glyph = False

    # Fold `a/b/c` into one reference to `c`, remembering its qualifying path.
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

    if not any(t[0] == "glyph" for t in tokens):
        return last_src

    # Every hole is its own node: `[?] -> [X]` and `[?] -> [Y]` are two unknowns.
    for kind, tok, _c in tokens:
        if kind == "glyph" and tok.is_hole:
            graph.hole_seq[0] += 1
            tok.id = f"{tok.id}{graph.hole_seq[0]}"

    if first is not None:
        first.append(next(t[1] for t in tokens if t[0] == "glyph"))

    # Group the line into endpoints separated by arrows. A `&` / `&?` / `/` join
    # extends the current endpoint; two glyphs with no operator between them are
    # separate endpoints with no edge (None). A continuation line (leading arrow)
    # takes the inherited subject as its first endpoint. An op-call target is an
    # endpoint standing for the endpoint before it (the caller runs the op).
    groups: list = []         # {"nodes": [Node], "join": kind, "join_idx", "op"}
    links: list = []          # links[k] joins groups[k] -> groups[k+1]
    cur = None
    pending = None            # the arrow awaiting a destination
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
                pending = tok
            joining = None
        elif kind == "join":
            joining = tok
        elif kind == "op":
            if cur is not None:
                groups.append(cur)
                pending = None
            if groups:
                links.append(pending)
                prev = groups[-1]
                cur = {"nodes": prev["nodes"], "join": None, "join_idx": prev["join_idx"],
                       "op": tok}
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
                cur = {"nodes": [tok], "join": None, "join_idx": None, "op": None}
                pending = None
            joining = None
    if cur is not None:
        groups.append(cur)

    placed = []
    for group in groups:
        if group.get("op") or group.get("inherited"):
            continue
        # Qualifying paths belong to the written token, before it is swapped for
        # the graph's node of that id.
        group["paths"] = [paths.get(id(n)) for n in group["nodes"]]
        for k, n in enumerate(group["nodes"]):
            if n.id not in graph.nodes:
                graph.nodes[n.id] = n
            group["nodes"][k] = graph.nodes[n.id]
            placed.append(n.id)
        if len(group["nodes"]) > 1 and group["join_idx"] is None:
            graph.joins.append(Join(group["join"] or "&", [n.id for n in group["nodes"]],
                                    line_no))
            group["join_idx"] = len(graph.joins) - 1

    # Fan every arrow out across both endpoints (`[A] & [B] -> [C] & [D]` is 4 edges).
    new_edges = []
    final = []
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
        else:
            dpaths = dst.get("paths") or [None] * len(dst["nodes"])
            for s, sp in zip(src["nodes"], spaths):
                for d, dp in zip(dst["nodes"], dpaths):
                    made.append(Edge(src=s.id, dst=d.id, kind=arrow,
                                     src_path=sp, dst_path=dp,
                                     src_join=src["join_idx"], dst_join=dst["join_idx"],
                                     line=line_no))
        new_edges += made
        if k == len(groups) - 2:
            final = made
    if payload:
        for e in final:
            e.payload = f"{e.target_op} : {payload}" if e.target_op else payload
    graph.edges.extend(new_edges)

    # Modifiers: between a glyph and the next arrow → that glyph's node; trailing
    # the statement → the final link's edges (or the last glyph without one);
    # entity declarations (_NODE_MODS) always on the node.
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
        if payload_span[0] <= col < payload_span[1] and final:
            for e in final:                     # a bound on the payload's stream
                _add_mod(e.mods, pair)
        elif pair[0] in _NODE_MODS or not trailing or not final:
            if owner is not None:
                _add_mod(owner.mods, pair)
                _access(graph, owner, pair, line_no, layer)
        else:
            for e in final:
                _add_mod(e.mods, pair)

    if out is not None:
        out["nodes"] = list(dict.fromkeys(placed))
        out["edges"] = new_edges
    head = groups[0]
    if head.get("inherited"):
        return last_src
    return Subject(tuple(n.id for n in head["nodes"]), head["join_idx"],
                   tuple(head.get("paths") or ()))


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
STATE_HEAD_RE = re.compile(r"^state\s*([~*]*[\[{<(|]" + _NAME_CHARS + r"+(?:" + _GENERIC
                           + r")?[\]}>)|])\s*\{")
STATE_OPEN_RE = re.compile(r"^state\s*\{")

# A transition inside a `state` block: `Src -<trigger>-> Dst` or `Src -> Dst`,
# optionally followed by per-transition modifiers (`×3`, `@timeout(…)`, …).
TRANSITION_RE = re.compile(r"^(\S+)\s+(?:-<([^<>]*)>->|->)\s+(\S+)\s*(.*)$")
PSEUDO_STATES = {"+": "start", "$": "end", "_": "any"}

# A control block header: its statements are ordinary flows (Graph.blocks).
LOOP_HEAD_RE = re.compile(r"^(loop|parallel|branch)\b")
# A scoped block `name { … }` (language.md "Structure").
SCOPE_HEAD_RE = re.compile(r"^[A-Za-z_][\w.-]*\s*\{(?=\s|$)")
# A branch arm `label => flow` (grammar: arm := (name | '_') '=>' flow).
ARM_RE = re.compile(r'^(?P<label>_|[\w.-]+|"[^"]*")\s*=>\s*(?P<body>.*)$')

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
        self.pending_states = []       # (owner Node, state graph)
        # Blocks being collected. Expansion: [target_name, target_kind, raw lines,
        # brace depth, first line, layer]; state: [owner Node | None, lines, brace
        # depth]; declaration: [(regex, on_raw), depth].
        self.expansion = None
        self.state = None
        self.decl = None
        self.decl_blocks = list(_hook(dialect, "DECLARATION_BLOCKS"))
        # Open control blocks (loop / parallel / branch / scope / owns), innermost
        # last; and the block whose subject continuation lines after it take.
        self.frames: list = []
        self.after_block = None
        # Composition tree state: open branches as (column, tree index), and the last
        # plain glyph line a branch could hang under: [column, node id, tree index|None].
        self.tree_stack: list = []
        self.tree_root: Optional[list] = None
        # Notes: the node the current line is "about", the document's comments, and
        # own-line comments waiting for the statement below.
        self.anchor = None
        self.comments: dict = {}
        self.above: list = []

    def ln(self, k: int) -> int:
        """The source line of this document's line index k."""
        return self.line0 + k + 1

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
        while self.frames:                  # a block left open at the end of the text
            self._close_block(len(lines) - 1)
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
                self.above.append((c[0], self.ln(k)))
                return
            if not line:                    # a blank line detaches waiting comments
                self.above.clear()
        if self._on_declaration(raw_lead, line) or self._on_section(k, line):
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
                cut = _close_at(text, before)
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
                    for g2, _o, _l in _walk(cand):
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
            if provisional != target_id:     # notes attached before resolution
                for note in self.graph.notes:
                    if note.node == provisional and note.line == line:
                        note.node = target_id
            if sub_graph is not None:
                home.expansions[target_id] = sub_graph
                by_level.setdefault(level, []).append(sub_graph)

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

        _resolve_access(graph, graph)
        for b in graph.blocks:              # `[X] @owns |R| {`: R when it is a node
            b.refs += [r for r in getattr(b, "_owned", ()) if r in graph.nodes
                       and r not in b.refs]
        if self.top:                        # top level: wire events to transitions
            for g2, _o, _l in _walk(graph):  # access lists inside expansions may
                _resolve_access(g2, graph)   # name a top-level principal / store
            graph.triggers = find_triggers(graph)
        return graph

    # -- helpers --------------------------------------------------------------

    def _sub_parse(self, text: str, line0: int) -> Graph:
        return parse_document(text, self.graph.hole_seq, self.dialect, _line0=line0)

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
            self.graph.notes.append(Note(node_id, trailing[0], self.ln(k), "inline", edges))
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
        # body recursively. Modifiers after the `}` (`} @inv x`) are the node's.
        cut = _close_at(stripped, before)
        last = stripped[:cut] if cut is not None else stripped
        if last.strip():
            exp[2].append(last)
        mods = scan_mods(stripped[cut + 1:]) if cut is not None else []
        self.pending_expansions.append(
            (exp[0], exp[1], self._sub_parse("\n".join(exp[2]), exp[4]), exp[5], mods,
             exp[6]))
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

    def _on_section(self, k: int, line: str) -> bool:
        sec = SECTION_RE.match(line)
        if not sec:
            return False
        self.above.clear()
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
        self.attach(mk_id(name + "_" + (kind or "alias")), k)
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
        cut = _close_at(body, 1)
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
                    (owner, parse_state_block([(body[:cut], self.ln(k))], owner.name)))
        else:
            self.state = [owner, [(body.strip(), self.ln(k))] if body.strip() else [],
                          1 + body.count("{") - body.count("}")]
        return True

    def _in_state(self, k: int, line: str):
        st = self.state
        before = st[2]
        st[2] += line.count("{") - line.count("}")
        if st[2] > 0:
            st[1].append((line, self.ln(k)))
            return
        cut = _close_at(line, before)
        if cut is not None and line[:cut].strip():
            st[1].append((line[:cut].strip(), self.ln(k)))   # a last transition before the `}`
        if st[0]:
            self.pending_states.append((st[0], parse_state_block(st[1], st[0].name)))
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
        if block is not None and block.kind == "branch" and not in_header:
            am = ARM_RE.match(body)
            if am and not ARROW_RE.match(body):
                # A branch arm: its flow starts afresh (it is not a continuation).
                block.arms.append((am.group("label"), []))
                block.arm_nodes.append((am.group("label"), []))
                fr.arm = len(block.arms) - 1
                offset += text.find(am.group("body")) if am.group("body") else len(text)
                text = body = am.group("body")
                self.last_src = None
                if not body.strip():
                    self.attach(None, k)
                    return
        continuation = bool(ARROW_RE.match(body))
        col = offset + len(text) - len(text.lstrip())
        acc = {"nodes": [], "edges": []}
        subject = self._flow(body, col, self.last_src, k, acc)
        if not continuation:
            self.last_src = subject
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

    def _flow(self, text: str, col: int, last, k: int, acc: dict):
        """One flow line; composition branches (`\\-<rel>`) become tree entries."""
        graph, dialect = self.graph, self.dialect

        def flows(t, last, cap):
            out = {}
            res = extract_flows(t, graph, self.layer, last, dialect, first=cap,
                                line_no=self.ln(k), out=out)
            acc["nodes"].extend(n for n in out.get("nodes", ()) if n not in acc["nodes"])
            acc["edges"].extend(out.get("edges", ()))
            return res

        m = BRANCH_RE.search(text)
        if m is not None and m.start() > 0 and not _BRANCH_PARENT_RE.match(text[:m.start()]):
            m = None                         # a marker inside prose / a payload, not a branch
        if m is None:
            cap: list = []
            last = flows(text, last, cap)
            if cap:
                self.tree_stack = [t for t in self.tree_stack if t[0] < col]
                self.tree_root = [col, cap[0].id, None]
                self.anchor = cap[0].id
            return last
        left, rest = text[:m.start()], BRANCH_RE.sub(" ", text[m.end():])
        bcol = m.start() + col
        if left.strip():                     # inline: `[parent] \\-& [child]`
            cap = []
            last = flows(left, last, cap)
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
        last = flows(rest, last, cap)
        if cap:
            spawn = bool(m.group("spawn") or m.group("bare_spawn"))
            rel = m.group("rel") or ("*" if m.group("bare_spawn") else None)
            weight = int(m.group("weight")) if m.group("weight") else None
            idx = self.add_entry(cap[0].id, parent, rel, spawn, m.group("cond"), weight)
            stack.append((bcol, idx))
            self.anchor = cap[0].id
        return last


def parse_document(text: str, _hole_seq: Optional[list] = None, dialect=None,
                   _line0: int = 0) -> Graph:
    """Parse a Sigil document into a Graph structure (see "THE MODEL" above).
    `dialect` is a loaded dialect (dialects.load) or None for core Sigil.
    `_hole_seq` / `_line0` are internal: a sub-document (an expansion body) shares
    its parent's hole counter, and its line numbers are offset to the source's."""
    return _DocParser(_hole_seq, dialect, _line0).parse(text)


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
                events.setdefault(n.base_name.lower(), n.id)   # `<Msg<T>>` drives `-<Msg>->`
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
        line, line_no = line if isinstance(line, tuple) else (line, 0)
        m = TRANSITION_RE.match(line.strip())
        if not m:
            continue
        src, trigger, dst, rest = m.groups()
        a, b = node(src), node(dst)
        label = f"<{trigger}>" if trigger else None
        rest = rest.strip()
        g.edges.append(Edge(src=a.id, dst=b.id, kind="->", label=label,
                            payload=rest or None, mods=scan_mods(rest), line=line_no))
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
    "alias":     ("[[", "]]"),       # subroutine — a bare-word `name := …` definition
}

_CORE_CLASSDEFS = [
    "classDef service fill:#E3F2FD,stroke:#1976D2,color:#0D47A1",
    "classDef data    fill:#F3E5F5,stroke:#7B1FA2,color:#4A148C",
    "classDef event   fill:#FFF3E0,stroke:#F57C00,color:#E65100",
    "classDef actor   fill:#E8F5E9,stroke:#388E3C,color:#1B5E20",
    "classDef store   fill:#FFF9C4,stroke:#F9A825,color:#F57F17",
    "classDef state   fill:#E0F2F1,stroke:#00897B,color:#004D40",
]
# Emitted only when a document has alias nodes (keeps every other footer as it was).
_ALIAS_CLASSDEF = "classDef alias   fill:#ECEFF1,stroke:#546E7A,color:#263238"
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
    label = e.label or getattr(e, "target_op", None)    # `[W] -> run()`: the op it runs
    if label:
        arrow = _labelled(arrow, mermaid_text(label))
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


def arm_wires(graph: Graph) -> list:
    """(decision node, arm entry node, arm label) per `branch on X { label => … }`
    arm: the branch's choice drawn from its subject glyph to each arm's first
    node. A branch with no glyph in its header draws no wires."""
    out = []
    for b in graph.blocks:
        if b.kind != "branch" or not b.refs:
            continue
        for label, nodes in b.arm_nodes:
            if nodes and nodes[0] != b.refs[0]:
                out.append((b.refs[0], nodes[0], label))
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
                lines.append(emit_edge(Edge(src=s, dst=d, kind=e.kind, label=e.label,
                                            target_op=e.target_op), indent, dialect))
    for src, dst, label in arm_wires(graph):
        for s in ends(src, None):
            for d in ends(dst, None):
                lines.append(f'{indent}{s} -. "{mermaid_text(label)}" .-> {d}')
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
        for src, dst, label in arm_wires(graph):
            lines.append(f'{indent}{src} -. "{mermaid_text(label)}" .-> {dst}')

    # Emit classes at this level
    if with_classes:
        for cls_line in emit_classes(graph, indent, dialect):
            lines.append(cls_line)

    return "\n".join(lines)


def unique_ids(graph: Graph, depth: int = 1) -> Graph:
    """A copy of the graph whose node ids are unique across every graph Mermaid
    draws (the top level and the expansions up to `depth`): Mermaid ids are
    global, so `[Handler]` at the top level and `[Core]`'s `[Handler]` would be
    one node. The top level keeps its ids; a nested graph's id that a graph
    nearer the top already uses becomes `<owner id>__<id>` (the owner being the
    node the expansion hangs off, as emitted). Triggers follow their nodes."""
    claimed = set(graph.nodes)
    renamed = {}                                # id(graph) → {old id: new id}
    queue = [(graph, None, 0)]
    order = []
    while queue:                                # breadth first: the shallower claims first
        g, owner_mid, level = queue.pop(0)
        order.append(g)
        names = renamed.setdefault(id(g), {})
        if g is not graph:
            for nid in g.nodes:
                new = nid
                if nid in claimed:
                    new, k = f"{owner_mid}__{nid}", 2
                    while new in claimed:
                        new, k = f"{owner_mid}__{nid}_{k}", k + 1
                    names[nid] = new
                claimed.add(new)
        if level < depth:
            for nid, sub in g.expansions.items():
                queue.append((sub, names.get(nid, nid), level + 1))
    if not any(renamed.values()):
        return graph

    def copy(g):
        m = renamed.get(id(g), {})

        def r(nid):
            return m.get(nid, nid)

        return replace(
            g,
            nodes={r(k): replace(n, id=r(n.id)) for k, n in g.nodes.items()},
            edges=[replace(e, src=r(e.src), dst=r(e.dst)) for e in g.edges],
            expansions={r(k): copy(sub) for k, sub in g.expansions.items()},
            tree=[replace(t, node=r(t.node)) for t in g.tree],
            blocks=[replace(b, refs=[r(x) for x in b.refs],
                            members=[r(x) for x in b.members],
                            arm_nodes=[(lab, [r(x) for x in ids]) for lab, ids in b.arm_nodes])
                    for b in g.blocks],
        )

    out = copy(graph)
    trig = []
    for t in graph.triggers:
        owner, src, dst, event = t.owner, t.src, t.dst, t.event
        for g, _o, _l in _walk(graph):
            sub = g.expansions.get(t.owner)
            if sub is not None and t.dst in sub.nodes:
                owner = renamed.get(id(g), {}).get(t.owner, t.owner)
                src = renamed.get(id(sub), {}).get(t.src, t.src)
                dst = renamed.get(id(sub), {}).get(t.dst, t.dst)
                break
        for g in order:
            if t.event in g.nodes:
                event = renamed.get(id(g), {}).get(t.event, t.event)
                break
        trig.append(replace(t, owner=owner, src=src, dst=dst, event=event))
    out.triggers = trig
    return out


def render(text: str, depth: int = 1, dialect=None, composition: Optional[str] = None) -> str:
    """Mermaid for a document. `composition`: "subgraphs" (default — composition
    trees as nested subgraphs, one node per occurrence), "edges" (one node per name,
    dotted relation edges), or "none"; a dialect may change the default
    (MERMAID_COMPOSITION)."""
    if composition is None:
        composition = _hook(dialect, "MERMAID_COMPOSITION", "subgraphs")
    graph = unique_ids(parse_document(text, dialect=dialect), depth)
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
    classes = _class_def(dialect)
    if any(n.kind == "alias" for g, _o, _l in _walk(graph) for n in g.nodes.values()):
        classes += "\n    " + _ALIAS_CLASSDEF
    return f"flowchart TD\n{body}\n\n{classes}"


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
