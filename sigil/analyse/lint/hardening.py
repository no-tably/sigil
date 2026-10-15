"""
Lint hardening (SGL120–188): the lines the parser would misread or drop. Parked
here with the rules that read them: lint's statement scanner (code_line,
tokenize_statement → Tok) and its block walk (_StructureWalk) — the parser steps
move them to sigil.core.lex / sigil.core.parse.
"""

import re
from dataclasses import dataclass
from typing import NamedTuple, Optional

from sigil.core import parse as render
from sigil.core.graph import walk_depth
from sigil.core.vocab import ANY_GLYPH_RE, ARROWS, ARROW_RE, COMMENT_START_RE as _COMMENT_START_RE, LintResult
from sigil.analyse.lint.payloads import _classify_payload
from sigil.analyse.lint.scan import (
    _OP_HEAD_RE, _apply_masks, _balanced_end, _hook, _mask_strings)


# ---------------------------------------------------------------------------
# Lint hardening — lines the parser would misread or drop (RFC 0003 §8)
# ---------------------------------------------------------------------------
#
# The parser (render.py) skips what it cannot read: an unclosed glyph becomes a
# phantom node, a dangling arrow draws nothing, an unclosed `:= {` loses its whole
# body. A model with silent holes cannot be trusted by anything downstream, so these
# rules report each such line. `_StructureWalk` follows the document's blocks the
# way the parser does and hands each statement to `tokenize_statement`; the rule
# functions below read the tokens. Codes and severities are fixed by RFC 0003's
# catalog §8: a silent drop is an error in every mode. Since the parser fix for
# `×3 Alias` (catalog §6 B7) an alias after `×N` is no longer dropped, so SGL181 (now:
# the alias is undefined) is a warning; since the `<H>({C})` chain fix (catalog §6 B8),
# SGL153 only guards against the chain being lost again.

HARDENING_SEVERITY = {
    "SGL120": "error", "SGL121": "error", "SGL122": "error",
    "SGL130": "error", "SGL131": "error", "SGL132": "error",
    "SGL150": "warn", "SGL151": "error", "SGL152": "warn", "SGL153": "error",
    "SGL160": "error", "SGL161": "error", "SGL162": "warn", "SGL163": "info",
    "SGL180": "error", "SGL181": "warn", "SGL182": "warn", "SGL183": "warn",
    "SGL184": "warn", "SGL185": "warn", "SGL186": "warn", "SGL187": "info",
    "SGL188": "warn",
}


class Finding(NamedTuple):
    """One hardening diagnostic before it reaches a LintResult."""
    line: int
    rule: str
    message: str


# Stands in for each column of a dialect glyph (masked by the dialect's
# lint_glyph_masks), so the glyph still counts as an endpoint.
DIALECT_COL = "\x01"


class Code(NamedTuple):
    """One line (or a slice of one) as the hardening rules read it, two aligned
    strings: `text` has the comment cut, string contents blanked and dialect glyphs
    replaced by DIALECT_COL; `raw` is the same span with strings intact."""
    text: str
    raw: str

    def cut(self, start: int, end: Optional[int] = None) -> "Code":
        return Code(self.text[start:end], self.raw[start:end])


class Tok(NamedTuple):
    """A token of one statement. `problem` names what is malformed ("" when well
    formed); `glued` is True when the token touches the glyph before it."""
    kind: str        # glyph nothing arrow join slash payload mod card bound mark
                     # field evarg op word str blockopen blockclose alias bad
    text: str
    col: int
    problem: str = ""
    glued: bool = False


def _comment_pos(line: str) -> Optional[int]:
    """Column of the comment `#` on the line (not one inside a closed `"…"`
    string, not a `#!` mode line), or None."""
    if line.lstrip().startswith("#!"):
        return None
    for m in _COMMENT_START_RE.finditer(line):
        inside = line.count('"', 0, m.start()) % 2 == 1 and '"' in line[m.start():]
        if not inside:
            return m.start()
    return None


def code_line(raw: str, masks=()) -> Code:
    """The Code of a raw line: comment cut, strings and dialect glyphs blanked."""
    pos = _comment_pos(raw)
    code = raw if pos is None else raw[:pos]
    masked = _mask_strings(code)
    dm = _apply_masks(masked, masks)
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

_CLOSER = {"[": "]", "{": "}", "<": ">", "(": ")", "|": "|"}


_GENERIC_RE = re.compile(r"<[^\[\]{}<>()|]*(?:<[^\[\]{}<>()|]*>[^\[\]{}<>()|]*)*>")


_WORD_RE = re.compile(r"[A-Za-z_\d][\w.-]*")


_MOD_NAME_RE = re.compile(r"@([A-Za-z][\w-]*)")


_CARD_RE = re.compile(r"×\s*(\w*)|(?<![\w.])x(\d+|N)\b(?=\s|$|@)|\*(\d+)\b")


_BOUND_RE = re.compile(r"\^(\w*)(?:@[a-z]+)?")


_FIELD_RE = re.compile(r"\.[A-Za-z_][\w.]*")


# Unicode arrows other than the core `→` (U+2192): `⇒`, `⟶`, `↦`, … are not arrows.
_FOREIGN_ARROW_RE = re.compile("[\u2190\u2191\u2193-\u21ff\u27f0-\u27ff\u2900-\u297f\u2b00-\u2bff]")


_BLOCK_OPEN_RE = re.compile(r"\{(?=\s|$)")


# Modifiers whose argument may run on without parens (`@owns |Conn|`, `@inv x`),
# to the next arrow, `@`, block `{` or line end — as the parser reads them.
_FREE_ARG_MODS = {"inv", "sla", "cap", "grants", "requires", "owns", "borrow", "loc",
                  "timeout", "after", "deadline"}


_NEEDS_ARG_MODS = {"timeout", "after", "deadline", "fallback"}


_POSITIVE_MODS = {"timeout", "deadline"}         # a zero or negative duration is no bound


_RESILIENCE_MODS = {"timeout", "deadline", "fallback"}


_TAIL_ONLY_RE = re.compile(r"^(?:\s*(?:×\s*\w+|x(?:\d+|N)\b|!(?![>=])))+\s*$")


# Trailing `×N` / `xN` / `^N` / `!` peeled off a payload (they are modifiers).
_PAYLOAD_TAIL_RE = re.compile(
    r"(?:\s*×\s*\w*|\s+x(?:\d+|N)\b|(?<=[\s>\]})|])\^\w*(?:@[a-z]+)?|\s+!(?![>=]))+\s*$")


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
    closer = _CLOSER[s[i]]
    j = i + 1
    while j < len(s):
        ch = s[j]
        if ch == ">" and j - 1 > i + 1 and s[j - 1] in "-~=!?*":
            return j - 1, "unclosed"                    # an arrow (even `<B ->`): resume at it
        if ch == closer:
            return j + 1, ("" if s[i + 1:j].strip() else "empty")
        if ch == "<":                                   # a generic: `[Cache<K,V>]`
            m = _GENERIC_RE.match(s, j)
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
        if s[k] == "@" or ARROW_RE.match(s, k) or _BLOCK_OPEN_RE.match(s, k):
            return k
        k += 1
    return k


def _scan_mod(s: str, i: int) -> tuple:
    """The modifier at s[i] (`@name`, its `( … )` and any free argument): (Tok, end)."""
    m = _MOD_NAME_RE.match(s, i)
    name, j = m.group(1), m.end()
    k = j
    while k < len(s) and s[k] == " " and name in _FREE_ARG_MODS:
        k += 1
    if k < len(s) and s[k] == "(":
        end = _balanced_end(s, k)
        if end < 0:
            return Tok("mod", s[i:], i, "unclosed"), len(s)
        arg = s[k + 1:end - 1].strip()
        if name in _FREE_ARG_MODS:
            more = _free_arg_end(s, end)
            if s[end:more].strip() and not _TAIL_ONLY_RE.match(s[end:more]):
                end = more
        return Tok("mod", s[i:end], i, _mod_problem(name, arg)), end
    end = _free_arg_end(s, j) if name in _FREE_ARG_MODS else j
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
    s = _mask_strings(raw)
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
    tail = _PAYLOAD_TAIL_RE.search(value)
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
        if not _MOD_NAME_RE.match(s, i):
            return [], i + 1
        tok, end = _scan_mod(s, i)
        return [tok], end
    if s[i] == "^":
        m = _BOUND_RE.match(s, i)
        return [Tok("bound", m.group(0), i, _count_problem(m.group(1)))], m.end()
    cm = _CARD_RE.match(s, i)
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
    if j < len(s) and s[j] in "[{<(|" and j > i and not _BLOCK_OPEN_RE.match(s, j):
        end, problem = _scan_glyph(s, j)
        return [Tok("glyph", s[i:end], i, problem)], end
    if j > i:                                       # `~` / `*` before no glyph
        return [Tok("bad", "~", i, "not-arrow")] if s[i] == "~" else [], j
    ch = s[i]
    if ch == "{" and _BLOCK_OPEN_RE.match(s, i):
        return [Tok("blockopen", "{", i)], i + 1
    if ch == "}":
        return [Tok("blockclose", "}", i)], i + 1
    if ch == "(" and toks and toks[-1].kind == "glyph" \
            and toks[-1].text.lstrip("~*").startswith("<") and not s[i - 1].isspace():
        end = _balanced_end(s, i)
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
    om = _OP_HEAD_RE.match(code.text, i)
    end = _balanced_end(code.text, om.end() - 1) if om else -1
    return ([Tok("op", code.text[i:end], i)], end) if end > 0 else None


def _scan_marker(code: Code, i: int, toks: list):
    """`!` critical / `?` optional, and a `.field` accessor after a glyph."""
    s = code.text
    bang = s[i] == "!" and not s.startswith(("!>", "!="), i)
    if bang or s[i] == "?" and not s.startswith("?>", i):
        return [Tok("mark", s[i], i)], i + 1
    if s[i] == "." and _after_glyph(toks):
        m = _FIELD_RE.match(s, i)
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
        end = _balanced_end(s, i + 1)
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


# -- rules over one statement's tokens ---------------------------------------

_STRUCTURAL = {"glyph", "nothing", "arrow", "join", "slash", "payload", "op", "word",
               "str", "blockopen", "blockclose", "alias", "bad"}


def _glyph_findings(toks: list) -> list:
    """SGL120 unclosed glyph · SGL121 empty glyph · SGL122 stray / mismatched closer."""
    out = []
    for t in toks:
        if t.kind == "glyph" and t.problem == "unclosed":
            out.append(("SGL120", f"unclosed glyph `{t.text.strip()}`: the parser reads a "
                        "different node (or none) here. Close it with its matching bracket."))
        elif t.kind == "glyph" and t.problem == "empty":
            out.append(("SGL121", f"empty glyph `{t.text.strip()}` names nothing and is "
                        "dropped. Name it, or write a hole (`[?]`) in sketch / craft."))
        elif t.kind == "glyph" and t.problem == "mismatched":
            out.append(("SGL122", f"glyph `{t.text.strip()}…` is closed by another kind's "
                        "bracket. Each glyph closes with its own: [] {} <> () ||."))
        elif t.kind == "bad" and t.problem == "closer":
            out.append(("SGL122", f"stray `{t.text}` closes no glyph; the parser ignores it."))
        elif t.kind == "blockclose":
            out.append(("SGL122", "stray `}` closes no block; the parser ignores it."))
    return out


def _arrow_findings(sig: list) -> list:
    """SGL130 an arrow with no endpoint · SGL131 a malformed arrow."""
    out = []
    if sig and sig[0].kind == "nothing":
        out.append(("SGL130", "a flow starts with `()`, which names no source."))
    for k, t in enumerate(sig):
        if t.kind == "bad" and t.problem == "not-arrow":
            out.append(("SGL131", f"`{t.text}` is not an arrow (arrows: "
                        f"{' '.join(ARROWS)}); the parser skips it, so no edge is drawn."))
            continue
        if t.kind != "arrow":
            continue
        nxt = sig[k + 1] if k + 1 < len(sig) else None
        if nxt is not None and nxt.kind == "arrow":
            out.append(("SGL131", f"two arrows in a row (`{t.text} {nxt.text}`): the parser "
                        f"keeps one and drops the other. Write one arrow per link."))
        elif nxt is None or nxt.kind in ("payload", "nothing", "str", "blockopen",
                                          "blockclose") or (nxt.kind == "word"
                                                            and nxt.text != "_"):
            what = ("nothing" if nxt is None else f"the payload `: {nxt.text}`"
                    if nxt.kind == "payload" else f"`{nxt.text}`")
            out.append(("SGL130", f"arrow `{t.text}` has no destination (it is followed by "
                        f"{what}); the parser draws no edge. Name the target glyph or op."))
    return out


def _join_findings(sig: list, is_alias: bool) -> list:
    """SGL132 a join (`&`, `&?`, `/`) with no glyph on one side, or no arrow."""
    out = []
    for k, t in enumerate(sig):
        if t.kind != "join":
            continue
        prev = sig[k - 1] if k else None
        nxt = sig[k + 1] if k + 1 < len(sig) else None
        if prev is None or prev.kind != "glyph" or nxt is None or nxt.kind != "glyph":
            out.append(("SGL132", f"join `{t.text}` needs a glyph on both sides "
                        "(`[A] & [B]`); the parser drops it here."))
            return out
    if not is_alias and any(t.kind == "join" for t in sig) \
            and not any(t.kind == "arrow" for t in sig):
        out.append(("SGL132", "a join with no arrow joins nothing: `[A] & [B]` must be "
                    "one end of a flow (`[A] & [B] -> [C]`)."))
    return out


def _payload_findings(toks: list, sig: list, is_alias: bool) -> list:
    """SGL150 payload with no flow · SGL151 unclosed payload or modifier · SGL152
    glyph after a payload."""
    out = []
    for t in toks:
        if t.kind == "payload" and t.problem == "unclosed":
            out.append(("SGL151", f"unclosed payload `{t.text}`: a string, `${{`, or "
                        "bracket is never closed, so the payload is kept as broken text."))
        elif t.kind == "mod" and t.problem == "unclosed":
            out.append(("SGL151", f"unclosed modifier `{t.text.strip()}`: its `(` is "
                        "never closed."))
        elif t.kind == "payload" and t.problem == "glyph-after":
            out.append(("SGL152", f"a glyph follows the payload `{t.text}` with no arrow: "
                        "the parser keeps it as payload text and draws no node. Add the "
                        "arrow, or move the glyph before the `:`."))
    payload = next((t for t in sig if t.kind == "payload"), None)
    if not is_alias and sig and sig[0].kind == "glyph" and payload is not None \
            and not any(t.kind == "arrow" for t in sig):
        out.extend(_lone_payload_finding(sig[0], payload))
    return out


def _lone_payload_finding(subject: Tok, payload: Tok) -> list:
    """SGL150 for a glyph subject with a payload and no arrow. A store slot with a
    value (`~|sys| : \"\"\"…\"\"\"`, `~|total| : ${x} + 1`) is a declaration, not a
    lost payload; so is an empty map (`~|graph| : {}`). A type annotation
    (`[A] : {X}`) is grammar the model drops."""
    kind = "map" if re.fullmatch(r"\{\s*\}", payload.text) else _classify_payload(payload.text)[0]
    if subject.text.lstrip("~*").startswith("|") and kind in ("value", "map"):
        return []
    if kind == "entity":
        return [("SGL150", f"the type annotation `: {payload.text}` is grammar, but the "
                 "parser keeps the node and drops the type, so no view or check sees it.")]
    return [("SGL150", "a payload with no flow: the parser keeps the node and "
             "drops the payload. Put it on a flow (`[A] -> [B] : {X}`).")]


class _LastLink(NamedTuple):
    """The statement's last link: its final endpoint's column, arrow and target."""
    end_col: int
    arrow: Tok
    dst: Optional[Tok]


def _last_link(sig: list) -> Optional[_LastLink]:
    ends = [t for t in sig if t.kind in ("glyph", "op")]
    arrows = [t for t in sig if t.kind == "arrow"]
    if not ends or not arrows:
        return None
    dst = next((t for t in sig if t.col > arrows[-1].col and t.kind in ("glyph", "op")), None)
    return _LastLink(ends[-1].col, arrows[-1], dst)


def _argument_findings(toks: list) -> list:
    """SGL180: a modifier, count or bound with a missing or impossible argument."""
    out = []
    for t in toks:
        if t.problem == "no-arg":
            out.append(("SGL180", f"`{t.text.strip()}` needs an argument "
                        f"(`{t.text.strip()}(…)`); the parser keeps it with none."))
        elif t.problem == "bad-duration":
            out.append(("SGL180", f"`{t.text.strip()}`: a duration must be positive."))
        elif t.problem == "no-count":
            out.append(("SGL180", f"`{t.text.strip()}` has no count (`×3`, `^100@drop`)."))
        elif t.problem == "zero":
            out.append(("SGL180", f"`{t.text.strip()}`: a count of zero is no count."))
    return out


def _trailing_findings(toks: list, sig: list) -> list:
    """What trails the last link: SGL182 a resilience modifier on a flow that is no
    call · SGL187 a spaced `×N` on a payload-less flow (cardinality or retries?)."""
    link = _last_link(sig)
    if link is None:
        return []
    out = []
    has_payload = any(t.kind == "payload" for t in sig)
    dst_text = link.dst.text.strip() if link.dst else ""
    for t in (t for t in toks if t.col > link.end_col):
        if t.kind == "mod" and _MOD_NAME_RE.match(t.text).group(1) in _RESILIENCE_MODS:
            data = link.dst is not None and link.dst.kind == "glyph" \
                and dst_text.lstrip("~*")[:1] in "{<"
            if link.arrow.text == "=>" or data:
                out.append(("SGL182", f"`{t.text.strip()}` sits on a flow that is not a "
                            f"call (`{link.arrow.text} {dst_text}`); resilience modifiers "
                            "bound a call (`->`, `<->`, `~>` to a component, actor, store "
                            "or op)."))
        elif t.kind == "card" and not t.glued and not has_payload and not t.problem:
            out.append(("SGL187", f"trailing `{t.text}` on a flow with no payload reads as "
                        f"cardinality; write `{dst_text or '[X]'}{t.text}` to say so, or "
                        "put it after a call payload (`: op() ×3`) for retries."))
    return out


def _marker_findings(toks: list) -> list:
    """SGL183: `!` / `?` between a glyph and an arrow marks the node, not the flow."""
    out = []
    for k, t in enumerate(toks):
        if t.kind != "mark" or not k or toks[k - 1].kind not in ("glyph", "field", "card"):
            continue
        nxt = next((u for u in toks[k + 1:] if u.kind != "mark"), None)
        if nxt is not None and nxt.kind == "arrow":
            out.append(("SGL183", f"`{t.text}` between a glyph and an arrow marks the node, "
                        "not the flow. Put it on the node's own line, or after the "
                        "flow's destination or payload."))
    return out


def statement_findings(line: int, code: Code, is_alias: bool = False) -> list:
    """Every hardening finding of one statement, as Findings."""
    toks = tokenize_statement(code)
    sig = [t for t in toks if t.kind in _STRUCTURAL]
    first_broken = next((t for t in toks if t.kind == "glyph"
                         and t.problem in ("unclosed", "mismatched")), None)
    if first_broken is not None:
        # A broken glyph throws the rest of the line out of step: report it alone.
        return [Finding(line, rule, msg) for rule, msg in _glyph_findings([first_broken])]
    pairs = (_glyph_findings(toks) + _arrow_findings(sig) + _join_findings(sig, is_alias)
             + _payload_findings(toks, sig, is_alias) + _argument_findings(toks)
             + _trailing_findings(toks, sig) + _marker_findings(toks))
    return [Finding(line, rule, msg) for rule, msg in pairs]


# -- the block structure -------------------------------------------------------

_SECTION_RE = re.compile(r"^-{2,}\s*(L\d+)?\s*:?\s*(.+?)\s*-{2,}\s*$")


_ALIAS_RE = re.compile(
    r"^(?:\[(?P<svc>[^\]]+)\]|\{(?P<data>[^}]+)\}|(?P<word>[A-Za-z_][\w.]*)|(?P<dia>\x01+))"
    r"\s*:=\s*(?P<rhs>.*)$")


_CONTROL_HEAD_RE = re.compile(r"^(loop|parallel|branch)\b")


_SCOPE_HEAD_RE = re.compile(r"^[A-Za-z_][\w.-]*\s*\{(?=\s|$)")


_ARM_RE = re.compile(r'^(?P<label>_|[\w.-]+|"[^"]*")\s*=>\s*(?P<body>.*)$')


_LOOP_BOUND_RE = re.compile(r"@(?:each|while|until|times)\b")


# A composition-branch body written without its `\-` (`*-> [X]`, `-& {H}`).
_BARE_BRANCH_RE = re.compile(
    r"^(?:\*-[>&?$@!=_]|-\*(?=\s|$)|-[&?$@!=_](?=\s)|\(\d+\)-[>&?$@!=_]"
    r"|\{[A-Za-z0-9_-]+\}-[>&?$@!=_])")


_HEADER_GLYPH_RE = re.compile(r"^[~*]*[\[{<(|](?P<name>[^\[\]{}<>()|]+)[\]}>)|]$")


_DROPS_BODY = ("alias", "state")


def _net_braces(text: str) -> int:
    return text.count("{") - text.count("}")


def _close_at(text: str, depth: int) -> Optional[int]:
    """Index of the `}` that closes a block open `depth` deep where `text` starts."""
    for i, ch in enumerate(text):
        depth += (ch == "{") - (ch == "}")
        if ch == "}" and depth <= 0:
            return i
    return None


def expansion_names(codes: list) -> set:
    """Names defined with `:=` anywhere in the document (`[Data] := {` → "Data")."""
    out = set()
    for code in codes:
        m = _ALIAS_RE.match(code.text.strip())
        if m:
            out.add(_alias_name(m, code))
    return out


def _alias_name(m: re.Match, code: Code) -> str:
    """The name an `_ALIAS_RE` match defines; a dialect glyph (`[[rate]] := {`) is
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


class _StructureWalk:
    """Follows a document's blocks as render's parser does: which lines are flows,
    which are block headers, transitions or section headers; where a continuation
    line has no subject. Collects the statements to tokenize (`stmts`) and the
    findings about structure (`findings`). Feed lines in order with `line()`, then
    call `finish()`."""

    def __init__(self, expansions: set, keywords=(), decl_blocks=()):
        self.expansions = expansions
        self.keyword_re = (re.compile(r"^(" + "|".join(map(re.escape, sorted(keywords)))
                                      + r")\b") if keywords else None)
        self.decl_blocks = list(decl_blocks)
        self.decl_depth = 0
        self.decl_on_raw = False
        self.frames: list = []
        self.subject = False        # a flow above that a continuation line takes
        self.blank = False          # a blank line since the last statement
        self.stmts: list = []       # (line, Code, is_alias)
        self.findings: list = []

    def add(self, line: int, rule: str, message: str):
        self.findings.append(Finding(line, rule, message))

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
            self._section(no, t)
        else:
            self._statement(no, code)
        self.blank = False

    def finish(self) -> list:
        for fr in self.frames:
            what = "its body is dropped" if fr.kind in _DROPS_BODY else \
                "the parser closes it at the end of the document"
            self.add(fr.line, "SGL160", f"block opened here is never closed: {what}. "
                     "Add the closing `}`.")
        self.frames = []
        return self.findings

    # -- line kinds ------------------------------------------------------------

    def _declaration(self, raw_lead: str, t: str) -> bool:
        """Dialect declaration blocks: consumed whole, never checked."""
        if self.decl_depth > 0:
            self.decl_depth += _net_braces(raw_lead if self.decl_on_raw else t)
            return True
        for opener, on_raw in self.decl_blocks:
            txt = raw_lead if on_raw else t
            if opener.match(txt):
                self.decl_depth = max(_net_braces(txt), 0)
                self.decl_on_raw = on_raw
                self.subject = False
                return True
        return False

    def _section(self, no: int, t: str):
        self.subject = False
        m = _SECTION_RE.match(t)
        if not m:
            self.add(no, "SGL184", "malformed section header: write `--- Lk: Name ---` or "
                     "`--- Name ---` (closing dashes included); the parser reads this "
                     "line as a flow.")
            return
        g = _HEADER_GLYPH_RE.match(m.group(2).strip())
        if m.group(1) and g and g.group("name").strip() not in self.expansions:
            self.add(no, "SGL184", f"section `{m.group(2).strip()}` names no expansion: "
                     f"nothing defines `{m.group(2).strip()} := {{ … }}`.")

    def _statement(self, no: int, code: Code):
        t = code.text.strip()
        if self._alias(no, code) or self._state_head(no, code) or self._block_head(no, code):
            return
        if self.frames:
            fr = self.frames[-1]
            before = fr.depth
            fr.depth += _net_braces(code.text)
            if fr.depth <= 0:
                cut = _close_at(code.text, before)
                cut = len(code.text) if cut is None else cut
                if code.text[:cut].strip():
                    self._flow(no, code.cut(0, cut))
                self._close(no)
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

    def _close(self, no: int):
        fr = self.frames.pop()
        if not fr.content and fr.kind != "keyword":
            self.add(fr.line, "SGL162", f"empty `{fr.kind}` block: it has no statements. "
                     "Fill it in or remove it.")
        if fr.kind == "alias":
            self.subject = False
        elif fr.kind != "state":
            self.subject = fr.glyphs
        if self.frames:
            self.frames[-1].glyphs |= fr.glyphs

    def _alias(self, no: int, code: Code) -> bool:
        t = code.text.strip()
        m = _ALIAS_RE.match(t)
        if not m:
            return False
        self.subject = False
        rhs = m.group("rhs")
        at = code.text.index(rhs, code.text.index(":=")) if rhs else len(code.text)
        brace = (code.text.index("{", at) if _BLOCK_OPEN_RE.match(rhs)
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
                self.stmts.append((no, body, True))
        return True

    def _state_head(self, no: int, code: Code) -> bool:
        t = code.text.strip()
        if not re.match(r"^state\b", t):
            return False
        om = _BLOCK_OPEN_RE.search(code.text)
        if om is None:
            return True
        saved = self.subject                    # a state block keeps the subject
        self._push("state", no, code.cut(om.end()))
        self.subject = saved
        return True

    def _block_head(self, no: int, code: Code) -> bool:
        t = code.text.strip()
        om = _BLOCK_OPEN_RE.search(code.text)
        head = code.text[:om.start()] if om else code.text
        hm = _CONTROL_HEAD_RE.match(t)
        if hm:
            kind = hm.group(1)
            if kind == "loop" and not _LOOP_BOUND_RE.search(head):
                self.add(no, "SGL163", "`loop` with no `@each`, `@while`, `@until` or "
                         "`@times`: say what bounds it.")
        elif self.keyword_re is not None and self.keyword_re.match(t):
            kind = "keyword"
        elif om and _SCOPE_HEAD_RE.match(t):
            kind = "scope"
        elif om and "@owns" in head and ANY_GLYPH_RE.search(head):
            kind = "owns"
        else:
            return False
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
        fr.depth += _net_braces(t)
        if fr.depth <= 0:
            cut = _close_at(t, before)
            t = t[:cut] if cut is not None else t
            if t.strip():
                fr.content = True
                self._transition(no, t)
            self._close(no)
            return
        fr.content = True
        self._transition(no, t)

    def _transition(self, no: int, t: str):
        if ARROW_RE.search(t) and "-<" not in t:
            self.add(no, "SGL161", f"transition `{t.strip()}` has no trigger: write "
                     "`Src -<trigger>-> Dst`. The parser keeps no cause for it.")

    def _flow(self, no: int, code: Code):
        t = code.text.strip()
        fr = self.frames[-1] if self.frames else None
        if fr is not None and fr.kind == "branch":
            am = _ARM_RE.match(t)
            if am and not ARROW_RE.match(t):
                fr.content = True
                self.subject = False
                body = am.group("body")
                if not body.strip():
                    return
                code = code.cut(code.text.rindex(body))
                t = body.strip()
        self._mark_content()
        if _BARE_BRANCH_RE.match(t):
            self.add(no, "SGL186", f"`{t.split()[0]}` looks like a composition branch "
                     "without its `\\-`; the parser reads it as a continuation line. "
                     "Write `\\-` before it.")
            return
        has_glyph = bool(ANY_GLYPH_RE.search(code.text) or DIALECT_COL in code.text)
        if ARROW_RE.match(t):                           # a continuation line
            if not self.subject:
                self.add(no, "SGL130", f"continuation `{t.split()[0]}` has no flow above "
                         "to continue (start of a document, section or block); the parser "
                         "drops its source.")
            elif self.blank:
                self.add(no, "SGL185", "continuation line after a blank line: it still "
                         "attaches to the flow above. Keep it directly under that flow.")
        elif has_glyph:
            self.subject = True
            if fr is not None:
                fr.glyphs = True
        self.stmts.append((no, code, False))


def reserved_marker_findings(lines: list) -> list:
    """SGL188: `#=` is reserved for the decorated acknowledgement (RFC 0003 Q7)."""
    out = []
    for no, raw in enumerate(lines, 1):
        pos = _comment_pos(raw)
        if pos is not None and raw.startswith("#=", pos):
            out.append(Finding(no, "SGL188", "`#=` is reserved for acknowledgements "
                               "(RFC 0003) and acknowledges nothing yet; write "
                               "`# accepts: rule — reason`, or a plain `# …` comment."))
    return out


# -- what the parser itself reports (Graph.dropped, edges by line) -------------

class ParsedFacts(NamedTuple):
    """What the parsed model says about each line, for the rules that ask the
    parser rather than re-read the text. `sources`: line → {(kind, name)} of every
    edge source on that line; `alias_refs`: line → {name} of each modifier alias
    after a `×N` that no modifier-only alias defines (render.ALIAS_REF);
    `untriggered`: lines of state-machine transitions with no trigger;
    `dropped`: (line, reason, text) the parser discarded."""
    sources: dict
    alias_refs: dict
    untriggered: frozenset
    dropped: tuple


def parsed_facts(graph) -> ParsedFacts:
    """The ParsedFacts of a render.Graph (every expansion and machine included)."""
    sources, alias_refs, untriggered = {}, {}, set()
    for sub, _owner, _lvl in walk_depth(graph):
        for e in sub.edges:
            src = sub.nodes.get(e.src)
            if src is not None:
                sources.setdefault(e.line, set()).add((src.kind, src.name))
            for name, arg in e.mods:
                if name == render.ALIAS_REF:
                    alias_refs.setdefault(e.line, set()).add(arg)
            if sub.role == "state" and e.label is None:
                untriggered.add(e.line)
    dropped = tuple((d.line, d.reason, d.text) for d in graph.dropped)
    return ParsedFacts(sources, alias_refs, frozenset(untriggered), dropped)


_EVENT_ARG_RE = re.compile(r"<([^<>\s][^<>]*)>\(")


def parser_gap_findings(codes: list, facts: ParsedFacts) -> list:
    """What the parsed model reports: SGL153 where an event argument still breaks
    the chain (a guard since catalog §6 B8: quiet while the parser reads the line), SGL181 a
    modifier alias after `×N` that nothing defines, SGL161 a transition with no
    trigger, and SGL160 / SGL161 for the lines it dropped (Graph.dropped)."""
    out = []
    for no, code in enumerate(codes, 1):
        for m in _EVENT_ARG_RE.finditer(code.text):
            end = _balanced_end(code.text, m.end() - 1)
            chained = end > 0 and ARROW_RE.match(code.text[end:].lstrip())
            if chained and ("event", m.group(1).strip()) not in facts.sources.get(no, set()):
                out.append(Finding(no, "SGL153", f"`<{m.group(1)}>(…)` breaks the chain: "
                                   "the parser draws no flow out of the event. Put the "
                                   "argument in a payload (`<E> -> [R] : {C}`)."))
    for no, names in facts.alias_refs.items():
        for name in sorted(names):
            out.append(Finding(no, "SGL181", f"`{name}` after `×N` names no modifier-only "
                               f"alias: define it (`{name} := @after(…)`) or write its "
                               "modifiers inline. The model keeps it as an unresolved name."))
    for no in facts.untriggered:
        out.append(Finding(no, "SGL161", "transition with no trigger: write "
                           "`Src -<trigger>-> Dst`. The parser keeps no cause for it."))
    for line, reason, text in facts.dropped:
        if reason == "unclosed":
            out.append(Finding(line, "SGL160", "the parser drops this line: it sits in a "
                               "block that is never closed."))
        elif reason == "no-owner" and text.startswith("state"):
            out.append(Finding(line, "SGL161", "`state` block with no owner glyph "
                               "(`state {Order} {`): the parser drops the whole machine."))
        elif reason == "not-a-transition" and "-<" not in text:
            out.append(Finding(line, "SGL161", f"`{text}` is not a transition "
                               "(`Src -<trigger>-> Dst`); the parser drops it."))
    return out


def hardening_findings(lines: list, masks=(), keywords=(), decl_blocks=(),
                       facts: Optional[ParsedFacts] = None) -> list:
    """Every hardening finding of a (pre-passed) document, in line order, at most
    one per rule per line. `facts` (from the parsed document) adds the rules that
    ask the parser; without it they are skipped."""
    codes = [code_line(raw, masks) for raw in lines]
    walk = _StructureWalk(expansion_names(codes), keywords, decl_blocks)
    for no, (raw, code) in enumerate(zip(lines, codes), 1):
        walk.line(no, raw.strip(), code)
    found = walk.finish() + reserved_marker_findings(lines)
    for no, code, is_alias in walk.stmts:
        found += statement_findings(no, code, is_alias)
    if facts is not None:
        found = _with_parser_gaps(found, parser_gap_findings(codes, facts))
    return _one_per_rule_and_line(found)


def _with_parser_gaps(found: list, gaps: list) -> list:
    """Add the parser's findings: an unclosed block is one SGL160 at its opener (the
    walker's); the parser's per-line SGL160 stands in only when the walker saw none."""
    walker_saw = any(f.rule == "SGL160" for f in found)
    dropped = [f for f in gaps if f.rule == "SGL160"]
    return found + [f for f in gaps if f.rule != "SGL160"] + ([] if walker_saw else dropped[:1])


def _one_per_rule_and_line(found: list) -> list:
    """The findings in (line, rule) order, the first of each (line, rule) kept."""
    seen, out = set(), []
    for f in sorted(found, key=lambda f: (f.line, f.rule)):
        if (f.line, f.rule) not in seen:
            seen.add((f.line, f.rule))
            out.append(f)
    return out


ANY_TARGET_WORD = r"(?!op\b)[A-Za-z_][\w.-]*"   # a bare word that is not an op call


def target_word_mask(words):
    """A glyph mask (length-preserving `fn(line) -> line`) that blanks each of a
    dialect's bare-word arrow targets (`<go> -> context`) right after an arrow, so
    the hardening scan reads it as a dialect endpoint; None when there are none.
    `words` is a set of words, or ANY_TARGET_WORD for every bare word (not an op
    call `run()` or the `op` keyword)."""
    if not words:
        return None
    alt = words if isinstance(words, str) else "|".join(map(re.escape, sorted(words)))
    rx = re.compile(ARROW_RE.pattern + r"(\s*)(" + alt + r")(?![\w.(-])")
    return lambda line: rx.sub(lambda m: m.group(1) + m.group(2) + " " * len(m.group(3)), line)


def lint_hardening(lines: list, result: LintResult, dialect=None, graph=None):
    """Report the hardening findings (SGL120–SGL188) on `result`. `graph` is the
    parsed document (render.parse_document), or None when it could not be parsed."""
    # A dialect owns its vocabulary: one that has not said which bare words it
    # reads as arrow targets keeps every bare word there (core cannot judge them).
    if dialect is not None and not hasattr(dialect, "ARROW_TARGET_WORDS"):
        target_mask = target_word_mask(ANY_TARGET_WORD)
    else:
        target_mask = target_word_mask(set(_hook(dialect, "ARROW_TARGET_WORDS", set())))
    for f in hardening_findings(
            lines,
            masks=list(_hook(dialect, "lint_glyph_masks")) + ([target_mask] if target_mask else []),
            keywords=set(_hook(dialect, "BLOCK_KEYWORDS", set())),
            decl_blocks=list(_hook(dialect, "DECLARATION_BLOCKS")),
            facts=parsed_facts(graph) if graph is not None else None):
        result.add(HARDENING_SEVERITY[f.rule], f.line, f.rule, f.message)
