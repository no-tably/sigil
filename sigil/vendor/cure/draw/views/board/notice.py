"""{Notice}: a notice the app wants seen.

Kind: data (a frozen dataclass, checked on construction). Plain data construct maps
its own model into (a word from one of its agents); cure never reads construct.

What it is: an id, the text, a role and whether its row is hit. Views draws a board's notices as a strip on
every tab ([Notices], `views/notices.py`): a row per notice, a Toast's form (the
role's word in that role, then the text in role `text`).

Data:
- `Notice(id, text, role="info", hit=True)`:
  - `id`: a non-empty `str`, unique among its {Board}'s notices (the Board checks
    that); the strip's hit for the notice's row is tagged `("notices", id)`.
  - `text`: any `str` (empty, line breaks and controls allowed): the caller's, drawn
    as given and harmless. The strip draws a line break (`"\\r\\n"` or `"\\n"`) as
    one space and hands the rest to Text, which draws every control as U+FFFD and a
    wide glyph two cells, so no control in the text reaches the terminal.
  - `role`: one of `ROLES` (`"info"`, `"ok"`, `"warn"`, `"error"`), the theme role
    the notice's word is drawn in.
  - `hit`: a `bool` (the exact type: `1`, `0` and the rest refused), `hit=True` by
    default: the strip gives the notice's row its hit; `False`: the row is drawn the
    same, with no hit (a standing note).
- Equality and hashing are field by field (every field is hashable).

Constants: `ROLES = ("info", "ok", "warn", "error")` (Toast's `KINDS`, in that
order), re-exported by Board's and Views' packages as `NOTICE_ROLES`.

Errors (construction, checked in field order, the first failure raised):
- `id`: `TypeError("notice id must be a str, got int")`; `ValueError("notice id must
  not be ''")`.
- `text`: `TypeError("notice text must be a str, got bytes")`.
- `role`: `TypeError("notice role must be a str, got NoneType")`; `ValueError("notice
  role must be one of info, ok, warn, error, got 'fatal'")`.
- `hit`: `TypeError("notice hit must be a bool, got int")`.
Assigning a field raises `dataclasses.FrozenInstanceError`.
Effects: none.

Usage:
    from cure.draw.views.board import Notice
    Notice("n1", "build failed", "error")
    Notice("n1", "saved") == Notice("n1", "saved", "info")    # True
    Notice("n2", "on call: ana", hit=False)    # drawn, no hit
    Notice("n1", "x", "fatal")      # ValueError: notice role must be one of ...
    Notice("", "x")                 # ValueError: notice id must not be ''
"""

from dataclasses import dataclass

ROLES = ("info", "ok", "warn", "error")
"""A notice's roles, in order (Toast's `KINDS`)."""


@dataclass(frozen=True)
class Notice:
    """A notice the app wants seen (see the module)."""

    id: str
    text: str
    role: str = "info"
    hit: bool = True

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        _str("id", self.id)
        if self.id == "":
            raise ValueError("notice id must not be ''")
        _str("text", self.text)
        _str("role", self.role)
        if self.role not in ROLES:
            raise ValueError(f"notice role must be one of {', '.join(ROLES)}, "
                             f"got {self.role!r}")
        if type(self.hit) is not bool:
            raise TypeError(f"notice hit must be a bool, got {type(self.hit).__name__}")


def _str(name: str, value: object) -> None:
    """Check `value` is a `str`."""
    if not isinstance(value, str):
        raise TypeError(f"notice {name} must be a str, got {type(value).__name__}")
