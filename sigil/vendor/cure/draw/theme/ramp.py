"""[Ramp]: surface levels from the real tree depth, from the app's base level; clamped.

Kind: service (two data classes and pure functions).

What it does: a theme declares its surface ramp, the grounds from the app's ground
outward (app ground → component → sub-component → raised, in the builtin); `level`
gives the ground a node paints at, from its depth in the node tree and the base level
the app passes in (README decision 6: cure has no rule of its own about where a
program's frame sits). The depth is counted by Theme's `enter` as Paint walks the
node tree (one more for each surface node entered); nothing here looks at what was
drawn.

The ramp (`ramp(raw, roles) -> Ramp`), from the theme's reserved `ramp` leaf: role
names split on spaces, in ground order, e.g. `ramp: surface.ground surface.component
surface.sub surface.raised`. The order is exactly the written one (never inferred from
role names or role order: merlang's latent drift). Each name must be a styled role
of `roles` (a key of `roles.styles`, exactly: no fallback) and appear once; otherwise
a ThemeError at the `ramp` leaf's source and line ("ramp names an undefined role
'x'", "ramp names 'x' twice"). A leaf below `ramp` is a ThemeError ("ramp must be a
scalar"). No `ramp` leaf: the empty ramp, `Ramp()` (no ground is ever filled). A
ground is drawn with its role's style as declared: write `surface.component: on
$surface` (its `bg` is the fill).

A ground (`level(ramp, depth, base=0, *, focused=False) -> Ground`): with
n = `len(ramp.roles)`:

- n = 0: `Ground(None, "", Style())`;
- else i = `min(base + depth + (1 if focused else 0), n - 1)`, and the ground is
  `Ground(i, ramp.roles[i], ramp.grounds[i])`. The focused component's ground lifts
  one level (Rules carried over); past the deepest level it stays there.

Invariant: from_tree — the level is a function of the node tree's depth and the
  app's base level alone, never of what was drawn (no border is counted): `level`
  reads only its arguments, and Theme's `enter` raises the depth by exactly one per
  surface node entered (and by nothing else); levels clamp at the deepest ground,
  never wrap: for every ramp of n >= 1 grounds, `level(r, d, b).index == min(b + d,
  n - 1)`, so it never decreases as `d` grows (a deeper box never reads as an
  outdent).

Data (frozen dataclasses; immutable all the way down, Theme's rule):
- `Ramp(roles: tuple[str, ...] = (), grounds: tuple[Style, ...] = ())`: the ground
  roles in order and their styles (same length). `__post_init__` stores each as a
  `tuple` (a list given becomes one, so `Ramp([..], [..]) == Ramp((..), (..))`); no
  mapping field. Hashable, as today.
- `Ground(index: int | None, role: str, style: Style)`: the level taken (None for an
  empty ramp), its role, its style. No container field; hashable, as today.

Inputs: `ramp`: a {Raw} and {Roles}. `level`: a {Ramp}, `depth: int >= 0`, `base: int
  >= 0`, `focused: bool` (keyword only).
Outputs: `ramp`: a {Ramp}. `level`: a {Ground}.
Errors: `ramp`: ThemeError as above. `level`: `TypeError` when `depth` or `base` is not
  an `int` (a `bool` included) or `focused` not a `bool`; `ValueError` when `depth` or
  `base` is negative.
Effects: none.

`Ramp`'s sequence fields are stored as tuples through [Parse]'s public
`freeze_seqs(self, "roles", "grounds")` in `__post_init__` (Q9b: never Parse's private
`_tuples`).

Usage:
    from cure.core.style import Style
    from cure.draw.theme.ramp import Ramp, level
    r = Ramp(("surface.ground", "surface.component", "surface.raised"),
             (Style(), Style(bold=True), Style(dim=True)))
    level(r, 0).role                  # "surface.ground"
    level(r, 1, base=1).index         # 2
    level(r, 7).index                 # 2: clamped, never wrapped
    level(r, 0, focused=True).index   # 1: the focused component lifts one level
    level(Ramp(), 3)                  # Ground(None, "", Style())
"""

from dataclasses import dataclass

from cure.core.style import Style

from .parse import Raw, ThemeError, freeze_seqs
from .roles import Roles


@dataclass(frozen=True)
class Ramp:
    """{Ramp}: the ground roles from the app's ground outward, and their styles."""

    roles: tuple = ()
    grounds: tuple = ()

    def __post_init__(self) -> None:
        freeze_seqs(self, "roles", "grounds")


@dataclass(frozen=True)
class Ground:
    """{Ground}: the level a node paints at (None: no ramp), its role and its style."""

    index: "int | None"
    role: str
    style: Style


def ramp(raw: Raw, roles: Roles) -> Ramp:
    """The theme's declared ramp (see The ramp)."""
    for path in raw.leaves:
        if path[0] == "ramp" and len(path) > 1:
            raise ThemeError(*raw.lines[path], "ramp must be a scalar")
    value = raw.at("ramp")
    if value is None:
        return Ramp()
    where = raw.line("ramp")
    names = []
    for name in value.split():
        if name not in roles.styles:
            raise ThemeError(*where, f"ramp names an undefined role '{name}'")
        if name in names:
            raise ThemeError(*where, f"ramp names '{name}' twice")
        names.append(name)
    return Ramp(tuple(names), tuple(roles.styles[n] for n in names))


def level(ramp: Ramp, depth: int, base: int = 0, *, focused: bool = False) -> Ground:
    """The ground at `base + depth` (+1 when focused), clamped at the deepest."""
    for what, value in (("depth", depth), ("base", base)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{what} must be an int, got {type(value).__name__}")
        if value < 0:
            raise ValueError(f"{what} must be >= 0, got {value}")
    if not isinstance(focused, bool):
        raise TypeError(f"focused must be a bool, got {type(focused).__name__}")
    if not ramp.roles:
        return Ground(None, "", Style())
    i = min(base + depth + (1 if focused else 0), len(ramp.roles) - 1)
    return Ground(i, ramp.roles[i], ramp.grounds[i])
