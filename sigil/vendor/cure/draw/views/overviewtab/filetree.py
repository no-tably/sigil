"""[FileTree]: the program's code folders, marked with builder, env and status; an entry
with a note marked held; the focused entry's note at the pane's title row end.

Kind: service (pure functions from Board {Entry}s to a widget node; see the
OverviewTab package for the tab, its key `k == ("overview",)` and its ids).

What it does: the board's entries as a Widgets `Tree`, one row per entry in the order
the {Board} gives them (tree order: a folder before what it holds), each row its
name and its marks: the builder whose worktree changes it, the env it builds in, the
status of the code there, and (Q10b) `held` when something waits on it (its
{Entry}'s `note`), the mark a held task gets. Every node is open and none shows a
twisty (the tree is construct's, shown whole; the app scrolls it). A click on a row hits that entry's
path. Views never lists a directory: the entries are construct's.

The nesting (`nodes(entries) -> tuple`): the roots, a `tuple` of Widgets `TreeNode`,
from `entries` (a `tuple` of {Entry}, the Board's, in tree order). Each entry `e`'s
parent is the nearest entry before it whose `depth` is less than `e.depth`, and it
is a root when there is none (so a depth that jumps by more than one nests under
the nearest shallower entry, and the drawn depth is the nesting, not the number
given). Each entry is `TreeNode(label(e), children, open=True, expandable=False,
state=TONES[e.status] if e.status else None, id=k + ("entry", e.path))`, its
children its entries in order.

The label (`label(e) -> Line`): a Text `Line` of spans (Text's `Line.of`), in order:
- the name: the part of `e.path` after its last `/` (the whole path when it has
  none, or when that part is empty), with `"/"` after it for a folder, in style
  `None` (the row's text);
- with `e.builder`: `"  @" + e.builder` in role `"accent"`;
- with `e.env`: `"  env " + e.env` in role `"muted"`;
- with `e.status`: `"  " + e.status` in role `"muted"`;
- with a note (Q10b; `getattr(e, "note", None) is not None`): `"  " + HELD` (`HELD == "held"`, {Task}'s state word) in role
  `"task.held"` (DagView's `STYLES["held"]`: the role a held task's box is drawn in,
  an open role a theme may style, an unstyled one degrading to the row's text), so a
  waiting row reads as a held task does, by the word, in the same colour. Last, after
  the status: the marks keep Entry's field order, and an unnoted row's spans are
  exactly as before. The status still shows beside it (a note is not a state: both
  are kept as given); the note's text is not in the row (it is the title's, below).
So `"views/  @b1  env py312  building"`, and `"relay.py  held"` for a noted file with
no other mark. The marks are words: they read with colour off, and a long row is cut
by Tree with the ellipsis, never silently (the `held` mark, last, is cut first).
A note changes only the label: the node's `state` (its tone) is still `TONES` of its
status, its id and its children are as before.

The pane (`filetree(entries, *, entry=None, offset=0) -> Block`):
- with entries: `Block((Tree(nodes(entries), cursor=c, offset=offset, id=k +
  ("files", "tree")),), title=L, kind="pane", id=k + ("files",))`, where `c`
  is the index in the Tree's `flat()` of the entry whose path is `entry` (by the
  order law below, its index in `entries`), or `None` when `entry` is `None` or
  names no entry; and the title `L` is, with `N` the note of that focused entry
  (`getattr(entries[c], "note", None)`; `None` when `c` is `None`), Q10b, SpecPane's title mechanism
  with `TITLE == "files"` in place of the path and role `"task.held"` in place of
  `warn`:
  - `N is None` (no focused entry, or one without a note): `L == TITLE`, the plain
    `str`, exactly as before Q10b;
  - else: the Text Line `L == Line.of((TITLE, None), ("  ", None), (N, "task.held"))`,
    in normal form `Line((Span("files  ", None), Span(N, "task.held")))`: the title
    and a two-space gap in style `None`, which the Block draws in its `title` role,
    then the note in the theme role `task.held` (Block's `_styled`).
  The Block's title rule cuts it (bordered: the title rect is `W = R.w - 4` cells of
  the top row at `R.x + 2`, for a pane rect `R` with `R.w >= 2` and `R.h >= 2`, when the
  theme's top ends are one cell each; a wider start or end, as wire's `▛▀` since round 13,
  moves the rect in past it and `W` is that much smaller), with `n = width(N)` and `e` the width of `ctx.glyph("ellipsis")`:
  - `W >= 9 + n` (`width("files") + 2 + n + 2`): the whole label `" files  " + N + " "`, left-aligned, the rest
    of the row the border's `h` line;
  - `3 <= W < 9 + n`: `" " + cut(L, W - 2, ellipsis) + " "`: a prefix of `"files  "
    + N` and the ellipsis, styled like the first cluster cut off, so the note is cut
    first, the gap next and `"files"` only once both are gone (`"files"` is whole
    exactly when `W >= 7 + e`);
  - `W < 3`, or no border drawn: no title, with a note or without.
  The note is shown only while its entry is the focused one (`entry` names it): moving
  `entry` changes the title, never the Tree's rows (a noted row is marked `held`
  wherever the cursor is).
- with none: `Block((Paragraph(EMPTY, role="muted"),), title="files", kind="pane",
  id=k + ("files",))`, `EMPTY == "no files yet"` (no entry, so no note: as before
  Q10b, whatever `entry` is).

Status tones: `TONES` maps every {Component} status to the Theme state an entry's
row is drawn in (TreeNode's `state`): `"planned"`: `None`, `"building"`:
`"active"`, `"built"`: `None`, `"stale"`: `"emphasised"`, `"rebuilding"`:
`"active"`, `"removed"`: `"muted"`, `"pruning"`: `"active"` (Inspector's, restated:
no tab imports another). The keys are exactly Board's `COMPONENT_STATES`.

Laws (each a property a test can loop over entry tuples, cursors, offsets, sizes and
contexts):
- pure: equal arguments give equal results (`nodes`, `label`, `filetree`).
- order: one row per entry, in the order given: `[n.id for _, n in
  Tree(nodes(es)).flat()] == [k + ("entry", e.path) for e in es]` (the nesting is
  depth first in order, and every node is open).
- depth: a row's drawn depth is `e.depth` whenever every entry's depth is at most
  one more than the entry before it's (and the first's is 0).
- ids: the node ids carried are exactly `{k + ("files",), k + ("files", "tree")}`
  with entries, `{k + ("files",)}` without; the item ids are `k + ("entry", path)`,
  one per entry.
- legible: with colour off (Caps depth 0), a row's builder, env and status are its
  label's words, a noted row's `held` is a word, and a folder ends in `/`; the
  title's note is words (its `task.held` colour adds nothing the words do not say).
- held (Q10b): for an entry `e` with a note, `label(e).spans == label(replace(e,
  note=None)).spans + (Span("  held", "task.held"),)`: the note adds one span at the
  end, nothing else; without one, no span in role `task.held`.
- note (Q10b): nothing in `filetree`'s result but the Block's `title` and the
  noted rows' labels depends on any entry's `note`; ids, `cursor`, `offset`, each
  node's `state`, `open` and `expandable`, and every other Block field never do; the
  title depends only on the focused entry's note.
- note-none-unchanged (Q10b): with every entry's `note` `None`, `nodes`, `label` and
  `filetree` equal (`==`) FileTree's at the commit before Q10b (b1132a1, loaded by git
  through `tests/_gitref.py` at test time), and so do the pane's frames (Paint's
  cells and hits), for every entry tuple, cursor, offset, size and context; likewise
  with notes but `entry` naming no noted entry, for `filetree`'s Block `title`.
- layout-unchanged (Q10b): a note never moves the layout. The Block's `chrome()`
  counts a title only as `title != ""`, true with a note or without (`"files"` is
  never `""`), so Layout's BoxModel gives the same content rect and the Tree the same
  rect at every pane rect; the title's note changes only the cells of the title rect
  (row `R.y`, columns `[R.x + 2, R.right - 2)`), never a hit. Only the Block's
  `measure("x")` grows (by `2 + n`); OverviewTab never asks it (its layout is
  Splits).
- note-cut-first (Q10b): at every pane rect, the drawn title is a prefix of
  `"files  " + N` and the ellipsis (or the whole); no cell of `"files"` is dropped
  while a cell of the gap or of `N` is drawn.
- frames (Q10b): for every pane rect (`R.w`, `R.h` from 0), every valid note (one
  line, wide glyphs included, wider than the rect included) and every shelf theme,
  depth and focus, painting the pane never raises.

Inputs: `entries` a `tuple` of Board {Entry} (paths unique: the Board's check);
  `entry` `None` or a `str`; `offset` an int `>= 0` (Tree's first row shown).
Outputs: a `tuple` of Widgets `TreeNode`; a Text `Line`; a Widgets `Block` (of a
  `Tree`, or a `Paragraph`; titled `"files"`, or with the focused entry's note a Text
  `Line`).
Errors: `TypeError` when `entries` is not a `tuple`, `entry` is neither `None` nor a
  `str`, or `offset` is not an int (a `bool` refused); `ValueError` when `offset <
  0`.
  A note is not checked here (Entry checks it); an entry value other than an Entry
  is read by attribute (`path`, `depth`, `folder`, `builder`, `env`, `status`, and
  `note` when it has it: a value without one is read as `None`, so an entry value of
  before Q10b serves unchanged).
Effects: none.

Usage:
    from cure.draw.views.board import Entry
    from cure.draw.views.overviewtab import filetree
    es = (Entry("cure/draw/views", folder=True, builder="b1", status="building"),
          Entry("cure/draw/views/overviewtab", depth=1, folder=True, env="py312"),
          Entry("cure/draw/views/inspector.py", depth=1, status="built"))
    filetree.label(es[0]).plain             # "views/  @b1  building"
    [len(n.children) for n in filetree.nodes(es)]   # [2]
    filetree.filetree(es, entry="cure/draw/views/inspector.py").children[0].cursor  # 2
    held = Entry("cure/edge/relay.py", note="Q12: is this module planned?")
    filetree.label(held).spans[-1]          # Span("  held", "task.held")
    filetree.filetree((held,), entry=held.path).title
    # Line((Span("files  ", None), Span("Q12: is this module planned?", "task.held")))
    filetree.filetree((held,)).title        # "files": no focused entry
"""

from cure.core.text import Line
from cure.draw.widgets import Block, Paragraph, Tree, TreeNode

KEY = ("overview",)
"""The tab's key (OverviewTab's `k`)."""

TITLE = "files"
"""The pane's title (with the focused entry's note after it, Q10b)."""

HELD = "held"
"""A noted entry's mark: {Task}'s held state word (Q10b)."""

HELD_ROLE = "task.held"
"""The role of the held mark and the title's note: DagView's `STYLES["held"]` (Q10b)."""

EMPTY = "no files yet"
"""What the pane says when the board has no entries."""

TONES = {"planned": None, "building": "active", "built": None, "stale": "emphasised",
         "rebuilding": "active", "removed": "muted", "pruning": "active"}
"""A code status's Theme state (its row's `state`), or None."""


def label(entry: object) -> Line:
    """An entry's row: its name (a folder ending in `/`), then its builder, env, status."""
    name = entry.path.rsplit("/", 1)[-1] or entry.path
    parts = [(name + "/" if entry.folder else name, None)]
    if entry.builder:
        parts.append(("  @" + entry.builder, "accent"))
    if entry.env:
        parts.append(("  env " + entry.env, "muted"))
    if entry.status:
        parts.append(("  " + entry.status, "muted"))
    if getattr(entry, "note", None) is not None:
        parts.append(("  " + HELD, HELD_ROLE))
    return Line.of(*parts)


def nodes(entries: tuple) -> tuple:
    """The entries as Tree roots, each nested under the nearest shallower entry before it."""
    _entries(entries)
    roots, kids, stack = [], {}, []   # stack: (depth, index) of the open ancestors
    for i, e in enumerate(entries):
        while stack and stack[-1][0] >= e.depth:
            stack.pop()
        (kids.setdefault(stack[-1][1], []) if stack else roots).append(i)
        stack.append((e.depth, i))

    def made(i: int) -> TreeNode:
        e = entries[i]
        return TreeNode(label(e), tuple(made(j) for j in kids.get(i, ())), open=True,
                        expandable=False, state=TONES[e.status] if e.status else None,
                        id=KEY + ("entry", e.path))
    return tuple(made(i) for i in roots)


def filetree(entries: tuple, *, entry: "str | None" = None, offset: int = 0) -> Block:
    """The files pane: a Tree of the entries in their order, every node open."""
    _entries(entries)
    if entry is not None and not isinstance(entry, str):
        raise TypeError(f"entry must be a str or None, got {type(entry).__name__}")
    if not isinstance(offset, int) or isinstance(offset, bool):
        raise TypeError(f"offset must be an int, got {type(offset).__name__}")
    if offset < 0:
        raise ValueError(f"offset must be >= 0, got {offset}")
    if not entries:
        return Block((Paragraph(EMPTY, role="muted"),), title=TITLE, kind="pane",
                     id=KEY + ("files",))
    c = next((i for i, e in enumerate(entries) if e.path == entry), None)
    tree = Tree(nodes(entries), cursor=c, offset=offset, id=KEY + ("files", "tree"))
    note = None if c is None else getattr(entries[c], "note", None)
    title = TITLE if note is None else Line.of((TITLE, None), ("  ", None), (note, HELD_ROLE))
    return Block((tree,), title=title, kind="pane", id=KEY + ("files",))


# --- private ------------------------------------------------------------------------

def _entries(entries: object) -> None:
    if not isinstance(entries, tuple):
        raise TypeError(f"entries must be a tuple, got {type(entries).__name__}")
