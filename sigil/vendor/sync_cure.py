#!/usr/bin/env python3
"""Vendor cure at a pinned commit: the person's sync tool (round 11).

    python3 sigil/vendor/sync_cure.py /path/to/cure [COMMIT]

Runs cure's own sync tool (`tools/sync.py` in the cure repository), which copies
the `cure/` package at COMMIT (default: its HEAD) exactly as committed (`git
archive`: no working-tree edit or cache file comes along) into
`sigil/vendor/cure/`, replacing what was there, and writes `cure/VENDORED` (the
commit, its date, the source). The source line is then made portable (the
repository's `origin` URL, else its folder name), since the folder ships in every
plugin archive.

Then writes `sigil/vendor/cure.lock`: the commit, and the full module path, the
interface hash and the body hash of each cure system in SYSTEMS, read from cure's
own export at that commit (`.construct/export/manifest.json`). A re-sync shows,
in the lock's diff, which contracts sigil stands on moved; the goldens decide
whether sigil takes it.

SYSTEMS covers every cure system Present imports from: the deepest system whose
full path is the imported module or a prefix of it, and where each imported name
is defined (tests/test_vendor.py checks it). Stdlib only; writes only under
`sigil/vendor/`. Sigil pins one cure commit per release.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

#: The cure systems Present stands on, sorted: Text (cell widths, cut, wrap), Style
#: (colours, SGR), Buffer (the Wire frames), Geometry (Rect), Canvas (strokes), Memo
#: (frame plans), Theme (the YAML parser), Layout (viewport), Term, Input, Clock and
#: Files (the live view), and the packages they sit in (Core, Draw, Interact, Edge),
#: whose `__init__` re-exports a name may come through.
SYSTEMS = ("Buffer", "Canvas", "Clock", "Core", "Draw", "Edge", "Files", "Geometry",
           "Input", "Interact", "Layout", "Memo", "Style", "Term", "Text", "Theme")

HERE = Path(__file__).resolve().parent
LOCK = HERE / "cure.lock"
MANIFEST = ".construct/export/manifest.json"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(("git", "-C", str(repo), *args), check=True,
                          capture_output=True, text=True).stdout.strip()


def full_paths(systems: dict) -> dict:
    """Each system's dotted module path: its manifest `path` under its parents'."""
    def path(name: str) -> str:
        entry = systems[name]
        parent = entry.get("parent")
        return entry["path"] if not parent else f"{path(parent)}.{entry['path']}"
    return {name: path(name) for name in systems}


def lock_of(sha: str, manifest: dict) -> dict:
    """The lock for SYSTEMS at a commit, from cure's manifest there."""
    systems = manifest["systems"]
    paths = full_paths(systems)
    return {"repo": "cure", "commit": sha,
            "paths": {n: paths[n] for n in SYSTEMS},
            "interfaces": {n: systems[n]["interface"] for n in SYSTEMS},
            "bodies": {n: systems[n]["body"] for n in SYSTEMS}}


def portable_source(repo: Path) -> str:
    """Where cure comes from, without this machine's paths: origin's URL, else
    the repository folder's name."""
    try:
        url = _git(repo, "remote", "get-url", "origin")
    except subprocess.CalledProcessError:
        url = ""
    return url or repo.resolve().name


def portable_note(vendored: Path, source: str) -> None:
    """cure/VENDORED with its `source:` line replaced by `source`."""
    lines = vendored.read_text(encoding="utf-8").splitlines()
    vendored.write_text("".join((f"source: {source}" if ln.startswith("source:") else ln) + "\n"
                                for ln in lines), encoding="utf-8")


def sync(repo: Path, commit: str = "HEAD") -> dict:
    """Vendor cure/ at commit through cure's sync tool and write the lock; return it."""
    sha = _git(repo, "rev-parse", "--verify", f"{commit}^{{commit}}")
    manifest = json.loads(_git(repo, "show", f"{sha}:{MANIFEST}"))
    lock = lock_of(sha, manifest)
    subprocess.run((sys.executable, str(repo / "tools" / "sync.py"), str(HERE), "--commit", sha),
                   check=True)
    portable_note(HERE / "cure" / "VENDORED", portable_source(repo))
    LOCK.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return lock


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__.strip().splitlines()[2].strip())
    print(json.dumps(sync(Path(sys.argv[1]), *sys.argv[2:]), indent=2, sort_keys=True))
