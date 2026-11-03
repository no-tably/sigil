"""[Osc]: title, clipboard (52), cursor shape, bell: only on the app's own call; each
through the one [Writer].

Kind: service (pure builders of `Osc` values, and the function that writes one). Nothing
here runs unless the app asks: cure never sets a title or touches the clipboard by
itself. Hyperlinks (OSC 8) are not built here: they are cell styles, opened and closed
by Buffer's [Display] through Style's `hyperlink` (no link outlives a frame).

What can be undone is: an `Osc` carries the bytes that prepare its kind before its first
use and the bytes that undo its kind. The Term handle's `osc` sends `prepare` before the
first `Osc` of a kind, and its `close` (and `suspend`) sends each used kind's `undo`
(see [Term]); this module's `write` sends only `data` (the raw op, for a headless
writer or an app that does its own bookkeeping).

Data:
- `Osc(kind, data, prepare=b"", undo=b"")`: `kind` a `str`, one of `KINDS`; `data`,
  `prepare`, `undo` `bytes`. Equality is field by field.

The builders (`E` is ESC `\\x1b`, `ST` the string terminator `ESC \\`; every number in
decimal):
- `title(text) -> Osc`: kind `"title"`; data `E ] 2 ; {text} ST`, `text` encoded as
  UTF-8 after every control code point (C0 U+0000..U+001F, DEL U+007F, C1
  U+0080..U+009F) is removed, so the sequence cannot be ended or extended early;
  prepare `E [ 22 ; 2 t` (XTWINOPS: push the window title); undo `E [ 23 ; 2 t` (pop
  it: the title before the app's comes back). A lone surrogate (U+D800..U+DFFF) in
  `text` is not removed but refused (it has no UTF-8), as in `clipboard`.
  `title("a\\x07b") == Osc("title", b"\\x1b]2;ab\\x1b\\\\", b"\\x1b[22;2t", b"\\x1b[23;2t")`.
- `clipboard(text, *, target="c") -> Osc`: kind `"clipboard"`; data
  `E ] 52 ; {target} ; {base64 of text's UTF-8, standard alphabet, padded} ST`; no
  prepare, no undo (a copy is the app's intent, not a mode). `target` is `"c"` (the
  clipboard) or `"p"` (the primary selection). The clipboard is never read: no query
  (`?`) is ever built. A lone surrogate in `text` is refused (it has no UTF-8).
  `clipboard("hi") == Osc("clipboard", b"\\x1b]52;c;aGk=\\x1b\\\\")`.
- `cursor(shape="default", *, blink=False) -> Osc`: kind `"cursor"`; data DECSCUSR
  `E [ {n} SP q` with `n`: `"default"` 0 (whatever `blink`), `"block"` 1 blinking / 2
  steady, `"underline"` 3 / 4, `"bar"` 5 / 6; no prepare; undo `E [ 0 SP q` (the
  terminal's default shape).
  `cursor("bar") == Osc("cursor", b"\\x1b[6 q", b"", b"\\x1b[0 q")`.
- `bell() -> Osc`: kind `"bell"`; data `b"\\x07"`; no prepare, no undo.

`write(writer, osc) -> None | Closed` ([Osc] -> [Writer] : write({Osc})): `osc.data`
through `writer.write` (the [Writer]); its result. Not `prepare`, not `undo`.

Inputs: `text` a `str`; `target` `"c"` or `"p"`; `shape` one of `SHAPES`; `blink` a
  `bool`; `writer` any object with a `write(bytes)` method (a [Writer]); `osc` an `Osc`.
Outputs: an `Osc` ({Osc}); `write`: `None` or a {Closed}.
Errors: `Osc(...)`: `TypeError` when `kind` is not a `str` or `data` / `prepare` /
  `undo` is not `bytes`; `ValueError` when `kind` is not in `KINDS`. `title`,
  `clipboard`: `TypeError` when `text` is not a `str`; `ValueError("text must not hold
  a lone surrogate")` when it holds one (never `UnicodeEncodeError`); `clipboard`:
  `ValueError` when `target` is not `"c"` or `"p"`. `cursor`: `ValueError` when `shape` is not in
  `SHAPES`, `TypeError` when `blink` is not a `bool`. `write`: `TypeError` when `osc`
  is not an `Osc`. No `OSError` escapes (the [Writer] returns a {Closed}).
Effects: the builders none; `write` one write through the given writer.

Usage:
    from cure.edge.term.osc import title, clipboard, cursor, bell, write
    from cure.edge.term.writer import Writer
    buf = bytearray()
    write(Writer(sink=buf), title("cure"))  # buf == b"\\x1b]2;cure\\x1b\\\\"
    clipboard("hi").data                     # b"\\x1b]52;c;aGk=\\x1b\\\\"
    cursor("block", blink=True).data         # b"\\x1b[1 q"
    bell().data                              # b"\\x07"
"""

import base64
from dataclasses import dataclass

from cure.closed import Closed

KINDS = ("title", "clipboard", "cursor", "bell")
SHAPES = ("default", "block", "underline", "bar")

_ST = b"\x1b\\"
_TARGETS = ("c", "p")
_SHAPE_CODES = {"block": 1, "underline": 3, "bar": 5}


@dataclass(frozen=True)
class Osc:
    """{Osc}: one sequence the app asked for, with its kind's prepare and undo bytes."""

    kind: str
    data: bytes
    prepare: bytes = b""
    undo: bytes = b""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str):
            raise TypeError(f"kind must be a str, got {type(self.kind).__name__}")
        for name in ("data", "prepare", "undo"):
            value = getattr(self, name)
            if not isinstance(value, bytes):
                raise TypeError(f"{name} must be bytes, got {type(value).__name__}")
        if self.kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}, got {self.kind!r}")


def title(text: str) -> Osc:
    """Set the window title (OSC 2), control code points removed; undone by a title pop."""
    _check_text(text)
    clean = "".join(ch for ch in text if not _is_control(ch))
    return Osc("title", b"\x1b]2;" + clean.encode("utf-8") + _ST, b"\x1b[22;2t", b"\x1b[23;2t")


def clipboard(text: str, *, target: str = "c") -> Osc:
    """Copy `text` to the clipboard (OSC 52, base64); never a read of it."""
    _check_text(text)
    if target not in _TARGETS:
        raise ValueError(f"target must be one of {_TARGETS}, got {target!r}")
    payload = base64.standard_b64encode(text.encode("utf-8"))
    return Osc("clipboard", b"\x1b]52;" + target.encode() + b";" + payload + _ST)


def cursor(shape: str = "default", *, blink: bool = False) -> Osc:
    """The text cursor's shape (DECSCUSR); undone by `ESC [ 0 SP q`."""
    if shape not in SHAPES:
        raise ValueError(f"shape must be one of {SHAPES}, got {shape!r}")
    if not isinstance(blink, bool):
        raise TypeError(f"blink must be a bool, got {type(blink).__name__}")
    n = 0 if shape == "default" else _SHAPE_CODES[shape] + (0 if blink else 1)
    return Osc("cursor", f"\x1b[{n} q".encode(), b"", b"\x1b[0 q")


def bell() -> Osc:
    """The bell (BEL)."""
    return Osc("bell", b"\x07")


def write(writer, osc: Osc) -> "Closed | None":
    """Send `osc.data` through `writer` (the [Writer]); its result."""
    if not isinstance(osc, Osc):
        raise TypeError(f"expected an Osc, got {type(osc).__name__}")
    return writer.write(osc.data)


def _check_text(text: object) -> None:
    if not isinstance(text, str):
        raise TypeError(f"text must be a str, got {type(text).__name__}")
    if any("\ud800" <= ch <= "\udfff" for ch in text):
        raise ValueError("text must not hold a lone surrogate")


def _is_control(ch: str) -> bool:
    code = ord(ch)
    return code < 0x20 or 0x7F <= code < 0xA0
