"""[Strokes]: free 2D drawing for what a box tree can't say: wires, maps, plots; glyphs
come from the {Charset} it is given. Light, heavy, double, dashed, dotted, heavy-dashed
(sigil's kit: dashed ╌ ╎, dotted ┄ ┆, heavy-dashed ╍ ╏ on straight runs, their corners
and tees light, light, heavy): a cell is a direction mask, crossings join; straight
runs hop over crossings.

Kind: service (a mutable drawing class, its kept form, and the functions that stroke
into it).

What it does: holds a drawing, the {Canvas}, as sparse cells in three layers, and
strokes {Path}s into it as direction masks ([Junctions]): lines that meet join into
corners, tees and crosses, and a straight run that crosses a straight line hops over
it. `rows` turns a canvas into rows of `(text, style)` runs with the glyphs of the
charset given ({Rows}). `keep` makes a {Kept} canvas, kept from frame to frame, whose
rows are worked out again only where its cells changed.

Coordinates: column `x`, row `y`, 0-based, `int`s (never `bool`). Every write refuses
a negative coordinate; there is no right or bottom edge (a canvas grows).

The {Canvas} (a mutable class; `Canvas()` is empty). Its state is exactly:
- joints: cell `(x, y)` -> a [Junctions] `Joint` (mask, weight, style): the strokes;
- texts: cell -> a Text `Cell` (glyph, width, style): what [Labels], [Plot] and
  [Sprites] write. A narrow glyph is `Cell(g, 1, s)`; a wide one is its head
  `Cell(g, 2, s)` at `x` and its tail `Cell("", 0, s)` at `x + 1`;
- tags: cell -> any hashable value other than `None` (never drawn; [Query] reads them);
- the extent `width`, `height` (read-only ints): `max(x) + 1` and `max(y) + 1` over
  every cell any op has written (a tail included) and every `extend`, `0` when none.
  The extent only grows (the one exception: `restore`, which [Sprites]' `undo` calls,
  puts it back).
Two canvases are `==` when their joints, texts, tags and extent are equal (a `Kept`
and a `Canvas` included); a canvas is unhashable.

Invariant: no_orphan_half — a canvas's texts are always well formed: every head
  (width 2) at `(x, y)` has its tail at `(x + 1, y)` in the same style, and every
  tail follows a head. When a write covers one column of a wide pair and not the
  other, the column it does not cover becomes `Cell(" ", 1, s)`, `s` the pair's
  style (its tag unchanged). A glyph is never split and never shifts what follows.

Invariant: text_wins — at a cell holding both a text and a joint, `rows` shows the
  text; the joint stays (a [Query] still sees its mask) and shows again once the
  text is gone.

Stroking (`stroke(canvas, path, *, hops=None, fixed=frozenset(), tag=None)`):
1. The hop cells. `hops=None` is the hop rule: with `m = link(path)`, every cell `c`
   where `m.at(c) == E | W` and the canvas's joint at `c` has mask exactly `N | S`, or
   `m.at(c) == N | S` and the joint's mask is exactly `E | W`. That is: an interior
   cell of a straight stretch of this path (never an end, never a bend) where it
   crosses a straight line already drawn. A crossing there is drawn as a hop-over,
   `─│─`: the line crossed keeps its cell, and the path's cells on either side keep
   their arms toward it, so it never reads as joined. Anywhere else lines join (an
   end on a line makes a tee, a bend on one a junction, lines that meet a corner).
   `hops` given (an iterable of cells) is exactly those cells; `hops=()` joins at
   every crossing (`──┼──`). The rule reads the canvas before this path is laid, so
   a path never hops over itself.
2. For each `(c, mask)` of `link(path, hops)`: the joint at `c` becomes
   `join(joint, mask, path.weight, path.style, fixed=c in fixed)` ([Junctions]: arms
   OR together; the higher-ranked weight takes the cell, the first on equal ranks,
   `dashed` against `heavy-dashed` included;
   a `fixed` cell keeps its weight and style). With `tag` not `None`, `c`'s tag
   becomes `tag`. The extent grows to cover `c`.
3. Returns the cells laid: `frozenset` of the cells of `link(path, hops)`.
A path drawn with `stroke` lays only joints: texts are untouched (text_wins).

Other writes:
- `stub(canvas, cell, mask, weight="light", style=None, *, tag=None) -> None`: half a
  link, an arm from `cell` toward a neighbour and not into it: the joint at `cell`
  becomes `join(joint, mask, weight, style)`; `mask` an int 1..15 (usually one of
  `N`, `E`, `S`, `W`). The tag and extent as `stroke`'s.
- `blit(canvas, other, x, y) -> None`: copy `other` (a canvas) in with its (0, 0) at
  `(x, y)`: each cell of `other` at `(cx, cy)` lands at `(x + cx, y + cy)`, where it
  REPLACES the joint (not joined), the text and the tag with `other`'s, for each of
  those `other` has there; what `other` lacks there is kept. Texts follow
  no_orphan_half at the edges of what lands. The extent grows to cover
  `(x + other.width - 1, y + other.height - 1)` when `other`'s extent is not empty.
- `Canvas.extend(w, h) -> None`: the extent becomes at least `w` x `h` (ints >= 0);
  nothing is drawn.
- `Canvas.copy() -> Canvas`: a new plain `Canvas` (never a `Kept`) `==` to it,
  independent of it.

The texts writers (Q9b: the one public way [Labels], [Plot] and [Sprites] write a
canvas's texts layer and read it back; none of them touches a `Canvas`'s private
fields or methods). Three module-level functions, as `stroke`, `stub` and `blit` are,
so that a drawn flow's op is a public name of this module:
- `place(canvas, x, y, cells, *, tag=None) -> None` (what [Labels]' `label` and
  [Plot]'s `plot` write through): cell `i` of `cells` (a `tuple` of Text `Cell`s, in
  the order Text's `put` gives them: a wide glyph as its head then its tail) becomes
  the text at `(x + i, y)`, replacing the text there (a tail included); joints are
  untouched (text_wins). With `tag` not `None` each written cell's tag becomes `tag`;
  otherwise tags are kept. The extent grows to cover every written cell. Then the
  row is mended (no_orphan_half): a wide pair the written columns cover only in part
  has its other column become `Cell(" ", 1, s)`, `s` the pair's style. Empty `cells`
  write nothing and leave the extent as it was. The cells are written as given: a
  wide head given without its tail (or a tail without its head) is mended like any
  other half pair, so the texts stay well formed whatever is given. On a `Kept`, row
  `y` is dirty when what it draws changed.
- `texts(canvas, y) -> dict[int, tuple[Cell | None, Hashable | None]]` (what
  [Sprites]' `overlay` reads before and after its label): row `y`'s `(text, tag)` by
  column `x`, for every column of that row holding a text or a tag (either may be
  `None` when only the other is there). A new `dict` the caller owns (writing it
  never reaches the canvas). Any int `y`; a row outside the canvas (negative, or at
  or past `height`) gives `{}`. Joints are left out (an overlay is text). Reads only.
- `restore(canvas, cells, extent) -> None` (what [Sprites]' `undo` writes through):
  for each `((x, y), text, tag)` of `cells` (an iterable, applied in order), the
  text at `(x, y)` becomes `text` (a Text `Cell`, or `None`, which removes it) and
  the tag becomes `tag` (hashable, or `None`, which removes it); joints are never
  touched. Then the extent becomes exactly `extent`, a `(width, height)` pair of
  ints >= 0: it may shrink (the one exception to "the extent only grows": the
  record a restore is given holds the extent from before the writes it undoes). No
  mend: `cells` is a record of a well-formed state taken by `texts`, and putting it
  back restores that state (Sprites' undo_exact). On a `Kept` the rows written are
  tracked as any write's, so a restore that puts a row back as it was at the last
  `rows` call leaves it clean.
  Errors (all checked before any write, so on an error the canvas is unchanged):
  `place`: `TypeError` when `canvas` is not a `Canvas`, `x` / `y` is not an `int` (a
  `bool` included), `cells` is not a `tuple`, an item of it is not a Text `Cell`, or
  `tag` is unhashable; `ValueError` for a negative `x` or `y`. `texts`: `TypeError`
  when `canvas` is not a `Canvas` or `y` is not an `int`. `restore`: `TypeError`
  when `canvas` is not a `Canvas`, a cell is not a pair of ints, a text is neither
  a `Cell` nor `None`, a tag is unhashable, or `extent` is not a pair of ints;
  `ValueError` for a negative coordinate or extent.

The query readers and writer (Q11: the one public way [Query] reads a canvas back and
recolours it in place; Query touches none of a `Canvas`'s private fields or methods,
`_read`, `_write`, `_texts`, `_joints`, `_tags` included). Module-level, as the texts
writers are. Existing names first: two are reused, two are new.
- `texts(canvas, y)` (above), reused: Query's `at` takes a cell's text and tag from
  its row's `texts`; `drawn` takes the columns holding a text, and `box` the tags,
  from `texts(canvas, y)` for each `y` in `0 .. height - 1`. Every cell any op here
  writes lies inside the extent (the extent covers every cell written; `restore`
  puts back an extent recorded with its cells), so those rows hold every cell.
- `joints(canvas, y) -> dict[int, Joint]` (new): row `y`'s strokes by column: the
  [Junctions] `Joint` (mask, weight, style) of every column `x` of that row holding
  one. A new `dict` the caller owns (writing it never reaches the canvas). Any int
  `y`; a row outside the canvas (negative, or at or past `height`) gives `{}`. Texts
  and tags are left out (they are `texts`'). Reads only. Query's `at` takes a cell's
  joint from it, and `drawn` the columns holding a joint (with `texts`, row by row as
  above). Errors: `TypeError` when `canvas` is not a `Canvas` or `y` is not an `int`
  (a `bool` included).
- `repaint(canvas, x, y, style) -> bool` (new; what Query's `restyle` writes a
  joint's style through): when `(x, y)` holds a joint `j`, it becomes `Joint(j.mask,
  j.weight, style)` (arms and weight unchanged, never joined: the style is
  replaced, whatever the weights' ranks), and `True` is returned; otherwise nothing
  is written and `False` is returned. Any int `x`, `y`: a cell outside the canvas
  (negative, or past its extent) holds no joint, so `False`. `style` is any value.
  Texts, tags and the extent are untouched. On a `Kept`, row `y` is dirty when what
  it draws changed (a style `==` to the old one leaves it clean). Errors (checked
  before any write, so on an error the canvas is unchanged): `TypeError` when
  `canvas` is not a `Canvas` or `x` / `y` is not an `int` (a `bool` included).
- `place(canvas, x, y, cells)` (above), reused: Query's `restyle` writes a text's
  style through it, `tag` left `None` so the tags are kept: a narrow text at `x` as
  `place(canvas, x, y, (Cell(t.glyph, 1, style),))`; a wide pair (from its head or its
  tail) as `place(canvas, h, y, (Cell(g, 2, style), Cell("", 0, style)))` at its head
  `h`, so the pair keeps one style, stays whole (the mend changes nothing) and the
  extent, which already covers it, is unchanged.
Cost: `at` reads two rows (`texts` and `joints` of its `y`) for one cell, so it is
linear in that row's cells; `drawn` and `box` are linear in the cells and the height.

The package's check toolkit (distance-2's family-toolkit rule): `_check_canvas`,
`_pair` and `_cell` are hosted here and imported by Labels, Plot, Sprites and Query
(as `_check_int`, `_check_mask` and `_check_weight` are by [Junctions]). They check
arguments only and read no canvas state; they stay private to the package.

Drawing rows (`Canvas.rows(charset, *, rounded=False) -> tuple[Line, ...]`, the
{Rows}): `height` Text `Line`s, line `y` for row `y`. A cell DRAWS as:
- a text: a head or a narrow text, its glyph in its style; a tail adds nothing (its
  head's glyph covers both columns);
- else a joint: `glyph(j.mask, j.weight, charset, rounded=rounded)` ([Junctions]) in
  `j.style`, or `" "` in `j.style` when that glyph is `""`;
- else nothing (undrawn).
Line `y` covers columns `0` to the last column of row `y` that draws (a text or a
joint; a drawn `" "` counts), each undrawn column before it a `" "` in style `None`;
it is in Text's normal form (`merge`: adjacent runs with `==` styles joined, the first
style object kept; Colours keep their roles, so two roles never merge). A row that
draws nothing is `Line()`. So trailing undrawn columns are cut and the lines are not
padded to `width`. Buffer's `Rows(lines)` and `Rows.of(lines)` take the result as it
is (each item a {Line}).
`rounded=True` draws light corners with the `border.rounded.*` tokens (╭╮╰╯).
`charset` is any object with `glyph(token: str) -> str` ([Charset]'s {Charset}).

The {Kept} canvas (`Kept`, a subclass of `Canvas`, made by `keep`). Everything a
`Canvas` does, with the same results (kept_same), plus:
- `dirty -> frozenset[int]`: the rows `y < height` whose cells (texts or joints; not
  tags) differ from what they held at the last `rows` call, and the rows that did
  not exist then (`y >=` the height at that call). Before its first `rows` call,
  every row `0 .. height - 1`. Right after a `rows` call, empty. A change undone
  before the next `rows` call (a sprite's overlay and its undo) leaves its rows
  clean: the idle frame is silent.
- `rows(charset, *, rounded=False)`: as `Canvas.rows`; only the dirty rows are worked
  out again when `charset` is the same object (`is`) and `rounded` the same as at the
  last call (else every row is).
- `splice(other, ys) -> None`: the rows `ys` (an iterable of ints >= 0) replaced by
  the same rows of `other` (a canvas, a drawing whose rows `ys` are right; the rest of
  it may be anything): every joint, text and tag of row `y` is dropped, then `other`'s
  cells of row `y` are copied in (all three layers). The extent grows to cover what
  is copied, never shrinks.
- `patch(other, cells) -> None`: `splice` by the cell: each of `cells` takes
  `other`'s joint, text and tag there (or none, for each `other` lacks), then any
  half pair this leaves follows no_orphan_half (the orphan becomes a blank in its
  style). For a wide row of many elements, a few of which changed.

Invariant: kept_same — a `Kept` draws exactly as a plain canvas holding the same
  cells: after any sequence of the ops here and in [Labels], [Plot] and [Sprites],
  `k.rows(cs, rounded=r) == k.copy().rows(cs, rounded=r)` for every `k` and charset.

- `keep(canvas) -> Kept` ({Canvas} => {Kept}, for Memo): a new `Kept` `==` to
  `canvas` and independent of it (later writes to either never reach the other);
  `canvas` is unchanged. `keep` of a `Kept` is a new `Kept` too. Its `dirty` is every
  row.

Inputs: `stroke`: a canvas, a [Junctions] `Path`, `hops` `None` or an iterable of
  cells, `fixed` an iterable of cells, `tag` hashable or `None`. `stub`: a cell, an
  int mask, a weight, a style. `blit`: two canvases and ints. `extend`: ints.
  `rows`: a charset, a bool. `splice` / `patch`: a canvas and ints / cells. `place`,
  `texts`, `restore`: as stated under The texts writers; `joints`, `repaint`: as
  stated under The query readers and writer.
Outputs: `stroke`: `frozenset` of cells. `rows`: `tuple[Line, ...]` ({Rows}). `keep`:
  {Kept}. `copy`: {Canvas}. `texts`: a `dict` of column -> `(text, tag)`. `joints`:
  a `dict` of column -> `Joint`. `repaint`: `bool`. The other writes return `None`.
Errors: `TypeError` when `canvas` / `other` is not a `Canvas`, `path` is not a `Path`,
  a coordinate or a mask is not an `int` (a `bool` included), or a cell is not a pair
  of ints; `ValueError` for a negative coordinate, a mask outside 1..15, a weight not
  in `WEIGHTS`, `w < 0` or `h < 0`, or `other is canvas` (`blit`, `splice`,
  `patch`). `rows` raises what `charset.glyph` raises (`AttributeError` when it has
  none). `place`, `texts`, `restore`: as stated under The texts writers; `joints`,
  `repaint`: as stated under The query readers and writer. On an error the canvas is
  unchanged.
Effects: only the stated in-place writes to the canvas argument. No I/O.

Usage:
    from cure.draw.canvas import Canvas, Path, stroke, label, keep
    from cure.draw.theme.charset import ASCII, Charset
    cs = Charset()
    c = Canvas()
    stroke(c, Path([(0, 0), (4, 0), (4, 2), (0, 2), (0, 0)]))
    [l.plain for l in c.rows(cs)]            # ["┌───┐", "│   │", "└───┘"]
    v = Canvas()
    stroke(v, Path([(2, 0), (2, 2)]))
    stroke(v, Path([(0, 1), (4, 1)]))        # frozenset({(0, 1), (1, 1), (3, 1), (4, 1)})
    v.rows(cs)[1].plain                      # "──│──": a hop-over
    stroke(v, Path([(0, 1), (4, 1)], "heavy"), hops=())
    v.rows(cs)[1].plain                      # "━━╋━━": joined, the heavy weight wins
    d = Canvas()
    stroke(d, Path([(0, 0), (3, 0), (3, 2), (0, 2)], "dashed"))
    stroke(d, Path([(5, 0), (5, 2), (7, 2)], "heavy-dashed"))
    stroke(d, Path([(1, 1), (1, 2)], "dotted"))   # its end at (1, 2) tees into dashed
    [l.plain for l in d.rows(cs)]            # ["╌╌╌┐ ╏", " ┆ ╎ ╏", "╌┴╌┘ ┗╍╍"]
    [l.plain for l in d.rows(Charset("ascii", ASCII))]   # ["---+ |", " | | |", "-+-+ +--"]
    h = Canvas()
    stroke(h, Path([(2, 0), (2, 2)], "dotted"))
    stroke(h, Path([(0, 1), (4, 1)], "dashed"))
    h.rows(cs)[1].plain                      # "╌╌┆╌╌": a dashed run hops a dotted line
    stroke(h, Path([(0, 1), (4, 1)], "heavy-dashed"), hops=())
    h.rows(cs)[1].plain                      # "╌╌╋╌╌": the dashed cells keep their
                                             # weight (equal rank, first kept); the
                                             # crossing goes heavy-dashed (over dotted)
    k = keep(c)
    k.rows(cs); k.dirty                      # frozenset()
    label(k, 1, 1, "hi"); k.dirty            # frozenset({1})
"""

from collections.abc import Iterable, Hashable
from operator import itemgetter

from cure.core.text import Cell, Line, Span

from .junctions import RANK, E, N, S, W, Joint, Path, _check_int, _check_mask, _check_weight, glyph, join, link

_KEEP = object()


class Canvas:
    """{Canvas}: a drawing as sparse joints, texts and tags, with an extent (mutable)."""

    def __init__(self) -> None:
        self._joints: dict = {}
        self._texts: dict = {}
        self._tags: dict = {}
        self._w = 0
        self._h = 0

    @property
    def width(self) -> int:
        """`max(x) + 1` over every cell written or extended to, 0 for none."""
        return self._w

    @property
    def height(self) -> int:
        """`max(y) + 1` over every cell written or extended to, 0 for none."""
        return self._h

    def extend(self, w: int, h: int) -> None:
        """Grow the extent to at least `w` x `h`; nothing is drawn."""
        _check_int(w, "w")
        _check_int(h, "h")
        if w < 0 or h < 0:
            raise ValueError(f"extent must be >= 0, got {w} x {h}")
        self._w, self._h = max(self._w, w), max(self._h, h)

    def copy(self) -> "Canvas":
        """A new, independent plain Canvas equal to this one."""
        out = Canvas()
        out._load(self)
        return out

    def rows(self, charset: object, *, rounded: bool = False) -> "tuple[Line, ...]":
        """One Text Line per row, glyphs from `charset`, text over strokes (see the module)."""
        glyphs: dict = {}   # Speed: a (mask, weight)'s glyph asked once per call
        return tuple(self._row(y, charset, rounded, glyphs) for y in range(self._h))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Canvas):
            return NotImplemented
        return (self._joints == other._joints and self._texts == other._texts
                and self._tags == other._tags and (self._w, self._h) == (other._w, other._h))

    __hash__ = None

    def _load(self, other: "Canvas") -> None:
        for name in ("_joints", "_texts", "_tags"):
            setattr(self, name, {y: dict(row) for y, row in getattr(other, name).items()})
        self._w, self._h = other._w, other._h

    def _read(self, x: int, y: int) -> tuple:
        """(text, joint, tag) at (x, y), each None when absent."""
        return tuple(layer.get(y, {}).get(x) for layer in (self._texts, self._joints, self._tags))

    def _write(self, x: int, y: int, *, text: object = _KEEP, joint: object = _KEEP, tag: object = _KEEP) -> None:
        """Set the layers named at (x, y); None removes. Never grows the extent."""
        for layer, value in ((self._texts, text), (self._joints, joint), (self._tags, tag)):
            if value is _KEEP:
                continue
            _put(layer, x, y, value)
            if layer is not self._tags:
                self._touch(y)

    def _grow(self, x: int, y: int) -> None:
        self._w, self._h = max(self._w, x + 1), max(self._h, y + 1)

    def _touch(self, y: int) -> None:
        """A row's texts or joints were written (a Kept tracks it)."""

    def _mend(self, y: int, cols: Iterable) -> None:
        """no_orphan_half around the columns `cols` of row `y`: an orphan becomes a blank."""
        near = sorted({c + d for c in cols for d in (-1, 0, 1) if c + d >= 0})
        row = self._texts.get(y, {})
        for x in near:
            t = row.get(x)
            if t is None or t.width == 1:
                continue
            if t.width == 2:
                tail = row.get(x + 1)
                whole = tail is not None and tail.width == 0 and tail.style == t.style
            else:
                head = row.get(x - 1)
                whole = head is not None and head.width == 2 and head.style == t.style
            if not whole:
                self._write(x, y, text=Cell(" ", 1, t.style))
                row = self._texts.get(y, {})

    def _row(self, y: int, charset: object, rounded: bool, glyphs: "dict | None" = None) -> Line:
        """Row y drawn. Speed: the runs are built directly, each `(text, style)` run the
        cells in a row whose style `==` its first cell's (that object kept), empty glyphs
        and tails adding nothing: `merge` of a span per cell, run for run. `glyphs` holds
        the glyph of each `(mask, weight)` already asked in this `rows` call (`rows`'
        own, dropped at its return)."""
        texts, joints = self._texts.get(y, {}), self._joints.get(y, {})
        if not texts and not joints:
            return Line()
        if glyphs is None:
            glyphs = {}
        spans = []
        parts: list = []
        style = None
        for x in range(max(max(texts, default=-1), max(joints, default=-1)) + 1):
            t = texts.get(x)
            if t is not None:
                if not t.width:
                    continue
                g, s = t.glyph, t.style
            else:
                j = joints.get(x)
                if j is None:
                    g, s = " ", None
                else:
                    key = (j.mask, j.weight)
                    g = glyphs.get(key)
                    if g is None:
                        g = glyphs[key] = glyph(j.mask, j.weight, charset, rounded=rounded) or " "
                    s = j.style
            if not g:
                continue
            if parts and style == s:
                parts.append(g)
            else:
                if parts:
                    spans.append(Span("".join(parts), style))
                parts, style = [g], s
        if parts:
            spans.append(Span("".join(parts), style))
        return Line(tuple(spans))

    def _state(self, y: int) -> tuple:
        """Row y's texts and joints, as they draw (tags left out)."""
        return dict(self._texts.get(y, {})), dict(self._joints.get(y, {}))


class Kept(Canvas):
    """{Kept}: a canvas kept from frame to frame; rows worked out again only where cells changed."""

    def __init__(self) -> None:
        super().__init__()
        self._touched: set = set()
        self._seen: dict = {}
        self._seen_h = 0
        self._lines: list = []
        self._drawn_with: tuple = (None, None)

    @property
    def dirty(self) -> "frozenset[int]":
        """The rows whose cells changed since the last `rows` call (see the module)."""
        changed = {y for y in self._touched
                   if y < min(self._h, self._seen_h) and self._state(y) != self._seen.get(y, ({}, {}))}
        return frozenset(changed | set(range(self._seen_h, self._h)))

    def rows(self, charset: object, *, rounded: bool = False) -> "tuple[Line, ...]":
        """As Canvas.rows, reworking only the dirty rows (see the module)."""
        old_charset, old_rounded = self._drawn_with
        same = old_charset is charset and old_rounded == rounded and self._lines
        rework = self.dirty if same else range(self._h)
        lines = (self._lines + [None] * self._h)[:self._h]
        glyphs: dict = {}   # Speed: a (mask, weight)'s glyph asked once per call
        for y in rework:
            lines[y] = self._row(y, charset, rounded, glyphs)
        for y in rework:
            self._seen[y] = self._state(y)
        for y in [y for y in self._seen if y >= self._h]:
            del self._seen[y]
        self._lines, self._drawn_with = lines, (charset, rounded)
        self._touched.clear()
        self._seen_h = self._h
        return tuple(lines)

    def splice(self, other: Canvas, ys: "Iterable[int]") -> None:
        """Rows `ys` replaced by the same rows of `other` (see the module)."""
        _check_other(self, other)
        ys = list(ys)
        for y in ys:
            _check_int(y, "row")
            if y < 0:
                raise ValueError(f"rows must be >= 0, got {y}")
        for y in ys:
            for mine, theirs in ((self._joints, other._joints), (self._texts, other._texts),
                                 (self._tags, other._tags)):
                mine.pop(y, None)
                if y in theirs:
                    mine[y] = dict(theirs[y])
                    self._grow(max(theirs[y]), y)
            self._touch(y)

    def patch(self, other: Canvas, cells: "Iterable[tuple[int, int]]") -> None:
        """Each of `cells` replaced by `other`'s cell there (see the module)."""
        _check_other(self, other)
        cells = [_cell(c) for c in cells]
        by_row: dict = {}
        for x, y in cells:
            text, joint, tag = other._read(x, y)
            self._write(x, y, text=text, joint=joint, tag=tag)
            if (text, joint, tag) != (None, None, None):
                self._grow(x, y)
            by_row.setdefault(y, []).append(x)
        for y, xs in by_row.items():
            self._mend(y, xs)

    def _touch(self, y: int) -> None:
        self._touched.add(y)


def keep(canvas: Canvas) -> Kept:
    """A new Kept canvas equal to `canvas`, independent of it (see the module)."""
    _check_canvas(canvas)
    out = Kept()
    out._load(canvas)
    return out


def stroke(canvas: Canvas, path: Path, *, hops: "Iterable[tuple[int, int]] | None" = None,
           fixed: "Iterable[tuple[int, int]]" = frozenset(), tag: "Hashable | None" = None) -> "frozenset[tuple[int, int]]":
    """Lay `path`'s masks into the canvas, hopping straight crossings (see the module)."""
    _check_canvas(canvas)
    if not isinstance(path, Path):
        raise TypeError(f"expected a Path, got {type(path).__name__}")
    fixed = {_cell(c) for c in fixed}
    if hops is None:
        cells = link(path).cells
        skip = _hops(canvas, cells)
        if skip:
            cells = tuple(item for item in cells if item[0] not in skip)
    else:
        cells = link(path, {_cell(c) for c in hops}).cells
    _lay(canvas, cells, path.weight, path.style, fixed, tag)
    return frozenset(map(_CELL, cells))


_CELL = itemgetter(0)   # a `(cell, mask)` item's cell


def _lay(canvas: Canvas, cells: tuple, weight: str, style: object, fixed: set, tag: object) -> None:
    """`stroke`'s step 2: each `(cell, mask)` joined into the canvas, in order. Speed:
    `join`'s rule applied directly (its checks hold for every cell: the weight is the
    Path's, checked once; every mask from `link` is 1..15), the joints and tags written
    in place, `_touch` per row; a `Joint` of this stroke's weight and style made once
    per mask (Joints are values); a cell holding anything but a `Joint` goes through
    `join` itself, so its error is `join`'s. The extent covers every cell laid, even
    when a cell raises part way."""
    if not cells:
        return
    _check_weight(weight)
    rank = RANK[weight]
    layer, tags, touch = canvas._joints, canvas._tags, canvas._touch
    made: dict = {}
    w = h = 0
    last = row = None
    try:
        for cell, mask in cells:
            x, y = cell
            if y != last:
                row = layer.get(y)
                if row is None:
                    row = layer[y] = {}
                touch(y)
                last = y
            old = row.get(x)
            if old is None:
                j = made.get(mask)
                if j is None:
                    j = made[mask] = Joint(mask, weight, style)
            elif old.__class__ is Joint:
                m = old.mask | mask
                if rank > RANK[old.weight] and cell not in fixed:
                    j = made.get(m)
                    if j is None:
                        j = made[m] = Joint(m, weight, style)
                elif m == old.mask:
                    j = old
                else:
                    j = Joint(m, old.weight, old.style)
            else:
                j = join(old, mask, weight, style, fixed=cell in fixed)
            row[x] = j
            if tag is not None:
                tags.setdefault(y, {})[x] = tag
            if x >= w:
                w = x + 1
            if y >= h:
                h = y + 1
    finally:
        if w:
            canvas._w, canvas._h = max(canvas._w, w), max(canvas._h, h)


def stub(canvas: Canvas, cell: "tuple[int, int]", mask: int, weight: str = "light",
         style: object = None, *, tag: "Hashable | None" = None) -> None:
    """Half a link: arms `mask` at `cell`, joined as a stroke (see the module)."""
    _check_canvas(canvas)
    x, y = _cell(cell)
    _check_mask(mask, low=1)
    _check_weight(weight)
    canvas._write(x, y, joint=join(canvas._read(x, y)[1], mask, weight, style))
    if tag is not None:
        canvas._write(x, y, tag=tag)
    canvas._grow(x, y)


def blit(canvas: Canvas, other: Canvas, x: int, y: int) -> None:
    """Copy `other` in at (x, y), replacing what it has there (see the module)."""
    _check_other(canvas, other)
    x, y = _cell((x, y))
    for name in ("joint", "text", "tag"):
        layer = {"joint": other._joints, "text": other._texts, "tag": other._tags}[name]
        for cy, row in layer.items():
            for cx, value in row.items():
                canvas._write(x + cx, y + cy, **{name: value})
    for cy, row in other._texts.items():
        canvas._mend(y + cy, [x + cx for cx in row])
    if other._w and other._h:
        canvas._grow(x + other._w - 1, y + other._h - 1)


def place(canvas: Canvas, x: int, y: int, cells: "tuple[Cell, ...]", *,
          tag: "Hashable | None" = None) -> None:
    """Write `cells` into the texts from (x, y), tagging them; then mend the row (see The texts writers)."""
    _check_canvas(canvas)
    if not (type(x) is int and type(y) is int and x >= 0 and y >= 0):   # the common case, checked fast
        x, y = _cell((x, y))
    if not isinstance(cells, tuple):
        raise TypeError(f"cells must be a tuple of Cells, got {type(cells).__name__}")
    for c in cells:
        if type(c) is not Cell and not isinstance(c, Cell):
            raise TypeError(f"a cell must be a Cell, got {type(c).__name__}")
    if tag is not None:
        _check_tag(tag)
    if not cells:
        return
    texts = canvas._texts.setdefault(y, {})
    for i, c in enumerate(cells):
        texts[x + i] = c
    if tag is not None:
        tags = canvas._tags.setdefault(y, {})
        for i in range(len(cells)):
            tags[x + i] = tag
    canvas._touch(y)
    canvas._grow(x + len(cells) - 1, y)
    canvas._mend(y, range(x, x + len(cells)))


def texts(canvas: Canvas, y: int) -> "dict[int, tuple[Cell | None, Hashable | None]]":
    """Row y's (text, tag) by column, for the columns holding either; a new dict (see The texts writers)."""
    _check_canvas(canvas)
    _check_int(y, "row")
    row, tags = canvas._texts.get(y, {}), canvas._tags.get(y, {})
    return {x: (row.get(x), tags.get(x)) for x in row.keys() | tags.keys()}


def restore(canvas: Canvas, cells: "Iterable[tuple[tuple[int, int], Cell | None, Hashable | None]]",
            extent: "tuple[int, int]") -> None:
    """Put recorded texts and tags back, then set the extent exactly (see The texts writers)."""
    _check_canvas(canvas)
    record = []
    for item in cells:
        if not isinstance(item, (tuple, list)) or len(item) != 3:
            raise TypeError(f"a record is a ((x, y), text, tag) triple, got {item!r}")
        cell, text, tag = item
        if text is not None and type(text) is not Cell and not isinstance(text, Cell):
            raise TypeError(f"a text must be a Cell or None, got {type(text).__name__}")
        if tag is not None:
            _check_tag(tag)
        if not (type(cell) is tuple and len(cell) == 2 and type(cell[0]) is int and type(cell[1]) is int
                and cell[0] >= 0 and cell[1] >= 0):
            cell = _cell(cell)
        record.append((cell, text, tag))
    w, h = _cell(extent)
    texts, tags = canvas._texts, canvas._tags
    for (x, y), text, tag in record:
        _put(texts, x, y, text)
        _put(tags, x, y, tag)
        canvas._touch(y)
    canvas._w, canvas._h = w, h


def joints(canvas: Canvas, y: int) -> "dict[int, Joint]":
    """Row y's joints by column; a new dict (see The query readers and writer)."""
    _check_canvas(canvas)
    _check_int(y, "row")
    return dict(canvas._joints.get(y, {}))


def repaint(canvas: Canvas, x: int, y: int, style: object) -> bool:
    """The joint at (x, y) takes `style`, mask and weight kept; False when there is none (see The query readers and writer)."""
    _check_canvas(canvas)
    x, y = _pair((x, y))
    joint = canvas._joints.get(y, {}).get(x)
    if joint is None:
        return False
    canvas._write(x, y, joint=Joint(joint.mask, joint.weight, style))
    return True


def _put(layer: dict, x: int, y: int, value: object) -> None:
    if value is None:
        row = layer.get(y)
        if row is not None:
            row.pop(x, None)
            if not row:
                del layer[y]
    else:
        layer.setdefault(y, {})[x] = value


def _hops(canvas: Canvas, cells: tuple) -> set:
    """The hop rule: straight cells of the path (its `link` cells, sorted by row) over an
    exactly perpendicular straight joint."""
    out = set()
    layer = canvas._joints
    last = row = None
    for cell, mask in cells:
        x, y = cell
        if y != last:
            row, last = layer.get(y), y
        if row is None:
            continue
        joint = row.get(x)
        if joint is None:
            continue
        held = joint.mask   # read for every joint the path meets, as `join` would be
        if (mask == _H and held == _V) or (mask == _V and held == _H):
            out.add(cell)
    return out


_H, _V = E | W, N | S


def _check_canvas(canvas: object, name: str = "canvas") -> None:
    if not isinstance(canvas, Canvas):
        raise TypeError(f"{name} must be a Canvas, got {type(canvas).__name__}")


def _check_other(canvas: object, other: object) -> None:
    _check_canvas(canvas)
    _check_canvas(other, "other")
    if other is canvas:
        raise ValueError("other must not be the canvas itself")


def _check_tag(tag: object) -> None:
    try:
        hash(tag)
    except TypeError:
        raise TypeError(f"a tag must be hashable, got {type(tag).__name__}") from None


def _pair(cell: object) -> "tuple[int, int]":
    """A cell as an (x, y) pair of ints, any sign."""
    if not isinstance(cell, (tuple, list)) or len(cell) != 2:
        raise TypeError(f"a cell is an (x, y) pair of ints, got {cell!r}")
    for v in cell:
        _check_int(v)
    return tuple(cell)


def _cell(cell: object) -> "tuple[int, int]":
    """A cell to write: an (x, y) pair of ints >= 0."""
    x, y = _pair(cell)
    if x < 0 or y < 0:
        raise ValueError(f"coordinates must be >= 0, got {(x, y)}")
    return x, y
