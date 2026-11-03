"""[Remote]: serve headless; attach locally or over ssh; one display per client, at its
size and caps; an attaching client opens its own terminal.

Kind: system (the expansion of [Remote] in Edge). Depends on Buffer (diffs, grids, the
client's {Display} through `show`), Core ({Caps}) and Term (the attaching terminal, and
the shared {Closed} it re-exports); nothing else in cure (not Clock: an app waiting on
more fds uses Clock's [Wait] over `Server.fds` / `Attach.fds` itself, then steps with
timeout 0).

herdr-style: the app runs in a [Server]; terminals attach to it through [Attach]. A
session is a name; each session has one owner-only unix socket
(`$XDG_RUNTIME_DIR/<app>/<session>.sock`, else `/tmp/<app>-<uid>/<session>.sock`, in a
0700 directory, the socket 0600, another user's peer refused); over ssh the app spawns
`ssh host <app> attach --stdio <session>` and attaches over its stdio, the far side
relaying to the session's socket ([Relay], in `relay.py`): no port of its own. The
[Protocol] is versioned, framed (a 4-byte length, a kind byte, a JSON or raw payload)
and carries cell diffs only, never terminal bytes (cells_only). A slow client gets the
latest frame, not a queue; input is never dropped. A client that leaves is a
<Detached>; its session, and the app's state, live on. Every way an attachment ends
gives the terminal back (restored).

The app owns the loop: nothing here runs one, starts a thread, installs a handler or
keeps process-wide state. All I/O is in [Transport] (sockets, pipes, poll); [Protocol]
is pure (bytes in, values out), so the whole format is testable over
`socket.socketpair()` without a terminal.

The boundary (the ops other parts call), defined in the modules and re-exported here:
- `serve(sessions, *, app, ...) -> Server | Fault` ((Construct) -> [Remote] :
  serve({Sessions}) => {Clients}): see [Server] (`server.serve`).
- `attach(term, target, modes=None, *, uid=None, ...) -> tuple[Attach, Caps | Ended]`
  ((Construct) -> [Remote] : attach({Session}) => {Caps}): an `Attach` built and
  opened at the session's `target`; see [Attach] (`attach.attach`). The `Attach`
  class stays public beside it, unchanged (construct's console builds it, then
  calls `open`). The function shadows the submodule's name on the package:
  `cure.edge.remote.attach` is the op; the module is
  `importlib.import_module("cure.edge.remote.attach")`, and `from
  cure.edge.remote.attach import ...` reaches it as before.
- `connect(target, hello, ...) -> (Link, Welcome) | Fault | Closed` ((Client) ->
  [Transport] : connect({Hello}) => {Diffs}): see [Transport] (`transport.connect`).
- `listen(server, session, path) -> Fault | None` ((Construct) -> [Server] :
  listen({Session}) => {Fault}) and `open(attach, target, modes=None) -> Caps | Ended`
  ((Construct) -> [Attach] : open({Session}) => {Caps}): one-line forwarders to the
  methods, module-level in `server.py` and `attach.py`, not re-exported here (the
  package's `listen` is [Transport]'s; a package-level `open` would shadow the builtin).
- `[Remote] -> [Term] : open` is [Attach]'s, and so is `[Attach] -> [Term] : show`
  (Term's module-level `show`, through the term's own {Display});
  `[Remote] -> [Buffer] : diff` is [Server]'s (each client's frame against the last).
- `[Server] / [Attach] -> [Transport] : poll`: Transport's one wait (every fd's
  revents), also [Relay]'s; a Transport-module name, not re-exported here (an app
  waiting on more fds uses Clock's [Wait], as above).
- `[Relay] -> (Client) : step`: see [Relay] (`relay.step`, the module-level op).

Re-exported for consumers: `Server`, `serve`, `Attached`, `Typed`, `Resized` (server);
`Detached` (detached); `Ended` (ended); `Attach`, `attach`, `fit` (attach); `Relay` (relay);
`Link`, `Listener`, `Client`, `Fault`, `listen`, `dial`, `connect`, `accept`, `events`,
`send`, `socket_dir`, `socket_path`, `secure_dir` (transport); `Hello`, `Input`, `Resize`,
`Bye`, `Welcome`, `Refuse`, `Frame`, `Malformed`, `Decoder`, `encode`, `decode`,
`frame`, `apply`, `negotiate`, `valid_name`, `VERSION`, `VERSIONS`, `MAX_FRAME`,
`MAX_SIDE` (protocol).

Inputs, outputs and errors: as each module states. Effects: [Transport]'s (sockets,
pipes, poll), [Relay]'s through it, and, through [Attach], Term's.

Usage:
    # the server process (construct serve):
    from cure.core.buffer import Grid, put
    from cure.edge.remote import serve, Fault, Attached, Typed, Resized, Detached
    srv = serve(["main"], app="construct")
    if isinstance(srv, Fault):
        ...                                     # "taken": a live server serves "main"
    while running:
        for ev in srv.step(0.25):
            if isinstance(ev, (Attached, Resized, Typed)):
                c = ev.client
                srv.show(c, put(Grid(*c.size), 0, 0, "hello"))
    srv.close()

    # the attaching process (construct attach main):
    from cure.edge.term import Term
    from cure.edge.remote import Attach, Ended, socket_path
    with Attach(Term(0, 1, signals=True)) as a:
        r = a.open(socket_path("construct", "main"))
        while not isinstance(r, Ended):
            r = a.step(0.25)
            if isinstance(r, bytes) and r:
                r = a.send(r) or b""
"""

from .attach import Attach, attach, fit
from .detached import Detached
from .ended import Ended
from .protocol import (MAX_FRAME, MAX_SIDE, VERSION, VERSIONS, Bye, Decoder, Frame, Hello,
                       Input, Malformed, Refuse, Resize, Welcome, apply, decode, encode,
                       frame, negotiate, valid_name)
from .server import Attached, Resized, Server, Typed, serve
from .relay import Relay
from .transport import (Client, Fault, Link, Listener, accept, connect, dial, events, listen,
                        secure_dir, send, socket_dir, socket_path)
