"""[Probe]: what the terminal can do, as a {Caps}: the env (COLORTERM, TERM, NO_COLOR,
FORCE_COLOR, isatty) and one batch of queries ending in DA1; no answer: what the env says.

Kind: service: three pure functions (the env fallback, the reply scanner, the merge)
and `probe`, the one that writes the queries and reads the replies with a deadline
(`@timeout(probe)`, `@fallback(env_caps)`). Depth always comes from the env; the
queries refine keys, mouse, sync and graphemes. Probe never fails: whatever goes wrong
(no tty, a dumb TERM, no answer in time, the terminal gone), the result is a valid
{Caps}, at worst `env_caps(env, tty=...)`.

The queries, written as one batch, in this order (`QUERIES`; `E` is ESC):
- `E [ ? u`: kitty keyboard flags (answer `E [ ? {flags} u`);
- `E [ ? 1006 $ p`, `E [ ? 2026 $ p`, `E [ ? 2027 $ p`: DECRQM for SGR mouse,
  synchronized output and grapheme clustering (answer DECRPM `E [ ? {mode} ; {ps} $ y`,
  `ps` 0 not recognized, 1 set, 2 reset, 3 permanently set, 4 permanently reset);
- `E [ c`: DA1, which every terminal answers (`E [ ? {p} ; ... c`): once it is in,
  every other answer that is coming has come.

`env_caps(env, *, tty) -> Caps` (the fallback; pure). `env` a mapping of names to
strings, `tty` whether both ends are terminals. With `TERM = env.get("TERM", "")`,
`COLORTERM = env.get("COLORTERM", "").lower()`, `dumb = TERM in ("", "dumb")`, and the
TERM depth `td`: 24 when COLORTERM is `"truecolor"` or `"24bit"` or TERM ends with
`"-direct"`; else 256 when TERM contains `"256color"`; else 16:
- `depth`, the first rule that applies:
  1. `NO_COLOR` is present and not `""`: 0;
  2. `FORCE_COLOR` is present: 0 when its value (stripped, lower-cased) is `"0"` or
     `"false"`; else the richer of `td` and the forced level (`"2"`: 256, `"3"`: 24,
     anything else, `""` and `"1"` included: 16), richer meaning later in
     0 < 16 < 256 < 24 (so FORCE_COLOR colours a pipe or a dumb TERM too);
  3. not `tty`, or `dumb`: 0;
  4. `td`.
- `keys`: `"legacy"` (the env cannot tell; the kitty answer upgrades it);
- `mouse`: `tty and not dumb and TERM != "linux"`;
- `graphemes`: `False`; `sync`: `False` (only an answer turns them on).

`scan(data) -> (Answers, rest)` (pure): every complete answer anywhere in `data`, and
`rest`, the bytes of `data` that are not part of an answer, in order (keys typed
during the probe, or an incomplete answer). Answers recognized, exactly: `E [ ? {d} u`
(kitty), `E [ ? {d} ; {d} $ y` (DECRPM), `E [ ? {d}(;{d})* c` (DA1), `{d}` one or more
ASCII digits. Anything else, a lone or incomplete `E [ ?` included, is `rest`.
Scanning is stateless: the caller rescans everything read so far.

`caps_of(base, answers) -> Caps` (pure): `base` with the answers applied, the last
answer for a mode winning:
- `keys`: `"kitty"` when `answers.kitty` is not `None`, else `base.keys`;
- `mouse`: the answer for 1006: `ps` 1, 2 or 3 -> `True`, 0 or 4 -> `False`, none ->
  `base.mouse`;
- `sync`: the answer for 2026, the same rule; none -> `base.sync`;
- `graphemes`: the answer for 2027: `ps` 1 or 3 -> `True` (the terminal clusters now;
  Modes never turns 2027 on), 0, 2 or 4 -> `False`, none -> `base.graphemes`;
- `depth`: `base.depth`, always.

`probe(env, *, reader, writer, tty=True, timeout=PROBE, now=time.monotonic) -> Caps`
([Probe] -> (Terminal) : probe({Env}) => {Caps}):
1. `base = env_caps(env, tty=tty)`. When `tty` is false or TERM is dumb: return `base`,
   with no write and no read.
2. `writer.write(QUERIES)`; a {Closed} -> return `base` (nothing read).
3. `deadline = now() + timeout`; repeat: `left = deadline - now()`; stop when
   `left <= 0`; `got = reader.read(left)`; stop when `got` is a {Closed} or `b""`
   (nothing came in time); else append `got` to what was read, rescan it with `scan`,
   and stop once the DA1 answer is in.
4. `reader.type(rest)` when `rest` is not empty: the bytes that were not answers go
   back to the reader's inbox, so the app's next read gets them first and nothing
   typed during the probe is lost.
5. Return `caps_of(base, answers)` (answers found so far: a late or missing reply only
   leaves that field at the env's value). A reply arriving after the deadline reaches
   the app's input as bytes (Input's decoder sees an unknown CSI).
The probe runs inside raw or cbreak mode (the Term handle opens termios first), so the
replies are not echoed.

Data:
- `Answers(kitty=None, modes=(), da1=None)`: `kitty` the flags `int` or `None`;
  `modes` a tuple of `(mode, ps)` int pairs in arrival order; `da1` the tuple of DA1
  parameters or `None`. `done` (property): `da1 is not None`. Equality field by field.

Inputs: `env` a `Mapping[str, str]` ({Env}); `tty` a `bool`; `data` `bytes`; `base` a
  Core {Caps}; `reader` any object with `read(timeout) -> bytes | Closed` and
  `type(bytes)` (a [Reader]); `writer` any object with `write(bytes) -> None | Closed`
  (the [Writer]); `timeout` seconds > 0; `now` a callable returning monotonic seconds
  (the clock is an argument).
Outputs: a {Caps}; `scan`: `(Answers, bytes)`.
Errors: `TypeError` when `env` is not a `Mapping`, `tty` is not a `bool`, `data` is
  not `bytes`, `base` is not a {Caps}, `timeout` is not a real number (a `bool` is
  refused) or `now` is not callable; `ValueError` when `timeout` is not > 0. Nothing
  else: a missing answer falls back, a {Closed} falls back (the reader and writer keep
  it, so the app's next read or write returns it).
Effects: `env_caps`, `scan`, `caps_of` none. `probe`: one `writer.write(QUERIES)`, then
  `reader.read` calls until the deadline or DA1, and at most one `reader.type`.

Usage:
    from cure.core.caps import Caps
    from cure.edge.term.probe import env_caps, scan, caps_of, probe, QUERIES
    env_caps({"TERM": "xterm-256color"}, tty=True)       # Caps(depth=256, mouse=True)
    env_caps({"TERM": "xterm", "NO_COLOR": "1"}, tty=True).depth  # 0
    env_caps({"FORCE_COLOR": "3"}, tty=False).depth       # 24
    a, rest = scan(b"\\x1b[?1uq\\x1b[?2026;2$y\\x1b[?62;22c")
    a.kitty, a.modes, a.da1, rest                       # 1, ((2026, 2),), (62, 22), b"q"
    caps_of(Caps(depth=16), a)                          # Caps(depth=16, keys="kitty", sync=True)
"""

import math
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace

from cure.closed import Closed
from cure.core.caps import Caps

QUERIES = b"\x1b[?u\x1b[?1006$p\x1b[?2026$p\x1b[?2027$p\x1b[c"
PROBE = 0.2  # seconds: the probe's deadline (@timeout(probe))

_ANSWER = re.compile(
    rb"\x1b\[\?(?:(?P<kitty>\d+)u|(?P<mode>\d+);(?P<ps>\d+)\$y|(?P<da1>\d+(?:;\d+)*)c)"
)
_RICHNESS = (0, 16, 256, 24)
_FORCED = {"2": 256, "3": 24}
_ON = {"mouse": (1, 2, 3), "sync": (1, 2, 3), "graphemes": (1, 3)}
_FIELD_OF = {1006: "mouse", 2026: "sync", 2027: "graphemes"}


@dataclass(frozen=True)
class Answers:
    """The terminal's answers found by `scan` (see the module)."""

    kitty: "int | None" = None
    modes: "tuple[tuple[int, int], ...]" = ()
    da1: "tuple[int, ...] | None" = None

    @property
    def done(self) -> bool:
        """The DA1 answer is in: every answer that is coming has come."""
        return self.da1 is not None


def env_caps(env: Mapping, *, tty: bool) -> Caps:
    """The {Caps} the environment alone gives (the probe's fallback; see the module)."""
    _check_env(env)
    _check_tty(tty)
    term = env.get("TERM", "")
    dumb = term in ("", "dumb")
    mouse = tty and not dumb and term != "linux"
    return Caps(depth=_depth(env, term, tty, dumb), mouse=mouse)


def scan(data: bytes) -> "tuple[Answers, bytes]":
    """The complete answers in `data`, and the bytes that are not answers (see the module)."""
    if not isinstance(data, bytes):
        raise TypeError(f"data must be bytes, got {type(data).__name__}")
    kitty, modes, da1 = None, [], None
    rest = bytearray()
    at = 0
    for m in _ANSWER.finditer(data):
        rest += data[at:m.start()]
        at = m.end()
        if m["kitty"] is not None:
            kitty = int(m["kitty"])
        elif m["mode"] is not None:
            modes.append((int(m["mode"]), int(m["ps"])))
        else:
            da1 = tuple(int(p) for p in m["da1"].split(b";"))
    rest += data[at:]
    return Answers(kitty, tuple(modes), da1), bytes(rest)


def caps_of(base: Caps, answers: Answers) -> Caps:
    """`base` refined by the answers: keys, mouse, sync, graphemes (see the module)."""
    if not isinstance(base, Caps):
        raise TypeError(f"base must be a Caps, got {type(base).__name__}")
    if not isinstance(answers, Answers):
        raise TypeError(f"answers must be an Answers, got {type(answers).__name__}")
    changes = {}
    if answers.kitty is not None:
        changes["keys"] = "kitty"
    for mode, ps in answers.modes:
        field = _FIELD_OF.get(mode)
        if field is not None:
            changes[field] = ps in _ON[field]
    return replace(base, **changes)


def probe(env: Mapping, *, reader, writer, tty: bool = True, timeout: float = PROBE,
          now=time.monotonic) -> Caps:
    """Query the terminal once, read until DA1 or the deadline, fall back to the env."""
    _check_env(env)
    _check_tty(tty)
    _check_timeout(timeout)
    if not callable(now):
        raise TypeError(f"now must be callable, got {type(now).__name__}")
    base = env_caps(env, tty=tty)
    if not tty or env.get("TERM", "") in ("", "dumb"):
        return base
    if isinstance(writer.write(QUERIES), Closed):
        return base
    answers, rest = _collect(reader, now() + timeout, now)
    if rest:
        reader.type(rest)
    return caps_of(base, answers)


def _collect(reader, deadline: float, now) -> "tuple[Answers, bytes]":
    got = b""
    answers, rest = Answers(), b""
    while True:
        left = deadline - now()
        if left <= 0:
            break
        chunk = reader.read(left)
        if isinstance(chunk, Closed) or not chunk:
            break
        got += chunk
        answers, rest = scan(got)
        if answers.done:
            break
    return answers, rest


def _depth(env: Mapping, term: str, tty: bool, dumb: bool) -> int:
    if env.get("NO_COLOR", "") != "":
        return 0
    td = _term_depth(env, term)
    if "FORCE_COLOR" in env:
        value = env["FORCE_COLOR"].strip().lower()
        if value in ("0", "false"):
            return 0
        return max(td, _FORCED.get(value, 16), key=_RICHNESS.index)
    if not tty or dumb:
        return 0
    return td


def _term_depth(env: Mapping, term: str) -> int:
    colorterm = env.get("COLORTERM", "").lower()
    if colorterm in ("truecolor", "24bit") or term.endswith("-direct"):
        return 24
    if "256color" in term:
        return 256
    return 16


def _check_env(env: object) -> None:
    if not isinstance(env, Mapping):
        raise TypeError(f"env must be a Mapping, got {type(env).__name__}")


def _check_tty(tty: object) -> None:
    if not isinstance(tty, bool):
        raise TypeError(f"tty must be a bool, got {type(tty).__name__}")


def _check_timeout(timeout: object) -> None:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise TypeError(f"timeout must be a real number, got {type(timeout).__name__}")
    if not timeout > 0 or math.isnan(timeout):
        raise ValueError(f"timeout must be > 0, got {timeout}")
