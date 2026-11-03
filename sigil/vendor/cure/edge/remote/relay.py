"""[Relay]: the far side of ssh, on the server's host: a transparent byte pipe between two
ends the app gives it; it never decodes or changes a byte.

Kind: service (a class with explicit state, and the flow's module-level op). The drawn
flow is `[Relay] -> (Client) : step({Bytes}) => {Bytes} @timeout(tick) !> <Closed>`:
each `step` moves the bytes that came from one end on to the other, both ways, and a
{Closed} (either end went away) is returned to the app, never raised.

Where the processes are. Remote spawns nothing ([Embed]'s Pty is cure's one spawner):
1. The client's app spawns `ssh host <app> attach --stdio <session>` itself and
   attaches over ssh's pipes ([Attach]'s `open((fd_in, fd_out))`).
2. On the server's host, sshd starts the app's `attach --stdio <session>`. That
   process runs Relay: its two ends are its own stdio (`(0, 1)`: the ssh channel) and
   the session's socket, which the app dialled with [Transport]'s `dial(socket_path(
   app, session))` (the owner-only checks; a {Fault} is the app's to report).
3. The server is a third process, reached only through that socket; to it the relayed
   client is one more connection, saying HELLO like a local one.
Relay itself opens, binds, dials and spawns nothing, and touches no terminal.

Transparent: the bytes are passed on as they came, in order, never decoded, framed,
merged or dropped. The attaching client validates every message itself, so
cells_only ([Protocol]) holds end to end: a server cannot reach the client's terminal
through a Relay either.

Built on [Transport]'s public face alone: `poll` (the one wait, every fd's revents) and
`End` (one end's single read and non-blocking flush); no private name of Transport's.

Data:
- `Relay(left, right, *, limit=RELAY)`: `left`, `right` each a connected
  `socket.socket` (owned from now on: `close` closes it) or an `(fd_in, fd_out)` pair
  of ints (the app's: `close` leaves them open), each made a Transport `End`. `limit`:
  an `int` >= 1, the most bytes kept waiting for one sink. Read-only attribute: `fds`
  (the fds to wait on, for an app waiting on more than the relay with Clock's [Wait]:
  `left.fd_in`, `right.fd_in`, `left.fd_out`, `right.fd_out`, each once, in that
  order). Two buffers, one per direction (left to right, right to left), both empty at
  first.
- `step(timeout=None) -> None | Closed`, one turn:
  1. Closed already (sticky, or after `close`): return it; no I/O.
  2. Wait: one Transport `poll` over each direction's source `fd_in` (`POLLIN`) while
     its buffer holds fewer than `limit` bytes, and its sink's `fd_out` (`POLLOUT`)
     while its buffer is not empty, for at most `min(timeout, TICK)` seconds (`None`:
     `TICK`; `@timeout(tick)`; `<= 0`: a look, no wait).
  3. Read, left to right first: a source reported `POLLNVAL` is `Closed("invalid",
     fd_in, EBADF)`; one reported readable (`POLLIN`, `POLLHUP` or `POLLERR`) with
     fewer than `limit` bytes buffered gets ONE `End.read` (at most `CHUNK`), its
     bytes appended to that direction's buffer; a read's {Closed} is kept.
  4. Flush, both directions, even after a {Closed} in step 3: `End.flush(buffer)` to
     each sink (non-blocking: what goes now; the rest stays, in order); its {Closed}
     kept.
  5. The first {Closed} met (in the order above) is kept; with no {Closed}, `None`.
     Then the drain: from that step on the relay reads no source, and flushes each
     direction whose sink has not failed until its buffer is empty. Until then `step`
     returns `None`; each later step's wait polls only the sinks' `POLLOUT` (each
     direction with bytes buffered), for at most `min(timeout, TICK)` seconds as in
     step 2, then flushes as in step 4. A sink's flush {Closed} drops that direction's
     bytes (kept, if it is the first met); the rest still drains. The kept {Closed}
     becomes the relay's own, sticky, and is returned when every live direction's
     buffer is empty, or once `DRAIN` seconds have passed since it was met
     (`time.monotonic`), the bytes still buffered then dropped.
  So a slow sink stops the relay reading its source (its buffer full at `limit`): the
  backpressure reaches the far side (the server's slow-client rule then applies to the
  frames; input is never dropped), and nothing is lost or reordered: at an end too,
  the bytes buffered reach a live sink within `DRAIN` seconds; only a sink that fails,
  or one still not reading after `DRAIN`, loses what was waiting for it.
- `close() -> None`: idempotent; closes the owned sockets (pipes left to the app);
  a drain under way stops (its bytes dropped); afterwards the relay's {Closed} is the one it kept, else `Closed("eof",
  left.fd_in)`, and every `step` returns it.

The flow's op (module-level, as Term's `open` is):
- `step(relay, timeout=None) -> None | Closed`: `relay.step(timeout)`.

Constants: `RELAY = 65536` (the default `limit`, bytes); `DRAIN = 2.0` (the most
  seconds a drain lasts after the first {Closed}).

Inputs: `left`, `right` as above; `limit` an `int`; `timeout` `None` or a real number.
Outputs: `step`: `None`, or the {Closed} of the end that went away (Term's shared edge
  event, as [Transport] returns it).
Errors (the caller's own wrong arguments only; never the OS's or a peer's):
  `Relay(...)`: `TypeError` when an end is neither a `socket.socket` nor a pair of
  ints (a `bool` refused) or `limit` is not an `int`; `ValueError` when an fd is
  negative, a socket is already closed, or `limit` < 1. `step`: `TypeError` when
  `timeout` is neither `None` nor a real number, `ValueError` when it is NaN (checked
  before the sticky {Closed} is returned). `step(relay, ...)`: `TypeError` when
  `relay` is not a `Relay`. No `OSError` escapes but `poll(2)`'s own (see
  [Transport]'s `poll`).
Effects: through [Transport]'s `End` and `poll` only: `recv` / `send` on the sockets,
  `os.read` / `os.write` on the pipes, `select.poll`. No thread, no signal handler, no
  process spawned, no fd's flags changed, no socket opened.

Usage:
    # the server host's `construct attach --stdio main` (sshd started it):
    from cure.edge.remote import Relay, Fault, dial, socket_path
    from cure.edge.remote.relay import step
    sock = dial(socket_path("construct", "main"))
    if isinstance(sock, Fault):
        ...                                   # "absent", "unsafe": the app reports it, exit 1
    r = Relay((0, 1), sock)
    try:
        while step(r, 0.25) is None:
            pass                              # the bytes flow until either end goes away
    finally:
        r.close()                             # the socket closed; stdio left to the process
"""

import errno as _errno
import math
import numbers
import select
import time

from cure.edge.term import Closed

from .transport import TICK, End, poll

RELAY = 65536
DRAIN = 2.0

_READABLE = select.POLLIN | select.POLLHUP | select.POLLERR


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _timeout(value: object) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"timeout must be None or a real number, got {type(value).__name__}")
    if math.isnan(value):
        raise ValueError("timeout must not be NaN")


class Relay:
    """A transparent, backpressured byte pipe between two ends (the far side of ssh)."""

    def __init__(self, left: object, right: object, *, limit: int = RELAY) -> None:
        self._left, self._right = End(left), End(right)
        if not _is_int(limit):
            raise TypeError(f"limit must be an int, got {type(limit).__name__}")
        if limit < 1:
            raise ValueError(f"limit must be >= 1, got {limit}")
        self._limit = limit
        # (source, sink, the bytes read from source waiting for sink)
        self._ways = ((self._left, self._right, bytearray()), (self._right, self._left, bytearray()))
        self._closed = None
        self._shut = False
        # the drain: the first {Closed} met, when it was met, the ways whose sink failed
        self._kept = None
        self._since = 0.0
        self._dead: set = set()

    @property
    def fds(self) -> "tuple[int, ...]":
        """The fds to wait on."""
        out = []
        for fd in (self._left.fd_in, self._right.fd_in, self._left.fd_out, self._right.fd_out):
            if fd not in out:
                out.append(fd)
        return tuple(out)

    def step(self, timeout: "float | None" = None) -> "Closed | None":
        """One poll, one read per ready direction, a non-blocking flush each way."""
        _timeout(timeout)
        if self._closed is not None:
            return self._closed
        wait = TICK if timeout is None else min(timeout, TICK)
        if self._kept is not None:
            return self._drain(wait)
        wants: dict = {}
        for source, sink, buf in self._ways:
            if len(buf) < self._limit:
                wants[source.fd_in] = wants.get(source.fd_in, 0) | select.POLLIN
            if buf:
                wants[sink.fd_out] = wants.get(sink.fd_out, 0) | select.POLLOUT
        ready = poll(wants, wait)
        gone = None
        for source, sink, buf in self._ways:
            got = ready.get(source.fd_in, 0)
            if got & select.POLLNVAL:
                gone = gone or Closed("invalid", source.fd_in, _errno.EBADF)
            elif got & _READABLE and len(buf) < self._limit:
                data = source.read()
                if isinstance(data, Closed):
                    gone = gone or data
                elif data:
                    buf += data
        for way, (source, sink, buf) in enumerate(self._ways):
            lost = sink.flush(buf)
            if lost is not None:
                self._dead.add(way)
            gone = gone or lost
        if gone is None:
            return None
        self._kept, self._since = gone, time.monotonic()
        return self._end()

    def _drain(self, wait: float) -> "Closed | None":
        """A drain's turn: wait on the sinks with bytes buffered, flush them, maybe end."""
        wants: dict = {}
        for way, (source, sink, buf) in enumerate(self._ways):
            if buf and way not in self._dead:
                wants[sink.fd_out] = wants.get(sink.fd_out, 0) | select.POLLOUT
        poll(wants, wait)
        for way, (source, sink, buf) in enumerate(self._ways):
            if buf and way not in self._dead and sink.flush(buf) is not None:
                self._dead.add(way)
        return self._end()

    def _end(self) -> "Closed | None":
        """The kept {Closed}, sticky, once the live buffers are empty or DRAIN has passed."""
        live = any(buf for way, (_, _, buf) in enumerate(self._ways) if way not in self._dead)
        if live and time.monotonic() - self._since < DRAIN:
            return None
        self._closed = self._kept
        return self._closed

    def close(self) -> None:
        """Close owned sockets; idempotent."""
        if self._shut:
            return None
        self._shut = True
        if self._closed is None:
            self._closed = self._kept or Closed("eof", self._left.fd_in)
        self._left.close()
        self._right.close()
        return None


def step(relay: Relay, timeout: "float | None" = None) -> "Closed | None":
    """`relay.step(timeout)`: one turn of the pipe; `None`, or the {Closed} of the end that went away."""
    if not isinstance(relay, Relay):
        raise TypeError(f"relay must be a Relay, got {type(relay).__name__}")
    return relay.step(timeout)
