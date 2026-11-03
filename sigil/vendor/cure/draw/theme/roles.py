"""[Roles]: an open, dotted role set: a widget asks for list.item.selected, which falls
back up the dots; an unknown role degrades, never fails.

Kind: service (a data class and pure functions).

What it does: `resolve` turns a {Raw}'s role leaves into {Roles}: for each role, the
{Style} its value describes, built by Style's `style({Spec})` so every colour carries
the role's name as its theme role. `style_of` answers a role by the fallback chain.
The set is open: a theme may declare any role, a widget may ask for any role, and a
role nobody declared gets the nearest declared ancestor's style, or `default`'s, or
the plain `Style()`.

Which leaves are roles. Every leaf of the Raw whose first path segment is not in
`RESERVED` (`name`, `label`, `type`, `extends`, `palette`, `charset`, `ramp`,
`derive`: read by Theme, [Parse], [Charset], [Ramp] and [Derive]) is a role, named
by its path joined with dots: `ui:` / `  text: $fg` is the role `ui.text`, and so is
a top-level `ui.text: $fg`. Leaves are taken in the Raw's order.

A role's value (the style grammar). The value is split on spaces into tokens
(`str.split()`); then, in this order:

1. every token starting with `$` is a palette reference, resolved by [Parse]'s
   `ref` against `palette(raw)`; a bad or unknown reference is a `ThemeError` at the
   leaf's source and line (a typo in a reference fails loudly, as sigil's did);
2. the tokens are read as `[fg] ["on" bg] {flag}`: an optional first token that is
   neither `"on"` nor a flag is the foreground; then optionally `"on"` followed by
   the background; then zero or more flags from `FLAGS` (`bold`, `dim`, `italic`,
   `underline` (single), `strike`, `reverse`), each at most once. A colour token is
   a resolved reference (an `Ink` or a literal str) or a literal Style's `resolve`
   takes with no inks (`red`, `#ff0000`, `default`, `196`);
3. the role's style is `style(Spec(fg, bg, <flags>, underline=True if "underline",
   role=<role name>))`.

So `$fg`, `$fg on $surface bold`, `on $raised`, `bold`, `red` and `""` (the plain
style: an empty value is a declared role whose style is `Style()`) are styles. A
value that does not fit (a flag twice, `on` with no colour, a token after the flags
that is not a flag, a literal that is not a colour such as `"0.22"` or `"2.2px"`, or
any value `style` refuses with `TypeError` / `ValueError`) is not an error: the role
is UNSTYLED, kept in `values` (a parameter such as sigil's `ui.fill`) and listed in
`unstyled`, and it is never a candidate of the fallback chain.

The fallback chain (`fallbacks(role) -> tuple[str, ...]`): the role itself, then each
prefix made by dropping its last dot-segment, then `"default"` (not repeated):
`fallbacks("list.item.selected") == ("list.item.selected", "list.item", "list",
"default")`, `fallbacks("default") == ("default",)`, `fallbacks("x") == ("x",
"default")`. Any `str` is accepted (an empty or odd name degrades like any unknown
role: `fallbacks("") == ("", "default")`). `style_of(roles, role)` is the style of the
first candidate in `roles.styles`, else `Style()`: never an error for a `str`.

Data (frozen dataclass; immutable all the way down, Theme's rule):
- `Roles(styles: Mapping[str, Style] = {}, values: Mapping[str, str] = {}, unstyled:
  tuple[str, ...] = (), derived: Mapping[str, Colour] = {})`: `styles`, `values` and
  `derived` are read-only (`__post_init__` stores each as a `types.MappingProxyType`
  over a private `dict` copy of the mapping given: writing raises, the caller's dict
  is not kept, `==` with a plain dict holds); `unstyled` is stored as a `tuple` (a
  list given becomes one). `__reduce__` rebuilds from plain dict copies (copy and
  pickle as today). Not hashable (`hash` raises `TypeError`, as today). The freezing
  and the rebuild go through [Parse]'s public `freeze_maps(self, "styles", "values",
  "derived")`, `freeze_seqs(self, "unstyled")` and `rebuild(self)` (Q9b: never
  Parse's private `_freeze`, `_tuples`, `_reduce`). `resolve`,
  `overlay` and Derive's `derive_all` build new dicts and a new Roles (`replace`
  copies and wraps again); none writes a Roles' own mapping.
  - `styles`: role name -> Style, for every styled role, in leaf order;
  - `values`: role name -> its value as written (references unresolved), for EVERY
    role, styled or not;
  - `unstyled`: the names of the roles that are not styles, in leaf order;
  - `derived`: `"kind:role"` -> the derived {Colour} ([Derive] fills it at theme
    load; `resolve` leaves it empty).
  `Roles()` is the empty set (every role answers `Style()`).

Overlay (`overlay(base, over) -> Roles`): `over`'s entries win role by role: styles,
values and derived are `{**base.x, **over.x}`; `unstyled` is base's names that are
not roles of `over`, then over's, in order. (A role styled in base and unstyled in
over is unstyled in the result.)

Inputs: `resolve`: a {Raw}. `fallbacks`: `role: str`. `style_of`: {Roles}, `role:
  str`. `overlay`: two {Roles}.
Outputs: `resolve`: {Roles}. `fallbacks`: a tuple of `str`. `style_of`: a {Style}.
  `overlay`: {Roles}.
Errors: `resolve`: `ThemeError` from [Parse]'s `palette` and `ref` (bad palette,
  bad or unknown reference); never for a value that is merely not a style.
  `fallbacks` / `style_of`: `TypeError` when `role` is not a `str`.
Effects: none.

Usage:
    from cure.draw.theme.parse import parse
    from cure.draw.theme.roles import resolve, style_of, fallbacks
    raw = parse("palette:\\n  fg: \\"#c9d1d9\\"\\n  bar: \\"#161b22\\"\\n"
                "default: $fg\\nlist.item: $fg on $bar bold\\nui.fill: \\"0.22\\"\\n", "t")
    roles = resolve(raw)
    style_of(roles, "list.item.selected")    # list.item's style: falls back up the dots
    style_of(roles, "list.item").fg          # Colour("rgb", (201, 209, 217), "list.item")
    style_of(roles, "nowhere").fg.role       # "default"
    roles.unstyled, roles.values["ui.fill"]  # ("ui.fill",), "0.22"
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from cure.core.style import Colour, Spec, Style, style

from .parse import Raw, freeze_maps, freeze_seqs, palette, rebuild, ref

RESERVED: tuple[str, ...] = ("name", "label", "type", "extends", "palette", "charset", "ramp", "derive")
"""Top-level keys that are not roles."""

FLAGS: tuple[str, ...] = ("bold", "dim", "italic", "underline", "strike", "reverse")
"""The flag words of a role's value."""

DEFAULT = "default"
"""The role every fallback chain ends at."""


@dataclass(frozen=True)
class Roles:
    """{Roles}: role -> Style, every role's written value, the unstyled ones, derived colours.

    `styles`, `values`, `derived` read-only proxies over copies, `unstyled` a tuple,
    made in `__post_init__`.
    """

    styles: Mapping = field(default_factory=dict)
    values: Mapping = field(default_factory=dict)
    unstyled: tuple = ()
    derived: Mapping = field(default_factory=dict)

    def __post_init__(self) -> None:
        freeze_maps(self, "styles", "values", "derived")
        freeze_seqs(self, "unstyled")

    def __reduce__(self):
        return rebuild(self)


def resolve(raw: Raw) -> Roles:
    """The {Roles} of a {Raw}'s role leaves (see the module)."""
    entries = palette(raw)
    styles, values, unstyled = {}, {}, []
    for path, value in raw.leaves.items():
        if path[0] in RESERVED:
            continue
        name = ".".join(path)
        values[name] = value
        tokens = [ref(entries, t, raw.lines[path]) if t.startswith("$") else t for t in value.split()]
        s = _style(tokens, name)
        if s is None:
            unstyled.append(name)
        else:
            styles[name] = s
    return Roles(styles, values, tuple(unstyled))


def fallbacks(role: str) -> tuple[str, ...]:
    """The fallback chain of `role`: itself, its dot-prefixes, then "default"."""
    if not isinstance(role, str):
        raise TypeError(f"role must be a str, got {type(role).__name__}")
    chain = [role]
    while "." in chain[-1]:
        chain.append(chain[-1].rsplit(".", 1)[0])
    if chain[-1] != DEFAULT:
        chain.append(DEFAULT)
    return tuple(chain)


def style_of(roles: Roles, role: str) -> Style:
    """The style of the first candidate of `fallbacks(role)` in `roles.styles`, else Style()."""
    for candidate in fallbacks(role):
        if candidate in roles.styles:
            return roles.styles[candidate]
    return Style()


def overlay(base: Roles, over: Roles) -> Roles:
    """`over`'s roles laid on `base`'s, role by role (see Overlay)."""
    named = set(over.values) | set(over.styles) | set(over.unstyled)
    styles = {**base.styles, **over.styles}
    for name in over.unstyled:
        styles.pop(name, None)
    unstyled = tuple(n for n in base.unstyled if n not in named) + tuple(over.unstyled)
    return Roles(styles, {**base.values, **over.values}, unstyled, {**base.derived, **over.derived})


def _style(tokens: list, role: str) -> "Style | None":
    """The style `[fg] ["on" bg] {flag}` describes, or None when the tokens do not fit."""
    fg = bg = None
    i = 0
    if i < len(tokens) and tokens[i] != "on" and tokens[i] not in FLAGS:
        fg, i = tokens[i], i + 1
    if i < len(tokens) and tokens[i] == "on":
        if i + 1 == len(tokens):
            return None
        bg, i = tokens[i + 1], i + 2
    flags = tokens[i:]
    if any(f not in FLAGS for f in flags) or len(set(flags)) != len(flags):
        return None
    spec = Spec(fg, bg, bold="bold" in flags, dim="dim" in flags, italic="italic" in flags,
                underline=True if "underline" in flags else None, strike="strike" in flags,
                reverse="reverse" in flags, role=role)
    try:
        return style(spec)
    except (TypeError, ValueError):
        return None
