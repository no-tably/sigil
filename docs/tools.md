# Tools reference

Every tool is a Python 3 script with no dependencies beyond the standard library.
Each one takes a file, or `-` for stdin. The [README](../README.md) has the overview.

## Exit codes

Every tool shares one table, and prints its errors to stderr as `tool.py: message`.

| Code | Means |
| --- | --- |
| 0 | OK: nothing to report (`--sim all` and `--rules` always exit 0) |
| 1 | warnings or findings only |
| 2 | errors: an error-severity diagnostic or finding, bad usage, or input the tool cannot read |

One exception: `view.py --once` exits 1 on a lint error, since the drawing is its output.

## `lint.py FILE|-`

Validates a document and prints one `severity:line:rule: message` line per issue.
Its exit code follows the [table](#exit-codes): 0 clean, 1 warnings, 2 errors.

- `--deep` also runs the composition checks (`check.py`) and merges both reports into
  one list by line. Acknowledged findings come last, as `accepted:` lines. The exit
  code is the worse of the two.
- `--dialect NAME` lints with a dialect's extra vocabulary (see [Dialects](#dialectspy)).

## `check.py FILE|-`

Composition checks: rules `SGCnnn`, from
[RFC 0003](../rfcs/0003-composition-checks.md). It asks whether the design says how
its risks are handled. Examples are an external call with no time bound, a retried
write with no idempotency, two writers on one store, a failure with no route, an
event nothing consumes, and a state machine that can get stuck.

A finding never forbids a shape. You satisfy it by declaring the handling in the
notation (`@timeout`, `×N`, `!>`, `@inv …`), or with a reasoned
`# accepts: rule-name — reason` comment. Severity follows the document's mode:
`#!sketch` hides findings, `#!craft` asks them as questions, and `#!spec` makes the
binding rules errors. The line format and [exit codes](#exit-codes) match lint.

- `--mode sketch|craft|spec` checks as another mode.
- `--k N` explores up to N failures per run.
- `--budget N` caps the runs one exploration may make; `--limit NAME=N` raises one
  simulator limit (repeatable, e.g. `depth=5`).
- `--all` also shows hidden findings.
- `--json` prints one object per run: rule, tier, why, how to satisfy, witness.
- `--rules` lists the rules and exits.
- `--dialect NAME` adds a dialect's rule pack.

See "Checks" in [`language.md`](../language.md).

## `view.py FILE`

A live terminal view of the design that redraws on every save. It has four views:
the flow view (a call graph read left to right: bare glyph labels in columns by
call depth, wires bending between them; the default), the graph view (boxes and
edges, top down), the tree view (the composition tree as an outline, with every flow
as a lane beside it) and the run view (one simulated run as a timeline: a lane per
participant, instance and recursion level, time left to right). The first three
draw the design, what can happen; the run view draws what did happen in one run.

Which view reads best depends on the question. The flow view suits request paths,
call chains and failure routes, and is usually the shortest drawing. The tree view
suits composition and ownership (has, spawns, `:=` internals) and state machines,
and is the narrowest for a small design. The graph view suits the overall topology
of a small design: fan-in, fan-out, where flows converge; it is the tallest. Every
view fits a narrow pane by growing down (see below). The run view presents a simulation: order and timing,
retries, spawned instances and recursion levels; it shows only what ran. An agent
that opens or presents a view tells the person in one sentence which view it
picked and why (the skill's "Which view" has the details).

Options:

- `--once` prints the drawing and a lint summary, then exits (1 on a lint error; see
  [exit codes](#exit-codes)).
- The view starts in the flow view; `--graph` starts in the graph view, `--tree`
  in the tree view, `--run` in the run view (`--sim`'s run, else the happy one; `--unroll N|all` sets how many instances
  of one node it shows before the rest fold, 3 by default).
- `--depth N|all` opens `X := { … }` expansions (in the tree view an expansion's
  members hang off dotted rails, `├┄┄`, apart from a branch's solid `├──`).
- `--payloads` shows flow payloads: chips on edges in the graph view, on the wire
  between two columns in the flow view (`─┆{Cart}┆─▶`; a self-call's on a stub under
  its subject), a list in the tree view (an error path's chip there led by `✖`). A `"""…"""` block-string shows its
  first line and `…`; its full text is a note (`--notes`).
- `--mods` shows modifiers (`@timeout 30s ×3`, `^10k drop`, `!`) as chips on edges and
  after node labels.
- `--access` draws the permission graph. `@read`, `@write` and `@borrow` become dotted
  principal → store edges headed `r`, `w` or `b` (`ƀ` for `@borrow(read)`). Stores get a `1w` or `Nw` writer badge.
- `--events land|nodes` draws a pass-through event where it lands (each emitter wired
  straight to each destination) or as a node of its own. The tree view defaults to
  `land`, the graph and flow views to `nodes`.
- `--notes markers|callouts` shows comments as `#N` tags with a notes list, or as boxes
  in a left margin tied to their rows (tree view). A comment above a glyph-less block
  header (`branch on …`, `loop …`, `parallel …`, a scoped `name {`) tags the block's
  frame title or header row. A header comment that comes before the first statement
  but isn't directly above it is the document's own note. It is listed first as `¶`
  and tagged on nothing.
- `--sim SCENARIO` runs one pathway of the design and draws its last frame, then the
  outcome and the run in plain words, one `tNNN …` line per step (`[API] calls
  [Payments] with charge(total) — attempt 2 of 4`; see
  [Simulation](../README.md#simulation)). With `--json` it prints that run as JSON
  instead, with no drawing: the facts `--sim all` lists, `steps` (frame, tick, text)
  and the simulator's raw `log`. `--sim list`
  prints the scenarios, one per line with its label. `--sim all` runs every scenario
  and prints no drawing: a line per run (name, outcome, frames, label), indented
  facts (`states:` each machine's end state, `failed:`, `routes:` the failure routes
  taken, `ignored:` events a state had no transition for, `waiting:`, `open:` joins
  left open, `bounds:` base case, visit limit, spawn cap, a capped loop, a cut) and a
  summary line. It always exits 0; diff two versions' tables to see what changed.
  `--json` prints either as JSON. `--run --json` prints the run's timeline as data
  (lanes with their labels, spans with their waits, moves, marks) — the scenario's,
  else the happy one.
- `--limit NAME=N` raises one simulator bound for `--sim` (repeatable): `iterations`
  (loop repetitions, 2), `depth` (recursion, 3), `spawn` / `spawns`, `visits`, `stack`,
  and the per-episode `frames` (2000) and `activations` (500). Each entry point runs
  as its own episode with its own `frames` and `activations`, so a large design runs
  every entry in full; a run that still ends `cut` names the bound it hit.
- `--checks` marks composition-check findings on the drawing, with a checks legend.
  Each finding's question follows the lint summary.
- `--compact` starts without the blank row between top-level units.
- `--no-triggers` starts with event ⇢ state triggers hidden.
- `--no-lint` skips lint.
- `--theme NAME` picks a colour theme (see [themes](#themespy-namepath)); `--color
  auto|always|never` decides when to colour.
- `--layout auto|wrap|pan` says how a drawing wider than the window is shown. `wrap`
  fits it to the width and lets it grow down; `pan` keeps its natural layout and
  pans across (arrows, mouse drag; with `--once`, the natural drawing, its lines
  under it still wrapped); `auto`, the default, picks whichever overflows less:
  wrap when the drawing is wider than the window in proportion to its height, pan
  when it is already much taller than the window and only a little too wide. A
  printout grows down freely, so `--once` wraps under `auto`. Live, `o` cycles
  the three and `f` flips between wrap and pan; the status bar says what is shown
  (`wrap`, `pan`, `auto→wrap`), and a run plays without switching layout.
- `--width N` fits a `--once` drawing to N columns (default: the terminal's width, or
  100 when stdout is not a terminal). Every view wraps to it and grows down: the
  graph view's layers wrap onto the rows below, the tree view's lanes fold, the flow
  view cuts into bands, the run view into bands of ticks. The summary and lint
  lines under the drawing wrap at it too.
- `--dialect NAME` draws with a dialect.

The graph and tree views also draw:

- control blocks. The graph view draws titled frames (`↺ loop …`, `∥ parallel …`,
  `◇ branch on …` with a decision node and arm chips, and `□ scope`). The tree view
  draws brackets in a left gutter.
- `&`, `&?` and `/` joins, `--- section ---` dividers, `[[alias]]` nodes, and the
  `#!mode` in the status bar.

The flow view reads like the project page's background graphs. A node's first callee
sits on its row and the rest below it; wires from one source share a trunk
(`─┬─▶ ├─▶ ╰─▶`), wires into one target with one kind of head share its last run, and
a target fed by several kinds of arrow takes their heads stacked (`▶┐` / `✖┘`). A
wire that only crosses another hops it (`─│─`); a wire back to an earlier column
runs along a return row under the drawing (`╰──╯`). Strokes, heads, colours, chips,
notes, triggers, the checks overlay and the simulation are the graph view's.
`--- section ---` dividers and expansions are parts under titles, as in the graph
view; a control block's flows are drawn in its frame under its part, as in the graph
view (a branch's arms are dotted wires labelled `‹arm›`), and a joined endpoint's
wire carries its join just before its head (`─&▶`, `─&?▶`, `─/▶`).

When the flow view is wider than its width (the window with the wrap layout, `--width`,
a pane), it wraps like text, a step at a time and only while it still doesn't fit:
chips become marker letters with a key (`┆a┆`); then what is written on a wire, and a
label's notes and modifiers, hang under the node that sends it, the wire keeping its
letter (`─a▶` over `a┆{Cart}`); then a part is cut between its call-depth columns
into bands stacked down the page, a cut wire ending in a numbered plug at the right
edge (`─▶①`, `─▶③↑` when it resumes in a band above) and resuming at the start of
the band it lands in (`①──┬─▶`). The cuts take the fewest bands, then the fewest
plugs. A band that still can't fit leaves a hint under the drawing that the tree
view reads narrow panes best; the view never switches by itself. A run plays
without reflowing, its tokens crossing the plugs.

The graph and tree views fit a width the same way, never squashing a box or a
label. In the graph view a chip becomes a marker letter first; then every layer
too wide for the width wraps onto the layers below it (a node only moves down, the
edges passing a layer take its room too), and each row of boxes, each row of
control-block frames and the grid of unconnected nodes keeps inside the width. In
the tree view the margins give way first (callouts narrow, then move to panels);
then the lanes past the gutter columns that fit fold into the same numbered plugs:
a folded lane draws no vertical, its source row ends `●①` and each target row
`◀───①`, a row's plugs in a run after the lanes it keeps. A drawing that still
can't fit (a box wider than the width, a row with more plugs than room) leaves a
hint under it saying how wide it is.

The run view draws one run as a timeline. Time (ticks) runs left to right under a
ruler, one column a tick; a quiet stretch of more than three ticks folds into one
`≈` column. Each participant gets a lane in the order it first acted — one per
composition instance (`{Transform·2}`), the levels of a recursion as `↻2` `↻3`
sub-rows under it, an expansion's lanes indented under its node:

```text
── run · API.charge:fails — charge fails 4×, no fallback ─────────────────────────

                  0         10        20        30
  (Shopper)       █░░░░░░░░░░░░░░░░░░░░░░░░░░░░░✕   episode 1's entry; fails
  [API]           ╰──▶██░░░░█░░░░█░░░░█░░░░█░░░░✕   routes the failure; fails
  [Payments]           ╰───✖╰───✖╰───✖╰───✖│        4 attempts, each fails
  <PaymentFailed>                          ╰──✖◆    lands
```

A bar per activation: `█` working, `░` waiting (on a call it made, a deeper
activation, the members it awaits), `◆` an event landing, then `✕` failed or `⊘`
cancelled. A call is drawn at its send tick: a vertical from the sender's lane, the
transit along the receiver's lane in its arrow's stroke (`╰──▶` `╰╌╌▶` `╰━━▶`
`├══▶`) into the callee's first cell. An attempt that fails on arrival ends `✖` with
no bar, and retries repeat the segment; a race's loser ends `⊘`; a reply runs on the
callee's lane to `↩`. `↺` is a self-call's pulse, `┤` where the depth limit stopped
a recursion, `⇱` a host op, `•` an actor reached with no work of its own, `┆` the
boundary between episodes. A spawned lane carries `◌` while its spawn hop flies;
many instances fold into `{…×k more}` (`u` / `--unroll`). Each lane has a note in
plain words ("4 attempts, each fails", "spawned by [Spawner] for [Asteroid]"); `n`
cycles run notes, the design's own notes on the node, and none. In sim mode the
playhead `▼` (and `┊` down the blank cells) is the frame's tick: nothing right of
it is drawn, lanes appear as they are born, `●` / `○` ride the transits and `▸`
marks the lanes working. With no scenario chosen it draws the happy run and says
so; `x` plays it. When it is too wide the notes shrink, then move below the drawing,
then the timeline wraps into bands, each with its own ruler and the lanes active in
it.

In sim mode every view draws the same run. The wire a token is on now is bright,
wires taken before are faded (`ui.sim_trail`), and wires never taken are
fainter (`ui.sim_faint`). Under the footer, in words that read without colour:
`path` and the episode's hops so far in notation, the last few events, and the
narration line, `›` and what is happening now. The path is numbered by branch: a
run of hops that starts again from a node already on the path is a new branch,
`①` `②` … (`(21)` past `⑳`), three spaces apart —
`① (Shopper) -> [API] -> [Payments] ✖×4   ② [API] !> <PaymentFailed>`. A hop that
failed on arrival is marked `✖` (`✖×4` when repeated; `×N` alone a hop repeated),
a cancelled one `⊘`, and the hop a token is on now is bold, as its wire is (`▸`
before it with `--color never`). It takes two rows at most; a longer path folds its
oldest branches into `①–③ …` so the newest stay readable. `--once --sim` prints
the path at the run's last frame under its outcome line. The view follows the run's tokens
and active nodes, panning only when they leave the window; `w` turns that off. The
playground shows the same path and narration under its drawing (from the same
`SimPlayer`), steps a frame (`,` `.`) or an event (`<` `>`) at a time, and picks its
view with the same `1` `2` `3` `4` and `t`.

Live keys:

| Key | Does |
| --- | --- |
| `1` `2` `3` `4` | the view: graph · tree · flow · run |
| `t` | the next view (graph → tree → flow → run → graph) |
| `x` | sim mode; then space play / pause, `,` `.` a frame, `<` `>` an event, `[` `]` scenario, `-` `+` speed (¼ to 32 frames/s, from 2), `w` follow |
| `c` | checks overlay |
| `n` `e` `v` | notes · triggers · events (where they land / as nodes); in the run view `n` cycles run notes · the design's · none |
| `u` | the run view: instances shown before folding, 3 → 8 → all |
| `p` `m` `a` | payloads · modifiers · access |
| `d` `s` `l` | depth · spacing · lint |
| `o` | layout: auto → wrap → pan (the status bar says what is shown) |
| `f` | flip between wrap and pan (sets `o`'s layout) |
| arrows, `h` `j` `k` `L` | pan; mouse drag pans, the wheel scrolls (shift+wheel across) |
| `z` `g` | centre · home |
| `r` `q` | reload · quit |

## The Claude Code viewer

The Claude Code plugin's mod (`plugin/claude`) gives the agent a `view` tool and
gives the person a `/sigil-pane` command. Both show a document in a live viewer,
redrawn on every save.

The tool's input:

- `file` — the `.sigil` file.
- `view` — `flow` (the default), `graph`, `tree` or `run` (one run as a
  timeline: the scenario's, else the happy one).
- `depth` — a number, or `"all"`.
- `scenario` — a scenario to simulate, as `--sim` names it. `""` ends the run.
- `frame` — the frame of the run to show: a 0-based number, or `"last"`. A new
  run starts on its last frame.
- `play` — `true` plays the run, `false` pauses it.
- `payloads` — show flow payloads.

A field you leave out keeps its last value. The reply says where the document is
shown, then gives the summary line, lint, the run's step at that frame, its
narration line (`now: …`, in view.py's words) and path (`path: …`, the hop now
marked `▸`), the run's
outcome, and the scenario names. It never returns the drawing:
`view.py --once` prints that.

`/sigil-pane` takes the same fields as words, in any order: `FILE`, a view name,
`depth N|all`, `sim SCENARIO`, `frame N|last`, `play` and `payloads`. With no
words it reopens the pane. `/sigil-pane display [mod|multiplex|auto]` says or sets
where it draws, and `/sigil-pane layout [auto|wrap|pan]` how a drawing wider than
the pane fits (see [the viewer plugin contract](#the-viewer-plugin-contract)).
`layout` is the plugin option of that name, a `/config` row as `display` is; in a
split it is view.py's `--layout`. Panned, a drawing wider than the pane shows its
`h` and `l` keys (`◀` `▶`), which move it half a pane across.

The plugin option `display` picks where the viewer draws. `/sigil-pane display
VALUE` writes it, as `/config sigil.display=VALUE` does; the module reloads with
the new value and the next view draws there.

- `mod` draws in a pane: a sidebar beside the transcript in Claude Code's
  fullscreen layout (`CLAUDE_CODE_NO_FLICKER=1`, from 110 columns), otherwise
  inline above the prompt. Its keys work while it holds the keyboard: a pane you
  open with `/sigil-pane` takes it at once, one the agent opens never does
  (ctrl+x then Tab, or a click, gives it the keys; Esc hands them back, and the
  footer says which). `1` `2` `3` `4` pick graph, tree, flow and run (the current
  one in brackets), `t` cycles them, `d` the depth; with a run, `p` plays or pauses it
  and `b` and `n` step it, and under the drawing the pane shows the run's path
  (in view.py's styles) and, after `›`, its narration line, as the live view's rows under its footer.
  Docked, the drawing fills the pane and the legend,
  summary and keys sit at its bottom. The flow and run views draw with their own
  legends. The pane draws the cells that `pane.py
  draw` packs (frames.py's packing, with hex colours), not ANSI. A pane opened
  without being asked needs 144 columns. Below that, the reply says it's waiting
  and names `/sigil-pane`, which opens it at any width.
- `multiplex` opens a split to the right in herdr, tmux or zellij, running
  `pane.py follow CONTROL`. That loop runs `view.py` live with the flags in the
  control file and restarts it each time the agent's next call rewrites the file.
  Pressing `q` in the split closes it. Frame and play are driven from the split's
  own keys.
- `auto`, the default, picks `multiplex` when `HERDR_ENV`, `TMUX` or `ZELLIJ` is
  set, and `mod` otherwise.

## The pi viewer

The pi package's extension (`plugin/pi`) does the same job in pi. The agent gets a
`sigil_view` tool and the person gets a `/sigil-pane` command. Both work as they do in
Claude Code, with these differences:

- The tool takes the same fields. `depth` and `frame` are strings: `"2"`, `"all"`,
  `"last"`. A number passes too, since pi converts it.
- `mod` draws in a widget above the editor, in the theme's colours as truecolour
  text. A tall drawing is cut to fit the terminal, and the last row says how
  many rows were left out. A run's path and narration line (`›`) follow the
  drawing, as in the pane. A widget opened without being asked needs 144 columns.
  Below that, the reply says it's waiting and names `/sigil-pane`, which opens it at
  any width.
- The widget takes no keys, since it never has focus. `/sigil-pane` takes the tool's
  words (`FILE`, a view name, `depth N|all`, `sim SCENARIO`, `frame N|last`,
  `play`, `payloads`) plus `pause`, `back`, `next` and `close`, and `left` and
  `right`, which pan a panned drawing half a widget across. With no words it
  reopens the widget.
- `multiplex` opens the same split, running `pane.py follow`.
- pi has no plugin settings, so `/sigil-pane display VALUE` and `/sigil-pane layout
  VALUE` save to the shared settings file (`~/.config/sigil/viewer.json`). For one
  session, `pi --sigil-display auto|mod|multiplex` or the `SIGIL_DISPLAY`
  environment variable wins over the file (`--sigil-layout`, `SIGIL_LAYOUT` for the
  layout); with none of them set it's `auto`.
- In print and json modes (`-p`, `--mode json`) there's no UI. The `mod` reply
  says so and points to `view.py --once`. In RPC mode the widget isn't drawn:
  pi sends RPC clients only plain-text widgets, and this one is a component.

## The viewer plugin contract

Every agent plugin that carries a viewer (Claude Code's mod, pi's extension, and
any later one) behaves the same way here, so a person moving between agents
finds the same command and the same words.

- **The command** is `/sigil-pane` (`/sigil` is the skill's own). With a file and
  the tool's words it shows the file; with no words it reopens the viewer.
- **`/sigil-pane display`** replies with the setting, where it comes from, and
  what `auto` resolves to in this session. **`/sigil-pane display VALUE`** sets it
  and replies the same way. Any other value is an error that names the three.
  `display` is never read as a file name.
- **`/sigil-pane layout`** and **`/sigil-pane layout VALUE`** do the same for the
  layout: `wrap` fits a drawing wider than the viewer to its width and lets it
  grow down, `pan` keeps the natural layout and pans across (the viewer's own keys
  or words), `auto` picks whichever overflows less (view.py's `pick_layout`, given
  the viewer's columns and rows). The reply says what the drawing shown was laid
  out as under `auto`. `layout` is never read as a file name either. A split
  passes it to view.py as `--layout`.
- **The values**: `mod` draws inside the agent's own UI (a pane, a widget),
  `multiplex` opens a split to the right running `view.py` live (through
  `pane.py follow`), and `auto` picks `multiplex` when `HERDR_ENV`, `TMUX` or
  `ZELLIJ` is set, and `mod` otherwise. `resolveDisplay` in
  `plugin/claude/hooks/logic.ts` is the rule; a plugin in TypeScript imports it.
- **Where it's kept**: in the host's own settings when it has them (Claude
  Code: the plugin's `userConfig` fields `display` and `layout`, `/config`
  rows). A host without them uses the shared file
  `$XDG_CONFIG_HOME/sigil/viewer.json` (`~/.config/sigil/viewer.json` when that's
  unset), holding `{"display": "mod", "layout": "wrap"}`. It's read on each use,
  and writing it keeps any other keys. A flag or environment variable the host
  offers for one session (`--sigil-display`, `SIGIL_DISPLAY`; `--sigil-layout`,
  `SIGIL_LAYOUT`) wins over the file, in that order.
- **The reply** (`displayReport` in `logic.ts`), one line:

  ```
  display: auto → multiplex (herdr detected) · from /config sigil.display
  display: mod · from SIGIL_DISPLAY · auto here → mod (no multiplexer detected)
  ```

  After a change, a second line says where the next view draws, or which
  setting still wins in this session. An error starts with `sigil:`. The layout
  reply (`layoutReport`) is the same shape:

  ```
  layout: auto → pan (the drawing shown) · from /config sigil.layout
  layout: wrap · from SIGIL_LAYOUT
  ```

## OpenCode

OpenCode gets the skill and commands but no viewer plugin. To show a design live
there, run `view.py FILE` in a herdr, tmux or zellij split; the agent reads
`view.py --once`. Checked on 2026-10-07:

- OpenCode's published plugin docs (opencode.ai/docs/plugins) cover server
  plugins only: hooks, events and custom tools. Nothing there draws in the TUI.
- The repository does have TUI plugins: slots, routes and dialogs, through
  `@opencode-ai/plugin/tui`, configured in `tui.json`. The only description is
  a spec inside the repository (`packages/opencode/specs/tui-plugins.md`). The
  published docs don't mention them.
- A viewer would need two modules. A server plugin would hold the agent's tool,
  and a TUI plugin, in Solid JSX on OpenTUI, would draw. The spec doesn't allow
  one module to be both. The two would talk through files, and none of that can
  be checked without OpenCode installed.

## `render.py FILE|-`

Emits a Mermaid `flowchart TD` for docs (GitHub, Obsidian, mermaid.live, …).

- `--depth N|all` opens expansions.
- `--dialect NAME` renders with a dialect.
- `--composition subgraphs|edges|none` draws composition trees as nested subgraphs
  (the default), as labelled dotted edges, or not at all.

## `themes.py [NAME|PATH]`

Loads a colour theme from `themes/<name>.yaml` and prints it resolved. `--list` lists
the themes. `view.py --theme NAME` or `SIGIL_THEME=NAME` picks one, and the web page
reads the same files. The format is in the README under
[Themes](../README.md#themes).

## `dialects.py`

Loads a dialect (`--dialect NAME` or `SIGIL_DIALECT`) that extends the linter, the
renderer and the checker. See "Dialects" in [`language.md`](../language.md).

## `highlight/`

Syntax highlighting for bat, nvim, VS Code and Sublime / TextMate. See
[`highlight/README.md`](../highlight/README.md).
