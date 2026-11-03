"""[Parser]: one table-driven state machine (Williams): bytes in, actions out.

Kind: service (an incremental parser object and the `feed` op on it); pure.

Paul Williams' DEC ANSI parser (vt100.net/emu/dec_ansi_parser), table-driven, with
UTF-8 decoding in ground state; parser and screen apart (as vte / pyte). It provides
`feed` on top of [Performer] (`[Parser] -> [Performer] : feed({Bytes}) => {Actions}`):
it turns {Bytes} into the action values [Performer] defines and RETURNS them as a
tuple ({Actions}). It never calls a performer; `performer.dispatch` hands a tuple to
one. Used both ways: "output" reads what a program writes (V2's Screen), "input" reads
what a terminal sends for a person's keys, mouse, pastes and query replies (I1's
Decoder).

Invariant: pure — a Parser does no I/O, reads no clock, environment or process-wide
  state, and its actions depend only on its direction and the bytes it has been fed
  (with any `flush` calls between them). Two fresh parsers of one direction fed the same
  bytes give equal actions. Chunk independence: for any bytes `data` and any split of
  it into chunks `c1 .. cn` (empty chunks allowed), on fresh parsers `p` and `q`,
  `coalesce(p.feed(c1) + ... + p.feed(cn) + p.flush()) == coalesce(q.feed(data) +
  q.flush())`, and `p.state`, `p.pending` equal `q.state`, `q.pending` after the last
  feed. Each `feed` result is already coalesced (`coalesce(r) == r`); a `Print` (or
  `Put`) may only be split where a chunk ended. `feed(b"")` returns `()` and changes
  nothing.

## The object

- `Parser(direction="output")`: a fresh parser in ground state. `direction`: "output"
  or "input" (`DIRECTIONS`). `TypeError` when it is not a `str`, `ValueError` when it
  is neither. `parser.direction` reads it back.
- `parser.feed(data) -> tuple[Action, ...]`: the actions the bytes complete, in order,
  coalesced. `data`: `bytes`, `bytearray` or `memoryview`; `TypeError` otherwise (a
  `str` included). No byte sequence raises: every byte value in every state has a
  transition. What is unfinished at the end (a partial UTF-8 character, a sequence or
  string not yet ended) is held in the parser for the next call.
- `feed(parser, data) -> tuple[Action, ...]` (module function, the flow's op): the same
  as `parser.feed(data)`; `TypeError` when `parser` is not a `Parser`.
- `parser.state -> str`: the current state's name, one of `STATES`: the fourteen
  Williams states "ground", "escape", "escape_intermediate", "csi_entry", "csi_param",
  "csi_intermediate", "csi_ignore", "dcs_entry", "dcs_param", "dcs_intermediate",
  "dcs_passthrough", "dcs_ignore", "osc_string", "sos_pm_apc_string", and three an
  input-direction parser also uses: "ss3", "legacy_mouse", "paste". An output-direction
  parser is never in the last three.
- `parser.pending -> bool`: True when the parser holds bytes it has not given out as
  actions: any state but "ground", or "ground" with a partial UTF-8 character held.
  A lone ESC is pending exactly when `state == "escape"` (Input's Decoder tells a lone
  Esc key apart by its own `now`, then calls `flush`).
- `parser.flush() -> tuple[Action, ...]`: ends whatever is unfinished, as the end of
  the stream, and returns the parser to "ground" with nothing pending (see "Flush").
  On a parser with nothing pending it returns `()`.

## Bytes and text (both directions)

C1 controls are not recognised as 8-bit bytes: the stream is UTF-8, so bytes
0x80..0xFF are only ever UTF-8 (in ground) or string data (in OSC and DCS), never
CSI (0x9B), ST (0x9C) or any other C1 control. A code point U+0080..U+009F decoded from
UTF-8 is printed like any other character, never executed.

In "ground", bytes 0x20..0x7E and 0x80..0xFF are text, decoded as Python's UTF-8 codec
with `errors="replace"` decodes them (an incremental decoder: a character split across
chunks is held, then given whole). Each maximal ill-formed subpart becomes one U+FFFD,
exactly as `bytes.decode("utf-8", "replace")` does (`b"\\xff"` one, `b"\\xc0\\x80"`
two, `b"\\xed\\xa0\\x80"` three, `b"\\xe4\\xb8"` then a non-continuation byte one). A
C0 byte, DEL or ESC arriving inside a partial character ends it: the U+FFFD is given
first, then that byte's action. So for bytes with no ESC, CAN or SUB, the joined
`Print` texts equal `data.decode("utf-8", "replace")` with its C0 and DEL characters
removed, and those characters arrive as `Execute`s in their places.

Text in ground is given as `Print`; within one `feed`, adjacent text is one `Print`
(it is coalesced: an `Execute` or any other action between two runs separates them).

## Params (CSI, DCS, SS3)

The parameter bytes 0x30..0x3B ("0".."9", ":", ";") of a sequence are collected and
read as: split on ";" into parameters, each split on ":" into sub-parameters (as SGR
`4:3` and kitty keys use), each an `int` of its decimal digits, or `None` when empty.
No parameter bytes give `params == ()`. `CSI m` → `()`; `CSI 1;31m` →
`((1,), (31,))`; `CSI ;m` → `((None,), (None,))`; `CSI 4:3m` → `((4, 3),)`;
`CSI 38:2::255:0:0m` → `((38, 2, None, 255, 0, 0),)`. A value saturates at
`MAX_VALUE` (2**31 - 1): more digits never raise or wrap.

Limits, and what overflow does:
- at most `MAX_PARAMS` (32) values per sequence, counting every sub-parameter (and an
  empty one): a sequence that opens a 33rd value (its 32nd ";" or ":") is not
  dispatched (CSI goes to "csi_ignore", DCS to "dcs_ignore", an SS3 is dropped);
- at most `MAX_INTERMEDIATES` (2) intermediates: a third makes the sequence not
  dispatched (CSI to "csi_ignore", DCS to "dcs_ignore"; an ESC sequence is dropped when
  its final byte arrives);
- an OSC's data at most `MAX_OSC` (1 MiB, 1048576) bytes: a longer one is not
  dispatched when it ends (the bytes past the limit are not kept);
- a DCS's data is streamed as `Put`s and a paste has no limit (it is the person's own).

## The table (output direction)

"C0" below is 0x00..0x17, 0x19, 0x1C..0x1F (every C0 but CAN, SUB and ESC).

Anywhere (in every state, before the state's own rows):
- 0x18 CAN, 0x1A SUB: cancel what is in progress (an unfinished OSC or sequence is
  dropped; in "dcs_passthrough" `Unhook()` is given first), give `Execute(code)`,
  go to "ground".
- 0x1B ESC: end what is in progress (in "osc_string" the `Osc(data, bel=False)` is given,
  unless over `MAX_OSC`; in "dcs_passthrough" `Unhook()`; a sequence is dropped), go to
  "escape". When this ESC ended a string ("osc_string", "dcs_passthrough", "dcs_ignore",
  "sos_pm_apc_string"), a "\\" (0x5C) right after it is taken as the rest of ST and
  gives nothing (no `Esc`); any other byte after it is read in "escape" as usual.

ground: C0 and 0x7F → `Execute`; text as above → `Print`.

escape: C0 → `Execute`, stay. 0x20..0x2F → intermediate, "escape_intermediate".
"[" → "csi_entry". "]" → "osc_string". "P" → "dcs_entry". "X", "^", "_" →
"sos_pm_apc_string". Any other byte 0x30..0x7E → `Esc(final)`, "ground" ("O" too:
SS3 is an `Esc` in this direction). 0x7F, 0x80..0xFF: ignored, stay.

escape_intermediate: C0 → `Execute`. 0x20..0x2F → intermediate. 0x30..0x7E →
`Esc(final, intermediates)` (nothing when over the limit), "ground". 0x7F, 0x80..0xFF:
ignored.

csi_entry: C0 → `Execute`. 0x20..0x2F → intermediate, "csi_intermediate".
0x30..0x3B → parameter byte, "csi_param". 0x3C..0x3F → `private`, "csi_param".
0x40..0x7E → `Csi(...)`, "ground". 0x7F, 0x80..0xFF: ignored.

csi_param: C0 → `Execute`. 0x30..0x3B → parameter byte. 0x3C..0x3F → "csi_ignore".
0x20..0x2F → intermediate, "csi_intermediate". 0x40..0x7E → `Csi(...)`, "ground".
0x7F, 0x80..0xFF: ignored.

csi_intermediate: C0 → `Execute`. 0x20..0x2F → intermediate. 0x30..0x3F →
"csi_ignore". 0x40..0x7E → `Csi(...)`, "ground". 0x7F, 0x80..0xFF: ignored.

csi_ignore: C0 → `Execute`. 0x40..0x7E → "ground", nothing given. Everything else
ignored.

dcs_entry, dcs_param, dcs_intermediate: as the three CSI states, except that C0 is
ignored (not executed), the CSI states' "csi_ignore" is "dcs_ignore", and a final
byte 0x40..0x7E gives `Hook(final, params, private, intermediates)` and goes to
"dcs_passthrough".

dcs_passthrough: C0, 0x20..0x7E and 0x80..0xFF → data, given as `Put` (adjacent data
in one feed is one `Put`). 0x7F ignored. Left only through Anywhere (`Unhook()`).

dcs_ignore: everything ignored, until Anywhere.

osc_string: 0x07 BEL → `Osc(data, bel=True)` (unless over `MAX_OSC`), "ground".
Other C0 ignored. 0x20..0xFF (0x7F included) → data. ESC → see Anywhere.

sos_pm_apc_string: everything ignored until Anywhere; SOS, PM and APC give no action.

## The input direction

`Parser("input")` reads what a terminal sends, where ESC also prefixes Alt and a
person's paste must stay text. It follows the table above except:

1. escape (these rows come before Anywhere): every byte but ESC and the five
   introducers "[", "]", "P", "_", "O" gives
   `Esc(chr(byte))` and goes to "ground": C0 (CAN and SUB included: Alt-Ctrl-X is
   `Esc("\\x18")`), 0x20..0x2F (Alt-Space is `Esc(" ")`, no intermediates in this
   direction), 0x30..0x7E (Alt-a `Esc("a")`, "X" and "^" included: no SOS or PM
   here), 0x7F (Alt-Backspace `Esc("\\x7f")`). A byte 0x80..0xFF starts one UTF-8
   character (still in "escape", pending): complete and valid it gives `Esc(char)`
   (Alt-é is `Esc("é")`); ill-formed it gives `Esc("\\ufffd")` and the byte that broke
   it (if any) is read again in "ground" (`ESC E4 41` → `Esc("\\ufffd")`, `Print("A")`).
   "\\" after a string's ESC is still swallowed as ST.
2. ESC in "escape" after a lone ESC (no byte after it yet, and it did not end a
   string): the first ESC gives `Execute(0x1B)` and the parser stays in "escape" for
   the second. After an ESC that ended a string, a second ESC gives nothing for the
   first.
3. "O" in escape → "ss3": parameter bytes 0x30..0x3B are collected; a byte 0x40..0x7E
   gives `Ss3(final, params)`, "ground" (`ESC O A` → `Ss3("A")`, `ESC O 2 P` →
   `Ss3("P", ((2,),))`). Any other byte ends it unfinished: with no parameter byte
   collected it gives `Esc("O")` (Alt-Shift-O), else nothing; then that byte is read
   in "ground" (so ESC, CAN and SUB act as Anywhere).
4. A `Csi("M")` with no params, private or intermediates is not given: the parser goes
   to "legacy_mouse" and takes the next three bytes, whatever they are (no Anywhere
   here), as
   `LegacyMouse(cb, cx, cy)`, then "ground".
5. A `Csi("~", ((200,),))` with no private or intermediates is not given: the parser
   goes to "paste" and keeps every byte as paste data until the exact bytes
   `ESC [ 2 0 1 ~` (1B 5B 32 30 31 7E), which it does not keep; it then gives
   `Pasted(data.decode("utf-8", "replace"))` and goes to "ground". In "paste" nothing
   else is recognised (no Anywhere, no controls): an ESC, a CAN, a `CSI 200~` are paste
   data. A partial end marker split across chunks is held; one that turns out not to
   be the marker is data. An empty paste gives `Pasted("")`. A `CSI 201~` outside a
   paste is an ordinary `Csi("~", ((201,),))`.

Everything else is as in the output direction, DEL in ground (`Execute(0x7F)`, the
Backspace key) and NUL (`Execute(0)`, Ctrl-Space) included. Query replies (DA1
`CSI ? 62;22c`, CPR `CSI 12;5R`, DECRPM `CSI ? 2026;2$y`, kitty `CSI ? 1u`) arrive as
`Csi`; OSC replies as `Osc`; XTGETTCAP and XTVERSION replies as `Hook`/`Put`/`Unhook`;
SGR mouse (`CSI < 0;10;5M`), kitty keys (`CSI 97;5u`, `CSI 97:65;2u`) and focus
(`CSI I`, `CSI O`) as `Csi`. Telling a key from a reply is the Decoder's job.

## Flush

Output direction: a partial UTF-8 character gives `Print("\\ufffd")`;
"dcs_passthrough" gives `Unhook()`; every other unfinished sequence or string is
dropped.

Input direction, by what is pending:
- a partial UTF-8 character in ground: `Print("\\ufffd")`;
- "escape" right after a lone ESC: `Execute(0x1B)` (the Esc key); right after an ESC
  that ended a string (ST pending): nothing;
- "escape" holding a partial UTF-8 character after the ESC: `Esc("\\ufffd")`;
- "paste": `Pasted(...)` of the data so far, held marker bytes included as data;
- "dcs_passthrough": `Unhook()`, as in the output direction (its `Hook` and `Put`s
  were already given out);
- any other state ("ss3", "legacy_mouse", the CSI, DCS entry, OSC and string
  states): the bytes from its ESC on, less any already given out (an `Execute` given inside a
  sequence is not given again), are reread with the ESC taken as Alt: `Esc(chr(b1))`
  for the byte after the ESC (`ESC [` → `Esc("[")`, `ESC O` → `Esc("O")`), then the
  rest is fed again from "ground"; this repeats until nothing is pending.
  `ESC [ 1 ;` flushed → `Esc("[")`, `Print("1;")`.
The result is coalesced, and the parser is in "ground" with nothing pending.

Inputs: {Bytes} (`bytes`, `bytearray`, `memoryview`). Outputs: {Actions}, a tuple of
[Performer]'s action values. Errors: `TypeError` for a wrong argument type,
`ValueError` for an unknown direction; never on any byte content. Effects: none, apart
from the state the parser object keeps for its own stream.

Usage:
    from cure.interact.vt.parser import Parser, feed
    from cure.interact.vt.performer import Print, Execute, Csi, Esc, Osc, Ss3, Pasted
    p = Parser()
    p.feed(b"\\x1b[1;31mred\\x1b[0m\\r\\n")
    # (Csi("m", ((1,), (31,))), Print("red"), Csi("m", ((0,),)), Execute(13), Execute(10))
    p.feed(b"\\xe4\\xb8")                  # (): the character is held; p.pending is True
    p.feed(b"\\xad\\x1b]0;hi\\x07")        # (Print("中"), Osc(b"0;hi", bel=True))
    p.feed(b"\\x1b[?25h")                  # (Csi("h", ((25,),), private="?"),)
    i = Parser("input")
    i.feed(b"\\x1b")                       # (); i.state == "escape", i.pending is True
    i.flush()                              # (Execute(0x1B),): the Esc key
    i.feed(b"\\x1bOA\\x1ba\\x1b[1;5A")      # (Ss3("A"), Esc("a"), Csi("A", ((1,), (5,))))
    i.feed(b"\\x1b[200~a\\x1b[Bb\\x1b[201~")  # (Pasted("a\\x1b[Bb"),)
"""

import re
from codecs import utf_8_decode as _utf8_decode

from .performer import Action, Csi, Esc, Execute, Hook, LegacyMouse, Osc, Pasted, Print, Put, Ss3, Unhook

DIRECTIONS = ("output", "input")

STATES = (
    "ground", "escape", "escape_intermediate",
    "csi_entry", "csi_param", "csi_intermediate", "csi_ignore",
    "dcs_entry", "dcs_param", "dcs_intermediate", "dcs_passthrough", "dcs_ignore",
    "osc_string", "sos_pm_apc_string",
    "ss3", "legacy_mouse", "paste",
)

MAX_PARAMS = 32
MAX_INTERMEDIATES = 2
MAX_OSC = 1 << 20
MAX_VALUE = 2**31 - 1


class Parser:
    """An incremental Williams parser for one stream, in one direction (see the module)."""

    __slots__ = (
        "_direction", "_input", "_table", "_runs", "_st", "_out", "_held", "_alt",
        "_pbuf", "_nsep", "_private", "_inter", "_inter_over", "_osc", "_osc_over",
        "_mouse", "_paste", "_raw", "_cache",
    )

    def __init__(self, direction: str = "output") -> None:
        if not isinstance(direction, str):
            raise TypeError(f"direction must be a str, got {type(direction).__name__}")
        if direction not in DIRECTIONS:
            raise ValueError(f"direction must be one of {DIRECTIONS}, got {direction!r}")
        self._direction = direction
        self._input = direction == "input"
        self._table = _INPUT_TABLE if self._input else _OUTPUT_TABLE
        self._runs = _INPUT_RUNS if self._input else _OUTPUT_RUNS
        self._st = _GROUND
        self._out: list = []           # the actions of the feed (or flush) in progress
        self._held = b""               # ground: the start of a UTF-8 character, held
        self._alt = bytearray()        # input: a UTF-8 character after ESC, arriving
        self._pbuf = bytearray()       # parameter bytes of a CSI, DCS or SS3
        self._nsep = 0                 # the ";" and ":" among them
        self._private = ""
        self._inter = ""
        self._inter_over = False       # an ESC sequence had a third intermediate
        self._osc = bytearray()
        self._osc_over = False         # the OSC passed MAX_OSC
        self._mouse = bytearray()      # input: the X10 report's bytes so far
        self._paste = bytearray()      # input: the paste's bytes so far
        self._raw = bytearray() if self._input else None  # input: bytes since the ESC, for flush
        self._cache: dict = {}         # CSI actions already built, by their bytes

    @property
    def direction(self) -> str:
        """"output" or "input", as constructed."""
        return self._direction

    @property
    def state(self) -> str:
        """The current state's name, one of `STATES`."""
        return _NAMES[self._st]

    @property
    def pending(self) -> bool:
        """True when bytes are held that have not been given out as actions."""
        return self._st != _GROUND or bool(self._held)

    def feed(self, data: "bytes | bytearray | memoryview") -> "tuple[Action, ...]":
        """The actions these bytes complete, in order, coalesced (see the module)."""
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError(f"data must be bytes-like, got {type(data).__name__}")
        if type(data) is not bytes:
            data = bytes(data)
        self._out = out = []
        self._run(data)
        self._out = []
        return tuple(out)

    def flush(self) -> "tuple[Action, ...]":
        """End whatever is unfinished; back to ground with nothing pending (see the module)."""
        self._out = out = []
        while True:
            st = self._st
            if st == _GROUND:
                if self._held:
                    _end_text(self)
                break
            if st == _DCS_PASSTHROUGH:
                out.append(_UNHOOK)
            elif self._input:
                if st == _ESCAPE:
                    out.append(_EXECUTE[_ESC])          # a lone ESC: the Esc key
                elif st == _ESCAPE_UTF8:
                    out.append(Esc(_REPLACEMENT))
                elif st == _PASTE:
                    out.append(Pasted(self._paste.decode("utf-8", "replace")))
                elif st != _ESCAPE_ST:
                    # Reread the sequence with its ESC taken as Alt, the rest from ground.
                    raw = bytes(self._raw)
                    self._reset()
                    out.append(Esc(chr(raw[0])))
                    self._run(raw[1:])
                    continue
            self._reset()
            break
        self._out = []
        return tuple(out)

    def _run(self, data: bytes) -> None:
        """Take `data` through the table, appending its actions to `self._out`."""
        table, runs, raw = self._table, self._runs, self._raw
        i, n = 0, len(data)
        while i < n:
            st = self._st
            run = runs[st]
            if run is not None:
                i = run(self, data, i)
                if i >= n:
                    break
                if self._st != st:
                    continue
            b = data[i]
            action, self._st = table[st][b]
            if raw is not None and _SEQUENCE[st] and action is not _execute:
                raw.append(b)
            if action is None or not action(self, b):
                i += 1

    def _reset(self) -> None:
        """Back to ground with nothing held (leaving ground already emptied the decoder)."""
        self._st = _GROUND
        self._alt.clear()
        self._pbuf.clear()
        self._osc.clear()
        self._mouse.clear()
        self._paste.clear()
        if self._raw is not None:
            self._raw.clear()


def feed(parser: Parser, data: "bytes | bytearray | memoryview") -> "tuple[Action, ...]":
    """`parser.feed(data)` (see the module)."""
    if not isinstance(parser, Parser):
        raise TypeError(f"parser must be a Parser, got {type(parser).__name__}")
    return parser.feed(data)


# -- states: indexes into STATES, and two more that read as "escape"

(_GROUND, _ESCAPE, _ESCAPE_INTERMEDIATE,
 _CSI_ENTRY, _CSI_PARAM, _CSI_INTERMEDIATE, _CSI_IGNORE,
 _DCS_ENTRY, _DCS_PARAM, _DCS_INTERMEDIATE, _DCS_PASSTHROUGH, _DCS_IGNORE,
 _OSC_STRING, _SOS_PM_APC_STRING,
 _SS3, _LEGACY_MOUSE, _PASTE) = range(len(STATES))
_ESCAPE_ST = len(STATES)        # right after an ESC that ended a string: "\\" completes ST
_ESCAPE_UTF8 = _ESCAPE_ST + 1   # input: a UTF-8 character after ESC (Alt) is arriving
_NAMES = STATES + ("escape", "escape")

# The states an input-direction parser keeps its bytes in, for flush's reread.
_SEQUENCE = tuple(st not in (_GROUND, _DCS_PASSTHROUGH, _PASTE) for st in range(len(_NAMES)))

_ESC, _CAN, _SUB, _BEL, _DEL = 0x1B, 0x18, 0x1A, 0x07, 0x7F
_C0 = [b for b in range(0x20) if b not in (_CAN, _SUB, _ESC)]
_REPLACEMENT = "�"
_PASTE_END = b"\x1b[201~"
_CACHE_SIZE = 4096

_EXECUTE = tuple(Execute(code) for code in range(0x80))
_UNHOOK = Unhook()
_BYTE = tuple(bytes((b,)) for b in range(256))


# -- emitting

def _print(p: Parser, text: str) -> None:
    """Give text, joined to a `Print` just given (so a feed's result stays coalesced)."""
    out = p._out
    if out and type(out[-1]) is Print:
        out[-1] = Print(out[-1].text + text)
    else:
        out.append(Print(text))


def _put_data(p: Parser, data: bytes) -> None:
    out = p._out
    if out and type(out[-1]) is Put:
        out[-1] = Put(out[-1].data + data)
    else:
        out.append(Put(data))


def _text(p: Parser, chunk: bytes) -> None:
    """Ground text, decoded as an incremental UTF-8 decoder would: a partial character
    at the end is held for the next bytes."""
    if p._held:
        chunk = p._held + chunk
    text, used = _utf8_decode(chunk, "replace", False)
    p._held = chunk[used:]
    if text:
        _print(p, text)


def _end_text(p: Parser) -> None:
    """A control arrived inside a partial character: give its U+FFFD first."""
    text = _utf8_decode(p._held, "replace", True)[0]
    p._held = b""
    if text:
        _print(p, text)


def _params(raw: bytes) -> "tuple[tuple[int | None, ...], ...]":
    """Parameter bytes read as ";"-separated parameters of ":"-separated values."""
    if not raw:
        return ()
    if b":" not in raw:
        return tuple((_value(v),) for v in raw.split(b";"))
    return tuple(tuple(map(_value, part.split(b":"))) for part in raw.split(b";"))


def _value(digits: bytes) -> "int | None":
    if len(digits) < 10:                # below MAX_VALUE whatever the digits
        return int(digits) if digits else None
    digits = digits.lstrip(b"0")
    if len(digits) > 10:
        return MAX_VALUE
    return min(int(digits or b"0"), MAX_VALUE)


# -- actions: `action(parser, byte)`, run after the table set the next state; an action
#    may set another, and returns True when the byte is to be read again (in ground).

def _execute(p: Parser, b: int) -> None:
    p._out.append(_EXECUTE[b])


def _print_byte(p: Parser, b: int) -> None:
    _text(p, _BYTE[b])


def _ground_execute(p: Parser, b: int) -> None:
    if p._held:
        _end_text(p)
    p._out.append(_EXECUTE[b])


def _ground_esc(p: Parser, b: int) -> None:
    if p._held:
        _end_text(p)
    _esc_enter(p, b)


def _esc_enter(p: Parser, b: int) -> None:
    """ESC: whatever was in progress is dropped; a new escape sequence starts."""
    p._inter = ""
    p._inter_over = False
    if p._raw is not None:
        p._raw.clear()


def _esc_osc(p: Parser, b: int) -> None:
    if not p._osc_over:
        p._out.append(Osc(bytes(p._osc), False))
    _esc_enter(p, b)


def _esc_dcs(p: Parser, b: int) -> None:
    p._out.append(_UNHOOK)
    _esc_enter(p, b)


def _cancel_dcs(p: Parser, b: int) -> None:
    p._out.append(_UNHOOK)
    p._out.append(_EXECUTE[b])


def _esc_collect(p: Parser, b: int) -> None:
    if len(p._inter) >= MAX_INTERMEDIATES:
        p._inter_over = True
    else:
        p._inter += chr(b)


def _esc_dispatch(p: Parser, b: int) -> None:
    if not p._inter_over:
        p._out.append(Esc(chr(b), p._inter))


def _seq_enter(p: Parser, b: int) -> None:
    """"[", "P" (and "O" for input): a CSI, DCS (or SS3) starts collecting."""
    p._pbuf.clear()
    p._nsep = 0
    p._private = ""


def _collect_param(p: Parser, b: int) -> bool:
    """Keep a parameter byte; True when it opened one value too many."""
    p._pbuf.append(b)
    if b >= 0x3A:
        p._nsep += 1
        return p._nsep >= MAX_PARAMS
    return False


def _csi_param(p: Parser, b: int) -> None:
    if _collect_param(p, b):
        p._st = _CSI_IGNORE


def _dcs_param(p: Parser, b: int) -> None:
    if _collect_param(p, b):
        p._st = _DCS_IGNORE


def _private(p: Parser, b: int) -> None:
    p._private = chr(b)


def _csi_collect(p: Parser, b: int) -> None:
    if len(p._inter) >= MAX_INTERMEDIATES:
        p._st = _CSI_IGNORE
    else:
        p._inter += chr(b)


def _dcs_collect(p: Parser, b: int) -> None:
    if len(p._inter) >= MAX_INTERMEDIATES:
        p._st = _DCS_IGNORE
    else:
        p._inter += chr(b)


def _csi_dispatch(p: Parser, b: int) -> None:
    key = (bytes(p._pbuf), p._private, p._inter, b)
    action = p._cache.get(key)
    if action is None:
        action = Csi(chr(b), _params(key[0]), p._private, p._inter)
        if len(p._cache) < _CACHE_SIZE:
            p._cache[key] = action
    p._out.append(action)


def _hook(p: Parser, b: int) -> None:
    p._out.append(Hook(chr(b), _params(bytes(p._pbuf)), p._private, p._inter))


def _put(p: Parser, b: int) -> None:
    _put_data(p, _BYTE[b])


def _osc_enter(p: Parser, b: int) -> None:
    p._osc.clear()
    p._osc_over = False


def _osc_put(p: Parser, b: int) -> None:
    if len(p._osc) < MAX_OSC:
        p._osc.append(b)
    else:
        p._osc_over = True


def _osc_bel(p: Parser, b: int) -> None:
    if not p._osc_over:
        p._out.append(Osc(bytes(p._osc), True))


# input direction

def _csi_dispatch_input(p: Parser, b: int) -> None:
    """As `_csi_dispatch`, but `CSI M` starts an X10 report and `CSI 200~` a paste."""
    if not p._private and not p._inter:
        if b == 0x4D and not p._pbuf:
            p._mouse.clear()
            p._st = _LEGACY_MOUSE
            return
        if b == 0x7E and _params(bytes(p._pbuf)) == ((200,),):
            p._paste.clear()
            p._st = _PASTE
            return
    _csi_dispatch(p, b)


def _alt(p: Parser, b: int) -> None:
    p._out.append(Esc(chr(b)))


def _lone_esc(p: Parser, b: int) -> None:
    """ESC after a lone ESC: the first was the Esc key; this one starts again."""
    p._out.append(_EXECUTE[_ESC])
    _esc_enter(p, b)


def _alt_lead(p: Parser, b: int) -> None:
    """A byte 0x80..0xFF after ESC: the lead of an Alt-modified character."""
    if _UTF8_LEAD[b] is None:
        p._out.append(Esc(_REPLACEMENT))
        p._st = _GROUND
    else:
        p._alt.append(b)


def _alt_more(p: Parser, b: int) -> bool:
    alt = p._alt
    need, lo, hi = _UTF8_LEAD[alt[0]]
    if len(alt) > 1:
        lo, hi = 0x80, 0xBF
    if not lo <= b <= hi:
        alt.clear()
        p._out.append(Esc(_REPLACEMENT))
        p._st = _GROUND
        return True
    alt.append(b)
    if len(alt) == need + 1:
        p._out.append(Esc(alt.decode()))
        alt.clear()
        p._st = _GROUND
    return False


def _ss3_param(p: Parser, b: int) -> None:
    _collect_param(p, b)


def _ss3_dispatch(p: Parser, b: int) -> None:
    if p._nsep < MAX_PARAMS:
        p._out.append(Ss3(chr(b), _params(bytes(p._pbuf))))


def _ss3_end(p: Parser, b: int) -> bool:
    """Any other byte ends an SS3 unfinished; it is read again in ground."""
    if not p._pbuf:
        p._out.append(Esc("O"))
    return True


def _mouse_byte(p: Parser, b: int) -> None:
    mouse = p._mouse
    mouse.append(b)
    if len(mouse) == 3:
        p._out.append(LegacyMouse(mouse[0], mouse[1], mouse[2]))
        mouse.clear()
        p._st = _GROUND


# A UTF-8 lead byte: (continuation bytes it needs, the range of the first of them),
# or None when it cannot start a character.
_UTF8_LEAD: "list[tuple[int, int, int] | None]" = [None] * 256
for _b in range(0xC2, 0xE0):
    _UTF8_LEAD[_b] = (1, 0x80, 0xBF)
for _b in range(0xE0, 0xF0):
    _UTF8_LEAD[_b] = (2, 0xA0 if _b == 0xE0 else 0x80, 0x9F if _b == 0xED else 0xBF)
for _b in range(0xF0, 0xF5):
    _UTF8_LEAD[_b] = (3, 0x90 if _b == 0xF0 else 0x80, 0x8F if _b == 0xF4 else 0xBF)


# -- runs: in some states a whole run of bytes takes one step; `run(parser, data, i)`
#    consumes from `i` and returns where it stopped (the same table rows, taken at once).

_OSC_DATA = re.compile(rb"[\x20-\xff]+")
_DCS_DATA = re.compile(rb"[^\x18\x1a\x1b\x7f]+")
_STRING_SKIP = re.compile(rb"[^\x18\x1a\x1b]+")
_CSI_SKIP = re.compile(rb"[\x20-\x3f\x7f-\xff]+")


# Ground's tokens taken at once: a text run, a run of controls (C0 but ESC, and DEL),
# and (output direction) a whole CSI the table would take straight through: ESC [, an
# optional private marker, parameter bytes, at most two intermediates, a final byte.
_GROUND_INPUT = re.compile(rb"([\x20-\x7e\x80-\xff]+)|([\x00-\x1a\x1c-\x1f\x7f]+)")
_GROUND_OUTPUT = re.compile(_GROUND_INPUT.pattern + rb"|\x1b\[([\x3c-\x3f]?)([\x30-\x3b]*)"
                            rb"([\x20-\x2f]{0,2})([\x40-\x7e])")


def _ground_run(p: Parser, data: bytes, i: int) -> int:
    """Ground's rows for a run of tokens, taken at once (see `_GROUND_OUTPUT`).

    It stops before anything else (an ESC starting another sequence, an unfinished
    CSI, one with too many values), which the table then reads byte by byte. The text
    path is `_text` and `_print`, inlined: this loop carries most of a session."""
    out, cache, held = p._out, p._cache, p._held
    tokens = (_GROUND_INPUT if p._input else _GROUND_OUTPUT).scanner(data, i)
    last = None
    for m in iter(tokens.match, None):
        kind = m.lastindex
        if kind == 1:
            chunk = m.group(1)
            if held:
                chunk = held + chunk
            text, used = _utf8_decode(chunk, "replace", False)
            held = chunk[used:]
            if text:
                if out and type(out[-1]) is Print:
                    out[-1] = Print(out[-1].text + text)
                else:
                    out.append(Print(text))
            last = m
            continue
        if kind == 2:
            action = None
        else:
            key = m.group()
            action = cache.get(key)
            if action is None:
                private, params, inter, final = m.group(3, 4, 5, 6)
                if params.count(b";") + params.count(b":") >= MAX_PARAMS:
                    p._held = held
                    return m.start()
                action = Csi(chr(final[0]), _params(params), private.decode(), inter.decode())
                if len(cache) < _CACHE_SIZE:
                    cache[key] = action
        if held:
            p._held = held
            _end_text(p)
            held = b""
        if action is None:
            out += map(_EXECUTE.__getitem__, m.group(2))
        else:
            out.append(action)
        last = m
    p._held = held
    return i if last is None else last.end()


def _osc_run(p: Parser, data: bytes, i: int) -> int:
    m = _OSC_DATA.match(data, i)
    if m is None:
        return i
    chunk = m.group()
    if p._raw is not None:
        p._raw += chunk
    room = MAX_OSC - len(p._osc)
    if len(chunk) > room:
        p._osc += chunk[:room]
        p._osc_over = True
    else:
        p._osc += chunk
    return m.end()


def _dcs_run(p: Parser, data: bytes, i: int) -> int:
    m = _DCS_DATA.match(data, i)
    if m is None:
        return i
    _put_data(p, m.group())
    return m.end()


def _skip_run(pattern: "re.Pattern[bytes]"):
    def run(p: Parser, data: bytes, i: int) -> int:
        m = pattern.match(data, i)
        if m is None:
            return i
        if p._raw is not None:
            p._raw += m.group()
        return m.end()
    return run


def _paste_run(p: Parser, data: bytes, i: int) -> int:
    """Keep paste bytes up to the end marker, which may have begun in an earlier feed."""
    buf = p._paste
    tail = bytes(buf[-(len(_PASTE_END) - 1):])
    if tail:
        k = (tail + data[i:i + len(_PASTE_END) - 1]).find(_PASTE_END)
        if k >= 0:
            del buf[len(buf) - len(tail) + k:]
            return _paste_end(p, i + k + len(_PASTE_END) - len(tail))
    k = data.find(_PASTE_END, i)
    if k < 0:
        buf += data[i:]
        return len(data)
    buf += data[i:k]
    return _paste_end(p, k + len(_PASTE_END))


def _paste_end(p: Parser, after: int) -> int:
    p._out.append(Pasted(p._paste.decode("utf-8", "replace")))
    p._paste.clear()
    p._st = _GROUND
    return after


# -- the tables: `table[state][byte] == (action or None, next state)`

def _output_table() -> list:
    t = [[(None, st)] * 256 for st in range(len(_NAMES))]

    def rows(st, lo, hi, entry):
        for b in range(lo, hi + 1):
            t[st][b] = entry

    def c0(st, entry):
        for b in _C0:
            t[st][b] = entry

    rows(_GROUND, 0x20, 0xFF, (_print_byte, _GROUND))
    c0(_GROUND, (_ground_execute, _GROUND))
    t[_GROUND][_DEL] = (_ground_execute, _GROUND)

    c0(_ESCAPE, (_execute, _ESCAPE))
    rows(_ESCAPE, 0x20, 0x2F, (_esc_collect, _ESCAPE_INTERMEDIATE))
    rows(_ESCAPE, 0x30, 0x7E, (_esc_dispatch, _GROUND))
    t[_ESCAPE][ord("[")] = (_seq_enter, _CSI_ENTRY)
    t[_ESCAPE][ord("]")] = (_osc_enter, _OSC_STRING)
    t[_ESCAPE][ord("P")] = (_seq_enter, _DCS_ENTRY)
    for intro in "X^_":
        t[_ESCAPE][ord(intro)] = (None, _SOS_PM_APC_STRING)
    t[_ESCAPE_ST] = [(a, _ESCAPE if st == _ESCAPE else st) for a, st in t[_ESCAPE]]
    t[_ESCAPE_ST][ord("\\")] = (None, _GROUND)

    c0(_ESCAPE_INTERMEDIATE, (_execute, _ESCAPE_INTERMEDIATE))
    rows(_ESCAPE_INTERMEDIATE, 0x20, 0x2F, (_esc_collect, _ESCAPE_INTERMEDIATE))
    rows(_ESCAPE_INTERMEDIATE, 0x30, 0x7E, (_esc_dispatch, _GROUND))

    for entry, param, inter, ignore, collect, param_action, final, run_c0 in (
        (_CSI_ENTRY, _CSI_PARAM, _CSI_INTERMEDIATE, _CSI_IGNORE, _csi_collect, _csi_param,
         (_csi_dispatch, _GROUND), True),
        (_DCS_ENTRY, _DCS_PARAM, _DCS_INTERMEDIATE, _DCS_IGNORE, _dcs_collect, _dcs_param,
         (_hook, _DCS_PASSTHROUGH), False),
    ):
        for st in (entry, param, inter, ignore):
            if run_c0:
                c0(st, (_execute, st))
        for st in (entry, param, inter):
            rows(st, 0x20, 0x2F, (collect, inter))
            rows(st, 0x40, 0x7E, final)
        rows(entry, 0x30, 0x3B, (param_action, param))
        rows(entry, 0x3C, 0x3F, (_private, param))
        rows(param, 0x30, 0x3B, (param_action, param))
        rows(param, 0x3C, 0x3F, (None, ignore))
        rows(inter, 0x30, 0x3F, (None, ignore))
    rows(_CSI_IGNORE, 0x40, 0x7E, (None, _GROUND))

    c0(_DCS_PASSTHROUGH, (_put, _DCS_PASSTHROUGH))
    rows(_DCS_PASSTHROUGH, 0x20, 0x7E, (_put, _DCS_PASSTHROUGH))
    rows(_DCS_PASSTHROUGH, 0x80, 0xFF, (_put, _DCS_PASSTHROUGH))

    rows(_OSC_STRING, 0x20, 0xFF, (_osc_put, _OSC_STRING))
    t[_OSC_STRING][_BEL] = (_osc_bel, _GROUND)

    # Anywhere: CAN, SUB and ESC, in every state but ground (whose rows are its own).
    for st in range(1, len(_NAMES)):
        t[st][_CAN] = t[st][_SUB] = (_execute, _GROUND)
        t[st][_ESC] = (_esc_enter, _ESCAPE)
    t[_DCS_PASSTHROUGH][_CAN] = t[_DCS_PASSTHROUGH][_SUB] = (_cancel_dcs, _GROUND)
    t[_OSC_STRING][_ESC] = (_esc_osc, _ESCAPE_ST)
    t[_DCS_PASSTHROUGH][_ESC] = (_esc_dcs, _ESCAPE_ST)
    t[_DCS_IGNORE][_ESC] = (_esc_enter, _ESCAPE_ST)
    t[_SOS_PM_APC_STRING][_ESC] = (_esc_enter, _ESCAPE_ST)
    t[_GROUND][_CAN] = t[_GROUND][_SUB] = (_ground_execute, _GROUND)
    t[_GROUND][_ESC] = (_ground_esc, _ESCAPE)
    return [tuple(row) for row in t]


def _input_table(output: list) -> list:
    t = [list(row) for row in output]
    for st in (_CSI_ENTRY, _CSI_PARAM, _CSI_INTERMEDIATE):
        for b in range(0x40, 0x7F):
            t[st][b] = (_csi_dispatch_input, _GROUND)

    # escape: these rows come before Anywhere; every other byte is Alt with it.
    esc = [(_alt, _GROUND)] * 256
    for b in range(0x80, 0x100):
        esc[b] = (_alt_lead, _ESCAPE_UTF8)
    esc[_ESC] = (_lone_esc, _ESCAPE)
    esc[ord("[")] = (_seq_enter, _CSI_ENTRY)
    esc[ord("]")] = (_osc_enter, _OSC_STRING)
    esc[ord("P")] = (_seq_enter, _DCS_ENTRY)
    esc[ord("_")] = (None, _SOS_PM_APC_STRING)
    esc[ord("O")] = (_seq_enter, _SS3)
    t[_ESCAPE] = esc
    t[_ESCAPE_ST] = list(esc)
    t[_ESCAPE_ST][_ESC] = (_esc_enter, _ESCAPE)     # nothing for the ESC that ended a string
    t[_ESCAPE_ST][ord("\\")] = (None, _GROUND)
    t[_ESCAPE_UTF8] = [(_alt_more, _ESCAPE_UTF8)] * 256

    ss3 = [(_ss3_end, _GROUND)] * 256
    for b in range(0x30, 0x3C):
        ss3[b] = (_ss3_param, _SS3)
    for b in range(0x40, 0x7F):
        ss3[b] = (_ss3_dispatch, _GROUND)
    t[_SS3] = ss3
    t[_LEGACY_MOUSE] = [(_mouse_byte, _LEGACY_MOUSE)] * 256
    t[_PASTE] = [(None, _PASTE)] * 256              # never read: `_paste_run` takes every byte
    return [tuple(row) for row in t]


_OUTPUT_TABLE = _output_table()
_INPUT_TABLE = _input_table(_OUTPUT_TABLE)

_OUTPUT_RUNS = [None] * len(_NAMES)
_OUTPUT_RUNS[_GROUND] = _ground_run
_OUTPUT_RUNS[_OSC_STRING] = _osc_run
_OUTPUT_RUNS[_DCS_PASSTHROUGH] = _dcs_run
_OUTPUT_RUNS[_DCS_IGNORE] = _OUTPUT_RUNS[_SOS_PM_APC_STRING] = _skip_run(_STRING_SKIP)
_OUTPUT_RUNS[_CSI_IGNORE] = _skip_run(_CSI_SKIP)
_OUTPUT_RUNS = tuple(_OUTPUT_RUNS)
_INPUT_RUNS = _OUTPUT_RUNS[:_PASTE] + (_paste_run,) + _OUTPUT_RUNS[_PASTE + 1:]
