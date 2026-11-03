"""[Sweep]: one view over widths × heights: no row or width jumps.

Kind: service (a frozen dataclass and pure functions).

What it does: renders one view at every size of a grid of widths and heights with
Paint's `sizes` (`[Sweep] -> [Paint] : sizes({Node}) => {Frames}`) and reports every
frame that does not hold together at its size: a buffer one column too wide or a row
short (a width or row jump), a hit region, the text cursor or a painted node's clip
outside the frame, or whatever the app's own `check` finds. The nominal size is not
the stressed one; a sweep is how a test reaches the sizes where layouts break (the
narrow width where a border eats the text, the height where a scroll marker takes
the last row).

## The sweep

`sweep(view, widths, heights, ctx, *, check=None) -> tuple[Jump, ...]`:
`frames = sizes(view, widths, heights, ctx)` (Paint's op: `frame(view, (w, h), ctx)`
for every `w` of `widths` and, inside it, every `h` of `heights`, widths outer). For
frame `f` at the requested size `(w, h)`, in that order, these findings, each a
`Jump((w, h), what, detail)` with the `what` and `detail` given:

1. `"width"`, when `f.buffer.w != w`: `f"the buffer is {f.buffer.w} cells wide"`;
2. `"rows"`, when `f.buffer.h != h`: `f"the buffer has {f.buffer.h} rows"`;
3. `"size"`, when `f.size != (w, h)`: `f"the frame's size is {f.size!r}"`;
4. `"hits"`, one per hit of `f.hits.hits`, in order, whose rect is not inside the
   frame: `f"{hit.tag!r} at {hit.rect!r}"`;
5. `"cursor"`, when `f.cursor` is not `None` and not a cell of the frame (`0 <= x <
   w` and `0 <= y < h`): `f"at {f.cursor!r}"`;
6. `"places"`, one per place of `f.places`, in order, whose `clip` is not inside the
   frame: `f"{place.id!r} clipped to {place.clip!r}"`;
7. `"check"`, when `check` is given and `check(f)` returns a `str` `s`: `s`.

A rect `r` is inside the `w` x `h` frame when it is empty (`r.w == 0` or `r.h == 0`:
it covers no cell) or `0 <= r.x`, `0 <= r.y`, `r.x + r.w <= w` and `r.y + r.h <= h`.
A place's `rect` is not checked (a scrolled node's rect may run past the frame; its
`clip` is what it painted). The result is every finding of every frame, frames in
`sizes`' order; `()` when the view holds together at every size.

`check`: `None`, or the app's own law for one frame, a function `check(frame) -> str |
None` (a `str` names what is wrong, `None` is fine), called once per frame in order,
after the built-in findings of that frame. Examples: "the title survives at every
width", "the `↓N more` marker shows whenever a row is hidden", or Testing's
[Virtual] replay of each frame.

`assert_sweep(view, widths, heights, ctx, *, check=None) -> None`: `sweep(...)`,
raising `AssertionError(message)` when it finds anything, `message` being
`f"the sweep found {n} jump(s):"` followed by one line per jump, `"\\n"` before each,
the first 20 only (`str(jump)`), then, when `n > 20`, a line
`f"... and {n - 20} more"`.

Data (frozen dataclass, stored as given):
- `Jump(size, what, detail)`: `size` the requested `(w, h)`; `what` one of `WHATS` =
  `("width", "rows", "size", "hits", "cursor", "places", "check")`; `detail` a `str`.
  `str(jump)`: `f"{w}x{h} {what}: {detail}"`.

Laws (each a property a test can loop over views, sizes and contexts):
- pure: `sweep(v, ws, hs, c) == sweep(v, ws, hs, c)`, with `v` and `c` unchanged (a
  frame is a pure function, [Frame]'s law), for a `check` that is itself pure.
- empty: `sweep(v, (), hs, c) == ()` and `sweep(v, ws, (), c) == ()`.
- Paint's sizes: for every view Paint takes, every `Jump` of `sweep(v, ws, hs, c)`
  without `check` is a breach of [Frame]'s laws (sizes; inside), so the result is
  `()`; with a `check` that always gives `None`, the same.
- check: with `check` returning `s` for every frame, the result holds exactly one
  `Jump(size, "check", s)` per frame, at its requested size, in `sizes`' order.
- order: the jumps of frame `i` come before those of frame `i + 1`, and within a
  frame in the order 1..7 above.

Inputs: `view`: what Paint's `frame` takes (a widget node, a Layout `Screens`, a
  `Tiled`); `widths`, `heights`: iterables of ints >= 0; `ctx`: the app's root Draw
  {Context}; `check`: `None` or a callable.
Outputs: a tuple of `Jump` (`sweep`); `None` (`assert_sweep`).
Errors: `TypeError` when `check` is neither `None` nor callable, or a `check(f)`
  returns something other than a `str` or `None`; and as Paint's `sizes` raises
  (`TypeError` for widths or heights that are not iterables of ints, `ValueError` for a
  negative size, and what the view's nodes raise). An exception from `check` itself
  propagates. `assert_sweep`: `AssertionError` when there is a jump, as above.
Effects: none (whatever `check` does is the app's).

Usage:
    from cure.core.buffer import text
    from cure.draw.context import Context
    from cure.draw.theme import builtin
    from cure.draw.widgets import Block, Paragraph
    from cure.testing.sweep import Jump, assert_sweep, sweep
    ctx = Context.of(builtin())
    node = Block((Paragraph("hi"),), id="b")
    sweep(node, (3, 4, 6), (3,), ctx)       # (): every frame its size, everything inside
    kept = lambda f: None if "hi" in text(f.buffer) else "the text is cut"
    sweep(node, (3, 4, 6), (3,), ctx, check=kept)
    # (Jump((3, 3), "check", "the text is cut"),): at 3 wide it shows "│↓│"
    str(Jump((3, 3), "check", "the text is cut"))   # "3x3 check: the text is cut"
    assert_sweep(node, (4, 6), (3, 5), ctx, check=kept)   # None
"""

from collections.abc import Iterable
from dataclasses import dataclass

from cure.draw.paint import sizes

WHATS: tuple[str, ...] = ("width", "rows", "size", "hits", "cursor", "places", "check")
"""What a `Jump` reports, in the order a frame's findings come."""

_SHOWN = 20


@dataclass(frozen=True)
class Jump:
    """A frame that does not hold together at its requested size (see the module)."""

    size: "tuple[int, int]"
    what: str
    detail: str

    def __str__(self) -> str:
        """`f"{w}x{h} {what}: {detail}"`."""
        w, h = self.size
        return f"{w}x{h} {self.what}: {self.detail}"


def sweep(view: object, widths: object, heights: object, ctx: object, *,
          check: object = None) -> "tuple[Jump, ...]":
    """Every jump of `view` over widths × heights, frames in Paint's `sizes` order (see the module)."""
    if check is not None and not callable(check):
        raise TypeError(f"check must be None or callable, got {type(check).__name__}")
    # Taken once (an iterator is read once), for the requested sizes; Paint checks them.
    ws = tuple(widths) if isinstance(widths, Iterable) else widths
    hs = tuple(heights) if isinstance(heights, Iterable) else heights
    frames = sizes(view, ws, hs, ctx)
    out: list = []
    for f, size in zip(frames, ((w, h) for w in ws for h in hs)):
        out.extend(_findings(f, size, check))
    return tuple(out)


def assert_sweep(view: object, widths: object, heights: object, ctx: object, *,
                 check: object = None) -> None:
    """`sweep(...)`, raising AssertionError listing the jumps when there are any."""
    jumps = sweep(view, widths, heights, ctx, check=check)
    if jumps:
        lines = [f"the sweep found {len(jumps)} jump(s):"] + [str(j) for j in jumps[:_SHOWN]]
        if len(jumps) > _SHOWN:
            lines.append(f"... and {len(jumps) - _SHOWN} more")
        raise AssertionError("\n".join(lines))


def _findings(f: object, size: "tuple[int, int]", check: object) -> "list[Jump]":
    """One frame's findings at its requested size, in the order 1..7 (see the module)."""
    w, h = size
    out = []
    if f.buffer.w != w:
        out.append(Jump(size, "width", f"the buffer is {f.buffer.w} cells wide"))
    if f.buffer.h != h:
        out.append(Jump(size, "rows", f"the buffer has {f.buffer.h} rows"))
    if f.size != (w, h):
        out.append(Jump(size, "size", f"the frame's size is {f.size!r}"))
    for hit in f.hits.hits:
        if not _inside(hit.rect, w, h):
            out.append(Jump(size, "hits", f"{hit.tag!r} at {hit.rect!r}"))
    if f.cursor is not None:
        x, y = f.cursor
        if not (0 <= x < w and 0 <= y < h):
            out.append(Jump(size, "cursor", f"at {f.cursor!r}"))
    for place in f.places:
        if not _inside(place.clip, w, h):
            out.append(Jump(size, "places", f"{place.id!r} clipped to {place.clip!r}"))
    if check is not None:
        s = check(f)
        if s is not None and not isinstance(s, str):
            raise TypeError(f"check must return a str or None, got {type(s).__name__}")
        if s is not None:
            out.append(Jump(size, "check", s))
    return out


def _inside(r: object, w: int, h: int) -> bool:
    """`r` covers no cell, or every cell it covers is in the `w` x `h` frame."""
    if r.w == 0 or r.h == 0:
        return True
    return 0 <= r.x and 0 <= r.y and r.x + r.w <= w and r.y + r.h <= h
