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
`sigil themes` itself loads no dialect. Standard library and the vendored cure.

The grammar is cure's (cure.draw.theme.parse, the one theme reader sigil and
construct share; its docstring is the contract, and the site's JavaScript parser
follows the same rules): nested maps by space indentation, plain / "JSON-escaped" /
'single-quoted' scalars, # comments; keys are dot-joined segments of ASCII letters,
digits, _ and - (`a.b: x` is `a:` / `  b: x`); a plain value starting with # (a
colour YAML reads as a comment) or with a YAML indicator must be quoted; control
characters, lists, flow collections, tabs in the indent, duplicate keys and
inconsistent indentation are errors, each naming the file and line in cure's words.
Sigil reads cure's flat key paths back into nested maps, which adds two errors of
its own: maps nested more than MAX_DEPTH (16) deep, and a key path that is both a
value and a map (`list.item: x` beside `list.item.selected: y`). `extends` is
cure's overlay (a value replaces the map below it), followed by name or path here;
an `extends` chain of more than MAX_EXTENDS (16) themes is an error.
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
# The grammar: cure's, read back into nested maps
# ---------------------------------------------------------------------------

def _cure():
    """cure's theme reader, imported on first use (`sigil themes --list` and the
    commands that never colour do not load cure's draw package)."""
    import importlib
    return importlib.import_module("cure.draw.theme.parse")


def _read(text: str, source: str):
    """cure's Raw of a theme text: its flat key paths, values and lines."""
    reader = _cure()
    try:
        return reader.parse(text, source)
    except reader.ThemeError as exc:
        raise ThemeError(str(exc)) from None


def _tree(raw) -> dict:
    """A Raw's flat key paths as nested dicts of strings (sigil's theme tree)."""
    root: dict = {}
    for path, value in raw.leaves.items():
        source, line = raw.lines[path]
        if len(path) - 1 > MAX_DEPTH:
            raise ThemeError(f"{source}:{line}: maps nested more than {MAX_DEPTH} deep")
        node = root
        for k, key in enumerate(path):
            if isinstance(node.get(key), str) or (k == len(path) - 1 and key in node):
                dotted = ".".join(path[:k + 1])
                raise ThemeError(f"{source}:{line}: '{dotted}' is both a value and a map")
            if k == len(path) - 1:
                node[key] = value
            else:
                node = node.setdefault(key, {})
    return root


def parse(text: str, source: str = "<theme>") -> dict:
    """Parse a theme's text by cure's grammar (see the module docstring) into
    nested dicts of strings; `extends` stays a key here."""
    return _tree(_read(text, source))


# ---------------------------------------------------------------------------
# Resolution: $refs
# ---------------------------------------------------------------------------

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


def _chain(spec: str, seen: tuple[Path, ...], base: Path | None):
    """The Raw of a theme with its `extends` laid under it (cure's merge), the
    parent found by name or path (a path against this theme's folder)."""
    path = find(spec, base)
    key = path.resolve()
    if key in seen:
        raise ThemeError(f"{path}: extends cycle")
    if len(seen) >= MAX_EXTENDS:
        raise ThemeError(f"{path}: an extends chain longer than {MAX_EXTENDS} themes")
    try:
        with path.open("rb") as fh:
            data = fh.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ThemeError(f"{path}: larger than {MAX_BYTES} bytes; not a theme")
        text = data.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ThemeError(f"{path}: cannot read theme: {exc}") from None
    raw = _read(text, str(path))
    extends = [p for p in raw.leaves if p[0] == "extends"]
    if any(len(p) > 1 for p in extends):
        raise ThemeError(f"{path}: extends must be a theme name or path, not a map")
    parent = raw.leaves.get(("extends",), "")
    if extends:
        kept = {p: v for p, v in raw.leaves.items() if p[0] != "extends"}
        raw = type(raw)(raw.source, kept, {p: raw.lines[p] for p in kept})
    if parent:
        raw = _cure().merge(_chain(parent, seen + (key,), path.parent), raw)
    return raw


def load_raw(spec: str, _seen: tuple[Path, ...] = (), _base: Path | None = None) -> dict:
    """A theme with `extends` applied but $refs left in place."""
    return _tree(_chain(spec, _seen, _base))


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
