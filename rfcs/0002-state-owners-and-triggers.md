# RFC 0002 — State-machine owners and event triggers

- **Status:** Accepted 2026-09-30 (owner sign-off)
- **Date:** 2026-09-30
- **Spec:** language.md "State machines (and lifecycle)" (owners, triggers,
  narrowing, typo hint) · grammar `state-block` · the glyph table's "component"
  wording · examples.md Example N
- **Tools:** render.py (`STATE_HEAD_RE`, `Graph.triggers`, Mermaid `triggers`
  edges), lint.py (SGL090 inside any-owner blocks, SGL091 typo hint), view.py
  (trigger lanes, `e` toggle, state labels, graph-mode trigger list)

## Problem

1. **Only records could have states.** The header took a bare name
   (`state {Order}`) and tools assumed a `{Data}` owner. A component's own modes,
   such as a checkout service going idle → busy → draining, could not be written.
2. **Causation was invisible.** A transition names its trigger (`-<Paid>->`), and
   a flow raises an event (`[Payments] ~> <Paid>`), but nothing tied the two
   together. "Payments settles the order" could be read only by eye.
3. **`[X]` was described as "service"** while being used for modules, widgets,
   systems and ECS entities. The narrower word misled.

## Design

- **Any glyph owns a state machine:** `state <glyph> { … }`, e.g.
  `state {Order}`, `state [Checkout]`, `state |Queue|`. The machine hangs off its
  owner, like an expansion. If the owner also has a `:=` expansion, the machine
  nests inside it.
- **Events drive transitions by name.** An event glyph whose name matches a
  trigger (case-insensitive) is that trigger. There is no new syntax. A trigger
  with no matching event stays valid and names an outside cause.
- **Narrowing.** If an event has explicit flows to state-machine owners
  (`<Paid> -> {Order}`), only those owners' machines react to it. With no such
  flows, the event drives every machine naming the trigger.

  ```
  [Payments] ~> <Paid>
  <Paid> -> {Order}          # {Order} reacts; [Checkout]'s -<Paid>-> does not
  ```
- **Typo hint.** Lint SGL091 (info): a trigger that matches no event but is a likely
  typo of one (edit distance ≤ 1, or ≤ 2 for names of five or more characters,
  case-insensitive) — "trigger <Payed> matches no event; did you mean <Paid>?".
  Otherwise silent, since machines may be driven from outside the document.
- **Drawing the link.**
  - Mermaid: a dotted `triggers` edge from the event into the state the transition
    enters. It points at the owner instead when the machine is collapsed at the
    current depth.
  - Tree view: a dashed lane in the event's colour from the event row into that
    state row. Each state row lists its incoming triggers. `e` toggles these lanes.
  - Graph view: a `triggers` list (`<Paid> ⇢ [Checkout]: Busy → Idle`), because
    the event and its states are drawn in different sections.
  - *(Later: the graph view also draws a dashed edge event ⇢ owner, alongside the list.)*
  - All three respect narrowing.
- **`[X]` is a component.** A service is one kind of component. The glyph table,
  pitfall 1, the skill and the viewer legend say "component".

## Compatibility

- `state {Name} { … }` is unchanged; it's the `{…}` owner case.
- Mermaid output changes only by adding `triggers` edges, and only in documents
  where an event name matches a trigger. Narrowing removes edges only where a
  document already had an explicit event → owner flow.
- The internal node kind stays `service`, so existing Mermaid classes and dialect
  hooks are untouched. Only the words change.

## Decisions

1. **Case-insensitive matching.** *Exact instead, with a lint note for near
   misses?* Matching stays case-insensitive. *Rationale:* existing documents mix
   `-<submit>->` with `<Submit>`; case is not a meaningful difference between
   events.
2. **A lint note for unfired triggers.** *An info hint when a trigger matches no
   event?* Only for likely typos: SGL091 (info), edit distance ≤ 1 (≤ 2 for 5+
   characters), with a "did you mean" suggestion; silent otherwise. *Rationale:*
   catches the real mistake without flagging machines deliberately driven from
   outside the document.
3. **Qualified targets.** *Should a flow aim an event at one owner
   (`<Paid> -> [Checkout]`)?* Yes, by narrowing: explicit event → owner flows
   restrict which machines react; without them every machine naming the trigger
   reacts. *Rationale:* reuses an ordinary flow instead of new syntax, and keeps the
   broadcast default for the common case.
4. **Any glyph as owner, `[X]` as component.** Accepted as implemented.
   *Rationale:* modes belong to components and stores as much as to records.
