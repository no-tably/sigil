"""[Geometry]: rects and the hit map.

Kind: system (the expansion of [Geometry] in Core); pure. Depends on nothing: no module
of this package imports any other cure package.

Where things are: plain values the packages hand each other. {Rect} is a rectangle of
terminal cells (x, y, w, h) with intersect, inset, split, contains and moved; {HitMap}
maps rects to tags per layer, Paint writes it as a value and Input reads it (the
smallest rect of the topmost layer wins). No flow crosses this system: the values
travel as arguments.

Re-exported here: `Rect` (rect); `Hit`, `HitMap` (hitmap).

Effects: none.

Usage:
    from cure.core.geometry import Rect, HitMap
    body = Rect(0, 0, 80, 24).inset(1)               # Rect(1, 1, 78, 22)
    hits = HitMap().add(body, "body").add(Rect(2, 2, 6, 1), "ok")
    hits.at(3, 2)                                     # "ok": the smaller rect wins
"""

from .hitmap import Hit, HitMap
from .rect import Rect
