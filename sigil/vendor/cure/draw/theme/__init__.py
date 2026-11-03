"""[Theme]: roles, charsets, ramp, states, scopes, the shelf.

Kind: system (the expansion of [Theme] in Draw); pure. Depends on Style, and on Text
for [Pattern] alone (its `cluster` and `width`: a pattern's cells are counted at load,
refine round 7): a {Context} and a {Node} arrive as arguments and are used by their
attributes (see [Scope]); theme TEXT arrives as strings (Files reads it; nothing here
reads a file).

Vocabulary and medium apart: a theme declares names (roles, palette entries, tokens);
cure maps names to the terminal. [Parse] reads the strict YAML subset into a {Raw}
and follows `extends` among the texts given; [Roles] resolves the open, dotted role
set into Styles (through Style's `style({Spec})`); [Derive] computes the derived
colours at load; [Charset] builds the glyphs; [Ramp] the surface levels; [States]
the visual-state treatments; [Scope] the per-node override; [Shelf] the shipped
themes as texts (builtin, light, contrast, and wire, an example of patterns) and the
lookup an app runs after Files; [Pattern] a run's start, fill and end, laid along n
cells by its fits law (names-free: [Charset] names the runs from its leaves, R3a).

The boundary (the ops other systems call), defined here:

- `enter(node, ctx) -> Context` ({Node} => {Context}, for Paint's [Painter], at its one
  recursion point): the context for `node` from its parent's. First the node's
  scope swaps (Q9b, sigil's ruling on Scope's direction: only `[Scope] -> [Theme] :
  scoped` is drawn, so Theme never calls into [Scope]; a {Scope} is a VALUE that
  Theme's `scoped` built, its theme made ahead at load, and `enter` reads its two
  fields itself, never calling Scope's `enter`):
  - `node.scope` is read. `None`: no swap (`c` is `ctx` itself). Not a `Scope` (an
    `isinstance` check on Scope's data class): `TypeError` ("node.scope must be a
    Scope or None").
  - Otherwise the swaps are `theme=scope.theme` when that is not None, then
    `charset=scope.charset` when that is not None, and `c` is
    `dataclasses.replace(ctx, **swaps)` with only those fields given; a scope whose
    fields are both None gives `ctx` itself. The two axes are independent (swapping
    the theme leaves `ctx.charset` as it is), and nothing is resolved: the scope's
    theme was built by `scoped`, its derived colours computed then.
  The result is exactly what `scope.enter(node, ctx)` gives today, cell for cell and
  `is` for `is`. Then,
  when `node.surface` is true (the node is a surface: a box that takes the next
  ground level), `dataclasses.replace(c, level=c.level + 1)`. A node that has no
  scope and is not a surface gets `ctx` itself back (the same object). `ctx` is any
  dataclass instance with the fields `theme`, `charset` and `level` (an `int`: the
  app's base level at the root, decision 6); `node` any object with the attributes
  `scope` (a `Scope` or None) and `surface` (a `bool`). The level is the real tree
  depth counted from the app's base (from_tree, see [Ramp]); the ground a node paints
  at is `level(theme.ramp, ctx.level)`, clamped there, never here.
  Errors: `TypeError` when `node.scope` is neither a `Scope` nor None, when
  `node.surface` is not a `bool`, or (from `dataclasses.replace`) when `ctx` is not
  a dataclass instance; `AttributeError` when `node` lacks `scope` or `surface`. The
  scope is read and checked before `surface`, as today.

- `parts(charset, token, n, base, *, weight=None) -> tuple[tuple[str, str], ...]`
  (R3a addendum, for R3b): the run's n cells as [Pattern]'s `lay_parts(charset.pattern(
  token, weight), n, b)` gives them, `(glyph, part)`, part one of `CELL_PARTS`, with
  `b` the Base of `base` and the checks of `run`'s step 1 (token, base, weight, n; no
  `focused`). So a widget that may not import Theme can measure a run's start and
  end as laid (Block's title rect): `run`'s glyphs equal `parts`' glyphs, cell for
  cell (law `parts_agree_run`).
- `run(theme, charset, token, n, base, *, weight=None, style=None, focused=False) ->
  tuple[tuple[str, Style], ...]` (the `[Widgets] -> [Theme] : run({Run}) => {Glyphs}`
  flow, R3a; Draw's {Context} offers it as `ctx.run(token, n, base, ...)`, passing its
  own `theme` and `charset`): a run's n cells, each `(glyph, style)`, its pattern laid
  along n cells. Every repeated run a widget draws asks it, never `glyph * n` (R3b
  moves Block's and Overlay's edges, Paint's gutters, Scrollbar's track and Progress's
  bar onto it). `theme` is any object with `style(role)` and `border(focused)` (a
  Theme); `charset` a {Charset} (the context's: a [Scope] may swap it). Arguments:
  - `token`: the run's name (`"frame.pane.top"`, `"frame.gutter.x"`,
    `"run.progress.track"`; [Charset]'s Patterns); any `str` (an unknown run lays as
    the base);
  - `n`: the run's length in cells (an `int >= 0`, as [Pattern]'s `lay`);
  - `base`: the base drawing, the glyphs the widget draws today, as plain strs (the
    widget families may not import Theme, so they never build a `Base`): a `str` `g`
    for a run with no ends (`Base(None, g, None)`, R1r: a frame's side, a track, a
    gutter, a bar; a fill-only pattern reaches both edges), or a tuple
    `(start, fill, end)` of three strs (`Base(start, fill, end)`: a top edge's `(tl, h,
    tr)`);
  - `weight`: the Block's current border weight (its `focus_border` while it lifts),
    for `frame.<kind>.<weight>.<edge>` first; `None`: the plain run only;
  - `style`: the EDGE style, the one the run's cells take today (a track's
    `ctx.style("progress.track")`); `None`: `theme.border(focused)`, a border's style
    at its state (receded at rest, full on focus), today's for a frame or a gutter;
  - `focused`: the state (a Block passes its `lifts(ctx)`), for the default edge style
    and for every role part.

  The result, in order:
  1. Checks, each raised before anything is laid: `token` not a `str`:
     `TypeError(f"token must be a str, got {type(token).__name__}")`; `base` neither a
     `str` nor a `tuple` of exactly three `str`s: `TypeError(f"base must be a glyph or
     a (start, fill, end) tuple of glyphs, got {type(base).__name__}")` (a tuple of
     another length or holding a non-`str` included); an empty glyph: Base's
     `ValueError(f"Base.{part} is empty")`; `weight` as [Charset]'s `pattern`;
     `focused` not a `bool`: `TypeError(f"focused must be a bool, got
     {type(focused).__name__}")`; `n` as `lay` (`TypeError` / `ValueError`, `lay`'s
     messages).
  2. `p = charset.pattern(token, weight)` (the weight-qualified run first, else the
     plain run, else `Pattern()`; under the ascii base a non-ASCII pattern is already
     gone, dropped at build).
  3. `edge = style if style is not None else theme.border(focused)`.
  4. For each `(glyph, part)` of [Pattern]'s `lay_parts(p, n, b)`, in order: the cell
     `(glyph, s)` where `s` is
     - `edge` when `part == "base"` (a missing part, a fallback end when the run is too
       short, a cut's leftover `base.fill` cell, the whole run when `n < 2`): a base
       cell NEVER takes a part role;
     - else, with `r = charset.role(token, part, weight)` (the role of that part of
       the run `pattern` chose): `edge` when `r` is None; otherwise the ROLE STYLE
       `theme.style(f"{r}.focus") if focused else theme.style(r)`.
     A wide cluster's tail `""` cell takes its head's style. Round 13: a cell tagged
     `"after"` (the after's k cells over the fill, [Pattern]'s rule 1) is a part cell
     like the other three: it takes the part role `<run>.after.role` exactly as a
     `"start"`, `"fill"` or `"end"` cell takes its own (`charset.role(token, "after",
     weight)`, `after` being one of [Charset]'s `PATTERN_PARTS`), and the edge style
     when that run names no after role (wire names none); a `base.fill` cell inside
     or just past the after (tagged `"base"`) takes `edge`. Nothing else in `run`,
     `parts` or their checks changes: `parts` gives the `"after"` tags as `lay_parts`
     does, and a share is never read here (it is the Pattern's, already laid).

  The role style is the border's own state treatment with the part's role in place of
  `border`: States' `border(roles, focused)` is `style_of(roles, "border.focus")` when
  focused (falling back up the dots to `border`, then `default`) else
  `style_of(roles, "border")`; a role part takes `R.focus` when focused (falling back
  to `R`, then up R's dots, then `default`) else `R`. So the states apply on top of a
  part's role the way they do for a border: a theme that wants a part receded at rest
  and up on focus gives it a role pair as `border` / `border.focus` are (`end.role:
  foot` with `foot: $dim` and `foot.focus: $accent`), and a role with no `.focus`
  declared (`accent`) reads the same in both states.
  A part whose role is `border` is drawn exactly as a part with no role (when `style`
  is None). A derived role `kind:rest` reads `theme.style(f"{kind}:{rest}.focus")`
  when focused (Theme's `style`: `rest.focus`'s style with its derived fg). The role
  style is the role's alone (no bg added): the widget lays its ground's bg under
  every run cell afterwards, as it does for the edge style today.

  Never a ThemeError at draw: patterns are checked at load, and a role that does not
  resolve in `theme` (a hand-built Scope pairing a charset with another theme) degrades
  as any unknown role does (Roles' fallback to `default`).

Loading a theme (`load(name, texts, *, ascii=False) -> Theme`), all at once (derived
colours included, decision 1):

1. `raw = chain(name, texts)` ([Parse]). `texts` maps theme names to texts (Files'
   `shelf(path).texts`); when it has no key `"builtin"`, `BUILTIN` stands in for it,
   so any theme may `extends: builtin` (a partial theme then overrides only what it
   names).
2. The reserved scalars: `name` and `label` (any text) and `type` (`dark` or
   `light`; absent: `dark`), each a single leaf with nothing below it; otherwise a
   ThemeError at the leaf ("type must be dark or light", "label must be a scalar").
3. `palette = palette(raw)`; `roles = derive_all(resolve(raw), derivation(raw))`;
   `charset = glyphs(raw, ascii=ascii)` (its patterns built, checked and, under the
   ascii base, dropped: [Charset]'s Patterns); then the PART ROLES are checked (R3a,
   here because this is the one place that holds both the charset's role leaves and
   the roles: a Charset holds no roles, Roles no charset); `ramp = ramp(raw, roles)`.
   The check: for each `(leaf, role, where)` of [Charset]'s `role_leaves(raw)` in
   order (every role leaf of the theme, the ones the ascii drop removed included, so
   a theme loads or fails alike in both modes), the role must RESOLVE in `roles`: with
   `kind, colon, rest = role.partition(":")` and, when there is no colon, `rest =
   role` (a plain role is its own name), `kind` (when `colon`) must be in
   Derive's `KINDS`, and some candidate of `rest`'s dot-prefixes (`rest` itself, then
   each prefix made by dropping its last segment: `progress.fill.end` ->
   `progress.fill`, `progress`; never the `default` the fallback chain appends,
   unless `rest`'s first segment is `default`) must be a key of `roles.styles` (a
   declared STYLE role; an unstyled parameter in `values` alone does not count).
   Otherwise `ThemeError(*where, f"{leaf}: unknown role '{role}'")`, e.g.
   `"mine:7: charset.frame.pane.bottom.end.role: unknown role 'acent'"`. The first
   failing leaf is raised. `scoped` builds through the same step, so a scope's
   fragment's roles are checked against the merged roles.
4. `Theme(name=name, label=raw.at("label") or name, kind=raw.at("type") or "dark",
   raw=raw, palette=palette, roles=roles, charset=charset, ramp=ramp,
   derivation=derivation(raw))`. The theme's `name` is always the name it was loaded
   by (a `name:` leaf is not used).

Errors: `ThemeError` from any step, naming the source theme and line. `load` itself
never falls back silently. The lookup is Theme's `pick(name, found)` (the Files
flow's `@fallback(builtin)`, the (Sigil)/[Files] comment): a theme Files found wins
over a shelf theme of the same name; a named miss falls back to the shelf by name,
then to `builtin()`; a miss is never an error. A found text that fails (unreadable, a
ThemeError from `pick`) is the app's fallback to take: `pick(name)` (no found texts:
the shelf's, else the builtin) or `builtin()`.

`load` is not memoised: its texts are the caller's, so every call parses and builds
afresh and returns a new Theme (equal to an earlier one of the same arguments).

Other ops:
- `builtin(*, ascii=False) -> Theme`: `load("builtin", {"builtin": BUILTIN},
  ascii=ascii)`, built once per argument set and memoised: the key is `("builtin",
  bool(ascii))` (`ascii` normalised to a `bool`, so `ascii=1` and `ascii=True` share
  one theme) in the module's private dict `_MEMO: dict[tuple[str, bool], Theme]`.
  Every later call with the same key returns the SAME object (`builtin() is
  builtin()`), which is safe because a Theme is immutable all the way down (below).
  Never raises for a keyword `ascii` whose `bool()` answers: `BUILTIN` is valid by
  this contract. A bad call (a positional argument, an unknown keyword, an `ascii` whose
  `bool()` raises) raises as today (`TypeError`, or what `bool()` raised) before the
  memo is read, and nothing is cached. Two threads racing on an empty key may each
  build; both themes are equal and the memo keeps one (no lock: a duplicate build is
  harmless). The memo is the shelf's too (W2): each shelf theme is built once under
  `(name, bool(ascii))` in the same `_MEMO` by Theme's `shelved` (builtin's key is
  `("builtin", ...)`: `shelved("builtin") is builtin()`); nothing else is ever stored
  there.
  For tests: `_MEMO` may be cleared (`_MEMO.clear()`) to start cold, and `_build` is a
  module-level function that `load` and `builtin` reach by its module global name
  at call time, so a test may wrap it (`unittest.mock.patch("cure.draw.theme._build",
  wraps=_build)`) and count its calls; cheapness is proved by that count, never by a
  wall-clock threshold.
- Theme's shelf ops (Theme's own: [Shelf] is data, no ops), defined here beside
  `builtin` (they read `load` and `_MEMO`; their contract is Theme's, written in
  `shelf.py` beside the texts, a module that holds the texts and imports nothing of
  this package, so there is no import cycle): `shelved(name, *, ascii=False) -> Theme
  | None` (a shelf theme, memoised in `_MEMO`; `shelved("builtin") is builtin()`) and
  `pick(name, found=None, *, ascii=False) -> Theme` (found, then shelf, then builtin).
  [Shelf]'s data `SHELF` (name -> text, read-only; `SHELF["builtin"] is BUILTIN`) and
  `NAMES` (`("builtin", "light", "contrast", "wire")`) are re-exported.
- `scoped(theme, text, source="<scope>") -> Scope`: a per-node override written as a
  theme fragment (any palette entries, roles, `charset`, `ramp`, `derive` leaves).
  `parse(text, source)`; an `extends` leaf in it is a ThemeError ("a scope cannot
  extend"); its `name` and `label` leaves are dropped; the fragment is merged over
  `theme.raw` ([Parse]'s `merge`) and built exactly as `load` step 3-4 builds a
  theme (name and label kept from `theme`; `ascii` true when `theme.charset.name ==
  "ascii"`). The result is `Scope(theme=<that theme>, charset=<its charset>)` when the
  fragment has a leaf under `charset`, else `Scope(theme=<that theme>)`. This is the
  drawn `[Scope] -> [Theme] : scoped({Raw}) => {Scope}`: Theme hands Scope the built
  theme as a value (the `Scope` it returns), and Scope never calls back into Theme.

Immutable all the way down (the rule every data class of this package follows, each
naming its fields): a Theme and everything it reaches is frozen or read-only, so a
memoised theme cannot be changed by any caller.

- Frozen dataclasses (`Theme`, `Raw`, `Roles`, `Charset`, `Ramp`, `Ground`,
  `Derivation`, `Scope`, `Treatment`; Core's `Style`, `Colour`, `Ink`): attribute
  assignment and deletion raise `dataclasses.FrozenInstanceError`.
- Every mapping field is stored, in `__post_init__`, as a `types.MappingProxyType`
  over a private `dict` copy of the mapping given (any `Mapping`, a proxy included):
  item assignment, deletion and `update` / `pop` / `clear` / `setdefault` /
  `popitem` raise (`TypeError` for `[k] = v` and `del`, `AttributeError` for the
  methods, which a proxy lacks), and the caller's mapping is never kept (changing it
  afterwards changes nothing). Reading is unchanged (`[k]`, `get`, `in`, `len`,
  iteration in the given order, `keys` / `values` / `items`, `{**m}`, `dict(m)`), and
  equality with a plain dict holds both ways (`MappingProxyType(d) == d`), so a
  dataclass's `==` is by value as today.
- Every sequence field is stored as a `tuple` (`tuple(x)` of what was given: a list
  becomes a tuple; a tuple is kept as is).
- The values inside are immutable already (strs, ints, floats, tuples, Core's frozen
  Style, Colour and Ink); nothing is copied deeper than the field.
- Module tables a theme's methods read at call time are read-only too: Charset's
  `UNICODE`, `POWERLINE`, `ASCII` and `TABLES`, States' `TABLE`, Derive's
  `DEFAULTS` are `MappingProxyType`s (their contents as today).
- Hashing is kept as is. `Theme`, `Raw`, `Roles` and `Charset` have a dataclass
  `__hash__` that raises `TypeError` today (a dict field) and still raises
  (`hash` of a mappingproxy is its dict's: unhashable); they compare by value and
  are never a dict key or a set member (the memo is keyed by `(name, ascii)`, never by
  a theme). `Ramp`, `Ground`, `Derivation`, `Treatment` and a `Scope` holding
  neither a Theme nor a Charset stay hashable.
- Copying and pickling work as today: each class holding a mapping field (`Theme`,
  `Raw`, `Roles`, `Charset`) defines `__reduce__` as `(type(self), (<its fields in
  order, each mapping as a plain dict copy>))` ([Parse]'s public `rebuild`; the
  mapping and sequence fields are stored through Parse's `freeze_maps` and
  `freeze_seqs`: Q9b, `Theme` included, never Parse's private `_freeze` / `_reduce`), so `copy.copy`, `copy.deepcopy` and
  `pickle` (which cannot take a mappingproxy) give an equal, equally read-only object
  (a new one, never the memoised one). `dataclasses.replace` builds through
  `__init__`, so a replaced field is copied and wrapped by the same rule.

Laws (the proofs of W1m):
- equal: `builtin(ascii=a) == builtin(ascii=a)` and `builtin(ascii=a) is
  builtin(ascii=a)` for `a` in (False, True); `builtin(ascii=1) is builtin(ascii=True)`;
  `builtin() is not builtin(ascii=True)`; two `load` calls of the same arguments are
  equal and not identical.
- immutable: walking every field of a builtin theme (and of its `raw`, `roles`,
  `charset`, `ramp`, `derivation`, every Style, Colour and Ink reached), every mapping
  refuses item assignment, deletion and `update`, every frozen dataclass refuses
  attribute assignment, and no mutable `dict`, `list` or `set` is reached; after
  every refused attempt the theme still equals a fresh `load` of the builtin; a dict
  given to a constructor and changed afterwards leaves the object unchanged.
- cheap: with `_MEMO` cleared and `_build` wrapped, the first `builtin(ascii=a)` runs
  `_build` once and the second runs it zero times (a count, no clock).
- unchanged: every style (each role in `roles.styles`, and `style(r)` of each derived
  `kind:role`), every glyph (`charset.glyphs`, `plots`), every ground (`ground(d)` and
  `ground(d, focused=True)` over the ramp) and the palette of `builtin(ascii=a)` equal
  those of today's HEAD (the commit before W1m, loaded by git through
  `tests/_gitref.py`, never a copy), field by field (the two Theme classes differ, so
  not by the Theme's own `==`); so every frame is today's.

Laws of the run op and the part roles (R3a; a test loops over themes with and without
patterns, both ascii modes, every weight, `n` in 0..N, `focused` both ways, `style`
None and given):
- base_unchanged: for a charset with no patterns (`patterns == {}`: the builtin, every
  theme before R3, any theme with no `frame` / `run` leaf), `run(t, cs, token, n,
  base, weight=w, style=s, focused=f) == tuple((g, e) for g in lay(Pattern(), n, b))`
  with `e = s if s is not None else t.border(f)` and `b` the Base of `base`: today's
  glyphs and the edge style, cell for cell; for a top edge `"".join(g for g, _ in
  run(...)) == tl + h * (n - 2) + tr`, and for a track `g * n`.
- fits (carried from [Pattern]): `tuple(g for g, _ in run(t, cs, token, n, base,
  ...)) == lay(cs.pattern(token, w), n, b)`, so the run is exactly n cells, never half
  a cluster, never a cell outside the run or its base.
- weight_first (carried from [Charset]): the cells follow `cs.pattern(token, w)`, the
  weight-qualified run first; the roles follow the same run (`cs.chosen`).
- ascii_drop (carried from [Charset]): under `load(..., ascii=True)` (or a theme of
  base ascii) every glyph `run` gives is ASCII or one of `base`'s.
- role_checked_at_load: `load` raises the ThemeError above for a role leaf whose role
  does not resolve, and loads for one that resolves (declared, or a declared dot-prefix;
  `kind:rest` with a known kind); in both ascii modes alike; never at draw.
- role_style: a cell tagged with part P (not `"base"`) whose run names role R for P
  has style `t.style(R + ".focus") if f else t.style(R)`; every other cell (every
  `"base"` cell, every part with no role) has the edge style; with R = `border` and
  `style` None the cell's style equals the edge's.
- pure: `run` reads only its arguments: equal arguments give equal results.

Data (frozen dataclass; immutable all the way down, as above):
- `Theme(name: str, label: str, kind: str, raw: Raw, palette: Mapping[str, Ink |
  str], roles: Roles, charset: Charset, ramp: Ramp, derivation: Derivation)`: `palette`
  is read-only (a `MappingProxyType` over a copy of the mapping given); `raw`,
  `roles`, `charset`, `ramp` and `derivation` are immutable by their own contracts.
  With:
  - `style(role) -> Style`: [Roles]' `style_of(self.roles, role)`; for a prefixed
    role `"kind:rest"` with `kind` in Derive's `KINDS`, the style of `rest` with
    its `fg` replaced by `derived(self.roles, kind, rest)` (the hosts' CSS reads the
    same names: `muted:kinds.service`). Any other `str` is an unprefixed role (an
    unknown role degrades, never fails).
  - `derived(kind, role) -> Colour | None`: [Derive]'s `derived(self.roles, kind, role)`.
  - `value(role) -> str | None`: `self.roles.values.get(role)` (exact: a parameter
    such as `ui.fill`, as written).
  - `ground(level, *, focused=False) -> Ground`: [Ramp]'s `level(self.ramp, level, 0,
    focused=focused)`.
  - `treat(state, charset=None) -> Treatment`: [States]' `treat(self.roles, state,
    charset if charset is not None else self.charset)`.
  - `border(focused) -> Style`: [States]' `border(self.roles, focused)`.

The built-in theme (`BUILTIN`, defined in [Shelf]'s module `shelf.py` with the other
shipped texts and re-exported here, the same object; part of this contract): a dark theme of inks
with declared tty256 / tty16 fallbacks; roles `default`, `text`, `strong`, `muted`,
`dim`, `accent`, `title`, `border` (receded: the dim ink), `border.focus` (the
accent), `surface.ground`, `surface.component`, `surface.sub`, `surface.raised` (its
ramp, in that order), `state.focused`, `state.selected`, `status.bar`, `key`, `ok`,
`warn`, `error`, `info`; the widget roles `control.on` (`$accent`: a toggle's,
radio's or switch's on glyph) and `control.frame` (`$muted`: a control's brackets,
parentheses and switch track), `progress.fill` (`$accent`: a bar's filled cells, the
pulse's block, the spinner's frame), `progress.track` (`$dim`: a bar's or pulse's
empty cells), `progress.label` (`$fg`, as `text`: a gauge's or spinner's label) and
`progress.figure` (`$muted`: a gauge's percentage), each resolving to exactly the
style of `accent`, `muted`, `accent`, `dim`, `text` and `muted` (the same ink and
attributes; the colour's role tag names the widget role) (a role falls back up
its dots to `default`, so a widget role is declared to keep today's cells; a theme
restyles one kind by setting its role alone); `derive.ground: $ground` (so its `Derivation` has
`ground256=(18, 18, 18)` and `ground16=(0, 0, 0)`, from the ground ink's 233 and
black); charset `unicode`. Its derived colours are `"ink"` Colours whose tty256 /
tty16 fallbacks are derived from the base inks' declared ones ([Derive]), e.g.
`roles.derived["tint:accent"] == Colour("ink", Ink("tint:accent", (54, 31, 67),
236, "black"), "tint:accent")`.

Re-exported for consumers: `ThemeError`, `Raw`, `parse`, `merge`, `chain`, `palette`
(parse); `Roles`, `resolve`, `fallbacks`, `style_of`, `overlay` (roles); `Derivation`,
`derive`, `derive_all`, `derivation` (derive); `Charset`, `glyphs` (charset); `Ramp`,
`Ground`, `ramp`, `level` (ramp); `Treatment`, `treat`, `apply`, `border` (states);
`Scope` (scope); `Pattern`, `Base`, `pattern`, `clusters`, `lay`, `lay_parts`,
`is_ascii` (pattern); `BUILTIN`, `SHELF`, `NAMES` (shelf); `shelved`, `pick` and `run` are this
module's own (above). Note: the functions `parse`, `ramp`, `derive` and `pattern`
shadow the submodules of the same names as package attributes; reach a submodule's own names
with a from-import of its dotted path (`from cure.draw.theme.ramp import Ground`).

Effects: none.

Usage:
    from dataclasses import dataclass
    from types import SimpleNamespace as Node
    from cure.draw.theme import load, builtin, enter, BUILTIN
    t = load("mine", {"mine": "extends: builtin\\npalette:\\n  fg: \\"#ffffff\\"\\n"})
    t.style("text").fg.hex             # "#ffffff": text is $fg, and fg was overridden
    t.style("list.item.selected")      # default's style: falls back up the dots
    t.ground(1).role                   # "surface.component"
    t.treat("focused").mark            # "›"
    @dataclass(frozen=True)
    class Ctx:
        theme: object
        charset: object
        level: int = 0
    ctx = Ctx(t, t.charset)
    enter(Node(scope=None, surface=True), ctx).level    # 1
    enter(Node(scope=None, surface=False), ctx) is ctx  # True
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import repeat

from cure.core.style import Colour, Ink, Style

from .charset import _EMPTY, Charset, glyphs, role_leaves
from .derive import KINDS as _KINDS
from .derive import Derivation, derivation, derive, derive_all
from .derive import derived as _derived
from .parse import Raw, ThemeError, chain, freeze_maps, merge, palette, parse, rebuild
from .pattern import Base, Pattern, _lay_checks, clusters, is_ascii, lay, lay_parts, pattern
from .ramp import Ground, Ramp, level, ramp
from .ramp import level as _level
from .roles import Roles, fallbacks, overlay, resolve, style_of
from .scope import Scope
from .shelf import BUILTIN, NAMES, SHELF
from .states import Treatment, apply, border, treat


@dataclass(frozen=True)
class Theme:
    """{Theme}: a loaded theme: its roles (derived colours included), charset and ramp.

    Immutable all the way down (see the module): frozen, `palette` a read-only
    `MappingProxyType` over a copy made in `__post_init__`; `__reduce__` rebuilds it
    from plain dicts (copy and pickle as today).
    """

    name: str
    label: str
    kind: str
    raw: Raw
    palette: Mapping
    roles: Roles
    charset: Charset
    ramp: Ramp
    derivation: Derivation

    def __post_init__(self) -> None:
        freeze_maps(self, "palette")

    def __reduce__(self):
        return rebuild(self)

    def style(self, role: str) -> Style:
        """The role's style along its fallback chain; `kind:role` gives a derived fg."""
        kind, colon, rest = role.partition(":") if isinstance(role, str) else ("", "", role)
        if colon and kind in _KINDS:
            return replace(style_of(self.roles, rest), fg=_derived(self.roles, kind, rest))
        return style_of(self.roles, role)

    def derived(self, kind: str, role: str) -> "Colour | None":
        """The role's derived colour of `kind`, along its fallback chain."""
        return _derived(self.roles, kind, role)

    def value(self, role: str) -> "str | None":
        """The role's value as written (exact name), or None."""
        return self.roles.values.get(role)

    def ground(self, level: int, *, focused: bool = False) -> Ground:
        """The ground at surface level `level` (clamped; +1 when focused)."""
        return _level(self.ramp, level, 0, focused=focused)

    def treat(self, state: str, charset: "Charset | None" = None) -> Treatment:
        """The treatment of `state`, marks from `charset` (default: the theme's)."""
        return treat(self.roles, state, charset if charset is not None else self.charset)

    def border(self, focused: bool) -> Style:
        """A border's style: `border.focus` when focused, else `border`."""
        return border(self.roles, focused)


def load(name: str, texts: Mapping[str, str], *, ascii: bool = False) -> Theme:
    """The theme `name`, its `extends` followed among `texts` (see Loading a theme).

    Not memoised: the texts are the caller's; a new Theme on every call.
    """
    if "builtin" not in texts:
        texts = {**texts, "builtin": BUILTIN}
    raw = chain(name, texts)
    _check_reserved(raw)
    return _build(name, raw.at("label") or name, raw, ascii)


def builtin(*, ascii: bool = False) -> Theme:
    """The built-in theme (`BUILTIN`), the app's fallback: built once per `bool(ascii)`.

    Memoised in `_MEMO` under `("builtin", bool(ascii))` (the shelf's memo too, W2);
    the same object on every later call. A bad call raises before the memo is read
    and caches nothing. Tests count `_build` calls (wrap the module global), never time.
    """
    key = ("builtin", bool(ascii))
    theme = _MEMO.get(key)
    if theme is None:
        theme = _MEMO.setdefault(key, load("builtin", {"builtin": BUILTIN}, ascii=key[1]))
    return theme


_MEMO: "dict[tuple[str, bool], Theme]" = {}
"""The memo of `builtin` (and the shelf's, W2): `(name, bool(ascii))` -> its Theme."""


def shelved(name: str, *, ascii: bool = False) -> "Theme | None":
    """Theme's `shelved` (over [Shelf]'s data): the shelf theme `name`, built once per `(name, bool(ascii))`
    in `_MEMO` (`builtin(ascii=ascii)` for `"builtin"`); None for a name not on the shelf.

    The contract is Theme's, written in `shelf.py` beside the texts; it lives here beside `builtin` because it
    reads `load` and `_MEMO` (the shelf module imports nothing of the package).
    """
    if not isinstance(name, str):
        raise TypeError(f"a theme name must be a str, got {type(name).__name__}")
    flag = bool(ascii)
    if name not in SHELF:
        return None
    if name == "builtin":
        return builtin(ascii=flag)
    key = (name, flag)
    theme = _MEMO.get(key)
    if theme is None:
        theme = _MEMO.setdefault(key, load(name, SHELF, ascii=flag))
    return theme


def pick(name: str, found: "Mapping[str, str] | None" = None, *, ascii: bool = False) -> Theme:
    """Theme's `pick` (over [Shelf]'s data): a found text of `name` wins (`load(name, {**SHELF, **found})`,
    not memoised; a ThemeError raises), else `shelved(name)`, else `builtin()`.

    The contract is Theme's, written in `shelf.py`; it lives here for the same reason as
    `shelved`.
    """
    if not isinstance(name, str):
        raise TypeError(f"a theme name must be a str, got {type(name).__name__}")
    if found is not None and not isinstance(found, Mapping):
        raise TypeError(f"found must be a mapping or None, got {type(found).__name__}")
    flag = bool(ascii)
    if found is not None and name in found:
        return load(name, {**SHELF, **found}, ascii=flag)
    theme = shelved(name, ascii=flag)
    return builtin(ascii=flag) if theme is None else theme


def scoped(theme: Theme, text: str, source: str = "<scope>") -> Scope:
    """A {Scope} whose theme is `theme` with a fragment laid over it (see Other ops)."""
    fragment = parse(text, source)
    for path in fragment.leaves:
        if path[0] == "extends":
            raise ThemeError(*fragment.lines[path], "a scope cannot extend")
    kept = {p: v for p, v in fragment.leaves.items() if p not in (("name",), ("label",))}
    fragment = Raw(fragment.source, kept, {p: fragment.lines[p] for p in kept})
    raw = merge(theme.raw, fragment)
    _check_reserved(raw)
    inner = _build(theme.name, theme.label, raw, theme.charset.name == "ascii")
    if any(p[0] == "charset" for p in kept):
        return Scope(theme=inner, charset=inner.charset)
    return Scope(theme=inner)


def enter(node: object, ctx: object) -> object:
    """The {Context} for `node`: its scope's swaps, and one level up when it is a surface."""
    c = ctx
    scope = node.scope
    if scope is not None:
        if not isinstance(scope, Scope):
            raise TypeError(f"node.scope must be a Scope or None, got {type(scope).__name__}")
        swaps = {k: v for k, v in (("theme", scope.theme), ("charset", scope.charset)) if v is not None}
        if swaps:
            c = replace(ctx, **swaps)
    surface = node.surface
    if not isinstance(surface, bool):
        raise TypeError(f"node.surface must be a bool, got {type(surface).__name__}")
    return replace(c, level=c.level + 1) if surface else c


def run(theme: object, charset: Charset, token: str, n: int, base: "str | tuple[str, str, str]", *,
        weight: "str | None" = None, style: "Style | None" = None,
        focused: bool = False) -> "tuple[tuple[str, Style], ...]":
    """A run's n cells, each `(glyph, style)`: its pattern laid along n cells (see The boundary).

    A part with no role, and every base cell, takes the edge style (`style`, else
    `theme.border(focused)`); a part with role R takes `theme.style(R + ".focus")`
    when focused, else `theme.style(R)`.
    """
    b = _run_base(token, base, weight)
    if not isinstance(focused, bool):
        raise TypeError(f"focused must be a bool, got {type(focused).__name__}")
    c = charset.chosen(token, weight)             # once: pattern and role both answer from it
    if c is None:                                 # no pattern: the base, laid once per (n, base)
        _lay_checks(_EMPTY, n, b)
        laid = _base_lay(n, b)
        edge = style if style is not None else theme.border(focused)
        return tuple(zip(laid, repeat(edge)))
    cells = lay_parts(charset.patterns[c], n, b)
    edge = style if style is not None else theme.border(focused)
    styles = {"base": edge}                       # one lookup per part laid
    for part in {p for _, p in cells} - {"base"}:
        r = charset.part_roles.get(f"{c}.{part}")  # Charset.role's answer, c chosen
        styles[part] = edge if r is None else theme.style(f"{r}.focus" if focused else r)
    return tuple((g, styles[p]) for g, p in cells)


def parts(charset: Charset, token: str, n: int, base: "str | tuple[str, str, str]", *,
          weight: "str | None" = None) -> "tuple[tuple[str, str], ...]":
    """A run's n `(glyph, part)` cells: `lay_parts` of its chosen pattern (see The boundary)."""
    b = _run_base(token, base, weight)
    c = charset.chosen(token, weight)
    if c is None:                                 # no pattern: the base, laid once per (n, base)
        _lay_checks(_EMPTY, n, b)
        return _base_parts(n, b)
    return lay_parts(charset.patterns[c], n, b)


@lru_cache(maxsize=1024)
def _base_lay(n: int, base: Base) -> tuple:
    """`lay(_EMPTY, n, base)`, memoised: n and base already checked, so it never raises."""
    return lay(_EMPTY, n, base)


@lru_cache(maxsize=1024)
def _base_parts(n: int, base: Base) -> tuple:
    """`lay_parts(_EMPTY, n, base)`, memoised: n and base already checked, so it never raises."""
    return lay_parts(_EMPTY, n, base)


def _run_base(token: object, base: object, weight: object) -> Base:
    """`run`'s and `parts`' step-1 checks of token, base and weight; the Base of `base`."""
    if not isinstance(token, str):
        raise TypeError(f"token must be a str, got {type(token).__name__}")
    if isinstance(base, str):
        b = Base(None, base, None)                # a run with no ends (R1r)
    elif type(base) is tuple and len(base) == 3 and all(isinstance(g, str) for g in base):
        b = Base(*base)
    else:
        raise TypeError("base must be a glyph or a (start, fill, end) tuple of glyphs, got "
                        f"{type(base).__name__}")
    if weight is not None and not isinstance(weight, str):
        raise TypeError(f"weight must be a str or None, got {type(weight).__name__}")
    return b


def _check_part_roles(raw: Raw, roles: Roles) -> None:
    """Load step 3's part-role check: each role leaf's role resolves in `roles` (every mode)."""
    for leaf, role, where in role_leaves(raw):
        kind, colon, rest = role.partition(":")
        if not colon:
            rest = role
        seg = rest.split(".")
        if (colon and kind not in _KINDS) or not any(
                ".".join(seg[:i]) in roles.styles for i in range(len(seg), 0, -1)):
            raise ThemeError(*where, f"{leaf}: unknown role '{role}'")


def _check_reserved(raw: Raw) -> None:
    """`name`, `label` and `type` are single leaves; `type` is dark or light."""
    for path in raw.leaves:
        if path[0] in ("name", "label", "type") and len(path) > 1:
            raise ThemeError(*raw.lines[path], f"{path[0]} must be a scalar")
    if raw.at("type") not in (None, "dark", "light"):
        raise ThemeError(*raw.line("type"), "type must be dark or light")


def _build(name: str, label: str, raw: Raw, ascii: bool) -> Theme:
    """Load step 3-4: palette, roles (derived filled), charset, its part roles checked
    against the roles (R3a: `role_leaves`, ThemeError "<leaf>: unknown role 'x'"), and
    ramp of `raw`.

    The one place a Theme is built (`load`, `builtin` through `load`, `scoped`); a
    module-level function reached by its global name at call time, so a test may wrap
    `cure.draw.theme._build` to count builds.
    """
    entries = palette(raw)
    roles = resolve(raw)
    d = derivation(raw)
    roles = derive_all(roles, d)
    charset = glyphs(raw, ascii=ascii)
    _check_part_roles(raw, roles)
    return Theme(name=name, label=label, kind=raw.at("type") or "dark", raw=raw,
                 palette=entries, roles=roles, charset=charset,
                 ramp=ramp(raw, roles), derivation=d)

