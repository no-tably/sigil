"""[Signals]: WINCH, TSTP / CONT, TERM / HUP as events, through a self-pipe the app opts
into; the size also polled (a signal doesn't cross a mux), which is the whole of the
fallback when no handler can be installed.

Kind: service (a class with explicit state, and the functions that drive it). Nothing
is installed behind the app's back: handlers exist only between `install` and
`uninstall`, which the app (or the Term handle, when the app passes `signals=True`)
calls; `uninstall` puts back exactly the handlers that were there. No `atexit`, no
`signal.set_wakeup_fd` (process-wide, and an event loop may own it).

The signals and the events they become (`SIGNALS`, by name; `KINDS`):
- `SIGWINCH` -> `"resize"`, but only through the size: see `on`;
- `SIGTSTP` -> `"suspend"`; `SIGCONT` -> `"resume"`;
- `SIGTERM` -> `"terminate"`; `SIGHUP` -> `"hangup"`.
`SIGINT` is never touched: it stays Python's `KeyboardInterrupt` (in cbreak mode), which
unwinds through the app's `with` / `finally` and so through the Term's `close`.

Data:
- `Event(kind, size=None)` ({Event}): `kind` one of `KINDS`; `size` the new `(w, h)`
  for a `"resize"` (or `None` when it is not known), `None` for the other kinds.
  Equality field by field.
- `Signals(size=None)`: `size` the last known `(w, h)` (or `None`). Read-only
  attributes: `size` (the last size `on` saw), `installed` (`bool`), `fd` (the
  self-pipe's read end while installed, for a reader or Clock's [Wait] to wait on,
  else `None`).

`install(signals) -> bool`: creates the self-pipe (`os.pipe()`, both ends
non-blocking, not inheritable) and sets, with `signal.signal`, a handler for each of
`SIGWINCH`, `SIGTSTP`, `SIGCONT`, `SIGTERM`, `SIGHUP`, remembering each previous
handler. The handler only writes the signal number as one byte to the pipe
(`os.write`, an `OSError` such as a full pipe ignored: repeats collapse anyway); it
never writes the terminal, so the [Writer] stays the only writer. Returns `True`.
The fallback (`@fallback(poll)`): when handlers cannot be installed (`signal.signal`
raises `ValueError` off the main thread, or the platform lacks one of the signals),
anything already set is put back, the pipe is closed, and `install` returns `False`
with `installed` false: the app gets resizes by the polled size only, and suspend /
terminate keep their default actions. A second `install` while installed returns
`True` and changes nothing.

`uninstall(signals) -> None`: puts back each remembered handler with `signal.signal`
(exactly the object `signal.signal` returned when installing), closes both pipe ends,
and clears `installed` and `fd`. A no-op when not installed. Idempotent.

`note(signals, signum) -> None`: what the handler does, as a function: one byte
`signum` written to the self-pipe (a no-op when not installed). A test calls it to
simulate a signal without sending one; sending a real one with
`signal.raise_signal` (main thread) has the same effect.

`on(signals, size=None) -> tuple[Event, ...]` ([Signals] -> (Terminal) :
on({Signal}) => {Event}, `@timeout(tick)`): never blocks. It drains the self-pipe
(non-blocking reads until empty; nothing when not installed) and returns, in order:
1. one event per signal byte read, in arrival order, `"suspend"` / `"resume"` /
   `"terminate"` / `"hangup"`, with consecutive equal kinds collapsed into one; a
   `SIGWINCH` byte adds no event here;
2. then the resize, at most one: when `size` is given (the size just measured, e.g. by
   `size_of`) and differs from `signals.size`: `Event("resize", size)`, and
   `signals.size` becomes `size` (whether a `SIGWINCH` came or not: that is the
   polling, and it also catches a resize no signal reports). When `size` is `None` and
   a `SIGWINCH` byte was read: `Event("resize", None)`.
So an unchanged size never makes a resize event, and the first `on` after
`Signals(size=s)` with the same `s` returns `()`. The caller bounds how stale a polled
size can be by how often it calls `on` (the Term handle: every read, which waits at
most its tick).

`baseline(signals, size) -> None` (Q11; what the Term handle's `open` calls once it
has measured the size): `signals.size` becomes `size`, the size the next `on`
compares with, and no event is made (so the first `on` at that same size returns
`()`, and `on`'s resize is only ever a change from it). `size` `None` or a `(w, h)`
tuple of ints > 0 (`None`: unknown, so the next `on` given a size reports it). The
self-pipe and the handlers are untouched; it works installed or not. Errors, checked
before the write (on an error `signals.size` is unchanged): `TypeError` when
`signals` is not a `Signals` or `size` is neither `None` nor a 2-tuple of ints (a
`bool` is refused); `ValueError` when a size value is < 1. Effects: none but
`signals.size`.

`size_of(fds, env, default=(80, 24)) -> (w, h)`: the terminal's size in cells: the
first fd of `fds` (ints, `None` entries skipped) for which `os.get_terminal_size(fd)`
succeeds with both columns and lines > 0; else `env["COLUMNS"]` and `env["LINES"]`
when both are decimal integers > 0; else `default`. Never raises for an fd that is not
a terminal.

Inputs: `signals` a `Signals`; `signum` an `int`; `size` `None` or a `(w, h)` tuple of
  ints > 0; `fds` an iterable of ints or `None`; `env` a `Mapping[str, str]`.
Outputs: `install` a `bool`; `on` a tuple of {Event}; `size_of` a `(w, h)` tuple;
  `baseline` `None`.
Errors: `TypeError` when `signals` is not a `Signals`, `size` / `default` is neither
  `None` nor a 2-tuple of ints (a `bool` is refused), `signum` is not an `int`, `env`
  is not a `Mapping`, or `Event`'s `kind` is not a `str`; `ValueError` when a size
  holds a value < 1 or `kind` is not in `KINDS`. No `OSError` escapes.
Effects: `install` / `uninstall`: `os.pipe`, `os.set_blocking`, `signal.signal`,
  `os.close`; `note` and the handler: `os.write` to the pipe; `on`: `os.read` from the
  pipe; `size_of`: `os.get_terminal_size` (the `TIOCGWINSZ` ioctl). No terminal byte
  is written by any of them.

Usage:
    from cure.edge.term.signals import Signals, Event, install, uninstall, note, on, size_of
    import signal
    s = Signals(size=(80, 24))
    on(s, (80, 24))                    # (): nothing changed (the poll, no handler needed)
    on(s, (100, 30))                   # (Event("resize", (100, 30)),)
    if install(s):                     # main thread: True
        note(s, signal.SIGTERM)
        on(s, (100, 30))               # (Event("terminate"),)
        uninstall(s)                   # the previous handlers are back
    size_of([None], {"COLUMNS": "120", "LINES": "40"})   # (120, 40)
"""

import os
import signal as _signal
from collections.abc import Mapping
from dataclasses import dataclass

SIGNALS = {
    "winch": _signal.SIGWINCH,
    "tstp": _signal.SIGTSTP,
    "cont": _signal.SIGCONT,
    "term": _signal.SIGTERM,
    "hup": _signal.SIGHUP,
}
KINDS = ("resize", "suspend", "resume", "terminate", "hangup")

_KIND_OF = {
    _signal.SIGTSTP: "suspend",
    _signal.SIGCONT: "resume",
    _signal.SIGTERM: "terminate",
    _signal.SIGHUP: "hangup",
}


@dataclass(frozen=True)
class Event:
    """{Event}: what a signal (or the polled size) means for the app. Checked on construction."""

    kind: str
    size: "tuple[int, int] | None" = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str):
            raise TypeError(f"kind must be a str, got {type(self.kind).__name__}")
        if self.kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}, got {self.kind!r}")
        _check_size(self.size, "size")


class Signals:
    """{Signals}: the self-pipe, the handlers it replaced, the last known size (see the module)."""

    def __init__(self, size: "tuple[int, int] | None" = None) -> None:
        _check_size(size, "size")
        self._size = size
        self._pipe = None
        self._previous = {}

    @property
    def size(self) -> "tuple[int, int] | None":
        """The last size `on` saw (or the one given)."""
        return self._size

    @property
    def installed(self) -> bool:
        """Handlers are installed (else: the polling fallback)."""
        return self._pipe is not None

    @property
    def fd(self) -> "int | None":
        """The self-pipe's read end while installed, else None."""
        return self._pipe[0] if self._pipe is not None else None


def install(signals: Signals) -> bool:
    """Install the self-pipe handlers; False (nothing installed) is the polling fallback."""
    _check_signals(signals)
    if signals.installed:
        return True
    try:
        r, w = os.pipe()
    except OSError:
        return False
    for fd in (r, w):
        os.set_blocking(fd, False)
        os.set_inheritable(fd, False)
    signals._pipe = (r, w)
    try:
        for signum in SIGNALS.values():
            signals._previous[signum] = _signal.signal(signum, _handler(signals))
    except (ValueError, OSError):
        uninstall(signals)
        return False
    return True


def uninstall(signals: Signals) -> None:
    """Put back exactly the handlers `install` replaced; close the pipe. Idempotent."""
    _check_signals(signals)
    for signum, previous in signals._previous.items():
        if previous is not None:
            _signal.signal(signum, previous)
    signals._previous = {}
    if signals._pipe is not None:
        for fd in signals._pipe:
            _close(fd)
        signals._pipe = None


def note(signals: Signals, signum: int) -> None:
    """What the handler does: one byte `signum` into the self-pipe (no-op when not installed)."""
    _check_signals(signals)
    if isinstance(signum, bool) or not isinstance(signum, int):
        raise TypeError(f"signum must be an int, got {type(signum).__name__}")
    if signals._pipe is None:
        return
    try:
        os.write(signals._pipe[1], bytes([signum & 0xFF]))
    except OSError:
        pass  # a full pipe: repeats collapse anyway


def on(signals: Signals, size: "tuple[int, int] | None" = None) -> "tuple[Event, ...]":
    """The events since the last call: drained signals, then a resize if the size changed."""
    _check_signals(signals)
    _check_size(size, "size")
    events = []
    winch = False
    for signum in _drain(signals):
        if signum == _signal.SIGWINCH:
            winch = True
            continue
        kind = _KIND_OF.get(signum)
        if kind is not None and (not events or events[-1].kind != kind):
            events.append(Event(kind))
    if size is not None:
        if size != signals._size:
            events.append(Event("resize", size))
            signals._size = size
    elif winch:
        events.append(Event("resize", None))
    return tuple(events)


def size_of(fds, env: Mapping, default: "tuple[int, int]" = (80, 24)) -> "tuple[int, int]":
    """The terminal's size: the first fd that answers, else COLUMNS / LINES, else `default`."""
    if not isinstance(env, Mapping):
        raise TypeError(f"env must be a Mapping, got {type(env).__name__}")
    _check_size(default, "default")
    for fd in fds:
        if fd is None:
            continue
        try:
            columns, lines = os.get_terminal_size(fd)
        except (OSError, ValueError):
            continue
        if columns > 0 and lines > 0:
            return (columns, lines)
    columns, lines = _positive(env.get("COLUMNS")), _positive(env.get("LINES"))
    if columns and lines:
        return (columns, lines)
    return default


def baseline(signals: Signals, size: "tuple[int, int] | None") -> None:
    """The size the next `on` compares with, set without an event (see the module)."""
    _check_signals(signals)
    _check_size(size, "size")
    signals._size = size


def _handler(signals: Signals):
    def handle(signum, frame):
        note(signals, signum)
    return handle


def _drain(signals: Signals) -> bytes:
    if signals._pipe is None:
        return b""
    out = bytearray()
    while True:
        try:
            chunk = os.read(signals._pipe[0], 4096)
        except (BlockingIOError, InterruptedError):
            break
        except OSError:
            break
        if not chunk:
            break
        out += chunk
    return bytes(out)


def _close(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def _positive(text: object) -> "int | None":
    if isinstance(text, str) and text.isascii() and text.isdigit() and int(text) > 0:
        return int(text)
    return None


def _check_signals(signals: object) -> None:
    if not isinstance(signals, Signals):
        raise TypeError(f"expected a Signals, got {type(signals).__name__}")


def _check_size(size: object, name: str) -> None:
    if size is None:
        return
    if not isinstance(size, tuple) or len(size) != 2 or any(
            isinstance(v, bool) or not isinstance(v, int) for v in size):
        raise TypeError(f"{name} must be None or a (w, h) tuple of ints, got {size!r}")
    if size[0] < 1 or size[1] < 1:
        raise ValueError(f"{name} must hold values >= 1, got {size!r}")
