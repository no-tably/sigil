# RFC 0003 catalog — composition checks

The full rule catalog for [RFC 0003](./0003-composition-checks.md). Status: Proposed
2026-10-02, together with the RFC. It was drafted against main @ 8a2aeea and revised
against an 86-point review (lenses: *never limits*, *computable*, *completeness*);
the review log is the last section. Nothing here is implemented yet.

References to `survey-*.md` and "corpus §n" point to the research notes the catalog
was written from; they are not part of the repository. Each rule entry says in words what model fact
or fix a gap id (MG, NG, CG) or defect id (B) stands for, and §1.5 and §6 list the
new facts and the defects, so the catalog reads on its own.

**How to read gap references.** The three surveys number their gaps separately, so
this file uses prefixes:

- **MG1..MG16** are model gaps from survey-model.md §2.
- **NG1..NG8** are notation gaps from survey-principles.md.
- **CG1..CG7** are gaps this catalog adds (listed in §1.5).
- **B1..B13** are tool defects (listed in §6).

Corpus citations use `file:line`. Examples.md citations use the examples.md line
number. "Example n" means language.md's worked example n.

---

## 0. Summary for review

| Id | Name | Layer | Tier | Phase | Corpus hits |
|---|---|---|---|---|---|
| SGC001 | ack-unknown-rule | meta | binding | P1 | — |
| SGC002 | ack-without-reason | meta | binding | P1 | — |
| SGC003 | ack-unused | meta | advisory | P2 | — |
| SGC004 | policy-in-prose | meta | hint | P1 | site 02:13, site 01:8 |
| SGC090 | exploration-incomplete | meta | hint | P3 (loop part P2) | coverage loop caps |
| SGC101 | unguarded-call | static | binding (op) / advisory (actor) | P2 | examples.md:497–498 |
| SGC102 | retry-amplification | static | advisory | P2 | probe only |
| SGC103 | timeout-budget-inverted | static | binding | P2 | probe only |
| SGC104 | retry-without-backoff | static | advisory | P2 | site 05:11 |
| SGC111 | retry-without-idempotency | static | binding | P2 | examples.md:49, site 01:8 |
| SGC112 | duplicate-delivery | static | advisory | P2 | probe only |
| SGC113 | dual-write | static | advisory | P2 | probe only |
| SGC114 | poison-message | static | binding (retrying) / advisory | P2 | (satisfied: examples.md:117) |
| SGC121 | saga-uncompensated | static | advisory | P2 | (satisfied: examples.md:52) |
| SGC122 | fragile-compensation | static | advisory | P2 | examples.md:52, executions:35 |
| SGC123 | race-loser-effects | static | binding | P2 | probe only |
| SGC131 | shared-writable-store | static | advisory | P2 | examples.md:814 (`\|Shared\|`) |
| SGC132 | undeclared-access | static | binding | P2 | examples.md:870 (FP check) |
| SGC133 | lost-update | static | advisory | P2 | examples.md:487–488 |
| SGC134 | held-across-call | static | advisory | P2 | probe only |
| SGC135 | stale-read | static | advisory | P2 | examples.md:750–751 |
| SGC136 | shared-data-order | static | hint | P2 | site 03:20–21, examples.md:589–591 |
| SGC141 | unreachable-state | static | binding | P2 | — |
| SGC142 | dead-end-state | static | hint | P2 | site 04 `Settled`, `Cancelled` |
| SGC143 | ambiguous-transition | static | binding | P2 | — |
| SGC144 | no-exit | static | advisory | P2 | — |
| SGC145 | orphan-event | static | hint (advisory when escalated) | P2 | examples.md:22, 408–409 |
| SGC146 | undriven-transition | static | hint (advisory when escalated) | P2 | examples.md:389, coverage:108 |
| SGC147 | wait-without-timeout | static | advisory | P2 | coverage:108, site 04 `Open` |
| SGC148 | wildcard-leaves-terminal | static | advisory | P2 | examples.md:72 |
| SGC151 | unbounded-recursion | static (+trace witness) | advisory | P2 / P3 | site 05:17, executions:28 |
| SGC152 | async-cycle | static (+trace witness) | advisory | P2 / P3 | examples.md:399–400 |
| SGC153 | unbounded-loop | static | hint | P2 | examples.md:537 |
| SGC161 | unbounded-buffer | static | advisory (hint for `~>`) | P2 | — (corpus streams all bounded) |
| SGC162 | unbounded-result | static | advisory | P2 | probe only |
| SGC163 | capacity-mismatch | static | hint | P2 | examples.md:149 |
| SGC165 | fanout-tail | static | advisory | P2 | examples.md:47–51 |
| SGC166 | single-point-of-failure | static | advisory (`!`) / hint | P2 | coverage:23, site 02:18–20 |
| SGC167 | unbounded-spawn | static | advisory (binding if recursive) | P2 | probe only |
| SGC171 | dependency-cycle | static | advisory | P2 | — (FPs excluded) |
| SGC172 | expansion-escape | static | advisory | P2 | — |
| SGC173 | lock-order-cycle | static | binding | P2 (declared order P4) | probe only |
| SGC174 | optional-callee | static | hint | P2 | coverage:63 |
| SGC175 | unreached | static | hint | P3 (gated on B4) | coverage:82, 194–197 |
| SGC201 | unhandled-failure | static (+trace witness) | binding | P2 / P3 | examples.md:497, executions:41 |
| SGC202 | dead-failure-route | static (+trace witness) | binding / advisory | P2 / P3 | **site 05:12** |
| SGC203 | event-ignored | trace + static diamond | binding | P3 | **coverage:119–121**, examples.md:388–412 |
| SGC204 | race | static + trace | binding | P2 (static) / P3 (trace) | examples.md:480–481 |
| SGC205 | ordering-unstated | trace + static | advisory | P3 | site 04:7–8 |
| SGC206 | stalled-join | trace | binding | P3 (after the join decision) | probe (§3) |
| SGC301 | inv-unchecked | invariant | hint | P4 | examples.md:159, 403–425 |
| SGC302 | inv-dangling | invariant | advisory | P4 | — |
| SGC303 | inv-contradicted | invariant | binding | P4 | — |
| SGC304 | layer-inversion | invariant | binding | P4 | — (needs `@inv layers`) |
| SGC306 | timeout-below-sla | invariant | advisory | P4 | — |

There are 55 core rules: 5 meta, 39 structural, 6 behavioural and 5
declared-invariant rules. Ids **SGC105** (`unbroken-dependency`) and **SGC164**
(`shared-pool`) left core for a dialect rule pack (§11), and **SGC305**
(`lock-order-violated`) merged into SGC173. Those three ids are retired, never
reused.

Since the revision, SGC201 and SGC202 have an exact *static* detector (the
`failure_flow` fact, §1.5 CG7), and the trace only names a witness scenario. Their
ids stay in the 2xx block so the numbering the first review saw does not churn; ids
are frozen once released, and none is released yet.

The rules with the strongest corpus evidence are SGC202 (site 05), SGC203
(coverage), SGC101, SGC111 and SGC204.

---

## 1. Conventions shared by every rule

### 1.1 Identity

- **Id.** The id is `SGC` plus 3 digits, and it never changes once released. The
  hundreds digit gives the layer: `0` meta, `1` structural, `2` behavioural and `3`
  declared invariants. The tens digit gives the family:
  - `10` calls
  - `11` delivery
  - `12` sagas
  - `13` shared state
  - `14` state machines
  - `15` termination
  - `16` load
  - `17` structure
- **Name.** Each rule also has a kebab-case name, unique and stable. The name is what
  people type: an acknowledgement cites the name, never the id. `SGL` stays the prefix
  for syntax (lint). Dialect rule packs pick their own prefix and must not reuse a
  core name.
- **One risk, one name.** Some risks have a static detector and a trace detector.
  Those rules keep a single name and id, so one acknowledgement covers both detectors
  (SGC151, SGC152, SGC201, SGC202, SGC203, SGC204 and SGC205 work this way).

### 1.2 Severity: tiers × modes

Decision 1 says severity follows the mode. Each rule also gets a **tier** that sets
its ceiling. The tier exists because some principles are opinions, and making them
errors in `#!spec` would limit what can be built.

| Tier | `#!sketch` | `#!craft` | `#!spec` |
|---|---|---|---|
| **binding** | info, hidden | warn, asked as a question | **error** |
| **advisory** | info, hidden | warn, asked as a question | warn |
| **hint** | not emitted | info, asked as a question | info |

**This table amends Decision 1** (which reads "spec findings are errors"): only
binding findings become errors, advisory ones stay warnings and hints stay info. The
amendment needs the user's explicit sign-off at the P0 gate; RFC 0003 lists it as
open question 1.

Adjustments to the tier:

- **Guess downgrade.** A finding that rests on a heuristic drops one tier. Examples
  are a read/write guess (MG2), pairing an operation with its compensation by name,
  and an edge `×N` read as a retry before CG1 lands. The message then says what the
  guess was ("this flow looks like a write"). An explicit `@read(…)` / `@write(…)` or
  other declaration makes the finding exact again.
- **Deviation depth cap.** A trace finding whose every witness needs k ≥ 2
  deviations caps at warn, whatever its tier. Only findings with a happy-path or
  k = 1 witness may be errors.
- **Behavioural rules warn-only until fixed.** Until B1–B4 (§6) are fixed and their
  regression fixtures pass, every finding whose evidence comes from a trace caps at
  warn. The static detectors of SGC201, SGC202 and SGC204 are not affected.
- **No mode line.** A fragment with no mode line is checked as `#!sketch`. That is
  lint's default reading, and it keeps the examples.md fragments quiet.

Every rule carries an **ask**. In `#!craft` the ask is the message, phrased as a
question. In `#!spec` the message is a statement, and the ask follows as the "how to
satisfy" text.

### 1.3 Finding record

Line output is lint-compatible: `severity:line:SGCnnn: name: message`. The rule
field stays one token, and the name leads the message. `--json` adds the following
fields to lint's `{severity, line, rule, message}`:
`name, tier, mode, anchor {node|wire|block|machine, id}, why, fix, guess (bool),
k (deviations of the witness, trace rules only), witness (scenario name or null),
acknowledged (reason|null), also ([folded findings], §1.7)`. These are the optional
Diagnostic fields from MG15, and the playground can show them without changing its
format. Acknowledged findings are listed separately and do not count toward the exit
code.

**Determinism.** Traces are deterministic (no clock, no randomness; tasks advance in
id order each tick; choices come only from the Scenario), and happens-before race
detection does not depend on the scheduler, so no interleaving search is needed. Two
things are kept stable on purpose:

- findings are sorted by `(line, id, anchor)`, and a witness is chosen by the
  deterministic scenario order, never by iterating a set (Python string-set order
  depends on `PYTHONHASHSEED`: route guard frozensets, `Frame.taken`/`failed`);
- the `Limits` in effect (depth, visits, iterations, spawn, scenario and trace
  budget, k) are printed in `--json` output and on every SGC090 line, because
  findings depend on them.

A test runs check.py twice under different `PYTHONHASHSEED` values and compares the
output byte for byte.

### 1.4 Shared model vocabulary (used by the queries below)

Every query works over three objects, built once per document:

- `sc  = sim.canonical(graph)`: the canonical Scene (every unit, events as nodes,
  triggers to states), so checks agree with the simulator.
- `sca = scene.build_scene(graph, access=True)`: the same with access wires.
- `prog = sim.program(sc)`.

The terms below are used throughout:

- **machine wire.** A wire whose `owner` unit has `graph.role == "state"`. Machine
  wires are excluded from every call, cycle and path query, because corpus §3.7 shows
  them appearing as false cycles.
- **call wire `w`.** `w.role == "flow"`, `w.kind in ("->", "<->")`, not a machine
  wire, and either `w.call is not None` or `sim.returned(w) is not None`.
- **external call.** A call wire with `w.call.external` (`op ns.verb(…)`), or one whose
  destination is an actor and that *returns* (`sim.returned(w)` is not None, or the
  kind is `<->`). A plain `-> (Actor)` with no return is a notification, so it is
  never an external call. This excludes the corpus §3.1 false positives (replies to
  actors).
- **emit.** In the canonical scene (`events="nodes"`) an emit is a wire whose
  destination node has kind `event` (`~>` into an event, `=> <E>`, `!> <E>`), plus,
  once B12 lands, `=> <E>` call returns and tree alerts `\-{c}-! <E>`. There is no
  role `emit` in the canonical scene.
- **policy(w).** The modifiers that govern one call: `Wire.mods` plus
  `Edge.src_mods` (**MG3**), exposed as `scene.call_policy(w)`. Until MG3 lands, a
  `@timeout` / `@deadline` / `@fallback` in the *source node's* `Node.mods` also
  counts (accepting a few false negatives). **A `×` in `Node.mods` is never read as
  a retry**: `[A]×3 -> [DB] : write()` and `[A] ×3 -> …` both put `("×","3")` on
  node A, and `sim._setup_instances` reads that field as an instance count, so it is
  cardinality.
- **retry(w).** The `×N` of `Wire.mods` (later `Edge.src_mods`) only, under the
  **retry reading**: the wire is a call wire with a payload and the `×` trails the
  payload. A `×N` glued to the destination glyph (`[App]×N`) is cardinality and
  moves to `Edge.card` with **CG1** (a P1 render change). A trailing `×N` on a
  payload-less flow (`[Api] -> [Shard] ×4`) is cardinality (§7.3, SGL187). Until CG1
  lands, every edge `×` is a guess.
- **attempts(w).** `sim.attempts(w, limits)` computed over policy(w), **except** that
  a symbolic `×N` makes the value *unknown*: the numeric rules (SGC102, SGC103) skip
  such paths instead of printing `Limits.spawn + 1`, a number the design never
  stated.
- **routes(n).** `prog.routes[(ui, n)]`, each with its guard (`sim._route_guard`;
  public under **MG4**).
- **can_fail / failure_flow.** `sim.failure_flow(prog)` (**CG7**) maps every
  `(ui, node)` to the set of failure guards that can arrive there. "Can fail" in any
  rule means a non-empty arriving set. It replaces "has a choice point" everywhere
  (SGC114, SGC121, SGC201, SGC202).
- **access_mode(w, graph).** `"read" | "write" | "rw" | "unknown" | None`
  (**MG2**). It needs `Graph.access`, so it cannot take the wire alone. In order:
  1. a declared `@read(P)` / `@write(P)` on the store for the wire's principal wins;
  2. a flow into a store followed by `=>` (a produced value) is a **read**;
  3. a flow into a store with **no payload** is **unknown** (`[Svc] -> |DB|` is how
     authors write "uses the DB"; language.md Example 2 `[Auth] -> |UserDB|` is a
     read);
  4. a flow into a store with a payload is a write, unless its op verb is one of
     `get read query fetch load find list scan lookup search count` (CG6, extendable
     by a dialect);
  5. `|S| -> X` and a `=>` out of a store are reads; `<->` is read and write.

  Steps 4–5 make the finding a guess (§1.2). **A rule that needs a write never fires
  on `unknown`.** At most, SGC131 gives one hint per store when the answer would
  change a finding (§2, SGC131 clause c).
- **effectful(w).** The wire writes a store (access_mode write/rw), is an external
  call, emits, or calls a node whose body (`prog.bodies`, transitively through aliases
  and expansions) contains an effectful wire. A node with no body and a non-read op
  verb is *possibly effectful*, which counts as a guess. **Direct effects** of a node
  are the effectful wires in its own flattened body, without the transitive step;
  SGC113 uses only those.
- **sync chain.** The static call graph over call wires and `prog.bodies`, descending
  through `prog.aliases` and `prog.expansions`, minus machine wires and minus replies
  (a wire whose destination is an actor that is a source of the same chain). **Awaited
  edges** count as sync: `*>` members (the sim always awaits them in `_group`), `&`
  join targets, `parallel @all` members.
- **async graph.** `~>`, `parallel @none` members, trigger wires and **spawn wires**
  (`\-*`, `*-` children, `=> [X]`), plus the bodies of the nodes they land on.
  Deadlines and failures never cross an async edge.
- **SCC.** Tarjan over the sync chain or the async graph, computed in check.py (MG7).
  Machine self-loops are removed before any machine SCC is computed.
- **arrivals.** The independent starts of work (MG9), stated as the **arrival model**
  (§7.10): actor flows, events with consumers and no emitter, stream sources, and
  nodes with no incoming wire that start work. Entry lines from the **same actor**
  are program-ordered; arrivals from distinct actors or distinct entries are
  concurrent.
- **concurrent(n).** The shared static predicate of SGC133, SGC204 (static half) and
  SGC167: `n` may run concurrently with itself when `n` or a node above it on its
  sync chain has cardinality (glued or tree `×N`, N > 1 or symbolic), a `\-*` / `*-`
  spawn, a generic role `Worker<N>`, is fed by a stream, or is reached from two or
  more concurrent arrivals. An actor entry alone does not make its chain
  self-concurrent (a design that names one user); SGC163 treats actor entries as
  unbounded for load only.
- **anchor line.** The line a finding reports and an acknowledgement matches. It is
  `Wire.line` for wires, `Block.lines[0]` for blocks, the transition's line for
  machine findings, `Access.line`, or the first line naming the node
  (`viewkit.node_lines`).

### 1.5 New model facts this catalog adds (beyond survey-model)

| Gap | What | Needed by | Smallest change |
|---|---|---|---|
| CG1 | Where a `×N` was written: glued to the destination glyph, or trailing the payload | SGC102, 104, 111, 163, 167 | **render change (P1)**: a glued destination `×N` goes to a new `Edge.card` (or onto the destination node so `_setup_instances` sees it); `Edge.mods` keeps meaning retries. Changes `sim.resilient`, attempts, scenario lists and goldens: the phantom choice point `Primary~>Replica:fails` (examples.md:141, language.md:961) goes away. |
| CG2 | Which statements are "the same request": an entry's episode with its sync chain | SGC121, 133, 135 | none; check.py derives it from `prog.bodies` |
| CG4 | Declared bounds compared with the simulator's | SGC151–153, SGC090 | **check.py only**: compare `@inv depth <= N` / `hops <= N` with `Limits` and the trace's limit events, report "bounded by design (N) vs simulator (depth 3)". sim.py stays unchanged, keeping its contract that declarations do not affect a run. |
| CG5 | Dead transitions caused by trigger narrowing | SGC145, SGC146 | `render.find_triggers` also returns the narrowed-away pairs (it drops them today) |
| CG6 | The read-verb list, the `×N` reading and the policy-in-prose word list as data a dialect can extend | SGC004, 111, 131, 204 | module constants in check.py, extended through the dialect hook (MG16) |
| CG7 | `failure_flow(prog) -> {(ui, node): set of arriving guards}` | SGC114, 121, 201, 202 | **sim.py**, beside the functions it mirrors: a may-fail fixpoint over bodies, regions, groups and callees that applies `_call_failed` (fallback absorbs), `_region` (relabels to the block), `_await` (today None; the member's guard after B1), `~>` (stops), stream and async edges (stop, after B13) and `_fire_routes` (guarded routes, else unguarded ones). A route is live iff its guard is selected for some arriving guard. Exact with respect to the sim. |

CG3 (entry order as a scenario parameter) was dropped: `Scenario(entries=…)` already
accepts an explicit node tuple (`_resolve_entries`).

### 1.6 Registry shape (leaves room for declarative rules, decision 3)

Each rule is a record, not a free-form function, so a later declarative front end
(rules written as Sigil patterns) can produce the same record:

```
Rule(id, name, layer, family, tier, ask, why, fix,
     match,        # static: pattern over sc/sca/prog -> candidate anchors
                   # trace:  predicate over (scenario, Trace, events)
     satisfiers,   # data: [(site, form)] that clear a candidate, where site is one of
                   # call | callee | store | block | machine | owner | document, and
                   # form is a modifier name, a recognised @inv head (§4), an arrow
                   # ("!>", "?>"), or a store kind ("~|", "*|")
     implies,      # data: [(rule, scope)] folded into this finding (§1.7)
     guess)        # which heuristics the match used
```

`satisfiers` and `implies` are data on purpose. Most of a rule's meaning is "this
shape, unless one of these declarations is present", and a declarative rule can
state that without code. Only `match` needs code today.

### 1.7 Suppression (one defect, one finding)

A cause rule may list `implies` edges. When a cause fires, a finding of an implied
rule at the same scope is **folded** into the cause's message as "also: …", is listed
under `also` in `--json`, and does not count toward the exit code. Acknowledging the
cause covers the folded findings.

| Cause | Folds | Scope |
|---|---|---|
| SGC146 (case 2: nothing drives the machine out of `+`) | SGC203, SGC205, SGC147 | that machine |
| SGC146 (any) | SGC147 | the undriven transition's source state |
| SGC131 | SGC204, SGC133 | that store |
| SGC204 | SGC133 | that (node, store) |
| SGC101 | SGC165, SGC134 | that call (the join or `owns` context goes into the 101 message) |
| SGC114 | SGC201 | that anchor (stream- or `~>`-fed node) |
| SGC202 | SGC145 | the event that is only the dead route's target |
| SGC151 | SGC171 | an SCC inside one component (SGC171 keeps cross-component SCCs) |
| SGC161 (`\|DLQ\|` clause) | SGC175 | that store |

The table is registry data, so a declarative front end can carry it.

---

## 2. Structural rules (static, over Scene / Graph / Program)

### Calls (SGC10x)

#### SGC101 `unguarded-call`
- **Risk.** An external call with no time bound can hang, and the caller hangs with
  it (blocked threads, then a cascade).
- **Principle.** Every integration point needs a timeout. Sources: Nygard, *Release
  It!* 2e, *Integration Points*, *Blocked Threads* and the *Timeouts* pattern;
  Deutsch, Fallacies of distributed computing.
- **Query.** Report every external call `w` where policy(w) has no `@timeout` or
  `@deadline` and the caller is not **covered**. `covered(n)` is a greatest
  fixpoint over the sync chain: it holds iff every incoming sync call into `n` either
  carries `@deadline` or comes from a covered caller; entries are uncovered.
  Coverage stops at `~>`, stream and spawn edges, because an async task does not
  inherit its sender's deadline. Linear in the number of wires. `×N`, `@fallback`
  and `!` do **not** satisfy this rule, because a retried hang still hangs.
- **Declare.** `@timeout(t)` or `@deadline(t)` on the call, or a `@deadline` on every
  path into the caller.
- **Tier.** binding for `op` reaches. **Advisory** for a returning actor destination:
  human-in-the-loop steps (an approval) may wait indefinitely on purpose. Asks:
  "How long may `[Judge]` wait on `db.insert`?" / "Is an unbounded wait on
  `(Approver)` intended?"
- **False positives.** Low. Notifications to actors (site 02:32,
  coverage:42/134/197, examples.md:56) do not fire.
- **Evidence.** Corpus hits: examples.md:497 `op db.insert`, examples.md:498
  `op mcp.search`. Satisfied: site 05:11, coverage:38/39, executions:16/18/41.
  ```
  [Judge] -> |Scores| : op db.insert(${out.score})                # flagged
  [Judge] -> |Scores| : op db.insert(${out.score}) @timeout(2s)   # declared
  ```
- **Phase.** P2, small. Uses `Wire.call.external` and `sim.mod`; wants MG3.

#### SGC102 `retry-amplification`
- **Risk.** Retries at several layers multiply, and fan-out multiplies again. Three
  layers of `×3` turn one request into 64 attempts at the bottom, during the very
  outage that caused them.
- **Principle.** Retry at one layer, or budget retries. Sources: Google SRE book
  ch. 22; Brooker (AWS Builders' Library), "Timeouts, retries and backoff with
  jitter"; Nygard, *Force Multiplier*.
- **Query.** A max-product dataflow on the DAG of sync-chain SCCs:
  `amp(n) = max over calls w in body(n) of retry_attempts(w) × width(w) ×
  amp(callee(w))`, where `width(w)` is the fan-out width (glued `×N` cardinality via
  CG1, the number of `*>` members, 2 for an `&?` hedge). The chain crosses `~>` and
  stream edges into a consumer that retries, because redelivery is one more retry
  layer. A recursive SCC gets `amp = unknown` and is left to SGC151. A symbolic `N`
  makes the value unknown and the path is skipped. Report when at least **two retry
  layers** exist and the product is at least `amplification` (default 9,
  configurable). The witness path is kept by argmax. The message separates the retry
  factor from the width factor.
- **Declare.** `@inv retry-budget(p)` on the outermost retrying call or its caller.
  This is the declaration that addresses the risk. A `@deadline` on the outer call
  limits time only; the message says it does not limit the attempt count.
- **Tier.** advisory. Ask: "Three layers retry (×48 at `[B]`, ×1 width). Is there a
  retry budget?"
- **False positives.** Medium while `×N` is ambiguous; CG1 removes the corpus
  cardinality cases (coverage:63/64/187, examples.md:149/156).
- **Evidence.** None in the corpus (§3.3). Probe:
  ```
  (U) -> [A] : run() ×3                          # flagged: 4·4·3 = 48
  [A] -> [B] : call() ×3
  [B] -> (Ext) : op x.write() ×2 @timeout(1s)
  ---
  (U) -> [A] : run() ×3 @inv retry-budget(10%)   # declared
  ```
  The sim does not re-drive inner retries (B5), so this rule is static only.
- **Phase.** P2, small to medium.

#### SGC103 `timeout-budget-inverted`
- **Risk.** An outer timeout shorter than the inner chain's worst case gives up while
  work below continues. That wastes load and leaves orphaned side effects.
- **Principle.** Propagate deadlines. Sources: SRE book ch. 22; gRPC deadline
  propagation; Brooker.
- **Query.** A duration algebra over Program items, computed as a memoised dataflow
  on the call DAG with SCCs collapsed (cycles are skipped; SGC151 covers them):
  - Step = attempts × timeout, plus `@after` waits when they parse;
  - sequence = sum;
  - `&` join, `*>` group, `parallel @all` = max of the members;
  - race (`&?`, `parallel @any`) and alternatives = max over the members that can
    win (open question 8 asks whether a race should take the min);
  - loop region = `@times N` × body;
  - the chain stops at `~>`, `*>`-into-stream and spawn edges (no deadline crosses
    them; the consumer needs its own bound).

  For a call `w` with `duration(@timeout or @deadline) = T`, report when the callee's
  value exceeds `T`. A path with a symbolic `×N` or an unparsed duration is skipped.
- **Declare.** Consistent numbers, or a `@deadline` on the inner call no longer than
  the outer budget.
- **Tier.** binding. Ask: "`[A]` waits 2s but `[B]` may take 4s (×4 attempts at 1s).
  Which bound wins?"
- **False positives.** Low when it fires; the algebra no longer sums concurrent
  members.
- **Evidence.** None in the corpus. Executions E5 to E6 is correct.
  ```
  (U) -> [A] : get() @timeout(2s)                         # flagged
  [A] -> (Ext) : op x.get() @timeout(1s) ×3
  ---
  [A] -> (Ext) : op x.get() @timeout(1s) ×3 @deadline(2s) # declared
  ```
- **Phase.** P2, small to medium. `sim.duration` and `sim.attempts` exist; needs MG3.

#### SGC104 `retry-without-backoff`
- **Risk.** Immediate retries synchronise clients into a thundering herd and hit a
  recovering dependency at full rate.
- **Principle.** Exponential backoff with jitter. Sources: Brooker (AWS); Nygard,
  *Dogpile*.
- **Query.** Report an external call `w` with retry(w) where policy(w) has no
  `@after`.
- **Declare.** Any `@after(…)`, including `@after(0)` for a deliberate immediate
  retry (one retry against another replica). `@after(exp-backoff, cap=…)` is the
  usual form; jitter is an argument inside `@after`.
- **Tier.** advisory. Ask: "`http.get` retries ×3 at once. What schedule?"
- **False positives.** Medium. Scoping to external calls removes in-process retries.
- **Evidence.** site/examples/05-executions.sigil:11
  `op http.get(${url}) @timeout(5s) ×3 @fallback(${cached})`.
- **Phase.** P2, small.

### Delivery and idempotency (SGC11x)

#### SGC111 `retry-without-idempotency`
- **Risk.** A retried write whose first attempt actually succeeded (and whose reply
  was lost) is applied twice: a double charge, a double booking.
- **Principle.** Make retried operations idempotent. Sources: Helland, "Idempotence
  Is Not a Medical Condition" (2012); Kleppmann, DDIA ch. 11; Leach, Stripe
  idempotency keys (2017).
- **Query.** Report a call wire `w` with retry(w) and effectful(w), when no
  `@inv idempotent(…)` appears in policy(w), the callee's `Node.mods`, the written
  store's `Node.mods`, or an enclosing block's `modifiers`. Exempt:
  - a read-only callee (every wire a read, or a read verb);
  - a plain value or `${ref}` assignment to a scalar store (`~|S| : true`,
    `: ${x}`), which is idempotent by construction.

  Fire on op-calls, appends (`*|S|`, `++`) and value-operator updates over
  `${state…}`. `×` on a node is never read here (§1.4 policy).
- **Declare.** `@inv idempotent(key)` on the call, the callee or the store.
- **Tier.** binding, with a guess downgrade when effectful(w) was decided by verb or
  by a missing body. Ask: "`charge` is retried ×3. Is it idempotent, and on what
  key?"
- **False positives.** Medium: cardinality is handled by retry(w) and CG1; write vs
  read by access_mode and the guess downgrade.
- **Evidence.**
  - examples.md:49 (also language.md:918) `charge ×3 @after(…)` (guess: warn in spec).
  - site/examples/01-checkout.sigil:8 `charge(total) ×3 @timeout(2s)   # retried,
    idempotent`: the claim is prose only (SGC004 also points at it).
  - examples.md:237/251 is blocked by B7.
  - Satisfied pattern: coverage:57 `[Payment] @inv idempotent(transaction_id)`.
  ```
  [API] -> [Payments] : charge(total) ×3 @timeout(2s)                            # flagged
  [API] -> [Payments] : charge(total) ×3 @timeout(2s) @inv idempotent(order_id)  # declared
  ```
- **Phase.** P2, medium. Needs MG2 and CG1.

#### SGC112 `duplicate-delivery`
- **Risk.** Async delivery is at-least-once, so a consumer that writes state
  processes duplicates.
- **Principle.** Exactly-once is at-least-once delivery plus idempotence, and dedup
  belongs at the endpoint. Sources: DDIA ch. 11; Helland, "Life beyond Distributed
  Transactions"; Saltzer, Reed and Clark, end-to-end argument.
- **Query.** Report an event or stream node `E` that crosses a boundary (a stream;
  emitter and consumer with different `@loc`; or it feeds a node with `×N`
  instances) and feeds a consumer whose body writes a store or makes an external
  call, with no `@inv idempotent(…)` on the consumer and no `@inv dedup(…)` on `E`.
  A stage that only re-emits to another stream is not reported: the duplicate flows
  downstream, where the final consumer is checked. A consumer that is only a state
  machine is satisfied **only if** no state reachable after `T` has a `T` transition
  (no `_ -<T>->` wildcard and no `S -<T>-> S` self-loop): under NG6/NG7 those re-fire
  on every duplicate.
- **Declare.** `@inv idempotent(key)` on the consumer, or `@inv dedup(key)` on the
  event or stream.
- **Tier.** advisory. Ask: "`*<Order>` may arrive twice. Does `[Billing]` dedupe?"
- **False positives.** Medium. The boundary condition keeps in-process `~>` quiet.
- **Evidence.** Probe:
  ```
  [Shop] => *<Order>^1k@block                     # flagged (consumer appends)
  *<Order> -> [Billing]
  [Billing] -> *|Ledger| : append({Order})
  ---
  [Billing] @inv idempotent(order_id)             # declared
  ```
- **Phase.** P2, medium.

#### SGC113 `dual-write`
- **Risk.** One activation makes two durable effects without atomicity. A crash
  between the two leaves them disagreeing for good.
- **Principle.** Write the event in the same transaction as the state and relay it
  later (Richardson's transactional messaging pattern), or use change data capture.
  Sources: DDIA ch. 11, "keeping systems in sync"; Richardson, *Microservices
  Patterns*. The pattern's usual one-word name is not used in repo text; call it a
  "relay store".
- **Query.** Over a node's **direct** effects only (`sim._flat` of its own body; the
  transitive case is SGC121's), report either
  - two store writes to distinct stores, or
  - a store write plus an emit whose event drives a state machine or reaches another
    store write (a consumer with state).

  Emits that reach only actors or nothing (a metric, a notification) and writes of
  `unknown` mode do not count. Report only when no `@inv atomic(…)` is on the node or
  an enclosing block and no `!>` route of the node names one of the targets.
- **Declare.** `@inv atomic(|S|, <E>)` on the node, a compensating `!>`, or one
  option among others: a relay store (`[Svc] -> *|Pending|` and
  `[Relay] -> *|Pending| ~> <E>`).
- **Tier.** advisory. Ask: "`[Orders]` writes `|DB|` and emits `<OrderPlaced>`, which
  `{Order}` reacts to. What happens if it stops in between?"
- **False positives.** Medium. A single-process store plus an in-memory event is
  fine, so the rule asks rather than asserts.
- **Evidence.** No direct hit (examples.md:47–55 writes no store itself). Probe:
  ```
  [Orders] -> |DB| : insert({Order})            # flagged (<OrderPlaced> drives {Order})
  [Orders] ~> <OrderPlaced>
  ---
  [Orders] @inv atomic(|DB|, <OrderPlaced>)     # declared
  ```
- **Phase.** P2, small.

#### SGC114 `poison-message`
- **Risk.** A consumer that fails on one message retries it forever and blocks the
  queue behind it.
- **Principle.** Dead letter channel. Sources: Hohpe and Woolf, *Enterprise
  Integration Patterns*; Nygard, *Steady State*.
- **Query.** Report a node fed by a stream or `~>` that can fail (failure_flow) and
  has no route in `prog.routes` and no `@fallback` on the failing call. With B13 the
  failure stops at this consumer, which is where the finding anchors (not at the
  producer).
- **Declare.** `!> |DLQ|` (Example 4), a `@fallback`, or an overflow policy upstream
  (`^N@drop`, `@err`) as a stated policy.
- **Tier.** **binding** when the consumer retries (`×N`) with no `!>` (the "retries
  forever" case); **advisory** otherwise (a fail-stop consumer may be deliberate).
  Ask: "What happens to a message that always fails?"
- **False positives.** Low.
- **Suppression.** Folds SGC201 at the same anchor (§1.7). SGC201 keeps request paths
  that end at an entry or actor.
- **Evidence.** examples.md:111–117 and coverage:71–72 are *satisfied*, though the
  route never fires in the sim today (B1). Probe:
  `*<Raw> -> [Parse] : parse() ×3` with no `!>` is flagged (binding).
- **Phase.** P2, small. Needs CG7; B13 for the anchor.

### Sagas and compensation (SGC12x)

#### SGC121 `saga-uncompensated`
- **Risk.** Step 1 commits (a seat hold), then step 2 fails (the charge is declined).
  With no handling, step 1's effect stays: leaked holds and inventory drift.
- **Principle.** Sagas: each committed step needs a compensation (backward recovery)
  or every later step must be driven to success (forward recovery). Sources:
  Garcia-Molina and Salem, "Sagas" (1987); Richardson ch. 4.
- **Query.** Within one body (CG2), take ordered effectful wires `w1 … wk`. A later
  `wj` that can fail (failure_flow) is **handled** when any of these holds:
  - backward: every earlier effectful target `t(wi)` is named by a route that guards
    `wj` (a continuation `!>` on `wj`'s line, a `} !> …` on an enclosing block, or a
    node-level route);
  - forward: `wj` carries a `@fallback`, or a durable retry route `!> *|…|`;
  - `@inv atomic(…)` on the node or block (one transaction).

  `&` joins and `parallel @all` with effectful members are checked the same way: a
  member's failure leaves its siblings' effects.

  **Across async edges (choreography).** For a step reached through `~>` from an
  earlier effectful step in another component, the failing step must have a route
  that emits an event consumed by the earlier step's component, or one of the forms
  above.

  **Pivots.** An external `op` call with no compensation route and a plain
  `-> (Actor)` notification cannot be undone. Steps *after* a pivot are checked for
  forward recovery only: `×N` with `@inv idempotent` (SGC122's satisfiers) or a
  durable retry route, never for compensation.
- **Declare.** A `!>` naming the earlier target (`!> |Seats| : release({Hold})`),
  a `@fallback` or durable retry route on the later step, or `@inv atomic(…)`.
- **Tier.** advisory; pairing a step with its compensation by target name is a
  heuristic. Ask: "If `charge` fails, what undoes `hold`, or what drives `charge` to
  success?"
- **False positives.** Medium. A route that names the target but does something else
  passes: the rule asks that recovery be stated, not that it be correct.
- **Evidence.** examples.md:47–53 and the booking demo are satisfied. Probe:
  ```
  [Book] -> |Seats| : hold({Trip}) => {Hold}                        # flagged
  [Book] -> (Bank) : op bank.charge(total) @timeout(5s)
  ---
  [Book] -> (Bank) : op bank.charge(total) @timeout(5s)             # declared
         !> |Seats| : release({Hold})
  ```
- **Phase.** P2, medium. Needs MG4 and CG7.

#### SGC122 `fragile-compensation`
- **Risk.** A compensation that fails is never retried, and the saga ends half-undone.
- **Principle.** Compensations must eventually succeed: retryable and idempotent.
  Sources: Garcia-Molina and Salem; Helland 2007.
- **Query.** Report a route wire (a `!>` target in `prog.routes`) that is a call to an
  effectful target, when none of these holds: retry(route), `@inv idempotent` on the
  route or its target, a durable route `!> *|…|` (a route into a stream or
  accumulator store passes).
- **Declare.** Any one of `×N`, `@inv idempotent(key)`, or a durable `!> *|Retry|`.
  The ask notes that `×N` alone will then lead SGC111 to ask about idempotency.
- **Tier.** advisory. Ask: "What if `release` itself fails?"
- **False positives.** Medium.
- **Evidence.** examples.md:52 `!> [Inventory] : release({Hold})`;
  executions:34–35 E11 `!> |Index| : release`.
- **Phase.** P2, small.

#### SGC123 `race-loser-effects`
- **Risk.** `&?` and `parallel @any` cancel the losers, but a loser may already have
  written or charged, and cancelling does not undo that.
- **Principle.** Hedged requests are safe only for idempotent or read-only work.
  Source: Dean and Barroso, "The Tail at Scale" (2013).
- **Query.** Report a member of a join with kind `&?`, or of a block `parallel @any`,
  whose wire is effectful, when it has no `@inv idempotent` on the member, callee or
  block, and no route that names its target.
- **Declare.** Idempotent or read-only members, or a compensation route.
- **Tier.** binding.
- **False positives.** Low.
- **Evidence.** None in the corpus. Probe:
  `[Client] -> [EU] &? [US] : put({Doc})` is flagged, and so is the same line with
  `[EU] @inv idempotent(doc_id)` declared on only one member.
- **Phase.** P2, small.

### Shared state and access (SGC13x)

#### SGC131 `shared-writable-store`
- **Risk.** Two writers to a plain store with no stated resolution: the last write
  wins by accident.
- **Principle.** Single writer, or a stated merge. Sources: Thompson, "Single Writer
  Principle" (2011); DDIA ch. 5 and ch. 7.
- **Query.** Build `writers(store)` = {principal: sources} (**MG12**) from
  `Graph.access` write entries, `@owns |S|` and `owns` blocks, and flow writers by
  access_mode. Count principals by **role** (`Worker<N>` is one principal; generic
  bases resolve with `_resolve_principal`).
  - **(a)** Report a plain `|S|` (data glyphs are never stores) with two or more
    writers, unless it states a **resolution**: a single owner (`@owns`, a
    single-member `@write`), `@inv serialised(|S|)`, `@inv cas(…)`,
    `@inv atomic(…)`, `@inv immutable`, or a change of store kind.
  - **Exempt kinds.** `~|S|` (last-writer-wins) and `*|S|` (merge) are exempt: the
    spec says the store kind supplies the resolution, and the writers are visible in
    the flows.
  - A multi-member `@write(a, b)` **does not** clear it: it repeats the wiring and
    states no resolution.
  - **(c) access unknown (hint).** When a store has one known writer plus flows of
    `unknown` mode (§1.4) that would make it two, one hint per store: "`[Svc] ->
    |DB|`: does it read or write? `@read`/`@write`, or a verb, says."
- **Declare.** `@owns |S|`, `@write(X)`, `@inv serialised(|S|)` / `cas(field)` /
  `atomic(…)`, or the `*|S|` / `~|S|` kind.
- **Tier.** advisory (with the guess downgrade when a writer is a heuristic); clause
  (c) is a hint. Ask: "`|Shared|` has three writers. How are their writes
  resolved?"
- **Suppression.** Folds SGC204 and SGC133 on the same store (§1.7). SGC204 then
  reports races only where SGC131 is satisfied or acknowledged.
- **False positives.** Medium: coverage:152–153 is handled by access_mode;
  examples.md:870 `(Auditor) -> *|EventLog|` is declared `@read`; data glyphs are
  excluded.
- **Evidence.**
  - examples.md:814–816 `|Shared|` with `@write(Planner, Builder, Tester)`: flagged
    (a list, no resolution) unless the example states one;
  - examples.md:480–481 `~|running|` is **exempt** (`~` kind);
  - satisfied: 868–869 (stream store), 844–853 (`Worker<N>` is one role), 399–420
    `|PROV|` (`@inv immutable`).
  ```
  [A] -> |Doc| : put({Doc})                     # flagged
  [B] -> |Doc| : put({Doc})
  ---
  |Doc| @inv serialised(|Doc|)                  # declared
  ```
  Whether an event may be a principal in `@write(…)` is open question 9.
- **Phase.** P2, medium. Needs MG2 and MG12.

#### SGC132 `undeclared-access`
- **Risk.** The wiring reaches a store its access list does not grant, so the
  design's access claims and its flows disagree.
- **Principle.** Least privilege. Sources: Saltzer and Schroeder (1975); Miller,
  *Robust Composition* (2006).
- **Query.** Opt-in **per direction**. Writes are checked only on a store with at
  least one `@write`; reads only on a store with at least one `@read`. A write needs
  `write` or a write-narrowed `borrow`; a read needs `read` or `write`. A store with
  only `@write` makes no read claim, so adding `@write` never turns every reader into
  a finding. Read the declared mode first, then the heuristic; `unknown` never fires.
- **Declare.** Add the principal to the list, or borrow from someone who has it.
  `@cap(…)` on the call is **not** a satisfier: a flow's capability requirement does
  not grant access the store's list withholds.
- **Tier.** binding, with a guess downgrade on a heuristic read/write.
- **False positives.** Low with per-direction opt-in. Test case: examples.md:870
  `(Auditor) -> *|EventLog|` is a flow into the store but declared `@read`.
- **Evidence.** None true in the corpus. examples.md:810–870 must stay clean; they
  are the regression fixture.
- **Phase.** P2, small (lint's SGL14x already resolves principals).

#### SGC133 `lost-update`
- **Risk.** A read-modify-write on a store by an activation that can run
  concurrently loses updates. This is the classic counter bug.
- **Principle.** Prevent lost updates with atomic operations, compare-and-set,
  locks, or commutative merges. Source: DDIA ch. 7.
- **Query.** Report a node `n` whose body reads `|S|` and later writes `|S|` (or does
  one write with a value operator over `${state.…}`), when concurrent(n) holds
  (§1.4, the same predicate as SGC204's static half), and none of the satisfiers
  holds. There is no dynamic confirmation: the sim models instances as counts and
  runs each entry once.
- **Declare.** In this order: `@inv atomic(…)` or `@inv cas(version)` on `n` or `|S|`;
  moving the store to the `*|S|` kind with `++` appends (merge and commute); an
  `@owns |S| { … }` block.
- **Tier.** advisory. Ask: "`~|total| : ${state.count} + 1`. Can two of these run at
  once?"
- **Suppression.** Folded under SGC131 or SGC204 on the same store.
- **False positives.** Medium. Whether a single value-operator write counts as atomic
  is open question 11; this draft says no.
- **Evidence.** examples.md:487–488 `<rated> -> ~|history| : ${state.history} ++ …`
  (concurrent only if `<rated>` has concurrent arrivals) and `~|total| : …` (lint gap
  L22, so only the first is visible).
- **Phase.** P2, medium.

#### SGC134 `held-across-call`
- **Risk.** Holding an owned resource across a slow or remote call exhausts the pool.
- **Principle.** Blocked threads and bulkheads; pool sizing by Little's law. Source:
  Nygard.
- **Query.** For a `Block` of kind `owns`, walk the region's call wires **and their
  transitive sync callees** (through bodies and aliases, stopping at `~>`): the sim
  holds the resource for everything that runs on the task during the region. Report
  an external call there when SGC101 is already satisfied for it but the hold is
  long: retry(w) is present, or attempts × timeout exceeds `hold` (default 1s,
  configurable). An unbounded call is SGC101's finding, with the `owns` context in
  its message (§1.7). Report the deepest external call with its path.
- **Declare.** `@deadline(t)` on the inner call, a deadline on the enclosing block
  (NG3), or moving the call out of the block.
- **Tier.** advisory.
- **False positives.** Medium.
- **Evidence.** None in the corpus. Probe:
  `[H] @owns |Conn| { [H] -> (Bank) : op bank.check() @timeout(5s) ×3 }` is flagged.
- **Phase.** P2, small.

#### SGC135 `stale-read`
- **Risk.** A request writes a primary and then reads a replica fed asynchronously
  from it, and sees its own write missing (read-your-writes violated).
- **Principle.** Replication lag. Source: DDIA ch. 5.
- **Query.** Within one episode's sync chain (CG2), report a write to store `P`
  followed by a read of store `R`, where `R` is fed only asynchronously from `P`
  (`~>` or a stream), when no `@inv consistent(…)` is on `R` or the reader.
- **Declare.** `@inv consistent(read-your-writes)` or `@inv consistent(eventual)` on
  `R` or the reader (one head; the argument states the accepted model).
- **Tier.** advisory.
- **False positives.** Low: it needs both the write and the async feed in the wiring.
- **Evidence.** examples.md:750–751 writes `|Primary|`, replicates with
  `|Primary| ~> |Replica|` and serves reads from `|Replica|`.
- **Phase.** P2, small.

#### SGC136 `shared-data-order`
- **Risk.** Several systems write one data glyph inside one tick, and the result
  depends on their order.
- **Principle.** System ordering in entity-component designs; ordering must be stated.
- **Query.** Report a data glyph written by two or more components inside one `loop`
  body or one fork, when no `@inv ordered(…)` is declared and no chain between the
  writers sequences them. A data type produced in unrelated places (coverage:76/196)
  is excluded.
- **Declare.** `@inv ordered(…)` on the loop or fork, or a flow chain between the
  writers.
- **Tier.** hint.
- **Evidence.** site 03-arena:20–21 and examples.md:589–591: `{Transform}` written by
  `[Physics]`, `[Homing]` and `[Steering]`.
- **Phase.** P2, small.

### State machines (SGC14x)

All machine queries read `prog.machines[owner]` (initial state and transitions). A
`_ -<T>-> X` counts as "every state has T". Self-loops are removed before any SCC is
computed (§1.4); the self-loop `S -<T>-> S` is the one blessed idiom for "ignored on
purpose" (NG7, §7.8).

#### SGC141 `unreachable-state`
- **Risk.** No path from a start enters this state. The design is dead, or a trigger
  is missing.
- **Principle.** Reachability. Source: Harel, "Statecharts" (1987).
- **Query.** BFS over the transitions, seeded from **every `+` target**. A machine
  with no `+` (component modes) is seeded from every state that is not the target of
  any transition; if every state is a target, the rule skips the machine. Report any
  named state not reached. `$` and `_` are exempt.
- **Declare.** The entering transition.
- **Tier.** binding.
- **False positives.** Low. Fixtures: a machine with two `+` transitions, and a
  component machine with no `+`.
- **Evidence.** None in the corpus. examples.md:388 is *dynamically* unreachable
  (nothing emits `<assert>`); SGC146 catches that.
- **Phase.** P2, small.

#### SGC142 `dead-end-state`
- **Risk.** A non-terminal state with no way out, so entities get stuck.
- **Principle.** Terminal-state checking. Sources: Harel; Lamport, TLA+.
- **Query.** Fire **only when the machine uses `$` somewhere** (the author adopted
  the terminal convention; otherwise a state with no outgoing transition already is
  terminal, as the spec says). Then report a reachable state with incoming
  transitions, no outgoing transition, no `_` wildcard source and no `-> $`.
- **Declare.** A real triggered transition out (to `$` or elsewhere, e.g.
  `Settled -<archive>-> $` when an archive event exists), or an acknowledgement. The
  rule never suggests an untriggered `Settled -> $`, which the grammar rejects
  (SGL161).
- **Tier.** hint. Ask: "Is `Settled` terminal? The other end states lead to `$`."
- **False positives.** Medium, which is why it is a hint.
- **Evidence.** site 04 `{Order}` `Settled` and `Cancelled` (only if site 04 uses
  `$`); coverage:110–116 `Full`, `Down`, `Away`.
- **Phase.** P2, small.

#### SGC143 `ambiguous-transition`
- **Risk.** Two transitions leave one state on one trigger, and which one wins is
  unstated.
- **Principle.** Determinism. Sources: Harel; SCR consistency checks (Heitmeyer et
  al. 1996).
- **Query.** Report duplicate `(src, label)` pairs among a machine's transitions,
  unless **each** of the duplicates carries a per-transition `@inv` (the spec allows
  per-transition modifiers: `Running -<done>-> Ok @inv {Job}.exit = 0`), which reads
  as the disambiguating condition. A specific transition plus a `_` wildcard on the
  same trigger is **not** ambiguous once NG6 (specific beats wildcard) is in the spec
  **and** in the sim. Until the sim fix lands (`_deliver` / `_trigger` take the first
  written match today, and `_machine_points` never makes the pair a choice point),
  the pair **is** reported when the wildcard is written first, because check and
  simulator would disagree.
- **Declare.** Distinct triggers (`<succeeded>` / `<failed>`), a per-transition
  `@inv` on each duplicate, removing one, or an acknowledgement.
- **Tier.** binding.
- **False positives.** Low.
- **Evidence.** None in the corpus. Probe:
  `state {Job} { Running -<done>-> Ok` plus `Running -<done>-> Failed }` is flagged;
  `_ -<Paid>-> Weird` before `Open -<Paid>-> Done` is flagged until NG6 lands in the
  sim (it ends in `Weird` today).
- **Phase.** P2, small. The wildcard exemption depends on the P3 sim fix.

#### SGC144 `no-exit`
- **Risk.** A record's lifecycle can circle forever without reaching an end (a retry
  loop with no exhaustion path), so records accumulate.
- **Principle.** Everything that accumulates must be purged. Source: Nygard, *Steady
  State*. Example 5 (`Retryable → Dead`) is the satisfying shape.
- **Query.** Applies to machines on **data** owners (`state {X}`); component modes
  are cyclic by design and exempt. Remove self-loops, then report a closed SCC (no
  transition leaves it) of **two or more** states that contains no transition to `$`
  and no state from which `$` is reachable. A terminal data state that ignores late
  events with a self-loop is therefore never flagged.
- **Declare.** A `$` path, an exhaustion transition, or `@inv retention(t)` on the
  owner.
- **Tier.** advisory.
- **False positives.** Medium. Records kept forever by design say so with
  `@inv retention` or an acknowledgement.
- **Evidence.** None in the corpus. Probe:
  `state {Msg} { + -<new>-> Pending` / `Pending -<fail>-> Retryable` /
  `Retryable -<retry>-> Pending }` is flagged.
- **Phase.** P2, small.

#### SGC145 `orphan-event`
- **Risk.** An event is emitted and nothing consumes it: lost work, or a stale design.
- **Principle.** Every message channel needs a consumer. Source: Hohpe and Woolf.
  Also ordinary dead-code analysis.
- **Query.** Report an event node with an incoming emit or flow (or that is a route
  target) and no outgoing wire in `sc` and no Trigger. A flow `<E> -> (Subscribers)`
  counts as consumed beyond the document. Publishing for outside consumers is valid,
  the same case as a trigger with no event (SGC146), so the base tier is a hint.
- **Escalation to advisory.** (1) A consumer for the event exists but was removed by
  narrowing (CG5); (2) the event is a `!>` route target and nothing outside the
  document is named as receiving it.
- **Declare.** A consumer flow, or `<E> -> (Actor)` to say "consumed outside".
- **Tier.** hint, advisory when escalated. Gated on B12 (`=> <E>` returns and tree
  alerts must count as emitters).
- **Suppression.** Folded under SGC202 when the event is only a dead route's target.
- **Evidence.** examples.md:22 `<Unauthorized>` (escalated, case 2); 408 `<Unroll>`
  and 409 `<Verify>`; site 01:9 `<PaymentFailed>` (sketch, hidden); site 05:12 and
  executions:19 `<FetchFailed>` (case 2).
- **Phase.** P2, small.

#### SGC146 `undriven-transition`
- **Risk.** A consumed event that nothing in the document produces. For a machine
  trigger, the transition is dead unless the cause is outside the document; for any
  other consumer, the missing emitter is hidden as a sim entry.
- **Principle.** The mirror of SGC145. A cause outside the document is valid Sigil,
  so this only asks.
- **Query.** Report any event with consumers (a flow out, or a Trigger) and no emit,
  flow in or route in (after B12, so `=> <E>` returns and tree alerts count). For
  machine triggers, report per transition label `T` of machine `M` with no Trigger
  whose owner is `M`. Escalation to advisory, machines only:
  1. an event named `T` exists in the document but was narrowed to other owners
     (**CG5**; coverage:108);
  2. *every* transition out of `+` is undriven, so the machine can never move
     (examples.md:388–412).
- **Declare.** An emitter, preferably an outside actor that names the cause
  (`(Clock) ~> <\Tick>`, `(User) ~> <submit>`), or an internal emitter. An explicit
  aim `<T> -> {M}` also works, but the ask says that **an aim narrows the event**:
  every other machine naming `T` then loses its trigger. Tests re-run the rule on the
  suggested fix.
- **Tier.** hint, advisory in the two escalated cases.
- **Suppression.** Case 2 folds SGC203, SGC205 and SGC147 on that machine; any
  SGC146 folds SGC147 on the undriven transition's source state.
- **Evidence.**
  - examples.md:389/391/394–395 `<assert>`, `<resolve>`, `<archive>` (case 2);
  - coverage:108 `Busy -<Paid>-> Idle`, narrowed away (case 1);
  - coverage:40 `<Stop>`, 46 `<\Tick>`, 122 `<Push>`, examples.md:481 `<stop>`
    (non-machine, hint);
  - coverage:103/104/114/117 (hint).
- **Phase.** P2, small. Needs CG5 and B12.

#### SGC147 `wait-without-timeout`
- **Risk.** A state waits on an event that may never come (the payer walks away, the
  reply is lost, the worker crashes), and the entity is stuck for good. This is the
  common stuck-saga defect.
- **Principle.** Every wait needs a deadline. Sources: Garcia-Molina and Salem;
  Nygard, *Timeouts*.
- **Query.** Report a reachable, non-terminal state of a data-owner machine
  (`state {X}`), or of a component machine, when every outgoing transition is driven
  by an event that comes from another episode, an async emit or an actor, and no
  transition out of it carries `@timeout(t)` / `@after(t)`, and no
  `_ -<T>-> X @after(t)` wildcard applies. Transitions whose trigger is undriven are
  SGC146's and are ignored here.
- **Declare.** A timed transition (`Open -<expired>-> Cancelled @after(30min)`),
  `@inv retention(t)` on the owner, or an acknowledgement.
- **Tier.** advisory. Ask: "`{Order}` waits in `Open` for `<Paid>`. What if it never
  comes?"
- **False positives.** Medium.
- **Evidence.** coverage:108 (stuck once narrowed; folded under SGC146 case 1);
  site 04 `{Order} Open` waiting on `<Paid>`; Example 5 `Running` waiting on
  `<ok>`/`<fail>` from the worker.
- **Phase.** P2, small.

#### SGC148 `wildcard-leaves-terminal`
- **Risk.** `_ -<T>-> X` also leaves states that are meant to be final, so a late `T`
  resurrects or rewrites a finished entity.
- **Principle.** Terminal states absorb. Source: Harel.
- **Query.** Report a `_ -<T>-> X` transition when some state `S ≠ X` looks
  terminal: it has a transition to `$`, or its only outgoing transitions come from
  wildcards.
- **Declare.** A specific self-loop `S -<T>-> S` (ignored on purpose; with NG6 it
  beats the wildcard), or an acknowledgement.
- **Tier.** advisory. Ask: "A late `<cancel>` also leaves `Done` and `Dead`. Is that
  intended?"
- **Evidence.** examples.md:72 `_ -<cancel>-> Cancelled` (also language.md Example 5).
- **Phase.** P2, small. The self-loop satisfier needs NG6 in the sim (P3) to be
  honoured by a run; the static rule accepts it from P2.

### Termination (SGC15x)

#### SGC151 `unbounded-recursion`
- **Risk.** A recursion or sync cycle inside one component or expansion with no
  stated bound can overflow the stack or run forever on adversarial input.
- **Principle.** Well-founded recursion. RFC 0003 amends language.md's Recursion
  paragraph so a bound **may optionally** be stated (`@inv depth <= N`,
  `@inv terminates`); the rule asks for it and never calls recursion unsafe.
- **Query.**
  - **Static.** SCCs of the sync chain that contain a self-call (`scene.self_calls`,
    `Call.recursive`) or a cycle of two or more nodes **inside one top-level
    component or expansion**. Report when no node carries `@inv depth <= N` /
    `@inv terminates`, and no `?>` arm or `branch` arm leaves the SCC. A `!>` route
    does **not** count as an exit: it says what happens on failure, not when the
    recursion stops.
  - **Trace witness.** The `limit` event (MG6) confirms the cycle is live. check.py
    compares a declared `depth <= N` with `Limits` (CG4): "bounded by design (32) vs
    simulator (depth 3)".
- **Reply hint.** When a back-edge carries only a data payload
  (`[B] -> [A] : {Result}`), the message suggests the `=>` return arrow: a reply
  currently reads as recursion.
- **Declare.** `@inv depth <= N` or `@inv terminates` on a node of the cycle, a `?>`
  exit, or an acknowledgement. **Not `@cap`** (a capability requirement, NG2).
- **Tier.** advisory, never binding. Ask: "How deep can `[Doc.walk]` go?"
- **Evidence.** site 05:17 `[Crawler.follow] -> [Crawler.follow] : link`;
  executions:28 E9 and :47; coverage:83.
  ```
  [Doc.walk] -> [Doc.walk] : child                    # flagged
  [Doc.walk] @inv depth <= 32                         # declared
  ```
- **Phase.** P2 static, P3 witness. Small.

#### SGC152 `async-cycle`
- **Risk.** Messages loop (`A ~> B ~> A`, two machines playing ping-pong, a spawn that
  spawns its own kind) and keep the system busy without progress.
- **Principle.** Livelock; message TTL and hop limits. Sources: Tanenbaum, *Modern
  Operating Systems*; Nygard, *Chain Reactions*.
- **Query.**
  - **Classification.** Only `~>`, `parallel @none`, trigger and spawn wires are
    async. `*>`, `&` targets and `parallel @all` members are awaited, so a cycle
    through them is a sync wait on itself (SGC151 or SGC171). In traces both show as
    a `visit limit`, so the static classification decides which rule reports it.
  - **Static.** SCCs of the async graph. Report when no wire carries `@after(t)` (a
    scheduled tick is a declared, rate-limited cycle), no node carries
    `@inv hops <= N`, no `?>` or route leaves it, and it is not inside a `loop`.
  - **Bounded-buffer clause (advisory).** An async SCC through a `^N@block` stream
    can fill and deadlock (the bounded-buffer cycle of process networks). Ask:
    "What drains `*<X>` when it is full?" Satisfied by `@drop` / `@latest` on that
    stream, `@inv hops <= N`, or an acknowledgement.
  - **Rootless SCCs.** An SCC with no entry (MG8) is reported as SGC175 with a note,
    and simulated with `Scenario(entries=…)`.
  - **Trace witness.** The `visit limit` event (MG6).
- **Declare.** A `?>` exit, `@after(t)`, `@inv hops <= N`, or `loop @until …`.
- **Tier.** advisory. Ask: "`|PROV|` → … → `|PROV|` loops. What stops it?"
- **False positives.** Medium. Heartbeats and schedulers are cycles on purpose;
  `@after` or an acknowledgement covers them.
- **Evidence.** examples.md:399–400, the core read/write loop (36 visit-limit lines).
- **Phase.** P2 static, P3 witness. Small.

#### SGC153 `unbounded-loop`
- **Risk.** A `loop @while` / `@until` whose body never changes the condition runs
  forever.
- **Principle.** Termination needs a variant. Source: Nygard, *Steady State*.
- **Query.** Report a `Block` of kind `loop` with neither `@times` nor `@each`, and
  no `@inv terminates` in `Block.modifiers` (a trailing `} @inv …`, NG3). A
  `@while` / `@until` naming a store that something in the document writes is
  satisfied (a stop exists). Loops with no modifier are lint SGL163.
- **Declare.** `@times N`, `@each`, `} @inv terminates`, a writer of the condition
  (`<stop> -> ~|running| : false`), or an acknowledgement for a service main loop
  that runs forever on purpose.
- **Tier.** hint.
- **Evidence.** examples.md:537 `loop @while node`; the `@fallback(${node})` on 538
  returns the same node, so the loop never ends under a literal reading.
- **Phase.** P2, small.

### Load and capacity (SGC16x)

#### SGC161 `unbounded-buffer`
- **Risk.** An unbounded stream, queue or store grows until memory runs out, and
  latency grows with it.
- **Principle.** Back-pressure; Little's law. Sources: Reactive Streams; Nygard,
  *Create Back Pressure* and *Shed Load*.
- **Query.** Three clauses:
  - **(a) streams, advisory.** A stream `*<X>` / `*{X}` with no `^N` bound on **any**
    of its occurrences in the document. `*<X>` is the spec's documented way to say
    "unbounded", so the rule asks whether that is intended.
  - **(b) stores, advisory.** An accumulator `*|S|`, or any store that is a `!>`
    route target (a dead-letter store, often a plain `|S|`) with no reader, when no
    `@inv retention(…)` is declared.
  - **(c) implicit queues, hint.** A `~>` on a per-request path whose consumer
    retries, makes an external call or has `×N` instances, with no stream between
    producer and consumer and no `@sla` on the consumer.
- **Declare.** `^N@policy` on any occurrence, `@inv retention(t)`, a reader for the
  store, a stream between producer and consumer, or an acknowledgement.
- **Tier.** advisory for (a) and (b); hint for (c). Ask: "`*<Raw>` is unbounded. Is
  that intended, and what drains it?"
- **Suppression.** Clause (b) folds SGC175 on the same store.
- **Evidence.** All streams in the corpus are bounded (language.md:930–932).
  Example 4's `!> |DLQ|` has no reader (clause b). Probe: `[Ingest] => *<Raw>`.
- **Phase.** P2, small.

#### SGC162 `unbounded-result`
- **Risk.** A query that returns every row works in tests and falls over in
  production.
- **Principle.** Source: Nygard, *Unbounded Result Sets*.
- **Query.** Report a store read (access_mode read) returning `{List<X>}`, a stream
  `*{X}`, or a tree child `\-{rows}-$`, when it is not bounded.
- **Declare.** For data results: `@inv limit(N)` (a page size counts) or an
  acknowledgement. `^N` applies only to stream results (`*{X}^N`): the spec defines
  `^` on streams, so `{List<Row>}^100` is not notation.
- **Tier.** advisory.
- **Evidence.** Probe: `[Api] -> |DB| : query() => {List<Row>}` is flagged.
- **Phase.** P2, small.

#### SGC163 `capacity-mismatch`
- **Risk.** A scaled-out tier, or the open front door, overwhelms a fixed tier during
  spikes.
- **Principle.** Sources: Nygard, *Unbalanced Capacities*, *Scaling Effects* and
  *Shed Load*.
- **Query.** Report a caller with instances (CG1 cardinality, `Worker<N>`, `\-*`
  spawn) **or an actor entry** (an unbounded caller) that calls a callee with no
  instances, when the callee has no `@sla`, no bounded stream and no `^N` in front of
  it. For actor entries, report only the first non-actor callee of a per-request
  path.
- **Declare.** `@sla(…)` on the callee, or a bounded stream between the two.
- **Tier.** hint (never reaches error).
- **Evidence.** examples.md:149 `[LB] -> [App]×N` then `[App] -> [Data]`; every
  `(Client) -> [Api]` front door.
- **Phase.** P2, small.

#### SGC165 `fanout-tail`
- **Risk.** A strict join is only as fast as its slowest member, so the p99 of the
  whole is far worse than any member's.
- **Principle.** Source: Dean and Barroso, "The Tail at Scale".
- **Query.** For a `&` join, a `*>` group or a `parallel @all` block with no
  join-level deadline (`} @deadline(t)` in `Block.modifiers`, NG3), report a member
  that **can fail** (failure_flow, or `×N`) and is not an external call, when it has
  no `@timeout` / `@deadline`. External members without a timeout are SGC101's
  finding, with the join context in its message (§1.7). Plain in-process members
  that cannot fail are never reported.
- **Declare.** Per-member `@timeout` / `@deadline`, or a block-level `@deadline`.
  `&?` is not suggested: a hedge changes the semantics.
- **Tier.** advisory.
- **Evidence.** examples.md:47–51: `charge` has `×3` but no timeout (reported);
  `reserve` cannot fail (not reported); `score` has `@timeout(500ms)`.
- **Phase.** P2, small. Ships only after the NG3 grammar change (trailing block
  modifiers) is in language.md.

#### SGC166 `single-point-of-failure`
- **Risk.** A component whose failure takes the system down, with no redundancy and
  no stated availability.
- **Principle.** Redundancy. Source: SRE book.
- **Query.**
  - **(a) marked, advisory.** A node marked `!`, or the destination of a flow marked
    `!` (`{Cart} !`), with no `×N` instances, no **reachable** standby, and no
    `@sla(avail…)`.
  - **(b) dominators, hint.** A node or store on every path from two or more entries
    with the same lack.
  - **(c) `standby-unused`, hint.** A `\-_` standby that no route, fallback or machine
    transition reaches; it does not count as redundancy.
- **Declare.** First `@sla(avail>…)` stating the accepted availability; then `×N` or
  a reachable `\-_` standby.
- **Tier.** advisory for (a); hint for (b) and (c). Ask: "What availability is
  accepted for `[Api]`?"
- **Evidence.** coverage:23 `(Customer) -> [Api] : {Cart} !` (fixture); site
  02-shop:18–20 `\-_ [StripePSP]` / `[AdyenPSP]` (clause c).
- **Phase.** P2, small.

#### SGC167 `unbounded-spawn`
- **Risk.** One task per message or item with no cap: a fork bomb or pool exhaustion.
- **Principle.** Bounded concurrency. Sources: Nygard, *Shed Load*; Reactive Streams.
- **Query.** Report a `\-*` dynamic child, a spawn flow (`=> [X]`, `*-` child) or a
  `*>` over a collection payload (`{List<X>}`) when there is no ceiling: no `×N` on
  the child, no `^N` on the feeding stream, no `@inv concurrency <= N` on the spawner
  or the child. A spawn that recurses (a spawned child spawns its own kind) is an
  async SCC through spawn wires; it is also seen by SGC152.
- **Declare.** `×N` on the child (a ceiling), `^N` upstream, or
  `@inv concurrency <= N`.
- **Tier.** advisory; **binding** when the spawn is recursive.
- **Trace witness.** The sim's `Limits.spawn` hit, reported through SGC090 as a limit
  event.
- **Evidence.** None in the corpus. Probe: `[Crawler] \-* [Fetch]` with
  `[Fetch] => [Crawler]`.
- **Phase.** P2, small.

### Structure (SGC17x)

#### SGC171 `dependency-cycle`
- **Risk.** Components that call each other synchronously cannot be deployed or
  scaled apart, and under thread-per-request a sync cycle can deadlock.
- **Principle.** Acyclic dependencies. Sources: Martin, ADP (2002); Parnas (1979).
- **Query.** SCCs of the **component-level** sync chain spanning **two or more
  distinct top-level components** (SCCs inside one component are SGC151's). Exclude
  replies to the caller and machine wires.
- **Declare.** `@timeout` / `@deadline` on an edge of the cycle (breaks the
  no-preemption condition), `@inv depth <= N` / `@inv terminates` (shared with
  SGC151: says how it ends), or an acknowledgement. The rule never suggests
  rewiring. When a back-edge is a reply, the message suggests `=>`.
- **Tier.** advisory. Ask: "`[A]` and `[B]` call each other. How does the cycle avoid
  deadlock, or end?"
- **False positives.** Medium. The exclusions remove the corpus false positives
  (coverage:23+42, examples.md:45+56, machine wires).
- **Evidence.** None true in the corpus.
- **Phase.** P2, small.

#### SGC172 `expansion-escape`
- **Risk.** An inner node of `[Core] := { … }` depends on a sibling of `[Core]` that
  the outer level never mentions, so the zoom levels hide a dependency.
- **Principle.** Information hiding and layers. Sources: Parnas; Dijkstra, THE
  system (1968).
- **Query.** For every expansion unit `U` of owner `O`, report a wire in `U` whose
  destination is a node of an outer unit other than `O`, when the outer level has no
  flow between `O` and that node.
- **Declare.** State the dependency at the outer level (`[O] -> [X]`); the inner
  calls stay as they are.
- **Tier.** advisory.
- **Evidence.** None in the corpus (Example 6 states `[Core] -> [Data]`, so
  `[App] -> [Data]` inside `[Core]` passes).
- **Phase.** P2, small.

#### SGC173 `lock-order-cycle`
- **Risk.** Two holders acquire the same resources in opposite orders: circular wait.
- **Principle.** The Coffman conditions; lock ordering. Sources: Coffman, Elphick and
  Shoshani (1971); Havender (1968).
- **Query.** Build the lock-order graph: an edge `R1 → R2` for an `owns` block on `R2`
  nested in one on `R1`, or a sync call made inside `owns R1` whose callee's chain
  acquires `R2`. With `@inv lock-order(|A| < |B|)` declared, report every edge that
  goes against the declared order (this absorbs the former SGC305). Without it,
  report cycles whose inner acquisition is not bounded by `@timeout`.
- **Declare.** One acquisition order, `@timeout` on the inner step, or
  `@inv lock-order(…)`.
- **Tier.** binding.
- **Evidence.** None in the corpus. Probe: `[P] @owns |A| { [P] -> [Q] }` with
  `[Q] @owns |B| { [Q] -> [P] }`.
- **Phase.** P2, medium (the declared-order clause lands with P4's invariants).

#### SGC174 `optional-callee`
- **Risk.** A call targets a node that may have zero instances (a conditional `\-?`,
  dynamic `\-*` or standby `\-_` child), and nothing says what happens when it is
  absent.
- **Principle.** Fail fast on missing dependencies. Source: Nygard.
- **Query.** Report a call wire whose destination's tree entries all have `rel` `?`
  or `_`, or a conditional `cond`, or that is created only by spawn, and whose caller
  has no route and no `@fallback`.
- **Declare.** A `!>` or `@fallback` on the call.
- **Tier.** hint.
- **Evidence.** coverage:63 `[Api] -> [Shard] ×4`; the sim logs "no instance of
  [Shard]".
- **Phase.** P2, small.

#### SGC175 `unreached`
- **Risk.** A construct no entry reaches: an alias never invoked, an unreachable
  branch, a rootless cycle.
- **Principle.** Dead-code analysis.
- **Query.** The complement of `sim._reachable(prog)` (public under MG4), over alias
  bodies, branches, regions and nodes with work. Rootless SCCs are reported here
  with a note (MG8).
- **Declare.** Wire it in, or acknowledge it as a library or fragment.
- **Tier.** hint.
- **False positives.** The sim's branch defect (B4) makes every payload-field branch
  look unreached. Not shipped before B4 is fixed.
- **Evidence.** coverage:82 and 194–197; executions:30 E10; coverage:151.
- **Phase.** P3 (gated on B4).

---

## 3. Behavioural rules (over simulator traces, plus the static facts that make them exact)

**Exploration.** `sim.scenarios(sc)` plus `sim.combinations(sc, k)` (**MG10**):
`--k`, default 1 in craft and in the playground, 2 in spec.

- **Semantics.** A deviation is a **persistent per-site failure**: a choice is keyed
  by wire or node ident and applies to every activation, so it means "this call
  always fails", never "fails once" or "fails on iteration 2". RFC 0003 states this.
- **Dependency-guided combination.** Pair B with A only when B's wires lie on A's
  deviated path, or when A enables B (`cond` plus `alt`, and routes). Example: in
  `[Router] ?> [Email] / [Push] / [SMS]` (examples.md:291, 313, 334), `Router/Push`
  and `Router/SMS` do nothing unless the `?>` is also taken, so they are paired with
  it.
- **Dedupe.** Traces are deduplicated by their event signature; a deviation whose log
  matches the happy path is dropped (B3 makes 8 such today).
- **Construction.** `Scenario(choices=…)` is built directly from `ChoicePoint.cid`,
  never by name (`sim.scenario(name)` re-lists every scenario on each call).
- **Budget.** A time or trace budget, not `Limits.scenarios` truncation by source
  order (which makes findings depend on edits to unrelated early lines). When the
  budget cuts exploration, SGC090 reports how many combinations were left out. Cost
  today: coverage.sigil at k = 2 is 91 pairs at about 22 ms per trace in CPython
  (about 2 s; roughly 10× in Pyodide).
- Every rule reads `Trace.end["events"]` (**MG1, MG5, MG6, MG11**) rather than log
  text. Findings are deduplicated by (rule, anchor); the message names the witness.

**Happens-before (MG1), per synchronisation site.** check.py computes vector clocks
from these events; sim.py only records them:

- `fork(child, parent, why)` at `_fork`, including `_deliver` (the parent is the task
  that delivered the event, so a trigger task is ordered after its emitter) and
  `_begin_episode` (a root);
- `gate-arrive(task, key, round)`, `gate-fire(task, key, round)` and
  `gate-resume(task, key, round)` at `_gate`: edges arrive_i → fire and
  fire-complete → each waiter. The last arriver runs the target on its own task and
  the waiters resume after its `_land` (round += 1);
- `await(waiter, members)` / `resume(waiter)` at `_await`: member ends → waiter;
- **gates may span episodes**: a gate edge is a real cross-episode edge (a probe of
  `[A] & [B] -> [C]` with A and B as entries shows A waiting in episode 1 and
  finishing in episode 2);
- each task records **its episode at fork time**, so failures and accesses are
  attributed to their own episode rather than to `self.episode`.

**Access events (MG2).** An `access(task, store, mode, wire, held)` event is emitted
at the **top of `_land`**, after the spawn step and before any early return (reach 0,
opaque, visit limit, depth cap): the corpus's main case,
`[Judge] -> |Scores| : op db.insert(...)`, returns at the opaque branch. `mode` uses
the same `access_mode(w, graph)` as the static rules. `held` is the set of stores the
accessing task holds, derived from the task's scopes and `owns` blocks, not from the
per-frame `Frame.held_resources`. A failed write attempt counts as an access with an
unknown outcome (open question 13).

#### SGC201 `unhandled-failure`
- **Risk.** A failure unwinds to an entry or an actor and nothing on the way says
  what happens. The user sees a raw error.
- **Principle.** Fail fast, and let it crash *under a supervisor*: the route is the
  supervisor. Sources: Nygard, *Fail Fast*; Armstrong (2003).
- **Query.**
  - **Static, exact (P2).** Propagate failure_flow (CG7) up the sync callers on
    **every** path, stopping at `~>` boundaries; report an entry or actor-facing
    call where some arriving failure passed no chosen route and no `@fallback`.
  - **Trace witness (P3).** Names a scenario that shows it. A trace detector proper
    would need `_Fail.origin` copied at the four re-raise sites (`_run`, `_region`,
    `_call_failed`, `_await`); it is not needed.
  - **Counting.** A `!>` route counts as handling **whether or not** the caller still
    fails after it (§7.1). Failures in `~>` tasks are reported only when the async
    task has no route of its own. A stream- or `~>`-fed node is SGC114's (§1.7).
  - This rule absorbs survey A2 `timeout-without-route` (executions:41 E12).
- **Declare.** A `!>` anywhere on the chain; one `!> (Caller) : <Failed>` at the
  entry covers the whole chain. Or `@fallback`, or an acknowledgement. `!` is **not**
  a satisfier: the spec defines it as "critical / must-not-fail" (SGC166 reads it
  that way).
- **Tier.** binding. Ask: "If `db.insert` fails, what does `[Judge]` do?"
- **False positives.** Low.
- **Evidence.** examples.md:497–498; executions:41 E12; executions:14 E4;
  coverage:59, 63, 64, 187. Not flagged: site 04:9, examples.md:47–53,
  executions:34–35.
- **Phase.** P2 static, P3 witness. Medium. Needs CG7, B13.

#### SGC202 `dead-failure-route`
- **Risk.** A `!>` route that no failure can reach. The author believes a failure is
  handled, and it is not.
- **Principle.** Reachability. Seed: executions E11 (fixed in d29e6b7).
- **Query.** **Static, exact (P2):** a route is dead iff its guard is selected for no
  arriving guard in failure_flow (CG7). That covers the cases the first draft
  missed: a continuation `!>` under a `~>` (structurally dead: `_async` never
  consults the call choice and an async failure stops as "not awaited"), a `!>` on a
  `*>` / `&` line (dead until B1 is fixed), block-guarded and node routes reached
  only by propagated failures. The trace (union of `end["routes"]`) only names a
  witness.
- **Two cases.**
  - **Unreachable (binding).** No failure can reach the route at all.
  - **Fallback shadow (advisory).** Every failure reaching the route is absorbed by a
    `@fallback`. Whether `!>` still fires when `@fallback` absorbs the failure
    ("notify, then yield": a deliberate degrade-and-alert design) is open question 2.
    Until the RFC decides, the ask is: "Should the route fire as well as the
    fallback?"
- **Gate.** Routes on `*>` / `&` lines are not reported until B1 is fixed (Example 4
  would otherwise be an error).
- **Declare.** Move the route under the flow it means, or acknowledge it.
- **Tier.** binding (unreachable) / advisory (fallback shadow).
- **Evidence.** **site/examples/05-executions.sigil:11–12** `@timeout(5s) ×3
  @fallback(${cached})` then `!> <FetchFailed>` (fallback shadow); coverage:72 and
  examples.md:117 `!> |DLQ|` (B1, gated); coverage:141 (B2).
  ```
  [A] -> (Ext) : op x.get() @timeout(1s) @fallback(0)     # flagged (advisory)
        !> <Failed>
  ---
  [A] -> (Ext) : op x.get() @timeout(1s)                  # declared: the route handles it
        !> <Failed>
  ```
- **Phase.** P2 static, P3 witness. Small. Needs CG7 and MG4.

#### SGC203 `event-ignored`
- **Risk.** An event reaches its machine in a state with no transition for it and is
  silently dropped.
- **Principle.** Every input must be handled in every mode. Sources: Harel; SCR
  completeness (Heitmeyer et al. 1996).
- **Query.** One order analysis shared with SGC205:
  - each machine's state is a shared variable, and each `_trigger` delivery is a
    write to it;
  - **per-sender FIFO**: deliveries from one task to one machine arrive in program
    order (this keeps a single producer quiet);
  - for each pair of HB-unordered deliveries to one machine, a static **diamond
    check** on `Program.machines`: from the state reached, are both orders accepted,
    and do they end in the same state?

  SGC203 reports a drop only when it happens in **every** admissible order (after
  `$`, or when the emitter is HB-before the event that enables the transition). An
  `ignored` event (MG11) that depends on order is SGC205's. **Drops while the owner
  is in `+`** (the event arrives before the record exists) are an ordering question
  and always go to SGC205.
- **Declare.** A transition for the event, a `_ -<T>-> …` wildcard, or the blessed
  self-loop `S -<T>-> S` ("seen and ignored on purpose", NG7). `+` is not a legal
  transition target, so the self-loop is never suggested for `+`.
- **Tier.** binding (warn until B1–B4 are fixed, §1.2). Ask: "`<Paid>` reaches
  `{Order}` while it is `Settled`. Should it be ignored, or is a transition missing?"
- **Suppression.** Folded under SGC146 case 2 on that machine.
- **Evidence.** coverage:119–121 (`<Paid>` before `<Placed>`: SGC205 under this rule
  set, because the owner is in `+`); examples.md:388–412 (folded under SGC146 case 2).
- **Phase.** P3, small. Needs MG1 and MG11.

#### SGC204 `race`
- **Risk.** Two tasks touch one store, at least one writes, and nothing orders them:
  a data race or write skew.
- **Principle.** Happens-before and locksets. Sources: Lamport (1978); Savage et al.,
  Eraser (1997); Flanagan and Freund, FastTrack (2009); DDIA ch. 7.
- **Query.** Split by where the concurrency comes from:
  1. **Static, across arrivals and instances (P2).** For each arrival (§1.4),
     compute the reachable `(store, mode)` set with `_reachable`. Compare arrivals
     pairwise (arrivals from the same actor are program-ordered and not compared),
     and compare an arrival with itself only when concurrent(n) holds for the
     writing node. The sim cannot show instance concurrency: instances are counts
     (`_Run.counts`), and a flow into an instanced node runs one activation.
  2. **Trace, inside one episode (P3).** Vector clocks over the MG1 events, limited
     to the tasks the sim really forks (`*>`, `&` targets, `parallel`, `~>`,
     triggers). Two `access` events on one store, at least one a write, that are
     HB-unordered **and** lockset-disjoint (`held` sets share no `owns` on the
     store).
  - **Concurrent ownership.** Two tasks holding the same `owns` at once (the sim
    never blocks on an `owns` region; its counter just reaches 2) is reported as its
    own finding under this name, never as a pass.
  - **Not reported when** the store has a single owner (`@owns`, single `@write`), is
    `*|S|` or `~|S|` (the kind resolves it), or has `@inv serialised` / `cas` /
    `atomic` / `immutable`. Folded under SGC131 on a store with no stated resolution.
- **Declare.** A single owner, a `*|S|` / `~|S|` kind, `@inv serialised(|S|)`,
  `@inv cas(version)`, `@inv atomic(…)`, or `@inv ordered(…)` on the actor (its
  arrivals are sequential).
- **Tier.** binding, with a guess downgrade when either access is a heuristic write;
  the trace half is warn-only until B1–B4 are fixed.
- **False positives.** Medium, contained by the arrival model, declared access and
  the guess downgrade.
- **Evidence.** examples.md:480–481 (`~|running|`: exempt by kind under this rule
  set); examples.md:814 `|Shared|` (folded under SGC131).
- **Phase.** P2 static (half 1), P3 trace (half 2). Needs MG1, MG2, MG9, MG12.

#### SGC205 `ordering-unstated`
- **Risk.** The design is only correct if events arrive in the order they are
  written. With a partitioned queue, retries or parallel consumers they arrive
  reordered.
- **Principle.** Ordering guarantees must be stated. Sources: DDIA ch. 9 and ch. 11;
  Lamport (1978).
- **Query.**
  - **Primary (trace, P3).** The SGC203 analysis: HB-unordered delivery pairs to one
    machine whose diamond check fails (different end states, or a drop in one order).
    This covers orderings inside an episode (fan-out, `~>`, `parallel`) and needs no
    reruns: O(deliveries²) per trace.
  - **Static (P2, a guess).** A machine whose triggers come from two or more
    independent sources (different arrivals, different members of a fork or
    `parallel`, distinct async emits in one body, or a consumer with `×N` /
    `Worker<N>` instances), with no `@inv ordered(key)`.
  - Drops while the owner is in `+` (from SGC203) are reported here with an ask that
    names the ordering.
  - Entry permutations, where wanted as extra evidence, use
    `Scenario(entries=perm)`; CG3 is not needed.
- **Declare.** `@inv ordered(key)` on the events or the machine owner, transitions for
  both orders, or an acknowledgement.
- **Tier.** advisory. Ask: "`{Order}` only works if `<Placed>` comes before `<Paid>`.
  Is that order guaranteed?"
- **Evidence.** site 04:7–8 (and examples.md:655–669); coverage:119–121.
- **Phase.** P3 (static part P2). Medium.

#### SGC206 `stalled-join`
- **Risk.** A join waits for a member that neither arrives nor fails.
- **Principle.** Coffman's circular wait, generalised; TLA+ liveness.
- **Query.** Detection reads `end["stalled"]`, which exists today; MG1 is needed only
  to attribute the stall to its join (`gate` / `await` events).
- **Prerequisite decision (open question 3).** A minimal probe stalls on the
  **happy path**: `[S] -> [A] : a()`, `[S] -> [B] : b()`, `[A] & [B] -> [C] : go()`
  gives `end["stalled"] == ['A_service']`: A blocks at the source-join gate on S's
  task, and B is only called after A returns. That comes from the sim's choice that
  a source-join arrival is a blocking barrier, while the notation reads `&` as a
  dataflow join. The RFC must choose:
  - **(a) non-blocking deposit** (recommended): the arriver deposits and continues,
    and the last arriver fires. A sim change, with goldens. The probe then passes.
  - **(b) blocking barrier**: the rule asks "`[A]` waits for `[B]`, but `[B]` is only
    reached after `[A]` returns on the same chain".
- **Declare.** `@timeout` on the members or the join (NG3), `@fallback`, or `~>`
  (unawaited).
- **Tier.** binding (warn until B1–B4 are fixed).
- **Evidence.** The probe above (a fixture), plus a join on an event nothing emits.
- **Phase.** P3, small, after the decision.

---

## 4. Declared invariants (`@inv`)

**Recognised invariants (NG5).** `@inv` takes a free expression, and every word stays
legal on its own. Recognising a head gives the checker something to check, so the
list is kept short and **canonical: one declaration per risk**, preferring an
existing modifier wherever one exists. RFC 0003 adds this as a short "Recognised
invariants" table to language.md.

| Head | Risk it states | Existing notation preferred instead, when it fits |
|---|---|---|
| `idempotent(key)` | a repeat has no further effect | — |
| `dedup(key)` | the channel drops duplicates | — |
| `atomic(x, …)` | these effects commit together | — |
| `ordered(key)` | arrivals keep order (per key) | — |
| `serialised(\|S\|)` | writes to S are applied one at a time | `@owns \|S\|`, a single `@write` |
| `cas(field)` | writes are compare-and-set on a version | — |
| `immutable` | written once, never changed | — |
| `depth <= N` | recursion depth bound | — |
| `hops <= N` | async cycle hop bound | — |
| `terminates` | the loop or recursion ends | `@times N`, `@each`, a `?>` exit |
| `retention(t)` | stored items expire | — |
| `lock-order(\|A\| < \|B\|)` | the global acquisition order | — |
| `layers(a > b > c)` | the tier order of `@loc` tiers | — |
| `retry-budget(p)` | retries are capped as a share of traffic | — |
| `limit(N)` | a data result is capped (a page size) | `^N` on stream results |
| `concurrency <= N` | spawned tasks are capped | `×N` on the child, `^N` upstream |
| `consistent(model)` | the read model a reader accepts | — |

Not recognised, because existing notation states the same risk: a bound (`^N`), a
rate or latency (`@sla`), ownership (`@owns`, `@write`), a time bound (`@timeout`,
`@deadline`), a handled failure (`!>`, `@fallback`), an exit (`?>`), a terminal
state (`$`), "ignored on purpose" (the self-loop `S -<T>-> S`; there is no
`ignores(…)`), a reply (`=>`). Architecture names (breaker, bulkhead, cancel-safe,
service-loop, deadline-propagated, callback) are not recognised: a risk they handle
is acknowledged, or checked by a dialect pack (§11).

- Each predicate is recognised by its head word; the `satisfiers` of §2 and §3 refer
  to these heads.
- Anything else (`unique:email`, `write-only-primary`, `>= 0`, `excludes(…)`) is
  **unchecked**, never failed.
- Dialects add heads through the rule-pack hook (MG16).

#### SGC301 `inv-unchecked`
- **What.** Lists each `@inv` whose head is not recognised, so the author knows which
  claims were taken on trust. It never fails a document.
- **Query.** Scan `("inv", text)` in `Node.mods`, `Edge.mods` and `Block.modifiers`
  across `render._walk`.
- **Tier.** hint.
- **Evidence.** language.md:751 `@inv unique:email`; examples.md:159
  `write-only-primary`; examples.md:403–425.
- **Phase.** P4, small.

#### SGC302 `inv-dangling`
- **Risk.** An invariant names something its anchor never touches (a typo, a stale
  reference after a rename), so the claim protects nothing.
- **Query.** A recognised head whose glyph arguments do not resolve:
  `atomic(|S|, <E>)` where the anchor does not write `|S|` or emit `<E>`;
  `serialised(|S|)` or `lock-order` naming a store no `owns` uses; `layers(…)` naming
  a tier no `@loc` uses. Key arguments (`idempotent(order_id)`) are checked only as a
  hint (payloads are free text).
- **Tier.** advisory; the key check is a hint.
- **Phase.** P4, small.

#### SGC303 `inv-contradicted`
- **Risk.** A recognised invariant that the wiring visibly breaks.
- **Query.** One clause per head, each added only after a probe shows that no correct
  reading of it exists:
  - `immutable` on a `~|S|` store, or on a store written with a value operator over
    its own state;
  - `idempotent` **with no key argument** on a node whose body does a value-operator
    update (`~|n| : ${state.n} + 1`). With a key, dedup on the key makes an increment
    idempotent (the idempotency-key pattern), so it never fires;
  - `depth <= N` / `hops <= N` / `concurrency <= N` where N is not a positive
    integer;
  - `ordered` **with no key** on a stream consumed by a node with `×N` instances and
    no `@owns`. A keyed `ordered(key)` with key-partitioned consumers keeps per-key
    order, so it never fires.
- **Tier.** binding.
- **Phase.** P4, medium.

#### SGC304 `layer-inversion`
- **Risk.** A lower tier calls an upper one, and the layering stops meaning anything.
- **Principle.** Layers. Sources: Dijkstra (1968); Parnas (1979); POSA vol. 1.
- **Query.** Only when the document declares `@inv layers(a > b > c)` and components
  carry `@loc(tier)`: report a sync call wire from a lower-tier node to a higher-tier
  node. `~>` (an event up) is allowed; nodes without `@loc` are ignored.
- **Declare.** This rule is the declaration's check; re-route, or add `~>`.
- **Tier.** binding (it only exists once declared).
- **Phase.** P4, small. Needs NG4.

#### SGC306 `timeout-below-sla`
- **Risk.** A caller's `@timeout` is shorter than the callee's own declared p99, so
  more than 1% of calls time out by design.
- **Query.** For a call `w` with `duration(@timeout) = T` to a node carrying
  `@sla(p99<X)` (or p95, p50), report when `X > T` and both parse. Not reported when
  the call has a `@fallback`, a route, or is a member of `&?` / `parallel @any`:
  cutting the tail on purpose is a standard design.
- **Tier.** advisory.
- **Evidence.** None in the corpus. language.md:932 `@sla(p99<50ms)` has no caller
  timeout.
- **Phase.** P4, small.

---

## 5. Meta rules (acknowledgements and exploration)

#### SGC001 `ack-unknown-rule`
An acknowledgement names no known rule (core or dialect). Binding in every mode,
including sketch, where it is a warn: a typo'd acknowledgement silently fails to
cover its finding. The message suggests the nearest name. P1.

#### SGC002 `ack-without-reason`
An acknowledgement has no reason after the separator. Binding; the acknowledgement
is then **ignored**, so the finding stands. P1.

#### SGC003 `ack-unused`
An acknowledgement covers no finding of that rule at its anchor (stale after an
edit). Judged only for static rules and for trace findings with a k = 1 witness:
craft explores at k = 1 and spec at k = 2, so an acknowledgement covering a k = 2-only
finding would otherwise flip between used and stale when the mode changes. Advisory,
P2.

#### SGC004 `policy-in-prose`
A trailing comment whose words match the resilience vocabulary (retry/retries,
timeout, idempotent, dedup, backoff, breaker) on a call line that carries no
matching modifier or `@inv`. The message suggests the notation form. Hint. It is
never acknowledged away: writing the modifier is the fix. The word list is data next
to CG6, so dialects can extend it. Evidence: site 02-shop:13 `charge(total) =>
{Receipt}   # 3 retries, idempotent key`; site 01:8. P1.

#### SGC090 `exploration-incomplete`
The behavioural results are partial. One finding per cause, each printing the
`Limits` in effect:

- the exploration budget left combinations out (with the count);
- a trace was `cut` (activations, stack or frames);
- a spawn ceiling was hit (`Limits.spawn`; SGC167's witness);
- a reachable loop is capped below its declared `@times N`. This is computed
  **statically** from `_reachable` regions and `_loop_count` (a pure function of
  `Block.modifiers` and `Limits`), so it needs no sim change and ships in P2. B11's
  missing log line is a viewer matter.

Hint in craft; in spec info plus a summary line. Never acknowledged. P3 (loop part
P2).

Meta rules cannot be acknowledged, except SGC003.

---

## 6. Prerequisite tool fixes (rules misfire without them)

| # | Defect | Root cause | Breaks | Fix owner |
|---|---|---|---|---|
| B1 | `!>` on a `*>` / `&` line never fires when a member fails (`<E> *> \|A\| & \|B\|` + `!> \|DLQ\|`) | `_group` / `_parallel` call `_await(guard=None)` for `&` and `*>` groups, which raises `_Fail(None)`, so `_fire_routes` skips the `("calls", …)` guard (`_parallel` passes `("block", i)`) | SGC202, SGC114, SGC201 | sim: raise the failed member's `("call", ident)` guard from `_await` for groups |
| B2 | Members of `parallel @all { … } !> …` get no failure scenario | block members are not listed as call choice points | SGC202 witness, SGC121 | sim choice points |
| B3 | `~>` failure choices are listed but ignored | `_step` forks `~>` to `_async` before any `self._choice(("call", w.ident))`, yet `choice_points` lists the wire because `resilient()` is true: 8 no-op deviations across the corpus, incl. `Primary~>Replica:fails` | SGC201, SGC112, exploration | sim: honour the call choice in `_async`, or stop listing `~>` wires as call points; a corpus test asserts every listed deviation changes the trace |
| B4 | A `branch on {R}.field` never runs | sim reachability | SGC175, branch exploration | sim |
| B5 | Nested retries are not re-driven per outer attempt | — | views only (SGC102 is static) | sim, optional |
| B6 | Trigger narrowing silently drops other machines' transitions | — | SGC145/146 (CG5), SGC203 | render, reported rather than changed |
| B7 | `×3 Retry` (a modifier alias after `×N`) loses the `×3` | parser L39 | SGC102/104/111 | parser |
| B8 | `<H>({C})` breaks the flow chain | parser L40 | SGC145/146, SGC152 | parser |
| B9 | `×N` is both cardinality and retry count | — | SGC102/104/111/163/167 | CG1 (render, P1) plus §7.3 |
| B10 | A continuation `!>` under a chained statement attaches to the first source (pitfall 4) | — | SGC202, SGC201 | parser, or a spec clarification |
| B11 | `@times 3` runs twice with no log line | — | views (SGC090 computes it statically) | sim (MG6) |
| B12 | Emitters the model does not see: a call's `=> <event>` return creates no wire (examples.md:487 `<rated>`); a tree alert `\-{lagging}-! <LagAlarm>` is not a flow (examples.md:752). Both events become phantom entries | parser / scene | SGC145, 146 (false positives); SGC204, 205 (false concurrency from phantom arrivals) | render + scene: both create emit wires |
| B13 | A failing sink behind a `^10k` stream fails the producer (examples.md:113–117), so SGC201 would anchor on `[Ingest]` instead of the consumer | failure crosses a stream / `~>` boundary upstream | SGC114, 201, 202 | sim: a failure stops at the consumer of a stream or `~>`. If the RFC wants producer failure, it must say so |
| — | NG6 not honoured: `_deliver` / `_trigger` take the first written match, so `_ -<Paid>-> Weird` before `Open -<Paid>-> Done` ends in `Weird` | sim | SGC143, SGC148 | sim: prefer a specific source over `_` (golden note) |
| — | Source-join arrival is a blocking barrier (open question 3) | `_gate` | SGC206 | sim, after the decision |

---

## 7. Positions this catalog takes (for RFC 0003 to confirm)

1. **`!>` counts as handling** for SGC201, whatever its runtime semantics. Whether a
   routed failure still fails the caller (today it does), and whether a route fires
   when `@fallback` absorbs the failure, are spec questions (open question 2). The
   checks depend only on the second, through SGC202's fallback-shadow case.
2. **Read vs write.** Declared `@read` / `@write` is the authority. A produced value
   (`=>`) is a read, a payload-less flow into a store is `unknown`, and only then
   the verb heuristic applies. A finding built on the heuristic is a guess; a write
   rule never fires on `unknown`. No new syntax.
3. **`×N`.** A glued `×N` (`[App]×N`) is cardinality (`Edge.card`, CG1). A trailing
   `×N` after a call payload is a retry. A payload-less trailing `×N`
   (`[Api] -> [Shard] ×4`) is read as cardinality, and P1 lint gives an info line
   (SGL187) suggesting the glued form. A `×N` on a node is cardinality, never a
   retry.
4. **Shared stores.** The store kind states the resolution (`~|…|` last-writer-wins,
   `*|…|` merge). A plain `|S|` with several writers needs a stated resolution
   (owner, `serialised`, `cas`, `atomic`, `immutable`); a list of writers alone
   does not state one.
5. **Recursion.** language.md's Recursion paragraph is amended: a depth or termination
   bound **may optionally** be stated (`@inv depth <= N`, `@inv terminates`). Never
   `@cap` (NG2). The rule asks and never forbids.
6. **Tiers.** Tiers are `@loc(tier)` plus `@inv layers(…)`. `--- Lk ---` stays a
   zoom level (NG4).
7. **Modifiers after any block close** (`} @inv …`, `} @deadline(t)`). The parser
   already stores them in `Block.modifiers`; the grammar adds `(mod)*` after a
   block's closing `}` (NG3), the precedent being `} @inv write-only-primary`.
8. **Transition precedence.** A specific transition beats `_` (NG6), in the spec and
   in the sim. The self-loop `S -<T>-> S` is the one idiom for "ignored on purpose"
   (NG7); there is no `@inv ignores(…)`.
9. **Instances.** `Worker<N>` is one principal for ownership and N tasks for races.
10. **Arrival model.** Independent arrivals are actor flows, events with consumers
    and no emitter, stream sources and work-starting nodes with no incoming wire.
    Entry lines from the same actor are program-ordered. An arrival is concurrent
    with itself only through concurrent(n) (cardinality, spawn, generic role, stream
    feed). The sim keeps running each entry once; the static half of SGC204 covers
    the rest.
11. **Deadlines and failures stop at async edges.** A deadline does not cross `~>`,
    a stream or a spawn (SGC101, SGC103), and a failure stops at the consumer
    (B13).
12. **Deviations are persistent per site** ("this call always fails"), explored to k
    with dependency-guided pairing.
13. **Per-sender FIFO.** Deliveries from one task to one machine arrive in program
    order.

---

## 8. Lint hardening (P1)

These come from corpus §5 (L1–L49) and survey-model §4. Every row lints clean today,
except L29 (a warning). The proposed codes use lint's free decades (12x, 13x, 15x,
16x, 18x). Silent drops are **errors in every mode**: the model loses content, so no
check downstream can be trusted.

| Code | Name | Catches | Severity |
|---|---|---|---|
| SGL120 | unclosed glyph | L1 `[Broken -> `, L5–L9 (`[A -> [B]`, `{B`, `<B`, `(A`, `\|B`), L43 `[Cache<K,V]`, L47 `[A [B]]`, L48 `[A->B]` | error |
| SGL121 | empty glyph | L12 `[]` | error |
| SGL122 | stray or mismatched closer | L10 `[A]]`, L11 `[A}`, L27 a stray `}` | error |
| SGL130 | dangling arrow / missing endpoint | L2 `[A] ->`, L3 `[A] -> : {X}`, L4 `-> [B]` with no subject, L32 `!>` with nothing above, L45 `-> op` / `-> ()`, L46 `[A] -> # …` | error |
| SGL131 | malformed arrow | L13 `-> ->`, L14 `~> !>` (drops `!>`), L15 `-->`, L16 `- >`, L17 an unknown arrow | error |
| SGL132 | stray / trailing join | L18 `& [B]`, L19 `[B] &` / `&?` / `/`, L20 `[A] & [B]` with no arrow, L21 `& -> [C]` | error |
| SGL150 | payload with no flow | L22 `[A] : {X}`, `~\|total\| : …` (examples.md:488) | warn |
| SGL151 | unclosed payload | L23 `charge(total`, L24 `${x` / `"abc`, L34 `@timeout(5s` | error |
| SGL152 | glyph after payload | L25 `: {X} [C]` | warn |
| SGL153 | event argument breaks the chain | L40 `<H>({C}) -> [R]` (or fix the parser, B8) | error until fixed |
| SGL160 | unclosed block | L26 `[A] := {` and L28 `state {X} {` never closed: **the body is dropped** | error |
| SGL161 | transition without trigger | L29 `+ -> S` inside `state` (today: empty machine) | error |
| SGL162 | empty block | L31 `branch on … { }` | warn |
| SGL163 | loop without a bound modifier | L30 `loop { … }`; the termination question itself is SGC153 | info |
| SGL180 | modifier argument | L35 `@timeout` with no argument, L36 `×` / `×0`, L37 `@timeout(-5s)`, L44 `^@drop` | error |
| SGL181 | modifier alias after `×N` | L39 `×3 Retry` (or fix the parser, B7) | error until fixed |
| SGL182 | resilience modifier off a call | L38 `@fallback` on a produce hop; `@timeout` on a non-call | warn |
| SGL183 | flow marker on a node | L49 `[A] ! -> [B]`, `[A]? ->` | warn |
| SGL184 | section header | L41 header without its closing `---`, L42 `--- L2: [Nope] ---` naming no expansion | warn |
| SGL185 | continuation across a blank line | L33 (pitfall 4 says "directly under") | warn |
| SGL186 | tree line without `\-` | `*-> [X]` under a composition tree parses as a continuation | warn |
| SGL187 | ambiguous `×N` | a trailing `×N` on a payload-less flow: suggests `[X]×N` for cardinality (§7.3) | info |
| SGL188 | reserved acknowledgement marker | the decorated marker (§10.2) with no rule name, once reserved | warn |

P1 cost: medium. Most rows are one regex or tokenizer check in `lint.py`. SGL160 and
SGL161 need the parser to report what it dropped (`Graph.dropped` lines).

---

## 9. Not checked (and why)

| Principle | Why it is left out |
|---|---|
| **fallback-unobserved** (a `@fallback` hides an outage) | Opinion, not risk handling; it would push a monitoring style on every design. It can come back as a dialect pack. |
| **Circuit breaker, bulkhead** (former SGC105, SGC164) | They ask for a component shape, not for a risk to be handled. Moved to a dialect pack (§11). |
| **Per-state missing transitions** (a static completeness matrix) | Every corpus machine has gaps (corpus §3.6). SGC203/205 report only drops that happen or depend on order; SGC146 reports dead triggers. |
| **"Recursion is unsafe" / "no sync cycles" / "no shared stores"** | Shape bans that break the one principle. Each is replaced by "state the bound / the resolution / how the cycle ends". |
| **Quantitative capacity planning** (Little's law sums, queue sizing) | Needs rates and service times the notation does not carry. SGC163 only asks. |
| **Algorithm and data-structure internals** | Pitfall 12: Sigil describes wiring, not internals. |
| **Consensus, Byzantine faults, clock skew, split brain** | Not expressible; the sim has no partitions or time beyond durations. |
| **Isolation levels beyond lost update** (write skew across two stores, phantoms) | The model has no transactions, only `@owns` scopes and `@inv atomic`. SGC133 and SGC135 cover the common cases. |
| **Security beyond the access graph** (authn flows, injection, secrets, PII) | Threat modelling. SGC132 covers what the permission graph states. |
| **Schema and version compatibility between producer and consumer** | Payloads are free text, so there are no types to compare. |
| **Event-to-instance correlation** (which `{Order}` a `<Paid>` drives) | Payloads are free text, so it is not checkable. The RFC may later bless `@inv keyed(field)`. |
| **Cancellation propagation after a caller's timeout** (beyond SGC103's budget) | Follows from §7.11 and the open `!>` semantics; revisit once open question 2 is settled. |
| **Cache stampede** | Needs rates. |
| **Handler-versus-notification double report** (examples.md:47–53: the user is notified and also sees the raw failure) | Depends on the open `!>` recovery-or-notification question (open question 2); revisit then. |
| **Exhaustive interleavings (model checking)** | Exploration is bounded by k deviations with dependency-guided pairing; HB analysis covers orderings inside an episode. Unbounded search would make the checker slow and its results unstable. |
| **Cross-document checks** | One document per run until there is an import story. |
| **Naming and style** (glyph naming, SNF order) | Lint's or the formatter's job, not composition. |

---

## 10. Acknowledgements

### 10.1 Now: a plain comment

```
[API] -> [Payments] : charge(total) ×3 @timeout(2s)   # accepts: retry-without-idempotency — charge is an upsert on order_id
```

**Grammar.** `accepts:` names separator reason.
- *names* is one or more rule names, comma-separated, in kebab case, matched against
  the core registry and any dialect rule packs.
- *separator* is `—`, `--` or ` - `.
- The reason is required (SGC002) and is printed with the acknowledged finding.

**Reading.** check.py reads acknowledgements with `render.collect_comments(lines)`,
**not** from `Graph.notes`: a probe (settling MG14) shows that collect_comments sees
every site, while Notes drop comments on a block header line, on a `}` closing line
and inside a `state { … }` block.

**Anchoring is by line:**

| Where the comment is | What it covers |
|---|---|
| trailing on a line | findings anchored on that line |
| own line(s) directly above a statement | findings anchored on the next statement line |
| own line above a block header (`parallel`, `loop`, `owns`, `branch`, `state`, `:=`) | findings anchored anywhere in `Block.lines` (or the expansion or machine body) |
| trailing on a block header or its `}` | the block, as above |
| inside an expansion or a state body | per line, as above (the line numbers are shared) |
| own line(s) before the first statement, separated from it by a blank line | **document scope**: every finding of the named rule, listed with a "document-wide" tag |

A Note above a flow anchors to the subject *node*, which would let one
acknowledgement cover every flow of `[API]`. Line anchoring is narrower and matches
what the author pointed at.

**False positives on prose.** A comment is an acknowledgement only if, after
`accepts:`, the first token is kebab case and a separator follows. `# accepts: any
JSON body` stays a note. A kebab token plus separator naming no rule is SGC001.

The text `accepts` appears nowhere in the corpus comments today (checked by grep).
Acknowledgements still render as notes in the viewers.

### 10.2 Later: a decorated comment form (decision 2)

A decorated form puts a marker character after `#`, so tools and readers tell an
acknowledgement from prose without reading the words. Taken today: `#!` (mode line),
line-leading `#&` (dialect syntax), and `-//` (one dialect marker). None of the
candidates below occurs after whitespace in the repo's `.sigil` or `.md` files.

| Marker | Example | For | Against |
|---|---|---|---|
| **`#=`** (preferred) | `#= retry-without-idempotency — upsert on order_id` | Reads as "settled". `=` is not a glyph prefix; easy to type; same in every font | `=` appears in `=>`, but never directly after `#` |
| `#+` | `#+ unguarded-call — the host enforces 5s` | Reads as "accepted" | Looks like a diff line; `+` is the initial pseudo-state |
| `#:` | `#: async-cycle — steady-state loop` | Short, reads like a label | Easy to miss next to a payload `:`; some editors treat `#:` as a pragma |

`#~` and `#?` were rejected (`~` is the mutability prefix, `?` marks holes).

1. `_COMMENT_START_RE` already treats `#=` as a comment start. `collect_comments`
   yields `kind="ack"` for the reserved marker; viewers can style it and it still
   renders.
2. The decorated form needs no `accepts:` word: its first token **must** be a rule
   name.
3. The marker becomes **reserved in core**, like `#!` and `#&`. The dialect
   `COMMENT_MARKERS` hook refuses it; lint SGL188 flags it with no rule name.
4. `# accepts: X — r` and `#= X — r` mean the same thing; both stay valid.

---

## 11. Moved out of core: an example dialect rule pack

The rule-pack hook (MG16, P4) lets a dialect register rules with its own prefix and
`@inv` heads. Two former core rules are the first candidates, kept here so the work
is not lost:

- **`unbroken-dependency`** (was SGC105): an external call on a per-request path with
  `@timeout` and retries, whose caller has no breaker. A pack may recognise
  `@inv breaker(spec)` or a state machine on the caller. Craft-only hint.
- **`shared-pool`** (was SGC164): a node making two or more external calls, one of
  them unbounded or retrying. A pack may recognise `@inv bulkhead(n)`. Craft-only
  hint; the core rule SGC101's `@timeout` already bounds how long a pool is held.

P4 ships one such pack as a test fixture to prove the hook, not as a core feature.

---

## 12. Calibration: the spec's own examples under `#!spec`

Gate (P2): every language.md worked example and every examples.md block, run as
`#!spec`, gives **zero binding findings**. Every advisory finding is either a
reviewed acknowledgement in the calibration fixture or the reason a rule was retuned.
Expected findings for language.md's examples under this rule set:

| Example | Expected findings | Disposition |
|---|---|---|
| 1 request-response | SGC163 hint (`(User)` front door, no `@sla` on `[API]`) | hint; none needed |
| 2 auth + audit | SGC145 advisory: `<Unauthorized>` is a route target nothing is named as receiving | reviewed ack, or the example adds `-> (User)` |
| | (`[Auth] -> \|UserDB\|` then `=>` is a read; `<LoginEvent> -> \|AuditLog\|` is `unknown`, so SGC113, 131, 133 and 204 stay quiet) | retuned (access unknown) |
| 3 parallel checkout | SGC111 advisory (guess: `[Payment]` has no body); SGC165 advisory (`charge ×3`, no timeout); SGC122 advisory (`release` not retryable); SGC121 hint (guess: `score` may time out after `charge` committed, no route names `[Payment]`); SGC163 hint | reviewed acks or example edits; `reserve` no longer fires (retuned SGC165) |
| 4 stream pipeline | SGC161 advisory (`\|DLQ\|` has no reader and no retention); SGC202 not reported until B1 is fixed (gate) | reviewed ack; SGC112 retuned so re-emitting stages are quiet |
| 5 state machine + worker | SGC146 advisory (case 2: nothing emits `<submit>`, so `{Job}` never leaves `+`; folds SGC203/205/147 on `{Job}` and the base hints); SGC148 advisory (`_ -<cancel>->` also leaves `Done` and `Dead`) | reviewed acks; SGC142 quiet (`Dead` has a wildcard exit) |
| 6 multi-level zoom | SGC301 hint (`write-only-primary` unchecked); SGC163 hints (`(Client)`, `[App]×N → [Data]`) | none needed; SGC172 quiet (`[Core] -> [Data]` is stated); CG1 removes the phantom `Primary~>Replica:fails` |

The examples.md blocks are recorded the same way in the P2 calibration fixture.

---

## Challenge log

86 points: 38 from the *never-limits* lens (N), 25 *computable* (C), 23
*completeness* (K). "Applied" means the catalog above reflects the fix; "partly"
names what was declined and why.

| # | Lens | Rule | Sev | Outcome |
|---|---|---|---|---|
| N1 | never-limits | GLOBAL `@inv` heads | must | **Applied.** §4 is now 17 canonical heads (from 27), one per risk, with the existing modifier preferred; language.md gets a "Recognised invariants" table via RFC 0003. Kept the 12 named heads plus `immutable` (corpus `\|PROV\|`), `retry-budget` (N35), `limit` (N32), `concurrency` (K1) and `consistent` (K10), each the only declaration for its risk. Self-loop chosen over `ignores()`. |
| N2 | never-limits | GLOBAL access heuristic | must | **Applied.** `unknown` mode; `=>` means read; write rules never fire on `unknown`; one SGC131 hint (clause c). |
| N3 | never-limits | GLOBAL calibration | should | **Applied.** P2 gate and §12 expected findings per language.md example; RFC records them. |
| N4 | never-limits | GLOBAL tier ceiling | should | **Applied.** §1.2 marks the table as an amendment to Decision 1 needing sign-off at the P0 gate; k ≥ 2-only findings cap at warn; trace findings warn-only until B1–B4 are fixed. |
| N5 | never-limits | SGC142 | must | **Applied.** Fires only when the machine uses `$`; hint; `Settled -> $` removed from the ask. |
| N6 | never-limits | SGC143 | must | **Applied.** Per-transition `@inv` on each duplicate disambiguates; distinct triggers suggested; the RFC decides the `@inv`-as-guard reading, so the rule stays binding with a real satisfier. |
| N7 | never-limits | SGC144 | must | **Applied.** Self-loops removed before SCCs; a circle needs two or more states; stated next to NG7. |
| N8 | never-limits | SGC203 (`+`) | must | **Applied.** Drops in `+` go to SGC205 with an ordering ask; `+ -<T>-> +` never suggested. Satisfiers for `+` are `@inv ordered(…)` or an acknowledgement (`ignores` is not recognised, per N1). |
| N9 | never-limits | SGC201 `!` | must | **Applied.** `!` removed; one `!> (Caller) : <Failed>` at the entry is the stated form. |
| N10 | never-limits | SGC202 fallback | must | **Applied.** Fallback shadow is advisory with the ask "should the route fire as well?"; binding only for unreachable routes; open question 2. |
| N11 | never-limits | SGC151 | must | **Applied.** RFC amends the Recursion paragraph (bound optionally stated); reply back-edges suggest `=>`. |
| N12 | never-limits | SGC171 | must | **Partly.** Reframed as "how does it avoid deadlock or end"; accepts `@timeout`/`@deadline`, `@inv depth`/`terminates`, ack; `@inv callback` dropped; `=>` suggested; never suggests rewiring. Merging into SGC151 declined: K5's split by SCC membership keeps two different questions (cross-component deadlock vs depth) under two names, with SGC151 folding SGC171 inside one component. |
| N13 | never-limits | SGC131 | must | **Applied.** `~\|S\|` and `*\|S\|` exempt; plain `\|S\|` advisory, cleared only by a resolution; multi-member `@write` no longer clears it. |
| N14 | never-limits | SGC132 | must | **Applied.** Opt-in per direction; `@cap` dropped as a satisfier. |
| N15 | never-limits | SGC303 | must | **Applied.** Both clauses fire only for the keyless form; clauses need a probe first. |
| N16 | never-limits | SGC161 | must | **Applied.** Advisory; `^N` on any occurrence; `retention`; ack. |
| N17 | never-limits | SGC121 | must | **Applied.** Forward recovery (`@fallback`, `!> *\|…\|`) counts as handling; `compensates(op)` dropped. |
| N18 | never-limits | SGC113 | should | **Applied.** Two store writes, or a write plus a stateful emit; relay store is one option. |
| N19 | never-limits | SGC114 | should | **Applied.** Binding only with `×N` and no `!>`; advisory otherwise; `^N@drop`/`@err` accepted; new ask. |
| N20 | never-limits | SGC111 | should | **Applied.** Plain value/ref assignments to scalar stores exempt. |
| N21 | never-limits | SGC104 | should | **Partly.** Any `@after`, incl. `@after(0)`, accepted. "Fire only for N ≥ 2" declined: one immediate retry still doubles load at the worst moment, the rule is advisory, and `@after(0)` is a cheap explicit answer. |
| N22 | never-limits | SGC105 | should | **Applied.** Moved to a dialect pack (§11); id retired. |
| N23 | never-limits | SGC164 | should | **Applied.** Moved to a dialect pack (§11); id retired. |
| N24 | never-limits | SGC165 | should | **Applied.** Limited to failable members (merged with K16); NG3 grammar first; `&?` not suggested. |
| N25 | never-limits | SGC166 | should | **Applied.** `!` on a node or the destination of a `!` flow; `@sla(avail…)` first in the ask. |
| N26 | never-limits | SGC145 | should | **Applied.** Base hint; advisory only when narrowed away or an unreceived route target. |
| N27 | never-limits | SGC146 | should | **Applied.** The ask says an aim narrows; an emitter / outside actor preferred; tests re-run the rule after the fix. |
| N28 | never-limits | SGC122 | should | **Applied.** Declare aligned with the query (any one); the ask notes SGC111 follows `×N`. |
| N29 | never-limits | SGC133 | should | **Applied.** `*\|S\|` kind accepted; `atomic`/`cas` listed first. |
| N30 | never-limits | SGC134 | should | **Applied.** `@deadline` on the inner call or block accepted. |
| N31 | never-limits | SGC141 | should | **Applied.** Seeds from every `+` target, or non-target states; both fixtures. |
| N32 | never-limits | SGC162 | should | **Applied.** `@inv limit(N)` for data results; `^N` only for `*{X}`. `paged` dropped as a second form (N1). |
| N33 | never-limits | SGC172 | should | **Applied.** Satisfier is stating the dependency at the outer level. |
| N34 | never-limits | SGC204 | should | **Applied.** Same-actor entries program-ordered; `@inv ordered(…)` on the actor accepted; §7.10. |
| N35 | never-limits | SGC102 | should | **Applied.** `retry-budget(p)` is the declaration; `@deadline` described as time-only. |
| N36 | never-limits | SGC306 | should | **Applied.** Not reported with `@fallback`, a route, or `&?`/`@any` membership. |
| N37 | never-limits | SGC101 | should | **Applied.** Returning actor destinations advisory with the unbounded-wait ask. |
| N38 | never-limits | SGC003 | should | **Applied.** Judged only for static rules and k = 1 trace findings. |
| C1 | computable | GLOBAL node `×` | must | **Applied.** Node-mods fallback narrowed to `@timeout`/`@deadline`/`@fallback`; node `×` is cardinality. |
| C2 | computable | GLOBAL CG1 | should | **Applied.** CG1 is a P1 render change (`Edge.card`) with goldens and scenario lists; phantom choice points noted; edge `×` is a guess until then. |
| C3 | computable | SGC204 instances | must | **Applied.** Option (a): static multiplicity predicate concurrent(n); trace detector limited to tasks the sim forks. |
| C4 | computable | SGC204 lockset | must | **Applied.** `held` recorded per access from task scopes; race = HB-unordered and lockset-disjoint; concurrent ownership is its own finding. |
| C5 | computable | SGC204 arrivals | must | **Applied.** Cross-arrival races static via `_reachable`; self-comparison only under concurrent(n); vector clocks only inside an episode; arrival model stated (§7.10). |
| C6 | computable | GLOBAL MG1 sites | must | **Applied.** Per-site events (fork incl. `_deliver` / `_begin_episode`, gate arrive/fire/resume, await/resume), cross-episode gate edges, episode recorded at fork. |
| C7 | computable | SGC203 order | must | **Applied.** One order analysis with SGC205: machine state as a shared variable, diamond check, per-sender FIFO; SGC203 only for drops in every admissible order. |
| C8 | computable | SGC205 CG3 | should | **Applied.** CG3 dropped; `Scenario(entries=perm)` for evidence; primary detector is HB pairs plus the diamond check. |
| C9 | computable | SGC143 NG6 | must | **Applied.** Wildcard-first pairs reported until the sim prefers specific sources; NG6 is a prerequisite of the exemption; sim fix in §6. |
| C10 | computable | SGC206 | must | **Applied.** Join semantics is open question 3 (deposit recommended); the probe is a fixture; MG1 only for attribution. |
| C11 | computable | SGC202 detector | must | **Applied.** `failure_flow` (CG7) in sim.py; exact; the trace only names a witness; SGC114, 121, 201 use the same "can fail". The B1 gate stays only for `*>`/`&` routes, because failure_flow mirrors today's sim until B1 is fixed. |
| C12 | computable | SGC201 detector | should | **Applied.** Static and exact over failure_flow, stopping at `~>`; trace names a witness; `_Fail.origin` only if a trace version is kept. |
| C13 | computable | GLOBAL B1/B3 | should | **Applied.** Root causes and fixes in §6; corpus test that every deviation changes the trace. |
| C14 | computable | SGC090 exploration | should | **Applied.** Dependency-guided pairing, dedupe by signature, `cid`-built scenarios, a budget reported by SGC090, k = 1 in the playground, persistent per-site semantics stated. |
| C15 | computable | SGC151 CG4 | should | **Applied.** CG4 lives in check.py; sim unchanged; `!>` removed from SGC151/152 exits. |
| C16 | computable | SGC103 algebra | must | **Applied.** Duration algebra on the collapsed DAG; symbolic `×N` skipped (also for SGC102). Races take the max over possible winners as the point says; K7's `&?` = min is open question 8. |
| C17 | computable | SGC102 algorithm | should | **Applied.** Max-product dataflow with argmax witness; recursive SCC unknown. |
| C18 | computable | SGC101 coverage | should | **Applied.** Greatest-fixpoint `covered(n)`, stopping at async edges. |
| C19 | computable | SGC113 direct | should | **Applied.** Direct effects only; emit defined as `dst kind == event` in §1.4. |
| C20 | computable | SGC152 classes | should | **Applied.** `*>`, `&`, `@all` are awaited (sync); only `~>`, `@none`, triggers, spawns are async; visit-limit ambiguity noted. |
| C21 | computable | SGC133 dynamic | should | **Applied.** Dynamic-confirmation claim dropped; shares concurrent(n) with SGC204. |
| C22 | computable | SGC134 transitive | should | **Applied.** Transitive sync callees; deepest call reported with its path. |
| C23 | computable | GLOBAL MG2 placement | should | **Applied.** Access event at the top of `_land`; `access_mode(w, graph)`; failed write attempt is open question 13. |
| C24 | computable | GLOBAL determinism | should | **Applied.** Sorting, deterministic witness, Limits printed, PYTHONHASHSEED test (§1.3). |
| C25 | computable | SGC090 loops | should | **Applied.** Loop shortfall computed statically in P2; MG6 log line is for views only. |
| K1 | completeness | NEW SGC167 | must | **Applied.** `unbounded-spawn`; spawn wires join the async graph; `concurrency <= N` recognised; `Limits.spawn` hit reported through SGC090. |
| K2 | completeness | NEW SGC147 | must | **Applied.** `wait-without-timeout`; undriven transitions left to SGC146 (folded). |
| K3 | completeness | GLOBAL B12/B13 | must | **Applied.** Both in §6 with gates on SGC145, 146, 204, 205 (B12) and SGC114, 201, 202 (B13). |
| K4 | completeness | SGC205 static | should | **Partly.** Static detector added (guess, advisory). Extending trace exploration to swap sibling emits and fork members declined: HB-unordered delivery pairs already cover orderings inside an episode without reruns (C8). |
| K5 | completeness | SGC171 split | should | **Partly.** Split by SCC membership applied (SGC151 inside a component, SGC171 across components). Declined: `@inv depth` not satisfying SGC171, `@inv callback`, and `~>` as a suggested fix, because N12 (must) requires `depth`/`terminates` to be accepted and drops `callback` and rewiring. The ask names both the deadlock and the termination reading. |
| K6 | completeness | SGC102 load | should | **Applied.** Width factor (cardinality, `*>`, `&?`) and redelivery layers across `~>`/streams; message separates retry and width factors. |
| K7 | completeness | SGC103 arithmetic | should | **Partly.** Sum / max / attempts × (timeout + backoff) and stopping propagation at `~>`, stream and spawn applied (SGC101 too). `&?` = min declined for now: it conflicts with C16 (must), which sets races to the max over possible winners; recorded as open question 8. |
| K8 | completeness | SGC121 choreography | should | **Applied.** Async-edge sagas and pivots added; `compensates(op)` replaced by "a route that emits an event the earlier component consumes" (N17). |
| K9 | completeness | NEW SGC148 | should | **Applied.** `wildcard-leaves-terminal`; satisfier is the self-loop only (N1). |
| K10 | completeness | NEW SGC135 | should | **Applied.** `stale-read`, with one head `consistent(model)` instead of three (N1). |
| K11 | completeness | SGC166 dominators | should | **Applied.** Dominator clause (hint) and `standby-unused` (hint) under the same name. |
| K12 | completeness | SGC161 queues | should | **Applied.** `~>` implicit-queue hint (with `@sla` instead of `@inv rate`, N1); `^N@block` cycle clause in SGC152; route-target store clause. |
| K13 | completeness | SGC146 generalise | should | **Applied.** Any consumed event with no emitter; hint; gated on B12. |
| K14 | completeness | SGC131 split | should | **Partly.** Precedence applied (131 folds 204/133; 204 folds 133). The proposed "131 cleared by `@write(…)` lists" declined: N13 (must) says a writer list states no resolution. |
| K15 | completeness | SGC305 | should | **Applied.** Merged into SGC173; id 305 retired. |
| K16 | completeness | SGC165 / 134 | should | **Partly.** Both narrowed so SGC101 owns the missing timeout (folded via §1.7). SGC165's "sum of member timeouts makes the tail dominant" clause declined: numeric budgets are SGC103's job. |
| K17 | completeness | SGC114 vs 201 | should | **Applied.** SGC114 folds SGC201 at stream/`~>`-fed anchors; SGC201 absorbs survey A2. |
| K18 | completeness | GLOBAL suppression | should | **Applied.** §1.7 with `implies` as registry data. |
| K19 | completeness | NEW SGC136 | should | **Applied.** `shared-data-order` hint, scoped to one loop body or fork; `@inv systems(…)` not added (N1: `ordered(…)` states it). |
| K20 | completeness | SGC163 actors | should | **Applied.** Actor entries are unbounded callers for this hint; satisfiers `@sla`, a bounded stream or `^N` (no `@inv rate`, N1). |
| K21 | completeness | NEW SGC004 | should | **Applied.** `policy-in-prose` meta hint, never acknowledged; word list is dialect-extendable data. |
| K22 | completeness | SGC112 exemption | should | **Applied.** Machine-only exemption narrowed to machines with no re-firing `T` (wildcard or self-loop). |
| K23 | completeness | GLOBAL §9 rows | should | **Applied.** Rows for correlation, cancellation propagation, stampede and double report. |

