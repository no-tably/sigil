"""vendor: the libraries sigil stands on, each at a pinned commit (round 11, round 12).

One today: cure, the shared terminal UI library. The repository keeps only the lock,
`cure.lock` (cure's lock format: `commit: <40 hex>` and `source: <URL>`), and
`supply/`, verbatim copies of cure's own loader and store (cure/supply/; a test keeps
them byte-identical to cure's at the lock's commit). The tree itself comes from:

  - `vendor/cure` beside this file, when a plugin archive carries it (build.py puts
    it there with cure's `store.py bundle`), else
  - the shared store, `$CURE_STORE/<commit>/cure` (default ~/.local/share/cure),
    which cure's store installs (`sync_cure.py`, or CI); sigil never fetches.

A tree there whose VENDORED names another commit is refused (cure's CureMismatch,
never passed over); none at all is cure's CureNotFound, naming the install command.
Both are ImportErrors, raised on `import sigil.vendor`.

cure imports itself absolutely (`from cure.core ...`), so loading puts the folder
that holds `cure/` on `sys.path` once, here: `import sigil.vendor` before `import
cure`. Only Present imports it (sigil/present/__init__.py does, so every drawing
module may then `import cure...`); sigil's other layers never do (tests/test_spine.py).
cure reads no files and starts no process of its own on import.
"""

from pathlib import Path

from .supply import loader

HERE = Path(__file__).resolve().parent
LOCK = HERE / "cure.lock"
#: Where sigil's copy of cure's store sits (the install command a person runs).
STORE_TOOL = "sigil/vendor/supply/store.py"

try:
    #: The folder holding the `cure/` this process draws with (on sys.path).
    FOLDER = loader.load(LOCK, vendor=HERE)
except loader.CureNotFound as exc:
    raise loader.CureNotFound(f"{exc} (in sigil, cure's store.py is {STORE_TOOL}; "
                              "sigil/vendor/sync_cure.py installs and pins a new commit)") from None
