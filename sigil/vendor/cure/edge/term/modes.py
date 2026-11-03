"""[Modes]: the tty, opened and closed exactly; the app calls it from its own loop:
raw / cbreak, alt screen or inline, cursor, mouse 1000 / 1002 / 1003 / 1006, paste 2004,
focus 1004, kitty keys, synchronized output; every mode set is undone, on exit, crash,
signal or suspend.

Kind: service: a data class (what the app asks for), a pure planner (the exact pairs of
escapes it means at the {Caps} the probe found), the writes of a plan's set and undo
halves, and the termios save / set / restore. The Term handle drives these in its
`open`, `close` and `suspend` (see [Term]); used alone, they are the same pieces.

Data:
- `Modes(input="raw", screen="alt", mouse=None, paste=True, focus=False, kitty=1,
  probe=True)` ({Modes}), checked on construction:
  - `input`: `"raw"` (termios raw: no echo, no line editing, no signals from keys,
    Ctrl-C / Ctrl-Z arrive as bytes `\\x03` / `\\x1a`), `"cbreak"` (no echo, no line
    editing; `ISIG` stays, so Ctrl-C is `KeyboardInterrupt` and Ctrl-Z `SIGTSTP`), or
    `None` (termios untouched);
  - `screen`: `"alt"` (the alternate screen, the shell's screen given back on close)
    or `"inline"` (draw in the normal screen);
  - `mouse`: `None` (no reports), `"click"` (1000: presses, releases, wheel), `"drag"`
    (1002: and motion with a button down), `"move"` (1003: and all motion); always
    SGR-encoded (1006);
  - `paste`: `bool`, bracketed paste (2004: pasted text arrives as text, never keys);
  - `focus`: `bool`, focus in / out reports (1004);
  - `kitty`: `int` 0..31, the kitty keyboard flags pushed (1: disambiguate escape
    codes); 0 pushes nothing;
  - `probe`: `bool`, whether the Term handle's `open` runs [Probe] (else the env only).
- `Pair(name, on, off)`: one mode: `name` a `str`, `on` the `bytes` that set it, `off`
  the `bytes` that undo it.
- `Saved(fd, attrs)`: the termios state `enter` replaced: `fd` an `int`, `attrs` the
  `termios.tcgetattr(fd)` list as it was (copied: later changes to it do not leak in).

`plan(modes, caps) -> tuple[Pair, ...]` (pure): the pairs to set, in this order, each
present only under its condition (`E` is ESC):

  | name        | on               | off              | when                                 |
  |-------------|------------------|------------------|--------------------------------------|
  | `alt`       | `E[?1049h`       | `E[?1049l`       | `screen == "alt"`                    |
  | `cursor`    | `E[?25l`         | `E[?25h`         | always (Display shows it per frame)  |
  | `paste`     | `E[?2004h`       | `E[?2004l`       | `paste`                              |
  | `focus`     | `E[?1004h`       | `E[?1004l`       | `focus`                              |
  | `mouse`     | `E[?1000h` / `E[?1002h` / `E[?1003h` | the same number with `l` | `mouse` set and `caps.mouse` |
  | `mouse_sgr` | `E[?1006h`       | `E[?1006l`       | as `mouse`                           |
  | `kitty`     | `E[>{kitty}u`    | `E[<u`           | `kitty > 0` and `caps.keys == "kitty"` |
  | `sgr`       | `b""`            | `E[0m`           | always (no colour outlives the app)  |
  | `sync`      | `b""`            | `E[?2026l`       | `caps.sync` (a frame cut off mid-way leaves no 2026 set) |

  So the undo, the offs in reverse, starts by ending synchronized output and resetting
  the SGR pen, and ends by leaving the alternate screen. modifyOtherKeys and mode 2027
  are never set (the probe reads 2027 only). When the terminal cannot report the mouse
  in SGR form (`caps.mouse` false) no mouse mode is set at all.
`set(writer, pairs) -> None | Closed` ([Modes] -> (Terminal) : set({Modes})): one write
of `b"".join(p.on for p in pairs)` through `writer` (nothing when that is empty);
the writer's result.
`unset(writer, pairs) -> None | Closed`: one write of
`b"".join(p.off for p in reversed(pairs))` (nothing when empty); the writer's result.
`enter(fd, input) -> Saved | None`: `input` `None`, or `fd` `None`, or `fd` not a
terminal (`termios.error`): `None`, nothing changed. Else saves
`termios.tcgetattr(fd)`, builds the new attributes from a copy with
`tty.cfmakeraw` (`"raw"`) or `tty.cfmakecbreak` (`"cbreak"`), sets `VMIN` 1 and
`VTIME` 0, applies them with `termios.tcsetattr(fd, termios.TCSANOW, new)` (typed-ahead
input is kept) and returns the `Saved`.
`leave(saved) -> None`: `termios.tcsetattr(saved.fd, termios.TCSADRAIN, saved.attrs)`
(after the undo bytes have drained); `None` saved, or a `termios.error` / `OSError`
(the terminal is gone), does nothing. Never raises.

Invariant: paired — every mode cure sets has its undo, applied in reverse order, on
  every exit path: for each `Pair` in a plan, `off` undoes `on`; `unset` sends the offs
  of exactly the pairs `set` sent, last set first; `leave` restores exactly the termios
  state `enter` saved, after the escapes. The Term handle applies the undo (Osc undos,
  then `unset`, then `leave`) on `close()` (so on the app's normal exit and, through
  `with` / `finally`, on an exception or `KeyboardInterrupt`), on `suspend` (Ctrl-Z:
  before the process stops; the plan is set again on resume), on `SIGTERM` / `SIGHUP`
  when the app opted into signals (read returns the {Closed}, the app's `with` closes),
  and when `open` itself fails part-way (what was set is undone before the error
  leaves). Not covered, and stated: `SIGKILL`, `os._exit`, and `SIGTERM` / `SIGHUP` /
  `SIGTSTP` without signals opted in (their default actions end or stop the process).
  Proof shape: a Term over a pty, opened with every mode on: the bytes the master reads
  after `close()` (or after a `KeyboardInterrupt` inside `with`, or after `suspend`)
  are exactly `unset`'s, and `tcgetattr` of the slave equals what it was before `open`.

Inputs: `modes` a `Modes`; `caps` a Core {Caps} (any object with `mouse`, `keys`,
  `sync`); `writer` any object with `write(bytes) -> None | Closed` (the [Writer]);
  `pairs` a tuple of `Pair`; `fd` an `int` or `None`; `input` `"raw"`, `"cbreak"` or
  `None`; `saved` a `Saved` or `None`.
Outputs: `plan` a tuple of `Pair`; `set` / `unset` `None` or a {Closed}; `enter` a
  `Saved` or `None`; `leave` `None`.
Errors: `Modes(...)`: `TypeError` when `input`, `screen` or `mouse` is not a `str` (or
  `None` where allowed), `paste` / `focus` / `probe` is not a `bool`, or `kitty` is not
  an `int` (a `bool` is refused); `ValueError` when `input` is not `"raw"` / `"cbreak"`
  / `None`, `screen` not `"alt"` / `"inline"`, `mouse` not `None` / `"click"` /
  `"drag"` / `"move"`, or `kitty` outside 0..31. `plan`: `TypeError` when `modes` is
  not a `Modes`. `set` / `unset`: `TypeError` when a pair is not a `Pair`. `enter`:
  `ValueError` for an `input` other than the three. No `OSError` or `termios.error`
  escapes `enter` or `leave`.
Effects: `plan` none; `set` / `unset` one `writer.write` each; `enter`
  `termios.tcgetattr` / `tcsetattr` on `fd`; `leave` `termios.tcsetattr`.

Usage:
    from cure.core.caps import Caps
    from cure.edge.term.modes import Modes, plan, set, unset, enter, leave
    from cure.edge.term.writer import Writer
    p = plan(Modes(mouse="drag"), Caps(depth=256, mouse=True))
    [x.name for x in p]   # ["alt", "cursor", "paste", "mouse", "mouse_sgr", "sgr"]
    buf = bytearray()
    set(Writer(sink=buf), p)      # buf == b"\\x1b[?1049h\\x1b[?25l\\x1b[?2004h\\x1b[?1002h\\x1b[?1006h"
    buf.clear()
    unset(Writer(sink=buf), p)    # buf == b"\\x1b[0m\\x1b[?1006l\\x1b[?1002l\\x1b[?2004l\\x1b[?25h\\x1b[?1049l"
    import os
    master, slave = os.openpty()
    saved = enter(slave, "raw")   # Saved(slave, <the attrs before>)
    leave(saved)                  # tcgetattr(slave) == saved.attrs again
"""

import copy
import termios
import tty
from dataclasses import dataclass

from cure.closed import Closed

INPUTS = ("raw", "cbreak", None)
SCREENS = ("alt", "inline")
MICE = (None, "click", "drag", "move")


@dataclass(frozen=True)
class Modes:
    """{Modes}: the terminal modes the app asks for. Checked on construction."""

    input: "str | None" = "raw"
    screen: str = "alt"
    mouse: "str | None" = None
    paste: bool = True
    focus: bool = False
    kitty: int = 1
    probe: bool = True

    def __post_init__(self) -> None:
        _check_choice(self.input, INPUTS, "input")
        _check_choice(self.screen, SCREENS, "screen")
        _check_choice(self.mouse, MICE, "mouse")
        for name in ("paste", "focus", "probe"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a bool, got {type(getattr(self, name)).__name__}")
        if isinstance(self.kitty, bool) or not isinstance(self.kitty, int):
            raise TypeError(f"kitty must be an int, got {type(self.kitty).__name__}")
        if not 0 <= self.kitty <= 31:
            raise ValueError(f"kitty must be in 0..31, got {self.kitty}")


@dataclass(frozen=True)
class Pair:
    """One mode: the bytes that set it and the bytes that undo it."""

    name: str
    on: bytes
    off: bytes


@dataclass(frozen=True)
class Saved:
    """The termios state `enter` replaced on `fd`."""

    fd: int
    attrs: list


def plan(modes: Modes, caps) -> "tuple[Pair, ...]":
    """The pairs `modes` means at `caps`, in the order they are set (see the module)."""
    if not isinstance(modes, Modes):
        raise TypeError(f"expected a Modes, got {type(modes).__name__}")
    pairs = []
    if modes.screen == "alt":
        pairs.append(_dec("alt", 1049))
    pairs.append(_dec("cursor", 25, on=b"l", off=b"h"))
    if modes.paste:
        pairs.append(_dec("paste", 2004))
    if modes.focus:
        pairs.append(_dec("focus", 1004))
    if modes.mouse is not None and caps.mouse:
        pairs.append(_dec("mouse", _MOUSE[modes.mouse]))
        pairs.append(_dec("mouse_sgr", 1006))
    if modes.kitty > 0 and caps.keys == "kitty":
        pairs.append(Pair("kitty", f"\x1b[>{modes.kitty}u".encode(), b"\x1b[<u"))
    pairs.append(Pair("sgr", b"", b"\x1b[0m"))
    if caps.sync:
        pairs.append(Pair("sync", b"", b"\x1b[?2026l"))
    return tuple(pairs)


def set(writer, pairs: "tuple[Pair, ...]") -> "Closed | None":  # noqa: A001 (the flow's op name)
    """Write every pair's `on`, in order, as one write."""
    return _write(writer, [p.on for p in _pairs(pairs)])


def unset(writer, pairs: "tuple[Pair, ...]") -> "Closed | None":
    """Write every pair's `off`, last pair first, as one write."""
    return _write(writer, [p.off for p in reversed(_pairs(pairs))])


def enter(fd: "int | None", input: "str | None") -> "Saved | None":
    """Save the termios state of `fd` and set raw or cbreak; None when nothing changed."""
    if input not in INPUTS:
        raise ValueError(f"input must be one of {INPUTS}, got {input!r}")
    if input is None or fd is None:
        return None
    try:
        before = termios.tcgetattr(fd)
        new = copy.deepcopy(before)
        (tty.cfmakeraw if input == "raw" else tty.cfmakecbreak)(new)
        new[6][termios.VMIN] = 1
        new[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, new)
    except (termios.error, OSError):
        return None
    return Saved(fd, before)


def leave(saved: "Saved | None") -> None:
    """Restore the saved termios state (TCSADRAIN); never raises."""
    if saved is None:
        return None
    try:
        termios.tcsetattr(saved.fd, termios.TCSADRAIN, saved.attrs)
    except (termios.error, OSError):
        pass
    return None


_MOUSE = {"click": 1000, "drag": 1002, "move": 1003}


def _dec(name: str, mode: int, *, on: bytes = b"h", off: bytes = b"l") -> Pair:
    return Pair(name, f"\x1b[?{mode}".encode() + on, f"\x1b[?{mode}".encode() + off)


def _pairs(pairs: object) -> "tuple[Pair, ...]":
    pairs = tuple(pairs)
    for p in pairs:
        if not isinstance(p, Pair):
            raise TypeError(f"expected a Pair, got {type(p).__name__}")
    return pairs


def _write(writer, parts: "list[bytes]") -> "Closed | None":
    data = b"".join(parts)
    return writer.write(data) if data else None


def _check_choice(value: object, choices: tuple, name: str) -> None:
    if not isinstance(value, str) and not (value is None and None in choices):
        raise TypeError(f"{name} must be a str, got {type(value).__name__}")
    if value not in choices:
        raise ValueError(f"{name} must be one of {choices}, got {value!r}")
