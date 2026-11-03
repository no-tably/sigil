"""[Spans]: styled text: Span(text, style), Line, Text, measured in cells.

Kind: service (data classes and pure functions).

What it does: holds the authoring format every Text op takes and returns, rows of
`(text, style)` runs: a {Span} is a run of text with one style, a {Line} a row of
spans, a {Text} a sequence of lines. It measures a line in cells and walks it by
grapheme cluster (`clusters`), which [Wrap], [Cut] and [Align] build on.

Styles are opaque. Text never imports Style and never looks inside a style: a style
is any value (`None` for unstyled), passed through unchanged and compared only with
`==` (two adjacent spans merge when their styles are `==`). [Ansi] supplies its own
style values (`AnsiStyle`); every other style comes from the caller.

Data (frozen dataclasses; the constructors store what they are given and do not
convert or check it, so pass tuples; `Line.of` and `Text.of` convert):
- `Span(text: str, style: object = None)`.
- `Line(spans: tuple[Span, ...] = ())`.
- `Text(lines: tuple[Line, ...] = ())`.
- `Cell(glyph: str, width: int, style: object = None)`: one grapheme cluster as it
  occupies columns. In `clusters` the glyph is the cluster's exact text; in
  `cure.core.text.put` / `cell` it is made safe to draw, and a tail cell (the second
  column of a wide glyph) is `Cell("", 0, style)`.

Normal form (`merge`): no span with empty text, and no two adjacent spans with `==`
styles (they are joined, keeping the first one's style object). `Line.of`, and the
results of [Wrap], [Cut], [Align] and [Ansi], are in normal form.

Measuring: the clusters of a line are those of its plain text taken whole
(`graphemes.cluster(line.plain)`), so a cluster may cross a span boundary (a
combining mark at the start of a span joins the last character of the span before
it); such a cluster takes the style of the span holding its first code point.
`measure(line) == sum(c.width for c in clusters(line)) == cure.core.text.width(line.plain)`.

Text's shared helper (the package's F1 toolkit, hosted here; private to the package,
never re-exported on Text's face, and named so by this docstring, Q11):
`_ascii_cells(line) -> tuple[Cell, ...] | None`, the printable-ASCII fast path that
`clusters` takes first and that the package's `put` takes too (`cure/core/text/
__init__.py`). For a {Line} whose `spans` is a `tuple`: `None` unless every span's
text is exactly a `str` (not a subclass) of printable ASCII (U+0020..U+007E); then
`clusters(line)`, one `Cell(ch, 1, style)` per code point, `style` its span's (the
very object), a cell made once per distinct code point of a span and shared. It
makes no check of its own (the caller's `_check` / `_as_line` come first, so an
error is the general path's) and has no effect. It is bound by the package's law
fast_equal: whatever it returns is what the general path gives.

Inputs: `measure(line)`, `clusters(line)`, `merge(line)`: a {Line}.
Outputs: `measure`: {Cells}, an int >= 0. `clusters`: a tuple of `Cell`. `merge`: a {Line}.
Errors: `TypeError` when a {Line} is expected and something else is given, or when a
  part given to `Line.of` is not a `str`, `Span` or 2-tuple `(str, style)`, or the text
  given to `Text.of` is not a `str`.
Effects: none.

Usage:
    from cure.core.text.spans import Span, Line, Text, measure
    bold = ("bold",)                              # any value serves as a style
    line = Line.of("name ", ("中文", bold))        # Line((Span("name "), Span("中文", bold)))
    measure(line)                                 # 9
    line.runs                                     # (("name ", None), ("中文", ("bold",)))
    Text.of("one\\ntwo").lines                     # (Line.of("one"), Line.of("two"))
"""

from dataclasses import dataclass

from . import graphemes, width


@dataclass(frozen=True)
class Span:
    """A run of `text` drawn in one `style` (opaque; None for unstyled)."""

    text: str
    style: object = None


@dataclass(frozen=True)
class Line:
    """A row of spans; it holds no newline by convention ([Wrap] and [Ansi] split at
    them; a stray one is a control cluster of width 1)."""

    spans: tuple[Span, ...] = ()

    @classmethod
    def of(cls, *parts) -> "Line":
        """A line in normal form from parts, each a `str` (style None), a `Span`,
        or a 2-tuple `(text, style)`. `Line.of()` is `Line()`. TypeError otherwise."""
        return merge(cls(tuple(_span(part) for part in parts)))

    @property
    def plain(self) -> str:
        """The spans' texts joined, styles dropped."""
        return "".join(span.text for span in self.spans)

    @property
    def width(self) -> int:
        """`measure(self)`."""
        return measure(self)

    @property
    def runs(self) -> tuple[tuple[str, object], ...]:
        """`(text, style)` per span, in order, as stored (not merged)."""
        return tuple((span.text, span.style) for span in self.spans)


@dataclass(frozen=True)
class Text:
    """A sequence of lines (paragraphs, for [Wrap])."""

    lines: tuple[Line, ...] = ()

    @classmethod
    def of(cls, text: str, style: object = None) -> "Text":
        """One `Line` per line of `text`, split at "\\n" ("\\r\\n" counts as one
        "\\n"), each `Line.of((piece, style))`, as `str.split` does: `Text.of("")` is
        `Text((Line(),))` and `Text.of("a\\n")` is `Text((Line.of("a"), Line()))`."""
        if not isinstance(text, str):
            raise TypeError(f"expected a str, got {type(text).__name__}")
        pieces = text.replace("\r\n", "\n").split("\n")
        return cls(tuple(Line.of((piece, style)) for piece in pieces))

    @property
    def plain(self) -> str:
        """The lines' plain texts joined with "\\n"."""
        return "\n".join(line.plain for line in self.lines)


@dataclass(frozen=True)
class Cell:
    """One grapheme cluster as it occupies columns: its `glyph`, its `width` (0, 1
    or 2) and its `style`."""

    glyph: str
    width: int
    style: object = None


def measure(line: Line) -> int:
    """The columns `line` takes: the sum of its clusters' widths (see the module)."""
    _check(line)
    plain = line.plain
    if plain.isascii() and plain.isprintable():
        return len(plain)             # Speed: printable ASCII, one column per code point
    return sum(width.cells(c) for c in graphemes.cluster(plain))


def clusters(line: Line) -> tuple[Cell, ...]:
    """One `Cell(cluster text, width.cells(cluster), style)` per grapheme cluster of
    `line.plain`, in order, the style that of the span holding the cluster's first
    code point. Zero-width clusters are included (width 0); glyphs are the exact
    text, controls included, so `"".join(c.glyph for c in clusters(line)) == line.plain`."""
    _check(line)
    parts = line.spans
    plain = found = None
    if parts.__class__ is tuple:
        fast = _ascii_cells(line)
        if fast is not None:
            return fast               # Speed: printable ASCII, one cell per code point
        texts = [span.text for span in parts]
        if all(text.__class__ is str for text in texts):
            plain = "".join(texts)
            found = graphemes.cluster(plain)
            if len(found) == len(plain):
                # Speed: every cluster is one code point, so a span's cells are one per
                # code point, made once per distinct code point (cells are immutable).
                out: list = []
                for span, text in zip(parts, texts):
                    if text:
                        style = span.style
                        made = {ch: Cell(ch, width.cells(ch), style) for ch in set(text)}
                        out.extend(map(made.__getitem__, text))
                return tuple(out)
    owners = [span.style for span in line.spans for _ in span.text]
    if found is None:
        plain = line.plain
        found = graphemes.cluster(plain)
    out, i = [], 0
    made: dict = {}                  # (cluster, id(style)) -> its cell, within this call
    for text in found:
        style = owners[i]
        cell = made.get((text, id(style)))
        if cell is None:
            cell = made[text, id(style)] = Cell(text, width.cells(text), style)
        out.append(cell)
        i += len(text)
    return tuple(out)


def merge(line: Line) -> Line:
    """`line` in normal form: empty spans dropped, adjacent `==`-styled spans joined."""
    _check(line)
    out: list[Span] = []
    for span in line.spans:
        if not span.text:
            continue
        if out and out[-1].style == span.style:
            out[-1] = Span(out[-1].text + span.text, out[-1].style)
        else:
            out.append(span)
    return Line(tuple(out))


def _ascii_cells(line: Line) -> "tuple[Cell, ...] | None":
    """Speed (the package's printable-ASCII fast path), for a line whose spans are a
    tuple: `clusters(line)` when every span's text is exactly a `str` of printable ASCII (each code point a cluster of
    width 1 in its span's style, the very object), else None. A cell is made once per
    distinct code point of a span and shared (cells are immutable)."""
    out: list[Cell] = []
    for span in line.spans:
        text = span.text
        if text.__class__ is not str or not (text.isascii() and text.isprintable()):
            return None
        if text:
            style = span.style
            made = {ch: Cell(ch, 1, style) for ch in set(text)}
            out.extend(map(made.__getitem__, text))
    return tuple(out)


def _check(line: object) -> None:
    if not isinstance(line, Line):
        raise TypeError(f"expected a Line, got {type(line).__name__}")


def _span(part: object) -> Span:
    if isinstance(part, str):
        return Span(part)
    if isinstance(part, Span):
        return part
    if isinstance(part, tuple) and len(part) == 2 and isinstance(part[0], str):
        return Span(part[0], part[1])
    raise TypeError(f"expected a str, Span or (str, style), got {part!r}")
