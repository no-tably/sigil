"""What a document's comments say: notes, block-strings, acknowledgements.

    comments        collect_comments(lines, dialect) → {line index: (text,
                    own_line)} (the parser's reading, sigil.core.parse)
    notes           note_index(g): every node's notes, numbered in document
                    order (top level first, then expansions); note_key,
                    block_note_key, DOC_NOTE / BLOCK_NOTE keys; a block-string
                    payload is an inline note of its flow (block_lines,
                    block_string_of)
    layout          layout_of(lines, strip_comment): statement lines and block
                    spans (Layout)
    acknowledgements  `# accepts: rule-name — reason` comments: parse_ack,
                    ack_span, read_acks → [Ack] (catalog §10.1); check reads
                    them, and so does the export model

Pure functions; no I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

from sigil.core.graph import Note, walk_breadth
from sigil.core.parse import collect_comments  # noqa: F401  (re-exported)


# ---------------------------------------------------------------------------
# Notes — numbered per node, in document order
# ---------------------------------------------------------------------------

def block_string_of(e):
    """The text of an edge's (or a wire's edge's) `\"\"\"…\"\"\"` payload, or None."""
    body = getattr(e, "block_string", None)
    return body if body is not None else getattr(getattr(e, "edge", None), "block_string", None)


def block_lines(body: str) -> list:
    """A block-string's lines, the blank ones at its ends dropped, each stripped."""
    lines = [ln.strip() for ln in body.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return lines


# The note-index key of the document's own notes (a header comment that precedes
# no statement): listed with the notes, tagged on nothing. Node ids never hold
# `@`, so neither this nor a block_note_key (BLOCK_NOTE…) can meet one.
DOC_NOTE = "@document"
BLOCK_NOTE = "@block:"


def block_note_key(b) -> str:
    """The note-index key of a control block's notes (a comment above its
    glyph-less header): its frame title (graph) or header row (tree) is tagged."""
    return f"{BLOCK_NOTE}{b.lines[0]}-{b.lines[1]}"


def note_key(g, n) -> str:
    """Where note n (of graph g) is indexed: its node id, its block's key, or
    DOC_NOTE."""
    if n.node is not None:
        return n.node
    bi = getattr(n, "block", None)
    return block_note_key(g.blocks[bi]) if bi is not None else DOC_NOTE


def note_index(g) -> dict:
    """{node id: [(number, text, kind, edges), …]}, numbered in document order (top
    level first, then expansions). A node's block comments (about the component)
    merge into one note; each inline comment (about its line) stays its own note
    and keeps the (src, dst, kind) of the flows that line drew. A control block's
    notes are keyed block_note_key; the document's are keyed DOC_NOTE (note_key)
    and merge into one note numbered 0, so the numbers tags show stay 1, 2, …"""
    out, num = {}, 0
    for cur in walk_breadth(g):
        for n in _notes_and_blocks(cur):
            kind = getattr(n, "kind", "block")
            entries = out.setdefault(note_key(cur, n), [])
            block = next((i for i, e in enumerate(entries) if e[2] == "block"), None)
            if kind == "block" and block is not None:
                b = entries[block]
                entries[block] = (b[0], f"{b[1]} · {n.text}", "block", ())
                continue
            key = note_key(cur, n)
            if key != DOC_NOTE:
                num += 1
            entries.append((num if key != DOC_NOTE else 0, n.text, kind,
                            tuple(getattr(n, "edges", ()) or ())))
    return out


def _notes_and_blocks(g) -> list:
    """g's notes with, among them in line order, an inline note per edge with a
    `\"\"\"…\"\"\"` payload holding its full text (about the flow, so drawn on it
    and listed where notes are)."""
    blocks = sorted((e.line, i, e) for i, e in enumerate(getattr(g, "edges", []))
                    if getattr(e, "block_string", None) is not None)
    out, k = [], 0
    for n in getattr(g, "notes", []):
        while k < len(blocks) and blocks[k][0] < n.line:
            out.append(_block_note(blocks[k][2]))
            k += 1
        out.append(n)
    return out + [_block_note(b[2]) for b in blocks[k:]]


def _block_note(e):
    """The note holding edge e's block-string, one line of it per text line."""
    text = '"""' + "\n".join(block_lines(e.block_string)) + '"""'
    return Note(e.src, text, e.line, "inline", (e.key,))


# ---------------------------------------------------------------------------
# Layout and acknowledgements (catalog §10.1)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Ack:
    """One acknowledgement comment (catalog §10.1). `reason` is "" when missing
    (the acknowledgement is then void, SGC002). `span` is the set of lines it
    covers; `document` makes it cover every line."""
    line: int
    names: tuple
    reason: str
    span: frozenset = frozenset()
    document: bool = False

    def covers(self, line: int) -> bool:
        return self.document or line in self.span


@dataclass(frozen=True)
class Layout:
    """Where the statements and blocks of a document are (1-based lines)."""
    statements: frozenset            # lines holding a statement
    blocks: dict                     # header or closing line → (header, closing)
    quoted: frozenset                # lines inside a `\"\"\"…\"\"\"` block-string body

    @property
    def first(self) -> Optional[int]:
        return min(self.statements, default=None)

    def span(self, line: int) -> frozenset:
        """A block header or its `}` covers the whole block; any other line itself."""
        if line in self.blocks:
            head, close = self.blocks[line]
            return frozenset(range(head, close + 1))
        return frozenset({line})


_STRING_RE = re.compile(r'"[^"]*"')


def layout_of(lines: list, strip_comment: Callable) -> Layout:
    """Statement lines and block spans. A line whose code ends with `{` opens a
    block, one whose code starts with `}` closes the innermost open block."""
    statements, quoted, blocks, stack = set(), set(), {}, []
    in_quote = False
    for n, raw in enumerate(lines, start=1):
        if in_quote:
            quoted.add(n)
            in_quote = raw.count('"""') % 2 == 0
            continue
        stripped = raw.strip()
        if stripped.startswith("#!"):
            continue
        code = stripped if stripped.startswith("#&") else strip_comment(raw).strip()
        if not code:
            continue
        statements.add(n)
        in_quote = code.count('"""') % 2 == 1
        bare = _STRING_RE.sub('""', code)
        if bare.startswith("}") and stack:
            head = stack.pop()
            blocks[head] = blocks[n] = (head, n)
        if bare.endswith("{"):
            stack.append(n)
    return Layout(frozenset(statements), blocks, frozenset(quoted))


# Any case, so a rule id (`SGC111`) or a mixed-case name still reads as an
# acknowledgement and reaches SGC001 rather than failing silently as prose.
_KEBAB = r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*"


_ACK_RE = re.compile(rf"^accepts:\s*(?P<names>{_KEBAB}(?:\s*,\s*{_KEBAB})*)(?P<tail>.*)$")


RULE_ID_RE = re.compile(r"^[A-Z]+[0-9]+$")


_SEPARATOR_RE = re.compile(r"^\s*(?:—|--)\s*(?P<reason>.*)$|^\s+-(?:\s+(?P<reason2>.*))?$")


def parse_ack(text: str, known: frozenset) -> Optional[tuple]:
    """(names, reason) when a comment's text is an acknowledgement, else None.
    `accepts:` then kebab-case rule names, a separator (`—`, `--`, ` - `) and a
    reason. Names of any case and rule ids are read too, so SGC001 can say what is
    wrong with them. With no separator it is an acknowledgement (missing its
    reason) only when the text is nothing but names and one of them is a rule
    name (in any case), a rule id or a kebab compound; so `# accepts: any JSON
    body` stays prose."""
    m = _ACK_RE.match(text.strip())
    if not m:
        return None
    names = tuple(n.strip() for n in m.group("names").split(","))
    tail = m.group("tail")
    if not tail.strip():
        if any(n.lower() in known or "-" in n or RULE_ID_RE.match(n) for n in names):
            return names, ""
        return None
    sep = _SEPARATOR_RE.match(tail)
    if not sep:
        return None
    return names, (sep.group("reason") or sep.group("reason2") or "").strip()


def ack_span(line: int, own_line: bool, layout: Layout, comment_lines: frozenset):
    """(span, document) for an acknowledgement on `line`: trailing → its line (a
    block header or `}` → the block); own line(s) directly above a statement →
    that statement (or block); before the first statement and not directly above
    it → the whole document; anywhere else → nothing."""
    if not own_line:
        return layout.span(line), False
    nxt = line + 1
    while nxt in comment_lines and nxt not in layout.statements:
        nxt += 1
    if nxt in layout.statements:
        return layout.span(nxt), False
    first = layout.first
    if first is None or line < first:
        return frozenset(), True
    return frozenset(), False


def read_acks(comments: dict, layout: Layout, known: frozenset) -> list:
    """Every acknowledgement in the document, in line order."""
    comment_lines = frozenset(comments)
    out = []
    for line in sorted(comments):
        text, own = comments[line]
        if line in layout.quoted:
            continue
        parsed = parse_ack(text, known)
        if parsed is None:
            continue
        span, document = ack_span(line, own, layout, comment_lines)
        out.append(Ack(line, parsed[0], parsed[1], span, document))
    return out
