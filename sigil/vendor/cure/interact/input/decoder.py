"""[Decoder]: bytes in, events out; a lone Esc told apart by the `now` given.

Kind: service (an incremental decoder object on a Vt `Parser("input")`, and the pure
`event` op that turns Vt's actions into [Events]); pure: no I/O, no clock read, no
process-wide state. Time comes in only as the `now` argument, the app's own clock.

It uses Vt's `feed` (`[Decoder] -> [Vt] : feed({Bytes}) => {Actions}`): the parser does
the bytes (incremental UTF-8, CSI / SS3 / OSC / DCS, X10 mouse, bracketed paste, Esc as
Alt); the decoder provides `event` on top of [Events] (`[Decoder] -> [Events] :
event({Actions}) => {Events}`): each action becomes the key, mouse report, paste, focus
change, resize or query reply it stands for. Keys and clicks reach the same Router and
fire the same actions; telling a person's input from a terminal's reply is done here.

Invariant: paste_is_text — the bytes of a bracketed paste never become `Key` (or any
  other) events, whatever they hold (ESC, controls, `CSI 200~`, mouse reports, a
  partial end marker). For any bytes `p` that do not contain `b"\\x1b[201~"`, the
  events of `b"\\x1b[200~" + p + b"\\x1b[201~"` fed to a fresh decoder in any chunks
  (at one `now`; or at any `now`s once the start marker is complete, as time never
  cuts a paste), then ended, are exactly `(Paste(p.decode("utf-8", "replace")),)`;
  and for bytes `a` that leave a fresh decoder with nothing pending and its carry
  `Carry()`, and any bytes `c`,
  `decode(a + b"\\x1b[200~" + p + b"\\x1b[201~" + c) == decode(a) +
  (Paste(p.decode("utf-8", "replace")),) + decode(c)`. A paste is never cut by the
  Esc timeout: while the parser is in "paste", nothing is due.

## The object

- `Decoder(timeout=0.05)`: a fresh decoder, holding a fresh `Parser("input")` and an
  empty `Carry`. `timeout`: how long held bytes (a lone ESC, an unfinished sequence)
  may wait for the rest, in the units of `now` (0.05 is 50 ms for a `now` from
  `time.monotonic()`; tens of ms locally, longer over ssh). An `int` or `float`, not a
  `bool`, `TypeError` otherwise; `ValueError` unless it is > 0 (finite).
  `decoder.timeout` reads it back.
- `decoder.feed(data, now) -> tuple[Event, ...]`: the events `data` completes, in
  order. `data`: `bytes`, `bytearray` or `memoryview` (`TypeError` otherwise, a `str`
  included); `now`: an `int` or `float`, not a `bool` (`TypeError`). In order:
  1. when `self.due(now)`, everything held is ended first, as `end()` does, and its
     events come first;
  2. `actions = feed(self.parser, data)` (Vt's op), then `event(actions, carry)` with
     the decoder's carry, which it keeps;
  3. when `data` is not empty, `now` is noted as the time of the last byte.
  No byte content raises. `feed(b"", now)` does only step 1 (an app woken by
  `deadline` may call it, or `flush`).
- `decoder.pending -> bool`: `self.parser.pending` (bytes held: a lone ESC, a partial
  UTF-8 character, an unfinished sequence, string or paste).
- `decoder.deadline -> float | int | None`: when the held bytes are due: the time of
  the last byte plus `timeout`, when `pending` and the parser is not in "paste"; else
  `None`. The app's loop sleeps at most until it (`term.read(timeout=deadline - now)`).
- `decoder.due(now) -> bool`: `deadline is not None and now >= deadline`. So a byte
  that arrives exactly `timeout` after the last one finds the held bytes due.
  `TypeError` as for `feed`'s `now`.
- `decoder.flush(now) -> tuple[Event, ...]`: `end()` when `due(now)`, else `()`.
- `decoder.end() -> tuple[Event, ...]`: everything held, as the end of the stream,
  whatever the time: `actions = self.parser.flush()` (a lone ESC becomes the Esc key,
  `ESC [` becomes Alt+[, a partial character U+FFFD, an unfinished paste its text so
  far; see Vt's [Parser], "Flush"), then `event(actions, carry)`; then a DCS still
  being collected in the carry is dropped (it gives nothing). Afterwards nothing is
  pending and `deadline` is `None`.
- `decoder.expect_cpr() -> None`: the app (Term's probe) has asked for a cursor
  position report (`CSI 6 n`): the next `CSI 1 ; m R` is a reply, not Shift..F3 (see
  "CSI"). Each call adds one to `carry.cpr`; each CPR reply decoded takes one off.
- `decoder.parser -> Parser`, `decoder.carry -> Carry`: read-only views of its state.

Chunk independence (a law): for any bytes `data`, any split of it into chunks
`c1 .. cn` (empty chunks allowed) and one `now` for every call, on fresh decoders `d`
and `e` with one timeout, `d.feed(c1, now) + ... + d.feed(cn, now) + d.end() ==
e.feed(data, now) + e.end() == decode(data)`, and `d.pending`, `d.deadline`,
`d.carry` equal `e`'s after the last feed. (With one `now` nothing is ever due between
the chunks, since `timeout > 0`.) Only time splits a sequence: with timeout 0.05,
`feed(b"\\x1b", 0)` then `feed(b"a", 0.01)` is `(Key("a", {"alt"}),)`, but `feed(b"\\x1b",
0)` then `feed(b"a", 0.05)` is `(Key("escape"), Key("a", text="a"))`.

## event: actions to events

- `event(actions, carry=Carry()) -> tuple[tuple[Event, ...], Carry]`: the events for
  an iterable of Vt actions, in order, and the carry after them. Pure: the same actions
  and carry always give the same result. `TypeError` when an item is not one of Vt's
  `ACTIONS` or `carry` is not a `Carry`; never on any action's content (an action
  nothing below fits becomes `Unknown(action)`).
- `Carry(button=None, hook=None, data=b"", cpr=0)` (frozen dataclass): what one action
  leaves for the next: `button`, the X10 button pressed and not yet released ("left",
  "middle", "right" or `None`); `hook`, the `Hook` of a DCS being collected (or
  `None`) and `data` its `Put` bytes so far; `cpr`, the cursor position reports still
  expected (an `int` >= 0).

In the rules below, "mods(m)" is the modifier set of a modifier number `m` (an `int`;
`None` or < 1 count as 1): the bits of `m - 1`, shift 1, alt 2, ctrl 4, super 8,
hyper 16, meta 32 (caps lock 64, num lock 128 and higher bits ignored). "The key's
fields" are `Csi.param`-style reads: the modifier number is the first sub-parameter of
the second parameter (default 1), its event type the second sub-parameter of that
parameter (1 or `None` "press", 2 "repeat", 3 "release"; any other value: the action
is `Unknown`). Every key's `text` is `text_of(name, mods)` unless a rule says
otherwise, and every `Key` given is in [Events]' normal form (`normal(k) == k`): the
rules below name the key, and `normal` then lower-cases an ASCII letter with "shift"
added, or folds a shifted character into the one its text gives. The decoder reaches
[Events] through its face alone: the canonical text is Events' `text_of(name, mods)`
and the normal form is Events' `normal(key)` (`[Decoder] -> [Events] : normal`), so a
key is `normal(Key(name, mods, text, kind))` with `text` given or `text_of(name,
mods)`; never Events' private `_normal` / `_text`.

### Print, Execute, Esc

- `Print(text)`: one event per code point `c`, in order: " " gives
  `Key("space", text=" ")`; a printable `c` gives `normal(Key(c, text=c))` (a legacy
  terminal sends Shift+A as "A": `Key("a", {"shift"}, "A")`, the stroke "shift+a");
  any other `c` (a format or C1 character such as U+200D, U+0085) gives
  `Unknown(Print(c))`.
- `Execute(code)`, a C0 control or DEL as a key, text "":
  0x1B `Key("escape")` (a lone ESC, after the timeout or `end`); 0x0D `Key("enter")`;
  0x09 `Key("tab")`; 0x7F `Key("backspace")`; 0x00 `Key("space", {"ctrl"})`; 0x1C
  `Key("\\\\", {"ctrl"})`; 0x1D `Key("]", {"ctrl"})`; 0x1E `Key("^", {"ctrl"})`; 0x1F
  `Key("_", {"ctrl"})`; every other code 0x01..0x1A `Key(chr(0x60 + code), {"ctrl"})`
  (0x01 ctrl+a, 0x08 ctrl+h, 0x0A ctrl+j, 0x1A ctrl+z).
- `Esc(final)` (ESC then a character: Alt), with "alt" added to the mods: when
  `final` is a C0 control or DEL, the `Execute` key of its code plus "alt"
  (`Esc("\\r")` alt+enter, `Esc("\\x7f")` alt+backspace, `Esc("\\x01")` ctrl+alt+a); " "
  `Key("space", {"alt"})`; a printable character `Key(final, {"alt"})` (`Esc("a")`
  alt+a, `Esc("O")` `Key("o", {"alt", "shift"})`, `Esc("[")` alt+[); text "" in
  each. Anything else (an
  `Esc` with intermediates, a non-printable `final`): `Unknown`.
  ESC ESC [ A arrives as two actions (the parser gives the first ESC alone):
  `Key("escape")` then `Key("up")`; no merging.

### CSI (`Csi(final, params, private, intermediates)`)

With no private marker and no intermediates, by `final`:
- "A" up, "B" down, "C" right, "D" left, "H" home, "F" end, "P" f1, "Q" f2, "S" f4:
  `Key(name, mods(m), "", event)` from the key's fields (`CSI A`, `CSI 1;5A`
  ctrl+up, `CSI 1;2:3A` a shift+up release; the first parameter is not read).
- "R": `CSI 1 ; m R` with exactly two parameters, first value 1 and `m >= 2`, while
  `carry.cpr == 0`, is f3 with mods(m) (legacy Shift..F3). Every other `Csi("R")` is
  `Reply("cpr", "R", params)`, and takes one off `carry.cpr` when it is > 0.
- "Z": `Key("tab", {"shift"} | mods(m), "", event)` (`CSI Z` shift+tab).
- "~", by the first parameter's value n: 1 or 7 home, 2 insert, 3 delete, 4 or 8 end,
  5 page_up, 6 page_down, 11 f1, 12 f2, 13 f3 (kitty's F3), 14 f4, 15 f5, 17 f6, 18 f7,
  19 f8, 20 f9, 21 f10, 23 f11, 24 f12; mods and event from the key's fields
  (`CSI 3~` delete, `CSI 15;2~` shift+f5). Any other n (201 outside a paste
  included): `Unknown`.
- "u": a kitty key, `CSI code[:shifted[:base]] [; m[:event] [; text]] u`. The name from
  `code`: 9 tab, 13 enter, 27 escape, 32 space, 127 backspace, 57399..57408
  kp_0..kp_9, 57409 kp_decimal, 57410 kp_divide, 57411 kp_multiply, 57412
  kp_subtract, 57413 kp_add, 57414 kp_enter, 57415 kp_equal; any other code that is a
  printable character (not a surrogate, <= 0x10FFFF, not 57344..63743 where kitty puts
  its other functional keys) that character (kitty sends the unshifted key: 97 for
  A); anything else (`code` missing, caps lock, a lone modifier key ...): `Unknown`.
  Mods and event as for the key's fields. `text`: when the third parameter is given,
  its sub-parameters as code points (`None` and invalid ones skipped: `CSI 97;;97u`
  has text "a"); else, when "shift" is held, no other of ctrl, alt, super, hyper, meta
  is, the key is a character key and `shifted` is given, `chr(shifted)` (`CSI
  97:65;2u` is `Key("a", {"shift"}, "A")`); else `text_of(name, mods)` (`CSI 97;2u` is
  `Key("a", {"shift"}, "A")` too). The base-layout key is not read.
- "I" `Focus(True)`, "O" `Focus(False)`.
- "n": `Reply("status", "n", params)`.
- "t": with first parameter 48 and at least three, `Resize(width=cols, height=rows)`
  from `CSI 48 ; rows ; cols [; ph ; pw] t` (mode 2048's in-band resize) when
  `1 <= cols <= MAX_RESIZE` and `1 <= rows <= MAX_RESIZE` (`MAX_RESIZE = 4096`); a
  value 0, missing or past it, and any other `Csi("t")`, is `Reply("window", "t",
  params)`. Gating the report on mode 2048 is the app's (cure never enables it).
- anything else: `Unknown`.
With a private marker or intermediates:
- `CSI ? ... c` `Reply("da1", ...)`; `CSI > ... c` `Reply("da2", ...)`;
  `CSI ? ... R` `Reply("cpr", ...)` (takes one off `carry.cpr` as above);
  `CSI ? ... u` `Reply("kitty", ...)`; `CSI [?] ... $ y` (intermediates "$", private
  "?" or "") `Reply("decrpm", ...)`; each with the `Csi`'s `final`, `params`,
  `private`, `intermediates`.
- `CSI < cb ; px ; py M` / `m`: an SGR mouse report (below).
- anything else: `Unknown`.

### Mouse

A button code `b` reads: low = `b & 3`, motion = `b & 32`, mods shift `b & 4`, alt
`b & 8`, ctrl `b & 16`, group = `b & 192` (0 buttons, 64 wheels, 128 extra buttons).
Group 0: low 0 left, 1 middle, 2 right, 3 none; group 64: low 0 wheel_up, 1
wheel_down, 2 wheel_left, 3 wheel_right; group 128 (buttons 8..11), and 192: `Unknown`.

- SGR (`Csi("M" | "m", private="<")`): exactly three parameters with values (not
  `None`) `cb`, `px`, `py`, `px >= 1` and `py >= 1`, else `Unknown`; `x = px - 1`,
  `y = py - 1`, `b = cb`. Final "M": with motion, `Mouse(button, "move", ...)`
  (`button` `None` for low 3 in group 0; a wheel with motion is `Unknown`); without,
  a "press" of the button (group 0 low 3 without motion: `Unknown`). Final "m": a
  "release" of the button (motion bit ignored); group 0 low 3, or a wheel: `Unknown`
  (a wheel step has no release).
- X10 (`LegacyMouse(cb, cx, cy)`): `b = cb - 32`, `x = cx - 33`, `y = cy - 33`; any of
  them negative: `Unknown`. With motion: a "move" (a drag of the button, or `button`
  `None` for low 3; a wheel: `Unknown`). Without, group 0: low 0..2 a "press" of that
  button, which `carry.button` then holds; low 3 a "release" of `carry.button` (or
  "left" when it is `None`), after which `carry.button` is `None` (X10 does not say
  which button was released). Group 64 without motion: a "press" of the wheel
  (`carry.button` unchanged).

### Paste, OSC, DCS, the rest

- `Pasted(text)`: `Paste(text)`, exactly one, whatever `text` holds (paste_is_text).
- `Osc(data, bel)`: `Reply("osc", data=data)`.
- `Hook(...)`: starts a DCS (a DCS already open in the carry is dropped): `carry.hook`
  is the `Hook`, `carry.data` b""; no event. `Put(data)` with a DCS open: appended to
  `carry.data`, no event, up to `MAX_DCS = 1 << 20` bytes (as Vt's `MAX_OSC`); bytes
  past it are dropped. `Unhook()` with a DCS open: `Reply("dcs", hook.final,
  hook.params, hook.private, hook.intermediates, carry.data)`, and the DCS is closed.
  The data is gathered in linear time (chunks joined once, not bytes + bytes per
  `Put`).
  A `Put` or `Unhook` with none open: `Unknown`.
- `Ss3(final, params)` (`ESC O`): mods(m) with m the first parameter's value (`ESC O
  2 P` shift+f1; none given: 1). "A" up, "B" down, "C" right, "D" left, "H" home,
  "F" end, "P" f1, "Q" f2, "R" f3, "S" f4; the keypad in application mode: "p".."y"
  kp_0..kp_9, "n" kp_decimal, "o" kp_divide, "j" kp_multiply, "m" kp_subtract, "k"
  kp_add, "M" kp_enter, "X" kp_equal; any other final: `Unknown`.

## Laws (round trips through Vt's [Encode])

Write `dec(b)` for `decode(b)` (a fresh decoder, ended) and `enc(e, m)` for
`encode(e, m)`.
- Bytes: for every `Modes` `m` and every event `e` Encode accepts, with `e` a `Key`
  whose `text == text_of(e.name, e.mods)` and `event == "press"`, a `Mouse`, a `Focus`,
  or (when `m.paste`) a `Paste` whose text has no lone surrogate: every event of
  `dec(enc(e, m))` is a `Key`, `Mouse`, `Focus` or `Paste`, and
  `b"".join(enc(d, m) for d in dec(enc(e, m))) == enc(e, m)`.
- Keys, exactly by stroke: for every stroke `s` and `k = key(s)`, with `m.kitty & 8`
  (every key as an escape) and `m.kitty & 16`, `dec(enc(k, m))` is one `Key` `d` with
  `stroke(d) == s` and `d.text == k.text`; with `m.kitty & 1` (and not 8) the same
  holds except for "shift+space" and a non-letter character key with only "shift"
  held ("shift+1"), which kitty sends as their legacy text (" ", "1").
- Mouse with `m.mouse_sgr` and `e` reported by `m.mouse` (Encode gives bytes):
  `dec(enc(e, m)) == (e',)` where `e'` is `e` with its mods cut to those the report
  carries (shift, alt, ctrl; none under `mouse == 9`).
- Focus with `m.focus`: `dec(enc(e, m)) == (e,)`. Paste with `m.paste`:
  `dec(enc(Paste(t), m)) == (Paste(t'),)`, `t'` being `t` with every `"\\x1b[201~"`
  removed as Encode removes it.

Inputs: {Bytes} (`bytes`, `bytearray`, `memoryview`), `now` (the app's clock, a
number), Vt's {Actions}. Outputs: {Events}, a tuple of [Events]' values. Errors:
`TypeError` / `ValueError` for wrong argument types or a bad `timeout`, as stated;
never on any byte content. Effects: none, apart from the state a `Decoder` keeps for
its own stream (its parser, carry and the time of its last byte).

Usage:
    from cure.interact.input.decoder import Decoder, event, Carry
    from cure.interact.input.events import Key, Mouse, Paste, Focus, Reply
    from cure.interact.vt import Esc
    d = Decoder(timeout=0.05)
    d.feed(b"q", 0.0)                          # (Key("q", text="q"),)
    d.feed(b"\\x1b[1;5A\\x01", 0.0)             # (Key("up", {"ctrl"}), Key("a", {"ctrl"}))
    d.feed(b"\\x1b", 1.0)                      # (); d.pending, d.deadline == 1.05
    d.feed(b"", 1.05)                          # (Key("escape"),): it was due
    d.feed(b"\\x1b[<0;5;3M", 2.0)              # (Mouse("left", "press", 4, 2),)
    d.feed(b"\\x1b[200~a\\x1b[Bb\\x1b[201~", 2.0)  # (Paste("a\\x1b[Bb"),)
    d.feed(b"\\x1b[97;5u\\x1b[I", 2.0)          # (Key("a", {"ctrl"}), Focus(True))
    d.feed(b"\\x1b[?62;22c", 2.0)              # (Reply("da1", "c", ((62,), (22,)), "?"),)
    d.feed(b"\\x1b[1;2R", 2.0)                 # (Key("f3", {"shift"}),)
    d.expect_cpr(); d.feed(b"\\x1b[1;2R", 2.0) # (Reply("cpr", "R", ((1,), (2,))),)
    event((Esc("x"),))                         # ((Key("x", {"alt"}),), Carry())
"""

from collections.abc import Iterable
from dataclasses import dataclass

import math

from cure.interact.vt import (
    ACTIONS, Csi, Esc, Execute, Hook, LegacyMouse, Osc, Parser, Pasted, Print, Put, Ss3, Unhook,
    feed,
)
from cure.interact.vt.performer import Action

from .events import Event, Focus, Key, Mouse, Paste, Reply, Resize, Unknown, normal, text_of

MAX_RESIZE = 4096   # an in-band resize past it (either side) is a Reply("window")
MAX_DCS = 1 << 20   # a DCS's data kept, as Vt's MAX_OSC; bytes past it are dropped


@dataclass(frozen=True)
class Carry:
    """What one action leaves for the next: X10's held button, an open DCS, CPRs expected."""

    button: "str | None" = None
    hook: "Hook | None" = None
    data: bytes = b""
    cpr: int = 0

    def __post_init__(self) -> None:
        if self.button is not None and self.button not in ("left", "middle", "right"):
            raise ValueError(f"Carry.button must be left, middle, right or None, got {self.button!r}")
        if self.hook is not None and not isinstance(self.hook, Hook):
            raise TypeError("Carry.hook must be a Hook or None")
        if not isinstance(self.data, bytes):
            raise TypeError("Carry.data must be bytes")
        if isinstance(self.cpr, bool) or not isinstance(self.cpr, int):
            raise TypeError("Carry.cpr must be an int")
        if self.cpr < 0:
            raise ValueError("Carry.cpr must be >= 0")


_MOD_NAMES = ("shift", "alt", "ctrl", "super", "hyper", "meta")
_MODS = tuple(frozenset(n for i, n in enumerate(_MOD_NAMES) if bits >> i & 1) for bits in range(64))
_ALT = frozenset({"alt"})
_SHIFT = frozenset({"shift"})
_CTRL = frozenset({"ctrl"})
_EVENT_TYPES = {None: "press", 1: "press", 2: "repeat", 3: "release"}
_NO_SHIFTED_MODS = frozenset({"ctrl", "alt", "super", "hyper", "meta"})


def _mods(m: "int | None") -> frozenset:
    """mods(m): the bits of m - 1 (None or < 1 count as 1), above meta ignored."""
    if m is None or m < 1:
        return _MODS[0]
    return _MODS[(m - 1) & 63]


def _execute_key(code: int) -> "tuple[str, frozenset]":
    """An Execute's key fields (name, mods); the Key is built by `_key` when it comes."""
    names = {0x1B: ("escape", ()), 0x0D: ("enter", ()), 0x09: ("tab", ()),
             0x7F: ("backspace", ()), 0x00: ("space", ("ctrl",)), 0x1C: ("\\", ("ctrl",)),
             0x1D: ("]", ("ctrl",)), 0x1E: ("^", ("ctrl",)), 0x1F: ("_", ("ctrl",))}
    name, mods = names.get(code, (chr(0x60 + code), ("ctrl",)))
    return name, frozenset(mods)


_EXECUTE = {code: _execute_key(code) for code in (*range(0x20), 0x7F)}
_EXECUTE_ALT = {code: (name, mods | _ALT) for code, (name, mods) in _EXECUTE.items()}

_CSI_LETTERS = {"A": "up", "B": "down", "C": "right", "D": "left", "H": "home", "F": "end",
                "P": "f1", "Q": "f2", "S": "f4"}
_TILDE = {1: "home", 7: "home", 2: "insert", 3: "delete", 4: "end", 8: "end", 5: "page_up",
          6: "page_down", 11: "f1", 12: "f2", 13: "f3", 14: "f4", 15: "f5", 17: "f6",
          18: "f7", 19: "f8", 20: "f9", 21: "f10", 23: "f11", 24: "f12"}
_KITTY = {9: "tab", 13: "enter", 27: "escape", 32: "space", 127: "backspace",
          57409: "kp_decimal", 57410: "kp_divide", 57411: "kp_multiply", 57412: "kp_subtract",
          57413: "kp_add", 57414: "kp_enter", 57415: "kp_equal"} | {
    57399 + i: f"kp_{i}" for i in range(10)}
_SS3 = {"A": "up", "B": "down", "C": "right", "D": "left", "H": "home", "F": "end",
        "P": "f1", "Q": "f2", "R": "f3", "S": "f4", "n": "kp_decimal", "o": "kp_divide",
        "j": "kp_multiply", "m": "kp_subtract", "k": "kp_add", "M": "kp_enter",
        "X": "kp_equal"} | {chr(ord("p") + i): f"kp_{i}" for i in range(10)}
_BUTTONS = ("left", "middle", "right", None)
_WHEELS = ("wheel_up", "wheel_down", "wheel_left", "wheel_right")


def _key(name: str, mods: frozenset, text: "str | None" = None, kind: str = "press") -> Key:
    """A Key in normal form; `text` None is the canonical text."""
    if text is None:
        text = text_of(name, mods)
    return normal(Key(name, mods, text, kind))


def _fields(a: Csi) -> "tuple[frozenset, str | None]":
    """The key's fields: mods(m) and the event type (None when it is not one of the three)."""
    params = a.params
    if len(params) < 2:
        return _MODS[0], "press"
    p = params[1]
    return _mods(p[0]), _EVENT_TYPES.get(p[1] if len(p) > 1 else None)


def _code_point(c: "int | None") -> bool:
    return c is not None and 0 <= c <= 0x10FFFF and not 0xD800 <= c <= 0xDFFF


def _print(a: Print, out: list) -> None:
    for c in a.text:
        if c == " ":
            out.append(_key("space", _MODS[0], " "))
        elif c.isprintable():
            out.append(_key(c, _MODS[0], c))
        else:
            out.append(Unknown(Print(c)))


def _esc(a: Esc) -> Event:
    final = a.final
    if a.intermediates or len(final) != 1:
        return Unknown(a)
    code = ord(final)
    if code in _EXECUTE_ALT:
        return _key(*_EXECUTE_ALT[code], "")
    if final == " ":
        return _key("space", _ALT, "")
    if final.isprintable():
        return _key(final, _ALT, "")
    return Unknown(a)


def _kitty(a: Csi) -> Event:
    params = a.params
    if not params:
        return Unknown(a)
    first = params[0]
    code = first[0]
    if code is None:
        return Unknown(a)
    name = _KITTY.get(code)
    if name is None:
        if not _code_point(code) or 57344 <= code <= 63743:
            return Unknown(a)
        name = chr(code)
        if name == " " or not name.isprintable():
            return Unknown(a)
    mods, kind = _fields(a)
    if kind is None:
        return Unknown(a)
    if len(params) >= 3:
        text = "".join(chr(c) for c in params[2] if _code_point(c))
    else:
        shifted = first[1] if len(first) > 1 else None
        if (len(name) == 1 and "shift" in mods and mods.isdisjoint(_NO_SHIFTED_MODS)
                and _code_point(shifted)):
            text = chr(shifted)
        else:
            text = None
    return _key(name, mods, text, kind)


def _sgr(a: Csi) -> Event:
    params = a.params
    if len(params) != 3:
        return Unknown(a)
    cb, px, py = params[0][0], params[1][0], params[2][0]
    if cb is None or px is None or py is None or px < 1 or py < 1:
        return Unknown(a)
    group, low, motion = cb & 192, cb & 3, cb & 32
    mods = _mouse_mods(cb)
    x, y = px - 1, py - 1
    if group == 0:
        button = _BUTTONS[low]
        if a.final == "M":
            if motion:
                return Mouse(button, "move", x, y, mods)
            if button is None:
                return Unknown(a)
            return Mouse(button, "press", x, y, mods)
        if button is None:
            return Unknown(a)
        return Mouse(button, "release", x, y, mods)
    if group == 64 and a.final == "M" and not motion:
        return Mouse(_WHEELS[low], "press", x, y, mods)
    return Unknown(a)


def _mouse_mods(b: int) -> frozenset:
    return _MODS[(1 if b & 4 else 0) | (2 if b & 8 else 0) | (4 if b & 16 else 0)]


def _private(a: Csi, carry: Carry) -> "tuple[Event, Carry]":
    final, private, inter = a.final, a.private, a.intermediates
    if inter == "$" and final == "y" and private in ("?", ""):
        return Reply("decrpm", final, a.params, private, inter), carry
    if not inter:
        if final == "c" and private == "?":
            return Reply("da1", final, a.params, private), carry
        if final == "c" and private == ">":
            return Reply("da2", final, a.params, private), carry
        if final == "R" and private == "?":
            if carry.cpr:
                carry = Carry(carry.button, carry.hook, carry.data, carry.cpr - 1)
            return Reply("cpr", final, a.params, private), carry
        if final == "u" and private == "?":
            return Reply("kitty", final, a.params, private), carry
        if final in "Mm" and private == "<":
            return _sgr(a), carry
    return Unknown(a), carry


def _csi(a: Csi, carry: Carry) -> "tuple[Event, Carry]":
    if a.private or a.intermediates:
        return _private(a, carry)
    final = a.final
    name = _CSI_LETTERS.get(final)
    if name is not None:
        mods, kind = _fields(a)
        return (Unknown(a) if kind is None else _key(name, mods, "", kind)), carry
    if final == "u":
        return _kitty(a), carry
    if final == "~":
        params = a.params
        name = _TILDE.get(params[0][0]) if params else None
        mods, kind = _fields(a)
        if name is None or kind is None:
            return Unknown(a), carry
        return _key(name, mods, "", kind), carry
    if final == "R":
        params = a.params
        if (len(params) == 2 and params[0][0] == 1 and params[1][0] is not None
                and params[1][0] >= 2 and carry.cpr == 0):
            mods, kind = _fields(a)
            if kind is not None:
                return _key("f3", mods, "", kind), carry
        if carry.cpr:
            carry = Carry(carry.button, carry.hook, carry.data, carry.cpr - 1)
        return Reply("cpr", final, a.params), carry
    if final == "Z":
        mods, kind = _fields(a)
        return (Unknown(a) if kind is None else _key("tab", mods | _SHIFT, "", kind)), carry
    if final == "I":
        return Focus(True), carry
    if final == "O":
        return Focus(False), carry
    if final == "n":
        return Reply("status", final, a.params), carry
    if final == "t":
        params = a.params
        if len(params) >= 3 and params[0][0] == 48:
            rows, cols = params[1][0], params[2][0]
            if rows and cols and rows <= MAX_RESIZE and cols <= MAX_RESIZE:
                return Resize(cols, rows), carry
        return Reply("window", final, params), carry
    return Unknown(a), carry


def _x10(a: LegacyMouse, carry: Carry) -> "tuple[Event, Carry]":
    b, x, y = a.cb - 32, a.cx - 33, a.cy - 33
    if b < 0 or x < 0 or y < 0:
        return Unknown(a), carry
    group, low, motion = b & 192, b & 3, b & 32
    mods = _mouse_mods(b)
    if group == 0:
        if motion:
            return Mouse(_BUTTONS[low], "move", x, y, mods), carry
        if low == 3:
            button = carry.button or "left"
            return Mouse(button, "release", x, y, mods), Carry(None, carry.hook, carry.data, carry.cpr)
        button = _BUTTONS[low]
        return Mouse(button, "press", x, y, mods), Carry(button, carry.hook, carry.data, carry.cpr)
    if group == 64 and not motion:
        return Mouse(_WHEELS[low], "press", x, y, mods), carry
    return Unknown(a), carry


def _ss3(a: Ss3) -> Event:
    name = _SS3.get(a.final)
    if name is None:
        return Unknown(a)
    m = a.params[0][0] if a.params else None
    mods = _mods(m)
    return _key(name, mods)


def event(actions: "Iterable[Action]", carry: Carry = Carry()) -> "tuple[tuple[Event, ...], Carry]":
    """The events Vt's actions stand for, and the carry after them (see the module)."""
    if not isinstance(carry, Carry):
        raise TypeError(f"carry must be a Carry, got {type(carry).__name__}")
    buf = bytearray()
    if carry.hook is not None:
        buf += carry.data[:MAX_DCS]
        carry = Carry(carry.button, carry.hook, b"", carry.cpr)
    events, carry = _event(actions, carry, buf)
    if carry.hook is not None:
        carry = Carry(carry.button, carry.hook, bytes(buf), carry.cpr)
    return events, carry


def _event(actions: "Iterable[Action]", carry: Carry, buf: bytearray) -> "tuple[tuple[Event, ...], Carry]":
    """`event`, with an open DCS's data in `buf` (grown in place, so linear over many
    calls), not in `carry.data`, which stays b"" while the DCS is open."""
    out: list = []
    append = out.append
    for a in actions:
        t = type(a)
        if t is Print:
            _print(a, out)
        elif t is Execute:
            f = _EXECUTE.get(a.code)
            append(_key(*f, "") if f is not None else Unknown(a))
        elif t is Csi:
            e, carry = _csi(a, carry)
            append(e)
        elif t is Pasted:
            append(Paste(a.text))
        elif t is Esc:
            append(_esc(a))
        elif t is Ss3:
            append(_ss3(a))
        elif t is LegacyMouse:
            e, carry = _x10(a, carry)
            append(e)
        elif t is Osc:
            append(Reply("osc", data=a.data))
        elif t is Hook:
            carry = Carry(carry.button, a, b"", carry.cpr)
            buf.clear()
        elif t is Put:
            if carry.hook is None:
                append(Unknown(a))
            else:
                room = MAX_DCS - len(buf)
                if room > 0:
                    buf += a.data if len(a.data) <= room else a.data[:room]
        elif t is Unhook:
            h = carry.hook
            if h is None:
                append(Unknown(a))
            else:
                append(Reply("dcs", h.final, h.params, h.private, h.intermediates, bytes(buf)))
                carry = Carry(carry.button, None, b"", carry.cpr)
                buf.clear()
        elif isinstance(a, ACTIONS):
            append(Unknown(a))
        else:
            raise TypeError(f"not a Vt action: {type(a).__name__}")
    return tuple(out), carry


def _number(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be an int or float, got {type(value).__name__}")


def _bytes(data: object) -> None:
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError(f"data must be bytes, bytearray or memoryview, got {type(data).__name__}")


class Decoder:
    """An incremental decoder: bytes and the app's `now` in, events out (see the module)."""

    __slots__ = ("_timeout", "_parser", "_carry", "_dcs", "_last")

    def __init__(self, timeout: "float | int" = 0.05) -> None:
        _number(timeout, "timeout")
        if not (timeout > 0 and math.isfinite(timeout)):
            raise ValueError(f"timeout must be > 0 and finite, got {timeout}")
        self._timeout = timeout
        self._parser = Parser("input")
        self._carry = Carry()
        self._dcs = bytearray()   # an open DCS's data; `carry` shows it as `data`
        self._last = None

    @property
    def timeout(self) -> "float | int":
        return self._timeout

    @property
    def parser(self) -> Parser:
        return self._parser

    @property
    def carry(self) -> Carry:
        c = self._carry
        if c.hook is None:
            return c
        return Carry(c.button, c.hook, bytes(self._dcs), c.cpr)

    @property
    def pending(self) -> bool:
        return self._parser.pending

    @property
    def deadline(self) -> "float | int | None":
        p = self._parser
        if not p.pending or p.state == "paste" or self._last is None:
            return None
        return self._last + self._timeout

    def due(self, now: "float | int") -> bool:
        _number(now, "now")
        d = self.deadline
        return d is not None and now >= d

    def feed(self, data: "bytes | bytearray | memoryview", now: "float | int") -> "tuple[Event, ...]":
        _bytes(data)
        _number(now, "now")
        first = self.end() if self.due(now) else ()
        if not data:
            return first
        events, self._carry = _event(feed(self._parser, data), self._carry, self._dcs)
        self._last = now
        return first + events if first else events

    def flush(self, now: "float | int") -> "tuple[Event, ...]":
        return self.end() if self.due(now) else ()

    def end(self) -> "tuple[Event, ...]":
        events, carry = _event(self._parser.flush(), self._carry, self._dcs)
        if carry.hook is not None or carry.data:
            carry = Carry(carry.button, None, b"", carry.cpr)
        self._dcs.clear()
        self._carry = carry
        return events

    def expect_cpr(self) -> None:
        c = self._carry
        self._carry = Carry(c.button, c.hook, c.data, c.cpr + 1)
