"""The `sigil` command: one entry point, a subcommand per tool.

    sigil lint FILE|- [--deep] [--dialect D]
    sigil check [FILE|-] [--mode M] [--k N] [--budget N] [--limit NAME=N] [--overlaps …] [--json] [--export] [--all-rules] [--rules]
    sigil view FILE [--once] [--graph|--tree|--flow|--run] [--sim S] …
    sigil view FILE --structure [--json]
    sigil export SPEC --out DIR [--name NAME] [--limit NAME=N] [--json] [--dry-run]
    sigil export FILE --mermaid [--depth N|all] [--composition subgraphs|edges|none]
    sigil export FILE --mermaid --spine [--name NAME]
    sigil frames draw FILE [--view V] [--depth N|all] [--width N] [--scenario S] [--limit NAME=N] …
    sigil frames follow CONTROL
    sigil themes [NAME|PATH] [--list]
    sigil highlight FILE|- [--theme NAME|PATH] [--dialect D] [--json]
    sigil highlight --stream [--theme NAME|PATH] [--dialect D]

Each subcommand imports its layer only when it runs, so `sigil lint` loads
neither the simulator nor the views. `main(argv, dialect=…)` is what a dialect's
wrapper calls: `dialect` becomes every subcommand's default `--dialect`.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path, PurePath

USAGE = __doc__.split("\n\n")[1].strip("\n")
ROOT = Path(__file__).resolve().parents[1]   # the folder holding the package and bin/sigil


# The name each command's messages and its usage line begin with (the Mermaid
# chart is `sigil export --mermaid`, so it speaks as `sigil export`).
SAID = {"lint": "sigil lint", "check": "sigil check", "view": "sigil view",
        "export": "sigil export", "mermaid": "sigil export", "frames": "sigil frames",
        "themes": "sigil themes", "highlight": "sigil highlight"}


def read_text(path: str) -> str:
    """The document at `path` (`-` = stdin, read as UTF-8). Raises OSError."""
    if path == "-":
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8")
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def load_dialect(name):
    """The dialect `name` (a name or a path; None: $SIGIL_DIALECT, else none).
    Raises ValueError naming what is wrong."""
    from sigil.core import dialects
    return dialects.load(name)


def say(cmd: str, message: str) -> None:
    """One of `cmd`'s messages on stderr, after its name (SAID)."""
    print(f"{SAID[cmd]}: {message}", file=sys.stderr)


def cannot_read(path: str, exc: OSError) -> str:
    return f"cannot read {path}: {exc.strerror or exc}"


def _name_flag(ap: argparse.ArgumentParser, where: str = "") -> None:
    ap.add_argument("--name", metavar="NAME", type=name_arg,
                    help="the top system's name (default: the file's stem)" + where)


def _dialect_flag(ap: argparse.ArgumentParser, dialect) -> None:
    ap.add_argument("--dialect", default=dialect,
                    help="dialect name or path (default: $SIGIL_DIALECT)")


# ---------------------------------------------------------------------------
# Flag types
# ---------------------------------------------------------------------------

def name_arg(value: str) -> str:
    """--name: the top system's name, not blank."""
    if not value.strip():
        raise argparse.ArgumentTypeError("the top system's name may not be blank")
    return value


def depth_arg(value: str) -> int:
    """--depth: a non-negative number, or `all` (the views and the Mermaid export)."""
    from sigil.core.graph import ALL_DEPTH
    if value == "all":
        return ALL_DEPTH
    try:
        depth = int(value)
    except ValueError:
        depth = -1
    if depth < 0:
        raise argparse.ArgumentTypeError(f"expected a number >= 0 or 'all', got {value!r}")
    return depth


def overlaps_arg(value: str):
    """--overlaps: off, listed, all, or N (all, at most N overlap runs)."""
    from sigil.analyse.check import OVERLAPS
    if value in OVERLAPS:
        return value
    if value.isdigit() and int(value) >= 1:
        return int(value)
    raise argparse.ArgumentTypeError(f"{value!r}: one of {', '.join(OVERLAPS)}, or a "
                                     "number of runs (at least 1)")


def width_arg(text: str) -> int:
    try:
        width = int(text)
    except ValueError:
        width = 0
    if width < 1:
        raise argparse.ArgumentTypeError(f"expected a number of columns >= 1, got {text!r}")
    return width


def frame_arg(text: str) -> int:
    """--frame N|last: N ≥ 0, or last (-1)."""
    if text == "last":
        return -1
    if not text.isdigit():
        raise argparse.ArgumentTypeError(f"expected a frame number >= 0 or last, got {text!r}")
    return int(text)


def unroll_arg(text: str) -> int:
    """--unroll N|all: N ≥ 1, or all (0: nothing folds)."""
    if text == "all":
        return 0
    try:
        n = int(text)
    except ValueError:
        n = 0
    if n < 1:
        raise argparse.ArgumentTypeError(f"expected a number >= 1 or all, got {text!r}")
    return n


# ---------------------------------------------------------------------------
# sigil lint — and --deep, which joins lint and check here, in the command
# (the lint layer never imports check)
# ---------------------------------------------------------------------------

def deep_lines(diagnostics: list, report) -> list:
    """The merged --deep listing: lint diagnostics and the check findings the
    mode shows, sorted by line (lint first on a line, each in its own order),
    then the acknowledged findings. `report` is a check.Report."""
    issues = ([(d.line, 0, d.format()) for d in diagnostics]
              + [(f.line, 1, f.line_text()) for f in report.shown])
    issues.sort(key=lambda row: row[:2])
    return [text for _line, _src, text in issues] + [
        f.accepted_text() for f in report.acknowledged]


def _report_lint(result, lint) -> int:
    """Print the plain lint report of `result` (a LintResult); its exit code."""
    if not result.diagnostics:
        print("sigil: OK (no issues)")
        return 0
    for d in result.diagnostics:
        print(d.format())
    print("\n" + lint.lint_summary(result), file=sys.stderr)
    return lint.exit_code(d.severity for d in result.diagnostics)


def _report_deep(result, report, lint, check) -> int:
    """Print the merged lint + check report; the worse exit code."""
    out = deep_lines(result.diagnostics, report)
    print("\n".join(out) if out else "sigil: OK (no issues, no findings)")
    print("\n" + lint.lint_summary(result) + "\n" + check.summary(report), file=sys.stderr)
    return max(lint.exit_code(d.severity for d in result.diagnostics), report.exit_code())


def _lint(argv: list, dialect) -> int:
    ap = argparse.ArgumentParser(prog=SAID["lint"], description="Lint a Sigil document.")
    ap.add_argument("file", help="a .sigil file, or - for stdin")
    _dialect_flag(ap, dialect)
    ap.add_argument("--deep", action="store_true",
                    help="also run the composition checks (sigil check) and merge the reports")
    a = ap.parse_args(argv)
    from sigil.analyse import lint
    try:
        loaded = load_dialect(a.dialect)
    except ValueError as exc:
        say("lint", str(exc))
        return 2
    try:
        text = read_text(a.file)
    except OSError as exc:
        say("lint", cannot_read(a.file, exc))
        return 2

    linted = lint.lint_reading(text, dialect=loaded)
    if not a.deep:
        return _report_lint(linted.result, lint)
    from sigil.analyse import check
    try:                                 # check judges lint's reading and model
        report = check.check(text, dialect=loaded, walk=linted.walk, graph=linted.graph)
    except ValueError as exc:            # a refused rule pack or registry
        say("lint", f"--deep: {exc}")
        return 2
    return _report_deep(linted.result, report, lint, check)


# ---------------------------------------------------------------------------
# sigil check
# ---------------------------------------------------------------------------

def _check_parser(dialect, check) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog=SAID["check"], description="Check a Sigil design's "
                                 "composition: risks it leaves undeclared.")
    ap.add_argument("file", nargs="?", help="a .sigil file, or - for stdin")
    ap.add_argument("--mode", choices=check.MODES, help="check as this mode")
    ap.add_argument("--k", type=int, help="failure combinations per scenario")
    ap.add_argument("--budget", type=int,
                    help="runs one exploration may make (deviations, then in spec the "
                         "state starts, then overlap runs)")
    ap.add_argument("--overlaps", type=overlaps_arg, metavar="off|listed|all|N",
                    help="overlap runs to make: none, the listed starts, every start "
                         "tick, or every tick but at most N runs (default: all in spec, "
                         "else off)")
    ap.add_argument("--limit", action="append", default=[], metavar="NAME=N",
                    help="raise one simulator limit (repeatable; e.g. depth=5)")
    ap.add_argument("--json", action="store_true", help="print one JSON object")
    ap.add_argument("--all", action="store_true", help="also print hidden findings")
    ap.add_argument("--export", action="store_true",
                    help="also check export readiness (SGC401 no-home, SGC402 "
                         "untyped-boundary)")
    ap.add_argument("--all-rules", action="store_true",
                    help="also run the rule groups the `#%%` kind line turns off")
    ap.add_argument("--rules", action="store_true",
                    help="list the rules (with each one's group) and exit")
    _dialect_flag(ap, dialect)
    return ap


def _limits(pairs: list):
    """The simulator bounds --limit NAME=N sets (None: none given). Raises ValueError."""
    if not pairs:
        return None
    from sigil.model import sim
    return sim.limits_from(pairs)


def _check(argv: list, dialect) -> int:
    from sigil.analyse import check
    ap = _check_parser(dialect, check)
    a = ap.parse_args(argv)
    if a.k is not None and a.k < 1:
        ap.error("--k must be at least 1")
    if a.budget is not None and a.budget < 1:
        ap.error("--budget must be at least 1")
    if not (a.rules or a.file):
        ap.error("a file is required (or --rules)")
    try:
        loaded = load_dialect(a.dialect)
        pack = check.dialect_pack(loaded)
        registry = check.default_registry(pack.rules, export=a.export or a.rules)
        limits = _limits(a.limit)
        text = None if a.rules else read_text(a.file)
    except check.RegistryError as exc:
        say("check", f"rule registry: {exc}")
        return 2
    except (ValueError, OSError) as exc:
        say("check", str(exc))
        return 2
    if a.rules:
        print("\n".join(check.registry_lines(registry)))
        return 0
    report = check.check(text, mode=a.mode, k=a.k, dialect=loaded, registry=registry,
                         pack=pack, budget=a.budget, limits=limits, overlaps=a.overlaps,
                         export=a.export, all_rules=a.all_rules)
    if a.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        out = check.format_lines(report, a.all)
        print("\n".join(out) if out else "sigil check: OK (no findings)")
        print(check.summary(report), file=sys.stderr)
    return report.exit_code()


# ---------------------------------------------------------------------------
# sigil view
# ---------------------------------------------------------------------------

def _view_parser(dialect, app) -> argparse.ArgumentParser:
    keys = ", ".join(f"{i} {v}" for i, v in enumerate(app.VIEWS, 1))
    ap = argparse.ArgumentParser(
        prog=SAID["view"],
        description="Draw a Sigil document in the terminal and redraw it on every save "
                    "(--once: print it once and exit). Four views, by their keys: "
                    f"{keys}; it starts in the {app.DEFAULT_VIEW} view.")
    ap.add_argument("file", type=Path, help="the Sigil file to draw")
    ap.add_argument("--depth", type=depth_arg, default=None, metavar="N|all",
                    help="how many levels of `X := { … }` expansions to draw "
                         "(default 1; all: every level); a run's narration and path "
                         "name the nodes drawn there and the run view folds deeper "
                         "lanes (with --sim NAME --json / --run --json: only "
                         "when given)")
    ap.add_argument("--payloads", action="store_true",
                    help="show what each flow carries: a chip on its edge (graph and flow "
                         "views), a list under the tree (tree view)")
    ap.add_argument("--no-lint", action="store_true",
                    help="leave out the lint problems under the drawing")
    ap.add_argument("--dialect", default=dialect, metavar="NAME",
                    help="a dialect to read the document with: a name or a path "
                         "(default: $SIGIL_DIALECT)")
    ap.add_argument("--once", action="store_true",
                    help="print the drawing and the lint once and exit, instead of "
                         "redrawing on every save (exit status 1 on a lint error)")
    ap.add_argument("--notes", choices=app.NOTE_MODES, default="off",
                    help="the document's comments: off (default), markers (#N on the "
                         "drawing, the notes listed under it) or callouts (tree view: "
                         "boxes in the left margin)")
    ap.add_argument("--compact", action="store_true",
                    help="tree view: no blank row between top-level parts")
    ap.add_argument("--no-triggers", action="store_true",
                    help="hide the wires from an event to the state it changes (dashed "
                         "edges in the graph view, lanes in the tree view)")
    ap.add_argument("--access", action="store_true",
                    help="draw who may read or write each store: dotted edges from the "
                         "principal to the store, headed r / w / b")
    ap.add_argument("--mods", action="store_true",
                    help="show modifiers (timeouts, retries, limits): on an edge's chip and "
                         "after a node's label")
    ap.add_argument("--events", choices=app.EVENT_MODES, default=None,
                    help="how an event that only passes through is drawn: land (each "
                         "sender wired straight to each receiver) or nodes (a box or row "
                         "of its own); default: land in the tree view, nodes in the others")
    views = ap.add_argument_group(
        "views", f"Start in one view (default: {app.DEFAULT_VIEW}); live, keys {keys} "
                 "switch between them and t steps to the next.").add_mutually_exclusive_group()
    views.add_argument("--graph", action="store_true",
                       help="graph (key 1): boxes and edges laid out top-down in layers")
    views.add_argument("--tree", action="store_true",
                       help="tree (key 2): the composition tree as an outline, each flow a "
                            "lane beside it")
    views.add_argument("--flow", action="store_true",
                       help="flow (key 3, the default): who calls whom, read left to right, "
                            "one column per call depth")
    views.add_argument("--run", action="store_true",
                       help="run (key 4): one simulated run as a timeline, a lane per "
                            "participant, time left to right (--sim's run, else the happy "
                            "path)")
    ap.add_argument("--unroll", type=unroll_arg, default=None, metavar="N|all",
                    help="run view: how many instances of one node to show before the rest "
                         f"fold into one row (default {app.RUN_UNROLL[0]}; all: none fold)")
    ap.add_argument("--layout", choices=app.LAYOUTS, default=app.LAYOUTS[0],
                    help="a drawing wider than the window: wrap (fit the width, grow "
                         "down), pan (keep its natural shape and scroll sideways) or auto "
                         "(default: whichever overflows less; --once: wrap)")
    ap.add_argument("--width", type=width_arg, default=None, metavar="N",
                    help="--once: fit the drawing to N columns (default: the terminal's "
                         f"width, or {app.ONCE_WIDTH} when the output is not a terminal)")
    ap.add_argument("--sim", default=None, metavar="SCENARIO",
                    help="simulate a run: happy (every default), a scenario's name, or "
                         "a+b to combine two scenarios. --once prints the run's last frame "
                         "(or --frame's), outcome and log; live, it starts with the run shown. list: the scenarios; "
                         "all: run every one and print a table of outcomes")
    ap.add_argument("--frame", type=frame_arg, default=None, metavar="N|last",
                    help="with --sim: the frame of the run to show (counting from 0) or "
                         "its last (past the end: the last). --once draws that frame in "
                         "any view (the run view: its playhead there); live, the run "
                         "starts there, paused unless --play")
    ap.add_argument("--play", action="store_true",
                    help="live, with --sim: start with the run playing")
    ap.add_argument("--limit", action="append", default=[], metavar="NAME=N",
                    help="with --sim: raise one of the simulator's bounds, e.g. "
                         "frames=5000 or depth=5 (repeat for more)")
    ap.add_argument("--json", action="store_true",
                    help="print JSON instead of a drawing. With --sim list / all: the "
                         "scenarios / every run's facts; with --sim SCENARIO: its facts, "
                         "the run in plain words and its log; with --run: the run's "
                         "timeline (lanes, spans, moves, marks)")
    ap.add_argument("--structure", action="store_true",
                    help="no drawing: the design read as units — each unit's members, "
                         "internal flows and dependencies, cycles, the parts that call "
                         "an actor, each part's reach, pass-throughs, units over 9 "
                         "members, a name declared in two units, writers per store "
                         "(with --json: as data); any mode, exit status 0")
    ap.add_argument("--checks", action="store_true",
                    help="mark the composition checks' findings (sigil check) on the drawing "
                         "and list them with their questions (live: key c toggles it)")
    ap.add_argument("--color", choices=("auto", "always", "never"), default="auto",
                    help="when to colour the output: auto (default: when it goes to a "
                         "terminal), always or never")
    ap.add_argument("--theme", default=None,
                    help="colour theme: a name in themes/ or a .yaml path (default: "
                         "$SIGIL_THEME, else the dialect's THEME, else sigil)")
    return ap


def _flag_problem(a, sim_batch: tuple) -> str | None:
    """Why the parsed view flags can't go together (None: they can)."""
    if a.structure and (a.sim is not None or a.run or a.frame is not None or a.play):
        return "--structure is a reading of its own: no --sim, --run, --frame or --play"
    if a.json and a.sim is None and not a.run and not a.structure:
        return "--json needs --sim (list, all or a scenario), --run or --structure"
    if (a.frame is not None or a.play) and (a.sim is None or a.sim in sim_batch):
        return "--frame and --play need --sim SCENARIO"
    return None


def _readable(path: Path) -> bool:
    """Whether path opens for reading; if not, say so on stderr. (The live view
    waits for the file instead: reload keeps the last view while it is missing.)"""
    try:
        path.open("rb").close()
    except OSError as exc:
        say("view", cannot_read(str(path), exc))
        return False
    return True


def _view(argv: list, dialect) -> int:
    from sigil.present import app, kit
    a = _view_parser(dialect, app).parse_args(argv)
    try:
        loaded = load_dialect(a.dialect)
        kit.use_theme(a.theme, loaded)     # --theme, $SIGIL_THEME, the dialect's THEME, sigil
        limits = _limits(a.limit)
    except ValueError as exc:
        say("view", str(exc))
        return 2
    problem = _flag_problem(a, app.SIM_BATCH)
    if problem:
        say("view", problem)
        return 2
    tty_out = sys.stdout.isatty()
    output = app.Output(
        once=a.once or not tty_out or not sys.stdin.isatty(),
        colour=a.color == "always" or (a.color == "auto" and tty_out),
        width=a.width or (shutil.get_terminal_size().columns if tty_out else app.ONCE_WIDTH))
    if (output.once or a.json or a.structure or a.sim in app.SIM_BATCH) \
            and not _readable(a.file):
        return 2
    try:
        return app.run(a, loaded, limits, output)
    except app.UnknownScenario as exc:     # the message lists the known ones
        say("view", f"--sim: {exc}")
        return 2


# ---------------------------------------------------------------------------
# sigil export — the export folder, or with --mermaid the document as a chart
# ---------------------------------------------------------------------------

# Both forms of `sigil export`, as the command's usage line (its --help and the
# message for a bad flag, in either form): the USAGE lines that start with it.
EXPORT_USAGE = "\n       ".join(line.strip() for line in USAGE.splitlines()
                                if line.strip().startswith("sigil export "))


def _export(argv: list, dialect) -> int:
    if "--mermaid" in argv:
        return _mermaid(argv, dialect)
    return _export_folder(argv, dialect)


def _export_folder(argv: list, dialect) -> int:
    ap = argparse.ArgumentParser(
        prog=SAID["export"], usage=EXPORT_USAGE,
        description="Export a ready Sigil spec as a build skeleton: a folder per "
                    "system, a file per component, manifest.json as the contract.",
        epilog="With --mermaid it draws FILE as a Mermaid chart instead "
               "(`sigil export FILE --mermaid --help`).")
    ap.add_argument("spec", help="a .sigil file whose mode line is #!spec")
    ap.add_argument("--out", required=True, metavar="DIR",
                    help="the export folder (empty, or an earlier export)")
    _name_flag(ap)
    _dialect_flag(ap, dialect)
    ap.add_argument("--json", action="store_true",
                    help="print the delta (what changed since the export in DIR) as JSON")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the delta and write nothing")
    ap.add_argument("--limit", action="append", default=[], metavar="NAME=N",
                    help="raise one simulator limit for the gate's check (repeatable; "
                         "e.g. frames=20000), as `sigil check` takes it: a run cut at "
                         "a limit blocks the export until raised or acknowledged")
    a = ap.parse_args(argv)
    from sigil.analyse import check, lint
    from sigil.publish import exporter
    if a.spec == "-":                        # the top system is named after the file
        say("export", "SPEC must be a file: its stem names the top system")
        return 2
    spec, out = Path(a.spec), Path(a.out)
    try:
        loaded = load_dialect(a.dialect)
        text = read_text(a.spec)
        passed = exporter.ready(text, loaded, lint, check, _limits(a.limit))
    except (ValueError, OSError) as exc:
        say("export", str(exc))
        return 2
    if passed.blocking:
        print("\n".join(passed.blocking))
        say("export", f"{spec.name} is not ready to export: {len(passed.blocking)} "
                      "blocking line(s); nothing written")
        return 2
    done = exporter.run(text, spec, out, loaded, a.json, a.dry_run, passed, name=a.name)
    if done.problem:
        say("export", done.problem)
    for name in done.kept:
        say("export", f"kept {out / name}/: it holds files sigil export did not "
                      "write (its system is gone)")
    print(done.printed, end="")
    return done.status


def stem_of(path: str) -> str:
    """The top system's name for a file (as `sigil export` names it); stdin's
    is `document`."""
    return "document" if path == "-" else PurePath(path).stem


def _mermaid(argv: list, dialect) -> int:
    ap = argparse.ArgumentParser(
        prog=SAID["mermaid"], usage=EXPORT_USAGE,
        description="Render a Sigil document as Mermaid.",
        epilog="Without --mermaid it exports a ready spec as a folder "
               "(`sigil export SPEC --out DIR`; `sigil export --help`).")
    ap.add_argument("file", help="a .sigil file, or - for stdin")
    ap.add_argument("--mermaid", action="store_true",
                    help="draw the document as a Mermaid chart (this form)")
    ap.add_argument("--depth", type=depth_arg, default=1,
                    help="expansion depth (N or 'all')")
    ap.add_argument("--composition", choices=("subgraphs", "edges", "none"), default=None,
                    help="composition trees as nested subgraphs (default), dotted "
                         "relation edges, or not at all")
    ap.add_argument("--spine", action="store_true",
                    help="group the chart by the export's systems (a subgraph per system)")
    _name_flag(ap, " (with --spine)")
    _dialect_flag(ap, dialect)
    a = ap.parse_args(argv)
    if a.name is not None and not a.spine:
        ap.error("--name names the top system of --spine; plain --mermaid has none")
    try:
        loaded = load_dialect(a.dialect)
    except ValueError as exc:
        say("mermaid", str(exc))
        return 2
    try:
        text = read_text(a.file)
    except OSError as exc:
        say("mermaid", cannot_read(a.file, exc))
        return 2
    if a.spine:
        from sigil.publish.spine import spine
        print(spine(text, a.name or stem_of(a.file), dialect=loaded))
    else:
        from sigil.publish import mermaid
        print(mermaid.render(text, depth=a.depth, dialect=loaded, composition=a.composition))
    return 0


# ---------------------------------------------------------------------------
# sigil frames — the hosts' drawings (draw) and the multiplexer split (follow)
# ---------------------------------------------------------------------------

FOLLOW_POLL_S = 0.3         # how often follow looks at CONTROL
CONTROL_PREFIX = "sigil-view-"   # a host's private directory for CONTROL (plugin logic.ts)
ALIVE_S = 1.0               # how often follow touches CONTROL.alive


def control_problem(path: Path) -> str | None:
    """Why CONTROL is not to be trusted, or None. CONTROL names the command line
    `sigil view` runs, and that can load a dialect (Python code), so it must be a
    regular file of this user's that no other user can write, in a directory of
    this user's that no other user can write (a host makes it in a private
    directory, 0700, with mode 0600). Unix only: elsewhere nothing is checked."""
    if not hasattr(os, "getuid"):
        return None
    uid = os.getuid()
    try:
        own = os.lstat(path)
        folder = os.stat(path.parent)
    except OSError as exc:
        return f"cannot read {exc.filename}: {exc.strerror or exc}"
    if not stat.S_ISREG(own.st_mode):
        return f"{path} is not a regular file (a link or a device)"
    for what, where, st in (("the control file", path, own),
                            ("its directory", path.parent, folder)):
        if st.st_uid != uid:
            return f"{what} {where} belongs to uid {st.st_uid}, not to you (uid {uid})"
        if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            return (f"{what} {where} can be written by other users "
                    f"(mode {stat.S_IMODE(st.st_mode):04o})")
    return None


def _refuse(control: Path, problem: str) -> None:
    say("frames", f"refusing {control}: {problem}. The control file names what "
                  "`sigil view` runs (a --dialect is Python code), so it must be yours "
                  "and writable by you alone (ctrl-c closes this split)")


def read_control(path: Path) -> list[str] | None:
    """The argv CONTROL asks for (None: unreadable or not a list of strings)."""
    try:
        argv = json.loads(path.read_text(encoding="utf-8")).get("argv")
    except (OSError, ValueError, AttributeError):
        return None
    if isinstance(argv, list) and argv and all(isinstance(a, str) for a in argv):
        return argv
    return None


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _stop(child) -> None:
    if child is not None and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def follow(control: Path, wait=lambda: signal.pause()) -> int:
    """The multiplexer split's loop: runs `sigil view` live with the argv in the
    JSON file CONTROL ({"argv": [...]}), restarts it whenever CONTROL changes,
    touches CONTROL.alive every second so the host can tell the split is still
    up, and exits when the view quits on its own (q) or the split closes —
    removing both files. A view that fails (a bad flag, an unreadable file)
    leaves its message on screen and the loop waiting.

    CONTROL is checked first (control_problem) and again before each request is
    run: one another user could write, or one not this user's, is refused on
    screen and nothing it asks is run. Refused at the start, follow writes and
    removes nothing and waits for the split to close (`wait`), so the message
    stays readable; it then exits 2."""
    for sig in (signal.SIGTERM, signal.SIGHUP):    # the split closed: unwind through finally
        signal.signal(sig, lambda *_: sys.exit(0))
    problem = control_problem(control)
    if problem is not None:
        _refuse(control, problem)
        try:
            wait()
        except KeyboardInterrupt:
            pass
        return 2
    alive = control.with_name(control.name + ".alive")
    child, seen, touched = None, None, 0.0
    try:
        while True:
            now = time.monotonic()
            if now - touched >= ALIVE_S:
                alive.write_text(str(os.getpid()), encoding="utf-8")
                touched = now
            stamp = _mtime(control)
            if stamp != seen:
                seen = stamp
                problem = control_problem(control) if stamp else None
                if problem is not None:
                    _refuse(control, problem)
                argv = None if problem is not None else read_control(control)
                if argv is not None:
                    _stop(child)
                    child = subprocess.Popen([sys.executable, str(ROOT / "bin" / "sigil"), "view", *argv])
            if child is not None and child.poll() is not None:
                if child.returncode == 0:
                    return 0                # quit from its own keys: the split's done
                print(f"\nsigil view stopped (status {child.returncode}); waiting for the "
                      "next request (ctrl-c closes this split)", flush=True)
                child = None
            time.sleep(FOLLOW_POLL_S)
    except KeyboardInterrupt:
        return 0
    finally:
        _stop(child)
        for path in (alive, control):
            try:
                path.unlink()
            except OSError:
                pass
        if control.parent.name.startswith(CONTROL_PREFIX):  # a host's private directory:
            for path in (control.with_suffix(".kdl"), control.parent):   # its zellij layout,
                try:                                         # then the directory once empty
                    path.unlink() if path != control.parent else path.rmdir()
                except OSError:
                    pass


def _depth(text: str) -> int:
    return 99 if text == "all" else max(0, int(text))


def _start(text: str) -> int | None:
    """--from: a run frame (from 0), or None for `last`."""
    return None if text == "last" else max(0, int(text))


def _frames(argv: list, dialect) -> int:
    from sigil.present import app, frames
    ap = argparse.ArgumentParser(prog=SAID["frames"],
                                 description="The Claude Code mod's drawing and split helper.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draw", help="a document's drawing as JSON for the mod's pane")
    d.add_argument("file", type=Path)
    d.add_argument("--view", choices=app.VIEWS, default="flow")
    d.add_argument("--depth", type=_depth, default=1)
    d.add_argument("--width", type=int, default=None)
    d.add_argument("--height", type=int, default=None)
    d.add_argument("--layout", choices=("auto", "wrap", "pan"), default="auto")
    d.add_argument("--scenario", default=None)
    d.add_argument("--from", dest="start", type=_start, default=0)
    d.add_argument("--count", type=int, default=frames.WINDOW)
    d.add_argument("--payloads", action="store_true")
    d.add_argument("--theme", default=None,
                   help="colour theme: a name or a .yaml path (default: $SIGIL_THEME, "
                        "else the dialect's THEME, else sigil)")
    _dialect_flag(d, dialect)
    d.add_argument("--limit", action="append", default=[], metavar="NAME=N",
                   help="raise one simulator limit (repeatable; e.g. frames=5000), as "
                        "view and check take it")
    f = sub.add_parser("follow", help="run `sigil view` live as a control file says")
    f.add_argument("control", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "follow":
        return follow(a.control)
    try:
        limits = _limits(a.limit)
        loaded = load_dialect(a.dialect)
    except ValueError as exc:
        say("frames", str(exc))
        return 2
    out = frames.draw(a.file, a.view, a.depth, a.width, a.scenario, a.payloads, a.theme,
                      a.layout, a.height, a.start, a.count, limits, dialect=loaded)
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    return 0


def _themes(argv: list, dialect) -> int:
    """`sigil themes`: what `python3 -m sigil.present.themes` does (no dialect)."""
    from sigil.present import themes
    return themes.main(argv)


# ---------------------------------------------------------------------------
# sigil highlight — the source as coloured runs (ANSI, --json, or --stream)
# ---------------------------------------------------------------------------

HIGHLIGHT_VERSION = 1       # "sigil_highlight" in --json: the shape below

HIGHLIGHT_PROTOCOL = """\
--json prints one object:
  {"sigil_highlight": 1, "theme": NAME,
   "lines": [[[TEXT, ROLE|null, "#rrggbb"|null], ...], ...],
   "carry": [CARRY, ...]}
one list of runs per line (its texts joined give the line back) and the carry
each line ends in (the one the next line starts in). ROLE is a theme path
(syntax.operator, kinds.service, ui.mode ...); the colour is that role's in
the theme, null for plain text.

CARRY is [quote, decl, decl_raw, state], four integers: quote 1 inside a
\"\"\"...\"\"\" block string; decl the brace depth inside a `#&` declaration's
body (0: none); decl_raw 1 when that body's braces count on the raw line;
state the brace depth inside a `state` block. A text starts in [0, 0, 1, 0].

--stream reads JSON-lines requests on stdin and answers each with one JSON
line on stdout (flushed), until stdin ends (exit 0):
  {"id": ANY, "lines": [STR, ...], "start": N, "carry": CARRY|null}
    -> {"id": ANY, "start": N, "lines": [[RUN, ...], ...], "carry": [CARRY, ...]}
  {"id": ANY, "theme": NAME|PATH}   -> {"id": ANY, "theme": NAME}
  {"id": ANY, "dialect": NAME|PATH|null}
    -> {"id": ANY, "dialect": NAME|null[, "theme": NAME]}
  anything malformed                -> {"id": ANY|null, "error": "..."}
A request may hold dialect, theme and lines together: the dialect switches
first, then the theme, then the lines are highlighted with both; the answer
holds a key for each part. A request that fails in any part answers only
{"id", "error"} and changes nothing (a dialect that fails to load keeps the old
one). A dialect is loaded as --dialect loads it (null: core Sigil, no dialect,
whatever $SIGIL_DIALECT says) and answered by its NAME. Themes: --theme or a
{"theme"} request is explicit and holds for the rest of the session; until one
is given the theme is $SIGIL_THEME if set, else the dialect's THEME, else
sigil, so (without $SIGIL_THEME) a dialect switch also switches the theme, and
its answer names the theme now in use ("theme"). After an explicit theme a
dialect switch leaves the theme alone.
`start` is the index of lines[0] (echoed; default 0), `carry` the carry lines[0]
starts in (null: a text's start). A line's runs depend only on the line and
the carry it starts in, so an editor highlights incrementally: after an edit it
sends the changed lines with the end carry of the line before them, and keeps
sending the lines that follow until a returned end carry equals the one it held
for that line; from there on nothing changed. No file is read but the theme and
a dialect asked for."""


def carry_json(carry) -> list:
    """A highlight Carry as its stable JSON form [quote, decl, decl_raw, state]."""
    return [int(carry.quote), carry.decl, int(carry.decl_raw), carry.state]


def carry_from_json(value):
    """The Carry a JSON value names (None: a text's start). Raises ValueError."""
    from sigil.present import highlight as hl
    if value is None:
        return hl.PLAIN
    if not (isinstance(value, list) and len(value) == 4
            and all(type(v) is int and v >= 0 for v in value)
            and value[0] in (0, 1) and value[2] in (0, 1)):
        raise ValueError("carry must be null or [quote 0|1, decl >= 0, decl_raw 0|1, "
                         "state >= 0]")
    return hl.Carry(bool(value[0]), value[1], bool(value[2]), value[3])


def runs_json(runs, theme: dict, lx) -> list:
    """A line's runs as [text, role, colour] triples."""
    from sigil.present import highlight as hl
    return [[text, role, hl.colour(role, theme, lx)] for text, role in runs]


def ansi_line(runs, theme: dict, lx) -> str:
    """A line's runs with a truecolour SGR around each coloured one."""
    from sigil.present import highlight as hl
    out = []
    for text, role in runs:
        hexa = hl.colour(role, theme, lx)
        if hexa is None or not text:
            out.append(text)
        else:
            r, g, b = (int(hexa[k:k + 2], 16) for k in (1, 3, 5))
            out.append(f"\x1b[38;2;{r};{g};{b}m{text}\x1b[0m")
    return "".join(out)


def theme_name(theme: dict, spec) -> str:
    """The name a loaded theme goes by (its `name`, else what was asked for)."""
    name = theme.get("name") if isinstance(theme, dict) else None
    return name if isinstance(name, str) and name else str(spec or "sigil")


def no_colour() -> bool:
    """NO_COLOR set and not empty (no-color.org): print plain text."""
    return bool(os.environ.get("NO_COLOR"))


def highlight_text(text: str, theme: dict, lx, colour: bool = True) -> str:
    """`text` with its lines highlighted in ANSI, every line ending kept as it is
    (the lines split as str.splitlines splits them, as highlight.lines does)."""
    from sigil.present import highlight as hl
    out, carry = [], hl.PLAIN
    for whole in text.splitlines(keepends=True):
        body = (whole.splitlines() or [""])[0]
        runs, carry = hl.line(body, carry, lx)
        out.append((ansi_line(runs, theme, lx) if colour else body) + whole[len(body):])
    return "".join(out)


def highlight_json(text: str, theme: dict, name: str, lx) -> dict:
    """The --json object of a text (HIGHLIGHT_PROTOCOL)."""
    from sigil.present import highlight as hl
    rows, ends, carry = [], [], hl.PLAIN
    for raw in text.splitlines():
        runs, carry = hl.line(raw, carry, lx)
        rows.append(runs_json(runs, theme, lx))
        ends.append(carry_json(carry))
    return {"sigil_highlight": HIGHLIGHT_VERSION, "theme": name, "lines": rows,
            "carry": ends}


def _one_line(value) -> bool:
    return isinstance(value, str) and value.splitlines() in ([], [value])


class StreamSession:
    """One --stream process's state: the theme it colours with (and whether it
    was asked for explicitly: --theme or a {"theme"} request), the dialect and
    its lexicon. answer() turns one request line into one response object; a
    request that fails changes none of it."""

    def __init__(self, theme: dict, name: str, lx, dialect=None, explicit: bool = False):
        self.theme, self.name, self.lx = theme, name, lx
        self.dialect, self.explicit = dialect, explicit

    def answer(self, raw: str) -> dict:
        try:
            req = json.loads(raw)
        except ValueError as exc:
            return {"id": None, "error": f"not JSON: {exc}"}
        if not isinstance(req, dict):
            return {"id": None, "error": "a request is a JSON object"}
        rid = req.get("id")
        try:
            return {"id": rid, **self._serve(req)}
        except ValueError as exc:
            return {"id": rid, "error": str(exc)}

    def _serve(self, req: dict) -> dict:
        from sigil.present import highlight as hl, themes
        if not {"dialect", "theme", "lines"} & req.keys():
            raise ValueError("a request holds lines, a theme or a dialect")
        out: dict = {}
        dialect, lx, explicit = self.dialect, self.lx, self.explicit
        theme, name = self.theme, self.name
        if "dialect" in req:                   # first: the theme may follow the dialect
            dialect = _stream_dialect(req["dialect"])
            lx = hl.lexicon(dialect)
            out["dialect"] = getattr(dialect, "NAME", None) if dialect is not None else None
            if not explicit and "theme" not in req:
                theme = themes.load(None, dialect)     # ThemeError is a ValueError
                name = theme_name(theme, themes.chosen(None, dialect)[0])
                out["theme"] = name
        if "theme" in req:
            spec = req["theme"]
            if not isinstance(spec, str) or not spec:
                raise ValueError("theme must be a theme name or path")
            theme = themes.load(spec)
            name, explicit = theme_name(theme, spec), True
            out["theme"] = name
        if "lines" in req:
            out.update(_stream_lines(req, theme, lx))
        self.dialect, self.lx, self.explicit = dialect, lx, explicit
        self.theme, self.name = theme, name
        return out


def _stream_dialect(spec):
    """The dialect a {"dialect"} request names (null: none). Raises ValueError
    for one that is not a name or path, or cannot be loaded."""
    if spec is not None and (not isinstance(spec, str) or not spec.strip()):
        raise ValueError("dialect must be a dialect name or path, or null")
    try:
        return load_dialect(spec or "")        # "": core, not $SIGIL_DIALECT
    except ValueError:
        raise
    except Exception as exc:                   # its module failed while it loaded
        raise ValueError(f"sigil dialect {spec!r} failed to load: "
                         f"{type(exc).__name__}: {exc}") from None


def _stream_lines(req: dict, theme: dict, lx) -> dict:
    """The answer to a request's lines (HIGHLIGHT_PROTOCOL). Raises ValueError."""
    from sigil.present import highlight as hl
    lines, start = req["lines"], req.get("start", 0)
    if not (isinstance(lines, list) and all(_one_line(s) for s in lines)):
        raise ValueError("lines must be a list of strings, each without a line break")
    if type(start) is not int or start < 0:
        raise ValueError("start must be a line index >= 0")
    carry = carry_from_json(req.get("carry"))
    rows, ends = [], []
    for raw in lines:
        runs, carry = hl.line(raw, carry, lx)
        rows.append(runs_json(runs, theme, lx))
        ends.append(carry_json(carry))
    return {"start": start, "lines": rows, "carry": ends}


def stream(session: StreamSession, inp, out) -> int:
    """The --stream loop: a response per non-blank request line, flushed, until EOF."""
    while True:
        raw = inp.readline()
        if not raw:
            return 0
        if not raw.strip():
            continue
        out.write(json.dumps(session.answer(raw)) + "\n")
        out.flush()


def _highlight(argv: list, dialect) -> int:
    ap = argparse.ArgumentParser(
        prog=SAID["highlight"],
        usage="sigil highlight FILE|- [--theme NAME|PATH] [--dialect D] [--json]\n"
              "       sigil highlight --stream [--theme NAME|PATH] [--dialect D]",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Print a Sigil document's source in its theme's colours (ANSI "
                    "truecolour; plain\nwhen NO_COLOR is set), or as runs for a host "
                    "(--json) or a live editor (--stream).",
        epilog=HIGHLIGHT_PROTOCOL)
    ap.add_argument("file", nargs="?", help="a .sigil file, or - for stdin")
    ap.add_argument("--theme", default=None,
                    help="colour theme: a name in themes/ or a .yaml path (default: "
                         "$SIGIL_THEME, else the dialect's THEME, else sigil)")
    _dialect_flag(ap, dialect)
    ap.add_argument("--json", action="store_true",
                    help="print each line's runs (text, role, colour) as one JSON object")
    ap.add_argument("--stream", action="store_true",
                    help="answer JSON-lines requests on stdin until it ends (no FILE)")
    a = ap.parse_args(argv)
    if a.stream and (a.file is not None or a.json):
        ap.error("--stream reads requests on stdin: no FILE, no --json")
    if not a.stream and a.file is None:
        ap.error("a file is required (or --stream)")
    from sigil.present import highlight as hl, themes
    try:
        loaded = load_dialect(a.dialect)
        theme = themes.load(a.theme, loaded)   # --theme, $SIGIL_THEME, the dialect's THEME, sigil
        name = theme_name(theme, themes.chosen(a.theme, loaded)[0])
    except ValueError as exc:
        say("highlight", str(exc))
        return 2
    lx = hl.lexicon(loaded)
    if a.stream:
        for io in (sys.stdin, sys.stdout):
            if hasattr(io, "reconfigure"):
                io.reconfigure(encoding="utf-8", errors="replace")
        session = StreamSession(theme, name, lx, loaded, explicit=bool(a.theme))
        return stream(session, sys.stdin, sys.stdout)
    try:
        text = read_text(a.file)
    except OSError as exc:
        say("highlight", cannot_read(a.file, exc))
        return 2
    except UnicodeDecodeError as exc:
        say("highlight", f"cannot read {a.file}: not UTF-8 ({exc.reason})")
        return 2
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if a.json:
        print(json.dumps(highlight_json(text, theme, name, lx), ensure_ascii=False))
    else:
        sys.stdout.write(highlight_text(text, theme, lx, colour=not no_colour()))
        sys.stdout.flush()
    return 0


COMMANDS = {"lint": _lint, "check": _check, "view": _view, "export": _export,
            "frames": _frames, "themes": _themes, "highlight": _highlight}


def main(argv=None, dialect=None) -> int:
    """Run one subcommand; its exit status. `argv` defaults to sys.argv[1:]."""
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] in ("-h", "--help"):
        print("usage:\n" + USAGE)
        return 0
    run = COMMANDS.get(argv[0]) if argv else None
    if run is None:
        named = f"unknown command {argv[0]!r}\n" if argv else ""
        print(f"sigil: {named}usage:\n{USAGE}", file=sys.stderr)
        return 2
    from sigil.core.dialects import DialectError
    try:
        return run(argv[1:], dialect)
    except DialectError as exc:            # a dialect hook broke its contract mid-read
        say(argv[0], str(exc))
        return 2
