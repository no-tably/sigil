"""[States]: focused, selected, hover, pressed, active, emphasised, muted, disabled:
style + extent (cell, text, row) + an optional mark.

Kind: service (a data class and pure functions).

What it does: `treat` gives a widget the {Treatment} for a visual state: the style to
lay over the cells, how far it runs, and the mark to add. A highlight changes the
background or the text colour; a mark only adds, so the screen still reads with
colour off (Rules carried over). `apply` lays a treatment's style over a base style,
only ever adding. `border` gives a box's border style: receded at rest, full on focus.

The states (`STATES`) and what each gets. The style is the theme's role
`state.<name>` when `roles.styles` has exactly that key (no fallback chain: a theme's
`default` role never stands in for a state), else the built-in default below; then
the state's FLOOR flags are turned on whatever the theme says; the mark is the
charset's `glyph(f"mark.<name>")` (`""` when the state has no mark):

| state | extent | built-in style | floor | mark token |
| --- | --- | --- | --- | --- |
| focused | row | reverse | — | `mark.focused` (›) |
| selected | row | reverse, dim | reverse | `mark.selected` (•) |
| hover | row | underline | underline | — |
| pressed | row | reverse, bold | bold | `mark.pressed` (●) |
| active | text | bold | bold | `mark.active` (●) |
| emphasised | text | bold | bold | `mark.emphasised` (✦) |
| muted | text | dim | dim | `mark.muted` (·) |
| disabled | text | dim | dim | — |

Why these floors. Each floor is the state's non-colour cue where a widget has no
reserved mark cell to show it: `selected`'s `reverse` is the conventional text-selection
cue, so a selection with no mark cell (TextInput's selected text, a text-extent
selection) still reads with colour off. `focused` has no floor: its mark (›) and the
text cursor carry it.

Focused and selected at once. A row that is both gets both treatments applied (in the
widget's order; `apply` ORs flags, so `reverse` stays on either way, and the colours of
the one applied last win). Under the built-in styles that is one `reverse` (a flag, not
a toggle: two reverses are still one). Under a theme whose `state.focused` sets a
background, the selected floor's `reverse` swaps fg and bg on that row: the focus
background is drawn as the text colour and the row's text colour as the background.
That is the intended result: the row reads as selected (reversed) and as focused (the
focus colour and the › mark), and it reads with colour off by its reverse and its mark.

Extents (`EXTENTS`): `row` runs the full row (cursor and selection, Rules carried
over), `text` covers only the text, `cell` one cell (for a treatment the caller asks
for with `extent="cell"`, such as a text cursor). `treat(..., extent=...)` overrides
the table's extent. A mark goes in a cell reserved for it (the key:value row's last
leader cell; a list's gutter): the widget places it, never over text.

Applying (`apply(base, t) -> Style`), with o = `t.style`: `fg` = o.fg when not None
else base.fg; the same for `bg` and `underline_colour`; `underline` = o.underline when
not None else base.underline; each of `bold`, `dim`, `italic`, `strike`, `reverse` =
base's OR o's; `link` = base.link. `base` may be `None` (taken as `Style()`).

Invariant: additive — a treatment only adds: for every base style b and treatment t,
  `apply(b, t)` keeps every flag b has on, keeps every colour and underline b has
  unless t replaces it with another (it is never cleared to None), changes nothing
  else, and is idempotent (`apply(apply(b, t), t) == apply(b, t)`); and every
  treatment `treat` gives carries a non-colour cue, a non-empty mark or a floor flag
  that is on in its style (every floor flag in the table is on in the style, whatever
  the theme's role says; `selected` carries both), so with colour off (depth 0, where Sgr still sends
  flags) a treated state still reads.

Borders (`border(roles, focused) -> Style`): `style_of(roles, "border.focus")` when
`focused` (falling back to `border`, then `default`), else `style_of(roles,
"border")`. Borders recede toward the ground at rest and come up to full on focus: the
theme declares both (the builtin's `border` is its dim colour, `border.focus` its
accent).

Data (frozen dataclass; immutable all the way down, Theme's rule):
- `Treatment(state: str, style: Style, extent: str, mark: str = "")`. No container
  field; hashable, as today.
- `TABLE` (read by `treat` at call time) is a read-only `types.MappingProxyType`,
  its contents as today.

Inputs: `treat`: {Roles}, `state` in `STATES`, a {Charset} (its `glyph` is called),
  `extent` (keyword only) None or one of `EXTENTS`. `apply`: a {Style} or None, a
  {Treatment}. `border`: {Roles}, `focused: bool`.
Outputs: `treat`: a {Treatment}. `apply`, `border`: a {Style}.
Errors: `ValueError` when `state` is not in `STATES` or `extent` not in `EXTENTS` (state
  names are code, not theme data); `TypeError` when `base` is neither a `Style` nor
  None, or `t` is not a `Treatment`.
Effects: none.

Usage:
    from cure.core.style import Style, resolve
    from cure.draw.theme.charset import glyphs
    from cure.draw.theme.roles import Roles
    from cure.draw.theme.states import treat, apply
    t = treat(Roles(), "focused", glyphs())
    t.extent, t.mark, t.style        # "row", "›", Style(reverse=True)
    apply(Style(bold=True, fg=resolve("red")), t)   # Style(fg=red, bold=True, reverse=True)
    treat(Roles(), "disabled", glyphs()).style       # Style(dim=True)
    treat(Roles(styles={"state.selected": Style(bg=resolve("blue"))}), "selected",
          glyphs()).style                            # Style(bg=blue, reverse=True): the floor
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

from cure.core.style import Style

from .roles import Roles, style_of

STATES: tuple[str, ...] = ("focused", "selected", "hover", "pressed", "active", "emphasised", "muted", "disabled")
"""The visual states a widget asks a treatment for."""

EXTENTS: tuple[str, ...] = ("cell", "text", "row")
"""How far a treatment runs."""

TABLE: Mapping = MappingProxyType({
    # state: (extent, built-in style flags, floor flags, mark token or None)
    "focused": ("row", ("reverse",), (), "mark.focused"),
    "selected": ("row", ("reverse", "dim"), ("reverse",), "mark.selected"),
    "hover": ("row", ("underline",), ("underline",), None),
    "pressed": ("row", ("reverse", "bold"), ("bold",), "mark.pressed"),
    "active": ("text", ("bold",), ("bold",), "mark.active"),
    "emphasised": ("text", ("bold",), ("bold",), "mark.emphasised"),
    "muted": ("text", ("dim",), ("dim",), "mark.muted"),
    "disabled": ("text", ("dim",), ("dim",), None),
})
"""The table above as data: `underline` in a flags tuple means `underline="single"`."""


@dataclass(frozen=True)
class Treatment:
    """{Treatment}: a state's style, its extent, and the mark it adds ("" for none)."""

    state: str
    style: Style
    extent: str
    mark: str = ""


def treat(roles: Roles, state: str, charset: object, *, extent: "str | None" = None) -> Treatment:
    """The {Treatment} of `state` (see the table)."""
    if state not in STATES:
        raise ValueError(f"state must be one of {STATES}, got {state!r}")
    if extent is not None and extent not in EXTENTS:
        raise ValueError(f"extent must be None or one of {EXTENTS}, got {extent!r}")
    table_extent, built_in, floor, token = TABLE[state]
    s = roles.styles.get(f"state.{state}")
    if s is None:
        s = Style(**_flags(built_in))
    s = replace(s, **{k: v for k, v in _flags(floor).items() if getattr(s, k) in (False, None)})
    mark = charset.glyph(token) if token else ""
    return Treatment(state, s, extent or table_extent, mark)


def apply(base: "Style | None", t: Treatment) -> Style:
    """`t`'s style laid over `base`, only adding (see Applying)."""
    if base is None:
        base = Style()
    if not isinstance(base, Style):
        raise TypeError(f"base must be a Style or None, got {type(base).__name__}")
    if not isinstance(t, Treatment):
        raise TypeError(f"expected a Treatment, got {type(t).__name__}")
    o = t.style
    return Style(
        fg=_either(o.fg, base.fg), bg=_either(o.bg, base.bg),
        bold=base.bold or o.bold, dim=base.dim or o.dim, italic=base.italic or o.italic,
        underline=_either(o.underline, base.underline),
        underline_colour=_either(o.underline_colour, base.underline_colour),
        strike=base.strike or o.strike, reverse=base.reverse or o.reverse, link=base.link)


def border(roles: Roles, focused: bool) -> Style:
    """A border's style: `border.focus` when focused, else `border`."""
    return style_of(roles, "border.focus" if focused else "border")


def _flags(names: tuple) -> dict:
    """Style keyword arguments turning `names` on (`underline` is a single underline)."""
    return {n: "single" if n == "underline" else True for n in names}


def _either(over: object, base: object) -> object:
    return over if over is not None else base
