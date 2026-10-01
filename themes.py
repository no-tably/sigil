#!/usr/bin/env python3
"""
themes.py — load a Sigil colour theme (themes/<name>.yaml).

A theme is a small YAML document: nested maps, scalar values, # comments. A
value "$name" refers to palette.name; `extends: other` starts from another
theme and overrides only the keys this one sets. view.py and the site both read
the same files, so a theme colours the terminal viewer and the web page alike.

    themes.py [NAME|PATH]          # print the resolved theme as JSON
    themes.py --list               # list the themes found
    themes.py --help

Lookup for a NAME: themes/ next to this file, then each directory on
SIGIL_THEME_PATH (os.pathsep-separated); `index` is never a theme name. A PATH
(it ends in .yaml/.yml or contains a slash) is read directly. The default is env
SIGIL_THEME, else "sigil". An `extends` value that is a path is resolved against
the folder of the theme that names it; a bare name uses the lookup above.
Standard library only.

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
    "[" or "{" (lists / flow collections), inconsistent indentation.
All values are strings; maps are dicts.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Union

_DIR = Path(__file__).resolve().parent
DEFAULT = "sigil"

Node = Union[dict, str]


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

    def colour(value: str, seen: tuple[str, ...] = ()) -> str:
        if not isinstance(value, str) or not value.startswith("$"):
            return value
        name = value[1:]
        if name in seen:
            raise ThemeError(f"{source}: palette cycle through ${name}")
        if name not in palette:
            raise ThemeError(f"{source}: unknown palette colour ${name}")
        entry = palette[name]
        if not isinstance(entry, str):
            raise ThemeError(f"{source}: palette.{name} is a map, not a colour")
        return colour(entry, seen + (name,))

    def walk(node: Node) -> Node:
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        return colour(node)

    return walk(theme)


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
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ThemeError(f"{path}: cannot read theme: {exc}") from None
    theme = parse(text, str(path))
    parent = theme.pop("extends", "")
    if isinstance(parent, dict):
        raise ThemeError(f"{path}: extends must be a theme name or path, not a map")
    if parent:
        theme = _merge(load_raw(parent, _seen + (key,), path.parent), theme)
    return theme


def load(spec: str | None = None) -> dict:
    """Load and resolve a theme by name or path (default: $SIGIL_THEME or sigil)."""
    spec = spec or os.environ.get("SIGIL_THEME") or DEFAULT
    return resolve(load_raw(spec), spec)


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


_USAGE = "usage: themes.py [NAME|PATH] | --list | --help"


def main(argv: list[str]) -> int:
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
        print(f"themes.py: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(theme, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
