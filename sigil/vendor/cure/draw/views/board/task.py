"""{Task}: one item of construct's schedule.

Kind: data (a frozen dataclass, checked on construction). Plain data construct maps
its own model into; cure never reads construct.

What it is: id, title, system, kind (work | cleanup), state (ready | held | running |
done | failed), builder id or none, and depends on (task ids: the schedule, which
OverviewTab's DagView lays out as Graph's {Dag}).

Data:
- `Task(id, *, title="", system="", kind="work", state="ready", builder=None,
  depends=())`:
  - `id`: a non-empty `str`, unique in its {Board} (the Board checks that).
  - `title`: a `str` (`""`: none), shown as given.
  - `system`: a `str`, the system the task builds (`""`: none); Tasks groups by it.
  - `kind`: one of `KINDS` (`"work"`, `"cleanup"`).
  - `state`: one of `STATES` (`"ready"`, `"held"`, `"running"`, `"done"`,
    `"failed"`).
  - `builder`: `None` or a non-empty `str`, the id of the builder working on it (a
    {Builder}'s `id`; a dangling id is allowed: the board is shown as given).
  - `depends`: a `tuple` of non-empty `str`, the ids of the tasks this one waits on,
    in the order given; no repeats and not the task's own id. (That each names a
    task of the board is the {Board}'s check.)
- Equality and hashing are field by field (every field is hashable).

Constants: `KINDS = ("work", "cleanup")`, `STATES = ("ready", "held", "running",
"done", "failed")`, each in that order (the order a view lists them in).

Errors (construction, checked in field order, the first failure raised):
- `TypeError` when `id`, `title`, `system`, `kind` or `state` is not a `str`;
  `builder` is neither `None` nor a `str`; `depends` is not a `tuple` (a `list` is
  refused: pass a tuple) or holds a non-`str`. Message: `"<field> must be <what>, got
  <type name>"`, e.g. `"depends must be a tuple of str, got list"`.
- `ValueError` when `id` or `builder` is `""`; `kind` is not in `KINDS` (`"kind must
  be one of work, cleanup, got 'x'"`) or `state` not in `STATES` (likewise); a
  `depends` entry is `""`, repeated (`"depends repeats 'a'"`) or the task's own id
  (`"a task cannot depend on itself: 'a'"`).
Assigning a field raises `dataclasses.FrozenInstanceError`.
Effects: none.

Usage:
    from cure.draw.views.board import Task
    Task("X1", title="Views", system="Views", depends=("Z1",))
    Task("X1", state="done") == Task("X1", state="done")      # True
    Task("X1", kind="chore")        # ValueError: kind must be one of work, cleanup, got 'chore'
"""

from dataclasses import KW_ONLY, dataclass

KINDS = ("work", "cleanup")
"""A task's kinds, in order."""

STATES = ("ready", "held", "running", "done", "failed")
"""A task's states, in order."""


@dataclass(frozen=True)
class Task:
    """One task of the schedule (see the module)."""

    id: str
    _: KW_ONLY
    title: str = ""
    system: str = ""
    kind: str = "work"
    state: str = "ready"
    builder: "str | None" = None
    depends: "tuple[str, ...]" = ()

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _text("id", self.id, empty=False)
        _text("title", self.title)
        _text("system", self.system)
        _choice("kind", self.kind, KINDS)
        _choice("state", self.state, STATES)
        if self.builder is not None:
            _text("builder", self.builder, empty=False, what="None or a str")
        if not isinstance(self.depends, tuple) or not all(isinstance(d, str) for d in self.depends):
            got = self.depends if not isinstance(self.depends, tuple) else next(
                d for d in self.depends if not isinstance(d, str))
            raise TypeError(f"depends must be a tuple of str, got {type(got).__name__}")
        seen = set()
        for d in self.depends:
            if d == "":
                raise ValueError("depends holds ''")
            if d in seen:
                raise ValueError(f"depends repeats {d!r}")
            if d == self.id:
                raise ValueError(f"a task cannot depend on itself: {d!r}")
            seen.add(d)


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
