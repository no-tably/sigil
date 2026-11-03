"""[Encode]: the other direction: keys and mouse as a target's modes want them.

Kind: service (a pure function from an input event and a target's {Modes} to {Bytes}).

construct forwards a person's keys, clicks, pastes and focus to the program in a pane
(`[Pty] -> [Vt] : encode({Event}) => {Bytes}`): the outer terminal's input is decoded
into Input's events (I1), and Encode writes each one again the way the pane's program
asked for, by the modes it set. Raw bytes are never passed through (outer and inner
terminals differ).

## The target's modes

`Modes` is a frozen dataclass, the input-side modes a program has set. V2's Screen
keeps one from the program's own sequences (noted per field); Encode only reads it.

- `cursor_keys: bool = False` — DECCKM, `CSI ? 1 h` / `l`: arrows and Home / End as
  SS3 (application) instead of CSI (normal).
- `keypad: bool = False` — DECKPAM `ESC =` / DECKPNM `ESC >`: keypad keys as SS3.
- `kitty: int = 0` — the kitty keyboard flags in force (the top of the program's
  `CSI > flags u` / `CSI < u` stack, or what `CSI = flags ; mode u` set), 0..31:
  1 disambiguate, 2 event types, 4 alternate keys, 8 all keys as escapes, 16
  associated text. 0 is legacy.
- `mouse: int = 0` — mouse tracking: 0 off, 9 (X10 compatibility, `?9`), 1000 (press
  and release), 1002 (also motion with a button held), 1003 (all motion); the mode the
  program set last, 0 once it reset it.
- `mouse_sgr: bool = False` — `?1006`: SGR mouse encoding; False is the legacy X10
  encoding (1005 and 1015 are not kept: a program that asks only for them gets X10).
- `paste: bool = False` — `?2004`: bracketed paste.
- `focus: bool = False` — `?1004`: focus in / out reports.

`Modes()` is a program that set nothing. `TypeError` when a bool field is not a
`bool`, or `kitty` / `mouse` is not an `int` (a `bool` is not accepted for them);
`ValueError` when `kitty` is outside 0..31 or `mouse` is not one of 0, 9, 1000, 1002,
1003.

## The events Encode reads (duck-typed; Vt cannot import Input)

`encode(event, modes)` tells the event's kind by its class name, `type(event).__name__`
(Input's names, as the spec gives them), and reads only these attributes:

- "Key": `name` (`str`), `mods`, `text` (`str`, what the key would insert; may be "").
- "Mouse": `button`, `kind` (`str`), `x`, `y` (`int`, 0-based cells in the target),
  `mods`.
- "Paste": `text` (`str`).
- "Focus": `focused` (`bool`: True for focus in, False for out).
- "Resize": nothing (a size goes to the pty, not its input): encodes to `b""`.

`mods`: an iterable of modifier names (a `frozenset` is expected; a `str` is not
accepted), each one of `MODS`: "shift", "alt", "ctrl", "super", "hyper", "meta".
Their bits, the same in every encoding below: shift 1, alt 2, ctrl 4, super 8, hyper
16, meta 32; the modifier number `m = 1 + sum(bits)`.

Key names (`name`):
- a character key: one code point, printable (`str.isprintable()`), not the space,
  e.g. "a", "A", "é", "1", "/";
- the named keys, `KEYS`: "up", "down", "left", "right", "home", "end", "insert",
  "delete", "page_up", "page_down", "f1" .. "f12", "enter", "tab", "backspace",
  "escape", "space", and the keypad `KEYPAD`: "kp_0" .. "kp_9", "kp_decimal",
  "kp_divide", "kp_multiply", "kp_subtract", "kp_add", "kp_enter", "kp_equal".

Mouse values: `button` one of `BUTTONS`: "left", "middle", "right", "wheel_up",
"wheel_down", "wheel_left", "wheel_right", or `None` (motion with no button held);
`kind` one of `KINDS`: "press", "release", "move" (a move with a button is a drag; a
wheel step is a "press").

## Keys, legacy (`modes.kitty` has neither 1 nor 8)

Named keys (CSI is `ESC [`, SS3 is `ESC O`); "m" means the modifier number, used when
any modifier is held (m > 1):

| key | plain | `cursor_keys` | with modifiers |
| --- | --- | --- | --- |
| up / down / right / left | `CSI A` / `B` / `C` / `D` | `SS3 A` .. `D` | `CSI 1;m A` .. `D` |
| home / end | `CSI H` / `CSI F` | `SS3 H` / `SS3 F` | `CSI 1;m H` / `F` |
| insert / delete | `CSI 2~` / `CSI 3~` | same | `CSI 2;m~` / `CSI 3;m~` |
| page_up / page_down | `CSI 5~` / `CSI 6~` | same | `CSI 5;m~` / `CSI 6;m~` |
| f1 .. f4 | `SS3 P` `Q` `R` `S` | same | `CSI 1;m P` .. `S` |
| f5 .. f12 | `CSI 15~` `17~` `18~` `19~` `20~` `21~` `23~` `24~` | same | `CSI 15;m~` .. |

The rest, where modifiers other than those named are ignored and "alt" (where it
counts) puts ESC before the bytes:
- enter `\\r`; tab `\\t`, with shift `CSI Z`; backspace `\\x7f`, with ctrl `\\x08`;
  escape `\\x1b`; space ` `, with ctrl `\\x00`. Alt: `\\x1b\\r`, `\\x1b\\t`
  (`\\x1b\\x1b[Z` with shift), `\\x1b\\x7f`, `\\x1b\\x1b`, `\\x1b `.
- a character key: with ctrl, by its name: a letter (either case) gives 0x01..0x1A,
  "@" and "2" give 0x00, "[" and "3" 0x1B, "\\\\" and "4" 0x1C, "]" and "5" 0x1D, "^" and
  "6" 0x1E, "_", "/" and "7" 0x1F, "?" and "8" 0x7F; any other character ignores ctrl.
  Without ctrl (or ctrl ignored): the UTF-8 of `text` when it is not empty, else of
  `name` (upper-cased when "shift" is held). Alt puts ESC first; super, hyper, meta
  are ignored.
- keypad keys ignore every modifier: with `keypad` off, their characters ("0".."9",
  ".", "/", "*", "-", "+", `\\r` for kp_enter, "="); with `keypad` on, `SS3 p` .. `y`
  for kp_0 .. kp_9, `SS3 n` decimal, `SS3 o` divide, `SS3 j` multiply, `SS3 m`
  subtract, `SS3 k` add, `SS3 M` enter, `SS3 X` equal.

## Keys, kitty (`modes.kitty` has 1 or 8)

The key code: a character key's `ord(name)`, an ASCII upper-case letter lowered
first ("A" is 97); space 32, enter 13, tab 9, backspace 127, escape 27; kp_0 .. kp_9
57399 .. 57408, kp_decimal 57409, kp_divide 57410, kp_multiply 57411, kp_subtract
57412, kp_add 57413, kp_enter 57414, kp_equal 57415. The CSI u form is
`CSI code[:alternate][;m[;text]] u`: ";m" only when m > 1 or a text field follows (an
empty modifier field then: `CSI 97;;97u`).

With 1 (disambiguate) and not 8:
- escape: always CSI u (`CSI 27u`, `CSI 27;m u`).
- character keys and space: with no modifier, or only shift, as legacy (their text);
  with any of alt, ctrl, super, hyper, meta: CSI u (`CSI 97;5u` for ctrl+a).
- enter, tab, backspace: with no modifier as legacy (`\\r`, `\\t`, `\\x7f`); with any:
  CSI u (`CSI 13;2u` shift+enter, `CSI 9;2u` shift+tab).
- keypad keys: always CSI u.
- the other named keys: as legacy (`cursor_keys` still applies), except f3, which is
  `CSI 13~` (`CSI 13;m~`), not SS3 R / CSI 1;m R (kitty's change: CSI R is a cursor
  position report).

With 8 (all keys as escapes): every character key, space, enter, tab, backspace,
escape and keypad key is CSI u, modifiers or not (`CSI 97u` for "a"); the other named
keys as with 1, but always in CSI form (`CSI A`, `CSI H`, `CSI P`, never SS3, whatever
`cursor_keys` says).

In CSI u forms only: with 4, when "shift" is held and `text` is one character whose
code differs from the key code, the alternate is that character's code
(`CSI 97:65;2u` for shift+a with text "A"). With 16 and 8, when `text` is not empty,
the text field is its code points joined by ":" (`CSI 97;;97u`). 2 (event types)
changes nothing: every Key is a press, and a press is the default type.

## Mouse

What each tracking mode reports (anything else encodes to `b""`):
- 0: nothing;
- 9: presses only, without modifier bits;
- 1000: presses and releases (a wheel button has no release: its "release" is `b""`);
- 1002: also "move" with a button held;
- 1003: also "move" with `button` None.

The button code `cb`: left 0, middle 1, right 2, wheel_up 64, wheel_down 65,
wheel_left 66, wheel_right 67; a "move" adds 32 (with no button: 35); modifiers add
shift 4, alt 8, ctrl 16 (super, hyper, meta are not encodable and ignored).

- SGR (`mouse_sgr`): `CSI < cb ; x+1 ; y+1 M` for a press or a move, final `m` for a
  release (cb as for the press). No coordinate limit.
- X10 (legacy): `CSI M` then the bytes `32+cb`, `32+x+1`, `32+y+1`; a release has
  `cb = 3` plus its modifier bits (the button is not said). When `x` or `y` is over
  222 (a byte over 255), the event encodes to `b""`.

## Paste and focus

- Paste: with `paste`, `CSI 200~` + the text + `CSI 201~`, where every
  `"\\x1b[201~"` is first removed from the text, repeatedly until none is left (a paste
  cannot end the bracket early); without, the text alone. Text as
  `text.encode("utf-8", "replace")`.
- Focus: with `focus`, `CSI I` (focused) or `CSI O`; without, `b""`.

Inputs: `event` (above), `modes` a `Modes`. Outputs: {Bytes}, `bytes` (possibly
empty). Errors: `TypeError` when `modes` is not a `Modes`, when the event's class name
is none of the five, when an attribute it reads is missing or of the wrong type (`mods`
a `str` or not iterable, a mod not a `str`, `x` / `y` not an `int`, a `bool` included);
`ValueError` for an unknown key name, modifier, button or kind, a negative `x` or
`y`, a "move" with a wheel button, or a "press" / "release" with `button` None.
Effects: none.

Usage:
    from cure.interact.vt.encode import encode, Modes
    # Key, Mouse, Paste, Focus: Input's event classes (or any classes of those names)
    encode(Key("up", frozenset(), ""), Modes())                       # b"\\x1b[A"
    encode(Key("up", frozenset(), ""), Modes(cursor_keys=True))       # b"\\x1bOA"
    encode(Key("up", frozenset({"ctrl"}), ""), Modes())               # b"\\x1b[1;5A"
    encode(Key("f5", frozenset({"shift"}), ""), Modes())              # b"\\x1b[15;2~"
    encode(Key("a", frozenset({"ctrl"}), ""), Modes())                # b"\\x01"
    encode(Key("a", frozenset({"alt"}), "a"), Modes())                # b"\\x1ba"
    encode(Key("a", frozenset({"ctrl"}), ""), Modes(kitty=1))         # b"\\x1b[97;5u"
    encode(Key("escape", frozenset(), ""), Modes(kitty=1))            # b"\\x1b[27u"
    encode(Key("a", frozenset({"shift"}), "A"), Modes(kitty=12))      # b"\\x1b[97:65;2u"
    encode(Mouse("left", "press", 4, 2, frozenset()), Modes(mouse=1000, mouse_sgr=True))
    # b"\\x1b[<0;5;3M"
    encode(Mouse("left", "release", 0, 0, frozenset()), Modes(mouse=1000))   # b"\\x1b[M#!!"
    encode(Mouse(None, "move", 0, 0, frozenset()), Modes(mouse=1002))  # b""
    encode(Paste("hi"), Modes(paste=True))                            # b"\\x1b[200~hi\\x1b[201~"
    encode(Focus(True), Modes())                                      # b""
"""

from dataclasses import dataclass

MODS = frozenset({"shift", "alt", "ctrl", "super", "hyper", "meta"})

KEYPAD = frozenset({
    "kp_0", "kp_1", "kp_2", "kp_3", "kp_4", "kp_5", "kp_6", "kp_7", "kp_8", "kp_9",
    "kp_decimal", "kp_divide", "kp_multiply", "kp_subtract", "kp_add", "kp_enter",
    "kp_equal",
})

KEYS = frozenset({
    "up", "down", "left", "right", "home", "end", "insert", "delete",
    "page_up", "page_down",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
    "enter", "tab", "backspace", "escape", "space",
}) | KEYPAD

BUTTONS = frozenset({"left", "middle", "right", "wheel_up", "wheel_down", "wheel_left", "wheel_right"})

KINDS = frozenset({"press", "release", "move"})

MOUSE_MODES = (0, 9, 1000, 1002, 1003)


@dataclass(frozen=True)
class Modes:
    """The input-side modes a target program has set (see the module)."""

    cursor_keys: bool = False
    keypad: bool = False
    kitty: int = 0
    mouse: int = 0
    mouse_sgr: bool = False
    paste: bool = False
    focus: bool = False

    def __post_init__(self) -> None:
        for name in ("cursor_keys", "keypad", "mouse_sgr", "paste", "focus"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"Modes.{name} must be a bool")
        for name in ("kitty", "mouse"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"Modes.{name} must be an int")
        if not 0 <= self.kitty <= 31:
            raise ValueError(f"Modes.kitty must be 0..31, got {self.kitty}")
        if self.mouse not in MOUSE_MODES:
            raise ValueError(f"Modes.mouse must be one of {MOUSE_MODES}, got {self.mouse}")


def encode(event: object, modes: Modes) -> bytes:
    """The bytes `event` is for a target whose modes are `modes` (see the module)."""
    if not isinstance(modes, Modes):
        raise TypeError(f"modes must be a Modes, got {type(modes).__name__}")
    encoder = _ENCODERS.get(type(event).__name__)
    if encoder is None:
        raise TypeError(f"not an input event: {type(event).__name__}")
    return encoder(event, modes)


# -- reading events

_MOD_BITS = {"shift": 1, "alt": 2, "ctrl": 4, "super": 8, "hyper": 16, "meta": 32}
_SHIFT, _ALT, _CTRL = 1, 2, 4


def _attr(event: object, name: str) -> object:
    """The event's attribute `name`; `TypeError` when it has none."""
    try:
        return getattr(event, name)
    except AttributeError:
        raise TypeError(f"{type(event).__name__} has no attribute {name!r}") from None


def _str(event: object, name: str) -> str:
    value = _attr(event, name)
    if not isinstance(value, str):
        raise TypeError(f"{type(event).__name__}.{name} must be a str")
    return value


def _int(event: object, name: str) -> int:
    value = _attr(event, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{type(event).__name__}.{name} must be an int")
    return value


def _bits(event: object) -> int:
    """The modifier bits of the event's `mods` (shift 1 .. meta 32)."""
    mods = _attr(event, "mods")
    if isinstance(mods, str):
        raise TypeError("mods must be an iterable of names, not a str")
    try:
        names = list(mods)
    except TypeError:
        raise TypeError(f"mods must be iterable, got {type(mods).__name__}") from None
    bits = 0
    for name in names:
        if not isinstance(name, str):
            raise TypeError(f"a modifier must be a str, got {type(name).__name__}")
        if name not in _MOD_BITS:
            raise ValueError(f"unknown modifier {name!r}")
        bits |= _MOD_BITS[name]
    return bits


def _csi(body: str) -> bytes:
    return b"\x1b[" + body.encode()


def _ss3(final: str) -> bytes:
    return b"\x1bO" + final.encode()


# -- keys

_CURSOR = {"up": "A", "down": "B", "right": "C", "left": "D", "home": "H", "end": "F"}
_FUNCTION = {"f1": "P", "f2": "Q", "f3": "R", "f4": "S"}
_TILDE = {"insert": 2, "delete": 3, "page_up": 5, "page_down": 6, "f5": 15, "f6": 17,
          "f7": 18, "f8": 19, "f9": 20, "f10": 21, "f11": 23, "f12": 24}
_KEYPAD_TEXT = {f"kp_{i}": str(i) for i in range(10)} | {
    "kp_decimal": ".", "kp_divide": "/", "kp_multiply": "*", "kp_subtract": "-",
    "kp_add": "+", "kp_enter": "\r", "kp_equal": "="}
_KEYPAD_APP = {f"kp_{i}": chr(ord("p") + i) for i in range(10)} | {
    "kp_decimal": "n", "kp_divide": "o", "kp_multiply": "j", "kp_subtract": "m",
    "kp_add": "k", "kp_enter": "M", "kp_equal": "X"}
_KITTY_CODES = {"space": 32, "enter": 13, "tab": 9, "backspace": 127, "escape": 27} | {
    f"kp_{i}": 57399 + i for i in range(10)} | {
    "kp_decimal": 57409, "kp_divide": 57410, "kp_multiply": 57411, "kp_subtract": 57412,
    "kp_add": 57413, "kp_enter": 57414, "kp_equal": 57415}
_CTRL_CODES = {"@": 0, "2": 0, "[": 0x1B, "3": 0x1B, "\\": 0x1C, "4": 0x1C, "]": 0x1D,
               "5": 0x1D, "^": 0x1E, "6": 0x1E, "_": 0x1F, "/": 0x1F, "7": 0x1F, "?": 0x7F,
               "8": 0x7F}
_ASCII_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _key(event: object, modes: Modes) -> bytes:
    name = _str(event, "name")
    bits = _bits(event)
    text = _str(event, "text")
    if name not in KEYS and not _is_character(name):
        raise ValueError(f"unknown key name {name!r}")
    if modes.kitty & 9:
        return _kitty_key(name, bits, text, modes)
    return _legacy_key(name, bits, text, modes)


def _is_character(name: str) -> bool:
    return len(name) == 1 and name != " " and name.isprintable()


def _legacy_key(name: str, bits: int, text: str, modes: Modes) -> bytes:
    if name in _CURSOR or name in _FUNCTION or name in _TILDE:
        return _legacy_named(name, bits, modes)
    if name in KEYPAD:
        if modes.keypad:
            return _ss3(_KEYPAD_APP[name])
        return _KEYPAD_TEXT[name].encode()
    alt = b"\x1b" if bits & _ALT else b""
    if name == "enter":
        return alt + b"\r"
    if name == "tab":
        return alt + (b"\x1b[Z" if bits & _SHIFT else b"\t")
    if name == "backspace":
        return alt + (b"\x08" if bits & _CTRL else b"\x7f")
    if name == "escape":
        return alt + b"\x1b"
    if name == "space":
        return alt + (b"\x00" if bits & _CTRL else b" ")
    return alt + _legacy_character(name, bits, text)


def _legacy_character(name: str, bits: int, text: str) -> bytes:
    if bits & _CTRL:
        if name in _ASCII_LETTERS:
            return bytes([ord(name.lower()) - 0x60])
        if name in _CTRL_CODES:
            return bytes([_CTRL_CODES[name]])
    if text:
        return text.encode("utf-8", "replace")
    return (name.upper() if bits & _SHIFT else name).encode("utf-8", "replace")


def _legacy_named(name: str, bits: int, modes: Modes, *, csi_only: bool = False,
                  kitty: bool = False) -> bytes:
    """Arrows, Home / End, the tilde keys and F1..F4, by the legacy table.

    `kitty`: F3 is `CSI 13~`; `csi_only`: never SS3 (kitty's all-keys flag)."""
    m = 1 + bits
    if kitty and name == "f3":
        return _csi("13~" if m == 1 else f"13;{m}~")
    if name in _TILDE:
        n = _TILDE[name]
        return _csi(f"{n}~" if m == 1 else f"{n};{m}~")
    final = _CURSOR.get(name) or _FUNCTION[name]
    if m > 1:
        return _csi(f"1;{m}{final}")
    if csi_only:
        return _csi(final)
    if name in _FUNCTION or modes.cursor_keys:
        return _ss3(final)
    return _csi(final)


def _kitty_key(name: str, bits: int, text: str, modes: Modes) -> bytes:
    flags = modes.kitty
    all_keys = bool(flags & 8)
    if name in _CURSOR or name in _FUNCTION or name in _TILDE:
        return _legacy_named(name, bits, modes, csi_only=all_keys, kitty=True)
    if not all_keys:
        if name in ("enter", "tab", "backspace") and not bits:
            return _legacy_key(name, bits, text, modes)
        if (name == "space" or _is_character(name)) and not bits & ~_SHIFT:
            return _legacy_key(name, bits, text, modes)
    if name in _KITTY_CODES:
        code = _KITTY_CODES[name]
    else:
        code = ord(name.lower()) if name in _ASCII_LETTERS else ord(name)
    alternate = None
    if flags & 4 and bits & _SHIFT and len(text) == 1 and ord(text) != code:
        alternate = ord(text)
    field = ":".join(str(ord(c)) for c in text) if flags & 16 and all_keys and text else ""
    return _csi_u(code, 1 + bits, alternate, field)


def _csi_u(code: int, m: int, alternate: "int | None", field: str) -> bytes:
    body = str(code) if alternate is None else f"{code}:{alternate}"
    if m > 1 or field:
        body += ";" + (str(m) if m > 1 else "")
    if field:
        body += ";" + field
    return _csi(body + "u")


# -- mouse

_BUTTON_CODES = {"left": 0, "middle": 1, "right": 2, "wheel_up": 64, "wheel_down": 65,
                 "wheel_left": 66, "wheel_right": 67}
_WHEELS = frozenset({"wheel_up", "wheel_down", "wheel_left", "wheel_right"})
_X10_LIMIT = 222


def _mouse(event: object, modes: Modes) -> bytes:
    button = _attr(event, "button")
    kind = _attr(event, "kind")
    x, y = _int(event, "x"), _int(event, "y")
    bits = _bits(event)
    if button is not None and button not in BUTTONS:
        raise ValueError(f"unknown button {button!r}")
    if kind not in KINDS:
        raise ValueError(f"unknown mouse kind {kind!r}")
    if x < 0 or y < 0:
        raise ValueError(f"negative mouse position ({x}, {y})")
    if kind == "move" and button in _WHEELS:
        raise ValueError("a move with a wheel button")
    if kind != "move" and button is None:
        raise ValueError(f"a {kind} with no button")
    if not _reported(modes.mouse, button, kind):
        return b""
    mod_bits = 0 if modes.mouse == 9 else (
        (4 if bits & _SHIFT else 0) | (8 if bits & _ALT else 0) | (16 if bits & _CTRL else 0))
    if kind == "move":
        cb = (3 if button is None else _BUTTON_CODES[button]) + 32
    else:
        cb = _BUTTON_CODES[button]
    if modes.mouse_sgr:
        final = "m" if kind == "release" else "M"
        return _csi(f"<{cb + mod_bits};{x + 1};{y + 1}{final}")
    if kind == "release":
        cb = 3
    if x > _X10_LIMIT or y > _X10_LIMIT:
        return b""
    return b"\x1b[M" + bytes((32 + cb + mod_bits, 33 + x, 33 + y))


def _reported(mode: int, button: "str | None", kind: str) -> bool:
    """Whether tracking mode `mode` reports this event at all."""
    if mode == 0:
        return False
    if kind == "press":
        return True
    if mode == 9:
        return False
    if kind == "release":
        return button not in _WHEELS
    if button is not None:
        return mode in (1002, 1003)
    return mode == 1003


# -- paste, focus, resize

_PASTE_END = "\x1b[201~"


def _paste(event: object, modes: Modes) -> bytes:
    text = _str(event, "text")
    if not modes.paste:
        return text.encode("utf-8", "replace")
    while _PASTE_END in text:
        text = text.replace(_PASTE_END, "")
    return b"\x1b[200~" + text.encode("utf-8", "replace") + b"\x1b[201~"


def _focus(event: object, modes: Modes) -> bytes:
    focused = _attr(event, "focused")
    if type(focused) is not bool:
        raise TypeError("Focus.focused must be a bool")
    if not modes.focus:
        return b""
    return b"\x1b[I" if focused else b"\x1b[O"


def _resize(event: object, modes: Modes) -> bytes:
    return b""


_ENCODERS = {"Key": _key, "Mouse": _mouse, "Paste": _paste, "Focus": _focus, "Resize": _resize}
