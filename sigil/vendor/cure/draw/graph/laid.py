"""{Laid}: lay's answer: the rows, each node's rect, the drawing's width and height.

Kind: data (Graph's; one module per data shape). [Diagram]'s `lay` builds it;
re-exported by Graph's package (`cure.draw.graph.Laid`) and imported by `diagram.py`
(`cure.draw.graph.diagram.Laid`), the same object.

`Laid(rows, rects, width=0, height=0)`, a frozen dataclass (its dict is not to be
mutated):
- `rows`: the drawing, one Text `Line` per canvas row ({Rows}: a Widgets `Drawing`
  takes them as they are);
- `rects`: each real node's drawn `Rect`, keyed by node id, in node order, in the rows'
  coordinates (a long edge's virtual vertices are not in it);
- `width`, `height`: the drawing's extent, set by `lay` from its Diagram (`g.width`,
  `g.height`): the widest row and the row count, so a caller that pans or clamps over
  the drawing (DagView's Drawing `extent`) never scans the rows for them. F8's memo
  hands them out with the rows. The defaults (`0`) keep older constructions
  (`Laid(rows, rects)`) working; `lay(Dag(), cs) == Laid((), {}, 0, 0)`.

A `Laid` is not a sequence of rows (not iterable, not indexable): a caller left on the
old `tuple[Line, ...]` fails at its first use. `==` compares every field.

Effects: none.

Usage:
    from cure.draw.graph import Dag, lay, sized
    from cure.draw.theme.charset import ASCII, Charset
    laid = lay(Dag([sized("a"), sized("b")], [("a", "b")]), Charset("ascii", ASCII))
    laid.width, laid.height      # the widest row, len(laid.rows)
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Laid:
    """{Laid}: a dag laid out once: its rows, each real node's rect keyed by id in node order, the drawing's width and height."""

    rows: tuple
    rects: dict
    width: int = 0
    height: int = 0
