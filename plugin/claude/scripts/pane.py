#!/usr/bin/env python3
"""
pane.py — the Claude Code mod's Python half: `sigil frames` under its old name.

    pane.py draw FILE [--view …] …     = sigil frames draw FILE [--view …] …
    pane.py follow CONTROL             = sigil frames follow CONTROL

The drawing lives in sigil.present.frames, the split's loop in sigil.cli; this
file only finds the package (beside it in the plugin, two directories up in the
repo) until the mod calls `sigil frames` itself.
"""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE if (_HERE / "sigil").is_dir() else _HERE.parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sigil import cli  # noqa: E402  (after the path is set)

if __name__ == "__main__":
    sys.exit(cli.main(["frames", *sys.argv[1:]]))
