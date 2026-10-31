"""
sigil themes — load a Sigil colour theme (themes/<name>.yaml).

A theme is a small YAML document: nested maps, scalar values, # comments. A
value "$name" refers to palette.name; `extends: other` starts from another
theme and overrides only the keys this one sets. sigil view and the site both read
the same files, so a theme colours the terminal viewer and the web page alike.

    sigil themes [NAME|PATH]       # print the resolved theme as JSON (and, on
                                   # stderr, a warning for each of problems())
    sigil themes --list            # list the themes found
    sigil themes --help

Lookup for a NAME: themes/ in the folder that holds the sigil package (the
repository, or the skill's scripts/), then each directory on
SIGIL_THEME_PATH (os.pathsep-separated); `index` is never a theme name. A PATH
(it ends in .yaml/.yml or contains a slash) is read directly. The default is env
SIGIL_THEME, else "sigil". An `extends` value that is a path is resolved against
the folder of the theme that names it; a bare name uses the lookup above.

A command that loads a dialect (view, frames draw, highlight) colours with
load(spec, dialect): an explicit spec (--theme) wins, then env SIGIL_THEME (the
person's choice), then the dialect's THEME hook (sigil.core.dialects.theme_hook:
a name, or a path taken against the dialect module's folder), read exactly as
any theme file is, else "sigil".
`sigil themes` itself loads no dialect. Standard library only.

The YAML subset (the site's JavaScript parser implements the same rules):
  - "\\r\\n" becomes "\\n", then lines split on "\\n" only; a leading BOM is ignored.
  - Indentation is spaces only: a tab or any other whitespace in it is an error.
    Trailing spaces/tabs are dropped; blank and comment-only lines are skipped.
  - A comment starts at "#" at line start or after a space/tab, outside quotes
    (a quote opens only at line start or after a space, tab or colon).
  - Each line is `key: value` or `key:` (the colon is followed by a space or
    ends the line). Keys and values are plain, "double-" or 'single-quoted'.
  - Double-quoted scalars follow JSON string rules (not YAML's): \\" and the
    other JSON escapes; \\" does not end the string.
  - Single-quoted scalars write a quote as '' (which does not end the string,
    in keys and values alike) and must be closed, with nothing after the close.
  - `key:` with no value followed by deeper-indented lines is a map; otherwise
    its value is "". Siblings share one indent; top-level keys are at column 0.
  - Errors: duplicate key, empty key, a line that is "-" or starts with "- ",
    "[" or "{" (lists / flow collections), inconsistent indentation, maps
    nested more than MAX_DEPTH (16) deep, an `extends` chain of more than
    MAX_EXTENDS (16) themes.
All values are strings; maps are dicts.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Union

from sigil.core import dialects

_DIR = Path(__file__).resolve().parents[2]      # the folder holding themes/
DEFAULT = "sigil"

Node = Union[dict, str]
MAX_DEPTH = 16          # maps nested deeper than this are an error (sigil's go 2 deep)
MAX_EXTENDS = 16        # a longer `extends` chain is an error
MAX_BYTES = 1024 * 1024  # a larger theme file is an error
HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})")   # a colour: #rrggbb or #rgb


class ThemeError(ValueError):
    """A theme that cannot be found, read, parsed or resolved."""


# ---------------------------------------------------------------------------
# The YAML subset
# ---------------------------------------------------------------------------

def _skip_quoted(s: str, i: int) -> int:
    """`s[i]` opens a quote; return the index just past its close (len(s) if
    unclosed). Double quotes: a backslash escapes the next character. Single
    quotes: '' is an escaped quote."""
    q = s[i]
    i += 1
    while i < len(s):
        ch = s[i]
        if q == '"' and ch == "\\":
            i += 2
            continue
        if ch == q:
            if q == "'" and s[i + 1:i + 2] == "'":
                i += 2
                continue
            return i + 1
        i += 1
    return len(s)


def _strip_comment(line: str) -> str:
    """Drop a # comment: one at the start or after whitespace, outside quotes."""
    i = 0
    while i < len(line):
        ch = line[i]
        if ch in "\"'" and (i == 0 or line[i - 1] in " \t:"):
            i = _skip_quoted(line, i)
            continue
        if ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i]
        i += 1
    return line


def _single_quoted(text: str, where: str) -> str:
    out = []
    i = 1
    while i < len(text):
        ch = text[i]
        if ch == "'":
            if text[i + 1:i + 2] == "'":
                out.append("'")
                i += 2
                continue
            if i + 1 != len(text):
                raise ThemeError(f"{where}: text after a closing single quote")
            return "".join(out)
        out.append(ch)
        i += 1
    raise ThemeError(f"{where}: unterminated single-quoted string")


def _scalar(text: str, where: str) -> str:
    text = text.strip(" \t")
    if text[:1] == '"':
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            raise ThemeError(f"{where}: bad double-quoted string {text}") from None
        if not isinstance(value, str):  # pragma: no cover - a "..." is a str
            raise ThemeError(f"{where}: bad double-quoted string {text}")
        return value
    if text[:1] == "'":
        return _single_quoted(text, where)
    return text


def _key(text: str, where: str) -> str:
    key = _scalar(text, where)
    if not key:
        raise ThemeError(f"{where}: empty key")
    return key


def _find_colon(body: str) -> int:
    """Index of the key/value colon (followed by a space or the end), skipping a
    quoted key; -1 if there is none."""
    i = _skip_quoted(body, 0) if body[:1] in "\"'" else 0
    while i < len(body):
        if body[i] == ":" and (i + 1 == len(body) or body[i + 1] == " "):
            return i
        i += 1
    return -1


def parse(text: str, source: str = "<theme>") -> dict:
    """Parse the theme YAML subset (see the module docstring) into nested dicts
    of strings."""
    if text.startswith("﻿"):
        text = text[1:]
    root: dict = {}
    stack: list[tuple[int, dict]] = [(0, root)]      # (indent, map), innermost last
    pending: tuple[int, dict, str] | None = None     # a `key:` that may open a map
    for n, raw in enumerate(text.replace("\r\n", "\n").split("\n"), start=1):
        where = f"{source}:{n}"
        line = _strip_comment(raw).rstrip(" \t")
        if not line.strip(" \t"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if line[indent].isspace():
            raise ThemeError(f"{where}: indent with spaces only (found {line[indent]!r})")
        body = line[indent:]
        if body.startswith(("- ", "[", "{")) or body == "-":
            raise ThemeError(f"{where}: lists and flow collections are not supported")
        if pending is not None:
            p_indent, p_map, p_key = pending
            pending = None
            if indent > p_indent:                    # deeper: `key:` opens a map
                if len(stack) > MAX_DEPTH:
                    raise ThemeError(f"{where}: maps nested more than {MAX_DEPTH} deep")
                child: dict = {}
                p_map[p_key] = child
                stack.append((indent, child))
        while indent < stack[-1][0]:
            stack.pop()
        if indent != stack[-1][0]:
            if len(stack) == 1 and not root:
                raise ThemeError(f"{where}: top-level keys start at column 0")
            raise ThemeError(f"{where}: inconsistent indentation")
        cur = stack[-1][1]
        sep = _find_colon(body)
        if sep < 0:
            raise ThemeError(f"{where}: expected `key: value`")
        key, value = _key(body[:sep], where), body[sep + 1:].strip(" \t")
        if key in cur:
            raise ThemeError(f"{where}: duplicate key {key!r}")
        if value:
            cur[key] = _scalar(value, where)
        else:
            cur[key] = ""
            pending = (indent, cur, key)
    return root


# ---------------------------------------------------------------------------
# Resolution: extends + $refs
# ---------------------------------------------------------------------------

def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def resolve(theme: dict, source: str = "<theme>") -> dict:
    """Replace every "$name" with palette.name (palette entries may chain)."""
    palette = theme.get("palette", {})
    if not isinstance(palette, dict):
        raise ThemeError(f"{source}: palette must be a map of name: colour")

    def colour(value: str) -> str:
        seen: set = set()
        while isinstance(value, str) and value.startswith("$"):
            name = value[1:]
            if name in seen:
                raise ThemeError(f"{source}: palette cycle through ${name}")
            if name not in palette:
                raise ThemeError(f"{source}: unknown palette colour ${name}")
            value = palette[name]
            if not isinstance(value, str):
                raise ThemeError(f"{source}: palette.{name} is a map, not a colour")
            seen.add(name)
        return value

    def walk(node: Node) -> Node:
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        return colour(node)

    return walk(theme)


def problems(theme: dict) -> list[str]:
    """What in a resolved theme the viewer will not use, as sigil's own theme
    (themes/sigil.yaml) reads: a section or a role it has no use for (any name
    goes in palette, and in kinds for a dialect's kinds), a colour that is not
    "#rrggbb" or "#rgb" (the viewer draws sigil's own colour there), and a
    fraction that is not a number from 0 to 1. [] for a theme it reads whole."""
    ref = resolve(load_raw(DEFAULT, _base=None), DEFAULT)
    out = []
    for section, value in theme.items():
        if section not in ref:
            out.append(f"unknown section {section!r}")
            continue
        known = ref[section]
        if not isinstance(known, dict) or not isinstance(value, dict):
            if isinstance(known, dict) != isinstance(value, dict):
                out.append(f"{section} must be " + ("a map" if isinstance(known, dict)
                                                    else "a value, not a map"))
            continue
        any_role = section in ("palette", "kinds")
        for role, got in value.items():
            if role not in known and not any_role:
                out.append(f"unknown role {section}.{role}")
                continue
            like = known.get(role, "#000000")
            if isinstance(got, dict):
                out.append(f"{section}.{role} is a map, not a value")
            elif HEX_RE.fullmatch(like) and not HEX_RE.fullmatch(got):
                out.append(f"{section}.{role}: {got!r} is not a colour (#rrggbb or #rgb)")
            elif _fraction(like) is not None and _fraction(got) is None:
                out.append(f"{section}.{role}: {got!r} is not a number from 0 to 1")
    return out


def _fraction(text: str):
    try:
        k = float(text)
    except ValueError:
        return None
    return k if 0.0 <= k <= 1.0 else None


def search_path() -> list[Path]:
    dirs = [_DIR / "themes"]
    dirs += [Path(p) for p in os.environ.get("SIGIL_THEME_PATH", "").split(os.pathsep) if p]
    return dirs


def _is_path(spec: str) -> bool:
    return Path(spec).suffix in (".yaml", ".yml") or "/" in spec or os.sep in spec


def find(spec: str, base: Path | None = None) -> Path:
    """The file for a theme NAME or PATH. A relative PATH is taken against
    `base` when given (the folder of the theme that extends it), else the CWD."""
    if _is_path(spec):
        p = Path(spec).expanduser()
        if base is not None and not p.is_absolute():
            p = base / p
        if p.is_file():
            return p
        if p.exists():
            raise ThemeError(f"{p}: not a regular file (a theme is a .yaml file)")
        raise ThemeError(f"theme file not found: {p}")
    for d in search_path():
        for ext in (".yaml", ".yml"):
            if (d / f"{spec}{ext}").is_file():
                return d / f"{spec}{ext}"
    raise ThemeError(f"unknown theme {spec!r} (have: {', '.join(names()) or 'none'})")


def load_raw(spec: str, _seen: tuple[Path, ...] = (), _base: Path | None = None) -> dict:
    """A theme with `extends` applied but $refs left in place."""
    path = find(spec, _base)
    key = path.resolve()
    if key in _seen:
        raise ThemeError(f"{path}: extends cycle")
    if len(_seen) >= MAX_EXTENDS:
        raise ThemeError(f"{path}: an extends chain longer than {MAX_EXTENDS} themes")
    try:
        with path.open("rb") as fh:
            data = fh.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ThemeError(f"{path}: larger than {MAX_BYTES} bytes; not a theme")
        text = data.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ThemeError(f"{path}: cannot read theme: {exc}") from None
    theme = parse(text, str(path))
    parent = theme.pop("extends", "")
    if isinstance(parent, dict):
        raise ThemeError(f"{path}: extends must be a theme name or path, not a map")
    if parent:
        theme = _merge(load_raw(parent, _seen + (key,), path.parent), theme)
    return theme


def chosen(spec: str | None = None, dialect=None) -> tuple[str, Path | None, bool]:
    """Which theme a command colours with: (the name or path, the folder a
    relative path is read against, whether it is the dialect's THEME). An
    explicit `spec` wins, then $SIGIL_THEME (the person's choice), then the
    dialect's THEME, else sigil.
    Raises DialectError (a ValueError) for a THEME that is not a string."""
    if spec:
        return spec, None, False
    env = os.environ.get("SIGIL_THEME")
    if env:
        return env, None, False
    hooked = dialects.theme_hook(dialect)
    if hooked is not None:
        return hooked[0], hooked[1], True
    return DEFAULT, None, False


def load(spec: str | None = None, dialect=None) -> dict:
    """Load and resolve a theme by name or path, as chosen() picks it (no spec:
    $SIGIL_THEME, else the dialect's THEME, else sigil). A dialect's THEME that
    cannot be found, read or parsed is a ThemeError naming the dialect."""
    name, base, by_dialect = chosen(spec, dialect)
    try:
        return resolve(load_raw(name, _base=base), name)
    except ThemeError as exc:
        if not by_dialect:
            raise
        raise ThemeError(f"sigil dialect {getattr(dialect, 'NAME', '?')!r} THEME: "
                         f"{exc}") from None


def names() -> list[str]:
    """Theme names on the search path, first occurrence wins (index is skipped)."""
    found: list[str] = []
    for d in search_path():
        if not d.is_dir():
            continue
        for p in sorted([*d.glob("*.yaml"), *d.glob("*.yml")]):
            if p.stem != "index" and p.stem not in found:
                found.append(p.stem)
    return found


_USAGE = "usage: sigil themes [NAME|PATH] | --list | --help"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return 0
    if len(argv) > 1 or (argv and argv[0].startswith("-") and argv[0] != "--list"):
        print(_USAGE, file=sys.stderr)
        return 2
    if argv == ["--list"]:
        print("\n".join(names()))
        return 0
    try:
        theme = load(argv[0] if argv else None)
    except (ThemeError, OSError, UnicodeDecodeError) as exc:
        print(f"sigil themes: {exc}", file=sys.stderr)
        return 2
    try:
        said = problems(theme)
    except ThemeError as exc:               # sigil's own theme is missing or broken
        said = [f"cannot check it against {DEFAULT}: {exc}"]
    for problem in said:
        print(f"sigil themes: warning: {problem}", file=sys.stderr)
    print(json.dumps(theme, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
