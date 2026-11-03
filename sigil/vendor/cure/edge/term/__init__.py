"""[Term]: the tty: modes, probe, read, write; opened and closed exactly, called from the
app's own loop.

Kind: system (the expansion of [Term] in Edge) and its boundary, the Term handle: one
`Term` per terminal, composing [Modes], [Probe], [Reader], [Writer], [Signals], [Osc]
and Core's [Display]. It has no loop: the app calls `open`, then `read` / `show` from
its own loop, then `close`. No process-wide state, no `atexit`, no handler the app did
not ask for; the fds, the environment, the size and the clock are arguments.

The boundary (the ops other parts call), defined here:
- `open(term, modes=None) -> Caps` ((Sigil) / [Attach] / [Remote] -> [Term] :
  open({Modes}) => {Caps}): `term.open(modes)`.
- `show(term, grid, *, cursor=None) -> None | Closed` ([Attach] -> [Term] :
  show({Grid}) => {Shown} !> <Closed>): `term.show(grid, cursor=cursor)`, exactly the
  handle's `show` below: the frame's bytes, which the term's own {Display} builds (only
  the change), written through its one [Writer]; `None` (the drawn {Shown}, which is
  nothing: the bytes go to the terminal, not back), or the writer's {Closed} (the
  drawn `!> <Closed>`, returned: the Display invalidated, the {Closed} kept). Its errors are the handle's: `RuntimeError` before `open`
  or after `close`; what `Display.show` raises for a bad `grid` / `cursor`, nothing
  written. Like `open`, it does not check that `term` is a Term (a non-Term raises
  `AttributeError` from the call).

The handle:
- `Term(fd_in=0, out=1, *, env=None, size=None, tick=TICK, timeout=PROBE,
  signals=False, tty=None, now=time.monotonic, stop=None)`:
  - `fd_in`: the input fd (`int` >= 0), or `None` for a headless terminal whose input
    is only what `term.reader.type(...)` puts in;
  - `out`: the output fd (`int` >= 0), from which the handle builds its one
    `Writer(out)`, or a [Writer] to use as it is (a headless sink, a pipe in a test);
  - `env`: the environment mapping the probe reads (`None`: `os.environ`, read at
    `open`);
  - `size`: `None` (measure: `size_of((out fd, fd_in), env)` from [Signals]) or a fixed
    `(w, h)` (headless, a server's client): never measured;
  - `tick`: seconds > 0, the longest one `read` waits, so the size is polled at least
    that often (`@timeout(tick)`); `timeout`: seconds > 0, the probe's deadline
    (`@timeout(probe)`);
  - `signals`: `bool`, the app opts in to [Signals]' handlers (WINCH, TSTP, CONT,
    TERM, HUP), installed by `open` and restored by `close`; off: the poll only;
  - `tty`: `None` (detect: the writer has an fd and `os.isatty` of it, and `fd_in` is
    `None` or `os.isatty(fd_in)`), or forced `True` / `False`. Not a tty (a pipe,
    `--once`, a server): `open` touches no termios, sends no query and no mode, and
    the caps are `env_caps(env, tty=False)`; frames are still written;
  - `now`: a callable returning monotonic seconds (the probe's deadline);
  - `stop`: a callable that stops the process until it is continued (`None`:
    `os.kill(os.getpid(), signal.SIGTSTP)`); `suspend` calls it, so a test injects
    one that returns at once.
- Read-only attributes: `caps` (the {Caps} `open` returned; `None` before), `size`
  (`(w, h)`, as measured by `open` and the latest `read`), `reader` (its [Reader]
  over `fd_in`), `writer` (its one [Writer]), `display` (its Core `Display`, built by
  `open` at `caps`; `None` before), `plan` (the `Pair`s `open` set, `()` before),
  `signals` (its [Signals]), `fds` (the fds to wait on: `fd_in` when not `None`, then
  the self-pipe while installed; for an app waiting with Clock's [Wait] on more fds,
  which then calls `read(timeout=0)`), `events` (the {Event}s the latest `read`
  handled), `closed` (the sticky {Closed}, or `None`), `opened` (`bool`: between a
  successful `open` and `close`).
- A context manager: `__enter__` returns the term (it does not open: `open` takes the
  modes and returns the caps); `__exit__` calls `close()` and lets any exception go on.

`open(modes=None) -> Caps`, `modes` a {Modes} (`None`: `Modes()`), in order:
1. `signals`: `install` ([Signals]); `False` is the polling fallback, not an error.
2. A tty: `enter(fd_in, modes.input)` ([Modes]: termios saved, raw or cbreak).
3. Caps: a tty and `modes.probe`: `probe(env, reader=..., writer=..., tty=True,
   timeout=timeout, now=now)` ([Probe]; it writes `QUERIES` first); else
   `env_caps(env, tty=tty)`.
4. A tty: `plan(modes, caps)` and `set(writer, plan)` ([Modes]: one write).
5. `display = Display(caps)`; `size` measured (or the fixed one), then [Signals]'
   public `baseline(signals, size)` (the size the first `read`'s `on` compares with:
   no resize event for the size `open` found; the handle calls no private name of
   `signals.py`); `opened` true.
6. Return `caps`.
So a tty's writer receives exactly `QUERIES` (when probing) then the plan's `on` bytes.
`open` never fails on the terminal's account: a {Closed} met on the way (the writer's,
the reader's) is kept as `closed`, the caps fall back to the env, and the app's next
`read` / `show` returns it. When anything raises inside `open`, what was already set is
undone (as `close` does) before the error leaves.

`read(timeout=None) -> bytes | Closed` (the README's `term.read(timeout=clock.due(now))`):
1. `closed` is set: return it (after any inbox bytes the reader still holds: they come
   first).
2. Wait: `reader.read(t, wake=(self-pipe,))` with `t = tick` when `timeout` is `None`,
   else `max(0, min(timeout, tick))`. So `read` may return `b""` before `timeout`: the
   app's loop goes round again (the idle frame is silent).
3. Measure the size and take `on(signals, size)`'s events (`events`), handling each in
   order: `"resize"`: `size` updated and `display.invalidate()` (a full repaint at the
   new size); `"suspend"`: `suspend()`; `"resume"` not caused by our own `suspend`:
   `enter` again (the shell may have reset termios) and `display.invalidate()`;
   `"terminate"`: `closed = Closed("terminate")`; `"hangup"`: `closed =
   Closed("hangup")`.
4. `closed` set by step 3: return it (bytes read in step 2 are then dropped: the app is
   leaving). Else the reader's result: bytes (`b""` for nothing), or its {Closed},
   which becomes `closed`.

`show(grid, *, cursor=None) -> None | Closed` (the README's `term.show(frame.buffer)`):
`writer.write(display.show(grid, cursor=cursor))` (an idle frame is `b""`: nothing is
written); on a {Closed}, `display.invalidate()`, and the {Closed} is returned (and kept).
`write(data) -> None | Closed`: raw bytes through the one writer (inline output; the
app's responsibility); the writer's result.
`osc(o) -> None | Closed`: an [Osc] on the app's call: the first `Osc` of its kind since
`open` (or since the last `suspend`) is written as `o.prepare + o.data`, later ones as
`o.data`, one write each; the kind's `undo` is remembered (in order of first use).

`suspend() -> None | Closed` (Ctrl-Z: called by `read` on `SIGTSTP`, or by the app on
its own binding in raw mode): when opened and not closed, in order: one write of the
remembered Osc undos (last kind first) followed by `unset`'s bytes; `leave` (termios);
with signals installed, `SIGTSTP` set to `SIG_DFL`; `stop()`; then, once continued: our
`SIGTSTP` handler back, `enter` again (saving the state found now), `set(writer, plan)`
again, the Osc bookkeeping cleared (the app re-sends a title if it wants one),
`display.invalidate()` (the next `show` is a full repaint), the size measured. The
writer's {Closed}, if one stopped it; else `None`. A no-op (`None`) when not opened.

`close() -> None`: when opened: one write of the remembered Osc undos (last kind first)
followed by `unset(writer, plan)`'s bytes; `leave` (termios restored, `TCSADRAIN`);
`uninstall` ([Signals]: the previous handlers back); `opened` false. Each step runs
even when an earlier one met a {Closed}; nothing raises. The fds are not closed (the app
owns them). Idempotent; a no-op before `open`.

Re-exported for consumers: `Modes`, `Pair` (modes); `Reader` (reader); `Writer`
(writer); `Signals`, `Event`, `size_of` (signals); `Osc`, `title`, `clipboard`,
`cursor`, `bell` (osc); `probe`, `env_caps`, `PROBE` (probe); `Caps` (Core's);
`Closed` (cure's).

Inputs: as above; `grid` a Core {Grid}; `cursor` `None` or `(x, y)`; `data` {Bytes};
  `o` an {Osc}.
Outputs: `open` a {Caps}; `read` {Bytes} or a {Closed}; `show` / `write` / `osc` /
  `suspend` `None` or a {Closed}; `close` `None`.
Errors: `Term(...)`: `TypeError` when `fd_in` is neither `None` nor an `int`, `out` is
  neither an `int` nor a `Writer`, `env` is neither `None` nor a `Mapping`, `size` is
  neither `None` nor a 2-tuple of ints, `tick` / `timeout` is not a real number,
  `signals` is not a `bool`, `tty` is neither `None` nor a `bool` (a `bool` is refused
  wherever an `int` is meant), or `now` / `stop` is not callable (`stop` may be
  `None`); `ValueError` when an fd is negative, a size value < 1, or `tick` /
  `timeout` <= 0. `open`: `TypeError` when `modes` is neither `None` nor a `Modes`;
  `RuntimeError` when called a second time (a `Term` opens once). `read`, `show`,
  `write`, `osc`: `RuntimeError` before `open` or after `close`; `show` raises what
  `Display.show` raises for a bad `grid` / `cursor` (`TypeError` / `ValueError`),
  with nothing written. No `OSError` or `termios.error` escapes any method: an fd
  failure is a returned {Closed}.
Effects: through its parts only: termios ([Modes]), signal handlers and the self-pipe
  ([Signals], only with `signals=True`), `select.poll` and `os.read` ([Reader]),
  `os.write` ([Writer], the only writer), `os.get_terminal_size` ([Signals]'
  `size_of`), `stop()`.

Invariant: single_writer and paired hold for the handle: see [Writer] and [Modes].

Usage:
    import os, time
    from cure.closed import Closed
    from cure.edge.term import Term, Modes
    from cure.core.buffer.grid import Grid, put
    with Term(0, 1, env=os.environ, signals=True) as term:
        caps = term.open(Modes(mouse="drag"))
        while True:
            data = term.read(timeout=0.5)            # or timers.due(time.monotonic())
            if isinstance(data, Closed):
                break
            w, h = term.size
            if isinstance(term.show(put(Grid(w, h), 0, 0, "hello")), Closed):
                break
    # headless, as a test drives it:
    from cure.edge.term import Writer
    buf = bytearray()
    t = Term(None, Writer(sink=buf), env={"TERM": "xterm"}, size=(20, 5), tty=True)
    t.reader.type(b"\\x1b[?1u\\x1b[?62c")         # the replies, already "typed"
    t.open(Modes())                               # Caps(depth=16, keys="kitty", mouse=True)
    # buf == QUERIES + b"\\x1b[?1049h\\x1b[?25l\\x1b[?2004h\\x1b[>1u"
    t.close()                                     # buf ends with b"\\x1b[0m\\x1b[<u\\x1b[?2004l\\x1b[?25h\\x1b[?1049l"
"""

import math
import os
import signal as _signal
import time
from collections.abc import Mapping

from cure.closed import Closed
from cure.core.buffer.display import Display
from cure.core.caps import Caps

from . import modes as _modes
from .modes import Modes, Pair
from .osc import Osc, bell, clipboard, cursor, title
from .probe import PROBE, env_caps, probe
from .reader import Reader
from .signals import Event, Signals, baseline, install, on, size_of, uninstall
from .writer import Writer

TICK = 0.25  # seconds: the longest one read waits, so the size is polled at least this often


class Term:
    """{Term}: one terminal: its modes, probe, reader, one writer, signals and display."""

    def __init__(self, fd_in: "int | None" = 0, out: "int | Writer" = 1, *,
                 env: "Mapping | None" = None, size: "tuple[int, int] | None" = None,
                 tick: float = TICK, timeout: float = PROBE, signals: bool = False,
                 tty: "bool | None" = None, now=time.monotonic, stop=None) -> None:
        if not isinstance(out, Writer) and (isinstance(out, bool) or not isinstance(out, int)):
            raise TypeError(f"out must be an int or a Writer, got {type(out).__name__}")
        if env is not None and not isinstance(env, Mapping):
            raise TypeError(f"env must be None or a Mapping, got {type(env).__name__}")
        _check_seconds(tick, "tick")
        _check_seconds(timeout, "timeout")
        for name, value in (("signals", signals), ("tty", tty)):
            if not isinstance(value, bool) and not (name == "tty" and value is None):
                raise TypeError(f"{name} must be a bool, got {type(value).__name__}")
        if not callable(now):
            raise TypeError(f"now must be callable, got {type(now).__name__}")
        if stop is not None and not callable(stop):
            raise TypeError(f"stop must be None or callable, got {type(stop).__name__}")
        self._reader = Reader(fd_in)
        self._writer = out if isinstance(out, Writer) else Writer(out)
        self._signals = Signals(size=size)
        self._fd_in = fd_in
        self._env = env
        self._fixed = size
        self._size = size
        self._tick = tick
        self._timeout = timeout
        self._want_signals = signals
        self._tty = tty
        self._now = now
        self._stop = stop if stop is not None else _stop_process
        self._modes = None
        self._caps = None
        self._display = None
        self._plan = ()
        self._saved = None
        self._osc_undo = {}
        self._events = ()
        self._closed = None
        self._tty_now = False
        self._started = False
        self._opened = False
        self._own_resume = False

    @property
    def caps(self) -> "Caps | None":
        """The {Caps} `open` returned, or None before."""
        return self._caps

    @property
    def size(self) -> "tuple[int, int]":
        """`(w, h)` as last measured (or the fixed size)."""
        return self._size

    @property
    def reader(self) -> Reader:
        """The [Reader] over `fd_in`."""
        return self._reader

    @property
    def writer(self) -> Writer:
        """The one [Writer]."""
        return self._writer

    @property
    def display(self) -> "Display | None":
        """The Core Display built by `open`, or None before."""
        return self._display

    @property
    def plan(self) -> "tuple[Pair, ...]":
        """The mode pairs `open` set, `()` before."""
        return self._plan

    @property
    def signals(self) -> Signals:
        """The [Signals] (installed only with `signals=True`)."""
        return self._signals

    @property
    def fds(self) -> "tuple[int, ...]":
        """The fds to wait on: `fd_in`, then the self-pipe while installed."""
        return tuple(fd for fd in (self._fd_in, self._signals.fd) if fd is not None)

    @property
    def events(self) -> "tuple[Event, ...]":
        """The events the latest `read` handled."""
        return self._events

    @property
    def closed(self) -> "Closed | None":
        """The sticky Closed, or None."""
        return self._closed

    @property
    def opened(self) -> bool:
        """Between a successful `open` and `close`."""
        return self._opened

    def open(self, modes: "Modes | None" = None) -> Caps:
        """Set the modes, probe the caps; the caps (see the module)."""
        if modes is None:
            modes = Modes()
        if not isinstance(modes, Modes):
            raise TypeError(f"modes must be None or a Modes, got {type(modes).__name__}")
        if self._started:
            raise RuntimeError("a Term opens once")
        self._started = True
        self._modes = modes
        try:
            self._caps = self._set_up(modes)
        except BaseException:
            self._undo()
            raise
        self._opened = True
        return self._caps

    def read(self, timeout: "float | None" = None) -> "bytes | Closed":
        """Input within `min(timeout, tick)`, signals handled; or the Closed (see the module)."""
        self._require_open()
        wait = self._wait(timeout)
        if self._closed is not None:
            return self._reader.read(0) if self._reader.pending else self._closed
        wake = () if self._signals.fd is None else (self._signals.fd,)
        data = self._reader.read(wait, wake=wake)
        self._events = on(self._signals, self._measure())
        for event in self._events:
            self._handle(event)
        self._own_resume = False
        if self._closed is not None:
            return self._closed
        if isinstance(data, Closed):
            self._closed = data
        return data

    def show(self, grid, *, cursor: "tuple[int, int] | None" = None) -> "Closed | None":
        """Write the frame's bytes (Display: only the change) through the one writer."""
        self._require_open()
        result = self._send(self._display.show(grid, cursor=cursor))
        if result is not None:
            self._display.invalidate()
        return result

    def write(self, data: "bytes | bytearray | memoryview") -> "Closed | None":
        """Raw bytes through the one writer."""
        self._require_open()
        return self._send(data)

    def osc(self, o: Osc) -> "Closed | None":
        """An Osc on the app's call; its kind's undo remembered for close (see the module)."""
        self._require_open()
        if not isinstance(o, Osc):
            raise TypeError(f"expected an Osc, got {type(o).__name__}")
        if o.kind in self._osc_undo:
            return self._send(o.data)
        self._osc_undo[o.kind] = o.undo
        return self._send(o.prepare + o.data)

    def suspend(self) -> "Closed | None":
        """Undo everything, stop until continued, set everything again (see the module)."""
        if not self._opened or self._closed is not None:
            return None
        gone = self._send(self._undo_bytes())
        _modes.leave(self._saved)
        self._saved = None
        self._stopped()
        if self._tty_now:
            self._saved = _modes.enter(self._fd_in, self._modes.input)
        gone = self._send_result(_modes.set(self._writer, self._plan)) or gone
        self._osc_undo = {}
        self._display.invalidate()
        self._size = self._measure()
        self._own_resume = True
        return gone

    def close(self) -> None:
        """Undo every mode set, restore termios and the signal handlers. Idempotent."""
        if not self._opened:
            return None
        self._undo()
        self._opened = False
        return None

    def __enter__(self) -> "Term":
        return self

    def __exit__(self, kind, value, traceback) -> bool:
        self.close()
        return False

    # -- open, in the contract's order

    def _set_up(self, modes: Modes) -> Caps:
        env = os.environ if self._env is None else self._env
        tty = self._is_tty()
        self._tty_now = tty
        if self._want_signals:
            install(self._signals)
        if tty:
            self._saved = _modes.enter(self._fd_in, modes.input)
        if tty and modes.probe:
            caps = probe(env, reader=self._reader, writer=self._writer, tty=True,
                         timeout=self._timeout, now=self._now)
        else:
            caps = env_caps(env, tty=tty)
        if tty:
            self._plan = _modes.plan(modes, caps)
            _modes.set(self._writer, self._plan)
        self._display = Display(caps)
        self._size = self._measure()
        baseline(self._signals, self._size)
        self._closed = self._writer.closed or self._reader.closed
        return caps

    def _is_tty(self) -> bool:
        if self._tty is not None:
            return self._tty
        out = self._writer.fd
        return out is not None and os.isatty(out) and (self._fd_in is None or os.isatty(self._fd_in))

    # -- read's events

    def _handle(self, event: Event) -> None:
        if event.kind == "resize":
            self._size = event.size or self._size
            self._display.invalidate()
        elif event.kind == "suspend":
            self.suspend()
        elif event.kind == "resume" and not self._own_resume:
            again = _modes.enter(self._fd_in, self._modes.input) if self._tty_now else None
            self._saved = self._saved or again
            self._display.invalidate()
        elif event.kind in ("terminate", "hangup"):
            self._closed = Closed(event.kind)

    # -- undo, shared by close, suspend and a failed open

    def _undo(self) -> None:
        self._send(self._undo_bytes())
        _modes.leave(self._saved)
        self._saved = None
        uninstall(self._signals)

    def _undo_bytes(self) -> bytes:
        undos = b"".join(reversed(list(self._osc_undo.values())))
        return undos + b"".join(p.off for p in reversed(self._plan))

    def _stopped(self) -> None:
        ours = None
        if self._signals.installed:
            ours = _signal.signal(_signal.SIGTSTP, _signal.SIG_DFL)
        try:
            self._stop()
        finally:
            if ours is not None:
                _signal.signal(_signal.SIGTSTP, ours)

    # -- small helpers

    def _send(self, data: "bytes | bytearray | memoryview") -> "Closed | None":
        return self._send_result(self._writer.write(data))

    def _send_result(self, result: "Closed | None") -> "Closed | None":
        if isinstance(result, Closed) and self._closed is None:
            self._closed = result
        return result

    def _measure(self) -> "tuple[int, int]":
        if self._fixed is not None:
            return self._fixed
        env = os.environ if self._env is None else self._env
        return size_of((self._writer.fd, self._fd_in), env)

    def _wait(self, timeout: "float | None") -> float:
        if timeout is None:
            return self._tick
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise TypeError(f"timeout must be None or a real number, got {type(timeout).__name__}")
        if math.isnan(timeout):
            raise ValueError("timeout must not be NaN")
        return max(0, min(timeout, self._tick))

    def _require_open(self) -> None:
        if not self._opened:
            raise RuntimeError("the Term is not open")


def open(term: Term, modes: "Modes | None" = None) -> Caps:  # noqa: A001 (the flow's op name)
    """`term.open(modes)`: the tty opened at `modes`; its {Caps}."""
    return term.open(modes)


def show(term: Term, grid, *, cursor: "tuple[int, int] | None" = None) -> "Closed | None":
    """`term.show(grid, cursor=cursor)`: the frame written through the term's own Display; None or its {Closed}."""
    return term.show(grid, cursor=cursor)


def _stop_process() -> None:
    os.kill(os.getpid(), _signal.SIGTSTP)


def _check_seconds(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a real number, got {type(value).__name__}")
    if not value > 0:
        raise ValueError(f"{name} must be > 0, got {value}")
