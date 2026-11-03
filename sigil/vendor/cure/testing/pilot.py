"""[Pilot]: scripted keys and clicks through real decoding and routing, with fake time;
the app's update and view passed in as plain functions.

Kind: service (a class with explicit state, and its default modes); no I/O, no clock
read.

What it does: drives an app the way its main loop would, without a terminal. A script
says what a person does (press keys, type, paste, click, resize, wait); the Pilot
writes it as the bytes a terminal sends (Vt's `encode`, for the `modes` a terminal
was put in), decodes them with a real Input `Decoder` (`[Pilot] -> [Input] :
feed({Bytes}) => {Events}`), routes each event with Input's `route` (`[Pilot] ->
[Input] : route({Events}) => {Actions}`) against the hits of the last frame, gives the
actions to the app's `update`, and paints the next frame with Paint's `frame`
(`[Pilot] -> [Paint] : frame({Node}) => {Frame}`) from the app's `view`. Time is a
number the Pilot holds and only `wait` moves (fake time): the Esc timeout and a chord's
timeout run on it, as they would on the app's clock.

cure has no runner and no App protocol (README decision 2): the app's model is its
own; the Pilot takes the two functions, the state they work on, and the routing
inputs, and runs the README's loop over them, one step per scripted input.

## The app's side

- `update(state, actions, now) -> state`: the app's update, called once per routed
  event with the tuple of actions `route` returned for it (possibly empty) and the
  Pilot's fake `now`, as the README's loop calls it (`state = update(state, actions,
  now)`, with the clock's `now`), and once per `wait` whose chord timeout gives actions. Its result is the new state. (Effects are the app's; the
  Pilot keeps only the state.)
- `view(state) -> node`: the app's view, anything Paint's `frame` takes (a widget
  node, a Layout `Screens`, a `Tiled`).
- The routing inputs, each given as a value or as a function of `(state, frame)` (the
  current state and the last frame painted), asked afresh for every event:
  `bindings` (Input's one [Bindings] table), `mode` (`None` or a `str`), `tree`
  (`None` or a [Focus] `Group`), `edits` (`None` or a mapping from a stop id to its
  [Edit] value). A value is told from a function by `callable(value)`.

## The pilot

`Pilot(update, view, state, ctx, *, bindings, size=(80, 24), now=0.0, mode=None,
tree=None, edits=None, routing=Routing(), modes=MODES, timeout=0.05)`:
- `ctx`: the app's root Draw {Context}. Each frame is painted with
  `dataclasses.replace(ctx, focus=routing.focused, hover=routing.hover)`: the focus
  and hover the router keeps (so a focused or hovered widget paints as one); every
  other field (the theme, the caps, the base level, `now`, the animation tick) is the
  app's, as given.
- `size`: the terminal's `(w, h)`; `now`: the start time (an `int` or `float`);
  `routing`: the router's starting `Routing` (`Routing(focused="search")` starts with
  a focus); `modes`: the Vt `Modes` the bytes are written for (what the app put the
  terminal in); `timeout`: the `Decoder`'s Esc timeout, in the units of `now`.
- `MODES = Modes(kitty=24, mouse=1003, mouse_sgr=True, paste=True, focus=True)`: kitty
  "all keys as escapes" with associated text (8 | 16), so every stroke decodes back to
  exactly itself (Input [Decoder]'s "Keys, exactly by stroke" law) and a lone Escape
  is never held; SGR mouse with all motion; bracketed paste; focus reports.
- The constructor makes a fresh `Decoder(timeout=timeout)` and paints the first frame.

State (read-only attributes, all of it): `state` (the app's state, as `update` last
returned it); `routing` (the router's `Routing`); `frame` (the last Paint `Frame`);
`size`; `now`; `modes`; `decoder` (the `Decoder`; `decoder.pending` tells a held
lone Esc).

One step. Every scripted input below is one step: its bytes are one read of the
terminal, at the current `now`:
1. `events = feed(decoder, data, now)` (Input's op);
2. for each event in order: `routing, actions = route(event, routing, now,
   bindings=B, mode=M, tree=T, hits=frame.hits, layer=frame.layer, edits=E)`, with
   `B`, `M`, `T`, `E` the routing inputs for the current state and `frame` (the
   frame of the step before: hits are always the last frame's, as in the README's
   loop); then `state = update(state, actions, now)`;
3. `frame = frame(view(state), size, ctx')` (Paint's op), `ctx'` as above.
It returns every action of the step, in order (all the events' actions joined).

The script (each returns `tuple[Action, ...]`, the actions of its step or steps):
- `send(data)`: one step of the raw `bytes` (`bytearray` and `memoryview` taken
  too): a sequence split by hand, a reply, an Esc to be timed out.
- `press(*strokes)`: each stroke in turn (a stroke as Input's `key` reads it: `"q"`,
  `"ctrl+x"`, `"shift+tab"`, `"escape"`) is one step of `encode(key(stroke), modes)`
  (Vt's [Encode]); the frame is repainted between strokes.
- `type(text)`: one step of `text.encode("utf-8")`: what a terminal sends for typed
  characters (each decodes as Input's Print rule gives it; a control character is the
  control key it is, `"\\n"` ctrl+j).
- `paste(text)`: one step of `encode(Paste(text), modes)`.
- `mouse(button, kind, x, y, *, mods=frozenset())`: one step of
  `encode(Mouse(button, kind, x, y, mods), modes)`: any one report (a "move" with
  `button` `None` hovers; a "press" of "wheel_down" is a wheel step). `b""` (the
  modes do not report it) is a step that routes nothing and repaints.
- `click(x, y, *, button="left", mods=frozenset())`: `mouse(button, "press", x, y,
  mods=mods)` then `mouse(button, "release", x, y, mods=mods)`: two steps.
- `centre(tag) -> tuple[int, int]`: where to click a region: the centre cell
  `(r.x + (r.w - 1) // 2, r.y + (r.h - 1) // 2)` of the rect `r` of the first `Hit`
  of `frame.hits.hits` whose `tag == tag` and whose rect is not empty. `KeyError(tag)`
  when there is none. (Not a step: it reads the frame.) `p.click(*p.centre("ok"))`.
- `resize(w, h)`: the terminal resized (a `SIGWINCH`, not bytes): `size = (w, h)`,
  then one step whose events are `(Resize(width=w, height=h),)` instead of decoded
  ones (the router passes it to the app as `Passed`), painted at the new size.
- `wait(seconds)`: time passes: `now += seconds`; then one step of `b""` (the
  decoder ends what is held once it is due: a lone Esc becomes the Escape key); then
  the chord timeout: `routing, actions = tick(routing, now, bindings=B)` (Input's
  [Router]), and when `actions` is not empty, `state = update(state, actions, now)`; then
  the frame is repainted. Returns the step's actions then the tick's.

Laws (each a property a test can loop over apps, scripts and modes):
- deterministic: two Pilots built from equal arguments (with a pure `update` and
  `view`) and driven by the same script return equal actions at every call and have
  equal `state`, `routing` and `frame` after it.
- the frame is the view: after the constructor and after every call,
  `p.frame == frame(view(p.state), p.size, dataclasses.replace(ctx,
  focus=p.routing.focused, hover=p.routing.hover))`.
- real routing: with `modes=MODES`, `p.press(s)` for one stroke `s` returns exactly
  `route(key(s), r, p.now, bindings=B, mode=M, tree=T, hits=f.hits, layer=f.layer,
  edits=E)[1]` for the `routing` `r`, frame `f` and routing inputs before the call;
  and `p.paste(t)` routes exactly `Paste(t')`, `t'` being `t` with every
  `"\\x1b[201~"` removed (Encode's rule).
- fake time: only `wait` moves `now`, by exactly `seconds`; with `modes=MODES`
  nothing is ever held, so `p.wait(t)` returns only the chord timeout's actions.
- a lone Esc (legacy `Modes()`): `p.press("escape")` returns `()` with
  `p.decoder.pending`; after `p.wait(timeout)` the Escape key is routed.

Inputs: as above.
Outputs: the script's calls return `tuple[Action, ...]` (Input's [Router] actions,
  `ACTIONS`); `centre` a cell `(x, y)`.
Errors: `Pilot(...)`: `TypeError` when `update` or `view` is not callable, `bindings`
  is neither a `Bindings` nor callable, `size` is not a pair of ints (a `bool`
  included), `now` is not an `int` or `float` (a `bool` is not), `routing` is not a
  `Routing` or `modes` not a Vt `Modes`; `ValueError` when a size is negative; and as
  `Decoder(timeout)` raises. `send`: `TypeError` when `data` is not bytes-like.
  `press`: as Input's `key` and Vt's `encode` raise for a stroke (`TypeError`,
  `ValueError`). `type`, `paste`: `TypeError` when `text` is not a `str`. `mouse`,
  `click`: as Input's `Mouse` and Vt's `encode` raise. `resize`: as for `size`.
  `wait`: `TypeError` when `seconds` is not an `int` or `float` (a `bool` is not);
  `ValueError` when it is negative (time never runs back). `centre`: `KeyError` as
  above. What the app's `update` and `view`, a routing input's function, `route`,
  `tick` and `frame` raise propagates unchanged: a step stops at the first error,
  keeping the state, routing and frame of the events before it (the decoder has
  taken the bytes).
Effects: only the stated changes to the Pilot's own state (and whatever the app's
  functions do). No I/O, no clock read.

Usage:
    from cure.core.buffer import text
    from cure.draw.context import Context
    from cure.draw.theme import builtin
    from cure.draw.widgets import Block, Button, Paragraph
    from cure.interact.input import Binding, Bindings, Fire, Miss, Pending
    from cure.interact.input.router import Pointer
    from cure.interact.vt import Modes
    from cure.testing.pilot import Pilot

    def view(n):
        return Block((Paragraph(f"count {n}"), Button("+1", id="inc")), id="box")

    def update(n, actions, now):
        for a in actions:
            if isinstance(a, Fire) and a.action == "inc":
                n += 1
            if isinstance(a, Pointer) and a.event.kind == "press" and a.target.hits[0].tag == "inc":
                n += 1
        return n

    table = Bindings(default=(Binding("+", "inc", "add one"),
                              Binding("ctrl+x ctrl+c", "quit", "quit")), timeout=1.0)
    p = Pilot(update, view, 0, Context.of(builtin()), bindings=table, size=(12, 4))
    text(p.frame.buffer)         # "╭──────────╮\\n│count 0   │\\n│ [ +1 ]   │\\n╰──────────╯"
    p.press("+", "+")            # (Fire("inc", ("+",), table.default[0]),) * 2
    p.state                      # 2
    p.centre("inc")              # (4, 2): the Button's hit is Rect(1, 2, 7, 1)
    [type(a).__name__ for a in p.click(*p.centre("inc"))]   # ["Hovered", "Pointer", "Pointer"]
    p.state, p.routing.hover     # 3, "inc"
    p.press("ctrl+x")            # (Pending(("ctrl+x",), 0.0),)
    p.wait(0.5), p.wait(0.5)     # (), (Miss(("ctrl+x",)),): the chord timed out at 1.0
    p.now                        # 1.0
    q = Pilot(update, view, 0, Context.of(builtin()), bindings=table, size=(12, 4),
              modes=Modes())     # a legacy terminal: Escape is a lone ESC
    q.press("escape"), q.decoder.pending   # (), True
    q.wait(0.05)                 # (Passed(Key("escape")),)
"""

import dataclasses

from cure.draw.paint import frame as paint
from cure.interact.input import Bindings, Decoder, Mouse, Paste, Resize, key
from cure.interact.input.router import Routing, route, tick
from cure.interact.vt import Modes, encode

MODES = Modes(kitty=24, mouse=1003, mouse_sgr=True, paste=True, focus=True)
"""The terminal modes a Pilot writes its bytes for by default (see the module)."""


class Pilot:
    """An app driven by a script: real decoding and routing, fake time, its update and view passed in."""

    def __init__(self, update: object, view: object, state: object, ctx: object, *,
                 bindings: object, size: "tuple[int, int]" = (80, 24),
                 now: "float | int" = 0.0, mode: object = None, tree: object = None,
                 edits: object = None, routing: Routing = Routing(), modes: Modes = MODES,
                 timeout: "float | int" = 0.05) -> None:
        """Check the arguments, make a fresh Decoder and paint the first frame (see the module)."""
        if not callable(update):
            raise TypeError(f"update must be callable, got {_name(update)}")
        if not callable(view):
            raise TypeError(f"view must be callable, got {_name(view)}")
        if not (isinstance(bindings, Bindings) or callable(bindings)):
            raise TypeError(f"bindings must be a Bindings or callable, got {_name(bindings)}")
        size = _size(size)
        if not _is_number(now):
            raise TypeError(f"now must be an int or float, got {_name(now)}")
        if not isinstance(routing, Routing):
            raise TypeError(f"routing must be a Routing, got {_name(routing)}")
        if not isinstance(modes, Modes):
            raise TypeError(f"modes must be a Vt Modes, got {_name(modes)}")
        self._decoder = Decoder(timeout=timeout)
        self._update, self._view, self._ctx = update, view, ctx
        self._inputs = (bindings, mode, tree, edits)
        self._state, self._routing, self._size, self._now = state, routing, size, now
        self._modes = modes
        self._frame = None
        self._paint()

    @property
    def state(self) -> object:
        """The app's state, as `update` last returned it."""
        return self._state

    @property
    def routing(self) -> Routing:
        """The router's own state."""
        return self._routing

    @property
    def frame(self) -> object:
        """The last Paint `Frame`."""
        return self._frame

    @property
    def size(self) -> "tuple[int, int]":
        """The terminal's `(w, h)`."""
        return self._size

    @property
    def now(self) -> "float | int":
        """The fake time; only `wait` moves it."""
        return self._now

    @property
    def modes(self) -> Modes:
        """The Vt `Modes` the scripted input is written for."""
        return self._modes

    @property
    def decoder(self) -> object:
        """The Input `Decoder` the bytes go through."""
        return self._decoder

    def send(self, data: "bytes | bytearray | memoryview") -> tuple:
        """One step of raw bytes: decoded, routed, updated, repainted; its actions."""
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError(f"data must be bytes, bytearray or memoryview, got {_name(data)}")
        return self._step(self._decoder.feed(data, self._now))

    def press(self, *strokes: str) -> tuple:
        """Each stroke, encoded for `modes`, one step each; every action, in order."""
        data = [encode(key(stroke), self._modes) for stroke in strokes]
        out: list = []
        for d in data:
            out.extend(self.send(d))
        return tuple(out)

    def type(self, text: str) -> tuple:
        """One step of the text's UTF-8 bytes, as a terminal sends typed characters."""
        if not isinstance(text, str):
            raise TypeError(f"text must be a str, got {_name(text)}")
        return self.send(text.encode("utf-8"))

    def paste(self, text: str) -> tuple:
        """One step of the text as a (bracketed) paste, encoded for `modes`."""
        if not isinstance(text, str):
            raise TypeError(f"text must be a str, got {_name(text)}")
        return self.send(encode(Paste(text), self._modes))

    def mouse(self, button: "str | None", kind: str, x: int, y: int, *,
              mods: frozenset = frozenset()) -> tuple:
        """One step of one mouse report, encoded for `modes`."""
        return self.send(encode(Mouse(button, kind, x, y, mods), self._modes))

    def click(self, x: int, y: int, *, button: str = "left", mods: frozenset = frozenset()) -> tuple:
        """A press then a release at `(x, y)`: two steps; every action, in order."""
        press = encode(Mouse(button, "press", x, y, mods), self._modes)
        release = encode(Mouse(button, "release", x, y, mods), self._modes)
        return self.send(press) + self.send(release)

    def centre(self, tag: object) -> "tuple[int, int]":
        """The centre cell of the first non-empty hit with `tag` in the last frame (KeyError when none)."""
        for hit in self._frame.hits.hits:
            r = hit.rect
            if hit.tag == tag and r.w > 0 and r.h > 0:
                return (r.x + (r.w - 1) // 2, r.y + (r.h - 1) // 2)
        raise KeyError(tag)

    def resize(self, w: int, h: int) -> tuple:
        """The terminal resized: the new size, a `Resize` routed, a frame at the new size."""
        self._size = _size((w, h))
        return self._step((Resize(width=w, height=h),))

    def wait(self, seconds: "float | int") -> tuple:
        """Fake time passes: held bytes ended once due, a chord's timeout, a repaint; their actions."""
        if not _is_number(seconds):
            raise TypeError(f"seconds must be an int or float, got {_name(seconds)}")
        if seconds < 0:
            raise ValueError(f"seconds must be >= 0 (time never runs back), got {seconds}")
        self._now += seconds
        stepped = self._route(self._decoder.feed(b"", self._now))
        bindings = self._ask(self._inputs[0])
        routing, ticked = tick(self._routing, self._now, bindings=bindings)
        if ticked:
            self._state = self._update(self._state, ticked, self._now)
        self._routing = routing
        self._paint()
        return stepped + ticked
    # -- one step

    def _step(self, events: tuple) -> tuple:
        """Route every event (updating the state after each), then repaint; the actions."""
        out = self._route(events)
        self._paint()
        return out

    def _route(self, events: tuple) -> tuple:
        """Each event routed against the last frame's hits and given to `update`."""
        out: list = []
        for event in events:
            b, m, t, e = (self._ask(x) for x in self._inputs)
            f = self._frame
            routing, actions = route(event, self._routing, self._now, bindings=b, mode=m,
                                     tree=t, hits=f.hits, layer=f.layer, edits=e)
            self._state = self._update(self._state, actions, self._now)
            self._routing = routing
            out.extend(actions)
        return tuple(out)

    def _ask(self, value: object) -> object:
        """A routing input: its value, or the function's for the state and last frame."""
        return value(self._state, self._frame) if callable(value) else value

    def _paint(self) -> None:
        """The next frame: the view of the state, with the router's focus and hover."""
        r = self._routing
        ctx = dataclasses.replace(self._ctx, focus=r.focused, hover=r.hover)
        self._frame = paint(self._view(self._state), self._size, ctx)


def _name(value: object) -> str:
    return type(value).__name__


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _size(size: object) -> "tuple[int, int]":
    """`size` as a `(w, h)` of ints >= 0 (TypeError, ValueError otherwise)."""
    if not isinstance(size, (tuple, list)) or len(size) != 2 or not all(map(_is_int, size)):
        raise TypeError(f"size must be a pair of ints, got {size!r}")
    w, h = size
    if w < 0 or h < 0:
        raise ValueError(f"a size cannot be negative, got {size!r}")
    return (w, h)
