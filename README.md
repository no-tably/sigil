# Sigil

<p align="center"><img src="assets/banner.svg" alt="Sigil — a coin with a knotwork ampersand, and the wordmark [S]{I}&lt;G&gt;(I)|L|" width="880"></p>

Sigil is a compact, non-executable notation for system designs. Components,
data, events, actors and stores are **glyphs**; the flows between them are
**arrows**; constraints are **modifiers**. A whole architecture fits on one
screen, reads aloud, and expands unambiguously back into prose.

```sigil
#!sketch

--- Checkout ---
(User) -> [API] : {Cart}
[API] -> [Payment] : charge ×3 @timeout(2s)
       !> <PaymentFailed>
[API] ~> <OrderPlaced> -> |Ledger|
```

`(User)` is an actor outside the system, `[API]` a component, `{Cart}` data,
`<OrderPlaced>` an event, `|Ledger|` a store. `->` is a call, `~>` is async,
`!>` is the failure path, and a line starting with an arrow continues the
previous subject. `view.py` draws it in the terminal:

```
── Checkout ───────────────────────────────────────────

                    ╭────────╮
                    │ (User) │
                    ╰────────╯
                         │
                         ▼
                     ┌───────┐
                     │ [API] │
                     └───────┘
                         │
      ┌──────────────────┼───────────────────┐
      ▼                  ▼                   ✖
┌───────────┐   ┌───────────────┐   ┌─────────────────┐
│ [Payment] │   │ <OrderPlaced> │   │ <PaymentFailed> │
└───────────┘   └───────────────┘   └─────────────────┘
                        │
                        ▼
                  ┌──────────┐
                  │ |Ledger| │
                  └──────────┘

checkout.sigil: 6 nodes, 5 edges, 0 expansions · #!sketch
lint: OK
```

**Try it:** the [project page](https://no-tably.github.io/sigil/) has a
[playground](https://no-tably.github.io/sigil/#playground) that runs these tools in
the browser — write a design, switch views, step through a simulation.

- **Spec:** [`language.md`](./language.md) — glyphs, arrows, modifiers, payloads,
  control-flow blocks, streams, zoom, composition trees (`\-` branches with the
  relations `> & ? $ @ ! = _` and qualified paths like `[Bullet]/{Transform}`),
  modes, normal form, grammar.
- **Design records:** [`rfcs/`](./rfcs/README.md) — accepted RFCs with their decisions.
- **Examples:** [`examples.md`](./examples.md) — worked prose ↔ Sigil pairs.

## Tools

All tools are Python 3 standard library only; each takes a file or `-` for stdin.
Every flag and key is in [`docs/tools.md`](./docs/tools.md).

| Tool | Does |
| --- | --- |
| `view.py FILE` | Live terminal view, redrawn on every save: a graph view and a tree view (`t`), a simulation mode (`x`) and a checks overlay (`c`). `--once` prints one drawing for agents and CI. |
| `lint.py FILE` | Validates a document: one `severity:line:rule: message` per issue; exit 0 clean, 1 warnings, 2 errors. `--deep` adds the composition checks. |
| `check.py FILE` | Composition checks ([RFC 0003](./rfcs/0003-composition-checks.md)): does the design say how its risks are handled — time bounds, idempotency, writers, failure routes, stuck state machines? A finding never forbids a shape: declare the handling, or accept the risk with a reason. |
| `render.py FILE` | Emits a Mermaid `flowchart TD` for docs (GitHub, Obsidian, mermaid.live). |
| `themes.py` | Colour themes from `themes/*.yaml`, shared by the viewer and the web page. |
| `dialects.py` | Loads a dialect (`--dialect NAME`) that extends the linter, renderer and checker. |
| `highlight/` | Syntax highlighting for bat, nvim, VS Code, Sublime/TextMate. |

## Install as an agent skill

Sigil ships as a skill (`sigil`) plus two commands (`sigil-view`, `sigil-lint`)
for several coding agents. Each GitHub release attaches one archive per agent,
`sigil-<agent>-<version>.zip` (and `.tar.gz`), plus
`sigil-{claude,codex}-marketplace-<version>` archives. Build them locally with
`./build.py` (see [Development](#development)).

### Claude Code

```sh
# from a release: unzip sigil-claude-marketplace-<version>.zip, then in Claude Code
/plugin marketplace add ./sigil-claude-marketplace-<version>
/plugin install sigil@sigil
# or try it for one session without installing
claude --plugin-dir ./sigil-claude-<version>
```

Commands appear as `/sigil:sigil-view <file>` and `/sigil:sigil-lint <file>`.

### Codex

Unzip `sigil-codex-marketplace-<version>.zip` and add it as a local plugin
marketplace (it holds `.agents/plugins/marketplace.json` → `./plugins/sigil`), or
copy the skills straight into a skills directory:

```sh
unzip sigil-codex-<version>.zip
cp -R sigil-codex-<version>/skills/* ~/.agents/skills/     # or <repo>/.agents/skills/
```

The commands become explicit-only skills: invoke them as `$sigil-view` /
`$sigil-lint`.

### pi

```sh
unzip sigil-pi-<version>.zip
pi install ./sigil-pi-<version>        # add -l to install for this project only
```

Provides the `sigil` skill and the `/sigil-view` and `/sigil-lint` prompts.

### OpenCode

```sh
unzip sigil-opencode-<version>.zip
./sigil-opencode-<version>/install.sh                   # ~/.config/opencode
./sigil-opencode-<version>/install.sh --project .       # ./.opencode
```

Provides the `sigil` skill and the `/sigil-view` and `/sigil-lint` commands.
(OpenCode also discovers skills in `~/.claude/skills` and `.agents/skills`.)

## Simulation

Sigil does not execute, but the viewer can *walk* a design: `sim.py` reads it as
tokens moving along its flows, so you can watch the happy path, each failure
route, each branch arm, race and alternative play out over the same drawing — in
the graph view and the tree view alike. No values are computed and nothing is
random; the run is a function of the design and the chosen **scenario**.

- **Scenarios** are the design's pathways, each with a stable name: `happy` (every
  default: calls succeed, `?>` not taken, the first member of a race / alternative /
  branch wins), then one per deviation — `API.charge:fails` (an op call fails:
  `Caller.verb:fails`, or `:fallback` when it falls back), `API->Payments:fails` (a
  plain call with `×N` / `@timeout` / `@fallback` / a `!>` route fails),
  `Risk?>Review` (a conditional taken), `Payments:fails` (a node with a `!>` route
  fails), `Api&?PspB` (another race winner), `Api/Err` (another alternative), a
  branch arm, … Join two with `a+b`. An unknown name prints the known ones (exit 2).
- **What moves:** `->` calls wait for their return, `~>` forks without waiting,
  `*>` and `&` fork to all and wait for all, `!>` fires only on failure, retries
  count their attempts, events drive the state machines that name them (each
  machine's current state is marked `◉`), loops and recursion are bounded.
- **The marks:** `●` a token going out, `○` a return or fallback, `✕` a failure (in
  the failure colour), `⊘` cancelled; lit wires in full colour, untouched ones
  muted; `…` waiting, `×n` spawned instances, `↻k` recursion depth.

Live, `x` enters sim mode: space plays and pauses, `,` / `.` step, `[` / `]` pick the
scenario (named in the status bar), `-` / `+` set the speed. For agents and CI,
`--once --sim SCENARIO` prints the run's last frame, the outcome and its log (here
[`examples/checkout.sigil`](https://no-tably.github.io/sigil/examples/checkout.sigil)
with its card charge failing; legend and lint summary left out):

```sh
view.py checkout.sigil --once --tree --sim 'API.charge:fails'
```

```
── checkout ──────────────────────────────
  (Shopper) ✕ ───────────────●
  [API] ✕ ◀──────────────────┴═●═✖═●═›═›═›
  [Payments] ✕ ◀───────────────┘ │ │ ║ ║ ║
  <PaymentFailed> ◀──────────────┘ │ ║ ║ ║
  |Orders| ◀───────────────────────┘ ║ ║ ║
  [Email] <OrderPlaced> ◀════════════╝ ║ ║
  [Shipping] <OrderPlaced> ◀═══════════╝ ║
  |Ledger| <OrderPlaced> ◀═══════════════╝

sim API.charge:fails (charge fails 4×, no fallback): failed · 31 frames
t000 conventions: written order; entries one after another; ?> not taken by default; the first member wins a race / alternative / branch
t000 episode 1: (Shopper)
t000 (Shopper) -> [API] : {Cart}
t005 [API] -> [Payments] : charge(total) attempt 1/4
t009 attempt 1/4 failed
t010 [API] -> [Payments] : charge(total) attempt 2/4
t014 attempt 2/4 failed
t015 [API] -> [Payments] : charge(total) attempt 3/4
t019 attempt 3/4 failed
t020 [API] -> [Payments] : charge(total) attempt 4/4
t024 attempt 4/4 failed
t025 [API] failed: charge(total) failed after 4 attempts
t025 [API] failed → <PaymentFailed>
t030 (Shopper) failed: {Cart}
t030 episode 1 failed
t030 done: failed
```

An agent designing with you runs every scenario at once: `--sim all` prints, with no
drawing, a line per run (name, outcome, frames, label) and the facts that judge it
(each state machine's end state, what failed, the routes taken, any bound hit), then
a summary. Diff two versions' tables to see what a change did to the design's
behaviour; `--sim list` lists the scenarios and `--json` prints either as JSON.

```sh
view.py orders.sigil --once --sim all
```

```
happy                    ok       32 frames  every default: the happy path
  states: [Checkout] Idle · {Order} Settled
Payments:fails           failed   32 frames  Payments fails → Declined
  states: [Checkout] Idle · {Order} Cancelled
  failed: [Payments]
  routes: [Payments] !> <Declined>
2 scenarios: 1 ok, 1 failed, 0 cut
```

## Themes

One YAML file colours both the terminal viewer and the web page:
`themes/sigil.yaml` (the default) holds a `palette` of named colours and the roles
built from it — `kinds` (box colours by glyph; `kinds.service` colours
`[component]` glyphs), `edges`, `syntax` (code highlighting), `ui` (viewer
chrome) and `site`. A value `$name` refers to `palette.name`, so a role follows
its palette colour; a new theme can start with `extends: sigil` and override
only what it changes. Drop it in `themes/` or a directory on `SIGIL_THEME_PATH`.
The format is a small YAML subset (nested maps, scalars, `#` comments) that
`themes.py` and the page both parse without a YAML library.

## Web page

`site/` is a static page: an explainer, a live editor that types the examples in
`site/examples/` line by line while `view.py`'s tree and graph views redraw in a
3D background, the skill, and install commands. `site/build_site.py` renders every
typing step through `view.py` into `frames.json` and turns the theme YAML into CSS
variables; `.github/workflows/pages.yml` publishes it with GitHub Pages.

The **playground** runs the tools themselves in the browser: the build copies
`view.py`, `lint.py`, `sim.py` and the modules they load into `py/` byte for byte, and
[Pyodide](https://pyodide.org) runs them when a visitor presses *start*
(`site/playground.py` is the thin JSON layer the page calls). Write a design, switch
views, read the lint, pick a scenario and step through its run; *share* puts the
document in the link. Nothing about the notation is re-implemented in JavaScript, so
the page cannot drift from the CLI (`tests/test_site.py` checks the copies and that
the playground draws what `view.py` draws).

```sh
python3 site/build_site.py --out _site && python3 -m http.server -d _site 8000
```

`?theme=NAME` previews another theme from `themes/`.

## Dialects

Plain Sigil is domain-neutral. A **dialect** layers extra vocabulary on top —
additional modifiers, lint passes and render rules — without changing the core
language. Dialects are Python modules loaded by `dialects.py` from a path or
from directories on `SIGIL_DIALECT_PATH`; select one with `--dialect NAME` or
`SIGIL_DIALECT=NAME`. For example, `sigil-merlang` (maintained separately) adds a
component type system and UI-layout vocabulary for one agent runtime. See
"Dialects" in [`language.md`](./language.md) for the extension API.

## Development

```sh
python3 -m unittest discover tests          # all tests
./build.py                                   # build every target into dist/
./build.py --target claude --version 1.2.3   # one target, explicit version
./build.py --check                           # validate dist/ (CI runs this)
```

### Layout

The modules sit flat at the top level so each runs as a script, ships into the
skill's `scripts/` unchanged and runs byte for byte in the playground:

```text
render.py    parse a design into a graph; render it as Mermaid        ┐
lint.py      the linter (SGLnnn)                                     │ the core
dialects.py  layer-1 hooks: extra vocabulary, rules, a rule pack     ┘
scene.py     one shared scene: wires, roles, colours, notes, joins   ┐
sim.py       the simulator: scenarios → runs of frames               │ the engine
check.py     the checker (SGCnnn) and its rule modules:              │
  check_flow.py · check_state.py · check_trace.py · check_inv.py     ┘
view.py      the terminal viewer app                                 ┐
viewkit.py   its drawing kit                                         │ the viewer
view_graph.py · view_tree.py   the graph and tree views              │
themes.py    YAML themes (themes/), shared with the page             ┘
build.py     packaging (maintainers only)
site/  the page and playground · tools/  golden drawings, doc regeneration
docs/  the tools reference, viewer coverage audit · rfcs/  design records
tests/  unit tests, fixtures and golden drawings · highlight/  editor grammars
```

`build.py`'s `TOOLS` is the one list of shipped modules; the page's playground copies
the same list, and a test fails if a new top-level module is missing from it.

Canonical packaging sources — edit these, never `dist/`:

- `skills/sigil/SKILL.md` — the skill, with spec-only frontmatter and paths
  relative to the skill (`scripts/…`, `references/…`).
- `plugin/meta.json` — name, version, description, author, keywords.
- `plugin/commands/*.md` — commands, using `$1` / `$ARGUMENTS` and the
  `@SCRIPTS@` placeholder for the skill's scripts directory.

`build.py` copies `lint.py`, `render.py`, the viewer (`view.py` with `viewkit.py`,
`view_graph.py`, `view_tree.py`, `scene.py` and `sim.py`), the checker (`check.py` with `check_flow.py`,
`check_state.py`, `check_trace.py` and `check_inv.py`), `dialects.py` and `themes.py`
(with `themes/*.yaml`) into `skills/sigil/scripts/` and `language.md` / `examples.md` into
`skills/sigil/references/`, then writes each agent's manifests. Archives are
deterministic. CI (`.github/workflows/ci.yml`) tests, builds and validates on
every push; pushing a `v*` tag builds with that version and attaches the
archives to a GitHub Release.

## License

MIT — see [`LICENSE`](./LICENSE).
