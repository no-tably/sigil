# Viewer coverage audit — `coverage.sigil`

Fixture: `tests/fixtures/coverage.sigil` (one `#!sketch` doc, 3 layer sections + 2 topic
sections). `./lint.py` → clean apart from one **info** (`SGL070`, line 83): the spec's own
recursion example `[Tree.walk] -> [Tree.walk] : child` puts the same glyph twice on a line.
Kept, because language.md uses that exact line.

Runs (all exit 0, no crash; `--color never` so strokes are judged without colour):
`view.py --once --no-lint` with (default), `--depth all`, `--payloads`, `--notes markers`,
`--tree`, `--tree --depth all --payloads --notes callouts`, `--tree --no-triggers`,
`--depth 0`; plus `render.py` (Mermaid). Footer: `121 nodes, 76 edges, 7 expansions` at the
audit; `127 nodes, 74 edges, 7 expansions` after the render.py model fixes.
The default graph was **392 columns wide** for this document; split into its sections and
block frames it is now **228** (227 before the self-call stubs).

Grades: **DRAWN** works · **WEAK** there but ambiguous, toggle-only or text-only · **LOST**
nothing in the drawing · **WRONG** the drawing misleads (phantom node, wrong edge). "mono" =
true with `--color never`, where colour is the only cue.

## Status after the render.py model fixes (2026-10-02)

The parser and graph model were fixed and enriched (render.py "THE MODEL"): continuation
subjects, generics, `branch` arms, `/` alternatives, zoom nesting, alias nodes, op-call
targets, plus new model fields `Graph.blocks`, `joins`, `access`, `sections`,
`Node.mods` / `Edge.mods`. The **Model** column says what the model now carries for each
row: **FIXED** — the parse was wrong or lossy and is now right (the Graph/Tree cells
were re-graded from `view.py --once` runs; view.py itself is unchanged); **KEPT** — the
construct was dropped by the parser and is now in the model, but the views do not draw
it yet (their Graph/Tree grade is unchanged). Mermaid also draws `branch` arms
(`{Request} -. "read" .-> [Reader]`), op-call labels and alias nodes (`[[walk]]`).
No row is WRONG any more.

## Status after the view.py drawing pass (2026-10-02)

view.py now draws what the model carries (each in the graph view and the tree +
wires view, re-graded below from `view.py --once` runs with `--color never`):

- **Control blocks** (`Graph.blocks`): graph — a titled light-dashed frame per block
  (`╭╌ ↺ loop @while |Q|.nonempty ╌╮`, `∥ parallel @all`, `□ checkout`,
  `□ [Handler] @owns |Conn|`) holding the block's flows, nested blocks nested; a branch
  holds a `╱ ◇ {Request}.kind ╲` decision node with dotted arm edges through arm chips
  (`┆ read ┆`); a `!>` after `}` leaves the block's subject inside the frame. A block's
  flows leave the main layout (a node used inside and outside a block is drawn in
  both). Tree — a bracket per block in a gutter left of the outline: a header row
  (`┌─ ↺ loop @while |Q|.nonempty`) before the first member the block introduces,
  `├─` taps into each member row, `‹read›` beside each branch arm's entry.
- **Joins** (`Graph.joins`): graph — a join bar where the joined edges fork or meet,
  `━┯┷┯━ &`, `&?`, `/` (heavy `┳┻╋` for `=>`); tree — the taps read `◀&`, `◀&?`, `◀/`
  (`─&` on a fan-in's sources). A `*>` target list is not drawn as a join.
- **Permission graph** (`a` key, `--access`): dotted edges principal → store headed
  `r` / `w` / `b`, stores badged `1w` / `Nw` writers; tree lanes marked `r` / `w` / `b`.
- **Arrow kinds without colour**: `!>` heads `✖`; triggers stroke `╍╏` (not `~>`'s
  `╌╎`); two kinds on one pair are two strokes; a `<->` lane reads `◀──▶`.
- **Modifiers** (`m` key, `--mods`): `┆ payload ┆ @timeout 30s ×3 ┆` chips on edges (a
  modifier-only chip `┆ ×4 ┆`), `[Api] @sla p99<100ms` after node labels; relocated
  with the payloads when the drawing must fit. `@read` / `@write` / `@borrow` / `@owns`
  are left to the access edges and frames.
- **Sections and mode**: graph — one part per `--- section ---` under a divider rule
  (`── L2 · [Core] ────`), expansions titled with their zoom level; tree — a divider
  row before each section's first unit; `#!sketch` in the status bar / `--once` summary.
- **Aliases**: `[[walk]]`, in their own theme colour (`kinds.alias`).
- **Mermaid**: node ids are unique per expansion path (`Core_service__Handler_service`).

Still open after that pass: self-loop payloads and op-call targets (rows 31, 48),
stream / role shapes (11, 83), `@borrow(read)`'s narrowing (28), block-comment anchoring
(85), external-op chips (47).

## Status after the scene-sim campaign (2026-10-02)

Both views now draw from one shared model (`scene.py`: wires, colours, notes, joins,
triggers), so a construct reads the same in the graph and the tree. Re-graded from
`view.py --once --color never` runs (with `--payloads --mods` for the chip rows):

- **Colour policy** (one rule for both views): a wire takes its arrow's colour when it
  has one (`!>`, `?>`, `~>`, triggers, access, emits), else its source's kind colour —
  graph default edges are no longer grey. Mono grades are unchanged by this.
- **Events toggle** (`v`, `--events land|nodes`): a pass-through event drawn where it
  lands (the tree's default) or as a node (the graph's default), in either view.
- **Executions** (rows 31, 41, 47, 48, 49, 67, 68): a self-call keeps its op on a stub
  chip under its box (graph) / on its row (tree), `↺ run()`; recursion reads `↻`
  (`[Tree.walk] ↻`, `┆ ↻ child ┆`); a call's return reads `↩` (`┆ charge(amount) ↩
  {Receipt} ┆`); a host-provided op reads `┆ ⇱ http.get(${url}) ┆` and badges its
  target `(Web) ⇱`; two flows into one target keep a chip each. Legend: `↺ self-call
  ↻ recursion ⇱ host-provided (opaque) ↩ returns`.
- **Simulation** (`x`, `--sim`): not a drawing grade — see "Simulation over this
  fixture" below.

Still open after the scene-sim campaign: stream / role shapes (11, 83), `@borrow(read)`'s
narrowing (28), block-comment anchoring (85), which of two chips on one tree row is the
error path without colour (49), the block-string's content (45), expansion vs contains in
the tree (51), the `\-_` group (76), path chips in the graph (81).

## Status after the viewer coverage gaps pass (2026-10-07)

Rows 11 28 45 49 51 76 81 83 85 are now drawn in both views (row 76's graph half stays
LOST by design, as row 69): a stream's shadowed box / tree ` ≋`, a role's stacked box and
`‹N›`, `ƀ` for `@borrow(read)`, a block-string's first line with its full text as a note,
`✖` leading an error path's tree chip, dotted `├┄┄` rails for `:=` internals, a `⎫ ⎭`
brace over one-of siblings, `[A]/` beside a qualified path's head, and a block comment
tagging its frame / header row (a detached document header listed as `¶`). The graph
legend lists the stream / role boxes; the tree legend each new mark when it is drawn.

Still open: the tree's hole rows (6), the graph's `×N` (79, composition is tree-only),
inline trailing comments (86). A mutable stream `~*` keeps `~`'s heavy box in the graph
(no glyph set is both heavy and shadowed); its label's `~*` and the tree's ` ≋` still
say stream.

## Construct table

| # | Construct | Example line | Graph | Tree | What the reader sees (quoted) | Idea for drawing it | Model (render.py) |
|---|---|---|---|---|---|---|---|
| 1 | component `[X]` | `[Api]` | DRAWN | DRAWN | `│ [Api] │` box; tree row `[Api]` | — | — |
| 2 | data `{X}` | `{User}` | DRAWN | DRAWN | `│ {User} │` (violet). Mono: same `┌┐` box as `[X]`, only the brackets tell them apart | — (the label brackets are enough) | — |
| 3 | event `<X>` | `<OrderPlaced>` | DRAWN | DRAWN | `│ <OrderPlaced> │` (pink) | — | — |
| 4 | actor `(X)` | `(Customer)` | DRAWN | DRAWN | round `╭──╮ (Customer)` | — | — |
| 5 | store `\|X\|` | `\|UserDB\|` | DRAWN | DRAWN | `│ \|UserDB\| │` (amber) | — | — |
| 6 | holes `?` | `[?] {?} <?> \|?\| (?)`, `[Ghost] -> [?]` | DRAWN | WEAK | graph: dashed `┆ [?] ┆`, each a distinct box (6 holes, 6 boxes). Tree: plain `[?]` text rows (grey only in colour) | tree: a dashed/dim marker on the row, e.g. `┄[?]┄` or `[?]⁇` | — |
| 7 | wildcard `_` (state source) | `_ -<cancel>-> Cancelled` | DRAWN | DRAWN | `╭───────╮ ∗ any`; tree `├─· ∗ any ───●` | — | — |
| 8 | wildcard `_` (branch arm) | `_ => <Rejected>` | DRAWN | DRAWN | graph: an arm chip `┆ _ ┆` on the `◇ {Request}.kind` → `<Rejected>` arm; tree: `<Rejected> ‹_›` on its row inside the branch bracket | done (view.py) | FIXED: arm `_` in `Block.arms` / `arm_nodes`; no phantom edge |
| 9 | generics `<…>` | `[Cache<K,V>]`, `{List<T>}`, `<Msg<T>>` | DRAWN | DRAWN | phantom **event** boxes `│ <K,V> │` and `│ <T> │`; `[Cache]`, `{List}`, `<Msg>` never appear; `[Api] <-> [Cache<K,V>]` draws as `[Api] ↔ <K,V>`. Lint says OK | parse `<…>` as part of the glyph; draw `[Cache‹K,V›]` in the owner's box shape | FIXED: one glyph, name `Cache<K,V>`, `params` ("K","V"), `base_name`; Mermaid escapes `<>` |
| 10 | mutability `~` | `~{Session}`, `~\|Counter\|` | DRAWN | DRAWN | heavy border `┏━━━━━━━━━━━━┓ ~\|Counter\|`; tree keeps `~` in the label | — | — |
| 11 | stream prefix `*` | `*<Raw>`, `*{Rows}`, `*\|AuditLog\|` | DRAWN | DRAWN | graph: a shadowed box — light top/left, heavy right side and bottom (`┌────────┒ │ *<Raw> ┃ ┕━━━━━━━━┛`), apart from `~`'s all-heavy `┏━┓` (a mutable stream `~*` keeps the heavy box, its label says `~*`); graph legend `┒┃┛ stream`; tree: ` ≋` after the label, also where the event lands (`[Parse] *<Raw> ≋`), `≋ stream` in the legend when drawn | done (view.py) | — |
| 12 | stream bound `^N@policy` | `*<Raw>^10k@drop`, `*<Enriched>^5@latest`, `*{Rows}^100@err` | DRAWN | DRAWN | with `m`: `*<Raw> ^10k drop`, `*<Parsed> ^10k`, `*<Enriched> ^5 latest`, `*{Rows} ^100 err` after the label (both views); nothing without `m` | done (view.py) | KEPT: node mod ("^", "10k@drop") |
| 13 | `->` | `(Customer) -> [Api]` | DRAWN | DRAWN | light `│─`; tree `●─ … ◀` | — | — |
| 14 | `→` | `[Api] → [Auth]` | DRAWN | DRAWN | same as `->` | — | — |
| 15 | `~>` | `[Api] ~> <OrderPlaced>` | DRAWN | DRAWN | dashed `╎╌`; tree `○╌` | — | — |
| 16 | `<->` | `[Handler] <-> \|Cache\|` | DRAWN | DRAWN | graph: heads both ends (`▲` under `[Handler]`, `▼` over `\|Cache\|`). Tree: the lane starts in `▶` and the row also gets `◀`: `[Handler] ◀──▶`; legend `◀─▶ both ways` | done (view.py) | — |
| 17 | `=>` | `[Ingest] => *<Raw>` | DRAWN | DRAWN | heavy `┃━`; tree `◆━` | — | — |
| 18 | `!>` | `[Auth] … !> <Unauthorized>` | DRAWN | DRAWN | graph: the head is `✖` (mono-safe), e.g. `[Auth] … ✖ <Unauthorized>`, `*<Enriched> … ✖ \|DLQ\|`; tree `✖` source marker | done (view.py) | — |
| 19 | `?>` | `[Api] ?> [Fraud]` | DRAWN | DRAWN | alone: dotted `┄`. A `?>` and a `->` on one pair are two strokes now (the second offset onto its own ports and track: `┆│` / two heads); in this fixture the `->` is inside the `parallel` frame, the `?>` in the Shop flows. Tree: `◇┄` lane | done (view.py) | — |
| 20 | `*>` | `<OrderPlaced> *> [Shipping] & [Email] & \|Ledger\|` | DRAWN | DRAWN | double `╔═══╩═══╦═══╗`; tree `✱═` (Mermaid flattens it to `-->`) | — | — |
| 21 | continuation lines | `[Auth] -> \|UserDB\|` / `=> ~{Session}?` / `!> <Unauthorized>` | DRAWN | DRAWN | subject becomes the previous **target**: `\|UserDB\| ━━▶ ~{Session}` and `~{Session} ──▶ <Unauthorized>` (tree `~{Session} ◀━━…┳───✖`). Same in the stream block: `\|RealtimeIdx\| ✖ → \|DLQ\|` instead of `*<Enriched> !> \|DLQ\|`. Contradicts pitfall #9 | parser: continuation inherits the previous line's *subject*; then draw normally | FIXED: continuation takes the subject (`[Auth] => ~{Session}`, `*<Enriched> !> \|DLQ\|`) |
| 22 | strict join `&` | `[Api] -> [Stock] & [Tax]` | DRAWN | DRAWN | graph: a join bar under `[Api]`: `━┯┷┯━ &` forking into `[Stock]` and `[Tax]`; tree: the taps read `[Stock] ◀&`, `[Tax] ◀&─`. (`*> … & …` is a broadcast list, not drawn as a join) | done (view.py) | KEPT: `Graph.joins` (`&`), `Edge.dst_join` |
| 23 | race `&?` | `[Api] -> [PspA] &? [PspB]` | DRAWN | DRAWN | graph `━┯┷┯━ &?`; tree `[PspA] ◀&?`, `[PspB] ◀&?` | done (view.py) | KEPT: `Graph.joins` (`&?`) |
| 24 | `@sla` | `[Api] @sla(p99<100ms, avail>99.95%)` | DRAWN | DRAWN | with `m`: `[Api] @sla p99<100ms, avail>…` in the box / on the row (long arguments cut at 18 chars) | done (view.py) | KEPT: node mod ("sla", …) |
| 25 | `@inv` | `[Payment] @inv idempotent(…)`, `{User}.age @inv >= 0` | DRAWN | DRAWN | with `m`: `[Payment] @inv idempotent(transa…`, `{User} .age @inv >= 0` | done (view.py) | KEPT: node mods (".", "age"), ("inv", ">= 0") |
| 26 | `@cap` | `[Auth] -> \|UserDB\| @cap(read)` | DRAWN | DRAWN | with `m`: a chip `┆ @cap read ┆` on the `[Auth] → \|UserDB\|` edge (graph), after the payload in the right margin (tree) | done (view.py) | KEPT: edge mod ("cap", "read") |
| 27 | `@owns X { … }` | `[Handler] @owns \|Conn\| { … }` | DRAWN | DRAWN | graph: a frame `╭╌ □ [Handler] @owns \|Conn\| ╌╮` around `[Handler] → \|Conn\|`; tree: a bracket `┌─ □ [Handler] @owns \|Conn\|` over the two rows | done (view.py) | KEPT: `Block(kind="owns")`, node mod ("owns", "\|Conn\|") |
| 28 | `@borrow` / `@borrow(read)` | `[Helper] @borrow \|Directives\|` | DRAWN | DRAWN | with `a`: dotted access edges into `\|Directives\|` headed `b` and into `\|Results\|` headed `ƀ` — the `(read)` narrowing (graph); `[Helper] ┄┄ƀ┄b` lanes (tree). `@borrow(write)` keeps `b`. Both legends list `ƀ` borrow(read) (the tree's only when drawn) | done (view.py) | KEPT: `Graph.access` mode "borrow", `narrow` |
| 29 | `@timeout` (flow) | `… : score({Cart}) @timeout(30s) ×3 @fallback(0)` | DRAWN | DRAWN | with `m`: `┆ score({Cart}) ┆ @timeout 30s ×3 @fallback 0 ┆` (payload, then the modifiers) | done (view.py) | KEPT: edge mods timeout / × / fallback |
| 30 | `@after` | `[Retry] @after(exp-backoff, cap=1min)` | DRAWN | DRAWN | with `m`: `[Retry] @after exp-backoff, cap=…`, `[[retry]] @after …` | done (view.py) | KEPT: node mod ("after", …) |
| 31 | `@deadline` | `[Worker] -> run() @deadline(2s)` | DRAWN | DRAWN | graph: `[Worker] ↺` with a stub under the box, `└─● ┆ ↺ run() ┆ @deadline 2s ┆` (`p`, `m`); tree: `[Worker] ↺` and the chip `┆ ↺ run() ┆ @deadline 2s ┆` on its row | done (scene + views) | FIXED: the flow is a self-edge, `target_op` "run()", edge mod ("deadline", "2s") |
| 32 | `@fallback` | `… op http.get(${url}) @timeout(5s) @fallback(${cache})` | DRAWN | DRAWN | with `m`: `┆ op http.get(${url}) ┆ @timeout 5s @fallback ${cache} ┆` | done (view.py) | KEPT: edge mod ("fallback", "${cache}") |
| 33 | `@grants` / `@requires` | `[AuthSvc] @grants(session)`, `\|PaymentDB\| @requires(write, pci)` | DRAWN | DRAWN | with `m`: `[AuthSvc] @grants session`, `\|PaymentDB\| @requires write, pci` | done (view.py) | KEPT: node mods grants / requires |
| 34 | `@loc` | `[Gateway] @loc(us-east)`, `[Cache<K,V>] @loc(eu-west)` | DRAWN | DRAWN | with `m`: `[Gateway] @loc us-east`, `[Cache<K,V>] @loc eu-west` | done (view.py) | KEPT: node mod ("loc", …) |
| 35 | `!` critical | `(Customer) -> [Api] : {Cart} !` | DRAWN | DRAWN | with `m`: `┆ {Cart} ┆ ! ┆` — the `!` after the payload, `┆`-separated, never inside it | done (view.py) | KEPT: edge mod ("!", None); no longer glued into the payload text |
| 36 | `?` optional | `=> ~{Session}?` | DRAWN | DRAWN | with `m`: a modifier chip `┆ ? ┆` on `[Auth] ⇒ ~{Session}` | done (view.py) | KEPT: edge mod ("?", None) |
| 37 | `.field` | `{User}.age`, `\|Q\|.nonempty`, `{Job}.state = done` | DRAWN | DRAWN | block frame titles / bracket headers carry them (`↺ loop @while \|Q\|.nonempty`, `@until {Job}.state = done`, `◇ branch on {Request}.kind`); with `m`, `{User} .age @inv >= 0` | done (view.py) | KEPT: (".", field) mod; `{Job}` is a node (loop header ref) |
| 38 | `×N` / `xN` on a flow | `[Api] -> [Shard] ×4`, `[Api] -> [Replica] x2`, `[Router] -> [Handler]×N` | DRAWN | DRAWN | with `m`: chips `┆ ×4 ┆`, `┆ ×2 ┆`, `┆ ×N ┆` (`[Router] → [Handler]`) | done (view.py) | KEPT: edge mods ("×", "4") / ("×", "2") / ("×", "N") |
| 39 | `×N` / mods on a transition | `_ -<cancel>-> Cancelled ×3`, `Open -<Paid>-> Settled @timeout(1d)` | DRAWN | DRAWN | with `m`: modifier chips `┆ ×3 ┆`, `┆ @timeout 1d ┆` (the payload copy of the same text is dropped when `m` is on); with only `p`, payload chips as before | done (view.py) | KEPT: transition `Edge.mods` |
| 40 | payload: entity glyph | `: {creds}` | DRAWN | DRAWN | with `p`: `┆ {creds} ┆` chip on the edge / `┄┆ {creds} ┆` on the target row | — | — |
| 41 | payload: internal op-call | `: charge(amount) => {Receipt}` | DRAWN | DRAWN | `┆ charge(amount) ↩ {Receipt} ┆` — the return after `↩` | — | — |
| 42 | payload: value literals | `: false`, `: "ack"`, `: 0.5`, `: null` | DRAWN | DRAWN | `┆ false ┆`, `┆ "ack" ┆`, `┆ 0.5 ┆`, `┆ null ┆` | — | — |
| 43 | payload: `${ref}` | `: ${state.count} + 1` | DRAWN | DRAWN | raw text in the chip | optional: tint `${…}` in the chip | — |
| 44 | payload: map / list | `: {retries: 3, mode: "x"}`, `: [1, 2, 3]` | DRAWN | DRAWN | `┆ {retries: 3, mode: "x"} ┆`, `┆ [1, 2, 3] ┆` (not mistaken for a `{X}` node) | — | — |
| 45 | payload: `"""…"""` block string | `[Grader] -> ~\|Sys\| : """ … """` | DRAWN | DRAWN | the chip shows its first line, cut at a word, and `…`: `┆ """You are a strict rubric…""" ┆`; the full text is an inline note on the flow (`#8` with `n`, one notes-list row per text line; a callout box in callouts mode). No phantom nodes | done (view.py) | KEPT: `Edge.block_string` |
| 46 | payload: value operators | `${state.history} ++ [${out}]`, `${a} \|\| {b: 1}`, `${n} * 2 - ${m} / 4` | DRAWN | DRAWN | raw text in chips | — | — |
| 47 | payload: external `op ns.verb` | `: op http.get(${url})` | DRAWN | DRAWN | `┆ ⇱ http.get(${url}) ┆` (no `op ` keyword) and the target badged `(Web) ⇱`; legend `⇱ host-provided (opaque)` | done (scene + views) | — |
| 48 | payload on a self-loop | `[Tree.walk] -> [Tree.walk] : child` | DRAWN | DRAWN | graph: `[Tree.walk] ↻` with a stub chip `└─● ┆ ↻ child ┆` (`p`); tree: `[Tree.walk] ↻ ┄┄┄ ┆ ↻ child ┆` on its own row (no longer only in a footer) | done (scene + views) | — |
| 49 | payloads of several edges to one target | `reserve => {Hold}` + `!> … : release({Hold})` | DRAWN | DRAWN | a chip per flow: `┆ reserve => {Hold} ┆   ┆ release({Hold}) ┆`. Graph: each on its own edge (the `release` one on the `✖` edge). Tree: both on the `[Inventory]` row, the error path's chip led by `✖` (`┆ ✖ release({Hold}) ┆`), so it reads without colour | done (view.py) | — |
| 50 | alias `name := expr` | `retry := @after(…)`, `walk := [Node] -> walk(.children)` | DRAWN | DRAWN | alias nodes in their own brackets and colour: `[[retry]]`, `[[walk]] ▾` with its `[[walk]] := { … }` section (`[Node] ↺`) | done (view.py) | FIXED: `retry`, `walk` are `alias` nodes (mods / expansion = the definition) |
| 51 | expansion `X := { … }` | `[Core] := { [Router] -> [Handler]×N … }` | DRAWN | DRAWN | graph: `── [Core] := { … } ──` section, `[Core] ▾` / `▸` at depth 0. Tree: the members hang off dotted rails (`├┄┄ [Router]`, `┆` down to the next member, also through a block bracket), apart from the `\->` contains relation's solid `├──`; `┄ := internals` in the legend when drawn | done (view.py) | — |
| 52 | expansion holding only aliases | `[Handler] := { ingress := {Req} => {Ctx} … }` | DRAWN | DRAWN | graph: a header `── [Handler] := { … } ──` with **nothing under it**, and `[Handler] ▾` promises content. Tree: nothing. (Mermaid: an empty `subgraph Handler_service` that collides with the `Handler_service` node inside `Core`) | render aliases (#50) inside the section; else drop the `▾` | FIXED: the section holds the alias nodes `ingress` / `process` / `egress`, each expandable |
| 53 | named declaration | `[Boss]`, `(Auditor)` | DRAWN | DRAWN | orphan strip at the bottom: `│ [Boss] │ │ <N> │ ╭ (Auditor) ╮` | — | — |
| 54 | topic section `--- Name ---` | `--- Control ---`, `--- Composition ---` | DRAWN | DRAWN | graph: a divider `── Control ─────` over the part holding that section's flows, nodes and block frames; tree: `── Control ──` before its first unit | done (view.py) | KEPT: `Graph.sections` (level None) |
| 55 | layer section `--- Lk: Name ---` / zoom | `--- L2: [Core] ---`, `--- L3: [Handler] ---` | DRAWN | DRAWN | graph: `── L1 · Shop ──`, `── L2 · [Core] ──` dividers; expansions titled with their zoom level, `L2 · [Core] := { … }  ›  L3 · [Handler] := { … }`. Tree: `── L2 · [Core] ──` before `(Client)`; L3 nests under `[Core]`'s `[Handler]` | done (view.py) | FIXED: `--- L3 ---` nests under `[Core]`'s `[Handler]`; `--depth all` ≠ depth 1; `Graph.sections` |
| 56 | alternative `a / b` | `[Api] => {Resp} / {Err}` | DRAWN | DRAWN | graph: a heavy join bar `━┳┻┳━ /` forking `[Api] ⇒` into `{Resp}` and `{Err}`; tree `{Resp} ◀/`, `{Err} ◀/` | done (view.py) | FIXED: both `=>` edges; one `/` Join (`dst_join`) |
| 57 | scoped block `name { … }` | `checkout { [Cart] -> [Api] }` | DRAWN | DRAWN | graph: frame `╭╌ □ checkout ╌╮` around `[Cart] → [Api]`; tree bracket `┌─ □ checkout` | done (view.py) | KEPT: `Block(kind="scope", header="checkout")` |
| 58 | mode line | `#!sketch` | DRAWN | DRAWN | `#!sketch` in the live status bar (gold) and at the end of the `--once` summary (`… 7 expansions · #!sketch`) | done (view.py) | — |
| 59 | `state` owners, every glyph | `state {Order}`, `state [Checkout]`, `state \|Queue\|`, `state <Signal>`, `state (Courier)` | DRAWN | DRAWN | owner gets `▾`, section `── {Order} state machine ──`; tree nests `├─· Open <Placed>` under each owner | — | — |
| 60 | pseudo-states `+ $ _` | `+ -<Placed>-> Open`, `Settled -<ship>-> $` | DRAWN | DRAWN | `● `, `◉`, `∗ any` circles | — | — |
| 61 | event triggers | `[Payments] ~> <Paid>` + `Open -<Paid>-> Settled` | DRAWN | DRAWN | graph: trigger edges are heavy-dashed `╏╍` (never the `╎╌` of `~>`); a `── triggers ──` list. Tree: `◎╍` lanes; `--no-triggers` removes all `◎` | done (view.py) | — |
| 62 | trigger narrowing | `<Paid> -> {Order}` (Checkout's `Busy -<Paid>-> Idle` not driven) | DRAWN | DRAWN | triggers list has no `<Paid> ⇢ [Checkout]`; tree `Idle <Paid>` row has no `◎` lane | — | — |
| 63 | `loop @each/@while/@until/@times` | `loop @while \|Q\|.nonempty { … }` | DRAWN | DRAWN | graph: a frame per loop, `╭╌ ↺ loop @while \|Q\|.nonempty ╌╮` around `[Worker] ╌▶ <metric> → \|Obs\|`; tree: `┌─ ↺ loop @while …` bracket over its member rows (`├─`, `└─`). `{Items}` / `{Job}` / `\|Q\|` are named in the titles | done (view.py) | KEPT: `Block(kind="loop")` header/modifiers/members; `{Items}`, `{Job}` are nodes (`refs`) |
| 64 | `parallel @all/@any/@none` | `parallel @all { [Api] -> [Inventory] … }` | DRAWN | DRAWN | graph frames `∥ parallel @all` / `@any` / `@none`; tree brackets `├─ ∥ parallel @all` … | done (view.py) | KEPT: `Block(kind="parallel")`, modifiers [("all", None)] |
| 65 | `!>` after a block (compensation) | `}` / `!> [Inventory] : release({Hold})` | DRAWN | DRAWN | inside the `∥ parallel @all` frame: `[Api]` → `[Inventory]` twice, `▼` (`->`) beside `✖` (the `!>` after `}`), each its own stroke; tree `[Api] ✖` lane into `[Inventory]` | done (view.py) | FIXED: `[Api] !> [Inventory]` from the block's subject; `Block.after` |
| 66 | `branch on X { arm => … }` | `read => [Reader] -> \|DB\|` … `_ => <Rejected>` | DRAWN | DRAWN | graph: a frame `◇ branch on {Request}.kind` holding a decision node `╱──╲ │ ◇ {Request}.kind │ ╲──╱` with dotted arm edges through arm chips `┆ read ┆`, `┆ write ┆`, `┆ admin ┆`, `┆ _ ┆` to each arm's entry; tree: bracket `┌─ ◇ branch on {Request}.kind`, `[Reader] ‹read›`, `[Writer] ‹write›`, `[AdminSvc] ‹admin›`, `<Rejected> ‹_›` | done (view.py) | FIXED: `Block(kind="branch")` arms + `refs` [`{Request}`]; no phantom chain; Mermaid draws `{Request} -. read .-> [Reader]` |
| 67 | recursion: self-arrow | `[Tree.walk] -> [Tree.walk] : child` | DRAWN | DRAWN | `│ [Tree.walk] ↻ │` (`↻` recursion, `↺` a plain self-call) | — | — |
| 68 | recursion: self-referential alias | `walk := [Node] -> walk(.children)` | DRAWN | DRAWN | `[[walk]] ▾` and its section `[[walk]] := { … }` drawing `[Node] ↻` with `┆ ↻ walk(.children) ┆` (tree: `[[walk]]` / `└── [Node] ↻`) | done (view.py) | FIXED: `walk` alias node, expansion `[Node] -> [Node]` (`target_op` "walk(.children)") |
| 69 | `\->` contains | `\-> [Hull]` | LOST | DRAWN | graph (by design, flows only): `[Ship]`, `[Hull]` … sit in the orphan strip as if unconnected. Tree: `├── [Hull]` | graph: optional faint nesting (`d`-style toggle) or `⊂Ship` tag on child boxes | — |
| 70 | `\-&` has | `\-& {Transform}` | LOST | DRAWN | tree `├─& {Transform}` | — (graph as #69) | — |
| 71 | `\-?` when + `{cond}-` | `\-{shattered}-? [Shard]` | LOST | DRAWN | tree `├─{shattered}? [Shard]` | — | — |
| 72 | `\-$` from data | `\-{rows}-$ [Row]` | LOST | DRAWN | tree `├─{rows}$ [Row]` | — | — |
| 73 | `\-@` attached | `\-@ [Tracer]` | LOST | DRAWN | tree `├─@ [Tracer]` | — | — |
| 74 | `\-!` alerts | `\-{lagging}-! <LagAlarm>` | LOST | DRAWN | tree `├─{lagging}! <LagAlarm>` | — | — |
| 75 | `\-=` gathers + `*-` | `\-*-= [ShardQuery]` | LOST | DRAWN | tree `├─*= [ShardQuery]` | — | — |
| 76 | `\-_` one of | `\-_ [PrimaryPsp]`, `\-_ [StandbyPsp]` | LOST | DRAWN | graph (by design, flows only, as row 69): orphan boxes. Tree: `├─_ [PrimaryPsp] ⎫` / `├─_ [StandbyPsp] ⎭` — a brace after the labels joins each run of two or more `_` siblings (`⎪` over rows between them, a sibling's own subtree), lanes start after it; `_⎫ one of` in the legend when drawn | done (view.py) | — |
| 77 | `*-` spawn / bare `\-*` | `\-*-> [Bullet] ×N`, `\-* [Drone]` | LOST | DRAWN | tree `├─* [Bullet]`, `└─* [Drone]` | — | — |
| 78 | `(N)-` weight | `\-(3)-> [ZoneA]`, `\-(1)-> [ZoneB]` | LOST | DRAWN | tree `├─(3)─ [ZoneA]`, `└─(1)─ [ZoneB]` | maybe a share bar `███░` | — |
| 79 | child count `×N` | `\-*-> [Bullet] ×N` | WEAK | DRAWN | with `m`: tree `├─* [Bullet] ×N`; graph: the `[Bullet] ×N` box (composition itself is not in the graph) | done (view.py) | KEPT: node mod ("×", "N") on `[Bullet]` |
| 80 | inline branch | `[Log] \-& {Scrollable}` | LOST | DRAWN | tree `[Log]` / `└─& {Scrollable}` | — | — |
| 81 | qualified path `[A]/{B}` | `[Homing] -> [Bullet]/{Transform}` | DRAWN | DRAWN | graph: still one `{Transform}` box, but Homing's edge carries the path's prefix beside its head (`▼ [Bullet]/`, `[Ship]/[Bullet]/` for a deeper path; a name with no box of its own shows bare, `Ship/`), Physics' edge none; legend `▼ [A]/ in path`. Tree: `[Physics]` taps both `{Transform}` rows, `[Homing]` only `│  ├─& {Transform} ◀──┼─┐` under `[Bullet]` | done (view.py) | — |
| 82 | permission `@read(…)` / `@write(…)` | `*\|AuditLog\| @read(Auditor) @write(Api, Worker)`, `\|Directives\| @read(Worker) @write(Boss)` | DRAWN | DRAWN | with `a`: dotted access edges principal → store headed `r` / `w` (graph), lanes whose source is marked `r` / `w` (tree); stores badged `\|Directives\| 1w`, `*\|AuditLog\| 2w` (one writer owns it vs shared) | done (view.py) | KEPT: `Graph.access` read/write, principals resolved to node ids |
| 83 | generic role | `[Worker<N>]` (`@read(Worker)`) | DRAWN | DRAWN | a generic glyph an `@read`/`@write` list names is a role (Node.is_role): its generics in ‹ › (`[Worker‹N›]`, both views) and, in the graph, a stacked box with a double right side (`┌─────────────╖ │ [Worker‹N›] ║ └─────────────╜`); the tree row `[Worker‹N›]`, `[R‹N›] role: N members` in its legend (`╖║╜ role` in the graph's). `[Cache<K,V>]` (no principal) stays a plain box | done (view.py) | FIXED: `[Worker<N>]` one node; `@read(Worker)` resolves by `base_name` when no exact `[Worker]`; `Node.is_role` marks the role (also when an exact `[Worker]` takes the edge) |
| 84 | block comment above | `# order lifecycle, driven by events` / `state {Order}` | DRAWN | DRAWN | `{Order} ¶10`; callout `╭ ¶10 order lifecycle, ╮ ──── {Order} ¶10` | — | — |
| 85 | block comment above a glyph-less statement | `# route by request kind` / `branch on …`; header comment above `retry :=` | DRAWN | DRAWN | the comment tags the block, not its first arm: graph `╭╌ ◇ branch on {Request}.kind #14 ╌╮` (the `[Reader]` box untagged), tree `┌─ ◇ branch on {Request}.kind #14` (a callout's `#>` leader points at that header row); the same for `loop` / `parallel` / a scoped `name {`, and a comment trailing such a header (no body on its line) trails the header row. A header comment that comes before the first statement but is detached from it (a blank line, a section, the end) is the document's own note, listed first as `¶ …` and tagged on nothing (tree callouts list it under the drawing). The fixture's header sits directly above `retry :=`, so it stays on `[[retry]]` | done (view.py) | FIXED: `Note.block` (index into `Graph.blocks`) for a comment above a glyph-less header; `Note.node` None for a block or document note; `[H] @owns \|R\| {` keeps its owner |
| 86 | inline trailing comment | `=> ~{Session}?  # optional result`, `\-& {Transform}  # inline note on a branch` | WEAK | WEAK | `#12` correctly on the branch row; but `#4 optional result` is placed on `~{Session}` and `#3`/`#6` on the line subject — they follow the parser's subject, so a continuation's note sits on the wrong node | fixed by #21; otherwise fine | — |

### Counts

86 rows × 2 views = 172 cells. Rows drawn only under a toggle (`p`, `m`, `a`, `d`) count
as DRAWN when the toggle draws them clearly, as payload chips always have.

| | Graph | Tree | Total |
|---|---|---|---|
| DRAWN | 73 | 84 | 157 |
| WEAK | 2 | 2 | 4 |
| LOST | 11 | 0 | 11 |
| WRONG | 0 | 0 | 0 |

(Composition rows #69–80 are LOST in the graph on purpose — language.md: "The default
graph view shows the flows alone." — all 11 graph LOST.) Counted from the table after
the viewer coverage gaps pass (rows 11 28 45 49 51 76 81 83 85); before it (after the
scene-sim campaign) DRAWN 68/77, WEAK 7/9, LOST 11/0. Before the scene-sim campaign
(graph/tree): DRAWN 64/74, WEAK 10/12, LOST 12/0; before the view.py drawing pass (after
the render.py model fixes): DRAWN 31/42, WEAK 18/19, LOST 37/25; before those: DRAWN
27/38, WEAK 13/15, LOST 38/26, WRONG 8/7.

## Simulation over this fixture

`view.py tests/fixtures/coverage.sigil --once --sim NAME` (no crash in any scenario).
`happy` runs 20 episodes (one per entry, written order) to `ok` in 802 frames. 14
scenarios: `happy`, `Customer->Api:fails`, `Auth:fails`, `Api?>Fraud`, `Api&?PspB`,
`Api.score:fallback`, `Api.http.get:fallback`, `Worker.run:fails`, `Api->Shard:fails`,
`Api->Replica:fails`, `Enriched:fails`, `Api/Err`, `Api@any=MirrorB`,
`Router->Handler:fails`.

What the `happy` log shows per construct group:

- **Calls / returns / resilience:** `[Inventory] ↩ {Hold}`; `[Api] -> [Replica]
  attempt 1/3`; `[Api] <-> [Cache<K,V>]` then `[Cache<K,V>] replies`; `@owns` acquires
  and releases (`acquire |Conn|` … `release |Conn|`). The `[Core]` internals
  (`[Router] -> [Handler]` attempts 1/3 … 3/3) show up only in the
  `Router->Handler:fails` scenario.
- **Joins / races:** `parallel @any` logs `race lost: [Api] -> [MirrorB]`; the
  alternative `[Api] => {Resp} / {Err}` takes `{Resp}` (`Api/Err` the other).
- **Recursion:** `[Tree.walk] ↻ child` twice, then `base case: [Tree.walk] at depth 3`.
- **Loops:** `iteration 1/2`, `iteration 2/2` (bounded at 2 per loop).
- **Composition:** a `setup:` line counts the instances (`[Bullet] ×2`, `[Shard] ×0`).
- **State machines:** `{Order} + -<Placed>-> Open`, `[Checkout] Idle -<Placed>-> Busy`,
  `|Queue| Empty -<push>-> Full`. `<Paid>` is logged `ignored: <Paid> — {Order} in +`:
  `[Payments]` (episode 12) is an entry written before `[Checkout]` (episode 13), so
  entries run in written order and `<Paid>` arrives before `<Placed>` — the fixture's
  order, not a design statement.
- **Not reached:** the `branch on {Request}.kind` block — `{Request}` is not an entry
  and nothing flows into it, so its arms never run and it lists no `Request.kind=…`
  scenarios.

## Crashes and phantom nodes

- **No crash** in any toggle; `view.py --once` with lint also exits 0; Mermaid exits 0.
- **Phantom nodes:** `<K,V>` (from `[Cache<K,V>]`), `<T>` (from `{List<T>}` *and*
  `<Msg<T>>`), `<N>` (from `[Worker<N>]`). All are drawn as **event** boxes in both views
  and in Mermaid (`K_V_event>"K,V"]`); `¶1` attaches to `<K,V>`.
- **Phantom edges:** the continuation edges (`|UserDB| => ~{Session}`,
  `~{Session} !> <Unauthorized>`, `|RealtimeIdx| !> |DLQ|`, `[Fraud] !> [Inventory]`) and the
  `branch` chain (`[Metrics] => [Reader]`, `|DB| => [Writer]`, `|WAL| => [AdminSvc]`,
  `[AdminSvc] => <Rejected>`).
- **Vanished nodes:** `[Cache]`, `{List}`, `<Msg>`, `[Node]` (alias), `{Items}`, `{Job}`,
  `{Request}`; the `[Worker] -> run() @deadline(2s)` flow.
- **Empty section:** `── [Handler] := { … } ──` with nothing under it. Mermaid emits an empty
  `subgraph Handler_service` *and* a `Handler_service` node inside `Core`, which reuses the id.
- **Status (render.py model fixes):** all phantom nodes and phantom edges above are gone;
  every vanished node is back (`[Cache<K,V>]`, `{List<T>}`, `<Msg<T>>`, `[Worker<N>]` as one
  glyph each; `[Node]` inside the `walk` alias; `{Items}` / `{Job}` / `{Request}` as block-header
  refs; `[Worker] -> run()` as a self-edge with `target_op`). The `[Handler]` expansion now hangs
  inside `[Core]` and lists its three aliases. Mermaid ids are now unique per expansion path
  (render.py `unique_ids`): `[Core]`'s `[Handler]` is `Core_service__Handler_service`, apart
  from the top-level `Handler_service`.

## Priority: fix these first

1. **[FIXED in render.py]** **Continuation-line subject (parser, both views + Mermaid): WRONG.** `render.extract_flows`
   carries the previous line's *last target* forward. Spec pitfall #9 says the reverse, and the
   bug hits the spec's own Examples 2, 3 and 4 (`=> … !> …` under one flow, the stream DLQ, the
   `parallel` compensation). The reader is shown wrong error paths: `~{Session} ✖→ <Unauthorized>`.
   It's a small parser fix and makes every view correct at once.
2. **[FIXED in render.py; lint agrees]** **Generics make phantom event nodes: WRONG, and lint stays silent.** `[Cache<K,V>]` turns
   into an event box `<K,V>`, and the real component disappears. It also breaks the
   permission-graph generic-role idiom (`[Worker<N>]` → `<N>`). Fix `parse_glyph` to take the
   nested `<…>`; draw `[Cache‹K,V›]`, with a stacked box for roles.
3. **[FIXED — model, Mermaid and both views]** **`branch on` arms chain into phantom `=>` edges: WRONG.** Each `label =>` arm is parsed
   as a continuation, so heavy "produces" edges run from the previous statement through every
   arm. The subject and arm labels never appear. Draw a decision node (`◇ {Request}.kind`)
   with `?>`-style dotted edges and arm chips (`read`, `write`, `_`).
4. **[DONE in view.py: frames, brackets, join bars]** **Control blocks leave no trace (loop, parallel, scoped `name {}`, `@owns {}`), and
   `&`/`&?` joins are lost.** These are half the "control flow" chapter, and the drawing
   reads them as plain unconditional wiring. A titled frame in the graph and a gutter bracket
   in the tree (`┌↻ @while |Q|.nonempty`, `┌∥ @all`) are both consistent with the existing
   section/lane language. A join bar with an `&`/`&?` chip would cover inline joins. It would
   also give the block's `!>` compensation a correct source.
5. **[DONE in view.py: `a` / `--access`]** **Permission graph is LOST.** `@read`/`@write`/`@borrow` are a whole spec chapter. The
   stores and principals show up only as orphans in the bottom strip, so the reader sees
   "unconnected" where the design has a dense access graph. Add dotted access edges or lanes
   (`r`/`w` heads) under a toggle (an `a` key, like `e` for triggers), plus a single-vs-shared
   writer badge.
6. **[DONE in view.py]** **Mono-only ambiguities (graph view).** `!>` is plain `│` without colour. Trigger edges
   use the same `╎╌` as `~>`. A `?>` sharing a pair with `->` disappears in the merge. In the
   tree, `<->` is the same as `●─ call`. Each is a one-glyph fix: a `✖` source or heavy-dash
   stroke for `!>`, a `◎`/`⇢` head for triggers, separate strokes for parallel edges, and
   `◀…◀` for `<->` lanes. The tree already has most of these markers.
7. **[DONE in view.py: `m` / `--mods`]** **Modifiers are invisible (`×N`/`xN`, `@timeout`/`@fallback`, `!`, `?`, `@sla`, `@inv`,
   `@cap`, `@loc`, stream `^N@policy`).** The edge or node is still there, so they are lower
   risk, but `×N` and the resilience trio matter for reading a design. A modifier-chip toggle
   (`m`) would cover them, styled like payload chips but separate from them:
   `⏱30s ×3 ↩0`, a `×4` badge at the arrowhead, `^10k⇣drop` in a stream box. It also stops
   `!` showing up inside the payload text (`┆ {Cart} ! ┆`).
8. **[DONE: render.py model + view.py dividers, `[[alias]]`, `#!mode`]** **Structure/zoom: sections, layers, mode, aliases.** Topic and `Lk` headers vanish.
   `--depth all` equals depth 1 because L3 expansions hang on the top-level node, not the
   L2 occurrence. Alias-only expansions produce an empty `▾` section, and `a / b` drops `b`
   as an orphan. Add section bands (tree) and group labels (graph), nest `Lk` under `Lk-1`,
   render alias bodies, and show `#!mode` in the footer.
