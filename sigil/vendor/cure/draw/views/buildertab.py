"""[BuilderTab]: one builder: its terminal, its worktree, its env, its phase's progress.

Kind: service (pure functions from a {Builder} to widget nodes; see the Views package
for the tab protocol every tab follows and the `TabView` the package builds from it).

What it does: construct's tab for one builder. Two panes: `"terminal"`, the builder's
terminal (a Widgets `Pane` over the screen the {Builder} holds, or a placeholder
before its first frame), and `"info"`, its status, task, worktree and env as
key:value rows (Widgets `PropertyList`s), with its phase as a Progress beside the
phase word between them (a Widgets `Gauge` with progress, a `Spinner` while working
without; neither: the pane as before). It composes existing widget nodes only and
paints nothing itself; it reads no file and touches no process (the screen is
construct's, run through Embed and Vt on its side).

The tab's key: `key(builder) == ("builder", builder.id)`, written `k` below. Every
id a node of this tab carries is `k + (part,)`, as listed; no other node carries one.

The panes (`views(builder) -> dict`), in this order:
- `"terminal"`: `terminal(builder)`:
  `Block((child,), title=T, kind="pane", id=k + ("terminal",))` with every other
  Block field its default, where `T == builder.id` when `builder.task is None`, else
  `f"{builder.id}: {builder.task}"`, and `child`:
  - with a screen: `Pane(builder.screen, cursor=builder.cursor, id=k + ("screen",))`
    (the app focuses `k + ("screen",)` to send the terminal keys: the Pane then
    gives `cursor_at`, and the Block, the focus pane, lifts);
  - with `screen is None`: `Paragraph(PLACEHOLDER, role="muted")` (no id),
    `PLACEHOLDER == "no screen yet"`.
- `"info"`: `info(builder)`:
  `Block((PropertyList(facts, size=Fixed(4)), PropertyList(env)), title="info",
  kind="pane", id=k + ("info",))` (Layout's `Fixed`; the Block's default Column layout) when
  `progress(builder) is None`, else `Block((PropertyList(facts, size=Fixed(4)), p,
  PropertyList(env)), title="info", kind="pane", id=k + ("info",))` with `p ==
  progress(builder)`
  (one row under the facts; the env list, `size=None`, takes the rest), where
  `facts` is, in order (Widgets' `Item(key, value, state)`, no ids):
  - `Item("status", s, TONES[builder.status])`, `s` being `builder.status`, or
    `f"{builder.status} ({builder.phase})"` when the phase is not `""`;
  - `Item("task", builder.task or "none")`;
  - `Item("worktree", builder.worktree or "none")`;
  - `Item("env", n)`: `n` is `"none"` for no pairs, `"1 name"` for one, else
    `f"{len(builder.env)} names"`;
  and `env == tuple(Item(name, value) for name, value in builder.env)` (`()` for
  none: an empty list draws only its ground).

The phase widget (`progress(builder) -> Gauge | Spinner | None`), the first that
applies (Widgets' Progress kinds, every field not named its default, no id):
- `builder.progress == (s, t)`: `Gauge(s / t, label=L, size=Fixed(1))`, `L ==
  f"{builder.phase} {s}/{t}"`, or `f"{s}/{t}"` when the phase is `""` (the phase
  word beside the bar; Gauge adds the percentage after it);
- else `builder.status == "working"`: `Spinner("dots", label=builder.phase or
  "working", size=Fixed(1))` (its frame is Paint's, from `ctx.now` alone: the tab
  reads no clock);
- else `None`.
BuilderGrid's cells restate it (no tab imports another).

The default tree (`tree() -> SplitTree`): `SplitTree(Split("x", (Pane("terminal"),
Pane("info")), (3, 1)))` (Layout's Splits: the terminal three quarters, the info a
quarter). The titles (`titles(builder) -> dict`): `{"terminal": builder.id, "info":
"info"}` (Paint's `Tiled` shows them only on a Tabs or Stacked bar, should the app
regroup the panes).

Status tones: `TONES` maps every {Builder} status to the Theme state its status row
is drawn in (PropertyList's item `state`): `"starting"`: `None`, `"working"`:
`"active"`, `"waiting"`: `"emphasised"`, `"passed"`: `"muted"`, `"failed"`:
`"emphasised"`. The keys are exactly Board's `BUILDER_STATES`.

Laws (each a property a test can loop over builders, sizes and contexts):
- pure: `views(b) == views(b)` and `terminal`, `info`, `progress`, `tree`, `titles`
  likewise, for equal builders `b`; nothing is read but the argument (no clock, no
  file, no process, no state of the module's own).
- ids: the ids carried in `views(b)` (every node reached through `children`, Tabs'
  bodies included) are exactly `{k + ("terminal",), k + ("info",)}`, plus `k +
  ("screen",)` when `b.screen is not None` (the phase widget carries none).
- tiles: `set(views(b)) == set(ids(tree())) == set(titles(b)) == {"terminal",
  "info"}` (Layout's `ids`), so the package's `TabView` accepts them.
- frames: for every size `(w, h)`, `1 <= w <= 120`, `1 <= h <= 40`, Paint's
  `frame(Tiled(tree(), views(b), titles(b)), (w, h), ctx)` returns a Frame (never
  raises), for every valid {Builder} (with and without progress, every status) and
  the builtin theme at every depth.
- unchanged: for a builder with `progress is None` and a status other than
  `"working"`, `views(b)` equals what the commit before X5 gives (the code at
  62d91e8, a git oracle loaded with `git archive` at test time), `kind` aside (R2:
  the Blocks' `kind="pane"` is left out of the comparison, the old Block having
  none), and so its frames, cell for cell, at every size and context above.
- kinds (R2): both pane Blocks are of kind `"pane"`; the frames equal 74f1f6a's
  (Views' kind-inert law).
- stable: a frame at a fixed `ctx.now` is the same every time it is drawn (the
  spinner's frame is `ctx.now`'s alone; the gauge has no phase of its own).
- legible: with colour off (Caps depth 0), the status row still reads: the status
  word is drawn whenever the info pane shows its first row whole, and a status with a
  tone shows that state's mark in the row's last leader cell (Theme's States: the
  treatment's floor flag on the text), as PropertyList draws it. The phase widget
  reads too, whenever its row is drawn whole: a gauge by its glyphs (`block.full`,
  the eighths and `block.light` differ in glyph, not only in colour) and its label
  word (`L`, with the step of the total), a spinner by its frame glyph and its word
  (the phase, or `"working"`).
- screen: with a screen, the terminal pane's Pane holds the very `Grid` object the
  builder holds (not a copy), so a frame shows the screen's cells as they are then.

Inputs: `builder` a Board {Builder}.
Outputs: widget nodes (Widgets' Block, Pane, Paragraph, PropertyList, Gauge,
  Spinner), or `None` (`progress`); a `dict` of them by pane id; a Layout
  `SplitTree`; a `dict` of titles.
Errors: `TypeError` when `builder` is not a Board `Builder` (`"builder must be a
  Builder, got <type name>"`). The nodes are built from checked data, so their own
  construction never fails.
Effects: none.

Usage:
    from cure.core.buffer import Grid
    from cure.draw.views.board import Builder
    from cure.draw.views import buildertab
    b = Builder("b1", task="X1", worktree="../wt/b1", status="working", screen=Grid(80, 24))
    buildertab.terminal(b).title          # "b1: X1"
    buildertab.views(b)["info"].id        # ("builder", "b1", "info")
    buildertab.tree()                     # SplitTree(Split("x", (Pane("terminal"), Pane("info")), (3, 1), (0, 0)))
    buildertab.progress(b)                # Spinner("dots", label="working", size=Fixed(1))
    p = Builder("b1", status="working", phase="proofs", progress=(3, 4))
    buildertab.progress(p)                # Gauge(0.75, label="proofs 3/4", size=Fixed(1))
    len(buildertab.info(p).children)      # 3: the facts, the gauge, the env
    buildertab.progress(Builder("b1"))    # None: info(...) as before X5
"""

from cure.draw.layout import Fixed, Split, SplitTree
from cure.draw.layout import Pane as Tile
from cure.draw.widgets import Block, Gauge, Item, Pane, Paragraph, PropertyList, Spinner

from .board import Builder

PANES = ("terminal", "info")
"""The tab's pane ids, in `views`' order."""

PLACEHOLDER = "no screen yet"
"""What the terminal pane says before the builder's first frame."""

TONES = {"starting": None, "working": "active", "waiting": "emphasised",
         "passed": "muted", "failed": "emphasised"}
"""A builder status's Theme state (its status row's `state`), or None."""


def key(builder: Builder) -> tuple:
    """The tab's key, `("builder", builder.id)`: every node id starts with it."""
    _check(builder)
    return ("builder", builder.id)


def terminal(builder: Builder) -> Block:
    """The terminal pane: a Block around a Pane over the screen, or the placeholder."""
    k = key(builder)
    if builder.screen is None:
        child = Paragraph(PLACEHOLDER, role="muted")
    else:
        child = Pane(builder.screen, cursor=builder.cursor, id=k + ("screen",))
    title = builder.id if builder.task is None else f"{builder.id}: {builder.task}"
    return Block((child,), title=title, kind="pane", id=k + ("terminal",))


def info(builder: Builder) -> Block:
    """The info pane: status, task, worktree and env, as key:value rows."""
    k = key(builder)
    status = builder.status if builder.phase == "" else f"{builder.status} ({builder.phase})"
    n = len(builder.env)
    names = "none" if n == 0 else "1 name" if n == 1 else f"{n} names"
    facts = (Item("status", status, TONES[builder.status]),
             Item("task", builder.task or "none"),
             Item("worktree", builder.worktree or "none"),
             Item("env", names))
    env = tuple(Item(name, value) for name, value in builder.env)
    p = progress(builder)
    phase = () if p is None else (p,)  # one row under the facts, when there is one
    return Block((PropertyList(facts, size=Fixed(4)), *phase, PropertyList(env)),
                 title="info", kind="pane", id=k + ("info",))


def progress(builder: Builder) -> "object | None":
    """The phase widget: a Gauge with progress, a Spinner while working, else None."""
    _check(builder)
    if builder.progress is not None:
        s, t = builder.progress
        label = f"{s}/{t}" if builder.phase == "" else f"{builder.phase} {s}/{t}"
        return Gauge(s / t, label=label, size=Fixed(1))
    if builder.status == "working":
        return Spinner("dots", label=builder.phase or "working", size=Fixed(1))
    return None


def views(builder: Builder) -> dict:
    """The tab's panes by id: `{"terminal": terminal(builder), "info": info(builder)}`."""
    return {"terminal": terminal(builder), "info": info(builder)}


def tree() -> SplitTree:
    """The tab's default split tree: terminal left (3), info right (1)."""
    return SplitTree(Split("x", (Tile("terminal"), Tile("info")), (3, 1)))


def titles(builder: Builder) -> dict:
    """The panes' titles: `{"terminal": builder.id, "info": "info"}`."""
    _check(builder)
    return {"terminal": builder.id, "info": "info"}


def _check(builder: object) -> None:
    """Refuse anything but a Board Builder."""
    if not isinstance(builder, Builder):
        raise TypeError(f"builder must be a Builder, got {type(builder).__name__}")
