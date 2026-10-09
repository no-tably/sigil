#!/usr/bin/env python3
"""
wide_table.py — write the WIDE tables of the JavaScript copies of the cell-width
rule from Python's unicodedata, by viewkit.char_cells's rule.

    tools/wide_table.py           # rewrite the tables in place, report what changed
    tools/wide_table.py --check   # write nothing; exit 1 if a table is stale

A wide character (East Asian Width W or F, not a combining mark or zero-width)
takes two columns. Two files measure text in the browser / in node and carry the
wide code points as a table:

- site/site.js: `const WIDE = new RegExp(...)`, a character class of ranges;
- plugin/claude/hooks/logic.ts: `const WIDE: readonly number[]`, inclusive
  [first, last] pairs.

Only the lines inside each table are written; the code around them is left as it
is. The ranges are exact over every code point (unassigned ones as unicodedata
reads them), so the tables agree with viewkit wherever a character is.

Standard library only.
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path
from typing import Callable, NamedTuple

ROOT = Path(__file__).resolve().parents[1]
LAST_CODE = 0x10FFFF
LINE_WIDTH = 100


class Table(NamedTuple):
    """One file's WIDE table: the lines between `start` and `end` (regexes
    matching whole lines) are `lines(ranges)`."""
    path: str
    start: str
    end: str
    lines: Callable[[list], list]


# ---------------------------------------------------------------------------
# The ranges
# ---------------------------------------------------------------------------

def wide_ranges(cells: Callable[[str], int], last: int = LAST_CODE) -> list:
    """Inclusive (first, last) code point runs whose characters take 2 cells."""
    runs: list = []
    for code in range(last + 1):
        if cells(chr(code)) != 2:
            continue
        if runs and runs[-1][1] == code - 1:
            runs[-1] = (runs[-1][0], code)
        else:
            runs.append((code, code))
    return runs


# ---------------------------------------------------------------------------
# The two formats
# ---------------------------------------------------------------------------

def packed(items: list, prefix: str, suffix: str, joiner: str, width: int) -> list:
    """items joined into lines of at most `width` columns, each line
    prefix + items + suffix (an item never split)."""
    lines, line = [], []
    for item in items:
        if line and len(prefix + joiner.join(line + [item]) + suffix) > width:
            lines.append(prefix + joiner.join(line) + suffix)
            line = []
        line.append(item)
    if line:
        lines.append(prefix + joiner.join(line) + suffix)
    return lines


def js_regex_lines(ranges: list, width: int = LINE_WIDTH) -> list:
    """site.js: `    String.raw`\\u{a}-\\u{b}\\u{c}...`,` lines."""
    def item(first, last):
        one = f"\\u{{{first:x}}}"
        return one if first == last else f"{one}-\\u{{{last:x}}}"
    return packed([item(a, b) for a, b in ranges], "    String.raw`", "`,", "", width)


def ts_pair_lines(ranges: list, width: int = LINE_WIDTH) -> list:
    """logic.ts: `  0xa, 0xb, 0xc, 0xc,` lines, a pair never split."""
    return packed([f"0x{a:x}, 0x{b:x}" for a, b in ranges], "  ", ",", ", ", width)


TABLES = (
    Table("site/site.js", r"\s*const WIDE = new RegExp\(`\[\$\{\[",
          r"\s*\]\.join\(\"\"\)\}\]`, \"u\"\);", js_regex_lines),
    Table("plugin/claude/hooks/logic.ts", r"const WIDE: readonly number\[\] = \[",
          r"\]", ts_pair_lines),
)


# ---------------------------------------------------------------------------
# Writing a table into its file
# ---------------------------------------------------------------------------

class TableNotFound(ValueError):
    """The file has no start line, or no end line after it."""


def with_table(text: str, table: Table, ranges: list) -> str:
    """text with the lines between the table's start and end lines replaced."""
    lines = text.split("\n")
    start = next((k for k, ln in enumerate(lines) if re.fullmatch(table.start, ln)), None)
    if start is None:
        raise TableNotFound(f"{table.path}: no line matching {table.start!r}")
    end = next((k for k in range(start + 1, len(lines))
                if re.fullmatch(table.end, lines[k])), None)
    if end is None:
        raise TableNotFound(f"{table.path}: no line matching {table.end!r} after the start")
    return "\n".join(lines[:start + 1] + table.lines(ranges) + lines[end:])


def load_char_cells(root: Path) -> Callable[[str], int]:
    """viewkit.char_cells, the rule the views draw by."""
    spec = importlib.util.spec_from_file_location("sigil_viewkit_wide", root / "viewkit.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.char_cells


def parse_args(argv):
    ap = argparse.ArgumentParser(
        prog="wide_table.py",
        description="Write the WIDE tables in site/site.js and "
                    "plugin/claude/hooks/logic.ts from Python's unicodedata.")
    ap.add_argument("--check", action="store_true",
                    help="write nothing; exit 1 if a table is stale (for tests / CI)")
    return ap.parse_args(argv)


def main(argv=None, root: Path = ROOT, cells: Callable[[str], int] | None = None) -> int:
    """root: where the two files are; cells: the width rule (viewkit's by default)."""
    check = parse_args(argv).check
    ranges = wide_ranges(cells or load_char_cells(root))
    stale = 0
    for table in TABLES:
        path = root / table.path
        text = path.read_text(encoding="utf-8")
        try:
            new = with_table(text, table, ranges)
        except TableNotFound as err:
            print(f"wide_table.py: {err}", file=sys.stderr)
            return 2
        changed = new != text
        stale += changed
        print(f"{table.path}: {'stale' if changed and check else 'updated' if changed else 'current'}")
        if changed and not check:
            path.write_text(new, encoding="utf-8")
    return 1 if check and stale else 0


if __name__ == "__main__":
    sys.exit(main())
