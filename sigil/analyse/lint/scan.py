"""
The text scanning lint's rules share: the length-preserving masks (strings,
principal sets, a dialect's spans), the block-string pre-pass
(collapse_block_strings, which reports SGL170), the hole and modifier tables, a
state block's lines, the op-call verb rule (_VerbPattern) and the dialect hook
reader. Lint's own copies of the tables the parser keeps too: the shared-tables
step moves them to sigil.core.lex.
"""

import re
import unicodedata
from typing import Optional

from sigil.core.vocab import COMMENT_START_RE as _COMMENT_START_RE, LintResult, strip_comment


def _hook(dialect, name: str, default=()):
    """Read an optional dialect hook (see dialects.py): a callable hook is called,
    a data hook returned as-is, a missing one (or no dialect) gives `default`."""
    if dialect is None:
        return default
    val = getattr(dialect, name, None)
    if val is None:
        return default
    return val() if callable(val) else val


# Permission graph — an access modifier `@read(…)` / `@write(…)` carrying a `( )`
# comma-list of bare principal names permitted that access on a store. It joins the
# capability-modifier family (`@grants`/`@requires`/`@owns`/`@borrow`, `@cap(read,
# write)`), every member of which takes its args in `( )`, never `{ }`.
# `PRINCIPAL_SET_RE` captures the modifier + its `( )` list so the structural
# linters can MASK it (a `(boss, worker)` list is NOT an actor glyph).
PRINCIPAL_SET_RE = re.compile(
    r"@(?P<mod>read|write)\s*\((?P<set>[^()]*)\)"
)


# `@borrow(…)` with a narrowing arg, lending access to a delegate (the lent
# resource is a store `|S|` or a bare name). The arg is captured whatever it is so
# lint_permission_graph can reject anything but `read` / `write`; bare `@borrow`
# (full access) has no arg to check.
BORROW_ACCESS_RE = re.compile(r"@borrow\s*\((?P<arg>[^)]*)\)")


def _mask_principal_sets(line: str) -> str:
    """Blank out permission-graph access modifiers `@read(…)` / `@write(…)` (and
    their `( )` principal lists) so the contained `(boss, worker)` list is NOT
    mis-read as an actor-glyph `(X)` by the structural / payload linters. The
    members are bare principal names, not glyphs. The dedicated
    `lint_permission_graph` validates them. Length-preserving."""
    return PRINCIPAL_SET_RE.sub(lambda m: " " * len(m.group(0)), line)


# A bare principal name in a set — a declared entity name or a generic role name.
PRINCIPAL_NAME_RE = re.compile(r"^[A-Za-z_][\w-]*$")


# A hole glyph (`[?]`, `{?}`, `<?>`, `(?)`, `|?|`).
HOLE_RE = re.compile(r"(\[\?\]|\{\?\}|<\?>|\(\?\)|\|\?\|)")


# A `"…"` string literal (masked by the per-line rules so its text is inert).
_STRING_RE = re.compile(r'"[^"]*"')


# An @-modifier token.
_MODIFIER_RE = re.compile(r"@[a-z][a-z0-9_-]*")


# A state-block header: `state <owner-glyph> {`, the owner optionally `~`/`*`
# prefixed and carrying one level of generics (`state {Job<T>} {`).
STATE_HEADER_RE = re.compile(
    r"^state\s*[~*]*[\[{<(|][^\[\]{}<>()|]+(?:<[^\[\]{}<>()|]+>)?[\]}>)|]\s*\{"
)


# Multiline block-string delimiter — a `str` literal's triple-quoted multiline form
# `"""…"""` (language.md "Multiline block-strings"). It is sigil's ONLY multiline
# construct.
BLOCK_DELIM = '"""'


# The masked stand-in a folded block body collapses to — an ordinary single-line
# STR value, so every downstream per-line linter reads the block as a normal `str`
# (trailing modifiers after the closing delimiter survive). The sentinel carries no
# glyphs / arrows / `:` so it perturbs no linter.
_BLOCK_SENTINEL = '"block-string"'


# ---------------------------------------------------------------------------
# Multiline block-strings — the `"""…"""` pre-pass (sigil's ONLY multiline form)
# ---------------------------------------------------------------------------
#
# A STR literal has a triple-quoted multiline form `"""…"""` (language.md
# "Multiline block-strings") — usable wherever a single-line STR is accepted. This
# is the ONE place sigil leaves strict line-orientation. To keep that cost CONTAINED
# to this token, the rest of the linter is NOT taught about blocks; instead a single
# tightly-scoped PRE-PASS folds each `"""…"""` block into a masked single-line STR
# on its opening line and BLANKS the consumed body lines. Line numbering is
# preserved (the list length is unchanged), so every downstream per-line linter
# runs UNCHANGED on a fully line-oriented document — the block reads to it as an
# ordinary `: "<…>"` value. `${…}` inside the block is NOT substituted here: sigil
# carries the template text; whatever consumes the design assembles/substitutes it.

def _block_open_pos(raw: str) -> Optional[int]:
    """Index of an opening `\"\"\"` on this line that is NOT inside a trailing
    comment, or None. A `#!` mode line never opens a block; a `\"\"\"` sitting after
    a `#` comment-start is comment text, not a delimiter (so `# see \"\"\"` is inert)."""
    if raw.lstrip().startswith("#!"):
        return None
    pos = raw.find(BLOCK_DELIM)
    if pos == -1:
        return None
    cm = _COMMENT_START_RE.search(raw)
    if cm and cm.start() < pos:
        return None
    return pos


def collapse_block_strings(lines: list, result: LintResult) -> list:
    """Pre-pass: fold every `\"\"\"…\"\"\"` multiline block-string into a masked
    single-line STR on its opening line, blanking the consumed body lines (the
    list length — and so every later diagnostic's line number — is preserved).
    The opening line becomes `<prefix>"block-string"<suffix>`, where `<suffix>` is
    whatever followed the closing `\"\"\"` (any trailing modifiers) so they
    survive. An unterminated block (opening `\"\"\"` with no closing `\"\"\"`) is
    rejected (SGL170). Tightly scoped to the `\"\"\"` token — nothing else in the
    linter leaves line-orientation."""
    out = list(lines)
    n = len(out)
    i = 0
    while i < n:
        open_pos = _block_open_pos(out[i])
        if open_pos is None:
            i += 1
            continue
        prefix = out[i][:open_pos]
        after_open = out[i][open_pos + len(BLOCK_DELIM):]
        # Degenerate single-line `"""…"""` (open + close on one physical line).
        # The folded line goes back through the scan (`i` is not advanced): the
        # suffix may open another block.
        close_rel = after_open.find(BLOCK_DELIM)
        if close_rel != -1:
            suffix = after_open[close_rel + len(BLOCK_DELIM):]
            out[i] = prefix + _BLOCK_SENTINEL + suffix
            continue
        # Multiline: consume forward to the line carrying the closing `"""`.
        j = i + 1
        while j < n and BLOCK_DELIM not in out[j]:
            j += 1
        if j >= n:
            result.add(
                "error", i + 1, "SGL170",
                "unterminated block-string: an opening `\"\"\"` has no matching "
                "closing `\"\"\"`. A `\"\"\"…\"\"\"` multiline string must be closed.",
            )
            # Blank the opening line too — a malformed (unterminated) block is one
            # hard error (SGL170); don't also leak a downstream payload diagnostic
            # on the dangling `"""`.
            for k in range(i, n):
                out[k] = ""
            break
        # Fold onto the opening line and rescan it: the closing line's suffix may
        # open another block (`""" -> [C] : """`).
        suffix = out[j][out[j].find(BLOCK_DELIM) + len(BLOCK_DELIM):]
        out[i] = prefix + _BLOCK_SENTINEL + suffix
        for k in range(i + 1, j + 1):
            out[k] = ""
    return out


def _apply_masks(line: str, masks) -> str:
    """Apply dialect glyph masks (length-preserving `fn(line) -> line`) in order."""
    for mask in masks:
        line = mask(line)
    return line


def _mask_strings(line: str) -> str:
    """Blank the text inside `"…"` string literals (the quotes stay), so `;`, `@`,
    holes, glyphs and prose inside a string payload are inert. Length-preserving."""
    return _STRING_RE.sub(lambda m: '"' + " " * (len(m.group(0)) - 2) + '"', line)


def _iter_state_block(lines: list):
    """Yield `(line_no, line, where)` for every line, `line` comment-stripped and
    trimmed. `where` is "header" for a `state … {` opener, "body" inside its block,
    "end" for the line that closes it, else None."""
    in_state_block = False
    brace_depth = 0
    for i, raw in enumerate(lines, start=1):
        line = strip_comment(raw).strip()
        if STATE_HEADER_RE.match(line):
            in_state_block = True
            brace_depth = line.count("{") - line.count("}")
            yield i, line, "header"
            continue
        if in_state_block:
            brace_depth += line.count("{") - line.count("}")
            if brace_depth <= 0:
                in_state_block = False
                yield i, line, "end"
            else:
                yield i, line, "body"
            continue
        yield i, line, None


def _is_mark(ch: str) -> bool:
    """A combining mark that joins the letter before it: nonspacing (Mn),
    spacing (Mc) or enclosing (Me, e.g. U+20DD around a letter)."""
    return unicodedata.category(ch) in ("Mn", "Mc", "Me")


def _marks_follow_letters(verb: str) -> bool:
    """Every character of `verb` that is no word character or other ASCII is a
    combining mark right after a letter or another mark (render's rule: a
    decomposed `ガ`, `カ` + U+3099, is one letter of a verb, a symbol is not)."""
    prev = ""
    for ch in verb:
        if not (ch.isascii() or ch.isalnum()) and not (
                _is_mark(ch) and prev and (prev.isalpha() or _is_mark(prev))):
            return False
        prev = ch
    return True


class _VerbPattern:
    """A compiled pattern whose `verb` group may also hold combining marks
    (render._VerbPattern): `match` is `re.Pattern.match`, None when the verb
    holds anything else that is no word character.

    A copy of render's rule (with `_is_mark` and `_marks_follow_letters`): lint.py
    is a standalone tool and imports nothing from render.py;
    tests/test_lint_verb_rules.py asserts the two copies agree."""

    _MARKISH = r"[^\s\w\x00-\x7f]"   # non-ASCII, no word character, no space

    def __init__(self, pattern: str):
        self._rx = re.compile(pattern.replace("{MARK}", self._MARKISH))

    def match(self, text: str, pos: int = 0):
        m = self._rx.match(text, pos)
        return m if m and _marks_follow_letters(m.group("verb")) else None


# A payload that is an op-call: `op ns.verb(args)` (external) / `verb(args)`.
_EXT_OP_RE = _VerbPattern(
    r"^op\s+(?P<verb>[^\W\d](?:\w|{MARK})*(?:\.[^\W\d](?:\w|{MARK})*)+)\s*\((.*)\)\s*$")


_INT_OP_RE = _VerbPattern(r"^(?P<verb>[^\W\d](?:\w|{MARK})*)\s*\(.*\)\s*$")


_OP_HEAD_RE = _VerbPattern(r"(?:op\s+)?(?P<verb>[^\W\d](?:[\w.]|{MARK})*)\(")  # render.OP_TARGET_RE


def _balanced_end(s: str, i: int) -> int:
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
