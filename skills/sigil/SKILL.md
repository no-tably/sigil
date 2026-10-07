---
name: sigil
description: Sigil is a compact, non-executable notation for system designs — glyphs like [Component], {Data}, <Event>, (Actor), |Store| wired with arrows like ->, ~>, =>, !>. Use whenever the user wants to (1) compress a design or prose spec into Sigil; (2) expand Sigil into prose; (3) compare two designs structurally; (4) tighten or normalize hand-written Sigil; (5) craft a design iteratively ("help me design X", or a craft-mode document); (6) lint or validate a .sigil document (bundled scripts/lint.py), or check whether its design declares how its risks are handled (scripts/check.py); (7) draw a Sigil document as a terminal graph (scripts/view.py) or a Mermaid diagram (scripts/render.py); (8) mentions Sigil, glyphs, or writes bracket-and-arrow notation; (9) describes architectures, state machines, data flows, workflows or pipelines where a compact notation clarifies the design. Prefer Sigil over prose for architecture once it has been introduced.
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

All scripts are Python 3 standard library only. Write the document to a file
(e.g. `/tmp/doc.sigil`) first; `lint.py`, `check.py` and `render.py` also accept `-` for stdin.

| Task | Command | Result |
| --- | --- | --- |
| Validate | `python3 scripts/lint.py FILE` | one `severity:line:rule: message` per issue; exit 0 clean, 1 warnings, 2 errors |
| Check the design | `python3 scripts/check.py FILE [--mode sketch\|craft\|spec] [--k N] [--json] [--all]` | composition findings, one `severity:line:SGCnnn: name: message` each (in craft the message is a question), then `accepted:line:SGCnnn: name: reason` per acknowledged one; `--json` adds each rule's why and the declaration that satisfies it; `--rules` lists the rules; exit codes as lint |
| Both at once | `python3 scripts/lint.py FILE --deep` | lint diagnostics and check findings merged by line, acknowledged findings last; exits with the worse of the two codes |
| Draw in the terminal | `python3 scripts/view.py FILE --once [--depth N\|all] [--payloads] [--mods] [--access] [--no-lint]` | box-drawing graph + lint summary; exit 1 on lint error; control blocks as titled frames, joins as bars, sections as dividers; `--mods` modifier chips, `--access` the permission graph (`r` / `w` / `b` heads, `1w` / `Nw` writer badges) |
| Show comments | `python3 scripts/view.py FILE --once --notes markers` (`--notes callouts` in `--tree`) | commented nodes tagged `#N`, notes listed (or drawn as margin boxes) |
| Call graph, left to right | `python3 scripts/view.py FILE --once --flow [--payloads]` | bare glyph labels in columns by call depth, a node's first callee on its row (`[API] ─┬─▶ [Payments]`, `├─✖ <Failed>`); one row per callee, so it reads like a call tree and is usually the shortest drawing; `--sim` / `--checks` work here too |
| Hierarchy + wiring | `python3 scripts/view.py FILE --once --tree [--compact]` | composition tree as an outline, each flow as a lane (`●` source, `◀` targets) + legend; `--compact` drops the blank row between top-level units |
| Live view for a human | `python3 scripts/view.py FILE` | full-screen view that redraws on every save (tell the user to run it in their own terminal); keys: `1` `2` `3` graph / flow / tree, `t` the next view, `x` sim mode (in it: space play / pause, `,` `.` step, `[` `]` scenario, `-` `+` speed), `n` notes, `e` triggers, `v` events (where they land / as nodes), `s` spacing, `f` fit to the window / natural layout with free pan, `c` checks overlay, `d` depth, `p` payloads, `m` modifiers, `a` access, `l` lint, arrows / `h j k L` or mouse drag / wheel pan, `z` centre, `g` home, `r` reload, `q` quit |
| Run every pathway | `python3 scripts/view.py FILE --sim all [--json]` | no drawing: per scenario `NAME outcome N frames label`, then indented facts — `states:` each machine's end state, `failed:` what failed (`↩ fallback`, `critical`), `routes:` failure routes taken, `ignored:` events a state had no transition for, `waiting:` nodes left blocked, `open:` joins left open, `bounds:` a base case, visit limit, spawn cap, loop at the cap or cut — then `N scenarios: a ok, b failed, c cut`; always exit 0. `--sim list`: the scenario names and labels |
| Walk one pathway | `python3 scripts/view.py FILE --once --tree --sim SCENARIO` | the run's last frame over the drawing (`✕` failed, `◉` a machine's state, wires taken vs never taken), then `sim NAME (label): ok\|failed\|cut · N frames` and the run in plain words, one `tNNN …` line per step (`[API] calls [Payments] with charge(total) — attempt 2 of 4`, `[API] routes the failure to <PaymentFailed>`); exit 2 for an unknown scenario, listing the known ones. `--sim SCENARIO --json` (no drawing): the run's facts, `steps` [{frame, tick, text}] and the raw `log` |
| Mark the findings | `python3 scripts/view.py FILE --once --checks [--tree]` | the check findings marked on the drawing, a checks legend, then each finding's question after lint |
| Show it to the user | the plugin's viewer tool — Claude Code: `view` (`mcp__sigil__view`); pi: `sigil_view` — with `file`, `view` graph\|tree\|flow, `depth`, `scenario`, `frame` N\|last, `play` | a live viewer the user watches (a pane or widget, or a herdr / tmux / zellij split) that redraws on every save; the reply gives the summary, lint and the run's step at that frame, never the drawing. See **Showing the user** |
| Mermaid diagram | `python3 scripts/render.py FILE [--depth N\|all] [--composition subgraphs\|edges\|none]` | `flowchart TD` source; present it in a fenced `mermaid` block. Composition trees draw as subgraphs by default |

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
  (`scenario`, then `frame` or `play`). The viewer redraws on every save, so
  don't call it after each edit. It draws in a pane (Claude Code) or a widget
  above the editor (pi). Inside herdr, tmux or zellij it opens a split running
  the live view instead. If the reply says the viewer is waiting (the terminal
  is narrower than 144 columns), tell the user they can open it with
  `/sigil-pane` in Claude Code or `/sigil` in pi. If it says there is no UI, or
  the tool fails, use `--once`.
- **A multiplexer split**, everywhere else (Codex, OpenCode), or when the user
  prefers it. Ask the user to run `python3 scripts/view.py FILE` in a split or a
  second terminal. If you can open the split yourself, do: `tmux split-window -h
  'python3 scripts/view.py FILE'`, or `zellij run --direction right -- python3
  scripts/view.py FILE`. In herdr, run `herdr pane split`, then `herdr pane run`
  on the new pane. It redraws on every save, and its keys are in the table above.
- **`--once`**, for you, or when the drawing belongs in your reply. It prints one
  drawing as text. Read it yourself to check the shape, or paste it into a code
  block when the user asked to see it here, or can't run a live view. It is also
  the way to see a run's frame yourself: the viewer tool never returns the
  drawing.

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
7. Emit in Sigil Normal Form, then run `python3 scripts/lint.py` and fix what it reports.

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
`python3 scripts/lint.py`.

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
`python3 scripts/view.py FILE` in a split. Use `--once` output only when the drawing
itself belongs in your reply.
After each substantive change, test-drive it before replying:
1. `python3 scripts/lint.py FILE --deep` — lint plus the composition checks (see
   **check**); put the findings' questions to the user alongside your next step.
2. `python3 scripts/view.py FILE --sim all` — run every pathway (see **simulate**)
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
`python3 scripts/view.py FILE --once` before replying. Before promoting to `#!spec`,
run `python3 scripts/check.py FILE --mode spec` and resolve every error.

### lint — validate
Run `python3 scripts/lint.py FILE`. Report each diagnostic with a suggested fix
(the rule ID and message explain the problem; `references/language.md` has the
rule). Surface issues before rewriting — let the user decide. Fix lint errors
before reading check findings (`--deep` shows both): a malformed line can explain
a finding.

### check — does the design say how its risks are handled?
`scripts/check.py` asks of a design what lint cannot: an external call with no
timeout, a retry on a write with no idempotency, two writers on one store, a failure
with no route, a race, an event nothing handles, an unbounded recursion. A finding
never forbids a shape; it names a risk the document leaves undeclared. Run it in
**craft** (findings are `warn` questions) and **spec** (findings of binding rules
are errors); in sketch they are hidden (`--all` shows them).
1. Run `python3 scripts/check.py FILE` (or `lint.py FILE --deep`). For a rule's
   rationale and the declarations that satisfy it, use `--json` (`why`, `fix`).
2. Put each finding to the user **as its question** (craft prints it; in spec turn
   the statement into one), in the design's own terms, and let the user answer.
   A finding marked `(guessed: …)` rests on a guess about a name — say so.
3. Resolve it in one of two ways only:
   - **declare** the handling in the notation the spec already has — `@timeout(t)`,
     `@deadline(t)`, `×N` with `@after(…)`, `@fallback(x)`, a `!>` route, a
     recognised `@inv` (`idempotent(key)`, `atomic(…)`, `cas(field)`,
     `depth <= N`, …), `@owns |S|`, `@read(…)` / `@write(…)`, a `^N` bound, an
     `@sla`, a `?>` exit, a terminal state `$`, a consumer for an event — whatever
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
5. Fix the acknowledgement itself when check reports `ack-unknown-rule`,
   `ack-without-reason` or `ack-unused` (correct the name, add the reason, delete
   the stale line); these three cannot be acknowledged.

To show the user where the findings sit, draw them: `python3 scripts/view.py FILE
--once --checks` (or `c` in the live view).

### simulate — run the design while you build it
Sigil does not execute; `view.py --sim` is the viewer's reading of a design — tokens
moving along its flows, deterministic, no values computed. It is your test harness:
run it to find out what the design does, not only to show the user.
1. `python3 scripts/view.py FILE --sim all` runs every scenario. `happy` takes every
   default (calls succeed, `?>` skipped, the first member of a race / alternative /
   branch wins); each other row is one deviation — `Caller.verb:fails` / `:fallback`,
   `Src->Dst:fails`, `Node:fails`, `Src?>Dst`, `Src&?Member`, `Src/Member`,
   `header=arm`, `Owner.State-ev->Other`. `--sim list` lists them; `a+b` combines two
   for a single run.
2. Judge each row against the intent: every failure ends somewhere intended (a
   `routes:` entry, a fallback, or a `failed` the user accepts — `failed` with no
   route is a failure nobody handles); machines end in the expected `states:`; a
   fan-out or `&` reaches everyone (no `open:` join, no `waiting:` node); `ignored:`
   events are ones the state should ignore; no `cut` and no `bounds:` the design
   should have stated — a base case, visit limit or spawn cap is a recursion, cycle
   or spawn the design leaves open, and a loop at the cap has no `@times`. To see
   past a bound, rerun with `--limit NAME=N` (e.g. `depth=6`, `frames=5000`); that
   explores further, it never fixes the design.
3. A surprising row: `--once --tree --sim NAME` draws its last frame and prints the
   run in plain words, one `tNNN …` line per step; find where the run diverged from
   the intent, and quote those lines to the user (`--sim NAME --json` has them as
   `steps`, with the raw `log`).
4. Propose the Sigil change (or ask) in the design's own terms; once it is made,
   `--sim all` again and diff against the previous table. The simulator's own
   choices (bounds, written order, ticks, frame counts) are not the design's
   behaviour — don't present them as such; a frame count moving is not a regression.

The user can watch the same runs live: `python3 scripts/view.py FILE`, then `x`
(space play / pause, `,` `.` a frame, `<` `>` an event, `[` `]` scenario, `-` `+`
speed from ¼ to 32 frames/s, starting at 2). Every view narrates the run the same
way: a trail of the hops so far, the last few events and a line saying what is
happening now. The view follows the run (`w` turns that off).

### view / render — show the shape
For a quick look in the conversation, run `python3 scripts/view.py FILE --once` and show
the drawing in a plain code block (`--flow` for a call graph read left to right: one
row per callee, usually the shortest drawing). When the user wants a diagram for docs, run
`python3 scripts/render.py` and present Mermaid. If the graph gets crowded (more than
~40 nodes or 3 levels), show one section at a time with a lower `--depth`.

## Pitfalls

- Wrong glyph kind: `{Order}` is the record, `[OrderSvc]` the component,
  `<OrderPlaced>` the event.
- `->` calls, `=>` produces; `~>` is async; `!>` is only for failure paths.
- A line starting with an arrow continues the previous line's *subject*.
- `&` is a strict join; use `&?` for a race.
- "Has" / "made of" is a composition branch (`\-& {Health}`), not a flow; a branch
  never carries traffic.
- No `;` separators, no reverse arrows, no prose verbs between glyphs, no
  invented keywords or modifiers.
- Sigil models wiring, not algorithms or data-structure internals — keep a
  component's internals opaque and point to prose or code for them.
