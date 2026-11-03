"""[Screen]: cursor, SGR, scroll regions, alt screen, modes, wide cells, tabs, charsets;
cure's own cells.

Kind: service (a mutable screen object implementing [Performer], the `apply` op on it,
the {Line} data class and the event values it gives out, and `reflow`); pure: no I/O.

A pane's program writes bytes; an output-direction [Parser] turns them into actions;
a `Screen` performs them (`[Screen] -> [Performer] : apply({Actions}) => {Grid}`) and
is read as a Buffer {Grid} of cure's own cells and styles, so a pane *is* cells: no
translation layer between a program and the compositor. The package op
`apply(screen, data)` ({Bytes} => {Grid}, for Embed's [Pty] and Testing's [Virtual])
is `apply(screen, screen.parser.feed(data))`, with this module's `apply`.

[Scrollback] keeps what scrolls off the top (`[Scrollback] -> [Screen] : keep({Lines})
=> {Ring}`): it builds on this module (it imports {Line} and `reflow`); this module
never imports it. The screen hands the rows it scrolls off out through `scrolled()`,
and the app gives them to `scrollback.keep`.

Invariant: contained — a program's bytes end as cells in its own screen and nowhere
  else. A Screen performs no I/O and holds no reference to a terminal, a file, a pty or
  a process; everything that leaves it is one of: (1) its own state, read by the
  methods and properties below (`grid()`, `cursor()`, `lines()`, `modes`, ...), whose
  cells are always well formed ([Cells]' `check`) and whose glyphs never hold a C0
  (U+0000..U+001F), DEL (U+007F) or C1 (U+0080..U+009F) code point, so no escape the
  program wrote survives into a cell; (2) `scrolled()`: {Line}s of its own primary
  screen, for its own scrollback; (3) `take()`: only `Reply`, `Title`, `Cwd`,
  `Clipboard` and `Bell` values (`EVENTS`). A `Reply` holds only bytes the screen built
  itself from its own state in answer to a query in the table below (DSR, CPR, DA1,
  DA2, DECID, DECRQM, XTWINOPS 18, kitty `CSI ? u`, OSC 4 / 10 / 11), meant for the
  program's OWN pty (the app writes it there), never for the real terminal; nothing
  else the program wrote is ever copied into a Reply. A title, a working directory, a
  clipboard write and a bell become event values the app may take or drop: the screen
  never acts on them. Every other sequence changes only the screen's state or is
  ignored. Nothing is forwarded to the real terminal, and a query is never passed on.

## The screen

`Screen(w, h, *, fg=FG, bg=BG)`: a fresh screen `w` columns by `h` rows (ints >= 1)
in its initial state (below). `fg`, `bg`: `(r, g, b)` tuples of ints 0..255, the
default colours the screen reports to OSC 10 / 11 queries (the app may pass the real
terminal's, learnt by its own queries); `FG = (229, 229, 229)`, `BG = (0, 0, 0)`.
`Screen` subclasses [Performer]: `print`, `execute`, `csi`, `esc`, `osc`, `hook`,
`put`, `unhook` perform an action (as the tables below); `ss3`, `legacy_mouse` and
`pasted` (input-direction actions) are ignored. Each returns `None`.

Initial state (also what RIS `ESC c` returns to, apart from what RIS keeps): both
buffers all `BLANK` with no row wrapped; the primary buffer active; cursor (0, 0),
visible, shape 0, no pending wrap; pen plain; region the whole screen; origin mode
off; auto-wrap on; insert off; newline (LNM) off; tab stops at every column 8, 16, ...
below `w`; G0 and G1 "ascii", G0 shifted in; `modes == Modes()`; both kitty stacks
empty; no saved cursor; title ""; title stack empty; not synced; nothing to take or
scrolled; REP has no last cluster.

State, read-only (properties unless shown with parentheses; all live, i.e. the state
after every action applied so far, sync blocks notwithstanding):

- `w`, `h`, `size == (w, h)`.
- `parser`: the output-direction `Parser` the screen holds for its byte stream (the
  package `apply` feeds it; it carries a sequence split across reads). An app at the
  stream's end may `apply(screen, screen.parser.flush())`.
- `alternate: bool`: the alternate buffer is active.
- `style -> Style | None`: the pen, the style printed cells take: `None` when every
  attribute is off and no link is set (the plain pen, so plain cells are `BLANK`'s
  style), else a Style `Style` (see "SGR").
- `region -> tuple[int, int]`: the scroll region `(top, bottom)`, 0-based rows, `top`
  inclusive, `bottom` exclusive; `(0, h)` is the whole screen.
- `origin`, `autowrap`, `insert`, `newline: bool`: DECOM, DECAWM, IRM, LNM.
- `tabs -> tuple[int, ...]`: the tab stop columns, ascending, each 0..w-1.
- `charsets -> tuple[str, str]`: G0 and G1, each one of `CHARSETS` ("ascii", "dec",
  "uk"); `shift -> int`: 0 (G0 in use, SI) or 1 (G1, SO).
- `modes -> Modes`: [Encode]'s `Modes`, kept from the program's own sequences (see
  "Modes"); input modes are never held back by a sync block.
- `title: str`: the last title set (OSC 0 / 2, or a pop); "" until then.
- `synced: bool`: inside a synchronized-output block (`CSI ? 2026 h` until `l`).
- `cursor(*, live=False) -> Cursor`: the cursor; inside a sync block, unless `live`,
  the cursor as it was when the block began.
- `grid(*, live=False) -> Grid`: a NEW Buffer `Grid` (`w` x `h`) of the active buffer's
  cells: row `y` of it equals the screen's row `y`, cell for cell. Inside a sync block,
  unless `live`, the cells as they were when the block began (the last complete
  frame, so a mux never shows a half-drawn one). Never the screen's own storage: a
  later action does not change a grid already returned, and writing into it does not
  change the screen.
- `lines() -> tuple[Line, ...]`: the active buffer's `h` rows as {Line}s, top to
  bottom, each as "A row as a Line" gives it (live).

Changing it (in place; each returns `None`):
- the [Performer] methods above, and this module's `apply`.
- `resize(w, h)`: see "Resize".

Taking what it gives out (each empties what it returns):
- `take() -> tuple[Event, ...]`: the replies and events since the last `take`, in the
  order they arose (see the invariant and "Events"). At most `MAX_TAKE` (4096) are
  held; past that the oldest is dropped.
- `scrolled() -> tuple[Line, ...]`: the rows scrolled off the top since the last call,
  oldest first, each as "A row as a Line" gives it, for [Scrollback]'s `keep`. Only
  rows scrolled off the top of a whole-screen region of the PRIMARY buffer (by LF, VT,
  FF, IND, NEL or auto-wrap at the bottom row, SU, and a resize's overflow, below) go
  here; rows scrolled out of a partial region, or of the alternate buffer, are
  dropped. At most `MAX_SCROLLED` (10000) are held; past that the oldest is dropped.

`apply(screen, actions) -> Grid` (the flow's op): performs each action of the iterable
in order (exactly `performer.dispatch(actions, screen)`), then returns `screen.grid()`.
`actions` may be any iterable of action values, e.g. a `Parser("output").feed(...)`
result.

## Data

- `Cursor(x, y, visible=True, shape=0, pending=False)`, frozen: column `x` 0..w-1,
  row `y` 0..h-1 (always inside the screen); `visible` DECTCEM; `shape` the last
  DECSCUSR value 0..6 (0 the terminal's default, 1 blinking block, 2 steady block,
  3 blinking underline, 4 steady underline, 5 blinking bar, 6 steady bar); `pending`
  the pending-wrap state: the cursor is at `w - 1` and the last print filled that
  column with auto-wrap on, so the next printed cluster wraps first.
- `Line(cells, wrapped=False)`, frozen, a {Line}: `cells` a tuple of {Cell} (any
  iterable is taken as a tuple), well formed ([Cells]' `check`), of any length;
  `wrapped`: the line continues in the next one (auto-wrap carried the cursor on, so
  the two are one logical line). `TypeError` when `wrapped` is not a `bool` or `cells`
  is not an iterable of `Cell`; `ValueError` from `check`.
- Events (`EVENTS = (Reply, Title, Cwd, Clipboard, Bell)`), frozen:
  - `Reply(data: bytes)`: bytes to write to the program's own pty;
  - `Title(text: str)`: the program set its title (OSC 0 / 2, or `CSI 23 t` popped one);
  - `Cwd(text: str)`: OSC 7, the program's working directory (usually a `file://` URI);
  - `Clipboard(targets: str, data: bytes)`: OSC 52, the program asks to set the
    clipboard: `targets` as it wrote them ("" when empty, the terminal's default),
    `data` the base64-decoded bytes (`b""` to clear);
  - `Bell()`: BEL.
  The text of `Title`, `Cwd` and `targets` is the field's bytes decoded as UTF-8 with
  `errors="replace"`, every C0, DEL and C1 character removed.
  `Event` is their union.

## A row as a Line

Each screen row carries a wrapped flag: set when auto-wrap carries the cursor from it
to the next row (a print with pending wrap, or a wide cluster that does not fit, see
"Printing"), cleared when the row is erased whole (ED 2, the rows ED 0 / 1 erase in
full, EL 2), when it is a new row a scroll, IL, DL or SD brings in, and by DECALN, RIS
and resize's rebuild. Wrapping because a wide cluster did not fit in the last column
also marks the row "padded": its last cell is a pad, not content.

A row as a Line: `Line(cells, wrapped)` with `wrapped` the row's flag and `cells` the
row's `w` cells, except: a padded wrapped row drops its last cell (the pad), and a row
that is not wrapped drops its trailing cells equal to `BLANK` (`Cell(" ", 1, None)`;
a styled blank is content and stays). In `resize`, the cursor's row keeps every cell
left of the cursor (trimming stops at the cursor column).

## Reflow

`reflow(lines, w) -> tuple[Line, ...]`: the lines joined into logical lines and wrapped
again at width `w` (an int >= 1). Consecutive lines join while a line is `wrapped`: a
logical line is the concatenation of the cells of a run of lines ending with one that
is not wrapped (or with the last line). Each logical line is cut into rows of at most
`w` columns, in order, never splitting a wide pair: a head that would fall in column
`w - 1` starts the next row instead (the row before it then holds `w - 1` cells); with
`w == 1` a wide pair becomes one `blank(style)` (its style). Every row but the last of
a logical line is `wrapped=True`; the last keeps the logical line's own flag (True only
when the input ended on a wrapped line). A logical line with no cells is one row with
no cells. So `reflow(reflow(ls, a), b) == reflow(ls, b)`, and with every line at most
`w` columns and wrapped only where it is full or padded, `reflow(ls, w) == ls`.
`TypeError` when `lines` is not an iterable of `Line` or `w` not an `int` (a `bool`
included); `ValueError` when `w < 1`.

## Printing

`Print(text)`: the text is mapped by the charset in use (G0, or G1 after SO), then cut
into grapheme clusters by Text's `cluster`, and each is printed in order. Charsets:
"ascii" changes nothing; "uk" maps "#" to "£"; "dec" (DEC special graphics) maps each
of "_`abcdefghijklmnopqrstuvwxyz{|}~" (0x5F..0x7E) through `DEC_GRAPHICS`, so `lqk`
draws "┌─┐". Only those ASCII code points are mapped.

A cluster's width is Text's `width` (so the screen agrees with Buffer), its cell
`cure.core.text.cell(cluster, pen)`: a control cluster (a C1 code point, say) is the
cell U+FFFD. With `n` its width and the cursor at (x, y):

1. Width 0 (a combining mark, ZWJ or variation selector arriving on its own): it joins
   the previous cell: the cell at `x` when pending wrap is set, or when auto-wrap is off
   and the last print wrote the last column with nothing having moved the cursor or
   written a cell since (the print that stayed at `w - 1`, rule 6, or that set pending
   wrap before `?7l` cleared it; a mark joining it, an SGR or a mode change neither
   moves nor writes; an erase writes), else at `x - 1`
   (when that is a tail, its head). The joined glyph replaces the cell's glyph only when
   Text's `width` of it equals the cell's width (else the mark is dropped); with
   `x == 0` and no pending wrap there is no previous cell and it is dropped. The cursor
   does not move. REP's last cluster becomes the joined glyph.
2. Pending wrap set (and auto-wrap on): the row is marked wrapped, the cursor goes to
   column 0 and down one row as LF does (scrolling at the region's bottom), and pending
   wrap clears.
3. `n == 2` and `x == w - 1`: with auto-wrap on, column `x` becomes the pad (the erase
   cell, see "SGR"), the row is marked wrapped and padded, and the cursor moves as in
   2; then the cluster prints at column 0. With auto-wrap off, the cluster is dropped.
   With `w == 1`, a wide cluster prints as `blank(pen)`, as a narrow cell.
4. Insert mode: the cells from `x` to the right edge move right by `n`; those pushed
   past the edge are lost (a pair cut there leaves `blank(its style)`).
5. The cell(s) are written at `x` (a wide cluster as its head and tail) by Buffer's
   rules: half of an old wide pair overwritten leaves its other half `blank(its
   style)` (no_orphan_half).
6. The cursor advances `n` columns; reaching `w` it stays at `w - 1`, with pending wrap
   set when auto-wrap is on (off: the next cluster overwrites the last column).

The cluster printed last (after mapping) is REP's last cluster. Clusters split across
two `Print`s (the parser coalesces within a feed, so only across reads) are printed as
two clusters, the second by rule 1 when it is zero-width.

## SGR (`CSI ... m`, no private marker, no intermediates)

The pen holds: fg, bg, bold, dim, italic, underline style, underline colour, strike,
reverse, and the OSC 8 link. `style` builds a Style from it: `underline_colour` only
while an underline is on (the pen keeps a 58 colour set before 4, Style would refuse
it). Colours from a program carry no theme role (`role == ""`). `CSI m` (no params)
is `CSI 0 m`; an empty parameter is 0. Codes, in order, each by its first sub-
parameter unless stated:

| code | effect |
| --- | --- |
| 0 | everything off, fg and bg `None` (the link is kept: OSC 8 is not SGR) |
| 1 / 2 / 3 | bold / dim / italic on |
| 4 | underline "single"; `4:0` off, `4:1` "single", `4:2` "double", `4:3` "curly", `4:4` "dotted", `4:5` "dashed", any other `4:n` "single" |
| 7 / 9 | reverse / strike on |
| 21 | underline "double" |
| 22 | bold and dim off |
| 23 / 24 / 27 / 29 | italic / underline / reverse / strike off |
| 30..37, 90..97 | fg `Colour("name", NAMES[n - 30])`, `NAMES[n - 90 + 8]` |
| 39 | fg `None` |
| 40..47, 100..107 | bg, the same names |
| 49 | bg `None` |
| 38 / 48 / 58 | fg / bg / underline colour, extended (below) |
| 59 | underline colour `None` |
| 5, 6, 8, 25, 28, 53, 55, others | ignored (no Style field: blink, conceal, overline) |

Extended colours, `;` form (the code takes the parameters after it): `38;5;n` →
`Colour("index", n)`; `38;2;r;g;b` → `Colour("rgb", (r, g, b))`. `:` form (all in one
parameter): `38:5:n`; `38:2:r:g:b`; `38:2:cs:r:g:b` (with a colour-space id, ignored,
possibly empty: `38:2::r:g:b`). A malformed one (a missing or empty value, a value over
255, a kind other than 2 or 5) is ignored together with every parameter it took; the
codes after it still apply. An unknown code never stops the rest.

Erasing (ED, EL, ECH, ICH, DCH, IL, DL, SU, SD, the pad) writes the erase cell:
`blank(Style(bg=pen.bg))` when the pen has a background, else `BLANK` (background
colour erase, as xterm).

## The sequences

Counts: a parameter "n" defaults to 1 and 0 means 1; larger counts are clamped to what
the screen can do. Positions are 1-based on the wire. Every cursor movement clears
pending wrap. Origin mode makes rows relative to the region's top and keeps the cursor
inside the region. "Inside the region": `top <= y < bottom`. Any sequence with a
private marker or intermediates not listed here, or a final not listed, is ignored.

C0 (`Execute(code)`):

| code | effect |
| --- | --- |
| 0x07 BEL | `Bell()` to take |
| 0x08 BS | `x - 1`, not past 0 (with pending wrap: from `w - 1` to `w - 2`) |
| 0x09 HT | to the next tab stop right of `x`, else `w - 1` |
| 0x0A LF, 0x0B VT, 0x0C FF | index (as IND); with LNM also CR |
| 0x0D CR | column 0 |
| 0x0E SO / 0x0F SI | use G1 / G0 |
| others, 0x7F | ignored (no answerback to ENQ) |

ESC (`Esc(final, intermediates)`):

| sequence | effect |
| --- | --- |
| `ESC D` IND | down one row; at the region's bottom row, scroll the region up one (to `scrolled()` when the region is the whole screen on the primary buffer); below the region, down unless at row `h - 1` |
| `ESC E` NEL | CR then IND |
| `ESC H` HTS | a tab stop at `x` |
| `ESC M` RI | up one row; at the region's top row, scroll the region down one; above the region, up unless at row 0 |
| `ESC 7` DECSC | save the cursor (below) |
| `ESC 8` DECRC | restore it |
| `ESC c` RIS | the initial state, keeping the size, the parser, `title`, and what is waiting in `take()` and `scrolled()`; a sync block ends |
| `ESC # 8` DECALN | every cell of the active buffer `Cell("E", 1, None)`, rows unwrapped, region the whole screen, origin off, cursor (0, 0) |
| `ESC ( C` / `ESC ) C` | G0 / G1: "B" ascii, "0" dec, "A" uk; any other `C` ascii |
| `ESC =` / `ESC >` | DECKPAM / DECKPNM: `modes.keypad` True / False |
| `ESC Z` DECID | as DA1 |
| others (`ESC \\`, `ESC N`, `ESC O`, `ESC * C`, `ESC % G`, ...) | ignored |

Save and restore (DECSC / DECRC, `CSI s` / `CSI u`, `?1048`, `?1049`): one slot per
buffer. Saved: the position, pending wrap, the pen (link included), G0, G1, the shift
and origin mode. Restoring clamps the position into the screen; with nothing saved in
the active buffer's slot it gives (0, 0), no pending wrap, the plain pen, "ascii" for
both, G0, origin off.

CSI (`Csi(final, params, private, intermediates)`; "?" the private marker):

| sequence | effect |
| --- | --- |
| `A` CUU n | up n, not above the region's top when inside the region, else row 0 |
| `B` CUD n, `e` VPR n | down n, not below the region's bottom row when inside it, else row `h - 1` |
| `C` CUF n, `a` HPR n | right n, not past `w - 1` |
| `D` CUB n | left n, not past 0 |
| `E` CNL n / `F` CPL n | as CUD / CUU, then column 0 |
| `G` CHA n, `` ` `` HPA n | column n - 1, clamped |
| `H` CUP r;c, `f` HVP | row r - 1, column c - 1 (defaults 1;1), clamped; origin-relative |
| `d` VPA n | row n - 1, clamped; origin-relative |
| `I` CHT n / `Z` CBT n | forward / back n tab stops (to `w - 1` / 0 when there are no more) |
| `J` ED p, `?J` | 0 cursor to end, 1 start to cursor (inclusive), 2 all; the cursor stays; 3 and others ignored (the scrollback is the app's) |
| `K` EL p, `?K` | 0 cursor to end of row, 1 start of row to cursor (inclusive), 2 the row |
| `X` ECH n | n cells from the cursor, not past the edge; the cursor stays |
| `@` ICH n | n erase cells at the cursor, the rest shifted right, lost past the edge |
| `P` DCH n | n cells deleted at the cursor, the rest shifted left, erase cells at the edge |
| `L` IL n / `M` DL n | when inside the region: n rows inserted / deleted at the cursor's row within the region (rows pushed past its bottom lost; erase rows brought in); column 0. Outside: ignored |
| `S` SU n / `T` SD n | scroll the region up / down n rows (n at most its height); SU to `scrolled()` as IND; `T` with more than one parameter ignored |
| `b` REP n | the last cluster printed, printed again n times (n at most `w * h`), only when the action just before this one was a `Print`; else ignored |
| `g` TBC p | 0 clear the stop at `x`, 3 clear all; others ignored |
| `m` SGR | see "SGR" |
| `r` DECSTBM t;b | the region `(t - 1, b)` (defaults 1 and h, b clamped to h), when t < b (two rows or more); then the cursor to the home position (the region's top in origin mode, else (0, 0)); otherwise ignored |
| `s` | SCOSC: save the cursor (as DECSC) when it has no parameters |
| `u` | SCORC: restore it, when it has no parameters and no private marker |
| `h` / `l` SM / RM | 4 insert (IRM), 20 newline (LNM); others ignored |
| `?h` / `?l` DECSET / DECRST | each parameter in order, see "Modes" |
| `n` DSR | 5: `Reply(CSI 0 n)`; 6: CPR `Reply(CSI r ; c R)`, the cursor's row (origin-relative) and column, 1-based |
| `?n` | 6: DECXCPR `Reply(CSI ? r ; c ; 1 R)` |
| `c` DA1 (parameter 0 or none) | `Reply(CSI ? 62 ; 22 c)` |
| `>c` DA2 (parameter 0 or none) | `Reply(CSI > 1 ; 10 ; 0 c)` |
| `?` p `$p` DECRQM | `Reply(CSI ? p ; s $ y)`: s 1 set, 2 reset, for the modes "Modes" tracks (1, 6, 7, 9, 25, 47, 1000, 1002, 1003, 1004, 1006, 1047, 1049, 2004, 2026), else 0 |
| p `$p` (ANSI DECRQM) | `Reply(CSI p ; s $ y)` for 4 and 20, else s 0 |
| `t` XTWINOPS | 18: `Reply(CSI 8 ; h ; w t)`; 22 (with 0, 2 or none after it): push `title` (at most `TITLE_DEPTH`, 10: the oldest is dropped); 23 (likewise): pop it into `title` and give `Title(title)` (empty stack: nothing); everything else ignored (no window op is ever done) |
| `>` f `u` | kitty: push flags f (default 0) |
| `<` n `u` | kitty: pop n (default 1) |
| `=` f;m `u` | kitty: set flags f by mode m (default 1) |
| `?u` | kitty: `Reply(CSI ? f u)`, f the flags in force |
| ` q` DECSCUSR (intermediate " ") | cursor shape p 0..6 (default 0); others ignored |
| `!p` DECSTR (intermediate "!") | soft reset: insert off, origin off, auto-wrap on, cursor visible, region the whole screen, G0 and G1 "ascii", G0, pen plain, the active buffer's saved slot as if nothing were saved |

Replies use 7-bit CSI (`ESC [`), written exactly as above with no spaces: CPR at
(row 3, column 5) is `b"\\x1b[3;5R"`.

OSC (`Osc(data, bel)`; the number before the first ";"):

| OSC | effect |
| --- | --- |
| 0, 2 | `title` = the rest (as for events), `Title(title)` to take |
| 1 | ignored (the icon name) |
| 7 | `Cwd(text)` |
| 8 `params;uri` | the pen's link: the uri decoded as UTF-8 (replace); `None` when it is empty or holds a C0, DEL or C1 character; params (`id=`) ignored; no second ";" ignored |
| 52 `targets;data` | data "?" (a read): ignored, never answered; else `Clipboard(targets, base64-decoded data)`, ignored when the base64 is invalid (`base64.b64decode(..., validate=True)` raises) |
| 4 `c;?` | for each `c;?` pair (c 0..255): `Reply(OSC 4 ; c ; rgb:rrrr/gggg/bbbb ST)` from Style's `palette_rgb(c)`; pairs that set a colour are ignored |
| 10 `?` / 11 `?` | `Reply(OSC 10 ; rgb:... ST)` / `OSC 11` from `fg` / `bg`; setting is ignored |
| others (104, 110, 112, 133, 1337, 9, 777, ...) | ignored |

Colour replies give each channel `v` as four lower-case hex digits of `v * 257`
(`(229, 229, 229)` → `rgb:e5e5/e5e5/e5e5`), and end with the query's own terminator:
BEL (`\\x07`) when `bel`, else ST (`\\x1b\\\\`).

DCS (`Hook`, `Put`, `Unhook`): all ignored (no DECRQSS, no XTGETTCAP, no sixel).

Nothing else is done, and no action sequence ever raises: an action whose fields hold
any values of the types [Performer] gives them (a `Csi` with any params, say) is
performed or ignored.

## Modes

DECSET / DECRST (`CSI ? p h` / `l`), each parameter in order:

| p | effect |
| --- | --- |
| 1 | `modes.cursor_keys` (DECCKM) |
| 6 | origin mode (DECOM); the cursor to the home position |
| 7 | auto-wrap (DECAWM); off clears pending wrap |
| 9, 1000, 1002, 1003 | set: `modes.mouse = p`; reset: `modes.mouse = 0` when p is the mode in force, else nothing |
| 25 | cursor visible (DECTCEM) |
| 47 | set: the alternate buffer active (not cleared); reset: the primary |
| 1047 | set: as 47; reset: the alternate buffer cleared (erase cells), then the primary |
| 1048 | set: save the cursor; reset: restore it (the active buffer's slot) |
| 1049 | set: save the cursor in the primary slot, the alternate buffer active, cleared (all `BLANK`, rows unwrapped); reset: the primary active, its cursor restored |
| 1004 | `modes.focus` |
| 1006 | `modes.mouse_sgr` |
| 2004 | `modes.paste` |
| 2026 | synchronized output (below) |
| others (3, 5, 12, 1005, 1015, 69, ...) | ignored |

Setting 47, 1047 or 1049 while the alternate buffer is active, or resetting one of them
while the primary is, does nothing. The cursor (position, pen) carries over a switch;
the region and tab stops are shared. Each buffer has its own saved slot and its own
kitty stack.

Kitty keyboard: each buffer keeps a stack of flags (at most `KITTY_DEPTH`, 16, entries:
a push onto a full stack drops the bottom one). `modes.kitty` is the top of the active
buffer's stack, 0 when it is empty. Push `CSI > f u` pushes `f & 31`; pop `CSI < n u`
removes n entries (all of them when n is more); set `CSI = f ; m u` replaces the top
(pushing one onto an empty stack) with `f & 31` for m 1, `top | f` for 2,
`top & ~f` for 3 (other m ignored).

Synchronized output (2026): set, when not already synced, takes the frame (the active
buffer's cells and the cursor) and makes `synced` True; while synced, `grid()`,
`cursor()` and `apply`'s result give that frame, and every action is still performed
on the live screen. Reset, RIS and `resize` end the block (`synced` False): the live
state shows again. A screen has no clock: an app that wants a timeout reads
`grid(live=True)` itself. Queries are answered from the live state.

## Resize

`resize(w, h)` (ints >= 1): the new size, in place.

- The primary buffer is reflowed: its rows taken as Lines ("A row as a Line", the
  cursor's row keeping the cells left of the cursor when the primary is active), then
  `reflow(..., w)`. The anchor is the cursor's logical position when the primary is
  active (its logical line and its offset in that line's cells, counting from the
  line's first cell; pending wrap is dropped first, the offset being the cursor's
  column), else the last row holding a cell (row 0 when none). If the anchor's new row
  is `h` or more, the rows above the first of the last `h` rows ending at the anchor
  go to `scrolled()` (oldest first); the next `h` rows become the buffer, padded at
  the bottom with empty rows (`BLANK`, unwrapped); rows past them are dropped. Lines
  are never pulled back from the scrollback. When the primary is active the cursor
  goes to its offset's new place: the row and column where the cell at that offset
  landed, or, past the line's last cell, the column right after it (column 0 of a new
  row when that would be `w`, the logical line gaining that row).
- The alternate buffer is not reflowed: it is cut or padded at the bottom and right
  (a pair cut by the new right edge leaves `blank(its style)`), wrapped flags kept.
  When it is active the cursor is clamped into the screen.
- Pending wrap clears; the region becomes the whole screen; saved cursors are clamped;
  tab stops left of the old width are kept (those at w or more are lost), and every
  column 8, 16, ... from the old width on gets a stop; a sync block ends.

`TypeError` when `w` / `h` is not an `int` (a `bool` included); `ValueError` when one
is < 1; on an error nothing changes.

Inputs: `Screen`: `w`, `h` ints, `fg`, `bg` rgb tuples. `apply`: a `Screen` and an
  iterable of [Performer]'s actions ({Actions}). `reflow`: an iterable of {Line} and an
  int width.
Outputs: `apply`: {Grid}. `grid`: {Grid}; `cursor`: `Cursor`; `lines`, `scrolled`,
  `reflow`: tuples of {Line}; `take`: a tuple of events.
Errors: `Screen(...)`: `TypeError` when `w` / `h` is not an `int` (a `bool` included)
  or `fg` / `bg` is not a tuple of three ints; `ValueError` when `w` or `h` is < 1 or a
  component is outside 0..255. `apply`: `TypeError` when `screen` is not a `Screen`,
  and as `dispatch` (an item that is not an action value, before any is performed).
  `grid` / `cursor`: `TypeError` when `live` is not a `bool`. `resize`, `reflow`,
  `Line`: as stated. Nothing else raises.
Effects: none beyond the screen's own state (and a `Screen`'s parser's); no I/O.

Usage:
    from cure.interact.vt import Csi, Esc, Osc, Print
    from cure.core.buffer.cells import line
    from cure.interact.vt.screen import Screen, Line, Reply, Title, apply, reflow
    from cure.core.style import Colour, Style
    s = Screen(10, 3)
    g = apply(s, (Csi("m", ((1,), (31,))), Print("hi"), Csi("m", ((0,),))))
    g.get(0, 0)          # Cell("h", 1, Style(fg=Colour("name", "red"), bold=True))
    g.get(2, 0)          # Cell(" ", 1, None)
    s.cursor()           # Cursor(2, 0, True, 0, False)
    apply(s, (Csi("n", ((6,),)), Osc(b"2;build", True)))
    s.take()             # (Reply(b"\\x1b[1;3R"), Title("build"))
    s.take()             # ()
    apply(s, (Print("abcdefghijkl"),))   # wraps: row 0 "hiabcdefgh" wrapped, row 1 "ijkl"
    s.lines()[0]         # Line(<10 cells>, wrapped=True)
    apply(s, (Csi("h", ((2026,),), "?"), Print("x")))
    s.synced             # True; s.grid() is the frame before "x", s.grid(live=True) has it
    apply(s, (Esc("0", "("), Print("lqk")))   # DEC graphics: "┌─┐"
    reflow([Line(line("abcdef"))], 4)
    # (Line(<"abcd">, wrapped=True), Line(<"ef">, wrapped=False))
"""

import base64
import binascii
from bisect import bisect_left, bisect_right, insort
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

from cure.core.buffer import BLANK, Grid, blank, check, fill, tail, write
from cure.core.style import NAMES, Colour, Style, palette_rgb
from cure.core.text import Cell, cell, cluster, width

from .encode import Modes
from .parser import Parser
from .performer import (
    Action, Csi, Esc, Execute, Hook, LegacyMouse, Osc, Pasted, Performer, Print, Put, Ss3,
    Unhook, dispatch,
)

FG: "tuple[int, int, int]" = (229, 229, 229)
"""The default foreground a screen reports to OSC 10 (xterm's colour 7)."""

BG: "tuple[int, int, int]" = (0, 0, 0)
"""The default background a screen reports to OSC 11."""

MAX_TAKE = 4096
"""At most this many replies and events wait for `take()`; past it the oldest is dropped."""

MAX_SCROLLED = 10_000
"""At most this many lines wait for `scrolled()`; past it the oldest is dropped."""

KITTY_DEPTH = 16
"""The depth of each buffer's kitty keyboard flags stack."""

TITLE_DEPTH = 10
"""The depth of the title stack (`CSI 22 t` / `CSI 23 t`)."""

CHARSETS: "tuple[str, ...]" = ("ascii", "dec", "uk")
"""The charsets G0 and G1 may hold."""

DEC_GRAPHICS: "dict[str, str]" = {
    "_": " ", "`": "◆", "a": "▒", "b": "␉", "c": "␌", "d": "␍", "e": "␊", "f": "°",
    "g": "±", "h": "␤", "i": "␋", "j": "┘", "k": "┐", "l": "┌", "m": "└", "n": "┼",
    "o": "⎺", "p": "⎻", "q": "─", "r": "⎼", "s": "⎽", "t": "├", "u": "┤", "v": "┴",
    "w": "┬", "x": "│", "y": "≤", "z": "≥", "{": "π", "|": "≠", "}": "£", "~": "·",
}
"""DEC special graphics (`ESC ( 0`): the ASCII code points 0x5F..0x7E it maps, to Unicode."""


@dataclass(frozen=True)
class Cursor:
    """The cursor: position, visibility, DECSCUSR shape, pending wrap (see the module)."""

    x: int
    y: int
    visible: bool = True
    shape: int = 0
    pending: bool = False


@dataclass(frozen=True)
class Line:
    """{Line}: a row's cells and whether it wrapped into the next (see the module)."""

    cells: "tuple[Cell, ...]"
    wrapped: bool = False

    def __post_init__(self) -> None:
        if type(self.wrapped) is not bool:
            raise TypeError(f"Line.wrapped must be a bool, got {type(self.wrapped).__name__}")
        if isinstance(self.cells, (str, bytes)) or not isinstance(self.cells, Iterable):
            raise TypeError(f"Line.cells must be an iterable of Cell, got {type(self.cells).__name__}")
        object.__setattr__(self, "cells", check(self.cells))


@dataclass(frozen=True)
class Reply:
    """Bytes for the program's own pty, answering one of its queries."""

    data: bytes


@dataclass(frozen=True)
class Title:
    """The program set its title (OSC 0 / 2, or a title popped)."""

    text: str


@dataclass(frozen=True)
class Cwd:
    """OSC 7: the program's working directory."""

    text: str


@dataclass(frozen=True)
class Clipboard:
    """OSC 52: the program asks to set the clipboard (`targets`, decoded `data`)."""

    targets: str
    data: bytes


@dataclass(frozen=True)
class Bell:
    """BEL."""


Event = Reply | Title | Cwd | Clipboard | Bell

EVENTS = (Reply, Title, Cwd, Clipboard, Bell)

# The pen: a tuple of these fields (Style's, the underline colour kept apart from the underline).
_FG, _BG, _BOLD, _DIM, _ITALIC, _UL, _ULC, _STRIKE, _REVERSE, _LINK = range(10)
_PLAIN = (None, None, False, False, False, None, None, False, False, None)

_UNDERLINES = {0: None, 1: "single", 2: "double", 3: "curly", 4: "dotted", 5: "dashed"}
_NAMED = tuple(Colour("name", n) for n in NAMES)

_ALIGN = Cell("E", 1, None)
_CONTROLS = {c: None for c in (*range(0x20), *range(0x7F, 0xA0))}
_TRACKED = (1, 6, 7, 9, 25, 47, 1000, 1002, 1003, 1004, 1006, 1047, 1049, 2004, 2026)
_MOUSE = (9, 1000, 1002, 1003)

_MAPS = {"ascii": None, "uk": str.maketrans({"#": "£"}), "dec": str.maketrans(DEC_GRAPHICS)}
_DESIGNATE = {"B": "ascii", "0": "dec", "A": "uk"}


def _kind(char: str) -> int:
    """How one code point prints on its own: 1 or 2 when it is always a cluster of that width by
    itself (whatever is around it, unless an extender follows it), 0 when it needs Text's `cluster`."""
    if cell(char).glyph != char:  # a control: U+FFFD
        return 0
    n = width(char)
    if n not in (1, 2):
        return 0
    if len(cluster("a" + char)) != 2 or len(cluster(char + char)) != 2 or len(cluster(char + "a")) != 2:
        return 0
    return n


_ASCII_KINDS = {chr(c): 1 for c in range(0x20, 0x7F)}


class _Buffer:
    """One buffer's rows and what goes with them: wrapped and padded flags, the saved slot, the
    kitty stack, and the last Grid built from it (rebuilt only where a row changed)."""

    __slots__ = ("rows", "wrapped", "padded", "saved", "kitty", "cache", "snap")

    def __init__(self, w: int, h: int) -> None:
        self.rows = [[BLANK] * w for _ in range(h)]
        self.wrapped = [False] * h
        self.padded = [False] * h
        self.saved = None
        self.kitty: "list[int]" = []
        self.cache = None
        self.snap: list = []

    def clear(self, w: int, new: Cell) -> None:
        self.rows = [[new] * w for _ in self.rows]
        self.wrapped = [False] * len(self.rows)
        self.padded = [False] * len(self.rows)

    def grid(self, w: int, h: int) -> Grid:
        """A new Grid of the rows: the cached one brought up to date, copied."""
        if self.cache is None or self.cache.size != (w, h):
            self.cache = Grid(w, h)
            self.snap = [None] * h
        for y, row in enumerate(self.rows):
            if self.snap[y] != row:
                n = _content(row)
                if n < w:  # the blank rest through `fill`, which need not check each cell
                    fill(self.cache, (n, y, w - n, 1))
                if n:
                    write(self.cache, 0, y, row[:n])
                self.snap[y] = list(row)
        return self.cache.copy()


class Screen(Performer):
    """A program's screen: two buffers, a cursor, a pen, modes (see the module)."""

    def __init__(self, w: int, h: int, *, fg: "tuple[int, int, int]" = FG,
                 bg: "tuple[int, int, int]" = BG) -> None:
        _size(w, h)
        self._fg_rgb = _rgb(fg, "fg")
        self._bg_rgb = _rgb(bg, "bg")
        self._w, self._h = w, h
        self._parser = Parser("output")
        self._title = ""
        self._events: deque = deque(maxlen=MAX_TAKE)
        self._scrolled: deque = deque(maxlen=MAX_SCROLLED)
        self._pens: dict = {}
        self._kinds = dict(_ASCII_KINDS)
        self._reset()

    def _reset(self) -> None:
        """The initial state (RIS), keeping the size, parser, title, events and scrolled rows."""
        w, h = self._w, self._h
        self._bufs = (_Buffer(w, h), _Buffer(w, h))
        self._alt = False
        self._buf = self._bufs[0]
        self._x = self._y = 0
        self._pending = False
        self._edge = False
        self._visible = True
        self._shape = 0
        self._set_pen(_PLAIN)
        self._top, self._bottom = 0, h
        self._origin = False
        self._autowrap = True
        self._insert = False
        self._newline = False
        self._tabs = list(range(8, w, 8))
        self._g = ["ascii", "ascii"]
        self._shift = 0
        self._cursor_keys = self._keypad = self._mouse_sgr = self._paste = self._focus = False
        self._mouse = 0
        self._titles: "list[str]" = []
        self._frame = None
        self._last: "str | None" = None
        self._after_print = False
        self._was_print = False

    # -- state

    @property
    def w(self) -> int:
        """Columns."""
        return self._w

    @property
    def h(self) -> int:
        """Rows."""
        return self._h

    @property
    def size(self) -> "tuple[int, int]":
        """`(w, h)`."""
        return (self._w, self._h)

    @property
    def parser(self) -> Parser:
        """The output-direction Parser this screen's byte stream goes through."""
        return self._parser

    @property
    def alternate(self) -> bool:
        """The alternate buffer is active."""
        return self._alt

    @property
    def style(self) -> "object":
        """The pen as a Style, or None when plain."""
        return self._style

    @property
    def region(self) -> "tuple[int, int]":
        """The scroll region `(top, bottom)`, bottom exclusive."""
        return (self._top, self._bottom)

    @property
    def origin(self) -> bool:
        """DECOM."""
        return self._origin

    @property
    def autowrap(self) -> bool:
        """DECAWM."""
        return self._autowrap

    @property
    def insert(self) -> bool:
        """IRM."""
        return self._insert

    @property
    def newline(self) -> bool:
        """LNM."""
        return self._newline

    @property
    def tabs(self) -> "tuple[int, ...]":
        """The tab stop columns, ascending."""
        return tuple(self._tabs)

    @property
    def charsets(self) -> "tuple[str, str]":
        """G0 and G1."""
        return (self._g[0], self._g[1])

    @property
    def shift(self) -> int:
        """0 when G0 is in use, 1 for G1."""
        return self._shift

    @property
    def modes(self) -> Modes:
        """The input modes the program set, as Encode reads them."""
        kitty = self._buf.kitty
        return Modes(cursor_keys=self._cursor_keys, keypad=self._keypad, kitty=kitty[-1] if kitty else 0,
                     mouse=self._mouse, mouse_sgr=self._mouse_sgr, paste=self._paste, focus=self._focus)

    @property
    def title(self) -> str:
        """The last title set."""
        return self._title

    @property
    def synced(self) -> bool:
        """Inside a synchronized-output block."""
        return self._frame is not None

    def cursor(self, *, live: bool = False) -> Cursor:
        """The cursor (the sync block's frame unless `live`)."""
        _bool(live, "live")
        if self._frame is not None and not live:
            return self._frame[1]
        return Cursor(self._x, self._y, self._visible, self._shape, self._pending)

    def grid(self, *, live: bool = False) -> Grid:
        """A new Grid of the active buffer (the sync block's frame unless `live`)."""
        _bool(live, "live")
        if self._frame is not None and not live:
            return self._frame[0].copy()
        return self._buf.grid(self._w, self._h)

    def lines(self) -> "tuple[Line, ...]":
        """The active buffer's rows as Lines (live)."""
        b = self._buf
        return tuple(_row_line(r, wr, pd) for r, wr, pd in zip(b.rows, b.wrapped, b.padded))

    # -- what leaves it

    def take(self) -> "tuple[Event, ...]":
        """The replies and events since the last take, in order; emptied."""
        out = tuple(self._events)
        self._events.clear()
        return out

    def scrolled(self) -> "tuple[Line, ...]":
        """The primary rows scrolled off the top since the last call; emptied."""
        out = tuple(r if isinstance(r, Line) else _row_line(*r) for r in self._scrolled)
        self._scrolled.clear()
        return out

    # -- changing it

    def resize(self, w: int, h: int) -> None:
        """The new size: the primary reflowed, the alternate cut or padded."""
        _size(w, h)
        old_w = self._w
        self._frame = None
        self._pending = self._edge = False
        cursor = self._resize_primary(w, h)
        self._resize_alternate(w, h)
        self._w, self._h = w, h
        if cursor is not None:
            self._x, self._y = cursor
        else:
            self._x, self._y = min(self._x, w - 1), min(self._y, h - 1)
        self._top, self._bottom = 0, h
        for b in self._bufs:
            b.cache = None
            if b.saved is not None:
                x, y, pending, *rest = b.saved
                b.saved = (min(x, w - 1), min(y, h - 1), pending, *rest)
        self._tabs = [t for t in self._tabs if t < min(w, old_w)]
        self._tabs += [t for t in range(8, w, 8) if t >= old_w]
        self._tabs.sort()

    def _resize_primary(self, w: int, h: int) -> "tuple[int, int] | None":
        """Reflow the primary buffer to `w` x `h`; the cursor's new place when it is active."""
        b = self._bufs[0]
        active = not self._alt
        lines = [_row_line(r, wr, pd, self._x if active and y == self._y else 0)
                 for y, (r, wr, pd) in enumerate(zip(b.rows, b.wrapped, b.padded))]
        anchor = None
        if active:
            first = self._y
            while first > 0 and lines[first - 1].wrapped:
                first -= 1
            anchor = (first, sum(len(ln.cells) for ln in lines[first:self._y]) + self._x)
        rows, at = _reflow(lines, w, anchor)
        if at is not None:
            row = at[0]
        else:
            row = max((i for i, r in enumerate(rows) if r.cells), default=0)
        start = max(0, row - h + 1)
        self._scrolled.extend(rows[:start])
        kept = rows[start:start + h]
        b.rows, b.wrapped, b.padded = [], [], []
        for i, ln in enumerate(kept):
            cells = list(ln.cells)
            nxt = kept[i + 1].cells if i + 1 < len(kept) else ()
            b.padded.append(ln.wrapped and len(cells) == w - 1 and bool(nxt) and nxt[0].width == 2)
            b.rows.append(cells + [BLANK] * (w - len(cells)))
            b.wrapped.append(ln.wrapped)
        for _ in range(h - len(kept)):
            b.rows.append([BLANK] * w)
            b.wrapped.append(False)
            b.padded.append(False)
        if at is None:
            return None
        return (at[1], at[0] - start)

    def _resize_alternate(self, w: int, h: int) -> None:
        """Cut or pad the alternate buffer at the bottom and right; its flags kept."""
        b = self._bufs[1]
        old_w = self._w
        rows = []
        for r in b.rows[:h]:
            if w < old_w:
                r = r[:w]
                if r[-1].width == 2:
                    r[-1] = blank(r[-1].style)
            else:
                r = r + [BLANK] * (w - old_w)
            rows.append(r)
        wrapped = b.wrapped[:h]
        padded = b.padded[:h] if w == old_w else [False] * len(rows)
        for _ in range(h - len(rows)):
            rows.append([BLANK] * w)
            wrapped.append(False)
            padded.append(False)
        b.rows, b.wrapped, b.padded = rows, wrapped, padded

    # -- the Performer methods

    def print(self, action: Print) -> None:
        self._after_print = False
        text = action.text
        table = _MAPS[self._g[self._shift]]
        mapped = text.translate(table) if table is not None else text
        if text.isascii() and text.isprintable() and table is None:
            self._narrow(mapped)
        else:
            self._text(mapped)
        self._was_print = True

    def execute(self, action: Execute) -> None:
        self._was_print = False
        handler = _C0.get(action.code)
        if handler is not None:
            handler(self)

    def csi(self, action: Csi) -> None:
        self._after_print, self._was_print = self._was_print, False
        handler = _CSI.get((action.private, action.intermediates, action.final))
        if handler is not None:
            handler(self, action)

    def esc(self, action: Esc) -> None:
        self._was_print = False
        handler = _ESC.get((action.intermediates, action.final))
        if handler is None and action.intermediates in ("(", ")") and len(action.final) == 1:
            handler = Screen._designate
        if handler is not None:
            handler(self, action)

    def osc(self, action: Osc) -> None:
        self._was_print = False
        data = action.data
        if not isinstance(data, (bytes, bytearray)):
            return
        number, sep, rest = bytes(data).partition(b";")
        handler = _OSC.get(number)
        if handler is not None:
            handler(self, rest if sep else None, action.bel)

    def hook(self, action: Hook) -> None:
        self._was_print = False

    def put(self, action: Put) -> None:
        self._was_print = False

    def unhook(self, action: Unhook) -> None:
        self._was_print = False

    def ss3(self, action: Ss3) -> None:
        return None

    def legacy_mouse(self, action: LegacyMouse) -> None:
        return None

    def pasted(self, action: Pasted) -> None:
        return None

    # -- the pen

    def _set_pen(self, pen: tuple) -> None:
        """Make `pen` the pen: its Style, its erase cell and its cache of printed cells."""
        got = self._pens.get(pen)
        if got is None:
            if len(self._pens) > 512:
                self._pens.clear()
            got = self._pens[pen] = _pen_state(pen)
        self._pen = pen
        self._style, self._erase, self._cells = got

    # -- printing

    def _cell(self, c: str) -> Cell:
        """The cell cluster `c` prints as in the pen (cached per pen)."""
        got = self._cells.get(c)
        if got is None:
            got = self._cells[c] = cell(c, self._style)
        return got

    def _text(self, text: str) -> None:
        """Print text of any code points: by runs of narrow code points where every one is its
        own cluster, else cluster by cluster."""
        kinds = self._kinds
        run: "list[str]" = []
        for ch in text:
            k = kinds.get(ch)
            if k is None:
                if len(kinds) > 65536:
                    kinds.clear()
                    kinds.update(_ASCII_KINDS)
                k = kinds[ch] = _kind(ch)
            if k == 0:
                break
            run.append(k)
        else:
            if all(k == 1 for k in run):
                self._narrow(text)
                return
            for ch, k in zip(text, run):
                self._cluster(ch, self._cell(ch))
            return
        for c in cluster(text):
            self._cluster(c, self._cell(c))

    def _narrow(self, text: str) -> None:
        """Print text whose every code point is a cluster of width 1, in runs per row."""
        cache = self._cells
        try:
            cells = list(map(cache.__getitem__, text))
        except KeyError:
            for c in set(text).difference(cache):
                cache[c] = Cell(c, 1, self._style)
            cells = list(map(cache.__getitem__, text))
        self._last = text[-1]
        w = self._w
        i, m = 0, len(cells)
        while i < m:
            if self._pending:
                self._wrap()
            x = self._x
            space = w - x
            if not self._autowrap and m - i > space:
                if space > 1:
                    self._lay(x, cells[i:i + space - 1])
                self._lay(w - 1, [cells[-1]])
                self._x = w - 1
                self._edge = True
                return
            k = min(space, m - i)
            self._lay(x, cells[i:i + k])
            i += k
            x += k
            if x >= w:
                self._x = w - 1
                self._pending = self._autowrap
                self._edge = True
            else:
                self._x = x
                self._edge = False

    def _cluster(self, c: str, new: Cell) -> None:
        """Print one cluster (already mapped) as the rules of "Printing" give."""
        n = new.width
        if n == 0:
            self._join(c)
            return
        if self._pending:
            self._wrap()
        w = self._w
        if n == 2:
            if w == 1:
                new, n = blank(self._style), 1
            elif self._x == w - 1:
                if not self._autowrap:
                    return
                y = self._y
                self._lay(w - 1, [self._erase])
                self._buf.wrapped[y] = True
                self._buf.padded[y] = True
                self._x = 0
                self._index()
        self._lay(self._x, [new, tail(new.style)] if n == 2 else [new])
        self._last = c
        x = self._x + n
        if x >= w:
            self._x = w - 1
            self._pending = self._autowrap
            self._edge = True
        else:
            self._x = x
            self._edge = False

    def _join(self, c: str) -> None:
        """A zero-width cluster joins the cell before the cursor (rule 1), or the cursor's cell
        when the last print wrote the last column and nothing has moved or written since."""
        if self._pending or (self._edge and not self._autowrap):
            tx = self._x
        elif self._x == 0:
            return
        else:
            tx = self._x - 1
        row = self._buf.rows[self._y]
        if row[tx].width == 0:
            tx -= 1
        old = row[tx]
        joined = old.glyph + c
        if width(joined) != old.width or len(cluster(joined)) != 1:
            return
        row[tx] = Cell(joined, old.width, old.style)
        self._last = joined

    def _lay(self, x: int, cells: "list[Cell]") -> None:
        """Write cells into the cursor's row at `x` (shifting right first in insert mode); a
        pair half overwritten leaves its other half blank."""
        y, w, k = self._y, self._w, len(cells)
        row = self._buf.rows[y]
        if self._insert:
            self._shift_right(row, x, k, BLANK)
        if row[x].width == 0:
            row[x - 1] = blank(row[x - 1].style)
        end = x + k
        if row[end - 1].width == 2:
            row[end] = blank(row[end].style)
        row[x:end] = cells
        if end == w:
            self._buf.padded[y] = False

    def _wrap(self) -> None:
        """Auto-wrap: the row marked wrapped, the cursor to column 0 of the next row."""
        self._buf.wrapped[self._y] = True
        self._x = 0
        self._pending = self._edge = False
        self._index()

    def _shift_right(self, row: "list[Cell]", x: int, n: int, new: Cell) -> None:
        """Move the cells from `x` right by `n` (lost past the edge), `new` cells brought in."""
        w = self._w
        n = min(n, w - x)
        self._edge = False
        if row[x].width == 0:
            row[x - 1] = blank(row[x - 1].style)
            row[x] = blank(row[x].style)
        row[x:x] = [new] * n
        del row[w:]
        if row[w - 1].width == 2:
            row[w - 1] = blank(row[w - 1].style)
        self._buf.padded[self._y] = False

    # -- moving and scrolling

    def _index(self) -> None:
        """IND: down one row, scrolling the region at its bottom row."""
        self._edge = False
        if self._y == self._bottom - 1:
            self._scroll_up(1, BLANK)
        elif self._y < self._h - 1:
            self._y += 1

    def _reverse_index(self) -> None:
        """RI: up one row, scrolling the region down at its top row."""
        self._edge = False
        if self._y == self._top:
            self._scroll_down(1, BLANK)
        elif self._y > 0:
            self._y -= 1

    def _scroll_up(self, n: int, new: Cell, top: "int | None" = None) -> None:
        """The region (from row `top` when given, for DL) up `n` rows; rows off the top of a
        whole primary screen to `scrolled()`."""
        self._edge = False
        out = top is None and self._top == 0 and self._bottom == self._h and not self._alt
        top, bottom, b = self._top if top is None else top, self._bottom, self._buf
        n = min(n, bottom - top)
        if out:
            self._scrolled.extend(zip(b.rows[:n], b.wrapped[:n], b.padded[:n]))
        rows = [[new] * self._w for _ in range(n)]
        b.rows[top:bottom] = b.rows[top + n:bottom] + rows
        b.wrapped[top:bottom] = b.wrapped[top + n:bottom] + [False] * n
        b.padded[top:bottom] = b.padded[top + n:bottom] + [False] * n

    def _scroll_down(self, n: int, new: Cell, top: "int | None" = None) -> None:
        """The region (from row `top` when given, for IL) down `n` rows; rows pushed past its
        bottom lost."""
        self._edge = False
        top, bottom, b = self._top if top is None else top, self._bottom, self._buf
        n = min(n, bottom - top)
        rows = [[new] * self._w for _ in range(n)]
        b.rows[top:bottom] = rows + b.rows[top:bottom - n]
        b.wrapped[top:bottom] = [False] * n + b.wrapped[top:bottom - n]
        b.padded[top:bottom] = [False] * n + b.padded[top:bottom - n]

    def _move(self, x: int, y: int) -> None:
        """The cursor to (x, y), clamped into the screen; pending wrap cleared."""
        self._x = max(0, min(x, self._w - 1))
        self._y = max(0, min(y, self._h - 1))
        self._pending = self._edge = False

    def _row(self, n: int) -> int:
        """Row `n` (0-based) as CUP / VPA address it: origin-relative and kept in the region."""
        if self._origin:
            return max(self._top, min(self._top + n, self._bottom - 1))
        return n

    def _home(self) -> None:
        self._move(0, self._top if self._origin else 0)

    def _up(self, n: int) -> None:
        y = self._y
        floor = self._top if self._top <= y < self._bottom else 0
        self._move(self._x, max(floor, y - n))

    def _down(self, n: int) -> None:
        y = self._y
        ceiling = self._bottom - 1 if self._top <= y < self._bottom else self._h - 1
        self._move(self._x, min(ceiling, y + n))

    def _tab_forward(self, n: int) -> None:
        x = self._x
        for _ in range(min(n, self._w)):
            i = bisect_right(self._tabs, x)
            x = self._tabs[i] if i < len(self._tabs) and self._tabs[i] < self._w else self._w - 1
        self._move(x, self._y)

    def _tab_back(self, n: int) -> None:
        x = self._x
        for _ in range(min(n, self._w)):
            i = bisect_left(self._tabs, x)
            x = self._tabs[i - 1] if i > 0 else 0
        self._move(x, self._y)

    # -- erasing

    def _erase_cells(self, y: int, lo: int, hi: int) -> None:
        """Columns `lo .. hi - 1` of row `y` become the erase cell; a whole row is unwrapped."""
        w = self._w
        self._edge = False
        lo, hi = max(0, lo), min(w, hi)
        if lo >= hi:
            return
        b = self._buf
        row = b.rows[y]
        if row[lo].width == 0:
            row[lo - 1] = blank(row[lo - 1].style)
        if row[hi - 1].width == 2:
            row[hi] = blank(row[hi].style)
        row[lo:hi] = [self._erase] * (hi - lo)
        if hi == w:
            b.padded[y] = False
            if lo == 0:
                b.wrapped[y] = False

    def _erase_rows(self, lo: int, hi: int) -> None:
        for y in range(lo, hi):
            self._erase_cells(y, 0, self._w)

    # -- save and restore

    def _save(self, buf: "_Buffer | None" = None) -> None:
        (buf or self._buf).saved = (self._x, self._y, self._pending, self._pen, self._g[0], self._g[1],
                                    self._shift, self._origin)

    def _restore(self, buf: "_Buffer | None" = None) -> None:
        saved = (buf or self._buf).saved
        if saved is None:
            saved = (0, 0, False, _PLAIN, "ascii", "ascii", 0, False)
        x, y, pending, pen, g0, g1, shift, origin = saved
        self._x, self._y = min(x, self._w - 1), min(y, self._h - 1)
        self._pending = pending and self._autowrap and self._x == self._w - 1
        self._edge = False
        self._set_pen(pen)
        self._g = [g0, g1]
        self._shift = shift
        self._origin = origin

    # -- buffers

    def _switch(self, alt: bool) -> None:
        self._alt = alt
        self._buf = self._bufs[1 if alt else 0]
        self._edge = False

    def _event(self, event: Event) -> None:
        self._events.append(event)

    def _reply(self, data: bytes) -> None:
        self._events.append(Reply(data))

    # -- C0

    def _bel(self) -> None:
        self._event(Bell())

    def _bs(self) -> None:
        self._move(self._x - 1, self._y)

    def _ht(self) -> None:
        self._tab_forward(1)

    def _lf(self) -> None:
        self._pending = False
        self._index()
        if self._newline:
            self._x = 0

    def _cr(self) -> None:
        self._x = 0
        self._pending = self._edge = False

    def _so(self) -> None:
        self._shift = 1

    def _si(self) -> None:
        self._shift = 0

    # -- ESC

    def _ind(self, a: Esc) -> None:
        self._pending = False
        self._index()

    def _nel(self, a: Esc) -> None:
        self._cr()
        self._index()

    def _hts(self, a: Esc) -> None:
        if self._x not in self._tabs:
            insort(self._tabs, self._x)

    def _ri(self, a: Esc) -> None:
        self._pending = False
        self._reverse_index()

    def _decsc(self, a: object) -> None:
        self._save()

    def _decrc(self, a: object) -> None:
        self._restore()

    def _ris(self, a: Esc) -> None:
        self._reset()

    def _decaln(self, a: Esc) -> None:
        self._buf.clear(self._w, _ALIGN)
        self._edge = False
        self._top, self._bottom = 0, self._h
        self._origin = False
        self._move(0, 0)

    def _designate(self, a: Esc) -> None:
        self._g[0 if a.intermediates == "(" else 1] = _DESIGNATE.get(a.final, "ascii")

    def _deckpam(self, a: Esc) -> None:
        self._keypad = True

    def _deckpnm(self, a: Esc) -> None:
        self._keypad = False

    def _decid(self, a: object) -> None:
        self._reply(b"\x1b[?62;22c")

    # -- CSI: the cursor

    def _cuu(self, a: Csi) -> None:
        self._up(_count(a))

    def _cud(self, a: Csi) -> None:
        self._down(_count(a))

    def _cuf(self, a: Csi) -> None:
        self._move(self._x + min(_count(a), self._w), self._y)

    def _cub(self, a: Csi) -> None:
        self._move(self._x - min(_count(a), self._w), self._y)

    def _cnl(self, a: Csi) -> None:
        self._down(_count(a))
        self._x = 0

    def _cpl(self, a: Csi) -> None:
        self._up(_count(a))
        self._x = 0

    def _cha(self, a: Csi) -> None:
        self._move(min(_count(a), self._w) - 1, self._y)

    def _cup(self, a: Csi) -> None:
        self._move(min(_count(a, 1), self._w) - 1, self._row(min(_count(a), self._h) - 1))

    def _vpa(self, a: Csi) -> None:
        self._move(self._x, self._row(min(_count(a), self._h) - 1))

    def _cht(self, a: Csi) -> None:
        self._tab_forward(_count(a))

    def _cbt(self, a: Csi) -> None:
        self._tab_back(_count(a))

    # -- CSI: erasing and editing

    def _ed(self, a: Csi) -> None:
        p, x, y, h = _arg(a, 0, 0), self._x, self._y, self._h
        if p == 0:
            self._erase_cells(y, x, self._w)
            self._erase_rows(y + 1, h)
        elif p == 1:
            self._erase_rows(0, y)
            self._erase_cells(y, 0, x + 1)
        elif p == 2:
            self._erase_rows(0, h)

    def _el(self, a: Csi) -> None:
        p, x, y = _arg(a, 0, 0), self._x, self._y
        if p == 0:
            self._erase_cells(y, x, self._w)
        elif p == 1:
            self._erase_cells(y, 0, x + 1)
        elif p == 2:
            self._erase_cells(y, 0, self._w)

    def _ech(self, a: Csi) -> None:
        self._erase_cells(self._y, self._x, self._x + min(_count(a), self._w))

    def _ich(self, a: Csi) -> None:
        self._shift_right(self._buf.rows[self._y], self._x, min(_count(a), self._w), self._erase)

    def _dch(self, a: Csi) -> None:
        x, w = self._x, self._w
        n = min(_count(a), w - x)
        self._edge = False
        row = self._buf.rows[self._y]
        if row[x].width == 0:
            row[x - 1] = blank(row[x - 1].style)
        del row[x:x + n]
        row.extend([self._erase] * n)
        if row[x].width == 0:
            row[x] = blank(row[x].style)
        self._buf.padded[self._y] = False

    def _il(self, a: Csi) -> None:
        if self._top <= self._y < self._bottom:
            self._scroll_down(_count(a), self._erase, self._y)
            self._move(0, self._y)

    def _dl(self, a: Csi) -> None:
        if self._top <= self._y < self._bottom:
            self._scroll_up(_count(a), self._erase, self._y)
            self._move(0, self._y)

    def _su(self, a: Csi) -> None:
        self._scroll_up(_count(a), self._erase)

    def _sd(self, a: Csi) -> None:
        if len(a.params) <= 1:
            self._scroll_down(_count(a), self._erase)

    def _rep(self, a: Csi) -> None:
        last = self._last
        if not self._after_print or last is None:
            return
        n = min(_count(a), self._w * self._h)
        if self._kinds.get(last) == 1:
            self._narrow(last * n)
            return
        new = self._cell(last)
        for _ in range(n):
            self._cluster(last, new)

    def _tbc(self, a: Csi) -> None:
        p = _arg(a, 0, 0)
        if p == 0:
            if self._x in self._tabs:
                self._tabs.remove(self._x)
        elif p == 3:
            self._tabs.clear()

    def _decstbm(self, a: Csi) -> None:
        t = max(1, _arg(a, 0, 1))
        b = _arg(a, 1, self._h)
        b = self._h if b == 0 else min(b, self._h)
        if t < b:
            self._top, self._bottom = t - 1, b
            self._home()

    def _scosc(self, a: Csi) -> None:
        if not a.params:
            self._save()

    def _scorc(self, a: Csi) -> None:
        if not a.params:
            self._restore()

    def _decstr(self, a: Csi) -> None:
        self._insert = self._origin = False
        self._autowrap = self._visible = True
        self._top, self._bottom = 0, self._h
        self._g = ["ascii", "ascii"]
        self._shift = 0
        self._set_pen(_PLAIN)
        self._buf.saved = None

    def _decscusr(self, a: Csi) -> None:
        p = _arg(a, 0, 0)
        if 0 <= p <= 6:
            self._shape = p

    # -- CSI: SGR

    def _sgr(self, a: Csi) -> None:
        pen = list(self._pen)
        params = a.params or ((0,),)
        i, m = 0, len(params)
        while i < m:
            p = params[i]
            code = p[0] or 0
            if code in (38, 48, 58):
                colour, i = _extended(params, i)
                if colour is not _BAD:
                    pen[_FG if code == 38 else _BG if code == 48 else _ULC] = colour
                continue
            _sgr_code(pen, code, p)
            i += 1
        self._set_pen(tuple(pen))

    # -- CSI: modes

    def _sm(self, a: Csi) -> None:
        self._ansi_modes(a, True)

    def _rm(self, a: Csi) -> None:
        self._ansi_modes(a, False)

    def _ansi_modes(self, a: Csi, on: bool) -> None:
        for p in a.params:
            if p[0] == 4:
                self._insert = on
            elif p[0] == 20:
                self._newline = on

    def _decset(self, a: Csi) -> None:
        self._dec_modes(a, True)

    def _decrst(self, a: Csi) -> None:
        self._dec_modes(a, False)

    def _dec_modes(self, a: Csi, on: bool) -> None:
        for p in a.params:
            handler = _DEC.get(p[0])
            if handler is not None:
                handler(self, p[0], on)

    def _m_cursor_keys(self, p: int, on: bool) -> None:
        self._cursor_keys = on

    def _m_origin(self, p: int, on: bool) -> None:
        self._origin = on
        self._home()

    def _m_autowrap(self, p: int, on: bool) -> None:
        self._autowrap = on
        if not on:
            self._pending = False

    def _m_mouse(self, p: int, on: bool) -> None:
        if on:
            self._mouse = p
        elif self._mouse == p:
            self._mouse = 0

    def _m_visible(self, p: int, on: bool) -> None:
        self._visible = on

    def _m_alternate(self, p: int, on: bool) -> None:
        if on == self._alt:
            return
        if on:
            if p == 1049:
                self._save(self._bufs[0])
                self._bufs[1].clear(self._w, BLANK)
            self._switch(True)
            return
        if p == 1047:
            self._bufs[1].clear(self._w, self._erase)
        self._switch(False)
        if p == 1049:
            self._restore(self._bufs[0])

    def _m_save(self, p: int, on: bool) -> None:
        if on:
            self._save()
        else:
            self._restore()

    def _m_focus(self, p: int, on: bool) -> None:
        self._focus = on

    def _m_mouse_sgr(self, p: int, on: bool) -> None:
        self._mouse_sgr = on

    def _m_paste(self, p: int, on: bool) -> None:
        self._paste = on

    def _m_sync(self, p: int, on: bool) -> None:
        if on and self._frame is None:
            self._frame = (self.grid(live=True), self.cursor(live=True))
        elif not on:
            self._frame = None

    def _mode_state(self, p: "int | None") -> int:
        """DECRQM's state for private mode `p`: 1 set, 2 reset, 0 not tracked."""
        if p not in _TRACKED:
            return 0
        if p in _MOUSE:
            on = self._mouse == p
        else:
            on = {1: self._cursor_keys, 6: self._origin, 7: self._autowrap, 25: self._visible,
                  47: self._alt, 1047: self._alt, 1049: self._alt, 1004: self._focus,
                  1006: self._mouse_sgr, 2004: self._paste, 2026: self._frame is not None}[p]
        return 1 if on else 2

    # -- CSI: reports

    def _dsr(self, a: Csi) -> None:
        p = _arg(a, 0, 0)
        if p == 5:
            self._reply(b"\x1b[0n")
        elif p == 6:
            self._reply(b"\x1b[%d;%dR" % self._report_position())

    def _xcpr(self, a: Csi) -> None:
        if _arg(a, 0, 0) == 6:
            self._reply(b"\x1b[?%d;%d;1R" % self._report_position())

    def _report_position(self) -> "tuple[int, int]":
        y = self._y - self._top if self._origin else self._y
        return (y + 1, self._x + 1)

    def _da1(self, a: Csi) -> None:
        if len(a.params) <= 1 and _arg(a, 0, 0) == 0:
            self._decid(a)

    def _da2(self, a: Csi) -> None:
        if len(a.params) <= 1 and _arg(a, 0, 0) == 0:
            self._reply(b"\x1b[>1;10;0c")

    def _decrqm(self, a: Csi) -> None:
        p = _arg(a, 0, 0)
        self._reply(b"\x1b[?%d;%d$y" % (p, self._mode_state(p)))

    def _ansirqm(self, a: Csi) -> None:
        p = _arg(a, 0, 0)
        state = {4: self._insert, 20: self._newline}.get(p)
        self._reply(b"\x1b[%d;%d$y" % (p, 0 if state is None else 1 if state else 2))

    def _winops(self, a: Csi) -> None:
        p = _arg(a, 0, 0)
        if p == 18:
            self._reply(b"\x1b[8;%d;%dt" % (self._h, self._w))
        elif p in (22, 23) and _arg(a, 1, 0) in (0, 2):
            if p == 22:
                self._titles.append(self._title)
                del self._titles[:-TITLE_DEPTH]
            elif self._titles:
                self._title = self._titles.pop()
                self._event(Title(self._title))

    # -- CSI: kitty keyboard

    def _kitty_push(self, a: Csi) -> None:
        stack = self._buf.kitty
        stack.append(_arg(a, 0, 0) & 31)
        del stack[:-KITTY_DEPTH]

    def _kitty_pop(self, a: Csi) -> None:
        stack = self._buf.kitty
        del stack[max(0, len(stack) - _count(a)):]

    def _kitty_set(self, a: Csi) -> None:
        f, m = _arg(a, 0, 0) & 31, _arg(a, 1, 1)
        stack = self._buf.kitty
        top = stack[-1] if stack else 0
        if m == 1:
            new = f
        elif m == 2:
            new = top | f
        elif m == 3:
            new = top & ~f
        else:
            return
        if stack:
            stack[-1] = new
        else:
            stack.append(new)

    def _kitty_query(self, a: Csi) -> None:
        stack = self._buf.kitty
        self._reply(b"\x1b[?%du" % (stack[-1] if stack else 0))

    # -- OSC

    def _osc_title(self, rest: "bytes | None", bel: bool) -> None:
        if rest is not None:
            self._title = _clean(rest)
            self._event(Title(self._title))

    def _osc_cwd(self, rest: "bytes | None", bel: bool) -> None:
        if rest is not None:
            self._event(Cwd(_clean(rest)))

    def _osc_link(self, rest: "bytes | None", bel: bool) -> None:
        if rest is None or b";" not in rest:
            return
        uri = rest.split(b";", 1)[1].decode("utf-8", "replace")
        link = uri if uri and uri.translate(_CONTROLS) == uri else None
        pen = list(self._pen)
        pen[_LINK] = link
        self._set_pen(tuple(pen))

    def _osc_clipboard(self, rest: "bytes | None", bel: bool) -> None:
        if rest is None or b";" not in rest:
            return
        targets, data = rest.split(b";", 1)
        if data == b"?":
            return
        try:
            decoded = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            return
        self._event(Clipboard(_clean(targets), decoded))

    def _osc_palette(self, rest: "bytes | None", bel: bool) -> None:
        if rest is None:
            return
        fields = rest.split(b";")
        for c, spec in zip(fields[::2], fields[1::2]):
            if spec == b"?" and c.isdigit() and int(c) <= 255:
                n = int(c)
                self._reply(b"\x1b]4;%d;" % n + _colour_reply(palette_rgb(n), bel))

    def _osc_fg(self, rest: "bytes | None", bel: bool) -> None:
        if rest == b"?":
            self._reply(b"\x1b]10;" + _colour_reply(self._fg_rgb, bel))

    def _osc_bg(self, rest: "bytes | None", bel: bool) -> None:
        if rest == b"?":
            self._reply(b"\x1b]11;" + _colour_reply(self._bg_rgb, bel))


_C0 = {0x07: Screen._bel, 0x08: Screen._bs, 0x09: Screen._ht, 0x0A: Screen._lf, 0x0B: Screen._lf,
       0x0C: Screen._lf, 0x0D: Screen._cr, 0x0E: Screen._so, 0x0F: Screen._si}

_ESC = {("", "D"): Screen._ind, ("", "E"): Screen._nel, ("", "H"): Screen._hts, ("", "M"): Screen._ri,
        ("", "7"): Screen._decsc, ("", "8"): Screen._decrc, ("", "c"): Screen._ris,
        ("#", "8"): Screen._decaln, ("", "="): Screen._deckpam, ("", ">"): Screen._deckpnm,
        ("", "Z"): Screen._decid}

_CSI = {
    ("", "", "A"): Screen._cuu, ("", "", "B"): Screen._cud, ("", "", "e"): Screen._cud,
    ("", "", "C"): Screen._cuf, ("", "", "a"): Screen._cuf, ("", "", "D"): Screen._cub,
    ("", "", "E"): Screen._cnl, ("", "", "F"): Screen._cpl, ("", "", "G"): Screen._cha,
    ("", "", "`"): Screen._cha, ("", "", "H"): Screen._cup, ("", "", "f"): Screen._cup,
    ("", "", "d"): Screen._vpa, ("", "", "I"): Screen._cht, ("", "", "Z"): Screen._cbt,
    ("", "", "J"): Screen._ed, ("?", "", "J"): Screen._ed, ("", "", "K"): Screen._el,
    ("?", "", "K"): Screen._el, ("", "", "X"): Screen._ech, ("", "", "@"): Screen._ich,
    ("", "", "P"): Screen._dch, ("", "", "L"): Screen._il, ("", "", "M"): Screen._dl,
    ("", "", "S"): Screen._su, ("", "", "T"): Screen._sd, ("", "", "b"): Screen._rep,
    ("", "", "g"): Screen._tbc, ("", "", "m"): Screen._sgr, ("", "", "r"): Screen._decstbm,
    ("", "", "s"): Screen._scosc, ("", "", "u"): Screen._scorc, ("", "", "h"): Screen._sm,
    ("", "", "l"): Screen._rm, ("?", "", "h"): Screen._decset, ("?", "", "l"): Screen._decrst,
    ("", "", "n"): Screen._dsr, ("?", "", "n"): Screen._xcpr, ("", "", "c"): Screen._da1,
    (">", "", "c"): Screen._da2, ("?", "$", "p"): Screen._decrqm, ("", "$", "p"): Screen._ansirqm,
    ("", "", "t"): Screen._winops, (">", "", "u"): Screen._kitty_push, ("<", "", "u"): Screen._kitty_pop,
    ("=", "", "u"): Screen._kitty_set, ("?", "", "u"): Screen._kitty_query,
    ("", " ", "q"): Screen._decscusr, ("", "!", "p"): Screen._decstr,
}

_DEC = {1: Screen._m_cursor_keys, 6: Screen._m_origin, 7: Screen._m_autowrap, 9: Screen._m_mouse,
        1000: Screen._m_mouse, 1002: Screen._m_mouse, 1003: Screen._m_mouse, 25: Screen._m_visible,
        47: Screen._m_alternate, 1047: Screen._m_alternate, 1049: Screen._m_alternate,
        1048: Screen._m_save, 1004: Screen._m_focus, 1006: Screen._m_mouse_sgr, 2004: Screen._m_paste,
        2026: Screen._m_sync}

_OSC = {b"0": Screen._osc_title, b"2": Screen._osc_title, b"7": Screen._osc_cwd, b"8": Screen._osc_link,
        b"52": Screen._osc_clipboard, b"4": Screen._osc_palette, b"10": Screen._osc_fg,
        b"11": Screen._osc_bg}


def apply(screen: Screen, actions: "Iterable[Action]") -> Grid:
    """Perform the actions on the screen, in order, and return `screen.grid()`."""
    if not isinstance(screen, Screen):
        raise TypeError(f"screen must be a Screen, got {type(screen).__name__}")
    dispatch(actions, screen)
    return screen.grid()


def reflow(lines: "Iterable[Line]", w: int) -> "tuple[Line, ...]":
    """The lines joined into logical lines and wrapped again at width `w`."""
    if not isinstance(w, int) or isinstance(w, bool):
        raise TypeError(f"w must be an int, got {type(w).__name__}")
    if w < 1:
        raise ValueError(f"w must be >= 1, got {w}")
    if isinstance(lines, (str, bytes)) or not isinstance(lines, Iterable):
        raise TypeError(f"lines must be an iterable of Line, got {type(lines).__name__}")
    items = list(lines)
    for item in items:
        if not isinstance(item, Line):
            raise TypeError(f"expected a Line, got {type(item).__name__}")
    return tuple(_reflow(items, w, None)[0])


# -- helpers


def _reflow(lines: "list[Line]", w: int, anchor: "tuple[int, int] | None"
            ) -> "tuple[list[Line], tuple[int, int] | None]":
    """Reflow `lines` at `w`; with `anchor` (the index of a logical line's first Line, an offset
    into its cells) also the (row, column) where that offset lands."""
    out: "list[Line]" = []
    at = None
    i, n = 0, len(lines)
    while i < n:
        first = i
        cells: "list[Cell]" = []
        while True:
            cells.extend(lines[i].cells)
            i += 1
            if not lines[i - 1].wrapped or i == n:
                break
        offset = anchor[1] if anchor is not None and anchor[0] == first else None
        rows, pos = _cut(cells, w, offset)
        if pos is not None:
            at = (len(out) + pos[0], pos[1])
        flag = lines[i - 1].wrapped
        last = len(rows) - 1
        out.extend(_line(tuple(r), k < last or flag) for k, r in enumerate(rows))
    return out, at


def _cut(cells: "list[Cell]", w: int, offset: "int | None"
         ) -> "tuple[list[list[Cell]], tuple[int, int] | None]":
    """One logical line's cells cut into rows of at most `w` columns, never splitting a pair;
    where `offset` lands (past the end: right after the last cell, a new row when that is `w`)."""
    rows: "list[list[Cell]]" = [[]]
    pos = None
    for k, c in enumerate(cells):
        if c.width == 0:
            if k == offset:
                pos = (len(rows) - 1, len(rows[-1]) - 1)  # the tail's own column
            continue
        cur = rows[-1]
        size = 2 if c.width == 2 and w > 1 else 1
        if len(cur) + size > w:
            cur = []
            rows.append(cur)
        if k == offset:
            pos = (len(rows) - 1, len(cur))
        if c.width == 2:
            if w == 1:
                cur.append(blank(c.style))
            else:
                cur.extend((c, tail(c.style)))
        else:
            cur.append(c)
    if offset is not None and pos is None:
        if len(rows[-1]) >= w:
            rows.append([])
        pos = (len(rows) - 1, len(rows[-1]))
    return rows, pos


def _line(cells: "tuple[Cell, ...]", wrapped: bool) -> Line:
    """A Line of cells this module built well formed (not checked again)."""
    new = object.__new__(Line)
    object.__setattr__(new, "cells", cells)
    object.__setattr__(new, "wrapped", wrapped)
    return new


def _row_line(row: "list[Cell]", wrapped: bool, padded: bool, keep: int = 0) -> Line:
    """A row as a Line: a padded wrapped row without its pad, an unwrapped one without its
    trailing BLANKs (but at least the `keep` cells left of the cursor)."""
    if wrapped:
        return _line(tuple(row[:-1] if padded else row), True)
    return _line(tuple(row[:max(keep, _content(row))]), False)


def _content(row: "list[Cell]") -> int:
    """The length of the row without its trailing BLANKs."""
    n = len(row)
    while n:
        c = row[n - 1]
        if c is not BLANK and not (c.style is None and c.width == 1 and c.glyph == " "):
            break
        n -= 1
    return n


def _pen_state(pen: tuple) -> "tuple[Style | None, Cell, dict]":
    """The pen's Style (None when plain), its erase cell and an empty cell cache."""
    fg, bg, bold, dim, italic, ul, ulc, strike, reverse, link = pen
    if fg is None and bg is None and not (bold or dim or italic or ul or strike or reverse) and link is None:
        style = None
    else:
        style = Style(fg=fg, bg=bg, bold=bold, dim=dim, italic=italic, underline=ul,
                      underline_colour=ulc if ul else None, strike=strike, reverse=reverse, link=link)
    erase = blank(Style(bg=bg)) if bg is not None else BLANK
    return style, erase, {}


_SGR_FLAGS = {1: (_BOLD, True), 2: (_DIM, True), 3: (_ITALIC, True), 7: (_REVERSE, True),
              9: (_STRIKE, True), 23: (_ITALIC, False), 24: (_UL, None), 27: (_REVERSE, False),
              29: (_STRIKE, False), 21: (_UL, "double"), 39: (_FG, None), 49: (_BG, None),
              59: (_ULC, None)}

_BAD = object()


def _sgr_code(pen: list, code: int, p: tuple) -> None:
    """Apply one SGR code (not an extended colour) to the pen."""
    if code == 0:
        pen[:_LINK] = _PLAIN[:_LINK]
    elif code == 4:
        sub = p[1] if len(p) > 1 else 1
        pen[_UL] = _UNDERLINES.get(sub or 0, "single")
    elif code == 22:
        pen[_BOLD] = pen[_DIM] = False
    elif code in _SGR_FLAGS:
        field, value = _SGR_FLAGS[code]
        pen[field] = value
    elif 30 <= code <= 37:
        pen[_FG] = _NAMED[code - 30]
    elif 90 <= code <= 97:
        pen[_FG] = _NAMED[code - 90 + 8]
    elif 40 <= code <= 47:
        pen[_BG] = _NAMED[code - 40]
    elif 100 <= code <= 107:
        pen[_BG] = _NAMED[code - 100 + 8]


def _extended(params: tuple, i: int) -> "tuple[object, int]":
    """The extended colour at parameter `i` (38 / 48 / 58) and the index after what it took;
    `_BAD` for a malformed one."""
    p = params[i]
    if len(p) > 1:  # the ":" form, all in one parameter
        subs = p[1:]
        if subs[0] == 5 and len(subs) >= 2:
            return _index_colour(subs[1]), i + 1
        if subs[0] == 2 and len(subs) >= 4:
            return _rgb_colour(subs[2:5] if len(subs) >= 5 else subs[1:4]), i + 1
        return _BAD, i + 1
    kind = params[i + 1][0] if i + 1 < len(params) else None
    if kind == 5:
        if i + 2 >= len(params):
            return _BAD, len(params)
        return _index_colour(params[i + 2][0]), i + 3
    if kind == 2:
        if i + 4 >= len(params):
            return _BAD, len(params)
        return _rgb_colour(tuple(q[0] for q in params[i + 2:i + 5])), i + 5
    return _BAD, min(i + 2, len(params))


def _index_colour(n: "int | None") -> object:
    if n is None or not 0 <= n <= 255:
        return _BAD
    return Colour("index", n)


def _rgb_colour(values: tuple) -> object:
    if len(values) != 3 or any(v is None or not 0 <= v <= 255 for v in values):
        return _BAD
    return Colour("rgb", tuple(values))


def _colour_reply(rgb: "tuple[int, int, int]", bel: bool) -> bytes:
    body = "rgb:%04x/%04x/%04x" % tuple(v * 257 for v in rgb)
    return body.encode() + (b"\x07" if bel else b"\x1b\\")


def _clean(data: bytes) -> str:
    """A field's bytes as text: UTF-8 (replace), every C0, DEL and C1 character removed."""
    return data.decode("utf-8", "replace").translate(_CONTROLS)


def _arg(a: Csi, i: int, default: int) -> int:
    """The first sub-parameter of parameter `i`, or `default` when it is missing or empty."""
    params = a.params
    if i < len(params):
        v = params[i][0]
        if v is not None:
            return v
    return default


def _count(a: Csi, i: int = 0) -> int:
    """A count or position: default 1, 0 means 1."""
    return max(1, _arg(a, i, 1))


def _size(w: object, h: object) -> None:
    for name, value in (("w", w), ("h", h)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if w < 1 or h < 1:
        raise ValueError(f"w and h must be >= 1, got {w}, {h}")


def _rgb(value: object, name: str) -> "tuple[int, int, int]":
    if not isinstance(value, tuple) or len(value) != 3 or not all(
            isinstance(v, int) and not isinstance(v, bool) for v in value):
        raise TypeError(f"{name} must be a tuple of three ints")
    if not all(0 <= v <= 255 for v in value):
        raise ValueError(f"{name}'s components must be 0..255, got {value}")
    return value


def _bool(value: object, name: str) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a bool, got {type(value).__name__}")
