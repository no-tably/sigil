"""[Controls]: the things a person operates: buttons, selects, text inputs.

Kind: system (the expansion of [Controls] in Widgets); pure. It imports Core only
(Text, Style, Buffer, Geometry, which it inherits through Draw): never Collections,
Containers, Readouts, Surfaces, the Widgets package, Layout, Theme, Input, Paint or
Draw's `context.py`. A {Context} arrives as an argument and is read by attribute;
so does Input's {Edit} (TextInput reads it by its attributes, as a duck type).

The parts, every one a leaf (no children, `chrome()` is `None`, `lifts(ctx)` is
`False`, `surface` defaults to `False`): [Button] (`Button`: a button, a toggle, a
radio, a switch), [Select] (`Select`, `Option`: a dropdown's face, or an open menu,
a command palette's list), [TextInput] (`TextInput`: one line or an area, drawn
from the app's edit value).

Inside the family, `button.py` hosts the family's private toolkit (the checks, the
ground, the key row and the indicator this package states once): Select and TextInput
import those helpers, never a Button name; Select's menu window is its own (Q9c).

A control never changes itself: what is pressed, on, chosen, open or typed is the
app's state, given in its fields; the control draws it and records where it is hit,
and the app's router turns a hit or a key into the app's action (roving, committing
a choice and firing an action stay three steps: hover only highlights).

The node protocol, as the Widgets package states it in full (`cure/draw/widgets`):
each kind is a frozen dataclass, its content fields first, then keyword-only fields
ending in `id`, `size`, `anchor`, `scope`, `surface`; `measure(axis, room, ctx,
content=0) -> int` (`content` ignored), `paint(rect, ctx, grid, clip=None) ->
tuple[Hit, ...]`, following the recipe (the clip's ground `ctx.ground()`, the
content, `shade(grid, clip, bg=g.style.bg)`).

The mark cell. Every control reserves one cell for its mark, never over text: a
control's first cell (`R.x`), or, for a control with a key (below), its last leader
cell. It shows the first non-empty mark of the control's states in the order each
kind gives (focused `›` first), in the style of the cell it replaces with those
states applied; else it is a blank (or the leader).

The key (Select's and TextInput's `label`), so a form of controls lines up with
PropertyLists at one separator column: with a non-empty `label`, the row starts as a
key:value row does: `Z = measure((label,))` (Text's: `1 + width(label)`), or
`max(ctx.zone, Z)` when `ctx.zone` is not `None` (an enclosing node pushed the zone
so siblings align); `L = Z - width(label)` leader cells `ctx.glyph("leader")` (-)
in role `dim`, the label in role `muted`, then `": "` (two ground cells); the
prefix is `P = Z + 2` cells and the mark cell is the last leader cell (`R.x + L -
1`). With no label, `P = 1` and the mark cell is `R.x`. The control's field is the
rest of the row, from `R.x + P`, `F = max(0, R.w - P)` cells (a rect narrower than
the prefix cuts the prefix and leaves the field no cells).

States, applied additively (`ctx.apply(<cell style>, state)`), each kind stating its
own order and extents; what shows with colour off, per state:
- focused: the mark cell's `›` (every kind);
- pressed: the mark cell's `●` and bold (Button);
- active (a latched button, `on`): the mark cell's `●` and bold (Button);
- hover: underline (its floor flag) over the control's cells;
- disabled: dim (its floor flag) over the label or the text;
- on / off (toggle, radio, switch): the glyph itself (`[•]` / `[ ]`, `(●)` / `( )`,
  `[─●]` / `[●─]`), whatever the colours; the glyphs are the charset's control tokens
  (`control.check`, `control.radio`, `control.knob`, `control.track`) and their
  styles the widget roles `control.on` (the on glyph) and `control.frame` (the
  frame and the track), which the builtin declares over `accent` and `muted`, so a
  theme restyles the controls alone (see Button; W1a: every builtin frame unchanged);
- chosen (Select's open menu): the state cell's `•` (Select keeps List's two-cell
  gutter, so the cursor and the choice both show on one row);
- a text selection (TextInput): the `selected` treatment over the selected cells;
  it reads with colour off only when the theme gives `selected` a floor flag (the
  builtin gives none: see TextInput).

Syntax styling (TextInput's `runs`, S1, refine round 5): the app may hand a text input
per-row runs `(text, spans)` of `(chunk, role, colour)` (sigil's highlight: its dotted
role and its `#rrggbb`). They colour the text and never change it; a row's runs are
used only while their `text` equals the row (else the row draws plain); a span's
style is the theme's declared `sigil.<role>` when it declares it (asked through the
context's `declared`, never by importing Theme), else its colour as a Core ink tagged
`sigil.<role>` (tty256 declared by Core's `nearest256`, tty16 left to the opt-in),
else plain. Every state above draws over a syntax-styled cell exactly as over a plain
one; with no runs every input draws as before S1. The rules, messages and laws are
TextInput's.

Hits, in order: each kind's, every one `Hit(r ∩ clip, tag)` and only when not
empty, with tags the control's `id` or `(id, part, ...)`, or an option's own `id`.

Every law listed in the Widgets package (contained, owned, pure, hits, moved,
legible, fits) holds for every kind here, the legible law with TextInput's one
stated exception, and for TextInput with or without runs; TextInput adds the syntax
styling's laws (unchanged, stale-plain, text-unchanged, colour-by-role, over,
frames).

Re-exported for consumers: `Button`, `KINDS` (button); `Select`, `Option` (select);
`TextInput`, `syntax_style` (textinput: the run-to-style lookup, S2b, so an app's test
asks which style a highlight role gets under a theme; re-exported here only, not from
the Widgets package).

Effects: none, apart from `paint`'s writes into the grid it is given.

Usage:
    from cure.core.buffer import Grid, text
    from cure.core.geometry import Rect
    from cure.draw.context import Context
    from cure.draw.theme import builtin
    from cure.draw.widgets.controls import Button
    ctx = Context.of(builtin(), focus="ok")
    g = Grid(9, 1)
    Button("OK", id="ok").paint(Rect(0, 0, 9, 1), ctx, g)   # (Hit(Rect(0, 0, 7, 1), "ok"),)
    text(g)                      # "›[ OK ]"
"""

from .button import KINDS, Button
from .select import Option, Select
from .textinput import TextInput, syntax_style
