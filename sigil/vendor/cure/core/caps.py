"""{Caps}: what a terminal can do: depth, keys, mouse, graphemes, sync; Term probes it.

Kind: data (a frozen dataclass, checked on construction). Imports nothing from cure: a
{Caps} is a plain value Edge's [Term] probes (falling back to the environment) and every
other part receives as an argument. Style reads only `caps.depth`; Buffer's [Display]
reads `depth`, `sync` and `graphemes`; Input reads `keys` and `mouse`. No part keeps a
{Caps} of its own: the capabilities are always arguments (Rules carried over).

Data:
- `Caps(depth=0, keys="legacy", mouse=False, graphemes=False, sync=False)`:
  - `depth`: `int`, exactly one of `DEPTHS`: `0` (no colour: NO_COLOR, a dumb
    terminal), `16` (the 16 ANSI colours), `256` (the xterm palette), `24` (24-bit
    colour). These are the values Style's `depth_of` accepts.
  - `keys`: `str`, one of `KEYS`, the keyboard protocol the terminal speaks:
    `"legacy"` (plain VT keys, ambiguous Esc/Alt and Ctrl combinations), `"modify"`
    (xterm modifyOtherKeys), `"kitty"` (the kitty progressive enhancement, CSI u).
  - `mouse`: `bool`, the terminal reports the mouse in SGR form (mode 1006).
  - `graphemes`: `bool`, the terminal draws a grapheme cluster of several code points
    (an emoji ZWJ sequence, a flag) as one glyph in the columns cure's |WideTable|
    gives it (mode 2027). When false, [Display] does not trust the cursor position
    after such a glyph and moves the cursor explicitly before the next cell.
  - `sync`: `bool`, the terminal understands synchronized output (mode 2026), so
    [Display] brackets each non-empty frame with `ESC[?2026h` ... `ESC[?2026l`.
  `Caps()` is the dumb terminal: no colour, legacy keys, no mouse, no grapheme
  clustering, no synchronized output. `Caps.dumb()` returns exactly `Caps()`.
  Equality and hashing are field by field (a {Caps} can key a cache).

Inputs: the five fields above.
Outputs: a {Caps}.
Errors: `TypeError` when a field has the wrong type: `depth` not an `int` (a `bool` is
  refused: `True` is not a depth), `keys` not a `str`, `mouse` / `graphemes` / `sync`
  not a `bool`. `ValueError` when `depth` is an `int` not in `DEPTHS` (e.g. 8, 2**24)
  or `keys` is a `str` not in `KEYS`. Assigning a field raises
  `dataclasses.FrozenInstanceError`.
Effects: none (no probing here; that is [Term]'s job).

Usage:
    from cure.core.caps import Caps
    Caps()                                  # the dumb terminal
    Caps.dumb() == Caps()                   # True
    Caps(depth=256, mouse=True, sync=True)  # what a probe of a modern xterm might give
    Caps(depth=8)                           # ValueError
"""

from dataclasses import dataclass

DEPTHS = (0, 16, 256, 24)
KEYS = ("legacy", "modify", "kitty")


@dataclass(frozen=True)
class Caps:
    """{Caps}: what a terminal can do. Checked on construction (see the module)."""

    depth: int = 0
    keys: str = "legacy"
    mouse: bool = False
    graphemes: bool = False
    sync: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.depth, int) or isinstance(self.depth, bool):
            raise TypeError(f"depth must be an int, got {type(self.depth).__name__}")
        if self.depth not in DEPTHS:
            raise ValueError(f"depth must be one of {DEPTHS}, got {self.depth!r}")
        if not isinstance(self.keys, str):
            raise TypeError(f"keys must be a str, got {type(self.keys).__name__}")
        if self.keys not in KEYS:
            raise ValueError(f"keys must be one of {KEYS}, got {self.keys!r}")
        for flag in ("mouse", "graphemes", "sync"):
            value = getattr(self, flag)
            if not isinstance(value, bool):
                raise TypeError(f"{flag} must be a bool, got {type(value).__name__}")

    @classmethod
    def dumb(cls) -> "Caps":
        """The dumb terminal: `Caps()` (depth 0, legacy keys, no mouse, graphemes or sync)."""
        return cls()
