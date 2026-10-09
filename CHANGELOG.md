# Changelog

Each release's notes, newest first. The same text is the GitHub release's description.

## 0.4.2 — 2026-10-09

Fixes for what 0.4.1 left open. No new features.

### Viewer

- **`--once` draws the frame you ask for.** `view.py --once --sim NAME --frame N|last`
  draws frame N in every view (the run view puts its playhead there) and says which
  frame it drew. Before, `--once` always drew the last frame.
- **The run view honours `--depth`.** Given `--depth`, an expansion's lanes fold into
  its node's lane, and a run's narration and path name only the nodes drawn, so at
  `--depth 0` they no longer talk about nodes you can't see. Without `--depth` the run
  view draws every level, as `--run --json` does; the graph, tree and flow views still
  open one level. A fold's own work (an emit inside an expansion) shows as one folded
  activation on its node's lane, not as extra runs of it. The ruler's `≈` marks and
  scale labels keep two blanks apart.
- **The graph view:** a fan-out's shared cells take its most severe member's look,
  wrapped or not, with or without a run, so an error wire reads red from its source; a
  plain crossing with no run and no `!>` keeps its owner's look. A wrapped, joined
  fan-out's join bar spans only its first row's branches and the trunk.
- **The flow view:** with `--payloads`, chipped wires back to one target share one
  return row (chips side by side, or stacked when they don't fit), and never cut an
  outer wire going back. With no run, a bundle's shared way takes its most severe
  member's look.
- **The tree view** picks its wrap again when a run's marks, badges or chips change a
  frame's width, instead of keeping the first frame's choice. A colour whose theme role
  changed is repainted even when its hex value is the same.

### Notation tools

- `render.py` gives non-ASCII names their own Mermaid ids, so names like `(利用者)` and
  `[転送器]` no longer collapse into one node.
- An op verb may start with any letter, so `検索({符号})` and `op 決済.請求(…)` are
  op-calls: `lint.py` accepts the external one, and the views draw both as op-calls
  (a self-call `↺`, a host op `⇱`).

### Checks

- `SGC132`, `SGC133`, static `SGC204` and every store scan count an outer flow and the
  expansion detail it summarises once, emit legs included.

### Agent plugins and page

- The Claude Code pane and pi widget draw wide characters as themselves over two cells,
  not `??`, with the same width rule as the views.
- A playing run in the pane or widget no longer pauses at a window boundary: the next
  window of frames is drawn ahead.
- The wide-character tables in the page and the Claude Code pane are generated from
  Python's `unicodedata` (`tools/wide_table.py`), so they agree with the views.

## 0.4.1 — 2026-10-09

Fixes and speed-ups for what 0.4.0 shipped. No new features.

### Viewer

- **Wide characters line up.** A CJK name takes two columns and a combining mark
  none, in every view, the Claude Code pane, the pi widget and the page. Before, a
  wide name pushed its row out of line, and a decomposed mark (as in が) could be drawn
  on its own. ASCII drawings are unchanged.
- **A playing run is much faster.** During a run the graph, tree and flow views lay
  the drawing out once and repaint only what changes (about 6–10× faster a frame on a
  500-flow chain). The pane, widget and playground do the same. The drawing is the same.
- **The graph view:** a fan-out wrapped onto lower rows passes them as one trunk, so the
  drawing is shorter and narrower. In a run the trunk takes the look of its busiest wire,
  so a failed call reads failed from its source down.
- **The tree view:** a lane reaches its ends only in the expansion its wire is written
  in. A store borrowed by two expansions gets a lane to each, and the gutter is
  narrower.
- **The flow view:** wires back from one source to one target share one return row
  instead of looping separately (the shortener's two replies to `(Visitor)`). A taken
  wire in that bundle is lit all the way along.
- **The run view:** `↺k`, episode and finding marks sit on a row of their own above the
  ruler, so they no longer hide its ticks. When loop marks crowd, only every 2nd, 5th,
  10th … is labelled.
- `view.py --help` explains every flag in plain words, lists the views in key order and
  names flow as the default.

### Simulation and checks

- At `--depth 0` a run's token on a folded detail rides the outer flow that summarises
  it (the shop's `[Shop] ~> <OrderPlaced>`), so the token no longer vanishes while
  the detail runs.
- Overlapping activations find their `∥` row by a heap instead of a scan, so long runs
  with many of them no longer slow down quadratically.
- `SGC131` counts an outer flow and the expansion detail it summarises as one writer, not
  two. A failure route (`!>`) still counts on its own.

### Agent plugins and page

- The Claude Code pane and pi widget play every frame of a long run, drawn a window at a
  time. Before, they showed at most 400 frames, evenly spread.
- The page's run section names the run playing in its command (`--sim not-found` while
  not-found plays). On a phone, the 3D planes stay above the section text.

## 0.4.0 — 2026-10-08

Two new views, a viewer inside your coding agent, drawings that fit the window, and
a simulator you can read.

### Viewer

- **Four views, flow first.** `view.py` now has four views on keys `1`–`4`
  (`t` steps to the next): graph, tree, flow and run. It opens in the **flow view**,
  a call graph read left to right: bare labels in columns by call depth, each payload
  on its wire. `--graph`, `--tree`, `--flow` and `--run` pick one.
- **The run view** (`--run`, key `4`) draws one simulated run as a timeline. Each
  participant gets a lane, and so does each instance and recursion level. Time runs
  left to right. A bar shows working or waiting, and each call is drawn at the tick it
  was sent. Retries show as repeated segments, spawns fork off their spawner, and
  loop iterations are marked `↺k` on the ruler. Activations that overlap on one lane
  get `∥k` sub-rows, and a check finding's number sits on the ruler at the tick its
  run shows it. Without `--sim` it draws the happy run. `--unroll` sets how many
  instances show before the rest fold. `--run --json` prints the timeline as data.
- **Every view fits the window.** Graph, tree and flow wrap to `--width` (or the
  pane) and grow downward instead of running off the right edge. No box or label is
  squashed. A graph layer that is too wide wraps onto the layers below. The tree
  folds lanes it has no room for into numbered plugs (`●①` … `◀───①`). The flow view
  cuts into bands joined by the same plugs. The summary, lint lines, legends and
  part titles wrap or cut to the width too. A drawing that still can't fit says how
  wide it is.
- **A layout preference.** `--layout wrap` (fit the width, grow down), `pan` (keep
  the natural layout and pan across) or `auto` (the default: whichever overflows
  less for the window's shape). Live, `o` cycles the three and `f` flips between wrap
  and pan.
- **Flow view details.** Control blocks (`loop`, `parallel`, branches) are drawn in
  frames under their part, and joins are marked just before their heads
  (`─&▶ ─&?▶ ─/▶`).
- **The graph view** keeps an edge label from sitting where it reads as the
  neighbouring head's.

### Simulation

- **Runs in plain words.** A run is narrated one step at a time ("[API] calls
  [Payments] with charge(total) — attempt 2 of 4"). The viewer shows the line now,
  the steps before it, and a `path` row of the hops taken so far, numbered by branch
  (`①` `②` …). `✖` marks a failed hop, `⊘` a cancelled one, and `▸` the hop now.
  `--once --sim NAME` prints the run in words, and `--sim NAME --json` prints its
  facts, steps and log.
- **Playback you can follow.** Speeds go from ¼ to 32 frames a second. `<` / `>` step
  by event, `,` / `.` by frame. The view follows the token, and `w` turns that off.
  `--frame N|last` and `--play` set where a live run starts.
- **A design's levels are read once.** An outer flow that summarises what its
  expansion already does no longer runs a second time: the shop's happy run lands
  `<OrderPlaced>` once, not twice. Only a detail that every run takes counts as
  summarised. Failure routes and optional `?>` branches don't.

### Agent plugins

- **A viewer in Claude Code.** The plugin adds a `view` tool for the agent and a
  `/sigil-pane` command for you. They show a document live in a pane inside Claude
  Code, or in a herdr / tmux / zellij split. The pane redraws on every save and can
  step or play a run at the viewer's speeds. `/sigil-pane display mod|multiplex|auto`
  picks where it draws, and `/sigil-pane layout wrap|pan|auto` how it fits. Both are
  kept in the plugin's `/config` row.
- **The same viewer in pi.** It has a `sigil_view` tool, `/sigil-pane`, a live widget
  above the editor and the same split. Settings live in
  `$XDG_CONFIG_HOME/sigil/viewer.json`, or `--sigil-display` / `--sigil-layout` and
  their environment variables. In RPC mode the widget is sent as text.
- Both draw exactly what `view.py` draws, and the agent's reply names the step now and
  the path. docs/tools.md describes the viewer plugin contract.
- **The skill** tells the agent how to show you a design (the viewer tool, a split, or
  `--once`) and which view fits it.

### Page and playground

- **The page opens with the problem and a URL shortener.** All four views play behind
  the editor as it types. Further down, a section per view brings its view forward.
  The run section plays the shortener's happy and not-found runs in the real run view.
- **The playground** has all four views, the run's path and narration, speed and step
  controls, and a polite live region that reads the narration aloud for screen
  readers.

### Fixes

- `check.py` no longer hits a RecursionError on a very long call chain.
- A store borrowed in one expansion, but a node only in a sibling expansion, gets its
  access edge.
- A run with no hops, an episode starting at a branch (a raw decision id leaked into
  the narration), and `--unroll 1` on a recursion no longer crash or misdraw.
- The run view, control-block frame titles, chip panels and the tree's payload list
  keep to `--width`.
- Plugin panes: an older redraw no longer overwrites a newer one, and a failed draw
  isn't retried in a loop. Run frames are numbered as the run numbers them (never
  capped at 99, never sampled). Naming the shown file again keeps its run.
- Legend lines no longer end in trailing blanks.

### Speed

- Banding a long flow, `check.py` on long chains, failure analysis, and drawing a run
  frame by frame (the plugin panes) now scale roughly linearly with the document. A
  600-node chain used to take over a minute to wrap. Output is unchanged.

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
