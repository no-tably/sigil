"""[Playback]: a frame player: speeds, step, seek; skips overdue frames to keep
wall-clock pace (pure).

Kind: service (a class with explicit state, and a pure function). Time comes in as
`now` on every call that needs it; nothing reads a clock or does I/O. Ported from
sigil's viewer (`SimPlayer`'s play / pause / step / advance / wait), generic over a run
of `last + 1` frames. An animation's phase comes from the tick: `frame_at` gives the
frame a looping animation shows at `now` with no state at all.

Data:
- `SPEEDS = (0.25, 0.5, 1, 2, 4, 8, 16, 32)`: frames a second, the steps an app's
  `-` / `+` keys may move through (sigil starts at 2).
- `Playback(last, *, fps=2.0, at=0, loop=False)`: a run of frames `0..last`, showing
  frame `at`, paused, at `fps` frames a second; `loop` plays on from frame 0 after the
  last instead of pausing there. Read-only attributes: `last`, `at` (the frame shown),
  `fps`, `interval` (`1 / fps`), `playing` (`bool`), `loop`, `due_at` (when the next
  frame shows, while playing; `None` when paused).

The operations (each returning whether the frame shown changed, unless stated):
- `play(now) -> bool`: play from here; when not looping and `at == last`, start over
  at 0 first. `playing` true, `due_at = now + interval`.
- `pause() -> bool`: stop; `due_at` `None`. Returns whether it was playing (the frame
  never changes).
- `toggle(now) -> bool`: `pause()` when playing (returns `False`), else `play(now)`.
- `step(delta) -> bool`: pause, then move `delta` frames (an `int`, either sign):
  clamped to `0..last`, or, when looping, wrapped modulo `last + 1`.
- `seek(frame, now) -> bool`: show `frame` clamped to `0..last` (a negative frame is 0,
  past the end is `last`), playing or paused as before; while playing,
  `due_at = now + interval` (the frame gets its full time).
- `speed(fps, now) -> None`: set `fps`; while playing, `due_at = now + 1 / fps`.
- `advance(now) -> bool`: when playing and `now >= due_at`: `behind = int((now -
  due_at) / interval)` frames are overdue and are skipped, so the run keeps
  wall-clock pace however slowly frames are drawn: `at` becomes
  `min(at + 1 + behind, last)` (looping: `(at + 1 + behind) % (last + 1)`), `due_at =
  now + interval`, and when not looping `playing` becomes `at < last` (it pauses on
  the last frame). Returns `True` then (a new frame is due to be drawn); `False` when
  paused or not yet due (nothing changes).
- `due(now) -> float | None`: seconds until the next frame, `max(due_at - now, 0.0)`,
  while playing; `None` when paused. The app's loop waits `min` of this and
  [Timers]' `due`.

`frame_at(start, now, fps, count, *, loop=True) -> int` (pure): the frame an animation
of `count` frames started at `start` shows at `now`: `n = floor((now - start) * fps)`,
`0` when `n < 0`; looping `n % count`, else `min(n, count - 1)`.

Inputs: `last`, `at`, `delta`, `frame`, `count` ints; `fps`, `now`, `start` real
  numbers; `loop` a `bool`.
Outputs: as each operation states.
Errors: `TypeError` when an int argument is not an `int`, a time or `fps` is not a real
  number, or `loop` is not a `bool` (a `bool` is refused wherever a number is meant);
  `ValueError` when `last` < 0, `at` is outside `0..last`, `count` < 1, `fps` is not a
  finite number > 0, or a time is NaN or infinite. On an error the state is unchanged.
Effects: only the stated changes to the `Playback`'s own state.

Usage:
    from cure.edge.clock.playback import Playback, frame_at
    p = Playback(9, fps=2.0)        # frames 0..9, paused at 0
    p.due(0.0)                      # None: paused
    p.play(0.0)                     # False; due_at == 0.5
    p.advance(0.4)                  # False: not yet
    p.advance(0.5)                  # True; p.at == 1, due_at == 1.0
    p.advance(2.0)                  # True; 2 frames overdue skipped: p.at == 4
    p.step(-1)                      # True; paused at 3
    p.seek(99, 3.0)                 # True; p.at == 9
    frame_at(0.0, 1.3, 10, 4)       # 1: floor(13) % 4
"""

import math

SPEEDS = (0.25, 0.5, 1, 2, 4, 8, 16, 32)


class Playback:
    """{Playback}: a frame player over frames 0..last; pure (see the module)."""

    def __init__(self, last: int, *, fps: float = 2.0, at: int = 0, loop: bool = False) -> None:
        _check_int(last, "last")
        _check_int(at, "at")
        _check_fps(fps)
        _check_bool(loop, "loop")
        if last < 0:
            raise ValueError(f"last must be >= 0, got {last}")
        if not 0 <= at <= last:
            raise ValueError(f"at must be in 0..{last}, got {at}")
        self._last = last
        self._at = at
        self._fps = fps
        self._loop = loop
        self._due_at = None

    @property
    def last(self) -> int:
        """The last frame's index."""
        return self._last

    @property
    def at(self) -> int:
        """The frame shown."""
        return self._at

    @property
    def fps(self) -> float:
        """Frames a second."""
        return self._fps

    @property
    def interval(self) -> float:
        """Seconds a frame: `1 / fps`."""
        return 1 / self._fps

    @property
    def playing(self) -> bool:
        """Playing (else paused)."""
        return self._due_at is not None

    @property
    def loop(self) -> bool:
        """Plays on from frame 0 after the last."""
        return self._loop

    @property
    def due_at(self) -> "float | None":
        """When the next frame shows, while playing; None when paused."""
        return self._due_at

    def play(self, now: float) -> bool:
        """Play from here (from 0 when at the last frame and not looping)."""
        _check_time(now, "now")
        before = self._at
        if not self._loop and self._at == self._last:
            self._at = 0
        self._due_at = now + self.interval
        return self._at != before

    def pause(self) -> bool:
        """Stop; whether it was playing."""
        was = self.playing
        self._due_at = None
        return was

    def toggle(self, now: float) -> bool:
        """Pause when playing, else play."""
        if self.playing:
            self.pause()
            return False
        return self.play(now)

    def step(self, delta: int) -> bool:
        """Pause and move `delta` frames (clamped, or wrapped when looping)."""
        _check_int(delta, "delta")
        self.pause()
        if self._loop:
            return self._show((self._at + delta) % (self._last + 1))
        return self._show(self._clamp(self._at + delta))

    def seek(self, frame: int, now: float) -> bool:
        """Show `frame`, clamped; playing or paused as before."""
        _check_int(frame, "frame")
        _check_time(now, "now")
        if self.playing:
            self._due_at = now + self.interval
        return self._show(self._clamp(frame))

    def speed(self, fps: float, now: float) -> None:
        """Set the frames a second."""
        _check_fps(fps)
        _check_time(now, "now")
        self._fps = fps
        if self.playing:
            self._due_at = now + self.interval

    def advance(self, now: float) -> bool:
        """When due, show the next frame, skipping overdue ones to keep the pace."""
        _check_time(now, "now")
        if not self.playing or now < self._due_at:
            return False
        behind = int((now - self._due_at) / self.interval)
        ahead = self._at + 1 + behind
        if self._loop:
            self._at = ahead % (self._last + 1)
            self._due_at = now + self.interval
        else:
            self._at = min(ahead, self._last)
            self._due_at = now + self.interval if self._at < self._last else None
        return True

    def due(self, now: float) -> "float | None":
        """Seconds until the next frame while playing; None when paused."""
        _check_time(now, "now")
        if not self.playing:
            return None
        return max(self._due_at - now, 0.0)

    def _clamp(self, frame: int) -> int:
        return min(max(frame, 0), self._last)

    def _show(self, frame: int) -> bool:
        changed = frame != self._at
        self._at = frame
        return changed


def frame_at(start: float, now: float, fps: float, count: int, *, loop: bool = True) -> int:
    """The frame an animation of `count` frames started at `start` shows at `now` (pure)."""
    _check_time(start, "start")
    _check_time(now, "now")
    _check_fps(fps)
    _check_int(count, "count")
    _check_bool(loop, "loop")
    if count < 1:
        raise ValueError(f"count must be >= 1, got {count}")
    n = math.floor((now - start) * fps)
    if n < 0:
        return 0
    return n % count if loop else min(n, count - 1)


def _check_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")


def _check_bool(value: object, name: str) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a bool, got {type(value).__name__}")


def _check_time(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a real number, got {type(value).__name__}")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value}")


def _check_fps(fps: object) -> None:
    _check_time(fps, "fps")
    if fps <= 0:
        raise ValueError(f"fps must be > 0, got {fps}")
