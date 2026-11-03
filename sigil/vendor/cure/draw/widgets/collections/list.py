"""[List]: virtualised, selectable, tail-follow (a log).

Kind: service (two frozen dataclasses, the `List` node kind and its `ListRow` item;
the `Window` value and the pure functions `window` and `reveal`; see the Widgets
package's protocol and the Collections package's shared rules: the source, the
gutter, a row's states, the window, the hits).

What it does: one row per item of an app-owned source, from an offset the app keeps,
each row its two gutter cells then its text; rows past the rect fold into the
indicator row (`↓N more`, `↑N more`, `↑A ↓B more`). `follow=True` pins the view to
the source's tail, so a log that grows shows its newest rows. It paints only the
rows in view.

Data (frozen dataclasses; checked on construction):
- `ListRow(text, state=None, *, id=None)`: one row: `text` styled text (a `str` or
  a Text {Line}; span style `None` is the role `text`, a `str` a theme role, a Style
  as given); `state` one of Theme's states (`"focused"`, `"selected"`, `"hover"`,
  `"pressed"`, `"active"`, `"emphasised"`, `"muted"`, `"disabled"`) or `None`; `id`
  the row's own tag (hashable or `None`). A source row may also be a bare `str` or
  `Line`: `ListRow(row)`.
- `List(rows=(), *, count=None, cursor=None, selected=frozenset(), offset=0,
  follow=False, focused=None, id=None, size=None, anchor=None, scope=None,
  surface=False)`:
  - `rows`: the source (Collections: a sequence, or a callable with `count`).
  - `count`: `None` for a sequence (its `len` is read when needed, so a list the app
    appends to grows the view); an `int >= 0` for a callable.
  - `cursor`: `None` (no cursor row) or an index in `range(n)`, `n` the row count at
    construction.
  - `selected`: the selected indices, any container (`in` is all that is asked: a
    set, a frozenset, a range, a tuple).
  - `offset`: an `int >= 0`, the first row the app wants shown (clamped by
    `window`).
  - `follow`: `True` shows the tail (the window's `first` is its top, below).
  - `focused`: `None` (ask `ctx.is_focused(id)`), `True` or `False`.
  - `id`, `size`, `anchor`, `scope`, `surface`: as the protocol states.
- `Window(first, shown, above, below)`: a frozen dataclass of four ints: the first
  row shown, how many show, how many are hidden above and below.
- `GUTTER = 2`: the reserved mark cells at the start of every row.

The window (`window(offset, count, height, *, follow=False) -> Window`), with `n =
count`, `H = height` (ints >= 0):
- `top = 0` when `n <= H`, else `n - max(H - 1, 0)` (the largest useful `first`;
  `n` when `H <= 1`);
- `first = top` when `follow`, else `min(offset, top)`;
- `cap = H` when `n <= H`, else `max(H - 1, 0)` (the indicator takes the last row);
- `shown = min(cap, n - first)`, `above = first`, `below = n - first - shown`.
So the indicator is drawn exactly when `n > H` (and `H >= 1`), and `above + shown +
below == n`. Examples: `window(0, 10, 4) == Window(0, 3, 0, 7)`; `window(5, 10, 4)
== Window(5, 3, 5, 2)`; `window(9, 10, 4) == Window(7, 3, 7, 0)` (clamped to the
top); `window(0, 10, 4, follow=True) == Window(7, 3, 7, 0)`; `window(3, 3, 4) ==
Window(0, 3, 0, 0)`; `window(0, 5, 1) == Window(0, 0, 0, 5)`; `window(0, 5, 0) ==
Window(0, 0, 0, 5)`.

Revealing (`reveal(cursor, offset, count, height) -> int`): the offset nearest
`offset` that shows row `cursor`. With `top`, `cap` as above and `o = min(offset,
top)`: `o` when `cap == 0`; else `cursor` when `cursor < o`; else `cursor - cap + 1`
when `cursor >= o + cap`; else `o`; the result is then `min(result, top)`. So
`window(reveal(c, o, n, H), n, H)` shows row `c` whenever `H >= 2` or `n <= H`
(a law a test can loop over), and the result equals `min(offset, top)` when that
already shows it (the least move). Examples: `reveal(9, 0, 10, 4) == 7`,
`reveal(2, 5, 10, 4) == 2`, `reveal(6, 5, 10, 4) == 5`, `reveal(4, 0, 3, 4) == 0`.

Painting (`paint(rect, ctx, grid, clip=None)`), on `rect` `R` with `g =
ctx.ground()` and `w = window(offset, n, R.h, follow=follow)`, `n` the row count
now: the clip's ground; row `w.first + k` (`k` in `range(w.shown)`) on cell row
`R.y + k`: the gutter (`R.x`, `R.x + 1`, the marks as the Collections package states),
then from `R.x + GUTTER` its text cut to `R.w - GUTTER` with `ctx.glyph("ellipsis")`
when wider, the rest of the row ground; the row's states over their extents; then,
when `n > R.h >= 1`, the indicator on row `R.y + R.h - 1` with `w.above` and
`w.below`; `shade(grid, clip, bg=g.style.bg)`. A rect narrower than the gutter shows
only the gutter's part that fits (the text gets no cells).

Hits: as the Collections package states (`Hit(clip, id)`, then each drawn row's
`ListRow.id` or `(id, "row", i)`, then `(id, "more")`).

Measuring: `"x"`: `GUTTER + max(width of each row's text)` over every row (`0` with
no rows); `"y"`: `n`.

The row painter (Q9c; Table's and Tree's way to List's rows, as the spec says: "virtualised
as List is: its window, its gutter and its row painter"). Two public names in this
module, neither re-exported by the Collections package (they are the family's, used by
`table.py` and `tree.py`; an app never needs them). List paints its own rows through
them too, so a change to List's rows changes Table's and Tree's:
- `fetch(rows, count, i) -> object`: row `i` of an app-owned source, as given:
  `rows[i]` when `count is None` (a sequence), else `rows(i)` (a callable). Inputs: a
  source and its `count` as the Collections package states them, `i` an index in
  `range(count)`. Outputs: the row, unchecked (the collection checks its shape and
  raises the `TypeError` its own Errors name). Errors: none of its own; whatever the
  source raises (an `IndexError` past a sequence's end, the callable's own) propagates.
  Pure apart from what the source does.
- `RowPainter(ctx)`: one paint call's row painter. Inputs: the {Context} of that call
  (read by attribute: `treat`, `apply`). It keeps `ctx.treat(state)` and
  `ctx.apply(style, state)` answers for the call (asked once each; the same answers,
  so a painter is never shared between calls or contexts). Construction checks
  nothing and asks `ctx` nothing.
  - `row(grid, rect, y, area, ground, state, pieces, *, selected=False,
    hovered=False, focused=False) -> None`: one collection row on cell row `y`, as the
    Collections package states a row (the gutter, a row's states): `rect` the
    collection's rect `R`, `area` the clip inside the grid (from `paint`), `ground`
    the ground's style, `state` the row's own state (`None` or one of Theme's
    states), `pieces` a sequence of `(x, line, is_text)` (a styled {Line} at column
    `x`; `is_text` marks the cells a `"text"`-extent state covers). The states are
    applied in the order own state, selected, hover, focused, none twice; a
    `"row"`-extent state first fills `Rect(R.x, y, R.w, 1) ∩ area` with blanks in
    `ground` so treated and covers every piece; a `"text"`-extent state covers the
    text pieces only. Then the marks: cell `R.x` the focused mark when `focused`,
    else the hover mark when `hovered`; cell `R.x + 1` (when `R.w >= 2`) the selected
    mark when `selected`, else the mark of `state` when it is neither `"focused"`
    nor `"hover"`; each mark in the row's blank style. Every cell is written once,
    only inside `area`; a `y` outside `area` writes nothing. Outputs: `None`.
    Effects: writes into `grid` inside `area` only. Errors: none of its own (its
    inputs are the collection's, checked at construction and by `paint`); what
    `ctx.treat` or `ctx.apply` raises propagates.
  - `hit(rect, y, clip, item_id, cid, part, i) -> Hit | None`: a drawn row's hit, as
    the Collections package states the hits: `Hit(Rect(rect.x, y, rect.w, 1) ∩ clip,
    tag)` with `tag = item_id` when that is not `None`, else `(cid, part, i)` when
    `cid` is not `None`; `None` when there is no tag or the intersection is empty.
    `part` is `"row"` for every kind today. Pure; errors: none of its own.
  - `treat(state)`, `compose(states)`, `apply(state)`: the kept answers themselves.
    `treat` is `ctx.treat(state)`; `compose` and `apply` give a `style -> style` that
    applies `states` in order, or the one `state`, through `ctx.apply`, each answer
    asked once. `row` styles through them, and Table's header restyles its hovered
    cells through `apply("hover")`. Errors: what `ctx` raises propagates.
- `row(painter, grid, rect, y, area, ground, state, pieces, *, selected=False,
  hovered=False, focused=False) -> None`: the drawn flow's op (`[Table] -> [List] : row`,
  `[Tree] -> [List] : row`), module-level as Term's `show` is beside its method:
  `painter.row(grid, rect, y, area, ground, state, pieces, selected=selected,
  hovered=hovered, focused=focused)`, with the same result, effects and errors, and no
  check of `painter` of its own (a non-painter fails as its missing method does). List,
  Table and Tree paint each row through it.
Table and Tree import `GUTTER`, `window`, `fetch`, `RowPainter` and `row` from here, plus the
family's private toolkit (`_begin`, `_check_*`, `_ground`, `_put`, `_styled`, `_fitted`,
`_indicator`, `_shade`, ...), which List uses too: same-system helpers, not List's face.

Exact cells (the builtin theme, `ctx = Context.of(builtin())`; text in
`ctx.style("text")`, the indicator in `ctx.style("muted")`, every blank in
`ctx.ground().style`, before the states are applied):
- `List(("alpha", "beta", "gamma"), id="l")` at `Rect(0, 0, 8, 3)`: `"  alpha "`,
  `"  beta  "`, `"  gamma "`; hits `Hit(Rect(0, 0, 8, 3), "l")`, then
  `Hit(Rect(0, y, 8, 1), ("l", "row", y))` for `y` in 0, 1, 2.
- The same with `cursor=1` and `ctx.focus == "l"`: row 1 `"› beta  "`, its eight
  cells `ctx.apply(<their style>, "focused")`; unfocused (no `ctx.focus`), row 1 is
  drawn as at rest (`"  beta  "`).
- `selected={2}`: row 2 `" •gamma "`, every cell `ctx.apply(.., "selected")`; with
  `cursor=2` and `ctx.focus == "l"` too: `"›•gamma "`, every cell selected then
  focused.
- `ListRow("beta", "emphasised")` second: `" ✦beta  "`, `beta`'s four cells in
  `ctx.apply(ctx.style("text"), "emphasised")` (bold), the gutter unstyled by it.
- `List(("abcdefghij",))` at `Rect(0, 0, 6, 1)`: `"  abc…"`.
- `List(tuple(f"r{i}" for i in range(10)))` at `Rect(0, 0, 10, 4)`: `"  r0      "`,
  `"  r1      "`, `"  r2      "`, `"↓7 more   "`; `offset=5`: `"  r5"`, `"  r6"`,
  `"  r7"`, `"↑5 ↓2 more"` (each padded to 10); `follow=True`: `"  r7"`, `"  r8"`,
  `"  r9"`, `"↑7 more"`.
- `List(lambda i: f"line {i}", count=1000, offset=500)` at `Rect(0, 0, 16, 3)`:
  `"  line 500"`, `"  line 501"`, `"↑500 ↓498 more"`; the source is asked for 500
  and 501 only.
- `measure("x", 0, ctx) == 7` and `measure("y", 0, ctx) == 3` for the first list.

Errors: construction: `TypeError` when `rows` is neither a sequence (a `str` or
  `bytes` refused) nor a callable, `count` is not `None` or an int (a `bool`
  included), `cursor` / `offset` is not an int (`cursor` may be `None`), `selected`
  has no `__contains__`, `follow` or `surface` is not a `bool`, `focused` is not
  `None` or a `bool`, `text` (a `ListRow`'s) is neither a `str` nor a `Line`,
  `state` is neither `None` nor a `str`, or an `id` is unhashable; `ValueError` when
  a callable source has no `count`, a sequence has one, `count` or `offset` is
  negative, `cursor` is outside `range(n)`, or `state` is not one of the states.
  `window` / `reveal`: `TypeError` for a non-int argument (a `bool` included),
  `ValueError` for a negative one. `paint` / `measure`: as the protocol states, and
  a `TypeError` for a fetched row that is not a `str`, `Line` or `ListRow`.
Effects: none, apart from `paint`'s writes into the grid it is given.

Usage:
    from cure.core.buffer import Grid, text
    from cure.core.geometry import Rect
    from cure.draw.context import Context
    from cure.draw.theme import builtin
    from cure.draw.widgets.collections import List, reveal
    log = [f"r{i}" for i in range(10)]
    ctx = Context.of(builtin())
    g = Grid(10, 4)
    List(log, follow=True).paint(Rect(0, 0, 10, 4), ctx, g)
    text(g)                      # "  r7\\n  r8\\n  r9\\n↑7 more"
    reveal(9, 0, 10, 4)          # 7
"""

from collections.abc import Hashable
from dataclasses import KW_ONLY, dataclass

from cure.core.buffer import Grid, fill, put, shade, write
from cure.core.geometry import Hit, Rect
from cure.core.text import Cell, Line, Span, cut, width

GUTTER = 2
"""The reserved mark cells at the start of every row: the cursor cell, the state cell."""

_STATES = ("focused", "selected", "hover", "pressed", "active", "emphasised", "muted", "disabled")


# -- the family's private helpers (Collections may not share another family's own) --

def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_int(name: str, value: object, *, none: bool = False) -> None:
    """An int >= 0 (a bool refused), or None when `none`."""
    if none and value is None:
        return
    if not _is_int(value):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{name} must be >= 0, got {value}")


def _check_id(name: str, value: object) -> None:
    if not isinstance(value, Hashable):
        raise TypeError(f"{name} must be hashable, got {type(value).__name__}")
    hash(value)


def _check_common(node: object) -> None:
    """The protocol's common fields: `id` hashable, `surface` a bool."""
    if not isinstance(node.surface, bool):
        raise TypeError(f"surface must be a bool, got {type(node.surface).__name__}")
    _check_id("id", node.id)


def _check_text(name: str, value: object) -> None:
    if not isinstance(value, (str, Line)):
        raise TypeError(f"{name} must be a str or a Line, got {type(value).__name__}")


def _check_state(state: object) -> None:
    if state is None:
        return
    if not isinstance(state, str):
        raise TypeError(f"state must be None or a str, got {type(state).__name__}")
    if state not in _STATES:
        raise ValueError(f"state must be one of {_STATES}, got {state!r}")


def _check_flag(name: str, value: object, *, none: bool = False) -> None:
    if none and value is None:
        return
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be {'None or ' if none else ''}a bool, got {type(value).__name__}")


def _check_source(rows: object, count: object) -> int:
    """The source's stated errors; its row count at construction."""
    if count is not None and not _is_int(count):
        raise TypeError(f"count must be None or an int, got {type(count).__name__}")
    if isinstance(rows, (str, bytes)):
        raise TypeError(f"rows must be a sequence or a callable, got {type(rows).__name__}")
    if _is_sequence(rows):
        if count is not None:
            raise ValueError("a sequence source takes no count")
        return len(rows)
    if callable(rows):
        if count is None:
            raise ValueError("a callable source needs a count")
        if count < 0:
            raise ValueError(f"count must be >= 0, got {count}")
        return count
    raise TypeError(f"rows must be a sequence or a callable, got {type(rows).__name__}")


def _is_sequence(rows: object) -> bool:
    return hasattr(rows, "__len__") and hasattr(rows, "__getitem__")


def _count(rows: object, count: "int | None") -> int:
    """The source's row count now (a list the app appends to grows the view)."""
    return len(rows) if count is None else count


def _check_collection(node: object) -> int:
    """List's and Table's shared fields (see List's Errors); the row count."""
    n = _check_source(node.rows, node.count)
    if node.cursor is not None:
        if not _is_int(node.cursor):
            raise TypeError(f"cursor must be None or an int, got {type(node.cursor).__name__}")
        if not 0 <= node.cursor < n:
            raise ValueError(f"cursor {node.cursor} is outside range({n})")
    _check_int("offset", node.offset)
    if not hasattr(node.selected, "__contains__"):
        raise TypeError(f"selected must be a container, got {type(node.selected).__name__}")
    _check_flag("follow", node.follow)
    _check_flag("focused", node.focused, none=True)
    _check_common(node)
    return n


def _check_measure(axis: object, room: object, content: object) -> None:
    """measure's stated errors: the axis, then `room` and `content` (ints >= 0)."""
    if axis not in ("x", "y"):
        raise ValueError(f"axis must be 'x' or 'y', got {axis!r}")
    for name, value in (("room", room), ("content", content)):
        if not _is_int(value):
            raise TypeError(f"{name} must be an int, got {type(value).__name__}")
        if value < 0:
            raise ValueError(f"{name} must be >= 0, got {value}")


def _begin(rect: object, grid: object, clip: object) -> "tuple[Rect, Rect] | None":
    """paint's stated errors; `(clip, area)` (area: the clip inside the grid), or None
    for an empty clip (nothing is written)."""
    if not isinstance(rect, Rect):
        raise TypeError(f"rect must be a Rect, got {type(rect).__name__}")
    if not isinstance(grid, Grid):
        raise TypeError(f"grid must be a Grid, got {type(grid).__name__}")
    if clip is None:
        clip = rect
    elif not isinstance(clip, Rect):
        raise TypeError(f"clip must be a Rect or None, got {type(clip).__name__}")
    if clip.empty:
        return None
    if clip.intersect(rect) != clip:
        raise ValueError(f"clip {clip} does not lie inside rect {rect}")
    return clip, clip.intersect(Rect(0, 0, grid.w, grid.h))


def _ground(grid: Grid, area: Rect, style: object) -> None:
    """Every cell of `area` becomes a blank in `style` (the recipe's step 1)."""
    if not area.empty:
        fill(grid, area, Cell(" ", 1, style))


def _shade(grid: Grid, area: Rect, style: object) -> None:
    """The recipe's last step: the ground's bg under every written cell without one."""
    bg = getattr(style, "bg", None)
    if bg is not None and not area.empty:
        shade(grid, area, bg=bg)


def _styled(text: "str | Line", ctx: object, role: str) -> Line:
    """Styled text with its spans' styles resolved: None is `role`, a str a theme role,
    a Style as given."""
    if isinstance(text, str):
        return Line((Span(text, ctx.style(role)),)) if text else Line()
    spans = []
    for span in text.spans:
        s = span.style
        if s is None:
            s = ctx.style(role)
        elif isinstance(s, str):
            s = ctx.style(s)
        spans.append(Span(span.text, s))
    return Line(tuple(spans))


def _plain(text: str, style: object) -> Line:
    return Line((Span(text, style),)) if text else Line()


def _join(*lines: Line) -> Line:
    return Line(tuple(span for line in lines for span in line.spans))


def _width(text: "str | Line") -> int:
    """Text's width (`width` / `Line.width`); printable ASCII is one cell a character."""
    if isinstance(text, str):
        return len(text) if text.isascii() and text.isprintable() else width(text)
    if all(sp.text.isascii() and sp.text.isprintable() for sp in text.spans):
        return sum(len(sp.text) for sp in text.spans)
    return text.width


def _fitted(line: Line, room: int, ctx: object) -> Line:
    """`line` cut to `room` cells with the measured ellipsis when wider."""
    if room <= 0:
        return Line()
    return cut(line, room, ellipsis=ctx.glyph("ellipsis")) if _width(line) > room else line


def _put(grid: Grid, x: int, y: int, line: Line, area: Rect) -> None:
    """`line` at (x, y), only inside `area`."""
    if line.spans and area.y <= y < area.bottom and x < area.right:
        put(grid, x, y, line, within=area)


def _restyle(grid: Grid, x0: int, x1: int, y: int, area: Rect, how) -> None:
    """Row `y`'s cells in columns [x0, x1) inside `area` take `how(style)`."""
    lo, hi = max(x0, area.x), min(x1, area.right)
    if not (area.y <= y < area.bottom) or lo >= hi:
        return
    row = grid.row(y)
    if row[lo].width == 0 and lo > area.x:
        lo -= 1
    if row[hi - 1].width == 2 and hi < area.right:
        hi += 1
    cells = [Cell(c.glyph, c.width, how(c.style)) for c in row[lo:hi]]
    write(grid, lo, y, cells, within=area)


def _hit(r: Rect, clip: Rect, tag: object) -> "Hit | None":
    """`Hit(r ∩ clip, tag)`, or None when that is empty."""
    v = r.intersect(clip)
    return None if v.empty else Hit(v, tag)


def _more_text(ctx: object, above: int, below: int) -> str:
    """`More`'s text: `↑A ↓B more`, `↓B more` or `↑A more`."""
    up, down = ctx.glyph("more.up"), ctx.glyph("more.down")
    if above > 0 and below > 0:
        return f"{up}{above} {down}{below} more"
    if below > 0:
        return f"{down}{below} more"
    if above > 0:
        return f"{up}{above} more"
    return ""


def _indicator(grid: Grid, R: Rect, y: int, area: Rect, ctx: object, above: int,
               below: int) -> None:
    """The indicator on row `y`, from `R.x`, in role `muted`, cut to the row."""
    line = cut(_plain(_more_text(ctx, above, below), ctx.style("muted")), max(0, R.w))
    _put(grid, R.x, y, line, area)


def _flags(c: object, ctx: object, i: int, item_id: object, own: "str | None",
           in_selected: bool, f: bool) -> "tuple[bool, bool, bool]":
    """A row's (selected, hovered, focused), as the Collections package states them
    (an item whose own state is one of these three counts as in it)."""
    selected = in_selected or own == "selected"
    hovered = (ctx.is_hovered(item_id) or (c.id is not None and ctx.is_hovered((c.id, "row", i)))
               or own == "hover")
    focused = (i == c.cursor and f) or ctx.is_focused(item_id) or own == "focused"
    return selected, hovered, focused


def _focus(c: object, ctx: object) -> bool:
    """The collection's focus: its `focused` field, else the context's."""
    return c.focused if c.focused is not None else ctx.is_focused(c.id)


def fetch(rows: object, count: "int | None", i: int) -> object:
    """Row `i` of the source, as given (see the module: the row painter)."""
    return rows[i] if count is None else rows(i)


class RowPainter:
    """One paint call's painter for a collection's rows (see the module: the row painter)."""

    # `ctx.apply` and `ctx.treat` are memoised for the call (pure: the same answers,
    # asked once); Table's header restyles through `apply` too.

    def __init__(self, ctx: object) -> None:
        """Keep `ctx`; ask it nothing yet."""
        self.ctx = ctx
        self.treats: dict = {}
        self.applied: dict = {}

    def treat(self, state: str) -> object:
        t = self.treats.get(state)
        if t is None:
            t = self.treats[state] = self.ctx.treat(state)
        return t

    def compose(self, states: "tuple[str, ...]"):
        """`style -> style` with each of `states` applied in order (memoised)."""
        def how(style: object) -> object:
            key = (style, states)
            try:
                return self.applied[key]
            except KeyError:
                pass
            except TypeError:
                key = None
            out = style
            for state in states:
                out = self._applied(out, state)
            if key is not None:
                self.applied[key] = out
            return out
        return how

    def apply(self, state: str):
        return lambda style: self._applied(style, state)

    def _applied(self, style: object, state: str) -> object:
        # Speed: one `ctx.apply` per (style, state) a call, the chains of `compose`
        # sharing their steps (an unhashable style applied directly).
        key = (style, state)
        try:
            return self.applied[key]
        except KeyError:
            out = self.applied[key] = self.ctx.apply(style, state)
            return out
        except TypeError:
            return self.ctx.apply(style, state)

    def row(self, grid: Grid, rect: Rect, y: int, area: Rect, ground: object,
            state: "str | None", pieces: "list[tuple[int, Line, bool]]", *,
            selected: bool = False, hovered: bool = False, focused: bool = False) -> None:
        """One row on cell row `y`: its pieces, its states, its two marks (see the module)."""
        # The states are folded into the styles as the cells are written (each cell is
        # written once).
        if not area.y <= y < area.bottom:
            return
        R, own = rect, state
        order = []
        for s, on in ((own, own is not None), ("selected", selected), ("hover", hovered),
                      ("focused", focused)):
            if on and s not in order:
                order.append(s)
        rowwise = tuple(s for s in order if self.treat(s).extent == "row")
        row_how, text_how = self.compose(rowwise), self.compose(tuple(order))
        blank = row_how(ground)
        if rowwise:
            lo, hi = max(R.x, area.x), min(R.right, area.right)
            if lo < hi:
                fill(grid, Rect(lo, y, hi - lo, 1), Cell(" ", 1, blank))
        for x, line, text in pieces:
            how = text_how if text else row_how
            if order:
                line = Line(tuple(Span(sp.text, how(sp.style)) for sp in line.spans))
            _put(grid, x, y, line, area)
        m0 = self.treat("focused").mark if focused else (
            self.treat("hover").mark if hovered else "")
        if selected:
            m1 = self.treat("selected").mark
        elif own is not None and own not in ("focused", "hover"):
            m1 = self.treat(own).mark
        else:
            m1 = ""
        if m0:
            _put(grid, R.x, y, _plain(m0, blank), Rect(R.x, y, 1, 1).intersect(area))
        if m1 and R.w >= 2:
            _put(grid, R.x + 1, y, _plain(m1, blank), Rect(R.x + 1, y, 1, 1).intersect(area))

    @staticmethod
    def hit(rect: Rect, y: int, clip: Rect, item_id: object, cid: object, part: str,
            i: int) -> "Hit | None":
        """A drawn row's hit: the item's id, else `(cid, part, i)`, else none (see the module)."""
        tag = item_id if item_id is not None else ((cid, part, i) if cid is not None else None)
        return None if tag is None else _hit(Rect(rect.x, y, rect.w, 1), clip, tag)


def row(painter: RowPainter, grid: object, rect: object, y: int, area: object, ground: object,
        state: object, pieces: object, *, selected: bool = False, hovered: bool = False,
        focused: bool = False) -> None:
    """`painter.row(...)`: the drawn op beside the method (see the module)."""
    return painter.row(grid, rect, y, area, ground, state, pieces, selected=selected,
                       hovered=hovered, focused=focused)


@dataclass(frozen=True)
class Window:
    """Which rows of a source show in a view (see the module)."""

    first: int
    shown: int
    above: int
    below: int


def _top_cap(count: int, height: int) -> "tuple[int, int]":
    if count <= height:
        return 0, height
    return count - max(height - 1, 0), max(height - 1, 0)


def window(offset: int, count: int, height: int, *, follow: bool = False) -> Window:
    """The rows `height` cell rows show of `count`, from `offset` (see the module)."""
    for name, value in (("offset", offset), ("count", count), ("height", height)):
        _check_int(name, value)
    top, cap = _top_cap(count, height)
    first = top if follow else min(offset, top)
    shown = min(cap, count - first)
    return Window(first, shown, first, count - first - shown)


def reveal(cursor: int, offset: int, count: int, height: int) -> int:
    """The offset nearest `offset` whose window shows row `cursor` (see the module)."""
    for name, value in (("cursor", cursor), ("offset", offset), ("count", count),
                        ("height", height)):
        _check_int(name, value)
    top, cap = _top_cap(count, height)
    o = min(offset, top)
    if cap == 0:
        r = o
    elif cursor < o:
        r = cursor
    elif cursor >= o + cap:
        r = cursor - cap + 1
    else:
        r = o
    return min(r, top)


@dataclass(frozen=True)
class ListRow:
    """One row of a List: styled text, a state, an id (see the module)."""

    text: "str | Line"
    state: "str | None" = None
    _: KW_ONLY
    id: Hashable = None

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _check_text("text", self.text)
        _check_state(self.state)
        _check_id("id", self.id)


def _list_row(row: object) -> ListRow:
    """A fetched row as a ListRow (a bare `str` or `Line` wrapped)."""
    if isinstance(row, ListRow):
        return row
    if isinstance(row, (str, Line)):
        return ListRow(row)
    raise TypeError(f"a List row must be a str, Line or ListRow, got {type(row).__name__}")


@dataclass(frozen=True)
class List:
    """A virtualised list of rows from an app-owned source (see the module)."""

    rows: object = ()
    _: KW_ONLY
    count: "int | None" = None
    cursor: "int | None" = None
    selected: object = frozenset()
    offset: int = 0
    follow: bool = False
    focused: "bool | None" = None
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = False

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _check_collection(self)

    def chrome(self) -> None:
        """None: no insets."""
        return None

    def lifts(self, ctx: object) -> bool:
        """Always False."""
        return False

    def measure(self, axis: str, room: int, ctx: object, content: int = 0) -> int:
        """The gutter and the widest row; one cell row per row (see the module)."""
        _check_measure(axis, room, content)
        n = _count(self.rows, self.count)
        if axis == "y":
            return n
        widest = None
        for i in range(n):
            w = _width(_list_row(fetch(self.rows, self.count, i)).text)
            widest = w if widest is None or w > widest else widest
        return 0 if widest is None else GUTTER + widest

    def paint(self, rect: Rect, ctx: object, grid: Grid, clip: "Rect | None" = None
              ) -> "tuple[Hit, ...]":
        """The rows in view, their marks and states, the indicator (see the module)."""
        begun = _begin(rect, grid, clip)
        if begun is None:
            return ()
        clip, area = begun
        g = ctx.ground()
        _ground(grid, area, g.style)
        R = rect
        hits = [] if self.id is None else [Hit(clip, self.id)]
        n = _count(self.rows, self.count)
        w = window(self.offset, n, R.h, follow=self.follow)
        f = _focus(self, ctx)
        painter = RowPainter(ctx)
        for k in range(w.shown):
            i = w.first + k
            it = _list_row(fetch(self.rows, self.count, i))
            y = R.y + k
            if area.y <= y < area.bottom:
                pieces = []
                room = R.w - GUTTER
                if room > 0:
                    line = _fitted(_styled(it.text, ctx, "text"), room, ctx)
                    pieces.append((R.x + GUTTER, line, True))
                sel, hov, foc = _flags(self, ctx, i, it.id, it.state, i in self.selected, f)
                row(painter, grid, R, y, area, g.style, it.state, pieces,
                    selected=sel, hovered=hov, focused=foc)
            hit = painter.hit(R, y, clip, it.id, self.id, "row", i)
            if hit is not None:
                hits.append(hit)
        if n > R.h >= 1:
            y = R.y + R.h - 1
            _indicator(grid, R, y, area, ctx, w.above, w.below)
            if self.id is not None:
                hit = _hit(Rect(R.x, y, R.w, 1), clip, (self.id, "more"))
                if hit is not None:
                    hits.append(hit)
        _shade(grid, area, g.style)
        return tuple(hits)
