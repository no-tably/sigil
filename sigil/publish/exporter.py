"""
sigil.publish.exporter — export a ready Sigil spec as a build skeleton: one folder per system,
one Markdown file per component, and a manifest that is the contract.

Usage:
    sigil export <spec.sigil> --out DIR [--name NAME] [--dialect D] [--json] [--dry-run]

Options:
    --out DIR    the export folder (made when missing). It must be empty, or hold
                 an earlier export (a manifest.json): `sigil export` never writes over
                 a folder it did not make
    --name NAME  the top system's name (default: the spec file's stem); no hash
                 depends on it
    --dialect D  load a dialect (as `sigil lint` and `sigil check` do; default $SIGIL_DIALECT)
    --json       print the delta as JSON instead of the summary in words
    --dry-run    print the delta and write nothing

The gate. Only a document that is ready exports: its mode line is `#!spec`,
`sigil lint` reports no error, and `sigil check` with the readiness rules (`--export`,
spec mode, so overlap runs too) leaves no error and no warning unacknowledged
(info is fine). Otherwise `sigil export` prints the lines that block it, exits 2 and
touches nothing.

The folder (systems, homes and hashes as sigil.model.systems reads them):

    DIR/
      manifest.json            the contract, written LAST (temp file + os.replace)
      delta.json               what changed since the manifest before (a first
                               export: every system added)
      README.md                the index: systems, what each depends on
      <system>/README.md       the system: description, components, boundary, deps
      <system>/<component>.md  kind, description, interface, requirements, lifecycle
      <system>/system.json     the same, machine-readable

    manifest.json = {"sigil_export": 1, "sigil": <version>, "spec": <file name>,
      "spec_hash": …,
      "top": <the top system's key>, "dialect"?: {"name", "version"?},
      "systems": {name: {"path", "interface", "body", "components", "depends_on",
                         "parent",
                         "component_hashes": {glyph: {"interface", "body"}}}}}

    `sigil` is the version of sigil that wrote the export (sigil.__version__, which
    the command passes in: publish sits below the package's command layer). No
    hash reads it and the delta ignores it, so a new sigil marks nothing to
    rebuild; a builder that wants to re-export on a new sigil compares it itself.
    `dialect` only when a dialect is loaded: its NAME, and its VERSION when the
    dialect module defines one. A system's `components` lists its glyphs (the
    file names follow from them); `component_hashes` each one's hashes
    (sigil.publish.systems: what each covers). `depends_on` names the systems
    its own flows reach (never what it inherits from the systems enclosing it);
    `parent` the enclosing system's key (null for the top), as system.json has
    it, so a delta reads nesting from the manifests alone. Neither enters a
    hash.

A system.json holds the system's normalised form (sigil.publish.systems): its
components (each with its `hashes`, its `lines` and, from a dialect, its
`attrs`), its flows (each with its `lines`), its `#&` declarations ({name, body,
line}), and its hashes. Lines are 1-based lines of the spec; no hash reads them.

Folder and file names are slugs of the names (systems.slugs: at most 100
bytes, a long one ending in a hash of the name; no Windows device name). A
system keeps the folder the manifest before gave it, so a new system whose slug
clashes takes the next free `-2`, `-3` … and never moves an existing one
(folder_names); a folder that moves anyway (the top renamed) is `moved` in the
delta. Whoever builds against the export reads the manifest first: its hashes
are the truth.

`sigil export` never writes, compares or deletes through a symbolic link inside
DIR (a system folder, a file in one, a file at the root): it refuses, exit 2.

Re-export and delta. Before writing, `sigil export` reads the manifest already in DIR
(if any) and sorts every system into one list:

    added      in the new export only
    removed    in the old one only (its folder is deleted)
    rebuild    its body hash changed
    recheck    its body is unchanged, but a system it depends on changed its
               interface (its calls into that system need a second look), or
               one an enclosing system depends on, outside that enclosing
               system, did
    unchanged  neither

    delta.json = {"sigil_delta": 1, "spec": <file name>, "from": <old spec_hash>,
      "to": <new spec_hash>, "added": […], "removed": […], "rebuild": […],
      "recheck": […], "unchanged": […], "systems": {name: {"status", "old",
      "new", "because"?, "via"?}}}   (old/new: {"interface", "body"}, or null;
      because: the systems whose interface changed, for a recheck, its own
      dependencies first; via: {inherited one: the enclosing system it came
      through}, only when it inherits one; moved: {from, to} folders, only
      when its folder moved)

A system folder may also hold a builder's own files: `sigil export` deletes or
compares only the files an earlier export wrote (the names its manifest's
components give), so any other file in a system folder stays, and a removed
system's folder stays while it holds one.

Only files whose content changed are written, each file on its own. A spec
edit that only reformats or reorders leaves every system unchanged and every
component file untouched (the spec hash in the index and the manifest still
moves, and a system.json whose `lines` moved is rewritten). Every export writes
delta.json; a first export's lists every system as added. The delta is a hint:
the manifest's hashes stay the truth.

Exit codes: 0 exported (or a dry run) · 1 the folder could not be written · 2 not ready to
export, or bad input (unreadable spec, unknown dialect, a folder `sigil export` did
not make, a manifest.json it cannot read, or a symbolic link where it would write).

Standard library only. Deterministic: no clock, no randomness, no set-order output.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from sigil.publish import systems as em
from sigil.publish.delta import (
    DELTA, EXPORT_VERSION, delta, delta_lines, dropped_folders, manifest_problem,
    top_renamed)


MANIFEST = "manifest.json"
INDEX = "README.md"
SYSTEM_README = "README.md"
SYSTEM_JSON = "system.json"
_README_KEY = "\0readme"                     # reserves `readme` among component slugs


@dataclass(frozen=True)
class Gate:
    """What the gate found: the lines that block the export (none: it is
    ready), and lint's reading of the document (its Walk and parsed model), the
    one the export's model is built from. `walk` and `graph` are None when lint
    did not run (the document is no spec)."""
    blocking: tuple
    walk: object = None
    graph: object = None


def ready(text: str, dialect, lint, check, limits=None) -> Gate:
    """The gate on `text`: what blocks exporting it, and the reading it made.
    `lint` and `check` are the sigil.analyse lint and check modules (the command
    passes them in). A document that is no spec, or that lint finds errors in,
    is not checked further. Raises ValueError for a rule pack check refuses. The
    document is read and parsed once: lint's reading and model are the ones
    check judges (and run builds the export's model from). `limits` (--limit's
    NAME=N pairs, or a sim.Limits; None: none given), laid over the document's own
    `#%` limits by check.check, bound check's runs, so a run cut at a limit is
    cleared by raising it (on the `#%` line, or `sigil export --limit NAME=N`)."""
    mode = check.read_mode(text.splitlines())
    if mode != "spec":
        return Gate((f"mode: the document is `#!{mode}`; only a `#!spec` document exports",))
    linted = lint.lint_reading(text, dialect=dialect)
    errors = tuple(d.format() for d in linted.result.diagnostics if d.severity == "error")
    if errors:
        return Gate(errors, linted.walk, linted.graph)
    report = check.check(text, mode="spec", dialect=dialect, export=True, limits=limits,
                         walk=linted.walk, graph=linted.graph)
    return Gate(tuple(f.line_text() for f in report.shown if f.severity in ("error", "warn")),
                linted.walk, linted.graph)


def gate(text: str, dialect, lint, check, limits=None) -> tuple:
    """The lines that block exporting `text` (none: it is ready): ready's."""
    return ready(text, dialect, lint, check, limits).blocking


def out_problem(out: Path) -> Optional[str]:
    """Why `sigil export` may not write into `out` (None: it may): it is a file, or a
    folder that is neither empty nor an earlier export."""
    if not out.exists():
        return None
    if not out.is_dir():
        return f"{out} is not a folder"
    if (out / MANIFEST).is_file() or not any(out.iterdir()):
        return None
    return (f"{out} holds files but no {MANIFEST}: sigil export writes only into an "
            "empty folder or an earlier export")


# ---------------------------------------------------------------------------
# The plan: every file's content, before anything is written
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SystemPlan:
    key: str
    path: str                                # folder name (a slug)
    files: dict                              # file name → content
    entry: dict                              # its manifest entry


@dataclass(frozen=True)
class ExportPlan:
    systems: dict                            # key → SystemPlan, top first
    index: str                               # README.md at the root
    manifest: dict


def plan_export(model, spec_name: str, spec_text: str, dialect=None,
                version: Optional[str] = None, old: Optional[dict] = None) -> ExportPlan:
    """What the export of `model` holds (read from the spec file `spec_name`,
    whose text is `spec_text`, with `dialect` loaded or None), written by sigil
    `version` (the manifest's "sigil"; None: null): pure, nothing written.
    `old`: the manifest of the export already there (None: none), whose
    folders the systems it lists keep (folder_names)."""
    keys = system_order(model)
    folders = folder_names(keys, old, model.top)
    forms = {k: em.system_json(model.systems[k], model.components) for k in keys}
    systems = {k: plan_system(k, model.systems[k], forms[k], folders) for k in keys}
    manifest = {"sigil_export": EXPORT_VERSION, "sigil": version, "spec": spec_name,
                "spec_hash": spec_hash(spec_text), "top": model.top}
    if dialect is not None:
        manifest["dialect"] = dialect_entry(dialect)
    manifest["systems"] = {k: p.entry for k, p in systems.items()}
    return ExportPlan(systems, index_md(spec_name, manifest, forms), manifest)


def folder_names(keys: list, old: Optional[dict], top: str) -> dict:
    """{system key: folder} for the systems `keys` (top first). A system the
    earlier export's manifest `old` lists keeps its folder there, so a new
    system never moves it; a new one takes its slug, or the next free `-2`,
    `-3` … past every folder `old` names (a removed system's folder may still
    hold a builder's files). The top renamed (delta.top_renamed) is the same
    system: it may take its old folder back, and otherwise follows its name."""
    olds = (old or {}).get("systems", {})
    out, used = {}, set()
    for k in keys:
        path = olds.get(k, {}).get("path")
        if path and path not in used:
            out[k] = path
            used.add(path)
    taken = used | {e["path"] for e in olds.values()}
    moved = top_renamed(old, {"systems": dict.fromkeys(keys), "top": top})
    for k in keys:
        if k in out:
            continue
        mine = olds[moved["from"]]["path"] if moved and k == moved["to"] else None
        out[k] = em.slugs([k], taken - {mine})[k]
        taken.add(out[k])
    return {k: out[k] for k in keys}


def dialect_entry(dialect) -> dict:
    """The manifest's record of the dialect the export was read with: its NAME,
    and its VERSION (as text) when the module defines one."""
    out = {"name": str(getattr(dialect, "NAME", "") or "")}
    version = getattr(dialect, "VERSION", None)
    if version is not None:
        out["version"] = str(version)
    return out


def system_order(model) -> list:
    """The top system, then the others by key: an order (and so folder names)
    reordering the spec cannot change."""
    return [model.top] + sorted(k for k in model.systems if k != model.top)


def spec_hash(text: str) -> str:
    """sha256 of the spec file's text, first 16 hex digits."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:em.HASH_LEN]


def plan_system(key: str, system, form: dict, folders: dict) -> SystemPlan:
    """One system's folder: README.md, a file per component, system.json."""
    names = component_files(form.get("components", []))
    files = {SYSTEM_README: system_md(key, form, names, folders)}
    for c in form.get("components", []):
        files[names[c["glyph"]]] = component_md(c, key, folders[key])
    files[SYSTEM_JSON] = json_text(form)
    comps = form.get("components", [])
    entry = {"path": folders[key], "interface": system.interface_hash,
             "body": system.body_hash,
             "components": [c["glyph"] for c in comps],
             "depends_on": list(system.depends_on),
             "parent": system.parent,
             "component_hashes": {c["glyph"]: c["hashes"] for c in comps}}
    return SystemPlan(key, folders[key], files, entry)


def component_files(components: list) -> dict:
    """{glyph: file name} for a system's components (in their normalised order),
    collision-free, never `readme.md` (README.md sits beside them)."""
    slugs = em.slugs([_README_KEY] + [c["glyph"] for c in components])
    return {c["glyph"]: slugs[c["glyph"]] + ".md" for c in components}


def json_text(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------------------
# Markdown: plain, short, every requirement verbatim
# ---------------------------------------------------------------------------

MODE_WORDS = {"sync": "sync call", "async": "async message", "return": "return",
              "failure": "failure route", "optional": "optional route", "flow": "flow"}


def mod_text(pair) -> str:
    """One modifier as the spec writes it: `×3`, `^10k@drop`, `.age`, `!`,
    `@inv idempotent(key)`, `@timeout(2s)`, `@owns`."""
    name, arg = pair
    if name in ("×", "^", "."):
        return f"{name}{arg or ''}"
    if name in ("!", "?"):
        return name
    if arg is None:
        return f"@{name}"
    return f"@{name} {arg}" if name == "inv" else f"@{name}({arg})"


def flow_text(src: str, dst: str, f: dict) -> str:
    """A flow as one line of notation: `src arrow dst×card : payload mods`."""
    dst = f"{dst}×{f['card']}" if f.get("card") else dst
    out = f"{src} {f['arrow']} {dst}"
    if f.get("payload"):
        out += f" : {f['payload']}"
    mods = " ".join(mod_text(m) for m in f.get("mods", []))
    return f"{out} {mods}" if mods else out


def flow_item(src: str, dst: str, f: dict) -> list:
    """A flow as a list item (and its block-string text, when it has one)."""
    notes = [MODE_WORDS.get(f.get("mode"), f.get("mode", "flow"))]
    if f.get("external"):
        notes.append("external")
    if f.get("implied"):
        notes.append(f"implied ({f['implied']})")
    paths = [p for p in (f.get("from_path"), f.get("to_path")) if p]
    if paths:
        notes.append("path " + " → ".join(paths))
    out = [f"- `{flow_text(src, dst, f)}` — {', '.join(notes)}"]
    if f.get("text"):
        out += ["", "  ```", *(f"  {ln}" for ln in f["text"].splitlines()), "  ```"]
    return out


def component_flow_item(glyph: str, f: dict) -> list:
    """A component's flow, written from its side: `out` from it, `in` to it."""
    if f["dir"] == "out":
        return flow_item(glyph, f["peer"], f)
    if f["dir"] == "in":
        return flow_item(f["peer"], glyph, f)
    return flow_item(glyph, glyph, f)


def section(title: str, body: list, empty: Optional[str] = None) -> list:
    """A `## title` section; nothing (or `empty`) when the body is empty."""
    if not body:
        return [f"## {title}", "", empty, ""] if empty else []
    return [f"## {title}", "", *body, ""]


def paragraphs(texts: Iterable[str]) -> list:
    """Each text its own paragraph (a blank line after each)."""
    return [ln for t in texts for ln in (t, "")]


def lines_of(items: Iterable[list]) -> list:
    return [ln for item in items for ln in item]


def component_md(c: dict, home: str, folder: str) -> str:
    """One component: kind, description, interface, requirements, lifecycle."""
    also = c.get("also_in", [])
    head = [f"# {c['glyph']}", "",
            f"Kind: {c['kind']}. Lives in system `{home}` (folder `{folder}/`)."
            + (f" Also written in: {', '.join(f'`{s}`' for s in also)}." if also else ""),
            ""]
    req = c.get("requirements", {})
    requirements = ([f"- `{mod_text(m)}`" for m in req.get("modifiers", [])]
                    + [f"- {mode} access to `{store}` (granted by the store)"
                       for mode, store in req.get("access", [])]
                    + [f"- {a}" for a in req.get("accepts", [])])
    return "\n".join(
        head
        + section("Description", paragraphs(c.get("description", []))[:-1])
        + section("Interface",
                  lines_of(component_flow_item(c["glyph"], f) for f in c.get("interface", [])),
                  "No flows in or out.")
        + section("Requirements", requirements, "None stated.")
        + section("Lifecycle", lifecycle_lines(c["lifecycle"]) if c.get("lifecycle") else [])
    ).rstrip("\n") + "\n"


def lifecycle_lines(lc: dict) -> list:
    def names(xs):
        return ", ".join(f"`{x}`" for x in xs) or "none"
    out = [f"States: {names(lc.get('states', []))}.",
           f"Initial: {names(lc.get('initial', []))}.",
           f"Terminal: {names(lc.get('terminal', []))}.", ""]
    for t in lc.get("transitions", []):
        on = f" on `{t['on']}`" if t.get("on") else ""
        mods = " ".join(mod_text(m) for m in t.get("mods", []))
        out.append(f"- `{t['from']}` → `{t['to']}`{on}" + (f" `{mods}`" if mods else ""))
    return out


def system_kind_line(key: str, form: dict) -> str:
    parent = f" (inside system `{form['parent']}`)" if form.get("parent") else ""
    if form["kind"] == "top":
        face = f", written as `{form['face']}`" if form.get("face") else ""
        return f"The top level of the spec{face}: every component no expansion or tree holds."
    if form["kind"] == "expansion":
        return f"The expansion of `{form.get('face', key)}`{parent}."
    return f"The composition tree rooted at `{form.get('face', key)}`{parent}."


def system_md(key: str, form: dict, files: dict, folders: dict) -> str:
    """One system: what it is, its components, its boundary (the contract), its
    internal flows and blocks, and what it depends on."""
    hashes = form.get("hashes", {})
    head = [f"# {key}", "", system_kind_line(key, form), "",
            *paragraphs(form.get("description", [])),
            f"Interface hash `{hashes.get('interface', '')}` · "
            f"body hash `{hashes.get('body', '')}`.", ""]
    comps = [f"- `{c['glyph']}` ({c['kind']}) — [{files[c['glyph']]}]({files[c['glyph']]})"
             for c in form.get("components", [])]
    blocks = []
    for b in form.get("blocks", []):
        mods = " ".join(mod_text(m) for m in b.get("mods", []))
        header = f" `{b['header']}`" if b.get("header") else ""  # a bare `loop {` has none
        blocks.append(f"- {b['kind']}{header}" + (f" `{mods}`" if mods else ""))
    deps = [f"- `{d}` — [{folders[d]}/](../{folders[d]}/{SYSTEM_README})"
            for d in form.get("depends_on", [])]
    return "\n".join(
        head
        + section("Components", comps, "None: the system is its face alone.")
        + section("Boundary", ["The flows that cross into or out of this system: "
                               "its contract.", "",
                               *lines_of(flow_item(f["from"], f["to"], f)
                                         for f in form.get("interface", []))]
                  if form.get("interface") else [], "No flow crosses it.")
        + section("Flows inside", lines_of(flow_item(f["from"], f["to"], f)
                                               for f in form.get("flows", [])))
        + section("Control blocks", blocks)
        + section("Depends on", deps, "Nothing.")
        + section("Acknowledgements (document-wide)" if form["kind"] == "top"
                  else "Acknowledgements (on its header)",
                  [f"- {a}" for a in form.get("accepts", [])])
    ).rstrip("\n") + "\n"


def index_md(spec_name: str, manifest: dict, forms: dict) -> str:
    """The root README.md: how to read the export, and every system."""
    rows = []
    for key, e in manifest["systems"].items():
        deps = ", ".join(f"`{d}`" for d in e["depends_on"]) or "nothing"
        rows.append(f"- `{key}` ({forms[key]['kind']}) — [{e['path']}/]"
                    f"({e['path']}/{SYSTEM_README}) — depends on {deps}")
    return "\n".join([
        f"# Export of {spec_name}", "",
        f"Exported from `{spec_name}` (spec hash `{manifest['spec_hash']}`) by sigil export.", "",
        f"- `{MANIFEST}` is the contract: per system, its interface hash, body hash, "
        "components and what it depends on. It is written last; a folder without it "
        "is no finished export.",
        f"- `<system>/{SYSTEM_README}` describes a system: its components, its boundary "
        "(the flows that cross it) and what it depends on.",
        "- `<system>/<component>.md` states one component: kind, description, "
        "interface, requirements and lifecycle, as the spec writes them.",
        f"- `<system>/{SYSTEM_JSON}` holds the same, machine-readable.", "",
        "## Systems", "", *rows]) + "\n"


# ---------------------------------------------------------------------------
# Writing (the only side effects)
# ---------------------------------------------------------------------------

def written_files(manifest: Optional[dict]) -> dict:
    """{folder: the file names `sigil export` wrote there} for the export `manifest`
    describes (None: no export yet, so nothing). Only these are ever overwritten
    as stale or deleted: a file a builder adds to a system folder is not ours."""
    out: dict = {}
    for e in (manifest or {}).get("systems", {}).values():
        out.setdefault(e["path"], set()).update(system_file_names(e["components"]))
    return {k: frozenset(v) for k, v in out.items()}


def system_file_names(glyphs: list) -> set:
    """The file names a system folder holds for the components `glyphs` (its
    manifest entry's list, in the same order plan_system names them)."""
    names = component_files([{"glyph": g} for g in glyphs]).values()
    return {SYSTEM_README, SYSTEM_JSON, *names}


def write_export(out: Path, plan: ExportPlan, only: Optional[Iterable] = None,
                 drop: Iterable[str] = (), change: Optional[dict] = None,
                 written: Optional[dict] = None) -> list:
    """Write the plan into `out`: the systems (all, or the keys in `only`), then
    remove the folders in `drop`, then the index, then `change` as delta.json
    (when given), then the manifest last via a temp file and os.replace (the
    commit point: a reader never sees a manifest whose files are not there yet).
    `written` ({folder: file names}, from written_files of the earlier manifest)
    names the files an earlier export wrote: the only ones removed when the plan
    no longer holds them. Every file is written only when its content changed.
    Returns the dropped folders kept because they
    hold files `sigil export` did not write."""
    written = written or {}
    wanted = set(plan.systems if only is None else only)
    keys = [k for k in plan.systems if k in wanted]
    out.mkdir(parents=True, exist_ok=True)
    for k in keys:
        sp = plan.systems[k]
        write_system(out / sp.path, sp.files, written.get(sp.path, frozenset()))
    kept = [name for name in drop
            if not remove_system(out / name, written.get(name, frozenset()))]
    write_changed(out / INDEX, plan.index)
    if change is not None:
        write_changed(out / DELTA, json_text(change))
    manifest = json_text(plan.manifest)
    if written_text(out / MANIFEST) != manifest:
        replace_text(out / MANIFEST, manifest)
    return kept


def read_manifest(out: Path) -> Optional[dict]:
    """The manifest of the export already in `out` (None: there is none). Raises
    ValueError for one `sigil export` cannot read."""
    text = written_text(out / MANIFEST)
    if text is None:
        return None
    try:
        obj = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"{out / MANIFEST} is no JSON: {exc}") from None
    except RecursionError:                   # nested deeper than the reader goes
        raise ValueError(f"{out / MANIFEST} is no manifest: nested too deep") from None
    problem = manifest_problem(obj)
    if problem:
        raise ValueError(f"{out / MANIFEST}: {problem}")
    return obj


def changed_systems(out: Path, plan: ExportPlan, written: dict) -> list:
    """The systems whose folder in `out` differs from the plan (missing, a planned
    file missing or with other content, or a stale file an earlier export wrote,
    named in `written`): the only ones written. Other files are not ours."""
    return [k for k, sp in plan.systems.items()
            if folder_differs(out / sp.path, sp.files, written.get(sp.path, frozenset()))]


def folder_differs(folder: Path, files: dict, ours: frozenset) -> bool:
    """Whether `folder` holds other than `files` among the planned names and the
    names an earlier export wrote (`ours`)."""
    if not folder.is_dir():
        return True
    return any(written_text(folder / n) != files.get(n) for n in sorted(set(files) | ours))


def remove_system(folder: Path, ours: frozenset) -> bool:
    """Remove an earlier export's system folder: the files it wrote there (`ours`),
    then the folder itself. False when it stays because it holds other files."""
    if not folder.is_dir():
        return True
    for p in stale_files(folder, ours, {}):
        p.unlink()
    if any(folder.iterdir()):
        return False
    folder.rmdir()
    return True


def written_text(path: Path) -> Optional[str]:
    """A file's exact text (newlines as written; bytes that are no UTF-8 as
    U+FFFD), or None when there is none."""
    try:
        with open(path, encoding="utf-8", errors="replace", newline="") as fh:
            return fh.read()
    except FileNotFoundError:
        return None


def write_changed(path: Path, content: str) -> None:
    if written_text(path) != content:
        write_text(path, content)


def write_system(folder: Path, files: dict, ours: frozenset) -> None:
    """A system folder holding `files`: a file an earlier export wrote there
    (named in `ours`) that the plan no longer has is removed; a planned file is
    written when its content differs; any other file is left as it is."""
    folder.mkdir(parents=True, exist_ok=True)
    for p in stale_files(folder, ours, files):
        p.unlink()
    for name, content in files.items():
        write_changed(folder / name, content)


def stale_files(folder: Path, ours: frozenset, files: dict) -> list:
    """The files in `folder` an earlier export wrote (`ours`) that `files` lacks."""
    return [folder / n for n in sorted(ours - set(files)) if (folder / n).is_file()]


def write_text(path: Path, content: str) -> None:
    """Write `path`, never through a symbolic link (link_problem refuses one
    first; O_NOFOLLOW where the platform has it, should one appear since)."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    with open(os.open(path, flags, 0o666), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


def link_problem(out: Path, plan: ExportPlan, old: Optional[dict]) -> Optional[str]:
    """Why `sigil export` may not write into `out` because of a symbolic link
    (None: there is none where it would write, compare or delete): a system
    folder, a file in one, or a file at the root. Writing or deleting through a
    link would reach outside `out`; `out` itself may be one."""
    written = written_files(old)
    folders = {sp.path: set(sp.files) for sp in plan.systems.values()}
    for name in dropped_folders(old, plan.manifest):
        folders.setdefault(name, set())
    paths = [out / n for n in (INDEX, DELTA, MANIFEST)]
    for name in sorted(folders):
        paths.append(out / name)
        paths += [out / name / f for f in sorted(folders[name] | written.get(name, set()))]
    for p in paths:
        if p.is_symlink():
            return (f"{p} is a symbolic link: sigil export never writes or deletes "
                    "through one (remove it, or export into another folder)")
    return None


def replace_text(path: Path, content: str) -> None:
    """Write `path` whole or not at all: a temp file beside it, then os.replace."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ---------------------------------------------------------------------------
# The run: plan, delta, write (the `sigil export` command is sigil.cli's, which
# reads the spec, loads the dialect and runs the gate first)
# ---------------------------------------------------------------------------

def done_lines(plan: ExportPlan, out: Path) -> list:
    out_lines = [f"sigil export: {len(plan.systems)} system(s) → {out}"]
    for key, sp in plan.systems.items():
        e = sp.entry
        out_lines.append(f"  {sp.path}/  {key}: {len(e['components'])} component(s), "
                         f"interface {e['interface']}, body {e['body']}")
    return out_lines


def report(change: dict, as_json: bool, head: list) -> str:
    """What the export prints: the delta as JSON, or `head` and the delta in words."""
    return json_text(change) if as_json else "\n".join(head + delta_lines(change)) + "\n"


@dataclass(frozen=True)
class Outcome:
    """What one export did. `status`: 0 exported (or a dry run), 1 the folder
    could not be written, 2 refused (`problem` says why). `printed`: the report
    for stdout. `kept`: removed systems' folders left in place because they hold
    files the export did not write."""
    status: int
    printed: str = ""
    problem: Optional[str] = None
    kept: tuple = ()


def run(text: str, spec: Path, out: Path, dialect, as_json: bool = False,
        dry_run: bool = False, passed: Optional[Gate] = None,
        name: Optional[str] = None, version: Optional[str] = None) -> Outcome:
    """Export `text` (a spec the gate passed, read from `spec`) into `out`, or
    with `dry_run` only say what would change. `passed`: that gate (ready's), whose
    reading the model is built from; None reads and parses `text` here. `name`:
    the top system's name (None: the spec's stem). `version`: the sigil that
    writes it (the manifest's "sigil"; the command passes sigil.__version__)."""
    try:
        problem = out_problem(out)
        old = None if problem else read_manifest(out)
    except (ValueError, OSError) as exc:
        problem = str(exc)
    if problem:
        return Outcome(2, problem=problem)
    walk, graph = (passed.walk, passed.graph) if passed else (None, None)
    model = em.build_model(text, name or spec.stem, dialect, walk=walk, graph=graph)
    plan = plan_export(model, spec.name, text, dialect, version, old)
    try:
        problem = link_problem(out, plan, old)
    except OSError as exc:
        problem = str(exc)
    if problem:
        return Outcome(2, problem=problem)
    change = delta(old, plan.manifest)
    if dry_run:
        head = [f"sigil export (dry run): nothing written to {out}"]
        return Outcome(0, report(change, as_json, head))
    written = written_files(old)
    try:
        kept = write_export(out, plan, only=changed_systems(out, plan, written),
                            drop=dropped_folders(old, plan.manifest),
                            change=change, written=written)
    except OSError as exc:
        return Outcome(1, problem=f"cannot write {out}: {exc}")
    return Outcome(0, report(change, as_json, done_lines(plan, out)), kept=tuple(kept))
