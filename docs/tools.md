# Tools reference

Every tool is a subcommand of one command, `sigil`, with no dependencies beyond
the Python 3 standard library: run `bin/sigil` (or `python3 -m sigil` from the
repository). `lint`, `check`, `export --mermaid` and `highlight` take `-` for stdin; `view`
needs a file, since it redraws on save, and the folder export needs one too, since
the manifest names the spec file (and its stem is the top system's default name). The [README](../README.md) has the overview.

## The command

```
sigil lint FILE|- [--deep] [--dialect D]
sigil check [FILE|-] [--mode M] [--k N] [--budget N] [--limit NAME=N] [--overlaps …] [--json] [--export] [--all-rules] [--rules]
sigil view FILE [--once] [--graph|--tree|--flow|--run] [--sim S] …
sigil view FILE --structure [--json]
sigil export SPEC --out DIR [--name NAME] [--limit NAME=N] [--json] [--dry-run]
sigil export FILE --mermaid [--depth N|all] [--composition subgraphs|edges|none]
sigil export FILE --mermaid --spine [--name NAME]
sigil frames draw FILE [--view V] [--depth N|all] [--width N] [--scenario S] [--limit NAME=N] …
sigil frames follow CONTROL
sigil themes [NAME|PATH] [--list]
sigil highlight FILE|- [--theme NAME|PATH] [--dialect D] [--json]
sigil highlight --stream [--theme NAME|PATH] [--dialect D]
```

`sigil` with no subcommand prints that list (exit 2), and `sigil --help` prints it
too (exit 0); `sigil CMD --help` gives each subcommand's flags. Each subcommand loads only the parts of
the package it needs, so `sigil lint` never loads the simulator or the views. Every
subcommand that reads a document (`lint`, `check`, `view`, `export`, `frames draw`,
`highlight`) takes `--dialect NAME` (see [Dialects](#dialects)).

**The package.** `bin/sigil` puts the package on the path and calls `sigil.cli`.
The package is `sigil/`, one subpackage per layer, as drawn in
[`design/sigil.sigil`](../design/sigil.sigil) (each expansion there is a layer):

| Layer | Holds |
| --- | --- |
| `sigil/core` | the notation read: `lex` (the lexical tables, kept once), `tokens`, `statements`, `parse` (a document → the graph model in `graph`), `comments`, `dialects`, `vocab` (the dialect API) |
| `sigil/model` | what a design does: `scene`, the simulator `sim/` (`program`, `engine`, `scenarios`, `narration`), `systems` (the export model), `structure` (the design read as units) |
| `sigil/analyse` | is it sound: `lint/` (SGLnnn, a module per rule group), `check` (SGCnnn: registry, findings, acknowledgements, budget), `rules/` |
| `sigil/publish` | what leaves sigil: `mermaid`, `spine`, `systems`, `exporter`, `delta` |
| `sigil/present` | the drawings: `app` (the live viewer), `views/` (graph, tree, flow, run), `kit`, `themes`, `frames`, `highlight` (the source as coloured runs) |
| `sigil/cli.py` | the command: argument parsing, `lint --deep` (lint and check joined here, not in a layer) |

**The layer rule.** A layer imports only the layers above it:
`core ← model ← analyse ← publish / present ← cli`, and publish and present never
import each other. No module loads another by path; the one exception is
`core/dialects.py`, since a dialect is a file beside the package.
`tests/test_spine.py` checks every import, lazy ones too.

## Exit codes

Every subcommand shares one table, and prints its errors to stderr after its own
name: `sigil lint: message`, `sigil check: …`, `sigil view: …`, `sigil export: …`
(`--mermaid` included); its usage line names it the same way.

| Code | Means |
| --- | --- |
| 0 | OK: nothing to report (`--sim all` and `--rules` always exit 0) |
| 1 | warnings, no errors (info alone exits 0) |
| 2 | errors: an error-severity diagnostic or finding, bad usage, or input the tool cannot read |

Two exceptions: `sigil view --once` exits 1 on a lint error, since the drawing is its
output, and `sigil export` exits 1 when it cannot write the folder and 2 when the spec
is not ready to export.

## `sigil lint FILE|-`

Validates a document and prints one `severity:line:rule: message` line per issue.
Its exit code follows the [table](#exit-codes): 0 clean, 1 warnings, 2 errors.

Lint reads a document once, the same way the parser does: one statement walk and
one tokenizer (`sigil/core/statements`, `sigil/core/tokens`) give both the model
every other subcommand draws and checks and the lines lint's rules judge. So a
rule reports what the drawing shows: a `#`, a brace or a `\-` inside a `"…"`
string is string text, and a branch marker counts only where the tree reads one.

- `--deep` also runs the composition checks (`sigil check`) and merges both reports into
  one list by line. Acknowledged findings come last, as `accepted:` lines. The exit
  code is the worse of the two.
- `--dialect NAME` lints with a dialect's extra vocabulary (see [Dialects](#dialects)).

## `sigil check FILE|-`

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
- `--budget N` caps the runs one exploration may make: the failure combinations
  first, then (in `#!spec`) the state starts, then the overlap runs (each later
  entry started at every tick of an earlier entry's episode; see [Runs that
  overlap](../README.md#runs-that-overlap)), so a race between two entries is found
  and its witness names the `Entry@t` run. A state start begins one state machine in
  a later state (`Owner=State`, one run per state a transition leaves; see `--sim`
  under [`sigil view`](#sigil-view-file)), so a way out of that state is walked; a
  finding only it shows names it as the witness. They run whatever `--overlaps` or
  the `#%` kind says, and an event on the machine's way to that state arriving
  again is the replay, not an `event-ignored` (SGC203) drop. A check that ran out
  of budget says so (SGC090, a hint, counting the unrun combinations, state starts
  and overlap runs) and names `--budget N`.
  The overlap runs also stop at a **work cap**: 400 frames a run × the budget (a
  budget below the default 256 counts as 256), so a large spec's sweep takes
  seconds, not minutes. When the cap stops the sweep, SGC090 says how many overlap
  runs were left and how far the frames got (`58 overlap runs (…; their frames
  reached the work cap: 103729 of 102400)`), and its fix names `--budget N` (above
  256 it raises the cap), `--overlaps listed` or a smaller `--k`.
- `--limit NAME=N` raises one simulator limit (repeatable, e.g. `depth=5`;
  `window=N` the start ticks tried per pair of entries, 64), as `sigil view
  --limit` does: every run check makes, and the scenario list it draws them from,
  use the raised limits. The default `frames` and `activations` grow with the
  document (see `--limit` under [`sigil view`](#sigil-view-file)), so most designs
  finish their runs without it. When a run is still cut short by a limit, SGC090
  names the limit, the run and the limits it had, with the fix `raise --limit
  frames=N until no run is cut, or acknowledge on the entry's line`. In `#!spec`
  that finding is a **warning**, so it also blocks the export gate: a spec whose
  runs never finished is not ready. When what ran is enough, acknowledge it on the
  line of the entry whose episode was cut (`# accepts: exploration-incomplete — …`).
  Failure scenarios come from the design alone and are listed at any limits; an
  overlap scenario needs the happy run to reach its start tick, so a happy run cut
  at its `frames` lists its overlaps only with `--limit frames=N` raised.
- `--overlaps off|listed|all|N` says which overlap runs to make. `off` makes none,
  and `listed` makes the listed `Entry@t` runs, alone and with each failure. `all`
  makes those, then every start tick, and `N` is `all` but at most N runs. The
  default is `all` in `#!spec` and `off` in sketch and craft: the sweep is the
  exhaustive check you run before a spec is final, not on every edit. `--json`
  reports the setting as `limits.overlap_runs`.
- `--all` also shows hidden findings.
- `--json` prints one JSON object: the mode, `k`, the `limits` (as the runs had
  them: `frames` and `activations` grown to the document; with `budget`, `k` and
  `overlap_runs`) and every finding
  with its rule, tier, why, how to satisfy (`fix`), witness (and `at`, the tick in
  the witness run where a behavioural finding shows), plus the acknowledged ones.
- `--export` also runs the export readiness rules, SGC401 `no-home` and SGC402
  `untyped-boundary` (see [`sigil export`](#sigil-export-spec---out-dir)). Without it they never
  run, so no other output changes.
- `--all-rules` also runs the rule groups the document's `#%` kind line turns off
  (language.md, "System kind"). Without it, the summary names the rules that kind
  turned off, and `--json` lists them under `kind` (`{"words": …, "off": [ids]}`;
  no `kind` key without a `#%` line). A `deterministic` kind also makes no overlap
  runs unless `--overlaps` is given.
- `--rules` lists the rules, each with its tier and group, and exits.
- `--dialect NAME` adds a dialect's rule pack.

Two structure rules read the units that [`sigil view --structure`](#sigil-view-file---structure)
lists, so the two never disagree: SGC176 `unit-cycle` (two sibling units whose
flows depend on each other; info in craft, a warning in spec, acknowledged on the
header of a unit in the cycle, never document-wide) and SGC177 `large-unit` (a unit
with more than 9 built members, actors not counted; info). A flow from a unit into
one enclosing it is never a finding. The web page's playground runs without them.

See "Checks" in [`language.md`](../language.md).

## `sigil export SPEC --out DIR`

Exports a ready `#!spec` document as a build skeleton: a folder per system, a file
per component, and `manifest.json` as the contract. Whoever builds against it reads
the manifest first. Building itself happens outside sigil.

**The gate.** Only a ready document exports: its mode line is `#!spec`, `sigil lint`
reports no error, and `sigil check --export` (spec mode, so the overlap runs too) leaves
no error and no warning unacknowledged; info findings are fine. Otherwise
`sigil export` prints the lines that block it, exits 2 and touches nothing.

**Systems** are read off the design, with no syntax of their own (see "Ready to
export" in [`language.md`](../language.md)): every `X := { … }` expansion is a
system named `X` (a nested one is its own system, and its parent depends on it),
every composition-tree root is a system holding its tree, and every other node is in
the top system, named after the spec file's stem (or `--name`). A top-level service
with the top's name (`[Shop]` in `shop.sigil`) is the top's face, not a second
system. Each component has one **home**: a level that names a part only in its flows
(or in passing: a block's subject, an arm, a borrow, a join) is never its home when
another level declares it.

- `--out DIR` the export folder, made when missing. It must be empty or hold an
  earlier export (a `manifest.json`); `sigil export` never writes over a folder it did
  not make.
- `--name NAME` names the top system (and its folder) instead of the file's stem. No
  hash depends on the top system's name, so renaming the spec, or exporting it under
  another name, moves no hash; the top's key and folder follow it, and the delta
  reports the move as `renamed`. A name that matches a top-level service rooting a
  tree or owning an expansion (by folder name: `--name shop` and `[Shop]`) makes that
  service the top's face: its tree or expansion is the top system, not a system of
  its own (this reverses 0.6.1, where `--name` renamed no system; the systems, and so
  their hashes and folders, then change). A top named like a system of another kind
  (a store's tree) is keyed `NAME (top)`, and that system keeps its name. A blank
  name is refused (exit 2).
  `--mermaid --spine` takes it too; plain `--mermaid` refuses it.
- `--dry-run` prints the delta and writes nothing.
- `--json` prints the delta as JSON instead of the summary in words.
- `--limit NAME=N` raises one simulator limit for the gate's check (repeatable,
  e.g. `frames=20000`), as `sigil check` takes it. A run cut at a limit is a
  warning in spec mode, so it blocks the export until the limit is raised or the
  cut is acknowledged on its entry's line.
- `--dialect NAME` loads a dialect, as `lint`, `check` and `view` do.

Exit codes: 0 exported (or a dry run), 1 the folder could not be written, 2 not
ready to export or bad input (an unreadable spec, an unknown dialect, a folder
`sigil export` did not make, a `manifest.json` it cannot read).

**The folder.**

```
DIR/
  manifest.json            the contract, written last (temp file, then renamed)
  delta.json               what changed since the manifest before (on a first
                           export: every system added)
  README.md                the index: systems, what each depends on
  <system>/README.md       the system: description, components, boundary, deps
  <system>/<component>.md  kind, description, interface, requirements, lifecycle
  <system>/system.json     the same, machine-readable
```

Folder and file names are slugs of the names: stable, ASCII-safe and
collision-free. A component file states, as the spec writes them: its **kind**; its
**description** (its `#` comments); its **interface** (every flow in or out, with the
peer, verb, payload, what a call returns, sync or async, failure routes and the
call's policy); its **requirements** (the modifiers on it, the access it is granted,
and every `# accepts:` acknowledgement covering it, verbatim); its **lifecycle** (its
state machine, when it has one). No target-language types.

**`manifest.json`**:

```
{"sigil_export": 1, "spec": <file name>, "spec_hash": …, "top": <key>,
 "dialect": {"name": …, "version": …},
 "systems": {name: {"path", "interface", "body", "components", "depends_on",
                    "parent",
                    "component_hashes": {glyph: {"interface", "body"}}}}}
```

`spec_hash` is the hash of the spec file's text as written (so a reformat moves it).
`top` is the top system's key (the first of `systems`).
`dialect` is there only when a dialect was loaded: its `NAME`, and its `VERSION`
(as text) when the dialect module defines one; with no dialect the key is absent.
`path` is the system's folder, `components` its glyphs, `depends_on` the systems
its flows reach, the ones nested in it, and the systems that hold the data its flows
carry (a homed `{D}` named in a payload, op arguments or return; not hashed);
only the system's own flows, never what it inherits from the systems enclosing it.
`parent` is the enclosing system's key (null for the top), as `system.json` has it,
so a delta reads the nesting from the manifests alone; no hash reads it.
`component_hashes` each component's two hashes, in the order of `components`.

**The hashes.** A system's `interface` is the hash of the flows that cross its
boundary, with their payloads and returns; its `body` the hash of everything in it:
interface, members, internal flows, control blocks, descriptions and its `#&`
declarations. A component's `interface` covers its flows in and out, with their
modifiers; its `body` its whole form: kind, home, the other systems it is written
in, a dialect's `attrs`, description, interface, requirements and lifecycle. A
component's hashes enter no system's hash (both are read off the same form). All
are sha256 over a normalised JSON form, first 16 hex digits. No line number,
whitespace, statement order or top system name enters any of them, so reformatting,
reordering or renaming the spec changes none; changing a payload, a modifier, a
description, a state or a declaration's body does (a declaration's body is kept as
written, so even its spacing counts). The manifest's hashes are the truth; written
last, it is what marks a finished export.

**`system.json`** is the system's normalised form: `name`, `kind` (`top`,
`expansion` or `tree`), `face` (the glyph the system is named after), `parent`,
`depends_on`, `description`, `interface` and `flows` (the flows inside), `shapes`,
`blocks`, `components`, `accepts` (the acknowledgements on it), `declarations` and
`hashes` (`{"interface", "body"}`). Keys with no value are left out. `blocks` are the
control blocks written in it, `[{"kind", "header", "mods"}]`.

`shapes` are the data shapes its interface covers: those of the data its boundary
flows carry (a payload, op arguments, a return, or a data glyph at one end) that have
a shape written (`{Doc} := { path, note? }`), the data its face's tree holds (every
`\-& {X}` below the face, listed even with no shape written), and each nested shape
a field of those names. Each is `{"glyph", "fields", "held"}`: `glyph` the data's
glyph (`{Doc}`); `fields` sorted by name, each `{"name", "optional", "shape"}`
(`optional` only when `?` marks it, `shape` the nested glyph a field names, `rows:
{Row}` or `{Row}`), `[]` for a shape with no fields and left out when none is
written; `held` true when the face's tree holds it. The list is sorted by glyph.

A flow holds:

| Key | Holds |
| --- | --- |
| `from`, `to` | its two glyphs; in a component's `interface` instead `dir` (`out`, `in` or `self`) and `peer`, the glyph at the other end |
| `arrow` | the arrow as written (`->`, `~>`, `=>`, …) |
| `mode` | `sync`, `async`, `return`, `failure`, `optional`, or `flow` (a dialect's arrow) |
| `payload` | the `: payload` text, tightened |
| `text` | the body of a `"""…"""` payload |
| `op`, `returns` | the call's verb with its arguments, and what `=>` it returns |
| `external` | `true` for an external `op ns.verb` call |
| `mods` | the call's modifiers (its policy), each `[name, arg]` (`arg` null when bare) |
| `card` | the destination's cardinality written on the flow (`×N`): `"N"`, `"4"` |
| `implied` | `"return"` or `"alert"` for a flow the notation implies without an arrow |
| `from_path`, `to_path` | a qualified-path end (`[Bullet]/{Transform}`), as written |
| `lines` | the spec lines that write it |

A component holds `name`, `kind`, `glyph` (as written, a dialect kind in its own
brackets), `home`, `also_in` (the other systems it is written in), `attrs`,
`description` (its comment lines), `interface` (flows, as above), `requirements`
(`{"modifiers": [[name, arg]…], "access": [[store, mode]…], "accepts": [text…]}`),
`lifecycle` (`{"states", "initial", "terminal", "transitions": [{"from", "to", "on",
"mods"}]}`), `shapes` (as a system's: the shaped data its flows carry, its own shape
when it is data, and the data its tree holds, its own `\-&` children), `lines` and
`hashes`.

- `lines` are the 1-based lines of the spec that write a flow or a component, to
  jump back to the source. No hash reads them.
- `declarations` are the `#& name …` lines (see "Dialects" in
  [`language.md`](../language.md)) of the system's scope, as `{"name", "body",
  "line"}`: one at the top level or in an alias body goes to the top system, one in
  an expansion's body to that system. `body` is the text as written: the inner
  lines of a `{ … }` block, the text between the braces of a one-line block, or the
  text after the name when there is no block. A dialect's `DECLARATION_BLOCKS`
  openers are not exported.
- `attrs` is what a dialect's tokenizer put on the glyph's node (`Node.attrs`),
  only when there is some: values as JSON holds them (a tuple as a list, a set as a
  sorted list, anything else as its text). Core glyphs never carry any.

**Re-export and the delta.** Before writing, `sigil export` reads the manifest already
in DIR and sorts every system into one list:

| Class | Means |
| --- | --- |
| `added` | in the new export only |
| `removed` | in the old one only; its folder is deleted |
| `rebuild` | its body hash changed |
| `recheck` | its body is unchanged, but a system it depends on changed its interface, or a system an enclosing system depends on (outside that enclosing system) did |
| `unchanged` | neither |

`delta.json`: `{"sigil_delta": 1, "spec", "from": <old spec_hash>, "to": <new
spec_hash>, "renamed", "added", "removed", "rebuild", "recheck", "unchanged",
"systems": {name: {"status", "old", "new", "because"?, "via"?}}}`, where `old` /
`new` are `{"interface", "body"}` (or null) and `because` lists, for a recheck, the
systems whose interface changed: its own dependencies first, then those it inherits
from the systems enclosing it. `via` (only when it inherits one) maps each inherited
one to the nearest enclosing system it came through, and the summary in words says
it the same way (`recheck    Leaf (interface changed: Store (via Outer))`). A nested
system's members make up the systems enclosing it, so they use what those depend on;
`depends_on` still lists only its own flows, and no hash moves. An old manifest
without `parent` fields (before 0.6.5) still compares: the nesting is read from the
new one. `renamed` is `{"from", "to"}` when the top system's key
moved (another `--name`, or the spec renamed), else null: the top is then compared
with its old entry, so the rename alone adds, removes or rechecks nothing. Each file is written only when its content changed, so an unchanged
system's files are left alone, and in a changed system only the files that differ
are rewritten. A reformat that moves lines rewrites the `system.json` files whose
`lines` moved (with the index `README.md`, `manifest.json` and `delta.json`), and no
component file. A system folder may also hold a builder's own files:
`sigil export` deletes or compares only the files an earlier export wrote (the names
in its manifest), and a removed system's folder stays while it holds others. Every
export writes `delta.json`; a first export's has `"from": null` and lists every
system as `added`. The delta is a hint; the manifest's hashes stay the truth.

## `sigil view FILE`

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
  members hang off dotted rails, `├┄┄`, apart from a branch's solid `├──`). The
  graph, tree and flow views open one level by default. The run view draws every
  level unless `--depth` is given; then a deeper expansion's lanes fold into its
  node's lane, and a run's narration and path name only the nodes drawn
  (`--run --json` and `--sim NAME --json` fold the same way when it is given). A
  node busy on its folded expansion's work counts as busy, so that stretch never
  folds into `≈`, and a loop inside the folded expansion is narrated as the node's
  ("[Shop] loops (inside)") and counted in its lane's note ("loops 3× (inside)";
  `--json` marks those iterations `"inside": true`).
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
  and tagged on nothing. A comment-only line right below a trailing comment, its `#` in
  the same column, continues that comment (one note on the line above, not a note
  on the next statement); a `# accepts:` line never does. So does a comment-only
  line right below a statement line with no comment of its own that opens no block,
  its `#` deeper than that line's first column: it is that line's note (lines below
  in its column go on with it), not the next statement's.
- `--sim SCENARIO` runs one pathway of the design and draws its last frame, then the
  outcome and the run in plain words, one `tNNN …` line per step (`[API] calls
  [Payments] with charge(total) — attempt 2 of 4`; see
  [Simulation](../README.md#simulation)). With `--json` it prints that run as JSON
  instead, with no drawing: the facts `--sim all` lists, `steps` (frame, tick, text)
  and the simulator's raw `log`; an overlap run (`Entry@t`) adds `episodes`, each
  one's number, entry and start tick. `--sim list`
  prints the scenarios, one per line with its label: `happy`, the deviations, then
  the overlap scenarios `Entry@t` (a later entry started at tick t, while an earlier
  one's episode is touching something it touches; at most 3 per pair of entries, 12
  in all), then the state starts `Owner=State` (a state machine begun in State, so a
  way out of a later state is walked: one per state, other than the initial one,
  that a transition leaves; label `starts with {Ticket} in Done`; the narration's
  first line says `{Ticket} starts in Done`). Any `Entry@t` runs by name, as does
  any `Owner=State` whose state the owner's block names (`+` and `$` are not
  states to begin in; an unknown state is refused with the owner's states listed),
  and each combines with `+` (`Builder.claim:fallback+Author@25`,
  `Ticket.kind=urgent+Ticket=Done`). `--sim all` runs every scenario
  and prints no drawing: a line per run (name, outcome, frames, label), indented
  facts (`states:` each machine's end state, `failed:`, `routes:` the failure routes
  taken, `ignored:` events a state had no transition for, `waiting:`, `open:` joins
  left open, `bounds:` base case, visit limit, spawn cap, a capped loop, a cut) and a
  summary line. It always exits 0; diff two versions' tables to see what changed.
  `--json` prints either as JSON. `--run --json` prints the run's timeline as data
  (lanes with their labels, spans with their waits, moves, marks, and `episodes`:
  each episode's number, start tick, entry and the episodes still running when it
  began, `with`) — the scenario's, else the happy one.
- `--frame N|last` and `--play` start the live view's run (`--sim`) at frame N
  (0-based) or its last, and playing. Without them it starts paused on the first
  frame. The agent plugins' split passes them. With `--once`, `--frame` picks the
  frame drawn in any view (the run view puts its playhead there) instead of the
  last.
- `--limit NAME=N` raises one simulator bound for `--sim` (repeatable): `iterations`
  (loop repetitions, 2), `depth` (recursion, 3), `spawn` / `spawns`, `visits`, `stack`,
  and the per-episode `frames` and `activations`; `overlaps` (12) and
  `pair_overlaps` (3) cap the overlap scenarios listed. The defaults of `frames`
  and `activations` grow with the document: 128 and 20 × its nodes plus edges
  (every level, each counted where written), never below 2000 and 500, so a large
  design finishes its runs at default limits and a small one is unchanged
  (02-shop gets 4736 frames and 740 activations). A given `--limit` wins. Each
  entry point runs as its own episode with its own `frames` and `activations`
  (`frames` counted from the latest episode's start), so a large design runs every
  entry in full. A run that still ends `cut` names the bound it hit, the episode
  that reached it and the tick it started from (`the run is cut: episode 1 reached
  the frames limit, 20 frames from t0`; in `--sim all`, `bounds: cut: frames limit
  (20 frames of an episode, from t0)`).
- `--structure` prints no drawing: the design read as units (see
  [below](#sigil-view-file---structure)). `--json` prints the same as data.
- `--checks` marks composition-check findings on the drawing, with a checks legend.
  Each finding's question follows the lint summary.
- `--compact` starts without the blank row between top-level units.
- `--no-triggers` starts with event ⇢ state triggers hidden.
- `--no-lint` skips lint.
- `--theme NAME` picks a colour theme (see [Themes](#themes)); `--color
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
runs along a return row under the drawing (`╰──╯`), and wires back from one source
to one target share that row as one bundle. Strokes, heads, colours, chips,
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
edges passing a layer take its room too, and a fan-out's edges pass the wrapped rows
as one trunk), and each row of boxes, each row of
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
sub-rows under it, activations that run on one lane at once (other tasks') as `∥2`
sub-rows, an expansion's lanes indented under its node:

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
boundary between episodes (an episode that begins while another runs gets no
boundary, only its start mark `ep2`, in its run colour, and a line under the drawing
lists the episodes, `episodes  ep1 (Operator)@0   ep2 (Author)@25`, with `▸` on the
running ones while it plays), `↺2` where a loop's next iteration starts ("loops 2×"
in the note of the lane running it), and with the checks overlay (`c`) a finding's
number at the tick this run shows it, when the run is its witness. These marks (and
`ep2` for an episode) sit on a row of their own above the ruler's scale, so they
never hide its ticks; when `↺k` marks crowd, only every second, fifth, tenth …
one is labelled (findings and episodes are placed first). A
spawned lane carries `◌` while its spawn hop flies;
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
narration line, `›` and what is happening now. While more than one episode runs
(a run that overlaps), each narrated sentence starts with its episode (`ep2: `), and
the graph, tree and flow views draw each token as its episode's number in that
episode's colour (theme section `run`); with one episode nothing changes. The path is numbered by branch: a
run of hops that starts again from a node already on the path is a new branch,
`①` `②` … (`(21)` past `⑳`), three spaces apart —
`① (Shopper) -> [API] -> [Payments] ✖×4   ② [API] !> <PaymentFailed>`. A hop that
failed on arrival is marked `✖` (`✖×4` when repeated; `×N` alone a hop repeated),
a cancelled one `⊘`, and the hop a token is on now is bold, as its wire is (`▸`
before it with `--color never`). It takes two rows at most; a longer path folds its
oldest branches into `①–③ …` so the newest stay readable. `--once --sim` prints
the path at the run's last frame (or `--frame`'s) under its outcome line. The view follows the run's tokens
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

### `sigil view FILE --structure`

Reads the design as units instead of drawing it: the numbers to look at when
refining a design's shape. It runs in any mode (no gate), prints no drawing, always
exits 0, and `--json` gives the same as data (`top`, `units`, `cycles`, `up`,
`edge`, `reach`, `pass_throughs`, `large`, `repeated`, `writers`, `summary`). The
units are the systems an export would make (the top, each expansion, each tree
root), so this reading and an export never disagree, and `sigil check`'s structure
rules read the same units. For `site/examples/02-shop.sigil`:

```
units
  02-shop  top · 5 members · 3 internal flows
    members: [Edge] · [Shop] · |Catalog| · [Fulfilment] · |Ledger|
    calls: Shop
    nests: Fulfilment · Shop
  Shop  expansion in 02-shop · 4 members · 4 internal flows
    members: <OrderPlaced> · [Cart] · [Checkout] · [Payments]
    calls: 02-shop · Fulfilment · Payments
    nests: Payments
  …
  Fulfilment  expansion in 02-shop · 2 members · 2 internal flows
    members: [Picker] · [Packer]

cycles (units whose flows depend on one another)
  (none)

up (a unit's flows into a unit enclosing it)
  Shop → 02-shop
      [Shop] -> |Catalog|  (line 8)
      <OrderPlaced> *> |Ledger|  (line 9)
  Risk → Payments
      [Risk] ?> [Review]  (line 22)

edge (parts that call an actor)
  [Packer] in Fulfilment → (Courier)

reach (what each part can drive / be driven by, largest first)
  [Edge]         out  15  in   0  02-shop  → (Courier)  ← (Shopper)
  [Shop]         out  14  in   1  02-shop  → (Courier)  ← (Shopper)
  …
  |Catalog|      out   0  in   2  02-shop  ← (Shopper)

pass-throughs (one caller, one callee, no actor)
  (none)

units over 9 members
  (none)

a name declared in two units (one name, one entity)
  (none)

writers per store
  |Catalog| in 02-shop  0: no writer
  |Features| in Risk  0: no writer
  |Ledger| in 02-shop  0: no writer

6 units: 0 cycles, 2 up, 1 edge part, 0 pass-throughs, 0 over 9 members, 0 names in two units, 0 stores with two or more writers
```

- **units**: each unit, its kind and where it sits, its members (the built parts
  homed there: services, stores, events, data; actors are not built, so they are
  kept apart, as `actors` in the JSON), its internal flows, the units its flows call
  (`calls`) and the units nested in it (`nests`). A flow to or from an actor makes
  no dependency.
- **cycles**: sibling units (neither encloses the other) whose flows depend on one
  another round, with every flow that makes the cycle. A flow from a part of a
  nested unit counts as its enclosing unit's. Each cycle is one SGC176 `unit-cycle`
  finding.
- **up**: a unit's flows into a unit enclosing it, here `[Shop]`'s parts leaning on
  the top level's stores. Listed only, never a finding: most layered designs have
  them.
- **edge**: the parts that call an actor, the ones that touch the outside world.
- **reach**: for each part, how many parts it can drive (`out`) and how many can
  drive it (`in`), over calls, sends and conditional flows (never `!>` or `=>`),
  then its unit, the actors it reaches (`→`) and the actors that can drive it
  (`←`). Data glyphs pass a path on but are not counted. It is the blast radius: a
  failed or hostile part reaches what its `out` counts.
- **pass-throughs**: a part (no data, event, store or actor, and no unit's face)
  with exactly one caller and one callee, neither an actor: a layer that may isolate nothing.
- **units over 9 members**: units too big to scan at a glance; each is one SGC177
  `large-unit` finding.
- **a name declared in two units**: a part written in two units neither of which
  encloses the other, so it has no home; `sigil check --export` calls it SGC401
  `no-home`.
- **writers per store**: who writes each store, counted as `sigil check` counts
  writers: a writing flow into it (not a read verb), `@write(…)` on it, `@owns` on
  the writer. It needs no `@read` / `@write` declared.

## The Claude Code viewer

The Claude Code plugin's mod (`plugin/claude`) gives the agent a `view` tool and
gives the person a `/sigil-pane` command. Both show a document in a live viewer,
redrawn on every save.

The tool's input:

- `file` — the `.sigil` file.
- `view` — `flow` (the default), `graph`, `tree` or `run` (one run as a
  timeline: the scenario's, else the happy one).
- `depth` — a number, or `"all"`.
- `scenario` — a scenario to simulate, as `--sim` names it: a listed name, or
  `Entry@t` to start that entry at tick t while earlier episodes still run, or
  `Owner=State` to begin a state machine in State, combined with `+`
  (`Api.charge:fails+Author@40`). `""` ends the run.
- `frame` — the frame of the run to show: a 0-based number, as the viewer's
  `--frame` counts them, or `"last"`. A new run starts on its last frame. The
  pane and widget play every frame of a run, however long, drawing it a window
  of frames at a time.
- `play` — `true` plays the run, `false` pauses it.
- `payloads` — show flow payloads.

A field you leave out keeps its last value. The reply says where the document is
shown, then gives the summary line, lint, the run's step at that frame, its
narration line (`now: …`, in the viewer's words) and path (`path: …`, the hop now
marked `▸`), the run's
outcome, and the scenario names. It never returns the drawing:
`sigil view --once` prints that.

`/sigil-pane` takes the same fields as words, in any order: `FILE`, a view name,
`depth N|all`, `sim SCENARIO`, `frame N|last`, `play` and `payloads`. With no
words it reopens the pane. `/sigil-pane display [mod|multiplex|auto]` says or sets
where it draws, `/sigil-pane layout [auto|wrap|pan]` how a drawing wider than
the pane fits, and `/sigil-pane placement [split|tab]` whether a multiplexer opens
it in a split or a tab (see [the viewer plugin contract](#the-viewer-plugin-contract)).
`layout` is the plugin option of that name, a `/config` row as `display` is; in a
split it is `sigil view`'s `--layout`. Panned, a drawing wider than the pane shows its
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
  one in brackets), `t` cycles them, `d` the depth; with a run, `p` plays or pauses it,
  `b` and `n` step it, and `s` and `f` play it slower and faster: the viewer's speeds,
  ¼ to 32 frames a second from 2, shown in the status line (a pane's hotkey is a
  letter or a digit, so not the viewer's `-` and `+`). Under the drawing the pane shows the run's path
  (in the viewer's styles) and, after `›`, its narration line, as the live view's rows under its footer.
  Docked, the drawing fills the pane and the legend,
  summary and keys sit at its bottom. The flow and run views draw with their own
  legends. The pane draws the cells that `sigil frames
  draw` packs (with hex colours), not ANSI. A pane opened
  without being asked needs 144 columns. Below that, the reply says it's waiting
  and names `/sigil-pane`, which opens it at any width.
- `multiplex` opens a split to the right in herdr, tmux or zellij, running
  `sigil frames follow CONTROL`. That loop runs `sigil view` live with the flags in the
  control file and restarts it each time the agent's next call rewrites the file.
  Pressing `q` in the split closes it. With the plugin option `placement` set to
  `tab` (`/sigil-pane placement tab`, or `/config sigil.placement=tab`) it opens in
  a tab of its own instead, labelled `sigil view`, without taking the focus where the
  multiplexer allows: a herdr tab in this session's workspace (`herdr tab create
  --no-focus`, then the follow line run in its pane), a tmux window (`new-window
  -d`) or a zellij tab (`action new-tab` with a layout of one pane running the follow
  line, closed when it exits). `split`, the default, is the split to the right. An
  open view is reused only while the multiplexer and the placement are the same, so
  after switching, the next view opens the new way. A run starts where the agent asked: the
  file's flags carry `frame` and `play` as `sigil view`'s `--frame` and `--play` (a run
  with neither starts on its last frame, as in the pane), and the reply reads the
  run at that frame. From there the split's own keys drive it.
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
  `play`, `payloads`) plus `pause`, `back`, `next`, `-` and `+` (the run's speed,
  as the viewer's keys, shown in the status line), `left` and `right`, which pan a
  panned drawing half a widget across, and `close`. With no words it
  reopens the widget.
- `multiplex` opens the same split (or, with `placement` `tab`, the same tab),
  running `sigil frames follow`.
- pi has no plugin settings, so `/sigil-pane display VALUE`, `/sigil-pane layout
  VALUE` and `/sigil-pane placement VALUE` save to the shared settings file
  (`~/.config/sigil/viewer.json`). For one session, `pi --sigil-display
  auto|mod|multiplex` or the `SIGIL_DISPLAY` environment variable wins over the file
  (`--sigil-layout`, `SIGIL_LAYOUT` for the layout; `--sigil-placement split|tab`,
  `SIGIL_PLACEMENT` for the placement); with none of them set it's `auto` (`split`
  for the placement).
- In print and json modes (`-p`, `--mode json`) there's no UI. The `mod` reply
  says so and points to `sigil view --once`. In RPC mode (stdout is pi's JSON
  channel, not a terminal) pi sends clients only plain-text widgets, so the widget
  goes as text lines: the whole drawing at 100 columns, no colours, sent again
  whenever its lines change (a run's frame, a save, the speed).

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
  or words), `auto` picks whichever overflows less (the viewer's `pick_layout`, given
  the viewer's columns and rows). The reply says what the drawing shown was laid
  out as under `auto`. `layout` is never read as a file name either. A split
  passes it to `sigil view` as `--layout`.
- **`/sigil-pane placement`** and **`/sigil-pane placement VALUE`** do the same for
  where `multiplex` opens the view: `split` (the default) a split to the right of
  the session, `tab` a tab of its own labelled `sigil view` (a herdr tab, a tmux
  window, a zellij tab). It changes nothing for `mod`.
- **The values**: `mod` draws inside the agent's own UI (a pane, a widget),
  `multiplex` opens a split to the right running `sigil view` live (through
  `sigil frames follow`), and `auto` picks `multiplex` when `HERDR_ENV`, `TMUX` or
  `ZELLIJ` is set, and `mod` otherwise. `resolveDisplay` in
  `plugin/claude/hooks/logic.ts` is the rule; a plugin in TypeScript imports it.
- **The split's control file** is private. It names the `sigil view` command line
  the split runs, and a `--dialect` there is Python code, so a host writes it as
  `control.json`, mode 0600, in a directory of its own that only this user can
  enter (0700, named `sigil-view-…`; `privateDirArgv` and `privateWriteArgv` in
  `logic.ts`, or `mkdtemp`), and replaces it whole (written beside it, then renamed
  over it). `sigil frames follow` checks it at the start and before each request it
  runs: a file, or a directory, that is not this user's or that another user could
  write is refused on screen and nothing it asks is run. Once the split closes,
  follow removes the file and, in a `sigil-view-…` directory, the directory too.
- **Where it's kept**: in the host's own settings when it has them (Claude
  Code: the plugin's `userConfig` fields `display`, `layout` and `placement`,
  `/config` rows). A host without them uses the shared file
  `$XDG_CONFIG_HOME/sigil/viewer.json` (`~/.config/sigil/viewer.json` when that's
  unset), holding `{"display": "mod", "layout": "wrap", "placement": "tab"}`. It's
  read on each use, and writing it keeps any other keys. A flag or environment
  variable the host offers for one session (`--sigil-display`, `SIGIL_DISPLAY`;
  `--sigil-layout`, `SIGIL_LAYOUT`; `--sigil-placement`, `SIGIL_PLACEMENT`) wins
  over the file, in that order.
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

  So is the placement reply (`placementReport`); after a change its second line
  says how the next view in a multiplexer opens:

  ```
  placement: tab · from /config sigil.placement
  The next view in a multiplexer opens in a tab of its own.
  ```

  A multiplex reply names the placement: `Opened a herdr tab running sigil view
  live …`, `Shown in the tmux split …`.

## OpenCode

OpenCode gets the skill and commands but no viewer plugin. To show a design live
there, run `sigil view FILE` in a herdr, tmux or zellij split; the agent reads
`sigil view FILE --once`. Checked on 2026-10-07:

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

## `sigil export FILE|- --mermaid`

Emits a Mermaid `flowchart TD` for docs or review (GitHub, Obsidian,
mermaid.live, …). It has no gate: any mode exports, a sketch as well as a spec, and
it writes nothing but the chart on stdout.

- `--depth N|all` opens expansions.
- `--composition subgraphs|edges|none` draws composition trees as nested subgraphs
  (the default), as labelled dotted edges, or not at all.
- `--spine` groups the chart by the systems an export would make (see
  [`sigil export`](#sigil-export-spec---out-dir)): the top system is the chart, and
  every other system is a subgraph inside the one it is nested in, holding the
  components homed there; flows are drawn as `--mermaid` draws them. Every system is
  drawn (`--depth` does not apply). It is the shape to review before a spec is
  exported.
- `--dialect NAME` draws with a dialect.

## `sigil frames`

What the Claude Code pane and the pi widget run; not meant to be typed.

- `sigil frames draw FILE [--view graph|tree|flow|run] [--depth N|all] [--width N]
  [--height N] [--layout auto|wrap|pan] [--scenario NAME [--from N|last] [--count N]]
  [--payloads] [--theme NAME] [--dialect D] [--limit NAME=N]` prints the drawing as one JSON
  object of packed rows (text and a style id per run, a style table with hex
  colours), with the legend, summary, lint and scenarios, and for a run its frames
  a window at a time. `--limit` raises one simulator limit (repeatable), as `sigil
  view` and `sigil check` take it, for the run and the scenarios listed. The
  shape is in the docstring of `sigil/present/frames.py`; the page's `frames.json`
  and the playground use the same packing.
- `sigil frames follow CONTROL` runs `sigil view` live with the flags in the
  control file, restarting it each time the file is rewritten (the `multiplex`
  split). The control file names a `sigil view` command line, which can load a
  dialect's code (`--dialect`), so follow refuses one, or one in a directory, that
  another user could write or that is not yours (it says why on screen, runs
  nothing and exits 2 when the split closes); see [the viewer plugin
  contract](#the-viewer-plugin-contract).

## `sigil highlight FILE|-`

Prints a document's source in its theme's colours: the text unchanged, each piece
wrapped in a truecolour escape (plain text when `NO_COLOR` is set). It reads each
line as every other command reads it (the same tokens, a dialect's syntax too), so a
glyph, arrow, modifier, payload, comment, section header, mode line, `#%` kind line
or `#&` declaration gets the colour its role has in the theme, and the colours are
the ones the drawings use. Any text highlights, half-typed or not linting; nothing is
checked and nothing else is read but the theme and the dialect.

- `--theme NAME|PATH` picks the theme (see [Themes](#themes) for the default order).
- `--dialect NAME` reads with a dialect (its glyphs, keywords, declaration blocks,
  comment markers, and its `THEME` as the default theme).
- `--json` prints one object for a host to paint:

  ```
  {"sigil_highlight": 1, "theme": "sigil",
   "lines": [[["[", "syntax.keyword", "#c850e0"], ["Shop", "kinds.service", "#8aa0ff"],
              ["]", "syntax.keyword", "#c850e0"], [" ", null, null],
              ["->", "syntax.operator", "#e85d9e"], …], …],
   "carry": [[0, 0, 1, 0], …]}
  ```

  one list of runs per line, each `[text, role, colour]` (a line's texts joined give
  the line back; `role` is a theme path such as `syntax.operator`, `kinds.service`,
  `ui.mode`, and `role` and `colour` are `null` for plain text), and per line the
  carry it ends in.
- `--stream` (no FILE) answers JSON-lines requests on stdin, one JSON line on stdout
  each (flushed), until stdin ends (exit 0). A request is `{"id", "lines", "start",
  "carry"}` (highlight these lines, the first starting in `carry`), `{"id", "theme"}`
  (switch the theme) or `{"id", "dialect"}` (switch the dialect; `null` for core
  Sigil), or any of them together; the answer echoes `id` and holds the runs and end
  carries in `--json`'s shape, the theme or dialect now in use, or only `error` for a
  request that fails (which changes nothing; the loop goes on). The full protocol is
  in `sigil highlight --help`.

**The carry.** Three things in Sigil span lines: a `"""…"""` block string, a `#&`
declaration's `{ … }` body, and a `state` block. A line's carry, `[quote, decl,
decl_raw, state]`, says which of them the next line starts inside (a text starts
in `[0, 0, 1, 0]`). A line's runs depend only on the line and the carry it starts
in, so an editor highlights incrementally: after an edit it sends the changed lines
with the end carry of the line before them and keeps sending the following lines
until a returned end carry equals the one it held; from there nothing changed.

The grammars in `highlight/` (TextMate, Sublime, vim, Pygments) are checked
against this highlighter over one corpus; see
[`highlight/README.md`](../highlight/README.md).

Exit codes: 0 printed (or the stream ended), 2 bad usage, a theme or dialect that
cannot be loaded, or a file that cannot be read (or is not UTF-8).

## Themes

The viewer loads a colour theme from `themes/<name>.yaml`: `sigil view --theme NAME`
or `SIGIL_THEME=NAME` picks one, and the web page reads the same files. A dialect
may name its own theme (its `THEME` hook: a theme name, or a YAML path beside the
dialect module, read as any theme file is). Every command that colours (`view`,
`frames draw`, `highlight`) takes an explicit `--theme` first, then `SIGIL_THEME`
(a person's choice beats a dialect's default), then the loaded dialect's `THEME`,
else `sigil`, so a dialect's drawings and its source agree. A theme the dialect's
`THEME` names that cannot be loaded is an error, as a bad `--theme` is.
`sigil themes [NAME|PATH]` prints a theme resolved (its `extends` and `$name`
references filled in) as JSON, and `sigil themes --list` lists the themes found. The format is in the README under [Themes](../README.md#themes).

## Dialects

`sigil lint`, `check`, `view`, `export`, `frames draw` and `highlight` load a dialect (`--dialect NAME` or
`SIGIL_DIALECT`) that extends the linter, Mermaid and the checker. A dialect module imports the core's vocabulary
from `sigil.core.vocab`, the dialect API, and a dialect's own command calls
`sigil.cli.main(argv, dialect=NAME)`. See "Dialects" in
[`language.md`](../language.md).

**One hook set.** A document is read once, and a dialect hooks that one reading:
the statement walk, its tokenizer, the parser and lint all go through the same
hooks (documented in `sigil/core/dialects.py`):

| Hook | Shape | Does |
| --- | --- | --- |
| `prepasses()` | `[fn(lines, result) -> lines]` | line rewrites that keep the line count, run once after the block-string fold and before the walk; the place for a blank that depends on context (whether a line is a composition branch, what the line above says). `result` is the lint result a pass may report on (the parser hands a scratch one). |
| `strips()` | `[fn(line) -> line]` | blanks of a flow statement's text that keep its length (spaces, never deletion), applied after its branch marker is read; never to block headers, definition heads, transitions or section headers. A strip sees text only, not its context. |
| `tokenizers()` | `[fn(s, i, prev_was_glyph, layer, Node) -> None \| (tokens, end, prev_was_glyph)]` | extra glyph or arrow syntax, tried at each column before the core rules. A glyph one reads is a glyph everywhere: a node in the model, an endpoint for lint, a definition head, and (by name) a principal an access list may name. |
| `COMMENT_MARKERS` | regex sources | extra comment markers; one ends a statement's code as `#` does, never inside a `"…"` string. |
| `DECLARATIONS` | `set[str]` | the `#&` names the dialect declares (`#& header …` declares `header`). Core reads every line-leading `#& name …` (or `#&name`) as a declaration that draws nothing, its `{ … }` block a body no rule reads; lint warns (SGL189) on a name no loaded dialect declares. A dialect without this hook hears nothing: it checks its own `#&` lines. `sigil.core.vocab.declaration_name(line)` reads the name. |

The other hooks keep their names: `lint_passes()`, `lint_payload_checks()` (its
`site` also says `branch`, true on a composition-branch statement), the data hooks
(`KNOWN_MODIFIERS`, `DECLARATION_BLOCKS`, `BLOCK_KEYWORDS`, `COMPOSITION_RELATIONS`,
…) and the check hooks; a `#&` declaration needs no `DECLARATION_BLOCKS` entry.
`KNOWN_MODIFIERS` and `DEFERRED_MODIFIERS` entries are written with their `@`
(`{"@at"}` for `@at(…)`); a bare `"at"` matches nothing, and `@at` still draws
SGL040. `THEME` names the dialect's colour theme (see [Themes](#themes)).
Two more attributes reach `sigil export`: an optional `VERSION`, recorded
as the manifest's `dialect.version` (as text), and the `Node.attrs` a tokenizer puts
on a glyph, written as its component's `attrs` (so keep them JSON-like; anything
else is written as its text).
The 0.5 hooks are refused by name: a dialect that still defines `lint_prepasses` or `render_prepasses` (now `prepasses`),
`render_line_strips` (now `strips`), `render_tokenizers`, `lint_glyph_masks` or
`lint_principal_scanners` (now `tokenizers`) fails to load with an error naming the
hook that replaces it. `strip_comment` from `sigil.core.vocab` is string-aware: a `#`
inside a `"…"` string starts no comment.

## `highlight/`

Syntax highlighting for bat, nvim, VS Code and Sublime / TextMate, checked against
[`sigil highlight`](#sigil-highlight-file-). See
[`highlight/README.md`](../highlight/README.md).
