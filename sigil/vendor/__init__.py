"""vendor: the libraries sigil carries, each at a pinned commit (round 11).

One today: cure, the shared terminal UI library, in `cure/`, at the commit its
`cure/VENDORED` file and `cure.lock` name. cure's own sync tool writes `cure/`
(`sync_cure.py` here runs it and writes the lock); nothing edits it by hand.

cure imports itself absolutely (`from cure.core ...`), so this folder goes on
`sys.path` once, here: `import sigil.vendor` before `import cure`. Only Present
imports it (sigil/present/__init__.py does, so every drawing module may then
`import cure...`); sigil's other layers never do (tests/test_spine.py).
cure reads no files and starts no process of its own on import.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_PATH = str(HERE)
if _PATH not in sys.path:
    sys.path.insert(0, _PATH)
