"""[Style]: colours with roles, inks with declared fallbacks, attributes, the one SGR seam.

Kind: system (the expansion of [Style] in Core); pure. Depends on nothing: no module of
this package imports another cure package (a {Caps} arrives as an argument and only
its `depth` attribute is read; see [Ink]).

[Ink] holds the colour vocabulary (the 16 names, the depths, the xterm palette) and
realizes an ink: a 24-bit value with DECLARED tty256 / tty16 fallbacks, nearest-colour
only on the caller's opt-in. [Colour] resolves a {Name} to a {Colour} (16 names,
`default`, an index, `#hex`, an ink) carrying its theme role. [Attrs] defines {Style}
and builds one from a theme's {Spec}. [Sgr] is the one seam from a Style to SGR
{Codes}.

The boundary (the ops other systems call), defined in the modules and re-exported here:

- `style(spec, inks=None) -> Style` ({Spec} => {Style}, for Theme's [Roles]): see
  [Attrs] (`attrs.style`).
- `sgr(style, caps, *, nearest=False) -> Codes` ({Style} => {Codes}, for [Buffer]):
  a style's full codes, led by the reset `"0"`; see [Sgr] (`sgr.sgr`).
- `codes(style, caps, prev, *, nearest=False) -> Codes` ({Style} => {Codes}, for
  Buffer's [Display]): only the change from `prev`; empty when nothing realized
  changes; see [Sgr] (`sgr.codes`).

Re-exported for consumers: `Style`, `Spec`, `UNDERLINES` (attrs); `Colour`, `Name`,
`FORMS`, `resolve`, `realize` (colour); `Ink`, `NAMES`, `DEPTHS`, `NO_COLOUR`,
`COLOURS_16`, `COLOURS_256`, `TRUECOLOUR`, `depth_of`, `realize_ink`, `parse_hex`,
`palette_rgb`, `nearest16`, `nearest256` (ink); `Codes`, `hyperlink` (sgr).

Note: the function `sgr` shadows the submodule of the same name as a package
attribute. Reach the submodule's own names with `from cure.core.style.sgr import
Codes` (a from-import of the dotted module path), never through the attribute.

Inputs, outputs and errors: as each module states. Effects: none.

Usage:
    from types import SimpleNamespace as Caps
    from cure.core.style import Spec, Style, Ink, style, sgr, codes
    teal = Ink("teal", (42, 161, 152), tty256=37, tty16="cyan")
    s = style(Spec(fg="teal", bold=True, role="kinds-service"), {"teal": teal})
    sgr(s, Caps(depth=24)).escape           # "\\x1b[0;1;38;2;42;161;152m"
    sgr(s, Caps(depth=16)).escape           # "\\x1b[0;1;36m"
    codes(s, Caps(depth=16), s)             # Codes(()): nothing changed
    codes(Style(), Caps(depth=16), s).escape    # "\\x1b[0m"
"""

from .attrs import UNDERLINES, Spec, Style, style
from .colour import FORMS, Colour, Name, realize, resolve
from .ink import (COLOURS_16, COLOURS_256, DEPTHS, NAMES, NO_COLOUR, TRUECOLOUR, Ink,
                  depth_of, nearest16, nearest256, palette_rgb, parse_hex, realize_ink)
from .sgr import Codes, codes, hyperlink, sgr
