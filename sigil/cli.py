"""The `sigil` command: one entry point, a subcommand per tool.

    sigil lint FILE|- [--deep] [--dialect D]
    sigil check [FILE|-] [--mode M] [--k N] [--budget N] [--overlaps …] [--json] [--export] [--rules]
    sigil view FILE [--once] [--graph|--tree|--flow|--run] [--sim S] …
    sigil export SPEC --out DIR [--json] [--dry-run]
    sigil export FILE --mermaid [--depth N|all] [--composition subgraphs|edges|none]
    sigil frames …                      (not yet: the plugin pane's frames)

Each subcommand imports its layer only when it runs, so `sigil lint` loads
neither the simulator nor the views. `main(argv, dialect=…)` is what a dialect's
wrapper calls: `dialect` becomes every subcommand's default `--dialect`.
"""

import argparse
import sys
from pathlib import Path

USAGE = __doc__.split("\n\n")[1].strip("\n")


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
        from sigil.core import parse
        return parse.main([a for a in argv if a != "--mermaid"], default_dialect=dialect)
    from sigil.publish import exporter
    return exporter.main(argv, default_dialect=dialect)


def _frames(argv: list, dialect) -> int:
    print("sigil frames: not available yet", file=sys.stderr)
    return 2


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
