# Changelog

Each release's notes, newest first. The same text is the GitHub release's description.

## 0.6.10 — 2026-10-30

Three gaps construct hit while writing its question gateway: a field the shape never
declared, a set of one, and a comparison the docs promised. Each cost it a workaround
or went unnoticed.

### New

- **SGL194** (warn): a `{X}.f` that names no field of X's shape. Once a data glyph
  declares its fields (`{Brief} := { title, note? }`), a `.f` written after it
  anywhere names one of them: in a flow, a `?>` guard, a `branch on`, a loop's
  condition or an `@inv`. `branch on {Brief}.gateway` with no `gateway` in the shape
  linted clean before. Every expansion of X counts together, `{Doc}.Meta.path` is
  judged by `Meta`, and a glyph that owns a `state` block also reads `.state`. A glyph
  with no shape is not judged.

### Fixes

- **A set of one needs no comma.** Braces right after `∈` or `∉` are a set whatever
  they hold, so `{Question}.state ∈ {Proposed}` is a one-member set, in a guard, a
  `branch on`, a loop's condition and an `@inv`. Before, `{Proposed}` read as a data
  glyph: lint passed, but drawings, `export --mermaid` and the export showed a
  `Proposed` part that is not in the design. The `{Proposed,}` workaround still reads
  the same and can go. `sigil highlight` and the editor grammars (TextMate, Sublime,
  Vim, Pygments) paint it as a set too. Braces anywhere else read as before.
- **A guard can compare a field.** `?> {Fact}.state = live -> [E]` was a lint error
  (SGL131, "`=` is not an arrow") although language.md shows that form. A comparison
  after a `.field` (`=`, `!=`, `==`, `>=`, `<=`, `>`, `<`) now reads as `∈` does and
  draws the same flow. `branch on`, `@while` and `@inv` already read it.

## 0.6.9 — 2026-10-29

Most of this release fixes what cure and construct hit while their specs caught up with
their code: each one cost them a workaround or an acknowledgement. A design can now
keep its simulator limits in the document, and an export says which sigil wrote it.

### New

- **Limits in the document.** A `name=N` word on the `#%` line is a simulator limit:
  `#% daemon frames=300000 activations=80000`, or `#% frames=300000` alone (the names
  are `--limit`'s; N at least 1). `sigil check`, the export gate, `sigil view`
  (`--sim`, `--run`, `--once`, live) and `sigil frames draw` all start from them, so a
  host's pane with no flag runs the design at the limits it needs. The defaults
  (grown to the document's size) come first, then the document's limits as written,
  then `--limit`, which now *sets* a limit over the document's own: a flag wins,
  whether it raises or lowers one. `check --json` gains `limit_sources` after
  `limits` (each limit's source: `default`, `scaled`, `document` or `flag`).
  SGC090's fix names both ways (`#% frames=N` in the document, or `--limit
  frames=N`).
- **`sigil --version`** prints `sigil X.Y.Z`. An export's `manifest.json` names the
  sigil that wrote it (`"sigil": "X.Y.Z"`, after `"sigil_export"`). No hash reads it
  and the delta ignores it, so a new sigil marks nothing to rebuild; a builder that
  wants to re-export on a new sigil compares it itself.

### Fixes

- **A branch in an expansion runs where it is written.** A field branch (`branch on
  {X}.f`) inside an expansion took over the expansion's entry, so flows written
  before it, and a call beside it, never ran; and an arm's call never entered the
  callee's own expansion. Now a branch between two flows of one source decides
  between them (as since 0.6.4); otherwise it decides in the part that has its
  subject, right after the last flow written before it that gives the subject
  (carries or returns `{X}`, or flows into it) and reaches the branch's arms, in that
  flow's episode. An arm's call is a call like any other: the callee runs its
  expansion, body and branches in its own unit, so a failure there is routed as
  anywhere else. The same holds for `->`, `~>` and gates, in a run and in the
  failure routes the checks read. A design whose arms call into an expansion now
  runs more of itself (construct's happy run: 9421 → 23066 frames), so watch its
  limits.
- **An acknowledgement that covered a finding is never stale.** `ack-unused`
  (SGC003) counted only findings with a one-failure witness, so an acknowledgement
  covering a cut or a stalled join that needs two failures was both accepted and
  called stale, a warning that blocked export in spec. Now any finding it covers
  counts. In craft (`--k 1`), an acknowledgement of a behavioural rule (SGC090,
  203–206, or a dialect rule whose findings carry a k) that covers nothing is an
  info hint naming the k instead of a warning, since spec's deeper runs may need it;
  a static rule's is still a warning.
- **An acknowledgement trailing a `#&` line is read.** `#& name {   # accepts: rule
  — reason` covers the declaration (its block, or its line when it opens none),
  exactly as one on the line above it, and is judged by `ack-unknown-rule`,
  `ack-without-reason` and `ack-unused`. The declaration's body stays as written
  (no hash moves); any other comment trailing a `#&` line stays the dialect's text.
- **Export readings.**
  - A branch's or loop's subject (`branch on {X}.f`, `loop @each x of {Xs}`,
    `loop @while |Q|.…`) is a read: a level that names a part only so is none of its
    systems, and a part every level names only so is no component (no page, no home,
    no dependency), so a subject no longer makes false unit cycles or a data page in
    the wrong unit. It stays a node in the drawings and the runs, and `large-unit`
    no longer counts it (a test fixture's top level: 13 → 12 members).
  - A flow on from a `?>` guard's data subject is the guard's caller's:
    `[Orch] ?> {Job}.ready -> [Builders]` exports as `[Orch] -> [Builders]` (the
    `?>` edge is still exported), not as a call from `{Job}`. Such a guarded call
    across a boundary with no payload or return is now `untyped-boundary` (SGC402).
  - A comment on a data shape's field (`note?   # one line`) joins the data's
    description ("`note?`: one line"). It moves the body hash of the data and of
    its home system, never an interface hash.
  - An acknowledgement of a unit's own finding (`unit-cycle`, `large-unit`) on an
    expansion's header (trailing it, on the line above, or on its `}`) is the
    unit's: `system.json` lists it under `accepts`, the system README under
    "Acknowledgements (on its header)", and the face's page carries it, instead of
    every member's requirements. Any other rule acknowledged on a unit's header
    still goes on each covered member. A re-export of a spec that writes one moves
    the members' and the unit's body hashes once.
- **Check uses far less memory.** Explored runs keep only the facts the trace rules
  read, so construct's spec at its limits takes 0.35 GB instead of 3.0 GB, with the
  same findings for the same runs (201 s against 192 s: with the branch fix above its
  runs now do the work they skipped before; the memory change alone made it 154 s).
- **`view --sim all` holds one run at a time.** The table keeps each run's facts, not
  its events, so a large spec's table no longer takes gigabytes (a construct draft:
  5.9 GB, now 0.36 GB), with the same output.

### New lint rule

- **SGL096** (error): a limit on the `#%` line the simulator refuses: an unknown
  name, a value below 1, a word that is not `NAME=N`, or a name written twice. A run
  ignores a bad one (and takes the first of a doubled one); a bad limit blocks
  export.

## 0.6.8 — 2026-10-28

- **A field is never a node.** In a data shape, `{Meta}`, `{Meta}?` and `rows: {Row}` all name a
  nested shape and draw nothing, whether the shape is written on one line or several. To make a
  glyph a part, write it in a flow or give it its own shape. `system.json` keeps a field glyph's
  name as written (`{Méta}`, `{Page<T>}` were mangled before).
- **Replayed events say so.** A run that starts a machine in a later state replays the events on
  its way there; `--sim all`, the log and the narration now say `replayed:` for those, as SGC203
  already counted them, instead of `ignored:`.
- **`check --json` lists the state starts** it ran (`"state_starts": {"ran": […], "left_out": N}`,
  only when there are any).
- construct's check is ~7% slower than in 0.6.4 because of the seven state-start runs 0.6.5 added
  (measured: no repeated work); unchanged.

## 0.6.7 — 2026-10-28

Data can say what it holds: a data glyph's expansion lists its field names, and an
export counts those shapes in the interface, so a field added reaches every part
that reads the data. Sets like `{pending, active}` are values everywhere, and a
command piped into `less` or `head` stops quietly.

### New

- **Data shapes.** `{Doc} := { path, text, note? }` names the fields of `{Doc}`:
  bare names, comma-separated or one or more to a line. `?` marks a field optional,
  and a data glyph names a nested shape (`rows: {Row}`, or `{Meta}` alone). Shapes
  hold names only, no types or values. A data expansion is the data's shape, not a
  system: an export gives it no folder, and `{Doc}` stays a component where it was.
  See "Data shapes" in language.md.

- **Interfaces cover shapes.** A system's interface hash now covers the shapes of
  the data its boundary flows carry and the data its face's tree holds (`\-& {X}`
  at any depth); a component's covers the shapes its flows carry, its own shape, and
  its own `\-&` data. Carried data counts only when its shape is written; held data
  counts by name even without one. Field order, one line or many, and comments move
  no interface hash; adding, removing or renaming a field, or a `?`, does. So after
  a field is added, a re-export rebuilds the systems that carry or hold the data and
  rechecks the systems that depend on them. `system.json` lists each system's and
  component's `shapes`.

- **What moves for an existing spec.** A spec with no shapes and no tree data
  exports the same hashes as before. A system whose tree holds data (a face with
  `\-& {X}` children) now has an interface: its interface and body hashes move once,
  so a re-export rebuilds it and rechecks the systems that depend on it. A data
  expansion `{X} := { … }` an earlier export made a system of is `removed`. A system
  described only by a tree, with no data held and no flow in or out, still has an
  empty interface: an interface is what crosses a boundary, so write the flow that
  calls it (`[App] -> [Tab] : view({Board})`).

### Fixes

- **A set is a value, never a glyph.** `{pending, active}` in a `?>` guard,
  `branch on`, `@while`, `@inv` or a payload was read as a data glyph named
  "pending, active", drawn as a node and as a Mermaid node. A glyph name now never
  holds a comma, so a set makes no node anywhere, and `sigil highlight` colours it
  as the editor grammars already did. `{Cache<K,V>}` stays one glyph, and `{A}, {B}`
  two.
- **A closed pipe ends quietly.** When the reader of a command's output leaves
  early (`sigil highlight FILE | less` quit before the end, `| head`), every
  command now stops with exit 1 and no `BrokenPipeError` traceback.

### New lint rules

- **SGL190** (error): a set as a flow's end (`[A] -> {B, C}`). Write one flow per
  glyph.
- **SGL191** (warn): a bare name outside a data expansion. It used to be dropped
  without a word; a field belongs in its data's shape.
- **SGL192** (error): a field written twice in one shape.
- **SGL193** (warn): a line in a shape that is neither fields nor a flow
  (`rows: {Row} more`). The parser drops it.

## 0.6.6 — 2026-10-27

Sigil colours its own source: a document read the way every other command reads it,
printed in the theme's colours, handed to a host as runs, or served to a live
editor. The editor grammars in `highlight/` are checked against it, and a dialect
can bring its own theme.

### New

- **Highlight a file in the terminal.** `sigil highlight FILE` (or `-` for stdin)
  prints the source in colour: each glyph, arrow, modifier, payload, comment,
  section header, mode line, `#%` kind line and `#&` declaration in the colour its
  role has in the theme, the same colours the drawings use. It reads each line as
  lint, check and the views do (a dialect's syntax too, with `--dialect`), so the
  colours say what sigil takes the text to be; half-typed text highlights as well.
  `--theme` picks the theme, and `NO_COLOR` prints the text plain.

- **Coloured runs for a host.** `sigil highlight FILE --json` prints each line as
  runs of `[text, role, colour]` (a role is a theme path such as
  `syntax.operator` or `kinds.service`) and the state each line ends in, for a host
  that paints the colours itself.

- **A live-editor stream.** `sigil highlight --stream` keeps running and answers
  JSON-lines requests on stdin: an editor sends the lines that changed with the
  state the line above ended in, and gets back their runs and end states, so after
  an edit it highlights only until an end state matches the one it held. A request
  can also switch the theme or the dialect (`{"dialect": NAME}`, `null` for core
  Sigil); a request that fails is answered with an error and changes nothing. The
  protocol is in `sigil highlight --help`.

- **Editor grammars that match.** The grammars in `highlight/` (TextMate for VS
  Code, sublime-syntax for Sublime and bat, vim, the Pygments lexer) are now checked against `sigil highlight`,
  character by character, over the Sigil blocks of language.md and examples.md,
  the site examples and design/sigil.sigil; every remaining difference is named
  and explained.

- **A dialect's own theme.** A dialect can name a colour theme (its `THEME`: a
  theme name, or a YAML file beside the dialect module). `view`, `frames draw` and
  `highlight` use it when the dialect is loaded, so its drawings and its source
  agree. The order is `--theme`, then `SIGIL_THEME`, then the dialect's `THEME`,
  else `sigil`; a `THEME` that cannot be loaded is an error, as a bad `--theme` is.

### Fixes in the editor grammars

- A call's name before its `(` (`charge({Order})`) and an op's verb (`db.put` in
  `op db.put(…)`) are coloured as a call's name (rose), as sigil colours them.
- The names in a `state` block, on one line or many, read as state names (cyan),
  and the one-line `state {S} { … }` is no longer taken for a data glyph.
- `#&` declarations read as sigil reads them: the mark, the name, the rest muted,
  and a `{ … }` body over several lines. The `#%` kind line has its mark and known
  words coloured, and a line-leading `#!` mode line holds its whole line (a comment
  after it included).
- Held text reads as sigil reads it: numbers with units (`30s`), `[${…}]` as a
  list, hyphenated words and calls whole, `^N` then `@policy`, a branch marker's
  `{cond}` and `(N)`, the `_` wildcard, a modifier alias after `×N`.
- A block's `{ }` and a map or list literal's brackets are punctuation, `{ … }`
  with a space is no data glyph, `.field` after a glyph is one name, and a section
  level's `:` belongs to the level.
- A trigger list `-<Paid, Declined>->` and a set `{pending, active}` split at their
  commas (each name its own, the comma punctuation; a set is no data glyph).

### For hosts and dialect authors

- `--json` and `--stream` share one shape (`"sigil_highlight": 1`, per line its
  runs and end carry `[quote, decl, decl_raw, state]`); see `sigil highlight
  --help` and docs/tools.md.
- `sigil frames draw` takes `--dialect` (and colours with that dialect's theme).
- A dialect module may define `THEME` (a theme name, or a YAML path read against
  the module's folder).
- `sigil.present.highlight` is the pure core of it: `lines(text, dialect)`,
  `line(raw, carry, lexicon)`, `edit(…)` (re-highlight after an edit until the
  carry matches) and `colour(role, theme)`.

## 0.6.5 — 2026-10-26

A run can begin a state machine in a later state, so the ways out of that state get
walked and checked; a comment written under a line belongs to that line; and a
re-export asks for a second look at the systems nested inside one whose outside
dependency changed.

### New

- **Begin a state machine in any state.** A scenario part `Owner=State` starts that
  machine in State and plays the episode from its entry as usual: `--sim
  Ticket=Done` walks what `Done` does with each event, which a run from the initial
  state might never reach. It combines with the other parts through `+` (listed
  names, `Entry@t`, field choices: `Ticket.kind=urgent+Ticket=Done`), and the run's
  narration opens with `{Ticket} starts in Done`. An unknown state is refused with
  the owner's states listed; `+` and `$` are no states to begin in.

- **The state starts are listed.** After the overlap runs, the scenario list
  (`--sim list`, `--sim all`, the plugin panes, the playground) holds one run per
  machine state, other than the initial one, that a transition leaves, labelled
  `starts with {Ticket} in Done`.

- **A spec check walks the state starts.** In `#!spec` the behavioural rules run
  them after the failure runs and before the overlap runs, within `--budget` (the
  overlap work cap stays the overlap runs' own), whatever `--overlaps` or the `#%`
  kind says. A finding only such a run shows names it as its witness (`<Nudge>`
  reaches `{Ticket}` while it is `Done` and is dropped in the `Ticket=Done` run),
  and the SGC090 hint counts any it left unrun. An event on the machine's way to
  its start state, arriving again, is the replay of how it got there, not an
  `event-ignored` drop. Sketch and craft checks are unchanged.

### Fixes

- **A comment indented under a line describes that line.** A comment-only line right
  below a statement line that holds no comment and opens no block, indented deeper
  than the statement, is that line's trailing comment (lines below it in the same
  column continue it), as if written at the end of the line. Before, it described
  the next statement instead, and the last statement of a block or file lost it.
  Under a continuation line it goes where that line's trailing comment would. A
  comment at the statement's own column, under a block opener, or between a line and
  its continuation is a comment above what follows, as before. Every view's notes
  and the export's descriptions read it the same way. *Moves:* the body hash of the
  components (and their systems) whose description changes.

- **A re-export rechecks the systems inside one whose outside dependency changed.**
  A nested system's members make up the systems enclosing it, so they use what
  those depend on. When a system an enclosing system depends on, outside that
  enclosing system, changes its interface, the nested system is now `recheck`
  (before: `unchanged`); `because` names the changed system and the new `via` the
  enclosing system it came through (`Store (via Outer)` in the summary). The
  manifest's systems gain `parent` so the delta reads the nesting from the
  manifests; an older manifest without it still compares. `depends_on` stays the
  system's own flows, and no hash moves.

## 0.6.4 — 2026-10-25

Fixes for what large real specs ran into: the export reads homes, the top and
dependencies the way a designer means them, an error route can sit on the call's
own line, and two checks stop flagging designs that are fine.

### Fixes

- **A one-line error route is the call's route.** `[A] -> [B] : run({X}) => {Y} !>
  <Fail>` and `[Worker] -> run({Job}) => <ok> !> <fail>` now mean what `!>` on the
  line under the call means. Before, the route was read as part of the payload (the
  run said "[B] returns {Y} !> <Fail>", and `<Fail>` was sent on every run as an
  entry of its own), or as a route from the returned glyph. Modifiers written after
  the route belong to the route, as on the line under. `[A] -> [B] !> <E>`, with no
  payload or return before the `!>`, is still `[B]`'s route. Lint, every view, the
  simulator and export all read the same graph.

- **A route inside a block is taken.** A call's `!>` inside a `loop` or an `@owns`
  scope now routes that call's failure in the simulator, and `unhandled-failure`
  (SGC201) reads it the same way, so language.md's worker-loop example no longer
  raises a false finding.

- **A field branch decides where it is written.** `branch on {X}.f { … }` between
  two flows of one source used to run after all of that source's flows (its arm
  fired after the record had reached its end). It now runs in the order written.

- **`expansion-escape` (SGC172) reads membership, not mentions.** A part declared
  inside a unit stays that unit's, however an outer level also reaches it, and a
  link stated between anything enclosing one end and anything enclosing the other
  connects them (`[Draw] -> [Core]` covers a member of Draw's unit calling a member
  of Core's). On one real spec this cleared 15 of 16 false findings. The trade-off:
  a member that also acts at the top level is still read as its holder's.

### Export reads differently

These change what `sigil export` writes for the shapes named; other specs export
exactly as before.

- **Homes: a level that only names a part never homes it when another declares it.**
  A part declared in one unit (`[Core] := { [Text] … }`) and named in another unit's
  flows (`[Buffer] := { [Cells] -> [Text] … }`) lives in Core, and Buffer depends on
  Core; before, SGC401 `no-home` blocked the export unless the naming unit was
  nested under the declaring one. Mentions in passing are references too: a block's
  subject (`branch on {X}.f`, a loop's or parallel's subject), an arm's body, a
  borrowed store and a join's member no longer count as a place a part is written
  (a `branch on {Contract}.fit` no longer made `{Contract}` homeless). A part
  declared nowhere still lives in the outer level (never homeless).
  *Moves:* the body hash of each moved component and of the systems it leaves and
  joins; their folders gain or lose its file.

- **A service named as the top is the top.** A top-level `[Shop]` in `shop.sigil`
  (or under `--name shop`) that roots a tree or owns an expansion is the top's face:
  one system, its members and comments the top's. Before, export wrote a `Shop`
  system and a `shop (top)` beside it, in two folders. A store or another kind named
  as the top keeps `NAME (top)`. This reverses 0.6.1's "`--name` renames no
  system": a `--name` that matches such a service makes it the top.
  *Moves:* the top system's hashes, every component of the face's system (now homed
  at the top), and the folders (one instead of two).

- **Data a flow carries is a dependency.** A `{D}` named in a flow's payload, op
  arguments or return, when `{D}` is a homed component, makes both ends' systems
  depend on `{D}`'s system (not their own, nor one enclosing them). Data named only
  in payloads makes none. `depends_on` (manifest, system.json, the index README) and
  `view --structure` gain these links (so `unit-cycle`, SGC176, can now see a cycle
  made through carried data); no hash reads dependencies, so no hash moves,
  but a re-export now reports such a system as `recheck` when that data's system's
  interface moves.

- **A one-line route** (above) changes the payload text of flows that wrote it, so
  their components' and systems' hashes move once.

## 0.6.3 — 2026-10-24

State machines say more in fewer lines, and the end state `$` means what the
checks already told you to write. A design can say what kind of system it is, and
the checks it cannot need step aside. The viewer uses the whole window.

### New

- **Trigger lists.** `S -<A, B>-> T` is `S -<A>-> T` and `S -<B>-> T` on one line,
  and every tool reads it as those lines. One line per state can now say everything
  that state ignores (`Built -<Planned, Assigned, Passed>-> Built`), or where several
  triggers lead (`Busy -<Paid, Declined>-> Idle`). Lint warns (SGL090) on an empty
  or repeated item.

- **System kinds.** A `#%` line under the mode line says what kind of system the
  design is: its shape (`service`, `library`, `daemon`, `job`), reach (`networked`,
  `in-process`) and concurrency (`concurrent`, `deterministic`). Each word turns off
  the group of checks its kind cannot need, so an agent is no longer pushed to
  restructure a design, or acknowledge rule after rule, for risks it cannot have:
  - `library` turns off entry (unreached, orphan event, undriven transition) and
    traffic (capacity, single point of failure); `job` turns off traffic;
  - `daemon` turns off ending (no-exit, wait-without-timeout, async cycle,
    unbounded loop);
  - `in-process` turns off network (timeouts, retries, duplicates, stale reads);
  - `deterministic` turns off concurrency (races, ordering, lost updates) and makes
    no overlap runs.

  Nothing is silent: the summary names every rule the kind turned off, `--json`
  lists them, `check --rules` shows each rule's group, and `check --all-rules` runs
  them anyway. An acknowledgement of a rule the kind turned off is reported unused.
  Lint checks the line (SGL093 an unknown or doubled word, SGL094 a `#%` line it
  does not read, SGL095 a race in a `deterministic` system). No `#%` line: the
  checks are as before.

### Fixes

- **`$` honours its own self-loops, and begins a new record through `+`.** An event
  that reaches a machine at `$` used to be dropped every time, so following the
  SGC203 hint, "the self-loop `$ -<E>-> $`", could never resolve the finding. Now:
  - `$ -<E>-> $` ignores a late `E` on purpose, and SGC203 is quiet;
  - an event with a `+ -<E>-> S` transition begins a new record in `S` (an order
    placed again is a new order);
  - `_` still never reaches `$`, and any other transition out of `$` is a lint
    error (SGL092).

  The SGC203 hint at `$` now names only these two fixes.
  The run narration says so: "{Order} ignores <pay> after its end, on purpose", and
  "{Order} begins again in Open on <place>: a new record".

- **The viewer uses the whole window.** A drawing narrower than the window used to
  open centred, leaving a wide blank margin on the left. It now opens at the
  top-left, and the graph and flow views lay their sections side by side when the
  window is wide enough: in order, down each column, the shortest layout that fits.
  At 200 columns a design that took 114 rows of flow view takes 59. A drawing that
  fits in one column, and the tree view (whose lanes run through every section),
  draw as before; `z` still centres.

## 0.6.2 — 2026-10-20

Sigil can now judge a design's structure, not only its flows. A new structure
reading and two new checks measure units, dependencies, reach and size. The skill
gains a refine loop that uses them after every feature. The checks no longer pass
on simulation runs that never finished.

### New

- **The refine step in the skill.** After each feature it adds with you, the agent
  reads the design from eight angles:
  - purpose and names;
  - dependencies;
  - blast radius (how far a failed or hostile part could reach, and who can drive it);
  - complexity, composability and efficiency;
  - behaviour.

  It proposes each structural change with its reason and measured cost, then
  re-measures, until a full round finds nothing you want changed. A refinement you
  agree to is kept apart from check findings, which are still resolved only by
  declaring or acknowledging them. A delegated run with no one to ask applies only
  what matches what is already known, and lists the rest as proposals.
- **`sigil view FILE --structure [--json]`** reads the design as units, with no
  drawing, in any mode. For each unit it shows:
  - its members (actors kept apart), its flows, and the units it calls and holds;
  - cycles between sibling units, with the flows that make them;
  - *up* links into an enclosing unit;
  - the edge: the parts that call an actor;
  - each part's reach, out and in;
  - pass-throughs;
  - units over 9 members;
  - parts with no home;
  - writers per store (counted from the flows, even without `@read`/`@write`).
- **New check rules:**
  - **SGC176 `unit-cycle`:** two sibling units that depend on each other. It is a
    warning in spec mode, which blocks export unless acknowledged on a unit's
    header.
  - **SGC177 `large-unit`:** more than 9 built members, actors not counted. Info only.
- **`sigil export … --limit NAME=N`** and **`sigil frames draw … --limit NAME=N`**
  take the simulator's limits, as `check` and `view` do.

### Changed

- **A run cut at the simulator's limits is now a spec-mode warning**
  (SGC090), so it blocks export unless acknowledged on its entry's line. Before, a
  large spec could pass `check --mode spec` and the export gate on runs that never
  finished.
- **The default `frames` and `activations` limits grow with the document**
  (128 and 20 × its nodes plus edges, never below 2000 and 500). Large designs
  finish their runs at default limits, small ones are unchanged, and a given
  `--limit` still wins. SGC090 and `check --json` show the limits the runs actually
  had.
- **The overlap sweep in spec mode stops at a work cap** (400 frames a run × the
  budget). A large spec's `sigil check` takes seconds again; one example went from
  about 7 minutes to 12 seconds. When the cap stops it, the hint says how many runs
  were left.
- **Where components live in the export:**
  - **An expansion** written at the top for a member of another unit nests under
    that unit. It is also run there by the simulator, and SGC172 no longer calls a
    wire to it an escape.
  - **An actor** creates no dependency between systems and is never *no-home*.
  - **A level that writes a part only as an end of its flows** refers into the unit
    that writes the part, and is no longer its home. Examples are an actor's entry
    line such as `(Client) -> [Transport]`, or a top-level flow into a part a unit
    writes. The part now lives in its unit, together with an expansion written at
    the top for it when the unit declares it. A part is never left homeless: one
    used by two sibling units stays at the level above, as before. **The first
    re-export after upgrading may mark such systems `rebuild`.**
- **A comment-only line aligned under a trailing comment continues that comment**,
  in notes, export descriptions and the views. Before, it described the next
  statement.
- **Overlap scenario labels** name the part that writes or reads (`as [Status]
  reads it`), not the episode's entry.
- **A cut run's log and narration** say which episode reached the limit and from
  which tick.

### Fixes

- **SGL030 (prose verb between glyphs)** reads the parsed tokens, so payload verbs
  such as `: calls(…)`, `sends(` and `reads(` are no longer flagged.
- **SGC090's loop-cap hint** reads the given `--limit iterations=N`.
- **Plain `sigil export --mermaid`** no longer fails on a dialect kind its
  `NODE_KINDS` doesn't list; it draws the core shape.
- **The viewer split's control file is private.** The Claude Code mod and pi create
  it in a 0700 directory with mode 0600. `sigil frames follow` refuses a control
  file, or its directory, that another user could write. The file names a `sigil
  view` command line, which can load a dialect's code.

## 0.6.1 — 2026-10-18

The export carries what a consumer needs to build and track work without reading
the spec again: hashes per component, the dialect's declarations and version, and
the spec lines behind every component and flow. The multiplex viewer can open in a
tab, and a check cut short by a simulator limit says which flag raises it. Nothing
else that the tools print changes.

### Export

- **Hashes per component.** Every component in `system.json` has
  `hashes: {interface, body}`: the interface covers its flows in and out with their
  modifiers, the body its whole form (kind, home, the other systems it is written
  in, description, interface, requirements, lifecycle, a dialect's attributes).
  Every system in `manifest.json` gains `component_hashes: {glyph: {interface,
  body}}`, in the order of its `components`. A component is the unit a builder works
  on, so it is the unit that goes stale.
- **`#&` declarations are exported.** Each system's `system.json` lists the
  `#& name …` declarations of its scope as `declarations: [{name, body, line}]`
  (top level and alias bodies on the top system, an expansion's body on that
  system), the body as written. The body is part of the system's body hash; no
  interface or component hash changes. A dialect's settings reach whoever builds
  without reading the spec.
- **`sigil export SPEC --out DIR --name NAME`** names the top system (default: the
  file's stem, as before); `--mermaid --spine` takes `--name` too. A blank name, or
  `--name` on plain `--mermaid` (which draws no top system), is refused. The top
  system's name no longer enters any hash, so renaming the spec moves none. This
  changes the top system's body hash of every existing export once (07-export's:
  `23efe2ea06bd3482` → `75979ceff2c70e06`); the other systems' hashes are unchanged.
- **The top yields a shared name.** A top named like one of the spec's systems
  (by `--name` or the stem) is keyed `NAME (top)`; the system keeps its name, key,
  folder and hashes. Before, the system was renamed `NAME (service)` and its body
  hash moved.
- **A renamed top is no change.** `manifest.json` records the top system's key as
  `top`. Re-exported under a new name (another `--name`, or a renamed spec without
  one), the top's key and folder follow the name, and `delta.json` says
  `renamed: {from, to}` (else `null`) and compares the top with its old entry: no
  system is added, removed or rechecked for the rename alone.
- **A dialect's glyphs keep their brackets.** A component of a dialect's node kind
  is written with its `NODE_KINDS` `open`/`close` (`[[Ledger]]`, not `Ledger`) in
  `components`, `component_hashes`, `glyph` and the flows' ends, so two kinds
  sharing a name stay two components.
- **`delta.json` on every export.** A first export writes one too, with
  `"from": null` and every system `added`, so a reader always finds one. Its shape
  and the delta's printed lines are unchanged.
- **The dialect is recorded.** With a dialect loaded, `manifest.json` gains
  `dialect: {name, version}` (between `spec_hash` and `systems`); `version` is the
  dialect module's `VERSION` as text, left out when it defines none. With no
  dialect the key is absent.
- **Source lines.** Every component and every flow in `system.json` (the system's
  interface, the flows inside it, each component's interface) carries `lines`, the
  1-based spec lines that write it. No hash reads them.
- **A dialect's node attributes.** What a dialect's tokenizer puts in `Node.attrs`
  is exported as the component's `attrs` (JSON-safe: a tuple as a list, a set as a
  sorted list, anything else as its text), and enters its body hash. Core glyphs
  carry none.
- **Only differing files are written.** Each export file is written only when its
  content differs, inside a changed system folder too (before, a changed system's
  folder was rewritten whole). A reformat that moves lines now rewrites the
  `system.json` files whose `lines` moved (with the index, the manifest and
  `delta.json`, as before) and no component file.

### Check

- **SGC090 names the flag.** When a run is cut by a simulator limit, or stops
  spawning or looping at one, the fix reads `run with a larger frames limit
  (--limit frames=N)` (depth, spawns, … likewise), where it said `run with larger
  limits` or `run with a larger spawns limit`; when
  a check runs out of runs it says `run with a larger budget (--budget N), or a
  smaller --k`. (`sigil check --limit NAME=N` itself has been there since 0.6.0;
  this release only names it in the fix, and `sigil --help` now lists it.)

### Viewer plugins

- **`placement`: `split` or `tab`.** A new plugin option says where the multiplex
  display opens `sigil view`: `split` (the default, a split to the right, as
  before) or `tab`, a tab of its own labelled `sigil view` that does not take the
  focus where the multiplexer allows (a herdr tab in the session's workspace, a
  tmux window, a zellij tab). `/sigil-pane placement [split|tab]` says or sets it
  (Claude Code: the `/config sigil.placement` row; pi: `viewer.json`, or
  `--sigil-placement` / `SIGIL_PLACEMENT` for one session). Multiplex replies name
  the placement (`Opened a herdr tab running sigil view live …`); for `split` they
  read as before. An open view is reused only while its placement matches.

### Docs

- `language.md` "Ready to export" says how descriptions are read: a header comment
  with no blank line after it describes the first statement's node, not the
  document. It also lists what the export records.
- `docs/tools.md` gives the full `manifest.json` and `system.json` schema and the
  `--name` flag, and `sigil/core/dialects.py` documents `VERSION`, `Node.attrs` as
  exported, and that `KNOWN_MODIFIERS` / `DEFERRED_MODIFIERS` entries are written
  with their `@` (`{"@at"}`).

## 0.6.0 — 2026-10-18

One command instead of seven scripts, Mermaid as an export with a new chart grouped
by system, the tools rebuilt as one package along the drawing of sigil in sigil
(`design/sigil.sigil`), and one reading of the text: lint and the parser now read a
document the same way. What the tools print is unchanged, apart from the messages
naming `sigil <command>`, the few lint and drawing changes under "One reading of
the text" and the fixes listed below.

### One command

- **`sigil <lint|check|view|export|frames|themes>`** replaces `lint.py`, `check.py`,
  `view.py`, `export.py`, `render.py`, `themes.py` and the Claude Code mod's
  `pane.py`. Run it as `bin/sigil` (Python 3 standard library only) or
  `python3 -m sigil`; the skill runs `scripts/bin/sigil`, and the plugin commands,
  the Claude Code mod and the pi extension call it too. Flags are
  the same as before:

  | 0.5 | 0.6 |
  | --- | --- |
  | `lint.py FILE [--deep]` | `sigil lint FILE [--deep]` |
  | `check.py FILE …` | `sigil check FILE …` |
  | `view.py FILE …` | `sigil view FILE …` |
  | `export.py SPEC --out DIR` | `sigil export SPEC --out DIR` |
  | `render.py FILE [--depth N] [--composition …]` | `sigil export FILE --mermaid [--depth N] [--composition …]` |
  | `plugin/claude/scripts/pane.py draw` / `follow` | `sigil frames draw` / `follow` |
  | `themes.py [NAME] [--list]` | `sigil themes [NAME] [--list]` |

  `sigil --help` lists them all, `sigil CMD --help` gives each one's flags, and
  `sigil export --help` shows both of its forms (the folder and `--mermaid`). Each
  subcommand loads only what it needs: `sigil lint` loads neither the checker, the
  simulator nor the views, and `sigil lint --deep` and the export gate read the
  document once for lint and check together.
- **Messages say `sigil <command>`.** Errors on stderr and usage lines begin with
  the subcommand (`sigil lint: …`, `sigil check: …`, `sigil view: …`,
  `sigil export: …`, the Mermaid chart's too) where 0.5 printed `lint.py: …`,
  `render.py: …` and so on, and an export's index `README.md` says it was written
  "by sigil export".
- **`sigil themes [NAME|PATH]`** prints a colour theme resolved, as JSON, and
  `sigil themes --list` lists the themes it finds.
- **Mermaid is an export.** `sigil export FILE --mermaid` prints the chart
  `render.py` printed, byte for byte, in any mode (no readiness gate: a sketch draws
  too, for review).
- **New: `--mermaid --spine`** groups the chart by the systems an export would make:
  a subgraph per expansion or composition tree, nested as the export nests them,
  each component in its home. It is the shape to look at before exporting a spec.

### One reading of the text

Lint and the parser used to read a document separately, and they disagreed on odd
input: lint could warn about something the drawing did not show, or the drawing
could show something no rule reported. Now one statement walk and one tokenizer
feed both, so lint reports what the drawing shows, and `sigil lint` reads a
document once. Where the two readings differed, the parser's was kept unless it
was plainly wrong. What changes:

- **Inside a `"…"` string, everything is string text.** A `#` there starts no
  comment for any rule (before, lint's line rules cut at any ` #`, so
  `: "a #" """…` could raise a false SGL170 and SGL151), and a brace there opens
  or closes no block (before, `: "}"` could end a loop or state block early, and
  `: "{"` could swallow the rest of a block or of the document).
- **A branch marker `\-` counts only where the tree reads one**: at the start of a
  line, after a parent glyph, or after a line's leading branch. Elsewhere (inside a
  string, a payload or prose) it is text, and SGL110 no longer fires on it. In the
  repository this changes one output: the grammar fragment in `language.md` loses
  two SGL110 errors.
- **A broken glyph places no node.** An unclosed or empty glyph (`[A] -> <B -> [C]`,
  `[]`) draws nothing, and nor does an arrow into or out of it; before, it drew a
  node named after the broken text (`B -`) or joined the arrow to the line above.
  A glyph closed by the wrong bracket (`[A}`) still reads as its opener's kind.
  Lint reports the same SGL120–SGL122 as before; Mermaid and `sigil check` lose the
  phantom nodes (and a check finding about one, such as an orphan event).
- **Modifier arguments in a block header name no node.** `loop @times(2) {` no
  longer draws an actor `(2)`, nor `@inv ordered(Physics, Steering)` an actor
  `Physics, Steering`, nor `@enum Mode { fast, slow }` a data node `fast, slow`.
- **A free modifier argument ends where the next part of the line begins**: an
  access list, a `^N` bound, the block's `{`, a trailing `×N` or `!`. With `--mods`,
  `~|Seats| @inv cas(version) @read(…) @write(…)` is labelled
  `@inv cas(version)`, no longer `@inv cas(version)     …`. Braces inside the
  argument stay (`@inv status in { open, closed }`).
- **A `${…}` ref names no data glyph**, outside a payload too:
  `[X] -> |tree| ${out.subtree}` and `loop @each kid of ${out.kids} {` no longer
  draw a phantom data node.
- **State blocks.** `state Order {` (no owner glyph) is now reported (SGL161, "no
  owner glyph") and draws nothing; before, its lines were drawn as stray flows. A
  machine's lines are judged once: SGL161 quotes the line it means
  (`` `A -<>-> B` has no trigger ``), a line the machine drops that writes a
  trigger (`A-<x>->B`) gains SGL090, and an owner-less machine is reported once, on
  its head.
- **Access lists split at commas outside strings** and quote a member as written:
  `@read(A, "B, C")` gives one SGL142 for `"B, C"` (before, two).
- **Block-strings.** A line that closes one `"""` block and opens another reads
  both; before, the parser missed the second and the flows after it.
- **A tree ended by a plain line is reported.** A plain glyph line at a branch's
  indent ends its composition tree, so a `\-` branch under it has no parent; the
  drawing always dropped it, and now SGL111 says so, with the rule in its message
  ("its parent is the nearest glyph line above at a shallower indent …").
- **A branch marker inside a `"""` block-string** no longer anchors SGC167; the
  finding sits on the real branch line.
- **A continuation under a malformed section header** (`--- L2: [X]` with no closing
  dashes) continues from the glyph that line drew, as the drawing does, so it no
  longer adds SGL130 next to the header's SGL184.
- **SGL153 is retired**: it compared the two readings of an event's arguments,
  which can no longer differ. Its id stays reserved.

### Fixes

- **No false cycle through the top system.** A flow into an expansion's owner (or a
  tree's root) is now a dependency on that system alone, not also on the system the
  owner is written in, so a design drawn as layers no longer exports every layer as
  depending on the top one.
- **SGC204's hint says where `@inv serialised(|S|)` goes**: on the store's own line
  (written on the write, it did nothing).
- **Lint's path and trigger rules (SGL112, SGL091) report the flow's own line**, read
  from the parsed document; a path also written earlier (in a comment, say) used to
  report that earlier line.
- A plain check leaves out an unused acknowledgement of an export readiness rule by
  the rule's id, no longer by the shape of the finding's scope.
- **The Claude Code plugin says which Claude Code it needs: 2.1.281 or later.**
  Older versions refuse to install it (`userConfig … Unrecognized key: "options"`
  before 2.1.260) or to load its viewer mod; 0.5.0 needed the same. `claude update`.
- **SGC205 reads a state machine's `} @inv ordered(…)` from its own closing `}`**; a
  machine closed on its last transition line no longer borrows a later block's.

### The package

The tools are one package, `sigil/`, with a subpackage per layer, each an expansion
of `design/sigil.sigil`: `core` (lex, tokens, statements, parse, graph, comments,
dialects, vocab), `model` (scene, the simulator `sim/` as program, engine,
scenarios and narration, the export model), `analyse` (lint by rule group, check
and its rule modules), `publish` (mermaid, spine, the exporter and its delta) and
`present` (the viewer app, the four views, kit, themes, frames), plus `cli`. A layer
imports only the layers above it (`core ← model ← analyse ← publish / present ←
cli`), and `tests/test_spine.py` checks every import. The lexical tables the
parser and the linter each kept a copy of live once, in `sigil/core/lex.py`; the
export model reads statement lines from the parser instead of searching the text.
`docs/tools.md` describes the layout.

The page's playground loads the same package into the browser (less the export
layer), and the plugin archives ship `sigil/` and `bin/sigil` in the skill's
`scripts/`.

### For dialect authors

A dialect imports the core's vocabulary from one public place, `sigil.core.vocab`
(`from sigil.core.vocab import strip_comment, ARROW_RE, GLYPH_PATTERNS,
ANY_GLYPH_RE, LintResult, VALID_MODIFIERS, CALL_RESILIENCE_MODIFIERS,
PERMISSION_MODIFIERS, VALID_LOOP_MODS`), not by loading `lint.py` by path. A
dialect's wrapper command calls `sigil.cli.main(argv, dialect=NAME)`; dialects are
still found by name next to the repository (`../sigil-<name>/dialect.py`) or on
`SIGIL_DIALECT_PATH`.

**One hook set.** A dialect hooks the one reading every tool shares, instead of a
`lint_*` and a `render_*` hook for the same job:

| 0.5 | 0.6 |
| --- | --- |
| `lint_prepasses()`, `render_prepasses()` | `prepasses()`: line rewrites before the walk, run by lint and the parser alike |
| `render_line_strips()` | `strips()`: now **length-preserving** (blank with spaces, never delete), applied to flow statements only, after a branch marker is read; a blank that depends on context goes in a prepass |
| `render_tokenizers()`, `lint_glyph_masks()`, `lint_principal_scanners()` | `tokenizers()` (the signature `render_tokenizers` had): a glyph it reads is a node, a lint endpoint, a definition head and a principal name alike |

A dialect that still defines a 0.5 hook fails to load, with an error naming the
hook that replaces it. A strip that changes a line's length, or a prepass that
changes the line count, is refused the same way: every command prints
`sigil <command>: …` naming the hook and exits 2 (before, a traceback or lines
that silently drifted). With a dialect's `COMMENT_MARKERS` (say `//`), a `#=` after
the marker is comment text (no SGL188), and an acknowledgement under the marker
exports its comment text. `lint_passes()`, `lint_payload_checks()` (whose `site` adds
`branch`, true on a composition-branch statement), `COMMENT_MARKERS` and the data
and check hooks keep their names. `strip_comment` in `sigil.core.vocab` is now
string-aware: a `#` inside a `"…"` string starts no comment. `docs/tools.md`
("Dialects") lists the hooks.

**`#& name …` is core syntax for a dialect's declarations**, as `#!` is for the
mode. Core reads a line-leading `#& name …` (or `#&name`, the same) as a
statement that draws nothing, never a comment, a note or a flow, and the
`{ … }` block it opens (`{` or `~{`, one line or many) as a body no rule reads,
with or without a dialect (before, core read such a block's lines as flows unless
the dialect's `DECLARATION_BLOCKS` matched it, and per-line lint rules still read
a matched block's body). A new hook, `DECLARATIONS`, lists the `#&` names a
dialect declares, and lint warns (SGL189) on a name no loaded dialect declares; a
dialect without the hook hears nothing. `sigil.core.vocab.declaration_name(line)`
reads the name. The viewer's title steps over the mode line and `#&`
declarations, and reads comments the dialect's way (its `COMMENT_MARKERS`): a
document whose opening comment comes after a declaration, or is written with the
dialect's marker, now gets a title.

## 0.5.0 — 2026-10-15

Runs whose entries happen at the same time, and checks that look for races between
them; and a finished spec exported as a build skeleton, with a manifest as the
contract and, on every re-export, the list of what changed.

### Runs that overlap

- **An entry can start at a tick of its own.** A run used to play its entries one
  after another, each starting once the one before it went quiet. Now a scenario can
  say `Author@25`: `(Author)`'s episode starts at tick 25 while the earlier ones are
  still running. It combines with any other scenario (`Builder.claim:fallback+Author@25`).
  Entries without a start tick keep the old rule. The run is still the same every
  time: running episodes take turns in a fixed order each tick.
- **A few overlap runs are listed for you.** After the failure scenarios,
  `--sim list` and `--sim all` add runs that start each later entry just as it would
  reach something an earlier entry is busy with (a store, a state machine, a node,
  an event): the moments a race could happen. At most 3 per pair of entries and 12
  in all (`--limit pair_overlaps=N`, `--limit overlaps=N`); their labels say what
  meets ("(Author) starts at t25, reaching |Export| as (Operator) reads it"). Any
  other `Entry@t` runs by name.
- **You can tell the episodes apart.** While more than one runs, each narrated
  sentence starts with its episode (`ep2: `). The graph, tree and flow views draw
  each token as its episode's number in that episode's colour, from a new theme
  section `run`. The run view marks where each episode starts on the ruler, in its
  colour, and lists the episodes under the drawing (`▸` on the running ones while
  it plays). `--run --json` lists each episode's start tick, entry and the episodes
  it began alongside, and `--sim Entry@t --json` lists the episodes too. A run with one episode at a time looks exactly as before.
- **A new example**, `overlap.sigil` (on the page and in `site/examples/`): an
  author exports while a builder is mid-build, and the stale notice lands between
  two of the builder's steps.

### Export a spec

- **A new tool, `export.py SPEC --out DIR`,** hands a final design to whoever builds
  it: a folder per system, a Markdown file per component (its kind, description,
  interface, requirements and lifecycle, as the spec writes them), each system's
  `system.json` with the same as data, an index `README.md`, and `manifest.json`, the
  contract. Systems need no new syntax: each `X := { … }` expansion, each
  composition-tree root, and the top level (named after the file).
- **Only a ready spec exports.** The document's mode line is `#!spec`, lint finds no
  error, and the checks (overlap runs included) leave no error or warning
  unacknowledged. Otherwise `export.py` prints what blocks it, exits 2 and writes
  nothing.
- **The manifest holds two hashes per system:** its interface (the flows that cross
  its boundary, with their payloads and returns) and its body (everything in it).
  Reformatting or reordering the spec changes neither; changing a payload, a
  modifier, a comment or a state does.
- **Exporting again says what changed.** `export.py` compares with the manifest
  already in the folder and lists each system as `added`, `removed`, `rebuild` (its
  body changed), `recheck` (unchanged, but a system it depends on changed its
  interface) or `unchanged`, in words, in `delta.json`, or as JSON (`--json`).
  Only changed files are rewritten, a builder's own files in a system folder stay,
  and `--dry-run` shows the delta without writing.
- **Two readiness rules,** run only with `check.py --export` (the export's gate), so
  every other check output is unchanged: SGC401 `no-home`, a component written in two
  systems neither of which encloses the other, and SGC402 `untyped-boundary`, a flow
  across a system boundary with no payload or a call across one with no stated
  return. `--rules` lists them.
- **A new example**, `export.sigil` (on the page and in `site/examples/`): a small
  shop that exports as five systems.

### Checks

- **Races between entries are found.** `check.py`'s behavioural rules now also try
  each later entry started at every tick of an earlier entry's episode, not only the
  listed few, so a race that shows a few ticks after the first contact is still
  found: two writers from two episodes, or an event landing in a state that exists
  only mid-episode. The finding's witness names the run (`… in the Bob@0 run`), which
  `--sim Bob@0` replays. These runs share `--budget` with the failure combinations
  (the listed overlap runs first, so a small budget still reaches every pair);
  `--limit window=N` sets how many start ticks one pair may try (64).
- **Overlap runs are the exhaustive check, so drafts skip them.** `check.py
  --overlaps off|listed|all|N` picks which overlap runs to make. The default is
  `all` for a `#!spec` document (the check before a spec is final) and `off` for
  sketch and craft, so a check while drafting stays as quick as before.

### Agent plugins and page

- The Claude Code and pi viewers list and play the overlap runs like any other, and
  the viewer tool's `scenario` field takes `Entry@t`.
- `export.py` ships in every plugin archive, and `/sigil-lint` says how to export
  once a spec is clean. The playground does not export.
- The playground groups the overlap runs under "overlaps" in its scenario menu. Its
  checks make at most 96 runs per exploration, so a large document stays quick in
  the browser; every bundled example finds what `check.py` finds.

## 0.4.4 — 2026-10-14

Fixes for what 0.4.3 left open. No new features.

### Viewer

- **The run view at `--depth`:** a loop inside an expansion folded into a node's lane
  now shows in that lane's note as well as in the narration ("loops 3× (inside)"), its
  iterations counted as the node's. `--run --json` marks those iterations
  `"inside": true`.
- **Changing the depth redraws at once.** Code that drives the viewer and sets its
  depth gets a drawing at the new depth straight away, as the `d` key always did; it
  no longer has to ask for a redraw itself.
- **The flow view** remembers which wrap each pattern of blank badges needed, so a
  playing run whose badges turn blank and back no longer repaints earlier wrap steps
  first. Every frame draws exactly as before, with fewer repaints.

### Notation tools

- An op verb holding an enclosing mark after a letter (such as U+20DD, a circle drawn
  around the letter) is one op-call in `lint.py`, `render.py` and the views, as
  combining marks already were. One shared set of test verbs now checks that
  `lint.py` and `render.py` read verbs alike (each keeps its own copy of the rule, so
  `lint.py` stays a standalone tool).
- **`lint.py` reports a malformed `op` call written as an arrow's target**, as it
  already did for one written as a payload: `[Api] -> op ns.9x({Job})` is SGL102 (each
  part of the dotted name must start with a letter). `render.py` and the views still
  draw it as written, one op-call, as they do every malformed op-call.

## 0.4.3 — 2026-10-14

Fixes for what 0.4.2 left open. No new features.

### Viewer

- **The run view at `--depth`:** a node busy on the work of an expansion folded into
  its lane now counts as busy, so that stretch is no longer squeezed into a `≈`
  column as if nothing happened. A loop inside a folded expansion is narrated as the
  drawn node's ("[Shop] loops (inside)"), not as a loop of the node itself.
- **The flow view** picks its wrap again when a run's badges change a frame's width
  or turn blank, so every frame of a playing run draws as it does on its own. A run
  that fits costs no more a frame than before.
- **One depth everywhere.** Setting the viewer's depth (from `--depth`, `d`, or code
  that drives the viewer) draws every view at that depth and tells the run the same
  depth, so a run's drawing and its narration never disagree.
- Two neighbouring stretches of one colour that come from different theme roles
  stay apart, so each keeps its own role when the drawing is repainted. What you see
  is unchanged.

### Notation tools

- An op verb written with a combining mark (a decomposed `ガ`, `カ` + U+3099) is one
  op-call in `lint.py`, `render.py` and the views, as the composed form already was.
- `render.py`'s Mermaid ids can no longer collide between an ASCII name spelt like an
  encoded character (`[u005229]`) and a non-ASCII one (`[利]`). Ids of other ASCII
  names are unchanged.

### Agent plugins and CI

- **CI type-checks the pi extension** and the logic it shares with the Claude Code
  mod on every push, now through bun with pinned TypeScript and `@types/node`
  (a dev-only `plugin/pi/package.json` and `bun.lock`, never shipped). Its first run
  found three fixes: pi's widget type now takes the plain text lines that RPC mode
  sends; the herdr wait command's first word can no longer read as undefined; and a
  Claude Code mod test whose filter the test kit ignored now checks the docked
  pane's height.
- The Claude Code plugin's README says why pane rows holding a wide character are
  drawn as text rather than repainted in place: the engine's `Raster` takes only
  one-column cells.

## 0.4.2 — 2026-10-10

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
