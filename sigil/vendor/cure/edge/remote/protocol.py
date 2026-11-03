"""[Protocol]: hello(size, caps), input, resize, cell diffs, bye; versioned. Cell diffs
cross, never terminal bytes. (A slow client gets the latest frame, not a queue: that rule
is [Server]'s, in its `show`.)

Kind: service (frozen data classes, constants and pure functions; no I/O). Everything a
Remote server and an attaching client say to each other is a message defined here,
encoded and decoded here: [Transport] moves the bytes, [Server] and [Attach] act on the
messages. Being pure, the whole format is testable from bytes alone (no socket, no
terminal).

Framing (every message, both directions, every version):

    length: 4 bytes, unsigned, big-endian   = len(body), 1 <= length <= MAX_FRAME
    body:   kind (1 byte) + payload (length - 1 bytes)

So a message is exactly `struct.pack(">I", len(body)) + body`. A reader bounds the
length below `MAX_FRAME` by its `Decoder`'s `limit` (see `Decoder`): [Transport] reads at
`MAX_HELLO` until the handshake is done, then a client at `frame_limit` of its own size
and a server at `MAX_INPUT`. The payload of an
`INPUT` message is the raw input bytes; every other payload is one JSON object, written
as `json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")` with
its keys in the order shown below (so `encode` is byte for byte fixed), and read with
`json.loads` of the payload decoded as strict UTF-8 (keys not listed are ignored, and
parsed with the rest: the limit bounds what an ignored key costs; a
listed key that is absent or of the wrong type is malformed; a JSON `true` / `false` is
never an int and a JSON float never an int).

Kinds (the byte, the message, who sends it, the payload):

- `HELLO = 0x01`, {Hello}, client: `{"versions":[1],"size":[w,h],"caps":{"depth":D,
  "keys":K,"mouse":M,"graphemes":G,"sync":S}}`: the versions the client speaks, its
  terminal's size and the {Caps} its own [Term] probed.
- `INPUT = 0x02`, {Input}, client: the bytes the person typed into the client's
  terminal, raw (possibly empty). The server decodes them with Input's decoder at the
  client's caps; Remote does not decode keys.
- `RESIZE = 0x03`, {Resize}, client: `{"size":[w,h]}`.
- `BYE = 0x04`, {Bye}, either side: `{"reason":R}`: this side is leaving.
- `WELCOME = 0x81`, {Welcome}, server: `{"version":V,"session":N,"client":C}`: the
  version chosen, the session joined, the client's id.
- `REFUSE = 0x82`, {Refuse}, server: `{"reason":R,"versions":[...]}`: no attach (the
  server's versions are always listed, so a client learns what it would need). The
  server closes the connection after it.
- `FRAME = 0x83`, {Frame}, server: `{"size":[w,h],"full":F,"cursor":null|[x,y],
  "styles":[entry,...],"changes":[[x,y,[[glyph,sid],...]],...]}`: one Buffer {Changes}
  (the runs `diff(front, grid)` gives) with the frame's size and text cursor.

`HELLO`, `WELCOME` and `REFUSE` are frozen across versions (their kinds and payloads
never change), so any two versions can negotiate. `CLIENT_KINDS` are the kinds a client
sends (`HELLO`, `INPUT`, `RESIZE`, `BYE`); `SERVER_KINDS` the kinds a server sends
(`WELCOME`, `REFUSE`, `FRAME`, `BYE`).

Values inside payloads:

- size `[w, h]`: two ints, each `1 <= v <= MAX_SIDE`.
- versions: a JSON list of 1..16 ints, each `>= 1` (order free, repeats allowed).
- caps: an object with the five keys above, each of the type Core's `Caps` takes
  (`depth` an int in `DEPTHS`, `keys` a str in `KEYS`, the others bools); decoded as
  `Caps(...)`; anything `Caps` refuses is malformed.
- a session name N: a str matching `NAME` (see `valid_name`).
- a reason R: a str matching `WORD`: `[a-z][a-z0-9-]{0,31}` (so no reason can hold a
  control character or an escape).
- a client id C, a version V: ints `>= 1`.
- a style entry: the JSON list `[fg, bg, attrs, underline, underline_colour, link]`, a
  lossless Style {Style}:
  - `fg`, `bg`, `underline_colour`: `null` (field `None`) or a colour `[form, value,
    role]` with `form` one of Style's `FORMS`: `["default",null,role]`,
    `["name","red",role]`, `["index",5,role]`, `["rgb",[r,g,b],role]`,
    `["ink",[name,[r,g,b],tty256|null,tty16|null],role]` (an `Ink`); decoded as
    `Colour(form, value, role)` (an rgb value as a tuple; an ink as `Ink(...)`).
  - `attrs`: a str of the letters of the flags set, in this order: `"b"` bold, `"d"`
    dim, `"i"` italic, `"s"` strike, `"r"` reverse (`""` for none; decoding accepts
    exactly the strings this order can produce).
  - `underline`: `null` or one of `UNDERLINES`; `link`: `null` or the link str.
  Decoded as `Style(...)`: whatever `Style`, `Colour` or `Ink` refuses (a link holding a
  control character included) is malformed (`"style"`), and so is a role or an ink name
  holding a control code point (C0, DEL, C1) or a lone surrogate, which `Colour` alone
  would accept (a link holding a lone surrogate is malformed too), or over `MAX_NAME`
  (64) UTF-8 bytes. On encode, such a role or ink name is a `ValueError`.
- the style table: `styles` lists each distinct Style (`==`) the frame's cells carry,
  in order of first appearance (changes in order, cells left to right); a cell's `sid`
  is `0` for a `None` style and `k >= 1` for `styles[k - 1]`. Every sid must be in
  `0..len(styles)`; an unused entry is allowed when decoding. The table's links total
  at most `LINK_BYTES` (64 KiB), each counted as JSON writes it (its UTF-8 bytes, plus
  one for each `"` and `\\`, which escape to two), unused entries included: else
  `Malformed("style")`, and on encode a `ValueError`.
- a change `[x, y, cells]`: ints `x >= 0`, `0 <= y < h`, and a non-empty list of cells
  with `x + len(cells) <= w`; a cell `[glyph, sid]`. A glyph `""` is a tail
  (`Cell("", 0, style)`); any other glyph is `Cell(glyph, text.width(glyph), style)`.
  The run must pass Buffer's `check` (one cluster of its width per cell, every head
  followed by its tail, no orphan tail) and no glyph may hold a control code point (C0
  U+0000..U+001F, DEL U+007F, C1 U+0080..U+009F) or a lone surrogate (only a JSON
  escape can make one): else malformed (`"cell"`). Nor may a glyph hold a bidi
  formatting character (Text's `BIDI`) or U+2028 / U+2029 (`SEPARATORS`), or more than
  Text's `MAX_CLUSTER` (32) code points: else malformed (`"frame"`). The changes' cells
  total at most `w * h` (so the changes number at most `w * h`), counted before any
  cell or style is built: else malformed (`"frame"`).
  On encode, a narrow cell's glyph holding a control code point or a lone surrogate
  is written as `"\\ufffd"` (a tail stays `""`), exactly what Buffer's `Display` would
  draw for it; the run, after that replacement, must pass `check` (else `ValueError`),
  and a head (width 2) whose glyph holds a control or a lone surrogate is a
  `ValueError` (no one-column U+FFFD can stand for it).
- cursor: `null` or `[x, y]` with `0 <= x < w`, `0 <= y < h`.
- `full`: a bool, the Changes' `full`: a whole repaint at this size (the client starts
  from a blank grid); `false` applies to the client's current grid, which must already
  be `size`.

Data (frozen dataclasses, stored as given; `encode` checks them):
- `Hello(versions: tuple[int, ...], size: tuple[int, int], caps)` (`caps` a {Caps}:
  any object with the five attributes when encoding; Core's `Caps` when decoded).
- `Input(data: bytes)`; `Resize(size: tuple[int, int])`; `Bye(reason: str)`.
- `Welcome(version: int, session: str, client: int)`;
  `Refuse(reason: str, versions: tuple[int, ...])`.
- `Frame(size: tuple[int, int], changes: Changes, cursor: tuple[int, int] | None = None)`.
- `Malformed(reason: str, detail: str = "")`, the named error a broken body decodes to
  (a value, returned, never raised). `reason` is one of `MALFORMED`:
  `"size"` (a length prefix above the decoder's `limit`, `MAX_FRAME` at most), `"empty"`
  (a length prefix of 0),
  `"kind"` (an unknown kind, or one the other side does not send), `"payload"` (not
  strict UTF-8, not JSON, or not a JSON object), `"field"` (a listed key absent, of the
  wrong type or out of range), `"cell"` (a run that is not well formed or a glyph with
  a control), `"style"` (a style entry Style refuses), `"order"` (a well-formed message
  at the wrong time: [Transport], [Server] and [Attach] use it; `apply` too), `"frame"`
  (a FRAME with more cells than its size holds, or a glyph with a bidi control, a
  separator or over `MAX_CLUSTER` code points; appended last). `detail`
  is a short human-readable note (not part of equality tests' contract beyond being a
  `str`).
`Message` is the union `Hello | Input | Resize | Bye | Welcome | Refuse | Frame`.

Operations:
- `encode(message) -> bytes`: the framed message (length prefix + kind + payload).
- `frame(changes, size, *, cursor=None) -> bytes` ([Server] -> [Protocol] :
  frame({Changes}) => {Bytes}): `encode(Frame(size, changes, cursor))`, the FRAME
  message a server sends for one diff. [Server] queues the `Frame` itself on the
  client's link ([Transport]'s `Link.queue`, which calls `encode`), so these are the
  bytes that go on the wire, and the framing stays here, in `encode`, alone.
- `decode(body, side) -> Message | Malformed`: one body (kind byte + payload, no length
  prefix). `side` is the end that RECEIVES it: `"server"` accepts `CLIENT_KINDS`,
  `"client"` accepts `SERVER_KINDS`; any other kind is `Malformed("kind")`. An empty
  body is `Malformed("empty")`.
- `Decoder(side, *, limit=MAX_FRAME)`: the incremental reader of a byte stream: `feed(data) ->
  tuple[Message | Malformed, ...]` appends `data` to its buffer and returns every
  complete message in arrival order. A length prefix above `limit` is
  `Malformed("size")` as soon as its 4 bytes are in (the body is never awaited), a
  prefix of 0 is `Malformed("empty")`; any `Malformed` is the last item returned, and
  the decoder is then broken (sticky): `broken` holds that `Malformed` and every later
  `feed` returns `()` and buffers nothing. `limit`, readable and settable: an int,
  `1 <= limit <= MAX_FRAME` (else `TypeError` / `ValueError`, and it is unchanged); a
  set takes effect at the next prefix read, and a body already being read keeps the
  bound its prefix passed. Read-only attributes: `side`, `pending` (the
  count of buffered bytes of an incomplete message), `broken` (`None` or the
  `Malformed`). A message split across any number of feeds, at any byte, decodes the
  same as when fed whole.
- `apply(grid, frame, *, own=False) -> Grid | Malformed` (the client's side of a FRAME):
  when `frame.changes.full`, a new `Grid(w, h)` (blank) with each change written in order
  (Buffer's `write`); otherwise `grid` must be a Grid of exactly `frame.size` (else
  `Malformed("order")`: a partial frame with nothing, or the wrong size, under it),
  and the result is a copy of it with each change written. With `own=False` (pure)
  `grid` itself is never changed. With `own=True` (the caller owns `grid`) a partial
  frame is written into `grid` itself, which is returned, at a cost per change rather
  than per cell of the grid; a full frame (a size change is one) still builds a new
  Grid, and a `Malformed` leaves `grid` as it was. The result is equal either way.
- `frame_limit(w, h) -> int`: the largest FRAME body a client of `w` x `h` cells takes:
  `min(MAX_FRAME, 4096 + LINK_BYTES + w * h * (CELL_BYTES + STYLE_BYTES))`, about
  2.3 MB at 80x24 and 14 MB at 200x60; `MAX_FRAME` from about 168x168 up. Law (fits):
  below `MAX_FRAME`, a full frame of `w` x `h` maximal legal cells (each its own worst
  style, the links at `LINK_BYTES`) fits it, by the derivations of `CELL_BYTES` and
  `STYLE_BYTES`. A full frame of maximal legal cells larger than that exceeds
  `MAX_FRAME`, as it always has (not new). `TypeError` / `ValueError` as for a size.
- `negotiate(theirs, ours=VERSIONS) -> int | None`: the highest version in both, or
  `None` when they share none.
- `valid_name(name) -> bool`: whether `name` is a session (or app) name: a `str`
  matching `NAME`, `[A-Za-z0-9][A-Za-z0-9._-]{0,31}` (so no `/`, no leading `.` or
  `-`, 1..32 chars).

Constants: `VERSION = 1` (this format); `VERSIONS = (1,)` (what this code speaks);
`MAX_FRAME = 1 << 25` (32 MiB, the largest body); `MAX_HELLO = 1 << 16` (the handshake
bound: HELLO, WELCOME and REFUSE fit far under it); `MAX_INPUT = 65792` (a server's
bound on a client's bodies once its HELLO is accepted: see below); `MAX_SIDE = 1024` (the largest
width or height a size may give); `HEADER = 4`; `NAME`, `WORD` (the regex strings
above); the kinds; `CLIENT_KINDS`, `SERVER_KINDS`; `MALFORMED` (the reasons);
`MAX_NAME = 64` (a role's or an ink name's most UTF-8 bytes); `LINK_BYTES = 1 << 16`
(a frame's links in total); and, derived in the code from the worst legal case:
- `CELL_BYTES = 160`: a one-cell change at the far corner, `[1023,1023,[[glyph,sid]]],`,
  its glyph `MAX_CLUSTER` code points of 4 bytes (the encoder writes UTF-8, controls
  are refused, a quote or backslash escapes to 2), its sid of 7 digits: 155 B, rounded
  up to 32 B.
- `STYLE_BYTES = 1024`: three colours in the ink form, each name and role `MAX_NAME`
  bytes that JSON escapes to twice that (all quotes), the largest rgb, tty256 and
  tty16, every attribute, the longest underline and a null link: 945 B, rounded up to
  256 B.
- `MAX_INPUT = 65792`: an INPUT's payload is the raw bytes (no escaping), and [Attach]
  sends at most [Transport]'s `CHUNK` (65536) of them per INPUT, so its largest body
  is the kind byte plus `CHUNK` bytes: 65537 B, rounded up to 256 B (a margin of 255).
  A client's other kinds are tiny: the largest RESIZE and BYE bodies are under 64 B.
An assertion ties the first two to `MAX_CLUSTER == 32`, and one in transport.py ties
`MAX_INPUT` to `CHUNK`.

Laws (a test can loop over them):
- round trip: for every message `m` that `encode` accepts and whose glyphs hold no
  control code point, `Decoder(side).feed(encode(m)) == (m,)` with `side` the receiving
  end of `m`'s kind (a `Hello`'s caps compared field by field; decoded as Core's Caps).
- framing: `encode(m)[:4] == struct.pack(">I", len(encode(m)) - 4)` and
  `encode(m)[4]` is `m`'s kind.
- convergence: for grids `g1, g2, ...` of any sizes, starting from `front = None` and
  `c = None`: `c = apply(c, decode(frame(diff(front, g), g.size)[4:], "client"))`,
  `front = g`, gives `c == g` after every step.

Invariant: cells_only — cell diffs cross, never terminal bytes: a server cannot write
  escapes into a client's terminal. (1) Server-to-client kinds are exactly WELCOME,
  REFUSE, FRAME and BYE; none carries bytes meant for a terminal: their payloads are
  JSON of ints, bools, nulls, `WORD` / `NAME` strings and the glyphs, colours and links
  of cells. (2) Every FRAME the client side decodes (`decode(..., "client")`,
  `Decoder("client").feed`) holds only well-formed runs (Buffer's `check`) whose glyphs
  hold no control code point, and Styles that `Style` accepted (no control in a link);
  any body that would carry one is `Malformed("cell")` / `Malformed("style")`, and a
  glyph with a bidi control, a separator or over `MAX_CLUSTER` code points, or more
  cells than the frame's size, is `Malformed("frame")` (so a full frame of the client's
  own size fits its `frame_limit`); and a
  REFUSE / BYE / WELCOME whose reason or session is not a `WORD` / `NAME` is
  `Malformed("field")`. (3) [Attach] writes to its terminal only its own [Term]'s bytes
  (modes, probe, undo) and `Display.show` of grids built by `apply`: no byte of a
  received payload is ever written to the terminal as it came. Proof shape: for each
  server kind, payloads with every C0 / DEL / C1 control and `ESC [`, `ESC ]` sequences
  injected into each string field (glyph, link, role, reason, session) decode to a
  `Malformed` or to values free of controls; over a socketpair, a hostile peer that
  sends FRAMEs, BYEs and unknown kinds carrying `"\\x1b]52;c;U0VDUkVU\\x07"` to an
  [Attach] on a headless Term: the term's writer never receives `b"]52;"`.

Inputs: messages as above; `body`, `data`: `bytes` (`bytearray` / `memoryview`
  accepted); `side`: `"server"` or `"client"`; `changes` a Buffer {Changes}; `size` a
  2-tuple of ints; `cursor` `None` or a 2-tuple of ints; `grid` `None` or a {Grid}.
Outputs: `encode`, `frame`: {Bytes} (one framed message, a {Message}); `decode`,
  `feed`: messages or a {Malformed}; `apply`: a {Grid} or a {Malformed}.
Errors: `encode` / `frame` (the sender's own values, checked before any byte is made):
  `TypeError` when `message` is not one of the message classes or a field has the
  wrong type (a `bool` refused wherever an int is meant; `Input.data` not `bytes` /
  `bytearray`; `changes` not a `Changes`; a cell's style neither `None` nor a `Style`);
  `ValueError` when a value is out of range as stated above (a size side outside
  `1..MAX_SIDE`, a version < 1, a name not `NAME`, a reason not `WORD`, a cursor or a
  change outside the size, an empty change, a run Buffer's `check` refuses, a role or
  ink name over `MAX_NAME` bytes, links over `LINK_BYTES`), or the body would exceed
  `MAX_FRAME`. `decode`, `Decoder(...)`, `feed`: `TypeError` when
  `body` / `data` is not bytes-like; `ValueError` when `side` is neither `"server"` nor
  `"client"`; a bad body is never raised, it is the returned `Malformed`. `apply`:
  `TypeError` when `grid` is neither `None` nor a `Grid` or `frame` is not a `Frame`.
  `apply` given a hand-built `Frame` whose changes do not fit its size (decoded frames
  always do): `ValueError`. `Decoder(..., limit=...)` and the `limit` setter: `TypeError`
  when it is not an int (a `bool` refused), `ValueError` outside `1..MAX_FRAME`. `negotiate`: `TypeError` when an entry is not an int. `Malformed(...)`: `TypeError`
  when a field is not a `str`, `ValueError` when `reason` is not in `MALFORMED`.
  `valid_name`: never raises (a non-`str` is `False`).
Effects: none (a `Decoder` changes only its own buffer and limit; `apply(..., own=True)`
  only the `grid` it is given).

Usage:
    from cure.core.buffer import Grid, put, diff
    from cure.core.caps import Caps
    from cure.edge.remote.protocol import (Decoder, Hello, Input, Bye, Welcome, apply,
                                           decode, encode, frame, frame_limit, negotiate)
    encode(Hello((1,), (80, 24), Caps(depth=256, mouse=True, sync=True)))
    # b'\\x00\\x00\\x00p\\x01{"versions":[1],"size":[80,24],"caps":{"depth":256,'
    # b'"keys":"legacy","mouse":true,"graphemes":false,"sync":true}}'
    encode(Input(b"q"))                  # b"\\x00\\x00\\x00\\x02\\x02q"
    encode(Bye("detach"))                # b'\\x00\\x00\\x00\\x14\\x04{"reason":"detach"}'
    encode(Welcome(1, "main", 1))        # b'\\x00\\x00\\x00*\\x81{"version":1,"session":"main","client":1}'
    g = put(Grid(2, 1), 0, 0, "hi")
    frame(diff(None, g), (2, 1))
    # b'\\x00\\x00\\x00Y\\x83{"size":[2,1],"full":true,"cursor":null,"styles":[],'
    # b'"changes":[[0,0,[["h",0],["i",0]]]]}'
    d = Decoder("client")
    m = frame(diff(None, g), (2, 1))
    d.feed(m[:3]), d.pending             # ((), 3): an incomplete prefix waits
    (f,) = d.feed(m[3:])                 # one Frame
    apply(None, f) == g                  # True
    decode(b"\\x01{}", "client")          # Malformed("kind", ...): a client's kind at the client
    Decoder("server").feed(b"\\xff\\xff\\xff\\xff")   # (Malformed("size", ...),); broken from now on
    Decoder("client", limit=frame_limit(80, 24))    # bounded by the client's own size
    negotiate((1, 2), (1,))              # 1
    negotiate((2,), (1,))                # None: no common version (the server REFUSEs)
"""

import json
import re
import struct
from dataclasses import dataclass

from cure.core.buffer import Change, Changes, Grid, check, write
from cure.core.caps import DEPTHS, KEYS, Caps
from cure.core.style import NAMES, UNDERLINES, Colour, Ink, Style
from cure.core.text import Cell
from cure.core.text import width as _width
from cure.core.text.width import BIDI, MAX_CLUSTER, SEPARATORS

VERSION = 1
VERSIONS = (1,)
MAX_FRAME = 1 << 25
MAX_SIDE = 1024
HEADER = 4
NAME = r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}"
WORD = r"[a-z][a-z0-9-]{0,31}"

HELLO = 0x01
INPUT = 0x02
RESIZE = 0x03
BYE = 0x04
WELCOME = 0x81
REFUSE = 0x82
FRAME = 0x83
CLIENT_KINDS = (HELLO, INPUT, RESIZE, BYE)
SERVER_KINDS = (WELCOME, REFUSE, FRAME, BYE)
SIDES = ("server", "client")

MALFORMED = ("size", "empty", "kind", "payload", "field", "cell", "style", "order", "frame")

_NAME = re.compile(NAME)
_WORD = re.compile(WORD)
_CAPS = ("depth", "keys", "mouse", "graphemes", "sync")
_ATTRS = (("b", "bold"), ("d", "dim"), ("i", "italic"), ("s", "strike"), ("r", "reverse"))
_REPLACEMENT = "�"
_MAX_VERSIONS = 16
_FORBIDDEN = BIDI | SEPARATORS

MAX_HELLO = 1 << 16
_CHUNK = 1 << 16            # Transport's CHUNK, the most raw bytes Attach puts in one INPUT
MAX_NAME = 64
LINK_BYTES = 1 << 16


def _json(obj: object) -> bytes:
    """The payload form: compact JSON, non-ASCII written as UTF-8 (so `encode` is byte for byte fixed)."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _round_up(n: int, unit: int) -> int:
    return -(-n // unit) * unit


def _worst_cell() -> int:
    """The wire bytes of the worst legal cell: a one-cell change at the far corner, its
    glyph MAX_CLUSTER code points of 4 UTF-8 bytes (no legal code point takes more, an
    escaped quote or backslash takes 2, controls are refused), its sid the largest a
    frame of MAX_SIDE x MAX_SIDE cells can need, and the comma after it."""
    glyph = "\U00010000" * MAX_CLUSTER
    return len(_json([MAX_SIDE - 1, MAX_SIDE - 1, [[glyph, MAX_SIDE * MAX_SIDE]]])) + 1


def _worst_style() -> int:
    """The wire bytes of the worst legal style entry: three ink colours whose name and role
    are MAX_NAME bytes that JSON escapes to two each (a quote), the largest rgb, tty256
    and tty16, every attribute, the longest underline, a null link (links are counted
    apart, in LINK_BYTES), and the comma after it."""
    name = '"' * MAX_NAME
    colour = ["ink", [name, [255, 255, 255], 255, max(NAMES, key=len)], name]
    return len(_json([colour, colour, "".join(a for a, _ in _ATTRS),
                      max(UNDERLINES, key=len), colour, None])) + 1


CELL_BYTES = _round_up(_worst_cell(), 32)
STYLE_BYTES = _round_up(_worst_style(), 256)
assert MAX_CLUSTER == 32 and (CELL_BYTES, STYLE_BYTES) == (160, 1024), (
    "Text's MAX_CLUSTER or a style's worst case moved: restate CELL_BYTES / STYLE_BYTES (round 18)")

# An INPUT's payload is its raw bytes: the worst body is the kind byte and a full CHUNK.
MAX_INPUT = _round_up(1 + _CHUNK, 256)
assert MAX_INPUT == 65792, "Transport's CHUNK moved: restate MAX_INPUT (J2)"


def frame_limit(w: int, h: int) -> int:
    """The largest FRAME body a client of `w` x `h` cells takes: every cell its own worst
    cell and style, the links at LINK_BYTES, 4096 for the rest; at most MAX_FRAME."""
    _enc_size((w, h))
    return min(MAX_FRAME, 4096 + LINK_BYTES + w * h * (CELL_BYTES + STYLE_BYTES))


@dataclass(frozen=True)
class Hello:
    """{Hello}: the client's versions, terminal size and caps (kind HELLO)."""

    versions: "tuple[int, ...]"
    size: "tuple[int, int]"
    caps: object


@dataclass(frozen=True)
class Input:
    """The raw bytes typed into the client's terminal (kind INPUT)."""

    data: bytes


@dataclass(frozen=True)
class Resize:
    """The client's terminal has a new size (kind RESIZE)."""

    size: "tuple[int, int]"


@dataclass(frozen=True)
class Bye:
    """This side is leaving, for `reason` (a WORD) (kind BYE, either side)."""

    reason: str


@dataclass(frozen=True)
class Welcome:
    """The server's yes: the version chosen, the session joined, the client's id (kind WELCOME)."""

    version: int
    session: str
    client: int


@dataclass(frozen=True)
class Refuse:
    """The server's no, with the versions it speaks (kind REFUSE)."""

    reason: str
    versions: "tuple[int, ...]"


@dataclass(frozen=True)
class Frame:
    """One cell diff at `size`, with the text cursor (kind FRAME)."""

    size: "tuple[int, int]"
    changes: Changes
    cursor: "tuple[int, int] | None" = None


@dataclass(frozen=True)
class Malformed:
    """{Malformed}: a body that breaks the format, by `reason` (one of MALFORMED); returned, never raised."""

    reason: str
    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str):
            raise TypeError(f"reason must be a str, got {type(self.reason).__name__}")
        if not isinstance(self.detail, str):
            raise TypeError(f"detail must be a str, got {type(self.detail).__name__}")
        if self.reason not in MALFORMED:
            raise ValueError(f"reason must be one of {MALFORMED}, got {self.reason!r}")


Message = Hello | Input | Resize | Bye | Welcome | Refuse | Frame


# -- shared checks

def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_control(ch: str) -> bool:
    code = ord(ch)
    return code < 0x20 or 0x7F <= code <= 0x9F


def _has_control(text: str) -> bool:
    return any(_is_control(ch) for ch in text)


def _surrogate(text: str) -> bool:
    """Whether `text` holds a lone surrogate (only a JSON escape makes one): not text a terminal can take."""
    return any(0xD800 <= ord(ch) <= 0xDFFF for ch in text)


def _too_long(name: str) -> bool:
    """Whether a role or an ink name is over MAX_NAME UTF-8 bytes."""
    return len(name.encode("utf-8", "surrogatepass")) > MAX_NAME


def _link_bytes(link: "str | None") -> int:
    """What a link costs against LINK_BYTES: its bytes as JSON writes them (a quote or a
    backslash escaped to 2), so the links' share of a frame is bounded by construction."""
    if link is None:
        return 0
    return len(link.encode("utf-8", "surrogatepass")) + link.count('"') + link.count("\\")


def _matches(pattern: "re.Pattern", value: object) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _bytes_like(value: object, name: str) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise TypeError(f"{name} must be bytes-like, got {type(value).__name__}")
    return bytes(value)


def _check_side(side: object) -> None:
    if side not in SIDES:
        raise ValueError(f"side must be 'server' or 'client', got {side!r}")


# -- encode: the sender's own values, checked before any byte is made

def _enc_int(value: object, name: str, low: int = 1) -> int:
    if not _is_int(value):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if value < low:
        raise ValueError(f"{name} must be >= {low}, got {value}")
    return value


def _enc_pair(value: object, name: str) -> "tuple[int, int]":
    if not isinstance(value, (tuple, list)):
        raise TypeError(f"{name} must be a 2-tuple of ints, got {type(value).__name__}")
    if len(value) != 2:
        raise ValueError(f"{name} must have two values, got {len(value)}")
    for v in value:
        if not _is_int(v):
            raise TypeError(f"{name} must hold ints, got {type(v).__name__}")
    return value[0], value[1]


def _enc_size(value: object) -> "list[int]":
    w, h = _enc_pair(value, "size")
    for v in (w, h):
        if not 1 <= v <= MAX_SIDE:
            raise ValueError(f"a size side must be 1..{MAX_SIDE}, got {v}")
    return [w, h]


def _enc_versions(value: object) -> "list[int]":
    if not isinstance(value, (tuple, list)):
        raise TypeError(f"versions must be a tuple of ints, got {type(value).__name__}")
    out = [_enc_int(v, "a version") for v in value]
    if not 1 <= len(out) <= _MAX_VERSIONS:
        raise ValueError(f"versions must list 1..{_MAX_VERSIONS} ints, got {len(out)}")
    return out


def _enc_text(value: object, pattern: "re.Pattern", name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a str, got {type(value).__name__}")
    if pattern.fullmatch(value) is None:
        raise ValueError(f"{name} {value!r} does not match {pattern.pattern}")
    return value


def _enc_caps(caps: object) -> dict:
    out = {}
    for key in _CAPS:
        try:
            out[key] = getattr(caps, key)
        except AttributeError:
            raise TypeError(f"caps has no {key!r}") from None
    depth = out["depth"]
    if not _is_int(depth):
        raise TypeError(f"caps.depth must be an int, got {type(depth).__name__}")
    if not isinstance(out["keys"], str):
        raise TypeError(f"caps.keys must be a str, got {type(out['keys']).__name__}")
    for key in ("mouse", "graphemes", "sync"):
        if not isinstance(out[key], bool):
            raise TypeError(f"caps.{key} must be a bool, got {type(out[key]).__name__}")
    if depth not in DEPTHS:
        raise ValueError(f"caps.depth must be one of {DEPTHS}, got {depth}")
    if out["keys"] not in KEYS:
        raise ValueError(f"caps.keys must be one of {KEYS}, got {out['keys']!r}")
    return out


def _enc_label(text: str, what: str) -> str:
    if _has_control(text):
        raise ValueError(f"{what} holds a control code point: {text!r}")
    if _too_long(text):
        raise ValueError(f"{what} is over MAX_NAME ({MAX_NAME}) UTF-8 bytes: {text[:16]!r}...")
    return text


def _enc_colour(colour: "Colour | None") -> object:
    if colour is None:
        return None
    if not isinstance(colour, Colour):
        raise TypeError(f"a colour must be None or a Colour, got {type(colour).__name__}")
    role = _enc_label(colour.role, "a colour's role")
    if colour.form == "rgb":
        value = list(colour.value)
    elif colour.form == "ink":
        ink = colour.value
        value = [_enc_label(ink.name, "an ink's name"), list(ink.rgb), ink.tty256, ink.tty16]
    else:
        value = colour.value
    return [colour.form, value, role]


def _enc_style(style: Style) -> list:
    attrs = "".join(letter for letter, flag in _ATTRS if getattr(style, flag))
    return [_enc_colour(style.fg), _enc_colour(style.bg), attrs, style.underline,
            _enc_colour(style.underline_colour), style.link]


def _enc_cells(cells: object, table: dict) -> "list[list]":
    if not isinstance(cells, tuple):
        cells = tuple(cells)
    sent = []
    for i, cell in enumerate(cells):
        if not isinstance(cell, Cell):
            raise TypeError(f"column {i}: expected a Cell, got {type(cell).__name__}")
        if cell.style is not None and not isinstance(cell.style, Style):
            raise TypeError(f"column {i}: a style must be None or a Style, got {type(cell.style).__name__}")
        glyph = cell.glyph
        if isinstance(glyph, str) and (_has_control(glyph) or _surrogate(glyph)):
            if cell.width == 2:
                raise ValueError(f"column {i}: a wide glyph holds a control: {glyph!r}")
            if cell.width == 1:
                glyph = _REPLACEMENT
        sent.append(cell if glyph is cell.glyph else Cell(glyph, cell.width, cell.style))
    check(sent)
    out = []
    for cell in sent:
        if cell.style is None:
            sid = 0
        else:
            sid = table.get(cell.style)
            if sid is None:
                sid = table[cell.style] = len(table) + 1
        out.append([cell.glyph, sid])
    return out


def _enc_frame(m: Frame) -> dict:
    size = _enc_size(m.size)
    w, h = size
    if not isinstance(m.changes, Changes):
        raise TypeError(f"changes must be a Changes, got {type(m.changes).__name__}")
    cursor = None
    if m.cursor is not None:
        x, y = _enc_pair(m.cursor, "cursor")
        if not (0 <= x < w and 0 <= y < h):
            raise ValueError(f"cursor {m.cursor} is outside {w} x {h}")
        cursor = [x, y]
    table: dict = {}
    changes = []
    for ch in m.changes.items:
        if not isinstance(ch, Change):
            raise TypeError(f"a change must be a Change, got {type(ch).__name__}")
        x, y = _enc_pair((ch.x, ch.y), "a change's position")
        cells = _enc_cells(ch.cells, table)
        if not cells:
            raise ValueError("a change holds no cells")
        if x < 0 or not 0 <= y < h or x + len(cells) > w:
            raise ValueError(f"a change at ({x}, {y}) of {len(cells)} cells is outside {w} x {h}")
        changes.append([x, y, cells])
    if not isinstance(m.changes.full, bool):
        raise TypeError("changes.full must be a bool")
    links = sum(_link_bytes(s.link) for s in table if isinstance(s.link, str))
    if links > LINK_BYTES:
        raise ValueError(f"the frame's links total {links} bytes, more than LINK_BYTES ({LINK_BYTES})")
    styles = [_enc_style(s) for s in table]
    return {"size": size, "full": m.changes.full, "cursor": cursor, "styles": styles,
            "changes": changes}


def _payload(m: object) -> "tuple[int, bytes]":
    if isinstance(m, Input):
        if not isinstance(m.data, (bytes, bytearray)):
            raise TypeError(f"Input.data must be bytes, got {type(m.data).__name__}")
        return INPUT, bytes(m.data)
    if isinstance(m, Hello):
        kind, obj = HELLO, {"versions": _enc_versions(m.versions), "size": _enc_size(m.size),
                            "caps": _enc_caps(m.caps)}
    elif isinstance(m, Resize):
        kind, obj = RESIZE, {"size": _enc_size(m.size)}
    elif isinstance(m, Bye):
        kind, obj = BYE, {"reason": _enc_text(m.reason, _WORD, "reason")}
    elif isinstance(m, Welcome):
        kind, obj = WELCOME, {"version": _enc_int(m.version, "version"),
                              "session": _enc_text(m.session, _NAME, "session"),
                              "client": _enc_int(m.client, "client")}
    elif isinstance(m, Refuse):
        kind, obj = REFUSE, {"reason": _enc_text(m.reason, _WORD, "reason"),
                             "versions": _enc_versions(m.versions)}
    elif isinstance(m, Frame):
        kind, obj = FRAME, _enc_frame(m)
    else:
        raise TypeError(f"not a message: {type(m).__name__}")
    return kind, _json(obj)


def encode(message: object) -> bytes:
    """The framed message: 4-byte big-endian length, kind byte, payload (see the module)."""
    kind, payload = _payload(message)
    length = 1 + len(payload)
    if length > MAX_FRAME:
        raise ValueError(f"the body is {length} bytes, more than MAX_FRAME ({MAX_FRAME})")
    return struct.pack(">I", length) + bytes([kind]) + payload


def frame(changes: Changes, size: "tuple[int, int]", *, cursor: "tuple[int, int] | None" = None) -> bytes:
    """`encode(Frame(size, changes, cursor))`: one cell diff as a FRAME message."""
    return encode(Frame(size, changes, cursor))


# -- decode: a bad body is a returned Malformed, never raised

class _Bad(Exception):
    """A broken body, inside decoding only: becomes the returned Malformed."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason, detail)
        self.reason, self.detail = reason, detail


def _need(obj: dict, key: str) -> object:
    if key not in obj:
        raise _Bad("field", f"{key!r} is absent")
    return obj[key]


def _dec_int(value: object, name: str, low: int = 1) -> int:
    if not _is_int(value) or value < low:
        raise _Bad("field", f"{name} is not an int >= {low}")
    return value


def _dec_size(value: object, name: str = "size") -> "tuple[int, int]":
    if not isinstance(value, list) or len(value) != 2:
        raise _Bad("field", f"{name} is not [w, h]")
    for v in value:
        if not _is_int(v) or not 1 <= v <= MAX_SIDE:
            raise _Bad("field", f"{name} holds a side outside 1..{MAX_SIDE}")
    return value[0], value[1]


def _dec_versions(value: object) -> "tuple[int, ...]":
    if not isinstance(value, list) or not 1 <= len(value) <= _MAX_VERSIONS:
        raise _Bad("field", "versions is not a list of 1..16 ints")
    return tuple(_dec_int(v, "a version") for v in value)


def _dec_text(value: object, pattern: "re.Pattern", name: str) -> str:
    if not _matches(pattern, value):
        raise _Bad("field", f"{name} does not match {pattern.pattern}")
    return value


def _dec_caps(value: object) -> object:
    if not isinstance(value, dict):
        raise _Bad("field", "caps is not an object")
    fields = {key: _need(value, key) for key in _CAPS}
    if not _is_int(fields["depth"]) or not isinstance(fields["keys"], str):
        raise _Bad("field", "caps has a field of the wrong type")
    try:
        return Caps(**fields)
    except (TypeError, ValueError) as e:
        raise _Bad("field", f"caps: {e}") from None


def _dec_label(value: object, what: str) -> str:
    if not isinstance(value, str) or _has_control(value) or _surrogate(value):
        raise _Bad("style", f"{what} is not a str free of controls")
    if _too_long(value):
        raise _Bad("style", f"{what} is over MAX_NAME ({MAX_NAME}) UTF-8 bytes")
    return value


def _dec_colour(value: object) -> "Colour | None":
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 3:
        raise _Bad("style", "a colour is not [form, value, role]")
    form, v, role = value
    role = _dec_label(role, "a colour's role")
    if form == "rgb" and isinstance(v, list):
        v = tuple(v)
    elif form == "ink":
        if not isinstance(v, list) or len(v) != 4:
            raise _Bad("style", "an ink is not [name, rgb, tty256, tty16]")
        name, rgb, tty256, tty16 = v
        name = _dec_label(name, "an ink's name")
        if isinstance(rgb, list):
            rgb = tuple(rgb)
        try:
            v = Ink(name, rgb, tty256, tty16)
        except (TypeError, ValueError) as e:
            raise _Bad("style", f"ink: {e}") from None
    try:
        return Colour(form, v, role)
    except (TypeError, ValueError) as e:
        raise _Bad("style", f"colour: {e}") from None


def _dec_attrs(value: object) -> dict:
    if not isinstance(value, str):
        raise _Bad("style", "attrs is not a str")
    flags = {}
    rest = value
    for letter, flag in _ATTRS:
        flags[flag] = rest.startswith(letter)
        if flags[flag]:
            rest = rest[1:]
    if rest:
        raise _Bad("style", f"attrs {value!r} is not in the order 'bdisr'")
    return flags


def _dec_style(entry: object) -> Style:
    if not isinstance(entry, list) or len(entry) != 6:
        raise _Bad("style", "a style entry is not a list of six")
    fg, bg, attrs, underline, underline_colour, link = entry
    flags = _dec_attrs(attrs)
    if isinstance(link, str) and _surrogate(link):
        raise _Bad("style", "a link holds a lone surrogate")
    colours = [_dec_colour(c) for c in (fg, bg, underline_colour)]
    if underline is not None and (not isinstance(underline, str) or underline not in UNDERLINES):
        raise _Bad("style", "underline is not one of UNDERLINES")
    try:
        return Style(fg=colours[0], bg=colours[1], underline=underline,
                     underline_colour=colours[2], link=link, **flags)
    except (TypeError, ValueError) as e:
        raise _Bad("style", f"style: {e}") from None


def _dec_cells(value: object, styles: "list[Style]") -> "tuple[Cell, ...]":
    if not isinstance(value, list) or not value:
        raise _Bad("field", "a change's cells is not a non-empty list")
    cells = []
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            raise _Bad("field", "a cell is not [glyph, sid]")
        glyph, sid = item
        if not isinstance(glyph, str):
            raise _Bad("field", "a glyph is not a str")
        if not _is_int(sid) or not 0 <= sid <= len(styles):
            raise _Bad("field", f"a sid is outside 0..{len(styles)}")
        style = None if sid == 0 else styles[sid - 1]
        if len(glyph) > MAX_CLUSTER:
            raise _Bad("frame", f"a glyph of {len(glyph)} code points, over MAX_CLUSTER ({MAX_CLUSTER})")
        if _has_control(glyph) or _surrogate(glyph):
            raise _Bad("cell", f"a glyph holds a control: {glyph!r}")
        if not _FORBIDDEN.isdisjoint(glyph):
            raise _Bad("frame", f"a glyph holds a bidi control or a separator: {ascii(glyph)}")
        cells.append(Cell("", 0, style) if glyph == "" else Cell(glyph, _width(glyph), style))
    try:
        return check(cells)
    except ValueError as e:
        raise _Bad("cell", str(e)) from None


def _count(raw: list, most: int) -> None:
    """The changes' cells, counted before any is built: at most `most` (w * h) in all, and
    so at most `most` changes (each holds at least one)."""
    if len(raw) > most:
        raise _Bad("frame", f"{len(raw)} changes, more than the frame's {most} cells")
    total = 0
    for item in raw:
        if not isinstance(item, list) or len(item) != 3:
            raise _Bad("field", "a change is not [x, y, cells]")
        if isinstance(item[2], list):
            total += len(item[2])
    if total > most:
        raise _Bad("frame", f"{total} cells, more than the frame's {most}")


def _dec_frame(obj: dict) -> Frame:
    w, h = _dec_size(_need(obj, "size"))
    full = _need(obj, "full")
    if not isinstance(full, bool):
        raise _Bad("field", "full is not a bool")
    cursor = _need(obj, "cursor")
    if cursor is not None:
        if (not isinstance(cursor, list) or len(cursor) != 2 or not all(map(_is_int, cursor))
                or not (0 <= cursor[0] < w and 0 <= cursor[1] < h)):
            raise _Bad("field", "cursor is not null or [x, y] inside the size")
        cursor = (cursor[0], cursor[1])
    entries = _need(obj, "styles")
    if not isinstance(entries, list):
        raise _Bad("field", "styles is not a list")
    raw = _need(obj, "changes")
    if not isinstance(raw, list):
        raise _Bad("field", "changes is not a list")
    _count(raw, w * h)
    styles = [_dec_style(e) for e in entries]
    links = sum(_link_bytes(s.link) for s in styles if isinstance(s.link, str))
    if links > LINK_BYTES:
        raise _Bad("style", f"the links total {links} bytes, over LINK_BYTES ({LINK_BYTES})")
    changes = []
    for item in raw:
        x, y, cells = item
        if not _is_int(x) or not _is_int(y) or x < 0 or not 0 <= y < h:
            raise _Bad("field", "a change's position is outside the size")
        cells = _dec_cells(cells, styles)
        if x + len(cells) > w:
            raise _Bad("field", "a change runs past the width")
        changes.append(Change(x, y, cells))
    return Frame((w, h), Changes(tuple(changes), full), cursor)


def _dec_object(kind: int, obj: dict) -> object:
    if kind == HELLO:
        return Hello(_dec_versions(_need(obj, "versions")), _dec_size(_need(obj, "size")),
                     _dec_caps(_need(obj, "caps")))
    if kind == RESIZE:
        return Resize(_dec_size(_need(obj, "size")))
    if kind == BYE:
        return Bye(_dec_text(_need(obj, "reason"), _WORD, "reason"))
    if kind == WELCOME:
        return Welcome(_dec_int(_need(obj, "version"), "version"),
                       _dec_text(_need(obj, "session"), _NAME, "session"),
                       _dec_int(_need(obj, "client"), "client"))
    if kind == REFUSE:
        return Refuse(_dec_text(_need(obj, "reason"), _WORD, "reason"),
                      _dec_versions(_need(obj, "versions")))
    return _dec_frame(obj)


def _decode(body: bytes, side: str) -> object:
    if not body:
        return Malformed("empty", "an empty body")
    kind = body[0]
    if kind not in (CLIENT_KINDS if side == "server" else SERVER_KINDS):
        return Malformed("kind", f"kind 0x{kind:02x} is not one the {side} receives")
    if kind == INPUT:
        return Input(body[1:])
    try:
        obj = json.loads(body[1:].decode("utf-8"))
    except (ValueError, RecursionError) as e:
        return Malformed("payload", f"not strict UTF-8 JSON: {type(e).__name__}")
    if not isinstance(obj, dict):
        return Malformed("payload", "not a JSON object")
    try:
        return _dec_object(kind, obj)
    except _Bad as bad:
        return Malformed(bad.reason, bad.detail)
    except RecursionError:
        return Malformed("payload", "nested too deeply")


def decode(body: bytes, side: str) -> "object":
    """One body (kind + payload) as the message it is, or a Malformed, for the receiving `side`."""
    data = _bytes_like(body, "body")
    _check_side(side)
    return _decode(data, side)


def _check_limit(limit: object) -> int:
    if not _is_int(limit):
        raise TypeError(f"limit must be an int, got {type(limit).__name__}")
    if not 1 <= limit <= MAX_FRAME:
        raise ValueError(f"limit must be 1..MAX_FRAME ({MAX_FRAME}), got {limit}")
    return limit


class Decoder:
    """An incremental stream reader for one receiving `side`, bodies bounded by `limit`; broken (sticky) after a Malformed."""

    def __init__(self, side: str, *, limit: int = MAX_FRAME) -> None:
        _check_side(side)
        self._side = side
        self._limit = _check_limit(limit)
        self._buf = bytearray()
        self._broken = None
        self._held = False          # the buffered message's prefix has passed its limit
        self._after = None          # Transport's handshake: called with each message, before the next prefix

    @property
    def limit(self) -> int:
        """The largest body taken, 1..MAX_FRAME; a set takes effect at the next prefix."""
        return self._limit

    @limit.setter
    def limit(self, value: int) -> None:
        self._limit = _check_limit(value)

    @property
    def side(self) -> str:
        """`"server"` or `"client"`: the end that receives."""
        return self._side

    @property
    def pending(self) -> int:
        """The bytes buffered of an incomplete message."""
        return len(self._buf)

    @property
    def broken(self) -> "Malformed | None":
        """The Malformed that broke the stream, or None."""
        return self._broken

    def feed(self, data: bytes) -> tuple:
        """Every complete message in `data` (after what was buffered), in order; a Malformed last."""
        data = _bytes_like(data, "data")
        if self._broken is not None:
            return ()
        buf = self._buf
        buf += data
        out = []
        at = 0
        while len(buf) - at >= HEADER:
            (length,) = struct.unpack_from(">I", buf, at)
            if not self._held:      # a body already being read keeps the bound it started under
                if length > self._limit:
                    return self._break(out, Malformed(
                        "size", f"a length prefix of {length}, over the limit {self._limit}"))
                if length == 0:
                    return self._break(out, Malformed("empty", "a length prefix of 0"))
            if len(buf) - at - HEADER < length:
                self._held = True
                break
            self._held = False
            body = bytes(buf[at + HEADER:at + HEADER + length])
            at += HEADER + length
            m = _decode(body, self._side)
            if isinstance(m, Malformed):
                return self._break(out, m)
            out.append(m)
            if self._after is not None:
                self._after(m)
        del buf[:at]
        return tuple(out)

    def _break(self, out: list, m: Malformed) -> tuple:
        self._broken = m
        self._buf = bytearray()
        out.append(m)
        return tuple(out)


def apply(grid: "Grid | None", frame: Frame, *, own: bool = False) -> "Grid | Malformed":
    """`frame`'s changes written over a copy of `grid` (`grid` itself when `own` and the frame is partial), or over a blank grid for a full frame."""
    if grid is not None and not isinstance(grid, Grid):
        raise TypeError(f"grid must be None or a Grid, got {type(grid).__name__}")
    if not isinstance(frame, Frame):
        raise TypeError(f"frame must be a Frame, got {type(frame).__name__}")
    w, h = frame.size
    for ch in frame.changes.items:
        if ch.x < 0 or not 0 <= ch.y < h or ch.x + len(ch.cells) > w:
            raise ValueError(f"a change at ({ch.x}, {ch.y}) does not fit {w} x {h}")
    if frame.changes.full:
        out = Grid(w, h)
    elif grid is None or grid.size != (w, h):
        return Malformed("order", "a partial frame with no grid of its size under it")
    elif own:
        out = grid                  # the caller owns it: a cost per change, not per cell
    else:
        out = grid.copy()
    for ch in frame.changes.items:
        write(out, ch.x, ch.y, ch.cells)
    return out


def negotiate(theirs: "tuple[int, ...]", ours: "tuple[int, ...]" = VERSIONS) -> "int | None":
    """The highest version both sides speak, or None."""
    for v in (*theirs, *ours):
        if not _is_int(v):
            raise TypeError(f"a version must be an int, got {type(v).__name__}")
    common = set(theirs) & set(ours)
    return max(common) if common else None


def valid_name(name: object) -> bool:
    """Whether `name` is a str matching NAME (a session or app name)."""
    return _matches(_NAME, name)
