"""[Events]: Key(name, mods, text), Mouse(button, kind, x, y, mods), Paste, Focus, Resize.

Kind: service (the event values a [Decoder] gives out, and the one string form of a
key that [Bindings] matches, writes in its hints and parses back); pure.

The values are plain data, frozen dataclasses checked on construction (equal by value,
hashable). Their class names, fields and values are exactly the ones Vt's [Encode]
reads by duck typing (`type(event).__name__` and the attributes below), so construct
can decode the outer terminal's input and write each event again for a pane:
`encode(event, modes)` accepts every `Key`, `Mouse`, `Paste`, `Focus` and `Resize` this
module lets you build. The name sets come from Encode itself (`KEYS`, `KEYPAD`, `MODS`,
`BUTTONS`, `KINDS` in `cure.interact.vt.encode`), never copied.

## The events

- `Key(name, mods=frozenset(), text="", event="press")`: a key.
  - `name`: a named key of `KEYS` ("up", "down", "left", "right", "home", "end",
    "insert", "delete", "page_up", "page_down", "f1" .. "f12", "enter", "tab",
    "backspace", "escape", "space", "kp_0" .. "kp_9", "kp_decimal", "kp_divide",
    "kp_multiply", "kp_subtract", "kp_add", "kp_enter", "kp_equal"), or a character
    key: exactly one code point, `str.isprintable()`, not " " (the space bar is
    "space"), e.g. "a", "A", "é", "1", "/", "\\ufffd".
  - `mods`: the modifiers held, any iterable of names of `MODS` ("shift", "alt",
    "ctrl", "super", "hyper", "meta"), not a `str`; stored as a `frozenset`
    (`Key("a", ["ctrl"]).mods == frozenset({"ctrl"})`).
  - `text`: what the key inserts, a `str` (may be ""); editors read `text`, bindings
    read `name` and `mods`. The decoder gives the canonical text (`text_of`) unless the
    terminal said otherwise (kitty's shifted key or associated text).
  - `event`: one of `KEY_EVENTS`, "press", "repeat", "release". Only a terminal the app
    asked for kitty's event types (flag 2) sends "repeat" and "release"; every other
    key is a "press". [Encode] does not read `event`: it writes every Key as a press,
    so a forwarder drops releases itself.
- `Mouse(button, kind, x, y, mods=frozenset())`: a mouse report.
  - `button`: one of `BUTTONS` ("left", "middle", "right", "wheel_up", "wheel_down",
    "wheel_left", "wheel_right") or `None` (motion with no button held).
  - `kind`: one of `KINDS`: "press", "release", "move" (a "move" with a button is a
    drag; a wheel step is a "press" and has no release).
  - `x`, `y`: `int` >= 0, 0-based cells (the terminal's 1-based column and row less 1).
  - `mods`: as `Key.mods`; a terminal reports only "shift", "alt" and "ctrl".
  - A "move" with a wheel button, or a "press" / "release" with `button` None, is a
    `ValueError` (Encode's rule).
- `Paste(text)`: a whole bracketed paste, `text` a `str`, every character kept
  (controls and ESC included): pasted text is text, never keys.
- `Focus(focused)`: the terminal gained (`True`) or lost (`False`) focus. `focused`: a
  `bool`.
- `Resize(width, height)`: the terminal's new size in cells, `int`s >= 0. A terminal's
  bytes carry it only with in-band resize reports (mode 2048, which the decoder turns
  into a `Resize`); otherwise the app makes one itself from its size poll or SIGWINCH
  (Term's `size`) and handles it like any other event.
- `Reply(kind, final="", params=(), private="", intermediates="", data=b"")`: a
  terminal's answer to a query, kept apart from the person's input in the same ordered
  stream (Term's probe picks them out; keys typed during a probe are not lost). `kind`:
  one of `REPLIES`:
  - "da1": `CSI ? ... c`; "da2": `CSI > ... c`;
  - "cpr": a cursor position report, `CSI row ; col R` or `CSI ? row ; col R`
    (DECXCPR); see [Decoder] for `CSI 1 ; m R` (also Shift..F3);
  - "status": `CSI n` with no private marker (DSR, `CSI 0 n`);
  - "decrpm": `CSI ? mode ; value $ y` or `CSI mode ; value $ y`;
  - "kitty": `CSI ? flags u`, the kitty keyboard flags in force;
  - "window": `CSI ... t`, an XTWINOPS report other than mode 2048's resize;
  - "osc": any OSC (colour replies `OSC 10 ; rgb:...`, `OSC 4 ; n ; ...`, OSC 52 ...);
  - "dcs": a whole device control string (XTVERSION `DCS > | ... ST`, XTGETTCAP
    `DCS 1 + r ... ST`, DECRQSS `DCS 1 $ r ... ST`).
  The other fields are the sequence's own, as Vt's actions give them: for a CSI reply
  `final`, `params`, `private`, `intermediates` from the `Csi` (`data` is b""); for
  "osc", `data` is the `Osc`'s data (the other fields empty); for "dcs", the `Hook`'s
  four fields and `data` the joined `Put`s.
- `Unknown(action)`: one Vt action (`Print`, `Execute`, `Csi`, `Esc`, `Ss3`,
  `LegacyMouse`, `Put`, `Unhook` ...) that is no key, mouse report, paste, focus change,
  resize or reply. Given, not dropped, so an app may log what its terminal sends; the
  Router ignores it. Never encodable (Encode raises `TypeError` for it).

`Event` is the union of the seven classes; `EVENTS` the tuple of them, in the order
above. `Key`, `Mouse`, `Paste`, `Focus` and `Resize` are the five Encode reads.

Construction errors: `TypeError` when a field has the wrong type (`name`, `text`,
`kind`, `event` not a `str`; `mods` a `str`, not iterable, or holding a non-`str`; `x`,
`y`, `width`, `height` not an `int`, a `bool` included; `focused` not a `bool`; `Paste`
text not a `str`; `Reply` fields not of the types above; `Unknown.action` not one of
Vt's `ACTIONS`); `ValueError` for an unknown key name, modifier, key event, button,
kind or reply kind, a negative coordinate or size, or a mouse combination Encode
refuses.

## The string form of a key (a stroke)

Bindings write keys as strokes: modifiers, then the key's name, joined by "+":
"q", "ctrl+s", "alt+x", "f5", "shift+tab", "ctrl+alt+delete", "space", "A", "?",
"ctrl++" (Ctrl and the "+" key). A chord is strokes separated by spaces
("ctrl+x ctrl+s", "g g"); that is [Bindings]' business, a stroke never holds a space.

The normal form (`normal`), so that a key matches one stroke however the terminal sent
it. A legacy terminal sends Shift+A as the character "A"; kitty sends the key "a" with
Shift held; Vt's [Encode] writes a kitty key from the lower-case letter and the mods.
So an ASCII letter is kept lower-case with "shift", and any other shifted character is
folded into the character it typed:
1. a character key that is an ASCII letter: its lower case, with "shift" added when the
   name was upper case (("A", {}) -> ("a", {shift}); ("A", {ctrl}) -> ("a", {ctrl,
   shift}); ("a", {shift}) is kept);
2. else a character key with "shift" held whose `text` is one character other than
   `name` becomes that character, shift dropped (kitty's ("1", {shift}, "!") -> ("!",
   {}); ("é", {shift}, "É") -> ("É", {}));
3. anything else is kept (named keys keep shift: "shift+tab", "shift+up",
   "shift+space"; a shifted non-letter with no other text keeps it: "shift+1").
So "A", "shift+a" and kitty's shift+a are one stroke, "shift+a", and "ctrl+A" is
"ctrl+shift+a" (which a legacy terminal sends as Ctrl+A: it cannot be told apart).
Every `Key` a [Decoder] gives is in normal form (`normal(k) == k`).

- `normal(key) -> Key`: the key with `name` and `mods` in normal form (rules above),
  `text` and `event` unchanged. `normal(normal(k)) == normal(k)`. `TypeError` when
  `key` is not a `Key`.
- `stroke(key) -> str`: the canonical stroke of `normal(key)`: its mods in the order
  `MOD_ORDER` ("ctrl", "alt", "shift", "super", "hyper", "meta"), each followed by "+",
  then its name (a named key's lower-case name, a character key's character).
  `event` and `text` play no part. `TypeError` when `key` is not a `Key`.
- `key(text) -> Key`: a stroke parsed, as a normal-form `Key` with the canonical text
  (`text_of`) and event "press". Grammar: `mod+mod+...+name`. Modifiers are
  case-insensitive names of `MODS` ("Ctrl+s" is "ctrl+s"), each at most once. The name
  is a named key, case-insensitive ("F5", "Enter", "PAGE_UP"), or one of the aliases
  `ALIASES` ("esc" escape, "return" enter, "pgup" page_up, "pgdn" page_down, "del"
  delete, "ins" insert), or a character key, case-sensitive ("a" and "A" differ). The
  name "+" is written last: "+" alone, or "ctrl++". `TypeError` when `text` is not a
  `str`; `ValueError` when it is empty, has an empty part ("ctrl+", "+a",
  "ctrl++a"), an unknown or repeated modifier, an unknown name, holds any whitespace
  (" " included: the space bar is "space"), or names a character that is not
  printable.
  Law: `stroke(key(s))` is the canonical spelling of `s`, and `key(stroke(k))` has the
  `name` and `mods` of `normal(k)`; for a canonical `s`, `stroke(key(s)) == s`.
- `text_of(name, mods) -> str`: the canonical text of a key: "" when any of "ctrl",
  "alt", "super", "hyper", "meta" is held; else " " for "space"; a keypad key's
  character ("0".."9" for kp_0..kp_9, "." decimal, "/" divide, "*" multiply, "-"
  subtract, "+" add, "=" equal; "" for kp_enter); "" for every other named key; for a
  character key, its upper case when "shift" is held and it is an ASCII letter, else
  the character itself. `TypeError` / `ValueError` as `Key` gives them for the name and
  mods.

[Decoder] builds its keys through these public names only (`[Decoder] -> [Events] :
normal`, and `text_of`): a key with the canonical text is
`normal(Key(name, mods, text_of(name, mods), event))`, one given its text
`normal(Key(name, mods, text, event))`. For every known name and valid mods that is
exactly the `Key` the module's private `_normal` / `_text` would build (same name,
mods, text, event; `normal` returns the key itself when it is already normal). The
helpers `_normal(name, mods, text)` and `_text(name, mods)` work on fields already
checked and are Events' own: no other module imports them.

Inputs: strings, names, ints as above. Outputs: event values, `str`. Errors: as stated.
Effects: none.

Usage:
    from cure.interact.input.events import Key, Mouse, Paste, Focus, key, stroke, normal
    key("ctrl+s")              # Key("s", frozenset({"ctrl"}), "")
    key("shift+a")             # Key("a", frozenset({"shift"}), "A")
    key("A")                   # the same Key
    key("Shift+Tab")           # Key("tab", frozenset({"shift"}), "")
    key("space")               # Key("space", frozenset(), " ")
    key("ctrl++")              # Key("+", frozenset({"ctrl"}), "")
    stroke(Key("A", text="A"))                 # "shift+a"
    stroke(Key("1", {"shift"}, "!"))           # "!"
    stroke(Key("s", {"alt", "ctrl"}))          # "ctrl+alt+s"
    stroke(Key("up", {"shift"}))               # "shift+up"
    normal(Key("A", {"ctrl"}))                 # Key("a", frozenset({"ctrl", "shift"}), "")
    text_of("a", {"shift"})                    # "A"
    Mouse("left", "press", 4, 2)               # x=4, y=2, mods=frozenset()
    Mouse(None, "press", 0, 0)                 # ValueError: a press with no button
"""

from collections.abc import Hashable, Iterable
from dataclasses import dataclass, field

from cure.interact.vt.encode import BUTTONS, KEYPAD, KEYS, KINDS, MODS
from cure.interact.vt.performer import ACTIONS

KEY_EVENTS = ("press", "repeat", "release")

MOD_ORDER = ("ctrl", "alt", "shift", "super", "hyper", "meta")

ALIASES = {"esc": "escape", "return": "enter", "pgup": "page_up", "pgdn": "page_down",
           "del": "delete", "ins": "insert"}

REPLIES = ("da1", "da2", "cpr", "status", "decrpm", "kitty", "window", "osc", "dcs")

_WHEELS = frozenset({"wheel_up", "wheel_down", "wheel_left", "wheel_right"})


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _mods(value: object) -> frozenset:
    """`mods` as a frozenset of MODS names; TypeError / ValueError as the module says."""
    if isinstance(value, str):
        raise TypeError("mods must be an iterable of names, not a str")
    try:
        names = frozenset(value)
    except TypeError:
        raise TypeError(f"mods must be an iterable of names, got {type(value).__name__}") from None
    for name in names:
        if not isinstance(name, str):
            raise TypeError(f"a modifier must be a str, got {type(name).__name__}")
        if name not in MODS:
            raise ValueError(f"unknown modifier {name!r}")
    return names


def _is_character(name: str) -> bool:
    return len(name) == 1 and name != " " and name.isprintable()


@dataclass(frozen=True)
class Key:
    """A key: its name, the modifiers held, the text it inserts, press / repeat / release."""

    name: str
    mods: frozenset = field(default_factory=frozenset)
    text: str = ""
    event: str = "press"

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise TypeError(f"Key.name must be a str, got {type(self.name).__name__}")
        if self.name not in KEYS and not _is_character(self.name):
            raise ValueError(f"unknown key name {self.name!r}")
        object.__setattr__(self, "mods", _mods(self.mods))
        if not isinstance(self.text, str):
            raise TypeError(f"Key.text must be a str, got {type(self.text).__name__}")
        if not isinstance(self.event, str):
            raise TypeError(f"Key.event must be a str, got {type(self.event).__name__}")
        if self.event not in KEY_EVENTS:
            raise ValueError(f"unknown key event {self.event!r}")


@dataclass(frozen=True)
class Mouse:
    """A mouse report: button (or None for motion), kind, 0-based cell x / y, mods."""

    button: "str | None"
    kind: str
    x: int
    y: int
    mods: frozenset = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.button is not None and not isinstance(self.button, str):
            raise TypeError("Mouse.button must be a str or None")
        if not isinstance(self.kind, str):
            raise TypeError("Mouse.kind must be a str")
        if not _is_int(self.x) or not _is_int(self.y):
            raise TypeError("Mouse.x and Mouse.y must be ints")
        object.__setattr__(self, "mods", _mods(self.mods))
        if self.button is not None and self.button not in BUTTONS:
            raise ValueError(f"unknown button {self.button!r}")
        if self.kind not in KINDS:
            raise ValueError(f"unknown mouse kind {self.kind!r}")
        if self.x < 0 or self.y < 0:
            raise ValueError(f"negative mouse position ({self.x}, {self.y})")
        if self.kind == "move" and self.button in _WHEELS:
            raise ValueError("a move with a wheel button")
        if self.kind != "move" and self.button is None:
            raise ValueError(f"a {self.kind} with no button")


@dataclass(frozen=True)
class Paste:
    """A whole bracketed paste: text, never keys."""

    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("Paste.text must be a str")


@dataclass(frozen=True)
class Focus:
    """The terminal gained (True) or lost (False) focus."""

    focused: bool

    def __post_init__(self) -> None:
        if type(self.focused) is not bool:
            raise TypeError("Focus.focused must be a bool")


@dataclass(frozen=True)
class Resize:
    """The terminal's new size in cells."""

    width: int
    height: int

    def __post_init__(self) -> None:
        if not _is_int(self.width) or not _is_int(self.height):
            raise TypeError("Resize.width and Resize.height must be ints")
        if self.width < 0 or self.height < 0:
            raise ValueError(f"negative size ({self.width}, {self.height})")


@dataclass(frozen=True)
class Reply:
    """A terminal's answer to a query (see the module for each kind's fields)."""

    kind: str
    final: str = ""
    params: "tuple[tuple[int | None, ...], ...]" = ()
    private: str = ""
    intermediates: str = ""
    data: bytes = b""

    def __post_init__(self) -> None:
        for name in ("kind", "final", "private", "intermediates"):
            if not isinstance(getattr(self, name), str):
                raise TypeError(f"Reply.{name} must be a str")
        if not isinstance(self.params, tuple) or not all(isinstance(p, tuple) for p in self.params):
            raise TypeError("Reply.params must be a tuple of tuples")
        if not isinstance(self.data, bytes):
            raise TypeError("Reply.data must be bytes")
        if self.kind not in REPLIES:
            raise ValueError(f"unknown reply kind {self.kind!r}")


@dataclass(frozen=True)
class Unknown:
    """A Vt action that is no input event the decoder knows; given so an app may log it."""

    action: Hashable

    def __post_init__(self) -> None:
        if not isinstance(self.action, ACTIONS):
            raise TypeError(f"Unknown.action must be a Vt action, got {type(self.action).__name__}")


Event = Key | Mouse | Paste | Focus | Resize | Reply | Unknown
EVENTS = (Key, Mouse, Paste, Focus, Resize, Reply, Unknown)


_ASCII_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
_NO_TEXT_MODS = frozenset({"ctrl", "alt", "super", "hyper", "meta"})
_KEYPAD_TEXT = {f"kp_{i}": str(i) for i in range(10)} | {
    "kp_decimal": ".", "kp_divide": "/", "kp_multiply": "*", "kp_subtract": "-",
    "kp_add": "+", "kp_equal": "=", "kp_enter": ""}
_SHIFT = frozenset({"shift"})


def _normal(name: str, mods: frozenset, text: str) -> "tuple[str, frozenset]":
    """The normal form's name and mods (rules 1..3), on checked fields."""
    if name in _ASCII_LETTERS:
        if name.isupper():
            return name.lower(), mods | _SHIFT
        return name, mods
    if len(name) == 1 and "shift" in mods and len(text) == 1 and text != name \
            and _is_character(text):
        mods = mods - _SHIFT
        if text in _ASCII_LETTERS and text.isupper():
            return text.lower(), mods | _SHIFT
        return text, mods
    return name, mods


def _text(name: str, mods: frozenset) -> str:
    """`text_of` on checked fields."""
    if mods and not mods.isdisjoint(_NO_TEXT_MODS):
        return ""
    if len(name) == 1:
        if name in _ASCII_LETTERS and "shift" in mods:
            return name.upper()
        return name
    if name == "space":
        return " "
    return _KEYPAD_TEXT.get(name, "")


def normal(key: Key) -> Key:
    """The key with Shift folded into a character key (see the module)."""
    if not isinstance(key, Key):
        raise TypeError(f"normal takes a Key, got {type(key).__name__}")
    name, mods = _normal(key.name, key.mods, key.text)
    if name == key.name and mods == key.mods:
        return key
    return Key(name, mods, key.text, key.event)


def stroke(key: Key) -> str:
    """The canonical stroke of a key, e.g. "ctrl+s" (see the module)."""
    if not isinstance(key, Key):
        raise TypeError(f"stroke takes a Key, got {type(key).__name__}")
    name, mods = _normal(key.name, key.mods, key.text)
    if not mods:
        return name
    return "".join(m + "+" for m in MOD_ORDER if m in mods) + name


def key(text: str) -> Key:
    """A stroke parsed into a normal-form Key with its canonical text (see the module)."""
    if not isinstance(text, str):
        raise TypeError(f"a stroke must be a str, got {type(text).__name__}")
    if not text:
        raise ValueError("an empty stroke")
    if any(c.isspace() for c in text):
        raise ValueError(f"a stroke holds no whitespace: {text!r}")
    if text == "+":
        parts, name = [], "+"
    elif text.endswith("++"):
        head = text[:-2]
        if not head:
            raise ValueError(f"an empty part in the stroke {text!r}")
        parts, name = head.split("+"), "+"
    else:
        parts = text.split("+")
        name = parts.pop()
    if not name or any(not p for p in parts):
        raise ValueError(f"an empty part in the stroke {text!r}")
    mods = set()
    for part in parts:
        mod = part.lower()
        if mod not in MODS:
            raise ValueError(f"unknown modifier {part!r} in the stroke {text!r}")
        if mod in mods:
            raise ValueError(f"the modifier {part!r} is repeated in the stroke {text!r}")
        mods.add(mod)
    if len(name) > 1:
        lower = name.lower()
        lower = ALIASES.get(lower, lower)
        if lower not in KEYS:
            raise ValueError(f"unknown key name {name!r} in the stroke {text!r}")
        name = lower
    elif not _is_character(name):
        raise ValueError(f"the character {name!r} is not printable")
    name, fmods = _normal(name, frozenset(mods), "")
    return Key(name, fmods, _text(name, fmods))


def text_of(name: str, mods: Iterable[str]) -> str:
    """The text a key inserts by default (see the module)."""
    k = Key(name, mods)
    return _text(k.name, k.mods)
