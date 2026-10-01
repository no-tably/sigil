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
The default graph is **392 columns wide** for this document.

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
| 8 | wildcard `_` (branch arm) | `_ => <Rejected>` | LOST | LOST | arm label gone; becomes `[AdminSvc] ⇒ <Rejected>` (see #61) | default-arm chip `_` on a branch edge | FIXED: arm `_` in `Block.arms` / `arm_nodes`; no phantom edge |
| 9 | generics `<…>` | `[Cache<K,V>]`, `{List<T>}`, `<Msg<T>>` | DRAWN | DRAWN | phantom **event** boxes `│ <K,V> │` and `│ <T> │`; `[Cache]`, `{List}`, `<Msg>` never appear; `[Api] <-> [Cache<K,V>]` draws as `[Api] ↔ <K,V>`. Lint says OK | parse `<…>` as part of the glyph; draw `[Cache‹K,V›]` in the owner's box shape | FIXED: one glyph, name `Cache<K,V>`, `params` ("K","V"), `base_name`; Mermaid escapes `<>` |
| 10 | mutability `~` | `~{Session}`, `~\|Counter\|` | DRAWN | DRAWN | heavy border `┏━━━━━━━━━━━━┓ ~\|Counter\|`; tree keeps `~` in the label | — | — |
| 11 | stream prefix `*` | `*<Raw>`, `*{Rows}`, `*\|AuditLog\|` | WEAK | WEAK | only the text prefix: `│ *<Raw> │`, `│ *\|AuditLog\| │`; no shape cue, unlike `~` | stacked/shadowed box (`┌─┐┐`) for streams, as `~` gets heavy borders | — |
| 12 | stream bound `^N@policy` | `*<Raw>^10k@drop`, `*<Enriched>^5@latest`, `*{Rows}^100@err` | LOST | LOST | `*<Raw>` — the `^10k@drop` is stripped in the parser (node name `Raw`, no attr) | suffix badge in the box: `*<Raw> ^10k⇣drop`; chip on the producing `=>` edge | KEPT: node mod ("^", "10k@drop") |
| 13 | `->` | `(Customer) -> [Api]` | DRAWN | DRAWN | light `│─`; tree `●─ … ◀` | — | — |
| 14 | `→` | `[Api] → [Auth]` | DRAWN | DRAWN | same as `->` | — | — |
| 15 | `~>` | `[Api] ~> <OrderPlaced>` | DRAWN | DRAWN | dashed `╎╌`; tree `○╌` | — | — |
| 16 | `<->` | `[Handler] <-> \|Cache\|` | DRAWN | WEAK | graph: heads both ends (`▲` under `[Handler]`, `▼` over `\|Cache\|`). Tree: `├── [Handler] … ●─┴` / `├── \|Cache\| ◀───┘` — legend says `●─ both ways`, identical to `●─ call` | tree: `◀` on both rows (or `◆◀`/`▶◀`), distinct legend glyph like `◀─▶` | — |
| 17 | `=>` | `[Ingest] => *<Raw>` | DRAWN | DRAWN | heavy `┃━`; tree `◆━` | — | — |
| 18 | `!>` | `[Auth] … !> <Unauthorized>` | WEAK | DRAWN | graph: red only — mono probe `[A] !> [D]` draws a plain `│` into `[D]`, identical to `->`. Tree: `✖` source marker (but on the wrong subject, #20) | a stroke that survives mono: `┅`/`╳` head or a `✖` at the source, matching the tree | — |
| 19 | `?>` | `[Api] ?> [Fraud]` | WEAK | DRAWN | alone: dotted `┄`. Here `[Api] -> [Fraud]` (in `parallel`) also exists and the pair collapses to **one solid edge** — the `?>` vanishes in the default view (probe `[A] ?> [B]` + `[A] -> [B]` draws one `└─┐ ▼`). Tree: `◇┄` lane | draw parallel edges between one pair as separate strokes, or a `?` chip on the merged one | — |
| 20 | `*>` | `<OrderPlaced> *> [Shipping] & [Email] & \|Ledger\|` | DRAWN | DRAWN | double `╔═══╩═══╦═══╗`; tree `✱═` (Mermaid flattens it to `-->`) | — | — |
| 21 | continuation lines | `[Auth] -> \|UserDB\|` / `=> ~{Session}?` / `!> <Unauthorized>` | DRAWN | DRAWN | subject becomes the previous **target**: `\|UserDB\| ━━▶ ~{Session}` and `~{Session} ──▶ <Unauthorized>` (tree `~{Session} ◀━━…┳───✖`). Same in the stream block: `\|RealtimeIdx\| ✖ → \|DLQ\|` instead of `*<Enriched> !> \|DLQ\|`. Contradicts pitfall #9 | parser: continuation inherits the previous line's *subject*; then draw normally | FIXED: continuation takes the subject (`[Auth] => ~{Session}`, `*<Enriched> !> \|DLQ\|`) |
| 22 | strict join `&` | `[Api] -> [Stock] & [Tax]` | LOST | LOST | two ordinary edges / lanes — identical to two separate lines | a join bar at the fan point: `┬` with a small `&` chip (graph); a `&` tag on the shared lane (tree) | KEPT: `Graph.joins` (`&`), `Edge.dst_join` |
| 23 | race `&?` | `[Api] -> [PspA] &? [PspB]` | LOST | LOST | two ordinary edges `[PspA]`, `[PspB]` | same bar with an `&?` chip (or `⚡`) — must differ from `&` | KEPT: `Graph.joins` (`&?`) |
| 24 | `@sla` | `[Api] @sla(p99<100ms, avail>99.95%)` | LOST | LOST | `│ [Api] │` only | node badge / ¶-style note `⏱ p99<100ms` (a modifiers toggle `m`) | KEPT: node mod ("sla", …) |
| 25 | `@inv` | `[Payment] @inv idempotent(…)`, `{User}.age @inv >= 0` | LOST | LOST | `{User}` lands in the orphan strip with nothing else | `⊨` badge on the node, text in the notes list | KEPT: node mods (".", "age"), ("inv", ">= 0") |
| 26 | `@cap` | `[Auth] -> \|UserDB\| @cap(read)` | LOST | LOST | plain edge | edge chip `🔑read` style, e.g. `╭cap:read╮` under `p`/`m` | KEPT: edge mod ("cap", "read") |
| 27 | `@owns X { … }` | `[Handler] @owns \|Conn\| { … }` | WEAK | WEAK | the inner flow `[Handler] → \|Conn\|` (payload `query => {Rows}`) is drawn; ownership/scope gone | heavy owner tick on the store (`◆\|Conn\|`) or an `owns` dotted edge like a trigger | KEPT: `Block(kind="owns")`, node mod ("owns", "\|Conn\|") |
| 28 | `@borrow` / `@borrow(read)` | `[Helper] @borrow \|Directives\|` | LOST | LOST | `[Helper]` orphan box | dotted access edge `[Helper] ⇢ \|Directives\|` labelled `borrow(read)` | KEPT: `Graph.access` mode "borrow", `narrow` |
| 29 | `@timeout` (flow) | `… : score({Cart}) @timeout(30s) ×3 @fallback(0)` | LOST | LOST | chip shows only `score({Cart})` | resilience chip `⏱30s ×3 ↩0` next to the payload chip | KEPT: edge mods timeout / × / fallback |
| 30 | `@after` | `[Retry] @after(exp-backoff, cap=1min)` | LOST | LOST | `[Retry]` orphan | node badge `↻ exp-backoff` | KEPT: node mod ("after", …) |
| 31 | `@deadline` | `[Worker] -> run() @deadline(2s)` | WEAK | WEAK | the **whole flow** is dropped (target `run()` is not a glyph) | draw op-call targets as a chip on a self-stub `[Worker] ─▸ run()` | FIXED: the flow is a self-edge, `target_op` "run()", edge mod ("deadline", "2s") |
| 32 | `@fallback` | `… op http.get(${url}) @timeout(5s) @fallback(${cache})` | LOST | LOST | chip `op http.get(${url})` only | `↩ ${cache}` in the resilience chip | KEPT: edge mod ("fallback", "${cache}") |
| 33 | `@grants` / `@requires` | `[AuthSvc] @grants(session)`, `\|PaymentDB\| @requires(write, pci)` | LOST | LOST | orphan boxes | badges `+session` / `⚿write,pci` | KEPT: node mods grants / requires |
| 34 | `@loc` | `[Gateway] @loc(us-east)`, `[Cache<K,V>] @loc(eu-west)` | LOST | LOST | nothing | small `@us-east` tag in the box's bottom border, or group-by-loc lanes | KEPT: node mod ("loc", …) |
| 35 | `!` critical | `(Customer) -> [Api] : {Cart} !` | LOST | LOST | the `!` is no longer glued into the payload chip (`┆ {Cart} ┆`); it is in `Edge.mods` now, which the views do not draw yet | bold/heavy-headed edge (`▼` → `⯆`) or a `!` mark on the arrowhead, not inside the chip | KEPT: edge mod ("!", None); no longer glued into the payload text |
| 36 | `?` optional | `=> ~{Session}?` | LOST | LOST | `~{Session}` | `?` superscript on the target label or a hollow arrowhead `▽` | KEPT: edge mod ("?", None) |
| 37 | `.field` | `{User}.age`, `\|Q\|.nonempty`, `{Job}.state = done` | LOST | LOST | field text gone; `{Job}` never becomes a node | show in loop/branch frame titles (#59–61) and `@inv` badges | KEPT: (".", field) mod; `{Job}` is a node (loop header ref) |
| 38 | `×N` / `xN` on a flow | `[Api] -> [Shard] ×4`, `[Api] -> [Replica] x2`, `[Router] -> [Handler]×N` | LOST | LOST | plain edges into `[Shard]`, `[Replica]`, `[Handler]` | `×4` badge at the arrowhead, or a stacked target box | KEPT: edge mods ("×", "4") / ("×", "2") / ("×", "N") |
| 39 | `×N` / mods on a transition | `_ -<cancel>-> Cancelled ×3`, `Open -<Paid>-> Settled @timeout(1d)` | WEAK | WEAK | only with `p`, as payload chips `┆ ×3 ┆`, `┆ @timeout(1d) ┆` | keep, but style as modifier chips, visible without `p` | KEPT: transition `Edge.mods` |
| 40 | payload: entity glyph | `: {creds}` | DRAWN | DRAWN | with `p`: `┆ {creds} ┆` chip on the edge / `┄┆ {creds} ┆` on the target row | — | — |
| 41 | payload: internal op-call | `: charge(amount) => {Receipt}` | DRAWN | DRAWN | `┆ charge(amount) => {Receipt} ┆` | — | — |
| 42 | payload: value literals | `: false`, `: "ack"`, `: 0.5`, `: null` | DRAWN | DRAWN | `┆ false ┆`, `┆ "ack" ┆`, `┆ 0.5 ┆`, `┆ null ┆` | — | — |
| 43 | payload: `${ref}` | `: ${state.count} + 1` | DRAWN | DRAWN | raw text in the chip | optional: tint `${…}` in the chip | — |
| 44 | payload: map / list | `: {retries: 3, mode: "x"}`, `: [1, 2, 3]` | DRAWN | DRAWN | `┆ {retries: 3, mode: "x"} ┆`, `┆ [1, 2, 3] ┆` (not mistaken for a `{X}` node) | — | — |
| 45 | payload: `"""…"""` block string | `[Grader] -> ~\|Sys\| : """ … """` | WEAK | WEAK | placeholder chip `┆ "block-string" ┆`; content gone (no phantom nodes, good) | first line + `…` (`"You are a strict rubric…"`), full text in a notes-style list | — |
| 46 | payload: value operators | `${state.history} ++ [${out}]`, `${a} \|\| {b: 1}`, `${n} * 2 - ${m} / 4` | DRAWN | DRAWN | raw text in chips | — | — |
| 47 | payload: external `op ns.verb` | `: op http.get(${url})` | WEAK | WEAK | `┆ op http.get(${url}) ┆` — same chip as an internal op; target `(Web)` not marked as host-provided/opaque | distinct chip edge (`╭⇱ http.get ╮`) or a dashed "outside" border on the far node | — |
| 48 | payload on a self-loop | `[Tree.walk] -> [Tree.walk] : child` | LOST | WEAK | graph: `[Tree.walk] ↺`, no chip even with `p`. Tree: only in a footer `── payloads ──  [Tree.walk] -> [Tree.walk] : child` | chip beside the `↺` | — |
| 49 | payloads of several edges to one target | `reserve => {Hold}` + `!> … : release({Hold})` | WEAK | WEAK | merged into one chip `┆ release({Hold}) · reserve => {Hold} ┆` — the error-path payload looks like part of the call | one chip per edge kind, in the edge's stroke | — |
| 50 | alias `name := expr` | `retry := @after(…)`, `walk := [Node] -> walk(.children)` | WEAK | WEAK | nothing; `[Node]` never appears at all | an "aliases" legend block; alias bodies parsed as flows under the alias name | FIXED: `retry`, `walk` are `alias` nodes (mods / expansion = the definition) |
| 51 | expansion `X := { … }` | `[Core] := { [Router] -> [Handler]×N … }` | DRAWN | WEAK | graph: `── [Core] := { … } ──` section, `[Core] ▾` / `▸` at depth 0. Tree: children nested as `├── [Router]` — same `──` as the `\->` "contains" relation | tree: a distinct marker for internals (`├┄ [Router]` or `╞═`), as Mermaid's "internals" subgraph | — |
| 52 | expansion holding only aliases | `[Handler] := { ingress := {Req} => {Ctx} … }` | DRAWN | DRAWN | graph: a header `── [Handler] := { … } ──` with **nothing under it**, and `[Handler] ▾` promises content. Tree: nothing. (Mermaid: an empty `subgraph Handler_service` that collides with the `Handler_service` node inside `Core`) | render aliases (#50) inside the section; else drop the `▾` | FIXED: the section holds the alias nodes `ingress` / `process` / `egress`, each expandable |
| 53 | named declaration | `[Boss]`, `(Auditor)` | DRAWN | DRAWN | orphan strip at the bottom: `│ [Boss] │ │ <N> │ ╭ (Auditor) ╮` | — | — |
| 54 | topic section `--- Name ---` | `--- Control ---`, `--- Composition ---` | LOST | LOST | no trace; all sections merge into one graph | tree: a band row `── Control ──` between units; graph: a section label above each section's layer block | KEPT: `Graph.sections` (level None) |
| 55 | layer section `--- Lk: Name ---` / zoom | `--- L2: [Core] ---`, `--- L3: [Handler] ---` | WEAK | WEAK | header gone; `(Client)` (L2) mixes into L1. `--depth all` is byte-identical to the default: L3 `[Handler] := {…}` is hung on the top-level `[Handler]`, not nested under `[Core]`'s `[Handler]` | show `L1`/`L2` bands; nest an `Lk` expansion under the Lk-1 node it zooms | FIXED: `--- L3 ---` nests under `[Core]`'s `[Handler]`; `--depth all` ≠ depth 1; `Graph.sections` |
| 56 | alternative `a / b` | `[Api] => {Resp} / {Err}` | WEAK | WEAK | `[Api] ━▶ {Resp}`; `{Err}` dropped into the orphan strip as an unconnected node (tree: `{Err}` row with no lane) | fork the `=>` into both with a `/` chip (one-of), or a `╱` split glyph | FIXED: both `=>` edges; one `/` Join (`dst_join`) |
| 57 | scoped block `name { … }` | `checkout { [Cart] -> [Api] }` | LOST | LOST | inner flow drawn; the scope name `checkout` gone | titled frame / tree band like #54 | KEPT: `Block(kind="scope", header="checkout")` |
| 58 | mode line | `#!sketch` | LOST | LOST | nothing (footer is `coverage.sigil: 121 nodes, …`) | `#!sketch` in the footer; spec mode could draw holes red | — |
| 59 | `state` owners, every glyph | `state {Order}`, `state [Checkout]`, `state \|Queue\|`, `state <Signal>`, `state (Courier)` | DRAWN | DRAWN | owner gets `▾`, section `── {Order} state machine ──`; tree nests `├─· Open <Placed>` under each owner | — | — |
| 60 | pseudo-states `+ $ _` | `+ -<Placed>-> Open`, `Settled -<ship>-> $` | DRAWN | DRAWN | `● `, `◉`, `∗ any` circles | — | — |
| 61 | event triggers | `[Payments] ~> <Paid>` + `Open -<Paid>-> Settled` | WEAK | DRAWN | graph: dashed edge `<Placed> ╌╌▶ {Order}` — mono it is the **same** `╎╌` stroke as `~>` (pink only in colour); a `── triggers ──` list helps. Tree: `◎╌` lanes into `Open <Placed>`, `Settled <Paid>`; `--no-triggers` removes all 4 `◎` | graph: a distinct head (`⇢`/`◎`) on trigger edges, as the tree already does | — |
| 62 | trigger narrowing | `<Paid> -> {Order}` (Checkout's `Busy -<Paid>-> Idle` not driven) | DRAWN | DRAWN | triggers list has no `<Paid> ⇢ [Checkout]`; tree `Idle <Paid>` row has no `◎` lane | — | — |
| 63 | `loop @each/@while/@until/@times` | `loop @while \|Q\|.nonempty { … }` | LOST | LOST | bodies flatten into the main graph; headers gone; `{Items}` (`@each x of {Items}`) and `{Job}` (`@until`) never become nodes | graph: a rounded frame titled `↻ @while \|Q\|.nonempty` around the body's nodes; tree: a gutter bracket `┌↻ … └` spanning the body rows | KEPT: `Block(kind="loop")` header/modifiers/members; `{Items}`, `{Job}` are nodes (`refs`) |
| 64 | `parallel @all/@any/@none` | `parallel @all { [Api] -> [Inventory] … }` | LOST | LOST | plain edges; `@all/@any/@none` gone | frame/bracket titled `∥ @all`; reuse the `&`/`&?` join bar (#22–23) | KEPT: `Block(kind="parallel")`, modifiers [("all", None)] |
| 65 | `!>` after a block (compensation) | `}` / `!> [Inventory] : release({Hold})` | DRAWN | DRAWN | drawn as `[Fraud] ──✖──▶ [Inventory]` (last line's target as subject) | attach to the block frame (#64) as source | FIXED: `[Api] !> [Inventory]` from the block's subject; `Block.after` |
| 66 | `branch on X { arm => … }` | `read => [Reader] -> \|DB\|` … `_ => <Rejected>` | LOST | LOST | phantom `=>` chain through all arms: `[Metrics] ━▶ [Reader]`, `\|DB\| ━▶ [Writer]`, `\|WAL\| ━▶ [AdminSvc]`, `[AdminSvc] ━▶ <Rejected>` (heavy, tree `◆━`); `{Request}` and the arm labels never appear | a decision node `◇ {Request}.kind` with `?>` dotted edges carrying arm chips (`read`, `write`, `admin`, `_`) | FIXED: `Block(kind="branch")` arms + `refs` [`{Request}`]; no phantom chain; Mermaid draws `{Request} -. read .-> [Reader]` |
| 67 | recursion: self-arrow | `[Tree.walk] -> [Tree.walk] : child` | DRAWN | DRAWN | `│ [Tree.walk] ↺ │` | — | — |
| 68 | recursion: self-referential alias | `walk := [Node] -> walk(.children)` | WEAK | WEAK | nothing (see #50) | `[Node] ↺ walk` | FIXED: `walk` alias node, expansion `[Node] -> [Node]` (`target_op` "walk(.children)") |
| 69 | `\->` contains | `\-> [Hull]` | LOST | DRAWN | graph (by design, flows only): `[Ship]`, `[Hull]` … sit in the orphan strip as if unconnected. Tree: `├── [Hull]` | graph: optional faint nesting (`d`-style toggle) or `⊂Ship` tag on child boxes | — |
| 70 | `\-&` has | `\-& {Transform}` | LOST | DRAWN | tree `├─& {Transform}` | — (graph as #69) | — |
| 71 | `\-?` when + `{cond}-` | `\-{shattered}-? [Shard]` | LOST | DRAWN | tree `├─{shattered}? [Shard]` | — | — |
| 72 | `\-$` from data | `\-{rows}-$ [Row]` | LOST | DRAWN | tree `├─{rows}$ [Row]` | — | — |
| 73 | `\-@` attached | `\-@ [Tracer]` | LOST | DRAWN | tree `├─@ [Tracer]` | — | — |
| 74 | `\-!` alerts | `\-{lagging}-! <LagAlarm>` | LOST | DRAWN | tree `├─{lagging}! <LagAlarm>` | — | — |
| 75 | `\-=` gathers + `*-` | `\-*-= [ShardQuery]` | LOST | DRAWN | tree `├─*= [ShardQuery]` | — | — |
| 76 | `\-_` one of | `\-_ [PrimaryPsp]`, `\-_ [StandbyPsp]` | LOST | WEAK | tree `├─_ [PrimaryPsp]` / `├─_ [StandbyPsp]` — each marked, but nothing groups the set | a side bracket `⎫` joining the `_` siblings | — |
| 77 | `*-` spawn / bare `\-*` | `\-*-> [Bullet] ×N`, `\-* [Drone]` | LOST | DRAWN | tree `├─* [Bullet]`, `└─* [Drone]` | — | — |
| 78 | `(N)-` weight | `\-(3)-> [ZoneA]`, `\-(1)-> [ZoneB]` | LOST | DRAWN | tree `├─(3)─ [ZoneA]`, `└─(1)─ [ZoneB]` | maybe a share bar `███░` | — |
| 79 | child count `×N` | `\-*-> [Bullet] ×N` | LOST | LOST | `├─* [Bullet]` — `×N` gone | `[Bullet] ×N` badge on the row | KEPT: node mod ("×", "N") on `[Bullet]` |
| 80 | inline branch | `[Log] \-& {Scrollable}` | LOST | DRAWN | tree `[Log]` / `└─& {Scrollable}` | — | — |
| 81 | qualified path `[A]/{B}` | `[Homing] -> [Bullet]/{Transform}` | WEAK | DRAWN | graph: one `{Transform}` box, Homing's edge indistinguishable from Physics' (path dropped). Tree: `[Physics]` taps both `{Transform}` rows, `[Homing]` only `│  ├─& {Transform} ◀──┼─┐` under `[Bullet]` | graph: path chip `/Bullet` on the edge head | — |
| 82 | permission `@read(…)` / `@write(…)` | `*\|AuditLog\| @read(Auditor) @write(Api, Worker)`, `\|Directives\| @read(Worker) @write(Boss)` | LOST | LOST | stores sit as orphans `│ \|Directives\| │`, `│ *\|AuditLog\| │`; no principal links; single-vs-shared writer invisible | dotted access edges (`w` into the store, `r` out of it) under an `a` toggle; tree: an access lane kind (`▷r`/`▶w`); a `1w` vs `Nw` badge on the store | KEPT: `Graph.access` read/write, principals resolved to node ids |
| 83 | generic role | `[Worker<N>]` (`@read(Worker)`) | WEAK | WEAK | phantom `│ <N> │` event box; the role is never drawn | stacked box `[Worker‹N›]` (role = many) | FIXED: `[Worker<N>]` one node; `@read(Worker)` resolves by `base_name` when no exact `[Worker]` |
| 84 | block comment above | `# order lifecycle, driven by events` / `state {Order}` | DRAWN | DRAWN | `{Order} ¶10`; callout `╭ ¶10 order lifecycle, ╮ ──── {Order} ¶10` | — | — |
| 85 | block comment above a glyph-less statement | `# route by request kind` / `branch on …`; header comment above `retry :=` | WEAK | WEAK | anchors to the first arm's glyph `[Reader] ¶11`; the doc header comment (above the alias) is dropped; `¶1` lands on the phantom `<K,V>` | anchor to the block frame (#63–66) or a document-level note | the comment above `retry :=` now lands on the `retry` alias node |
| 86 | inline trailing comment | `=> ~{Session}?  # optional result`, `\-& {Transform}  # inline note on a branch` | WEAK | WEAK | `#12` correctly on the branch row; but `#4 optional result` is placed on `~{Session}` and `#3`/`#6` on the line subject — they follow the parser's subject, so a continuation's note sits on the wrong node | fixed by #21; otherwise fine | — |

### Counts

86 rows × 2 views = 172 cells.

| | Graph | Tree | Total |
|---|---|---|---|
| DRAWN | 31 | 42 | 73 |
| WEAK | 18 | 19 | 37 |
| LOST | 37 | 25 | 62 |
| WRONG | 0 | 0 | 0 |

(Composition rows #69–80 are LOST in the graph on purpose — language.md: "The default
graph view shows the flows alone." Without those 12 rows the graph view has 25 LOST.) Counts as of the render.py
model fixes below; before them: DRAWN 27/38, WEAK 13/15, LOST 38/26, WRONG 8/7.

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
  inside `[Core]` and lists its three aliases. Left: Mermaid ids are global, so a node id used in
  two graphs (top-level `[Handler]` and `[Core]`'s `[Handler]`, now a subgraph) still shares one
  Mermaid id.

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
3. **[FIXED in render.py — model + Mermaid; views still to draw `Graph.blocks`]** **`branch on` arms chain into phantom `=>` edges: WRONG.** Each `label =>` arm is parsed
   as a continuation, so heavy "produces" edges run from the previous statement through every
   arm. The subject and arm labels never appear. Draw a decision node (`◇ {Request}.kind`)
   with `?>`-style dotted edges and arm chips (`read`, `write`, `_`).
4. **[MODEL READY: `Graph.blocks`, `Graph.joins`, `Block.subject` / `after`]** **Control blocks leave no trace (loop, parallel, scoped `name {}`, `@owns {}`), and
   `&`/`&?` joins are lost.** These are half the "control flow" chapter, and the drawing
   reads them as plain unconditional wiring. A titled frame in the graph and a gutter bracket
   in the tree (`┌↻ @while |Q|.nonempty`, `┌∥ @all`) are both consistent with the existing
   section/lane language. A join bar with an `&`/`&?` chip would cover inline joins. It would
   also give the block's `!>` compensation a correct source.
5. **[MODEL READY: `Graph.access`]** **Permission graph is LOST.** `@read`/`@write`/`@borrow` are a whole spec chapter. The
   stores and principals show up only as orphans in the bottom strip, so the reader sees
   "unconnected" where the design has a dense access graph. Add dotted access edges or lanes
   (`r`/`w` heads) under a toggle (an `a` key, like `e` for triggers), plus a single-vs-shared
   writer badge.
6. **Mono-only ambiguities (graph view).** `!>` is plain `│` without colour. Trigger edges
   use the same `╎╌` as `~>`. A `?>` sharing a pair with `->` disappears in the merge. In the
   tree, `<->` is the same as `●─ call`. Each is a one-glyph fix: a `✖` source or heavy-dash
   stroke for `!>`, a `◎`/`⇢` head for triggers, separate strokes for parallel edges, and
   `◀…◀` for `<->` lanes. The tree already has most of these markers.
7. **[MODEL READY: `Node.mods` / `Edge.mods`]** **Modifiers are invisible (`×N`/`xN`, `@timeout`/`@fallback`, `!`, `?`, `@sla`, `@inv`,
   `@cap`, `@loc`, stream `^N@policy`).** The edge or node is still there, so they are lower
   risk, but `×N` and the resilience trio matter for reading a design. A modifier-chip toggle
   (`m`) would cover them, styled like payload chips but separate from them:
   `⏱30s ×3 ↩0`, a `×4` badge at the arrowhead, `^10k⇣drop` in a stream box. It also stops
   `!` showing up inside the payload text (`┆ {Cart} ! ┆`).
8. **[render.py part FIXED: L3 nesting, alias nodes, `a / b`, `Graph.sections`; views still to draw bands]** **Structure/zoom: sections, layers, mode, aliases.** Topic and `Lk` headers vanish.
   `--depth all` equals depth 1 because L3 expansions hang on the top-level node, not the
   L2 occurrence. Alias-only expansions produce an empty `▾` section, and `a / b` drops `b`
   as an orphan. Add section bands (tree) and group labels (graph), nest `Lk` under `Lk-1`,
   render alias bodies, and show `#!mode` in the footer.
