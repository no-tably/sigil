---
name: sigil
description: Sigil is a compact, non-executable notation for system designs — glyphs like [Component], {Data}, <Event>, (Actor), |Store| wired with arrows like ->, ~>, =>, !>. Use whenever the user wants to (1) compress a design or prose spec into Sigil; (2) expand Sigil into prose; (3) compare two designs structurally; (4) tighten or normalize hand-written Sigil; (5) craft and refine a design ("help me design X", or a craft-mode document); (6) lint or validate a .sigil document (bundled `sigil lint`), or check whether its design declares how its risks are handled (`sigil check`), or export a ready spec as a build skeleton (`sigil export`); (7) draw a Sigil document as a terminal graph (`sigil view`) or a Mermaid diagram (`sigil export --mermaid`); (8) mentions Sigil, glyphs, or writes bracket-and-arrow notation; (9) describes architectures, state machines, data flows, workflows or pipelines where a compact notation clarifies the design. Prefer Sigil over prose for architecture once it has been introduced.
license: MIT
---

# Sigil — system design shorthand

Sigil describes the *wiring* of a system — components, data, events, actors,
stores and the flows between them — in a form dense enough to fit on one screen
and precise enough to expand unambiguously back into prose. It is a notation,
not a program: nothing executes.

The authoritative spec is `references/language.md`; worked prose ↔ Sigil pairs
are in `references/examples.md`. Read the relevant section of the spec before
using any construct you are not sure of — do not invent syntax.

## Quick reference

| Glyph | Kind | | Arrow | Meaning |
| --- | --- | --- | --- | --- |
| `[X]` | component (service, module, widget, system…) | | `->` | sync call / request |
| `{X}` | data / record | | `~>` | async / fire-and-forget |
| `<X>` | event / message | | `<->` | bidirectional |
| `(X)` | actor outside the system | | `=>` | returns / produces |
| `\|X\|` | store / persistence | | `!>` | error path |
| `[?]` `{?}` … | hole (unspecified) | | `?>` | conditional |
| `~{X}` | mutable | | `*>` | broadcast / fan-out |
| `*<X>` | stream | | `&` / `&?` | strict join / race |

Every document starts with a mode line — exactly `#!spec` (binding, no holes),
`#!sketch` (partial, holes allowed) or `#!craft` (work in progress). Titles go in
section headers: `--- Checkout ---`. Modifiers (`@inv`, `@sla`, `@timeout`, `×N`,
`@cap`, …), control blocks (`state`, `loop`, `parallel`, `branch`), expansions
(`[X] := { … }`), payloads (`: {X}`, `: verb(args)`, `: op ns.verb(args)`, value literals) and Sigil Normal Form are all
defined in `references/language.md`.

```
#!sketch

--- Checkout ---
(User) -> [API] : {Cart}
[API] -> [Payment] : charge ×3 @timeout(2s)
       !> <PaymentFailed>
[API] ~> <OrderPlaced> -> |Ledger|
```

## Tools

One command, `python3 scripts/bin/sigil <lint|check|view|export>`, Python 3 standard
library only. Write the document to a file (e.g. `/tmp/doc.sigil`) first; `sigil lint`,
`sigil check` and `sigil export --mermaid` also accept `-` for stdin.

| Task | Command | Result |
| --- | --- | --- |
| Validate | `python3 scripts/bin/sigil lint FILE` | one `severity:line:rule: message` per issue; exit 0 clean, 1 warnings, 2 errors |
| Check the design | `python3 scripts/bin/sigil check FILE [--mode sketch\|craft\|spec] [--k N] [--overlaps off\|listed\|all\|N] [--export] [--json] [--all]` | composition findings, one `severity:line:SGCnnn: name: message` each (in craft the message is a question), then `accepted:line:SGCnnn: name: reason` per acknowledged one; `--json` adds each rule's why and the declaration that satisfies it; `--rules` lists the rules; `--overlaps` picks the overlap runs (default `all` in spec, `off` in sketch and craft; see **simulate**); `--export` adds the export readiness rules (see **export**); exit codes as lint |
| Both at once | `python3 scripts/bin/sigil lint FILE --deep` | lint diagnostics and check findings merged by line, acknowledged findings last; exits with the worse of the two codes |
| Draw in the terminal | `python3 scripts/bin/sigil view FILE --once --graph [--depth N\|all] [--payloads] [--mods] [--access] [--no-lint]` | box-drawing graph + lint summary; exit 1 on lint error; control blocks as titled frames, joins as bars, sections as dividers; `--mods` modifier chips, `--access` the permission graph (`r` / `w` / `b` heads, `1w` / `Nw` writer badges) |
| Show comments | `python3 scripts/bin/sigil view FILE --once --notes markers` (`--notes callouts` in `--tree`) | commented nodes tagged `#N`, notes listed (or drawn as margin boxes) |
| Call graph, left to right | `python3 scripts/bin/sigil view FILE --once [--payloads]` (the default view; `--flow` names it) | bare glyph labels in columns by call depth, a node's first callee on its row (`[API] ─┬─▶ [Payments]`, `├─✖ <Failed>`); one row per callee, so it reads like a call tree and is usually the shortest drawing; `--sim` / `--checks` work here too |
| One run as a timeline | `python3 scripts/bin/sigil view FILE --once --run [--sim SCENARIO] [--depth N] [--unroll N\|all] [--json]` | what did happen in one run (the happy one without `--sim`; every level unless `--depth` folds deeper lanes into their node's): a lane per participant, instance (`{Transform·2}`), recursion level (`↻2`) and activations at once (`∥2`), time left to right; `↺2` over the ruler a loop's next iteration; `█` working, `░` waiting, a call `╰──▶` at its send tick, retries `╰───✖╰───✖`, a reply `───↩`, `✕` failed, `◌` a spawn in flight, `{…×k more}` folded instances; a note per lane in plain words ("4 attempts, each fails"). `--json`: the timeline as data (lanes, spans with their waits, moves, marks) |
| Hierarchy + wiring | `python3 scripts/bin/sigil view FILE --once --tree [--compact]` | composition tree as an outline, each flow as a lane (`●` source, `◀` targets) + legend; `--compact` drops the blank row between top-level units |
| Live view for a human | `python3 scripts/bin/sigil view FILE` | full-screen view that redraws on every save (tell the user to run it in their own terminal); keys: `1` `2` `3` `4` graph / tree / flow / run, `t` the next view, `x` sim mode (in it: space play / pause, `,` `.` a frame, `<` `>` an event, `[` `]` scenario, `-` `+` speed, `w` follow), `n` notes (in the run view: run notes / the design's / none), `u` the run view's folding, `e` triggers, `v` events (where they land / as nodes), `s` spacing, `o` layout (auto / wrap: fit the width, grow down / pan: natural, pan across; `f` flips wrap and pan; `--layout` to start in one), `c` checks overlay, `d` depth, `p` payloads, `m` modifiers, `a` access, `l` lint, arrows / `h j k L` or mouse drag / wheel pan, `z` centre, `g` home, `r` reload, `q` quit |
| Run every pathway | `python3 scripts/bin/sigil view FILE --sim all [--json]` | no drawing: per scenario `NAME outcome N frames label`, then indented facts — `states:` each machine's end state, `failed:` what failed (`↩ fallback`, `critical`), `routes:` failure routes taken, `ignored:` events a state had no transition for, `waiting:` nodes left blocked, `open:` joins left open, `bounds:` a base case, visit limit, spawn cap, loop at the cap or cut — then `N scenarios: a ok, b failed, c cut`; always exit 0. `--sim list`: the scenario names and labels |
| Walk one pathway | `python3 scripts/bin/sigil view FILE --once --tree --sim SCENARIO` | the run's last frame over the drawing (`✕` failed, `◉` a machine's state, wires taken vs never taken), then `sim NAME (label): ok\|failed\|cut · N frames` and the run in plain words, one `tNNN …` line per step (`[API] calls [Payments] with charge(total) — attempt 2 of 4`, `[API] routes the failure to <PaymentFailed>`); exit 2 for an unknown scenario, listing the known ones. `--sim SCENARIO --json` (no drawing): the run's facts, `steps` [{frame, tick, text}] and the raw `log` |
| Read the structure | `python3 scripts/bin/sigil view FILE --structure [--json]` | no drawing: per unit its members (actors apart), flows, the units it calls and holds; then cycles between sibling units with their flows, *up* links, the edge (parts that call an actor), each part's reach out and in, pass-throughs, units over 9 members, parts with no home, writers per store; any mode, exit 0. See **refine** |
| Mark the findings | `python3 scripts/bin/sigil view FILE --once --checks [--tree]` | the check findings marked on the drawing, a checks legend, then each finding's question after lint |
| Show it to the user | the plugin's viewer tool — Claude Code: `view` (`mcp__sigil__view`); pi: `sigil_view` — with `file`, `view` graph\|tree\|flow\|run, `depth`, `scenario`, `frame` N\|last, `play` | a live viewer the user watches (a pane or widget, or a herdr / tmux / zellij split) that redraws on every save; the reply gives the summary, lint and the run's step at that frame (`now:` the narration line, `path:` the hops so far, by branch), never the drawing. See **Showing the user** |
| Export a ready spec | `python3 scripts/bin/sigil export FILE --out DIR [--name NAME] [--dry-run] [--json]` | a `#!spec` document that lints and checks clean (with `--export`) written as a build skeleton: a folder per system, a `.md` per component, `manifest.json` (per system: interface and body hash, components, each component's two hashes, depends_on; the dialect, when one is loaded); `--name` names the top system (default: the file's stem); every export writes `delta.json`, and a re-export prints the delta (`added` / `removed` / `rebuild` / `recheck` / `unchanged`); not ready → the blocking lines, exit 2, nothing written. See **export** |
| Mermaid diagram | `python3 scripts/bin/sigil export FILE --mermaid [--depth N\|all] [--composition subgraphs\|edges\|none] [--spine]` | `flowchart TD` source, in any mode (no gate; for docs or review); present it in a fenced `mermaid` block. Composition trees draw as subgraphs by default; `--spine` draws a subgraph per system the export would make |
| Colour the source | `python3 scripts/bin/sigil highlight FILE [--json]` | the source in the theme's colours, for a person's terminal (a split, or `less -R`); `--json` each line's `[text, role, colour]` runs for a host to paint; `--stream` serves an editor (protocol in `--help`). Not for your replies: read the plain file |

`--depth 0` shows the top level only, `1` (default) opens direct `:=` expansions,
`all` opens everything — keep `all` for small documents. If a dialect is in use
(see "Dialects" in `references/language.md`), pass `--dialect NAME` or set
`SIGIL_DIALECT`; plain Sigil needs neither.

### Showing the user

The user should see the design while you work on it together. There are three
ways to show it. Pick by where you are running:

- **The viewer tool**, in Claude Code (`view`) and pi (`sigil_view`). Use it if
  you have it. Call it once on the file when the design work starts. Call it
  again when you want the user to look at something particular, such as a run
  (`scenario`, then `frame` or `play`): under the drawing the user reads the
  run's path (its hops so far, numbered by branch; the reply's `path:`) and
  its narration line, the same words the reply's `now:` gives you. Pick the view
  as in **Which view** below. The viewer redraws on every save, so
  don't call it after each edit. It draws in a pane (Claude Code) or a widget
  above the editor (pi). Inside herdr, tmux or zellij it opens a split running
  the live view instead. If the reply says the viewer is waiting (the terminal
  is narrower than 144 columns), tell the user they can open it with
  `/sigil-pane` in Claude Code or pi. To draw somewhere else, the user runs
  `/sigil-pane display mod|multiplex|auto` (with no value it says the current
  setting). The pane's keys work once the user gives it the keyboard (ctrl+x
  then Tab); it docks as a sidebar in Claude Code's fullscreen layout. If it
  says there is no UI, or the tool fails, use `--once`.
- **A multiplexer split**, everywhere else (Codex, OpenCode), or when the user
  prefers it. Ask the user to run `python3 scripts/bin/sigil view FILE` in a split or a
  second terminal. If you can open the split yourself, do: `tmux split-window -h
  'python3 scripts/bin/sigil view FILE'`, or `zellij run --direction right -- python3
  scripts/bin/sigil view FILE`. In herdr, run `herdr pane split`, then `herdr pane run`
  on the new pane. It redraws on every save, and its keys are in the table above.
  To show a run, add `--sim SCENARIO`, and `--frame N|last` or `--play` to start
  it at a frame or playing.
- **`--once`**, for you, or when the drawing belongs in your reply. It prints one
  drawing as text. Read it yourself to check the shape, or paste it into a code
  block when the user asked to see it here, or can't run a live view. It is also
  the way to see a run's frame yourself (`--sim NAME --frame N|last`): the
  viewer tool never returns the drawing.

### Which view

Pick the view that answers the question at hand. Whenever you open or present a
view, tell the user in one sentence which one you picked and why — e.g. "The flow
view: it reads the checkout's request path and its failure route left to right."

| View | Reads best for | Weak at |
| --- | --- | --- |
| flow (default) | request paths, call chains, failure routes (`├─✖`), payloads (`--payloads`) and findings (`--checks`) on the wire; usually the shortest drawing, and it wraps into bands in a narrow pane. With a run: the route taken | many back-edges or state triggers tangle it |
| tree (`--tree`) | composition and ownership (`\-&` has, `\-*` spawns, `:=` internals — the other views draw a parts-only unit with no parts), state machines with their triggers in a few rows; the narrowest drawing of a small design. With a run: `◉` current states, wires taken | lanes multiply on large designs (past the pane's width they fold into numbered plugs, `●①` … `◀───①`) |
| graph (`--graph`) | overall topology: fan-in (several writers into one store), fan-out, where flows converge; state machines as state diagrams; control blocks as frames | the tallest drawing; in a narrow pane its layers wrap, so it grows taller still |
| run (`--run`) | presenting a simulation: order and timing, retries (`╰───✖` per attempt), spawned instances (`[Bullet·2]`), recursion levels (`↻2`), async hand-offs, fan-out, episodes, a plain-words note per lane; the happy run without `--sim` | shows only what ran — unreached parts are absent, so it is not a picture of the design |

To show a design, start with flow; switch to tree when the question is what owns
or contains what, or the pane is narrow, and to graph for the big picture of a
small design. To present a simulation, use run when the answer is *when*, *how
many times* or *which instance* (retries, spawns, recursion, waiting); use flow
(or tree for state machines) when it is *which route* the run took through the
design. On a large design, `--depth 0` first, then open one expansion at a time;
keep `--depth all` for small documents.

## Operations

### compress — prose → Sigil
1. List every noun and tag its kind (`[ ]`, `{ }`, `< >`, `( )`, `| |`). Actors are
   *outside* the system boundary; lifecycle states are never actors — they go in a
   `state {Entity} { … }` block.
2. List every verb and map it to an arrow. Verbs like "filters", "excludes",
   "reads" that are not connections become `@inv …`, comments, or explicit flows.
3. Qualifiers become modifiers from the spec's closed vocabulary only (`@loc`,
   `×N`, `@sla(…)`, `@inv …`, `@cap(…)`, `@timeout(t)`, …). If nothing fits, use a
   `# comment` — never an invented `@modifier`.
4. Iteration → `loop`, concurrency → `parallel`, labelled alternatives → `branch`.
   Modes of anything → a `state <owner> { … }` block (the owner may be any glyph:
   `state {Order}`, `state [Checkout]`); name each trigger after the event that
   causes it (`-<Paid>->` with a `<Paid>` event) and the tools wire them together.
5. Layer it: a scannable top level, then `[X] := { … }` expansions below.
   When something is *made of* parts (entities and components, UI trees, region →
   cluster → service), write a composition tree — the parent glyph, then indented
   `\-<rel>` branches (`\->` contains, `\-&` has, `\-*->` spawns, `\-{cond}-?` when,
   `\-$` from data, `\-@` attached, `\-{cond}-!` alerts when, `\-*-=` spawns and
   gathers, `\-_` one of; `\-(N)->` gives a sibling N shares, `×N` stays the count)
   — and keep the wiring in ordinary flows. A flow to a bare name reaches every
   occurrence; a path with no spaces (`[Bullet]/{Transform}`) reaches only the
   occurrences under that parent.
6. Mark genuine unknowns as holes (sketch/craft only).
7. Emit in Sigil Normal Form, then run `python3 scripts/bin/sigil lint` and fix what it reports.

Output one code block; first line is the bare mode line. No prose unless asked.

### expand — Sigil → prose
Walk statements in order; each flow becomes one sentence (source, verb from the
arrow, destination, qualifiers). Blocks become sections, expansions become
subsections, invariants/SLAs become bullet constraints. In `#!spec`, anything not
stated is "unspecified" — never invent defaults. In `#!sketch`, label every
filled-in default as "assumed".

### compare — two documents → structural diff
Align equivalent roles with aliases, reduce both to skeleton form (names → `_`,
keep glyph kinds, arrows, structure), diff the top level first, then deeper
layers. Report: identical shape, same shape with different details, or different
shape — then side-by-side skeletons and the meaningful differences.

### tighten — messy Sigil → Sigil Normal Form
Mode line first; aliases clustered at the top; sections shallow → deep; within a
section: declarations, state blocks, sync flow (source → sink), async flows, error
paths, constraints. Inline single-use aliases, chain flows where it stays
readable, list remaining holes under a `# TODO` comment. Always finish with
`python3 scripts/bin/sigil lint`.

### craft — design together, iteratively
Anchor a `#!craft` document on a one-line purpose. Start at the top level;
confirm each new noun's glyph kind with the user instead of assuming it; expand
one component per turn; mark gaps as holes *and* say so; re-emit the whole
document after every substantive change; offer a tighten pass every few turns;
propose promotion to `#!sketch` / `#!spec` once holes are resolved. Do not
produce a finished-looking spec prematurely or drop into algorithm internals.

Keep the craft document in a file and rewrite that file after every change: the
user's live view (see **Showing the user**) redraws on every save. Show it with the
viewer tool once at the start, if you have one; otherwise ask the user to open
`python3 scripts/bin/sigil view FILE` in a split. Use `--once` output only when the drawing
itself belongs in your reply.
After each substantive change, test-drive it before replying:
1. `python3 scripts/bin/sigil lint FILE --deep` — lint plus the composition checks (see
   **check**); put the findings' questions to the user alongside your next step.
2. `python3 scripts/bin/sigil view FILE --sim all` — run every pathway (see **simulate**)
   and read the table against what the user said the system should do.
3. Drill into any surprising row with `--once --tree --sim NAME` and its log.
4. Turn what you found into a proposed design change or a question for the user —
   never a silent fix.
5. After the change, run `--sim all` again and compare it with the previous table:
   a row whose outcome, states, failures or routes changed without being meant to
   is a behaviour regression — say so.

The outcomes the user confirms ("a declined card cancels the order") are the
design's acceptance tests: re-check them on every run, and keep them in the
document as plain comments if that helps (`# expected: Payments:fails → {Order}
Cancelled` — free text, no tool reads it). Check the drawing with
`python3 scripts/bin/sigil view FILE --once` before replying. Once a feature is in and
test-driven, take the design through **refine** before the next one. Before promoting to `#!spec`,
run `python3 scripts/bin/sigil check FILE --mode spec` and resolve every error. Once the
spec is final and the user wants it built, see **export**.

### refine — work the design to its cleanest shape
Refining is a loop, run after every feature added in **craft**, until the design is
the simplest acyclic, composable structure that meets its goal. It is not tied to
any domain or language.
1. **Fix the limits first.** Run `--sim all` and raise `--limit frames=N` (and
   `activations=N`) until no row is `cut`. Keep the same limits for every round. A
   cut run measures nothing, and in spec mode it is a warning that blocks export.
2. **Read the design from each angle below.** Note what each reading shows.
3. **Propose each change** to the user: the change, the pass that found it, and what
   it costs (measured, if you tried it on a copy). Apply only what the user takes.
4. **Re-measure.**
   - **After each change:** `lint FILE --deep`, `view FILE --sim all` and `view FILE
     --structure`, all at the same limits.
   - **Once per round:** `check FILE --mode spec`, which runs every overlap run and
     takes much longer.
   - Compare the happy run's frames, the failure rows and the structure summary
     with the last round.
5. **Stop** when a full round finds nothing the user wants to change.

`python3 scripts/bin/sigil view FILE --structure [--json]` is the main reading for
several of the passes. For each unit (each `X := { … }`, tree root, and the top) it
lists:
- its members, kept apart from its actors;
- its internal flows;
- the units it calls and the units it holds;
- cycles between sibling units, with the flows that make them;
- *up* links: a unit's flows into a unit that encloses it, such as a layer using a
  store written at the top. These are normal, not cycles;
- the *edge*: the parts that call an actor;
- each part's reach, out and in: what it can drive and what can drive it;
- pass-throughs;
- units over 9 members;
- parts with no home (written in two units, neither enclosing the other);
- writers per store.

| Pass | Ask | Read it with |
| --- | --- | --- |
| purpose | does every part serve the goal? | `--depth 0`; `check` *unreached*; the run view |
| names | one concern per name, the simplest true name, the right kind? | `--tree`; a name used twice is **one** entity (it merges silently); `--structure` parts with no home |
| dependencies | acyclic, and pointing toward the stable and pure? | `--structure` cycles and *up* links; `check` *unit-cycle*, *expansion-escape* |
| blast radius | if a part failed or were hostile, how far could it reach, and who can drive it? | `--structure` reach, edge and writers per store; each failure row's `failed:` line in `--sim all`; every outside sender drawn as an actor |
| complexity | the least structure that does the job? | `--structure` units over 9 and pass-throughs (`check` *large-unit*); modes split from their thing |
| composability | can each unit be used and tested alone? | `--structure` calls per unit; a call that only fetches configuration |
| efficiency | does the work per run fit the goal? | the happy run's frames, compared between versions only; `--run` waits; retries |
| behaviour | does it still do what the user said? | `--sim all` against the expected outcomes; `check --mode spec` (worth reading even on a sketch: it finds unhandled failures) |

The usual changes, in the design's own terms:
- **Break a cycle between siblings** by moving what both sides share down into a
  value both read, or into a unit both depend on. An *up* link that hurts (a layer
  using its parent's part) is fixed by making that part a sibling unit.
- **Pass configuration** (a clock, sizes, capabilities, a theme) in as data, not as a call.
- **Keep the edge small:** only the parts that touch the outside world talk to
  actors.
- **Wire narrowly, but within the home rules.** From an outer level, including an
  actor's entry line, point at the inner part it uses: a coarse edge to a whole unit
  pulls every failure behind it into the caller's runs. Between sibling units, call
  the unit itself. Naming a sibling's part makes that part homeless (*no-home*
  under `--export`).
- **Contain the blast radius:**
  - draw every trust boundary as an actor with what it sends (an entry at the top
    pointing at the part it reaches);
  - give each device or store one writer;
  - decode untrusted input into the design's own values, and never forward it raw;
  - put the powerful parts (spawning, loading code, writing, the network) at the
    edge, with the least reach;
  - make every failure end in a fallback or a named error its caller handles. No
    failure rows in `--sim all` means the design draws no failures: draw the ones
    the system handles.
- **Shrink:** fold a mode into its owner, merge two parts doing one concern, group
  a large unit into families, and delete a layer that isolates nothing.

**What to apply and what to propose:**
- **A refinement** is a structural change the user agrees to, made for a reason a
  pass gave. It is not a way to quiet a check finding (see **check**).
- **A notation fix that only restates what the document already says** (its
  comments call a send conditional, so it becomes `?>`) is applied. The findings it
  uncovers go to the user as questions.
- **A truer relation kind** (`\-_` one of, `\-*->` spawns) may raise new questions.
  Ask them; don't fall back to a vaguer kind.
- **With no user to ask** (a delegated run), apply only changes that make the design
  match what is already known: the code, the stated decisions, the comments. List
  the rest as proposals, each with its reason and measured cost.

**The system's kind.** Early in a craft session, ask the user once what kind of
system it is and write the answer on a `#%` line under the mode line (language.md
"System kind"): its shape (`service`, `library`, `daemon`, `job`), reach
(`networked`, `in-process`) and concurrency (`concurrent`, `deterministic`); write
only the words that differ from the first, the default. The kind turns off the rule
groups that cannot apply — a `library` is not asked who calls it, a `daemon` not
what ends it — and the check's summary names the rules it turned off. Never write
or change a kind to quiet a finding: it is a fact the user states. A finding the
kind does not cover, such as *saga-uncompensated* over pure parts, is still answered
by declaring or acknowledging it. **A design that uses a library** names the library's
parts as op calls (`: op cure.paint(view)`), not as components: a component would
be exported as something to build, and would merge with any part of the same name.
Acknowledge the op calls' missing timeouts document-wide, as in-process library
calls.

### lint — validate
Run `python3 scripts/bin/sigil lint FILE`. Report each diagnostic with a suggested fix
(the rule ID and message explain the problem; `references/language.md` has the
rule). Surface issues before rewriting — let the user decide. Fix lint errors
before reading check findings (`--deep` shows both): a malformed line can explain
a finding.

### check — does the design say how its risks are handled?
`sigil check` asks of a design what lint cannot: an external call with no
timeout, a retry on a write with no idempotency, two writers on one store, a failure
with no route, a race, an event nothing handles, an unbounded recursion. A finding
never forbids a shape; it names a risk the document leaves undeclared. Run it in
**craft** (findings are `warn` questions) and **spec** (findings of binding rules
are errors); in sketch they are hidden (`--all` shows them).
1. Run `python3 scripts/bin/sigil check FILE` (or `sigil lint FILE --deep`). Its
   summary names any rules the `#%` kind turned off; an acknowledgement of one of
   them is reported unused (SGC003): delete it, the kind says it once. For a rule's
   rationale and the declarations that satisfy it, use `--json` (`why`, `fix`).
2. Put each finding to the user **as its question** (craft prints it; in spec turn
   the statement into one), in the design's own terms, and let the user answer.
   A finding marked `(guessed: …)` rests on a guess about a name — say so.
   In spec mode a run the simulator cut at its limits is a warning
   (*exploration-incomplete*): raise `--limit frames=N` on `check` (and `export`)
   until nothing is cut before trusting the rest; the defaults already grow with
   the document's size. A `#&` declaration whose dialect is not available leaves
   an SGL189 warning until it is; say so rather than removing the declaration.
   A behavioural finding names its witness run; one named `Entry@t` (`race: … in
   the Bob@0 run`) is two entries running at once — replay it with
   `sigil view FILE --once --run --sim Bob@0` and show the user where they meet.
   One named `Owner=State` (spec mode walks these too) began that machine in a
   later state: `--sim Ticket=Done` replays it. Ask what the state should do with
   the event, as for any dropped event.
3. Resolve it in one of two ways only:
   - **declare** the handling in the notation the spec already has — `@timeout(t)`,
     `@deadline(t)`, `×N` with `@after(…)`, `@fallback(x)`, a `!>` route, a
     recognised `@inv` (`idempotent(key)`, `atomic(…)`, `cas(field)`,
     `depth <= N`, …), `@owns |S|`, `@read(…)` / `@write(…)`, a `^N` bound, an
     `@sla`, a `?>` exit, a terminal state `$`, a consumer for an event, a
     self-loop that ignores an event on purpose (several at once as a trigger list,
     `Built -<Planned, Passed>-> Built`; after the end, `$ -<Passed>-> $`) — whatever
     the user's answer says is true of the system. `@cap(…)` is a capability
     requirement, not a bound: it resolves no finding;
   - or **acknowledge** it, when the user accepts the risk: a comment
     `# accepts: rule-name — the reason` trailing the line or on the line(s)
     directly above it; on or above a block's header or on its `}` to cover the
     block; or before the first statement, separated from it by a blank line, to
     cover the document. The reason is required; the finding is then listed as
     `accepted:` and no longer counts.
4. **Never reshape the design to make a finding go away** — do not remove a call,
   a writer, a retry or a branch, merge components or reroute flows unless the user
   asks for that change. An unusual shape with its risks declared is a passing
   design; the check asks for explicitness, not for a different architecture.
   (A structural change proposed on a **refine** pass, with its reason, is not
   this: put it to the user, and apply it only if they take it.)
5. Fix the acknowledgement itself when check reports `ack-unknown-rule`,
   `ack-without-reason` or `ack-unused` (correct the name, add the reason, delete
   the stale line); these three cannot be acknowledged.

To show the user where the findings sit, draw them: `python3 scripts/bin/sigil view FILE
--once --checks` (or `c` in the live view).

### simulate — run the design while you build it
Sigil does not execute; `sigil view --sim` is the viewer's reading of a design — tokens
moving along its flows, deterministic, no values computed. It is your test harness:
run it to find out what the design does, not only to show the user.
1. `python3 scripts/bin/sigil view FILE --sim all` runs every scenario. `happy` takes every
   default (calls succeed, `?>` skipped, the first member of a race / alternative /
   branch wins); each other row is one deviation — `Caller.verb:fails` / `:fallback`,
   `Src->Dst:fails`, `Node:fails`, `Src?>Dst`, `Src&?Member`, `Src/Member`,
   `header=arm`, `Owner.State-ev->Other`. The last rows are overlap runs, `Entry@t`:
   a later entry started at tick t while an earlier entry's episode still runs, at
   the moments it reaches something that episode is busy with. `--sim list` lists
   them all; `a+b` combines two for a single run (`Builder.claim:fallback+Author@25`).
   After them come the state starts, `Owner=State` (`starts with {Ticket} in Done`):
   that machine begun in a later state, so a way out of it is walked, which a run
   from the initial state may never reach. Any state the owner's block names runs
   by name (not `+` or `$`; an unknown one lists the owner's states) and combines
   with `+` (`Ticket.kind=urgent+Ticket=Done`).
2. Judge each row against the intent: every failure ends somewhere intended (a
   `routes:` entry, a fallback, or a `failed` the user accepts — `failed` with no
   route is a failure nobody handles); machines end in the expected `states:`; a
   fan-out or `&` reaches everyone (no `open:` join, no `waiting:` node); `ignored:`
   events are ones the state should ignore; no `cut` and no `bounds:` the design
   should have stated — a base case, visit limit or spawn cap is a recursion, cycle
   or spawn the design leaves open, and a loop at the cap has no `@times`. To see
   past a bound, rerun with `--limit NAME=N` (e.g. `depth=6`, `frames=5000`); that
   explores further, it never fixes the design.
   Entries run one after another unless a scenario starts one at a tick, so a design
   with two or more entries (two actors, a job and a user) also needs the question
   "what if they happen at once?": read the `Entry@t` rows, try other ticks by name
   (`--once --sim Author@40`; the log leads each sentence with its episode, `ep2:`),
   and run `sigil check --mode spec` (or `--overlaps all`), which starts each later
   entry at every tick of an earlier one's episode and names the run where two
   entries race (two writers, an event landing in a state that exists only
   mid-episode). That sweep is the exhaustive pass, made once before a spec is
   final: in sketch and craft `sigil check` skips overlap runs (`--overlaps off`), so
   checks on every edit stay quick. `--overlaps listed` tries only the listed
   `Entry@t` runs, and `--overlaps N` caps the sweep.
3. A surprising row: `--once --tree --sim NAME` draws its last frame and prints the
   run in plain words, one `tNNN …` line per step; find where the run diverged from
   the intent, and quote those lines to the user (`--sim NAME --json` has them as
   `steps`, with the raw `log`).
4. Propose the Sigil change (or ask) in the design's own terms; once it is made,
   `--sim all` again and diff against the previous table. The simulator's own
   choices (bounds, written order, ticks, frame counts) are not the design's
   behaviour — don't present them as such; a frame count moving is not a regression.

The user can watch the same runs live: `python3 scripts/bin/sigil view FILE`, then `x`
(space play / pause, `,` `.` a frame, `<` `>` an event, `[` `]` scenario, `-` `+`
speed from ¼ to 32 frames/s, starting at 2). Every view narrates the run the same
way: the path of hops so far (numbered by branch, `✖` a failed hop), the last few
events and a line saying what is happening now. The view follows the run (`w` turns that off).

### export — hand a final spec to whoever builds it
`sigil export` writes a final spec as a build skeleton. Export only when the
user says the design is final: a `#!spec` document that lints clean and passes
`sigil check --export` (spec mode, overlap runs included) with no error or warning left
unacknowledged. The tool enforces that gate itself.
1. Run `python3 scripts/bin/sigil check FILE --export` first. Its two extra rules are about
   the export's shape: `no-home` (SGC401, a component written in two systems,
   neither enclosing the other) and `untyped-boundary` (SGC402, a flow across a
   system boundary with no payload, or a call across one with no `=> return`).
   Resolve them as any finding — ask the user, then declare or acknowledge; never
   reshape. Systems are each `X := { … }` expansion, each composition-tree root,
   and the top level (named after the file, or `--name NAME`); "Ready to export" in
   `references/language.md` has the rules. To make a root service the project
   itself, name the file after it (`[Shop]` in `shop.sigil`, or `--name shop`): its
   tree or expansion is then the top level, not a second system. Declare each part
   in one unit (a line of its own, a tree, a modifier line) and only name it in the
   flows of the others: a level that only reaches a part, or names it in passing (a
   `branch on {X}.f` subject, an arm, a borrow, a join), is never its home, so
   `no-home` asks only about parts declared in two sibling units. Data a flow
   carries counts as a dependency: a payload naming a homed `{D}` makes both ends
   depend on `{D}`'s system. Descriptions come from the `#` comments:
   a header comment needs a blank line after it to describe the top system, or it
   describes the first statement's node. A trailing comment describes its line's
   first node, and a comment-only line aligned under it continues it. A
   comment-only line indented under a statement line with no comment (and no `{`
   opening a block) is that line's trailing comment, not the next statement's
   header; at the statement's own column it is the next one's. `# accepts:`
   lines show under the component's Requirements.
2. `python3 scripts/bin/sigil export FILE --out DIR`. If it exits 2 it prints what blocks
   it (lint errors, findings, a non-spec mode line) and writes nothing; take those
   back to the user like any finding.
3. What the folder means: one folder per system, one `.md` per component (kind,
   description, interface, requirements, lifecycle, as the spec states them —
   no target-language types), `system.json` the same as data, `README.md` the
   index. **`manifest.json` is the contract**: per system its interface hash (the
   flows across its boundary), body hash (everything in it), components, each
   component's interface and body hash, depends_on (its own flows) and parent (the
   enclosing system); with a dialect loaded, the
   dialect's name and version. `system.json` adds each component's and flow's spec
   `lines` and the system's `#&` declarations. No hash reads line numbers or the
   top system's name. The manifest is written last, so a folder without it is no
   finished export.
4. After the spec changes, export again into the same DIR (`--dry-run` first to
   preview). The delta (printed, and in `delta.json`, which every export writes; a
   first export lists every system as `added`; `--json` for data) is the work
   to redo: `rebuild` systems changed inside; `recheck` systems are unchanged but
   depend on one whose interface moved, so their calls into it need a second look
   (or sit inside a system that depends on it from outside itself: `X (via Outer)`);
   `added` / `removed` are new or gone; `unchanged` need nothing. Reformatting or
   reordering the spec changes no hash. Tell the user these lists.
5. Building against the export happens outside sigil: `sigil export` writes the folder
   and stops. Don't run a build loop, track who builds what, or keep a ledger of
   it here; a builder's own files in a system folder are left alone on re-export.

### view / Mermaid — show the shape
For a quick look in the conversation, run `python3 scripts/bin/sigil view FILE --once` and show
the drawing in a plain code block, in the view that fits (see **Which view**) and
saying which and why. When the user wants a diagram for docs, run
`python3 scripts/bin/sigil export FILE --mermaid` and present Mermaid; before an export,
`--spine` shows the systems it would make. If the graph gets crowded (more than
~40 nodes or 3 levels), show one section at a time with a lower `--depth`.

## Pitfalls

- Wrong glyph kind: `{Order}` is the record, `[OrderSvc]` the component,
  `<OrderPlaced>` the event.
- `->` calls, `=>` produces; `~>` is async; `!>` is only for failure paths.
  A call's route can go on its own line or after its payload or return on the call
  line (`[A] -> [B] : run({X}) => {Y} !> <Fail>`): both are the call's route. With
  no payload or return before it, `[A] -> [B] !> <E>` is `[B]`'s route instead.
- A line starting with an arrow continues the previous line's *subject*.
- `&` is a strict join; use `&?` for a race.
- "Has" / "made of" is a composition branch (`\-& {Health}`), not a flow; a branch
  never carries traffic.
- No `;` separators, no reverse arrows, no prose verbs between glyphs, no
  invented keywords or modifiers.
- One name is one entity everywhere in a document: a component named the same in
  two expansions is a single component, wired into both.
- Wire a caller to the part it uses from an outer level, but call a sibling unit,
  not its part: the simulator runs everything behind a coarse edge, and a part
  named in two sibling units has no home.
- A send that happens only sometimes is `?>`, not `~>`. Every plain send fires in
  the happy run, so a happy run where alternatives all fire is not the system's
  happy path (an order both built and pruned).
- Sigil models wiring, not algorithms or data-structure internals — keep a
  component's internals opaque and point to prose or code for them.
