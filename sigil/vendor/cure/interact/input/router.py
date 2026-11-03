"""[Router]: mouse by the {HitMap} it is given; a focused input owns ordinary keys.

Kind: service (the router's own state `Routing`, a drag's `Capture`, the actions it
returns, and the pure ops `route` and `tick`); pure. The router returns actions for
the app to apply; it changes no app state. The only state it reads and returns is its
own `Routing` (the focused id, a pending chord, a mouse capture, the hovered tag),
which the app keeps between calls, like the Decoder's.

It calls [Bindings] (`[Router] -> [Bindings] : action({Key}) => {Action}`: `match`,
`expire`, `hints`), [Focus] (`[Router] -> [Focus] : target({Event}) => {Target}`:
`target`, `path`, `move`) and [Edit] (`[Router] -> [Edit] : keys({Key}) => {Edit}`:
`keys`, `typed`, `command`, `apply`), and is the package's `route` op ({Events} =>
{Actions}, for Testing's [Pilot], which routes each decoded event in turn).

ONE bindings table drives every key: the app's table holds its own bindings and,
usually in its default layer, [Focus]' `FOCUS_BINDINGS` and [Edit]'s `EDIT_BINDINGS`
(scoped `EDIT_SCOPE`). The router applies the two reserved action shapes itself: a
focus action `(FOCUS, how)` with [Focus]' `move`, an edit action `(EDIT, command)` with
[Edit]'s `apply` on the focused input. Only the keys that type text skip the table
when an input is focused.

## State

- `Routing(focused=None, pending=None, capture=None, hover=None)` (frozen dataclass):
  `focused` `None` or a stop id ([Focus]' focus id: a `str` or a `tuple` of `str`,
  carried exactly as the tree and the hits give it; Router checks it, and every other
  id it is handed, with [Focus]' public `is_id` and annotates it with Focus' `Id`,
  never the private `_Id` / `_is_id`); `pending` `None` or [Bindings]'
  `Pending` (the chord so far); `capture` `None` or a `Capture`; `hover` `None` or the
  tag (any hashable) under the pointer. `Routing()` is the start. `TypeError` when a
  field has another type (`hover` unhashable included; `focused` neither `None`, a `str`
  nor a `tuple` of `str`: "Routing.focused must be None, a str or a tuple of str, got
  <type>"). `focused` is never checked against the tree: after the app changes its tree
  it heals focus itself, `dataclasses.replace(routing, focused=heal(old, new,
  routing.focused))` ([Focus]).
- `Capture(button, target)` (frozen dataclass): a drag in progress: the mouse
  `button` pressed (one of Vt's `BUTTONS`, never a wheel) and the [Focus] `Target` it
  was pressed on. `TypeError` / `ValueError` for another type or button.

## Actions

What `route` and `tick` return, in order, for the app's update (frozen dataclasses,
equal by value):
- [Bindings]' `Fire(action, keys, binding)`: fire `action`, as `match` gives it, from
  keys or from a click on a key hint (the same `Fire` the hint's keys give: keys and
  clicks fire the same actions). Never a focus or edit action: the router applies
  those.
- [Bindings]' `Pending(keys, since)`: a chord started or went on (also kept in
  `Routing.pending`, for a status bar); `Miss(keys)`: a chord broken or timed out.
- `Edited(stop, edit)`: the focused input's new [Edit] value (`stop` its id, a key of
  `edits`); the app stores it in
  place of the old one (it may equal the old one: the key was owned, nothing changed).
- `Focused(old, new)`: focus roved from `old` to `new` (each `None` or a stop id, a
  `str` or a tuple id as the tree holds it; never equal). Given only on a change.
- `Hovered(old, new)`: the tag under the pointer changed (each `None` or a tag; never
  equal).
- `Pointer(event, target, captured=False)`: a mouse event delivered: the [Events]
  `Mouse`, the [Focus] `Target` it is aimed at (its `hits`, innermost first, are what
  the app bubbles it through; empty: it hit no region of the input screen, e.g. a
  press outside a modal, which the app may take as "dismiss"), and whether it came
  through a drag's capture (`target` then is the capture's, whatever lies under the
  pointer now). The position is the event's own (`event.x`, `event.y`), screen cells;
  the region's own rect is `target.hits[0].rect`.
- `Passed(event)`: an event the router delivers to nothing: a key nothing owns or
  binds (a mux forwards it to its pane), a paste with no focused input, and every
  `Focus`, `Resize` and `Reply`, the app's own.
`ACTIONS` is the tuple of the eight classes in that order (`Fire`, `Pending`, `Miss`,
`Edited`, `Focused`, `Hovered`, `Pointer`, `Passed`); `Action` their union.

## Route

- `scopes(focused, *, tree=None, edits=None) -> tuple[str | tuple[str, ...], ...]`:
  the [Bindings] `scopes` the router queries with, which an app passes to `hints` and
  `help` too so that its key hints match dispatch: `p = path(tree, focused)` ([Focus];
  `()` with no tree or no such node), and, when `edits` has the key `focused` (a focused
  input), `EDIT_SCOPE` put right after the stop's own id: `(p[0], EDIT_SCOPE) + p[1:]`,
  or `(EDIT_SCOPE,)` when `p` is `()`. Every id of the chain is passed as it is, tuple
  ids included: a binding scoped by a tuple id (`scope=("pane", "dag")`) is active while
  that stop, or a stop inside a group with that id, is focused ([Bindings] matches
  scopes by `==`). `TypeError` when `focused` is not `None`, a `str` or a `tuple` of
  `str` ("focused must be None, a str or a tuple of str, got <type>"), `tree` not `None`
  or a `Group`, `edits` not `None` or a mapping; `ValueError` when `p` holds
  `EDIT_SCOPE` (the id is reserved; a tuple id is never equal to it, `("edit",)`
  included).
- `route(event, state, now, *, bindings, mode=None, tree=None, hits=None, layer=0,
  edits=None) -> tuple[Routing, tuple[Action, ...]]`: one event, routed. The app
  passes, per call:
  - `event`: one of [Events]' `EVENTS`; `state`: the `Routing` the last call gave (or
    `Routing()`); `now`: its clock, a number (chords time out by it);
  - `bindings`: the input screen's one [Bindings] table, with `mode` (`None` or a
    `str`, the app's current mode);
  - `tree`: `None` or the input screen's [Focus] tree (a `Group`);
  - `hits`: `None` or the last frame's {HitMap} (duck typed: read through `stack(x,
    y)`), and `layer`: the input screen's lowest hit layer (an `int`, 0 for the base
    screen; a modal's overlay layer while one is up);
  - `edits`: `None` or a mapping from a stop id (a `str` or a `tuple` of `str`) to
    that text input's [Edit] value (a focused stop that is a key of it is a focused
    input: `{("orchestrator", "spec"): edit}` for a Views node's id).
  It returns the next `Routing` and the actions, in the order they happen.

The route order: modal capture -> the prefix layer -> a focused input -> bindings ->
bubble.

Modal capture: the router sees only the input screen ([Screens]' `input`: the top of
the screen stack; the ones under it get none): its table, its tree, and its hits at or
above `layer`; nothing the router does reaches a screen under it. A drag's capture is
the mouse's own (below).

With `f = state.focused`, `input = f` when `edits` has the key `f` (else `None`), `p
= path(tree, f)` and `sc = scopes(f, tree=tree, edits=edits)` (the focus chain,
innermost first, by which [Bindings] ranks a scoped binding first: the bubble from the
focused widget out to the screen, an input's edit keys right after its own):

Handling a `Fire` `got` (from keys, or from a click):
- an edit action (`command(got.action)` is a command `c`): with `input` not `None`
  and `r = apply(edits[input], c)` not `None`: `Edited(input, r)`. When the input
  does not own `c` (`r` is `None`: "newline" or "up" in a one-line input), for a key
  the table is asked again without the edit keys: `match(bindings, key, now,
  mode=mode, scopes=p)`, whose `Pending` becomes `pending` and is returned, whose
  `Fire` is handled by these rules (an edit action again giving `Passed(key)`), and
  whose `None` gives `Passed(key)` (so enter submits a one-line input, through the
  app's own unscoped "enter"); for a click, nothing more. With no focused input: for
  a key `Passed(key)`, for a click nothing.
- a focus action (`got.action` a 2-tuple `(FOCUS, how)` with `how` one of [Focus]'
  `MOVES`) and `tree` not `None`: `new = move(tree, f, how)`; `Focused(f, new)` and
  `focused = new` when `new != f`, nothing otherwise.
- any other `Fire`: returned as it is.

A `Key`:
1. "release": `(state, ())`: nothing (as `match` does).
2. The prefix layer, a chord pending: when `state.pending` has timed out
   (`expire(bindings, pending, now)` gives a `Miss`), that `Miss` comes first and the
   key goes on as with no chord pending. Otherwise the key belongs to the chord:
   `got = match(bindings, key, now, mode=mode, scopes=sc, pending=pending)`; a
   `Fire` clears `pending` and is handled (above); a `Pending` becomes `pending` and
   is returned; a `Miss` clears `pending` and is returned. Done.
3. The prefix layer, no chord pending: `got = match(bindings, key, now, mode=mode,
   scopes=sc)`. When `got` is a `Pending` (the key starts a chord: a prefix key,
   "ctrl+x") and not both `input` is not `None` and `typed(key)` (a key that types
   text into a focused input never starts a chord: "g" types "g"), `got` becomes
   `pending` and is returned. Done.
4. A focused input owns ordinary keys: when `input` is not `None` and `typed(key)`:
   `Edited(input, keys(edits[input], key))`, whatever the table binds. Done.
5. Bindings: when `got` is a `Fire`, it is handled (above). Done.
6. Bubble's end: `Passed(key)`: nothing owns or binds it.

A `Paste`: never matched against the bindings (pasted text is text, never keys), and
the chord pending is left as it is: with `input` not `None`, `Edited(input,
keys(edits[input], paste))`; else `Passed(paste)`.

A `Mouse` (the chord is left as it is, except by a key hint's click that fires, step 4):
- Captured (`state.capture` is not `None`): `Pointer(event, capture.target,
  captured=True)`, whatever lies under the pointer, wheel steps included. A "release"
  (of any button), or a "move" with no button held (the release was lost), ends the
  capture: `capture` becomes `None`, then hover is updated at the event's position
  as below (`Hovered` after the `Pointer`).
- Not captured: `t = target(event, tree=tree, focused=f, hits=hits, layer=layer)`
  ([Focus]: the hits at or above `layer`, innermost first, and the stop among them).
  In order:
  1. hover: `new = t.hits[0].tag` (or `None` when `t.hits` is empty); when `new !=
     state.hover`: `Hovered(state.hover, new)` and `hover = new` (hover moves);
  2. a "press" of "left", "middle" or "right": focus on click: when `t.stop` is not
     `None` and differs from `f`: `Focused(f, t.stop)` and `focused = t.stop` (a
     tuple id as well: a press on a pane whose hit Paint's `Tiled` tags `("pane",
     id)` focuses the stop `Stop(("pane", id))`, and a press on a Views node focuses
     the stop with that node's id, the innermost such hit first); and
     when `t.hits` is not empty, `capture = Capture(event.button, t)` (the drag that
     follows goes to it). A wheel step neither focuses nor captures;
  3. `Pointer(event, t)` (press fires: the press, not the release, is the click);
  4. a key hint's click: a "press" of "left" whose `t.hits[0].tag` is an action tag,
     a 3-tuple `(owner, "action", a)` (the tag KeyHints writes for a hint). KeyHints
     shows only table entries, so the click fires the table's own: with the focus as
     step 2 left it (`f2`, and `sc2 = scopes(f2, tree=tree, edits=edits)`), the first
     entry of `hints(bindings, mode=mode, scopes=sc2)` whose `action == a`, and its
     first sequence `k` (its `keys` if a `str`, else `keys[0]`, as strokes
     `sequence(k)`). The `Fire` is the one `match` gives for those strokes typed in
     turn at `now` (`key(stroke)` each, from no chord, each `Pending` passed to the
     next): `Fire(a, sequence(k), winner)`, `winner` the table's own `Binding`. It is
     handled (above), after the `Pointer`, and it ends the chord: the resulting
     `pending` is `None`, as when the hint's keys fire (a click on a hint shown after
     a prefix fires that binding and the prefix is done), whatever handling the `Fire`
     gives (an edit no input owns, a focus move that changes nothing). A click never
     expires a timed-out chord first: no `Miss` comes before the `Fire`. The hint's
     tag is known by its shape alone, so a stop whose id has that shape (a 3-tuple
     `(owner, "action", a)`) is also a hint's tag: a press on it focuses it (step 2)
     and fires (this step); an app gives its stops no such id. When no entry has
     action `a` (it is masked, out of mode or scope, or no table entry), nothing
     beyond the `Pointer`, and the chord is left as it is.

Any other event: a `Focus`, `Resize` or `Reply`: `(state, (Passed(event),))`; an
`Unknown`: `(state, ())` (the router ignores it).

`route` reads only its arguments and changes none of them. `TypeError` when `event`
is not one of `EVENTS`, `state` not a `Routing`, `now` not a number (a `bool` is not),
`bindings` not a `Bindings`, `mode` not `None` or a `str`, `tree` not `None` or a
`Group`, `hits` not `None` and without a callable `stack`, `layer` not an `int` (a
`bool` included), `edits` not `None` or a mapping of stop ids (a `str` or a `tuple` of
`str`) to `Edit`s ("edits must map a str or a tuple of str to an Edit"); `ValueError`
as `scopes` gives it; and as `match`, `keys` and `apply` raise.

- `tick(state, now, *, bindings) -> tuple[Routing, tuple[Action, ...]]`: the app's
  loop wakes at [Bindings]' `deadline(bindings, state.pending)` and calls it: when the
  pending chord has timed out (`expire` gives a `Miss`): `(state with pending None,
  (miss,))`; else `(state, ())`. `TypeError` when `state` is not a `Routing`, `now`
  not a number, `bindings` not a `Bindings`.

Laws (a test can loop over events and states):
- `route` is pure: the same arguments give equal results, and the arguments are
  unchanged.
- a `Paste` never yields a `Fire`, `Pending` or `Miss`, and leaves `pending` as it was.
- with `edits` holding the focused stop, a typed key with no chord pending yields
  exactly `(Edited(f, keys(edits[f], key)),)`, whatever `bindings` holds.
- no returned `Fire` carries a focus or edit action.
- a key yields at most one action besides a leading timed-out `Miss`.
- with no focused input, the edit keys are inactive: `scopes` holds no `EDIT_SCOPE`,
  so an arrow reaches the app's own bindings (a list's).
- `Focused(old, new)` always has `old != new` and `new` is the returned
  `Routing.focused`; `Hovered(old, new)` has `old != new` and `new` the returned
  `hover`.
- after a non-wheel press that hit a region, every mouse event up to and including
  the next "release" (or "move" with no button) yields a `Pointer` with
  `captured=True` and the press's target, and the events after it are not captured.
- a hint's click and its keys fire equal `Fire`s, for the same state, and both leave
  `pending` `None`.
- ids are carried unchanged: `Routing.focused`, `Focused`'s `old` / `new` and
  `Edited.stop` are `None` or `==` (and of the same type as) an id of `tree`, a key of
  `edits` or the `focused` given.
- str ids unchanged: with a tree, edits and bindings whose ids and scopes are all `str`
  and a `focused` that is `None` or a `str`, `route`, `tick` and `scopes` give the
  results they gave before tuple ids were allowed (the str-only tests pass
  unchanged); renaming the ids one to one (in the tree, the hit tags that name stops,
  `edits`, the bindings' scopes and `focused` alike) commutes with `route`.

Inputs: [Events]' events, the app's `now`, mode, its one [Bindings] table, [Focus]
tree, {HitMap} and layer, and its [Edit] values. Outputs: a `Routing` and {Actions}.
Errors: as stated. Effects: none.

Usage:
    from cure.core.geometry import HitMap, Rect
    from cure.interact.input.bindings import Binding, Bindings, Fire, Pending
    from cure.interact.input.edit import EDIT_BINDINGS, Edit
    from cure.interact.input.events import Key, Mouse, Paste, key
    from cure.interact.input.focus import FOCUS_BINDINGS, Group, Stop
    from cure.interact.input.router import Routing, Edited, Focused, Passed, route, scopes
    table = Bindings(default=FOCUS_BINDINGS + EDIT_BINDINGS + (
        Binding("q", "quit", "quit"), Binding("enter", "submit", "submit"),
        Binding("ctrl+x ctrl+s", "save", "save")))
    tree = Group("screen", (Stop("search", Rect(0, 0, 20, 1)), Stop("list", Rect(0, 1, 20, 9))))
    edits = {"search": Edit("")}
    s = Routing(focused="list")
    route(key("q"), s, 0.0, bindings=table, tree=tree, edits=edits)[1]
    # (Fire("quit", ("q",), Binding("q", "quit", "quit")),)
    s, acts = route(key("tab"), s, 0.0, bindings=table, tree=tree, edits=edits)
    acts, s.focused                  # ((Focused("list", "search"),), "search")
    route(key("q"), s, 0.0, bindings=table, tree=tree, edits=edits)[1]
    # (Edited("search", Edit("q", ...)),): the focused input owns "q"
    route(key("left"), s, 0.0, bindings=table, tree=tree, edits=edits)[1]
    # (Edited("search", Edit("")),): ("edit", "left") from the table, applied
    route(key("enter"), s, 0.0, bindings=table, tree=tree, edits=edits)[1]
    # (Fire("submit", ("enter",), Binding("enter", "submit", "submit")),): one line
    route(key("ctrl+x"), s, 1.0, bindings=table, tree=tree, edits=edits)[1]
    # (Pending(("ctrl+x",), 1.0),): the chord beats the input
    route(Paste("a b"), s, 0.0, bindings=table, tree=tree, edits=edits)[1]
    # (Edited("search", Edit("a b", ...)),)
    route(key("f5"), s, 0.0, bindings=table, tree=tree, edits=edits)[1]
    # (Passed(Key("f5")),)
    hits = (HitMap().add(Rect(0, 0, 20, 1), "search").add(Rect(0, 1, 20, 9), "list")
            .add(Rect(0, 10, 6, 1), ("k", "action", "quit")))
    s, acts = route(Mouse("left", "press", 3, 4), s, 0.0, bindings=table, tree=tree, hits=hits)
    [type(a).__name__ for a in acts]  # ["Hovered", "Focused", "Pointer"]
    s.focused, s.capture.button       # ("list", "left")
    _, acts = route(Mouse("left", "press", 1, 10), Routing(), 0.0, bindings=table, tree=tree,
                    hits=hits)
    acts[-1]                          # Fire("quit", ("q",), Binding("q", "quit", "quit"))
    panes = Group("screen", (Stop(("pane", "dag"), Rect(0, 0, 40, 20)),
                             Stop(("pane", "tasks"), Rect(40, 0, 40, 20))))
    tiled = HitMap().add(Rect(0, 0, 40, 20), ("pane", "dag")).add(Rect(40, 0, 40, 20),
                                                                   ("pane", "tasks"))
    own = Bindings(default=(Binding("home", "origin", scope=("pane", "tasks")),))
    s, acts = route(Mouse("left", "press", 50, 3), Routing(focused=("pane", "dag")), 0.0,
                    bindings=own, tree=panes, hits=tiled)
    s.focused                         # ("pane", "tasks"): focus on click, a tuple id
    scopes(s.focused, tree=panes)     # (("pane", "tasks"), "screen")
    route(key("home"), s, 0.0, bindings=own, tree=panes)[1]
    # (Fire("origin", ("home",), Binding("home", "origin", scope=("pane", "tasks"))),)
"""

from collections.abc import Hashable, Mapping
from dataclasses import dataclass

from cure.interact.vt.encode import BUTTONS

from .bindings import Bindings, Fire, Miss, Pending, expire, hints, match, sequence
from .edit import EDIT_SCOPE, Edit  # noqa: F401 (the reserved scope: see the module)
from .edit import apply, command, keys, typed
from .events import EVENTS, Event, Focus, Key, Mouse, Paste, Reply, Resize, key
from .focus import FOCUS, MOVES, Group, Target, move, path, target
from .focus import Id, is_id  # a focus id: a str or a tuple of str (see [Focus])


_HELD = frozenset(b for b in BUTTONS if not b.startswith("wheel_"))
_CLICK = frozenset({"left", "middle", "right"})


@dataclass(frozen=True)
class Capture:
    """A drag in progress: the button pressed and the target it was pressed on."""

    button: str
    target: Target

    def __post_init__(self) -> None:
        if not isinstance(self.button, str):
            raise TypeError(f"Capture.button must be a str, got {type(self.button).__name__}")
        if not isinstance(self.target, Target):
            raise TypeError(f"Capture.target must be a Target, got {type(self.target).__name__}")
        if self.button not in _HELD:
            raise ValueError(f"Capture.button must be a held button, got {self.button!r}")


@dataclass(frozen=True)
class Routing:
    """The router's own state, kept by the app: focus, the pending chord, a capture, hover."""

    focused: "Id | None" = None
    pending: "Pending | None" = None
    capture: "Capture | None" = None
    hover: "Hashable | None" = None

    def __post_init__(self) -> None:
        if self.focused is not None and not is_id(self.focused):
            raise TypeError(f"Routing.focused must be None, a str or a tuple of str,"
                            f" got {type(self.focused).__name__}")
        if self.pending is not None and not isinstance(self.pending, Pending):
            raise TypeError(f"Routing.pending must be None or a Pending, got {type(self.pending).__name__}")
        if self.capture is not None and not isinstance(self.capture, Capture):
            raise TypeError(f"Routing.capture must be None or a Capture, got {type(self.capture).__name__}")
        try:
            hash(self.hover)
        except TypeError:
            raise TypeError(f"Routing.hover must be hashable, got {type(self.hover).__name__}") from None


@dataclass(frozen=True)
class Edited:
    """The focused input's new edit value."""

    stop: "Id"
    edit: Edit


@dataclass(frozen=True)
class Focused:
    """Focus roved from `old` to `new`."""

    old: "Id | None"
    new: "Id | None"


@dataclass(frozen=True)
class Hovered:
    """The tag under the pointer changed from `old` to `new`."""

    old: "Hashable | None"
    new: "Hashable | None"


@dataclass(frozen=True)
class Pointer:
    """A mouse event delivered to its target (through a drag's capture or not)."""

    event: Mouse
    target: Target
    captured: bool = False


@dataclass(frozen=True)
class Passed:
    """An event the router delivers to nothing: the app's, or a pane's."""

    event: Event


ACTIONS = (Fire, Pending, Miss, Edited, Focused, Hovered, Pointer, Passed)

Action = Fire | Pending | Miss | Edited | Focused | Hovered | Pointer | Passed


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _number(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number, got {type(value).__name__}")


def _check_scope_args(focused: object, tree: object, edits: object) -> None:
    if focused is not None and not is_id(focused):
        raise TypeError(f"focused must be None, a str or a tuple of str,"
                        f" got {type(focused).__name__}")
    if tree is not None and not isinstance(tree, Group):
        raise TypeError(f"tree must be None or a Group, got {type(tree).__name__}")
    if edits is not None and not isinstance(edits, Mapping):
        raise TypeError(f"edits must be None or a mapping, got {type(edits).__name__}")


def _scopes(focused: "Id | None", tree: "Group | None", edits: "Mapping | None"
            ) -> "tuple[tuple[Id, ...], tuple[Id, ...]]":
    """(path, scopes) for a focus, its arguments checked."""
    p = () if tree is None or focused is None else path(tree, focused)
    if EDIT_SCOPE in p:                # by ==: a tuple id is never the str EDIT_SCOPE
        raise ValueError(f"the focus tree uses the reserved id {EDIT_SCOPE!r}")
    if edits is not None and focused is not None and focused in edits:
        return p, ((p[0], EDIT_SCOPE) + p[1:] if p else (EDIT_SCOPE,))
    return p, p


def scopes(focused: "Id | None", *, tree: "Group | None" = None,
           edits: "Mapping[Id, Edit] | None" = None) -> "tuple[Id, ...]":
    """The bindings scopes for a focus: its focus chain, with EDIT_SCOPE in an input (see the module)."""
    _check_scope_args(focused, tree, edits)
    return _scopes(focused, tree, edits)[1]


def _focus_how(action: object) -> "str | None":
    if (isinstance(action, tuple) and len(action) == 2 and action[0] == FOCUS
            and isinstance(action[1], str) and action[1] in MOVES):
        return action[1]
    return None


class _Call:
    """One route call's arguments and the state it builds (private, never returned)."""

    __slots__ = ("now", "bindings", "mode", "tree", "hits", "layer", "edits", "focused",
                 "pending", "capture", "hover", "out")

    def __init__(self, state, now, bindings, mode, tree, hits, layer, edits):
        self.now, self.bindings, self.mode = now, bindings, mode
        self.tree, self.hits, self.layer, self.edits = tree, hits, layer, edits
        self.focused, self.pending = state.focused, state.pending
        self.capture, self.hover = state.capture, state.hover
        self.out: list = []

    def input(self) -> "Id | None":
        f = self.focused
        return f if f is not None and self.edits is not None and f in self.edits else None

    def fire(self, got: Fire, ev: "Key | None") -> None:
        """Handle a Fire from a key (`ev`) or from a click (`ev` None)."""
        c = command(got.action)
        if c is not None:
            inp = self.input()
            if inp is not None:
                r = apply(self.edits[inp], c)
                if r is not None:
                    self.out.append(Edited(inp, r))
                    return
                if ev is None:
                    return
                p = _scopes(self.focused, self.tree, self.edits)[0]
                again = match(self.bindings, ev, self.now, mode=self.mode, scopes=p)
                if isinstance(again, Pending):
                    self.pending = again
                    self.out.append(again)
                elif isinstance(again, Fire) and command(again.action) is None:
                    self.fire(again, ev)
                else:
                    self.out.append(Passed(ev))
                return
            if ev is not None:
                self.out.append(Passed(ev))
            return
        how = _focus_how(got.action)
        if how is not None:
            if self.tree is not None:
                new = move(self.tree, self.focused, how)
                if new != self.focused:
                    self.out.append(Focused(self.focused, new))
                    self.focused = new
            return
        self.out.append(got)

    def key(self, ev: Key) -> None:
        if ev.event == "release":
            return
        b, now, mode = self.bindings, self.now, self.mode
        sc = _scopes(self.focused, self.tree, self.edits)[1]
        if self.pending is not None:
            gone = expire(b, self.pending, now)
            if isinstance(gone, Miss):
                self.out.append(gone)
                self.pending = None
            else:
                got = match(b, ev, now, mode=mode, scopes=sc, pending=self.pending)
                if isinstance(got, Fire):
                    self.pending = None
                    self.fire(got, ev)
                elif isinstance(got, Pending):
                    self.pending = got
                    self.out.append(got)
                else:
                    self.pending = None
                    self.out.append(got)
                return
        got = match(b, ev, now, mode=mode, scopes=sc)
        inp = self.input()
        owned = inp is not None and typed(ev)
        if isinstance(got, Pending) and not owned:
            self.pending = got
            self.out.append(got)
        elif owned:
            self.out.append(Edited(inp, keys(self.edits[inp], ev)))
        elif isinstance(got, Fire):
            self.fire(got, ev)
        else:
            self.out.append(Passed(ev))

    def paste(self, ev: Paste) -> None:
        inp = self.input()
        if inp is not None:
            self.out.append(Edited(inp, keys(self.edits[inp], ev)))
        else:
            self.out.append(Passed(ev))

    def aim(self, ev: Mouse) -> Target:
        return target(ev, tree=self.tree, focused=self.focused, hits=self.hits, layer=self.layer)

    def hovered(self, t: Target) -> None:
        new = t.hits[0].tag if t.hits else None
        if new != self.hover:
            self.out.append(Hovered(self.hover, new))
            self.hover = new

    def mouse(self, ev: Mouse) -> None:
        cap = self.capture
        if cap is not None:
            self.out.append(Pointer(ev, cap.target, captured=True))
            if ev.kind == "release" or (ev.kind == "move" and ev.button is None):
                self.capture = None
                self.hovered(self.aim(ev))
            return
        t = self.aim(ev)
        self.hovered(t)
        press = ev.kind == "press"
        if press and ev.button in _CLICK:
            if t.stop is not None and t.stop != self.focused:
                self.out.append(Focused(self.focused, t.stop))
                self.focused = t.stop
            if t.hits:
                self.capture = Capture(ev.button, t)
        self.out.append(Pointer(ev, t))
        if press and ev.button == "left" and t.hits:
            tag = t.hits[0].tag
            if isinstance(tag, tuple) and len(tag) == 3 and tag[1] == "action":
                self.hint(tag[2])

    def hint(self, a: object) -> None:
        """A key hint's click: the table's own Fire for its first sequence; the chord ends."""
        sc2 = _scopes(self.focused, self.tree, self.edits)[1]
        b, mode = self.bindings, self.mode
        for entry in hints(b, mode=mode, scopes=sc2):
            if entry.action == a:
                break
        else:
            return
        k = entry.keys if isinstance(entry.keys, str) else entry.keys[0]
        got = None
        for one in sequence(k):
            got = match(b, key(one), self.now, mode=mode, scopes=sc2, pending=got)
            if not isinstance(got, Pending):
                break
        if isinstance(got, Fire):
            self.pending = None
            self.fire(got, None)

    def result(self) -> "tuple[Routing, tuple[Action, ...]]":
        return (Routing(self.focused, self.pending, self.capture, self.hover), tuple(self.out))


def _check_edits(edits: object) -> None:
    if edits is None:
        return
    if not isinstance(edits, Mapping):
        raise TypeError(f"edits must be None or a mapping, got {type(edits).__name__}")
    for k, v in edits.items():
        if not is_id(k) or not isinstance(v, Edit):
            raise TypeError("edits must map a str or a tuple of str to an Edit")


def route(event: Event, state: Routing, now: "float | int", *, bindings: Bindings,
          mode: "str | None" = None, tree: "Group | None" = None, hits: object = None,
          layer: int = 0, edits: "Mapping[Id, Edit] | None" = None
          ) -> "tuple[Routing, tuple[Action, ...]]":
    """One event routed: the next Routing and the actions, in order (see the module)."""
    if not isinstance(event, EVENTS):
        raise TypeError(f"event must be one of EVENTS, got {type(event).__name__}")
    if not isinstance(state, Routing):
        raise TypeError(f"state must be a Routing, got {type(state).__name__}")
    _number(now, "now")
    if not isinstance(bindings, Bindings):
        raise TypeError(f"bindings must be a Bindings, got {type(bindings).__name__}")
    if mode is not None and not isinstance(mode, str):
        raise TypeError(f"mode must be None or a str, got {type(mode).__name__}")
    if tree is not None and not isinstance(tree, Group):
        raise TypeError(f"tree must be None or a Group, got {type(tree).__name__}")
    if hits is not None and not callable(getattr(hits, "stack", None)):
        raise TypeError(f"hits must be None or have a callable stack, got {type(hits).__name__}")
    if not _is_int(layer):
        raise TypeError(f"layer must be an int, got {type(layer).__name__}")
    _check_edits(edits)
    _scopes(state.focused, tree, edits)          # the reserved id, whatever the event
    if isinstance(event, (Focus, Resize, Reply)):
        return state, (Passed(event),)
    if not isinstance(event, (Key, Paste, Mouse)):
        return state, ()
    call = _Call(state, now, bindings, mode, tree, hits, layer, edits)
    if isinstance(event, Key):
        call.key(event)
    elif isinstance(event, Paste):
        call.paste(event)
    else:
        call.mouse(event)
    if not call.out and call.focused == state.focused and call.pending is state.pending \
            and call.capture is state.capture and call.hover == state.hover:
        return state, ()
    return call.result()


def tick(state: Routing, now: "float | int", *, bindings: Bindings
         ) -> "tuple[Routing, tuple[Action, ...]]":
    """A pending chord's timeout, at the deadline the app's loop wakes for (see the module)."""
    if not isinstance(state, Routing):
        raise TypeError(f"state must be a Routing, got {type(state).__name__}")
    _number(now, "now")
    if not isinstance(bindings, Bindings):
        raise TypeError(f"bindings must be a Bindings, got {type(bindings).__name__}")
    if state.pending is None:
        return state, ()
    got = expire(bindings, state.pending, now)
    if isinstance(got, Miss):
        return Routing(state.focused, None, state.capture, state.hover), (got,)
    return state, ()
