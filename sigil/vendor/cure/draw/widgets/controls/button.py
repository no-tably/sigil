"""[Button]: buttons, toggles, radios, switches.

Kind: service (a frozen dataclass node kind, `Button`, one class for the four kinds;
see the Widgets package's protocol and the Controls package's shared rules: the
mark cell, the states, the hits).

What it does: one row: the mark cell, then the control's face, a label in a frame
that says what it is, readable with colour off: a button `[ OK ]`, a toggle (a
check box) `[•] Wrap`, a radio `(●) One`, a switch `[─●] Dark`. Whether it is on,
pressed or disabled is the app's (its fields); a radio group is the app's too (one
`Button(kind="radio")` per choice, the app turning the others off). A click hits
the control; the app's router fires its action.

Data (frozen dataclass; checked on construction):
- `Button(label="", *, kind="button", on=False, pressed=False, disabled=False,
  focused=None, id=None, size=None, anchor=None, scope=None, surface=False)`:
  - `label`: styled text (span style `None` is the role `text`).
  - `kind`: one of `KINDS`: `"button"`, `"toggle"`, `"radio"`, `"switch"`.
  - `on`: a `bool`: a toggle, radio or switch is on; a button with `on=True` is
    latched (drawn active).
  - `pressed`: a `bool`, held down now (the app sets it between press and release).
  - `disabled`: a `bool`: drawn dim (it still records its hit; the app ignores it).
  - `focused`: `None` (ask `ctx.is_focused(id)`), `True` or `False`.
- `KINDS = ("button", "toggle", "radio", "switch")`.

The face, `prefix + label + suffix`, from the control tokens (Charset's; W1a), with
`check = ctx.glyph("control.check")` (•), `radio = ctx.glyph("control.radio")` (●),
`knob = ctx.glyph("control.knob")` (●), `track = ctx.glyph("control.track")` (─):
- `"button"`: prefix `"[ "`, suffix `" ]"`;
- `"toggle"`: prefix `"[" + (check if on else " ") + "] "`, no suffix;
- `"radio"`: prefix `"(" + (radio if on else " ") + ") "`, no suffix;
- `"switch"`: prefix `"[" + (track + knob if on else knob + track) + "] "`, no
  suffix (the knob right when on, left when off).
The brackets, parentheses, their inner blanks (an off toggle's or radio's blank
included) and the switch's `track` in role `control.frame`; the on glyph (`check`,
`radio`, the switch's `knob` on or off) in role `control.on`; the label in its own
styles. Button asks for no other glyph or role for its face (`mark.*`,
`border.light.h`, `muted` and `accent` no longer reach it), so a theme's
`charset.control.radio` changes a radio's on glyph and nothing else, and a theme's
`control.on` restyles the on glyphs of all three kinds without moving `accent`. A
face of width `fw` and a control of `c = 1 + fw` cells (the mark cell first).

The law (W1a, unchanged frames): at the builtin theme, in both charsets (`builtin()`
and `builtin(ascii=True)`) and at every colour depth (off, 16, 256, truecolour),
every Button frame (every kind, on and off, pressed, disabled, focused, hovered,
latched, every width from 0 past `c`, every clip) is cell for cell the frame of the
code before W1a: the same glyph, width and style in every cell, and the same text and
rendered bytes, the one difference being the role tag of a colour (Roles: every
colour carries its role's name), which names `control.frame` where it named `muted`
and `control.on` where it named `accent`. The builtin's tokens equal the glyphs
drawn before (`mark.selected`, `mark.active`, `mark.active`, `border.light.h`) and its
two roles are `$muted` and `$accent`. So are the measures and the hits. The oracle
is the code of the commit before W1a, loaded from git at test time
(`tests/_gitref.py`), never a frozen copy.

Fitting, on `rect` `R` (row `R.y`): when `R.w >= c` the face is drawn whole from
`R.x + 1` and the rest of the row is ground; otherwise the label is cut with
`ctx.glyph("ellipsis")` to `R.w - 1 - width(prefix) - width(suffix)` cells when that
is at least 1, and with less room the face is cut plainly (no ellipsis) to `R.w - 1`.
The control's cells are the mark cell and the face as drawn: `Rect(R.x, R.y,
min(R.w, c), 1)`.

The states, stacked in the order disabled, active (`kind == "button"` and `on`),
pressed, hover (`ctx.is_hovered(id)`), focused (`focused` if not `None`, else
`ctx.is_focused(id)`), each over its extent: `"text"` (disabled, active) over the
label's cells only; `"row"` (pressed, hover, focused) over the control's cells (not
the ground after them). The mark cell: the first non-empty mark of focused, pressed,
active, hover (`›`, `●`, `●`, none); else a blank.

Painting (`paint(rect, ctx, grid, clip=None)`), `g = ctx.ground()`: the clip's
ground, the mark cell and the face on row `R.y`, the states, `shade(grid, clip,
bg=g.style.bg)`. Rows below `R.y` stay ground. Hits: `(Hit(<the control's cells> ∩
clip, id),)` when `id` is not `None`, else `()`.

Measuring: `"x"`: `c` (`1 + width(prefix) + width(label) + width(suffix)`); `"y"`:
`1`.

Exact cells (the builtin theme, `ctx = Context.of(builtin())`; every blank in
`ctx.ground().style`):
- `Button("OK", id="ok")` at `Rect(0, 0, 8, 1)`: `" [ OK ] "`; `[` and `]` with
  their inner spaces in `ctx.style("control.frame")`, `OK` in `ctx.style("text")`; hits
  `(Hit(Rect(0, 0, 7, 1), "ok"),)`. With `ctx.focus == "ok"`: `"›[ OK ] "`, its
  seven control cells `ctx.apply(.., "focused")`, the last cell plain ground.
- `pressed=True`: `"●[ OK ] "`, the control's cells pressed (reverse, bold); with
  focus as well: `"›[ OK ] "`, pressed then focused.
- `Button("Wrap", kind="toggle", on=True)` at width 9: `" [•] Wrap"`, the `•` in
  `ctx.style("control.on")`; off: `" [ ] Wrap"`. The ASCII charset: `" [*] Wrap"`.
- `Button("One", kind="radio", on=True)`: `" (●) One"`; `Button("Dark",
  kind="switch", on=True)`: `" [─●] Dark"`, off `" [●─] Dark"`. The ASCII charset:
  `" (*) One"`, `" [-*] Dark"`, `" [*-] Dark"`.
- a theme `extends: builtin` with `charset:` / `  control.radio: "◉"`: the radio on
  `" (◉) One"`; every toggle, switch and button cell as at the builtin.
- `Button("Cancel")` at width 7 (`c = 11`): the label cut to 2: `" [ C… ]"`; at
  width 4: `" [ C"` (the face cut plainly to 3).
- `Button("OK", disabled=True)`: `" [ OK ] "`, `OK` in `ctx.apply(ctx.style("text"),
  "disabled")` (dim).
- `measure("x", 0, ctx) == 7` for `Button("OK")`, `9` for the toggle.

Errors: construction: `TypeError` when `label` is neither a `str` nor a `Line`,
  `kind` is not a `str`, `on`, `pressed`, `disabled` or `surface` is not a `bool`,
  `focused` is not `None` or a `bool`, or `id` is unhashable; `ValueError` when
  `kind` is not one of `KINDS`. `measure` / `paint`: as the protocol states.
Effects: none, apart from `paint`'s writes into the grid it is given.

The family's toolkit (this module hosts it, under its own heading below; Q9c). The
private helpers every Controls module imports (`_begin`, `_check_*`, `_ground`,
`_put`, `_styled`, `_Styler`, `_mark`, `_shade`, ...) are the family's, not Button's
face: same-system, package-internal, no spec name. Among them are two rows the Controls
package states once for Select and TextInput, which Button never draws (it has no key
and no menu); they are the family's, so Select and TextInput reach no Button name:
- the key row, as the Controls package states the key: `_prefix(label, ctx) -> (P,
  L)` the prefix width and leader count (`(1, 0)` for an empty label), and `_key(label,
  ctx, R, y, grid, area) -> (P, mark_x, mark_style)`, which draws the leaders (role
  `dim`), the label (role `muted`) and `": "` on row `y`, only inside `area`, and gives
  where the mark cell is and its style (`R.x` and the ground's style with no key);
- the indicator row, as List's (`More`'s text in role `muted`, cut to the row):
  `_indicator(grid, R, y, area, ctx, above, below) -> None`, with `_more_text(ctx,
  above, below) -> str`.
Inputs are the node's, checked at construction and by `paint`; errors: none of their
own (what `ctx` raises propagates); effects: writes into `grid` inside `area` only.
The menu window (`_window(offset, n, h) -> (first, shown)`, List's window with no
follow) is Select's alone and lives in `select.py` (Q9c), not here.

Usage:
    from cure.core.buffer import Grid, text
    from cure.core.geometry import Rect
    from cure.draw.context import Context
    from cure.draw.theme import builtin
    from cure.draw.widgets.controls import Button
    ctx = Context.of(builtin())
    g = Grid(9, 1)
    Button("Wrap", kind="toggle", on=True, id="w").paint(Rect(0, 0, 9, 1), ctx, g)
    text(g)                      # " [•] Wrap"
    Button("OK").measure("x", 0, ctx)   # 7
"""

from collections.abc import Hashable
from dataclasses import KW_ONLY, dataclass

from cure.core.buffer import Grid, fill, put, shade, write
from cure.core.geometry import Hit, Rect
from cure.core.text import Cell, Line, Span, cut, measure, width

KINDS = ("button", "toggle", "radio", "switch")
"""The kinds of Button: what its face looks like."""

_STATES = ("focused", "selected", "hover", "pressed", "active", "emphasised", "muted", "disabled")


# -- the family's toolkit: private helpers shared by Button, Select and TextInput, not
#    Button's face (Controls may not share another family's own; see the module) --

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
    return width(text) if isinstance(text, str) else text.width


def _fitted(line: Line, room: int, ctx: object) -> Line:
    """`line` cut to `room` cells with the measured ellipsis when wider."""
    if room <= 0:
        return Line()
    return cut(line, room, ellipsis=ctx.glyph("ellipsis")) if line.width > room else line


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


class _Styler:
    """`ctx.apply` and `ctx.treat`, memoised for one paint call (pure: the same
    answers, asked once)."""

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



def _plain_of(text: "str | Line") -> str:
    return text if isinstance(text, str) else text.plain


def _prefix(label: "str | Line", ctx: object) -> "tuple[int, int]":
    """The key's prefix width `P` and its leader count `L` (0: no key)."""
    if _plain_of(label) == "":
        return 1, 0
    wl = _width(label)
    Z = measure((label,))
    if ctx.zone is not None:
        Z = max(ctx.zone, Z)
    return Z + 2, Z - wl


def _key(label: "str | Line", ctx: object, R: Rect, y: int, grid: Grid, area: Rect
         ) -> "tuple[int, int, object]":
    """Draw the key on row `y` (leaders, the label, `": "`); `(P, mark x, the mark
    cell's style)`."""
    P, L = _prefix(label, ctx)
    if L == 0:
        return P, R.x, ctx.ground().style
    dim = ctx.style("dim")
    _put(grid, R.x, y, _plain(ctx.glyph("leader") * L, dim), area)
    key = _styled(label, ctx, "muted")
    _put(grid, R.x + L, y, key, area)
    _put(grid, R.x + L + key.width, y, _plain(": ", ctx.ground().style), area)
    return P, R.x + L - 1, dim


def _mark(grid: Grid, x: int, y: int, area: Rect, glyph: str, style: object, R: Rect) -> None:
    """A mark in its one reserved cell (inside the rect)."""
    if glyph and R.x <= x < R.right:
        _put(grid, x, y, _plain(glyph, style), Rect(x, y, 1, 1).intersect(area))


def _focus(node: object, ctx: object) -> bool:
    """A control's focus: its `focused` field, else the context's."""
    return node.focused if node.focused is not None else ctx.is_focused(node.id)


@dataclass(frozen=True)
class Button:
    """A button, toggle, radio or switch: a mark cell and a face (see the module)."""

    label: "str | Line" = ""
    _: KW_ONLY
    kind: str = "button"
    on: bool = False
    pressed: bool = False
    disabled: bool = False
    focused: "bool | None" = None
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = False

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _check_text("label", self.label)
        if not isinstance(self.kind, str):
            raise TypeError(f"kind must be a str, got {type(self.kind).__name__}")
        for name in ("on", "pressed", "disabled"):
            _check_flag(name, getattr(self, name))
        _check_flag("focused", self.focused, none=True)
        _check_common(self)
        if self.kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}, got {self.kind!r}")

    def chrome(self) -> None:
        """None: no insets."""
        return None

    def lifts(self, ctx: object) -> bool:
        """Always False."""
        return False

    def _parts(self, ctx: object) -> "tuple[Line, Line]":
        """The face's prefix and suffix, styled."""
        frame, on = ctx.style("control.frame"), ctx.style("control.on")
        if self.kind == "button":
            return _plain("[ ", frame), _plain(" ]", frame)
        if self.kind == "toggle":
            glyph = ctx.glyph("control.check") if self.on else " "
            return _join(_plain("[", frame), _plain(glyph, on if self.on else frame),
                         _plain("] ", frame)), Line()
        if self.kind == "radio":
            glyph = ctx.glyph("control.radio") if self.on else " "
            return _join(_plain("(", frame), _plain(glyph, on if self.on else frame),
                         _plain(") ", frame)), Line()
        track, knob = _plain(ctx.glyph("control.track"), frame), _plain(ctx.glyph("control.knob"), on)
        face = _join(track, knob) if self.on else _join(knob, track)
        return _join(_plain("[", frame), face, _plain("] ", frame)), Line()

    def measure(self, axis: str, room: int, ctx: object, content: int = 0) -> int:
        """The mark cell and the face; one row (see the module)."""
        _check_measure(axis, room, content)
        if axis == "y":
            return 1
        pre, suf = self._parts(ctx)
        return 1 + pre.width + _width(self.label) + suf.width

    def paint(self, rect: Rect, ctx: object, grid: Grid, clip: "Rect | None" = None
              ) -> "tuple[Hit, ...]":
        """The mark cell, the face and its states into `grid` (see the module)."""
        begun = _begin(rect, grid, clip)
        if begun is None:
            return ()
        clip, area = begun
        g = ctx.ground()
        _ground(grid, area, g.style)
        R, y = rect, rect.y
        pre, suf = self._parts(ctx)
        label = _styled(self.label, ctx, "text")
        c = 1 + pre.width + label.width + suf.width
        if R.w >= c:
            face = _join(pre, label, suf)
        else:
            room = R.w - 1 - pre.width - suf.width
            if room >= 1:
                label = _fitted(label, room, ctx)
                face = _join(pre, label, suf)
            else:
                face = cut(_join(pre, label, suf), max(R.w - 1, 0))
        _put(grid, R.x + 1, y, face, area)
        right = R.x + min(R.w, c)
        lx0 = R.x + 1 + pre.width
        lx1 = min(lx0 + label.width, R.x + 1 + face.width)
        st = _Styler(ctx)
        hovered, focused = ctx.is_hovered(self.id), _focus(self, ctx)
        active = self.kind == "button" and self.on
        for state, on in (("focused", focused), ("pressed", self.pressed), ("active", active),
                          ("hover", hovered)):
            if on and st.treat(state).mark:
                _mark(grid, R.x, y, area, st.treat(state).mark, g.style, R)
                break
        for state, on, extent in (("disabled", self.disabled, "text"), ("active", active, "text"),
                                  ("pressed", self.pressed, "row"), ("hover", hovered, "row"),
                                  ("focused", focused, "row")):
            if not on:
                continue
            if extent == "text":
                _restyle(grid, lx0, lx1, y, area, st.apply(state))
            else:
                _restyle(grid, R.x, right, y, area, st.apply(state))
        _shade(grid, area, g.style)
        if self.id is None:
            return ()
        hit = _hit(Rect(R.x, y, min(R.w, c), 1), clip, self.id)
        return () if hit is None else (hit,)
