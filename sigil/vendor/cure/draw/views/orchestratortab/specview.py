"""[SpecView]: sigil's view of the spec: a Drawing of the rows the app gives, marked when stale.

Kind: service (pure functions from a {SpecDoc} and the app's viewport to a widget node;
see the OrchestratorTab package for the tab and its key `k == ("orchestrator",)`).

What it does: the `"view"` pane of construct's orchestrator tab. sigil's drawing of the
spec arrives as Buffer {Rows} (construct runs sigil and hands in the rows it drew):
they are shown through a Widgets `Drawing` at the viewport the app keeps and scrolls
(its offset passed in), inside a Block. When the spec changed since the rows were
drawn (`spec.stale`), the pane says so in words, on its first content row and in its
title. It composes existing widget nodes only and paints nothing itself; it never runs
sigil.

The {SpecDoc} is read by attribute (`spec.rows`, `spec.stale`): OrchestratorTab's
import grants do not include Views' `board/`, so any value with them serves, Board's
`SpecDoc` among them.

The title (`title(spec) -> str`): `TITLE == "sigil view"`, or `TITLE + STALE_TAG`
(`"sigil view (stale)"`) when `spec.stale`.

The pane (`specview(spec, at=(0, 0)) -> Block`):
`Block(children, title=title(spec), kind="pane", id=k + ("view",))`, every other
Block field its default (Column layout, `focused=None`; `kind="pane"`, R2, inert
until R3), where with `(x, y) = at`:
- `body` is `Drawing(spec.rows, x=x, y=y)` (Widgets' Drawing, its overflow marks on:
  a row cut on the right ends in the ellipsis, rows hidden above or below fold into
  the `↑N ↓M more` row, so nothing is cut silently; no id, no regions) when
  `spec.rows.lines` is not empty, else `Paragraph(NOT_DRAWN, role="muted")` (no id),
  `NOT_DRAWN == "not drawn yet"`;
- `children == (body,)` when not stale; when stale, `(Paragraph(STALE, role="warn",
  wrap=False, size=Fixed(1)), body)` (Layout's `Fixed`; Theme role `warn`, which an
  unknown theme degrades to its default), `STALE == "stale: the spec changed since
  this view was drawn"`. The stale row takes the content's first row, so at one
  content row it is the row shown.
`at` is the viewport: the content cell `(x, y)` shown at the body's top-left, a pair of
ints `>= 0` the app keeps (arrow keys or the wheel while the pane is focused move it;
the app clamps it as it likes: a viewport past the rows' end shows Drawing's `↑N
more`, never an error). The app focuses `k + ("view",)` (the Block) to scroll it.

Laws (a test can loop over specs, viewports, sizes and contexts):
- pure: `specview(s, at) == specview(s, at)` and `title(s) == title(s)` for equal
  arguments; nothing is read but the arguments.
- ids: the only id carried is `k + ("view",)`.
- viewport: changing `at` changes nothing in the tree but the Drawing's `x` and `y`.
- legible: with colour off (Caps depth 0), the stale mark is words: whenever the
  pane is stale and its content rect is at least 6 cells wide and 1 row high, the word
  `stale` is drawn on the content's first row (`"stale…"` at width 6); the title
  says `(stale)` whenever the Block draws its title whole.

Inputs: `spec` a Board {SpecDoc} (or any value with `rows`, a Buffer {Rows}, and
  `stale`, a `bool`); `at` a pair of ints `>= 0`.
Outputs: a Widgets `Block` holding a `Drawing` or a `Paragraph`, after a stale row
  (a `Paragraph`) when stale; a `str` title.
Errors: `TypeError` when `spec` lacks `rows` or `stale` (`"spec lacks 'rows'"`, the
  first missing in that order), or `at` is not a `tuple` of two ints (a `bool`
  refused: `"at must be a pair of ints, got list"`); `ValueError` when a value of `at`
  is negative (`"at values must be >= 0, got (-1, 0)"`). Rows of the wrong type are
  refused by Widgets' Drawing (its own `TypeError`, passed through; a Board `SpecDoc`
  never holds them).
Effects: none.

Usage:
    from cure.core.buffer import Rows
    from cure.draw.views.board import SpecDoc
    from cure.draw.views.orchestratortab import specview
    s = SpecDoc("cure.sigil", rows=Rows.of(["[Views] -> [Widgets]", "  [Board]"]), stale=True)
    node = specview.specview(s, at=(0, 1))
    node.title                        # "sigil view (stale)"
    node.children[0].text             # "stale: the spec changed since this view was drawn"
    node.children[1].y                # 1
"""

from cure.draw.layout import Fixed
from cure.draw.widgets import Block, Drawing, Paragraph

_K = ("orchestrator",)

TITLE = "sigil view"
"""The view pane's title."""

STALE_TAG = " (stale)"
"""What the title gains while the view is stale."""

STALE = "stale: the spec changed since this view was drawn"
"""The view pane's first content row while the view is stale."""

NOT_DRAWN = "not drawn yet"
"""What the view pane says before sigil's first drawing."""


def title(spec: object) -> str:
    """The view pane's title: `"sigil view"`, with `" (stale)"` while stale."""
    if not hasattr(spec, "stale"):
        raise TypeError("spec lacks 'stale'")
    return TITLE + STALE_TAG if spec.stale else TITLE


def specview(spec: object, at: "tuple[int, int]" = (0, 0)) -> Block:
    """The view pane: a Block around a Drawing of `spec.rows` at viewport `at`, after
    the stale row when stale."""
    for name in ("rows", "stale"):
        if not hasattr(spec, name):
            raise TypeError(f"spec lacks {name!r}")
    _check_at(at)
    x, y = at
    rows = spec.rows
    if hasattr(rows, "lines") and not rows.lines:
        body = Paragraph(NOT_DRAWN, role="muted")
    else:
        body = Drawing(rows, x=x, y=y)  # Drawing refuses rows of the wrong type
    if spec.stale:
        children = (Paragraph(STALE, role="warn", wrap=False, size=Fixed(1)), body)
    else:
        children = (body,)
    return Block(children, title=title(spec), kind="pane", id=_K + ("view",))


def _check_at(at: object) -> None:
    """Refuse a viewport that is not a pair of ints `>= 0`."""
    if not (type(at) is tuple and len(at) == 2 and all(type(v) is int for v in at)):
        raise TypeError(f"at must be a pair of ints, got {type(at).__name__}")
    if min(at) < 0:
        raise ValueError(f"at values must be >= 0, got {at!r}")
