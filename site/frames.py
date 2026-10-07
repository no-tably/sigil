"""
frames.py — a document drawn as page frames, shared by build_site.py (the
pre-rendered frames.json the page's view planes play) and playground.py (the same
drawing done live in the browser by Pyodide). Standard library only.

    autoclose(lines)     a half-typed document with its open `{` blocks closed
    Styles / pack_rows   view.py rows of (text, (fg, bg, bold)) runs → compact
                         [[text, style id], …] rows plus a style table whose
                         colours are theme roles ("kinds-service"), so the page
                         recolours them on a theme change
"""

from __future__ import annotations

import re

_STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"?')
_INNER_BRACES_RE = re.compile(r"\{[^{}]*\}")


def _code(line: str) -> str:
    """The line without a trailing # comment and with "…" strings blanked to
    spaces (same length), so neither a # nor a brace inside a string counts.
    Mode lines (#!…) have no code."""
    if line.lstrip().startswith("#!"):
        return ""
    blanked = _STRING_RE.sub(lambda m: " " * len(m.group()), line)
    m = re.search(r"(^|\s)#", blanked)
    return blanked[:m.start()] if m else blanked


def autoclose(lines: list[str]) -> str:
    """The prefix as a document: close any `{` blocks still open, so a half-typed
    expansion already draws. Braces are counted structurally: after dropping
    balanced {…} runs on a line (data glyphs, \\-{cond}- relations, one-line
    blocks), each `{` left opens a block and each `}` closes one — so `X := {`,
    `state X {`, `[A] @owns |S| {`, `} @inv …` and `}}` all count."""
    depth = 0
    for ln in lines:
        code, prev = _code(ln), None
        while code != prev:
            prev, code = code, _INNER_BRACES_RE.sub("", code)
        for ch in code:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth = max(depth - 1, 0)
    return "\n".join(lines + ["}"] * depth) + "\n"


StyleKey = tuple  # (fg role/hex | None, bg role/hex | None, bold)


class Styles:
    """Interns (fg, bg, bold) styles as compact role/hex triples."""

    def __init__(self) -> None:
        self.table: list[list] = []
        self.index: dict[StyleKey, int] = {}

    @staticmethod
    def _colour(c) -> str | None:
        """A colour as its theme role (e.g. "kinds-service") when it has one, else hex."""
        if not c:
            return None
        role = getattr(c, "role", "")
        return role or str(c)

    def intern(self, style) -> int:
        """The table index of a view.py (fg, bg, bold) style, adding it if new."""
        if style is None:
            style = (None, None, False)
        fg, bg, bold = style
        key = (self._colour(fg), self._colour(bg), bool(bold))
        if key not in self.index:
            self.index[key] = len(self.table)
            self.table.append(list(key))
        return self.index[key]


def pack_rows(rows, styles: Styles) -> list:
    """Rows of (text, style) runs -> [[text, style id], …] with equal neighbours
    merged; trailing blank runs and rows are dropped (a run with a background
    colour is kept — it is visible)."""
    out = []
    for row in rows:
        packed: list = []
        for text, st in row:
            sid = styles.intern(st)
            if packed and packed[-1][1] == sid:
                packed[-1][0] += text
            else:
                packed.append([text, sid])
        while packed and not packed[-1][0].strip() and not styles.table[packed[-1][1]][1]:
            packed.pop()
        out.append(packed)
    while out and not out[-1]:
        out.pop()
    return out
