"""[Legend]: marker + word entries that wrap between entries.

Kind: service (two frozen dataclasses: the `Legend` node kind and its `Entry`s; see
the Widgets package's protocol).

What it does: says what a drawing's marks mean, `● out  ○ return  ✕ failed`, after
an optional label, wrapping between entries (never inside one) with the continuation
rows indented under the label, as sigil's `wrap_legend` does. The markers are the
app's own vocabulary (the glyphs it drew with), passed in with the roles they were
drawn in, so a legend's colours are its drawing's.

Data (frozen dataclasses; checked on construction):
- `Entry(marker, word, role=None)`: `marker` and `word` styled text (`str` or
  {Line}); span style `None` is `role` for the marker (`text` when `role` is `None`)
  and `muted` for the word.
- `Legend(entries=(), *, label="", id=None, size=None, anchor=None, scope=None,
  surface=False)`: `entries` a tuple of `Entry`; `label` a `str` drawn first in role
  `dim` (`""`: none).

An entry's cells: the marker, one ground cell, the word: `s = width(marker) + 1 +
width(word)`. Between two entries: two ground cells. The prefix `P`: `label` and one
ground cell when there is a label, else `0`.

The flow is KeyHints' `flow` (`keyhints.py`), called by Legend (the drawn `[Legend] ->
[KeyHints] : flow({Entries}) => {Rows}`) and painted through the family toolkit's
`_paint_flow` (`paragraph.py`): the prefix on the first row, every row's entries from `R.x + P`, an entry on the current row when it is the row's first and
fits `R.w - P` or fits after its separator, else on the next row; the last row ends
`" …"` (`ctx.glyph("ellipsis")`, role `muted`) when entries remain past `R.h` rows.
One difference: an entry alone wider than `R.w - P` is not cut but breaks between
the words of its `word` (Text's `wrap` at `R.w - P - width(marker) - 1`, its first
row after the marker, the rest indented under the word's first column), each of
those rows a row of the flow; the next entry starts after its last row's text.

Painting (`paint(rect, ctx, grid, clip=None)`), `g = ctx.ground()`: the clip's
ground, the flow, `shade(grid, clip, bg=g.style.bg)`. Hits: `(Hit(clip, id),)` when
`id` is not `None`.

Measuring: `"x"`: the one-row width, `P` plus every entry and separator (0 with
neither); `"y"`: the flow's rows at width `room` with no height limit (`1` for a
label alone, `0` with neither).

Exact cells (the builtin theme):
- `Legend((Entry("●", "out", "accent"), Entry("○", "return", "accent"),
  Entry("✕", "failed", "error")), label="run")` at `Rect(0, 0, 30, 1)`:
  `"run ● out  ○ return  ✕ failed "` (4 + 5 + 2 + 8 + 2 + 8 = 29 cells, then one of
  ground); `●` and `○` in
  `ctx.style("accent")`, `✕` in `ctx.style("error")`, the words in
  `ctx.style("muted")`, `run` in `ctx.style("dim")`.
- At `Rect(0, 0, 20, 2)`: `"run ● out  ○ return "`, `"    ✕ failed        "`.
- At `Rect(0, 0, 20, 1)`: `"run ● out  ○ return "` cannot take `" …"` after
  `○ return` (19 + 2 > 20), so that entry is dropped: `"run ● out …         "`.

Errors: `TypeError` when `entries` is not a tuple of `Entry`, a marker or word is
  neither a `str` nor a `Line`, `role` is neither `None` nor a `str`, `label` is not a
  `str`, or `id` is unhashable. `measure` / `paint`: as the protocol states.
Effects: none, apart from `paint`'s writes into the grid it is given.
"""

from collections.abc import Hashable
from dataclasses import KW_ONLY, dataclass

from cure.core.buffer import Grid
from cure.core.geometry import Hit, Rect
from cure.core.text import Line, wrap

from .keyhints import flow
from .paragraph import (_begin, _check_common, _check_measure, _check_role, _check_text, _ground,
                        _join, _own, _paint_flow, _plain, _shade, _styled)


@dataclass(frozen=True)
class Entry:
    """One legend entry: a marker, the role it was drawn in, and its word."""

    marker: "str | Line"
    word: "str | Line"
    role: "str | None" = None

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _check_text("marker", self.marker)
        _check_text("word", self.word)
        if self.role is not None:
            _check_role("role", self.role)


@dataclass(frozen=True)
class Legend:
    """Marker + word entries after a label, wrapping between entries (see the module)."""

    entries: tuple = ()
    _: KW_ONLY
    label: str = ""
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = False

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        if not isinstance(self.entries, tuple) or not all(isinstance(e, Entry) for e in self.entries):
            raise TypeError("entries must be a tuple of Entry")
        if not isinstance(self.label, str):
            raise TypeError(f"label must be a str, got {type(self.label).__name__}")
        _check_common(self)

    def chrome(self) -> None:
        """None: a leaf has no insets."""
        return None

    def lifts(self, ctx: object) -> bool:
        """Always False."""
        return False

    def measure(self, axis: str, room: int, ctx: object, content: int = 0) -> int:
        """One row's width, or the flow's rows at `room` columns (see the module)."""
        _check_measure(axis, room, content)
        prefix, P = self._prefix(ctx)
        items = self._items(ctx)
        if axis == "x":
            return P + sum((sep.width if i else 0) + line.width
                           for i, (line, sep, _, _) in enumerate(items))
        if not items:
            return 1 if P else 0
        return len(flow(P, items, room, None, ctx))

    def paint(self, rect: Rect, ctx: object, grid: Grid, clip: "Rect | None" = None
              ) -> "tuple[Hit, ...]":
        """The legend into `grid` inside `clip` (see the module)."""
        begun = _begin(rect, grid, clip)
        if begun is None:
            return ()
        clip, area = begun
        g = ctx.ground()
        _ground(grid, area, g.style)
        if rect.h >= 1:
            prefix, P = self._prefix(ctx)
            items = self._items(ctx)
            rows = flow(P, items, rect.w, rect.h, ctx) if items else []
            _paint_flow(rows, prefix, P, rect, grid, area)
        _shade(grid, area, g.style)
        return tuple(_own(self, clip))

    def _prefix(self, ctx: object) -> "tuple[Line, int]":
        """The label and its ground cell, and its width `P` (0 without a label)."""
        if not self.label:
            return Line(), 0
        line = _join(_plain(self.label, ctx.style("dim")), _plain(" ", ctx.ground().style))
        return line, line.width

    def _items(self, ctx: object) -> list:
        """The entries as flow items `(line, sep, None, broken)`."""
        gs = ctx.ground().style
        sep = _plain("  ", gs)
        space = _plain(" ", gs)
        out = []
        for entry in self.entries:
            marker = _styled(entry.marker, ctx, entry.role or "text")
            word = _styled(entry.word, ctx, "muted")
            line = _join(marker, space, word)

            def broken(avail: int, marker=marker, word=word) -> list:
                indent = marker.width + 1
                rows = wrap(word, max(1, avail - indent))
                return [(0, _join(marker, space, rows[0]))] + [(indent, r) for r in rows[1:]]

            out.append((line, sep, None, broken))
        return out
