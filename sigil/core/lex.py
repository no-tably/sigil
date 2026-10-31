"""
lex — the lexical tables of Sigil text, kept once: the statement walk
(sigil.core.statements), its tokenizer (sigil.core.tokens), the parser
(sigil.core.parse) and lint (sigil.analyse.lint) all read lines through these,
one reading each:

    source        MAX_SOURCE_BYTES, SourceError, read_source (a document's
                  file or stdin), decode_source (its bytes: UTF-8, a leading
                  BOM dropped), split_lines (its lines: \n, \r\n or \r ends one)
    comments      is_mode_line, is_comment_line, first_content, COMMENT_START_RE, in_string, comment_start, comment_col,
                  DECLARATION_MARK, DECLARATION_RE, declaration_name (a
                  line-leading `#& name …`: a dialect declaration),
                  code_end (where a line's code ends: `#` or a dialect's
                  comment marker, outside a `"…"` string), strip_comment
    strings       STRING_RE, mask_strings
    block strings BLOCK_DELIM, BLOCK_SENTINEL, fold_block_strings → Folded
    verbs         is_mark, marks_follow_letters, VerbPattern; OP_TARGET_RE (a
                  flow's op-call target), EXT_OP_RE / INT_OP_RE (an op-call
                  payload), OP_HEAD_RE (an op-call's head `verb(`)
    arrows        ARROWS, ARROW_RE
    glyphs        GLYPH_BRACKETS (the core kinds' brackets: OPEN_TO_KIND,
                  CLOSER, OPENERS, CLOSERS and their regex classes,
                  GLYPH_PATTERNS read off it, glyph_name_source),
                  GLYPH_PREFIXES, glyph_kind,
                  NAME_CHARS, GENERIC, NOT_A_SET, NOT_A_MEMBER_SET, is_set,
                  GLYPH_RE, GENERIC_RE, ANY_GLYPH_RE, HOLE_RE, DIALECT_COL
    modifiers     PAREN_ARG, FREE_ARG_MODS, ARG_MODIFIERS, MODIFIER_RE,
                  MOD_TOKEN_RE, MOD_NAME_RE, TAIL_ONLY_RE, PRINCIPAL_SET_RE,
                  blank_access_lists,
                  STREAM_BOUND_RE, GLUED_MOD_RE, TAIL_MOD_RE, CARD_RE, BOUND_RE,
                  FIELD_RE, ALIAS_REF_RE, ALIAS_REF
    payloads      PAYLOAD_RE, PAYLOAD_TAIL_RE, PAYLOAD_TAIL_LOOSE_RE
    heads         SECTION_RE, ALIAS_RE, EXPANSION_OPEN_RE, BLOCK_OPEN_RE,
                  STATE_HEAD_RE, STATE_OPEN_RE, LOOP_HEAD_RE,
                  SCOPE_HEAD_RE, ARM_RE, BRANCH_RE, BRANCH_PARENT_RE,
                  CORE_RELATIONS, BRANCH_ANY_RE, branch_re, BARE_BRANCH_RE,
                  BRANCH_LEAD_RE,
                  close_at, net_braces (braces in a string are string text)
    scanning      balanced_end (a bracket group's end)

A dialect's hooks are read by sigil.core.dialects._hook; its vocabulary (the
names a dialect builds on) is re-exported by sigil.core.vocab.

Standard library only; imports nothing of sigil.
"""

import errno
import re
import sys
import unicodedata
from pathlib import Path
from typing import NamedTuple, Optional

# ---------------------------------------------------------------------------
# Source — a document's text, read the one way every command reads it
# ---------------------------------------------------------------------------

MAX_SOURCE_BYTES = 64 * 1024 * 1024   # a document larger than this is refused
BOM = "\ufeff"
_LINE_END_RE = re.compile(r"\r\n|\r|\n")


class SourceError(OSError):
    """A document that can't be read as Sigil text (not UTF-8, too large).
    An OSError, so every `cannot read F: …` message says it: str(exc.strerror)
    is the reason."""

    def __init__(self, code: int, reason: str):
        super().__init__(code, reason)


def decode_source(data: bytes) -> str:
    """A document's text from its bytes: strict UTF-8, a leading byte-order
    mark dropped (editors hide it; it would hide the `#!` mode line). Raises
    SourceError naming the line of the first byte that is not UTF-8."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        line = len(split_lines(data[:exc.start].decode("utf-8", "replace") + "x"))
        raise SourceError(errno.EILSEQ, f"not UTF-8 (line {line}: {exc.reason})") from None
    return text[1:] if text.startswith(BOM) else text


def read_source(path) -> str:
    """The document at `path` (a str or Path; `-`: standard input), as
    decode_source reads it. Raises OSError: the file's own, or SourceError for
    one over MAX_SOURCE_BYTES or not UTF-8."""
    limit = MAX_SOURCE_BYTES
    if str(path) == "-":
        stream = getattr(sys.stdin, "buffer", None)
        data = stream.read(limit + 1) if stream is not None \
            else sys.stdin.read(limit + 1).encode("utf-8")
    else:
        with Path(path).open("rb") as fh:
            data = fh.read(limit + 1)
    if len(data) > limit:
        raise SourceError(errno.EFBIG, f"larger than {limit // (1024 * 1024)} MiB "
                                       f"({limit} bytes)")
    return decode_source(data)


def split_lines(text: str) -> list:
    """A document's lines, as editors count them: a line ends at \\n, \\r\\n
    or \\r only — a form feed, NEL, U+2028/2029 and the other breaks
    str.splitlines knows stay in their line. A final line end opens no line
    (as str.splitlines). A leading byte-order mark is dropped."""
    if text.startswith(BOM):
        text = text[1:]
    lines = _LINE_END_RE.split(text)
    if lines[-1] == "":
        lines.pop()
    return lines

# ---------------------------------------------------------------------------
# Comments and strings
# ---------------------------------------------------------------------------

# A comment starts at a `#` at line start or after whitespace — not the `#!` mode
# line — and never inside a `"…"` string (`: "issue #5"` is a payload; see
# comment_start). A `#&` (DECLARATION_MARK) also starts here: it is erased from
# flows like a comment, but it is dialect syntax, not prose, so the parser never
# makes a note of it; leading a line it is a declaration (declaration_name).
COMMENT_START_RE = re.compile(r"(?<!\S)#(?!!)")

# A dialect declaration (language.md "Dialects"): a line led by `#&`, then the
# name of what it declares — `#& name …`, or `#&name` the same — the name being
# NAME_CHARS up to a space, `~`, `{` or the end of the line (it may be empty). The
# name belongs to a dialect (its DECLARATIONS). The statement walk reads such a
# line as a statement that draws nothing, and a `{ … }` block it opens as its
# body (sigil.core.statements); it is never a comment, a note or a flow.
DECLARATION_MARK = "#&"


def declaration_name(line: str) -> Optional[str]:
    """The name a line-leading `#&` declaration gives ("" when it names none), or
    None when the line is no declaration (see DECLARATION_RE)."""
    if DECLARATION_MARK not in line:
        return None
    m = DECLARATION_RE.match(line)
    return m.group("name") if m else None


def in_string(line: str, pos: int) -> bool:
    """Whether `pos` sits inside a closed `"…"` span (an odd number of quotes
    before it and at least one after; an unclosed quote opens no string)."""
    return line.count('"', 0, pos) % 2 == 1 and '"' in line[pos:]


def comment_start(line: str, notes_only: bool = False):
    """The match of the first comment `#` on the line outside a `"…"` string, or
    None. `notes_only` skips a `#&` (DECLARATION_MARK, see COMMENT_START_RE)."""
    if "#" not in line:
        return None
    if '"' not in line and not notes_only:
        return COMMENT_START_RE.search(line)
    for m in COMMENT_START_RE.finditer(line):
        if in_string(line, m.start()):
            continue
        if notes_only and line.startswith(DECLARATION_MARK, m.start()):
            continue
        return m
    return None


def is_mode_line(line: str) -> bool:
    """Whether the line is a `#!` mode line (indented or not): it holds no code
    and no comment."""
    return line.lstrip().startswith("#!")


def is_comment_line(line: str) -> bool:
    """Whether the line is a core comment and nothing else: its first non-blank
    is a `#` (a bare `#` counts) that is not the `#!` mode line nor a `#&`
    declaration, which is a statement and so comes after the mode line. A
    dialect's comment markers are not read here: the mode-line rules see a line
    of them as content, as they always have."""
    s = line.lstrip()
    return s.startswith("#") and not s.startswith("#!") and declaration_name(s) is None


def first_content(lines) -> Optional[int]:
    """The index of the first line that is neither blank nor a comment line
    (is_comment_line) — where a document's mode line belongs — or None."""
    return next((k for k, line in enumerate(lines)
                 if line.strip() and not is_comment_line(line)), None)


def comment_col(line: str) -> Optional[int]:
    """Column of the comment `#` on the line (not one inside a closed `"…"`
    string, not on a line that is a `#!` mode line once indented), or None."""
    if is_mode_line(line):
        return None
    m = comment_start(line)
    return m.start() if m else None


def code_end(line: str, marker: Optional[re.Pattern] = None) -> int:
    """Where the line's code ends: at its comment `#` (comment_col) or at the
    first of a dialect's comment markers (`marker`, matched at line start or
    after whitespace) outside a `"…"` string; else the line's length."""
    col = comment_col(line)
    end = len(line) if col is None else col
    if marker is not None and not is_mode_line(line):
        for m in marker.finditer(line, 0, end):
            if not in_string(line, m.start()):
                return m.start()
    return end


def strip_comment(line: str) -> str:
    """The line without its comment, a `#` inside a `"…"` string kept; a `#!`
    mode line is returned whole."""
    if "#" not in line or line.startswith("#!"):
        return line
    m = comment_start(line)
    if m:
        return line[: m.start()]
    return line


# A `"…"` string literal (masked by lint's per-line rules so its text is inert).
STRING_RE = re.compile(r'"[^"]*"')


def mask_strings(line: str) -> str:
    """Blank the text inside `"…"` string literals (the quotes stay), so `;`, `@`,
    holes, glyphs and prose inside a string payload are inert. Length-preserving."""
    if '"' not in line:
        return line
    return STRING_RE.sub(lambda m: '"' + " " * (len(m.group(0)) - 2) + '"', line)


# ---------------------------------------------------------------------------
# Multiline block-strings — `"""…"""` (language.md "Multiline block-strings")
# ---------------------------------------------------------------------------
#
# A STR literal has a triple-quoted multiline form, sigil's ONLY multiline
# construct. Readers fold each block into a masked single-line STR on its opening
# line and blank the consumed body lines, so line numbering is preserved and every
# later per-line reading runs unchanged: the block reads as an ordinary `: "<…>"`
# value. `${…}` inside a block is not substituted: sigil carries the template text.

BLOCK_DELIM = '"""'
# The masked STR a block folds to. It carries no glyphs / arrows / `:`, so it
# perturbs no later reading; trailing modifiers after the closing delimiter survive.
BLOCK_SENTINEL = '"block-string"'


class Folded(NamedTuple):
    """fold_block_strings' result: the folded lines (same count as given) and the
    index of an opening `\"\"\"` that is never closed (None when every block
    closes); from that line on every line is blanked. `quoted`: the indices of
    the lines a block's body consumed (after each opening line, its closing
    line included; an unterminated block's every later line)."""
    lines: list
    unterminated: Optional[int]
    quoted: frozenset = frozenset()


def block_open_pos(raw: str) -> Optional[int]:
    """Index of an opening `\"\"\"` on this line that is NOT comment text, or
    None. A `#!` mode line never opens a block; a `\"\"\"` after the line's
    comment `#` is comment text (`# see \"\"\"` is inert)."""
    pos = raw.find(BLOCK_DELIM)
    if pos == -1 or is_mode_line(raw):
        return None
    col = comment_col(raw)
    if col is not None and col < pos:
        return None
    return pos


def fold_block_strings(lines: list, bodies: Optional[dict] = None) -> Folded:
    """Fold each `\"\"\"…\"\"\"` block into BLOCK_SENTINEL on its opening line,
    blanking the consumed body lines. A folded line is read again: whatever
    followed the closing `\"\"\"` may open another block (`\"\"\" -> [C] :
    \"\"\"`). `bodies`, when given, gets {opening line index: the text of the
    line's first block} for each terminated block (a payload is terminal: the
    first block on a line is its flow's). An unterminated block blanks every line
    from its opener."""
    out = list(lines)
    n = len(out)
    quoted = set()
    i = 0
    while i < n:
        open_pos = block_open_pos(out[i])
        if open_pos is None:
            i += 1
            continue
        prefix = out[i][:open_pos]
        after_open = out[i][open_pos + len(BLOCK_DELIM):]
        close_rel = after_open.find(BLOCK_DELIM)
        if close_rel != -1:           # degenerate single-line `"""…"""`
            if bodies is not None:
                bodies.setdefault(i, after_open[:close_rel])
            out[i] = prefix + BLOCK_SENTINEL + after_open[close_rel + len(BLOCK_DELIM):]
            continue
        j = i + 1
        while j < n and BLOCK_DELIM not in out[j]:
            j += 1
        if j >= n:
            for k in range(i, n):
                out[k] = ""
            return Folded(out, i, frozenset(quoted | set(range(i + 1, n))))
        close = out[j].find(BLOCK_DELIM)
        if bodies is not None:
            bodies.setdefault(i, "\n".join([after_open] + out[i + 1:j] + [out[j][:close]]))
        out[i] = prefix + BLOCK_SENTINEL + out[j][close + len(BLOCK_DELIM):]
        for k in range(i + 1, j + 1):
            out[k] = ""
            quoted.add(k)
    return Folded(out, None, frozenset(quoted))


# ---------------------------------------------------------------------------
# The op-call verb rule
# ---------------------------------------------------------------------------

def is_mark(ch: str) -> bool:
    """A combining mark that joins the letter before it: nonspacing (Mn),
    spacing (Mc) or enclosing (Me, e.g. U+20DD around a letter)."""
    return unicodedata.category(ch) in ("Mn", "Mc", "Me")


def marks_follow_letters(verb: str) -> bool:
    """Every character of `verb` that is no word character or other ASCII is a
    combining mark right after a letter or another mark: a decomposed `ガ`
    (`カ` + U+3099) is one letter of a verb, a symbol is not."""
    prev = ""
    for ch in verb:
        if not (ch.isascii() or ch.isalnum()) and not (
                is_mark(ch) and prev and (prev.isalpha() or is_mark(prev))):
            return False
        prev = ch
    return True


class VerbPattern:
    """A compiled pattern whose `verb` group may also hold combining marks
    (`re` has no class for them): `match` is `re.Pattern.match`, None when the
    verb holds anything else that is no word character. `{MARK}` in the source
    stands for such a character."""

    _MARKISH = r"[^\s\w\x00-\x7f]"   # non-ASCII, no word character, no space

    def __init__(self, pattern: str):
        self.pattern = pattern.replace("{MARK}", self._MARKISH)
        self._rx = re.compile(self.pattern)

    def match(self, text: str, pos: int = 0):
        m = self._rx.match(text, pos)
        return m if m and marks_follow_letters(m.group("verb")) else None


# A verb starts with any letter or `_`, never a digit; a combining mark after a
# letter stays in it. A dotted verb (`ns.run`) may hold dots anywhere after its
# first letter; an external op's namespace and verb are word segments.
_VERB_WORD = r"[^\W\d](?:\w|{MARK})*"
_VERB_DOTTED = r"[^\W\d](?:[\w.]|{MARK})*"

# An internal op-call written as a flow's target: `[Worker] -> run()`,
# `-> run({Job})`, `-> walk(.children)` (no space before the `(`: `-> x (Y)` is
# a word and an actor). An `op ns.verb(…)` external reach is taken too
# (`-> 短縮({網址})`, `-> カ\u3099ス()`).
OP_TARGET_RE = VerbPattern(
    r"(?:op\s+)?(?P<verb>" + _VERB_DOTTED + r")\((?:[^()]|\([^()]*\))*\)")

# A payload that is an op-call: `op ns.verb(args)` (external) / `verb(args)`.
EXT_OP_RE = VerbPattern(
    r"^op\s+(?P<verb>" + _VERB_WORD + r"(?:\." + _VERB_WORD + r")+)\s*\((.*)\)\s*$")
INT_OP_RE = VerbPattern(r"^(?P<verb>" + _VERB_WORD + r")\s*\(.*\)\s*$")

# The head `verb(` of an op-call where a flow names one (OP_TARGET_RE's head).
OP_HEAD_RE = VerbPattern(r"(?:op\s+)?(?P<verb>" + _VERB_DOTTED + r")\(")


# ---------------------------------------------------------------------------
# Arrows and joins
# ---------------------------------------------------------------------------

# The closed arrow set, ordered longest-first so `<->` is not matched as `->`.
ARROWS = ["<->", "->", "~>", "=>", "!>", "?>", "*>", "→"]
ARROW_RE = re.compile("(" + "|".join(map(re.escape, ARROWS)) + ")")


# ---------------------------------------------------------------------------
# Glyphs
# ---------------------------------------------------------------------------

# A glyph's name may carry generics (language.md "Parametric"): `[Cache<K,V>]`,
# `{List<T>}`, `<Msg<T>>` — one level of nesting inside the generic list
# (`{List<Map<K,V>>}`). The generic is part of the ONE glyph's name.
NAME_CHARS = r"[^\[\]\{\}<>()|]"
# A `#&` declaration's line: the mark, spaces, the name (declaration_name).
DECLARATION_RE = re.compile(r"\s*" + DECLARATION_MARK + r"\s*(?P<name>(?:(?![\s~])"
                            + NAME_CHARS + r")*)")
GENERIC = (r"<" + NAME_CHARS + r"*(?:<" + NAME_CHARS + r"*>" + NAME_CHARS + r"*)*>")
GENERIC_RE = re.compile(GENERIC)
# The core glyph kinds and their brackets — the one table; the views below and
# core.graph.GLYPH_KINDS (a node's label brackets) are read off it.
GLYPH_BRACKETS = {
    "service": ("[", "]"),
    "data":    ("{", "}"),
    "event":   ("<", ">"),
    "actor":   ("(", ")"),
    "store":   ("|", "|"),
}

# Each glyph's opening bracket → its kind, and → its closing bracket.
OPEN_TO_KIND = {open_: kind for kind, (open_, _close) in GLYPH_BRACKETS.items()}
CLOSER = dict(GLYPH_BRACKETS.values())

# Every glyph's opening / closing bracket as one string, and the prefixes a glyph
# may carry (`~` mutable, then `*` stream); OPENERS_CLASS, CLOSERS_CLASS and
# PREFIXES_CLASS are regex classes of them.
OPENERS = "".join(OPEN_TO_KIND)
CLOSERS = "".join(CLOSER.values())
GLYPH_PREFIXES = "~*"
OPENERS_CLASS = "[" + re.escape(OPENERS) + "]"
CLOSERS_CLASS = "[" + re.escape(CLOSERS) + "]"
PREFIXES_CLASS = "[" + re.escape(GLYPH_PREFIXES) + "]"



def glyph_kind(text: str) -> Optional[str]:
    """The core kind whose opening bracket `text` starts with once its `~` / `*`
    prefixes are skipped (`~|S|` → "store", `*<E>` → "event"), or None."""
    return OPEN_TO_KIND.get(text.lstrip(GLYPH_PREFIXES)[:1])


# A set (language.md: `{Order}.status ∈ {pending, active}`): braces whose name
# holds a comma — before any generic `<…>` — are a value, never a data glyph, so
# a glyph name never holds a comma and a set makes no node wherever it stands.
# `{Cache<K,V>}` is still a glyph (its comma is a generic's) and `{A}, {B}` is two.
# Braces right after `∈` or `∉` (up to three blanks between) are a set whatever
# they hold: `∈ {Proposed}` is a one-member set, not a data glyph.
# NOT_A_SET, written just after a glyph's opening bracket, refuses a `{` set;
# NOT_A_MEMBER_SET, written just before a `{`, refuses the braces after `∈` / `∉`.
_MEMBER_BLANKS = range(4)
NOT_A_MEMBER_SET = "".join(r"(?<![∈∉][ \t]{%d})" % n for n in _MEMBER_BLANKS)
NOT_A_SET = (r"(?:(?<!\{)|(?!" + NAME_CHARS + r"*,)"
             + "".join(r"(?<![∈∉][ \t]{%d}\{)" % n for n in _MEMBER_BLANKS) + ")")
_SET_RE = re.compile(r"\{" + NAME_CHARS + r"*,")
_MEMBER_END_RE = re.compile(r"[∈∉][ \t]{0,%d}$" % _MEMBER_BLANKS[-1])


def is_set(text: str, before: str = "") -> bool:
    """Whether a bracket group's text (its `~` / `*` prefixes skipped) is a set
    `{a, b}`: a value, not a data glyph. `before`: the text the group follows on
    its line, so braces right after `∈` / `∉` read as a set (`∈ {Proposed}`)."""
    bare = text.lstrip(GLYPH_PREFIXES)
    return bool(_SET_RE.match(bare)) or (
        bare.startswith("{") and text == bare and _MEMBER_END_RE.search(before) is not None)


GLYPH_RE = re.compile(
    r"(?P<mut>~)?(?P<stream>\*)?"
    r"(?P<open>" + OPENERS_CLASS + ")" + NOT_A_SET +
    r"(?P<name>" + NAME_CHARS + r"+(?:" + GENERIC + r")?)"
    r"(?P<close>" + CLOSERS_CLASS + ")"
)


def glyph_name_source(kind: str, group: str = "") -> str:
    """The regex source of one `kind` glyph, its name captured (no bracket of its
    own inside) — group 1, or the named group `group` when given."""
    open_, close = GLYPH_BRACKETS[kind]
    inside = "".join(map(re.escape, dict.fromkeys(open_ + close)))
    cap = f"(?P<{group}>" if group else "("
    member, not_set = (NOT_A_MEMBER_SET, r"(?![^{}<]*,)") if kind == "data" else ("", "")
    return f"{member}{re.escape(open_)}{not_set}{cap}[^{inside}]+){re.escape(close)}"


# One pattern per core glyph kind, group 1 the name (no generics: lint's reading).
GLYPH_PATTERNS = {kind: re.compile(glyph_name_source(kind)) for kind in GLYPH_BRACKETS}

# Any glyph at all (for flow-line analysis). The `<->` bidirectional arrow is
# never an event glyph `<-…>`.
ANY_GLYPH_RE = re.compile(
    r"(\[[^\[\]]+\]|" + NOT_A_MEMBER_SET + r"\{(?![^{}<]*,)[^\{\}]+\}|<(?!->)[^<>]+>|\([^()]+\)|\|[^|]+\|)"
)

# The pieces of a shown text — a payload, a modifier's argument, a block header,
# a section title — finer than a statement's tokens (sigil.core.tokens hands a
# payload back as one span): strings, `${…}` references, glyphs (with their `~` /
# `*` prefix), call names, operators, counts, modifiers, the `op` keyword,
# numbers and punctuation. Only colour reads it (sigil.present.kit's payload runs,
# sigil.present.highlight); what it reads decides no fact.
PAYLOAD_PIECE_RE = re.compile(r"""
    (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<ref>\$\{[^}]*\})
  | (?P<glyph>""" + PREFIXES_CLASS + r"""?(?:\[[^\]\s,][^\],]*\]|""" + NOT_A_MEMBER_SET + r"""\{[^}\s:,][^}:,]*\}|<(?!->)[^<>\s][^<>]*>
                    |(?<!\w)\([^)\s][^)]*\)|\|[^|\s][^|]*\|))
  | (?P<call>[A-Za-z_][\w.]*)(?=\()
  | (?P<operator>=>|->|~>|!>|\?>|\*>|<->|\+\+|\|\||[+\-*/])
  | (?P<cardinality>[×^]\d+\w*)
  | (?P<modifier>@[A-Za-z_][\w-]*)
  | (?P<keyword>\bop\b)
  | (?P<number>\b\d+(?:\.\d+)?\b)
  | (?P<punct>[(),:{}\[\]])
""", re.X)

# A hole glyph (`[?]`, `{?}`, `<?>`, `(?)`, `|?|`).
HOLE_RE = re.compile(r"(\[\?\]|\{\?\}|<\?>|\(\?\)|\|\?\|)")

# Stands in for each column of a dialect glyph in a statement's Code (a glyph one
# of the dialect's tokenizers reads), so text-reading rules see an endpoint there
# and never read the glyph's own brackets.
DIALECT_COL = "\x01"


# ---------------------------------------------------------------------------
# Modifiers
# ---------------------------------------------------------------------------

# A modifier's `( … )` argument, one level of nested parens allowed (`@inv(f(x) > 0)`).
PAREN_ARG = r"\((?:[^()]|\([^()]*\))*\)"

# Modifiers whose argument may also (or further) follow without parens (`@owns
# |Conn|`, `@inv unique:order_id`, `@borrow(read) |tree|`): that argument runs to the
# next arrow, `@`, block `{` or line end. Their contents are semantic, not
# structural — they must not leak as phantom glyphs. Lint reads these.
FREE_ARG_MODS = ("inv", "sla", "cap", "grants", "requires", "owns", "borrow",
                 "loc", "timeout", "after", "deadline")
# The parser reads `@notify`'s argument that way too (lint reports `@notify` as an
# unknown modifier, so it never reads its argument).
ARG_MODIFIERS = FREE_ARG_MODS + ("notify",)

# Every modifier (a property, not a flow or a node — it leaves no phantom node): one
# of ARG_MODIFIERS with its argument, or any other `@name` with an optional `( … )`.
# Only the modifier and its argument go: `[A] @timeout(5s) -> [B]` keeps its flow.
MODIFIER_RE = re.compile(
    r"(?P<arg>@(?:" + "|".join(ARG_MODIFIERS) + r")\b"
    r"(?:\s*" + PAREN_ARG + r")?[^\n@]*?(?=\s*(?:" + ARROW_RE.pattern + r")|@|$))"
    r"|@[a-z][a-z0-9_-]*(?:" + PAREN_ARG + r")?"
)

# An @-modifier token, name only (lint's per-line rules).
MOD_TOKEN_RE = re.compile(r"@[a-z][a-z0-9_-]*")

# An @-modifier's name, any case (group 1; lint's statement scanner).
MOD_NAME_RE = re.compile(r"@([A-Za-z][\w-]*)")

# What may follow a modifier's `( … )` argument and still be other modifiers:
# `@timeout(30s) ×3` is two modifiers, not one with the argument "(30s) ×3".
TAIL_ONLY_RE = re.compile(r"^(?:\s*(?:×\s*\w+|x(?:\d+|N)\b|!(?![>=])))+\s*$")

# Permission-graph access modifiers `@read(…)` / `@write(…)` (language.md
# "Permission graph"), carrying a `( )` comma-list of principal names — a
# DECLARATION of access edges on a store, not a flow. The parser captures them
# before other modifiers and lint masks them, so a list like `(boss, worker)` is
# never read as an actor glyph.
PRINCIPAL_SET_RE = re.compile(
    r"@(?P<mod>read|write)\s*\((?P<set>[^()]*)\)"
)


def blank_access_lists(text: str) -> str:
    """`text` with each `@read(…)` / `@write(…)` access list blanked to spaces
    (length-preserving): its members are principal names, never glyphs."""
    if "@" not in text:
        return text
    return PRINCIPAL_SET_RE.sub(lambda m: " " * len(m.group(0)), text)


# A stream bound `^N` / `^N@policy` (language.md "Streams"), glued to a glyph:
# captured before the generic `@name` modifier rule, which would otherwise take
# its `@policy`. (`x^2` in a value is not a bound.)
STREAM_BOUND_RE = re.compile(r"(?<=[\]}>)|\s])\^[A-Za-z0-9]+(?:@[a-z]+)?")

# Modifiers glued to (or right after) a glyph, read by the parser's tokenizer:
# `×N`, the legacy `*N`, ASCII `xN`, `!` critical, `?` optional, `.field`.
GLUED_MOD_RE = re.compile(
    r"×\s*(?P<card>\w+)"
    r"|\*\s*(?P<card2>\d+)\b"
    r"|(?<![\w.])x(?P<card3>\d+|N)\b(?=\s|$|@)"
    r"|(?P<bang>!)(?![>=])"
    r"|(?P<opt>\?)(?!>)"
    r"|\.(?P<field>[A-Za-z_][\w.]*)"
)

# The modifiers the parser peels off a payload's tail (`: score ×3`, `: {Cart} !`).
TAIL_MOD_RE = re.compile(r"×\s*(\w+)|x(\d+|N)\b|\^(\w+(?:@\w+)?)|(!)")

# Lint's statement scanner: a cardinality (an empty `×` count is taken, to be
# reported), a stream bound, a `.field` reach.
CARD_RE = re.compile(r"×\s*(\w*)|(?<![\w.])x(\d+|N)\b(?=\s|$|@)|\*(\d+)\b")
BOUND_RE = re.compile(r"\^(\w*)(?:@[a-z]+)?")
FIELD_RE = re.compile(r"\.[A-Za-z_][\w.]*")

# Modifier aliases named after a retry count at a payload's end (`: charge ×3 Retry`,
# `Retry := @after(…)`): each name is an (ALIAS_REF, name) modifier until the
# document is read, then the alias's own modifiers.
ALIAS_REF_RE = re.compile(r"(?:×\s*\w+|(?<!\w)x(?:\d+|N))(?P<names>(?:\s+[A-Za-z_][\w-]*)+)\s*$")
ALIAS_REF = "alias"


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------

# The terminal `: payload` of a flow (not a `:=` alias), up to any `@` left outside
# a `"…"` string.
PAYLOAD_RE = re.compile(r'\s*:(?!=)\s*((?:"[^"]*"|[^@])*?)(?=@|$)')

# Trailing cardinality (`×3`, ` x3`), stream-bound (`^5`) and `!` tokens after a
# payload: modifiers, not payload text (a `×` inside a string or value is left
# alone). The parser's: a count is required, a bound follows a space or `>`.
PAYLOAD_TAIL_RE = re.compile(r"(?:\s*×\s*\w+|\s+x(?:\d+|N)\b|(?<=[\s>])\^\w+|\s+!(?![>=]))+\s*$")
# Lint's: an empty count is taken too (to be reported), a bound may follow any
# glyph's closer and carry its `@policy`.
PAYLOAD_TAIL_LOOSE_RE = re.compile(
    r"(?:\s*×\s*\w*|\s+x(?:\d+|N)\b|(?<=[\s>\]})|])\^\w*(?:@[a-z]+)?|\s+!(?![>=]))+\s*$")


# ---------------------------------------------------------------------------
# Statement heads and blocks
# ---------------------------------------------------------------------------

# Section header `-- L2: Name --` (the layer is optional).
SECTION_RE = re.compile(r"^-{2,}\s*(L\d+)?\s*:?\s*(.+?)\s*-{2,}\s*$")

# `name := expr`, `[name] := expr` or `{name} := expr` — a definition, not a flow.
_ALIAS_HEADS = r"\[(?P<svc>[^\]]+)\]|\{(?P<data>[^}]+)\}|(?P<word>[A-Za-z_][\w.]*)"
ALIAS_RE = re.compile(r"^(?:" + _ALIAS_HEADS + r")\s*:=\s*(?P<rhs>.*)$")
# The `:=` after a definition head written as a dialect glyph (`[[rate]] := {`).
DEFINE_RE = re.compile(r"\s*:=\s*(?P<rhs>.*)$")

# An alias right-hand side that opens an expansion block: a bare `{` (`X := {`,
# `X := { [A] -> [B] }`) — not a data glyph (`X := {Summary} cache` is an alias).
# EXPANSION_OPEN_RE consumes the space after it, BLOCK_OPEN_RE only looks.
EXPANSION_OPEN_RE = re.compile(r"\{(\s|$)")
BLOCK_OPEN_RE = re.compile(r"\{(?=\s|$)")

# A state-machine header: `state <glyph> {` — any glyph owns the machine (`{Order}`
# a record's lifecycle, `[Checkout]` a component's own modes). STATE_OPEN_RE also
# takes a malformed header (no owner glyph: `state {`, `state Foo {`), whose block
# is consumed unparsed. The owner's prefixes are a glyph's (GLYPH_RE: `~`, then
# `*`), so `state ~~{X} {` has no owner to the walk, as to the parser.
STATE_HEAD_RE = re.compile(r"^state\s*(~?\*?" + OPENERS_CLASS + NAME_CHARS + r"+(?:"
                           + GENERIC + r")?" + CLOSERS_CLASS + r")\s*\{")
STATE_OPEN_RE = re.compile(r"^state(?:\s[^{]*)?\{")

# A control block header: its statements are ordinary flows.
LOOP_HEAD_RE = re.compile(r"^(loop|parallel|branch)\b")
# A scoped block `name { … }` (language.md "Structure").
SCOPE_HEAD_RE = re.compile(r"^[A-Za-z_][\w.-]*\s*\{(?=\s|$)")
# A branch arm `label => flow` (grammar: arm := (name | '_') '=>' flow).
ARM_RE = re.compile(r'^(?P<label>_|[\w.-]+|"[^"]*")\s*=>\s*(?P<body>.*)$')

# A composition-tree branch marker: `\\-` [`*-` spawn] [`(N)-` weight | `{cond}-`]
# <rel>, or a bare spawn `\\-*`. Core relations are CORE_RELATIONS; the parser
# accepts the wider punctuation set of BRANCH_RE so a dialect's extra relations
# still place in the tree, and lint decides which relations are valid
# (branch_re(CORE_RELATIONS + a dialect's COMPOSITION_RELATIONS)).
BRANCH_RE = re.compile(
    r"\\-(?:(?P<spawn>\*)-)?(?:\((?P<weight>\d+)\)-|\{(?P<cond>[A-Za-z0-9_-]+)\}-)?"
    r"(?P<rel>[>+#_^v$?!&@=])(?=\s|$)"
    r"|\\-(?P<bare_spawn>\*)(?=\s|$)"
)
CORE_RELATIONS = ">&?$@!=_"
# What may precede an inline branch (`[parent] \\-& [child]`): glyphs only — no
# payload colon, no prose.
BRANCH_PARENT_RE = re.compile(r"^\s*" + PREFIXES_CLASS + "?" + OPENERS_CLASS + "[^:]*" + CLOSERS_CLASS
                              + r"\s*$")
BRANCH_ANY_RE = re.compile(r"\\-")


def branch_re(relations: str) -> re.Pattern:
    """A well-formed branch marker whose relation is one of `relations`."""
    rel = re.escape(relations)
    return re.compile(
        rf"\\-(?:\*-)?(?:\(\d+\)-|\{{[A-Za-z0-9_-]+\}}-)?[{rel}](?=\s|$)|\\-\*(?=\s|$)")


# A composition-branch body written without its `\-` (`*-> [X]`, `-& {H}`).
BARE_BRANCH_RE = re.compile(
    r"^(?:\*-[>&?$@!=_]|-\*(?=\s|$)|-[&?$@!=_](?=\s)|\(\d+\)-[>&?$@!=_]"
    r"|\{[A-Za-z0-9_-]+\}-[>&?$@!=_])")

# What leads a statement that stands as a composition branch, well formed or not
# (lint judges the marker): a `\\-`, or a bare `*-`, `{c}-`, `(N)-` written
# without it, its relation not looked at.
BRANCH_LEAD_RE = re.compile(r"^\s*(?:" + BRANCH_ANY_RE.pattern + r"|\*-|\{[^}]*\}-|\(\d+\)-)")


def net_braces(text: str) -> int:
    """How many more `{` than `}` the text holds (a brace in a string is string
    text, not a brace)."""
    if '"' in text:
        text = mask_strings(text)
    return text.count("{") - text.count("}")


def close_at(text: str, depth: int) -> Optional[int]:
    """Index of the `}` in `text` that closes a block open `depth` deep where the
    text starts, or None when the block stays open past it (a brace in a string
    is string text)."""
    if '"' in text:
        text = mask_strings(text)
    for i, ch in enumerate(text):
        depth += (ch == "{") - (ch == "}")
        if ch == "}" and depth <= 0:
            return i
    return None


# ---------------------------------------------------------------------------
# Scanning helpers
# ---------------------------------------------------------------------------

def balanced_end(s: str, i: int) -> int:
    """Index just past the `( [ {` group opening at s[i], or -1 if it never closes
    (or closes with the wrong bracket)."""
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack = []
    for j in range(i, len(s)):
        ch = s[j]
        if ch in pairs:
            stack.append(pairs[ch])
        elif ch in ")]}":
            if not stack or ch != stack.pop():
                return -1
            if not stack:
                return j + 1
    return -1
