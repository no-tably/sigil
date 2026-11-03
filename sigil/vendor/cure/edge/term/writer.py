"""[Writer]: the one writer: every byte cure sends to a terminal goes through it; or a
headless sink: tests, --once, a server.

Kind: service (a class with explicit state, and the function that drives it). The only
unit of cure that calls `os.write` on a terminal's fd. Modes' escapes, Probe's queries,
Osc's sequences and every frame Buffer's [Display] builds reach the terminal through one
`Writer`'s `write`; the Term handle holds exactly one per terminal.

Data:
- `Writer(fd=None, *, sink=None)`: exactly one of
  - `fd`: an `int` >= 0, an open fd (a tty, a pty's slave, a pipe, a socket) the
    writer writes with `os.write`; it is never closed, made non-blocking or otherwise
    changed by the writer (the app owns it);
  - `sink`: a `bytearray` the writer appends to: the headless sink (tests, `--once`
    into a buffer, a server composing output). A sink write never fails.
  Read-only attributes: `fd` (`int` or `None`), `sink` (the `bytearray` or `None`),
  `written` (`int`, the total bytes written so far, to the fd or the sink), `closed`
  (the sticky {Closed}, or `None` while the writer works).
  `Writer.write(data)` is `write(self, data)`.

`write(writer, data) -> None | Closed`. `data` is `bytes`, `bytearray` or `memoryview`
({Bytes}). In order:
1. `writer.closed` is set: return it; nothing is written.
2. `data` is empty: return `None`; no system call.
3. A sink: `sink.extend(data)`; `written` grows by `len(data)`; return `None`.
4. An fd: `os.write(fd, rest)` until every byte is written, `rest` the unwritten tail:
   - a partial write (fewer bytes than asked) continues with the remaining tail;
   - `BlockingIOError` (`EAGAIN` / `EWOULDBLOCK`: a non-blocking fd whose buffer is
     full) waits until the fd is writable (`select.poll`, `POLLOUT`, no time limit)
     and continues;
   - `InterruptedError` (`EINTR`) retries;
   - any other `OSError` (`EPIPE`, `EIO`, `EBADF`, ...) stops: `closed` becomes
     `Closed.of(error, fd)` (`"epipe"`, `"eio"`, `"invalid"`, ...), returned now and
     by every later call; the unwritten tail is dropped.
   `written` grows by each byte the OS accepted. Return `None` once all are written.
So a frame is never torn by the writer itself: it returns only when the whole of `data`
is out, or the fd is gone.

Inputs: `writer` a `Writer`; `data` {Bytes}.
Outputs: `None`, or a {Closed} (the terminal went away).
Errors: `Writer(...)`: `TypeError` when `fd` is not an `int` (a `bool` is refused) or
  `sink` is not a `bytearray`; `ValueError` when both or neither are given, or `fd` is
  negative. `write`: `TypeError` when `writer` is not a `Writer` or `data` is not
  `bytes` / `bytearray` / `memoryview` (a `str` is refused: encoding is the caller's).
  No `OSError` escapes: an fd failure is the returned {Closed}.
Effects: `os.write` on `fd` (and `select.poll` on it while it is full); a sink's
  `extend`. Nothing else: no flush of Python's `sys.stdout`, no signal handling
  (Python ignores `SIGPIPE`, so a closed pipe is `EPIPE`, i.e. `"epipe"`).

Invariant: single_writer — every byte cure sends to a terminal goes through one
  `Writer`'s `write`: the Term handle builds exactly one `Writer` for its output (or
  takes the one it is given) and sends Modes' escapes, Probe's queries, Osc's
  sequences, raw `term.write` bytes and every [Display] frame through it, in the order
  they are asked for; no other unit of cure calls `os.write` (or any other write) on a
  terminal's fd. Proof shape: a Term given `Writer(fd=w)` over a pipe while its input is
  a pty's slave: everything the terminal side receives arrives on the pipe, `written`
  equals the bytes the pipe received, and the pty's master receives nothing cure wrote.

Usage:
    import os
    from cure.closed import Closed
    from cure.edge.term.writer import Writer, write
    buf = bytearray()
    w = Writer(sink=buf)
    write(w, b"\\x1b[?25l")         # None; buf == bytearray(b"\\x1b[?25l"), w.written == 6
    r, fd = os.pipe()
    p = Writer(fd)
    p.write(b"hello")               # None; os.read(r, 5) == b"hello"
    os.close(r)
    p.write(b"more")                # Closed("epipe", fd, errno.EPIPE); sticky
    Writer()                        # ValueError: neither fd nor sink
"""

import os
import select

from cure.closed import Closed


class Writer:
    """{Writer}: the one writer of a terminal's fd, or a headless sink (see the module)."""

    def __init__(self, fd: "int | None" = None, *, sink: "bytearray | None" = None) -> None:
        if fd is not None and (isinstance(fd, bool) or not isinstance(fd, int)):
            raise TypeError(f"fd must be an int, got {type(fd).__name__}")
        if sink is not None and not isinstance(sink, bytearray):
            raise TypeError(f"sink must be a bytearray, got {type(sink).__name__}")
        if (fd is None) == (sink is None):
            raise ValueError("give exactly one of fd and sink")
        if fd is not None and fd < 0:
            raise ValueError(f"fd must be >= 0, got {fd}")
        self._fd = fd
        self._sink = sink
        self._written = 0
        self._closed = None

    @property
    def fd(self) -> "int | None":
        """The fd written to, or None for a sink."""
        return self._fd

    @property
    def sink(self) -> "bytearray | None":
        """The bytearray appended to, or None for an fd."""
        return self._sink

    @property
    def written(self) -> int:
        """The total bytes written so far."""
        return self._written

    @property
    def closed(self) -> "Closed | None":
        """The sticky Closed once the fd went away, else None."""
        return self._closed

    def write(self, data: "bytes | bytearray | memoryview") -> "Closed | None":
        """`write(self, data)`."""
        return write(self, data)


def write(writer: Writer, data: "bytes | bytearray | memoryview") -> "Closed | None":
    """Write all of `data`, or return the Closed that stopped it (see the module)."""
    if not isinstance(writer, Writer):
        raise TypeError(f"expected a Writer, got {type(writer).__name__}")
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError(f"data must be bytes, got {type(data).__name__}")
    if writer._closed is not None:
        return writer._closed
    if not data:
        return None
    if writer._sink is not None:
        writer._sink.extend(data)
        writer._written += len(data)
        return None
    return _write_fd(writer, memoryview(data).cast("B"))


def _write_fd(writer: Writer, rest: memoryview) -> "Closed | None":
    while rest:
        try:
            n = os.write(writer._fd, rest)
        except BlockingIOError:
            _wait_writable(writer._fd)
            continue
        except InterruptedError:
            continue
        except OSError as error:
            writer._closed = Closed.of(error, writer._fd)
            return writer._closed
        writer._written += n
        rest = rest[n:]
    return None


def _wait_writable(fd: int) -> None:
    poller = select.poll()
    poller.register(fd, select.POLLOUT)
    try:
        poller.poll()
    except OSError:
        pass  # the next os.write meets the same failure and reports it
