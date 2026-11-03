"""<Closed>: the terminal, a waited-on fd, a pane's program or a link went away: returned
to the app (Term, Clock, Embed's Pty, Remote's Transport, Attach and Relay).

Kind: event (a frozen dataclass value). The one shared error event of the edge: Term's
[Reader] (and the Term handle's read, write, show and osc), Clock's [Wait], Embed's
[Pty] (its read and write: the program exited), and Remote's [Transport] (a link's
receive, send and flush), [Relay] (`step`: either end went away) and [Attach] (inside
its `Ended("dropped" | "terminal", closed=it)`) RETURN a `Closed` in place of their
normal result when an fd they work on has gone away. It is a value, NEVER raised: no
cure unit raises `Closed`, and no `OSError` from an fd escapes those units either
(Defender's view: every edge failure falls back or is returned to the app as a named
error). The app tests `isinstance(result, Closed)` and decides (usually: close the Term
and leave its loop). A `Closed` is truthy (an ordinary object), so it is
never mistaken for an idle `b""`.

Where one comes from, and which `reason` it carries:
- `"eof"`: a read returned `b""`: the other end closed (a pipe's writer, a socket peer,
  a pty master on BSD).
- `"eio"`: a read or write failed with `EIO` or `ENXIO`: the controlling terminal or
  the other side of a pty is gone (Linux reports a closed pty master this way).
- `"epipe"`: a write failed with `EPIPE` or `ECONNRESET`: the reader went away.
- `"hangup"`: `SIGHUP` arrived (a Term with signals opted in), or Wait's poll reported
  `POLLHUP` / `POLLERR` on an fd with nothing left to read.
- `"terminate"`: `SIGTERM` arrived (a Term with signals opted in): the process is asked
  to end; the terminal is still there, so the app's `close()` still undoes the modes.
- `"invalid"`: the fd is not open: `EBADF`, or poll's `POLLNVAL`.
- `"error"`: any other `OSError` from the fd (its errno kept).

Sticky: a unit that has returned a `Closed` returns that same (equal) value from every
later call that would touch the fd, without touching it again (each unit states this).

Data:
- `Closed(reason, fd=None, errno=None)`:
  - `reason`: `str`, one of `REASONS`;
  - `fd`: `int` (>= 0) the fd that went away, or `None` (a signal, or no single fd);
  - `errno`: `int` the OS error number when an `OSError` caused it, else `None`.
  Equality and hashing are field by field.
- `Closed.of(error, fd=None) -> Closed`: the `Closed` an `OSError` from `fd` means:
  `errno.EIO`, `errno.ENXIO` -> `"eio"`; `errno.EPIPE`, `errno.ECONNRESET` ->
  `"epipe"`; `errno.EBADF` -> `"invalid"`; any other errno (or `None`) -> `"error"`.
  The result's `errno` is `error.errno`, its `fd` the `fd` given. Pure.

Inputs: the three fields; for `of`, an `OSError` and an optional fd.
Outputs: a `Closed`.
Errors: `TypeError` when `reason` is not a `str`, `fd` is neither `None` nor an `int`
  (a `bool` is refused), `errno` is neither `None` nor an `int` (a `bool` is refused),
  or (`of`) `error` is not an `OSError`. `ValueError` when `reason` is not in `REASONS`
  or `fd` is negative. Assigning a field raises `dataclasses.FrozenInstanceError`.
Effects: none.

Usage:
    import errno
    from cure.closed import Closed
    Closed("eof", fd=0)                              # the tty's reader saw end of file
    Closed.of(OSError(errno.EIO, "EIO"), fd=3)       # Closed("eio", 3, errno.EIO)
    Closed.of(BrokenPipeError(errno.EPIPE, "x"), 1)  # Closed("epipe", 1, errno.EPIPE)
    Closed("gone")                                   # ValueError
"""

import errno as _errno
from dataclasses import dataclass

REASONS = ("eof", "eio", "epipe", "hangup", "terminate", "invalid", "error")


@dataclass(frozen=True)
class Closed:
    """<Closed>: an fd went away; returned (never raised). Checked on construction."""

    reason: str
    fd: "int | None" = None
    errno: "int | None" = None

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str):
            raise TypeError(f"reason must be a str, got {type(self.reason).__name__}")
        if self.reason not in REASONS:
            raise ValueError(f"reason must be one of {REASONS}, got {self.reason!r}")
        _check_optional_int(self.fd, "fd")
        _check_optional_int(self.errno, "errno")
        if self.fd is not None and self.fd < 0:
            raise ValueError(f"fd must be >= 0, got {self.fd}")

    @classmethod
    def of(cls, error: OSError, fd: "int | None" = None) -> "Closed":
        """The `Closed` an `OSError` from `fd` means (see the module)."""
        if not isinstance(error, OSError):
            raise TypeError(f"expected an OSError, got {type(error).__name__}")
        return cls(_REASON_OF.get(error.errno, "error"), fd, error.errno)


_REASON_OF = {
    _errno.EIO: "eio",
    _errno.ENXIO: "eio",
    _errno.EPIPE: "epipe",
    _errno.ECONNRESET: "epipe",
    _errno.EBADF: "invalid",
}


def _check_optional_int(value: object, name: str) -> None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise TypeError(f"{name} must be None or an int, got {type(value).__name__}")
