---
name: sigil
description: Sigil is a compact, non-executable notation for system designs — glyphs like [Component], {Data}, <Event>, (Actor), |Store| wired with arrows like ->, ~>, =>, !>. Use whenever the user wants to (1) compress a design or prose spec into Sigil; (2) expand Sigil into prose; (3) compare two designs structurally; (4) tighten or normalize hand-written Sigil; (5) craft a design iteratively ("help me design X", or a craft-mode document); (6) lint or validate a .sigil document (bundled scripts/lint.py); (7) draw a Sigil document as a terminal graph (scripts/view.py) or a Mermaid diagram (scripts/render.py); (8) mentions Sigil, glyphs, or writes bracket-and-arrow notation; (9) describes architectures, state machines, data flows, workflows or pipelines where a compact notation clarifies the design. Prefer Sigil over prose for architecture once it has been introduced.
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
(e.g. `/tmp/doc.sigil`) first; `lint.py` and `render.py` also accept `-` for stdin.

| Task | Command | Result |
| --- | --- | --- |
| Validate | `python3 scripts/lint.py FILE` | one `severity:line:rule: message` per issue; exit 0 clean, 1 warnings, 2 errors |
| Draw in the terminal | `python3 scripts/view.py FILE --once [--depth N\|all] [--payloads] [--no-lint]` | box-drawing graph + lint summary; exit 1 on lint error |
| Show comments | `python3 scripts/view.py FILE --once --notes markers` (`--notes callouts` in `--tree`) | commented nodes tagged `#N`, notes listed (or drawn as margin boxes) |
| Hierarchy + wiring | `python3 scripts/view.py FILE --once --tree [--compact]` | composition tree as an outline, each flow as a lane (`●` source, `◀` targets) + legend; `--compact` drops the blank row between top-level units |
| Live view for a human | `python3 scripts/view.py FILE` | full-screen view that redraws on every save (tell the user to run it in their own terminal); keys: `t` tree/graph, `n` notes, `e` triggers, `s` spacing, `d` depth, `p` payloads, `l` lint, `c` centre, `g` home, `r` reload, `q` quit |
| Mermaid diagram | `python3 scripts/render.py FILE [--depth N\|all] [--composition subgraphs\|edges\|none]` | `flowchart TD` source; present it in a fenced `mermaid` block. Composition trees draw as subgraphs by default |

`--depth 0` shows the top level only, `1` (default) opens direct `:=` expansions,
`all` opens everything — keep `all` for small documents. If a dialect is in use
(see "Dialects" in `references/language.md`), pass `--dialect NAME` or set
`SIGIL_DIALECT`; plain Sigil needs neither.

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

Keep the craft document in a file and rewrite that file after every change: a user
running `python3 scripts/view.py FILE` in a side pane sees the graph redraw live, and
you check the same drawing with `python3 scripts/view.py FILE --once` before replying.

### lint — validate
Run `python3 scripts/lint.py FILE`. Report each diagnostic with a suggested fix
(the rule ID and message explain the problem; `references/language.md` has the
rule). Surface issues before rewriting — let the user decide.

### view / render — show the shape
For a quick look in the conversation, run `python3 scripts/view.py FILE --once` and show
the drawing in a plain code block. When the user wants a diagram for docs, run
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
