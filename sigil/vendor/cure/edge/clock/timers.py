"""[Timers]: a deadline heap: next due, what fired at `now` (pure).

Kind: service (a class with explicit state; pure: time comes in as an argument, never
read from a clock; no I/O). The app's loop asks it how long it may wait
(`due(now)`, the README's `term.read(timeout=clock.due(now))`) and, after waking, what
fired (`expired(now)`). Times are plain numbers in the app's own units (seconds of
`time.monotonic()` is the intent); only differences matter.

Data:
- `Timers()`: empty. State: for each key, its deadline `at`, its period `every` (or
  `None` for a one-shot), and the order it was (last) added in. `len(t)` is the number
  of keys; `key in t` whether a key is set.

The operations:
- `add(key, at, *, every=None) -> None`: set `key`'s deadline to `at`. `key` any
  hashable; adding a key already set replaces its deadline and period and moves it to
  the end of the add order. `every`: `None` (fires once) or a period > 0 (fires again
  every `every` after each deadline).
- `cancel(key) -> bool`: forget `key`; `True` when it was set, `False` otherwise.
- `next() -> float | None`: the earliest deadline, `None` when empty.
- `due(now) -> float | None`: how long the app may wait: `max(0.0, next() - now)` as a
  `float`, `None` when empty (wait for input only).
- `expired(now) -> tuple`: the keys whose deadline is `<= now`, each once, ordered by
  deadline, equal deadlines by add order. A one-shot key fired is removed. A repeating
  key fired at deadline `d` gets the deadline `d + k * every` for the smallest `k >= 1`
  that is `> now` (so a stalled loop gets one firing, not a burst, and the phase is
  kept), and stays in its add order. Nothing due: `()`.
- `due(timers, now)` (module function): `timers.due(now)`.

Inputs: `key` hashable; `at`, `now`, `every` real numbers (`int` or `float`).
Outputs: as each operation states.
Errors: `TypeError` when `at`, `now` or `every` is not a real number (a `bool` is
  refused; `every` may be `None`), or `key` is unhashable; `ValueError` when `at` or
  `now` is NaN or infinite, or `every` is not a finite number > 0. On an error the
  state is unchanged. `due(timers, now)`: `TypeError` when `timers` is not a `Timers`.
Effects: only the stated changes to the `Timers`' own state.

Usage:
    from cure.edge.clock.timers import Timers
    t = Timers()
    t.due(0.0)                      # None: nothing pending
    t.add("blink", 0.5, every=0.5)
    t.add("toast", 2.0)
    t.due(0.2)                      # 0.3
    t.expired(0.2)                  # ()
    t.expired(1.7)                  # ("blink",): next blink at 2.0, not a burst of three
    t.expired(2.0)                  # ("blink", "toast"): equal deadlines by add order
    "toast" in t                    # False: a one-shot is gone once fired
    t.cancel("blink")               # True; t.due(9.0) is None
"""


import math
from itertools import count


class Timers:
    """{Timers}: deadlines keyed by the caller; pure (see the module)."""

    def __init__(self) -> None:
        self._timers = {}
        self._order = count()

    def __len__(self) -> int:
        return len(self._timers)

    def __contains__(self, key) -> bool:
        return key in self._timers

    def add(self, key, at: float, *, every: "float | None" = None) -> None:
        """Set `key`'s deadline (and period); replaces a key already set."""
        hash(key)
        _check_time(at, "at")
        if every is not None:
            _check_time(every, "every")
            if every <= 0:
                raise ValueError(f"every must be > 0, got {every}")
        self._timers.pop(key, None)
        self._timers[key] = (at, every, next(self._order))

    def cancel(self, key) -> bool:
        """Forget `key`; whether it was set."""
        return self._timers.pop(key, None) is not None

    def next(self) -> "float | None":
        """The earliest deadline, or None when empty."""
        if not self._timers:
            return None
        return min(at for at, _, _ in self._timers.values())

    def due(self, now: float) -> "float | None":
        """Seconds until the earliest deadline (0.0 when overdue), or None when empty."""
        _check_time(now, "now")
        earliest = self.next()
        if earliest is None:
            return None
        return max(0.0, float(earliest - now))

    def expired(self, now: float) -> tuple:
        """The keys due by `now`, by deadline then add order; one-shots removed, repeats moved on."""
        _check_time(now, "now")
        fired = sorted(
            (at, order, key) for key, (at, _, order) in self._timers.items() if at <= now
        )
        for at, order, key in fired:
            every = self._timers[key][1]
            if every is None:
                del self._timers[key]
            else:
                self._timers[key] = (_next_after(at, every, now), every, order)
        return tuple(key for _, _, key in fired)


def due(timers: Timers, now: float) -> "float | None":
    """`timers.due(now)`."""
    if not isinstance(timers, Timers):
        raise TypeError(f"expected a Timers, got {type(timers).__name__}")
    return timers.due(now)


def _next_after(at: float, every: float, now: float) -> float:
    """`at + k * every` for the smallest k >= 1 that is > now."""
    k = max(1, math.floor((now - at) / every) + 1)
    while at + k * every <= now:
        k += 1
    return at + k * every


def _check_time(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a real number, got {type(value).__name__}")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value}")
