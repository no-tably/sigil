"""[Notices]: the board's notices as a strip, on every tab.

Kind: service (Views' component; pure). Imported by Views' package only: `view` hands
the strip with every tab, as `TabView.strip` (`strip(board.notices)`), and no tab
module imports this one.

Where it sits. The app draws the strip full width under the tab's body: with strip
height `s` (its `measure("y")`) in a tab's area of height `h`, the body is
`Tiled(tree, views, titles)` in rows `[0, h - s)` and the strip is painted at
`(w, s)` in rows `[h - s, h)`. It is no pane of the tab's tree, so a kept tree never
moves for it. No notices: no strip (`None`), every tab drawn exactly as before.

The strip (`strip(notices) -> Drawing | None`). `None` for `()`; otherwise one
Widgets `Drawing` (no `id`) of `r` rows, its `measure("y")` being `r`. With `n =
len(notices)`:
- `n <= SHOWN` (3): `r = n`, one row per notice in the board's order;
- `n > SHOWN`: `r = 3`, the first 2 notices, then the overflow row, `f"+{n - 2}
  more"` in role `muted`.
A notice's row is a Toast's form, a Text `Line` of three spans: the role's word in
that role (`"info"`, `"ok"`, `"warn"`, `"error"`), `" "` in role `text`, then
`flat(text)` in role `text`. `flat` replaces each `"\\r\\n"`, then each `"\\n"`, with
one space; every other character is left as given.

The cut. Each row is cut at the strip's width by Text's `cut` with the ellipsis
(`ctx.glyph("ellipsis")`: Drawing's marks), the rest of the row ground; a wide glyph
straddling the cut is never half drawn.

The tags. Each row carries one hit covering that whole row of the strip's rect (all
its width, whatever its text): `KEY + (notice.id,)`, i.e. `("notices", id)`, and the
overflow row `KEY`, `("notices",)`. A notice whose `hit` is `False` has its row
drawn exactly the same but no hit (no region for that row); it still counts toward
the 3 rows and "+n more", in the caller's order (the strip sorts nothing). The
overflow row keeps its hit. The strip adds no other hit. What a hit does is
the app's (construct's: "this one"; the overflow's: e.g. a list of them all).

The text is harmless. It is the caller's, drawn as given: the strip only flattens
line breaks and hands the rest to Text unescaped, and Text draws every control (C0,
DEL, C1, ESC, a lone surrogate, a tab, a lone CR) as U+FFFD and a wide glyph as two
cells; Display sends only the cells. So only visible cells reach the terminal: no
control or escape sequence of the text does.

Constants: `KEY = ("notices",)` (the overflow row's tag, the prefix of every row's
tag); `SHOWN = 3` (the most rows the strip has).

Errors: none of its own (the notices are checked by {Notice} and {Board}).
Effects: none.

Usage:
    from cure.draw.context import Context
    from cure.draw.theme import builtin
    from cure.draw.views import notices
    from cure.draw.views.board import Notice
    ctx = Context.of(builtin())
    s = notices.strip((Notice("n1", "build failed", "error"),))
    s.measure("y", 0, ctx)          # 1
    notices.strip(())               # None
"""

from cure.core.geometry import Hit, Rect
from cure.core.text import Line, Span
from cure.draw.widgets import Drawing

from .board import Notice

KEY = ("notices",)
"""The strip's tag: the overflow row's, and the prefix of every notice's row."""

SHOWN = 3
"""The most rows the strip has."""

_WIDE = 1 << 30
"""A row's hit width before Drawing's clip makes it the row's full width."""


def strip(notices: "tuple[Notice, ...]") -> "Drawing | None":
    """The notices as a strip, or None for none (see the module)."""
    if not notices:
        return None
    n = len(notices)
    shown = notices if n <= SHOWN else notices[:SHOWN - 1]
    rows = [(_row(x), KEY + (x.id,) if x.hit else None) for x in shown]
    if n > SHOWN:
        rows.append((Line((Span(f"+{n - 2} more", "muted"),)), KEY))
    return Drawing(tuple(line for line, _ in rows),
                   regions=tuple(Hit(Rect(0, y, _WIDE, 1), tag)
                                 for y, (_, tag) in enumerate(rows)
                                 if tag is not None))


def _flat(text: str) -> str:
    """Each `"\\r\\n"`, then each `"\\n"`, as one space; every other character as given."""
    return text.replace("\r\n", " ").replace("\n", " ")


def _row(notice: Notice) -> Line:
    """A notice's row: its role's word in that role, then " " and the text in `text`."""
    parts = ((notice.role, notice.role), (" ", "text"), (_flat(notice.text), "text"))
    return Line(tuple(Span(t, role) for t, role in parts if t))
