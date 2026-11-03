"""[Files]: find and read themes, watch a file.

Kind: system (the expansion of [Files] in Edge); it touches the OS (the `(Disk)`
actor: no module stands for it; its flows are [Themes]' `read` and [Watch]'s `stat`).
Depends on nothing: no module of this package imports any other cure package (it
reads theme TEXT; Theme parses it). No process-wide state, no loop, no thread, no
timer: the search path, the environment, the limits and the last stamp are
arguments, and the app decides when to ask.

Failures are named values returned to the app, never exceptions escaping: a
{FileError} (`kind` one of `KINDS`: `bad_name`, `missing`, `not_file`, `too_large`,
`unreadable`, `not_text`) from [Themes], and the last stamp from [Watch]'s `watch`
(`@fallback(last_stamp)`). A theme that cannot be found or read is a named miss (a
FileError) returned; its fallback (`(Sigil) -> [Files] : read … @fallback(builtin)`)
is the caller's: the app falls back to its built-in theme (Theme's `builtin()`), so
Files never imports Theme (README decision 3).

No time bound: Files' reads and stats carry no `@timeout`. The stdlib has no bound
on a stat of a hung mount, and a thread to fake one would be a loop of cure's own;
the spec acknowledges this on `(Disk)` (`# accepts: unguarded-call`). So a hung
network mount can block a call; nothing here arms a timer.

The boundary (the op other systems call), defined in [Watch] and re-exported here:

- `watch(path, last=None) -> Stamp | None` ({Path} => {Stamp}, for the app, e.g.
  sigil's redraw on save): one `os.stat(path)`; the file's {Stamp} now, or `last`
  when it cannot be stat'ed (a mid-save rename). `changed(last, now)` says whether to
  reload. See [Watch].

Re-exported for consumers: `Stamp`, `stat`, `watch`, `changed` (watch); `FileError`,
`Shelf`, `KINDS`, `NAME`, `EXTENSIONS`, `LIMIT`, `search`, `chosen`, `find`,
`names`, `read`, `shelf` (themes).

Note: the function `watch` shadows the submodule of the same name as a package
attribute; reach the submodule's own names with a from-import of its dotted path
(`from cure.edge.files.watch import Stamp`).

Inputs, outputs and errors: as each module states.
Effects: only `os.stat`, `os.scandir` (with `DirEntry.is_file`), `os.open`, `os.fstat`,
`os.read` and `os.close`, exactly as [Themes] and [Watch] list them; nothing writes.

Usage:
    import os
    from cure.edge.files import search, chosen, shelf, watch, changed
    path = search(["/repo/themes"], os.environ, "SIGIL_THEME_PATH")
    texts = shelf(path).texts                     # {"sigil": "...", ...}
    name = chosen(os.environ, "SIGIL_THEME", "sigil")
    stamp = watch("design.sigil")
    # later, each frame:
    now = watch("design.sigil", stamp)
    if changed(stamp, now):
        stamp = now                               # ... and reload
"""

from .themes import (EXTENSIONS, KINDS, LIMIT, NAME, FileError, Shelf, chosen, find, names, read,
                     search, shelf)
from .watch import Stamp, changed, stat, watch
