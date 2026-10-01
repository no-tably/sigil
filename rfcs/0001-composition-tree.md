# RFC 0001 — Composition trees

- **Status:** Accepted 2026-09-30 (owner sign-off)
- **Date:** 2026-09-30
- **Spec:** language.md "Composition trees" (relations, qualified paths, rendering) ·
  grammar `comp-tree` / `branch` / `weight` / `path` · pitfalls 15 and 19 ·
  examples.md Examples M and O
- **Tools:** render.py (`Graph.tree`, `--composition subgraphs|edges|none`),
  lint.py (SGL110, SGL111, SGL112), view.py `--tree`

## Problem

Core Sigil describes wiring well: flows are a DAG between components. It has no
way to say what something is *made of*. `X := { … }` zooms into how a component
works (its internal flows), but it is untyped containment, and it cannot say "the
ship **has** a health component", "the ship **spawns** bullets", or "a shard exists
**only once** the asteroid shatters".

Many designs are a hierarchy and a network at the same time: entity-component
systems (entities → components, prefabs → spawned instances, systems wired to
components), UI component trees, deployment topology, fan-out/fan-in services,
failover pairs, org structures, scene or document graphs. Written as flows alone,
`[Ship] -> {Health}` claims the ship *calls* its health. Written as prose, the
structure is lost to tools.

A dialect of Sigil already had this shape. Its self-describing layout uses an
indented tree whose children start with `\-<arr>`, where the arr chooses the
relation. Part of that arr set is layout for a UI surface (down, across, grid,
popover, drop). The rest describes system composition and is general.

## Design

Composition trees are core. Every relation with real system-composition meaning
lives in core; only layout, UI and similar host-specific relations stay in a
dialect.

```
[Ship]
    \-& {Transform}              # has
    \-*-> [Bullet]               # spawns instances (contains)
        \-& {Damage}
[Asteroid]
    \-{shattered}-? [Shard]      # present only when a condition holds
[Search]
    \-*-= [ShardQuery] ×N        # spawns and gathers their results
[Router]
    \-(3)-> [ZoneA]              # weight 3 : 1
    \-(1)-> [ZoneB]
[Physics] -> {Transform}         # wiring stays in flows
[Homing]  -> [Bullet]/{Transform}  # a path: only the Transform under a Bullet
```

**Branch marker.** `\-  [*-]?  [(N)- | {cond}-]?  REL`, or the bare spawn `\-*`.

| REL | Reads as | Meaning |
| --- | --- | --- |
| `>` | contains | a part owned by the parent (default relation) |
| `&` | has | a component or mixin carried by the parent |
| `?` | when | present only while a condition holds |
| `$` | from data | children produced from data at run time |
| `@` | attached | wired into the parent at run time (sidecar, plugin) |
| `!` | alerts when | a monitor, alarm or assertion on the parent, active while a condition holds |
| `=` | gathers | the children's results are reduced back into the parent (scatter/gather, fork-join) |
| `_` | one of | exactly one sibling in the `_` group is active at a time (active/standby, blue/green, strategy) |

**Prefixes.** `*-` spawned instances (many, created at run time). `(N)-` a weight:
a relative share among siblings (traffic split, capacity, priority), not a count.
`{cond}-` names the condition or data source; its name is `[A-Za-z0-9_-]+`, so
write `{lagging}-!`, not `{lag>5s}-!`. `(N)-` and `{cond}-` are alternatives.
Cardinality stays `×N` on the child's line.

**Qualified paths.** `path := glyph ('/' glyph)+`, with no spaces around `/`. Each
step is a direct parent → child branch, and a path matches as a suffix of an
occurrence's ancestor chain: `[Bullet]/{Transform}` matches under any Bullet,
`[Ship]/[Bullet]/{Transform}` is fully qualified. A bare name still means every
occurrence. A path may be a flow's source or destination. `/` with spaces keeps its
old meaning (`{Resp} / {Err}` alternatives). Lint SGL112 (warn): a path that
matches no occurrence.

**Semantics.** Depth is indentation. An inline branch sits on the parent's line
(`[Log] \-& {Scrollable}`). Branches add no flow edges. The same name under several
parents is the same kind composed into each; a flow naming it applies to every
occurrence, which is exactly an ECS query, and a path narrows it. Markers count only
at line start or right after a parent glyph, so `\-` in prose, comments or payloads
stays text.

**Dialect hooks.** `COMPOSITION_RELATIONS` adds relation characters;
`COMPOSITION_LINT = False` hands validation to the dialect; `MERMAID_COMPOSITION`
sets the Mermaid default. A dialect may read a core relation with a host meaning
(a UI dialect can draw `_` as tabs), but it does not change the core meaning.

## Rendering

**Mermaid (render.py).**

- Default, **subgraphs**: a parent with branches becomes a `subgraph`, and every
  occurrence is its own node (for example `Ship_service__Transform_data`). A flow to
  a bare name fans out to every occurrence; a path flow reaches the matching ones.
  A parent that also has a `:=` expansion keeps it as a nested "internals" subgraph.
- `--composition edges`: one node per name, `parent -. "<relation word>" .-> child`.
- `--composition none`: no composition, the previous output.

**Terminal (view.py --tree).** There are established ways to draw a graph that is
both hierarchy and network: compound or clustered graphs, hierarchical edge
bundling, and an outline with a lane gutter (in the spirit of `git log --graph`).
The first does not survive a terminal once edges cross box borders, the second
needs pixels, and the third keeps the tree readable as text, so the viewer uses it:

- The composition tree, with `:=` expansions and state machines nested to the
  current depth, is an outline.
- Every flow is a vertical lane. `●` marks its source row and `◀` each target row.
  A flow to a repeated name taps every occurrence; a path flow taps only the
  matching ones.
- Lanes are interval-packed into as few columns as possible. A row hops over
  lanes it only crosses (`─│─`), so a joint (`┬ ┴ ┤ ┼`) always means a real
  connection.
- Lanes take their colour from the source node's type, and strokes follow the
  arrow type (`╌` async, `━` produces, `┄` conditional, red for error paths).
- Keys: `e` toggles trigger lanes, `s` toggles spacing between top-level units
  (on by default; `--compact` starts with it off); the legend lists every key.

## Compatibility

- **Core documents without `\-`:** unchanged.
- **Core documents with composition:** Mermaid now draws it as subgraphs by
  default; `--composition none` restores the previous output.
- **Dialect documents:** a dialect that sets `MERMAID_COMPOSITION = "none"` keeps
  its Mermaid output unchanged unless composition is asked for.
- **`!`, `=`, `_`, `(N)-`** were dialect-only. They are now core, with the meanings
  above. A dialect that already used them keeps reading them with its host meaning
  (for example tabs for `_`, flex weight for `(N)-`).

## Decisions

1. **Qualified references.** *Should a path form target one occurrence?* Yes:
   `glyph('/'glyph)+`, direct steps, suffix match, usable as a flow's source or
   destination, SGL112 for a path that matches nothing. A bare name still means
   every occurrence. *Rationale:* systems that reuse a component kind need to wire
   one occurrence without renaming it.
2. **`$` and `@` in core.** *Keep them, or keep only `> & ?` plus `*-`?* Keep both.
   *Rationale:* children-from-data and run-time attachment are system-composition
   logic (dynamic sets, sidecars, plugins), not UI.
3. **More relations in core** (raised at sign-off). `!` alerts when, `=` gathers,
   `_` one of, and the `(N)-` weight move to core; `+ # ^ v` stay in the dialect.
   *Rationale:* the promotion rule is that everything with real system-composition
   logic goes to core, and only UI, prompt and agent-specific relations stay in a
   dialect. Alarms, fork-join, failover and traffic weights are system concepts;
   across, grid, popover and drop are layout.
4. **Mermaid.** *Emit composition, as subgraphs or as dotted edges?* Both: subgraphs
   per occurrence by default, `--composition edges` for one node per name, and
   `--composition none` for the old output. A dialect may change the default.
   *Rationale:* subgraphs show structure directly, and nesting a `:=` expansion as an
   "internals" subgraph resolves the collision.
5. **Cardinality.** *Does a branch want its own count?* No: `×N` on the child's
   line stays the count, and `(N)-` is a weight, never a count.
   *Rationale:* one count token serves both flows and trees, and a share is not a
   count.
