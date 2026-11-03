"""{Builder}: one builder: its worktree, its env, its status and its terminal's screen.

Kind: data (a frozen dataclass, checked on construction). Plain data construct maps
its own model into; the screen is one construct already has (its builder's pty, run
through Embed and Vt on construct's side): Views never starts, reads or writes a
process.

What it is: id, task id, worktree path, env (name: value pairs), status, phase, its
progress through the phase (a step of a total, or unknown), and the terminal's screen
({Grid}) and cursor, or none before its first frame.

Data:
- `Builder(id, *, task=None, worktree="", env=(), status="starting", phase="",
  progress=None, screen=None, cursor=None)`:
  - `id`: a non-empty `str`, unique in its {Board}.
  - `task`: `None` (no task assigned) or a non-empty `str`, a {Task}'s id.
  - `worktree`: a `str`, the worktree's path as construct names it (`""`: none
    yet). Shown as given; never opened.
  - `env`: a `tuple` of `(name, value)` pairs, each a `tuple` of two `str`, the name
    non-empty; names unique; kept in the order given (the order BuilderTab lists
    them in).
  - `status`: one of `STATES`:
    - `"starting"`: the worktree and env are being made, no agent yet;
    - `"working"`: its agent is running a phase;
    - `"waiting"`: it waits on the person (a question or a witness);
    - `"passed"`: its work passed and landed;
    - `"failed"`: it gave up or was taken back (a failed try, escalated).
  - `phase`: a `str`, construct's name for the phase its agent is in (`"contract"`,
    `"proofs"`, `"implement"`, ...; free text, shown as given; `""`: none).
  - `progress`: `None` (unknown) or a pair `(step, total)`, a `tuple` of two ints,
    `0 <= step <= total` and `total > 0`: how far its agent has got through the
    phase, as construct counts it (BuilderTab and BuilderGrid draw it as a Gauge).
    Independent of `status` (a builder may hold one in any status).
  - `screen`: `None` (before its first frame) or a Buffer {Grid}, the terminal's
    screen. Held, not copied (a Grid is mutable: the app hands in the frame's grid).
  - `cursor`: `None` (hidden) or a pair `(x, y)`, a `tuple` of two ints `>= 0`, the
    program's cursor in screen cells; only with a `screen`.
- Equality is field by field (the screen by Grid's `==`, cell by cell; `progress`
  included). Hashing includes `progress` and leaves the screen out
  (`field(hash=False)`: a Grid is unhashable) and the cursor with it (a cursor needs
  a screen, so a builder hashes as it would before its first frame), so every
  Builder is hashable and equal builders hash equal.

Constants: `STATES = ("starting", "working", "waiting", "passed", "failed")`.

Errors (construction, in field order, the first failure raised):
- `TypeError` when `id`, `worktree`, `status` or `phase` is not a `str`; `task` is neither
  `None` nor a `str`; `env` is not a `tuple` of 2-tuples of `str` (`"env must be a
  tuple of (str, str) pairs, got list"`); `progress` is neither `None` nor a `tuple`
  of two ints, a `bool` refused (`"progress must be None or a (step, total) pair of
  int, got list"`, the type name of the value given: a pair of the wrong length or
  holding a non-int names its own type, `tuple`); `screen` is neither `None` nor
  a Buffer `Grid`; `cursor` is neither `None` nor a `tuple` of two ints (a `bool`
  refused).
- `ValueError` when `id` or `task` is `""`; an env name is `""` or repeated
  (`"env repeats 'HOME'"`); `status` is not in `STATES` (`"status must be one of
  starting, working, waiting, passed, failed, got 'x'"`); `progress` breaks `0 <=
  step <= total` or `total > 0` (`"progress needs 0 <= step <= total and total > 0,
  got (3, 2)"`, the pair's repr); a cursor value is negative; `cursor` is given
  with `screen=None` (`"cursor needs a screen"`).
Assigning a field raises `dataclasses.FrozenInstanceError`.
Effects: none.

Usage:
    from cure.core.buffer import Grid
    from cure.draw.views.board import Builder
    b = Builder("b1", task="X1", worktree="../wt/b1", env=(("PYTHON", "3.12"),),
                status="working", screen=Grid(80, 24), cursor=(0, 0))
    hash(b) == hash(Builder("b1", task="X1", worktree="../wt/b1",
                            env=(("PYTHON", "3.12"),), status="working"))   # True: the screen and cursor are left out
    Builder("b1", status="working", phase="proofs", progress=(3, 7)).progress   # (3, 7)
    Builder("b1", progress=(3, 2))      # ValueError: progress needs 0 <= step <= total and total > 0, got (3, 2)
    Builder("b1", progress=[1, 2])      # TypeError: progress must be None or a (step, total) pair of int, got list
    Builder("b1", cursor=(0, 0))        # ValueError: cursor needs a screen
"""

from dataclasses import KW_ONLY, dataclass, field

from cure.core.buffer import Grid

STATES = ("starting", "working", "waiting", "passed", "failed")
"""A builder's statuses, in order."""


@dataclass(frozen=True)
class Builder:
    """One builder and its terminal's screen (see the module)."""

    id: str
    _: KW_ONLY
    task: "str | None" = None
    worktree: str = ""
    env: "tuple[tuple[str, str], ...]" = ()
    status: str = "starting"
    phase: str = ""
    progress: "tuple[int, int] | None" = None
    screen: "Grid | None" = field(default=None, hash=False)
    cursor: "tuple[int, int] | None" = field(default=None, hash=False)  # out with the screen

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _text("id", self.id, empty=False)
        if self.task is not None:
            _text("task", self.task, empty=False, what="None or a str")
        _text("worktree", self.worktree)
        _env(self.env)
        if not isinstance(self.status, str):
            raise TypeError(f"status must be a str, got {type(self.status).__name__}")
        if self.status not in STATES:
            raise ValueError(f"status must be one of {', '.join(STATES)}, got {self.status!r}")
        _text("phase", self.phase)
        _progress(self.progress)
        if self.screen is not None and not isinstance(self.screen, Grid):
            raise TypeError(f"screen must be None or a Grid, got {type(self.screen).__name__}")
        _cursor(self.screen, self.cursor)


def _text(name: str, value: object, *, empty: bool = True, what: str = "a str") -> None:
    """Check `value` is a `str` (non-empty unless `empty`)."""
    if not isinstance(value, str):
        raise TypeError(f"{name} must be {what}, got {type(value).__name__}")
    if not empty and value == "":
        raise ValueError(f"{name} must not be ''")


def _env(env: object) -> None:
    """Check the env: a tuple of (str, str) pairs, names non-empty and unique."""
    def pair(p: object) -> bool:
        return isinstance(p, tuple) and len(p) == 2 and all(isinstance(s, str) for s in p)
    if not isinstance(env, tuple) or not all(pair(p) for p in env):
        got = env if not isinstance(env, tuple) else next(p for p in env if not pair(p))
        raise TypeError(f"env must be a tuple of (str, str) pairs, got {type(got).__name__}")
    seen = set()
    for name, _ in env:
        if name == "":
            raise ValueError("env names must not be ''")
        if name in seen:
            raise ValueError(f"env repeats {name!r}")
        seen.add(name)


def _progress(progress: object) -> None:
    """Check a progress: `None` or a pair of ints (no bool), `0 <= step <= total`, `total > 0`."""
    if progress is None:
        return
    if (not isinstance(progress, tuple) or len(progress) != 2
            or not all(isinstance(v, int) and not isinstance(v, bool) for v in progress)):
        raise TypeError("progress must be None or a (step, total) pair of int, "
                        f"got {type(progress).__name__}")
    step, total = progress
    if not (0 <= step <= total and total > 0):
        raise ValueError(f"progress needs 0 <= step <= total and total > 0, got {progress!r}")


def _cursor(screen: object, cursor: object) -> None:
    """Check a cursor: `None` or a pair of ints `>= 0` (no bool), only with a screen."""
    if cursor is None:
        return
    if (not isinstance(cursor, tuple) or len(cursor) != 2
            or not all(isinstance(v, int) and not isinstance(v, bool) for v in cursor)):
        raise TypeError(f"cursor must be None or a tuple of two ints, got {type(cursor).__name__}")
    if min(cursor) < 0:
        raise ValueError(f"cursor must not be negative, got {cursor!r}")
    if screen is None:
        raise ValueError("cursor needs a screen")
