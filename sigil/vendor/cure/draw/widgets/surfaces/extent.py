"""{Extent}: a Drawing's content extent (width, height), a pair.

Kind: data (Surfaces'; one module per data shape). `Extent(width: int, height: int)`,
a `NamedTuple`: `width` the widest row in cells, `height` the row count. It is a
tuple, so it equals (and hashes as) the plain pair `(width, height)` and unpacks as
one. [Drawing] holds one as its `extent`: the caller's when it knows it (Graph's `lay`
does, so DagView passes it), else counted once from the rows. Re-exported by Surfaces
and Widgets as Drawing is.

Effects: none.

Usage:
    from cure.draw.widgets.surfaces import Extent
    e = Extent(6, 3)
    e.width, e.height, e == (6, 3)   # 6, 3, True
"""

from typing import NamedTuple


class Extent(NamedTuple):
    """{Extent}: a content extent, `width` (cells) and `height` (rows)."""

    width: int
    height: int
