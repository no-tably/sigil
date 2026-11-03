"""[Plan]: retained drawing for animation: repaint only what moved; a per-drawing slot
keyed by the caller, with an explicit epoch (a theme change).

Kind: service (two mutable classes and a function).

What it does: what a caller that draws frame after frame (a sigil view playing a
run, a construct pane) keeps between its frames. A `Memo` holds a `Plan` per
drawing, found by a KEY the caller names (its view, options, width), the objects the
drawing is OF (`holds`: compared by identity) and an EPOCH the caller bumps when
everything kept must go (a theme or a dialect applied: what was kept is drawn in the
colours of then). cure keeps no epoch of its own and reads no global. A `Plan` holds
what is worked out once per drawing (`held`, see [Held]) and the slots one compose
fills in order, so the next frame's compose finds each where the last one left it.

`Plan()` (mutable). Its state: `held` (a `dict` the plan's users fill; [Held]'s
`held` and `keep` keep their values in it) and a list of slots with a cursor.
- `begin() -> Plan`: starts a compose: the next `slot()` is the first again. Returns
  the plan itself.
- `slot() -> dict`: the next slot of this compose: a new `{}` the first time a
  compose reaches that position, the same `dict` object on every later compose.
- `sub(name) -> Plan`: the plan of one way of drawing (a step of a wrap ladder, taken
  on some frames only), with slots of its own: created the first time, kept in
  `held` under the key `("sub", name)`, and returned begun (the same `Plan` object
  for the same `name`).

`Memo(keep=8)` (mutable): the plans of the `keep` most recently used drawings.
- `plan(key, holds=(), *, epoch=0) -> Plan`: the plan whose `epoch == epoch`,
  `key == key`, and `holds` of the same length, each item the same object (`is`) as
  the given one's; it becomes the most recently used, and is returned begun. When
  there is none, a new `Plan` is made, kept as the most recently used, and the least
  recently used are dropped beyond `keep`; it is returned begun. So a plan of another
  epoch is never returned: bumping the epoch starts every drawing afresh.
- `invalidate() -> None`: forget every plan.
- `len(memo)`: the number of plans kept (at most `keep`).
- `slot(plan) -> dict | None` (a module function): `plan.slot()`; `None` when `plan`
  is `None` (a drawing made without a memo).

The caller's rule (not checked here): a plan only saves work, so a drawing composed
with a `Memo` must be the drawing composed without one; [Retained] and [Held] keep it
for what they hold (kept_same, only_what_moved).

Inputs: `key`, `epoch`: any values compared with `==`; `holds`: a tuple (any
  sequence, read as a tuple); `name`: any hashable; `keep`: an int >= 1.
Outputs: as stated.
Errors: `Memo(keep)`: `TypeError` when `keep` is not an `int` (a `bool` included),
  `ValueError` when it is below 1. `slot(plan)`: `TypeError` when `plan` is neither
  `None` nor a `Plan`.
Effects: only the stated changes to the memo and plans themselves.

Usage:
    from cure.draw.memo.plan import Memo, Plan, slot
    memo, doc = Memo(), object()
    p = memo.plan(("graph", 80), (doc,), epoch=1)
    s = p.slot(); s["laid"] = True
    memo.plan(("graph", 80), (doc,), epoch=1) is p      # True
    p.slot() is s                                       # True: begun again
    memo.plan(("graph", 80), (doc,), epoch=2) is p      # False: a theme change
    slot(None)                                          # None
"""

from collections.abc import Hashable


class Plan:
    """One drawing's plan: what is held once, and the slots one compose fills in order (mutable)."""

    def __init__(self) -> None:
        self._held: dict = {}
        self._slots: list = []
        self._next = 0

    @property
    def held(self) -> dict:
        """What is worked out once per plan, by name."""
        return self._held

    def begin(self) -> "Plan":
        """Start a compose: slots are handed out from the first again; returns self."""
        self._next = 0
        return self

    def slot(self) -> dict:
        """The next slot of this compose: {} the first time, the same dict later."""
        if self._next == len(self._slots):
            self._slots.append({})
        self._next += 1
        return self._slots[self._next - 1]

    def sub(self, name: Hashable) -> "Plan":
        """The begun sub-plan of one way of drawing, kept under ("sub", name)."""
        key = ("sub", name)
        if key not in self._held:
            self._held[key] = Plan()
        return self._held[key].begin()


class Memo:
    """The plans of the most recently used drawings, keyed by the caller, with an explicit epoch (mutable)."""

    def __init__(self, keep: int = 8) -> None:
        if isinstance(keep, bool) or not isinstance(keep, int):
            raise TypeError(f"keep must be an int, got {type(keep).__name__}")
        if keep < 1:
            raise ValueError(f"keep must be >= 1, got {keep}")
        self._keep = keep
        self._plans: list = []

    def plan(self, key: object, holds: tuple = (), *, epoch: object = 0) -> Plan:
        """The begun plan for (epoch, key, holds by identity); a new one when none (see the module)."""
        holds = tuple(holds)
        for i, entry in enumerate(self._plans):
            if _matches(entry, key, holds, epoch):
                self._plans.append(self._plans.pop(i))
                return entry[3].begin()
        self._plans.append((epoch, key, holds, Plan()))
        del self._plans[:-self._keep]
        return self._plans[-1][3]

    def invalidate(self) -> None:
        """Forget every plan."""
        self._plans.clear()

    def __len__(self) -> int:
        return len(self._plans)


def slot(plan: "Plan | None") -> "dict | None":
    """`plan.slot()`, or None without a plan."""
    if plan is None:
        return None
    if not isinstance(plan, Plan):
        raise TypeError(f"expected a Plan or None, got {type(plan).__name__}")
    return plan.slot()


def _matches(entry: tuple, key: object, holds: tuple, epoch: object) -> bool:
    """An entry (epoch, key, holds, plan) is this drawing's: equal epoch and key, the same objects held."""
    old_epoch, old_key, old_holds, _ = entry
    return (old_epoch == epoch and old_key == key and len(old_holds) == len(holds)
            and all(a is b for a, b in zip(old_holds, holds)))
