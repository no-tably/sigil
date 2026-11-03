"""[Scope]: a per-node override that cascades to the children.

Kind: service (a data class: a value Theme builds and Theme reads; no ops of its own).

What it does: a node may carry a {Scope}: a theme and/or a charset to use for it and
everything under it (a pane in another palette, a panel in ASCII). Overlays are built
ahead of time, at theme load: Theme's `scoped(theme, text)` makes the scope's theme
from a theme fragment laid over the outer theme, its derived colours computed then
(decision 1), and hands it to Scope as a value, `Scope(theme=..., charset=...)`. This
is the one drawn flow, `[Scope] -> [Theme] : scoped({Raw}) => {Scope}`: a Scope's
theme comes from Theme's `scoped`.

The direction (Q9b, sigil's ruling on Scope): Scope never calls into Theme, and Theme
never calls into Scope. The cascade is Theme's face `enter(node, ctx)` (see [Theme],
The boundary): it reads `node.scope`, checks it is a `Scope` (or None), and swaps in
this value's `theme` then its `charset` (each when not None) with
`dataclasses.replace`, so the children inherit it (pushed and restored at Paint's one
recursion point simply by passing the returned value down). Entering a node never
resolves a role. This module imports nothing of Theme's.

What a Scope value means (the rule Theme's `enter` applies, stated here as the
value's meaning):
- `theme`: the theme the node and its children use (a Theme), or None to inherit the
  context's;
- `charset`: the charset they use (a Charset), or None to inherit; independent of
  `theme` (swapping one leaves the other as the context has it);
- both None: no override (the context passes through unchanged, the same object).

Withdrawn (Q9b): the module function `enter(node, ctx)`, removed. The cascade is on
Theme's face (Theme's `enter`); the tests (`tests/theme/test_scope.py`) prove the same
cases through it, with `surface=False` nodes.

Data (frozen dataclass; immutable all the way down, Theme's rule):
- `Scope(theme: Theme | None = None, charset: Charset | None = None)`. No container
  field of its own: a Theme and a Charset are immutable by their own contracts.
  Hashing as today: hashable when both are None; `hash` raises `TypeError` when it
  holds a Theme or a Charset (theirs does).

Inputs: `Scope`'s two fields, as above (no check at construction, as today: a wrong
  type is found by whoever reads it).
Outputs: a `Scope` value.
Errors: none of its own (`dataclasses.FrozenInstanceError` on assignment).
Effects: none.

Usage:
    from dataclasses import dataclass
    from types import SimpleNamespace as Node
    from cure.draw.theme import enter
    from cure.draw.theme.charset import glyphs
    from cure.draw.theme.scope import Scope
    @dataclass(frozen=True)
    class Ctx:
        theme: object = None
        charset: object = None
        level: int = 0
    ctx = Ctx(theme="outer", charset=glyphs())
    enter(Node(scope=None, surface=False), ctx) is ctx                               # True
    enter(Node(scope=Scope(charset=glyphs(ascii=True)), surface=False), ctx).charset.name   # "ascii"
    enter(Node(scope=Scope(charset=glyphs(ascii=True)), surface=False), ctx).theme          # "outer"
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Scope:
    """{Scope}: the theme and charset a node and its children use instead (None: inherit)."""

    theme: object = None
    charset: object = None

