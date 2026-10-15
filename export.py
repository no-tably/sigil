#!/usr/bin/env python3
"""
export.py — export a ready Sigil spec as a build skeleton: one folder per system,
one Markdown file per component, and a manifest that is the contract.

Usage:
    ./export.py <spec.sigil> --out DIR [--dialect D]

Options:
    --out DIR    the export folder (made when missing). It must be empty, or hold
                 an earlier export (a manifest.json): export.py never writes over
                 a folder it did not make
    --dialect D  load a dialect (as lint.py and check.py do; default $SIGIL_DIALECT)

The gate. Only a document that is ready exports: its mode line is `#!spec`,
lint.py reports no error, and check.py with the readiness rules (`--export`,
spec mode, so overlap runs too) leaves no error and no warning unacknowledged
(info is fine). Otherwise export.py prints the lines that block it, exits 2 and
touches nothing.

The folder (systems, homes and hashes as export_model.py reads them):

    DIR/
      manifest.json            the contract, written LAST (temp file + os.replace)
      README.md                the index: systems, what each depends on
      <system>/README.md       the system: description, components, boundary, deps
      <system>/<component>.md  kind, description, interface, requirements, lifecycle
      <system>/system.json     the same, machine-readable

    manifest.json = {"sigil_export": 1, "spec": <file name>, "spec_hash": …,
      "systems": {name: {"path", "interface", "body", "components", "depends_on"}}}

Folder and file names are slugs of the names (export_model.slugs). Whoever
builds against the export reads the manifest first: its hashes are the truth.

Exit codes: 0 exported · 1 the folder could not be written · 2 not ready to
export, or bad input (unreadable spec, unknown dialect, a folder export.py did
not make).

Standard library only. Deterministic: no clock, no randomness, no set-order output.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


_HERE = Path(__file__).resolve().parent

EXPORT_VERSION = 1
MANIFEST = "manifest.json"
INDEX = "README.md"
SYSTEM_README = "README.md"
SYSTEM_JSON = "system.json"
WRITTEN_SUFFIXES = (".md", ".json")          # what a system folder holds of ours
_README_KEY = "\0readme"                     # reserves `readme` among component slugs


def _sibling(name: str, fname: str):
    """The module fname beside this file, loaded by path once per directory and then
    shared (the same loader check.py and export_model.py use, so the Graph and
    modules are the ones they read)."""
    key = f"{name}@{_HERE}"
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, _HERE / fname)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod   # dataclasses resolve string annotations via sys.modules
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            del sys.modules[key]
            raise
    return sys.modules[key]


def _model():
    return _sibling("sigil_export_model", "export_model.py")


def _check():
    return _sibling("sigil_check", "check.py")


def _lint():
    return _sibling("sigil_viewkit", "viewkit.py").lint


def _dialects():
    return _sibling("sigil_dialects", "dialects.py")


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

def gate(text: str, dialect, lint, check) -> tuple:
    """The lines that block exporting `text` (none: it is ready). `lint` and
    `check` are the lint.py and check.py modules. A document that is no spec, or
    that lint finds errors in, is not checked further. Raises ValueError for a
    rule pack check.py refuses."""
    mode = check.read_mode(text.splitlines())
    if mode != "spec":
        return (f"mode: the document is `#!{mode}`; only a `#!spec` document exports",)
    errors = tuple(d.format() for d in lint.lint(text, dialect=dialect).diagnostics
                   if d.severity == "error")
    if errors:
        return errors
    report = check.check(text, mode="spec", dialect=dialect, export=True)
    return tuple(f.line_text() for f in report.shown if f.severity in ("error", "warn"))


def out_problem(out: Path) -> Optional[str]:
    """Why export.py may not write into `out` (None: it may): it is a file, or a
    folder that is neither empty nor an earlier export."""
    if not out.exists():
        return None
    if not out.is_dir():
        return f"{out} is not a folder"
    if (out / MANIFEST).is_file() or not any(out.iterdir()):
        return None
    return (f"{out} holds files but no {MANIFEST}: export.py writes only into an "
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


def plan_export(model, spec_name: str, spec_text: str) -> ExportPlan:
    """What the export of `model` holds (read from the spec file `spec_name`,
    whose text is `spec_text`): pure, nothing written."""
    em = _model()
    keys = system_order(model)
    folders = em.slugs(keys)
    forms = {k: em.system_json(model.systems[k], model.components) for k in keys}
    systems = {k: plan_system(k, model.systems[k], forms[k], folders) for k in keys}
    manifest = {"sigil_export": EXPORT_VERSION, "spec": spec_name,
                "spec_hash": spec_hash(spec_text),
                "systems": {k: p.entry for k, p in systems.items()}}
    return ExportPlan(systems, index_md(spec_name, manifest, forms), manifest)


def system_order(model) -> list:
    """The top system, then the others by key: an order (and so folder names)
    reordering the spec cannot change."""
    return [model.top] + sorted(k for k in model.systems if k != model.top)


def spec_hash(text: str) -> str:
    """sha256 of the spec file's text, first 16 hex digits."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:_model().HASH_LEN]


def plan_system(key: str, system, form: dict, folders: dict) -> SystemPlan:
    """One system's folder: README.md, a file per component, system.json."""
    names = component_files(form.get("components", []))
    files = {SYSTEM_README: system_md(key, form, names, folders)}
    for c in form.get("components", []):
        files[names[c["glyph"]]] = component_md(c, key, folders[key])
    files[SYSTEM_JSON] = json_text(form)
    entry = {"path": folders[key], "interface": system.interface_hash,
             "body": system.body_hash,
             "components": [c["glyph"] for c in form.get("components", [])],
             "depends_on": list(system.depends_on)}
    return SystemPlan(key, folders[key], files, entry)


def component_files(components: list) -> dict:
    """{glyph: file name} for a system's components (in their normalised order),
    collision-free, never `readme.md` (README.md sits beside them)."""
    slugs = _model().slugs([_README_KEY] + [c["glyph"] for c in components])
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
        return "The top level of the spec: every component no expansion or tree holds."
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
        blocks.append(f"- {b['kind']} `{b['header']}`" + (f" `{mods}`" if mods else ""))
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
        + section("Acknowledgements (document-wide)",
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
        f"Exported from `{spec_name}` (spec hash `{manifest['spec_hash']}`) by export.py.", "",
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

def write_export(out: Path, plan: ExportPlan, only: Optional[Iterable] = None) -> None:
    """Write the plan into `out`: the systems (all, or the keys in `only`), then
    the index, then the manifest last via a temp file and os.replace (the commit
    point: a reader never sees a manifest whose files are not there yet)."""
    wanted = set(plan.systems if only is None else only)
    keys = [k for k in plan.systems if k in wanted]
    out.mkdir(parents=True, exist_ok=True)
    for k in keys:
        write_system(out / plan.systems[k].path, plan.systems[k].files)
    write_text(out / INDEX, plan.index)
    replace_text(out / MANIFEST, json_text(plan.manifest))


def write_system(folder: Path, files: dict) -> None:
    """A system folder holding exactly `files` of ours: a component file an
    earlier export wrote that the plan no longer has is removed."""
    folder.mkdir(parents=True, exist_ok=True)
    for p in sorted(folder.iterdir()):
        if p.is_file() and p.suffix in WRITTEN_SUFFIXES and p.name not in files:
            p.unlink()
    for name, content in files.items():
        write_text(folder / name, content)


def write_text(path: Path, content: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


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
# CLI
# ---------------------------------------------------------------------------

def done_lines(plan: ExportPlan, out: Path) -> list:
    out_lines = [f"sigil export: {len(plan.systems)} system(s) → {out}"]
    for key, sp in plan.systems.items():
        e = sp.entry
        out_lines.append(f"  {sp.path}/  {key}: {len(e['components'])} component(s), "
                         f"interface {e['interface']}, body {e['body']}")
    return out_lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="export.py",
        description="Export a ready Sigil spec as a build skeleton: a folder per "
                    "system, a file per component, manifest.json as the contract.")
    ap.add_argument("spec", help="a .sigil file whose mode line is #!spec")
    ap.add_argument("--out", required=True, metavar="DIR",
                    help="the export folder (empty, or an earlier export)")
    ap.add_argument("--dialect", default=None,
                    help="dialect name or path (default: $SIGIL_DIALECT)")
    a = ap.parse_args(argv)
    spec, out = Path(a.spec), Path(a.out)
    try:
        dialect = _dialects().load(a.dialect)
        text = spec.read_text(encoding="utf-8")
        blocking = gate(text, dialect, _lint(), _check())
    except (ValueError, OSError) as exc:
        print(f"export.py: {exc}", file=sys.stderr)
        return 2
    if blocking:
        print("\n".join(blocking))
        print(f"export.py: {spec.name} is not ready to export: {len(blocking)} "
              "blocking line(s); nothing written", file=sys.stderr)
        return 2
    problem = out_problem(out)
    if problem:
        print(f"export.py: {problem}", file=sys.stderr)
        return 2
    plan = plan_export(_model().build_model(text, spec.stem, dialect), spec.name, text)
    try:
        write_export(out, plan)
    except OSError as exc:
        print(f"export.py: cannot write {out}: {exc}", file=sys.stderr)
        return 1
    print("\n".join(done_lines(plan, out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
