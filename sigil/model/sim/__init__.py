"""
sigil.model.sim — the simulation engine: runs a design's pathways over the Scene.

Not a command: the views and the app load it. Sigil has no execution semantics
of its own; this is the simulator's reading of a design — tokens moving along
Scene wires so a reader sees the happy path, each failure route, each branch,
race and alternative. No values are computed, nothing is evaluated, no time
passes except ticks. This docstring is the contract the views rely on; the
construct-by-construct rules are stated here and on the functions that apply them.

    from sigil.model.sim import scenarios, simulate, project
    for sc in scenarios(scene):
        trace = simulate(scene, sc)            # a list of Frames, one per tick
        shown = project(trace, view_scene)     # the same run, named as a view draws it

Pure and deterministic: simulate() is a function of its arguments — no clock,
no randomness, no I/O. Every choice comes from the Scenario; every order is
written order (the Scene's wire order). Every loop, recursion, cycle, spawn and
the trace length are bounded by Limits (the default frames and activations limits
grow with the document: scaled, sized). A document may set its own on its `#%`
line (`#% daemon frames=300000`): limits_for merges the defaults, those and
--limit's flags (a flag wins), limit_sources says where each came from; hitting a
bound is logged. No drawing
code: it reads sigil.model.scene (and through it the parsed model) only.

The package, part by part (program ← engine ← scenarios / narration):

    program     the records, the Scene compiled into a Program, static facts
    engine      one run: simulate(scene, scenario) → Trace
    scenarios   failure flow, choice points, scenarios, overlaps, exploration
    narration   timeline, project, narrate / hops

Every public name below is importable from the package itself.

THE RUN

The simulator always runs on the CANONICAL scene (canonical()): every unit,
every event a node, every trigger wired to the state it enters. Frames name
wires by Wire.ident and nodes by node id; project() maps them onto the Scene a
view draws (events drawn where they land, a shallower depth).

  activation  one run of one node's work in one unit: its body (its outgoing
              work wires in that unit, written order), its `!>` routes on failure
  task        a thread of control: a stack of activations. A sync call pushes
              onto the caller's task; `~>`, a fan-out member, a trigger and a
              parallel member each start a task. Tasks run in id order per tick
  token       travels one wire, `at` 0 → 1 (a return 1 → 0 on the call's wire)
  tick        one Frame. A hop takes Limits.hop ticks (a self-call 1); the
              task's next turn is the tick after the arrival
  episode     one per entry. An entry the scenario gives a start tick
              (Scenario.starts) begins at that tick, whether or not earlier
              episodes still run; the others run one after another, each the
              tick after the run went quiet (no task with a turn or hop to
              come). Running episodes share the tick: their tasks take turns in
              task-id order, as one episode's do. A task belongs to its
              parent's episode (an entry's root: the one it begins); per-episode
              limits (visits, activations) count each episode's own. Entries:
              the document's nodes with work and no incoming flow (or actors),
              in written order

  Wires: `->` `→` `<->` sync call (and its return); `~>` fork, don't wait;
  `*>` and a `&` target fork all and wait for all; `&?` the scenario's winner;
  `/` the chosen member; `=>` a produce hop (into a spawned child: one more
  instance); `?>` only when the scenario takes it (a join's `?>` members too);
  `!>` only on failure. A join's members are resolved first, then its arrow
  runs them: on `~>` forked unawaited. A source join (`[A] & [B] -> [C]`) is
  a deposit, never a barrier: each member deposits and goes on, and the last
  arrival runs the target (`&?`: the first; later ones are dropped).
  A failure stops the activation it reaches, fires its routes (those guarded
  by the failed block or call first, else its unguarded ones), ends it failed and
  unwinds the sync stack. An awaited member (`*>`, an `&` target, a race's
  winner) fails its waiter as its own call, so its line's routes fire. A
  failure never crosses an async edge: a `~>` send (whose own failure the
  scenario may choose too), a `=>` produce hop or a flow into a stream stops
  it at the consumer ("not awaited"); the producer goes on.

  Resilience: a failing call makes attempts() tries; a call that arrives and
  whose callee's work fails (a nested call the scenario fails) is not retried —
  it made one attempt, and its failure says so ("failed after 1 attempt (its
  callee failed)"): the scenario names which call fails, so a retry could only
  replay the same failure. On a call's final failure `@fallback(x)` fires the
  caller's routes guarded by that call ("notify, then yield"), returns x and
  the caller goes on as ok; `!` critical ends the run. A self-call is a
  one-tick pulse; recursion stops at Limits.depth (the base case). An external
  op's far node is opaque. Blocks: `loop` repeats its region (`@times N`, capped
  by Limits.iterations), `parallel` forks it (@all waits, @any races, @none
  doesn't wait), `branch` runs the chosen arm only; a block repeats or forks only
  on its outermost entry on a task; a branch on a value's field (`branch on
  {R}.kind`) decides where it is written, as one with no header glyph does. State
  machines start in `+` (or the source of their first written transition, or the
  state the scenario names: Scenario.machines); an
  event delivers its triggers (a transition written from the machine's state
  beats a `_` one), then runs its body. An expansion is a closer reading of the same node: its entries run first,
  then the node's body minus its summary wires (out-wires to a target the
  expansion already reaches: the detail carries the traffic, and the summary
  is lit and taken with it), so `<OrderPlaced>` lands once, not once per level;
  a view that folds the expansion (--depth 0) draws the detail's token on the
  summary (project).
  A node reached in a unit where it has no work of its own runs its home
  unit's (the shallowest that has some). An expansion whose owner its level
  writes only on the `X := {` header (`[A] := { … }` at the top, [A] written
  inside `[Core] := { … }`) is the inside of the X written there: it runs where
  X is reached, as if written in that body (the export model nests it the same
  way; core.graph.header_only). An alias runs when called by name.
  Composition children are instances: static ones once per parent (×N
  multiplies), dynamic ones Limits.spawn per parent, a `=>` into one spawns
  another. A flow's destination cardinality (`-> [App]×N`, Edge.card) is how
  many instances it reaches, never a retry: only a `×N` in a call's policy
  (scene.call_policy: Wire.mods, then Edge.src_mods) retries. Declarations (`@read`, `@inv`, `@sla`, notes, …) do not affect a run.

SCENARIOS

scenarios(scene) lists `happy` (every default) and then one scenario per
non-default option of each reachable choice point (call outcomes, node
outcomes, `?>`, `/`, `&?`, `parallel @any`, branch arms, `\\-_` siblings,
ambiguous machine transitions), ordered by source line. A route makes what it
guards a choice point: the calls on its line, and — when nothing in it fails
on its own — the awaited calls of the block whose `}` it follows. scenario(scene,
"a+b") combines deviations. Scenario(name, choices, label, entries, starts, machines):
choices a tuple of (choice id, option); starts the entries that begin at a tick
of their own, ((entry node id, tick), …) (a dict reads the same); machines the
state machines that begin in a state of their own (below).

After them come the overlap scenarios (overlaps(scene)): for each later entry B
and earlier entry A of the happy run, B started so it reaches something A's
episode touches (a store A accesses, a machine A moves, a node or event A is
busy at) as A touches it: the moments a race could happen; at most
Limits.pair_overlaps per pair and Limits.overlaps in all, named `B@t`.
scenario() also reads any `Entry@t` part (the entry as scenario names write
nodes, a whole tick): `Builder.claim:fallback+Author@40`. overlap_windows(scene)
gives each pair's window (A's first to last busy tick) and overlap_runs(scene)
one `B@t` per tick of it (at most Limits.window per pair): what a checker tries
beyond the listed few.

Last come the state starts (state_starts(scene)): one per state machine and
state other than its initial one that a transition leaves (one written from it,
or a `_` one to another state), named `Owner=State`, beginning that machine
there so a way out of a later state is walked. scenario() reads any `Owner=State`
part (the owner as scenario names write nodes, any state its block names but `+`,
`$`, `_`; no `.` before the `=`, so `Owner.field=value` stays a field choice):
`Owner.field=value+Owner=Built`. Scenario.machines holds them, ((owner node id,
state node id), …).

combinations(scene, k, budget=…) explores up to k deviations at once: a
combination grows only by a deviation its own run meets after its first
deviation took effect; runs that repeat an earlier one are dropped; the budget
caps the runs and says how many it left out (Exploration). deviations(prog)
lists the single ones.

STATIC FACTS (pure, over program(canonical(graph)); no run changes)

  reachable(prog)         what the default entries reach (wires, nodes, regions)
  route_guard / selected_routes   a route's guard; the routes a failure takes
  loop_count(block, limits)       how often the simulator runs a loop
  failure_flow(prog)      {(ui, node): the failure guards that can arrive there};
                          failure_analysis(prog) adds what fallbacks absorbed and
                          the live routes — mirrors the run

THE TRACE

Trace(scenario, frames, outcome, end, scene)
  outcome   "ok" | "failed" | "cut"
  end       {"machines", "routes", "stalled", "deposits", "cut", "visited", "log",
             "events", "episodes"}
            episodes: every episode begun, in start order — [{"episode" (k, from
            1), "entry" (node id), "start" (its first tick)}]
            deposits: the `&` source joins left open — [{"join": (unit, index),
            "target", "arrived", "missing"}] (node ids); a member deposits and goes
            on, so an open join is a deposit no last arrival consumed
            events: the run as data, in order — dicts with "kind", "t" (tick),
            "task" (id, or None for the run) and "episode" (the task's, recorded
            when it was forked), plus by kind:
              fork        parent (task id | None), why (entry | async | fan | join |
                          race | parallel | trigger), wire, node
              end         how (ok | failed | cancelled)
              await       members, need (task ids)   resume  failed (bool)
              gate-arrive key (unit, join, target), round, node, wire
              gate-fire   key, round, node (the target)
              gate-drop   key, round, node (an `&?` arrival after the winner)
              access      store, mode (read | write | rw | unknown), wire, held
                          (stores the task's `owns` blocks hold), outcome (done |
                          unknown: a failed attempt)
              choice      cid, option, default (bool): a choice point consulted
              fail        origin (("call", ident) | ("node", id)), node; for a call
                          fallback, critical (bool), tries (the attempts it made),
                          callee (bool: it arrived and its callee's work failed)
              route       node, wire, guard        transition  owner, label, src, dst
              stop        how (entry | unawaited | fallback | route-failed |
                          abort), node, guard
              limit       name (depth | visits | spawns | iterations | activations
                          | stack | frames), node; a depth limit also act (the
                          capped caller), level (how deep it is) and wire; a
                          frames limit also frames (the limit) and start (the
                          tick the latest episode began: it counts from there)
              enter       act (run-wide activation number, from 1), caller (the
                          act whose hop or fork started it; None for an entry),
                          node, unit (index), level (activations of node on the
                          task's stack, itself included: Frame.depth's count),
                          insts (the instance keys it stands for, its lanes; ()
                          outside the composition tree), wire (the ident that
                          started it; None for an entry or an expansion's entry),
                          hop (the id of the hop that landed it there; None)
              leave       act, how (ok | failed | cancelled)
              hop         id (run-wide hop number, from 1), act (the one it sets
                          out from), wire, back (bool), lanes (the instance keys
                          it reaches going out into a composition node; None
                          otherwise), attempt ((k, of) | None), carries; a reply
                          (back) also callee (the act it leaves from: the one
                          that just ran; None for a fallback or no callee)
              land        hop (its id), node (where it ended: the wire's far end,
                          a reply's near one), how (entered | reached: an actor,
                          no work | opaque: a hole or a host's side | base: the
                          depth limit | none: no instance | visits: the visit
                          limit | arrived: nothing ran there (a gate, a
                          trigger) | failed: an attempt failing on arrival |
                          cancelled: on the way, or a race's loser on arrival |
                          returned | fallback | self: a self-call's pulse).
                          A hop still in flight when the run ends has none
              spawn       node, inst (the new key), parent (its parent instance's
                          key), wire
              ignored     event, label, owner, state; replayed True when a
                          state start replays it (replayed(): an event on the
                          machine's way to its start state, not a new arrival)
              iterate     owner (the unit's owner node; None: the document),
                          block (index into its graph's blocks), k (from 1), of
                          (the iterations it runs), act (the one running it;
                          None): a loop starting its k-th iteration
              quiet       waiting (task ids still waiting when the run went quiet)
            A source join is a deposit, so its arrivers never wait: there is no
            gate resume; a gate's round counts the times it fired.
  scene     the Scene its frames name (the canonical one, or project()'s)

Frame — a full, immutable snapshot (a view draws frame i alone)
  tick, episode, entry, tokens (Token, task order), lit, held, taken, failed,
  nodes {id: active|waiting|visited|failed|cancelled|opaque}, depth,
  machines {owner: state node id}, changed, instances, loops, blocks,
  held_resources, log (lines added this frame, each led by `t` and the tick, zero-padded), done,
  episodes
  episode, entry: the latest episode begun and its entry; episodes: the running
  ones (a task of theirs with a turn or hop to come, or a token drawn) — more
  than one only while episodes overlap

Token(wire, at, dir, task, state, carries, reach, attempt, act, episode)
  dir "out" | "back"; state "moving" | "failed" | "cancelled" | "fallback";
  act the activation the hop set out from; episode its task's

INSTANCES

instances(prog, limits, potential=False) -> (Instance(key, node, ordinal, parent,
rel, spawn, setup, entry), …): the composition instances at setup, keyed (node
id, ordinal), in composition order (a parent instance, then its children depth
first); a spawn adds one under the parent instance with the fewest of its
entry. A hop into a composition node stands for some of its instances (its
lanes): from a sender standing for instances I, for each i in I the target's
instances under i when there are any, else every instance the wire selects (a
`[A]/` path, Limits.spawns); from a sender standing for none, every one.

THE TIMELINE (pure, no drawing; what the run view draws)

  timeline(trace, limits, show)   the run as lanes over ticks: a Lane per
                  participant it touched (every node an activation entered or a
                  hop set out to), one per composition instance and recursion
                  level, born at the tick it first acts or a hop sets out to it
                  and ordered by birth (an expansion's lanes under its node, a
                  recursion's `↻k` levels under its lane, one node's instances
                  together); a Span per activation and lane ([enter, leave),
                  its waits: the rest is work); a Move per hop (start, end and
                  how, from the land events; a reply leaves its callee's lanes);
                  a Mark per self-call pulse, host op and base case. A frame is
                  the timeline clipped at its tick: there is no per-frame
                  structure. Lane keys (node, ordinal | None, level).
  folds (show, RUN_SHOW 3): a (node, owner's node) group of more than show
                  instances keeps its first show − 1 and every one that failed
                  or was cancelled, the rest one lane (ordinal `…<owner>`, its
                  levels with it); a lane deeper than show + 1 keeps ↻2 …
                  ↻(show − 1) and its deepest, the middle one lane (`lo‥hi`)
  hosts (folded_hosts(scene, depth): {node: the drawn node standing for it} for
                  each node inside an expansion a view drawn to depth folds): a
                  folded node's lanes fold into its host's lane — its work is
                  the host's, a hop between two of them is the host's own
                  work (not drawn), a hop across the fold leaves or reaches the
                  host's lane

NARRATION (pure, over a Trace and the scene it names)

  narrate(trace, hosts)  (Beat(frame, tick, text), …): the run in plain words,
                  one Beat per frame where something happens ("[API] calls
                  [Payments] with charge(total) — attempt 2 of 4"), read from
                  the frames and the events, never from the log's text; while
                  episodes overlap each sentence is led by `ep{k}: `
  hops(trace, hosts)     (Hop(frame, src, kind, dst, end, outcome), …): every hop
                  set out on, in order, with the frame it ends and how (failed,
                  cancelled)
                  hosts (folded_hosts; None: every node drawn): both name a
                  folded node by its host and leave out what happens wholly
                  inside a fold (a hop between two of its nodes, an event of
                  one), so at --depth 0 they name only the drawn nodes
"""


from sigil.model.sim.program import (  # noqa: F401  (the package's API)
    LIMIT_SOURCES, PER_SIZE, Decide, Floor, Frame, Group, Instance, Limits, Machine, Program,
    Region, Scenario, Step,
    Token, Trace, TriggerRef, attempts, canonical, carried, doc_size, document_limits, duration,
    flag_names, instances, limit_name, limit_problem, limit_sources, limits_for, limits_from,
    loop_count, usable_limits, mod, program, replayed, resilient, returned, route_guard, scaled,
    selected_routes, sized,
    _flat, _program_of)        # read by the flow rules and the run view through the package
from sigil.model.sim.engine import CONVENTIONS, simulate  # noqa: F401
from sigil.model.sim.scenarios import (  # noqa: F401
    ChoicePoint, Deviation, Exploration, FailureFlow, OverlapWindow, choice_points,
    combinations, deviations, failure_analysis, failure_flow, overlap_runs, overlap_windows,
    overlaps, reachable, scenario, scenarios, state_starts)
from sigil.model.sim.narration import (  # noqa: F401
    FOLD, RUN_SHOW, Beat, Hop, Iteration, Lane, Mark, Move, Span, Timeline, change_ticks,
    folded_details, folded_hosts, folded_wire, host_map, hops, ident_map, narrate, project,
    timeline)
