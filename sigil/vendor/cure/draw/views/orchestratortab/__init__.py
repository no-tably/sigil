"""[OrchestratorTab]: the orchestrator's agent, left; right: the spec over its live sigil view.

Kind: system (the composition tree rooted at [OrchestratorTab] in [Views]); pure
functions from {Board} parts and the app's state for this tab to widget nodes. It
follows the Views package's tab protocol (`views`, `tree`, `titles`, `key`), from which
`cure.draw.views.view(board, "orchestrator", ...)` builds the `TabView`. Its parts, one
module each: [AgentPane] (`agentpane.py`), [SpecPane] (`specpane.py`), [SpecView]
(`specview.py`). It composes existing widget nodes only (Widgets' Block, Pane,
TextInput, Drawing, Paragraph), lays out nothing itself but its default tree (Layout's
Splits), and paints no cell. It imports only Graph, Layout, Widgets, Core and
Geometry (its grants): {Board}'s parts arrive as arguments, read by attribute, never
imported, and it imports neither the Views package nor another tab.

Trust: none added. The agent's screen and sigil's rows are cells and runs construct
already has (its pty and its sigil process, through Embed and Vt on its side); the
spec's edit is construct's. Every string (a path, a row) is drawn as text through Text
and Buffer.

The tab's key: `key() == ("orchestrator",)`, written `k`: the tab is board-wide (one
per board), so the key names no part. Every id a node of this tab carries is `k +
(part,)`, as listed; no other node carries one:
- `k + ("agent",)`: the agent pane's Block; `k + ("screen",)`: its Pane, when the
  agent has a screen. The app focuses `k + ("screen",)` to send the agent keys.
- `k + ("spec",)`: the spec pane's Block; `k + ("edit",)`: its TextInput, when the
  spec has an edit. The app focuses `k + ("edit",)` to send the edit keys.
- `k + ("view",)`: the view pane's Block. The app focuses it to scroll the view.
Focus is the Context's (`ctx.focus`), as in every tab: the tab takes no focus state.

The panes (`views(agent, spec, *, spec_scroll=None, view_at=(0, 0)) -> dict`), in this
order:
- `"agent"`: `agentpane.agentpane(agent)`;
- `"spec"`: `specpane.specpane(spec, spec_scroll)`;
- `"view"`: `specview.specview(spec, view_at)`.
`agent` is Board's `board.agent` (an {Agent}), `spec` its `board.spec` (a {SpecDoc}),
each read by attribute as its module states (the spec's `highlight`, S1, by SpecPane
alone: it becomes the TextInput's `runs`; the spec's `note`, S2, by SpecPane alone:
it is drawn in `warn` after the path in the spec Block's title, cut first; SpecView
and `titles` never read either). The state, the app's for this tab, each
with a default:
- `spec_scroll`: SpecPane's TextInput scroll, `None` (follow the cursor) or a pair
  `(sx, sy)` of ints `>= 0` (a sticky scroll the app keeps);
- `view_at`: SpecView's viewport, a pair `(x, y)` of ints `>= 0`, the content cell
  at the view's top-left.
Each is checked by its pane's function (whether or not the pane uses it).

The default tree (`tree() -> SplitTree`): `SplitTree(Split("x", (Pane("agent"),
Split("y", (Pane("spec"), Pane("view")), (1, 1))), (1, 1)))` (Layout's Splits: the
agent the left half; on the right the spec over its view, half each).

The titles (`titles(spec) -> dict`): `{"agent": agentpane.TITLE, "spec": spec.path or
specpane.UNTITLED, "view": specview.title(spec)}` (`"agent"`, the path or `"spec"`,
`"sigil view"` or `"sigil view (stale)"`: the same words as the Blocks' titles; Paint's
`Tiled` shows them only on a Tabs or Stacked bar, should the app regroup the panes).

Laws (each a property a test can loop over agents, specs, states, sizes and contexts):
- pure (`pure_view`): equal arguments give equal results for `views`, `tree`,
  `titles` and `key`; nothing is read but the arguments (no clock, no file, no
  process, no state of the package's own).
- ids: the ids carried in `views(a, s, ...)` (every node reached through `children`)
  are exactly `{k + ("agent",), k + ("spec",), k + ("view",)}`, plus `k +
  ("screen",)` when `a.screen is not None` and `k + ("edit",)` when `s.edit is not
  None`.
- state: changing `spec_scroll` changes nothing in the result but the TextInput's
  `scroll`; changing `view_at` nothing but the Drawing's `x` and `y`.
- highlight (S1): changing `s.highlight` changes nothing in the result but the
  TextInput's `runs` (the very highlight, `is`), and nothing at all when `s.edit is
  None`; ids, titles and the tree never depend on it.
- unchanged (S1, condition d): with `s.highlight` `None`, the tab's frames (Paint's
  `frame` of the Tiled tab: cells, hits, cursor) equal those of the commit before S1
  (3ff3b8b, loaded by git through `tests/_gitref.py` at test time), for every agent,
  spec, state, size and context.
- note (S2): changing `s.note` changes nothing in the result but the spec Block's
  `title` (SpecPane's note law), whether or not `s.edit is None`; ids, titles, the
  tree and the agent and view panes never depend on it.
- note-none-unchanged (S2): with `s.note` `None` (or absent), `views` equals (`==`),
  `kind` aside (R2: every Block's `kind` left out of the comparison, the old Block
  having none), and the tab's frames (cells, hits, cursor) equal those of the commit before S2
  (df0fa3c, loaded by git through `tests/_gitref.py` at test time), for every agent,
  spec, state, size and context.
- layout-unchanged (S2): for every agent, spec, state, size and context, the frame
  with a note and the frame without (the same spec but `note=None`) have the same
  `tiling` (every pane rect), the same `places` (every node's rect), the same hits
  and cursor, and the same cells but those of the spec Block's title rect (row
  `R.y`, columns `[R.x + 2, R.right - 2)` of the spec pane's rect `R`). Why: the
  pane rects are Splits' `panes(tree, A)` (Paint's Frame, step 1), sized by the
  splits' weights and mins alone, never by a measure; each pane's tree is laid with
  its root at `pane.rect` (Layout's `lay`: the root's entry is `Placed((), node,
  rect, ...)`), so the spec Block's `measure` (the one thing a title's width
  reaches) is never asked; the Block's `chrome()` is the same with a note (its
  `title` is a flag, true either way), so its content rect and the child's rect are
  too; and `titles(s)` never reads the note, so Tiled's bars are unchanged.
- tiles: `set(views(a, s)) == set(ids(tree())) == set(titles(s)) == {"agent",
  "spec", "view"}` (Layout's `ids`), so the Views package's `TabView` accepts them.
- kinds (R2): the agent, spec and view Blocks are of kind `"pane"` (each module
  states it); the tab's frames equal 74f1f6a's (Views' kind-inert law).
- frames: for every size `(w, h)`, `1 <= w <= 120`, `1 <= h <= 40`, Paint's
  `frame(Tiled(tree(), views(a, s, spec_scroll=sc, view_at=at), titles(s)), (w, h),
  ctx)` returns a Frame (never raises), for every valid {Agent} and {SpecDoc} (the
  edit one TextInput accepts), every valid `sc` and `at` (a viewport or scroll past
  the content's end included), with `highlight` `None` and with any valid highlight
  (fresh, stale, shorter or longer than the edit's rows), with `note` `None` and with
  any valid note (one line, wide glyphs included, wider than the pane included; S2),
  every shelf theme
  (`cure.draw.theme.NAMES`: builtin, light, contrast) at every depth, with
  `ctx.focus` `None` or any id of the tab.
- legible: with colour off (Caps depth 0), every pane reads by words and marks: the
  placeholders are words, SpecView's stale mark is the word `stale` (its module's
  law), focus shows by the focus pane's border weight and the TextInput's `›` mark;
  a highlight only colours the spec's text (TextInput's text-unchanged law); a note
  is words.

Inputs: `agent` a Board {Agent}; `spec` a Board {SpecDoc}; `spec_scroll`, `view_at`
  as above.
Outputs: widget nodes (Widgets' Block, Pane, TextInput, Drawing, Paragraph); a `dict`
  of them by pane id; a Layout `SplitTree`; a `dict` of titles; a key `tuple`.
Errors: each pane's (its module's Errors), raised in the panes' order: `TypeError`
  when `agent` lacks `screen` / `cursor`, `spec` lacks `path` / `edit` / `rows` /
  `stale` (a missing `highlight` or `note` is `None`, never an error), or `spec_scroll` /
  `view_at` is of the wrong type; `ValueError` for a
  negative scroll or viewport value; a widget's own error for a value it refuses (an
  edit TextInput refuses) passes through. `titles` raises `TypeError` when `spec`
  lacks `path` or `stale`.
Effects: none.

Usage:
    from cure.core.buffer import Grid, Rows
    from cure.draw import Tiled, frame
    from cure.draw.context import Context
    from cure.draw.theme import builtin
    from cure.draw.views.board import Agent, SpecDoc
    from cure.draw.views import orchestratortab as ot
    agent = Agent(Grid(80, 24), (0, 0))
    spec = SpecDoc("cure.sigil", rows=Rows.of(["[Views] -> [Widgets]"]), stale=True)
    vs = ot.views(agent, spec, view_at=(0, 0))
    tuple(vs)                         # ("agent", "spec", "view")
    ot.titles(spec)["view"]           # "sigil view (stale)"
    f = frame(Tiled(ot.tree(), vs, ot.titles(spec)), (120, 40),
              Context.of(builtin(), focus=ot.key() + ("screen",)))
"""

from cure.draw.layout import Split, SplitTree
from cure.draw.layout import Pane as Tile

from . import agentpane, specpane, specview

PANES = ("agent", "spec", "view")
"""The tab's pane ids, in `views`' order."""


def key() -> tuple:
    """The tab's key, `("orchestrator",)`: every node id starts with it."""
    return ("orchestrator",)


def views(agent: object, spec: object, *, spec_scroll: "tuple[int, int] | None" = None,
          view_at: "tuple[int, int]" = (0, 0)) -> dict:
    """The tab's panes by id: `{"agent": ..., "spec": ..., "view": ...}` (see the module)."""
    return {"agent": agentpane.agentpane(agent),
            "spec": specpane.specpane(spec, spec_scroll),
            "view": specview.specview(spec, view_at)}


def tree() -> SplitTree:
    """The tab's default split tree: agent left (1); spec over view right (1), half each."""
    return SplitTree(Split("x", (Tile("agent"),
                                 Split("y", (Tile("spec"), Tile("view")), (1, 1))), (1, 1)))


def titles(spec: object) -> dict:
    """The panes' titles: `{"agent": "agent", "spec": path or "spec", "view": ...}`."""
    if not hasattr(spec, "path"):
        raise TypeError("spec lacks 'path'")
    return {"agent": agentpane.TITLE, "spec": spec.path or specpane.UNTITLED,
            "view": specview.title(spec)}
