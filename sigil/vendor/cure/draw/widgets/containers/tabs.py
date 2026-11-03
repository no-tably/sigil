"""[Tabs]: a strip and the active body.

Kind: service (two frozen dataclasses: the `Tabs` node kind and its `Tab` items; see
the Widgets package's protocol).

What it does: one row of tab labels, the strip, on top of its rect, and below it only
the active tab's body (its one child). Which tab is active is the app's state (the
`active` index); clicking a tab's segment hits that tab, and the router turns it into
the app's action (rove, commit and fire stay three steps).

Data (frozen dataclasses; checked on construction):
- `Tab(label, body=None, *, id=None)`: `label` styled text (a `str` or a {Line};
  span style `None` is the tab's role, below), `body` the node shown while the tab is
  active (`None`: an empty body), `id` the tab's own tag (hashable or `None`).
- `Tabs(tabs=(), active=0, *, focused=None, id=None, size=None, anchor=None,
  scope=None, surface=False)`: `tabs` a tuple of `Tab`; `active` an index into it
  (`0` when it is empty); `focused` as Block's (`None`: `ctx.is_focused(id)`).

Children (`children`, a property): `(tabs[active].body,)` when there are tabs and
that body is not `None`, else `()`. Chrome (`chrome()`): `{"padding": (1, 0, 0, 0)}`:
the strip is the rect's first row and the body's content rect is the rest.

The strip, on row `R.y` of `rect` `R`. Tab `i`'s segment is `[m][label][" "]`:
one mark cell, the label, one space, so `s_i = width(label_i) + 2` cells; between two
segments one separator cell, `ctx.glyph("border.light.v")` (│) in `ctx.border(f)`,
`f` whether the Tabs is focused. The whole strip is `S = sum(s_i) + (n - 1)` cells.
- Styles: an inactive label in role `muted`; the active one in role `strong`, then
  its whole segment `ctx.apply(.., "active")` (bold: it reads with colour off); when
  the Tabs is focused, the active segment also `ctx.apply(.., "focused")`; a hovered
  tab (`ctx.is_hovered(tab.id)`) `ctx.apply(.., "hover")` on its segment. A tab's
  extent is its segment, whatever extent the treatment names.
- The mark cell: the first non-empty mark of focused (when the Tabs is focused and
  the tab is active), active (the active tab), hover; else a blank. So the active
  tab's cell shows `●` at rest and `›` when the Tabs is focused.
- Fitting: when `S <= R.w` the strip is drawn from `R.x` and the rest of the row is
  ground. Otherwise (never silent): `k` is the smallest index `<= active` such that
  `(1 if k > 0 else 0) + sum(s_i for i in k..active) + (active - k) + (1 if active <
  n - 1 else 0) <= R.w`, or `active` when none is. The strip is then: an ellipsis
  cell `ctx.glyph("ellipsis")` in role `muted` when `k > 0`, then the segments from
  `k` (each after the first drawn preceded by its separator) while the next one and
  its separator fit in the row less one cell kept for a trailing ellipsis (when tabs
  remain after it); then that trailing ellipsis, right after the last whole segment,
  when any tab is left undrawn. A lone active segment wider than the row is cut with
  the ellipsis (its mark cell first).

Painting (`paint(rect, ctx, grid, clip=None)`), `g = ctx.ground()`: the clip's
ground (the body's area too: Paint paints the body over it), the strip, then
`shade(grid, clip, bg=g.style.bg)`. Hits, in order: `Hit(clip, id)` when `id` is not
`None`; then, for each segment drawn whole, `Hit(segment rect ∩ clip, tag)` with
`tag = tab.id` when that is not `None`, else `(id, "tab", i)` when `id` is not
`None`, else none. Only whole segments are recorded (a cut one is not clickable).

Measuring: `"x"`: `max(S, content)` (`0` with no tabs); `"y"`: `1 + content`.
`lifts(ctx)` is `False` (a strip is not a pane).

Exact cells (the builtin theme; mark and label styles as above):
- `Tabs((Tab("one"), Tab("two"), Tab("three")), id="t")` at `Rect(0, 0, 20, 1)`:
  `"●one │ two │ three  "`; hits `Hit(Rect(0, 0, 20, 1), "t")`, then
  `(Rect(0, 0, 5, 1), ("t", "tab", 0))`, `(Rect(6, 0, 5, 1), ("t", "tab", 1))`,
  `(Rect(12, 0, 7, 1), ("t", "tab", 2))`.
- The same with `ctx.focus == "t"`: `"›one │ two │ three  "`.
- At width 12, `active=2`: `k = 2` (for `k = 1`: 1 + 5 + 7 + 1 = 14 > 12; for
  `k = 2`: 1 + 7 = 8): `"…●three     "`; hits `Hit(Rect(0, 0, 12, 1), "t")`, then
  `(Rect(1, 0, 7, 1), ("t", "tab", 2))`.

Errors: `TypeError` when `tabs` is not a tuple of `Tab`, `active` is not an int (a
  `bool` included), `label` is neither a `str` nor a `Line`, `focused` is not `None`
  or a `bool`, or an `id` is unhashable; `ValueError` when `active` is outside
  `range(len(tabs))` (any `active` but 0 with no tabs). `measure` / `paint`: as the
  protocol states.
Effects: none, apart from `paint`'s writes into the grid it is given.
"""

from collections.abc import Hashable
from dataclasses import KW_ONLY, dataclass

from cure.core.buffer import Grid
from cure.core.geometry import Hit, Rect
from cure.core.text import Line, cut, width

from .block import (_begin, _check_common, _check_measure, _ground, _hit, _join, _plain, _put,
                    _shade, _styled, _width)


@dataclass(frozen=True)
class Tab:
    """One tab: its label, its body and its own tag (see the module)."""

    label: "str | Line"
    body: object = None
    _: KW_ONLY
    id: Hashable = None

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        if not isinstance(self.label, (str, Line)):
            raise TypeError(f"label must be a str or a Line, got {type(self.label).__name__}")
        if not isinstance(self.id, Hashable):
            raise TypeError(f"id must be hashable, got {type(self.id).__name__}")
        hash(self.id)


@dataclass(frozen=True)
class Tabs:
    """A strip of tabs and the active tab's body (see the module)."""

    tabs: tuple = ()
    active: int = 0
    _: KW_ONLY
    focused: "bool | None" = None
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = False

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        if not isinstance(self.tabs, tuple) or not all(isinstance(t, Tab) for t in self.tabs):
            raise TypeError("tabs must be a tuple of Tab")
        if not isinstance(self.active, int) or isinstance(self.active, bool):
            raise TypeError(f"active must be an int, got {type(self.active).__name__}")
        if self.tabs and not 0 <= self.active < len(self.tabs) or not self.tabs and self.active != 0:
            raise ValueError(f"active must index the tabs, got {self.active}")
        if self.focused is not None and not isinstance(self.focused, bool):
            raise TypeError(f"focused must be None or a bool, got {type(self.focused).__name__}")
        _check_common(self)

    @property
    def children(self) -> tuple:
        """The active tab's body, alone (see the module)."""
        if not self.tabs or self.tabs[self.active].body is None:
            return ()
        return (self.tabs[self.active].body,)

    def chrome(self) -> dict:
        """The strip's row, as Layout `Box` keyword arguments."""
        return {"padding": (1, 0, 0, 0)}

    def lifts(self, ctx: object) -> bool:
        """Always False: a strip is not a pane."""
        return False

    def measure(self, axis: str, room: int, ctx: object, content: int = 0) -> int:
        """The natural size along `axis`, the strip included (see the module)."""
        _check_measure(axis, room, content)
        if axis == "y":
            return 1 + content
        if not self.tabs:
            return content
        sw = width(ctx.glyph("border.light.v"))
        return max(sum(_width(t.label) + 2 for t in self.tabs) + (len(self.tabs) - 1) * sw,
                   content)

    def paint(self, rect: Rect, ctx: object, grid: Grid, clip: "Rect | None" = None
              ) -> "tuple[Hit, ...]":
        """The ground and the strip into `grid` inside `clip` (see the module)."""
        begun = _begin(rect, grid, clip)
        if begun is None:
            return ()
        clip, area = begun
        g = ctx.ground()
        _ground(grid, area, g.style)
        hits = [] if self.id is None else [Hit(clip, self.id)]
        if self.tabs and rect.h >= 1:
            for x, i in self._strip(rect, ctx, grid, area):
                tag = self.tabs[i].id
                if tag is None and self.id is not None:
                    tag = (self.id, "tab", i)
                if tag is not None:
                    seg = Rect(x, rect.y, _width(self.tabs[i].label) + 2, 1)
                    hit = _hit(seg, clip, tag)
                    if hit is not None:
                        hits.append(hit)
        _shade(grid, area, g.style)
        return tuple(hits)

    def _segment(self, i: int, ctx: object, f: bool, st: "_Styler") -> Line:
        """Tab `i`'s segment, `[m][label][" "]`, its states applied over it."""
        tab = self.tabs[i]
        active = i == self.active
        label = _styled(tab.label, ctx, "strong" if active else "muted")
        states = []
        if active:
            states.append("active")
        if ctx.is_hovered(tab.id):
            states.append("hover")
        if f and active:
            states.append("focused")
        marks = [st.treat(s).mark for s in ("focused", "active", "hover") if s in states]
        mark = next((m for m in marks if m), " ")
        seg = _join(_plain(mark, None), label, _plain(" ", None))
        if not states:
            return seg
        spans = []
        for span in seg.spans:
            style = span.style
            for state in states:
                style = st.apply(style, state)
            spans.append(type(span)(span.text, style))
        return Line(tuple(spans))

    def _strip(self, R: Rect, ctx: object, grid: Grid, area: Rect) -> "list[tuple[int, int]]":
        """Draw the strip on row R.y; the (x, index) of every segment drawn whole."""
        f = self.focused if self.focused is not None else ctx.is_focused(self.id)
        st = _Styler(ctx)
        n, a = len(self.tabs), self.active
        sizes = [_width(t.label) + 2 for t in self.tabs]
        sep = _plain(ctx.glyph("border.light.v"), ctx.border(f))
        sw = sep.width
        ell = _plain(ctx.glyph("ellipsis"), ctx.style("muted"))
        ew = ell.width
        whole = []
        if sum(sizes) + (n - 1) * sw <= R.w:
            x = R.x
            for i in range(n):
                if i:
                    _put(grid, x, R.y, sep, area)
                    x += sw
                _put(grid, x, R.y, self._segment(i, ctx, f, st), area)
                whole.append((x, i))
                x += sizes[i]
            return whole
        k = a
        for j in range(a + 1):
            need = ((ew if j > 0 else 0) + sum(sizes[j:a + 1]) + (a - j) * sw
                    + (ew if a < n - 1 else 0))
            if need <= R.w:
                k = j
                break
        x = R.x
        if k > 0:
            _put(grid, x, R.y, ell, area)
            x += ew
        first = self._segment(k, ctx, f, st)
        if x + sizes[k] + (ew if k < n - 1 else 0) > R.right:
            tail = _join(first, ell) if k < n - 1 else first
            _put(grid, x, R.y, cut(tail, max(0, R.right - x), ellipsis=ell.plain), area)
            return whole
        _put(grid, x, R.y, first, area)
        whole.append((x, k))
        x += sizes[k]
        last = k
        for i in range(k + 1, n):
            room = R.right - (ew if i < n - 1 else 0)
            if x + sw + sizes[i] > room:
                break
            _put(grid, x, R.y, sep, area)
            x += sw
            _put(grid, x, R.y, self._segment(i, ctx, f, st), area)
            whole.append((x, i))
            x += sizes[i]
            last = i
        if last < n - 1:
            _put(grid, x, R.y, ell, area)
        return whole


class _Styler:
    """`ctx.treat` and `ctx.apply`, memoised for one paint call (pure: the same
    answers, asked once)."""

    # Speed: the segments share their states and styles; each is asked once a paint.

    def __init__(self, ctx: object) -> None:
        self.ctx = ctx
        self.treats: dict = {}
        self.applied: dict = {}

    def treat(self, state: str) -> object:
        t = self.treats.get(state)
        if t is None:
            t = self.treats[state] = self.ctx.treat(state)
        return t

    def apply(self, style: object, state: str) -> object:
        key = (style, state)
        try:
            return self.applied[key]
        except KeyError:
            out = self.applied[key] = self.ctx.apply(style, state)
            return out
        except TypeError:
            return self.ctx.apply(style, state)
