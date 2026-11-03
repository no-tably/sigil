"""[SpecPane]: the root spec, editable: a TextInput area over the app's Edit, styled by
SpecDoc's highlight when given; SpecDoc's note in warn at the title row's end.

Kind: service (a pure function from a {SpecDoc} and the app's scroll to a widget node;
see the OrchestratorTab package for the tab and its key `k == ("orchestrator",)`).

What it does: the `"spec"` pane of construct's orchestrator tab. The spec's text is
construct's edit (Input's {Edit}: construct keeps it, its router hands it the keys
while the input is focused, every op returns a new value it hands in next frame),
drawn by a Widgets `TextInput` area inside a Block titled with the spec's path (and,
S2, the spec's note after it, in role `warn`). With no edit (no text loaded) the pane
is a read-only placeholder. It composes existing
widget nodes only and paints nothing itself; it reads no file.

The {SpecDoc} is read by attribute (`spec.path`, `spec.edit`, and `spec.highlight`
and `spec.note` when it has them: a value without one is read as `None`, so a spec
value of before S1, or of before S2, serves unchanged): OrchestratorTab's
import grants do not include Views' `board/` (nor Input), so any value with them
serves, Board's `SpecDoc` among them. The edit is duck-typed as Widgets' TextInput
reads it (`rows`, `line`, `column`, `selection`); TextInput checks its values when the
pane is built.

The pane (`specpane(spec, scroll=None) -> Block`):
`Block((child,), title=L, kind="pane", id=k + ("spec",))`, every other Block field
its default (Column layout, rounded border, `focused=None`; `kind="pane"`, R2, inert
until R3), where `T == spec.path` when it is
not `""`, else `UNTITLED == "spec"`, and the title `L` is, with `N = getattr(spec,
"note", None)` (S2):
- `N is None`: `L == T`, the plain `str`, exactly as before S2 (a long path is cut by
  the Block's title rule, with the ellipsis);
- else: the Text Line `L == Line.of((T, None), ("  ", None), (N, "warn"))`, in normal
  form `Line((Span(T + "  ", None), Span(N, "warn")))`: the path and a two-space gap
  in style `None`, which the Block draws in its `title` role, then the note in the
  theme role `warn` (Block's `_styled`: a span style `None` is the `title` role, a
  `str` a theme role).
The note is the Block's title, so it is shown whether or not there is an edit (over
the read-only placeholder too). The Block's title rule (bordered: the title rect is
`W = R.w - 4` cells of the top row at `R.x + 2`, for a pane rect `R` with `R.w >= 2`
and `R.h >= 2`, when the theme's top ends are one cell each; a wider start or end, as
wire's `▛▀` since round 13, moves the rect in past it and `W` is that much smaller), with `t = width(T)`, `n = width(N)` and `e` the width of
`ctx.glyph("ellipsis")` (1 for `…`, 3 for the ascii charset's `...`):
- `W >= t + n + 4`: the whole label `" " + T + "  " + N + " "`, left-aligned, the
  rest of the row the border's `h` line;
- `3 <= W < t + n + 4`: `" " + cut(L, W - 2, ellipsis) + " "`: Text's `cut` keeps the
  first `W - 2 - e` cells of `T + "  " + N` (a wide glyph straddling the edge is
  dropped) and the ellipsis after them, styled like the first cluster cut off
  (`warn` while the cut falls inside the note, the `title` role once it falls in
  the gap or the path). The kept cells are a prefix, so the note is cut first, the
  gap next and the path only once the note and the gap are gone: the path stays
  whole exactly when `W >= t + 2 + e` (without a note, when `W >= t + 2`: in the `e`
  widths between, a note costs the path's last cells to its ellipsis);
- `W < 3`, or no border drawn: no title, with a note or without (the `h` line stays).
`child` is:
- with an edit (`spec.edit is not None`): `TextInput(spec.edit, placeholder=EMPTY,
  scroll=scroll, runs=H, id=k + ("edit",))` with `H = getattr(spec, "highlight",
  None)` (S1: sigil's highlight of the text, passed as is: TextInput checks it,
  draws a row's runs only while their text equals the row, colours by the theme's
  `sigil.<role>` else the hex, and draws the selection, cursor and focus over it),
  every other TextInput field its default (`label ""`, so the key prefix is the one
  mark cell; `focused=None`). `EMPTY == "empty
  spec"` shows when the edit's rows are `("",)`. The app focuses `k + ("edit",)` to
  route the edit its keys: the input then draws its cursor cell and gives
  `cursor_at` (the terminal cursor) and `locate` (a click's text position), and the
  Block lifts.
- with `edit is None`: `Paragraph(READ_ONLY, role="muted")` (no id), `READ_ONLY ==
  "no spec loaded"`. Nothing in the pane takes keys. A highlight is not used (nor
  checked here: SpecDoc checked it).
`scroll` is TextInput's: `None` (the default: the view follows the cursor, a pure
function of the edit and the rect) or a pair `(sx, sy)` of ints `>= 0`, the first
column and row shown, kept by the app for a sticky scroll. It is checked here whether
or not there is an edit (so a state the app keeps is refused the same way either way)
and ignored without one.

Laws (a test can loop over specs, scrolls, sizes and contexts):
- pure: `specpane(s, sc) == specpane(s, sc)` for equal arguments (the edit by its
  own `==`); nothing is read but the arguments.
- ids: the ids carried are exactly `{k + ("spec",)}`, plus `k + ("edit",)` when
  `s.edit is not None`.
- edit: the TextInput holds the very edit object the spec holds (not a copy).
- highlight (S1): the TextInput's `runs` is the very highlight the spec holds (`is`;
  `None` when it has none or lacks the attribute); nothing else in the result
  depends on it (two specs differing only in `highlight` give Blocks differing only
  in the TextInput's `runs`).
- unchanged (S1, condition d): with `highlight` `None` (or absent), the pane's frames
  (Paint's cells, hits and the cursor) equal those of SpecPane at the commit before
  S1 (3ff3b8b, loaded by git through `tests/_gitref.py` at test time), for every
  spec, scroll, size and context.
- legible: with colour off (Caps depth 0), the placeholders are words; focus shows
  through the TextInput's `›` mark cell and its cursor cell, and the selection
  through `reverse` (TextInput's floors), the Block's focus border weight besides;
  with a highlight or without (syntax colours never carry meaning alone: the text is
  the same). A note is words (its `warn` colour adds nothing the words do not say).
- note (S2): nothing in the result but the Block's `title` depends on `s.note`
  (two specs differing only in `note` give Blocks differing only in `title`); ids,
  the child (TextInput or Paragraph, `scroll`, `runs`) and every other Block field
  never depend on it.
- note-none-unchanged (S2): with `note` `None` (or absent), the pane equals (`==`)
  SpecPane's at the commit before S2 (df0fa3c, loaded by git through
  `tests/_gitref.py` at test time), `kind` aside (R2: the Block's `kind="pane"` is
  left out of the comparison, the old Block having none), and so do its frames (Paint's cells, hits and the
  cursor), for every spec, scroll, size and context.
- layout-unchanged (S2): a note never moves the layout. The Block's `chrome()`
  counts a title only as `title != ""` (`_plain_of(self.title) != ""`), true with a
  note or without since `T` is never `""`, so Layout's BoxModel gives the same
  content rect and the child the same rect at every pane rect; the note changes
  only the cells of the title rect (row `R.y`, columns `[R.x + 2, R.right - 2)`),
  never a hit or the cursor. Only the Block's `measure("x")` grows (`need = tw + 6`
  counts the title's width, here by `2 + n`); OrchestratorTab never asks it (its
  layout law). An app placing the Block by its natural width (an `Auto` size, an
  anchor) would see the note's width there: outside this tab.
- note-cut-first (S2): at every pane rect, the drawn title is a prefix of
  `T + "  " + N` and the ellipsis (or the whole); no cell of `T` is dropped while a
  cell of the gap or of `N` is drawn, and `T` is whole exactly when `W >= t + 2 + e`
  (above).
- frames (S2): for every pane rect (`R.w`, `R.h` from 0), every valid note (one
  line, wide glyphs included, wider than the rect included) and every shelf theme,
  depth and focus, painting the pane never raises.

Inputs: `spec` a Board {SpecDoc} (or any value with `path` and `edit`, and
  optionally `highlight` and `note`); `scroll`
  `None` or a pair of ints `>= 0`.
Outputs: a Widgets `Block` holding a `TextInput` or a `Paragraph`.
Errors: `TypeError` when `spec` lacks `path` or `edit` (`"spec lacks 'path'"`, the
  first missing in that order), or `scroll` is neither `None` nor a `tuple` of two
  ints (a `bool` refused: `"scroll must be None or a pair of ints, got list"`);
  `ValueError` when a scroll value is negative (`"scroll values must be >= 0, got (0,
  -1)"`). An edit whose values TextInput refuses (a `line` outside its rows, ...),
  or a highlight it refuses (a spec value other than a SpecDoc, which checks it
  first), raises TextInput's own error (`runs...` messages), passed through. A note
  is not checked here (SpecDoc checks it); from a spec value other than a SpecDoc a
  non-`str` note raises Text's `Line.of` error (`TypeError("expected a str, Span or
  (str, style), got (5, 'warn')")`), passed through.
Effects: none.

Usage:
    from types import SimpleNamespace as Ed
    from cure.draw.views.board import SpecDoc
    from cure.draw.views.orchestratortab import specpane
    node = specpane.specpane(SpecDoc("cure.sigil", Ed(rows=("[A] -> [B]",), line=0,
                                                       column=0, selection=None)))
    node.title, node.children[0].id   # ("cure.sigil", ("orchestrator", "edit"))
    specpane.specpane(SpecDoc()).children[0].text   # "no spec loaded"
    specpane.specpane(SpecDoc("cure.sigil", note="sigil highlight: exited 1")).title
    # Line((Span("cure.sigil  ", None), Span("sigil highlight: exited 1", "warn")))
    specpane.specpane(SpecDoc(), scroll=(0, -1))    # ValueError: scroll values must be >= 0, got (0, -1)
"""

from cure.core.text import Line
from cure.draw.widgets import Block, Paragraph, TextInput

_K = ("orchestrator",)

UNTITLED = "spec"
"""The spec pane's title when the spec has no path."""

EMPTY = "empty spec"
"""The TextInput's placeholder, shown when the spec's text is empty."""

READ_ONLY = "no spec loaded"
"""What the spec pane says when there is no edit."""


def specpane(spec: object, scroll: "tuple[int, int] | None" = None) -> Block:
    """The spec pane: a Block titled with the path around a TextInput over the edit,
    or the read-only placeholder."""
    for name in ("path", "edit"):
        if not hasattr(spec, name):
            raise TypeError(f"spec lacks {name!r}")
    _check_scroll(scroll)
    title = spec.path if spec.path != "" else UNTITLED
    note = getattr(spec, "note", None)
    if note is not None:
        title = Line.of((title, None), ("  ", None), (note, "warn"))
    if spec.edit is None:
        child = Paragraph(READ_ONLY, role="muted")
    else:
        child = TextInput(spec.edit, placeholder=EMPTY, scroll=scroll,
                          runs=getattr(spec, "highlight", None), id=_K + ("edit",))
    return Block((child,), title=title, kind="pane", id=_K + ("spec",))


def _check_scroll(scroll: object) -> None:
    """Refuse a scroll that is neither `None` nor a pair of ints `>= 0`."""
    if scroll is None:
        return
    if not (type(scroll) is tuple and len(scroll) == 2
            and all(type(v) is int for v in scroll)):
        raise TypeError(f"scroll must be None or a pair of ints, got {type(scroll).__name__}")
    if min(scroll) < 0:
        raise ValueError(f"scroll values must be >= 0, got {scroll!r}")
