"""[Tween]: a value at `now`: from `start` to `end` over `duration` on an easing curve;
done at the end, exactly the end value (pure).

Kind: service (a frozen dataclass and pure functions; no state, no clock read, no
I/O). The app holds a `Tween` and, on each frame, hands `value(tween, now)` to a node's
field (a fraction, a knob's place). `now` is always a parameter, in the app's own units
(seconds of `time.monotonic()` is the intent; only differences matter), as for
[Timers] and [Playback]. Reduced motion is the app passing `duration=0`: such a tween
is done, and `end`, at every `now >= at`. With no live tween the app's loop waits on
input alone: `due` is `None` then (`@inv idle([Tween])`).

Data:
- `EASES = ("linear", "in", "out", "in-out", "steps")`: the easing curves.
- `Tween(start, end, at, duration, ease="linear", *, steps=None)`: frozen (its fields
  cannot be set; equal fields are an equal `Tween`). `start`, `end`: the values it
  runs between, each an `int` or a `float`; `at`: the `now` it began; `duration`: how
  long it runs, `>= 0`; `ease`: one of `EASES`; `steps`: the number of equal steps,
  an `int >= 1`, given with `ease="steps"` only (required there, refused elsewhere).

The curves, `c(p)` for the progress `p` in the open interval (0, 1) (each is monotone
non-decreasing and within [0, 1]; the quadratic family):
- `"linear"`: `c(p) = p`.
- `"in"`: `c(p) = p * p` (slow start).
- `"out"`: `c(p) = 1 - (1 - p) * (1 - p)` (slow end; the mirror of `"in"`).
- `"in-out"`: `c(p) = 2 * p * p` when `p < 0.5`, else `1 - 2 * (1 - p) * (1 - p)`.
- `"steps"`: `c(p) = floor(p * steps) / steps` (holds `start` for the first step, so
  `end` is reached only at done: `steps` changes in all, the last at done).

The operations:
- `value(tween, now) -> int | float`: in this order (the first that holds):
  1. `now >= at + duration`: `end`, the object given (`is`), for every ease (so a
     tween of `duration` 0 is `end` at every `now >= at`, `now == at` included);
  2. `now <= at`: `start`, the object given (`is`);
  3. otherwise (`duration > 0` and `at < now < at + duration`): with `p = (now - at) /
     duration`, the `float` `float(start) + (float(end) - float(start)) * c(p)`,
     clamped to `[min(start, end), max(start, end)]` (so float rounding never leaves
     the interval). An `int` `start` and `end` give a `float` between, and the `int`
     objects themselves at rule 1 and rule 2.
  Over `now`, the value is monotone (non-decreasing when `start <= end`,
  non-increasing otherwise) and within `[min(start, end), max(start, end)]`.
- `done(tween, now) -> bool`: `now >= at + duration` (rule 1: `value` is `end`).
- `due(tweens, now, *, frame=0.0) -> float | None`: how long the app may wait before a
  live tween next changes value (for Wait's timeout; the app waits the `min` of this,
  [Timers]' `due` and [Playback]'s). A tween is live at `now` when it is not
  `done(tween, now)`. `None` when no tween in `tweens` is live (the idle rule; an
  empty `tweens` included). Otherwise the `min`, over the live tweens, of each one's
  wait, a `float >= 0.0`:
  - `now < at` (not begun): `at - now` for a continuous ease; for `"steps"`, the time
    to its first step, `at + duration / steps - now`.
  - begun, a continuous ease (`"linear"`, `"in"`, `"out"`, `"in-out"`): it changes at
    every instant, so the app paces it: `min(frame, at + duration - now)` (`frame`,
    the app's frame interval; the default `0.0` means "draw again now"; the end is
    never waited past).
  - begun, `"steps"`: with `k = floor(p * steps)` (as `value` computes it), the time
    to the next step, `at + (k + 1) * duration / steps - now`; the last step is at
    `at + duration` (done). `frame` does not apply.
  Each wait is `max(0.0, ...)`: never negative, so the `now` it names is never
  earlier than `now`. (Float rounding can make a step land a hair after the time
  `due` names; `due` is then `0.0` again until `now` passes it, never negative.)

Inputs: `tween` a `Tween`; `tweens` an iterable of `Tween`s (read once); `start`, `end`
  `int` or `float`; `at`, `duration`, `now`, `frame` real numbers (`int` or `float`); a
  `bool` is refused wherever a number is meant.
Outputs: as each operation states.
Errors:
- `Tween(...)`: `TypeError` when `start`, `end`, `at` or `duration` is not an `int` or
  `float` (a `bool` refused), `ease` is not a `str`, or `steps` is neither `None` nor
  an `int` (a `bool` refused); `ValueError` when any of `start`, `end`, `at`,
  `duration` is NaN or infinite, `duration < 0`, `ease` is not in `EASES`, `ease ==
  "steps"` and `steps is None`, `ease != "steps"` and `steps is not None`, or `steps <
  1`.
- `value`, `done`: `TypeError` when `tween` is not a `Tween` or `now` is not a real
  number; `ValueError` when `now` is NaN or infinite.
- `due`: as `value` for `now` and for each item of `tweens`, and for `frame`
  (`TypeError` when not a real number; `ValueError` when NaN, infinite or `< 0`);
  `TypeError` when `tweens` is not iterable.

Effects: none.

Invariant: idle — no tick while nothing moves: with no live tween `due` is `None`, so the
  app's loop waits on input alone (Wait's timeout comes only from live tweens and timers).

Laws (a test loops over tweens, eases and `now`s):
- pure: the same arguments give the same result (`==`, and the same type).
- exact end: for every ease, `value(t, now) is t.end` whenever `done(t, now)`.
- duration 0: `value(t, now) is t.end` at every `now >= t.at`; `t.start` before.
- monotone and bounded: over increasing `now`, `value` moves one way only, within
  `[min(start, end), max(start, end)]`.
- idle: `due(ts, now) is None` exactly when no `t` in `ts` is live at `now`.
- `due` never negative: `due(ts, now) >= 0.0` when not `None`.

Usage:
    from cure.edge.clock.tween import Tween, value, done, due
    t = Tween(0, 10, at=1.0, duration=2.0)           # linear, 0 -> 10 over [1, 3]
    value(t, 0.5)                                    # 0 (the int given: not begun)
    value(t, 2.0)                                    # 5.0
    value(t, 3.0)                                    # 10 (the int given: done)
    done(t, 3.0)                                     # True
    due([t], 2.0, frame=1 / 30)                      # 0.0333...: draw the next frame
    due([t], 3.0)                                    # None: idle, wait on input alone
    s = Tween(0.0, 1.0, 0.0, 1.0, "steps", steps=4)
    value(s, 0.3)                                    # 0.25
    due([s], 0.3)                                    # 0.2: the next step at 0.5
    value(Tween(0.0, 1.0, 5.0, 0), 5.0)              # 1.0: reduced motion, done at once
"""

import math
from collections.abc import Iterable
from dataclasses import KW_ONLY, dataclass

EASES = ("linear", "in", "out", "in-out", "steps")


@dataclass(frozen=True)
class Tween:
    """{Tween}: start, end, at, duration, ease, steps; validated (see the module)."""

    start: "int | float"
    end: "int | float"
    at: "int | float"
    duration: "int | float"
    ease: str = "linear"
    _: KW_ONLY
    steps: "int | None" = None

    def __post_init__(self) -> None:
        """Validate the fields; raise as the module's Errors state."""
        for name in ("start", "end", "at", "duration"):
            _check_real(getattr(self, name), name)
        if not isinstance(self.ease, str):
            raise TypeError(f"ease must be a str, got {type(self.ease).__name__}")
        if self.steps is not None and (isinstance(self.steps, bool)
                                       or not isinstance(self.steps, int)):
            raise TypeError(f"steps must be None or an int, got {type(self.steps).__name__}")
        if self.duration < 0:
            raise ValueError(f"duration must be >= 0, got {self.duration}")
        if self.ease not in EASES:
            raise ValueError(f"ease must be one of {EASES}, got {self.ease!r}")
        if self.ease == "steps" and self.steps is None:
            raise ValueError("steps is required with ease='steps'")
        if self.ease != "steps" and self.steps is not None:
            raise ValueError(f"steps is given with ease='steps' only, got ease={self.ease!r}")
        if self.steps is not None and self.steps < 1:
            raise ValueError(f"steps must be >= 1, got {self.steps}")


def value(tween: Tween, now: "int | float") -> "int | float":
    """The tween's value at `now` (see the module's rules 1 to 3)."""
    if done(tween, now):                          # checks tween and now
        return tween.end                          # rule 1: the object given
    if now <= tween.at:
        return tween.start                        # rule 2: the object given
    p = (now - tween.at) / tween.duration         # rule 3: duration > 0 here
    lo, hi = float(tween.start), float(tween.end)
    v = lo + (hi - lo) * _curve(tween, p)
    return min(max(v, min(lo, hi)), max(lo, hi))  # rounding never leaves the interval


def done(tween: Tween, now: "int | float") -> bool:
    """Whether `now >= tween.at + tween.duration`."""
    if not isinstance(tween, Tween):
        raise TypeError(f"expected a Tween, got {type(tween).__name__}")
    _check_real(now, "now")
    return now >= tween.at + tween.duration


def due(tweens: Iterable[Tween], now: "int | float", *,
        frame: "int | float" = 0.0) -> "float | None":
    """How long the app may wait before a live tween next changes; None when idle."""
    _check_real(now, "now")
    _check_real(frame, "frame")
    if frame < 0:
        raise ValueError(f"frame must be >= 0, got {frame}")
    try:
        items = iter(tweens)                      # read once
    except TypeError:
        raise TypeError(f"tweens must be iterable, got {type(tweens).__name__}") from None
    waits = [_wait(t, now, frame) for t in items if not done(t, now)]
    return min(waits) if waits else None


def _wait(tween: Tween, now: "int | float", frame: "int | float") -> float:
    """A live tween's wait until it next changes value (see `due`)."""
    at, duration = tween.at, tween.duration
    if tween.ease == "steps":
        if now < at:
            nxt = at + duration / tween.steps     # its first step
        else:
            k = math.floor((now - at) / duration * tween.steps)  # as `value` computes it
            nxt = at + (k + 1) * duration / tween.steps
        return max(0.0, float(nxt - now))
    if now < at:
        return max(0.0, float(at - now))
    return max(0.0, float(min(frame, at + duration - now)))  # the end never waited past


def _curve(tween: Tween, p: float) -> float:
    """`c(p)` for the tween's ease, `p` in (0, 1)."""
    ease = tween.ease
    if ease == "linear":
        return p
    if ease == "in":
        return p * p
    if ease == "out":
        return 1 - (1 - p) * (1 - p)
    if ease == "in-out":
        return 2 * p * p if p < 0.5 else 1 - 2 * (1 - p) * (1 - p)
    return math.floor(p * tween.steps) / tween.steps  # "steps"


def _check_real(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be an int or a float, got {type(value).__name__}")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value}")
