"""[Clock]: timers, playback, tween, wait: the app's loop asks them.

Kind: system (the expansion of [Clock] in Edge). Time and waiting as tools: `now` comes
from the app, there is no loop here. [Timers] (a deadline heap), [Playback] (a frame
player) and [Tween] (a value eased from start to end) are pure: every time is an
argument. [Wait] is the one part that blocks: it waits on fds (the tty, a self-pipe,
ptys, sockets) for at most the timeout the pure parts give (`@timeout(due)`), and
returns the shared {Closed} when a waited-on fd went away. Depends only on cure's top
level (`cure.closed`), not on Term: a Term's own `read` waits on its own fds (see
[Term]); an app with more fds waits here on `term.fds` plus its others, then calls
`term.read(timeout=0)`.

The boundary (the op other parts call), re-exported from [Wait]:
- `select(fds, timeout=None, *, write=()) -> Ready | Closed` ([Embed] -> [Wait] :
  select({Fds}) => {Ready}): wait until an fd is ready or the timeout passes.

Re-exported for consumers: `Ready` (wait); `Timers`, `due` (timers); `Playback`,
`frame_at`, `SPEEDS` (playback); `Tween`, `EASES`, `value`, `done`, and its `due` as
`tween_due` (tween; `due` here stays Timers'); `Closed` (cure's).

Effects: none (importing it imports its children, nothing else).

Usage:
    import time
    from cure.edge.clock import Timers, Playback, select, Ready
    timers = Timers()
    timers.add("tick", time.monotonic() + 0.5, every=0.5)
    ready = select([0], timers.due(time.monotonic()))   # Ready(read=(0,)) or Ready()
    fired = timers.expired(time.monotonic())             # ("tick",) once it is due
"""

from cure.closed import Closed

from .playback import SPEEDS, Playback, frame_at
from .timers import Timers, due
from .tween import EASES, Tween, done, value
from .tween import due as tween_due
from .wait import Ready, select
