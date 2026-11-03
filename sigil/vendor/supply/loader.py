"""[Loader]: finds the tree a lock names and loads it; never touches the network.

Kind: service (stdlib only; imports nothing of cure, so a consumer copies this file
verbatim and loads it by its path before any `import cure`). It reads (Disk) and nothing
else: no git, no socket, no URL.

Data:
- The lock format, shared with VENDORED: UTF-8 text, one `key: value` per line; a blank
  line or one starting with `#` is skipped; unknown keys are kept (and ignored here);
  keys are case-sensitive. `commit` is required (40 lowercase hex digits), `source`
  optional (the URL to fetch from). VENDORED also has `date`, so a VENDORED file is
  itself a valid lock.
- `Lock(commit, source)`: a frozen dataclass, `source` a URL or `None`.

The operations:
- `read_lock(path) -> Lock`, or `LockError` (a `ValueError`) naming the path: the file
  is missing (chained from the `OSError`), a line has no `": "`, `commit` is missing or
  not 40 lowercase hex, or a key is repeated.
- `store_root(env=None) -> Path`: `env["CURE_STORE"]` when set, non-empty and absolute
  (a relative one is a `ValueError`), else `~/.local/share/cure` with `HOME` from `env`.
  `env` is a mapping; `None` means `os.environ`.
- `find(lock, *, vendor=None, env=None) -> Path` (`[Loader] -> (Disk) : find`): the folder
  that holds `cure/`, the one that goes on `sys.path`. `lock` is a `Lock` or a path to
  one. First `<vendor>/cure/VENDORED` (when `vendor` is given and it exists), then
  `<store_root>/<commit>/cure/VENDORED`. A tree there naming another commit is a
  `CureMismatch` (an `ImportError`) naming both commits: never passed over for the next
  place. Neither there: `CureNotFound` (an `ImportError`) naming the commit, every place
  looked and the fetch to run, `python3 cure/supply/store.py install <commit> --from
  <source>`.
- `load(lock, *, vendor=None, env=None) -> Path` (`(Sigil) -> [Loader] : load`, and the
  same from (Construct)): `find`, then the folder at `sys.path[0]` (never twice). A
  `cure` already in `sys.modules` from another folder is a `CureMismatch` naming both
  folders; one from the same folder makes the call do nothing. It imports nothing
  itself: the app's own `import cure` then takes the tree.

Invariant: one_commit: the tree a loader returns has the lock's commit in its VENDORED;
otherwise nothing is returned (an error is raised).

Usage (a consumer, with its verbatim copy of this file, before any `import cure`):
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location("cure_loader", "path/to/loader.py")
    loader = importlib.util.module_from_spec(spec)
    sys.modules["cure_loader"] = loader
    spec.loader.exec_module(loader)
    loader.load("cure.lock", vendor="vendor")
    import cure
"""

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}")
FETCH = "python3 cure/supply/store.py install {commit} --from {source}"
NO_SOURCE = "<cure's origin URL>"


class LockError(ValueError):
    """A lock (or VENDORED) file that cannot be read as one; the message names it."""


class CureMismatch(ImportError):
    """A tree at another commit than the lock's, or cure already loaded from elsewhere."""


class CureNotFound(ImportError):
    """The lock's commit is in none of the places looked; the message says what to fetch."""


@dataclass(frozen=True)
class Lock:
    commit: str
    source: str | None = None


def read_fields(path) -> dict:
    """A lock or VENDORED file's `key: value` lines, or LockError naming the file."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise LockError(f"{path}: cannot read the lock: {error}") from error
    out = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        key, sep, value = line.partition(": ")
        if not sep:
            raise LockError(f"{path}:{number}: not a `key: value` line: {line!r}")
        if key in out:
            raise LockError(f"{path}:{number}: {key!r} repeated")
        out[key] = value
    return out


def read_lock(path) -> Lock:
    fields = read_fields(path)
    commit = fields.get("commit")
    if commit is None:
        raise LockError(f"{path}: no `commit: <sha>` line")
    if not SHA.fullmatch(commit):
        raise LockError(f"{path}: commit {commit!r} is not 40 lowercase hex digits")
    return Lock(commit, fields.get("source"))


def store_root(env=None) -> Path:
    env = os.environ if env is None else env
    root = env.get("CURE_STORE") or ""
    if root:
        if not Path(root).is_absolute():
            raise ValueError(f"CURE_STORE must be an absolute path, not {root!r}")
        return Path(root)
    home = env.get("HOME") or str(Path.home())
    return Path(home) / ".local" / "share" / "cure"


def _holds(folder: Path, commit: str) -> bool:
    """Whether folder/cure/VENDORED exists and names `commit`; CureMismatch when it names
    another (one_commit: such a tree is never passed over)."""
    note = folder / "cure" / "VENDORED"
    if not note.is_file():
        return False
    found = read_lock(note).commit
    if found != commit:
        raise CureMismatch(f"{folder / 'cure'} is cure at {found}, not the lock's {commit}")
    return True


def find(lock, *, vendor=None, env=None) -> Path:
    lock = lock if isinstance(lock, Lock) else read_lock(lock)
    places = [Path(vendor)] if vendor is not None else []
    places.append(store_root(env) / lock.commit)
    for folder in places:
        if _holds(folder, lock.commit):
            return folder
    looked = ", ".join(str(folder / "cure") for folder in places)
    fetch = FETCH.format(commit=lock.commit, source=lock.source or NO_SOURCE)
    raise CureNotFound(f"cure {lock.commit} not found (looked in {looked}); fetch it with: {fetch}")


def load(lock, *, vendor=None, env=None) -> Path:
    folder = find(lock, vendor=vendor, env=env)
    loaded = sys.modules.get("cure")
    if loaded is not None:
        file = getattr(loaded, "__file__", None)
        have = Path(file).parent.parent if file else None
        if have is None or have.resolve() != folder.resolve():
            raise CureMismatch(f"cure is already loaded from {have or 'no file'}, not {folder}")
        return folder
    entry = str(folder)
    if sys.path[:1] != [entry]:
        while entry in sys.path:
            sys.path.remove(entry)
        sys.path.insert(0, entry)
    return folder
