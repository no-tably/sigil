"""[Screens]: a screen stack: push a modal, pop back.

Kind: service (a frozen value with pure methods; `Pushed` and `Screens` are frozen
dataclasses). What is on screen is a stack: the app's base screen at the bottom,
modals (a dialog, a picker, a help sheet) pushed over it and popped back. The stack
says which screen receives input and which are drawn; what a screen is (its node,
its bindings, its result) is the app's: a screen is any value, kept as given and
compared with `==`. Screens knows nothing of painting: the backdrop (dimming what
lies under a modal) is Paint's, told by the `backdrop` flag. A toast or tooltip that
takes no input is not a screen: it is an overlay (an [Anchor] placement).

Data:
- `Pushed(screen, kind="full")`: one entry: the app's `screen` value and its `kind`,
  one of `KINDS`: "full" (it covers the whole area: nothing under it is drawn) or
  "modal" (drawn over the screens under it, which are still drawn, under a backdrop).
- `Screens(entries=())`: the stack, a tuple of `Pushed`, bottom first (a list is
  stored as a tuple). `Screens()` is empty.

The modal rule:
- Input goes to the top screen only (`input`); the ones under it get none.
- Drawn: from the topmost "full" entry (the bottom one when there is none) up to the
  top, bottom first, in paint order. Every drawn screen but the top has a modal
  above it and so is drawn under a backdrop; the top never is. The screens under the
  topmost "full" one are not drawn at all.

Operations (each returns a new value; none changes `self`):
- `push(screen, kind="modal") -> Screens`: `screen` on top.
- `pop() -> tuple[Screens, object]`: the stack without its top, and the top's screen
  (the app reads a modal's result from it).
- `replace(screen, kind=None) -> Screens`: the top entry's screen swapped for
  `screen`, with `kind` (`None`: the top's own kind).
- `top -> object` (a property): the top entry's screen.
- `input -> object | None` (a property): the screen that receives input: the top's,
  or `None` when the stack is empty.
- `drawn -> tuple[tuple[object, bool], ...]` (a property): `(screen, backdrop)` per
  drawn screen, bottom first, by the modal rule; `()` when empty.
- `len(stack)`; `iter(stack)` over the screens (not the entries), bottom first;
  `screen in stack` (by `==`).

Laws:
- `s.push(x, k).pop() == (s, x)` for every stack `s`, screen `x` and kind `k`.
- `s.push(x, k).input == x`, and `s.push(x, k).drawn[-1] == (x, False)`.
- `s.push(x, "full").drawn == ((x, False),)`.
- `s.push(x, "modal").drawn == tuple((y, True) for y, _ in s.drawn) + ((x, False),)`
  (pushing a modal puts a backdrop over everything that was drawn).
- `len(s.push(x, k)) == len(s) + 1`; `replace` keeps the length.

Inputs: `screen` any value; `kind` one of `KINDS` (or `None` for `replace`);
  `entries` a tuple or list of `Pushed`.
Outputs: a `Screens`; a `(Screens, screen)` pair; a screen, `None` or a tuple.
Errors: `TypeError` when `kind` is not a `str`, an entry is not a `Pushed`, or
  `entries` is not a tuple or list; `ValueError` when `kind` is not one of `KINDS`;
  `IndexError` from `pop`, `replace` and `top` on an empty stack. Assigning a field
  raises `dataclasses.FrozenInstanceError`.
Effects: none.

Usage:
    from cure.draw.layout.screens import Screens
    s = Screens().push("main", "full")
    s.input, s.drawn                         # ("main", (("main", False),))
    s = s.push("confirm")                    # a modal
    s.input, s.drawn                         # ("confirm", (("main", True), ("confirm", False)))
    s = s.push("help", "full").push("keys")
    s.drawn                                  # (("help", True), ("keys", False)): main is covered
    s, gone = s.pop()                        # gone == "keys"
    s.top, len(s)                            # ("help", 3)
    Screens().input, Screens().drawn         # (None, ())
"""

from collections.abc import Iterator
from dataclasses import dataclass

KINDS = ("full", "modal")


def _kind(kind: object) -> None:
    if not isinstance(kind, str):
        raise TypeError(f"kind must be a str, got {type(kind).__name__}")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")


@dataclass(frozen=True)
class Pushed:
    """One entry of the stack: the app's screen and its kind ("full" or "modal")."""

    screen: object
    kind: str = "full"

    def __post_init__(self) -> None:
        _kind(self.kind)


@dataclass(frozen=True)
class Screens:
    """The screen stack, bottom first."""

    entries: tuple = ()

    def __post_init__(self) -> None:
        if not isinstance(self.entries, (tuple, list)):
            raise TypeError(f"entries must be a tuple or list, got {type(self.entries).__name__}")
        object.__setattr__(self, "entries", tuple(self.entries))
        for entry in self.entries:
            if not isinstance(entry, Pushed):
                raise TypeError(f"entries must hold Pushed values, got {type(entry).__name__}")

    def push(self, screen: object, kind: str = "modal") -> "Screens":
        """`screen` on top."""
        _kind(kind)
        return Screens(self.entries + (Pushed(screen, kind),))

    def pop(self) -> "tuple[Screens, object]":
        """The stack without its top, and the top's screen (IndexError when empty)."""
        if not self.entries:
            raise IndexError("pop from an empty screen stack")
        return Screens(self.entries[:-1]), self.entries[-1].screen

    def replace(self, screen: object, kind: "str | None" = None) -> "Screens":
        """The top's screen swapped for `screen` (kind None: the top's own)."""
        if not self.entries:
            raise IndexError("replace on an empty screen stack")
        top = self.entries[-1]
        if kind is None:
            kind = top.kind
        _kind(kind)
        return Screens(self.entries[:-1] + (Pushed(screen, kind),))

    @property
    def top(self) -> object:
        """The top's screen (IndexError when empty)."""
        if not self.entries:
            raise IndexError("top of an empty screen stack")
        return self.entries[-1].screen

    @property
    def input(self) -> object:
        """The screen that receives input: the top's, or None when empty."""
        return self.entries[-1].screen if self.entries else None

    @property
    def drawn(self) -> tuple:
        """(screen, backdrop) per drawn screen, bottom first, by the modal rule."""
        entries = self.entries
        start = max((i for i, e in enumerate(entries) if e.kind == "full"), default=0)
        last = len(entries) - 1
        return tuple((e.screen, i != last) for i, e in enumerate(entries) if i >= start)

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator:
        return iter(tuple(e.screen for e in self.entries))

    def __contains__(self, screen: object) -> bool:
        return any(e.screen == screen for e in self.entries)
