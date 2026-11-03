"""[Colour]: a colour is a name or an ink, carrying the theme role it came from; this
module also holds {Colour}, the data class it builds (a shared module, spec question 1).

Kind: service ([Colour]: pure functions) and data ({Colour}: a frozen dataclass).

What it does: `resolve` turns a {Name} (a colour as a theme or an app writes it) into a
{Colour}: one of the 16 names, `default`, an index 0..255, a `#hex` value or an ink.
Every {Colour} carries `role`, the theme role it came from (`""` for none), so a web
host recolours a drawing on a theme change without redrawing it. `realize` gives the
shade a colour takes at the depth a {Caps} allows (see [Ink] for depths and shades).

Data (frozen dataclasses):
- `Name(value, role: str = "")`: a colour as written, not yet checked. `value` is a
  `str`, an `int`, an `Ink` or a `Colour`; `role` the theme role it is resolved for.
  Stored as given; `resolve` checks it.
- `Colour(form: str, value, role: str = "")`, checked on construction. `form` is one
  of `FORMS`, and `value` fits it:
  - `"default"`: `value is None` (the terminal's default colour, SGR 39 / 49 / 59);
  - `"name"`: one of `NAMES` (`"red"`, `"bright_black"`, ...);
  - `"index"`: an `int` 0..255;
  - `"rgb"`: a `tuple` of three `int`s 0..255;
  - `"ink"`: an `Ink`.
  `role` is a `str`. Equality is field by field, so two colours of the same value and
  different roles are different colours (runs of them never merge).
  `Colour.hex`: `"#rrggbb"` (lower case) for the `"rgb"` and `"ink"` forms (the ink's
  24-bit value), `None` for the others.
  `Colour.derive(kind, value)`: see role_kept below.

Resolving (`resolve(name, inks=None)`). `name` is a `Name`, or a bare value taken as
`Name(value)` (role `""`). `inks` maps ink names to `Ink`s (`None` is no inks). The
value is matched in this order; the first match wins, so an ink never shadows a
built-in form (an ink keyed `"red"` is never reached):

1. a `Colour`: returned unchanged (its own role kept; the Name's role is not applied);
2. an `Ink`: `Colour("ink", value, role)`;
3. an `int` (not a `bool`) 0..255: `Colour("index", value, role)`;
4. the `str` `"default"`: `Colour("default", None, role)`;
5. a `str` in `NAMES`: `Colour("name", value, role)`;
6. a `str` starting with `"#"`: `parse_hex(value)`, `Colour("rgb", rgb, role)`
   (`"#ABC"` gives `(170, 187, 204)`); any other `#` string is a `ValueError`;
7. a non-empty `str` of ASCII digits: its int value (leading zeros allowed, `"007"` is
   7) 0..255, `Colour("index", n, role)`;
8. a `str` that is a key of `inks`: `Colour("ink", inks[value], role)`;
9. anything else: an error (below).

Names are exact: lower case, underscores, no surrounding space (`"Red"`, `" red"` and
`"bright-red"` are errors). An unknown name is an error here; it is [Theme]'s [Roles]
that degrades an unknown role, never Style.

Realizing (`realize(colour, caps, nearest=False)`), with D = `depth_of(caps)`; the
result is a shade: `None`, an index 0..255 or an `(r, g, b)` tuple:

- D = 0: `None` for every form (no colour; attributes still draw, see [Sgr]).
- `"default"`: `None` at every depth.
- `"name"`: `NAMES.index(value)` at D >= 16.
- `"index"` i: i at D in (256, 24); at D = 16, i when i < 16, else
  `nearest16(palette_rgb(i))` when `nearest`, else `None`.
- `"rgb"`: exactly as `realize_ink(Ink("", value), caps, nearest=nearest)`: the value
  at 24, `nearest256` / `nearest16` of it at 256 / 16 when `nearest`, else `None`.
- `"ink"`: `realize_ink(value, caps, nearest=nearest)`.

`realize` never reads `role`: colours that differ only by role realize alike.

Invariant: role_kept — a colour keeps the theme role it came from through every Style
  operation, and a derived colour keeps its source's role under a prefix:
  (1) `resolve(Name(v, role)).role == role` for every form of `v` other than a Colour,
  and `resolve(c) is c` for a Colour `c`; (2) [Attrs]' `style(spec)` gives each colour
  of the Style the role rule stated there (a given Colour unchanged); (3)
  `c.derive(kind, value)` is `resolve(Name(value, role=f"{kind}:{c.role}"))` when
  `c.role` is non-empty, and has role `""` when `c.role` is `""` (no role to keep):
  `kind` is a non-empty `str` of the letters a..z (`"tint"`, `"muted"`, `"trail"`,
  `"faint"`), `value` any value `resolve` takes without inks (a Colour value is
  refused: `TypeError`); derive again and the prefixes stack
  (`"faint:muted:kinds-service"`); (4) realizing and [Sgr]'s codes neither read nor
  change a role, and `dataclasses.replace` of a Style keeps the colours it does not
  replace, roles and all.

Inputs: `resolve`: a {Name} (a `Name`, `str`, `int`, `Ink` or `Colour`), and an
  optional mapping `str -> Ink`. `realize`: a `Colour`, a {Caps} (`caps.depth`), and
  `nearest: bool` (keyword only). `Colour.derive`: `kind: str`, `value`.
Outputs: `resolve`, `derive`: a {Colour}. `realize`: a shade.
Errors: `Colour(...)`: `ValueError` when `form` is not in `FORMS` or `value` does not
  fit it (a name not in `NAMES`, an index or component outside 0..255, an rgb tuple
  not of length 3, a non-None default); `TypeError` when `role` is not a `str`, or
  `value` has the wrong type for its form (`bool` counts as wrong for an int).
  `resolve`: `TypeError` when the value is none of the types above (a `bool`, a
  `float`, `None` included), or an `inks` value it reaches is not an `Ink`;
  `ValueError` when a `str` or `int` matches no form (an int or digit string outside
  0..255, a malformed `#` string, an unknown name, `""`). `realize`: `TypeError` when
  `colour` is not a `Colour`; `ValueError` from `depth_of`. `derive`: `ValueError`
  when `kind` is not as above, else as `resolve`.
Effects: none.

Usage:
    from types import SimpleNamespace as Caps
    from cure.core.style.colour import Colour, Name, resolve, realize
    from cure.core.style.ink import Ink
    teal = Ink("teal", (42, 161, 152), tty256=37, tty16="cyan")
    c = resolve(Name("teal", role="kinds-service"), {"teal": teal})
    # Colour("ink", teal, "kinds-service")
    realize(c, Caps(depth=256))                    # 37
    resolve("#2aa198")                             # Colour("rgb", (42, 161, 152), "")
    resolve(Name("bright_red", "error"))           # Colour("name", "bright_red", "error")
    c.derive("muted", "#5a8a85")                   # Colour("rgb", (90, 138, 133), "muted:kinds-service")
"""

from collections.abc import Mapping
from dataclasses import dataclass

from .ink import NAMES, Ink, depth_of, nearest16, palette_rgb, parse_hex, realize_ink

FORMS: tuple[str, ...] = ("default", "name", "index", "rgb", "ink")
"""The forms a {Colour} takes."""


@dataclass(frozen=True)
class Name:
    """A colour as written ({Name}): `value` (str, int, Ink or Colour) and the theme
    `role` it is resolved for. Not checked until `resolve`."""

    value: object
    role: str = ""


@dataclass(frozen=True)
class Colour:
    """{Colour}: a colour in one of `FORMS`, carrying the theme `role` it came from
    (see role_kept). Checked on construction."""

    form: str
    value: object
    role: str = ""

    def __post_init__(self) -> None:
        """Check `form`, `value` and `role` (see the module's Errors)."""
        if not isinstance(self.role, str):
            raise TypeError(f"role must be a str, got {type(self.role).__name__}")
        if self.form not in FORMS:
            raise ValueError(f"form must be one of {FORMS}, got {self.form!r}")
        _CHECKS[self.form](self.value)

    @property
    def hex(self) -> "str | None":
        """`"#rrggbb"` for the rgb and ink forms, else None."""
        if self.form == "rgb":
            return Ink("", self.value).hex
        if self.form == "ink":
            return self.value.hex
        return None

    def derive(self, kind: str, value: object) -> "Colour":
        """A colour computed from this one (tint, muted, trail, faint ...): `value`
        resolved with the role `f"{kind}:{self.role}"`, or `""` when this has none."""
        if not isinstance(kind, str) or not kind or not all("a" <= ch <= "z" for ch in kind):
            raise ValueError(f"kind must be a non-empty str of a..z, got {kind!r}")
        if isinstance(value, Colour):
            raise TypeError("derive takes a value to resolve, not a Colour")
        role = f"{kind}:{self.role}" if self.role else ""
        return resolve(Name(value, role))


def resolve(name: object, inks: "Mapping[str, Ink] | None" = None) -> Colour:
    """The {Colour} a {Name} stands for, by the match order in the module docstring."""
    if not isinstance(name, Name):
        name = Name(name)
    value, role = name.value, name.role
    if isinstance(value, Colour):
        return value
    if isinstance(value, Ink):
        return Colour("ink", value, role)
    if isinstance(value, int) and not isinstance(value, bool):
        return Colour("index", value, role)
    if not isinstance(value, str):
        raise TypeError(f"not a colour: {type(value).__name__} {value!r}")
    return _resolve_str(value, role, inks or {})


def realize(colour: Colour, caps: object, *, nearest: bool = False) -> "int | tuple[int, int, int] | None":
    """The shade `colour` takes at `caps.depth` (see the module docstring)."""
    if not isinstance(colour, Colour):
        raise TypeError(f"expected a Colour, got {type(colour).__name__}")
    depth = depth_of(caps)
    if depth == 0 or colour.form == "default":
        return None
    if colour.form == "name":
        return NAMES.index(colour.value)
    if colour.form == "index":
        return _realize_index(colour.value, depth, nearest)
    ink = colour.value if colour.form == "ink" else Ink("", colour.value)
    return realize_ink(ink, caps, nearest=nearest)


def _realize_index(i: int, depth: int, nearest: bool) -> "int | None":
    if depth != 16 or i < 16:
        return i
    return nearest16(palette_rgb(i)) if nearest else None


def _resolve_str(value: str, role: str, inks: "Mapping[str, Ink]") -> Colour:
    if value == "default":
        return Colour("default", None, role)
    if value in NAMES:
        return Colour("name", value, role)
    if value.startswith("#"):
        rgb = parse_hex(value)
        if rgb is None:
            raise ValueError(f"malformed hex colour {value!r}")
        return Colour("rgb", rgb, role)
    if value and all("0" <= ch <= "9" for ch in value):
        return Colour("index", int(value), role)
    if value in inks:
        ink = inks[value]
        if not isinstance(ink, Ink):
            raise TypeError(f"ink {value!r} is a {type(ink).__name__}, not an Ink")
        return Colour("ink", ink, role)
    raise ValueError(f"unknown colour {value!r}")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_byte(value: object, what: str) -> None:
    if not _is_int(value):
        raise TypeError(f"{what} must be an int, got {type(value).__name__}")
    if not 0 <= value <= 255:
        raise ValueError(f"{what} must be 0..255, got {value}")


def _check_default(value: object) -> None:
    if value is not None:
        raise ValueError(f"a default colour has no value, got {value!r}")


def _check_name(value: object) -> None:
    if not isinstance(value, str):
        raise TypeError(f"a colour name must be a str, got {type(value).__name__}")
    if value not in NAMES:
        raise ValueError(f"not one of the 16 names: {value!r}")


def _check_rgb(value: object) -> None:
    if not isinstance(value, tuple):
        raise TypeError(f"an rgb colour must be a tuple, got {type(value).__name__}")
    if len(value) != 3:
        raise ValueError(f"an rgb colour has three components, got {len(value)}")
    for c in value:
        _check_byte(c, "an rgb component")


def _check_ink(value: object) -> None:
    if not isinstance(value, Ink):
        raise TypeError(f"an ink colour must hold an Ink, got {type(value).__name__}")


_CHECKS = {
    "default": _check_default,
    "name": _check_name,
    "index": lambda v: _check_byte(v, "an index"),
    "rgb": _check_rgb,
    "ink": _check_ink,
}
