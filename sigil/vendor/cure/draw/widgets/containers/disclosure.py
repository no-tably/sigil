"""[Disclosure]: a collapsible panel: header line, open / closed.

Kind: service (a frozen dataclass node kind; see the Widgets package's protocol).

What it does: a header line (a twisty and a label) and, when open, its body below it.
Whether it is open is the app's state (`open`; merlang's `open = default XOR toggled`
lives in the app). Closing changes only what is drawn: the body is not laid out or
painted, nothing else about it changes. Only the header is clickable.

Data (frozen dataclass; checked on construction):
- `Disclosure(label, body=None, open=False, *, focused=None, id=None, size=None,
  anchor=None, scope=None, surface=False)`: `label` styled text (`str` or {Line};
  span style `None` is the role `strong`), `body` the node shown when open (`None`:
  none), `open` a `bool`, `focused` as Block's (`None`: `ctx.is_focused(id)`).

Children (`children`, a property): `(body,)` when `open` and `body` is not `None`,
else `()`. Chrome (`chrome()`): `{"padding": (1, 0, 0, 0)}`: the header is the rect's
first row; the body's content rect is the rest.

The header, on row `R.y` of `rect` `R`: `[m][t][" "][label]`, then ground to the end
of the row:
- `m`, the mark cell: the focused mark (`ctx.treat("focused").mark`, ›) when the
  Disclosure is focused, else the hover mark when hovered (`ctx.is_hovered(id)`; the
  builtin's hover has none), else a blank;
- `t`, the twisty: `ctx.glyph("twisty.open")` (▾) when open, else
  `ctx.glyph("twisty.closed")` (▸), in role `muted`;
- the label in role `strong`, cut to the room left (`R.w - 3`) with
  `ctx.glyph("ellipsis")` when wider;
- a hovered header gets `ctx.apply(.., "hover")` and a focused one
  `ctx.apply(.., "focused")` (in that order) over the whole header row inside the
  clip (row extent: the cursor runs the full row).

Painting (`paint(rect, ctx, grid, clip=None)`), `g = ctx.ground()`: the clip's
ground, the header, `shade(grid, clip, bg=g.style.bg)`. Hits: `(Hit(Rect(R.x, R.y,
R.w, 1) ∩ clip, id),)` when `id` is not `None` and that is not empty (the press rect
is the header only), else `()`.

Measuring: `"x"`: `max(3 + width(label), content)`; `"y"`: `1 + content` when open,
else `1`. `lifts(ctx)` is `False`.

Exact cells (the builtin theme):
- `Disclosure("Logs", id="d")` at `Rect(0, 0, 10, 1)`: `" ▸ Logs   "`; hits
  `(Hit(Rect(0, 0, 10, 1), "d"),)`.
- `Disclosure("Logs", body, open=True, id="d")` with `ctx.focus == "d"` at
  `Rect(0, 0, 10, 4)`: row 0 `"›▾ Logs   "`, every cell of row 0
  `ctx.apply(<its style>, "focused")`; rows 1 to 3 ground (the body is Paint's);
  hits `(Hit(Rect(0, 0, 10, 1), "d"),)`.
- `Disclosure("Configuration")` at width 8: `" ▸ Conf…"`.

Errors: `TypeError` when `label` is neither a `str` nor a `Line`, `open` or `surface`
  is not a `bool`, `focused` is not `None` or a `bool`, or `id` is unhashable.
  `measure` / `paint`: as the protocol states.
Effects: none, apart from `paint`'s writes into the grid it is given.
"""

from collections.abc import Hashable
from dataclasses import KW_ONLY, dataclass

from cure.core.buffer import Grid
from cure.core.geometry import Hit, Rect
from cure.core.text import Line, cut

from .block import (_begin, _check_common, _check_measure, _ground, _plain, _put, _restyle,
                    _shade, _styled, _width)


@dataclass(frozen=True)
class Disclosure:
    """A collapsible panel: a header line and, when open, its body (see the module)."""

    label: "str | Line"
    body: object = None
    open: bool = False
    _: KW_ONLY
    focused: "bool | None" = None
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = False

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        if not isinstance(self.label, (str, Line)):
            raise TypeError(f"label must be a str or a Line, got {type(self.label).__name__}")
        if not isinstance(self.open, bool):
            raise TypeError(f"open must be a bool, got {type(self.open).__name__}")
        if self.focused is not None and not isinstance(self.focused, bool):
            raise TypeError(f"focused must be None or a bool, got {type(self.focused).__name__}")
        _check_common(self)

    @property
    def children(self) -> tuple:
        """The body when open, else nothing (see the module)."""
        return (self.body,) if self.open and self.body is not None else ()

    def chrome(self) -> dict:
        """The header's row, as Layout `Box` keyword arguments."""
        return {"padding": (1, 0, 0, 0)}

    def lifts(self, ctx: object) -> bool:
        """Always False: a disclosure is not a pane."""
        return False

    def measure(self, axis: str, room: int, ctx: object, content: int = 0) -> int:
        """The natural size along `axis`, the header included (see the module)."""
        _check_measure(axis, room, content)
        if axis == "x":
            return max(3 + _width(self.label), content)
        return 1 + content if self.open else 1

    def paint(self, rect: Rect, ctx: object, grid: Grid, clip: "Rect | None" = None
              ) -> "tuple[Hit, ...]":
        """The ground and the header line into `grid` inside `clip` (see the module)."""
        begun = _begin(rect, grid, clip)
        if begun is None:
            return ()
        clip, area = begun
        g = ctx.ground()
        _ground(grid, area, g.style)
        R = rect
        f = self.focused if self.focused is not None else ctx.is_focused(self.id)
        hov = ctx.is_hovered(self.id)
        if R.h >= 1:
            mark = (ctx.treat("focused").mark if f else "") or (ctx.treat("hover").mark if hov else "")
            twisty = ctx.glyph("twisty.open" if self.open else "twisty.closed")
            _put(grid, R.x, R.y, _plain(mark or " ", None), area)
            _put(grid, R.x + 1, R.y, _plain(twisty, ctx.style("muted")), area)
            label = _styled(self.label, ctx, "strong")
            room = max(0, R.w - 3)
            if label.width > room:
                label = cut(label, room, ellipsis=ctx.glyph("ellipsis"))
            _put(grid, R.x + 3, R.y, label, area)
            applied: dict = {}      # Speed: one `ctx.apply` per (style, state) a paint

            def how(st: object, s: str) -> object:
                try:
                    return applied[st, s]
                except KeyError:
                    out = applied[st, s] = ctx.apply(st, s)
                    return out
                except TypeError:
                    return ctx.apply(st, s)

            for state, on in (("hover", hov), ("focused", f)):
                if on:
                    _restyle(grid, R.x, R.right, R.y, area, lambda st, s=state: how(st, s))
        _shade(grid, area, g.style)
        if self.id is None:
            return ()
        head = Rect(R.x, R.y, R.w, 1).intersect(clip)
        return () if head.empty else (Hit(head, self.id),)
