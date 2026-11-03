"""[Embed]: a program in a pane: its pty.

Kind: system (the expansion of [Embed] in Edge). The edge half of a pane: [Pty] forks
the command the app hands it on a new pty, reads the program's output into a Vt
`Screen` (Vt is the pure half), writes a person's input re-encoded for the modes the
program set, and resizes the pty; a program that cannot be started is a
[SpawnFailed], returned. No loop, no thread, no signal handler: the app waits on the
handle's fds (with Clock's [Wait], beside its Term's) and calls its non-blocking steps.
Depends on Clock (`select`, and `Closed` through it) and Vt (`Screen`, `apply`,
`encode`, `Modes`, `Reply`); it imports no Input: events reach it as arguments, read by
their class name and attributes, as Vt's [Encode] reads them.

The boundary (the op other parts call), defined in [Pty] and re-exported here:
- `spawn(argv, *, size=SIZE, env=None, cwd=None, timeout=SPAWN) -> Pty | SpawnFailed`
  ((Construct) -> [Embed] : spawn({Command}) => {Fd}): fork and exec exactly `argv`
  (with exactly `env`, in `cwd`) on a new pty of `size`; the `Pty` (its `fd` the
  {Fd}), or the {SpawnFailed} (exec failure in the child reported through a
  close-on-exec status pipe). It waits for that report with Clock's `select`
  ([Embed] -> [Wait] : select({Fds}) => {Ready}) for at most `timeout` seconds.

Re-exported for consumers: `spawn`, `Pty`, `output`, `forward`, `SIZE`, `SPAWN`,
`CLOSE`, `STEP`, `READ`, `MAX_PENDING`, `MAX_EVENTS`, `MAX_SIZE`, `EXIT_FAILED`,
`RESET` (pty); `SpawnFailed`, `STAGES` (spawnfailed); `Closed` (cure's, through Clock).

Effects: none on import (importing it imports its two modules, Clock and Vt, nothing
else); `spawn` and the handle's steps as [Pty] states them.

Usage:
    import sys
    from cure.edge.embed import spawn, SpawnFailed, Closed
    p = spawn([sys.executable, "-c", "print('hi')"], size=(20, 3), env={"TERM": "xterm"})
    isinstance(p, SpawnFailed)     # False: p is a Pty
    p.close()                      # 0 once reaped; no fd, no zombie left
    f = spawn(["/no/such/program"])
    f.message                      # "/no/such/program: exec: No such file or directory"
"""

from cure.edge.clock import Closed

from .pty import (
    CLOSE,
    EXIT_FAILED,
    MAX_EVENTS,
    MAX_PENDING,
    MAX_SIZE,
    READ,
    RESET,
    SIZE,
    SPAWN,
    STEP,
    Pty,
    forward,
    output,
    spawn,
)
from .spawnfailed import STAGES, SpawnFailed
