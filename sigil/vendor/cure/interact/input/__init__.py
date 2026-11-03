"""[Input]: events, bindings, focus, routing.

Kind: system (the expansion of [Input] in Interact); pure: no I/O, no clock read, no
process-wide state. Depends on Vt (its own spec), and on Core, inherited through
Interact (spec question 6); never on Draw (so not Widgets): the shapes Draw reads from
it (KeyHints' entries) and it reads from Draw (a HitMap, in I2) are duck typed.

[Decoder] turns the bytes a terminal sends into [Events] on a Vt `Parser("input")`
(incremental UTF-8, CSI / SS3 keys with modifiers, kitty CSI u, SGR and X10 mouse,
bracketed paste as one `Paste`, focus, in-band resize, query replies as `Reply`), a
lone Esc told apart by the `now` the app gives; [Events] are the values (Key, Mouse,
Paste, Focus, Resize, Reply, Unknown) and a key's one string form (a stroke,
"ctrl+s"); [Bindings] is the one table that drives dispatch, the key hints and the
help (layers default <- child <- authored <- runtime, a `None` action masking; chords
with a timeout by `now`, a prefix key, modes). I2 adds [Focus] (the ring, scopes,
traps, spatial moves; rove != commit != fire), [Router] (`route`: modal -> prefix ->
focused input -> bindings -> bubble, mouse by the HitMap it is given, returning
actions, changing no app state) and [Edit] (a text-edit value), and the `route` op.

The boundary (the ops other systems call), defined in the modules and re-exported here:

- `decode(data) -> tuple[Event, ...]` ({Bytes} => {Events}, for sigil, construct and
  merlang's adapter): one complete input at once, on a fresh decoder and ended:
  `event(parse(data, direction="input"))[0]`, using Vt's `parse` (`[Input] -> [Vt] :
  parse`). It equals `d.feed(data, now) + d.end()` for a fresh `Decoder()` `d` and any
  `now` (chunk independence: [Decoder]). `decode(b"q\\x1b[A\\x1b") == (Key("q",
  text="q"), Key("up"), Key("escape"))`. `TypeError` when `data` is not `bytes`,
  `bytearray` or `memoryview`; never on byte content. An app's loop, where bytes come
  in pieces and time matters, keeps a `Decoder` and calls `feed`.
- `feed(decoder, data, now) -> tuple[Event, ...]` ({Bytes} => {Events}, for the app's
  loop and Testing's [Pilot], which drives real decoding with fake time):
  `decoder.feed(data, now)`, see [Decoder]. `TypeError` when `decoder` is not a
  `Decoder`, and as `Decoder.feed` gives it.
- `route(event, state, now, *, bindings, ...)` ({Events} => {Actions}, for the app's
  loop (construct, the gallery) and [Pilot]): [Router]'s `route`, built (I2), its full
  signature below and its contract in `router`.

Re-exported for consumers: `Decoder`, `Carry`, `event` (decoder); `Key`, `Mouse`,
`Paste`, `Focus`, `Resize`, `Reply`, `Unknown`, `Event`, `EVENTS`, `KEY_EVENTS`,
`MOD_ORDER`, `ALIASES`, `REPLIES`, `key`, `stroke`, `normal`, `text_of` (events);
`Binding`, `Bindings`, `LAYERS`, `Fire`, `Pending`, `Miss`, `sequence`, `match`,
`action`, `expire`, `deadline`, `prefixed`, `hints`, `help` (bindings).

Effects: none, apart from the state a `Decoder` keeps for its own stream.

Usage (the app owns the loop; the README's sample):
    from cure.interact.input import Decoder, Bindings, Binding, Pending, Fire, Key, match
    from cure.interact.input import deadline, expire
    decoder = Decoder(timeout=0.05)
    table = Bindings(default=(Binding("q", "quit", "quit"),
                              Binding("ctrl+x ctrl+s", "save", "save")), timeout=1.0)
    chord = None
    for ev in decoder.feed(data, now):         # data, now: the app's read and clock
        if isinstance(ev, Key):
            got = match(table, ev, now, pending=chord)
            chord = got if isinstance(got, Pending) else None
            if isinstance(got, Fire):
                ...                            # the app's update(state, got.action)
    # sleep at most until min(decoder.deadline, deadline(table, chord)), then
    # decoder.flush(now) and expire(table, chord, now)

I2's `route`, re-exported from [Router] (the `route` op above): `route(event, state,
now, *, bindings, mode=None, tree=None, hits=None, layer=0, edits=None) ->
tuple[Routing, tuple[Action, ...]]`, one event routed through the app's one bindings
table, see `router`. [Focus] (`focus`), [Router] (`router`) and [Edit] (`edit`) are imported
from their modules; the app's names are re-exported here (Z1): `route`, `tick`, `scopes`,
`Routing` and the actions it gives (`Capture`, `Edited`, `Focused`, `Hovered`, `Passed`,
`Pointer`), and Focus's tree (`Group`, `Stop`, `Target`).
"""

from cure.interact.vt import parse

from .bindings import (
    LAYERS, Binding, Bindings, Fire, Miss, Pending, action, deadline, expire, help, hints,
    match, prefixed, sequence,
)
from .decoder import Carry, Decoder, event
from .events import (
    ALIASES, EVENTS, KEY_EVENTS, MOD_ORDER, REPLIES, Event, Focus, Key, Mouse, Paste, Reply,
    Resize, Unknown, key, normal, stroke, text_of,
)
from .focus import Group, Stop, Target
from .router import Capture, Edited, Focused, Hovered, Passed, Pointer, Routing, route, scopes, tick


def decode(data: "bytes | bytearray | memoryview") -> "tuple[Event, ...]":
    """One complete input on a fresh decoder, ended (see the package)."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError(f"data must be bytes, bytearray or memoryview, got {type(data).__name__}")
    return event(parse(data, direction="input"))[0]


def feed(decoder: Decoder, data: "bytes | bytearray | memoryview", now: "float | int") -> "tuple[Event, ...]":
    """`decoder.feed(data, now)`: the events the bytes complete (see the package)."""
    if not isinstance(decoder, Decoder):
        raise TypeError(f"decoder must be a Decoder, got {type(decoder).__name__}")
    return decoder.feed(data, now)
