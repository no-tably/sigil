"""[Themes]: find and read theme files on a search path and env names the app passes in;
unreadable or absent: a named miss returned, the caller falls back (Files never imports
Theme).

Kind: service (two data classes, pure helpers, and functions that touch the disk).

What it does: finds theme files by NAME on the directories the app gives, and reads
them as TEXT, bounded in size. It never parses a theme ([Theme] does, from the text)
and holds no theme of its own: a theme that is unreadable or absent (and every other
failure) is a named {FileError} returned to the caller, and the fallback is the
caller's (the spec's `(Sigil) -> [Files] : read … @fallback(builtin)`: the app falls
back to its built-in theme, e.g. Theme's `builtin()`). Files never imports Theme and
never falls back by itself (README decision 3). No process-wide
state: the search path, the environment and the size limit are arguments; nothing
reads `os.environ` or the working directory by itself (a relative directory is
relative to the process's working directory, as the OS resolves it).

The search path (`search(dirs, env=None, var=None) -> tuple[Path, ...]`, pure): the
`dirs` as given (each a `str` or `Path`, made a `Path`, in order), then, when `env`
(a mapping, e.g. the app's `os.environ`) and `var` (an env name, e.g.
`"SIGIL_THEME_PATH"`) are both given, each non-empty entry of `env.get(var, "")`
split on `os.pathsep`. No `~` expansion, no de-duplication.

The chosen name (`chosen(env, var, default) -> str`, pure): `env[var]` when `env` is
not None, `var` is a key of it and its value is non-empty; else `default`.

Names. A theme name is one segment `[A-Za-z0-9_-]+` (`NAME`): no dot, no slash, so a
name can never reach outside the search path. The file for a name in a directory is
`<dir>/<name>.yaml`, else `<dir>/<name>.yml` (`EXTENSIONS`, in that order).

Finding (`find(name, path) -> Path | FileError`): a name that is not a `NAME` is
`FileError("bad_name", name, ...)`. Otherwise, for each directory of `path` in order
and each extension in order, the candidate is `Path(dir) / (name + ext)`; the first
for which `os.stat(candidate)` succeeds and is a regular file (`stat.S_ISREG`;
symlinks followed) is returned. A failing `os.stat` (any `OSError`) skips the
candidate. None found: `FileError("missing", name, "not on the search path: " +
", ".join(str(d) for d in path))` (`"not on the search path: (empty)"` for an empty
path).

Listing (`names(path) -> tuple[str, ...]`): for each directory in order,
`os.scandir(dir)` (a directory that cannot be listed, any `OSError`, is skipped);
its entries sorted by name; an entry counts when its name is `stem + ext` with `ext`
in `EXTENSIONS`, `stem` a `NAME`, and `entry.is_file()` (symlinks followed). The
first occurrence of each stem wins; the result is in that order.

Reading (`read(path, limit=LIMIT) -> str | FileError`), the `(Disk)` flow
`read({Path}) => {Text}`: exactly these OS calls, in order:

1. `fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)` (non-blocking, so
   a FIFO on the path never blocks the app's loop);
2. `os.fstat(fd)`: not a regular file is `FileError("not_file", ...)`; `st_size >
   limit` is `FileError("too_large", ...)`;
3. `os.read(fd, n)` repeated until it returns `b""` or more than `limit` bytes are
   held (a file that grew past the limit is `"too_large"` too);
4. `os.close(fd)`, always, once opened (whatever happened after).

The bytes are decoded as strict UTF-8 (a BOM is kept: Theme drops it); a decode
error is `FileError("not_text", ...)`. `FileNotFoundError` or `NotADirectoryError`
from `os.open` is `"missing"`; any other `OSError` (permission, I/O, a directory
`os.open` refuses) is `"unreadable"`. The text is returned as decoded (no newline
change). No exception escapes for a failure of the disk.

Shelving (`shelf(path, limit=LIMIT) -> Shelf`): every theme on the path, for
Theme's `load(name, texts)` (which resolves `extends` among them, and only them):
for each name of `names(path)` in order, `p = find(name, path)` then `read(p,
limit)`; a text goes in `texts[name]`, a FileError in `errors` (in order). One bad
file never hides the others. (Every op takes `tuple(path)` once, so a generator
serves.)

No time bound (README decision 3; the spec's `# accepts: unguarded-call` on
`(Disk)`): Files' reads and stats carry no `@timeout`. Every call is a fixed number of
syscalls on a local path (the open is non-blocking, so a FIFO never blocks; the read is
bounded in SIZE by `limit`), but nothing bounds their TIME: the stdlib has no bound on
a stat of a hung mount, and a thread to fake one would be a loop of cure's own, so a
hung network mount can block a call. No timer, thread or signal is used.

Data (frozen dataclasses):
- `FileError(kind: str, path: str, detail: str = "")`: `kind` one of `KINDS`
  (`"bad_name"`, `"missing"`, `"not_file"`, `"too_large"`, `"unreadable"`,
  `"not_text"`); `path` the path (or the name, for `bad_name` / a `find` miss) as a
  `str`; `detail` a human-readable reason (the OS error's `strerror`, the size, ...;
  tests compare `kind` and `path`, never `detail`). It is a value, never raised.
- `Shelf(texts: dict[str, str] = {}, errors: tuple[FileError, ...] = ())`.

Inputs: `search`: an iterable of `str | Path`, an optional `Mapping[str, str]`, an
  optional `str`. `chosen`: a mapping or None, a `str`, a `str`. `find`: `name: str`, an
  iterable of `str | Path`. `names`: the same iterable. `read`: `str | Path`, `limit:
  int >= 0`. `shelf`: an iterable of `str | Path`, `limit`.
Outputs: `search`: a tuple of `Path`. `chosen`: a `str`. `find`: a `Path` or a
  {FileError}. `names`: a tuple of `str`. `read`: a `str` or a {FileError}. `shelf`: a
  {Shelf}.
Errors: failures of the disk are {FileError} values, never raised. A caller's
  mistake raises: `TypeError` when `name` is not a `str`, `limit` not an `int` (a
  `bool` included) or `path` not a `str` / `os.PathLike`; `ValueError` when `limit`
  is negative.
Effects: `find`: `os.stat` per candidate. `names`: `os.scandir` per directory and
  `DirEntry.is_file()` per entry. `read`: `os.open`, `os.fstat`, `os.read`,
  `os.close`, as listed. `shelf`: those of `names`, `find` and `read`. `search`,
  `chosen`: none. Nothing writes.

Usage:
    import os
    from cure.edge.files.themes import search, chosen, find, read, shelf, FileError
    path = search(["/repo/themes"], os.environ, "SIGIL_THEME_PATH")
    name = chosen(os.environ, "SIGIL_THEME", "sigil")
    found = find(name, path)            # Path("/repo/themes/sigil.yaml"), or FileError("missing", "sigil", ...)
    text = read(found) if not isinstance(found, FileError) else found
    s = shelf(path)                     # Shelf({"sigil": "..."}, ())
    # then the CALLER: theme = cure.draw.theme.load(name, s.texts), and its built-in
    # theme (builtin()) on a FileError or a ThemeError; Files itself never imports Theme
"""

import os
import re
import stat
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

NAME = r"[A-Za-z0-9_-]+"
"""A theme name (a regex, full match): one segment, never a path."""

EXTENSIONS: tuple[str, ...] = (".yaml", ".yml")
"""Theme file extensions, in lookup order."""

LIMIT = 64 * 1024
"""The default size limit of a theme file, in bytes."""

KINDS: tuple[str, ...] = ("bad_name", "missing", "not_file", "too_large", "unreadable", "not_text")
"""The kinds of {FileError}."""


@dataclass(frozen=True)
class FileError:
    """{FileError}: a named failure returned to the app: `kind` (one of KINDS), `path`, `detail`."""

    kind: str
    path: str
    detail: str = ""


@dataclass(frozen=True)
class Shelf:
    """{Shelf}: the theme texts read from a search path, by name, and the failures."""

    texts: dict = field(default_factory=dict)
    errors: tuple = ()


def search(dirs: Iterable, env: "Mapping[str, str] | None" = None, var: "str | None" = None) -> tuple:
    """The search path: `dirs`, then the entries of `env[var]` split on os.pathsep."""
    path = tuple(Path(d) for d in dirs)
    if env is not None and var is not None:
        path += tuple(Path(p) for p in env.get(var, "").split(os.pathsep) if p)
    return path


def chosen(env: "Mapping[str, str] | None", var: str, default: str) -> str:
    """`env[var]` when set and non-empty, else `default`."""
    if env is not None and env.get(var):
        return env[var]
    return default


def find(name: str, path: Iterable) -> "Path | FileError":
    """The first `<dir>/<name>.yaml|.yml` that is a regular file, or a FileError."""
    if not isinstance(name, str):
        raise TypeError(f"name must be a str, got {type(name).__name__}")
    path = tuple(path)
    if not re.fullmatch(NAME, name):
        return FileError("bad_name", name, "a theme name is letters, digits, _ and - only")
    for d in path:
        for ext in EXTENSIONS:
            candidate = Path(d) / (name + ext)
            try:
                st = os.stat(candidate)
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                return candidate
    dirs = ", ".join(str(d) for d in path) or "(empty)"
    return FileError("missing", name, "not on the search path: " + dirs)


def names(path: Iterable) -> tuple:
    """The theme names on the path, first occurrence wins."""
    found = []
    for d in tuple(path):
        for stem in _stems(d):
            if stem not in found:
                found.append(stem)
    return tuple(found)


def read(path: "str | Path", limit: int = LIMIT) -> "str | FileError":
    """The file's text (strict UTF-8, at most `limit` bytes), or a FileError."""
    _check_limit(limit)
    if not isinstance(path, (str, os.PathLike)):
        raise TypeError(f"path must be a str or os.PathLike, got {type(path).__name__}")
    where = str(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    except (FileNotFoundError, NotADirectoryError) as e:
        return FileError("missing", where, e.strerror or "")
    except OSError as e:
        return FileError("unreadable", where, e.strerror or "")
    try:
        data = _read_fd(fd, where, limit)
    except OSError as e:
        return FileError("unreadable", where, e.strerror or "")
    finally:
        os.close(fd)
    if isinstance(data, FileError):
        return data
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        return FileError("not_text", where, str(e))


def shelf(path: Iterable, limit: int = LIMIT) -> Shelf:
    """Every theme on the path read: texts by name, and the failures."""
    _check_limit(limit)
    path = tuple(path)
    texts, errors = {}, []
    for name in names(path):
        found = find(name, path)
        got = found if isinstance(found, FileError) else read(found, limit)
        if isinstance(got, FileError):
            errors.append(got)
        else:
            texts[name] = got
    return Shelf(texts, tuple(errors))


_CHUNK = 64 * 1024


def _stems(d: object) -> list:
    """The theme stems in one directory, its entries sorted by name ([] when it cannot be listed)."""
    try:
        with os.scandir(d) as it:
            entries = sorted(it, key=lambda e: e.name)
    except OSError:
        return []
    stems = []
    for entry in entries:
        for ext in EXTENSIONS:
            stem = entry.name[:-len(ext)]
            if entry.name.endswith(ext) and re.fullmatch(NAME, stem) and _is_file(entry):
                stems.append(stem)
    return stems


def _is_file(entry: os.DirEntry) -> bool:
    try:
        return entry.is_file()
    except OSError:
        return False


def _read_fd(fd: int, where: str, limit: int) -> "bytes | FileError":
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        return FileError("not_file", where, "not a regular file")
    if st.st_size > limit:
        return FileError("too_large", where, f"{st.st_size} bytes, over the limit of {limit}")
    chunks, held = [], 0
    while held <= limit:
        chunk = os.read(fd, min(_CHUNK, limit + 1 - held))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        held += len(chunk)
    return FileError("too_large", where, f"grew past the limit of {limit} bytes")


def _check_limit(limit: object) -> None:
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise TypeError(f"limit must be an int, got {type(limit).__name__}")
    if limit < 0:
        raise ValueError(f"limit must be >= 0, got {limit}")
