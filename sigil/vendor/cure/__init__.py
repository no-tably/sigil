"""[Cure]: a stdlib-only terminal UI library, shared by sigil (the viewer), construct
(the console and its multiplexer) and merlang (through an adapter).

A library, not a program: the app owns its main loop and imports only the parts it
needs. No part of cure runs a loop of its own. No part calls the app, except Testing's
Pilot (the update and view a test hands it) and the `now` and `stop` the app may inject
(Term; Remote's Transport, Server and Attach take `now`). No part holds process-wide
state, except Term's Signals on the app's opt-in (handlers installed, the previous ones
put back on close) and module-level memo caches that keep only what a pure function
answers again for the same arguments.
What the parts share travels as plain values (`Caps`, `Rect`, `HitMap`, `Grid` in Core;
`Charset`, `Context` in Draw).

Kind: the top system of the spec; `[Cure]` has no flows in or out, so this module
defines and re-exports nothing. It imports nothing from cure, so `import cure` pulls in
no package, and importing one package never pulls in another
(`.construct/mapping.md`). Its one module beside the packages is `<Closed>`
(`cure/closed.py`): the terminal, a waited-on fd, a pane's program or a link went away,
returned to the app (never raised) by Term's Reader, Clock's Wait, Embed's Pty and
Remote's Transport, Attach and Relay (Attach hands it back inside its `Ended`).

The packages, each importable alone, each depending only on those above it:

- `cure.core` (pure): Text, Style, Buffer, Geometry and `Caps`; the ops `write`, `show`,
  `rows`.
- `cure.draw` (pure): Theme, Canvas, Layout, Graph, Widgets, Paint, Memo, Views; the op
  `frame` (and `sizes`).
- `cure.interact` (pure): Vt, Input; the op `apply`.
- `cure.edge`: Term, Clock, Files, Embed, Remote: the only parts that touch the OS.
- `cure.testing`: Virtual, Pilot, Snapshot, Sweep.

The flows between them, each op public in the package it is called on:

- `[Draw] -> [Core] : write({Cells}) => {Grid}` and `[Interact] -> [Core] :
  write({Cells}) => {Grid}`: Core's `write`.
- `[Edge] -> [Core] : show({Buffer}) => {Bytes}`: Core's `show`.
- `[Testing] -> [Core] : rows({Buffer}) => {Rows}`: Core's `rows`.
- `[Testing] -> [Draw] : frame({Node}) => {Frame}`: Draw's `frame`.
- `[Edge] -> [Interact] : apply({Bytes}) => {Grid}` and `[Testing] -> [Interact] :
  apply({Bytes}) => {Grid}`: Interact's `apply`.

One frame, in the app's own loop (README.md; the app's `update` and `view` are its own
code, Elm-style, README decision 2): `data = term.read(timeout)` (Edge's Term);
`decoder.feed(data, now)` (Interact's Input) gives events; `route(...)` gives actions,
and the app's `update(state, actions, now)` is called once per routed event;
`frame(view(state), size, ctx)` (Draw's Paint) gives a Buffer and a HitMap;
`term.show(frame.buffer)` diffs against the front buffer and writes. Rects first,
cells second, strings last.

Effects: none on import.
"""
