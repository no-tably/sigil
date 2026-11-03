"""[TextInput]: one line or an area; its edit state is the app's.

Kind: service (a frozen dataclass node kind, `TextInput`; see the Widgets package's
protocol and the Controls package's shared rules: the mark cell, the key, the
states, the hits).

What it does: draws an edit value the app keeps (Input's {Edit}: the app holds one
per input, the router hands the focused one its keys, every op returns a new value)
into its rect: the key prefix, then the text's rows, scrolled so the cursor shows,
the selection highlighted, the cursor's cell marked, the rows optionally coloured by
the app's syntax runs (`runs`: sigil's highlight, laid over the text and never
changing it); and it says where the terminal cursor goes (`cursor_at`) and which
text position a click lands on (`locate`).
TextInput edits nothing and keeps no scroll of its own: with `scroll=None` the view
is a pure function of the edit and the rect (below); an app that wants a sticky
scroll passes `scroll` itself.

The edit, by its attributes (Widgets may not import Input, `.construct/mapping.md`:
any value with these attributes serves, Input's `Edit` among them):
- `rows`: a non-empty tuple of `str`, the lines drawn (an area's text cut at its
  breaks, the breaks dropped; a one-line edit's `(text,)`);
- `line`: an `int` in `range(len(rows))`, the cursor's row;
- `column`: an `int >= 0`, the cursor's column in cells within its row (a cluster
  boundary of `rows[line]`: `width` of the clusters before it);
- `selection`: `None`, or a pair `(a, b)` of ints, `0 <= a <= b`: the selected
  cluster boundaries over the whole text, every break counting as one cluster
  between two rows (as Edit counts them).
They are read once, at construction, and checked there (so `paint` never fails on
them). With Text's `cluster`, row `r`'s clusters are `cl_r = cluster(rows[r])` and
its first cluster's index is `B_r = sum(len(cl_j) + 1 for j < r)`; cluster `k` of
row `r` is selected when `a <= B_r + k < b`, and row `r`'s break (index `B_r +
len(cl_r)`, for `r < len(rows) - 1`) when `a <= B_r + len(cl_r) < b`.

Data (frozen dataclass; checked on construction):
- `TextInput(edit, *, label="", placeholder="", mask=None, scroll=None,
  disabled=False, focused=None, runs=None, id=None, size=None, anchor=None,
  scope=None, surface=False)`:
  - `edit`: the edit value above.
  - `label`: styled text, the key (the Controls package's key); `""` for none.
  - `placeholder`: styled text drawn in role `muted` when `rows == ("",)`.
  - `mask`: `None`, or a `str` of one cluster one cell wide: every cluster of the
    text is drawn as it (a password field); columns are then counted in clusters.
  - `scroll`: `None` (the view follows the cursor, below) or a pair `(sx, sy)` of
    ints `>= 0`: the first column and the first row shown, as the app keeps them.
  - `disabled`: a `bool`: the text is drawn dim.
  - `focused`: `None` (ask `ctx.is_focused(id)`), `True` or `False`.
  - `runs`: `None` (no styling: every row plain, as before S1), or the app's
    per-row syntax styling (sigil's highlight of the text; see The syntax styling
    below): a `tuple` with one entry per row index (entry `r` is for `rows[r]`); it
    may be shorter than `rows` (a missing entry is `None`) and may be longer (an
    entry past the last row belongs to no row and is ignored, though still checked:
    an app's runs may lag its edit by a frame). Each entry is `None` (the row draws
    plain) or a pair `(text, spans)`:
    - `text`: a `str`, the row's text the spans were made for;
    - `spans`: a `tuple` of triples `(chunk, role, colour)`, in order, whose chunks
      join to `text` exactly (`"".join(c for c, _, _ in spans) == text`; `text ==
      ""` takes `spans == ()`):
      - `chunk`: a non-empty `str`;
      - `role`: `None` (plain text) or a non-empty `str`, sigil's dotted role
        verbatim (`"syntax.keyword"`, `"kinds.service"`, `"ui.note"`, ...);
      - `colour`: `None` or a `str` `"#rrggbb"` (`#` and exactly six hex digits,
        either case: sigil's colour for the role).
    Equal and hashable as the tuple it is (a dataclass field like the others).

The view, on `rect` `R`, with `P`, `F` the key's prefix and field widths, `n =
len(rows)`, `H = R.h`, `E = width(ctx.glyph("ellipsis"))`, and the display width of
a row `tw_r` (`width(rows[r])`, or its cluster count when masked) and the cursor's
display column `c` (`column`, or when masked the `k` with `width("".join(cl[:k]))
== column` in `rows[line]`):
- Rows: List's window over the rows: `top = 0` when `n <= H`, else `n - max(H - 1,
  0)`; `cap = H` when `n <= H`, else `max(H - 1, 0)`; the first row `t`: with
  `scroll`, `min(sy, top)`; else `0` when `line < cap`, else `min(line - cap + 1,
  top)` (`0` when `cap == 0`); `shown = min(cap, n - t)`; when `n > H >= 1` the last
  cell row is the indicator, `More`'s text with `above = t` and `below = n - t -
  shown` (`↑2 more`, ...) in role `muted` from `R.x`, cut to the row.
- Columns: the first column `s`: with `scroll`, `sx`; else `0` when `tw + 1 <= F`
  (`tw` the cursor row's: the text and the cell after it fit); else the smallest `s
  >= 0` with `s + lm(s) <= c < s + F - rm(s)`, where `lm(s) = E` when `s > 0` else
  `0` and `rm(s) = E` when `tw > s + F` else `0` (the cursor stays clear of both
  overflow marks); when no `s <= c` satisfies it (a field narrower than `2 * E +
  1`), `s = max(0, c - F + 1)`. Every row is drawn at the same `s`, so columns line
  up.
- A row `r` on cell row `R.y + (r - t)`: the prefix cells (row `t`'s cell row draws
  the key and the mark cell; every other row `P` ground cells), then in the field:
  with `lead = E` when `s > 0` and `tw_r > 0` (cells hidden on the left), else `0`:
  `ctx.glyph("ellipsis")` in role `muted` when `lead`, then `cut(<the row>, F -
  lead, start=s + lead, ellipsis=ctx.glyph("ellipsis"))` (so a row running past the
  field ends in the ellipsis), in role `text` (masked: the mask in role `text`), the
  rest ground. A field too narrow for `lead` (`F < E`) draws the row cut plainly.
  `<the row>` is the row's styled line (The syntax styling, below): the row as one
  span in role `text` when it draws plain, else one span per chunk; the cut, the
  lead and the ellipsis are the same either way (the right ellipsis takes, by
  Text's `cut`, the style of the first cluster cut off, so a styled row's may carry
  that cluster's syntax style; the left one is `muted` as always).
- The placeholder, when `rows == ("",)` and it is not empty: on row `t`'s cell row
  from the field's start, cut with the ellipsis to `F`, in role `muted`.

The syntax styling (`runs`): the app's colours laid over the text, never changing it.
Row `r`'s styled line, with `run = runs[r]` when `runs` is not `None` and `r <
len(runs)`, else `None`:
- Plain (as before S1: `Line((Span(rows[r], ctx.style("text")),))`, empty for `""`)
  when `run is None`, when the input is masked (`mask` is not `None`: the mask is
  drawn in role `text` whatever the runs say), or when the run is stale: `run[0] !=
  rows[r]` (condition a: the spans are used only while the text they were made for
  equals the row now; no guessing, no clipping, no partial use of a stale run).
- Else one `Span(chunk, S)` per span `(chunk, role, colour)`, in order, with `S =
  syntax_style(ctx, role, colour)` (The run-to-style lookup, below: the one function
  `paint` calls for each span, not a copy of it), which is, by these rules
  (conditions b and round 5's Q2: a declared theme role wins, else the hex, else
  plain), `T = "sigil." + role` (sigil's role verbatim under the one prefix
  `sigil.`, which no cure role uses):
  1. `role is None`: `ctx.style("text")` (plain; a colour given with no role is
     not used);
  2. `ctx.declared(T)` is not `None` (the context's theme DECLARES the style role
     `T` exactly, not by falling back up the dots; Draw's {Context} op, which reads
     `theme.roles.styles` and never imports Theme here): that style, as the theme
     resolved it (its colours already tagged `T` by Theme's [Roles]);
  3. else, `colour` not `None`: `dataclasses.replace(ctx.style("text"), fg=Colour(
     "ink", Ink(T, rgb, tty256=nearest256(rgb)), T))` with `rgb =
     parse_hex(colour)` (Core Style's `Colour`, `Ink`, `parse_hex`, `nearest256`):
     the text style with its foreground the run's 24-bit colour, as an ink whose
     name and colour role are `T` (so a host restyles it by role). Its fallbacks,
     by the rules Core and Theme already have: `tty256` DECLARED as Core Ink's
     `nearest256(rgb)` (the cube and greys 16..255, which do not vary by terminal:
     the rule Theme's [Derive] uses for a derived tty256), so it shows at depth 256;
     `tty16` NOT declared (README decisions 1 and 4: nearest-of-sixteen is opt-in
     only, since xterm's sixteen vary by terminal and turn colours grey, e.g.
     `nearest16((255, 123, 114))` is `bright_black`), so at depth 16 it realizes by
     Core Ink's rule: `None` (the terminal's default) unless the caller passes
     `nearest=True`;
  4. else (`colour is None`, `T` not declared): `ctx.style("text")` (plain).
  `ctx.declared` is asked only in step 2 (`syntax_style` asks it only once `role`
  is not `None`), so with `runs=None` (or every row plain) a context without it
  serves, as before S1.
  A cluster whose code points fall in two or more chunks (a combining mark or a
  ZWJ sequence split by the spans) takes, for all its cells, the style of the span
  holding its first code point.
- Runs change only the styles of a row's text cells: never a glyph, a width, a
  position, the lead, the window, the first column, a hit, `cursor_at`, `locate`,
  `measure` or `zone` (each reads `rows`, never `runs`).

The cursor cell: the cell at `x = R.x + P + c - s`, on the cursor row's cell row,
when the input is focused (`focused` if not `None`, else `ctx.is_focused(id)`), the
cursor row is shown and `P <= x - R.x < R.w`: the cluster after the cursor (both
cells of a wide one), or the blank after the row's end. It takes `ctx.apply(<its
style>, "focused", "cell")` (Theme's cell extent: a block cursor). The focused input
draws no row highlight: it would hide the cursor cell. `cursor_at` gives the same
cell to the app for the terminal's own cursor.

The states, in order: the selection (each selected cluster's cells, and a selected
break as the one cell after its row's text, `ctx.apply(.., "selected")`), disabled
(`"text"`: the text cells), hover (`ctx.is_hovered(id)`, over every field cell of
the shown rows), the cursor cell (focused). The mark cell: focused's `›`, else
hover's, else a blank (or the leader). The states are laid over the cells the rows
drew, whatever their styles (condition c): over a syntax-styled cell exactly as over
a plain one, the same `ctx.apply` of the same state and extent to the cell's own
style (so the selection, the cursor cell, disabled and hover draw over the syntax
colours, and with `runs=None` every state draws as before S1).

Legible, with colour off: focused, through the mark cell's `›` (and the terminal
cursor at `cursor_at`); hover, underline; disabled, dim; the selection, reverse
(Theme [States] gives `selected` the floor `reverse` whatever the theme's role says).

Painting (`paint(rect, ctx, grid, clip=None)`), `g = ctx.ground()`: the clip's
ground, the rows, the indicator, the states, `shade(grid, clip, bg=g.style.bg)`.
Hits: `(Hit(clip, id),)` when `id` is not `None`, else `()`.

The app's helpers (pure, the same arithmetic as `paint`):
- `cursor_at(rect, ctx, clip=None) -> tuple[int, int] | None`: the screen cell
  `(x, y)` of the cursor cell, when it is drawn (focused, shown, inside `rect` and
  `clip`), else `None`.
- `locate(rect, ctx, x, y) -> tuple[int, int] | None`: for a screen cell in the
  field of a shown row (`R.x + P <= x < R.right`, `R.y <= y < R.y + shown`), the
  text position under it, `(line, column)`: `line = t + (y - R.y)`, the display
  column `d = s + (x - R.x - P)`, and `column` the cells of the clusters of
  `rows[line]` before the largest boundary at or left of `d` (a column inside a
  wide cluster lands before it; past the row's end, its width; masked, `d` counts
  clusters); `None` elsewhere (the prefix, the indicator, outside `rect`). The app
  turns it into a cursor (Input's Edit counts in clusters).

The run-to-style lookup (S2b, public, so an app's test asks which style, and so which
ink, a highlight role gets under a theme without private names; the Controls package
re-exports it):
- `syntax_style(ctx, role, colour) -> Style`: a module-level function (not a method),
  the style a span `(chunk, role, colour)` of a fresh run gives its cells before the
  states and the final `shade`: exactly rules 1..4 of The syntax styling above (`role
  is None`: `ctx.style("text")`; `ctx.declared("sigil." + role)` when not `None`;
  else, `colour` not `None`, the text style with fg the `"ink"` Colour of
  `parse_hex(colour)`, ink name and colour role `"sigil." + role`, `tty256 =
  nearest256(rgb)`, `tty16` not declared; else `ctx.style("text")`).
  - `ctx`: a Draw Context, or any value with `style(role)` and `declared(role)`
    (read by attribute, as `paint` reads it; Controls never imports Draw's
    `context.py`); `ctx.declared` is asked only when rule 2 is reached (`role` not
    `None`), so a value without `declared` serves for `role=None`.
  - `role`: `None` or a non-empty `str`, sigil's dotted role verbatim, WITHOUT the
    `sigil.` prefix (`"syntax.keyword"`; the lookup adds the prefix).
  - `colour`: `None` or a `str` `"#rrggbb"` (`#` and exactly six hex digits, either
    case), as a span's colour.
  It IS the lookup `paint` uses (each fresh span's style is `syntax_style(ctx, role,
  colour)`, called, not copied); `_syntax` is gone, renamed to it, with no private
  alias left behind.
  Errors: checked before `ctx` is touched, in the order role then colour, with the
  span checks' wording less their `runs[i] span j ` prefix (`T` a type's `__name__`):
  `TypeError(f"role must be None or a str, got {T}")`, `ValueError("role must not be
  empty")`, `TypeError(f"colour must be None or a str, got {T}")`, `ValueError(f"colour
  must be '#rrggbb', got {colour!r}")`; past those, a `ctx` lacking what a rule asks
  raises whatever that attribute access raises. Effects: none; pure: equal arguments
  give equal styles, nothing read but the arguments.
  Exact styles: under `ctx = Context.of(builtin())` (which declares no `sigil.*`),
  `syntax_style(ctx, "syntax.keyword", "#ff7b72")` is
  `dataclasses.replace(ctx.style("text"), fg=Colour("ink", Ink("sigil.syntax.keyword",
  (255, 123, 114), tty256=209), "sigil.syntax.keyword"))`; `syntax_style(ctx,
  "syntax.keyword", None)` and `syntax_style(ctx, None, "#ff7b72")` are
  `ctx.style("text")`. Under `ctx = Context.of(pick("light"))` (Theme's `pick`; the
  light shelf theme declares `sigil.syntax.keyword`), `syntax_style(ctx,
  "syntax.keyword", "#ff7b72") == ctx.declared("sigil.syntax.keyword")`, the theme's
  own style (fg its `accent` ink tagged role `sigil.syntax.keyword`), whatever the hex.

Measuring: `"x"`: `P + max(max(tw_r), width(placeholder)) + 1` (the cell after the
text for the cursor); `"y"`: `n`.

Exact cells (the builtin theme, `ctx = Context.of(builtin())`, `E = 1`; text in
`ctx.style("text")`), edits written as `Ed(rows, line, column, selection)` for any
value with those four attributes (`types.SimpleNamespace` serves):
- `TextInput(Ed(("hello",), 0, 5, None), id="t")` at `Rect(0, 0, 10, 1)`:
  `" hello    "`; hits `(Hit(Rect(0, 0, 10, 1), "t"),)`; `cursor_at` is `None`. With
  `ctx.focus == "t"`: `"›hello    "`, the cell at (6, 0) a blank in
  `ctx.apply(ctx.ground().style, "focused", "cell")`; `cursor_at(...) == (6, 0)`.
- `Ed(("hello world",), 0, 11, None)` at `Rect(0, 0, 9, 1)`, focused (`F = 8`,
  `s = 4`): `"›… world "`, the cursor at (8, 0); `column=0` (`s = 0`):
  `"›hello w…"`, the cursor on `h` at (1, 0). `locate(rect, ctx, 3, 0)` is `(0, 2)`
  there.
- `Ed(("hello",), 0, 3, (1, 3))`: `e` and `l` (x 2, 3) in `ctx.apply(..,
  "selected")`.
- `Ed(("ab", "cd"), 1, 1, (1, 4))` at `Rect(0, 0, 6, 2)`: `b` (2, 0), the break's
  cell (3, 0) and `c` (1, 1) selected.
- `label="Name"` with `Ed(("hello",), 0, 5, None)` at width 13 (`P = 7`, `F = 6`):
  `"-Name: hello "`; focused, `"›Name: hello "` with the cursor at (12, 0).
- `Ed(("",), 0, 0, None)` with `placeholder="search"` at width 10:
  `" search   "`, `search` muted.
- `Ed(("one", "two", "three"), 2, 5, None)` at `Rect(0, 0, 8, 2)`, focused (`t =
  2`): `"›three  "`, `"↑2 more "`; at `Rect(0, 0, 8, 3)`: `"›one    "`,
  `" two    "`, `" three  "`, the cursor at (6, 2).
- `mask="•"` with `Ed(("abc",), 0, 3, None)`: `" •••"` and the cursor at (4, 0).
- `measure("x", 0, ctx) == 7` and `measure("y", 0, ctx) == 1` for the first input;
  `7` and `3` for the area (`1 + 5 + 1`).
- Runs, with `e = Ed(("a b", "cd"), 0, 0, None)`, `kw = ("a", "syntax.keyword",
  "#ff7b72")`, `sp = (" ", None, None)`, `sv = ("b", "kinds.service", "#79c0ff")`
  and `runs=(("a b", (kw, sp, sv)),)` at `Rect(0, 0, 6, 2)`: the characters are
  `" a b  "`, `" cd   "` (as with `runs=None`); `a` (1, 0) is the plain cell with its
  fg `Colour("ink", Ink("sigil.syntax.keyword", (255, 123, 114), tty256=209),
  "sigil.syntax.keyword")`, `b` (3, 0) with fg `Colour("ink", Ink(
  "sigil.kinds.service", (121, 192, 255), tty256=111), "sigil.kinds.service")`, the
  blank (2, 0) plain; row 1 (no entry) plain. With `runs=(("a c", (...)),)` (stale)
  every cell is the `runs=None` cell. Under `load("t", {"t": "extends: builtin\\n"
  "sigil.syntax.keyword: $accent bold\\n"})`, `a` takes that theme's
  `style("sigil.syntax.keyword")` (shaded as every cell is) and `b` keeps its hex.
  With `selection=(0, 1)`, `a` is `ctx.apply(<its syntax style>, "selected")`;
  focused at column 0, `a` is `ctx.apply(<its syntax style>, "focused", "cell")`.

The zone (`zone(ctx) -> int`, PropertyList's signature and rule, so Paint gathers it
from a parent's children as it gathers a PropertyList's): the key zone the input
aligns at, `Z` of the Controls package's key: with a non-empty `label`,
`measure((label,))` (Text's: `1 + width(label)`, one leader cell before the key, as a
PropertyList's `1 + widest key`), or `max(ctx.zone, that)` when `ctx.zone` is not
`None`; with an empty `label` it adds nothing: `measure(())` (`1`, Text's for no
keys, as a PropertyList with no items gives), or `ctx.zone` when that is not `None`.
It is never below `ctx.zone` and never below `1`; it reads only `label` and
`ctx.zone` (not the edit, the mask or the rect). `paint` keys the input at
`zone(ctx)`, so under Paint's pushed zone `Z'` (the siblings' max) it aligns at
exactly `Z'`.

Law (aligned): for a column of nodes, each a labelled TextInput, a labelled Select
face or a PropertyList, painted at one `R.x` with `ctx.zone = max(n.zone(ctx0) for
n in the column)` (what Paint pushes to siblings), every key row puts its
separator's `:` at column `R.x + Z` and its value or field from `R.x + Z + 2`
(whenever the row is wide enough that a PropertyList's leaders do not shrink and a
control's prefix is not cut). With `ctx.zone == 11` (a PropertyList with key
`identifier`) at width 22: `"-------Name: hello    "` (`label="Name"` with
`Ed(("hello",), 0, 5, None)`, `L = 7`, `P = 13`), `"-------Size: Medium  ▸"` (a
Select face), `"-identifier: 42       "`; the `:` at column 11 in all three.

Laws of the syntax styling (S1; a test loops over edits, runs, rects, clips, states
and every shelf theme, `cure.draw.theme.NAMES` through `shelved`):
- pure: equal arguments (node, rect, ctx, clip) give equal cells and hits; nothing is
  read but the arguments.
- unchanged (condition d): with `runs=None`, and with runs whose every entry is
  `None` or stale, `paint`'s cells and hits, `cursor_at`, `locate`, `measure` and
  `zone` equal those of the TextInput of the commit before S1 (3ff3b8b, loaded by git
  through `tests/_gitref.py` at test time, never a copy), for the same edit, fields,
  rect, clip and context.
- stale-plain: a row whose entry is `None`, missing, or has `text != rows[r]` draws
  exactly as with `runs=None`, whatever its spans say and whatever the other rows'
  runs are; a masked input draws as with `runs=None` whatever the runs.
- text-unchanged: for any runs, every cell's glyph and width, and the hits,
  `cursor_at`, `locate`, `measure` and `zone`, equal those with `runs=None`: runs
  change styles only, never text.
- colour-by-role: a text cell of a fresh run's span `(chunk, role, colour)`, before
  the states, has the style of rule 1..4 above: `role is None`: plain; `sigil.<role>`
  declared by the theme (`ctx.declared` not `None`): that style, whatever `colour`;
  else a colour: the plain style with fg the `"ink"` Colour of that rgb, ink name and
  role `sigil.<role>`, `tty256 = nearest256(rgb)`, `tty16 = None`; else plain (that
  is, `syntax_style(ctx, role, colour)`). A role the theme reaches only by falling
  back up the dots (`sigil.syntax` declared, `sigil.syntax.keyword` not) is not
  declared: the hex.
- syntax-style-is-paint (S2b): for every fresh run's span `(chunk, role, colour)` of
  every row drawn, with no state on the cell, the cell's style before the final
  `shade` equals `syntax_style(ctx, role, colour)` (so the colour-by-role law is
  `syntax_style`'s rules 1..4, and an app's test that derives an expected ink through
  `syntax_style` derives the ink `paint` draws).
- syntax-style-pure (S2b): `syntax_style` with equal arguments gives equal styles,
  reads nothing but its arguments and writes nothing.
- over (condition c): with a selection, focus (the cursor cell), disabled or hover,
  each cell equals the state's `ctx.apply` (same state, same extent, same order)
  of the style the same runs give that cell with no state, before the final
  `shade` (the point at which every state applies to a plain cell); so the selection's, the cursor's,
  disabled's and hover's floors (reverse, the cursor cell, dim, underline) show over
  syntax colours as over plain text.
- frames: `paint` never raises, for every rect `1 <= w <= 120`, `1 <= h <= 40` (any
  `x`, `y`, and a clip inside it, or one across it cut to it: the Widgets
  protocol refuses a clip outside the rect), with `runs=None` and with any valid runs
  (fresh, stale, shorter or longer than the rows), every edit TextInput accepts,
  masked or not, focused or not, every shelf theme at every depth.

Errors: construction: `TypeError` when `edit` lacks `rows`, `line`, `column` or
  `selection` (naming it), `rows` is not a tuple of `str`, `line` / `column` is not
  an int, `selection` is not `None` or a pair of ints (a `bool` refused each time),
  `label` / `placeholder` is neither a `str` nor a `Line`, `mask` is not `None` or a
  `str`, `scroll` is not `None` or a pair of ints, `disabled` / `surface` is not a
  `bool`, `focused` is not `None` or a `bool`, or `id` is unhashable; `ValueError`
  when `rows` is empty, `line` is outside `range(len(rows))`, `column` or a scroll
  value is negative, `selection` has `a > b` or a negative end, or `mask` is not one
  cluster one cell wide. `runs` is checked after the fields above, entry by entry in
  index order (`i` the entry's index, `j` the span's), every entry, past the rows
  included; the first failure raises, with exactly these messages (`T` a type's
  `__name__`, `!r` a repr):
  - `TypeError(f"runs must be None or a tuple, got {T}")`;
  - `TypeError(f"runs[{i}] must be None or a pair (text, spans), got {T}")` (not a
    `tuple` of length 2: a list, a triple, a str);
  - `TypeError(f"runs[{i}] text must be a str, got {T}")`;
  - `TypeError(f"runs[{i}] spans must be a tuple, got {T}")`;
  - `TypeError(f"runs[{i}] span {j} must be a (chunk, role, colour) triple, got
    {T}")` (not a `tuple` of length 3);
  - `TypeError(f"runs[{i}] span {j} chunk must be a str, got {T}")`;
  - `ValueError(f"runs[{i}] span {j} chunk must not be empty")`;
  - `TypeError(f"runs[{i}] span {j} role must be None or a str, got {T}")`;
  - `ValueError(f"runs[{i}] span {j} role must not be empty")`;
  - `TypeError(f"runs[{i}] span {j} colour must be None or a str, got {T}")`;
  - `ValueError(f"runs[{i}] span {j} colour must be '#rrggbb', got {colour!r}")`
    (anything but `#` and six hex digits: `"#abc"`, `"red"`, `""`);
  - `ValueError(f"runs[{i}] spans join to {joined!r}, not its text {text!r}")`
    (checked after the entry's spans, each span's fields in the order chunk, role,
    colour).
  The runs are never checked against the rows (a stale run is not an error: it
  draws plain). `syntax_style`: its own four messages (The run-to-style lookup,
  above). `measure` / `paint`: as the protocol states; `cursor_at` /
  `locate`: `TypeError` when `rect` / `clip` is not a Rect or `x` / `y` not an int.
Through the family (Q9c): the key row (`_key`, `_prefix`) and the indicator
(`_indicator`) are the Controls toolkit's (`button.py`'s toolkit section: the
package's stated key and List's indicator), never Button's own.
Effects: none, apart from `paint`'s writes into the grid it is given.

Usage:
    from types import SimpleNamespace as Ed
    from cure.core.buffer import Grid, text
    from cure.core.geometry import Rect
    from cure.draw.context import Context
    from cure.draw.theme import builtin
    from cure.draw.widgets.controls import TextInput
    ctx = Context.of(builtin(), focus="t")
    field = TextInput(Ed(rows=("hello world",), line=0, column=11, selection=None), id="t")
    g = Grid(9, 1)
    field.paint(Rect(0, 0, 9, 1), ctx, g)
    text(g)                                  # "›… world"
    field.cursor_at(Rect(0, 0, 9, 1), ctx)   # (8, 0)
    field.zone(ctx)                          # 1: no label adds nothing
    TextInput(field.edit, label="Name").zone(ctx)                          # 5: 1 + width("Name")
    TextInput(field.edit, label="Name").zone(Context.of(builtin(), zone=11))  # 11
    from cure.draw.theme import pick
    from cure.draw.widgets.controls import syntax_style
    syntax_style(ctx, "syntax.keyword", "#ff7b72").fg
    # Colour("ink", Ink("sigil.syntax.keyword", (255, 123, 114), tty256=209), "sigil.syntax.keyword")
    light = Context.of(pick("light"))
    syntax_style(light, "syntax.keyword", "#ff7b72") == light.declared("sigil.syntax.keyword")  # True
"""

import re
from collections.abc import Hashable
from dataclasses import KW_ONLY, dataclass, replace

from cure.core.buffer import Grid
from cure.core.geometry import Hit, Rect
from cure.core.style import Colour, Ink, nearest256, parse_hex
from cure.core.text import Line, Span, cluster, cut, measure, width

from .button import (_begin, _check_common, _check_flag, _check_measure, _check_text, _focus,
                     _fitted, _ground, _indicator, _is_int, _key, _mark, _plain, _plain_of, _prefix,
                     _put, _restyle, _shade, _styled, _Styler, _width)


def _pair(name: str, value: object) -> None:
    """A pair of ints (a bool refused each time)."""
    if (not isinstance(value, (tuple, list)) or len(value) != 2
            or not all(_is_int(v) for v in value)):
        raise TypeError(f"{name} must be None or a pair of ints, got {value!r}")


_HEX = re.compile(r"#[0-9a-fA-F]{6}")


def _check_runs(runs: object) -> None:
    """The runs' shape, entry by entry in index order (see Errors)."""
    if runs is None:
        return
    if not isinstance(runs, tuple):
        raise TypeError(f"runs must be None or a tuple, got {type(runs).__name__}")
    for i, entry in enumerate(runs):
        if entry is None:
            continue
        if not isinstance(entry, tuple) or len(entry) != 2:
            raise TypeError(f"runs[{i}] must be None or a pair (text, spans), got {type(entry).__name__}")
        text, spans = entry
        if not isinstance(text, str):
            raise TypeError(f"runs[{i}] text must be a str, got {type(text).__name__}")
        if not isinstance(spans, tuple):
            raise TypeError(f"runs[{i}] spans must be a tuple, got {type(spans).__name__}")
        for j, span in enumerate(spans):
            _check_span(f"runs[{i}] span {j}", span)
        joined = "".join(chunk for chunk, _, _ in spans)
        if joined != text:
            raise ValueError(f"runs[{i}] spans join to {joined!r}, not its text {text!r}")


def _check_span(name: str, span: object) -> None:
    """One `(chunk, role, colour)` triple, its fields in that order."""
    if not isinstance(span, tuple) or len(span) != 3:
        raise TypeError(f"{name} must be a (chunk, role, colour) triple, got {type(span).__name__}")
    chunk, role, colour = span
    if not isinstance(chunk, str):
        raise TypeError(f"{name} chunk must be a str, got {type(chunk).__name__}")
    if chunk == "":
        raise ValueError(f"{name} chunk must not be empty")
    if role is not None and not isinstance(role, str):
        raise TypeError(f"{name} role must be None or a str, got {type(role).__name__}")
    if role == "":
        raise ValueError(f"{name} role must not be empty")
    if colour is not None and not isinstance(colour, str):
        raise TypeError(f"{name} colour must be None or a str, got {type(colour).__name__}")
    if colour is not None and not _HEX.fullmatch(colour):
        raise ValueError(f"{name} colour must be '#rrggbb', got {colour!r}")


def syntax_style(ctx: object, role: "str | None", colour: "str | None") -> object:
    """A span's style by rules 1..4: plain with no role; the declared `sigil.<role>`;
    else the text style with the hex as a `sigil.<role>` ink; else plain. The
    arguments are checked before `ctx` is touched (see The run-to-style lookup)."""
    if role is not None and not isinstance(role, str):
        raise TypeError(f"role must be None or a str, got {type(role).__name__}")
    if role == "":
        raise ValueError("role must not be empty")
    if colour is not None and not isinstance(colour, str):
        raise TypeError(f"colour must be None or a str, got {type(colour).__name__}")
    if colour is not None and not _HEX.fullmatch(colour):
        raise ValueError(f"colour must be '#rrggbb', got {colour!r}")
    text = ctx.style("text")
    if role is None:
        return text
    T = "sigil." + role
    declared = ctx.declared(T)
    if declared is not None:
        return declared
    if colour is None:
        return text
    rgb = parse_hex(colour)
    return replace(text, fg=Colour("ink", Ink(T, rgb, tty256=nearest256(rgb)), T))


class _View:
    """Where a TextInput's text sits in a rect (the module's view): the prefix, the
    field, the rows shown, the first column, the cursor's display column."""

    def __init__(self, node: "TextInput", R: Rect, ctx: object) -> None:
        self.R = R
        rows = node._rows
        self.P, self.L = _prefix(node.label, ctx)
        self.F = max(0, R.w - self.P)
        self.E = width(ctx.glyph("ellipsis"))
        n, H = len(rows), R.h
        top = 0 if n <= H else n - max(H - 1, 0)
        cap = H if n <= H else max(H - 1, 0)
        if node.scroll is not None:
            t = min(node.scroll[1], top)
        elif cap == 0 or node._line < cap:
            t = 0
        else:
            t = min(node._line - cap + 1, top)
        self.n, self.t, self.shown = n, t, min(cap, n - t)
        self.c = node._display(node._line, node._column)
        self.s = node.scroll[0] if node.scroll is not None else self._first(node._tw(node._line))

    def _first(self, tw: int) -> int:
        """The first column shown, following the cursor clear of the overflow marks."""
        F, E, c = self.F, self.E, self.c
        if tw + 1 <= F:
            return 0
        for s in range(c + 1):
            lm = E if s > 0 else 0
            rm = E if tw > s + F else 0
            if s + lm <= c < s + F - rm:
                return s
        return max(0, c - F + 1)

    def cursor(self, node: "TextInput") -> "tuple[int, int] | None":
        """The cursor cell's screen position when its row shows and it is in the field."""
        R = self.R
        if not self.t <= node._line < self.t + self.shown:
            return None
        x = R.x + self.P + self.c - self.s
        if not self.P <= x - R.x < R.w:
            return None
        return x, R.y + node._line - self.t


@dataclass(frozen=True)
class TextInput:
    """One line or an area of the app's edit value (see the module)."""

    edit: object
    _: KW_ONLY
    label: "str | Line" = ""
    placeholder: "str | Line" = ""
    mask: "str | None" = None
    scroll: "tuple[int, int] | None" = None
    disabled: bool = False
    focused: "bool | None" = None
    runs: "tuple | None" = None
    id: Hashable = None
    size: object = None
    anchor: object = None
    scope: object = None
    surface: bool = False

    def __post_init__(self) -> None:
        """Read and check the edit and the fields (see Errors)."""
        read = {}
        for name in ("rows", "line", "column", "selection"):
            if not hasattr(self.edit, name):
                raise TypeError(f"edit lacks {name!r}")
            read[name] = getattr(self.edit, name)
        rows, line, column, sel = read["rows"], read["line"], read["column"], read["selection"]
        if not isinstance(rows, tuple) or not all(isinstance(r, str) for r in rows):
            raise TypeError("edit.rows must be a tuple of str")
        for name, value in (("line", line), ("column", column)):
            if not _is_int(value):
                raise TypeError(f"edit.{name} must be an int, got {type(value).__name__}")
        if sel is not None:
            _pair("edit.selection", sel)
        _check_text("label", self.label)
        _check_text("placeholder", self.placeholder)
        if self.mask is not None and not isinstance(self.mask, str):
            raise TypeError(f"mask must be None or a str, got {type(self.mask).__name__}")
        if self.scroll is not None:
            _pair("scroll", self.scroll)
        _check_flag("disabled", self.disabled)
        _check_flag("focused", self.focused, none=True)
        _check_common(self)
        if not rows:
            raise ValueError("edit.rows must not be empty")
        if not 0 <= line < len(rows):
            raise ValueError(f"edit.line {line} is outside range({len(rows)})")
        if column < 0:
            raise ValueError(f"edit.column must be >= 0, got {column}")
        if sel is not None:
            a, b = sel
            if a < 0 or b < 0 or a > b:
                raise ValueError(f"edit.selection must be (a, b) with 0 <= a <= b, got {sel!r}")
        if self.scroll is not None and min(self.scroll) < 0:
            raise ValueError(f"scroll values must be >= 0, got {self.scroll!r}")
        if self.mask is not None and (len(cluster(self.mask)) != 1 or width(self.mask) != 1):
            raise ValueError(f"mask must be one cluster one cell wide, got {self.mask!r}")
        _check_runs(self.runs)
        object.__setattr__(self, "_rows", rows)
        object.__setattr__(self, "_line", line)
        object.__setattr__(self, "_column", column)
        object.__setattr__(self, "_selection", None if sel is None else (sel[0], sel[1]))
        object.__setattr__(self, "_clusters", tuple(cluster(r) for r in rows))

    # -- the text, by display columns (cells; clusters when masked)

    def _cl(self, r: int) -> "tuple[str, ...]":
        return self._clusters[r]

    def _cols(self, r: int) -> "list[int]":
        """The display column where each cluster of row `r` starts, then the row's end."""
        out, d = [0], 0
        for piece in self._cl(r):
            d += 1 if self.mask is not None else width(piece)
            out.append(d)
        return out

    def _tw(self, r: int) -> int:
        return len(self._cl(r)) if self.mask is not None else width(self._rows[r])

    def _display(self, r: int, column: int) -> int:
        """A cell column of row `r` as a display column (masked: a cluster count)."""
        if self.mask is None:
            return column
        k, w = 0, 0
        for piece in self._cl(r):
            w += width(piece)
            if w > column:
                break
            k += 1
        return k

    def _shown_line(self, r: int, ctx: object) -> Line:
        if self.mask is not None:
            return _plain(self.mask * len(self._cl(r)), ctx.style("text"))
        run = self.runs[r] if self.runs is not None and r < len(self.runs) else None
        if run is None or run[0] != self._rows[r]:
            return _plain(self._rows[r], ctx.style("text"))
        return Line(tuple(Span(chunk, syntax_style(ctx, role, colour)) for chunk, role, colour in run[1]))

    def chrome(self) -> None:
        """None: no insets."""
        return None

    def lifts(self, ctx: object) -> bool:
        """Always False."""
        return False

    def zone(self, ctx: object) -> int:
        """The key zone: Text's `measure` of the label (none when unlabelled), at least
        `ctx.zone` (see the module)."""
        z = measure((self.label,) if _plain_of(self.label) != "" else ())
        return z if ctx.zone is None else max(ctx.zone, z)

    def measure(self, axis: str, room: int, ctx: object, content: int = 0) -> int:
        """The prefix, the widest row and the cursor's cell; one row per row (see the module)."""
        _check_measure(axis, room, content)
        if axis == "y":
            return len(self._rows)
        P, _ = _prefix(self.label, ctx)
        widest = max(max(self._tw(r) for r in range(len(self._rows))), _width(self.placeholder))
        return P + widest + 1

    def paint(self, rect: Rect, ctx: object, grid: Grid, clip: "Rect | None" = None
              ) -> "tuple[Hit, ...]":
        """The key, the rows in view, the selection and the cursor cell (see the module)."""
        begun = _begin(rect, grid, clip)
        if begun is None:
            return ()
        clip, area = begun
        g = ctx.ground()
        _ground(grid, area, g.style)
        R = rect
        v = _View(self, R, ctx)
        st = _Styler(ctx)
        fx = R.x + v.P
        focused, hovered = _focus(self, ctx), ctx.is_hovered(self.id)
        texts: "list[tuple[int, int, int]]" = []
        leads: "dict[int, int]" = {}
        for r in range(v.t, v.t + v.shown):
            y = R.y + r - v.t
            if r == v.t:
                _, mx, mstyle = _key(self.label, ctx, R, y, grid, area)
                for state, on in (("focused", focused), ("hover", hovered)):
                    if on and st.treat(state).mark:
                        _mark(grid, mx, y, area, st.treat(state).mark, mstyle, R)
                        break
            leads[r] = self._row(r, y, fx, v, ctx, grid, area, texts)
        if self._rows == ("",) and _plain_of(self.placeholder) and v.shown and v.F > 0:
            line = _fitted(_styled(self.placeholder, ctx, "muted"), v.F, ctx)
            _put(grid, fx, R.y, line, area)
        if v.n > R.h >= 1:
            _indicator(grid, R, R.y + R.h - 1, area, ctx, v.t, v.n - v.t - v.shown)
        if self._selection is not None:
            self._select(v, fx, leads, st, grid, area)
        if self.disabled:
            for y, x0, x1 in texts:
                _restyle(grid, x0, x1, y, area, st.apply("disabled"))
        if hovered:
            for r in range(v.t, v.t + v.shown):
                _restyle(grid, fx, R.right, R.y + r - v.t, area, st.apply("hover"))
        if focused:
            at = v.cursor(self)
            if at is not None:
                x, y = at
                cell: dict = {}     # Speed: a wide cluster's two cells share a style

                def how(s: object) -> object:
                    try:
                        return cell[s]
                    except KeyError:
                        out = cell[s] = ctx.apply(s, "focused", "cell")
                        return out
                    except TypeError:
                        return ctx.apply(s, "focused", "cell")

                _restyle(grid, x, x + 1, y, area, how)
        _shade(grid, area, g.style)
        return () if self.id is None else (Hit(clip, self.id),)

    def _row(self, r: int, y: int, fx: int, v: _View, ctx: object, grid: Grid, area: Rect,
             texts: list) -> int:
        """Row `r`'s field cells on cell row `y`; its lead (cells of the left mark)."""
        F, s, E = v.F, v.s, v.E
        if F <= 0 or not area.y <= y < area.bottom:
            return 0
        line = self._shown_line(r, ctx)
        tw = self._tw(r)
        if F < E:
            body = cut(line, F, start=s)
            lead = 0
        else:
            lead = E if s > 0 and tw > 0 else 0
            if lead:
                _put(grid, fx, y, _plain(ctx.glyph("ellipsis"), ctx.style("muted")), area)
            body = cut(line, F - lead, start=s + lead, ellipsis=ctx.glyph("ellipsis"))
        _put(grid, fx + lead, y, body, area)
        if body.width:
            texts.append((y, fx + lead, fx + lead + body.width))
        return lead

    def _select(self, v: _View, fx: int, leads: dict, st: _Styler, grid: Grid, area: Rect
                ) -> None:
        """The selected clusters' cells, and each selected break's one cell."""
        a, b = self._selection
        R = v.R
        how = st.apply("selected")
        base = 0
        for r in range(len(self._rows)):
            k = len(self._cl(r))
            if r >= v.t + v.shown or base >= b:
                break
            if r >= v.t and base + k + 1 > a:
                y = R.y + r - v.t
                lo = fx + leads.get(r, 0)
                cols = self._cols(r)
                for j in range(max(0, a - base), min(k, b - base)):
                    x0, x1 = max(fx + cols[j] - v.s, lo), min(fx + cols[j + 1] - v.s, R.right)
                    _restyle(grid, x0, x1, y, area, how)
                if r < len(self._rows) - 1 and a <= base + k < b:
                    x = fx + cols[k] - v.s
                    if lo <= x < R.right:
                        _restyle(grid, x, x + 1, y, area, how)
            base += k + 1

    def cursor_at(self, rect: Rect, ctx: object, clip: "Rect | None" = None
                  ) -> "tuple[int, int] | None":
        """The screen cell of the cursor, when it is drawn (see the module)."""
        if not isinstance(rect, Rect):
            raise TypeError(f"rect must be a Rect, got {type(rect).__name__}")
        if clip is None:
            clip = rect
        elif not isinstance(clip, Rect):
            raise TypeError(f"clip must be a Rect or None, got {type(clip).__name__}")
        if not _focus(self, ctx):
            return None
        at = _View(self, rect, ctx).cursor(self)
        if at is None or not rect.contains(*at) or not clip.contains(*at):
            return None
        return at

    def locate(self, rect: Rect, ctx: object, x: int, y: int) -> "tuple[int, int] | None":
        """The `(line, column)` under screen cell `(x, y)`, in the field (see the module)."""
        if not isinstance(rect, Rect):
            raise TypeError(f"rect must be a Rect, got {type(rect).__name__}")
        for name, value in (("x", x), ("y", y)):
            if not _is_int(value):
                raise TypeError(f"{name} must be an int, got {type(value).__name__}")
        v = _View(self, rect, ctx)
        R = rect
        if not (R.x + v.P <= x < R.right and R.y <= y < R.y + v.shown):
            return None
        line = v.t + (y - R.y)
        d = v.s + (x - R.x - v.P)
        cl = self._cl(line)
        if self.mask is not None:
            return line, width("".join(cl[:min(d, len(cl))]))
        col = 0
        for piece in cl:
            w = width(piece)
            if col + w > d:
                break
            col += w
        return line, col
