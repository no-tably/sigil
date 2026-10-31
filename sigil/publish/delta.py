"""
The delta: an earlier export's manifest against the new one, pure (no files).
Every system sorts into one of STATUSES:

    added      in the new export only
    removed    in the old one only (its folder is deleted)
    rebuild    its body hash changed
    recheck    its body is unchanged, but a system it depends on changed its
               interface (its calls into that system need a second look), or
               one an enclosing system depends on, outside that enclosing
               system, did (its members make up the enclosing system, so they
               use what it depends on)
    unchanged  neither

`depends_on` is a system's own flows only; what a nested system inherits from
the systems enclosing it is read here, through the new manifest's `parent`
fields (an old manifest without them still compares). A recheck's `because`
lists the changed systems, its own dependencies first, then inherited ones;
`via` maps each inherited one to the nearest enclosing system it came through
(only when something is inherited). No hash reads any of this.

The top system renamed (the spec renamed, or another --name) is the same system
under its new key: `renamed` gives {from, to} (else null), and the top is
compared with its old entry, so a rename alone marks nothing.
A system whose folder is not the one the old export gave it (the top renamed:
the exporter keeps every other system's folder) has `moved` {from, to}.

delta(old, new) is delta.json's content; manifest_problem says why a parsed
manifest.json is none an export wrote; dropped_folders, delta_lines and
delta_note are what the exporter deletes and prints.
"""

from __future__ import annotations

import re
from typing import Optional


EXPORT_VERSION = 1                          # manifest.json's "sigil_export"
DELTA = "delta.json"
DELTA_VERSION = 1
STATUSES = ("added", "removed", "rebuild", "recheck", "unchanged")

_FOLDER_RE = re.compile(r"[a-z0-9][a-z0-9-]*")


def manifest_problem(obj) -> Optional[str]:
    """Why `obj` (a parsed manifest.json) is no manifest `sigil export` wrote
    (None: it is one). Folder names must be slugs, so a delta never deletes
    anything outside the export."""
    if not isinstance(obj, dict) or obj.get("sigil_export") != EXPORT_VERSION:
        return f"not a version {EXPORT_VERSION} export manifest"
    systems = obj.get("systems")
    if not isinstance(systems, dict):
        return "no systems"
    for key, e in systems.items():
        if not (isinstance(e, dict)
                and all(isinstance(e.get(f), str) for f in ("path", "interface", "body"))
                and isinstance(e.get("depends_on"), list)
                and isinstance(e.get("components"), list)
                and all(isinstance(c, str) for c in e["components"])):
            return f"system {key!r} lacks path, interface, body, components or depends_on"
        if e.get("parent") is not None and not isinstance(e["parent"], str):
            return f"system {key!r} has a parent that is no system key"
        if not _FOLDER_RE.fullmatch(e["path"]):
            return f"system {key!r} has folder {e['path']!r}, no slug"
    folders = [e["path"] for e in systems.values()]
    for path in sorted({p for p in folders if folders.count(p) > 1}):
        return f"two systems share folder {path!r}"   # a delete would reach the other's files
    return None


def delta(old: Optional[dict], new: dict) -> dict:
    """What changed from the manifest `old` (None: a first export, so every system
    is added) to the manifest `new`: a list per status and, per system, its status
    with its old and new hashes."""
    olds, news = (old or {}).get("systems", {}), new["systems"]
    moved = top_renamed(old, new)
    if moved:
        olds = {(moved["to"] if k == moved["from"] else k): e for k, e in olds.items()}
    systems = {k: with_move(system_delta(k, olds, news), olds.get(k), news[k])
               for k in news}
    systems.update({k: {"status": "removed", "old": hashes(olds[k]), "new": None}
                    for k in sorted(olds) if k not in news})
    out = {"sigil_delta": DELTA_VERSION, "spec": new["spec"],
           "from": old.get("spec_hash") if old else None, "to": new["spec_hash"],
           "renamed": moved}
    for status in STATUSES:
        out[status] = [k for k, d in systems.items() if d["status"] == status]
    out["systems"] = systems
    return out


def with_move(d: dict, old: Optional[dict], new: dict) -> dict:
    """d with `moved` {from, to} when the system's folder is not the one the old
    export gave it (only the top renamed moves one: exporter.folder_names)."""
    if old is not None and old.get("path") != new.get("path"):
        d["moved"] = {"from": old.get("path"), "to": new.get("path")}
    return d


def top_key(manifest: dict) -> Optional[str]:
    """The top system's key: the manifest's `top`, or (an export before 0.6.1)
    its first system, which the exporter always writes first."""
    return manifest.get("top") or next(iter(manifest.get("systems", {})), None)


def top_renamed(old: Optional[dict], new: dict) -> Optional[dict]:
    """{from, to} when the top system's key moved and neither key names another
    system of the other export (None: no rename)."""
    if not old:
        return None
    was, now = top_key(old), top_key(new)
    if was is None or now is None or was == now or was in new["systems"] or now in old.get("systems", {}):
        return None
    return {"from": was, "to": now}


def system_delta(key: str, olds: dict, news: dict) -> dict:
    """One system of the new export against the old: added, rebuild (its body
    changed), recheck or unchanged. A recheck's `because` names the changed
    systems it depends on, then those it inherits (inherited_changes); `via`
    maps each inherited one to the enclosing system it came through."""
    old, new = olds.get(key), news[key]
    entry = {"old": hashes(old), "new": hashes(new)}
    if old is None:
        return {"status": "added", **entry}
    if old["body"] != new["body"]:
        return {"status": "rebuild", **entry}
    because = [d for d in new["depends_on"] if interface_changed(d, olds, news)]
    via = {d: up for d, up in inherited_changes(key, olds, news).items()
           if d not in because}
    if because or via:
        return {"status": "recheck", **entry, "because": because + list(via),
                **({"via": via} if via else {})}
    return {"status": "unchanged", **entry}


def inherited_changes(key: str, olds: dict, news: dict) -> dict:
    """{changed system: the nearest enclosing system it came through} for system
    `key`: each system an enclosing system of `key` (its parent, its parent's
    parent, …, read from the new manifest's `parent`) depends on, outside that
    enclosing system, whose interface changed. Nearest enclosing system first,
    each in its `depends_on` order."""
    out = {}
    for up in enclosing(key, news):
        for d in news[up]["depends_on"]:
            if d not in out and d != key and not within(d, up, news) \
                    and interface_changed(d, olds, news):
                out[d] = up
    return out


def enclosing(key: str, news: dict) -> list:
    """The systems enclosing `key`, nearest first (its parent, …): none when the
    manifest has no `parent` fields (an export before 0.6.5)."""
    out, k = [], news.get(key, {}).get("parent")
    while k in news and k != key and k not in out:
        out.append(k)
        k = news[k].get("parent")
    return out


def within(key: str, up: str, news: dict) -> bool:
    """Whether system `key` is `up` or nested (at any depth) under it."""
    return key == up or up in enclosing(key, news)


def interface_changed(key: str, olds: dict, news: dict) -> bool:
    """Whether system `key` (in the new export) has an interface the old export
    did not (a system new to it counts as changed)."""
    old = olds.get(key)
    return old is None or old["interface"] != news[key]["interface"]


def hashes(entry: Optional[dict]) -> Optional[dict]:
    return None if entry is None else {"interface": entry["interface"], "body": entry["body"]}


def dropped_folders(old: Optional[dict], new: dict) -> list:
    """The folders of the old export no system of the new one uses (removed
    systems, and systems whose folder name moved)."""
    if not old:
        return []
    keep = {e["path"] for e in new["systems"].values()}
    return sorted({e["path"] for e in old["systems"].values()} - keep)


def delta_lines(change: dict) -> list:
    """The delta in words: a count line, then a line per status that has systems."""
    if change["from"] is None:
        return [f"first export: {len(change['added'])} system(s) added"]
    counts = ", ".join(f"{len(change[s])} {s}" for s in STATUSES if change[s])
    out = [f"since spec {change['from']}: {counts or 'no systems'}"]
    if change.get("renamed"):
        out.append(f"  {'renamed':<9}  {change['renamed']['from']} → {change['renamed']['to']}")
    for status in STATUSES[:-1]:
        for key in change[status]:
            out.append(f"  {status:<9}  {key}{delta_note(change['systems'][key])}")
    for key, d in change["systems"].items():
        if d.get("moved"):
            out.append(f"  {'moved':<9}  {key}: {d['moved']['from']}/ → {d['moved']['to']}/")
    if change["unchanged"]:
        out.append(f"  {'unchanged':<9}  {', '.join(change['unchanged'])}")
    return out


def delta_note(d: dict) -> str:
    """What a status line adds: a rebuild's body hashes, what a recheck depends on
    (an inherited one with the enclosing system it came through)."""
    if d["status"] == "rebuild":
        return f" (body {d['old']['body']} → {d['new']['body']})"
    if d["status"] == "recheck":
        via = d.get("via", {})
        named = (f"{k} (via {via[k]})" if k in via else k for k in d["because"])
        return f" (interface changed: {', '.join(named)})"
    return ""
