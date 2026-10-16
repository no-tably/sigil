"""
lex — the lexical tables of Sigil text, kept once: the parser (sigil.core.parse)
and lint (sigil.analyse.lint) both read lines through these. Where the two read
a piece of text differently on purpose, both readings live here side by side,
named apart (the parser's first, lint's after it):

    comments      COMMENT_START_RE, in_string, comment_start, comment_col,
                  strip_comment (string-aware: the parser's),
                  strip_comment_plain (any `#` after whitespace: lint's and the
                  dialect API's), plain_comment_col
    strings       STRING_RE, mask_strings
    block strings BLOCK_DELIM, BLOCK_SENTINEL, fold_block_strings → Folded
    verbs         is_mark, marks_follow_letters, VerbPattern; OP_TARGET_RE (a
                  flow's op-call target), EXT_OP_RE / INT_OP_RE (an op-call
                  payload), OP_HEAD_RE (an op-call's head `verb(`)
    arrows        ARROWS, ARROW_RE, JOIN_RE
    glyphs        NAME_CHARS, GENERIC, GLYPH_RE, OPEN_TO_KIND, CLOSER, GENERIC_RE,
                  GLYPH_PATTERNS, ANY_GLYPH_RE, HOLE_RE, DIALECT_COL
    modifiers     PAREN_ARG, FREE_ARG_MODS, ARG_MODIFIERS, MODIFIER_RE,
                  MOD_TOKEN_RE, MOD_NAME_RE, TAIL_ONLY_RE, PRINCIPAL_SET_RE,
                  STREAM_BOUND_RE, GLUED_MOD_RE, TAIL_MOD_RE, CARD_RE, BOUND_RE,
                  FIELD_RE, ALIAS_REF_RE, ALIAS_REF
    payloads      PAYLOAD_RE, PAYLOAD_TAIL_RE, PAYLOAD_TAIL_LOOSE_RE
    heads         SECTION_RE, ALIAS_RE, ALIAS_MASKED_RE, EXPANSION_OPEN_RE,
                  BLOCK_OPEN_RE, STATE_HEAD_RE, STATE_OPEN_RE, STATE_HEAD_FLAT_RE,
                  LOOP_HEAD_RE, SCOPE_HEAD_RE, ARM_RE, BRANCH_RE, CORE_RELATIONS,
                  BRANCH_ANY_RE, branch_re, BARE_BRANCH_RE, close_at, net_braces

A dialect's hooks are read by sigil.core.dialects._hook; its vocabulary (the
names a dialect builds on) is re-exported by sigil.core.vocab.

Standard library only; imports nothing of sigil.
"""

import re
import unicodedata
from typing import Callable, NamedTuple, Optional

# ---------------------------------------------------------------------------
# Comments and strings
# ---------------------------------------------------------------------------

# A comment starts at a `#` at line start or after whitespace — not the `#!` mode
# line. The parser also skips a `#` inside a `"…"` string (`: "issue #5"` is a
# payload; see comment_start); lint's plain reading does not (strip_comment_plain).
# A `#&…` marker also starts here: it is erased from flows like a comment, but it
# is dialect syntax (e.g. a declaration-block opener), not prose, so the parser
# never makes a note of it.
COMMENT_START_RE = re.compile(r"(?<!\S)#(?!!)")


def in_string(line: str, pos: int) -> bool:
    """Whether `pos` sits inside a closed `"…"` span (an odd number of quotes
    before it and at least one after; an unclosed quote opens no string)."""
    return line.count('"', 0, pos) % 2 == 1 and '"' in line[pos:]


def comment_start(line: str, notes_only: bool = False):
    """The match of the first comment `#` on the line outside a `"…"` string, or
    None. `notes_only` skips `#&` markers (see COMMENT_START_RE)."""
    for m in COMMENT_START_RE.finditer(line):
        if in_string(line, m.start()):
            continue
        if notes_only and line.startswith("&", m.end()):
            continue
        return m
    return None


def comment_col(line: str) -> Optional[int]:
    """Column of the comment `#` on the line (not one inside a closed `"…"`
    string, not on a line that is a `#!` mode line once indented), or None."""
    if line.lstrip().startswith("#!"):
        return None
    m = comment_start(line)
    return m.start() if m else None


def plain_comment_col(line: str) -> Optional[int]:
    """Column of the first comment start on the line, strings not looked at."""
    m = COMMENT_START_RE.search(line)
    return m.start() if m else None


def strip_comment(line: str) -> str:
    """The line without its comment, a `#` inside a `"…"` string kept; a `#!`
    mode line is returned whole (the parser's reading)."""
    if line.startswith("#!"):
        return line
    m = comment_start(line)
    if m:
        return line[: m.start()]
    return line


def strip_comment_plain(line: str) -> str:
    """Remove inline comments: a `#` at the start of the line or after whitespace
    starts one, unless it is a `#!` (a mode line is returned whole). Not
    inside-string aware (lint's reading, and the dialect API's strip_comment)."""
    if line.startswith("#!"):
        return line
    col = plain_comment_col(line)
    if col is not None:
        return line[:col]
    return line


# A `"…"` string literal (masked by lint's per-line rules so its text is inert).
STRING_RE = re.compile(r'"[^"]*"')


def mask_strings(line: str) -> str:
    """Blank the text inside `"…"` string literals (the quotes stay), so `;`, `@`,
    holes, glyphs and prose inside a string payload are inert. Length-preserving."""
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
    closes); from that line on every line is blanked."""
    lines: list
    unterminated: Optional[int]


def _block_open_pos(raw: str, comment_at: Callable[[str], Optional[int]]) -> Optional[int]:
    """Index of an opening `\"\"\"` on this line that is NOT comment text, or None.
    A `#!` mode line never opens a block; a `\"\"\"` after the comment start
    `comment_at` finds is comment text (`# see \"\"\"` is inert)."""
    if raw.lstrip().startswith("#!"):
        return None
    pos = raw.find(BLOCK_DELIM)
    if pos == -1:
        return None
    col = comment_at(raw)
    if col is not None and col < pos:
        return None
    return pos


def fold_block_strings(lines: list, comment_at: Callable[[str], Optional[int]], *,
                       rescan: bool, bodies: Optional[dict] = None) -> Folded:
    """Fold each `\"\"\"…\"\"\"` block into BLOCK_SENTINEL on its opening line,
    blanking the consumed body lines. `comment_at` tells comment text from a
    delimiter (the parser: comment_col; lint: plain_comment_col). `rescan` reads a
    folded line again (whatever followed the closing `\"\"\"` may open another
    block: lint); without it reading goes on after the block (the parser).
    `bodies`, when given, gets {opening line index: the block's text} for each
    terminated block. An unterminated block blanks every line from its opener."""
    out = list(lines)
    n = len(out)
    i = 0
    while i < n:
        open_pos = _block_open_pos(out[i], comment_at)
        if open_pos is None:
            i += 1
            continue
        prefix = out[i][:open_pos]
        after_open = out[i][open_pos + len(BLOCK_DELIM):]
        close_rel = after_open.find(BLOCK_DELIM)
        if close_rel != -1:           # degenerate single-line `"""…"""`
            if bodies is not None:
                bodies[i] = after_open[:close_rel]
            out[i] = prefix + BLOCK_SENTINEL + after_open[close_rel + len(BLOCK_DELIM):]
            i += 0 if rescan else 1
            continue
        j = i + 1
        while j < n and BLOCK_DELIM not in out[j]:
            j += 1
        if j >= n:
            for k in range(i, n):
                out[k] = ""
            return Folded(out, i)
        close = out[j].find(BLOCK_DELIM)
        if bodies is not None:
            bodies[i] = "\n".join([after_open] + out[i + 1:j] + [out[j][:close]])
        out[i] = prefix + BLOCK_SENTINEL + out[j][close + len(BLOCK_DELIM):]
        for k in range(i + 1, j + 1):
            out[k] = ""
        i = i if rescan else j + 1
    return Folded(out, None)


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

# Strict join `&` / race `&?` between glyphs (language.md "a & b").
JOIN_RE = re.compile(r"&\??")


# ---------------------------------------------------------------------------
# Glyphs
# ---------------------------------------------------------------------------

# A glyph's name may carry generics (language.md "Parametric"): `[Cache<K,V>]`,
# `{List<T>}`, `<Msg<T>>` — one level of nesting inside the generic list
# (`{List<Map<K,V>>}`). The generic is part of the ONE glyph's name.
NAME_CHARS = r"[^\[\]\{\}<>()|]"
GENERIC = (r"<" + NAME_CHARS + r"*(?:<" + NAME_CHARS + r"*>" + NAME_CHARS + r"*)*>")
GENERIC_RE = re.compile(GENERIC)
GLYPH_RE = re.compile(
    r"(?P<mut>~)?(?P<stream>\*)?"
    r"(?P<open>[\[\{<\(\|])"
    r"(?P<name>" + NAME_CHARS + r"+(?:" + GENERIC + r")?)"
    r"(?P<close>[\]\}>\)\|])"
)

OPEN_TO_KIND = {
    "[": "service",
    "{": "data",
    "<": "event",
    "(": "actor",
    "|": "store",
}

# Each glyph's opening bracket → its closing one.
CLOSER = {"[": "]", "{": "}", "<": ">", "(": ")", "|": "|"}

# One pattern per core glyph kind, group 1 the name (no generics: lint's reading).
GLYPH_PATTERNS = {
    "service": re.compile(r"\[([^\[\]]+)\]"),
    "data":    re.compile(r"\{([^\{\}]+)\}"),
    "event":   re.compile(r"<([^<>]+)>"),
    "actor":   re.compile(r"\(([^()]+)\)"),
    "store":   re.compile(r"\|([^|]+)\|"),
}

# Any glyph at all (for flow-line analysis). The `<->` bidirectional arrow is
# never an event glyph `<-…>`.
ANY_GLYPH_RE = re.compile(
    r"(\[[^\[\]]+\]|\{[^\{\}]+\}|<(?!->)[^<>]+>|\([^()]+\)|\|[^|]+\|)"
)

# A hole glyph (`[?]`, `{?}`, `<?>`, `(?)`, `|?|`).
HOLE_RE = re.compile(r"(\[\?\]|\{\?\}|<\?>|\(\?\)|\|\?\|)")

# Stands in for each column of a dialect glyph once lint masks it (a dialect's
# lint_glyph_masks), so the glyph still counts as an endpoint.
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
# Lint's: a masked dialect glyph (DIALECT_COL columns, group `dia`) may be named too.
ALIAS_MASKED_RE = re.compile(
    r"^(?:" + _ALIAS_HEADS + r"|(?P<dia>" + DIALECT_COL + r"+))\s*:=\s*(?P<rhs>.*)$")

# An alias right-hand side that opens an expansion block: a bare `{` (`X := {`,
# `X := { [A] -> [B] }`) — not a data glyph (`X := {Summary} cache` is an alias).
# EXPANSION_OPEN_RE consumes the space after it, BLOCK_OPEN_RE only looks.
EXPANSION_OPEN_RE = re.compile(r"\{(\s|$)")
BLOCK_OPEN_RE = re.compile(r"\{(?=\s|$)")

# A state-machine header: `state <glyph> {` — any glyph owns the machine (`{Order}`
# a record's lifecycle, `[Checkout]` a component's own modes). STATE_OPEN_RE also
# takes a malformed header (no owner glyph), whose block is consumed unparsed.
STATE_HEAD_RE = re.compile(r"^state\s*([~*]*[\[{<(|]" + NAME_CHARS + r"+(?:" + GENERIC
                           + r")?[\]}>)|])\s*\{")
STATE_OPEN_RE = re.compile(r"^state\s*\{")
# Lint's: the owner carries at most one level of generics, unnested
# (`state {Job<T>} {`), nothing captured.
STATE_HEAD_FLAT_RE = re.compile(
    r"^state\s*[~*]*[\[{<(|][^\[\]{}<>()|]+(?:<[^\[\]{}<>()|]+>)?[\]}>)|]\s*\{"
)

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


def net_braces(text: str) -> int:
    """How many more `{` than `}` the text holds."""
    return text.count("{") - text.count("}")


def close_at(text: str, depth: int) -> Optional[int]:
    """Index of the `}` in `text` that closes a block open `depth` deep where the
    text starts, or None when the block stays open past it."""
    for i, ch in enumerate(text):
        depth += (ch == "{") - (ch == "}")
        if ch == "}" and depth <= 0:
            return i
    return None
