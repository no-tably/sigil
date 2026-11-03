"""{Agent}: the orchestrator's terminal: its screen and cursor.

Kind: data (a frozen dataclass, checked on construction). The screen is one construct
already has (the orchestrator agent's pty, run through Embed and Vt on construct's
side): Views never starts, reads or writes a process.

Data:
- `Agent(screen=None, cursor=None)`:
  - `screen`: `None` (no frame yet: OrchestratorTab shows a placeholder) or a Buffer
    {Grid}. Held, not copied.
  - `cursor`: `None` (hidden) or a pair `(x, y)`, a `tuple` of two ints `>= 0`;
    only with a `screen`.
- `Agent()` is the empty agent (the {Board}'s default).
- Equality is field by field (the screen by Grid's `==`); hashing leaves the screen
  out (`field(hash=False)`), so every Agent is hashable.

Errors (construction, in field order):
- `TypeError` when `screen` is neither `None` nor a `Grid`, or `cursor` is neither
  `None` nor a `tuple` of two ints (a `bool` refused).
- `ValueError` when a cursor value is negative, or `cursor` is given with
  `screen=None` (`"cursor needs a screen"`).
Effects: none.

Usage:
    from cure.core.buffer import Grid
    from cure.draw.views.board import Agent
    Agent(Grid(80, 24), (3, 0))
    Agent() == Agent(None, None)      # True
"""

from dataclasses import dataclass, field

from cure.core.buffer import Grid


@dataclass(frozen=True)
class Agent:
    """The orchestrator agent's terminal (see the module)."""

    screen: "Grid | None" = field(default=None, hash=False)
    cursor: "tuple[int, int] | None" = None

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        if self.screen is not None and not isinstance(self.screen, Grid):
            raise TypeError(f"screen must be None or a Grid, got {type(self.screen).__name__}")
        _cursor(self.screen, self.cursor)


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
