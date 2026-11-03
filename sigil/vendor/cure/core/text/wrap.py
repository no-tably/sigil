"""[Wrap]: words, CJK by cell, hyphens, indent, glue.

Kind: service (a pure function from {Text} to {Lines}).

What it does: `wrap(text, width, first="", indent="", hyphens=True, long_words=True,
glue=())` fills each paragraph of `text` into lines at most `width` columns wide,
measured in cells by grapheme cluster, greedily (each line takes as much as fits;
no look-ahead). Spans keep their styles; a word may cross spans.

Paragraphs. `text` is a {Text}, a {Line} or a `str` (`Text.of(text)`). Each line of a
Text is a paragraph, and a "\\n" or "\\r\\n" cluster inside a line also ends one (a hard
break, never kept in the output). Each paragraph is wrapped on its own; an empty or
all-whitespace paragraph gives one empty `Line()`, so blank lines are kept;
`Text()` gives `()`.

Break opportunities, the only places a line may end:

1. Whitespace: a run of U+0020, "\\t", "\\v", "\\f" or a lone "\\r". The run is dropped at
   a break (it ends neither line). Whitespace kept inside a line becomes one U+0020
   per character, in its span's style. Whitespace at the end of a paragraph is
   dropped; whitespace at its start is kept on the first line (as textwrap does).
   No-break spaces (U+00A0, U+2007, U+202F) are not whitespace and never break.
2. Hyphens (when `hyphens` is true): right after "-" (U+002D) or U+2010 HYPHEN whose
   previous cluster is not whitespace and not a hyphen, and whose next cluster is a
   letter or digit (`str.isalnum` of its first code point). The hyphen stays at the
   end of the first line.
3. CJK by cell: before and after every wide (2-column) cluster, so CJK text with no
   spaces breaks between any two of its characters (no kinsoku: closing punctuation
   may start a line).
4. Right after a cluster that ends in U+200B ZERO WIDTH SPACE (which stays, 0 wide).
5. Glue. Each string in `glue` (e.g. " · ") binds to what follows it: in the
   paragraph's plain text, occurrences are found left to right without overlap, and
   inside an occurrence or directly after it there is no break opportunity, except
   at the occurrence's leading whitespace run, which is one (rule 1). So
   "a · b" with `glue=(" · ",)` breaks only as "a" / "· b".

Indents. `first` starts the first line of each paragraph and `indent` every
continuation line; each is a `str` (style None) or a {Line}, and its width counts
against `width`.

Long words. A word (a stretch with no break opportunity) that does not fit the rest
of the current line but fits an empty one moves to the next line. One wider than an
empty line: when `long_words` is true it is cut by cells at cluster boundaries,
starting on the current line (filling its room, after the separating space) and
continuing on as many lines as it needs; when false it goes alone on a line of its
own, which is then wider than `width`. A single cluster wider than an empty line's
room (a wide character at width 1 with no indent) goes alone on its own line either
way. These are the only lines wider than `width`.

Inputs: a {Text}, {Line} or `str`; `width`: int >= 1; `first`, `indent`: `str` or {Line};
  `hyphens`, `long_words`: bool; `glue`: an iterable of non-empty `str`.
Outputs: {Lines}: a tuple of {Line}, each in normal form, with no trailing whitespace.
Errors: `TypeError` when `text`, `first`, `indent` or a glue item has the wrong type;
  `ValueError` when `width < 1`, when `first` or `indent` is `width` columns wide or
  wider, or when a glue item is empty.
Effects: none.

Usage:
    from cure.core.text.wrap import wrap
    wrap("the quick brown fox", 10)             # (Line.of("the quick"), Line.of("brown fox"))
    wrap("中文字符串", 4)                         # (Line.of("中文"), Line.of("字符"), Line.of("串"))
    wrap("well-known words", 6)                 # (Line.of("well-"), Line.of("known"), Line.of("words"))
    wrap("one two three", 8, indent="  ")       # (Line.of("one two"), Line.of("  three"))
    wrap("a · b · c", 5, glue=(" · ",))         # (Line.of("a · b"), Line.of("· c"))
"""

from collections.abc import Iterable

from . import spans
from .spans import Cell, Line, Span, Text


def wrap(text: "Text | Line | str", width: int, *, first: "str | Line" = "",
         indent: "str | Line" = "", hyphens: bool = True, long_words: bool = True,
         glue: Iterable[str] = ()) -> tuple[Line, ...]:
    """The lines of `text` filled to `width` columns, by the rules above."""
    paragraphs = _text(text).lines
    if width < 1:
        raise ValueError(f"width must be >= 1, got {width}")
    head = _indent(first, width, "first")
    rest = _indent(indent, width, "indent")
    glues = _glues(glue)
    out: list[Line] = []
    for line in paragraphs:
        for para in _paragraphs(spans.clusters(line)):
            whole = _whole(para, width, head)
            if whole is not None:
                out.append(whole)
                continue
            words = _words(para, hyphens, glues)
            if not words:
                out.append(Line())
            else:
                out.extend(_fill(words, width, head, rest, long_words))
    return tuple(out)


_WHITESPACE = (" ", "\t", "\v", "\f", "\r")
_HYPHENS = ("-", "\u2010")
_ZWSP = "\u200b"


def _text(text: object) -> Text:
    if isinstance(text, Text):
        return text
    if isinstance(text, Line):
        return Text((text,))
    if isinstance(text, str):
        return Text.of(text)
    raise TypeError(f"expected a Text, Line or str, got {type(text).__name__}")


def _indent(value: object, width: int, name: str) -> tuple[Cell, ...]:
    if value.__class__ is str and not value:
        return ()                     # Speed: no indent (0 columns, below any width >= 1)
    if isinstance(value, str):
        value = Line.of(value)
    elif not isinstance(value, Line):
        raise TypeError(f"{name} must be a str or Line, got {type(value).__name__}")
    if spans.measure(value) >= width:
        raise ValueError(f"{name} must be narrower than width {width}")
    return spans.clusters(value)


def _glues(glue: Iterable[str]) -> tuple[str, ...]:
    items = tuple(glue)
    for item in items:
        if not isinstance(item, str):
            raise TypeError(f"a glue item must be a str, got {type(item).__name__}")
        if not item:
            raise ValueError("a glue item must not be empty")
    return items


def _paragraphs(cs: tuple[Cell, ...]) -> list[list[Cell]]:
    """`cs` split at its "\\n" and "\\r\\n" clusters (hard breaks, dropped)."""
    out: list[list[Cell]] = [[]]
    for c in cs:
        if c.glyph in ("\n", "\r\n"):
            out.append([])
        else:
            out[-1].append(c)
    return out


def _space(c: Cell) -> bool:
    return c.glyph in _WHITESPACE


def _whole(cs: list[Cell], width: int, head: tuple[Cell, ...]) -> "Line | None":
    """Speed: the paragraph's one line when it fits whole after `head` (or `Line()` when
    it is empty or all whitespace), else None. Greedy filling then never breaks, so the
    line is `head`, then every cluster with whitespace as U+0020 in its style, its
    trailing whitespace dropped: what `_words` and `_fill` give."""
    end = len(cs)
    while end and _space(cs[end - 1]):
        end -= 1
    if not end:
        return Line()
    body = cs[:end]
    if sum(c.width for c in head) + sum(c.width for c in body) > width:
        return None
    return _finish([*head, *(Cell(" ", 1, c.style) if _space(c) else c for c in body)])


def _words(cs: list[Cell], hyphens: bool, glues: tuple[str, ...]) -> list[tuple[list[Cell], list[Cell]]]:
    """The paragraph as (separator, word) pairs: the separator the breakable
    whitespace run before the word as spaces (empty at a zero-width break), the word
    the clusters up to the next break opportunity. Trailing whitespace is dropped."""
    while cs and _space(cs[-1]):
        cs = cs[:-1]
    if not cs:
        return []
    offsets = _offsets(cs)
    bound = _glued(cs, glues)
    words: list[tuple[list[Cell], list[Cell]]] = []
    sep: list[Cell] = []
    word: list[Cell] = []
    i = 0
    while i < len(cs):
        if _space(cs[i]):
            j = i
            while j < len(cs) and _space(cs[j]):
                j += 1
            run = [Cell(" ", 1, c.style) for c in cs[i:j]]
            if bound(offsets[i]):
                word.extend(run)
            else:
                if word:
                    words.append((sep, word))
                sep, word = run, []
            i = j
            continue
        if word and not bound(offsets[i]) and _opportunity(cs, i, hyphens):
            words.append((sep, word))
            sep, word = [], []
        word.append(cs[i])
        i += 1
    words.append((sep, word))
    return words


def _offsets(cs: list[Cell]) -> list[int]:
    out, offset = [], 0
    for c in cs:
        out.append(offset)
        offset += len(c.glyph)
    return out


def _glued(cs: list[Cell], glues: tuple[str, ...]):
    """A test: True when a break at that plain-text offset is inside or right after a
    glue occurrence, so not a break opportunity (rule 5)."""
    plain = "".join(c.glyph for c in cs)
    found: list[tuple[int, int]] = []
    p = 0
    while glues and p < len(plain):
        item = next((g for g in glues if plain.startswith(g, p)), None)
        if item is None:
            p += 1
        else:
            found.append((p, p + len(item)))
            p += len(item)
    return lambda offset: any(lo < offset <= hi for lo, hi in found)


def _opportunity(cs: list[Cell], i: int, hyphens: bool) -> bool:
    """A zero-width break opportunity between cs[i - 1] and cs[i] (rules 2 to 4)."""
    prev, cur = cs[i - 1], cs[i]
    if prev.width == 2 or cur.width == 2:
        return True
    if prev.glyph.endswith(_ZWSP):
        return True
    return (hyphens and prev.glyph in _HYPHENS and i >= 2
            and not _space(cs[i - 2]) and cs[i - 2].glyph not in _HYPHENS
            and cur.glyph[0].isalnum())


def _fill(words, width: int, head: tuple[Cell, ...], rest: tuple[Cell, ...],
          long_words: bool) -> list[Line]:
    """Greedy filling of one paragraph's (separator, word) pairs."""
    lines: list[Line] = []
    rest_width = sum(c.width for c in rest)
    line, col, content = list(head), sum(c.width for c in head), False

    def newline():
        nonlocal line, col, content
        lines.append(_finish(line))
        line, col, content = list(rest), rest_width, False

    for sep, word in words:
        sw = len(sep)
        ww = sum(c.width for c in word)
        if not content and col + sw + ww > width:
            sep, sw = [], 0
        if col + sw + ww <= width:
            line += sep + word
            col += sw + ww
            content = True
            continue
        if content and rest_width + ww <= width:
            newline()
            line += word
            col += ww
            content = True
            continue
        if not long_words:
            if content:
                newline()
            line += word
            col += ww
            content = True
            continue
        if content and col + sw + word[0].width > width:
            newline()
            sep, sw = [], 0
        line += sep
        col += sw
        for c in word:
            if content and col + c.width > width:
                newline()
            line.append(c)
            col += c.width
            content = True
    lines.append(_finish(line))
    return lines


def _finish(cs: list[Cell]) -> Line:
    while cs and _space(cs[-1]):
        cs = cs[:-1]
    # `Line.of(*((c.glyph, c.style) for c in cs))` in one pass: a run of cells whose
    # styles are `==` to the run's first is one span in that first style (merge's rule).
    out: list[Span] = []
    run: list[str] = []
    style = None
    for c in cs:
        if not c.glyph:
            continue
        if run and style == c.style:
            run.append(c.glyph)
        else:
            if run:
                out.append(Span("".join(run), style))
            run, style = [c.glyph], c.style
    if run:
        out.append(Span("".join(run), style))
    return Line(tuple(out))
