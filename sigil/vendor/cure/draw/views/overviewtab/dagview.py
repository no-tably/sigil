"""[DagView]: the schedule's DAG: ready, held, running, done, failed.

Kind: service (pure functions from Board {Task}s and a {Charset} to a Graph {Dag} and a
widget node; see the OverviewTab package for the tab, its key `k == ("overview",)`
and its ids).

What it does: lays the schedule out as Graph's {Dag}, one node per task and one edge
per `depends` entry, lays it out once with Graph's `lay` (`[DagView] -> [Graph] :
lay({Dag}) => {Laid}`: the rows and each task's rect from one call) and shows the rows
in a Widgets `Drawing` scrolled by the app, with one hit region per task's box, its
rect `lay`'s, so a click names the task. It calls nothing else of Graph's to draw
the layered view: no second layout, no Diagram (it imports `Dag`, `lanes`, `lay` and
`sized` from Graph's face, nothing from `diagram.py`). Each box's label carries the
task's state as a word, so the state reads with colour off; its colour is the theme
role `task.<state>` (an open role: a theme may style it, an unstyled one degrades
to the text's). It paints nothing itself.

The graph (`dag(tasks, charset=None) -> Dag`), for `tasks` a `tuple` of {Task} (the
Board's, in schedule order):
- nodes, in `tasks`' order: `sized(t.id, label(t, t.id, charset))` (Graph's
  `sized`: a box two cells wider than its label, three rows high). Every box is
  sized for its label in the selected form, mark included, so selecting a task
  moves nothing: the layout is the same whichever task is selected (an unselected
  label is drawn in the same box, padded on the right, as Diagram cuts labels with
  `pad=True`).
- edges: `(d, t.id)` for each task `t` in order and each `d` in `t.depends` in
  order (drawn from the task waited on to the task that waits). A cycle in the
  board's `depends` is drawn, not refused: Graph breaks it ([Ranks]' `acyclic`) and
  draws the reversed edge dashed.
The label (`label(t, selected=None, charset=None) -> str`): `f"{t.id} {t.state}"`
(`"X1 running"`); for the selected task (`t.id == selected`) with a charset whose
`glyph("mark.selected")` is not `""`, that glyph and a blank before it (`"• X1
running"`, ASCII `"* X1 running"`).

The pane (`dagview(tasks, charset, *, task=None, scroll=(0, 0), lanes=False) ->
Block`), with `lanes=False` (the default, the layered view):
- with tasks: `Block((Drawing(rows, x=scroll[0], y=scroll[1], regions=regions,
  extent=(laid.width, laid.height), id=VIEW),), title="schedule", kind="pane",
  id=PANE)`, where, with `g =
  dag(tasks, charset)`, `labels = {t.id: label(t, task, charset) for t in
  tasks}` and `styles = {t.id: STYLES[t.state] for t in tasks}`:
  - `laid = lay(g, charset, labels=labels, styles=styles)` (Graph's boundary op,
    called once, every other keyword its default: laid down, boxes, heads on, the
    charset's ellipsis);
  - `rows == laid.rows`;
  - `regions == tuple(Hit(laid.rects[t.id], k + ("node", t.id)) for t in tasks)`
    (Geometry's `Hit`): the rects the boxes are drawn in, from the same layout as
    the rows;
  - Drawing's overflow marks on: a schedule wider or longer than the pane shows the
    ellipsis and `↑N` / `↓N more`, never cut silently.
- with none (`tasks == ()`): `Block((Paragraph(EMPTY, role="muted"),),
  title="schedule", kind="pane", id=PANE)`, `EMPTY == "no tasks yet"` (no Drawing,
  no regions).
- the ids, module constants beside the code that sets them: `PANE == k + ("dag",)`
  (the Block's), `VIEW == k + ("dag", "view")` (the Drawing's).
- the extent: the Drawing is given its content extent, `(laid.width, laid.height)`
  (Graph's `lay` knows it from its Diagram: the widest row and the row count), so
  neither the Drawing nor the app scans the rows for it; the app reads it for its pan
  and clamp. Paint never reads it: every frame is the same as without it.

The lanes mode (`lanes=True`; round 15): a compact schedule, one row per task, as
`git log --graph` draws history in a narrow pane. The app picks it, per view
(OverviewTab's `views(..., lanes=True)`, passed through by Views' `view(board,
"overview", ..., lanes=...)`); absent or `False`, the pane is the layered one above,
frame for frame and hit for hit. With tasks, `L = lanes(dag(tasks, charset))`
(Graph's `lanes`, `[DagView] -> [Graph] : lanes({Dag}) => {Rows}`, its default
order: [Ranks]' `topo`, a cycle broken as in the layered view; the board's schedule
order need not be topological). For each `Row` `r` at index `i`, `t` the task it
names, the row is the Text `Line` (normal form) of:
- the lane columns: for each column `j < L.width`, mask `m = r.cells[j]`: `" "` when
  `m == 0`, else `charset.glyph("border.light." + _PART[m])` (the light junction
  glyph; `_PART` the mask -> part table, private here, equal to Canvas's
  [Junctions]' `PART`: DagView imports no Canvas name and reads the tokens through
  the charset, as Minimap reads `block.full`), unstyled; except column `r.x`, the
  task's own cell: `charset.glyph("mark.active")` (`●`, ASCII `*`) in `STYLES[t.state]`;
- then one blank (unstyled) and `label(t, task, charset)` in `STYLES[t.state]` (the
  state reads by word with colour off; the selected task's carries `mark.selected`).
Hits: `regions == tuple(Hit(Rect(0, i, L.width + 1 + width(label(t, t.id,
charset)), 1), k + ("node", t.id)) for t in tasks)`, `i` the task's row: one per
task, in `tasks`' order (not the rows'), the width the selected form's, so selecting
a task never moves a hit. The pane is the same Block and Drawing as the layered
view's (`rows` the lines above, overflow marks on, the app's `scroll`, the ids
`PANE` and `VIEW`), given its own extent `(L.width + 1 + max(width(label(t, task,
charset)) for t in tasks), len(rows))` (the widths it already computes). Scroll and
follow: DagView never scrolls itself; the app follows the selection by scrolling to
the selected task's row (its hit's `y`), as it follows a box's rect in the layered
view. With no tasks: the same `Paragraph(EMPTY)` pane.

The extent for the app (`extent(node) -> tuple[int, int] | None`, `(Construct) ->
[DagView] : extent({Node}) => {Extent}`): `node` a widget node (a Block, a tab's
panes in a Block, the Drawing itself: anything with `paint`, its `children` walked
depth first, the node given included); the `extent` (a Surfaces {Extent}) of the
first node whose `id == VIEW`, found by id, never by position; `None` when there is
none (no tasks: the pane is a Paragraph). The walk reads only ids and children, never
the rows, so it costs less than one scan of them.

Styles: `STYLES` maps every {Task} state to its theme role: `"ready"`:
`"task.ready"`, `"held"`: `"task.held"`, `"running"`: `"task.running"`, `"done"`:
`"task.done"`, `"failed"`: `"task.failed"`. The keys are exactly Board's
`TASK_STATES`. A colour only: the label's word is the cue.

Laws (each a property a test can loop over task tuples, selections, scrolls, sizes
and contexts):
- pure: equal arguments give equal results (`dag`, `label`, `dagview`); nothing is
  read but the arguments.
- still: the selection changes only labels: `dag(ts, cs)` does not depend on `task`,
  so the boxes, the wires and the regions stay where they are when the selection
  moves; every label fits its box (`width(label(t, s, cs)) <= box width - 2` for
  every `s`).
- once: every task appears exactly once: `[n.id for n in dag(ts).nodes] == [t.id for
  t in ts]`, `len(dag(ts).edges) == sum(len(t.depends) for t in ts)`, and the
  Drawing's regions are one per task, in `ts`' order, each tag `k + ("node", t.id)`.
- drawn: each task's label is drawn whole inside its region's rect (Graph's every
  node is drawn; the box is sized for the label), so a click inside a box hits
  that task.
- ids: the node ids carried are exactly `{PANE, VIEW}` with tasks, `{PANE}` without.
- given-equals-counted: the Drawing's extent equals `(max row width, row count)` of
  its own rows, layered and lanes; `extent(dagview(ts, cs, ...))` is that Drawing's
  extent, `None` without tasks.
- legible: with colour off (Caps depth 0), each task's state is its label's word,
  and the selected task's box shows `mark.selected` before its id.
- scroll: changing `scroll` changes only the Drawing's `x` and `y`; changing `task`
  changes only the rows (the labels), never the regions (in the lanes mode, never
  the lane cells either; there the extent follows the widest label drawn, so a
  selection mark may widen it: the layered boxes are sized for the selected form,
  so its extent never moves).
- lanes: `len(rows) == len(tasks)`, row `i` names `L.rows[i].node`, every label is
  drawn whole after the lane columns; absent or `False`, every result is `==` the
  6e8f0d6 tree's.
- pinned (Views is pinned by construct): DagView's frames and hits equal those at
  ca4f257: for every task tuple, selection, scroll and charset, `dagview(ts, cs,
  task=s, scroll=sc)` here `==` the same call on the ca4f257 tree (loaded from git by
  `tests/_gitref.extract`, never a frozen copy), so the Drawing's rows and regions
  are unchanged, and so is every frame painted from it. Laying out once changes how,
  not what: the rows and rects are the ones the two calls gave.

Inputs: `tasks` a `tuple` of Board {Task} (ids unique, every `depends` entry naming
  one of them: the Board's checks); `charset` a {Charset} (`glyph(token)`; Canvas's
  `plots`; `None` allowed for `dag` and `label`, which then draw no mark);
  `task` / `selected` `None` or a `str` (an id naming no task selects none);
  `scroll` a `tuple` of two ints; `lanes` a `bool`; `extent`'s `node` a widget node.
Outputs: a Graph {Dag}; a `str` label; a Widgets `Block` (of a `Drawing` of {Laid}'s
  rows with a hit per {Laid} rect, or of {Rows}' lines with a hit per row, or a
  `Paragraph`); `extent`: an {Extent} or None.
Errors: `TypeError` when `tasks` is not a `tuple`, `charset` has no callable `glyph`
  (`"charset must be a Charset (the frame's ctx.charset), got NoneType"`), `task` is
  neither `None` nor a `str`, or `scroll` is not a `tuple` of two ints (a `bool`
  refused), or `lanes` is not a `bool` (`"lanes must be a bool, got int"`, checked
  after `scroll`); `extent`: `TypeError` when `node` is not a widget node (no
  `paint`). Graph's own errors cannot arise from a valid {Board} (ids are non-empty
  and unique, no task depends on itself).
Effects: none.

Usage:
    from cure.draw.theme.charset import ASCII, Charset
    from cure.draw.views.board import Task
    from cure.draw.views.overviewtab import dagview
    ts = (Task("X1", state="done"), Task("X3", state="running", depends=("X1",)))
    dagview.label(ts[1])                                  # "X3 running"
    dagview.label(ts[1], "X3", Charset("ascii", ASCII))   # "* X3 running"
    dagview.dag(ts).edges                                 # (("X1", "X3"),)
    dagview.dagview(ts, Charset()).children[0].regions[1].tag   # ("overview", "node", "X3")
    [r.plain for r in dagview.dagview(ts, Charset(), lanes=True).children[0].rows]
        # ["● X1 done", "● X3 running"]
    dagview.extent(dagview.dagview(ts, Charset(), lanes=True))    # Extent(width=12, height=2)
"""

from cure.core.geometry import Hit, Rect
from cure.core.text import Line, Span, width
from cure.draw.graph import Dag, lanes, lay, sized
from cure.draw.widgets import Block, Drawing, Paragraph

KEY = ("overview",)
"""The tab's key (OverviewTab's `k`)."""

PANE = KEY + ("dag",)
"""The pane's id (the Block's): `k + ("dag",)`."""

VIEW = KEY + ("dag", "view")
"""The view's id (the Drawing's): `k + ("dag", "view")`; `extent` finds the Drawing by it."""

EMPTY = "no tasks yet"
"""What the pane says when the board has no tasks."""

STYLES = {"ready": "task.ready", "held": "task.held", "running": "task.running",
          "done": "task.done", "failed": "task.failed"}
"""A task state's theme role (a colour only: the label's word is the cue)."""

_PART = {0: None, 1: "v", 4: "v", 5: "v", 2: "h", 8: "h", 10: "h", 6: "tl", 12: "tr",
         3: "bl", 9: "br", 7: "tee_l", 13: "tee_r", 14: "tee_t", 11: "tee_b", 15: "cross"}
"""A junction mask (N 1, E 2, S 4, W 8) -> its `border.light.<part>` part (Canvas's
[Junctions]' `PART`, kept here: DagView imports no Canvas name)."""


def label(t: object, selected: "str | None" = None, charset: object = None) -> str:
    """A task's box label: `"<id> <state>"`, with `mark.selected` first when selected."""
    text = f"{t.id} {t.state}"
    if charset is not None and selected is not None and t.id == selected:
        mark = _charset(charset).glyph("mark.selected")
        if mark:
            return f"{mark} {text}"
    return text


def dag(tasks: tuple, charset: object = None) -> Dag:
    """The schedule as Graph's {Dag}: a box per task, an edge per `depends` entry."""
    _tasks(tasks)
    if charset is not None:
        _charset(charset)
    nodes = [sized(t.id, label(t, t.id, charset)) for t in tasks]
    edges = [(d, t.id) for t in tasks for d in t.depends]
    return Dag(nodes, edges)


def dagview(tasks: tuple, charset: object, *, task: "str | None" = None,
            scroll: "tuple[int, int]" = (0, 0), lanes: bool = False) -> Block:
    """The DAG pane: Graph's `lay` (or, with `lanes`, its `lanes`) of `dag(tasks)` in a
    scrolled Drawing, a hit per task."""
    _tasks(tasks)
    _charset(charset)
    if task is not None and not isinstance(task, str):
        raise TypeError(f"task must be a str or None, got {type(task).__name__}")
    _scroll(scroll)
    if not isinstance(lanes, bool):
        raise TypeError(f"lanes must be a bool, got {type(lanes).__name__}")
    if not tasks:
        return Block((Paragraph(EMPTY, role="muted"),), title="schedule", kind="pane",
                     id=PANE)
    if lanes:
        rows, regions, size = _lanes(tasks, charset, task)
        view = Drawing(rows, x=scroll[0], y=scroll[1], regions=regions, extent=size, id=VIEW)
        return Block((view,), title="schedule", kind="pane", id=PANE)
    g = dag(tasks, charset)
    labels = {t.id: label(t, task, charset) for t in tasks}
    styles = {t.id: STYLES[t.state] for t in tasks}
    laid = lay(g, charset, labels=labels, styles=styles)
    regions = tuple(Hit(laid.rects[t.id], KEY + ("node", t.id)) for t in tasks)
    view = Drawing(laid.rows, x=scroll[0], y=scroll[1], regions=regions,
                   extent=(laid.width, laid.height), id=VIEW)
    return Block((view,), title="schedule", kind="pane", id=PANE)


def extent(node: object) -> "tuple[int, int] | None":
    """The schedule's content extent, `(width, height)`: the `extent` of the node under
    `node` (itself included, depth first through `children`) whose `id == VIEW`; None
    when there is none (no tasks)."""
    if not callable(getattr(node, "paint", None)):
        raise TypeError(f"node must be a widget node, got {type(node).__name__}")
    view, stack = VIEW, [node]
    while stack:
        n = stack.pop()
        if getattr(n, "id", None) == view:
            return n.extent
        children = getattr(n, "children", None)
        if children:
            stack.extend(reversed(children))
    return None


# --- private ------------------------------------------------------------------------

def _lanes(tasks: tuple, charset: object, task: "str | None") -> tuple:
    """The lanes mode's rows (a Line per Graph `lanes` row), hits (in tasks' order) and
    extent (`L.width + 1 +` the widest label drawn, the row count)."""
    laid = lanes(dag(tasks, charset))
    by = {t.id: t for t in tasks}
    active = charset.glyph("mark.active")
    rows, at, widest = [], {}, 0
    for i, r in enumerate(laid.rows):
        t = by[r.node]
        at[t.id] = i
        role = STYLES[t.state]
        spans = [Span(active, role) if j == r.x
                 else Span(" " if m == 0 else charset.glyph("border.light." + _PART[m]))
                 for j, m in enumerate(r.cells[:laid.width])]
        text = label(t, task, charset)
        widest = max(widest, width(text))
        rows.append(Line.of(*spans, Span(" "), Span(text, role)))
    regions = tuple(Hit(Rect(0, at[t.id], laid.width + 1 + width(label(t, t.id, charset)), 1),
                        KEY + ("node", t.id)) for t in tasks)
    return tuple(rows), regions, (laid.width + 1 + widest, len(rows))


def _tasks(tasks: object) -> None:
    if not isinstance(tasks, tuple):
        raise TypeError(f"tasks must be a tuple, got {type(tasks).__name__}")


def _charset(charset: object) -> object:
    if not callable(getattr(charset, "glyph", None)):
        raise TypeError("charset must be a Charset (the frame's ctx.charset), got "
                        f"{type(charset).__name__}")
    return charset


def _int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _scroll(scroll: object) -> None:
    if not (isinstance(scroll, tuple) and len(scroll) == 2 and all(_int(v) for v in scroll)):
        raise TypeError(f"scroll must be a tuple of two ints, got {type(scroll).__name__}")
