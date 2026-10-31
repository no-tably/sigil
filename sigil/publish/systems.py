"""
The export model as it leaves sigil: the hashed model, its normalised JSON, the
folder slugs. The model itself — systems, homes, components, flows, what is
untyped — is sigil.model.systems (check's export rules read it too); this module
adds what sigil export writes.

    model = build_model(text, stem="shop")
    model.systems["shop"].interface_hash, model.systems["shop"].body_hash
    model.components["Api_service"].interface_hash      # and body_hash
    to_json(model)          # the normalised, JSON-able form

HASHES

  sha256 of canonical JSON (sorted keys, compact separators), first 16 hex.
  A system's interface_hash covers its boundary flows and the shapes of the data
  they carry or its face's tree holds; its body_hash everything in it
  (interface, shapes, members, internal flows, control blocks, descriptions, its
  `#&` declarations). A component's interface_hash covers its flows in and out
  (with their modifiers) and the shapes of the data it carries, holds or is
  (sigil.model.systems, SHAPES: fields by name, so their order moves no hash; a
  comment is body only); its body_hash everything about it (kind, home,
  description, interface, requirements, lifecycle, a dialect's attrs). No line
  numbers (`lines`, a declaration's `line`), whitespace or order from the source
  enter either, nor the top system's name (the file stem or `--name`): renaming
  the spec moves no hash, unless the new name makes a top-level service the
  top's face or stops doing so (sigil.model.systems, SYSTEMS): then the systems
  themselves change. A component's hashes enter no system's hash (they are
  read off the same form).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Iterable, Mapping, Optional

from sigil.core import parse
from sigil.core.comments import read_acks, walk_layout
from sigil.core.statements import read_document
from sigil.model import systems
from sigil.model.systems import ARROW_MODE, Component, Flow, Model, System, slug
from sigil.analyse.check import CORE_NAMES


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def build_model(text: str, stem: str, dialect=None, walk=None, graph=None) -> Model:
    """The model of a document, hashed: parsed, its acknowledgements read as
    check reads them. `walk`: the document's reading (read_document of `text`
    with `dialect`) when the caller has it already, as the export gate does, and
    `graph` the model parsed from that walk; None reads / parses it here."""
    if walk is None:
        walk = read_document(text, dialect)           # the one reading
    if graph is None:
        graph = parse.parse_document(text, dialect=dialect, walk=walk)
    comments = {k + 1: v for k, v in walk.comments.items()}
    acks = read_acks(comments, walk_layout(walk), frozenset(CORE_NAMES.values()))
    return model_of(graph, stem, systems.accepted(acks, comments),
                    getattr(dialect, "NODE_KINDS", None) or {},
                    systems.field_comments(graph, walk))


def model_of(graph, stem: str, accepts: Iterable[systems.Accepted] = (),
             kinds: Mapping = {}, field_notes: Mapping = {}) -> Model:
    """sigil.model.systems.model_of with each component's and each system's
    interface and body hash."""
    m = systems.model_of(graph, stem, accepts, kinds, field_notes)
    comps = {nid: component_hashed(c, m.components, m.top) for nid, c in m.components.items()}
    return replace(m, components=comps,
                   systems={k: with_hashes(s, comps, m.top) for k, s in m.systems.items()})


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
        "implied": f.implied, "from_path": f.paths[0], "to_path": f.paths[1],
        "lines": [f.line] if f.line else None})


def component_json(c: Component, components: dict) -> dict:
    lc = c.lifecycle
    return _compact({
        "name": c.name, "kind": c.kind, "glyph": c.glyph, "home": c.home,
        "also_in": sorted(s for s in c.systems if s != c.home),
        "attrs": plain(c.attrs),
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
                            for a, b, on, mods in lc.transitions]},
        "shapes": shapes_json(c.shapes),
        "lines": list(c.lines),
        "hashes": {"interface": c.interface_hash, "body": c.body_hash}
        if c.body_hash else None})


def system_json(s: System, components: dict) -> dict:
    """One system in its normalised, JSON-able form (what system.json holds)."""
    return _compact({
        "name": s.name, "kind": s.kind,
        "face": components[s.face].glyph if s.face in components else None,
        "parent": s.parent, "depends_on": list(s.depends_on),
        "description": list(s.description),
        "interface": _sorted([flow_json(f, components) for f in s.interface]),
        "shapes": shapes_json(s.shapes),
        "flows": _sorted([flow_json(f, components) for f in s.internal]),
        "blocks": [_compact({"kind": k, "header": h, "mods": [list(m) for m in mods]})
                   for k, h, mods in s.blocks],
        "components": sorted((component_json(components[m], components) for m in s.members),
                             key=lambda c: (c["glyph"], c["kind"])),
        "accepts": sorted(s.accepts),
        "declarations": [{"name": d.name, "body": d.body, "line": d.line}
                         for d in s.declarations],
        "hashes": {"interface": s.interface_hash, "body": s.body_hash}
        if s.body_hash else None})


def shapes_json(shapes: Iterable[systems.Shape]) -> list:
    """Shapes as system.json lists them: each `glyph`, its `fields` (each `name`,
    `optional` when it is, the nested `shape`'s glyph; [] for a shape with no
    fields; left out when no shape is written) and `held` when a tree holds it.
    Already in their canonical order (by glyph; fields by name)."""
    out = []
    for sh in shapes:
        entry = {"glyph": sh.glyph}
        if sh.fields is not None:
            entry["fields"] = [_compact({"name": n, "optional": o, "shape": g})
                               for n, o, g in sh.fields]
        if sh.held:
            entry["held"] = True
        out.append(entry)
    return out


def interface_digest(body: dict) -> str:
    """The interface hash of a component's or system's form as the hashes read it:
    its interface flows and, when it has any, the shapes they carry or it holds
    (with none, the flows alone, as before shapes counted)."""
    flows, shapes = body.get("interface", []), body.get("shapes")
    return digest({"interface": flows, "shapes": shapes} if shapes else flows)


def component_hashed(c: Component, components: dict, top: str) -> Component:
    """c with its interface hash (its flows in and out, the shapes of the data it
    carries, holds or is) and body hash (its whole form); `top`: the top system's
    key, which enters neither."""
    body = hash_form(component_json(c, components), top)
    return replace(c, interface_hash=interface_digest(body), body_hash=digest(body))


def with_hashes(s: System, components: dict, top: str) -> System:
    """s with its interface and body hash; `top`: the top system's key, which
    enters neither (the top system's own name is left out of its body)."""
    body = hash_form(system_json(s, components), top)
    for k in ("parent", "depends_on") + (("name",) if s.kind == "top" else ()):
        body.pop(k, None)
    return replace(s, interface_hash=interface_digest(body), body_hash=digest(body))


UNHASHED = frozenset({"lines", "line", "hashes"})   # where it is written, and hashes
TOP = ""                                # the top system's key, as the hashes read it


def hash_form(obj, top: str):
    """obj as the hashes read it: no line numbers and no hashes (UNHASHED keys),
    every `description` and `declarations` list sorted (their order is the
    source's, so moving a statement changes no hash), and the top system's key
    `top` as TOP wherever a component names its systems (`home`, `also_in`), so
    the top's name (the file stem, or `--name`) changes no hash. A dialect's
    `attrs` are copied as they are (already JSON-safe): these rules read the
    export form's own keys, so an attribute named `lines` or `home` still counts."""
    if isinstance(obj, dict):
        out = {k: v if k == "attrs" else hash_form(v, top)
               for k, v in obj.items() if k not in UNHASHED}
        if isinstance(out.get("description"), list):
            out["description"] = sorted(out["description"])
        if "declarations" in out:
            out["declarations"] = sorted(out["declarations"], key=canonical)
        if out.get("home") == top:
            out["home"] = TOP
        if "also_in" in out:
            out["also_in"] = sorted(TOP if k == top else k for k in out["also_in"])
        return out
    if isinstance(obj, list):
        return [hash_form(v, top) for v in obj]
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


def slugs(names: Iterable, taken: Iterable[str] = ()) -> dict:
    """{name: slug}, collision-free (a later name that would clash, case aside,
    gets `-2`, `-3` …), in the order given; never one of `taken` (slugs already
    used elsewhere: an earlier export's folders)."""
    out, taken = {}, set(taken)
    for name in names:
        base = s = slug(name)
        n = 1
        while s in taken:
            n += 1
            s = f"{base}-{n}"
        taken.add(s)
        out[name] = s
    return out


def plain(value):
    """A dialect's attribute value as JSON can hold it: dicts (keys as text,
    sorted), lists, text, numbers, booleans and null as they are; a tuple or set
    as a list (a set sorted); anything else as its text."""
    if isinstance(value, dict):
        return {str(k): plain(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, (set, frozenset)):
        return sorted((plain(v) for v in value), key=canonical)
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _sorted(items: list) -> list:
    """Normalised items in an order the source cannot change: by their form as
    the hashes read it (no lines), then by their lines."""
    return sorted(items, key=lambda x: (canonical(hash_form(x, TOP)), canonical(x)))


def _compact(d: dict) -> dict:
    """d without its None, False and empty values."""
    return {k: v for k, v in d.items()
            if v is not None and v is not False and v not in ("", [], {}, ())}
