#!/usr/bin/env python3
"""
golden.py — golden outputs: every input drawn every way, kept under tests/golden/.

    tools/golden.py --check            # exit 1 if any drawing differs from its golden
    tools/golden.py --check --diff     # … and print a unified diff of each difference
    tools/golden.py --update           # rewrite tests/golden/ from the current code

Inputs: `site/examples/*.sigil`, the FIXTURES under `tests/fixtures/`, and every Sigil
block of examples.md (each fenced block that isn't a ```text drawing), named
`examples-NN[-slug]` in document order (the slug from the block's first
`--- name ---` header). A block that repeats a site example word for word (the
URL shortener opening examples.md) is drawn once, under the site example's name,
and takes no number.

Each input gets a directory `tests/golden/<input>/` with one file per variant:

- `graph-<v>.txt` / `tree-<v>.txt` / `flow-<v>.txt` — exactly what
  `sigil view <input>.sigil --once --color never --no-lint --width 100 [--tree|--flow] <flags>`
  prints, for <v> in: default (lint on: the summary line ends in the lint result),
  payloads (--payloads), notes-markers (--notes markers), notes-callouts
  (--notes callouts), depth-all (--depth all), access (--access), mods (--mods),
  width-60 (--width 60), color (--color always); and for the flow view alone
  width-80 / width-50 (--width 80 / 50 --payloads --mods --notes markers: the
  wrap ladder's hung chips and bands);
- `run-<v>.txt` — the run view (`--run`), for the site examples and the
  executions fixture only: run-default (the happy run, no scenario chosen,
  --width 140, lint on), run-sim (the first deviation after `happy`, its final
  frame, --sim NAME --width 140; the happy one when there is none; the run in
  words, its `tNNN …` lines, left out — tests/ holds no task-like ids, and the
  path and outcome stay), run-width-80
  (the happy run at --width 80: notes shortened or below, bands);
- `run-json-depth-<d>.txt` — what `sigil view <input>.sigil --run --json --depth <d>`
  prints (the happy run's timeline as JSON), for RUN_JSON_INPUTS at RUN_JSON_DEPTHS;
- `mermaid.txt` — what `sigil export <input>.sigil --mermaid` prints.

The export variant: for each of EXPORT_INPUTS, `tests/golden/export/<input>/` holds
every file `sigil export <input>.sigil --out DIR` writes into an empty DIR (the index,
a folder per system, manifest.json), byte for byte. `--only export` checks just
these. No input may be named `export`.

Drawings are made in-process (sigil.present.app.once, its stdout captured) with the
built-in `sigil` theme and no dialect, so $SIGIL_THEME / $SIGIL_DIALECT don't leak in;
the theme applied before is put back afterwards. The
CLI re-runs itself with PYTHONHASHSEED=0: a drawing must not depend on set order,
but if one does, the goldens still stay stable (see HASH_SEED).
tests/test_golden.py runs the same check.

Standard library only.
"""
from __future__ import annotations

import argparse
import contextlib
import difflib
import io
import os
import re
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sigil import cli                           # noqa: E402  (the package sits at ROOT)
from sigil.core import parse                    # noqa: E402
from sigil.core.graph import ALL_DEPTH as GRAPH_ALL_DEPTH  # noqa: E402
from sigil.model import sim as simulator        # noqa: E402
from sigil.present import app, kit              # noqa: E402
from sigil.publish import mermaid               # noqa: E402

GOLDEN_DIR = ROOT / "tests" / "golden"
THEME = "sigil"
WIDTH = 100                     # `sigil view --once` width when stdout isn't a terminal
NARROW = 60
FLOW_WRAPS = (80, 50)           # the flow view wrapped, chips and notes on
RUN_WIDE, RUN_NARROW = 140, 80  # the run view: a wide pane, and one that wraps
RUN_INPUTS = ("executions",)    # beside the site examples, the inputs drawn in the run view
NEXT_SCENARIO = "@next"         # Variant.sim: the first deviation after `happy`
RUN_JSON_INPUTS = ("02-shop",)  # the inputs whose `--run --json` is kept, at each RUN_JSON_DEPTHS
RUN_JSON_DEPTHS = (0, 1)
ALL_DEPTH = "all"
# Set iteration order (string hashing) must not change a drawing; pinning the seed
# keeps the goldens stable while a drawing that still depends on it gets fixed.
HASH_SEED = "0"
_BEAT = re.compile(r"t\d{3} ")       # a line of the run in words (app.beat_line)
# Fixtures drawn alongside the site examples (by stem, so each names its own directory).
FIXTURES = ("coverage.sigil", "executions.sigil")
EXPORT_DIR = "export"           # tests/golden/export/<input>/: what `sigil export` writes
EXPORT_INPUTS = ("07-export",)  # the inputs exported (each a ready #!spec document)
GOLDEN_SUFFIXES = (".txt", ".md", ".json")   # the files a golden directory holds


# ---------------------------------------------------------------------------
# Variants — one drawing each
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Variant:
    """One way of drawing an input: the app.once() options (and their CLI flags)."""
    name: str
    view: str = "graph"         # "graph" | "tree" | "flow"
    depth: int | str | None = None  # None: not given (as the CLI); a number, or ALL_DEPTH
    payloads: bool = False
    notes: str = "off"
    access: bool = False
    mods: bool = False
    width: int = WIDTH
    colour: bool = False
    lint: bool = False
    sim: str | None = None      # a scenario (NEXT_SCENARIO: the first deviation after happy)
    json: bool = False          # `--run --json` (the timeline as JSON), not a drawing
    inputs: tuple[str, ...] | None = None   # only these inputs (None: as the view says)


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
    wraps = tuple(Variant(f"flow-width-{w}", view="flow", width=w, payloads=True, mods=True,
                          notes="markers") for w in FLOW_WRAPS)
    runs = (Variant("run-default", view="run", width=RUN_WIDE, lint=True),
            Variant("run-sim", view="run", width=RUN_WIDE, sim=NEXT_SCENARIO),
            Variant("run-width-80", view="run", width=RUN_NARROW))
    run_json = tuple(Variant(f"run-json-depth-{d}", view="run", depth=d, json=True,
                             inputs=RUN_JSON_INPUTS) for d in RUN_JSON_DEPTHS)
    return tuple(replace(v, name=f"{view}-{v.name}", view=view)
                 for view in ("graph", "tree", "flow") for v in flavours) + wraps + runs + run_json


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


def examples_inputs(markdown: str, drawn: frozenset[str] = frozenset()) -> list[Input]:
    """The Sigil blocks of a Markdown document (fenced blocks other than ```text
    drawings), named `examples-NN[-slug]` in order. Blocks whose text is in `drawn`
    (already an input) are left out and not counted."""
    out = []
    blocks = [m.group(2) for m in _FENCE.finditer(markdown)
              if m.group(1) != "text" and m.group(2) not in drawn]
    for k, block in enumerate(blocks, 1):
        header = _HEADER.search(block)
        slug = _slug(header.group(1)) if header else ""
        out.append(Input(f"examples-{k:02d}" + (f"-{slug}" if slug else ""), block))
    return out


def run_inputs(root: Path) -> frozenset:
    """The inputs drawn in the run view: the site examples and RUN_INPUTS."""
    return frozenset([p.stem for p in (root / "site" / "examples").glob("*.sigil")]
                     + list(RUN_INPUTS))


def collect_inputs(root: Path) -> list[Input]:
    """Every golden input under the repo `root`. Raises ValueError on a name clash."""
    files = sorted((root / "site" / "examples").glob("*.sigil"))
    files += [root / "tests" / "fixtures" / name for name in FIXTURES]
    inputs = [Input(p.stem, p.read_text(encoding="utf-8")) for p in files]
    inputs += examples_inputs((root / "examples.md").read_text(encoding="utf-8"),
                              drawn=frozenset(i.text for i in inputs))
    names = [i.name for i in inputs] + [EXPORT_DIR]
    clash = sorted({n for n in names if names.count(n) > 1})
    if clash:
        raise ValueError(f"golden inputs share a name: {', '.join(clash)}")
    return inputs


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def themed(spec: str):
    """Draw in theme `spec`; the theme applied before comes back on the way out
    (the package keeps one theme per process)."""
    before = dict(kit.THEME)
    kit.use_theme(spec)
    try:
        yield
    finally:
        kit.apply_theme(before)


def next_scenario(path: Path) -> str:
    """The first deviation after `happy` of the document at `path`: a listed
    scenario that starts no entry at a tick (an overlap, `Entry@t`, is not one);
    happy when there is none."""
    g = parse.parse_document(path.read_text(encoding="utf-8"))
    found = simulator.scenarios(simulator.canonical(g))
    return next((sc.name for sc in found[1:] if not sc.starts), found[0].name)


def draw(path: Path, v: Variant) -> str:
    """What `sigil view path --once` prints for variant `v`."""
    depth = GRAPH_ALL_DEPTH if v.depth == ALL_DEPTH else v.depth   # None stays not given
    sim = next_scenario(path) if v.sim == NEXT_SCENARIO else v.sim
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        if v.json:
            app.run_json(path, sim, dialect=None, depth=depth)
            return buf.getvalue()
        app.once(path, depth, v.payloads, v.lint, dialect=None, colour=v.colour,
                  notes=v.notes, width=v.width, access=v.access, mods=v.mods,
                  view=v.view, sim=sim)
    out = buf.getvalue()
    if sim is not None:                 # the run in words: tNNN … lines, left out
        out = "".join(ln for ln in out.splitlines(True) if not _BEAT.match(ln))
    return out


def drawn_in(v: Variant, inp: "Input", runs: frozenset) -> bool:
    """Whether input `inp` gets variant `v`: every input every view but the run
    view, which only the inputs named in `runs` get; a variant naming its
    `inputs` only those."""
    return ((v.view != "run" or inp.name in runs)
            and (v.inputs is None or inp.name in v.inputs))


def draw_input(workdir: Path, inp: Input, runs: frozenset = frozenset()) -> dict[str, str]:
    """Every variant of one input, keyed `<input>/<variant>.txt`. The input is
    written to `workdir/<name>.sigil` (app.once reads a file; its name shows in
    the summary line). `runs`: the inputs drawn in the run view too."""
    path = workdir / f"{inp.name}.sigil"
    path.write_text(inp.text, encoding="utf-8")
    out = {f"{inp.name}/{v.name}.txt": draw(path, v) for v in VARIANTS
           if drawn_in(v, inp, runs)}
    out[f"{inp.name}/{MERMAID}.txt"] = mermaid.render(inp.text, dialect=None) + "\n"
    return out


def draw_all(root: Path, only: str | None = None) -> dict[str, str]:
    """Every golden drawing of the repo at `root` (only input `only`, when given;
    EXPORT_DIR: only the exports)."""
    every = collect_inputs(root)
    inputs = [i for i in every if only is None or i.name == only]
    runs = run_inputs(root)
    out: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as tmp, themed(THEME):
        for inp in inputs:
            out.update(draw_input(Path(tmp), inp, runs))
        if only in (None, EXPORT_DIR):
            for inp in (i for i in every if i.name in EXPORT_INPUTS):
                out.update(export_input(Path(tmp), inp))
    return out


# ---------------------------------------------------------------------------
# Exporting
# ---------------------------------------------------------------------------

def export_input(workdir: Path, inp: Input) -> dict[str, str]:
    """Every file `sigil export <name>.sigil --out DIR` writes into an empty DIR,
    keyed `EXPORT_DIR/<input>/<path in DIR>`. Raises ValueError when the input
    does not export (not ready, or the folder could not be written)."""
    path = workdir / f"{inp.name}.sigil"
    path.write_text(inp.text, encoding="utf-8")
    out_dir = workdir / EXPORT_DIR / inp.name
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = cli.main(["export", str(path), "--out", str(out_dir)])
    if code != 0:
        raise ValueError(f"{inp.name} does not export (exit {code}):\n{buf.getvalue()}")
    return {f"{EXPORT_DIR}/{inp.name}/{p.relative_to(out_dir).as_posix()}":
            p.read_text(encoding="utf-8")
            for p in sorted(out_dir.rglob("*")) if p.is_file()}


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
            for p in sorted(base.rglob("*"))
            if p.is_file() and p.suffix in GOLDEN_SUFFIXES}


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
    ap = argparse.ArgumentParser(description="Golden outputs of sigil view / sigil export.")
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
