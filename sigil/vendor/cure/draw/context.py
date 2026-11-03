"""{Context}: theme, charset, caps, surface level (from the app's base), focus, now.

Kind: data (a frozen dataclass, checked on construction, with pure helper methods that
only delegate to the theme and charset it holds). Draw's {Context} is what every widget
paints from: Paint builds the root one from the app's arguments, Theme's `enter` gives
each node its own from its parent's, and a widget reads it by attribute (the widget
families never import this module: they may not, see `.construct/mapping.md`, and they
need not, since a context arrives as an argument). Nothing here holds state between
frames: the clock, the size and the capabilities are always arguments (Rules carried
over), so the same tree and context give the same frame.

Data:
- `Context(theme, charset, caps=Caps(), level=0, focus=None, hover=None, now=0,
  lift=False, zone=None)`:
  - `theme`: a Theme {Theme} (`cure.draw.theme.Theme`): its roles, ramp, states and
    borders are asked through the methods below. Not checked (duck typed).
  - `charset`: a Theme {Charset}: the glyphs. It is kept beside the theme (not read
    from `theme.charset`) because a [Scope] may swap either one alone. Not checked.
  - `caps`: a Core {Caps}: what the terminal can do. Widgets do not branch on it today
    (Style realizes colours at the depth it allows); it is here so a painter that must
    (a plot mode, a glyph the terminal cannot show) reads it from the one place.
  - `level`: the surface level, an `int >= 0`: at the root it is the app's base level
    (README decision 6: cure has no rule about where a program's frame sits), and
    Theme's `enter` adds exactly one per surface node entered (Ramp's from_tree). The
    ground a node paints at is `theme.ground(level, focused=lift)`, clamped there.
  - `focus`: the id of the focused node (the `id` field of a widget node; any hashable
    value), or `None` when nothing is focused. The app passes it in (Input's focus
    ring, I2); widgets compare it with their own ids (`is_focused`).
  - `hover`: the id under the pointer (the app's last `HitMap.at(x, y)`), or `None`.
    Hover only moves a highlight; it never selects (rove != commit != fire).
  - `now`: the tick, an `int` (frames or the app's own tick counter; never read from a
    clock here). An animation's phase is a function of it alone (Rules carried over):
    a spinner's frame, a pulse's position.
  - `lift`: `True` inside the focus pane: the grounds of the pane and of every node in
    it are taken one level up (the focused component's ground lifts one level, Rules
    carried over). Paint sets it for the subtree of a node whose `lifts(ctx)` is true
    (see the Widgets package); the root has `False`.
  - `zone`: the key:value alignment zone an enclosing node pushed (an `int >= 1`), or
    `None`. A PropertyList aligns at `max(zone, its own)`, so sibling lists line up
    at one separator column (Paint pushes it at its one recursion point).
- `Context.of(theme, **fields) -> Context`: `Context(theme, theme.charset, **fields)`,
  the usual root.

Helpers (each a one-line delegation; none caches or changes anything):
- `style(role) -> Style`: `theme.style(role)` (a dotted role falls back up the dots;
  an unknown one degrades, never fails).
- `declared(role) -> Style | None` (S1): `theme.roles.styles.get(role)`: the style
  of `role` when the theme DECLARES it as a style role, exactly (no fallback up the
  dots, no `default`, no `kind:` prefix); `None` when it does not (never declared,
  declared only by an ancestor, or declared but unstyled: a parameter in
  `theme.roles.values` alone). So a widget tells a declared role from a fallback
  without importing Theme: TextInput's runs ask `declared("sigil." + role)` and use
  the hex when it is `None`. A scoped theme answers by its own (merged) roles.
  `TypeError` when `role` is not a `str`.
- `treat(state, extent=None) -> Treatment`: Theme [States]' `treat(theme.roles, state,
  charset, extent=extent)` (marks from this context's charset).
- `apply(base, state, extent=None) -> Style`: [States]' `apply(base, treat(state,
  extent))`: the state's style laid over `base`, only adding.
- `ground(focused=False) -> Ground`: `theme.ground(level, focused=lift or focused)`.
- `border(focused) -> Style`: `theme.border(focused)`: receded at rest, full on focus.
- `glyph(token) -> str`: `charset.glyph(token)`.
- `run(token, n, base, *, weight=None, style=None, focused=False) -> tuple[tuple[str,
  Style], ...]` (R3a; the `[Widgets] -> [Theme] : run` flow): Theme's `run(theme,
  charset, token, n, base, weight=weight, style=style, focused=focused)` with this
  context's `theme` and `charset` (a [Scope]'s swap included): a run's n cells, each
  `(glyph, style)`, its pattern laid along n cells; a part with no role, and every
  base cell, in the edge style (`style`, else `border(focused)`); a part with role R
  in `style(R + ".focus")` when `focused`, else `style(R)`. `base` is the widget's
  base drawing as plain strs (a glyph `g`, or `(start, fill, end)`), so a widget
  builds no Theme type. With no pattern in the charset, it is today's glyphs in the
  edge style, cell for cell (base_unchanged). Every repeated run a widget draws asks
  it, never `glyph * n`. The contract, errors and laws are Theme's (`cure/draw/theme`).
- `parts(token, n, base, *, weight=None) -> tuple[tuple[str, str], ...]` (R3a
  addendum): Theme's `parts(charset, token, n, base, weight=weight)` with this
  context's charset: the run's n cells as `(glyph, part)`, so a widget reads where
  its start and end lie as laid (Block's title rect) without importing Theme.
- `frame(spinner, every=1) -> str`: `charset.frame(spinner, now // every)`.
- `is_focused(id) -> bool`: `id is not None and id == focus`.
- `is_hovered(id) -> bool`: `id is not None and id == hover`.

Deriving a child's context is Theme's op, not this module's: `enter(node, ctx)` swaps
`theme` / `charset` for a node with a scope and adds one to `level` for a surface node,
by `dataclasses.replace` (so every other field is inherited unchanged); Paint sets
`lift` and `zone` the same way at the same recursion point.

Inputs: the fields above.
Outputs: a {Context}.
Errors: `TypeError` when `level` or `now` is not an `int` (a `bool` included), `lift`
  is not a `bool`, `zone` is neither `None` nor an `int` (a `bool` included), or
  `focus` / `hover` is unhashable; `ValueError` when `level < 0` or `zone < 1`. The same
  checks run on `dataclasses.replace`. Assigning a field raises
  `dataclasses.FrozenInstanceError`. The helpers raise what the theme and charset
  raise (a `ValueError` for an unknown state, a `TypeError` for `every` not an int,
  a `ZeroDivisionError` never: `every < 1` is a `ValueError`).
Effects: none.

Usage:
    from cure.draw.theme import builtin, enter
    from cure.draw.context import Context
    from types import SimpleNamespace as Node
    ctx = Context.of(builtin(), level=1, focus="list", now=7)
    ctx.ground().role                                   # "surface.component"
    ctx.glyph("mark.focused"), ctx.frame("line")        # "›", "/"   (7 % 4 == 3)
    ctx.run("frame.pane.top", 4, ("╭", "─", "╮"), weight="rounded")
    # (("╭", b), ("─", b), ("─", b), ("╮", b)), b = ctx.border(False): no pattern
    ctx.is_focused("list"), ctx.is_focused(None)        # True, False
    enter(Node(scope=None, surface=True), ctx).level    # 2
"""

from collections.abc import Hashable
from dataclasses import dataclass, field

from cure.core.caps import Caps
from cure.draw.theme import parts as _parts, run as _run
from cure.draw.theme.states import apply as _apply, treat as _treat


def _int(name: str, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")


@dataclass(frozen=True)
class Context:
    """{Context}: what a widget paints from (see the module)."""

    theme: object
    charset: object
    caps: Caps = field(default_factory=Caps)
    level: int = 0
    focus: Hashable = None
    hover: Hashable = None
    now: int = 0
    lift: bool = False
    zone: "int | None" = None

    def __post_init__(self) -> None:
        """Check the fields (see the module's Errors)."""
        _int("level", self.level)
        if self.level < 0:
            raise ValueError(f"level must be >= 0, got {self.level}")
        _int("now", self.now)
        if not isinstance(self.lift, bool):
            raise TypeError(f"lift must be a bool, got {type(self.lift).__name__}")
        if self.zone is not None:
            _int("zone", self.zone)
            if self.zone < 1:
                raise ValueError(f"zone must be >= 1, got {self.zone}")
        for name in ("focus", "hover"):
            value = getattr(self, name)
            if not isinstance(value, Hashable):
                raise TypeError(f"{name} must be hashable, got {type(value).__name__}")
            hash(value)

    @classmethod
    def of(cls, theme: object, **fields: object) -> "Context":
        """The root context for `theme`, its charset the theme's own."""
        return cls(theme, theme.charset, **fields)

    def style(self, role: str) -> object:
        """The theme's style for `role` (falls back up the dots)."""
        return self.theme.style(role)

    def declared(self, role: str) -> object:
        """The theme's style for `role` when it declares it exactly, else None (see the module)."""
        if not isinstance(role, str):
            raise TypeError(f"role must be a str, got {type(role).__name__}")
        return self.theme.roles.styles.get(role)

    def treat(self, state: str, extent: "str | None" = None) -> object:
        """The {Treatment} of `state`, its mark from this context's charset."""
        return _treat(self.theme.roles, state, self.charset, extent=extent)

    def apply(self, base: object, state: str, extent: "str | None" = None) -> object:
        """`state`'s style laid over `base`, only adding."""
        return _apply(base, self.treat(state, extent))

    def ground(self, focused: bool = False) -> object:
        """The {Ground} at this level (one up when lifted or `focused`)."""
        return self.theme.ground(self.level, focused=self.lift or focused)

    def border(self, focused: bool) -> object:
        """A border's style: receded at rest, full on focus."""
        return self.theme.border(focused)

    def glyph(self, token: str) -> str:
        """The charset's glyph for `token` ("" for an unknown token)."""
        return self.charset.glyph(token)

    def run(self, token: str, n: int, base: "str | tuple[str, str, str]", *,
            weight: "str | None" = None, style: object = None,
            focused: bool = False) -> tuple:
        """A run's n `(glyph, style)` cells: Theme's `run` over this context's theme and charset."""
        return _run(self.theme, self.charset, token, n, base, weight=weight, style=style, focused=focused)

    def parts(self, token: str, n: int, base: "str | tuple[str, str, str]", *,
              weight: "str | None" = None) -> tuple:
        """A run's n `(glyph, part)` cells: Theme's `parts` over this context's charset."""
        return _parts(self.charset, token, n, base, weight=weight)

    def frame(self, spinner: str, every: int = 1) -> str:
        """The spinner's frame at this tick, advancing once every `every` ticks."""
        _int("every", every)
        if every < 1:
            raise ValueError(f"every must be >= 1, got {every}")
        return self.charset.frame(spinner, self.now // every)

    def is_focused(self, id: Hashable) -> bool:
        """Whether `id` names the focused node."""
        return id is not None and id == self.focus

    def is_hovered(self, id: Hashable) -> bool:
        """Whether `id` names the node under the pointer."""
        return id is not None and id == self.hover
