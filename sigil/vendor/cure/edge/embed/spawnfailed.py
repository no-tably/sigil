"""<SpawnFailed>: the command a pane was handed could not be started: returned to the
app, which shows it in the pane.

Kind: event (a frozen dataclass value). What [Pty]'s `spawn` RETURNS in place of a
`Pty` when the program could not be started (`[Pty] !> <SpawnFailed>`). It is a value,
NEVER raised: no cure unit raises `SpawnFailed`, and no `OSError` from opening the pty,
starting the process or exec escapes `spawn` (an edge failure is a named error returned to the app).
The app tests `isinstance(result, SpawnFailed)` and shows `result.message` in the pane
where the program would have been. A `SpawnFailed` is truthy (an ordinary object).

Where one comes from (the `stage` it carries), in the order `spawn` meets them:
- `"pty"`: `os.openpty()`, or setting the window size or non-blocking mode on it,
  failed in the parent (`errno` kept; e.g. `EMFILE`, `ENOSPC`, `EAGAIN`).
- `"fork"`: `os.posix_spawn` of the boot interpreter (or making the status pipe, or
  making or writing the payload's carrier, a memfd or a pipe) failed in the parent, or
  there is no `sys.executable` to boot (`errno` kept; e.g. `EAGAIN`, `ENOMEM`, `EMFILE`;
  `E2BIG` for a payload that does not fit the pipe carrier; `ENOENT` for no
  `sys.executable`).
- `"tty"`: in the new process, making the pty its controlling terminal and its stdin,
  stdout and stderr (`os.login_tty`) failed (`errno` kept).
- `"chdir"`: in the new process, `os.chdir(cwd)` failed (`ENOENT`, `ENOTDIR`, `EACCES`
  ...).
- `"exec"`: in the new process, `os.execvpe` failed: the program was not found on the
  `PATH` of the environment given, is not executable, or is not a valid executable
  (`ENOENT`, `EACCES`, `ENOEXEC`, `E2BIG` ...); or the boot interpreter never started
  (`errno` `None`).
- `"timeout"`: the new process neither exec'd nor reported a failure within `spawn`'s
  `timeout` (`@timeout(spawn)`); `spawn` killed and reaped it. `errno` is `None`.
A failure in the new process reaches the parent through the status pipe (see [Pty]'s
"Starting"): the boot writes `b"+"` when it starts, then `b"<stage>:<errno>"`, and
`_exit`s; the parent reads it and builds this value. In every case `spawn` has already
closed every fd it opened and reaped any process it started: a `SpawnFailed` leaves no
fd and no zombie behind.

Data:
- `SpawnFailed(argv, stage, errno=None)`:
  - `argv`: the command as `spawn` was handed it, a `tuple` of `str`, not empty (any
    sequence of `str` is taken as a tuple; a `str` itself is refused);
  - `stage`: `str`, one of `STAGES`;
  - `errno`: `int` (>= 0) the OS error number, or `None` (`"timeout"` always has
    `None`; the other stages have an `int` when `spawn` builds them).
  Equality and hashing are field by field.
- `message -> str` (property): the one line the app shows, exactly
  `f"{argv[0]}: {stage}: {reason}"`, `reason` being `os.strerror(errno)` when `errno`
  is not `None`, else `"no answer within the spawn timeout"` for `"timeout"` and
  `"failed"` for any other stage. Pure.

Inputs: the three fields.
Outputs: a `SpawnFailed`; `message` a `str`.
Errors: `TypeError` when `argv` is a `str` / `bytes`, not iterable, or holds a non-`str`;
  `stage` is not a `str`; `errno` is neither `None` nor an `int` (a `bool` is refused).
  `ValueError` when `argv` is empty, `stage` is not in `STAGES`, or `errno` is negative.
  Assigning a field raises `dataclasses.FrozenInstanceError`.
Effects: none.

Usage:
    import errno
    from cure.edge.embed.spawnfailed import SpawnFailed
    f = SpawnFailed(("nosuch", "-x"), "exec", errno.ENOENT)
    f.message                     # "nosuch: exec: No such file or directory"
    SpawnFailed(["sh"], "timeout").argv      # ("sh",)
    SpawnFailed(("sh",), "timeout").message  # "sh: timeout: no answer within the spawn timeout"
    SpawnFailed((), "exec")                  # ValueError: an empty command
    SpawnFailed(("sh",), "boom")             # ValueError: not a stage
"""

import os as _os
from dataclasses import dataclass

STAGES = ("pty", "fork", "tty", "chdir", "exec", "timeout")


@dataclass(frozen=True)
class SpawnFailed:
    """<SpawnFailed>: the program could not be started; returned (never raised). Checked on construction."""

    argv: "tuple[str, ...]"
    stage: str
    errno: "int | None" = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "argv", _check_argv(self.argv))
        if not isinstance(self.stage, str):
            raise TypeError(f"stage must be a str, got {type(self.stage).__name__}")
        if self.stage not in STAGES:
            raise ValueError(f"stage must be one of {STAGES}, got {self.stage!r}")
        code = self.errno
        if code is not None:
            if isinstance(code, bool) or not isinstance(code, int):
                raise TypeError(f"errno must be None or an int, got {type(code).__name__}")
            if code < 0:
                raise ValueError(f"errno must be >= 0, got {code}")

    @property
    def message(self) -> str:
        """`"{argv[0]}: {stage}: {reason}"`: the line the app shows in the pane (see the module)."""
        if self.errno is not None:
            reason = _os.strerror(self.errno)
        elif self.stage == "timeout":
            reason = "no answer within the spawn timeout"
        else:
            reason = "failed"
        return f"{self.argv[0]}: {self.stage}: {reason}"


def _check_argv(argv: object) -> "tuple[str, ...]":
    """`argv` as a non-empty tuple of str; TypeError / ValueError as the module states."""
    if isinstance(argv, (str, bytes, bytearray)):
        raise TypeError(f"argv must be a sequence of str, not a {type(argv).__name__}")
    try:
        items = tuple(argv)
    except TypeError:
        raise TypeError(f"argv must be a sequence of str, got {type(argv).__name__}") from None
    for item in items:
        if not isinstance(item, str):
            raise TypeError(f"argv must hold only str, got {type(item).__name__}")
    if not items:
        raise ValueError("argv must not be empty")
    return items
