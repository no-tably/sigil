"""[Sgr]: the ONE style -> SGR seam: a style's codes, or only the change from the previous one.

Kind: service (a data class and pure functions).

What it does: turns a {Style} into {Codes}, the SGR parameters that draw it at the depth
a {Caps} allows. `sgr(style, caps)` gives a style's full codes, led by a reset, so a
run can stand alone (rows printed once, goldens). `codes(style, caps, prev)` gives
only the change from `prev`, the style the terminal's pen is known to hold (Display's
diff). No other cure module writes SGR; nothing parses it back.

Data (frozen dataclass):
- `Codes(params: tuple[str, ...] = ())`: the SGR parameters in order, each one group
  as written between ";" (`"1"`, `"38;5;37"`, `"4:3"`). Stored as given.
  `Codes.escape`: `""` when `params` is empty, else `"\\x1b[" + ";".join(params) + "m"`.
  `bool(codes)` is `bool(codes.params)`.

The realized pen. With D = `depth_of(caps)`, a style realizes to nine values:
`bold, dim, italic, underline, reverse, strike` as stored, and three shades (see
[Colour]'s `realize`, `nearest` passed through): `fg = realize(style.fg)`,
`bg = realize(style.bg)`, and `ul = realize(style.underline_colour)` when D is 256 or
24, else `None` (an underline colour is never sent to a 16-colour or colourless
terminal, where `58;5;n` could read as blink and bold). A `None` colour field realizes
to `None`. The *plain* pen has every flag off, `underline` `None` and all three shades
`None`. Roles and `link` are not part of the pen.

The parameter for each part (one entry of `params` each):

| part | on / value | off / none |
| --- | --- | --- |
| bold | `"1"` | `"22"` (shared with dim) |
| dim | `"2"` | `"22"` (shared with bold) |
| italic | `"3"` | `"23"` |
| underline | `"4"` single, `"4:2"` double, `"4:3"` curly, `"4:4"` dotted, `"4:5"` dashed | `"24"` |
| reverse | `"7"` | `"27"` |
| strike | `"9"` | `"29"` |
| fg | index i < 8 `str(30 + i)`; 8 <= i < 16 `str(90 + i - 8)`; i >= 16 `f"38;5;{i}"`; `(r, g, b)` `f"38;2;{r};{g};{b}"` | `"39"` |
| bg | i < 8 `str(40 + i)`; 8 <= i < 16 `str(100 + i - 8)`; i >= 16 `f"48;5;{i}"`; `f"48;2;{r};{g};{b}"` | `"49"` |
| underline colour | any index `f"58;5;{i}"`; `f"58;2;{r};{g};{b}"` | `"59"` |

(Semicolons throughout, colons only in the underline style; numbers in decimal with no
padding.)

The change (`codes(style, caps, prev, nearest=False)`), comparing the realized pens
P (of `prev`) and N (of `style`):

1. P == N: `Codes(())`, so an unchanged style emits nothing (the idle frame is silent),
   however the two styles differ in roles, links or unrealized colours.
2. N is plain (and P is not): `Codes(("0",))`.
3. Otherwise, in this order:
   a. offs: `"22"` when bold or dim was on in P and is off in N; `"23"` when italic
      turns off; `"24"` when underline goes from a style to `None`; `"27"` when
      reverse turns off; `"29"` when strike turns off;
   b. ons: `"1"` when N has bold and (P had not, or `"22"` was just emitted); `"2"`
      likewise for dim; `"3"` when italic turns on; the underline style's code when
      N's underline is not `None` and differs from P's (`"single"` -> `"curly"` is
      just `"4:3"`); `"7"` when reverse turns on; `"9"` when strike turns on;
   c. colours: fg's parameter when the fg shade differs (`"39"` when N's is `None`),
      then bg's (`"49"`), then the underline colour's (`"59"`).

The full codes: `sgr(style, caps, nearest=False).params == ("0",) +
codes(style, caps, Style(), nearest=nearest).params`: a reset, then every part N
holds that the plain pen does not, in the order above (bold, dim, italic, underline,
reverse, strike, fg, bg, underline colour). `sgr(Style(), caps).params == ("0",)`.

`style` and `prev` may each be `None`, taken as `Style()` (a cell with no style).

Colour off. At depth 0 every shade is `None`, so no colour parameter is ever emitted,
while bold, dim, italic, underline, reverse and strike still are: the screen still
reads with colour off when highlights add marks or reverse (Rules carried over; making
them do so is [Theme]'s `additive` rule, not Style's).

Links are not SGR: `codes` and `sgr` never look at `link`, and SGR 0 does not end a
hyperlink. Display opens and closes them itself with `hyperlink(uri)`, the OSC 8
string: `"\\x1b]8;;" + uri + "\\x1b\\\\"` for a `str` uri, and the closing
`"\\x1b]8;;\\x1b\\\\"` for `None` or `""`.

Inputs: `sgr`, `codes`: a {Style} (or `None`), a {Caps} (`caps.depth`), for `codes`
  the previous {Style} (or `None`), and `nearest: bool` (keyword only; the caller's
  opt-in to nearest-colour, README decision 1). `hyperlink`: `str | None`.
Outputs: `sgr`, `codes`: {Codes}. `hyperlink`: a `str`.
Errors: `sgr` / `codes`: `TypeError` when `style` or `prev` is neither a `Style` nor
  `None`; `ValueError` from `depth_of` when `caps.depth` is not a depth.
  `hyperlink`: `TypeError` when `uri` is neither a `str` nor `None`; `ValueError` when
  it holds a control character (C0, DEL or C1; `uri holds a control character:
  <repr>`), so a link can never carry an escape, or a lone surrogate (U+D800..U+DFFF;
  `uri holds a lone surrogate: <repr>`, the control checked first), which no terminal
  can take. These are exactly the links [Attrs]' Style refuses, so `hyperlink`
  never raises for the `link` of any Style, and its result always encodes as strict
  UTF-8.
Effects: none.

Invariant: one_seam — every SGR byte cure emits for a style comes from this module's
  `sgr` / `codes`: for any styles a, b and depth, applying `codes(b, caps, a)` to a pen
  drawn by `sgr(a, caps)` leaves the same realized pen as `sgr(b, caps)`.

Usage:
    from types import SimpleNamespace as Caps
    from cure.core.style import Spec, Style, style, sgr, codes
    s = style(Spec(fg="red", bold=True))
    sgr(s, Caps(depth=256)).params                  # ("0", "1", "31")
    sgr(s, Caps(depth=256)).escape                  # "\\x1b[0;1;31m"
    codes(Style(dim=True), Caps(depth=256), s).params   # ("22", "2", "39")
    codes(Style(), Caps(depth=256), s).params       # ("0",)
    codes(s, Caps(depth=0), Style(bold=True))       # Codes(()): colour off
"""

from dataclasses import dataclass

from .attrs import Style
from .colour import Colour, realize
from .ink import NAMES, depth_of


@dataclass(frozen=True)
class Codes:
    """{Codes}: SGR parameters in order; `escape` is the CSI ... m string ("" for none)."""

    params: tuple[str, ...] = ()

    @property
    def escape(self) -> str:
        """`""` for no params, else `"\\x1b[" + ";".join(params) + "m"`."""
        return "\x1b[" + ";".join(self.params) + "m" if self.params else ""

    def __bool__(self) -> bool:
        """True when there is at least one parameter."""
        return bool(self.params)


def sgr(style: "Style | None", caps: object, *, nearest: bool = False) -> Codes:
    """A style's full codes at `caps.depth`: `"0"`, then every part it holds (see the module)."""
    return Codes(("0",) + codes(style, caps, Style(), nearest=nearest).params)


def codes(style: "Style | None", caps: object, prev: "Style | None", *, nearest: bool = False) -> Codes:
    """Only the change from `prev` to `style` at `caps.depth` (see the module)."""
    # Speed: the depth is read once for both pens (the errors in today's order: `style`'s
    # type, then the depth, then `prev`'s type).
    style = _checked(style)
    depth = depth_of(caps)
    new = _pen(style, depth, caps, nearest)
    old = _pen(_checked(prev), depth, caps, nearest)
    if new == old:
        return Codes(())
    if new == _PLAIN:
        return Codes(("0",))
    return Codes(tuple(_change(old, new)))


def hyperlink(uri: "str | None") -> str:
    """The OSC 8 string that opens a hyperlink to `uri`, or closes one for None / ""."""
    if uri is None:
        uri = ""
    if not isinstance(uri, str):
        raise TypeError(f"uri must be a str or None, got {type(uri).__name__}")
    if any(ord(ch) < 0x20 or 0x7F <= ord(ch) <= 0x9F for ch in uri):
        raise ValueError(f"uri holds a control character: {uri!r}")
    if any(0xD800 <= ord(ch) <= 0xDFFF for ch in uri):
        raise ValueError(f"uri holds a lone surrogate: {uri!r}")
    return "\x1b]8;;" + uri + "\x1b\\"


_Shade = "int | tuple[int, int, int] | None"

# The realized pen: what a style draws as at one depth, the tuple (bold, dim, italic,
# underline, reverse, strike, fg, bg, ul). Speed: a plain tuple, built and compared
# without a class.
_Pen = tuple
_PLAIN: _Pen = (False, False, False, None, False, False, None, None, None)


def _checked(style: "Style | None") -> Style:
    if style is None:
        return _NONE
    if not isinstance(style, Style):
        raise TypeError(f"expected a Style or None, got {type(style).__name__}")
    return style


_NONE = Style()


def _pen(style: Style, depth: int, caps: object, nearest: bool) -> _Pen:
    ul = _shade(style.underline_colour, depth, caps, nearest) if depth in (256, 24) else None
    return (style.bold, style.dim, style.italic, style.underline, style.reverse, style.strike,
            _shade(style.fg, depth, caps, nearest), _shade(style.bg, depth, caps, nearest), ul)


def _shade(colour: object, depth: int, caps: object, nearest: bool) -> _Shade:
    """`realize(colour, caps, nearest=nearest)` (`None` for `None`), `depth` its depth."""
    if colour is None:
        return None
    if type(colour) is Colour:
        # Speed: the common forms answered here, without realize's checks (the depth is
        # known good; an exact Colour was checked on construction).
        if depth == 0:
            return None
        form = colour.form
        if form == "index" and (depth != 16 or colour.value < 16):
            return colour.value
        if form == "name":
            return NAMES.index(colour.value)
        if form == "default":
            return None
    return realize(colour, caps, nearest=nearest)


def _change(old: _Pen, new: _Pen) -> list[str]:
    o_bold, o_dim, o_italic, o_under, o_rev, o_strike, o_fg, o_bg, o_ul = old
    n_bold, n_dim, n_italic, n_under, n_rev, n_strike, n_fg, n_bg, n_ul = new
    out = []
    intensity_off = (o_bold and not n_bold) or (o_dim and not n_dim)
    if intensity_off:
        out.append("22")
    if o_italic and not n_italic:
        out.append("23")
    if o_under and not n_under:
        out.append("24")
    if o_rev and not n_rev:
        out.append("27")
    if o_strike and not n_strike:
        out.append("29")
    if n_bold and (not o_bold or intensity_off):
        out.append("1")
    if n_dim and (not o_dim or intensity_off):
        out.append("2")
    if n_italic and not o_italic:
        out.append("3")
    if n_under is not None and n_under != o_under:
        out.append(_UNDERLINE_CODES[n_under])
    if n_rev and not o_rev:
        out.append("7")
    if n_strike and not o_strike:
        out.append("9")
    if n_fg != o_fg:
        out.append(_fg(n_fg))
    if n_bg != o_bg:
        out.append(_bg(n_bg))
    if n_ul != o_ul:
        out.append(_ul(n_ul))
    return out


_UNDERLINE_CODES = {"single": "4", "double": "4:2", "curly": "4:3", "dotted": "4:4", "dashed": "4:5"}


def _rgb(lead: str, rgb: tuple[int, int, int]) -> str:
    return f"{lead};2;{rgb[0]};{rgb[1]};{rgb[2]}"


def _fg(shade: _Shade) -> str:
    return _ansi(shade, 30, 90, "38", "39")


def _bg(shade: _Shade) -> str:
    return _ansi(shade, 40, 100, "48", "49")


def _ansi(shade: _Shade, base: int, bright: int, lead: str, off: str) -> str:
    if shade is None:
        return off
    if isinstance(shade, tuple):
        return _rgb(lead, shade)
    if shade < 8:
        return str(base + shade)
    if shade < 16:
        return str(bright + shade - 8)
    return f"{lead};5;{shade}"


def _ul(shade: _Shade) -> str:
    if shade is None:
        return "59"
    if isinstance(shade, tuple):
        return _rgb("58", shade)
    return f"58;5;{shade}"
