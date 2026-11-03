"""{SpecDoc}: the root spec: its text's edit, its path, sigil's view of it, stale or not,
sigil's highlight of its text, and a note about that highlight.

Kind: data (a frozen dataclass, checked on construction). Plain data construct maps
its own model into: construct keeps the edit (Input's {Edit}, routed its keys), runs
sigil and hands in the rows it drew. Views never reads the file or runs sigil.

What it is: the root spec: its text's Edit, the path, sigil's view as {Rows},
whether the view is stale (the spec changed since it was drawn), sigil's highlight
of the text (per-line runs, `sigil highlight`) or none, and a note about the highlight
(one line of text, e.g. why the pane draws plain) or none.

Data:
- `SpecDoc(path="", edit=None, rows=Rows(), stale=False, highlight=None, note=None)`:
  - `path`: a `str`, the spec's path as construct names it (`""`: none).
  - `edit`: `None` (no text loaded) or an edit value, read by its attributes as
    Widgets' TextInput reads one (Draw may not import Input, so any value with them
    serves, Input's `Edit` among them): `rows`, `line`, `column`, `selection`. Only
    their presence is checked here; TextInput checks their values when SpecPane is
    built (X2).
  - `rows`: a Buffer {Rows}, sigil's view of the spec as rows of `(text, style)`
    runs (`Rows()`: not drawn yet).
  - `stale`: a `bool`, true when the spec changed since `rows` was drawn.
  - `highlight` (S1): `None` (no highlight: the spec pane draws plain, as before
    S1), or sigil's runs of the spec's text in exactly the shape of Widgets'
    TextInput `runs` (its module states it): a `tuple`, one entry per row index of
    the edit's rows (shorter or longer allowed), each `None` or a pair `(text,
    spans)`, `spans` a tuple of `(chunk, role, colour)` triples, `chunk` a non-empty
    `str`, `role` `None` or a non-empty `str` (sigil's dotted role), `colour` `None`
    or `"#rrggbb"`, the chunks joining to `text`. construct makes it from `sigil
    highlight` (incremental by its carry state) and hands it in beside the edit; a
    line edited since keeps its old pair, which TextInput draws plain (its `text`
    no longer equals the row: condition a), so construct need not drop it. Checked
    here by TextInput's rules; it is never checked against `edit` (a stale or a
    missing edit is not an error; with `edit is None` it is kept and unused).
  - `note` (S2, the last field): `None` (no note: the spec pane's title is as before
    S2), or a note about the highlight as construct words it (e.g. `"sigil
    highlight: exited 1"` while sigil's highlighter is down and the pane draws the
    text plain): a non-empty `str` of one line, holding no line break (no character
    `str.splitlines` splits at: `\\n`, `\\r`, `\\v`, `\\f`, `\\x1c`, `\\x1d`, `\\x1e`,
    `\\x85`, `\\u2028`, `\\u2029`). SpecPane draws it in role `warn` at the end of its
    title row, after the path (its module states how). It is never checked against
    `highlight` or `edit` (a note with a highlight, or with no edit, is kept as
    given: construct decides what it says).
- `SpecDoc()` is the empty spec (the {Board}'s default).
- Equality is field by field (`note` included); hashing leaves `edit` out
  (`field(hash=False)`: an edit value need not be hashable) and takes every other
  field, `note` included, so every SpecDoc is hashable (a valid `highlight` is a
  tuple of strs, `None`s and tuples, a valid `note` `None` or a `str`: hashable).
- A SpecDoc made without `note` (every SpecDoc of before S2) has `note is None` and
  equals, field for field, the SpecDoc of before S2.

Errors (construction, in field order):
- `TypeError` when `path` is not a `str`; `edit` is not `None` and lacks one of
  `rows`, `line`, `column`, `selection` (`"edit lacks 'rows'"`, the first missing in
  that order); `rows` is not a Buffer `Rows` (pass `Rows.of(...)`); `stale` is not a
  `bool`.
- `highlight`, checked after `stale`, by exactly TextInput's checks of `runs`, in its order,
  with its messages but `highlight` in place of `runs`: e.g. `TypeError("highlight
  must be None or a tuple, got list")`, `TypeError("highlight[0] must be None or a
  pair (text, spans), got list")`, `ValueError("highlight[2] span 0 chunk must not
  be empty")`, `ValueError("highlight[1] span 1 colour must be '#rrggbb', got
  'red'")`, `ValueError("highlight[0] spans join to 'ab', not its text 'abc'")`.
- `note` (S2), checked last, after `highlight`: `TypeError("note must be None or a
  str, got int")` when it is neither; `ValueError("note must not be empty")` for
  `""`; `ValueError("note must be one line, got 'a\\nb'")` when it holds a line
  break (any character `str.splitlines` splits at; the note shown by `repr`).
Effects: none.

Usage:
    from cure.core.buffer import Rows
    from cure.draw.views.board import SpecDoc
    SpecDoc("cure.sigil", rows=Rows.of(["[Views] -> [Widgets]"]), stale=True)
    SpecDoc(edit=object())            # TypeError: edit lacks 'rows'
    SpecDoc(highlight=(("[A]", (("[A]", "kinds.service", "#79c0ff"),)),))
    SpecDoc(highlight=(("[A]", (("[", None, None),)),))
    # ValueError: highlight[0] spans join to '[', not its text '[A]'
    SpecDoc("cure.sigil", note="sigil highlight: exited 1").note   # "sigil highlight: exited 1"
    SpecDoc(note="a\\nb")             # ValueError: note must be one line, got 'a\\nb'
"""

import re
from dataclasses import dataclass, field

from cure.core.buffer import Rows

_EDIT = ("rows", "line", "column", "selection")
"""The attributes an edit value is read by, in the order they are checked."""

_HEX = re.compile(r"#[0-9a-fA-F]{6}")
"""A run's colour: `#` and exactly six hex digits, either case."""


def _check_highlight(runs: object) -> None:
    """TextInput's checks of `runs`, in its order, named `highlight` (see Errors).
    Board imports no widget, so the rules are restated here."""
    if runs is None:
        return
    if not isinstance(runs, tuple):
        raise TypeError(f"highlight must be None or a tuple, got {type(runs).__name__}")
    for i, entry in enumerate(runs):
        if entry is None:
            continue
        if not isinstance(entry, tuple) or len(entry) != 2:
            raise TypeError(f"highlight[{i}] must be None or a pair (text, spans), got {type(entry).__name__}")
        text, spans = entry
        if not isinstance(text, str):
            raise TypeError(f"highlight[{i}] text must be a str, got {type(text).__name__}")
        if not isinstance(spans, tuple):
            raise TypeError(f"highlight[{i}] spans must be a tuple, got {type(spans).__name__}")
        for j, span in enumerate(spans):
            _check_span(f"highlight[{i}] span {j}", span)
        joined = "".join(chunk for chunk, _, _ in spans)
        if joined != text:
            raise ValueError(f"highlight[{i}] spans join to {joined!r}, not its text {text!r}")


def _check_span(name: str, span: object) -> None:
    """One `(chunk, role, colour)` triple, its fields in that order."""
    if not isinstance(span, tuple) or len(span) != 3:
        raise TypeError(f"{name} must be a (chunk, role, colour) triple, got {type(span).__name__}")
    chunk, role, colour = span
    if not isinstance(chunk, str):
        raise TypeError(f"{name} chunk must be a str, got {type(chunk).__name__}")
    if chunk == "":
        raise ValueError(f"{name} chunk must not be empty")
    if role is not None and not isinstance(role, str):
        raise TypeError(f"{name} role must be None or a str, got {type(role).__name__}")
    if role == "":
        raise ValueError(f"{name} role must not be empty")
    if colour is not None and not isinstance(colour, str):
        raise TypeError(f"{name} colour must be None or a str, got {type(colour).__name__}")
    if colour is not None and not _HEX.fullmatch(colour):
        raise ValueError(f"{name} colour must be '#rrggbb', got {colour!r}")


def _check_note(note: object) -> None:
    """`None`, or a non-empty str holding no line break (see Errors)."""
    if note is None:
        return
    if not isinstance(note, str):
        raise TypeError(f"note must be None or a str, got {type(note).__name__}")
    if note == "":
        raise ValueError("note must not be empty")
    if note.splitlines() != [note]:
        raise ValueError(f"note must be one line, got {note!r}")


@dataclass(frozen=True)
class SpecDoc:
    """The root spec, its edit and sigil's view of it (see the module)."""

    path: str = ""
    edit: object = field(default=None, hash=False)
    rows: Rows = Rows()
    stale: bool = False
    highlight: "tuple | None" = None
    note: "str | None" = None

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        if not isinstance(self.path, str):
            raise TypeError(f"path must be a str, got {type(self.path).__name__}")
        if self.edit is not None:
            for name in _EDIT:
                if not hasattr(self.edit, name):
                    raise TypeError(f"edit lacks {name!r}")
        if not isinstance(self.rows, Rows):
            raise TypeError(f"rows must be a Rows (pass Rows.of(...)), got {type(self.rows).__name__}")
        if not isinstance(self.stale, bool):
            raise TypeError(f"stale must be a bool, got {type(self.stale).__name__}")
        _check_highlight(self.highlight)
        _check_note(self.note)
