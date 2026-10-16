"""
What lint reads off a document's one reading (sigil.core.statements.Walk), for
the rules that judge a line rather than a statement: each line's code as those
rules see it (LineView), the lines `state` blocks cover, the tokens of the
control-block headers — and the block-string report (SGL170). Nothing here reads
the text again: comments, strings, dialect glyphs, the dialect's strips and the
composition branch markers are where the walk found them.
"""

from typing import NamedTuple

from sigil.core.lex import DIALECT_COL, PRINCIPAL_SET_RE, fold_block_strings
from sigil.core.statements import BlockOpen, Definition, Doc, StateEnd, StateHead, Walk
from sigil.core.vocab import LintResult


class LineView(NamedTuple):
    """One line's code as the per-line rules read it. `plain`: the comment cut,
    string contents blanked, the dialect's strips and the composition branch
    markers read past blanked, a dialect glyph's text kept. `bare`: `plain` with
    each dialect glyph and each `@read(…)` / `@write(…)` access list blanked too
    (neither holds glyphs: a list's members are principal names)."""
    plain: str
    bare: str


def line_views(walk: Walk, markers: dict) -> tuple:
    """A LineView per line of `walk`. `markers`: {line index: [(start, end)]} of
    the branch markers to blank (composition.branch_markers)."""
    texts = [c.text for c in walk.codes]
    raws = [c.raw for c in walk.codes]
    for st in walk.statements:
        k, at = st.line - 1, st.code.col
        texts[k] = _overlay(texts[k], st.code.text, at)
        raws[k] = _overlay(raws[k], st.code.raw, at)
    views = []
    for k, (text, raw) in enumerate(zip(texts, raws)):
        text, raw = _blank(text, markers.get(k, ())), _blank(raw, markers.get(k, ()))
        bare = PRINCIPAL_SET_RE.sub(lambda m: " " * len(m.group(0)),
                                    text.replace(DIALECT_COL, " "))
        views.append(LineView(_with_dialect_text(text, raw), bare))
    return tuple(views)


def _with_dialect_text(text: str, raw: str) -> str:
    """A line's code with each dialect glyph's columns as written in `raw`."""
    if DIALECT_COL not in text:
        return text
    return "".join(r if t == DIALECT_COL else t for t, r in zip(text, raw))


def _overlay(line: str, piece: str, at: int) -> str:
    """`line` with `piece` written over it from column `at`."""
    return line[:at] + piece + line[at + len(piece):]


def _blank(line: str, spans) -> str:
    """`line` with each (start, end) column span blanked to spaces."""
    for start, end in spans:
        line = line[:start] + " " * (end - start) + line[end:]
    return line


def blank_lines(lines: tuple, markers: dict) -> list:
    """The document's lines with the given column spans blanked ({line index:
    [(start, end)]}: the branch markers read past)."""
    return [_blank(line, markers.get(k, ())) for k, line in enumerate(lines)]


def _documents(doc: Doc):
    """`doc` and every definition body inside it, outermost first."""
    stack = [doc]
    while stack:
        d = stack.pop()
        yield d
        stack.extend(i.body for i in reversed(d.items)
                     if isinstance(i, Definition) and i.body is not None)


def state_lines(doc: Doc) -> frozenset:
    """The line numbers (1-based) a `state` block covers, from its head to the line
    that closes it (to the end of its document when it is never closed)."""
    out: set = set()
    for d in _documents(doc):
        head = None
        for item in d.items:
            if isinstance(item, StateHead):
                head = item.line
            elif isinstance(item, StateEnd):
                out.update(range(item.head + 1, item.line + 2))
                head = None
        if head is not None:
            out.update(range(head + 1, d.end + 1))
    return frozenset(out)


def header_tokens(doc: Doc) -> list:
    """(line number, tokens) of each control-block header that is no statement of
    its own (an owns header is one), in document order."""
    return sorted(((item.line + 1, item.toks) for d in _documents(doc) for item in d.items
                   if isinstance(item, BlockOpen) and item.header is None),
                  key=lambda pair: pair[0])


# ---------------------------------------------------------------------------
# Multiline block-strings — `"""…"""` (folded by the reading; reported here)
# ---------------------------------------------------------------------------

def unterminated_block(at, result: LintResult):
    """SGL170 for an opening `\"\"\"` (line index `at`, or None) never closed."""
    if at is not None:
        result.add(
            "error", at + 1, "SGL170",
            "unterminated block-string: an opening `\"\"\"` has no matching "
            "closing `\"\"\"`. A `\"\"\"…\"\"\"` multiline string must be closed.",
        )


def collapse_block_strings(lines: list, result: LintResult) -> list:
    """The lines with every `\"\"\"…\"\"\"` block folded onto its opening line
    (sigil.core.lex.fold_block_strings; the line count is kept), and SGL170 on
    `result` for a block never closed. A dialect's tests read it as
    lint.collapse_block_strings."""
    folded = fold_block_strings(lines)
    unterminated_block(folded.unterminated, result)
    return folded.lines
