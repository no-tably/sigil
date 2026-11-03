"""[Width]: everything measured in terminal cells, never in code points.

Kind: service (pure functions).

What it does: the width of one code point (from |WideTable|) and of one grapheme
cluster ({Char}): 0, 1 or 2 columns. Splitting text into clusters is
[Graphemes]' job (it builds on this module, so this module does not import it);
measuring a string or a line is `cure.core.text.width` (the package function) and
`cure.core.text.spans.measure`, which sum `cells` over the clusters.

Note on the name: the package `cure.core.text` exports a *function* `width`, which
shadows this submodule as a package attribute. Import from this module with
`from cure.core.text.width import cells, point`, not `import cure.core.text.width as m`.

The cluster rule (`cells`), for a string taken as ONE grapheme cluster:

1. Empty string: 0.
2. A control cluster, one whose first code point is a C0 or C1 control or DEL
   (U+0000..U+001F, U+007F..U+009F) or a surrogate (U+D800..U+DFFF), including the
   CR LF pair and a tab: 1. It is drawn as U+FFFD by `cure.core.text.cell` / `put`,
   never as itself. (Text never expands tabs except [Ansi] at 8-column stops and
   [Wrap] as a space.)
3. Otherwise `w = min(2, sum(point(c) for c in cluster))`, and when the cluster
   contains U+FE0F VARIATION SELECTOR-16 and `w == 1`, `w = 2` (emoji presentation).

So, with the table as generated: "a" 1, "中" 2, "Ａ" (fullwidth) 2, "ｱ" (halfwidth) 1,
"★" (ambiguous) 1, "e\\u0301" 1, "\\u0301" alone 0, "\\u200b" 0, "\\u00ad" 1,
"❤" 1, "❤\\ufe0f" 2, "1\\ufe0f\\u20e3" (keycap) 2, "👍" 2, "👍🏽" 2,
"👨\\u200d👩\\u200d👧" 2, "🇺🇸" (a regional indicator pair) 2, "🇺" alone 1,
"\\u1100\\u1161\\u11a8" (Hangul L V T jamo) 2, "\\t" 1, "\\x1b" 1, "\\r\\n" 1.

The public names other modules use: `point`, `control`, `cells`, `CONTROL_RANGES`,
`VS16`, and the display filter's sets: `BIDI` (U+061C, U+200E, U+200F, U+202A..U+202E,
U+2066..U+2069), `SEPARATORS` (U+2028, U+2029) and `MAX_CLUSTER` (32), shared by
Buffer's Display, [Ansi] and Remote's protocol check. They change no width: a bidi
character is 0 columns, a separator 1, and a cluster of any length is measured. `control(char) -> bool`: True when the one code point `char` falls in
`CONTROL_RANGES` (rule 2's code points: C0, DEL, C1, a surrogate); `TypeError` when
`char` is not a `str`, `ValueError` when `len(char) != 1`; printable ASCII answers
False without the ranges (Speed). `_is_control(code)` (on an `int`) is this module's
own: [Graphemes] and every other caller ask `control(char)` instead (Q9a; Graphemes'
classing loop already passes exactly one code point, so the answer is the same).

Inputs: `point(char)`: one code point (`str` of length 1). `control(char)`: the same.
  `cells(cluster)`: a `str`
  the caller has already cut to one cluster ({Char}); it is not checked to be one.
Outputs: {Cells}: an int in 0..2.
Errors: `TypeError` when the argument is not a `str`; `point` raises `ValueError`
  when `len(char) != 1`.
Effects: none.

Speed: `point`, `control` and `cells` may answer a printable-ASCII code point
(U+0020..U+007E: width 1, not a control) without the table; the answers and the errors
are the general rule's (law fast_equal of `cure.core.text`).

Usage:
    from cure.core.text.width import cells, point
    point("中")             # 2, |WideTable|'s answer
    cells("e\\u0301")        # 1
    cells("❤\\ufe0f")        # 2
"""

from functools import lru_cache

from . import widetable

CONTROL_RANGES: tuple[tuple[int, int], ...] = ((0x00, 0x1F), (0x7F, 0x9F), (0xD800, 0xDFFF))
"""Inclusive code point ranges whose clusters are controls (rule 2); fixed, not table data."""

VS16 = "️"

BIDI: frozenset[str] = frozenset(map(chr, (0x061C, 0x200E, 0x200F, *range(0x202A, 0x202F),
                                           *range(0x2066, 0x206A))))
"""The bidi formatting characters (ALM, LRM, RLM, LRE..RLO, LRI..PDI): Cf, so [Graphemes]
makes them extenders and `cells` measures them, but Buffer's Display sends a glyph
holding one as U+FFFD, [Ansi] drops a link holding one, and Remote refuses them."""

SEPARATORS: frozenset[str] = frozenset(("\u2028", "\u2029"))
"""LINE SEPARATOR and PARAGRAPH SEPARATOR: width 1 here, sent as U+FFFD by Display."""

MAX_CLUSTER = 32
"""The most code points a glyph Display sends may hold; a longer one is sent as U+FFFD
(F9: no repaint cost grows with a cell's marks). Remote's frame limit assumes it
(sigil's edge 3), so it changes only with that limit."""


def point(char: str) -> int:
    """The columns one code point takes on its own: `widetable.read(char)`
    (0, 1 or 2; controls and surrogates are 1 here, as in the table)."""
    if char.__class__ is str and len(char) == 1:
        return 1 if " " <= char <= "~" else _read(char)   # Speed: ASCII without the table
    return widetable.read(char)


def control(char: str) -> bool:
    """True when code point `char` is a control by rule 2 (in CONTROL_RANGES).
    `TypeError` if not a `str`, `ValueError` if `len(char) != 1`."""
    if char.__class__ is str and len(char) == 1 and " " <= char <= "~":
        return False                  # Speed: printable ASCII is not a control
    _one(char)
    return _is_control(ord(char))


def cells(cluster: str) -> int:
    """The columns one grapheme cluster takes, by the cluster rule above (0, 1 or 2)."""
    if not isinstance(cluster, str):
        raise TypeError(f"expected a str, got {type(cluster).__name__}")
    if cluster.__class__ is str and len(cluster) == 1 and " " <= cluster <= "~":
        return 1                      # Speed: one printable-ASCII code point
    if not cluster:
        return 0
    if _is_control(ord(cluster[0])):
        return 1
    if len(cluster) == 1:
        return _read(cluster[0])      # one code point: its own width (0..2, never VS16's boost)
    w = min(2, sum(_read(c) for c in cluster))
    if w == 1 and VS16 in cluster:
        return 2
    return w


_read = lru_cache(maxsize=4096)(widetable.read)
"""Speed: |WideTable|'s answer for one code point (an exact `str` of length 1), memoised:
the table is frozen with the release, so the memo changes no answer."""


def _one(char: str) -> None:
    if not isinstance(char, str):
        raise TypeError(f"expected a str, got {type(char).__name__}")
    if len(char) != 1:
        raise ValueError(f"expected one code point, got {len(char)}")


def _is_control(code: int) -> bool:
    for first, last in CONTROL_RANGES:
        if first <= code <= last:
            return True
    return False
