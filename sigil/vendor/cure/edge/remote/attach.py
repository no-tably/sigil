"""[Attach]: the client: a thin terminal, input up, diffs down; the client draws the cells
itself; detach or a dropped link gives the terminal back.

Kind: service (a class with explicit state, a pure helper, and the flows' module-level
ops `attach` and `open`; its ending value {Ended} is in `ended.py`). An
attaching process opens its OWN terminal through Term (`[Attach] -> [Term] :
open({Modes}) => {Caps}`), says hello to a server with that terminal's size and caps,
applies every FRAME it receives to its own grid ([Protocol]'s `apply`) and draws that
grid with its Term's own {Display} (`[Attach] -> [Term] : show({Grid}) => {Shown}
!> <Closed>`, Term's module-level `show(term, grid, cursor=...)`: {Shown} is nothing,
the bytes go to the terminal, not back; its {Closed} ends the attach `"terminal"`). It waits through [Transport]'s
public `poll` (`[Attach] -> [Transport] : poll({Fds}) => {Revents}`). It writes nothing to the terminal that its own Term did not
build: no byte the server sent reaches the terminal as it came (cells_only). It has
no loop: the app calls `step` from its own loop and decides what to forward.

Data:
- {Ended}: how an attachment ended, returned (never raised) by `open`, `step`, `send`,
  `detach` and `close`; its reasons (`ENDINGS`) and fields are stated in `ended.py`.
- `Attach(term, *, uid=None, tick=TICK, handshake=HANDSHAKE, now=time.monotonic)`:
  `term` a Term handle (`cure.edge.term.Term`), not yet opened (Attach opens and
  closes it; the app may still read its attributes). `tick`: seconds > 0, the longest
  one `step` waits; `handshake`: seconds > 0, `open`'s connect deadline.
  Read-only attributes: `term`; `link` (the [Transport] `Link`, `None` before `open`);
  `welcome` (the {Welcome}, or `None`); `grid` (the server's grid as last applied,
  `None` before the first FRAME: Attach's own, which later frames change in place; copy
  it to keep it); `cursor` (the last FRAME's cursor); `ended` (the
  sticky {Ended}, or `None` while attached); `fds` (to wait on: the term's `fds`, then
  the link's `fd_in`; `()` once ended). A context manager: `__exit__` calls `close()`
  and lets any exception go on.
- `fit(grid, size, cursor=None) -> tuple[Grid, cursor]` (pure): what the terminal shows
  of the server's grid: `grid` itself when `grid.size == size`; else a new
  `Grid(*size)` with `grid` blitted at (0, 0) (clipped at the right and bottom edges,
  blank beyond; Buffer's `blit` never leaves half a wide glyph); a `None` grid gives a
  blank `Grid(*size)`. The cursor is kept when it lies inside `size`, else `None`.

The handle's operations:
- `open(target, modes=None) -> Caps | Ended`: once. 0. `target` is checked with
  [Transport]'s public `check_target(target)` (no I/O; never the private
  `_check_target`), then `modes`, both before the terminal is touched.
  1. `caps = term.open(modes)`
  (Term never fails on the terminal's account). 2. [Transport]'s `connect(target,
  Hello(VERSIONS, term.size, caps), uid=uid, timeout=handshake, now=now)`, `target` a
  socket path (`str`), a connected `socket.socket`, or `(fd_in, fd_out)` (ssh stdio,
  spawned by the app). 3. A {Fault}: the end `Ended("refused", fault=fault)`; a
  {Closed}: `Ended("dropped", closed=it)`. Else `link` and `welcome` are set, nothing
  is drawn yet (the server's first FRAME is full), and `caps` is returned. From the
  welcome on, `link.limit = frame_limit(w, h)` of the terminal's size (Protocol's: a
  FRAME body above it ends the attach `"malformed"`, as `"size"`).
- `step(timeout=None) -> bytes | Ended`: one turn:
  1. `ended` set: return it (no I/O).
  2. Wait: one [Transport] `poll(wants, t)` over the term's `fds` and the link's
     `fd_in` (`POLLIN`), and the link's `fd_out` (`POLLOUT`) when bytes are queued,
     for at most `t = tick` (`None`) or `max(0, min(timeout, tick))`; its result is
     not read (steps 3 and 4 do one non-blocking look each).
  3. The link: `receive(0)`, ONE read's worth (at most `CHUNK` bytes past an incomplete
     message: the bounded batch, so a flood of frames cannot hold back the terminal's
     read and the detach key), each message in order: `Frame`: `grid = apply(grid,
     frame, own=True)`, written into Attach's own grid at a cost per change (a
     `Malformed`: end `"malformed"`), `cursor` = its cursor, and a frame of the size
     last sent sets the limit to `frame_limit` of that size; `Bye(r)`: end
     `"bye"`, detail `r`; any other message, or a `Malformed`: end `"malformed"`; a
     {Closed}: end `"dropped"`. Then `flush()`; a {Closed}: end `"dropped"`.
  4. The terminal: `data = term.read(timeout=0)`; a {Closed}: end `"terminal"`. When
     `term.size` differs from the size last sent, the limit is set for the larger of
     each side of the size it covered and the new one (frames of the old size may still
     come: `(max(w0, w1), max(h0, h1))`), `Resize(term.size)` is sent (a
     {Closed}: end `"dropped"`) and the frame is redrawn; also redrawn when
     `term.events` holds a `"resize"` or `"resume"` (the term's Display was
     invalidated).
  5. Draw, when step 3 applied a FRAME or step 4 asks: with `g, c = fit(grid,
     term.size, cursor)`, Term's `show(term, g, cursor=c)` (the Display's diff makes
     it cheap; an idle frame writes nothing); a {Closed}: end `"terminal"`. `g` may be
     Attach's grid itself (`fit`'s identity case), which a later in-place write
     changes: Display's `show` keeps `grid.copy()` as its front (one copy per show),
     never `g`, so no write reaches what it holds.
  6. Return `data`: the input bytes the person typed (`b""` for none). They are NOT
     sent: the app forwards them with `send(data)` (and keeps for itself whatever it
     binds locally, e.g. a detach key: it then calls `detach()`).
  An end in any step stops the turn there: nothing more is drawn, read or sent.
- `send(data) -> None | Ended`: `data` up the link as INPUTs of at most [Transport]'s
  `CHUNK` raw bytes each, in order (so no body exceeds the server's `MAX_INPUT`; a
  `data` of at most `CHUNK` bytes is one INPUT, an empty `data` sends nothing), all in
  one [Transport] `send`; a {Closed}: end `"dropped"`, returned. Input is never
  dropped or merged by the client: each call is its INPUTs, in order.
- `detach() -> Ended`: `Bye("detach")` queued and drained for at most `tick` seconds,
  then the end `Ended("detach")`.
- `close() -> Ended`: the end `Ended("closed")` (no BYE: the server sees the link
  drop, a `"dropped"` <Detached>). Idempotent: once ended, every one of `open`,
  `step`, `send`, `detach`, `close` returns the same `ended` and does no I/O.

The flow's op ((Construct) -> [Remote] : attach({Session}) => {Caps}), module-level and
re-exported by Remote's face:
- `attach(term, target, modes=None, *, uid=None, tick=TICK, handshake=HANDSHAKE,
  now=time.monotonic) -> tuple[Attach, Caps | Ended]`: `a = Attach(term, uid=uid,
  tick=tick, handshake=handshake, now=now)`, then `(a, a.open(target, modes))`. The
  {Session} is reached through `target`, as `open` takes it: the session's socket path
  (Remote's `socket_path(app, session)`, or the app's own, as construct's), a
  connected socket, or ssh's `(fd_in, fd_out)`. The handle comes back whichever way
  `open` went, so the app's loop is the same as with the class: `step`, `send`,
  `detach`, `close` on `a`; on an {Ended} the terminal is already given back. It
  adds nothing to `Attach` and `open`: the class stays the way in for an app that
  builds the handle first (construct's console does: `Attach(t, uid=uid)`, then
  `a.open(path, modes)`).
  Errors: `Attach(...)`'s and `open`'s, raised as they state; an argument error of
  `open`'s is raised before the terminal is touched, so nothing needs giving back.

The drawn op ((Construct) -> [Attach] : open({Session}) => {Caps}), module-level, not
re-exported by Remote's face (a package-level `open` would shadow the builtin):
- `open(attach, target, modes=None) -> Caps | Ended`: `attach.open(target, modes)`,
  nothing else; the method's own checks give the errors.

Ending (every path above, one routine): `link.close()`, then `term.close()` (Term's
close: the remembered Osc undos, every mode it set unset, termios restored, signal
handlers back), then `ended` is set. It runs exactly once.

Invariant: restored — detach or a dropped link gives the terminal back: on every path
  by which an attachment ends — `detach()`, the server's BYE, the link dropping (end of
  file, `EPIPE`, `ECONNRESET`) while waiting, reading or writing, a malformed or
  out-of-order message, `open`'s refusal (no server, unsafe socket, version mismatch,
  handshake timeout), the terminal's own hangup or terminate signal, `close()`,
  `__exit__`, and an exception raised inside any method after its argument checks (a
  bug, a `KeyboardInterrupt`: the end runs before the exception leaves; a wrong
  argument raises before anything is touched and ends nothing) — the Term has been
  closed exactly once before the method returns:
  `term.opened` is `False`, its writer received the bytes of `unset` for its plan (the
  modes undone, last set first) and its termios was restored. After the end no byte
  is written to the terminal again. Proof shape: a headless `Term(None,
  Writer(sink=buf), size=(w, h), tty=True)` and an Attach over `socket.socketpair()`
  with the test playing the server: for each path, the method's result is an {Ended}
  of the path's reason, `term.opened` is `False`, `buf` ends with the plan's undo bytes
  exactly once, and a further `step` returns the same {Ended} with `buf` unchanged.

Inputs: `term` a Term; `target` as above; `modes` a Term {Modes} or `None`; `timeout`
  a number or `None`; `data` `bytes` / `bytearray`.
Outputs: `attach`: the {Attach} and `open`'s result; `open`: {Caps} or {Ended}; `step`: {Bytes} or {Ended}; `send`: `None` or
  {Ended}; `detach`, `close`: {Ended}; `fit`: a {Grid} and a cursor.
Errors (the caller's own wrong arguments only; never the server's or the OS's):
  `Attach(...)`: `TypeError` when `term` is not a Term, `uid` is not an `int`, `tick` /
  `handshake` is not a real number (a `bool` refused) or `now` is not callable;
  `ValueError` when `tick` / `handshake` <= 0. `open`: `RuntimeError` when called a
  second time (once ended it returns `ended` instead), or (Term's own) when the term
  was already opened by someone else; `TypeError` / `ValueError` for a bad `target` or `modes`
  (as [Transport] and Term state), raised before the terminal is touched. `step`:
  `TypeError` / `ValueError` for a bad `timeout`; `RuntimeError` before `open`. `send`:
  `TypeError` when `data` is not `bytes` / `bytearray`; `RuntimeError` before `open`.
  `fit`: `TypeError` when `grid` is neither `None` nor a `Grid`, or `size` / `cursor`
  are not 2-tuples of ints; `ValueError` when a size side < 1. `Ended(...)`:
  `TypeError` / `ValueError` for wrong fields (`reason` not in `ENDINGS`).
Effects: through Term (the terminal: modes, probe, reads, the one Writer, `show`) and
  [Transport] (the link, `poll`); `now()`. No thread, no signal handler of its
  own (Term's, when the app opted in), no process spawned.

Usage:
    from cure.edge.term import Term, Modes
    from cure.edge.remote import Attach, Ended, socket_path
    from cure.interact.input import Key, decode
    DETACH = Key("\\\\", {"ctrl"})             # the app's own detach key (Ctrl-\\), legacy or kitty
    with Attach(Term(0, 1, signals=True)) as a:
        r = a.open(socket_path("construct", "main"), Modes(mouse="drag"))
        while not isinstance(r, Ended):
            r = a.step(0.5)
            if isinstance(r, bytes) and r:
                if DETACH in decode(r):          # the decoded key: b"\\x1c", or ESC [92;5u
                    r = a.detach()               # Ended("detach")
                else:
                    r = a.send(r) or b""
    # here the terminal is back as it was, whichever way it ended
    from cure.edge.remote import attach
    a, r = attach(Term(0, 1, signals=True), socket_path("construct", "main"))
    # r: the Caps, or an Ended (the terminal given back); then the same loop on a
    from cure.core.buffer import Grid, put
    from cure.edge.remote.attach import fit
    g, c = fit(put(Grid(4, 1), 0, 0, "abcd"), (2, 2), (3, 0))
    # g: "ab" over a blank row (2 x 2); c: None (column 3 is outside)
"""

import math
import numbers
import select
import time

from cure.core.buffer import Grid, blit
from cure.edge import term as _term
from cure.edge.term import Closed, Modes, Term

from . import transport as _t
from .ended import ENDINGS, Ended
from .protocol import VERSIONS, Bye, Frame, Hello, Input, Malformed, Resize, apply, frame_limit
from .transport import HANDSHAKE, TICK, Fault

_REDRAW = ("resize", "resume")


def _int_pair(value: object, name: str) -> "tuple[int, int]":
    if (not isinstance(value, tuple) or len(value) != 2
            or not all(isinstance(v, int) and not isinstance(v, bool) for v in value)):
        raise TypeError(f"{name} must be a 2-tuple of ints, got {value!r}")
    return value


def fit(grid: object, size: "tuple[int, int]", cursor: "tuple[int, int] | None" = None) -> tuple:
    """The server's grid fitted to the terminal's size (clipped or padded blank), and the cursor if inside."""
    if grid is not None and not isinstance(grid, Grid):
        raise TypeError(f"grid must be None or a Grid, got {type(grid).__name__}")
    w, h = _int_pair(size, "size")
    if cursor is not None:
        _int_pair(cursor, "cursor")
    if w < 1 or h < 1:
        raise ValueError(f"a size side must be >= 1, got {size}")
    if grid is not None and grid.size == (w, h):
        out = grid
    else:
        out = Grid(w, h)
        if grid is not None:
            blit(out, grid, 0, 0)
    if cursor is not None and not (0 <= cursor[0] < w and 0 <= cursor[1] < h):
        cursor = None
    return out, cursor


def _seconds(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"{name} must be a real number, got {type(value).__name__}")
    if math.isnan(value) or value <= 0:
        raise ValueError(f"{name} must be > 0, got {value}")
    return value


def attach(term: object, target: object, modes: object = None, *, uid: "int | None" = None,
           tick: float = TICK, handshake: float = HANDSHAKE, now: object = time.monotonic) -> tuple:
    """Build an Attach and open it: `(attach, caps or ended)` (see the module)."""
    a = Attach(term, uid=uid, tick=tick, handshake=handshake, now=now)
    return a, a.open(target, modes)


def open(attach: "Attach", target: object, modes: "Modes | None" = None) -> "Caps | Ended":  # noqa: A001 (the flow's op name)
    """`attach.open(target, modes)`: (Construct) -> [Attach] : open({Session}) => {Caps}; its {Caps} or {Ended}."""
    return attach.open(target, modes)


class _End(Exception):
    """An end met inside a turn: unwinds to the method, which runs the one ending routine."""

    def __init__(self, ended: Ended) -> None:
        super().__init__(ended.reason)
        self.ended = ended


class Attach:
    """The client: opens its own Term, attaches, applies diffs and draws; every end restores the terminal."""

    def __init__(self, term: object, *, uid: "int | None" = None, tick: float = TICK,
                 handshake: float = HANDSHAKE, now: object = time.monotonic) -> None:
        if not isinstance(term, Term):
            raise TypeError(f"term must be a Term, got {type(term).__name__}")
        if uid is not None and (isinstance(uid, bool) or not isinstance(uid, int)):
            raise TypeError(f"uid must be an int, got {type(uid).__name__}")
        _seconds(tick, "tick")
        _seconds(handshake, "handshake")
        if not callable(now):
            raise TypeError(f"now must be callable, got {type(now).__name__}")
        self._term = term
        self._uid = uid
        self._tick = tick
        self._handshake = handshake
        self._now = now
        self._link = None
        self._welcome = None
        self._grid = None
        self._cursor = None
        self._ended = None
        self._opened = False
        self._sent_size = None
        self._cover = None          # the size the link's limit covers (frame_limit of it)

    @property
    def term(self) -> object:
        """The Term it opens and closes."""
        return self._term

    @property
    def link(self) -> object:
        """The Transport Link, or None before open."""
        return self._link

    @property
    def welcome(self) -> object:
        """The server's Welcome, or None."""
        return self._welcome

    @property
    def grid(self) -> object:
        """The server's grid as last applied, or None: Attach's own, changed in place by later frames (copy it to keep it)."""
        return self._grid

    @property
    def cursor(self) -> "tuple[int, int] | None":
        """The last frame's text cursor."""
        return self._cursor

    @property
    def ended(self) -> "Ended | None":
        """The sticky Ended, or None while attached."""
        return self._ended

    @property
    def fds(self) -> "tuple[int, ...]":
        """The fds to wait on: the term's, then the link's."""
        if self._ended is not None:
            return ()
        fds = tuple(self._term.fds)
        return fds if self._link is None else fds + (self._link.fd_in,)

    def open(self, target: object, modes: object = None) -> object:
        """Open the terminal, connect with its size and caps: the Caps, or an Ended."""
        if self._ended is not None:
            return self._ended
        if self._opened:
            raise RuntimeError("an Attach opens once")
        _t.check_target(target)
        if modes is not None and not isinstance(modes, Modes):
            raise TypeError(f"modes must be None or a Modes, got {type(modes).__name__}")
        caps = self._term.open(modes)       # Term undoes itself if it raises
        self._opened = True
        return self._guard(self._connect, target, caps)

    def step(self, timeout: "float | None" = None) -> "bytes | Ended":
        """One turn: frames applied and drawn, resize sent; the typed bytes returned (not sent)."""
        if timeout is not None:
            if isinstance(timeout, bool) or not isinstance(timeout, numbers.Real):
                raise TypeError(f"timeout must be None or a real number, got {type(timeout).__name__}")
            if math.isnan(timeout):
                raise ValueError("timeout must not be NaN")
        if self._ended is not None:
            return self._ended
        if not self._opened:
            raise RuntimeError("step before open")
        return self._guard(self._turn, timeout)

    def send(self, data: bytes) -> "Ended | None":
        """The typed bytes up the link, as INPUTs of at most CHUNK bytes."""
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError(f"data must be bytes, got {type(data).__name__}")
        if self._ended is not None:
            return self._ended
        if not self._opened:
            raise RuntimeError("send before open")
        return self._guard(self._send, bytes(data))

    def detach(self) -> Ended:
        """BYE, then end: the terminal given back."""
        if self._ended is not None:
            return self._ended
        return self._guard(self._detach)

    def close(self) -> Ended:
        """End without BYE: the terminal given back; idempotent."""
        if self._ended is not None:
            return self._ended
        return self._end(Ended("closed"))

    def __enter__(self) -> "Attach":
        return self

    def __exit__(self, kind, value, traceback) -> bool:
        self.close()
        return False

    # -- the one ending routine, and the guard every method runs its body in

    def _end(self, ended: Ended) -> Ended:
        if self._ended is not None:
            return self._ended
        try:
            if self._link is not None:
                self._link.close()
        finally:
            try:
                self._term.close()
            finally:
                self._ended = ended
        return ended

    def _guard(self, body, *args):
        try:
            return body(*args)
        except _End as end:
            return self._end(end.ended)
        except BaseException as e:
            self._end(Ended("closed", type(e).__name__))
            raise

    # -- the bodies

    def _connect(self, target: object, caps: object) -> object:
        size = self._term.size
        got = _t.connect(target, Hello(VERSIONS, size, caps), uid=self._uid,
                         timeout=self._handshake, now=self._now)
        if isinstance(got, Fault):
            raise _End(Ended("refused", fault=got))
        if isinstance(got, Closed):
            raise _End(Ended("dropped", closed=got))
        self._link, self._welcome = got
        self._sent_size = size
        self._bound(size)
        return caps

    def _turn(self, timeout: "float | None") -> bytes:
        link, term = self._link, self._term
        wait = self._tick if timeout is None else max(0, min(timeout, self._tick))
        self._wait(wait)
        drawn = self._receive()
        gone = link.flush()
        if gone is not None:
            raise _End(Ended("dropped", closed=gone))
        data = term.read(timeout=0)
        if isinstance(data, Closed):
            raise _End(Ended("terminal", closed=data))
        if term.size != self._sent_size:
            (w0, h0), (w1, h1) = self._cover, term.size
            self._bound((max(w0, w1), max(h0, h1)))     # frames of the old size may still come
            gone = _t.send(link, Resize(term.size))
            if gone is not None:
                raise _End(Ended("dropped", closed=gone))
            self._sent_size = term.size
            drawn = True
        if any(getattr(e, "kind", None) in _REDRAW for e in term.events):
            drawn = True
        if drawn and self._grid is not None:
            # `fit` may hand over the grid itself, which later frames write into: safe, as
            # Display keeps a copy of what it showed as its front (Buffer's `show`).
            grid, cursor = fit(self._grid, term.size, self._cursor)
            gone = _term.show(term, grid, cursor=cursor)
            if gone is not None:
                raise _End(Ended("terminal", closed=gone))
        return data

    def _wait(self, wait: float) -> None:
        link = self._link
        wants = {}
        for fd in self._term.fds:
            wants[fd] = wants.get(fd, 0) | select.POLLIN
        wants[link.fd_in] = wants.get(link.fd_in, 0) | select.POLLIN
        if link.pending:
            wants[link.fd_out] = wants.get(link.fd_out, 0) | select.POLLOUT
        _t.poll(wants, wait)

    def _bound(self, size: "tuple[int, int]") -> None:
        if size != self._cover:
            self._link.limit = frame_limit(*size)
            self._cover = size

    def _receive(self) -> bool:
        # One read's worth of frames (at most CHUNK bytes beyond one incomplete message),
        # then back to the terminal: a flood cannot hold the detach key back.
        got = self._link.receive(0)
        if isinstance(got, Closed):
            raise _End(Ended("dropped", closed=got))
        applied = False
        for m in got:
            if isinstance(m, Frame):
                grid = apply(self._grid, m, own=True)
                if isinstance(grid, Malformed):
                    raise _End(Ended("malformed", grid.reason))
                self._grid, self._cursor = grid, m.cursor
                if m.size == self._sent_size:
                    self._bound(m.size)
                applied = True
            elif isinstance(m, Bye):
                raise _End(Ended("bye", m.reason))
            elif isinstance(m, Malformed):
                raise _End(Ended("malformed", m.reason))
            else:
                raise _End(Ended("malformed", "order"))
        return applied

    def _send(self, data: bytes) -> None:
        if not data:
            return None
        chunk = _t.CHUNK                    # the server's MAX_INPUT holds one INPUT of CHUNK bytes
        gone = _t.send(self._link, *(Input(data[i:i + chunk]) for i in range(0, len(data), chunk)))
        if gone is not None:
            raise _End(Ended("dropped", closed=gone))
        return None

    def _detach(self) -> Ended:
        if self._link is not None:
            self._link.queue(Bye("detach"))
            self._link.drain(self._tick)
        return self._end(Ended("detach"))
