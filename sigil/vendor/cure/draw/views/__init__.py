"""[Views]: ready-made views: construct's console tabs as node trees from plain data.

Kind: system (the expansion of [Views] in Draw); pure. Its parts: the data, {Board}
(`board/`: Task, Builder, Component, Entry, Agent, SpecDoc, Notice), one tab each:
[BuilderTab] (`buildertab.py`), [Inspector] (`inspector.py`), [OrchestratorTab]
(`orchestratortab/`) and [OverviewTab] (`overviewtab/`), and the board's notices
strip, [Notices] (`notices.py`, F14: drawn on every tab, imported by this package
only). Names follow construct's spec (its Panes, OrchestratorTab and OverviewTab
systems).

What a view is. A pure function from {Board} parts (and the app's own state for that
tab: the active page, a scroll) to widget nodes: it composes Widgets' existing node
kinds (Block, Tabs, Pane, PropertyList, Paragraph, Drawing, Table, Tree, ...), lays a
DAG out through Graph and a split tree through Layout, and paints no cell itself
(Paint paints the nodes). It reads no file, no clock and no environment, spawns
nothing, keeps no state, and imports no app: construct depends on cure, never the
other way.

The kinds of its boxes (R2). Every Block a view builds as a tab's pane is of kind
`"pane"` (Block's `kind`, the name a theme's edge patterns go by from R3,
`frame.pane.<edge>`), and every Overlay a view builds would be of kind `"dialog"`;
a Block inside a pane that is no pane keeps the default `"block"`. Today:
- `"pane"`: BuilderTab's `"terminal"` and `"info"`; Inspector's `"inspector"`;
  OrchestratorTab's `"agent"`, `"spec"` and `"view"`; OverviewTab's `"dag"`,
  `"tasks"`, `"builders"`, `"minimap"`, `"files"`, and every builder's cell in
  BuilderGrid (a live terminal, framed and titled, the focus pane while its screen
  has the keys: a pane in its own right, drawn as BuilderTab's terminal is);
- `"block"`: Inspector's page row of radios (with `actions`): a borderless,
  surfaceless one-row Block, the pane's row and not a pane;
- `"dialog"`: none yet: Views builds no Overlay today. Any it builds takes
  `kind="dialog"`.
Each module states the kind in its nodes' expressions (`Block(..., kind="pane",
...)`). This moves Views' public node values
(each tab's `views`, hence `TabView` and `view`): construct pins them; the move was
approved by the sigil session (round 7, Q2).

The patterns its boxes take (R3b). Nothing in Views' code changes for them: every
`"pane"` Block above draws a theme's `frame.pane.<edge>` patterns (and
`frame.pane.<weight>.<edge>` first, so a focused pane's `heavy` look may have its
own), every `"dialog"` Overlay would draw `frame.dialog.*`, and the `"block"` row
`frame.block.*`, through Block's edge runs (Block's The edges: the top and bottom
rows own their corners, the sides the rows between; the title moves in only past a
start or end wider than the corner; chrome and measure untouched, so no pane's
content rect moves). Views passes no theme and no charset of its own: the patterns
come from the context the app paints with. With none declared for those kinds (the
builtin, every shelf theme before R4's `wire`), every frame of every tab is cell for
cell commit 73c003c's (Block's `base_unchanged`), and Views' and Board's public
values, hence their pinned hashes, are untouched by R3b.

Trust. Views adds no trust boundary. Live terminals (the orchestrator's agent, a
builder's) reach it only as screens inside {Board}, Buffer {Grid}s construct already
has: construct owns the ptys and the sigil process (Embed and Vt, on its side), and
a pane's program reaches the terminal only as cells cure emits itself. Views never
starts, reads or writes a process, and every string in {Board} (a path, an env
value, a page line) is drawn as text through Text and Buffer, never sent as bytes.

What a tab returns: a `TabView`.
- `TabView(views, tree, titles=None, strip=None)`, a frozen dataclass:
  - `views`: a mapping from pane id (a non-empty `str`) to the widget node that pane
    shows (any value with every attribute of Widgets' `PROTOCOL`), stored as a new
    `dict` in the order given (not to be mutated);
  - `tree`: the tab's default Layout `SplitTree`, whose pane ids are exactly the
    keys of `views` (Layout's `ids(tree)`, as a set);
  - `titles`: a mapping from pane id to its title, a `str` or a Text {Line}, every
    key one of `views`' (`None` is stored as `{}`), stored as a new `dict`;
  - `strip` (F14, the last field): `None` (no notices) or a node with every
    `PROTOCOL` attribute, the board's notices strip ([Notices]' `strip`). It is not
    a pane: `views` and `tree` never name it.
  The app draws it with Paint's Tiled: `frame(Tiled(tab.tree, tab.views,
  tab.titles), size, ctx)`. The tree is only the default: construct keeps a tree per
  tab per session (dragged, zoomed, kept across detach), starting from `tab.tree`,
  and draws `Tiled(kept, tab.views, tab.titles)` (Views never imports Paint).
  The strip, with notices: in the tab's area `(w, h)`, with strip height `s` (its
  `measure("y")`, `tab.strip.measure("y", h, ctx)`; `s` is 0 when `strip is None`),
  the body is `Tiled(tree, views, titles)` in rows `[0, h - s)` and the strip is
  painted at `(w, s)` in rows `[h - s, h)`, full width (construct's own bottom rows
  are below both, as before). Without notices the tab is drawn exactly as before F14.
  Equality is field by field (the dicts by `==`); a TabView is unhashable
  (`__hash__ = None`: its nodes may hold Grids).
  Errors: `TypeError` when `views` or `titles` is not a mapping (`titles` may be
  `None`), a pane id is not a `str`, a view lacks a `PROTOCOL` attribute (`"view
  'info' lacks 'paint'"`, the first missing in `PROTOCOL`'s order), a title is
  neither a `str` nor a `Line`, or `tree` is not a `SplitTree`; `ValueError` when a
  pane id is `""`, the tree's pane ids and the views' keys differ (`"views and tree
  differ: missing ['a'], extra ['b']"`, each list sorted), or a title names no view
  (`"title for unknown pane 'c'"`); `TypeError` when `strip` is neither `None` nor
  a node (`"strip lacks 'paint'"`, the first missing in `PROTOCOL`'s order).

The tab protocol. Each tab provides its parts as plain functions, and `view` builds
the `TabView` from them (so no tab module imports this package, and none imports
another tab):
- `views(<its parts>, <its state>) -> dict`: pane id -> node;
- `tree(...) -> SplitTree`: the default tree over those ids;
- `titles(<its parts>) -> dict`: pane id -> title;
- `key(<its part>) -> tuple`: the tab's key, the prefix of every node id it gives
  (each tab states the ids it gives, part by part).
X2 and X3 follow it in their packages, reading {Board} parts by attribute (their
import grants do not include `board/`).

The boundary op: `view` (`(Construct) -> [Views] : view({Board}) => {TabView}`: a tab
as a {TabView}, its panes' nodes by id, the default tree and the titles; and
`[Views] -> [Widgets] : view({Fields}) => {Node}`: the nodes it holds are Widgets'
node kinds built from the board's fields).
- `view(board, tab, *, page="brief", scroll=0, actions=None, spec_scroll=None,
  view_at=(0, 0), charset=None, task=None, entry=None, scrolls=None, size=None,
  kept=None, lanes=False) -> TabView`: the tab named `tab` of `board`:
  - `("builder", id)`: `TabView(buildertab.views(b), buildertab.tree(),
    buildertab.titles(b))` with `b = board.builder(id)`;
  - `("inspector", key)`: `TabView(inspector.views(c, page, scroll,
    actions=actions), inspector.tree(), inspector.titles(c))` with `c =
    board.component(key)` (with `actions=None`, today's inspector tab, node for node
    and frame for frame: Inspector's unchanged law);
  - `"orchestrator"`: `TabView(orchestratortab.views(board.agent, board.spec,
    spec_scroll=spec_scroll, view_at=view_at), orchestratortab.tree(),
    orchestratortab.titles(board.spec))`;
  - `"overview"`: `TabView(overviewtab.views(board, charset, task=task,
    entry=entry, scrolls=scrolls, size=size, kept=kept, lanes=lanes),
    overviewtab.tree(), overviewtab.titles(board))`;
  and every tab, each of the four, with `strip=notices.strip(board.notices)` (the
  board's notices, the same strip on every tab; `None` without notices), its other
  fields unchanged.
  Each tab's state is its own keywords, checked by that tab's `views`, so given for
  another tab they are not checked (and change nothing): `page`, `scroll` and
  `actions` (the app's map from page name to action tag `(owner, "action", a)`, or
  `None`: with it the page row is radios whose clicks fire the app's bindings) the
  inspector's; `spec_scroll` (SpecPane's TextInput scroll) and `view_at` (SpecView's
  viewport) the orchestrator's; `charset` (the frame's `ctx.charset`: the overview's
  DAG and minimap glyphs; the overview refuses `None`), `task` (the selected task
  id), `entry` (FileTree's cursor path), `scrolls` (per pane: `"dag"` and
  `"minimap"` an `(x, y)`, `"tasks"` and `"files"` an int), `size` (the tab's area
  `(w, h)`), `kept` (the app's kept SplitTree, for BuilderGrid's room) and `lanes`
  (a `bool`, `False` by default: DagView's compact lanes mode, one row per task;
  absent, the layered view as before) the overview's.
  The overview's schedule extent, for the app's pan and clamp: `dagview.extent(
  tv.views["dag"])` (OverviewTab's `dagview`), the DAG Drawing's `extent` found by its
  id, `None` without tasks.
- Constants: `TABS = ("orchestrator", "overview")`, the board-wide tabs;
  `KINDS = ("builder", "inspector")`, the kinds of per-part tab, a tab being
  `(kind, id)`.

Invariant: pure_view — the same {Board}, tab and state give an equal TabView (and so,
  through Paint, the same frame at the same size and context); `view` reads nothing
  but its arguments: no I/O, no clock, no process, no app import.

Laws (a test can loop over them):
- pure_view, above: `view(b, t, **s) == view(b, t, **s)` for equal boards.
- tiles: `set(view(b, t).views) == set(ids(view(b, t).tree))` (TabView's own check).
- frames: every tab's laws (`buildertab`, `inspector`, `orchestratortab`,
  `overviewtab`): a frame of the result at every size `1..120 x 1..40` never raises.
- kinds (R2): every Block and Overlay reached through `children` in `view(b, t,
  **s).views` has the kind the list above gives it (by its id); no other kind.
- kind-inert (R2): for every board, tab, state, size and context, the frame of
  `view(b, t, **s)` (cells, hits, cursor, `tiling`, `places`) equals that of the
  code at 74f1f6a (loaded through `tests/_gitref.py` at test time, never a copy):
  the kind is inert until R3 (Block's `kind-inert`). Only the node trees differ,
  and only by the Blocks' kinds: with `kind` left out of every Block and Overlay,
  the trees equal 74f1f6a's field for field. Each tab's own laws that compare its
  nodes with an older commit's (`unchanged`, `note-none-unchanged`) compare them so,
  `kind` aside; the frames they compare are unchanged.

Errors (`view`): `TypeError` when `board` is not a `Board`, or `tab` is neither a `str`
  nor a `tuple` `(kind, id)` of two `str`; `ValueError` when a `str` tab is not one of
  `TABS` or a pair's kind is not one of `KINDS` (`"tab must be one of orchestrator,
  overview, or (builder|inspector, id), got 'x'"`); `KeyError` (Board's lookup) when
  no builder or component has that id; the tab's own errors (its keywords', and its
  parts' as it reads them) pass through.
Effects: none.

Re-exports: `Board`, `Task`, `Builder`, `Component`, `Entry`, `Agent`, `SpecDoc`,
`Notice` and `TASK_KINDS`, `TASK_STATES`, `BUILDER_STATES`, `COMPONENT_KINDS`,
`COMPONENT_STATES`, `PAGES`, `NOTICE_ROLES` (from `board`); the tab modules
`buildertab`, `inspector`, `orchestratortab` and `overviewtab`, and `notices`.

Usage:
    from cure.core.buffer import Grid
    from cure.draw import Tiled, frame
    from cure.draw.context import Context
    from cure.draw.theme import builtin
    from cure.draw.views import Board, Builder, view
    board = Board(builders=(Builder("b1", task="X1", status="working", screen=Grid(80, 24)),))
    tab = view(board, ("builder", "b1"))
    tuple(tab.views)                  # ("terminal", "info")
    f = frame(Tiled(tab.tree, tab.views, tab.titles), (100, 30), Context.of(builtin()))
    view(board, ("builder", "b9"))    # KeyError: 'b9'
"""

from collections.abc import Mapping
from dataclasses import dataclass

from cure.core.text import Line
from cure.draw.layout import SplitTree, ids
from cure.draw.widgets import PROTOCOL

from . import buildertab, inspector, notices, orchestratortab, overviewtab
from .board import (BUILDER_STATES, COMPONENT_KINDS, COMPONENT_STATES, NOTICE_ROLES, PAGES,
                    TASK_KINDS, TASK_STATES, Agent, Board, Builder, Component, Entry, Notice,
                    SpecDoc, Task)

TABS = ("orchestrator", "overview")
"""The board-wide tabs, by name."""

KINDS = ("builder", "inspector")
"""The per-part tabs' kinds: a tab `(kind, id)`."""


@dataclass(frozen=True)
class TabView:
    """A tab: its panes' nodes by id, its default split tree, its titles (see the module)."""

    views: Mapping
    tree: SplitTree
    titles: "Mapping | None" = None
    strip: object = None

    __hash__ = None  # its nodes may hold Grids: unhashable

    def __post_init__(self) -> None:
        """Check the fields and store the mappings as new dicts (see the module)."""
        if not isinstance(self.views, Mapping):
            raise TypeError(f"views must be a mapping, got {type(self.views).__name__}")
        titles = {} if self.titles is None else self.titles
        if not isinstance(titles, Mapping):
            raise TypeError(f"titles must be a mapping or None, got {type(titles).__name__}")
        views = dict(self.views)
        for pane, node in views.items():
            if not isinstance(pane, str):
                raise TypeError(f"pane ids must be str, got {type(pane).__name__}")
            if pane == "":
                raise ValueError("a pane id must not be ''")
            for name in PROTOCOL:
                if not hasattr(node, name):
                    raise TypeError(f"view {pane!r} lacks {name!r}")
        titles = dict(titles)
        for pane, title in titles.items():
            if not isinstance(title, (str, Line)):
                raise TypeError(f"title for {pane!r} must be a str or a Line, "
                                f"got {type(title).__name__}")
        if not isinstance(self.tree, SplitTree):
            raise TypeError(f"tree must be a SplitTree, got {type(self.tree).__name__}")
        tiles = set(ids(self.tree))
        missing, extra = sorted(tiles - set(views)), sorted(set(views) - tiles)
        if missing or extra:
            raise ValueError(f"views and tree differ: missing {missing}, extra {extra}")
        for pane in titles:
            if pane not in views:
                raise ValueError(f"title for unknown pane {pane!r}")
        if self.strip is not None:
            for name in PROTOCOL:
                if not hasattr(self.strip, name):
                    raise TypeError(f"strip lacks {name!r}")
        object.__setattr__(self, "views", views)
        object.__setattr__(self, "titles", titles)


def view(board: Board, tab: "str | tuple[str, str]", *, page: str = "brief",
         scroll: int = 0, actions: object = None,
         spec_scroll: "tuple[int, int] | None" = None,
         view_at: "tuple[int, int]" = (0, 0), charset: object = None,
         task: "str | None" = None, entry: "str | None" = None,
         scrolls: object = None, size: "tuple[int, int] | None" = None,
         kept: object = None, lanes: bool = False) -> TabView:
    """[Views]' boundary op: the tab `tab` of `board`, as a TabView (see the module)."""
    if not isinstance(board, Board):
        raise TypeError(f"board must be a Board, got {type(board).__name__}")
    strip = notices.strip(board.notices)
    if isinstance(tab, str):
        if tab == "orchestrator":
            return TabView(orchestratortab.views(board.agent, board.spec,
                                                 spec_scroll=spec_scroll, view_at=view_at),
                           orchestratortab.tree(), orchestratortab.titles(board.spec), strip)
        if tab == "overview":
            return TabView(overviewtab.views(board, charset, task=task, entry=entry,
                                             scrolls=scrolls, size=size, kept=kept,
                                             lanes=lanes),
                           overviewtab.tree(), overviewtab.titles(board), strip)
        raise ValueError(_unknown(tab))
    if not (isinstance(tab, tuple) and len(tab) == 2 and all(isinstance(s, str) for s in tab)):
        raise TypeError(f"tab must be a str or a (kind, id) pair of str, got {type(tab).__name__}")
    kind, id = tab
    if kind == "builder":
        b = board.builder(id)
        return TabView(buildertab.views(b), buildertab.tree(), buildertab.titles(b), strip)
    if kind == "inspector":
        c = board.component(id)
        return TabView(inspector.views(c, page, scroll, actions=actions),
                       inspector.tree(), inspector.titles(c), strip)
    raise ValueError(_unknown(tab))


def _unknown(tab: object) -> str:
    """The message for a tab that names no tab."""
    return f"tab must be one of {', '.join(TABS)}, or ({'|'.join(KINDS)}, id), got {tab!r}"
