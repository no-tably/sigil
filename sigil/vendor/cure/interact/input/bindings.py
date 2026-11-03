"""[Bindings]: ONE table: dispatch, key hints and help.

Kind: service (the `Binding` entry, the layered `Bindings` table, the match results,
and the pure ops that read the table); pure.

One declarative table drives everything a key does and everything said about it: what
a key fires (`match`, `action`), the key hints row (`hints`, the entries Draw's
KeyHints reads) and the help (`help`), so a hint can never disagree with dispatch. It
provides `match` on top of [Events] (`[Bindings] -> [Events] : match({Key}) =>
{Action}`: a key, by its stroke, to an action) and `action` for the Router
(`[Router] -> [Bindings] : action({Key}) => {Action}`). Keys and clicks fire the same
action: a hint's click fires the entry's `action`, the value its keys fire.

## Entries

- `Binding(keys, action, label="", *, group=None, hidden=False, on=None, mode=None,
  scope=None)` (frozen dataclass, the shape KeyHints reads by attribute):
  - `keys`: a `str`, or a non-empty tuple of `str` (alternatives: `("j", "down")`
    shows `j/down`). Each is a key sequence: one stroke ("ctrl+s") or a chord, strokes
    separated by whitespace ("ctrl+x ctrl+s", "g g"). Stored in canonical form
    (`sequence`: each stroke as [Events]' `stroke` writes it, joined by one space):
    `Binding("Ctrl+s", "save").keys == "ctrl+s"`; `Binding("A", "x").keys ==
    "shift+a"`; a tuple stays a tuple (repeats after normalising are a `ValueError`).
  - `action`: any hashable value the app chooses ("quit", `("mode", "insert")`), or
    `None`: a mask, which unbinds these keys in every lower layer (see "Layers").
  - `label`: the word shown in hints and help, a `str`.
  - `group`: a `str` or `None`, for the hint separators and the help's sections.
  - `hidden`: a `bool`; a hidden entry fires but is not shown (KeyHints skips it,
    `help` leaves it out).
  - `on`: `True`, `False` or `None`: a toggle's state as shown (`hints` can take it
    from the app's state, see there).
  - `mode`: `None` (active in every mode) or a non-empty `str`, the mode it belongs
    to. Modes are named tables: the app keeps the current mode (an action of its own
    switches it) and passes it to every call; the table never changes it.
  - `scope`: `None` (active everywhere) or a focus id, [Focus]' id type: a non-empty
    `str` or a non-empty `tuple` of non-empty `str` (`("pane", "dag")`, a Views node's
    id): active only when the caller lists it in `scopes` (the focus chain, innermost
    first: a focused widget's own bindings, its ancestors', the screen's; [Focus]'
    `path`, which holds a tuple id as one item). A scope is matched by `==` only: the
    scope `("pane", "dag")` is active for `scopes=(("pane", "dag"), "screen")`, never
    for `("pane",)`, `"pane"` or `("pane", "dag", "view")` (no prefix or element
    matching), and `"a"` and `("a",)` are two scopes.
  `TypeError` when `keys` is neither a `str` nor a tuple of `str`, `action` is
  unhashable, `label` not a `str`, `group`, `mode` neither `None` nor a `str`, `scope`
  neither `None`, a `str` nor a `tuple` of `str` ("Binding.scope must be None, a str
  or a tuple of str, got <type>"), `hidden` not a `bool`, `on` not `None` or a `bool`;
  `ValueError` for an empty tuple of keys, a sequence with no stroke, a malformed
  stroke (as [Events]' `key` raises), an empty `mode`, a `scope` that is `""` or `()`
  ("Binding.scope must not be empty"), a `scope` tuple holding `""` ("Binding.scope
  must not hold an empty str"), or a repeated sequence in `keys`.
- `sequence(text) -> tuple[str, ...]`: a key sequence parsed into its canonical
  strokes: `sequence("ctrl+x  Ctrl+s") == ("ctrl+x", "ctrl+s")`, `sequence("A") ==
  ("shift+a",)`. `TypeError` when `text` is not a `str`; `ValueError` when it holds no
  stroke or a malformed one.

## Layers

`Bindings(default=(), child=(), authored=(), runtime=(), *, timeout=None)` (frozen
dataclass): the one table, four layers of `Binding`s (each any iterable, held as a
tuple), lowest first, `LAYERS = ("default", "child", "authored", "runtime")`: the
library's or app's defaults, an embedded child's own keys (namespaced by the app, e.g.
actions `("child", id, name)`), what the app's author bound, and what the person
rebound at run time. A higher layer overrides a lower one; a `None` action masks.
`timeout`: how long a chord may wait for its next key, in the units of `now`; `None`
(wait for ever: a tmux-style prefix) or a number > 0. Change a layer with
`dataclasses.replace(bindings, runtime=...)` (checked again).

A query is a `mode` (`None` or a `str`) and `scopes` (a tuple, innermost first, each
item a `str` or a `tuple` of `str`: a scope as a `Binding` names it, an item no binding
names matching none). A binding is active for it when its `mode` is `None` or equal to
`mode`, and its `scope` is `None` or in `scopes` (by `==`). For a sequence, the winner
is the active binding with that sequence among its keys that ranks first by: its scope's
index in `scopes` (`None` after every listed scope), then a binding of the mode before a
mode-`None` one, then the higher layer. The sequence is bound when the winner's `action`
is not `None`; with a `None` action it is masked (unbound, whatever loses to it). A
sequence is a prefix when it is a proper prefix of some bound sequence.

Errors at construction: `TypeError` when a layer is not iterable or holds a
non-`Binding`, `timeout` is not `None` or a number (a `bool` is not); `ValueError`
for a `timeout` <= 0; for two bindings of one layer with the same `mode` and `scope`
that share a sequence (a conflict: say it once, or in a higher layer); and when, for
some query whose `mode` is `None` or one of the bindings' modes and whose `scopes` are
`()` or one of the bindings' scopes alone, a bound sequence is a proper prefix of
another bound sequence ("g" and "g g"): a key would be both an action and the start of
a chord. (In a query of several scopes, an exact match wins: it fires.) The messages
name the sequences. (Which order the check visits the scopes in is not part of the
contract, only which query a message names; `str` and tuple scopes are checked alike.)

## Matching keys

The results (frozen dataclasses):
- `Fire(action, keys, binding)`: a bound sequence is complete. `action` the winner's
  action (never `None`), `keys` the sequence (a tuple of strokes), `binding` the
  winning `Binding`.
- `Pending(keys, since)`: `keys` (a tuple of strokes) is a prefix: the next key may
  complete it. `since` the `now` of its last key. The caller keeps it and passes it
  back to the next `match`; shown in a status bar, and `hints(pending=...)` lists what
  may follow.
- `Miss(keys)`: a pending chord was broken (the last key continues no bound sequence)
  or timed out: `keys` the strokes swallowed, the breaking key included. The app drops
  them (tmux) or reports them ("ctrl+x z is undefined").

- `match(bindings, key, now, *, mode=None, scopes=(), pending=None) -> Fire | Pending
  | Miss | None`: one key, by its stroke (`stroke(key)`), after the chord `pending`
  (a `Pending` from the last call, or `None`). With `seq = pending.keys + (stroke(key),)`
  (or just the stroke):
  1. a key whose `event` is "release" changes nothing: the result is `pending` itself
     (`None` with no chord pending); "repeat" matches as "press" does;
  2. `seq` bound: `Fire(winner.action, seq, winner)`;
  3. else `seq` a prefix: `Pending(seq, now)`;
  4. else, with a chord pending: `Miss(seq)`;
  5. else `None`: nothing is bound to this key, it passes on (to the focused input, or
     a mux's pane: with a prefix key, everything else passes through).
  `match` never expires a chord itself (call `expire`). `TypeError` when `bindings`
  is not a `Bindings`, `key` not an [Events] `Key`, `now` not a number, `mode` not
  `None` or a `str`, `scopes` not a tuple whose items are each a `str` or a `tuple` of
  `str` ("scopes must be a tuple of scopes, each a str or a tuple of str"), `pending`
  not a `Pending` or `None`.
- `expire(bindings, pending, now) -> Pending | Miss`: `Miss(pending.keys)` when
  `bindings.timeout` is not `None` and `now - pending.since >= bindings.timeout`;
  else `pending`. `TypeError` for wrong types.
- `deadline(bindings, pending) -> float | int | None`: `pending.since +
  bindings.timeout`, or `None` when `pending` or the timeout is `None`; the app's loop
  wakes for it.
- `action(bindings, keys, *, mode=None, scopes=()) -> Hashable | None`: what a whole
  sequence fires, with no chord state or time: the winner's action when `keys` is
  bound, else `None` (unbound, masked or only a prefix). `keys`: a sequence string
  ("ctrl+x ctrl+s") or a tuple of `Key`s. `TypeError` / `ValueError` as `match` and
  `sequence` give them.

A prefix key (tmux): bind chords that start with it, `prefixed("ctrl+b",
(Binding("c", "new"), Binding("ctrl+b", "send_prefix")))`, in a table with
`timeout=None`. A key with no chord pending that starts none gives `None` and goes to
the inner program; after the prefix, a key of the prefix table fires, any other gives
`Miss`. Modes are the other way to switch tables (zellij, vim).
- `prefixed(prefix, bindings) -> tuple[Binding, ...]`: each binding with `prefix` (a
  sequence string) put before each of its sequences, everything else kept:
  `prefixed("ctrl+b", (Binding("c", "new"),)) == (Binding("ctrl+b c", "new"),)`.
  `TypeError` when `prefix` is not a `str` or an item not a `Binding`; `ValueError`
  for a malformed prefix.

## Hints and help, from the same table

- `hints(bindings, *, mode=None, scopes=(), pending=None, on=None) -> tuple[Binding,
  ...]`: the entries KeyHints shows, for one query. Every binding of every layer, in
  order (default first, each layer in its own order), whose action is not `None`,
  keeping only the sequences of its `keys` it is the winner for (and bound); one with
  none left is left out. `keys` keeps its form: a `str` stays a `str`, a tuple the
  tuple of those kept. With `pending`, only the sequences that extend `pending.keys`
  are kept, written without its strokes (after "ctrl+b": `"c"`, which-key style).
  `on`: `None` or a mapping from action to `bool`: an entry whose action is in it
  shows that state (`on=...`), the others their own `on`. Hidden entries are included
  (KeyHints skips them; the Router never needs `hints`). Every other field as bound.
- `help(bindings, *, mode=None, scopes=(), on=None) -> tuple[tuple[str | None,
  tuple[Binding, ...]], ...]`: the help, as sections: the non-hidden entries of
  `hints(...)` (no pending), grouped by `group`, the groups in the order of their first
  entry, each group's entries in order.
Errors: `TypeError` for wrong argument types (as `match`; `on` not a mapping).

Laws: for a table and queries whose scopes are all `str`, every result (and every
construction error) is the one given before tuple scopes were allowed (the str-only
tests pass unchanged); renaming scopes one to one, in the table and in every query
alike, changes no `match`, `action`, `hints` or `help` result but for the renamed
`scope` fields.

Inputs: [Events]' `Key`, stroke strings, the app's `now`, mode and scopes. Outputs:
the results above (an {Action}: `Fire.action`), entries. Effects: none.

Usage:
    from cure.interact.input.bindings import Binding, Bindings, match, hints, help
    from cure.interact.input.bindings import Fire, Pending, Miss, prefixed, expire, action
    from cure.interact.input.events import key
    table = Bindings(
        default=(Binding("q", "quit", "quit"), Binding("ctrl+s", "save", "save"),
                 Binding(("j", "down"), "next", "move", group="nav")),
        runtime=(Binding("ctrl+s", None),))                # the person unbound ctrl+s
    match(table, key("q"), 0.0)                # Fire("quit", ("q",), Binding("q", "quit", "quit"))
    match(table, key("ctrl+s"), 0.0)           # None: masked
    [h.keys for h in hints(table)]             # ["q", ("j", "down")]
    emacs = Bindings(default=(Binding("ctrl+x ctrl+s", "save", "save"),), timeout=1.0)
    p = match(emacs, key("ctrl+x"), 5.0)       # Pending(("ctrl+x",), 5.0)
    match(emacs, key("ctrl+s"), 5.2, pending=p)   # Fire("save", ("ctrl+x", "ctrl+s"), ...)
    match(emacs, key("z"), 5.2, pending=p)     # Miss(("ctrl+x", "z"))
    expire(emacs, p, 6.0)                      # Miss(("ctrl+x",))
    mux = Bindings(default=prefixed("ctrl+b", (Binding("c", "new", "new pane"),)))
    match(mux, key("x"), 0.0)                  # None: to the pane
    [h.keys for h in hints(mux, pending=Pending(("ctrl+b",), 0.0))]   # ["c"]
    Bindings(default=(Binding("g", "top"), Binding("g g", "home")))   # ValueError: "g" is a prefix of "g g"
    panes = Bindings(default=(Binding("home", ("home", "dag"), scope=("pane", "dag")),))
    action(panes, "home", scopes=(("pane", "dag"), "screen"))   # ("home", "dag")
    action(panes, "home", scopes=("pane", "dag"))   # None: two str scopes, not the tuple
"""

from collections.abc import Hashable, Iterable, Mapping
from dataclasses import dataclass, field, replace

from .events import Key, key, stroke

LAYERS = ("default", "child", "authored", "runtime")


def sequence(text: str) -> "tuple[str, ...]":
    """A key sequence ("ctrl+x ctrl+s") as its canonical strokes (see the module)."""
    if not isinstance(text, str):
        raise TypeError(f"a key sequence must be a str, got {type(text).__name__}")
    parts = text.split()
    if not parts:
        raise ValueError(f"a key sequence with no stroke: {text!r}")
    return tuple(stroke(key(p)) for p in parts)


def _opt_str(value: object, name: str) -> None:
    if value is not None and not isinstance(value, str):
        raise TypeError(f"Binding.{name} must be None or a str, got {type(value).__name__}")
    if value == "":
        raise ValueError(f"Binding.{name} must not be empty")


def _is_scope(value: object) -> bool:
    """A focus id's type: a str, or a tuple whose items are all str (emptiness aside)."""
    return isinstance(value, str) or (isinstance(value, tuple)
                                      and all(isinstance(v, str) for v in value))


def _check_scope(value: object) -> None:
    if value is None:
        return
    if not _is_scope(value):
        raise TypeError(f"Binding.scope must be None, a str or a tuple of str,"
                        f" got {type(value).__name__}")
    if value == "" or value == ():
        raise ValueError("Binding.scope must not be empty")
    if isinstance(value, tuple) and "" in value:
        raise ValueError("Binding.scope must not hold an empty str")


@dataclass(frozen=True)
class Binding:
    """One entry of the table: keys, action (None masks), label and how it is shown."""

    keys: "str | tuple[str, ...]"
    action: "Hashable | None"
    label: str = ""
    group: "str | None" = field(default=None, kw_only=True)
    hidden: bool = field(default=False, kw_only=True)
    on: "bool | None" = field(default=None, kw_only=True)
    mode: "str | None" = field(default=None, kw_only=True)
    scope: "str | tuple[str, ...] | None" = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        keys = self.keys
        if isinstance(keys, str):
            object.__setattr__(self, "keys", " ".join(sequence(keys)))
        elif isinstance(keys, tuple) and all(isinstance(k, str) for k in keys):
            if not keys:
                raise ValueError("Binding.keys must not be an empty tuple")
            canonical = tuple(" ".join(sequence(k)) for k in keys)
            if len(set(canonical)) != len(canonical):
                raise ValueError(f"Binding.keys repeats a sequence: {keys!r}")
            object.__setattr__(self, "keys", canonical)
        else:
            raise TypeError("Binding.keys must be a str or a tuple of str")
        try:
            hash(self.action)
        except TypeError:
            raise TypeError(f"Binding.action must be hashable, got {type(self.action).__name__}") from None
        if not isinstance(self.label, str):
            raise TypeError("Binding.label must be a str")
        if self.group is not None and not isinstance(self.group, str):
            raise TypeError("Binding.group must be None or a str")
        if type(self.hidden) is not bool:
            raise TypeError("Binding.hidden must be a bool")
        if self.on is not None and type(self.on) is not bool:
            raise TypeError("Binding.on must be None or a bool")
        _opt_str(self.mode, "mode")
        _check_scope(self.scope)


@dataclass(frozen=True)
class Bindings:
    """The one table: four layers, lowest first, and the chord timeout (see the module)."""

    default: "tuple[Binding, ...]" = ()
    child: "tuple[Binding, ...]" = ()
    authored: "tuple[Binding, ...]" = ()
    runtime: "tuple[Binding, ...]" = ()
    timeout: "float | int | None" = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        for name in LAYERS:
            layer = getattr(self, name)
            try:
                items = tuple(layer)
            except TypeError:
                raise TypeError(f"Bindings.{name} must be an iterable of Binding") from None
            for item in items:
                if not isinstance(item, Binding):
                    raise TypeError(f"Bindings.{name} holds a {type(item).__name__}, not a Binding")
            object.__setattr__(self, name, items)
        t = self.timeout
        if t is not None:
            if isinstance(t, bool) or not isinstance(t, (int, float)):
                raise TypeError("Bindings.timeout must be None or a number")
            if not t > 0:
                raise ValueError(f"Bindings.timeout must be > 0, got {t}")
        _check(self)


def _check(bindings: "Bindings") -> None:
    """The conflict and prefix checks (see "Errors at construction")."""
    entries = []                       # (rank of layer, Binding, its sequences as tuples)
    for li, name in enumerate(LAYERS):
        seen: dict = {}
        for b in getattr(bindings, name):
            seqs = _seqs(b)
            for seq in seqs:
                where = (b.mode, b.scope, seq)
                if where in seen:
                    raise ValueError(f"the {name} layer binds {' '.join(seq)!r} twice"
                                     f" (mode {b.mode!r}, scope {b.scope!r})")
                seen[where] = b
            entries.append((li, b, seqs))
    object.__setattr__(bindings, "_entries", tuple(entries))
    object.__setattr__(bindings, "_tables", {})
    modes = [None] + sorted({b.mode for _, b, _ in entries if b.mode is not None})
    # str scopes first, in their old order, then the tuple ones (a str and a tuple never compare)
    scopes = [()] + [(sc,) for sc in sorted({b.scope for _, b, _ in entries if b.scope is not None},
                                            key=lambda sc: (isinstance(sc, tuple), sc))]
    for mode in modes:
        for scope in scopes:
            bound, _ = _table(bindings, mode, scope)
            for seq in bound:
                for n in range(1, len(seq)):
                    if seq[:n] in bound:
                        raise ValueError(f"{' '.join(seq[:n])!r} is a prefix of {' '.join(seq)!r}"
                                         f" (mode {mode!r}, scopes {scope!r})")


def _seqs(b: "Binding") -> "tuple[tuple[str, ...], ...]":
    """A binding's sequences, each a tuple of strokes."""
    keys = b.keys if isinstance(b.keys, tuple) else (b.keys,)
    return tuple(tuple(k.split(" ")) for k in keys)


def _table(bindings: "Bindings", mode: "str | None",
           scopes: "tuple[str | tuple[str, ...], ...]") -> "tuple[dict, frozenset]":
    """For one query: {bound sequence: (winner entry index, Binding)} and the prefixes."""
    cache = bindings._tables
    got = cache.get((mode, scopes))
    if got is not None:
        return got
    best: dict = {}                    # sequence -> (rank, index, Binding)
    far = len(scopes)
    for i, (li, b, seqs) in enumerate(bindings._entries):
        if b.mode is not None and b.mode != mode:
            continue
        if b.scope is None:
            place = far
        elif b.scope in scopes:
            place = scopes.index(b.scope)
        else:
            continue
        rank = (place, 0 if b.mode is not None else 1, -li)
        for seq in seqs:
            old = best.get(seq)
            if old is None or rank < old[0]:
                best[seq] = (rank, i, b)
    bound = {seq: (i, b) for seq, (_, i, b) in best.items() if b.action is not None}
    prefixes = frozenset(seq[:n] for seq in bound for n in range(1, len(seq)))
    got = (bound, prefixes)
    if len(cache) < 256:
        cache[(mode, scopes)] = got
    return got


def _query(bindings: object, mode: object, scopes: object) -> None:
    if not isinstance(bindings, Bindings):
        raise TypeError(f"bindings must be a Bindings, got {type(bindings).__name__}")
    if mode is not None and not isinstance(mode, str):
        raise TypeError("mode must be None or a str")
    if not isinstance(scopes, tuple) or not all(_is_scope(sc) for sc in scopes):
        raise TypeError("scopes must be a tuple of scopes, each a str or a tuple of str")


def _number(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number, got {type(value).__name__}")


def _pending(value: object, optional: bool = True) -> None:
    if value is None and optional:
        return
    if not isinstance(value, Pending):
        raise TypeError(f"pending must be a Pending{' or None' if optional else ''},"
                        f" got {type(value).__name__}")


@dataclass(frozen=True)
class Fire:
    """A bound sequence is complete: fire `action`."""

    action: Hashable
    keys: "tuple[str, ...]"
    binding: Binding


@dataclass(frozen=True)
class Pending:
    """A chord's keys so far, and the `now` of the last one."""

    keys: "tuple[str, ...]"
    since: "float | int"


@dataclass(frozen=True)
class Miss:
    """A pending chord broken or timed out: the strokes swallowed."""

    keys: "tuple[str, ...]"


def match(bindings: Bindings, key: Key, now: "float | int", *, mode: "str | None" = None,
          scopes: "tuple[str | tuple[str, ...], ...]" = (), pending: "Pending | None" = None,
          ) -> "Fire | Pending | Miss | None":
    """One key after the chord pending: fire, wait, miss or pass on (see the module)."""
    _query(bindings, mode, scopes)
    if not isinstance(key, Key):
        raise TypeError(f"key must be a Key, got {type(key).__name__}")
    _number(now, "now")
    _pending(pending)
    if key.event == "release":
        return pending
    one = stroke(key)
    seq = pending.keys + (one,) if pending is not None else (one,)
    bound, prefixes = _table(bindings, mode, scopes)
    won = bound.get(seq)
    if won is not None:
        return Fire(won[1].action, seq, won[1])
    if seq in prefixes:
        return Pending(seq, now)
    if pending is not None:
        return Miss(seq)
    return None


def expire(bindings: Bindings, pending: Pending, now: "float | int") -> "Pending | Miss":
    """A pending chord, or its Miss once the table's timeout has passed (see the module)."""
    if not isinstance(bindings, Bindings):
        raise TypeError(f"bindings must be a Bindings, got {type(bindings).__name__}")
    _pending(pending, optional=False)
    _number(now, "now")
    t = bindings.timeout
    if t is not None and now - pending.since >= t:
        return Miss(pending.keys)
    return pending


def deadline(bindings: Bindings, pending: "Pending | None") -> "float | int | None":
    """When a pending chord times out, or None (see the module)."""
    if not isinstance(bindings, Bindings):
        raise TypeError(f"bindings must be a Bindings, got {type(bindings).__name__}")
    _pending(pending)
    if pending is None or bindings.timeout is None:
        return None
    return pending.since + bindings.timeout


def action(bindings: Bindings, keys: "str | tuple[Key, ...]", *, mode: "str | None" = None,
           scopes: "tuple[str | tuple[str, ...], ...]" = ()) -> "Hashable | None":
    """What a whole key sequence fires, or None (see the module)."""
    _query(bindings, mode, scopes)
    if isinstance(keys, str):
        seq = sequence(keys)
    elif isinstance(keys, tuple) and all(isinstance(k, Key) for k in keys):
        seq = tuple(stroke(k) for k in keys)
    else:
        raise TypeError("keys must be a sequence str or a tuple of Key")
    won = _table(bindings, mode, scopes)[0].get(seq)
    return None if won is None else won[1].action


def prefixed(prefix: str, bindings: Iterable[Binding]) -> "tuple[Binding, ...]":
    """Each binding's sequences behind a prefix key (see the module)."""
    if not isinstance(prefix, str):
        raise TypeError(f"prefix must be a str, got {type(prefix).__name__}")
    head = " ".join(sequence(prefix)) + " "
    out = []
    for b in bindings:
        if not isinstance(b, Binding):
            raise TypeError(f"prefixed takes Bindings, got {type(b).__name__}")
        keys = head + b.keys if isinstance(b.keys, str) else tuple(head + k for k in b.keys)
        out.append(replace(b, keys=keys))
    return tuple(out)


def hints(bindings: Bindings, *, mode: "str | None" = None,
          scopes: "tuple[str | tuple[str, ...], ...]" = (),
          pending: "Pending | None" = None, on: "Mapping[Hashable, bool] | None" = None,
          ) -> "tuple[Binding, ...]":
    """The entries KeyHints shows for one query (see the module)."""
    _query(bindings, mode, scopes)
    _pending(pending)
    if on is not None and not isinstance(on, Mapping):
        raise TypeError(f"on must be None or a mapping, got {type(on).__name__}")
    bound = _table(bindings, mode, scopes)[0]
    lead = pending.keys if pending is not None else ()
    cut = len(lead)
    out = []
    for i, (_, b, seqs) in enumerate(bindings._entries):
        if b.action is None:
            continue
        kept = []
        for seq in seqs:
            won = bound.get(seq)
            if won is None or won[0] != i:
                continue
            if cut:
                if len(seq) <= cut or seq[:cut] != lead:
                    continue
                seq = seq[cut:]
            kept.append(" ".join(seq))
        if not kept:
            continue
        keys = kept[0] if isinstance(b.keys, str) else tuple(kept)
        state = on[b.action] if on is not None and b.action in on else b.on
        if keys != b.keys or state != b.on:
            b = replace(b, keys=keys, on=state)
        out.append(b)
    return tuple(out)


def help(bindings: Bindings, *, mode: "str | None" = None,
         scopes: "tuple[str | tuple[str, ...], ...]" = (),
         on: "Mapping[Hashable, bool] | None" = None,
         ) -> "tuple[tuple[str | None, tuple[Binding, ...]], ...]":
    """The help: the shown entries, grouped (see the module)."""
    groups: dict = {}
    for b in hints(bindings, mode=mode, scopes=scopes, on=on):
        if not b.hidden:
            groups.setdefault(b.group, []).append(b)
    return tuple((g, tuple(entries)) for g, entries in groups.items())
