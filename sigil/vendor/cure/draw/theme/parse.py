"""[Parse]: the strict YAML subset from text: extends (only among the texts given),
$palette refs, cycles refused; no code, no includes.

Kind: service (a data class, an error class and pure functions).

What it does: themes declare names, cure maps names to the terminal (vocabulary and
medium apart). `parse` turns a theme's text into a {Raw}: a FLAT mapping from key
paths to scalar strings, each with the source and line it came from. `merge` lays one
Raw over another (what `extends` means), `chain` follows `extends` among the theme
texts the app was given (Files reads them from the app's search path; nothing here
reads a file), and `palette` resolves the `palette` section: `$name` references,
chains of them, and declared inks. [Roles] and [Charset] read a Raw; nothing here
knows about roles or glyphs.

Ported from sigil's `sigil/present/themes.py` (the same grammar, so sigil's
`themes/sigil.yaml` parses unchanged), with these fixes: control characters are
refused (a theme reaches the terminal only as cells cure emits itself); a tab may
follow the key's colon; a plain `key: #0d1117` (a colour YAML reads as a comment)
is an error instead of a silent empty value; plain values starting with a YAML
indicator are refused instead of read differently from YAML; keys are checked; and
`extends` takes a theme NAME only (never a path), resolved only among the texts given.

The grammar (`parse(text, source="<theme>")`). Every error is a `ThemeError` naming
`source` and the 1-based line number.

1. A leading U+FEFF (BOM) is dropped. `"\\r\\n"` becomes `"\\n"`; lines are split on
   `"\\n"` only. Line 1 is the text before the first `"\\n"`.
2. A line holding a control character is an error, wherever it stands (comments
   included): C0 U+0000..U+001F other than TAB U+0009, DEL U+007F, C1 U+0080..U+009F.
   So a lone `"\\r"` is an error ("control character U+000D").
3. Comments: scanning left to right, a `#` at column 0 or right after a space or tab
   starts a comment running to the end of the line, unless it stands inside a quoted
   run. A quoted run opens at a `"` or `'` that stands at column 0 or right after a
   space, tab or colon, and ends at its closing quote (a backslash escapes the next
   character inside `"`; `''` is an escaped quote inside `'`); an unclosed run lasts
   to the end of the line. A `#` with anything else before it (`a#b`) is text.
4. Trailing spaces and tabs are dropped. A line that is then empty or holds only
   spaces and tabs is skipped (blank and comment-only lines).
5. Indentation is the leading run of spaces. A tab (or any other whitespace) where
   the indentation ends is an error ("indent with spaces only").
6. A body (the line after its indentation) that is `-` or starts with `- `, `[` or
   `{` is an error ("lists and flow collections are not supported").
7. The separator is the first `:` that is followed by a space, a tab or the end of
   the body, searched after a leading quoted key when the body starts with a quote.
   No separator is an error ("expected `key: value`").
8. The key is the text before the separator with spaces and tabs stripped, unquoted
   when quoted (rules 10b/10c). An empty key is an error ("empty key"). A key must
   match `KEY`: one or more segments of ASCII letters, digits, `_` and `-`, joined by
   single dots (`ui`, `bar_fg`, `list.item.selected`); anything else is an error
   ("bad key"). Quoting a key changes nothing (`"ui": x` is `ui: x`).
9. The value is the text after the separator with spaces and tabs stripped.
   a. Empty (`key:`): when the next content line is indented deeper, `key` opens a
      map at that line's indentation; otherwise `key` is a leaf whose value is `""`.
      An empty value whose line had a comment whose `#` is directly followed by an
      ASCII letter or digit (`bg: #0d1117`) is an error ("a value starting with #
      must be quoted").
   b. Otherwise it is a scalar (rule 10) and `key` is a leaf.
10. Scalars:
   a. Plain: the text as it stands. A plain scalar starting with one of `[ { | > & *
      ! % @` or a backquote is an error ("quote a value that starts with X").
   b. Double-quoted (starts with `"`): JSON string rules, not YAML's (the whole value
      text is read as one JSON string: `\\"`, `\\\\`, `\\n`, `\\u00e9` ...); anything
      after the closing quote, or a malformed string, is an error.
   c. Single-quoted (starts with `'`): `''` stands for one `'` (and does not end the
      string); it must be closed, with nothing after the close.
   d. A decoded key or value holding a control character (rule 2's set, TAB
      included: a raw tab inside a value, or a `\\t` escape) is an error.
11. Structure: sibling keys share one indentation; a line indented less closes maps
   back to the sibling group at its indentation, and an indentation that matches no
   open group is an error ("inconsistent indentation"; for the first content line
   at a column above 0: "top-level keys start at column 0"). A line indented deeper
   that does not follow an empty `key:` is "inconsistent indentation" too.
12. A key may appear once per map ("duplicate key 'x'"), and a key path once per
   text: the path of a leaf is its map's path followed by its key's segments, so
   `ui:` / `  bar.fg: x` and `ui.bar:` / `  fg: y` both give `("ui", "bar", "fg")`
   and the second is a "duplicate key 'ui.bar.fg'" at its line. A path may be both a
   leaf and a prefix of other leaves (`list.item: x` beside `list.item.selected: y`).
   A map with no leaves under it (`key:` followed by a deeper `key2:` that is a
   leaf with `""`) contributes only that leaf.

No anchors, aliases, tags, merge keys, lists, flow collections, multi-line scalars
or documents: each is an error by the rules above (`<<`, `&a`, `---` are bad keys or
values). All values are strings.

Data:
- `Raw(source: str, leaves: Mapping[tuple[str, ...], str], lines: Mapping[tuple[str,
  ...], tuple[str, int]])` (frozen dataclass; immutable all the way down, Theme's
  rule): `leaves` maps each leaf's key path to its value, in document order; `lines`
  maps the same paths to `(source, line)`. Both are read-only: `__post_init__`
  stores each as a `types.MappingProxyType` over a private `dict` copy of the mapping
  given (writing raises; the caller's dict is not kept; `==` with a plain dict holds).
  `__reduce__` rebuilds from plain dict copies (copy and pickle as today). Not
  hashable (`hash` raises `TypeError`, as today). `merge` and `chain` read these and
  build new dicts for a new Raw; they never write a Raw's own. `Raw.at(*path) -> str | None` is the value at that exact
  path. `Raw.line(*path) -> tuple[str, int] | None` is where it came from.
- `ThemeError(source: str, line: int | None, reason: str)`: a `ValueError` with those
  three attributes; `str(e)` is `f"{source}:{line}: {reason}"`, or
  `f"{source}: {reason}"` when `line` is `None`.

Merging (`merge(base, over) -> Raw`): what `extends` means. For every leaf path P of
`over`, the base's leaves strictly below P (longer paths starting with P) are
dropped, so a scalar in `over` replaces a whole map of the base; base leaves at P
itself or at a proper prefix of P are kept. Then the result is the remaining base
leaves in base order, updated with over's leaves (`dict.update`: a path also in base
keeps the base's position and takes over's value; a new path is appended in over's
order). `lines` follows the
same rule (each leaf keeps the `(source, line)` of the Raw it came from). The
result's `source` is `over.source`.

Following extends (`chain(name, texts) -> Raw`). `texts` maps theme names to their
texts (what Files read from the app's search path, plus Theme's `BUILTIN` when the
app adds it); it is the only place an `extends` is looked up.

1. `name` not a key of `texts`: `ThemeError(name, None, "unknown theme 'name'")`.
2. Parse `texts[name]` with `source=name`. Its `("extends",)` leaf, when present,
   names the parent: it must match `NAME` (one KEY segment: `[A-Za-z0-9_-]+`; no
   dots, no slashes, so never a path), else `ThemeError(name, line, "extends takes a
   theme name")`; a leaf below it (`extends:` opening a map) is the same error.
3. The parent is chained the same way (its own `extends` followed in turn), and the
   result is `merge(parent_chain, this)` with the `("extends",)` leaf dropped.
4. An ancestor's `("name",)` and `("label",)` leaves are dropped before merging, so
   the result holds only the named theme's own `name` and `label`.
5. A name met twice on the way up is `ThemeError(<the theme naming it>, <its
   extends line>, "extends cycle: a -> b -> a")`; a parent missing from `texts` is
   `ThemeError(<the theme naming it>, <its extends line>, "unknown theme 'x' (not
   among the themes given)")`. A ThemeError from parsing an ancestor names that
   ancestor as its source.

The palette (`palette(raw) -> dict[str, Ink | str]`), from the leaves under
`("palette",)`, in leaf order:

- `("palette", n)`: a colour entry. Its value is `$m` (a reference to entry `m`,
  followed until it reaches a non-reference; entries may chain) or a literal colour
  that Style's `resolve` takes with no inks (one of the 16 names, `default`,
  `#rgb` / `#rrggbb`, an index `0`..`255` in digits). The entry's result is the
  literal string reached, or the `Ink` when the chain reaches an ink entry.
- `("palette", n, f)` with `f` in `INK_FIELDS` (`rgb`, `tty256`, `tty16`): an ink
  entry, `Ink(n, rgb, tty256, tty16)`: `rgb` is required and is a literal `#rgb` /
  `#rrggbb` (no reference); `tty256` digits 0..255; `tty16` one of Style's `NAMES`.
- Errors (`ThemeError` at the offending leaf's source and line): an entry that is
  both a colour and an ink ("palette.n is both a colour and an ink"); a leaf under
  `palette` that is neither shape ("palette.n.f: not an ink field"; `("palette",)`
  itself as a leaf: "palette must be a map"); a reference that is not `$` followed by
  one KEY segment ("bad palette reference"); an unknown entry ("unknown palette
  colour $m"); a cycle ("palette cycle through $m"); a literal that is not a colour
  ("not a colour: 'x'"); an ink without `rgb`, or a field out of range or of the
  wrong form.

References (`ref(entries, token, where) -> Ink | str`): the shared rule for a `$name` token
elsewhere (role values, `derive.ground`): `token` must be `$` followed by one KEY
segment ("bad palette reference" otherwise) naming a key of `entries`, the resolved
palette ("unknown palette colour $m" otherwise); the result is that entry. `where`
is the `(source, line)` the ThemeError names (`line` may be None).

Immutable all the way down (Theme's rule; Q9b: the public helpers the Theme package's
frozen data classes use, [Charset]'s `Charset`, [Roles]' `Roles`, [Derive]'s
`Derivation`, [Ramp]'s `Ramp` and Theme's own `Theme` as well as `Raw`, in place of
the private `_freeze`, `_tuples` and `_reduce` they import today; those stay, as the
bodies these call or as aliases, until the build moves the callers):
- `freeze_maps(obj, *names) -> None`: for each name, the field `name` of the frozen
  dataclass instance `obj` becomes a `types.MappingProxyType` over `dict(value)`, a
  private copy (the caller's mapping is not kept; writing the proxy raises). Called
  from `__post_init__` (it writes with `object.__setattr__`, so a frozen dataclass
  takes it). Names already frozen are copied again (a proxy over a new dict).
- `freeze_seqs(obj, *names) -> None`: for each name, the field becomes
  `tuple(value)`; `None` is kept, and a value whose type is exactly `tuple` is kept
  as it is (the same object). Called from `__post_init__`, as `freeze_maps`.
- `rebuild(obj) -> tuple`: what a frozen data class's `__reduce__` returns, `(type(obj),
  args)`, `args` the values of `dataclasses.fields(obj)` in field order, each
  `MappingProxyType` among them replaced by a plain `dict` copy (so copy and pickle
  rebuild through the constructor, which freezes again; other values as they are).
- Errors: `freeze_maps` / `freeze_seqs`: `AttributeError` when `obj` has no field
  `name`; what `dict(value)` / `tuple(value)` raise for a value that is not a mapping
  (or iterable of pairs) / not iterable (`TypeError`, or `ValueError` for a bad pair).
  `rebuild`: `TypeError` when `obj` is not a dataclass instance. Effects: the two
  freezers write only the named fields of `obj`; `rebuild` none.

Inputs: `parse`: `text: str`, `source: str`. `merge`: two {Raw}. `chain`: `name: str`,
  `texts: Mapping[str, str]`. `palette`: a {Raw}. `ref`: the dict `palette` gives, a
  `str`, a `(source, line)` pair.
Outputs: {Raw}; the palette as `dict[str, Ink | str]`; `ref`: an `Ink` or `str`.
Errors: `ThemeError` as above (every one naming its source and, when it comes from
  a line, its line). `TypeError` when `text`, `source` or `name` is not a `str`, or
  a value of `texts` is not a `str`.
Effects: none.

Usage:
    from cure.draw.theme.parse import parse, merge, chain, palette, ThemeError
    raw = parse("palette:\\n  bg: \\"#0d1117\\"\\nui:\\n  text: $bg  # a role\\n", "t")
    raw.leaves      # {("palette", "bg"): "#0d1117", ("ui", "text"): "$bg"}
    raw.line("ui", "text")                       # ("t", 4)
    palette(raw)                                 # {"bg": "#0d1117"}
    chain("child", {"child": "extends: base\\nui.text: red\\n",
                    "base": "ui.text: blue\\nui.dim: black\\n"}).leaves
    # {("ui", "text"): "red", ("ui", "dim"): "black"}
    parse("bg: #fff\\n", "t")                     # ThemeError: t:1: a value starting with # must be quoted
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from types import MappingProxyType

from cure.core.style import NAMES, Ink, parse_hex, resolve

KEY = r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*"
"""A key: dot-joined segments of ASCII letters, digits, `_` and `-` (a regex, full match)."""

NAME = r"[A-Za-z0-9_-]+"
"""One key segment: a theme name, a palette entry name (a regex, full match)."""

PALETTE = "palette"
"""The section `$name` references resolve against."""

INK_FIELDS: tuple[str, ...] = ("rgb", "tty256", "tty16")
"""The fields of an ink entry in the palette."""

Path = tuple[str, ...]


class ThemeError(ValueError):
    """A theme that cannot be parsed or resolved: `source`, `line` (or None), `reason`."""

    def __init__(self, source: str, line: "int | None", reason: str) -> None:
        where = source if line is None else f"{source}:{line}"
        super().__init__(f"{where}: {reason}")
        self.source = source
        self.line = line
        self.reason = reason


@dataclass(frozen=True)
class Raw:
    """{Raw}: a parsed theme, flat: leaf key path -> value, and path -> (source, line).

    `leaves` and `lines` are read-only proxies over copies made in `__post_init__`.
    """

    source: str
    leaves: Mapping
    lines: Mapping

    def __post_init__(self) -> None:
        freeze_maps(self, "leaves", "lines")

    def __reduce__(self):
        return rebuild(self)

    def at(self, *path: str) -> "str | None":
        """The value of the leaf at exactly `path`, or None."""
        return self.leaves.get(path)

    def line(self, *path: str) -> "tuple[str, int] | None":
        """`(source, line)` of the leaf at exactly `path`, or None."""
        return self.lines.get(path)


def parse(text: str, source: str = "<theme>") -> Raw:
    """The {Raw} of a theme's text, by the grammar above (ThemeError with the line)."""
    _check_str(text, "text")
    _check_str(source, "source")
    if text.startswith("﻿"):
        text = text[1:]
    tree = _Tree(source)
    for n, line in enumerate(text.replace("\r\n", "\n").split("\n"), start=1):
        tree.line(n, line)
    tree.end()
    return Raw(source, tree.leaves, tree.lines)


def merge(base: Raw, over: Raw) -> Raw:
    """`over` laid on `base` (see Merging)."""
    covered = set(over.leaves)
    kept = [p for p in base.leaves if not any(p[:i] in covered for i in range(1, len(p)))]
    leaves = {p: base.leaves[p] for p in kept}
    lines = {p: base.lines[p] for p in kept}
    leaves.update(over.leaves)
    lines.update(over.lines)
    return Raw(over.source, leaves, lines)


def chain(name: str, texts: Mapping[str, str]) -> Raw:
    """The theme `name` with its `extends` followed among `texts` (see Following extends)."""
    _check_str(name, "name")
    for value in texts.values():
        _check_str(value, "a theme text")
    if name not in texts:
        raise ThemeError(name, None, f"unknown theme '{name}'")
    return _chain(name, texts, ())


def palette(raw: Raw) -> "dict[str, Ink | str]":
    """The resolved palette: entry name -> literal colour str or Ink (see The palette)."""
    colours, fields, order = _palette_leaves(raw)
    inks = {name: _ink(name, fields[name]) for name in fields}
    return {name: inks[name] if name in inks else _follow(name, colours, inks) for name in order}


def ref(entries: "Mapping[str, Ink | str]", token: str, where: "tuple[str, int | None]") -> "Ink | str":
    """The palette entry a `$name` token names (ThemeError at `where` otherwise)."""
    source, line = where
    if not isinstance(token, str) or not re.fullmatch(r"\$" + NAME, token):
        raise ThemeError(source, line, "bad palette reference")
    if token[1:] not in entries:
        raise ThemeError(source, line, f"unknown palette colour {token}")
    return entries[token[1:]]


# -- immutable all the way down (the rule of `cure.draw.theme`, shared by its data classes)

def freeze_maps(obj: object, *names: str) -> None:
    """Store each named mapping field of the frozen dataclass `obj` as a read-only proxy
    over a private dict copy (see Immutable all the way down)."""
    for name in names:
        object.__setattr__(obj, name, MappingProxyType(dict(getattr(obj, name))))


def freeze_seqs(obj: object, *names: str) -> None:
    """Store each named sequence field of the frozen dataclass `obj` as a tuple, None kept
    (see Immutable all the way down)."""
    for name in names:
        value = getattr(obj, name)
        if value is not None and type(value) is not tuple:
            object.__setattr__(obj, name, tuple(value))


def rebuild(obj: object) -> tuple:
    """`(type(obj), its field values in order, each read-only mapping as a plain dict)`:
    a frozen data class's `__reduce__` (see Immutable all the way down)."""
    if isinstance(obj, type) or not is_dataclass(obj):
        raise TypeError(f"expected a dataclass instance, got {type(obj).__name__}")
    args = tuple(dict(v) if isinstance(v, MappingProxyType) else v
                 for v in (getattr(obj, f.name) for f in fields(obj)))
    return (type(obj), args)


# -- the grammar

_INDICATORS = "[{|>&*!%@`"


class _Tree:
    """The parser's state across lines: the open maps, the pending `key:`, the leaves."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.leaves: dict = {}
        self.lines: dict = {}
        self.stack: list = [(0, (), set())]      # (indent, path, keys seen), innermost last
        self.pending = None                      # (indent, path, line) of a `key:` that may open a map
        self.first = True

    def error(self, n: int, reason: str) -> ThemeError:
        return ThemeError(self.source, n, reason)

    def line(self, n: int, line: str) -> None:
        bad = next((ch for ch in line if _is_control(ch) and ch != "\t"), None)
        if bad is not None:
            raise self.error(n, f"control character U+{ord(bad):04X}")
        line, hashed = _strip_comment(line)
        line = line.rstrip(" \t")
        if not line:
            return
        indent = len(line) - len(line.lstrip(" "))
        if line[indent].isspace():
            raise self.error(n, "indent with spaces only")
        body = line[indent:]
        if body == "-" or body.startswith(("- ", "[", "{")):
            raise self.error(n, "lists and flow collections are not supported")
        self.place(n, indent)
        key, value = self.split(n, body)
        _, path, keys = self.stack[-1]
        if key in keys:
            raise self.error(n, f"duplicate key '{key}'")
        keys.add(key)
        path = path + tuple(key.split("."))
        if value:
            self.leaf(n, path, _scalar(value, lambda r: self.error(n, r)))
        elif hashed is not None and hashed.isascii() and hashed.isalnum():
            raise self.error(n, "a value starting with # must be quoted")
        else:
            self.pending = (indent, path, n)

    def place(self, n: int, indent: int) -> None:
        if self.pending is not None:
            p_indent, p_path, p_line = self.pending
            self.pending = None
            if indent > p_indent:
                self.stack.append((indent, p_path, set()))
            else:
                self.leaf(p_line, p_path, "")
        while indent < self.stack[-1][0]:
            self.stack.pop()
        if indent != self.stack[-1][0]:
            if self.first:
                raise self.error(n, "top-level keys start at column 0")
            raise self.error(n, "inconsistent indentation")
        self.first = False

    def split(self, n: int, body: str) -> "tuple[str, str]":
        sep = _separator(body)
        if sep < 0:
            raise self.error(n, "expected `key: value`")
        key = body[:sep].strip(" \t")
        if key[:1] in ("\"", "'"):
            key = _scalar(key, lambda r: self.error(n, r))
        if not key:
            raise self.error(n, "empty key")
        if not re.fullmatch(KEY, key):
            raise self.error(n, "bad key")
        return key, body[sep + 1:].strip(" \t")

    def leaf(self, n: int, path: Path, value: str) -> None:
        if path in self.leaves:
            raise self.error(n, f"duplicate key '{'.'.join(path)}'")
        self.leaves[path] = value
        self.lines[path] = (self.source, n)

    def end(self) -> None:
        if self.pending is not None:
            _, path, n = self.pending
            self.leaf(n, path, "")


def _is_control(ch: str) -> bool:
    code = ord(ch)
    return code < 0x20 or 0x7F <= code <= 0x9F


def _skip_quoted(s: str, i: int) -> int:
    """Past the quoted run opening at `s[i]` (len(s) when it is not closed)."""
    q = s[i]
    i += 1
    while i < len(s):
        if q == "\"" and s[i] == "\\":
            i += 2
            continue
        if s[i] == q:
            if q == "'" and s[i + 1:i + 2] == "'":
                i += 2
                continue
            return i + 1
        i += 1
    return len(s)


def _strip_comment(line: str) -> "tuple[str, str | None]":
    """The line without its comment, and the character after the comment's `#`
    ("" at the end of the line; None when there was no comment)."""
    i = 0
    while i < len(line):
        ch = line[i]
        if ch in "\"'" and (i == 0 or line[i - 1] in " \t:"):
            i = _skip_quoted(line, i)
            continue
        if ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i], line[i + 1:i + 2]
        i += 1
    return line, None


def _separator(body: str) -> int:
    i = _skip_quoted(body, 0) if body[:1] in ("\"", "'") else 0
    while i < len(body):
        if body[i] == ":" and body[i + 1:i + 2] in ("", " ", "\t"):
            return i
        i += 1
    return -1


def _scalar(text: str, error) -> str:
    if text[:1] == "\"":
        try:
            value = json.loads(text)
        except ValueError:
            raise error("malformed double-quoted string") from None
    elif text[:1] == "'":
        value = _single_quoted(text, error)
    elif text[:1] in _INDICATORS:
        raise error(f"quote a value that starts with {text[0]}")
    else:
        value = text
    bad = next((ch for ch in value if _is_control(ch)), None)
    if bad is not None:
        raise error(f"control character U+{ord(bad):04X}")
    return value


def _single_quoted(text: str, error) -> str:
    out = []
    i = 1
    while i < len(text):
        if text[i] == "'":
            if text[i + 1:i + 2] == "'":
                out.append("'")
                i += 2
                continue
            if i + 1 != len(text):
                raise error("text after a closing single quote")
            return "".join(out)
        out.append(text[i])
        i += 1
    raise error("unclosed single-quoted string")


# -- extends

def _chain(name: str, texts: Mapping[str, str], trail: tuple) -> Raw:
    raw = parse(texts[name], name)
    parent, line = _parent(raw)
    own = _without(raw, lambda p: p[0] == "extends")
    if parent is None:
        return own
    if parent in trail or parent == name:
        cycle = " -> ".join(trail + (name, parent))
        raise ThemeError(name, line, f"extends cycle: {cycle}")
    if parent not in texts:
        raise ThemeError(name, line, f"unknown theme '{parent}' (not among the themes given)")
    base = _chain(parent, texts, trail + (name,))
    return merge(_without(base, lambda p: p in (("name",), ("label",))), own)


def _parent(raw: Raw) -> "tuple[str | None, int | None]":
    for path, value in raw.leaves.items():
        if path[0] != "extends":
            continue
        line = raw.lines[path][1]
        if len(path) > 1 or not re.fullmatch(NAME, value):
            raise ThemeError(raw.source, line, "extends takes a theme name")
        return value, line
    return None, None


def _without(raw: Raw, drop) -> Raw:
    leaves = {p: v for p, v in raw.leaves.items() if not drop(p)}
    return Raw(raw.source, leaves, {p: raw.lines[p] for p in leaves})


# -- the palette

def _palette_leaves(raw: Raw) -> tuple:
    """The palette's colour entries `name -> (value, where)`, its ink entries
    `name -> {field: (value, where)}`, and the entry names in leaf order."""
    colours, fields, order = {}, {}, []
    for path, value in raw.leaves.items():
        if path[0] != PALETTE:
            continue
        where = raw.lines[path]
        if len(path) == 1:
            raise ThemeError(*where, "palette must be a map")
        name = path[1]
        is_ink = len(path) == 3 and path[2] in INK_FIELDS
        if len(path) > 2 and not is_ink:
            raise ThemeError(*where, f"{'.'.join(path)}: not an ink field")
        if name in (colours if is_ink else fields):
            raise ThemeError(*where, f"palette.{name} is both a colour and an ink")
        if name not in order:
            order.append(name)
        if is_ink:
            fields.setdefault(name, {})[path[2]] = (value, where)
        else:
            colours[name] = (value, where)
    return colours, fields, order


def _follow(name: str, colours: dict, inks: dict) -> "Ink | str":
    seen = [name]
    value, where = colours[name]
    while value.startswith("$"):
        ref({**colours, **inks}, value, where)
        target = value[1:]
        if target in inks:
            return inks[target]
        if target in seen:
            raise ThemeError(*where, f"palette cycle through ${target}")
        seen.append(target)
        value, where = colours[target]
    try:
        resolve(value)
    except (TypeError, ValueError):
        raise ThemeError(*where, f"not a colour: '{value}'") from None
    return value


def _ink(name: str, fields: dict) -> Ink:
    if "rgb" not in fields:
        first = next(iter(fields.values()))[1]
        raise ThemeError(*first, f"palette.{name}: an ink needs rgb")
    value, where = fields["rgb"]
    rgb = parse_hex(value)
    if rgb is None:
        raise ThemeError(*where, f"palette.{name}.rgb must be #rgb or #rrggbb")
    tty256 = tty16 = None
    if "tty256" in fields:
        value, where = fields["tty256"]
        if not (value.isascii() and value.isdigit() and int(value) <= 255):
            raise ThemeError(*where, f"palette.{name}.tty256 must be an index 0..255")
        tty256 = int(value)
    if "tty16" in fields:
        value, where = fields["tty16"]
        if value not in NAMES:
            raise ThemeError(*where, f"palette.{name}.tty16 must be one of the 16 colour names")
        tty16 = value
    return Ink(name, rgb, tty256, tty16)


def _check_str(value: object, what: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{what} must be a str, got {type(value).__name__}")
