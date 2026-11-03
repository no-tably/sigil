"""[Ansi]: interop only: ANSI text in, spans out.

Kind: service (a pure function from {Bytes} to {Text}).

What it does: `parse(data)` reads text that carries ANSI escape sequences (a
program's coloured output, a golden from another tool) and returns a {Text} of
styled spans. It only reads: cure never builds its own drawing by parsing SGR back
(Rules carried over), and nothing of the input's escapes survives as text. The
styles it makes are `AnsiStyle` values, plain data Text defines itself (Text may not
import Style); a consumer maps them by their attributes.

Decoding: `bytes` are decoded as UTF-8 with `errors="replace"` (each bad byte
sequence becomes U+FFFD); a `str` is read as is.

What each part of the input does:

- SGR, `ESC [ params m` (params separated by ";", sub-params by ":"; an empty param
  is 0): updates the current style. 0 resets every attribute and both colours (not
  `link`, which only OSC 8 changes). 1 bold, 2 dim, 3 italic, 4 underline (4:0
  off, 4:n for n >= 1 on), 5 and 6 blink, 7 reverse, 8 hidden, 9 strike, 21 underline;
  22 bold and dim off, 23 italic off, 24 underline off, 25 blink off, 27 reverse off,
  28 hidden off, 29 strike off. 30..37 fg index 0..7, 90..97 fg 8..15, 39 fg default;
  40..47 bg 0..7, 100..107 bg 8..15, 49 bg default. 38 / 48 extended colours:
  `38;5;n` (index), `38;2;r;g;b` (rgb), and the colon forms `38:5:n`,
  `38:2:r:g:b`, `38:2::r:g:b` (empty colour-space id); likewise 48. An index outside
  0..255 or a component outside 0..255 ignores that colour code; a 38/48 missing its
  numbers ends the processing of that sequence (codes before it stay applied).
  Every other code is ignored.
- OSC 8 hyperlinks, `ESC ] 8 ; params ; uri` ended by BEL or ST (`ESC \\`): sets
  `link` to `uri`, or clears it when `uri` is empty. A `uri` holding any control (C0
  U+0000..U+001F, DEL, C1 U+0080..U+009F), any lone surrogate (U+D800..U+DFFF) or any
  bidi formatting character ([Width]'s `BIDI`: U+061C, U+200E, U+200F,
  U+202A..U+202E, U+2066..U+2069) also clears it: the link is dropped and the text
  after it is kept, unlinked. So every link `parse` makes is one Style takes.
- Every other escape is dropped whole and never kept as text: other CSI sequences
  (`ESC [` ... a final byte 0x40..0x7E), other OSC, DCS, SOS, PM and APC strings
  (to BEL or ST, or to the end of the input when unterminated), and any other
  `ESC` + one character. A lone ESC at the end is dropped.
- "\\n" ends the line; "\\r\\n" also ends it (once); a lone "\\r" is dropped (no
  overprinting). "\\t" becomes spaces up to the next multiple of 8 columns of the
  line so far (measured in cells). Every other C0 control, DEL and every C1 control
  (U+0080..U+009F, so 8-bit CSI too) is dropped.
- Everything else is text, in the current style.

The style persists across lines (as on a terminal). Text in the default style (no
attribute, no colour, no link) gets style `None`; otherwise its `AnsiStyle`.
Lines are split as `str.split("\\n")` would: `parse("")` is `Text((Line(),))` and a
trailing newline gives a final empty line. Each line is in normal form (adjacent text
of `==` styles is one span; escapes that change nothing leave no seam).

Inputs: `data`: `bytes`, `bytearray` or `str` ({Bytes}).
Outputs: {Text}; spans' styles are `None` or `AnsiStyle`.
Errors: `TypeError` when `data` is none of those types. No content raises.
Effects: none.

Usage:
    from cure.core.text.ansi import parse, AnsiStyle
    parse(b"\\x1b[1;31mred\\x1b[0m plain")
    # Text((Line((Span("red", AnsiStyle(fg=1, bold=True)), Span(" plain"))),))
    parse("a\\x1b[2Kb\\tc")      # Text((Line.of("ab      c"),))
"""

from dataclasses import dataclass, replace

from . import spans
from .spans import Line, Span, Text
from .width import BIDI

@dataclass(frozen=True)
class AnsiStyle:
    """The SGR state a run of text was written in. `fg`, `bg`: None, an index
    0..255 (0..15 for the 16 named colours), or an `(r, g, b)` tuple of ints 0..255.
    `link`: an OSC 8 URI or None. `AnsiStyle()` is the default state, which
    `parse` reports as style `None`."""

    fg: "int | tuple[int, int, int] | None" = None
    bg: "int | tuple[int, int, int] | None" = None
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: bool = False
    blink: bool = False
    reverse: bool = False
    hidden: bool = False
    strike: bool = False
    link: "str | None" = None


def parse(data: "bytes | bytearray | str") -> Text:
    """The styled text in `data`, by the rules above."""
    if isinstance(data, (bytes, bytearray)):
        data = bytes(data).decode("utf-8", errors="replace")
    elif not isinstance(data, str):
        raise TypeError(f"expected bytes, bytearray or str, got {type(data).__name__}")
    lines: list[list[Span]] = [[]]
    style = AnsiStyle()
    i = 0
    while i < len(data):
        ch = data[i]
        if ch == _ESC:
            i, style = _escape(data, i, style)
            continue
        if ch == "\n":
            lines.append([])
        elif ch == "\t":
            col = spans.measure(Line(tuple(lines[-1])))
            _add(lines[-1], " " * (8 - col % 8), style)
        elif not _control(ch):
            j = i + 1
            while j < len(data) and data[j] not in (_ESC, "\n", "\t") and not _control(data[j]):
                j += 1
            _add(lines[-1], data[i:j], style)
            i = j
            continue
        i += 1
    return Text(tuple(spans.merge(Line(tuple(line))) for line in lines))


_ESC = "\x1b"
_BEL = "\x07"
_ST = "\x1b\\"
_STRINGS = "]PX^_"
_DEFAULT = AnsiStyle()

_ON = {1: ("bold", True), 2: ("dim", True), 3: ("italic", True), 4: ("underline", True),
       5: ("blink", True), 6: ("blink", True), 7: ("reverse", True), 8: ("hidden", True),
       9: ("strike", True), 21: ("underline", True), 23: ("italic", False),
       24: ("underline", False), 25: ("blink", False), 27: ("reverse", False),
       28: ("hidden", False), 29: ("strike", False), 39: ("fg", None), 49: ("bg", None)}


class _Stop(Exception):
    """A 38/48 missing its numbers: the rest of the sequence is not processed."""


def _control(ch: str) -> bool:
    code = ord(ch)
    return code < 0x20 or 0x7F <= code <= 0x9F


def _clean(uri: str) -> bool:
    """`uri` holds no control, lone surrogate or bidi formatting character (OSC 8 above)."""
    return not any(_control(ch) or "\ud800" <= ch <= "\udfff" or ch in BIDI for ch in uri)


def _add(line: list[Span], text: str, style: AnsiStyle) -> None:
    line.append(Span(text, None if style == _DEFAULT else style))


def _escape(data: str, i: int, style: AnsiStyle) -> tuple[int, AnsiStyle]:
    """Consume the escape at `data[i]` (an ESC); the index after it and the new style."""
    if i + 1 >= len(data):
        return len(data), style
    kind = data[i + 1]
    if kind == "[":
        return _csi(data, i + 2, style)
    if kind in _STRINGS:
        end, body = _string(data, i + 2)
        if kind == "]" and body.startswith("8;"):
            _, _, uri = body[2:].partition(";")
            style = replace(style, link=uri if uri and _clean(uri) else None)
        return end, style
    return i + 2, style


def _string(data: str, start: int) -> tuple[int, str]:
    """An OSC/DCS/SOS/PM/APC body from `start` to BEL or ST (or the end)."""
    bel = data.find(_BEL, start)
    st = data.find(_ST, start)
    ends = [(at, len(term)) for at, term in ((bel, _BEL), (st, _ST)) if at >= 0]
    if not ends:
        return len(data), data[start:]
    at, size = min(ends)
    return at + size, data[start:at]


def _csi(data: str, start: int, style: AnsiStyle) -> tuple[int, AnsiStyle]:
    j = start
    while j < len(data) and 0x20 <= ord(data[j]) <= 0x3F:
        j += 1
    if j >= len(data):
        return len(data), style
    if not 0x40 <= ord(data[j]) <= 0x7E:
        return j, style
    params = data[start:j]
    if data[j] == "m" and all(c in "0123456789;:" for c in params):
        style = _sgr(params, style)
    return j + 1, style


def _sgr(params: str, style: AnsiStyle) -> AnsiStyle:
    fields = [[int(n) if n else None for n in p.split(":")] for p in params.split(";")]
    k = 0
    try:
        while k < len(fields):
            subs = fields[k]
            code = subs[0] or 0
            k += 1
            if code in (38, 48):
                if len(subs) > 1:
                    colour = _colour_colon(subs[1:])
                else:
                    colour, k = _colour_semicolon(fields, k)
                if colour is not _BAD:
                    style = replace(style, **{"fg" if code == 38 else "bg": colour})
            else:
                style = _apply(style, code, subs[1:])
    except _Stop:
        pass
    return style


_BAD = object()


def _valid(*values) -> bool:
    return all(v is not None and 0 <= v <= 255 for v in values)


def _colour_colon(subs: list) -> object:
    if subs[0] == 5:
        if len(subs) < 2:
            raise _Stop
        return subs[1] if _valid(subs[1]) else _BAD
    if subs[0] == 2:
        if len(subs) < 4:
            raise _Stop
        rgb = tuple(subs[1:4] if len(subs) == 4 else subs[2:5])
        return rgb if _valid(*rgb) else _BAD
    raise _Stop


def _colour_semicolon(fields: list, k: int) -> tuple[object, int]:
    numbers = [f[0] or 0 for f in fields[k:k + 4]]
    if not numbers:
        raise _Stop
    if numbers[0] == 5:
        if len(numbers) < 2:
            raise _Stop
        return (numbers[1] if _valid(numbers[1]) else _BAD), k + 2
    if numbers[0] == 2:
        if len(numbers) < 4:
            raise _Stop
        rgb = tuple(numbers[1:4])
        return (rgb if _valid(*rgb) else _BAD), k + 4
    raise _Stop


def _apply(style: AnsiStyle, code: int, subs: list) -> AnsiStyle:
    if code == 0:
        return AnsiStyle(link=style.link)
    if code == 4 and subs:
        return replace(style, underline=bool(subs[0]))
    if code == 22:
        return replace(style, bold=False, dim=False)
    if 30 <= code <= 37:
        return replace(style, fg=code - 30)
    if 90 <= code <= 97:
        return replace(style, fg=code - 82)
    if 40 <= code <= 47:
        return replace(style, bg=code - 40)
    if 100 <= code <= 107:
        return replace(style, bg=code - 92)
    if code in _ON:
        name, value = _ON[code]
        return replace(style, **{name: value})
    return style
