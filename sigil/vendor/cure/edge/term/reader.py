"""[Reader]: the tty's input as bytes, waited for with a timeout (the tick); the terminal
going away is a {Closed} returned to the app.

Kind: service (a class with explicit state, and the functions that drive it). Bytes in,
nothing decoded: splitting escape sequences, UTF-8 and keys is Input's job (a sequence
or a character may straddle two reads). The Reader keeps an inbox of bytes the person
"typed" by other means (`type`): a headless terminal's input (a server's client, a
test), and the bytes Probe read that were not replies (typed ahead during the probe),
so no input is ever lost.

Data:
- `Reader(fd=None, *, chunk=CHUNK)`:
  - `fd`: an `int` >= 0, the fd input is read from (a tty, a pty's slave or master, a
    pipe, a socket), or `None` for a headless reader whose only input is its inbox.
    The reader never closes the fd or changes its flags (it never sets
    `O_NONBLOCK`): it reads only after poll says the fd is readable, so one `os.read`
    never blocks;
  - `chunk`: `int` > 0, the most bytes one `os.read` asks for.
  Read-only attributes: `fd`, `chunk`, `pending` (`bytes`: the inbox, not yet
  returned), `closed` (the sticky {Closed}, or `None`).
  `Reader.read(timeout=None, *, wake=())` is `read(self, timeout, wake=wake)`;
  `Reader.type(data)` is `type(self, data)`.

`read(reader, timeout=None, *, wake=()) -> bytes | Closed` ({Fd} => {Bytes},
`@timeout(tick)`). `timeout`: seconds (`int` or `float`; negative counts as `0`), or
`None` to wait until something happens. `wake`: other fds (ints) whose readiness also
ends the wait, e.g. Signals' self-pipe; the reader never reads them. In order:
1. The inbox is not empty: return all of it and empty it. No wait, no system call
   (even when `closed` is set: input already received is never lost).
2. `closed` is set: return it.
3. `fd` is `None`: return `b""` at once (a headless reader never blocks).
4. Wait with `select.poll` on `fd` (`POLLIN`) and each `wake` fd (`POLLIN`), up to
   `timeout` (milliseconds rounded up, so a positive timeout never becomes a busy
   `0`; `EINTR` retried with the remaining time):
   - nothing ready within the timeout: `b""`;
   - only `wake` fds ready: `b""`;
   - `fd` reports `POLLNVAL`: `Closed("invalid", fd, errno.EBADF)`;
   - `fd` reports `POLLIN`, `POLLHUP` or `POLLERR`: one `os.read(fd, chunk)`:
     - data: return it (at most `chunk` bytes, exactly what the OS gave);
     - `b""` (end of file): `Closed("eof", fd)`;
     - `BlockingIOError` (`EAGAIN`, a spurious wake-up): `b""`;
     - `InterruptedError`: retried;
     - any other `OSError` (`EIO`: the pty or the controlling terminal is gone): a
       `Closed.of(error, fd)`.
   A `Closed` returned here is kept in `closed` and returned by every later call once
   the inbox is empty (sticky).

`type(reader, data) -> None` ((Person) ~> [Reader] : type({Bytes})): the person typed
`data`; it is appended to the inbox, and the next `read` returns the whole inbox before
anything from the fd. Works on a closed reader too.

Inputs: `reader` a `Reader`; `timeout` a number or `None`; `wake` an iterable of ints;
  `data` `bytes` / `bytearray`.
Outputs: `read`: {Bytes} (`b""` for "nothing yet") or a {Closed}; `type`: `None`.
Errors: `Reader(...)`: `TypeError` when `fd` is neither `None` nor an `int` (a `bool`
  is refused) or `chunk` is not an `int`; `ValueError` when `fd` is negative or
  `chunk` < 1. `read`: `TypeError` when `reader` is not a `Reader`, `timeout` is
  neither `None` nor a real number (a `bool` is refused), or a `wake` entry is not an
  `int`; `ValueError` when `timeout` is NaN. `type`: `TypeError` when `data` is not
  `bytes` / `bytearray` (a `str` is refused). No `OSError` escapes: an fd failure is
  the returned {Closed}.
Effects: `select.poll` on `fd` and the `wake` fds; `os.read(fd, chunk)`. Nothing is
  written, and no terminal mode is touched (that is [Modes]').

Note: `type` shadows the builtin inside this module; code here reaches the builtin as
`builtins.type`.

Usage:
    import os
    from cure.closed import Closed
    from cure.edge.term.reader import Reader, read, type
    r, w = os.pipe()
    rd = Reader(r)
    read(rd, 0)                    # b"": nothing yet
    os.write(w, b"q")
    read(rd, 1.0)                  # b"q"
    type(rd, b"\\x1b[A")
    rd.read(0)                     # b"\\x1b[A": the inbox first, no system call
    os.close(w)
    read(rd, 1.0)                  # Closed("eof", r); every later read returns it too
    headless = Reader(None)
    headless.read(None)            # b"": never blocks
"""

import builtins
import errno
import math
import os
import select

from cure.closed import Closed

CHUNK = 65536


class Reader:
    """{Reader}: one fd's input and an inbox of typed bytes (see the module)."""

    def __init__(self, fd: "int | None" = None, *, chunk: int = CHUNK) -> None:
        if fd is not None and (isinstance(fd, bool) or not isinstance(fd, int)):
            raise TypeError(f"fd must be None or an int, got {builtins.type(fd).__name__}")
        if isinstance(chunk, bool) or not isinstance(chunk, int):
            raise TypeError(f"chunk must be an int, got {builtins.type(chunk).__name__}")
        if fd is not None and fd < 0:
            raise ValueError(f"fd must be >= 0, got {fd}")
        if chunk < 1:
            raise ValueError(f"chunk must be >= 1, got {chunk}")
        self._fd = fd
        self._chunk = chunk
        self._inbox = bytearray()
        self._closed = None

    @property
    def fd(self) -> "int | None":
        """The fd read from, or None (headless)."""
        return self._fd

    @property
    def chunk(self) -> int:
        """The most bytes one os.read asks for."""
        return self._chunk

    @property
    def pending(self) -> bytes:
        """The inbox: typed bytes not yet returned."""
        return bytes(self._inbox)

    @property
    def closed(self) -> "Closed | None":
        """The sticky Closed once the fd went away, else None."""
        return self._closed

    def read(self, timeout: "float | None" = None, *, wake=()) -> "bytes | Closed":
        """`read(self, timeout, wake=wake)`."""
        return read(self, timeout, wake=wake)

    def type(self, data: "bytes | bytearray") -> None:
        """`type(self, data)`."""
        return type(self, data)


def read(reader: Reader, timeout: "float | None" = None, *, wake=()) -> "bytes | Closed":
    """The inbox, or one read of the fd within `timeout`, or the Closed (see the module)."""
    if not isinstance(reader, Reader):
        raise TypeError(f"expected a Reader, got {builtins.type(reader).__name__}")
    ms = _milliseconds(timeout)
    wake = _wake_fds(wake)
    if reader._inbox:
        data = bytes(reader._inbox)
        reader._inbox.clear()
        return data
    if reader._closed is not None:
        return reader._closed
    if reader._fd is None:
        return b""
    result = _wait_and_read(reader, ms, wake)
    if isinstance(result, Closed):
        reader._closed = result
    return result


def type(reader: Reader, data: "bytes | bytearray") -> None:  # noqa: A001 (the flow's op name)
    """Append `data` to `reader`'s inbox: the person typed it (see the module)."""
    if not isinstance(reader, Reader):
        raise TypeError(f"expected a Reader, got {builtins.type(reader).__name__}")
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError(f"data must be bytes, got {builtins.type(data).__name__}")
    reader._inbox.extend(data)


_GONE = select.POLLIN | select.POLLHUP | select.POLLERR


def _wait_and_read(reader: Reader, ms: "int | None", wake: "tuple[int, ...]") -> "bytes | Closed":
    fd = reader._fd
    poller = select.poll()
    for other in wake:
        if other != fd:
            poller.register(other, select.POLLIN)
    poller.register(fd, select.POLLIN)
    try:
        events = dict(poller.poll(ms))
    except OSError as error:
        return Closed.of(error, fd)
    ev = events.get(fd, 0)
    if ev & select.POLLNVAL:
        return Closed("invalid", fd, errno.EBADF)
    if not ev & _GONE:
        return b""
    return _read_once(fd, reader._chunk)


def _read_once(fd: int, chunk: int) -> "bytes | Closed":
    while True:
        try:
            data = os.read(fd, chunk)
        except BlockingIOError:
            return b""
        except InterruptedError:
            continue
        except OSError as error:
            return Closed.of(error, fd)
        return data if data else Closed("eof", fd)


def _wake_fds(wake: object) -> "tuple[int, ...]":
    fds = tuple(wake)
    for fd in fds:
        if isinstance(fd, bool) or not isinstance(fd, int):
            raise TypeError(f"wake must hold ints, got {builtins.type(fd).__name__}")
    return fds


def _milliseconds(timeout: object) -> "int | None":
    if timeout is None:
        return None
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise TypeError(f"timeout must be None or a real number, got {builtins.type(timeout).__name__}")
    if math.isnan(timeout):
        raise ValueError("timeout must not be NaN")
    if timeout <= 0:
        return 0
    if math.isinf(timeout):
        return None
    return min(math.ceil(timeout * 1000), 2**31 - 1)
