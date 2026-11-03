"""[Interact]: Vt, Input.

Kind: system (the expansion of [Interact] in cure); pure: no I/O, no clock read, no
process-wide state. Bytes in, events out, and the other way round, a program's bytes in,
cells out. Two systems: [Vt] (`cure.interact.vt`: the DEC parser, used both for our input
and for a pane's output; Screen, Scrollback, Encode) and [Input] (`cure.interact.input`:
Decoder, Events, Bindings, Focus, Router, Edit). Depends on Core (`[Interact] -> [Core] :
write({Cells}) => {Grid}`: a Screen's cells are Core's cells, written into Core's Grid),
never on Draw or Edge.

The boundary (the op the other packages call): `apply`, Vt's package op re-exported
here, the same object (`cure.interact.apply is cure.interact.vt.apply`), for both drawn
flows (refine round 9: the root flows name the op the detail flows already call):

- `apply(screen, data) -> Grid`:
  - for [Edge]: `[Edge] -> [Interact] : apply({Bytes}) => {Grid}`, a pane's program
    through Vt; Embed's [Pty] keeps one `Screen` per pane and performs its program's
    output on it (`[Pty] -> [Vt] : apply`);
  - for [Testing]: `[Testing] -> [Interact] : apply({Bytes}) => {Grid}`, emitted bytes
    replayed; Testing's [Virtual] keeps one `Screen` across frames (`[Virtual] -> [Vt] :
    apply`).
  Its contract is Vt's (`cure.interact.vt`): the bytes performed on `screen`, changed in
  place, and a new Core `Grid` of what it shows returned. The laws the two flows rely on,
  stated over the screen's `grid()`, `cursor()`, `title`, `modes`, `take()` and
  `scrolled()`:
  - chunk independence: for any split `data == a + b` that does not fall inside a
    grapheme cluster (Vt's Printing: a cluster split across two reads prints as two
    clusters), applying `a` then `b` on one fresh `Screen(w, h)` and `data` once on
    another leave the two alike;
  - the replay law (Testing's [Virtual]): the bytes Core's `show` emits for a grid,
    applied on a fresh `Screen(g.w, g.h)`, show that grid as a terminal at the
    display's depth realizes it: `apply(Screen(g.w, g.h), show(Display(caps), g)) ==
    realized(g, caps)` (`cure.testing.realized`), within Virtual's accepted limits (no
    control glyphs, no neighbouring cells that join into one cluster).
  Errors: Vt's (`TypeError` when `screen` is not a Vt `Screen` or `data` is not `bytes`,
  `bytearray` or `memoryview`); no byte sequence raises.

`emulate` and `replay` are gone (refine round 9, Z1d: nothing called them; Pty and
Virtual call `apply`): `cure.interact` has neither name.

Re-exported for consumers: `Screen` (Vt's [Screen], the screen `apply` performs on).
Everything else is reached through its own system's package (`cure.interact.vt`,
`cure.interact.input`).

Effects: none on import (importing it imports Vt, and through Vt Core's Buffer, Text and
Style; not Input); `apply` changes only the screen it is given.

Usage:
    from cure.core import Caps, Display, cells, rows, show
    from cure.interact import Screen, apply
    s = Screen(20, 2)
    apply(s, b"\\x1b[32mo")
    rows(apply(s, b"k\\x1b[6n")).plain     # ("ok                  ", "                    ")
    s.cursor().x, s.cursor().y            # (2, 0)
    s.take()                              # (Reply(data=b"\\x1b[1;3R"),): for the program's pty
    g = cells(["hello", "world"])
    rows(apply(Screen(5, 2), show(Display(Caps(depth=16)), g))).plain   # ("hello", "world")
"""

from .vt import Screen, apply
