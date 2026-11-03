"""{Ended}: how an attachment ended; the terminal is already given back.

Kind: data (a frozen dataclass value). [Attach]'s ending value: returned (never
raised) by `Attach`'s `open`, `step`, `send`, `detach` and `close`, by then with the
terminal given back (`restored`). Its own module, so the data item the spec draws is
where its name says; `cure.edge.remote.Ended` and `cure.edge.remote.attach.Ended` are
this one class.

Data:
- `Ended(reason, detail="", closed=None, fault=None)` (frozen): `reason` one of
  `ENDINGS`:
  - `"detach"`: the app called `detach()` (a clean detach: BYE sent);
  - `"bye"`: the server sent BYE (`detail` its reason: `"end"`, `"detached"`, ...);
  - `"dropped"`: the link went away (`closed` its {Closed});
  - `"malformed"`: the server broke the [Protocol] (`detail` the `Malformed`'s
    reason; a FRAME `apply` refused is `"order"`);
  - `"refused"`: `open` could not attach (`fault` the [Transport] {Fault}: `"absent"`,
    `"unsafe"`, `"version"`, `"refused"`, `"timeout"`, `"malformed"`, `"error"`);
  - `"terminal"`: the attaching terminal itself went away (`closed` Term's {Closed}:
    a hangup, a terminate signal, end of file);
  - `"closed"`: the app called `close()` (or `__exit__` ran), or an exception raised
    inside a method after its argument checks (`detail` the exception's class name).
  Equality and hashing field by field.

Inputs: the fields above.
Outputs: an {Ended}.
Errors: `TypeError` when `reason` / `detail` is not a `str`, `closed` is neither
  `None` nor a `Closed`, or `fault` is neither `None` nor a [Transport] `Fault`;
  `ValueError` when `reason` is not in `ENDINGS`. Assigning a field raises
  `dataclasses.FrozenInstanceError`.
Effects: none.

Usage:
    from cure.edge.remote.ended import Ended
    Ended("bye", "end")                               # the server ended the session
    Ended("nope")                                     # ValueError: not one of ENDINGS
"""

from dataclasses import dataclass

from cure.edge.term import Closed

from .transport import Fault

ENDINGS = ("detach", "bye", "dropped", "malformed", "refused", "terminal", "closed")


@dataclass(frozen=True)
class Ended:
    """{Ended}: how an attachment ended; the terminal is already given back."""

    reason: str
    detail: str = ""
    closed: "Closed | None" = None
    fault: "Fault | None" = None

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str):
            raise TypeError(f"reason must be a str, got {type(self.reason).__name__}")
        if not isinstance(self.detail, str):
            raise TypeError(f"detail must be a str, got {type(self.detail).__name__}")
        if self.closed is not None and not isinstance(self.closed, Closed):
            raise TypeError(f"closed must be None or a Closed, got {type(self.closed).__name__}")
        if self.fault is not None and not isinstance(self.fault, Fault):
            raise TypeError(f"fault must be None or a Fault, got {type(self.fault).__name__}")
        if self.reason not in ENDINGS:
            raise ValueError(f"reason must be one of {ENDINGS}, got {self.reason!r}")
