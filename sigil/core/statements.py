"""
statements — a document read once: the statement walk. The parser
(sigil.core.parse) builds the model from it and lint's rules judge it; neither
reads the text again.

    read_document(text, dialect=None, result=None) → Walk
    read_lines(lines, dialect=None, result=None) → Walk

The reading: the lines with their block strings folded (lex.fold_block_strings)
and the dialect's prepasses run (`result` takes what a prepass reports; a
scratch one when None), each line's Code (comment cut, strings blanked), and the
document walked line by line the way the model reads it — sections,
declarations, definitions (`X := …`, whose `{ … }` body is read as a document
of its own), `state` machines, control blocks, branch arms — down to each
statement, which is read into tokens (sigil.core.tokens) once, its composition
branch marker first and the dialect's strips after.

The Walk is that reading twice over: `doc`, the documents and items in reading
order the parser builds from (Doc, and the item records below), and the flat
records lint's rules judge (statements, blocks, headers, sections,
transitions, bare branches, continuation lines, definitions, codes). The walk
only records what it reads; what is wrong with it is for the reader to judge.
"""

import re
from bisect import bisect_left
from dataclasses import dataclass
from typing import NamedTuple, Optional

from sigil.core.dialects import _hook
from sigil.core.lex import (
    ALIAS_RE, ANY_GLYPH_RE, ARM_RE, ARROW_RE, BARE_BRANCH_RE, BLOCK_OPEN_RE,
    BRANCH_ANY_RE, BRANCH_PARENT_RE, BRANCH_RE, DEFINE_RE, DIALECT_COL, EXPANSION_OPEN_RE,
    GLYPH_RE, LOOP_HEAD_RE, SCOPE_HEAD_RE, SECTION_RE, STATE_HEAD_RE, STATE_OPEN_RE,
    close_at, comment_start, fold_block_strings, in_string, mask_strings, net_braces)
from sigil.core.tokens import (
    NO_DIALECT, Code, Lexicon, Tok, code_line, lexicon, tokenize_statement)


# ---------------------------------------------------------------------------
# What lint judges
# ---------------------------------------------------------------------------

class Statement(NamedTuple):
    """A statement: its source line (1-based), its Code span (the dialect's strips
    applied) and its tokens (columns in the span). `alias`: the body of a
    one-line definition (`[R] := [A] -> [B]`). `branch`: the index in `toks` of
    its composition branch marker (a `branch` token), or -1. `marks`: the
    columns (in the span) of every `\\-` that stands where a branch marker may
    (its start, after a glyph-only parent, after the leading marker). `quiet`:
    the model reads it, lint judges it by a rule of its own only (a bare branch,
    a malformed section header, a definition that draws nothing). `shift`: the
    column its document line starts at (a definition's body read from the
    middle of a line). `cont`: it starts with an arrow (a continuation line, as
    written: before the strips)."""
    line: int
    code: Code
    alias: bool = False
    toks: tuple = ()
    branch: int = -1
    marks: tuple = ()
    quiet: bool = False
    shift: int = 0
    cont: bool = False

    @property
    def col(self) -> int:
        """The column of the statement's first character in its line."""
        text = self.code.text
        return self.code.col + len(text) - len(text.lstrip())


class Block(NamedTuple):
    """A block the walk opened: kind (alias state loop parallel branch scope owns
    keyword), the line of its `{`, whether a statement sits in it, whether a `}`
    closed it."""
    kind: str
    line: int
    content: bool
    closed: bool


class Header(NamedTuple):
    """A control-block header (`loop …`, `parallel …`, `branch …`, a scope, an
    owns block, a dialect keyword), with or without its `{`: `head` is its text
    before the `{`."""
    kind: str
    line: int
    head: str


class Continuation(NamedTuple):
    """A line that starts with an arrow: `subject` when a flow above gives it its
    source, `after_blank` when a blank line separates it from that flow."""
    line: int
    text: str
    subject: bool
    after_blank: bool


# ---------------------------------------------------------------------------
# What the parser builds from: a document's items, in reading order
# ---------------------------------------------------------------------------
# `line` is a 0-based line index of the whole source (a body's lines too).

class Note(NamedTuple):
    """A comment on a line of its own."""
    line: int
    text: str


class Blank(NamedTuple):
    """A line with no code and no comment of its own (it detaches the comments
    waiting above)."""
    line: int


class Declaration(NamedTuple):
    """The opener of a dialect declaration block (its body is consumed)."""
    line: int


class SectionHead(NamedTuple):
    line: int
    level: Optional[str]
    title: str


class Definition(NamedTuple):
    """`name := …`: `name`, `kind` (service, data, None for a bare word) or
    `glyph` (a dialect glyph's text) name the node. `form` "block" (`{ … }`) or
    "inline" (`X := expr`); `body` the body read as a document; `closed`
    whether its `}` came; `tail` the text after that `}`; `rhs` an inline
    definition's text."""
    line: int
    name: str
    kind: Optional[str]
    glyph: Optional[str]
    form: str
    body: Optional["Doc"] = None
    closed: bool = False
    tail: str = ""
    rhs: str = ""


class StateHead(NamedTuple):
    """`state <owner> {`: `owner` the owner glyph's text, None when there is none."""
    line: int
    owner: Optional[str]


class StateEnd(NamedTuple):
    """A `state` block's end: its body lines as (text, line), the text after its
    `}`, and the line of its head."""
    line: int
    lines: tuple
    tail: str
    head: int


class BlockOpen(NamedTuple):
    """A control block's header (loop parallel branch scope owns keyword): `head`
    its text before the `{`, `toks` the tokens of that text, `header` an owns
    header read as a statement, `rest` the text after the `{`."""
    line: int
    kind: str
    head: str
    toks: tuple
    header: Optional[Statement]
    rest: str = ""


class BlockClose(NamedTuple):
    line: int


class BlockMods(NamedTuple):
    """`} @inv …`: modifiers after a control block's `}`."""
    line: int
    text: str


class Flow(NamedTuple):
    """A flow statement; `arm` the label of the branch arm it is the body of (an
    empty arm has no statement)."""
    line: int
    statement: Optional[Statement]
    arm: Optional[str] = None


class Doc(NamedTuple):
    """A document — the whole text, or a definition's body: its items in reading
    order; `end` the line index past its last line; `unclosed` the line of a
    definition, `state` or declaration block left open at its end (its lines
    are dropped from there); `top` the whole text; `texts` {line: text} of the
    lines read from a piece of a source line."""
    items: tuple
    end: int
    unclosed: Optional[int]
    top: bool
    texts: dict


class Walk(NamedTuple):
    """What a document's reading found. For the parser: `doc`, `lines` (block
    strings folded, prepasses run), `comments` ({line index: (text, own_line)}
    of the top level, read before the prepasses), `bodies` ({line index: a
    block string's text}), `lexicon`. For lint, each in reading order:
    `statements`; `blocks` (the closed ones as they close, then those left
    open); `headers`; `sections`, `transitions` and `bare_branches` as (line,
    text): a `--…` line, a line of a `state` block, a branch body written
    without its `\\-`; `continuations`; `definitions` (every name defined with
    `:=`); `codes` (every line's Code); `unterminated` (the index of an opening
    `\"\"\"` never closed, or None). `inner`: the comments of a definition's
    body lines, read after the prepasses (a body is read as written then).
    `spans`: (header line, closing line) of every block a `}` closed — control
    blocks, `state` blocks, definition bodies, dialect declarations — as they
    close; `quoted`: the indices of the lines a block string's body consumed."""
    statements: tuple
    blocks: tuple
    headers: tuple
    sections: tuple
    transitions: tuple
    bare_branches: tuple
    continuations: tuple
    definitions: frozenset
    codes: tuple
    doc: Doc = None
    lines: tuple = ()
    comments: dict = {}
    bodies: dict = {}
    unterminated: Optional[int] = None
    lexicon: Lexicon = NO_DIALECT
    inner: dict = {}
    spans: tuple = ()
    quoted: frozenset = frozenset()


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

def comment_of(line: str, marker) -> Optional[tuple]:
    """A line's comment: (text, own_line), or None. Core comments start with `#`
    (not the `#!` mode line, nor a `#&` marker — see lex.COMMENT_START_RE); a
    dialect's markers (`marker`, one pattern) too. A marker inside a `"…"` string
    starts no comment."""
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


def collect_comments(lines: list, dialect=None) -> dict:
    """{line index: (text, own_line)} for every comment (comment_of)."""
    marker = lexicon(dialect).marker
    out = {}
    for k, line in enumerate(lines):
        c = comment_of(line, marker)
        if c:
            out[k] = c
    return out


# ---------------------------------------------------------------------------
# The reading
# ---------------------------------------------------------------------------

def read_document(text: str, dialect=None, result=None) -> Walk:
    """Read a document once (see the module notes)."""
    return read_lines(text.splitlines(), dialect, result)


def read_lines(lines: list, dialect=None, result=None) -> Walk:
    """read_document of a document's lines."""
    lx = lexicon(dialect)
    bodies: dict = {}
    folded = fold_block_strings(list(lines), bodies)
    lines = folded.lines
    comments = collect_comments(lines, dialect)
    prepasses = list(_hook(dialect, "prepasses"))
    if prepasses:
        from sigil.core.vocab import LintResult
        report = result if result is not None else LintResult()
        for prepass in prepasses:
            lines = prepass(lines, report)
        inner = {k: c for k, line in enumerate(lines) if (c := comment_of(line, lx.marker))}
    else:
        inner = comments
    codes = tuple(code_line(raw, lx) for raw in lines)
    w = _Walker(lines, codes, comments, inner, lx,
                keywords=set(_hook(dialect, "BLOCK_KEYWORDS", set())),
                decl_blocks=list(_hook(dialect, "DECLARATION_BLOCKS")))
    return w.finish(w.read(), tuple(lines), comments, bodies, folded)


def walk_statements(lines: list, dialect=None) -> Walk:
    """The Walk of a document's lines (read_lines; a test's view of the walk)."""
    return read_lines(lines, dialect)


@dataclass
class _Frame:
    """An open control block (or a dialect keyword's block) while its body is read."""
    kind: str             # loop parallel branch scope owns keyword
    line: int
    depth: int
    content: bool = False   # any statement inside
    glyphs: bool = False    # a statement inside drew a glyph (the block's subject)


@dataclass
class _Body:
    """A definition's `{ … }` body its header just opened: the Definition's index
    among the items, its line, the brace depth after the header, the text after
    the header's `{` (its first line, when not blank) and that text's column."""
    item: int
    line: int
    depth: int
    piece: str
    col: int


@dataclass
class _State:
    """A `state` block being read."""
    owner: Optional[str]
    lines: list
    depth: int
    head: int
    content: bool = False


class _Walker:
    """What every document level of one reading shares: the lines, their Codes
    and comments, the dialect's reading, and lint's records."""

    def __init__(self, lines, codes, comments, inner, lx, keywords=(), decl_blocks=()):
        self.lines, self.codes, self.lx = lines, codes, lx
        self.comments, self.inner = comments, inner
        self.keyword_re = (re.compile(r"^(" + "|".join(map(re.escape, sorted(keywords)))
                                      + r")\b") if keywords else None)
        self.decl_blocks = list(decl_blocks)
        self.stmts: list = []
        self.blocks: list = []      # closed, as they close
        self.open_blocks: list = []
        self.headers: list = []
        self.sections: list = []
        self.transitions: list = []
        self.bare: list = []
        self.continuations: list = []
        self.spans: list = []       # (header line, closing line), 1-based, as they close
        self.defined = frozenset(filter(None, (self.definition_name(c) for c in codes)))

    def finish(self, doc, lines, comments, bodies, folded) -> Walk:
        return Walk(tuple(self.stmts), tuple(self.blocks + self.open_blocks),
                    tuple(self.headers), tuple(self.sections), tuple(self.transitions),
                    tuple(self.bare), tuple(self.continuations), self.defined, self.codes,
                    doc, lines, comments, bodies, folded.unterminated, self.lx, self.inner,
                    tuple(self.spans), folded.quoted)

    # -- the document, line by line ----------------------------------------------

    def read(self) -> Doc:
        """Read every line once. A definition's body is read as it arrives by a
        reader of its own — the stack's innermost — and ends with the `}` that
        balances its `{`; nesting grows the stack, not the Python call stack.

        Every open body counts the same braces on a line it does not close, so one
        running sum `acc` stands for all: body i's depth is offs[i] + acc. The
        bodies a line closes are those whose depth it takes to 0 or below; the
        outermost is found by bisecting the running minimum of offs. Inside it,
        each deeper body reads that line's text before its `}` as a line of its
        own, and ends there too if its `}` is in that text; a deeper body that
        does not is left unclosed (the model drops it)."""
        top = _DocReader(self, top=True)
        stack = [top]                       # each reader but the last has an open body
        offs: list = []                     # offs[i]: depth of stack[i]'s body, less acc
        lows: list = []                     # lows[i]: -min(offs[:i + 1]) (ascending)
        acc = 0
        for t, code in enumerate(self.codes):
            line = code.raw.strip()
            delta = (self.delta(self.lines[t].strip(), code.raw)
                     if offs and line and not line.startswith("#!") else 0)
            j = bisect_left(lows, acc + delta)
            if j == len(lows):              # closes no body: the innermost reads it
                acc += delta
                self._feed(stack, offs, lows, acc, t, None)
                continue
            # Body j closes; the text before its `}` goes on down the open bodies.
            text, tail = _close_head(code.raw.rstrip(), offs[j] + acc)
            closed = {j: tail}              # body index → the text after its `}`
            fed = set()                     # readers that read the line's text
            text = text if text.strip() else None
            i = j + 1
            while text is not None and i < len(stack):
                fed.add(i)
                if i == len(stack) - 1:
                    self._feed(stack, offs, lows, acc, t, text)
                    break
                stack[i].texts[t] = text
                t_line = text.strip()
                if t_line and not t_line.startswith("#!"):
                    before = offs[i] + acc
                    if before + self.delta(t_line, text) <= 0:
                        text, closed[i] = _close_head(text.rstrip(), before)
                        text = text if text.strip() else None
                i += 1
            while len(stack) > j + 1:
                child = stack.pop()
                offs.pop()
                lows.pop()
                home = stack[-1]
                if len(stack) - 1 in closed:
                    doc = child.finish(self._body_end(child, t, len(stack) in fed))
                    home.body_read(doc, True, closed[len(stack) - 1], t)
                else:
                    home.body_read(child.finish(t), False, "")
            acc += delta
        while len(stack) > 1:               # bodies left open at the end of the text
            child = stack.pop()
            stack[-1].body_read(child.finish(len(self.lines)), False, "")
        return top.finish(len(self.lines))

    def _feed(self, stack, offs, lows, acc, t, piece):
        """The innermost reader reads line t (`piece`: the text it reads instead of
        the line); a body that line opens is pushed and reads the text after its
        header's `{`."""
        p = stack[-1]
        if piece is not None:
            p.texts[t] = piece
        p.line(t, piece, 0)
        while p.opening is not None:
            b, p.opening = p.opening, None
            child = _DocReader(self, top=False)
            child.base = t if b.piece.strip() else t + 1
            child.item, child.def_line = b.item, b.line
            off = b.depth - acc
            offs.append(off)
            lows.append(max(lows[-1], -off) if lows else -off)
            stack.append(child)
            if not b.piece.strip():
                break
            child.texts[t] = b.piece
            child.line(t, b.piece, b.col)
            p = child

    def _body_end(self, child, t: int, fed: bool) -> int:
        """Where a body that line t closes ends (`fed`: the closing line's text
        before its `}` is its last line). A last blank line is no line of it."""
        end = t + 1 if fed else t
        if not fed and end > child.base and (end - 1) not in child.texts \
                and self.lines[end - 1] == "":
            end -= 1
        return end

    def delta(self, raw_lead: str, text: str) -> int:
        """Net braces a line opens. A raw-matched declaration opener (a `#…` marker,
        erased with the comment) counts on the raw line."""
        if any(on_raw and rx.match(raw_lead) for rx, on_raw in self.decl_blocks):
            return net_braces(raw_lead)
        return net_braces(text)

    def code(self, k: int, piece: Optional[str], shift: int) -> Code:
        if piece is None:
            return self.codes[k]
        c = code_line(piece, self.lx)
        return Code(c.text, c.raw, shift)

    # -- definition heads ------------------------------------------------------

    def definition_head(self, code: Code) -> Optional[tuple]:
        """(name, kind, dialect glyph text, column of the right-hand side) when the
        code is a definition `name := …` (`[name]`, `{name}`, a bare word, or a
        glyph the dialect's tokenizers read); else None."""
        raw = code.raw
        if ":=" not in raw:
            return None
        lead = len(raw) - len(raw.lstrip())
        t = raw.strip()
        am = ALIAS_RE.match(t)
        if am:
            name = (am.group("svc") or am.group("data") or am.group("word")).strip()
            kind = ("service" if am.group("svc") is not None
                    else "data" if am.group("data") is not None else None)
            return name, kind, None, lead + am.start("rhs")
        if not self.lx.tokenizers:
            return None
        from sigil.core.graph import Node
        s = mask_strings(raw)
        for tok in self.lx.tokenizers:
            hit = tok(s, lead, False, "L1", Node)
            if hit:
                new, end, _prev = hit
                dm = DEFINE_RE.match(s, end)
                if dm and any(kind == "glyph" for kind, _v in new):
                    name = raw[lead:end].strip("[]{}<>()|~* ")
                    return name, None, raw[lead:end], dm.start("rhs")
                return None
        return None

    def definition_name(self, code: Code) -> Optional[str]:
        head = self.definition_head(code)
        return head[0] if head else None

    # -- statements --------------------------------------------------------------

    def statement(self, k: int, code: Code, alias: bool, quiet: bool, shift: int) -> Statement:
        """Read one statement: its composition branch marker (the model's rule:
        at its start or after a glyph-only parent), the dialect's strips on what
        is left, and its tokens."""
        s = code.text
        lead = len(s) - len(s.lstrip())
        cont = bool(ARROW_RE.match(code.raw.strip()))
        m = BRANCH_RE.search(s, lead)
        if m is not None and m.start() > lead \
                and not BRANCH_PARENT_RE.match(code.raw[lead:m.start()]):
            m = None
        if m is None:
            marks = []
            x = BRANCH_ANY_RE.search(s, lead)
            if x is not None and (x.start() == lead
                                  or BRANCH_PARENT_RE.match(code.raw[lead:x.start()])):
                marks.append(x.start())
            body = self._strip(code, lead)
            toks = _shift(tokenize_statement(body, self.lx), 0)
            return Statement(k + 1, body, alias, tuple(toks), -1, tuple(marks), quiet, shift,
                             cont)
        marks = [m.start()] + [x.start() for x in BRANCH_ANY_RE.finditer(s, m.end())]
        later = [(x.start(), x.end()) for x in BRANCH_RE.finditer(s, m.end())]
        code = code.blank(later)
        left = self._strip(code.cut(0, m.start()), lead) if s[lead:m.start()].strip() else None
        rest = self._strip(code.cut(m.end()), 0)
        toks = (_shift(tokenize_statement(left, self.lx), 0) if left is not None else [])
        branch = len(toks)
        toks.append(Tok("branch", m.group(0), m.start()))
        toks += _shift(tokenize_statement(rest, self.lx), m.end())
        whole = Code((left.text if left is not None else code.text[:m.start()])
                     + code.text[m.start():m.end()] + rest.text,
                     (left.raw if left is not None else code.raw[:m.start()])
                     + code.raw[m.start():m.end()] + rest.raw, code.col)
        return Statement(k + 1, whole, alias, tuple(toks), branch, tuple(marks), quiet, shift,
                         cont)

    def _strip(self, code: Code, start: int) -> Code:
        """The code with the dialect's strips run on its text from `start` (they
        blank, never delete)."""
        if not self.lx.strips:
            return code
        before = code.raw[start:]
        after = before
        for strip in self.lx.strips:
            after = strip(after)
        if after == before:
            return code
        if len(after) != len(before):
            raise ValueError("a dialect strip must keep the line's length (blank, "
                             "never delete)")
        return code.blank([(start + i, start + i + 1)
                           for i, (a, b) in enumerate(zip(before, after)) if a != b])


def _shift(toks: list, by: int) -> list:
    return [t._replace(col=t.col + by) for t in toks] if by else list(toks)


def _close_head(stripped: str, before: int) -> tuple:
    """The line that closes a body open `before` deep: the text before its `}`
    (the body's last line) and the text after it (the defined node's
    modifiers)."""
    cut = close_at(stripped, before)
    if cut is None:
        return stripped, ""
    return stripped[:cut], stripped[cut + 1:]


class _DocReader:
    """One document level being read — the whole text, or a definition's body
    (read as a document of its own, as the model reads it): its items, its open
    control blocks, the `state` block or declaration it is inside, the body it
    is collecting, and lint's view of the subject a continuation line takes."""

    def __init__(self, w: _Walker, top: bool, alias: bool = False):
        self.w, self.top, self.alias = w, top, alias
        self.items: list = []
        self.frames: list = []
        self.opening: Optional[_Body] = None   # a body the last line opened
        self.open_body: Optional[tuple] = None  # (item, line) of the body being read
        self.base = 0                  # a body's first line
        self.item = self.def_line = 0  # a body's Definition (its index in the parent)
        self.state: Optional[_State] = None
        self.decl = None               # [(opener, on_raw), depth]
        self.decl_line = 0
        self.texts: dict = {}
        self.subject = False           # a flow above that a continuation line takes
        self.blank = False             # a blank line since the last statement
        self.content = False           # a statement sits in this document

    def read(self, entries: list) -> Doc:
        """Read a one-line body (its lines as (index, text, column)): a body its
        own line opens stays open — the model reads no further."""
        for k, piece, shift in entries:
            self.texts[k] = piece
            self.line(k, piece, shift)
        return self.finish(entries[-1][0] + 1 if entries else 0)

    def finish(self, end: int) -> Doc:
        unclosed = None
        if self.opening is not None:           # a body opened on the last line read
            b, self.opening = self.opening, None
            self.body_read(Doc((), b.line, None, False, {}), False, "")
        if self.open_body is not None:
            unclosed = self.open_body[1]
        if self.state is not None:
            st, self.state = self.state, None
            unclosed = st.head
            self.w.open_blocks.append(Block("state", st.head + 1, st.content, False))
        if self.decl is not None:
            unclosed = self.decl_line
        for fr in self.frames:
            self.w.open_blocks.append(Block(fr.kind, fr.line, fr.content, False))
        self.frames = []
        return Doc(tuple(self.items), end, unclosed, self.top, self.texts)

    def body_read(self, doc: Doc, closed: bool, tail: str, end: Optional[int] = None):
        """The body this reader's last definition opened is read: `doc` (`closed`
        by a `}` on line index `end`)."""
        item, line = self.open_body if self.open_body else (len(self.items) - 1, doc.end)
        self.open_body = None if closed else (item, self.items[item].line)
        content = any(isinstance(i, (Flow, Definition, BlockOpen, StateHead))
                      for i in doc.items)
        block = Block("alias", self.items[item].line + 1, content, closed)
        if closed:
            self.w.blocks.append(block)
            self.w.spans.append((block.line, end + 1))
        else:
            self.w.open_blocks.insert(0, block)
        self.items[item] = self.items[item]._replace(body=doc, closed=closed, tail=tail)

    # -- a line ------------------------------------------------------------------

    def line(self, k: int, piece: Optional[str], shift: int):
        w = self.w
        raw = piece if piece is not None else w.lines[k]
        code = w.code(k, piece, shift)
        raw_lead = raw.strip()
        line = code.raw.strip()
        if self.state is None and self.decl is None:
            c = None if piece is not None else (w.comments if self.top else w.inner).get(k)
            if c and c[1]:                  # a comment on its own line
                self.items.append(Note(k, c[0]))
                return
            if not line:
                self.items.append(Blank(k))
        if self._declaration(k, raw_lead, line):
            return
        if not line:
            if not raw_lead:
                self.blank = True
            return
        if self._section(k, line, code) or line.startswith("#!"):
            return
        if self.state is not None:
            self._state_line(k, line, code)
        elif line.startswith("--") and not ARROW_RE.match(line):
            # A malformed section header: read as a flow (the model's reading); lint
            # reports it by its own rule.
            w.sections.append((k + 1, code.text.strip()))
            self.statement(k, code, quiet=True, shift=shift)
        else:
            self.statement(k, code, shift=shift)
        self.blank = False

    def _declaration(self, k: int, raw_lead: str, line: str) -> bool:
        """Dialect declaration blocks: consumed whole, never read. A raw-matched
        opener (a `#…` marker, erased with the comment) counts on the raw line."""
        if self.decl is not None:
            txt = raw_lead if self.decl[0][1] else line
            self.decl[1] += net_braces(txt)
            if self.decl[1] <= 0:
                self.decl = None
                self.w.spans.append((self.decl_line + 1, k + 1))
            return True
        for opener, on_raw in self.w.decl_blocks:
            txt = raw_lead if on_raw else line
            if opener.match(txt):
                depth = net_braces(txt)
                self.decl = [(opener, on_raw), depth] if depth > 0 else None
                self.decl_line = k
                self.items.append(Declaration(k))
                self.subject = False
                return True
        return False

    def _section(self, k: int, line: str, code: Code) -> bool:
        sec = SECTION_RE.match(line)
        if not sec:
            return False
        self.w.sections.append((k + 1, code.text.strip()))
        self.items.append(SectionHead(k, sec.group(1), sec.group(2)))
        self.subject = False
        self.blank = False
        return True

    # -- statements --------------------------------------------------------------

    def statement(self, k: int, code: Code, quiet: bool = False, shift: int = 0):
        """One statement: a definition, a `state` head, a block header, a line
        inside / closing an open block, or a flow."""
        if not code.raw.strip():
            return
        if (self._definition(k, code, shift) or self._state_head(k, code)
                or self._block_head(k, code, shift)):
            return
        if self.frames:
            fr = self.frames[-1]
            before = fr.depth
            fr.depth += net_braces(code.raw)
            if fr.depth <= 0:                   # the line closes the innermost block
                cut = close_at(code.raw, before)
                cut = len(code.raw) if cut is None else cut
                if code.raw[:cut].strip():
                    self._flow(k, code.cut(0, cut), quiet, shift)
                self._close(k)
                rest = code.cut(cut + 1)
                if rest.raw.strip():            # `} !> [X]`, `} }`, `} @inv …`
                    if rest.raw.strip().startswith("@"):
                        self.items.append(BlockMods(k, rest.raw))
                    else:
                        self.statement(k, rest, quiet, shift)
                return
        self._flow(k, code, quiet, shift)

    def _mark_content(self):
        self.content = True
        if self.frames:
            self.frames[-1].content = True

    def _push(self, kind: str, k: int, glyphs: bool = False):
        self._mark_content()
        self.frames.append(_Frame(kind, k + 1, 1, glyphs=glyphs))
        self.subject = False

    def _close(self, k: int):
        fr = self.frames.pop()
        self.w.blocks.append(Block(fr.kind, fr.line, fr.content, True))
        self.w.spans.append((fr.line, k + 1))
        self.items.append(BlockClose(k))
        self.subject = fr.glyphs
        if self.frames:
            self.frames[-1].glyphs |= fr.glyphs

    # -- definitions ---------------------------------------------------------------

    def _definition(self, k: int, code: Code, shift: int) -> bool:
        """`name := …`: a `{ … }` body is read as a document of its own (the
        caller pushes its reader: `opening`); a one-line body (`X := { … }`,
        `X := expr`) is read at once."""
        head = self.w.definition_head(code)
        if head is None:
            return False
        name, kind, glyph, at = head
        self._mark_content()
        self.subject = False
        rhs_raw = code.raw[at:]
        lead = len(rhs_raw) - len(rhs_raw.lstrip())
        rhs = rhs_raw.strip()
        masked = mask_strings(rhs)
        rcol = code.col + at + lead            # the column rhs starts at
        item = len(self.items)
        if EXPANSION_OPEN_RE.match(masked) or masked.endswith("{"):
            if EXPANSION_OPEN_RE.match(masked):
                piece, pcol = rhs[1:], rcol + 1
            else:
                piece, pcol = "", rcol + len(rhs)
            self.items.append(Definition(k, name, kind, glyph, "block"))
            cut = close_at(piece, 1)
            if cut is not None:                 # `[X] := { … }`: its body is right here
                doc = _DocReader(self.w, top=False).read([(k, piece[:cut], pcol)])
                self.open_body = (item, k)
                self.body_read(doc, True, piece[cut + 1:], k)
            else:
                self.open_body = (item, k)
                self.opening = _Body(item, k, 1 + net_braces(piece), piece, pcol)
            return True
        self.items.append(Definition(k, name, kind, glyph, "inline", rhs=rhs))
        doc = _DocReader(self.w, top=False, alias=True).read([(k, rhs, rcol)])
        self.items[item] = self.items[item]._replace(body=doc, closed=True)
        return True

    # -- state machines --------------------------------------------------------------

    def _state_head(self, k: int, code: Code) -> bool:
        """`state <owner> { … }`: its lines are collected (transitions); with no
        owner glyph (`state {`, `state Foo {`) the block is consumed unread."""
        line = code.raw.strip()
        sm = STATE_HEAD_RE.match(line)
        if not sm:
            if not STATE_OPEN_RE.match(line):
                return False
            self._mark_content()
            self.items.append(StateHead(k, None))
            depth = net_braces(line)
            if depth > 0:
                self.state = _State(None, [], depth, k)
            else:
                self.items.append(StateEnd(k, (), "", k))
            return True
        self._mark_content()
        owner = sm.group(1)
        self.items.append(StateHead(k, owner))
        body = line[sm.end():]
        cut = close_at(body, 1)
        if cut is not None:                     # one line: `state {X} { A -> B }`
            text = body[:cut].strip()
            if text:
                self._transition(k, code, body[:cut])
            self.w.blocks.append(Block("state", k + 1, bool(text), True))
            self.w.spans.append((k + 1, k + 1))
            self.items.append(StateEnd(k, ((text, k),) if text else (),
                                       body[cut + 1:], k))
            return True
        self.state = _State(owner, [(body.strip(), k)] if body.strip() else [],
                            1 + net_braces(body), k)
        if body.strip():
            self.state.content = True
            self._transition(k, code, body)
        return True

    def _state_line(self, k: int, line: str, code: Code):
        st = self.state
        before = st.depth
        st.depth += net_braces(line)
        if st.depth > 0:
            st.lines.append((line, k))
            st.content = True
            self._transition(k, code, line)
            return
        cut = close_at(line, before)
        if cut is not None and line[:cut].strip():
            st.lines.append((line[:cut].strip(), k))
            st.content = True
            self._transition(k, code, line[:cut])
        tail = line[cut + 1:] if cut is not None else ""
        self.state = None
        self.w.blocks.append(Block("state", st.head + 1, st.content, True))
        self.w.spans.append((st.head + 1, k + 1))
        self.items.append(StateEnd(k, tuple(st.lines), tail, st.head))

    def _transition(self, k: int, code: Code, text: str):
        """Record a `state` block line for lint, its strings masked."""
        at = code.raw.find(text.strip())
        masked = code.text[at:at + len(text.strip())] if at >= 0 else mask_strings(text)
        self.w.transitions.append((k + 1, masked.strip()))

    # -- control blocks ------------------------------------------------------------

    def _block_head(self, k: int, code: Code, shift: int) -> bool:
        """A control-block header — `loop …`, `parallel …`, `branch on X`, a scoped
        `name {`, an `[X] @owns |R| {`, a dialect keyword — opens a block whose
        body statements are ordinary flows."""
        t = code.raw.strip()
        om = BLOCK_OPEN_RE.search(code.text)
        head_raw = code.raw[:om.start()] if om else code.raw
        hm = LOOP_HEAD_RE.match(t)
        if hm:
            kind = hm.group(1)
        elif self.w.keyword_re is not None and self.w.keyword_re.match(t):
            kind = "keyword"
        elif om and SCOPE_HEAD_RE.match(t):
            kind = "scope"
        elif om and "@owns" in head_raw and GLYPH_RE.search(head_raw):
            kind = "owns"
        else:
            return False
        head_text = code.text[:om.start()] if om else code.text
        self.w.headers.append(Header(kind, k + 1, head_text))
        if om is None:                          # a header with no body: nothing to read
            return True
        head = code.cut(0, om.start())
        header = None
        if kind == "owns":                      # the header is itself a statement
            header = self.w.statement(k, head, self.alias, False, shift)
            self.w.stmts.append(header)
            self._mark_content()
        toks = tuple(tokenize_statement(head, self.w.lx)) if kind != "owns" else header.toks
        body = code.cut(om.end())
        self.items.append(BlockOpen(k, kind, head.raw.strip(), toks, header, body.raw))
        glyphs = kind in ("branch", "owns") and bool(ANY_GLYPH_RE.search(head_text))
        self._push(kind, k, glyphs)
        if body.raw.strip():                    # statements after the header's `{`
            self.statement(k, body, shift=shift)
        return True

    # -- flows ---------------------------------------------------------------------

    def _flow(self, k: int, code: Code, quiet: bool, shift: int):
        """A flow statement: a branch arm's label is read off first."""
        t = code.raw.strip()
        fr = next((f for f in reversed(self.frames) if f.kind != "keyword"), None)
        arm = None
        if fr is not None and fr.kind == "branch":
            am = ARM_RE.match(t)
            if am and not ARROW_RE.match(t):
                fr.content = True
                self.subject = False
                arm = am.group("label")
                body = am.group("body")
                if not body.strip():
                    self.items.append(Flow(k, None, arm))
                    return
                code = code.cut(code.raw.find(body))
                t = body.strip()
        self._mark_content()
        masked = code.text.strip()
        bare = bool(BARE_BRANCH_RE.match(masked))
        if bare:
            self.w.bare.append((k + 1, masked))
        quiet = quiet or bare
        st = self.w.statement(k, code, self.alias, quiet, shift)
        if self.alias and not quiet:
            draws = ANY_GLYPH_RE.search(code.text) or DIALECT_COL in code.text
            if not (ARROW_RE.search(code.text) and draws):
                st = st._replace(quiet=True)
        has_glyph = bool(ANY_GLYPH_RE.search(code.text) or DIALECT_COL in code.text)
        lead = masked.lstrip("}").strip() if not self.frames else masked
        if ARROW_RE.match(lead):                # a continuation line
            self.w.continuations.append(Continuation(k + 1, lead, self.subject, self.blank))
        elif has_glyph and not bare:
            self.subject = True
            if self.frames:
                self.frames[-1].glyphs = True
        self.w.stmts.append(st)
        self.items.append(Flow(k, st, arm))
