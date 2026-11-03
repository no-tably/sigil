"""[Held]: kept rows, spliced and patched.

Kind: service (pure-in-arguments functions over a [Plan]).

What it does: what a drawing works out once per plan and keeps for every later frame:
any value (`held`: its scene, the choices its wrap ladder made) and, above all, its
canvas kept with its rows worked out ([Canvas]' {Kept}, through Canvas's `keep`), so a
frame changes it only by splicing or patching the rows and cells that moved
(`Kept.splice` / `Kept.patch`, or [Retained]'s `repaint`) and by one-frame sprites
(Canvas's `overlay` / `undo`).

- `held(plan, name, make)`: `make()`, worked out once per plan: the first call for a
  `name` calls `make()` and keeps its result in `plan.held[name]`; every later call
  returns that same object without calling `make`. With `plan` `None` (no memo),
  `make()` each time.
- `keep(plan, name, make) -> Kept` ({Canvas} => {Kept}): the plan's kept canvas
  `name`: the first call calls `make()` (which returns a {Canvas}), keeps it with
  Canvas's `keep` and holds the `Kept` in `plan.held` under the key `("kept", name)`;
  every later call returns that same `Kept` (the one the last frame spliced, patched
  and overlaid) without calling `make`. With `plan` `None`, Canvas's `keep(make())`
  (`cure.draw.canvas.keep`) each time.

Inputs: `plan`: a [Plan] `Plan` or `None`; `name`: any hashable; `make`: a callable of
  no arguments (for `keep`, returning a {Canvas}).
Outputs: `held`: what `make` returned. `keep`: a {Kept}.
Errors: `TypeError` when `plan` is neither `None` nor a `Plan`, `make` is not
  callable, or (`keep`) `make()` returns something that is not a `Canvas`; what `make`
  raises propagates, and then nothing is held.
Effects: only the stated writes to `plan.held`.

Usage:
    from cure.draw.memo.plan import Memo
    from cure.draw.memo.held import held, keep
    from cure.draw.canvas import Canvas, Kept
    p = Memo().plan("view")
    held(p, "scene", lambda: [1]) is held(p, "scene", lambda: [2])   # True
    k = keep(p, "base", Canvas)
    isinstance(k, Kept), keep(p, "base", Canvas) is k              # (True, True)
"""

from collections.abc import Callable, Hashable

from cure.draw.canvas import Canvas, Kept
from cure.draw.canvas import keep as _keep_canvas

from .plan import Plan


def held(plan: "Plan | None", name: Hashable, make: Callable[[], object]) -> object:
    """`make()` once per plan, kept under `name`; each time without a plan."""
    _check(plan, make)
    if plan is None:
        return make()
    if name not in plan.held:
        plan.held[name] = make()
    return plan.held[name]


def keep(plan: "Plan | None", name: Hashable, make: "Callable[[], Canvas]") -> Kept:
    """The plan's kept canvas `name`, made and kept once (see the module)."""
    _check(plan, make)
    return held(plan, ("kept", name), lambda: _kept(make))


def _kept(make: "Callable[[], Canvas]") -> Kept:
    canvas = make()
    if not isinstance(canvas, Canvas):
        raise TypeError(f"make must return a Canvas, got {type(canvas).__name__}")
    return _keep_canvas(canvas)


def _check(plan: object, make: object) -> None:
    if plan is not None and not isinstance(plan, Plan):
        raise TypeError(f"expected a Plan or None, got {type(plan).__name__}")
    if not callable(make):
        raise TypeError(f"make must be callable, got {type(make).__name__}")
