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

import sys

USAGE = __doc__.split("\n\n")[1].strip("\n")


def _lint(argv: list, dialect) -> int:
    from sigil.analyse import lint
    return lint.main(argv, default_dialect=dialect)


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
