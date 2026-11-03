"""<Detached>: a client dropped: its session lives on.

Kind: event (a frozen dataclass value). [Server]'s failure route (`[Server] !>
<Detached>`): when an attached client leaves, for any reason, the server's `step`
RETURNS one `Detached` for it, among its other events; it is never raised. The
session, and all of the app's state, are untouched: the server keeps serving the
session, other clients stay attached, and the same person can attach again (a new
client id). What the app does with it is its own choice (usually: forget that
client's per-client view state).

Exactly one `Detached` is returned per attached client, at the first `step` after it
left (or by `Server.detach`, which returns it directly instead); a client that never
finished its handshake was never attached and has none.

Data:
- `Detached(client, session, reason, detail="", closed=None)`:
  - `client`: `int` >= 1, the client's id;
  - `session`: `str`, the session it was attached to;
  - `reason`: one of `REASONS`:
    - `"bye"`: the client said BYE (a clean detach on its side; `detail` its reason);
    - `"dropped"`: the link went away (end of file, `EPIPE`, `ECONNRESET`, ...):
      `closed` is that Term {Closed};
    - `"malformed"`: the client broke the [Protocol] (`detail` the `Malformed`'s
      reason, e.g. `"kind"`, `"order"`); the server sent `Bye("malformed")` best-effort
      and closed the link;
    - `"detached"`: the server's app detached it (`Server.detach`; `detail` the reason
      sent in the BYE);
  - `detail`: `str` (`""` when there is nothing to add);
  - `closed`: a {Closed} for `"dropped"`, else `None`.
  Equality and hashing field by field.

Inputs: the fields above.
Outputs: a {Detached}.
Errors: `TypeError` when `client` is not an `int` (a `bool` refused), `session` /
  `reason` / `detail` is not a `str`, or `closed` is neither `None` nor a `Closed`;
  `ValueError` when `client` < 1 or `reason` is not in `REASONS`. Assigning a field
  raises `dataclasses.FrozenInstanceError`.
Effects: none.

Usage:
    from cure.edge.term import Closed
    from cure.edge.remote.detached import Detached
    Detached(3, "main", "bye", "detach")              # the client detached itself
    Detached(4, "main", "dropped", closed=Closed("eof", 7))   # its ssh link died
    Detached(0, "main", "bye")                        # ValueError: ids start at 1
"""

from dataclasses import dataclass

from cure.edge.term import Closed

REASONS = ("bye", "dropped", "malformed", "detached")


@dataclass(frozen=True)
class Detached:
    """<Detached>: an attached client left; its session lives on (returned, never raised)."""

    client: int
    session: str
    reason: str
    detail: str = ""
    closed: "Closed | None" = None

    def __post_init__(self) -> None:
        if not isinstance(self.client, int) or isinstance(self.client, bool):
            raise TypeError(f"client must be an int, got {type(self.client).__name__}")
        for name in ("session", "reason", "detail"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a str, got {type(value).__name__}")
        if self.closed is not None and not isinstance(self.closed, Closed):
            raise TypeError(f"closed must be None or a Closed, got {type(self.closed).__name__}")
        if self.client < 1:
            raise ValueError(f"client must be >= 1, got {self.client}")
        if self.reason not in REASONS:
            raise ValueError(f"reason must be one of {REASONS}, got {self.reason!r}")
