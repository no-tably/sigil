# Calibration: the spec's own examples under `#!spec`

The P2 calibration gate (RFC 0003 "Calibration", catalog §12). Every worked example
of language.md (its "Worked examples" section) and every Sigil block of examples.md
is checked as `#!spec` with every rule module present. This file records each
finding the run gives, and tests/test_check_state.py (`Calibration`) asserts the
record and the run agree, finding for finding.

Each entry is `- file · rule · severity · `the line it is on``, followed by its
disposition:

- **accepted** — an advisory finding reviewed and acknowledged here: the example
  leaves the risk open on purpose (it shows another construct), and the reason says
  what declaration would close it.
- **noted** — a hint (info in spec); no disposition is required, the note says why
  it is expected.
- **open** — not yet resolved; the reason names the role that resolves it. The gate
  is met when no binding (error) finding remains, so an open error blocks it.
- **shown** — the example raises the finding on purpose, to show the rule (examples.md
  Example Q's risky half); its declared twin is the same design with every risk
  declared and gives none. Allowed at any severity: a shown error does not block the
  gate, since the twin, not the risky half, is the design.

Retuned rules (recorded for the catalog): SGC153 counts a flow on the condition's
store whose verb is no read verb as changing it (`pop => {Job}` drains `|Q|`;
language.md Example 5 is no longer asked); SGC172 looks only at component-to-
component wires (a data glyph inside an alias body is no dependency). The catalog's
SGC135 evidence (examples.md:750–751) does not hold: nothing in that block writes
`|Primary|`, so the rule is quiet there.

The gate covers language.md's "Worked examples" section only, as catalog §12 says;
the reference fragments elsewhere in language.md are not designs (`[Worker] -> run()
@timeout(30s)` under "SLAs and timing" would give unhandled-failure as an error).

Folded findings do not appear: an `undriven-transition` case 2 folds its machine's
`wait-without-timeout` and `ordering-unstated`; a `shared-writable-store` folds its
store's races.

## language.md
- language.md · capacity-mismatch · info · `(User) -> [Auth] : {creds}`
  noted — hint (catalog §12)
- language.md · orphan-event · warn · `!> <Unauthorized>`
  accepted — the example routes the refusal to an event and leaves its receiver outside the design; adding `<Unauthorized> -> (User)` would say so (catalog §12, Example 2)
- language.md · capacity-mismatch · info · `(User) -> [API] : {Cart}`
  noted — hint (catalog §12)
- language.md · retry-without-idempotency · warn · `[API] -> [Payment]   : charge  ×3 @after(exp-backoff, cap=1min)`
  accepted — a guess: `[Payment]` has no body, so `charge` reads as a write; the example does not say charge is idempotent (catalog §12, Example 3)
- language.md · saga-uncompensated · info · `[API] -> [Payment]   : charge  ×3 @after(exp-backoff, cap=1min)`
  noted — hint (catalog §12)
- language.md · fanout-tail · warn · `[API] -> [Payment]   : charge  ×3 @after(exp-backoff, cap=1min)`
  accepted — `charge ×3` has no timeout inside `parallel @all` (catalog §12, Example 3)
- language.md · saga-uncompensated · info · `[API] -> [Fraud]     : score   @timeout(500ms)`
  noted — hint (catalog §12)
- language.md · fragile-compensation · warn · `!> [Inventory] : release({Hold})`
  accepted — `release` is not retried if it fails (catalog §12, Example 3)
- language.md · unbounded-buffer · warn · `!> |DLQ|`
  accepted — the dead-letter store's reader and retention are outside the example (catalog §12, Example 4)
- language.md · fanout-tail · warn · `*<Enriched>    *> |Warehouse| & |RealtimeIdx|`
  accepted — the fan-out member `|Warehouse|` has no timeout, so one slow member holds the `&` join (Example 4); `@timeout(t)` on the member would bound it
- language.md · fanout-tail · warn · `*<Enriched>    *> |Warehouse| & |RealtimeIdx|`
  accepted — the fan-out member `|RealtimeIdx|` has no timeout, so one slow member holds the `&` join (Example 4); `@timeout(t)` on the member would bound it
- language.md · undriven-transition · warn · `+         -<submit>->    Pending`
  accepted — case 2: the example shows the lifecycle, and `<submit>` comes from a client the example leaves out; it folds the machine's waits (catalog §12, Example 5)
- language.md · wildcard-leaves-terminal · warn · `_         -<cancel>->    Cancelled`
  accepted — a late `<cancel>` leaving `Done` and `Dead` is what the example says; a self-loop on each would state otherwise (catalog §12, Example 5)
- language.md · capacity-mismatch · info · `(Client) -> [Edge] -> [Core] -> [Data]`
  noted — hint (catalog §12)
- language.md · capacity-mismatch · info · `[App] -> [Data]`
  noted — hint (catalog §12)
- language.md · unbounded-buffer · info · `[Primary] ~> [Replica]×2`
  noted — hint for a `~>` queue (catalog SGC161)
- language.md · inv-unchecked · info · `} @inv write-only-primary`
  noted — hint: an unrecognised @inv is listed as taken on trust, never failed (catalog SGC301)

## examples.md
- examples.md · capacity-mismatch · info · `(User) -> [Web]  : {creds}`
  noted — hint (catalog §12)
- examples.md · orphan-event · warn · `!> <Unauthorized>`
  accepted — the example routes the refusal to an event and leaves its receiver outside the design; adding `<Unauthorized> -> (User)` would say so (catalog §12, Example 2)
- examples.md · capacity-mismatch · info · `(User) -> [API] : {Cart}`
  noted — hint (catalog §12)
- examples.md · retry-without-idempotency · warn · `[API] -> [Payment]   : charge  ×3 @after(exp-backoff, cap=1min)`
  accepted — a guess: `[Payment]` has no body, so `charge` reads as a write; the example does not say charge is idempotent (catalog §12, Example 3)
- examples.md · saga-uncompensated · info · `[API] -> [Payment]   : charge  ×3 @after(exp-backoff, cap=1min)`
  noted — hint (catalog §12)
- examples.md · fanout-tail · warn · `[API] -> [Payment]   : charge  ×3 @after(exp-backoff, cap=1min)`
  accepted — `charge ×3` has no timeout inside `parallel @all` (catalog §12, Example 3)
- examples.md · saga-uncompensated · info · `[API] -> [Fraud]     : score   @timeout(500ms)`
  noted — hint (catalog §12)
- examples.md · fragile-compensation · warn · `!> [Inventory] : release({Hold})`
  accepted — `release` is not retried if it fails (catalog §12, Example 3)
- examples.md · undriven-transition · warn · `+         -<submit>->    Pending`
  accepted — case 2: the example shows the lifecycle, and `<submit>` comes from a client the example leaves out; it folds the machine's waits (catalog §12, Example 5)
- examples.md · wildcard-leaves-terminal · warn · `_         -<cancel>->    Cancelled`
  accepted — a late `<cancel>` leaving `Done` and `Dead` is what the example says; a self-loop on each would state otherwise (catalog §12, Example 5)
- examples.md · unbounded-buffer · warn · `!> |DLQ|`
  accepted — the dead-letter store's reader and retention are outside the example (catalog §12, Example 4)
- examples.md · fanout-tail · warn · `*<Enriched>    *> |Warehouse| & |RealtimeIdx|`
  accepted — the fan-out member `|Warehouse|` has no timeout, so one slow member holds the `&` join (Example 4); `@timeout(t)` on the member would bound it
- examples.md · fanout-tail · warn · `*<Enriched>    *> |Warehouse| & |RealtimeIdx|`
  accepted — the fan-out member `|RealtimeIdx|` has no timeout, so one slow member holds the `&` join (Example 4); `@timeout(t)` on the member would bound it
- examples.md · capacity-mismatch · info · `(Client) -> [Edge] -> [Core] -> [Data]`
  noted — hint (catalog §12)
- examples.md · capacity-mismatch · info · `[App] -> [Data]`
  noted — hint (catalog §12)
- examples.md · unbounded-buffer · info · `[Primary] ~> [Replica]×2`
  noted — hint for a `~>` queue (catalog SGC161)
- examples.md · capacity-mismatch · info · `(User) -> [?] : {Intent}`
  noted — hint (catalog §12)
- examples.md · capacity-mismatch · info · `(Customer) -> [StorefrontAPI] -> [LoginService] -> |Users| => {SessionToken}`
  noted — hint (catalog §12)
- examples.md · capacity-mismatch · info · `(Shopper) -> [WebGateway] -> [AuthLambda] -> |CustomerStore| => {JWT}`
  noted — hint (catalog §12)
- examples.md · retry-without-idempotency · warn · `[API] -> [Payment] : charge ×3 Retry`
  accepted — a guess: `[Payment]` has no body, so `charge` reads as a write; the example does not say charge is idempotent (catalog §12, Example 3)
- examples.md · saga-uncompensated · info · `[API] -> [Payment] : charge ×3 Retry`
  noted — hint (catalog §12)
- examples.md · retry-without-idempotency · warn · `[API]  -> [Payment]   : charge  ×3 Retry`
  accepted — a guess: `[Payment]` has no body, so `charge` reads as a write; the example does not say charge is idempotent (catalog §12, Example 3)
- examples.md · saga-uncompensated · info · `[API]  -> [Payment]   : charge  ×3 Retry`
  noted — hint (catalog §12)
- examples.md · undriven-transition · warn · `+          -<assert>->      live`
  accepted — case 2: the provenance machine is driven from outside the excerpt (catalog evidence 389); it folds the machine's ordering and wait questions
- examples.md · async-cycle · warn · `|PROV| -> [MCP.r] -> {Payload} -> [Agent]`
  accepted — the core read/write loop is the design's main cycle and runs per request (catalog evidence 399–400); `@inv hops <= N` would bound it
- examples.md · orphan-event · info · `[Agent] ~> <Unroll>     # walk wasDerivedFrom backward`
  noted — hint: published for an outside consumer (catalog evidence 408)
- examples.md · orphan-event · info · `[Agent] ~> <Verify>     # unroll + re-check antecedents`
  noted — hint: published for an outside consumer (catalog evidence 409)
- examples.md · undriven-transition · info · `<stop>  -> ~|running| : false`
  noted — hint: `<stop>` is the operator's outside cause (catalog evidence 481)
- examples.md · unbounded-loop · info · `loop @while node {`
  noted — hint: the planner loop ends when the planner yields no node (catalog evidence 537)
- examples.md · unbounded-buffer · warn · `[Planner] => *|visited| : ${state.visited} ++ [${out.node}]`
  accepted — the planner's visited set grows for one run only; `@inv retention(t)` would say so
- examples.md · unbounded-spawn · warn · `\-*-> [Bullet]`
  accepted — the arena sketch spawns bullets per shot with no ceiling stated
- examples.md · unbounded-spawn · warn · `[Spawner]  => [Shard]`
  accepted — the arena sketch spawns shards per destroyed asteroid with no ceiling stated; `×N` on `[Shard]` or `@inv concurrency <= N` on `[Spawner]` would bound it
- examples.md · capacity-mismatch · info · `(Shopper)  -> [Checkout] -> {Order}`
  noted — hint (catalog §12)
- examples.md · ordering-unstated · warn · `+     -<Placed>->    Open`
  accepted — the runs show `<Paid>` reaching `{Order}` / `[Checkout]` before `<Placed>` from two independent arrivals; `@inv ordered(order_id)` would state the order (catalog SGC205 evidence: site 04 lines 7–8, examples.md lines 655–669)
- examples.md · wait-without-timeout · warn · `Open  -<Paid>->      Settled`
  accepted — the checkout sketch waits on the shopper's payment with no expiry; an `@after(t)` transition would state one (catalog evidence site 04, examples.md:655–669)
- examples.md · ordering-unstated · warn · `Idle  -<Placed>->    Busy`
  accepted — the runs show `<Paid>` reaching `{Order}` / `[Checkout]` before `<Placed>` from two independent arrivals; `@inv ordered(order_id)` would state the order (catalog SGC205 evidence: site 04 lines 7–8, examples.md lines 655–669)
- examples.md · capacity-mismatch · info · `(User)       -> [Router] : {Query}`
  noted — hint (catalog §12)
- examples.md · optional-callee · info · `[Search]     -> [ShardQuery] => {Hits}`
  noted — hint: the composition sketch shows conditional and standby children; a route or `@fallback` would say what happens when one is absent
- examples.md · capacity-mismatch · info · `(User)       -> [Payments] -> [PrimaryPsp] : {Charge}`
  noted — hint (catalog §12)
- examples.md · optional-callee · info · `(User)       -> [Payments] -> [PrimaryPsp] : {Charge}`
  noted — hint: the composition sketch shows conditional and standby children; a route or `@fallback` would say what happens when one is absent
- examples.md · optional-callee · info · `[Payments]   -> [StandbyPsp] : {Charge}`
  noted — hint: the composition sketch shows conditional and standby children; a route or `@fallback` would say what happens when one is absent
- examples.md · shared-writable-store · warn · `[Planner] -> |Shared|`
  accepted — the permission example lists three writers to show a shared store; a list states no resolution (catalog evidence 814)
- examples.md · inv-unchecked · info · `} @inv write-only-primary`
  noted — hint: an unrecognised @inv is listed as taken on trust, never failed (catalog SGC301)
- examples.md · inv-unchecked · info · `[MCP.r] @inv excludes({Entity}.state ∈ {superseded, retracted})`
  noted — hint: an unrecognised @inv is listed as taken on trust, never failed (catalog SGC301)
- examples.md · inv-unchecked · info · `[MCP.r] @inv surfaces-flagged({Entity}.state = disputed)`
  noted — hint: an unrecognised @inv is listed as taken on trust, never failed (catalog SGC301)
- examples.md · inv-unchecked · info · `{Summary} @inv wasDerivedFrom({Concept}.hash)`
  noted — hint: an unrecognised @inv is listed as taken on trust, never failed (catalog SGC301)
- examples.md · inv-unchecked · info · `|PROV|    @inv content-addressed(id = hash(canonical))`
  noted — hint: an unrecognised @inv is listed as taken on trust, never failed (catalog SGC301)
- examples.md · inv-unchecked · info · `{Payload} @inv extension-only`
  noted — hint: an unrecognised @inv is listed as taken on trust, never failed (catalog SGC301)
- examples.md · inv-unchecked · info · `[MCP.r]   @inv semantic-surface(no raw graph queries)`
  noted — hint: an unrecognised @inv is listed as taken on trust, never failed (catalog SGC301)
- examples.md · inv-unchecked · info · `[MCP.w]   @inv validates-before-commit`
  noted — hint: an unrecognised @inv is listed as taken on trust, never failed (catalog SGC301)
- examples.md · inv-unchecked · info · `{Entity}  @inv lifecycle-transitions-explicit`
  noted — hint: an unrecognised @inv is listed as taken on trust, never failed (catalog SGC301)
- examples.md · capacity-mismatch · info · `(User)×N -> [Booking] : book({Seat})`
  shown — Example Q's risky half raises it on purpose; its declared twin `--- booking-declared ---` declares the risk and gives no finding (ExampleQ in tests/test_check_state.py)
- examples.md · lost-update · warn · `[Booking] -> ~|Seats| : ${state.Seats} - 1`
  shown — Example Q's risky half raises it on purpose; its declared twin `--- booking-declared ---` declares the risk and gives no finding (ExampleQ in tests/test_check_state.py)
- examples.md · retry-without-idempotency · error · `[Booking] -> [Payments] : charge({Seat}) ×3`
  shown — Example Q's risky half raises it on purpose; its declared twin `--- booking-declared ---` declares the risk and gives no finding (ExampleQ in tests/test_check_state.py)
- examples.md · saga-uncompensated · info · `[Booking] -> [Payments] : charge({Seat}) ×3`
  shown — Example Q's risky half raises it on purpose; its declared twin `--- booking-declared ---` declares the risk and gives no finding (ExampleQ in tests/test_check_state.py)
- examples.md · unguarded-call · error · `[Payments] -> [Card] : op card.charge(${total})`
  shown — Example Q's risky half raises it on purpose; its declared twin `--- booking-declared ---` declares the risk and gives no finding (ExampleQ in tests/test_check_state.py)
- examples.md · unhandled-failure · error · `[Payments] -> [Card] : op card.charge(${total})`
  shown — Example Q's risky half raises it on purpose; its declared twin `--- booking-declared ---` declares the risk and gives no finding (ExampleQ in tests/test_check_state.py)
- examples.md · orphan-event · info · `[Booking] ~> <Booked>`
  shown — Example Q's risky half raises it on purpose; its declared twin `--- booking-declared ---` declares the risk and gives no finding (ExampleQ in tests/test_check_state.py)
