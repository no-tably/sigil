"""[Snapshot]: plain or styled snapshots of a frame, goldens compared and updated only
when the caller asks.

Kind: service (two frozen dataclasses and functions; pure except `golden` and
`assert_golden`, which read and write the one golden file the caller names).

What it does: turns a frame (a {Grid}, or rows of `(text, style)` runs) into a
deterministic, diff-friendly snapshot string, compares a snapshot with an expected one
or with a golden file, and reads a styled snapshot back as {Rows}. A plain snapshot is
Buffer's `text` ({Grid} => {Text}). A styled snapshot adds where every style sits and
what it is, printed by theme role (Rules carried over: colours keep their theme role,
so a theme recolour does not churn goldens). The same input always gives the same
string: nothing here reads the clock, the environment, the terminal or any state
beyond its arguments.

The frame (`subject` below): a `Grid` (`cure.core.Grid`) is used as it is; anything
else is taken as rows, `Rows.of(subject)` (a `Rows`, or an iterable of Lines, strs or
lists of `(text, style)` runs), and laid out with Core's `cells(rows)` (width
`rows.width`, one grid row per row). "The grid" below is that grid.

Data (frozen dataclasses):
- `Label(text: str)`: a style as a styled snapshot names it (its legend label, below).
  `parse` puts Labels in the runs it returns, since a label printed by role cannot be
  turned back into the colours it came from. `text` is a non-empty `str` holding no
  control character (C0, DEL, C1) and not starting or ending with a space; anything
  else is refused on construction (`TypeError` for a non-`str`, `ValueError` for the
  rest). Equality is by `text`.
- `Diff(name: str, expected: str, actual: str, missing: bool = False)`: a mismatch,
  stored as given. `name` names the expected side (`"expected"`, or a golden's path).
  - `lines` -> `tuple[str, ...]`: exactly
    `tuple(difflib.unified_diff(expected.split("\\n"), actual.split("\\n"),
    fromfile=name, tofile="actual", lineterm=""))` (3 lines of context).
  - `str(diff)`: when `missing`, `f"golden {name} is missing (pass update=True to
    write it)"`; otherwise `f"snapshot differs from {name}:\\n"` followed by
    `"\\n".join(diff.lines)`.

The plain format (`plain(subject)`): exactly Buffer's `text(grid)`: each grid row's
glyphs joined (a wide glyph's tail adds nothing, so a wide glyph appears once), trailing
U+0020 spaces stripped, rows joined by `"\\n"`, no trailing newline, `""` for a grid
with no rows. Styles are not shown.

The styled format (`styled(subject)`), version 1, for a grid `w` cells wide and `h`
rows high, is these lines joined by `"\\n"` (no trailing newline):

1. the header `f"cure-snapshot 1 {w}x{h}"`;
2. the text block: `h` lines, line `y` being row `y` of `plain(grid)` (so the text
   block is the plain snapshot, line for line);
3. a line `"--"`;
4. the mask block: `h` lines, one character per cell of the row (a wide glyph's head
   and tail columns both carry its head's key, so the mask lines up column for column
   with the text in a monospace view), each cell's character being `"."` when the
   cell's style labels as `""` and otherwise its style's key; then trailing `"."`
   characters stripped (a row with no styled cell is `""`);
5. a line `"--"`;
6. the legend: one line `f"{key} {label}"` per key, in key order.

Labels. `label(style)` is the style's legend label:
- `None`, and a Style whose every field is at its default (`Style()`), label as `""`
  (plain: `"."` in the mask, no key). So a snapshot does not tell `None` from
  `Style()` (as [Wire]'s plain entry), but does tell `Style()` from
  `Style(fg=resolve("default"))` (`"fg=default"`).
- a `Label` labels as its `text`.
- a Style (`cure.core.style.Style`) labels as its tokens joined by one space, in this
  order, each present only when the field is set: `fg=C`, `bg=C`, `bold`, `dim`,
  `italic`, `underline` (underline `"single"`) or `underline=K` (any other underline
  kind `K`, e.g. `underline=curly`), `ul=C` (the underline colour), `strike`,
  `reverse`, `link=TARGET` (always last).
  Each colour `C` prints as:
  - `@` + its `role` when the role is not `""` (so `fg=@kinds-service`,
    `bg=@dim:list.item`): two colours of one role print alike whatever their values;
  - otherwise by form: `"default"` -> `default`; `"name"` -> the name (`red`,
    `bright_black`); `"index"` -> the decimal index (`42`); `"rgb"` -> `#rrggbb`
    (lower case); `"ink"` -> `ink:` + the ink's name (`ink:teal`), or the ink's
    `#rrggbb` when its name is `""`.
  Example: `Style(fg=resolve(Name("teal", "kinds-service"), inks), bold=True)` labels
  as `"fg=@kinds-service bold"`.
Styles that label alike share one key; styles that label differently never do.

Keys: `KEYS` = `"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"`.
The distinct non-empty labels are given keys from `KEYS` in order of first appearance
(rows top to bottom, cells left to right): the first label `"a"`, the next `"b"`, and
so on. (So adding a style earlier in the frame renames the later keys; the text block
never changes for a style change.)

Rows of the text block are right-stripped, so a styled trailing blank (a background
run) shows only in the mask; cells past the end of a text line are `" "`.

Example: `styled([[("name ", None), ("中文", bold)], "ok"])` with
`bold = Style(bold=True)` is

    cure-snapshot 1 9x2
    name 中文
    ok
    --
    .....aaaa

    --
    a bold

Reading back (`parse(snapshot, *, styled=True)`):
- `styled=True`: the styled format above, read strictly: the header must match
  `cure-snapshot 1 {w}x{h}` (decimal ints, no sign, no leading zeros except `0`
  itself); then exactly `h` text lines, `"--"`, `h` mask lines, `"--"`, and the
  legend lines to the end (none is allowed). Each legend line is a key from `KEYS`,
  one space, and a label `Label` accepts; a key appears at most once (the legend's
  order and unused keys are not checked). Each text line, laid out as cells by Text's
  layout (`cure.core.text.put` of `Line.of(line)`), takes at most `w` cells; each mask
  line is at most `w` characters, each `"."` or a key the legend names; the mask
  characters of a wide glyph's head and tail columns are the same. The result is a
  {Rows} of `h` lines, each line `w` cells wide: the text laid out, padded with `" "`
  to `w` cells, each cell's style `None` for `"."` (or a column past the mask line's
  end) and `Label(label)` for a key, as one {Line} in normal form (adjacent cells
  with `==` styles in one run, a wide glyph once, as Core's `rows` reads a grid).
- `styled=False`: a plain snapshot as rows: `Rows()` for `""`, otherwise
  `Rows.of(snapshot.split("\\n"))` (every style `None`, no padding).

Round trip: for every subject, `parse(styled(subject)) == labelled(subject)`; for
every subject whose grid has a row or is 0 cells wide (a `w`x0 grid parses to
`Rows()`, which lays out as 0x0), `styled(parse(styled(subject))) == styled(subject)`;
and
`parse(styled(subject)).plain` right-stripped of spaces line by line is
`plain(subject).split("\\n")` (for a grid with rows). `labelled(subject)` is Core's
`rows(grid)` with each run's style `s` replaced by `None` when `label(s) == ""` and
by `Label(label(s))` otherwise, then each line merged (adjacent runs with `==` styles
joined, `cure.core.text.merge`).

Comparing:
- `match(expected, actual, *, name="expected") -> Diff | None`: `None` when the two
  strings are equal (`==`), else `Diff(name, expected, actual)`.
- `assert_snapshot(expected, actual, *, name="expected") -> None`: raises
  `AssertionError(str(diff))` when `match` gives a Diff (so a `unittest.TestCase`
  reports it as a failure, its message the readable diff); returns `None` otherwise.

Goldens (the only file I/O). A golden file holds a snapshot followed by one `"\\n"`,
UTF-8 without a BOM, newlines never translated (read and written with `newline=""`).
- `golden(path, actual, *, update=False) -> Diff | None`: `path` a `str` or
  `os.PathLike`, `name` below being `os.fspath(path)`.
  - `update=False` (the default): reads the file; its content with exactly one
    trailing `"\\n"` removed (when present) is the expected snapshot. Returns
    `match(expected, actual, name=name)`. A missing file (`FileNotFoundError`) is
    not raised: it returns `Diff(name, "", actual, missing=True)`. Nothing is
    written.
  - `update=True`: when the file exists and matches (as above), nothing is written;
    otherwise writes `actual + "\\n"` to `path` (replacing the file), creating its
    missing parent directories first. Returns `None` (the golden now matches).
- `assert_golden(path, actual, *, update=False) -> None`: `golden(...)`, raising
  `AssertionError(str(diff))` when it returns a Diff.
The update is only ever the caller's explicit `update=True`: Snapshot reads no
environment variable and no command line; a suite's `--update` flag maps to the
argument.

Inputs: `subject`: a {Grid}, or rows `Rows.of` takes; `style` (`label`): `None`, a
  Style or a `Label`; `snapshot` (`parse`): a `str`; `expected`, `actual`: `str`;
  `name`: `str`; `path`: `str` or `os.PathLike`; `update`, `styled`: `bool`.
Outputs: `plain`: {Text}, a `str`; `styled`: `str`; `label`: `str`; `parse`,
  `labelled`: {Rows}; `match`, `golden`: a `Diff` or `None`; `assert_snapshot`,
  `assert_golden`: `None`.
Errors: `TypeError` when `subject` is neither a `Grid` nor rows `Rows.of` takes (as
  Rows raises), when a style in the frame (or `label`'s argument) is none of `None`,
  a Style or a `Label`, when `snapshot`, `expected`, `actual` or `name` is not a
  `str`, `path` not a `str` / `os.PathLike`, or `update` / `styled` not a `bool`.
  `ValueError` when a colour's role (or an ink's name, where printed) or a link target
  holds whitespace or a control character (a label could not be read unambiguously),
  when a frame has more distinct non-empty labels than `KEYS` has characters (62), and from `parse`
  when the snapshot breaks any rule of the format (the message names the 1-based line).
  `golden` / `assert_golden`: `OSError` other than a missing file on reading, and any
  `OSError` on writing or creating directories, propagate; `UnicodeDecodeError` for a
  golden that is not UTF-8. `assert_*`: `AssertionError` on a mismatch, as above.
Effects: `golden` and `assert_golden` read the file at `path` and, with
  `update=True`, write it (and create its parent directories); nothing else here
  touches a file, and no function keeps state between calls.

Usage:
    import unittest
    from cure.core.style import Style
    from cure.testing.snapshot import plain, styled, parse, assert_golden, assert_snapshot

    class Frame(unittest.TestCase):
        UPDATE = False                                # a suite's --update sets this
        def test_header(self):
            frame = [[("name ", None), ("中文", Style(bold=True))], "ok"]
            assert_snapshot("name 中文\\nok", plain(frame))
            assert_golden("tests/golden/header.txt", styled(frame), update=self.UPDATE)
            parse(styled(frame)).plain                # ("name 中文", "ok       ")
"""

import difflib
import os
import re
from dataclasses import dataclass

from cure.core import Grid, Rows, cells, rows
from cure.core.buffer import text
from cure.core.style import Colour, Style
from cure.core.text import Cell, Line, Span, merge, put

KEYS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
HEADER = "cure-snapshot 1"
SEPARATOR = "--"
PLAIN = "."


@dataclass(frozen=True)
class Label:
    """A style as a styled snapshot names it (see the module); checked on construction."""

    text: str

    def __post_init__(self) -> None:
        """Check `text` (see the module's Label)."""
        if not isinstance(self.text, str):
            raise TypeError(f"label text must be a str, got {type(self.text).__name__}")
        if not self.text:
            raise ValueError("label text must not be empty")
        if any(_is_control(ch) for ch in self.text):
            raise ValueError(f"label text holds a control character: {self.text!r}")
        if self.text[0] == " " or self.text[-1] == " ":
            raise ValueError(f"label text starts or ends with a space: {self.text!r}")


@dataclass(frozen=True)
class Diff:
    """A snapshot mismatch: the expected side's `name`, both strings, and whether the
    golden was `missing` (see the module)."""

    name: str
    expected: str
    actual: str
    missing: bool = False

    @property
    def lines(self) -> "tuple[str, ...]":
        """The unified diff of expected against actual, line by line (see the module)."""
        return tuple(difflib.unified_diff(self.expected.split("\n"), self.actual.split("\n"),
                                         fromfile=self.name, tofile="actual", lineterm=""))

    def __str__(self) -> str:
        """The readable message: the missing golden, or the header and the diff lines."""
        if self.missing:
            return f"golden {self.name} is missing (pass update=True to write it)"
        return f"snapshot differs from {self.name}:\n" + "\n".join(self.lines)


def plain(subject: "Grid | object") -> str:
    """The plain snapshot: Buffer's `text` of the frame (see the module)."""
    return text(_grid_of(subject))


def styled(subject: "Grid | object") -> str:
    """The styled snapshot, format version 1: header, text, mask, legend (see the module)."""
    grid = _grid_of(subject)
    keys: dict[str, str] = {}
    masks = [_mask(grid.row(y), keys) for y in range(grid.h)]
    texts = text(grid).split("\n") if grid.h else []
    legend = [f"{key} {name}" for name, key in keys.items()]
    return "\n".join([f"{HEADER} {grid.w}x{grid.h}", *texts, SEPARATOR, *masks, SEPARATOR,
                      *legend])


def label(style: object) -> str:
    """A style's legend label, colours by theme role; `""` for plain (see the module)."""
    if style is None:
        return ""
    if isinstance(style, Label):
        return style.text
    if not isinstance(style, Style):
        raise TypeError(f"a style must be None, a Style or a Label, got {type(style).__name__}")
    return " ".join(_tokens(style))


def labelled(subject: "Grid | object") -> Rows:
    """The frame's rows with each style replaced by its Label (or None), merged."""
    return Rows(tuple(_labelled_line(line) for line in rows(_grid_of(subject)).lines))


def parse(snapshot: str, *, styled: bool = True) -> Rows:
    """A snapshot read back as Rows: styled strictly (Label styles), or plain."""
    _check_str(snapshot, "snapshot")
    _check_bool(styled, "styled")
    if not styled:
        return Rows() if snapshot == "" else Rows.of(snapshot.split("\n"))
    return _parse_styled(snapshot.split("\n"))


def match(expected: str, actual: str, *, name: str = "expected") -> "Diff | None":
    """None when the snapshots are equal, else their Diff."""
    _check_str(expected, "expected")
    _check_str(actual, "actual")
    _check_str(name, "name")
    return None if expected == actual else Diff(name, expected, actual)


def assert_snapshot(expected: str, actual: str, *, name: str = "expected") -> None:
    """Raise AssertionError(str(diff)) when `actual` differs from `expected`."""
    diff = match(expected, actual, name=name)
    if diff is not None:
        raise AssertionError(str(diff))


def golden(path: "str | os.PathLike[str]", actual: str, *, update: bool = False) -> "Diff | None":
    """Compare `actual` with the golden file at `path`; with `update=True`, write it."""
    name = _path_name(path)
    _check_str(actual, "actual")
    _check_bool(update, "update")
    try:
        expected = _read_golden(name)
    except FileNotFoundError:
        expected = None
    if expected == actual:
        return None
    if update:
        _write_golden(name, actual)
        return None
    if expected is None:
        return Diff(name, "", actual, missing=True)
    return match(expected, actual, name=name)


def assert_golden(path: "str | os.PathLike[str]", actual: str, *, update: bool = False) -> None:
    """`golden(...)`, raising AssertionError(str(diff)) on a Diff."""
    diff = golden(path, actual, update=update)
    if diff is not None:
        raise AssertionError(str(diff))


_SIZE = re.compile(re.escape(HEADER) + r" (0|[1-9][0-9]*)x(0|[1-9][0-9]*)")
_PAD = Cell(" ", 1, None)


# -- frames and labels

def _grid_of(subject: object) -> Grid:
    return subject if isinstance(subject, Grid) else cells(Rows.of(subject))


def _mask(row: "tuple[Cell, ...]", keys: "dict[str, str]") -> str:
    """One mask line, giving each new label the next key (in place)."""
    return "".join(_key(label(cell.style), keys) for cell in row).rstrip(PLAIN)


def _key(name: str, keys: "dict[str, str]") -> str:
    if name == "":
        return PLAIN
    if name not in keys:
        if len(keys) == len(KEYS):
            raise ValueError(f"a frame has more than {len(KEYS)} distinct styles")
        keys[name] = KEYS[len(keys)]
    return keys[name]


def _tokens(style: Style) -> "list[str]":
    tokens = []
    if style.fg is not None:
        tokens.append("fg=" + _colour(style.fg))
    if style.bg is not None:
        tokens.append("bg=" + _colour(style.bg))
    tokens += [flag for flag in ("bold", "dim", "italic") if getattr(style, flag)]
    if style.underline == "single":
        tokens.append("underline")
    elif style.underline is not None:
        tokens.append(f"underline={style.underline}")
    if style.underline_colour is not None:
        tokens.append("ul=" + _colour(style.underline_colour))
    tokens += [flag for flag in ("strike", "reverse") if getattr(style, flag)]
    if style.link is not None:
        tokens.append("link=" + _printable(style.link, "link target"))
    return tokens


def _colour(colour: Colour) -> str:
    if colour.role:
        return "@" + _printable(colour.role, "colour role")
    if colour.form == "default":
        return "default"
    if colour.form == "name":
        return colour.value
    if colour.form == "index":
        return str(colour.value)
    if colour.form == "ink" and colour.value.name:
        return "ink:" + _printable(colour.value.name, "ink name")
    return colour.hex


def _printable(value: str, what: str) -> str:
    if any(ch.isspace() or _is_control(ch) for ch in value):
        raise ValueError(f"{what} holds whitespace or a control character: {value!r}")
    return value


def _is_control(ch: str) -> bool:
    code = ord(ch)
    return code < 0x20 or 0x7F <= code <= 0x9F


def _as_label(style: object) -> "Label | None":
    name = label(style)
    return None if name == "" else Label(name)


def _labelled_line(line: Line) -> Line:
    return merge(Line(tuple(Span(span.text, _as_label(span.style)) for span in line.spans)))


# -- reading back

def _fail(index: int, message: str) -> ValueError:
    return ValueError(f"snapshot line {index + 1}: {message}")


def _parse_styled(lines: "list[str]") -> Rows:
    w, h = _size(lines[0])
    texts = [_text_row(_take(lines, 1 + y), w, 1 + y) for y in range(h)]
    _separator(lines, 1 + h)
    masks = [_mask_row(_take(lines, 2 + h + y), w, 2 + h + y) for y in range(h)]
    _separator(lines, 2 + 2 * h)
    legend = _legend(lines, 3 + 2 * h)
    return Rows(tuple(_read_row(texts[y], masks[y], legend, w, 2 + h + y) for y in range(h)))


def _size(header: str) -> "tuple[int, int]":
    found = _SIZE.fullmatch(header)
    if found is None:
        raise _fail(0, f"expected {HEADER!r} and a size WxH, got {header!r}")
    return int(found[1]), int(found[2])


def _take(lines: "list[str]", index: int) -> str:
    if index >= len(lines):
        raise _fail(index, "the snapshot ends early")
    return lines[index]


def _separator(lines: "list[str]", index: int) -> None:
    if _take(lines, index) != SEPARATOR:
        raise _fail(index, f"expected {SEPARATOR!r}, got {lines[index]!r}")


def _text_row(line: str, w: int, index: int) -> "tuple[Cell, ...]":
    laid = put(Line.of(line))
    if len(laid) > w:
        raise _fail(index, f"the text takes {len(laid)} cells, more than {w}")
    return laid + (_PAD,) * (w - len(laid))


def _mask_row(line: str, w: int, index: int) -> str:
    if len(line) > w:
        raise _fail(index, f"the mask has {len(line)} characters, more than {w}")
    for ch in line:
        if ch != PLAIN and ch not in KEYS:
            raise _fail(index, f"{ch!r} is neither {PLAIN!r} nor a key")
    return line


def _legend(lines: "list[str]", start: int) -> "dict[str, Label]":
    legend: dict[str, Label] = {}
    for index in range(start, len(lines)):
        key, name = _legend_line(lines[index], index)
        if key in legend:
            raise _fail(index, f"the key {key!r} appears twice in the legend")
        legend[key] = name
    return legend


def _legend_line(line: str, index: int) -> "tuple[str, Label]":
    if len(line) < 3 or line[0] not in KEYS or line[1] != " ":
        raise _fail(index, f"expected a key, a space and a label, got {line!r}")
    try:
        return line[0], Label(line[2:])
    except ValueError as error:
        raise _fail(index, str(error)) from None


def _read_row(laid: "tuple[Cell, ...]", mask: str, legend: "dict[str, Label]", w: int,
              index: int) -> Line:
    marks = mask.ljust(w, PLAIN)
    for ch in mask:
        if ch != PLAIN and ch not in legend:
            raise _fail(index, f"the key {ch!r} is not in the legend")
    spans: list[Span] = []
    for x, cell in enumerate(laid):
        if cell.width == 0:
            continue
        if cell.width == 2 and marks[x] != marks[x + 1]:
            raise _fail(index, f"a wide glyph's columns {x} and {x + 1} differ in the mask")
        spans.append(Span(cell.glyph, None if marks[x] == PLAIN else legend[marks[x]]))
    return merge(Line(tuple(spans)))


# -- checks and files

def _check_str(value: object, name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a str, got {type(value).__name__}")


def _check_bool(value: object, name: str) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a bool, got {type(value).__name__}")


def _path_name(path: object) -> str:
    if not isinstance(path, (str, os.PathLike)):
        raise TypeError(f"path must be a str or os.PathLike, got {type(path).__name__}")
    name = os.fspath(path)
    if not isinstance(name, str):
        raise TypeError(f"path must name a str path, got {type(name).__name__}")
    return name


def _read_golden(name: str) -> str:
    with open(name, encoding="utf-8", newline="") as file:
        content = file.read()
    return content[:-1] if content.endswith("\n") else content


def _write_golden(name: str, snapshot: str) -> None:
    parent = os.path.dirname(name)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(name, "w", encoding="utf-8", newline="") as file:
        file.write(snapshot + "\n")
