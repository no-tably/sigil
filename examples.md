# Sigil — Worked Examples

This file contains worked prose↔Sigil pairs in core Sigil (no dialect). Consult it when the compress or expand operation is non-trivial. Each example shows the translation and briefly explains key decisions.

---

## Example A: Login flow (prose → Sigil)

**Prose:**

> A user submits their credentials to the web frontend. The frontend forwards them to the authentication service, which verifies them against the user database. If the credentials are valid, the auth service returns a session token that expires in 24 hours and is mutable (since we refresh it). If invalid, it returns an Unauthorized error. Either way, the auth service asynchronously emits a LoginEvent to the audit log.

**Sigil:**

```
#!spec

(User) -> [Web]  : {creds}
[Web]  -> [Auth] : {creds}
[Auth] -> |UserDB|
       => ~{Session}   # ttl 24h
       !> <Unauthorized>
[Auth] ~> <LoginEvent> -> |AuditLog|
```

**Key decisions:**
- `(User)` is an actor, not a component — external to the system we're describing.
- `{creds}` is data being passed as a payload; `~{Session}` is mutable (will be refreshed); the 24h TTL is a comment, since entities carry no schema.
- The `!>` continuation line attaches to the `[Auth] -> |UserDB|` flow, not to `[Auth]` generally.
- `~>` captures "asynchronously emits" cleanly; the audit happens independent of the main flow.

---

## Example B: Checkout with retries and compensation (prose → Sigil)

**Prose:**

> When a user submits a cart, the API runs inventory reservation, payment charging, and fraud scoring in parallel, failing if any of the three fails. Payment is retried up to 3 times with exponential backoff. Fraud scoring must complete within 500ms. If the whole parallel step fails, we release the inventory hold (compensation) and notify the user of the failure. On success, the API asynchronously fans out an OrderPlaced event to shipping, email, and the ledger, then returns confirmation to the user.

**Sigil:**

```
#!spec

(User) -> [API] : {Cart}

parallel @all {
  [API] -> [Inventory] : reserve => {Hold}
  [API] -> [Payment]   : charge  ×3 @after(exp-backoff, cap=1min)
  [API] -> [Fraud]     : score   @timeout(500ms)
}
       !> [Inventory] : release({Hold})
       !> (User)      : <CheckoutFailed>

[API] ~> <OrderPlaced> *> [Shipping] & [Email] & |Ledger|
[API] -> (User) : {Confirmation}
```

**Key decisions:**
- `parallel @all` is the right choice because all three must succeed — the prose says "failing if any fails."
- `×3 @after(exp-backoff, cap=1min)` attaches to the payment arrow specifically.
- The `!>` paths are attached to the parallel block as continuation lines — they run only if the block fails.
- `*>` with `&` chain handles the fan-out to multiple recipients (broadcast with strict join).

---

## Example C: State machine (Sigil → prose)

**Sigil:**

```
state {Job} {
  +         -<submit>->    Pending
  Pending   -<pick>->      Running
  Running   -<ok>->        Done
  Running   -<fail>->      Retryable
  Retryable -<retry>->     Pending     ×3
  Retryable -<exhaust>->   Dead
  Done      -<archive>->   $
  _         -<cancel>->    Cancelled
  Cancelled -<archive>->   $
}
```

**Prose:**

> Jobs go through the following lifecycle:
>
> - A job is created and enters the **Pending** state on submission.
> - A worker **picks** a pending job, moving it to **Running**.
> - From Running, if the job completes successfully, it transitions to **Done** on an `ok` event; if it fails, it transitions to **Retryable** on a `fail` event.
> - Retryable jobs can be retried back to Pending up to 3 times; after exhausting retries, they move to **Dead**.
> - Done jobs are archived (terminal).
> - From any state, a `cancel` event moves the job to **Cancelled**; Cancelled jobs are then archived (terminal).
>
> Terminal states: Done (via archive), Cancelled (via archive), Dead.

**Key decisions:**
- `+` read as "the job is created and enters..."
- `$` read as "terminal" or archived / ended.
- `_` read as "from any state."
- `×3` on a transition reads as "up to 3 times."

---

## Example D: Stream pipeline with backpressure (Sigil → prose, spec mode)

**Sigil:**

```
#!spec

[Ingest]       => *<Raw>^10k@drop
*<Raw>         -> [Parse]    => *<Parsed>^10k
*<Parsed>      -> [Enrich]   => *<Enriched>^10k  @sla(p99<50ms)
*<Enriched>    *> |Warehouse| & |RealtimeIdx|
               !> |DLQ|
```

**Prose:**

> The ingestion service produces an unbounded stream of raw events, buffered at 10,000 items with a drop-oldest overflow policy. The parse stage transforms raw events into parsed events (buffered at 10,000, default backpressure). The enrichment stage transforms parsed events into enriched events (buffered at 10,000, default backpressure) with a p99 latency requirement of 50ms. Enriched events are broadcast to both the warehouse and the realtime index; the broadcast requires both destinations to succeed. If the broadcast of enriched events fails, they are routed to a dead-letter queue.
>
> Unspecified in this Sigil: the transport between stages, serialization format, failure detection mechanism, failure handling of the parse/enrich stages, DLQ retention policy.

**Key decisions:**
- `*<X>^N@drop` unpacks to "bounded at N with drop policy."
- `*<Y>^N` without `@policy` is default policy = block (backpressure).
- Because this is spec mode (`#!spec`), the prose ends with an explicit "Unspecified" list.

---

## Example E: Multi-level zoom (prose → Sigil)

**Prose:**

> The system accepts client traffic at an edge layer, which forwards it to a core layer, which communicates with a data layer. Zooming into the core: there's a load balancer that fans out to N app instances, each of which talks bidirectionally to a cache and forwards to the data layer. Zooming into the data layer: there's a primary database that replicates asynchronously to 2 replicas; the primary writes to OLTP, replicas serve read-only OLTP traffic. An invariant holds: writes only go through the primary.

**Sigil:**

```
#!sketch

--- L1: System ---
(Client) -> [Edge] -> [Core] -> [Data]

--- L2: [Core] ---
[Core] := {
  [LB]  -> [App]×N
  [App] <-> [Cache]
  [App] -> [Data]
}

--- L3: [Data] ---
[Data] := {
  [Primary] ~> [Replica]×2
  [Primary] -> |OLTP|
  [Replica] -> |OLTP-RO|
} @inv write-only-primary
```

**Key decisions:**
- L1 stays completely clean — readable in seconds.
- L2 expands `[Core]` via `:= { ... }`; only introduces the detail about LB/App/Cache at this level.
- L3 expands `[Data]`; note `~>` for asynchronous replication.
- The invariant attaches to the `[Data]` block as a whole.
- Sketch mode chosen because the prose uses "there's a..." style — this is describing an architecture, not pinning down a contract.

---

## Example F: Sketch with holes (prose → Sigil)

**Prose:**

> A user triggers some kind of intent-handling system. We're not sure yet whether it's a single service or a fleet, but it looks up something in a data store and then publishes events to an as-yet-undesigned pub/sub layer.

**Sigil:**

```
#!sketch

(User) -> [?] : {Intent}
[?]    -> |?| : lookup => {?}
[?]    ~> <?> -> [?]    # pub/sub layer TBD
```

**Key decisions:**
- Sketch mode is correct — the prose is full of hedges ("some kind of", "not sure yet", "as-yet-undesigned").
- Holes mark the genuinely unknown: which service handles intent, what store it looks up, what event/consumer the pub/sub is.
- Inline comment `# pub/sub layer TBD` provides human-readable context for the hole.

---

## Example G: Comparison via skeleton form

**Spec A:**

```
(Customer) -> [StorefrontAPI] -> [LoginService] -> |Users| => {SessionToken}
[LoginService] ~> <SignIn> -> |Audit|
```

**Spec B:**

```
(Shopper) -> [WebGateway] -> [AuthLambda] -> |CustomerStore| => {JWT}
[AuthLambda] ~> <LoginEvent> -> |LogSink|
```

**Skeletons:**

```
Both:  (_) -> [_] -> [_] -> |_| => {_}
       [_] ~> <_> -> |_|
```

**Conclusion:** Structurally isomorphic. Both systems: an external actor calls a gateway/API that calls an auth service that reads from a user store and returns a session token; the auth service asynchronously emits a login event to a log/audit store. Differences are purely naming and implementation detail (Lambda vs service, JWT vs generic token, etc.) — the shape of the solution is identical.

---

## Example H: Tighten (messy → SNF)

**Messy input:**

```
[API] -> [Payment] : charge
[API] ~> <OrderPlaced> -> [Shipping]

#!spec

(User) -> [API] : {Cart}
[API]  -> [Inventory] : reserve => {Hold}
Retry := @after(exp-backoff, cap=1min)

[API] @sla(p99<200ms)

[API] -> [Payment] : charge ×3 Retry
       !> (User) : <Failed>
```

**Tightened (SNF):**

```
#!spec

Retry := @after(exp-backoff, cap=1min)

--- System ---
(User) -> [API] : {Cart}
[API]  -> [Inventory] : reserve => {Hold}
[API]  -> [Payment]   : charge  ×3 Retry
       !> (User) : <Failed>
[API]  ~> <OrderPlaced> -> [Shipping]

[API] @sla(p99<200ms)
```

**Changes made:**
- Mode declaration moved to first line.
- Alias cluster (`Retry := ...`) placed just after mode.
- Section header added.
- Duplicate `[API] -> [Payment]` flow merged — kept the fuller one with retries.
- Statement order within section: primary sync flow (topological; `!>` continuations stay under the flow they attach to) → async flows → constraints (`@sla`).
- Whitespace/alignment normalized for scannability.

---

## Example I: Craft session (collaborative authoring transcript)

This example shows how a craft-mode session progresses turn by turn. The user is designing a notification system from scratch.

**User, turn 1:** "Let's design a notification system in Sigil."

**Agent, turn 1:**
> Starting a craft session. At the highest level — who triggers notifications, what kinds of notifications are produced, and where do they land?
>
> Rough L1 draft:
> ```
> #!craft
>
> --- L1: System ---
> (?) -> [?] => <?> -> (?)
> ```
> Holes to resolve: who triggers, what produces, what the notification is, who receives.

**User, turn 2:** "Our backend services trigger them. They go to users via email, push, or SMS depending on preference."

**Agent, turn 2:**
> Good — that gives us the shape. I'm treating the backend as a generic `[Origin]` component (we can open it up later), users as `(User)` (actor), and introducing a `[Router]` that dispatches to the right channel.
>
> ```
> #!craft
>
> --- L1: System ---
> [Origin] ~> <Notification> -> [Router]
> [Router] ?> [Email] / [Push] / [SMS]
> [Email] -> (User)
> [Push]  -> (User)
> [SMS]   -> (User)
> ```
> A few decisions I've made — confirm or push back:
> - `<Notification>` as an event (async fire-from-origin feels right)
> - `[Router]` as a component, not a store — it's active dispatch, not persistence
> - Conditional `?>` because the channel depends on user preference
>
> Should user preferences be a separate store? If so, what reads them?

**User, turn 3:** "Yes, preferences live in a DB, and the Router reads them. Also, we need to record which notifications were sent for audit."

**Agent, turn 3:**
> Adding a `|Prefs|` store that `[Router]` reads, and an `|AuditLog|` store for the record. I'll make the audit async so it doesn't slow delivery.
>
> ```
> #!craft
>
> --- L1: System ---
> [Origin] ~> <Notification> -> [Router]
> [Router] -> |Prefs|              # read user preferences
> [Router] ?> [Email] / [Push] / [SMS]
> [Router] ~> <Sent> -> |AuditLog|
> [Email] -> (User)
> [Push]  -> (User)
> [SMS]   -> (User)
> ```
> Remaining holes: `[Origin]` is still a placeholder for whichever backend services trigger notifications. Want to nail that down, or defer since it's upstream of the system we're designing?
>
> Also — should I tighten this into SNF so we can see the shape cleanly before adding more?

**User, turn 4:** "Defer Origin. Tighten please."

**Agent, turn 4:**
> Tightened:
>
> ```
> #!craft
> # TODO: [Origin] deferred — upstream-agnostic
>
> --- L1: System ---
> [Origin]  ~> <Notification> -> [Router]
> [Router]  -> |Prefs|
> [Router]  ?> [Email] / [Push] / [SMS]
> [Email]   -> (User)
> [Push]    -> (User)
> [SMS]     -> (User)
> [Router]  ~> <Sent> -> |AuditLog|
> ```
>
> Statement order is now canonical: sync flows first (primary dispatch), async afterward (audit). No state blocks yet — do you want to add lifecycle for notifications (e.g., Pending → Sent → Delivered → Failed)?

**... (session continues until user promotes to `#!sketch` or `#!spec`)**

**Key observations about craft dialog:**
- Every turn re-emits the full current document. The user never has to scroll back.
- Glyph-kind decisions are surfaced explicitly ("`<Notification>` as an event because..."), not silent.
- Holes are named and flagged. Deferred holes stay as `[?]` with a TODO comment.
- Tighten is offered, not forced — the user drives when to normalize.
- Implementation detail is refused gently: if the user asked "how should the Router decide?" the agent would note that's internal logic, out of Sigil's scope.

---

## Example J: Agent-memory system with lifecycle and hydration (prose → Sigil)

This example covers a system that is easy to miscode if you're not careful with state glyphs, prose verbs, or the "same component twice" trap. Useful reference for anything with immutable storage, filtered reads, and validated writes.

**Prose:**

> An agent reads from an immutable content-addressed provenance store (PROV) through a semantic interface (MCP). The MCP hydrates a payload for the agent: handles plus rendered summaries, filtered so that superseded and retracted entities are excluded and disputed entities are surfaced with a flag. The agent reasons over one turn (an Activity) and emits mutation events — Unroll, Verify, Dispute, Supersede, Retract — back through the MCP, which validates each and commits to PROV. Separately, a Renderer watches PROV for hash changes on Concept entities and re-materializes Summary entities; Summaries are first-class in PROV. Entities move through a lifecycle: live → disputed (reversible), live → superseded (terminal via archive), live → retracted (terminal via archive). The whole store is immutable, content-addressed, and entities are never mutated in place.

**Sigil:**

```
#!spec

--- agent-memory ---

# aliases
[Agent]      := reasoning worker, stateless wrt memory
[MCP.r]      := read-path semantic interface (hydration)
[MCP.w]      := write-path semantic interface (validation)
[Renderer]   := subgraph -> summary transformer
|PROV|       := immutable time-indexed JSON-LD store
{Fact}       := atomic assertion, content-addressed
{Concept}    := versioned subgraph of facts + sub-refs
{Summary}    := rendered current-state of {Concept}, first-class entity
{Payload}    := extension delivered to [Agent]: handles + summaries

# entity lifecycle
state {Entity} {
  +          -<assert>->      live
  live       -<dispute>->     disputed
  disputed   -<resolve>->     live
  live       -<supersede>->   superseded
  live       -<retract>->     retracted
  superseded -<archive>->     $
  retracted  -<archive>->     $
}

# core read/write loop
|PROV| -> [MCP.r] -> {Payload} -> [Agent]
[Agent] ~> <Activity> -> [MCP.w] -> |PROV|

# hydration policy (on [MCP.r])
[MCP.r] @inv excludes({Entity}.state ∈ {superseded, retracted})
[MCP.r] @inv surfaces-flagged({Entity}.state = disputed)
[MCP.r] -> {Payload} : handles & {Summary}  # staged delivery

# mutation surface (agent-visible events)
[Agent] ~> <Unroll>     # walk wasDerivedFrom backward
[Agent] ~> <Verify>     # unroll + re-check antecedents
[Agent] ~> <Dispute>    # reversible flag
[Agent] ~> <Supersede>  # new entity + wasRevisionOf
[Agent] ~> <Retract>    # withdraw, no replacement

# summary materialization (out-of-loop)
|PROV| ~> <ΔHash>({Concept}) -> [Renderer] => {Summary}
{Summary} -> |PROV|
{Summary} @inv wasDerivedFrom({Concept}.hash)

# global invariants
|PROV|    @inv immutable
|PROV|    @inv content-addressed(id = hash(canonical))
{Payload} @inv extension-only
[MCP.r]   @inv semantic-surface(no raw graph queries)
[MCP.w]   @inv validates-before-commit
{Entity}  @inv lifecycle-transitions-explicit
```

**Key decisions:**
- **`state {Entity}` block** captures the lifecycle cleanly. States are `live / disputed / superseded / retracted`, all named inside the block — not wrapped in parens as actors.
- **`[MCP.r]` / `[MCP.w]` split** at L1 resolves the "same component twice" ambiguity without requiring immediate L2 expansion. The read and write roles have genuinely different invariants, so the qualified names earn their keep.
- **Hydration filters as invariants**, not prose. `@inv excludes(...)` and `@inv surfaces-flagged(...)` attach the filtering behavior to `[MCP.r]` where it lives. The original prose "excludes X and surfaces Y" would be illegal Sigil if written with verbs between glyphs.
- **`.field` accessor** for state predicates: `{Entity}.state = disputed`, `{Entity}.state ∈ {superseded, retracted}`. No new glyphs needed.
- **Mutation events** are all `~>` (async) because the agent emits them and the loop continues; it doesn't await a specific one.
- **`<ΔHash>` as an explicit event** captures the reactive materialization trigger. The Renderer is outside the main loop and reacts to hash-change events rather than being called.
- **Comments (`#`)** carry the semantic gloss that isn't Sigil-native. `# walk wasDerivedFrom backward` is prose documentation, clearly separated from flow syntax.

**Optional L2 expansion:**

```
--- L2: [MCP.r] ---
[MCP.r] := {
  [Surface]      := agent-facing semantic API
  [Hydrator]     := lifecycle filter, staged drill
  [Materializer] := {Summary} cache  # @miss → triggers [Renderer]
}

--- L2: [MCP.w] ---
[MCP.w] := {
  [Surface]  := agent-facing semantic API
  [Validator] := immutability + supersession integrity gate
}
```

At L2, `[Surface]` appears in both expansions — this is fine because each is scoped to its own expansion block; the reader understands they may be the same code or separate instances depending on implementation detail (which Sigil deliberately doesn't specify).

---

## Example K: Value payloads and an external op (prose → Sigil)

This example exercises the value side of the payload grammar (see `language.md`
"Payloads & values"): literal, ref and map values, the closed value operators, a
multiline block-string, and an **external op-call** reaching a host-provided system.

**Prose:**

> A grading loop sets a mutable `running` flag to true and clears it when a stop
> event fires. The judge sends a draft to a scorer. Each score is appended to a
> history store and a running total is incremented. Configuration holds a rubric
> string, an options map, and a long grading policy written out in full. The judge
> also records the score in an external SQL store and searches an external index.

**Sigil:**

```
#!spec

--- judge-loop ---

# control values written to a mutable store
[Loop]  -> ~|running| : true
<stop>  -> ~|running| : false

# an internal op-call (structural) — no `op` keyword, no namespace
[Judge] -> [Scorer]   : score({Draft}) => <rated>

# store writes using the closed value operators
<rated> -> ~|history| : ${state.history} ++ [${out.score}]
~|total|              : ${state.count} + 1
[Cfg]   -> ~|rubric|  : "clarity, correctness, concision"
[Cfg]   -> ~|opts|    : {retries: 3, mode: "strict"}
[Cfg]   -> ~|policy|  : """
Rate the draft 1-10 on ${state.rubric}.
Return only the integer.
"""

# external op-calls: a host-provided reach (far side opaque)
[Judge] -> |Scores|   : op db.insert(${out.score})
[Judge] -> [Index]    : op mcp.search(${query})
```

**Key decisions:**
- **Values are self-describing.** `true`/`false`, the `${…} + 1` arithmetic, the
  `++` list-concat and the `{retries: 3, …}` map literal each say what they carry;
  core Sigil asks for nothing more. (A dialect may require extra annotation, such
  as a tag naming which concern a value serves.)
- **`{retries: 3, mode: "strict"}` is a map literal** (it has a top-level `:`),
  distinct from a data-entity glyph `{Opts}`.
- **The block-string is just a `str`.** The `${state.rubric}` inside it is
  template text for the consumer to fill; sigil does not substitute it.
- **External vs internal.** `op <ns>.<verb>(args)` with a dotted name
  (`db.insert`, `mcp.search`) marks an external reach — the consumer validates
  only its well-formedness; the far side is opaque. `score({Draft})` is an internal
  dispatch — a bare op-call.

---

## Example L: Call resilience (prose → Sigil)

**Prose:**

> A walker repeatedly asks a planner for the next hop until there is no next
> node. Each request is bounded at 30 seconds, retried up to 3 times, and on final
> failure falls back to the current node instead of failing the walk. Visited nodes
> accumulate in a stream store. Separately, a fetcher calls an external HTTP API
> with a 5-second timeout and falls back to a cached value.

**Sigil:**

```
#!spec

--- walk ---

~|node|
*|visited|

loop @while node {
  [Walker] -> [Planner] : next({Node})  @timeout(30s) ×3 @fallback(${node})
  [Planner] => ~|node|    : ${out.node}
  [Planner] => *|visited| : ${state.visited} ++ [${out.node}]
}

[Fetcher] -> [Web] : op http.get(${url})  @timeout(5s) @fallback(${cache})
```

**Key decisions:**
- **`@timeout` · `×N` · `@fallback` compose into one per-call policy**, read
  left-to-right: bound each attempt, retry, then recover with a value.
- **Distinct from `!>` and `@after`.** `!>` routes a failure to another flow;
  `@after` is a backoff schedule. The resilience trio instead says what the *call*
  does when it fails.
- **Store kinds.** `~|node|` is a scalar (last write wins); `*|visited|` is a stream
  (appends accumulate).

---

## Example M: Entity-component system — a composition tree wired as a DAG (prose → Sigil)

**Prose:**

> An arena shooter. A ship carries a position/velocity, health and player input,
> and fires bullets; each bullet has its own position and a damage value. Asteroids
> have a position and health, and break into shards once shattered. Systems do the
> work: physics moves everything with a position, steering turns input into motion,
> homing bends the path of bullets only, combat applies damage to health and
> announces destructions, and a spawner creates the shards.

**Sigil:**

```
#!sketch

--- arena ---

[Ship]
    \-& {Transform}
    \-& {Health}
    \-& {Input}
    \-*-> [Bullet]
        \-& {Transform}
        \-& {Damage}
[Asteroid]
    \-& {Transform}
    \-& {Health}
    \-{shattered}-? [Shard]

--- systems ---

[Physics]  -> {Transform}
{Input}    -> [Steering] -> {Transform}
[Homing]   -> [Bullet]/{Transform}
{Damage}   -> [Combat]   -> {Health}
[Combat]   ~> <Destroyed> -> [Spawner]
[Spawner]  => [Shard]
```

**Tree view** (`view.py FILE --tree` — the outline is the composition, each lane a
flow; `●` a lane's source, `◀` each target):

```text
── systems ──
[Ship]
├─& {Transform} ◀────────────────┬─┐
├─& {Health} ◀───────────────────│─│─┐
├─& {Input} ─────────────●       │ │ │
└─* [Bullet]             │       │ │ │
   ├─& {Transform} ◀─────│───┬───┼─┤ │
   └─& {Damage} ─────────│───│─● │ │ │
                         │   │ │ │ │ │
[Asteroid]               │   │ │ │ │ │
├─& {Transform} ◀────────│───│─│─┼─┤ │
├─& {Health} ◀───────────│───│─│─│─│─┤
└─{shattered}? [Shard] ◀━│━┓ │ │ │ │ │
                         │ ┃ │ │ │ │ │
[Physics] ───────────────│─┃─│─│─● │ │
[Steering] ◀─────────────┴─┃─│─│───● │
[Homing] ──────────────────┃─● │     │
[Combat] ◀───────────────›─┃───┴─────●
[Spawner] <Destroyed> ◀──┴━◆
```

**Key decisions:**
- **Entities are composition trees.** `\-&` attaches a component; `\-*->` marks
  spawned instances (bullets); `\-{shattered}-?` is a part that exists only under a
  condition. None of these are flows — nothing is being called.
- **Systems are ordinary components wired with flows.** `[Physics] -> {Transform}`
  names the component *kind*, so it reaches every entity that has one — the ECS
  query — which the tree view shows as one lane tapping all three occurrences.
- **A path narrows the query.** `[Homing] -> [Bullet]/{Transform}` reaches only the
  Transform directly under a Bullet — not the ship's or the asteroid's. The bare
  `{Transform}` in the Physics line still means every occurrence.
- **Read/write sets give the schedule.** `{Damage} -> [Combat] -> {Health}` says
  Combat reads Damage and writes Health; ordering systems by these edges is the
  system schedule, with no separate scheduling syntax.

---

## Example N: Events driving state — an order's lifecycle and a component's modes (prose → Sigil)

**Prose:**

> A shopper checks out; the checkout records an order and announces it was placed.
> Payments later announces the payment went through, or that it was declined. The
> order opens when placed, settles when paid, and is cancelled when declined. The
> checkout itself is busy from the moment an order is placed until the payment
> resolves either way, then idle again.

**Sigil:**

```
#!sketch

--- checkout ---

(Shopper)  -> [Checkout] -> {Order}
[Checkout] ~> <Placed>
[Payments] ~> <Paid>
[Payments] !> <Declined>

state {Order} {
  +     -<Placed>->    Open
  Open  -<Paid>->      Settled
  Open  -<Declined>->  Cancelled
}
state [Checkout] {
  Idle  -<Placed>->    Busy
  Busy  -<Paid>->      Idle
  Busy  -<Declined>->  Idle
}
```

**Tree view** (`view.py FILE --tree` — an event is drawn where it lands: trigger lanes
(`╍`) run from each emitter (`›`) into the states its events drive; each state lists
the triggers that enter it):

```text
── checkout ──
(Shopper) ───────────────────────●
                                 │
[Checkout] ◀─────────────────────┴─›─●╍›
├─· Idle <Declined> <Paid> ◀─●─┬╍╍╍╏╍│╍╏╍┐
└─· Busy <Placed> ◀──────────┴─●╍╍╍┘ │ ╏ ╏
                                     │ ╏ ╏
{Order} ◀────────────────────────────┘ ╏ ╏
├─· ● ───────────────────────●         ╏ ╏
├─· Open <Placed> ◀──────────┴─●─●╍╍╍╍╍┘ ╏
├─· Settled <Paid> ◀───────────┴╍│╍┐     ╏
└─· Cancelled <Declined> ◀───┬───┘ ╏     ╏
                             ╏     ╏     ╏
[Payments] ╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍╍›╍╍╍╍╍›╍╍╍╍╍›
```

**Key decisions:**
- **Two owners, one set of events.** `state {Order}` is the record's lifecycle;
  `state [Checkout]` is the component's own modes. Both react to the same
  `<Placed>` / `<Paid>` / `<Declined>` — no event is declared twice.
- **Triggers are named after events.** The flows say who raises each event; the
  state blocks say what it does. Matching names are the wiring — viewers and Mermaid
  draw the link, nothing else is authored.
- **The error path is an event too.** `[Payments] !> <Declined>` keeps the failure
  on the error arrow, and the state blocks still react to it by name.

---

## Example O: Fan-out, failover, weighted routing and alarms — a search and payments front (prose → Sigil)

**Prose:**

> Users reach the product through a router that sends three quarters of traffic to
> zone A and a quarter to zone B; both zones serve search. A search spawns one query
> per index shard and merges the shards' hits into one result. Shard queries read
> from a replica, which the primary database feeds asynchronously; while the replica
> lags, a lag alarm is raised and the on-call engineer is paged. Checkout charges
> through a payment provider: a primary and a standby, with exactly one of them
> taking charges at any time.

**Sigil:**

```
#!sketch

--- structure ---

[Router]
    \-(3)-> [ZoneA]
    \-(1)-> [ZoneB]
[Search]
    \-*-= [ShardQuery] ×N
|Replica|
    \-{lagging}-! <LagAlarm>
[Payments]
    \-_ [PrimaryPsp]
    \-_ [StandbyPsp]

--- wiring ---

(User)       -> [Router] : {Query}
[ZoneA]      -> [Search]
[ZoneB]      -> [Search]
[Search]     -> [ShardQuery] => {Hits}
[ShardQuery] -> |Replica|
|Primary|    ~> |Replica|
<LagAlarm>   ~> (OnCall)
(User)       -> [Payments] -> [PrimaryPsp] : {Charge}
[Payments]   -> [StandbyPsp] : {Charge}
```

**Tree view** (`view.py FILE --tree`):

```text
── wiring ──
[Router] ◀────────────────────────────┐
├─(3)─ [ZoneA] ─────────────────●     │
└─(1)─ [ZoneB] ─────────────●   │     │
                            │   │     │
[Search] ◀────────────────●─┴───┘     │
└─*= [ShardQuery] ◀───────┴━━━●━━━━━◆ │
                              │     ┃ │
|Replica| ◀───────────────────┴╌┐   ┃ │
└─{lagging}! <LagAlarm> ╌╌╌╌╌╌╌╌╎╌○ ┃ │
                                ╎ ╎ ┃ │
[Payments] ◀──────────────●─●─┐ ╎ ╎ ┃ │
├─_ [PrimaryPsp] ◀────────┘ │ │ ╎ ╎ ┃ │
└─_ [StandbyPsp] ◀──────────┘ │ ╎ ╎ ┃ │
                              │ ╎ ╎ ┃ │
(User) ───────────────────────●─╎─╎─┃─●
{Hits} ◀━━━━━━━━━━━━━━━━━━━━━━━━╎━╎━┛
|Primary| ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌○ ╎
(OnCall) ◀╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌┘
```

**Key decisions:**
- **`(N)-` is a share, not a count.** `\-(3)->` and `\-(1)->` say zone A takes three
  parts of the traffic to zone B's one. How many of anything exist stays `×N`, as on
  `[ShardQuery] ×N`.
- **Fan-out plus gather is one branch.** `\-*-=` spawns shard queries at run time and
  reduces their results back into `[Search]`. The call and its `{Hits}` stay a flow;
  the branch says who owns the queries and where their results go.
- **The alarm hangs off what it watches.** `\-{lagging}-! <LagAlarm>` puts the alarm
  on the replica, active while the `lagging` condition holds. Paging on-call is
  traffic, so it is a flow from the alarm.
- **`_` is failover without a state machine.** Both providers are wired from
  `[Payments]`; the `_` group says only one is active at a time. If the switch-over
  itself needs rules, add a `state [Payments] { … }` block.

---

## Example P: Permission graph — entities, shared stores, who reads/writes each

A system of entities communicating through **shared stores** is a **permission
graph**: who may `@read(…)` / `@write(…)` each store. Sigil describes the *edges*;
the **shape emerges** — flat, hierarchical, coordinated, isolated, freeform are all
just configurations of those edges. The surface is **consumer-agnostic**: it never
says "swarm" / "agent" / "acl"; the same idiom models a multi-agent system **and**
an ordinary service mesh (the last example below). A downstream tool interprets
the graph and lowers it; sigil only records the edges.

**Flat / integrated — every principal reads + writes one shared store:**

```
#!spec

--- flat ---

[Planner] -> |Shared|
[Builder] -> |Shared|
[Tester]  -> |Shared|

# one shared channel; all three both read and write it ⇒ integrated, all-to-all.
|Shared| @read(Planner, Builder, Tester) @write(Planner, Builder, Tester)
```

**Hierarchical — a parent writes down, children write up:**

```
#!spec

--- hierarchical ---

[Boss]   -> |Directives|
[Worker] -> |Results|

# a DOWN store: Boss is the SOLE writer (cardinality 1 ⇒ single-owner), Worker reads.
|Directives| @read(Worker) @write(Boss)

# an UP store: Worker writes, only Boss reads. The Worker @borrows the down store's
# read access rather than re-declaring it (effective access ⊆ the lender's).
|Results|    @read(Boss)   @write(Worker)
[Worker] @borrow(read) |Directives|
```

**Coordinated — one coordinator reads all, writes a per-principal directive store:**

```
#!spec

--- coordinated ---

[Coordinator] -> |Directives|
[Worker<N>]   -> |Reports|       # a generic ROLE: N workers, count unknown at author time

# the coordinator reads every channel and writes the directive store each worker reads.
|Directives| @read(Worker)      @write(Coordinator)
|Reports|    @read(Coordinator) @write(Worker)
# runtime add/remove of a concrete worker is the consumer's concern (the role
# `Worker` stands for every current member).
```

**Service mesh — services and an auditor over a shared event log (same surface):**

```
#!spec

--- audit-mesh ---

# principals are just entities that hold edges (here, plain services + an auditor).
# Two services append to the log (many writers ⇒ shared; a stream store ⇒ appends
# merge); the auditor reads.
[ServiceA] -> *|EventLog| : <Event>
[ServiceB] -> *|EventLog| : <Event>
(Auditor)  -> *|EventLog|

*|EventLog| @read(Auditor) @write(ServiceA, ServiceB)
```

**Key decisions:**
- **Principals are entities; channels are stores.** No `agents:` roster keyword;
  the principal set is the entities that hold edges. A `|store|` is the channel.
- **Access is `@read(…)` / `@write(…)`** — a matched pair of `@`-modifiers (joining
  the `@grants`/`@requires`/`@owns`/`@borrow` family), each carrying a **`( )`
  comma-list** of bare principal names. The `( )` is the modifier-family arg form
  (like `@cap(read, write)`) — not a `{ }` set.
- **Write cardinality fixes the discipline** — one writer ⇒ strict single-owner;
  many ⇒ shared, resolved by the store kind (stream ⇒ merge, scalar ⇒ last write
  wins). No control-policy keyword.
- **Topology emerges** from the edges — flat / hierarchical / coordinated /
  isolated / freeform. No topology keyword.
- **Delegation is `@borrow`** — narrowable, never wider (child ⊆ parent). No
  hierarchy keyword.
- **Dynamic membership is a generic role** (`[Worker<N>]`) — the role name in a
  list stands for every current member. The static edges are the design-time
  skeleton.
