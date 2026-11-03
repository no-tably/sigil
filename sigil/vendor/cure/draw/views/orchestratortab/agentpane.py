"""[AgentPane]: the orchestrator's agent terminal: a Pane over the {Grid} the app gives.

Kind: service (a pure function from an {Agent} to a widget node; see the OrchestratorTab
package for the tab and its key `k == ("orchestrator",)`).

What it does: the `"agent"` pane of construct's orchestrator tab. The agent's screen
(a Buffer {Grid} construct already has: the orchestrator agent's pty, run through Embed
and Vt on construct's side) is shown through a Widgets `Pane` inside a Block, or a
placeholder before its first frame. It composes existing widget nodes only and paints
nothing itself; it never starts, reads or writes a process.

The {Agent} is read by attribute (`agent.screen`, `agent.cursor`): OrchestratorTab's
import grants do not include Views' `board/`, so any value with those two attributes
serves, Board's `Agent` among them (whose construction has already checked them).

The pane (`agentpane(agent) -> Block`):
`Block((child,), title=TITLE, kind="pane", id=k + ("agent",))`, every other Block
field its default (rounded border, Column layout, `focused=None`: the Block is the
focus pane exactly when `ctx.focus` names it or a node inside it; `kind="pane"`, R2:
a tab's tiled pane, inert until R3 gives it its edge patterns), where `child` is:
- with a screen (`agent.screen is not None`): `Pane(agent.screen,
  cursor=agent.cursor, id=k + ("screen",))` (Widgets' Pane, `x == y == 0`: a live
  screen). The app focuses `k + ("screen",)` to send the agent its keys: the Pane
  then gives `cursor_at` (where the app puts the terminal's own cursor) and the
  Block, the focus pane, lifts (its heavy focus border).
- with `screen is None`: `Paragraph(PLACEHOLDER, role="muted")` (no id).
`TITLE == "agent"`, `PLACEHOLDER == "no screen yet"`.

Laws (a test can loop over agents, sizes and contexts):
- pure: `agentpane(a) == agentpane(a)` for equal agents; nothing is read but the
  argument.
- ids: the ids carried (every node reached through `children`) are exactly `{k +
  ("agent",)}`, plus `k + ("screen",)` when `a.screen is not None`.
- screen: the Pane holds the very `Grid` object the agent holds (not a copy).
- kind (R2): the Block's `kind` is `"pane"`; its cells, hits and layout equal those
  at 74f1f6a (the Block's `kind-inert`), only the node differs, by its kind.
- legible: with colour off (Caps depth 0), the placeholder is words; the focus shows
  through the Block's focus border weight and the terminal cursor at `cursor_at`.

Inputs: `agent` a Board {Agent} (or any value with `screen` and `cursor`).
Outputs: a Widgets `Block` holding a `Pane` or a `Paragraph`.
Errors: `TypeError` when `agent` lacks `screen` or `cursor` (`"agent lacks 'screen'"`,
  the first missing in that order); a screen or cursor of the wrong type is refused by
  Widgets' `Pane` (its own `TypeError` / `ValueError`, passed through; a Board `Agent`
  never holds one).
Effects: none.

Usage:
    from cure.core.buffer import Grid
    from cure.draw.views.board import Agent
    from cure.draw.views.orchestratortab import agentpane
    node = agentpane.agentpane(Agent(Grid(80, 24), (0, 0)))
    node.id, node.children[0].id      # (("orchestrator", "agent"), ("orchestrator", "screen"))
    agentpane.agentpane(Agent()).children[0].text   # "no screen yet"
"""

from cure.draw.widgets import Block, Pane, Paragraph

_K = ("orchestrator",)

TITLE = "agent"
"""The agent pane's Block title."""

PLACEHOLDER = "no screen yet"
"""What the agent pane says before the agent's first frame."""


def agentpane(agent: object) -> Block:
    """The agent pane: a Block around a Pane over `agent.screen`, or the placeholder."""
    for name in ("screen", "cursor"):
        if not hasattr(agent, name):
            raise TypeError(f"agent lacks {name!r}")
    if agent.screen is None:
        child = Paragraph(PLACEHOLDER, role="muted")
    else:
        child = Pane(agent.screen, cursor=agent.cursor, id=_K + ("screen",))
    return Block((child,), title=TITLE, kind="pane", id=_K + ("agent",))
