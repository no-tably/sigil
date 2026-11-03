#!/usr/bin/env python3
"""Pin cure at a commit: the person's tool (round 11; round 12: through the store).

    python3 sigil/vendor/sync_cure.py REV [--from SOURCE] [--store DIR]

1. Installs cure's `cure/` at REV into the shared store with cure's own store
   (`supply/store.py` here, a verbatim copy of cure/supply/store.py): SOURCE is
   cure's git URL (REV then a full 40-hex sha) or a local cure repository (any
   commit-ish; it must have an origin URL, which VENDORED records). SOURCE
   defaults to the current lock's `source`; DIR to $CURE_STORE, else
   ~/.local/share/cure.
2. Copies cure's supply files at that commit (`cure/supply/{__init__,loader,
   store}.py`) over `supply/` here, byte for byte, so sigil loads with the loader
   of the cure it pins.
3. Writes `cure.lock` in cure's lock format (`commit:` and `source:` lines), and
   `cure.systems.json`: the commit, and the full module path, interface hash and
   body hash of each cure system in SYSTEMS, from cure's own export at that commit
   (`.construct/export/manifest.json`). A re-pin shows, in that file's diff, which
   contracts sigil stands on moved; the goldens decide whether sigil takes it.

SYSTEMS covers every cure system Present imports from (the deepest system whose
full path is the imported module or a prefix of it, and where each imported name
is defined; tests/test_vendor.py checks it), plus Supply, whose loader sigil
copies. Stdlib only; writes the store and files under `sigil/vendor/` only. Sigil
pins one cure commit per release.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

if __package__:
    from .supply import loader, store
else:                       # run as a script: `supply` beside this file
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from supply import loader, store

#: The cure systems sigil stands on, sorted: Text (cell widths, cut, wrap), Style
#: (colours, SGR), Buffer (the Wire frames), Geometry (Rect), Canvas (strokes), Memo
#: (frame plans), Theme (the YAML grammar), Layout (viewport), Term, Input, Clock and
#: Files (the live view), the packages they sit in (Core, Draw, Interact, Edge),
#: whose `__init__` re-exports a name may come through, and Supply (the loader).
SYSTEMS = ("Buffer", "Canvas", "Clock", "Core", "Draw", "Edge", "Files", "Geometry",
           "Input", "Interact", "Layout", "Memo", "Style", "Supply", "Term", "Text", "Theme")

HERE = Path(__file__).resolve().parent
LOCK = HERE / "cure.lock"
SYSTEMS_FILE = HERE / "cure.systems.json"
SUPPLY = HERE / "supply"
SUPPLY_FILES = ("__init__.py", "loader.py", "store.py")
MANIFEST = ".construct/export/manifest.json"
LOCK_HEAD = ("# cure, the terminal UI library Present draws with, at one commit (cure's lock\n"
             "# format). Written by sigil/vendor/sync_cure.py; never by hand.\n")


def full_paths(systems: dict) -> dict:
    """Each system's dotted module path: its manifest `path` under its parents'."""
    def path(name: str) -> str:
        entry = systems[name]
        parent = entry.get("parent")
        return entry["path"] if not parent else f"{path(parent)}.{entry['path']}"
    return {name: path(name) for name in systems}


def systems_of(sha: str, manifest: dict) -> dict:
    """cure.systems.json for SYSTEMS at a commit, from cure's manifest there."""
    systems = manifest["systems"]
    paths = full_paths(systems)
    return {"commit": sha,
            "paths": {n: paths[n] for n in SYSTEMS},
            "interfaces": {n: systems[n]["interface"] for n in SYSTEMS},
            "bodies": {n: systems[n]["body"] for n in SYSTEMS}}


def lock_text(lock: loader.Lock) -> str:
    """cure.lock's text: VENDORED's format, the commit and where it comes from."""
    return LOCK_HEAD + f"commit: {lock.commit}\n" + (f"source: {lock.source}\n" if lock.source else "")


def manifest_at(sha: str, source: str, root: Path) -> dict:
    """cure's export manifest at sha: from a local repository, or through the
    store's bare cache of a URL (fetched there by sha when the cache lacks it)."""
    if not store.is_url(source):
        return json.loads(store.git("-C", source, "show", f"{sha}:{MANIFEST}"))
    repo = store.cache(root)
    try:
        return json.loads(store.git("-C", repo, "show", f"{sha}:{MANIFEST}"))
    except store.StoreError:
        store.git("-C", repo, "fetch", "-q", "--depth", "1", source, sha)
        return json.loads(store.git("-C", repo, "show", f"{sha}:{MANIFEST}"))


def sync(rev: str, source: str | None = None, root: Path | None = None) -> dict:
    """Install cure at rev into the store, copy its supply files here, write the
    lock and the systems file; return the systems file's data."""
    source = source or loader.read_lock(LOCK).source
    if not source:
        raise ValueError(f"{LOCK} names no source: pass --from <cure's URL or repository>")
    root = store.root_of(root, None)
    tree = store.install(rev, source=source, store=root) / "cure"
    pinned = loader.read_lock(tree / "VENDORED")       # commit + the origin URL recorded
    data = systems_of(pinned.commit, manifest_at(pinned.commit, source, root))
    for name in SUPPLY_FILES:
        shutil.copyfile(tree / "supply" / name, SUPPLY / name)
    LOCK.write_text(lock_text(loader.Lock(pinned.commit, pinned.source)), encoding="utf-8")
    SYSTEMS_FILE.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return data


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="sync_cure.py", description=__doc__.strip().splitlines()[0])
    ap.add_argument("rev", help="the cure commit to pin (a full sha when SOURCE is a URL)")
    ap.add_argument("--from", dest="source", help="cure's URL or a local cure repository "
                                                  "(default: the lock's source)")
    ap.add_argument("--store", type=Path, help="the store folder (default: $CURE_STORE, "
                                               "else ~/.local/share/cure)")
    args = ap.parse_args(argv)
    try:
        data = sync(args.rev, args.source, args.store)
    except (ValueError, ImportError, store.StoreError, OSError) as error:
        print(f"sync_cure.py: {error}", file=sys.stderr)
        return 1
    print(json.dumps(data, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
