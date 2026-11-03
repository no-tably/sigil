"""[Charset]: primitive → token → glyph: borders (light, heavy, double, rounded, dashed
╌╎, dotted ┄┆, heavy-dashed ╍╏, ascii), guides, twisties, leaders, marks, spinners,
blocks, braille, sextants, powerline, arrows (▶ ◀ ▲ ▼; ascii > < ^ v).

Kind: service (a data class, three built-in tables and pure functions).

What it does: a widget asks for a primitive (a border part of a weight, a guide, a
state's mark, a spinner's frame); the primitive names a TOKEN (`border.light.tl`,
`mark.focused`, `spinner.dots`); the charset gives the token's glyph. A {Charset} is
plain data passed in a {Context} (Canvas and Widgets read it; they never pick glyphs
themselves). `glyphs(raw)` builds one from a theme's `charset` section over a
built-in base.

The tokens (each glyph a non-empty `str` with no control character; most are one
cluster, a spinner is a string of frames and `ellipsis` may be several characters):

- borders, `border.<weight>.<part>` for each weight in `BORDERS` (`light`, `heavy`,
  `double`, `rounded`, `dashed`, `dotted`, `heavy-dashed`, `ascii`: every Canvas
  weight has glyphs) and part in `PARTS` (`tl`, `tr`, `bl`, `br` corners; `h`, `v`
  lines; `tee_l` (├, on a left edge), `tee_r` (┤), `tee_t` (┬, on a top edge),
  `tee_b` (┴); `cross` (┼)). The stroke glyphs follow sigil's kit (README decision
  5): `dashed` ╌ (h) ╎ (v), `dotted` ┄ (h) ┆ (v), `heavy-dashed` ╍ (h) ╏ (v).
  Box drawing has no dashed corners or tees, so `dashed` and `dotted` take the
  light ones (┌┐└┘├┤┬┴┼) and `heavy-dashed` the heavy ones (┏┓┗┛┣┫┳┻╋);
- guides (trees): `guide.branch` ├, `guide.last` └, `guide.vert` │, `guide.stem` ─;
- twisties: `twisty.open` ▾, `twisty.closed` ▸;
- leaders and overflow: `leader` (the key:value dash leader) -, `ellipsis` …,
  `more.down` ↓, `more.up` ↑ (the `↓N more` row);
- marks, one per state that has one ([States]): `mark.focused` ›, `mark.selected` •,
  `mark.pressed` ●, `mark.active` ●, `mark.emphasised` ✦, `mark.muted` ·;
- controls (Button's face, W1a): `control.check` • (a toggle's on glyph),
  `control.radio` ● (a radio's on glyph), `control.knob` ● and `control.track` ─ (a
  switch's knob and track). In each base each equals the glyph Button drew in that
  cell before the tokens (`mark.selected`, `mark.active`, `mark.active`,
  `border.light.h`), so every frame at a base charset is unchanged; they are their
  own tokens (overriding `mark.active` no longer moves a radio, and a theme's
  `charset.control.radio` moves the radio's on glyph and nothing else);
- spinners, a string whose code points are the frames: `spinner.dots`
  ⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏, `spinner.line` -\\|/, `spinner.pulse` ⣾⣽⣻⢿⡿⣟⣯⣷;
- blocks: `block.full` █, `block.light` ░, `block.medium` ▒, `block.dark` ▓,
  `block.eighths.h` (9 code points, index i = i eighths filled from the left:
  " ▏▎▍▌▋▊▉█"), `block.eighths.v` (from the bottom: " ▁▂▃▄▅▆▇█");
- arrows (heads, by the way they point; README decision 9): `arrow.right` ▶ U+25B6,
  `arrow.left` ◀ U+25C0, `arrow.up` ▲ U+25B2, `arrow.down` ▼ U+25BC. Each is the bare
  code point (no variation selector: text presentation, never the emoji form) and one
  cell wide (East Asian Width A, narrow under Text's width table; the ascii glyphs are
  one cell too). Graph's Diagram puts one on the cell where a wire meets its target,
  the head pointing the way the wire travels into it (a wire entering from the left
  takes `arrow.right`). They are rows of `UNICODE` (so of `POWERLINE`, which spreads
  it) and of `ASCII`, beside the blocks;
- powerline (the `powerline` base only; it needs a patched font):
  `powerline.right` U+E0B0, `powerline.right_thin` U+E0B1, `powerline.left`
  U+E0B2, `powerline.left_thin` U+E0B3.

Sub-cell plots are a property, not glyphs: `Charset.plots` lists the plot modes a
canvas may use, finest first, from `PLOTS` (`braille` 2x4 dots per cell,
`sextant` 2x3, `quadrant` 2x2, `half` 1x2, `block` 1x1, `ascii`); Canvas computes the
code points.

The three bases (`BASES`), the tables `UNICODE`, `POWERLINE` and `ASCII` below, are
the exact glyphs (the module constants are part of this contract):

- `unicode`: every token above but the powerline ones; plots `("braille",
  "sextant", "quadrant", "half", "block")`. The `ascii` border weight is in it too
  (`+`, `-`, `|`), so a widget may ask for ascii borders on a unicode terminal.
  The weights' rows are the table's, in full, below.
- `powerline`: `UNICODE` plus the four powerline tokens; the same plots.
- `ascii`: every token in plain ASCII (borders `+` `-` `|`, double and heavy `h` `=`;
  `dashed`, `dotted` and `heavy-dashed` the plain ASCII box `+` `-` `|`;
  guides `+` `` ` `` `|` `-`; twisties `v` `>`; marks `>` `*` `@` `*` `+` `.`;
  controls (check, radio, knob, track) `*` `*` `*` `-`; leader
  `-`; ellipsis `...`; more `v` `^`; spinners `-\\|/`; blocks (full, light, medium,
  dark) `#` `:` `%` `#`, eighths (`h` and `v` alike) " ,-~=+*%#"; arrows `>` `<` `^`
  `v` (right, left, up, down); powerline `>` `>` `<` `<`); plots `("ascii",)`.

The ASCII blocks and eighths (T1r; they were light `.`, medium `:`, eighths
" .:-=+*#@", under which a Bar's empty track `###...` read as a cut). Their laws:

- no block glyph and no eighths code point holds a character of `ASCII["ellipsis"]`
  (none is `.`), so no run of them (a Bar's or Gauge's cells, a Pulse's track, a
  Sparkline's columns, a Bars row) can contain the ellipsis: under ASCII, as under
  Unicode, `...` in a widget's cells means a cut and nothing else;
- `block.light` (`:`) is not `block.full` and not one of the eighths' steps 1..7, so
  a bar's partial cell, its filled cells and its empty track differ in glyph; it is
  none of the line, leader, guide or ellipsis glyphs (`-` `|` `=` `+` `` ` `` `.`),
  so an empty Bar or Gauge (`::::::`) reads as neither a rule, a leader nor a cut;
- the eighths' steps 1..8 are pairwise distinct, rising in ink, and step 8 is
  `block.full` (`#`), as in `UNICODE` (█): a whole cell reads the same from a Bar,
  `Bars`, a Sparkline or Plot's `bar` / `spark`;
- `block.medium` (`%`) is not `block.light`, so the shades stay ordered light <
  medium < dark, and not `block.full` (Views' minimap draws its built blocks with it,
  M1); `block.dark` stays `#` (ASCII has no shade between `%` and `#`; no widget draws
  `block.dark`).

Looking a glyph up (`Charset.glyph(token) -> str`): the charset's own glyph; else
`ASCII`'s glyph for the token (the ascii fallback: a charset missing a token still
draws, in ASCII); else `""` (an unknown token draws nothing; never an error).
`Charset.border(weight, part)` is `glyph(f"border.{weight}.{part}")`, with a weight
not in `BORDERS` taken as `light`. `Charset.frame(spinner, tick)` is the
`tick % n`-th code point of `glyph(f"spinner.{spinner}")` (n its length; `""` when
it is empty); `tick` an `int` (`bool` refused: `TypeError`), negative ticks wrap as
Python's `%` does.

Building one (`glyphs(raw=None, *, ascii=False) -> Charset`), from the leaves under
`("charset",)` of a {Raw} (`None`: no section):

- the base: `charset.base` (or `charset` as a scalar: `charset: ascii`), one of
  `BASES`; absent: `unicode`. Both forms at once, or a name not in `BASES`, is a
  ThemeError at the leaf ("charset.base must be one of ...").
- `charset.plots`: the plot modes, split on spaces, each in `PLOTS`, no repeats
  (ThemeError otherwise); absent: the base's.
- a leaf under `charset.frame` or `charset.run` is a pattern leaf (see Patterns):
  never a glyph;
- every other leaf `("charset", *token)` overrides the glyph of the token
  `".".join(token)` (any token name: the set is open; `charset.arrow.right: "→"`
  overrides a head like any other token). Its value must be non-empty
  (ThemeError "charset.x: empty glyph"); a value is literal (`$` is not a
  reference here). A glyph's width is not checked (an arrow override of other than
  one cell is the theme's to answer for, as for every token).
- `ascii=True` (the app's fallback for a terminal that cannot show Unicode): the
  base is `ascii` whatever the theme says, every override holding a non-ASCII
  character is dropped, and plots are `("ascii",)`.
- the result: `Charset(name=<base>, glyphs={**BASE_TABLE, **overrides}, plots=...,
  patterns=..., part_roles=...)` (Patterns: built, checked, and under the ascii base
  dropped as below).

Patterns (R3a; refine round 7, its Q3 and Q4 and the roles addendum). A leaf under
`charset.frame` or `charset.run` is a PATTERN leaf, never a glyph token: it names one
part of a run's {Pattern} ([Pattern], `pattern.py`), or that part's role. The run
names (the user's, settled):

| run | its part leaves | vertical |
| --- | --- | --- |
| `frame.<kind>.<edge>` | `frame.<kind>.<edge>.<part>` | edge `left` / `right` |
| `frame.<kind>.<weight>.<edge>` | `frame.<kind>.<weight>.<edge>.<part>` | the same |
| `frame.gutter.<axis>` | `frame.gutter.<axis>.<part>` | axis `x` |
| `run.<widget>.<part>` | `run.<widget>.<part>.<partname>` | always (below) |

with `<part>` (and `<partname>`) one of `PATTERN_PARTS` (`start`, `fill`, `end`,
`after`; round 13 adds `after`, so `<run>.after` is a part leaf and `<run>.after.role`
a role leaf like the others),
`<edge>` one of `EDGES` (`top`, `bottom`, `left`, `right`), `<axis>` one of `AXES`
(`x`: the vertical strip between side-by-side panes; `y`: the horizontal one between
stacked panes), `<weight>` one of `BORDERS`, and `<kind>`, `<widget>`, `<part>` of a
`run.` any one key segment, except that the kind `gutter` is the gutters' own (a
`frame.gutter.<edge>...` or `frame.gutter.<weight>...` leaf is not a pattern leaf).
Each part leaf may have a ROLE leaf, its own path followed by `role`
(`frame.pane.bottom.end.role: accent`). An `after` part leaf has, and must have, a
SHARE leaf, its own path followed by `share` (`frame.pane.bottom.after.share: 0.10`:
the after's share of the run, [Pattern]'s `share`); no other part has one. [Parse] holds a leaf and a leaf below it at
once (its rule 12: a path may be both a leaf and a prefix of other leaves), written
with a dotted key beside it, since a YAML scalar cannot open a map:

    charset:
      frame.pane.bottom:
        start: "▙"
        fill: "─┴─"
        end: "///"
        end.role: accent
        after: "▀"
        after.share: 0.10

The leaf grammar, after `charset.` (each leaf in the Raw's order; `token` is the
leaf's path joined with dots, `where` its `(source, line)`; every error a ThemeError
at `where`):

1. The last segment is `role`: a ROLE leaf, its part leaf the path without it, which
   must have a part leaf's shape by rule 2 (else `f"charset.{token}: not a pattern
   leaf"`, `token` the role leaf's). The value must be non-empty (`f"charset.{token}:
   empty role"`) and a role name: one KEY ([Parse]'s `KEY`, a dotted role such as
   `accent` or `progress.fill`), optionally prefixed `"<kind>:"` with `<kind>` one
   NAME segment (`muted:accent`, Theme's derived styles); otherwise
   `f"charset.{token}: bad role name '{value}'"`. The theme must give the part leaf
   itself (in this Raw, after `extends` is followed): a role leaf whose part leaf is
   absent is `f"charset.{token}: a role for a part the theme does not give"` (a part
   not given is drawn from the base, and base cells never take a part role, below).
2. Otherwise a PART leaf when its path is one of the four shapes of the table; any
   other leaf under `frame` or `run` (`charset.frame: x`, `frame.pane.middle.start`,
   `frame.pane.top.begin`, `frame.pane.bold.top.start`, `frame.gutter.top.fill`,
   `run.progress.fill`, a seventh segment) is `f"charset.{token}: not a pattern
   leaf"` (a typo there would otherwise draw nothing, silently). An empty value is
   `f"charset.{token}: empty glyph"` (as for a glyph). The value is split by
   [Pattern]'s `clusters(value, vertical=<the run's>, name=f"charset.{token}",
   where=where)`, so a control, a width-0 cluster, or (vertical) a wide one is its
   ThemeError, e.g. `"pane.yaml:12: charset.frame.pane.left.fill: cluster 1 (U+4E2D)
   is 2 cells wide; a vertical run takes one cell per row"`. An `after` part leaf is
   split the same way (vertical as its run).
3. The last segment is `share` (round 13): a SHARE leaf, its part leaf the path
   without it, which must have a part leaf's shape by rule 2 AND end in `after`
   (`frame.pane.bottom.fill.share`, `frame.pane.bottom.share` and a share under a
   path of no run shape are `f"charset.{token}: not a pattern leaf"`, `token` the
   leaf's own; rule 1 is tested first, so `frame.pane.bottom.after.share.role` is a
   role leaf whose part leaf has no part shape: rule 1's "not a pattern leaf"). The
   value, as Parse gives it (a `str`: a trailing comment and the quotes of a quoted
   scalar already gone), must fullmatch `[0-9]+(?:\\.[0-9]*)?|\\.[0-9]+` (ASCII digits
   with at most one point and a digit on at least one side of it: `0.10`, `.5`, `1`,
   `1.`, `1.0`, `0.25`; no sign, exponent, underscore, space, `inf` or `nan`), else
   `f"charset.{token}: share '{value}' is not a number"` (`''` included: an empty
   share is not a number); its number `float(value)` must satisfy `0 < share <= 1`,
   else `f"charset.{token}: share {value} is out of range (0 < share <= 1)"` (`value`
   as written: `share 0 is out of range ...`, `share 1.5 is out of range ...`); and the
   theme must give the after part leaf itself (in this Raw, after `extends` is
   followed), else `f"charset.{token}: a share for an after part the theme does not
   give"` (as a role's). An after part leaf given with no share leaf is
   `f"charset.{token}: an after part with no share (give charset.{token}.share)"` at
   the AFTER leaf's `where`, `token` the after leaf's.

Rule 1 is checked for every role leaf after rule 2 has passed for every part leaf
(so a bad glyph is reported before a role that names it). Rule 3 is checked in the
same pass as rule 1: once every part leaf has passed rule 2, the role and share
leaves in the Raw's leaf order, each by its own rule, each share leaf's checks in the
order above (shape, number, range, its after given), the first failure raised (so of
two bad leaves the earlier is reported); then, once all have passed, every after part
leaf with no share leaf, in leaf order (so a bad share is reported before a missing
one). Whether a role RESOLVES is
not checked here (a Charset holds no roles): the Theme build checks it (Theme's
`_build`, below and in the package).

A run's Pattern is `Pattern(start, fill, end, vertical=v, after=after, share=share)`
of its part leaves' clusters (`()` for a part not given) and its share leaf's number
(`float(value)`; `None` with no after), built when at least one part leaf names the
run (a share leaf alone builds nothing: it needs its after). The rules above already
hold every leaf to Pattern's checks, so building it never raises. Vertical
runs: `frame.<kind>[.<weight>].left` and `.right` (one cell per row, so a frame never
eats the inside), `frame.gutter.x`, and every `run.` run: a widget may lay its run
along either axis (Scrollbar's `axis` is `x` or `y`), so its clusters are held to one
cell each, which lays the same both ways. The horizontal runs (`top`, `bottom`,
`frame.gutter.y`) may hold wide clusters.

The ascii drop: at BUILD, never at lookup. When the charset built is the `ascii` base
(`charset.base: ascii`, or `glyphs(..., ascii=True)`), every run whose Pattern is not
`is_ascii` (its after included: a non-ASCII after drops the run though every other
part is ASCII) is dropped whole (its part roles and its share with it), after every
leaf above has been checked (so a theme loads, or fails, the same way in both modes). Built, not looked
up, because a Charset is immutable and built once per mode (Theme's memo keys on
`ascii`): its patterns are then exactly what it draws, `pattern` is a plain lookup,
and the drop is a fact of the data a test can read (`cs.patterns`), as the dropped
glyph overrides are. A dropped weighted run lets the plain run answer for its
weight (when that one is ASCII), as if the weighted run were never declared.
(Note the difference from glyph overrides: those are dropped under `ascii=True` only;
a pattern is dropped under the ascii base too, so an ascii charset never lays a
non-ASCII run cell.)

Data, beside `glyphs` (see the dataclass below):
- `Charset.patterns: Mapping[str, Pattern]`: run name (`"frame.pane.bottom"`,
  `"frame.pane.heavy.top"`, `"frame.gutter.x"`, `"run.progress.track"`) -> its
  Pattern (its `after` and `share` included), in the order each run's first part leaf
  appears; only runs with a part given (never an empty Pattern), the dropped ones
  absent. The share lives in the Pattern only (no mapping of its own).
- `Charset.part_roles: Mapping[str, str]`: `f"{run}.{part}"` (`"frame.pane.bottom.end"`)
  -> the role name as written (`"accent"`), for every role leaf whose run is in
  `patterns`.

Looking a pattern up (`Charset.pattern(run, weight=None) -> Pattern`), for the widgets
and Context's run op:
1. `run` not a `str`, or `weight` neither `None` nor a `str`: `TypeError(f"run must be
   a str, got {type(run).__name__}")` / `TypeError(f"weight must be a str or None, got
   {type(weight).__name__}")`.
2. Weight first: when `weight` is a `str` and `run` is `frame.<kind>.<edge>` (three
   segments, `<edge>` in `EDGES`, `<kind>` not `gutter`), the run `frame.<kind>.
   <weight>.<edge>` when it is in `patterns`: its Pattern, WHOLE (a part it does not
   give falls back to the base, never to the plain run's part: a weighted run is a
   look of its own, round 7 Q4).
3. Else `patterns[run]` when present.
4. Else `Pattern()`, the empty pattern (it lays as the base: base_unchanged). So an
   unknown run, a malformed name, a weight on a `run.` or gutter run, a weight not in
   `BORDERS` and a dropped run are never errors: they draw as before.
The run chosen by 2-3 (or None at 4) is `Charset.chosen(run, weight=None) -> str |
None`, so the pattern and its roles are always read from the same run.

Looking a part's role up (`Charset.role(run, part, weight=None) -> str | None`):
`part_roles.get(f"{c}.{part}")` with `c = chosen(run, weight)`; `None` when `c` is
None or that part names no role (`role(run, "after")` answers `<run>.after.role`
exactly as for the other parts, `after` being one of `PATTERN_PARTS`). `part` must be a `str` (`TypeError(f"part must be a
str, got {type(part).__name__}")`); a `part` outside `PATTERN_PARTS` gives `None`.
A separate lookup rather than a richer `pattern` return: [Pattern] stays the
names-free, role-free value `lay` takes (the sigil flow `pattern({Token}) =>
{Pattern}`), a widget that only lays cells never unpacks roles, and the run op asks
`role` once per part it actually lays.

Role leaves read from a Raw, for the Theme build's check (`role_leaves(raw) ->
tuple[tuple[str, str, tuple[str, int | None]], ...]`): each role leaf of `raw`'s
`charset` section by the grammar above, in leaf order, as `(f"charset.{token}",
role, where)`, whatever the ascii drop does; `()` for `None` or no section. It checks
nothing a `glyphs(raw)` would not (call it after `glyphs`).

Data (frozen dataclass; immutable all the way down, Theme's rule):
- `Charset(name: str = "unicode", glyphs: Mapping[str, str] = UNICODE copy, plots:
  tuple[str, ...] = UNICODE_PLOTS, patterns: Mapping[str, Pattern] = {}, part_roles:
  Mapping[str, str] = {})` (R3a adds the last two, defaulting empty: every Charset
  built before R3a, and `Charset()`, has no patterns; both read-only like `glyphs`,
  their values immutable already, Pattern being frozen; `__reduce__` rebuilds them
  from plain dict copies; equality by value as today; `glyphs` holds no pattern
  leaf, so `glyph("frame.pane.top.start")` is `""` like any unknown token). `glyphs` is read-only (`__post_init__` stores it
  as a `types.MappingProxyType` over a private `dict` copy of the mapping given, the
  default a copy of `UNICODE`: writing raises, the caller's dict is not kept, so
  `Charset("ascii", ASCII)` holds its own copy; `==` with a plain dict holds);
  `plots` is stored as a `tuple` (a list given becomes one). `__reduce__` rebuilds
  from a plain dict copy (copy and pickle as today). Not hashable (`hash` raises
  `TypeError`, as today). The freezing and the rebuild go through [Parse]'s public
  `freeze_maps(self, "glyphs", "patterns", "part_roles")`, `freeze_seqs(self,
  "plots")` and `rebuild(self)` (Q9b: never Parse's private `_freeze`, `_tuples`,
  `_reduce`).
- The tables `UNICODE`, `POWERLINE`, `ASCII` (what `glyph` falls back to at call
  time) and `TABLES` are read-only `types.MappingProxyType`s, their contents as
  today; `TABLES` maps a base to `(that table, its plots)`. `glyphs` builds `{**base,
  **overrides}` from them and never writes one.

Inputs: `glyphs`: a {Raw} or None, `ascii: bool`. `glyph`: `token: str`. `border`:
  `weight: str`, `part: str`. `frame`: `spinner: str`, `tick: int`. `pattern` /
  `chosen`: `run: str`, `weight: str | None`. `role`: `run: str`, `part: str`, `weight:
  str | None`. `role_leaves`: a {Raw} or None.
Outputs: `glyphs`: a {Charset}. `glyph`, `border`, `frame`: a `str`. `pattern`: a
  {Pattern}. `chosen`, `role`: a `str` or None. `role_leaves`: a tuple of `(leaf, role,
  where)`.
Errors: `glyphs`: ThemeError as above (Patterns' messages included). `glyph` /
  `border` / `frame` / `pattern` / `chosen` / `role`: `TypeError` for a non-`str`
  token, run, part or weight (None allowed for a weight) or a non-`int` tick; never
  for an unknown token or run. `role_leaves`: none for a Raw `glyphs` accepts.
Effects: none.

Laws (R3a; a test loops over themes of pattern leaves, both modes, every weight):
- base_unchanged: a charset section with no `frame` / `run` leaf gives `patterns ==
  {}` and `part_roles == {}`, and its `glyphs`, `plots` and `name` are exactly what
  they were before R3a (the builtin's and every shelf theme's included), so every
  `pattern(...)` is `Pattern()` and every `role(...)` None.
- weight_first: with both `frame.k.<w>.e` and `frame.k.e` declared, `pattern("frame.k.e",
  w) == patterns["frame.k.<w>.e"]` and `pattern("frame.k.e", w2) ==
  patterns["frame.k.e"]` for any other weight `w2` (or None); `role` follows the same
  run (`chosen`).
- ascii_drop: for `cs = glyphs(raw, ascii=True)` (or a raw of base ascii), every
  Pattern in `cs.patterns` is `is_ascii`, every run of the non-ascii build whose
  Pattern is `is_ascii` is kept unchanged, and every key of `cs.part_roles` names a
  run in `cs.patterns`; `glyphs(raw, ascii=True)` raises exactly when `glyphs(raw)`
  does (the same error).
- unknown_run: `pattern(r, w)` is `Pattern()` and `role(r, p, w)` is None for any run
  name not declared (never an error for a `str`).
- checked: every Pattern in `patterns` obeys [Pattern]'s `checked` (it was built by
  `clusters`), vertical as the table says; its `share` is its run's share leaf's
  `float`, None exactly when it has no after.
- share (round 13): for a run with leaves `after: a` and `after.share: v` (v matching
  the share spelling, `0 < float(v) <= 1`), `patterns[run].after == clusters(a, ...)`
  and `patterns[run].share == float(v)`; removing either leaf, or giving a share to
  another part of the run, is a ThemeError at load, in both modes alike.

Usage:
    from cure.draw.theme.charset import glyphs
    from cure.draw.theme.parse import parse
    cs = glyphs()
    cs.border("rounded", "tl"), cs.glyph("mark.focused")   # "╭", "›"
    cs.frame("line", 5)                                    # "\\\\"
    cs.glyph("powerline.right")                            # ">": the ascii fallback
    cs.glyph("arrow.right"), cs.glyph("arrow.down")        # "▶", "▼"
    cs.glyph("control.radio"), cs.glyph("control.track")   # "●", "─"
    glyphs(ascii=True).glyph("control.check")              # "*"
    glyphs(ascii=True).glyph("arrow.up")                   # "^"
    glyphs(parse("charset:\\n  base: ascii\\n  mark.focused: \\"»\\"\\n", "t")).glyph("mark.focused")  # "»"
    glyphs(ascii=True).border("light", "h")                # "-"
    raw = parse("charset:\\n  frame.pane.bottom:\\n    start: \\"▙\\"\\n"
                "    fill: \\"─┴─\\"\\n    end: \\"///\\"\\n    end.role: accent\\n"
                "  frame.pane.heavy.top.fill: \\"━\\"\\n", "t")
    w = glyphs(raw)
    w.pattern("frame.pane.bottom")         # Pattern(("▙",), ("─", "┴", "─"), ("/", "/", "/"))
    w.role("frame.pane.bottom", "end"), w.role("frame.pane.bottom", "start")  # "accent", None
    w.pattern("frame.pane.top", "heavy")   # Pattern((), ("━",), ()): the weight first
    w.pattern("frame.pane.top", "rounded"), w.pattern("frame.dialog.top")     # Pattern(), Pattern()
    w.glyph("frame.pane.bottom.start")     # "": a pattern leaf is not a glyph
    glyphs(raw, ascii=True).patterns       # {}: both runs hold non-ASCII cells, dropped
    a = glyphs(parse("charset:\n  frame.pane.bottom:\n    start: \"▙\"\n"
                     "    after: \"▀\"\n    after.share: 0.10\n", "t"))
    a.pattern("frame.pane.bottom")         # Pattern(("▙",), (), (), after=("▀",), share=0.1)
    a.role("frame.pane.bottom", "after")   # None: no after.role given
    # with line 5 (the share leaf; line 4 the after leaf) written otherwise, each a ThemeError:
    #   "    after.share: 2"    -> "t:5: charset.frame.pane.bottom.after.share: share 2 is out of range (0 < share <= 1)"
    #   "    after.share: 1/10" -> "t:5: charset.frame.pane.bottom.after.share: share '1/10' is not a number"
    #   "    fill.share: 0.5"   -> "t:5: charset.frame.pane.bottom.fill.share: not a pattern leaf"
    #   line 5 removed          -> "t:4: charset.frame.pane.bottom.after: an after part with no share (give charset.frame.pane.bottom.after.share)"
    #   line 4 removed (the share then line 4) -> "t:4: charset.frame.pane.bottom.after.share: a share for an after part the theme does not give"
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from .parse import KEY, NAME, Raw, ThemeError, freeze_maps, freeze_seqs, rebuild
from .pattern import Pattern, clusters, is_ascii

BORDERS: tuple[str, ...] = ("light", "heavy", "double", "rounded", "dashed", "dotted", "heavy-dashed",
                             "ascii")
"""Border weights."""

PARTS: tuple[str, ...] = ("tl", "tr", "bl", "br", "h", "v", "tee_l", "tee_r", "tee_t", "tee_b", "cross")
"""Border parts: corners, lines, tees (by the edge they sit on), the cross."""

PLOTS: tuple[str, ...] = ("braille", "sextant", "quadrant", "half", "block", "ascii")
"""Sub-cell plot modes, finest first."""

BASES: tuple[str, ...] = ("unicode", "powerline", "ascii")
"""The built-in charsets a theme starts from."""

PATTERN_PARTS: tuple[str, ...] = ("start", "fill", "end", "after")
"""A run's parts: the last segment of a pattern part leaf (see Patterns)."""

_EMPTY: Pattern = Pattern()
"""`pattern`'s answer for an unknown run: the one empty pattern, shared (a Pattern is immutable)."""

EDGES: tuple[str, ...] = ("top", "bottom", "left", "right")
"""A frame's edges (`frame.<kind>.<edge>`); `left` and `right` are vertical runs."""

AXES: tuple[str, ...] = ("x", "y")
"""A gutter's axis (`frame.gutter.<axis>`): `x` the vertical strip between side-by-side
panes, `y` the horizontal one between stacked panes."""


_ASCII_BOX = ("+", "+", "+", "+", "-", "|", "+", "+", "+", "+", "+")
_ASCII_EQ = ("+", "+", "+", "+", "=", "|", "+", "+", "+", "+", "+")

UNICODE: Mapping = MappingProxyType({
    **{f"border.{weight}.{part}": glyph for weight, row in {
        "light":   ("┌", "┐", "└", "┘", "─", "│", "├", "┤", "┬", "┴", "┼"),
        "heavy":   ("┏", "┓", "┗", "┛", "━", "┃", "┣", "┫", "┳", "┻", "╋"),
        "double":  ("╔", "╗", "╚", "╝", "═", "║", "╠", "╣", "╦", "╩", "╬"),
        "rounded": ("╭", "╮", "╰", "╯", "─", "│", "├", "┤", "┬", "┴", "┼"),
        "dashed":  ("┌", "┐", "└", "┘", "╌", "╎", "├", "┤", "┬", "┴", "┼"),
        "dotted":  ("┌", "┐", "└", "┘", "┄", "┆", "├", "┤", "┬", "┴", "┼"),
        "heavy-dashed": ("┏", "┓", "┗", "┛", "╍", "╏", "┣", "┫", "┳", "┻", "╋"),
        "ascii":   _ASCII_BOX,
    }.items() for part, glyph in zip(PARTS, row)},
    "guide.branch": "├", "guide.last": "└", "guide.vert": "│", "guide.stem": "─",
    "twisty.open": "▾", "twisty.closed": "▸",
    "leader": "-", "ellipsis": "…", "more.down": "↓", "more.up": "↑",
    "mark.focused": "›", "mark.selected": "•", "mark.pressed": "●", "mark.active": "●",
    "mark.emphasised": "✦", "mark.muted": "·",
    "control.check": "•", "control.radio": "●", "control.knob": "●", "control.track": "─",
    "spinner.dots": "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏", "spinner.line": "-\\|/", "spinner.pulse": "⣾⣽⣻⢿⡿⣟⣯⣷",
    "block.full": "█", "block.light": "░", "block.medium": "▒", "block.dark": "▓",
    "block.eighths.h": " ▏▎▍▌▋▊▉█", "block.eighths.v": " ▁▂▃▄▅▆▇█",
    "arrow.right": "▶", "arrow.left": "◀", "arrow.up": "▲", "arrow.down": "▼",
})
"""The `unicode` base: token -> glyph."""

POWERLINE: Mapping = MappingProxyType({
    **UNICODE,
    "powerline.right": "", "powerline.right_thin": "",
    "powerline.left": "", "powerline.left_thin": "",
})
"""The `powerline` base: UNICODE plus the powerline separators."""

ASCII: Mapping = MappingProxyType({
    **{f"border.{weight}.{part}": glyph for weight, row in {
        "light": _ASCII_BOX, "heavy": _ASCII_EQ, "double": _ASCII_EQ,
        "rounded": _ASCII_BOX, "dashed": _ASCII_BOX, "dotted": _ASCII_BOX,
        "heavy-dashed": _ASCII_BOX, "ascii": _ASCII_BOX,
    }.items() for part, glyph in zip(PARTS, row)},
    "guide.branch": "+", "guide.last": "`", "guide.vert": "|", "guide.stem": "-",
    "twisty.open": "v", "twisty.closed": ">",
    "leader": "-", "ellipsis": "...", "more.down": "v", "more.up": "^",
    "mark.focused": ">", "mark.selected": "*", "mark.pressed": "@", "mark.active": "*",
    "mark.emphasised": "+", "mark.muted": ".",
    "control.check": "*", "control.radio": "*", "control.knob": "*", "control.track": "-",
    "spinner.dots": "-\\|/", "spinner.line": "-\\|/", "spinner.pulse": "-\\|/",
    "block.full": "#", "block.light": ":", "block.medium": "%", "block.dark": "#",
    "block.eighths.h": " ,-~=+*%#", "block.eighths.v": " ,-~=+*%#",
    "arrow.right": ">", "arrow.left": "<", "arrow.up": "^", "arrow.down": "v",
    "powerline.right": ">", "powerline.right_thin": ">",
    "powerline.left": "<", "powerline.left_thin": "<",
})
"""The `ascii` base, and the fallback of every charset's `glyph`."""

UNICODE_PLOTS: tuple[str, ...] = ("braille", "sextant", "quadrant", "half", "block")
ASCII_PLOTS: tuple[str, ...] = ("ascii",)

TABLES: Mapping = MappingProxyType({
    "unicode": (UNICODE, UNICODE_PLOTS), "powerline": (POWERLINE, UNICODE_PLOTS),
    "ascii": (ASCII, ASCII_PLOTS)})
"""Base name -> (its glyphs, its plots)."""


@dataclass(frozen=True)
class Charset:
    """{Charset}: token -> glyph, and the plot modes; `name` is the base it was built on.

    `glyphs` a read-only proxy over a copy, `plots` a tuple, made in `__post_init__`.
    R3a adds `patterns` (run -> Pattern) and `part_roles` (`<run>.<part>` -> role), both
    read-only and empty by default (see the module's Patterns); R3 builds them.
    """

    name: str = "unicode"
    glyphs: Mapping = field(default_factory=lambda: dict(UNICODE))
    plots: tuple = UNICODE_PLOTS
    patterns: Mapping = field(default_factory=dict)
    part_roles: Mapping = field(default_factory=dict)

    def __post_init__(self) -> None:
        freeze_maps(self, "glyphs", "patterns", "part_roles")
        freeze_seqs(self, "plots")

    def __reduce__(self):
        return rebuild(self)

    def glyph(self, token: str) -> str:
        """The token's glyph: own, else ASCII's, else ""."""
        if not isinstance(token, str):
            raise TypeError(f"token must be a str, got {type(token).__name__}")
        if token in self.glyphs:
            return self.glyphs[token]
        return ASCII.get(token, "")

    def border(self, weight: str, part: str) -> str:
        """`glyph(f"border.{weight}.{part}")`, an unknown weight taken as light."""
        if not isinstance(weight, str) or not isinstance(part, str):
            raise TypeError("weight and part must be str")
        return self.glyph(f"border.{weight if weight in BORDERS else 'light'}.{part}")

    def frame(self, spinner: str, tick: int) -> str:
        """The spinner's frame at `tick` (one code point), or ""."""
        if not isinstance(spinner, str):
            raise TypeError(f"spinner must be a str, got {type(spinner).__name__}")
        if not isinstance(tick, int) or isinstance(tick, bool):
            raise TypeError(f"tick must be an int, got {type(tick).__name__}")
        frames = self.glyph(f"spinner.{spinner}")
        return frames[tick % len(frames)] if frames else ""

    def chosen(self, run: str, weight: "str | None" = None) -> "str | None":
        """The run `pattern` answers from: `frame.<kind>.<weight>.<edge>` first, else `run`, else None."""
        if not isinstance(run, str):
            raise TypeError(f"run must be a str, got {type(run).__name__}")
        if weight is not None and not isinstance(weight, str):
            raise TypeError(f"weight must be a str or None, got {type(weight).__name__}")
        if weight is not None:
            seg = run.split(".")
            if len(seg) == 3 and seg[0] == "frame" and seg[1] != "gutter" and seg[2] in EDGES:
                weighted = f"frame.{seg[1]}.{weight}.{seg[2]}"
                if weighted in self.patterns:     # taken whole (round 7 Q4)
                    return weighted
        return run if run in self.patterns else None

    def pattern(self, run: str, weight: "str | None" = None) -> Pattern:
        """The run's {Pattern}, the weight-qualified run first; `Pattern()` for an unknown run."""
        c = self.chosen(run, weight)
        return _EMPTY if c is None else self.patterns[c]

    def role(self, run: str, part: str, weight: "str | None" = None) -> "str | None":
        """The role `part` of the chosen run names (`<run>.<part>.role`), or None."""
        if not isinstance(run, str):
            raise TypeError(f"run must be a str, got {type(run).__name__}")
        if not isinstance(part, str):
            raise TypeError(f"part must be a str, got {type(part).__name__}")
        c = self.chosen(run, weight)
        if c is None or part not in PATTERN_PARTS:
            return None
        return self.part_roles.get(f"{c}.{part}")


def glyphs(raw: "Raw | None" = None, *, ascii: bool = False) -> Charset:
    """The {Charset} of a theme's `charset` section over its base (see Building one)."""
    leaves = {} if raw is None else {p[1:]: (v, raw.lines[p]) for p, v in raw.leaves.items()
                                     if p[0] == "charset"}
    base = _base(leaves)
    table, plots = TABLES[base]
    if ("plots",) in leaves:
        plots = _plots(*leaves[("plots",)])
    overrides, parts, wheres, later = {}, {}, {}, []
    for path, (value, where) in leaves.items():
        if path in ((), ("base",), ("plots",)):
            continue
        token = ".".join(path)
        pat = _is_pattern_leaf(path)
        if pat and path[-1] in ("role", "share"):  # rules 1 and 3, once every part leaf has passed
            later.append((path, value, where))
            continue
        if pat and _run_of(path) is None:         # rule 2
            raise ThemeError(*where, f"charset.{token}: not a pattern leaf")
        if not value:
            raise ThemeError(*where, f"charset.{token}: empty glyph")
        if pat:
            parts[path] = clusters(value, vertical=_vertical(path[:-1]), name=f"charset.{token}",
                                   where=where)
            wheres[path] = where
        else:
            overrides[token] = value
    part_roles, shares = {}, {}
    for path, value, where in later:              # role and share leaves, in leaf order
        token = ".".join(path)
        if path[-1] == "share":
            run = _share(path, value, where, parts)   # checked before its float is taken
            shares[run] = float(value)
            continue
        if _run_of(path[:-1]) is None:
            raise ThemeError(*where, f"charset.{token}: not a pattern leaf")
        if not value:
            raise ThemeError(*where, f"charset.{token}: empty role")
        if not _ROLE.fullmatch(value):
            raise ThemeError(*where, f"charset.{token}: bad role name '{value}'")
        if path[:-1] not in parts:
            raise ThemeError(*where, f"charset.{token}: a role for a part the theme does not give")
        part_roles[".".join(path[:-1])] = value
    for path in parts:                            # then every after with no share, in leaf order
        if path[-1] == "after" and _run_of(path) not in shares:
            token = ".".join(path)
            raise ThemeError(*wheres[path], f"charset.{token}: an after part with no share "
                                            f"(give charset.{token}.share)")
    patterns = _patterns(parts, shares)
    if ascii:
        base, table, plots = "ascii", ASCII, ASCII_PLOTS
        overrides = {t: g for t, g in overrides.items() if g.isascii()}
    if base == "ascii":                           # the ascii drop: whole runs, at build
        patterns = {r: p for r, p in patterns.items() if is_ascii(p)}
    part_roles = {k: v for k, v in part_roles.items() if k.rsplit(".", 1)[0] in patterns}
    return Charset(base, {**table, **overrides}, plots, patterns, part_roles)


def role_leaves(raw: "Raw | None") -> tuple:
    """Every pattern role leaf of `raw`'s charset section: `(f"charset.{token}", role, where)`."""
    if raw is None:
        return ()
    return tuple((f"charset.{'.'.join(p[1:])}", v, raw.lines[p]) for p, v in raw.leaves.items()
                 if p[0] == "charset" and _is_pattern_leaf(p[1:]) and p[-1] == "role")


_ROLE = re.compile(rf"(?:{NAME}:)?{KEY}")
"""A part role's value: one key, optionally prefixed `<kind>:` (Theme's derived styles)."""


def _is_pattern_leaf(path: tuple) -> bool:
    """A leaf under `charset.frame` or `charset.run` (a pattern leaf, never a glyph)."""
    return bool(path) and path[0] in ("frame", "run")


def _run_of(path: tuple) -> "str | None":
    """The run a part leaf's path names, by the table's four shapes; None for another path."""
    if len(path) < 2 or path[-1] not in PATTERN_PARTS:
        return None
    seg = path[:-1]
    if seg[0] == "run" and len(seg) == 3:
        return ".".join(seg)
    if seg[0] != "frame":
        return None
    if len(seg) == 3 and (seg[2] in AXES if seg[1] == "gutter" else seg[2] in EDGES):
        return ".".join(seg)
    if len(seg) == 4 and seg[1] != "gutter" and seg[2] in BORDERS and seg[3] in EDGES:
        return ".".join(seg)
    return None


def _vertical(run: tuple) -> bool:
    """The table's vertical column, by a run's segments."""
    if run[0] == "run":
        return True
    if run[1] == "gutter":
        return run[2] == "x"
    return run[-1] in ("left", "right")


def _share(path: tuple, value: str, where: tuple, parts: dict) -> str:
    """Rule 3's checks of a share leaf, in order (shape, number, range, its after given); its run."""
    token = ".".join(path)
    run = _run_of(path[:-1])
    if run is None or path[-2] != "after":
        raise ThemeError(*where, f"charset.{token}: not a pattern leaf")
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]*)?|\.[0-9]+", value):
        raise ThemeError(*where, f"charset.{token}: share '{value}' is not a number")
    if not 0 < float(value) <= 1:
        raise ThemeError(*where, f"charset.{token}: share {value} is out of range (0 < share <= 1)")
    if path[:-1] not in parts:
        raise ThemeError(*where, f"charset.{token}: a share for an after part the theme does not give")
    return run


def _patterns(parts: dict, shares: dict) -> dict:
    """Run -> Pattern of the part leaves' clusters and its share, runs in the order of their
    first part leaf."""
    runs: dict = {}
    for path, cs in parts.items():
        runs.setdefault(_run_of(path), {})[path[-1]] = cs
    return {run: Pattern(given.get("start", ()), given.get("fill", ()), given.get("end", ()),
                         vertical=_vertical(run.split(".")), after=given.get("after", ()),
                         share=shares.get(run))
            for run, given in runs.items()}


def _base(leaves: dict) -> str:
    given = [leaves[p] for p in ((), ("base",)) if p in leaves]
    if not given:
        return "unicode"
    value, where = given[-1]
    if len(given) > 1 or value not in BASES:
        raise ThemeError(*where, f"charset.base must be one of {', '.join(BASES)}")
    return value


def _plots(value: str, where: tuple) -> tuple:
    plots = tuple(value.split())
    for p in plots:
        if p not in PLOTS:
            raise ThemeError(*where, f"charset.plots: '{p}' is not one of {', '.join(PLOTS)}")
    if len(set(plots)) != len(plots):
        raise ThemeError(*where, "charset.plots names a mode twice")
    return plots
