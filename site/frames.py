"""
frames.py — the page's packed frames: sigil.present.frames (autoclose, Styles,
pack_rows) under the name build_site.py loads. The drawing and the packing live
in the package; this file only finds it (beside this file in _site/py/, one
directory up in the repo).
"""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE if (_HERE / "sigil").is_dir() else _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sigil.present.frames import Styles, autoclose, pack_rows  # noqa: E402,F401
