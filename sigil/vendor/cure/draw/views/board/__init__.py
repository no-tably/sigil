"""{Board}: the plain data construct's console tabs are drawn from.

Kind: system (the composition tree rooted at `{Board}` in [Views]); data only. Plain
frozen data: cure's contract for construct to map its model into. construct depends
on cure, never the other way: nothing here knows construct, reads a file, or touches
a process. Live terminals arrive as screens (Buffer {Grid}s construct already has,
through Embed and Vt on its side); sigil's view arrives as {Rows}.

The parts, one module each (each a frozen dataclass checked on construction, every
optional field with an empty default, equal field by field and hashable):
- {Task} (`task.py`): `Task(id, *, title, system, kind, state, builder, depends)`;
  `KINDS`, `STATES` re-exported here as `TASK_KINDS`, `TASK_STATES`.
- {Builder} (`builder.py`): `Builder(id, *, task, worktree, env, status, phase,
  progress, screen, cursor)`; `STATES` as `BUILDER_STATES`.
- {Component} (`component.py`): `Component(key, *, kind, status, builder, brief,
  binding, recipe, suite, history)`; `KINDS`, `STATES`, `PAGES` as
  `COMPONENT_KINDS`, `COMPONENT_STATES`, `PAGES`.
- {Entry} (`entry.py`): `Entry(path, *, depth, folder, builder, env, status, note)`
  (`note`, Q10b, the last field: what waits on the path, one line of text (a
  non-empty `str` with no line break), or `None`; every Entry without one is as
  before Q10b, and Board's own fields, checks and errors are unchanged by it).
- {Agent} (`agent.py`): `Agent(screen, cursor)`.
- {SpecDoc} (`specdoc.py`): `SpecDoc(path, edit, rows, stale, highlight, note)`
  (`highlight`, S1: sigil's per-line runs of the text, TextInput's `runs` shape, or
  `None`; `SpecDoc()` and every SpecDoc without one are as before S1. `note`, S2, the
  last field: a note about the highlight, one line of text (a non-empty `str` with
  no line break), or `None`; every SpecDoc without one is as before S2, and Board's
  own fields, checks and errors are unchanged by it).
- {Notice} (`notice.py`, F14): `Notice(id, text, role="info")`, a notice the app
  wants seen; `ROLES` re-exported here as `NOTICE_ROLES` (Toast's `KINDS`).

The whole board (this module):
- `Board(*, tasks=(), builders=(), components=(), entries=(), agent=Agent(),
  spec=SpecDoc(), notices=())`, a frozen dataclass:
  - `tasks`: a `tuple` of {Task}, ids unique, in schedule order (as construct gives
    it); every id in a task's `depends` names a task of the board.
  - `builders`: a `tuple` of {Builder}, ids unique, in the order construct gives
    (BuilderGrid's order, X3).
  - `components`: a `tuple` of {Component}, keys unique.
  - `entries`: a `tuple` of {Entry}, paths unique, in tree order.
  - `agent`: an {Agent}; `spec`: a {SpecDoc}.
  - `notices` (F14, the last field): a `tuple` of {Notice}, ids unique, in the order
    the app gives (the strip's order: Views' [Notices] draws them on every tab).
    `Board()` and every board without notices are as before F14, field by field (the
    hash over the old fields plus `()`); no lookup is added for them.
  A reference from one part to another by id (a task's `builder`, a builder's
  `task`, a component's or an entry's `builder`) need not resolve: a view shows the
  id as given (construct's model may lag a frame). Only `depends` must resolve, since
  DagView lays the tasks out as a DAG.
  - Lookups: `board.task(id) -> Task`, `board.builder(id) -> Builder`,
    `board.component(key) -> Component`: the part with that id / key; `KeyError(id)`
    when none (`TypeError` for a non-`str`).
  - Equality field by field; hashable (every part is: screens and edits are left
    out of the parts' hashes).
  - `Board()` is the empty board.

Errors (construction, in field order, the first failure raised):
- `TypeError` when a field is not a `tuple` (`"tasks must be a tuple of Task, got
  list"`) or holds a value of another class; `agent` is not an `Agent`, `spec` not a
  `SpecDoc`; `notices` (checked after `spec`) is not a `tuple` of `Notice`
  (`"notices must be a tuple of Notice, got list"`, `"... got one str"`).
- `ValueError` when ids repeat (`"task ids repeat: ['a']"`, likewise `"builder ids
  repeat"`, `"component keys repeat"`, `"entry paths repeat"`, `"notice ids
  repeat"`, the repeated ones
  sorted), or a `depends` entry names no task (`"task 'b' depends on unknown task
  'z'"`).
Effects: none.

Usage:
    from cure.draw.views.board import Board, Builder, Task
    board = Board(tasks=(Task("Z1"), Task("X1", depends=("Z1",))),
                  builders=(Builder("b1", task="X1"),))
    board.builder("b1").task          # "X1"
    Board(tasks=(Task("X1", depends=("Q",)),))   # ValueError: task 'X1' depends on unknown task 'Q'
"""

from dataclasses import KW_ONLY, dataclass, field

from .agent import Agent
from .builder import STATES as BUILDER_STATES
from .builder import Builder
from .component import KINDS as COMPONENT_KINDS
from .component import PAGES
from .component import STATES as COMPONENT_STATES
from .component import Component
from .entry import Entry
from .notice import ROLES as NOTICE_ROLES
from .notice import Notice
from .specdoc import SpecDoc
from .task import KINDS as TASK_KINDS
from .task import STATES as TASK_STATES
from .task import Task


@dataclass(frozen=True)
class Board:
    """Everything construct's console tabs show, as plain data (see the module)."""

    _: KW_ONLY
    tasks: "tuple[Task, ...]" = ()
    builders: "tuple[Builder, ...]" = ()
    components: "tuple[Component, ...]" = ()
    entries: "tuple[Entry, ...]" = ()
    agent: Agent = field(default_factory=Agent)
    spec: SpecDoc = field(default_factory=SpecDoc)
    notices: "tuple[Notice, ...]" = ()

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _parts("tasks", self.tasks, Task, "task ids", lambda t: t.id)
        known = {t.id for t in self.tasks}
        for t in self.tasks:
            for d in t.depends:
                if d not in known:
                    raise ValueError(f"task {t.id!r} depends on unknown task {d!r}")
        _parts("builders", self.builders, Builder, "builder ids", lambda b: b.id)
        _parts("components", self.components, Component, "component keys", lambda c: c.key)
        _parts("entries", self.entries, Entry, "entry paths", lambda e: e.path)
        if not isinstance(self.agent, Agent):
            raise TypeError(f"agent must be an Agent, got {type(self.agent).__name__}")
        if not isinstance(self.spec, SpecDoc):
            raise TypeError(f"spec must be a SpecDoc, got {type(self.spec).__name__}")
        _parts("notices", self.notices, Notice, "notice ids", lambda n: n.id)

    def task(self, id: str) -> Task:
        """The task with this id (`KeyError` when none)."""
        return _find(self.tasks, id, lambda t: t.id)

    def builder(self, id: str) -> Builder:
        """The builder with this id (`KeyError` when none)."""
        return _find(self.builders, id, lambda b: b.id)

    def component(self, key: str) -> Component:
        """The component with this key (`KeyError` when none)."""
        return _find(self.components, key, lambda c: c.key)


def _parts(name: str, parts: object, cls: type, ids: str, ident) -> None:
    """Check a field: a tuple of `cls`, whose ids (by `ident`) do not repeat."""
    if not isinstance(parts, tuple):
        raise TypeError(f"{name} must be a tuple of {cls.__name__}, got {type(parts).__name__}")
    for part in parts:
        if not isinstance(part, cls):
            raise TypeError(f"{name} must be a tuple of {cls.__name__}, "
                            f"got one {type(part).__name__}")
    seen, repeated = set(), set()
    for part in parts:
        i = ident(part)
        (repeated if i in seen else seen).add(i)
    if repeated:
        raise ValueError(f"{ids} repeat: {sorted(repeated)}")


def _find(parts: tuple, id: object, ident):
    """The part whose id (by `ident`) is `id`; `KeyError(id)` when none."""
    if not isinstance(id, str):
        raise TypeError(f"id must be a str, got {type(id).__name__}")
    for part in parts:
        if ident(part) == id:
            return part
    raise KeyError(id)
