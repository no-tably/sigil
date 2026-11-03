"""[Pty]: a program in a pane: the edge half (spawn, resize, read, write); Vt is the pure
half. The one part of cure that starts a process, and only the command it is handed.

Kind: service (the `spawn` op, the `Pty` handle it returns, and the two pure steps the
handle is built on). construct's builders' terminals run in panes: `spawn` starts the
command the app hands it on a new pty, and the `Pty` handle reads the program's output
into a Vt `Screen` (its cells are what a Pane widget is given, `[Pty] -> [Vt] :
apply({Bytes}) => {Grid}`), writes a person's input to it re-encoded for the modes the
program set (`[Pty] -> [Vt] : encode({Event}) => {Bytes}`), and resizes it
(`TIOCSWINSZ`). It has no loop and no thread: the app waits on `pty.fds` (with Clock's
[Wait], beside its Term's fds) and calls the non-blocking steps from its own loop.

## What is pure and what touches fds

- Pure (no fd, no process; testable on a bare `Screen`): `output(screen, data)`, the
  bytes -> screen step, and `forward(event, modes)`, the event -> bytes step. The
  handle's `read` and `send` are exactly these around one `os.read` / `os.write`.
- The edge: `spawn` (`os.openpty`, `os.pipe`, one `os.posix_spawn` of a boot
  interpreter (its payload in an `os.memfd_create` memfd or an `os.pipe`), and in the
  new process the boot's `os.login_tty`, `os.chdir`,
  `os.execvpe`), and the handle's `read` (`os.read`), `write` / `send` /
  `flush` (`os.write`), `resize` (`fcntl.ioctl(TIOCSWINSZ)`), `poll` / `close`
  (`os.waitpid`), `kill` / `close` (`os.killpg`). Nothing else in cure forks, execs or
  spawns (`only_spawner`).
- Tests need no real terminal: `spawn([sys.executable, "-c", "..."])` runs a
  stdlib-only child on a real pty, and the pure steps run on a `Screen` alone.

Invariant: only_spawner — this module is the one place in cure that starts a process,
  and it starts only the command it is handed. (1) No other module under `cure/` calls
  `os.fork`, `os.forkpty`, `os.posix_spawn`, `os.posix_spawnp`, `os.system`,
  `os.popen`, any `os.exec*` / `os.spawn*` function, or imports `subprocess`, `pty` or
  `multiprocessing` (a test walks every module's AST and finds these names only in
  `cure/edge/embed/pty.py`). (2) `spawn(argv, ...)` execs exactly `argv`: `argv[0]`
  looked up on the `PATH` of the environment given, the program receiving `argv`
  itself as its `sys.argv` / `argv` (no shell, no added, dropped or rewritten
  argument, no default command), with exactly that environment (nothing added: not
  even `TERM`) and in exactly that `cwd`. (3) Each `spawn` starts at most one process
  (one `os.posix_spawn`); the program is that process (the boot execs in place, same
  pid); a `Pty` never starts another (not on resize, not on close). No Python code
  runs in a forked child: this module never calls `os.fork`.

Constants:
- `SIZE = (80, 24)`: the default `(w, h)` of a new pty and its screen.
- `SPAWN = 5.0`: seconds, the default `@timeout(spawn)`: how long `spawn` waits for the
  new process to exec or report its failure.
- `CLOSE = 0.5`: seconds, `close`'s default grace between `SIGHUP` and `SIGKILL`.
- `STEP = 0.01`: seconds between two `poll`s while `close` waits out its grace.
- `READ = 65536`: the most bytes one `read` takes (so a flooding program cannot
  starve the app's loop; the rest waits for the next `read`).
- `MAX_PENDING = 1 << 20`: the most bytes the outbox holds (see `write`; `read`'s
  replies join it as a `write`).
- `MAX_EVENTS = 4096`: the most events `take` holds; past that the oldest is dropped.
- `MAX_SIZE = 65535`: the largest `w` or `h` (`TIOCSWINSZ`'s fields are unsigned
  shorts).
- `RESET`: the signals set to `SIG_DFL` in the new process before exec: `SIGPIPE`, `SIGXFSZ`
  (Python ignores them), `SIGINT`, `SIGQUIT`, `SIGTSTP`, `SIGTTIN`, `SIGTTOU`,
  `SIGHUP`, `SIGTERM`, `SIGCHLD`, `SIGWINCH` (an app may ignore any of these, and an
  ignored disposition survives exec), as `signal.Signals` in that order.
- `EXIT_FAILED = 127`: the new process's exit status when it could not exec.

## The pure steps

`output(screen, data) -> tuple[Grid, bytes, tuple[Event, ...]]` ((Program) ~> [Pty] :
output({Bytes}), then [Pty] -> [Vt] : apply({Bytes}) => {Grid}; the bytes -> screen
step): the program's output `data` performed on its `screen`, in order:
1. `grid = apply(screen, data)` (Vt's package `apply`: the screen's own parser carries
   a sequence split across calls);
2. `events = screen.take()` (this empties the screen's queue);
3. `replies = b"".join(e.data for e in events if isinstance(e, Reply))`: the answers
   to the program's queries (DSR, DA, DECRQM, colours ...), in order, to be written
   back to the program's own pty; `others`: the remaining events (Vt's `Title`, `Cwd`,
   `Clipboard`, `Bell`), in order.
Returns `(grid, replies, others)`. `data` may be empty (`(screen.grid(), b"", ())`
when nothing was waiting in the screen's queue).
Law (chunk independence): for every split `data == a + b`, performing `a` then `b` on
  one fresh screen and `data` at once on another leave the two screens' `grid()` /
  `cursor()` / `modes` equal, and the replies joined and the other events
  concatenated equal (from Vt's own laws).
Errors: `TypeError` when `screen` is not a Vt `Screen` or `data` is not `bytes`,
  `bytearray` or `memoryview` (as Vt's `apply`); no byte sequence raises.
Effects: none beyond `screen`'s own state.

`forward(event, modes) -> bytes` (the event -> bytes step): a person's input event as
the pane's program asked for it, by the Vt `Modes` it set (`screen.modes`). Events are
read by duck typing, as Vt's [Encode] reads them (Embed imports no Input):
- a "Key" (by `type(event).__name__`) whose `event` attribute is `"release"`: `b""`,
  dropped. [Encode] writes every Key as a press, so a forwarded release would type the
  key a second time. Input decodes releases only when the app asked the outer terminal
  for kitty's event types (flag 2).
- a "Key" whose `event` is `"repeat"`: forwarded as a press, `encode(event, modes)`: a
  held key keeps typing in the pane, as it does in a terminal that reports no event
  types (whose auto-repeat sends presses).
- a "Key" whose `event` is `"press"`, or which has no `event` attribute:
  `encode(event, modes)`.
- anything else: `encode(event, modes)` as it is. A "Mouse" release is a real report
  (the program asked for releases by its mouse mode) and goes through; a "Resize"
  encodes to `b""` (a pane's size is `Pty.resize`'s business, never the outer
  terminal's size); "Paste" and "Focus" as Encode writes them.
Laws (loopable over Key names x mods x Modes): `forward(k_release, m) == b""`;
  `forward(k_repeat, m) == forward(k_press, m) == encode(k_press, m)`, where the three
  keys differ only in `event`; `forward(e, m) == encode(e, m)` for every non-Key `e`.
Errors: `TypeError` when a Key's `event` is not a `str`; `ValueError` when it is none
  of "press", "repeat", "release"; otherwise what `encode` raises (`TypeError` for a
  `modes` that is not a Vt `Modes` or an event of no known kind, `ValueError` for an
  unknown key name ...). A release is checked as a Key (its `event`) but not encoded.
Effects: none.

## Starting: `spawn`

`spawn(argv, *, size=SIZE, env=None, cwd=None, timeout=SPAWN) -> Pty | SpawnFailed`
((Construct) -> [Embed] / [Pty] -> (Program) : spawn({Command}) => {Fd}
@timeout(spawn)): the {Command} is `argv` with its `env` and `cwd`; the {Fd} is the
returned handle's `fd`, the pty's master side.
- `argv`: a non-empty `list` or `tuple` of `str`, run as it is (no shell: a shell is
  run only when the app hands one, e.g. `["sh", "-c", line]`). `argv[0]` is the
  program, looked up on the `PATH` of the environment used (`os.execvpe`'s rule:
  `os.defpath` when that environment has no `PATH`; a name with a "/" is a path).
- `size`: `(w, h)`, ints 1..`MAX_SIZE`: the pty's window size, set on the pty before
  the spawn, so the program reads the right size from its first instruction, and the
  screen's size.
- `env`: a `Mapping` of `str` to `str`, the child's whole environment, exactly as
  given; `None`: the parent's `os.environ` as it is at the spawn. Embed adds nothing:
  `TERM` is the app's to give (construct passes the type its Vt screen emulates, e.g.
  `TERM=xterm-256color`); a program run without one sees none.
- `cwd`: the child's working directory (`str` or `os.PathLike` of `str`), or `None`:
  the parent's.
- `timeout`: seconds > 0 (finite), how long the parent waits for the new process to
  exec or report its failure (`@timeout(spawn)`).

In the parent, in order:
1. `os.openpty()` (both fds non-inheritable); `TIOCSWINSZ` on the slave side to `size`
   (rows `h`, columns `w`, pixels 0); the master side non-blocking. An `OSError`:
   both fds closed, `SpawnFailed(argv, "pty", errno)`.
2. The status pipe `os.pipe()` (non-inheritable: close-on-exec); `sys.executable`
   empty or `None`: every fd opened so far closed, `SpawnFailed(argv, "fork",
   errno.ENOENT)`. Then the payload's carrier, written in full before the spawn (the
   parent never writes later, so it never blocks and no `SIGPIPE` can reach it). The
   payload: `"-"` for `cwd=None` or `"+" + cwd`, `str(len(argv))`, each of `argv`, then
   `f"{k}={v}"` for the child's env, each as `os.fsencode` bytes ended by one NUL (no
   field holds a NUL: the checks refuse it). It goes down a fd, never the boot's argv:
   `/proc/<pid>/cmdline` is readable by every local user, `/proc/<pid>/fd` by the same
   user only (and the exec limits count the payload once, in the program's own exec).
   The carrier: where `os.memfd_create` exists, a memfd (`MFD_CLOEXEC`) written in full,
   then `lseek` to 0 (no size cap); elsewhere a pipe (both ends non-inheritable), its
   size raised to fit with `F_SETPIPE_SZ` where that exists (a refusal ignored), the
   payload written with the write end non-blocking, the write end then closed; a
   payload that does not fit: `SpawnFailed(argv, "fork", errno.E2BIG)`. An `OSError`
   making or writing it: every fd opened so far closed, `SpawnFailed(argv, "fork",
   errno)`, nothing started. Then one `os.posix_spawn` of a boot interpreter,
   `sys.executable -I -S -X utf8 -c _BOOT` (nothing after `_BOOT`, which is constant
   source), with the parent's `os.environ` as its env (`-I` keeps `PYTHON*` out),
   `setsigmask=()`, `setsigdef=RESET`, and `file_actions` putting the slave on fds 0,
   1, 2, the pipe's write end on fd 3 and the carrier's read side on fd 4 (from copies
   of the three at fds >= 5, so whatever numbers the parent's fds have, 0, 1 or 2
   closed included, no action clobbers another's source). An `OSError`: every fd
   opened so far closed, `SpawnFailed(argv, "fork", errno)`. The parent closes its
   copies of the carrier on every path. No Python runs in a forked child
   (glibc's `posix_spawn` is a vfork and an exec), so a multi-threaded caller gets no
   `DeprecationWarning` and no lock held across a fork. The cost: about 17 ms a spawn,
   a boot interpreter's start (a pane opening, not a frame).
3. The boot (`_BOOT`, importing only `os` and `signal`; single-threaded, it
   never returns into the caller's code: everything ends in `os._exit`): writes `b"+"`
   to fd 3; sets fd 3 non-inheritable, each of `RESET` to `SIG_DFL` (the interpreter
   re-ignores `SIGPIPE` and `SIGXFSZ` at its start) and empties its signal mask;
   `os.login_tty(0)` (a new session, the pty its controlling terminal and its fds 0,
   1, 2); reads fd 4 to its end of file (a memfd ends at its size, a pipe at its closed
   write end), closes it and splits the bytes at NUL, the empty tail dropped (the
   payload back exactly, as bytes); closes every fd >= 4 (to the open-files limit; all
   stage "tty"); `os.chdir(cwd)` when one was given (stage "chdir"); `os.execvpe(argv[0],
   argv, env)` in place, same pid, all in bytes (stage "exec"). On an `OSError` at a
   stage it writes `f"{stage}:{error.errno}"` (ASCII, one `os.write`, shorter than
   `PIPE_BUF`) to fd 3 and `os._exit(EXIT_FAILED)`; on any other exception the same
   with nothing after the colon. A successful exec closes fd 3 (non-inheritable): that
   is how the parent knows.
4. The parent closes the slave side and the pipe's write end, then reads the pipe
   until its end of file, waiting with Clock's `select([r], left)` ([Embed] -> [Wait] :
   select({Fds}) => {Ready}), `left` the time left of `timeout` (`time.monotonic`):
   - `b"+"` then end of file (the boot ran and the exec happened): the pipe closed; a
     `Pty` over the master, the child's pid, `argv` (as a tuple), `size`, and a fresh
     Vt `Screen(w, h)`;
   - `b"+<stage>:<errno>"`: the child `os.waitpid`-reaped (it is exiting), the pipe and
     the master closed, `SpawnFailed(argv, stage, errno)` (`errno` `None` when the
     part after the colon is empty);
   - anything else, end of file with nothing read included (the interpreter failed to
     start, or the boot never ran its first line): `SIGKILL` to the child (whatever
     ran is not the boot), which is then reaped, the pipe and the master closed,
     `SpawnFailed(argv, "exec")` (`errno` `None`);
   - `timeout` passes first: `SIGKILL` to the child, which is then reaped, the pipe
     and the master closed, `SpawnFailed(argv, "timeout")`.
So a `Pty` means "the command was exec'd", not "it runs well": a program that exits 1
at once is a `Pty` whose `returncode` becomes 1. A `SpawnFailed` leaves no fd open and
no child unreaped. The pty starts in the kernel's default line discipline (cooked,
echo on, `\\n` written as `\\r\\n`): Embed sets no termios; the program sets its own.

## The handle: `Pty`

Made only by `spawn` (calling `Pty(...)` directly raises `TypeError`). State, read-only
(properties unless shown with parentheses):
- `fd -> int | None`: the master side ({Fd}); `None` once `close` closed it.
- `pid -> int`: the child's pid (the leader of its own session and process group).
- `argv -> tuple[str, ...]`: the command as handed.
- `screen -> Screen`: the program's Vt screen. The app reads it (`title`, `cursor()`,
  `scrolled()` for its scrollback `keep`, ...); it changes it only through the handle
  (`read`, `resize`), never by applying bytes or resizing it itself.
- `size -> (w, h)`: the size last set (`spawn`'s, then `resize`'s).
- `grid(*, live=False) -> Grid`: `screen.grid(live=live)`: what the Pane widget is
  given.
- `fds -> tuple[int, ...]`: what to wait on to read: `(fd,)` while the fd is open and
  `closed` is `None`; `()` after (a hung-up pty in Clock's `select` would make every
  wait return a {Closed} at once).
- `pending -> int`: bytes waiting in the outbox (wait to write on `fd` while > 0).
- `dropped -> int`: bytes refused since the spawn because the outbox was full: those
  `write` (and `send`) refused, and the replies `read` could not queue.
- `closed -> Closed | None`: the sticky {Closed} the fd met (its output ended, or a
  write failed), or `None`.
- `returncode -> int | None`: `None` while the child runs (or once it was reaped by
  someone else); its exit status once reaped: the exit code (>= 0), or `-n` when
  signal `n` ended it (`os.waitstatus_to_exitcode`).
- `exited -> bool`: the child has been reaped (by `poll` / `close`, or found reaped by
  someone else, e.g. an app that set `SIGCHLD` to `SIG_IGN`).
- A context manager: `__enter__` returns the handle; `__exit__` calls `close()` and
  lets any exception go on.

`read(limit=READ) -> Grid | None | Closed` (the program's `output({Bytes})`, through
`[Pty] -> [Vt] : apply`), never blocking:
1. `closed` is set: return it (the fd is not touched).
2. `os.read` from the master (more than once if a read returns less than asked) until
   it would block (`EAGAIN`: nothing more now), `limit` bytes are taken, or the output
   ends: `b""` from a read is `Closed("eof", fd)` (BSD, macOS); an `OSError` is
   `Closed.of(error, fd)`: on Linux the master reads `EIO` once the program's side is
   closed and drained (the child and every process holding the pty have exited), so
   the usual end is `Closed("eio", fd, errno.EIO)`. `EINTR` is retried.
3. Bytes were read: `output(screen, data)`; the other events join `take`'s queue;
   then, when `replies` is not empty and no end was met in this call, the replies go
   to the outbox as one `write(replies)` of all of them joined, with `write`'s rule
   and order: past the bound (`pending + len(replies) > MAX_PENDING`) they are
   refused whole (no reply is cut inside its sequence, and none of this read's
   replies is sent), `dropped` grows by `len(replies)`, and nothing is flushed; else
   they join the outbox behind what was waiting (the outbox stays in order: the
   app's earlier writes, then the replies) and the outbox is flushed (as `flush`). A
   flush that fails sets `closed` (the outbox emptied), which the next `read`
   returns. An end met in this call leaves the replies unsent and uncounted (the
   program's side is gone; `dropped` counts only the bound's refusals). The grid is
   returned in every case (a refusal or a failed flush is no error of the read; the
   app sees it in `dropped` / `closed`). An end met in the same call is kept as
   `closed` and returned by the next `read` (so the last bytes are always shown
   first).
4. No bytes: the end's {Closed}, now `closed`, or `None` (nothing to read).
`limit`: int >= 1.
Law (bounded outbox): after any sequence of `read`, `write`, `send` and `flush` calls,
  `pending <= MAX_PENDING`, whatever the program sends; and the bytes offered to the
  outbox (`write`'s non-empty `data` while `closed` is `None`, plus each read's joined
  `replies` when no end was met in it) equal the bytes the outbox took plus the growth
  of `dropped`. A test checks it on a pty that never drains (a child that never reads
  its input, or a fake fd whose `os.write` always raises `BlockingIOError`): `write`
  input until the outbox is near `MAX_PENDING`, then let the program flood
  `ESC[6n` queries: each `read` returns a Grid, `pending` stays `<= MAX_PENDING`,
  `dropped` grows by each refused read's `len(replies)`, and the outbox's bytes are
  whole replies (each `ESC[<row>;<col>R` complete).

`take() -> tuple[Event, ...]`: the `Title`, `Cwd`, `Clipboard` and `Bell` events the
reads gave since the last `take`, in order (replies never appear: `read` wrote them
or refused them),
and empties the queue. At most `MAX_EVENTS`; past that the oldest is dropped. Works in
every state, after `close` too.

`send(event) -> None | Closed` (`[Pty] -> [Vt] : encode`): `write(forward(event,
screen.modes))`, the modes being the ones in force at the call. `forward` runs first
(its errors raise whatever the state); then as `write`.

`write(data) -> None | Closed`: raw bytes for the program's input (the app's
responsibility; a person's input goes through `send`). In order: `closed` set: return
it; `data` empty: `None`; `pending + len(data) > MAX_PENDING`: `data` is refused
whole (never cut inside a sequence), `dropped` grows by its length, `None`; else
`data` joins the outbox and the outbox is flushed (as `flush`). `read` queues the
program's query replies through this same rule (see `read`, step 3).

`flush() -> None | Closed`: `os.write` the outbox from its front until it is empty or
a write would block (`EAGAIN`: the rest waits; the app waits to write on `fd` while
`pending`); written bytes leave the outbox; `EINTR` is retried. An `OSError`:
`Closed.of(error, fd)` (on Linux, `EIO` once the program's side is gone), kept as
`closed`, the outbox emptied, and returned. `closed` set: return it, the fd untouched.
Else `None`.

`resize(w, h) -> None | Closed` (TIOCSWINSZ): `w`, `h` ints 1..`MAX_SIZE`. The same
size as `size`: nothing happens, `None` (no ioctl, so no `SIGWINCH`). Else, in order:
`screen.resize(w, h)` (Vt reflows the primary buffer), `size` updated; then, while the
fd is open and `closed` is `None`, `TIOCSWINSZ` on the master (rows `h`, columns `w`):
the kernel sends `SIGWINCH` to the pty's foreground process group, and the program
redraws in later output. An `OSError` from the ioctl: `Closed.of(error, fd)`, kept as
`closed` and returned. After the output ended or after `close`: the screen alone is
resized (a dead pane's last screen still reflows), `None`. Before the program has
drawn anything is no special case: `spawn`'s `size` was set before the spawn.

`poll() -> int | None`: reap the child if it has exited, never blocking:
`os.waitpid(pid, os.WNOHANG)`; exited: `returncode` set, `exited` true; still running:
`None`; `ChildProcessError` (someone else reaped it): `exited` true, `returncode`
`None`. Once `exited`, returns `returncode` without a system call. Returns
`returncode`. The output's end and the child's exit are separate facts: a program may
exit while a background process it started still holds the pty (no end yet), or close
its output before it exits; the app calls `poll` (or `close`) once `read` returned
the {Closed}, or on its own timer.

`kill(sig=signal.SIGTERM) -> bool`: `os.killpg(pid, sig)`, the child's whole process
group; `True` when sent. `False`, sending nothing, once `exited` (the pid may belong to
another process by then: a reaped child is never signalled), or on
`ProcessLookupError` / `PermissionError`. It does not reap (`poll` / `close` do).
`sig`: an `int` or `signal.Signals` in `signal.valid_signals()`.

`close(grace=CLOSE) -> int | None`: end the pane: no fd left, no zombie. In order:
1. A second `close`: return `returncode` (idempotent).
2. The master closed (`fd` `None`, `fds` `()`, the outbox dropped; an `OSError` from
   `os.close` ignored): the kernel hangs up the pty.
3. Not `exited`: `poll()`; still running: `os.killpg(pid, SIGHUP)`; then `poll()`
   every `STEP` seconds (sleeping through Clock's `select((), STEP)`) until it has
   exited or `grace` seconds have passed (`time.monotonic`); still running:
   `os.killpg(pid, SIGKILL)` and a blocking `os.waitpid(pid, 0)` (bounded: `SIGKILL`
   cannot be caught). `ProcessLookupError`, `PermissionError` and `ChildProcessError`
   on the way are absorbed (as `poll` states them).
4. Return `returncode` (`None` when someone else reaped it).
After `close`, `exited` is true. Processes the program moved into other process groups
of its session get the kernel's hangup, but are not ours to reap. `grace`: a real
number >= 0 (0: `SIGKILL` right after `SIGHUP`). `close` may block up to `grace`
seconds plus the `SIGKILL`'s reaping: call it when the pane goes, not every frame.

After `close`: `read`, `send`, `write` and `flush` raise `RuntimeError` (a closed pane
is the app's error); `resize`, `take`, `poll`, `kill`, `grid` and the properties still
work. A `Pty` dropped without `close` keeps its fd and its child until the app's
process exits (no finalizer: the app owns it).

## In the app's loop

The app waits on its Term's fds and its panes' together, then calls the steps:

    ready = select(term.fds + pty.fds, timers.due(now),
                   write=pty.fds if pty.pending else ())
    if pty.fd in getattr(ready, "write", ()): pty.flush()
    grid = pty.read()        # a Grid to give the Pane, None, or the pane's Closed

A hung-up pty makes Clock's `select` return `Closed("hangup", pty.fd)` in place of a
`Ready`: the app then calls `pty.read()`, which returns the pty's own {Closed} and
drops the fd from `pty.fds`, then `pty.poll()` / `pty.close()` for the exit status.

Re-exported by the package: everything public here and [SpawnFailed]'s names.

Inputs: `argv` ({Command}), `size`, `env`, `cwd`, `timeout` as above; `data` {Bytes};
  `event` an Input {Event} (duck-typed); `modes` a Vt `Modes`; `screen` a Vt `Screen`.
Outputs: `spawn`: a `Pty` (its `fd` the {Fd}) or a {SpawnFailed}; `output`: a {Grid},
  {Bytes} and events; `forward`: {Bytes}; `read`: a {Grid}, `None` or a {Closed};
  `send` / `write` / `flush` / `resize`: `None` or a {Closed}; `take`: events; `poll`
  / `close`: an exit status or `None`; `kill`: `bool`.
Errors: `spawn`, before anything is opened: `TypeError` when `argv` is not a `list` /
  `tuple` or holds a non-`str`, `size` is not a 2-tuple of ints, `env` is neither
  `None` nor a `Mapping` of `str` to `str`, `cwd` is neither `None`, a `str` nor an
  `os.PathLike` of `str`, `timeout` is not a real number (a `bool` is refused wherever
  a number is meant); `ValueError` when `argv` is empty, `argv[0]` is "", an argument,
  env key or value, or `cwd` holds "\\0", an env key is "" or holds "=", a size value is
  outside 1..`MAX_SIZE`, or `timeout` is not finite and > 0. No `OSError` escapes
  `spawn`: an OS failure is a returned {SpawnFailed}. The handle: `TypeError` /
  `ValueError` for `limit`, `w` / `h`, `grace`, `sig` and `data` (not bytes-like) as
  stated; `RuntimeError` as stated after `close`; `output` / `forward`'s errors.
  No `OSError` escapes any method: an fd failure is a returned {Closed}, a process
  failure is absorbed as stated.
Effects: as "What is pure and what touches fds" lists them; no signal handler is
  installed in the parent, no thread is started, no loop is run.

Usage:
    import errno, sys
    from cure.edge.clock import select, Closed
    from cure.edge.embed import spawn, SpawnFailed, output, forward
    from cure.interact.vt import Screen, Modes
    p = spawn([sys.executable, "-c", "print('hi')"], size=(20, 3), env={"TERM": "xterm"})
    # a Pty: p.fd its master, p.size == (20, 3)
    select(p.fds, 2.0)       # Ready(read=(p.fd,)) once the child printed
    p.read()                 # a Grid: row 0 "hi"; p.screen.cursor() is at (0, 1)
    p.read()                 # None, or Closed("eio", p.fd, errno.EIO) once the child is gone
    p.close()                # 0 (its exit status); p.exited is True, p.fds == ()
    spawn(["/no/such/program"])     # SpawnFailed(("/no/such/program",), "exec", errno.ENOENT)
    spawn(["sh"], cwd="/no/such")   # SpawnFailed(("sh",), "chdir", errno.ENOENT)
    spawn("sh")                     # TypeError: a str is not an argv
    s = Screen(10, 2)
    output(s, b"ok\\x1b[6n")        # (a Grid with "ok" on row 0, b"\\x1b[1;3R", ())
    # forward: Key from cure.interact.input.events (or any class named "Key")
    forward(Key("a", text="a"), Modes())                     # b"a"
    forward(Key("a", text="a", event="release"), Modes())    # b"": releases are dropped
    forward(Key("a", text="a", event="repeat"), Modes())     # b"a": repeats type as presses
"""

import signal as _signal

import errno as _errno
import fcntl as _fcntl
import math as _math
import os
import struct as _struct
import sys
import termios as _termios
import time as _time
from collections import deque as _deque
from collections.abc import Mapping as _Mapping
from numbers import Real as _Real

from cure.edge.clock import Closed, select
from cure.interact.vt import Modes, Reply, Screen, apply, encode

from .spawnfailed import STAGES, SpawnFailed

SIZE = (80, 24)
SPAWN = 5.0  # seconds: @timeout(spawn)
CLOSE = 0.5  # seconds: close's grace between SIGHUP and SIGKILL
STEP = 0.01  # seconds between polls while close waits
READ = 65536  # the most bytes one read takes
MAX_PENDING = 1 << 20  # the most bytes the outbox holds
MAX_EVENTS = 4096  # the most events take holds
MAX_SIZE = 65535  # TIOCSWINSZ's fields are unsigned shorts
EXIT_FAILED = 127  # the child's status when it could not exec
RESET = (
    _signal.SIGPIPE, _signal.SIGXFSZ, _signal.SIGINT, _signal.SIGQUIT, _signal.SIGTSTP,
    _signal.SIGTTIN, _signal.SIGTTOU, _signal.SIGHUP, _signal.SIGTERM, _signal.SIGCHLD,
    _signal.SIGWINCH,
)

_KEY_EVENTS = ("press", "repeat", "release")
_CHILD_STAGES = ("tty", "chdir", "exec")  # the stages the boot can report
_TIMEOUT = object()  # _await_report's "no answer in time"

# The boot: the only code that runs in the new process before the program. A fresh
# `python -I -S -X utf8 -c _BOOT` (single-threaded, holding no lock of the caller's; no
# data on its command line), started by `spawn`'s one `os.posix_spawn` with the slave on
# fds 0, 1, 2, the status pipe's write end on fd 3 and the payload's carrier on fd 4. It
# reads the payload, writes `b"+"` (it ran), sets up the pty and
# execs the program in place (same pid), or writes `<stage>:<errno>` and `_exit`s.
_BOOT = """\
import os, signal
os.write(3, b"+")
stage = "tty"
try:
    try:
        os.set_inheritable(3, False)
        for sig in (%(reset)s):
            signal.signal(sig, signal.SIG_DFL)
        signal.pthread_sigmask(signal.SIG_SETMASK, ())
        os.login_tty(0)
        data = []
        while True:
            chunk = os.read(4, 1 << 20)
            if not chunk:
                break
            data.append(chunk)
        os.close(4)
        a = b"".join(data).split(b"\\0")[:-1]
        try:
            maxfd = os.sysconf("SC_OPEN_MAX")
        except (OSError, ValueError):
            maxfd = -1
        os.closerange(4, maxfd if maxfd > 0 else 256)
        n = int(a[1])
        args = a[2:2 + n]
        env = dict(kv.split(b"=", 1) for kv in a[2 + n:])
        if a[0] != b"-":
            stage = "chdir"
            os.chdir(a[0][1:])
        stage = "exec"
        os.execvpe(args[0], args, env)
    except OSError as error:
        code = "" if error.errno is None else str(error.errno)
        os.write(3, (stage + ":" + code).encode("ascii"))
    except BaseException:
        os.write(3, (stage + ":").encode("ascii"))
finally:
    os._exit(%(failed)d)
""" % {"reset": ", ".join(f"signal.{sig.name}" for sig in RESET), "failed": EXIT_FAILED}


def output(screen: Screen, data) -> "tuple[object, bytes, tuple]":
    """The program's bytes performed on its screen: (grid, replies, other events) (see the module)."""
    grid = apply(screen, data)
    events = screen.take()
    replies = b"".join(e.data for e in events if isinstance(e, Reply))
    others = tuple(e for e in events if not isinstance(e, Reply))
    return grid, replies, others


def forward(event, modes: Modes) -> bytes:
    """A person's event as the pane's modes want it; Key releases dropped, repeats as presses (see the module)."""
    if type(event).__name__ == "Key":
        kind = getattr(event, "event", "press")
        if not isinstance(kind, str):
            raise TypeError(f"Key.event must be a str, got {type(kind).__name__}")
        if kind not in _KEY_EVENTS:
            raise ValueError(f"Key.event must be one of {_KEY_EVENTS}, got {kind!r}")
        if kind == "release":
            return b""
    return encode(event, modes)


def spawn(argv, *, size: "tuple[int, int]" = SIZE, env=None, cwd=None,
          timeout: float = SPAWN) -> "Pty | SpawnFailed":
    """Start exactly `argv` on a new pty (one posix_spawn, a boot that execs it); the Pty, or the SpawnFailed (see the module)."""
    argv = _check_argv(argv)
    w, h = _check_size(size)
    env = _check_env(env)
    cwd = _check_cwd(cwd)
    _check_timeout(timeout)

    # 1. the pty, its size, the master non-blocking
    try:
        master, slave = os.openpty()
    except OSError as error:
        return SpawnFailed(argv, "pty", error.errno)
    try:
        _set_winsize(slave, w, h)
        os.set_blocking(master, False)
    except OSError as error:
        _close_all(master, slave)
        return SpawnFailed(argv, "pty", error.errno)

    # 2. the status pipe, then one posix_spawn of the boot interpreter
    try:
        r, wr = os.pipe()
    except OSError as error:
        _close_all(master, slave)
        return SpawnFailed(argv, "fork", error.errno)
    if not sys.executable:
        _close_all(master, slave, r, wr)
        return SpawnFailed(argv, "fork", _errno.ENOENT)
    if env is None:
        env = dict(os.environ)  # the parent's environment as it is at the spawn
    try:
        carrier = _carrier(_payload(argv, env, cwd))  # the payload, written in full
    except OSError as error:
        _close_all(master, slave, r, wr)
        return SpawnFailed(argv, "fork", error.errno)
    high = []  # the slave, the write end and the carrier again, all >= 5: no action clashes
    try:
        high.append(_fcntl.fcntl(slave, _fcntl.F_DUPFD_CLOEXEC, 5))
        high.append(_fcntl.fcntl(wr, _fcntl.F_DUPFD_CLOEXEC, 5))
        high.append(_fcntl.fcntl(carrier, _fcntl.F_DUPFD_CLOEXEC, 5))
        exe = os.fsencode(sys.executable)
        pid = os.posix_spawn(
            exe, [exe, b"-I", b"-S", b"-X", b"utf8", b"-c", os.fsencode(_BOOT)],
            os.environ, setsigmask=(), setsigdef=RESET,
            file_actions=[(os.POSIX_SPAWN_DUP2, high[0], 0),
                          (os.POSIX_SPAWN_DUP2, high[0], 1),
                          (os.POSIX_SPAWN_DUP2, high[0], 2),
                          (os.POSIX_SPAWN_DUP2, high[1], 3),
                          (os.POSIX_SPAWN_DUP2, high[2], 4)])
    except OSError as error:
        _close_all(master, slave, r, wr, carrier, *high)
        return SpawnFailed(argv, "fork", error.errno)

    # 4. the parent: wait for the exec or the boot's report
    _close_all(slave, wr, carrier, *high)
    report = _await_report(r, timeout)
    _close_all(r)
    if report == b"+":  # the boot ran and the exec happened
        return Pty._made(master, pid, argv, (w, h))
    if report is _TIMEOUT or not report.startswith(b"+"):  # no answer, or no boot
        _absorb(os.kill, pid, _signal.SIGKILL)
    _reap(pid)
    _close_all(master)
    if report is _TIMEOUT:
        return SpawnFailed(argv, "timeout")
    stage, code = _parse_report(report)
    return SpawnFailed(argv, stage, code)


class Pty:
    """A program in a pane: its pty's master, its pid, its Vt screen, its outbox (see the module)."""

    def __init__(self, *args, **kwargs) -> None:
        raise TypeError("a Pty is made only by spawn")

    @classmethod
    def _made(cls, fd: int, pid: int, argv: "tuple[str, ...]", size: "tuple[int, int]") -> "Pty":
        self = cls.__new__(cls)
        self._fd = fd
        self._pid = pid
        self._argv = argv
        self._size = size
        self._screen = Screen(*size)
        self._outbox = bytearray()
        self._dropped = 0
        self._closed = None
        self._returncode = None
        self._exited = False
        self._shut = False
        self._events = _deque(maxlen=MAX_EVENTS)
        return self

    @property
    def fd(self) -> "int | None":
        """The master side ({Fd}); None once closed."""
        return self._fd

    @property
    def pid(self) -> int:
        """The child's pid (its session and process group leader)."""
        return self._pid

    @property
    def argv(self) -> "tuple[str, ...]":
        """The command as handed."""
        return self._argv

    @property
    def screen(self) -> Screen:
        """The program's Vt screen."""
        return self._screen

    @property
    def size(self) -> "tuple[int, int]":
        """`(w, h)` as last set."""
        return self._size

    @property
    def fds(self) -> "tuple[int, ...]":
        """`(fd,)` while open and not closed; `()` after."""
        if self._fd is None or self._closed is not None:
            return ()
        return (self._fd,)

    @property
    def pending(self) -> int:
        """Bytes waiting in the outbox."""
        return len(self._outbox)

    @property
    def dropped(self) -> int:
        """Bytes refused because the outbox was full (`write`'s, and `read`'s replies)."""
        return self._dropped

    @property
    def closed(self) -> "Closed | None":
        """The sticky Closed the fd met, or None."""
        return self._closed

    @property
    def returncode(self) -> "int | None":
        """The exit status once reaped (code, or -signal); None while running or when lost."""
        return self._returncode

    @property
    def exited(self) -> bool:
        """The child has been reaped (by us or someone else)."""
        return self._exited

    def grid(self, *, live: bool = False):
        """`screen.grid(live=live)`: what the Pane widget is given."""
        return self._screen.grid(live=live)

    def read(self, limit: int = READ) -> "object | None | Closed":
        """Read what the program wrote (non-blocking) into the screen; the Grid, None, or the Closed."""
        _check_int(limit, "limit", 1, None)
        self._open_or_raise("read")
        if self._closed is not None:
            return self._closed
        data, end = self._drain(limit)
        if end is not None:
            self._closed = end
        if not data:
            return end
        grid, replies, others = output(self._screen, data)
        self._events.extend(others)
        if replies and self._closed is None:
            self.write(replies)
        return grid

    def take(self) -> tuple:
        """The Title / Cwd / Clipboard / Bell events since the last take, in order."""
        events = tuple(self._events)
        self._events.clear()
        return events

    def send(self, event) -> "None | Closed":
        """`write(forward(event, screen.modes))`."""
        return self.write(forward(event, self._screen.modes))

    def write(self, data) -> "None | Closed":
        """Raw bytes to the program's input, through the bounded outbox."""
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError(f"data must be bytes, bytearray or memoryview, got {type(data).__name__}")
        self._open_or_raise("write")
        if self._closed is not None:
            return self._closed
        if isinstance(data, memoryview):
            data = data.tobytes()
        if not data:
            return None
        if len(self._outbox) + len(data) > MAX_PENDING:
            self._dropped += len(data)
            return None
        self._outbox += data
        return self.flush()

    def flush(self) -> "None | Closed":
        """Write the outbox until empty or it would block."""
        self._open_or_raise("flush")
        if self._closed is not None:
            return self._closed
        while self._outbox:
            try:
                n = os.write(self._fd, self._outbox)
            except (BlockingIOError, InterruptedError) as error:
                if isinstance(error, InterruptedError):
                    continue
                break
            except OSError as error:
                self._closed = Closed.of(error, self._fd)
                self._outbox.clear()
                return self._closed
            del self._outbox[:n]
        return None

    def resize(self, w: int, h: int) -> "None | Closed":
        """The screen resized and TIOCSWINSZ set on the pty (see the module)."""
        _check_int(w, "w", 1, MAX_SIZE)
        _check_int(h, "h", 1, MAX_SIZE)
        if (w, h) == self._size:
            return None
        self._screen.resize(w, h)
        self._size = (w, h)
        if self._fd is not None and self._closed is None:
            try:
                _set_winsize(self._fd, w, h)
            except OSError as error:
                self._closed = Closed.of(error, self._fd)
                return self._closed
        return None

    def poll(self) -> "int | None":
        """Reap the child if it exited (never blocks); its returncode."""
        if self._exited:
            return self._returncode
        try:
            pid, status = os.waitpid(self._pid, os.WNOHANG)
        except ChildProcessError:
            self._exited = True
            return None
        except OSError:
            return None
        if pid == 0:
            return None
        self._exit_with(status)
        return self._returncode

    def kill(self, sig: int = _signal.SIGTERM) -> bool:
        """Signal the child's process group, unless it was reaped; whether it was sent."""
        if isinstance(sig, bool) or not isinstance(sig, int):
            raise TypeError(f"sig must be an int or signal.Signals, got {type(sig).__name__}")
        if sig not in _signal.valid_signals():
            raise ValueError(f"not a valid signal: {sig}")
        if self._exited:
            return False
        try:
            os.killpg(self._pid, sig)
        except OSError:
            return False
        return True

    def close(self, grace: float = CLOSE) -> "int | None":
        """Close the master, SIGHUP, wait `grace`, SIGKILL, reap; the returncode."""
        if isinstance(grace, bool) or not isinstance(grace, _Real):
            raise TypeError(f"grace must be a real number, got {type(grace).__name__}")
        if not grace >= 0:
            raise ValueError(f"grace must be >= 0, got {grace}")
        if self._shut:
            return self._returncode
        self._shut = True
        fd, self._fd = self._fd, None
        self._outbox.clear()
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if self._exited:
            return self._returncode
        self.poll()
        if self._exited:
            return self._returncode
        _absorb(os.killpg, self._pid, _signal.SIGHUP)
        deadline = _time.monotonic() + grace
        while True:
            self.poll()
            if self._exited:
                return self._returncode
            left = deadline - _time.monotonic()
            if left <= 0:
                break
            select((), min(STEP, left))
        _absorb(os.killpg, self._pid, _signal.SIGKILL)
        try:
            _, status = os.waitpid(self._pid, 0)
        except OSError:
            self._exited = True
            return self._returncode
        self._exit_with(status)
        return self._returncode

    def __enter__(self) -> "Pty":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- private

    def _open_or_raise(self, step: str) -> None:
        if self._shut:
            raise RuntimeError(f"{step} on a closed Pty")

    def _exit_with(self, status: int) -> None:
        try:
            self._returncode = os.waitstatus_to_exitcode(status)
        except ValueError:
            self._returncode = None
        self._exited = True

    def _drain(self, limit: int) -> "tuple[bytes, Closed | None]":
        """Read the master until it would block, `limit` bytes are taken, or the output
        ends; the bytes and the end's Closed (or None)."""
        chunks, got, end = [], 0, None
        while got < limit:
            try:
                chunk = os.read(self._fd, limit - got)
            except BlockingIOError:
                break
            except InterruptedError:
                continue
            except OSError as error:
                end = Closed.of(error, self._fd)
                break
            if not chunk:
                end = Closed("eof", self._fd)
                break
            chunks.append(chunk)
            got += len(chunk)
        return b"".join(chunks), end


# -- spawn's steps


def _payload(argv: "tuple[str, ...]", env: dict, cwd: "str | None") -> bytes:
    """The boot's payload for fd 4: the cwd (`-` or `+cwd`), `len(argv)`, argv, then `k=v`
    for the child's env, each as `os.fsencode` bytes ended by one NUL."""
    head = [b"-" if cwd is None else b"+" + os.fsencode(cwd), str(len(argv)).encode("ascii")]
    fields = head + [os.fsencode(a) for a in argv] + [os.fsencode(f"{k}={v}") for k, v in env.items()]
    return b"".join(field + b"\0" for field in fields)


def _carrier(payload: bytes) -> int:
    """A fd to read `payload` from, written in full now (nothing writes after the spawn):
    a memfd at offset 0 where `os.memfd_create` exists, else a pipe's read end (its write
    end closed). An `OSError` on failure (`E2BIG`: the payload does not fit the pipe), no
    fd left open."""
    memfd = getattr(os, "memfd_create", None)
    if memfd is not None:
        fd = memfd("cure-spawn", os.MFD_CLOEXEC)
        try:
            _write_all(fd, payload)
            os.lseek(fd, 0, os.SEEK_SET)
        except OSError:
            _close_all(fd)
            raise
        return fd
    r, w = os.pipe()
    try:
        setsz = getattr(_fcntl, "F_SETPIPE_SZ", None)
        if setsz is not None:
            try:
                size = _fcntl.fcntl(w, _fcntl.F_GETPIPE_SZ)
                if len(payload) > size:
                    _fcntl.fcntl(w, setsz, len(payload))
            except OSError:
                pass  # the pipe keeps its size; a payload too big is E2BIG below
        os.set_blocking(w, False)
        try:
            _write_all(w, payload)
        except BlockingIOError:
            raise OSError(_errno.E2BIG, os.strerror(_errno.E2BIG)) from None
    except OSError:
        _close_all(r, w)
        raise
    _close_all(w)
    return r


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]


def _await_report(r: int, timeout: float) -> "object":
    """Read the status pipe to its end within `timeout`: the bytes the boot wrote (`b""`
    when nothing), or _TIMEOUT."""
    deadline = _time.monotonic() + timeout
    got = bytearray()
    while True:
        left = deadline - _time.monotonic()
        if left <= 0:
            return _TIMEOUT
        ready = select([r], left)
        if isinstance(ready, Closed):  # the write end closed with nothing left: the end
            break
        if not ready:
            continue
        try:
            chunk = os.read(r, 512)
        except InterruptedError:
            continue
        except OSError:
            return b"?"  # an unreadable report: parsed as "exec", None
        if not chunk:
            break
        got += chunk
    return bytes(got)


def _parse_report(report: bytes) -> "tuple[str, int | None]":
    """The boot's `b"+<stage>:<errno>"` as (stage, errno); ("exec", None) when it does not parse."""
    if not report.startswith(b"+"):  # the boot never ran its first line
        return "exec", None
    try:
        stage, colon, code = report[1:].decode("ascii").partition(":")
    except UnicodeDecodeError:
        return "exec", None
    if not colon or stage not in _CHILD_STAGES:
        return "exec", None
    if code == "":
        return stage, None
    if not code.isdigit() or not code.isascii():
        return "exec", None
    return stage, int(code)


def _reap(pid: int) -> None:
    """A blocking `waitpid` on a child that is exiting (or killed); errors absorbed."""
    try:
        os.waitpid(pid, 0)
    except OSError:
        pass


def _absorb(call, *args) -> None:
    """`call(*args)`, a process failure (no such process, not permitted) absorbed."""
    try:
        call(*args)
    except OSError:
        pass


def _close_all(*fds: int) -> None:
    for fd in fds:
        try:
            os.close(fd)
        except OSError:
            pass


def _set_winsize(fd: int, w: int, h: int) -> None:
    _fcntl.ioctl(fd, _termios.TIOCSWINSZ, _struct.pack("HHHH", h, w, 0, 0))


# -- argument checks


def _check_int(value: object, name: str, lo: int, hi: "int | None") -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if value < lo or (hi is not None and value > hi):
        bound = f"{lo}..{hi}" if hi is not None else f">= {lo}"
        raise ValueError(f"{name} must be {bound}, got {value}")


def _no_nul(text: str, what: str) -> None:
    if "\0" in text:
        raise ValueError(f"{what} must not hold a NUL")


def _check_argv(argv: object) -> "tuple[str, ...]":
    if not isinstance(argv, (list, tuple)):
        raise TypeError(f"argv must be a list or tuple of str, got {type(argv).__name__}")
    for item in argv:
        if not isinstance(item, str):
            raise TypeError(f"argv must hold only str, got {type(item).__name__}")
    if not argv:
        raise ValueError("argv must not be empty")
    if argv[0] == "":
        raise ValueError("argv[0] must not be empty")
    for item in argv:
        _no_nul(item, "an argument")
    return tuple(argv)


def _check_size(size: object) -> "tuple[int, int]":
    if not isinstance(size, tuple) or len(size) != 2:
        raise TypeError(f"size must be a (w, h) tuple of ints, got {size!r}")
    for value in size:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"size must hold ints, got {type(value).__name__}")
    w, h = size
    _check_int(w, "w", 1, MAX_SIZE)
    _check_int(h, "h", 1, MAX_SIZE)
    return w, h


def _check_env(env: object) -> "dict | None":
    if env is None:
        return None
    if not isinstance(env, _Mapping):
        raise TypeError(f"env must be None or a Mapping of str to str, got {type(env).__name__}")
    items = dict(env)
    for key, value in items.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise TypeError("env must map str to str")
    for key, value in items.items():
        if key == "" or "=" in key:
            raise ValueError(f"not an environment name: {key!r}")
        _no_nul(key, "an env key")
        _no_nul(value, "an env value")
    return items


def _check_cwd(cwd: object) -> "str | None":
    if cwd is None:
        return None
    if isinstance(cwd, os.PathLike):
        cwd = os.fspath(cwd)
    if not isinstance(cwd, str):
        raise TypeError(f"cwd must be None, a str or a PathLike of str, got {type(cwd).__name__}")
    _no_nul(cwd, "cwd")
    return cwd


def _check_timeout(timeout: object) -> None:
    if isinstance(timeout, bool) or not isinstance(timeout, _Real):
        raise TypeError(f"timeout must be a real number, got {type(timeout).__name__}")
    if not (_math.isfinite(timeout) and timeout > 0):
        raise ValueError(f"timeout must be finite and > 0, got {timeout}")
