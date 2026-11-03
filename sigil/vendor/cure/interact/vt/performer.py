"""[Performer]: what a consumer implements: Input's decoder, a Screen.

Kind: service (the action values a [Parser] gives out, the protocol a consumer
implements to receive them, and the one function that hands them over); pure.

The parser and its consumers stay apart (as vte's `Perform` and pyte's Stream /
Screen): [Parser] turns bytes into the action values defined here and returns them;
it never calls a consumer. A consumer either reads the returned tuples itself (Input's
decoder, I1) or implements `Performer` and is handed them by `dispatch` (V2's Screen,
whose `apply` is the flow `[Screen] -> [Performer] : apply({Actions}) => {Grid}`).

The actions ({Actions} is a tuple of them). Every one is a frozen dataclass (equal by
value, hashable when its fields are) with a class attribute `kind`, the name of the
`Performer` method that receives it. Constructors do not validate their fields: they
are plain data, and the values below are what a [Parser] gives them.

- `Print(text)`, kind "print": text to show. `text`: a non-empty `str` holding no
  C0 control (U+0000..U+001F) and no DEL (U+007F); it may hold U+FFFD (an invalid
  byte sequence, see [Parser]) and any other code point, U+0080..U+009F included.
- `Execute(code)`, kind "execute": a control on its own. `code`: an `int`, one of
  0x00..0x1F or 0x7F. 0x1B (ESC) is given out only by an input-direction parser, for
  an Esc that stood alone (see [Parser]).
- `Csi(final, params=(), private="", intermediates="")`, kind "csi": a control
  sequence, `ESC [` (or `CSI`) private? params intermediates final. `final`: one
  character U+0040..U+007E. `params`: a tuple of parameters, each a non-empty tuple
  of its sub-parameter values (`int`, or `None` for an empty one), see "Params".
  `private`: "" or one of "<", "=", ">", "?" (the marker right after `[`).
  `intermediates`: "" or one or two characters U+0020..U+002F, in order.
- `Esc(final, intermediates="")`, kind "esc": an escape sequence, `ESC`
  intermediates final. `final`: one character (U+0030..U+007E from an output-direction
  parser; an input-direction parser also gives any other character, see [Parser]).
  `intermediates`: "" or one or two characters U+0020..U+002F.
- `Osc(data, bel=False)`, kind "osc": an operating system command, `ESC ]` data
  terminator. `data`: the `bytes` between `]` and the terminator, as they came (no
  decoding; `data.split(b";")` gives the usual fields, e.g. `b"0;title"`).
  `bel`: True when BEL (0x07) ended it, False when ESC did (ST, `ESC \\`), so a
  consumer may answer a query with the same terminator.
- `Hook(final, params=(), private="", intermediates="")`, kind "hook": a device
  control string begins, `ESC P` private? params intermediates final; the fields as
  in `Csi`. Its data follows as `Put`s and it ends with one `Unhook`.
- `Put(data)`, kind "put": `bytes` of the current device control string (non-empty).
- `Unhook()`, kind "unhook": the current device control string ended.
- `Ss3(final, params=())`, kind "ss3" (input direction only): `ESC O` params final,
  the keys a terminal sends as SS3 (`ESC O A` up in application cursor mode, `ESC O P`
  F1). `final`: one character U+0040..U+007E; `params` as in `Csi`.
- `LegacyMouse(cb, cx, cy)`, kind "legacy_mouse" (input direction only): an X10-encoded
  mouse report, `ESC [ M` and three bytes. `cb`, `cx`, `cy`: those three bytes as
  `int`s 0..255, exactly as they came (each still carries its +32 offset).
- `Pasted(text)`, kind "pasted" (input direction only): the whole of a bracketed paste,
  the bytes between `ESC [ 200 ~` and `ESC [ 201 ~` decoded as UTF-8
  (`bytes.decode("utf-8", "replace")`); every character kept, controls and ESC
  included. Never parsed as controls.

`Action` is the union of these classes; `ACTIONS` is the tuple of them, in the order
above.

`Csi.param(index, default=0) -> int`: the first sub-parameter value of the parameter
at `index` (0-based), or `default` when there is no such parameter or that value is
`None`. `Csi("H", ((None,), (5,))).param(0, 1) == 1`, `.param(1, 1) == 5`,
`.param(2, 1) == 1`; `Csi("m", ((4, 3),)).param(0) == 4`. `TypeError` when `index`
or `default` is not an `int`; a negative `index` gives `default`.

The protocol: `Performer` is a base class with one method per action kind (`print`,
`execute`, `csi`, `esc`, `osc`, `hook`, `put`, `unhook`, `ss3`, `legacy_mouse`,
`pasted`), each taking the action value (`performer.csi(Csi(...))`), doing nothing
and returning `None`. A consumer subclasses it and overrides the methods it needs; any
object with the methods it is sent may be used without subclassing.

- `dispatch(actions, performer) -> None`: for each action of the iterable `actions`,
  in order, calls `getattr(performer, action.kind)(action)`. What a method returns is
  ignored; what it raises propagates (the actions after it are not sent). An object
  lacking the method an action needs raises `AttributeError` when that action is
  reached. `TypeError` (before any call is made) when an item is not an instance of
  one of `ACTIONS`.
- `coalesce(actions) -> tuple[Action, ...]`: the actions in order, with every run of
  adjacent `Print`s merged into one `Print` (texts joined) and every run of adjacent
  `Put`s into one `Put` (data joined); a `Print("")` or `Put(b"")` is dropped. Nothing
  else is merged, moved or dropped. `coalesce(coalesce(a)) == coalesce(a)`.
  `TypeError` when an item is not an instance of one of `ACTIONS`.

Inputs: actions; any object as a performer. Outputs: `None`; a tuple of actions.
Errors: as stated per function. Effects: none of its own (`dispatch` runs the
performer's methods, whose effects are the performer's).

Usage:
    from cure.interact.vt.performer import Performer, Print, Csi, Put, dispatch, coalesce
    class Log(Performer):
        def __init__(self):
            self.seen = []
        def print(self, action):
            self.seen.append(action.text)
    log = Log()
    dispatch((Print("hi"), Csi("m", ((1,),))), log)   # log.seen == ["hi"]; csi: the no-op
    coalesce((Print("a"), Print("b"), Put(b"x"), Put(b"y"), Print("")))
    # (Print("ab"), Put(b"xy"))
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class Print:
    """Text to show (no C0, no DEL)."""

    kind: ClassVar[str] = "print"
    text: str


@dataclass(frozen=True)
class Execute:
    """A control on its own: 0x00..0x1F or 0x7F."""

    kind: ClassVar[str] = "execute"
    code: int


@dataclass(frozen=True)
class Csi:
    """A control sequence: `ESC [` private params intermediates final."""

    kind: ClassVar[str] = "csi"
    final: str
    params: "tuple[tuple[int | None, ...], ...]" = ()
    private: str = ""
    intermediates: str = ""

    def param(self, index: int, default: int = 0) -> int:
        """The first sub-parameter of parameter `index`, or `default` (see the module)."""
        if not isinstance(index, int) or not isinstance(default, int):
            raise TypeError("index and default must be int")
        if index < 0 or index >= len(self.params):
            return default
        value = self.params[index][0]
        return default if value is None else value


@dataclass(frozen=True)
class Esc:
    """An escape sequence: `ESC` intermediates final."""

    kind: ClassVar[str] = "esc"
    final: str
    intermediates: str = ""


@dataclass(frozen=True)
class Osc:
    """An operating system command: its raw data and whether BEL ended it."""

    kind: ClassVar[str] = "osc"
    data: bytes
    bel: bool = False


@dataclass(frozen=True)
class Hook:
    """A device control string begins: `ESC P` private params intermediates final."""

    kind: ClassVar[str] = "hook"
    final: str
    params: "tuple[tuple[int | None, ...], ...]" = ()
    private: str = ""
    intermediates: str = ""


@dataclass(frozen=True)
class Put:
    """Bytes of the current device control string."""

    kind: ClassVar[str] = "put"
    data: bytes


@dataclass(frozen=True)
class Unhook:
    """The current device control string ended."""

    kind: ClassVar[str] = "unhook"


@dataclass(frozen=True)
class Ss3:
    """An SS3 key (input direction): `ESC O` params final."""

    kind: ClassVar[str] = "ss3"
    final: str
    params: "tuple[tuple[int | None, ...], ...]" = ()


@dataclass(frozen=True)
class LegacyMouse:
    """An X10-encoded mouse report (input direction): the three raw bytes after `ESC [ M`."""

    kind: ClassVar[str] = "legacy_mouse"
    cb: int
    cx: int
    cy: int


@dataclass(frozen=True)
class Pasted:
    """A whole bracketed paste (input direction), decoded as UTF-8, never parsed."""

    kind: ClassVar[str] = "pasted"
    text: str


Action = Print | Execute | Csi | Esc | Osc | Hook | Put | Unhook | Ss3 | LegacyMouse | Pasted

ACTIONS = (Print, Execute, Csi, Esc, Osc, Hook, Put, Unhook, Ss3, LegacyMouse, Pasted)


class Performer:
    """The consumer protocol: one method per action kind, each a no-op returning None."""

    def print(self, action: Print) -> None:
        return None

    def execute(self, action: Execute) -> None:
        return None

    def csi(self, action: Csi) -> None:
        return None

    def esc(self, action: Esc) -> None:
        return None

    def osc(self, action: Osc) -> None:
        return None

    def hook(self, action: Hook) -> None:
        return None

    def put(self, action: Put) -> None:
        return None

    def unhook(self, action: Unhook) -> None:
        return None

    def ss3(self, action: Ss3) -> None:
        return None

    def legacy_mouse(self, action: LegacyMouse) -> None:
        return None

    def pasted(self, action: Pasted) -> None:
        return None


def dispatch(actions: "Iterable[Action]", performer: object) -> None:
    """Send each action, in order, to the performer method its `kind` names (see the module)."""
    actions = _checked(actions)
    for action in actions:
        getattr(performer, action.kind)(action)


def coalesce(actions: "Iterable[Action]") -> "tuple[Action, ...]":
    """Merge adjacent Prints and adjacent Puts; drop empty ones (see the module)."""
    out: list = []
    run: list = []  # the texts (or data) of the Print (or Put) run being merged
    run_type = None
    for action in _checked(actions):
        kind = type(action)
        if kind is Print or kind is Put:
            value = action.text if kind is Print else action.data
            if not value:
                continue
            if kind is not run_type:
                _close(out, run, run_type)
                run_type = kind
            run.append(value)
            continue
        _close(out, run, run_type)
        run_type = None
        out.append(action)
    _close(out, run, run_type)
    return tuple(out)


def _checked(actions: "Iterable[Action]") -> list:
    """The actions as a list; `TypeError` when one is not an action value."""
    items = list(actions)
    for item in items:
        if not isinstance(item, ACTIONS):
            raise TypeError(f"not an action: {type(item).__name__}")
    return items


def _close(out: list, run: list, run_type: "type | None") -> None:
    """Append the merged run (if any) to `out` and empty it."""
    if not run:
        return
    if run_type is Print:
        out.append(Print("".join(run)))
    else:
        out.append(Put(b"".join(run)))
    run.clear()
