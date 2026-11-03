"""[Inspector]: one component: brief, binding, recipe, suite, history (tabs).

Kind: service (pure functions from a {Component} and the app's page state to widget
nodes; see the Views package for the tab protocol and its `TabView`).

What it does: construct's tab for one component. One pane, `"inspector"`: a Block
titled with the component's key, holding its kind, status and builder as key:value
rows over a Widgets `Tabs` of its five pages (brief, binding, recipe, suite,
history), each page's lines a `Drawing` scrolled by the app. Which page is active
and how far it is scrolled are the app's state, passed in; a click on a page's tab
hits that tab's id, and the app's update makes it the page (the router turns the hit
into the app's action: rove, commit and fire stay three steps). Given the app's
`actions` (page name -> action tag, construct C1), the page row is radios instead,
one per page, on for the page shown, each hit tagged with the app's tag, so a click
fires the app's own binding through Input's `route` (its key hint's click, step 4),
with no app code between. It composes existing widget nodes only and paints nothing
itself.

The tab's key: `key(component) == ("inspector", component.key)`, written `k`. Every
id a node of this tab carries is `k + (part, ...)`, as listed; no other node carries
one.

The pane (`inspector(component, page="brief", scroll=0, *, actions=None) -> Block`).
Without `actions` (`None`, the default):
`Block((summary, pages), title=component.key, kind="pane", id=k + ("inspector",))`,
every other Block field its default (Column layout), where:
- `summary == PropertyList((Item("kind", component.kind), Item("status",
  component.status, TONES[component.status]), Item("builder", component.builder or
  "none")), size=Fixed(3))` (Widgets' Item, no ids; Layout's `Fixed`).
- `pages == Tabs(tuple(Tab(name, body(name), id=k + ("page", name)) for name in
  PAGES), active=PAGES.index(page), id=k + ("pages",))` (Widgets' Tabs and Tab; the
  strip reads `brief │ binding │ recipe │ suite │ history`, the active one marked),
  where `body(name)` is, with `lines = component.page(name)`:
  - `Drawing(Rows.of(lines), y=scroll)` for the active page (`name == page`), and
    `Drawing(Rows.of(lines))` for the others (y 0), when `lines` is not empty
    (Buffer's `Rows`; Drawing's overflow marks on: `↓N more` and `↑N` show where the
    page runs past the pane, so nothing is cut silently);
  - `Paragraph(EMPTY, role="muted")` when it is, `EMPTY == "nothing yet"`.
  No body carries an id.

With `actions` (a mapping from every page name to an action tag, below):
`Block((summary, radios, body(page)), title=component.key, kind="pane", id=k +
("inspector",))`, every other Block field its default (Column layout), where
`summary` is as above, `body(page)` is the active page's body as above
(`Drawing(Rows.of(lines), y=scroll)`, or the muted EMPTY Paragraph; no id; its `size` the default, `Fill(1)`: it takes the
rows left), and:
- `radios == Block(tuple(Button(name, kind="radio", on=(name == page), size=Auto(),
  id=actions[name]) for name in PAGES), border=None, surface=False, size=Fixed(1),
  layout=Row(gap=1), id=k + ("pages",))` (Widgets' Block and Button, Layout's
  `Row`, `Auto` and `Fixed`), every other field its default (no title, no padding):
  one row, the radios left to right in `PAGES` order, each its natural width (Button's
  `measure("x")`, its mark cell included: `1 + 4 + width(name)`) with one ground cell
  between each two, the rest of the row ground (`justify="start"`). The whole row
  needs 59 cells (`10 + 12 + 11 + 10 + 12 + 4`); narrower, Solver's short case
  shrinks the `Auto` radios in proportion and each Button cuts its label as Button
  fits (`(●) bri…`), never wrapping. Its 59 cells, from the content's left edge
  (builtin theme, page `"suite"`), read
      ` ( ) brief  ( ) binding  ( ) recipe  (●) suite  ( ) history`
  each radio's blank mark cell before its face, so two blanks show between faces
  (the gap and the next mark cell). `surface=False`: the row keeps the pane's
  ground level (not a nested surface); `border=None`: no chrome, so its content
  rect is its one row. It is still a Block (`pane = True`): a radio holding the
  focus makes this row, not the inspector Block, its nearest pane (the row's ground
  lifts; it has no border to show it). Its `kind` stays the default `"block"`: it
  is the pane's page row, not a tiled pane (no border, no surface, one row), so
  no pane pattern (R3's `frame.pane.<edge>`) is meant for it.
- The page Tabs and its Tab ids are absent: the radios are the page row, and only
  the active page's body is in the tree.

`actions`: `None`, or a mapping whose keys are exactly `PAGES` (each page once; any
order, the radios always in `PAGES` order) and whose every value is an action tag: a
3-tuple `(owner, "action", a)`, `owner` a non-empty `str`, the middle item the `str`
`"action"`, `a` any hashable value (Input's key hint tag, the shape its router knows
by its shape alone). The tags are the app's: they need not differ, and Views never
reads `a`. Checked after `component`, `page` and `scroll`: first the mapping, then
its keys, then each value in `PAGES` order.

`views(component, page="brief", scroll=0, *, actions=None) -> dict`: `{"inspector":
inspector(component, page, scroll, actions=actions)}`. The default tree (`tree() ->
SplitTree`): `SplitTree(Pane("inspector"))` (Layout's). The titles
(`titles(component) -> dict`): `{"inspector": component.key}`.

Status tones: `TONES` maps every {Component} status to the Theme state its status row
is drawn in: `"planned"`: `None`, `"building"`: `"active"`, `"built"`: `None`,
`"stale"`: `"emphasised"`, `"rebuilding"`: `"active"`, `"removed"`: `"muted"`,
`"pruning"`: `"active"`. The keys are exactly Board's `COMPONENT_STATES`.

Laws (each a property a test can loop over components, pages, scrolls, sizes and
contexts):
- pure: equal arguments give equal results, for `inspector`, `views`, `tree` and
  `titles`; nothing is read but the arguments.
- unchanged: with `actions=None` (given or defaulted), `inspector(c, page, scroll)`
  and `views(c, page, scroll)` give nodes equal to those of the code at commit
  8497c77 (loaded by git at test time, `tests/_gitref.py`, never a copy), `kind`
  aside (R2: the inspector Block's `kind="pane"` is left out of the comparison, the
  old Block having none), and their
  frames (Paint's `frame(Tiled(tree(), views(c, page, scroll), titles(c)), (w, h),
  ctx)`) are cell for cell equal to that commit's, hits included, at every size and
  context the frames law loops over; so is the package's `view(board, ("inspector",
  key), page=page, scroll=scroll)`.
- ids: the ids carried in `views(c, page, scroll)` (every node reached through
  `children`, and every `Tab` of the Tabs, whose bodies included) are exactly `{k +
  ("inspector",), k + ("pages",)} | {k + ("page", name) for name in PAGES}`; in
  `views(c, page, scroll, actions=m)` exactly `{k + ("inspector",), k + ("pages",)} |
  set(m.values())`.
- page: the Tabs' `active` is `PAGES.index(page)`, so its `children` are the body of
  `page` alone; changing `page` or `scroll` changes nothing else in the tree but the
  Tabs' `active` and the active Drawing's `y`. With `actions`: changing `page` changes
  only which radio is `on` (exactly the one named `page`) and the body (the third
  child); changing `scroll` only the body's `y`.
- routed: with `actions=m` and a Bindings table holding a binding whose action is
  `a` (unscoped, in the default mode, not masked: one `hints` shows), and `m[name]
  == (owner, "action", a)`, a left "press" on any cell of that radio's control in a
  painted frame (the hits of `frame(Tiled(tree(), views(c, page, scroll,
  actions=m), titles(c)), (w, h), ctx)` at a size where the radio's cells show)
  makes Input's `route` give, after its `Pointer`, `Fire(a, ...)` with the table's
  own binding (the router's step 4: the innermost hit is the radio's, tagged `m[name]`).
  The click fires the app's binding; no app code runs between the press and the
  `Fire`, and the page it names is the app's to show.
- tiles: `set(views(c)) == set(ids(tree())) == set(titles(c)) == {"inspector"}`.
- kinds (R2): the inspector Block is of kind `"pane"`, the radios' row `"block"`;
  the frames equal 74f1f6a's (Views' kind-inert law).
- frames: for every size `(w, h)`, `1 <= w <= 120`, `1 <= h <= 40`, Paint's
  `frame(Tiled(tree(), views(c, page, scroll, actions=m), titles(c)), (w, h), ctx)`
  never raises, for every valid {Component}, every page, every `scroll >= 0` (a
  scroll past the page's end shows Drawing's `↑N` marks, never an error) and `m`
  both `None` and a valid map, the builtin theme at every depth.
- legible: with colour off (Caps depth 0), the status row's word is drawn whenever
  the summary's second row shows whole, and a status with a tone shows its state's
  mark in that row's last leader cell; the active page reads by Tabs' active mark
  (`●`, `›` when the Tabs is focused) and bold, as Tabs draws it. With `actions`, the
  shown page's radio reads `(●) <page>` and every other `( ) <name>` (a radio's
  face whole), by the charset's control tokens as Button draws a radio
  (`control.radio` the on glyph: `●` in the unicode charset, its ASCII form in the
  ASCII one; the parentheses in role `control.frame`, the glyph in `control.on`,
  W1a), so the page shown reads without colour.

Inputs: `component` a Board {Component}; `page` a `str` of `PAGES`; `scroll` an
  `int >= 0`, the active page's first row shown; `actions` `None` or the app's map
  from page name to action tag (above).
Outputs: widget nodes (Widgets' Block, PropertyList, Tabs, Button, Drawing,
  Paragraph); a `dict` by pane id; a Layout `SplitTree`; a `dict` of titles.
Errors: `TypeError` when `component` is not a Board `Component` (`"component must be a
  Component, got <type name>"`), `page` is not a `str`, or `scroll` is not an `int` (a
  `bool` refused); `ValueError` when `page` is not one of `PAGES` (`"page must be one
  of brief, binding, recipe, suite, history, got 'x'"`) or `scroll < 0`. For
  `actions`: `TypeError` when it is neither `None` nor a mapping (`"actions must be a
  mapping or None, got list"`), or a value is not an action tag (`"actions['suite']
  must be an action tag (owner, 'action', a), got ('app', 'go')"`: the key and the
  value by `repr`; a non-empty `str` owner, the `str` `"action"` and a hashable `a`
  are each required, an unhashable `a` refused here, not by Button); `ValueError`
  when its keys are not exactly `PAGES` (`"actions and PAGES differ: missing
  ['history'], extra ['notes']"`, each list sorted by `repr` so keys of any type
  sort, either list possibly `[]`).
Effects: none.

Usage:
    from cure.draw.views.board import Component
    from cure.draw.views import inspector
    c = Component("Views/Inspector", status="stale", brief=("one component", "five pages"))
    node = inspector.inspector(c, page="suite")
    node.title, node.id               # ("Views/Inspector", ("inspector", "Views/Inspector", "inspector"))
    node.children[1].active           # 3
    inspector.inspector(c, page="notes")   # ValueError: page must be one of brief, ...
    m = {name: ("console", "action", ("page", name)) for name in inspector.PAGES}
    node = inspector.inspector(c, page="suite", actions=m)
    node.children[1].id               # ("inspector", "Views/Inspector", "pages")
    [b.on for b in node.children[1].children]   # [False, False, False, True, False]
    node.children[1].children[3].id   # ("console", "action", ("page", "suite"))
"""

from collections.abc import Mapping

from cure.core.buffer import Rows
from cure.draw.layout import Auto, Fixed, Row, SplitTree
from cure.draw.layout import Pane as Tile
from cure.draw.widgets import (Block, Button, Drawing, Item, Paragraph, PropertyList, Tab,
                               Tabs)

from .board import PAGES, Component

EMPTY = "nothing yet"
"""What an empty page says."""

TONES = {"planned": None, "building": "active", "built": None, "stale": "emphasised",
         "rebuilding": "active", "removed": "muted", "pruning": "active"}
"""A component status's Theme state (its status row's `state`), or None."""


def key(component: Component) -> tuple:
    """The tab's key, `("inspector", component.key)`: every node id starts with it."""
    _check(component)
    return ("inspector", component.key)


def inspector(component: Component, page: str = "brief", scroll: int = 0, *,
              actions: "Mapping | None" = None) -> Block:
    """The inspector pane: summary over the pages' Tabs, or radios with `actions`."""
    k = key(component)
    _state(page, scroll)
    _actions(actions)
    summary = PropertyList((Item("kind", component.kind),
                            Item("status", component.status, TONES[component.status]),
                            Item("builder", component.builder or "none")), size=Fixed(3))
    if actions is not None:
        # the page row as radios, each hit tagged with the app's own action tag
        radios = Block(tuple(Button(name, kind="radio", on=(name == page), size=Auto(),
                                    id=actions[name]) for name in PAGES),
                       border=None, surface=False, size=Fixed(1), layout=Row(gap=1),
                       id=k + ("pages",))
        return Block((summary, radios, _body(component.page(page), scroll)),
                     title=component.key, kind="pane", id=k + ("inspector",))
    pages = Tabs(tuple(Tab(name, _body(component.page(name), scroll if name == page else 0),
                           id=k + ("page", name)) for name in PAGES),
                 active=PAGES.index(page), id=k + ("pages",))
    return Block((summary, pages), title=component.key, kind="pane", id=k + ("inspector",))


def views(component: Component, page: str = "brief", scroll: int = 0, *,
          actions: "Mapping | None" = None) -> dict:
    """The tab's panes by id: `{"inspector": inspector(component, page, scroll, ...)}`."""
    return {"inspector": inspector(component, page, scroll, actions=actions)}


def tree() -> SplitTree:
    """The tab's default split tree: the one pane, `SplitTree(Pane("inspector"))`."""
    return SplitTree(Tile("inspector"))


def titles(component: Component) -> dict:
    """The pane's title: `{"inspector": component.key}`."""
    _check(component)
    return {"inspector": component.key}


def _body(lines: tuple, y: int):
    """A page's body: its lines as a Drawing scrolled to `y`, or the muted EMPTY."""
    if not lines:
        return Paragraph(EMPTY, role="muted")
    return Drawing(Rows.of(lines), y=y)


def _check(component: object) -> None:
    """Refuse anything but a Board Component."""
    if not isinstance(component, Component):
        raise TypeError(f"component must be a Component, got {type(component).__name__}")


def _state(page: object, scroll: object) -> None:
    """Check the app's page state: a page of PAGES and a scroll int >= 0."""
    if not isinstance(page, str):
        raise TypeError(f"page must be a str, got {type(page).__name__}")
    if page not in PAGES:
        raise ValueError(f"page must be one of {', '.join(PAGES)}, got {page!r}")
    if not isinstance(scroll, int) or isinstance(scroll, bool):
        raise TypeError(f"scroll must be an int, got {type(scroll).__name__}")
    if scroll < 0:
        raise ValueError(f"scroll must be >= 0, got {scroll}")


def _actions(actions: object) -> None:
    """Check the app's page -> action tag map: a mapping, keys PAGES, then each value."""
    if actions is None:
        return
    if not isinstance(actions, Mapping):
        raise TypeError(f"actions must be a mapping or None, got {type(actions).__name__}")
    missing = sorted((name for name in PAGES if name not in actions), key=repr)
    extra = sorted((name for name in actions if name not in PAGES), key=repr)
    if missing or extra:
        raise ValueError(f"actions and PAGES differ: missing {missing}, extra {extra}")
    for name in PAGES:
        if not _tag(actions[name]):
            raise TypeError(f"actions[{name!r}] must be an action tag (owner, 'action', a), "
                            f"got {actions[name]!r}")


def _tag(value: object) -> bool:
    """An action tag: `(owner, "action", a)`, a non-empty str owner and a hashable a."""
    if not (isinstance(value, tuple) and len(value) == 3):
        return False
    owner, middle, a = value
    if not (isinstance(owner, str) and owner and isinstance(middle, str) and middle == "action"):
        return False
    try:
        hash(a)
    except TypeError:
        return False
    return True
