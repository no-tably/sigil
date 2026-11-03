"""[Tasks]: the work and the cleanup, laid out by system.

Kind: service (pure functions from Board {Task}s to a widget node; see the
OverviewTab package for the tab, its key `k == ("overview",)` and its ids).

What it does: the schedule as a Widgets `Table`, one row per task, grouped by the
system it builds (the systems in the order the schedule first names them, each
group's work before its cleanup), with the task's state and builder as columns. The
system is written on its group's first row only, so the groups read as blocks. A
click on a row hits that task's id. It composes existing widget nodes only and
paints nothing itself.

The order (`grouped(tasks) -> tuple`): the tasks of `tasks` (a `tuple` of {Task},
the Board's, in schedule order), stably sorted by `(S.index(t.system),
TASK_KINDS.index(t.kind))`, `S` being the distinct systems in order of first
appearance (`""`, no system, is a system like any other) and `TASK_KINDS ==
("work", "cleanup")` (Board's): grouped by system, work then cleanup, schedule order
within.

The columns (`COLUMNS`, in this order; Widgets' `TableColumn`): `"system"`,
`"task"`, `"state"` with `min=7` (the longest state, `"running"`, whole), `"builder"`,
`"kind"`, then `"title"` with `grow=1` (it takes the spare cells), every other field
its default. The state comes before the free text, so a narrow pane drops the title
first (Table's width rule keeps columns from the left), and Table's shrinking stops
at the column's `min`, so a state word is cut only when the table's room is below
the first three columns' mins and gaps (11 cells: Table's step 4 then gives the
state column what is left).

The rows (`rows(tasks) -> tuple`): for each task `t` of `grouped(tasks)`, the `i`-th,
`TableRow((s, t.id, t.state, t.builder or "none", t.kind, t.title), TONES[t.state],
id=k + ("task", t.id))`, where `s` is `t.system or "none"` on the first row of its
system's group and `""` on the others.

The pane (`tasks(tasks, *, task=None, offset=0) -> Block`):
- with tasks: `Block((Table(COLUMNS, rows(tasks), cursor=c, selected=sel,
  offset=offset, id=k + ("tasks", "table")),), title="tasks", kind="pane", id=k +
  ("tasks",))`,
  where `c` is the index in `grouped(tasks)` of the task whose id is `task`, or
  `None` when `task` is `None` or names no task, and `sel == frozenset()` when `c`
  is `None`, else `frozenset({c})` (Table's: the cursor shows while the table is
  focused, the selection always, by its gutter mark);
- with none: `Block((Paragraph(EMPTY, role="muted"),), title="tasks", kind="pane",
  id=k + ("tasks",))`, `EMPTY == "no tasks yet"`.

State tones: `TONES` maps every {Task} state to the Theme state its row is drawn in
(TableRow's `state`): `"ready"`: `None`, `"held"`: `None`, `"running"`: `"active"`,
`"done"`: `"muted"`, `"failed"`: `"emphasised"`. The keys are exactly Board's
`TASK_STATES`. The state column's word is the cue; the tone adds its mark in the
row's gutter (● running, · done, ✦ failed).

Laws (each a property a test can loop over task tuples, selections, offsets, sizes
and contexts):
- pure: equal arguments give equal results (`grouped`, `rows`, `tasks`).
- once: every task has exactly one row: `sorted(t.id for t in grouped(ts)) ==
  sorted(t.id for t in ts)`, the row ids `k + ("task", t.id)` each once.
- grouped: the rows of one system are contiguous, the groups in the order of their
  system's first task in `ts`, within a group every work row before every cleanup
  row, and otherwise `ts`' order; the system cell is non-empty exactly on each
  group's first row.
- ids: the node ids carried are exactly `{k + ("tasks",), k + ("tasks", "table")}`
  with tasks, `{k + ("tasks",)}` without.
- legible: with colour off (Caps depth 0), a row's state is its state column's word,
  drawn whole whenever the table's room is at least 11 cells (the pane at least 15
  wide: its border and Table's gutter), and the selected row shows Table's selected
  mark in its gutter.

Inputs: `tasks` a `tuple` of Board {Task}; `task` `None` or a `str`; `offset` an int
  `>= 0` (Table's: the first row the app wants shown).
Outputs: a `tuple` of {Task}; a `tuple` of Widgets `TableRow`; a Widgets `Block` (of a
  `Table`, or a `Paragraph`).
Errors: `TypeError` when `tasks` is not a `tuple`, `task` is neither `None` nor a
  `str`, or `offset` is not an int (a `bool` refused); `ValueError` when `offset <
  0`.
Effects: none.

Usage:
    from cure.draw.views.board import Task
    from cure.draw.views.overviewtab import tasks
    ts = (Task("X1", system="Views"), Task("D1", system="Draw"),
          Task("X1c", system="Views", kind="cleanup"), Task("X2", system="Views"))
    [t.id for t in tasks.grouped(ts)]       # ["X1", "X2", "X1c", "D1"]
    tasks.rows(ts)[1].cells[0]              # "": Views is written on its first row only
    tasks.tasks(ts, task="D1").children[0].cursor   # 3
"""

from cure.draw.widgets import Block, Paragraph, Table, TableColumn, TableRow

KEY = ("overview",)
"""The tab's key (OverviewTab's `k`)."""

EMPTY = "no tasks yet"
"""What the pane says when the board has no tasks."""

KINDS = ("work", "cleanup")
"""Board's `TASK_KINDS`, the order within a system's group (Board is not imported)."""

COLUMNS = (TableColumn("system"), TableColumn("task"), TableColumn("state", min=7),
           TableColumn("builder"), TableColumn("kind"), TableColumn("title", grow=1))
"""The table's columns, in order."""

TONES = {"ready": None, "held": None, "running": "active", "done": "muted",
         "failed": "emphasised"}
"""A task state's Theme state (its row's `state`), or None."""


def grouped(tasks: tuple) -> tuple:
    """The tasks grouped by system (first appearance), work before cleanup, stable."""
    _tasks(tasks)
    systems = list(dict.fromkeys(t.system for t in tasks))
    return tuple(sorted(tasks, key=lambda t: (systems.index(t.system), KINDS.index(t.kind))))


def rows(tasks: tuple) -> tuple:
    """The table's rows, one per task in `grouped` order (see the module)."""
    out, seen = [], set()
    for t in grouped(tasks):
        first = t.system not in seen
        seen.add(t.system)
        s = (t.system or "none") if first else ""
        out.append(TableRow((s, t.id, t.state, t.builder or "none", t.kind, t.title),
                            TONES[t.state], id=KEY + ("task", t.id)))
    return tuple(out)


def tasks(tasks: tuple, *, task: "str | None" = None, offset: int = 0) -> Block:
    """The tasks pane: a Table by system, the selected task's row marked."""
    _tasks(tasks)
    if task is not None and not isinstance(task, str):
        raise TypeError(f"task must be a str or None, got {type(task).__name__}")
    if not isinstance(offset, int) or isinstance(offset, bool):
        raise TypeError(f"offset must be an int, got {type(offset).__name__}")
    if offset < 0:
        raise ValueError(f"offset must be >= 0, got {offset}")
    if not tasks:
        return Block((Paragraph(EMPTY, role="muted"),), title="tasks", kind="pane",
                     id=KEY + ("tasks",))
    order = grouped(tasks)
    c = next((i for i, t in enumerate(order) if t.id == task), None)
    sel = frozenset() if c is None else frozenset({c})
    table = Table(COLUMNS, rows(tasks), cursor=c, selected=sel, offset=offset,
                  id=KEY + ("tasks", "table"))
    return Block((table,), title="tasks", kind="pane", id=KEY + ("tasks",))


# --- private ------------------------------------------------------------------------

def _tasks(tasks: object) -> None:
    if not isinstance(tasks, tuple):
        raise TypeError(f"tasks must be a tuple, got {type(tasks).__name__}")
