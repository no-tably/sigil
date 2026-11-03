"""[Scaffold]: header and footer pinned, body scrolls; chrome reserved before the body.

Kind: service (a pure function from row counts and a {Rect} to `Regions`; `Scaffold`
and `Regions` are frozen dataclasses). Scaffold provides `regions` on top of [Solver]:
when the pins must shrink, `solve` shares the rows. Overflow always shows: `↓N more`
is the floor. A nested scaffold behaves as the root does. Scaffold is vertical only:
every region spans the rect's full width; what is too wide is the body's concern.

`regions(rect, header, content, footer, *, offset=0, anchor="head") -> Regions`.
`header` and `footer` are the pins' natural heights in rows and `content` the body's
natural height (all measured by the caller; Layout never measures). With
`H = rect.h` and `B = H - header - footer` (the body's budget), exactly one case holds:

A. Fits (`B >= 0` and `content <= B`): the pins get their full heights; the body
   region is all `B` rows (a body may fill it); no indicator (`more.h == 0`).
   `first = 0`, `shown = content`.
B. The body overflows (`B >= 1` and `content > B`): the pins get their full heights;
   the indicator takes the body's last row; the body viewport keeps `keep = B - 1`
   rows. The scroll position: with `anchor="head"`, `first = clamp(offset, 0,
   content - keep)` (`offset` rows scrolled down from the top); with `anchor="tail"`,
   `first = content - keep - clamp(offset, 0, content - keep)` (`offset` rows
   scrolled up from the end: a log follows its tail at 0). `shown = keep`. With
   `B == 1` only the indicator shows.
C. The pins do not leave a row (`B < 0`, or `B == 0` and `content > 0`), and `H >= 1`:
   the indicator still gets its row (the floor is under the pins) and the pins share
   the other `H - 1`: `header_rows, footer_rows = solve([Fixed(header),
   Fixed(footer)], H - 1)` (in proportion, the header first on a tie: so the taller
   pin yields, and on a tie the footer). The body viewport is empty; `first = 0`,
   `shown = 0`.
D. `H == 0` and A does not hold: there is no row to show anything: every region is
   empty (at `rect.x, rect.y`), `first = 0`, `shown = 0`, and the counts
   still say what is hidden (`below = content`, the cuts the pins' full heights).

The regions, top to bottom, each `rect.w` wide at `rect.x`: `header`, `body` (the
viewport: the content rows `first .. first + shown - 1` are drawn in it, scrolled by
the caller with `first`), `more` (the indicator row, `h` 0 or 1, directly above the
footer), `footer`. An empty region keeps its position (where it would start).

The counts: `above = first` (content rows hidden above), `below = content - first -
shown` (hidden below), `header_cut` and `footer_cut` (pin rows lost: the full height
minus the rows given). `hidden = above + below + header_cut + footer_cut`. What Paint
draws in `more`: the counts, e.g. "↑{above} ↓{below} more" (each part only when not
0), and a mark when a pin is cut; the words are Paint's, the row and the numbers are
Scaffold's.

Invariant: never_silent — for every input with `rect.h >= 1`: `more.h == 1` exactly when `hidden > 0`; and always `above + shown + below == content`, `header.h + header_cut == header`, `footer.h + footer_cut == footer`. Nothing is ever dropped without the indicator row and an exact count, and no indicator is drawn when nothing is hidden.
Invariant: same_at_depth — `regions(rect.moved(dx, dy), *counts, **kw) == regions(rect, *counts, **kw).moved(dx, dy)` for every `dx`, `dy`: the result depends only on the rect's size and the counts, never on where the rect sits or what contains it (there is no depth or parent argument). Through `lay`, a `Scaffold` node laid anywhere in a tree gets the same `Regions` and the same child rects as that node laid as the root in the same rect.

Also always: `header.h + body.h + more.h + footer.h == rect.h`, the four regions tile
`rect` in that order; `body.h == shown` in cases B, C and D (the viewport is exactly
the rows shown) and `body.h == B` in case A.

Data:
- `Scaffold(offset=0, anchor="head")`: the layout value `lay` reads off a node whose
  children are exactly `(header, body, footer)` (an absent pin is a node whose natural
  height is 0). `offset` any int (clamped as above: an overshooting scroll is not an
  error); `anchor` one of `ANCHORS` ("head", "tail"). The scroll position is the
  app's state, passed in the node.
- `Regions(header, body, more, footer, first, shown, above, below, header_cut,
  footer_cut)`: four `Rect`s and six ints. `hidden` (property) as above;
  `moved(dx, dy) -> Regions` with every rect moved, the counts kept.

Inputs: `rect` a {Rect}; `header`, `content`, `footer`: ints >= 0; `offset` an int;
  `anchor` a str.
Outputs: `Regions` ({Rects} and the overflow counts).
Errors: `TypeError` when `rect` is not a `Rect` or a count or `offset` is not an int
  (a `bool` included); `ValueError` when a count is negative or `anchor` is unknown.
  Assigning a field raises `dataclasses.FrozenInstanceError`.
Effects: none.

Usage:
    from cure.core.geometry import Rect
    from cure.draw.layout.scaffold import regions
    r = regions(Rect(0, 0, 80, 24), 1, 10, 1)       # A: fits
    r.header, r.body, r.more, r.footer
    #   Rect(0, 0, 80, 1), Rect(0, 1, 80, 22), Rect(0, 23, 80, 0), Rect(0, 23, 80, 1)
    r.first, r.shown, r.hidden                      # 0, 10, 0
    r = regions(Rect(0, 0, 80, 24), 1, 100, 1)      # B: overflows
    r.body, r.more                                  # Rect(0, 1, 80, 21), Rect(0, 22, 80, 1)
    r.first, r.shown, r.above, r.below              # 0, 21, 0, 79
    regions(Rect(0, 0, 80, 24), 1, 100, 1, offset=90).first          # 79 (clamped)
    regions(Rect(0, 0, 80, 24), 1, 100, 1, anchor="tail").first      # 79
    regions(Rect(0, 0, 80, 24), 1, 100, 1, anchor="tail", offset=5).first   # 74
    r = regions(Rect(0, 0, 10, 6), 3, 5, 3)         # C: the pins fill it; the footer yields
    r.header, r.more, r.footer                      # Rect(0, 0, 10, 3), Rect(0, 3, 10, 1), Rect(0, 4, 10, 2)
    r.footer_cut, r.below                           # 1, 5
    r = regions(Rect(0, 0, 10, 4), 3, 5, 3)         # C: the pins exceed it
    r.header.h, r.more.h, r.footer.h, r.header_cut, r.footer_cut   # 2, 1, 1, 1, 2
    regions(Rect(0, 0, 10, 1), 0, 5, 0).more        # Rect(0, 0, 10, 1): "↓5 more"
"""

from dataclasses import dataclass

from cure.core.geometry import Rect

from .solver import Fixed, solve

ANCHORS = ("head", "tail")


@dataclass(frozen=True)
class Scaffold:
    """The layout value for a node of (header, body, footer): scroll offset and anchor."""

    offset: int = 0
    anchor: str = "head"

    def __post_init__(self) -> None:
        if not isinstance(self.offset, int) or isinstance(self.offset, bool):
            raise TypeError(f"offset must be an int, got {type(self.offset).__name__}")
        if self.anchor not in ANCHORS:
            raise ValueError(f"anchor must be one of {ANCHORS}, got {self.anchor!r}")


@dataclass(frozen=True)
class Regions:
    """A scaffold's four regions, top to bottom, and its overflow counts."""

    header: Rect
    body: Rect
    more: Rect
    footer: Rect
    first: int
    shown: int
    above: int
    below: int
    header_cut: int
    footer_cut: int

    @property
    def hidden(self) -> int:
        """`above + below + header_cut + footer_cut`: what the indicator reports."""
        return self.above + self.below + self.header_cut + self.footer_cut

    def moved(self, dx: int, dy: int) -> "Regions":
        """Every rect moved by (`dx`, `dy`), the counts kept."""
        return Regions(self.header.moved(dx, dy), self.body.moved(dx, dy),
                       self.more.moved(dx, dy), self.footer.moved(dx, dy), self.first,
                       self.shown, self.above, self.below, self.header_cut, self.footer_cut)


def regions(rect: Rect, header: int, content: int, footer: int, *, offset: int = 0,
            anchor: str = "head") -> Regions:
    """The header, body, indicator and footer of a scaffold in `rect` (cases A-D above)."""
    if not isinstance(rect, Rect):
        raise TypeError(f"rect must be a Rect, got {type(rect).__name__}")
    for value, name in ((header, "header"), (content, "content"), (footer, "footer")):
        _int(value, name)
        if value < 0:
            raise ValueError(f"{name} must be >= 0, got {value}")
    _int(offset, "offset")
    if anchor not in ANCHORS:
        raise ValueError(f"anchor must be one of {ANCHORS}, got {anchor!r}")
    height = rect.h
    budget = height - header - footer
    if budget >= 0 and content <= budget:
        return _tiled(rect, header, budget, 0, footer, 0, content, content, header, footer)
    if budget >= 1:
        keep = budget - 1
        scroll = _clamp(offset, 0, content - keep)
        first = scroll if anchor == "head" else content - keep - scroll
        return _tiled(rect, header, keep, 1, footer, first, keep, content, header, footer)
    if height >= 1:
        header_rows, footer_rows = solve([Fixed(header), Fixed(footer)], height - 1)
        return _tiled(rect, header_rows, 0, 1, footer_rows, 0, 0, content, header, footer)
    return _tiled(rect, 0, 0, 0, 0, 0, 0, content, header, footer)


def _int(value: object, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))


def _tiled(rect: Rect, header_h: int, body_h: int, more_h: int, footer_h: int, first: int,
           shown: int, content: int, header: int, footer: int) -> Regions:
    """The four regions stacked from `rect.y` at the given heights, and the counts."""
    y, rows = rect.y, []
    for h in (header_h, body_h, more_h, footer_h):
        rows.append(Rect(rect.x, y, rect.w, h))
        y += h
    return Regions(*rows, first=first, shown=shown, above=first,
                   below=content - first - shown, header_cut=header - header_h,
                   footer_cut=footer - footer_h)
