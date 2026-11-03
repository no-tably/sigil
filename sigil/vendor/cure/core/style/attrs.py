"""[Attrs]: fg, bg, bold, dim, italic, underline (+ style, colour), strike, reverse, link.

Kind: service (two data classes and a pure function).

What it does: defines {Style}, the value every styled cell and run carries, and builds
one from a {Spec}, the theme-side description of a role's look (`style(spec)`): each
colour of the spec is resolved by [Colour] and gets its theme role. [Sgr] turns a
Style into codes. Text and Buffer treat a Style as opaque, compared with `==` (two
styles are equal when every field is, colours' roles included).

Data (frozen dataclasses):
- `Style(fg=None, bg=None, bold=False, dim=False, italic=False, underline=None,
  underline_colour=None, strike=False, reverse=False, link=None)`, checked on
  construction:
  - `fg`, `bg`, `underline_colour`: `None` (not set: the terminal's default) or a
    `Colour`;
  - `bold`, `dim`, `italic`, `strike`, `reverse`: `bool`;
  - `underline`: `None` (off) or one of `UNDERLINES` (`"single"`, `"double"`,
    `"curly"`, `"dotted"`, `"dashed"`);
  - `underline_colour` may be set only when `underline` is (an underline colour
    without an underline is refused, so the codes never leave a stale 58 behind);
  - `link`: `None` or a non-empty `str` holding no control character (no C0
    U+0000..U+001F, no DEL U+007F, no C1 U+0080..U+009F) and no lone surrogate (no
    code point U+D800..U+DFFF; a Python `str` holds a surrogate pair written as two
    escapes, `"\\ud83d\\ude00"`, as two lone surrogates, so it is refused too): an
    OSC 8 hyperlink target, carried for Buffer and Display and never part of the SGR
    codes (see [Sgr]). So every accepted link encodes as strict UTF-8 and [Sgr]'s
    `hyperlink` never raises for it.
  `link` is the only field whose text reaches a terminal's bytes. Colours reach them
  only as SGR numbers ([Sgr]): a colour's `role`, a `"name"` colour's name and an
  `Ink`'s name are never sent to a terminal ([Colour]'s `realize` reads none of them),
  so Style puts no character rule on them. (Remote's protocol, which does carry roles
  and ink names to a client, refuses a control or a lone surrogate in them itself.)
  `Style()` is the plain style. `Style(fg=resolve("default"))` is a different value
  from `Style()` that draws the same.
- `Spec(fg=None, bg=None, bold=False, dim=False, italic=False, underline=None,
  underline_colour=None, strike=False, reverse=False, link=None, role="")`: a style as
  a theme declares it. Stored as given, checked by `style`:
  - `fg`, `bg`, `underline_colour`: `None` or anything [Colour]'s `resolve` takes (a
    `Name`, a `str`, an `int`, an `Ink` or a `Colour`);
  - `bold`, `dim`, `italic`, `strike`, `reverse`: `bool`;
  - `underline`: `None` or `False` (off), `True` (`"single"`), or one of `UNDERLINES`;
  - `link`: `None` or a `str` as Style requires;
  - `role`: a `str`, the theme role the spec is for (`"list.item.selected"`).

Building (`style(spec, inks=None)`): `Style(fg=c(spec.fg), bg=c(spec.bg),
underline_colour=c(spec.underline_colour), underline=u(spec.underline), link=...,
and each flag as given)`, where `c(None)` is `None` and otherwise `c(v)` is:

- `v` itself when `v` is a `Colour` (its role kept);
- `resolve(v, inks)` when `v` is a `Name` with a non-empty role (that role);
- `resolve(Name(value, spec.role), inks)` otherwise, `value` being `v.value` for a
  `Name` (role `""`) and `v` itself for a bare value.

So every colour a spec names carries the spec's role unless it already carries its own
(role_kept, see [Colour]). `u(None) = u(False) = None`, `u(True) = "single"`, and a
`str` in `UNDERLINES` is itself.

Inputs: `style`: a {Spec} and an optional mapping `str -> Ink` (the theme's inks).
Outputs: `style`: a {Style}.
Errors: `Style(...)`: `TypeError` when a field has the wrong type (a colour field not
  `None` or a `Colour`, a flag not a `bool`, `underline` / `link` not `None` or a
  `str`); `ValueError` when `underline` is a `str` not in `UNDERLINES`,
  `underline_colour` is set while `underline` is `None`, or `link` is `""`
  (`link must not be empty`), holds a control character (`link holds a control
  character: <repr>`) or holds a lone surrogate (`link holds a lone surrogate:
  <repr>`), the control checked first, `<repr>` being `repr(link)`. `style`: `TypeError` when `spec` is not a `Spec`, or a field of
  it has the wrong type (as for Style, `underline` also admitting a `bool`, a colour
  field anything `resolve` takes, `role` a `str`); `ValueError` from `resolve` (an
  unknown colour name) or as for Style. Theme's [Roles] catches these to degrade an
  unknown or broken role; Style never degrades silently.
Effects: none.

Usage:
    from cure.core.style.attrs import Spec, Style, style
    from cure.core.style.colour import Colour
    s = style(Spec(fg="bright_white", bg="#203040", bold=True, role="status.bar"))
    s.fg                                   # Colour("name", "bright_white", "status.bar")
    s.bg                                   # Colour("rgb", (32, 48, 64), "status.bar")
    style(Spec(underline=True)).underline  # "single"
    style(Spec()) == Style()               # True
"""

from collections.abc import Mapping
from dataclasses import dataclass

from .colour import Colour, Name, resolve
from .ink import Ink

UNDERLINES: tuple[str, ...] = ("single", "double", "curly", "dotted", "dashed")
"""The underline styles, in the order of their SGR sub-parameters 1..5 (see [Sgr])."""


@dataclass(frozen=True)
class Style:
    """{Style}: how a run of text draws. Checked on construction (see the module)."""

    fg: "Colour | None" = None
    bg: "Colour | None" = None
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: "str | None" = None
    underline_colour: "Colour | None" = None
    strike: bool = False
    reverse: bool = False
    link: "str | None" = None

    def __post_init__(self) -> None:
        """Check every field (see the module's Errors)."""
        for field in ("fg", "bg", "underline_colour"):
            value = getattr(self, field)
            if value is not None and not isinstance(value, Colour):
                raise TypeError(f"{field} must be None or a Colour, got {type(value).__name__}")
        _check_flags(self)
        if self.underline is not None:
            if not isinstance(self.underline, str):
                raise TypeError(f"underline must be None or a str, got {type(self.underline).__name__}")
            if self.underline not in UNDERLINES:
                raise ValueError(f"underline must be one of {UNDERLINES}, got {self.underline!r}")
        elif self.underline_colour is not None:
            raise ValueError("underline_colour is set without an underline")
        _check_link(self.link)


@dataclass(frozen=True)
class Spec:
    """{Spec}: a style as a theme declares it, for `role`. Stored as given; `style`
    checks it."""

    fg: object = None
    bg: object = None
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: "bool | str | None" = None
    underline_colour: object = None
    strike: bool = False
    reverse: bool = False
    link: "str | None" = None
    role: str = ""


def style(spec: Spec, inks: "Mapping[str, Ink] | None" = None) -> Style:
    """The {Style} a {Spec} describes, its colours resolved with their roles (see the module)."""
    if not isinstance(spec, Spec):
        raise TypeError(f"expected a Spec, got {type(spec).__name__}")
    if not isinstance(spec.role, str):
        raise TypeError(f"role must be a str, got {type(spec.role).__name__}")
    _check_flags(spec)

    def colour(value: object) -> "Colour | None":
        return None if value is None else _colour(value, spec.role, inks)

    return Style(fg=colour(spec.fg), bg=colour(spec.bg), bold=spec.bold, dim=spec.dim,
                 italic=spec.italic, underline=_underline(spec.underline),
                 underline_colour=colour(spec.underline_colour), strike=spec.strike,
                 reverse=spec.reverse, link=spec.link)


_FLAGS = ("bold", "dim", "italic", "strike", "reverse")


def _check_flags(obj: "Style | Spec") -> None:
    for flag in _FLAGS:
        value = getattr(obj, flag)
        if not isinstance(value, bool):
            raise TypeError(f"{flag} must be a bool, got {type(value).__name__}")


def _check_link(link: object) -> None:
    if link is None:
        return
    if not isinstance(link, str):
        raise TypeError(f"link must be None or a str, got {type(link).__name__}")
    if not link:
        raise ValueError("link must not be empty")
    if any(_is_control(ch) for ch in link):
        raise ValueError(f"link holds a control character: {link!r}")
    if any(0xD800 <= ord(ch) <= 0xDFFF for ch in link):
        raise ValueError(f"link holds a lone surrogate: {link!r}")


def _is_control(ch: str) -> bool:
    code = ord(ch)
    return code < 0x20 or 0x7F <= code <= 0x9F


def _colour(value: object, role: str, inks: "Mapping[str, Ink] | None") -> Colour:
    if isinstance(value, Colour):
        return value
    if isinstance(value, Name):
        return resolve(value if value.role else Name(value.value, role), inks)
    return resolve(Name(value, role), inks)


def _underline(value: object) -> "str | None":
    if value is None or value is False:
        return None
    if value is True:
        return "single"
    if isinstance(value, str):
        return value
    raise TypeError(f"underline must be None, a bool or a str, got {type(value).__name__}")
