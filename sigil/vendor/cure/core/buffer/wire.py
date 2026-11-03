"""[Wire]: one char per cell (wide → char + \\0); per row, a side table {column: cluster}
for the cells longer than one char; a style table (roles or hex); versioned.

Kind: service (a data class and pure functions from {Rows} to {Packed}).

What it does: packs a drawing for the hosts that paint cells without a terminal (the
web page, the Claude Code pane, the pi pane; TS code that cannot run Buffer): every
cell becomes exactly one code point, so a host crops, pans and measures by counting
code points; the cells whose cluster is longer than one code point (combining marks,
ZWJ sequences, VS16, flags) are also listed whole in a per-row side table, so a web
host can paint them whole; and every style becomes an entry of a small table, its
colours given as theme roles (the page recolours on a theme change) or as hex (a pane
paints cells). A host that ignores the side table renders exactly what it rendered
from version 1. The format is versioned: `WIRE = 2` is this one; a change to anything
below is a new version. (Version 1 was this format without the side table, with
trimming read on the wire char; it is not produced any more.)

Format version 2 (`pack(rows, *, colours="role")`):

- Cells. Each row is laid out as cells by Text's `put` (`[Wire] -> [Text] : put`:
  Wire calls `cure.core.text.put(line)` on each {Line} of `rows.lines` itself,
  through Text's face, not [Cells]' `line`, which for a {Line} is that same call and
  so gives the same cells; Wire imports nothing from `cells`) (so widths come from the one
  |WideTable| the hosts share, controls are U+FFFD, marks ride their base, a
  base-less mark at the start of a row is dropped). Each cell is one code point on
  the wire: a narrow cell is its glyph's FIRST code point (marks, joiners and
  selectors after it are left to the side table); a head is its glyph's first code
  point; its tail is `"\\0"` (U+0000). So a wide glyph is `char + "\\0"`, and a row's
  text has exactly as many code points as the row has cells; a cell's column is its
  code-point offset in the row's text.
- Clusters (the side table). For each row, the pairs `(column, cluster)`, in
  ascending column order, one for each kept cell (see Runs: trimmed cells have none)
  whose glyph is longer than one code point: `column` is the cell's 0-based column in
  the row (for a wide glyph, its head's column; a tail never has an entry), and
  `cluster` is the cell's whole glyph exactly as Text's `put` laid it out (no
  normalization; its first code point is the wire char at that column). A cell whose
  glyph is one code point (U+FFFD for a control included) has no entry. A row with no
  such cell has the empty table `()`.
- Styles. Each style becomes an entry `(fg, bg, attrs, link)`:
  - `fg`, `bg`: `None` for no colour (a style field `None`, or a `Colour` of form
    `"default"`); otherwise, with `colours="role"`, the colour's `role` when it is
    not `""`, else its hex; with `colours="hex"`, always its hex. A colour's hex is
    `"#rrggbb"` (lower case): `Colour.hex` for forms `"rgb"` and `"ink"` (the ink's
    24-bit value), and Style's `palette_rgb(i)` for form `"index"` (i) and form
    `"name"` (`i = NAMES.index(name)`, the xterm defaults).
  - `attrs`: a `str` of the letters for the flags the style holds, in this order:
    `"b"` bold, `"d"` dim, `"i"` italic, `"u"` underline (any underline style), `"s"`
    strike, `"r"` reverse; `""` for none. The underline colour is not carried.
  - `link`: the style's `link`, or `None`.
  A `None` style is the plain entry `(None, None, "", None)`, and so is `Style()`.
  The table always starts with the plain entry at index 0; every other distinct
  entry follows in order of first appearance (rows top to bottom, cells left to
  right, trimmed cells included). Styles that encode alike share one entry.
- Runs. A row is a tuple of runs `(text, style_id)`: adjacent cells with the same id
  are one run. Trailing blanks are dropped: from the end of a row, cells whose glyph
  is exactly `" "` and whose entry has no `bg` and none of `"u"`, `"s"`, `"r"`
  (nothing a host would draw; a space carrying a mark, `" \\u0301"`, is drawn and
  kept). Then trailing empty rows are dropped, and their side tables with them, so
  `len(clusters) == len(rows)`.
- `width`: `rows.width` (the widest row in cells, before trimming); `height`: the
  number of rows given (before trimming); `colours`: `"role"` or `"hex"`.

Data (frozen dataclass, stored as given):
- `Packed(version: int, width: int, height: int, colours: str,
  styles: tuple[tuple, ...], rows: tuple[tuple[tuple[str, int], ...], ...],
  clusters: tuple[tuple[tuple[int, str], ...], ...])`. `clusters` has no default;
  `pack` gives it one table per row of `rows`, in the same order.
  - `data() -> dict`: the JSON-ready form, keys in this order: `"wire"` (version),
    `"width"`, `"height"`, `"colours"`, `"styles"` (a list of 4-lists), `"rows"` (a
    list of rows, each a list of `[text, style_id]` 2-lists), then `"clusters"` only
    when at least one row's table is non-empty: a list with one entry per row (an
    empty list for a row with none), each a list of `[column, cluster]` 2-lists in
    column order, `column` an `int` (not a string key). When every table is empty the
    key is absent, so a drawing without long clusters has exactly the version-1 keys.
  - `json() -> str`: `json.dumps(data(), ensure_ascii=False, separators=(",", ":"))`
    (so `"\\0"` appears as the JSON escape `\\u0000`; marks, joiners and selectors
    appear as themselves).

Operations:
- `pack(rows, *, colours="role") -> Packed`: the format above, from a {Rows}.
- `packed(source, *, colours="role") -> Packed`: what a host asks for: `source` is a
  {Rows}, a {Grid} (read as `runs(grid)`, so `width` is the grid's), or anything
  `Rows.of` takes; then `pack`.

Inputs: `rows`: a {Rows}; `source`: as above; `colours`: `"role"` or `"hex"`.
Outputs: {Packed}: version `WIRE` (2), the style table, the rows of runs and, per row,
  the side table of long clusters.
Errors: `TypeError` when `rows` is not a `Rows` (`pack`) or `source` is none of the
  accepted types (`packed`), or a style is neither `None` nor a `Style`; `ValueError`
  when `colours` is neither `"role"` nor `"hex"`.
Effects: none.

Usage:
    from cure.core.style import Style, resolve, Name
    from cure.core.buffer.rows import Rows
    from cure.core.buffer.wire import pack
    teal = Style(fg=resolve(Name("#2aa198", "kinds-service")), bold=True)
    p = pack(Rows.of([[("中x", teal), ("  ", None)]]))
    p.rows        # ((("中\\0x", 1),),): the trailing blanks dropped
    p.clusters    # ((),): no cell longer than one code point
    p.styles      # ((None, None, "", None), ("kinds-service", None, "b", None))
    pack(Rows.of([[("a", teal)]]), colours="hex").styles[1]   # ("#2aa198", None, "b", None)
    p.json()      # '{"wire":2,"width":5,"height":1,"colours":"role",'
                  # '"styles":[[null,null,"",null],["kinds-service",null,"b",null]],'
                  # '"rows":[[["中\\u0000x",1]]]}'   (no "clusters" key)

    m = pack(Rows.of(["cafe\\u0301!"]))     # a combining mark rides its base
    m.rows        # ((("cafe!", 0),),)
    m.clusters    # (((3, "e\\u0301"),),)
    m.json()      # '{"wire":2,"width":5,"height":1,"colours":"role",'
                  # '"styles":[[null,null,"",null]],"rows":[[["cafe!",0]]],'
                  # '"clusters":[[[3,"e\\u0301"]]]}'   (the U+0301 written as itself)

    f = pack(Rows.of(["ab", "\\U0001f1ef\\U0001f1f5 \\U0001f468\\u200d\\U0001f469\\u200d\\U0001f467"]))
    f.rows        # ((("ab", 0),), (("\\U0001f1ef\\0 \\U0001f468\\0", 0),))   (a flag, a ZWJ family)
    f.clusters    # ((), ((0, "\\U0001f1ef\\U0001f1f5"), (3, "\\U0001f468\\u200d\\U0001f469\\u200d\\U0001f467")))
    f.json()      # '{"wire":2,"width":5,"height":2,"colours":"role",'
                  # '"styles":[[null,null,"",null]],"rows":[[["ab",0]],[["\\U0001f1ef\\u0000 \\U0001f468\\u0000",0]]],'
                  # '"clusters":[[],[[0,"\\U0001f1ef\\U0001f1f5"],[3,"\\U0001f468\\u200d\\U0001f469\\u200d\\U0001f467"]]]}'
                  # (every escape but \\u0000 written as the code point itself)
"""

import json
from dataclasses import dataclass

from cure.core.style import NAMES, Colour, Style, palette_rgb
from cure.core.text import Cell, put

from .grid import Grid
from .rows import Rows, runs

WIRE = 2
COLOURS = ("role", "hex")
_PLAIN = (None, None, "", None)


@dataclass(frozen=True)
class Packed:
    """{Packed}: one drawing in wire format `version` (see the module)."""

    version: int
    width: int
    height: int
    colours: str
    styles: "tuple[tuple, ...]"
    rows: "tuple[tuple[tuple[str, int], ...], ...]"
    clusters: "tuple[tuple[tuple[int, str], ...], ...]"

    def data(self) -> dict:
        """The JSON-ready dict: wire, width, height, colours, styles, rows, then clusters when any row has one."""
        return {
            "wire": self.version,
            "width": self.width,
            "height": self.height,
            "colours": self.colours,
            "styles": [list(entry) for entry in self.styles],
            "rows": [[[text, i] for text, i in row] for row in self.rows],
        } | _cluster_data(self.clusters)

    def json(self) -> str:
        """The compact JSON text of `data()`."""
        return json.dumps(self.data(), ensure_ascii=False, separators=(",", ":"))


def pack(rows: Rows, *, colours: str = "role") -> Packed:
    """Rows packed in wire format 2: one code point per cell, runs, a style table, per-row clusters."""
    if not isinstance(rows, Rows):
        raise TypeError(f"expected Rows, got {type(rows).__name__}")
    if colours not in COLOURS:
        raise ValueError(f"colours must be one of {COLOURS}, got {colours!r}")
    table = {_PLAIN: 0}
    laid = []
    for ln in rows.lines:
        cells = []
        for cell in put(ln):
            entry = _entry(cell.style, colours)
            cells.append((cell, table.setdefault(entry, len(table)), entry))
        laid.append(_trimmed(cells))
    while laid and not laid[-1]:
        laid.pop()
    return Packed(WIRE, rows.width, len(rows.lines), colours, tuple(table),
                  tuple(_runs(cells) for cells in laid), tuple(_long(cells) for cells in laid))


def packed(source: "Rows | Grid | object", *, colours: str = "role") -> Packed:
    """A host's packed drawing from Rows, a Grid (via `runs`) or anything `Rows.of` takes."""
    if isinstance(source, Grid):
        return pack(runs(source), colours=colours)
    return pack(Rows.of(source), colours=colours)


def _code_point(cell: Cell) -> str:
    """The one code point a cell is on the wire: "\\0" for a tail, else its glyph's first."""
    return "\0" if cell.width == 0 else cell.glyph[0]


def _cluster_data(clusters: tuple) -> dict:
    """`{"clusters": ...}` when any row's side table is non-empty, else `{}`."""
    if not any(clusters):
        return {}
    return {"clusters": [[[column, cluster] for column, cluster in table] for table in clusters]}


def _entry(style: object, colours: str) -> tuple:
    if style is None:
        return _PLAIN
    if not isinstance(style, Style):
        raise TypeError(f"a style must be None or a Style, got {type(style).__name__}")
    flags = (("b", style.bold), ("d", style.dim), ("i", style.italic),
             ("u", style.underline is not None), ("s", style.strike), ("r", style.reverse))
    attrs = "".join(letter for letter, on in flags if on)
    return (_colour(style.fg, colours), _colour(style.bg, colours), attrs, style.link)


def _colour(colour: "Colour | None", colours: str) -> "str | None":
    if colour is None or colour.form == "default":
        return None
    if colours == "role" and colour.role:
        return colour.role
    if colour.form in ("rgb", "ink"):
        return colour.hex
    index = colour.value if colour.form == "index" else NAMES.index(colour.value)
    return "#%02x%02x%02x" % palette_rgb(index)


def _trimmed(cells: list) -> list:
    """The cells without the trailing blanks a host would not draw."""
    end = len(cells)
    while end and _undrawn(cells[end - 1]):
        end -= 1
    return cells[:end]


def _undrawn(cell: tuple) -> bool:
    laid, _, (fg, bg, attrs, link) = cell
    return laid.glyph == " " and bg is None and not any(a in attrs for a in "usr")


def _long(cells: list) -> "tuple[tuple[int, str], ...]":
    """The row's side table: (column, glyph) for each kept cell longer than one code point."""
    return tuple((column, laid.glyph) for column, (laid, _, _) in enumerate(cells) if len(laid.glyph) > 1)


def _runs(cells: list) -> "tuple[tuple[str, int], ...]":
    out: list[list] = []
    for laid, i, _ in cells:
        char = _code_point(laid)
        if out and out[-1][1] == i:
            out[-1][0] += char
        else:
            out.append([char, i])
    return tuple((text, i) for text, i in out)
