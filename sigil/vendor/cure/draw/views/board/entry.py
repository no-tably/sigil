"""{Entry}: one row of the FileTree: a code folder or file.

Kind: data (a frozen dataclass, checked on construction). Plain data construct maps
its own model into; a {Board} holds its entries in tree order (a folder before what
it holds), and Views never lists a directory.

What it is: path, depth, folder or not, builder id, env, status, and a note (Q10b):
what waits on that path, or none.

Data:
- `Entry(path, *, depth=0, folder=False, builder=None, env=None, status=None,
  note=None)`:
  - `path`: a non-empty `str`, the path as construct names it (relative to the
    program's root, `/`-separated); unique in its {Board}. Never opened.
  - `depth`: an int `>= 0`, the row's nesting level in the tree (0: top level).
  - `folder`: a `bool`, whether the entry is a folder.
  - `builder`: `None` or a non-empty `str`, the {Builder} whose worktree changes it.
  - `env`: `None` or a non-empty `str`, the name of the env (recipe) it builds in.
  - `status`: `None` (no component bound to it) or one of {Component}'s `STATES`
    (`"planned"` ... `"pruning"`), the status of the code there.
  - `note` (Q10b, the last field): `None` (nothing waits on the path: the row and the
    files pane are drawn as before Q10b), or what waits on this path as construct
    words it (e.g. `"Q12: is this module planned?"`): a non-empty `str` of one line,
    holding no line break (no character `str.splitlines` splits at: `\\n`, `\\r`,
    `\\v`, `\\f`, `\\x1c`, `\\x1d`, `\\x1e`, `\\x85`, `\\u2028`, `\\u2029`; the
    note is drawn on the files pane's title row, and a Text `Line` holds no line
    break). It is for a path that is no component, so no `status` can say it; it is
    never checked against `status` (a note beside a status is kept as given:
    construct decides what it says). FileTree marks a noted entry's row `held` and
    shows the focused entry's note at its title row's end (its module states how).
- Equality and hashing are field by field (`note` included: a valid note is `None`
  or a `str`, hashable).
- An Entry made without `note` (every Entry of before Q10b) has `note is None` and
  equals, field for field, the Entry of before Q10b.

Errors (construction, in field order):
- `TypeError` when `path` is not a `str`; `depth` is not an int (a `bool` refused);
  `folder` is not a `bool`; `builder`, `env` or `status` is neither `None` nor a
  `str`.
- `ValueError` when `path`, `builder` or `env` is `""`; `depth < 0`; `status` is not
  one of {Component}'s states (`"status must be None or one of planned, ..., got
  'x'"`).
- `note` (Q10b), checked last, after `status`, in this order: `TypeError("note must
  be None or a str, got int")` when it is neither; `ValueError("note must not be
  ''")` for `""` (Entry's message for an empty text, as `builder`'s and `env`'s);
  `ValueError("note must be one line, got 'a\\nb'")` when it holds a line break
  (any character `str.splitlines` splits at; the note shown by `repr`, SpecDoc's
  message).
Effects: none.

Usage:
    from cure.draw.views.board import Entry
    Entry("cure/draw/views", folder=True, builder="b1", status="building")
    Entry("cure/draw/views/inspector.py", depth=1, status="planned")
    Entry("cure/edge/relay.py", note="Q12: is this module planned?").note
    # "Q12: is this module planned?"
    Entry("cure/x.py", note="a\\nb")   # ValueError: note must be one line, got 'a\\nb'
"""

from dataclasses import KW_ONLY, dataclass

from .component import STATES


@dataclass(frozen=True)
class Entry:
    """One FileTree row (see the module)."""

    path: str
    _: KW_ONLY
    depth: int = 0
    folder: bool = False
    builder: "str | None" = None
    env: "str | None" = None
    status: "str | None" = None
    note: "str | None" = None

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _text("path", self.path, empty=False)
        if not isinstance(self.depth, int) or isinstance(self.depth, bool):
            raise TypeError(f"depth must be an int, got {type(self.depth).__name__}")
        if self.depth < 0:
            raise ValueError(f"depth must be >= 0, got {self.depth}")
        if not isinstance(self.folder, bool):
            raise TypeError(f"folder must be a bool, got {type(self.folder).__name__}")
        for name in ("builder", "env"):
            if getattr(self, name) is not None:
                _text(name, getattr(self, name), empty=False, what="None or a str")
        if self.status is not None:
            _text("status", self.status, what="None or a str")
            if self.status not in STATES:
                raise ValueError(f"status must be None or one of {', '.join(STATES)}, "
                                 f"got {self.status!r}")
        if self.note is not None:
            _text("note", self.note, empty=False, what="None or a str")
            if self.note.splitlines() != [self.note]:
                raise ValueError(f"note must be one line, got {self.note!r}")


def _text(name: str, value: object, *, empty: bool = True, what: str = "a str") -> None:
    """Check `value` is a `str` (non-empty unless `empty`)."""
    if not isinstance(value, str):
        raise TypeError(f"{name} must be {what}, got {type(value).__name__}")
    if not empty and value == "":
        raise ValueError(f"{name} must not be ''")
