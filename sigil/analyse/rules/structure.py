"""
rules.structure — Sigil structure checks: does the design read as units that
stand apart and scan at a glance?

A rule module for sigil.analyse.check, loaded with the core modules wherever it
ships (check.STRUCTURE_MODULES): `rules(ck)` returns this module's `ck.Rule`s,
where `ck` is sigil.analyse.check itself (passed in, so this module never imports
it). The playground ships neither this module nor the reading it reads
(sigil.model.structure imports the export model), so a playground check runs
without these rules and their names stay known (check.CORE_NAMES). Rules
(advisory):

    SGC176 unit-cycle    sibling units (neither encloses the other) whose flows
                         depend on one another in a cycle: info in sketch and
                         craft, warn in spec; acknowledged on the header of any
                         unit in the cycle (never document-wide)
    SGC177 large-unit    a unit with more than structure.LARGE built members
                         (actors never count): info in craft and spec, hidden
                         in sketch

Both read the structure reading's units (sigil.model.structure.units_of: the
export model's systems), so `sigil view --structure` lists exactly what these
rules find: its cycles are SGC176's, its "units over 9" SGC177's. A flow from a
unit into one enclosing it (an `up` line of the reading) is never a finding. A
part written in two units with no home is the export model's SGC401 (`sigil
check --export`); this module adds no second rule for it.

Standard library only. Deterministic: the model's order, never set order.
"""

from __future__ import annotations


TOP_STEM = "top"                     # the top unit's key; never shown


def units_of(doc):
    """The structure reading's units of a check's document, built once and kept on
    it (sigil.model.structure.units_of, imported on first use)."""
    found = doc.__dict__.get("_structure_units")
    if found is None:
        from sigil.model import structure
        found = doc.__dict__["_structure_units"] = structure.units_of(
            doc.graph, TOP_STEM, getattr(doc.dialect, "NODE_KINDS", None) or {})
    return found


def _structure():
    from sigil.model import structure
    return structure


# ---------------------------------------------------------------------------
# Wording (pure)
# ---------------------------------------------------------------------------

def unit_name(key: str, top: str) -> str:
    return "the top level" if key == top else f"`{key}`"


def unit_list(keys, top: str) -> str:
    """`A`, `B` and `C`."""
    names = [unit_name(k, top) for k in keys]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def link_text(k) -> str:
    """`A` → `B` by `[P] -> [Q]` (line 4), … (the first two flows, then a count)."""
    flows = [f"`{f.text}` (line {f.line})" for f in k.flows[:2]]
    more = len(k.flows) - 2
    tail = f" and {more} more" if more > 0 else ""
    return f"`{k.src}` → `{k.dst}` by {', '.join(flows)}{tail}"


def unit_line(u, doc) -> int:
    """Where a unit's finding is said: its header, else the first statement."""
    return u.line or doc.layout.first or 1


# ---------------------------------------------------------------------------
# SGC176 unit-cycle
# ---------------------------------------------------------------------------

def acknowledged_unit(cycle, units: dict, doc):
    """The unit of the cycle whose header an acknowledgement naming unit-cycle
    covers (a document-wide one aside), the first in the model's order; else
    the cycle's first unit. A cycle is one finding, acknowledged on the header
    of any unit in it."""
    acks = [a for a in doc.acks if a.reason and not a.document and "unit-cycle" in a.names]
    for key in cycle.units:
        line = units[key].line
        if line is not None and any(a.covers(line) for a in acks):
            return units[key]
    return units[cycle.units[0]]


def cycle_hit(ck, cycle, units: dict, top: str, doc):
    """One Hit per cycle, on the header of its first unit (the model's order), or
    of the first unit whose header acknowledges it (acknowledged_unit)."""
    first = acknowledged_unit(cycle, units, doc)
    where = unit_list(cycle.units, top)
    links = "; ".join(link_text(k) for k in cycle.links)
    return ck.Hit(
        unit_line(first, doc),
        f"{where} depend on one another in a cycle: {links}",
        f"{where} depend on one another in a cycle ({links}). Are they one part, built "
        "and changed together?",
        anchor=("unit", first.key),
        fix="if they are built and changed together, acknowledge it on the unit's "
            "header (`# accepts: unit-cycle — …`); otherwise move what they both "
            "lean on to the unit that encloses them",
        scopes=(("cycle", " ".join(cycle.units)),))


def find_unit_cycles(ck, doc):
    u = units_of(doc)
    units = {x.key: x for x in u.units}
    for cycle in _structure().sibling_cycles(u):
        yield cycle_hit(ck, cycle, units, u.model.top, doc)


# ---------------------------------------------------------------------------
# SGC177 large-unit
# ---------------------------------------------------------------------------

def large_hit(ck, unit, top: str, limit: int, doc):
    where = unit_name(unit.key, top)
    n = len(unit.members)
    return ck.Hit(
        unit_line(unit, doc),
        f"{where} has {n} members (over {limit}): it does not scan at a glance",
        f"{where} has {n} members. Do some of them form a unit of their own?",
        anchor=("unit", unit.key),
        fix="group the members that work together into an expansion of their own, "
            "or acknowledge the size",
        scopes=(("members", str(n)),))


def find_large_units(ck, doc):
    u = units_of(doc)
    s = _structure()
    for unit in s.large_units(u):
        yield large_hit(ck, unit, u.model.top, s.LARGE, doc)


# ---------------------------------------------------------------------------
# The module's rules
# ---------------------------------------------------------------------------

def rules(ck) -> list:
    return [
        ck.Rule("SGC176", "unit-cycle", "advisory",
                ask="These units depend on one another in a cycle. Are they one part?",
                why="Units whose flows depend on one another cannot be built, tested "
                    "or replaced apart; neither is the other's foundation.",
                fix="acknowledge it on a unit's header when they change together, or "
                    "move what both lean on to the unit enclosing them",
                match=lambda doc: find_unit_cycles(ck, doc), family="17",
                severity_in=(("craft", "info"),), ack_document=False),
        ck.Rule("SGC177", "large-unit", "advisory",
                ask="This unit has many members. Do some form a unit of their own?",
                why="A unit past a handful of built parts no longer reads at a glance; "
                    "a reader has to hold its whole membership to follow one flow.",
                fix="group members that work together into an expansion of their own",
                match=lambda doc: find_large_units(ck, doc), family="17",
                severity_in=(("craft", "info"), ("spec", "info"))),
    ]
