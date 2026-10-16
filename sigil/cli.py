"""The `sigil` command: one entry point, a subcommand per tool.

    sigil lint FILE|- [--deep] [--dialect D]
    sigil check [FILE|-] [--mode M] [--k N] [--budget N] [--overlaps …] [--json] [--export] [--rules]
    sigil view FILE [--once] [--graph|--tree|--flow|--run] [--sim S] …
    sigil export SPEC --out DIR [--json] [--dry-run]
    sigil export FILE --mermaid [--depth N|all] [--composition subgraphs|edges|none]
    sigil export FILE --mermaid --spine
    sigil frames draw FILE [--view V] [--depth N|all] [--width N] [--scenario S] …
    sigil frames follow CONTROL

Each subcommand imports its layer only when it runs, so `sigil lint` loads
neither the simulator nor the views. `main(argv, dialect=…)` is what a dialect's
wrapper calls: `dialect` becomes every subcommand's default `--dialect`.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

USAGE = __doc__.split("\n\n")[1].strip("\n")
ROOT = Path(__file__).resolve().parents[1]   # the folder holding the package and bin/sigil


def read_text(path: str) -> str:
    """The document at `path` (`-` = stdin, read as UTF-8). Raises OSError."""
    if path == "-":
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8")
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


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
    ap = argparse.ArgumentParser(prog="lint.py", description="Lint a Sigil document.")
    ap.add_argument("file", help="a .sigil file, or - for stdin")
    ap.add_argument("--dialect", default=dialect,
                    help="dialect name or path (default: $SIGIL_DIALECT)")
    ap.add_argument("--deep", action="store_true",
                    help="also run the composition checks (check.py) and merge the reports")
    a = ap.parse_args(argv)
    from sigil.core import dialects
    from sigil.analyse import lint
    try:
        loaded = dialects.load(a.dialect)
    except ValueError as exc:
        print(f"lint.py: {exc}", file=sys.stderr)
        return 2
    try:
        text = read_text(a.file)
    except OSError as exc:
        print(f"lint.py: cannot read {a.file}: {exc.strerror or exc}", file=sys.stderr)
        return 2

    result = lint.lint(text, dialect=loaded)
    if not a.deep:
        return _report_lint(result, lint)
    from sigil.analyse import check
    try:
        report = check.check(text, dialect=loaded)
    except ValueError as exc:            # a refused rule pack or registry
        print(f"lint.py: --deep: {exc}", file=sys.stderr)
        return 2
    return _report_deep(result, report, lint, check)


def _check(argv: list, dialect) -> int:
    from sigil.analyse import check
    return check.main(argv, default_dialect=dialect)


def _view(argv: list, dialect) -> int:
    from sigil.present import app
    return app.main(argv, default_dialect=dialect)


def _export(argv: list, dialect) -> int:
    """The export folder, or with `--mermaid` the document as a Mermaid chart."""
    if "--mermaid" in argv:
        from sigil.publish import mermaid
        return mermaid.main([a for a in argv if a != "--mermaid"], default_dialect=dialect)
    from sigil.publish import exporter
    return exporter.main(argv, default_dialect=dialect)


# ---------------------------------------------------------------------------
# sigil frames — the hosts' drawings (draw) and the multiplexer split (follow)
# ---------------------------------------------------------------------------

FOLLOW_POLL_S = 0.3         # how often follow looks at CONTROL
ALIVE_S = 1.0               # how often follow touches CONTROL.alive


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


def follow(control: Path) -> int:
    """The multiplexer split's loop: runs `sigil view` live with the argv in the
    JSON file CONTROL ({"argv": [...]}), restarts it whenever CONTROL changes,
    touches CONTROL.alive every second so the host can tell the split is still
    up, and exits when the view quits on its own (q) or the split closes —
    removing both files. A view that fails (a bad flag, an unreadable file)
    leaves its message on screen and the loop waiting."""
    alive = control.with_name(control.name + ".alive")
    child, seen, touched = None, None, 0.0
    for sig in (signal.SIGTERM, signal.SIGHUP):    # the split closed: unwind through finally
        signal.signal(sig, lambda *_: sys.exit(0))
    try:
        while True:
            now = time.monotonic()
            if now - touched >= ALIVE_S:
                alive.write_text(str(os.getpid()), encoding="utf-8")
                touched = now
            stamp = _mtime(control)
            if stamp != seen:
                seen = stamp
                argv = read_control(control)
                if argv is not None:
                    _stop(child)
                    child = subprocess.Popen([sys.executable, str(ROOT / "bin" / "sigil"), "view", *argv])
            if child is not None and child.poll() is not None:
                if child.returncode == 0:
                    return 0                # quit from its own keys: the split's done
                print(f"\nview.py stopped (status {child.returncode}); waiting for the "
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


def _depth(text: str) -> int:
    return 99 if text == "all" else max(0, int(text))


def _start(text: str) -> int | None:
    """--from: a run frame (from 0), or None for `last`."""
    return None if text == "last" else max(0, int(text))


def _frames(argv: list, dialect) -> int:
    from sigil.present import app, frames
    ap = argparse.ArgumentParser(description="The Claude Code mod's drawing and split helper.")
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
    d.add_argument("--theme", default=None)
    f = sub.add_parser("follow", help="run view.py live as a control file says")
    f.add_argument("control", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "follow":
        return follow(a.control)
    out = frames.draw(a.file, a.view, a.depth, a.width, a.scenario, a.payloads, a.theme,
                      a.layout, a.height, a.start, a.count)
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    return 0


COMMANDS = {"lint": _lint, "check": _check, "view": _view, "export": _export,
            "frames": _frames}


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
    return run(argv[1:], dialect)
