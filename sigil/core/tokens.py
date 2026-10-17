"""
tokens — one statement read as tokens: the one tokenizer. The statement walk
(sigil.core.statements) hands it each statement; the parser (sigil.core.parse)
builds the statement's flow from the tokens and lint's rules judge them. Pure:
the same text always gives the same tokens.

    Lexicon, lexicon(dialect)          what a dialect adds to reading a line: its
                                       tokenizers, strips and comment markers
    code_line(raw, lx) → Code          a line as read: comment cut, strings
                                       blanked, a dialect glyph's columns
                                       DIALECT_COL, its column kept
    tokenize_statement(code, lx) → [Tok]
                                       the statement's tokens, each with its
                                       column in the statement, what is
                                       malformed about it (`problem`) and the
                                       modifier it places (`pair`)
    mod_pair(text), scan_mods(text)    a modifier's (name, arg); every modifier
                                       of a statement-free text (a block's or a
                                       transition's tail, a definition's body)

How a statement reads (the model's reading): its modifiers are found first,
anywhere outside a string (a stream bound `^N@policy`, then the access lists
`@read(…)` / `@write(…)`, then every other `@name` with its argument); its
payload runs from the first `:` (not `:=`) to the line end, less those
modifiers, a trailing count, bound or `!`, and modifier aliases after a `×N`
(`: charge ×3 Retry`). The rest is read left to right: a dialect's tokenizers
first, then arrows, joins, glyphs, op-call targets and the marks glued to a
glyph (`×N`, `!`, `?`, `.field`). Unreadable text becomes a `bad` token or a
token with a `problem`, which lint's hardening rules report; a token the model
does not read (a join with no glyph before it, a broken glyph) says so in its
`flag`. The lexical tables are sigil.core.lex's.

The modifier and payload capture (_capture_mods, _take_payload, run by _Reader
before the scan) is part of this one reading, not a second tokenizer: it only
decides which spans are a modifier or the payload, and blanks them in place so
every other column stays put; the scanner then reads the rest, and the spans'
own tokens (span_tokens) come from the same capture. It stays a pass of its own
because what a span is depends on the whole statement, not on what is left of
it: a stream bound is taken before the `@policy` it holds, an access list before
the `@name` rule, a free argument runs up to the next arrow or `@`, and a
payload runs from its `:` to the line end less a tail peeled from the right
(`×N`, `!`, alias references). A left-to-right scanner would need that same
look-ahead at each column, so folding it in would move the pass, not remove it.
"""

import re
from functools import lru_cache
from operator import itemgetter
from typing import NamedTuple, Optional

from sigil.core.lex import (
    ALIAS_REF, ALIAS_REF_RE, ARG_MODIFIERS, ARROW_RE, BLOCK_OPEN_RE, BOUND_RE, CARD_RE,
    CLOSER, CLOSERS, DIALECT_COL, FIELD_RE, FREE_ARG_MODS, GENERIC_RE, GLUED_MOD_RE,
    GLYPH_PREFIXES, MODIFIER_RE, MOD_NAME_RE, OPENERS, OPENERS_CLASS, OP_HEAD_RE,
    OP_TARGET_RE, PAYLOAD_RE, PAYLOAD_TAIL_LOOSE_RE, PAYLOAD_TAIL_RE, PREFIXES_CLASS,
    PRINCIPAL_SET_RE, STREAM_BOUND_RE, TAIL_MOD_RE, TAIL_ONLY_RE, balanced_end, code_end,
    in_string, mask_strings)


# ---------------------------------------------------------------------------
# What a dialect adds to reading a line
# ---------------------------------------------------------------------------

class Lexicon(NamedTuple):
    """A dialect's part in reading a statement: `tokenizers` (tried first at each
    column), `strips` (length-preserving blanks of a flow statement's code),
    `marker` (its extra comment markers as one pattern, or None)."""
    tokenizers: tuple = ()
    strips: tuple = ()
    marker: Optional[re.Pattern] = None


NO_DIALECT = Lexicon()


@lru_cache(maxsize=64)
def lexicon(dialect) -> Lexicon:
    """The Lexicon of a loaded dialect (None: core Sigil)."""
    if dialect is None:
        return NO_DIALECT
    from sigil.core.dialects import DialectError, _hook, retired_hook_problems
    problems = retired_hook_problems(dialect)
    if problems:
        raise DialectError(f"sigil dialect {getattr(dialect, 'NAME', '?')!r}: "
                           + "; ".join(problems))
    extra = list(_hook(dialect, "COMMENT_MARKERS"))
    marker = re.compile(r"(?:^|(?<=\s))(?:" + "|".join(extra) + ")") if extra else None
    return Lexicon(tuple(_hook(dialect, "tokenizers")), tuple(_hook(dialect, "strips")),
                   marker)


# ---------------------------------------------------------------------------
# A line as read
# ---------------------------------------------------------------------------

class Code(NamedTuple):
    """One line (or a slice of one) as a statement is read, two aligned strings:
    `text` has the comment cut, string contents blanked and dialect glyphs
    replaced by DIALECT_COL; `raw` is the same span with strings and glyphs
    intact. `col` is the column of the span's first character in its line."""
    text: str
    raw: str
    col: int = 0

    def cut(self, start: int, end: Optional[int] = None) -> "Code":
        """The span from `start` to `end` (indices into this span), its column kept."""
        return Code(self.text[start:end], self.raw[start:end],
                    self.col + len(self.text[:start]))

    def blank(self, spans) -> "Code":
        """This span with the columns of each (start, end) blanked to spaces."""
        text, raw = list(self.text), list(self.raw)
        for start, end in spans:
            for k in range(start, end):
                text[k] = raw[k] = " "
        return Code("".join(text), "".join(raw), self.col)


def code_line(raw: str, lx: Lexicon = NO_DIALECT) -> Code:
    """The Code of a raw line: comment cut, strings and dialect glyphs blanked."""
    code = raw if lx.marker is None and "#" not in raw else raw[:code_end(raw, lx.marker)]
    masked = mask_strings(code)
    if not lx.tokenizers:
        return Code(masked, code)
    cols = _dialect_columns(masked, lx.tokenizers)
    if not any(cols):
        return Code(masked, code)
    # Dialect glyphs glued together (`[a]>[b]`) are one piece of dialect syntax.
    for m in re.finditer(r"\S+", masked):
        hits = [k for k in range(m.start(), m.end()) if cols[k]]
        if hits:
            for k in range(hits[0], hits[-1] + 1):
                cols[k] = True
    text = "".join(DIALECT_COL if c else ch for c, ch in zip(cols, masked))
    return Code(text, code)


def _dialect_columns(s: str, tokenizers) -> list:
    """Which columns of `s` a dialect glyph covers (its tokenizers' glyph tokens)."""
    from sigil.core.graph import Node
    cols = [False] * len(s)
    i, prev = 0, False
    while i < len(s):
        if s[i].isspace():
            i += 1
            continue
        hit = _dialect_hit(tokenizers, s, i, prev, "L1", Node)
        if hit is None:
            i, prev = i + 1, False
            continue
        new, end, prev = hit
        if any(kind == "glyph" for kind, _v in new):
            for k in range(i, end):
                cols[k] = True
        i = max(end, i + 1)
    return cols


def _dialect_hit(tokenizers, s: str, i: int, prev: bool, layer: str, node_cls):
    for tok in tokenizers:
        hit = tok(s, i, prev, layer, node_cls)
        if hit:
            return hit
    return None


def dialect_glyph_nodes(text: str, lx: Lexicon) -> list:
    """The nodes a dialect's tokenizers read as glyphs anywhere in `text` (a
    principal an access list may name), with each one's (start, end)."""
    from sigil.core.graph import Node
    out, i, prev = [], 0, False
    while i < len(text) and lx.tokenizers:
        if text[i].isspace():
            i += 1
            continue
        hit = _dialect_hit(lx.tokenizers, text, i, prev, "L1", Node)
        if hit is None:
            i, prev = i + 1, False
            continue
        new, end, prev = hit
        out += [(node, (i, end)) for kind, node in new if kind == "glyph"]
        i = max(end, i + 1)
    return out


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

class Tok(NamedTuple):
    """A token of one statement, its column in the statement. `problem` names what
    is malformed ("" when well formed); `glued`: it touches the glyph before it
    (`[App]×N`). `pair`: the modifier the model places for it ((name, arg), or
    None). `flag`: how the model reads it apart from its kind — "dead" (it reads
    nothing here: a join with no glyph before it, a mark that marks no glyph),
    "kv" (a payload that is a modifier's `key:value`), "glued" (a count the model
    takes as the glyph's cardinality). A payload's `end` is where its text ends
    (its modifiers inside). A dialect glyph carries the dialect's Node."""
    kind: str        # glyph nothing arrow join slash payload mod card bound mark
                     # field evarg op word str blockopen blockclose alias aref bad
    text: str
    col: int
    problem: str = ""
    glued: bool = False
    pair: Optional[tuple] = None
    flag: str = ""
    end: int = -1
    node: object = None


# Masking. A captured modifier / payload is blanked in place, so every other
# column stays put: with one space where a text-deleting strip would put one (a
# modifier with an argument, a payload) and _GAP elsewhere — a filler the
# tokenizer skips, so text around a removed modifier still reads as adjacent.
_GAP = "\x00"


def _blank(n: int, spaced: bool = True) -> str:
    return (" " + _GAP * (n - 1)) if spaced and n else _GAP * n


_MOD_HEAD_RE = re.compile(r"@([A-Za-z][\w-]*)\s*")
_MOD_PAREN_RE = re.compile(r"@[A-Za-z][\w-]*\s*\(")
_REF_NAME_RE = re.compile(r"[A-Za-z_][\w-]*")
_NOT_POSITIVE_RE = re.compile(r"^(?:-|0+(?:\.0+)?(?:[a-z]+)?$)")
_ZERO_RE = re.compile(r"0+")
_BOUND_COUNT_RE = re.compile(r"\^(\w*)")
_TAIL_COUNT_RE = re.compile(r"[×^x]\s*(\w*)")
_LOOSE_COUNT_RE = re.compile(r"×\s*(\w*)|\^(\w*)(?:@[a-z]+)?")
_WORD_END_RE = re.compile(r"[A-Za-z_\d][\w.-]*$")


def mod_pair(text: str) -> tuple:
    """`@timeout(30s)` → ("timeout", "30s"); `@inv >= 0` → ("inv", ">= 0");
    `@all` → ("all", None). A lone `( … )` argument loses its parens."""
    m = _MOD_HEAD_RE.match(text)
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


def _mod_spans(rx, text: str) -> list:
    """(start, end) of each modifier `rx` finds outside `"…"` strings, a free
    argument cut where the next header token starts (_own_length)."""
    spans = []
    quoted = '"' in text
    block = _HEADER_BLOCK_RE.search(text)
    limit = block.start() if block else len(text)
    for m in rx.finditer(text):
        if quoted and in_string(text, m.start()):
            continue
        end = m.end()
        tok = text[m.start():end] if end <= limit else text[m.start():limit].rstrip()
        spans.append((m.start(), m.start() + _own_length(tok)))
    return spans


# The block `{` that ends a header (`[Y] @owns(|S|) ^4 ! {`): the last thing on the
# statement. A `{` inside an argument (`@inv status in { open, closed }`) is not one.
_HEADER_BLOCK_RE = re.compile(r"\{\s*$")


def _own_length(tok: str) -> int:
    """How much of a matched modifier `tok` (cut before the header's block `{`)
    is the modifier's own. A free argument (`@owns(|S|) ^4 ! {`, `@owns |S| ×3`)
    ends before a span blanked by an earlier capture (a stream bound `^N`, an
    access list), and leaves out a trailing run of `×N` / `xN` / `!` — modifiers
    of their own, read as they would be without it."""
    stop = tok.find(_GAP, 1)
    if stop > 0:
        tok = tok[:stop].rstrip()
    pm = _MOD_PAREN_RE.match(tok)
    if pm:
        close = _close_paren(tok[pm.end() - 1:])
        if close >= 0:
            cut = pm.end() + close
            return cut if cut < len(tok) and TAIL_ONLY_RE.match(tok[cut:]) else len(tok)
    head = _MOD_HEAD_RE.match(tok)
    for gap in re.finditer(r"\s+", tok[head.end():] if head else ""):
        if TAIL_ONLY_RE.match(tok[head.end() + gap.start():]):
            return head.end() + gap.start()
    return len(tok)


class _Mod(NamedTuple):
    start: int
    end: int
    pair: tuple
    bound: bool          # a stream bound `^N@policy`


# The modifier patterns in the order _capture_mods takes them, each with a
# pattern for the text every match of it holds.
_MOD_KINDS = ((STREAM_BOUND_RE, re.compile(r"\^")),
              (PRINCIPAL_SET_RE, re.compile("@read|@write")),
              (MODIFIER_RE, re.compile("@")))


def _capture_mods(text: str) -> tuple:
    """A statement's modifiers, each with its span, and the text with them
    blanked (length-preserving). Stream bounds first (their `@policy` is not a
    modifier of its own); then the access lists `@read(…)` / `@write(…)` —
    principal NAMES, never actor glyphs; then every other modifier with its
    argument — not an `@` inside a `"…"` string (`: "ops@example.com"` is
    payload text)."""
    mods = []
    if "@" not in text and "^" not in text:
        return text, mods
    for rx, needs in _MOD_KINDS:
        if not needs.search(text):              # no such modifier left to find
            continue
        for start, end in _mod_spans(rx, text):
            tok = text[start:end]
            if rx is STREAM_BOUND_RE:
                pair, spaced = ("^", tok[1:]), False
            else:
                pair = mod_pair(tok)
                spaced = rx is PRINCIPAL_SET_RE or pair[0] in ARG_MODIFIERS
            mods.append(_Mod(start, end, pair, rx is STREAM_BOUND_RE))
            text = text[:start] + _blank(end - start, spaced) + text[end:]
    return text, mods


class _Payload(NamedTuple):
    colon: int           # the `:`'s column
    start: int           # where its text starts (after the `:` and spaces)
    end: int             # where the payload's span ends
    text: Optional[str]  # the payload (None when empty)
    rest: str            # its text up to its tail, blanked modifiers as _GAP / space
    peeled: list         # [(column, kind, text, pair)] its tail and alias references


# A character every payload tail (PAYLOAD_TAIL_RE, PAYLOAD_TAIL_LOOSE_RE) holds.
_TAIL_CHARS_RE = re.compile("[×x^!]")


def _take_payload(text: str) -> tuple:
    """The terminal `: payload` (not a `:=` alias) of a modifier-blanked line, kept
    as text less its trailing cardinality / stream-bound / `!` modifiers and
    modifier-alias references. Returns (the line with every payload blanked, a
    _Payload or None)."""
    pm = PAYLOAD_RE.search(text) if ":" in text else None
    if not pm:
        return text, None
    raw = pm.group(1)
    peeled = []
    refs = (ALIAS_REF_RE.search(raw.replace(_GAP, " "))
            if "×" in raw or "x" in raw else None)        # a count comes first
    if refs:
        at = pm.start(1) + refs.start("names")
        for nm in _REF_NAME_RE.finditer(refs.group("names")):
            peeled.append((at + nm.start(), "aref", nm.group(0), (ALIAS_REF, nm.group(0))))
        raw = raw[:refs.start("names")]
    tail = (PAYLOAD_TAIL_RE.search(raw.replace(_GAP, " "))   # same length
            if _TAIL_CHARS_RE.search(raw) else None)
    if tail and tail.start() < len(raw):
        at = pm.start(1) + tail.start()
        for t in TAIL_MOD_RE.finditer(tail.group(0)):
            card = t.group(1) or t.group(2)
            pair = ("×", card) if card else ("^", t.group(3)) if t.group(3) else ("!", None)
            kind = "card" if card else "bound" if t.group(3) else "mark"
            peeled.append((at + t.start(), kind, t.group(0).strip(), pair))
        raw = raw[:tail.start()]
    payload = raw.replace(_GAP, "").strip() or None
    colon = text.index(":", pm.start())
    out = text[:pm.start()] + _blank(pm.end() - pm.start()) + text[pm.end():]
    if ":" in out:
        out = PAYLOAD_RE.sub(lambda m: _blank(len(m.group(0))), out)
    return out, _Payload(colon, pm.start(1), pm.end(), payload, raw, sorted(peeled))


def _overlay(base: str, blanked: str, spans) -> str:
    """`base` with the columns of each (start, end) taken from `blanked`."""
    for start, end in spans:
        base = base[:start] + blanked[start:end] + base[end:]
    return base


def scan_mods(text: str) -> list:
    """Every modifier in a statement-free text (a block header's tail, a
    definition's body, a transition's tail) as (name, arg) pairs, in written
    order: the statement's modifiers (as tokenize_statement finds them), then any
    `×N` / `xN` / `^N` / `!` outside a string."""
    masked, mods = _capture_mods(text)
    out = [(m.start, m.pair) for m in mods]
    for m in TAIL_MOD_RE.finditer(masked):
        if in_string(masked, m.start()):
            continue
        card = m.group(1) or m.group(2)
        out.append((m.start(), ("×", card) if card else ("^", m.group(3)) if m.group(3)
                    else ("!", None)))
    return [p for _pos, p in sorted(out, key=lambda x: x[0])]


# -- the statement scanner ----------------------------------------------------

_WORD_RE = re.compile(r"[A-Za-z_\d][\w.-]*")


# Unicode arrows other than the core `→` (U+2192): `⇒`, `⟶`, `↦`, … are not arrows.
_FOREIGN_ARROW_RE = re.compile("[←↑↓-⇿⟰-⟿⤀-⥿⬀-⯿]")


_NEEDS_ARG_MODS = {"timeout", "after", "deadline", "fallback"}


_POSITIVE_MODS = {"timeout", "deadline"}         # a zero or negative duration is no bound


# Where a glyph starts: its prefixes, then an opening bracket.
_GLYPH_START_RE = re.compile("^" + PREFIXES_CLASS + "*" + OPENERS_CLASS)


# A payload item made only of operator characters (`++`, `||`, `->`, `&?`, a
# dialect's `|||`) joins the items around it.
_OPERATOR_RE = re.compile(r"^[-+*/|&?!=<>~→,]+$")


# `|||` (a by-key merge) outside a payload: a value operator, not an empty `||` glyph.
_MERGE_OP_RE = re.compile(r"\|\|\|(?!\|)")


# The `:value` half of a modifier's `key:value` argument, up to the next `@` or line end.
_KEY_VALUE_RE = re.compile(r":[A-Za-z_][\w-]*(?=\s*(?:@|$))")


_CLOSERS = tuple(CLOSERS)


# A glyph whose text holds no bracket at all up to its closer: _scan_glyph's
# loop would meet only its closer (`<A->` excepted: an arrow, checked first).
_PLAIN_GLYPH = {o: re.compile(re.escape(o) + r"[^\]})>\[{(|<]*" + re.escape(c))
                for o, c in CLOSER.items()}


def _scan_glyph(s: str, i: int) -> tuple:
    """Scan the glyph whose opener is s[i]: (end, problem). `problem` is "" for a
    well-formed glyph (`end` is past its closer), else "empty", "unclosed" (an
    arrow, another glyph or the line end came first; `end` is where the scan
    stopped) or "mismatched" (closed by another kind's bracket; `end` is past it)."""
    fast = _PLAIN_GLYPH[s[i]].match(s, i)
    if fast is not None and not (s[i] == "<" and fast.end() - i > 3
                                 and s[fast.end() - 2] in "-~=!?*"):
        end = fast.end()
        return end, ("" if s[i + 1:end - 1].strip(" " + _GAP) else "empty")
    closer = CLOSER[s[i]]
    j = i + 1
    while j < len(s):
        ch = s[j]
        if ch == ">" and j - 1 > i + 1 and s[j - 1] in "-~=!?*":
            return j - 1, "unclosed"                    # an arrow (even `<B ->`): resume at it
        if ch == closer:
            return j + 1, ("" if s[i + 1:j].strip(" " + _GAP) else "empty")
        if ch == "<":                                   # a generic: `[Cache<K,V>]`
            m = GENERIC_RE.match(s, j)
            if not m:
                return j, "unclosed"
            j = m.end()
            continue
        if ch in "]})>":
            return j + 1, "mismatched"
        if ch in "[{(|":
            return j, "unclosed"
        j += 1
    return j, "unclosed"


def _mod_problem(name: str, arg: str) -> str:
    """What is wrong with a modifier's argument: "no-arg", "bad-duration" or ""."""
    if name in _NEEDS_ARG_MODS and not arg:
        return "no-arg"
    if name in _POSITIVE_MODS and _NOT_POSITIVE_RE.match(arg):
        return "bad-duration"
    if name == "after" and arg.startswith("-"):
        return "bad-duration"
    return ""


def _free_arg_end(s: str, j: int) -> int:
    """Where a free (unparenthesised) modifier argument starting at j ends: the
    next arrow, `@`, block `{` or the line end."""
    m = _FREE_ARG_STOP_RE.search(s, j)
    return m.start() if m else len(s)


# What ends a free modifier argument: an `@`, an arrow or a block `{`.
_FREE_ARG_STOP_RE = re.compile("@|" + ARROW_RE.pattern + "|" + BLOCK_OPEN_RE.pattern)


def _lint_mod(s: str, i: int) -> tuple:
    """The modifier at s[i] as lint judges it (`@name`, its `( … )` and any free
    argument): (Tok, end) — a `(` that never closes makes it run to the line end."""
    m = MOD_NAME_RE.match(s, i)
    name, j = m.group(1), m.end()
    k = j
    while k < len(s) and s[k] == " " and name in FREE_ARG_MODS:
        k += 1
    if k < len(s) and s[k] == "(":
        end = balanced_end(s, k)
        if end < 0:
            return Tok("mod", s[i:], i, "unclosed"), len(s)
        arg = s[k + 1:end - 1].strip()
        if name in FREE_ARG_MODS:
            more = _free_arg_end(s, end)
            if s[end:more].strip() and not TAIL_ONLY_RE.match(s[end:more]):
                end = more
        return Tok("mod", s[i:end], i, _mod_problem(name, arg)), end
    end = _free_arg_end(s, j) if name in FREE_ARG_MODS else j
    return Tok("mod", s[i:end], i, _mod_problem(name, s[j:end].strip())), end


def _count_problem(count: str) -> str:
    if not count:
        return "no-count"
    return "zero" if _ZERO_RE.fullmatch(count) else ""


def _payload_problem(raw: str) -> str:
    """What is wrong with a payload's text: "unclosed" (an open string, `${` or
    bracket), "glyph-after" (a glyph follows a value with nothing joining them,
    `: {X} [C]`), or "" when nothing is."""
    if raw.count('"') % 2:
        return "unclosed"
    s = mask_strings(raw)
    brackets = "".join(_BRACKET_RE.findall(s))
    if brackets:
        depth = []
        for ch in brackets:
            if ch in "([{":
                depth.append(ch)
            elif ch in ")]}":
                if not depth or "([{"[")]}".index(ch)] != depth.pop():
                    return "unclosed"
        if depth:
            return "unclosed"
    if not _LATER_GLYPH_RE.search(s):       # no item after the first starts a glyph
        return ""
    items = _top_level_items(s)
    for prev, item in zip(items, items[1:]):
        if (_GLYPH_START_RE.match(item) and not _OPERATOR_RE.match(item)
                and not _OPERATOR_RE.match(prev) and not prev.endswith(",")):
            return "glyph-after"
    return ""


_BRACKET_RE = re.compile(r"[(\[{)\]}]")        # what _payload_problem balances
# An item after whitespace that _GLYPH_START_RE would take as a glyph.
_LATER_GLYPH_RE = re.compile(r"\s" + PREFIXES_CLASS + "*" + OPENERS_CLASS)


def _top_level_items(s: str) -> list:
    """Whitespace-separated items of a payload value, brackets kept whole."""
    items, buf, depth = [], [], 0
    for ch in s:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch.isspace() and depth == 0:
            if buf:
                items.append("".join(buf))
                buf = []
            continue
        buf.append(ch)
    if buf:
        items.append("".join(buf))
    return items


class _Reader:
    """One statement being tokenized (see the module notes): `w` is the text the
    scanners read — strings masked, the statement's modifiers and payload
    blanked — and `prev` tracks whether the model's reading stands right after a
    glyph (what a join, a `?`, a `.field` or a dialect tokenizer needs)."""

    def __init__(self, code: Code, lx: Lexicon):
        self.code, self.lx = code, lx
        blanked, mods = _capture_mods(code.raw)
        blanked, payload = _take_payload(blanked)
        self.mods, self.payload = mods, payload
        # The scanners read the masked text with the model's blanks over it.
        masked = mask_strings(code.raw)
        if blanked == code.raw:
            self.w = masked
        else:
            spans = [(m.start, m.end) for m in mods]
            if payload is not None:
                spans.append((payload.colon, len(blanked)))
            self.w = _overlay(masked, blanked, spans)
        self.toks: list = []
        self.prev = False

    # -- the tokens of the blanked spans -------------------------------------

    def span_tokens(self) -> list:
        """The modifier, payload and payload-tail tokens (the spans the model
        reads before the rest), as lint judges them."""
        text, out = self.code.text, []
        for m in self.mods:
            if m.bound:
                count = _BOUND_COUNT_RE.match(self.code.raw[m.start:m.end]).group(1)
                out.append(Tok("bound", text[m.start:m.end], m.start,
                               _count_problem(count), pair=m.pair))
                continue
            problem, tok_text = "", text[m.start:m.end]
            if MOD_NAME_RE.match(text, m.start):
                problem = _lint_mod(text, m.start)[0].problem
                if problem == "unclosed":       # lint names an unclosed one to the line end
                    tok_text = text[m.start:]
            out.append(Tok("mod", tok_text, m.start, problem, pair=m.pair))
        p = self.payload
        if p is not None:
            out += self._payload_tokens(p)
        return out

    def _payload_tokens(self, p: _Payload) -> list:
        """The payload token and its tail's: the model's peeled count, bound, `!`
        and alias references, and — for lint — a count or bound with nothing to
        count (`: x ×`), which the model leaves in the payload's text."""
        out = []
        for col, kind, text, pair in p.peeled:
            count = _TAIL_COUNT_RE.match(text)
            problem = _count_problem(count.group(1)) if kind in ("card", "bound") and count \
                else ""
            out.append(Tok(kind, text, col, problem, pair=pair))
        rest = p.rest.replace(_GAP, " ")
        loose = PAYLOAD_TAIL_LOOSE_RE.search(rest) if _TAIL_CHARS_RE.search(rest) else None
        if loose and loose.start() > 0:
            for t in _LOOSE_COUNT_RE.finditer(loose.group(0)):
                count = t.group(1) if t.group(0).startswith("×") else t.group(2)
                if _count_problem(count) == "no-count":
                    out.append(Tok("card" if t.group(0).startswith("×") else "bound",
                                   t.group(0), p.start + loose.start() + t.start(), "no-count"))
            rest = rest[:loose.start()]
        problem = _payload_problem(rest) if rest.strip() else ""
        kv = self._key_value(p.colon)
        out.append(Tok("payload", p.text or "", p.colon, problem, flag="kv" if kv else "",
                       end=p.end))
        if kv:
            m = _KEY_VALUE_RE.match(self.code.text, p.colon)
            out.append(Tok("word", self.code.text[p.colon:m.end()], p.colon))
        return out

    def _key_value(self, colon: int) -> bool:
        """Whether the payload's `:` joins a modifier's `key:value` argument
        (`@spawn state:inline`): glued to a word that follows a modifier, with one
        word after it and nothing else before the next modifier or the line end."""
        text = self.code.text
        if not _KEY_VALUE_RE.match(text, colon):
            return False
        wm = _WORD_END_RE.search(text[:colon])
        return bool(wm) and any(not m.bound and m.end <= wm.start()
                                and not text[m.end:wm.start()].strip() for m in self.mods)

    # -- the scan ------------------------------------------------------------

    def scan(self) -> list:
        w, text, toks = self.w, self.code.text, self.toks
        dialect = bool(self.lx.tokenizers)
        i, n = 0, len(w)
        while i < n:
            ch = w[i]
            if ch.isspace() or ch == _GAP:
                i += 1
                continue
            hit = self._dialect(i) if dialect else None
            if hit is None and text[i] == DIALECT_COL:
                # Glued to a dialect glyph (`[[a]]>[[b]]`): dialect syntax, read by
                # no core rule.
                hit = [], i + 1, False
            if hit is None:
                for scanner in _scanners_for(ch):
                    hit = scanner(self, i)
                    if hit is not None:
                        break
            new, i, self.prev = hit
            toks.extend(new)
        return toks

    def _dialect(self, i: int):
        if not self.lx.tokenizers:
            return None
        from sigil.core.graph import Node
        hit = _dialect_hit(self.lx.tokenizers, self.w, i, self.prev, "L1", Node)
        if hit is None:
            return None
        new, end, prev = hit
        toks = []
        for kind, val in new:
            if kind == "glyph":
                toks.append(Tok("glyph", self.code.raw[i:end], i, node=val))
            else:
                toks.append(Tok(kind, val, i))
        return toks, end, prev

    def before_is_closer(self, i: int) -> bool:
        """Whether the character before column i (blanked modifiers that leave no
        space skipped) closes a glyph — what a glued `×N`, `?` or `.field` needs."""
        return self.w[:i].rstrip(_GAP)[-1:] in _CLOSERS


def _after_glyph(toks: list) -> bool:
    """Whether the last token ends a glyph (a glued modifier may follow it)."""
    return bool(toks) and toks[-1].kind in ("glyph", "field", "evarg")


def _glued(s: str, i: int, toks: list) -> bool:
    """Whether the token at s[i] touches the glyph before it (`[App]×N`)."""
    return _after_glyph(toks) and i > 0 and not s[i - 1].isspace()


# Each scanner looks at column i of the statement: it returns (new tokens, the
# column to resume at, whether the model now stands after a glyph), or None to
# let the next scanner try. Their order is the grammar's precedence (an arrow
# before a glyph, so `<->` is never an event).

def _scan_arrow_or_alias(r: _Reader, i: int):
    s = r.w
    am = ARROW_RE.match(s, i)
    if am:
        return [Tok("arrow", am.group(0), i)], am.end(), False
    if s.startswith(":=", i):
        return [Tok("alias", ":=", i)], i + 2, False
    return None


# What a glyph's text may start with: a prefix or an opening bracket.
_GLYPH_HEADS = OPENERS + GLYPH_PREFIXES


def _scan_join(r: _Reader, i: int):
    s = r.w
    if s[i] == "&":
        j = i + 2 if s.startswith("&?", i) else i + 1
        return [Tok("join", s[i:j], i, flag="" if r.prev else "dead")], j, False
    if s[i] == "/":
        path = _glued(s, i, r.toks) and i + 1 < len(s) and s[i + 1] in _GLYPH_HEADS
        if r.prev:
            # Qualified path `[Bullet]/{Transform}`: a `/` glued between glyphs; else
            # an alternative `a / b` (language.md "Structure"): one-of endpoint.
            model = (i + 1 < len(s) and s[i + 1] in _GLYPH_HEADS and not s[i - 1].isspace())
            return [Tok("slash" if path else "join", "/", i,
                        flag="" if model == path else ("slash" if model else "join"))], \
                i + 1, False
        return [Tok("slash" if path else "join", "/", i, flag="dead")], i + 1, False
    return None


def _scan_modifier(r: _Reader, i: int):
    s = r.w
    if s[i] == "@":
        if not MOD_NAME_RE.match(s, i):
            return [], i + 1, False
        tok, end = _lint_mod(s, i)
        return [tok], end, False
    if s[i] == "^":
        # Lint names the bound with its `@policy`, which the model reads as a
        # modifier of its own when the bound has no count (`^@drop`).
        m = BOUND_RE.match(r.code.text, i)
        return [Tok("bound", m.group(0), i, _count_problem(m.group(1)))], \
            max(BOUND_RE.match(s, i).end(), i + 1), False
    cm = CARD_RE.match(s, i)
    if cm:
        count = next(g for g in cm.groups() if g is not None)
        gm = GLUED_MOD_RE.match(s, i)
        card = gm and (gm.group("card") or gm.group("card2") or gm.group("card3"))
        glued = _glued(s, i, r.toks)
        if card:
            flag = "glued" if r.before_is_closer(i) else ""
            return [Tok("card", cm.group(0), i, _count_problem(count), glued=glued,
                        pair=("×", card), flag=flag)], max(cm.end(), gm.end()), r.prev
        return [Tok("card", cm.group(0), i, _count_problem(count), glued=glued)], \
            cm.end(), False
    return None


def _scan_glyph_token(r: _Reader, i: int):
    """A glyph with its `~` / `*` prefixes, a block brace, an event's argument
    `<H>({C})`, or the empty `()`."""
    s = r.w
    j = i
    while j < len(s) and s[j] in GLYPH_PREFIXES:
        j += 1
    if j < len(s) and s[j] in OPENERS and j > i and not BLOCK_OPEN_RE.match(s, j):
        end, problem = _scan_glyph(s, j)
        return _glyph(r, i, end, problem)
    if j > i:                                       # `~` / `*` before no glyph
        return ([Tok("bad", "~", i, "not-arrow")] if s[i] == "~" else []), j, False
    ch = s[i]
    if ch == "{" and BLOCK_OPEN_RE.match(s, i):
        return [Tok("blockopen", "{", i)], i + 1, False
    if ch == "}":
        return [Tok("blockclose", "}", i)], i + 1, False
    if ch == "(" and r.toks and r.toks[-1].kind == "glyph" \
            and r.toks[-1].text.lstrip(GLYPH_PREFIXES).startswith("<") and not s[i - 1].isspace():
        end = balanced_end(s, i)
        end = end if end > 0 else len(s)
        return [Tok("evarg", r.code.raw[i:end].replace(_GAP, ""), i)], end, True
    if ch == "(" and s.startswith("()", i):
        return [Tok("nothing", "()", i)], i + 2, False
    if ch == "<" and (i + 1 >= len(s) or s[i + 1] in " =-"):
        return [], i + 1, False                     # a comparison; `<-` is SGL060's
    if ch == "|" and _MERGE_OP_RE.match(s, i):
        return [], i + 3, False                     # the `|||` value operator, no glyph
    if ch in OPENERS:
        end, problem = _scan_glyph(s, i)
        return _glyph(r, i, max(end, i + 1), problem)
    return None


def _glyph(r: _Reader, i: int, end: int, problem: str) -> tuple:
    """A core glyph token from column i to `end`: the model reads it as a node
    unless it is broken (unclosed or empty: a void endpoint, flag "void")."""
    text = r.code.raw[i:end].replace(_GAP, "")
    flag = "void" if problem in ("unclosed", "empty") else ""
    return [Tok("glyph", text, i, problem, flag=flag)], end, not flag


def _scan_op_target(r: _Reader, i: int):
    """`verb(args)` / `op ns.verb(args)` written as an arrow's target."""
    last = r.toks[-1] if r.toks else None
    if last is None or last.kind != "arrow":
        return None
    om = OP_HEAD_RE.match(r.w, i)
    end = balanced_end(r.w, om.end() - 1) if om else -1
    if end <= 0:
        return None
    model = OP_TARGET_RE.match(r.w, i)
    text = r.code.raw[i:end].replace(_GAP, "")
    flag = "" if model and model.end() == end else "dead"
    return [Tok("op", text, i, flag=flag)], end, False


def _scan_marker(r: _Reader, i: int):
    """`!` critical / `?` optional, and a `.field` accessor after a glyph."""
    s = r.w
    bang = s[i] == "!" and not s.startswith(("!>", "!="), i)
    if bang:
        return [Tok("mark", "!", i, pair=("!", None))], i + 1, r.prev
    if s[i] == "?" and not s.startswith("?>", i):
        if r.prev and r.before_is_closer(i):
            return [Tok("mark", "?", i, pair=("?", None))], i + 1, r.prev
        return [Tok("mark", "?", i, flag="dead")], i + 1, False
    if s[i] == "." and _after_glyph(r.toks):
        m = FIELD_RE.match(s, i)
        if m:
            if r.prev and r.before_is_closer(i):
                return [Tok("field", m.group(0), i, pair=(".", m.group(0)[1:]))], m.end(), r.prev
            return [Tok("field", m.group(0), i, flag="dead")], m.end(), False
    return None


def _scan_value(r: _Reader, i: int):
    """A string, a `${ref}`, a word or number outside a payload."""
    s = r.w
    if s[i] == '"':
        j = s.find('"', i + 1)
        j = len(s) if j < 0 else j + 1
        return [Tok("str", r.code.raw[i:j], i)], j, False
    if s.startswith("${", i):
        end = balanced_end(s, i + 1)
        end = len(s) if end < 0 else end
        return [Tok("word", s[i:end], i)], end, False
    wm = _WORD_RE.match(s, i)
    return ([Tok("word", wm.group(0), i)], wm.end(), False) if wm else None


def _scan_other(r: _Reader, i: int):
    """Anything else: a stray closer or arrow-like character is `bad`; other
    symbols are skipped, as the model skips them."""
    ch = r.w[i]
    if ch in "])":
        return [Tok("bad", ch, i, "closer")], i + 1, False
    if ch in "->=~" or _FOREIGN_ARROW_RE.match(ch):
        return [Tok("bad", ch, i, "not-arrow")], i + 1, False
    return [], i + 1, False


_SCANNERS = (_scan_arrow_or_alias, _scan_join, _scan_modifier, _scan_glyph_token,
             _scan_op_target, _scan_marker, _scan_value, _scan_other)


# The ASCII characters each scanner can start at (from its patterns); a scanner
# never tried at another ASCII character would return None there. A non-ASCII
# character (`→`, `×`, a letter a verb starts with) tries every scanner.
_LETTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_"
_STARTS = {
    _scan_arrow_or_alias: "<-~=!?*:",
    _scan_join: "&/",
    _scan_modifier: "@^x*",
    _scan_glyph_token: GLYPH_PREFIXES + OPENERS + "}",
    _scan_op_target: _LETTERS,
    _scan_marker: "!?.",
    _scan_value: '"$0123456789' + _LETTERS,
}


@lru_cache(maxsize=None)
def _scanners_for(ch: str) -> tuple:
    """The scanners, in precedence order, that can read a token starting at `ch`."""
    if not ch.isascii():
        return _SCANNERS
    return tuple(s for s in _SCANNERS if s is _scan_other or ch in _STARTS[s])


def tokenize_statement(code: Code, lx: Lexicon = NO_DIALECT) -> list:
    """Tokenize one statement (pure: the same Code always gives the same tokens),
    in column order. Unreadable text becomes a `bad` token or a token with a
    `problem`, which the hardening rules report; only symbols the model also
    ignores are skipped."""
    r = _Reader(code, lx)
    toks = r.scan()
    spans = r.span_tokens()
    if not spans:               # the scan's tokens come in column order
        return toks
    return sorted(toks + spans, key=_COL)


_COL = itemgetter(2)        # a Tok's column
