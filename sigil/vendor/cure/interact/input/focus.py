"""[Focus]: ring, scopes, traps, spatial moves; rove != commit != fire; hover moves, press fires.

Kind: service (the focus tree the app describes, `Stop` and `Group`, the `Target` an
event is aimed at, and the pure ops that read them); pure. The app keeps the focused
id (in the Router's `Routing`, or itself); every op here takes it as an argument and
returns the new one, so nothing here holds state between calls.

Focus only roves: it moves which stop is focused. Committing a choice (enter on a list
row) and firing an action are the app's bindings' actions, three separate steps
(Rules carried over); no op here commits or fires. Hover follows the pointer and a
press fires (the Router's `Hovered` and `Pointer`); a press also focuses the stop it
lands on (focus on click, `target`).

It provides `target` for the Router (`[Router] -> [Focus] : target({Event}) =>
{Target}`): which stop, focus path and hit regions an event is aimed at, the mouse by
the {HitMap} it is given.

## The focus tree

The app describes what can take focus each frame, as a tree of plain values (like the
HitMap, a value the app builds and passes in; nothing keeps it):

A focus id (the id of a stop or a group) is either a non-empty `str` ("ok") or a
non-empty `tuple` of non-empty `str` (`("pane", "dag")`, `("overview", "tasks")`: the
tuple ids Views' nodes carry and the `("pane", id)` tags Paint's `Tiled` writes for
its panes, so an app focuses those by the very tags the frame's HitMap holds). Ids are
compared by `==` and nothing else: a `str` id and a tuple id are never equal (`"a"`
and `("a",)` are two ids), and every op carries an id it is given or returns
unchanged (never joined, split or converted). A tree of `str` ids only behaves exactly
as it would with no tuple ids allowed.

- `Id`: the type of a focus id, `str | tuple[str, ...]` (a type alias for
  annotations; the emptiness rules above are checked by `Stop` / `Group`, not by the
  type).
- `is_id(value) -> bool`: whether `value` has a focus id's type: a `str` (a subclass
  included), or a `tuple` (a subclass included) whose items are all `str`; emptiness
  aside (`is_id("")`, `is_id(())` and `is_id(("a", ""))` are True). It reads a
  tuple's items by type only, so a value that is no id is never compared by `==`.
  Never raises; any value is a valid argument. This is the check behind every
  "must be a str or a tuple of str" `TypeError` here and in [Router]: [Router] imports
  `Id` and `is_id` (not the private `_Id` / `_is_id`, which stay as this module's own
  spelling of the same thing).

- `Stop(id, rect=None)` (frozen dataclass): one focusable thing (a button, an input, a
  list). `id`: a focus id, the same id the app writes as the stop's tag in the HitMap
  (so a click finds it) and that its bindings name as a `scope` ([Bindings] takes
  the same id type for a scope). `rect`: `None` or the stop's rect on screen, a Core
  `Rect` or any object with `int` attributes `x`, `y`, `w`, `h` (read by attribute,
  never imported: duck typed); only spatial moves read it. `TypeError` when `id` is
  neither a `str` nor a `tuple` of `str` ("Stop.id must be a str or a tuple of str,
  got <type>") or `rect` is neither `None` nor such an object (an attribute missing,
  or not an `int`, a `bool` included); `ValueError` when `id` is `""` or `()` ("Stop.id
  must not be empty") or a tuple holding `""` ("Stop.id must not hold an empty str").
- `Group(id, children=(), *, trap=False)` (frozen dataclass): a scope: a panel, a
  form, a dialog, the screen. `id`: a focus id (a bindings `scope`, like a stop's).
  `children`: any iterable of `Stop` and `Group`, held as a tuple, in tab order.
  `trap`: a `bool`; a trapped group keeps focus inside it (see "Traps"). `TypeError`
  when `id` is neither a `str` nor a `tuple` of `str` ("Group.id must be a str or a
  tuple of str, got <type>"), `children` is not iterable (or is a `str`) or holds
  anything but a `Stop` or `Group`, `trap` is not a `bool`; `ValueError` when `id` is
  `""` or `()` ("Group.id must not be empty") or a tuple holding `""` ("Group.id must
  not hold an empty str"), or two nodes of the subtree (the group itself included)
  share an id.
  The tree passed to every op is a `Group`, the root (the screen); the root's own
  `trap` flag plays no part (the root bounds every move anyway).

Equality is by value, field by field; both are hashable when their rects are.

A focused id passed to an op (`path`'s `id`; `ring`'s, `move`'s, `heal`'s and
`target`'s `focused`) is checked by its type only: `None`, a `str` or a `tuple` of
`str` (an empty one, or one no node has, is simply an id of no node, as `""` is);
anything else is a `TypeError`, "focused must be None, a str or a tuple of str, got
<type>".

- `stops(tree) -> tuple[Stop, ...]`: every stop of the tree in tab order: depth-first,
  each group's children in order (a group's stops where the group stands).
- `path(tree, id) -> tuple[str | tuple[str, ...], ...]`: the focus chain of the node
  with that id (a stop or a group), innermost first: its own id, then each enclosing
  group's id, the root's last, each id as the tree holds it (a tuple id stays one item
  of the chain). This is the `scopes` a [Bindings] query takes (a focused widget's own
  bindings, its ancestors', the screen's), tuple ids included. `()` when `id` is
  `None` or no node of the tree has it (a removed widget).

## Traps

The active scope of a focus is the group moves stay inside:
- when `focused` is the id of a stop of the tree: the innermost group with `trap`
  True that contains it, or the root when none does;
- otherwise (`None`, an id no stop has, or a group's id): the first group with `trap`
  True in depth-first pre-order (a dialog just opened: the first Tab lands in it), or
  the root when there is none.
- `ring(tree, focused) -> tuple[Stop, ...]`: `stops(active scope)`, the stops focus
  may move among from `focused`. `next` / `prev` wrap inside it; spatial moves and
  focus on click never leave it; nothing here moves focus out of a trap (the app
  does, by changing the tree: closing the dialog).

## Moves

`MOVES = ("next", "prev", "first", "last", "up", "down", "left", "right")`.

- `move(tree, focused, how) -> str | tuple[str, ...] | None`: the stop focused after
  the move `how`, from `focused` (the app's focused id, `None` for none). With `R =
  ring(tree, focused)`:
  1. `R` empty: `focused`, unchanged.
  2. `focused` not the id of a stop in `R` (`None`, removed, a group's id): `R[-1].id`
     for "prev" and "last", `R[0].id` for every other move.
  3. "next": the stop after `focused` in `R`, wrapping (`R[(i + 1) % len(R)]`);
     "prev": the one before, wrapping; "first": `R[0].id`; "last": `R[-1].id`.
  4. "up", "down", "left", "right" (spatial; they never wrap): from the focused stop's
     rect `f`. When `f` is `None` or empty (`w` or `h` 0): `focused`, unchanged. The
     candidates are the other stops of `R` with a non-empty rect `c` lying wholly on
     that side of `f`: "right" `c.x >= f.x + f.w`; "left" `c.x + c.w <= f.x`; "down"
     `c.y >= f.y + f.h`; "up" `c.y + c.h <= f.y`. Each is ranked by
     `(cross, gap, index)`, smallest first, and the first wins:
     - `gap`, the distance along the move: "right" `c.x - (f.x + f.w)`, "left"
       `f.x - (c.x + c.w)`, "down" `c.y - (f.y + f.h)`, "up" `f.y - (c.y + c.h)`;
     - `cross`, how far apart they are across it: for "left" / "right" over the rows
       `[f.y, f.y + f.h)` and `[c.y, c.y + c.h)`, for "up" / "down" over the columns
       `[f.x, f.x + f.w)` and `[c.x, c.x + c.w)`, `max(0, max(a0, b0) - min(a1, b1) +
       1)` for the half-open ranges `[a0, a1)`, `[b0, b1)`: 0 when they overlap, 1
       when they only touch, more the further apart (so a stop in line wins over a
       nearer one off to the side);
     - `index`: its position in `R` (tab order breaks ties).
     No candidate: `focused`, unchanged.
  `move` only roves: it never commits or fires. `TypeError` when `tree` is not a
  `Group`, `focused` not `None`, a `str` or a `tuple` of `str`, `how` not a `str`;
  `ValueError` when `how` is not one of `MOVES`.
- `heal(old, new, focused) -> str | tuple[str, ...] | None`: where focus goes when the
  tree changes (a removed widget): `focused` when it is the id of a stop of `new`; else,
  when it was a stop of `old`, the first stop after it in `stops(old)` whose id is a
  stop of `new`, else the last one before it that is; else `stops(new)[0].id`; `None`
  when `new` has no stop. `TypeError` when `old` or `new` is not a `Group` or `focused`
  not `None`, a `str` or a `tuple` of `str`.

Focus actions in the one bindings table: a binding whose action is `(FOCUS, how)`
(`FOCUS = "focus"`, `how` one of `MOVES`) moves focus; the Router applies it with
`move` (see [Router]). `FOCUS_BINDINGS` are the usual ones, for an app's default
layer: `(Binding("tab", ("focus", "next"), "next", group="focus", hidden=True),
Binding("shift+tab", ("focus", "prev"), "previous", group="focus", hidden=True))`.
Spatial moves are not bound by default (the arrows belong to lists and inputs); an
app binds them itself, e.g. `Binding("alt+right", ("focus", "right"))`.

## Targets

- `Target(stop=None, path=(), hits=())` (frozen dataclass): what an event is aimed
  at. `stop`: the focusable stop's id (a focus id, as the tree holds it), or `None`;
  `path`: `path(tree, stop)` (`()` when `stop` is `None`); `hits`: for a mouse event,
  the hit regions under the pointer that receive input, innermost first (the HitMap's
  own `Hit` values, as its `stack` gives them), the stack the app bubbles a click
  through; `()` otherwise.
- `target(event, *, tree=None, focused=None, hits=None, layer=0) -> Target`:
  - a `Key` or `Paste`: aimed at the focus: `Target(f, path(tree, f), ())` with `f =
    focused` when it is the id of a stop of `tree`, else `Target()`;
  - a `Mouse`: `hits.stack(event.x, event.y)` (the HitMap's precedence order:
    highest layer first, then the smallest rect, then the later added), keeping only
    the hits whose `layer >= layer` (modal capture: the regions of the screens under
    the input screen receive no mouse input). `stop` is the first kept hit's tag (in
    that order) that is the id of a stop in `ring(tree, focused)` (focus on click
    stays inside the trap; a tag that is neither a `str` nor a `tuple` of `str` is
    never a stop, and is never compared with one: a tag `("pane", "dag")` is the stop
    `Stop(("pane", "dag"))`, a tag `("pane", 3)` no stop); `path` its `path`; `hits`
    the kept hits. With `hits` `None`: `Target()`;
  - any other event: `Target()`.
  `hits`: `None` or a {HitMap}, read only through `stack(x, y)` (each hit's `tag` and
  `layer` by attribute; duck typed, never imported). `TypeError` when `event` is not
  one of [Events]' `EVENTS`, `tree` not `None` or a `Group`, `focused` not `None`, a
  `str` or a `tuple` of `str`, `hits` not `None` and without a callable `stack`,
  `layer` not an `int` (a `bool` included).

Laws (for any tree `t` in which no trapped group lies inside another, and any focused
id `f`; a test can loop over them):
- `move(t, f, how)` is `None` only when `ring(t, f)` is empty and `f` is `None`;
  otherwise it is `f` or the id of a stop in `ring(t, f)`.
- in a tree with no trapped group (from outside a trap, "next" may enter it and then
  stays inside, so these three hold only without traps):
  - for a stop `s` of `ring(t, f)`, `ring(t, s.id) == ring(t, f)` when `f` is also a
    stop of it (moves never leave the active scope);
  - `move(t, move(t, s, "next"), "prev") == s` for every stop id `s` of the tree;
  - cycling: applying "next" `len(ring(t, s))` times from a stop id `s` gives `s`.
- `path(t, s.id)[0] == s.id` and `path(t, s.id)[-1] == t.id` for every stop `s`.
- `heal(t, t, s) == s` for every stop id `s` of `t`; `heal(old, new, f)` is `None` or
  the id of a stop of `new`.
- ids are carried unchanged: every id `move`, `heal`, `path` and `target` return is
  `==` (and of the same type as) the id of a node of the tree they were given, or the
  `focused` they were given.
- str ids unchanged: for a tree whose ids are all `str` and a `focused` that is `None`
  or a `str`, every op gives the result it gave before tuple ids were allowed (the
  str-only tests pass unchanged), and a tuple-id tree behaves as the str-id tree got
  by renaming each id one to one (`move`, `ring`, `path`, `heal`, `target` commute
  with the renaming; a tag is renamed with the stop it names).

Inputs: the focus tree (`Group`, `Stop`), the focused id (a focus id or `None`),
[Events]' events, a HitMap and a layer. Outputs: a stop id (or `None`), a chain of
ids, a `Target`. Errors: as stated. Effects: none.

Usage:
    from cure.core.geometry import HitMap, Rect
    from cure.interact.input.events import Key, Mouse
    from cure.interact.input.focus import Group, Stop, stops, path, move, heal, target
    tree = Group("screen", (
        Group("form", (Stop("name", Rect(0, 0, 10, 1)), Stop("email", Rect(0, 2, 10, 1)))),
        Stop("ok", Rect(12, 2, 4, 1))))
    [s.id for s in stops(tree)]        # ["name", "email", "ok"]
    path(tree, "email")                # ("email", "form", "screen")
    move(tree, "email", "next")        # "ok"
    move(tree, "ok", "next")           # "name": it wraps
    move(tree, None, "prev")           # "ok"
    move(tree, "ok", "left")           # "email": in line beats "name" (cross 2)
    move(tree, "name", "up")           # "name": nothing above
    heal(tree, Group("screen", (Stop("name"), Stop("ok"))), "email")   # "ok"
    dialog = Group("screen", (Stop("a"), Group("ask", (Stop("yes"), Stop("no")), trap=True)))
    move(dialog, None, "next")         # "yes": the first trap
    move(dialog, "no", "next")         # "yes": it never leaves the trap
    hits = HitMap().add(Rect(0, 0, 20, 3), "form").add(Rect(12, 2, 4, 1), "ok")
    target(Mouse("left", "press", 13, 2), tree=tree, hits=hits).stop   # "ok"
    target(Mouse("left", "press", 1, 1), tree=tree, hits=hits).stop    # None: "form" is no stop
    target(Key("x", text="x"), tree=tree, focused="name").path         # ("name", "form", "screen")
    panes = Group("screen", (Stop(("pane", "dag"), Rect(0, 0, 40, 20)),
                             Stop(("pane", "tasks"), Rect(40, 0, 40, 20))))
    move(panes, ("pane", "dag"), "right")      # ("pane", "tasks")
    path(panes, ("pane", "tasks"))             # (("pane", "tasks"), "screen")
    tiled = HitMap().add(Rect(40, 0, 40, 20), ("pane", "tasks"))   # as Paint's Tiled tags it
    target(Mouse("left", "press", 50, 3), tree=panes, hits=tiled).stop   # ("pane", "tasks")
"""

from dataclasses import dataclass

from .bindings import Binding
from .events import EVENTS, Event, Key, Mouse, Paste

FOCUS = "focus"

MOVES = ("next", "prev", "first", "last", "up", "down", "left", "right")

FOCUS_BINDINGS = (
    Binding("tab", (FOCUS, "next"), "next", group="focus", hidden=True),
    Binding("shift+tab", (FOCUS, "prev"), "previous", group="focus", hidden=True),
)

# A focus id: a non-empty str or a non-empty tuple of non-empty str (see the module)
_Id = str | tuple[str, ...]

_SPATIAL = frozenset({"up", "down", "left", "right"})


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_id(value: object) -> bool:
    """A focus id's type: a str, or a tuple whose items are all str (emptiness aside).
    It reads a tuple's items by type only, so a value that is no id is never compared."""
    return isinstance(value, str) or (isinstance(value, tuple)
                                      and all(isinstance(v, str) for v in value))


Id = _Id
"""A focus id's type, `str | tuple[str, ...]` (see the module)."""


def is_id(value: object) -> bool:
    """Whether `value` has a focus id's type (see the module); never raises. Stub (Q9a):
    the implementer makes it `_is_id(value)`."""
    return _is_id(value)


def _check_id(value: object, owner: str) -> None:
    """A node's id: a focus id's type (the TypeError half; `_check_empty` the rest)."""
    if not _is_id(value):
        raise TypeError(f"{owner}.id must be a str or a tuple of str, got {type(value).__name__}")


def _check_empty(value: "_Id", owner: str) -> None:
    if value == "" or value == ():
        raise ValueError(f"{owner}.id must not be empty")
    if isinstance(value, tuple) and "" in value:
        raise ValueError(f"{owner}.id must not hold an empty str")


def _check_rect(rect: object) -> None:
    if rect is None:
        return
    for name in ("x", "y", "w", "h"):
        if not _is_int(getattr(rect, name, None)):
            raise TypeError(f"Stop.rect must be None or have int x, y, w, h (bad {name!r})")


@dataclass(frozen=True)
class Stop:
    """One focusable thing: its id (its HitMap tag and bindings scope) and its rect, or None."""

    id: "_Id"
    rect: object = None

    def __post_init__(self) -> None:
        _check_id(self.id, "Stop")
        _check_rect(self.rect)
        _check_empty(self.id, "Stop")


@dataclass(frozen=True)
class Group:
    """A focus scope: its id, its children in tab order, and whether it traps focus."""

    id: "_Id"
    children: "tuple[Stop | Group, ...]" = ()
    trap: bool = False

    def __post_init__(self) -> None:
        _check_id(self.id, "Group")
        children = self.children
        if isinstance(children, str):
            raise TypeError("Group.children must be an iterable of Stop and Group, not a str")
        try:
            children = tuple(children)
        except TypeError:
            raise TypeError("Group.children must be an iterable of Stop and Group") from None
        for c in children:
            if not isinstance(c, (Stop, Group)):
                raise TypeError(f"Group.children holds a {type(c).__name__}, not a Stop or Group")
        if type(self.trap) is not bool:
            raise TypeError("Group.trap must be a bool")
        _check_empty(self.id, "Group")
        object.__setattr__(self, "children", children)
        ids = {self.id}
        count = 1
        for c in children:
            sub = c._ids if isinstance(c, Group) else (c.id,)
            ids.update(sub)
            count += len(sub)
        if len(ids) != count:
            raise ValueError(f"two nodes of group {self.id!r} share an id")
        object.__setattr__(self, "_ids", frozenset(ids))


@dataclass(frozen=True)
class Target:
    """What an event is aimed at: the stop, its focus path, the hits under the pointer."""

    stop: "_Id | None" = None
    path: "tuple[_Id, ...]" = ()
    hits: "tuple[object, ...]" = ()


class _Index:
    """A tree's derived tables: stops in tab order, paths, groups, the stop ids."""

    __slots__ = ("stops", "paths", "groups", "stop_ids", "first_trap", "rings")

    def __init__(self, tree: Group) -> None:
        stops: list = []
        paths: dict = {}
        groups: dict = {}
        first_trap: list = []

        def walk(node, chain):
            chain = (node.id,) + chain
            paths[node.id] = chain
            if isinstance(node, Stop):
                stops.append(node)
                return
            groups[node.id] = node
            if node.trap and node is not tree and not first_trap:
                first_trap.append(node)
            for c in node.children:
                walk(c, chain)

        walk(tree, ())
        self.stops = tuple(stops)
        self.paths = paths
        self.groups = groups
        self.stop_ids = frozenset(s.id for s in stops)
        self.first_trap = first_trap[0] if first_trap else tree
        self.rings: dict = {}          # active scope id -> (ring, {id: index})


def _index(tree: Group) -> _Index:
    got = tree.__dict__.get("_index")
    if got is None:
        got = _Index(tree)
        object.__setattr__(tree, "_index", got)
    return got


def _tree(tree: object) -> None:
    if not isinstance(tree, Group):
        raise TypeError(f"tree must be a Group, got {type(tree).__name__}")


def _focused(focused: object) -> None:
    if focused is not None and not _is_id(focused):
        raise TypeError(f"focused must be None, a str or a tuple of str,"
                        f" got {type(focused).__name__}")


def _scope(tree: Group, ix: _Index, focused: "_Id | None") -> Group:
    """The active scope (see "Traps")."""
    if focused is not None and focused in ix.stop_ids:
        for gid in ix.paths[focused][1:-1]:
            g = ix.groups[gid]
            if g.trap:
                return g
        return tree
    return ix.first_trap


def _ring(tree: Group, focused: "_Id | None") -> "tuple[tuple[Stop, ...], dict]":
    ix = _index(tree)
    scope = _scope(tree, ix, focused)
    got = ix.rings.get(scope.id)
    if got is None:
        r = _index(scope).stops
        got = (r, {s.id: i for i, s in enumerate(r)})
        ix.rings[scope.id] = got
    return got


def stops(tree: Group) -> "tuple[Stop, ...]":
    """Every stop of the tree in tab order (see the module)."""
    _tree(tree)
    return _index(tree).stops


def path(tree: Group, id: "_Id | None") -> "tuple[_Id, ...]":
    """The focus chain of a node, innermost first; () when absent (see the module)."""
    _tree(tree)
    _focused(id)
    if id is None:
        return ()
    return _index(tree).paths.get(id, ())


def ring(tree: Group, focused: "_Id | None") -> "tuple[Stop, ...]":
    """The stops of the active scope focus may move among (see "Traps")."""
    _tree(tree)
    _focused(focused)
    return _ring(tree, focused)[0]


def _empty(r: object) -> bool:
    return r is None or r.w <= 0 or r.h <= 0


def _cross(a0: int, a1: int, b0: int, b1: int) -> int:
    return max(0, max(a0, b0) - min(a1, b1) + 1)


def _spatial(r: "tuple[Stop, ...]", i: int, how: str) -> "_Id | None":
    f = r[i].rect
    if _empty(f):
        return None
    best = None
    for j, s in enumerate(r):
        c = s.rect
        if j == i or _empty(c):
            continue
        if how == "right":
            if c.x < f.x + f.w:
                continue
            gap, cross = c.x - (f.x + f.w), _cross(f.y, f.y + f.h, c.y, c.y + c.h)
        elif how == "left":
            if c.x + c.w > f.x:
                continue
            gap, cross = f.x - (c.x + c.w), _cross(f.y, f.y + f.h, c.y, c.y + c.h)
        elif how == "down":
            if c.y < f.y + f.h:
                continue
            gap, cross = c.y - (f.y + f.h), _cross(f.x, f.x + f.w, c.x, c.x + c.w)
        else:
            if c.y + c.h > f.y:
                continue
            gap, cross = f.y - (c.y + c.h), _cross(f.x, f.x + f.w, c.x, c.x + c.w)
        rank = (cross, gap, j)
        if best is None or rank < best[0]:
            best = (rank, s.id)
    return None if best is None else best[1]


def move(tree: Group, focused: "_Id | None", how: str) -> "_Id | None":
    """The stop focused after one move: next, prev, first, last or spatial (see the module)."""
    _tree(tree)
    _focused(focused)
    if not isinstance(how, str):
        raise TypeError(f"how must be a str, got {type(how).__name__}")
    if how not in MOVES:
        raise ValueError(f"unknown move {how!r}; expected one of {MOVES}")
    r, where = _ring(tree, focused)
    if not r:
        return focused
    i = where.get(focused) if focused is not None else None
    if i is None:
        return r[-1].id if how in ("prev", "last") else r[0].id
    if how == "next":
        return r[(i + 1) % len(r)].id
    if how == "prev":
        return r[(i - 1) % len(r)].id
    if how == "first":
        return r[0].id
    if how == "last":
        return r[-1].id
    got = _spatial(r, i, how)
    return focused if got is None else got


def heal(old: Group, new: Group, focused: "_Id | None") -> "_Id | None":
    """Where focus goes when the tree changes under it (see the module)."""
    _tree(old)
    _tree(new)
    _focused(focused)
    nx = _index(new)
    if focused is not None and focused in nx.stop_ids:
        return focused
    ox = _index(old)
    if focused is not None and focused in ox.stop_ids:
        olds = ox.stops
        i = next(k for k, s in enumerate(olds) if s.id == focused)
        for s in olds[i + 1:]:
            if s.id in nx.stop_ids:
                return s.id
        for s in reversed(olds[:i]):
            if s.id in nx.stop_ids:
                return s.id
    return nx.stops[0].id if nx.stops else None


_NONE = Target()


def _hits(hits: object) -> None:
    if hits is not None and not callable(getattr(hits, "stack", None)):
        raise TypeError(f"hits must be None or have a callable stack, got {type(hits).__name__}")


def target(event: Event, *, tree: "Group | None" = None, focused: "_Id | None" = None,
           hits: object = None, layer: int = 0) -> Target:
    """The stop, focus path and hit regions an event is aimed at (see the module)."""
    if not isinstance(event, EVENTS):
        raise TypeError(f"event must be one of EVENTS, got {type(event).__name__}")
    if tree is not None:
        _tree(tree)
    _focused(focused)
    _hits(hits)
    if not _is_int(layer):
        raise TypeError(f"layer must be an int, got {type(layer).__name__}")
    return _target(event, tree, focused, hits, layer)


def _target(event: Event, tree: "Group | None", focused: "_Id | None", hits: object,
            layer: int) -> Target:
    """`target` with its arguments checked."""
    if isinstance(event, (Key, Paste)):
        if tree is None or focused is None:
            return _NONE
        ix = _index(tree)
        if focused not in ix.stop_ids:
            return _NONE
        return Target(focused, ix.paths[focused], ())
    if not isinstance(event, Mouse) or hits is None:
        return _NONE
    kept = tuple(h for h in hits.stack(event.x, event.y) if h.layer >= layer)
    stop = None
    if tree is not None and kept:
        where = _ring(tree, focused)[1]
        for h in kept:
            tag = h.tag
            if _is_id(tag) and tag in where:     # the type first: no other tag is compared
                stop = tag
                break
    return Target(stop, _index(tree).paths[stop] if stop is not None else (), kept)
