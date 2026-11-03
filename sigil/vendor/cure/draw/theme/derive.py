"""[Derive]: tint:, muted:, trail:, faint: — computed at theme load, mirrored by the
hosts' CSS; the tty256 / tty16 fallbacks derived by the same rule from the base's
declared ones (none declared: nearest, and only on opt-in).

Kind: service (a data class and pure functions).

What it does: computes the derived colours of a role's foreground (README decision 1:
derived roles are computed when a theme loads, never while painting, and a web host
mirrors the same maths in CSS from the role names, so it recolours a drawing on a
theme change without redrawing it). Each derived colour is built with Style's
`Colour.derive(kind, value)`, so it keeps its source's theme role under a prefix:
the muted colour of the role `kinds.service` has the role `"muted:kinds.service"`.

The four kinds (`KINDS`), from a colour C with an `(r, g, b)` value (C's `hex` is not
None: the `"rgb"` and `"ink"` forms; an ink's value is its `rgb`), the theme's ground
G (an `(r, g, b)`) and the theme's fractions (`Derivation`):

- `tint`:  `mix(C, G, d.tint)` (a fill that keeps a label legible; sigil's box fill);
- `muted`: `desaturate(C, d.muted)` (sigil's glyph-name colour);
- `trail`: `mix(C, G, d.trail)` (sigil's sim wire taken before);
- `faint`: `mix(desaturate(C, d.muted), G, d.faint)` (a wire never taken).

The maths, exactly (the hosts' CSS must agree; ported from sigil's kit `_tint`,
`muted` and `faded`):

- `mix(rgb, ground, k)`: `tuple(round(g + (c - g) * k) for c, g in zip(rgb, ground))`,
  keeping the fraction `k` of the colour over the ground (k = 1: the colour; k = 0:
  the ground). `round` is Python's (half to even).
- `desaturate(rgb, k)`: `h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)`;
  `colorsys.hls_to_rgb(h, l, s * k)`; each channel `round(x * 255)`.

Deriving one colour (`derive(colour, kind, d)`), by its form:

- `"rgb"` (no declared fallback): `colour.derive(kind, "#rrggbb")` of the 24-bit
  result above (lower-case hex): an `"rgb"` Colour, no tty256 / tty16 fallback, so
  below truecolour it draws only on nearest-colour opt-in (Style's `realize(...,
  nearest=True)`).
- `"ink"` (an `Ink` B, whose declared fallbacks are derived by the same rule, README
  decision 4): `colour.derive(kind, Ink(f"{kind}:{B.name}", rgb, tty256, tty16))`, an
  `"ink"` Colour (Style's `resolve` of an `Ink`), where
  - `rgb` is the 24-bit result above;
  - `tty256`: when `B.tty256` is not None, the same kind's maths (same `mix` /
    `desaturate`, same fractions) applied to `palette_rgb(B.tty256)` against the
    ground's 256-colour rgb `G256`, then `nearest256` of that (an index 16..255: the
    rule's own last step on a declared value, mapping back into the
    terminal-independent cube and greys; it is not nearest-colour of the 24-bit
    value); `None` when `B.tty256` is None;
  - `tty16`: when `B.tty16` is not None, the same maths applied to
    `palette_rgb(NAMES.index(B.tty16))` (its `XTERM16` value) against the ground's
    16-colour rgb `G16`, then `NAMES[nearest16(that)]`; `None` when `B.tty16` is None.
  So a base that declares a fallback gives a derived colour that declares one, and a
  base that declares none gives one that declares none (nearest-colour then applies
  only on opt-in, through Style's `realize_ink(..., nearest=True)`, as for any ink).
  For `faint`, the maths is `mix(desaturate(x, d.muted), G', d.faint)` at each depth,
  with `G'` that depth's ground.
- `G256` is `d.ground256` when it is not None, else `d.ground`; `G16` is `d.ground16`
  when it is not None, else `d.ground` (see Derivation for where they come from).

Either way the role is `f"{kind}:{colour.role}"` (`""` when `colour.role` is `""`):
role_kept, through Style's `Colour.derive` (Style's public units only: `Colour`,
`Ink`, `NAMES`, `palette_rgb`, `nearest16`, `nearest256`).
A colour with no `(r, g, b)` value (the `"name"`, `"index"` and `"default"` forms)
cannot be mixed: `derive` returns `None`.

Derivation (`derivation(raw) -> Derivation`), from the leaves under `("derive",)`:

- `derive.ground`: the colour mixed toward: a `$name` reference ([Parse]'s `ref`;
  an ink gives its `rgb`) or a literal; it must have an `(r, g, b)` value (`#hex`,
  or a reference reaching one); a name or an index is a ThemeError ("derive.ground
  must be an rgb colour"). Absent: the palette entry `bg` when there is one with an
  `(r, g, b)` value; else `(0, 0, 0)` when the theme's `type` is `dark` (or absent)
  and `(255, 255, 255)` when it is `light`.
- `derive.tint`, `derive.muted`, `derive.trail`, `derive.faint`: decimal fractions
  (`float` of the value, finite, 0 <= k <= 1; anything else is a ThemeError at the
  leaf, "derive.x must be a fraction 0..1"). Absent: `DEFAULTS` (sigil's: tint 0.22,
  muted 0.4, trail 0.6, faint 0.4).
- The ground below 24-bit (`ground256`, `ground16`): when the ground came from an
  `Ink` (`derive.ground: $name` reaching an ink, or, with no `derive.ground`, the
  palette entry `bg` being or reaching an ink: [Parse]'s `palette` gives an `Ink`),
  `ground256 = palette_rgb(ink.tty256)` when the ink declares `tty256`
  (else `None`), and `ground16 = palette_rgb(NAMES.index(ink.tty16))` when it
  declares `tty16` (else `None`). A ground from a literal `#hex`, a palette entry
  that is a `#hex` string, or the `type` default has both `None` (each depth then
  uses `ground`, the 24-bit rgb). The built-in theme's ground (`#0d1117`, tty256
  233, tty16 black) gives `Derivation(ground=(13, 17, 23), ground256=(18, 18, 18),
  ground16=(0, 0, 0))`.
- Any other leaf under `derive` is a ThemeError ("unknown derive key 'x'").

Deriving a theme's roles (`derive_all(roles, d) -> Roles`): `roles` with `derived`
filled: for every role R of `roles.styles`, in order, whose style's `fg` is not None
and has an `(r, g, b)` value, and every kind K in `KINDS` order,
`derived[f"{K}:{R}"] = derive(fg, K, d)` (so an ink fg gives `"ink"` derived colours
with derived fallbacks, an rgb fg `"rgb"` ones). Roles whose fg has none get no entry. Every
other field is unchanged.

Looking one up (`derived(roles, kind, role) -> Colour | None`): along
`fallbacks(role)` ([Roles]), the first candidate in `roles.styles` answers:
`roles.derived[f"{kind}:{candidate}"]` when present, else that candidate's own `fg`
unchanged (a 16-colour name degrades to itself; `None` when it has no fg). No
candidate: `None`.

Data (frozen dataclass; immutable all the way down, Theme's rule):
- `Derivation(ground: tuple[int, int, int] = (0, 0, 0), tint: float = 0.22, muted:
  float = 0.4, trail: float = 0.6, faint: float = 0.4, ground256: tuple[int, int,
  int] | None = None, ground16: tuple[int, int, int] | None = None)`: `ground` the
  24-bit ground; `ground256` / `ground16` the ground's rgb at 256 / 16 colours
  (`None`: `ground`). The two new fields come last, so the positional form
  `Derivation(ground, tint, muted, trail, faint)` keeps its meaning. `__post_init__`
  stores `ground`, and `ground256` / `ground16` when not None, as `tuple`s (a list
  given becomes one); no mapping field. Hashable, as today.
- `DEFAULTS` is a read-only `types.MappingProxyType` (its contents as today).

Inputs: `derive`: a {Colour}, `kind` in `KINDS`, a `Derivation`. `derivation`: a
  {Raw}. `derive_all`: {Roles}, a `Derivation`. `derived`: {Roles}, `kind`, `role:
  str`. `mix` / `desaturate`: an `(r, g, b)` of ints 0..255 and a fraction.
Outputs: `derive`: a {Colour} or None. `derivation`: a `Derivation`. `derive_all`:
  {Roles}. `derived`: a {Colour} or None. `mix` / `desaturate`: an `(r, g, b)`.
Errors: `ValueError` when `kind` is not in `KINDS` (`derive`, `derived`); `TypeError`
  when `colour` is not a `Colour`; `ThemeError` from `derivation` as above.
Effects: none.

`Derivation`'s sequence fields are stored as tuples through [Parse]'s public
`freeze_seqs(self, "ground", "ground256", "ground16")` in `__post_init__` (Q9b:
never Parse's private `_tuples`).

Usage:
    from cure.core.style import Colour, Ink
    from cure.draw.theme.derive import Derivation, derive, mix, desaturate
    d = Derivation(ground=(13, 17, 23))
    c = Colour("rgb", (138, 160, 255), "kinds.service")
    derive(c, "tint", d)             # Colour("rgb", mix((138, 160, 255), (13, 17, 23), 0.22), "tint:kinds.service")
                                     # == Colour("rgb", (40, 48, 74), "tint:kinds.service")
    derive(c, "muted", d).role       # "muted:kinds.service"
    derive(Colour("name", "red", "x"), "tint", d)   # None
    mix((255, 255, 255), (0, 0, 0), 0.5)            # (128, 128, 128)
    # an ink: its declared fallbacks derived by the same rule
    g = Derivation(ground=(13, 17, 23), ground256=(18, 18, 18), ground16=(0, 0, 0))
    teal = Colour("ink", Ink("teal", (42, 161, 152), tty256=37, tty16="cyan"), "kinds.service")
    derive(teal, "tint", g)          # Colour("ink", Ink("tint:teal", (19, 49, 51), 235, "black"), "tint:kinds.service")
    derive(teal, "muted", g)         # Colour("ink", Ink("muted:teal", (78, 125, 122), 66, "bright_black"), "muted:kinds.service")
    derive(teal, "trail", g)         # Colour("ink", Ink("trail:teal", (30, 103, 100), 23, "cyan"), "trail:kinds.service")
    derive(teal, "faint", g)         # Colour("ink", Ink("faint:teal", (39, 60, 63), 236, "black"), "faint:kinds.service")
    # tint, worked: 24-bit mix((42, 161, 152), (13, 17, 23), 0.22) = (19, 49, 51);
    # tty256: palette_rgb(37) = (0, 175, 175), mix(it, (18, 18, 18), 0.22) = (14, 53, 53),
    #   nearest256 -> 235; tty16: palette_rgb(6) = (0, 205, 205), mix(it, (0, 0, 0), 0.22)
    #   = (0, 45, 45), nearest16 -> 0, "black"
    derive(Colour("ink", Ink("rose", (232, 90, 120)), "r"), "tint", g).value.tty256   # None: none declared
"""

import colorsys
import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

from cure.core.style import NAMES, Colour, Ink, nearest16, nearest256, palette_rgb, parse_hex

from .parse import Raw, ThemeError, freeze_seqs, palette, ref
from .roles import Roles, fallbacks

KINDS: tuple[str, ...] = ("tint", "muted", "trail", "faint")
"""The derived kinds, in the order `derive_all` computes them."""

DEFAULTS: Mapping = MappingProxyType({"tint": 0.22, "muted": 0.4, "trail": 0.6, "faint": 0.4})
"""The fractions a theme that names none gets (sigil's ui.fill, name_saturation, sim_trail, sim_faint)."""


@dataclass(frozen=True)
class Derivation:
    """The ground mixed toward and the four fractions."""

    ground: tuple = (0, 0, 0)
    tint: float = 0.22
    muted: float = 0.4
    trail: float = 0.6
    faint: float = 0.4
    ground256: "tuple | None" = None
    ground16: "tuple | None" = None

    def __post_init__(self) -> None:
        freeze_seqs(self, "ground", "ground256", "ground16")


def derive(colour: Colour, kind: str, d: Derivation) -> "Colour | None":
    """The `kind` colour derived from `colour` (role `kind:<role>`), or None when it has no rgb."""
    if not isinstance(colour, Colour):
        raise TypeError(f"expected a Colour, got {type(colour).__name__}")
    _check_kind(kind)
    rgb = _rgb(colour)
    if rgb is None:
        return None
    out = _maths(rgb, kind, d, d.ground)
    if colour.form == "rgb":
        return colour.derive(kind, "#%02x%02x%02x" % out)
    base = colour.value
    g256 = d.ground if d.ground256 is None else d.ground256
    g16 = d.ground if d.ground16 is None else d.ground16
    tty256 = None
    if base.tty256 is not None:
        tty256 = nearest256(_maths(palette_rgb(base.tty256), kind, d, g256))
    tty16 = None
    if base.tty16 is not None:
        tty16 = NAMES[nearest16(_maths(palette_rgb(NAMES.index(base.tty16)), kind, d, g16))]
    return colour.derive(kind, Ink(f"{kind}:{base.name}", out, tty256, tty16))


def _maths(rgb: tuple, kind: str, d: Derivation, ground: tuple) -> tuple:
    """The `kind` maths on `rgb` against `ground` (see The maths)."""
    if kind == "tint":
        return mix(rgb, ground, d.tint)
    if kind == "muted":
        return desaturate(rgb, d.muted)
    if kind == "trail":
        return mix(rgb, ground, d.trail)
    return mix(desaturate(rgb, d.muted), ground, d.faint)


def derivation(raw: Raw) -> Derivation:
    """The theme's `derive` section as a Derivation (see Derivation)."""
    given = {}
    for path, value in raw.leaves.items():
        if path[0] != "derive":
            continue
        key = ".".join(path[1:])
        if key != "ground" and key not in DEFAULTS:
            raise ThemeError(*raw.lines[path], f"unknown derive key '{key}'")
        given[key] = (value, raw.lines[path])
    fractions = {k: _fraction(k, *given[k]) if k in given else v for k, v in DEFAULTS.items()}
    entry = _ground(*given["ground"], raw) if "ground" in given else _default_ground(raw)
    ground256, ground16 = _below(entry)
    return Derivation(_entry_rgb(entry), **fractions, ground256=ground256, ground16=ground16)


def derive_all(roles: Roles, d: Derivation) -> Roles:
    """`roles` with every derived colour filled in (see Deriving a theme's roles)."""
    out = dict(roles.derived)
    for role, s in roles.styles.items():
        if s.fg is not None and _rgb(s.fg) is not None:
            for kind in KINDS:
                out[f"{kind}:{role}"] = derive(s.fg, kind, d)
    return replace(roles, derived=out)


def derived(roles: Roles, kind: str, role: str) -> "Colour | None":
    """The `kind` colour of `role`, along its fallback chain (see Looking one up)."""
    _check_kind(kind)
    for candidate in fallbacks(role):
        if candidate in roles.styles:
            return roles.derived.get(f"{kind}:{candidate}", roles.styles[candidate].fg)
    return None


def mix(rgb: tuple, ground: tuple, k: float) -> tuple:
    """`rgb` kept at fraction `k` over `ground`, channel by channel, rounded."""
    return tuple(round(g + (c - g) * k) for c, g in zip(rgb, ground))


def desaturate(rgb: tuple, k: float) -> tuple:
    """`rgb` with its HLS saturation scaled by `k`, rounded."""
    r, g, b = rgb
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return tuple(round(x * 255) for x in colorsys.hls_to_rgb(h, l, s * k))


def _check_kind(kind: object) -> None:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")


def _rgb(colour: Colour) -> "tuple | None":
    if colour.form == "rgb":
        return colour.value
    if colour.form == "ink":
        return colour.value.rgb
    return None


def _fraction(key: str, value: str, where: tuple) -> float:
    try:
        k = float(value)
    except ValueError:
        k = math.nan
    if not (math.isfinite(k) and 0 <= k <= 1):
        raise ThemeError(*where, f"derive.{key} must be a fraction 0..1")
    return k


def _ground(value: str, where: tuple, raw: Raw) -> "Ink | str":
    """The ground's palette entry or literal colour (ThemeError when it has no rgb)."""
    entry = ref(palette(raw), value, where) if value.startswith("$") else value
    if _entry_rgb(entry) is None:
        raise ThemeError(*where, "derive.ground must be an rgb colour")
    return entry


def _default_ground(raw: Raw) -> "Ink | str":
    """The palette's `bg` when it has an rgb, else the `type` default as a literal."""
    entry = palette(raw).get("bg")
    if _entry_rgb(entry) is not None:
        return entry
    return "#ffffff" if raw.at("type") == "light" else "#000000"


def _below(entry: "Ink | str") -> tuple:
    """`(ground256, ground16)` of a ground entry: an ink's declared fallbacks' rgb, else None."""
    if not isinstance(entry, Ink):
        return None, None
    g256 = None if entry.tty256 is None else palette_rgb(entry.tty256)
    g16 = None if entry.tty16 is None else palette_rgb(NAMES.index(entry.tty16))
    return g256, g16


def _entry_rgb(entry: "Ink | str | None") -> "tuple | None":
    """The `(r, g, b)` of a palette entry or a literal colour, None when it has none."""
    if isinstance(entry, Ink):
        return entry.rgb
    if isinstance(entry, str) and entry.startswith("#"):
        return parse_hex(entry)
    return None
