"""
sigil.present.highlight — sigil source as coloured runs: each line split into
(text, role) runs, a role being a theme path ("syntax.operator", "kinds.service",
"ui.mode" …) or None for plain text. The reading is pure: no file is read,
nothing is printed; only the hosts' end (below) loads a theme or a dialect and
writes to the stream it is handed.

    lexicon(dialect) → Lexicon         what a dialect adds to reading a line
    lines(text, dialect=None) → [Line] every line of a text, highlighted
    line(raw, carry, lx) → (runs, carry)
                                       one line, from the carry state it starts
                                       in to the one the next line starts in
    edit(old, raws, start, end, lx, carry) → ([Line], stop)
                                       after an edit, only the lines whose runs
                                       can have changed are highlighted again
    colour(role, theme, lx) → "#rrggbb" | None
                                       a role's colour in a resolved theme
                                       (sigil.present.themes.load())

and, for `sigil highlight` (the hosts' end, at the bottom of this module):

    theme_for(spec, dialect) → (theme, name)
                                       the theme a command colours with
    write_text(text, out, theme, name, lx, as_json, colour)
                                       a file in ANSI, or as its --json object
    serve(inp, out, theme, name, lx, dialect, explicit) → exit status
                                       the --stream session (HIGHLIGHT_PROTOCOL):
                                       JSON-lines requests in, answers out; a
                                       {"dialect"} request loads it through Core

One token model: the roles come from Core's own reading — each statement read by
sigil.core.statements.read_statement (the walk's reading: branch marker, the
dialect's strips, sigil.core.tokens' tokens with their columns), a `state` block
line by statements.read_transition's pattern, section headers by lex.SECTION_RE,
the mode, `#%` kind and `#&` declaration lines by lex / kinds, comments where
lex.code_end cuts the code, and a payload's or argument's finer pieces by
lex.PAYLOAD_PIECE_RE (the split kit draws payloads with, read a little finer:
_piece_re). Nothing here decides
what text means; it only names a colour for each character.

Laws (tests/test_highlight.py): every character of a line is in exactly one
run, so a line's runs joined give the line back; any text highlights (text that
does not lint, half-typed glyphs, unbalanced brackets) and nothing raises; a
line's runs depend only on the line and the carry state it starts in, so
`lines(text)` equals highlighting line by line with the carry, and after an edit
highlighting from the changed line until the carry matches the old one gives
what a full highlight gives.

The carry (Carry, a small hashable tuple) is what one line hands the next — the
constructs of sigil that span lines:
    quote   inside a `\"\"\"…\"\"\"` block string (language.md: sigil's one
            multiline construct)
    decl    inside the `{ … }` body of a `#&` declaration (or a dialect's
            DECLARATION_BLOCKS opener): its brace depth, and whether its braces
            count on the raw line (`decl_raw`, a `#…` opener) or on its code
    state   inside a `state … { … }` block: its brace depth (its lines are
            transitions, read by their own pattern)
A continued trailing comment is one comment to the model, but its lines are
comment text either way, so it changes no role and is no part of the carry.
Definitions, control blocks and branch arms need none: their lines read as
statements whatever encloses them.

Roles (a theme section and key):
    syntax.operator      arrows, `:=`, joins `&` `&?` `/`, branch markers `\\-…`
                         (but their `{cond}` and `(N)`), a transition's `-<` `>->`
    syntax.keyword       glyph brackets and `~` / `*` prefixes, `state loop
                         parallel branch` (+ `on`, `op`, a dialect's
                         BLOCK_KEYWORDS), a `#%` line's known words, a `#&`
                         declaration's name
    syntax.modifier      `@name` (the `@policy` of `^N@policy` too), `!`, `?`, an
                         alias reference after `×N`
    syntax.cardinality   `×N`, `xN`, `^N`
    syntax.string        `"…"` and block strings
    syntax.ref           `${…}`
    syntax.number        numbers in payloads and arguments (with a unit: `2s`,
                         `1min`, `99.95%`), number words, a branch's `(N)` weight
    syntax.punct         `:`, `{` `}` of blocks, `( ) , [ ]` in payloads, `()`,
                         state anchors `+ $ _`, the wildcard `_` (a default arm)
    syntax.tag           bare words: state names outside a `state` block,
                         branch labels, `.field`
    syntax.call          a call's `( )` in a payload; syntax.call_name its name
    kinds.<kind>         a glyph's name in its kind's colour (service, data,
                         event, actor, store, hole, a dialect's kinds); a state
                         name in a `state` block is kinds.state, a branch
                         marker's `{cond}` kinds.data
    ui.mode              the `#!mode` line, the `#%` and `#&` marks
    ui.section           a `--- section ---` header
    ui.note_tag          a comment's marker (`#`, a dialect's markers)
    ui.note              a comment's text
    ui.payload           what a declaration holds (its line after the name, its
                         body): dialect text core does not read
    None                 anything else (spaces, words in a payload, text the
                         reading skips or finds malformed)

A dialect's `prepasses` are not run: they rewrite whole documents, and a line
here is read on its own.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import NamedTuple, Optional

from sigil.core.dialects import _hook
from sigil.core.dialects import load as load_dialect
from sigil.core.kinds import CHOICE_OF, KIND_MARK, is_kind_line
from sigil.core.lex import (
    BLOCK_DELIM, DECLARATION_RE, GLYPH_BRACKETS, GLYPH_PREFIXES, MOD_NAME_RE,
    OP_HEAD_RE, PAYLOAD_PIECE_RE, SECTION_RE, STATE_HEAD_RE, STATE_OPEN_RE, block_open_pos,
    close_at, declaration_name, glyph_kind, is_mode_line, net_braces)
from sigil.core.statements import TRANSITION_RE, read_statement
from sigil.core.tokens import NO_DIALECT, Code, code_line, lexicon as core_lexicon
from sigil.core.tokens import Lexicon as CoreLexicon
from sigil.present import themes


# ---------------------------------------------------------------------------
# What a dialect adds
# ---------------------------------------------------------------------------

class Lexicon(NamedTuple):
    """What reading a line takes from a dialect: `core` (sigil.core.tokens'
    Lexicon: tokenizers, strips, comment markers), `decl_blocks` (its
    DECLARATION_BLOCKS: (pattern, on_raw)), `keywords` (its BLOCK_KEYWORDS) and
    `kinds` ((kind, open, close, colour) for each of its NODE_KINDS)."""
    core: CoreLexicon = NO_DIALECT
    decl_blocks: tuple = ()
    keywords: frozenset = frozenset()
    kinds: tuple = ()


CORE = Lexicon()


@lru_cache(maxsize=64)
def lexicon(dialect) -> Lexicon:
    """The Lexicon of a loaded dialect (None: core Sigil)."""
    if dialect is None:
        return CORE
    kinds = tuple((kind, spec.get("open") or "", spec.get("close") or "", spec.get("color"))
                  for kind, spec in dict(_hook(dialect, "NODE_KINDS", {})).items()
                  if isinstance(spec, dict))
    return Lexicon(core_lexicon(dialect), tuple(_hook(dialect, "DECLARATION_BLOCKS")),
                   frozenset(_hook(dialect, "BLOCK_KEYWORDS", set())), kinds)


# ---------------------------------------------------------------------------
# Lines and their carry
# ---------------------------------------------------------------------------

class Carry(NamedTuple):
    """The state a line starts in (see the module notes)."""
    quote: bool = False
    decl: int = 0
    decl_raw: bool = True
    state: int = 0


PLAIN = Carry()


class Line(NamedTuple):
    """A highlighted line: its runs ((text, role) pairs, joined: the line), the
    carry state it starts in and the one it hands the next line."""
    runs: tuple
    start: Carry
    end: Carry

    @property
    def text(self) -> str:
        return "".join(text for text, _role in self.runs)


def lines(text: str, dialect=None) -> list:
    """Every line of `text` (str.splitlines, as the walk splits it), highlighted."""
    lx = lexicon(dialect)
    out, carry = [], PLAIN
    for raw in text.splitlines():
        runs, end = line(raw, carry, lx)
        out.append(Line(runs, carry, end))
        carry = end
    return out


def line(raw: str, carry: Carry = PLAIN, lx: Lexicon = CORE) -> tuple:
    """One line's runs and the carry the next line starts in. Never raises on
    text: a reading that fails on a malformed line leaves it plain."""
    roles: list = [None] * len(raw)
    try:
        carry = _line(raw, carry, lx, roles)
    except Exception:                       # never an error for bad text
        roles = [None] * len(raw)
        carry = _fallback_carry(raw, carry)
    return _runs(raw, roles), carry


def edit(old: list, raws: list, start: int, end: int, lx: Lexicon = CORE,
         carry: Carry = PLAIN) -> tuple:
    """Highlight a text again after an edit. `old`: the Lines before it; `raws`:
    every line after it; new lines [start, end) replace old lines [start, end +
    len(old) - len(raws)). Lines before `start` keep their runs; from `start` on
    each line is highlighted again until one past the edit starts in the carry
    its old line started in — from there on nothing can differ. `carry`: the
    state the text's first line starts in (a text's start; a part of a longer
    text, as --stream gets one, starts where that part does). Returns (the new
    Lines, the index past the last line highlighted again)."""
    shift = len(old) - len(raws)
    out = list(old[:start])
    carry = out[-1].end if out else carry
    j = start
    while j < len(raws):
        k = j + shift
        if j >= end and 0 <= k < len(old) and old[k].start == carry:
            return out + list(old[k:]), j
        runs, nxt = line(raws[j], carry, lx)
        out.append(Line(runs, carry, nxt))
        carry = nxt
        j += 1
    return out, j


def _runs(raw: str, roles: list) -> tuple:
    """The roles of a line's characters as runs: one run per stretch of one role."""
    runs, at = [], 0
    for k in range(1, len(raw) + 1):
        if k == len(raw) or roles[k] != roles[at]:
            runs.append((raw[at:k], roles[at]))
            at = k
    return tuple(runs)


def _fallback_carry(raw: str, carry: Carry) -> Carry:
    """The carry past a line no reading could take (never expected): a block
    string still opens or closes on it."""
    if raw.count(BLOCK_DELIM) % 2:
        return carry._replace(quote=not carry.quote)
    return carry


# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------

_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})")


def colour(role: Optional[str], theme: dict, lx: Lexicon = CORE) -> Optional[str]:
    """A role's colour in a resolved theme (themes.load()): "#rrggbb", or None for
    plain text and for a role the theme gives no colour. A dialect kind the theme
    does not colour takes its NODE_KINDS colour."""
    if not role or "." not in role:
        return None
    section, key = role.split(".", 1)
    sec = theme.get(section) if isinstance(theme, dict) else None
    value = sec.get(key) if isinstance(sec, dict) else None
    if value is None and section == "kinds":
        value = next((c for kind, _o, _c, c in lx.kinds if kind == key), None)
    if not isinstance(value, str) or not _HEX_RE.fullmatch(value):
        return None
    value = value.lower()
    return value if len(value) == 7 else "#" + "".join(ch * 2 for ch in value[1:])


# ---------------------------------------------------------------------------
# Reading a line
# ---------------------------------------------------------------------------

STRING, PUNCT, OPERATOR, KEYWORD = "syntax.string", "syntax.punct", "syntax.operator", \
    "syntax.keyword"
MODIFIER, CARD, TAG = "syntax.modifier", "syntax.cardinality", "syntax.tag"
NOTE, NOTE_TAG, MODE, SECTION, HELD = "ui.note", "ui.note_tag", "ui.mode", "ui.section", \
    "ui.payload"
STATE = "kinds.state"

# Words that open a control block (lex.LOOP_HEAD_RE, STATE_OPEN_RE's `state`).
_BLOCK_WORDS = frozenset({"state", "loop", "parallel", "branch"})


def _piece_re() -> "re.Pattern":
    """lex.PAYLOAD_PIECE_RE read finer, as the editor grammars read held text
    (highlight/README.md): a `[` that opens `${…}` is a list, not a glyph
    (`[${out}]`); a hyphenated word is one word (`exp-backoff`, a call
    `surfaces-flagged(…)`), its `-` no operator; a number takes its unit (`2s`,
    `1min`, `99.95%`). kit's drawings keep PAYLOAD_PIECE_RE as it is (their
    goldens would move), so the difference lives here, each step checked."""
    rx = PAYLOAD_PIECE_RE.pattern
    for old, new in ((r"(?:\[[^\]\s,]", r"(?:\[(?!\$\{)[^\]\s,]"),
                     (r"(?P<call>[A-Za-z_][\w.]*)", r"(?P<call>[A-Za-z_][\w.]*(?:-[\w.]+)*)"),
                     (r"[+\-*/])", r"[+*/]|(?<!\w)-|-(?!\w))"),
                     (r"(?P<number>\b\d+(?:\.\d+)?\b)",
                      r"(?P<number>\b\d+(?:\.\d+)?(?:[A-Za-z%]+\b|%|\b))")):
        if rx.count(old) != 1:
            raise AssertionError(f"PAYLOAD_PIECE_RE changed: {old!r} not found once")
        rx = rx.replace(old, new)
    return re.compile(rx, PAYLOAD_PIECE_RE.flags)


_PIECE_RE = _piece_re()
# A branch marker's interior: `\-{cond}-…` (its cond a data name) or `\-(N)-…`
# (its weight a number); the rest of the marker is its operator.
_BRANCH_INNER_RE = re.compile(r"\\-(?:\*-)?(?:\{(?P<cond>[^{}]*)\}-|\((?P<weight>\d+)\)-)")
# A state block's anchors: the start `+`, the end `$`, any state `_`.
_ANCHORS = frozenset({"+", "$", "_"})


def _paint(roles: list, start: int, end: int, role) -> None:
    """Set the role of columns [start, end) (clipped to the line)."""
    end = min(end, len(roles))
    for k in range(max(start, 0), end):
        roles[k] = role


def _placeholder(n: int) -> str:
    """A `"…"` string `n` columns wide (n ≥ 2): where a block string stands while
    its line is read (lex.fold_block_strings folds it to a string too)."""
    return '"' + "x" * (n - 2) + '"'


def _line(raw: str, carry: Carry, lx: Lexicon, roles: list) -> Carry:
    if carry.quote:
        close = raw.find(BLOCK_DELIM)
        if close < 0:
            _paint(roles, 0, len(raw), STRING)
            return carry
        cut = close + len(BLOCK_DELIM)
        _paint(roles, 0, cut, STRING)
        carry = carry._replace(quote=False)
        if not raw[cut:].strip():
            return carry
        # What follows the closing `"""` goes on reading (the fold reads it on).
        rest = [None] * len(raw)
        carry = _folded(" " * cut + raw[cut:], carry, lx, rest)
        roles[cut:] = rest[cut:]
        return carry
    return _folded(raw, carry, lx, roles)


def _folded(raw: str, carry: Carry, lx: Lexicon, roles: list) -> Carry:
    """A line with each block string it opens folded to a string of its own width
    (lex.fold_block_strings' reading), then read; the block strings painted."""
    work, spans, opened = raw, [], False
    while True:
        at = block_open_pos(work)
        if at is None:
            break
        close = work.find(BLOCK_DELIM, at + len(BLOCK_DELIM))
        if close < 0:
            spans.append((at, len(work)))
            work = work[:at] + _placeholder(len(work) - at)
            opened = True
            break
        stop = close + len(BLOCK_DELIM)
        spans.append((at, stop))
        work = work[:at] + _placeholder(stop - at) + work[stop:]
    carry = _read(work, carry, lx, roles)
    for start, stop in spans:
        _paint(roles, start, stop, STRING)
    return carry._replace(quote=True) if opened else carry


def _read(raw: str, carry: Carry, lx: Lexicon, roles: list) -> Carry:
    """A line (block strings folded) in the carry it starts in."""
    lead_at = len(raw) - len(raw.lstrip())
    lead = raw.strip()
    if carry.decl:
        # A declaration's body: consumed whole by core (its braces counted on the
        # raw line for a `#…` opener, else on its code).
        _paint(roles, lead_at, lead_at + len(lead), HELD)
        text = lead if carry.decl_raw else code_line(raw, lx.core).raw
        depth = carry.decl + net_braces(text)
        return carry._replace(decl=max(depth, 0), decl_raw=True if depth <= 0 else
                              carry.decl_raw)
    if carry.state:
        return _state_line(raw, carry, lx, roles)
    if not lead:
        return carry
    if is_mode_line(raw):
        _paint(roles, lead_at, lead_at + len(lead), MODE)
        return carry
    if is_kind_line(raw):
        _kind_line(raw, lead_at, roles)
        return carry
    code = code_line(raw, lx.core)
    opened = _declaration(raw, lead, lead_at, code, lx, roles)
    if opened is not None:
        return carry._replace(decl=opened[0], decl_raw=opened[1])
    _comment(raw, len(code.raw), roles, lx.core.marker)
    head = code.raw.strip()
    if not head:
        return carry
    at = len(code.raw) - len(code.raw.lstrip())
    if head.startswith("--") and SECTION_RE.match(head):
        _paint(roles, at, at + len(head), SECTION)
        return carry
    if "state" in head and (STATE_HEAD_RE.match(head) or STATE_OPEN_RE.match(head)):
        return _state_head(raw, code, at, carry, lx, roles)
    _statement(code, lx, roles)
    return carry


def _comment(raw: str, start: int, roles: list, marker=None) -> None:
    """The comment from `start` (where the code ends): its marker (`#`, or one of
    a dialect's comment markers), then its text."""
    body = raw[start:]
    if not body.strip():
        return
    at = start + len(body) - len(body.lstrip())
    m = marker.match(raw, at) if marker is not None and raw[at] != "#" else None
    end = m.end() if m is not None and m.end() > at else at + 1
    _paint(roles, at, end, NOTE_TAG)
    _paint(roles, end, len(raw.rstrip()), NOTE)


def _kind_line(raw: str, at: int, roles: list) -> None:
    """A `#%` line: its mark, its words (a known one as a keyword), its comment."""
    _paint(roles, at, at + len(KIND_MARK), MODE)
    body_at = at + len(KIND_MARK)
    hash_at = raw.find("#", body_at)            # kinds.kind_words: words end at a `#`
    stop = len(raw) if hash_at < 0 else hash_at
    for m in re.finditer(r"\S+", raw[body_at:stop]):
        if m.group(0) in CHOICE_OF:
            _paint(roles, body_at + m.start(), body_at + m.end(), KEYWORD)
    if hash_at >= 0:
        _comment(raw, hash_at, roles)


def _declaration(raw: str, lead: str, lead_at: int, code: Code, lx: Lexicon,
                 roles: list) -> Optional[tuple]:
    """A declaration line — a `#& name …` (core's, any name, declared or not) or
    a dialect's DECLARATION_BLOCKS opener: painted, and (depth, on_raw) of the
    body it leaves open (depth 0: none). None when the line is none."""
    on_raw = None
    if declaration_name(lead) is not None:
        on_raw = True
        m = DECLARATION_RE.match(lead)
        mark = lead.index("#&")
        _paint(roles, lead_at + mark, lead_at + mark + 2, MODE)
        name_at = lead_at + m.start("name")
        _paint(roles, name_at, lead_at + m.end("name"), KEYWORD)
        _paint(roles, lead_at + m.end("name"), lead_at + len(lead), HELD)
        _blank_spaces(raw, roles, lead_at + m.end("name"))
    else:
        head = code.raw.strip()
        for rx, raw_match in lx.decl_blocks:
            if (raw_match and rx.match(lead)) or (not raw_match and rx.match(head)):
                on_raw = bool(raw_match)
                break
        if on_raw is None:
            return None
        _paint(roles, lead_at, lead_at + len(lead), HELD)
    depth = net_braces(lead if on_raw else code.raw.strip())
    return (depth, on_raw) if depth > 0 else (0, True)


def _blank_spaces(raw: str, roles: list, start: int) -> None:
    """Leave the spaces between a held text's words plain where they lead it."""
    k = start
    while k < len(raw) and raw[k].isspace():
        roles[k] = None
        k += 1


# -- state blocks ---------------------------------------------------------------

def _state_head(raw: str, code: Code, at: int, carry: Carry, lx: Lexicon,
                roles: list) -> Carry:
    """`state <owner> {` (a body may follow on the line, or end on it)."""
    head = code.raw.strip()
    sm = STATE_HEAD_RE.match(head)
    if sm is None:                          # no owner: the block is consumed unread
        _statement(code, lx, roles)
        depth = net_braces(head)
        return carry._replace(state=depth) if depth > 0 else carry
    body_at = at + sm.end()
    _statement(Code(code.text[:body_at], code.raw[:body_at]), lx, roles)
    body = code.raw[body_at:]
    cut = close_at(body, 1)
    if cut is None:
        if body.strip():
            _transition(code, body_at, len(code.raw), lx, roles)
        return carry._replace(state=1 + net_braces(body))
    _transition(code, body_at, body_at + cut, lx, roles)
    _paint(roles, body_at + cut, body_at + cut + 1, PUNCT)
    _statement(_piece(code, body_at + cut + 1, len(code.raw)), lx, roles)
    return carry


def _state_line(raw: str, carry: Carry, lx: Lexicon, roles: list) -> Carry:
    """A line inside a `state` block: transitions, up to the `}` that ends it."""
    code = code_line(raw, lx.core)
    _comment(raw, len(code.raw), roles, lx.core.marker)
    depth = carry.state + net_braces(code.raw)
    if depth > 0:
        _transition(code, 0, len(code.raw), lx, roles)
        return carry._replace(state=depth)
    cut = close_at(code.raw, carry.state)
    if cut is None:                         # unbalanced the other way: the block ends
        _transition(code, 0, len(code.raw), lx, roles)
        return carry._replace(state=0)
    _transition(code, 0, cut, lx, roles)
    _paint(roles, cut, cut + 1, PUNCT)
    _statement(_piece(code, cut + 1, len(code.raw)), lx, roles)   # `} @inv …`
    return carry._replace(state=0)


def _piece(code: Code, start: int, end: int) -> Code:
    """Columns [start, end) of a line's code, the rest blanked: read on its own,
    its tokens keep the line's columns."""
    n = len(code.raw)
    end = min(end, n)
    return Code(" " * start + code.text[start:end] + " " * (n - end),
                " " * start + code.raw[start:end] + " " * (n - end))


def _transition(code: Code, start: int, end: int, lx: Lexicon, roles: list) -> None:
    """A `state` block line in columns [start, end): `Src -<E>-> Dst …` or `Src ->
    Dst …` (statements.TRANSITION_RE), its trailing modifiers read as a
    statement's; any other text read as a statement."""
    seg = code.text[start:end]
    text = seg.strip()
    if not text:
        return
    off = start + len(seg) - len(seg.lstrip())
    m = TRANSITION_RE.match(text)
    if m is None:
        _statement(_piece(code, start, end), lx, roles)
        return
    for g in (1, 3):
        name = m.group(g)
        _paint(roles, off + m.start(g), off + m.end(g), PUNCT if name in _ANCHORS else STATE)
    arrow_at, arrow_end = off + m.end(1), off + m.start(3)
    if m.group(2) is None:
        k = code.text.find("->", arrow_at, arrow_end)
        _paint(roles, k, k + 2, OPERATOR)
    else:
        k = code.text.find("-<", arrow_at, arrow_end)
        _paint(roles, k, k + 1, OPERATOR)
        _paint(roles, k + 1, k + 2, KEYWORD)
        lo, hi = off + m.start(2), off + m.end(2)
        for item in re.finditer(r"[^,\s]+|,", code.text[lo:hi]):
            role = PUNCT if item.group(0) == "," else "kinds.event"
            _paint(roles, lo + item.start(), lo + item.end(), role)
        _paint(roles, hi, hi + 1, KEYWORD)
        _paint(roles, hi + 1, hi + 3, OPERATOR)
    if m.group(4):
        _statement(_piece(code, off + m.start(4), end), lx, roles)


# -- statements -----------------------------------------------------------------

def _statement(code: Code, lx: Lexicon, roles: list) -> None:
    """A statement as Core reads it (statements.read_statement), its tokens
    painted: the payload first, then every other token over it."""
    if not code.raw.strip():
        return
    st = read_statement(0, code, lx.core)
    toks = sorted(st.toks, key=lambda t: t.kind != "payload")
    words = [t for t in st.toks if t.kind == "word"]
    first = st.toks[0] if st.toks else None
    for t in toks:
        _token(t, code, lx, roles, first, words)


def _token(t, code: Code, lx: Lexicon, roles: list, first, words: list) -> None:
    at, end = t.col, t.col + len(t.text)
    kind = t.kind
    if kind == "payload":
        stop = t.end if t.end >= 0 else len(code.raw)
        _paint(roles, at, at + 1, PUNCT)
        _pieces(code.raw, at + 1, stop, roles)
    elif kind == "glyph":
        _glyph(code.raw[at:end], at, roles, t.node, lx)
    elif kind in ("arrow", "join", "slash", "alias"):
        _paint(roles, at, end, OPERATOR)
    elif kind == "branch":
        _branch(t.text, at, roles)
    elif kind in ("card", "bound"):
        # `^10k@drop`: the bound, then its overflow policy (a modifier, as every
        # `@`-word reads)
        cut = t.text.find("@")
        cut = len(t.text) if cut < 0 else cut
        _paint(roles, at, at + cut, CARD)
        _paint(roles, at + cut, end, MODIFIER)
    elif kind in ("mark", "aref"):
        _paint(roles, at, end, MODIFIER)
    elif kind == "mod":
        m = MOD_NAME_RE.match(code.raw, at)
        name_end = m.end() if m else at + 1
        _paint(roles, at, name_end, MODIFIER)
        _pieces(code.raw, name_end, min(end, len(code.raw)), roles)
    elif kind in ("nothing", "blockopen", "blockclose"):
        _paint(roles, at, end, PUNCT)
    elif kind == "str":
        _paint(roles, at, end, STRING)
    elif kind == "field":
        _paint(roles, at, end, TAG)
    elif kind in ("evarg", "set"):         # a set `{a, b}` reads as held text does
        _pieces(code.raw, at, end, roles)
    elif kind == "op":
        _op(code.raw, at, end, roles)
    elif kind == "word":
        _paint(roles, at, end, _word_role(t, first, words, lx))


def _word_role(t, first, words: list, lx: Lexicon) -> str:
    """A word's role: a block keyword leading its statement (and the `on` of
    `branch on`, the `of` of `loop @each x of`), `op`, a `${…}` reference, a
    number, else a bare name."""
    text = t.text
    if text.startswith("${"):
        return "syntax.ref"
    if t is first and (text in _BLOCK_WORDS or text in lx.keywords):
        return KEYWORD
    if text == "on" and len(words) > 1 and words[1] is t and words[0] is first \
            and first.text == "branch":
        return KEYWORD
    if text == "op" or (text == "of" and first is not None and first.text == "loop"):
        return KEYWORD
    if text[:1].isdigit():
        return "syntax.number"
    if text == "_":                         # the wildcard (a branch's default arm)
        return PUNCT
    return TAG


def _branch(text: str, at: int, roles: list) -> None:
    """A composition-tree marker: an operator, its `{cond}` name a data glyph's
    name and its `(N)` weight a number (as the grammars read them)."""
    _paint(roles, at, at + len(text), OPERATOR)
    m = _BRANCH_INNER_RE.match(text)
    if m is None:
        return
    if m.group("cond") is not None:
        _paint(roles, at + m.start("cond"), at + m.end("cond"), "kinds.data")
    else:
        _paint(roles, at + m.start("weight"), at + m.end("weight"), "syntax.number")


def _glyph(text: str, at: int, roles: list, node=None, lx: Lexicon = CORE) -> None:
    """A glyph: its prefixes and brackets as keywords, its name in its kind's
    colour (a dialect glyph's brackets are its kind's own)."""
    if node is not None:
        kind = getattr(node, "kind", None)
        spec = next(((o, c) for k, o, c, _col in lx.kinds if k == kind), ("", ""))
    else:
        kind = glyph_kind(text)
        spec = GLYPH_BRACKETS.get(kind, ("", ""))
    if not kind:
        _paint(roles, at, at + len(text), PUNCT)
        return
    lead = len(text) - len(text.lstrip(GLYPH_PREFIXES)) if node is None else 0
    body = text[lead:]
    op, cl = spec
    if not (op and body.startswith(op)):
        op = body[:1] if node is None else ""
    if not (cl and body.endswith(cl) and len(body) >= len(op) + len(cl)):
        cl = ""
    name = body[len(op):len(body) - len(cl)]
    _paint(roles, at, at + lead + len(op), KEYWORD)
    role = "kinds.hole" if name.strip() == "?" else f"kinds.{kind}"
    _paint(roles, at + lead + len(op), at + lead + len(op) + len(name), role)
    _paint(roles, at + len(text) - len(cl), at + len(text), KEYWORD)


def _pieces(raw: str, start: int, end: int, roles: list) -> None:
    """Text a statement holds as one span (a payload, a modifier's argument, an
    event's argument) by its pieces (lex.PAYLOAD_PIECE_RE): a call's name and its
    `( )` as calls, glyphs as glyphs, the rest by their role."""
    if start >= end:
        return
    parens, pending = [], False
    for m in _PIECE_RE.finditer(raw, start, end):
        role, a, b = m.lastgroup, m.start(), m.end()
        tok = m.group()
        if role == "glyph":
            _glyph(tok, a, roles)
        elif role == "call":
            _paint(roles, a, b, "syntax.call_name")
            pending = True
            continue
        elif tok == "(":
            parens.append(pending)
            _paint(roles, a, b, "syntax.call" if pending else PUNCT)
        elif tok == ")":
            _paint(roles, a, b, "syntax.call" if parens and parens.pop() else PUNCT)
        else:
            _paint(roles, a, b, f"syntax.{role}")
        pending = False


def _op(raw: str, start: int, end: int, roles: list) -> None:
    """An op-call target `op ns.verb(args)` / `verb(args)`: `op` a keyword, the
    verb a call name, its `( )` calls, its arguments by their pieces."""
    m = OP_HEAD_RE.match(raw, start)
    if m is None:
        _pieces(raw, start, end, roles)
        return
    if raw.startswith("op", start) and m.start("verb") > start:
        _paint(roles, start, start + 2, KEYWORD)
    _paint(roles, m.start("verb"), m.end("verb"), "syntax.call_name")
    _paint(roles, m.end() - 1, m.end(), "syntax.call")
    if end - 1 >= m.end() and raw[end - 1:end] == ")":
        _pieces(raw, m.end(), end - 1, roles)
        _paint(roles, end - 1, end, "syntax.call")
    else:
        _pieces(raw, m.end(), end, roles)


# ---------------------------------------------------------------------------
# Hosts: the theme, ANSI and --json output, the --stream session
# ---------------------------------------------------------------------------
# What `sigil highlight` serves (sigil.cli keeps its argv, opening stdin and
# stdout, and the exit codes). The only part of this module that reads files (a
# theme, a dialect asked for) or writes (to the stream it is handed).

HIGHLIGHT_VERSION = 1       # "sigil_highlight" in --json: the shape below

HIGHLIGHT_PROTOCOL = """\
--json prints one object:
  {"sigil_highlight": 1, "theme": NAME,
   "lines": [[[TEXT, ROLE|null, "#rrggbb"|null], ...], ...],
   "carry": [CARRY, ...]}
one list of runs per line (its texts joined give the line back) and the carry
each line ends in (the one the next line starts in). ROLE is a theme path
(syntax.operator, kinds.service, ui.mode ...); the colour is that role's in
the theme, null for plain text.

CARRY is [quote, decl, decl_raw, state], four integers: quote 1 inside a
\"\"\"...\"\"\" block string; decl the brace depth inside a `#&` declaration's
body (0: none); decl_raw 1 when that body's braces count on the raw line;
state the brace depth inside a `state` block. A text starts in [0, 0, 1, 0].

--stream reads JSON-lines requests on stdin and answers each with one JSON
line on stdout (flushed), until stdin ends (exit 0):
  {"id": ANY, "lines": [STR, ...], "start": N, "carry": CARRY|null}
    -> {"id": ANY, "start": N, "lines": [[RUN, ...], ...], "carry": [CARRY, ...]}
  {"id": ANY, "theme": NAME|PATH}   -> {"id": ANY, "theme": NAME}
  {"id": ANY, "dialect": NAME|PATH|null}
    -> {"id": ANY, "dialect": NAME|null[, "theme": NAME]}
  anything malformed                -> {"id": ANY|null, "error": "..."}
A request may hold dialect, theme and lines together: the dialect switches
first, then the theme, then the lines are highlighted with both; the answer
holds a key for each part. A request that fails in any part answers only
{"id", "error"} and changes nothing (a dialect that fails to load keeps the old
one). A dialect is loaded as --dialect loads it (null: core Sigil, no dialect,
whatever $SIGIL_DIALECT says) and answered by its NAME. Themes: --theme or a
{"theme"} request is explicit and holds for the rest of the session; until one
is given the theme is $SIGIL_THEME if set, else the dialect's THEME, else
sigil, so (without $SIGIL_THEME) a dialect switch also switches the theme, and
its answer names the theme now in use ("theme"). After an explicit theme a
dialect switch leaves the theme alone.
`start` is the index of lines[0] (echoed; default 0), `carry` the carry lines[0]
starts in (null: a text's start). A line's runs depend only on the line and
the carry it starts in, so an editor highlights incrementally: after an edit it
sends the changed lines with the end carry of the line before them, and keeps
sending the lines that follow until a returned end carry equals the one it held
for that line; from there on nothing changed. No file is read but the theme and
a dialect asked for."""


def theme_for(spec, dialect) -> tuple:
    """(the resolved theme, the name it goes by) for `spec` (--theme or a
    {"theme"} request; None: $SIGIL_THEME, else the dialect's THEME, else sigil).
    Raises ValueError (themes.ThemeError, a dialect's bad THEME)."""
    theme = themes.load(spec, dialect)
    return theme, theme_name(theme, themes.chosen(spec, dialect)[0])


def theme_name(theme: dict, spec) -> str:
    """The name a loaded theme goes by (its `name`, else what was asked for)."""
    name = theme.get("name") if isinstance(theme, dict) else None
    return name if isinstance(name, str) and name else str(spec or "sigil")


def carry_json(carry) -> list:
    """A Carry as its stable JSON form [quote, decl, decl_raw, state]."""
    return [int(carry.quote), carry.decl, int(carry.decl_raw), carry.state]


def carry_from_json(value):
    """The Carry a JSON value names (None: a text's start). Raises ValueError."""
    if value is None:
        return PLAIN
    if not (isinstance(value, list) and len(value) == 4
            and all(type(v) is int and v >= 0 for v in value)
            and value[0] in (0, 1) and value[2] in (0, 1)):
        raise ValueError("carry must be null or [quote 0|1, decl >= 0, decl_raw 0|1, "
                         "state >= 0]")
    return Carry(bool(value[0]), value[1], bool(value[2]), value[3])


def runs_json(runs, theme: dict, lx: Lexicon) -> list:
    """A line's runs as [text, role, colour] triples."""
    return [[text, role, colour(role, theme, lx)] for text, role in runs]


def ansi_line(runs, theme: dict, lx: Lexicon) -> str:
    """A line's runs with a truecolour SGR around each coloured one."""
    out = []
    for text, role in runs:
        hexa = colour(role, theme, lx)
        if hexa is None or not text:
            out.append(text)
        else:
            r, g, b = (int(hexa[k:k + 2], 16) for k in (1, 3, 5))
            out.append(f"\x1b[38;2;{r};{g};{b}m{text}\x1b[0m")
    return "".join(out)


def highlight_text(text: str, theme: dict, lx: Lexicon, colour: bool = True) -> str:
    """`text` with its lines highlighted in ANSI, every line ending kept as it is
    (the lines split as str.splitlines splits them, as lines() does)."""
    out, carry = [], PLAIN
    for whole in text.splitlines(keepends=True):
        body = (whole.splitlines() or [""])[0]
        runs, carry = line(body, carry, lx)
        out.append((ansi_line(runs, theme, lx) if colour else body) + whole[len(body):])
    return "".join(out)


def highlight_json(text: str, theme: dict, name: str, lx: Lexicon) -> dict:
    """The --json object of a text (HIGHLIGHT_PROTOCOL)."""
    rows, ends, carry = [], [], PLAIN
    for raw in text.splitlines():
        runs, carry = line(raw, carry, lx)
        rows.append(runs_json(runs, theme, lx))
        ends.append(carry_json(carry))
    return {"sigil_highlight": HIGHLIGHT_VERSION, "theme": name, "lines": rows,
            "carry": ends}


def write_text(text: str, out, theme: dict, name: str, lx: Lexicon, as_json: bool = False,
               colour: bool = True) -> None:
    """`sigil highlight FILE`: `text` written to `out` as one --json object (a
    line), or in ANSI (plain when not `colour`), flushed."""
    if as_json:
        out.write(json.dumps(highlight_json(text, theme, name, lx), ensure_ascii=False)
                  + "\n")
    else:
        out.write(highlight_text(text, theme, lx, colour=colour))
        out.flush()


def _one_line(value) -> bool:
    return isinstance(value, str) and value.splitlines() in ([], [value])


class StreamSession:
    """One --stream process's state: the theme it colours with (and whether it
    was asked for explicitly: --theme or a {"theme"} request), the dialect and
    its lexicon. answer() turns one request line into one response object; a
    request that fails changes none of it."""

    def __init__(self, theme: dict, name: str, lx: Lexicon, dialect=None,
                 explicit: bool = False):
        self.theme, self.name, self.lx = theme, name, lx
        self.dialect, self.explicit = dialect, explicit

    def answer(self, raw: str) -> dict:
        try:
            req = json.loads(raw)
        except ValueError as exc:
            return {"id": None, "error": f"not JSON: {exc}"}
        if not isinstance(req, dict):
            return {"id": None, "error": "a request is a JSON object"}
        rid = req.get("id")
        try:
            return {"id": rid, **self._serve(req)}
        except ValueError as exc:
            return {"id": rid, "error": str(exc)}

    def _serve(self, req: dict) -> dict:
        if not {"dialect", "theme", "lines"} & req.keys():
            raise ValueError("a request holds lines, a theme or a dialect")
        out: dict = {}
        dialect, lx, explicit = self.dialect, self.lx, self.explicit
        theme, name = self.theme, self.name
        if "dialect" in req:                   # first: the theme may follow the dialect
            dialect = _stream_dialect(req["dialect"])
            lx = lexicon(dialect)
            out["dialect"] = getattr(dialect, "NAME", None) if dialect is not None else None
            if not explicit and "theme" not in req:
                theme, name = theme_for(None, dialect)   # ThemeError is a ValueError
                out["theme"] = name
        if "theme" in req:
            spec = req["theme"]
            if not isinstance(spec, str) or not spec:
                raise ValueError("theme must be a theme name or path")
            theme = themes.load(spec)
            name, explicit = theme_name(theme, spec), True
            out["theme"] = name
        if "lines" in req:
            out.update(_stream_lines(req, theme, lx))
        self.dialect, self.lx, self.explicit = dialect, lx, explicit
        self.theme, self.name = theme, name
        return out


def _stream_dialect(spec):
    """The dialect a {"dialect"} request names (null: none), loaded by Core as
    --dialect loads it. Raises ValueError for one that is not a name or path, or
    cannot be loaded."""
    if spec is not None and (not isinstance(spec, str) or not spec.strip()):
        raise ValueError("dialect must be a dialect name or path, or null")
    try:
        return load_dialect(spec or "")        # "": core, not $SIGIL_DIALECT
    except ValueError:
        raise
    except Exception as exc:                   # its module failed while it loaded
        raise ValueError(f"sigil dialect {spec!r} failed to load: "
                         f"{type(exc).__name__}: {exc}") from None


def _stream_lines(req: dict, theme: dict, lx: Lexicon) -> dict:
    """The answer to a request's lines (HIGHLIGHT_PROTOCOL): the lines sent, as
    edit() highlights a new text from the carry the first one starts in. Raises
    ValueError."""
    lines_, start = req["lines"], req.get("start", 0)
    if not (isinstance(lines_, list) and all(_one_line(s) for s in lines_)):
        raise ValueError("lines must be a list of strings, each without a line break")
    if type(start) is not int or start < 0:
        raise ValueError("start must be a line index >= 0")
    done, _stop = edit([], lines_, 0, len(lines_), lx,
                       carry=carry_from_json(req.get("carry")))
    return {"start": start, "lines": [runs_json(d.runs, theme, lx) for d in done],
            "carry": [carry_json(d.end) for d in done]}


def stream(session: StreamSession, inp, out) -> int:
    """The --stream loop: a response per non-blank request line, flushed, until EOF."""
    while True:
        raw = inp.readline()
        if not raw:
            return 0
        if not raw.strip():
            continue
        out.write(json.dumps(session.answer(raw)) + "\n")
        out.flush()


def serve(inp, out, theme: dict, name: str, lx: Lexicon, dialect=None,
          explicit: bool = False) -> int:
    """`sigil highlight --stream`: one session over `inp` and `out`, from the
    theme and dialect the command started with (`explicit`: --theme was given).
    Its exit status (0 when `inp` ends)."""
    return stream(StreamSession(theme, name, lx, dialect, explicit=explicit), inp, out)
