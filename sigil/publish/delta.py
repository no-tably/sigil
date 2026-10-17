"""
The delta: an earlier export's manifest against the new one, pure (no files).
Every system sorts into one of STATUSES:

    added      in the new export only
    removed    in the old one only (its folder is deleted)
    rebuild    its body hash changed
    recheck    its body is unchanged, but a system it depends on changed its
               interface (its calls into that system need a second look)
    unchanged  neither

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
        if not _FOLDER_RE.fullmatch(e["path"]):
            return f"system {key!r} has folder {e['path']!r}, no slug"
    return None


def delta(old: Optional[dict], new: dict) -> dict:
    """What changed from the manifest `old` (None: a first export, so every system
    is added) to the manifest `new`: a list per status and, per system, its status
    with its old and new hashes."""
    olds, news = (old or {}).get("systems", {}), new["systems"]
    systems = {k: system_delta(k, olds, news) for k in news}
    systems.update({k: {"status": "removed", "old": hashes(olds[k]), "new": None}
                    for k in sorted(olds) if k not in news})
    out = {"sigil_delta": DELTA_VERSION, "spec": new["spec"],
           "from": old.get("spec_hash") if old else None, "to": new["spec_hash"]}
    for status in STATUSES:
        out[status] = [k for k, d in systems.items() if d["status"] == status]
    out["systems"] = systems
    return out


def system_delta(key: str, olds: dict, news: dict) -> dict:
    """One system of the new export against the old: added, rebuild (its body
    changed), recheck (`because` names the systems it depends on whose interface
    changed) or unchanged."""
    old, new = olds.get(key), news[key]
    entry = {"old": hashes(old), "new": hashes(new)}
    if old is None:
        return {"status": "added", **entry}
    if old["body"] != new["body"]:
        return {"status": "rebuild", **entry}
    because = [d for d in new["depends_on"] if interface_changed(d, olds, news)]
    if because:
        return {"status": "recheck", **entry, "because": because}
    return {"status": "unchanged", **entry}


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
    for status in STATUSES[:-1]:
        for key in change[status]:
            out.append(f"  {status:<9}  {key}{delta_note(change['systems'][key])}")
    if change["unchanged"]:
        out.append(f"  {'unchanged':<9}  {', '.join(change['unchanged'])}")
    return out


def delta_note(d: dict) -> str:
    """What a status line adds: a rebuild's body hashes, what a recheck depends on."""
    if d["status"] == "rebuild":
        return f" (body {d['old']['body']} → {d['new']['body']})"
    if d["status"] == "recheck":
        return f" (interface changed: {', '.join(d['because'])})"
    return ""
