"""[Pattern]: a run's pattern: start, fill, end, and an optional after (a unit laid over
the fill's first cells, a share of the run), laid along a run of n cells by the fits
law; every cell counted by Text's width table at load.

Kind: service (two frozen data classes and pure functions).

What it does: a widget draws some of its cells as a RUN, a line of n cells along one
axis (a frame's edge, a split's gutter, a scrollbar's track, a progress bar). Today a
run is one glyph per part: a corner, the edge glyph repeated, a corner
(`tl + h * (n - 2) + tr`). A {Pattern} restyles a run with more than one glyph per
part: a START of one or more cells, a FILL, a repeating unit of one or more cells cut
to fit, and an END of one or more cells (construct's pane foot: start `▙`, fill
`─┴─`, end `///`). It may also have an AFTER (refine round 13): a unit of one or more
cells laid OVER the fill's first k cells, k its SHARE of the run (wire's foot: `▙`,
then a tenth of the run in `▀`, then the fill; the fill keeps its phase, as if the
after were not there, so the `┴` marks sit where they would without it). `lay(pattern,
n, base)` gives the run's n cells; `base` is the
one-glyph-per-part drawing the widget would make without a pattern, so a missing part,
a run too short for the pattern, and a theme with no patterns all draw exactly as
before.

This module is the names-free core (R1, refine round 7). It knows no token names, reads
no charset and draws no widget: which charset leaves (`<run>.start|fill|end|after`,
`<run>.after.share`) become
which run's pattern, and the ascii drop, are [Charset]'s and the widgets' (R3).

A part is a tuple of grapheme clusters (Text's `cluster`), each counted by Text's
`width` (1 or 2 cells). An empty tuple means the part is not given. `after` is a part like the
other three (a tuple of clusters, checked by the same rules); `share` is a number, not
a part (Data). A VERTICAL pattern
is laid down rows, one cell per row (a frame's left and right edges, a gutter between
side-by-side panes), so every one of its clusters is one cell wide: a frame never eats
the inside and layout never moves.

Checking, at load (never at draw: a theme that loads draws). `clusters(text, *,
vertical=False, name="pattern", where=("<pattern>", None)) -> tuple[str, ...]` cuts
one part's text into clusters and checks each; `pattern(start="", fill="", end="", *,
vertical=False, after="", share=None, name="pattern", where=("<pattern>", None)) ->
Pattern` is `Pattern(clusters(start, vertical=vertical, name=f"{name}.start",
where=where), clusters(fill, ..., name=f"{name}.fill", ...), clusters(end, ...,
name=f"{name}.end", ...), vertical=vertical, after=clusters(after, ...,
name=f"{name}.after", ...), share=share)`: the four parts split in the order start,
fill, end, after (the first failure raised), then `Pattern`'s own checks, which are
where `share` is checked (Data: its errors, and the pairing of `after` and `share`). `name` is the run's name as the theme writes it (R3 passes
the leaf's run, `frame.pane.bottom`); `where` is the `(source, line)` a ThemeError
carries (Parse's `Raw.line(...)` of the leaf; `line` None when unknown). A caller with
one leaf per part, each on its own line, calls `clusters` per leaf (`name` the full
leaf, `where` that leaf's line) and builds the `Pattern` itself. `clusters`, in order:

1. `text` not a `str`: `TypeError(f"{name} must be a str, got {type(text).__name__}")`.
2. `""`: `()` (the part is not given; no error; whether an empty leaf in a theme is an
   error is the caller's, as charset's "empty glyph" is).
3. A control code point anywhere in `text` (Text's `control`: C0, DEL, C1, a
   surrogate; a tab, CR and LF included): `ThemeError(*where, f"{name}: control
   character U+{ord(ch):04X}")`, `ch` the first one (Parse's wording).
4. `cs = cluster(text)`; for each cluster `c` at 1-based index `i`, in order:
   - `width(c) == 0` (a base-less mark, a zero-width space): `ThemeError(*where,
     f"{name}: cluster {i} (U+{ord(c[0]):04X}) has width 0")`;
   - `vertical` and `width(c) > 1`: `ThemeError(*where, f"{name}: cluster {i}
     (U+{ord(c[0]):04X}) is {width(c)} cells wide; a vertical run takes one cell per
     row")`.
5. `cs`.

So `str(error)` reads, for `where=("pane.yaml", 12)` and `name="frame.pane.left"`:
`"pane.yaml:12: frame.pane.left: cluster 1 (U+4E2D) is 2 cells wide; a vertical run
takes one cell per row"`; with the defaults and `fill="\u0301-"` (Text's `cluster` joins a mark
to the cluster before it, so a width-0 cluster is always the first):
`"<pattern>: pattern.fill: cluster 1 (U+0301) has width 0"`.

The fits law (`lay(pattern, n, base) -> tuple[str, ...]`). A base end may be `None`
(R1r: the run has NO end there, as a track, a gutter, a bar or a frame's side has
none; see Data). Let the base ends be `BS = (base.start,)` when `base.start` is not
None, else `()`, and `BE` likewise; the EFFECTIVE parts `S = pattern.start or BS`, `F
= pattern.fill or (base.fill,)`, `E = pattern.end or BE` (a missing part falls back
to the base part, alone: a missing end of a run with no base end lays nothing, so the
fill runs to that edge); `A = pattern.after` (no fallback: a missing after lays no
after; `A` given exactly when `pattern.share` is not None, Data); and `w(c)` a cell count: Text's `width(c)` for a pattern
cluster, 1 for a base part (the base parts are counted as one cell each, unchecked:
the caller's word, as `h * (n - 2)` takes it today; see Data). `ws`, `we` the sums of
`w` over `S`, `E` (0 for an empty end); `bs = len(BS)`, `be = len(BE)`.

1. `ws + we <= n` (the ends fit): `cells(S) + mid + cells(E)`, the MIDDLE `mid`
   being `m = n - ws - we` cells:
   - `A` not given: `mid = cut(F, m)` (as before round 13);
   - `A` given: with `k = min(max(1, round(share * n)), m)` (`n` the whole run's
     length, not `m`; Python's `round` of the Python product, half to even: `round(2.5)
     == 2`, `round(1.5) == 2`; `k == 0` exactly when `m == 0`), `mid` is `cut(F, m)`
     with its first `k` cells replaced by `cut(A, k)` (the after unit cut by the same
     walk, `base.fill` taking a last cell a wide after cluster would overrun), and then,
     when `k < m` and cell `k` of `cut(F, m)` is `""` (the tail of a wide fill cluster
     whose head, cell `k - 1`, the after overwrote), that cell `base.fill`. So `mid ==
     cut(A, k) + cut(F, m)[k:]` but for that one cell: the fill keeps its phase (cell
     `j >= k` of the middle is the fill's own cell `j`), never half a glyph.
2. else, when `bs + be <= n` (too short: the ends fall back, BOTH, to their base
   ends, whichever was too wide): `BS + cut(F, n - bs - be) + BE`. No after: `A` is
   laid under rule 1 only (a run too short for its ends draws as before round 13).
3. else (only when `n < bs + be`, so `n <= 1` with two base ends): `(base.fill,) * n`
   (`()` for `n == 0`; one cell is the run's middle: no end is drawn whole). No after.

So with two base ends (a frame's top or bottom) the rules are as before R1r: rule 1
never holds for `n < 2`, rule 2 always holds for `n >= 2` when rule 1 does not. With
no base ends (`Base(None, g, None)`) rule 1 or 2 always holds: a fill-only pattern
fills every cell, `n == 1` included.

- `cells(parts)`: each cluster `c` in order as `(c,)` when `w(c) == 1`, `(c, "")` when
  `w(c) == 2` (a wide cluster, then its tail).
- `cut(F, m)` (the fill cut at a cluster boundary): walk `F` cyclically from its first
  cluster with `r = m` cells left; while `r > 0`: the next cluster `c` is placed
  (`cells((c,))`, `r -= w(c)`) when `w(c) <= r`; otherwise (it would overrun the run,
  so `r == 1` and `w(c) == 2`) the cell left takes `(base.fill,)` and the walk ends.
  `cut(F, 0) == ()`. So the fill is a prefix of `F` repeated, never half a glyph, then
  at most one `base.fill` cell.

The output shape: a `tuple` of exactly `n` `str`s, element `i` the glyph at cell `i`
of the run (left to right, or top to bottom for a vertical run): a cluster, or `""`
for the tail cell of the wide cluster just before it. It is Buffer's cell model
(Text's `put`, Buffer's [Cells]: a head of width 2, then its tail `Cell("", 0)`), so a
painter maps it cell for cell with no width arithmetic of its own, and `"".join(cells)`
is the line a widget paints where it paints `tl + h * inner + tr` today. A vertical
pattern never has a tail (every cluster one cell), so its element `i` is row `i`'s
glyph. Rejected: one string (loses the cell index of a vertical run and of a cut),
`(glyph, width)` pairs (a second, private cell model beside Buffer's).

Data (frozen dataclasses; immutable all the way down, Theme's rule; both hashable):
- `Pattern(start: tuple[str, ...] = (), fill: tuple[str, ...] = (), end: tuple[str,
  ...] = (), *, vertical: bool = False, after: tuple[str, ...] = (), share: float | None
  = None)` (round 13 adds `after` and `share`, keyword-only, after `vertical`: every
  positional call `Pattern(start, fill, end)` is as before, and so is its value: `after
  == ()`, `share is None`). The four parts are `start`, `fill`, `end`, `after`, in
  that order wherever this module says "the parts in turn". Each part is stored as a `tuple`
  (`tuple(x)` of what was given: a list becomes one); its items are `str`s, each
  exactly one grapheme cluster (`cluster(c) == (c,)`). `__post_init__` holds a
  directly built Pattern to `clusters`' rules, so every Pattern that exists can be
  laid (fits holds for all of them): a part given as a `str` is a `TypeError`
  (`f"Pattern.{part} must be a tuple of clusters, got str (split a string with
  pattern())"`: `tuple("e\\u0301")` would split a cluster); a part that is not
  iterable, a `TypeError` (`f"Pattern.{part} must be a tuple of clusters, got
  {type(part).__name__}"`); an item that is not a `str`, a `TypeError`
  (`f"Pattern.{part}: item {i} must be a str, got {type(item).__name__}"`); `vertical` not a `bool`, a `TypeError`
  (`f"Pattern.vertical must be a bool, got {type(vertical).__name__}"`); an item that is
  empty or not one cluster, `ThemeError("<pattern>", None, f"Pattern.{part}: item {i}
  is not one grapheme cluster")`; a control, a width 0 or (vertical) a wide item, the
  ThemeError of `clusters` rules 3-4 with `name=f"Pattern.{part}"`, `where=
  ("<pattern>", None)` and `i` the item's 1-based index (`after` held to them exactly
  as the other parts, vertical included: a vertical pattern's after is one cell per
  cluster). `share`: `None`, or an `int` or a `float` that is not a `bool` (anything
  else, a `str` `"0.1"`, a `Fraction` or `Decimal` included, is
  `TypeError(f"Pattern.share must be None or a number, got {type(share).__name__}")`,
  `True` giving `"... got bool"`), stored as given (`share=1` stays the int `1`, equal
  and hashing equal to `1.0`), with `0 < share <= 1` (else `ThemeError("<pattern>",
  None, f"Pattern.share must be > 0 and <= 1, got {share!r}")`; a NaN fails it too);
  `after` and `share` are given together or not at all: `after` given (non-empty) with
  `share` None is `ThemeError("<pattern>", None, "Pattern.after is given with no
  share")`, `share` not None with `after == ()` is `ThemeError("<pattern>", None,
  "Pattern.share is given with no after")`. The order: every `TypeError` first (the
  parts `start`, `fill`, `end`, `after` in turn, each part's shape then its items; then
  `vertical`; then `share`'s type), then the ThemeErrors (the parts in turn, items in
  order, per item: not one cluster, then control, then width; then `share`'s range;
  then the pairing, after-with-no-share before share-with-no-after, only one of which
  can hold), the first failure raised. So `Pattern(after=("中",), share=2,
  vertical=True)` raises the wide cluster's ThemeError, not the share's.
  `Pattern()` is the empty pattern (no part given): it lays as the base
  (base_unchanged).
- `Base(start: str | None, fill: str, end: str | None)`: the base drawing, the glyphs
  the widget draws today: a frame's top or bottom, its two corners and its line
  (`Base(tl, h, tr)`); a run with no ends (a frame's side between the corners, a
  track, a gutter, a bar's filled cells) the glyph with no ends (`Base(None, g,
  None)`, R1r: its base drawing is `g * n`, and a pattern's fill reaches both of its
  edges). `Base(g, g, g)` is still valid and lays as before R1r (its ends are glyphs
  that happen to equal the fill). Each glyph is meant to be one cluster one cell wide
  (a charset glyph) and is counted as one cell by `lay`, unchecked: a theme may
  override a border glyph with any non-empty text (Charset checks no width), and then
  the run draws exactly as it does today (base_unchanged). The checks, field by
  field in order (`start`, `fill`, `end`), each field's type then its emptiness, the
  first failure raised: `start` and `end` `None` or a `str` (`TypeError(f"Base.{part} must be None or
  a str, got {type(x).__name__}")`), `fill` a `str` (`TypeError(f"Base.fill must be a
  str, got {type(x).__name__}")`); a given glyph non-empty (`ValueError(f"Base.{part}
  is empty")`: an empty glyph would leave the run a cell short).

Other ops:
- `is_ascii(pattern) -> bool`: every cluster of every part (`after` included) is ASCII
  (`c.isascii()`); `True` for `Pattern()`; `share` plays no part. Under `ascii=True` the caller (R3) drops a pattern for which
  it is False, whole, to the ascii base; this module drops nothing.

Each cell's part (`lay_parts(pattern, n, base) -> tuple[tuple[str, str], ...]`, R3a; a
new op beside `lay`, whose contract above is unchanged). The run op (Theme's `run`)
styles a cell by the part it was laid from (a part may name a role), so it needs to
know, cell for cell, which of the PATTERN's parts a cell came from and which cells are
the base's. `lay_parts` gives `n` pairs `(glyph, part)`, `part` one of `CELL_PARTS`
(`"start"`, `"fill"`, `"end"`, `"after"`, `"base"`; round 13 adds `"after"`, before
`"base"`), by the same rules as `lay`:

- the glyphs are `lay`'s: `tuple(g for g, _ in lay_parts(p, n, b)) == lay(p, n, b)`
  for every `p`, `n`, `b` (the same checks and errors as `lay`, raised in the same
  order, with `lay`'s messages);
- rule 1 (the ends fit): the cells of `cells(S)` are `"start"` when `pattern.start` is
  given, `"base"` when `S` is the base fallback `BS` (none when `BS == ()`); likewise `cells(E)`
  is `"end"` or `"base"`; in `cut(F, m)` a cell placed from a cluster of `pattern.fill`
  is `"fill"`, and every `base.fill` cell is `"base"` (the whole cut when
  `pattern.fill` is not given, and the one cell left over when a wide fill cluster
  would overrun); with an after, the middle's first `k` cells (`cut(A, k)`) are
  `"after"`, but a `base.fill` cell left over inside `cut(A, k)` (a wide after cluster
  that would overrun) is `"base"`; the cells after them are tagged as the fill's cut
  tags them, but a fill tail the after's last cell orphaned (cell `k`, now
  `base.fill`) is `"base"`;
- rule 2 (too short): the cells of `BS` and `BE` are `"base"`; the middle is `cut(F,
  n - bs - be)`, tagged as the fill's cut under rule 1 (no `"after"`: rule 2 lays no
  after);
- rule 3: every cell (`base.fill`) is `"base"`; `n == 0` gives `()`;
- a wide cluster's tail cell `""` carries its head's part (a cell pair is never split
  between parts).

So `"base"` marks exactly the cells `lay` draws from `base` (a missing part, a fallback
end, a cut's leftover cell, an orphaned fill tail, the whole run when too short), and a part's tag appears
only on cells drawn from that part's own clusters: under `Pattern()` every cell is
`"base"`.

Laws (R3a, beside `lay`'s; round 13 restates them with `after`):
- parts_agree: the glyphs of `lay_parts` are `lay`'s (above), for every pattern (with
  and without an after, every share), base and `n` in 0..N.
- parts_tagged: a cell tagged `"start"` / `"fill"` / `"end"` / `"after"` holds a
  cluster of that part of the pattern (or the `""` tail of one); a cell tagged `"base"`
  holds one of `base`'s three glyphs; under rule 1 the first `ws` cells are all
  `"start"` or all `"base"`, the last `we` all `"end"` or all `"base"`, and every cell
  between is `"after"`, `"fill"` or `"base"`, an `"after"` cell only among the `k`
  cells from `ws` (none when `pattern.after == ()`); under rules 2 and 3 no cell is
  `"start"`, `"end"` or `"after"`.
- parts_base: `all(t == "base" for _, t in lay_parts(Pattern(vertical=v), n, b))`
  (the empty pattern has no after); and a pattern with only an after (`Pattern(after=a,
  share=s, vertical=v)`) tags every cell `"after"` or `"base"`.
- after_over_fill (round 13): under rule 1 with `after` given, with `m = n - ws - we`,
  `k = min(max(1, round(share * n)), m)` and `c = cut(F, m)` (its tags as the fill's
  cut gives them): the cells `ws .. ws + k - 1` of `lay_parts(p, n, b)` are each
  `"after"` or `"base"`, and are `cut(A, k)` cell for cell; and every cell `ws + j`
  for `k <= j < m` is `c[j]` (glyph and tag), except that when `c[k]` is a `""` tail
  (`k < m`) cell `ws + k` is `(base.fill, "base")`. `k >= 1` whenever `m >= 1`: an
  after whose first cluster is one cell wide is always seen when the ends leave a
  middle (a wide first cluster at `k == 1` leaves `cut(A, 1)` one `base.fill` cell).

Inputs: `clusters`: `text: str`, `vertical: bool`, `name: str`, `where: tuple[str, int
  | None]`. `pattern`: three `str`s and the same keywords, with `after: str` and
  `share: int | float | None`. `lay`: a {Pattern}, `n: int`
  (`n >= 0`), a `Base`. `is_ascii`: a {Pattern}.
Outputs: `clusters`: a tuple of clusters. `pattern`: a {Pattern}. `lay`: a tuple of
  `n` glyph strings ({Glyphs}, one per cell, `""` for a tail). `lay_parts`: a tuple of
  `n` `(glyph, part)` pairs. `is_ascii`: a `bool`.
Errors: `clusters` / `pattern`: `TypeError` and `ThemeError` as above (a ThemeError is
  a `ValueError`; `pattern`'s share errors are `Pattern`'s). `Pattern` / `Base`: as in
  Data (the share's type, range and pairing included). `lay`: `TypeError` when `pattern` is
  not a `Pattern` (`f"pattern must be a Pattern, got {type(pattern).__name__}"`), `base`
  not a `Base` (`f"base must be a Base, got {type(base).__name__}"`) or `n` not an
  `int` (a `bool` refused: `f"n must be an int, got {type(n).__name__}"`); `ValueError`
  when `n < 0` (`f"n must be >= 0, got {n}"`). Never a ThemeError: widths are checked
  at load. `lay_parts`: exactly `lay`'s. `is_ascii`: `TypeError` when not a `Pattern`
  (as `lay`'s).
Effects: none.

Laws (each loops over patterns, bases and every n in 0..N; a test builds them from
clusters of width 1 and 2, ASCII and not, every part given or not, vertical or not):
- fits: `len(lay(p, n, b)) == n`; every `""` element directly follows a pattern
  cluster of width 2, and every pattern cluster of width 2 is directly followed by
  `""` (never half a cluster: no wide head at index `n - 1`, no tail at index 0);
  every non-`""` element is a cluster of `p` or a part of `b` (never a glyph from
  outside the pattern and its base); the sum of `w` over the non-`""` elements is
  `n` (never a cell outside the run). With an after these hold as stated (a cluster
  of `p` includes one of `p.after`; the orphaned-tail rule keeps the `""` clause).
- base_unchanged: `lay(Pattern(vertical=v), n, b) == (b.start,) + (b.fill,) * (n - 2)
  + (b.end,)` for `n >= 2`, `(b.fill,)` for `n == 1`, `()` for `n == 0`, when both
  base ends are glyphs; `(b.fill,) * n` when both are `None` (`BS + (b.fill,) * (n -
  bs - be) + BE` in general, `n >= bs + be`); so for the edge of a frame
  `"".join(lay(Pattern(), n, Base(tl, h, tr))) == tl + h * (n - 2) + tr`, exactly what
  Block draws today, and for a track `Base(None, g, None)` (or `Base(g, g, g)`) it is
  `g * n`.
  More generally a pattern whose given parts are the base's own glyphs lays as the
  base.
- cut_at_boundary: when rule 1 holds and `p.after == ()`, `lay(p, n, b)[ws:n - we]`
  is `cut(F, n - ws - we)`: a prefix of `cells(F * k)` for some k, followed by
  `(b.fill,)` only when the next cluster of `F` is wide and one cell is left; with an
  after, the same of the cells past the after (law after_over_fill); under rule 2 the
  same of `[1:n - 1]` with `n - 2` (no after).
- too_short: `ws + we > n >= 2` implies `lay(p, n, b)[0] == b.start` and `lay(p, n,
  b)[-1] == b.end` (both ends fall back together); `n == 1` gives `(b.fill,)` and `n ==
  0` gives `()` whatever `p`; when `ws + we <= n`, `lay(p, n, b)` starts with
  `cells(S)` and ends with `cells(E)`.
- missing_part: replacing a missing part of `p` with the base's (`start=(b.start,)`,
  `fill=(b.fill,)` or `end=(b.end,)`, a 1-cell cluster) leaves `lay(p, n, b)`
  unchanged (the fallback is exactly the base part). The after has no base part: a
  missing after lays no after, and `Pattern(s, f, e, vertical=v)` lays as before
  round 13 for every `n`.
- vertical: `pattern(..., vertical=True)` refuses any wide cluster (its after's too), so `lay` of a
  vertical pattern has no `""` element: element `i` is row `i`'s glyph.
- checked: `clusters(t, ...)` either raises or returns clusters `c` with `"".join(cs)
  == t`, each `width(c)` in 1..2 (1 when vertical), no control code point; `Pattern`
  built directly obeys the same, in all four parts, and its `share` is None or an
  `int` / `float` in `(0, 1]`, not None exactly when `after != ()`.
- ascii: `is_ascii(p) == all(c.isascii() for c in p.start + p.fill + p.end +
  p.after)`.
- pure: `lay`, `clusters`, `pattern` and `is_ascii` read only their arguments (and
  Text's fixed table): equal arguments give equal results, nothing is cached or
  written, and the arguments are unchanged (they are immutable).

Invariant: fits — a run of n cells is start, then fill cut to fit at a cluster
boundary (the after, when given, laid over its first k cells, the fill keeping its
phase), then end, when they fit; too short, the ends fall back to their one-cell
base glyphs, then the whole run to the base; always exactly n cells (`len == n`, the
cell widths summing to n), never half a cluster, never a cell outside the run.

Invariant: base_unchanged — with no pattern part given, `lay(Pattern(), n, base)` is
the base drawing exactly (`start + fill * (n - 2) + end` for an edge, `g * n` for a
track), so a theme without patterns draws every run as before (the frames oracle, R3).

Usage:
    from cure.draw.theme.pattern import Base, Pattern, lay, lay_parts, pattern, is_ascii
    b = Base("┗", "─", "┛")
    lay(Pattern(), 5, b)        # ("┗", "─", "─", "─", "┛"): the base drawing
    p = pattern(start="▙", fill="─┴─", end="///")
    lay(p, 10, b)               # ("▙", "─", "┴", "─", "─", "┴", "─", "/", "/", "/")
    lay(p, 4, b)                # ("▙", "/", "/", "/"): the ends just fit, no fill
    lay(p, 3, b)                # ("┗", "─", "┛"): too short, one-cell ends, p's fill
    lay(p, 1, b), lay(p, 0, b)  # ("─",), ()
    lay(pattern(fill="中"), 5, b)   # ("┗", "中", "", "─", "┛"): cut at the boundary
    pattern(fill="中", vertical=True)
    # ThemeError: "<pattern>: pattern.fill: cluster 1 (U+4E2D) is 2 cells wide; a
    # vertical run takes one cell per row"
    is_ascii(p), is_ascii(pattern(fill="-="))   # False, True
    lay_parts(p, 6, b)          # (("▙", "start"), ("─", "fill"), ("┴", "fill"),
                                #  ("/", "end"), ("/", "end"), ("/", "end"))
    lay_parts(p, 3, b)          # (("┗", "base"), ("─", "fill"), ("┛", "base"))
    lay_parts(pattern(end="//"), 4, b)  # (("┗", "base"), ("─", "base"), ("/", "end"), ("/", "end"))

    # the after (round 13): wire's foot, a tenth of the run in ▀ over the fill
    r = Base("╰", "─", "╯")
    w = Pattern(("▙",), ("─", "┴", "─"), ("/", "/", "▔"), after=("▀",), share=0.10)
    w == pattern(start="▙", fill="─┴─", end="//▔", after="▀", share=0.10)   # True
    "".join(lay(w, 25, r))      # "▙▀▀──┴──┴──┴──┴──┴──┴─//▔": m 21, k round(2.5) == 2
    "".join(lay(w, 15, r))      # "▙▀▀──┴──┴──┴//▔": m 11, k round(1.5) == 2
    "".join(lay(w, 13, r))      # "▙▀┴──┴──┴─//▔": m 9, k round(1.3) == 1
    "".join(lay(w, 6, r))       # "▙▀┴//▔": m 2, k max(1, round(0.6)) == 1
    "".join(lay(w, 5, r))       # "▙▀//▔": m 1, k max(1, round(0.5) == 0) == 1
    "".join(lay(w, 4, r))       # "▙//▔": m 0, so k 0: no after
    "".join(lay(w, 3, r)), "".join(lay(w, 2, r))   # "╰─╯", "╰╯": rule 2, no after
    lay(w, 1, r), lay(w, 0, r)  # ("─",), (): rule 3
    lay_parts(w, 13, r)         # (("▙", "start"), ("▀", "after"), ("┴", "fill"), ("─", "fill"),
                                #  ("─", "fill"), ("┴", "fill"), ("─", "fill"), ("─", "fill"),
                                #  ("┴", "fill"), ("─", "fill"), ("/", "end"), ("/", "end"), ("▔", "end"))
    lay_parts(w, 5, r)          # (("▙", "start"), ("▀", "after"), ("/", "end"), ("/", "end"), ("▔", "end"))
    lay_parts(w, 4, r)          # (("▙", "start"), ("/", "end"), ("/", "end"), ("▔", "end"))
    lay_parts(Pattern(fill=("中",), after=("▀",), share=0.5), 6, r)
    # (("╰", "base"), ("▀", "after"), ("▀", "after"), ("▀", "after"), ("─", "base"), ("╯", "base")):
    # k 3 over 中 "" 中 "": the second 中's tail, orphaned, is base.fill
    lay_parts(Pattern(fill=("─",), after=("中",), share=0.6), 5, r)
    # (("╰", "base"), ("中", "after"), ("", "after"), ("─", "base"), ("╯", "base")):
    # k 3: cut(("中",), 3) is 中, its tail, and base.fill for the cell a second 中 would overrun
    lay_parts(Pattern(after=("▀",), share=0.5), 4, Base(None, "│", None))
    # (("▀", "after"), ("▀", "after"), ("│", "base"), ("│", "base")): k round(2.0) == 2
    Pattern(after=("▀",))       # ThemeError: "<pattern>: Pattern.after is given with no share"
    Pattern(fill=("─",), share=0.5)   # ThemeError: "<pattern>: Pattern.share is given with no after"
    Pattern(after=("▀",), share=0)    # ThemeError: "<pattern>: Pattern.share must be > 0 and <= 1, got 0"
    Pattern(after=("▀",), share=True) # TypeError: "Pattern.share must be None or a number, got bool"
    is_ascii(Pattern(fill=("-",), after=("▀",), share=1))   # False: the after counts
"""

from dataclasses import dataclass, field

from cure.core.text import cluster, width
from cure.core.text.width import control

from .parse import ThemeError

WHERE: tuple[str, None] = ("<pattern>", None)
"""The default `where` of a ThemeError raised here: no source line known."""


@dataclass(frozen=True)
class Pattern:
    """{Pattern}: a run's start, fill and end, each a tuple of clusters (`()`: not given),
    and an optional after (a part, keyword-only) with its share of the run.

    Checked in `__post_init__` by `clusters`' rules, `share`'s type and range and their
    pairing (see the module's Data); hashable.
    """

    start: tuple = ()
    fill: tuple = ()
    end: tuple = ()
    vertical: bool = field(default=False, kw_only=True)
    after: tuple = field(default=(), kw_only=True)
    share: "float | None" = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        for part in _PARTS:                       # every TypeError first, parts in turn
            value = getattr(self, part)
            if isinstance(value, str):
                raise TypeError(f"Pattern.{part} must be a tuple of clusters, got str "
                                "(split a string with pattern())")
            try:
                items = tuple(value)
            except TypeError:
                raise TypeError(f"Pattern.{part} must be a tuple of clusters, got "
                                f"{type(value).__name__}") from None
            for i, item in enumerate(items, 1):
                if not isinstance(item, str):
                    raise TypeError(f"Pattern.{part}: item {i} must be a str, got "
                                    f"{type(item).__name__}")
            object.__setattr__(self, part, items)
        if not isinstance(self.vertical, bool):
            raise TypeError(f"Pattern.vertical must be a bool, got "
                            f"{type(self.vertical).__name__}")
        share = self.share
        if share is not None and (isinstance(share, bool) or not isinstance(share, (int, float))):
            raise TypeError(f"Pattern.share must be None or a number, got {type(share).__name__}")
        for part in _PARTS:                       # then the ThemeErrors, items in order
            name = f"Pattern.{part}"
            for i, item in enumerate(getattr(self, part), 1):
                if not item or cluster(item) != (item,):
                    raise ThemeError(*WHERE, f"{name}: item {i} is not one grapheme cluster")
                _no_control(item, name, WHERE)
                _fits(item, i, self.vertical, name, WHERE)
        if share is not None and not 0 < share <= 1:   # a NaN fails it too
            raise ThemeError(*WHERE, f"Pattern.share must be > 0 and <= 1, got {share!r}")
        if self.after and share is None:
            raise ThemeError(*WHERE, "Pattern.after is given with no share")
        if share is not None and not self.after:
            raise ThemeError(*WHERE, "Pattern.share is given with no after")


@dataclass(frozen=True)
class Base:
    """A run's base drawing: one glyph each for its start, fill and end, each one cell."""

    start: str
    fill: str
    end: str

    def __post_init__(self) -> None:
        for part in _BASE_PARTS:                  # field by field: its type, then emptiness
            x = getattr(self, part)
            if part == "fill" and not isinstance(x, str):
                raise TypeError(f"Base.fill must be a str, got {type(x).__name__}")
            if x is None:                         # an end may be None: the run has none there
                continue
            if not isinstance(x, str):
                raise TypeError(f"Base.{part} must be None or a str, got {type(x).__name__}")
            if not x:
                raise ValueError(f"Base.{part} is empty")


_PARTS = ("start", "fill", "end", "after")
_BASE_PARTS = ("start", "fill", "end")


def _no_control(text: str, name: str, where: tuple) -> None:
    """Rule 3: the first control code point in `text` refused (Parse's wording)."""
    for ch in text:
        if control(ch):
            raise ThemeError(*where, f"{name}: control character U+{ord(ch):04X}")


def _fits(c: str, i: int, vertical: bool, name: str, where: tuple) -> None:
    """Rule 4 for cluster `c` at 1-based index `i`: width 0, or wide on a vertical run."""
    w = width(c)
    if w == 0:
        raise ThemeError(*where, f"{name}: cluster {i} (U+{ord(c[0]):04X}) has width 0")
    if vertical and w > 1:
        raise ThemeError(*where, f"{name}: cluster {i} (U+{ord(c[0]):04X}) is {w} cells "
                                 "wide; a vertical run takes one cell per row")


def clusters(text: str, *, vertical: bool = False, name: str = "pattern",
             where: "tuple[str, int | None]" = WHERE) -> tuple:
    """One part's text as clusters, each checked (width 0, or wide on a vertical run, refused)."""
    if not isinstance(text, str):
        raise TypeError(f"{name} must be a str, got {type(text).__name__}")
    if not text:
        return ()
    _no_control(text, name, where)
    cs = cluster(text)
    for i, c in enumerate(cs, 1):
        _fits(c, i, vertical, name, where)
    return cs


def pattern(start: str = "", fill: str = "", end: str = "", *, vertical: bool = False,
            after: str = "", share: "int | float | None" = None, name: str = "pattern",
            where: "tuple[str, int | None]" = WHERE) -> Pattern:
    """The {Pattern} of four part texts, each split by `clusters` (`name.start`, ...), and a share."""
    s, f, e, a = (clusters(text, vertical=vertical, name=f"{name}.{part}", where=where)
                  for part, text in zip(_PARTS, (start, fill, end, after)))
    return Pattern(s, f, e, vertical=vertical, after=a, share=share)


def lay(pattern: Pattern, n: int, base: Base) -> tuple:
    """The run's n cells by the fits law: one glyph per cell, `""` for a wide cluster's tail."""
    _lay_checks(pattern, n, base)
    bs, be = _base_end(base.start), _base_end(base.end)
    start = _cells(pattern.start) if pattern.start else bs
    end = _cells(pattern.end) if pattern.end else be
    ws, we = len(start), len(end)                 # cells: a wide cluster and its tail
    if ws + we <= n:                              # rule 1: the ends fit
        m = n - ws - we
        mid = _cut(pattern.fill, m, base)
        if pattern.after and m:                   # the after over the fill's first k cells
            k = min(max(1, round(pattern.share * n)), m)
            head = _cut(pattern.after, k, base)
            mid = head + ((base.fill,) + mid[k + 1:] if k < m and mid[k] == "" else mid[k:])
        return start + mid + end
    if len(bs) + len(be) <= n:                    # rule 2: both ends fall back to the base's
        return bs + _cut(pattern.fill, n - len(bs) - len(be), base) + be
    return (base.fill,) * n                       # rule 3: the base whole


def _lay_checks(pattern: object, n: object, base: object) -> None:
    """`lay`'s (and `lay_parts`') argument checks, in order."""
    _is_pattern(pattern)
    if not isinstance(base, Base):
        raise TypeError(f"base must be a Base, got {type(base).__name__}")
    if not isinstance(n, int) or isinstance(n, bool):
        raise TypeError(f"n must be an int, got {type(n).__name__}")
    if n < 0:
        raise ValueError(f"n must be >= 0, got {n}")


def _base_end(glyph: "str | None") -> tuple:
    """A base end as its cells: the glyph alone, or `()` for a run with no end there."""
    return () if glyph is None else (glyph,)


def _cells(parts: tuple) -> tuple:
    """Each pattern cluster as its cells: `(c,)`, or `(c, "")` for a wide one."""
    out = []
    for c in parts:
        out += (c,) if width(c) == 1 else (c, "")
    return tuple(out)


def _cut(fill: tuple, m: int, base: Base) -> tuple:
    """`m` cells of the fill, cut at a cluster boundary (`()`: the base fill, alone)."""
    if not fill:
        return (base.fill,) * m                   # a base part counts one cell
    out, r, i = [], m, 0
    while r > 0:
        c = fill[i % len(fill)]
        w = width(c)
        if w > r:                                 # r == 1, a wide cluster: the base fills
            out.append(base.fill)
            break
        out += (c,) if w == 1 else (c, "")
        r -= w
        i += 1
    return tuple(out)


def _is_pattern(pattern: object) -> None:
    """`lay`'s and `is_ascii`'s argument check."""
    if not isinstance(pattern, Pattern):
        raise TypeError(f"pattern must be a Pattern, got {type(pattern).__name__}")


def is_ascii(pattern: Pattern) -> bool:
    """Every cluster of every part is ASCII (True for the empty pattern)."""
    _is_pattern(pattern)
    return all(c.isascii() for c in pattern.start + pattern.fill + pattern.end + pattern.after)


CELL_PARTS: tuple[str, ...] = ("start", "fill", "end", "after", "base")
"""The part a laid cell came from (`lay_parts`): one of the pattern's four, or the base's."""


def lay_parts(pattern: Pattern, n: int, base: Base) -> tuple:
    """`lay`'s n cells, each with the part it was laid from: `(glyph, part)`, part in CELL_PARTS."""
    _lay_checks(pattern, n, base)
    bs = _tagged(_base_end(base.start), "base")
    be = _tagged(_base_end(base.end), "base")
    start = _tagged(_cells(pattern.start), "start") if pattern.start else bs
    end = _tagged(_cells(pattern.end), "end") if pattern.end else be
    if len(start) + len(end) <= n:                # rule 1: the ends fit
        m = n - len(start) - len(end)
        mid = _cut_parts(pattern.fill, m, base)
        if pattern.after and m:                   # the after over the fill's first k cells
            k = min(max(1, round(pattern.share * n)), m)
            head = _cut_parts(pattern.after, k, base, "after")
            mid = head + (((base.fill, "base"),) + mid[k + 1:] if k < m and mid[k][0] == ""
                          else mid[k:])
        return start + mid + end
    if len(bs) + len(be) <= n:                    # rule 2: both ends fall back to the base's
        return bs + _cut_parts(pattern.fill, n - len(bs) - len(be), base) + be
    return ((base.fill, "base"),) * n             # rule 3: the base whole


def _tagged(cells: tuple, part: str) -> tuple:
    """Each cell (a tail included) as `(glyph, part)`."""
    return tuple((g, part) for g in cells)


def _cut_parts(fill: tuple, m: int, base: Base, part: str = "fill") -> tuple:
    """`_cut`'s m cells, each tagged: `part` from a pattern cluster, `"base"` from `base.fill`."""
    if not fill:
        return ((base.fill, "base"),) * m
    out, r, i = [], m, 0
    while r > 0:                                  # `_cut`'s walk
        c = fill[i % len(fill)]
        w = width(c)
        if w > r:                                 # the leftover cell: the base's
            out.append((base.fill, "base"))
            break
        out += ((c, part),) if w == 1 else ((c, part), ("", part))
        r -= w
        i += 1
    return tuple(out)
