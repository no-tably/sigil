"""[Select]: menus, dropdowns, a command palette.

Kind: service (two frozen dataclasses, the `Select` node kind and its `Option`
items; see the Widgets package's protocol and the Controls package's shared rules:
the mark cell, the key, the states, the hits).

What it does: a choice among options, drawn one of two ways, as the app says
(`open`): closed, a dropdown's face, one row showing the chosen option and a twisty
(▸); open, the menu, one row per option with a cursor and the chosen one marked. A
dropdown is the closed face in the form and, while it is open, an open `Select` in
an Overlay anchored under it; a menu is an open `Select` in an Overlay; a command
palette is a TextInput over an open `Select` whose options the app has filtered by
the query (and whose labels may style the matched characters through their spans).
Select filters, sorts and chooses nothing itself: the cursor, the choice and the
options are the app's, and roving the cursor, choosing and firing stay three steps.

Data (frozen dataclasses; checked on construction):
- `Option(label, *, hint="", state=None, id=None)`: `label` styled text (span style
  `None` is the role `text`); `hint` styled text drawn at the row's right end (a
  shortcut, a detail; span style `None` is the role `muted`), `""` for none; `state`
  one of Theme's states or `None` (`"disabled"` for an option that cannot be
  chosen); `id` its own tag.
- `Select(options=(), *, open=False, cursor=None, chosen=None, offset=0, label="",
  placeholder="", disabled=False, focused=None, id=None, size=None, anchor=None,
  scope=None, surface=False)`:
  - `options`: a tuple of `Option`.
  - `open`: `False` draws the face, `True` the menu.
  - `cursor`: `None` or an index into `options`: the menu's cursor row.
  - `chosen`: `None` or an index into `options`: the current choice.
  - `offset`: an `int >= 0`, the menu's first row (List's window rules).
  - `label`: styled text, the face's key (the Controls package's key; `""` for none).
    The menu draws no label.
  - `placeholder`: styled text the face shows in role `muted` when `chosen` is
    `None`.
  - `disabled`: a `bool`: the face's text is drawn dim.
  - `focused`: `None` (ask `ctx.is_focused(id)`), `True` or `False`.

The face (`open=False`), on row `R.y` of `rect` `R`, with `f` the focus: the key
prefix (`P` cells, the mark cell in it) and the field from `R.x + P`, `F` cells: the
chosen option's label (or the placeholder) from the field's start, cut with the
ellipsis to `F - 2` cells (drawn only when `F >= 3`), and `ctx.glyph("twisty.closed")`
(▸) in role `muted` in the row's last cell (when `F >= 1`), ground between. States:
disabled (`"text"`, over the label's cells), hover (`ctx.is_hovered(id)`, `"row"`),
focused (`"row"`), in that order, the row extent being every cell of the row in the
clip (the key included). The mark cell: focused's `›`, else hover's, else blank (or
the leader). Hits: `(Hit(clip, id),)` when `id` is not `None`, else `()`.

The menu (`open=True`): List's rows over `options` (the source a tuple, `window(offset,
len(options), R.h)`, no `follow`), each row the two gutter cells, the label from
`R.x + 2`, and the hint, when not empty, right-aligned so its last cell is the row's
last; the label is cut with the ellipsis to the room left before the hint and one
ground cell (`R.w - 2 - width(hint) - 1`), and when even a one-cell label does not
fit the hint is dropped and the label takes the row. The gutter, as List's: cell 0
the focused mark when the row is focused (`i == cursor` and `f`, or
`ctx.is_focused(option.id)`), else hover's; cell 1 `•` (mark.selected) when `i ==
chosen`, else the option's own state's mark. States stacked as List's: the option's
state, chosen (applied as `"selected"`), hover (`ctx.is_hovered(option.id)` or
`(id, "option", i)`), focused. The indicator row as List's. Hits: `Hit(clip, id)`
when `id` is not `None`; then each drawn row, `Hit(Rect(R.x, y, R.w, 1) ∩ clip,
tag)` with `tag = option.id` when that is not `None`, else `(id, "option", i)` when
`id` is not `None`; then the indicator's `(id, "more")`.

Painting (`paint(rect, ctx, grid, clip=None)`), `g = ctx.ground()`: the clip's
ground, the face or the menu, `shade(grid, clip, bg=g.style.bg)`.

Measuring: the face: `"x"`: `P + max(width of every option's label and of the
placeholder) + 2` (so the face does not jump as the choice changes), `"y"`: `1`;
the menu: `"x"`: `2 + max(width(label) + (1 + width(hint) if hint else 0))` over the
options (`0` with none), `"y"`: `len(options)`.

The zone (`zone(ctx) -> int`, PropertyList's signature and rule, so Paint gathers it
from a parent's children as it gathers a PropertyList's): the key zone the face aligns
at, `Z` of the Controls package's key: with a non-empty `label` and `open=False`,
`measure((label,))` (Text's: `1 + width(label)`, one leader cell before the key, as a
PropertyList's `1 + widest key`), or `max(ctx.zone, that)` when `ctx.zone` is not
`None`; with an empty `label`, or `open=True` (the menu draws no label), it adds
nothing: `measure(())` (`1`, Text's for no keys, as a PropertyList with no items
gives), or `ctx.zone` when that is not `None`. It is never below `ctx.zone` and
never below `1` (a {Context}'s zone is an `int >= 1`). `paint` keys the face at
`zone(ctx)`, so under Paint's pushed zone `Z'` (the siblings' max) it aligns at
exactly `Z'`.

Law (aligned): for a column of nodes, each a labelled Select face, a labelled
TextInput or a PropertyList, painted at one `R.x` with `ctx.zone = max(n.zone(ctx0)
for n in the column)` (what Paint pushes to siblings), every key row puts its
separator's `:` at column `R.x + Z` and its value or field from `R.x + Z + 2`
(whenever the row is wide enough that a PropertyList's leaders do not shrink and a
control's prefix is not cut). With `ctx.zone == 11` (a PropertyList with key
`identifier`) at width 22: `"-------Size: Medium  ▸"` (this face, `L = 7`),
`"-------Name: hello    "` (a TextInput), `"-identifier: 42       "`; the `:` at
column 11 in all three.

Exact cells (the builtin theme; labels in `ctx.style("text")`, hints and the
twisty in `ctx.style("muted")`), with `opts = (Option("Small"), Option("Medium",
hint="m"), Option("Large", state="disabled"))`:
- `Select(opts, open=True, cursor=1, chosen=0, id="s")` at `Rect(0, 0, 12, 3)`
  with `ctx.focus == "s"`: `" •Small     "` (selected), `"› Medium   m"` (focused),
  `"  Large     "` (`Large` dim); hits `Hit(Rect(0, 0, 12, 3), "s")`, then
  `Hit(Rect(0, i, 12, 1), ("s", "option", i))` for `i` in 0, 1, 2.
- `cursor=0` there: `"›•Small     "` (the cursor and the choice on one row).
- `Select(opts, chosen=1, id="s")` at `Rect(0, 0, 12, 1)`: `" Medium    ▸"`; hits
  `(Hit(Rect(0, 0, 12, 1), "s"),)`; focused: `"›Medium    ▸"`, every cell focused.
- `Select(opts, chosen=1, label="Size")` at width 16 (`Z = 5`, `L = 1`, `P = 7`):
  `"-Size: Medium  ▸"`; with `ctx.zone == 8` (`Z = 8`, `L = 4`, `P = 10`, `F = 6`:
  the label cut to 4, then a blank and the twisty): `"----Size: Med… ▸"`; focused,
  the leader's last cell is the mark: `"›Size: Medium  ▸"` and `"---›Size: Med… ▸"`.
- `Select(opts, placeholder="pick")` at width 8: `" pick  ▸"`, `pick` muted.
- `measure("x", 0, ctx) == 9` for the face (`1 + 6 + 2`), `10` for the menu (`2 +
  6 + 1 + 1`).

Errors: construction: `TypeError` when `options` is not a tuple of `Option`, a
  `label`, `hint` or `placeholder` is neither a `str` nor a `Line`, `state` is
  neither `None` nor a `str`, `open` / `disabled` / `surface` is not a `bool`,
  `cursor` / `chosen` is not `None` or an int, `offset` is not an int (a `bool`
  included each time), `focused` is not `None` or a `bool`, or an `id` is
  unhashable; `ValueError` when `state` is not one of the states, `cursor` or
  `chosen` is outside `range(len(options))`, or `offset` is negative. `measure` /
  `paint`: as the protocol states.
Through the family (Q9c): the key row (`_key`, `_prefix`) and the indicator
(`_indicator`) are the Controls toolkit's (`button.py`'s toolkit section, the
package's stated key and List's indicator), never Button's own; the menu window is
Select's own `_window(offset, n, h) -> (first, shown)` in this module: with `cap =
max(h - 1, 0)`, `(0, n)` when `n <= h`, else `first = min(offset, n - cap)` and
`shown = min(cap, n - first)` (List's `window` with no follow; Controls may not import
Collections). Pure; its inputs are checked at construction (`offset >= 0`); no errors.
Effects: none, apart from `paint`'s writes into the grid it is given.

Usage:
    from cure.core.buffer import Grid, text
    from cure.core.geometry import Rect
    from cure.draw.context import Context
    from cure.draw.theme import builtin
    from cure.draw.widgets.controls import Option, Select
    opts = (Option("Small"), Option("Medium", hint="m"), Option("Large"))
    ctx = Context.of(builtin(), focus="s")
    g = Grid(12, 3)
    Select(opts, open=True, cursor=1, chosen=0, id="s").paint(Rect(0, 0, 12, 3), ctx, g)
    text(g)                      # " •Small\\n› Medium   m\\n  Large"
    Select(opts, label="Size").zone(ctx)            # 5: 1 + width("Size")
    Select(opts, label="Size").zone(Context.of(builtin(), zone=11))   # 11
    Select(opts).zone(ctx)                          # 1: no label adds nothing
"""

from collections.abc import Hashable
from dataclasses import KW_ONLY, dataclass

from cure.core.buffer import Grid
from cure.core.geometry import Hit, Rect
from cure.core.text import Line, measure

from .button import (_begin, _check_common, _check_flag, _check_id, _check_int, _check_measure,
                     _check_state, _check_text, _fitted, _focus, _ground, _hit, _indicator,
                     _is_int, _key, _mark, _plain, _plain_of, _prefix, _put, _restyle, _shade,
                     _styled, _Styler, _width)

_GUTTER = 2


def _window(offset: int, n: int, h: int) -> "tuple[int, int]":
    """Select's menu window (List's with no follow): `(first, shown)` of `n` rows in
    `h` cell rows."""
    if n <= h:
        return 0, n
    cap = max(h - 1, 0)
    first = min(offset, n - cap)
    return first, min(cap, n - first)


@dataclass(frozen=True)
class Option:
    """One choice: a label, a hint, a state, an id (see the module)."""

    label: "str | Line"
    _: KW_ONLY
    hint: "str | Line" = ""
    state: "str | None" = None
    id: Hashable = None

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _check_text("label", self.label)
        _check_text("hint", self.hint)
        _check_state(self.state)
        _check_id("id", self.id)


@dataclass(frozen=True)
class Select:
    """A choice among options: a dropdown's face, or the open menu (see the module)."""

    options: tuple = ()
    _: KW_ONLY
    open: bool = False
    cursor: "int | None" = None
    chosen: "int | None" = None
    offset: int = 0
    label: "str | Line" = ""
    placeholder: "str | Line" = ""
    disabled: bool = False
    focused: "bool | None" = None
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = False

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        if not isinstance(self.options, tuple) or not all(
                isinstance(o, Option) for o in self.options):
            raise TypeError("options must be a tuple of Option")
        _check_flag("open", self.open)
        _check_flag("disabled", self.disabled)
        _check_flag("focused", self.focused, none=True)
        for name in ("cursor", "chosen"):
            value = getattr(self, name)
            if value is not None and not _is_int(value):
                raise TypeError(f"{name} must be None or an int, got {type(value).__name__}")
        _check_int("offset", self.offset)
        _check_text("label", self.label)
        _check_text("placeholder", self.placeholder)
        _check_common(self)
        n = len(self.options)
        for name in ("cursor", "chosen"):
            value = getattr(self, name)
            if value is not None and not 0 <= value < n:
                raise ValueError(f"{name} {value} is outside range({n})")

    def chrome(self) -> None:
        """None: no insets."""
        return None

    def lifts(self, ctx: object) -> bool:
        """Always False."""
        return False

    def zone(self, ctx: object) -> int:
        """The key zone: Text's `measure` of the face's label (none when open or unlabelled),
        at least `ctx.zone` (see the module)."""
        keyed = not self.open and _plain_of(self.label) != ""
        z = measure((self.label,) if keyed else ())
        return z if ctx.zone is None else max(ctx.zone, z)

    def measure(self, axis: str, room: int, ctx: object, content: int = 0) -> int:
        """The face's or the menu's natural size (see the module)."""
        _check_measure(axis, room, content)
        if self.open:
            if axis == "y":
                return len(self.options)
            return max((_GUTTER + _width(o.label) + (1 + _width(o.hint) if _plain_of(o.hint) else 0)
                        for o in self.options), default=0)
        if axis == "y":
            return 1
        P, _ = _prefix(self.label, ctx)
        widest = max([_width(o.label) for o in self.options] + [_width(self.placeholder)])
        return P + widest + 2

    def paint(self, rect: Rect, ctx: object, grid: Grid, clip: "Rect | None" = None
              ) -> "tuple[Hit, ...]":
        """The face or the menu into `grid` (see the module)."""
        begun = _begin(rect, grid, clip)
        if begun is None:
            return ()
        clip, area = begun
        g = ctx.ground()
        _ground(grid, area, g.style)
        if self.open:
            hits = self._menu(rect, ctx, grid, area, clip, g.style)
        else:
            self._face(rect, ctx, grid, area)
            hits = [] if self.id is None else [Hit(clip, self.id)]
        _shade(grid, area, g.style)
        return tuple(hits)

    def _face(self, R: Rect, ctx: object, grid: Grid, area: Rect) -> None:
        """The closed face on row `R.y`: the key, the choice, the twisty, the states."""
        y = R.y
        P, mx, mstyle = _key(self.label, ctx, R, y, grid, area)
        F = max(0, R.w - P)
        x = R.x + P
        texts = []
        if F >= 3:
            if self.chosen is not None:
                text = _styled(self.options[self.chosen].label, ctx, "text")
            else:
                text = _styled(self.placeholder, ctx, "muted")
            line = _fitted(text, F - 2, ctx)
            _put(grid, x, y, line, area)
            if line.width:
                texts.append((x, x + line.width))
        if F >= 1:
            _put(grid, R.right - 1, y, _plain(ctx.glyph("twisty.closed"), ctx.style("muted")), area)
        st = _Styler(ctx)
        hovered, focused = ctx.is_hovered(self.id), _focus(self, ctx)
        for state, on in (("focused", focused), ("hover", hovered)):
            if on and st.treat(state).mark:
                _mark(grid, mx, y, area, st.treat(state).mark, mstyle, R)
                break
        if self.disabled:
            for x0, x1 in texts:
                _restyle(grid, x0, x1, y, area, st.apply("disabled"))
        for state, on in (("hover", hovered), ("focused", focused)):
            if on:
                _restyle(grid, R.x, R.right, y, area, st.apply(state))

    def _menu(self, R: Rect, ctx: object, grid: Grid, area: Rect, clip: Rect,
              ground: object) -> "list[Hit]":
        """The open menu: List's rows over the options, the indicator; its hits."""
        hits = [] if self.id is None else [Hit(clip, self.id)]
        n = len(self.options)
        first, shown = _window(self.offset, n, R.h)
        f = _focus(self, ctx)
        st = _Styler(ctx)
        for k in range(shown):
            i = first + k
            o = self.options[i]
            y = R.y + k
            if area.y <= y < area.bottom:
                texts = self._option(o, R, y, ctx, grid, area)
                own = o.state
                sel = i == self.chosen or own == "selected"
                hov = (ctx.is_hovered(o.id) or own == "hover"
                       or (self.id is not None and ctx.is_hovered((self.id, "option", i))))
                foc = (i == self.cursor and f) or ctx.is_focused(o.id) or own == "focused"
                _option_states(st, grid, R, y, area, ground, own, sel, hov, foc, texts)
            tag = o.id if o.id is not None else ((self.id, "option", i) if self.id is not None else None)
            if tag is not None:
                hit = _hit(Rect(R.x, y, R.w, 1), clip, tag)
                if hit is not None:
                    hits.append(hit)
        if n > R.h >= 1:
            y = R.y + R.h - 1
            _indicator(grid, R, y, area, ctx, first, n - first - shown)
            if self.id is not None:
                hit = _hit(Rect(R.x, y, R.w, 1), clip, (self.id, "more"))
                if hit is not None:
                    hits.append(hit)
        return hits

    def _option(self, o: Option, R: Rect, y: int, ctx: object, grid: Grid, area: Rect
                ) -> "list[tuple[int, int]]":
        """One option's label and hint; the label's cells as its text extent."""
        label = _styled(o.label, ctx, "text")
        hint = _styled(o.hint, ctx, "muted") if _plain_of(o.hint) else Line()
        room = R.w - _GUTTER
        if hint.width:
            beside = R.w - _GUTTER - hint.width - 1
            if beside >= 1:
                room = beside
                _put(grid, R.right - hint.width, y, hint, area)
        line = _fitted(label, room, ctx)
        x = R.x + _GUTTER
        _put(grid, x, y, line, area)
        return [(x, x + line.width)] if line.width else []


def _option_states(st: _Styler, grid: Grid, R: Rect, y: int, area: Rect, ground: object,
                   own: "str | None", selected: bool, hovered: bool, focused: bool,
                   texts: "list[tuple[int, int]]") -> None:
    """A menu row's two gutter marks (List's), then its states over their extents in
    the order own state, chosen (as selected), hover, focused (none applied twice)."""
    m0 = st.treat("focused").mark if focused else (st.treat("hover").mark if hovered else "")
    if selected:
        m1 = st.treat("selected").mark
    elif own is not None and own not in ("focused", "hover"):
        m1 = st.treat(own).mark
    else:
        m1 = ""
    _mark(grid, R.x, y, area, m0, ground, R)
    _mark(grid, R.x + 1, y, area, m1, ground, R)
    order = []
    for state, on in ((own, own is not None), ("selected", selected), ("hover", hovered),
                      ("focused", focused)):
        if on and state not in order:
            order.append(state)
    for state in order:
        how = st.apply(state)
        if st.treat(state).extent == "row":
            _restyle(grid, R.x, R.right, y, area, how)
        else:
            for x0, x1 in texts:
                _restyle(grid, x0, x1, y, area, how)
