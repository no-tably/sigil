"""[OverviewTab]: the global view of the pieces being worked on.

Kind: system (the composition tree rooted at [OverviewTab] in Views); pure functions
from {Board} parts and the app's state for this tab to widget nodes. It follows the
Views package's tab protocol (`views`, `tree`, `titles`, `key`; the package's `view`
builds the `TabView` from them). Its parts, one module each: [DagView]
(`dagview.py`), [Tasks] (`tasks.py`), [FileTree] (`filetree.py`), [Minimap]
(`minimap.py`), [BuilderGrid] (`buildergrid.py`). It imports Graph, Layout, Widgets
and Core only (its grants): never `board/`, another tab, the Views package, Theme or
Paint. {Board} parts arrive as arguments and are read by attribute (`board.tasks`,
`board.builders`, `board.components`, `board.entries`; each part's fields as Board
names them). It composes existing widget nodes only (Block, Drawing, Table, Tree,
Pane, Paragraph, Gauge, Spinner) and paints no cell itself: a DAG's rows come from
Graph's `lay`, a minimap's rows are runs of the charset's block glyphs over Graph's
Blocks, and Paint paints the nodes.

The charset. Graph draws a DAG with a {Charset} (box-drawing glyphs, ASCII when the
terminal has no Unicode) and the minimap's cells are its block glyphs, so this tab
takes one: the frame's own, `ctx.charset` (a Theme {Charset}, or any object with
`glyph(token) -> str` and `plots`, as Canvas reads it). It is an argument, not an
import (Theme is not among the grants). The same {Board}, state and charset give the
same nodes (Views' pure_view: "the same {Board}, size and context").

The tab's key: `key(board) == ("overview",)`, written `k`. Every id a node of this
tab carries, and every item id and region tag, is `k + (part, ...)`, as listed; no
other node carries one.

The panes (`views(board, charset, *, task=None, entry=None, scrolls=None, size=None,
kept=None, lanes=False) -> dict`), in `PANES`' order, each a Widgets `Block` of kind `"pane"`
(R2) with every field not named its default:
- `"dag"`: `dagview.dagview(board.tasks, charset, task=task, scroll=s["dag"],
  lanes=lanes)`;
- `"tasks"`: `tasks.tasks(board.tasks, task=task, offset=s["tasks"])`;
- `"builders"`: `buildergrid.buildergrid(board.builders, size=size, kept=K)`, `K`
  being `kept` when it is not `None`, else `tree()`;
- `"minimap"`: `minimap.minimap(board.components, charset, scroll=s["minimap"])`;
- `"files"`: `filetree.filetree(board.entries, entry=entry, offset=s["files"])`;
where `s` is `scrolls` with every missing key at its default: `(0, 0)` for `"dag"`
and `"minimap"`, `0` for `"tasks"` and `"files"`.

The schedule's content extent, for the app's pan and clamp (round 16): the `"dag"`
pane's Drawing carries it as its `extent` (Graph's `lay` width and height, or the
lanes mode's own), and `dagview.extent(node)` finds it by the Drawing's id
(`dagview.VIEW`) under any node given (the `"dag"` pane, or the tab's panes in a
Block), `None` when there are no tasks; the app never scans the rows for it.

The app's state (keyword only, each with its default):
- `task`: `None` or a `str`, the selected task's id (DagView marks its box, Tasks
  selects its row and puts its cursor there). An id that names no task of the board
  selects none (construct's model may lag a frame), as Board's references do.
- `entry`: `None` or a `str`, the FileTree's cursor: the path of the entry it is on;
  a path that names no entry puts it nowhere.
- `scrolls`: `None` (every default) or a mapping from a pane id of `SCROLLS` to its
  scroll: `"dag"`, `"minimap"`: the Drawing's `(x, y)`, a `tuple` of two ints
  (any sign, as Drawing's offset); `"tasks"`, `"files"`: the collection's `offset`,
  an int `>= 0`.
- `size`: `None` or `(w, h)`, a `tuple` of two ints `>= 0`: the area the tab is
  drawn in (the frame's size, as the app passes `frame(Tiled(...), size, ctx)`).
  BuilderGrid finds its own tile in it through Layout's `panes`.
- `kept`: `None` (the default tree, `tree()`) or a Layout `SplitTree`: the tree the
  app keeps for this tab (dragged, zoomed), the one it draws; BuilderGrid reads its
  tile from it. It changes only the builders pane's grid shape.
- `lanes`: a `bool`, `False` by default: the DAG pane's mode, passed to DagView only.
  `True` draws the compact schedule (Graph's `lanes`: one row per task, its lane
  columns, then its label; see `dagview.py`); `False` the layered view, every pane
  as before.
How the Views package passes them: `view(board, "overview", *, charset=None,
task=None, entry=None, scrolls=None, size=None, kept=None, lanes=False)` gives
`TabView(overviewtab.views(board, charset, task=task, entry=entry, scrolls=scrolls,
size=size, kept=kept, lanes=lanes), overviewtab.tree(), overviewtab.titles(board))`. `charset`
has a default there only because `view` serves every tab: for this one `None` is
refused (`TypeError`, below), since a DAG cannot be drawn without glyphs.

The default tree (`tree() -> SplitTree`): `SplitTree(Split("x", (Split("y",
(Pane("dag"), Pane("tasks")), (3, 2)), Pane("builders"), Split("y",
(Pane("minimap"), Pane("files")), (1, 2))), (2, 2, 1)))` (Layout's Splits): the
schedule over its table on the left, the builders' terminals in the middle, the map
over the files on the right. The titles (`titles(board) -> dict`): `TITLES`, a new
dict each call: `{"dag": "schedule", "tasks": "tasks", "builders": "builders",
"minimap": "map", "files": "files"}` (shown only on a Tabs or Stacked bar, should
the app regroup the panes).

The ids, by pane (each module states its own exactly):
- nodes: `k + ("dag",)`, `k + ("dag", "view")`; `k + ("tasks",)`, `k + ("tasks",
  "table")`; `k + ("builders",)`, `k + ("builder", id)`, `k + ("screen", id)`;
  `k + ("minimap",)`, `k + ("minimap", "view")`; `k + ("files",)`, `k + ("files",
  "tree")` (the inner ones only when their pane is not empty);
- items: `k + ("task", id)` (a Tasks row), `k + ("entry", path)` (a FileTree row);
- regions (hit tags a Drawing carries): `k + ("node", id)` (a task's box in the
  DAG), `k + ("component", key)` (a minimap block).
A click's tag says what it names: `("overview", "node" | "task", id)` a task,
`("overview", "entry", path)` an entry, `("overview", "component", key)` a component
(the app opens its sub-hierarchy, an Inspector tab or the next level), `("overview",
"builder" | "screen", id)` a builder (focusing `k + ("screen", id)` sends the
terminal keys, as BuilderTab's).

Laws (each a property a test can loop over boards, states, sizes and contexts):
- pure: `views(b, cs, **s) == views(b, cs, **s)`, and `tree`, `titles`, `key`
  likewise, for equal arguments; nothing is read but the arguments.
- ids: the ids carried in `views(...)` (every node reached through `children`) are
  exactly those listed above for the board's parts, each once; the item ids and
  region tags likewise (one per task, entry, component).
- tiles: `set(views(b, cs)) == set(ids(tree())) == set(titles(b)) == set(PANES)`
  (Layout's `ids`), so the package's `TabView` accepts them.
- kinds (R2): the five pane Blocks and every builder's cell are of kind `"pane"`
  (each module states it); the tab's frames equal 74f1f6a's (Views' kind-inert
  law).
- frames: for every size `(w, h)`, `1 <= w <= 120`, `1 <= h <= 40`, Paint's
  `frame(Tiled(tree(), views(b, ctx.charset, size=(w, h)), titles(b)), (w, h), ctx)`
  returns a Frame (never raises), for every valid {Board} (empty parts included) and
  every valid state, the builtin theme at every depth.
- legible: with colour off (Caps depth 0) every task's state, every builder's
  status (and its phase's progress), a component lit or not and an entry's marks
  still read: as words (the DAG's labels, the table's state column, the builders'
  titles and phase words, the files' marks) or as distinct glyphs (the minimap's,
  a gauge's), never by colour alone; each module states how.
- plus each pane's own laws (its module).

Inputs: `board` a {Board} (read by attribute); `charset` a {Charset}; the state above.
Outputs: a `dict` of widget nodes by pane id; a Layout `SplitTree`; a `dict` of titles;
  the key, a `tuple`.
Errors (`views`, checked in this order, the first raised): `TypeError` when `charset`
  has no callable `glyph` (`"charset must be a Charset (the frame's ctx.charset), got
  NoneType"`), `task` or `entry` is neither `None` nor a `str`, `scrolls` is neither
  `None` nor a mapping, a scroll has the wrong type (`"scroll of 'dag' must be a
  tuple of two ints, got list"`; a `bool` refused), `size` is neither `None` nor a
  `tuple` of two ints, or `kept` is neither `None` nor a `SplitTree`; `ValueError`
  when a `scrolls` key is not one of `SCROLLS` (`"scrolls has no pane 'x': one of
  dag, tasks, minimap, files"`), an offset or a size value is negative. The parts'
  own errors (their modules) pass through, DagView's `lanes` check among them (`"lanes
  must be a bool, got int"`).
Effects: none.

Usage:
    from cure.draw.context import Context
    from cure.draw.theme import builtin
    from cure.draw.views.board import Board, Builder, Task
    from cure.draw.views import overviewtab
    board = Board(tasks=(Task("X1", state="done"), Task("X3", state="running",
                  builder="b2", depends=("X1",))), builders=(Builder("b2", task="X3"),))
    cs = Context.of(builtin()).charset
    v = overviewtab.views(board, cs, task="X3", size=(120, 40))
    tuple(v)                       # ("dag", "tasks", "builders", "minimap", "files")
    v["dag"].id                    # ("overview", "dag")
    overviewtab.views(board, None) # TypeError: charset must be a Charset (the frame's ctx.charset), got NoneType
"""

from collections.abc import Mapping

from cure.draw.layout import Pane as Tile
from cure.draw.layout import Split, SplitTree

from . import buildergrid, dagview, filetree, minimap, tasks

PANES = ("dag", "tasks", "builders", "minimap", "files")
"""The tab's pane ids, in `views`' order."""

SCROLLS = ("dag", "tasks", "minimap", "files")
"""The panes `scrolls` may name, in order."""

TITLES = {"dag": "schedule", "tasks": "tasks", "builders": "builders",
          "minimap": "map", "files": "files"}
"""The panes' titles (`titles` returns a new dict of these)."""

KEY = ("overview",)
"""The tab's key: the prefix of every id it gives."""


def key(board: object) -> tuple:
    """The tab's key, `("overview",)`: every id this tab gives starts with it."""
    return KEY


def views(board: object, charset: object, *, task: "str | None" = None,
          entry: "str | None" = None, scrolls: "Mapping | None" = None,
          size: "tuple[int, int] | None" = None, kept: "SplitTree | None" = None,
          lanes: bool = False) -> dict:
    """The tab's panes by id, in `PANES`' order (see the module)."""
    if not callable(getattr(charset, "glyph", None)):
        raise TypeError("charset must be a Charset (the frame's ctx.charset), got "
                        f"{type(charset).__name__}")
    for name, value in (("task", task), ("entry", entry)):
        if value is not None and not isinstance(value, str):
            raise TypeError(f"{name} must be a str or None, got {type(value).__name__}")
    if scrolls is not None and not isinstance(scrolls, Mapping):
        raise TypeError(f"scrolls must be a mapping or None, got {type(scrolls).__name__}")
    s = {"dag": (0, 0), "tasks": 0, "minimap": (0, 0), "files": 0}
    given = dict(scrolls or {})
    for pane, value in given.items():
        if pane not in s:
            continue
        if isinstance(s[pane], tuple):
            if not (isinstance(value, tuple) and len(value) == 2
                    and all(_is_int(v) for v in value)):
                raise TypeError(f"scroll of {pane!r} must be a tuple of two ints, "
                                f"got {type(value).__name__}")
        elif not _is_int(value):
            raise TypeError(f"scroll of {pane!r} must be an int, got {type(value).__name__}")
    if size is not None and not (isinstance(size, tuple) and len(size) == 2
                                 and all(_is_int(v) for v in size)):
        raise TypeError(f"size must be None or a tuple of two ints, got {type(size).__name__}")
    if kept is not None and not isinstance(kept, SplitTree):
        raise TypeError(f"kept must be None or a SplitTree, got {type(kept).__name__}")
    for pane, value in given.items():
        if pane not in s:
            raise ValueError(f"scrolls has no pane {pane!r}: one of {', '.join(SCROLLS)}")
        if not isinstance(value, tuple) and value < 0:
            raise ValueError(f"the offset of {pane!r} must be >= 0, got {value}")
    if size is not None and min(size) < 0:
        raise ValueError(f"size values must be >= 0, got {size}")
    s.update(given)
    return {
        "dag": dagview.dagview(board.tasks, charset, task=task, scroll=s["dag"], lanes=lanes),
        "tasks": tasks.tasks(board.tasks, task=task, offset=s["tasks"]),
        "builders": buildergrid.buildergrid(board.builders, size=size,
                                            kept=tree() if kept is None else kept),
        "minimap": minimap.minimap(board.components, charset, scroll=s["minimap"]),
        "files": filetree.filetree(board.entries, entry=entry, offset=s["files"]),
    }


def tree() -> SplitTree:
    """The tab's default split tree: schedule over tasks | builders | map over files."""
    return SplitTree(Split("x", (Split("y", (Tile("dag"), Tile("tasks")), (3, 2)),
                                 Tile("builders"),
                                 Split("y", (Tile("minimap"), Tile("files")), (1, 2))),
                           (2, 2, 1)))


def titles(board: object) -> dict:
    """The panes' titles: a new dict of `TITLES`."""
    return dict(TITLES)


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)
