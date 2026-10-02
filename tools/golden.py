#!/usr/bin/env python3
"""
golden.py — golden outputs: every input drawn every way, kept under tests/golden/.

    tools/golden.py --check            # exit 1 if any drawing differs from its golden
    tools/golden.py --check --diff     # … and print a unified diff of each difference
    tools/golden.py --update           # rewrite tests/golden/ from the current code

Inputs: `site/examples/*.sigil`, the FIXTURES under `tests/fixtures/`, and every Sigil
block of examples.md (each fenced block that isn't a ```text drawing), named
`examples-NN[-slug]` in document order (the slug from the block's first
`--- name ---` header).

Each input gets a directory `tests/golden/<input>/` with one file per variant:

- `graph-<v>.txt` / `tree-<v>.txt` — exactly what
  `view.py <input>.sigil --once --color never --no-lint --width 100 [--tree] <flags>`
  prints, for <v> in: default (lint on: the summary line ends in the lint result),
  payloads (--payloads), notes-markers (--notes markers), notes-callouts
  (--notes callouts), depth-all (--depth all), access (--access), mods (--mods),
  width-60 (--width 60), color (--color always);
- `mermaid.txt` — what `render.py <input>.sigil` prints.

Drawings are made in-process (view.once, its stdout captured) with the built-in
`sigil` theme and no dialect, so $SIGIL_THEME / $SIGIL_DIALECT don't leak in. The
CLI re-runs itself with PYTHONHASHSEED=0: a drawing must not depend on set order,
but if one does, the goldens still stay stable (see HASH_SEED).
tests/test_golden.py runs the same check.

Standard library only.
"""
from __future__ import annotations

import argparse
import contextlib
import difflib
import importlib.util
import io
import os
import re
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = ROOT / "tests" / "golden"
THEME = "sigil"
WIDTH = 100                     # view.py's --once width when stdout isn't a terminal
NARROW = 60
ALL_DEPTH = "all"
# Set iteration order (string hashing) must not change a drawing; pinning the seed
# keeps the goldens stable while a drawing that still depends on it gets fixed.
HASH_SEED = "0"
# Fixtures drawn alongside the site examples (by stem, so each names its own directory).
FIXTURES = ("coverage.sigil", "executions.sigil")


# ---------------------------------------------------------------------------
# Variants — one drawing each
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Variant:
    """One way of drawing an input: the view.once() options (and their CLI flags)."""
    name: str
    tree: bool = False
    depth: int | str = 1        # a number, or ALL_DEPTH
    payloads: bool = False
    notes: str = "off"
    access: bool = False
    mods: bool = False
    width: int = WIDTH
    colour: bool = False
    lint: bool = False


def _variants() -> tuple[Variant, ...]:
    flavours = (
        Variant("default", lint=True),
        Variant("payloads", payloads=True),
        Variant("notes-markers", notes="markers"),
        Variant("notes-callouts", notes="callouts"),
        Variant("depth-all", depth=ALL_DEPTH),
        Variant("access", access=True),
        Variant("mods", mods=True),
        Variant("width-60", width=NARROW),
        Variant("color", colour=True),
    )
    return tuple(replace(v, name=f"{view}-{v.name}", tree=view == "tree")
                 for view in ("graph", "tree") for v in flavours)


VARIANTS = _variants()
MERMAID = "mermaid"


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Input:
    name: str                   # the golden directory, and the drawn file's stem
    text: str


_FENCE = re.compile(r"^```([a-z]*)\n(.*?)^```", re.S | re.M)
_HEADER = re.compile(r"^\s*---\s*(.+?)\s*---\s*$", re.M)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def examples_inputs(markdown: str) -> list[Input]:
    """The Sigil blocks of a Markdown document (fenced blocks other than ```text
    drawings), named `examples-NN[-slug]` in order."""
    out = []
    blocks = [m.group(2) for m in _FENCE.finditer(markdown) if m.group(1) != "text"]
    for k, block in enumerate(blocks, 1):
        header = _HEADER.search(block)
        slug = _slug(header.group(1)) if header else ""
        out.append(Input(f"examples-{k:02d}" + (f"-{slug}" if slug else ""), block))
    return out


def collect_inputs(root: Path) -> list[Input]:
    """Every golden input under the repo `root`. Raises ValueError on a name clash."""
    files = sorted((root / "site" / "examples").glob("*.sigil"))
    files += [root / "tests" / "fixtures" / name for name in FIXTURES]
    inputs = [Input(p.stem, p.read_text(encoding="utf-8")) for p in files]
    inputs += examples_inputs((root / "examples.md").read_text(encoding="utf-8"))
    names = [i.name for i in inputs]
    clash = sorted({n for n in names if names.count(n) > 1})
    if clash:
        raise ValueError(f"golden inputs share a name: {', '.join(clash)}")
    return inputs


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def load_view(root: Path):
    """A private instance of the repo's view.py (its own theme state), themed THEME.
    view.render is the render.py it loaded."""
    spec = importlib.util.spec_from_file_location("sigil_golden_view", root / "view.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod    # dataclasses resolve string annotations via sys.modules
    spec.loader.exec_module(mod)
    mod.use_theme(THEME)
    return mod


def draw(view, path: Path, v: Variant) -> str:
    """What `view.py path --once` prints for variant `v`."""
    depth = view.ALL_DEPTH if v.depth == ALL_DEPTH else v.depth
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        view.once(path, depth, v.payloads, v.lint, dialect=None, colour=v.colour,
                  tree=v.tree, notes=v.notes, width=v.width, access=v.access,
                  mods=v.mods)
    return buf.getvalue()


def draw_input(view, workdir: Path, inp: Input) -> dict[str, str]:
    """Every variant of one input, keyed `<input>/<variant>.txt`. The input is
    written to `workdir/<name>.sigil` (view.once reads a file; its name shows in
    the summary line)."""
    path = workdir / f"{inp.name}.sigil"
    path.write_text(inp.text, encoding="utf-8")
    out = {f"{inp.name}/{v.name}.txt": draw(view, path, v) for v in VARIANTS}
    out[f"{inp.name}/{MERMAID}.txt"] = view.render.render(inp.text, dialect=None) + "\n"
    return out


def draw_all(root: Path, only: str | None = None) -> dict[str, str]:
    """Every golden drawing of the repo at `root` (only input `only`, when given)."""
    view = load_view(root)
    inputs = [i for i in collect_inputs(root) if only is None or i.name == only]
    out: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for inp in inputs:
            out.update(draw_input(view, Path(tmp), inp))
    return out


# ---------------------------------------------------------------------------
# Comparing and writing
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Drift:
    """How drawings differ from the goldens (each a sorted list of relative paths)."""
    missing: list[str]          # drawn, no golden yet
    changed: list[str]          # drawn differently from the golden
    stale: list[str]            # a golden nothing draws any more

    def __bool__(self) -> bool:
        return bool(self.missing or self.changed or self.stale)

    def lines(self) -> list[str]:
        return ([f"missing  {p}" for p in self.missing] + [f"changed  {p}" for p in self.changed]
                + [f"stale    {p}" for p in self.stale])


def read_goldens(golden_dir: Path, only: str | None = None) -> dict[str, str]:
    base = golden_dir / only if only else golden_dir
    return {p.relative_to(golden_dir).as_posix(): p.read_text(encoding="utf-8")
            for p in sorted(base.rglob("*.txt"))}


def compare(golden: dict[str, str], drawn: dict[str, str]) -> Drift:
    return Drift(missing=sorted(drawn.keys() - golden.keys()),
                 changed=sorted(k for k in drawn.keys() & golden.keys() if drawn[k] != golden[k]),
                 stale=sorted(golden.keys() - drawn.keys()))


def unified(path: str, golden: str, drawn: str) -> str:
    return "".join(difflib.unified_diff(golden.splitlines(True), drawn.splitlines(True),
                                        f"golden/{path}", f"drawn/{path}"))


def write_goldens(golden_dir: Path, drawn: dict[str, str], stale: list[str]) -> None:
    """Write every drawing and delete the stale goldens (and emptied directories)."""
    for rel, text in drawn.items():
        p = golden_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    for rel in stale:
        p = golden_dir / rel
        p.unlink()
        if not any(p.parent.iterdir()):
            p.parent.rmdir()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def pin_hash_seed(argv: list[str]) -> None:
    """Re-run this script with PYTHONHASHSEED=HASH_SEED unless it already is."""
    if os.environ.get("PYTHONHASHSEED") != HASH_SEED:
        env = {**os.environ, "PYTHONHASHSEED": HASH_SEED}
        os.execve(sys.executable, [sys.executable, str(Path(__file__).resolve()), *argv], env)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Golden outputs of view.py / render.py.")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="exit 1 if any drawing differs")
    mode.add_argument("--update", action="store_true", help="rewrite tests/golden/")
    ap.add_argument("--diff", action="store_true", help="--check: print unified diffs")
    ap.add_argument("--only", metavar="INPUT", help="one input (a tests/golden/ directory name)")
    a = ap.parse_args(argv)
    try:
        drawn = draw_all(ROOT, a.only)
    except ValueError as exc:
        print(f"golden.py: {exc}", file=sys.stderr)
        return 2
    if a.only and not drawn:
        print(f"golden.py: no input named {a.only!r}", file=sys.stderr)
        return 2
    golden = read_goldens(GOLDEN_DIR, a.only)
    drift = compare(golden, drawn)
    for line in drift.lines():
        print(line)
    if a.update:
        write_goldens(GOLDEN_DIR, drawn, drift.stale)
        print(f"golden: {len(drawn)} drawing(s) written, {len(drift.stale)} stale removed")
        return 0
    if a.diff:
        for rel in drift.changed:
            print(unified(rel, golden[rel], drawn[rel]), end="")
    print(f"golden: {len(drawn)} drawing(s), "
          + ("all match" if not drift else f"{len(drift.lines())} differ"))
    return 1 if drift else 0


if __name__ == "__main__":
    pin_hash_seed(sys.argv[1:])
    sys.exit(main())
