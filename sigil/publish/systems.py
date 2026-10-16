"""
The export model as it leaves sigil: the hashed model, its normalised JSON, the
folder slugs. The model itself — systems, homes, components, flows, what is
untyped — is sigil.model.systems (check's export rules read it too); this module
adds what export.py writes.

    model = build_model(text, stem="shop")
    model.systems["shop"].interface_hash, model.systems["shop"].body_hash
    to_json(model)          # the normalised, JSON-able form

HASHES

  sha256 of canonical JSON (sorted keys, compact separators), first 16 hex.
  interface_hash covers the system's boundary flows; body_hash everything in it
  (interface, members, internal flows, control blocks, descriptions). No line
  numbers, whitespace or order from the source enter either.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from typing import Iterable, Optional

from sigil.core import parse
from sigil.core.comments import read_acks, walk_layout
from sigil.core.statements import read_document
from sigil.model import systems
from sigil.model.systems import ARROW_MODE, Component, Flow, Model, System
from sigil.analyse.check import CORE_NAMES


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def build_model(text: str, stem: str, dialect=None) -> Model:
    """The model of a document, hashed: parsed, its acknowledgements read as
    check reads them."""
    lines = text.splitlines()
    walk = read_document(text, dialect)               # the one reading
    graph = parse.parse_document(text, dialect=dialect, walk=walk)
    comments = {k + 1: v for k, v in walk.comments.items()}
    acks = read_acks(comments, walk_layout(walk), frozenset(CORE_NAMES.values()))
    return model_of(graph, lines, stem, acks)


def model_of(graph, lines: list, stem: str, acks: Iterable = ()) -> Model:
    """sigil.model.systems.model_of with each system's interface and body hash."""
    m = systems.model_of(graph, lines, stem, acks)
    return replace(m, systems={k: with_hashes(s, m.components) for k, s in m.systems.items()})


# ---------------------------------------------------------------------------
# Normalised JSON and hashes
# ---------------------------------------------------------------------------

HASH_LEN = 16


def flow_json(f: Flow, components: dict, side: Optional[str] = None) -> dict:
    """A flow as JSON: `from` / `to` glyphs, or seen from component `side`:
    `dir` (out, in, self) and `peer`."""
    if side is None:
        ends = {"from": components[f.src].glyph, "to": components[f.dst].glyph}
    else:
        d = "self" if f.src == f.dst else "out" if f.src == side else "in"
        ends = {"dir": d, "peer": components[f.dst if d == "out" else f.src].glyph}
    return _compact({
        **ends, "arrow": f.arrow, "mode": ARROW_MODE.get(f.arrow, "flow"),
        "payload": f.payload, "text": f.text, "op": f.op, "returns": f.returns,
        "external": f.external, "mods": [list(m) for m in f.mods], "card": f.card,
        "implied": f.implied, "from_path": f.paths[0], "to_path": f.paths[1]})


def component_json(c: Component, components: dict) -> dict:
    lc = c.lifecycle
    return _compact({
        "name": c.name, "kind": c.kind, "glyph": c.glyph, "home": c.home,
        "also_in": sorted(s for s in c.systems if s != c.home),
        "description": list(c.description),
        "interface": _sorted([flow_json(f, components, c.id) for f in c.flows]),
        "requirements": _compact({
            "modifiers": [list(m) for m in c.modifiers],
            "access": [list(a) for a in c.access],
            "accepts": sorted(c.accepts)}) or None,
        "lifecycle": None if lc is None else {
            "states": list(lc.states), "initial": list(lc.initial),
            "terminal": list(lc.terminal),
            "transitions": [_compact({"from": a, "to": b, "on": on,
                                      "mods": [list(m) for m in mods]})
                            for a, b, on, mods in lc.transitions]}})


def system_json(s: System, components: dict) -> dict:
    """One system in its normalised, JSON-able form (what system.json holds)."""
    return _compact({
        "name": s.name, "kind": s.kind,
        "face": components[s.face].glyph if s.face in components else None,
        "parent": s.parent, "depends_on": list(s.depends_on),
        "description": list(s.description),
        "interface": _sorted([flow_json(f, components) for f in s.interface]),
        "flows": _sorted([flow_json(f, components) for f in s.internal]),
        "blocks": [_compact({"kind": k, "header": h, "mods": [list(m) for m in mods]})
                   for k, h, mods in s.blocks],
        "components": sorted((component_json(components[m], components) for m in s.members),
                             key=lambda c: (c["glyph"], c["kind"])),
        "accepts": sorted(s.accepts),
        "hashes": {"interface": s.interface_hash, "body": s.body_hash}
        if s.body_hash else None})


def with_hashes(s: System, components: dict) -> System:
    body = system_json(s, components)
    iface = body.get("interface", [])
    for k in ("parent", "depends_on"):
        body.pop(k, None)
    return replace(s, interface_hash=digest(iface), body_hash=digest(hash_form(body)))


def hash_form(obj):
    """obj with every `description` list sorted, so moving a commented statement
    changes no hash (the descriptions' order is the source's)."""
    if isinstance(obj, dict):
        return {k: sorted(v) if k == "description" and isinstance(v, list)
                else hash_form(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [hash_form(v) for v in obj]
    return obj


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(obj) -> str:
    """sha256 of obj's canonical JSON, first 16 hex digits."""
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()[:HASH_LEN]


def to_json(model: Model) -> dict:
    """The whole model, normalised: systems by key, the readiness facts."""
    return {
        "spec": model.stem, "top": model.top,
        "systems": {k: system_json(s, model.components) for k, s in model.systems.items()},
        "shared": [{"component": s.glyph, "systems": list(s.systems), "home": s.home}
                   for s in model.shared],
        "untyped": [{"line": u.line, "from": u.src, "to": u.dst, "arrow": u.arrow,
                     "missing": u.missing, "systems": list(u.systems)}
                    for u in model.untyped]}


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug(name: str) -> str:
    """An ASCII-safe file name for a name: lower-case letters, digits and `-`;
    any other character by its code point (`Café` → `caf-e9`)."""
    out = []
    for ch in name.lower():
        out.append(ch if ch.isascii() else f"-{ord(ch):x}-")
    s = _SLUG_RE.sub("-", "".join(out)).strip("-")
    return s or "x"


def slugs(names: Iterable) -> dict:
    """{name: slug}, collision-free (a later name that would clash, case aside,
    gets `-2`, `-3` …), in the order given."""
    out, taken = {}, set()
    for name in names:
        base = s = slug(name)
        n = 1
        while s in taken:
            n += 1
            s = f"{base}-{n}"
        taken.add(s)
        out[name] = s
    return out


def _sorted(items: list) -> list:
    return sorted(items, key=canonical)


def _compact(d: dict) -> dict:
    """d without its None, False and empty values."""
    return {k: v for k, v in d.items()
            if v is not None and v is not False and v not in ("", [], {}, ())}
