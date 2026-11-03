"""{Component}: one component of the design, with its inspector pages.

Kind: data (a frozen dataclass, checked on construction). Plain data construct maps
its own model into.

What it is: key (system/component), kind, status, builder id or none, and its
inspector pages: brief, binding, recipe, suite, history (text lines).

Data:
- `Component(key, *, kind="service", status="planned", builder=None, brief=(),
  binding=(), recipe=(), suite=(), history=())`:
  - `key`: a `str` `"<System>/<Component>"`, both parts non-empty (exactly one
    `/`), e.g. `"Views/BuilderTab"`; unique in its {Board}.
  - `kind`: one of `KINDS`, sigil's five glyph kinds: `"service"` `[ ]`,
    `"store"` `| |`, `"data"` `{ }`, `"event"` `< >`, `"actor"` `( )`.
  - `status`: one of `STATES`, construct's component lifecycle: `"planned"`,
    `"building"`, `"built"`, `"stale"`, `"rebuilding"`, `"removed"`, `"pruning"`.
  - `builder`: `None` or a non-empty `str`, the {Builder} holding it.
  - `brief`, `binding`, `recipe`, `suite`, `history`: the five pages, each a
    `tuple` of lines, a line a `str` or a Text {Line} (styled: span styles as the
    Widgets protocol reads them, `None`, a theme role `str` or a Style); `()` is an
    empty page. One line is one row (no line holds a line break: construct splits
    its text into lines).
  - `page(name) -> tuple`: the page named `name` (one of `PAGES`); `ValueError`
    for another name, `TypeError` for a non-`str`.
- Equality and hashing are field by field.

Constants: `KINDS = ("service", "store", "data", "event", "actor")`; `STATES =
("planned", "building", "built", "stale", "rebuilding", "removed", "pruning")`;
`PAGES = ("brief", "binding", "recipe", "suite", "history")` (the field names, in
Inspector's tab order).

Errors (construction, in field order, the first failure raised):
- `TypeError` when `key`, `kind` or `status` is not a `str`; `builder` is neither
  `None` nor a `str`; a page is not a `tuple` (`"brief must be a tuple of lines, got
  list"`) or holds a line that is neither a `str` nor a `Line`.
- `ValueError` when `key` is not two non-empty parts joined by one `/` (`"key must
  be 'System/Component', got 'x'"`); `kind` not in `KINDS` or `status` not in
  `STATES` (`"status must be one of planned, ..., got 'x'"`); `builder` is `""`; a
  page's line holds `"\\n"` or `"\\r"` (`"brief line 3 holds a line break"`, the
  index from 0).
Effects: none.

Usage:
    from cure.draw.views.board import Component
    c = Component("Views/Inspector", status="building", builder="b1",
                  brief=("one component: brief, binding ...",))
    c.page("brief")                   # ("one component: brief, binding ...",)
    Component("Inspector")            # ValueError: key must be 'System/Component', got 'Inspector'
"""

from dataclasses import KW_ONLY, dataclass

from cure.core.text import Line

KINDS = ("service", "store", "data", "event", "actor")
"""A component's kinds (sigil's glyph kinds), in order."""

STATES = ("planned", "building", "built", "stale", "rebuilding", "removed", "pruning")
"""A component's statuses (construct's lifecycle), in order."""

PAGES = ("brief", "binding", "recipe", "suite", "history")
"""The inspector pages, in tab order (each a field)."""


@dataclass(frozen=True)
class Component:
    """One component and its inspector pages (see the module)."""

    key: str
    _: KW_ONLY
    kind: str = "service"
    status: str = "planned"
    builder: "str | None" = None
    brief: tuple = ()
    binding: tuple = ()
    recipe: tuple = ()
    suite: tuple = ()
    history: tuple = ()

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _text("key", self.key)
        parts = self.key.split("/")
        if len(parts) != 2 or not all(parts):
            raise ValueError(f"key must be 'System/Component', got {self.key!r}")
        _choice("kind", self.kind, KINDS)
        _choice("status", self.status, STATES)
        if self.builder is not None:
            _text("builder", self.builder, empty=False, what="None or a str")
        for name in PAGES:
            _page(name, getattr(self, name))

    def page(self, name: str) -> tuple:
        """The page named `name`, one of `PAGES` (see the module)."""
        _choice("page", name, PAGES)
        return getattr(self, name)


def _text(name: str, value: object, *, empty: bool = True, what: str = "a str") -> None:
    """Check `value` is a `str` (non-empty unless `empty`)."""
    if not isinstance(value, str):
        raise TypeError(f"{name} must be {what}, got {type(value).__name__}")
    if not empty and value == "":
        raise ValueError(f"{name} must not be ''")


def _choice(name: str, value: object, choices: tuple) -> None:
    """Check `value` is a `str` and one of `choices`."""
    _text(name, value)
    if value not in choices:
        raise ValueError(f"{name} must be one of {', '.join(choices)}, got {value!r}")


def _page(name: str, lines: object) -> None:
    """Check a page: a tuple of lines (`str` or `Line`), none holding a line break."""
    if not isinstance(lines, tuple):
        raise TypeError(f"{name} must be a tuple of lines, got {type(lines).__name__}")
    for i, line in enumerate(lines):
        if isinstance(line, str):
            text = line
        elif isinstance(line, Line):
            text = "".join(span.text for span in line.spans)
        else:
            raise TypeError(f"{name} line {i} must be a str or a Line, got {type(line).__name__}")
        if "\n" in text or "\r" in text:
            raise ValueError(f"{name} line {i} holds a line break")
