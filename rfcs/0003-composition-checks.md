# RFC 0003 — Composition checks

- **Status:** Proposed 2026-10-02 (awaiting owner review)
- **Date:** 2026-10-02
- **Spec (to change on acceptance):** language.md "Recursion" (a bound may be
  stated), "Invariants" (a "Recognised invariants" table), "State machines"
  (specific beats `_`; the self-loop idiom), grammar (`(mod)*` after any block's
  closing `}`), a new "Checks" section; examples.md: a deliberately risky design and
  its fixed twin
- **Tools (to add or change):** `check.py` (new), `lint.py` (`--deep`, SGL120–188),
  render.py (`Edge.card`, emit wires, dropped lines), scene.py (`call_policy`,
  `access_mode`, `writers`), sim.py (`failure_flow`, structured events, defect
  fixes), view.py (`c` overlay), the playground, the SKILL
- **Catalog:** [0003-catalog.md](./0003-catalog.md) — every rule in full

## Motivation

`lint.py` checks that a document is well formed. It cannot say whether the design
the document describes is *sound*: whether a retried write is safe to repeat,
whether two components race on a store, whether a failure reaches the user with
nothing on the way saying what happens, whether a recursion or a message loop ends,
whether a state machine can get stuck. These are the questions a reviewer asks of a
system design, and most of them can be read off the wiring: the notation already
carries timeouts, retries, fallbacks, failure routes, ownership, access lists,
streams and their bounds, joins, state machines and their triggers, and the
simulator already runs the design.

The goal is to validate a design's composition, and its use of well-known systems
principles (Release It!, DDIA, sagas, single writer, happens-before), **without
limiting what can be built**. A check that says "don't build X" would turn Sigil
into a house style. A check that says "X carries a risk, and the design doesn't say
how it is handled" makes the design more explicit and leaves its shape alone.

## The one principle: explicitness, not shape

A check never forbids a shape. Every finding names a risk and is satisfied by
**declaring** how the risk is handled, in notation that already exists:

- a call's policy: `@timeout`, `@deadline`, `×N`, `@after`, `@fallback`;
- a failure route `!>`, an exit `?>`, a terminal state `$`;
- ownership and access: `@owns`, `@write(…)`, `@read(…)`, the store kinds `~|S|` and
  `*|S|`;
- a bound: `^N` on a stream, `@sla`;
- a recognised `@inv` (below);
- or an explicit, reasoned **acknowledgement**.

A design that declares its risks passes, however unusual its shape. Two corollaries
shaped every rule:

- **No rule asks for an architecture.** Breakers and bulkheads are designs, not risk
  declarations; those rules moved to a dialect pack. A rule never suggests rewiring
  (`~>` instead of `->`, "route through `[O]`", "move the call out of the block");
  it suggests a declaration and accepts the rewiring if the author chooses it.
- **No rule asks for a declaration the notation lacks.** Where a design is valid and
  the notation has no way to say so (degrade and also notify, an intentional
  unbounded wait on a human), the rule is advisory or the case is an open question,
  never a binding error.

## Modes → severity

Severity follows the existing modes (Decision 1); there is no new switch. Each rule
also has a **tier** that caps how strict it can get, because some principles are
judgement calls and making them errors would limit what can be built.

| Tier | `#!sketch` | `#!craft` | `#!spec` |
|---|---|---|---|
| **binding** | info, hidden | warn, asked as a question | **error** |
| **advisory** | info, hidden | warn, asked as a question | warn |
| **hint** | not emitted | info, asked as a question | info |

- In `#!craft` every finding is phrased as the question it asks ("`charge` is
  retried ×3. Is it idempotent, and on what key?"). In `#!spec` it is a statement
  followed by how to satisfy it.
- A finding built on a heuristic (a read/write guess, a name-based pairing) drops
  one tier and says what it guessed.
- A trace finding whose every witness needs two or more deviations caps at warn.
- Until the simulator defects B1–B4 are fixed, trace-based findings cap at warn.
- A fragment with no mode line is checked as `#!sketch`.

The tier ceiling **amends Decision 1** ("spec findings are errors"): only binding
findings become errors in spec. This needs explicit sign-off (open question 1).

## Three rule sources

### 1. Structural queries over the Scene (static)

Every rule is a predicate over the canonical Scene, the Program the simulator
builds from it, and the Graph's access list, plus a rationale and the declarations
that satisfy it. Working over `sim.canonical(graph)` means the checker and the
simulator agree on what a wire, a call, a route and an entry are. A few shared facts
carry most rules:

- **call policy** — the modifiers that govern one call. A `×N` on a node is
  cardinality, never a retry; a glued `[App]×N` moves to its own `Edge.card` field;
  only a `×N` trailing a call payload is a retry.
- **access mode** — `read`, `write`, `rw` or `unknown`. A declared `@read` /
  `@write` wins; a produced value (`=>`) is a read; a payload-less `[Svc] -> |DB|`
  is `unknown`, and no rule that needs a write fires on it.
- **failure flow** — `sim.failure_flow(prog)`, a may-fail fixpoint that mirrors the
  simulator's own failure handling (fallback absorbs, blocks relabel, groups
  await, `~>` and streams stop, routes choose). "Can fail", "is this route
  reachable", and "does this failure reach an entry unhandled" are exact static
  answers over it.
- **concurrency** — a static predicate (cardinality, spawns, generic roles, stream
  feeds, concurrent arrivals) shared by every rule that asks "can this run twice at
  once?", plus an explicit **arrival model**: actor flows, outside-cause events,
  stream sources and work-starting nodes are independent arrivals; lines from the
  same actor are program-ordered.

### 2. Behavioural properties over simulator traces (dynamic)

The simulator already models tasks, forks, joins, failures and limits. The
behavioural layer adds structured events to a trace and checks properties of them:

- **Bounded k-deviation exploration.** Today's single deviations widen to
  combinations of up to k (1 in craft and the playground, 2 in spec). A deviation is
  a *persistent per-site failure* ("this call always fails"). Pairs are chosen by
  dependency (B is paired with A only if A's deviation reaches or enables B),
  duplicates are removed by trace signature, and a time budget replaces silent
  truncation; anything left out is reported.
- **Happens-before race detection.** sim.py records fork, await/resume and gate
  arrive/fire/resume events, plus an access event for every store access with the
  stores the task holds. check.py builds vector clocks and reports two accesses to
  one store, at least one a write, that are unordered **and** hold no common
  ownership. Because traces are deterministic and the analysis does not depend on
  the scheduler, no interleaving search is needed. Concurrency the simulator does
  not fork (instances, self-concurrent arrivals) is covered by the static half.
- **Order analysis for state machines.** Each machine's state is treated as a shared
  variable and each delivery as a write; for unordered pairs of deliveries a static
  diamond check asks whether both orders are accepted and end in the same state.
  Drops that happen in every order are `event-ignored`; order-dependent ones are
  `ordering-unstated`.
- **Stalls and limits.** Tasks still waiting at the end of a run, and limit hits
  (depth, visits, spawns, loop caps), become findings or witnesses.

Behavioural rules keep one name with their static detector where both exist, so one
acknowledgement covers both.

### 3. Declared invariants (`@inv`)

A document's own `@inv` lines are checked where they are checkable. `@inv` still
takes a free expression; a short list of **recognised heads** gives the checker
something to check, one canonical declaration per risk, preferring an existing
modifier wherever one exists:

`idempotent(key)` · `dedup(key)` · `atomic(…)` · `ordered(key)` · `serialised(|S|)` ·
`cas(field)` · `immutable` · `depth <= N` · `hops <= N` · `terminates` ·
`retention(t)` · `lock-order(|A| < |B|)` · `layers(a > b > c)` ·
`retry-budget(p)` · `limit(N)` · `concurrency <= N` · `consistent(model)`

Anything else is listed as unchecked, never failed. There is no `ignores(…)` (the
self-loop `S -<T>-> S` says it), no `rate` (`@sla`), no `bounded(N)` (`^N`), and no
architecture names (`breaker`, `bulkhead`, `callback`). Dialects add heads through
the rule-pack hook. On acceptance, language.md gets this as a short "Recognised
invariants" table, so authors learn one form per risk rather than the checker's
dictionary.

## Acknowledgements

The "never limits" valve. Any finding except the meta rules can be acknowledged with
a reason:

```
[API] -> [Payments] : charge(total) ×3 @timeout(2s)   # accepts: retry-without-idempotency — charge is an upsert on order_id
```

- **Now: a comment** (Decision 2). `accepts:` then one or more rule names (kebab
  case), a separator (`—`, `--` or ` - `) and a required reason. No new syntax:
  comments are already parsed, and the form never matches ordinary prose
  (`# accepts: any JSON body` stays a note).
- **Anchoring is by line**: trailing on a line, on the line(s) directly above a
  statement, above or on a block header or its `}` (the whole block), or before the
  first statement separated by a blank line (document scope, listed as such).
- Acknowledged findings are listed separately with their reasons and do not count
  toward the exit code. Meta findings catch the failure modes of the valve itself:
  an unknown rule name (`ack-unknown-rule`), a missing reason (`ack-without-reason`,
  which voids the acknowledgement), and a stale acknowledgement (`ack-unused`).
- **Later: a decorated form.** A reserved marker after `#` (candidates: `#=`
  preferred, `#+`, `#:`) lets tools and readers tell an acknowledgement from prose
  without reading words: `#= retry-without-idempotency — upsert on order_id`. Both
  forms would stay valid and mean the same. Choosing the marker is open question 7.

## Output surfaces

- **`check.py`** (new, executable, stdlib only): `check.py design.sigil [--k N]
  [--json] [--mode sketch|craft|spec]`. Lines are lint-compatible
  (`severity:line:SGCnnn: name: message`); `--json` adds the rule name, tier, mode,
  anchor, why, how to satisfy, guess flag, witness scenario, deviation count,
  acknowledgement and folded findings. Output is sorted and stable across runs
  (tested under different hash seeds), and prints the simulator limits in effect.
- **`lint.py --deep`** runs check.py after lint and merges the two reports.
- **view.py**: a `c` overlay marks offending nodes and wires in both the graph and
  the tree view, with the finding's question in the side panel.
- **The playground** shows findings beside lint diagnostics, exploring at k = 1.
- **The SKILL** tells agents to run `check.py` in craft and spec, to put each
  finding to the user as its question, and to resolve it by a declaration or an
  acknowledgement, never by reshaping a design the user did not ask to change.

**One defect, one finding.** Rules declare which other rules they imply at a given
scope (an undriven machine implies its ignored events; a store with no stated
resolution implies its races; a missing timeout implies the join-tail and held-lock
questions on that call). Implied findings are folded into the cause's message as
"also: …" and do not count separately.

## Rule catalog (summary)

Ids are `SGC` + 3 digits (hundreds: 0 meta, 1 structural, 2 behavioural, 3
invariants; tens: the family). People type the **name**, never the id. The full
entries — risk, principle and sources, query, satisfying declarations, tier and ask,
false-positive analysis, corpus evidence — are in
[0003-catalog.md](./0003-catalog.md).

| Id | Name | Layer | Phase |
|---|---|---|---|
| SGC001 | ack-unknown-rule | meta | P1 |
| SGC002 | ack-without-reason | meta | P1 |
| SGC003 | ack-unused | meta | P2 |
| SGC004 | policy-in-prose | meta | P1 |
| SGC090 | exploration-incomplete | meta | P3 (loop caps P2) |
| SGC101 | unguarded-call | structural | P2 |
| SGC102 | retry-amplification | structural | P2 |
| SGC103 | timeout-budget-inverted | structural | P2 |
| SGC104 | retry-without-backoff | structural | P2 |
| SGC111 | retry-without-idempotency | structural | P2 |
| SGC112 | duplicate-delivery | structural | P2 |
| SGC113 | dual-write | structural | P2 |
| SGC114 | poison-message | structural | P2 |
| SGC121 | saga-uncompensated | structural | P2 |
| SGC122 | fragile-compensation | structural | P2 |
| SGC123 | race-loser-effects | structural | P2 |
| SGC131 | shared-writable-store | structural | P2 |
| SGC132 | undeclared-access | structural | P2 |
| SGC133 | lost-update | structural | P2 |
| SGC134 | held-across-call | structural | P2 |
| SGC135 | stale-read | structural | P2 |
| SGC136 | shared-data-order | structural | P2 |
| SGC141 | unreachable-state | structural | P2 |
| SGC142 | dead-end-state | structural | P2 |
| SGC143 | ambiguous-transition | structural | P2 |
| SGC144 | no-exit | structural | P2 |
| SGC145 | orphan-event | structural | P2 |
| SGC146 | undriven-transition | structural | P2 |
| SGC147 | wait-without-timeout | structural | P2 |
| SGC148 | wildcard-leaves-terminal | structural | P2 |
| SGC151 | unbounded-recursion | structural (+ trace witness) | P2 / P3 |
| SGC152 | async-cycle | structural (+ trace witness) | P2 / P3 |
| SGC153 | unbounded-loop | structural | P2 |
| SGC161 | unbounded-buffer | structural | P2 |
| SGC162 | unbounded-result | structural | P2 |
| SGC163 | capacity-mismatch | structural | P2 |
| SGC165 | fanout-tail | structural | P2 |
| SGC166 | single-point-of-failure | structural | P2 |
| SGC167 | unbounded-spawn | structural | P2 |
| SGC171 | dependency-cycle | structural | P2 |
| SGC172 | expansion-escape | structural | P2 |
| SGC173 | lock-order-cycle | structural | P2 (declared order P4) |
| SGC174 | optional-callee | structural | P2 |
| SGC175 | unreached | structural | P3 |
| SGC201 | unhandled-failure | behavioural (static, exact) | P2 / P3 |
| SGC202 | dead-failure-route | behavioural (static, exact) | P2 / P3 |
| SGC203 | event-ignored | behavioural | P3 |
| SGC204 | race | behavioural (static + trace) | P2 / P3 |
| SGC205 | ordering-unstated | behavioural | P3 |
| SGC206 | stalled-join | behavioural | P3 |
| SGC301 | inv-unchecked | invariant | P4 |
| SGC302 | inv-dangling | invariant | P4 |
| SGC303 | inv-contradicted | invariant | P4 |
| SGC304 | layer-inversion | invariant | P4 |
| SGC306 | timeout-below-sla | invariant | P4 |

55 core rules. SGC105 (`unbroken-dependency`) and SGC164 (`shared-pool`) are
retired from core and offered as an example dialect pack; SGC305 merged into
SGC173. Retired ids are never reused.

**Calibration.** Before the structural rules ship, every language.md worked example
and every examples.md block is run as `#!spec` and must give zero binding findings;
each advisory finding becomes a reviewed acknowledgement in a fixture or retunes a
rule. Expected findings for language.md's examples:

| Example | Expected |
|---|---|
| 1 request-response | `capacity-mismatch` hint |
| 2 auth + audit | `orphan-event` advisory (`<Unauthorized>`: nothing is named as receiving it) |
| 3 parallel checkout | `retry-without-idempotency` (guess), `fanout-tail`, `fragile-compensation` advisories; `saga-uncompensated` hint (guess); `capacity-mismatch` hint |
| 4 stream pipeline | `unbounded-buffer` advisory (`\|DLQ\|` has no reader or retention); `dead-failure-route` held back until B1 is fixed |
| 5 state machine + worker | `undriven-transition` advisory (nothing emits `<submit>`; folds the machine's other findings); `wildcard-leaves-terminal` advisory |
| 6 multi-level zoom | `inv-unchecked` hint; `capacity-mismatch` hints |

## Model changes needed

The checker reads the model; it does not re-parse. The changes below keep existing
fields and outputs stable except where a defect fix changes a run (goldens are
updated in the same phase).

- **render.py**
  - `Edge.card`: a `×N` glued to the destination glyph is cardinality, recorded apart
    from `Edge.mods` (which keeps meaning retries). Removes phantom failure choices
    such as `Primary~>Replica:fails`.
  - Emit wires for `=> <E>` call returns and tree alerts `\-{c}-! <E>`; today both
    events become phantom entries.
  - `find_triggers` also returns the pairs that narrowing removed.
  - `Graph.dropped`: lines the parser discarded (unclosed blocks, transitions
    without triggers), so lint can report silent drops.
  - Parser fixes: `×3 Retry` loses the `×3`; `<H>({C})` breaks the chain.
- **scene.py**: `call_policy(w)` (wire plus source-side modifiers), `access_mode(w,
  graph)` (shared by the static rules and the simulator), `writers(store)`.
- **sim.py**
  - `failure_flow(prog)`, beside the functions it mirrors.
  - Public `reachable` and `route_guard`.
  - Structured events in `Trace.end["events"]`: fork (with parent, including
    deliveries and episode starts), gate arrive/fire/resume, await/resume, access
    (with held stores), failure, limit hit, ignored delivery, quiet. Each task
    records its episode at fork time.
  - `combinations(sc, k)` with dependency-guided pairing and scenarios built from
    choice ids.
  - Defect fixes: a failed `&` / `*>` member raises its own guard, so the line's
    `!>` fires (B1); block members get failure choices (B2); `~>` failure choices
    are honoured or not listed (B3); field branches run (B4); a failure stops at the
    consumer of a stream or `~>` (B13); a specific transition beats `_`; and,
    depending on open question 3, a source join becomes a non-blocking deposit.
  - Declared bounds never change a run: check.py compares `@inv depth <= N` with the
    simulator's limits and reports both.
- **lint.py**: SGL120–188 (unclosed glyphs, dangling arrows, malformed arrows and
  joins, unclosed payloads and blocks, transitions without triggers, modifier
  arguments, ambiguous `×N`, the reserved acknowledgement marker, …); `--deep`.
- **dialects.py**: a rule-pack hook (rules, recognised `@inv` heads, read verbs,
  prose policy words), and refusal of the reserved acknowledgement marker in
  `COMMENT_MARKERS`.

## User-written declarative rules (deferred)

Rules written by users as Sigil patterns are deferred (Decision 3), but the registry
is shaped for them. Each rule is a record, not a free-form function:

```
Rule(id, name, layer, family, tier, ask, why, fix,
     match,        # code today; a pattern later
     satisfiers,   # data: (site, form) pairs that clear a candidate
     implies,      # data: rules folded into this one at a scope
     guess)        # heuristics the match used
```

Most of a rule's meaning is "this shape, unless one of these declarations is
present". `satisfiers` and `implies` are data, so a declarative front end only has
to produce `match`. Dialect rule packs use the same record, with their own id prefix
and names that never reuse a core name.

## Alternatives considered

- **Shape bans** ("no sync cycles", "no shared stores", "recursion is unsafe").
  Rejected: they forbid valid designs. Each became "state the bound / the resolution
  / how it ends".
- **A new strictness switch** (`--strict`, per-rule severities in the document).
  Rejected: the modes already express how settled a design is (Decision 1).
- **New modifiers for every risk** (`@idempotent`, `@breaker`, `@ignores`).
  Rejected by pitfall 15; the existing `@inv expr` with a short recognised list
  carries them.
- **A large recognised `@inv` vocabulary** (the first draft had 27 heads, several
  duplicating `^N`, `@sla` and the self-loop). Rejected: two forms per risk make
  authors learn the checker's dictionary.
- **Reading `--- Lk ---` sections as architectural tiers.** Rejected: sections are
  zoom levels. Tiers are `@loc(tier)` with `@inv layers(…)`.
- **Exhaustive interleaving search / model checking.** Rejected: slow, and unstable
  results. Happens-before analysis over deterministic traces plus a static diamond
  check covers orderings inside an episode; a static arrival model covers the rest.
- **Trace-only detectors for failure handling.** Rejected: the simulator discards
  failure identity across re-raises, and route choice is static anyway; a static
  fixpoint mirroring the simulator is exact and cheaper, and traces name witnesses.
- **Changing simulator bounds from declarations** (a declared depth becomes the
  simulator's depth). Rejected: the simulator's contract is that declarations do not
  affect a run.
- **Acknowledgements in a separate file.** Rejected: an acknowledgement belongs next
  to what it accepts, and comments are already parsed and anchored.

## Open questions for the reviewer

1. **Tier ceiling (amends Decision 1).** Only binding findings become errors in
   `#!spec`; advisory ones stay warnings, hints stay info; k ≥ 2-only findings and
   (until B1–B4 are fixed) trace findings cap at warn. Accept?
2. **`!>` with `@fallback`.** When a fallback absorbs a failure, does the route still
   fire ("notify, then yield")? If yes, a fallback no longer shadows a route; if no,
   "degrade and alert" has no notation. Until decided, the shadow case is advisory.
3. **Source-join semantics.** Is an `&` arrival a non-blocking deposit (the arriver
   continues, the last arriver fires; recommended, matching the notation's dataflow
   reading) or a blocking barrier (today's simulator, which stalls
   `[S] -> [A]`, `[S] -> [B]`, `[A] & [B] -> [C]` on the happy path)?
4. **Recognised invariants.** The 17 heads above, one per risk, with `ignores(…)`
   dropped in favour of the self-loop. Accept the list, and its addition to
   language.md?
5. **Recursion.** Amend the Recursion paragraph so a depth or termination bound may
   optionally be stated (`@inv depth <= N`, `@inv terminates`)?
6. **`×N` placement.** Glued `[App]×N` and node `×N` are cardinality; a `×N`
   trailing a call payload is a retry; a payload-less trailing `×N` reads as
   cardinality with an info hint. Accept?
7. **Acknowledgement marker.** Reserve `#=` now (unused, but reserved), or wait
   until the plain form is in use?
8. **Races in the timeout budget.** For `&?` / `parallel @any`, should the worst case
   be the max over members that can win (fewer missed inversions) or the min (fewer
   false errors, since the rule is binding)? The draft uses the max.
9. **Events as principals.** May `@write(…)` name an event (`<stop>` writing
   `~|running|`), or must the write go through a component?
10. **Actor arrivals.** Is a design's `(User)` one sequential caller (the draft) or
    many concurrent ones? The answer decides whether `lost-update` and `race` treat
    every actor entry as concurrent with itself.
11. **Value-operator writes.** Is a single `~|n| : ${state.n} + 1` atomic? The draft
    says no.
12. **Transition precedence.** Specific beats `_`, in the spec and in the
    simulator (a run changes for documents that write `_` first). Accept?
13. **Failed writes.** Does a write attempt that failed (timed out) count as an
    access with an unknown outcome for race detection? The draft says yes.
