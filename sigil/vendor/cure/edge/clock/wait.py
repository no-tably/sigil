"""[Wait]: time and waiting as tools: `now` comes from the app, no loop here; wait on the
tty, a self-pipe, ptys, sockets until one is ready or the timeout (`@timeout(due)`).

Kind: service (one function and its result type). The one place in Clock that blocks:
`select` waits on fds with `select.poll` for at most the timeout the app passes (from
[Timers]' `due(now)`, or [Playback]'s), and returns which fds are ready. A waited-on fd
that went away is the shared {Closed}, returned (never raised).

Data:
- `Ready(read=(), write=())` ({Ready}): `read` the fds ready to read, `write` the fds
  ready to write, each a tuple of ints in the order the caller gave them. `bool(ready)`
  is true when either holds an fd; `Ready()` (falsy) means the timeout passed.
  Equality field by field.

`select(fds, timeout=None, *, write=()) -> Ready | Closed` ([Embed] -> [Wait] /
[Wait] -> (Os) : select({Fds}) => {Ready}):
- `fds`: the fds to wait to read (an iterable of ints >= 0); `write`: the fds to wait
  to write. A repeated fd counts once, at its first place.
- `timeout`: seconds (`int` / `float`; negative counts as `0`, which polls once and
  returns at once), or `None` to wait until something is ready. It is given to poll in
  whole milliseconds, rounded up (`math.ceil(timeout * 1000)`), so a positive timeout
  never becomes a busy `0`. An `EINTR` (a signal handler ran) is retried with the time
  that is left (Python's own retry, PEP 475), so a signal never ends the wait early by
  itself; a self-pipe among `fds` is what makes a signal end it.
- With no fds at all, `select((), t)` sleeps `t` seconds (through poll) and returns
  `Ready()`.
- The result, judging each fd in order (the `fds` first, then `write`), the first fd
  that went away deciding:
  - `POLLNVAL` (not an open fd): `Closed("invalid", fd, errno.EBADF)`;
  - a read fd with `POLLHUP` or `POLLERR` and no `POLLIN` / `POLLPRI` (nothing left to
    read): `Closed("hangup", fd)`; a read fd with `POLLIN` (or `POLLPRI`) is ready,
    `POLLHUP` or not (the reader drains it and meets its own end of file or `EIO`);
  - a write fd with `POLLERR` or `POLLHUP`: `Closed("hangup", fd)`; with `POLLOUT`:
    ready;
  - otherwise: `Ready(read, write)` of the ready ones (`Ready()` at the timeout).
  Any `OSError` from poll itself: `Closed.of(error)` (its `fd` `None`).

Inputs: `fds` and `write` iterables of ints ({Fds}); `timeout` a number or `None`.
Outputs: a {Ready}, or a {Closed}.
Errors: `TypeError` when `fds` or `write` is not iterable, or holds a non-`int` (a
  `bool` is refused), or `timeout` is neither `None` nor a real number (a `bool` is
  refused); `ValueError` when an fd is negative, `timeout` is NaN, or there are no fds
  and `timeout` is `None` (that would wait forever). No `OSError` escapes.
Effects: `select.poll()`, `register`, `poll(ms)`; nothing is read or written, and no fd
  is closed or changed.

Note: `select` shadows the stdlib module inside this module, which reaches it as
`_select`.

Usage:
    import os
    from cure.closed import Closed
    from cure.edge.clock.wait import select, Ready
    r, w = os.pipe()
    select([r], 0)                 # Ready(): nothing to read yet
    os.write(w, b"x")
    select([r], 1.0)               # Ready(read=(r,))
    select([], 0.01, write=[w])    # Ready(write=(w,))
    os.close(w); os.read(r, 1)
    select([r], 1.0)               # Closed("hangup", r): the writer is gone, nothing left
    select([9999], 0)              # Closed("invalid", 9999, errno.EBADF)
"""

import errno
import math
import select as _select
from dataclasses import dataclass

from cure.closed import Closed


@dataclass(frozen=True)
class Ready:
    """{Ready}: the fds ready to read and to write, in the caller's order."""

    read: "tuple[int, ...]" = ()
    write: "tuple[int, ...]" = ()

    def __bool__(self) -> bool:
        return bool(self.read or self.write)


def select(fds, timeout: "float | None" = None, *, write=()) -> "Ready | Closed":
    """Wait until an fd is ready or `timeout` passes; the ready fds, or the Closed (see the module)."""
    reads = _fds(fds, "fds")
    writes = _fds(write, "write")
    ms = _milliseconds(timeout)
    if ms is None and not reads and not writes:
        raise ValueError("no fds and no timeout would wait forever")
    try:
        events = _poll(reads, writes, ms)
    except OSError as error:
        return Closed.of(error)
    return _judge(reads, writes, events)


_POLL_MAX_MS = 2**31 - 1
_READ = _select.POLLIN | _select.POLLPRI
_GONE = _select.POLLHUP | _select.POLLERR


def _poll(reads: "tuple[int, ...]", writes: "tuple[int, ...]", ms: "int | None") -> dict:
    poller = _select.poll()
    masks = {}
    for fd in reads:
        masks[fd] = masks.get(fd, 0) | _READ
    for fd in writes:
        masks[fd] = masks.get(fd, 0) | _select.POLLOUT
    for fd, mask in masks.items():
        poller.register(fd, mask)
    return dict(poller.poll(ms))


def _judge(reads: "tuple[int, ...]", writes: "tuple[int, ...]", events: dict) -> "Ready | Closed":
    ready_read, ready_write = [], []
    for fd in reads:
        ev = events.get(fd, 0)
        if ev & _select.POLLNVAL:
            return Closed("invalid", fd, errno.EBADF)
        if ev & _READ:
            ready_read.append(fd)
        elif ev & _GONE:
            return Closed("hangup", fd)
    for fd in writes:
        ev = events.get(fd, 0)
        if ev & _select.POLLNVAL:
            return Closed("invalid", fd, errno.EBADF)
        if ev & _GONE:
            return Closed("hangup", fd)
        if ev & _select.POLLOUT:
            ready_write.append(fd)
    return Ready(tuple(ready_read), tuple(ready_write))


def _fds(fds: object, name: str) -> "tuple[int, ...]":
    try:
        items = iter(fds)
    except TypeError:
        raise TypeError(f"{name} must be an iterable of ints, got {type(fds).__name__}") from None
    seen = []
    for fd in items:
        if isinstance(fd, bool) or not isinstance(fd, int):
            raise TypeError(f"{name} must hold ints, got {type(fd).__name__}")
        if fd < 0:
            raise ValueError(f"{name} must hold fds >= 0, got {fd}")
        if fd not in seen:
            seen.append(fd)
    return tuple(seen)


def _milliseconds(timeout: object) -> "int | None":
    if timeout is None:
        return None
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise TypeError(f"timeout must be None or a real number, got {type(timeout).__name__}")
    if math.isnan(timeout):
        raise ValueError("timeout must not be NaN")
    if timeout <= 0:
        return 0
    if math.isinf(timeout):
        return None
    return min(math.ceil(timeout * 1000), _POLL_MAX_MS)
