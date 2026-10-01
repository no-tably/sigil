#!/usr/bin/env python3
"""
dialects.py — load a Sigil DIALECT: an optional extension of the core notation.

Core Sigil (lint.py / render.py with no dialect) knows only the standard
vocabulary. A dialect is a single Python module (`dialect.py`) that layers extra
vocabulary and rules on top — new modifiers, new glyph syntax, new lint rules,
extra render strips — without the core tools ever importing it. A dialect is
loaded at run time and handed to the tools:

    import dialects, lint, render
    d = dialects.load("mydialect")          # or a path, or None → $SIGIL_DIALECT
    lint.lint(text, dialect=d)
    render.parse_document(text, dialect=d)
    render.render(text, depth=1, dialect=d)

Both CLIs accept `--dialect NAME` (default: the SIGIL_DIALECT environment
variable; unset / empty = pure core Sigil).

Resolution (`load(spec)`):
    spec None       → read env SIGIL_DIALECT; unset or "" → None (core only).
    spec ""         → None (core only).
    an existing file path → loaded directly (a directory is taken to hold
                      `dialect.py`).
    a NAME          → a leading "sigil-" is dropped (so "x" and "sigil-x" are the
                      same dialect); a name containing a path separator or ".."
                      is rejected. Then the first of:
                        <this dir>/../sigil-<name>/dialect.py
                        <dir>/sigil-<name>/dialect.py  or  <dir>/<name>/dialect.py
                          for each <dir> in env SIGIL_DIALECT_PATH (os.pathsep list)
    otherwise       → ValueError naming every place that was searched.

Caching: a loaded dialect is registered in sys.modules under a name derived from
its resolved path ("sigil_dialect_<name>_<hash of path>"), and load() returns
that registered module when the same file is loaded again. sys.modules is shared
by the whole process, so this holds even across separate copies of this module —
lint.py and render.py each exec their own copy of dialects.py, and both get the
same dialect module object for the same file. (Registration also lets a dialect
use dataclasses, typing.get_type_hints, pickle etc., which look the module up in
sys.modules.) The file is read once per process: edits to it need a new process.

Run directly (`dialects.py [SPEC]`) it prints the resolved dialect's NAME, or
reports an unknown dialect on stderr and exits 2.

The Dialect object is the loaded module itself. Every hook is OPTIONAL — a
missing attribute means "no extension". Hooks named as functions return lists;
upper-case attributes are data.

  NAME: str
      The dialect's name (defaults to the name it was loaded by).

  -- lint ------------------------------------------------------------------
  KNOWN_MODIFIERS: set[str]
      Modifiers added to the core allowlist. They are accepted silently and are
      offered by the unknown-modifier diagnostic (SGL040) as a "Did you mean" or
      "Known:" hint.
  DEFERRED_MODIFIERS: set[str]
      Modifiers the dialect validates ITSELF (placement rules etc.): the core
      allowlist never reports them as unknown, and does not list them as known.
  lint_prepasses() -> [fn(lines, result) -> lines]
      Line-count-preserving rewrites run after the core pre-passes (block-string
      folding) and before every core rule — e.g. stripping dialect comment forms
      or masking dialect-only syntax down to plain glyphs.
  lint_passes() -> [fn(lines, result) -> None]
      Extra rules, run after the core rules on the same (pre-passed) lines.
  lint_glyph_masks() -> [fn(line) -> line]
      Length-preserving masks applied before the core glyph scans (actor-as-state,
      prose-verb) so dialect glyph syntax is not mis-read as core glyphs.
  lint_principal_scanners() -> [fn(line) -> (names, masked_line)]
      Contribute declared entity names from dialect glyph syntax to the
      permission-graph closed-reference check (SGL143), returning the line with
      that syntax masked so the core glyph scan does not also read it.
  lint_payload_checks() -> [fn(site, result) -> None]
      Called for every `: payload` segment the core payload rule inspects, after
      the core checks for it. `site` has: line_no, value (the payload text with
      trailing modifiers peeled), tags (the peeled @-modifiers, source order),
      kind (the core classification: value / ext-op / ext-op-bad / map / entity /
      int-op / opaque), known_modifiers (core ∪ dialect allowlist).
  DECLARATION_BLOCKS: [(compiled_regex, on_raw: bool)]
      Openers of `name { … }` blocks whose bodies are DECLARATIONS, not flows.
      The core payload rule skips their bodies and render draws nothing for them.
      `on_raw=True` matches the raw stripped line (use it for markers that begin
      with `#`, which comment stripping would erase); otherwise the
      comment-stripped line. The body ends when its braces balance.
  BLOCK_KEYWORDS: set[str]
      Extra statement-leading block keywords (alongside state/loop/parallel/
      branch) whose header line carries no flow payload.

  -- render ----------------------------------------------------------------
  render_prepasses() -> [fn(lines) -> lines]
      Line-count-preserving rewrites run after the core block-string pre-pass.
  render_line_strips() -> [fn(line) -> line]
      Applied first, to every flow line, inside render.extract_flows.
  render_tokenizers() -> [fn(s, i, prev_was_glyph, layer, Node)
                          -> None | (tokens, end, prev_was_glyph)]
      Glyph-tokenizer extensions, tried (in order) at each position before the
      core arrow / join / glyph rules. Return None to decline; otherwise the
      tokens to append (`("glyph", node)` built with the passed `Node` class, or
      `("arrow", kind)`), the index to resume at, and the new prev_was_glyph.
      Dialect-specific node metadata goes in `Node.attrs` (a free-form dict).
  NODE_KINDS: {kind: spec}
      Extra node kinds (`Node.kind` stays a plain string) a tokenizer may produce,
      and how viewers draw them. `spec` is a dict:
        "open", "close"    textual brackets for the kind (e.g. "[[", "]]") —
                           how a text viewer frames the label;
        "mermaid_shape"    (open, close) Mermaid node-shape delimiters;
        "mermaid_class"    Mermaid class name for nodes of this kind;
        "classdef"         Mermaid style body for that class (`fill:…,stroke:…`);
        "color"            a hex colour for viewers (e.g. "#F06292");
        "border"           a border hint for viewers: "single" | "double" |
                           "round" | "heavy";
        "label"            optional callable(node) -> str: the plain-text label
                           (default: node.name). Emitters escape it as needed.
  RENDER_ARROWS: {kind: mermaid_arrow}
      Extra arrow (edge) kinds a tokenizer may produce, and their Mermaid form.
  COMPOSITION_RELATIONS: str
      Extra composition-tree relation CHARACTERS (a string, joined onto the core
      set) lint accepts after a branch marker (core: `> & ? $ @`). The parser
      already places any of `>+#_^v$?!&@`. Only read when COMPOSITION_LINT is
      true. (Not a set of modifiers: a dialect's own modifier sets need other
      names.)
  COMMENT_MARKERS: list[str]
      Extra comment markers (regex sources) besides core `#`, matched at line start
      or after whitespace. Comments become notes on the node they describe.
  COMPOSITION_LINT: bool
      False when the dialect validates and masks branch markers itself; the core
      composition pre-pass (SGL110/SGL111) then stands down.
  MERMAID_COMPOSITION: str
      The default for render.render(composition=…) when the caller passes none:
      "subgraphs" (core default — composition trees as nested subgraphs, one
      node per occurrence), "edges" (one node per name, dotted relation edges)
      or "none" (composition trees are not drawn).

This module is standard-library only.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
import types
from pathlib import Path

Dialect = types.ModuleType

_HERE = Path(__file__).resolve().parent


def _candidates(name: str) -> list[Path]:
    out = [_HERE.parent / f"sigil-{name}" / "dialect.py"]
    for d in os.environ.get("SIGIL_DIALECT_PATH", "").split(os.pathsep):
        if d:
            out.append(Path(d) / f"sigil-{name}" / "dialect.py")
            out.append(Path(d) / name / "dialect.py")
    return out


def _module_name(path: Path) -> str:
    """A sys.modules key unique to the resolved path: the readable part alone
    could collide ("a-b" and "a_b"), so a hash of the path is appended."""
    safe = "".join(c if c.isalnum() else "_" for c in _name_of(path))
    digest = hashlib.sha1(str(path).encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    return f"sigil_dialect_{safe}_{digest}"


def _load_file(path: Path, name: str) -> Dialect:
    path = path.resolve()
    modname = _module_name(path)
    cached = sys.modules.get(modname)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(modname, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"sigil dialect {name!r}: cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod          # before exec: dataclasses etc. look it up
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(modname, None)
        raise
    if not getattr(mod, "NAME", None):
        mod.NAME = name
    return mod


def _name_of(p: Path) -> str:
    """The dialect name implied by a file path: its folder for `dialect.py`,
    else the file's stem; a leading "sigil-" is dropped."""
    raw = p.parent.name if p.name == "dialect.py" else p.stem
    return raw.removeprefix("sigil-")


def load(spec: str | None) -> Dialect | None:
    """Resolve and load a dialect (see the module docstring). Returns None for
    core Sigil; raises ValueError for an unknown or malformed dialect name."""
    if spec is None:
        spec = os.environ.get("SIGIL_DIALECT", "")
    spec = spec.strip()
    if not spec:
        return None
    p = Path(spec).expanduser()
    if p.is_file():
        return _load_file(p, _name_of(p))
    if p.is_dir() and (p / "dialect.py").is_file():
        return _load_file(p / "dialect.py", p.name.removeprefix("sigil-"))
    name = spec.removeprefix("sigil-")
    seps = {"/", os.sep} | ({os.altsep} if os.altsep else set())
    if not name or any(s in name for s in seps) or ".." in name:
        raise ValueError(
            f"unknown sigil dialect {spec!r}: not a dialect file or directory, and "
            "not a plain dialect name (no path separators or '..')."
        )
    tried = _candidates(name)
    for cand in tried:
        if cand.is_file():
            return _load_file(cand, name)
    raise ValueError(
        f"unknown sigil dialect {spec!r}: not a dialect file, and none of "
        + ", ".join(str(t) for t in tried)
        + " exists (set SIGIL_DIALECT_PATH to add search directories)."
    )


# There is no shared hook reader here: lint.py and render.py each define their
# own `_hook(dialect, name, default)` (callable hooks are called, data hooks
# returned as-is), since each loads this module only on demand.


def main(argv: list[str]) -> int:
    try:
        d = load(argv[0] if argv else None)
    except ValueError as exc:
        print(f"dialects.py: {exc}", file=sys.stderr)
        return 2
    print(getattr(d, "NAME", None) if d else "(core sigil — no dialect)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
