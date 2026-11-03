"""[Progress]: bar, gauge, pulse, spinner (phase from the tick).

Kind: service (four frozen dataclass node kinds; see the Widgets package's protocol).

What it does: shows how far something has got. `Bar` and `Gauge` show a known
fraction in eighth-cell steps; `Pulse` (a block bouncing along a track) and `Spinner`
(a cycling glyph) show that something is under way without a fraction. Their phase
is a function of `ctx.now` alone (an animation's phase comes from the tick: Rules
carried over), so the same tick always gives the same cells and a test can step it.
Every glyph is the charset's: `block.full` (█), `block.light` (░), the eighths
`block.eighths.h` (" ▏▎▍▌▋▊▉█", index i = i eighths), the spinners `spinner.<name>`.
Filled and empty cells differ in glyph, not only in colour, so a bar reads with
colour off.

Every colour is a widget role (Theme's `BUILTIN` declares each over today's value):
`progress.fill` (`$accent`: the filled cells, the pulse's block, the spinner's frame),
`progress.track` (`$dim`: the empty cells), `progress.label` (`$fg`, as `text`: a
gauge's or spinner's label) and `progress.figure` (`$muted`: a gauge's percentage),
so a theme restyles Progress alone by setting its roles (a theme that sets only `accent`, `dim`,
`text` or `muted` moves Progress no longer; a role falls back up its dots to `default`
where a theme does not declare it).

Data (frozen dataclasses; checked on construction; every kind ends with the common
keyword-only fields `id`, `size`, `anchor`, `scope`, `surface=False`):
- `Bar(fraction, *, span=20)`: `fraction` an int or float (finite; clamped into
  `[0, 1]` when drawn); `span` the natural width (`measure("x")`), an `int >= 1`.
- `Gauge(fraction, label="", *, span=20)`: a bar with a label before it and the
  percentage after it.
- `Pulse(*, width=3, every=1, span=20)`: a block `width` cells long bouncing along the
  track, one step every `every` ticks.
- `Spinner(name="dots", label="", *, every=1)`: the spinner `spinner.<name>`
  (`dots`, `line`, `pulse` in the builtin charsets), one frame every `every` ticks,
  then the label.

The bar cells (`Bar`, and the bar part of `Gauge`: both draw them through the one
helper), `n` cells long: `e = int(f * n * 8)` eighths with `f` the clamped fraction
(floor), `k = e // 8` full cells, `p = 1 if e % 8 > 0 else 0` partial cell and `r = n -
k - p` track cells, left to right:
1. the FILL run (R3b, refine round 7; Context's run op, R3a): `ctx.run(
   "run.progress.fill", k, ctx.glyph("block.full"), style=ctx.style("progress.fill"))`
   (`weight` None, `focused` False: a bar has no focus state), its `k` cells;
2. when `p`, the one partial cell `ctx.glyph("block.eighths.h")[e % 8]` in role
   `progress.fill`, exactly as today: never part of a run, never patterned (the
   eighths are a glyph table indexed by the fraction, not a run's parts);
3. the TRACK run: `ctx.run("run.progress.track", r, ctx.glyph("block.light"),
   style=ctx.style("progress.track"))`, its `r` cells.
Each run cell is its glyph in its style: the edge style passed (the role as today),
or, for a cell laid from a pattern part naming a role, that role's style (R3a's
`role_style`, at rest: `focused` is False). So a fill pattern's end rides the bar's
head as the fraction grows (it sits on the last full cell), and the track's start sits
just after the partial cell (or the last full one). Every `run.` pattern is one cell
per cluster (checked at load), so no run cell is a wide pair. With no
`run.progress.fill` / `run.progress.track` pattern in the context's charset (and
under the ascii base, a non-ASCII one is already dropped at load), the runs are
`block.full` `k` times and `block.light` `r` times in the two roles: today's bar,
cell for cell (base_unchanged).
`Pulse` and `Spinner` take NO run (untouched by R3b): a pulse's block is a moving
mark over a track split around it by the tick (its cells stay `block.full` /
`block.light` repeated, as today), a spinner's frame is one cell in time. A theme's
`run.progress.*` patterns never change a Pulse or a Spinner frame.

Painting (`paint(rect, ctx, grid, clip=None)`), on row `R.y` of `rect` `R` (the rows
below are ground), the protocol's recipe around it:
- `Bar`: the bar cells over `n = R.w`.
- `Gauge`: `label` (role `progress.label`) and one ground cell when `label` is not empty
  (`p = width(label) + 1`, else `0`), the bar over `n = R.w - p - 5`, one ground
  cell, then `f"{int(f * 100):>3}%"` (4 cells, role `progress.figure`). When `n < 1` the bar
  and its ground cell are left out (the label, cut to fit, and the percentage stay).
- `Pulse`: `s = min(width, R.w)`, the period `T = 2 * (R.w - s)`, `t = ctx.now //
  every`; the block's first cell `x = 0` when `T == 0`, else `x = t % T`, mirrored
  `x = T - x` when `x > R.w - s`. Cells `x .. x + s - 1` `block.full` (role
  `progress.fill`), the rest `block.light` (role `progress.track`).
- `Spinner`: `ctx.frame(name, every)` (role `progress.fill`), then, when `label` is
  not empty, one ground cell and the label (role `progress.label`), cut to the row
  with the ellipsis.
Hits: `(Hit(clip, id),)` when `id` is not `None`.

Measuring: `"y"`: `1` for every kind. `"x"`: `Bar`: `span`; `Gauge`: `p + span + 5`;
`Pulse`: `span`; `Spinner`: `1`, plus `1 + width(label)` with a label.

Exact cells (the builtin charset; the roles as above: `progress.fill` on the filled
cells, the block and the frame, `progress.track` on the empty cells,
`progress.label` on the label, `progress.figure` on the percentage):
- `Bar(0.5)` at width 10: `"█████░░░░░"`; `Bar(0.55)`: `e = 44`: `"█████▌░░░░"`;
  `Bar(0)`: `"░░░░░░░░░░"`; `Bar(1.7)`: `"██████████"`.
- `Gauge(0.5, "cpu")` at width 16: `n = 7`, `e = 28`: `"cpu ███▌░░░  50%"`.
- `Pulse()` at width 10 (`T = 14`): `now=0`: `"███░░░░░░░"`; `now=8`: `x = 14 - 8 =
  6`: `"░░░░░░███░"`; `now=7`: `x = 7`: `"░░░░░░░███"`.
- `Spinner(label="loading")` at `now=1`: `"⠙ loading"`; `Spinner("line")` at
  `now=5`: one cell, a backslash (`spinner.line` is `-\\|/`, and 5 % 4 == 1); with an
  ascii charset `spinner.dots` is `-\\|/` too.

The law (W1, unchanged frames): at the builtin theme, in both charsets (`builtin()`
and `builtin(ascii=True)`) and at every colour depth (off, 16, 256, truecolour),
every Progress frame (every kind; fractions in and out of `[0, 1]`, with and without
a label; every `now`, `every` and `width`; every rect width from 0 past the natural
one, every clip) is cell for cell the frame of the code before W1 (commit 2a559e3):
the same glyph, width, ink and attributes in every cell, and the same text and
rendered bytes, the one difference being the role tag of a colour (Roles: every
colour carries its role's name), which names `progress.fill` where it named
`accent`, `progress.track` where it named `dim`, `progress.label` where it named
`text` and `progress.figure` where it named `muted`, in Progress's own cells only;
every other cell (the ground around them, the gap cells) is equal, tags included. So
are the measures and the hits. The same holds for every Views tab (builders with
progress, a gauge, and working builders, a spinner, included): every cell outside a
Progress's own cells is equal to the oracle's, tags included. The oracle is the code
of the commit before W1, loaded from git at test time (`tests/_gitref.py`), never a
frozen copy.

Laws (R3b; a test loops over themes with and without `run.progress.*` patterns,
both ascii modes, fractions in and out of `[0, 1]`, every rect width from 0 past the
natural one, every clip):
- base_unchanged (73c003c): with no `run.progress.fill` or `run.progress.track`
  pattern in the context's charset, every Progress frame (every kind), measure and
  hits equal commit 73c003c's for the same fields and context (that commit's code
  loaded through `tests/_gitref.py` at test time, skipped without git history).
- bar-runs: a bar's cells are exactly the fill run's `k` cells, then the partial cell
  when `p`, then the track run's `r` cells (`k + p + r == n`); the partial cell is
  today's whatever the theme; `e`, `k`, `p`, `r` do not depend on the pattern.
- untouched: every Pulse and Spinner frame is the same with and without the
  patterns; so is every Gauge cell outside its bar (label, gap, percentage), and every
  measure (`fits` holds unchanged: a run is always exactly its cells).

Errors: `TypeError` when `fraction` is not an int or float (a `bool` included),
  `label` / `name` is not a `str`, `span`, `width` or `every` is not an int (a `bool`
  included), or as the common fields; `ValueError` when `fraction` is not finite, or
  `span`, `width` or `every` is < 1. `measure` / `paint`: as the protocol states.
Effects: none, apart from `paint`'s writes into the grid it is given.
"""

import math
from collections.abc import Hashable
from dataclasses import KW_ONLY, dataclass
from itertools import groupby
from operator import itemgetter

from cure.core.buffer import Grid
from cure.core.geometry import Hit, Rect
from cure.core.text import Line, Span, cut, width

from .paragraph import (_begin, _check_common, _check_measure, _ground, _join, _own, _plain, _put,
                        _shade)


def _check_fraction(value: object) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"fraction must be an int or a float, got {type(value).__name__}")
    if not math.isfinite(value):
        raise ValueError(f"fraction must be finite, got {value!r}")


def _check_positive(name: str, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if value < 1:
        raise ValueError(f"{name} must be >= 1, got {value}")


def _check_str(name: str, value: object) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a str, got {type(value).__name__}")


class _Leaf:
    """The leaf methods every progress kind shares (stubs: see the module)."""

    def chrome(self) -> None:
        """None: a leaf has no insets."""
        return None

    def lifts(self, ctx: object) -> bool:
        """Always False."""
        return False

    def measure(self, axis: str, room: int, ctx: object, content: int = 0) -> int:
        """The kind's natural width; one row (see the module)."""
        _check_measure(axis, room, content)
        return self._natural(ctx) if axis == "x" else 1

    def paint(self, rect: Rect, ctx: object, grid: Grid, clip: "Rect | None" = None
              ) -> "tuple[Hit, ...]":
        """The kind's row into `grid` inside `clip` (see the module)."""
        begun = _begin(rect, grid, clip)
        if begun is None:
            return ()
        clip, area = begun
        g = ctx.ground()
        _ground(grid, area, g.style)
        if rect.h >= 1 and rect.w >= 1:
            _put(grid, rect.x, rect.y, self._row(rect.w, ctx, g.style), area)
        _shade(grid, area, g.style)
        return tuple(_own(self, clip))


def _clamped(f: float) -> float:
    return min(1.0, max(0.0, float(f)))


def _bar(f: float, n: int, ctx: object) -> Line:
    """The bar cells: `n` cells of a clamped fraction in eighths, the full and the empty
    ones runs (see the module)."""
    if n < 1:
        return Line()
    e = min(int(_clamped(f) * n * 8), n * 8)
    k, p = e // 8, 1 if e % 8 else 0
    fs = ctx.style("progress.fill")
    full = ctx.run("run.progress.fill", k, ctx.glyph("block.full"), style=fs)
    part = _plain(ctx.glyph("block.eighths.h")[e % 8], fs) if p else Line()
    track = ctx.run("run.progress.track", n - k - p, ctx.glyph("block.light"),
                    style=ctx.style("progress.track"))
    return _join(_run_line(full), part, _run_line(track))


def _run_line(cells: tuple) -> Line:
    """A run's cells as one Line, a span per stretch of one style."""
    return Line(tuple(Span("".join(g for g, _ in group), s)
                      for s, group in groupby(cells, key=itemgetter(1))))


@dataclass(frozen=True)
class Bar(_Leaf):
    """A known fraction as a bar in eighth-cell steps (see the module)."""

    fraction: float
    _: KW_ONLY
    span: int = 20
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = False

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _check_fraction(self.fraction)
        _check_positive("span", self.span)
        _check_common(self)

    def _natural(self, ctx: object) -> int:
        return self.span

    def _row(self, w: int, ctx: object, gs: object) -> Line:
        return _bar(self.fraction, w, ctx)


@dataclass(frozen=True)
class Gauge(_Leaf):
    """A labelled bar with its percentage (see the module)."""

    fraction: float
    label: str = ""
    _: KW_ONLY
    span: int = 20
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = False

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _check_fraction(self.fraction)
        _check_str("label", self.label)
        _check_positive("span", self.span)
        _check_common(self)

    def _natural(self, ctx: object) -> int:
        return (width(self.label) + 1 if self.label else 0) + self.span + 5

    def _row(self, w: int, ctx: object, gs: object) -> Line:
        f = _clamped(self.fraction)
        percent = _plain(f"{int(f * 100):>3}%", ctx.style("progress.figure"))
        space = _plain(" ", gs)
        p = width(self.label) + 1 if self.label else 0
        n = w - p - 5
        if n >= 1:
            label = (_join(_plain(self.label, ctx.style("progress.label")), space) if self.label
                     else Line())
            return _join(label, _bar(f, n, ctx), space, percent)
        if not self.label:
            return percent
        label = _plain(self.label, ctx.style("progress.label"))
        room = max(0, w - 5)
        if label.width > room:
            label = cut(label, room, ellipsis=ctx.glyph("ellipsis"))
        return _join(label, space, percent)


@dataclass(frozen=True)
class Pulse(_Leaf):
    """A block bouncing along a track by the tick (see the module)."""

    _: KW_ONLY
    width: int = 3
    every: int = 1
    span: int = 20
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = False

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _check_positive("width", self.width)
        _check_positive("every", self.every)
        _check_positive("span", self.span)
        _check_common(self)

    def _natural(self, ctx: object) -> int:
        return self.span

    def _row(self, w: int, ctx: object, gs: object) -> Line:
        s = min(self.width, w)
        T = 2 * (w - s)
        x = 0
        if T:
            x = (ctx.now // self.every) % T
            if x > w - s:
                x = T - x
        light, track = ctx.glyph("block.light"), ctx.style("progress.track")
        return _join(_plain(light * x, track),
                     _plain(ctx.glyph("block.full") * s, ctx.style("progress.fill")),
                     _plain(light * (w - x - s), track))


@dataclass(frozen=True)
class Spinner(_Leaf):
    """A charset spinner's frame by the tick, then a label (see the module)."""

    name: str = "dots"
    label: str = ""
    _: KW_ONLY
    every: int = 1
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = False

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _check_str("name", self.name)
        _check_str("label", self.label)
        _check_positive("every", self.every)
        _check_common(self)

    def _natural(self, ctx: object) -> int:
        return 1 + (1 + width(self.label) if self.label else 0)

    def _row(self, w: int, ctx: object, gs: object) -> Line:
        frame = _plain(ctx.frame(self.name, self.every), ctx.style("progress.fill"))
        if not self.label:
            return frame
        label = _plain(self.label, ctx.style("progress.label"))
        room = max(0, w - frame.width - 1)
        if label.width > room:
            label = cut(label, room, ellipsis=ctx.glyph("ellipsis"))
        return _join(frame, _plain(" ", gs), label)
