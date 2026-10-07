# Changelog

Each release's notes, newest first. The same text is the GitHub release's description.

## 0.3.3 — 2026-10-07

Fixes from the viewer-coverage review.

- **Borrowed stores are always drawn.** A `@borrow(...)` to a store that appears in no
  flow lost its access edge, because the store never became a node. It is now placed
  where the borrow is written, so its `b` / `ƀ` edge draws in both views. lint and check
  output is unchanged.
- **Mutable streams keep their stream shape.** A `~*` stream keeps the heavy `~` box and
  gains the stream mark after its label (`┃ ~*<Raw> ≋ ┃`); the graph legend reads
  `┒┃┛ ≋ stream`.
- **Paths on the source side are labelled.** A flow out of a qualified path
  (`[Bullet]/{Transform} -> [Render]`) carries `from [Bullet]/` beside its tail, or beside
  its head when the tail shares a trunk. Legend `│ from [A]/ out of path`.
- **Role box stubs join cleanly.** Self-call stubs under a role box's double side bend
  with `╟─●` / `╙─●` instead of a light `├` under a double line.
