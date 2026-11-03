"""[Transport]: the bytes between a server and its clients: an owner-only unix socket, or a
pair of pipes (ssh stdio); framed messages, non-blocking, no threads, no port.

Kind: service (classes with explicit state and the functions that drive them). The one
part of Remote that touches sockets and pipes: it binds, connects, accepts, reads and
writes, and hands every byte to [Protocol] to frame or unframe. It never waits longer
than the timeout it is given, never blocks on a slow peer, never changes an fd's
flags (it reads only after poll says readable and writes non-blocking), and runs no
loop: [Server], [Attach] and the app call it from their own loop. A dropped peer is a
Term {Closed} returned (the shared edge event, re-exported by Term); every other failure
is a {Fault} returned. No `OSError` escapes, but `poll(2)`'s own (see `poll`).

Where a session lives (pure helpers):
- `socket_dir(app, *, env=None, uid=None) -> str`: with `env` (a mapping; `None`:
  `os.environ`) and `uid` (`None`: `os.getuid()`): `os.path.join(X, app)` when
  `X = env["XDG_RUNTIME_DIR"]` is set and is an absolute path; else
  `os.path.join(T, f"{app}-{uid}")` where `T` is `env["TMPDIR"]` when set and
  absolute, else `"/tmp"`. `app` must be a name (`valid_name`).
- `socket_path(app, session, *, env=None, uid=None) -> str`:
  `os.path.join(socket_dir(...), f"{session}.sock")`; `session` a name. One socket per
  session: the socket's path IS the session's name, so two sessions never collide and
  a second server for one name meets the first (see `listen`). A long one is accepted
  (see the two routes): a session's name always fits `MAX_LEAF`.

Two routes (M2, round 19): a socket path `p` is short when its UTF-8 bytes (surrogates
escaped) are at most `MAX_PATH` (103, the smaller of Linux's and macOS's `sun_path`
limits), and long otherwise.
- Short: `p` itself is lstat'ed, bound, connected, chmodded and unlinked, its parent
  verified by `os.lstat`; no /proc is needed.
- Long: accepted only when its name `os.path.basename(p)` is non-empty and at most
  `MAX_LEAF` (78 = `MAX_PATH - len("/proc/self/fd/") - 10 - 1`) bytes; otherwise
  `ValueError("the path is longer than 103 bytes: <repr>")`, from `socket_path`,
  `listen`, `dial`, and `connect`'s and `check_target`'s target check. Its folder
  `os.path.dirname(p)` is opened once per `listen` or `dial` (`O_RDONLY | O_DIRECTORY |
  O_NOFOLLOW | O_CLOEXEC`: a symlink or a non-directory is `Fault("unsafe", folder,
  "not a directory")`, another `OSError` `Fault("error", folder, ...)`), checked by
  `os.fstat` of that fd (the same checks and Faults as `secure_dir`'s, naming the
  folder), and every later step goes through the fd, never through the folder's path:
  the name is stated by `os.stat(name, dir_fd=fd, follow_symlinks=False)`, chmodded and
  unlinked by `dir_fd`, and probed, bound and connected at
  `/proc/self/fd/<fd>/<name>` (within `MAX_PATH`). That needs /proc:
  `os.stat("/proc/self/fd/<fd>")` must give the fd's own `(st_dev, st_ino)`, else
  `Fault("error", p, "a socket path over 103 bytes needs /proc/self/fd", ENOENT)` (so
  on macOS a long path is that Fault). `dial` closes the fd before it returns; a
  `Listener` keeps it until `close`; a failed `listen` closes it.

Owner-only (every check uses `os.lstat`, or on the long route `os.fstat` of the
folder's `O_NOFOLLOW` fd and `os.stat(..., follow_symlinks=False)` of the name: a
symlink is never followed and never accepted):
- `secure_dir(path, *, uid=None) -> None | Fault`: `os.mkdir(path, 0o700)` (the last
  component only; `FileExistsError` is fine), then the directory must be a real
  directory (`S_ISDIR` of the lstat), owned by `uid`, with no group or other bits
  (`st_mode & 0o077 == 0`): `None`; otherwise `Fault("unsafe", path, detail)` naming
  the failed check. Cure never chmods or chowns a directory it finds: an unsafe one is
  refused, not repaired. Another `OSError` (no parent, `EACCES`):
  `Fault("error", path, ..., errno)`.
- The socket file is `chmod 0o600` right after `bind` (the 0700 directory is the guard
  for the instant between).
- A peer's user: on Linux, `listen`'s accepted connections are checked with
  `SO_PEERCRED` (`struct "3i"`: pid, uid, gid); a peer whose uid is not `uid` is
  closed at once, silently (it never reaches the server's events). Where the platform
  has no `SO_PEERCRED`, the 0700 directory is the only guard.

Invariant: owner_only — a session's socket files are its owner's alone, and Transport
  never loosens what it finds. (1) The directory: `secure_dir` makes it `0o700` (its
  last component only); one that exists is verified by `os.lstat` (a real directory,
  not a symlink, owned by `uid`, `st_mode & 0o077 == 0`) and never chmodded or
  chowned: an unsafe one is `Fault("unsafe")`, left as it was. `listen` and `dial`
  verify the parent the same way, creating nothing; on the long route by `os.fstat` of
  the folder's `O_NOFOLLOW` fd, through which every later step goes (a folder swapped
  after the open is never reached). (2) The socket: `chmod 0o600`
  right after `bind`, before `listen(BACKLOG)`; at `path`, by `lstat`, anything but a
  socket owned by `uid` is `Fault("unsafe")` and never touched. (3) A stale socket
  (connect `ECONNREFUSED`: its server died) is unlinked and bound again; a live one is
  `Fault("taken")` and kept. (4) `Listener.close` unlinks its own socket only, the
  file with the `st_dev` and `st_ino` it bound, and nothing else. (5) An accepted peer
  of another uid is closed at once (`SO_PEERCRED`, where the platform has it). The
  `os.chmod` of (2) and the `os.unlink`s of (3) and (4) are the only mode changes and
  removals Transport makes. Enforced by `tests/remote/test_transport.py`:
  `SecureDirTest.test_creates_0700`, `.test_wrong_mode_refused_not_repaired`,
  `.test_symlink_refused`, `.test_not_a_dir_refused`, `.test_other_owner_refused` (1);
  `ListenDialTest.test_listen_binds_0600`, `.test_unsafe_parent`,
  `.test_not_a_socket_is_unsafe`, `.test_symlink_is_unsafe`, `.test_other_uid` (1, 2),
  `.test_stale_is_rebound`, `.test_live_is_taken` (3),
  `.test_close_unlinks_own_socket`, `.test_close_leaves_replaced_file` (4); and
  `tests/remote/test_server.py`: `ListenServeTest.test_serve` (the 0700 directory and
  the sockets `serve` makes), `.test_serve_unsafe_dir` (an unsafe directory refused).
  (5) has no test there (it needs a second uid). `tests/remote/test_owner_only.py`
  gathers the five parts as `OwnerOnlyTest.test_owner_only_*` (the names conform's
  proof check matches), (5) with the peer's uid faked through `getsockopt`.

Data:
- `Fault(reason, path=None, detail="", errno=None, versions=())`: the named error a
  transport step returns (a value, never raised), frozen. `reason` one of `FAULTS`:
  `"unsafe"` (a directory or socket that is not owner-only or not what it should be),
  `"taken"` (a live server already serves the session), `"absent"` (no server: no
  socket, or a stale one), `"refused"` (the server sent REFUSE for a reason other than
  the version), `"version"` (REFUSE `"version"`: no common version; `versions` the
  server's), `"timeout"` (the handshake did not finish in time), `"malformed"` (the
  server's reply broke the [Protocol]), `"error"` (any other `OSError`, its errno
  kept). `path`: `str` or `None`; `detail`: `str`; `errno`: `int` or `None`;
  `versions`: a tuple of ints.
- `Link(target, *, side)`: one end of one connection. `target` is a connected
  `socket.socket` (the Link owns it: `close` closes it) or a pair of ints
  `(fd_in, fd_out)` (pipes, e.g. ssh's stdout and stdin; the app owns them: `close`
  does not close them). `side`: `"server"` (this end decodes CLIENT_KINDS) or
  `"client"` (it decodes SERVER_KINDS). Read-only attributes: `side`; `fd_in`,
  `fd_out` (ints; a socket's fd twice); `decoder` (its [Protocol] `Decoder`); `pending`
  (int: bytes queued, not yet written); `closed` (the sticky {Closed}, or `None`).
  `limit`, readable and settable: its Decoder's `limit`, with the Decoder's checks
  (an int in `1..MAX_FRAME`, else `TypeError` / `ValueError`); a body above it is
  `Malformed("size")`. A new Link's Decoder starts at `MAX_HELLO` (the handshake
  bound); then its owner sets it: `connect` and Attach on the client's side (see
  `connect`), `accept` on the server's (`MAX_INPUT`, see `accept`).
  - `receive(timeout=0) -> tuple[Message | Malformed, ...] | Closed`: messages kept
    by `connect` (decoded after its Welcome) are returned first, at once, with no wait
    and no read; otherwise poll `fd_in`
    (`POLLIN`) for at most `timeout` seconds (`None`: until readable; negative counts
    as 0; milliseconds rounded up); when readable, ONE read of at most `CHUNK` bytes
    (`recv(CHUNK, MSG_DONTWAIT)` on a socket, `os.read` on a pipe), fed to the decoder;
    returns the messages decoded (`()` when nothing came). End of file:
    `Closed("eof", fd_in)`; `EAGAIN`: `()`; `EINTR`: retried; another `OSError`:
    `Closed.of(error, fd_in)`; `POLLNVAL`: `Closed("invalid", fd_in, EBADF)`. A
    `Closed` is sticky: every later `receive`, `flush` and `send` returns it without
    touching the fds. Once the decoder is broken, `receive` returns `()`.
  - `queue(message)`: `encode(message)` appended to the outbox; no I/O. `message` is
    any [Protocol] message the link's side sends, a `Frame` included: [Server] queues
    each cell diff as `Frame(size, changes, cursor)`, whose bytes are exactly
    `frame(changes, size, cursor=cursor)`'s. `queue` (and `send`, which queues) is the
    public way into the outbox, and there is no raw-bytes one: [Server], [Attach] and
    the app queue messages, never bytes, and nothing outside this module touches the
    outbox. So every byte a Link writes was framed by [Protocol]'s `encode`, and an
    `encode` error leaves the outbox as it was. On a closed link the message is still
    encoded (its errors raised) and then dropped.
  - `flush() -> None | Closed`: write as much of the outbox as goes without blocking:
    a socket with `send(rest, MSG_DONTWAIT)` until the outbox is empty or `EAGAIN`; a
    pipe only while `poll(0)` reports `POLLOUT`, at most `select.PIPE_BUF` bytes per
    `os.write` (so a write to a pipe never blocks). Written bytes leave the outbox
    from the front; a partial write keeps the rest, in order. `EINTR`: retried.
    `EPIPE`, `ECONNRESET`, `EIO`, `EBADF`, ...: `Closed.of(error, fd_out)`, sticky; the
    outbox is dropped.
  - `drain(timeout) -> None | Closed`: `flush`, then while the outbox is not empty,
    wait for `POLLOUT` up to the time left of `timeout` seconds and `flush` again;
    `None` also when time runs out with bytes still queued (they stay queued).
  - `send(*messages) -> None | Closed`: `queue` each, in order, then `flush`.
  - `close() -> None`: idempotent; closes the socket when owned; the outbox is
    dropped. After `close`, `closed` is the {Closed} already kept, else
    `Closed("eof", fd_in)`, and every `receive` / `flush` / `drain` / `send` returns it.
- `Listener`: one bound, listening session socket (built by `listen`, keeping its
  `uid` for the peer check). Read-only attributes: `path`, `fd`, `closed` (`bool`). `incoming() -> Link | None | Fault`:
  accepts at most ONE waiting connection without blocking (the listening socket is
  non-blocking: it is cure's own); `None` when none is waiting (`EAGAIN`), or when the
  one accepted came from another user (closed, see above); else a new
  `Link(socket, side="server")`; another `OSError` (`EMFILE`...): `Fault("error", ...)`.
  `close() -> None`: idempotent; closes the socket and unlinks `path` only when the
  file there is still the one it bound (same `st_dev` and `st_ino`); on the long route
  both by `dir_fd` of the folder's fd it holds, which it then closes. `path` is the
  path as given, either route.
- `Client(link, ident, session, version, size, caps)`: an attached client, as
  [Server] knows it (built by `accept`). Read-only attributes: `link`, `id` (int >= 1,
  unique per server, never reused), `session` (the name), `version` (negotiated),
  `size` (the latest `(w, h)` it reported: updated by `events` on a RESIZE), `caps`
  (Core's {Caps} from its hello). `Client` compares by identity.

Operations:
- `listen(path, *, uid=None) -> Listener | Fault`: the parent directory must pass the
  owner-only checks (`secure_dir`'s verification, without creating it; a long path's
  through its folder's fd, see the two routes). Then by `lstat(path)` (long: the
  name's `dir_fd` stat):
  - absent: bind, `chmod 0o600`, `listen(BACKLOG)`;
  - a socket owned by `uid`: try to connect to it (non-blocking): connected, or
    `EAGAIN` (its backlog is full: alive): `Fault("taken", path)`; `ECONNREFUSED`
    (stale: its server died): `os.unlink(path)`, then bind as above;
  - anything else (not a socket, another user's): `Fault("unsafe", path, detail)`;
  - a bind that loses a race (`EADDRINUSE`): `Fault("taken", path)`.
- `dial(path, *, uid=None) -> socket.socket | Fault`: the checked unix connect,
  without a handshake (also the relay's way in): the parent directory passes the
  owner-only checks (else `Fault("unsafe")`); `lstat(path)` absent: `Fault("absent")`;
  not a socket, or not owned by `uid`: `Fault("unsafe")`; connect `ECONNREFUSED`:
  `Fault("absent", path, "stale")`; another `OSError`: `Fault("error")`.
- `connect(target, hello, *, uid=None, timeout=HANDSHAKE, now=time.monotonic) ->
  tuple[Link, Welcome] | Fault | Closed` ((Client) -> [Transport] : connect({Hello})
  => {Diffs}): `target` a socket path (`str`: `dial`), a connected `socket.socket`, or
  `(fd_in, fd_out)` (ssh stdio: the app spawned ssh; Remote spawns nothing). The
  client's `Link(..., side="client")` sends `hello`, drains, then receives until the
  first message, all within `timeout` seconds by `now()`:
  - `Welcome` with a version in `hello.versions`: `(link, welcome)`; messages that
    came in the same read after the Welcome are kept and returned first by the link's
    next `receive` (none is lost); from here on the link yields the {Diffs} (FRAMEs);
  - the link reads the reply at `MAX_HELLO`; once a Welcome is decoded, and before the
    next length prefix is read (a first FRAME may share the Welcome's read), its
    limit is `frame_limit(*hello.size)`, the client's own size;
  - `Refuse("version", vs)`: `Fault("version", versions=vs)`; another `Refuse`:
    `Fault("refused", detail=reason)`; anything else first, a `Malformed`, or a
    `Welcome` with a version not offered: `Fault("malformed", detail)`;
  - the time passes: `Fault("timeout")`; the link drops: its {Closed}.
  On every result but success the link is closed (an owned socket closed; pipes left
  to the app).
- `accept(link, hello, *, session, ident, versions=VERSIONS) -> Client | Refuse`
  ([Server] -> [Transport] : accept({Hello}) => {Client}): `negotiate(hello.versions,
  versions)`: a version: queue `Welcome(version, session, ident)` on `link`, flush, set
  `link.limit = MAX_INPUT` (a client's bodies are an INPUT of at most `CHUNK` bytes or
  tiny), and return `Client(link, ident, session, version, hello.size, hello.caps)`. A
  server link reads its HELLO at `MAX_HELLO`; when that first message is a Hello this
  code can negotiate (`VERSIONS`), the limit is already `MAX_INPUT` before the next
  length prefix in the same read (a client may write its HELLO and a full `CHUNK`
  INPUT together), as `connect` moves the client's on its Welcome; none: queue
  `Refuse("version", versions)`, flush, and return that `Refuse` (the caller closes
  the link). A flush's {Closed} is kept in the link (seen at its next use).
- `events(client, timeout=0) -> tuple[Input | Resize | Bye | Malformed, ...] | Closed`
  ([Server] -> [Transport] : events({Client}) => {Bytes} `@timeout(tick)`):
  `client.link.receive(min(timeout, TICK))` (`None` counts as `TICK`; [Server] passes
  0 after its own wait); each RESIZE also sets `client.size`; a HELLO after the
  handshake becomes `Malformed("order")` (and ends the tuple); a `Malformed` from the
  decoder is the last item. The person's input is never dropped or merged: every INPUT
  arrives, in order, as sent. It is `received(client, got)` of what the receive got
  (`got` when it is a {Closed}).
- `received(client, messages) -> tuple[Input | Resize | Bye | Malformed, ...]` (Q11;
  for messages already read off `client.link`, such as the [Server]'s messages after
  the HELLO in the read that carried it, which `accept` does not see): exactly
  `events`' rule over `messages` (a `tuple`, as `Link.receive` returns it), in order:
  each RESIZE also sets `client.size`; a HELLO becomes `Malformed("order", "a HELLO
  after the handshake")` and ends the tuple; every other item is passed as it is (a
  `Malformed` from the decoder included). Nothing is read from or written to the
  link. So a client's size is Transport's to keep: `accept` sets it from the HELLO,
  and `events` and `received` on each RESIZE; no caller writes it. Errors (checked
  before any size is set): `TypeError` when `client` is not a `Client` or `messages`
  is not a `tuple`. Effects: only `client.size`.
- `send(link, *messages) -> None | Closed` ([Attach] -> [Transport] : send({Bytes})):
  `link.send(*messages)`.
- `poll(wants, timeout) -> dict[int, int]` ([Server] / [Attach] -> [Transport] :
  poll({Fds}) => {Revents}): the one wait of Remote, over many fds at once. `wants` a
  mapping `{fd: mask}`, each `fd` an `int` >= 0 and each `mask` an `int` of
  `select.POLLIN` / `POLLOUT` / `POLLPRI` bits (`0` is allowed: the fd then reports only
  `POLLHUP`, `POLLERR`, `POLLNVAL`); one `select.poll()` with every fd registered at its
  mask, one `poll(2)` for at most `timeout` seconds: `None` until one fd is ready; `<=
  0` (or `-inf`) not at all (a non-blocking look); `+inf` as `None`; else milliseconds
  rounded up (so it never returns early by rounding). Result: `{fd: revents}` for the
  fds `poll(2)` reported, each `revents` the kernel's bits as they came (`POLLIN`,
  `POLLOUT`, `POLLHUP`, `POLLERR`, `POLLNVAL`: a closed or bad fd is `POLLNVAL` in the
  result, never an error), and no entry for an fd with none; `{}` when the time ran
  out, or when a signal interrupted the wait (`EINTR`: the caller's loop goes round
  again; Python's own retry on `EINTR` may also simply finish the wait). An empty
  `wants` with a finite `timeout` sleeps that long and returns `{}` (Server, with no
  socket and no client yet, waits through it too). Every fd's readiness is returned,
  not only the first: [Server] needs each listener's, connection's and client's, so
  it is not Clock's `[Wait] : select`, which returns the first hung-up fd as a
  {Closed}. It reads, writes and changes no fd; it never retries past `timeout`.
  Raises (the caller's own wrong arguments): `TypeError` when `wants` is not a
  mapping, a key or mask is not an `int` (a `bool` refused) or `timeout` is neither
  `None` nor a real number; `ValueError` when an fd is negative, `timeout` is NaN, or
  `wants` is empty and `timeout` is `None` (it would wait forever on nothing). The one
  `OSError` Transport lets pass is `poll(2)`'s own (`ENOMEM`, `EINVAL`: more fds than
  the process may poll): no fd and no peer is at fault, so no {Closed} or {Fault} can
  name it.
- `End(target)`: one end's raw bytes, the reads and non-blocking writes a `Link` and
  [Relay] share; it frames nothing (a `Link` frames through [Protocol], a Relay never
  does). `target` a connected `socket.socket` (owned: `close` closes it) or an
  `(fd_in, fd_out)` pair of ints (the app's: `close` leaves them). Read-only
  attributes: `sock` (the socket or `None`), `fd_in`, `fd_out` (a socket's fd twice).
  - `read() -> bytes | None | Closed`: ONE read of at most `CHUNK` bytes, called only
    after `poll` said readable: `recv(CHUNK, MSG_DONTWAIT)` on a socket, `os.read` on
    a pipe; the bytes; `None` for nothing (`EAGAIN`); `EINTR` retried; end of file
    `Closed("eof", fd_in)`; another `OSError` `Closed.of(error, fd_in)`.
  - `flush(out) -> None | Closed`: `out` a `bytearray`, written from the front while
    it goes without blocking, written bytes deleted from it (a partial write keeps
    the rest, in order): a socket with `send(out, MSG_DONTWAIT)` until `out` is empty
    or `EAGAIN`; a pipe only while `poll({fd_out: POLLOUT}, 0)` reports it writable,
    at most `select.PIPE_BUF` bytes per `os.write` (so a write to a pipe never
    blocks); `POLLNVAL` `Closed("invalid", fd_out, EBADF)`; `EINTR` retried; another
    `OSError` `Closed.of(error, fd_out)`. On a {Closed}, `out` is cleared.
  - `close() -> None`: closes the socket when owned; idempotent; pipes left open.
  Raises: `TypeError` when `target` is neither a socket nor a pair of ints;
  `ValueError` when an fd is negative or the socket is already closed (`fileno() <
  0`). `End` keeps no state of its own beyond its fds: no outbox (the caller's
  `bytearray` is), no sticky {Closed} (a `Link`, a Relay keep theirs).

Targets (no I/O):
- `check_target(target) -> None`: whether `target` is one `connect` takes, checked
  exactly as `connect` checks it first, with no I/O, no dial and no fd touched: a
  socket path (`str`; `ValueError` "the path is longer than 103 bytes: <repr>" when
  its UTF-8 bytes, surrogates escaped, exceed `MAX_PATH` and its name is empty or over
  `MAX_LEAF` bytes), a `socket.socket` (any; its state is not read), or a pair `(fd_in,
  fd_out)`: a `tuple` of length 2 (else `TypeError` "a target is a socket or (fd_in,
  fd_out), got <type name>") of ints, a `bool` refused (`TypeError` "an fd must be an
  int, got <type name>"), each >= 0 (`ValueError` "an fd must be >= 0, got <n>").
  Returns `None` for a good target. [Attach] calls it before it opens the terminal,
  so a bad target is refused before the terminal is touched (Attach's own contract);
  `connect` makes the same check, so a caller that only connects need not.
- `Link(target, side=...)` checks its own `target` first (a `socket.socket`, or the
  pair above with the same errors) before it builds anything; [Server]'s `adopt`
  relies on this and makes no check of its own (it calls no private `_pair`).

Within this module, `_handshake` writes a fresh client `Link`'s outbox (`link._out
+= encode(hello)`) and its kept messages (`link._kept`) directly. That stays: a
module's private names are its own (a `Link` is this module's class, as `_handshake`
is its function), the bytes are those `link.queue(hello)` would append (the link is
new, so not closed), and `connect` encodes the Hello before it dials so that an
unencodable Hello fails with no socket made. Outside this module nobody reads or
writes a `Link`'s private fields: [Server] queues through `queue`, [Attach] through
`send`.

[Relay] (the far side of ssh, a transparent byte pipe) is its own module,
`relay.py`, built on `poll` and `End` alone.

Constants: `CHUNK = 65536` (the most one read takes); `HANDSHAKE = 5.0` (seconds,
`connect`'s default); `TICK = 0.25` (seconds, Term's tick: the longest `events` waits);
`BACKLOG = 8`; `MAX_PATH = 103`; `MAX_LEAF = 78` (a long path's longest name, asserted
equal to `MAX_PATH - len("/proc/self/fd/") - 10 - 1`); `FAULTS` (the reasons). (`RELAY` moved with Relay.)

Inputs: as above (paths `str`, fds ints >= 0, timeouts numbers, a {Hello}).
Outputs: as above: a {Link}, {Listener}, {Client}, {Welcome}, {Diffs} through the link,
  or a {Fault} / {Closed}.
Errors (raised only for the caller's own wrong arguments; never for the OS or the
  peer): `TypeError` when a target is none of the accepted types, an fd or `uid` is not
  an `int` (a `bool` refused), `env` is not a mapping, a timeout is neither `None` nor
  a real number, `hello` is not a `Hello`, a message is not a [Protocol] message, or
  `client` is not a `Client`; `ValueError` when `side` is not `"server"` / `"client"`,
  `app` / `session` is not a name, a path is longer than `MAX_PATH` with a name that is
  empty or longer than `MAX_LEAF` (the 103-byte rule: see the two routes), an fd is negative,
  or a timeout is NaN (`poll`'s own, above). `Fault(...)`: `TypeError` / `ValueError` for a
  wrong field (`reason` not in `FAULTS`). `encode`'s errors pass through `queue` /
  `send` before any byte is queued.
Effects: `socket` (AF_UNIX, SOCK_STREAM): bind, listen, accept, connect, send, recv,
  getsockopt; `os.mkdir`, `os.lstat`, `os.chmod` (the socket only), `os.unlink` (a
  stale or our own socket only); on the long route `os.open` / `os.close` of the
  folder (read-only), `os.fstat`, `os.stat` of `/proc/self/fd/<fd>` and of the name by
  `dir_fd`; `os.read` / `os.write` on pipes; `select.poll`. No
  thread, no signal handler, no process-wide state; no fd's flags are changed except
  the listening socket's own (non-blocking).

Usage:
    import socket
    from cure.core.caps import Caps
    from cure.edge.remote.protocol import Hello, Input, VERSIONS
    from cure.edge.remote.transport import Link, accept, events, send, socket_path
    socket_path("construct", "main", env={"XDG_RUNTIME_DIR": "/run/user/1000"})
    # "/run/user/1000/construct/main.sock"
    socket_path("construct", "main", env={}, uid=1000)      # "/tmp/construct-1000/main.sock"
    a, b = socket.socketpair()
    srv, cli = Link(a, side="server"), Link(b, side="client")
    hello = Hello(VERSIONS, (80, 24), Caps(depth=256))
    send(cli, hello)                           # None
    (h,) = srv.receive(1.0)                    # the Hello, decoded
    c = accept(srv, h, session="main", ident=1)    # Client: id 1, size (80, 24)
    cli.receive(1.0)                           # (Welcome(1, "main", 1),)
    send(cli, Input(b"q"))
    events(c, 1.0)                             # (Input(b"q"),)
    b.close()
    events(c, 1.0)                             # Closed("eof", a.fileno())
"""

import errno as _errno
import math
import numbers
import os
import select
import socket
import stat
import struct
import time
from collections.abc import Mapping
from dataclasses import dataclass

from cure.edge.term import Closed

from .protocol import (MAX_HELLO, MAX_INPUT, SIDES, VERSIONS, Decoder, Hello, Malformed, Refuse,
                       Resize, Welcome, encode, frame_limit, negotiate, valid_name)

CHUNK = 65536
HANDSHAKE = 5.0
TICK = 0.25
BACKLOG = 8
MAX_PATH = 103
MAX_LEAF = 78
FAULTS = ("unsafe", "taken", "absent", "refused", "version", "timeout", "malformed", "error")
_PROC_FD = "/proc/self/fd/"
assert MAX_LEAF == MAX_PATH - len(_PROC_FD) - 10 - 1, "a long path's /proc/self/fd/<fd>/<name> no longer fits MAX_PATH"
assert CHUNK + 1 <= MAX_INPUT <= 2 * CHUNK, "MAX_INPUT no longer holds one INPUT of CHUNK bytes (J2)"

_READABLE = select.POLLIN | select.POLLHUP | select.POLLERR
_WRITABLE = select.POLLOUT | select.POLLHUP | select.POLLERR
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_NO_PROC = f"a socket path over {MAX_PATH} bytes needs /proc/self/fd"


@dataclass(frozen=True)
class Fault:
    """{Fault}: a named transport failure, returned to the app (never raised)."""

    reason: str
    path: "str | None" = None
    detail: str = ""
    errno: "int | None" = None
    versions: "tuple[int, ...]" = ()

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str):
            raise TypeError(f"reason must be a str, got {type(self.reason).__name__}")
        if self.path is not None and not isinstance(self.path, str):
            raise TypeError(f"path must be None or a str, got {type(self.path).__name__}")
        if not isinstance(self.detail, str):
            raise TypeError(f"detail must be a str, got {type(self.detail).__name__}")
        if self.errno is not None and not _is_int(self.errno):
            raise TypeError(f"errno must be None or an int, got {type(self.errno).__name__}")
        if not isinstance(self.versions, tuple) or not all(_is_int(v) for v in self.versions):
            raise TypeError("versions must be a tuple of ints")
        if self.reason not in FAULTS:
            raise ValueError(f"reason must be one of {FAULTS}, got {self.reason!r}")


# -- argument checks (the caller's own wrong arguments are raised)

def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _uid(uid: object) -> int:
    if uid is None:
        return os.getuid()
    if not _is_int(uid):
        raise TypeError(f"uid must be an int, got {type(uid).__name__}")
    return uid


def _timeout(value: object, name: str = "timeout") -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"{name} must be None or a real number, got {type(value).__name__}")
    if math.isnan(value):
        raise ValueError(f"{name} must not be NaN")


def _ms(timeout: "float | None") -> "int | None":
    """Poll milliseconds: None waits until ready; negative counts as 0; rounded up."""
    if timeout is None:
        return None
    if timeout <= 0:
        return 0
    if math.isinf(timeout):
        return None
    return math.ceil(timeout * 1000)


def _fd(value: object) -> int:
    if not _is_int(value):
        raise TypeError(f"an fd must be an int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"an fd must be >= 0, got {value}")
    return value


def _check_target(target: object) -> None:
    """A connect target: a socket path, a connected socket, or (fd_in, fd_out)."""
    if isinstance(target, str):
        _path(target)
    elif not isinstance(target, socket.socket):
        _pair(target)


def check_target(target: object) -> None:
    """A connect target checked, no I/O (see the module). Stub (Q9a): the implementer
    makes it `_check_target(target)`."""
    _check_target(target)


def _pair(target: object) -> "tuple[int, int]":
    if not isinstance(target, tuple) or len(target) != 2:
        raise TypeError(f"a target is a socket or (fd_in, fd_out), got {type(target).__name__}")
    return _fd(target[0]), _fd(target[1])


def _nbytes(text: str) -> int:
    return len(text.encode("utf-8", "surrogateescape"))


def _long(path: str) -> bool:
    """Past sun_path: reached through its folder's fd (the long route)."""
    return _nbytes(path) > MAX_PATH


def _path(path: object) -> str:
    """A socket path: at most MAX_PATH bytes, or longer with a name of 1..MAX_LEAF bytes."""
    if not isinstance(path, str):
        raise TypeError(f"a path must be a str, got {type(path).__name__}")
    if _long(path):
        name = os.path.basename(path)
        if not name or _nbytes(name) > MAX_LEAF:
            raise ValueError(f"the path is longer than {MAX_PATH} bytes: {path!r}")
    return path


def _env(env: object) -> Mapping:
    if env is None:
        return os.environ
    if not isinstance(env, Mapping):
        raise TypeError(f"env must be None or a mapping, got {type(env).__name__}")
    return env


def _name(value: object, what: str) -> str:
    if not valid_name(value):
        raise ValueError(f"{what} is not a name: {value!r}")
    return value


# -- where a session lives

def socket_dir(app: str, *, env: "object" = None, uid: "int | None" = None) -> str:
    """The owner-only directory an app's session sockets live in (see the module)."""
    _name(app, "app")
    env = _env(env)
    uid = _uid(uid)
    runtime = env.get("XDG_RUNTIME_DIR")
    if runtime and os.path.isabs(runtime):
        return os.path.join(runtime, app)
    tmp = env.get("TMPDIR")
    base = tmp if tmp and os.path.isabs(tmp) else "/tmp"
    return os.path.join(base, f"{app}-{uid}")


def socket_path(app: str, session: str, *, env: "object" = None, uid: "int | None" = None) -> str:
    """`<socket_dir>/<session>.sock` (a session's name always fits MAX_LEAF)."""
    _name(session, "session")
    return _path(os.path.join(socket_dir(app, env=env, uid=uid), f"{session}.sock"))


def _verify_dir(path: str, uid: int) -> "Fault | None":
    """The owner-only checks of a directory, by lstat (never followed, never repaired)."""
    try:
        st = os.lstat(path)
    except OSError as e:
        return Fault("error", path, str(e), e.errno)
    return _owner_dir(st, path, uid)


def _owner_dir(st: os.stat_result, path: str, uid: int) -> "Fault | None":
    """A directory's stat (lstat, or fstat of its fd) checked: a real directory, ours, 0700-tight."""
    if not stat.S_ISDIR(st.st_mode):
        return Fault("unsafe", path, "not a directory")
    if st.st_uid != uid:
        return Fault("unsafe", path, f"owned by uid {st.st_uid}, not {uid}")
    if st.st_mode & 0o077:
        return Fault("unsafe", path, f"mode {st.st_mode & 0o777:o} gives group or other access")
    return None


def secure_dir(path: str, *, uid: "int | None" = None) -> "Fault | None":
    """Make (0700) or verify an owner-only directory; a Fault when it is not one."""
    if not isinstance(path, str):
        raise TypeError(f"path must be a str, got {type(path).__name__}")
    uid = _uid(uid)
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    except OSError as e:
        return Fault("error", path, str(e), e.errno)
    return _verify_dir(path, uid)


def _parent(path: str) -> str:
    return os.path.dirname(path) or "."


class _Spot:
    """Where a session socket is reached. Short: its own path. Long: its name in a folder
    held open (`fd`), bound and connected at `/proc/self/fd/<fd>/<name>` and stated,
    chmodded and unlinked by `dir_fd`; the folder's path is never used again."""

    def __init__(self, path: str, fd: "int | None" = None) -> None:
        self.path, self.fd = path, fd
        self.name = os.path.basename(path)
        self.addr = path if fd is None else f"{_PROC_FD}{fd}/{self.name}"

    def lstat(self) -> os.stat_result:
        if self.fd is None:
            return os.lstat(self.path)
        return os.stat(self.name, dir_fd=self.fd, follow_symlinks=False)

    def chmod(self) -> None:
        if self.fd is None:
            os.chmod(self.path, 0o600)
        else:
            os.chmod(self.name, 0o600, dir_fd=self.fd)

    def unlink(self) -> None:
        if self.fd is None:
            os.unlink(self.path)
        else:
            os.unlink(self.name, dir_fd=self.fd)

    def close(self) -> None:
        """Close the folder's fd (long); its owner calls it once."""
        if self.fd is not None:
            os.close(self.fd)


def _reach(path: str, uid: int) -> "_Spot | Fault":
    """The checked folder of a socket path: by lstat (short), or by one fd (long)."""
    if not _long(path):
        fault = _verify_dir(_parent(path), uid)
        return _Spot(path) if fault is None else fault
    folder = os.path.dirname(path)
    try:
        fd = os.open(folder, _DIR_FLAGS)
    except OSError as e:
        if e.errno in (_errno.ELOOP, _errno.ENOTDIR):
            return Fault("unsafe", folder, "not a directory")
        return Fault("error", folder, str(e), e.errno)
    try:
        fault = _held_dir(fd, folder, path, uid)
    except BaseException:
        os.close(fd)
        raise
    if fault is not None:
        os.close(fd)
        return fault
    return _Spot(path, fd)


def _held_dir(fd: int, folder: str, path: str, uid: int) -> "Fault | None":
    """The folder's fd checked by fstat, and reachable as /proc/self/fd/<fd> (the same file)."""
    try:
        st = os.fstat(fd)
    except OSError as e:
        return Fault("error", folder, str(e), e.errno)
    fault = _owner_dir(st, folder, uid)
    if fault is not None:
        return fault
    try:
        via = os.stat(f"{_PROC_FD}{fd}")
    except OSError:
        via = None
    if via is None or (via.st_dev, via.st_ino) != (st.st_dev, st.st_ino):
        return Fault("error", path, _NO_PROC, _errno.ENOENT)
    return None


# -- one end's bytes: the reads and non-blocking writes Link and Relay share

def poll(wants: "Mapping[int, int]", timeout: "float | None") -> "dict[int, int]":
    """One wait over many fds: `{fd: revents}` for each fd ready within `timeout` (see the module)."""
    if not isinstance(wants, Mapping):
        raise TypeError(f"wants must be a mapping of fd to mask, got {type(wants).__name__}")
    for fd, mask in wants.items():
        _fd(fd)
        if not _is_int(mask):
            raise TypeError(f"a mask must be an int, got {type(mask).__name__}")
    _timeout(timeout)
    ms = _ms(timeout)
    if not wants and ms is None:
        raise ValueError("wants is empty and timeout is not finite: it would wait forever")
    p = select.poll()
    for fd, mask in wants.items():
        p.register(fd, mask)
    try:
        return dict(p.poll(ms))
    except InterruptedError:
        return {}


class End:
    """One end's raw bytes: a connected socket (owned) or a pipe pair (the app's); one read, a non-blocking flush."""

    def __init__(self, target: object) -> None:
        if isinstance(target, socket.socket):
            self.sock = target
            self.fd_in = self.fd_out = target.fileno()
            if self.fd_in < 0:
                raise ValueError("the socket is closed")
        else:
            self.sock = None
            self.fd_in, self.fd_out = _pair(target)

    def read(self) -> "bytes | Closed | None":
        """One read of at most CHUNK: the bytes, None for nothing (EAGAIN), or the Closed."""
        while True:
            try:
                if self.sock is not None:
                    data = self.sock.recv(CHUNK, socket.MSG_DONTWAIT)
                else:
                    data = os.read(self.fd_in, CHUNK)
            except InterruptedError:
                continue
            except BlockingIOError:
                return None
            except OSError as e:
                return Closed.of(e, self.fd_in)
            return data if data else Closed("eof", self.fd_in)

    def flush(self, out: bytearray) -> "Closed | None":
        """Write the front of `out` while it goes without blocking; written bytes leave it."""
        while out:
            try:
                if self.sock is not None:
                    n = self.sock.send(out, socket.MSG_DONTWAIT)
                else:
                    ready = poll({self.fd_out: select.POLLOUT}, 0).get(self.fd_out, 0)
                    if ready & select.POLLNVAL:
                        out.clear()
                        return Closed("invalid", self.fd_out, _errno.EBADF)
                    if not ready & _WRITABLE:
                        return None
                    n = os.write(self.fd_out, out[:select.PIPE_BUF])
            except InterruptedError:
                continue
            except BlockingIOError:
                return None
            except OSError as e:
                out.clear()
                return Closed.of(e, self.fd_out)
            del out[:n]
        return None

    def close(self) -> None:
        if self.sock is not None:
            self.sock.close()


def _hello(decoder: Decoder) -> object:
    """A server link's hook on its first message: a HELLO `accept` can take moves the bound
    to MAX_INPUT before the next prefix (a full CHUNK INPUT may share the HELLO's read)."""

    def first(m: object) -> None:
        decoder._after = None
        if isinstance(m, Hello) and negotiate(m.versions, VERSIONS) is not None:
            decoder.limit = MAX_INPUT

    return first


class Link:
    """One end of one connection: framed, non-blocking, with an outbox; a dropped peer is a sticky Closed."""

    def __init__(self, target: object, *, side: str) -> None:
        if side not in SIDES:
            raise ValueError(f"side must be 'server' or 'client', got {side!r}")
        if not isinstance(target, socket.socket):
            _pair(target)
        self._end = End(target)
        self._side = side
        self._decoder = Decoder(side, limit=MAX_HELLO)
        if side == "server":
            self._decoder._after = _hello(self._decoder)
        self._out = bytearray()
        self._closed = None
        self._kept = []
        self._shut = False

    @property
    def side(self) -> str:
        """`"server"` or `"client"`: the end this link is."""
        return self._side

    @property
    def fd_in(self) -> int:
        """The fd read from."""
        return self._end.fd_in

    @property
    def fd_out(self) -> int:
        """The fd written to."""
        return self._end.fd_out

    @property
    def decoder(self) -> object:
        """Its Protocol Decoder."""
        return self._decoder

    @property
    def limit(self) -> int:
        """Its Decoder's limit: MAX_HELLO until its owner sets it (the Decoder's checks)."""
        return self._decoder.limit

    @limit.setter
    def limit(self, value: int) -> None:
        self._decoder.limit = value

    @property
    def pending(self) -> int:
        """Bytes queued and not yet written."""
        return len(self._out)

    @property
    def closed(self) -> "Closed | None":
        """The sticky Closed, or None."""
        return self._closed

    def receive(self, timeout: "float | None" = 0) -> "tuple | Closed":
        """Wait at most `timeout` to read, read once, return the messages decoded."""
        _timeout(timeout)
        if self._closed is not None:
            return self._closed
        if self._kept:
            kept, self._kept = tuple(self._kept), []
            return kept
        if self._decoder.broken is not None:
            return ()
        fd = self._end.fd_in
        ready = poll({fd: select.POLLIN}, timeout).get(fd, 0)
        if ready & select.POLLNVAL:
            return self._drop(Closed("invalid", fd, _errno.EBADF))
        if not ready & _READABLE:
            return ()
        data = self._end.read()
        if data is None:
            return ()
        if isinstance(data, Closed):
            return self._drop(data)
        return self._decoder.feed(data)

    def queue(self, message: object) -> None:
        """Encode `message` onto the outbox; no I/O."""
        data = encode(message)
        if self._closed is None:
            self._out += data

    def flush(self) -> "Closed | None":
        """Write what goes without blocking."""
        if self._closed is not None:
            return self._closed
        gone = self._end.flush(self._out)
        return None if gone is None else self._drop(gone)

    def drain(self, timeout: float) -> "Closed | None":
        """Flush, waiting at most `timeout` seconds for the outbox to empty."""
        _timeout(timeout)
        gone = self.flush()
        if gone is not None:
            return gone
        deadline = None if timeout is None else time.monotonic() + timeout
        while self._out:
            left = None if deadline is None else deadline - time.monotonic()
            if left is not None and left <= 0:
                return None
            poll({self._end.fd_out: select.POLLOUT}, left)
            gone = self.flush()
            if gone is not None:
                return gone
        return None

    def send(self, *messages: object) -> "Closed | None":
        """Queue each message, then flush."""
        data = [encode(m) for m in messages]
        if self._closed is not None:
            return self._closed
        for d in data:
            self._out += d
        return self.flush()

    def close(self) -> None:
        """Close (an owned socket); idempotent."""
        if self._shut:
            return None
        self._shut = True
        if self._closed is None:
            self._closed = Closed("eof", self._end.fd_in)
        self._out.clear()
        self._kept = []
        self._end.close()
        return None

    def _drop(self, closed: Closed) -> Closed:
        self._closed = closed
        self._out.clear()
        return closed


class Listener:
    """A bound, listening, owner-only session socket."""

    @classmethod
    def _bound(cls, sock: socket.socket, spot: _Spot, uid: int, ident: "tuple[int, int]") -> "Listener":
        self = cls.__new__(cls)
        self._sock, self._spot, self._uid, self._ident = sock, spot, uid, ident
        self._path = spot.path
        self._fd = sock.fileno()
        self._closed = False
        return self

    @property
    def path(self) -> str:
        """The socket's path."""
        return self._path

    @property
    def fd(self) -> int:
        """The listening socket's fd."""
        return self._fd

    @property
    def closed(self) -> bool:
        """Whether `close` has run."""
        return self._closed

    def incoming(self) -> "Link | Fault | None":
        """Accept one waiting connection (another user's is dropped), without blocking."""
        if self._closed:
            return None
        try:
            conn, _ = self._sock.accept()
        except (BlockingIOError, InterruptedError):
            return None
        except OSError as e:
            return Fault("error", self._path, str(e), e.errno)
        try:
            if not self._peer_ok(conn):
                conn.close()
                return None
            return Link(conn, side="server")
        except OSError as e:
            conn.close()
            return Fault("error", self._path, str(e), e.errno)
        except BaseException:
            conn.close()
            raise

    def _peer_ok(self, conn: socket.socket) -> bool:
        opt = getattr(socket, "SO_PEERCRED", None)
        if opt is None:
            return True
        size = struct.calcsize("3i")
        _pid, uid, _gid = struct.unpack("3i", conn.getsockopt(socket.SOL_SOCKET, opt, size))
        return uid == self._uid

    def close(self) -> None:
        """Close and unlink our own socket file (then its folder's fd, when held); idempotent."""
        if self._closed:
            return None
        self._closed = True
        self._sock.close()
        try:
            st = self._spot.lstat()
            if (st.st_dev, st.st_ino) == self._ident:
                self._spot.unlink()
        except OSError:
            pass
        finally:
            self._spot.close()
        return None


class Client:
    """An attached client: its link, id, session, version, size and caps."""

    def __init__(self, link: Link, ident: int, session: str, version: int,
                 size: "tuple[int, int]", caps: object) -> None:
        if not isinstance(link, Link):
            raise TypeError(f"link must be a Link, got {type(link).__name__}")
        for name, value in (("ident", ident), ("version", version)):
            if not _is_int(value):
                raise TypeError(f"{name} must be an int, got {type(value).__name__}")
        if not isinstance(session, str):
            raise TypeError(f"session must be a str, got {type(session).__name__}")
        self._link, self._id, self._session, self._version = link, ident, session, version
        self._size = tuple(size)
        self._caps = caps

    @property
    def link(self) -> Link:
        """Its Link."""
        return self._link

    @property
    def id(self) -> int:
        """Its id, unique per server."""
        return self._id

    @property
    def session(self) -> str:
        """The session it attached to."""
        return self._session

    @property
    def version(self) -> int:
        """The negotiated protocol version."""
        return self._version

    @property
    def size(self) -> "tuple[int, int]":
        """Its terminal's latest size."""
        return self._size

    @property
    def caps(self) -> object:
        """Its terminal's Caps."""
        return self._caps

    def __repr__(self) -> str:
        return f"Client(id={self._id}, session={self._session!r}, size={self._size})"


def _bind(spot: _Spot, uid: int) -> "Listener | Fault":
    path = spot.path
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(spot.addr)
    except OSError as e:
        sock.close()
        if e.errno == _errno.EADDRINUSE:
            return Fault("taken", path, "lost a race to bind")
        return Fault("error", path, str(e), e.errno)
    except BaseException:
        sock.close()
        raise
    try:
        spot.chmod()
        st = spot.lstat()
        sock.listen(BACKLOG)
        sock.setblocking(False)
    except BaseException as e:
        sock.close()
        try:
            spot.unlink()
        except OSError:
            pass
        if isinstance(e, OSError):
            return Fault("error", path, str(e), e.errno)
        raise
    return Listener._bound(sock, spot, uid, (st.st_dev, st.st_ino))


def _probe(path: str) -> int:
    """Try a non-blocking connect to a socket found at `path`: its errno (0: connected)."""
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.setblocking(False)
        return probe.connect_ex(path)
    finally:
        probe.close()


def listen(path: str, *, uid: "int | None" = None) -> "Listener | Fault":
    """Bind an owner-only session socket; a stale one is replaced, a live one is `taken`."""
    _path(path)
    uid = _uid(uid)
    spot = _reach(path, uid)
    if isinstance(spot, Fault):
        return spot
    try:
        result = _listen(spot, uid)
    except BaseException:
        spot.close()
        raise
    if not isinstance(result, Listener):
        spot.close()                        # a Listener keeps the folder's fd; a Fault does not
    return result


def _listen(spot: _Spot, uid: int) -> "Listener | Fault":
    path = spot.path
    try:
        st = spot.lstat()
    except FileNotFoundError:
        return _bind(spot, uid)
    except OSError as e:
        return Fault("error", path, str(e), e.errno)
    if not stat.S_ISSOCK(st.st_mode):
        return Fault("unsafe", path, "not a socket")
    if st.st_uid != uid:
        return Fault("unsafe", path, f"owned by uid {st.st_uid}, not {uid}")
    try:
        err = _probe(spot.addr)
    except OSError as e:
        return Fault("error", path, str(e), e.errno)
    if err in (0, _errno.EAGAIN, _errno.EWOULDBLOCK, _errno.EINPROGRESS):
        return Fault("taken", path, "a live server serves it")
    if err == _errno.ECONNREFUSED:
        try:
            spot.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            return Fault("error", path, str(e), e.errno)
        return _bind(spot, uid)
    if err == _errno.ENOENT:
        return _bind(spot, uid)
    return Fault("error", path, os.strerror(err), err)


def dial(path: str, *, uid: "int | None" = None) -> "object":
    """Connect to an owner-only session socket (no handshake); a socket or a Fault."""
    _path(path)
    uid = _uid(uid)
    spot = _reach(path, uid)
    if isinstance(spot, Fault):
        return spot
    try:
        return _dial(spot, uid)
    finally:
        spot.close()                        # the folder's fd is dial's own


def _dial(spot: _Spot, uid: int) -> "socket.socket | Fault":
    path = spot.path
    try:
        st = spot.lstat()
    except FileNotFoundError:
        return Fault("absent", path, "no socket")
    except OSError as e:
        return Fault("error", path, str(e), e.errno)
    if not stat.S_ISSOCK(st.st_mode):
        return Fault("unsafe", path, "not a socket")
    if st.st_uid != uid:
        return Fault("unsafe", path, f"owned by uid {st.st_uid}, not {uid}")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(spot.addr)
    except BaseException as e:
        sock.close()
        if isinstance(e, ConnectionRefusedError):
            return Fault("absent", path, "stale")
        if isinstance(e, FileNotFoundError):
            return Fault("absent", path, "no socket")
        if isinstance(e, OSError):
            return Fault("error", path, str(e), e.errno)
        raise
    return sock


def connect(target: object, hello: Hello, *, uid: "int | None" = None, timeout: float = HANDSHAKE,
            now: "object" = time.monotonic) -> "tuple[Link, Welcome] | Fault | Closed":
    """Connect, say hello, and wait (bounded) for the server's Welcome."""
    _check_target(target)
    if not isinstance(hello, Hello):
        raise TypeError(f"hello must be a Hello, got {type(hello).__name__}")
    _timeout(timeout)
    if not callable(now):
        raise TypeError(f"now must be callable, got {type(now).__name__}")
    uid = _uid(uid)
    data = encode(hello)
    path = target if isinstance(target, str) else None
    if path is not None:
        target = dial(path, uid=uid)
        if isinstance(target, Fault):
            return target
    try:
        link = Link(target, side="client")
    except BaseException:
        if path is not None:
            target.close()
        raise
    try:
        result = _handshake(link, data, hello, path, timeout, now)
    except BaseException:
        link.close()
        raise
    finally:
        link._decoder._after = None
    if not isinstance(result, tuple):
        link.close()
    return result


def _handshake(link: Link, data: bytes, hello: Hello, path: "str | None", timeout: float,
               now: object) -> "tuple[Link, Welcome] | Fault | Closed":
    deadline = None if timeout is None else now() + timeout

    def welcomed(m: object) -> None:
        # A first FRAME may share the Welcome's read: the bound moves before its prefix.
        if isinstance(m, Welcome):
            link._decoder._after = None
            link.limit = frame_limit(*hello.size)

    link._decoder._after = welcomed
    link._out += data
    gone = link.drain(None if deadline is None else max(0.0, deadline - now()))
    if gone is not None:
        return gone
    while True:
        left = None if deadline is None else deadline - now()
        if left is not None and left <= 0:
            return Fault("timeout", path, f"no reply in {timeout} s")
        got = link.receive(left)
        if isinstance(got, Closed):
            return got
        if not got:
            if link.decoder.broken is not None:
                return Fault("malformed", path, link.decoder.broken.reason)
            continue
        first, rest = got[0], got[1:]
        if isinstance(first, Welcome) and first.version in hello.versions:
            link._kept = list(rest)
            return link, first
        if isinstance(first, Refuse):
            if first.reason == "version":
                return Fault("version", path, "no common version", versions=first.versions)
            return Fault("refused", path, first.reason)
        if isinstance(first, Malformed):
            return Fault("malformed", path, first.reason)
        if isinstance(first, Welcome):
            return Fault("malformed", path, f"version {first.version} was not offered")
        return Fault("malformed", path, f"a {type(first).__name__} before the Welcome")


def accept(link: Link, hello: Hello, *, session: str, ident: int,
           versions: "tuple[int, ...]" = VERSIONS) -> "Client | Refuse":
    """Negotiate a version: Welcome and a Client, or Refuse."""
    if not isinstance(link, Link):
        raise TypeError(f"link must be a Link, got {type(link).__name__}")
    if not isinstance(hello, Hello):
        raise TypeError(f"hello must be a Hello, got {type(hello).__name__}")
    version = negotiate(hello.versions, versions)
    if version is None:
        refuse = Refuse("version", tuple(versions))
        link.queue(refuse)
        link.flush()
        return refuse
    link.queue(Welcome(version, session, ident))
    link.flush()
    link.limit = MAX_INPUT                  # a client's bodies: one INPUT of CHUNK bytes at most
    return Client(link, ident, session, version, hello.size, hello.caps)


def events(client: Client, timeout: "float | None" = 0) -> "tuple | Closed":
    """A client's messages received within `min(timeout, TICK)`; RESIZE updates its size."""
    if not isinstance(client, Client):
        raise TypeError(f"client must be a Client, got {type(client).__name__}")
    _timeout(timeout)
    got = client.link.receive(TICK if timeout is None else min(timeout, TICK))
    if isinstance(got, Closed):
        return got
    return received(client, got)


def received(client: Client, messages: tuple) -> tuple:
    """Messages already read off `client.link`, by `events`' rule: RESIZE sets the size; a HELLO ends it as Malformed."""
    if not isinstance(client, Client):
        raise TypeError(f"client must be a Client, got {type(client).__name__}")
    if not isinstance(messages, tuple):
        raise TypeError(f"messages must be a tuple, got {type(messages).__name__}")
    out = []
    for m in messages:
        if isinstance(m, Hello):
            out.append(Malformed("order", "a HELLO after the handshake"))
            break
        if isinstance(m, Resize):
            client._size = m.size
        out.append(m)
    return tuple(out)


def send(link: Link, *messages: object) -> "Closed | None":
    """`link.send(*messages)`."""
    if not isinstance(link, Link):
        raise TypeError(f"link must be a Link, got {type(link).__name__}")
    return link.send(*messages)

