# Sigil — Language Specification

This document defines the Sigil notation: glyphs, arrows, modifiers, payloads, control-flow blocks, modes, normal form, the formal grammar, the dialect mechanism, and what the language deliberately omits.

Sigil is a compact, non-executable notation for describing system designs — components, data, events, actors, stores, and the flows between them — as compressed symbolic blueprints. The language is consumed by the `sigil` skill (which provides operations like `compress`, `expand`, `compare`, `tighten`, `craft`, `lint`, `render`) and by any other tool that emits or reads Sigil documents.

This file is the **core language** (layer 0). A **dialect** may extend it with extra vocabulary and lint rules for a particular host (see "Dialects"); a document that uses only the vocabulary defined here is valid Sigil everywhere.

For worked prose↔Sigil examples covering the full range of the language, see `examples.md` alongside this file.

---

## Glyphs (entities)

| Glyph   | Kind                    | Example          |
| ------- | ----------------------- | ---------------- |
| `[X]`   | component               | `[AuthSvc]`      |
| `{X}`   | data / record type      | `{User}`         |
| `<X>`   | event / message         | `<OrderPlaced>`  |
| `(X)`   | actor / external system | `(Customer)`     |
| `|X|`   | store / persistence     | `|UserDB|`       |

A **component** `[X]` is anything with identity that does work or is built from
parts — a service, a module, a UI widget, a system, an entity in an
entity-component design. "Service" is one kind of component, not the definition.

**Holes.** Any glyph can take `?` as its name to mean "unspecified of this kind": `[?]` `{?}` `<?>` `|?|` `(?)`.

**Wildcards / anonymous.** `_` in any position means "any" or "I don't care about identity here." Used in state blocks, branches, skeleton form, and pattern positions.

**Parametric.** Generics inside the glyph, in angle brackets: `[Cache<K,V>]`, `{List<T>}`, `<Msg<T>>`.

**Mutability.** Prefix `~` marks in-flux/mutable data. Unmarked is immutable-by-default:
- `{User}` immutable  `~{Session}` mutable  `~|Counter|` mutable store

## Arrows (verbs)

| Arrow          | Meaning                     |
| -------------- | --------------------------- |
| `->` or `→`    | sync call / request         |
| `~>`           | async / fire-and-forget     |
| `<->`          | bidirectional / RPC         |
| `=>`           | returns / produces / yields |
| `!>`           | error / failure path        |
| `?>`           | conditional branch          |
| `*>`           | broadcast / fan-out         |

Arrows compose left-to-right. A **continuation line** (starting with an arrow) inherits only the *subject* of the previous line — not its modifiers. This lets you attach multiple outcomes to one subject without repetition.

Flows are written in source-to-sink order. There is no reverse arrow.

## Modifiers

| Token    | Meaning                       |
| -------- | ----------------------------- |
| `: {X}`  | typed payload (data)          |
| `: verb(args)` | internal operation invocation (the target runs it) |
| `: op <ns>.<verb>(args)` | external (host-provided) op-call |
| `: <value>` | value payload — a literal, a `${ref}`, a `{k: v}` map, a `[…]` list, or a `"""…"""` block-string (see "Payloads & values") |
| `.field` | field accessor                |
| `@loc`   | deployment / region / tier    |
| `×N` / `xN`  | cardinality / retries / fanout (ASCII alternative: `xN`) |
| `#`      | inline comment                |
| `!`      | critical / must-not-fail      |
| `?`      | optional / nullable           |
| `@inv e` | invariant (must hold)         |
| `@sla s` | non-functional constraint     |
| `@timeout(t)`, `@after(t)`, `@deadline(t)` | time constraints |
| `@fallback(x)` | call-resilience fallback (on error / timeout) |
| `@cap(...)` | capability requirement     |
| `@grants(...)` | capability issued       |
| `@requires(...)` | capability required   |
| `@owns X`, `@borrow X` | resource lifecycle |
| `@read(…)`, `@write(…)` | permission-graph access (principal lists on a store) |

**Payload vs operation.** After `:`, a glyphed entity (`{X}`, `<X>`) is data being passed; a bare identifier with parens (`charge(amount)`) is an internal operation invocation. If the operation yields something, follow with `=>`.

See **Payloads & values** below for the full payload vocabulary: value literals/refs, the external `op <ns>.<verb>(…)` reach, and the internal-vs-external boundary for op-calls.

A dialect may add modifiers of its own (see "Dialects"); the table above is the core set.

## Payloads & values

An edge payload (the thing after `:`) names *what flows*. A payload is one of:

1. a **structural** payload — a glyphed entity (`{X}`, `<X>`, …) or a bare
   **internal** op-call (`verb(args)`);
2. a **value** payload — a literal, a `${ref}`, a `[…]` list, or a `{k: v}` map
   literal;
3. an **external** op-call — `op <ns>.<verb>(args)`.

The grammar is **explicit, not inferred**: a value payload says *what* it carries
in its own syntax, and a consumer (a code generator, a validator, a renderer)
reads it deterministically with no shape-guessing. In the core language a value
payload needs no further annotation; a dialect may require one (for example, a
tag saying which concern the value serves).

```
<stop>  -> ~|running| : false          # a control value written to a mutable store
[Cfg]   -> ~|opts|    : {retries: 3}   # a map literal
[Svc]   -> (Client)   : "ack"          # a string value
```

### Value literals

The value vocabulary is a small, conventional, JSON-like type taxonomy: sigil does
not invent exotic literal kinds or operators of its own.

| Form            | Type        | Example                              |
| --------------- | ----------- | ------------------------------------ |
| `true` / `false`| bool        | `<stop> -> ~|running| : false`       |
| `3`, `-1`, `0`  | int         | `: 3`                                |
| `3.14`          | float       | `: 0.5`                              |
| `"…"`           | str         | `: "approved"`                       |
| `null`          | null        | `: null`                             |
| `[a, b, …]`     | list        | `: [1, 2, 3]`                        |
| `{k: v, …}`     | map         | `: {retries: 3, mode: "x"}`          |

A `str` value also has a **multiline `"""…"""` block-string** form — the same
`str` type, spanning multiple lines (see "Multiline block-strings" below).

**Refs.** `${…}` is a reference resolved by the consumer (at generation, deploy or
run time — sigil does not say which) and is **type-preserving** (it resolves to the
referent's type): `${input}`, `${state.count}`, `${out.field}`. A ref may stand
alone as a payload (`: ${input}`) or be substituted into a surrounding string. The
path inside `${…}` is free-form: sigil names the referent, the consumer resolves it.

### `{…}` payload — entity glyph vs map literal

A `{…}` payload is a **map literal** (a value) **iff its body contains a
top-level `:`** (key/value pairs), e.g. `{retries: 3}` or `{ttl: 24h, mode:
"x"}`; **otherwise** it is a **data-entity glyph** (structural), e.g. `{User}`,
`~{Session}`. Every bare-identifier `{X}` payload is an entity. A body that has a
top-level `:` but is not pure key/value pairs is ambiguous and rejected (`SGL100`).

### Multiline block-strings — `"""…"""` (sigil's one multiline construct)

A `str` literal has a **triple-quoted multiline form** `"""…"""` alongside the
single-line `"…"`. It is a **general `str`** — usable **wherever a single-line
`STR` is accepted**. Its typical use is to hold a long, static piece of text *in
the document* — a template, a system prompt, a policy blurb — rather than pointing
at it from outside:

```
~|sys| : """
You are a strict rubric grader.
Rate the draft 1–10 on clarity, correctness, concision.
Interpolations like ${rubric} are resolved by the consumer — not here.
Return only the integer.
"""
```

- **It is sigil's ONLY multiline construct.** Sigil is otherwise strictly
  line-oriented (one statement = one line). The block-string is the single,
  deliberate exception: a **tightly-scoped block-aware path** consumes from the
  opening `"""` to the closing `"""` as one logical token, then resumes per-line —
  it does **not** leak into the rest of the line-oriented model. An **unterminated
  `"""`** (no closing delimiter) is a **lint/parse error** (`SGL170`) — rejected,
  not silently swallowed.
- **`${…}` inside the block is not substituted by sigil.** Sigil carries the
  **template text** verbatim and **names** the `${…}` refs; the consumer
  assembles/substitutes. Inside the `"""…"""` body, `${…}` is ordinary template
  text to sigil ("sigil describes, the consumer assembles").
- **It means exactly what the single-line form means.** A block-string is a `str`
  value like any other; it only changes how the text is laid out in the source.

### Value operators

A value expression may use the closed operator set below — recognized only at the
**top level** of the value (inside a `${…}` ref, a `[…]`/`{…}` literal, or a
quoted string they are ordinary text):

| Operator    | Reads as    | Operands               |
| ----------- | ----------- | ---------------------- |
| `++`        | list concat | each a list            |
| `\|\|`      | map merge   | each a map (right wins on collision) |
| `+ - * /`   | arithmetic  | each a number          |

```
<tick> -> ~|history| : ${state.history} ++ [${out}]   # grow a list slot
~|total|             : ${state.count} + 1             # arithmetic
```

Sigil **describes** the value; it does not run it and does not type-check it.
The value's type-check, if any, happens **at the consumer** (for example when a
store write is realized; an external op's far side is the host's). If a payload
needs an operator this closed set does not have, that is a gap to surface in
prose — not a reason to invent syntax.

### Internal vs external wiring (the boundary)

Edges and op-calls fall in two classes; what a consumer validates differs:

- **Internal wiring** — the closed dispatch graph between the components a
  sigil document describes, plus store writes. This is **fully describable**
  (composition is sound, the actor set is closed, topology resolves).
- **External wiring** — an op that **reaches a peripheral system** (an HTTP
  API, a database, a tool server). It is written at the call site as
  `: op <ns>.<verb>(args)`, where `<ns>.<verb>` is a **dotted** name that
  resolves to a **host-provided operation** (e.g. `http.get`, `db.query`,
  `mcp.search`) and `args` are payloads (literals/refs/map-literals). The
  leading `op` keyword + the dotted namespace make the external reach **visible
  at the call site** — it is not inferred. Its far side is **host-provided** and
  treated as **opaque**. A consumer validates only that the op-call is
  **well-formed** (the op is named with a dotted ns, its param payloads resolve,
  it sits in a sound internal composition); it does **not** reach into or
  validate the external system. A malformed external op-call (no dotted name) is
  rejected (`SGL102`). A result bound back into state is type-checked at that
  bind, by the consumer.

By contrast, an **internal** dispatch stays a bare op-call `: verb(args)` (no
`op` keyword, no namespace) — it is structural.

The principle: sigil (and whatever consumes it) certifies the **wiring**, not the
**world**. An API/DB/tool reach is just another host-provided op.

### Calls — who runs an op, and what comes back

- **The target runs a payload op.** In `[API] -> [Payments] : charge(total)`,
  `[API]` calls and `[Payments]` runs `charge`. A `->` call waits until the op
  returns or fails; a `~>` call does not wait; `<->` is the call and its reply in
  one stroke.
- **`=> X` after an op is what the call returns** to the caller:
  `[Shop] -> |Catalog| : lookup(sku) => {Item}` hands `{Item}` back to `[Shop]`.
- **An op-call written as the target is a self-call:** `[Worker] -> run()` — the
  subject runs that op itself, no other glyph is involved, and
  `[Sched] -> plan({Seed}) => {Plan}` returns `{Plan}` to `[Sched]`. With `op`
  (`[Notifier] -> op mail.send(${report})`) the subject reaches a host-provided op
  whose far side is left unnamed (opaque, as above).
- **Each flow line is its own call.** Two lines with the same endpoints and arrow
  (`: reserve(…)` and `: write(…)` into one `|Index|`) are two calls, not one.
- **A dotted glyph name is one glyph.** `[Tree.walk]` names the `walk` role or
  operation of `Tree` by convention (like the `.read` / `.write` role names lint
  suggests for a glyph that plays two parts); it implies no edge to `[Tree]` —
  write that flow if it exists.

Viewers mark these on the payload chips (`p`): `↺ plan({Seed})` a self-call, `↻` a
recursive one, `↩ {Plan}` what a call returns, `⇱ http.get(…)` a host-provided op —
whose target is badged `(Web) ⇱`, opaque.

## Permission graph

A system of components communicating through **shared persistent state** is a
**permission graph**: a set of **entities** (the principals), a set of **stores**
(the shared channels), and the **read/write edges** between them. Sigil describes
this graph in general vocabulary — it does **not** name any consumer's notion of a
"swarm", "agent roster", or "ACL". A reader who knows nothing about a particular
runtime reads it as exactly what it is: *entities, shared stores, and who may read
or write each.* The SAME surface models a multi-agent system **and** an ordinary
service mesh (e.g. `[ServiceA]` writes an event log an `(Auditor)` reads).

A downstream tool MAY lower this graph to a concrete shape — N isolated sessions
over one shared store, a single store with per-principal projections, per-channel
access maps — but that lowering is the **consumer's**, not the surface's. Sigil
names the edges; the shape **emerges** from them.

### Principals are entities; channels are stores

- A **principal** is any modeled **entity** — a component `[Planner]`, an actor
  `(Customer)`, another component `[ServiceA]`. There is **no roster keyword**: the
  principal set is simply the entities that appear in read/write edges.
- A **channel** is a **store** `|name|` — shared persistent state. The store glyph
  is unchanged.

### Access modifiers — `@read(…)` / `@write(…)` (principal lists)

Access is expressed with two **`@`-modifiers** that join the existing capability
family (`@grants` / `@requires` / `@owns` / `@borrow`). They **anchor on the
store** (as `|PaymentDB| @requires(write, pci)` anchors access on the store) and
each carries a **`( )` comma-list** of the principal entities permitted that
access — exactly the paren-wrapped argument form every other modifier in the
family uses (`@cap(read, write)`, `@requires(write, pci)`):

| Modifier      | Meaning                                            |
| ------------- | -------------------------------------------------- |
| `@read( … )`  | the principals permitted to **read** the store |
| `@write( … )` | the principals permitted to **write** the store |

The argument is a **`( )` comma-list** — the modifier-family arg form — **not** a
`{ }` set (in sigil `{ }` is reserved for block bodies and value/predicate sets
like `{Order}.status ∈ {pending, active}`, never a modifier's arguments) and
**not** a `[ ]` list. Its members are **bare principal names** (the names of
declared entities), comma-separated; a one-member list needs no special form
(`@write(Boss)`). An empty list, a duplicated member, a member that is not a
bare name, or a name that does not resolve to a declared entity or generic role
is rejected (`SGL140`–`SGL143`):

```
[Boss]
[Worker]
[ServiceA]
[ServiceB]
(Auditor)
|Directives| @read(Worker)  @write(Boss)        # Boss writes; Worker reads
|Results|    @read(Boss)    @write(Worker)      # Worker writes; Boss reads
|EventLog|   @read(Auditor) @write(ServiceA, ServiceB)   # two writers, one reader
```

Read it as a graph edge: `@write(ServiceA, ServiceB)` is the in-edges of
`|EventLog|` (who may write it); `@read(Auditor)` is its out-edges (who may read
it). A store with **no** `@read` is readable by none-by-default at this surface
(the consumer decides whether absence means "deny" or "open"); the surface only
records the **declared** edges.

### Cardinality decides single-owner vs shared — no policy keyword

There is **no control-policy keyword.** The write cardinality alone fixes the
write discipline:

- **`@write(boss)`** — exactly **one** writer ⇒ a **strict single-owner** channel.
- **`@write(a, b, c)`** — **many** writers ⇒ a **shared** channel (the store's own
  resolution policy settles concurrent writes — see below).

If a clearer single-owner *spelling* is wanted, the existing **`@owns |store|`**
ownership modifier already says "this entity solely owns this store"; it is
equivalent to a single-member `@write( )` and may be used interchangeably. Prefer
the emergent cardinality rule; keep the vocabulary minimal.

**The store KIND supplies the shared-resolution policy (cardinality ⊕ store-kind
interlock).** Cardinality fixes *single-vs-shared* but **defers** how a *shared*
channel resolves concurrent writes. The **store kind** is exactly that deferred
policy:

- a **`*|…|` accumulator** (a stream / collection) ⇒ **merge / commute** — concurrent
  appends accrete;
- a **`~|…|` input** (a mutable scalar) ⇒ **last-writer-wins** — the latest write replaces.

So cardinality (single-vs-shared) and store kind (the shared resolution) **INTERLOCK** —
two halves of one design, not a conflict. The motivating case: the SAME writer-set (a
role, cardinality N) can write BOTH a `*|log|` accumulator (concurrent appends MERGE) and
a `~|turn|` input (last-writer-wins) — so the resolution can only come from the store
kind. A consumer reads the store kind for this resolution (it does **not** infer it
purely from cardinality).

### Topology emerges — no topology keyword

There is **no topology keyword.** Every familiar shape is just a configuration of
read/write edges:

- **flat / integrated** — every principal in both the `@read` and `@write` set of
  one shared store.
- **hierarchical** — a parent writes a *down* store children read (`@write(boss)`
  / `@read(worker)`); children write an *up* store only the parent reads.
- **isolated** — no shared stores (each principal touches only private state).
- **coordinated** — a coordinator reads every store and writes a per-principal
  directive store each principal reads.
- **freeform** — arbitrary read/write edges.

You do not enumerate the topology; you author the edges and the shape is whatever
they describe.

### Delegation — `@borrow`

When a principal **delegates** to a sub-principal, the delegate does not
re-declare the delegator's edges — it **`@borrow`s** them, reusing the existing
`@owns` / `@borrow` ownership-lending idiom. A borrowed access is **narrowable but
never wider** than the lender's: the **effective delegate permission is a subset
of the lender's** (`child ⊆ parent`). The forms:

```
[Worker] @borrow |Directives|             # borrows the lender's full access to |Directives|
[Worker] @borrow(read) |Shared|           # borrows ONLY read (narrows write away)
```

The narrowing argument is `read` or `write` (anything else is `SGL144`).
Delegation chains end at the top entity. No hierarchy keyword is introduced.

### Dynamic membership — generic roles

When the principal set is **not known at design time** (N workers created at
runtime), name a **role with cardinality** using the entity's existing
**`generics?`** — a `Worker` *role*, not enumerated `WorkerA` / `WorkerB`:

```
[Worker<N>]                                      # a role: N workers, count unknown at author time
[Coordinator]
|Tasks| @read(Worker) @write(Coordinator)        # the ROLE `Worker` reads the store
```

A `( )` list member that names a **generic role** (rather than a concrete entity)
stands for *every* current member of that role. The static `@read` / `@write`
edges are the **design-time skeleton**; **runtime add/remove of a concrete
member** is the consumer's concern (it lowers onto whatever dynamic-permission
primitive the target provides). Sigil **describes** the role surface; it does
**not** run the add/remove path.

### What this surface does and does not say

The permission graph is a set of **declarations**: the `@read(…)` / `@write(…)`
modifiers do not lower as values. A document with no `@read`/`@write` edges is
fully valid. A consumer interprets the graph — mapping each entity to a principal,
each store's read/write sets to its access map, each `@borrow` to inherited edges,
and each generic role to a dynamic principal class — but that is the consumer's
lowering, not part of this surface.

## Structure

| Token              | Meaning                      |
| ------------------ | ---------------------------- |
| `\|S\| @read(…) @write(…)` | permission-graph access edges (principal lists on a store) |
| `@borrow X`        | delegate (lend) access (child ⊆ parent) |
| `name := expr`     | named alias / expansion      |
| `name { ... }`     | scoped block                 |
| `--- Lk: Name ---` | layer section header         |
| `--- Name ---`     | topic section header         |
| `a / b`            | alternative (one-of)         |
| `a & b`            | **strict join** (both must succeed) |
| `a &? b`           | race / first-wins            |
| `#!spec`, `#!sketch`, `#!craft` | mode declaration (top of doc) |

`&` is strict-join-by-default — bare `A & B` means "both A and B, wait for both, fail if either fails." For racing, use `&?`. For fire-and-forget parallelism, use `~>` multiple times or a `parallel @none` block.

Indentation has no semantic weight — use it for readability. (A dialect may define
an indentation-significant authoring style of its own; core Sigil never does.)

---

## Control-flow blocks

Control flow lives in named blocks rather than overloading arrows.

**Modifiers after a block.** Any block — a named block, `state`, `loop`, `parallel`,
`branch`, an `@owns` scope, a `:= { … }` expansion — may carry modifiers after its
closing `}`. They apply to the block as a whole — a deadline over every member of a
join, an invariant over a loop — and an expansion's go to the entity it expands
(`} @inv write-only-primary`, Example 6).

```
#!sketch
parallel @all {
  [Checkout] -> [Payments] : charge({Order}) @timeout(2s)
  [Checkout] -> [Stock]    : reserve({Order}) @timeout(2s)
} @deadline(3s)

loop @while {Queue}.size > 0 {
  [Worker] -> |Queue| : take() => {Job}
} @inv terminates
```

### State machines (and lifecycle)

```
state {Name} {
  +         -<create>->    S1
  S1        -<trigger>->   S2
  S2        -<done>->      $
  _         -<cancel>->    Cancelled
}
```

- `+` — creation source (no predecessor)
- `$` — terminal state (no successor)
- `_` — wildcard source (transitions from any state)
- **A specific transition beats `_`.** When a state has its own transition for a
  trigger, that transition is taken and the wildcard's is not, whichever is written
  first.
- **A self-loop `S -<T>-> S` says "seen and ignored on purpose".** The machine stays
  in `S` when `T` arrives there; it is the one way to state that an event is
  deliberately ignored in a state (and, with the rule above, to keep a state out of a
  wildcard's reach).
- Inside a `state` block, bare names are states of its owner, `->` is a transition, and `<x>` between the dashes is the trigger.
- **Any glyph owns a state machine.** `state {Order} { … }` is a record's lifecycle;
  `state [Checkout] { … }` is a component's own modes (idle / busy / draining);
  `state |Queue| { … }` a store's. The machine belongs to — and in views nests under —
  its owner.
- Per-transition modifiers: `×N` (retry count), `@inv`, `@timeout`, etc.

Lifecycle is just a state machine with `+` and `$`. No separate keyword.

```
#!sketch
state {Order} {
  _         -<cancel>->  Cancelled
  +         -<place>->   Open
  Open      -<pay>->     Settled
  Settled   -<pay>->     Settled     # a repeated payment is ignored on purpose
  Settled   -<cancel>->  Settled     # beats `_`: a settled order is not cancelled
  Settled   -<ship>->    $
}
```

**Events drive transitions by name.** A trigger names an event: when the document
has an event glyph of the same name (case-insensitive), that event **is** the
trigger — no extra wiring syntax. Flows say who raises the event; the state block
says what it does to its owner:

```
#!sketch
[Payments] ~> <Paid>
[Checkout] ~> <Placed>

state {Order} {
  +     -<Placed>->  Open
  Open  -<Paid>->    Settled
}
state [Checkout] {
  Idle  -<Placed>->  Busy
  Busy  -<Paid>->    Idle
}
```

Here `<Paid>` settles the order *and* frees the checkout. Viewers draw the link:
`view.py` draws a dashed edge from `<Paid>` to each owner it drives (and lists the
transitions under "triggers"), `view.py --tree` draws `<Paid>` where it lands — a lane
from whoever emits it (`›`) into each state it enters (`e` toggles both; `v` /
`--events land|nodes` switches either view between an event drawn where it lands and
an event drawn as a node of its own) — and Mermaid gets a dotted `triggers` edge.
`view.py --sim` runs the machines: each event moves its owners' current state (`◉`). A trigger with no matching event is still valid — it
names a cause outside the document.

**Narrowing: aim an event at one owner.** By default an event drives every machine
that names it as a trigger. When an event has explicit flows to state-machine
owners, only those owners' machines react to it:

```
#!sketch
[Payments] ~> <Paid>
<Paid> -> {Order}             # only the order's machine reacts to <Paid>

state {Order} {
  Open  -<Paid>->  Settled
}
state [Checkout] {
  Busy  -<Paid>->  Idle       # not driven by this <Paid>: the flow above narrows it
}
```

With no such flows, the event still drives every machine naming the trigger.

**Typo hint.** Matching ignores case. Lint `SGL091` (info) flags a trigger that
matches no event but is one edit away from one (two edits for names of five or more
characters): "trigger <Payed> matches no event; did you mean <Paid>?". A trigger
that is not close to any event gets no note, since machines may be driven from
outside the document.

**When to use `state` blocks.** Any time an entity, component, task, job, document, session, or record can be in one of several named modes — use a `state` block. Triggers: the words "state," "status," "phase," "lifecycle," "mode," or any enumeration like "live/disputed/retracted," "pending/running/done," "draft/published/archived." Do not model these as actor glyphs `(X)`, data glyphs `{X}`, or ad-hoc tags. The state block is the single canonical place lifecycle information lives.

**Referencing states inline.** To filter, predicate, or gate on an entity's current state from outside the state block, use the `.field` accessor: `{Fact}.state = live`, `{Order}.status ∈ {pending, active}`, `{Task}.phase != archived`. This works inside `@inv`, `branch on`, guard conditions, and loop terminators. Do not introduce new glyph shorthands for states — the state block defines them, the `.field` accessor references them.

### Loops

```
loop @each x of {Xs}  { ... }    # for-each
loop @while cond      { ... }    # pre-check
loop @until cond      { ... }    # post-check
loop @times N         { ... }    # counted
```

The loop modifiers (`@each`/`@while`/`@until`/`@times`) are loop-only in the core
language: a bare `@each` with no `loop` host is rejected. (A dialect may give
`@each` a further host — see "Dialects".)

### Parallel execution

```
parallel @all  { ... }    # wait for all, fail if any fails
parallel @any  { ... }    # race, first wins, cancel rest
parallel @none { ... }    # fire-and-forget all
```

Use `parallel` blocks when each branch has internal structure. For single-destination fan-out, inline `&` / `&?` is sufficient.

### Branching

Inline conditional: `?>`. Labeled branches:

```
branch on {Request}.kind {
  read  => [Reader]  -> |DB|
  write => [Writer]  -> |DB| -> |WAL|
  admin => [AdminSvc] @cap(admin)
  _     => <Rejected>               # default / fallthrough
}
```

### Recursion

Self-arrows or self-referential aliases:

```
walk := [Node] -> walk(.children)
[Tree.walk] -> [Tree.walk] : child
```

A self-arrow (or an alias whose body calls its own name) is a recursive call. Sigil
does not describe the recursion's base case — that is the callee's internals (see
"What Sigil deliberately doesn't do"). A design **may** state a bound on it, as an
invariant on a node of the recursion: `@inv depth <= N` (how deep it can go) or
`@inv terminates` (it ends, without a number). Stating one is optional; recursion
without one is still valid.

```
#!sketch
[Doc.walk] -> [Doc.walk] : child
[Doc.walk] @inv depth <= 32
```

A stated bound does not change how a design is run: a consumer that runs it bounds
the depth itself (`view.py --sim` stops at depth 3 and logs a base case).

---

## Streams, generators, backpressure

A stream is a sequence of elements over time: `*<X>` (events) or `*{X}` (data). The `*` prefix denotes multiplicity.

```
[Source]    => *<Event>              # generator
*<Event>    -> [Filter] => *<Event>  # stream transform
*<Event>    -> [Consumer]            # sink
```

**Backpressure and boundedness.** `^` is the cap/ceiling operator on streams. The `@policy` suffix attaches *to the bound* — it describes overflow behavior, not general stream semantics:

| Notation        | Meaning                                     |
| --------------- | ------------------------------------------- |
| `*<X>`          | unbounded stream                            |
| `*<X>^N`        | bounded at N, default policy (block/backpressure) |
| `*<X>^N@drop`   | bounded, drop oldest on overflow            |
| `*<X>^N@latest` | bounded, keep only latest on overflow       |
| `*<X>^N@err`    | bounded, raise on overflow                  |

`*<X>` (stream) is distinct from `*>` (broadcast fan-out) and `×N` (static cardinality). A stream is temporal; fan-out is topological; cardinality is quantity.

**Failures stop at the consumer.** A stream decouples its producer from its
consumers: nothing awaits an element once it is in the stream, so a consumer's
failure stops at that consumer and never fails the producer upstream (the same holds
behind a `~>` send). Route it where it happens. In Example 4 a failing `|Warehouse|`
fires the `!> |DLQ|` under the `*>` line, and `[Ingest]` goes on producing.

**Store kinds.** The same prefixes classify a **store**: a bare `|X|` or mutable
`~|X|` is a **scalar** store (one held value), and `*|X|` is a **stream** store (a
sequence that accumulates over time). The kind is what decides how concurrent
writes resolve (see "Permission graph → Cardinality decides single-owner vs
shared").

---

## Abstraction & zoom

`[X] := { ... }` defines an expansion for `X` that can be read separately. Top-level stays legible; zoom is opt-in.

```
--- L1: System ---
(Client) -> [Gateway] -> [Core] -> |DB|

--- L2: [Core] ---
[Core] := {
  [Router]   -> [Handler]×N
  [Handler] <-> |Cache|
  [Handler]  -> |DB|
  [Handler]  ~> <AuditEvt> -> |Log|
}

--- L3: [Handler] ---
[Handler] := {
  ingress := {Req} => {Ctx}
  process := {Ctx} => {Resp} / {Err}
  egress  := {Resp} -> (Client)
}
```

Any entity can be expanded later; an entity without an expansion is a leaf. Deeper sections go **below** shallower ones — general-to-specific top-down.

---

## Composition trees

Flows say how things **talk**. A composition tree says what things are **made of**:
which parts a component contains, which components an entity carries, what it
spawns. The two are orthogonal and live in the same document — the tree is the
hierarchy, the flows are a DAG wired across it.

A tree hangs under a parent glyph. Each child line starts with a **branch marker**
`\-` followed by a **relation**, and indentation gives depth:

```
#!sketch
[Ship]
    \-& {Transform}
    \-& {Health}
    \-*-> [Bullet]
        \-& {Transform}
        \-& {Damage}
[Asteroid]
    \-& {Transform}
    \-{shattered}-? [Shard]

[Physics] -> {Transform}
{Damage}  -> [Combat] -> {Health}
```

### Relations

A branch carries exactly one relation, from this closed set:

| Relation | Reads as | Meaning | Example |
| --- | --- | --- | --- |
| `\->` | contains | a part owned by the parent (the default relation) | `[Cluster]` `\-> [Api]` |
| `\-&` | has | a component or mixin carried by the parent | `[Ship]` `\-& {Health}` |
| `\-?` | when | present only while a condition holds | `\-{shattered}-? [Shard]` |
| `\-$` | from data | children produced from data at run time (an unbounded or not-yet-known set) | `\-{rows}-$ [Row]` |
| `\-@` | attached | wired into the parent at run time rather than authored in place (a sidecar, a plugin) | `\-@ [Tracer]` |
| `\-!` | alerts when | a monitor, alarm or assertion on the parent, active while a condition holds | `\-{lagging}-! <LagAlarm>` |
| `\-=` | gathers | the children's results are reduced back into the parent (scatter/gather, fork-join) | `\-*-= [ShardQuery]` |
| `\-_` | one of | exactly one sibling in the `_` group is active at a time (active/standby, blue/green, a strategy) | `\-_ [PrimaryPsp]` |

Three prefixes refine a relation. Each ends in `-`, so the relation always follows
a dash:

- **`*-`** marks spawned *instances*, many and created at run time
  (`\-*-> [Bullet]` — the ship creates bullets). A bare `\-*` means "spawns" with the
  default relation. It combines with any relation: `\-*-= [ShardQuery]` spawns
  shard queries and gathers their results.
- **`(N)-`** is a **weight**: a relative share among siblings (traffic split,
  capacity, priority). `\-(3)-> [ZoneA]` next to `\-(1)-> [ZoneB]` is a 3:1 split.
  It is not a count.
- **`{cond}-`** names the condition or data source the branch depends on
  (`\-{shattered}-?`, `\-{rows}-$`, `\-{lagging}-!`). The name is a plain identifier
  (letters, digits, `_`, `-`); write `{lagging}-!`, not `{lag>5s}-!`.

`(N)-` and `{cond}-` are alternatives: a branch carries at most one of them, after
an optional `*-`. A count stays the ordinary cardinality token on the child's line
(`\-*-> [Bullet] ×N`). A child may carry flows on its own line
(`\-> [Router] -> [Handler]`); a child written on the parent's line
(`[Log] \-& {Scrollable}`) is an inline branch.

**Semantics.**

- The tree is structure, not traffic: branches add no flow edges. Wiring stays in
  ordinary flow lines, which may connect any nodes in the tree, at any depth.
- The same name under several parents is the **same kind** of thing composed into
  each of them (`{Transform}` on both the ship and the bullet). A flow that names
  it applies to every occurrence — exactly how a system in an entity-component-system
  design touches every entity that has the component. A qualified path narrows that
  (next section).
- `X := { … }` and composition trees are complementary: `:=` zooms into how a
  component *works* (its internal flows); a composition tree states what it
  *consists of*. A document can use both; viewers nest expansions under their node.
- Branch markers are recognised only at the start of a line or right after a
  parent glyph — `\-` inside prose, a comment or a payload is just text.

**Where it fits.** Entity-component-system designs (entities → components, prefabs →
spawned instances, systems wired to components), UI component trees, deployment
topology (region → cluster → service), fan-out/fan-in services, failover pairs,
organisational structure, document or scene graphs — anything that is both a
hierarchy and a network.

### Qualified paths

A bare name in a flow means **every occurrence** of it. To reach only some
occurrences, write a **path**: glyphs joined by `/` with no spaces around it.

```
#!sketch
[Ship]
    \-& {Transform}
    \-*-> [Bullet]
        \-& {Transform}

[Physics] -> {Transform}              # every Transform: the ship's and each bullet's
[Homing]  -> [Bullet]/{Transform}     # only the Transform directly under a Bullet
```

- Each `/` is a **direct parent → child step** in the tree.
- A path matches as a **suffix** of an occurrence's ancestor chain.
  `[Bullet]/{Transform}` matches a Transform directly under any Bullet, wherever that
  Bullet sits; `[Ship]/[Bullet]/{Transform}` is fully qualified.
- A path may be a flow's source or its destination.
- `/` with spaces around it keeps its old meaning, alternatives:
  `process := {Ctx} => {Resp} / {Err}`.

Lint `SGL112` (warning): a path that matches no occurrence in the document.

### Rendering composition

**Terminal.** `view.py FILE --tree` draws the tree as an outline and each flow as a
lane beside it (`●` marks a lane's source, `◀` each target; a lane crossing another
row hops over it). A flow to a bare name taps every occurrence; a path flow taps only
the occurrences it matches. An opened `X := { … }` expansion's members hang off dotted
rails (`├┄┄ [Router]`), apart from a branch's solid `├──`; a run of `\-_` one-of
siblings is joined by a brace (`⎫ … ⎭`) after their labels. The default graph view
and the flow view (`--flow`, a call graph read left to right) show the flows alone.

**Mermaid.** `render.py` draws composition by default:

- **Subgraphs** (the default). A parent with branches becomes a `subgraph`, and every
  occurrence is its own node, so the ship's `{Transform}` and the bullet's
  `{Transform}` are two boxes. A flow to a bare name fans out to every occurrence; a
  path flow reaches only the matching ones. A parent that also has a `:=` expansion
  keeps it as a nested "internals" subgraph.
- **`--composition edges`**: one node per name, with a dotted edge from parent to
  child labelled with the relation word (`contains`, `has`, `spawns`, `when`, …).
- **`--composition none`**: no composition, only flows.

A dialect may change the default (see "Dialects").

Lint: `SGL110` a malformed branch or an unknown relation; `SGL111` a branch with no
parent above it; `SGL112` a path that matches nothing. A dialect may add relations
(for example layout relations for a UI host).

---

## Invariants, capabilities, resource ownership

**Invariants** — claims that must hold at the point they appear:
```
|UserDB| @inv unique:email
[Payment] @inv idempotent(transaction_id)
{User}.age @inv >= 0
```

`@inv` takes a free expression, and any expression stays valid. **Recognised
invariants** are the short list of heads a checker can test against the wiring — one
form per risk. Where an existing modifier already says the same thing, write that
instead (last column).

| Invariant | States that | Prefer instead, when it fits |
| --- | --- | --- |
| `idempotent(key)` | a repeat (on `key`) has no further effect | — |
| `dedup(key)` | the channel drops duplicates | — |
| `atomic(x, …)` | these effects commit together | — |
| `ordered(key)` | arrivals keep their order (per key) | — |
| `serialised(\|S\|)` | writes to `S` are applied one at a time | `@owns \|S\|`, a single `@write(…)` |
| `cas(field)` | writes compare-and-set on a version | — |
| `immutable` | written once, never changed | — |
| `depth <= N` | a recursion goes at most `N` deep | — |
| `hops <= N` | a message cycle takes at most `N` hops | — |
| `terminates` | a loop or recursion ends | `@times N`, `@each`, a `?>` exit |
| `retention(t)` | stored items expire after `t` | — |
| `lock-order(\|A\| < \|B\|)` | stores are always acquired in this order | — |
| `layers(a > b > c)` | the order of `@loc` tiers (calls go downward) | — |
| `retry-budget(p)` | retries are capped at a share `p` of traffic | — |
| `limit(N)` | a data result is capped (a page size) | `^N` on a stream result |
| `concurrency <= N` | at most `N` spawned tasks at once | `×N` on the child, `^N` upstream |
| `consistent(model)` | the read model a reader accepts | — |

Other risks already have notation and get no `@inv` head: a bound (`^N`), a rate or
latency (`@sla`), ownership (`@owns`, `@write(…)`), a time bound (`@timeout`,
`@deadline`), a handled failure (`!>`, `@fallback`), an exit (`?>`), a terminal
state (`$`), a reply (`=>`), and "ignored on purpose" (the self-loop `S -<T>-> S`).
Anything else written after `@inv` (`unique:email`, `>= 0`) is a claim for readers
that tools list as unchecked.

**SLAs and timing:**
```
[API] @sla(p99<100ms, avail>99.95%)
[Worker] -> run() @timeout(30s)
[Retry]  @after(exp-backoff, cap=1min)
```

**Call resilience — `@timeout` · `×N` · `@fallback`.** A call (an op invocation,
an external `op` reach, a request to an actor) describes its **error policy** with
three composable modifiers:

| Modifier        | Meaning on a call                                          |
| --------------- | ---------------------------------------------------------- |
| `@timeout(t)`   | bound one attempt — exceed `t` ⇒ the attempt is an error   |
| `×N`            | **retry count** — re-attempt up to `N` times on error      |
| `@fallback(x)`  | on **final** failure (retries exhausted / timeout), yield `x` instead of failing the call |

`@fallback`'s argument `x` is the recovery payload — a **value** (`@fallback("")`),
a **`${ref}`**, or an **op-call** (`@fallback(default())`). The three compose into
one policy and read left-to-right:

```
[Judge] -> [Scorer] : score({Draft})  @timeout(30s) ×3 @fallback(0)
#   one attempt ≤ 30s; up to 3 retries; on final failure yield 0 instead of erroring
[Svc] -> [Web] : op http.get(${url})  @timeout(5s) @fallback(${cache})
```

**Where `×N` sits decides what it means.** The same token is a retry count or a
cardinality, and its place says which:

- trailing a call's payload (`: charge({Order}) ×3`) — **retries** of that call;
- glued to a glyph (`[App]×3`, `(User)×N`) or on a node's own line — **cardinality**:
  that many instances, never a retry. An actor with a cardinality is that many
  concurrent callers; a plain `(User)` is one caller, whose requests come one after
  another;
- trailing a flow with no payload (`[Api] -> [Shard] ×4`) — read as cardinality of
  the destination; lint notes it (SGL187) and suggests the glued `[Shard]×4`.

```
#!sketch
(User)×N -> [Api] : submit({Form})
[Api] -> [Billing]×2 : charge({Order}) ×3 @timeout(2s)
#   many concurrent users; two billing instances; each charge retried up to 3 times
```

`@deadline(t)` bounds the **whole** call — every attempt and the waits between
them; past it the call has finally failed (and yields its `@fallback`, if any).

This is **distinct** from the `!>` error *path* (which routes a failure to
another flow) and `@after` (a backoff schedule): `@timeout`/`×N`/`@fallback`
declare the **per-call resilience policy**, which a consumer maps onto its
target's error-handling mechanism.

The two compose. A `!>` under a call that has a `@fallback` still fires when the
call finally fails — "notify, then yield": the route runs, then the call returns its
fallback instead of failing. So degrading and alerting needs no extra notation:

```
#!sketch
[Search] -> [Ranker] : rank({Hits})  @timeout(200ms) @fallback(${hits})
  !> <RankerDegraded>
```

A route under a call with no fallback still means "fail, and route the failure".

A `!>` under a fan-out or join line (`*> |A| & |B|`, `-> [A] & [B]`) guards each
awaited member: when one member fails, the route fires. A failure does not cross an
unawaited hop (a `~>` send, a stream): it stops at the receiver, which routes it
itself (see "Streams, generators, backpressure").

**Capabilities:**
```
[User]   -> |UserDB|   @cap(read)
[Admin]  -> |UserDB|   @cap(read,write)
[AuthSvc]              @grants(session)
|PaymentDB|            @requires(write,pci)
```

**Resource ownership** — block-scoped acquire/release:
```
[Handler] @owns |Conn| {
  [Handler] -> |Conn| : query => {Rows}
}   # |Conn| released at block exit
```

---

## Modes

```
#!spec       # binding — every element is a constraint, holes are errors
#!sketch     # partial — holes allowed, defaults assumed
#!craft      # work-in-progress — collaborative authoring, holes expected,
             # agent actively surfaces gaps and proposes structure
```

Mode declaration goes on the first non-empty line of the document. `#!craft` documents should normally be promoted to `#!spec` or `#!sketch` when authoring concludes — craft is a process mode, not a resting state.


---

## Checks

Lint asks whether a document is well formed; the **composition checks**
(`check.py`, rules `SGCnnn`, [RFC 0003](./rfcs/0003-composition-checks.md)) ask
whether it says how its risks are handled — an external call with no `@timeout`, a
retry on a write with no idempotency, two writers on one store, a failure with no
route, an event nothing handles, a state machine that can get stuck. A finding never
forbids a shape; it names a risk the document leaves undeclared. A design that
declares its risks passes, however unusual its shape.

**Modes decide severity; tiers cap it.** There is no strictness switch beyond the
mode line. Each rule has a tier, because some principles are judgement calls:

| Tier | `#!sketch` | `#!craft` | `#!spec` |
| --- | --- | --- | --- |
| **binding** | info, hidden | warn, asked as a question | **error** |
| **advisory** | info, hidden | warn, asked as a question | warn |
| **hint** | not emitted | info, asked as a question | info |

In `#!craft` each finding is the question a reviewer would ask ("`charge` is retried
×3. Is it idempotent, and on what key?"); in `#!spec` it is a statement followed by
the declarations that would satisfy it. A finding built on a guess (a payload read
as a write, a name-based pairing) drops one tier and says what it guessed; a finding
whose every witness needs two or more simultaneous failures caps at warn. A fragment
with no mode line is checked as `#!sketch`.

**Running them.** `check.py FILE` prints the findings in lint's format
(`severity:line:SGCnnn: rule-name: message`), exit 0 / 1 / 2 like lint.
`--mode sketch|craft|spec` checks as another mode; `--all` also prints the hidden
findings; `--k N` sets how many failures one simulated run combines (default 1 in
sketch and craft, 2 in spec); `--json` prints one object with each rule's tier, why
it matters, how to satisfy it, and the witness scenario; `--rules` lists every rule
with its tier. `lint.py FILE --deep` runs lint and the checks together and merges the
two reports into one list sorted by line, with the acknowledged findings last as
`accepted:` lines; its exit code is the worse of the two. Fix lint errors first: a
malformed line can explain a finding. `view.py FILE --checks` (live key `c`) marks
the findings on the drawing in every view (graph, tree, flow).

**Three sources of rules.** *Structural* rules read the wiring (call policy, store
access, failure routes, state machines, cycles, bounds). *Behavioural* rules read the
simulator's runs of the design (`view.py --sim`), exploring single and combined
failures: races on a store, joins that stall, events a machine drops, orders a
machine cannot absorb. *Invariant* rules check the document's own `@inv` lines where
the head is a recognised one (see "Recognised invariants" under "Invariants,
capabilities, resource ownership"); any other `@inv` is listed as unchecked, never
failed. A dialect can add rules and `@inv` heads of its own (see "Dialects").

**A finding is resolved in one of two ways only:**

- **declare** the handling in notation the language already has — `@timeout(t)`,
  `@deadline(t)`, `×N` with `@after(…)`, `@fallback(x)`, a `!>` route, a recognised
  `@inv` (`idempotent(key)`, `atomic(…)`, `cas(field)`, `depth <= N`, …),
  `@owns |S|`, `@read(…)` / `@write(…)`, a `^N` bound, an `@sla`, a `?>` exit, a
  terminal state `$`, a consumer for an event — whatever is true of the system;
- or **acknowledge** an accepted risk with a comment: `# accepts: rule-name — the
  reason` (one or more rule names, then `—`, `--` or ` - `, then the reason).

```
#!sketch
[API] -> [Payments] : charge({Order}) ×3 @timeout(2s)   # accepts: retry-without-idempotency — charge is an upsert on order_id
```

An acknowledgement anchors by line: trailing the line, on the line(s) directly
above a statement, on or above a block's header or its `}` (the whole block), or
before the first statement and separated from it by a blank line (the whole
document). The reason is required. An acknowledged finding is listed as `accepted:`
with its reason and no longer counts toward the exit code. Three meta rules keep the
valve honest and cannot themselves be acknowledged: `ack-unknown-rule` (a mistyped
rule name; a warn even in `#!sketch`), `ack-without-reason` (the acknowledgement is
void) and `ack-unused` (it no longer matches a finding — delete it). Rule names are
kebab case; people write the name, never the `SGCnnn` id.

`#=` is **reserved** for a later decorated form of the same acknowledgement
(`#= retry-without-idempotency — upsert on order_id`). Until that form lands it
acknowledges nothing, lint notes any `#=` (SGL188), and a dialect may not claim it
as a comment marker.

**Never reshape the design to make a finding go away** — removing a call, a writer,
a retry or a branch, merging components or rerouting flows is a design change for
its author to choose, not a fix. Each finding names declarations, not rewirings.
examples.md "Example Q" shows a risky design and its declared twin; the full rule
catalog, with a flagged and a declared example for every rule, is
[rfcs/0003-composition-checks.catalog.md](./rfcs/0003-composition-checks.catalog.md).

---

## Sigil Normal Form (SNF)

Canonical ordering. Two documents in SNF can be diffed line-by-line for structural comparison.

**Document order:**
1. Mode declaration (`#!spec` / `#!sketch` / `#!craft`)
2. Any dialect-defined document header blocks (see "Dialects"), in the order the dialect specifies
3. Alias cluster (role / type definitions)
4. Sections in strict **L1 → Lk** order (general → specific, depth increases down the file)

**Within each section:**
1. Standalone entity declarations
2. State / lifecycle blocks
3. Primary sync flow (topological: source → sink)
4. Async flows (`~>`)
5. Error paths (`!>`) (`!>` continuation lines stay directly under the flow they attach to)
6. Invariants, SLAs, capabilities (if not inline)

Always emit `compress` and `tighten` outputs in SNF.

---

## Skeleton form (for comparison)

Strip names to `_`, keep glyphs, arrows, and structure:

```
Original:  (User) -> [API] -> [Auth] -> |UserDB| => {Session}
Skeleton:  (_)    -> [_]   -> [_]    -> |_|      => {_}
```

Two documents with identical skeletons are structurally isomorphic.

---

## Dialects

Core Sigil is deliberately small and host-agnostic. A **dialect** is a named
extension of it for a particular host or toolchain — the vocabulary a specific
code generator, runtime, or UI surface needs to read a design without guessing.
A dialect **adds**; it never changes the meaning of core syntax:

- **Vocabulary.** New modifiers (e.g. tags that route a value to a particular
  concern), new statement or block keywords, new line-leading markers or glyph
  forms, and extra composition-tree relations (for example layout relations for a
  UI host).
- **Rules.** Extra lint rules, including rules that *tighten* core leniency (for
  example, "every value payload in this dialect must carry a concern tag").
- **Renderer hooks.** Pre-processing so that dialect-only lines render sensibly
  (or are stripped) in diagrams.
- **Rule packs.** Extra composition checks for `check.py` (see "Checks"), extra
  recognised `@inv` heads, and extra read verbs. A pack's rules use the dialect's
  own id prefix and never reuse a core rule's id or name, its heads never redefine
  a core head, and a dialect may not claim a comment marker the core reserves
  (`#=`).

The dialect's own document is the authority on its vocabulary; it names the core
sections it extends. A dialect's grammar is an **addendum** to the core formal
grammar below — it extends `stmt`, `entity`, `mod`, and `payload`, and adds its
own productions.

**Selecting a dialect.** The reference tools (`lint.py`, `render.py`, `check.py`
and the viewer) take `--dialect NAME`, defaulting to the environment variable
`SIGIL_DIALECT`. A dialect is found by name next to the core package
(`../sigil-<name>/dialect.py`), in any directory on `SIGIL_DIALECT_PATH`
(`os.pathsep`-separated; a `sigil-<name>/dialect.py` or `<name>/dialect.py` inside
it), or by passing a path to the dialect module directly. An unknown name is an
error, not a silent fallback.

**Without a dialect** the tools lint and render pure core Sigil. Dialect
vocabulary that appears in a core-only run gets no special treatment — it is
reported the way any unfamiliar token is (for example an unknown modifier is an
informational `SGL040` note), and no dialect rule runs. Core documents,
including the examples in this file and `examples.md`, lint clean with no dialect
selected. Core tools never depend on any dialect.

---

## Worked examples

The following are inline reference examples. For a longer collection of prose↔Sigil pairs, see `examples.md` in this directory.

### Example 1: Simple request-response
```
(User) <-> [API] <-> |DB| : {Result}
```

### Example 2: Auth with async audit
```
(User) -> [Auth] : {creds}
[Auth] -> |UserDB|
       => ~{Session}   # ttl 24h
       !> <Unauthorized>
[Auth] ~> <LoginEvent> -> |AuditLog|
```

### Example 3: Parallel checkout with strict join + compensation
```
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

### Example 4: Stream pipeline with backpressure
```
[Ingest]       => *<Raw>^10k@drop
*<Raw>         -> [Parse]    => *<Parsed>^10k
*<Parsed>      -> [Enrich]   => *<Enriched>^10k  @sla(p99<50ms)
*<Enriched>    *> |Warehouse| & |RealtimeIdx|
               !> |DLQ|
```

### Example 5: State machine + worker loop
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

loop @while |Q|.nonempty {
  [Worker] @owns |Conn| {
    [Worker] -> |Q| : pop => {Job}
    [Worker] -> run({Job}) => <ok> !> <fail>
    [Worker] ~> <metric> -> |Obs|
  }
}
```

### Example 6: Multi-level zoom
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

---

## Common pitfalls

1. **Using the wrong glyph.** Components (`[X]`), data (`{X}`), events (`<X>`), actors (`(X)`), stores (`|X|`) are all distinct. An order record is `{Order}`; a service that processes orders is `[OrderProcessor]`; the event that fires when an order is placed is `<OrderPlaced>`. Do not use `{Order}` for the service.

2. **Using actor glyphs `(X)` for states, tags, or attributes.** Parentheses denote external actors — users, third-party systems, things outside the bounds of the system being described. They do NOT denote lifecycle states, entity flags, or tags. Wrong: `(live) (disputed) (retracted)` to list states. Right: a `state {Entity} { ... }` block with named states and transitions. If a user writes states in parens during `craft`, correct the glyph kind immediately.

3. **Confusing `->` with `=>`.** `->` is a call/request (A invokes B). `=>` is a return/produces (A yields X). `[API] -> [DB] => {Rows}` means "API calls DB, which returns Rows."

4. **Forgetting arrow semantics.** `~>` is async; do not use `->` for fire-and-forget. `!>` is error path; do not mix it into the happy path. Error paths attach to the most recent flow as continuation lines.

5. **Mixing up `*` uses.** `*<X>` (stream), `*>` (broadcast), `×N` (cardinality) all use `*` or similar but mean different things. Streams are temporal, broadcast is topological, cardinality is a count.

6. **Using `&` without understanding it means strict join.** Bare `A & B` means both must succeed. For race/first-wins, use `&?`. For fire-and-forget, use `~>` twice or `parallel @none`.

7. **Overfitting L1.** The top level should be scannable in seconds. Do not pack implementation detail into L1 — that belongs in L2+ expansions via `:= { ... }`.

8. **Mode mismatch.** In spec mode, holes (`[?]`, `{?}`, etc.) are errors — do not use them. In sketch mode, they're encouraged to mark known gaps. Always include a mode line at the top.

9. **Forgetting the continuation rule.** When a line starts with an arrow, it inherits only the subject of the previous line. `[Auth] -> |UserDB|` followed by `       => {Session}` means `[Auth] => {Session}`, not `|UserDB| => {Session}`.

10. **Inventing details during expansion in spec mode.** If the Sigil doesn't specify something, spec-mode prose must say "unspecified." Do not fabricate defaults.

11. **Not producing SNF output.** When the user asks for `compress` or `tighten`, always emit in Sigil Normal Form: mode first, aliases clustered near top, sections L1→Lk, statements within sections ordered entity→state→sync→async→error→constraints.

12. **Encoding algorithms or data-structure internals.** Sigil describes the wiring between components, not their internals. If a user asks "how should `[Sorter]` sort?" the answer is not more Sigil — it's prose or code. Declare `[Sorter]` with its inputs/outputs and treat its internals as opaque. This boundary is what keeps Sigil language-agnostic.

13. **Mode declaration with trailing text.** The mode line is exactly `#!spec`, `#!sketch`, or `#!craft` — no title, no name after it. A document title belongs in a section header: `--- System Name ---`. Wrong: `#!spec agent-memory`. Right: `#!spec\n\n--- agent-memory ---`.

14. **Writing prose verbs inside flow lines.** Every connector between glyphs must be an arrow (`->`, `~>`, `=>`, `!>`, `?>`, `*>`, `<->`). Do not write English verbs like "excludes", "surfaces", "returns", "calls", "reads" as if they were operators. Wrong: `[MCP] excludes (superseded) ∪ (retracted)`. Right: model the filter as an invariant (`[MCP] @inv excludes({Entity}.state ∈ {superseded, retracted})`), a branch, or a comment — never inline prose posing as notation.

15. **Inventing keywords or modifiers.** The core spec defines the full core vocabulary: the five glyphs (with holes `?`, wildcard `_`, generics, the `~` mutability and `*` stream prefixes), the closed arrow set, the modifiers (`@inv`, `@sla`, `@cap`, `@owns`, `@borrow`, `@timeout`, `@after`, `@deadline`, `@fallback`, `@grants`, `@requires`, `@loc`, `!`, `?`, `.field`, `×N`), the **call-resilience** trio (`@timeout` · `×N` · `@fallback` — a call's error policy, see "Call resilience"), the **composition-tree** branches (`\-` with relation `>` `&` `?` `$` `@` `!` `=` `_`, the `*-` spawn, `(N)-` weight and `{cond}-` prefixes, and qualified paths `[A]/{B}` — see "Composition trees"), the **permission-graph access modifiers** `@read(…)` / `@write(…)` (principal lists on a store — see "Permission graph"), the payload forms (entity glyph, internal op-call, value literal / `${ref}` / map / list / `"""…"""` block-string, the value operators `++` `||` `+ - * /`, and the external-op **`op`** keyword — see "Payloads & values"), the stream bound `^N@policy`, the structure tokens (`:=`, `name { … }`, section headers, `/`, `&`, `&?`), mode lines, and the control blocks (`state`, `loop`, `parallel`, `branch`). Do not invent new ones — no `composes:`, no `@notify`, no `@reacts`. **For the permission graph specifically, do NOT invent a `swarm`/`agents`/`acl` block, an `agents:` roster key, or a topology/control-policy keyword** (`flat`/`hierarchical`/`coordinated`/`single-owner`/`lww`): the topology and write-discipline **emerge** from the `@read(…)` / `@write(…)` edges and their cardinality (one writer ⇒ single-owner, many ⇒ shared), delegation is `@borrow`, and dynamic membership is a generic role. Local-component composition is `:= { ... }`. Async emission is `~>`. **Dialects extend this vocabulary** (see "Dialects"): a dialect's own document lists what it adds, and that vocabulary is valid only when the dialect is selected — do not use it in a core document, and do not invent vocabulary a dialect doesn't define either. If a concept genuinely lacks notation, demote it to an inline comment (`# ...`) rather than inventing syntax.

16. **Statement separators.** Sigil has no `;` — each statement is on its own line. Inline conditionals use `?>` or `branch on X { ... }`. Wrong: `Δhash -> re-render ; =hash -> reuse`. Right: a `branch on {Concept}.hash { … }` block with one arm per line (`changed => …`, `_ => …`), or two separate statements.

17. **Same glyph appearing twice in a linear flow.** When the same component plays two roles (e.g., `[MCP]` as read-hydrator and write-validator), a line like `|DB| -> [MCP] -> ... -> [MCP] -> |DB|` is ambiguous — the reader can't tell the two calls apart. Either (a) use role-qualified names (`[MCP.read]` / `[MCP.write]`) at L1, or (b) accept the ambiguity at L1 and disambiguate via `:= { ... }` expansion at L2. The second is usually cleaner.

18. **Referencing entity states inline with new syntax.** To filter on or predicate over an entity's current state, use the existing `.field` accessor: `{Fact}.state = live`, `{Order}.status ∈ {pending, active}`. Do NOT invent new glyph shorthands like `{Fact}#live` or `{Fact}@state=live`. The state itself is defined in a `state { ... }` block; predicates reference states via the standard accessor.

19. **Using flows for composition (or branches for calls).** "The ship has a health component" is structure: `[Ship]` with `\-& {Health}` beneath it — not `[Ship] -> {Health}`, which says the ship *calls* or *sends to* its health. Conversely a branch never carries traffic: to say a system updates a component, write the flow (`[Combat] -> {Health}`). The traffic-shaped relations are still structure: `\-*-= [ShardQuery]` says the search service is made of shard queries whose results it gathers, `\-(3)-> [ZoneA]` says zone A takes three shares, `\-_ [PrimaryPsp]` says one of the siblings is active — the calls themselves remain flows. To reach one occurrence of a repeated name, use a path (`[Bullet]/{Transform}`), not a renamed glyph.

---

## Formal grammar (compact)

The core grammar. A dialect's grammar addendum extends `stmt`, `entity`, `mod` and
`payload` and adds its own productions (see "Dialects").

```
doc         := mode? stmt*
mode        := '#!spec' | '#!sketch' | '#!craft'
stmt        := entity | flow | alias | block | state-block
             | loop-block | parallel-block | branch-block
             | section | note | comp-tree

entity      := GLYPH (name | '?' | '_') generics? (':' type)? (mod)*
generics    := '<' name (',' name)* '>'

section     := '---' ('L' INT ':')? title '---'
note        := '#' char*                              # inline / whole-line comment
                                                      # `#=` is reserved (see "Checks")

flow        := src arrow dst (':' payload)? (mod)*
             | arrow dst ...              # continuation (inherits subject only)
src         := entity | path              # a bare name = every occurrence; a path = the
dst         := entity | path | op-target  # occurrences it matches
op-target   := int-op-call | ext-op-call  # a self-call: the subject runs the op itself
arrow       := '->' | '~>' | '<->' | '=>' | '!>' | '?>' | '*>' | '→'

mod         := '@' name ('(' arg (',' arg)* ')')?     # @inv @sla @cap @grants @requires
                                                      # @owns @borrow @loc @timeout @after
                                                      # @deadline @fallback @read @write
             | ('×' | 'x') N | '!' | '?' | '.' name
             | fallback-mod | access-mod | borrow-mod

# Call resilience — `@timeout`/`×N`/`@fallback` form a call's error policy.
# `×N` trailing a call payload is a retry count; glued to a glyph (`[App]×3`),
# on a node, or trailing a payload-less flow it is cardinality.
# `@fallback(x)` is the recovery payload on final failure.
fallback-mod:= '@fallback' '(' (value | int-op-call | ext-op-call) ')'

# A payload is structural (an entity or internal op-call) or a value.
payload     := structural | value-payload
structural  := entity | int-op-call               # entity glyph or internal op-call
int-op-call := name '(' (arg (',' arg)*)? ')'      # bare verb — internal dispatch
value-payload := value | ext-op-call
ext-op-call := 'op' dotted-name '(' (arg (',' arg)*)? ')' # external, host-provided
dotted-name := name ('.' name)+                    # host-provided op ns.verb

value       := literal | ref | value op value
literal     := 'true' | 'false' | INT | FLOAT | STR | 'null'
             | '[' (value (',' value)*)? ']'        # list literal
             | '{' pair (',' pair)* '}'             # map literal (top-level ':')
pair        := name ':' value
ref         := '${' path '}'
op          := '++' | '||' | '+' | '-' | '*' | '/'  # closed; top-level only

# A STR literal is single-line `"…"` OR the multiline triple-quoted block form
# `"""…"""` — sigil's ONLY multiline construct (a tightly-scoped block-aware
# linter path; an unterminated `"""` → SGL170). `${…}` inside the block is NOT
# substituted by sigil — it carries the template text + names the refs; the
# consumer assembles.
STR         := '"' char* '"' | '"""' any* '"""'    # single-line | multiline block

# Disambiguation: a `{…}` payload is a MAP LITERAL iff its body has a top-level
# `:` (key/value pairs), e.g. `{retries: 3}`; otherwise it is the DATA-GLYPH
# `{X}` (entity). Every bare-identifier `{X}` stays an entity.

alias       := name ':=' (expr | '{' stmt* '}' (mod)*)
block       := name '{' stmt* '}' (mod)*
# Any block's closing `}` may carry modifiers for the whole block
# (`} @deadline(3s)`, `} @inv terminates`); an expansion's go to its entity.

comp-tree   := entity (INLINE-BRANCH)? NL branch+     # children indented deeper than the parent
branch      := INDENT '\\-' spawn? (weight | cond)? rel entity (flow-tail)? NL branch*
             | INDENT '\\-*' entity NL branch*        # bare spawn, default relation
spawn       := '*-'
weight      := '(' INT ')-'                           # relative share among siblings, not a count
cond        := '{' name '}-'                          # name: [A-Za-z0-9_-]+
rel         := '>' | '&' | '?' | '$' | '@'             # contains · has · when · from data · attached
             | '!' | '=' | '_'                         # alerts when · gathers · one of
                                                      # a dialect may add relations
# Depth is indentation. A branch adds no flow edge; flows wire the tree separately.

path        := entity ('/' entity)+                   # no spaces around '/'; each step is a direct
                                                      # parent→child branch; matches as a suffix of an
                                                      # occurrence's ancestor chain (SGL112 if none)

state-block := 'state' entity '{' trans* '}' (mod)*   # any glyph owns the machine
trans       := (name | '+' | '_') '-<' name '>->' (name | '$') (mod)*

loop-block     := 'loop' loopmod '{' stmt* '}' (mod)*
loopmod        := '@each' name 'of' expr | '@while' expr
                | '@until' expr | '@times' N

parallel-block := 'parallel' ('@all'|'@any'|'@none') '{' stmt* '}' (mod)*

branch-block   := 'branch' 'on' expr '{' arm* '}' (mod)*
arm            := (name | '_') '=>' flow

# Permission graph — access edges on a store, as `@`-modifiers carrying a `( )`
# comma-list of principal entity names (the modifier-family arg form: parens, not
# `{ }`). Topology / write-discipline EMERGE (no keyword).
access-mod  := ('@read'|'@write') '(' principal (',' principal)* ')'
principal   := name                                   # a declared entity OR a generic role name
access-kind := 'read' | 'write'                       # narrowing arg on @borrow only
borrow-mod  := '@borrow' ('(' access-kind ')')? (STORE | name)   # lend access down (child ⊆ parent)
# `@read`/`@write`/`@borrow` join the (mod)* family on an entity/store. `@write(x)`
# (one) ⇒ single-owner; many ⇒ shared. A `( )` list member naming a generic
# role stands for every current member of that role.

stream      := '*' entity ('^' N ('@' policy)?)?
policy      := 'block' | 'drop' | 'latest' | 'err'
```

GLYPH ∈ `{ [ ( { < | }`, matched by its closing counterpart.

---

## What Sigil deliberately doesn't do

- **No algorithm or data-structure notation.** Sigil describes wiring between components, not what happens *inside* one. A component `[QuickSort]` is a valid glyph; its recursion depth, partition strategy, or complexity bound is not Sigil's concern. If the user asks to encode an algorithm, direct them to prose or code — Sigil stays language-agnostic by keeping implementation internals opaque.
- **No execution semantics** (no runtime, no types beyond declaration). `view.py --sim`
  walks a design's pathways for a reader — tokens along the flows, one scenario at a
  time (happy path, each failure route, branch arm, race) — but its choices (written
  order, bounded loops and recursion, the first member wins by default) are the
  viewer's reading, not part of the language.
- **No schema syntax for data *entities*** — a `{X}` entity payload is named, not schema'd; expand it elsewhere if you need a full record shape. (A payload *may* carry a concrete **value** — a literal/ref from the closed value vocabulary; see "Payloads & values". That is a value, not an entity schema.)
- **No absolute layout / visual coordinates** — Sigil is textual; placement is the renderer's concern. (A dialect may describe **relational** layout intent; none names coordinates or pixel sizes.)
- **No module/import system** — use `:=` expansions and section headers for scoping.
- **No reverse arrow** — all flows written source-to-sink.

If you reach for one of these, the answer is usually "write prose" or "generate a diagram from the Sigil" — not extend Sigil.

---

## On the name

The language is called **Sigil** — always and globally. The name is the compressed form; treat it as a proper noun, not an acronym.

If pressed for an expanded meaning, Sigil unpacks to **S**ymbolic **I**ntent **G**lyph **I**ntermediate **L**anguage — the uncompressed intent of the name itself. This is a deliberate meta-reference: even the name obeys the compress/expand semantics of the language. Do not lead with this expansion in documentation or conversation — Sigil is the real name. The acronym is a footnote, available when someone asks what the name "stands for."
