"""[Align]: left, centre, right, justify.

Kind: service (a pure function over {Line}).

What it does: `align(line, width, how="left", fill=" ", fill_style=None)` places
`line` in a field `width` columns wide (measured in cells, `spans.measure`) and
returns a {Line} in normal form. It never cuts: a line already `width` columns wide
or wider comes back unchanged (in normal form); cut it first with [Cut] if needed.

With `w = measure(line)` and `extra = width - w > 0`:

- "left": `line`, then `extra` columns of `fill`.
- "right": `extra` columns of `fill`, then `line`.
- "centre" (also spelt "center"): `extra // 2` columns of `fill`, `line`, then the
  other `extra - extra // 2` (the odd column goes to the right).
- "justify": the extra columns are shared among the line's gaps, a gap being a
  maximal run of U+0020 SPACE with a non-space cluster on each side (leading and
  trailing spaces are not gaps and stay as they are). With `g` gaps each gap gets
  `extra // g` more spaces and the first `extra % g` gaps (from the left) one more;
  the added spaces take the style of the gap's first space. A line with no gap is
  aligned "left" (padded with `fill`).

Padding is `fill` (one cluster, 1 column wide) in `fill_style`; justify's widened
gaps use U+0020, not `fill`.

Inputs: a {Line}; `width`: int >= 0; `how`: one of "left", "centre", "center",
  "right", "justify"; `fill`: str; `fill_style`: an opaque style.
Outputs: {Line} in normal form, exactly `max(width, measure(line))` columns wide.
Errors: `TypeError` when `line` is not a `Line` or `fill` is not a `str`;
  `ValueError` when `width < 0`, `how` is not one of the five, or `fill` is not
  exactly one cluster of width 1.
Effects: none.

Usage:
    from cure.core.text.spans import Line
    from cure.core.text.align import align
    align(Line.of("ab"), 5, "right")             # Line.of("   ab")
    align(Line.of("ab"), 5, "centre")            # Line.of(" ab  ")
    align(Line.of("a b c"), 8, "justify")        # Line.of("a   b  c")
    align(Line.of("中"), 4, fill=".")            # Line.of("中..")
"""

from . import graphemes, spans
from .spans import Line, Span
from .width import cells

HOWS = ("left", "centre", "center", "right", "justify")


def align(line: Line, width: int, how: str = "left", *, fill: str = " ",
          fill_style: object = None) -> Line:
    """`line` placed in `width` columns, by the rules above."""
    if not isinstance(line, Line):
        raise TypeError(f"expected a Line, got {type(line).__name__}")
    _check_fill(fill)
    if width < 0:
        raise ValueError(f"width must be >= 0, got {width}")
    if how not in HOWS:
        raise ValueError(f"how must be one of {HOWS}, got {how!r}")
    extra = width - spans.measure(line)
    if extra <= 0:
        return spans.merge(line)
    if how == "justify":
        gaps = _gaps(line)
        if gaps:
            return _widen(line, gaps, extra)
        how = "left"
    pad = Span(fill * extra, fill_style)
    if how == "left":
        return Line.of(*line.spans, pad)
    if how == "right":
        return Line.of(pad, *line.spans)
    half = extra // 2
    return Line.of(Span(fill * half, fill_style), *line.spans,
                   Span(fill * (extra - half), fill_style))


def _check_fill(fill: object) -> None:
    if not isinstance(fill, str):
        raise TypeError(f"fill must be a str, got {type(fill).__name__}")
    if len(graphemes.cluster(fill)) != 1 or cells(fill) != 1:
        raise ValueError(f"fill must be one cluster 1 column wide, got {fill!r}")


def _gaps(line: Line) -> list[tuple[int, object]]:
    """(offset of the gap's first space in `line.plain`, its style), left to right."""
    cs = spans.clusters(line)
    gaps, offset, run = [], 0, None
    seen_ink = False
    for c in cs:
        if c.glyph == " ":
            if run is None and seen_ink:
                run = (offset, c.style)
        else:
            if run is not None:
                gaps.append(run)
            run = None
            seen_ink = True
        offset += len(c.glyph)
    return gaps


def _widen(line: Line, gaps: list[tuple[int, object]], extra: int) -> Line:
    share, rest = divmod(extra, len(gaps))
    inserts = {offset + 1: Span(" " * (share + (i < rest)), style)
               for i, (offset, style) in enumerate(gaps)}
    parts, offset = [], 0
    for span in line.spans:
        start = offset
        for cut in sorted(k for k in inserts if start < k <= start + len(span.text)):
            parts.append(Span(span.text[offset - start:cut - start], span.style))
            parts.append(inserts[cut])
            offset = cut
        parts.append(Span(span.text[offset - start:], span.style))
        offset = start + len(span.text)
    return Line.of(*parts)
