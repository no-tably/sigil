"""[PropertyList]: key:value rows aligned at the separator.

zone = 1 + widest key; dash leaders; the mark in the last leader cell.

Kind: service (two frozen dataclasses: the `PropertyList` node kind and its `Item`
rows; see the Widgets package's protocol). No flow of its own: the key zone is Text's
`measure(keys)`, `1 + max(width(key))`, `1` for no keys, one of Draw's uses of Core's
primitives that the root's `[Draw] -> [Core]` stands for (not drawn one by one).

What it does: one row per item, `key: value`, the keys right-aligned against one
separator column so the values start in one column. The key zone is one cell wider
than the widest key, so every row has at least one leader cell before its key, and
the last leader cell is where a state's mark goes (never over text). Key and value
highlights are word-exact: a text-extent state colours exactly the key's and the
value's text; a row-extent state (the cursor, a selection) runs the full row.

Data (frozen dataclasses; checked on construction):
- `Item(key, value="", state=None, *, id=None)`: `key` and `value` styled text (`str`
  or {Line}; span style `None` is the role `muted` for the key and `text` for the
  value); `state` one of Theme's states (`"focused"`, `"selected"`, `"hover"`,
  `"pressed"`, `"active"`, `"emphasised"`, `"muted"`, `"disabled"`) or `None`; `id`
  the row's own tag.
- `PropertyList(items=(), *, id=None, size=None, anchor=None, scope=None,
  surface=False)`: `items` a tuple of `Item`.

The zone: `Z = measure(<the items' keys>)` (Text's), or `max(ctx.zone, Z)` when
`ctx.zone` is not `None` (an enclosing node pushed one so sibling lists align).

A row, for item `it` at `rect` `R` (row `R.y + i`), with `wk = width(key)`, `wv =
width(value)`, leaders `L = Z - wk` (always >= 1) and `full = Z + 2 + wv`:
1. The order of sacrifice when `R.w < full`: the leaders shrink first, to
   `L' = max(1, L - (full - R.w))` (that row loses its alignment, never its mark
   cell); then the value is cut with `ctx.glyph("ellipsis")` to the room left; the
   key is never cut, but by the rect itself when `R.w < 1 + wk`.
2. The cells, from `R.x`: `L'` leader cells, `ctx.glyph("leader")` (-) in role `dim`;
   the key; the separator `": "` (two cells in the ground's style: unpainted); the
   value; ground to the end of the row.
3. The mark: the first non-empty mark of focused (`ctx.is_focused(it.id)`),
   `it.state`, hover (`ctx.is_hovered(it.id)`) replaces the LAST leader cell (column
   `R.x + L' - 1`), in the leader's style with that state's treatment applied.
4. The states, stacked in the order `it.state`, hover, focused, each
   `ctx.apply(<cell style>, state)` over its treatment's extent: `"row"` (focused,
   selected, hover, pressed) over every cell of the row inside the clip, leaders,
   separator and trailing ground included; `"text"` (active, emphasised, muted,
   disabled) over the key's and the value's text cells only.

Painting (`paint(rect, ctx, grid, clip=None)`), `g = ctx.ground()`: the clip's
ground; the rows from `R.y` down, at most `R.h`: with more items than that, the first
`R.h - 1` and then the overflow row (`↓N more`); `shade(grid, clip, bg=g.style.bg)`.
Hits, in order: `Hit(clip, id)` when `id` is not `None`; then for each row drawn
whose item has an `id`, `Hit(Rect(R.x, row, R.w, 1) ∩ clip, it.id)`.

Measuring: `"x"`: `Z + 2 + max(wv)` (`0` with no items); `"y"`: `len(items)`.

Exact cells (the builtin theme):
- `PropertyList((Item("name", "cure"), Item("id", "42")))` at `Rect(0, 0, 12, 2)`,
  `Z = 5`: `"-name: cure "`, `"---id: 42   "`; `-` in `ctx.style("dim")`, `name`
  and `id` in `ctx.style("muted")`, `": "` in `ctx.ground().style`, `cure` and `42`
  in `ctx.style("text")`.
- `Item("id", "42", "emphasised")` second: `"--✦id: 42   "`, `id` and `42` in
  `ctx.apply(<their role>, "emphasised")` (bold), the `✦` in
  `ctx.apply(ctx.style("dim"), "emphasised")`, the rest as before.
- `Item("name", "cure", id="n")` first with `ctx.focus == "n"`: `"›name: cure "`,
  every one of its twelve cells `ctx.apply(<its style>, "focused")`; hits
  `(Hit(Rect(0, 0, 12, 1), "n"),)`.
- With `ctx.zone == 8`: `"----name: cure"`, `"------id: 42"` (width 14).
- `Item("name", "a long value")` alone at width 12 (`Z = 5`, `full = 19`): `L' =
  max(1, 1 - 7) = 1`, the value cut to 5: `"-name: a lo…"`.

Errors: `TypeError` when `items` is not a tuple of `Item`, a key or value is neither
  a `str` nor a `Line`, `state` is neither `None` nor a `str`, or an `id` is
  unhashable; `ValueError` when `state` is not one of the states. `measure` / `paint`:
  as the protocol states.
Effects: none, apart from `paint`'s writes into the grid it is given.
"""

from collections.abc import Hashable
from dataclasses import KW_ONLY, dataclass

from cure.core.buffer import Grid
from cure.core.geometry import Hit, Rect
from cure.core.text import Line, cut, measure

from .paragraph import (_begin, _check_common, _check_measure, _check_text, _ground, _hit, _more,
                        _own, _plain, _put, _restyle, _shade, _shown, _styled, _width)

STATES = ("focused", "selected", "hover", "pressed", "active", "emphasised", "muted", "disabled")
"""The states an item may be in (Theme's [States])."""


@dataclass(frozen=True)
class Item:
    """One key:value row (see the module)."""

    key: "str | Line"
    value: "str | Line" = ""
    state: "str | None" = None
    _: KW_ONLY
    id: Hashable = None

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _check_text("key", self.key)
        _check_text("value", self.value)
        if self.state is not None and not isinstance(self.state, str):
            raise TypeError(f"state must be None or a str, got {type(self.state).__name__}")
        if self.state is not None and self.state not in STATES:
            raise ValueError(f"state must be one of {STATES}, got {self.state!r}")
        if not isinstance(self.id, Hashable):
            raise TypeError(f"id must be hashable, got {type(self.id).__name__}")
        hash(self.id)


@dataclass(frozen=True)
class PropertyList:
    """Key:value rows aligned at the separator (see the module)."""

    items: tuple = ()
    _: KW_ONLY
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = False

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        if not isinstance(self.items, tuple) or not all(isinstance(i, Item) for i in self.items):
            raise TypeError("items must be a tuple of Item")
        _check_common(self)

    def zone(self, ctx: object) -> int:
        """The key zone: Text's `measure` of the keys, at least `ctx.zone`."""
        z = measure(item.key for item in self.items)
        return z if ctx.zone is None else max(ctx.zone, z)

    def chrome(self) -> None:
        """None: a leaf has no insets."""
        return None

    def lifts(self, ctx: object) -> bool:
        """Always False."""
        return False

    def measure(self, axis: str, room: int, ctx: object, content: int = 0) -> int:
        """The zone, separator and widest value; one row per item (see the module)."""
        _check_measure(axis, room, content)
        if axis == "y":
            return len(self.items)
        if not self.items:
            return 0
        return self.zone(ctx) + 2 + max(_width(item.value) for item in self.items)

    def paint(self, rect: Rect, ctx: object, grid: Grid, clip: "Rect | None" = None
              ) -> "tuple[Hit, ...]":
        """The rows into `grid` inside `clip` (see the module)."""
        begun = _begin(rect, grid, clip)
        if begun is None:
            return ()
        clip, area = begun
        g = ctx.ground()
        _ground(grid, area, g.style)
        R = rect
        hits = _own(self, clip)
        keep, more = _shown(len(self.items), R.h)
        if keep or more:
            Z = self.zone(ctx)
            st = _Styler(ctx)
            for i in range(keep):
                item = self.items[i]
                if area.y <= R.y + i < area.bottom:
                    self._row(item, Z, R, R.y + i, ctx, grid, area, st)
                if item.id is not None:
                    hit = _hit(Rect(R.x, R.y + i, R.w, 1), clip, item.id)
                    if hit is not None:
                        hits.append(hit)
            if more:
                _put(grid, R.x, R.y + keep, _more(ctx, more, R.w), area)
        _shade(grid, area, g.style)
        return tuple(hits)

    def _row(self, item: Item, Z: int, R: Rect, y: int, ctx: object, grid: Grid,
             area: Rect, st: "_Styler") -> None:
        """One key:value row on row `y` (see the module's steps 1 to 4)."""
        key = _styled(item.key, ctx, "muted")
        value = _styled(item.value, ctx, "text")
        wk, wv = key.width, value.width
        L = Z - wk
        full = Z + 2 + wv
        if R.w < full:
            L = max(1, L - (full - R.w))
        vx = L + wk + 2
        room = max(0, R.w - vx)
        if wv > room:
            value = cut(value, room, ellipsis=ctx.glyph("ellipsis"))
        dim = ctx.style("dim")
        _put(grid, R.x, y, _plain(ctx.glyph("leader") * L, dim), area)
        _put(grid, R.x + L, y, key, area)
        _put(grid, R.x + L + wk, y, _plain(": ", ctx.ground().style), area)
        _put(grid, R.x + vx, y, value, area)
        focused, hovered = ctx.is_focused(item.id), ctx.is_hovered(item.id)
        for state, on in (("focused", focused), (item.state, item.state), ("hover", hovered)):
            if on:
                mark = st.treat(state).mark
                if mark:
                    _put(grid, R.x + L - 1, y, _plain(mark, st.apply(state)(dim)), area)
                    break
        for state, on in ((item.state, item.state), ("hover", hovered), ("focused", focused)):
            if not on:
                continue
            how = st.apply(state)
            if st.treat(state).extent == "row":
                _restyle(grid, R.x, R.right, y, area, how)
            else:
                _restyle(grid, R.x + L, R.x + L + wk, y, area, how)
                _restyle(grid, R.x + vx, R.x + vx + value.width, y, area, how)


class _Styler:
    """`ctx.apply` and `ctx.treat`, memoised for one paint call (pure: the same
    answers, asked once)."""

    # Speed: a row-extent state restyles every cell of its row; the cells share a few
    # styles, so each (style, state) is laid once per paint, not once per cell.

    def __init__(self, ctx: object) -> None:
        self.ctx = ctx
        self.treats: dict = {}
        self.applied: dict = {}

    def treat(self, state: str) -> object:
        t = self.treats.get(state)
        if t is None:
            t = self.treats[state] = self.ctx.treat(state)
        return t

    def apply(self, state: str):
        def how(style: object) -> object:
            key = (style, state)
            try:
                return self.applied[key]
            except KeyError:
                out = self.applied[key] = self.ctx.apply(style, state)
                return out
            except TypeError:
                return self.ctx.apply(style, state)
        return how
