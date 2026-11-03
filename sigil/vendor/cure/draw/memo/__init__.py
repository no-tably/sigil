"""[Memo]: retained drawing for an app's animated canvas.

Kind: system (the expansion of [Memo] in Draw). Depends on Canvas only: it keeps
canvases with Canvas's `keep` and splices and draws them through the `Kept` canvas's
own methods; it imports no other cure package (the rows it gives are Text `Line`s, as
Canvas's `rows` gives them; a charset is passed through to Canvas, untouched).

Retained drawing for animation: repaint only what moved. [Plan] holds a plan per
drawing, keyed by the caller with an explicit epoch (a theme change starts every
drawing afresh); [Held] keeps what a plan works out once, its canvas above all, kept
with its rows ({Canvas} => {Kept}); [Retained] repaints only the rows of the elements
whose look changed ({Looks} => {Rows}). The pattern that makes it work is the
caller's: reserve widths over the whole animation (pad every badge to its widest over
the run) so the layout holds still and only looks change.

The boundary: `[Memo] -> [Canvas] : keep({Canvas}) => {Kept}`: Memo calls Canvas's
`keep` (`cure.draw.canvas.keep`, through [Held]'s `keep` and `Retained`). Memo
defines no op another system calls; its classes and functions are for apps.

Re-exported for consumers: `Memo`, `Plan`, `slot` (plan); `held`, `keep` (held: the
plan's kept canvas, NOT Canvas's `keep`, which it calls); `Looks`, `Retained`,
`moved`, `repaint` (retained).

Effects: none outside the memo, plans and retained drawings the caller holds.

Usage (a sketch: `doc`, `run`, `theme_epoch`, `lay_out`, `looks_at`, `paint`, `tick`
and `charset` are the app's):
    from cure.draw.memo import Memo, held, keep, Retained, repaint
    memo = Memo()
    plan = memo.plan(("flow", 120), (doc, run), epoch=theme_epoch)   # the caller's key
    base = keep(plan, "base", lambda: lay_out(doc))                  # laid out once
    r = held(plan, "retained", lambda: Retained(base, looks_at(0)))
    rows = repaint(r, looks_at(tick), lambda ys: paint(doc, tick, ys), charset)
"""

from .held import held, keep
from .plan import Memo, Plan, slot
from .retained import Looks, Retained, moved, repaint
