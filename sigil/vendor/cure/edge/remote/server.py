"""[Server]: herdr-style: the app runs in a server, terminals attach to it; sessions by
name; the app's state outlives a detach; a unix socket (owner-only), or ssh stdio: no
port of its own.

Kind: service (a class with explicit state, the events it returns, `serve`, and the
flow's module-level op `listen`). The
server is the app's side of Remote. It has no loop and no thread: the app calls `step`
from its own loop (or waits on `fds` / `writing` with Clock's [Wait] among its other
fds, then calls `step(0)`), reads the events it returns (who attached, what they
typed, who resized, who left), paints each client a frame at that client's own size
and caps, and hands it to `show`. The server sends cell diffs only ([Protocol]'s
cells_only); it keeps no app state and no {Display}: each client's own [Attach] draws
the cells on its own terminal.

Data (frozen dataclasses: the events `step` returns, besides <Detached>):
- `Attached(client)`: a client finished its handshake; `client` is its [Transport]
  `Client` (id, session, version, size, caps). The app paints it a first frame.
- `Typed(client, data)`: `data` (`bytes`, non-empty) is what the person typed at that
  client's terminal, raw, exactly as one INPUT carried it: the app decodes it with
  Input's decoder at `client.caps`. Input is never dropped, merged or reordered.
- `Resized(client, size)`: the client's terminal is now `size` (`client.size` already
  is). The app paints it a frame at the new size.
- {Detached} (<Detached>, from `detached.py`): an attached client left; the session
  lives on.

The handle:
- `Server(sessions, *, uid=None, tick=TICK, handshake=HANDSHAKE, now=time.monotonic)`:
  `sessions` the names this server serves (an iterable of `valid_name` strs, unique,
  at least one), in order; `uid` the owner (`None`: `os.getuid()`); `tick` seconds >
  0, the longest one `step` waits; `handshake` seconds > 0, how long a new connection
  may take to say HELLO; `now` a callable giving monotonic seconds. A new Server
  listens nowhere: `listen` binds a session's socket, `adopt` takes a connection the
  app already holds (ssh stdio, a socketpair in a test).
  Read-only attributes: `sessions` (the names, in order); `paths` (`{session: path}`
  of the sockets bound); `clients` (the attached `Client`s, by id ascending); `fds`
  (the fds to wait on for reading: listeners in session order, less any backing off
  (see `step`), then connections not yet attached in arrival order, then clients by
  id); `writing` (the out fds of
  connections with bytes queued, same order); `closed` (`bool`).
  A context manager: `__exit__` calls `close()` and lets any exception go on.
- `listen(session, path) -> None | Fault`: [Transport]'s `listen(path, uid=uid)` for
  that session (one socket per session: `socket_path(app, session)`); a {Fault}
  (`"unsafe"`, `"taken"`, `"error"`) is returned and nothing is kept.
- `adopt(target, session) -> None`: `target` a connected `socket.socket` (owned from
  now on) or `(fd_in, fd_out)`; it becomes a connection awaiting HELLO, exactly as one
  `incoming` from a listener would (the deadline starts now). The target is checked by
  [Transport]'s `Link(target, side="server")` itself (its own first check: the same
  `TypeError` / `ValueError` before anything is built); `adopt` makes no check of its
  own and calls no private Transport name (not `_pair`).
- `step(timeout=None) -> tuple[Attached | Typed | Resized | Detached, ...]`:
  1. Wait: one [Transport] `poll` over `fds` (`POLLIN`) and `writing` (`POLLOUT`) for
     at most `t` seconds, `t = tick` when `timeout` is `None`, else
     `max(0, min(timeout, tick))` (`@timeout(tick)`; `[Server] -> [Transport] :
     poll({Fds}) => {Revents}`); with nothing to wait on yet, the same `poll({}, t)`
     sleeps `t`. Its `{fd: revents}` say which listeners, connections and clients the
     steps below read.
  2. Listeners, in session order: each readable one's `incoming()` until it returns
     `None` or `BACKLOG` connections were taken this step; each new connection
     awaits HELLO, its deadline `now() + handshake`. A listener's {Fault} is not an
     event: that listener is skipped this step. A Fault whose errno is EMFILE, ENFILE,
     ENOBUFS or ENOMEM (no fd or memory for the connection, which stays queued, so
     the listener stays readable) also backs the listener off: it is out of `fds`,
     and so of step 1's poll, until `now()` reaches the Fault's time plus the back-off,
     which starts at `ACCEPT_BACKOFF` (0.05 s), doubles on each such Fault in a row up
     to 1.0 s, and resets on the listener's next accepted connection. Other listeners,
     connections and clients are served meanwhile; a Fault of another errno does not
     back off.
  3. Connections awaiting HELLO, in arrival order: readable ones `receive(0)`. The
     first message a `Hello`: [Transport]'s `accept(link, hello, session=...,
     ident=next id)`: a `Client` gives `Attached(client)` (ids from 1, ascending,
     never reused), and the messages after the HELLO in the same read go through
     [Transport]'s `received(client, rest)` (a RESIZE among them sets `client.size`)
     and are handled as in step 4 for it; a `Refuse` is flushed once (non-blocking) and the link closed.
     Anything else first (or a `Malformed`): `Refuse("hello", VERSIONS)` flushed once,
     link closed. A {Closed}, or `now()` past the deadline: closed, silently. None of
     these but `Attached` is an event: a connection never attached never detaches.
     An accepted client's link reads at [Protocol]'s `MAX_INPUT` from its HELLO on (set
     by [Transport]: a HELLO and a full `CHUNK` INPUT may come in one read): a body
     over it ends the client as `"malformed"`, `"size"`, in step 4, at its prefix.
  4. Clients, by id: readable ones: [Transport]'s `events(client, 0)`, each item in
     order: `Input(data)` with data: `Typed(client, data)` (an empty INPUT is
     nothing); `Resize(size)`: `Resized(client, size)`; `Bye(r)`: the link closed,
     `Detached(id, session, "bye", r)`, and nothing more is read from it; a
     `Malformed(m)`: `Bye("malformed")` flushed once, link closed,
     `Detached(..., "malformed", m.reason)`; a {Closed}: `Detached(..., "dropped",
     closed=it)`. Then, for each client still attached: `flush()`; a {Closed} is
     `"dropped"` as above; when its outbox is now empty and a latest frame waits
     (see `show`), that frame is sent. A drop met inside `show` is reported here, at
     this client's place.
  The events come in that order (steps 3, then 4); `()` when nothing happened. A step
  on a closed server returns `()`.
  A client's size is [Transport]'s to keep, and the Server never writes it (nor any
  private field of a `Client`): `accept` sets it from the HELLO; every RESIZE the
  Server handles reaches it through Transport first, `events` in step 4 and
  `received` for step 3's messages after the HELLO, which `events` never sees (they
  came in the read that carried the HELLO, taken by `receive(0)` before there was a
  `Client`). Those are the only paths a message reaches `step`'s handling by, so
  `Resized(client, size)` always finds `client.size == size`.
- `show(client, grid, *, cursor=None) -> None`: give `client` this frame (the app
  paints it at `client.size` and `client.caps`; another size is allowed: the client
  fits it to its terminal). The slow-client rule, per client, with `front` the last
  grid encoded for it (`None` at first), `sent` the cursor then, `latest` a waiting
  frame:
  - the client's outbox is not empty (an earlier frame is still on its way): `latest
    = (copy of grid, cursor)`, replacing any earlier waiting frame; nothing is
    encoded;
  - else: `changes = diff(front, grid)` (Buffer); when `changes` is empty and
    `cursor == sent` and `front` is not `None`: nothing (the idle frame is silent);
    otherwise `send(link, Frame(grid.size, changes, cursor))` ([Transport]'s module
    `send`, `[Server] -> [Transport] : send({Frame})`: the link encodes the message with
    [Protocol]'s `encode`, the bytes `frame(changes, grid.size, cursor=cursor)` gives,
    queues it and flushes without blocking), then `front = copy of grid`, `sent =
    cursor`, `latest = None`. A `ValueError` from the encode (`MAX_FRAME`) comes before
    any of these: nothing is queued or changed. On a link already closed the frame is
    dropped and `send`'s {Closed} ignored here (the drop is reported by the next
    `step`). The server never writes a link's outbox itself: Transport's `send` is its
    way to put a FRAME on a link, `Link.queue` then `flush` its way for BYE and REFUSE
    (WELCOME goes through `accept`).
  So each client has at most one encoded frame in flight plus one waiting grid: no
  queue grows with a slow client; frames coalesce to the latest, and the diff is
  always against what the client will hold once the earlier frame lands. A client no
  longer attached (or not this server's): nothing happens.
- `detach(client, reason="detached") -> Detached | None`: the app ends one client's
  attachment: `Bye(reason)` queued, `flush()` once (non-blocking), link closed; returns
  `Detached(id, session, "detached", reason)` (and `step` will not report it again);
  `None` when the client is no longer attached.
- `close() -> None`: every client gets `Bye("end")`, flushed once (non-blocking); every
  link closed (no `Detached` is returned for them: the server is ending, not the
  session's clients leaving); connections awaiting HELLO closed; each listener closed
  (its own socket file unlinked; the directory stays). Idempotent; nothing raises.

`serve(sessions, *, app, env=None, uid=None, tick=TICK, handshake=HANDSHAKE,
now=time.monotonic) -> Server | Fault` ((Construct) -> [Remote] : serve({Sessions}) =>
{Clients}): a `Server(sessions, ...)` listening on each session's socket: for each name
in order, `path = socket_path(app, name, env=env, uid=uid)`, `secure_dir(dirname)`,
then `listen(name, path)`. The first {Fault} closes what was opened and is returned.
The server's clients then arrive through `step` ({Clients}).

`listen(server, session, path) -> Fault | None` ((Construct) -> [Server] :
listen({Session}) => {Fault}): `server.listen(session, path)`, nothing else (the drawn
op, as Term's `open` / `show`); the method's own checks give the errors. Not
re-exported by Remote's face, whose `listen` is [Transport]'s.

Laws (a test can loop over them):
- latest: for any client that reads nothing while `show` is called with grids `g1..gn`
  (any sizes), the bytes queued for it never exceed one encoded frame plus control
  messages (WELCOME, BYE); once it reads everything and the server steps until its
  outbox is empty, the client's grid after [Protocol]'s `apply` of every FRAME it
  received `==` `gn`, and its cursor is the last one shown.
- convergence: for any interleaving of `show` and `step`, a client that reads all
  holds exactly the last grid shown to it.
- one Detached: every `Attached(c)` is followed by exactly one `Detached` with
  `client == c.id` (from `step` or `detach`), or by `close()`.

Inputs: as above; `grid` a Buffer {Grid} (each side `1..MAX_SIDE`); `cursor` `None` or
  `(x, y)` inside the grid; `client` a [Transport] `Client`.
Outputs: `step`: a tuple of events (Attached, Typed carrying the raw input {Bytes},
  Resized, <Detached>); `serve`: a {Server} or a {Fault}; `listen`: `None` or a
  {Fault}; `detach`: a {Detached} or `None`.
Errors (the caller's own wrong arguments only; no `OSError` escapes, a peer's failure
  is an event): `Server(...)` / `serve`: `TypeError` when `sessions` is not an iterable
  of `str`, `uid` is not an `int`, `tick` / `handshake` is not a real number (a `bool`
  refused), or `now` is not callable; `ValueError` when a name is not `valid_name`,
  names repeat, there are none, or `tick` / `handshake` <= 0. `listen` / `adopt`:
  `ValueError` when `session` is not one of `sessions`; `adopt`: `TypeError` for a
  target of the wrong type. `show`: `TypeError` when `client` is not a [Transport]
  `Client`, `grid` is not a `Grid` or `cursor`
  is neither `None` nor a 2-tuple of ints; `ValueError` when a grid side exceeds
  `MAX_SIDE`, `cursor` is outside the grid, or the frame would exceed `MAX_FRAME`
  ([Protocol]'s `encode`); on an error nothing is queued or changed. `step`:
  `TypeError` / `ValueError` for a bad `timeout`. `detach`: `ValueError` when `reason`
  is not a `WORD`. Any of these after `close()`: `RuntimeError` (except `close`, a
  no-op, and `step`, which returns `()`).
Effects: through [Transport] only: the session sockets (bind, accept, send, recv,
  unlink of our own socket files) and its `poll`; `now()`. No thread, no signal
  handler, no process-wide state; it never spawns a process (ssh is the app's).

Constants: `ACCEPT_BACKOFF = 0.05` (seconds, a listener's first back-off at EMFILE,
ENFILE, ENOBUFS or ENOMEM; doubled on each in a row, to 1.0 s at most).

Usage:
    import socket
    from cure.core.buffer import Grid, put
    from cure.edge.remote import serve, Server, Attached, Typed, Detached
    srv = serve(["main"], app="construct")         # Server | Fault: the socket is bound
    # or, without a socket (a test, or the app's own ssh stdio):
    srv = Server(["main"])
    a, b = socket.socketpair()
    srv.adopt(a, "main")                            # b is the client's end
    # the app's loop:
    for ev in srv.step(0.5):
        if isinstance(ev, Attached):                # paint it a first frame
            w, h = ev.client.size
            srv.show(ev.client, put(Grid(w, h), 0, 0, "hello"))
        elif isinstance(ev, Typed):
            ...                                     # decode ev.data at ev.client.caps
        elif isinstance(ev, Detached):
            ...                                     # the session lives on
    srv.close()
"""

import errno
import math
import numbers
import os
import re
import select
import time
from dataclasses import dataclass

from cure.core.buffer import Grid, diff
from cure.edge.term import Closed

from . import transport as _t
from .detached import Detached
from .protocol import (MAX_SIDE, VERSIONS, WORD, Bye, Frame, Hello, Input, Malformed, Refuse,
                       Resize, valid_name)
from .transport import HANDSHAKE, TICK, Client, Fault

__all__ = ["Attached", "Typed", "Resized", "Detached", "Server", "serve"]

ACCEPT_BACKOFF = 0.05
_BACKOFF_MOST = 1.0
_BACKING = frozenset((errno.EMFILE, errno.ENFILE, errno.ENOBUFS, errno.ENOMEM))

_WORD = re.compile(WORD)


@dataclass(frozen=True)
class Attached:
    """A client finished its handshake."""

    client: Client


@dataclass(frozen=True)
class Typed:
    """What the person typed at a client's terminal: raw bytes, for the app to decode."""

    client: Client
    data: bytes


@dataclass(frozen=True)
class Resized:
    """A client's terminal has a new size."""

    client: Client
    size: "tuple[int, int]"


def _seconds(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"{name} must be a real number, got {type(value).__name__}")
    if math.isnan(value) or value <= 0:
        raise ValueError(f"{name} must be > 0, got {value}")
    return value


def _names(sessions: object) -> "tuple[str, ...]":
    if isinstance(sessions, str):
        raise TypeError("sessions must be an iterable of str, not a str")
    try:
        names = tuple(sessions)
    except TypeError:
        raise TypeError(f"sessions must be an iterable of str, got {type(sessions).__name__}") from None
    for n in names:
        if not isinstance(n, str):
            raise TypeError(f"a session must be a str, got {type(n).__name__}")
        if not valid_name(n):
            raise ValueError(f"not a session name: {n!r}")
    if not names:
        raise ValueError("a server serves at least one session")
    if len(set(names)) != len(names):
        raise ValueError("session names repeat")
    return names


class _Waiting:
    """A connection that has not said HELLO yet."""

    __slots__ = ("link", "session", "deadline")

    def __init__(self, link: "_t.Link", session: str, deadline: float) -> None:
        self.link, self.session, self.deadline = link, session, deadline


class _View:
    """What the server keeps per client: the last grid encoded, its cursor, the waiting frame."""

    __slots__ = ("front", "sent", "latest")

    def __init__(self) -> None:
        self.front = None
        self.sent = None
        self.latest = None


class Server:
    """The app's side of Remote: sessions, clients, the latest-frame rule; stepped by the app."""

    def __init__(self, sessions: object, *, uid: "int | None" = None, tick: float = TICK,
                 handshake: float = HANDSHAKE, now: object = time.monotonic) -> None:
        names = _names(sessions)
        if uid is not None and (isinstance(uid, bool) or not isinstance(uid, int)):
            raise TypeError(f"uid must be an int, got {type(uid).__name__}")
        _seconds(tick, "tick")
        _seconds(handshake, "handshake")
        if not callable(now):
            raise TypeError(f"now must be callable, got {type(now).__name__}")
        self._sessions = names
        self._uid = os.getuid() if uid is None else uid
        self._tick = tick
        self._handshake = handshake
        self._now = now
        self._listeners: dict = {}
        self._backoff: dict = {}            # session -> (until, its back-off): a listener out of the poll
        self._waiting: list = []
        self._clients: dict = {}
        self._views: dict = {}
        self._next = 1
        self._closed = False

    @property
    def sessions(self) -> "tuple[str, ...]":
        """The session names, in order."""
        return self._sessions

    @property
    def paths(self) -> "dict[str, str]":
        """The socket path bound per session."""
        return {s: self._listeners[s].path for s in self._sessions if s in self._listeners}

    @property
    def clients(self) -> "tuple[Client, ...]":
        """The attached clients, by id."""
        return tuple(self._clients[i] for i in sorted(self._clients))

    @property
    def fds(self) -> "tuple[int, ...]":
        """The fds to wait on for reading."""
        now = self._now() if self._backoff else None
        out = [self._listeners[s].fd for s in self._sessions
               if s in self._listeners and not self._backing(s, now)]
        out += [w.link.fd_in for w in self._waiting]
        out += [c.link.fd_in for c in self.clients]
        return tuple(out)

    @property
    def writing(self) -> "tuple[int, ...]":
        """The fds with bytes queued, to wait on for writing."""
        links = [w.link for w in self._waiting] + [c.link for c in self.clients]
        return tuple(L.fd_out for L in links if L.pending)

    @property
    def closed(self) -> bool:
        """Whether `close` has run."""
        return self._closed

    def listen(self, session: str, path: str) -> "Fault | None":
        """Bind `session`'s owner-only socket at `path`."""
        self._open()
        self._session(session)
        if session in self._listeners:
            return Fault("taken", path, f"this server already listens for {session!r}")
        got = _t.listen(path, uid=self._uid)
        if isinstance(got, Fault):
            return got
        self._listeners[session] = got
        return None

    def adopt(self, target: object, session: str) -> None:
        """Take a connection the app holds; it awaits HELLO."""
        self._open()
        self._session(session)
        self._await(_t.Link(target, side="server"), session)
        return None

    def step(self, timeout: "float | None" = None) -> tuple:
        """Wait at most `min(timeout, tick)`, then accept, read and flush: the events, in order."""
        if timeout is not None:
            if isinstance(timeout, bool) or not isinstance(timeout, numbers.Real):
                raise TypeError(f"timeout must be None or a real number, got {type(timeout).__name__}")
            if math.isnan(timeout):
                raise ValueError("timeout must not be NaN")
        if self._closed:
            return ()
        wait = self._tick if timeout is None else max(0, min(timeout, self._tick))
        ready = self._wait(wait)
        events: list = []
        self._accept(ready)
        fresh = self._handshakes(ready, events)
        self._read(ready, fresh, events)
        self._flush(events)
        return tuple(events)

    def show(self, client: Client, grid: object, *, cursor: "tuple[int, int] | None" = None) -> None:
        """Send `client` this frame as a cell diff, or keep it as the latest while one is in flight."""
        self._open()
        if not isinstance(client, Client):
            raise TypeError(f"client must be a Client, got {type(client).__name__}")
        if not isinstance(grid, Grid):
            raise TypeError(f"grid must be a Grid, got {type(grid).__name__}")
        if cursor is not None:
            if (not isinstance(cursor, tuple) or len(cursor) != 2
                    or not all(isinstance(v, int) and not isinstance(v, bool) for v in cursor)):
                raise TypeError(f"cursor must be None or a 2-tuple of ints, got {cursor!r}")
        w, h = grid.size
        if not (1 <= w <= MAX_SIDE and 1 <= h <= MAX_SIDE):
            raise ValueError(f"a grid side must be 1..{MAX_SIDE}, got {w} x {h}")
        if cursor is not None and not (0 <= cursor[0] < w and 0 <= cursor[1] < h):
            raise ValueError(f"cursor {cursor} is outside {w} x {h}")
        if self._clients.get(client.id) is not client:
            return None
        view = self._views[client.id]
        if client.link.pending:
            view.latest = (grid.copy(), cursor)
            return None
        self._paint(client, view, grid, cursor, copy=True)
        return None

    def detach(self, client: Client, reason: str = "detached") -> "Detached | None":
        """End one client's attachment: BYE, close, and its Detached."""
        self._open()
        if not isinstance(reason, str) or _WORD.fullmatch(reason) is None:
            raise ValueError(f"reason must be a WORD, got {reason!r}")
        if not isinstance(client, Client) or self._clients.get(client.id) is not client:
            return None
        self._part(client, Bye(reason))
        return Detached(client.id, client.session, "detached", reason)

    def close(self) -> None:
        """BYE to every client, close every link and listener; idempotent."""
        if self._closed:
            return None
        self._closed = True
        for client in self.clients:
            try:
                self._part(client, Bye("end"))
            except Exception:
                client.link.close()
        for waiting in self._waiting:
            waiting.link.close()
        self._waiting = []
        for session in self._sessions:
            listener = self._listeners.pop(session, None)
            if listener is not None:
                listener.close()
        return None

    def __enter__(self) -> "Server":
        return self

    def __exit__(self, kind, value, traceback) -> bool:
        self.close()
        return False

    # -- helpers

    def _open(self) -> None:
        if self._closed:
            raise RuntimeError("the server is closed")

    def _session(self, session: object) -> None:
        if session not in self._sessions:
            raise ValueError(f"not one of this server's sessions: {session!r}")

    def _await(self, link: "_t.Link", session: str) -> None:
        self._waiting.append(_Waiting(link, session, self._now() + self._handshake))

    def _wait(self, wait: float) -> "dict[int, int]":
        wants: dict = {}
        for fd in self.fds:
            wants[fd] = wants.get(fd, 0) | select.POLLIN
        for fd in self.writing:
            wants[fd] = wants.get(fd, 0) | select.POLLOUT
        return _t.poll(wants, wait)

    def _backing(self, session: str, now: "float | None") -> bool:
        held = self._backoff.get(session)
        return held is not None and now < held[0]

    def _accept(self, ready: "dict[int, int]") -> None:
        now = self._now() if self._backoff else None
        for session in self._sessions:
            listener = self._listeners.get(session)
            if listener is None or not ready.get(listener.fd, 0) or self._backing(session, now):
                continue
            for _ in range(_t.BACKLOG):
                got = listener.incoming()
                if isinstance(got, Fault):
                    if got.errno in _BACKING:
                        self._back_off(session)
                    break
                if got is None:
                    break
                self._backoff.pop(session, None)
                self._await(got, session)

    def _back_off(self, session: str) -> None:
        # Out of the poll until the back-off passes; its length doubles on each Fault in a row.
        held = self._backoff.get(session)
        delay = ACCEPT_BACKOFF if held is None else min(2 * held[1], _BACKOFF_MOST)
        self._backoff[session] = (self._now() + delay, delay)

    def _handshakes(self, ready: "dict[int, int]", events: list) -> set:
        fresh = set()
        still = []
        for waiting in self._waiting:
            link = waiting.link
            got = link.receive(0) if ready.get(link.fd_in, 0) else ()
            if isinstance(got, Closed):
                link.close()
                continue
            if not got:
                if self._now() > waiting.deadline:
                    link.close()
                else:
                    still.append(waiting)
                continue
            first, rest = got[0], got[1:]
            if not isinstance(first, Hello):
                self._refuse(link, Refuse("hello", VERSIONS))
                continue
            ident = self._next
            result = _t.accept(link, first, session=waiting.session, ident=ident)
            if isinstance(result, Refuse):
                link.close()
                continue
            self._next += 1
            self._clients[ident] = result
            self._views[ident] = _View()
            fresh.add(ident)
            events.append(Attached(result))
            self._handle(result, _t.received(result, rest), events)
        self._waiting = still
        return fresh

    def _refuse(self, link: "_t.Link", refuse: Refuse) -> None:
        link.queue(refuse)
        link.flush()
        link.close()

    def _read(self, ready: "dict[int, int]", fresh: set, events: list) -> None:
        for client in self.clients:
            if client.id in fresh or not ready.get(client.link.fd_in, 0):
                continue
            got = _t.events(client, 0)
            if isinstance(got, Closed):
                self._dropped(client, got, events)
            else:
                self._handle(client, got, events)

    def _handle(self, client: Client, messages: tuple, events: list) -> None:
        for m in messages:
            if isinstance(m, Input):
                if m.data:
                    events.append(Typed(client, m.data))
            elif isinstance(m, Resize):
                events.append(Resized(client, m.size))
            elif isinstance(m, Bye):
                self._forget(client)
                client.link.close()
                events.append(Detached(client.id, client.session, "bye", m.reason))
                return
            elif isinstance(m, Malformed):
                self._part(client, Bye("malformed"))
                events.append(Detached(client.id, client.session, "malformed", m.reason))
                return
            else:
                self._part(client, Bye("malformed"))
                events.append(Detached(client.id, client.session, "malformed", "order"))
                return

    def _flush(self, events: list) -> None:
        for client in self.clients:
            gone = client.link.flush()
            if gone is None and not client.link.pending:
                view = self._views[client.id]
                if view.latest is not None:
                    grid, cursor = view.latest
                    view.latest = None
                    try:
                        self._paint(client, view, grid, cursor, copy=False)
                    except ValueError:
                        pass      # a waiting frame too large to encode: dropped, the next show retries
                    gone = client.link.closed
            if gone is not None:
                self._dropped(client, gone, events)

    def _paint(self, client: Client, view: _View, grid: Grid, cursor: object, *, copy: bool) -> None:
        changes = diff(view.front, grid)
        if not changes and cursor == view.sent and view.front is not None:
            view.latest = None
            return
        _t.send(client.link, Frame(grid.size, changes, cursor))   # encodes first; a Closed ignored
        view.front = grid.copy() if copy else grid
        view.sent = cursor
        view.latest = None

    def _dropped(self, client: Client, closed: Closed, events: list) -> None:
        self._forget(client)
        client.link.close()
        events.append(Detached(client.id, client.session, "dropped", closed=closed))

    def _part(self, client: Client, bye: Bye) -> None:
        self._forget(client)
        client.link.queue(bye)
        client.link.flush()
        client.link.close()

    def _forget(self, client: Client) -> None:
        self._clients.pop(client.id, None)
        self._views.pop(client.id, None)


def listen(server: Server, session: str, path: str) -> "Fault | None":
    """`server.listen(session, path)`: (Construct) -> [Server] : listen({Session}) => {Fault}; None or its {Fault}."""
    return server.listen(session, path)


def serve(sessions: object, *, app: str, env: object = None, uid: "int | None" = None,
          tick: float = TICK, handshake: float = HANDSHAKE, now: object = time.monotonic) -> "Server | Fault":
    """A Server listening on each session's owner-only socket, or the first Fault."""
    if not valid_name(app):
        raise ValueError(f"app is not a name: {app!r}")
    srv = Server(sessions, uid=uid, tick=tick, handshake=handshake, now=now)
    try:
        for name in srv.sessions:
            path = _t.socket_path(app, name, env=env, uid=uid)
            fault = _t.secure_dir(os.path.dirname(path), uid=uid)
            if fault is None:
                fault = srv.listen(name, path)
            if fault is not None:
                srv.close()
                return fault
    except BaseException:
        srv.close()
        raise
    return srv
