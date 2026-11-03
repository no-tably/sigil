"""[Shelf]: the shipped themes as texts: builtin (dark), light, contrast; each extends
builtin, each valid by contract (no file read); a Files theme of the same name wins
over it; plus an example of patterns, written to be copied and edited: wire (a
block-cornered heavy top, a wire bottom with a //▔ corner in accent, a block foot in
the border's own role and a share of half blocks after it; a heavy left side, a light
right one; refine round 13).

Kind: service (module data here, and no ops: the spec's [Shelf] is "data, no ops").
The ops over the shelf, `shelved` and `pick` (with `load`, which they call), are
Theme's own, defined in the Theme package; their contract is written here, beside the
texts it is about, and is Theme's.

Where things live. This module holds the shelf's DATA: the four texts (`BUILTIN`,
`LIGHT`, `CONTRAST`, `WIRE`), `NAMES` and `SHELF`, and imports nothing of the Theme
package (only the stdlib), so the package can import it without an import cycle (conform's
`check_imports` refuses `cure.draw.theme -> .shelf -> cure.draw.theme`). The two ops,
`shelved` and `pick`, read Theme's `load`, `builtin` and `_MEMO`, so they are defined
in the package (`cure/draw/theme/__init__.py`) beside `builtin`; they are Theme's ops,
and their contract (below) is Theme's, kept in this module beside the texts. The package re-exports `BUILTIN`, `SHELF` and `NAMES` (the same
objects): `cure.draw.theme.BUILTIN is cure.draw.theme.shelf.BUILTIN`. Reach the ops as
`cure.draw.theme.shelved` / `.pick`.

What it does: the library ships four themes as TEXT, so an app (and the gallery) can
switch among them by name with no file on disk. `SHELF` holds the texts; `shelved`
builds a shelf theme by name, once per charset, in Theme's memo; `pick` is the lookup
an app runs after Files has read its search path: a theme Files found wins, then the
shelf's of that name, then `builtin()` (the spec's `(Sigil) -> [Files] : read ...
@fallback(builtin)`: "a file found wins over a shelf theme of the same name; a named
miss falls back to the shelf by name, then to builtin"; refine-3 Q1 (a)).

Data (part of this contract; the texts below are the exact themes):
- `SIGIL_ROLES`: sigil's highlighting roles, a tuple of 24 dotted names (syntax.*,
  ui.*, kinds.*; sigil's H1 table, the fixture's roles among them).
- `NAMES = ("builtin", "light", "contrast", "wire")`: the shelf's names, in the shelf's
  order (the gallery's `t` key cycles them in it); `wire` (R4, refine round 7 Q5) comes
  last, after contrast.
- `SHELF: Mapping[str, str]`: a read-only `types.MappingProxyType` mapping each name of
  `NAMES`, in that order, to its text. `SHELF["builtin"] is BUILTIN` (Theme's built-in
  theme, the same object, defined below and re-exported by the package; its contract
  is the package's "The built-in theme", unchanged). `LIGHT` and `CONTRAST` are two
  more texts, module constants, and `WIRE` the fourth (its own rules: "The wire
  theme", below; the list here is light's and contrast's, not wire's). Each of light
  and contrast:
  - says `extends: builtin` and gives its own `name`, `label` and `type`;
  - declares every palette entry BUILTIN declares (`ground`, `surface`, `raised`,
    `overlay`, `fg`, `bright`, `muted`, `dim`, `accent`, `select`, `ok`, `warn`,
    `error`, `info`) as an ink with `rgb`, `tty256` and `tty16`, as BUILTIN does (so
    every colour, and every derived colour, has declared fallbacks at every depth);
  - declares `derive.ground: $ground` and the same `ramp` (`surface.ground
    surface.component surface.sub surface.raised`);
  - declares every role BUILTIN declares, by the same names (`default`, `text`,
    `strong`, `muted`, `dim`, `accent`, `title`, `border`, `border.focus`,
    `surface.ground`, `surface.component`, `surface.sub`, `surface.raised`,
    `state.focused`, `state.selected`, `status.bar`, `control.on`, `control.frame`,
    `progress.fill`, `progress.track`, `progress.label`, `progress.figure`, `key`,
    `ok`, `warn`, `error`, `info`), each written out in full (nothing is left to be
    inherited: a later change to BUILTIN's roles moves no shelf theme's role);
  - declares, beyond them, the TASK family, Views' DAG states (Overview's DagView
    `STYLES`): `task.ready`, `task.held`, `task.running`, `task.done`, `task.failed`
    (a colour only: the label's word is the cue), each within the theme's own rules
    (below). BUILTIN does not declare them (Views' DAG roles stay at `default` there:
    colouring builtin moves construct's frames, a later, separate change), so
    `set(theme.roles.styles)` is exactly BUILTIN's keys plus the five task roles
    plus the SIGIL family below (their order is [Parse]'s `merge`'s: `border: x` over
    BUILTIN drops and re-appends `border.focus`; the task roles, then the sigil roles,
    come last);
  - declares the SIGIL family, sigil's highlighting roles (refine round 5, Q2):
    `"sigil." + role` for every role of `SIGIL_ROLES` (sigil's dotted role verbatim,
    so never clashing with cure's), written as the nested block `sigil:` / `syntax:`,
    `ui:`, `kinds:`. A run TextInput paints carries sigil's role and hex; a theme's
    `sigil.<role>` overrides the hex, and an undeclared role keeps sigil's hex (never
    plain). BUILTIN declares none (sigil's own colours show there). The checked-in
    fixture `tests/fixtures/sigil/construct.highlight.json` (`sigil highlight --json`,
    keyed on its `sigil_highlight` version) is the source: every role it carries is in
    `SIGIL_ROLES` and so declared here;
  - declares, beyond BUILTIN's palette entries, the inks its sigil roles need, each
    an ink with `rgb`, `tty256` and `tty16` (light: `pink`, `rose`, `periwinkle`,
    `violet`, `teal`, `navy`, `slate`; contrast: `pink`, `rose`, `periwinkle`,
    `violet`, `blue`, `sky`, `cyan`).

The wire theme (`WIRE`, R4; refine round 7 Q5 and its roles addendum, settled; its
block and pane edges redrawn by refine round 13, the look sigil's user approved): an
EXAMPLE of patterns, written to be copied and edited (a user's own theme takes a name
of its own and says `extends: wire`, or copies the text). It is builtin's look with
patterns on it: it says `extends: builtin` and brings NO palette, ramp or `derive` of
its own (builtin's colours, unchanged: `palette`, `ramp`, `derivation` and every
ground equal builtin's), no task family and no sigil family (as builtin: Views' DAG
roles stay at `default`, sigil's own colours show), and exactly ONE role of its own,
`border.focus: $accent bold` (builtin's `$accent` plus `bold`; why: Invariant
no_hue_alone, below). Its other roles are builtin's, inherited, NOT written out (the
opposite of light's and contrast's rule: wire is "builtin plus patterns", so a later
change to builtin's roles moves wire with it, by design, and the text stays short
enough to read as an example). So `set(theme.roles.styles)` is exactly BUILTIN's
keys, and every style but `border.focus` equals builtin's.

The text, exactly (`WIRE`; the module constant is part of this contract):

    # cure's wire theme: an example of patterns, to copy and edit. builtin's colours;
    # the edges of a Block (kind block) and of construct's panes (kind pane): a
    # block-cornered heavy top; a wire bottom with a block foot, a tenth of the run in
    # half blocks after it, and a //▔ corner in accent; a heavy left side, a light right.
    extends: builtin
    name: wire
    label: Wire
    type: dark

    border.focus: $accent bold   # focus reads by a flag too: a patterned edge keeps its
                                 #   glyphs on focus (the top is heavy at rest)

    charset:
      frame.block.top:           # every Block an app draws (Block's kind, by default)
        start: "▛▀"              # the block corner, two cells: the title moves in past it
        fill: "━"
        end: "┑"
      frame.block.bottom:
        start: "▙"               # the foot,
        start.role: border       #   in the border's own role (receded, up on focus),
        after: "▀"               #   then half blocks over the wire's first cells,
        after.share: 0.10        #   a tenth of the run (at least one cell)
        fill: "─┴─"
        end: "//▔"               # the corner,
        end.role: accent         #   in accent, at rest and on focus
      frame.block.left.fill: "┃"
      frame.block.right.fill: "│"
      frame.pane.top:            # construct's panes (Views' kind pane), the same look
        start: "▛▀"
        fill: "━"
        end: "┑"
      frame.pane.bottom:
        start: "▙"
        start.role: border
        after: "▀"
        after.share: 0.10
        fill: "─┴─"
        end: "//▔"
        end.role: accent
      frame.pane.left.fill: "┃"
      frame.pane.right.fill: "│"
      frame.gutter.x.fill: "┃"   # a split's gutters: side by side, stacked
      frame.gutter.y.fill: "━"
      run.progress.track:        # a bar's empty cells: a wire with a plug at its end
        fill: "─"
        end: "╼"

What it builds (`shelved("wire")`, its charset; [Charset]'s Patterns):
- `charset.name == "unicode"`, `glyphs` and `plots` exactly builtin's (no glyph
  override: every leaf of the section is a pattern leaf);
- `charset.patterns`, in this order (each run's first part leaf's): `frame.block.top`
  `Pattern(("▛", "▀"), ("━",), ("┑",))`; `frame.block.bottom` `Pattern(("▙",), ("─",
  "┴", "─"), ("/", "/", "▔"), after=("▀",), share=0.1)` (the share `float("0.10")`);
  `frame.block.left` `Pattern((), ("┃",), (), vertical=True)`; `frame.block.right`
  `Pattern((), ("│",), (), vertical=True)`; the same four for `frame.pane.*`;
  `frame.gutter.x` `Pattern((), ("┃",), (), vertical=True)`; `frame.gutter.y`
  `Pattern((), ("━",), ())`; `run.progress.track` `Pattern((), ("─",), ("╼",),
  vertical=True)` (every `run.` run is held vertical: one cell per cluster; the
  gutters and the track are as before round 13). No weighted run
  (`frame.<kind>.<weight>.<edge>`): the plain run serves every weight, so a focused
  Block (drawn at its `focus_border`, `heavy`) lays the same glyphs as at rest
  wherever the ends fit, and reads its focus by its style (`border.focus`, bold) and
  its ground's lift; `chosen(r, w)` is `r` for every weight `w` (weight_first holds
  vacuously: a theme that copies wire and adds a `frame.pane.heavy.bottom` gets it on
  focus, the plain one at rest);
- `charset.part_roles == {"frame.block.bottom.start": "border", "frame.block.bottom.end":
  "accent", "frame.pane.bottom.start": "border", "frame.pane.bottom.end": "accent"}`
  (the after names no role: `role("frame.pane.bottom", "after")` is None). Both
  resolve at load (Theme's check: `border` and `accent` are declared roles).
- The part roles at draw (the package's `run`, the rule R -> R / R.focus): the foot
  `▙` (role `border`) takes `style("border.focus")` focused, else `style("border")`,
  which is exactly the edge's own style (`theme.border(focused)`; the package's "a part
  whose role is `border` is drawn exactly as a part with no role"): written out to
  show the syntax, it changes no cell. The after's `▀` cells name no role, so they
  take the edge style, as the foot does (the foot and its share read as one block).
  The corner `//▔` (role `accent`) takes `style("accent.focus")` focused, which falls
  back to `accent` (wire declares no `accent.focus`, and need not: the load check
  resolves `accent` itself, and a role with no `.focus` reads the same in both
  states, the addendum's own example), so the corner is accent at rest and on focus
  while the rest of the edge comes up from dim to accent bold.
- Under the ascii base (`shelved("wire", ascii=True)`): every run above holds a
  non-ASCII cell (the top's `▛▀`, the bottom's `▙`, `▀` and `─┴─`, the corner's `▔`,
  the sides' `┃` and `│`), so every one is dropped at build: `patterns == {}`,
  `part_roles == {}`, the charset equal to `builtin(ascii=True).charset`. Wire in
  ascii draws as builtin in ascii, cell for cell, a focused border's `bold` aside.
- Exact cells (`ctx = Context.of(shelved("wire"), level=1)`; Block's own example,
  kind `block`, and the same for kind `pane`). The top's start `▛▀` is two cells, so
  Block's title rect moves in past it (Block's "The start and end AS LAID": `ws == 2`,
  `we == 1` wherever the top's ends fit, `R.w >= 3`): `T == Rect(R.x + 3, R.y, max(0,
  R.w - 5), 1)`, one cell narrower than before round 13. `Block(title="Title")` at `Rect(0, 0,
  13, 4)` (`T == Rect(3, 0, 8, 1)`, the label `" Title "` at x 3..9, left):
  `"▛▀━ Title ━━┑"`, `"┃           │"` twice, `"▙▀┴──┴──┴─//▔"` (the bottom: `m ==
  9`, `k == min(max(1, round(1.3)), 9) == 1`, so one `▀` over the fill's first cell,
  the fill's `─┴──┴──┴─` keeping its phase); `//▔` (x 10..12, row 3) in
  `ctx.style("accent")`, the label's two spaces in `ctx.border(False)`, `"Title"` in
  `ctx.style("title")`, every other edge cell (`▙` and `▀` included) in
  `ctx.border(False)`. Focused (`focused=True`, or `ctx.focus` its `id`): the same
  four rows, `//▔` in `ctx.style("accent")` and every other edge cell, the label's
  spaces included, in `ctx.border(True)` (accent bold), the ground one level up. At
  `Rect(0, 0, 25, 4)` (`T == Rect(3, 0, 20, 1)`): `"▛▀━ Title ━━━━━━━━━━━━━━┑"`,
  `"┃                       │"` twice, `"▙▀▀──┴──┴──┴──┴──┴──┴─//▔"` (`m == 21`, `k ==
  round(2.5) == 2`), the same styles, rest and focused alike. At Block's natural width
  for the title, `Rect(0, 0, 11, 4)` (`measure("x", ...) == width("Title") + 6`), `T.w
  == 6` is too narrow for `" Title "`, so the title is cut: `"▛▀━ Tit… ━┑"` (Block's
  measure note: wire's two-cell top start is the case it names). The bottom row of
  `Block()` (kind `block` or `pane`) at `Rect(0, 0, w, 3)`, by width, at rest and
  focused alike while the ends fit: 15 `"▙▀▀──┴──┴──┴//▔"` (`k == round(1.5) == 2`),
  10 `"▙▀┴──┴─//▔"`, 6 `"▙▀┴//▔"`, 5 `"▙▀//▔"` (`m == 1`: `round(0.5) == 0`, raised
  to 1), 4 `"▙//▔"` (the ends just fit, `m == 0`: no after); at 3 (too short for `▙`
  + `//▔`) the base fallback, `"╰─╯"` (`"┗─┛"` focused: the heavy base corners, the
  pattern's `─` between), no after; at 2 `"╰╯"` (`"┗┛"` focused). The top row at 3
  `"▛▀┑"`, at 2 `"╭╮"` (`"┏┓"` focused). The sides: `┃` down the left, `│` down the
  right, every row between the corners, in the edge style. A gutter: `┃` down every
  row (`x`), `━` along (`y`), in `ctx.border(False)`. `Bar(0.55)` 10 cells:
  `"█████▌───╼"`; `Bar(0.0)` 3 cells `"──╼"`, 1 cell `"╼"`; the track in
  `progress.track`. A Scrollbar's track, Tabs' and Tree's glyphs, a Pulse and a
  Spinner are builtin's (wire patterns none of them). Views' overlays (kind
  `dialog`) draw as builtin: wire patterns `block` and `pane` only.

The palettes in brief (the texts are authoritative):
- `light` (`type: light`): ground white `#ffffff`, ramp `#f6f8fa` → `#eaeef2` →
  `#dde3e9`; text `#1f2328`, strong `#0d1117` bold; muted `#59636e`; dim `#818b98`
  (receded, as BUILTIN's dim); focus `on #ddf4ff`; accents darkened for a light
  ground: accent `#6639ba`, ok `#116329`, warn `#7d4e00`, error `#a40e26` bold, info
  `#0550ae`, each at least 5.4:1 on every ramp ground (WCAG, below). BUILTIN's roles
  with BUILTIN's flags; the task family from those accents, so each is readable as
  they are, at least 5.4:1 on every ramp ground and on the focused and selected rows:
  `task.ready` `$info`, `task.held` `$warn`, `task.running` `$accent`, `task.done`
  `$ok`, `task.failed` `$error bold` (as `error`). The sigil family a colour only (no
  flags, as sigil's own), each ink at least 5.4:1 on every ground: sigil's hues
  darkened for a light ground, the theme's inks reused where the meanings match
  (keyword `$accent`, modifier, mode and store `$warn`, number `$info`, actor `$ok`,
  tag `$fg`, section `$bright`), the receded ones (punct, notes, payload, hole)
  `$slate` `#4d5560` (sigil's muted and dim would fall under 5.4:1).
- `contrast` (`type: dark`): ground black `#000000`, ramp `#121212` → `#1c1c1c` →
  `#262626`; focus `on #00204a`; text and strong `#ffffff`; muted `#d0d0d0`; dim
  `#bcbcbc` (not receded: it carries text); accent `#ff99ff`; ok `#87ff87`; warn
  `#ffd75f` underline; error `#ff9999` bold; info `#87d7ff` italic; borders `$bright`
  at rest and `$bright bold` on focus; the task family from the status inks and the
  accent, each with its own flags: `task.ready` `$info italic`, `task.held` `$warn
  underline`, `task.running` `$accent bold underline`, `task.done` `$ok`,
  `task.failed` `$error bold`; the sigil family from those inks and seven more, each
  7:1 on every ground, told apart per family by flags and two luminance tiers (the
  rules below).

The contrast rules (what `no_hue_alone` proves of `contrast`), exactly:

- Luminance: an `(r, g, b)` colour's relative luminance is WCAG 2's: each channel
  c / 255 linearised (`c / 12.92` when `c <= 0.04045`, else `((c + 0.055) / 1.055) **
  2.4`), `L = 0.2126 R + 0.7152 G + 0.0722 B`; the ratio of two colours is `(L1 +
  0.05) / (L2 + 0.05)` with L1 the lighter. Colours are the truecolour inks (an ink's
  `rgb`); the tty256 / tty16 fallbacks are declared but not measured (their rgb is the
  terminal's).
- Text 7:1. The GROUNDS are the backgrounds a role's text may be drawn on: every ramp
  ground's `bg` (`theme.ground(d).style.bg` and `theme.ground(d, focused=True)`, so the
  focused lift is included), and the row backgrounds of `state.focused` and
  `state.selected`. Every styled role R with an `fg` (the role tags aside, by its
  rgb): when R's own style has a `bg` (`key`, `status.bar`, `state.selected`), its fg
  is at least 7:1 against that bg; otherwise at least 7:1 against every one of the
  GROUNDS. This covers every text-bearing and glyph-bearing role (text, strong,
  title, key, accent, ok, warn, error, info, progress.label, progress.figure,
  progress.fill, progress.track, control.on, control.frame, muted, dim, border,
  border.focus, status.bar, default, and the task family: task.ready, task.held,
  task.running, task.done, task.failed, and the sigil family, every `sigil.` role).
  A `reverse` floor (selected) swaps fg and bg,
  which keeps the ratio; a `dim` flag (the muted and disabled states) is the
  terminal's rendering and is not measured.
- Borders at full: `border` and `border.focus` both have the fg `$bright` (`#ffffff`,
  15.1:1 or more on every ground); focus adds `bold` (a non-hue cue), so a focused box
  reads by its weight and its ground's lift, never by a hue.
- Not by hue alone. Two roles of one FAMILY are told apart other than by hue when
  their fg luminance ratio is at least 1.5:1, OR their depth-0 cues differ: for a role,
  its style's set of flags that are on (`bold`, `dim`, `italic`, `underline` not None,
  `strike`, `reverse`); for a state, the pair `(treat(state).mark, <its style's flag
  set>)` (a mark is a glyph, so it reads at depth 0, where Sgr still sends flags). The
  families and how contrast meets the rule:
  - `ok`, `warn`, `error`, `info` (Toast's kinds, the status colours): their
    luminances (0.78, 0.71, 0.46, 0.61) all sit high so each clears 7:1, so they cannot
    also be 1.5:1 apart (four values would span 1.5**3 = 3.4:1); every pair is told
    apart by its flags instead: ok none, warn `underline`, error `bold`, info `italic`
    (four distinct sets).
  - `task.ready`, `task.held`, `task.running`, `task.done`, `task.failed` (Views' DAG
    states): the same inks as the status family and the accent (luminances 0.61,
    0.71, 0.51, 0.78, 0.46), all high so each clears 7:1 (8:1 or more on every
    ground but failed's 7.4:1), so they cannot all be 1.5:1 apart; every pair is
    told apart by its flags instead, the status family's where the meaning is
    theirs: ready `italic` (as info), held `underline` (as warn), running `bold
    underline`, done none (as ok), failed `bold` (as error): five distinct sets.
  - the sigil families, `sigil.syntax.*`, `sigil.ui.*`, `sigil.kinds.*` (each a family
    of its own): 7:1 on the most lifted ground puts every fg at luminance 0.44 or
    more, so only two tiers fit 1.5:1 apart: low (0.44 to 0.51) and high (0.71 to 1).
    Two roles share a flag set only as one low and one high (at least 1.5:1 apart);
    every other pair differs in flags. syntax: `{}` tag `$fg` (high) / punct `$dim`
    (low); `{bold}` modifier `$warn` (high) / operator `$pink` (low); `{italic}`
    string `$sky` (high) / number `$blue` (low); `{underline}` call `$ok` (high) / ref
    `$violet` (low); keyword `$accent bold italic`, call_name `$rose bold underline`,
    cardinality `$rose italic underline` alone. ui: `{}` payload `$fg` (high) /
    note_tag `$dim` (low); mode `$warn bold`, section `$bright bold underline`, note
    `$muted italic` alone. kinds: `{}` actor `$ok` (high) / service `$periwinkle`
    (low); `{bold}` store `$warn` (high) / event `$pink` (low); `{italic}` state
    `$cyan` (high) / data `$violet` (low); hole `$dim underline`, alias `$rose bold
    italic` alone.
  - the states (`STATES`, through `treat` in either charset): focused `(›, {})`,
    selected `(•, {reverse})`, hover `("", {underline})`, pressed `(●, {reverse,
    bold})`, active `(●, {bold})`, emphasised `(✦, {bold})`, muted `(·, {dim})`,
    disabled `("", {dim})`: eight distinct pairs (in ascii, `>` `*` `""` `@` `*` `+`
    `.` `""`: selected and active share `*` and differ by `reverse`), so no two states
    differ by colour alone; contrast's `state.focused` (`on $select`) and
    `state.selected` (`$bright on $raised`) add colour over those cues, and the floors
    hold whatever a theme says ([States]).

Theme's ops over the shelf (Theme's own, defined in the Theme package; the shelf has
none, see "Where things live"):
- `shelved(name, *, ascii=False) -> Theme | None`: the shelf theme `name`, or None when
  `name` is not a key of `SHELF` (a miss is never an error). `"builtin"` is
  `builtin(ascii=ascii)` (the same object: `shelved("builtin") is builtin()`, one memo
  key `("builtin", bool(ascii))`). Any other shelf name: built by `load(name, SHELF,
  ascii=bool(ascii))` once per key `(name, bool(ascii))` and kept in Theme's `_MEMO`
  (the package's dict, read at call time: "the memo is the shelf's too"), exactly as
  `builtin` keeps its own (`get`, else `setdefault` of the built theme); every later
  call with the same key returns the SAME object. Nothing is built at import: a shelf
  theme is built only when looked up. A shelf theme is built from `SHELF` alone, never
  from texts Files found (so a found `builtin` never changes `shelved("light")`).
  Never raises for a `str` name and a keyword `ascii` whose `bool()` answers (each
  shelf text is valid by this contract). `TypeError` when `name` is not a `str` (or
  for a positional `ascii`, an unknown keyword); what `bool(ascii)` raised; in each case
  before the memo is read, and nothing is cached.
- `pick(name, found=None, *, ascii=False) -> Theme`: the theme an app draws with for
  the chosen `name` ([Files]' `chosen`), in this order:
  1. `found` is not None and `name` is a key of it (a text Files found, `shelf(path).
     texts`): `load(name, {**SHELF, **found}, ascii=bool(ascii))`. Not memoised (the
     texts are the caller's): a new Theme on every call. A ThemeError raises (a found
     text that fails to load is the app's fallback to take, never silently replaced
     here).
  2. else `shelved(name, ascii=ascii)` when it is not None (the memoised object);
  3. else `builtin(ascii=ascii)` (the memoised object).
  `found` is None or a `Mapping[str, str]` (anything else: `TypeError`); `name` a `str`
  (else `TypeError`). A name that is not a valid theme NAME is simply a miss (step 3).
  Only step 1 can raise ThemeError.

How a found theme's `extends` resolves (step 1): the texts given to `load` are the
shelf's overlaid by the found ones, `{**SHELF, **found}`, so [Parse]'s `chain` looks
each parent name up there: a FOUND text of that name first, else the SHELF text of
that name; an unknown name is chain's ThemeError ("unknown theme 'x' (not among the
themes given)"). So a found `mine.yaml` may say `extends: light` or `extends: contrast`
(the shelf's) or `extends: builtin` (BUILTIN, unless Files also found a `builtin`, which
then stands in for it in that chain: a file found wins, in a chain as at the top). A
found theme named like a shelf theme that extends its own name (`light.yaml` saying
`extends: light`) is chain's "extends cycle: light -> light" ThemeError: the found
text has replaced the shelf's under that name; a user's variation of a shelf theme
takes a name of its own. Found texts never reach a shelf theme built by steps 2-3.

Invariant: every_role — every role a widget asks for resolves in each shelf theme to
  a declared role, and every role Views' tabs ask for resolves in light and contrast
  to a declared role: the roles are DERIVED, never listed: every node kind Widgets
  exports (walked from its package, each in each of its kinds and states: focused,
  hovered, each item state, both charsets) is painted with a context whose theme
  records every role it is asked for (`style(role)` records `role`, a prefixed
  `kind:role` records `role`; `derived(kind, role)` records `role`; `border(focused)`
  records `"border.focus"` or `"border"`), and for every recorded role R and every
  shelf theme T, the first of `fallbacks(R)` that is a key of `T.roles.styles` exists
  and is not `"default"` (R == `"default"` aside). Likewise every Views tab (both
  board-wide tabs, each part's tab, each inspector page, focus on each pane, both
  charsets) is framed with such a context, and every role it records resolves so in
  `light` and `contrast` (builtin, and wire with builtin's roles, leave Views' DAG
  roles, the task family, at `default`: a later, separate change). Every shelf
  theme's `roles.styles` has BUILTIN's keys; light's and contrast's add exactly the
  task family and the sigil family; wire's adds none (exactly BUILTIN's keys). Wire
  is walked like every other shelf theme (its patterns change glyphs, never the roles
  a widget asks for), and its part roles resolve to declared roles (`border`,
  `accent`: Theme's load check, here asserted of the shelf: for every `(leaf, role,
  where)` of `role_leaves(raw)` the first of `fallbacks(role)` in `roles.styles` is
  `role` itself).
Invariant: no_hue_alone — in `contrast`, no two roles of one family (the status
  family, the task family, the states, each sigil family) differ by hue alone and text meets 7:1 against its ground (the rules above, over contrast's
  resolved roles and treatments); and with colour off (depth 0) every state still
  shows its mark or its floor flag, in both charsets, in `contrast` and in `wire`.
  The 7:1 and family rules are contrast's alone (builtin's colours, which wire keeps,
  make no contrast claim); the colour-off clause is run over wire too, since wire is
  the shelf theme whose glyphs do NOT change with focus: under wire, a Block of a kind
  it patterns (`block`, `pane`) lays the same edge glyphs at rest and focused, so its
  focus must read by something other than hue at depth 0. It does: `border.focus` is
  `$accent bold`, so every edge cell but the accent corner is bold on focus (a flag
  Sgr sends at depth 0), and the corner `//▔` is told from the edge by its glyphs, not
  its colour. (With builtin's `border.focus: $accent`, a focused wire pane would differ
  from one at rest by hue and by its ground's bg alone, neither shown at depth 0: the
  law fails, which is why wire declares the one role.) The colour-off proof's frames
  under wire: every exported kind's samples (as for contrast), and a Block of each kind
  wire patterns at rest against it focused, both charsets (in ascii the patterns are
  dropped and the heavy focus corners differ in glyph as builtin's do).

Laws (the proofs of W2):
- every_role, no_hue_alone: as above.
- loads: `load(n, SHELF, ascii=a)` for every n in `NAMES` and a in (False, True)
  never raises; each light / contrast theme has `kind` its `type` (`"light"`,
  `"dark"`), `name` n, a non-empty ramp of four grounds, and every palette entry an
  `Ink` with `tty256` and `tty16` not None.
- memo: with `_MEMO` cleared and `_build` wrapped, the first `shelved(n, ascii=a)`
  runs `_build` once and the second zero times; `shelved(n, ascii=a) is shelved(n,
  ascii=a)`; `shelved(n, ascii=1) is shelved(n, ascii=True)`; `shelved(n) ==
  load(n, SHELF)`; importing the module builds nothing (`_MEMO` unchanged); each
  shelf theme is immutable all the way down (W1m's walk).
- pick order: a found text of `name` wins (equal to `load(name, {**SHELF, **found})`,
  not identical across calls), a found `light` wins over the shelf's; a found theme
  extending a shelf theme by name loads; a miss in `found` gives `shelved(name)` (`is`);
  a miss everywhere gives `builtin(ascii=ascii)` (`is`), never an error; a found text
  that fails raises ThemeError.
- wire (R4): `SHELF["wire"] is WIRE`; `NAMES[-1] == "wire"`; the text loads in both
  charsets with `name` `"wire"`, `label` `"Wire"`, `kind` `"dark"`; its palette,
  ramp, derivation and every ground equal builtin's (`shelved("wire", ascii=a)` against
  `builtin(ascii=a)`, field by field), every role style but `border.focus` equal
  builtin's, `border.focus` builtin's with `bold=True`; `charset.patterns` and
  `charset.part_roles` exactly as "The wire theme" lists them (keys in order, Patterns
  by value), `glyphs` / `plots` / `name` builtin's; under `ascii=True`, `patterns ==
  {}` and `part_roles == {}` and the charset equal to builtin's ascii charset; the
  exact cells listed there. Loads, memo and pick laws run over every name of `NAMES`,
  wire included (a found `mine` saying `extends: wire` loads, with wire's patterns).
- builtin unchanged: `SHELF["builtin"] is BUILTIN`, `shelved("builtin", ascii=a) is
  builtin(ascii=a)`, and no frame at the builtin theme changes (W1m's unchanged law
  still holds).

Inputs: `shelved`: a `str` name, `ascii`. `pick`: a `str` name, None or a mapping of
  found texts, `ascii`.
Outputs: a {Theme} (or None from `shelved` for a miss).
Errors: `TypeError` as above; `ThemeError` only from `pick` step 1.
Effects: none (the memo aside: a shelf theme is kept once built).

Usage:
    from cure.draw.theme import NAMES, SHELF, BUILTIN, pick, shelved, builtin
    SHELF["builtin"] is BUILTIN              # True
    shelved("light").kind                    # "light"
    shelved("builtin") is builtin()          # True
    shelved("nope")                          # None
    shelved("wire").charset.role("frame.pane.bottom", "end")   # "accent"
    shelved("wire", ascii=True).charset.patterns                # {}: every run dropped
    pick("contrast").name                    # "contrast": the shelf's (memoised)
    pick("contrast", {"contrast": "extends: light\\n"}).kind   # "light": found wins
    pick("nope", {}) is builtin()            # True: a miss is never an error
"""

from collections.abc import Mapping
from types import MappingProxyType

BUILTIN = """\
# cure's built-in theme: what an app draws with when no theme can be read.
name: builtin
label: Built-in
type: dark

palette:
  ground:
    rgb: "#0d1117"
    tty256: "233"
    tty16: black
  surface:
    rgb: "#161b22"
    tty256: "234"
    tty16: black
  raised:
    rgb: "#21262d"
    tty256: "235"
    tty16: bright_black
  overlay:
    rgb: "#30363d"
    tty256: "237"
    tty16: bright_black
  fg:
    rgb: "#c9d1d9"
    tty256: "252"
    tty16: white
  bright:
    rgb: "#e6edf3"
    tty256: "255"
    tty16: bright_white
  muted:
    rgb: "#8b949e"
    tty256: "246"
    tty16: white
  dim:
    rgb: "#6e7681"
    tty256: "243"
    tty16: bright_black
  accent:
    rgb: "#c850e0"
    tty256: "170"
    tty16: magenta
  select:
    rgb: "#264f78"
    tty256: "24"
    tty16: blue
  ok:
    rgb: "#3fb950"
    tty256: "71"
    tty16: green
  warn:
    rgb: "#ffbf47"
    tty256: "215"
    tty16: yellow
  error:
    rgb: "#f85149"
    tty256: "203"
    tty16: red
  info:
    rgb: "#79c0ff"
    tty256: "111"
    tty16: blue

derive:
  ground: $ground

ramp: surface.ground surface.component surface.sub surface.raised

default: $fg
text: $fg
strong: $bright bold
muted: $muted
dim: $dim
accent: $accent
title: $bright bold
border: $dim              # receded at rest
border.focus: $accent     # full on focus
surface:
  ground: on $ground
  component: on $surface
  sub: on $raised
  raised: on $overlay
state:
  focused: on $select
  selected: $bright on $raised
status.bar: $fg on $surface
control.on: $accent       # a control's on glyph
control.frame: $muted     # a control's brackets and track
progress.fill: $accent    # a bar's filled cells, the pulse, the spinner frame
progress.track: $dim      # a bar's or pulse's empty cells
progress.label: $fg       # a gauge's or spinner's label
progress.figure: $muted   # a gauge's percentage
key: $bright on $overlay
ok: $ok
warn: $warn
error: $error bold
info: $info
"""
"""The built-in theme's text (its contract: the package's "The built-in theme")."""

LIGHT = """\
# cure's light theme: a light ground and ramp, dark text, accents for a light ground.
extends: builtin
name: light
label: Light
type: light

palette:
  ground:
    rgb: "#ffffff"
    tty256: "231"
    tty16: bright_white
  surface:
    rgb: "#f6f8fa"
    tty256: "255"
    tty16: bright_white
  raised:
    rgb: "#eaeef2"
    tty256: "254"
    tty16: white
  overlay:
    rgb: "#dde3e9"
    tty256: "253"
    tty16: white
  fg:
    rgb: "#1f2328"
    tty256: "235"
    tty16: black
  bright:
    rgb: "#0d1117"
    tty256: "233"
    tty16: black
  muted:
    rgb: "#59636e"
    tty256: "242"
    tty16: bright_black
  dim:
    rgb: "#818b98"
    tty256: "245"
    tty16: bright_black
  accent:
    rgb: "#6639ba"
    tty256: "55"
    tty16: magenta
  select:
    rgb: "#ddf4ff"
    tty256: "195"
    tty16: cyan
  ok:
    rgb: "#116329"
    tty256: "22"
    tty16: green
  warn:
    rgb: "#7d4e00"
    tty256: "94"
    tty16: yellow
  error:
    rgb: "#a40e26"
    tty256: "124"
    tty16: red
  info:
    rgb: "#0550ae"
    tty256: "25"
    tty16: blue
  pink:                   # the sigil roles' inks (below), each 5.4:1 or more on every ground
    rgb: "#a3125d"
    tty256: "125"
    tty16: magenta
  rose:
    rgb: "#9a1f40"
    tty256: "89"
    tty16: red
  periwinkle:
    rgb: "#3a4bb0"
    tty256: "61"
    tty16: blue
  violet:
    rgb: "#7a2bb0"
    tty256: "91"
    tty16: magenta
  teal:
    rgb: "#0a5c68"
    tty256: "23"
    tty16: cyan
  navy:
    rgb: "#0a3069"
    tty256: "24"
    tty16: blue
  slate:
    rgb: "#4d5560"
    tty256: "240"
    tty16: bright_black

derive:
  ground: $ground

ramp: surface.ground surface.component surface.sub surface.raised

default: $fg
text: $fg
strong: $bright bold
muted: $muted
dim: $dim
accent: $accent
title: $bright bold
border: $dim              # receded at rest
border.focus: $accent     # full on focus
surface:
  ground: on $ground
  component: on $surface
  sub: on $raised
  raised: on $overlay
state:
  focused: on $select
  selected: $bright on $raised
status.bar: $fg on $surface
control.on: $accent       # a control's on glyph
control.frame: $muted     # a control's brackets and track
progress.fill: $accent    # a bar's filled cells, the pulse, the spinner frame
progress.track: $dim      # a bar's or pulse's empty cells
progress.label: $fg       # a gauge's or spinner's label
progress.figure: $muted   # a gauge's percentage
key: $bright on $overlay
ok: $ok
warn: $warn
error: $error bold
info: $info
task:                     # Views' DAG states (a colour only: the label's word is the cue)
  ready: $info
  held: $warn
  running: $accent
  done: $ok
  failed: $error bold
sigil:                    # sigil's highlighting roles (sigil.<role>), a colour only, as sigil's own
  syntax:
    operator: $pink       # -> ~> => !> := &
    keyword: $accent      # state loop parallel branch
    modifier: $warn       # @timeout(2s)
    cardinality: $rose    # x3 ^8
    string: $navy
    ref: $violet          # ${ref}
    number: $info
    punct: $slate
    tag: $fg              # bare names: states, labels
    call: $teal           # a call's ( ) in a payload
    call_name: $rose      #   its name
  ui:
    mode: $warn           # #!spec
    section: $bright      # a section's name
    note_tag: $slate
    note: $slate
    payload: $slate
  kinds:                  # node boxes, by glyph
    service: $periwinkle  # [component]
    data: $violet         # {data}
    event: $pink          # <event>
    actor: $ok            # (actor)
    store: $warn          # |store|
    state: $teal          # a state machine's states
    hole: $slate          # [?]
    alias: $rose          # [[alias]]
"""
"""The light theme's text (see the module)."""

CONTRAST = """\
# cure's high-contrast theme: text 7:1 on every ground, borders at full, and no
# status or state told apart by hue alone (a flag or a mark tells each apart).
extends: builtin
name: contrast
label: High contrast
type: dark

palette:
  ground:
    rgb: "#000000"
    tty256: "16"
    tty16: black
  surface:
    rgb: "#121212"
    tty256: "233"
    tty16: black
  raised:
    rgb: "#1c1c1c"
    tty256: "234"
    tty16: black
  overlay:
    rgb: "#262626"
    tty256: "235"
    tty16: bright_black
  fg:
    rgb: "#ffffff"
    tty256: "231"
    tty16: bright_white
  bright:
    rgb: "#ffffff"
    tty256: "231"
    tty16: bright_white
  muted:
    rgb: "#d0d0d0"
    tty256: "252"
    tty16: white
  dim:
    rgb: "#bcbcbc"
    tty256: "250"
    tty16: white
  accent:
    rgb: "#ff99ff"
    tty256: "213"
    tty16: bright_magenta
  select:
    rgb: "#00204a"
    tty256: "17"
    tty16: blue
  ok:
    rgb: "#87ff87"
    tty256: "120"
    tty16: bright_green
  warn:
    rgb: "#ffd75f"
    tty256: "221"
    tty16: bright_yellow
  error:
    rgb: "#ff9999"
    tty256: "217"
    tty16: bright_red
  info:
    rgb: "#87d7ff"
    tty256: "117"
    tty16: bright_cyan
  pink:                   # the sigil roles' inks (below), each 7:1 or more on every ground;
    rgb: "#ff8fbc"        #   the low tier (luminance 0.44 to 0.45) beside warn, ok, sky, cyan
    tty256: "211"
    tty16: bright_magenta
  rose:
    rgb: "#ff97bd"
    tty256: "218"
    tty16: bright_red
  periwinkle:
    rgb: "#9faeff"
    tty256: "147"
    tty16: bright_blue
  violet:
    rgb: "#cc9eff"
    tty256: "177"
    tty16: bright_magenta
  blue:
    rgb: "#8ab3ff"
    tty256: "111"
    tty16: bright_blue
  sky:
    rgb: "#d7f0ff"
    tty256: "195"
    tty16: bright_cyan
  cyan:
    rgb: "#afffff"
    tty256: "159"
    tty16: bright_cyan

derive:
  ground: $ground

ramp: surface.ground surface.component surface.sub surface.raised

default: $fg
text: $fg
strong: $bright bold
muted: $muted
dim: $dim                 # carries text: 7:1, not receded
accent: $accent
title: $bright bold
border: $bright           # at full at rest
border.focus: $bright bold   # focus by weight and the ground's lift, not by hue
surface:
  ground: on $ground
  component: on $surface
  sub: on $raised
  raised: on $overlay
state:
  focused: on $select
  selected: $bright on $raised
status.bar: $fg on $surface
control.on: $accent       # a control's on glyph
control.frame: $muted     # a control's brackets and track
progress.fill: $accent    # a bar's filled cells, the pulse, the spinner frame
progress.track: $dim      # a bar's or pulse's empty cells
progress.label: $fg       # a gauge's or spinner's label
progress.figure: $muted   # a gauge's percentage
key: $bright on $overlay
ok: $ok                   # the status family, told apart by flags:
warn: $warn underline     #   ok none, warn underline,
error: $error bold        #   error bold,
info: $info italic        #   info italic
task:                     # Views' DAG states, told apart by flags like the status:
  ready: $info italic     #   ready italic,
  held: $warn underline   #   held underline,
  running: $accent bold underline   # running bold underline,
  done: $ok               #   done none,
  failed: $error bold     #   failed bold
sigil:                    # sigil's highlighting roles (sigil.<role>): within a family two
  syntax:                 #   roles share a flag set only 1.5:1 apart in luminance
    tag: $fg              # {} high (1.00)
    punct: $dim           # {} low (0.50)
    operator: $pink bold  # {bold} low (0.45)
    modifier: $warn bold  # {bold} high (0.71)
    keyword: $accent bold italic
    string: $sky italic   # {italic} high (0.84)
    number: $blue italic  # {italic} low (0.45)
    ref: $violet underline   # {underline} low (0.45)
    call: $ok underline   # {underline} high (0.78)
    call_name: $rose bold underline
    cardinality: $rose italic underline
  ui:
    mode: $warn bold
    section: $bright bold underline
    note: $muted italic
    note_tag: $dim        # {} low (0.50)
    payload: $fg          # {} high (1.00)
  kinds:
    service: $periwinkle  # {} low (0.45)
    actor: $ok            # {} high (0.78)
    event: $pink bold     # {bold} low (0.45)
    store: $warn bold     # {bold} high (0.71)
    data: $violet italic  # {italic} low (0.45)
    state: $cyan italic   # {italic} high (0.88)
    hole: $dim underline
    alias: $rose bold italic
"""
"""The high-contrast theme's text (see the module)."""

WIRE = """\
# cure's wire theme: an example of patterns, to copy and edit. builtin's colours;
# the edges of a Block (kind block) and of construct's panes (kind pane): a
# block-cornered heavy top; a wire bottom with a block foot, a tenth of the run in
# half blocks after it, and a //▔ corner in accent; a heavy left side, a light right.
extends: builtin
name: wire
label: Wire
type: dark

border.focus: $accent bold   # focus reads by a flag too: a patterned edge keeps its
                             #   glyphs on focus (the top is heavy at rest)

charset:
  frame.block.top:           # every Block an app draws (Block's kind, by default)
    start: "▛▀"              # the block corner, two cells: the title moves in past it
    fill: "━"
    end: "┑"
  frame.block.bottom:
    start: "▙"               # the foot,
    start.role: border       #   in the border's own role (receded, up on focus),
    after: "▀"               #   then half blocks over the wire's first cells,
    after.share: 0.10        #   a tenth of the run (at least one cell)
    fill: "─┴─"
    end: "//▔"               # the corner,
    end.role: accent         #   in accent, at rest and on focus
  frame.block.left.fill: "┃"
  frame.block.right.fill: "│"
  frame.pane.top:            # construct's panes (Views' kind pane), the same look
    start: "▛▀"
    fill: "━"
    end: "┑"
  frame.pane.bottom:
    start: "▙"
    start.role: border
    after: "▀"
    after.share: 0.10
    fill: "─┴─"
    end: "//▔"
    end.role: accent
  frame.pane.left.fill: "┃"
  frame.pane.right.fill: "│"
  frame.gutter.x.fill: "┃"   # a split's gutters: side by side, stacked
  frame.gutter.y.fill: "━"
  run.progress.track:        # a bar's empty cells: a wire with a plug at its end
    fill: "─"
    end: "╼"
"""
"""The wire theme's text (see the module): an example of patterns, to copy and edit."""

# sigil's highlighting roles, dotted and verbatim (sigil's H1 role table, attempts/S1.md).
# Since sigil's H2 the checked-in `sigil highlight --json` fixture
# (tests/fixtures/sigil/construct.highlight.json) is the source: a proof checks that every
# role it carries is here and declared by light and contrast (this list may hold more,
# which is harmless; a role sigil adds, a dialect's kind included, joins it here).
SIGIL_ROLES: tuple[str, ...] = (
    "syntax.operator", "syntax.keyword", "syntax.modifier", "syntax.cardinality",
    "syntax.string", "syntax.ref", "syntax.number", "syntax.punct", "syntax.tag",
    "syntax.call", "syntax.call_name",
    "ui.mode", "ui.section", "ui.note_tag", "ui.note", "ui.payload",
    "kinds.service", "kinds.data", "kinds.event", "kinds.actor", "kinds.store",
    "kinds.state", "kinds.hole", "kinds.alias",
)
"""sigil's roles; light and contrast declare `"sigil." + role` for each, builtin none."""

NAMES: tuple[str, ...] = ("builtin", "light", "contrast", "wire")
"""The shelf's names, in the shelf's order."""

SHELF: Mapping = MappingProxyType(
    {"builtin": BUILTIN, "light": LIGHT, "contrast": CONTRAST, "wire": WIRE}
)
"""The shelf: name -> text, read-only, in `NAMES` order; `SHELF["builtin"] is BUILTIN`."""

