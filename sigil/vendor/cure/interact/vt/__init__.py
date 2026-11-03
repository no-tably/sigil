"""[Vt]: the DEC parser, used both ways: our input, a pane's output.

Kind: system (the expansion of [Vt] in Interact); pure: no I/O, no process-wide state.
Depends on nothing in its own spec; it may import Core (inherited through Interact,
spec question 6): [Screen] imports Buffer, Text and Style (its cells are cure's own
cells, its pen a Style). It never imports Input (a sibling): Input's events reach
[Encode] as arguments, read by their attributes.

One table-driven state machine (Williams), parser and screen apart (as vte / pyte):
[Parser] turns bytes into action values, in the "output" direction (what a program
writes) or the "input" direction (what a terminal sends for a person); [Performer]
defines those actions, the protocol a consumer implements (Input's decoder, a Screen)
and `dispatch`; [Encode] goes the other way, writing keys, mouse, pastes and focus as a
target program's {Modes} want them. [Screen] performs an output-direction parser's
actions on two buffers of cure's own cells (cursor, SGR, scroll regions, alt screen,
modes, wide cells, tabs, charsets), keeps the program's {Modes} for [Encode], answers
its queries from the screen itself and gives its OSC out as events (`contained`);
[Scrollback] keeps the rows it scrolls off as logical lines in a ring, reflowed at any
width.

The boundary (the ops other systems call), defined in the modules and re-exported here:

- `feed(parser, data) -> tuple[Action, ...]` ({Bytes} => {Actions}, for Input's
  [Decoder]): the actions `data` completes on the parser the Decoder keeps for its
  stream; see [Parser] (`parser.feed`). The Decoder makes its parser with
  `Parser("input")`, reads `parser.state` / `parser.pending` to tell a lone Esc apart
  by its own `now`, and calls `parser.flush()` to end it.
- `parse(data, *, direction="output") -> tuple[Action, ...]` ({Bytes} => {Actions},
  for [Input]): one complete stream at once, on a fresh parser:
  `coalesce(p.feed(data) + p.flush())` with `p = Parser(direction)`. So
  `parse(b"\\x1b", direction="input") == (Execute(0x1B),)`. Errors as `Parser` and
  `Parser.feed` give them (`TypeError` for data that is not bytes-like or a direction
  that is not a `str`, `ValueError` for an unknown direction).
- `encode(event, modes) -> bytes` ({Event} => {Bytes}, for Embed's [Pty]): an input
  event as the target's modes want it; see [Encode] (`encode.encode`).
- `apply(screen, data) -> Grid` ({Bytes} => {Grid}, for Embed's [Pty] and Testing's
  [Virtual]): the bytes a program wrote, performed on its `Screen`:
  `screen_apply(screen, screen.parser.feed(data))`, `screen_apply` being [Screen]'s
  own `apply` (the module function `cure.interact.vt.screen.apply`, which takes
  actions; a `Screen` has no `apply` method). It returns `screen.grid()`: a new
  Grid of the active buffer (inside a sync block, the block's starting frame). A
  sequence split across two calls is carried by the screen's parser. The replies to
  write back to the program's pty and the events (title, cwd, clipboard, bell) are
  then `screen.take()`; the rows scrolled off, `screen.scrolled()`, for
  `keep(ring, ...)`. `TypeError` when `screen` is not a `Screen` or `data` is not
  `bytes`, `bytearray` or `memoryview`; no byte sequence raises. Only this op of the
  two is re-exported under the name `apply`; reach [Screen]'s with
  `from cure.interact.vt.screen import apply`.

Re-exported for consumers: `Parser`, `STATES`, `DIRECTIONS`, `MAX_PARAMS`,
`MAX_INTERMEDIATES`, `MAX_OSC`, `MAX_VALUE` (parser); `Print`, `Execute`, `Csi`, `Esc`,
`Osc`, `Hook`, `Put`, `Unhook`, `Ss3`, `LegacyMouse`, `Pasted`, `Action`, `ACTIONS`,
`Performer`, `dispatch`, `coalesce` (performer); `Modes`, `KEYS`, `KEYPAD`, `MODS`,
`BUTTONS`, `KINDS`, `MOUSE_MODES` (encode); `Screen`, `Cursor`, `Line`, `Reply`,
`Title`, `Cwd`, `Clipboard`, `Bell`, `Event`, `EVENTS`, `CHARSETS`, `DEC_GRAPHICS`,
`reflow` (screen); `Ring`, `keep`, `height`, `view` (scrollback).

Note: the function `encode` shadows the submodule of the same name as a package
attribute. Reach the submodule's own names with a from-import of the dotted module path
(`from cure.interact.vt.encode import Modes`), never through the attribute.

Effects: none, apart from the state a `Parser` keeps for its own stream, a `Screen`
its own (`apply` changes the screen it is given) and a `Ring` the lines `keep` adds.

Usage:
    from cure.interact.vt import Parser, feed, parse, encode, Modes, Csi, Print, Execute
    from cure.interact.vt import Screen, Ring, apply, keep
    parse(b"\\x1b[1mhi\\x1b[0m")          # (Csi("m", ((1,),)), Print("hi"), Csi("m", ((0,),)))
    p = Parser("input")
    feed(p, b"\\x1b[A\\x1b")               # (Csi("A"),); p.state == "escape"
    p.flush()                             # (Execute(0x1B),)
    encode(Key("enter", frozenset(), ""), Modes())   # b"\\r" (Key: Input's event class)
    s = Screen(20, 2)
    apply(s, b"\\x1b[32mok\\x1b[6n")      # a Grid: row 0 "ok" in green
    s.take()                              # (Reply(b"\\x1b[1;3R"),): for the program's pty
    ring = keep(Ring(), s.scrolled())     # nothing scrolled yet: an empty ring
"""

from .encode import BUTTONS, KEYPAD, KEYS, KINDS, MODS, MOUSE_MODES, Modes, encode
from .parser import (
    DIRECTIONS, MAX_INTERMEDIATES, MAX_OSC, MAX_PARAMS, MAX_VALUE, STATES, Parser, feed,
)
from .performer import (
    ACTIONS, Action, Csi, Esc, Execute, Hook, LegacyMouse, Osc, Pasted, Performer, Print,
    Put, Ss3, Unhook, coalesce, dispatch,
)
from .screen import apply as screen_apply
from .screen import (
    CHARSETS, DEC_GRAPHICS, EVENTS, Bell, Clipboard, Cursor, Cwd, Event, Line, Reply, Screen,
    Title, reflow,
)
from .scrollback import Ring, height, keep, view


def parse(data: "bytes | bytearray | memoryview", *, direction: str = "output") -> "tuple[Action, ...]":
    """One complete stream on a fresh parser, flushed and coalesced (see the package)."""
    p = Parser(direction)
    return coalesce(p.feed(data) + p.flush())


def apply(screen: Screen, data: "bytes | bytearray | memoryview") -> "Grid":
    """A program's bytes performed on its screen; a new Grid of what it shows (see the package)."""
    if not isinstance(screen, Screen):
        raise TypeError(f"screen must be a Screen, got {type(screen).__name__}")
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError(f"data must be bytes, bytearray or memoryview, got {type(data).__name__}")
    return screen_apply(screen, screen.parser.feed(data))
