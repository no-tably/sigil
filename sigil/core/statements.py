"""
statements — a document's statement walk: which lines are flows, block headers,
transitions or section headers, where each block opens and closes, and which
continuation lines have a flow above to continue. Each statement it finds is a
Code span (sigil.core.tokens) with its line and column, for
tokenize_statement to read.

    walk_statements(lines, masks=(), keywords=(), decl_blocks=()) → Walk

`lines` are the document's lines after the pre-passes (block strings folded,
composition markers masked); `masks` a dialect's length-preserving glyph masks,
`keywords` its block keywords, `decl_blocks` its declaration-block openers
(regex, on_raw). The walk only records what it reads; what is wrong with it is
for the reader to judge (lint's hardening rules).
"""

import re
from dataclasses import dataclass
from typing import NamedTuple

from sigil.core.lex import (
    ALIAS_MASKED_RE, ANY_GLYPH_RE, ARM_RE, ARROW_RE, BARE_BRANCH_RE, BLOCK_OPEN_RE,
    DIALECT_COL, LOOP_HEAD_RE, SCOPE_HEAD_RE, close_at, net_braces)
from sigil.core.tokens import Code, code_line


class Statement(NamedTuple):
    """A statement: its source line and its Code span. `alias` marks the body of
    a one-line definition (`[R] := [A] -> [B]`)."""
    line: int
    code: Code
    alias: bool = False

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


class Walk(NamedTuple):
    """What a statement walk read, each in reading order. `blocks`: the closed
    blocks as they close, then those left open (outermost first); `sections`,
    `transitions` and `bare_branches` are (line, text): a `--…` line, a line of
    a `state` block, a branch body written without its `\\-`; `definitions`:
    every name defined with `:=` in the document; `codes`: every line's Code."""
    statements: tuple
    blocks: tuple
    headers: tuple
    sections: tuple
    transitions: tuple
    bare_branches: tuple
    continuations: tuple
    definitions: frozenset
    codes: tuple


def walk_statements(lines: list, masks=(), keywords=(), decl_blocks=()) -> Walk:
    """Walk the document's lines (see the module notes)."""
    codes = [code_line(raw, masks) for raw in lines]
    walker = _Walker(definitions(codes), keywords, decl_blocks)
    for no, (raw, code) in enumerate(zip(lines, codes), 1):
        walker.line(no, raw.strip(), code)
    return walker.finish(tuple(codes))


def definitions(codes: list) -> frozenset:
    """Names defined with `:=` anywhere in the document (`[Data] := {` → "Data")."""
    out = set()
    for code in codes:
        m = ALIAS_MASKED_RE.match(code.text.strip())
        if m:
            out.add(_alias_name(m, code))
    return frozenset(out)


def _alias_name(m: re.Match, code: Code) -> str:
    """The name an `ALIAS_MASKED_RE` match defines; a dialect glyph (`[[rate]] := {`) is
    named by its raw text, less its brackets."""
    if m.group("dia") is None:
        return (m.group("svc") or m.group("data") or m.group("word")).strip()
    lead = len(code.text) - len(code.text.lstrip())
    return code.raw[lead + m.start("dia"):lead + m.end("dia")].strip("[]{}<>()|~* ")


@dataclass
class _Frame:
    kind: str             # alias state loop parallel branch scope owns keyword
    line: int
    depth: int
    content: bool = False   # any statement inside
    glyphs: bool = False    # a statement inside drew a glyph (the block's subject)


class _Walker:
    """Follows a document's blocks as the parser does. Feed lines in order with
    `line()`, then call `finish()` for the Walk."""

    def __init__(self, defined: frozenset, keywords=(), decl_blocks=()):
        self.defined = defined
        self.keyword_re = (re.compile(r"^(" + "|".join(map(re.escape, sorted(keywords)))
                                      + r")\b") if keywords else None)
        self.decl_blocks = list(decl_blocks)
        self.decl_depth = 0
        self.decl_on_raw = False
        self.frames: list = []
        self.subject = False        # a flow above that a continuation line takes
        self.blank = False          # a blank line since the last statement
        self.stmts: list = []
        self.blocks: list = []      # closed, as they close
        self.headers: list = []
        self.sections: list = []
        self.transitions: list = []
        self.bare: list = []
        self.continuations: list = []

    def line(self, no: int, raw_lead: str, code: Code):
        if self._declaration(raw_lead, code.text.strip()):
            return
        t = code.text.strip()
        if not t:
            if not raw_lead:
                self.blank = True
            return
        if t.startswith("#!"):
            return
        if self.frames and self.frames[-1].kind == "state":
            self._state_line(no, code)
        elif t.startswith("--") and not ARROW_RE.match(t):
            self.subject = False
            self.sections.append((no, t))
        else:
            self._statement(no, code)
        self.blank = False

    def finish(self, codes: tuple) -> Walk:
        unclosed = [Block(fr.kind, fr.line, fr.content, False) for fr in self.frames]
        self.frames = []
        return Walk(tuple(self.stmts), tuple(self.blocks + unclosed), tuple(self.headers),
                    tuple(self.sections), tuple(self.transitions), tuple(self.bare),
                    tuple(self.continuations), self.defined, codes)

    # -- line kinds ------------------------------------------------------------

    def _declaration(self, raw_lead: str, t: str) -> bool:
        """Dialect declaration blocks: consumed whole, never read."""
        if self.decl_depth > 0:
            self.decl_depth += net_braces(raw_lead if self.decl_on_raw else t)
            return True
        for opener, on_raw in self.decl_blocks:
            txt = raw_lead if on_raw else t
            if opener.match(txt):
                self.decl_depth = max(net_braces(txt), 0)
                self.decl_on_raw = on_raw
                self.subject = False
                return True
        return False

    def _statement(self, no: int, code: Code):
        t = code.text.strip()
        if self._alias(no, code) or self._state_head(no, code) or self._block_head(no, code):
            return
        if self.frames:
            fr = self.frames[-1]
            before = fr.depth
            fr.depth += net_braces(code.text)
            if fr.depth <= 0:
                cut = close_at(code.text, before)
                cut = len(code.text) if cut is None else cut
                if code.text[:cut].strip():
                    self._flow(no, code.cut(0, cut))
                self._close()
                rest = code.cut(cut + 1)
                if rest.text.strip() and not rest.text.strip().startswith("@"):
                    self._statement(no, rest)
                return
        if t:
            self._flow(no, code)

    def _mark_content(self):
        if self.frames:
            self.frames[-1].content = True

    def _push(self, kind: str, no: int, body: Code, glyphs: bool = False):
        """Open a block at line `no`; `body` is the header line's text after `{`."""
        self._mark_content()
        self.frames.append(_Frame(kind, no, 1, glyphs=glyphs))
        self.subject = False
        if body.text.strip():
            if kind == "state":
                self._state_line(no, body)
            else:
                self._statement(no, body)

    def _close(self):
        fr = self.frames.pop()
        self.blocks.append(Block(fr.kind, fr.line, fr.content, True))
        if fr.kind == "alias":
            self.subject = False
        elif fr.kind != "state":
            self.subject = fr.glyphs
        if self.frames:
            self.frames[-1].glyphs |= fr.glyphs

    def _alias(self, no: int, code: Code) -> bool:
        t = code.text.strip()
        m = ALIAS_MASKED_RE.match(t)
        if not m:
            return False
        self.subject = False
        rhs = m.group("rhs")
        at = code.text.index(rhs, code.text.index(":=")) if rhs else len(code.text)
        brace = (code.text.index("{", at) if BLOCK_OPEN_RE.match(rhs)
                 else code.text.rindex("{") if rhs.rstrip().endswith("{") else None)
        if brace is not None:
            self._push("alias", no, code.cut(brace + 1))
            self.subject = False
        else:
            self._mark_content()
            body = code.cut(at)
            # A one-line definition is a flow only when it draws one; otherwise it
            # is prose (`[R] := subgraph -> summary`) and the parser reads it so.
            draws = ANY_GLYPH_RE.search(body.text) or DIALECT_COL in body.text
            if ARROW_RE.search(body.text) and draws:
                self.stmts.append(Statement(no, body, True))
        return True

    def _state_head(self, no: int, code: Code) -> bool:
        t = code.text.strip()
        if not re.match(r"^state\b", t):
            return False
        om = BLOCK_OPEN_RE.search(code.text)
        if om is None:
            return True
        saved = self.subject                    # a state block keeps the subject
        self._push("state", no, code.cut(om.end()))
        self.subject = saved
        return True

    def _block_head(self, no: int, code: Code) -> bool:
        t = code.text.strip()
        om = BLOCK_OPEN_RE.search(code.text)
        head = code.text[:om.start()] if om else code.text
        hm = LOOP_HEAD_RE.match(t)
        if hm:
            kind = hm.group(1)
        elif self.keyword_re is not None and self.keyword_re.match(t):
            kind = "keyword"
        elif om and SCOPE_HEAD_RE.match(t):
            kind = "scope"
        elif om and "@owns" in head and ANY_GLYPH_RE.search(head):
            kind = "owns"
        else:
            return False
        self.headers.append(Header(kind, no, head))
        if om is None:
            return True
        # A branch's subject is what it branches on; an owns block's, its owner.
        glyphs = kind in ("branch", "owns") and bool(ANY_GLYPH_RE.search(head))
        self._push(kind, no, code.cut(om.end()), glyphs)
        return True

    def _state_line(self, no: int, code: Code):
        fr = self.frames[-1]
        t = code.text.strip()
        before = fr.depth
        fr.depth += net_braces(t)
        if fr.depth <= 0:
            cut = close_at(t, before)
            t = t[:cut] if cut is not None else t
            if t.strip():
                fr.content = True
                self.transitions.append((no, t))
            self._close()
            return
        fr.content = True
        self.transitions.append((no, t))

    def _flow(self, no: int, code: Code):
        t = code.text.strip()
        fr = self.frames[-1] if self.frames else None
        if fr is not None and fr.kind == "branch":
            am = ARM_RE.match(t)
            if am and not ARROW_RE.match(t):
                fr.content = True
                self.subject = False
                body = am.group("body")
                if not body.strip():
                    return
                code = code.cut(code.text.rindex(body))
                t = body.strip()
        self._mark_content()
        if BARE_BRANCH_RE.match(t):
            self.bare.append((no, t))
            return
        has_glyph = bool(ANY_GLYPH_RE.search(code.text) or DIALECT_COL in code.text)
        if ARROW_RE.match(t):                           # a continuation line
            self.continuations.append(Continuation(no, t, self.subject, self.blank))
        elif has_glyph:
            self.subject = True
            if fr is not None:
                fr.glyphs = True
        self.stmts.append(Statement(no, code))
