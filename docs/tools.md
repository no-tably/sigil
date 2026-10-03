# Tools reference

Every tool is a Python 3 script with no dependencies beyond the standard library.
Each one takes a file, or `-` for stdin. The [README](../README.md) has the overview.

## `lint.py FILE|-`

Validates a document and prints one `severity:line:rule: message` line per issue.
It exits 0 when clean, 1 on warnings and 2 on errors.

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
binding rules errors. The line format and exit codes match lint.

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

A live terminal view of the design that redraws on every save. It has a graph view
and a tree view (the composition tree as an outline, with every flow as a lane
beside it).

Options:

- `--once` prints the drawing and a lint summary, then exits (1 on a lint error).
- `--tree` starts in the tree view.
- `--depth N|all` opens `X := { … }` expansions.
- `--payloads` shows flow payloads: chips on edges in the graph view, a list in the
  tree view.
- `--mods` shows modifiers (`@timeout 30s ×3`, `^10k drop`, `!`) as chips on edges and
  after node labels.
- `--access` draws the permission graph. `@read`, `@write` and `@borrow` become dotted
  principal → store edges headed `r`, `w` or `b`. Stores get a `1w` or `Nw` writer badge.
- `--events land|nodes` draws a pass-through event where it lands (each emitter wired
  straight to each destination) or as a node of its own. The tree view defaults to
  `land`, the graph view to `nodes`.
- `--notes markers|callouts` shows comments as `#N` tags with a notes list, or as boxes
  in a left margin tied to their rows (tree view).
- `--sim SCENARIO` runs one pathway of the design and draws its last frame (see
  [Simulation](../README.md#simulation)).
- `--checks` marks composition-check findings on the drawing, with a checks legend.
  Each finding's question follows the lint summary.
- `--compact` starts without the blank row between top-level units.
- `--no-triggers` starts with event ⇢ state triggers hidden.
- `--no-lint` skips lint.
- `--theme NAME` picks a colour theme (see [themes](#themespy-namepath)); `--color
  auto|always|never` decides when to colour.
- `--width N` fits a `--once` drawing to N columns (default: the terminal's width, or
  100 when stdout is not a terminal).
- `--dialect NAME` draws with a dialect.

Both views also draw:

- control blocks. The graph view draws titled frames (`↺ loop …`, `∥ parallel …`,
  `◇ branch on …` with a decision node and arm chips, and `□ scope`). The tree view
  draws brackets in a left gutter.
- `&`, `&?` and `/` joins, `--- section ---` dividers, `[[alias]]` nodes, and the
  `#!mode` in the status bar.

Live keys:

| Key | Does |
| --- | --- |
| `t` | tree / graph |
| `x` | sim mode; then space play / pause, `,` `.` step, `[` `]` scenario, `-` `+` speed |
| `c` | checks overlay |
| `n` `e` `v` | notes · triggers · events (where they land / as nodes) |
| `p` `m` `a` | payloads · modifiers · access |
| `d` `s` `l` | depth · spacing · lint |
| `f` | fit to the window / natural layout with free pan |
| arrows, `h` `j` `k` `L` | pan; mouse drag pans, the wheel scrolls (shift+wheel across) |
| `z` `g` | centre · home |
| `r` `q` | reload · quit |

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
