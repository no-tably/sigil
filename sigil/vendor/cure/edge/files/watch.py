"""[Watch]: a file's stamp; mid-save rename: the last one.

Kind: service (a data class and functions that stat the disk).

What it does: tells the app whether a file changed since it last looked, so it can
redraw on save (sigil's `ViewState.reload`, generic part). There is no loop, thread or
notifier here: the app asks when it likes (each frame, or on a timer of its own
`Clock`) and passes in the stamp it got last time; the clock is the app's.

A {Stamp} is what `os.stat(path)` says of the file now: `Stamp(st.st_mtime_ns,
st.st_size, st.st_ino, st.st_dev)`. Two stamps are equal when all four are, so a save
that keeps the mtime but changes the size, or an editor's atomic save (write a new
file, rename it over: a new inode), is a change.

Stat (`stat(path) -> Stamp | FileError`), the `(Disk)` flow `stat({Path}) =>
{Stamp}`: one `os.stat(path)` (symlinks followed). `FileNotFoundError` or
`NotADirectoryError` is `FileError("missing", str(path), ...)`; any other `OSError` is
`FileError("unreadable", str(path), ...)` ([Themes]' FileError). Any kind of file
gets a stamp (a directory too).

Watch (`watch(path, last=None) -> Stamp | None`), the boundary op: `stat(path)`;
a Stamp is returned; a FileError gives back `last` unchanged (`@fallback(last_stamp)`:
mid-save, between the old file's removal and the new one's rename, the file is
briefly missing, and that is not a change). So `last` is `None` until the file has
been seen once. The app's loop:

    stamp = watch(path, stamp_before)
    if changed(stamp_before, stamp):  reload; stamp_before = stamp

No time bound: the `os.stat` carries no `@timeout` (the spec's `# accepts:
unguarded-call` on `(Disk)`): the stdlib has no bound on a stat of a hung mount, and
a thread to fake one would be a loop of cure's own, so a stat of a hung network mount
blocks the call. `@fallback(last_stamp)` covers a stat that fails, not one that hangs.

Changed (`changed(last, now) -> bool`, pure): `now is not None and now != last`.
(A file seen for the first time is a change: `changed(None, stamp)` is True.)

Data (frozen dataclass):
- `Stamp(mtime_ns: int, size: int, ino: int, dev: int)`.

Inputs: `stat`, `watch`: `path: str | os.PathLike`; `watch`: `last` a {Stamp} or None.
  `changed`: two `Stamp | None`.
Outputs: `stat`: a {Stamp} or a {FileError}. `watch`: a {Stamp} or None. `changed`: a
  `bool`.
Errors: failures of the disk are values (`stat`) or the last stamp (`watch`), never
  raised. `TypeError` when `path` is not a `str` / `os.PathLike`, or `last` is neither
  a `Stamp` nor None.
Effects: `stat`, `watch`: exactly one `os.stat(path)` each. `changed`: none. Nothing
  writes; nothing is kept between calls.

Usage:
    from cure.edge.files.watch import watch, changed, stat
    seen = watch("design.sigil")          # Stamp(...) (None if it is not there)
    later = watch("design.sigil", seen)   # mid-save and missing: `seen` itself
    changed(seen, later)                  # False until the file really changes
"""

import os
from dataclasses import dataclass

from .themes import FileError


@dataclass(frozen=True)
class Stamp:
    """{Stamp}: a file's mtime (ns), size, inode and device, as os.stat gives them."""

    mtime_ns: int
    size: int
    ino: int
    dev: int


def stat(path: object) -> "Stamp | FileError":
    """The file's stamp now (one os.stat), or a FileError."""
    if not isinstance(path, (str, os.PathLike)):
        raise TypeError(f"path must be a str or os.PathLike, got {type(path).__name__}")
    try:
        st = os.stat(path)
    except (FileNotFoundError, NotADirectoryError) as e:
        return FileError("missing", str(path), e.strerror or "")
    except OSError as e:
        return FileError("unreadable", str(path), e.strerror or "")
    return Stamp(st.st_mtime_ns, st.st_size, st.st_ino, st.st_dev)


def watch(path: object, last: "Stamp | None" = None) -> "Stamp | None":
    """The file's stamp now; `last` when it cannot be stat'ed (mid-save)."""
    if last is not None and not isinstance(last, Stamp):
        raise TypeError(f"last must be a Stamp or None, got {type(last).__name__}")
    now = stat(path)
    return last if isinstance(now, FileError) else now


def changed(last: "Stamp | None", now: "Stamp | None") -> bool:
    """True when `now` is a stamp different from `last`."""
    return now is not None and now != last
