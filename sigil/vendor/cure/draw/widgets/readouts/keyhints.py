"""[KeyHints]: drawn from a bindings table it is given.

Kind: service (two frozen dataclasses: the `KeyHints` node kind and `Hint`, one
entry of the shape it reads; see the Widgets package's protocol).

What it does: one or more rows of `key action` hints, read from the same bindings
table that drives dispatch and help (one bindings table: Rules carried over), so a
hint can never disagree with what a key does. KeyHints never builds or filters the
table's logic itself: it shows the entries it is given, in their order, skipping the
hidden ones. A click on a hint hits its action, so keys and clicks fire the same one.

The shape it reads (duck typed; Input's Bindings, built in I1, offers entries of this
shape, by iterating the table or through a method the app calls; `Hint` below is a
plain one for apps and tests). Each entry is read by attribute:
- `keys`: a `str` or a tuple of `str`, the key labels as Input names them (`"q"`,
  `"ctrl+c"`, `"space"`); several are joined with `"/"` (`("j", "k")` shows `j/k`).
  Required.
- `label`: a `str`, the action's word (`"quit"`). Required.
- `action`: any hashable value or `None`, what a click fires (the hit's tag part;
  `None`: not clickable). Read with `getattr`, default `None`.
- `group`: a `str` or `None`, the entry's group; a change of group between two shown
  entries draws a group separator. `getattr`, default `None`.
- `hidden`: a `bool`; a hidden entry is not shown (bound for dispatch only).
  `getattr`, default `False`.
- `on`: `True`, `False` or `None`: a toggle's state; `True` shows the label bright.
  `getattr`, default `None`.

Data (frozen dataclasses; checked on construction):
- `Hint(keys, label, action=None, *, group=None, hidden=False, on=None)`.
- `KeyHints(bindings=(), *, label="", id=None, size=None, anchor=None, scope=None,
  surface=False)`: `bindings` any iterable of entries of the shape above (Input's
  table, a tuple of `Hint`); it is iterated once, at construction, and held as a
  tuple. `label` a `str` drawn before the hints (sigil's `keys`), `""` for none.

An entry's cells: its keys (joined) in role `key` (the builtin's `$bright on
$overlay`), one ground cell, its label in role `muted` (role `strong` when `on` is
`True`); `s = width(keys) + 1 + width(label)`. Between two shown entries: two ground
cells, or, when their groups differ, `"  " + ctx.glyph("border.light.v") + "  "` (the
bar in `ctx.border(False)`). The prefix, when `label` is not empty: `label` in role
`dim` and one ground cell, `P` cells wide (else `P = 0`).

The flow (KeyHints' `flow`, below; Legend calls it too, the drawn `[Legend] ->
[KeyHints] : flow({Entries}) => {Rows}`; it paints through the family toolkit's
`_paint_flow`, `paragraph.py`), at `rect` `R`, rows `R.y ..`: the prefix on the first
row at `R.x`; every row's entries start at column `R.x + P` (continuation rows are
indented under the label). An entry goes on the current row when it is the row's
first and `s <= R.w - P`, or when it fits after its separator (`cursor + sep + s <=
R.right`); else it starts the next row. An entry alone wider than `R.w - P` goes on a
row of its own, its label cut with `ctx.glyph("ellipsis")` to fit. Wrapping is only
ever between entries. When entries remain after row `R.h - 1` (never silent): on the
last row, its entries are dropped from the end until `" …"` fits after the last kept
one (a row's first entry is kept, cut further if need be), and `" " +
ctx.glyph("ellipsis")` is drawn there in role `muted`.

`flow(P, items, w, h, ctx) -> list` (module level; round 12 moved it here from
`paragraph.py`'s toolkit, where it was `_flow`): the rows of the flow above. Inputs:
`P` the prefix width (an int >= 0); `items` a list of `(line, sep, tag, broken)`, `line` an entry's styled {Line}, `sep` the {Line} drawn before it
when it follows another on a row, `tag` the entry's hit tag or `None`, `broken(avail)`
the `(x, line)` rows of the entry alone when it is wider than a row (KeyHints: one row,
cut with the ellipsis; Legend: its word wrapped); `w` the rect's width; `h` the most
rows (`None`: no limit, as `measure` asks). Outputs: a list of rows, each a list of
pieces `[x, line, tag, whole]` (`x` from the entries' column `R.x + P`; `tag` is
`_SEP` for a separator and for the closing `" …"`; `whole` is `False` for a piece cut
or broken); with `h` rows at most, the last row's entries dropped from its end until
`" " + ctx.glyph("ellipsis")` (role `muted`) fits, a row's first entry kept and cut.
At least one row (`[[]]` for no items). Errors: none of its own (its inputs are the
node's, checked at construction and by `measure` / `paint`); what `ctx.glyph`,
`ctx.style` or `broken` raises propagates. Pure.

Painting (`paint(rect, ctx, grid, clip=None)`), `g = ctx.ground()`: the clip's
ground, the flow, `shade(grid, clip, bg=g.style.bg)`. Hits, in order: `Hit(clip, id)`
when `id` is not `None`; then, when `id` is not `None`, each entry drawn whole whose
`action` is not `None`: `Hit(<its cells> ∩ clip, (id, "action", entry.action))`.

Measuring: `"x"`: the one-row width, `P` plus every shown entry and separator (0
with neither); `"y"`: the flow's rows at width `room` with no height limit (`1` for a
label alone, `0` with neither).

Exact cells (the builtin theme):
- `KeyHints((Hint("q", "quit", "quit"), Hint("?", "help", "help")), id="k")` at
  `Rect(0, 0, 20, 1)`: `"q quit  ? help      "`, `q` and `?` in `ctx.style("key")`,
  `quit` and `help` in `ctx.style("muted")`; hits `Hit(Rect(0, 0, 20, 1), "k")`,
  `Hit(Rect(0, 0, 6, 1), ("k", "action", "quit"))`, `Hit(Rect(8, 0, 6, 1), ("k",
  "action", "help"))`.
- With `label="keys"`: `"keys q quit  ? help "`.
- The two hints at `Rect(0, 0, 8, 2)`: `"q quit  "`, `"? help  "`; at `Rect(0, 0, 8,
  1)`: `"q quit …"`.
- `Hint(("j", "k"), "move", group="nav")`, `Hint("q", "quit", group="app")`:
  `"j/k move  │  q quit"`.

Errors: `TypeError` when `bindings` is not iterable, an entry lacks `keys` or
  `label`, `keys` is neither a `str` nor a tuple of `str`, `label` (an entry's or the
  node's) is not a `str`, `hidden` is not a `bool`, `on` is not `None` or a `bool`, or
  an `action` / `id` is unhashable. `measure` / `paint`: as the protocol states.
Effects: none, apart from `paint`'s writes into the grid it is given.
"""

from collections.abc import Hashable
from dataclasses import KW_ONLY, dataclass

from cure.core.buffer import Grid
from cure.core.geometry import Hit, Rect
from cure.core.text import Line, cut

from .paragraph import (_SEP, _begin, _check_common, _check_measure, _ground, _hit, _join, _own,
                        _paint_flow, _plain, _put, _shade)

def _check_entry(entry: object) -> None:
    """One entry of the shape KeyHints reads (see the module)."""
    for name in ("keys", "label"):
        if not hasattr(entry, name):
            raise TypeError(f"a bindings entry needs `{name}`, got {entry!r}")
    keys = entry.keys
    if not (isinstance(keys, str) or isinstance(keys, tuple) and all(isinstance(k, str) for k in keys)):
        raise TypeError(f"keys must be a str or a tuple of str, got {keys!r}")
    if not isinstance(entry.label, str):
        raise TypeError(f"label must be a str, got {type(entry.label).__name__}")
    if not isinstance(getattr(entry, "hidden", False), bool):
        raise TypeError("hidden must be a bool")
    on = getattr(entry, "on", None)
    if on is not None and not isinstance(on, bool):
        raise TypeError("on must be None or a bool")
    action = getattr(entry, "action", None)
    if not isinstance(action, Hashable):
        raise TypeError(f"action must be hashable, got {type(action).__name__}")
    hash(action)
    group = getattr(entry, "group", None)
    if group is not None and not isinstance(group, str):
        raise TypeError(f"group must be None or a str, got {type(group).__name__}")


@dataclass(frozen=True)
class Hint:
    """One bindings entry as KeyHints reads it (see the module)."""

    keys: "str | tuple[str, ...]"
    label: str
    action: Hashable = None
    _: KW_ONLY
    group: "str | None" = None
    hidden: bool = False
    on: "bool | None" = None

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _check_entry(self)


@dataclass(frozen=True)
class KeyHints:
    """Key hints drawn from the bindings table it is given (see the module)."""

    bindings: tuple = ()
    _: KW_ONLY
    label: str = ""
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = False

    def __post_init__(self) -> None:
        """Hold the entries as a tuple and check them (see Errors)."""
        try:
            entries = tuple(self.bindings)
        except TypeError:
            raise TypeError(f"bindings must be iterable, got {type(self.bindings).__name__}") from None
        for entry in entries:
            _check_entry(entry)
        object.__setattr__(self, "bindings", entries)
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
        """The hints into `grid` inside `clip` (see the module)."""
        begun = _begin(rect, grid, clip)
        if begun is None:
            return ()
        clip, area = begun
        g = ctx.ground()
        _ground(grid, area, g.style)
        R = rect
        hits = _own(self, clip)
        if R.h >= 1:
            prefix, P = self._prefix(ctx)
            items = self._items(ctx)
            rows = flow(P, items, R.w, R.h, ctx) if items else []
            _paint_flow(rows, prefix, P, R, grid, area)
            if self.id is not None:
                for i, row in enumerate(rows):
                    for x, line, tag, whole in row:
                        if whole and tag is not _SEP and tag is not None:
                            hit = _hit(Rect(R.x + P + x, R.y + i, line.width, 1), clip,
                                       (self.id, "action", tag))
                            if hit is not None:
                                hits.append(hit)
        _shade(grid, area, g.style)
        return tuple(hits)

    def _prefix(self, ctx: object) -> "tuple[Line, int]":
        """The label and its ground cell, and its width `P` (0 without a label)."""
        if not self.label:
            return Line(), 0
        line = _join(_plain(self.label, ctx.style("dim")), _plain(" ", ctx.ground().style))
        return line, line.width

    def _items(self, ctx: object) -> list:
        """The shown entries as flow items `(line, sep, action, broken)`."""
        gs = ctx.ground().style
        ell = ctx.glyph("ellipsis")
        plain_sep = _plain("  ", gs)
        group_sep = _join(_plain("  ", gs), _plain(ctx.glyph("border.light.v"), ctx.border(False)),
                          _plain("  ", gs))
        out, prev = [], None
        for entry in self.bindings:
            if getattr(entry, "hidden", False):
                continue
            keys = entry.keys if isinstance(entry.keys, str) else "/".join(entry.keys)
            role = "strong" if getattr(entry, "on", None) is True else "muted"
            line = _join(_plain(keys, ctx.style("key")), _plain(" ", gs),
                         _plain(entry.label, ctx.style(role)))
            group = getattr(entry, "group", None)
            sep = group_sep if out and group != prev else plain_sep
            prev = group
            broken = lambda avail, line=line: [(0, cut(line, max(0, avail), ellipsis=ell))]
            out.append((line, sep, getattr(entry, "action", None), broken))
        return out


def flow(P: int, items: list, w: int, h: "int | None", ctx: object) -> list:
    """KeyHints' flow (Legend calls it too; see the module's The flow): the rows of
    pieces `[x, line, tag, whole]` (x from the entries' column, `R.x + P`) for `items`,
    each `(line, sep, tag, broken)` (`broken(avail)` gives the `(x, line)` rows of an
    entry alone wider than the row), at width `w`; with `h` rows at most, the last ends
    `" …"`."""
    avail = w - P
    rows: list = [[]]
    cursor = 0
    for line, sep, tag, broken in items:
        s = line.width
        if rows[-1]:
            if cursor + sep.width + s <= avail:
                rows[-1].append([cursor, sep, _SEP, True])
                rows[-1].append([cursor + sep.width, line, tag, True])
                cursor += sep.width + s
                continue
            rows.append([])
        if s <= avail:
            rows[-1].append([0, line, tag, True])
            cursor = s
            continue
        for j, (x, part) in enumerate(broken(avail)):
            if j:
                rows.append([])
            rows[-1].append([x, part, tag, False])
            cursor = x + part.width
    if h is None or len(rows) <= h:
        return rows
    rows = rows[:h]
    last = rows[-1]
    ell = _plain(" " + ctx.glyph("ellipsis"), ctx.style("muted"))
    end = lambda: last[-1][0] + last[-1][1].width
    while len(last) > 1 and end() + ell.width > avail:
        last.pop()
        if last and last[-1][2] is _SEP:
            last.pop()
    if end() + ell.width > avail:
        x, line = last[-1][0], last[-1][1]
        last[-1] = [x, cut(line, max(0, avail - ell.width - x)), last[-1][2], False]
    last.append([end(), ell, _SEP, False])
    return rows
