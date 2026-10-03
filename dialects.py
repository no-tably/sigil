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
  ARROW_TARGET_WORDS: set[str]
      Bare words the dialect reads as an arrow's destination (`<go> -> word`).
      Core lint's dangling-arrow rule (SGL130) accepts them after an arrow; any
      other bare word there is still an arrow with no destination.

  -- render ----------------------------------------------------------------
  render_prepasses() -> [fn(lines) -> lines]
      Line-count-preserving rewrites run after the core block-string pre-pass.
      An expansion body is read in one pass, so a body's line is not re-run
      through them; only a line the body reads rewritten (a header's text after
      `{`, a closing line's text before `}`) is, on its own: a pass must leave its
      own output unchanged.
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
      A marker may not claim a reserved core marker (`#=`, the decorated
      acknowledgement — RFC 0003 Q7): load() refuses such a dialect.
  COMPOSITION_LINT: bool
      False when the dialect validates and masks branch markers itself; the core
      composition pre-pass (SGL110/SGL111) then stands down.
  MERMAID_COMPOSITION: str
      The default for render.render(composition=…) when the caller passes none:
      "subgraphs" (core default — composition trees as nested subgraphs, one
      node per occurrence), "edges" (one node per name, dotted relation edges)
      or "none" (composition trees are not drawn).

  -- check (the rule-pack hook; catalog §1 CG6, §1 MG16) -------------------------
  check_rules(api) -> [api.Rule]
      Composition rules the dialect adds to check.py's registry. `api` is the
      check module (its Rule and Hit records), as for core rule modules. Ids use
      the dialect's own prefix; ids and names may not reuse a core one.
  INV_HEADS: set[str]
      `@inv` heads the dialect's rules recognise (e.g. "breaker"), beside the
      core list. A core head may not be redefined.
  READ_VERBS: set[str]
      Verbs read as store reads (a store call `get(…)` reads), beside the core list.
  policy_words(api) -> [api.PolicyWord]
      Resilience words a comment may state as prose (policy-in-prose), beside the
      core list.
  LINT_CODES: set[str]
      Every diagnostic code the dialect's lint passes emit. None may be a core
      lint code or a core check id: core lint owns its codes (e.g. SGL120–188).

  rule_pack(dialect, api) reads these hooks into a RulePack; checked_pack()
  also refuses a pack whose names clash with the core's (CoreNames, supplied by
  the caller, since this module imports no core tool).

This module is standard-library only.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import sys
import types
from pathlib import Path
from typing import Iterable, NamedTuple, Optional

Dialect = types.ModuleType

_HERE = Path(__file__).resolve().parent

# Comment markers the core reserves: `#=` is the decorated acknowledgement
# (RFC 0003 Q7). A dialect's COMMENT_MARKERS may not claim one.
RESERVED_MARKERS = ("#=",)


class DialectError(ValueError):
    """A dialect breaks a core reservation (a reserved marker, a core name)."""


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
    problems = marker_problems(_hook(mod, "COMMENT_MARKERS"))
    if problems:
        sys.modules.pop(modname, None)
        raise DialectError(f"sigil dialect {mod.NAME!r}: " + "; ".join(problems))
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


# lint.py and render.py each define their own `_hook(dialect, name, default)`
# (callable hooks are called, data hooks returned as-is), since each loads this
# module only on demand. The reader below serves this module's own checks.

def _hook(dialect, name: str, default=(), *args):
    """A dialect hook's value: a callable hook is called with `args`, a data hook
    returned as-is, a missing one (or no dialect) gives `default`."""
    val = getattr(dialect, name, None) if dialect is not None else None
    if val is None:
        return default
    return val(*args) if callable(val) else val


# ---------------------------------------------------------------------------
# Core reservations: markers and names a dialect may not claim
# ---------------------------------------------------------------------------

def marker_problem(source: str, reserved: Iterable[str] = RESERVED_MARKERS) -> Optional[str]:
    """Why a COMMENT_MARKERS regex source may not be used, or None. A marker
    claims a reserved one when, matched where a comment may start, it consumes
    the whole reserved marker (`#=`, `#[=+]`, `#.` all do; `-//` does not)."""
    try:
        rx = re.compile(f"(?:{source})")
    except re.error as exc:
        return f"comment marker {source!r} is not a valid regex ({exc})"
    for mark in reserved:
        m = rx.match(f"{mark} name")
        if m and m.end() >= len(mark):
            return (f"comment marker {source!r} claims `{mark}`, which the core "
                    "reserves for acknowledgements")
    return None


def marker_problems(sources: Iterable[str]) -> list[str]:
    """marker_problem for every source, in order (None dropped)."""
    return [p for p in (marker_problem(s) for s in sources) if p]


class CoreNames(NamedTuple):
    """What the core already names. The caller supplies it (lint's codes, the
    check catalog, the recognised `@inv` heads): this module imports no tool."""
    lint_codes: frozenset = frozenset()
    rule_ids: frozenset = frozenset()
    rule_names: frozenset = frozenset()
    inv_heads: frozenset = frozenset()


class RulePack(NamedTuple):
    """A dialect's contribution to check.py (see the module docstring)."""
    rules: tuple = ()
    inv_heads: frozenset = frozenset()
    read_verbs: frozenset = frozenset()
    policy_words: tuple = ()
    lint_codes: frozenset = frozenset()


def rule_pack(dialect, api) -> RulePack:
    """Read a dialect's check hooks; an empty pack for no dialect."""
    return RulePack(
        rules=tuple(_hook(dialect, "check_rules", (), api)),
        inv_heads=frozenset(_hook(dialect, "INV_HEADS")),
        read_verbs=frozenset(_hook(dialect, "READ_VERBS")),
        policy_words=tuple(_hook(dialect, "policy_words", (), api)),
        lint_codes=frozenset(_hook(dialect, "LINT_CODES")))


def name_problems(pack: RulePack, core: CoreNames) -> list[str]:
    """Every place a pack reuses a core name, sorted. Core ids are lint codes
    and check ids alike: a dialect code or rule id may be neither."""
    core_ids = core.lint_codes | core.rule_ids
    out = [f"lint code {c} is a core code" for c in pack.lint_codes & core_ids]
    for rule in pack.rules:
        if rule.id in core_ids:
            out.append(f"rule id {rule.id} is a core id")
        if rule.name in core.rule_names:
            out.append(f"rule {rule.id}: `{rule.name}` is a core rule name")
    out += [f"@inv head `{h}` is a core head" for h in pack.inv_heads & core.inv_heads]
    return sorted(out)


def checked_pack(dialect, api, core: CoreNames) -> RulePack:
    """The dialect's rule pack, or DialectError naming every clash with the core
    (reserved markers included, for a dialect not loaded through load())."""
    pack = rule_pack(dialect, api)
    problems = (marker_problems(_hook(dialect, "COMMENT_MARKERS"))
                + name_problems(pack, core))
    if problems:
        name = getattr(dialect, "NAME", "?")
        raise DialectError(f"sigil dialect {name!r}: " + "; ".join(problems))
    return pack


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        d = load(argv[0] if argv else None)
    except ValueError as exc:
        print(f"dialects.py: {exc}", file=sys.stderr)
        return 2
    print(getattr(d, "NAME", None) if d else "(core sigil — no dialect)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
