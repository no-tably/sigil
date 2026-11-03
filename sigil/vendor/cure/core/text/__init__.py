"""[Text]: cell widths, graphemes, styled spans, wrap.

Kind: system (the expansion of [Text] in Core); pure. Depends on nothing: no module of
this package imports another cure package, or `unicodedata` (widths are the release's
|WideTable|, see `widetable`).

Everything is measured in terminal cells, never in code points, by grapheme cluster:
[Graphemes] cuts text into clusters, [Width] gives each 0, 1 or 2 columns from
|WideTable|, [Spans] holds styled text (`Span`, `Line`, `Text`; styles are opaque
values Text never looks inside), and [Wrap], [Cut], [Align] and [Ansi] work on it.

The boundary (the ops other systems call), defined here:

- `width(text) -> int` ({Char} => {Cells}, for [Buffer]): the columns `text` takes,
  `sum(width.cells(c) for c in cluster(text))`; for one cluster ({Char}) that cluster's
  width. `width("") == 0`. `TypeError` when `text` is not a `str`.
- `cell(char, style=None) -> Cell` ({Char} => {Cell}, for Buffer's [Cells]): one
  grapheme cluster as a cell, `Cell(glyph, width, style)`. A control cluster (see
  [Width]: C0, DEL, C1, a surrogate, CR LF, a tab) becomes `Cell("\\ufffd", 1, style)`,
  so no raw control ever reaches a terminal; any other cluster is
  `Cell(char, width(char), style)`, width 0 for a base-less cluster such as a lone
  combining mark (Buffer lets it ride its base). `TypeError` when `char` is not a
  `str`; `ValueError` when it is not exactly one cluster (empty, or two or more).
- `put(spans) -> tuple[Cell, ...]` ({Spans} => {Cells}, for Canvas's [Labels]): a line
  laid out as one cell per column. `spans` is a {Line} or an iterable of `Span`. Its
  clusters (`spans.clusters`, so a cluster may cross a span boundary and takes the
  style of its first code point's span) become, in order: a control cluster,
  `Cell("\\ufffd", 1, style)`; a 1-column cluster, `Cell(text, 1, style)`; a 2-column
  cluster, `Cell(text, 2, style)` then its tail `Cell("", 0, style)`; a 0-column
  cluster is appended to the glyph of the last non-tail cell before it (it rides its
  base, keeping the base's style), or dropped when there is none. So
  `len(put(line)) == spans.measure(line)`, a width-0 cell is always a tail
  right after a width-2 cell, and `"".join(c.glyph for c in put(line))` is the line's
  plain text when it holds no control and starts with no base-less cluster.
  `TypeError` when `spans` is neither (a `str` included).
- `measure(keys) -> int` ({Keys} => {Zone}, for Readouts' [PropertyList]): the key zone
  of a key:value list, `1 + max(width of each key)`, `1` when there are no keys
  (zone = 1 + the widest key; Rules carried over). Each key is a `str` or a {Line};
  `TypeError` otherwise. (Not `spans.measure`, which measures one line.)

Speed (F1): the printable-ASCII fast path. Printable ASCII is U+0020..U+007E: not DEL
(U+007F), and not a tab, CR or LF (controls, rule 2 of [Width]). Its answers need
neither |WideTable| nor the cluster rules, so Text may give them directly. For a `str`
`s` (exactly `str`, not a subclass) of printable ASCII only, and any style `st`:
`cluster(s) == tuple(s)`; `width.cells(ch) == width(ch) == 1` and `width(s) ==
len(s)`; `cell(ch, st) == Cell(ch, 1, st)`; and for a {Line} whose `plain` is such a
`s`, `put(line)`, like `spans.clusters(line)`, is one `Cell(ch, 1, style)` per code
point, `style` its span's, and `spans.measure(line) == len(s)`. The edge of the path:
an ASCII code point is a cluster of its own only when the code point after it is not an
extender and the one before it is not a ZWJ that follows a base. `"e\\u0301"` is one
cluster of width 1, `"1\\ufe0f\\u20e3"` (keycap) one of width 2 (VS16), `"a\\U0001F3FB"`
one of width 2, `"a\\u200db"` one of width 2, while `"a\\r\\nb"` is `a`, CR LF, `b`. So
over mixed text the path may take an ASCII run's clusters only up to (not including)
its last code point before a non-ASCII one; that code point's cluster is decided by the
general rules, which see it as `prev`.

Where the path lives: `put` takes the line path through [Spans]' `_ascii_cells`,
Text's shared helper (the package's F1 toolkit, declared in `spans.py`'s docstring:
private to the package, never on this face), the same path `spans.clusters` takes
first; `width` and `cell` test printable ASCII here.

Law fast_equal: the fast path changes no answer. For every function it touches
(`width`, `cell`, `put`, `measure` here; `graphemes.cluster` / `extender`;
`width.cells` / `point` / `control`; `spans.measure` / `clusters`, `Line.width`; and
through them `wrap`, `cut`, `align` and `parse`) and every input, the result is the
general path's (the rules of [Graphemes] and [Width] applied with no shortcut, as of
commit 26d0853): equal by `==`, of the same types throughout (tuples stay tuples,
widths `int`, cells `Cell`, lines `Line`), every style the very object (`is`) the
general path puts there (Text passes styles through). An error is the same class with
the same message (`str(e)`) for the same input: the type checks (`TypeError` for a
non-`str`, a non-{Line}) and `cell`'s one-cluster check stay in front of any shortcut.
A proof holds the general path as a reference model (a copy of those functions at
26d0853) and compares over random strings mixing printable ASCII; wide (`"中"`,
`"Ａ"`, `"👍"`); marks and joiners (U+0301, ZWJ, VS16, U+20E3, skin-tone modifiers,
regional indicators); controls (C0, ESC, DEL, C1, `"\\t"`, `"\\r\\n"`); invalid (a lone
surrogate U+D800); and the edge pairs above (each kind straight after an ASCII code
point), styled as random spans whose boundaries fall anywhere, a cluster's included.
The closed forms above are laws too, and hold before F1 as after. The budget this path
serves is Buffer's (B3, `put` of 40 rows of 116 ASCII cells; see [Buffer]).

Re-exported for consumers: `Span`, `Line`, `Text`, `Cell`, `merge` (spans);
`cluster` (graphemes); `wrap`; `cut`; `align`; `parse`, `AnsiStyle` (ansi);
`WideTable`, `TABLE` (widetable).

Note: the functions `width`, `wrap`, `cut` and `align` shadow the submodules of the
same names as package attributes (`import cure.core.text.wrap as m` binds the
function). Reach a submodule's own names with `from cure.core.text.width import
cells, point` (a from-import of the dotted module path), never through the attribute.

Effects: none.

Usage:
    from cure.core.text import width, cell, put, measure, Line, Span
    width("中a")                         # 3
    cell("中")                           # Cell("中", 2, None)
    cell("\\x1b")                         # Cell("\\ufffd", 1, None)
    put(Line.of(("中", "s"), "e\\u0301"))  # (Cell("中", 2, "s"), Cell("", 0, "s"), Cell("e\\u0301", 1, None))
    measure(["name", "中文"])            # 5
"""

from collections.abc import Iterable
from functools import lru_cache
from operator import attrgetter

from .align import align
from .ansi import AnsiStyle, parse
from .cut import cut
from .graphemes import cluster
from .spans import Cell, Line, Span, Text, merge
from .widetable import TABLE, WideTable
from .width import cells as _cells, control as _control
from .wrap import wrap
from . import spans as _spans

_REPLACEMENT = "\ufffd"
_width_of = attrgetter("width")


def width(text: str) -> int:
    """The columns `text` takes: the sum of its clusters' widths (see the package)."""
    if not isinstance(text, str):
        raise TypeError(f"expected a str, got {type(text).__name__}")
    if _ascii(text):
        return len(text)              # Speed: printable ASCII, one column per code point
    return sum(_cells(c) for c in cluster(text))


def cell(char: str, style: object = None) -> Cell:
    """One grapheme cluster as a `Cell` (see the package)."""
    if not isinstance(char, str):
        raise TypeError(f"expected a str, got {type(char).__name__}")
    if char.__class__ is str and len(char) == 1 and " " <= char <= "~":
        return Cell(char, 1, style)   # Speed: one printable-ASCII code point
    if len(cluster(char)) != 1:
        raise ValueError(f"expected exactly one grapheme cluster, got {char!r}")
    if _control(char[0]):
        return Cell(_REPLACEMENT, 1, style)
    return Cell(char, _cells(char), style)


def put(spans: "Line | Iterable[Span]") -> tuple[Cell, ...]:
    """A line as one `Cell` per column, wide glyphs followed by their tails (see the package)."""
    line = _as_line(spans)
    parts = line.spans
    tupled = parts.__class__ is tuple
    if tupled:
        if (len(parts) == 1 and parts[0].__class__ is Span and parts[0].text.__class__ is str
                and len(parts[0].text) == 1):
            return _one(parts[0].text, parts[0].style)   # Speed: one code point, one cluster
        fast = _spans._ascii_cells(line)
        if fast is not None:
            return fast               # Speed: printable ASCII, one cell per code point
    cs = _spans.clusters(line)
    if tupled and set(map(_width_of, cs)) == {1} and line.plain.isprintable():
        # Speed: every cluster narrow and none a control (C0, C1 and DEL are Cc, a
        # surrogate Cs, never printable), so the loop below would keep each as it is.
        return cs
    out: list[Cell] = []
    base = None
    for c in cs:
        g0 = c.glyph[0]
        if not " " <= g0 <= "~" and _control(g0):
            base = len(out)
            out.append(Cell(_REPLACEMENT, 1, c.style))
        elif c.width == 0:
            if base is not None:
                out[base] = Cell(out[base].glyph + c.glyph, out[base].width, out[base].style)
        else:
            base = len(out)
            out.append(c)
            if c.width == 2:
                out.append(Cell("", 0, c.style))
    return tuple(out)


def measure(keys: "Iterable[str | Line]") -> int:
    """The key zone: 1 + the widest key's width in cells, 1 for no keys (see the package)."""
    widest = 0
    for key in keys:
        if isinstance(key, Line):
            widest = max(widest, _spans.measure(key))
        elif isinstance(key, str):
            widest = max(widest, width(key))
        else:
            raise TypeError(f"expected a str or Line key, got {type(key).__name__}")
    return 1 + widest


def _one(char: str, style: object) -> "tuple[Cell, ...]":
    """`put` of a line of one code point `char` (one cluster, so the general path's cells
    directly): printable ASCII and narrow glyphs one cell, a control U+FFFD, a wide glyph
    its head and tail, a zero-width one nothing (it has no base to ride)."""
    if " " <= char <= "~":
        return (Cell(char, 1, style),)
    w = _point_width(char)
    if w < 0:
        return (Cell(_REPLACEMENT, 1, style),)
    if w == 1:
        return (Cell(char, 1, style),)
    if w == 2:
        return (Cell(char, 2, style), Cell("", 0, style))
    return ()


@lru_cache(maxsize=4096)
def _point_width(char: str) -> int:
    """Speed: -1 for a control code point, else its width as a cluster (memoised: the
    table is frozen with the release)."""
    return -1 if _control(char) else _cells(char)


def _ascii(text: str) -> bool:
    """Speed: `text` is exactly a `str` of printable ASCII only (U+0020..U+007E)."""
    return text.__class__ is str and text.isascii() and text.isprintable()


def _as_line(spans: object) -> Line:
    if isinstance(spans, Line):
        return spans
    if isinstance(spans, (str, bytes, Text)) or not isinstance(spans, Iterable):
        raise TypeError(f"expected a Line or an iterable of Span, got {type(spans).__name__}")
    parts = tuple(spans)
    if not all(isinstance(part, Span) for part in parts):
        raise TypeError("expected an iterable of Span")
    return Line(parts)
