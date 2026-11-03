"""[Overlay]: popover, modal, tooltip: a layer with an anchor.

Kind: service (a frozen dataclass node kind; see the Widgets package's protocol).

What it does: a box that floats over its parent on a layer of its own: a popover, a
modal dialog, a menu, a tooltip, a toast's frame. It draws exactly as a Block with
the same fields would (ground, border, title, padding, the focus pop); what makes it
an overlay is data Paint and Layout read:
- `anchor`: where it goes, a Layout [Anchor] `At` the app builds (`At("centre")`,
  `At("bottom-right", margin=1)`). Overlay cannot import Layout and holds it opaque;
  Layout's `lay` reads it (the node floats over its parent's content rect, out of the
  flow, at its measured size, clipped only by the root rect).
- `layer`: its z (an `int >= 1`): Paint paints the overlay's subtree into a layer of
  its own, composes it over the base by `layer` (Buffer's `Layer(..., z=layer,
  backdrop=backdrop)`), and adds its hits to the {HitMap} on that layer, so a click
  on it never reaches what is underneath.
- `backdrop`: one of Buffer's `BACKDROPS`: `"none"` (only its own footprint covers),
  `"dim"` (a modal's scrim: what is beneath reads, faded), `"opaque"`.
- `modal`: a `bool`: Paint records, on the overlay's layer and before the overlay's
  own hits, `Hit(<the root rect>, (id, "outside"))`, so a click anywhere else lands
  on the overlay (modal capture; the router may dismiss on it). Ignored when `id` is
  `None`.

Data (frozen dataclass; checked on construction):
- `Overlay(body=None, *, anchor, title="", title_at="left", border="rounded",
  focus_border="heavy", kind="block", padding=0, focused=None, layer=1,
  backdrop="none", modal=False, id=None, size=None, scope=None, surface=True)`:
  `anchor` is required (any value but `None`: an overlay always floats; Layout
  checks it is an `At`); `body` its one child (`None`: none); the box fields
  (`title`, `title_at`, `border`, `focus_border`, `kind`, `padding`, `focused`)
  exactly as Block's. `kind` is Block's: a free `str` matching Block's `KIND`,
  `"block"` by default (Views gives its overlays `"dialog"`), the name its edge
  patterns go by (R3b: the runs `frame.<kind>.<edge>`, Block's The edges).
- Equality and hash: the dataclass's own, field by field, `kind` included.
- Class attribute `pane = True` (a focus pane, as Block).

Children (`children`, a property): `(body,)` when `body` is not `None`, else `()`.
`chrome()`, `lifts(ctx)`, `measure(axis, room, ctx, content=0)` and `paint(rect,
ctx, grid, clip=None)` are exactly those of `Block((body,) or (), title=title,
title_at=title_at, border=border, focus_border=focus_border, kind=kind,
padding=padding, focused=focused, id=id)` (the overlay's subtree is its own for
`lifts`; the kind passed through, so a theme's `frame.<kind>.*` patterns reach an
overlay as they reach a Block: its four edges are Block's runs, at the weight it
draws at, its title rect moved in past a wide start or end exactly as Block's, its
chrome and measure untouched by patterns). So an
`Overlay(anchor=At(), title="Help", id="o")` at `Rect(0, 0, 10, 3)` draws
`"╭─ Help ─╮"`, `"│        │"`, `"╰────────╯"` and returns `(Hit(Rect(0, 0, 10, 3),
"o"),)` on layer 0 (Paint moves it to `layer`).

Laws (R2 and R3b, Block's through the Block it draws as):
- draws-as-block: for every Overlay `o` and context, `o.chrome()`, `o.measure(...)`,
  `o.lifts(ctx)` and `o.paint(...)` (cells and hits) equal those of `o._block()`,
  patterns or none; so Block's `kind-inert`, `edges-fit`, `title-around`,
  `layout-unchanged` and `ascii` hold for an Overlay.
- base_unchanged (73c003c): for an Overlay unpatterned for its kind (Block's term),
  every one of them equals commit 73c003c's Overlay built from the same fields
  (loaded through `tests/_gitref.py` at test time, skipped without git history).

Errors: `TypeError` when `anchor` is missing (Python's own) or `None`, `layer` is not
  an int (a `bool` included), `backdrop` is not a `str`, `modal` is not a `bool`, or
  as Block's for the box fields (`kind` included: `"kind must be a str, got
  int"`); `ValueError` when `layer < 1`, `backdrop` is not in `("none", "dim",
  "opaque")`, or as Block's (`kind` included: `"kind must be one lowercase word,
  like 'pane' or 'dialog', got 'Pane'"`). The order: `anchor`, then
  the box fields in Block's order (the shared check, `kind` after `focus_border`),
  then `layer`, `backdrop`, `modal`, then the common fields. `measure` / `paint`: as the protocol
  states.
Effects: none, apart from `paint`'s writes into the grid it is given.
"""

from collections.abc import Hashable
from dataclasses import KW_ONLY, dataclass
from typing import ClassVar

from cure.core.buffer import BACKDROPS, Grid
from cure.core.geometry import Hit, Rect
from cure.core.text import Line

from .block import Block, _check_box, _check_common


@dataclass(frozen=True)
class Overlay:
    """A floating box on a layer of its own, placed by its anchor (see the module)."""

    body: object = None
    _: KW_ONLY
    anchor: object
    title: "str | Line" = ""
    title_at: str = "left"
    border: "str | None" = "rounded"
    focus_border: "str | None" = "heavy"
    kind: str = "block"
    padding: "int | tuple" = 0
    focused: "bool | None" = None
    layer: int = 1
    backdrop: str = "none"
    modal: bool = False
    id: Hashable = None
    size: object = None
    scope: object = None
    surface: bool = True

    pane: ClassVar[bool] = True

    def __post_init__(self) -> None:
        """Check the fields (see Errors)."""
        if self.anchor is None:
            raise TypeError("an Overlay needs an anchor (a Layout At), got None")
        _check_box(self.title, self.title_at, self.border, self.focus_border, self.kind,
                  self.padding, self.focused)
        if not isinstance(self.layer, int) or isinstance(self.layer, bool):
            raise TypeError(f"layer must be an int, got {type(self.layer).__name__}")
        if self.layer < 1:
            raise ValueError(f"layer must be >= 1, got {self.layer}")
        if not isinstance(self.backdrop, str):
            raise TypeError(f"backdrop must be a str, got {type(self.backdrop).__name__}")
        if self.backdrop not in BACKDROPS:
            raise ValueError(f"backdrop must be one of {BACKDROPS}, got {self.backdrop!r}")
        if not isinstance(self.modal, bool):
            raise TypeError(f"modal must be a bool, got {type(self.modal).__name__}")
        _check_common(self)

    @property
    def children(self) -> tuple:
        """The body, alone (see the module)."""
        return () if self.body is None else (self.body,)

    def chrome(self) -> dict:
        """As a Block's with the same box fields."""
        return self._block().chrome()

    def lifts(self, ctx: object) -> bool:
        """As a Block's: whether this overlay is the focus pane."""
        return self._block().lifts(ctx)

    def measure(self, axis: str, room: int, ctx: object, content: int = 0) -> int:
        """As a Block's with the same box fields."""
        return self._block().measure(axis, room, ctx, content)

    def paint(self, rect: Rect, ctx: object, grid: Grid, clip: "Rect | None" = None
              ) -> "tuple[Hit, ...]":
        """As a Block's with the same box fields."""
        return self._block().paint(rect, ctx, grid, clip)

    def _block(self) -> Block:
        """The Block this overlay draws as (its box fields, its body, its id)."""
        return Block(self.children, title=self.title, title_at=self.title_at,
                     border=self.border, focus_border=self.focus_border, kind=self.kind,
                     padding=self.padding, focused=self.focused, id=self.id)
