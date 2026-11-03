#!/usr/bin/env python3
"""
wide_table.py — write the cell-width tables of logic.ts (the Claude Code pane's and
pi's plain-text measure) from cure's |WideTable|, by sigil.present.kit.char_cells
(cure's rule for one code point).

    tools/wide_table.py           # rewrite the tables in place, report what changed
    tools/wide_table.py --check   # write nothing; exit 1 if a table is stale

plugin/claude/hooks/logic.ts carries two tables of inclusive [first, last] pairs:
`const WIDE: readonly number[]`, the code points 2 columns wide, and `const ZERO:
readonly number[]`, the code points 0 wide (combining marks, joiners, format
characters, Hangul vowel and final jamo); every other one is 1. Packed rows need
neither (`sigil frames` sends cure's Wire: one code point a cell, the side table
for a longer cluster); plain text a host draws (a status, narration, lint line)
is measured by them. The page (site/site.js) measures nothing: it counts a
packed row's code points.

Only the lines inside each table are written; the code around them is left as it
is. The ranges are exact over every code point, so the tables agree with the kit
wherever a character is.

Standard library only (and the package beside tools/, for the kit's rule).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Callable, NamedTuple

ROOT = Path(__file__).resolve().parents[1]
LAST_CODE = 0x10FFFF
LINE_WIDTH = 100


class Table(NamedTuple):
    """One table in a file: the lines between `start` and `end` (regexes
    matching whole lines) are `lines(ranges)`, the ranges of the code points
    `cells` columns wide."""
    path: str
    start: str
    end: str
    lines: Callable[[list], list]
    cells: int = 2


# ---------------------------------------------------------------------------
# The ranges
# ---------------------------------------------------------------------------

def wide_ranges(cells: Callable[[str], int], last: int = LAST_CODE, n: int = 2) -> list:
    """Inclusive (first, last) code point runs whose characters take `n` cells
    (surrogates left out: they are no character)."""
    runs: list = []
    for code in range(last + 1):
        if 0xD800 <= code <= 0xDFFF or cells(chr(code)) != n:
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


def ts_pair_lines(ranges: list, width: int = LINE_WIDTH) -> list:
    """logic.ts: `  0xa, 0xb, 0xc, 0xc,` lines, a pair never split."""
    return packed([f"0x{a:x}, 0x{b:x}" for a, b in ranges], "  ", ",", ", ", width)


TABLES = (
    Table("plugin/claude/hooks/logic.ts", r"const WIDE: readonly number\[\] = \[",
          r"\]", ts_pair_lines, 2),
    Table("plugin/claude/hooks/logic.ts", r"const ZERO: readonly number\[\] = \[",
          r"\]", ts_pair_lines, 0),
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


def load_char_cells() -> Callable[[str], int]:
    """sigil.present.kit.char_cells, the rule the views draw by (cure's, through
    the package beside tools/, at ROOT)."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from sigil.present import kit
    return kit.char_cells


def parse_args(argv):
    ap = argparse.ArgumentParser(
        prog="wide_table.py",
        description="Write the WIDE and ZERO tables in plugin/claude/hooks/logic.ts "
                    "from cure's widths (sigil.present.kit.char_cells).")
    ap.add_argument("--check", action="store_true",
                    help="write nothing; exit 1 if a table is stale (for tests / CI)")
    return ap.parse_args(argv)


def main(argv=None, root: Path = ROOT, cells: Callable[[str], int] | None = None) -> int:
    """root: where the file is; cells: the width rule (the kit's by default)."""
    check = parse_args(argv).check
    cells = cells or load_char_cells()
    stale = 0
    for table in TABLES:
        path = root / table.path
        text = path.read_text(encoding="utf-8")
        try:
            new = with_table(text, table, wide_ranges(cells, n=table.cells))
        except TableNotFound as err:
            print(f"wide_table.py: {err}", file=sys.stderr)
            return 2
        changed = new != text
        stale += changed
        name = "WIDE" if table.cells == 2 else "ZERO"
        print(f"{table.path} {name}: "
              f"{'stale' if changed and check else 'updated' if changed else 'current'}")
        if changed and not check:
            path.write_text(new, encoding="utf-8")
    return 1 if check and stale else 0


if __name__ == "__main__":
    sys.exit(main())
