"""[Cut]: clip, pad, ellipsis; never splits a wide char.

Kind: service (a pure function over {Line}).

What it does: `cut(line, width, start=0, ellipsis="", pad=False, fill=" ",
fill_style=None)` keeps the columns `[start, start + width)` of `line`, measured in
cells by grapheme cluster (`spans.clusters`), and returns them as a {Line} in normal
form. Every kept cluster keeps its text and its span's style.

The rules:

1. Clip. A cluster wholly inside the window is kept. A wide cluster straddling the
   LEFT edge (it begins before `start` and ends after it) is replaced by one space
   per column it has inside the window, in its own style, so what follows stays at
   its column. A cluster straddling the RIGHT edge is dropped (the result is then
   narrower than `width`). A glyph is never split.
2. Zero-width clusters ride their base: one is kept exactly when the cluster before
   it is kept whole; at the very start of the line it is kept when `start == 0` and
   `width > 0`.
3. Ellipsis. When `ellipsis` is not empty and the line overflows the window on the
   right (`measure(line) > start + width`), the kept part is clipped to
   `width - w` columns, `w` the ellipsis' width in cells, instead (rules 1 and 2, the same `start`), and
   `ellipsis` follows it directly, styled like the first cluster that was cut off
   (the first not kept whole by that narrower clip). If `w > width`
   the result is `ellipsis` itself clipped to `width` (rule 1). With no overflow the
   ellipsis is not added. Overflow on the left is never marked.
4. Pad. When `pad` is true and the result is narrower than `width`, `fill` (one
   1-column cluster) is appended in `fill_style` until it is exactly `width` columns.
5. `width == 0` gives `Line()` (pad and ellipsis add nothing). A window wholly past
   the line's end gives `Line()`, or only padding.

Inputs: a {Line}; `width`, `start`: int >= 0; `ellipsis`: str (e.g. "…"); `pad`: bool;
  `fill`: str of one cluster 1 column wide; `fill_style`: an opaque style.
Outputs: {Line} in normal form, at most `width` columns wide.
Errors: `TypeError` when `line` is not a `Line` or `ellipsis`/`fill` is not a `str`;
  `ValueError` when `width < 0`, `start < 0`, or `fill` is not exactly one cluster of
  width 1.
Effects: none.

Usage:
    from cure.core.text.spans import Line
    from cure.core.text.cut import cut
    cut(Line.of("ab中文"), 3)                   # Line.of("ab")      (中 would straddle)
    cut(Line.of("ab中文"), 3, pad=True)         # Line.of("ab ")
    cut(Line.of("abcdef"), 4, ellipsis="…")     # Line.of("abc…")
    cut(Line.of("ab中文"), 3, start=3)          # Line.of(" 文")     (中's right half → blank)
"""

from . import graphemes, spans
from .spans import Cell, Line, Span
from .width import cells


def cut(line: Line, width: int, *, start: int = 0, ellipsis: str = "", pad: bool = False,
        fill: str = " ", fill_style: object = None) -> Line:
    """The columns `[start, start + width)` of `line`, by the rules above."""
    if not isinstance(line, Line):
        raise TypeError(f"expected a Line, got {type(line).__name__}")
    if not isinstance(ellipsis, str):
        raise TypeError(f"ellipsis must be a str, got {type(ellipsis).__name__}")
    _check_fill(fill)
    if width < 0 or start < 0:
        raise ValueError(f"width and start must be >= 0, got {width}, {start}")
    if width == 0:
        return Line()
    cs = spans.clusters(line)
    total = sum(c.width for c in cs)
    if ellipsis and total > start + width:
        kept = _ellipsized(cs, start, width, ellipsis)
    else:
        kept = _clip(cs, start, width)
    if pad:
        short = width - sum(span_width for _, span_width in kept)
        kept += [(Span(fill, fill_style), 1)] * max(0, short)
    return Line.of(*(span for span, _ in kept))


def _check_fill(fill: object) -> None:
    if not isinstance(fill, str):
        raise TypeError(f"fill must be a str, got {type(fill).__name__}")
    if len(graphemes.cluster(fill)) != 1 or cells(fill) != 1:
        raise ValueError(f"fill must be one cluster 1 column wide, got {fill!r}")


def _clip(cs: tuple[Cell, ...], start: int, width: int) -> list[tuple[Span, int]]:
    """Rules 1 and 2: the kept pieces of clusters `cs`, each (span, columns)."""
    end = start + width
    out, col, whole = [], 0, start == 0 and width > 0
    for c in cs:
        right = col + c.width
        if c.width == 0:
            if whole:
                out.append((Span(c.glyph, c.style), 0))
        elif start <= col and right <= end:
            out.append((Span(c.glyph, c.style), c.width))
            whole = True
        else:
            if col < start < right:
                inside = min(right, end) - start
                out.append((Span(" " * inside, c.style), inside))
            whole = False
        col = right
    return out


def _ellipsized(cs: tuple[Cell, ...], start: int, width: int,
                ellipsis: str) -> list[tuple[Span, int]]:
    """Rule 3: the line clipped narrower, then `ellipsis` in the style of the first
    cluster cut off."""
    mark = spans.clusters(Line.of(ellipsis))
    w = sum(c.width for c in mark)
    narrow = max(0, width - w)
    style = _first_cut_style(cs, start + narrow)
    if w > width:
        return _clip(tuple(Cell(c.glyph, c.width, style) for c in mark), 0, width)
    return _clip(cs, start, narrow) + [(Span(ellipsis, style), w)]


def _first_cut_style(cs: tuple[Cell, ...], edge: int) -> object:
    col = 0
    for c in cs:
        col += c.width
        if col > edge:
            return c.style
    return None
