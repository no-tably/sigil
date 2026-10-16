"""
tokens — one statement read as tokens: the lexer every reader of a statement
shares (lint's rules; sigil.core.statements hands it each statement the walk
finds). Pure: the same text always gives the same tokens.

    code_line(raw, masks) → Code     a line as read: comment cut, strings and a
                                     dialect's glyphs blanked, its column kept
    tokenize_statement(code) → [Tok] the statement's tokens, each with its column
                                     in the statement and what is malformed
                                     about it (`problem`, "" when well formed)

Unreadable text becomes a `bad` token or a token with a `problem`; only symbols
the parser also ignores are skipped. The lexical tables are sigil.core.lex's.
"""

import re
from typing import NamedTuple, Optional

from sigil.core.lex import (
    ARROW_RE, BLOCK_OPEN_RE, BOUND_RE, CARD_RE, CLOSER, DIALECT_COL, FIELD_RE,
    FREE_ARG_MODS, GENERIC_RE, MOD_NAME_RE, OP_HEAD_RE, PAYLOAD_TAIL_LOOSE_RE,
    TAIL_ONLY_RE, apply_masks, balanced_end, comment_col, mask_strings)


class Code(NamedTuple):
    """One line (or a slice of one) as a statement is read, two aligned strings:
    `text` has the comment cut, string contents blanked and dialect glyphs
    replaced by DIALECT_COL; `raw` is the same span with strings intact. `col`
    is the column of the span's first character in its line."""
    text: str
    raw: str
    col: int = 0

    def cut(self, start: int, end: Optional[int] = None) -> "Code":
        """The span from `start` to `end` (indices into this span), its column kept."""
        return Code(self.text[start:end], self.raw[start:end],
                    self.col + len(self.text[:start]))


class Tok(NamedTuple):
    """A token of one statement. `problem` names what is malformed ("" when well
    formed); `glued` is True when the token touches the glyph before it."""
    kind: str        # glyph nothing arrow join slash payload mod card bound mark
                     # field evarg op word str blockopen blockclose alias bad
    text: str
    col: int
    problem: str = ""
    glued: bool = False


def code_line(raw: str, masks=()) -> Code:
    """The Code of a raw line: comment cut, strings and dialect glyphs blanked."""
    pos = comment_col(raw)
    code = raw if pos is None else raw[:pos]
    masked = mask_strings(code)
    dm = apply_masks(masked, masks)
    if len(dm) != len(masked):          # a mask that is not length-preserving
        return Code(masked, code)
    cols = [a != b for a, b in zip(masked, dm)]
    # Dialect glyphs glued together (`[a]>[b]`) are one piece of dialect syntax.
    for m in re.finditer(r"\S+", masked):
        span = range(m.start(), m.end())
        hits = [k for k in span if cols[k]]
        if hits:
            for k in range(hits[0], hits[-1] + 1):
                cols[k] = True
    text = "".join(DIALECT_COL if c else ch for c, ch in zip(cols, dm))
    return Code(text, code)


# -- the statement scanner ----------------------------------------------------

_WORD_RE = re.compile(r"[A-Za-z_\d][\w.-]*")


# Unicode arrows other than the core `→` (U+2192): `⇒`, `⟶`, `↦`, … are not arrows.
_FOREIGN_ARROW_RE = re.compile("[\u2190\u2191\u2193-\u21ff\u27f0-\u27ff\u2900-\u297f\u2b00-\u2bff]")


_NEEDS_ARG_MODS = {"timeout", "after", "deadline", "fallback"}


_POSITIVE_MODS = {"timeout", "deadline"}         # a zero or negative duration is no bound


_GLYPH_START_RE = re.compile(r"^[~*]*[\[{<(|]")


# A payload item made only of operator characters (`++`, `||`, `->`, `&?`, a
# dialect's `|||`) joins the items around it.
_OPERATOR_RE = re.compile(r"^[-+*/|&?!=<>~→,]+$")


# `|||` (a by-key merge) outside a payload: a value operator, not an empty `||` glyph.
_MERGE_OP_RE = re.compile(r"\|\|\|(?!\|)")


# The `:value` half of a modifier's `key:value` argument, up to the next `@` or line end.
_KEY_VALUE_RE = re.compile(r":[A-Za-z_][\w-]*(?=\s*(?:@|$))")


def _scan_glyph(s: str, i: int) -> tuple:
    """Scan the glyph whose opener is s[i]: (end, problem). `problem` is "" for a
    well-formed glyph (`end` is past its closer), else "empty", "unclosed" (an
    arrow, another glyph or the line end came first; `end` is where the scan
    stopped) or "mismatched" (closed by another kind's bracket; `end` is past it)."""
    closer = CLOSER[s[i]]
    j = i + 1
    while j < len(s):
        ch = s[j]
        if ch == ">" and j - 1 > i + 1 and s[j - 1] in "-~=!?*":
            return j - 1, "unclosed"                    # an arrow (even `<B ->`): resume at it
        if ch == closer:
            return j + 1, ("" if s[i + 1:j].strip() else "empty")
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
    if name in _POSITIVE_MODS and re.match(r"^(?:-|0+(?:\.0+)?(?:[a-z]+)?$)", arg):
        return "bad-duration"
    if name == "after" and arg.startswith("-"):
        return "bad-duration"
    return ""


def _free_arg_end(s: str, j: int) -> int:
    """Where a free (unparenthesised) modifier argument starting at j ends: the
    next arrow, `@`, block `{` or the line end."""
    k = j
    while k < len(s):
        if s[k] == "@" or ARROW_RE.match(s, k) or BLOCK_OPEN_RE.match(s, k):
            return k
        k += 1
    return k


def _scan_mod(s: str, i: int) -> tuple:
    """The modifier at s[i] (`@name`, its `( … )` and any free argument): (Tok, end)."""
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
    return "zero" if re.fullmatch(r"0+", count) else ""


def _payload_problem(raw: str) -> str:
    """What is wrong with a payload's text: "unclosed" (an open string, `${` or
    bracket), "glyph-after" (a glyph follows a value with nothing joining them,
    `: {X} [C]`), or "" when nothing is."""
    if raw.count('"') % 2:
        return "unclosed"
    s = mask_strings(raw)
    depth = []
    for ch in s:
        if ch in "([{":
            depth.append(ch)
        elif ch in ")]}":
            if not depth or "([{"[")]}".index(ch)] != depth.pop():
                return "unclosed"
    if depth:
        return "unclosed"
    items = _top_level_items(s)
    for prev, item in zip(items, items[1:]):
        if (_GLYPH_START_RE.match(item) and not _OPERATOR_RE.match(item)
                and not _OPERATOR_RE.match(prev) and not prev.endswith(",")):
            return "glyph-after"
    return ""


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


def _scan_payload(code: Code, i: int) -> tuple:
    """The payload starting at the `:` at column i, to the next `@` or the line end
    (as the parser reads it), and the modifier tokens peeled off its tail."""
    s = code.text
    end = s.find("@", i)
    end = len(s) if end < 0 else end
    value = code.raw[i + 1:end]
    tail = PAYLOAD_TAIL_LOOSE_RE.search(value)
    toks = []
    if tail and tail.start() > 0:
        base = i + 1 + tail.start()
        for t in re.finditer(r"×\s*(\w*)|x(\d+|N)\b|\^(\w*)(?:@[a-z]+)?|!", tail.group(0)):
            if t.group(0) == "!":
                toks.append(Tok("mark", "!", base + t.start()))
            elif t.group(0).startswith("^"):
                toks.append(Tok("bound", t.group(0), base + t.start(), _count_problem(t.group(3))))
            else:
                count = t.group(1) if t.group(1) is not None else t.group(2)
                toks.append(Tok("card", t.group(0), base + t.start(), _count_problem(count)))
        value = value[:tail.start()]
    payload = Tok("payload", value.strip(), i, _payload_problem(value) if value.strip() else "")
    return [payload] + toks, end


def _after_glyph(toks: list) -> bool:
    """Whether the last token ends a glyph (a glued modifier may follow it)."""
    return bool(toks) and toks[-1].kind in ("glyph", "field", "evarg")


def _glued(s: str, i: int, toks: list) -> bool:
    """Whether the token at s[i] touches the glyph before it (`[App]×N`)."""
    return _after_glyph(toks) and i > 0 and not s[i - 1].isspace()


# Each scanner looks at column i of a statement: it returns (new tokens, the column
# to resume at), or None to let the next scanner try. Their order is the grammar's
# precedence (an arrow before a glyph, so `<->` is never an event).

def _scan_dialect(code: Code, i: int, toks: list):
    s = code.text
    if s[i] != DIALECT_COL:
        return None
    j = i
    while j < len(s) and s[j] == DIALECT_COL:
        j += 1
    return [Tok("glyph", code.raw[i:j], i)], j


def _scan_arrow_or_alias(code: Code, i: int, toks: list):
    s = code.text
    am = ARROW_RE.match(s, i)
    if am:
        return [Tok("arrow", am.group(0), i)], am.end()
    if s.startswith(":=", i):
        return [Tok("alias", ":=", i)], i + 2
    if s[i] == ":" and _mod_key_value(code, i, toks):
        end = _KEY_VALUE_RE.match(s, i).end()
        return [Tok("word", s[i:end], i)], end
    if s[i] == ":":
        return _scan_payload(code, i)
    return None


def _mod_key_value(code: Code, i: int, toks: list) -> bool:
    """Whether the `:` at column i joins a modifier's `key:value` argument
    (`@spawn state:inline`): glued to a word that follows a modifier, with one word
    after it and nothing else before the next modifier or the line end."""
    if len(toks) < 2 or toks[-1].kind != "word" or toks[-2].kind != "mod":
        return False
    glued = toks[-1].col + len(toks[-1].text) == i
    return glued and _KEY_VALUE_RE.match(code.text, i) is not None


def _scan_join(code: Code, i: int, toks: list):
    s = code.text
    if s[i] == "&":
        j = i + 2 if s.startswith("&?", i) else i + 1
        return [Tok("join", s[i:j], i)], j
    if s[i] == "/":
        path = _glued(s, i, toks) and i + 1 < len(s) and s[i + 1] in "[{<(|~*"
        return [Tok("slash" if path else "join", "/", i)], i + 1
    return None


def _scan_modifier(code: Code, i: int, toks: list):
    s = code.text
    if s[i] == "@":
        if not MOD_NAME_RE.match(s, i):
            return [], i + 1
        tok, end = _scan_mod(s, i)
        return [tok], end
    if s[i] == "^":
        m = BOUND_RE.match(s, i)
        return [Tok("bound", m.group(0), i, _count_problem(m.group(1)))], m.end()
    cm = CARD_RE.match(s, i)
    if cm:
        count = next(g for g in cm.groups() if g is not None)
        return [Tok("card", cm.group(0), i, _count_problem(count),
                    glued=_glued(s, i, toks))], cm.end()
    return None


def _scan_glyph_token(code: Code, i: int, toks: list):
    """A glyph with its `~` / `*` prefixes, a block brace, an event's argument
    `<H>({C})`, or the empty `()`."""
    s = code.text
    j = i
    while j < len(s) and s[j] in "~*":
        j += 1
    if j < len(s) and s[j] in "[{<(|" and j > i and not BLOCK_OPEN_RE.match(s, j):
        end, problem = _scan_glyph(s, j)
        return [Tok("glyph", s[i:end], i, problem)], end
    if j > i:                                       # `~` / `*` before no glyph
        return [Tok("bad", "~", i, "not-arrow")] if s[i] == "~" else [], j
    ch = s[i]
    if ch == "{" and BLOCK_OPEN_RE.match(s, i):
        return [Tok("blockopen", "{", i)], i + 1
    if ch == "}":
        return [Tok("blockclose", "}", i)], i + 1
    if ch == "(" and toks and toks[-1].kind == "glyph" \
            and toks[-1].text.lstrip("~*").startswith("<") and not s[i - 1].isspace():
        end = balanced_end(s, i)
        return [Tok("evarg", s[i:end if end > 0 else len(s)], i)], (end if end > 0 else len(s))
    if s.startswith("()", i):
        return [Tok("nothing", "()", i)], i + 2
    if ch == "<" and (i + 1 >= len(s) or s[i + 1] in " =-"):
        return [], i + 1                            # a comparison; `<-` is SGL060's
    if _MERGE_OP_RE.match(s, i):
        return [], i + 3                            # the `|||` value operator, no glyph
    if ch in "[{<(|":
        end, problem = _scan_glyph(s, i)
        return [Tok("glyph", s[i:end], i, problem)], max(end, i + 1)
    return None


def _scan_op_target(code: Code, i: int, toks: list):
    """`verb(args)` / `op ns.verb(args)` written as an arrow's target."""
    if not toks or toks[-1].kind != "arrow":
        return None
    om = OP_HEAD_RE.match(code.text, i)
    end = balanced_end(code.text, om.end() - 1) if om else -1
    return ([Tok("op", code.text[i:end], i)], end) if end > 0 else None


def _scan_marker(code: Code, i: int, toks: list):
    """`!` critical / `?` optional, and a `.field` accessor after a glyph."""
    s = code.text
    bang = s[i] == "!" and not s.startswith(("!>", "!="), i)
    if bang or s[i] == "?" and not s.startswith("?>", i):
        return [Tok("mark", s[i], i)], i + 1
    if s[i] == "." and _after_glyph(toks):
        m = FIELD_RE.match(s, i)
        if m:
            return [Tok("field", m.group(0), i)], m.end()
    return None


def _scan_value(code: Code, i: int, toks: list):
    """A string, a `${ref}`, a word or number outside a payload."""
    s = code.text
    if s[i] == '"':
        j = s.find('"', i + 1)
        j = len(s) if j < 0 else j + 1
        return [Tok("str", code.raw[i:j], i)], j
    if s.startswith("${", i):
        end = balanced_end(s, i + 1)
        end = len(s) if end < 0 else end
        return [Tok("word", s[i:end], i)], end
    wm = _WORD_RE.match(s, i)
    return ([Tok("word", wm.group(0), i)], wm.end()) if wm else None


def _scan_other(code: Code, i: int, toks: list):
    """Anything else: a stray closer or arrow-like character is `bad`; other
    symbols are skipped, as the parser skips them."""
    ch = code.text[i]
    if ch in "])":
        return [Tok("bad", ch, i, "closer")], i + 1
    if ch in "->=~" or _FOREIGN_ARROW_RE.match(ch):
        return [Tok("bad", ch, i, "not-arrow")], i + 1
    return [], i + 1


_SCANNERS = (_scan_dialect, _scan_arrow_or_alias, _scan_join, _scan_modifier,
             _scan_glyph_token, _scan_op_target, _scan_marker, _scan_value, _scan_other)


def tokenize_statement(code: Code) -> list:
    """Tokenize one statement (pure: the same Code always gives the same tokens).
    Unreadable text becomes a `bad` token or a token with a `problem`, which the
    hardening rules report; only symbols the parser also ignores are skipped."""
    toks, i = [], 0
    while i < len(code.text):
        if code.text[i].isspace():
            i += 1
            continue
        for scan in _SCANNERS:
            hit = scan(code, i, toks)
            if hit is not None:
                new, i = hit
                toks.extend(new)
                break
    return toks
