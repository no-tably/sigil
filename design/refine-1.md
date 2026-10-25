# sigil.sigil — refinement round 1 (patch-0.6.2, Q1)

Date: 2026-10-20. Method: the skill's **refine** loop (`skills/sigil/SKILL.md`, the
eight passes, re-measured after each change), plus a defender's reading of the
trust boundaries. No user was asked in this round. I applied only changes that make
the model match the code (read from `git log main..HEAD` and the `sigil/` package's
imports) or that the plan asks for. Real design choices are listed under
**Proposals**, each with its cost, measured on a scratch copy where I could.

Tool: the worktree's `bin/sigil` (branch patch-0.6.2: S1 1baac99, M1 bb0687f, L1
9926e10, L2 5d82c66, C1 2b62027, and R1's uncommitted `sigil/model/structure.py`,
which works and is used here as `view --structure`). "Raised" means
`--limit frames=14000`, the least that leaves no run cut. `activations` needs no raise.

## Measures

| | before (main's model, `#!craft`) | after (`#!sketch`) |
|---|---|---|
| `sigil lint` | OK, 0.07 s | OK, 0.07 s |
| `check --mode sketch` | OK, 0.20 s | OK, 0 shown / 2 hidden, 0.55 s |
| `check --mode sketch --all` | 0 findings | 2 info: SGC101 `[Dialects]`→`(Dialect)`, SGC204 `|ThemeFiles|` |
| `check --mode spec` (default limits) | 0 err, 0 warn, 3 info, 1.25 s | 0 err, **3 warn**, 8 info, 1.70 s. Warns: SGC090 *happy cut at frames=9216* (L1's new warn), SGC101, SGC204 |
| `check --mode spec`, raised | same as default | 0 err, 2 warn (SGC101, SGC204), 8 info, 1.85 s |
| `--sim all` (default) | 13 rows, 13 ok, happy 2849 frames, 0.35 s | 4 rows, **4 cut** (happy cut at 11382), 0.49 s |
| `--sim all`, raised | same | 4 rows, 4 ok, happy **13602** frames, 0.52 s |
| `view --structure` | 10 units: 1 cycle, 2 up, 0 edge parts, 5 pass-throughs, 1 over 9, 0 in two units, 0 multi-writer stores, 0.12 s | 10 units: 2 cycles, 2 up, 1 edge part, 4 pass-throughs, 2 over 9, 0 in two units, 1 multi-writer store, 0.13 s |
| `export --mermaid --spine` | 9 subgraphs | 9 subgraphs |

Per step (structure summary; happy run frames when raised; `--sim all` rows):

| step | structure | happy (raised) | rows |
|---|---|---|---|
| 0 before | 1 cycle (Present·Views), 2 up, 0 edge | 2849 | 13 ok |
| 1 truth pass: layers, export, trust boundaries, actors at the top | 1 cycle (sigil·Publish·Present·Views), 5 up | — | — |
| 1a boundary writers moved into their layers, Cli an expansion with each command's flow | 2 cycles (Model·Sim, Present·Views), 2 up | 39610 | 13 ok, happy cut at default |
| 1b Sim nested inside Model (so the simulator enters it, see D1) | same | 39610 | 13 ok |
| 2 each actor drawn at the command it runs (inside Cli) | 2 cycles, 2 up, 1 edge | 13682 | 4 ok |
| 3 the dialect's lint rules and rule pack read through Core, not drawn to `[Dialects]` | same, SGC401 0 (was 1 with `--export`) | 13602 | 4 ok |

No outcome, end state, failure or route changed at any step. Every row is `ok` and
there are no failure rows, because the model has no `!>` route, retry or fallback.
Frame counts moving is not a regression. The 13 → 4 rows in step 2 is a cost, though:
see Proposal 9.

## What each pass found

**purpose** (`--depth 0`, unreached, run view). Before, `[Systems]` sat in Publish.
The code has it in Model (`sigil/model/systems.py`, read by the export rules,
Publish and Structure). The structure reading (`model/structure.py`) and the
structure checks (K1) were missing. Once `[Sim]` was written as a top-level
expansion, its expansion's parts were unreached (SGC175 `[Scenarios]`, `[Engine]`).
That came from a simulator gap, not from the design (D1). Nesting Sim inside Model's
body cleared it.

**names** (`--tree`). Two modules are named `systems`: `model/systems.py` (the export
model) and `publish/systems.py` (hashes, normalised JSON, slugs). The model calls
the second `[Hashes]` (Proposal 3). A dialect's lint rules and rule pack drawn as
`[Lint] -> [Dialects]` / `[Check] -> [Dialects]` wrote `[Dialects]` in two units.
`check --export` called that SGC401, but the structure reading listed no name in two
units (D2). Applied: those reads now go through Core (step 3). The payload verb
`calls(...)` tripped lint SGL030 (D8), so it was renamed `edges(...)`.

**dependencies** (`export --mermaid --spine`, structure cycles and up). The spine is a
DAG at the layer level: Cli → {Analyse, Present, Publish, Core}; Publish → {Analyse,
Model, Core}; Present → {Analyse, Model, Core}; Analyse → {Model, Core}; Model →
Core. Two cycles remain, and both are *up* readings: a nested unit's face calls a part
of its parent. `[Sim] -> [Scene]` is in Model, and `[Views] -> [Kit]` is in Present.
They match the code: `model/sim/*` imports `model/scene.py`, and `present/views/*`
imports `present/kit.py` (Proposals 1, 2; D5). Hidden edges the old model left out
and that are now drawn: `[Kit] -> [Analyse]` (kit.run_lint: the drawing kit runs the
linter), `[Hashes] -> [Analyse]` (publish/systems imports `check.CORE_NAMES` to read
acks), `[Frames] -> [App]`, `[Structure] -> [Sim]` (`sim.canonical`). Edges in the old
model that the code doesn't have, now removed: `[Check] -> [Lint]` (check never calls
lint; `cli --deep` and `exporter.ready` join the two) and `[Parse] -> [Comments]`
(parse never imports comments; scene, check, kit and the export do).

**blast radius** (reach, writers per store, actors). The one part that calls an actor
is `[Dialects] -> (Dialect)`. Almost every part reaches `(Dialect)` (in-reach 24 of
40): a dialect's code runs in every command except `sigil themes`, and in the split's
child `sigil view` too. The stores each have one writer except `|ExportDir|`
(Exporter, Builder), and that's correct: the manifest rule separates the files
(Proposal 5). The old model claimed `@inv serialised(|ExportDir|)`. The exporter has no
lock, so that line is gone, and a comment says two exports into one folder at once are
not ordered (Proposal 6). Untrusted input is decoded before use: the old manifest is
checked by `delta.manifest_problem` (slug folders) before anything is deleted, and a
theme is a YAML subset whose values are strings only.

**complexity** (members per unit, pass-throughs). Cli and the top system come out at 10
members, "over 9". Both counts include actors and a store: Cli has 7 commands plus
`(Agent)`, `(Host)` and `|Control|`, and the top has 6 layers plus the playground and 3
actors. Counted as built parts, neither unit is large (D4). The pass-throughs are
`[Systems]` and `[Mermaid]` (reading artefacts: their other callers reach them through
the `[Model]` / `[Publish]` face), `[Themes]` (the YAML loader that isolates the file
format: keep) and `[Engine]` (the run, between scenarios and the program: keep).

**composability** (what each unit calls). Model, Core and the Sim are pure but for the
dialect load. Present isn't composable below App: the cell kit (`[Kit]`) calls
Analyse to draw the lint summary, so cure (Present's planned base) couldn't replace
Kit + Themes without also taking a linter call (Proposal 1). `publish/systems.py`
imports the whole of `analyse/check.py` for one table of rule names (Proposal 4).

**efficiency** (happy frames, waits). Every cross-layer call targets a layer's face
(`[Present]`, `[Analyse]`), so the simulator runs the whole layer behind it. For
example, `sigil themes` "reaches" 27 parts in the model, but in the code it imports
one module. Drawing each actor at the command it runs cut the happy run from 39610 to
13682 frames. Even so, it doesn't finish under the S1 default (frames=9216 at this
size; D6).

**behaviour** (`--sim all`, `check --mode spec`). There's no failure path, so the only
rows are the happy run and overlaps. The model leaves out the failures the code
handles: a dialect that fails to load (ValueError, exit 2), a gate that blocks
(exit 2, nothing written), an unreadable file. Spec check: L1's SGC090 warn fires on
the cut happy run, which is what it is meant to do. SGC101 (no time bound on the
dialect import) and SGC204 (a theme edited while a view reads it) are real but small
(Proposal 5). SGC163 capacity on each actor → command is library-shaped noise.

**defender's view** (trust boundaries, each with what crosses it, drawn in the model):

| boundary | what crosses | where in the model | note |
|---|---|---|---|
| dialect | Python code (a path, `$SIGIL_DIALECT_PATH`, `../sigil-NAME`, or `$SIGIL_DIALECT` by default) | `[Dialects] -> (Dialect) : load`, `(Dialect) -> [LintCmd]` | runs inside lint, check, view, export and frames. A NAME resolves first to `sigil-NAME/` beside the repository (or the installed skill folder), so a folder planted there is loaded |
| themes | YAML text | `(Author) -> |ThemeFiles|`, `[Themes] -> |ThemeFiles|` | strings only, own parser, no code |
| export folder | the old `manifest.json` (read), the files (written and deleted) | `[Exporter] -> |ExportDir|` read/write, `(Builder) -> |ExportDir|` | deletes only the files the old manifest names, after a slug check. No lock. A system folder that is a symlink would be followed (not checked) |
| plugin hosts | argv of a spawned `sigil`; the split's control file | `(Host) -> [FramesCmd]`, `(Host) -> |Control|`, `[Follow] -> |Control|`, `[Follow] ~> [ViewCmd]` | the control file is in `$TMPDIR` under a random UUID name, and its argv may carry `--dialect PATH` (code), so whoever can write it runs code as the user (Proposal 10) |
| Pyodide | the visitor's text; drawings and findings out | `(Visitor) -> [Playground]` | no files, no dialect, no export; the check budget is `CHECK_RUNS` |

## Changes applied

1. Header: dropped "behaviour stays as 0.5.0's" and every "target: … PLAN.md L2"
   note. The mode is `#!sketch` (was `#!craft`). Added the rule that structural changes
   are modelled here first.
2. The agent that follows the skill is the main user. `(Agent)` calls the commands of
   its loop (lint --deep; --sim all, --structure; check --mode spec --export; export),
   next to `(Author)`, `(Host)`, `(Dialect)` and `(Visitor)`.
3. `[Cli]` is an expansion with one flow per command into its layer, plus `[ThemesCmd]`
   and `[Follow]` (`sigil frames follow`), with summary flows at the top (SGC172 asked
   for them).
4. Core is drawn as the code is: `[Parse] -> [Read]` (statements.read_document, the one
   walk) `-> [Lex]` / `-> [Dialects]`, `[Parse] -> [Graph]`, `[Comments] -> [Graph]`, and
   a note on C1's continued comments.
5. Model: `[Systems]` (moved from Publish) with M1's nesting, home and actor rules,
   `[Structure]` (R1), and `[Sim]` as an expansion inside Model (scenarios → engine →
   program, narration), with S1's sized limits.
6. Analyse: L1 / L2 notes (SGC090's spec warn, the work cap), `[StructureRules]` (K1,
   not built), `header_only` shared with Systems. `[Check] -> [Lint]` removed.
7. Publish: `[Exporter]`, `[Hashes]` (0.6.1: per-component hashes, `#&` declarations,
   lines, attrs, `--name`, delta every time, the dialect in the manifest), `[Delta]`
   (renamed top), `[Mermaid]` (an unlisted dialect kind falls back to the core shape),
   `[Spine]`, export `--limit`. The false `@inv serialised(|ExportDir|)` replaced by a
   comment.
8. Present: the cure note, `[Frames] -> [App]`, `[Kit] -> [Analyse]`.
9. Trust boundaries drawn: `(Dialect)`, `|ThemeFiles|` with its writer, `|Control|`,
   `|ExportDir|` with `(Builder)`, Pyodide.

Writers of a store are drawn inside the layer that owns it. Written at the top, the
store is homed at the top, and every layer that touches it then cycles with the top
(step 1: sigil·Publish·Present·Views).

## Proposals not applied (for the user)

1. **A cells layer under Present** (dependencies, composability). Move `[Kit]` + `[Themes]`
   + `|ThemeFiles|` into their own unit (code: a `sigil/present/kit/`-like package, or a
   `cells` layer), and have App compose the lint summary instead of the kit. This removes
   the Present·Views cycle, makes Kit + Themes exactly what cure would replace, and
   makes `sigil themes` depend on one unit. Measured: 11 units, 1 cycle, 1 up, happy
   12082 frames (from 13682). *Cost:* a module move in `sigil/present`, `kit.run_lint`
   moving to app, and import churn in four views.
2. **The simulator as its own layer** (dependencies). Move `sim.canonical` (a one-line
   `scene.build_scene(…)` call) into `model/scene.py`, so Structure needs only Scene. Then
   Sim can be a sibling layer that Analyse and Present call, removing the Model·Sim cycle.
   Measured: 10 units, 1 cycle, happy 14002. *Cost:* `sigil/model/sim/` → `sigil/sim/`
   (imports in check, app, frames, playground, tests). Moving `canonical` alone is cheap,
   and on its own it removes the `[Structure] -> [Sim]` edge.
3. **Rename `publish/systems.py`** for what it does (hashes / form), so that `systems`
   names one thing.
4. **Rule names as data** (composability): put the `CORE_NAMES` / `EXPORT_NAMES` table
   beside the ack reader in core (or pass it in), so Publish doesn't import `analyse.check`
   to read acks.
5. **Settle the findings** the spec check raises (none were acknowledged here; each is
   the user's answer). SGC101: a dialect import is in-process, trusted code, and can't
   be time-bounded. SGC131 `|ExportDir|`: the manifest rule separates the exporter's
   files from a builder's. SGC204 `|ThemeFiles|`: a theme is read once per view start.
   SGC163 ×6: library-shaped, one document-wide ack.
6. **An export lock**: `O_EXCL` lock file in DIR, or a documented "one export per folder
   at a time". The old model claimed the lock but the code doesn't have one.
7. **Draw the failures the code handles** (behaviour): `[Dialects] -> (Dialect)` `!>` a
   named error that Cli turns into exit 2; the gate's `{Gate}` blocking. That gives
   `--sim all` failure rows to judge.
8. **Expected outcomes as comments** (behaviour), e.g. `# expected: a spec with a cut
   run does not export (SGC090 warn)`, so each refine round re-checks them.
9. **Where the actors sit.** Drawing each actor at its command (applied) gives honest
   reach and a 3× shorter happy run. But the simulator then treats every actor inside
   `[Cli]` as one entry, `[Cli]`, so the overlap rows are `Cli@t` (4 rows, was 13 with
   per-actor entries) and Agent ‖ Host overlaps are never tried. The alternative is
   actors at the top calling `[Cli]`: 13 rows, happy 39610.
10. **The split's control file** carries any `sigil view` argv, `--dialect` included.
    Either `follow` refuses `--dialect` / dialect paths from CONTROL (the host passes the
    name in its own argv), or the docs say the control file is code-equivalent.

## Where the code and the model disagree

Flagged for the main session (**fix in 0.6.2** where marked):

- **D1 (fix in 0.6.2, M1 follow-up; sim/scene).** M1 nests an expansion written at the
  top for another unit's member, in `systems.py` and SGC172. The simulator still doesn't
  enter that expansion when the member's face has flows of its own at its level, so the
  body never runs and `check --mode spec` reports SGC175 *unreached* for it. Repro:
  ```
  #!sketch
  (U) -> [Core] : use({X}) => {Y}

  [Core] := {
    [B] -> [A] : get({X}) => {Y}
    [A] -> [C] : put({X}) => {Y}
  }

  [A] := {
    [P] -> [Q] : go({X}) => {Y}
  }
  ```
  happy: `[B] calls [A]`, `[A] calls [C]`, and `[P]`/`[Q]` never run. Spec: `info:10:SGC175
  … [P]`. Written inside Core's body (`  [A] := { … }`), `[P] calls [Q]` runs. Structure
  says `A expansion in Core` in both forms.
- **D2 (R1/K1).** The structure reading's "a name declared in two units" misses a
  component that a second unit only *references* in a flow. `check --export` calls the
  same thing SGC401 no-home, and the structure reading counts it as an ordinary call
  (`B calls A`). Repro: `[A] := { [P] -> [Q] … }`, `[B] := { [R] -> [P] … }`: structure 0
  names in two units, SGC401 error on `[P]`. K1 should follow one rule.
- **D3 (fix in 0.6.2; R1, site/build_site.py).** `sigil/model/structure.py` is shipped to
  the playground (it is not in `NOT_IN_PLAYGROUND`), but it imports `sigil.model.systems`,
  which isn't shipped. App imports it lazily, so nothing breaks today, but it's dead
  weight that can't import. K1's `rules/structure.py` must load on demand like
  `EXPORT_MODULES`, or the playground must ship `systems.py` + `structure.py`.
  Otherwise the playground's check breaks.
- **D4 (R1/K1).** LARGE ("units over 9 members") counts actors and stores. M1 says actors
  aren't built. Here Cli (7 commands) and the top (6 layers + playground) are "over 9" only
  because of actors. Proposal: count built components, and list actors apart.
- **D5 (R1/K1, a decision).** By the export model, a nested unit's face flow at the
  enclosing level (`[Sim] -> [Scene]` inside Model) is the nested system's flow, and the
  parent depends on everything nested in it. So any nested unit that uses a sibling part
  is a cycle (*up*). That's consistent with `depends_on`, but a K1 "cycle" rule would then
  fire on most layered designs, this one included. Decide before K1: are face flows the
  enclosing unit's?
- **D6 (S1; fixed in M2: factor 128, the cut reports its episode).** The sized default (`frames` = 64 × size = 9216 here) didn't finish this
  model's happy run (13602 frames). The frames limit also counts from the latest episode's
  start, so SGC090 says `frames=9216` while `view --sim all` shows the happy run `cut 11382
  frames` (the earlier Visitor episode added). "Raise --limit frames=N" starts from a number
  that doesn't match what the view shows. (The episode counting is an open sim-overlap leftover.)
- **D7 (sim narration).** Overlap label `[Cli] starts at t240, reaching |ThemeFiles| as
  (Visitor) writes it`: the write is `(Author) -> |ThemeFiles|` (an actor written inside
  Present, which runs whenever Present is entered), not the Visitor. The label names the
  episode's entry, not the writer.
- **D8 (lint; pre-existing on main).** SGL030 flags a payload op verb that is also a prose
  verb: `[A] -> [B] : calls({Doc}) => {Spine}` (also `sends`, `reads`). `lint/lines.py`
  rescans the line text instead of reading the walk's payload tokens. That contradicts the
  model's own rule ("lint reads its tokens and statements, it does not scan text again").
- **Fixed in the model** (it was wrong, the code was right): `[Check] -> [Lint]`, `[Parse]
  -> [Comments]`, `[Systems]` in Publish, `@inv serialised(|ExportDir|)`, no Follow / themes
  command, no structure reading.

## Round 2: system kinds (2026-10-22, patch-0.6.3)

The change, modelled before it was built: Core gains `[Kinds]` (a table read from
the `#%` line after the mode line: shape, reach, concurrency, and the rule groups
each word turns off); Lint judges the line (SGL093–095); Check drops the groups the
Doc's kind turns off, names them in its summary, and makes no overlap runs for a
`deterministic` kind; `--all-rules` runs everything; the skill asks the kind once.
No new dependency or trust boundary: the line is text, and `[Kinds]` calls nothing.

| reading | before | after |
|---|---|---|
| Core members / internal flows | 6 / 5 | 7 / 6 |
| units, cycles, up links | 10, 0, 2 | 10, 0, 2 |
| `[Kinds]` reach | — | out 0, in 31 (a leaf, like Lex) |
| spec check (no `#%` line) | 0 error, 2 warn, 8 info | the same |
| happy run | 13602 frames | 14912 (one more call per parse) |

Then the model itself took `#% job in-process deterministic`: 21 rules off, and its
two warnings go with them — SGC101 on loading a dialect (an import: in-process) and
SGC204 on `|ThemeFiles|` (the author's edit and the viewer's reload, one at a time).
The second is a judgement the user may revisit: `frames follow` spawns a child
`sigil view`, so part of sigil is not one process.

Revisited (2026-10-24, user): `deterministic` comes off — `frames follow` spawns a child
`sigil view`, and the author saves themes while views start, so the race is real. The model
takes `#% job in-process` (13 rules off) and says what the code does:
`|ThemeFiles| @inv atomic(theme)` — each run reads its theme once, and applies it only once
it parses and resolves, so a save caught half-written stops the run (exit 2), never draws
half a theme. Concurrency back on also raises SGC131 on `|ExportDir|` (export and builder
both write it), acknowledged: the folder is split by file (an export writes and deletes only
the files its manifest names). Spec check: 0 error, 0 warn, 1 info (SGC090, overlap budget);
1 acknowledged; 4 runs ok.

## Round 3: homes, the root, payload dependencies (2026-10-24, patch-0.6.4)

The change, modelled before it is built: three readings in `[Systems]` (the export model),
no new module, flow, dependency or trust boundary.

1. **Homes.** A level that names a part only in its flows is never its home when another
   level declares it, at any level (today: only when the declaring level is nested under
   it). With no declaration anywhere, the outer level still homes it (never homeless).
2. **The root** (user: a component named as the project root is the root). A tree root or
   expansion owner named as the top is the top: one system, not `NAME (top)` beside it.
3. **Payload dependencies** (user: a real gap). A flow whose payload names a homed data glyph
   makes both ends' systems depend on that glyph's system.

| reading | before | after |
|---|---|---|
| lint / spec check | clean / 0 findings | the same |
| sim | 4 ok | 4 ok |

The model's own readings don't move (sigil.sigil has none of the three shapes). Specs that
do: one with six parts declared once and named in sibling layers' flows (6 SGC401 → 0), one
whose top tree is named as the file (two folders → one), one whose flows carry a data tree's
names (a dependency the manifest lacked).

## Round 4: starts in a state (2026-10-25, 0.6.5)

Asked by construct (its R0: a report against a Built component, `Built -<Reported>->
Stale`, then Rebuilding): every run starts from an empty world, so a way out of a later
state is never walked. The change, modelled before it is built: one reading in `[Sim]`'s
Scenarios, no new module, flow, dependency or trust boundary.

- A scenario part `Owner=State` begins that owner's machine in State (any state its block
  names). Parts combine with `+` like `Entry@t`: `happy+Component=Built`,
  `Component.change=reported+Component=Built`. Everything that takes a scenario name
  (view, frames, the MCP and pi tools, check witnesses) takes it with no new flag.
- Listed: one run per state with a way out other than the initial one, after the
  overlaps, within the scenario limit; so `--sim all` and spec-mode check walk them.
- An unknown owner or state is the usual unknown-scenario error, listing the states.

| reading | before | after |
|---|---|---|
| sigil.sigil lint / check | clean / OK | the same |
| sigil.sigil sim | 4 ok | 4 ok (no machines) |
| construct.sigil listed runs | — | +7 (Planned, Building, Built, Stale, Rebuilding, Pruning, Removed) |
| cure.sigil, 02-shop | — | no change (no machine with a later state) |

## Round 5: a nested system rechecks along its owner's dependencies (2026-10-26, 0.6.5)

Found by cure (its K1: a nested system may import what its enclosing systems depend on
outside themselves). A nested system's members make up its owner, so the owner's
dependencies are used through them; today the delta marks only systems whose own
`depends_on` names the changed system, so a change to Core flags Interact but not the
systems nested in it. The change, modelled before it is built: one reading in `[Publish]`'s
Delta and one manifest field, no new module, flow, dependency or trust boundary.

- **Recheck** also when a system an enclosing system depends on, outside that enclosing
  system, changed its interface. `because` names the changed system; a new `via` names the
  enclosing system it came through. `depends_on` keeps its meaning (own flows only), and no
  hash moves.
- **Manifest** systems gain `parent` (system.json already has it), so a delta reads nesting
  from the manifests alone.

| reading | before | after |
|---|---|---|
| sigil.sigil lint / check | clean / OK | the same |
| cure export | 29 systems | 19 gain inherited rechecks (e.g. Vt ← Core via Interact) |
| construct export | 16 systems | 5 gain inherited rechecks (e.g. Unit ← construct) |
| hashes | — | unchanged; manifests gain `parent` |
